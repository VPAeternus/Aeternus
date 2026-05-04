"""CLI command: breakout-scan — scan for 52-week high breakouts in AKG universe."""
from cli.common import *  # noqa: F401,F403


@app.command("breakout-scan")
def breakout_scan(
    dry_run: bool = typer.Option(False, "--dry-run", help="Scan without writing to AKG"),
    format: str = typer.Option("table", "--format", help="Output format: table|json"),
):
    """Scan AKG universe for 52-week high breakouts on volume (free, yfinance)."""
    import json as _json
    from tradingagents.dealflow.sources.breakout_scanner import scan_breakout_discovery
    from rich.table import Table as RichTable

    result = scan_breakout_discovery(dry_run=dry_run)

    if format == "json":
        console.print(_json.dumps(result, indent=2))
        return

    alerts = result.get("alerts", [])
    if not alerts:
        console.print("[green]No breakout alerts detected.[/green]")
        if dry_run:
            console.print("[yellow]--dry-run: no events written to AKG[/yellow]")
        return

    table = RichTable(
        title=f"Breakout Discovery — {result.get('trade_date', 'today')}",
        show_header=True,
    )
    table.add_column("Ticker", style="cyan bold")
    table.add_column("Score", justify="right")
    table.add_column("Near High", justify="right")
    table.add_column("Vol Ratio", justify="right")
    table.add_column("Trend", justify="center")

    for a in sorted(alerts, key=lambda x: x["score"], reverse=True):
        score_color = "green" if a["score"] >= 70 else "yellow"
        trend = ""
        if a.get("above_sma200"):
            trend += ">SMA200"
        if a.get("sma50_above_sma200"):
            trend += " GC"
        table.add_row(
            a["ticker"],
            f"[{score_color}]{a['score']:.0f}[/{score_color}]",
            f"{a['near_high']:.2%}",
            f"{a['vol_ratio']:.1f}x",
            trend.strip() or "-",
        )

    console.print(table)
    console.print(f"\n  {result['count']} breakouts from {result.get('universe_scanned', '?')} liquid symbols")
    if dry_run:
        console.print("[yellow]--dry-run: no events written to AKG[/yellow]")
