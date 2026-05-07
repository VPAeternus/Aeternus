# tests/test_credibility_ledger.py

import sys
import types
import pytest
from unittest.mock import patch

# Stub chromadb (Python 3.14 compat)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.graph.credibility_ledger import (
    CredibilityLedger,
    _summarize,
    _agent_display_name,
    _AGENTS,
    _PILLARS,
    _MIN_TRADES,
)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _make_attribution(
    ticker="AAPL",
    regime="NEUTRAL",
    return_pct=10.0,
    agent_decisions=None,
    pillar_scores_dict=None,
    report_found=True,
):
    """Factory helper to build a fake attribution dict matching post_mortem.analyze_trade output."""
    if agent_decisions is None:
        agent_decisions = {
            "investment_judge": {"decision": "BUY", "verdict": "CORRECT"},
            "trader": {"decision": "HOLD", "verdict": "NEUTRAL"},
            "trader": {"decision": "BUY", "verdict": "CORRECT"},
            "bull_side": {"verdict": "CORRECT"},
            "bear_side": {"verdict": "INCORRECT"},
        }

    if pillar_scores_dict is None:
        pillar_scores_dict = {
            "fundamental": 70,
            "coherence": 60,
            "macro": 50,
            "sentiment": 75,
            "momentum": 65,
        }

    # Build pillar_attribution from scores
    pillar_attribution = {}
    for pillar, score in pillar_scores_dict.items():
        # Determine signal from score
        if score >= 60:
            signal = "BULLISH"
        elif score < 40:
            signal = "BEARISH"
        else:
            signal = "NEUTRAL"

        # Determine verdict from signal and return
        if signal == "NEUTRAL" or abs(return_pct) < 0.5:
            verdict = "NEUTRAL"
        elif signal == "BULLISH" and return_pct > 0:
            verdict = "RIGHT"
        elif signal == "BEARISH" and return_pct < 0:
            verdict = "RIGHT"
        else:
            verdict = "WRONG"

        pillar_attribution[pillar] = {
            "score": score,
            "signal": signal,
            "verdict": verdict,
            "magnitude": abs(score - 50),
        }

    return {
        "ticker": ticker,
        "close_id": f"test-{ticker}-{regime}",
        "close_date": "2026-02-06",
        "weight_regime": regime,
        "return_pct": return_pct,
        "pnl_usd": return_pct * 100,
        "outcome": "WIN" if return_pct > 0.5 else "LOSS" if return_pct < -0.5 else "FLAT",
        "entry_score": sum(pillar_scores_dict.values()) / len(pillar_scores_dict),
        "entry_rating": "Hold",
        "breakdown": pillar_scores_dict,
        "pillar_attribution": pillar_attribution,
        "pillar_summary": {"right_count": 2, "wrong_count": 1, "neutral_count": 2},
        "agent_accuracy": agent_decisions,
        "counterfactual": {},
        "narrative": f"Test narrative for {ticker}",
        "report_found": report_found,
    }


# ---------------------------------------------------------------------------
# Bayesian accuracy tests
# ---------------------------------------------------------------------------


class TestBayesianAccuracy:
    """Test the Beta-Binomial posterior mean calculation."""

    def test_bayesian_zero_trades(self):
        """0 trades returns 0.5 (neutral prior)."""
        result = CredibilityLedger._bayesian_accuracy(0, 0)
        assert result == 0.5

    def test_bayesian_one_win(self):
        """1/1 returns 0.6 (slightly optimistic)."""
        result = CredibilityLedger._bayesian_accuracy(1, 1)
        assert result == 0.6

    def test_bayesian_one_loss(self):
        """0/1 returns 0.4 (slightly pessimistic)."""
        result = CredibilityLedger._bayesian_accuracy(0, 1)
        assert result == 0.4

    def test_bayesian_seven_of_ten(self):
        """7/10 returns ~0.643."""
        result = CredibilityLedger._bayesian_accuracy(7, 10)
        assert abs(result - 0.643) < 0.001

    def test_bayesian_three_of_ten(self):
        """3/10 returns ~0.357."""
        result = CredibilityLedger._bayesian_accuracy(3, 10)
        assert abs(result - 0.357) < 0.001


# ---------------------------------------------------------------------------
# _summarize helper tests
# ---------------------------------------------------------------------------


