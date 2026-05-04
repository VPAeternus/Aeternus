from cli.common import *  # noqa: F401,F403

import json
from dataclasses import asdict
from pathlib import Path

from tradingagents.research.fundamental_autoresearch.artifacts import (
    write_autoresearch_summary,
    write_baseline_comparison,
    write_best_strategy,
    write_constrained_search,
    write_experiment_summary,
    write_leaderboard,
    write_replay_arena,
    write_robustness_report,
    write_top_robustness,
)
from tradingagents.research.fundamental_autoresearch.autoresearch import run_constrained_autoresearch
from tradingagents.research.fundamental_autoresearch.evaluate import (
    compare_baseline_strategies,
    evaluate_scored_rows,
)
from tradingagents.research.fundamental_autoresearch.market_data import enrich_prepared_rows_with_market_data
from tradingagents.research.fundamental_autoresearch.prepare import (
    build_prepared_rows_from_cache,
    load_prepared_rows,
    write_prepared_rows,
)
from tradingagents.research.fundamental_autoresearch.qwen_autoresearch import (
    QwenAutoresearchError,
    run_qwen_autoresearch,
)
from tradingagents.research.fundamental_autoresearch.qwen_feature_lab import (
    QwenFeatureLabError,
    run_qwen_feature_lab,
)
from tradingagents.research.fundamental_autoresearch.replay_arena import run_replay_arena
from tradingagents.research.fundamental_autoresearch.promotion_gate import evaluate_promotion_gate
from tradingagents.research.fundamental_autoresearch.registry import (
    promote_strategy,
    save_signal_registry,
)
from tradingagents.research.fundamental_autoresearch.score import score_feature_row
from tradingagents.research.fundamental_autoresearch.search import run_constrained_search
from tradingagents.research.fundamental_autoresearch.robustness import evaluate_strategy_robustness
from tradingagents.research.fundamental_autoresearch.sec_fetch import fill_sec_cache_for_universe
from tradingagents.research.fundamental_autoresearch.sec_fetch import resolve_ticker_cik_map
from tradingagents.research.fundamental_autoresearch.sector_map import get_large_cap_v1_sector_map
from tradingagents.research.fundamental_autoresearch.universe import (
    get_universe_sector_map,
    get_v1_universe,
)
from tradingagents.research.fundamental_autoresearch.universe_builders import (
    build_liquid_core_v1,
    load_research_universe,
)


def _parse_symbols(symbols: str) -> list[str]:
    return [symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip()]


def _resolve_universe(*, symbols: str, universe_name: str) -> list[str]:
    if universe_name:
        return get_v1_universe(universe_name)
    if symbols:
        return _parse_symbols(symbols)
    raise typer.BadParameter("Provide either --symbols or --universe-name")


def _sector_map_for_universe(
    universe: list[str],
    *,
    universe_name: str,
    sector_map_json: str,
) -> dict[str, str] | None:
    if sector_map_json:
        return json.loads(Path(sector_map_json).read_text())

    if universe_name:
        return get_universe_sector_map(universe_name)

    large_cap_symbols = set(get_v1_universe("large_cap_v1"))
    if set(universe).issubset(large_cap_symbols):
        sector_map = get_large_cap_v1_sector_map()
        return {ticker: sector_map[ticker] for ticker in universe if ticker in sector_map}

    return None


def _infer_run_date_from_artifact(artifact_path: Path, *, results_root: str) -> str:
    root = Path(results_root).resolve()
    resolved = artifact_path.resolve()
    try:
        rel = resolved.relative_to(root)
    except ValueError as exc:
        raise typer.BadParameter(
            f"Unable to infer run date from artifact outside results root: {artifact_path}"
        ) from exc
    parts = rel.parts
    if not parts:
        raise typer.BadParameter(f"Unable to infer run date from artifact: {artifact_path}")
    return parts[0]


