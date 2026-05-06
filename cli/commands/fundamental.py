"""CLI command: fundamental — run fundamental framework from dealflow queue."""
from __future__ import annotations

from cli.common import *  # noqa: F401,F403

import datetime as _dt
import sys as _sys


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