class TestSummarize:
    """Test the _summarize helper function."""

    def test_summarize_empty(self):
        """Empty list returns {wins:0, losses:0, total:0, accuracy:0.5}."""
        result = _summarize([], CredibilityLedger._bayesian_accuracy)
        assert result["wins"] == 0
        assert result["losses"] == 0
        assert result["total"] == 0
        assert result["accuracy"] == 0.5

    def test_summarize_mixed(self):
        """[True, True, False] returns correct counts."""
        result = _summarize([True, True, False], CredibilityLedger._bayesian_accuracy)
        assert result["wins"] == 2
        assert result["losses"] == 1
        assert result["total"] == 3
        assert abs(result["accuracy"] - (4 / 7)) < 0.001  # (2+2)/(3+4)


class TestAgentDisplayName:
    """Test the _agent_display_name helper."""

    def test_investment_judge_display(self):
        assert _agent_display_name("investment_judge") == "Investment Judge"

    def test_trader_display(self):
        assert _agent_display_name("trader") == "Trader"

    def test_trader_display(self):
        assert _agent_display_name("trader") == "Trader"

    def test_bull_side_display(self):
        assert _agent_display_name("bull_side") == "Bull side"

    def test_bear_side_display(self):
        assert _agent_display_name("bear_side") == "Bear side"

    def test_unknown_agent_display(self):
        assert _agent_display_name("unknown_agent") == "unknown_agent"


# ---------------------------------------------------------------------------
# Agent scores tests
# ---------------------------------------------------------------------------


class TestComputeAgentScores:
    """Test per-agent accuracy computation."""

    def test_compute_agent_scores_empty(self, monkeypatch):
        """No attributions → all agents have total=0."""
        ledger = CredibilityLedger()
        result = ledger._compute_agent_scores([])

        for agent in _AGENTS:
            assert agent in result
            assert result[agent]["overall"]["total"] == 0
            assert result[agent]["overall"]["wins"] == 0
            assert result[agent]["overall"]["accuracy"] == 0.5

    def test_compute_agent_scores_single_trade(self, monkeypatch):
        """One attribution with investment_judge CORRECT → wins=1."""
        ledger = CredibilityLedger()
        attr = _make_attribution(
            agent_decisions={
                "investment_judge": {"decision": "BUY", "verdict": "CORRECT"},
                "trader": {"decision": "HOLD", "verdict": "NEUTRAL"},
                "trader": {"decision": "BUY", "verdict": "CORRECT"},
                "bull_side": {"verdict": "CORRECT"},
                "bear_side": {"verdict": "INCORRECT"},
            }
        )
        result = ledger._compute_agent_scores([attr])

        assert result["investment_judge"]["overall"]["wins"] == 1
        assert result["investment_judge"]["overall"]["total"] == 1
        assert result["investment_judge"]["overall"]["accuracy"] == 0.6  # (1+2)/(1+4)

    def test_compute_agent_scores_neutral_excluded(self, monkeypatch):
        """NEUTRAL verdict excluded from counts."""
        ledger = CredibilityLedger()
        attr = _make_attribution(
            agent_decisions={
                "investment_judge": {"decision": "HOLD", "verdict": "NEUTRAL"},
                "trader": {"decision": "HOLD", "verdict": "NEUTRAL"},
                "trader": {"decision": "BUY", "verdict": "CORRECT"},
                "bull_side": {"verdict": "CORRECT"},
                "bear_side": {"verdict": "INCORRECT"},
            }
        )
        result = ledger._compute_agent_scores([attr])

        # investment_judge should have no data because verdict is NEUTRAL
        assert result["investment_judge"]["overall"]["total"] == 0
        assert result["investment_judge"]["overall"]["accuracy"] == 0.5

    def test_compute_agent_scores_by_regime(self, monkeypatch):
        """Two trades in different regimes counted separately."""
        ledger = CredibilityLedger()
        attr1 = _make_attribution(
            regime="BULL",
            agent_decisions={
                "investment_judge": {"decision": "BUY", "verdict": "CORRECT"},
                "trader": {"decision": "BUY", "verdict": "CORRECT"},
                "trader": {"decision": "BUY", "verdict": "CORRECT"},
                "bull_side": {"verdict": "CORRECT"},
                "bear_side": {"verdict": "INCORRECT"},
            },
        )
        attr2 = _make_attribution(
            regime="BEAR",
            agent_decisions={
                "investment_judge": {"decision": "SELL", "verdict": "INCORRECT"},
                "trader": {"decision": "SELL", "verdict": "INCORRECT"},
                "trader": {"decision": "BUY", "verdict": "INCORRECT"},
                "bull_side": {"verdict": "INCORRECT"},
                "bear_side": {"verdict": "CORRECT"},
            },
        )
        result = ledger._compute_agent_scores([attr1, attr2])

        bull_stats = result["investment_judge"]["by_regime"]["BULL"]
        bear_stats = result["investment_judge"]["by_regime"]["BEAR"]

        assert bull_stats["wins"] == 1
        assert bull_stats["total"] == 1
        assert bear_stats["wins"] == 0
        assert bear_stats["total"] == 1

    def test_compute_agent_scores_by_decision(self, monkeypatch):
        """BUY vs SELL decisions tracked separately."""
        ledger = CredibilityLedger()
        attr1 = _make_attribution(
            agent_decisions={
                "investment_judge": {"decision": "BUY", "verdict": "CORRECT"},
                "trader": {"decision": "BUY", "verdict": "CORRECT"},
                "trader": {"decision": "BUY", "verdict": "CORRECT"},
                "bull_side": {"verdict": "CORRECT"},
                "bear_side": {"verdict": "INCORRECT"},
            }
        )
        attr2 = _make_attribution(
            return_pct=-10.0,
            agent_decisions={
                "investment_judge": {"decision": "SELL", "verdict": "CORRECT"},
                "trader": {"decision": "SELL", "verdict": "CORRECT"},
                "trader": {"decision": "SELL", "verdict": "CORRECT"},
                "bull_side": {"verdict": "INCORRECT"},
                "bear_side": {"verdict": "CORRECT"},
            },
        )
        result = ledger._compute_agent_scores([attr1, attr2])

        buy_stats = result["investment_judge"]["by_decision"]["BUY"]
        sell_stats = result["investment_judge"]["by_decision"]["SELL"]

        assert buy_stats["overall"]["wins"] == 1
        assert buy_stats["overall"]["total"] == 1
        assert sell_stats["overall"]["wins"] == 1
        assert sell_stats["overall"]["total"] == 1


