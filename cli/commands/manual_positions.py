"""Manual position entry for brokers without API access (e.g. Robinhood).

Since we can't sync automatically, the operator registers positions manually.
Positions are written to the same positions.json that the rest of the system reads.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import typer
from rich.console import Console

from cli.common import app

console = Console()

POSITIONS_PATH = "eval_results/paper_execution/positions.json"


def _load_positions() -> dict:
    path = Path(POSITIONS_PATH)
    if not path.exists():
        return {"updated_at": "", "open_positions": {}, "source_plan_id": None, "source_date": None}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"updated_at": "", "open_positions": {}, "source_plan_id": None, "source_date": None}


def _save_positions(data: dict) -> None:
    path = Path(POSITIONS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    path.write_text(json.dumps(data, indent=2))


def _lookup_analysis(symbol: str) -> dict:
    """Try to find the most recent analysis report for entry score/breakdown."""
    results_dir = Path("results") / symbol
    if not results_dir.exists():
        return {}
    date_dirs = sorted(results_dir.iterdir(), reverse=True)
    for d in date_dirs:
        report = d / "analysis_report.json"
        if report.exists():
            try:
                data = json.loads(report.read_text())
                rating = data.get("aeternus_score", data)
                if isinstance(rating, dict):
                    return rating
                return data
            except Exception:
                pass
    return {}


@app.command("add-position")
def add_position(
    symbol: str = typer.Argument(..., help="Ticker symbol (e.g. AAPL)"),
    shares: float = typer.Argument(..., help="Number of shares bought"),
    price: float = typer.Argument(..., help="Average entry price per share"),
    date: str = typer.Option(None, "--date", help="Entry date YYYY-MM-DD (default: today)"),
    lane: str = typer.Option("CORE", "--lane", help="Lane: CORE or MOMENTUM"),
):
    """Register a manually-entered position (for brokers without API access)."""
    symbol = symbol.upper()
    entry_date = date or dt.date.today().isoformat()
    opened_at = f"{entry_date}T09:30:00Z"

    # Pull entry score from latest analysis if available
    analysis = _lookup_analysis(symbol)
    if isinstance(analysis, dict) and "aeternus_score" in analysis:
        # analysis_report stores the full rating dict as aeternus_score
        rating_obj = analysis["aeternus_score"]
        if isinstance(rating_obj, dict):
            entry_score = float(rating_obj.get("aeternus_score", 0) or 0)
            breakdown = dict(rating_obj.get("breakdown", {}))
            weight_regime = str(rating_obj.get("weight_regime", ""))
            rating_id = str(rating_obj.get("rating_id", ""))
        else:
            entry_score = float(rating_obj or 0)
            breakdown = dict(analysis.get("breakdown", {}))
            weight_regime = str(analysis.get("weight_regime", ""))
            rating_id = str(analysis.get("rating_id", ""))
    else:
        entry_score = float(analysis.get("aeternus_score", 0) or 0)
        breakdown = dict(analysis.get("breakdown", {}))
        weight_regime = str(analysis.get("weight_regime", ""))
        rating_id = str(analysis.get("rating_id", ""))

    data = _load_positions()
    open_pos = data.get("open_positions", {})

    if symbol in open_pos:
        console.print(f"[yellow]{symbol} already has an open position. Use close-paper first to close it.[/yellow]")
        return

    open_pos[symbol] = {
        "symbol": symbol,
        "net_quantity": float(shares),
        "avg_price": float(price),
        "market_value_usd": round(shares * price, 2),
        "last_mark_price": float(price),
        "opened_at": opened_at,
        "high_watermark_price": float(price),
        "low_watermark_price": None,
        "direction": "LONG" if shares > 0 else "SHORT",
        "rating_ids": [rating_id] if rating_id else [],
        "lane": lane,
        "research_playbook": None,
        "invalidation_conditions": [],
        "original_conviction": 3,
        "entry_aeternus_score": entry_score,
        "entry_pillar_breakdown": breakdown,
        "entry_weight_regime": weight_regime,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    data["open_positions"] = open_pos
    _save_positions(data)

    # Sync to AKG so T6 portfolio tier activates in pipeline universe
    try:
        from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
        akg = AeternusKnowledgeGraph.load()
        akg.set_current_position(symbol, shares, price, entry_date)
        akg.save()
    except Exception:
        pass  # AKG sync is best-effort; positions.json is source of truth

    console.print(f"[green]Added {symbol}:[/green] {shares} shares @ ${price:.2f} (score: {entry_score:.1f}, lane: {lane})")
    if breakdown:
        parts = " | ".join(f"{k}: {v}" for k, v in breakdown.items())
        console.print(f"  Pillars: {parts}")


@app.command("remove-position")
def remove_position(
    symbol: str = typer.Argument(..., help="Ticker symbol to remove"),
):
    """Remove a manually-entered position (e.g. after selling on Robinhood)."""
    symbol = symbol.upper()
    data = _load_positions()
    open_pos = data.get("open_positions", {})

    if symbol not in open_pos:
        console.print(f"[yellow]{symbol} not found in open positions.[/yellow]")
        return

    del open_pos[symbol]
    data["open_positions"] = open_pos
    _save_positions(data)

    # Sync to AKG — clear current_position so T6 tier drops this ticker
    try:
        from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
        akg = AeternusKnowledgeGraph.load()
        akg.close_position(symbol, 0.0, dt.date.today().isoformat())
        akg.save()
    except Exception:
        pass  # AKG sync is best-effort

    console.print(f"[green]Removed {symbol} from positions.[/green]")
