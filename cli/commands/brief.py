"""Morning brief command — portfolio overview for traders and investors."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.common import app
from tradingagents.graph.morning_brief import build_morning_brief

console = Console()


def _format_html_brief(brief: dict) -> str:
    """Generate self-contained HTML from brief dict."""
    port = brief.get("portfolio", {})
    perf = brief.get("performance", {})
    risk = brief.get("risk", {})
    catalysts = brief.get("catalysts", {})
    deal_flow = brief.get("deal_flow", {})

    # Build position rows
    pos_rows = ""
    for pos in port.get("top_positions", []):
        pnl_color = "green" if pos["pnl_pct"] > 0 else "red"
        pos_rows += f"""
        <tr>
            <td>{pos['symbol']}</td>
            <td>{pos['direction']}</td>
            <td style="color: {pnl_color}; font-weight: bold;">{pos['pnl_pct']:+.2f}%</td>
            <td>${pos['notional']:,.0f}</td>
        </tr>
        """

    # Build signal rows
    signal_rows = ""
    for sig in deal_flow.get("top_signals", []):
        signal_rows += f"""
        <tr>
            <td>{sig['symbol']}</td>
            <td>{sig['score']:.1f}</td>
            <td>{sig['family']}</td>
        </tr>
        """

    # Build recent trades rows
    recent_rows = ""
    for trade in perf.get("recent_closes", []):
        trade_color = "green" if trade["pnl_pct"] > 0 else "red"
        recent_rows += f"""
        <tr>
            <td>{trade['symbol']}</td>
            <td style="color: {trade_color}; font-weight: bold;">{trade['pnl_pct']:+.2f}%</td>
            <td>{trade['closed_at']}</td>
        </tr>
        """

    # Drawdown status badge
    status = risk.get("drawdown_status", "OK")
    status_color = {"OK": "green", "WARNING": "orange", "ALERT": "red"}.get(status, "blue")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aeternus Morning Brief — {brief.get('date', 'N/A')}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, #1e1e2e 0%, #2d2d44 100%);
            color: #e0e0e0;
            padding: 20px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: #2a2a3e;
            border-radius: 8px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 30px;
            color: white;
            text-align: center;
        }}
        .header h1 {{ font-size: 2.2em; margin-bottom: 10px; }}
        .header p {{ font-size: 1em; opacity: 0.9; }}
        .status-badge {{
            display: inline-block;
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: bold;
            margin-top: 15px;
            background: {status_color};
            color: white;
        }}
        .content {{
            padding: 30px;
        }}
        .section {{
            margin-bottom: 40px;
        }}
        .section h2 {{
            font-size: 1.4em;
            color: #667eea;
            margin-bottom: 15px;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .kpi-card {{
            background: #383854;
            padding: 15px;
            border-radius: 6px;
            border-left: 4px solid #667eea;
        }}
        .kpi-label {{
            font-size: 0.9em;
            color: #a0a0b0;
            margin-bottom: 5px;
        }}
        .kpi-value {{
            font-size: 1.6em;
            font-weight: bold;
            color: #e0e0e0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }}
        th {{
            background: #383854;
            color: #667eea;
            padding: 12px;
            text-align: left;
            font-weight: bold;
            border-bottom: 2px solid #667eea;
        }}
        td {{
            padding: 10px 12px;
            border-bottom: 1px solid #383854;
        }}
        tr:hover {{
            background: #383854;
        }}
        .text-positive {{ color: #52c41a; }}
        .text-negative {{ color: #ff4d4f; }}
        .alert {{
            background: #2d2d44;
            border-left: 4px solid #ff4d4f;
            padding: 15px;
            border-radius: 4px;
            margin-top: 15px;
        }}
        .footer {{
            background: #1e1e2e;
            padding: 20px 30px;
            text-align: center;
            color: #707080;
            font-size: 0.9em;
        }}
        .timestamp {{
            color: #707080;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚡ AETERNUS MORNING BRIEF</h1>
            <p>{brief.get('date', 'N/A')}</p>
            <div class="status-badge">{status}</div>
            <div class="timestamp">Generated: {brief.get('generated_at', 'N/A')}</div>
        </div>

        <div class="content">
            <!-- Portfolio Section -->
            <div class="section">
                <h2>Portfolio Overview</h2>
                <div class="kpi-grid">
                    <div class="kpi-card">
                        <div class="kpi-label">Current Equity</div>
                        <div class="kpi-value">${port.get('equity', 0):,.0f}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">High Water Mark</div>
                        <div class="kpi-value">${port.get('hwm', 0):,.0f}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Drawdown</div>
                        <div class="kpi-value">{port.get('drawdown_pct', 0):+.2f}%</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Open Positions</div>
                        <div class="kpi-value">{port.get('open_positions', 0)}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Gross Exposure</div>
                        <div class="kpi-value">${port.get('gross_exposure', 0):,.0f}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Net Exposure</div>
                        <div class="kpi-value">${port.get('net_exposure', 0):,.0f}</div>
                    </div>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th>Position</th>
                            <th>Direction</th>
                            <th>P&L %</th>
                            <th>Notional</th>
                        </tr>
                    </thead>
                    <tbody>
                        {pos_rows}
                    </tbody>
                </table>
            </div>

            <!-- Performance Section -->
            <div class="section">
                <h2>Performance Metrics</h2>
                <div class="kpi-grid">
                    <div class="kpi-card">
                        <div class="kpi-label">Win Rate</div>
                        <div class="kpi-value">{perf.get('win_rate', 0):.1%}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Closed Trades</div>
                        <div class="kpi-value">{perf.get('closed_trades', 0)} / {perf.get('total_trades', 0)}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Avg Win</div>
                        <div class="kpi-value text-positive">{perf.get('avg_win_pct', 0):+.2f}%</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Avg Loss</div>
                        <div class="kpi-value text-negative">{perf.get('avg_loss_pct', 0):+.2f}%</div>
                    </div>
                </div>
                <h3 style="color: #a0a0b0; margin-top: 20px; margin-bottom: 10px;">Recent Closes</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th>Return</th>
                            <th>Date</th>
                        </tr>
                    </thead>
                    <tbody>
                        {recent_rows}
                    </tbody>
                </table>
            </div>

            <!-- Risk Section -->
            <div class="section">
                <h2>Risk Summary</h2>
                <div class="kpi-grid">
                    <div class="kpi-card">
                        <div class="kpi-label">Status</div>
                        <div class="kpi-value">{risk.get('drawdown_status', 'OK')}</div>
                    </div>
                </div>
                {f'<div class="alert">Concentration alerts:<br>' + '<br>'.join(risk.get('concentration_flags', [])) + '</div>' if risk.get('concentration_flags') else ''}
            </div>

            <!-- Deal Flow Section -->
            <div class="section">
                <h2>Top Deal Flow Signals</h2>
                <p style="color: #a0a0b0; margin-bottom: 15px;">Latest Queue: {deal_flow.get('latest_queue_date', 'N/A')}</p>
                <table>
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th>Score</th>
                            <th>Lane</th>
                        </tr>
                    </thead>
                    <tbody>
                        {signal_rows}
                    </tbody>
                </table>
            </div>

            <!-- Catalysts Section -->
            <div class="section">
                <h2>Catalysts & Research</h2>
                <div class="kpi-grid">
                    <div class="kpi-card">
                        <div class="kpi-label">Active Causal Candidates</div>
                        <div class="kpi-value">{catalysts.get('causal_candidates', 0)}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Upcoming Catalysts</div>
                        <div class="kpi-value">{catalysts.get('forward_anticipation', 0)}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Watchlist Items</div>
                        <div class="kpi-value">{catalysts.get('watchlist_items', 0)}</div>
                    </div>
                </div>
            </div>
        </div>

        <div class="footer">
            <p>Aeternus Investment Intelligence Platform</p>
            <p>Generated: {brief.get('generated_at', 'N/A')}</p>
        </div>
    </div>
</body>
</html>
"""
    return html


