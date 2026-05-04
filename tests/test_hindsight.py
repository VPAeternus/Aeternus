"""Tests for tradingagents.dealflow.hindsight."""

import json
import math
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dealflow.hypothesis_ledger import append_ledger_row, make_ledger_row


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

def _signals_raw():
    """Synthetic signals_raw with 6 tickers across multiple families."""
    families = ["social_momentum", "news_catalyst", "macro_regime_fit", "smart_money"]
    tickers = ["AAPL", "NVDA", "GOOGL", "ARM", "PLTR", "XYZ"]
    signals = []
    for sym in tickers:
        # XYZ only has 1 family → LOW_DATA
        fams = families[:1] if sym == "XYZ" else families
        for fam in fams:
            signals.append({
                "symbol": sym,
                "signal_family": fam,
                "raw_score": 80.0,
                "z_score": 0.5,
                "direction": "BULLISH",
                "evidence_count": 100,
                "freshness_hours": 24.0,
                "source_status": "OK",
                "source_name": "test",
            })
    return signals


def _research_queue():
    """Research queue: AAPL, NVDA selected_for_deep; GOOGL not; ARM/PLTR/XYZ absent."""
    return {
        "run_id": "test-run",
        "date": "2026-02-20",
        "items": [
            {"symbol": "AAPL", "deal_flow_score": 70.0, "momentum_score": 55.0,
             "triage_score": 80.0, "selected_for_deep": True, "lane": "CORE"},
            {"symbol": "NVDA", "deal_flow_score": 65.0, "momentum_score": 60.0,
             "triage_score": 75.0, "selected_for_deep": True, "lane": "CORE"},
            {"symbol": "GOOGL", "deal_flow_score": 60.0, "momentum_score": 50.0,
             "triage_score": 70.0, "selected_for_deep": False, "lane": "CORE"},
        ],
    }


def _batch_analyze():
    """Batch analyze: AAPL and NVDA analyzed successfully."""
    return {
        "queue_date": "2026-02-20",
        "analyzed_count": 2,
        "items": [
            {"symbol": "AAPL", "status": "SUCCESS", "recommendation": "BUY",
             "aeternus_score": 62.5, "confidence": 4},
            {"symbol": "NVDA", "status": "SUCCESS", "recommendation": "HOLD",
             "aeternus_score": 58.0, "confidence": 3},
        ],
    }


def _portfolio_plan():
    """Portfolio plan with only AAPL deployed."""
    return {
        "plan_id": "test-plan",
        "date": "2026-02-20",
        "orders": [
            {"symbol": "AAPL", "side": "BUY", "target_weight": 0.25},
        ],
    }


def _mock_prices():
    """Return a DataFrame mimicking yf.download() for 6 tickers + QQQ."""
    dates = pd.bdate_range("2026-02-20", periods=6)
    tickers = ["AAPL", "NVDA", "GOOGL", "ARM", "PLTR", "XYZ", "QQQ"]
    # Base prices at T+0, returns at T+5
    base = {"AAPL": 200, "NVDA": 150, "GOOGL": 170, "ARM": 130, "PLTR": 25, "XYZ": 10, "QQQ": 500}
    # 5-day returns: AAPL +5%, NVDA +2%, GOOGL +1%, ARM +8%, PLTR -3%, XYZ +1%, QQQ +1%
    ret5 = {"AAPL": 0.05, "NVDA": 0.02, "GOOGL": 0.01, "ARM": 0.08, "PLTR": -0.03, "XYZ": 0.01, "QQQ": 0.01}
    data = {}
    for sym in tickers:
        p0 = base[sym]
        p5 = p0 * (1 + ret5[sym])
        # Linear interpolation for intermediate days
        data[sym] = [p0 + (p5 - p0) * i / 5 for i in range(6)]
    close_df = pd.DataFrame(data, index=dates)
    # Build MultiIndex columns like yf.download returns
    arrays = [["Close"] * len(tickers), tickers]
    tuples = list(zip(*arrays))
    idx = pd.MultiIndex.from_tuples(tuples)
    result = pd.DataFrame(close_df.values, index=dates, columns=idx)
    return result


