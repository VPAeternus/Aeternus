from cli.common import *  # noqa: F401,F403
from tradingagents.context import get_company_context, get_event_state


context_app = typer.Typer(name="context", help="Internal context query commands.")
app.add_typer(context_app, name="context")


def _format_optional_metric(value: object) -> str:
    if value is None:
        return "None"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _format_bool_date(found: bool, date_value: object) -> str:
    if not found:
        return "no"
    date_text = str(date_value or "").strip()
    return f"yes ({date_text})" if date_text else "yes"


@app.command("event-state")
def event_state(
    date: Optional[str] = typer.Option(None, help="Run date label (YYYY-MM-DD), defaults to today"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Show observed market event-state based on SPY/VIX shock metrics."""
    run_date = date or _today_str()
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    payload = get_event_state(
        as_of_date=run_date,
        config=DEFAULT_CONFIG,
        market_shock_provider=DealFlowPipeline(config=DEFAULT_CONFIG.copy())._market_shock_metrics,
    )

    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2, default=str))
        return

    table = Table(title="Event State")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Date", str(payload.get("as_of_date", "")))
    table.add_row("Triggered", "yes" if bool(payload.get("triggered")) else "no")
    reasons = list(payload.get("reasons", []) or [])
    table.add_row("Reasons", ", ".join(reasons) if reasons else "None")
    metrics = dict(payload.get("metrics", {}) or {})
    table.add_row("SPY Move %", _format_optional_metric(metrics.get("spy_move_pct")))
    table.add_row("VIX Jump %", _format_optional_metric(metrics.get("vix_jump_pct")))
    console.print(table)


@context_app.command("company")
def context_company(
    symbol: str = typer.Argument(..., help="Ticker symbol (e.g. AAPL)"),
    date: Optional[str] = typer.Option(None, help="As-of date (YYYY-MM-DD), defaults to today"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Show current internal Aeternus context for a company."""
    run_date = date or _today_str()
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    payload = get_company_context(symbol, as_of_date=run_date)
    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2, default=str))
        return

    akg = dict(payload.get("akg", {}) or {})
    analysis = dict(payload.get("analysis", {}) or {})
    dealflow = dict(payload.get("dealflow", {}) or {})
    research_queue = dict(dealflow.get("research_queue", {}) or {})
    shortlist = dict(dealflow.get("shortlist", {}) or {})
    portfolio = dict(payload.get("portfolio", {}) or {})
    x_feed = dict(payload.get("x_feed", {}) or {})
    gaps = list(payload.get("known_gaps", []) or [])

    table = Table(title=f"Company Context: {payload.get('symbol', symbol.upper())}")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("As Of", str(payload.get("as_of_date", "")))
    table.add_row("Search Scope", str(payload.get("search_scope", "internal_only")))
    table.add_row("AKG", "yes" if bool(akg.get("found")) else "no")
    table.add_row("Display Name", str(akg.get("display_name") or "None"))
    table.add_row("Sector", str(akg.get("sector") or "None"))
    table.add_row("Latest Analysis", _format_bool_date(bool(analysis.get("found")), analysis.get("latest_report_date")))
    table.add_row("Latest Rating", str(analysis.get("rating") or "None"))
    table.add_row("Latest Score", _format_optional_metric(analysis.get("aeternus_score")))
    table.add_row("Research Queue", _format_bool_date(bool(research_queue.get("found")), research_queue.get("date")))
    table.add_row("Shortlist", _format_bool_date(bool(shortlist.get("found")), shortlist.get("date")))
    table.add_row("Open Position", "yes" if bool(portfolio.get("found")) else "no")
    table.add_row("X Feed", _format_bool_date(bool(x_feed.get("found")), x_feed.get("source_date")))
    table.add_row("Known Gaps", ", ".join(gaps) if gaps else "None")
    console.print(table)
