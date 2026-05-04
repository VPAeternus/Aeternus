"""Tests for performance_tracker.py — funnel report card engine."""

import json
import math
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dealflow.hypothesis_ledger import append_ledger_row, make_ledger_row


# --- Fixtures ---

def _make_funnel_artifacts(base: Path, symbols: list[str], queued: list[str],
                           analyzed: list[str], deployed: list[str]):
    """Create minimal funnel artifacts on disk."""
    base.mkdir(parents=True, exist_ok=True)

    # signals_raw.json — one signal per symbol per family
    signals = []
    for sym in symbols:
        for fam in ("price_momentum", "news_catalyst", "smart_money"):
            signals.append({
                "symbol": sym,
                "signal_family": fam,
                "raw_score": symbols.index(sym) * 10.0 + 5.0,
                "z_score": 0.5,
                "direction": "LONG",
                "evidence_count": 3,
            })
    (base / "signals_raw.json").write_text(json.dumps(signals))

    # all_scored_candidates.json
    scored = [{"symbol": sym, "status": "SCORED", "core_score": 50 + i * 5,
               "momentum_score": 40 + i * 3, "lane": "CORE"}
              for i, sym in enumerate(symbols)]
    (base / "all_scored_candidates.json").write_text(json.dumps(scored))

    # research_queue.json
    queue_items = [{"symbol": sym, "deal_flow_score": 60 + i * 2}
                   for i, sym in enumerate(queued)]
    (base / "research_queue.json").write_text(json.dumps({"items": queue_items}))

    # batch_analyze_latest.json
    batch_items = [{"symbol": sym, "status": "SUCCESS", "aeternus_score": 70 + i * 3}
                   for i, sym in enumerate(analyzed)]
    (base / "batch_analyze_latest.json").write_text(json.dumps({"items": batch_items}))


def _write_ledger_row(base: Path, source_date: str, kept: list[str], dropped: list[str]):
    row = make_ledger_row(
        run_id=f"{source_date}-120000-manual",
        source_date=source_date,
        lane="shared",
        stage_id="shortlist_cut",
        rule_snapshot={"top_k": len(kept)},
        kept_symbols=kept,
        dropped_symbols=dropped,
        base_dir=base,
    )
    append_ledger_row(base_dir=base, lane="shared", row=row)


def _mock_prices(
    symbols: list[str],
    t0: str,
    returns_5d: dict,
    returns_20d: dict | None = None,
    returns_3m: dict | None = None,
):
    """Build a mock yfinance DataFrame with close prices producing desired returns."""
    periods = 65 if returns_3m is not None else 25
    dates = pd.bdate_range(t0, periods=periods)
    data = {}
    all_syms = set(symbols) | {"QQQ"}
    for sym in all_syms:
        p0 = 100.0
        r5 = returns_5d.get(sym, 0.0)
        r20 = (returns_20d or {}).get(sym, 0.0)
        r3m = (returns_3m or {}).get(sym, r20)
        # Build a series: p0 at day 0, p0*(1+r5) at day 5, p0*(1+r20) at day 20, p0*(1+r3m) at day 60
        prices = [p0] * len(dates)
        if len(dates) > 5:
            prices[5] = p0 * (1 + r5)
        if len(dates) > 20:
            prices[20] = p0 * (1 + r20)
        if returns_3m is not None and len(dates) > 60:
            prices[60] = p0 * (1 + r3m)
        # Fill intermediate with linear interpolation for simplicity
        for i in range(1, min(5, len(dates))):
            prices[i] = p0 + (prices[5] - p0) * i / 5 if len(dates) > 5 else p0
        for i in range(6, min(20, len(dates))):
            prices[i] = prices[5] + (prices[20] - prices[5]) * (i - 5) / 15 if len(dates) > 20 else prices[5]
        if returns_3m is not None:
            for i in range(21, min(60, len(dates))):
                prices[i] = prices[20] + (prices[60] - prices[20]) * (i - 20) / 40 if len(dates) > 60 else prices[20]
        data[sym] = prices[:len(dates)]

    df = pd.DataFrame(data, index=dates[:len(data[list(all_syms)[0]])])
    # Make MultiIndex columns like yfinance returns
    df.columns = pd.MultiIndex.from_product([["Close"], df.columns])
    return df


# --- Tests ---

