import json
import csv

from tradingagents.research.fundamental.src.features.llm_extraction import (
    CSV_FIELDS,
    result_schema,
    run_llm_batches,
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


def valid_payload_for(sample_id: str, ticker: str, quarter: str = "2024Q4"):
    return valid_payload(sample_id=sample_id, ticker=ticker, quarter=quarter)


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


def test_llm_batches_accept_same_sample_ids_when_model_reorders_results(tmp_path):
    packets = [
        {"sample_id": "AAA_2024Q4", "quarter": "2024Q4", "ticker": "AAA", "event_date": "2024-11-01"},
        {"sample_id": "BBB_2024Q4", "quarter": "2024Q4", "ticker": "BBB", "event_date": "2024-11-01"},
    ]

    def invoker(_prompt, _schema, _model, _reasoning_effort):
        return json.dumps({
            "results": [
                valid_payload_for("BBB_2024Q4", "BBB"),
                valid_payload_for("AAA_2024Q4", "AAA"),
            ]
        })

    rows = run_llm_batches(
        packets,
        output_dir=tmp_path / "llm_batches",
        invoker=invoker,
        model="test",
        reasoning_effort="low",
        batch_size=2,
    )

    assert [row["sample_id"] for row in rows] == ["AAA_2024Q4", "BBB_2024Q4"]


def test_llm_batches_ignore_stale_resume_file_when_batch_sample_ids_changed(tmp_path):
    output_dir = tmp_path / "llm_batches"
    output_dir.mkdir()
    (output_dir / "batch_0001.json").write_text(json.dumps([{"sample_id": "STALE_2024Q4"}]), encoding="utf-8")
    packets = [
        {"sample_id": "BBB_2024Q4", "quarter": "2024Q4", "ticker": "BBB", "event_date": "2024-11-01"},
    ]
    calls = 0

    def invoker(_prompt, _schema, _model, _reasoning_effort):
        nonlocal calls
        calls += 1
        return json.dumps({"results": [valid_payload_for("BBB_2024Q4", "BBB")]})

    rows = run_llm_batches(
        packets,
        output_dir=output_dir,
        invoker=invoker,
        model="test",
        reasoning_effort="low",
        batch_size=1,
    )

    assert calls == 1
    assert [row["sample_id"] for row in rows] == ["BBB_2024Q4"]


def test_in_session_llm_writes_returned_rows_not_stale_batch_directory(tmp_path, monkeypatch):
    from tradingagents.research.fundamental.src.cli import commands
    from tradingagents.research.fundamental.src.features import llm_extraction
    from tradingagents.research.fundamental.src import storage

    packets_path = tmp_path / "packets.jsonl"
    packets_path.write_text(
        json.dumps({"sample_id": "BBB_2024Q4", "quarter": "2024Q4", "ticker": "BBB", "event_date": "2024-11-01"}) + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "llm_batches"
    output_dir.mkdir()
    (output_dir / "batch_0001.json").write_text(json.dumps([{"sample_id": "STALE_2024Q4"}]), encoding="utf-8")
    output_csv = tmp_path / "post_llm_scores.csv"
    current_row = validate_llm_result(
        valid_payload_for("BBB_2024Q4", "BBB"),
        {"sample_id": "BBB_2024Q4", "quarter": "2024Q4", "ticker": "BBB", "event_date": "2024-11-01"},
    )

    def fake_run_llm_batches(*_args, **_kwargs):
        return [current_row]

    monkeypatch.setattr(llm_extraction, "run_llm_batches", fake_run_llm_batches)
    monkeypatch.setattr(storage, "write_table", lambda *_args, **_kwargs: None)

    commands._run_in_session_llm(
        packets_path=packets_path,
        output_dir=output_dir,
        output_csv=output_csv,
        lake_root=tmp_path / "lake",
        as_of="2024-12-31",
        model="test",
        reasoning_effort="low",
        batch_size=1,
    )

    rows = list(csv.DictReader(output_csv.open()))
    assert [row["sample_id"] for row in rows] == ["BBB_2024Q4"]