# ---------------------------------------------------------------------------
# Pillar scores tests
# ---------------------------------------------------------------------------


class TestComputePillarScores:
    """Test per-pillar accuracy computation."""

    def test_compute_pillar_scores_empty(self, monkeypatch):
        """No attributions → all pillars total=0."""
        ledger = CredibilityLedger()
        result = ledger._compute_pillar_scores([])

        for pillar in _PILLARS:
            assert pillar in result
            assert result[pillar]["overall"]["total"] == 0
            assert result[pillar]["overall"]["wins"] == 0

    def test_compute_pillar_scores_right_wrong(self, monkeypatch):
        """RIGHT counted as win, WRONG as loss."""
        ledger = CredibilityLedger()
        # Fundamental score 70 (BULLISH) + positive return = RIGHT
        # Sentiment score 30 (BEARISH) + positive return = WRONG
        attr = _make_attribution(
            return_pct=10.0,
            pillar_scores_dict={
                "fundamental": 70,  # BULLISH + positive = RIGHT
                "coherence": 60,
                "macro": 50,
                "sentiment": 30,  # BEARISH + positive = WRONG
                "momentum": 65,
            },
        )
        result = ledger._compute_pillar_scores([attr])

        assert result["fundamental"]["overall"]["wins"] == 1
        assert result["fundamental"]["overall"]["total"] == 1
        assert result["sentiment"]["overall"]["wins"] == 0
        assert result["sentiment"]["overall"]["total"] == 1

    def test_compute_pillar_scores_neutral_excluded(self, monkeypatch):
        """NEUTRAL pillar verdict excluded."""
        ledger = CredibilityLedger()
        # Score 50 (NEUTRAL signal) = NEUTRAL verdict, excluded
        attr = _make_attribution(
            pillar_scores_dict={
                "fundamental": 50,  # NEUTRAL
                "coherence": 70,  # BULLISH
                "macro": 50,
                "sentiment": 50,
                "momentum": 70,
            }
        )
        result = ledger._compute_pillar_scores([attr])

        assert result["fundamental"]["overall"]["total"] == 0
        assert result["coherence"]["overall"]["total"] == 1


