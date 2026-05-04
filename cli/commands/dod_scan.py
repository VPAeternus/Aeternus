"""CLI command: dod-scan — detect DoD defense contract spending spikes."""
from cli.common import *  # noqa: F401,F403


@app.command("dod-scan")
def dod_scan(
    dry_run: bool = typer.Option(False, "--dry-run", help="Detect spikes without writing to AKG"),
    lookback_days: int = typer.Option(30, "--lookback-days", help="Recent window in days"),
    format: str = typer.Option("table", "--format", help="Output format: table|json"),
):
    """Scan DoD USASpending.gov for defense contract award spikes (free, no API key)."""
    import json as _json
    import dataclasses
    from tradingagents.dealflow.sources.dod_contract_scout import scan_dod_contract_spikes
    from rich.table import Table as RichTable

    spikes = scan_dod_contract_spikes(lookback_days=lookback_days, dry_run=dry_run)

    output_format = str(format or "table").lower().strip()

    if output_format == "json":
        console.print(_json.dumps([dataclasses.asdict(s) for s in spikes], indent=2))
        return

    if not spikes:
        console.print("[green]No DoD contract spending anomalies detected.[/green]")
        if dry_run:
            console.print("[yellow]--dry-run: no events written to AKG[/yellow]")
        return

    table = RichTable(title="DoD Contract Spending Alerts", show_header=True)
    table.add_column("Sector", style="cyan bold")
    table.add_column("Z-Score", justify="right")
    table.add_column("Confidence", justify="right")
    table.add_column("Recent Total")
    table.add_column("Top Recipients")

    for spike in sorted(spikes, key=lambda s: s.z_score, reverse=True):
        conf_color = "green" if spike.confidence >= 0.6 else "yellow"
        table.add_row(
            spike.sector,
            f"{spike.z_score:.2f}",
            f"[{conf_color}]{spike.confidence:.2f}[/{conf_color}]",
            f"${spike.recent_total_usd/1e6:.1f}M",
            ", ".join(spike.top_recipients[:2]),
        )

    console.print(table)
    if dry_run:
        console.print("[yellow]--dry-run: no events written to AKG[/yellow]")
