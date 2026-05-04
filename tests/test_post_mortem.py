# tests/test_post_mortem.py

import json
import os
import sys
import types
import pytest
from pathlib import Path
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

from tradingagents.graph.post_mortem import (
    PostMortemEngine,
    _extract_decision,
    _outcome_label,
    _pillar_signal,
    _pillar_verdict,
    _decision_verdict,
    _rating_from_score,
)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _make_trade(
    symbol="AAPL",
    return_pct=10.0,
    pnl_usd=500.0,
    close_price=111.0,
    avg_entry_price=100.0,
    rating_ids=None,
    close_date="2026-02-06",
    close_id="test-close-id",
    closed_at="2026-02-25T22:00:00+00:00",
):
    return {
        "close_id": close_id,
        "closed_at": closed_at,
        "symbol": symbol,
        "close_date": close_date,
        "close_price": close_price,
        "avg_entry_price": avg_entry_price,
        "pnl_usd": pnl_usd,
        "return_pct": return_pct,
        "rating_ids": rating_ids or ["PHASE:2026-02-07:AAPL"],
        "updated_rating_ids": [],
        "net_quantity": -10.0,
    }


def _make_report(
    breakdown=None,
    entry_score=59.55,
    rating="Hold",
    weight_regime="NEUTRAL",
    judge_decision="**Recommendation: SELL**",
    risk_judge_decision="**RECOMMENDATION: SELL**",
    trader_text="**Recommendation: HOLD**",
    bull_history="Bull argues BUY",
    bear_history="Bear argues SELL",
):
    return {
        "aeternus_score": {
            "rating_id": "test-rating-id",
            "ticker": "AAPL",
            "date": "2026-02-07",
            "aeternus_score": entry_score,
            "rating": rating,
            "breakdown": breakdown or {
                "fundamental": 70,
                "macro": 50,
                "sentiment": 77,
                "momentum": 50,
                "coherence": 48,
            },
            "weight_regime": weight_regime,
        },
        "investment_debate_state": {
            "judge_decision": judge_decision,
            "bull_history": bull_history,
            "bear_history": bear_history,
        },
        "risk_debate_state": {
            "judge_decision": risk_judge_decision,
        },
        "trader_investment_plan": trader_text,
    }


# ---------------------------------------------------------------------------
# Unit tests — helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_outcome_label_win(self):
        assert _outcome_label(10.0) == "WIN"

    def test_outcome_label_loss(self):
        assert _outcome_label(-5.0) == "LOSS"

    def test_outcome_label_flat(self):
        assert _outcome_label(0.0) == "FLAT"
        assert _outcome_label(0.3) == "FLAT"
        assert _outcome_label(-0.4) == "FLAT"

    def test_pillar_signal_bullish(self):
        assert _pillar_signal(60) == "BULLISH"
        assert _pillar_signal(100) == "BULLISH"

    def test_pillar_signal_bearish(self):
        assert _pillar_signal(39) == "BEARISH"
        assert _pillar_signal(0) == "BEARISH"

    def test_pillar_signal_neutral(self):
        assert _pillar_signal(40) == "NEUTRAL"
        assert _pillar_signal(59) == "NEUTRAL"
        assert _pillar_signal(50) == "NEUTRAL"

    def test_pillar_verdict_right(self):
        assert _pillar_verdict("BULLISH", 10.0) == "RIGHT"
        assert _pillar_verdict("BEARISH", -10.0) == "RIGHT"

    def test_pillar_verdict_wrong(self):
        assert _pillar_verdict("BULLISH", -10.0) == "WRONG"
        assert _pillar_verdict("BEARISH", 10.0) == "WRONG"

    def test_pillar_verdict_neutral(self):
        assert _pillar_verdict("NEUTRAL", 10.0) == "NEUTRAL"
        assert _pillar_verdict("BULLISH", 0.0) == "NEUTRAL"

    def test_extract_decision_recommendation(self):
        assert _extract_decision("**Recommendation: SELL**") == "SELL"
        assert _extract_decision("Recommendation: BUY") == "BUY"

    def test_extract_decision_verdict(self):
        assert _extract_decision("Verdict: HOLD") == "HOLD"

    def test_extract_decision_fallback(self):
        assert _extract_decision("I think we should BUY this stock") == "BUY"

    def test_extract_decision_unknown(self):
        assert _extract_decision("") == "UNKNOWN"
        assert _extract_decision("No clear signal here") == "UNKNOWN"

    def test_decision_verdict_correct(self):
        assert _decision_verdict("BUY", 10.0) == "CORRECT"
        assert _decision_verdict("SELL", -10.0) == "CORRECT"

    def test_decision_verdict_incorrect(self):
        assert _decision_verdict("BUY", -10.0) == "INCORRECT"
        assert _decision_verdict("SELL", 10.0) == "INCORRECT"

    def test_decision_verdict_neutral(self):
        assert _decision_verdict("HOLD", 10.0) == "NEUTRAL"
        assert _decision_verdict("UNKNOWN", -10.0) == "NEUTRAL"

    def test_rating_from_score(self):
        assert _rating_from_score(85) == "Strong Buy"
        assert _rating_from_score(65) == "Buy"
        assert _rating_from_score(50) == "Hold"
        assert _rating_from_score(30) == "Sell"
        assert _rating_from_score(10) == "Strong Sell"