class TestCohortAssignment:
    def test_cohorts_assigned_correctly(self, tmp_path):
        """Symbols are assigned to the highest stage they reached."""
        from tradingagents.dealflow.performance_tracker import compute_performance_review

        source_date = "2026-01-15"
        base = tmp_path / "eval_results" / "deal_flow" / source_date
        symbols = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        queued = ["BBB", "CCC", "DDD"]
        analyzed = ["CCC", "DDD"]
        deployed = ["DDD"]

        _make_funnel_artifacts(base, symbols, queued, analyzed, deployed)

        returns_5d = {s: 0.01 * (i + 1) for i, s in enumerate(symbols)}
        returns_5d["QQQ"] = 0.005
        prices = _mock_prices(symbols, "2026-01-15", returns_5d)

        with patch("tradingagents.dealflow.performance_tracker._DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow"), \
             patch("tradingagents.dealflow.performance_tracker._deployed_tickers", return_value=set(deployed)), \
             patch("yfinance.download", return_value=prices):
            result = compute_performance_review(source_date, db_path=tmp_path / "test.db")

        assert result.get("error") is None
        # Check ticker cohort assignments
        td = {t["ticker"]: t["cohort"] for t in result["ticker_data"]}
        assert td["AAA"] == "SCORED"
        assert td["EEE"] == "SCORED"
        assert td["BBB"] == "QUEUED"
        assert td["CCC"] == "ANALYZED"
        assert td["DDD"] == "DEPLOYED"


class TestFilterAlpha:
    def test_positive_filter_alpha(self, tmp_path):
        """When kept tickers outperform rejected, filter alpha is positive."""
        from tradingagents.dealflow.performance_tracker import compute_performance_review

        source_date = "2026-01-20"
        base = tmp_path / "eval_results" / "deal_flow" / source_date
        # Scored: LOW, LOW, LOW, HIGH, HIGH — queued picks HIGH
        symbols = ["LO1", "LO2", "LO3", "HI1", "HI2"]
        queued = ["HI1", "HI2"]

        _make_funnel_artifacts(base, symbols, queued, analyzed=[], deployed=[])

        returns_5d = {"LO1": -0.02, "LO2": -0.01, "LO3": 0.0, "HI1": 0.05, "HI2": 0.04, "QQQ": 0.01}
        prices = _mock_prices(symbols, "2026-01-20", returns_5d)

        with patch("tradingagents.dealflow.performance_tracker._DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow"), \
             patch("tradingagents.dealflow.performance_tracker._deployed_tickers", return_value=set()), \
             patch("yfinance.download", return_value=prices):
            result = compute_performance_review(source_date, db_path=tmp_path / "test.db")

        fa = result["filter_alpha"]["scored_to_queued_5d"]
        assert fa is not None
        assert fa > 0, f"Filter alpha should be positive, got {fa}"


class TestSignalFamilyIC:
    def test_known_ic(self, tmp_path):
        """Perfect rank correlation between raw_score and returns → IC near +1."""
        from tradingagents.dealflow.performance_tracker import compute_performance_review

        source_date = "2026-01-25"
        base = tmp_path / "eval_results" / "deal_flow" / source_date
        symbols = [f"T{i:02d}" for i in range(10)]
        base.mkdir(parents=True, exist_ok=True)

        # signals_raw: monotonically increasing raw_score
        signals = []
        for i, sym in enumerate(symbols):
            signals.append({
                "symbol": sym,
                "signal_family": "price_momentum",
                "raw_score": float(i * 10),
            })
        (base / "signals_raw.json").write_text(json.dumps(signals))

        scored = [{"symbol": sym, "status": "SCORED", "core_score": 50 + i}
                  for i, sym in enumerate(symbols)]
        (base / "all_scored_candidates.json").write_text(json.dumps(scored))
        (base / "research_queue.json").write_text(json.dumps({"items": []}))
        (base / "batch_analyze_latest.json").write_text(json.dumps({"items": []}))

        # Returns perfectly correlated with score rank
        returns_5d = {sym: 0.01 * i for i, sym in enumerate(symbols)}
        returns_5d["QQQ"] = 0.05
        prices = _mock_prices(symbols, "2026-01-25", returns_5d)

        with patch("tradingagents.dealflow.performance_tracker._DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow"), \
             patch("tradingagents.dealflow.performance_tracker._deployed_tickers", return_value=set()), \
             patch("yfinance.download", return_value=prices):
            result = compute_performance_review(source_date, db_path=tmp_path / "test.db")

        fic = {r["signal_family"]: r for r in result["signal_family_ic"]}
        assert "price_momentum" in fic
        ic = fic["price_momentum"]["ic"]
        assert ic is not None
        assert ic > 0.8, f"Expected IC near +1.0 with perfect correlation, got {ic}"


