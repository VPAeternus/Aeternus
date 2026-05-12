from tradingagents.research.fundamental.src.daily_run.finalize import build_final_scores, validate_broad_final_scores
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


def test_validate_broad_final_scores_hard_stops_on_unreconciled_row_loss():
    gate = validate_broad_final_scores(final_rows=[{"ticker": f"S{i}"} for i in range(162)], broad_universe_count=1276, explicit_invalid_quarantine_count=3, run_mode=RunMode.BROAD_MASTER_FINAL, artifacts={})
    assert gate.status == GateStatus.HARD_STOP
    assert gate.summary["reason"] == "final_scores_plus_quarantine_do_not_reconcile_to_broad_universe"


def test_validate_broad_final_scores_passes_when_rows_plus_explicit_quarantine_reconcile():
    gate = validate_broad_final_scores(final_rows=[{"ticker": f"T{i}"} for i in range(4)], broad_universe_count=5, explicit_invalid_quarantine_count=1, run_mode=RunMode.BROAD_MASTER_FINAL, artifacts={})
    assert gate.status == GateStatus.PASS