@app.command("brief")
def morning_brief(
    format: str = typer.Option("rich", "--format", help="Output format: rich or json"),
    save: bool = typer.Option(False, "--save", help="Save HTML version to ~/.agent/diagrams/"),
):
    """Generate morning briefing: positions, overnight P&L, signals, catalysts."""
    brief = build_morning_brief()

    if format == "json":
        console.print(json.dumps(brief, indent=2))
        return

    # Rich terminal output
    port = brief.get("portfolio", {})
    perf = brief.get("performance", {})
    risk = brief.get("risk", {})
    catalysts = brief.get("catalysts", {})
    deal_flow = brief.get("deal_flow", {})

    # Header
    status = port.get("drawdown_status", "OK")
    status_color = {"OK": "green", "WARNING": "yellow", "ALERT": "red"}.get(status, "blue")
    header = Panel(
        f"[bold][{status_color}]AETERNUS MORNING BRIEF[/{status_color}][/bold]\n"
        f"{brief.get('date', 'N/A')} • Status: [{status_color}]{status}[/{status_color}]",
        style="bold blue",
    )
    console.print(header)

    # Portfolio table
    port_table = Table(title="Portfolio Overview", show_header=True, header_style="bold cyan")
    port_table.add_column("Metric", style="cyan")
    port_table.add_column("Value", justify="right", style="bold white")

    port_table.add_row("Current Equity", f"${port.get('equity', 0):,.0f}")
    port_table.add_row("High Water Mark", f"${port.get('hwm', 0):,.0f}")
    port_table.add_row("Drawdown", f"{port.get('drawdown_pct', 0):+.2f}%")
    port_table.add_row("Open Positions", str(port.get("open_positions", 0)))
    port_table.add_row("Gross Exposure", f"${port.get('gross_exposure', 0):,.0f}")
    port_table.add_row("Net Exposure", f"${port.get('net_exposure', 0):,.0f}")

    console.print(port_table)
    console.print()

    # Top positions table
    if port.get("top_positions"):
        pos_table = Table(title="Top Positions (by notional)", show_header=True, header_style="bold cyan")
        pos_table.add_column("Symbol", style="green")
        pos_table.add_column("Direction", style="cyan")
        pos_table.add_column("P&L %", justify="right")
        pos_table.add_column("Notional", justify="right", style="bold white")

        for pos in port.get("top_positions", []):
            pnl_color = "green" if pos["pnl_pct"] > 0 else "red"
            pos_table.add_row(
                pos["symbol"],
                pos["direction"],
                f"[{pnl_color}]{pos['pnl_pct']:+.2f}%[/{pnl_color}]",
                f"${pos['notional']:,.0f}",
            )

        console.print(pos_table)
        console.print()

    # Performance table
    perf_table = Table(title="Performance Metrics", show_header=True, header_style="bold cyan")
    perf_table.add_column("Metric", style="cyan")
    perf_table.add_column("Value", justify="right", style="bold white")

    perf_table.add_row("Win Rate", f"{perf.get('win_rate', 0):.1%}")
    perf_table.add_row("Closed Trades", f"{perf.get('closed_trades', 0)} / {perf.get('total_trades', 0)}")
    perf_table.add_row("Avg Win", f"[green]{perf.get('avg_win_pct', 0):+.2f}%[/green]")
    perf_table.add_row("Avg Loss", f"[red]{perf.get('avg_loss_pct', 0):+.2f}%[/red]")

    console.print(perf_table)
    console.print()

    # Recent closes
    if perf.get("recent_closes"):
        recent_table = Table(title="Recent Closed Positions", show_header=True, header_style="bold cyan")
        recent_table.add_column("Symbol", style="green")
        recent_table.add_column("Return %", justify="right")
        recent_table.add_column("Closed", style="cyan")

        for trade in perf.get("recent_closes", []):
            trade_color = "green" if trade["pnl_pct"] > 0 else "red"
            recent_table.add_row(
                trade["symbol"],
                f"[{trade_color}]{trade['pnl_pct']:+.2f}%[/{trade_color}]",
                trade["closed_at"],
            )

        console.print(recent_table)
        console.print()

    # GEX Regime section
    gex = brief.get("gex_regime", {})
    if gex.get("stale"):
        console.print(
            "[bold red]GEX DATA STALE[/bold red] — run: "
            "[cyan]aeternus x-feed --generate --pass 15[/cyan]"
        )
        console.print()
    elif gex.get("data"):
        regime = gex["data"]
        console.print(
            f"[cyan]GEX:[/cyan] {regime.get('net_gex', '?')} "
            f"({regime.get('gex_magnitude', '?')}) | "
            f"Pin: {regime.get('key_pin_strike', '?')} | "
            f"Flip: {regime.get('gamma_flip_strike', '?')} | "
            f"DIX: {regime.get('dix_signal', '?')}"
        )
        console.print()

    # Risk section
    risk_table = Table(title="Risk Status", show_header=True, header_style="bold cyan")
    risk_table.add_column("Metric", style="cyan")
    risk_table.add_column("Value", justify="right", style="bold white")

    risk_table.add_row("Drawdown Status", f"[{status_color}]{risk.get('drawdown_status', 'OK')}[/{status_color}]")
    risk_table.add_row(
        "Concentration Flags",
        f"[yellow]{len(risk.get('concentration_flags', []))}[/yellow]",
    )

    console.print(risk_table)

    if risk.get("concentration_flags"):
        console.print("[yellow]Concentration Alerts:[/yellow]")
        for flag in risk.get("concentration_flags", []):
            console.print(f"  • {flag}")
        console.print()

    if risk.get("stress_brief"):
        stress_panel = Panel(risk.get("stress_brief"), title="[yellow]Stress Test Summary[/yellow]")
        console.print(stress_panel)
        console.print()

    # Catalysts section
    cat_table = Table(title="Catalysts & Research", show_header=True, header_style="bold cyan")
    cat_table.add_column("Metric", style="cyan")
    cat_table.add_column("Count", justify="right", style="bold white")

    cat_table.add_row("Active Causal Candidates", str(catalysts.get("causal_candidates", 0)))
    cat_table.add_row("Upcoming Catalysts", str(catalysts.get("forward_anticipation", 0)))
    cat_table.add_row("Watchlist Items", str(catalysts.get("watchlist_items", 0)))

    console.print(cat_table)
    console.print()

    # Deal flow signals
    if deal_flow.get("top_signals"):
        signals_table = Table(title="Top Deal Flow Signals", show_header=True, header_style="bold cyan")
        signals_table.add_column("Symbol", style="green")
        signals_table.add_column("Score", justify="right")
        signals_table.add_column("Lane", style="magenta")

        for sig in deal_flow.get("top_signals", []):
            signals_table.add_row(
                sig["symbol"],
                f"{sig['score']:.1f}",
                sig["family"],
            )

        console.print(signals_table)
        console.print()

    # Optionally save HTML
    if save:
        html_content = _format_html_brief(brief)
        agent_dir = Path.home() / ".agent" / "diagrams"
        agent_dir.mkdir(parents=True, exist_ok=True)

        html_path = agent_dir / f"brief-{brief.get('date', 'N/A')}.html"
        html_path.write_text(html_content)
        console.print(f"[green]✓[/green] Saved HTML brief to [cyan]{html_path}[/cyan]")


@app.command("brief-html")
def morning_brief_html():
    """Generate and open HTML morning brief in browser."""
    brief = build_morning_brief()
    html_content = _format_html_brief(brief)

    agent_dir = Path.home() / ".agent" / "diagrams"
    agent_dir.mkdir(parents=True, exist_ok=True)

    html_path = agent_dir / f"brief-{brief.get('date', 'N/A')}.html"
    html_path.write_text(html_content)

    console.print(f"[green]✓[/green] Generated brief: [cyan]{html_path}[/cyan]")

    # Open in browser
    try:
        subprocess.run(["open", str(html_path)], check=True)
        console.print("[green]✓[/green] Opened in browser")
    except Exception as e:
        console.print(f"[yellow]Note:[/yellow] Could not open browser: {e}")
