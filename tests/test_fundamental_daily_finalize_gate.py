from tradingagents.research.fundamental.src.daily_run.finalize import build_final_scores, publish_top15_and_shadow, validate_broad_final_scores
from tradingagents.research.fundamental.src.daily_run.models import GateStatus, RunMode


def _base(ticker, entry_open="12"):
    return {"ticker": ticker, "quarter": "2026Q2", "tradable_date": "2026-05-11", "entry_open": entry_open, "revenue_bucket": "$500M-$1B", "pre_llm_fundamental_score": "3", "pre_llm_fundamental_bucket": "good"}


def test_build_final_scores_preserves_broad_rows_when_post_llm_is_subset():
    broad = [_base("AAA"), _base("BBB", entry_open="20")]
    post_llm = [{"ticker": "AAA", "quarter": "2026Q2", "post_llm_candidate_flag": "1", "causal_change": "3", "negative_revision_risk": "1", "narrative_delta_bucket": "constructive", "operating_leverage_quality": "1", "durability": "1", "proof_alignment": "2"}]
    rows, summary = build_final_scores(broad, as_of="2026-05-12", post_llm_rows=post_llm)
    assert [row["ticker"] for row in rows] == ["AAA", "BBB"]
    assert summary["final_score_rows"] == 2
    assert "entry_score_0_100" in rows[0]
    assert "hp_structure_score" in rows[0]
    assert "rm_buy_review_flag" in rows[0]
    assert rows[0]["score_producing_flag"] == "1"
    assert rows[0]["accepted_row_flag"] == "1"
    assert rows[0]["diagnostic_only_flag"] == "0"


def test_build_final_scores_does_not_let_post_llm_overwrite_fresh_price_fields():
    broad = [_base("AAA")]
    post_llm = [
        {
            "ticker": "AAA",
            "quarter": "2026Q2",
            "tradable_date": "5/10/26",
            "entry_open": "999",
            "pre_llm_fundamental_score": "-4",
            "post_llm_candidate_flag": "1",
            "post_llm_high_priority_flag": "1",
            "post_llm_demote_flag": "0",
            "causal_change": "3",
            "negative_revision_risk": "1",
            "narrative_delta_bucket": "constructive",
            "operating_leverage_quality": "1",
            "durability": "1",
            "proof_alignment": "2",
        }
    ]
    rows, summary = build_final_scores(broad, as_of="2026-05-12", post_llm_rows=post_llm)
    assert rows[0]["tradable_date"] == "2026-05-11"
    assert float(rows[0]["entry_open"]) == 12
    assert float(rows[0]["pre_llm_fundamental_score"]) == 3
    assert rows[0]["llm_status"] == "complete"
    assert summary["final_score_rows"] == 1


def _valid_prior_summary():
    return {"prior_context_loaded": True, "expected_prior_context_rows": 4, "prior_duplicate_key_count": 0}


def test_validate_broad_final_scores_hard_stops_on_unreconciled_row_loss():
    gate = validate_broad_final_scores(final_rows=[{"ticker": f"S{i}"} for i in range(162)], broad_universe_count=1276, explicit_invalid_quarantine_count=3, run_mode=RunMode.BROAD_MASTER_FINAL, artifacts={}, prior_context_summary=_valid_prior_summary())
    assert gate.status == GateStatus.HARD_STOP
    assert gate.summary["reason"] == "final_scores_plus_quarantine_do_not_reconcile_to_broad_universe"


def test_validate_broad_final_scores_passes_when_rows_plus_explicit_quarantine_reconcile():
    gate = validate_broad_final_scores(final_rows=[{"ticker": f"T{i}"} for i in range(4)], broad_universe_count=5, explicit_invalid_quarantine_count=1, run_mode=RunMode.BROAD_MASTER_FINAL, artifacts={}, prior_context_summary=_valid_prior_summary())
    assert gate.status == GateStatus.PASS


def test_validate_broad_final_scores_hard_stops_without_prior_context():
    gate = validate_broad_final_scores(final_rows=[{"ticker": "T0"}], broad_universe_count=1, explicit_invalid_quarantine_count=0, run_mode=RunMode.BROAD_MASTER_FINAL, artifacts={})
    assert gate.status == GateStatus.HARD_STOP
    assert gate.summary["reason"] == "missing_prior_final_scores"


def test_validate_broad_final_scores_hard_stops_when_llm_complete_qoq_missing():
    rows = [{"ticker": "AAA", "llm_status": "complete", "entry_qoq_pct": "", "score_change": "1", "prior_pre_llm_fundamental_score": "3"}]
    gate = validate_broad_final_scores(final_rows=rows, broad_universe_count=1, explicit_invalid_quarantine_count=0, run_mode=RunMode.BROAD_MASTER_FINAL, artifacts={}, prior_context_summary=_valid_prior_summary())
    assert gate.status == GateStatus.HARD_STOP
    assert gate.summary["reason"] == "llm_complete_rows_missing_qoq_context"
    assert gate.summary["llm_complete_qoq_missing_tickers"] == ["AAA"]


def test_validate_broad_final_scores_allows_qoq_missing_when_prior_filing_impossible():
    rows = [{"ticker": "AAA", "llm_status": "complete", "entry_qoq_pct": "", "score_change": "1", "prior_pre_llm_fundamental_score": "3"}]
    prior = {**_valid_prior_summary(), "prior_llm_extract_impossible_no_filings_tickers": ["AAA"]}
    gate = validate_broad_final_scores(final_rows=rows, broad_universe_count=1, explicit_invalid_quarantine_count=0, run_mode=RunMode.BROAD_MASTER_FINAL, artifacts={}, prior_context_summary=prior)
    assert gate.status == GateStatus.PASS
    assert gate.summary["llm_complete_qoq_missing_rows"] == 0
    assert gate.summary["llm_complete_qoq_allowed_missing_tickers"] == ["AAA"]


def test_publish_passes_coverage_gating_to_top15_and_shadow(tmp_path, monkeypatch):
    from tradingagents.research.fundamental.src.selection import high_conviction_top10

    scores = tmp_path / "scores.csv"
    scores.write_text("ticker,quarter\nAAA,2026Q2\n", encoding="utf-8")
    coverage = tmp_path / "coverage.csv"
    coverage.write_text("ticker,quarter,coverage_status\nAAA,2026Q2,CACHED_READY\n", encoding="utf-8")
    seen = {}

    def fake_top15(scores_csv, output_root, config, coverage_manifest=None):
        seen["top15"] = config
        return {"selected_rows": [{"ticker": "AAA"}], "output_paths": {}}

    def fake_shadow(scores_csv, output_root, config, coverage_manifest=None):
        seen["shadow"] = config
        return {"selected_rows": [{"ticker": "AAA"}], "output_paths": {}}

    monkeypatch.setattr(high_conviction_top10, "select_top15_from_csv", fake_top15)
    monkeypatch.setattr(high_conviction_top10, "select_top15_core_deterioration_refill_shadow_from_csv", fake_shadow)

    gate = publish_top15_and_shadow(
        scores_csv=scores,
        output_root=tmp_path,
        as_of="2026-05-12",
        broad_universe_count=1,
        coverage_manifest=coverage,
    )

    assert gate.status == GateStatus.PASS
    assert seen["top15"]["coverage_gating"] is True
    assert seen["shadow"]["coverage_gating"] is True
