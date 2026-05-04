import json
from dataclasses import asdict
from pathlib import Path

from tradingagents.research.fundamental_autoresearch.contracts import FundamentalEvaluationSummary


def write_experiment_summary(
    summary: FundamentalEvaluationSummary,
    *,
    results_root: str | Path = "eval_results/fundamental_autoresearch",
    run_date: str,
    experiment_name: str,
) -> Path:
    output_dir = Path(results_root) / run_date / experiment_name
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "summary.json"
    path.write_text(json.dumps(asdict(summary), indent=2, sort_keys=True))
    return path


def write_baseline_comparison(
    rows: list[dict],
    *,
    results_root: str | Path = "eval_results/fundamental_autoresearch",
    run_date: str,
    experiment_name: str,
) -> Path:
    output_dir = Path(results_root) / run_date / experiment_name
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "baseline_comparison.json"
    path.write_text(json.dumps(rows, indent=2, sort_keys=True))
    return path


def write_constrained_search(
    rows: list[dict],
    *,
    results_root: str | Path = "eval_results/fundamental_autoresearch",
    run_date: str,
    experiment_name: str,
) -> Path:
    output_dir = Path(results_root) / run_date / experiment_name
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "constrained_search.json"
    path.write_text(json.dumps(rows, indent=2, sort_keys=True))
    return path


def write_robustness_report(
    payload: dict,
    *,
    results_root: str | Path = "eval_results/fundamental_autoresearch",
    run_date: str,
    experiment_name: str,
) -> Path:
    output_dir = Path(results_root) / run_date / experiment_name
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "robustness.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


def write_best_strategy(
    payload: dict,
    *,
    results_root: str | Path = "eval_results/fundamental_autoresearch",
    run_date: str,
    experiment_name: str,
) -> Path:
    output_dir = Path(results_root) / run_date / experiment_name
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "best_strategy.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


def write_leaderboard(
    payload: list[dict],
    *,
    results_root: str | Path = "eval_results/fundamental_autoresearch",
    run_date: str,
    experiment_name: str,
) -> Path:
    output_dir = Path(results_root) / run_date / experiment_name
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "leaderboard.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


def write_top_robustness(
    payload: dict,
    *,
    results_root: str | Path = "eval_results/fundamental_autoresearch",
    run_date: str,
    experiment_name: str,
) -> Path:
    output_dir = Path(results_root) / run_date / experiment_name
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "top_robustness.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


def write_autoresearch_summary(
    payload: dict,
    *,
    results_root: str | Path = "eval_results/fundamental_autoresearch",
    run_date: str,
    experiment_name: str,
) -> Path:
    output_dir = Path(results_root) / run_date / experiment_name
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "autoresearch_summary.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


def write_replay_arena(
    payload: dict,
    *,
    results_root: str | Path = "eval_results/fundamental_autoresearch",
    run_date: str,
    experiment_name: str,
) -> Path:
    output_dir = Path(results_root) / run_date / experiment_name
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "replay_arena.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path