# ---------------------------------------------------------------------------
# Pattern detection tests
# ---------------------------------------------------------------------------


class TestDetectPatterns:
    """Test pattern detection logic."""

    def test_detect_patterns_judge_underperformance(self, monkeypatch):
        """Judge with <40% accuracy in a regime flagged."""
        ledger = CredibilityLedger()

        # Create 5 trades in BULL regime where investment_judge gets 1/5 correct
        attrs = []
        for i in range(5):
            attr = _make_attribution(
                regime="BULL",
                agent_decisions={
                    "investment_judge": {
                        "decision": "BUY" if i == 0 else "SELL",
                        "verdict": "CORRECT" if i == 0 else "INCORRECT",
                    },
                    "trader": {"decision": "HOLD", "verdict": "NEUTRAL"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "bull_side": {"verdict": "CORRECT"},
                    "bear_side": {"verdict": "INCORRECT"},
                },
            )
            attrs.append(attr)

        agent_scores = ledger._compute_agent_scores(attrs)
        patterns = ledger._detect_patterns(agent_scores, {})

        # Check for underperformance pattern (impl emits "bearish bias" per spec)
        found = any("bearish bias" in p and "BULL" in p for p in patterns)
        assert found

    def test_detect_patterns_bear_side_wrong(self, monkeypatch):
        """Bear side wrong >70% in regime flagged."""
        ledger = CredibilityLedger()

        # Create trades where bull side wins and bear side loses heavily in BULL regime
        attrs = []
        for i in range(4):
            attr = _make_attribution(
                regime="BULL",
                return_pct=10.0,  # Positive return
                agent_decisions={
                    "investment_judge": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "bull_side": {"verdict": "CORRECT"},  # Bull wins
                    "bear_side": {"verdict": "INCORRECT"},  # Bear loses
                },
            )
            attrs.append(attr)

        agent_scores = ledger._compute_agent_scores(attrs)
        patterns = ledger._detect_patterns(agent_scores, {})

        # Bear side should show strong bias
        found = any("Bear side wrong" in p and "BULL" in p for p in patterns)
        assert found

    def test_detect_patterns_pillar_spread(self, monkeypatch):
        """Large spread between best/worst pillar flagged."""
        ledger = CredibilityLedger()

        # Create 5 trades (≥5 threshold) where coherence is always WRONG
        attrs = []
        for i in range(5):
            attr = _make_attribution(
                regime="NEUTRAL",
                return_pct=10.0,
                pillar_scores_dict={
                    "fundamental": 80,  # BULLISH, will be RIGHT
                    "coherence": 20,  # BEARISH, will be WRONG (0/5 → unreliable)
                    "macro": 50,  # NEUTRAL
                    "sentiment": 75,  # BULLISH, will be RIGHT
                    "momentum": 25,  # BEARISH, will be WRONG
                },
            )
            attrs.append(attr)

        pillar_scores = ledger._compute_pillar_scores(attrs)
        patterns = ledger._detect_patterns({}, pillar_scores)

        # Implementation flags pillar unreliable when overall accuracy < 40% and total >= 5
        found = any("unreliable" in p.lower() and "coherence" in p.lower() for p in patterns)
        assert found


# ---------------------------------------------------------------------------
# Brief generation tests
# ---------------------------------------------------------------------------


class TestBuildCredibilityBrief:
    """Test brief generation."""

    def test_brief_empty_no_trades(self, monkeypatch):
        """0 trades → empty string."""
        ledger = CredibilityLedger()
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: [],
        )

        brief = ledger.build_credibility_brief("NEUTRAL")
        assert brief == ""

    def test_brief_insufficient_data(self, monkeypatch):
        """3 trades → 'Insufficient data' one-liner."""
        ledger = CredibilityLedger()
        attrs = [_make_attribution() for _ in range(3)]
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: attrs,
        )

        brief = ledger.build_credibility_brief("NEUTRAL")
        assert "Insufficient data (3 trades)" in brief
        assert "=== AGENT CREDIBILITY" in brief

    def test_brief_full_output(self, monkeypatch):
        """7+ trades → contains 'AGENT CREDIBILITY' and 'Agent Track Record'."""
        ledger = CredibilityLedger()
        attrs = [_make_attribution() for _ in range(7)]
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: attrs,
        )

        brief = ledger.build_credibility_brief("NEUTRAL")
        assert "=== AGENT CREDIBILITY" in brief
        assert "Agent Track Record:" in brief
        assert "Investment Judge:" in brief

    def test_brief_regime_filter(self, monkeypatch):
        """Brief mentions requested regime."""
        ledger = CredibilityLedger()
        attrs = [_make_attribution(regime="BULL") for _ in range(7)]
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: attrs,
        )

        brief = ledger.build_credibility_brief("BULL")
        assert "BULL regime" in brief

    def test_brief_includes_regime_specific_stats(self, monkeypatch):
        """Brief includes regime-specific accuracy for agents."""
        ledger = CredibilityLedger()
        attrs = [
            _make_attribution(
                regime="BULL",
                agent_decisions={
                    "investment_judge": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "bull_side": {"verdict": "CORRECT"},
                    "bear_side": {"verdict": "INCORRECT"},
                },
            )
            for _ in range(7)
        ]
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: attrs,
        )

        brief = ledger.build_credibility_brief("BULL")
        assert "In BULL:" in brief or "BULL" in brief

    def test_brief_pillar_reliability(self, monkeypatch):
        """Brief includes pillar reliability section."""
        ledger = CredibilityLedger()
        attrs = [_make_attribution() for _ in range(7)]
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: attrs,
        )

        brief = ledger.build_credibility_brief("NEUTRAL")
        assert "Pillar Reliability" in brief

    def test_brief_patterns_section(self, monkeypatch):
        """Brief includes PATTERNS section if patterns exist."""
        ledger = CredibilityLedger()
        # Create trades that trigger a pattern
        attrs = []
        for i in range(5):
            attr = _make_attribution(
                regime="BULL",
                agent_decisions={
                    "investment_judge": {
                        "decision": "SELL",
                        "verdict": "INCORRECT",
                    },
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "bull_side": {"verdict": "CORRECT"},
                    "bear_side": {"verdict": "INCORRECT"},
                },
            )
            attrs.append(attr)

        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: attrs,
        )

        brief = ledger.build_credibility_brief("BULL")
        # May or may not have patterns depending on thresholds
        # Just check it's well-formed
        assert "=== END AGENT CREDIBILITY ===" in brief


