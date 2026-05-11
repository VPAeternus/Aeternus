"""Position review command — adaptive hold/exit recommendations for open positions."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from cli.common import app

console = Console()

POSITIONS_PATH = "eval_results/paper_execution/positions.json"
AKG_PATH = "eval_results/akg/akg.json"


def _load_json(path: str, default=None):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default if default is not None else {}


@app.command("position-review")
def position_review(
    ticker: str = typer.Argument(None, help="Optional ticker for single-position deep review"),
    deep: bool = typer.Option(False, "--deep", help="Re-run propagate() for fresh LLM verdict"),
    format: str = typer.Option("rich", "--format", help="Output format: rich or json"),
):
    """Review open positions with adaptive hold/exit recommendations."""
    from tradingagents.graph.position_review import review_positions

    positions_data = _load_json(POSITIONS_PATH, {})
    open_positions = positions_data.get("open_positions", {}) if isinstance(positions_data, dict) else {}

    if not open_positions:
        console.print("[yellow]No open positions found.[/yellow]")
        return

    # Load AKG for thesis stress
    akg = None
    try:
        from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
        akg = AeternusKnowledgeGraph.load()
    except Exception:
        pass

    # Scout-only dealflow no longer provides scored opportunity-cost candidates.
    pipeline_candidates = []

    # Filter to single ticker if specified
    if ticker:
        ticker = ticker.upper()
        if ticker not in open_positions:
            console.print(f"[red]{ticker} not found in open positions.[/red]")
            return
        open_positions = {ticker: open_positions[ticker]}

        # Deep mode: re-run propagate() for fresh verdict
        if deep:
            console.print(f"[cyan]Running deep analysis on {ticker}...[/cyan]")
            try:
                import datetime as dt
                from tradingagents.graph.trading_graph import TradingAgentsGraph
                from tradingagents.default_config import DEFAULT_CONFIG
                graph = TradingAgentsGraph(DEFAULT_CONFIG)
                today = dt.date.today().isoformat()
                final_state, signal = graph.propagate(ticker, today)
                console.print(f"[bold]Fresh verdict:[/bold] {signal}")
                entry_score = float(open_positions[ticker].get("entry_aeternus_score", 0) or 0)
                new_score = float(final_state.get("aeternus_score", 0) or 0)
                if entry_score > 0:
                    delta = new_score - entry_score
                    console.print(f"Entry score: {entry_score:.0f} → Current: {new_score:.0f} (Δ {delta:+.0f})")
                console.print()
            except Exception as e:
                console.print(f"[red]Deep analysis failed: {e}[/red]")

    reviews = review_positions(
        positions=open_positions,
        akg=akg,
        pipeline_candidates=pipeline_candidates,
    )

    if format == "json":
        console.print(json.dumps(reviews, indent=2))
        return

    # Rich table output
    table = Table(title="Position Review", show_header=True, header_style="bold cyan")
    table.add_column("Symbol", style="green")
    table.add_column("Entry", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("Δ%", justify="right")
    table.add_column("PnL%", justify="right")
    table.add_column("AnnRet%", justify="right")
    table.add_column("AnnVol%", justify="right")
    table.add_column("MaxDD%", justify="right")
    table.add_column("Hold", justify="right")
    table.add_column("Stress", style="cyan")
    table.add_column("Action", style="bold")
    table.add_column("Reason")

    action_colors = {"EXIT": "red", "WATCH": "yellow", "ROTATE": "magenta", "HOLD": "green"}

    for r in reviews:
        entry = r["entry_score"]
        current = r["current_score"]
        score_delta_pct = ((current - entry) / entry * 100) if entry > 0 else 0
        color = action_colors.get(r["recommendation"], "white")
        pnl = r["pnl_pct"]
        ann_ret = r.get("ann_return_pct", 0.0)
        ann_vol = r.get("ann_vol_pct", 0.0)
        max_dd = r.get("max_dd_pct", 0.0)

        table.add_row(
            r["symbol"],
            f"{entry:.0f}",
            f"{current:.0f}",
            f"{score_delta_pct:+.0f}%",
            f"{'[green]' if pnl >= 0 else '[red]'}{pnl:+.1f}%{'[/green]' if pnl >= 0 else '[/red]'}",
            f"{'[green]' if ann_ret >= 0 else '[red]'}{ann_ret:+.0f}%{'[/green]' if ann_ret >= 0 else '[/red]'}",
            f"{ann_vol:.0f}%",
            f"[red]{max_dd:.1f}%[/red]" if max_dd < 0 else f"{max_dd:.1f}%",
            f"{r['hold_days']}d",
            r["thesis_stress"],
            f"[{color}]{r['recommendation']}[/{color}]",
            r["reason"],
        )

    console.print(table)