def _write_artifacts(tmp_path: Path, source_date: str = "2026-02-20"):
    """Write all deal-flow artifacts to tmp_path-based directories."""
    df_dir = tmp_path / "eval_results" / "deal_flow" / source_date
    df_dir.mkdir(parents=True)
    (df_dir / "signals_raw.json").write_text(json.dumps(_signals_raw()))
    (df_dir / "research_queue.json").write_text(json.dumps(_research_queue()))
    (df_dir / "batch_analyze_latest.json").write_text(json.dumps(_batch_analyze()))

    plans_dir = tmp_path / "eval_results" / "paper_execution" / "plans" / source_date
    plans_dir.mkdir(parents=True)
    (plans_dir / "portfolio_plan_120000.json").write_text(json.dumps(_portfolio_plan()))


def _write_ledger_row(base: Path, source_date: str = "2026-02-20"):
    row = make_ledger_row(
        run_id=f"{source_date}-120000-manual",
        source_date=source_date,
        lane="shared",
        stage_id="shortlist_cut",
        rule_snapshot={"top_k": 2},
        kept_symbols=["AAPL", "NVDA"],
        dropped_symbols=["ARM", "PLTR"],
        base_dir=base,
    )
    append_ledger_row(base_dir=base, lane="shared", row=row)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCohortAssignment:
    def test_cohort_labels(self, tmp_path, monkeypatch):
        _write_artifacts(tmp_path)
        import tradingagents.dealflow.hindsight as mod
        monkeypatch.setattr(mod, "_DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow")
        monkeypatch.setattr(mod, "_PLANS_DIR", tmp_path / "eval_results" / "paper_execution" / "plans")
        monkeypatch.setattr(mod.yf, "download", lambda *a, **kw: _mock_prices())

        result = mod.compute_hindsight("2026-02-20", benchmark="QQQ")

        cohort_map = {t["ticker"]: t["cohort"] for t in result["ticker_returns"]}
        assert cohort_map["AAPL"] == "DEPLOYED"
        assert cohort_map["NVDA"] == "ANALYZED"
        assert cohort_map["GOOGL"] == "QUEUED"
        assert cohort_map["ARM"] == "FILTERED"
        assert cohort_map["PLTR"] == "FILTERED"
        assert cohort_map["XYZ"] == "LOW_DATA"

    def test_cohort_stats(self, tmp_path, monkeypatch):
        _write_artifacts(tmp_path)
        import tradingagents.dealflow.hindsight as mod
        monkeypatch.setattr(mod, "_DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow")
        monkeypatch.setattr(mod, "_PLANS_DIR", tmp_path / "eval_results" / "paper_execution" / "plans")
        monkeypatch.setattr(mod.yf, "download", lambda *a, **kw: _mock_prices())

        result = mod.compute_hindsight("2026-02-20", benchmark="QQQ")

        deployed = result["cohorts"]["DEPLOYED"]
        assert deployed["count"] == 1
        assert abs(deployed["mean_return"] - 0.05) < 0.001

        filtered = result["cohorts"]["FILTERED"]
        assert filtered["count"] == 2  # ARM and PLTR


class TestRankIC:
    def test_ic_with_synthetic_data(self, tmp_path, monkeypatch):
        _write_artifacts(tmp_path)
        import tradingagents.dealflow.hindsight as mod
        monkeypatch.setattr(mod, "_DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow")
        monkeypatch.setattr(mod, "_PLANS_DIR", tmp_path / "eval_results" / "paper_execution" / "plans")
        monkeypatch.setattr(mod.yf, "download", lambda *a, **kw: _mock_prices())

        result = mod.compute_hindsight("2026-02-20", benchmark="QQQ")
        ic = result["rank_ic"]
        # With only 3 scored tickers (< 5), IC should be None
        assert ic["core_score"] is None