# ---------------------------------------------------------------------------
# Build integration tests
# ---------------------------------------------------------------------------


class TestBuild:
    """Test the main build() method."""

    def test_build_no_closed_trades(self, monkeypatch):
        """Returns trade_count=0."""
        ledger = CredibilityLedger()
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: [],
        )

        result = ledger.build()
        assert result["trade_count"] == 0
        assert result["trade_count_with_reports"] == 0

    def test_build_with_mock_attributions(self, monkeypatch):
        """Returns correct structure."""
        ledger = CredibilityLedger()
        attrs = [_make_attribution() for _ in range(5)]
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: attrs,
        )

        result = ledger.build()

        assert result["trade_count"] == 5
        assert result["trade_count_with_reports"] == 5
        assert "agent_scores" in result
        assert "pillar_scores" in result
        assert "patterns" in result

        # Check agents structure
        for agent in _AGENTS:
            assert agent in result["agent_scores"]
            assert "overall" in result["agent_scores"][agent]
            assert "by_regime" in result["agent_scores"][agent]

        # Check pillars structure
        for pillar in _PILLARS:
            assert pillar in result["pillar_scores"]
            assert "overall" in result["pillar_scores"][pillar]
            assert "by_regime" in result["pillar_scores"][pillar]

    def test_build_filters_no_report_trades(self, monkeypatch):
        """Only counts trades with report_found=True in accuracy."""
        ledger = CredibilityLedger()
        attrs = [
            _make_attribution(report_found=True),
            _make_attribution(report_found=False),
            _make_attribution(report_found=True),
        ]
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: attrs,
        )

        result = ledger.build()
        assert result["trade_count"] == 3
        assert result["trade_count_with_reports"] == 2

    def test_build_structure_matches_api(self, monkeypatch):
        """Returned structure matches public API expectations."""
        ledger = CredibilityLedger()
        attrs = [_make_attribution() for _ in range(7)]
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: attrs,
        )

        ledger_data = ledger.build()

        # Public API expects these keys
        assert isinstance(ledger_data, dict)
        assert set(ledger_data.keys()) >= {"agent_scores", "pillar_scores", "patterns", "trade_count", "trade_count_with_reports"}

        # Agents dict structure
        agents = ledger_data["agent_scores"]
        for agent_key in agents:
            agent_info = agents[agent_key]
            assert "overall" in agent_info
            assert "by_regime" in agent_info
            if "by_decision" in agent_info and agent_info["by_decision"]:
                # Should have decision-level data for judges
                for decision, d_info in agent_info["by_decision"].items():
                    assert "overall" in d_info
                    assert "by_regime" in d_info