# ---------------------------------------------------------------------------
# Pillar attribution
# ---------------------------------------------------------------------------

class TestPillarAttribution:
    def test_basic_attribution(self):
        engine = PostMortemEngine()
        breakdown = {"fundamental": 70, "macro": 50, "sentiment": 30, "momentum": 80, "coherence": 45}
        result = engine.compute_pillar_attribution(breakdown, 10.0)

        assert result["fundamental"]["signal"] == "BULLISH"
        assert result["fundamental"]["verdict"] == "RIGHT"
        assert result["fundamental"]["magnitude"] == 20

        assert result["macro"]["signal"] == "NEUTRAL"
        assert result["macro"]["verdict"] == "NEUTRAL"

        assert result["sentiment"]["signal"] == "BEARISH"
        assert result["sentiment"]["verdict"] == "WRONG"

        assert result["momentum"]["signal"] == "BULLISH"
        assert result["momentum"]["verdict"] == "RIGHT"

    def test_negative_return(self):
        engine = PostMortemEngine()
        breakdown = {"fundamental": 30, "macro": 50, "sentiment": 70, "momentum": 50, "coherence": 50}
        result = engine.compute_pillar_attribution(breakdown, -15.0)

        assert result["fundamental"]["verdict"] == "RIGHT"  # bearish + negative = right
        assert result["sentiment"]["verdict"] == "WRONG"  # bullish + negative = wrong

    def test_empty_breakdown(self):
        engine = PostMortemEngine()
        result = engine.compute_pillar_attribution({}, 10.0)
        assert result == {}


# ---------------------------------------------------------------------------
# Agent accuracy
# ---------------------------------------------------------------------------

class TestAgentAccuracy:
    def test_agents_with_positive_return(self):
        engine = PostMortemEngine()
        result = engine.compute_agent_accuracy(
            invest_debate={"judge_decision": "Recommendation: SELL"},
            risk_debate={"judge_decision": "RECOMMENDATION: SELL"},
            trader_text="Recommendation: HOLD",
            return_pct=59.69,
        )
        assert result["investment_judge"]["decision"] == "SELL"
        assert result["investment_judge"]["verdict"] == "INCORRECT"
        assert result["risk_judge"]["verdict"] == "INCORRECT"
        assert result["trader"]["decision"] == "HOLD"
        assert result["trader"]["verdict"] == "NEUTRAL"
        assert result["bull_side"]["verdict"] == "CORRECT"
        assert result["bear_side"]["verdict"] == "INCORRECT"

    def test_agents_with_negative_return(self):
        engine = PostMortemEngine()
        result = engine.compute_agent_accuracy(
            invest_debate={"judge_decision": "Recommendation: SELL"},
            risk_debate={"judge_decision": "RECOMMENDATION: SELL"},
            trader_text="Recommendation: SELL",
            return_pct=-20.0,
        )
        assert result["investment_judge"]["verdict"] == "CORRECT"
        assert result["risk_judge"]["verdict"] == "CORRECT"
        assert result["trader"]["verdict"] == "CORRECT"
        assert result["bull_side"]["verdict"] == "INCORRECT"
        assert result["bear_side"]["verdict"] == "CORRECT"

    def test_empty_debate(self):
        engine = PostMortemEngine()
        result = engine.compute_agent_accuracy({}, {}, "", 10.0)
        assert result["investment_judge"]["decision"] == "UNKNOWN"
        assert result["investment_judge"]["verdict"] == "NEUTRAL"


