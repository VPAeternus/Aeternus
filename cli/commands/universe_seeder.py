"""CLI command: akg-seed — seed AKG with S&P500, NASDAQ, Russell 2000, Dow, ARK, ETFs, and growth watchlist."""

from cli.common import *  # noqa: F401,F403


@app.command("akg-seed")
def akg_seed(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be added without modifying AKG"),
) -> None:
    """Seed AKG with tickers from S&P 500, NASDAQ, Russell 2000, Dow, ARK, ETFs, and growth watchlist."""
    from tradingagents.dealflow.sources.universe_seeder import seed_akg

    console.print("[cyan]Starting AKG universe seed...[/cyan]")
    if dry_run:
        console.print("[yellow]DRY RUN — AKG will not be modified[/yellow]")

    result = seed_akg(dry_run=dry_run)

    table = Table(title="AKG Seed Results", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")

    table.add_row("Total unique tickers fetched", str(result["total_fetched"]))
    table.add_row("New nodes added", str(result["new_nodes_added"]))
    table.add_row("Existing nodes updated", str(result["existing_updated"]))
    table.add_row("Errors", str(len(result["errors"])))
    if dry_run:
        table.add_row("Mode", "[yellow]DRY RUN[/yellow]")
    else:
        table.add_row("Mode", "[green]LIVE[/green]")

    console.print(table)

    if result["errors"]:
        console.print(f"\n[yellow]Errors ({len(result['errors'])}):[/yellow]")
        for err in result["errors"][:10]:
            console.print(f"  [red]•[/red] {err}")
        if len(result["errors"]) > 10:
            console.print(f"  ... and {len(result['errors']) - 10} more")