class TestEmptyStages:
    def test_no_crash_on_empty(self, tmp_path):
        """Empty stages (no queued/analyzed/deployed) produce None stats, no crash."""
        from tradingagents.dealflow.performance_tracker import compute_performance_review

        source_date = "2026-01-30"
        base = tmp_path / "eval_results" / "deal_flow" / source_date
        symbols = ["AAA", "BBB", "CCC"]
        _make_funnel_artifacts(base, symbols, queued=[], analyzed=[], deployed=[])

        returns_5d = {"AAA": 0.01, "BBB": 0.02, "CCC": -0.01, "QQQ": 0.005}
        prices = _mock_prices(symbols, "2026-01-30", returns_5d)

        with patch("tradingagents.dealflow.performance_tracker._DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow"), \
             patch("tradingagents.dealflow.performance_tracker._deployed_tickers", return_value=set()), \
             patch("yfinance.download", return_value=prices):
            result = compute_performance_review(source_date, db_path=tmp_path / "test.db")

        assert result.get("error") is None
        stages = result["stages"]
        assert stages["QUEUED"]["n"] == 0
        assert stages["QUEUED"]["mean_5d"] is None
        assert stages["ANALYZED"]["n"] == 0
        assert stages["DEPLOYED"]["n"] == 0
        assert stages["SCORED"]["n"] > 0


class TestLedgerEnrichment:
    def test_performance_review_enriches_stage_ledger_rows(self, tmp_path):
        """Performance review should write 5d/20d ledger metrics from realized returns."""
        from tradingagents.dealflow.performance_tracker import compute_performance_review

        source_date = "2026-01-20"
        base = tmp_path / "eval_results" / "deal_flow" / source_date
        symbols = ["LO1", "LO2", "LO3", "HI1", "HI2"]
        queued = ["HI1", "HI2"]

        _make_funnel_artifacts(base, symbols, queued, analyzed=[], deployed=[])
        _write_ledger_row(base, source_date, kept=["HI1", "HI2"], dropped=["LO1", "LO2", "LO3"])

        returns_5d = {"LO1": -0.02, "LO2": -0.01, "LO3": 0.0, "HI1": 0.05, "HI2": 0.04, "QQQ": 0.01}
        returns_20d = {"LO1": -0.04, "LO2": -0.02, "LO3": 0.01, "HI1": 0.12, "HI2": 0.08, "QQQ": 0.03}
        prices = _mock_prices(symbols, "2026-01-20", returns_5d, returns_20d)

        with patch("tradingagents.dealflow.performance_tracker._DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow"), \
             patch("tradingagents.dealflow.performance_tracker._deployed_tickers", return_value=set()), \
             patch("yfinance.download", return_value=prices):
            compute_performance_review(source_date, db_path=tmp_path / "test.db")

        rows = json.loads((base / "hypothesis_ledger" / "shared" / "rows.json").read_text())
        row = rows[0]
        assert row["edge_5d"] == 0.055
        assert row["edge_20d"] == 0.1167
        assert row["future_winner_recall"] == 1.0
        assert row["false_negative_cost"] == 0.0


class TestStageSummary:
    def test_performance_review_includes_hypothesis_stage_summary(self, tmp_path):
        from tradingagents.dealflow.performance_tracker import compute_performance_review

        source_date = "2026-01-20"
        base = tmp_path / "eval_results" / "deal_flow" / source_date
        symbols = ["LO1", "LO2", "LO3", "HI1", "HI2"]
        queued = ["HI1", "HI2"]

        _make_funnel_artifacts(base, symbols, queued, analyzed=[], deployed=[])
        _write_ledger_row(base, source_date, kept=["HI1", "HI2"], dropped=["LO1", "LO2", "LO3"])

        returns_5d = {"LO1": -0.02, "LO2": -0.01, "LO3": 0.0, "HI1": 0.05, "HI2": 0.04, "QQQ": 0.01}
        returns_20d = {"LO1": -0.04, "LO2": -0.02, "LO3": 0.01, "HI1": 0.12, "HI2": 0.08, "QQQ": 0.03}
        prices = _mock_prices(symbols, "2026-01-20", returns_5d, returns_20d)

        with patch("tradingagents.dealflow.performance_tracker._DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow"), \
             patch("tradingagents.dealflow.performance_tracker._deployed_tickers", return_value=set()), \
             patch("yfinance.download", return_value=prices):
            result = compute_performance_review(source_date, db_path=tmp_path / "test.db")

        summary = result["hypothesis_stage_summary"]
        assert summary["lane"] == "shared"
        assert summary["stages"][0]["stage_id"] == "shortlist_cut"
        assert summary["stages"][0]["edge_5d"] == 0.055
        assert summary["stages"][0]["edge_20d"] == 0.1167


