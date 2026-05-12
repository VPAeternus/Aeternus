import csv
from tradingagents.research.fundamental.src.daily_run.llm_validation import validate_post_llm_csv
from tradingagents.research.fundamental.src.daily_run.models import GateStatus


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def test_validate_post_llm_csv_passes_one_row_per_packet(tmp_path):
    path = tmp_path / "post_llm_scores.csv"
    _write_csv(path, [{"sample_id": "AAA_2026Q2", "ticker": "AAA", "quarter": "2026Q2", "post_llm_candidate_flag": "1", "post_llm_high_priority_flag": "1", "post_llm_demote_flag": "0", "causal_change": "3", "negative_revision_risk": "1", "narrative_delta_bucket": "constructive", "operating_leverage_quality": "1", "durability": "1", "proof_alignment": "2"}])
    result = validate_post_llm_csv(path, expected_sample_ids={"AAA_2026Q2"})
    assert result.status == GateStatus.PASS
    assert result.summary["completed_count"] == 1


def test_validate_post_llm_csv_hard_stops_on_missing_sample_id(tmp_path):
    path = tmp_path / "post_llm_scores.csv"
    _write_csv(path, [{"sample_id": "AAA_2026Q2", "ticker": "AAA", "quarter": "2026Q2", "post_llm_candidate_flag": "1", "post_llm_high_priority_flag": "1", "post_llm_demote_flag": "0", "causal_change": "3", "negative_revision_risk": "1", "narrative_delta_bucket": "constructive", "operating_leverage_quality": "1", "durability": "1", "proof_alignment": "2"}])
    result = validate_post_llm_csv(path, expected_sample_ids={"AAA_2026Q2", "BBB_2026Q2"})
    assert result.status == GateStatus.HARD_STOP
    assert result.summary["missing_sample_ids"] == ["BBB_2026Q2"]