@app.command("fundamental-research-build-universe")
def fundamental_research_build_universe(
    name: str = typer.Option("liquid_core_v1", "--name", help="Research universe name"),
    universe_root: str = typer.Option(
        "eval_results/fundamental_autoresearch/universes",
        "--universe-root",
        help="Universe artifact root",
    ),
    target_size: int = typer.Option(250, "--target-size", help="Target number of symbols"),
    per_sector_cap: int = typer.Option(30, "--per-sector-cap", help="Maximum names per sector"),
    min_avg_dollar_volume: float = typer.Option(
        20_000_000.0,
        "--min-avg-dollar-volume",
        help="Minimum 60d average dollar volume",
    ),
    min_last_close: float = typer.Option(
        5.0,
        "--min-last-close",
        help="Minimum last close price",
    ),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
) -> None:
    if name != "liquid_core_v1":
        raise typer.BadParameter("Only liquid_core_v1 is supported in v1")

    artifact_path = build_liquid_core_v1(
        universe_root=universe_root,
        target_size=target_size,
        per_sector_cap=per_sector_cap,
        min_avg_dollar_volume=min_avg_dollar_volume,
        min_last_close=min_last_close,
    )
    payload = load_research_universe(name, universe_root=universe_root)
    output = {
        "name": name,
        "count": int(payload.get("count", 0) or 0),
        "artifact_path": str(artifact_path),
    }

    if format == "json":
        typer.echo(json.dumps(output))
        return

    table = Table(title="Fundamental Research Universe", box=box.ROUNDED, show_header=True)
    table.add_column("Metric", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Name", output["name"])
    table.add_row("Count", str(output["count"]))
    table.add_row("Artifact", output["artifact_path"])
    console.print(table)


@app.command("fundamental-research-cache-fill")
def fundamental_research_cache_fill(
    symbols: str = typer.Option("", "--symbols", help="Comma-separated ticker list"),
    universe_name: str = typer.Option("", "--universe-name", help="Named research universe artifact"),
    cache_root: str = typer.Option(
        "eval_results/fundamental_autoresearch/sec_cache",
        "--cache-root",
        help="SEC raw cache root",
    ),
    user_agent: str = typer.Option(
        "AeternusAgentsAG/1.0 (research@aeternus.ai)",
        "--user-agent",
        help="SEC-compliant user agent",
    ),
    include_history: bool = typer.Option(
        False,
        "--include-history/--no-include-history",
        help="Also fetch and cache historical SEC submissions shards",
    ),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
) -> None:
    import requests

    universe = _resolve_universe(symbols=symbols, universe_name=universe_name)
    session = requests.Session()
    ticker_to_cik = resolve_ticker_cik_map(
        universe,
        cache_root=cache_root,
        session=session,
        user_agent=user_agent,
    )
    summary = fill_sec_cache_for_universe(
        universe,
        ticker_to_cik=ticker_to_cik,
        cache_root=cache_root,
        session=session,
        user_agent=user_agent,
        include_history=include_history,
    )

    payload = {
        **summary,
        "cache_root": str(cache_root),
    }

    if format == "json":
        typer.echo(json.dumps(payload))
        return

    table = Table(title="Fundamental SEC Cache Fill", box=box.ROUNDED, show_header=True)
    table.add_column("Metric", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Cached", ", ".join(payload["cached"]) or "None")
    table.add_row("Missing CIK", ", ".join(payload["skipped_missing_cik"]) or "None")
    table.add_row("Failed", ", ".join(payload["failed"]) or "None")
    table.add_row("Cache Root", payload["cache_root"])
    console.print(table)


@app.command("fundamental-research-prepare")
def fundamental_research_prepare(
    symbols: str = typer.Option("", "--symbols", help="Comma-separated ticker list"),
    universe_name: str = typer.Option("", "--universe-name", help="Named research universe artifact"),
    cache_root: str = typer.Option(
        "eval_results/fundamental_autoresearch/sec_cache",
        "--cache-root",
        help="SEC raw cache root",
    ),
    sector_map_json: str = typer.Option("", "--sector-map-json", help="Optional path to ticker->sector JSON"),
    run_name: str = typer.Option("large_cap_v1-latest", "--run-name", help="Prepared dataset run name"),
    all_filings: bool = typer.Option(
        False,
        "--all-filings/--latest-only",
        help="Build all supported filing snapshots instead of latest-only rows",
    ),
    start_year: int = typer.Option(2009, "--start-year", help="Earliest fiscal year to include for all-filings runs"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
) -> None:
    universe = _resolve_universe(symbols=symbols, universe_name=universe_name)
    sector_map = _sector_map_for_universe(
        universe,
        universe_name=universe_name,
        sector_map_json=sector_map_json,
    )
    rows = build_prepared_rows_from_cache(
        cache_root=cache_root,
        universe=universe,
        sector_map=sector_map,
        include_history=all_filings,
        latest_only=not all_filings,
        start_year=start_year if all_filings else None,
    )
    artifact_path = write_prepared_rows(rows, cache_root=cache_root, run_name=run_name)

    payload = {
        "rows": len(rows),
        "artifact_path": str(artifact_path),
    }

    if format == "json":
        typer.echo(json.dumps(payload))
        return

    table = Table(title="Fundamental Prepared Rows", box=box.ROUNDED, show_header=True)
    table.add_column("Metric", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Rows", str(payload["rows"]))
    table.add_row("Artifact", payload["artifact_path"])
    console.print(table)


@app.command("fundamental-research-attach-returns")
def fundamental_research_attach_returns(
    prepared_json: str = typer.Option(..., "--prepared-json", help="Path to prepared feature rows JSON"),
    output_json: str = typer.Option(..., "--output-json", help="Path to write prepared rows with returns"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
) -> None:
    rows = load_prepared_rows(prepared_json)
    enriched_rows = enrich_prepared_rows_with_market_data(rows)
    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(enriched_rows, indent=2, sort_keys=True))

    payload = {
        "rows": len(enriched_rows),
        "artifact_path": str(output_path),
    }

    if format == "json":
        typer.echo(json.dumps(payload))
        return

    table = Table(title="Fundamental Prepared Rows With Returns", box=box.ROUNDED, show_header=True)
    table.add_column("Metric", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Rows", str(payload["rows"]))
    table.add_row("Artifact", payload["artifact_path"])
    console.print(table)


@app.command("fundamental-research")
def fundamental_research(
    prepared_json: str = typer.Option(..., "--prepared-json", help="Path to prepared feature rows JSON"),
    results_root: str = typer.Option(
        "eval_results/fundamental_autoresearch",
        "--results-root",
        help="Output root for experiment artifacts",
    ),
    run_date: str = typer.Option("2026-03-08", "--run-date", help="Run date (YYYY-MM-DD)"),
    experiment_name: str = typer.Option("baseline", "--experiment-name", help="Experiment name"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
) -> None:
    """Run the fundamental autoresearch scorer on prepared feature rows."""
    rows = json.loads(Path(prepared_json).read_text())
    scored_rows = []
    for row in rows:
        score = score_feature_row(row)
        scored_rows.append(
            {
                **row,
                "fundamental_score": score.fundamental_score,
            }
        )

    summary = evaluate_scored_rows(
        scored_rows,
        dataset_name="prepared_json",
        score_version="baseline_v1",
    )
    artifact_path = write_experiment_summary(
        summary,
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )

    payload = {
        **asdict(summary),
        "artifact_path": str(artifact_path),
    }

    if format == "json":
        typer.echo(json.dumps(payload))
        return

    table = Table(title="Fundamental Autoresearch", box=box.ROUNDED, show_header=True)
    table.add_column("Metric", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Dataset", payload["dataset_name"])
    table.add_row("Score Version", payload["score_version"])
    table.add_row("Primary Metric", payload["primary_metric_name"])
    table.add_row("Primary Value", f"{float(payload['primary_metric_value']):.4f}")
    table.add_row("Coverage", f"{100.0 * float(payload['coverage_ratio']):.2f}%")
    table.add_row("Observations", str(payload["observations"]))
    table.add_row("Artifact", payload["artifact_path"])
    console.print(table)


@app.command("fundamental-research-compare-baselines")
def fundamental_research_compare_baselines(
    prepared_json: str = typer.Option(..., "--prepared-json", help="Path to prepared feature rows JSON"),
    results_root: str = typer.Option(
        "eval_results/fundamental_autoresearch",
        "--results-root",
        help="Output root for experiment artifacts",
    ),
    run_date: str = typer.Option("2026-03-08", "--run-date", help="Run date (YYYY-MM-DD)"),
    experiment_name: str = typer.Option("baseline-comparison", "--experiment-name", help="Experiment name"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
) -> None:
    rows = load_prepared_rows(prepared_json)
    comparison = compare_baseline_strategies(rows, dataset_name="prepared_json")
    artifact_path = write_baseline_comparison(
        comparison,
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )

    payload = {
        "strategies": len(comparison),
        "artifact_path": str(artifact_path),
        "results": comparison,
    }

    if format == "json":
        typer.echo(json.dumps(payload))
        return

    table = Table(title="Fundamental Baseline Comparison", box=box.ROUNDED, show_header=True)
    table.add_column("Strategy", style="bold cyan", no_wrap=True)
    table.add_column("Metric", style="white")
    table.add_column("Value", style="white")
    table.add_column("Coverage", style="white")
    table.add_column("Obs", style="white")
    for row in comparison:
        table.add_row(
            row["strategy"],
            row["primary_metric_name"],
            f"{float(row['primary_metric_value']):.6f}",
            f"{100.0 * float(row['coverage_ratio']):.2f}%",
            str(row["observations"]),
        )
    console.print(table)
    console.print(f"Artifact: {artifact_path}")


@app.command("fundamental-research-constrained-search")
def fundamental_research_constrained_search(
    prepared_json: str = typer.Option(..., "--prepared-json", help="Path to prepared feature rows JSON"),
    results_root: str = typer.Option(
        "eval_results/fundamental_autoresearch",
        "--results-root",
        help="Output root for experiment artifacts",
    ),
    run_date: str = typer.Option("2026-03-08", "--run-date", help="Run date (YYYY-MM-DD)"),
    experiment_name: str = typer.Option("constrained-search", "--experiment-name", help="Experiment name"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
) -> None:
    rows = load_prepared_rows(prepared_json)
    comparison = run_constrained_search(rows, dataset_name="prepared_json")
    artifact_path = write_constrained_search(
        comparison,
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )

    payload = {
        "strategies": len(comparison),
        "artifact_path": str(artifact_path),
        "results": comparison,
    }

    if format == "json":
        typer.echo(json.dumps(payload))
        return

    table = Table(title="Fundamental Constrained Search", box=box.ROUNDED, show_header=True)
    table.add_column("Strategy", style="bold cyan", no_wrap=True)
    table.add_column("Metric", style="white")
    table.add_column("Value", style="white")
    table.add_column("Coverage", style="white")
    table.add_column("Obs", style="white")
    for row in comparison[:10]:
        table.add_row(
            row["strategy"],
            row["primary_metric_name"],
            f"{float(row['primary_metric_value']):.6f}",
            f"{100.0 * float(row['coverage_ratio']):.2f}%",
            str(row["observations"]),
        )
    console.print(table)
    console.print(f"Artifact: {artifact_path}")


@app.command("fundamental-research-robustness")
def fundamental_research_robustness(
    prepared_json: str = typer.Option(..., "--prepared-json", help="Path to prepared feature rows JSON"),
    strategy: str = typer.Option(..., "--strategy", help="Strategy name to evaluate"),
    results_root: str = typer.Option(
        "eval_results/fundamental_autoresearch",
        "--results-root",
        help="Output root for experiment artifacts",
    ),
    run_date: str = typer.Option("2026-03-08", "--run-date", help="Run date (YYYY-MM-DD)"),
    experiment_name: str = typer.Option("robustness", "--experiment-name", help="Experiment name"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
) -> None:
    rows = load_prepared_rows(prepared_json)
    result = evaluate_strategy_robustness(rows, strategy=strategy)
    artifact_path = write_robustness_report(
        result,
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )

    payload = {
        "artifact_path": str(artifact_path),
        "result": result,
    }

    if format == "json":
        typer.echo(json.dumps(payload))
        return

    table = Table(title="Fundamental Robustness", box=box.ROUNDED, show_header=True)
    table.add_column("Horizon", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white", justify="right")
    table.add_column("Coverage", style="white", justify="right")
    table.add_column("Obs", style="white", justify="right")
    for horizon, row in result["by_horizon"].items():
        table.add_row(
            horizon,
            f"{float(row['primary_metric_value']):.6f}",
            f"{100.0 * float(row['coverage_ratio']):.2f}%",
            str(row["observations"]),
        )
    console.print(table)
    console.print(f"Artifact: {artifact_path}")


@app.command("fundamental-research-autoresearch")
def fundamental_research_autoresearch(
    prepared_json: str = typer.Option(..., "--prepared-json", help="Path to prepared feature rows JSON"),
    results_root: str = typer.Option(
        "eval_results/fundamental_autoresearch",
        "--results-root",
        help="Output root for experiment artifacts",
    ),
    run_date: str = typer.Option("2026-03-08", "--run-date", help="Run date (YYYY-MM-DD)"),
    experiment_name: str = typer.Option("constrained-autoresearch", "--experiment-name", help="Experiment name"),
    top_n: int = typer.Option(10, "--top-n", help="Number of ranked strategies to keep"),
    robustness_top_n: int = typer.Option(0, "--robustness-top-n", help="Number of top strategies to evaluate for robustness"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
) -> None:
    rows = load_prepared_rows(prepared_json)
    experiment = run_constrained_autoresearch(
        rows,
        dataset_name="prepared_json",
        top_n=top_n,
        robustness_top_n=robustness_top_n,
    )
    registry_rows = experiment.get("registry_rows", experiment["leaderboard"])
    summary_path = write_autoresearch_summary(
        experiment,
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )
    write_best_strategy(
        experiment["best_strategy"],
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )
    write_leaderboard(
        experiment["leaderboard"],
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )
    write_top_robustness(
        experiment["top_robustness"],
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )
    registry_path = save_signal_registry(
        registry_rows,
        results_root=results_root,
        run_date=run_date,
        registry_name="fundamental_signals",
    )

    payload = {
        **experiment,
        "registry_rows": registry_rows,
        "artifact_path": str(summary_path),
        "registry_artifact_path": str(registry_path),
    }

    if format == "json":
        typer.echo(json.dumps(payload))
        return

    table = Table(title="Fundamental Constrained Autoresearch", box=box.ROUNDED, show_header=True)
    table.add_column("Strategy", style="bold cyan", no_wrap=True)
    table.add_column("Metric", style="white")
    table.add_column("Value", style="white")
    table.add_column("Coverage", style="white")
    table.add_column("Obs", style="white")
    for row in experiment["leaderboard"]:
        table.add_row(
            row["strategy"],
            row["primary_metric_name"],
            f"{float(row['primary_metric_value']):.6f}",
            f"{100.0 * float(row['coverage_ratio']):.2f}%",
            str(row["observations"]),
        )
    console.print(table)
    console.print(f"Artifact: {summary_path}")


@app.command("fundamental-research-replay-arena")
def fundamental_research_replay_arena(
    prepared_json: str = typer.Option(..., "--prepared-json", help="Path to prepared feature rows JSON"),
    results_root: str = typer.Option(
        "eval_results/fundamental_autoresearch",
        "--results-root",
        help="Output root for experiment artifacts",
    ),
    run_date: str = typer.Option("2026-03-09", "--run-date", help="Run date (YYYY-MM-DD)"),
    experiment_name: str = typer.Option("replay-arena", "--experiment-name", help="Experiment name"),
    strategies: str = typer.Option(
        "baseline_v1,health_only,quality_only_inverted",
        "--strategies",
        help="Comma-separated strategy list",
    ),
    baseline_strategy: str = typer.Option("baseline_v1", "--baseline-strategy", help="Baseline strategy"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
) -> None:
    rows = load_prepared_rows(prepared_json)
    strategy_list = [token.strip() for token in strategies.split(",") if token.strip()]
    result = run_replay_arena(
        rows,
        strategies=strategy_list,
        baseline_strategy=baseline_strategy,
        dataset_name="prepared_json",
    )
    artifact_path = write_replay_arena(
        result,
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )

    payload = {
        "artifact_path": str(artifact_path),
        "result": result,
    }

    if format == "json":
        typer.echo(json.dumps(payload))
        return

    table = Table(title="Fundamental Replay Arena", box=box.ROUNDED, show_header=True)
    table.add_column("Horizon", style="bold cyan", no_wrap=True)
    table.add_column("Winner", style="white")
    table.add_column("Metric", style="white")
    table.add_column("Value", style="white")
    for horizon, row in result["winners_by_horizon"].items():
        table.add_row(
            horizon,
            row["strategy"],
            row["primary_metric_name"],
            f"{float(row['primary_metric_value']):.6f}",
        )
    console.print(table)
    console.print(f"Artifact: {artifact_path}")


@app.command("fundamental-research-qwen-autoresearch")
def fundamental_research_qwen_autoresearch(
    prepared_json: str = typer.Option(..., "--prepared-json", help="Path to prepared feature rows JSON"),
    results_root: str = typer.Option(
        "eval_results/fundamental_autoresearch",
        "--results-root",
        help="Output root for experiment artifacts",
    ),
    run_date: str = typer.Option("2026-03-09", "--run-date", help="Run date (YYYY-MM-DD)"),
    experiment_name: str = typer.Option("qwen-autoresearch", "--experiment-name", help="Experiment name"),
    base_url: str = typer.Option("http://127.0.0.1:8090/v1", "--base-url", help="Local MLX OpenAI-compatible base URL"),
    model: str = typer.Option("mlx-community/Qwen3.5-9B-MLX-8bit", "--model", help="Local MLX Qwen model name"),
    proposal_count: int = typer.Option(8, "--proposal-count", help="Number of Qwen proposals to request"),
    current_leaderboard_top_n: int = typer.Option(5, "--current-leaderboard-top-n", help="Current constrained leaders to show Qwen"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
) -> None:
    rows = load_prepared_rows(prepared_json)
    try:
        experiment = run_qwen_autoresearch(
            rows,
            dataset_name="prepared_json",
            base_url=base_url,
            model=model,
            proposal_count=proposal_count,
            current_leaderboard_top_n=current_leaderboard_top_n,
        )
    except Exception as exc:
        payload = {"error": str(exc)}
        if format == "json":
            typer.echo(json.dumps(payload))
        else:
            console.print(f"[red]Qwen autoresearch failed:[/red] {exc}")
        raise typer.Exit(code=1)

    summary_path = write_autoresearch_summary(
        experiment,
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )
    write_best_strategy(
        experiment["best_strategy"],
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )
    write_leaderboard(
        experiment["leaderboard"],
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )

    payload = {
        **experiment,
        "artifact_path": str(summary_path),
    }

    if format == "json":
        typer.echo(json.dumps(payload))
        return

    table = Table(title="Fundamental Qwen Autoresearch", box=box.ROUNDED, show_header=True)
    table.add_column("Strategy", style="bold cyan", no_wrap=True)
    table.add_column("Metric", style="white")
    table.add_column("Value", style="white")
    table.add_column("Coverage", style="white")
    table.add_column("Obs", style="white")
    for row in experiment["leaderboard"]:
        table.add_row(
            row["strategy"],
            row["primary_metric_name"],
            f"{float(row['primary_metric_value']):.6f}",
            f"{100.0 * float(row['coverage_ratio']):.2f}%",
            str(row["observations"]),
        )
    console.print(table)
    console.print(f"Artifact: {summary_path}")


@app.command("fundamental-research-qwen-feature-lab")
def fundamental_research_qwen_feature_lab(
    prepared_json: str = typer.Option(..., "--prepared-json", help="Path to prepared feature rows JSON"),
    results_root: str = typer.Option(
        "eval_results/fundamental_autoresearch",
        "--results-root",
        help="Output root for experiment artifacts",
    ),
    run_date: str = typer.Option("2026-03-09", "--run-date", help="Run date (YYYY-MM-DD)"),
    experiment_name: str = typer.Option("qwen-feature-lab", "--experiment-name", help="Experiment name"),
    base_url: str = typer.Option("http://127.0.0.1:8090/v1", "--base-url", help="OpenAI-compatible chat base URL"),
    model: str = typer.Option("mlx-community/Qwen3.5-9B-MLX-8bit", "--model", help="Model name for the local chat server"),
    proposal_count: int = typer.Option(4, "--proposal-count", help="Number of Qwen proposals to request"),
    current_leaderboard_top_n: int = typer.Option(5, "--current-leaderboard-top-n", help="Number of current leaderboard rows to show Qwen"),
    timeout_seconds: int = typer.Option(120, "--timeout-seconds", help="Request timeout in seconds"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
) -> None:
    rows = load_prepared_rows(prepared_json)
    try:
        experiment = run_qwen_feature_lab(
            rows,
            dataset_name="prepared_json",
            base_url=base_url,
            model=model,
            proposal_count=proposal_count,
            current_leaderboard_top_n=current_leaderboard_top_n,
            timeout_seconds=timeout_seconds,
        )
    except QwenFeatureLabError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)

    summary_path = write_autoresearch_summary(
        experiment,
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )
    write_best_strategy(
        experiment["best_strategy"],
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )
    write_leaderboard(
        experiment["leaderboard"],
        results_root=results_root,
        run_date=run_date,
        experiment_name=experiment_name,
    )

    payload = {
        **experiment,
        "artifact_path": str(summary_path),
    }

    if format == "json":
        typer.echo(json.dumps(payload))
        return

    table = Table(title="Qwen Fundamental Feature Lab", box=box.ROUNDED, show_header=True)
    table.add_column("Strategy", style="bold cyan", no_wrap=True)
    table.add_column("Metric", style="white")
    table.add_column("Value", style="white")
    table.add_column("Coverage", style="white")
    table.add_column("Obs", style="white")
    for row in experiment["leaderboard"]:
        table.add_row(
            row["strategy"],
            row["primary_metric_name"],
            f"{float(row['primary_metric_value']):.6f}",
            f"{100.0 * float(row['coverage_ratio']):.2f}%",
            str(row["observations"]),
        )
    console.print(table)
    console.print(f"Artifact: {summary_path}")


@app.command("fundamental-research-promote-strategy")
def fundamental_research_promote_strategy(
    autoresearch_summary_json: str = typer.Option(
        ...,
        "--autoresearch-summary-json",
        help="Path to autoresearch_summary.json",
    ),
    strategy: str = typer.Option(
        "",
        "--strategy",
        help="Strategy to promote; defaults to the best strategy in the summary artifact",
    ),
    robustness_json: str = typer.Option(
        "",
        "--robustness-json",
        help="Optional robustness.json to attach and evaluate gate status",
    ),
    results_root: str = typer.Option(
        "eval_results/fundamental_autoresearch",
        "--results-root",
        help="Registry/results root",
    ),
    run_date: str = typer.Option(
        "",
        "--run-date",
        help="Registry run date; inferred from the summary artifact when omitted",
    ),
    status: str = typer.Option(
        "shadow",
        "--status",
        help="Promotion status to set: shadow or promoted",
    ),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
) -> None:
    summary_path = Path(autoresearch_summary_json)
    summary = json.loads(summary_path.read_text())
    registry_rows = [dict(row) for row in (summary.get("registry_rows") or summary.get("leaderboard") or [])]
    if not registry_rows:
        raise typer.BadParameter("Summary artifact does not contain registry_rows or leaderboard entries.")

    chosen_strategy = strategy or (summary.get("best_strategy") or {}).get("strategy")
    if not chosen_strategy:
        raise typer.BadParameter("Unable to determine strategy to promote from the summary artifact.")

    resolved_run_date = run_date or _infer_run_date_from_artifact(summary_path, results_root=results_root)

    robustness_payload = None
    if robustness_json:
        raw = json.loads(Path(robustness_json).read_text())
        robustness_payload = raw.get("result", raw)
        registry_rows = [
            evaluate_promotion_gate(row, robustness=robustness_payload) if row.get("strategy") == chosen_strategy else row
            for row in registry_rows
        ]

    promoted_rows = promote_strategy(
        registry_rows,
        strategy=chosen_strategy,
        status=status,
        robustness=robustness_payload,
    )
    registry_path = save_signal_registry(
        promoted_rows,
        results_root=results_root,
        run_date=resolved_run_date,
        registry_name="fundamental_signals",
    )

    active_row = next(row for row in promoted_rows if row.get("strategy") == chosen_strategy)
    payload = {
        "strategy": chosen_strategy,
        "status": active_row.get("status"),
        "gate_status": active_row.get("gate_status"),
        "recommended_status": active_row.get("recommended_status"),
        "registry_artifact_path": str(registry_path),
        "run_date": resolved_run_date,
    }

    if format == "json":
        typer.echo(json.dumps(payload))
        return

    table = Table(title="Fundamental Strategy Promotion", box=box.ROUNDED, show_header=True)
    table.add_column("Metric", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Strategy", payload["strategy"])
    table.add_row("Status", str(payload["status"]))
    table.add_row("Gate Status", str(payload["gate_status"]))
    table.add_row("Recommended Status", str(payload["recommended_status"]))
    table.add_row("Run Date", payload["run_date"])
    table.add_row("Registry", payload["registry_artifact_path"])
    console.print(table)