class TestDiscoveryDeltaCohorts:
    def test_performance_review_includes_discovery_delta_cohorts(self, tmp_path):
        from tradingagents.dealflow.performance_tracker import compute_performance_review

        source_date = "2026-01-20"
        base = tmp_path / "eval_results" / "deal_flow" / source_date
        symbols = ["LO1", "LO2", "LO3", "HI1", "HI2"]
        queued = ["HI1", "HI2"]

        _make_funnel_artifacts(base, symbols, queued, analyzed=[], deployed=[])
        (base / "discovery_delta.json").write_text(
            json.dumps(
                {
                    "cohorts": {
                        "scout_only": ["LO1"],
                        "technical_only": ["LO2", "LO3"],
                        "multi_channel": ["HI1", "HI2"],
                    }
                }
            )
        )

        returns_5d = {"LO1": -0.02, "LO2": -0.01, "LO3": 0.0, "HI1": 0.05, "HI2": 0.04, "QQQ": 0.01}
        returns_20d = {"LO1": -0.04, "LO2": -0.02, "LO3": 0.01, "HI1": 0.12, "HI2": 0.08, "QQQ": 0.03}
        returns_3m = {"LO1": -0.08, "LO2": -0.03, "LO3": 0.02, "HI1": 0.2, "HI2": 0.16, "QQQ": 0.07}
        prices = _mock_prices(symbols, "2026-01-20", returns_5d, returns_20d, returns_3m)

        with patch("tradingagents.dealflow.performance_tracker._DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow"), \
             patch("tradingagents.dealflow.performance_tracker._deployed_tickers", return_value=set()), \
             patch("yfinance.download", return_value=prices):
            result = compute_performance_review(source_date, db_path=tmp_path / "test.db")

        cohorts = result["discovery_delta_cohorts"]
        assert cohorts["cohorts"]["multi_channel"]["mean_return_20d"] == 0.1
        assert cohorts["cohorts"]["multi_channel"]["mean_return_3m"] == 0.18
        assert cohorts["cohorts"]["multi_channel"]["shortlist_conversion"] == 1.0
        assert cohorts["cohorts"]["multi_channel"]["deep_selection_conversion"] == 0.0
        assert cohorts["comparisons"]["vs_other_cohorts"]["multi_channel"]["mean_return_3m_delta"] == 0.2225


class TestEvidenceIntegrityCohorts:
    def test_performance_review_includes_evidence_integrity_cohorts(self, tmp_path):
        from tradingagents.dealflow.performance_tracker import compute_performance_review

        source_date = "2026-01-20"
        base = tmp_path / "eval_results" / "deal_flow" / source_date
        symbols = ["LO1", "LO2", "LO3", "HI1", "HI2"]
        queued = ["HI1", "HI2"]

        _make_funnel_artifacts(base, symbols, queued, analyzed=[], deployed=[])
        (base / "evidence_integrity.json").write_text(
            json.dumps(
                {
                    "candidate_records": [
                        {"symbol": "LO1", "integrity_class": "LOW_SIGNAL"},
                        {"symbol": "LO2", "integrity_class": "DATA_DEGRADED"},
                        {"symbol": "LO3", "integrity_class": "CONFIRMED"},
                        {"symbol": "HI1", "integrity_class": "SPARSE_BUT_INTERESTING"},
                        {"symbol": "HI2", "integrity_class": "SPARSE_BUT_INTERESTING"},
                    ]
                }
            )
        )

        returns_5d = {"LO1": -0.02, "LO2": -0.01, "LO3": 0.0, "HI1": 0.05, "HI2": 0.04, "QQQ": 0.01}
        returns_20d = {"LO1": -0.04, "LO2": -0.02, "LO3": 0.01, "HI1": 0.12, "HI2": 0.08, "QQQ": 0.03}
        returns_3m = {"LO1": -0.08, "LO2": -0.03, "LO3": 0.02, "HI1": 0.2, "HI2": 0.16, "QQQ": 0.07}
        prices = _mock_prices(symbols, "2026-01-20", returns_5d, returns_20d, returns_3m)

        with patch("tradingagents.dealflow.performance_tracker._DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow"), \
             patch("tradingagents.dealflow.performance_tracker._deployed_tickers", return_value=set()), \
             patch("yfinance.download", return_value=prices):
            result = compute_performance_review(source_date, db_path=tmp_path / "test.db")

        cohorts = result["evidence_integrity_cohorts"]
        assert cohorts["cohorts"]["SPARSE_BUT_INTERESTING"]["count"] == 2
        assert cohorts["cohorts"]["SPARSE_BUT_INTERESTING"]["mean_return_20d"] == 0.1
        assert cohorts["cohorts"]["SPARSE_BUT_INTERESTING"]["deep_selection_conversion"] == 0.0
        assert "vs_other_cohorts" in cohorts["comparisons"]
