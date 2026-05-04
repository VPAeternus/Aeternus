from cli.common import *  # noqa: F401,F403

@app.command("execute-paper")
def execute_paper(
    plan_path: Optional[Path] = typer.Option(
        None,
        "--plan-path",
        help="Optional explicit portfolio plan path. Defaults to latest.",
    ),
    execution_mode: str = typer.Option(
        str(DEFAULT_CONFIG.get("execution_broker_mode", "paper")),
        "--execution-mode",
        help="Execution adapter mode (paper, live, alpaca-paper, alpaca-live).",
    ),
    slippage_bps: float = typer.Option(
        float(DEFAULT_CONFIG.get("paper_execution_slippage_bps", 0.0)),
        "--slippage-bps",
        min=0.0,
        help="Synthetic fill slippage in basis points for paper fills.",
    ),
    max_gross_exposure_pct: float = typer.Option(
        float(DEFAULT_CONFIG.get("execution_max_gross_exposure_pct", 1.0)),
        "--max-gross-exposure-pct",
        min=0.1,
        help="Pre-trade hard cap for projected gross exposure as fraction of plan capital.",
    ),
    max_single_position_pct: float = typer.Option(
        float(DEFAULT_CONFIG.get("execution_max_single_position_pct", 0.25)),
        "--max-single-position-pct",
        min=0.01,
        max=1.0,
        help="Pre-trade hard cap for projected single-name exposure as fraction of plan capital.",
    ),
    max_open_positions: int = typer.Option(
        int(DEFAULT_CONFIG.get("execution_max_open_positions", 12)),
        "--max-open-positions",
        min=1,
        help="Pre-trade hard cap for projected open position count.",
    ),
    max_new_orders_per_run: int = typer.Option(
        int(DEFAULT_CONFIG.get("execution_max_new_orders_per_run", 12)),
        "--max-new-orders-per-run",
        min=1,
        help="Pre-trade cap on number of new order intents accepted in one execution.",
    ),
    block_short_orders: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_block_short_orders", True)),
        "--block-shorts/--allow-shorts",
        help="Block SELL intents during execution risk checks.",
    ),
    allow_hedge_short_orders: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_allow_hedge_short_orders", True)),
        "--allow-hedge-shorts/--block-hedge-shorts",
        help="Allow SELL intents tagged as HEDGE while other short orders remain blocked.",
    ),
    max_hedge_notional_pct: float = typer.Option(
        float(DEFAULT_CONFIG.get("execution_max_hedge_notional_pct", 1.50)),
        "--max-hedge-notional-pct",
        min=0.0,
        help="Cap projected hedge notional as a fraction of plan capital.",
    ),
    rebalance_to_target: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_rebalance_to_target", True)),
        "--rebalance-to-target/--full-size-intents",
        help="Execute delta-to-target orders against current positions.",
    ),
    min_rebalance_notional_usd: float = typer.Option(
        float(DEFAULT_CONFIG.get("execution_min_rebalance_notional_usd", 100.0)),
        "--min-rebalance-notional-usd",
        min=0.0,
        help="Skip rebalance intents with smaller delta notional than this threshold.",
    ),
    close_missing_positions: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_close_missing_positions", False)),
        "--close-missing-positions/--keep-missing-positions",
        help="When rebalancing, generate close intents for symbols not present in plan.",
    ),
    position_parity_check: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_require_position_parity_for_live", True)),
        "--position-parity-check/--skip-position-parity-check",
        help="For alpaca execution modes, compare broker vs shadow positions before order submission.",
    ),
    position_parity_fail_on_drift: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_block_on_position_drift", True)),
        "--position-parity-fail-on-drift/--position-parity-warn-only",
        help="Block submission when parity check reports drift or parity-check errors.",
    ),
    position_parity_refresh_snapshot: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_position_parity_refresh_snapshot", True)),
        "--position-parity-refresh-snapshot/--position-parity-use-existing-snapshot",
        help="Refresh broker positions snapshot before parity evaluation.",
    ),
    position_parity_qty_tolerance: float = typer.Option(
        float(DEFAULT_CONFIG.get("execution_position_parity_qty_tolerance", 0.0001)),
        "--position-parity-qty-tolerance",
        min=0.0,
        help="Absolute quantity tolerance for parity drift checks.",
    ),
    position_parity_notional_tolerance_usd: float = typer.Option(
        float(DEFAULT_CONFIG.get("execution_position_parity_notional_tolerance_usd", 25.0)),
        "--position-parity-notional-tolerance-usd",
        min=0.0,
        help="Absolute notional tolerance for parity drift checks.",
    ),
    position_parity_snapshot_path: str = typer.Option(
        str(
            DEFAULT_CONFIG.get(
                "live_broker_positions_snapshot_path",
                "eval_results/live_execution/broker_positions_latest.json",
            )
        ),
        "--position-parity-snapshot-path",
        help="Broker positions snapshot path used by parity checks.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Execute a portfolio plan through the configured paper adapter."""
    from tradingagents.dealflow.system_halt import is_hands_off_active
    if is_hands_off_active():
        console.print("[bold red]SYSTEM HALT ACTIVE — aborting. Clear halt before retrying.[/bold red]")
        raise typer.Exit(code=1)

    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    try:
        plan, resolved_plan_path = _load_portfolio_plan(plan_path)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    normalized_mode = str(execution_mode).strip().lower().replace("_", "-")
    orders_path, positions_path = _resolve_execution_paths_for_mode(normalized_mode)

    execution_plan = dict(plan)
    if rebalance_to_target:
        execution_plan = build_rebalance_execution_plan(
            plan=plan,
            positions_path=positions_path,
            min_rebalance_notional_usd=float(min_rebalance_notional_usd),
            close_missing_positions=bool(close_missing_positions),
        )

    risk_check = evaluate_pretrade_risk(
        plan=execution_plan,
        positions_path=positions_path,
        max_gross_exposure_pct=float(max_gross_exposure_pct),
        max_single_position_pct=float(max_single_position_pct),
        max_open_positions=int(max_open_positions),
        max_new_orders_per_run=int(max_new_orders_per_run),
        block_short_orders=bool(block_short_orders),
        max_hedge_notional_pct=float(max_hedge_notional_pct),
        allow_hedge_short_orders=bool(allow_hedge_short_orders),
    )
    parity_report = {
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "execution_mode": normalized_mode,
        "status": "SKIPPED_DISABLED",
        "all_clear": True,
        "drift_count": 0,
        "symbols_compared": 0,
        "drift_symbols": [],
        "total_notional_drift_usd": 0.0,
        "broker_positions_snapshot_path": str(position_parity_snapshot_path),
        "positions_path": str(positions_path),
    }
    parity_blocked = False
    if bool(position_parity_check):
        parity_report = _evaluate_position_parity_gate(
            execution_mode=normalized_mode,
            positions_path=str(positions_path),
            broker_positions_snapshot_path=str(position_parity_snapshot_path),
            refresh_snapshot=bool(position_parity_refresh_snapshot),
            qty_tolerance=float(position_parity_qty_tolerance),
            notional_tolerance_usd=float(position_parity_notional_tolerance_usd),
        )
        parity_status = str(parity_report.get("status", "UNKNOWN")).upper()
        if bool(position_parity_fail_on_drift) and parity_status in {"DRIFT_DETECTED", "ERROR"}:
            parity_blocked = True
            parity_reason = "POSITION_PARITY_DRIFT" if parity_status == "DRIFT_DETECTED" else "POSITION_PARITY_ERROR"
            risk_check = dict(risk_check)
            accepted_before = [
                order
                for order in list(risk_check.get("accepted_orders", []))
                if isinstance(order, dict)
            ]
            rejected_orders = list(risk_check.get("rejected_orders", []))
            for order in accepted_before:
                rejected = dict(order)
                rejected["rejected_reason"] = parity_reason
                rejected["position_parity_status"] = parity_status
                rejected_orders.append(rejected)
            reason_counts = dict(risk_check.get("rejected_reason_counts", {}))
            reason_counts[parity_reason] = int(reason_counts.get(parity_reason, 0)) + int(
                max(1, len(accepted_before))
            )
            blockers = list(risk_check.get("blockers", []))
            blockers.append(
                f"{parity_reason}: status={parity_status} drift_count={int(parity_report.get('drift_count', 0))}"
            )
            risk_check["blockers"] = blockers
            risk_check["status"] = "REJECTED"
            risk_check["accepted_orders"] = []
            risk_check["accepted_count"] = 0
            risk_check["rejected_orders"] = rejected_orders
            risk_check["rejected_count"] = int(len(rejected_orders))
            risk_check["rejected_reason_counts"] = reason_counts
            risk_check["position_parity_gate"] = {
                "status": parity_status,
                "blocked_submission": True,
                "drift_count": int(parity_report.get("drift_count", 0)),
                "positions_drift_path": str(parity_report.get("positions_drift_path", "")),
            }

    risk_check_path = _persist_pretrade_risk(risk_check)

    execution_plan = dict(execution_plan)
    execution_plan["orders"] = list(risk_check.get("accepted_orders", []))

    if execution_plan["orders"]:
        try:
            result = execute_plan_with_adapter(
                plan=execution_plan,
                execution_mode=normalized_mode,
                orders_path=orders_path,
                positions_path=positions_path,
                fill_price_slippage_bps=float(slippage_bps),
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
    else:
        result = {
            "plan_id": plan.get("plan_id"),
            "date": plan.get("date"),
            "execution_mode": str(execution_mode).strip().lower(),
            "submitted_orders": 0,
            "executed_orders": 0,
            "skipped_duplicate_orders": 0,
            "orders_path": orders_path,
            "positions_path": positions_path,
            "skipped_duplicate_intent_ids": [],
            "orders": [],
        }

    result["plan_path"] = str(resolved_plan_path)
    result["execution_mode"] = normalized_mode
    result["slippage_bps"] = float(slippage_bps)
    result["rebalance"] = dict(execution_plan.get("rebalance", {}))
    result["risk_check"] = {
        "status": str(risk_check.get("status", "UNKNOWN")),
        "accepted_count": int(risk_check.get("accepted_count", 0) or 0),
        "rejected_count": int(risk_check.get("rejected_count", 0) or 0),
        "orders_considered": int(risk_check.get("orders_considered", 0) or 0),
        "rejected_reason_counts": dict(risk_check.get("rejected_reason_counts", {})),
    }
    result["risk_check_path"] = str(risk_check_path)
    result["position_parity"] = dict(parity_report)
    result["position_parity"]["blocked_submission"] = bool(parity_blocked)
    result["hedge_sync"] = {"state_updated": False, "orders_seen": 0}

    try:
        hedge_orders = [
            order
            for order in result.get("orders", [])
            if isinstance(order, dict)
            and str(order.get("intent_category") or "").upper().strip() == "HEDGE"
        ]
        result["hedge_sync"]["orders_seen"] = int(len(hedge_orders))
        if hedge_orders:
            hedge_ctx = plan.get("hedge_context", {}) if isinstance(plan, dict) else {}
            signal = hedge_ctx.get("signal", {}) if isinstance(hedge_ctx, dict) else {}
            decision = hedge_ctx.get("decision", {}) if isinstance(hedge_ctx, dict) else {}
            portfolio_snapshot = (
                hedge_ctx.get("portfolio_snapshot", {}) if isinstance(hedge_ctx, dict) else {}
            )
            if (
                isinstance(signal, dict)
                and isinstance(decision, dict)
                and isinstance(portfolio_snapshot, dict)
                and str(decision.get("status") or "").upper() == "EXECUTED"
                and float(portfolio_snapshot.get("gross_exposure_usd", 0.0) or 0.0) > 0.0
            ):
                hedge_order_record = AdaptiveHedgeEngine().persist_state_and_orders(
                    signal=signal,
                    decision=decision,
                    portfolio_snapshot=portfolio_snapshot,
                )
                result["hedge_sync"] = {
                    "state_updated": True,
                    "orders_seen": int(len(hedge_orders)),
                    "recorded_order": hedge_order_record or {},
                }
    except Exception as exc:
        result["hedge_sync"] = {
            "state_updated": False,
            "orders_seen": int(result.get("hedge_sync", {}).get("orders_seen", 0) or 0),
            "error": str(exc),
        }

    try:
        audit = RatingAuditLog()
        audit.log_event(
            "LIVE_POSITION_PARITY_EVALUATED",
            str(plan.get("plan_id") or "position-parity"),
            {
                "status": str(parity_report.get("status", "UNKNOWN")),
                "blocked_submission": bool(parity_blocked),
                "drift_count": int(parity_report.get("drift_count", 0)),
                "drift_symbols": list(parity_report.get("drift_symbols", [])),
                "total_notional_drift_usd": float(parity_report.get("total_notional_drift_usd", 0.0)),
                "positions_drift_path": str(parity_report.get("positions_drift_path", "")),
                "broker_positions_snapshot_path": str(parity_report.get("broker_positions_snapshot_path", "")),
            },
        )
        if parity_blocked:
            audit.log_event(
                "PAPER_EXECUTION_BLOCKED_POSITION_PARITY",
                str(plan.get("plan_id") or "position-parity"),
                {
                    "status": str(parity_report.get("status", "UNKNOWN")),
                    "drift_count": int(parity_report.get("drift_count", 0)),
                    "drift_symbols": list(parity_report.get("drift_symbols", [])),
                    "positions_drift_path": str(parity_report.get("positions_drift_path", "")),
                },
            )
        audit.log_event(
            "PAPER_PRETRADE_RISK_CHECK",
            str(plan.get("plan_id") or "paper-risk-check"),
            {
                "risk_check_path": str(risk_check_path),
                "status": str(risk_check.get("status", "UNKNOWN")),
                "accepted_count": int(risk_check.get("accepted_count", 0) or 0),
                "rejected_count": int(risk_check.get("rejected_count", 0) or 0),
                "rejected_reason_counts": dict(risk_check.get("rejected_reason_counts", {})),
                "rebalance": dict(execution_plan.get("rebalance", {})),
            },
        )
        for rejected in risk_check.get("rejected_orders", []):
            if not isinstance(rejected, dict):
                continue
            rejected_intent_category = str(rejected.get("intent_category") or "").upper().strip()
            rejected_event_type = (
                "HEDGE_ORDER_REJECTED_RISK"
                if rejected_intent_category == "HEDGE"
                else "PAPER_ORDER_REJECTED_RISK"
            )
            audit.log_event(
                rejected_event_type,
                str(rejected.get("order_intent_id") or plan.get("plan_id") or "paper-risk-reject"),
                rejected,
            )
        for order in result.get("orders", []):
            if not isinstance(order, dict):
                continue
            intent_category = str(order.get("intent_category") or "").upper().strip()
            order_status = str(order.get("status") or "").upper().strip()
            if intent_category == "HEDGE":
                event_type = (
                    "HEDGE_ORDER_EXECUTED"
                    if order_status in {"FILLED", "PARTIAL", "PARTIALLY_FILLED"}
                    else "HEDGE_ORDER_SUBMITTED"
                )
            else:
                event_type = "PAPER_ORDER_EXECUTED"
            audit.log_event(
                event_type,
                str(order.get("rating_id") or result.get("plan_id") or "paper-order"),
                order,
            )
        if int(result.get("skipped_duplicate_orders", 0) or 0) > 0:
            audit.log_event(
                "PAPER_ORDER_SKIPPED_DUPLICATE",
                str(result.get("plan_id") or "paper-order"),
                {
                    "count": int(result.get("skipped_duplicate_orders", 0) or 0),
                    "intent_ids": result.get("skipped_duplicate_intent_ids", []),
                    "plan_path": str(resolved_plan_path),
                },
            )
    except Exception:
        pass


    if output_format == "json":
        print(json_lib.dumps(result, indent=2))
        return

    console.print(
        f"[green]Execution complete[/green] | executed={result.get('executed_orders', 0)} | "
        f"submitted={result.get('submitted_orders', 0)} | "
        f"duplicates_skipped={result.get('skipped_duplicate_orders', 0)}"
    )
    console.print(
        f"[cyan]Risk check:[/cyan] status={result['risk_check'].get('status')} | "
        f"accepted={result['risk_check'].get('accepted_count')} | "
        f"rejected={result['risk_check'].get('rejected_count')}"
    )
    console.print(
        "[cyan]Position parity:[/cyan] "
        f"status={result['position_parity'].get('status', 'UNKNOWN')} | "
        f"drift={result['position_parity'].get('drift_count', 0)} | "
        f"blocked={bool(result['position_parity'].get('blocked_submission'))}"
    )
    console.print(f"[cyan]Plan path:[/cyan] {resolved_plan_path}")
    console.print(f"[cyan]Risk check path:[/cyan] {risk_check_path}")
    _render_executed_orders_table(result)


@app.command("pull-broker-orders")
def pull_broker_orders(
    broker: str = typer.Option(
        "alpaca",
        "--broker",
        help="Broker source (currently: alpaca).",
    ),
    mode: str = typer.Option(
        "alpaca-paper",
        "--mode",
        help="Broker mode for API source (alpaca-paper or alpaca-live).",
    ),
    status: str = typer.Option(
        "all",
        "--status",
        help="Order status filter (all|open|closed).",
    ),
    limit: int = typer.Option(
        500,
        "--limit",
        min=1,
        max=500,
        help="Maximum number of broker orders to fetch.",
    ),
    out_path: str = typer.Option(
        str(
            DEFAULT_CONFIG.get(
                "live_broker_orders_snapshot_path",
                "eval_results/live_execution/broker_orders_latest.json",
            )
        ),
        "--out-path",
        help="Snapshot output path used by reconciliation.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Fetch broker order snapshot for reconciliation."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    source = str(broker or "").strip().lower()
    if source != "alpaca":
        console.print(f"[red]Unsupported broker:[/red] {broker}")
        raise typer.Exit(1)

    try:
        snapshot = fetch_alpaca_orders_snapshot(
            out_path=str(out_path),
            mode=str(mode),
            status=str(status),
            limit=int(limit),
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    try:
        RatingAuditLog().log_event(
            "LIVE_BROKER_SNAPSHOT_FETCHED",
            str(snapshot.get("fetched_at") or _today_str()),
            {
                "broker": source,
                "mode": str(snapshot.get("mode")),
                "orders": len(snapshot.get("orders", [])),
                "status": str(snapshot.get("status", "all")),
                "out_path": str(out_path),
            },
        )
    except Exception:
        pass

    payload = {
        "broker": source,
        "mode": snapshot.get("mode"),
        "fetched_at": snapshot.get("fetched_at"),
        "status": snapshot.get("status"),
        "limit": snapshot.get("limit"),
        "orders": len(snapshot.get("orders", [])),
        "snapshot_path": str(out_path),
    }
    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
        return

    console.print(
        f"[green]Broker snapshot fetched[/green] | broker={source} | "
        f"orders={payload['orders']} | mode={payload.get('mode')}"
    )
    console.print(f"[cyan]Snapshot path:[/cyan] {out_path}")


@app.command("pull-broker-positions")
def pull_broker_positions(
    broker: str = typer.Option(
        "alpaca",
        "--broker",
        help="Broker source (currently: alpaca).",
    ),
    mode: str = typer.Option(
        "alpaca-paper",
        "--mode",
        help="Broker mode for API source (alpaca-paper or alpaca-live).",
    ),
    out_path: str = typer.Option(
        str(
            DEFAULT_CONFIG.get(
                "live_broker_positions_snapshot_path",
                "eval_results/live_execution/broker_positions_latest.json",
            )
        ),
        "--out-path",
        help="Position snapshot output path.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Fetch broker position snapshot for side-by-side diagnostics."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    source = str(broker or "").strip().lower()
    if source != "alpaca":
        console.print(f"[red]Unsupported broker:[/red] {broker}")
        raise typer.Exit(1)

    try:
        snapshot = fetch_alpaca_positions_snapshot(
            out_path=str(out_path),
            mode=str(mode),
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    try:
        RatingAuditLog().log_event(
            "LIVE_BROKER_POSITIONS_SNAPSHOT_FETCHED",
            str(snapshot.get("fetched_at") or _today_str()),
            {
                "broker": source,
                "mode": str(snapshot.get("mode")),
                "positions": len(snapshot.get("positions", [])),
                "out_path": str(out_path),
            },
        )
    except Exception:
        pass

    payload = {
        "broker": source,
        "mode": snapshot.get("mode"),
        "fetched_at": snapshot.get("fetched_at"),
        "positions": len(snapshot.get("positions", [])),
        "snapshot_path": str(out_path),
    }
    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
        return

    console.print(
        f"[green]Broker positions snapshot fetched[/green] | broker={source} | "
        f"positions={payload['positions']} | mode={payload.get('mode')}"
    )
    console.print(f"[cyan]Snapshot path:[/cyan] {out_path}")


@app.command("positions-drift")
def positions_drift(
    broker: str = typer.Option(
        "alpaca",
        "--broker",
        help="Broker source (currently: alpaca).",
    ),
    mode: str = typer.Option(
        "alpaca-paper",
        "--mode",
        help="Broker mode for API source (alpaca-paper or alpaca-live).",
    ),
    broker_positions_snapshot_path: str = typer.Option(
        str(
            DEFAULT_CONFIG.get(
                "live_broker_positions_snapshot_path",
                "eval_results/live_execution/broker_positions_latest.json",
            )
        ),
        "--broker-positions-snapshot-path",
        help="Broker positions snapshot path.",
    ),
    positions_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_positions_shadow_path", "eval_results/live_execution/positions_shadow.json")),
        "--positions-path",
        help="Shadow positions path used by reconciliation.",
    ),
    refresh_snapshot: bool = typer.Option(
        True,
        "--refresh-snapshot/--no-refresh-snapshot",
        help="Refresh broker positions snapshot before drift comparison.",
    ),
    qty_tolerance: float = typer.Option(
        0.0001,
        "--qty-tolerance",
        min=0.0,
        help="Absolute quantity tolerance before symbol is flagged as drift.",
    ),
    notional_tolerance_usd: float = typer.Option(
        25.0,
        "--notional-tolerance-usd",
        min=0.0,
        help="Absolute notional drift tolerance before symbol is flagged as drift.",
    ),
    fail_on_drift: bool = typer.Option(
        False,
        "--fail-on-drift/--allow-drift",
        help="Return non-zero exit code when any symbol drift is detected.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Compare broker positions vs live shadow ledger and report per-symbol drift."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    source = str(broker or "").strip().lower()
    if source != "alpaca":
        console.print(f"[red]Unsupported broker:[/red] {broker}")
        raise typer.Exit(1)

    snapshot_path = Path(str(broker_positions_snapshot_path))
    if refresh_snapshot:
        try:
            fetch_alpaca_positions_snapshot(
                out_path=str(snapshot_path),
                mode=str(mode),
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

    if not snapshot_path.exists():
        console.print(f"[red]Broker positions snapshot not found:[/red] {snapshot_path}")
        raise typer.Exit(1)

    broker_snapshot = _read_json(snapshot_path)
    shadow_payload = load_open_positions(positions_path=str(positions_path))
    report = _build_positions_drift_report(
        broker_snapshot=broker_snapshot,
        shadow_positions_payload=shadow_payload,
        qty_tolerance=float(qty_tolerance),
        notional_tolerance_usd=float(notional_tolerance_usd),
    )
    report["broker_positions_snapshot_path"] = str(snapshot_path)
    report["positions_path"] = str(positions_path)
    drift_path = _persist_positions_drift(report)
    report["positions_drift_path"] = str(drift_path)

    try:
        RatingAuditLog().log_event(
            "LIVE_POSITIONS_DRIFT_EVALUATED",
            str(report.get("generated_at") or _today_str()),
            {
                "broker": source,
                "mode": str(mode),
                "symbols_compared": int(report.get("symbols_compared", 0)),
                "drift_count": int(report.get("drift_count", 0)),
                "total_notional_drift_usd": float(report.get("total_notional_drift_usd", 0.0)),
                "positions_drift_path": str(drift_path),
            },
        )
    except Exception:
        pass

    if output_format == "json":
        typer.echo(json_lib.dumps(report, indent=2))
    else:
        _render_positions_drift_table(report)
        console.print(f"[cyan]Broker snapshot:[/cyan] {snapshot_path}")
        console.print(f"[cyan]Shadow positions:[/cyan] {positions_path}")
        console.print(f"[cyan]Drift artifact:[/cyan] {drift_path}")

    if bool(fail_on_drift) and int(report.get("drift_count", 0)) > 0:
        raise typer.Exit(2)


@app.command("reconcile-execution")
def reconcile_execution(
    broker_snapshot_path: Optional[Path] = typer.Option(
        None,
        "--broker-snapshot-path",
        help="Path to broker order-status snapshot JSON.",
    ),
    outbox_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_execution_outbox_path", "eval_results/live_execution/outbox.json")),
        "--outbox-path",
        help="Live execution outbox path.",
    ),
    positions_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_positions_shadow_path", "eval_results/live_execution/positions_shadow.json")),
        "--positions-path",
        help="Shadow positions path updated by reconciled fills.",
    ),
    fills_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_execution_fills_path", "eval_results/live_execution/fills.json")),
        "--fills-path",
        help="Path for persisted live fill events.",
    ),
    closed_trades_path: str = typer.Option(
        str(
            DEFAULT_CONFIG.get(
                "live_execution_closed_trades_path",
                "eval_results/live_execution/closed_trades.json",
            )
        ),
        "--closed-trades-path",
        help="Path for persisted live closed-trade/outcome events.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Reconcile live broker statuses/fills into local ledgers."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    snapshot_default = str(
        DEFAULT_CONFIG.get(
            "live_broker_orders_snapshot_path",
            "eval_results/live_execution/broker_orders_latest.json",
        )
    )
    snapshot_path = Path(broker_snapshot_path) if broker_snapshot_path else Path(snapshot_default)
    if not snapshot_path.exists():
        console.print(f"[red]Broker snapshot not found:[/red] {snapshot_path}")
        raise typer.Exit(1)

    broker_snapshot = _read_json(snapshot_path)
    report = reconcile_live_execution(
        broker_snapshot=broker_snapshot,
        outbox_path=str(outbox_path),
        positions_path=str(positions_path),
        fills_path=str(fills_path),
        closed_trades_path=str(closed_trades_path),
        track_record=TrackRecord(),
    )
    report["date"] = _today_str()
    report["broker_snapshot_path"] = str(snapshot_path)
    reconciliation_path = _persist_execution_reconciliation(report)
    report["reconciliation_path"] = str(reconciliation_path)

    try:
        audit = RatingAuditLog()
        audit.log_event(
            "LIVE_RECONCILIATION_COMPLETED",
            str(report.get("date") or "live-reconcile"),
            {
                "reconciliation_path": str(reconciliation_path),
                "broker_snapshot_path": str(snapshot_path),
                "matched_orders": int(report.get("matched_orders", 0)),
                "unmatched_orders": int(report.get("unmatched_orders", 0)),
                "status_updates": int(report.get("status_updates", 0)),
                "fills_applied": int(report.get("fills_applied", 0)),
                "filled_notional_usd": float(report.get("filled_notional_usd", 0.0)),
                "closed_positions": int(report.get("closed_positions", 0)),
                "outcomes_updated": int(report.get("outcomes_updated", 0)),
            },
        )
        for order_intent_id in report.get("status_updated_order_intent_ids", []):
            audit.log_event(
                "LIVE_ORDER_RECONCILED",
                str(order_intent_id),
                {
                    "order_intent_id": str(order_intent_id),
                    "reconciliation_path": str(reconciliation_path),
                },
            )
        for fill in report.get("fills", []):
            if not isinstance(fill, dict):
                continue
            audit.log_event(
                "LIVE_FILL_APPLIED",
                str(fill.get("order_intent_id") or fill.get("rating_id") or report.get("date")),
                fill,
            )
        for close_event in report.get("closed_trades", []):
            if not isinstance(close_event, dict):
                continue
            audit.log_event(
                "LIVE_POSITION_CLOSED",
                str(close_event.get("close_id") or close_event.get("symbol") or report.get("date")),
                close_event,
            )
    except Exception:
        pass

    if output_format == "json":
        typer.echo(json_lib.dumps(report, indent=2))
        return

    console.print(
        f"[green]Execution reconciliation complete[/green] | "
        f"matched={report.get('matched_orders', 0)} | "
        f"fills_applied={report.get('fills_applied', 0)} | "
        f"status_updates={report.get('status_updates', 0)} | "
        f"closed_positions={report.get('closed_positions', 0)}"
    )
    console.print(f"[cyan]Broker snapshot:[/cyan] {snapshot_path}")
    console.print(f"[cyan]Reconciliation path:[/cyan] {reconciliation_path}")
    _render_execution_reconciliation_table(report)


@app.command("execution-sync")
def execution_sync(
    broker: str = typer.Option(
        "alpaca",
        "--broker",
        help="Broker source (currently: alpaca).",
    ),
    mode: str = typer.Option(
        "alpaca-paper",
        "--mode",
        help="Broker mode for API source (alpaca-paper or alpaca-live).",
    ),
    status: str = typer.Option(
        "all",
        "--status",
        help="Order status filter (all|open|closed).",
    ),
    limit: int = typer.Option(
        500,
        "--limit",
        min=1,
        max=500,
        help="Maximum number of broker orders to fetch.",
    ),
    snapshot_out_path: str = typer.Option(
        str(
            DEFAULT_CONFIG.get(
                "live_broker_orders_snapshot_path",
                "eval_results/live_execution/broker_orders_latest.json",
            )
        ),
        "--snapshot-out-path",
        help="Broker snapshot output path.",
    ),
    outbox_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_execution_outbox_path", "eval_results/live_execution/outbox.json")),
        "--outbox-path",
        help="Live execution outbox path.",
    ),
    positions_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_positions_shadow_path", "eval_results/live_execution/positions_shadow.json")),
        "--positions-path",
        help="Shadow positions path updated by reconciled fills and mark refresh.",
    ),
    fills_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_execution_fills_path", "eval_results/live_execution/fills.json")),
        "--fills-path",
        help="Path for persisted live fill events.",
    ),
    closed_trades_path: str = typer.Option(
        str(
            DEFAULT_CONFIG.get(
                "live_execution_closed_trades_path",
                "eval_results/live_execution/closed_trades.json",
            )
        ),
        "--closed-trades-path",
        help="Path for persisted live closed-trade/outcome events.",
    ),
    broker_positions_snapshot_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_broker_positions_snapshot_path", "eval_results/live_execution/broker_positions_latest.json")),
        "--broker-positions-snapshot-path",
        help="Broker positions snapshot path used for optional shadow-sync.",
    ),
    manage_open_orders: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_sync_manage_open_orders", False)),
        "--manage-open-orders/--skip-manage-open-orders",
        help="Run stale open-order management before readiness checks.",
    ),
    manage_open_orders_apply: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_sync_manage_open_orders_apply", False)),
        "--manage-open-orders-apply/--manage-open-orders-dry-run",
        help="Apply stale open-order cancellations/replacements during sync.",
    ),
    open_orders_max_age_minutes: int = typer.Option(
        int(DEFAULT_CONFIG.get("execution_open_orders_max_age_minutes", 90)),
        "--open-orders-max-age-minutes",
        min=1,
        help="Stale age threshold used by open-order manager.",
    ),
    open_orders_replace_stale: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_open_orders_replace_stale", False)),
        "--open-orders-replace-stale/--open-orders-cancel-only",
        help="Replace stale orders after cancel when retry budget allows.",
    ),
    open_orders_replacement_order_type: str = typer.Option(
        str(DEFAULT_CONFIG.get("execution_open_orders_replacement_order_type", "market")),
        "--open-orders-replacement-order-type",
        help="Replacement order type for stale-order manager (market|limit).",
    ),
    open_orders_limit_price_offset_bps: float = typer.Option(
        float(DEFAULT_CONFIG.get("execution_open_orders_limit_price_offset_bps", 10.0)),
        "--open-orders-limit-price-offset-bps",
        min=0.0,
        help="Limit replacement offset for stale-order manager (bps).",
    ),
    open_orders_max_retries_per_symbol_per_day: int = typer.Option(
        int(DEFAULT_CONFIG.get("execution_open_orders_max_retries_per_symbol_per_day", 2)),
        "--open-orders-max-retries-per-symbol-per-day",
        min=0,
        help="Maximum stale-order replacement retries per symbol per day.",
    ),
    sync_shadow_positions: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_sync_sync_shadow_positions", False)),
        "--sync-shadow-positions/--skip-shadow-positions-sync",
        help="Sync shadow positions from broker positions before readiness checks.",
    ),
    sync_shadow_positions_apply: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_sync_sync_shadow_positions_apply", False)),
        "--sync-shadow-positions-apply/--sync-shadow-positions-dry-run",
        help="Apply broker->shadow position sync changes during sync.",
    ),
    sync_shadow_positions_drop_missing: bool = typer.Option(
        False,
        "--sync-shadow-positions-drop-missing/--sync-shadow-positions-keep-missing",
        help="Drop shadow symbols absent from broker snapshot when syncing.",
    ),
    auto_remediate_readiness: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_sync_auto_remediate_readiness", True)),
        "--auto-remediate-readiness/--no-auto-remediate-readiness",
        help="When readiness is blocked, auto-run stale-order and drift remediation then re-check readiness.",
    ),
    auto_remediate_drop_missing: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_sync_auto_remediate_drop_missing", True)),
        "--auto-remediate-drop-missing/--auto-remediate-keep-missing",
        help="When auto-remediating drift, drop shadow symbols missing from broker positions.",
    ),
    apply_exits: bool = typer.Option(
        False,
        "--apply-exits/--skip-exits",
        help="Generate and submit deterministic exit orders after sync cycle.",
    ),
    require_ready: bool = typer.Option(
        True,
        "--require-ready/--skip-ready-check",
        help="Require execution-readiness pass before submitting exit orders.",
    ),
    min_position_notional_usd: float = typer.Option(
        float(DEFAULT_CONFIG.get("execution_exit_min_position_notional_usd", 250.0)),
        "--min-position-notional-usd",
        min=0.0,
        help="Skip exit generation for positions below this notional.",
    ),
    max_exit_orders_per_run: int = typer.Option(
        int(DEFAULT_CONFIG.get("execution_exit_max_orders_per_run", 6)),
        "--max-exit-orders-per-run",
        min=1,
        help="Maximum number of exit orders generated per cycle.",
    ),
    max_stale_submitted_minutes: int = typer.Option(
        int(DEFAULT_CONFIG.get("execution_readiness_max_stale_submitted_minutes", 180)),
        "--max-stale-submitted-minutes",
        min=1,
        help="Readiness threshold for pending order age.",
    ),
    max_unmatched_open_orders: int = typer.Option(
        int(DEFAULT_CONFIG.get("execution_readiness_max_unmatched_open_orders", 10)),
        "--max-unmatched-open-orders",
        min=0,
        help="Readiness threshold for unmatched pending orders.",
    ),
    max_position_drift_notional_usd: float = typer.Option(
        float(DEFAULT_CONFIG.get("execution_readiness_max_position_drift_notional_usd", 2500.0)),
        "--max-position-drift-notional-usd",
        min=0.0,
        help="Readiness threshold for shadow vs broker position drift notional.",
    ),
    min_buying_power_usd: float = typer.Option(
        float(DEFAULT_CONFIG.get("execution_readiness_min_buying_power_usd", 1.0)),
        "--min-buying-power-usd",
        min=0.0,
        help="Readiness threshold for broker buying power.",
    ),
    once: bool = typer.Option(
        True,
        "--once/--loop",
        help="Run one sync cycle or run continuously in a loop.",
    ),
    interval_sec: int = typer.Option(
        300,
        "--interval-sec",
        min=5,
        help="Loop interval in seconds when --loop is used.",
    ),
    max_loops: int = typer.Option(
        0,
        "--max-loops",
        min=0,
        help="Optional maximum loop count in --loop mode (0 means run indefinitely).",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Run broker sync loop with optional readiness gate and exit-order management."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)
    replacement_order_type = str(open_orders_replacement_order_type or "market").strip().lower()
    if replacement_order_type not in {"market", "limit"}:
        console.print("[red]Error: open-orders-replacement-order-type must be market or limit[/red]")
        raise typer.Exit(1)

    cycle = 0
    while True:
        cycle += 1
        try:
            report = _run_execution_sync_cycle(
                broker=str(broker),
                mode=str(mode),
                status=str(status),
                limit=int(limit),
                snapshot_out_path=str(snapshot_out_path),
                outbox_path=str(outbox_path),
                positions_path=str(positions_path),
                fills_path=str(fills_path),
                closed_trades_path=str(closed_trades_path),
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        report["cycle"] = int(cycle)
        report["loop_mode"] = not bool(once)
        refresh = report.get("position_refresh", {})
        open_orders_report = None
        shadow_sync_report = None

        if manage_open_orders:
            try:
                open_orders_report = _run_manage_open_orders_once(
                    broker=str(broker),
                    mode=str(mode),
                    outbox_path=str(outbox_path),
                    broker_snapshot_path=str(snapshot_out_path),
                    refresh_snapshot=False,
                    max_age_minutes=int(open_orders_max_age_minutes),
                    replace_stale=bool(open_orders_replace_stale),
                    replacement_order_type=replacement_order_type,
                    limit_price_offset_bps=float(open_orders_limit_price_offset_bps),
                    max_retries_per_symbol_per_day=int(open_orders_max_retries_per_symbol_per_day),
                    apply_changes=bool(manage_open_orders_apply),
                )
                management_path = _persist_open_orders_management(open_orders_report)
                open_orders_report["open_orders_management_path"] = str(management_path)
                report["open_orders_management"] = open_orders_report
                if bool(manage_open_orders_apply):
                    try:
                        fetch_alpaca_orders_snapshot(
                            out_path=str(snapshot_out_path),
                            mode=str(mode),
                            status=str(status),
                            limit=int(limit),
                        )
                    except Exception:
                        pass
            except Exception as exc:
                open_orders_report = {
                    "date": _today_str(),
                    "error": str(exc),
                    "stale_candidates_count": 0,
                    "canceled_count": 0,
                    "replaced_count": 0,
                    "errors_count": 1,
                }
                report["open_orders_management"] = open_orders_report

        if sync_shadow_positions:
            try:
                shadow_sync_report = _run_sync_positions_from_broker_once(
                    broker=str(broker),
                    mode=str(mode),
                    broker_positions_snapshot_path=str(broker_positions_snapshot_path),
                    positions_path=str(positions_path),
                    refresh_snapshot=True,
                    drop_missing=bool(sync_shadow_positions_drop_missing),
                    apply_changes=bool(sync_shadow_positions_apply),
                )
                positions_sync_path = _persist_positions_sync(shadow_sync_report)
                shadow_sync_report["positions_sync_path"] = str(positions_sync_path)
                report["positions_sync"] = shadow_sync_report
            except Exception as exc:
                shadow_sync_report = {
                    "date": _today_str(),
                    "error": str(exc),
                    "added_count": 0,
                    "updated_count": 0,
                    "removed_count": 0,
                }
                report["positions_sync"] = shadow_sync_report

        readiness_report = evaluate_execution_readiness(
            broker=str(broker),
            mode=str(mode),
            outbox_path=str(outbox_path),
            positions_path=str(positions_path),
            snapshot_path=str(snapshot_out_path),
            max_stale_submitted_minutes=int(max_stale_submitted_minutes),
            max_unmatched_open_orders=int(max_unmatched_open_orders),
            max_position_drift_notional_usd=float(max_position_drift_notional_usd),
            min_buying_power_usd=float(min_buying_power_usd),
        )
        readiness_report["date"] = _today_str()
        readiness_path = _persist_execution_readiness(readiness_report)
        readiness_report["execution_readiness_path"] = str(readiness_path)
        report["execution_readiness"] = readiness_report

        remediation_report = {
            "attempted": False,
            "actions": [],
            "errors": [],
            "final_overall_ready": bool(readiness_report.get("overall_ready")),
        }
        if require_ready and auto_remediate_readiness and not bool(readiness_report.get("overall_ready")):
            checks = readiness_report.get("checks", {})
            stale_check = checks.get("stale_pending_orders", {}) if isinstance(checks, dict) else {}
            open_match_check = checks.get("open_order_match", {}) if isinstance(checks, dict) else {}
            drift_check = checks.get("position_drift", {}) if isinstance(checks, dict) else {}
            stale_blocked = bool(isinstance(stale_check, dict) and stale_check.get("pass") is False)
            unmatched_blocked = bool(
                isinstance(open_match_check, dict) and open_match_check.get("pass") is False
            )
            drift_blocked = bool(isinstance(drift_check, dict) and drift_check.get("pass") is False)
            remediation_report["attempted"] = bool(stale_blocked or unmatched_blocked or drift_blocked)

            if (stale_blocked or unmatched_blocked) and not manage_open_orders:
                try:
                    auto_open_orders = _run_manage_open_orders_once(
                        broker=str(broker),
                        mode=str(mode),
                        outbox_path=str(outbox_path),
                        broker_snapshot_path=str(snapshot_out_path),
                        refresh_snapshot=False,
                        max_age_minutes=int(open_orders_max_age_minutes),
                        replace_stale=bool(open_orders_replace_stale),
                        replacement_order_type=replacement_order_type,
                        limit_price_offset_bps=float(open_orders_limit_price_offset_bps),
                        max_retries_per_symbol_per_day=int(open_orders_max_retries_per_symbol_per_day),
                        apply_changes=True,
                    )
                    auto_management_path = _persist_open_orders_management(auto_open_orders)
                    auto_open_orders["open_orders_management_path"] = str(auto_management_path)
                    report["open_orders_management"] = auto_open_orders
                    open_orders_report = auto_open_orders
                    remediation_report["actions"].append("MANAGE_OPEN_ORDERS_APPLY")
                    fetch_alpaca_orders_snapshot(
                        out_path=str(snapshot_out_path),
                        mode=str(mode),
                        status=str(status),
                        limit=int(limit),
                    )
                except Exception as exc:
                    remediation_report["errors"].append(f"MANAGE_OPEN_ORDERS_FAILED: {exc}")

            if drift_blocked and not sync_shadow_positions:
                try:
                    auto_shadow_sync = _run_sync_positions_from_broker_once(
                        broker=str(broker),
                        mode=str(mode),
                        broker_positions_snapshot_path=str(broker_positions_snapshot_path),
                        positions_path=str(positions_path),
                        refresh_snapshot=True,
                        drop_missing=bool(auto_remediate_drop_missing),
                        apply_changes=True,
                    )
                    auto_sync_path = _persist_positions_sync(auto_shadow_sync)
                    auto_shadow_sync["positions_sync_path"] = str(auto_sync_path)
                    report["positions_sync"] = auto_shadow_sync
                    shadow_sync_report = auto_shadow_sync
                    remediation_report["actions"].append("SYNC_SHADOW_POSITIONS_APPLY")
                except Exception as exc:
                    remediation_report["errors"].append(f"SYNC_SHADOW_POSITIONS_FAILED: {exc}")

            if remediation_report["actions"]:
                readiness_report = evaluate_execution_readiness(
                    broker=str(broker),
                    mode=str(mode),
                    outbox_path=str(outbox_path),
                    positions_path=str(positions_path),
                    snapshot_path=str(snapshot_out_path),
                    max_stale_submitted_minutes=int(max_stale_submitted_minutes),
                    max_unmatched_open_orders=int(max_unmatched_open_orders),
                    max_position_drift_notional_usd=float(max_position_drift_notional_usd),
                    min_buying_power_usd=float(min_buying_power_usd),
                )
                readiness_report["date"] = _today_str()
                readiness_path = _persist_execution_readiness(readiness_report)
                readiness_report["execution_readiness_path"] = str(readiness_path)
                report["execution_readiness"] = readiness_report
                remediation_report["final_overall_ready"] = bool(readiness_report.get("overall_ready"))

            report["readiness_remediation"] = remediation_report

        try:
            RatingAuditLog().log_event(
                "EXECUTION_READINESS_EVALUATED",
                str(readiness_report.get("date") or _today_str()),
                {
                    "overall_ready": bool(readiness_report.get("overall_ready")),
                    "broker": str(broker),
                    "mode": str(mode),
                    "execution_readiness_path": str(readiness_path),
                    "blockers": list(readiness_report.get("blockers", [])),
                },
            )
        except Exception:
            pass

        exit_management = None
        if apply_exits:
            if require_ready and not bool(readiness_report.get("overall_ready")):
                exit_management = {
                    "date": _today_str(),
                    "submitted": False,
                    "blocked": True,
                    "reason": "EXECUTION_READINESS_FAILED",
                    "blockers": list(readiness_report.get("blockers", [])),
                    "orders_generated": 0,
                    "orders_submitted": 0,
                    "signals_generated": 0,
                }
            else:
                exit_management = _run_manage_exits_once(
                    execution_mode=str(mode),
                    orders_path=str(outbox_path),
                    positions_path=str(positions_path),
                    stop_loss_pct=0.0,
                    take_profit_pct=0.0,
                    max_hold_days=0,
                    trailing_stop_pct=0.0,
                    min_position_notional_usd=float(min_position_notional_usd),
                    max_exit_orders_per_run=int(max_exit_orders_per_run),
                    submit=True,
                    slippage_bps=0.0,
                )
            report["exit_management"] = exit_management

        if output_format == "json":
            if once:
                typer.echo(json_lib.dumps(report, indent=2))
            else:
                typer.echo(json_lib.dumps(report))
        else:
            console.print(
                f"[green]Execution sync cycle complete[/green] | cycle={cycle} | "
                f"snapshot_orders={report.get('snapshot_orders', 0)} | "
                f"matched={report.get('matched_orders', 0)} | "
                f"fills={report.get('fills_applied', 0)} | "
                f"status_updates={report.get('status_updates', 0)} | "
                f"closed_positions={report.get('closed_positions', 0)}"
            )
            console.print(
                f"[cyan]Position refresh:[/cyan] refreshed={refresh.get('refreshed_count', 0)} | "
                f"unavailable={refresh.get('unavailable_count', 0)}"
            )
            if manage_open_orders and isinstance(open_orders_report, dict):
                console.print(
                    f"[cyan]Open-order management:[/cyan] stale={open_orders_report.get('stale_candidates_count', 0)} | "
                    f"canceled={open_orders_report.get('canceled_count', 0)} | "
                    f"replaced={open_orders_report.get('replaced_count', 0)} | "
                    f"errors={open_orders_report.get('errors_count', 0)}"
                )
            if sync_shadow_positions and isinstance(shadow_sync_report, dict):
                console.print(
                    f"[cyan]Shadow sync:[/cyan] added={shadow_sync_report.get('added_count', 0)} | "
                    f"updated={shadow_sync_report.get('updated_count', 0)} | "
                    f"removed={shadow_sync_report.get('removed_count', 0)}"
                )
            ready_label = "READY" if bool(readiness_report.get("overall_ready")) else "BLOCKED"
            console.print(
                f"[cyan]Execution readiness:[/cyan] {ready_label} | "
                f"blockers={len(readiness_report.get('blockers', []))}"
            )
            if isinstance(report.get("readiness_remediation"), dict):
                remediation = report.get("readiness_remediation", {})
                console.print(
                    f"[cyan]Readiness remediation:[/cyan] "
                    f"attempted={bool(remediation.get('attempted'))} | "
                    f"actions={len(remediation.get('actions', []))} | "
                    f"errors={len(remediation.get('errors', []))}"
                )
            if apply_exits and isinstance(exit_management, dict):
                console.print(
                    f"[cyan]Exit management:[/cyan] signals={exit_management.get('signals_generated', 0)} | "
                    f"orders={exit_management.get('orders_generated', 0)} | "
                    f"submitted={exit_management.get('orders_submitted', 0)}"
            )
            console.print(f"[cyan]Snapshot path:[/cyan] {snapshot_out_path}")
            console.print(f"[cyan]Reconciliation path:[/cyan] {report.get('reconciliation_path')}")
            if manage_open_orders and isinstance(open_orders_report, dict):
                console.print(
                    f"[cyan]Open-order artifact:[/cyan] "
                    f"{open_orders_report.get('open_orders_management_path', 'N/A')}"
                )
            if sync_shadow_positions and isinstance(shadow_sync_report, dict):
                console.print(
                    f"[cyan]Positions-sync artifact:[/cyan] "
                    f"{shadow_sync_report.get('positions_sync_path', 'N/A')}"
                )
            console.print(f"[cyan]Readiness path:[/cyan] {readiness_path}")

        if once:
            break
        if int(max_loops) > 0 and cycle >= int(max_loops):
            break
        time.sleep(int(interval_sec))


@app.command("manage-exits")
def manage_exits(
    execution_mode: str = typer.Option(
        str(DEFAULT_CONFIG.get("execution_broker_mode", "paper")),
        "--execution-mode",
        help="Execution adapter mode (paper, live, alpaca-paper, alpaca-live).",
    ),
    orders_path: Optional[str] = typer.Option(
        None,
        "--orders-path",
        help="Optional override for orders/outbox path.",
    ),
    positions_path: Optional[str] = typer.Option(
        None,
        "--positions-path",
        help="Optional override for positions path.",
    ),
    min_position_notional_usd: float = typer.Option(
        float(DEFAULT_CONFIG.get("execution_exit_min_position_notional_usd", 250.0)),
        "--min-position-notional-usd",
        min=0.0,
    ),
    max_exit_orders_per_run: int = typer.Option(
        int(DEFAULT_CONFIG.get("execution_exit_max_orders_per_run", 6)),
        "--max-exit-orders-per-run",
        min=1,
    ),
    submit: bool = typer.Option(
        False,
        "--submit/--dry-run",
        help="Submit generated exit orders via adapter or only preview in dry-run.",
    ),
    slippage_bps: float = typer.Option(
        float(DEFAULT_CONFIG.get("paper_execution_slippage_bps", 0.0)),
        "--slippage-bps",
        min=0.0,
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Generate adaptive exit signals using position review; optionally submit close intents."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    normalized_mode = str(execution_mode or "paper").strip().lower().replace("_", "-")
    default_orders_path, default_positions_path = _resolve_execution_paths_for_mode(normalized_mode)
    resolved_orders_path = str(orders_path) if orders_path else default_orders_path
    resolved_positions_path = str(positions_path) if positions_path else default_positions_path

    report = _run_manage_exits_once(
        execution_mode=normalized_mode,
        orders_path=resolved_orders_path,
        positions_path=resolved_positions_path,
        stop_loss_pct=0.0,
        take_profit_pct=0.0,
        max_hold_days=0,
        trailing_stop_pct=0.0,
        min_position_notional_usd=float(min_position_notional_usd),
        max_exit_orders_per_run=int(max_exit_orders_per_run),
        submit=bool(submit),
        slippage_bps=float(slippage_bps),
    )

    if output_format == "json":
        typer.echo(json_lib.dumps(report, indent=2))
        return

    status_text = "submitted" if bool(report.get("submitted")) else "preview"
    console.print(
        f"[green]Exit management complete[/green] | mode={normalized_mode} | status={status_text} | "
        f"signals={report.get('signals_generated', 0)} | orders={report.get('orders_generated', 0)} | "
        f"submitted={report.get('orders_submitted', 0)}"
    )
    if report.get("error"):
        console.print(f"[red]{report.get('error')}[/red]")
    if report.get("exit_management_path"):
        console.print(f"[cyan]Artifact:[/cyan] {report.get('exit_management_path')}")


@app.command("execution-readiness")
def execution_readiness(
    broker: str = typer.Option(
        "alpaca",
        "--broker",
        help="Broker source (currently: alpaca).",
    ),
    mode: str = typer.Option(
        str(DEFAULT_CONFIG.get("execution_broker_mode", "alpaca-paper")),
        "--mode",
        help="Broker mode (alpaca-paper or alpaca-live).",
    ),
    outbox_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_execution_outbox_path", "eval_results/live_execution/outbox.json")),
        "--outbox-path",
        help="Outbox path for pending-order checks.",
    ),
    positions_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_positions_shadow_path", "eval_results/live_execution/positions_shadow.json")),
        "--positions-path",
        help="Shadow positions path for drift checks.",
    ),
    snapshot_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_broker_orders_snapshot_path", "eval_results/live_execution/broker_orders_latest.json")),
        "--snapshot-path",
        help="Broker snapshot path used for open-order matching.",
    ),
    refresh_snapshot: bool = typer.Option(
        True,
        "--refresh-snapshot/--no-refresh-snapshot",
        help="Refresh broker snapshot before readiness evaluation.",
    ),
    max_stale_submitted_minutes: int = typer.Option(
        int(DEFAULT_CONFIG.get("execution_readiness_max_stale_submitted_minutes", 180)),
        "--max-stale-submitted-minutes",
        min=1,
    ),
    max_unmatched_open_orders: int = typer.Option(
        int(DEFAULT_CONFIG.get("execution_readiness_max_unmatched_open_orders", 10)),
        "--max-unmatched-open-orders",
        min=0,
    ),
    max_position_drift_notional_usd: float = typer.Option(
        float(DEFAULT_CONFIG.get("execution_readiness_max_position_drift_notional_usd", 2500.0)),
        "--max-position-drift-notional-usd",
        min=0.0,
    ),
    min_buying_power_usd: float = typer.Option(
        float(DEFAULT_CONFIG.get("execution_readiness_min_buying_power_usd", 1.0)),
        "--min-buying-power-usd",
        min=0.0,
    ),
    fail_on_blocked: bool = typer.Option(
        False,
        "--fail-on-blocked/--allow-blocked",
        help="Return non-zero exit code when readiness is blocked.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Evaluate broker-connected execution readiness and persist gate artifact."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    if bool(refresh_snapshot):
        try:
            fetch_alpaca_orders_snapshot(
                out_path=str(snapshot_path),
                mode=str(mode),
                status="open",
                limit=500,
            )
        except ValueError:
            # Readiness evaluator will capture API failures in blockers.
            pass

    report = evaluate_execution_readiness(
        broker=str(broker),
        mode=str(mode),
        outbox_path=str(outbox_path),
        positions_path=str(positions_path),
        snapshot_path=str(snapshot_path),
        max_stale_submitted_minutes=int(max_stale_submitted_minutes),
        max_unmatched_open_orders=int(max_unmatched_open_orders),
        max_position_drift_notional_usd=float(max_position_drift_notional_usd),
        min_buying_power_usd=float(min_buying_power_usd),
    )
    report["date"] = _today_str()
    readiness_path = _persist_execution_readiness(report)
    report["execution_readiness_path"] = str(readiness_path)
    try:
        RatingAuditLog().log_event(
            "EXECUTION_READINESS_EVALUATED",
            str(report.get("date") or _today_str()),
            {
                "overall_ready": bool(report.get("overall_ready")),
                "broker": str(broker),
                "mode": str(mode),
                "execution_readiness_path": str(readiness_path),
                "blockers": list(report.get("blockers", [])),
            },
        )
    except Exception:
        pass

    if output_format == "json":
        typer.echo(json_lib.dumps(report, indent=2))
    else:
        status_label = "[green]READY[/green]" if bool(report.get("overall_ready")) else "[yellow]BLOCKED[/yellow]"
        console.print(f"[cyan]Execution Readiness:[/cyan] {status_label} (mode={mode})")
        console.print(f"[cyan]Artifact:[/cyan] {readiness_path}")
        checks = dict(report.get("checks", {}))
        table = Table(title="Execution Readiness Checks")
        table.add_column("Check", style="cyan")
        table.add_column("Pass", justify="center")
        table.add_column("Details", style="white")
        for key in ("credentials", "account", "market_clock", "stale_pending_orders", "open_order_match", "position_drift"):
            payload = checks.get(key, {})
            table.add_row(
                key,
                "yes" if bool(payload.get("pass")) else "no",
                json_lib.dumps(payload),
            )
        console.print(table)
        blockers = list(report.get("blockers", []))
        if blockers:
            console.print("[yellow]Blockers:[/yellow]")
            for blocker in blockers:
                console.print(f"- {blocker}")

    if bool(fail_on_blocked) and not bool(report.get("overall_ready")):
        raise typer.Exit(2)


@app.command("manage-open-orders")
def manage_open_orders(
    broker: str = typer.Option(
        "alpaca",
        "--broker",
        help="Broker source (currently: alpaca).",
    ),
    mode: str = typer.Option(
        str(DEFAULT_CONFIG.get("execution_broker_mode", "alpaca-paper")),
        "--mode",
        help="Broker mode (alpaca-paper or alpaca-live).",
    ),
    outbox_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_execution_outbox_path", "eval_results/live_execution/outbox.json")),
        "--outbox-path",
        help="Live execution outbox path.",
    ),
    broker_snapshot_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_broker_orders_snapshot_path", "eval_results/live_execution/broker_orders_latest.json")),
        "--broker-snapshot-path",
        help="Path to broker orders snapshot JSON (open orders).",
    ),
    refresh_snapshot: bool = typer.Option(
        True,
        "--refresh-snapshot/--no-refresh-snapshot",
        help="Refresh broker open-orders snapshot before management.",
    ),
    max_age_minutes: int = typer.Option(
        int(DEFAULT_CONFIG.get("execution_open_orders_max_age_minutes", 90)),
        "--max-age-minutes",
        min=1,
        help="Minimum submitted age (minutes) before pending order is treated as stale.",
    ),
    replace_stale: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("execution_open_orders_replace_stale", False)),
        "--replace-stale/--cancel-only",
        help="Replace stale orders after cancel when retry budget allows.",
    ),
    replacement_order_type: str = typer.Option(
        str(DEFAULT_CONFIG.get("execution_open_orders_replacement_order_type", "market")),
        "--replacement-order-type",
        help="Replacement order type: market or limit.",
    ),
    limit_price_offset_bps: float = typer.Option(
        float(DEFAULT_CONFIG.get("execution_open_orders_limit_price_offset_bps", 10.0)),
        "--limit-price-offset-bps",
        min=0.0,
        help="Offset in basis points applied to limit replacements.",
    ),
    max_retries_per_symbol_per_day: int = typer.Option(
        int(DEFAULT_CONFIG.get("execution_open_orders_max_retries_per_symbol_per_day", 2)),
        "--max-retries-per-symbol-per-day",
        min=0,
        help="Maximum replacement submissions per symbol per day.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply/--dry-run",
        help="Apply cancellations/replacements or run in preview mode only.",
    ),
    fail_on_errors: bool = typer.Option(
        False,
        "--fail-on-errors/--allow-errors",
        help="Return non-zero exit code when management errors occur.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Cancel and optionally replace stale open broker orders."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    order_type = str(replacement_order_type or "market").strip().lower()
    if order_type not in {"market", "limit"}:
        console.print("[red]Error: replacement-order-type must be market or limit[/red]")
        raise typer.Exit(1)

    try:
        report = _run_manage_open_orders_once(
            broker=str(broker),
            mode=str(mode),
            outbox_path=str(outbox_path),
            broker_snapshot_path=str(broker_snapshot_path),
            refresh_snapshot=bool(refresh_snapshot),
            max_age_minutes=int(max_age_minutes),
            replace_stale=bool(replace_stale),
            replacement_order_type=order_type,
            limit_price_offset_bps=float(limit_price_offset_bps),
            max_retries_per_symbol_per_day=int(max_retries_per_symbol_per_day),
            apply_changes=bool(apply),
        )
    except (ValueError, FileNotFoundError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    artifact_path = _persist_open_orders_management(report)
    report["open_orders_management_path"] = str(artifact_path)

    try:
        audit = RatingAuditLog()
        batch_id = str(report.get("managed_at") or _today_str())
        for row in report.get("stale_candidates", []):
            if not isinstance(row, dict):
                continue
            audit.log_event(
                "OPEN_ORDER_STALE_DETECTED",
                str(row.get("order_intent_id") or row.get("symbol") or batch_id),
                row,
            )
        for row in report.get("canceled", []):
            if not isinstance(row, dict) or not bool(row.get("ok")):
                continue
            audit.log_event(
                "OPEN_ORDER_CANCELED",
                str(row.get("order_intent_id") or row.get("symbol") or batch_id),
                row,
            )
        for row in report.get("replaced", []):
            if not isinstance(row, dict) or not bool(row.get("ok")):
                continue
            audit.log_event(
                "OPEN_ORDER_REPLACED",
                str(row.get("order_intent_id") or row.get("symbol") or batch_id),
                row,
            )
        for row in report.get("retry_exhausted", []):
            if not isinstance(row, dict):
                continue
            audit.log_event(
                "OPEN_ORDER_RETRY_EXHAUSTED",
                str(row.get("order_intent_id") or row.get("symbol") or batch_id),
                row,
            )
        audit.log_event(
            "OPEN_ORDER_MANAGEMENT_COMPLETED",
            batch_id,
            {
                "broker": str(broker),
                "mode": str(mode),
                "apply": bool(apply),
                "stale_candidates_count": int(report.get("stale_candidates_count", 0)),
                "canceled_count": int(report.get("canceled_count", 0)),
                "replaced_count": int(report.get("replaced_count", 0)),
                "retry_exhausted_count": int(report.get("retry_exhausted_count", 0)),
                "errors_count": int(report.get("errors_count", 0)),
                "open_orders_management_path": str(artifact_path),
            },
        )
    except Exception:
        pass

    if output_format == "json":
        typer.echo(json_lib.dumps(report, indent=2))
    else:
        console.print(
            f"[green]Open-order management complete[/green] | "
            f"stale={report.get('stale_candidates_count', 0)} | "
            f"canceled={report.get('canceled_count', 0)} | "
            f"replaced={report.get('replaced_count', 0)} | "
            f"errors={report.get('errors_count', 0)}"
        )
        console.print(f"[cyan]Artifact:[/cyan] {artifact_path}")
        _render_open_orders_management_table(report)

    if bool(fail_on_errors) and int(report.get("errors_count", 0)) > 0:
        raise typer.Exit(2)


@app.command("sync-positions-from-broker")
def sync_positions_from_broker(
    broker: str = typer.Option(
        "alpaca",
        "--broker",
        help="Broker source (currently: alpaca).",
    ),
    mode: str = typer.Option(
        str(DEFAULT_CONFIG.get("execution_broker_mode", "alpaca-paper")),
        "--mode",
        help="Broker mode (alpaca-paper or alpaca-live).",
    ),
    broker_positions_snapshot_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_broker_positions_snapshot_path", "eval_results/live_execution/broker_positions_latest.json")),
        "--broker-positions-snapshot-path",
        help="Path to broker positions snapshot JSON.",
    ),
    positions_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_positions_shadow_path", "eval_results/live_execution/positions_shadow.json")),
        "--positions-path",
        help="Shadow positions path to update from broker snapshot.",
    ),
    refresh_snapshot: bool = typer.Option(
        True,
        "--refresh-snapshot/--no-refresh-snapshot",
        help="Refresh broker positions snapshot before syncing.",
    ),
    drop_missing: bool = typer.Option(
        False,
        "--drop-missing/--keep-missing",
        help="Drop shadow symbols not present at broker snapshot.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply/--dry-run",
        help="Apply sync into shadow positions or preview only.",
    ),
    fail_on_changes: bool = typer.Option(
        False,
        "--fail-on-changes/--allow-changes",
        help="Return non-zero exit code when the sync would change positions.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Sync live shadow positions from broker positions snapshot."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    try:
        report = _run_sync_positions_from_broker_once(
            broker=str(broker),
            mode=str(mode),
            broker_positions_snapshot_path=str(broker_positions_snapshot_path),
            positions_path=str(positions_path),
            refresh_snapshot=bool(refresh_snapshot),
            drop_missing=bool(drop_missing),
            apply_changes=bool(apply),
        )
    except (ValueError, FileNotFoundError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    artifact_path = _persist_positions_sync(report)
    report["positions_sync_path"] = str(artifact_path)

    try:
        RatingAuditLog().log_event(
            "LIVE_POSITIONS_SHADOW_SYNCED",
            str(report.get("synced_at") or _today_str()),
            {
                "broker": str(broker),
                "mode": str(mode),
                "apply": bool(apply),
                "drop_missing": bool(drop_missing),
                "broker_positions_count": int(report.get("broker_positions_count", 0)),
                "shadow_positions_before": int(report.get("shadow_positions_before", 0)),
                "shadow_positions_after": int(report.get("shadow_positions_after", 0)),
                "added_count": int(report.get("added_count", 0)),
                "updated_count": int(report.get("updated_count", 0)),
                "removed_count": int(report.get("removed_count", 0)),
                "positions_sync_path": str(artifact_path),
            },
        )
    except Exception:
        pass

    if output_format == "json":
        typer.echo(json_lib.dumps(report, indent=2))
    else:
        console.print(
            f"[green]Positions sync complete[/green] | "
            f"added={report.get('added_count', 0)} | "
            f"updated={report.get('updated_count', 0)} | "
            f"removed={report.get('removed_count', 0)}"
        )
        console.print(f"[cyan]Artifact:[/cyan] {artifact_path}")
        _render_positions_sync_table(report)

    total_changes = int(report.get("added_count", 0)) + int(report.get("updated_count", 0)) + int(report.get("removed_count", 0))
    if bool(fail_on_changes) and total_changes > 0:
        raise typer.Exit(2)


@app.command("paper-positions")
def paper_positions(
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """View current paper positions ledger."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    positions_path = str(DEFAULT_CONFIG.get("paper_positions_path", "eval_results/paper_execution/positions.json"))
    payload = load_open_positions(positions_path=positions_path)
    if output_format == "json":
        print(json_lib.dumps(payload, indent=2))
        return

    console.print(f"[cyan]Positions path:[/cyan] {positions_path}")
    _render_positions_table(payload, title="Paper Positions")


@app.command("live-positions")
def live_positions(
    positions_path: str = typer.Option(
        str(DEFAULT_CONFIG.get("live_positions_shadow_path", "eval_results/live_execution/positions_shadow.json")),
        "--positions-path",
        help="Live/shadow positions ledger path.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """View live/shadow positions ledger used by broker reconciliation."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    payload = load_open_positions(positions_path=str(positions_path))
    if output_format == "json":
        print(json_lib.dumps(payload, indent=2))
        return

    console.print(f"[cyan]Positions path:[/cyan] {positions_path}")
    _render_positions_table(payload, title="Live Shadow Positions")


@app.command("close-paper")
def close_paper(
    symbol: str,
    close_price: float = typer.Option(..., "--close-price", min=0.0001, help="Close price."),
    close_date: str = typer.Option(
        _today_str(),
        "--close-date",
        help="Close date (YYYY-MM-DD). Defaults to today.",
    ),
    execution_mode: str = typer.Option(
        str(DEFAULT_CONFIG.get("execution_broker_mode", "paper")),
        "--execution-mode",
        help="Execution adapter mode (paper for now).",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Close an open paper position and update linked track-record outcomes."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    positions_path = str(DEFAULT_CONFIG.get("paper_positions_path", "eval_results/paper_execution/positions.json"))
    closed_path = str(DEFAULT_CONFIG.get("paper_closed_trades_path", "eval_results/paper_execution/closed_trades.json"))
    try:
        close_event = close_position_with_adapter(
            symbol=symbol,
            close_price=float(close_price),
            close_date=close_date,
            execution_mode=str(execution_mode).strip().lower(),
            positions_path=positions_path,
            closed_trades_path=closed_path,
            track_record=TrackRecord(),
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    try:
        RatingAuditLog().log_event(
            "PAPER_POSITION_CLOSED",
            str((close_event.get("updated_rating_ids") or close_event.get("rating_ids") or [symbol])[0]),
            {
                **close_event,
                "execution_mode": str(execution_mode).strip().lower(),
            },
        )
    except Exception:
        pass

    if output_format == "json":
        print(json_lib.dumps(close_event, indent=2))
        return

    table = Table(title=f"Closed Paper Position ({str(symbol).upper()})")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Close Date", str(close_event.get("close_date")))
    table.add_row("Close Price", f"{float(close_event.get('close_price', 0.0)):.4f}")
    table.add_row("Net Quantity", f"{float(close_event.get('net_quantity', 0.0)):.4f}")
    table.add_row("Average Entry", f"{float(close_event.get('avg_entry_price', 0.0)):.4f}")
    table.add_row("PnL USD", f"{float(close_event.get('pnl_usd', 0.0)):.2f}")
    table.add_row("Return %", f"{float(close_event.get('return_pct', 0.0)):.4f}")
    table.add_row("Ratings Updated", str(len(close_event.get("updated_rating_ids", []))))
    console.print(table)


@app.command("panic-liquidate")
def panic_liquidate(
    execution_mode: str = typer.Option(
        DEFAULT_CONFIG.get("execution_broker_mode", "paper"),
        "--execution-mode",
        help="Execution mode (alpaca-paper, alpaca-live)",
    ),
    skip_confirmation: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    format: str = typer.Option("table", "--format", "-f", help="Output format"),
):
    """EMERGENCY: Cancel all orders and liquidate all positions."""
    if not skip_confirmation:
        console.print("[bold red]WARNING: This will cancel ALL open orders and close ALL positions.[/bold red]")
        confirm = typer.confirm("Are you sure you want to proceed?")
        if not confirm:
            raise typer.Exit(code=0)

    results = {}
    try:
        results = close_all_positions(mode=execution_mode, cancel_orders_first=True)
        console.print(f"[green]Liquidation complete.[/green] Closed {results.get('positions_closed', 0)} positions.")
    except Exception as exc:
        console.print(f"[bold red]Liquidation failed: {exc}[/bold red]")
        raise typer.Exit(code=1)

    if str(format).lower() == "json":
        console.print_json(data=results)
    else:
        console.print(Panel(json_lib.dumps(results, indent=2), title="Panic Liquidation Result"))


@app.command("reconciliation-loop")
def reconciliation_loop(
    execution_mode: str = typer.Option(
        str(DEFAULT_CONFIG.get("execution_broker_mode", "alpaca-paper")),
        "--execution-mode",
        help="Execution adapter mode (alpaca-paper or alpaca-live).",
    ),
    interval_seconds: int = typer.Option(
        int(DEFAULT_CONFIG.get("reconciliation_poll_interval_seconds", 60)),
        "--interval-seconds",
        min=1,
        help="Seconds to sleep between reconciliation cycles.",
    ),
    max_cycles: Optional[int] = typer.Option(
        None,
        "--max-cycles",
        help="Maximum number of cycles to run (omit for infinite).",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Run the automated reconciliation daemon, polling broker fills on a fixed interval.

    Fetches broker orders and positions each cycle, reconciles fills into the local
    ledger, and (when RECONCILIATION_AUTO_EXIT_CHECK=true) enforces stop-loss,
    take-profit, and max-hold-days exit rules automatically.
    """
    from tradingagents.graph.reconciliation_daemon import ReconciliationDaemon

    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    normalized_mode = str(execution_mode or "alpaca-paper").strip().lower().replace("_", "-")
    auto_exit = bool(DEFAULT_CONFIG.get("reconciliation_auto_exit_check", False))

    console.print(
        f"[green]Starting reconciliation daemon[/green] | mode={normalized_mode} | "
        f"interval={interval_seconds}s | max_cycles={max_cycles if max_cycles is not None else 'infinite'} | "
        f"auto_exit_check={auto_exit}"
    )

    daemon = ReconciliationDaemon(config=DEFAULT_CONFIG, mode=normalized_mode)
    results = daemon.run_loop(interval_seconds=interval_seconds, max_cycles=max_cycles)

    if output_format == "json":
        typer.echo(json_lib.dumps(results, indent=2))
        return

    total = len(results)
    ok_count = sum(1 for r in results if r.get("ok"))
    total_fills = sum(int(r.get("fills_applied", 0)) for r in results)
    total_status_updates = sum(int(r.get("status_updates", 0)) for r in results)
    total_closed = sum(int(r.get("closed_positions", 0)) for r in results)
    console.print(
        f"[green]Reconciliation loop complete[/green] | cycles={total} | ok={ok_count} | "
        f"total_fills={total_fills} | status_updates={total_status_updates} | closed_positions={total_closed}"
    )
    if auto_exit:
        total_exit_signals = sum(
            int((r.get("exit_check") or {}).get("signals_generated", 0)) for r in results
        )
        total_exit_submitted = sum(
            int((r.get("exit_check") or {}).get("orders_submitted", 0)) for r in results
        )
        console.print(
            f"[cyan]Exit checks[/cyan] | signals_generated={total_exit_signals} | orders_submitted={total_exit_submitted}"
        )


@app.command("reanalyze-positions")
def reanalyze_positions(
    execution_mode: str = typer.Option(
        str(DEFAULT_CONFIG.get("execution_broker_mode", "paper")),
        "--execution-mode",
        help="Execution adapter mode (paper, alpaca-paper, alpaca-live).",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Evaluate open positions for score-based exit signals."""
    from tradingagents.graph.paper_execution import evaluate_position_reanalysis

    result = evaluate_position_reanalysis(execution_mode=execution_mode)

    output_format = str(format or "table").lower().strip()
    if output_format == "json":
        typer.echo(json_lib.dumps(result, indent=2, default=str))
        return

    console.print(f"\n[bold]Position Re-Analysis[/bold] (mode: {execution_mode})\n")

    exits = result.get("exit_recommendations", [])
    if exits:
        console.print("[bold red]Exit Recommendations:[/bold red]")
        for rec in exits:
            console.print(
                f"  [red]EXIT[/red] {rec['ticker']} — {rec['exit_reason']} "
                f"(entry: {rec.get('entry_score', 'N/A')}, current: {rec.get('current_score', 'N/A')})"
            )
        console.print()

    needs = result.get("needs_reanalysis", [])
    if needs:
        console.print("[bold yellow]Needs Re-Analysis:[/bold yellow]")
        for rec in needs:
            console.print(
                f"  [yellow]STALE[/yellow] {rec['ticker']} — held {rec.get('hold_days', '?')}d, no fresh analysis today"
            )
        console.print()

    holds = result.get("hold", [])
    if holds:
        console.print("[bold green]Hold (Thesis Intact):[/bold green]")
        for rec in holds:
            console.print(
                f"  [green]HOLD[/green] {rec['ticker']} — score: {rec.get('current_score', 'N/A')}"
            )
        console.print()

    total = result.get("positions_evaluated", 0)
    console.print(f"[dim]Evaluated: {total} positions | Exits: {len(exits)} | Stale: {len(needs)} | Hold: {len(holds)}[/dim]")




@app.command("post-mortem")
def post_mortem_cmd(
    ticker: Optional[str] = typer.Option(None, "--ticker", help="Filter to specific ticker"),
    all_trades: bool = typer.Option(False, "--all", help="Show all post-mortems"),
    format: str = typer.Option("table", "--format", help="table|json"),
):
    """Show post-mortem attribution for closed trades."""
    import glob
    from rich.table import Table

    pm_dir = "eval_results/paper_execution/post_mortems"

    pattern = f"{pm_dir}/{ticker}_*.json" if ticker else f"{pm_dir}/*.json"
    files = sorted(glob.glob(pattern))

    if not files:
        console.print("[yellow]No post-mortem files found. Close a position to generate one.[/yellow]")
        return

    attributions = []
    for f in files:
        try:
            with open(f) as fh:
                attributions.append(json_lib.load(fh))
        except Exception:
            continue

    output_format = str(format or "table").lower().strip()
    if output_format == "json":
        typer.echo(json_lib.dumps(attributions, indent=2, default=str))
        return

    table = Table(title="Post-Mortem Attribution", show_header=True)
    table.add_column("Ticker", style="cyan bold")
    table.add_column("Date")
    table.add_column("Outcome")
    table.add_column("Return %", justify="right")
    table.add_column("P&L", justify="right")
    table.add_column("Regime")
    table.add_column("Pillars R/W/N")
    table.add_column("Score@Entry", justify="right")

    for attr in attributions:
        outcome = attr.get("outcome", "?")
        outcome_color = "green" if outcome == "WIN" else ("red" if outcome == "LOSS" else "yellow")
        ps = attr.get("pillar_summary", {})
        table.add_row(
            attr.get("ticker", "?"),
            attr.get("close_date", "?"),
            f"[{outcome_color}]{outcome}[/{outcome_color}]",
            f"{attr.get('return_pct', 0):+.2f}%",
            f"${attr.get('pnl_usd', 0):+,.2f}",
            attr.get("weight_regime", "?"),
            f"{ps.get('right_count', 0)}R/{ps.get('wrong_count', 0)}W/{ps.get('neutral_count', 0)}N",
            str(attr.get("entry_score", "?")),
        )

    console.print(table)


def _trade_outcome(trade: dict) -> str:
    """Classify trade as WIN, LOSS, or FLAT."""
    ret = float(trade.get("return_pct", 0))
    if abs(ret) <= 1.0 and ret != 0:
        ret = ret * 100
    if ret > 0.5:
        return "WIN"
    if ret < -0.5:
        return "LOSS"
    return "FLAT"


@app.command("trade-audit")
def trade_audit(
    ticker: Optional[str] = typer.Option(None, "--ticker", help="Filter to specific ticker"),
    min_return: Optional[float] = typer.Option(None, "--min-return", help="Minimum return %% filter (e.g. -5 for losses only)"),
    outcome: Optional[str] = typer.Option(None, "--outcome", help="Filter: WIN, LOSS, FLAT"),
    format: str = typer.Option("table", "--format", help="table|json|csv"),
    limit: int = typer.Option(50, "--limit", help="Max rows to show"),
):
    """LP-grade trade-by-trade audit trail from closed positions."""
    import csv
    import io
    from pathlib import Path

    from rich.table import Table

    closed_path = Path("eval_results/paper_execution/closed_trades.json")
    if not closed_path.exists():
        console.print("[yellow]No closed trades found.[/yellow]")
        return

    with open(closed_path) as f:
        trades = json_lib.load(f)

    if not isinstance(trades, list):
        trades = list(trades.values()) if isinstance(trades, dict) else []

    if ticker:
        trades = [t for t in trades if t.get("symbol", "").upper() == ticker.upper()]
    if outcome:
        trades = [t for t in trades if _trade_outcome(t) == outcome.upper()]
    if min_return is not None:
        trades = [t for t in trades if float(t.get("return_pct", 0)) * 100 >= min_return]

    trades = trades[-limit:]

    if not trades:
        console.print("[yellow]No trades match the filters.[/yellow]")
        return

    if format == "json":
        typer.echo(json_lib.dumps(trades, indent=2, default=str))
        return

    if format == "csv":
        buf = io.StringIO()
        if trades:
            writer = csv.DictWriter(buf, fieldnames=list(trades[0].keys()), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(trades)
        typer.echo(buf.getvalue())
        return

    table = Table(title=f"Trade Audit ({len(trades)} trades)", show_header=True, show_lines=False)
    table.add_column("Symbol", style="cyan bold", no_wrap=True)
    table.add_column("Entry Date", no_wrap=True)
    table.add_column("Exit Date", no_wrap=True)
    table.add_column("Days", justify="right")
    table.add_column("Entry $", justify="right")
    table.add_column("Exit $", justify="right")
    table.add_column("Return %", justify="right")
    table.add_column("P&L USD", justify="right")
    table.add_column("Outcome")
    table.add_column("Signal Source", no_wrap=True)

    total_pnl = 0.0
    wins = losses = flats = 0

    for t in trades:
        ret = float(t.get("return_pct", 0))
        if abs(ret) <= 1.0 and ret != 0:
            ret = ret * 100
        pnl = float(t.get("pnl_usd", 0))
        total_pnl += pnl
        oc = _trade_outcome(t)
        if oc == "WIN":
            wins += 1
        elif oc == "LOSS":
            losses += 1
        else:
            flats += 1

        oc_color = "green" if oc == "WIN" else ("red" if oc == "LOSS" else "yellow")
        ret_color = "green" if ret > 0 else ("red" if ret < 0 else "white")
        pnl_color = "green" if pnl > 0 else ("red" if pnl < 0 else "white")

        entry_d = str(t.get("entry_date", t.get("open_date", "?")))[:10]
        exit_d = str(t.get("close_date", t.get("exit_date", "?")))[:10]
        try:
            from datetime import datetime
            days: object = (datetime.fromisoformat(exit_d) - datetime.fromisoformat(entry_d)).days
        except Exception:
            days = "?"

        table.add_row(
            t.get("symbol", "?"),
            entry_d,
            exit_d,
            str(days),
            f"${float(t.get('entry_price', t.get('open_price', 0))):.2f}",
            f"${float(t.get('close_price', t.get('exit_price', 0))):.2f}",
            f"[{ret_color}]{ret:+.2f}%[/{ret_color}]",
            f"[{pnl_color}]${pnl:+,.2f}[/{pnl_color}]",
            f"[{oc_color}]{oc}[/{oc_color}]",
            str(t.get("signal_source", t.get("source", "—")))[:20],
        )

    console.print(table)

    total = wins + losses + flats
    win_rate = wins / total * 100 if total else 0
    pnl_color = "green" if total_pnl > 0 else "red"
    console.print(
        f"\nSummary: {wins}W / {losses}L / {flats}F  |  "
        f"Win Rate: {win_rate:.1f}%  |  "
        f"Total P&L: [{pnl_color}]${total_pnl:+,.2f}[/{pnl_color}]"
    )