class TestMissedOpportunities:
    def test_arm_flagged(self, tmp_path, monkeypatch):
        _write_artifacts(tmp_path)
        import tradingagents.dealflow.hindsight as mod
        monkeypatch.setattr(mod, "_DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow")
        monkeypatch.setattr(mod, "_PLANS_DIR", tmp_path / "eval_results" / "paper_execution" / "plans")
        monkeypatch.setattr(mod.yf, "download", lambda *a, **kw: _mock_prices())

        result = mod.compute_hindsight("2026-02-20", benchmark="QQQ")

        missed = result["missed_opportunities"]
        missed_tickers = {m["ticker"] for m in missed}
        # ARM: 8% return, QQQ: 1% → edge 7% > 2% threshold
        assert "ARM" in missed_tickers
        # PLTR: -3% return → not missed
        assert "PLTR" not in missed_tickers


class TestMissingPriceData:
    def test_graceful_on_empty_download(self, tmp_path, monkeypatch):
        _write_artifacts(tmp_path)
        import tradingagents.dealflow.hindsight as mod
        monkeypatch.setattr(mod, "_DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow")
        monkeypatch.setattr(mod, "_PLANS_DIR", tmp_path / "eval_results" / "paper_execution" / "plans")
        monkeypatch.setattr(mod.yf, "download", lambda *a, **kw: pd.DataFrame())

        result = mod.compute_hindsight("2026-02-20", benchmark="QQQ")
        assert "error" in result

    def test_missing_batch_analyze(self, tmp_path, monkeypatch):
        """Handles missing batch_analyze_latest.json gracefully."""
        _write_artifacts(tmp_path)
        (tmp_path / "eval_results" / "deal_flow" / "2026-02-20" / "batch_analyze_latest.json").unlink()
        import tradingagents.dealflow.hindsight as mod
        monkeypatch.setattr(mod, "_DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow")
        monkeypatch.setattr(mod, "_PLANS_DIR", tmp_path / "eval_results" / "paper_execution" / "plans")
        monkeypatch.setattr(mod.yf, "download", lambda *a, **kw: _mock_prices())

        result = mod.compute_hindsight("2026-02-20", benchmark="QQQ")
        # Should still work — DEPLOYED is from portfolio plan, not batch
        assert "error" not in result
        assert result["cohorts"]["DEPLOYED"]["count"] == 1  # AAPL still in plan


class TestBenchmarkReturn:
    def test_benchmark_return_value(self, tmp_path, monkeypatch):
        _write_artifacts(tmp_path)
        import tradingagents.dealflow.hindsight as mod
        monkeypatch.setattr(mod, "_DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow")
        monkeypatch.setattr(mod, "_PLANS_DIR", tmp_path / "eval_results" / "paper_execution" / "plans")
        monkeypatch.setattr(mod.yf, "download", lambda *a, **kw: _mock_prices())

        result = mod.compute_hindsight("2026-02-20", benchmark="QQQ")
        assert abs(result["benchmark_return_5d"] - 0.01) < 0.001


class TestLedgerEnrichment:
    def test_hindsight_enriches_stage_ledger_rows(self, tmp_path, monkeypatch):
        source_date = "2026-02-20"
        _write_artifacts(tmp_path, source_date=source_date)
        base = tmp_path / "eval_results" / "deal_flow" / source_date
        _write_ledger_row(base, source_date=source_date)

        import tradingagents.dealflow.hindsight as mod

        monkeypatch.setattr(mod, "_DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow")
        monkeypatch.setattr(mod, "_PLANS_DIR", tmp_path / "eval_results" / "paper_execution" / "plans")
        monkeypatch.setattr(mod.yf, "download", lambda *a, **kw: _mock_prices())

        mod.compute_hindsight(source_date, benchmark="QQQ")

        rows_path = base / "hypothesis_ledger" / "shared" / "rows.json"
        rows = json.loads(rows_path.read_text())
        row = rows[0]
        assert row["kept_mean_return_5d"] == 0.035
        assert row["dropped_mean_return_5d"] == 0.025


