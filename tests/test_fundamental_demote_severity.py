from tradingagents.research.fundamental.src.features.llm_extraction import (
    CSV_FIELDS,
    result_schema,
    validate_llm_result,
)
from tradingagents.research.fundamental.src.features.post_llm_scores import classify_llm_status


def packet():
    return {"sample_id": "AAA_2024Q4", "quarter": "2024Q4", "ticker": "AAA", "event_date": "2024-11-01"}


def valid_payload(**extra):
    base = {
        "sample_id": "AAA_2024Q4",
        "quarter": "2024Q4",
        "ticker": "AAA",
        "event_date": "2024-11-01",
        "causal_change": 1,
        "proof_alignment": 1,
        "durability": 1,
        "operating_leverage_quality": 1,
        "negative_revision_risk": 1,
        "story_vs_numbers_gap_penalty": 0,
        "narrative_delta_score": 0,
        "narrative_delta_bucket": "neutral",
        "score_addition": 0,
        "detected_driver_category": "turnaround",
        "detected_driver_name": "cyclical trough",
        "evidence_positive": "evidence",
        "evidence_risk": "risk",
        "confidence": "medium",
        "blocking_issues": "",
        "primary_theme": "",
        "secondary_themes": [],
        "theme_tags": [],
        "theme_role": "none",
        "theme_confidence": "none",
        "theme_driver_type": "none",
        "theme_momentum": "unknown",
        "theme_evidence": [],
        "filing_theme_growth_flag": 0,
        "filing_theme_guidance_flag": 0,
        "filing_theme_margin_flag": 0,
        "filing_theme_customer_win_flag": 0,
        "filing_theme_capacity_expansion_flag": 0,
        "theme_acceleration_score": 0,
        "theme_tailwind_score": 0,
        "theme_driver_summary": "",
        "theme_evidence_summary": "",
        "post_llm_demote_severity": "none",
        "post_llm_demote_reason_code": "",
        "post_llm_demote_overrideable": 0,
        "post_llm_demote_evidence": "",
    }
    base.update(extra)
    return base


def test_llm_schema_declares_demote_severity_fields():
    item = result_schema()["properties"]["results"]["items"]
    for field in [
        "post_llm_demote_severity",
        "post_llm_demote_reason_code",
        "post_llm_demote_overrideable",
        "post_llm_demote_evidence",
    ]:
        assert field in CSV_FIELDS
        assert field in item["properties"]
        assert field in item["required"]


def test_demote_severity_forces_old_demote_flag():
    out = validate_llm_result(valid_payload(
        negative_revision_risk=1,
        story_vs_numbers_gap_penalty=0,
        narrative_delta_bucket="neutral",
        post_llm_demote_severity="hard",
        post_llm_demote_reason_code="fraud_or_integrity",
        post_llm_demote_overrideable=0,
        post_llm_demote_evidence="integrity issue",
    ), packet())
    assert out["post_llm_demote_flag"] == 1
    assert out["post_llm_demote_severity"] == "hard"


def test_none_severity_blanks_reason_and_evidence_when_no_deterministic_demote():
    out = validate_llm_result(valid_payload(
        post_llm_demote_severity="none",
        post_llm_demote_reason_code="weak_fundamentals",
        post_llm_demote_evidence="stale text",
        post_llm_demote_overrideable=1,
        negative_revision_risk=1,
        story_vs_numbers_gap_penalty=0,
        narrative_delta_bucket="neutral",
    ), packet())
    assert out["post_llm_demote_flag"] == 0
    assert out["post_llm_demote_reason_code"] == ""
    assert out["post_llm_demote_evidence"] == ""
    assert out["post_llm_demote_overrideable"] == 0


def test_old_rows_default_demote_fields_safely():
    row = {"repricing_momentum_extension": "1"}
    llm = {
        "post_llm_demote_flag": "1",
        "post_llm_candidate_flag": "0",
        "post_llm_high_priority_flag": "0",
        "causal_change": 1,
        "negative_revision_risk": 4,
        "narrative_delta_bucket": "neutral",
        "operating_leverage_quality": 1,
        "durability": 1,
        "proof_alignment": 1,
    }
    out = classify_llm_status(row, llm)
    assert out["post_llm_demote_severity"] == "unknown"
    assert out["post_llm_demote_reason_code"] == ""
    assert out["post_llm_demote_overrideable"] == 0
    assert out["post_llm_demote_evidence"] == ""
