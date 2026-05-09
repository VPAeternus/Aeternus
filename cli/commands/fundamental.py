"""CLI command: fundamental — run fundamental framework from dealflow queue."""
from __future__ import annotations

from cli.common import *  # noqa: F401,F403

import datetime as _dt
import json
import sys as _sys


def _print_top10_table(rows: list[dict]) -> None:
    table = Table(title="Fundamental High-Conviction Top 10")
    table.add_column("Rank", justify="right")
    table.add_column("Ticker", style="bold green")
    table.add_column("Composite", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Confidence", justify="right")
    table.add_column("Lane")
    table.add_column("Reasons")
    for idx, row in enumerate(rows, start=1):
        table.add_row(
            str(row.get("selection_rank") or row.get("selection_order") or idx),
            str(row.get("ticker", "")),
            str(row.get("composite_score", "")),
            str(row.get("score", row.get("entry_score_0_100", ""))),
            str(row.get("confidence_numeric", row.get("confidence", ""))),
            str(row.get("lane_normalized", row.get("lane", ""))),
            ",".join(str(x) for x in row.get("reason_codes", [])),
        )
    console.print(table)


def _print_top15_table(rows: list[dict]) -> None:
    table = Table(title="Fundamental High-Conviction Top 15")
    table.add_column("Sleeve")
    table.add_column("Rank", justify="right")
    table.add_column("Ticker", style="bold green")
    table.add_column("Treatment")
    table.add_column("Score", justify="right")
    table.add_column("Exception", justify="right")
    for idx, row in enumerate(rows, start=1):
        table.add_row(
            str(row.get("selected_sleeve", "")),
            str(row.get("selected_sleeve_rank") or row.get("selection_rank") or idx),
            str(row.get("ticker", "")),
            str(row.get("portfolio_treatment", "")),
            str(row.get("score", row.get("entry_score_0_100", ""))),
            str(row.get("right_tail_exception_score", "")),
        )
    console.print(table)


def _print_candidate_scores(lake_root: Path) -> None:
    try:
        import pandas as pd
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not render score table: pandas unavailable ({exc})[/yellow]")
        return

    path = lake_root / "candidate_scores.parquet"
    if not path.exists():
        console.print(f"[yellow]No candidate_scores artifact found at {path}[/yellow]")
        return
    frame = pd.read_parquet(path)
    if frame.empty:
        console.print("[yellow]candidate_scores is empty[/yellow]")
        return

    table = Table(title="Fundamental Scores")
    table.add_column("Ticker", style="bold green")
    table.add_column("Pre Score", justify="right")
    table.add_column("Bucket")
    table.add_column("Entry", justify="right")
    table.add_column("Label")
    table.add_column("Decision")
    table.add_column("Docs")
    for _, row in frame.iterrows():
        table.add_row(
            str(row.get("ticker", "")),
            str(row.get("pre_llm_fundamental_score", "")),
            str(row.get("pre_llm_fundamental_bucket", "")),
            str(row.get("entry_score_0_100", "")),
            str(row.get("entry_score_label", "")),
            str(row.get("decision_type", "")),
            str(row.get("document_status", "")),
        )
    console.print(table)


@app.command("fundamental-top10")
def fundamental_top10(
    scores_csv: str = typer.Option(..., "--scores-csv", help="Required final fundamental scores CSV path"),
    coverage_manifest: str = typer.Option("", "--coverage-manifest", help="Optional SEC coverage manifest CSV path"),
    output_root: str = typer.Option("", "--output-root", help="Output root; defaults to scores CSV parent or eval_results/fundamental/<date>"),
    date: str = typer.Option("", "--date", help="Selection date YYYY-MM-DD"),
    top_n: int = typer.Option(10, "--top-n", min=1, help="Number of names to select"),
    min_score: float = typer.Option(70.0, "--min-score", help="Minimum score threshold"),
    min_confidence: float = typer.Option(3.0, "--min-confidence", help="Minimum confidence threshold"),
    format: str = typer.Option("table", "--format", help="Output format: table|json"),
):
    """Select post-score high-conviction fundamental Top-N names."""
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_from_csv

    fmt = format.strip().lower()
    if fmt not in {"table", "json"}:
        console.print("[red]--format must be table or json[/red]")
        raise typer.Exit(1)

    scores_path = Path(scores_csv)
    if not scores_path.exists():
        console.print(f"[red]scores CSV not found: {scores_path}[/red]")
        raise typer.Exit(1)
    coverage_path = Path(coverage_manifest) if coverage_manifest.strip() else None
    if coverage_path is not None and not coverage_path.exists():
        console.print(f"[red]coverage manifest not found: {coverage_path}[/red]")
        raise typer.Exit(1)

    selection_date = date.strip()
    out_root = Path(output_root.strip()) if output_root.strip() else (
        Path("eval_results") / "fundamental" / selection_date if selection_date else scores_path.parent
    )
    config = {
        "top_n": top_n,
        "min_score": min_score,
        "min_confidence": min_confidence,
        "selection_date": selection_date,
        "coverage_gating": coverage_path is not None,
    }
    result = select_from_csv(scores_path, out_root, config, coverage_path)

    if fmt == "json":
        console.print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_top10_table(result.get("selected_rows", []))
        paths = result["output_paths"]
        console.print(f"[green]Wrote[/green] {paths['csv']} | {paths['json']} | {paths['recommendation_md']}")


@app.command("fundamental-top15")
def fundamental_top15(
    scores_csv: str = typer.Option(..., "--scores-csv", help="Required final fundamental scores CSV path"),
    coverage_manifest: str = typer.Option("", "--coverage-manifest", help="Optional SEC coverage manifest CSV path"),
    output_root: str = typer.Option("", "--output-root", help="Output root; defaults to scores CSV parent or eval_results/fundamental/<date>"),
    date: str = typer.Option("", "--date", help="Selection date YYYY-MM-DD"),
    core_n: int = typer.Option(10, "--core-n", min=1, help="Core names to select"),
    exception_slots: int = typer.Option(5, "--exception-slots", min=0, help="Right-tail exception slots"),
    format: str = typer.Option("table", "--format", help="Output format: table|json"),
):
    """Select Top-15 queue: Top-10 core plus right-tail exception sleeve."""
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_top15_from_csv

    fmt = format.strip().lower()
    if fmt not in {"table", "json"}:
        console.print("[red]--format must be table or json[/red]")
        raise typer.Exit(1)
    scores_path = Path(scores_csv)
    if not scores_path.exists():
        console.print(f"[red]scores CSV not found: {scores_path}[/red]")
        raise typer.Exit(1)
    coverage_path = Path(coverage_manifest) if coverage_manifest.strip() else None
    if coverage_path is not None and not coverage_path.exists():
        console.print(f"[red]coverage manifest not found: {coverage_path}[/red]")
        raise typer.Exit(1)
    selection_date = date.strip()
    out_root = Path(output_root.strip()) if output_root.strip() else (
        Path("eval_results") / "fundamental" / selection_date if selection_date else scores_path.parent
    )
    config = {
        "selection_date": selection_date,
        "enabled": True,
        "core_n": core_n,
        "exception_slots": exception_slots,
        "coverage_gating": coverage_path is not None,
    }
    result = select_top15_from_csv(scores_path, out_root, config, coverage_path)
    if fmt == "json":
        console.print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_top15_table(result.get("selected_rows", []))
        paths = result["output_paths"]
        console.print(f"[green]Wrote[/green] {paths['csv']} | {paths['json']} | {paths['recommendation_md']}")


@app.command("fundamental-right-tail-queues")
def fundamental_right_tail_queues(
    scores_csv: str = typer.Option(..., "--scores-csv", help="Required final fundamental scores CSV path"),
    top15_selected_csv: str = typer.Option("", "--top15-selected-csv", help="Optional high_conviction_top15.csv path for already-selected suppression"),
    target_events_csv: str = typer.Option("", "--target-events-csv", help="Optional historical/debug target events CSV"),
    output_root: str = typer.Option("", "--output-root", help="Output root; defaults to scores CSV parent"),
    date: str = typer.Option("", "--date", help="Selection date YYYY-MM-DD"),
    format: str = typer.Option("table", "--format", help="Output format: table|json"),
):
    """Emit right-tail visibility queues from final fundamental scores."""
    from tradingagents.research.fundamental.src.selection.right_tail_queues import select_right_tail_queues_from_csv

    fmt = format.strip().lower()
    if fmt not in {"table", "json"}:
        console.print("[red]--format must be table or json[/red]")
        raise typer.Exit(1)
    scores_path = Path(scores_csv)
    if not scores_path.exists():
        console.print(f"[red]scores CSV not found: {scores_path}[/red]")
        raise typer.Exit(1)
    top15_path = Path(top15_selected_csv) if top15_selected_csv.strip() else None
    if top15_path is not None and not top15_path.exists():
        console.print(f"[yellow]Top15 selected CSV not provided or not found: {top15_path}; scout queues may include already-selected Top15 names.[/yellow]")
        top15_path = None
    elif top15_path is None:
        console.print("[yellow]Top15 selected CSV not provided; scout queues may include already-selected Top15 names.[/yellow]")
    target_path = Path(target_events_csv) if target_events_csv.strip() else None
    if target_path is not None and not target_path.exists():
        console.print(f"[red]target events CSV not found: {target_path}[/red]")
        raise typer.Exit(1)
    out_root = Path(output_root.strip()) if output_root.strip() else scores_path.parent
    result = select_right_tail_queues_from_csv(
        scores_path,
        out_root,
        top15_selected_csv=top15_path,
        target_events_csv=target_path,
        selection_date=date.strip(),
    )
    if fmt == "json":
        console.print(json.dumps(result, indent=2, sort_keys=True))
    else:
        paths = result["output_paths"]
        console.print(f"[green]Wrote[/green] {paths['top15_exception_candidate_queue']} | {paths['right_tail_scout_queue']} | {paths['demote_review_queue']} | {paths['right_tail_evidence_score_diagnostics']}")
        if "target_miss_rescue_audit" in paths:
            console.print(f"[green]Target audit[/green] {paths['target_miss_rescue_audit']}")


@app.command("fundamental")
def fundamental(
    date: str = typer.Option("", "--date", help="Dealflow queue date YYYY-MM-DD; defaults to today"),
    quarter: str = typer.Option("", "--quarter", help="Fundamental quarter, e.g. 2026Q2; defaults from --date"),
    queue: str = typer.Option("", "--queue", help="Optional research_queue.json path"),
    output_root: str = typer.Option("", "--output-root", help="Output root; defaults to eval_results/fundamental/<date>"),
    all_items: bool = typer.Option(False, "--all", help="Use all queue items, not only selected_for_deep"),
    refresh_cik_map: bool = typer.Option(False, "--refresh-cik-map", help="Refresh SEC company_tickers.json cache"),
    skip_sec_fetch: bool = typer.Option(False, "--skip-sec-fetch", help="Skip SEC filing/document fetch"),
    skip_llm: bool = typer.Option(True, "--skip-llm/--run-llm", help="Skip LLM extraction stage by default"),
    skip_price_fetch: bool = typer.Option(True, "--skip-price-fetch/--fetch-prices", help="Skip Yahoo price fetch by default"),
):
    """Run the fundamental framework from a dealflow research queue."""
    import sys as _sys

    fundamental_root = Path("tradingagents") / "research" / "fundamental"
    if str(fundamental_root) not in _sys.path:
        _sys.path.insert(0, str(fundamental_root))

    framework_root = Path("tradingagents") / "research" / "fundamental"
    if str(framework_root.resolve()) not in _sys.path:
        _sys.path.insert(0, str(framework_root.resolve()))

    from tradingagents.research.fundamental.src.pipeline.dealflow_adapter import build_dealflow_universe_csv
    from tradingagents.research.fundamental.src.pipeline.run_quarter import run_quarter_pipeline

    run_date = date.strip() or _dt.date.today().strftime("%Y-%m-%d")
    out_root = Path(output_root.strip()) if output_root.strip() else Path("eval_results") / "fundamental" / run_date
    out_root.mkdir(parents=True, exist_ok=True)
    queue_path = Path(queue.strip()) if queue.strip() else Path("eval_results") / "deal_flow" / run_date / "research_queue.json"
    if not queue_path.exists():
        console.print(f"[red]research queue not found: {queue_path}[/red]")
        raise typer.Exit(1)

    universe_path = out_root / "dealflow_universe.csv"
    adapter_result = build_dealflow_universe_csv(
        as_of_date=run_date,
        queue_path=queue_path,
        output_path=universe_path,
        quarter=quarter.strip() or None,
        refresh_cik_map=bool(refresh_cik_map),
        selected_only=not bool(all_items),
    )
    console.print(
        f"[green]Universe ready[/green] rows={adapter_result['row_count']} | "
        f"cik_resolved={adapter_result['resolved_cik_count']} | path={universe_path}"
    )
    if int(adapter_result.get("unresolved_cik_count", 0) or 0):
        console.print(f"[yellow]Unresolved CIKs: {adapter_result['unresolved_cik_count']}[/yellow]")

    lake_root = out_root / "lake"
    result = run_quarter_pipeline(
        quarter=str(adapter_result["quarter"]),
        universe_path=universe_path,
        as_of=run_date,
        lake_root=lake_root,
        post_llm_path=None,
        skip_sec_fetch=bool(skip_sec_fetch),
        skip_llm=bool(skip_llm),
        skip_price_fetch=bool(skip_price_fetch),
    )
    console.print(
        f"[green]Fundamental run complete[/green] run_id={result['pipeline_run_id']} | "
        f"candidates={result['candidate_rows']} | lake={lake_root}"
    )
    _print_candidate_scores(lake_root)
