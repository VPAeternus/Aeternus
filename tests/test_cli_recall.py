import sys
import types
import tempfile
from pathlib import Path
from unittest.mock import patch
import json

from typer.testing import CliRunner

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


def test_recall_fvg_json_returns_backend_payload():
    payload = {
        "selected_symbols": ["NVDA", "MU"],
        "artifact": {
            "date": "2026-03-22",
            "selected_symbols": ["NVDA", "MU"],
            "quota": 30,
            "rows": [
                {
                    "symbol": "NVDA",
                    "score": 88.2,
                    "relative_strength_20d": 0.11,
                    "sma50_above_sma200": True,
                    "bullish_fvg_present": True,
                }
            ],
            "rule_snapshot": {
                "enabled": True,
                "quota": 30,
                "min_rs20": 0.03,
                "min_liquidity_score": 30.0,
            },
        },
    }

    with patch("cli.commands.recall.DealFlowPipeline._build_fvg_recall_channel", return_value=payload) as builder:
        result = runner.invoke(app, ["recall", "fvg", "--date", "2026-03-22", "--format", "json"])

    assert result.exit_code == 0
    assert '"selected_symbols": [' in result.stdout
    assert '"NVDA"' in result.stdout
    builder.assert_called_once_with(as_of_date="2026-03-22")


def test_recall_fma_json_returns_backend_payload():
    payload = {
        "selected_symbols": ["PLTR"],
        "artifact": {
            "date": "2026-03-22",
            "selected_symbols": ["PLTR"],
            "quota": 20,
            "rows": [
                {
                    "symbol": "PLTR",
                    "score": 72.5,
                    "velocity_60d": 0.9,
                    "accel_value": 0.3,
                    "mass_ratio": 1.1,
                    "force_value": 0.7,
                    "relative_strength_60d": 0.18,
                }
            ],
            "rule_snapshot": {
                "enabled": True,
                "quota": 20,
                "min_score": 60.0,
                "min_liquidity_score": 30.0,
            },
        },
    }

    with patch("cli.commands.recall.DealFlowPipeline._build_fma_recall_channel", return_value=payload) as builder:
        result = runner.invoke(app, ["recall", "fma", "--date", "2026-03-22", "--format", "json"])

    assert result.exit_code == 0
    assert '"PLTR"' in result.stdout
    builder.assert_called_once_with(as_of_date="2026-03-22")


def test_recall_fvg_table_explains_rules_and_selected_symbols():
    payload = {
        "selected_symbols": ["NVDA", "MU"],
        "artifact": {
            "date": "2026-03-22",
            "selected_symbols": ["NVDA", "MU"],
            "quota": 30,
            "rows": [
                {
                    "symbol": "NVDA",
                    "score": 88.2,
                    "relative_strength_20d": 0.11,
                    "sma50_above_sma200": True,
                    "bullish_fvg_present": True,
                }
            ],
            "rule_snapshot": {
                "enabled": True,
                "quota": 30,
                "min_rs20": 0.03,
                "min_liquidity_score": 30.0,
                "required_confirmation": [
                    "bullish_fvg_present",
                    "relative_strength_20d",
                    "sma50_above_sma200",
                ],
            },
        },
    }

    with patch("cli.commands.recall.DealFlowPipeline._build_fvg_recall_channel", return_value=payload):
        result = runner.invoke(app, ["recall", "fvg", "--date", "2026-03-22"])

    assert result.exit_code == 0
    assert "Fair Value Gap Recall" in result.stdout
    assert "Bullish FVG" in result.stdout
    assert "NVDA, MU" in result.stdout
    assert "0.03" in result.stdout


def test_recall_rejects_invalid_format():
    result = runner.invoke(app, ["recall", "fvg", "--format", "yaml"])

    assert result.exit_code == 1
    assert "format must be table or json" in result.stdout


def test_recall_fvg_single_symbol_json_returns_explanation_payload():
    payload = {
        "mode": "single_symbol",
        "channel": "fvg",
        "symbol": "NVDA",
        "as_of_date": "2026-03-22",
        "selected": True,
        "explanation": "Selected because bullish FVG is present, RS20 exceeds threshold, and SMA50 is above SMA200.",
        "metrics": {
            "score": 88.2,
            "bullish_fvg_present": True,
            "relative_strength_20d": 0.11,
            "sma50_above_sma200": True,
        },
        "thresholds": {
            "min_rs20": 0.03,
            "required_confirmation": [
                "bullish_fvg_present",
                "relative_strength_20d",
                "sma50_above_sma200",
            ],
        },
        "checks": [
            {"name": "bullish_fvg_present", "passed": True, "observed": True},
            {"name": "relative_strength_20d", "passed": True, "observed": 0.11, "threshold": 0.03},
            {"name": "sma50_above_sma200", "passed": True, "observed": True},
        ],
    }

    with patch("cli.commands.recall._build_fvg_single_symbol_payload", return_value=payload) as builder:
        result = runner.invoke(app, ["recall", "fvg", "NVDA", "--date", "2026-03-22", "--format", "json"])

    assert result.exit_code == 0
    assert '"mode": "single_symbol"' in result.stdout
    assert '"symbol": "NVDA"' in result.stdout
    builder.assert_called_once_with(symbol="NVDA", as_of_date="2026-03-22")


