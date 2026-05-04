import sys
import types

# Stub chromadb before it can be imported (pydantic v1 incompatible with Python 3.14)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []  # make it look like a package
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

import json
import subprocess
import datetime
import io
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
from typer.testing import CliRunner

from cli.main import app
import cli.commands.dealflow as dealflow_cmd
from cli.common import (
    _build_noninteractive_selections,
    _extract_analysis_outcome,
    _extract_json_object_from_output,
    _load_batch_summary,
)


runner = CliRunner()


def _extract_json(text: str):
    lines = text.strip().splitlines()
    for idx, line in enumerate(lines):
        if line.strip().startswith("{"):
            return json.loads("\n".join(lines[idx:]))
    raise AssertionError(f"No JSON object found in output: {text}")


def test_extract_json_object_from_output_tolerates_log_noise():
    noisy = (
        "DEBUG: provider selected\\n"
        '{"ticker":"VZ","date":"2026-02-07","aeternus_score":61.2,"rating":"Hold","confidence":3}\\n'
        "DEBUG: trailing line\\n"
    )
    parsed = _extract_json_object_from_output(noisy)
    assert isinstance(parsed, dict)
    assert parsed.get("ticker") == "VZ"
    assert float(parsed.get("aeternus_score", 0.0)) == 61.2


def test_extract_analysis_outcome_exposes_rating_id_and_recommendation_side(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report_path = tmp_path / "results" / "AAPL" / "2026-03-10" / "analysis_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "final_trade_decision": "Recommendation: **BUY**\n\nRationale: test",
                "aeternus_score": {
                    "rating_id": "rid-abc",
                    "aeternus_score": 73.5,
                    "confidence": 4,
                    "rating": "Hold",
                },
            }
        )
    )

    outcome = _extract_analysis_outcome("AAPL", "2026-03-10")

    assert outcome["analysis_report_found"] is True
    assert outcome["rating_id"] == "rid-abc"
    assert outcome["recommendation"] == "BUY"
    assert outcome["recommendation_side"] == "LONG"


