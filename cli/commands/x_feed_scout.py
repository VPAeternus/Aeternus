"""CLI command: x-discover — scan financial X for trending tickers via xAI x_search."""

from cli.common import *  # noqa: F401,F403


@app.command("x-discover")
def x_discover(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show discoveries without writing to AKG"),
) -> None:
    """Scan financial X for trending tickers via xAI x_search. Writes discoveries to AKG."""
    from tradingagents.dealflow.sources.x_feed_scout import scan_x_feed
    from tradingagents.default_config import DEFAULT_CONFIG

    result = scan_x_feed(config=DEFAULT_CONFIG, dry_run=dry_run)

    if not result.get("ran"):
        console.print(f"[red]Did not run: {result.get('reason')}[/red]")
        raise typer.Exit(1)

    table = Table(title="X Feed Discovery Scout")
    table.add_column("Ticker", style="bold")
    table.add_column("Mentions", justify="right")
    table.add_column("Context")
    table.add_column("Status")

    for t in result.get("tickers", []):
        status = "[green]NEW[/green]" if t.get("is_new") else "[dim]existing[/dim]"
        table.add_row(t["ticker"], str(t["mentions_estimate"]), t["context"], status)

    console.print(table)
    console.print(
        f"\nCalls: {result['calls_made']} | "
        f"Found: {result['tickers_found']} | "
        f"New: {result['new_nodes_created']} | "
        f"Updated: {result['existing_nodes_updated']}"
    )
    if result.get("errors"):
        for err in result["errors"]:
            console.print(f"[yellow]Warning: {err}[/yellow]")