# ---------------------------------------------------------------------------
# Counterfactual
# ---------------------------------------------------------------------------

class TestCounterfactual:
    def test_all_regimes_present(self):
        engine = PostMortemEngine()
        breakdown = {"fundamental": 70, "macro": 50, "sentiment": 77, "momentum": 50, "coherence": 48}
        result = engine.compute_counterfactual(breakdown, "NEUTRAL")

        # All 9 regimes present + 2 meta keys
        assert len(result) == 11  # 9 regimes + best + most_protective
        assert result["NEUTRAL"]["is_actual"] is True
        assert result["BULL"]["is_actual"] is False
        assert result["NEUTRAL"]["delta"] == 0.0

        # best and most protective
        assert "best_regime_for_outcome" in result
        assert "most_protective_regime" in result

    def test_scores_differ_across_regimes(self):
        engine = PostMortemEngine()
        breakdown = {"fundamental": 80, "macro": 20, "sentiment": 90, "momentum": 30, "coherence": 60}
        result = engine.compute_counterfactual(breakdown, "NEUTRAL")

        # VOL_SHOCK weights macro heavily (0.35) — macro=20 should pull score down
        # EUPHORIA weights coherence heavily (0.35) — coherence=60 should be decent
        assert result["VOL_SHOCK"]["score"] != result["EUPHORIA"]["score"]

    def test_empty_breakdown(self):
        engine = PostMortemEngine()
        result = engine.compute_counterfactual({}, "NEUTRAL")
        assert result == {}

    def test_deltas_relative_to_actual(self):
        engine = PostMortemEngine()
        breakdown = {"fundamental": 70, "macro": 50, "sentiment": 77, "momentum": 50, "coherence": 48}
        result = engine.compute_counterfactual(breakdown, "NEUTRAL")
        actual_score = result["NEUTRAL"]["score"]
        for regime_name, entry in result.items():
            if isinstance(entry, dict) and "delta" in entry:
                assert abs(entry["delta"] - (entry["score"] - actual_score)) < 0.01


# ---------------------------------------------------------------------------
# Regime accuracy table
# ---------------------------------------------------------------------------

class TestRegimeAccuracyTable:
    def test_basic_table(self):
        engine = PostMortemEngine()
        attrs = [
            {
                "report_found": True,
                "weight_regime": "NEUTRAL",
                "pillar_attribution": {
                    "fundamental": {"verdict": "RIGHT"},
                    "macro": {"verdict": "WRONG"},
                    "sentiment": {"verdict": "NEUTRAL"},
                    "momentum": {"verdict": "RIGHT"},
                    "coherence": {"verdict": "WRONG"},
                },
            },
            {
                "report_found": True,
                "weight_regime": "NEUTRAL",
                "pillar_attribution": {
                    "fundamental": {"verdict": "RIGHT"},
                    "macro": {"verdict": "RIGHT"},
                    "sentiment": {"verdict": "RIGHT"},
                    "momentum": {"verdict": "WRONG"},
                    "coherence": {"verdict": "NEUTRAL"},
                },
            },
        ]
        table = engine.build_regime_accuracy_table(attrs)

        assert "NEUTRAL" in table
        assert table["NEUTRAL"]["fundamental"]["right"] == 2
        assert table["NEUTRAL"]["fundamental"]["accuracy"] == 100.0
        assert table["NEUTRAL"]["macro"]["right"] == 1
        assert table["NEUTRAL"]["macro"]["wrong"] == 1
        assert table["NEUTRAL"]["macro"]["accuracy"] == 50.0

    def test_skips_no_report(self):
        engine = PostMortemEngine()
        attrs = [{"report_found": False, "weight_regime": "NEUTRAL", "pillar_attribution": {}}]
        table = engine.build_regime_accuracy_table(attrs)
        assert table == {}


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------

