import pytest

from tradingagents.research.fundamental.src.features.llm_extraction import validate_llm_result
from tradingagents.research.fundamental.src.features.llm_packets import build_llm_packets
from tradingagents.research.fundamental.src.features.post_llm_scores import classify_llm_status


def _payload(**extra):
    base = {
        "sample_id": "AAA_2026Q2",
        "quarter": "2026Q2",
        "ticker": "AAA",
        "event_date": "2026-05-01",
        "causal_change": 3,
        "proof_alignment": 3,
        "durability": 2,
        "operating_leverage_quality": 2,
        "negative_revision_risk": 1,
        "story_vs_numbers_gap_penalty": 0,
        "narrative_delta_bucket": "constructive",
        "post_llm_candidate_flag": 1,
        "post_llm_high_priority_flag": 1,
        "post_llm_demote_flag": 0,
        "post_llm_demote_severity": "none",
        "post_llm_demote_reason_code": "",
        "post_llm_demote_overrideable": 0,
        "post_llm_demote_evidence": "",
        "detected_driver_category": "demand",
        "detected_driver_name": "enterprise demand",
        "evidence_positive": "orders improved",
        "evidence_risk": "",
        "confidence": "high",
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
    }
    base.update(extra)
    return base


def _packet(**extra):
    base = {
        "sample_id": "AAA_2026Q2",
        "quarter": "2026Q2",
        "ticker": "AAA",
        "decision_date": "2026-05-10",
        "llm_source_document_dates": "2026-05-01;2026-05-02",
        "llm_source_accessions": "0001;0002",
        "llm_prompt_input_allowed_docs_only": "1",
    }
    base.update(extra)
    return base


def test_classify_complete_llm_derives_legacy_score_fields():
    row = {"tier_1_bucket": "Tier 1"}
    out = classify_llm_status(row, _payload())

    assert out["llm_status"] == "complete"
    assert out["post_llm_fundamental_score"] == "9"
    assert out["post_llm_fundamental_bucket"] == "inflecting"
    assert out["post_llm_fundamental_score_source"] == "derived_from_llm_components"


def test_llm_complete_rejects_future_source_document():
    with pytest.raises(ValueError, match="future LLM source document"):
        validate_llm_result(
            _payload(),
            _packet(llm_source_document_dates="2026-05-01;2026-05-11"),
        )


def test_llm_generated_later_allowed_when_inputs_are_pit():
    out = validate_llm_result(
        _payload(llm_generated_at="2026-06-01T00:00:00Z", llm_model="gpt-5.5"),
        _packet(),
    )

    assert out["llm_generated_at"] == "2026-06-01T00:00:00Z"
    assert out["llm_model"] == "gpt-5.5"
    assert out["llm_source_available_date"] == "2026-05-02"


def test_llm_packet_records_allowed_source_documents_only():
    packets = build_llm_packets(
        [{"ticker": "AAA", "quarter": "2026Q2", "decision_date": "2026-05-10"}],
        [
            {"ticker": "AAA", "quarter": "2026Q2", "document_type": "earnings_exhibit", "accession": "0001", "document_name": "ex99.htm", "filing_date": "2026-05-01", "clean_text": "good"},
            {"ticker": "AAA", "quarter": "2026Q2", "document_type": "later_news", "accession": "NEWS", "document_name": "news.htm", "filing_date": "2026-05-20", "clean_text": "bad"},
        ],
    )

    assert packets[0]["llm_prompt_input_allowed_docs_only"] == "1"
    assert packets[0]["llm_source_accessions"] == "0001"
    assert packets[0]["llm_source_document_dates"] == "2026-05-01"