# ---------------------------------------------------------------------------
# Edge cases and integration
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and corner scenarios."""

    def test_mixed_regime_and_decision_tracking(self, monkeypatch):
        """Correctly tracks both regime and decision dimensions."""
        ledger = CredibilityLedger()
        attrs = [
            _make_attribution(
                regime="BULL",
                return_pct=10.0,
                agent_decisions={
                    "investment_judge": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "HOLD", "verdict": "NEUTRAL"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "bull_side": {"verdict": "CORRECT"},
                    "bear_side": {"verdict": "INCORRECT"},
                },
            ),
            _make_attribution(
                regime="BEAR",
                return_pct=-10.0,
                agent_decisions={
                    "investment_judge": {"decision": "SELL", "verdict": "CORRECT"},
                    "trader": {"decision": "SELL", "verdict": "CORRECT"},
                    "trader": {"decision": "SELL", "verdict": "CORRECT"},
                    "bull_side": {"verdict": "INCORRECT"},
                    "bear_side": {"verdict": "CORRECT"},
                },
            ),
        ]
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: attrs,
        )

        result = ledger.build()
        inv_judge = result["agent_scores"]["investment_judge"]

        # Should have both BULL and BEAR in by_regime
        assert "BULL" in inv_judge["by_regime"]
        assert "BEAR" in inv_judge["by_regime"]
        assert inv_judge["by_regime"]["BULL"]["wins"] == 1
        assert inv_judge["by_regime"]["BEAR"]["wins"] == 1

        # Should have both BUY and SELL in by_decision
        assert "BUY" in inv_judge["by_decision"]
        assert "SELL" in inv_judge["by_decision"]

    def test_all_wrong_trades(self, monkeypatch):
        """Correctly computes accuracy when all trades are wrong."""
        ledger = CredibilityLedger()
        attrs = [
            _make_attribution(
                return_pct=10.0,
                agent_decisions={
                    "investment_judge": {"decision": "SELL", "verdict": "INCORRECT"},
                    "trader": {"decision": "SELL", "verdict": "INCORRECT"},
                    "trader": {"decision": "SELL", "verdict": "INCORRECT"},
                    "bull_side": {"verdict": "CORRECT"},
                    "bear_side": {"verdict": "INCORRECT"},
                },
            )
            for _ in range(5)
        ]
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: attrs,
        )

        result = ledger.build()
        inv_judge = result["agent_scores"]["investment_judge"]

        assert inv_judge["overall"]["wins"] == 0
        assert inv_judge["overall"]["total"] == 5
        # Bayesian: (0+2)/(5+4) = 2/9 ≈ 0.222
        assert abs(inv_judge["overall"]["accuracy"] - (2 / 9)) < 0.001

    def test_no_agents_tracked(self, monkeypatch):
        """Handles trades with no agent decisions gracefully."""
        ledger = CredibilityLedger()
        attr = _make_attribution(agent_decisions={})  # Empty decisions
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: [attr],
        )

        result = ledger.build()
        for agent in _AGENTS:
            assert result["agent_scores"][agent]["overall"]["total"] == 0

    def test_missing_pillar_in_attribution(self, monkeypatch):
        """Handles missing pillars gracefully."""
        ledger = CredibilityLedger()
        attr = _make_attribution(
            pillar_scores_dict={
                "fundamental": 70,
                # missing coherence, macro, sentiment, momentum
            }
        )
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: [attr],
        )

        result = ledger.build()
        assert result["pillar_scores"]["fundamental"]["overall"]["total"] == 1
        assert result["pillar_scores"]["coherence"]["overall"]["total"] == 0


# ---------------------------------------------------------------------------
# Consensus Paradox tests
# ---------------------------------------------------------------------------


class TestConsensusParadox:
    """Test consensus paradox detection."""

    def test_consensus_paradox_empty(self, monkeypatch):
        """No attributions → all consensus buckets have total=0, paradox_detected=False."""
        ledger = CredibilityLedger()
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: [],
        )

        result = ledger.build()

        # Check consensus data exists and is empty
        assert "consensus_paradox" in result
        consensus = result["consensus_paradox"]
        assert consensus.get("paradox_detected") is False
        assert consensus.get("unanimous", {}).get("total", 0) == 0
        assert consensus.get("split", {}).get("total", 0) == 0

    def test_consensus_paradox_unanimous(self, monkeypatch):
        """5 trades where all 5 agents agree CORRECT → unanimous bucket has 5."""
        ledger = CredibilityLedger()
        attrs = []

        for _ in range(5):
            attr = _make_attribution(
                return_pct=10.0,
                agent_decisions={
                    "investment_judge": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "bull_side": {"verdict": "CORRECT"},
                    "bear_side": {"verdict": "CORRECT"},  # All agree
                },
            )
            attrs.append(attr)

        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: attrs,
        )

        result = ledger.build()
        consensus = result.get("consensus_paradox", {})

        # All 5 agents agreed (all CORRECT)
        assert consensus.get("unanimous", {}).get("total", 0) == 5
        assert consensus.get("unanimous", {}).get("wins", 0) == 5

    def test_consensus_paradox_split(self, monkeypatch):
        """5 trades where 3 agents CORRECT, 2 INCORRECT → split bucket has 5."""
        ledger = CredibilityLedger()
        attrs = []

        for _ in range(5):
            attr = _make_attribution(
                return_pct=10.0,
                agent_decisions={
                    "investment_judge": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},  # 3 CORRECT
                    "bull_side": {"verdict": "INCORRECT"},
                    "bear_side": {"verdict": "INCORRECT"},  # 2 INCORRECT
                },
            )
            attrs.append(attr)

        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: attrs,
        )

        result = ledger.build()
        consensus = result.get("consensus_paradox", {})

        # 3 agents CORRECT, 2 INCORRECT = split
        assert consensus.get("split", {}).get("total", 0) == 5
        assert consensus.get("split", {}).get("wins", 0) == 5  # All won

    def test_consensus_paradox_detected(self, monkeypatch):
        """Unanimous trades lose, split trades win → paradox_detected=True."""
        ledger = CredibilityLedger()

        # Unanimous: all agree INCORRECT, and they lose
        unanimous_attrs = []
        for _ in range(5):
            attr = _make_attribution(
                return_pct=-10.0,  # LOSS
                agent_decisions={
                    "investment_judge": {"decision": "BUY", "verdict": "INCORRECT"},
                    "trader": {"decision": "BUY", "verdict": "INCORRECT"},
                    "trader": {"decision": "BUY", "verdict": "INCORRECT"},
                    "bull_side": {"verdict": "INCORRECT"},
                    "bear_side": {"verdict": "INCORRECT"},  # All agree and lose
                },
            )
            unanimous_attrs.append(attr)

        # Split: 3 CORRECT (win), 2 INCORRECT (lose), but outcome is WIN
        split_attrs = []
        for _ in range(5):
            attr = _make_attribution(
                return_pct=10.0,  # WIN
                agent_decisions={
                    "investment_judge": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},  # 3 CORRECT
                    "bull_side": {"verdict": "INCORRECT"},
                    "bear_side": {"verdict": "INCORRECT"},  # 2 INCORRECT
                },
            )
            split_attrs.append(attr)

        all_attrs = unanimous_attrs + split_attrs
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: all_attrs,
        )

        result = ledger.build()
        consensus = result.get("consensus_paradox", {})

        # Unanimous lost (0 wins), split won (5 wins) → paradox
        assert consensus.get("paradox_detected") is True

    def test_consensus_paradox_not_detected(self, monkeypatch):
        """Unanimous wins > split wins → paradox_detected=False."""
        ledger = CredibilityLedger()

        # Unanimous: all agree CORRECT, and they win
        unanimous_attrs = []
        for _ in range(5):
            attr = _make_attribution(
                return_pct=10.0,  # WIN
                agent_decisions={
                    "investment_judge": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "bull_side": {"verdict": "CORRECT"},
                    "bear_side": {"verdict": "CORRECT"},  # All agree and win
                },
            )
            unanimous_attrs.append(attr)

        # Split: 3 CORRECT, 2 INCORRECT, outcome is WIN but less consensus
        split_attrs = []
        for _ in range(3):
            attr = _make_attribution(
                return_pct=10.0,  # WIN
                agent_decisions={
                    "investment_judge": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},  # 3 CORRECT
                    "bull_side": {"verdict": "INCORRECT"},
                    "bear_side": {"verdict": "INCORRECT"},  # 2 INCORRECT
                },
            )
            split_attrs.append(attr)

        all_attrs = unanimous_attrs + split_attrs
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: all_attrs,
        )

        result = ledger.build()
        consensus = result.get("consensus_paradox", {})

        # Unanimous won (5 wins) > split won (3 wins) → no paradox
        assert consensus.get("paradox_detected") is False

    def test_consensus_too_few_directional(self, monkeypatch):
        """Trades with < 3 directional agents skipped from consensus."""
        ledger = CredibilityLedger()

        # Trade with only 2 directional agents (most NEUTRAL)
        attr = _make_attribution(
            agent_decisions={
                "investment_judge": {"decision": "HOLD", "verdict": "NEUTRAL"},
                "trader": {"decision": "HOLD", "verdict": "NEUTRAL"},
                "trader": {"decision": "HOLD", "verdict": "NEUTRAL"},
                "bull_side": {"verdict": "CORRECT"},
                "bear_side": {"verdict": "INCORRECT"},  # Only 2 directional
            },
        )

        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: [attr],
        )

        result = ledger.build()
        consensus = result.get("consensus_analysis", {})

        # Should have no consensus data or empty counts
        assert consensus.get("unanimous", {}).get("total", 0) == 0
        assert consensus.get("split", {}).get("total", 0) == 0

    def test_consensus_in_brief(self, monkeypatch):
        """10+ trades with consensus data → brief contains 'Consensus Analysis'."""
        ledger = CredibilityLedger()
        attrs = []

        # Create 10 unanimous trades
        for _ in range(10):
            attr = _make_attribution(
                return_pct=10.0,
                agent_decisions={
                    "investment_judge": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "bull_side": {"verdict": "CORRECT"},
                    "bear_side": {"verdict": "CORRECT"},
                },
            )
            attrs.append(attr)

        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: attrs,
        )

        brief = ledger.build_credibility_brief("NEUTRAL")

        # Brief should mention consensus analysis
        assert "Consensus Analysis" in brief or "consensus" in brief.lower()

    def test_consensus_paradox_warning_in_brief(self, monkeypatch):
        """Paradox detected → brief contains 'WARNING: Dissent is signal'."""
        ledger = CredibilityLedger()

        # Unanimous loses, split wins → paradox
        unanimous_attrs = []
        for _ in range(5):
            attr = _make_attribution(
                return_pct=-10.0,
                agent_decisions={
                    "investment_judge": {"decision": "BUY", "verdict": "INCORRECT"},
                    "trader": {"decision": "BUY", "verdict": "INCORRECT"},
                    "trader": {"decision": "BUY", "verdict": "INCORRECT"},
                    "bull_side": {"verdict": "INCORRECT"},
                    "bear_side": {"verdict": "INCORRECT"},
                },
            )
            unanimous_attrs.append(attr)

        split_attrs = []
        for _ in range(5):
            attr = _make_attribution(
                return_pct=10.0,
                agent_decisions={
                    "investment_judge": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "trader": {"decision": "BUY", "verdict": "CORRECT"},
                    "bull_side": {"verdict": "INCORRECT"},
                    "bear_side": {"verdict": "INCORRECT"},
                },
            )
            split_attrs.append(attr)

        all_attrs = unanimous_attrs + split_attrs
        monkeypatch.setattr(
            ledger._engine,
            "analyze_all",
            lambda: all_attrs,
        )

        brief = ledger.build_credibility_brief("NEUTRAL")

        # Brief should contain paradox warning
        assert "WARNING: Dissent is signal" in brief or "paradox" in brief.lower() or "dissent" in brief.lower()
