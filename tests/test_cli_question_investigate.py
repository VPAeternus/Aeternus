import sys
import types
from unittest.mock import patch

from typer.testing import CliRunner

# Stub chromadb before it can be imported (pydantic v1 incompatible with Python 3.14)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from cli.main import app


runner = CliRunner()


def test_question_investigate_json_runs_internal_pipeline_only():
    compiled = {
        "query_type": "reverse_forensic",
        "intent": "missed_alpha_diagnosis",
        "raw_question": "MU went up 10% today, why did we miss it?",
        "target_entities": ["MU"],
        "observation": {"kind": "price_move", "value": "+10%", "date": "2026-03-17"},
        "required_stages": ["scouts"],
        "required_dimensions": ["social"],
        "manual_only": True,
    }
    investigation = {
        "query_type": "reverse_forensic",
        "intent": "missed_alpha_diagnosis",
        "target_entities": ["MU"],
        "as_of_date": "2026-03-17",
        "stage_diagnosis": [{"stage": "scouts", "status": "MISS"}],
        "first_miss_stage": "scouts",
        "matched_event_cards": [],
        "evidence_found": [],
        "evidence_missing": ["scouts"],
    }
    response = {
        "summary": "Investigation is missing critical evidence for MU; first miss point is scouts.",
        "coverage_status": "MISSING",
        "query_type": "reverse_forensic",
        "matched_entities": ["MU"],
        "stage_diagnosis": [{"stage": "scouts", "status": "MISS"}],
        "evidence_found": [],
        "evidence_missing": ["scouts"],
        "recommended_changes": ["Expand discovery triggers for target entities and relevant catalysts."],
        "manual_gap_fill_requests": ["manual_event_specific_x_feed_pass"],
        "confidence": 0.35,
    }

    with (
        patch("cli.commands.dealflow.compile_question", return_value=compiled) as compile_mock,
        patch("cli.commands.dealflow.run_investigation", return_value=investigation) as run_mock,
        patch("cli.commands.dealflow.build_investigation_response", return_value=response) as build_mock,
    ):
        result = runner.invoke(
            app,
            [
                "question-investigate",
                "--date",
                "2026-03-17",
                "--question",
                "MU went up 10% today, why did we miss it?",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    assert '"coverage_status": "MISSING"' in result.stdout
    compile_mock.assert_called_once_with(
        question="MU went up 10% today, why did we miss it?",
        as_of_date="2026-03-17",
    )
    run_mock.assert_called_once()
    build_mock.assert_called_once_with(investigation_result=investigation)


def test_question_investigate_table_prints_wait_message_for_missing():
    with (
        patch(
            "cli.commands.dealflow.compile_question",
            return_value={"query_type": "reverse_forensic", "target_entities": ["MU"], "manual_only": True},
        ),
        patch(
            "cli.commands.dealflow.run_investigation",
            return_value={"stage_diagnosis": [], "first_miss_stage": "scouts", "target_entities": ["MU"]},
        ),
        patch(
            "cli.commands.dealflow.build_investigation_response",
            return_value={
                "summary": "Investigation is missing critical evidence for MU; first miss point is scouts.",
                "coverage_status": "MISSING",
                "matched_entities": ["MU"],
                "manual_gap_fill_requests": ["manual_event_specific_x_feed_pass"],
            },
        ),
    ):
        result = runner.invoke(
            app,
            [
                "question-investigate",
                "--date",
                "2026-03-17",
                "--question",
                "MU went up 10% today, why did we miss it?",
                "--format",
                "table",
            ],
        )

    assert result.exit_code == 0
    assert "Question investigation complete" in result.stdout
    assert "MISSING" in result.stdout
    assert "Waiting for user-supplied gap fill" in result.stdout


def test_question_investigate_rejects_invalid_format():
    result = runner.invoke(
        app,
        [
            "question-investigate",
            "--question",
            "MU went up 10% today, why did we miss it?",
            "--format",
            "yaml",
        ],
    )

    assert result.exit_code == 1
    assert "format must be table or json" in result.stdout
