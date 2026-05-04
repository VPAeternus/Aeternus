"""CLI commands: options-add, options-list, options-close, roll-check.

options-add    — register a CC or CSP position in the options position store
options-list   — display all registered positions as a Rich table
options-close  — mark a position as closed
roll-check     — evaluate all active positions and render roll recommendations
"""

import datetime

from cli.common import *  # noqa: F401,F403

_OPTIONS_POSITIONS_PATH = DEFAULT_CONFIG.get(
    "options_positions_path", "eval_results/control/options_positions.json"
)


@app.command("options-add")
def options_add(
    type: str = typer.Option(..., "--type", help="Position type: cc or csp"),
    ticker: str = typer.Option(..., "--ticker", help="Underlying ticker symbol (e.g. QQQ)"),
    strike: float = typer.Option(..., "--strike", help="Option strike price"),
    expiry: Optional[str] = typer.Option(
        None,
        "--expiry",
        help="Expiry date YYYY-MM-DD (default: today for 0DTE)",
    ),
    credit: float = typer.Option(..., "--credit", help="Credit received per share (premium)"),
    contracts: int = typer.Option(1, "--contracts", help="Number of contracts"),
    notes: str = typer.Option("", "--notes", help="Optional notes"),
) -> None:
    """Register a covered call (CC) or cash-secured put (CSP) position."""
    from tradingagents.graph.cc_csp_roll_monitor import add_position

    pos_type = type.lower().strip()
    if pos_type not in ("cc", "csp"):
        console.print("[red]Error: --type must be cc or csp[/red]")
        raise typer.Exit(1)

    expiry_str = expiry or datetime.date.today().isoformat()

    pos_dict = {
        "type": pos_type,
        "ticker": ticker.upper(),
        "strike": strike,
        "expiry": expiry_str,
        "credit_received": credit,
        "contracts": contracts,
        "notes": notes,
    }

    pos_id = add_position(pos_dict, path=Path(_OPTIONS_POSITIONS_PATH))
    console.print(
        f"[green]Registered[/green] {pos_type.upper()} | "
        f"{ticker.upper()} ${strike} exp {expiry_str} | "
        f"credit ${credit:.2f} × {contracts} contract(s) | "
        f"id=[bold]{pos_id}[/bold]"
    )


@app.command("options-list")
def options_list(
    all: bool = typer.Option(False, "--all", help="Include closed and expired positions"),
) -> None:
    """List registered options positions."""
    from tradingagents.graph.cc_csp_roll_monitor import load_positions

    positions = load_positions(path=Path(_OPTIONS_POSITIONS_PATH))
    if not positions:
        console.print("[yellow]No positions registered.[/yellow]")
        return

    if not all:
        positions = [p for p in positions if p.get("status") == "active"]

    if not positions:
        console.print("[yellow]No active positions. Use --all to see closed/expired.[/yellow]")
        return

    today = datetime.date.today()
    table = Table(title="Options Positions", box=box.SIMPLE_HEAD)
    table.add_column("ID", style="dim")
    table.add_column("Type", style="bold")
    table.add_column("Ticker", style="bold white")
    table.add_column("Strike", justify="right", style="cyan")
    table.add_column("Expiry", style="cyan")
    table.add_column("DTE", justify="right")
    table.add_column("Credit", justify="right", style="green")
    table.add_column("Contracts", justify="right")
    table.add_column("Status", style="yellow")

    for pos in positions:
        expiry_str = pos.get("expiry", "")
        dte_str = ""
        try:
            exp_date = datetime.date.fromisoformat(expiry_str)
            dte_val = (exp_date - today).days
            dte_str = str(max(0, dte_val))
            if dte_val < 0:
                dte_str = "[dim]expired[/dim]"
        except ValueError:
            pass

        pos_type = pos.get("type", "").upper()
        type_style = "magenta" if pos_type == "CC" else "blue"

        table.add_row(
            pos.get("id", ""),
            f"[{type_style}]{pos_type}[/{type_style}]",
            pos.get("ticker", ""),
            f"${pos.get('strike', 0):.2f}",
            expiry_str,
            dte_str,
            f"${pos.get('credit_received', 0):.2f}",
            str(pos.get("contracts", 1)),
            pos.get("status", ""),
        )

    console.print(table)
    active_count = sum(1 for p in positions if p.get("status") == "active")
    console.print(f"[dim]{active_count} active position(s)[/dim]")


@app.command("options-close")
def options_close(
    position_id: str = typer.Argument(..., help="Position ID to close"),
) -> None:
    """Mark an options position as closed."""
    from tradingagents.graph.cc_csp_roll_monitor import close_position

    ok = close_position(position_id, path=Path(_OPTIONS_POSITIONS_PATH))
    if ok:
        console.print(f"[green]Position {position_id} marked as closed.[/green]")
    else:
        console.print(f"[red]Position {position_id} not found.[/red]")
        raise typer.Exit(1)


