import json

from tradingagents.research.fundamental_autoresearch.artifacts import (
    write_autoresearch_summary,
    write_baseline_comparison,
    write_best_strategy,
    write_constrained_search,
    write_robustness_report,
    write_top_robustness,
    write_experiment_summary,
)
from tradingagents.research.fundamental_autoresearch.contracts import FundamentalEvaluationSummary


def test_write_experiment_summary_writes_expected_json(tmp_path):
    summary = FundamentalEvaluationSummary(
        dataset_name="sec_large_cap_v1",
        score_version="baseline_v1",
        primary_metric_name="rank_ic_60d_sector_neutral",
        primary_metric_value=0.071,
        coverage_ratio=0.88,
        observations=34120,
    )

    path = write_experiment_summary(
        summary,
        results_root=tmp_path,
        run_date="2026-03-08",
        experiment_name="baseline",
    )

    payload = json.loads(path.read_text())

    assert path.name == "summary.json"
    assert payload["dataset_name"] == "sec_large_cap_v1"
    assert payload["score_version"] == "baseline_v1"


def test_write_baseline_comparison_writes_expected_json(tmp_path):
    rows = [
        {
            "strategy": "baseline_v1",
            "primary_metric_name": "rank_ic_60d_sector_neutral",
            "primary_metric_value": 0.01,
            "coverage_ratio": 1.0,
            "observations": 100,
        }
    ]

    path = write_baseline_comparison(
        rows,
        results_root=tmp_path / "results",
        run_date="2026-03-08",
        experiment_name="baseline-comparison",
    )

    assert path == tmp_path / "results" / "2026-03-08" / "baseline-comparison" / "baseline_comparison.json"
    payload = json.loads(path.read_text())
    assert payload[0]["strategy"] == "baseline_v1"
    assert payload[0]["primary_metric_name"] == "rank_ic_60d_sector_neutral"


def test_write_constrained_search_writes_expected_json(tmp_path):
    rows = [
        {
            "strategy": "health_0p7__inv_quality_0p3",
            "weights": {
                "health": 0.7,
                "growth": 0.0,
                "quality": -0.3,
            },
            "primary_metric_name": "rank_ic_60d_sector_neutral",
            "primary_metric_value": 0.07,
            "coverage_ratio": 1.0,
            "observations": 100,
        }
    ]

    path = write_constrained_search(
        rows,
        results_root=tmp_path / "results",
        run_date="2026-03-08",
        experiment_name="constrained-search",
    )

    assert path == tmp_path / "results" / "2026-03-08" / "constrained-search" / "constrained_search.json"
    payload = json.loads(path.read_text())
    assert payload[0]["strategy"] == "health_0p7__inv_quality_0p3"
    assert payload[0]["weights"]["quality"] == -0.3


def test_write_robustness_report_writes_expected_json(tmp_path):
    payload = {
        "strategy": "health_0p5__inv_growth_0p1__inv_quality_0p4",
        "by_horizon": {"60d": {"primary_metric_value": 0.08}},
        "by_era": {"2020_2026": {"primary_metric_value": 0.09}},
        "by_sector": {"Technology": {"primary_metric_value": 0.07}},
    }

    path = write_robustness_report(
        payload,
        results_root=tmp_path / "results",
        run_date="2026-03-08",
        experiment_name="robustness",
    )

    assert path == tmp_path / "results" / "2026-03-08" / "robustness" / "robustness.json"
    disk_payload = json.loads(path.read_text())
    assert disk_payload["strategy"] == "health_0p5__inv_growth_0p1__inv_quality_0p4"
    assert disk_payload["by_horizon"]["60d"]["primary_metric_value"] == 0.08


def test_write_best_strategy_writes_expected_json(tmp_path):
    payload = {
        "strategy": "health_0p5__inv_growth_0p1__inv_quality_0p4",
        "primary_metric_value": 0.087029,
    }

    path = write_best_strategy(
        payload,
        results_root=tmp_path / "results",
        run_date="2026-03-08",
        experiment_name="autoresearch",
    )

    assert path == tmp_path / "results" / "2026-03-08" / "autoresearch" / "best_strategy.json"
    disk_payload = json.loads(path.read_text())
    assert disk_payload["strategy"] == payload["strategy"]


def test_write_top_robustness_writes_expected_json(tmp_path):
    payload = {
        "health_0p5__inv_growth_0p1__inv_quality_0p4": {
            "by_horizon": {"60d": {"primary_metric_value": 0.08}}
        }
    }

    path = write_top_robustness(
        payload,
        results_root=tmp_path / "results",
        run_date="2026-03-08",
        experiment_name="autoresearch",
    )

    assert path == tmp_path / "results" / "2026-03-08" / "autoresearch" / "top_robustness.json"
    disk_payload = json.loads(path.read_text())
    assert disk_payload["health_0p5__inv_growth_0p1__inv_quality_0p4"]["by_horizon"]["60d"]["primary_metric_value"] == 0.08


def test_write_autoresearch_summary_writes_expected_json(tmp_path):
    payload = {
        "strategy_count": 21,
        "leaderboard": [{"strategy": "health_0p5__inv_growth_0p1__inv_quality_0p4"}],
        "best_strategy": {"strategy": "health_0p5__inv_growth_0p1__inv_quality_0p4"},
        "top_robustness": {},
    }

    path = write_autoresearch_summary(
        payload,
        results_root=tmp_path / "results",
        run_date="2026-03-08",
        experiment_name="autoresearch",
    )

    assert path == tmp_path / "results" / "2026-03-08" / "autoresearch" / "autoresearch_summary.json"
    disk_payload = json.loads(path.read_text())
    assert disk_payload["strategy_count"] == 21