class TestEvidenceIntegrityCohorts:
    def test_hindsight_includes_evidence_integrity_cohorts(self, tmp_path, monkeypatch):
        from tradingagents.dealflow.hindsight import compute_hindsight

        _write_artifacts(tmp_path)
        base = tmp_path / "eval_results" / "deal_flow" / "2026-02-20"
        (base / "evidence_integrity.json").write_text(
            json.dumps(
                {
                    "candidate_records": [
                        {"symbol": "AAPL", "integrity_class": "CONFIRMED"},
                        {"symbol": "NVDA", "integrity_class": "SPARSE_BUT_INTERESTING"},
                        {"symbol": "GOOGL", "integrity_class": "DATA_DEGRADED"},
                        {"symbol": "ARM", "integrity_class": "LOW_SIGNAL"},
                    ]
                }
            )
        )

        monkeypatch.setattr("tradingagents.dealflow.hindsight._DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow")
        monkeypatch.setattr("tradingagents.dealflow.hindsight._PLANS_DIR", tmp_path / "eval_results" / "paper_execution" / "plans")
        monkeypatch.setattr("tradingagents.dealflow.hindsight.yf.download", lambda *a, **kw: _mock_prices())

        result = compute_hindsight("2026-02-20", benchmark="QQQ")

        cohorts = result["evidence_integrity_cohorts"]
        assert cohorts["cohorts"]["SPARSE_BUT_INTERESTING"]["count"] == 1
        assert cohorts["cohorts"]["SPARSE_BUT_INTERESTING"]["shortlist_conversion"] == 1.0
        assert "vs_step2_baseline" in cohorts["comparisons"]


class TestStageSummary:
    def test_hindsight_includes_hypothesis_stage_summary(self, tmp_path, monkeypatch):
        source_date = "2026-02-20"
        _write_artifacts(tmp_path, source_date=source_date)
        base = tmp_path / "eval_results" / "deal_flow" / source_date
        _write_ledger_row(base, source_date=source_date)

        import tradingagents.dealflow.hindsight as mod

        monkeypatch.setattr(mod, "_DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow")
        monkeypatch.setattr(mod, "_PLANS_DIR", tmp_path / "eval_results" / "paper_execution" / "plans")
        monkeypatch.setattr(mod.yf, "download", lambda *a, **kw: _mock_prices())

        result = mod.compute_hindsight(source_date, benchmark="QQQ")

        summary = result["hypothesis_stage_summary"]
        assert summary["lane"] == "shared"
        assert summary["stages"][0]["stage_id"] == "shortlist_cut"
        assert summary["stages"][0]["edge_5d"] == 0.01
        assert summary["stages"][0]["kept_count"] == 2


class TestDiscoveryDeltaCohorts:
    def test_hindsight_includes_discovery_delta_cohorts(self, tmp_path, monkeypatch):
        source_date = "2026-02-20"
        _write_artifacts(tmp_path, source_date=source_date)
        base = tmp_path / "eval_results" / "deal_flow" / source_date
        (base / "discovery_delta.json").write_text(
            json.dumps(
                {
                    "cohorts": {
                        "scout_only": ["ARM"],
                        "technical_only": ["GOOGL"],
                        "multi_channel": ["AAPL", "NVDA"],
                    }
                }
            )
        )

        import tradingagents.dealflow.hindsight as mod

        monkeypatch.setattr(mod, "_DEAL_FLOW_DIR", tmp_path / "eval_results" / "deal_flow")
        monkeypatch.setattr(mod, "_PLANS_DIR", tmp_path / "eval_results" / "paper_execution" / "plans")
        monkeypatch.setattr(mod.yf, "download", lambda *a, **kw: _mock_prices())

        result = mod.compute_hindsight(source_date, benchmark="QQQ")

        cohorts = result["discovery_delta_cohorts"]
        assert cohorts["cohorts"]["multi_channel"]["count"] == 2
        assert cohorts["cohorts"]["multi_channel"]["mean_return_5d"] == 0.035
        assert cohorts["cohorts"]["multi_channel"]["shortlist_conversion"] == 1.0
        assert cohorts["cohorts"]["multi_channel"]["deep_selection_conversion"] == 1.0
        assert cohorts["step1_baseline"]["count"] == 6
        assert cohorts["comparisons"]["vs_step1_baseline"]["multi_channel"]["mean_return_5d_delta"] == 0.0117
