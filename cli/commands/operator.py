from cli.common import *  # noqa: F401,F403


@app.command("kerberos-evaluate")
def kerberos_evaluate(
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Run one Kerberos %B overlay evaluation cycle and print signal/decision."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    signal, decision, order = run_kerberos_cycle()
    payload = {
        "evaluated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "signal": signal,
        "decision": decision,
        "order": order,
    }

    if output_format == "json":
        print(json_lib.dumps(payload, indent=2))
        return

    console.print(
        "[green]Kerberos evaluation complete[/green] | "
        f"status={decision.get('status', 'UNKNOWN')} | "
        f"action={decision.get('action', 'NO_SIGNAL')}"
    )
    # Load state for panel rendering
    state_path = Path("eval_results/kerberos_state.json")
    state = _read_json(state_path) if state_path.exists() else {}
    if not isinstance(state, dict):
        state = {}
    format_kerberos_overlay_panel(signal, decision, state=state)


@app.command("kerberos-status")
def kerberos_status(
    state_path: str = typer.Option(
        "eval_results/kerberos_state.json",
        "--state-path",
        help="Path to persisted Kerberos state JSON.",
    ),
    orders_path: str = typer.Option(
        "eval_results/kerberos_orders.json",
        "--orders-path",
        help="Path to persisted Kerberos orders JSON.",
    ),
    tail: int = typer.Option(
        10,
        "--tail",
        min=1,
        help="Number of most recent order records to show.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Show current Kerberos overlay state and recent trade log."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    state = _read_json(Path(state_path)) if Path(state_path).exists() else {}
    orders = _read_json(Path(orders_path)) if Path(orders_path).exists() else []
    if not isinstance(state, dict):
        state = {}
    if not isinstance(orders, list):
        orders = []

    payload = {
        "state_path": str(state_path),
        "orders_path": str(orders_path),
        "state": state,
        "orders_count": int(len(orders)),
        "orders_tail": orders[-int(tail):],
    }

    if output_format == "json":
        print(json_lib.dumps(payload, indent=2))
        return

    summary = Table(title="Kerberos %B Overlay State")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="white")
    summary.add_row("Position Open", str(state.get("position_open", False)))
    summary.add_row("Entry Date", str(state.get("entry_date") or "N/A"))
    summary.add_row("Entry Strike", f"${float(state.get('entry_put_strike', 0.0) or 0.0):.0f}" if state.get("entry_put_strike") else "N/A")
    summary.add_row("Entry Premium", f"${float(state.get('entry_put_premium', 0.0) or 0.0):.2f}" if state.get("entry_put_premium") else "N/A")
    summary.add_row("Expiry Date", str(state.get("entry_expiry_date") or "N/A"))
    summary.add_row("Last Action Date", str(state.get("last_action_date") or "N/A"))
    summary.add_row("Last Updated", str(state.get("last_updated") or "N/A"))
    summary.add_row("Orders Recorded", str(len(orders)))
    console.print(summary)

    recent = orders[-int(tail):]
    orders_table = Table(title=f"Recent Kerberos Trades (last {len(recent)})")
    orders_table.add_column("#", justify="right")
    orders_table.add_column("Timestamp", style="cyan")
    orders_table.add_column("Action", justify="center")
    orders_table.add_column("VXX Spot", justify="right")
    orders_table.add_column("Strike", justify="right")
    orders_table.add_column("Premium", justify="right")
    orders_table.add_column("Exit Value", justify="right")
    orders_table.add_column("P&L", justify="right")
    orders_table.add_column("Return%", justify="right")
    orders_table.add_column("Days", justify="right")
    orders_table.add_column("Reason", style="white")

    for idx, row in enumerate(recent, start=1):
        if not isinstance(row, dict):
            continue
        action = str(row.get("action", "N/A"))
        pnl = float(row.get("pnl_per_contract", 0.0) or 0.0)
        ret = float(row.get("return_on_premium_pct", 0.0) or 0.0)
        pnl_style = "green" if pnl > 0 else ("red" if pnl < 0 else "white")
        orders_table.add_row(
            str(idx),
            str(row.get("timestamp", "N/A"))[:19],
            action,
            f"${float(row.get('vxx_spot', 0.0) or 0.0):.2f}" if action == "OPEN_PUT" else f"${float(row.get('exit_vxx_spot', 0.0) or 0.0):.2f}",
            f"${float(row.get('put_strike', 0.0) or 0.0):.0f}",
            f"${float(row.get('put_premium', 0.0) or 0.0):.2f}",
            f"${float(row.get('exit_put_value', 0.0) or 0.0):.2f}" if action == "CLOSE_PUT" else "-",
            f"[{pnl_style}]{pnl:+.2f}[/{pnl_style}]" if action == "CLOSE_PUT" else "-",
            f"[{pnl_style}]{ret:+.1f}%[/{pnl_style}]" if action == "CLOSE_PUT" else "-",
            str(row.get("hold_days", "-")) if action == "CLOSE_PUT" else "-",
            str(row.get("exit_reason", "-")) if action == "CLOSE_PUT" else "-",
        )
    console.print(orders_table)


@app.command("hedge-evaluate")
def hedge_evaluate(
    rating_id: Optional[str] = typer.Option(
        None,
        "--rating-id",
        help="Optional rating ID used for hedge audit events.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Run one deterministic hedge evaluation cycle and print decision outputs."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    portfolio_snapshot, market_regime, hedge_signal, hedge_decision = run_hedging_cycle(
        rating_id=rating_id
    )
    payload = {
        "evaluated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rating_id": rating_id,
        "portfolio_snapshot": portfolio_snapshot,
        "market_regime": market_regime,
        "hedge_signal": hedge_signal,
        "hedge_decision": hedge_decision,
    }

    if output_format == "json":
        print(json_lib.dumps(payload, indent=2))
        return

    console.print(
        "[green]Hedge evaluation complete[/green] | "
        f"status={hedge_decision.get('status', 'UNKNOWN')} | "
        f"action={hedge_decision.get('action', 'NO_CHANGE')} | "
        f"instrument={hedge_decision.get('instrument', 'N/A')}"
    )
    console.print(
        Markdown(
            format_portfolio_risk_hedge_markdown(
                portfolio_snapshot,
                market_regime,
                hedge_signal,
                hedge_decision,
            )
        )
    )


@app.command("hedge-status")
def hedge_status(
    state_path: str = typer.Option(
        "eval_results/hedge_state.json",
        "--state-path",
        help="Path to persisted hedge state JSON.",
    ),
    orders_path: str = typer.Option(
        "eval_results/hedge_orders.json",
        "--orders-path",
        help="Path to persisted hedge orders JSON.",
    ),
    tail: int = typer.Option(
        10,
        "--tail",
        min=1,
        help="Number of most recent hedge order records to show.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Show current persisted hedge state and recent hedge actions."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    state = _read_json(Path(state_path)) if Path(state_path).exists() else {}
    orders = _read_json(Path(orders_path)) if Path(orders_path).exists() else []
    if not isinstance(state, dict):
        state = {}
    if not isinstance(orders, list):
        orders = []

    payload = {
        "state_path": str(state_path),
        "orders_path": str(orders_path),
        "state": state,
        "orders_count": int(len(orders)),
        "orders_tail": orders[-int(tail) :],
    }

    if output_format == "json":
        print(json_lib.dumps(payload, indent=2))
        return

    summary = Table(title="Hedge State")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="white")
    summary.add_row("Current Hedge %", f"{float(state.get('current_hedge_pct', 0.0) or 0.0):.2f}")
    summary.add_row("Last Rebalance Date", str(state.get("last_rebalance_date") or "N/A"))
    summary.add_row("Last Updated", str(state.get("last_updated") or "N/A"))
    summary.add_row("Orders Recorded", str(len(orders)))
    console.print(summary)

    recent = orders[-int(tail) :]
    orders_table = Table(title=f"Recent Hedge Orders (last {len(recent)})")
    orders_table.add_column("#", justify="right")
    orders_table.add_column("Timestamp", style="cyan")
    orders_table.add_column("Instrument", justify="center")
    orders_table.add_column("Action", justify="center")
    orders_table.add_column("Delta %", justify="right")
    orders_table.add_column("Delta Notional($)", justify="right")
    orders_table.add_column("Reason", style="white")

    for idx, row in enumerate(recent, start=1):
        if not isinstance(row, dict):
            continue
        orders_table.add_row(
            str(idx),
            str(row.get("timestamp", "N/A")),
            str(row.get("instrument", "N/A")),
            str(row.get("action", "N/A")),
            f"{float(row.get('delta_hedge_pct', 0.0) or 0.0):.2f}",
            f"{float(row.get('delta_notional_usd', 0.0) or 0.0):,.2f}",
            str(row.get("reason", "N/A")),
        )
    console.print(orders_table)