@app.command("roll-check")
def roll_check(
    ticker: Optional[str] = typer.Option(
        None,
        "--ticker",
        help="Filter to a specific ticker symbol",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
) -> None:
    """Evaluate registered CC/CSP positions and show roll recommendations.

    Fetches live option chain data from yfinance for each active position
    and renders actionable roll guidance.
    """
    from tradingagents.graph.cc_csp_roll_monitor import (
        evaluate_position,
        load_positions,
        RollDecision,
    )

    output_format = str(format or "table").lower().strip()
    positions = load_positions(path=Path(_OPTIONS_POSITIONS_PATH))
    active = [p for p in positions if p.get("status") == "active"]

    if ticker:
        active = [p for p in active if p.get("ticker", "").upper() == ticker.upper()]

    if not active:
        console.print("[yellow]No active positions to evaluate.[/yellow]")
        return

    config = {
        "cc_roll_close_early_pct": DEFAULT_CONFIG.get("cc_roll_close_early_pct", 0.75),
        "csp_roll_close_early_pct": DEFAULT_CONFIG.get("csp_roll_close_early_pct", 0.80),
        "cc_roll_accept_assignment_mins": DEFAULT_CONFIG.get("cc_roll_accept_assignment_mins", 60),
    }

    results = []
    with console.status("[cyan]Fetching live option chains…[/cyan]"):
        for pos in active:
            result = evaluate_position(pos, config=config)
            results.append(result)

    if output_format == "json":
        import json as _json
        output = []
        for r in results:
            output.append({
                "id": r.position.get("id"),
                "ticker": r.position.get("ticker"),
                "type": r.position.get("type"),
                "strike": r.position.get("strike"),
                "expiry": r.position.get("expiry"),
                "decision": r.decision.value,
                "underlying_price": r.underlying_price,
                "option_mark": r.option_mark,
                "pct_captured": round(r.pct_captured, 4),
                "intrinsic": r.intrinsic,
                "extrinsic": r.extrinsic,
                "roll_target_strike": r.roll_target_strike,
                "roll_net_debit": r.roll_net_debit,
                "rationale": r.rationale,
            })
        typer.echo(_json.dumps(output, indent=2))
        return

    # Rich panel rendering
    for r in results:
        pos = r.position
        pos_type = pos.get("type", "").upper()
        ticker_sym = pos.get("ticker", "")
        strike_val = pos.get("strike", 0)
        credit_val = pos.get("credit_received", 0)
        contracts = pos.get("contracts", 1)

        # Decision color coding
        action_colors = {
            RollDecision.CC_HOLD_OTM: "green",
            RollDecision.CC_CLOSE_EARLY: "bright_green",
            RollDecision.CC_WATCH_ITM: "yellow",
            RollDecision.CC_ROLL_UP: "red",
            RollDecision.CC_ACCEPT_ASSIGNMENT: "bright_red",
            RollDecision.CSP_HOLD_OTM: "green",
            RollDecision.CSP_CLOSE_EARLY: "bright_green",
            RollDecision.CSP_WATCH_APPROACH: "yellow",
            RollDecision.CSP_ROLL_DOWN: "red",
            RollDecision.CSP_ACCEPT_ASSIGNMENT: "bright_red",
            RollDecision.DATA_UNAVAILABLE: "dim",
        }
        color = action_colors.get(r.decision, "white")

        pnl_per_share = credit_val - r.option_mark
        pnl_dollars = pnl_per_share * 100 * contracts
        pnl_sign = "+" if pnl_dollars >= 0 else ""

        pct_from_strike = (
            (r.underlying_price - strike_val) / strike_val * 100
            if r.underlying_price > 0 and strike_val > 0
            else 0.0
        )
        price_sign = "+" if pct_from_strike >= 0 else ""

        header = (
            f"[bold]{pos_type} {ticker_sym} ${strike_val:.2f}[/bold]  |  "
            f"Current: [cyan]${r.underlying_price:.2f}[/cyan] "
            f"({price_sign}{pct_from_strike:.2f}% vs strike)  |  "
            f"id=[dim]{pos.get('id', '')}[/dim]"
        )

        body_lines = [
            f"Credit: [green]${credit_val:.2f}[/green]  |  "
            f"Mark: [cyan]${r.option_mark:.2f}[/cyan]  |  "
            f"Captured: [bold]{r.pct_captured:.0%}[/bold]",
            f"Intrinsic: ${r.intrinsic:.2f}  |  "
            f"Extrinsic: ${r.extrinsic:.2f}  |  "
            f"DTE: {r.dte}  |  "
            f"Contracts: {contracts}",
            f"P&L: [{('green' if pnl_dollars >= 0 else 'red')}]{pnl_sign}${pnl_dollars:.2f}[/{'green' if pnl_dollars >= 0 else 'red'}] "
            f"({pnl_sign}${pnl_per_share:.2f}/share)",
            "",
            f"[{color}][bold]▶ {r.decision.value}[/bold][/{color}]",
            f"[{color}]{r.rationale}[/{color}]",
        ]

        if r.roll_target_strike is not None:
            debit_label = "debit" if (r.roll_net_debit or 0) > 0 else "credit"
            debit_val = abs(r.roll_net_debit or 0)
            body_lines.append(
                f"\n[bold]Roll target:[/bold] ${r.roll_target_strike:.2f} | "
                f"Net {debit_label}: ${debit_val:.2f} | "
                f"Expiry: {r.roll_target_expiry}"
            )

        console.print(
            Panel(
                "\n".join(body_lines),
                title=header,
                border_style=color,
                padding=(0, 1),
            )
        )