class TestNarrative:
    def test_narrative_with_report(self):
        engine = PostMortemEngine()
        trade = _make_trade(return_pct=59.69, pnl_usd=5259.59)
        report = _make_report()
        attr = engine.analyze_trade(trade, report)

        narrative = attr["narrative"]
        assert "POST-MORTEM: AAPL" in narrative
        assert "59.69%" in narrative or "+59.69%" in narrative
        assert "Hold" in narrative

    def test_narrative_without_report(self):
        engine = PostMortemEngine()
        trade = _make_trade()
        attr = engine.analyze_trade(trade, None)

        assert "Phase Engine trade" in attr["narrative"]
        assert attr["report_found"] is False


# ---------------------------------------------------------------------------
# analyze_trade integration
# ---------------------------------------------------------------------------

class TestAnalyzeTrade:
    def test_full_attribution(self):
        engine = PostMortemEngine()
        trade = _make_trade(return_pct=59.69, pnl_usd=5259.59)
        report = _make_report()
        attr = engine.analyze_trade(trade, report)

        assert attr["ticker"] == "AAPL"
        assert attr["outcome"] == "WIN"
        assert attr["return_pct"] == 59.69
        assert attr["entry_score"] == 59.55
        assert attr["entry_rating"] == "Hold"
        assert attr["report_found"] is True
        assert len(attr["pillar_attribution"]) == 5
        assert "investment_judge" in attr["agent_accuracy"]
        assert "best_regime_for_outcome" in attr["counterfactual"]
        assert attr["narrative"]

    def test_no_report(self):
        engine = PostMortemEngine()
        trade = _make_trade()
        attr = engine.analyze_trade(trade, None)

        assert attr["report_found"] is False
        assert attr["pillar_attribution"] == {}
        assert attr["agent_accuracy"] == {}
        assert attr["counterfactual"] == {}


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_dedup_keeps_most_recent(self):
        engine = PostMortemEngine()
        trades = [
            _make_trade(closed_at="2026-02-25T19:00:00+00:00", pnl_usd=100.0),
            _make_trade(closed_at="2026-02-25T22:00:00+00:00", pnl_usd=200.0),
        ]
        result = engine._deduplicate(trades)
        assert len(result) == 1
        assert result[0]["pnl_usd"] == 200.0

    def test_different_trades_not_deduped(self):
        engine = PostMortemEngine()
        trades = [
            _make_trade(close_price=111.0),
            _make_trade(close_price=222.0),
        ]
        result = engine._deduplicate(trades)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# File loading edge cases
# ---------------------------------------------------------------------------

class TestFileLoading:
    def test_missing_closed_trades(self, tmp_path):
        engine = PostMortemEngine(
            closed_trades_path=str(tmp_path / "nonexistent.json"),
        )
        assert engine._load_closed_trades() == []

    def test_empty_closed_trades(self, tmp_path):
        f = tmp_path / "closed_trades.json"
        f.write_text("[]")
        engine = PostMortemEngine(closed_trades_path=str(f))
        assert engine._load_closed_trades() == []

    def test_analyze_all_empty(self, tmp_path):
        f = tmp_path / "closed_trades.json"
        f.write_text("[]")
        engine = PostMortemEngine(closed_trades_path=str(f))
        assert engine.analyze_all() == []

    def test_analyze_all_with_real_structure(self, tmp_path):
        # Create a minimal file structure
        results = tmp_path / "results"
        ticker_dir = results / "AAPL" / "2026-02-07"
        ticker_dir.mkdir(parents=True)

        report = _make_report()
        (ticker_dir / "analysis_report.json").write_text(json.dumps(report))

        trades_file = tmp_path / "closed_trades.json"
        trade = _make_trade(return_pct=10.0, pnl_usd=500.0)
        trades_file.write_text(json.dumps([trade]))

        engine = PostMortemEngine(
            results_root=str(results),
            closed_trades_path=str(trades_file),
            track_record_path=str(tmp_path / "track_record.json"),
        )
        attrs = engine.analyze_all()
        assert len(attrs) == 1
        assert attrs[0]["ticker"] == "AAPL"
        assert attrs[0]["report_found"] is True
        assert attrs[0]["outcome"] == "WIN"
