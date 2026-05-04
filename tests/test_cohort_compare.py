import sys
import types
from unittest.mock import patch

# Stub chromadb before cli.main import on Python 3.14
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from typer.testing import CliRunner

from cli.main import app


runner = CliRunner()


def test_cohort_compare_renders_v3_rejected_and_benchmark_gap():
    payload = {
        "source_date": "2026-03-10",
        "eval_date": "2026-03-17",
        "days": 7,
        "cohorts": {
            "ENTERED": {
                "cohort": "ENTERED",
                "ticker_count": 30,
                "eq_weight_return": 0.03,
                "score_weight_return": 0.031,
                "benchmark_return": 0.1,
                "filter_alpha": -0.07,
            },
            "SELECTED": {
                "cohort": "SELECTED",
                "ticker_count": 12,
                "eq_weight_return": 0.04,
                "score_weight_return": 0.041,
                "benchmark_return": 0.1,
                "filter_alpha": -0.06,
            },
            "V3_CLEARED": {
                "cohort": "V3_CLEARED",
                "ticker_count": 1,
                "eq_weight_return": 0.05,
                "score_weight_return": 0.05,
                "benchmark_return": 0.1,
                "filter_alpha": -0.05,
            },
            "V3_REJECTED": {
                "cohort": "V3_REJECTED",
                "ticker_count": 11,
                "eq_weight_return": 0.12,
                "score_weight_return": 0.13,
                "benchmark_return": 0.1,
                "filter_alpha": 0.02,
            },
        },
        "inter_stage_alpha": {
            "entered_to_selected": 0.01,
            "selected_to_v3": 0.01,
            "benchmark_to_v3_rejected": -0.02,
        },
    }

    with patch(
        "tradingagents.dealflow.cohort_tracker.compute_cohort_returns",
        return_value=payload,
    ):
        result = runner.invoke(app, ["cohort-compare", "--date", "2026-03-10"])

    assert result.exit_code == 0
    assert "V3_REJECTED" in result.stdout
    assert "Benchmark→V3 Rejected" in result.stdout