def test_recall_fma_single_symbol_table_shows_pass_fail_explanation():
    payload = {
        "mode": "single_symbol",
        "channel": "fma",
        "symbol": "NVDA",
        "as_of_date": "2026-03-22",
        "selected": False,
        "explanation": "Not selected because FMA score is below the live minimum threshold.",
        "metrics": {
            "score": 52.4,
            "velocity_60d": -0.05,
            "accel_value": -0.02,
            "mass_ratio": 1.07,
            "force_value": -0.02,
            "relative_strength_60d": 0.00,
        },
        "thresholds": {
            "min_score": 60.0,
            "required_confirmation": ["fma_live_score"],
        },
        "checks": [
            {"name": "fma_live_score", "passed": False, "observed": 52.4, "threshold": 60.0},
        ],
    }

    with patch("cli.commands.recall._build_fma_single_symbol_payload", return_value=payload):
        result = runner.invoke(app, ["recall", "fma", "NVDA", "--date", "2026-03-22"])

    assert result.exit_code == 0
    assert "Single-Symbol FMA Recall" in result.stdout
    assert "Not selected because FMA score is below the live minimum threshold." in result.stdout
    assert "52.40" in result.stdout
    assert "60.00" in result.stdout


def test_recall_performance_json_returns_combined_payload_from_artifacts():
    payload = {
        "as_of_date": "2026-03-25",
        "universe": "semis-ai-narrow",
        "benchmark": "SMH",
        "methodology": {
            "study_type": "historical_signal_study",
            "data_source": "Yahoo Finance daily OHLCV",
        },
        "fvg": {"source": "artifact", "event_summary": {"event_count": 12}},
        "fma": {"source": "artifact", "variant_summaries": {"fma_live": {"event_summary": {"event_count": 8}}}},
        "comparison": {"summary": "FVG has more events; FMA has stronger 20d edge."},
    }

    with patch("cli.commands.recall._build_recall_performance_payload", return_value=payload) as builder:
        result = runner.invoke(app, ["recall", "performance", "--date", "2026-03-25", "--format", "json"])

    assert result.exit_code == 0
    assert '"historical_signal_study"' in result.stdout
    assert '"event_count": 12' in result.stdout
    builder.assert_called_once_with(as_of_date="2026-03-25", universe="semis-ai-narrow", benchmark="SMH", refresh=False)


def test_recall_performance_table_renders_investor_readable_scorecard():
    payload = {
        "as_of_date": "2026-03-25",
        "universe": "semis-ai-narrow",
        "benchmark": "SMH",
        "methodology": {
            "study_type": "historical_signal_study",
            "data_source": "Yahoo Finance daily OHLCV",
            "note": "Signal study, not execution-adjusted PnL.",
        },
        "fvg": {
            "source": "artifact",
            "event_summary": {
                "event_count": 20,
                "mean_forward_return_20d": 0.12,
                "mean_forward_return_60d": 0.25,
            },
            "basket_summary": {
                "avg_edge_vs_benchmark_20d": 0.04,
                "avg_edge_vs_benchmark_60d": 0.08,
            },
            "top_tickers": [{"ticker": "NVDA", "event_count": 5}],
        },
        "fma": {
            "source": "artifact",
            "variant_summaries": {
                "fma_live": {
                    "event_summary": {
                        "event_count": 16,
                        "mean_forward_return_20d": 0.15,
                        "mean_forward_return_60d": 0.22,
                    },
                    "basket_summary": {
                        "avg_edge_vs_benchmark_20d": 0.06,
                        "avg_edge_vs_benchmark_60d": 0.05,
                    },
                }
            },
            "overlap_summary": {
                "fvg_and_fma": {"event_count": 7, "mean_forward_return_20d": 0.18, "mean_forward_return_60d": 0.30}
            },
        },
        "comparison": {"summary": "FMA leads on 20d edge; FVG leads on 60d follow-through."},
    }

    with patch("cli.commands.recall._build_recall_performance_payload", return_value=payload):
        result = runner.invoke(app, ["recall", "performance", "--date", "2026-03-25"])

    assert result.exit_code == 0
    assert "Recall Performance" in result.stdout
    assert "Signal study, not execution-adjusted PnL." in result.stdout
    assert "FMA leads on 20d edge; FVG leads on 60d follow-through." in result.stdout
    assert "20.00" in result.stdout or "20" in result.stdout


