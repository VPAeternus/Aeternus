"""CLI command: commodity-scan — detect geopolitical pre-positioning anomalies."""
from cli.common import *  # noqa: F401,F403


@app.command("commodity-scan")
def commodity_scan(
    dry_run: bool = typer.Option(False, "--dry-run", help="Detect anomalies without writing to AKG"),
    lookback_days: int = typer.Option(10, "--lookback-days", help="Recent window for anomaly detection"),
    baseline_days: int = typer.Option(30, "--baseline-days", help="Baseline window for Z-score"),
    format: str = typer.Option("table", "--format", help="Output format: table|json"),
):
    """Scan geopolitical cluster instruments for pre-positioning anomalies (free, yfinance)."""
    import json as _json
    from tradingagents.dealflow.sources.commodity_shock_scout import scan_commodity_shock_clusters
    from rich.table import Table as RichTable

    alerts = scan_commodity_shock_clusters(
        lookback_days=lookback_days,
        baseline_days=baseline_days,
        dry_run=dry_run,
    )

    output_format = str(format or "table").lower().strip()

    if output_format == "json":
        console.print(_json.dumps([{
            "cluster": a.cluster_name,
            "confidence": a.confidence,
            "direction": a.direction,
            "triggered": a.triggered_instruments,
            "volume_z_max": a.volume_z_max,
        } for a in alerts], indent=2))
        return

    if not alerts:
        console.print("[green]No cluster anomalies detected.[/green]")
        if dry_run:
            console.print("[yellow]--dry-run: no events written to AKG[/yellow]")
        return

    table = RichTable(title="COMMODITY_SHOCK Cluster Alerts", show_header=True)
    table.add_column("Cluster", style="cyan bold")
    table.add_column("Confidence", justify="right")
    table.add_column("Direction")
    table.add_column("Vol Z-Max", justify="right")
    table.add_column("Triggered Instruments")

    for alert in sorted(alerts, key=lambda a: a.confidence, reverse=True):
        conf_color = "green" if alert.confidence >= 0.6 else "yellow"
        table.add_row(
            alert.cluster_name,
            f"[{conf_color}]{alert.confidence:.2f}[/{conf_color}]",
            "[green]POSITIVE[/green]" if alert.direction == "POSITIVE" else "[red]NEGATIVE[/red]",
            f"{alert.volume_z_max:.2f}",
            ", ".join(alert.triggered_instruments),
        )

    console.print(table)
    if dry_run:
        console.print("[yellow]--dry-run: no events written to AKG[/yellow]")