def test_source_command_json_format_emits_artifacts_and_audit_event():
    shortlist = {
        "run_id": "2026-02-05-090000-daily",
        "date": "2026-02-05",
        "trigger": "daily",
        "top_k": 20,
        "candidates": [
            {
                "rank": 1,
                "symbol": "AAPL",
                "asset_class": "Equity",
                "sector": "Technology",
                "deal_flow_score": 88.0,
                "freshness_hours": 2.0,
                "reason": "Top drivers: social_momentum, news_catalyst",
            }
        ],
        "event_triggered": False,
        "event_reasons": [],
    }
    queue = {
        "run_id": "2026-02-05-090000-daily",
        "date": "2026-02-05",
        "items": [
            {
                "queue_id": "2026-02-05-090000-daily:AAPL",
                "symbol": "AAPL",
                "asset_class": "Equity",
                "deal_flow_score": 88.0,
                "triage_score": 84.0,
                "selected_for_deep": True,
            }
        ],
        "deep_k": 8,
        "selected_queue_ids": ["2026-02-05-090000-daily:AAPL"],
        "source_artifact": "eval_results/deal_flow/2026-02-05/shortlist_top20.json",
    }

    with patch("cli.commands.dealflow.DealFlowPipeline") as pipeline_cls, patch("cli.commands.dealflow.RatingAuditLog") as audit_cls:
        pipeline_cls.return_value.run.return_value = (
            shortlist,
            queue,
            [{"symbol": "AAPL", "signal_family": "news_catalyst"}],
            {"triggered": False, "reasons": [], "metrics": {}},
        )
        audit = Mock()
        audit_cls.return_value = audit

        result = runner.invoke(
            app,
            [
                "source",
                "--date",
                "2026-02-05",
                "--top-k",
                "20",
                "--trigger",
                "daily",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["shortlist"]["run_id"] == "2026-02-05-090000-daily"
    assert parsed["research_queue"]["items"][0]["symbol"] == "AAPL"
    assert parsed["signal_count"] == 1
    audit.log_event.assert_called_once()


def test_discover_command_renders_discovery_delta_summary():
    discovery_summary = {
        "universe_size": 3,
        "breakout_count": 1,
        "technical_ignition_count": 2,
        "iv_force_queue_count": 0,
        "insider_summary": {},
        "manual_symbols": [],
        "fvg_recall_symbols": ["NVDA"],
        "fma_recall_symbols": ["PLTR"],
        "universe_filter": {
            "universe_size": 3,
            "overall_ready": True,
            "tier_counts": {"T1_ANCHOR": 1, "T3B_FVG_RECALL": 1, "MANUAL": 1},
            "source_counts": {"x_feed_merged_symbols": 2, "fvg_recall_selected": 1, "fma_recall_selected": 1},
            "overlap_counts": {"fvg_fma_overlap": 0, "manual_technical_overlap": 1, "scout_technical_overlap": 0},
            "health_checks": {
                "universe_nonzero": {"pass": True, "observed": 3, "required": ">0"},
                "tier_diversity_ok": {"pass": True, "observed": 3, "required": ">=2"},
                "technical_recall_present": {"pass": True, "observed": 2, "required": ">0"},
                "manual_xfeed_present": {"pass": True, "observed": 2, "required": ">0"},
                "scout_activity_present": {"pass": True, "observed": 1, "required": ">0"},
            },
        },
        "discovery_delta_summary": {"signal_count": 3, "record_count": 3},
        "discovery_delta": {
            "top_delta_symbols": [
                {
                    "symbol": "NVDA",
                    "delta_score": 83.5,
                    "sources_fired": ["fvg_recall"],
                    "independent_channel_count": 1,
                }
            ],
            "cohorts": {
                "scout_only": ["AMD"],
                "technical_only": ["NVDA", "PLTR"],
                "multi_channel": [],
            },
        },
    }

    with patch("cli.commands.dealflow.DealFlowPipeline") as pipeline_cls:
        pipeline_cls.return_value.discover.return_value = discovery_summary
        result = runner.invoke(app, ["discover", "--date", "2026-03-07"])

    assert result.exit_code == 0
    assert "First Universe Filter" in result.stdout
    assert "Discovery Delta" in result.stdout
    assert "Technical ignition setups: 2" in result.stdout
    assert "NVDA" in result.stdout
    assert "technical_only" in result.stdout


def test_earnings_scan_command_removed():
    result = runner.invoke(app, ["earnings-scan"])

    assert result.exit_code != 0
    assert "No such command" in result.output


def test_universe_filter_command_renders_status_and_counts():
    payload = {
        "as_of_date": "2026-03-09",
        "universe_size": 62,
        "overall_ready": True,
        "tier_counts": {"T1_ANCHOR": 10, "T3B_FVG_RECALL": 30, "T3C_FMA_RECALL": 20, "MANUAL": 2},
        "source_counts": {"x_feed_merged_symbols": 117, "fvg_recall_selected": 30, "fma_recall_selected": 20},
        "overlap_counts": {"fvg_fma_overlap": 4, "manual_technical_overlap": 2, "scout_technical_overlap": 5},
        "health_checks": {
            "universe_nonzero": {"pass": True, "observed": 62, "required": ">0"},
            "tier_diversity_ok": {"pass": True, "observed": 4, "required": ">=2"},
            "technical_recall_present": {"pass": True, "observed": 50, "required": ">0"},
            "manual_xfeed_present": {"pass": True, "observed": 117, "required": ">0"},
            "scout_activity_present": {"pass": True, "observed": 9, "required": ">0"},
        },
    }

    with patch("tradingagents.dealflow.universe_filter.load_universe_filter_report", return_value=payload):
        result = runner.invoke(app, ["universe-filter", "--date", "2026-03-09", "--status"])

    assert result.exit_code == 0
    assert "READY First Universe Filter" in result.stdout
    assert "Universe Tier Counts" in result.stdout
    assert "T3B_FVG_RECALL" in result.stdout


def test_source_command_renders_discovery_delta_summary():
    shortlist = {
        "run_id": "2026-02-05-090000-daily",
        "date": "2026-02-05",
        "trigger": "daily",
        "top_k": 20,
        "candidates": [
            {
                "rank": 1,
                "symbol": "AAPL",
                "asset_class": "Equity",
                "sector": "Technology",
                "deal_flow_score": 88.0,
                "freshness_hours": 2.0,
                "reason": "Top drivers: social_momentum, news_catalyst",
            }
        ],
        "event_triggered": False,
        "event_reasons": [],
    }
    queue = {
        "run_id": "2026-02-05-090000-daily",
        "date": "2026-02-05",
        "items": [],
        "deep_k": 8,
        "selected_queue_ids": [],
        "source_artifact": "eval_results/deal_flow/2026-02-05/shortlist_top20.json",
    }

    with patch("cli.commands.dealflow.DealFlowPipeline") as pipeline_cls, patch("cli.commands.dealflow.RatingAuditLog") as audit_cls:
        pipeline = pipeline_cls.return_value
        pipeline._last_discovery_delta = {
            "top_delta_symbols": [
                {
                    "symbol": "NVDA",
                    "delta_score": 83.5,
                    "sources_fired": ["fvg_recall", "breakout_scanner"],
                    "independent_channel_count": 2,
                }
            ],
            "cohorts": {
                "scout_only": ["AMD"],
                "technical_only": ["PLTR"],
                "multi_channel": ["NVDA"],
            },
        }
        pipeline.run.return_value = (
            shortlist,
            queue,
            [{"symbol": "AAPL", "signal_family": "news_catalyst"}],
            {"triggered": False, "reasons": [], "metrics": {}},
        )
        audit_cls.return_value = Mock()

        result = runner.invoke(
            app,
            ["source", "--date", "2026-02-05", "--top-k", "20", "--trigger", "daily"],
        )

    assert result.exit_code == 0
    assert "Discovery Delta" in result.stdout
    assert "NVDA" in result.stdout
    assert "multi_channel" in result.stdout


def test_queue_command_json_reads_queue_loader():
    queue_data = {
        "run_id": "2026-02-05-090000-daily",
        "date": "2026-02-05",
        "items": [
            {
                "queue_id": "2026-02-05-090000-daily:GLD",
                "symbol": "GLD",
                "asset_class": "CommodityProxy",
                "deal_flow_score": 74.2,
                "triage_score": 70.1,
                "selected_for_deep": True,
            }
        ],
        "deep_k": 8,
        "selected_queue_ids": ["2026-02-05-090000-daily:GLD"],
        "source_artifact": "eval_results/deal_flow/2026-02-05/shortlist_top20.json",
    }

    with patch("cli.commands.dealflow._load_research_queue", return_value=(queue_data, Path("eval_results/deal_flow/latest_research_queue.json"))):
        result = runner.invoke(app, ["queue", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["items"][0]["symbol"] == "GLD"


def test_hindsight_command_renders_hypothesis_stage_summary():
    result_payload = {
        "source_date": "2026-02-20",
        "eval_date": "2026-02-27",
        "benchmark": "QQQ",
        "benchmark_return_5d": 0.01,
        "output_path": "eval_results/deal_flow/2026-02-20/hindsight.json",
        "cohorts": {
            "DEPLOYED": {"count": 1, "mean_return": 0.05, "median_return": 0.05, "edge_vs_benchmark": 0.04},
            "ANALYZED": {"count": 0},
            "QUEUED": {"count": 0},
            "FILTERED": {"count": 0},
            "LOW_DATA": {"count": 0},
        },
        "rank_ic": {"core_score": 0.2, "momentum_score": 0.1, "triage_score": 0.15},
        "missed_opportunities": [],
        "hypothesis_stage_summary": {
            "lane": "shared",
            "stages": [
                {
                    "stage_id": "shortlist_cut",
                    "kept_count": 2,
                    "dropped_count": 1,
                    "edge_5d": 0.01,
                    "edge_20d": None,
                    "edge_3m": None,
                    "future_winner_recall": 1.0,
                    "false_negative_cost": 0.0,
                }
            ],
        },
        "discovery_delta_cohorts": {
            "cohorts": {
                "scout_only": {
                    "count": 1,
                    "mean_return_5d": 0.01,
                    "mean_return_20d": None,
                    "mean_return_3m": None,
                    "shortlist_conversion": 0.0,
                    "deep_selection_conversion": 0.0,
                },
                "technical_only": {
                    "count": 1,
                    "mean_return_5d": 0.03,
                    "mean_return_20d": None,
                    "mean_return_3m": None,
                    "shortlist_conversion": 1.0,
                    "deep_selection_conversion": 0.0,
                },
                "multi_channel": {
                    "count": 2,
                    "mean_return_5d": 0.04,
                    "mean_return_20d": None,
                    "mean_return_3m": None,
                    "shortlist_conversion": 1.0,
                    "deep_selection_conversion": 1.0,
                },
            },
            "step1_baseline": {
                "count": 4,
                "mean_return_5d": 0.025,
                "mean_return_20d": None,
                "mean_return_3m": None,
                "shortlist_conversion": 0.5,
                "deep_selection_conversion": 0.25,
            },
            "comparisons": {
                "vs_step1_baseline": {
                    "multi_channel": {"mean_return_5d_delta": 0.015, "mean_return_20d_delta": None, "mean_return_3m_delta": None},
                    "scout_only": {"mean_return_5d_delta": -0.015, "mean_return_20d_delta": None, "mean_return_3m_delta": None},
                    "technical_only": {"mean_return_5d_delta": 0.005, "mean_return_20d_delta": None, "mean_return_3m_delta": None},
                },
                "vs_other_cohorts": {
                    "multi_channel": {"mean_return_5d_delta": 0.02, "mean_return_20d_delta": None, "mean_return_3m_delta": None},
                    "scout_only": {"mean_return_5d_delta": -0.025, "mean_return_20d_delta": None, "mean_return_3m_delta": None},
                    "technical_only": {"mean_return_5d_delta": -0.005, "mean_return_20d_delta": None, "mean_return_3m_delta": None},
                },
            },
        },
        "evidence_integrity_cohorts": {
            "cohorts": {
                "CONFIRMED": {
                    "count": 1,
                    "mean_return_5d": 0.03,
                    "mean_return_20d": None,
                    "mean_return_3m": None,
                    "shortlist_conversion": 1.0,
                    "deep_selection_conversion": 0.0,
                },
                "SPARSE_BUT_INTERESTING": {
                    "count": 1,
                    "mean_return_5d": 0.05,
                    "mean_return_20d": None,
                    "mean_return_3m": None,
                    "shortlist_conversion": 1.0,
                    "deep_selection_conversion": 1.0,
                },
                "DATA_DEGRADED": {
                    "count": 1,
                    "mean_return_5d": -0.01,
                    "mean_return_20d": None,
                    "mean_return_3m": None,
                    "shortlist_conversion": 0.0,
                    "deep_selection_conversion": 0.0,
                },
                "LOW_SIGNAL": {
                    "count": 1,
                    "mean_return_5d": 0.0,
                    "mean_return_20d": None,
                    "mean_return_3m": None,
                    "shortlist_conversion": 0.0,
                    "deep_selection_conversion": 0.0,
                },
            },
            "step2_baseline": {
                "count": 4,
                "mean_return_5d": 0.0175,
                "mean_return_20d": None,
                "mean_return_3m": None,
                "shortlist_conversion": 0.5,
                "deep_selection_conversion": 0.25,
            },
            "comparisons": {
                "vs_step2_baseline": {
                    "SPARSE_BUT_INTERESTING": {"mean_return_5d_delta": 0.0325},
                },
                "vs_other_cohorts": {
                    "SPARSE_BUT_INTERESTING": {"mean_return_5d_delta": 0.0567},
                },
            },
        },
    }

    with patch("tradingagents.dealflow.hindsight.compute_hindsight", return_value=result_payload):
        result = runner.invoke(
            app,
            ["hindsight", "--source-date", "2026-02-20", "--benchmark", "QQQ"],
        )

    assert result.exit_code == 0
    assert "Hypothesis Ledger Summary" in result.stdout
    assert "Discovery Delta Cohort Scorecards" in result.stdout
    assert "Evidence Integrity Cohort Scorecards" in result.stdout


def test_why_missed_command_renders_recent_run_root_causes():
    payload = {
        "ticker": "MU",
        "lookback_runs_requested": 10,
        "lookback_runs_used": 5,
        "flagged_run_count": 4,
        "ever_flagged": True,
        "runs": [
            {
                "source_date": "2026-03-10",
                "highest_stage": "ANALYZED",
                "root_cause": "V3_HURDLE_REJECTED",
                "primary_stage_drop": "portfolio_inclusion_cut",
                "improvement_target": "portfolio_inclusion_cut",
                "edge_vs_benchmark_5d": 0.12,
                "review_recommended": True,
                "review_reason": "portfolio_inclusion_cut dropped MU before a +12.00% edge vs QQQ",
                "x_feed_seen": True,
                "signals_seen": True,
                "scored_seen": True,
                "queue_seen": True,
                "selected_for_deep": True,
                "analyzed_success": True,
                "deployed": False,
                "v3_hurdle_cleared": False,
            },
            {
                "source_date": "2026-03-09",
                "highest_stage": "QUEUED",
                "root_cause": "DEEP_SELECTION_CUT",
                "primary_stage_drop": "deep_selection_cut",
                "improvement_target": "deep_selection_cut",
                "edge_vs_benchmark_5d": None,
                "review_recommended": False,
                "review_reason": None,
                "x_feed_seen": True,
                "signals_seen": True,
                "scored_seen": True,
                "queue_seen": True,
                "selected_for_deep": False,
                "analyzed_success": False,
                "deployed": False,
                "v3_hurdle_cleared": False,
            },
        ],
    }

    with patch(
        "tradingagents.dealflow.why_missed.compute_why_missed",
        return_value=payload,
    ):
        result = runner.invoke(app, ["why-missed", "MU"])

    assert result.exit_code == 0
    assert "Why Missed: MU" in result.stdout
    assert "V3_HURDLE_REJECTED" in result.stdout
    assert "DEEP_SELECTION_CUT" in result.stdout
    assert "step1_baseline" in result.stdout
    assert "shortlist_cut" in result.stdout
    assert "+1.00%" in result.stdout
    assert "portfolio_inclusion_cut" in result.stdout


def test_needle_retro_command_renders_top_false_negatives():
    payload = {
        "cycles_requested": 5,
        "cycles_completed": 3,
        "benchmark": "QQQ",
        "min_edge": 0.03,
        "cycles": [
            {"source_date": "2026-03-08", "status": "COMPLETED", "benchmark_return_5d": 0.01},
            {"source_date": "2026-03-07", "status": "COMPLETED", "benchmark_return_5d": 0.02},
            {"source_date": "2026-03-06", "status": "COMPLETED", "benchmark_return_5d": 0.01},
        ],
        "opportunities": [
            {
                "source_date": "2026-03-08",
                "ticker": "MU",
                "cohort": "FILTERED",
                "return_5d": 0.23,
                "benchmark_return_5d": 0.01,
                "edge_vs_benchmark_5d": 0.22,
                "highest_stage": "SCORED",
                "root_cause": "SHORTLIST_CUT",
                "improvement_target": "shortlist_cut",
                "primary_stage_drop": "shortlist_cut",
            },
            {
                "source_date": "2026-03-06",
                "ticker": "TSM",
                "cohort": "QUEUED",
                "return_5d": 0.09,
                "benchmark_return_5d": 0.01,
                "edge_vs_benchmark_5d": 0.08,
                "highest_stage": "QUEUED",
                "root_cause": "DEEP_SELECTION_CUT",
                "improvement_target": "deep_selection_cut",
                "primary_stage_drop": "deep_selection_cut",
            },
        ],
        "stage_summary": [
            {"improvement_target": "shortlist_cut", "count": 1, "avg_edge_5d": 0.22, "total_edge_5d": 0.22},
            {"improvement_target": "deep_selection_cut", "count": 1, "avg_edge_5d": 0.08, "total_edge_5d": 0.08},
        ],
    }

    with patch("tradingagents.dealflow.needle_retro.compute_needle_retro", return_value=payload):
        result = runner.invoke(app, ["needle-retro"])

    assert result.exit_code == 0
    assert "Needle Retro" in result.stdout
    assert "MU" in result.stdout
    assert "SHORTLIST_CUT" in result.stdout
    assert "deep_selection_cut" in result.stdout
    assert "+22.00%" in result.stdout


def test_performance_review_command_renders_hypothesis_stage_summary():
    result_payload = {
        "source_date": "2026-01-20",
        "benchmark_return_5d": 0.01,
        "stages": {
            "SCORED": {"n": 5, "mean_5d": 0.012, "mean_20d": 0.03, "edge_5d": 0.002},
            "QUEUED": {"n": 2, "mean_5d": 0.045, "mean_20d": 0.10, "edge_5d": 0.035},
            "ANALYZED": {"n": 0, "mean_5d": None, "mean_20d": None, "edge_5d": None},
            "DEPLOYED": {"n": 0, "mean_5d": None, "mean_20d": None, "edge_5d": None},
        },
        "filter_alpha": {
            "scored_to_queued_5d": 0.055,
            "queued_to_analyzed_5d": None,
            "analyzed_to_deployed_5d": None,
        },
        "signal_family_ic": [],
        "hypothesis_stage_summary": {
            "lane": "shared",
            "stages": [
                {
                    "stage_id": "universe_gate_edge",
                    "kept_count": 300,
                    "dropped_count": 420,
                    "edge_5d": 0.008,
                    "edge_20d": 0.024,
                    "edge_3m": None,
                    "future_winner_recall": 0.67,
                    "false_negative_cost": 0.31,
                }
            ],
        },
        "discovery_delta_cohorts": {
            "cohorts": {
                "scout_only": {
                    "count": 1,
                    "mean_return_5d": 0.01,
                    "mean_return_20d": 0.02,
                    "mean_return_3m": 0.03,
                    "shortlist_conversion": 0.0,
                    "deep_selection_conversion": 0.0,
                },
                "technical_only": {
                    "count": 2,
                    "mean_return_5d": 0.03,
                    "mean_return_20d": 0.05,
                    "mean_return_3m": 0.08,
                    "shortlist_conversion": 0.5,
                    "deep_selection_conversion": 0.0,
                },
                "multi_channel": {
                    "count": 2,
                    "mean_return_5d": 0.05,
                    "mean_return_20d": 0.10,
                    "mean_return_3m": 0.18,
                    "shortlist_conversion": 1.0,
                    "deep_selection_conversion": 0.5,
                },
            },
            "step1_baseline": {
                "count": 5,
                "mean_return_5d": 0.025,
                "mean_return_20d": 0.05,
                "mean_return_3m": 0.09,
                "shortlist_conversion": 0.4,
                "deep_selection_conversion": 0.2,
            },
            "comparisons": {
                "vs_step1_baseline": {
                    "multi_channel": {"mean_return_5d_delta": 0.025, "mean_return_20d_delta": 0.05, "mean_return_3m_delta": 0.09},
                    "scout_only": {"mean_return_5d_delta": -0.015, "mean_return_20d_delta": -0.03, "mean_return_3m_delta": -0.06},
                    "technical_only": {"mean_return_5d_delta": 0.005, "mean_return_20d_delta": 0.0, "mean_return_3m_delta": -0.01},
                },
                "vs_other_cohorts": {
                    "multi_channel": {"mean_return_5d_delta": 0.03, "mean_return_20d_delta": 0.065, "mean_return_3m_delta": 0.125},
                    "scout_only": {"mean_return_5d_delta": -0.03, "mean_return_20d_delta": -0.055, "mean_return_3m_delta": -0.1},
                    "technical_only": {"mean_return_5d_delta": 0.0, "mean_return_20d_delta": -0.01, "mean_return_3m_delta": -0.025},
                },
            },
        },
        "evidence_integrity_cohorts": {
            "cohorts": {
                "CONFIRMED": {
                    "count": 1,
                    "mean_return_5d": 0.02,
                    "mean_return_20d": 0.04,
                    "mean_return_3m": 0.08,
                    "shortlist_conversion": 1.0,
                    "deep_selection_conversion": 0.0,
                },
                "SPARSE_BUT_INTERESTING": {
                    "count": 2,
                    "mean_return_5d": 0.05,
                    "mean_return_20d": 0.10,
                    "mean_return_3m": 0.16,
                    "shortlist_conversion": 1.0,
                    "deep_selection_conversion": 0.5,
                },
                "DATA_DEGRADED": {
                    "count": 1,
                    "mean_return_5d": -0.01,
                    "mean_return_20d": 0.01,
                    "mean_return_3m": 0.03,
                    "shortlist_conversion": 0.0,
                    "deep_selection_conversion": 0.0,
                },
                "LOW_SIGNAL": {
                    "count": 1,
                    "mean_return_5d": 0.0,
                    "mean_return_20d": 0.01,
                    "mean_return_3m": 0.02,
                    "shortlist_conversion": 0.0,
                    "deep_selection_conversion": 0.0,
                },
            },
            "step2_baseline": {
                "count": 5,
                "mean_return_5d": 0.022,
                "mean_return_20d": 0.052,
                "mean_return_3m": 0.09,
                "shortlist_conversion": 0.4,
                "deep_selection_conversion": 0.2,
            },
            "comparisons": {
                "vs_step2_baseline": {
                    "SPARSE_BUT_INTERESTING": {"mean_return_20d_delta": 0.048},
                },
                "vs_other_cohorts": {
                    "SPARSE_BUT_INTERESTING": {"mean_return_3m_delta": 0.1167},
                },
            },
        },
    }

    with patch("tradingagents.dealflow.performance_tracker.compute_performance_review", return_value=result_payload):
        result = runner.invoke(
            app,
            ["performance-review", "--source-date", "2026-01-20", "--benchmark", "QQQ"],
        )

    assert result.exit_code == 0
    assert "Hypothesis Ledger Summary" in result.stdout
    assert "Discovery Delta Cohort Scorecards" in result.stdout
    assert "Evidence Integrity Cohort Scorecards" in result.stdout
    assert "Delta Cohort Deltas" in result.stdout
    assert "universe_gate_edge" in result.stdout
    assert "+2.40%" in result.stdout


def test_stage_diagnosis_command_renders_priority_ranking():
    result_payload = {
        "lane": "shared",
        "cycles_considered": 4,
        "stages": [
            {
                "stage_id": "universe_gate_haystack",
                "cycles_seen": 4,
                "sample_cycles": 4,
                "avg_edge_5d": 0.004,
                "avg_edge_20d": 0.012,
                "avg_edge_3m": 0.03,
                "avg_recall": 0.42,
                "total_false_negative_cost": 0.53,
                "avg_false_negative_cost": 0.1325,
                "worst_cycle_date": "2026-03-01",
                "worst_cycle_false_negative_cost": 0.31,
                "priority_score": 61.0,
            }
        ],
        "worst_cycles": [
            {
                "source_date": "2026-03-01",
                "stage_id": "universe_gate_haystack",
                "edge_5d": 0.004,
                "edge_20d": 0.012,
                "edge_3m": 0.03,
                "future_winner_recall": 0.35,
                "false_negative_cost": 0.31,
            }
        ],
        "diagnosis": "Inspect universe_gate_haystack first: highest cumulative false-negative cost with sub-50% recall.",
    }

    with patch("tradingagents.dealflow.stage_diagnosis.compute_stage_diagnosis", return_value=result_payload):
        result = runner.invoke(
            app,
            ["stage-diagnosis", "--last", "10"],
        )

    assert result.exit_code == 0
    assert "Stage Diagnosis" in result.stdout
    assert "universe_gate_haystack" in result.stdout
    assert "Inspect universe_gate_haystack first" in result.stdout


def test_fvg_backtest_command_renders_summary():
    result_payload = {
        "universe_name": "semis_ai_narrow",
        "artifact_dir": "eval_results/deal_flow/fvg_backtest/2026-03-06",
        "event_summary": {
            "event_count": 12,
            "mean_forward_return_20d": 0.084,
            "mean_forward_return_60d": 0.192,
        },
        "basket_summary": {
            "top_n": 3,
            "avg_forward_return_20d": 0.097,
            "avg_forward_return_60d": 0.215,
            "avg_edge_vs_benchmark_20d": 0.031,
            "avg_edge_vs_benchmark_60d": 0.052,
        },
    }

    with patch("tradingagents.dealflow.fvg_recall.run_fvg_backtest", return_value=result_payload, create=True):
        result = runner.invoke(
            app,
            ["fvg-backtest", "--top-n", "3"],
        )

    assert result.exit_code == 0
    assert "FVG Backtest" in result.stdout
    assert "20d" in result.stdout
    assert "Edge vs Benchmark" in result.stdout
    assert "eval_results/deal_flow/fvg_backtest/2026-03-06" in result.stdout


def test_fvg_backtest_command_threads_proxy_universe_and_benchmark():
    result_payload = {
        "universe_name": "qqq_top20_proxy",
        "artifact_dir": "eval_results/deal_flow/fvg_backtest/2026-03-06/qqq_top20_proxy-vs-QQQ",
        "benchmark": "QQQ",
        "event_summary": {
            "event_count": 12,
            "mean_forward_return_20d": 0.084,
            "mean_forward_return_60d": 0.192,
        },
        "basket_summary": {
            "top_n": 3,
            "avg_forward_return_20d": 0.097,
            "avg_forward_return_60d": 0.215,
            "avg_edge_vs_benchmark_20d": 0.031,
            "avg_edge_vs_benchmark_60d": 0.052,
        },
    }

    with patch("tradingagents.dealflow.fvg_recall.run_fvg_backtest", return_value=result_payload, create=True) as run_mock:
        result = runner.invoke(
            app,
            ["fvg-backtest", "--universe", "qqq-top20-proxy", "--benchmark", "QQQ", "--top-n", "3"],
        )

    assert result.exit_code == 0
    run_mock.assert_called_once()
    _, kwargs = run_mock.call_args
    assert kwargs["universe_name"] == "qqq_top20"
    assert kwargs["benchmark"] == "QQQ"


def test_fma_backtest_command_renders_summary():
    result_payload = {
        "universe_name": "semis_ai_narrow",
        "artifact_dir": "eval_results/deal_flow/fma_backtest/2026-03-06",
        "benchmark": "SMH",
        "variant_summaries": {
            "fma_live": {
                "event_summary": {
                    "event_count": 12,
                    "mean_forward_return_20d": 0.074,
                    "mean_forward_return_60d": 0.162,
                },
                "basket_summary": {
                    "top_n": 3,
                    "avg_forward_return_20d": 0.081,
                    "avg_forward_return_60d": 0.193,
                    "avg_edge_vs_benchmark_20d": 0.022,
                    "avg_edge_vs_benchmark_60d": 0.041,
                },
            },
        },
        "overlap_summary": {
            "fvg_only": {"event_count": 4},
            "fma_only": {"event_count": 5},
            "fvg_and_fma": {"event_count": 3},
            "fvg_or_fma": {"event_count": 12},
        },
    }

    with patch("tradingagents.dealflow.fma_recall.run_fma_backtest", return_value=result_payload, create=True):
        result = runner.invoke(
            app,
            ["fma-backtest", "--top-n", "3"],
        )

    assert result.exit_code == 0
    assert "FMA Backtest" in result.stdout
    assert "fma_live" in result.stdout
    assert "Overlap" in result.stdout


def test_fma_backtest_command_threads_proxy_universe_and_benchmark():
    result_payload = {
        "universe_name": "qqq_top20_proxy",
        "artifact_dir": "eval_results/deal_flow/fma_backtest/2026-03-06/qqq_top20_proxy-vs-QQQ",
        "benchmark": "QQQ",
        "variant_summaries": {
            "fma_live": {
                "event_summary": {"event_count": 10},
                "basket_summary": {"top_n": 3},
            },
        },
        "overlap_summary": {},
    }

    with patch("tradingagents.dealflow.fma_recall.run_fma_backtest", return_value=result_payload, create=True) as run_mock:
        result = runner.invoke(
            app,
            ["fma-backtest", "--universe", "qqq-top20-proxy", "--benchmark", "QQQ", "--top-n", "3"],
        )

    assert result.exit_code == 0
    run_mock.assert_called_once()
    _, kwargs = run_mock.call_args
    assert kwargs["universe_name"] == "qqq_top20"
    assert kwargs["benchmark"] == "QQQ"


def test_kama_backtest_command_renders_summary():
    result_payload = {
        "universe_name": "semis_ai_narrow",
        "artifact_dir": "eval_results/deal_flow/kama_backtest/2026-03-10",
        "benchmark": "SMH",
        "event_summary": {
            "event_count": 9,
            "mean_forward_return_20d": 0.081,
            "mean_forward_return_60d": 0.173,
        },
        "basket_summary": {
            "top_n": 3,
            "avg_forward_return_20d": 0.089,
            "avg_forward_return_60d": 0.201,
            "avg_edge_vs_benchmark_20d": 0.024,
            "avg_edge_vs_benchmark_60d": 0.048,
        },
        "overlap_summary": {
            "kama_only": {"event_count": 3},
            "fvg_only": {"event_count": 2},
            "fma_only": {"event_count": 1},
            "any_signal": {"event_count": 9},
        },
    }

    with patch("tradingagents.dealflow.kama_recall.run_kama_backtest", return_value=result_payload, create=True):
        result = runner.invoke(
            app,
            ["kama-backtest", "--top-n", "3"],
        )

    assert result.exit_code == 0
    assert "KAMA Backtest" in result.stdout
    assert "20d" in result.stdout
    assert "Overlap" in result.stdout


def test_kama_backtest_command_threads_proxy_universe_and_benchmark():
    result_payload = {
        "universe_name": "qqq_top20_proxy",
        "artifact_dir": "eval_results/deal_flow/kama_backtest/2026-03-10/qqq_top20_proxy-vs-QQQ",
        "benchmark": "QQQ",
        "event_summary": {"event_count": 7},
        "basket_summary": {"top_n": 3},
        "overlap_summary": {},
    }

    with patch("tradingagents.dealflow.kama_recall.run_kama_backtest", return_value=result_payload, create=True) as run_mock:
        result = runner.invoke(
            app,
            ["kama-backtest", "--universe", "qqq-top20-proxy", "--benchmark", "QQQ", "--top-n", "3"],
        )

    assert result.exit_code == 0
    run_mock.assert_called_once()
    _, kwargs = run_mock.call_args
    assert kwargs["universe_name"] == "qqq_top20"
    assert kwargs["benchmark"] == "QQQ"


def test_technical_universe_refresh_command_threads_sources_and_writes_json():
    rows = [
        {
            "source_index": "SPY",
            "ticker": "NVDA",
            "company_name": "NVIDIA",
            "sector": "Technology",
            "as_of_date": "2026-03-11",
            "fetched_at_utc": "2026-03-11T12:00:00Z",
        },
        {
            "source_index": "QQQ",
            "ticker": "MSFT",
            "company_name": "Microsoft",
            "sector": "Technology",
            "as_of_date": "2026-03-11",
            "fetched_at_utc": "2026-03-11T12:00:00Z",
        },
    ]

    with patch("tradingagents.dealflow.current_universe.fetch_current_universe", return_value=rows, create=True) as fetch_mock, patch(
        "tradingagents.dealflow.current_universe.persist_current_universe_snapshot",
        return_value=Path("eval_results/control/technical_universe/2026-03-11/current_universe_spy_qqq.json"),
        create=True,
    ), patch("tradingagents.dealflow.technical_signal_store.SQLiteTechnicalSignalStore") as store_cls:
        store_cls.return_value.list_invalid_yahoo_tickers.return_value = []
        result = runner.invoke(
            app,
            [
                "technical-universe-refresh",
                "--sources",
                "SPY",
                "--sources",
                "QQQ",
                "--as-of-date",
                "2026-03-11",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    fetch_mock.assert_called_once()
    _, kwargs = fetch_mock.call_args
    assert kwargs["as_of_date"] == "2026-03-11"
    store_cls.return_value.upsert_universe_membership_current.assert_called_once_with(rows)
    parsed = _extract_json(result.stdout)
    assert parsed["row_count"] == 2
    assert parsed["unique_ticker_count"] == 2


def test_technical_signal_sync_command_threads_universe_and_reports_status_counts():
    membership_rows = [
        {"source_index": "SPY", "ticker": "NVDA"},
        {"source_index": "QQQ", "ticker": "NVDA"},
        {"source_index": "DOW", "ticker": "MSFT"},
    ]

    with patch("tradingagents.dealflow.technical_signal_store.SQLiteTechnicalSignalStore") as store_cls, patch(
        "tradingagents.dealflow.technical_market_cache.sync_market_history",
        return_value={"tickers": [{"ticker": "NVDA", "rows": 5}, {"ticker": "MSFT", "rows": 5}], "inserted_rows": 10},
        create=True,
    ) as sync_mock, patch(
        "tradingagents.dealflow.technical_signal_engine.recompute_signal_state",
        side_effect=[
            {"ticker": "NVDA", "signal_rows_recomputed": 5, "status_label": "BUY_TRIGGER"},
            {"ticker": "MSFT", "signal_rows_recomputed": 5, "status_label": "NOT_IN_BUY_ZONE"},
        ],
        create=True,
    ):
        store = store_cls.return_value
        store.list_universe_membership_current.return_value = membership_rows
        store.list_buy_zone_states.return_value = [{"ticker": "NVDA"}]
        result = runner.invoke(
            app,
            [
                "technical-signal-sync",
                "--start-date",
                "2020-01-01",
                "--end-date",
                "2026-03-11",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    store.list_universe_membership_current.assert_called_once_with(exclude_invalid=True)
    sync_mock.assert_called_once()
    _, kwargs = sync_mock.call_args
    assert kwargs["start_date"] == "2020-01-01"
    assert kwargs["end_date"] == "2026-03-11"
    parsed = _extract_json(result.stdout)
    assert parsed["ticker_count"] == 2
    assert parsed["buy_zone_count"] == 1
    assert parsed["status_counts"]["BUY_TRIGGER"] == 1
    assert parsed["status_counts"]["NOT_IN_BUY_ZONE"] == 1


def test_technical_universe_refresh_filters_previously_invalid_tickers():
    rows = [
        {
            "source_index": "SPY",
            "ticker": "BAD",
            "company_name": "Bad Co",
            "sector": "Technology",
            "as_of_date": "2026-03-11",
            "fetched_at_utc": "2026-03-11T12:00:00Z",
        },
        {
            "source_index": "QQQ",
            "ticker": "MSFT",
            "company_name": "Microsoft",
            "sector": "Technology",
            "as_of_date": "2026-03-11",
            "fetched_at_utc": "2026-03-11T12:00:00Z",
        },
    ]

    with patch("tradingagents.dealflow.current_universe.fetch_current_universe", return_value=rows, create=True), patch(
        "tradingagents.dealflow.current_universe.persist_current_universe_snapshot",
        return_value=Path("eval_results/control/technical_universe/2026-03-11/current_universe_spy_qqq.json"),
        create=True,
    ), patch("tradingagents.dealflow.technical_signal_store.SQLiteTechnicalSignalStore") as store_cls:
        store = store_cls.return_value
        store.list_invalid_yahoo_tickers.return_value = ["BAD"]
        result = runner.invoke(
            app,
            [
                "technical-universe-refresh",
                "--sources",
                "SPY",
                "--sources",
                "QQQ",
                "--as-of-date",
                "2026-03-11",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    store.upsert_universe_membership_current.assert_called_once_with([rows[1]])
    parsed = _extract_json(result.stdout)
    assert parsed["row_count"] == 1


def test_buy_zone_command_returns_json_state():
    payload = {
        "ticker": "NVDA",
        "as_of_date": "2026-03-11",
        "in_buy_zone": 1,
        "status_label": "BUY_TRIGGER",
        "reason": "Fresh KAMA cross inside bullish FVG regime",
        "last_cross_up_date": "2026-03-11",
        "bullish_fvg_regime_active": 1,
        "bullish_fvg_streak": 3,
        "bullish_fvg_regime_age_bars": 0,
        "fast_kama": 123.4,
        "slow_kama": 120.0,
        "score": 283.3,
        "updated_at_utc": "2026-03-11T12:10:00Z",
    }

    with patch("tradingagents.dealflow.technical_signal_store.SQLiteTechnicalSignalStore") as store_cls:
        store_cls.return_value.get_buy_zone_state.return_value = payload
        result = runner.invoke(app, ["buy-zone", "NVDA", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["ticker"] == "NVDA"
    assert parsed["status_label"] == "BUY_TRIGGER"


def test_buy_zone_summary_command_renders_table():
    rows = [
        {"ticker": "NVDA", "status_label": "BUY_TRIGGER", "reason": "Fresh KAMA cross", "score": 280.0, "as_of_date": "2026-03-11"},
        {"ticker": "MSFT", "status_label": "BUY_ZONE", "reason": "Trend still fresh", "score": 190.0, "as_of_date": "2026-03-11"},
    ]

    with patch("tradingagents.dealflow.technical_signal_store.SQLiteTechnicalSignalStore") as store_cls:
        store_cls.return_value.list_buy_zone_states.return_value = rows
        result = runner.invoke(app, ["buy-zone-summary", "--status", "BUY_TRIGGER", "--status", "BUY_ZONE"])

    assert result.exit_code == 0
    assert "Buy Zone Summary" in result.stdout
    assert "NVDA" in result.stdout
    assert "MSFT" in result.stdout


def test_fvg_qqq_backtest_command_threads_strategy_args():
    result_payload = {
        "ticker": "QQQ",
        "benchmark": "SPY",
        "total_trades": 4,
        "win_rate": 0.5,
        "avg_trade_return": 0.08,
        "total_return": 0.42,
        "max_drawdown": -0.12,
        "avg_hold_days": 34.5,
        "exit_reason_counts": {"timeout_90d": 2, "close_below_sma50": 2},
        "artifact_dir": "eval_results/deal_flow/fvg_strategy_backtest/2026-03-06/QQQ-vs-SPY",
        "trades": [],
    }

    with patch("tradingagents.dealflow.fvg_recall.run_fvg_strategy_backtest", return_value=result_payload, create=True) as run_mock:
        result = runner.invoke(
            app,
            ["fvg-qqq-backtest", "--start", "1999-01-01", "--format", "json"],
        )

    assert result.exit_code == 0
    _, kwargs = run_mock.call_args
    assert kwargs["ticker"] == "QQQ"
    assert kwargs["benchmark"] == "SPY"
    parsed = _extract_json(result.stdout)
    assert parsed["total_trades"] == 4


def test_fvg_qqq_backtest_command_threads_execution_timing():
    result_payload = {
        "ticker": "QQQ",
        "benchmark": "SPY",
        "execution_timing": "signal_close",
        "total_trades": 4,
        "win_rate": 0.5,
        "avg_trade_return": 0.08,
        "total_return": 0.42,
        "max_drawdown": -0.12,
        "avg_hold_days": 34.5,
        "exit_reason_counts": {"timeout_90d": 2, "close_below_sma50": 2},
        "artifact_dir": "eval_results/deal_flow/fvg_strategy_backtest/2026-03-06/QQQ-vs-SPY",
        "trades": [],
    }

    with patch("tradingagents.dealflow.fvg_recall.run_fvg_strategy_backtest", return_value=result_payload, create=True) as run_mock:
        result = runner.invoke(
            app,
            ["fvg-qqq-backtest", "--start", "1999-01-01", "--execution-timing", "signal_close", "--format", "json"],
        )

    assert result.exit_code == 0
    _, kwargs = run_mock.call_args
    assert kwargs["execution_timing"] == "signal_close"


def test_fvg_qqq_backtest_command_compare_exits_returns_comparison_payload():
    result_payload = {
        "ticker": "QQQ",
        "benchmark": "SPY",
        "strategies": {
            "exit_c": {"total_return": 0.4},
            "sma50_only": {"total_return": 0.5},
            "timeout_90d_only": {"total_return": 0.6},
            "buy_and_hold": {"total_return": 1.2},
        },
    }

    with patch("tradingagents.dealflow.fvg_recall.run_fvg_strategy_exit_comparison", return_value=result_payload, create=True) as run_mock:
        result = runner.invoke(
            app,
            ["fvg-qqq-backtest", "--start", "1999-01-01", "--compare-exits", "--format", "json"],
        )

    assert result.exit_code == 0
    run_mock.assert_called_once()
    parsed = _extract_json(result.stdout)
    assert parsed["strategies"]["buy_and_hold"]["total_return"] == 1.2


def test_analyze_from_queue_id_uses_queue_selection_path():
    queue_item = {
        "queue_id": "2026-02-05-090000-daily:AAPL",
        "symbol": "AAPL",
        "lane": "MOMENTUM",
        "momentum_score": 82.0,
        "asymmetry_score": 84.0,
        "research_playbook": "MOMENTUM_BREAKOUT",
        "selected_for_deep": True,
        "deal_flow_score": 88.0,
    }
    queue_data = {"run_id": "2026-02-05-090000-daily", "date": "2026-02-05"}

    with patch("cli.commands.scoring._find_queue_item", return_value=(queue_item, queue_data, Path("eval_results/deal_flow/latest_research_queue.json"))) as find_mock, patch(
        "cli.commands.scoring._build_noninteractive_selections",
        return_value={"ticker": "AAPL", "analysis_date": "2026-02-05", "analysts": []},
    ) as build_mock, patch("cli.commands.scoring.run_analysis") as run_mock, patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["analyze", "--from-queue-id", "2026-02-05-090000-daily:AAPL"])

    assert result.exit_code == 0
    find_mock.assert_called_once()
    build_mock.assert_called_once_with(
        "AAPL",
        "2026-02-05",
        queue_item=queue_item,
        analyst_provider=None,
        post_analyst_provider=None,
    )
    run_mock.assert_called_once_with({"ticker": "AAPL", "analysis_date": "2026-02-05", "analysts": []})


def test_analyze_from_queue_id_not_found_returns_error():
    with patch("cli.commands.scoring._find_queue_item", side_effect=ValueError("missing queue id")):
        result = runner.invoke(app, ["analyze", "--from-queue-id", "missing"])

    assert result.exit_code == 1
    assert "missing queue id" in result.stdout


def test_orchestrate_command_json_mode_wires_scheduler():
    orchestrate_result = {
        "ran": True,
        "trigger": "daily",
        "reason": "Daily pre-open window active and run not completed for date.",
        "date": "2026-02-06",
        "run_id": "2026-02-06-090000-daily",
        "signal_count": 42,
        "event_trigger": {"triggered": False, "reasons": [], "metrics": {}},
    }

    with patch("cli.commands.dealflow.DealFlowScheduler") as scheduler_cls, patch("cli.commands.dealflow.RatingAuditLog") as audit_cls:
        scheduler = Mock()
        scheduler.run_once.return_value = orchestrate_result
        scheduler_cls.return_value = scheduler
        audit_cls.return_value = Mock()

        result = runner.invoke(app, ["orchestrate", "--mode", "auto", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["ran"] is True
    assert parsed["trigger"] == "daily"
    scheduler.run_once.assert_called_once_with(force_trigger=None, as_of_date=None, top_k=30)


def test_step1_readiness_command_json_emits_snapshot():
    snapshot = {
        "overall_ready": True,
        "as_of_date": "2026-02-06",
        "gates": {
            "stability": {"pass": True, "consecutive_stable_cycles": 3, "required_stable_cycles": 3},
            "attribution_sample": {"pass": True, "evaluated_5d": 3, "required_5d": 2, "evaluated_20d": 3, "required_20d": 2},
            "connector_policy": {"pass": True, "missing_connectors": [], "degraded_connectors": []},
        },
    }

    with patch("cli.commands.dealflow.evaluate_step1_readiness", return_value=snapshot), patch(
        "cli.commands.dealflow.persist_step1_readiness",
        return_value=Path("eval_results/deal_flow/2026-02-06/step1_readiness.json"),
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["step1-readiness", "--date", "2026-02-06", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["overall_ready"] is True
    assert "output_path" in parsed


def test_evidence_telemetry_command_json_emits_report():
    report = {
        "from_date": "2026-02-06",
        "to_date": "2026-02-07",
        "sample_days": 2,
        "totals": {
            "processed": 6,
            "success_count": 5,
            "failure_count": 1,
            "skipped_count": 0,
            "estimated_x_api_calls": 9,
            "estimated_x_cost_usd": 4.5,
        },
        "alpha": {
            "5d": {"evaluated_count": 3, "avg_strategy_edge_vs_benchmark_pct": 0.8},
            "20d": {"evaluated_count": 2, "avg_strategy_edge_vs_benchmark_pct": 1.1},
        },
        "efficiency": {
            "5d_edge_bps_per_usd": 17.777778,
            "20d_edge_bps_per_usd": 24.444444,
        },
        "feature_family_dashboard": {"rows": []},
    }
    artifacts = {
        "cost_alpha_telemetry": Path("eval_results/evidence/2026-02-07/cost_alpha_telemetry.json"),
        "feature_family_dashboard": Path("eval_results/evidence/2026-02-07/feature_family_dashboard.json"),
    }

    with patch("cli.commands.dealflow.build_evidence_telemetry", return_value=(report, artifacts)):
        result = runner.invoke(
            app,
            [
                "evidence-telemetry",
                "--from-date",
                "2026-02-06",
                "--to-date",
                "2026-02-07",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["sample_days"] == 2
    assert parsed["totals"]["estimated_x_cost_usd"] == 4.5


def test_load_batch_summary_prefers_non_dry_run_artifact(tmp_path):
    dealflow_dir = tmp_path / "deal_flow" / "2026-02-06"
    dealflow_dir.mkdir(parents=True, exist_ok=True)
    (dealflow_dir / "batch_analyze_latest.json").write_text(
        json.dumps(
            {
                "run_id": "dry-run",
                "date": "2026-02-06",
                "dry_run": True,
                "items": [],
            },
            indent=2,
        )
    )
    (dealflow_dir / "batch_analyze_summary_120000.json").write_text(
        json.dumps(
            {
                "run_id": "real-run",
                "date": "2026-02-06",
                "dry_run": False,
                "items": [{"symbol": "AAPL"}],
            },
            indent=2,
        )
    )

    with patch("cli.common._dealflow_base_dir", return_value=tmp_path / "deal_flow"):
        payload, path = _load_batch_summary(queue_date="2026-02-06")

    assert payload["run_id"] == "real-run"
    assert path.name == "batch_analyze_summary_120000.json"


def test_analyze_batch_selected_only_runs_marked_items():
    queue_data = {
        "run_id": "2026-02-06-090000-daily",
        "date": "2026-02-06",
        "items": [
            {
                "queue_id": "2026-02-06-090000-daily:AAPL",
                "symbol": "AAPL",
                "lane": "CORE",
                "research_playbook": "VALUE_MEAN_REVERSION",
                "selected_for_deep": True,
            },
            {
                "queue_id": "2026-02-06-090000-daily:TSLA",
                "symbol": "TSLA",
                "lane": "MOMENTUM",
                "research_playbook": "MOMENTUM_BREAKOUT",
                "selected_for_deep": False,
            },
        ],
    }

    with patch("cli.commands.scoring._load_research_queue", return_value=(queue_data, Path("eval_results/deal_flow/latest_research_queue.json"))), patch(
        "cli.commands.scoring.subprocess.run", return_value=Mock(returncode=0)
    ) as run_mock, patch(
        "cli.commands.scoring._attach_realized_horizons"
    ), patch(
        "cli.commands.scoring._persist_batch_summary", return_value=Path("eval_results/deal_flow/2026-02-06/batch_analyze_latest.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["analyze-batch", "--selected-only", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["processed"] == 1
    assert parsed["success_count"] == 1
    assert run_mock.call_count == 1
    cmd = run_mock.call_args.args[0]
    assert any("AAPL" in part for part in cmd)
    assert "TSLA" not in " ".join(cmd)


def test_analyze_batch_default_uses_quick_mode_for_unselected():
    queue_data = {
        "run_id": "2026-02-06-090000-daily",
        "date": "2026-02-06",
        "items": [
            {
                "queue_id": "2026-02-06-090000-daily:AAPL",
                "symbol": "AAPL",
                "lane": "CORE",
                "research_playbook": "HYBRID_COMPOUNDER",
                "selected_for_deep": True,
            },
            {
                "queue_id": "2026-02-06-090000-daily:TSLA",
                "symbol": "TSLA",
                "lane": "MOMENTUM",
                "research_playbook": "MOMENTUM_BREAKOUT",
                "selected_for_deep": False,
            },
        ],
    }
    deep_outcome = {
        "analysis_report_path": "results/AAPL/2026-02-06/analysis_report.json",
        "analysis_report_found": True,
        "recommendation": "BUY",
        "aeternus_score": 81.0,
        "confidence": 4,
        "rating": "Buy",
    }

    def _run_side_effect(cmd, **kwargs):
        if "score" in cmd:
            return Mock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "ticker": "TSLA",
                        "date": "2026-02-06",
                        "aeternus_score": 73.5,
                        "rating": "Buy",
                        "confidence": 4,
                    }
                ),
                stderr="",
            )
        return Mock(returncode=0)

    with patch("cli.commands.scoring._load_research_queue", return_value=(queue_data, Path("eval_results/deal_flow/latest_research_queue.json"))), patch(
        "cli.commands.scoring.subprocess.run", side_effect=_run_side_effect
    ) as run_mock, patch(
        "cli.commands.scoring._extract_analysis_outcome", return_value=deep_outcome
    ), patch(
        "cli.commands.scoring._attach_realized_horizons"
    ), patch(
        "cli.commands.scoring._persist_batch_summary", return_value=Path("eval_results/deal_flow/2026-02-06/batch_analyze_latest.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["analyze-batch", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["processed"] == 2
    assert parsed["success_count"] == 2
    assert parsed["analysis_mode_counts"]["DEEP"] == 1
    assert parsed["analysis_mode_counts"]["QUICK"] == 1
    status_map = {item["symbol"]: item["status"] for item in parsed["items"]}
    mode_map = {item["symbol"]: item["analysis_mode"] for item in parsed["items"]}
    assert status_map["AAPL"] == "SUCCESS"
    assert status_map["TSLA"] == "SUCCESS_QUICK"
    assert mode_map["AAPL"] == "DEEP"
    assert mode_map["TSLA"] == "QUICK"
    assert run_mock.call_count == 2


def test_analyze_batch_quick_mode_uses_cached_report_when_json_missing():
    queue_data = {
        "run_id": "2026-02-06-090000-daily",
        "date": "2026-02-06",
        "items": [
            {
                "queue_id": "2026-02-06-090000-daily:VZ",
                "symbol": "VZ",
                "lane": "CORE",
                "research_playbook": "VALUE_MEAN_REVERSION",
                "selected_for_deep": False,
            }
        ],
    }
    cached_outcome = {
        "analysis_report_path": "results/VZ/2026-02-06/analysis_report.json",
        "analysis_report_found": True,
        "recommendation": "HOLD",
        "aeternus_score": 61.2,
        "confidence": 3,
        "rating": "Hold",
    }

    with patch("cli.commands.scoring._load_research_queue", return_value=(queue_data, Path("eval_results/deal_flow/latest_research_queue.json"))), patch(
        "cli.commands.scoring.subprocess.run",
        return_value=Mock(returncode=0, stdout="DEBUG: quick run complete\\n", stderr=""),
    ), patch(
        "cli.commands.scoring._extract_analysis_outcome",
        return_value=cached_outcome,
    ), patch(
        "cli.commands.scoring._attach_realized_horizons"
    ), patch(
        "cli.commands.scoring._persist_batch_summary", return_value=Path("eval_results/deal_flow/2026-02-06/batch_analyze_latest.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["analyze-batch", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["processed"] == 1
    assert parsed["success_count"] == 1
    assert parsed["failure_count"] == 0
    item = parsed["items"][0]
    assert item["status"] == "SUCCESS_QUICK_FALLBACK"
    assert "Reused existing analysis report" in str(item.get("reason", ""))
    assert item["analysis_report_found"] is True
    assert item["recommendation"] == "HOLD"


def test_analyze_batch_dry_run_includes_unselected_without_execution():
    queue_data = {
        "run_id": "2026-02-06-090000-daily",
        "date": "2026-02-06",
        "items": [
            {
                "queue_id": "2026-02-06-090000-daily:AAPL",
                "symbol": "AAPL",
                "selected_for_deep": True,
            },
            {
                "queue_id": "2026-02-06-090000-daily:TSLA",
                "symbol": "TSLA",
                "selected_for_deep": False,
            },
        ],
    }

    with patch("cli.commands.scoring._load_research_queue", return_value=(queue_data, Path("eval_results/deal_flow/latest_research_queue.json"))), patch(
        "cli.commands.scoring.subprocess.run"
    ) as run_mock, patch(
        "cli.commands.scoring._persist_batch_summary", return_value=Path("eval_results/deal_flow/2026-02-06/batch_analyze_latest.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "analyze-batch",
                "--include-unselected",
                "--dry-run",
                "--no-allow-cached-report-on-failure",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["processed"] == 2
    assert parsed["skipped_count"] == 2
    assert run_mock.call_count == 0
    assert all(item["status"] == "SKIPPED" for item in parsed["items"])


def test_analyze_batch_returns_nonzero_when_any_item_fails():
    queue_data = {
        "run_id": "2026-02-06-090000-daily",
        "date": "2026-02-06",
        "items": [
            {
                "queue_id": "2026-02-06-090000-daily:AAPL",
                "symbol": "AAPL",
                "selected_for_deep": True,
            }
        ],
    }

    with patch("cli.commands.scoring._load_research_queue", return_value=(queue_data, Path("eval_results/deal_flow/latest_research_queue.json"))), patch(
        "cli.commands.scoring.subprocess.run", return_value=Mock(returncode=3)
    ), patch(
        "cli.commands.scoring._persist_batch_summary", return_value=Path("eval_results/deal_flow/2026-02-06/batch_analyze_latest.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            ["analyze-batch", "--no-allow-cached-report-on-failure", "--format", "json"],
        )

    assert result.exit_code == 1
    parsed = _extract_json(result.stdout)
    assert parsed["failure_count"] == 1
    assert parsed["items"][0]["status"] == "FAILED"


def test_analyze_batch_marks_timeout_as_failed_with_code_124():
    queue_data = {
        "run_id": "2026-02-06-090000-daily",
        "date": "2026-02-06",
        "items": [
            {
                "queue_id": "2026-02-06-090000-daily:AAPL",
                "symbol": "AAPL",
                "selected_for_deep": True,
            }
        ],
    }

    timeout_exc = subprocess.TimeoutExpired(cmd=["python", "-m", "cli.main", "analyze"], timeout=180)
    with patch("cli.commands.scoring._load_research_queue", return_value=(queue_data, Path("eval_results/deal_flow/latest_research_queue.json"))), patch(
        "cli.commands.scoring.subprocess.run", side_effect=timeout_exc
    ) as run_mock, patch(
        "cli.commands.scoring._persist_batch_summary", return_value=Path("eval_results/deal_flow/2026-02-06/batch_analyze_latest.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "analyze-batch",
                "--per-item-timeout-seconds",
                "180",
                "--no-allow-cached-report-on-failure",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 1
    parsed = _extract_json(result.stdout)
    assert parsed["failure_count"] == 1
    assert parsed["per_item_timeout_seconds"] == 180
    item = parsed["items"][0]
    assert item["status"] == "FAILED"
    assert item["return_code"] == 124
    assert "Timed out after 180s while analyzing AAPL" in item["reason"]
    run_mock.assert_called_once()
    assert run_mock.call_args.kwargs["timeout"] == 180


def test_analyze_batch_uses_cached_report_when_execution_fails():
    queue_data = {
        "run_id": "2026-02-06-090000-daily",
        "date": "2026-02-06",
        "items": [
            {
                "queue_id": "2026-02-06-090000-daily:AAPL",
                "symbol": "AAPL",
                "lane": "CORE",
                "research_playbook": "HYBRID_COMPOUNDER",
                "selected_for_deep": True,
            }
        ],
    }
    cached_outcome = {
        "analysis_report_path": "results/AAPL/2026-02-06/analysis_report.json",
        "analysis_report_found": True,
        "recommendation": "BUY",
        "aeternus_score": 81.5,
        "confidence": 4,
        "rating": "Buy",
    }
    with patch("cli.commands.scoring._load_research_queue", return_value=(queue_data, Path("eval_results/deal_flow/latest_research_queue.json"))), patch(
        "cli.commands.scoring.subprocess.run", return_value=Mock(returncode=3)
    ), patch(
        "cli.commands.scoring._extract_analysis_outcome", return_value=cached_outcome
    ), patch(
        "cli.commands.scoring._attach_realized_horizons"
    ), patch(
        "cli.commands.scoring._persist_batch_summary", return_value=Path("eval_results/deal_flow/2026-02-06/batch_analyze_latest.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["analyze-batch", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["success_count"] == 1
    assert parsed["failure_count"] == 0
    assert parsed["items"][0]["status"] == "SUCCESS_CACHED"
    assert parsed["items"][0]["analysis_report_found"] is True
    assert parsed["items"][0]["recommendation"] == "BUY"


def test_analyze_batch_emits_attribution_by_lane_and_playbook():
    queue_data = {
        "run_id": "2026-02-06-090000-daily",
        "date": "2026-02-06",
        "items": [
            {
                "queue_id": "2026-02-06-090000-daily:AAPL",
                "symbol": "AAPL",
                "lane": "CORE",
                "research_playbook": "VALUE_MEAN_REVERSION",
                "selected_for_deep": True,
            },
            {
                "queue_id": "2026-02-06-090000-daily:TSLA",
                "symbol": "TSLA",
                "lane": "MOMENTUM",
                "research_playbook": "MOMENTUM_BREAKOUT",
                "selected_for_deep": True,
            },
        ],
    }

    outcomes = [
        {
            "analysis_report_path": "results/AAPL/2026-02-06/analysis_report.json",
            "analysis_report_found": True,
            "recommendation": "BUY",
            "aeternus_score": 88.0,
            "confidence": 5,
            "rating": "Strong Buy",
        },
        {
            "analysis_report_path": "results/TSLA/2026-02-06/analysis_report.json",
            "analysis_report_found": True,
            "recommendation": "MODERATE BUY",
            "aeternus_score": 81.0,
            "confidence": 4,
            "rating": "Buy",
        },
    ]

    with patch("cli.commands.scoring._load_research_queue", return_value=(queue_data, Path("eval_results/deal_flow/latest_research_queue.json"))), patch(
        "cli.commands.scoring.subprocess.run", return_value=Mock(returncode=0)
    ), patch(
        "cli.commands.scoring._extract_analysis_outcome", side_effect=outcomes
    ), patch(
        "cli.commands.scoring._attach_realized_horizons"
    ), patch(
        "cli.commands.scoring._persist_batch_summary", return_value=Path("eval_results/deal_flow/2026-02-06/batch_analyze_latest.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["analyze-batch", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["attribution"]["by_lane"]["CORE"]["success_count"] == 1
    assert parsed["attribution"]["by_lane"]["MOMENTUM"]["success_count"] == 1
    assert parsed["attribution"]["by_playbook"]["VALUE_MEAN_REVERSION"]["recommendation_counts"]["BUY"] == 1
    assert parsed["attribution"]["by_playbook"]["MOMENTUM_BREAKOUT"]["recommendation_counts"]["MODERATE BUY"] == 1


def test_analyze_batch_emits_attribution_by_signal_family():
    queue_data = {
        "run_id": "2026-02-06-090000-daily",
        "date": "2026-02-06",
        "items": [
            {
                "queue_id": "2026-02-06-090000-daily:AAPL",
                "symbol": "AAPL",
                "lane": "CORE",
                "research_playbook": "VALUE_MEAN_REVERSION",
                "selected_for_deep": True,
                "subscores": {
                    "price_momentum": 55.0,
                    "news_catalyst": 92.0,
                    "social_momentum": 80.0,
                },
            },
            {
                "queue_id": "2026-02-06-090000-daily:TSLA",
                "symbol": "TSLA",
                "lane": "MOMENTUM",
                "research_playbook": "MOMENTUM_BREAKOUT",
                "selected_for_deep": True,
                "subscores": {
                    "price_momentum": 95.0,
                    "news_catalyst": 60.0,
                    "social_momentum": 70.0,
                },
            },
        ],
    }

    outcomes = [
        {
            "analysis_report_path": "results/AAPL/2026-02-06/analysis_report.json",
            "analysis_report_found": True,
            "recommendation": "BUY",
            "aeternus_score": 88.0,
            "confidence": 5,
            "rating": "Strong Buy",
        },
        {
            "analysis_report_path": "results/TSLA/2026-02-06/analysis_report.json",
            "analysis_report_found": True,
            "recommendation": "MODERATE BUY",
            "aeternus_score": 81.0,
            "confidence": 4,
            "rating": "Buy",
        },
    ]

    with patch("cli.commands.scoring._load_research_queue", return_value=(queue_data, Path("eval_results/deal_flow/latest_research_queue.json"))), patch(
        "cli.commands.scoring.subprocess.run", return_value=Mock(returncode=0)
    ), patch(
        "cli.commands.scoring._extract_analysis_outcome", side_effect=outcomes
    ), patch(
        "cli.commands.scoring._attach_realized_horizons"
    ), patch(
        "cli.commands.scoring._persist_batch_summary", return_value=Path("eval_results/deal_flow/2026-02-06/batch_analyze_latest.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["analyze-batch", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["attribution"]["signal_family_counts"]["news_catalyst"] == 1


def test_collect_command_renders_fundamental_shadow_summary():
    shortlist = {
        "run_id": "2026-03-09-collect",
        "candidates": [],
        "fundamental_shadow_summary": {
            "strategy_name": "health_0p4__inv_growth_0p1__inv_quality_0p5",
            "coverage_summary": {
                "signal_count": 2,
                "ok_count": 2,
                "shortlist_overlap_count": 1,
                "selected_for_deep_overlap_count": 1,
            },
            "top_signals": [
                {
                    "symbol": "AAPL",
                    "raw_score": 78.4,
                    "in_shortlist": True,
                    "selected_for_deep": True,
                }
            ],
        },
    }
    research_queue = {"items": []}

    with patch("cli.commands.dealflow.DealFlowPipeline") as pipeline_cls:
        pipeline = pipeline_cls.return_value
        pipeline.collect.return_value = (
            shortlist,
            research_queue,
            [],
            {"triggered": False, "reasons": []},
        )
        result = runner.invoke(app, ["collect", "--date", "2026-03-09"])

    assert result.exit_code == 0
    assert "Fundamental Shadow" in result.stdout
    assert "health_0p4__inv_growth_0p1__inv_quality_0p5" in result.stdout


def test_analyze_batch_realized_attribution_by_lane_and_playbook():
    queue_data = {
        "run_id": "2026-01-02-090000-daily",
        "date": "2026-01-02",
        "items": [
            {
                "queue_id": "2026-01-02-090000-daily:AAPL",
                "symbol": "AAPL",
                "lane": "CORE",
                "research_playbook": "VALUE_MEAN_REVERSION",
                "selected_for_deep": True,
            },
            {
                "queue_id": "2026-01-02-090000-daily:TSLA",
                "symbol": "TSLA",
                "lane": "MOMENTUM",
                "research_playbook": "MOMENTUM_BREAKOUT",
                "selected_for_deep": True,
            },
        ],
    }
    outcomes = [
        {
            "analysis_report_path": "results/AAPL/2026-01-02/analysis_report.json",
            "analysis_report_found": True,
            "recommendation": "BUY",
            "aeternus_score": 88.0,
            "confidence": 5,
            "rating": "Strong Buy",
        },
        {
            "analysis_report_path": "results/TSLA/2026-01-02/analysis_report.json",
            "analysis_report_found": True,
            "recommendation": "BUY",
            "aeternus_score": 81.0,
            "confidence": 4,
            "rating": "Buy",
        },
    ]

    dates = pd.bdate_range("2026-01-02", periods=40)
    frame = pd.DataFrame(
        {
            ("AAPL", "Close"): [100.0 + idx for idx in range(len(dates))],
            ("TSLA", "Close"): [200.0 - 0.5 * idx for idx in range(len(dates))],
            ("SPY", "Close"): [400.0 + 0.3 * idx for idx in range(len(dates))],
        },
        index=dates,
    )
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)

    with patch("cli.commands.scoring._load_research_queue", return_value=(queue_data, Path("eval_results/deal_flow/latest_research_queue.json"))), patch(
        "cli.commands.scoring.subprocess.run", return_value=Mock(returncode=0)
    ), patch(
        "cli.commands.scoring._extract_analysis_outcome", side_effect=outcomes
    ), patch(
        "cli.common.yf.download", return_value=frame
    ), patch(
        "cli.commands.scoring._persist_batch_summary", return_value=Path("eval_results/deal_flow/2026-01-02/batch_analyze_latest.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["analyze-batch", "--queue-date", "2026-01-02", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)

    core_5d = parsed["attribution"]["by_lane"]["CORE"]["realized_horizons"]["5d"]
    mom_5d = parsed["attribution"]["by_lane"]["MOMENTUM"]["realized_horizons"]["5d"]
    assert core_5d["evaluated_count"] == 1
    assert mom_5d["evaluated_count"] == 1
    assert core_5d["avg_edge_vs_benchmark_pct"] is not None
    assert mom_5d["avg_edge_vs_benchmark_pct"] is not None

    pb_20d = parsed["attribution"]["by_playbook"]["MOMENTUM_BREAKOUT"]["realized_horizons"]["20d"]
    assert pb_20d["evaluated_count"] == 1
    assert pb_20d["avg_return_pct"] is not None


def test_analyze_batch_realized_attribution_marks_pending_horizon():
    queue_data = {
        "run_id": "2026-02-03-090000-daily",
        "date": "2026-02-03",
        "items": [
            {
                "queue_id": "2026-02-03-090000-daily:AAPL",
                "symbol": "AAPL",
                "lane": "CORE",
                "research_playbook": "HYBRID_COMPOUNDER",
                "selected_for_deep": True,
            }
        ],
    }
    outcomes = [
        {
            "analysis_report_path": "results/AAPL/2026-02-03/analysis_report.json",
            "analysis_report_found": True,
            "recommendation": "BUY",
            "aeternus_score": 75.0,
            "confidence": 4,
            "rating": "Buy",
        }
    ]

    dates = pd.bdate_range("2026-02-03", periods=8)
    frame = pd.DataFrame(
        {
            ("AAPL", "Close"): [100.0 + idx for idx in range(len(dates))],
            ("SPY", "Close"): [400.0 + 0.2 * idx for idx in range(len(dates))],
        },
        index=dates,
    )
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)

    with patch("cli.commands.scoring._load_research_queue", return_value=(queue_data, Path("eval_results/deal_flow/latest_research_queue.json"))), patch(
        "cli.commands.scoring.subprocess.run", return_value=Mock(returncode=0)
    ), patch(
        "cli.commands.scoring._extract_analysis_outcome", side_effect=outcomes
    ), patch(
        "cli.common.yf.download", return_value=frame
    ), patch(
        "cli.commands.scoring._persist_batch_summary", return_value=Path("eval_results/deal_flow/2026-02-03/batch_analyze_latest.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["analyze-batch", "--queue-date", "2026-02-03", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    hz5 = parsed["attribution"]["overall"]["realized_horizons"]["5d"]
    hz20 = parsed["attribution"]["overall"]["realized_horizons"]["20d"]
    assert hz5["evaluated_count"] == 1
    assert hz20["pending_count"] == 1


def test_watchlist_add_list_remove_json(tmp_path):
    watchlist_path = tmp_path / "manual_watchlist.json"

    with patch.dict("cli.commands.dealflow.DEFAULT_CONFIG", {"dealflow_manual_watchlist_path": str(watchlist_path)}, clear=False), patch(
        "tradingagents.dealflow.manual_watchlist.get_company_context",
        side_effect=lambda symbol, **_: {
            "akg": {
                "found": True,
                "display_name": f"{symbol} Inc",
                "sector": "Technology",
                "aeternus_score": 77,
                "node": {
                    "asset_class": "Equity",
                    "last_scored_date": "2026-03-22",
                },
            }
        },
    ):
        add_result = runner.invoke(
            app,
            [
                "watchlist",
                "add",
                "AAPL, MSFT, GOOGL",
                "--format",
                "json",
            ],
        )
        assert add_result.exit_code == 0
        add_payload = _extract_json(add_result.stdout)
        assert add_payload["count"] == 3
        assert [row["symbol"] for row in add_payload["items"]] == ["AAPL", "MSFT", "GOOGL"]
        assert add_payload["items"][0]["context_snapshot"]["display_name"] == "AAPL Inc"

        list_result = runner.invoke(app, ["watchlist", "list", "--format", "json"])
        assert list_result.exit_code == 0
        list_payload = _extract_json(list_result.stdout)
        assert list_payload["count"] == 3
        assert list_payload["items"][0]["symbol"] == "AAPL"

        remove_result = runner.invoke(app, ["watchlist", "remove", "AAPL, GOOGL", "--format", "json"])
        assert remove_result.exit_code == 0
        remove_payload = _extract_json(remove_result.stdout)
        assert remove_payload["action"] == "removed"
        assert remove_payload["count"] == 2
        assert remove_payload["symbols"] == ["AAPL", "GOOGL"]

        active_list_result = runner.invoke(app, ["watchlist", "list", "--format", "json"])
        assert active_list_result.exit_code == 0
        active_list_payload = _extract_json(active_list_result.stdout)
        assert active_list_payload["count"] == 1
        assert [row["symbol"] for row in active_list_payload["items"]] == ["MSFT"]

        all_list_result = runner.invoke(app, ["watchlist", "list", "--all", "--format", "json"])
        assert all_list_result.exit_code == 0
        all_list_payload = _extract_json(all_list_result.stdout)
        assert all_list_payload["count"] == 3
        inactive_rows = [row for row in all_list_payload["items"] if row["symbol"] in {"AAPL", "GOOGL"}]
        assert len(inactive_rows) == 2
        assert all(row["active"] is False for row in inactive_rows)


def test_watchlist_add_remove_accepts_unquoted_multi_arg_input(tmp_path):
    watchlist_path = tmp_path / "manual_watchlist.json"

    with patch.dict("cli.commands.dealflow.DEFAULT_CONFIG", {"dealflow_manual_watchlist_path": str(watchlist_path)}, clear=False), patch(
        "tradingagents.dealflow.manual_watchlist.get_company_context",
        side_effect=lambda symbol, **_: {
            "akg": {
                "found": True,
                "display_name": f"{symbol} Inc",
                "sector": "Technology",
                "aeternus_score": 77,
                "node": {
                    "asset_class": "Equity",
                    "last_scored_date": "2026-03-22",
                },
            }
        },
    ):
        add_result = runner.invoke(
            app,
            ["watchlist", "add", "AAPL,", "MSFT,", "GOOGL", "--format", "json"],
        )
        assert add_result.exit_code == 0
        add_payload = _extract_json(add_result.stdout)
        assert add_payload["count"] == 3
        assert [row["symbol"] for row in add_payload["items"]] == ["AAPL", "MSFT", "GOOGL"]

        remove_result = runner.invoke(
            app,
            ["watchlist", "remove", "AAPL,", "MSFT", "--format", "json"],
        )
        assert remove_result.exit_code == 0
        remove_payload = _extract_json(remove_result.stdout)
        assert remove_payload["count"] == 2
        assert remove_payload["symbols"] == ["AAPL", "MSFT"]


def test_x_discovery_command_json():
    payload = {
        "as_of_date": "2026-02-06",
        "lookback_days": 30,
        "seed_handle_count": 5,
        "events_analyzed": 50,
        "symbol_edge_coverage": 10,
        "generated_at": "2026-02-06T00:00:00+00:00",
        "candidates": [{"handle": "new_handle", "composite_score": 77.1}],
    }

    with patch("cli.commands.dealflow.run_x_account_discovery", return_value=payload), patch(
        "cli.commands.dealflow.persist_x_account_candidates",
        return_value=Path("eval_results/deal_flow/2026-02-06/x_account_candidates.json"),
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["x-discovery", "--date", "2026-02-06", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["as_of_date"] == "2026-02-06"
    assert parsed["candidates"][0]["handle"] == "new_handle"
    assert str(parsed["output_path"]).endswith("x_account_candidates.json")


def test_source_table_prints_x_scope_and_manual_merge_lines():
    shortlist = {
        "run_id": "2026-02-05-090000-manual",
        "date": "2026-02-05",
        "trigger": "manual",
        "top_k": 20,
        "candidates": [],
        "event_triggered": True,
        "event_reasons": ["SPY move 2.10%"],
        "connector_health_summary": {
            "status_totals": {"OK": 5, "NO_DATA": 1, "ERROR": 0, "NOT_CONFIGURED": 1}
        },
        "x_scope_summary": {"mode": "HYBRID", "handles": 10, "symbol_calls": 4, "expansions": 2},
        "manual_merge_summary": {"requested": 3, "included": 2, "reinforced": 1, "rejected": 0},
    }
    queue = {
        "run_id": "2026-02-05-090000-manual",
        "date": "2026-02-05",
        "items": [],
        "deep_k": 8,
        "selected_queue_ids": [],
        "source_artifact": "eval_results/deal_flow/2026-02-05/shortlist_top20.json",
    }

    with patch("cli.commands.dealflow.DealFlowPipeline") as pipeline_cls, patch("cli.commands.dealflow.RatingAuditLog") as audit_cls:
        pipeline_cls.return_value.run.return_value = (
            shortlist,
            queue,
            [{"symbol": "AAPL", "signal_family": "news_catalyst"}],
            {"triggered": True, "reasons": ["SPY move 2.10%"], "metrics": {}},
        )
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            ["source", "--date", "2026-02-05", "--trigger", "manual", "--top-k", "20", "--format", "table"],
        )

    assert result.exit_code == 0
    assert "X scope:" in result.stdout
    assert "Manual merge:" in result.stdout


def test_source_profile_applies_max_recall_overrides():
    shortlist = {
        "run_id": "2026-02-05-090000-manual",
        "date": "2026-02-05",
        "trigger": "manual",
        "top_k": 20,
        "candidates": [],
        "event_triggered": False,
        "event_reasons": [],
    }
    queue = {
        "run_id": "2026-02-05-090000-manual",
        "date": "2026-02-05",
        "items": [],
        "deep_k": 8,
        "selected_queue_ids": [],
        "source_artifact": "eval_results/deal_flow/2026-02-05/shortlist_top20.json",
    }

    with patch("cli.commands.dealflow.DealFlowPipeline") as pipeline_cls, patch("cli.commands.dealflow.RatingAuditLog") as audit_cls:
        pipeline_cls.return_value.run.return_value = (shortlist, queue, [], {"triggered": False, "reasons": [], "metrics": {}})
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "source",
                "--date",
                "2026-02-05",
                "--trigger",
                "manual",
                "--top-k",
                "20",
                "--profile",
                "max-recall",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    config = pipeline_cls.call_args.kwargs["config"]
    assert config["dealflow_run_profile"] == "MAX_RECALL"


def test_source_profile_auto_defaults_to_low_cost_when_non_interactive():
    shortlist = {
        "run_id": "2026-02-05-090000-manual",
        "date": "2026-02-05",
        "trigger": "manual",
        "top_k": 20,
        "candidates": [],
        "event_triggered": False,
        "event_reasons": [],
    }
    queue = {
        "run_id": "2026-02-05-090000-manual",
        "date": "2026-02-05",
        "items": [],
        "deep_k": 8,
        "selected_queue_ids": [],
        "source_artifact": "eval_results/deal_flow/2026-02-05/shortlist_top20.json",
    }

    with patch("cli.commands.dealflow.DealFlowPipeline") as pipeline_cls, patch("cli.commands.dealflow.RatingAuditLog") as audit_cls:
        pipeline_cls.return_value.run.return_value = (shortlist, queue, [], {"triggered": False, "reasons": [], "metrics": {}})
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "source",
                "--date",
                "2026-02-05",
                "--trigger",
                "manual",
                "--top-k",
                "20",
                "--profile",
                "auto",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["run_profile"] == "LOW_COST"
    config = pipeline_cls.call_args.kwargs["config"]
    assert config["dealflow_run_profile"] == "LOW_COST"


def test_source_profile_defaults_to_daily_low_cost():
    shortlist = {
        "run_id": "2026-02-05-090000-daily",
        "date": "2026-02-05",
        "trigger": "daily",
        "top_k": 20,
        "candidates": [],
        "event_triggered": False,
        "event_reasons": [],
    }
    queue = {
        "run_id": "2026-02-05-090000-daily",
        "date": "2026-02-05",
        "items": [],
        "deep_k": 8,
        "selected_queue_ids": [],
        "source_artifact": "eval_results/deal_flow/2026-02-05/shortlist_top20.json",
    }

    with patch("cli.commands.dealflow.DealFlowPipeline") as pipeline_cls, patch("cli.commands.dealflow.RatingAuditLog") as audit_cls:
        pipeline_cls.return_value.run.return_value = (shortlist, queue, [], {"triggered": False, "reasons": [], "metrics": {}})
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "source",
                "--date",
                "2026-02-05",
                "--trigger",
                "daily",
                "--top-k",
                "20",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["run_profile"] == "LOW_COST"
    config = pipeline_cls.call_args.kwargs["config"]
    assert config["dealflow_run_profile"] == "LOW_COST"


def test_portfolio_plan_command_json_emits_plan_payload():
    batch_summary = {"run_id": "2026-02-06-batch", "date": "2026-02-06", "items": []}
    plan = {"plan_id": "plan-1", "date": "2026-02-06", "orders": [{"symbol": "AAPL"}]}

    with patch("cli.commands.portfolio._load_batch_summary", return_value=(batch_summary, Path("eval_results/deal_flow/2026-02-06/batch_analyze_latest.json"))), patch(
        "cli.commands.portfolio.build_portfolio_plan", return_value=plan
    ), patch(
        "cli.commands.portfolio._persist_portfolio_plan", return_value=Path("eval_results/paper_execution/plans/2026-02-06/portfolio_plan_120000.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            ["portfolio-plan", "--queue-date", "2026-02-06", "--skip-hedges", "--format", "json"],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["plan_id"] == "plan-1"
    assert parsed["plan_path"].endswith("portfolio_plan_120000.json")


def test_persist_research_conversion_integrity_writes_artifact_and_uses_same_date_plan(tmp_path, monkeypatch):
    from cli.commands.scoring import _persist_research_conversion_integrity

    monkeypatch.chdir(tmp_path)
    plans_dir = tmp_path / "eval_results" / "paper_execution" / "plans" / "2026-03-08"
    plans_dir.mkdir(parents=True)
    (plans_dir / "portfolio_plan_120000.json").write_text(
        json.dumps(
            {
                "plan_id": "plan-1",
                "date": "2026-03-08",
                "orders": [{"symbol": "AAPL"}],
            }
        )
    )
    summary = {
        "run_id": "2026-03-08-batch",
        "date": "2026-03-08",
        "requested": 2,
        "processed": 2,
        "include_unselected": True,
        "quick_unselected": True,
        "per_item_timeout_seconds": 420,
        "items": [
            {
                "symbol": "AAPL",
                "selected_for_deep": True,
                "analysis_mode": "DEEP",
                "status": "SUCCESS",
                "analysis_report_found": True,
                "aeternus_score": 70.0,
                "recommendation": "BUY",
                "realized_horizons": {"5d": 0.03},
            },
            {
                "symbol": "PLTR",
                "selected_for_deep": False,
                "analysis_mode": "QUICK",
                "status": "FAILED",
                "analysis_report_found": False,
                "aeternus_score": None,
                "recommendation": "UNKNOWN",
                "realized_horizons": {},
            },
        ],
    }

    artifact_path = _persist_research_conversion_integrity("2026-03-08", summary)

    assert artifact_path is not None
    assert artifact_path.name == "research_conversion_integrity.json"
    payload = json.loads(artifact_path.read_text())
    assert payload["rule_snapshot"]["portfolio_plan_found"] is True
    assert payload["coverage_summary"]["candidate_count"] == 2
    assert payload["coverage_summary"]["portfolio_included_count"] == 1
    assert payload["portfolio_plan_path"].endswith("portfolio_plan_120000.json")


def test_portfolio_plan_command_uses_whole_share_mode_for_alpaca():
    batch_summary = {"run_id": "2026-02-06-batch", "date": "2026-02-06", "items": []}
    plan = {"plan_id": "plan-1", "date": "2026-02-06", "orders": []}

    with patch("cli.commands.portfolio._load_batch_summary", return_value=(batch_summary, Path("eval_results/deal_flow/2026-02-06/batch_analyze_latest.json"))), patch(
        "cli.commands.portfolio.build_portfolio_plan", return_value=plan
    ) as build_mock, patch(
        "cli.commands.portfolio._persist_portfolio_plan", return_value=Path("eval_results/paper_execution/plans/2026-02-06/portfolio_plan_120000.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls, patch.dict("cli.commands.portfolio.DEFAULT_CONFIG", {"alpaca_enforce_whole_shares": True}, clear=False):
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "portfolio-plan",
                "--queue-date",
                "2026-02-06",
                "--execution-mode",
                "alpaca-paper",
                "--skip-hedges",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    assert build_mock.call_args.kwargs["enforce_whole_shares"] is True


def test_portfolio_plan_command_adds_hedge_intent_when_enabled():
    batch_summary = {"run_id": "2026-02-06-batch", "date": "2026-02-06", "items": []}
    base_plan = {
        "plan_id": "plan-hedge",
        "date": "2026-02-06",
        "orders": [{"symbol": "AAPL", "intent_category": "ALPHA"}],
    }
    hedge_order = {
        "order_intent_id": "hedge-intent-1",
        "symbol": "SPY",
        "intent_category": "HEDGE",
        "side": "SELL",
    }

    with patch(
        "cli.commands.portfolio._load_batch_summary",
        return_value=(batch_summary, Path("eval_results/deal_flow/2026-02-06/batch_analyze_latest.json")),
    ), patch(
        "cli.commands.portfolio.build_portfolio_plan",
        return_value=dict(base_plan),
    ), patch(
        "cli.commands.portfolio._persist_portfolio_plan",
        return_value=Path("eval_results/paper_execution/plans/2026-02-06/portfolio_plan_120000.json"),
    ), patch(
        "cli.commands.portfolio.build_portfolio_risk_snapshot",
        return_value={"gross_exposure_usd": 100000.0},
    ), patch("cli.common.MarketRegimeProvider") as provider_cls, patch(
        "cli.commands.portfolio.AdaptiveHedgeEngine"
    ) as engine_cls, patch(
        "cli.commands.portfolio.build_hedge_order_intent",
        return_value=hedge_order,
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        provider_cls.return_value.get_market_regime_snapshot.return_value = {"spy_close": 500.0}
        engine = Mock()
        engine.compute_hedge_signal.return_value = {"mode": "BULL", "market_regime": "BULL"}
        engine.decide_hedge.return_value = {
            "status": "EXECUTED",
            "action": "INCREASE_HEDGE",
            "instrument": "SPY",
            "final_target_hedge_pct": 50.0,
            "delta_hedge_pct": 50.0,
            "delta_notional_usd": 50000.0,
            "reason": "defensive",
        }
        engine_cls.return_value = engine
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            ["portfolio-plan", "--queue-date", "2026-02-06", "--include-hedges", "--skip-cc-wyckoff", "--skip-cc-scanner", "--format", "json"],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert len(parsed["orders"]) == 2
    assert any(str(order.get("intent_category")) == "HEDGE" for order in parsed["orders"])
    assert bool(parsed.get("hedge_context", {}).get("order_added")) is True
    assert parsed.get("portfolio_risk_summary", {}).get("hedge_action") == "INCREASE_HEDGE"


def test_execute_paper_command_json_uses_adapter_result():
    plan = {
        "plan_id": "plan-1",
        "date": "2026-02-06",
        "orders": [
            {
                "order_intent_id": "intent-1",
                "symbol": "AAPL",
                "side": "BUY",
                "target_notional_usd": 1000.0,
                "target_quantity": 10.0,
                "reference_price": 100.0,
            }
        ],
    }
    risk_result = {
        "status": "PASS",
        "orders_considered": 1,
        "accepted_count": 1,
        "rejected_count": 0,
        "accepted_orders": plan["orders"],
        "rejected_orders": [],
        "rejected_reason_counts": {},
    }
    rebalance_plan = {
        **plan,
        "rebalance": {
            "mode": "DELTA_TO_TARGET",
            "input_orders": 1,
            "output_orders": 1,
            "skipped_within_tolerance": 0,
        },
    }
    execution_result = {
        "plan_id": "plan-1",
        "date": "2026-02-06",
        "executed_orders": 1,
        "skipped_duplicate_orders": 0,
        "orders": [
            {
                "symbol": "AAPL",
                "rating_id": "rid-1",
                "side": "BUY",
                "filled_quantity": 10.0,
                "filled_price": 100.0,
                "filled_notional_usd": 1000.0,
                "lane": "CORE",
                "research_playbook": "HYBRID_COMPOUNDER",
                "status": "FILLED",
            }
        ],
    }

    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "cli.commands.execution._load_portfolio_plan", return_value=(plan, Path("eval_results/paper_execution/latest_plan.json"))
    ), patch(
        "cli.commands.execution.build_rebalance_execution_plan", return_value=rebalance_plan
    ), patch(
        "cli.commands.execution.evaluate_pretrade_risk", return_value=risk_result
    ), patch(
        "cli.commands.execution._persist_pretrade_risk", return_value=Path("eval_results/paper_execution/latest_pretrade_risk.json")
    ), patch(
        "cli.commands.execution._evaluate_position_parity_gate",
        return_value={"status": "SKIPPED_MODE", "drift_count": 0, "drift_symbols": []},
    ), patch(
        "cli.commands.execution.execute_plan_with_adapter", return_value=execution_result
    ) as exec_mock, patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["execute-paper", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["executed_orders"] == 1
    assert parsed["rebalance"]["mode"] == "DELTA_TO_TARGET"
    assert parsed["position_parity"]["status"] == "SKIPPED_MODE"
    exec_mock.assert_called_once()


def test_execute_paper_updates_hedge_state_when_hedge_order_is_processed():
    hedge_order = {
        "order_intent_id": "hedge-1",
        "symbol": "SPY",
        "side": "SELL",
        "intent_category": "HEDGE",
        "target_notional_usd": 50000.0,
        "target_quantity": 100.0,
        "reference_price": 500.0,
    }
    plan = {
        "plan_id": "plan-hedge-sync",
        "date": "2026-02-06",
        "orders": [hedge_order],
        "hedge_context": {
            "signal": {"mode": "BULL", "market_regime": "BULL"},
            "decision": {
                "status": "EXECUTED",
                "instrument": "SPY",
                "action": "INCREASE_HEDGE",
                "final_target_hedge_pct": 50.0,
                "delta_hedge_pct": 50.0,
                "delta_notional_usd": 50000.0,
                "reason": "defensive",
            },
            "portfolio_snapshot": {"gross_exposure_usd": 100000.0, "current_hedge_pct": 0.0},
        },
    }
    risk_result = {
        "status": "PASS",
        "orders_considered": 1,
        "accepted_count": 1,
        "rejected_count": 0,
        "accepted_orders": [hedge_order],
        "rejected_orders": [],
        "rejected_reason_counts": {},
    }
    execution_result = {
        "plan_id": "plan-hedge-sync",
        "date": "2026-02-06",
        "executed_orders": 0,
        "submitted_orders": 1,
        "skipped_duplicate_orders": 0,
        "orders": [
            {
                "order_intent_id": "hedge-1",
                "symbol": "SPY",
                "side": "SELL",
                "intent_category": "HEDGE",
                "status": "SUBMITTED",
            }
        ],
    }

    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "cli.commands.execution._load_portfolio_plan",
        return_value=(plan, Path("eval_results/paper_execution/latest_plan.json")),
    ), patch(
        "cli.commands.execution.build_rebalance_execution_plan", return_value=plan
    ), patch(
        "cli.commands.execution.evaluate_pretrade_risk", return_value=risk_result
    ), patch(
        "cli.commands.execution._persist_pretrade_risk", return_value=Path("eval_results/paper_execution/latest_pretrade_risk.json")
    ), patch(
        "cli.commands.execution._evaluate_position_parity_gate",
        return_value={"status": "SKIPPED_MODE", "drift_count": 0, "drift_symbols": []},
    ), patch(
        "cli.commands.execution.execute_plan_with_adapter", return_value=execution_result
    ), patch("cli.commands.execution.AdaptiveHedgeEngine") as engine_cls, patch(
        "cli.commands.execution.RatingAuditLog"
    ) as audit_cls:
        engine = Mock()
        engine.persist_state_and_orders.return_value = {"timestamp": "2026-02-06T00:00:00Z"}
        engine_cls.return_value = engine
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["execute-paper", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert bool(parsed.get("hedge_sync", {}).get("state_updated")) is True
    assert parsed.get("hedge_sync", {}).get("orders_seen") == 1
    engine.persist_state_and_orders.assert_called_once()


def test_execute_paper_live_mode_uses_live_paths():
    plan = {
        "plan_id": "plan-live",
        "date": "2026-02-06",
        "orders": [
            {
                "order_intent_id": "intent-1",
                "symbol": "AAPL",
                "side": "BUY",
                "target_notional_usd": 1000.0,
                "target_quantity": 10.0,
                "reference_price": 100.0,
            }
        ],
    }
    risk_result = {
        "status": "PASS",
        "orders_considered": 1,
        "accepted_count": 1,
        "rejected_count": 0,
        "accepted_orders": plan["orders"],
        "rejected_orders": [],
        "rejected_reason_counts": {},
    }
    rebalance_plan = {
        **plan,
        "rebalance": {
            "mode": "DELTA_TO_TARGET",
            "input_orders": 1,
            "output_orders": 1,
            "skipped_within_tolerance": 0,
        },
    }
    execution_result = {
        "plan_id": "plan-live",
        "date": "2026-02-06",
        "execution_mode": "live",
        "executed_orders": 0,
        "submitted_orders": 1,
        "skipped_duplicate_orders": 0,
        "orders": [{"symbol": "AAPL", "status": "SUBMITTED"}],
    }

    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "cli.commands.execution._load_portfolio_plan", return_value=(plan, Path("eval_results/paper_execution/latest_plan.json"))
    ), patch(
        "cli.commands.execution.build_rebalance_execution_plan", return_value=rebalance_plan
    ), patch(
        "cli.commands.execution.evaluate_pretrade_risk", return_value=risk_result
    ), patch(
        "cli.commands.execution._persist_pretrade_risk", return_value=Path("eval_results/paper_execution/latest_pretrade_risk.json")
    ), patch(
        "cli.commands.execution.execute_plan_with_adapter", return_value=execution_result
    ) as exec_mock, patch(
        "cli.commands.execution._evaluate_position_parity_gate",
        return_value={"status": "SKIPPED_MODE", "drift_count": 0, "drift_symbols": []},
    ), patch("cli.common.RatingAuditLog") as audit_cls, patch.dict(
        "cli.commands.execution.DEFAULT_CONFIG",
        {
            "live_execution_outbox_path": "eval_results/live_execution/outbox.json",
            "live_positions_shadow_path": "eval_results/paper_execution/positions.json",
        },
        clear=False,
    ):
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["execute-paper", "--execution-mode", "live", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["execution_mode"] == "live"
    assert parsed["submitted_orders"] == 1
    exec_mock.assert_called_once()
    kwargs = exec_mock.call_args.kwargs
    assert kwargs["execution_mode"] == "live"
    assert kwargs["orders_path"].endswith("eval_results/live_execution/outbox.json")


def test_execute_paper_alpaca_mode_uses_live_paths():
    plan = {
        "plan_id": "plan-alpaca",
        "date": "2026-02-06",
        "orders": [
            {
                "order_intent_id": "intent-1",
                "symbol": "AAPL",
                "side": "BUY",
                "target_notional_usd": 1000.0,
                "target_quantity": 10.0,
                "reference_price": 100.0,
            }
        ],
    }
    risk_result = {
        "status": "PASS",
        "orders_considered": 1,
        "accepted_count": 1,
        "rejected_count": 0,
        "accepted_orders": plan["orders"],
        "rejected_orders": [],
        "rejected_reason_counts": {},
    }
    execution_result = {
        "plan_id": "plan-alpaca",
        "date": "2026-02-06",
        "execution_mode": "alpaca-paper",
        "executed_orders": 0,
        "submitted_orders": 1,
        "skipped_duplicate_orders": 0,
        "orders": [{"symbol": "AAPL", "status": "SUBMITTED"}],
    }

    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "cli.commands.execution._load_portfolio_plan", return_value=(plan, Path("eval_results/paper_execution/latest_plan.json"))
    ), patch(
        "cli.commands.execution.build_rebalance_execution_plan", return_value=plan
    ), patch(
        "cli.commands.execution.evaluate_pretrade_risk", return_value=risk_result
    ), patch(
        "cli.commands.execution._persist_pretrade_risk", return_value=Path("eval_results/paper_execution/latest_pretrade_risk.json")
    ), patch(
        "cli.commands.execution.execute_plan_with_adapter", return_value=execution_result
    ) as exec_mock, patch(
        "cli.commands.execution._evaluate_position_parity_gate",
        return_value={
            "status": "CLEAR",
            "all_clear": True,
            "drift_count": 0,
            "drift_symbols": [],
            "total_notional_drift_usd": 0.0,
        },
    ), patch("cli.common.RatingAuditLog") as audit_cls, patch.dict(
        "cli.commands.execution.DEFAULT_CONFIG",
        {
            "live_execution_outbox_path": "eval_results/live_execution/outbox.json",
            "live_positions_shadow_path": "eval_results/paper_execution/positions.json",
        },
        clear=False,
    ):
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["execute-paper", "--execution-mode", "alpaca-paper", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["execution_mode"] == "alpaca-paper"
    assert parsed["submitted_orders"] == 1
    kwargs = exec_mock.call_args.kwargs
    assert kwargs["orders_path"].endswith("eval_results/live_execution/outbox.json")


def test_execute_paper_blocks_on_position_parity_drift_in_alpaca_mode():
    plan = {
        "plan_id": "plan-parity",
        "date": "2026-02-06",
        "orders": [
            {
                "order_intent_id": "intent-1",
                "symbol": "AAPL",
                "side": "BUY",
                "target_notional_usd": 1000.0,
                "target_quantity": 10.0,
                "reference_price": 100.0,
            }
        ],
    }
    risk_result = {
        "status": "PASS",
        "orders_considered": 1,
        "accepted_count": 1,
        "rejected_count": 0,
        "accepted_orders": plan["orders"],
        "rejected_orders": [],
        "rejected_reason_counts": {},
    }
    parity_report = {
        "status": "DRIFT_DETECTED",
        "all_clear": False,
        "drift_count": 1,
        "drift_symbols": ["AAPL"],
        "total_notional_drift_usd": 1000.0,
        "positions_drift_path": "eval_results/live_execution/positions_drift/latest.json",
    }

    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "cli.commands.execution._load_portfolio_plan",
        return_value=(plan, Path("eval_results/paper_execution/latest_plan.json")),
    ), patch(
        "cli.commands.execution.build_rebalance_execution_plan",
        return_value=plan,
    ), patch(
        "cli.commands.execution.evaluate_pretrade_risk",
        return_value=risk_result,
    ), patch(
        "cli.commands.execution._persist_pretrade_risk",
        return_value=Path("eval_results/paper_execution/latest_pretrade_risk.json"),
    ), patch(
        "cli.commands.execution._evaluate_position_parity_gate",
        return_value=parity_report,
    ), patch(
        "cli.commands.execution.execute_plan_with_adapter"
    ) as exec_mock, patch("cli.common.RatingAuditLog") as audit_cls, patch.dict(
        "cli.commands.execution.DEFAULT_CONFIG",
        {
            "live_execution_outbox_path": "eval_results/live_execution/outbox.json",
            "live_positions_shadow_path": "eval_results/paper_execution/positions.json",
            "execution_require_position_parity_for_live": True,
            "execution_block_on_position_drift": True,
        },
        clear=False,
    ):
        audit_cls.return_value = Mock()
        result = runner.invoke(app, ["execute-paper", "--execution-mode", "alpaca-paper", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["position_parity"]["status"] == "DRIFT_DETECTED"
    assert parsed["position_parity"]["blocked_submission"] is True
    assert parsed["risk_check"]["status"] == "REJECTED"
    assert parsed["risk_check"]["accepted_count"] == 0
    assert parsed["risk_check"]["rejected_reason_counts"]["POSITION_PARITY_DRIFT"] >= 1
    assert parsed["submitted_orders"] == 0
    exec_mock.assert_not_called()


def test_pull_broker_orders_command_json_alpaca():
    snapshot = {
        "source": "alpaca",
        "mode": "alpaca-paper",
        "fetched_at": "2026-02-07T00:00:00+00:00",
        "status": "all",
        "limit": 500,
        "orders": [{"id": "ord-1"}],
    }
    with patch("cli.commands.execution.fetch_alpaca_orders_snapshot", return_value=snapshot) as fetch_mock, patch(
        "cli.commands.execution.RatingAuditLog"
    ) as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "pull-broker-orders",
                "--broker",
                "alpaca",
                "--mode",
                "alpaca-paper",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["broker"] == "alpaca"
    assert parsed["orders"] == 1
    fetch_mock.assert_called_once()


def test_pull_broker_positions_command_json_alpaca():
    snapshot = {
        "source": "alpaca",
        "mode": "alpaca-paper",
        "fetched_at": "2026-02-07T00:00:00+00:00",
        "positions": [{"symbol": "AAPL", "qty": "10"}],
    }
    with patch("cli.commands.execution.fetch_alpaca_positions_snapshot", return_value=snapshot) as fetch_mock, patch(
        "cli.commands.execution.RatingAuditLog"
    ) as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "pull-broker-positions",
                "--broker",
                "alpaca",
                "--mode",
                "alpaca-paper",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["broker"] == "alpaca"
    assert parsed["positions"] == 1
    fetch_mock.assert_called_once()


def test_positions_drift_command_json_reports_symbol_drift(tmp_path):
    snapshot_path = tmp_path / "broker_positions_latest.json"
    snapshot_payload = {
        "source": "alpaca",
        "mode": "alpaca-paper",
        "fetched_at": "2026-02-07T00:00:00+00:00",
        "positions": [
            {"symbol": "AAPL", "qty": "10", "current_price": "100", "market_value": "1000"},
            {"symbol": "TSLA", "qty": "2", "current_price": "200", "market_value": "400"},
        ],
    }
    snapshot_path.write_text(json.dumps(snapshot_payload))
    shadow_payload = {
        "updated_at": "2026-02-07T00:00:00+00:00",
        "open_positions": {
            "AAPL": {"symbol": "AAPL", "net_quantity": 10.0, "last_mark_price": 100.0, "market_value_usd": 1000.0},
            "TSLA": {"symbol": "TSLA", "net_quantity": 1.0, "last_mark_price": 200.0, "market_value_usd": 200.0},
        },
    }

    with patch("cli.commands.execution.load_open_positions", return_value=shadow_payload), patch(
        "cli.commands.execution._persist_positions_drift", return_value=Path("positions_drift.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "positions-drift",
                "--broker",
                "alpaca",
                "--mode",
                "alpaca-paper",
                "--broker-positions-snapshot-path",
                str(snapshot_path),
                "--no-refresh-snapshot",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["symbols_compared"] == 2
    assert parsed["drift_count"] == 1
    assert parsed["drift_symbols"] == ["TSLA"]
    assert parsed["positions_drift_path"].endswith("positions_drift.json")


def test_positions_drift_command_fail_on_drift_returns_exit_2(tmp_path):
    snapshot_path = tmp_path / "broker_positions_latest.json"
    snapshot_payload = {
        "source": "alpaca",
        "mode": "alpaca-paper",
        "fetched_at": "2026-02-07T00:00:00+00:00",
        "positions": [{"symbol": "AAPL", "qty": "10", "current_price": "100", "market_value": "1000"}],
    }
    snapshot_path.write_text(json.dumps(snapshot_payload))
    shadow_payload = {
        "updated_at": "2026-02-07T00:00:00+00:00",
        "open_positions": {
            "AAPL": {"symbol": "AAPL", "net_quantity": 9.0, "last_mark_price": 100.0, "market_value_usd": 900.0},
        },
    }

    with patch("cli.commands.execution.load_open_positions", return_value=shadow_payload), patch(
        "cli.commands.execution._persist_positions_drift", return_value=Path("positions_drift.json")
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "positions-drift",
                "--broker-positions-snapshot-path",
                str(snapshot_path),
                "--no-refresh-snapshot",
                "--fail-on-drift",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 2
    parsed = _extract_json(result.stdout)
    assert parsed["drift_count"] == 1


def test_reconcile_execution_command_json_runs(tmp_path):
    broker_snapshot = tmp_path / "broker_orders_latest.json"
    broker_snapshot.write_text(json.dumps({"orders": []}))

    reconcile_result = {
        "reconciled_at": "2026-02-07T04:22:39+00:00",
        "execution_mode": "live",
        "outbox_path": "eval_results/live_execution/outbox.json",
        "positions_path": "eval_results/paper_execution/positions.json",
        "fills_path": "eval_results/live_execution/fills.json",
        "outbox_orders": 2,
        "broker_orders_seen": 2,
        "matched_orders": 2,
        "unmatched_orders": 0,
        "status_updates": 1,
        "fills_applied": 1,
        "filled_notional_usd": 1000.0,
        "status_counts": {"FILLED": 1, "SUBMITTED": 1},
        "positions_touched": ["AAPL"],
        "status_updated_order_intent_ids": ["intent-1"],
        "filled_order_intent_ids": ["intent-1"],
        "fills": [
            {
                "order_intent_id": "intent-1",
                "symbol": "AAPL",
                "side": "BUY",
                "filled_quantity": 10.0,
                "filled_price": 100.0,
                "filled_notional_usd": 1000.0,
                "lane": "CORE",
                "research_playbook": "HYBRID_COMPOUNDER",
            }
        ],
    }

    with patch("cli.commands.execution.reconcile_live_execution", return_value=reconcile_result) as reconcile_mock, patch(
        "cli.commands.execution._persist_execution_reconciliation",
        return_value=Path("reconcile.json"),
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "reconcile-execution",
                "--broker-snapshot-path",
                str(broker_snapshot),
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["matched_orders"] == 2
    assert parsed["fills_applied"] == 1
    assert parsed["reconciliation_path"].endswith("reconcile.json")
    reconcile_mock.assert_called_once()


def test_execution_sync_command_json_runs_once():
    report = {
        "reconciled_at": "2026-02-07T12:00:00+00:00",
        "date": "2026-02-07",
        "snapshot_orders": 4,
        "matched_orders": 4,
        "status_updates": 2,
        "fills_applied": 1,
        "position_refresh": {"refreshed_count": 3, "unavailable_count": 0},
        "reconciliation_path": "eval_results/live_execution/reconciliation/2026-02-07/reconcile.json",
    }
    with patch("cli.commands.execution._run_execution_sync_cycle", return_value=report) as cycle_mock:
        result = runner.invoke(
            app,
            [
                "execution-sync",
                "--once",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["snapshot_orders"] == 4
    assert parsed["fills_applied"] == 1
    assert parsed["position_refresh"]["refreshed_count"] == 3
    cycle_mock.assert_called_once()


def test_execution_sync_command_loop_respects_max_loops():
    report = {
        "reconciled_at": "2026-02-07T12:00:00+00:00",
        "date": "2026-02-07",
        "snapshot_orders": 0,
        "matched_orders": 0,
        "status_updates": 0,
        "fills_applied": 0,
        "position_refresh": {"refreshed_count": 0, "unavailable_count": 0},
        "reconciliation_path": "reconcile.json",
    }
    with patch("cli.commands.execution._run_execution_sync_cycle", return_value=report) as cycle_mock, patch(
        "cli.commands.execution.time.sleep"
    ) as sleep_mock:
        result = runner.invoke(
            app,
            [
                "execution-sync",
                "--loop",
                "--interval-sec",
                "5",
                "--max-loops",
                "2",
                "--format",
                "table",
            ],
        )

    assert result.exit_code == 0
    assert cycle_mock.call_count == 2
    sleep_mock.assert_called_once_with(5)


def test_execution_sync_apply_exits_blocks_when_readiness_fails():
    report = {
        "reconciled_at": "2026-02-07T12:00:00+00:00",
        "date": "2026-02-07",
        "snapshot_orders": 0,
        "matched_orders": 0,
        "status_updates": 0,
        "fills_applied": 0,
        "position_refresh": {"refreshed_count": 0, "unavailable_count": 0},
        "reconciliation_path": "reconcile.json",
    }
    readiness = {
        "overall_ready": False,
        "blockers": ["stale pending orders"],
        "checks": {},
    }

    with patch("cli.commands.execution._run_execution_sync_cycle", return_value=report), patch(
        "cli.commands.execution.evaluate_execution_readiness",
        return_value=readiness,
    ), patch(
        "cli.commands.execution._persist_execution_readiness",
        return_value=Path("ready.json"),
    ), patch(
        "cli.commands.execution._run_manage_exits_once"
    ) as manage_mock, patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "execution-sync",
                "--once",
                "--apply-exits",
                "--require-ready",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["execution_readiness"]["overall_ready"] is False
    assert parsed["exit_management"]["blocked"] is True
    assert parsed["exit_management"]["reason"] == "EXECUTION_READINESS_FAILED"
    manage_mock.assert_not_called()


def test_execution_sync_optional_open_orders_and_shadow_sync_are_wired():
    report = {
        "reconciled_at": "2026-02-07T12:00:00+00:00",
        "date": "2026-02-07",
        "snapshot_orders": 4,
        "matched_orders": 4,
        "status_updates": 1,
        "fills_applied": 0,
        "position_refresh": {"refreshed_count": 0, "unavailable_count": 0},
        "reconciliation_path": "reconcile.json",
    }
    management_report = {
        "date": "2026-02-07",
        "stale_candidates_count": 2,
        "canceled_count": 2,
        "replaced_count": 0,
        "errors_count": 0,
    }
    sync_report = {
        "date": "2026-02-07",
        "added_count": 1,
        "updated_count": 2,
        "removed_count": 0,
    }
    readiness = {"overall_ready": True, "blockers": [], "checks": {}}

    with patch("cli.commands.execution._run_execution_sync_cycle", return_value=report), patch(
        "cli.commands.execution._run_manage_open_orders_once",
        return_value=management_report,
    ) as manage_mock, patch(
        "cli.commands.execution._persist_open_orders_management",
        return_value=Path("open-orders.json"),
    ), patch(
        "cli.commands.execution._run_sync_positions_from_broker_once",
        return_value=sync_report,
    ) as sync_mock, patch(
        "cli.commands.execution._persist_positions_sync",
        return_value=Path("positions-sync.json"),
    ), patch(
        "cli.commands.execution.evaluate_execution_readiness",
        return_value=readiness,
    ), patch(
        "cli.commands.execution._persist_execution_readiness",
        return_value=Path("ready.json"),
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "execution-sync",
                "--once",
                "--manage-open-orders",
                "--manage-open-orders-dry-run",
                "--sync-shadow-positions",
                "--sync-shadow-positions-dry-run",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["open_orders_management"]["stale_candidates_count"] == 2
    assert parsed["open_orders_management"]["open_orders_management_path"].endswith("open-orders.json")
    assert parsed["positions_sync"]["updated_count"] == 2
    assert parsed["positions_sync"]["positions_sync_path"].endswith("positions-sync.json")
    assert parsed["execution_readiness"]["overall_ready"] is True
    manage_mock.assert_called_once()
    sync_mock.assert_called_once()


def test_execution_sync_manage_open_orders_apply_refreshes_snapshot():
    report = {
        "reconciled_at": "2026-02-07T12:00:00+00:00",
        "date": "2026-02-07",
        "snapshot_orders": 4,
        "matched_orders": 4,
        "status_updates": 1,
        "fills_applied": 0,
        "position_refresh": {"refreshed_count": 0, "unavailable_count": 0},
        "reconciliation_path": "reconcile.json",
    }
    readiness = {"overall_ready": True, "blockers": [], "checks": {}}

    with patch("cli.commands.execution._run_execution_sync_cycle", return_value=report), patch(
        "cli.commands.execution._run_manage_open_orders_once",
        return_value={
            "date": "2026-02-07",
            "stale_candidates_count": 1,
            "canceled_count": 1,
            "replaced_count": 0,
            "errors_count": 0,
        },
    ), patch(
        "cli.commands.execution._persist_open_orders_management",
        return_value=Path("open-orders.json"),
    ), patch(
        "cli.commands.execution.fetch_alpaca_orders_snapshot",
    ) as refresh_mock, patch(
        "cli.commands.execution.evaluate_execution_readiness",
        return_value=readiness,
    ), patch(
        "cli.commands.execution._persist_execution_readiness",
        return_value=Path("ready.json"),
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "execution-sync",
                "--once",
                "--manage-open-orders",
                "--manage-open-orders-apply",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["open_orders_management"]["canceled_count"] == 1
    refresh_mock.assert_called_once()


def test_execution_sync_auto_remediates_readiness_blockers():
    report = {
        "reconciled_at": "2026-02-07T12:00:00+00:00",
        "date": "2026-02-07",
        "snapshot_orders": 4,
        "matched_orders": 4,
        "status_updates": 1,
        "fills_applied": 0,
        "position_refresh": {"refreshed_count": 0, "unavailable_count": 0},
        "reconciliation_path": "reconcile.json",
    }
    readiness_blocked = {
        "overall_ready": False,
        "blockers": [
            "Stale pending orders detected (1 >= 1).",
            "Position drift exceeds threshold (5000.00 > 2500.00).",
        ],
        "checks": {
            "stale_pending_orders": {"pass": False},
            "open_order_match": {"pass": True},
            "position_drift": {"pass": False},
        },
    }
    readiness_ready = {
        "overall_ready": True,
        "blockers": [],
        "checks": {
            "stale_pending_orders": {"pass": True},
            "open_order_match": {"pass": True},
            "position_drift": {"pass": True},
        },
    }
    with patch("cli.commands.execution._run_execution_sync_cycle", return_value=report), patch(
        "cli.commands.execution.evaluate_execution_readiness",
        side_effect=[readiness_blocked, readiness_ready],
    ), patch(
        "cli.commands.execution._persist_execution_readiness",
        side_effect=[Path("ready-before.json"), Path("ready-after.json")],
    ), patch(
        "cli.commands.execution._run_manage_open_orders_once",
        return_value={
            "date": "2026-02-07",
            "stale_candidates_count": 1,
            "canceled_count": 1,
            "replaced_count": 0,
            "errors_count": 0,
        },
    ) as manage_mock, patch(
        "cli.commands.execution._persist_open_orders_management",
        return_value=Path("open-orders.json"),
    ), patch(
        "cli.commands.execution._run_sync_positions_from_broker_once",
        return_value={
            "date": "2026-02-07",
            "added_count": 0,
            "updated_count": 2,
            "removed_count": 1,
        },
    ) as sync_mock, patch(
        "cli.commands.execution._persist_positions_sync",
        return_value=Path("positions-sync.json"),
    ), patch(
        "cli.commands.execution.fetch_alpaca_orders_snapshot",
        return_value={"orders": []},
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "execution-sync",
                "--once",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["execution_readiness"]["overall_ready"] is True
    assert parsed["execution_readiness"]["execution_readiness_path"].endswith("ready-after.json")
    assert parsed["readiness_remediation"]["attempted"] is True
    assert "MANAGE_OPEN_ORDERS_APPLY" in parsed["readiness_remediation"]["actions"]
    assert "SYNC_SHADOW_POSITIONS_APPLY" in parsed["readiness_remediation"]["actions"]
    manage_mock.assert_called_once()
    sync_mock.assert_called_once()


def test_workflow_run_skips_when_orchestration_does_not_run():
    scheduler_result = {
        "ran": False,
        "date": "2026-02-07",
        "reason": "outside policy window",
        "trigger": None,
    }
    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "cli.commands.dealflow.DealFlowScheduler"
    ) as scheduler_cls, patch(
        "cli.commands.dealflow._persist_workflow_run",
        return_value=Path("workflow-skip.json"),
    ):
        scheduler = Mock()
        scheduler.run_once.return_value = scheduler_result
        scheduler_cls.return_value = scheduler
        result = runner.invoke(app, ["workflow-run", "--mode", "auto", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["status"] == "SKIPPED_ORCHESTRATION"
    assert parsed["workflow_run_path"].endswith("workflow-skip.json")


def test_workflow_run_success_chains_all_steps():
    scheduler_result = {
        "ran": True,
        "date": "2026-02-07",
        "reason": "forced",
        "trigger": "manual",
        "run_id": "2026-02-07-120000-manual",
        "signal_count": 120,
    }
    side_effects = [
        {
            "return_code": 0,
            "payload": {
                "processed": 8,
                "success_count": 8,
                "failure_count": 0,
                "skipped_count": 0,
                "summary_path": "eval_results/deal_flow/2026-02-07/batch_analyze_summary.json",
            },
            "stdout": "{}",
            "stderr": "",
        },
        {
            "return_code": 0,
            "payload": {
                "plan_id": "plan-1",
                "orders": [{"symbol": "AAPL"}],
                "plan_path": "eval_results/paper_execution/latest_plan.json",
            },
            "stdout": "{}",
            "stderr": "",
        },
        {
            "return_code": 0,
            "payload": {
                "submitted_orders": 4,
                "executed_orders": 0,
                "skipped_duplicate_orders": 0,
                "risk_check": {"status": "PASS"},
            },
            "stdout": "{}",
            "stderr": "",
        },
        {
            "return_code": 0,
            "payload": {
                "snapshot_orders": 4,
                "matched_orders": 4,
                "fills_applied": 0,
                "status_updates": 0,
                "execution_readiness": {"overall_ready": True},
            },
            "stdout": "{}",
            "stderr": "",
        },
    ]
    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "tradingagents.dealflow.sources.x_feed_manual.get_readiness",
        return_value={"ready": True, "missing_passes": [], "completed_passes": list(range(1, 16)), "merged_symbol_count": 10},
    ), patch(
        "cli.commands.dealflow.DealFlowScheduler"
    ) as scheduler_cls, patch(
        "cli.commands.dealflow._run_cli_subcommand_json",
        side_effect=side_effects,
    ) as subcmd_mock, patch(
        "cli.commands.dealflow._persist_workflow_run",
        return_value=Path("workflow-success.json"),
    ), patch(
        "cli.commands.dealflow.run_learning_cycle",
        return_value={"learning_status": "OK", "output_path": "eval_results/deal_flow/2026-02-07/learning_status.json"},
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        scheduler = Mock()
        scheduler.run_once.return_value = scheduler_result
        scheduler_cls.return_value = scheduler
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "workflow-run",
                "--mode",
                "manual",
                "--date",
                "2026-02-07",
                "--execution-mode",
                "alpaca-paper",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["status"] == "SUCCESS"
    assert parsed["steps"]["analyze_batch"]["success_count"] == 8
    assert parsed["steps"]["portfolio_plan"]["plan_id"] == "plan-1"
    assert parsed["steps"]["execute"]["submitted_orders"] == 4
    assert parsed["steps"]["execution_sync"]["matched_orders"] == 4
    assert parsed["workflow_run_path"].endswith("workflow-success.json")
    assert subcmd_mock.call_count == 4


def test_workflow_run_partial_analyze_failure_continues_with_warning_status():
    scheduler_result = {
        "ran": True,
        "date": "2026-02-07",
        "reason": "forced",
        "trigger": "manual",
        "run_id": "2026-02-07-120000-manual",
        "signal_count": 120,
    }
    side_effects = [
        {
            "return_code": 1,
            "payload": {
                "processed": 12,
                "success_count": 11,
                "failure_count": 1,
                "skipped_count": 0,
                "summary_path": "eval_results/deal_flow/2026-02-07/batch_analyze_summary.json",
            },
            "stdout": "{}",
            "stderr": "one item failed",
        },
        {
            "return_code": 0,
            "payload": {
                "plan_id": "plan-1",
                "orders": [{"symbol": "AAPL"}],
                "plan_path": "eval_results/paper_execution/latest_plan.json",
            },
            "stdout": "{}",
            "stderr": "",
        },
        {
            "return_code": 0,
            "payload": {
                "submitted_orders": 4,
                "executed_orders": 0,
                "skipped_duplicate_orders": 0,
                "risk_check": {"status": "PASS"},
            },
            "stdout": "{}",
            "stderr": "",
        },
        {
            "return_code": 0,
            "payload": {
                "snapshot_orders": 4,
                "matched_orders": 4,
                "fills_applied": 0,
                "status_updates": 0,
                "execution_readiness": {"overall_ready": True},
            },
            "stdout": "{}",
            "stderr": "",
        },
    ]
    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "tradingagents.dealflow.sources.x_feed_manual.get_readiness",
        return_value={"ready": True, "missing_passes": [], "completed_passes": list(range(1, 16)), "merged_symbol_count": 10},
    ), patch(
        "cli.commands.dealflow.DealFlowScheduler"
    ) as scheduler_cls, patch(
        "cli.commands.dealflow._run_cli_subcommand_json",
        side_effect=side_effects,
    ) as subcmd_mock, patch(
        "cli.commands.dealflow._persist_workflow_run",
        return_value=Path("workflow-partial.json"),
    ), patch(
        "cli.commands.dealflow.run_learning_cycle",
        return_value={"learning_status": "OK", "output_path": "eval_results/deal_flow/2026-02-07/learning_status.json"},
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        scheduler = Mock()
        scheduler.run_once.return_value = scheduler_result
        scheduler_cls.return_value = scheduler
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "workflow-run",
                "--mode",
                "manual",
                "--date",
                "2026-02-07",
                "--execution-mode",
                "alpaca-paper",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["status"] == "COMPLETED_WITH_ANALYZE_FAILURES"
    assert parsed["steps"]["analyze_batch"]["continue_reason"] == "partial_success"
    assert parsed["steps"]["analyze_batch"]["failure_count"] == 1
    assert parsed["workflow_run_path"].endswith("workflow-partial.json")
    assert subcmd_mock.call_count == 4


def test_workflow_run_uses_summary_fallback_when_analyze_payload_missing():
    scheduler_result = {
        "ran": True,
        "date": "2026-02-07",
        "reason": "forced",
        "trigger": "manual",
        "run_id": "2026-02-07-120000-manual",
        "signal_count": 120,
    }
    side_effects = [
        {
            "return_code": 1,
            "payload": {},
            "stdout": "Batch analyze complete",
            "stderr": "",
        },
        {
            "return_code": 0,
            "payload": {
                "plan_id": "plan-1",
                "orders": [{"symbol": "AAPL"}],
                "plan_path": "eval_results/paper_execution/latest_plan.json",
            },
            "stdout": "{}",
            "stderr": "",
        },
        {
            "return_code": 0,
            "payload": {
                "submitted_orders": 4,
                "executed_orders": 0,
                "skipped_duplicate_orders": 0,
                "risk_check": {"status": "PASS"},
            },
            "stdout": "{}",
            "stderr": "",
        },
        {
            "return_code": 0,
            "payload": {
                "snapshot_orders": 4,
                "matched_orders": 4,
                "fills_applied": 0,
                "status_updates": 0,
                "execution_readiness": {"overall_ready": True},
            },
            "stdout": "{}",
            "stderr": "",
        },
    ]
    fallback_summary = {
        "processed": 12,
        "success_count": 11,
        "failure_count": 1,
        "skipped_count": 0,
    }
    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "tradingagents.dealflow.sources.x_feed_manual.get_readiness",
        return_value={"ready": True, "missing_passes": [], "completed_passes": list(range(1, 16)), "merged_symbol_count": 10},
    ), patch(
        "cli.commands.dealflow.DealFlowScheduler"
    ) as scheduler_cls, patch(
        "cli.commands.dealflow._run_cli_subcommand_json",
        side_effect=side_effects,
    ), patch(
        "cli.commands.dealflow._load_batch_summary",
        return_value=(fallback_summary, Path("eval_results/deal_flow/2026-02-07/batch_analyze_latest.json")),
    ), patch(
        "cli.commands.dealflow._persist_workflow_run",
        return_value=Path("workflow-fallback.json"),
    ), patch(
        "cli.commands.dealflow.run_learning_cycle",
        return_value={"learning_status": "OK", "output_path": "eval_results/deal_flow/2026-02-07/learning_status.json"},
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        scheduler = Mock()
        scheduler.run_once.return_value = scheduler_result
        scheduler_cls.return_value = scheduler
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "workflow-run",
                "--mode",
                "manual",
                "--date",
                "2026-02-07",
                "--execution-mode",
                "alpaca-paper",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["status"] == "COMPLETED_WITH_ANALYZE_FAILURES"
    assert parsed["steps"]["analyze_batch"]["used_fallback_summary"] is True
    assert parsed["steps"]["analyze_batch"]["summary_path"].endswith("batch_analyze_latest.json")
    assert parsed["workflow_run_path"].endswith("workflow-fallback.json")


def test_workflow_run_fails_when_analyze_has_no_success_and_nonzero_exit():
    scheduler_result = {
        "ran": True,
        "date": "2026-02-07",
        "reason": "forced",
        "trigger": "manual",
        "run_id": "2026-02-07-120000-manual",
        "signal_count": 120,
    }
    side_effects = [
        {
            "return_code": 1,
            "payload": {
                "processed": 12,
                "success_count": 0,
                "failure_count": 12,
                "skipped_count": 0,
                "summary_path": "eval_results/deal_flow/2026-02-07/batch_analyze_summary.json",
            },
            "stdout": "{}",
            "stderr": "all failed",
        }
    ]
    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "tradingagents.dealflow.sources.x_feed_manual.get_readiness",
        return_value={"ready": True, "missing_passes": [], "completed_passes": list(range(1, 16)), "merged_symbol_count": 10},
    ), patch(
        "cli.commands.dealflow.DealFlowScheduler"
    ) as scheduler_cls, patch(
        "cli.commands.dealflow._run_cli_subcommand_json",
        side_effect=side_effects,
    ) as subcmd_mock, patch(
        "cli.commands.dealflow._persist_workflow_run",
        return_value=Path("workflow-analyze-failed.json"),
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        scheduler = Mock()
        scheduler.run_once.return_value = scheduler_result
        scheduler_cls.return_value = scheduler
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "workflow-run",
                "--mode",
                "manual",
                "--date",
                "2026-02-07",
                "--execution-mode",
                "alpaca-paper",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 1
    parsed = _extract_json(result.stdout)
    assert parsed["status"] == "FAILED_ANALYZE_BATCH"
    assert parsed["workflow_run_path"].endswith("workflow-analyze-failed.json")
    assert subcmd_mock.call_count == 1


def test_workflow_run_blocks_when_manual_x_feed_incomplete():
    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "tradingagents.dealflow.sources.x_feed_manual.get_readiness",
        return_value={
            "ready": False,
            "missing_passes": [3, 4, 15],
            "completed_passes": [1, 2],
            "merged_symbol_count": 12,
        },
    ), patch(
        "cli.commands.dealflow._persist_workflow_run",
        return_value=Path("workflow-manual-x-blocked.json"),
    ), patch(
        "cli.commands.dealflow.DealFlowScheduler"
    ) as scheduler_cls:
        result = runner.invoke(
            app,
            [
                "workflow-run",
                "--mode",
                "manual",
                "--date",
                "2026-02-07",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 1
    parsed = _extract_json(result.stdout)
    assert parsed["status"] == "BLOCKED_MANUAL_X_FEED"
    assert parsed["steps"]["manual_x_feed"]["missing_passes"] == [3, 4, 15]
    assert parsed["workflow_run_path"].endswith("workflow-manual-x-blocked.json")
    scheduler_cls.assert_not_called()


def test_workflow_run_records_learning_step_when_learning_succeeds():
    scheduler_result = {
        "ran": True,
        "date": "2026-02-07",
        "reason": "forced",
        "trigger": "manual",
        "run_id": "2026-02-07-120000-manual",
        "signal_count": 120,
    }
    side_effects = [
        {
            "return_code": 0,
            "payload": {
                "processed": 8,
                "success_count": 8,
                "failure_count": 0,
                "skipped_count": 0,
                "summary_path": "eval_results/deal_flow/2026-02-07/batch_analyze_summary.json",
            },
            "stdout": "{}",
            "stderr": "",
        },
        {
            "return_code": 0,
            "payload": {
                "plan_id": "plan-1",
                "orders": [{"symbol": "AAPL"}],
                "plan_path": "eval_results/paper_execution/latest_plan.json",
            },
            "stdout": "{}",
            "stderr": "",
        },
    ]
    learning_result = {
        "learning_status": "OK",
        "hindsight_status": "OK",
        "performance_status": "OK",
        "weight_update_status": "UPDATED",
        "output_path": "eval_results/deal_flow/2026-02-07/learning_status.json",
    }
    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "tradingagents.dealflow.sources.x_feed_manual.get_readiness",
        return_value={"ready": True, "missing_passes": [], "completed_passes": list(range(1, 16)), "merged_symbol_count": 10},
    ), patch(
        "cli.commands.dealflow.DealFlowScheduler"
    ) as scheduler_cls, patch(
        "cli.commands.dealflow._run_cli_subcommand_json",
        side_effect=side_effects,
    ), patch(
        "cli.commands.dealflow.run_learning_cycle",
        return_value=learning_result,
    ), patch(
        "cli.commands.dealflow._persist_workflow_run",
        return_value=Path("workflow-learning-ok.json"),
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        scheduler = Mock()
        scheduler.run_once.return_value = scheduler_result
        scheduler_cls.return_value = scheduler
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "workflow-run",
                "--mode",
                "manual",
                "--date",
                "2026-02-07",
                "--skip-execution",
                "--skip-sync",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["status"] == "SUCCESS"
    assert parsed["steps"]["learning"]["learning_status"] == "OK"
    assert parsed["workflow_run_path"].endswith("workflow-learning-ok.json")


def test_workflow_run_degraded_learning_does_not_fail_workflow():
    scheduler_result = {
        "ran": True,
        "date": "2026-02-07",
        "reason": "forced",
        "trigger": "manual",
        "run_id": "2026-02-07-120000-manual",
        "signal_count": 120,
    }
    side_effects = [
        {
            "return_code": 0,
            "payload": {
                "processed": 8,
                "success_count": 8,
                "failure_count": 0,
                "skipped_count": 0,
                "summary_path": "eval_results/deal_flow/2026-02-07/batch_analyze_summary.json",
            },
            "stdout": "{}",
            "stderr": "",
        },
        {
            "return_code": 0,
            "payload": {
                "plan_id": "plan-1",
                "orders": [{"symbol": "AAPL"}],
                "plan_path": "eval_results/paper_execution/latest_plan.json",
            },
            "stdout": "{}",
            "stderr": "",
        },
    ]
    learning_result = {
        "learning_status": "DEGRADED",
        "hindsight_status": "ERROR",
        "performance_status": "SKIPPED",
        "weight_update_status": "SKIPPED",
        "warnings": ["no hindsight window"],
        "output_path": "eval_results/deal_flow/2026-02-07/learning_status.json",
    }
    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "tradingagents.dealflow.sources.x_feed_manual.get_readiness",
        return_value={"ready": True, "missing_passes": [], "completed_passes": list(range(1, 16)), "merged_symbol_count": 10},
    ), patch(
        "cli.commands.dealflow.DealFlowScheduler"
    ) as scheduler_cls, patch(
        "cli.commands.dealflow._run_cli_subcommand_json",
        side_effect=side_effects,
    ), patch(
        "cli.commands.dealflow.run_learning_cycle",
        return_value=learning_result,
    ), patch(
        "cli.commands.dealflow._persist_workflow_run",
        return_value=Path("workflow-learning-degraded.json"),
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        scheduler = Mock()
        scheduler.run_once.return_value = scheduler_result
        scheduler_cls.return_value = scheduler
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "workflow-run",
                "--mode",
                "manual",
                "--date",
                "2026-02-07",
                "--skip-execution",
                "--skip-sync",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["status"] == "COMPLETED_WITH_LEARNING_DEGRADED"
    assert parsed["steps"]["learning"]["learning_status"] == "DEGRADED"
    assert parsed["workflow_run_path"].endswith("workflow-learning-degraded.json")


def test_workflow_run_interactive_requires_manual_mode():
    result = runner.invoke(
        app,
        [
            "workflow-run",
            "--interactive",
            "--mode",
            "auto",
        ],
    )

    assert result.exit_code == 1
    assert "interactive mode requires --mode manual" in result.stdout.lower()


def test_interactive_complete_x_feed_reads_until_ready(monkeypatch):
    prompts = [(1, "Technology", "PROMPT 1"), (2, "Healthcare", "PROMPT 2")]
    readiness_states = [
        {
            "ready": False,
            "missing_passes": [1, 2],
            "completed_passes": [],
            "required_passes": list(range(1, 16)),
            "merged_symbol_count": 0,
            "merged_path": "merged.json",
        },
        {
            "ready": False,
            "missing_passes": [2],
            "completed_passes": [1],
            "required_passes": list(range(1, 16)),
            "merged_symbol_count": 4,
            "merged_path": "merged.json",
        },
        {
            "ready": True,
            "missing_passes": [],
            "completed_passes": [1, 2],
            "required_passes": list(range(1, 16)),
            "merged_symbol_count": 6,
            "merged_path": "merged.json",
        },
    ]
    ingest_calls = []

    monkeypatch.setattr(
        dealflow_cmd,
        "_read_multiline_until_end",
        lambda prompt_label="": '{"trending":[]}',
    )

    with patch(
        "tradingagents.dealflow.sources.x_feed_manual.generate_prompts",
        return_value=prompts,
    ), patch(
        "tradingagents.dealflow.sources.x_feed_manual.get_readiness",
        side_effect=readiness_states,
    ), patch(
        "tradingagents.dealflow.sources.x_feed_manual.ingest_pass",
        side_effect=lambda run_date, raw, pass_num, dry_run=False: ingest_calls.append((run_date, pass_num, raw)) or {
            "raw_path": f"pass_{pass_num:02d}.json",
            "tickers_parsed": 3,
            "tickers_merged": 6,
            "akg_written": 3,
            "entries": [],
            "themes": [],
            "options_flow": [],
        },
    ):
        result = dealflow_cmd._interactive_complete_x_feed("2026-02-07")

    assert [call[1] for call in ingest_calls] == [1, 2]
    assert result["ready"] is True
    assert result["merged_symbol_count"] == 6


def test_workflow_run_interactive_manual_runs_staged_pipeline():
    discover_summary = {
        "universe_size": 150,
        "breakout_count": 2,
        "technical_ignition_count": 3,
        "iv_force_queue_count": 0,
        "insider_summary": {"new_txns": 4, "buy_clusters": 1, "sell_clusters": 0},
        "manual_symbols": ["NVDA"],
        "fvg_recall_symbols": ["NVDA"],
        "fma_recall_symbols": ["PLTR"],
        "earnings_options_count": 1,
        "earnings_options_symbols": ["BABA"],
        "universe_filter": {"universe_size": 150, "overall_ready": True},
        "discovery_delta": {"coverage_summary": {"signal_count": 5, "record_count": 5}},
    }
    shortlist = {
        "run_id": "2026-02-07-120000-manual",
        "date": "2026-02-07",
        "trigger": "manual",
        "top_k": 30,
        "candidates": [{"symbol": "OXY"}],
        "connector_health_summary": {"overall_status": "OK", "ok_count": 5, "error_count": 0},
    }
    research_queue = {
        "run_id": "2026-02-07-120000-manual",
        "date": "2026-02-07",
        "items": [{"queue_id": "2026-02-07-120000-manual:OXY", "symbol": "OXY", "selected_for_deep": True}],
        "selected_queue_ids": ["2026-02-07-120000-manual:OXY"],
    }
    analyze_payload = {
        "processed": 1,
        "success_count": 1,
        "failure_count": 0,
        "skipped_count": 0,
        "summary_path": "eval_results/deal_flow/2026-02-07/batch_analyze_summary.json",
    }
    plan_payload = {
        "plan_id": "plan-1",
        "orders": [{"symbol": "QQQ"}],
        "plan_path": "eval_results/paper_execution/latest_plan.json",
    }

    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "cli.commands.dealflow._interactive_complete_x_feed",
        return_value={"ready": True, "merged_symbol_count": 59, "completed_passes": list(range(1, 16))},
    ) as x_feed_mock, patch(
        "cli.commands.dealflow._interactive_complete_macro",
        return_value={"regime": "late_cycle", "sector_count": 11},
    ) as macro_mock, patch(
        "cli.commands.dealflow._interactive_complete_earnings_options",
        return_value={"setup_count": 1},
    ) as earnings_mock, patch(
        "cli.commands.dealflow.DealFlowPipeline"
    ) as pipeline_cls, patch(
        "cli.commands.dealflow._run_cli_subcommand_json",
        side_effect=[
            {"return_code": 0, "payload": analyze_payload, "stdout": "{}", "stderr": ""},
            {"return_code": 0, "payload": plan_payload, "stdout": "{}", "stderr": ""},
        ],
    ) as subcmd_mock, patch(
        "cli.commands.dealflow.run_learning_cycle",
        return_value={"learning_status": "DEGRADED", "output_path": "learning.json"},
    ), patch(
        "cli.commands.dealflow._persist_workflow_run",
        return_value=Path("workflow-interactive.json"),
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        pipeline = Mock()
        pipeline.discover.return_value = discover_summary
        pipeline.collect.return_value = (shortlist, research_queue, [{"symbol": "OXY"}], {"triggered": False, "reasons": [], "metrics": {}})
        pipeline_cls.return_value = pipeline
        audit_cls.return_value = Mock()

        result = runner.invoke(
            app,
            [
                "workflow-run",
                "--interactive",
                "--mode",
                "manual",
                "--date",
                "2026-02-07",
                "--skip-execution",
                "--skip-sync",
            ],
        )

    assert result.exit_code == 0
    assert "Following scouts are now going to run" in result.stdout
    assert "Following collectors are now going to run" in result.stdout
    assert "Manual X-feed complete" in result.stdout
    assert "Macro cache saved" in result.stdout
    assert "Earnings/options scout saved" in result.stdout
    assert "Discovery complete" in result.stdout
    assert "Collect complete" in result.stdout
    assert "Deep analysis complete" in result.stdout
    assert "Portfolio plan complete" in result.stdout
    assert "Learning status" in result.stdout
    x_feed_mock.assert_called_once_with("2026-02-07")
    macro_mock.assert_called_once_with("2026-02-07")
    earnings_mock.assert_called_once_with("2026-02-07")
    pipeline.discover.assert_called_once()
    pipeline.collect.assert_called_once()
    assert subcmd_mock.call_count == 2


def test_scenario_retrieve_command_json_returns_internal_only_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "eval_results" / "deal_flow" / "2026-03-15"
    base.mkdir(parents=True, exist_ok=True)
    (base / "event_cards.json").write_text(
        json.dumps(
            [
                {
                    "event_card_id": "evt_iran",
                    "date": "2026-03-15",
                    "title": "Iran escalation drives oil cluster",
                    "summary": "Oil up, airlines down",
                    "event_type": "geopolitical_supply_shock",
                    "source_bundle": ["x_feed", "macro"],
                    "source_records": [],
                    "direct_entities": [{"entity_type": "ticker", "entity_id": "XLE", "label": "XLE"}],
                    "second_order_entities": [{"entity_type": "ticker", "entity_id": "UAL", "label": "UAL"}],
                    "channels": ["oil", "risk_off"],
                    "expected_direction": {"XLE": "up", "UAL": "down"},
                    "confidence": 0.8,
                    "urgency": "immediate",
                    "time_horizon": "1d_to_5d",
                    "portfolio_relevance": "medium",
                    "matched_holdings": [],
                    "matched_universe_symbols": ["XLE", "UAL", "SPY"],
                    "coverage_dimensions": ["social", "macro"],
                    "missing_dimensions": ["portfolio"],
                    "followup_questions": [],
                }
            ]
        )
    )
    (base / "coverage_precheck.json").write_text(
        json.dumps(
            {
                "date": "2026-03-15",
                "rows": [
                    {
                        "event_card_id": "evt_iran",
                        "coverage_status": "PARTIAL",
                        "coverage_score": 0.62,
                        "missing_dimensions": ["portfolio"],
                        "ready_for_retrieval": True,
                    }
                ],
            }
        )
    )
    (base / "universe_filter.json").write_text(json.dumps({"symbols": ["XLE", "UAL", "SPY"]}))

    result = runner.invoke(
        app,
        [
            "scenario-retrieve",
            "--date",
            "2026-03-15",
            "--question",
            "Trump announced war on Iran. Should we hedge with SPY?",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _extract_json(result.output)
    assert payload["coverage_status"] == "PARTIAL"
    assert "evt_iran" in payload["matched_event_cards"]
    assert payload["wait_for_user"] is True


def test_workflow_loop_runs_requested_cycles():
    side_effects = [
        {
            "return_code": 0,
            "payload": {
                "status": "SUCCESS",
                "date": "2026-02-07",
                "steps": {"analyze_batch": {"processed": 10, "success_count": 10, "failure_count": 0}},
            },
            "stdout": "{}",
            "stderr": "",
        },
        {
            "return_code": 0,
            "payload": {
                "status": "SUCCESS",
                "date": "2026-02-07",
                "steps": {"analyze_batch": {"processed": 9, "success_count": 9, "failure_count": 0}},
            },
            "stdout": "{}",
            "stderr": "",
        },
    ]
    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "cli.commands.dealflow._run_cli_subcommand_json", side_effect=side_effects
    ) as subcmd_mock, patch(
        "cli.commands.dealflow._persist_workflow_loop_run",
        return_value=Path("workflow-loop.json"),
    ), patch("cli.commands.dealflow.time.sleep") as sleep_mock:
        result = runner.invoke(
            app,
            [
                "workflow-loop",
                "--cycles",
                "2",
                "--interval-seconds",
                "5",
                "--mode",
                "manual",
                "--date",
                "2026-02-07",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["status"] == "SUCCESS"
    assert parsed["completed_cycles"] == 2
    assert parsed["failure_cycles"] == 0
    assert parsed["workflow_loop_path"].endswith("workflow-loop.json")
    assert subcmd_mock.call_count == 2
    sleep_mock.assert_called_once_with(5)


def test_workflow_loop_stops_on_failure_when_enabled():
    side_effects = [
        {
            "return_code": 1,
            "payload": {
                "status": "FAILED_ANALYZE_BATCH",
                "date": "2026-02-07",
                "steps": {"analyze_batch": {"processed": 10, "success_count": 0, "failure_count": 10}},
            },
            "stdout": "{}",
            "stderr": "failed",
        },
        {
            "return_code": 0,
            "payload": {
                "status": "SUCCESS",
                "date": "2026-02-07",
                "steps": {"analyze_batch": {"processed": 9, "success_count": 9, "failure_count": 0}},
            },
            "stdout": "{}",
            "stderr": "",
        },
    ]
    with patch("tradingagents.dealflow.system_halt.is_hands_off_active", return_value=False), patch(
        "cli.commands.dealflow._run_cli_subcommand_json", side_effect=side_effects
    ) as subcmd_mock, patch(
        "cli.commands.dealflow._persist_workflow_loop_run",
        return_value=Path("workflow-loop-failure.json"),
    ):
        result = runner.invoke(
            app,
            [
                "workflow-loop",
                "--cycles",
                "2",
                "--stop-on-failure",
                "--mode",
                "manual",
                "--date",
                "2026-02-07",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 1
    parsed = _extract_json(result.stdout)
    assert parsed["status"] == "COMPLETED_WITH_FAILURES"
    assert parsed["completed_cycles"] == 1
    assert parsed["failure_cycles"] == 1
    assert parsed["workflow_loop_path"].endswith("workflow-loop-failure.json")
    assert subcmd_mock.call_count == 1


def test_manage_exits_command_json_dry_run():
    report = {
        "date": "2026-02-07",
        "execution_mode": "alpaca-paper",
        "submitted": False,
        "signals_generated": 2,
        "orders_generated": 2,
        "orders_submitted": 0,
        "signals": [{"symbol": "AAPL"}],
        "orders": [{"symbol": "AAPL", "side": "SELL"}],
        "skipped": [],
        "rules": {},
        "exit_management_path": "exit-management.json",
    }
    with patch("cli.commands.execution._run_manage_exits_once", return_value=report) as manage_mock:
        result = runner.invoke(
            app,
            [
                "manage-exits",
                "--execution-mode",
                "alpaca-paper",
                "--dry-run",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["submitted"] is False
    assert parsed["signals_generated"] == 2
    manage_mock.assert_called_once()


def test_execution_readiness_fail_on_blocked_returns_exit_2():
    report = {
        "overall_ready": False,
        "checks": {},
        "blockers": ["missing credentials"],
        "warnings": [],
    }
    with patch("cli.commands.execution.evaluate_execution_readiness", return_value=report), patch(
        "cli.commands.execution._persist_execution_readiness",
        return_value=Path("ready.json"),
    ), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "execution-readiness",
                "--no-refresh-snapshot",
                "--fail-on-blocked",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 2
    parsed = _extract_json(result.stdout)
    assert parsed["overall_ready"] is False
    assert parsed["execution_readiness_path"].endswith("ready.json")


def test_paper_positions_command_json_reads_positions():
    payload = {
        "updated_at": "2026-02-06T00:00:00+00:00",
        "open_positions": {
            "AAPL": {
                "symbol": "AAPL",
                "net_quantity": 10.0,
                "avg_price": 100.0,
                "market_value_usd": 1000.0,
            }
        },
    }
    with patch("cli.commands.execution.load_open_positions", return_value=payload):
        result = runner.invoke(app, ["paper-positions", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert "AAPL" in parsed["open_positions"]


def test_live_positions_command_json_reads_positions():
    payload = {
        "updated_at": "2026-02-06T00:00:00+00:00",
        "open_positions": {
            "META": {
                "symbol": "META",
                "net_quantity": 3.0,
                "avg_price": 100.0,
                "market_value_usd": 300.0,
            }
        },
    }
    with patch("cli.commands.execution.load_open_positions", return_value=payload):
        result = runner.invoke(app, ["live-positions", "--format", "json"])

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert "META" in parsed["open_positions"]


def test_close_paper_command_json_emits_close_event():
    close_event = {
        "symbol": "AAPL",
        "close_date": "2026-02-06",
        "close_price": 111.0,
        "net_quantity": 10.0,
        "avg_entry_price": 100.0,
        "pnl_usd": 110.0,
        "return_pct": 11.0,
        "rating_ids": ["rid-1"],
        "updated_rating_ids": ["rid-1"],
    }
    with patch("cli.commands.execution.close_position_with_adapter", return_value=close_event), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "close-paper",
                "AAPL",
                "--close-price",
                "111",
                "--close-date",
                "2026-02-06",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["symbol"] == "AAPL"
    assert parsed["updated_rating_ids"] == ["rid-1"]


def test_manage_open_orders_dry_run_detects_stale_candidate(tmp_path):
    outbox_path = tmp_path / "outbox.json"
    snapshot_path = tmp_path / "broker_orders.json"
    live_dir = tmp_path / "live_execution"
    submitted_at = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)).isoformat()

    outbox_path.write_text(
        json.dumps(
            [
                {
                    "order_intent_id": "intent-1",
                    "broker_order_id": "broker-1",
                    "client_order_id": "client-1",
                    "symbol": "AAPL",
                    "side": "BUY",
                    "target_quantity": 10.0,
                    "status": "SUBMITTED",
                    "submitted_at": submitted_at,
                }
            ],
            indent=2,
        )
    )
    snapshot_path.write_text(
        json.dumps(
            {
                "source": "alpaca",
                "mode": "alpaca-paper",
                "orders": [
                    {
                        "id": "broker-1",
                        "client_order_id": "client-1",
                        "status": "new",
                    }
                ],
            },
            indent=2,
        )
    )

    with patch("cli.commands.execution._live_execution_base_dir", return_value=live_dir), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "manage-open-orders",
                "--broker",
                "alpaca",
                "--mode",
                "alpaca-paper",
                "--outbox-path",
                str(outbox_path),
                "--broker-snapshot-path",
                str(snapshot_path),
                "--no-refresh-snapshot",
                "--max-age-minutes",
                "30",
                "--dry-run",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["apply_changes"] is False
    assert parsed["stale_candidates_count"] == 1
    assert parsed["canceled_count"] == 1
    assert parsed["replaced_count"] == 0
    assert parsed["errors_count"] == 0


def test_sync_positions_from_broker_apply_updates_shadow_positions(tmp_path):
    snapshot_path = tmp_path / "broker_positions.json"
    positions_path = tmp_path / "positions.json"
    live_dir = tmp_path / "live_execution"

    snapshot_path.write_text(
        json.dumps(
            {
                "source": "alpaca",
                "mode": "alpaca-paper",
                "positions": [
                    {
                        "symbol": "AAPL",
                        "qty": "10",
                        "avg_entry_price": "110.5",
                        "current_price": "111.0",
                        "market_value": "1110.0",
                    }
                ],
            },
            indent=2,
        )
    )
    positions_path.write_text(
        json.dumps(
            {
                "updated_at": "2026-02-06T00:00:00+00:00",
                "open_positions": {
                    "AAPL": {
                        "symbol": "AAPL",
                        "net_quantity": 5.0,
                        "avg_price": 100.0,
                        "market_value_usd": 500.0,
                        "last_mark_price": 100.0,
                        "direction": "LONG",
                        "opened_at": "2026-02-05T00:00:00+00:00",
                        "rating_ids": ["rid-1"],
                        "lane": "CORE",
                        "research_playbook": "HYBRID_COMPOUNDER",
                    }
                },
            },
            indent=2,
        )
    )

    with patch("cli.commands.execution._live_execution_base_dir", return_value=live_dir), patch("cli.common.RatingAuditLog") as audit_cls:
        audit_cls.return_value = Mock()
        result = runner.invoke(
            app,
            [
                "sync-positions-from-broker",
                "--broker",
                "alpaca",
                "--mode",
                "alpaca-paper",
                "--broker-positions-snapshot-path",
                str(snapshot_path),
                "--positions-path",
                str(positions_path),
                "--no-refresh-snapshot",
                "--apply",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0
    parsed = _extract_json(result.stdout)
    assert parsed["apply_changes"] is True
    assert parsed["updated_count"] == 1
    updated_payload = json.loads(positions_path.read_text())
    updated = updated_payload["open_positions"]["AAPL"]
    assert updated["net_quantity"] == 10.0
    assert updated["avg_price"] == 110.5
    assert updated["rating_ids"] == ["rid-1"]