def test_recall_performance_reads_saved_artifacts_when_present():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fvg_dir = root / "fvg_backtest" / "2026-03-25" / "semis-ai-narrow-vs-SMH"
        fma_dir = root / "fma_backtest" / "2026-03-25" / "semis-ai-narrow-vs-SMH"
        fvg_dir.mkdir(parents=True)
        fma_dir.mkdir(parents=True)
        (fvg_dir / "summary.json").write_text(json.dumps({
            "benchmark": "SMH",
            "event_summary": {"event_count": 9},
            "basket_summary": {"avg_edge_vs_benchmark_20d": 0.03},
            "top_tickers": [],
        }))
        (fma_dir / "summary.json").write_text(json.dumps({
            "benchmark": "SMH",
            "variant_summaries": {"fma_live": {"event_summary": {"event_count": 7}, "basket_summary": {"avg_edge_vs_benchmark_20d": 0.05}}},
            "overlap_summary": {},
        }))

        with patch("cli.commands.recall.resolve_fvg_artifact_dir", return_value=fvg_dir), patch(
            "cli.commands.recall.resolve_fma_artifact_dir", return_value=fma_dir
        ):
            payload = __import__("cli.commands.recall", fromlist=["_build_recall_performance_payload"])._build_recall_performance_payload(
                as_of_date="2026-03-25",
                universe="semis-ai-narrow",
                benchmark="SMH",
                refresh=False,
            )

    assert payload["fvg"]["source"] == "artifact"
    assert payload["fma"]["source"] == "artifact"
    assert payload["fvg"]["event_summary"]["event_count"] == 9
    assert payload["fma"]["variant_summaries"]["fma_live"]["event_summary"]["event_count"] == 7


def test_recall_performance_multi_json_returns_multiple_universes():
    payload = {
        "as_of_date": "2026-03-26",
        "universes": [
            {"universe": "semis_ai", "benchmark": "SMH"},
            {"universe": "qqq_top20", "benchmark": "QQQ"},
            {"universe": "spy_top20", "benchmark": "SPY"},
        ],
    }

    with patch("cli.commands.recall._build_multi_universe_recall_performance_payload", return_value=payload) as builder:
        result = runner.invoke(app, ["recall", "performance", "--multi", "--date", "2026-03-26", "--format", "json"])

    assert result.exit_code == 0
    assert '"semis_ai"' in result.stdout
    assert '"qqq_top20"' in result.stdout
    assert '"spy_top20"' in result.stdout
    builder.assert_called_once_with(as_of_date="2026-03-26", refresh=False)


def test_recall_performance_multi_table_shows_benchmark_comparison_rows():
    payload = {
        "as_of_date": "2026-03-26",
        "universes": [
            {
                "universe": "qqq_top20",
                "benchmark": "QQQ",
                "fvg": {"event_summary": {"event_count": 100}, "basket_summary": {"avg_edge_vs_benchmark_20d": 0.03, "avg_edge_vs_benchmark_60d": 0.06}},
                "fma": {"variant_summaries": {"fma_live": {"event_summary": {"event_count": 120}, "basket_summary": {"avg_edge_vs_benchmark_20d": 0.02, "avg_edge_vs_benchmark_60d": 0.05}}}},
            },
            {
                "universe": "spy_top20",
                "benchmark": "SPY",
                "fvg": {"event_summary": {"event_count": 80}, "basket_summary": {"avg_edge_vs_benchmark_20d": 0.01, "avg_edge_vs_benchmark_60d": 0.02}},
                "fma": {"variant_summaries": {"fma_live": {"event_summary": {"event_count": 95}, "basket_summary": {"avg_edge_vs_benchmark_20d": 0.00, "avg_edge_vs_benchmark_60d": 0.01}}}},
            },
        ],
    }

    with patch("cli.commands.recall._build_multi_universe_recall_performance_payload", return_value=payload):
        result = runner.invoke(app, ["recall", "performance", "--multi", "--date", "2026-03-26"])

    assert result.exit_code == 0
    assert "Multi-Universe Recall Performance" in result.stdout
    assert "qqq_top20" in result.stdout
    assert "spy_top20" in result.stdout
    assert "QQQ" in result.stdout
    assert "SPY" in result.stdout


def test_normalize_universe_name_accepts_new_labels_and_old_aliases():
    from tradingagents.dealflow.fvg_recall import normalize_universe_name

    assert normalize_universe_name("semis-ai") == "semis_ai"
    assert normalize_universe_name("semis_ai_narrow") == "semis_ai"
    assert normalize_universe_name("qqq-top20") == "qqq_top20"
    assert normalize_universe_name("qqq_top20_proxy") == "qqq_top20"
