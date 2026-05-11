from cli.common import *  # noqa: F401,F403
from cli.commands.dealflow_workflow_interactive import _run_workflow_interactive


def _compat(name: str):
    import sys

    facade = sys.modules.get("cli.commands.dealflow")
    if facade is not None and hasattr(facade, name):
        return getattr(facade, name)
    return globals()[name]


@app.command("workflow-run")
def workflow_run(
    mode: str = typer.Option(
        "auto",
        "--mode",
        help="Deal-flow orchestration mode: auto|daily|event|manual.",
    ),
    date: Optional[str] = typer.Option(
        None,
        "--date",
        help="Optional run date (YYYY-MM-DD).",
    ),
    top_k: int = typer.Option(
        1,
        "--top-k",
        min=1,
        help="Deprecated; scout-only dealflow no longer ranks tickers.",
    ),
    profile: str = typer.Option(
        "daily",
        "--profile",
        help="Run profile: daily|max-recall|auto.",
    ),
    require_manual_x_feed: bool = typer.Option(
        True,
        "--require-manual-x-feed/--allow-missing-manual-x-feed",
        help="Require today's manual X-feed passes before running manual workflow mode.",
    ),
    include_unselected: bool = typer.Option(
        True,
        "--include-unselected/--selected-only",
        help="Deprecated; no queue batch run is created.",
    ),
    quick_unselected: bool = typer.Option(
        True,
        "--quick-unselected/--deep-unselected",
        help="Deprecated; scout tickers are not quick-scored.",
    ),
    per_item_timeout_seconds: int = typer.Option(
        int(os.getenv("AETERNUS_ANALYZE_BATCH_ITEM_TIMEOUT_SECONDS", "420")),
        "--per-item-timeout-seconds",
        min=30,
        help="Per-item analyze timeout in seconds.",
    ),
    allow_cached_report_on_failure: bool = typer.Option(
        True,
        "--allow-cached-report-on-failure/--no-allow-cached-report-on-failure",
        help="Allow cached report fallback on analyze failures.",
    ),
    continue_on_batch_failure: bool = typer.Option(
        False,
        "--continue-on-batch-failure/--fail-on-batch-failure",
        help="Deprecated; workflow no longer runs post-scout analysis.",
    ),
    capital_usd: float = typer.Option(
        float(DEFAULT_CONFIG.get("portfolio_capital_usd", 100000.0)),
        "--capital-usd",
        min=1000.0,
        help="Portfolio capital used for plan sizing.",
    ),
    max_positions: int = typer.Option(
        int(DEFAULT_CONFIG.get("portfolio_max_positions", 8)),
        "--max-positions",
        min=1,
        help="Maximum portfolio plan positions.",
    ),
    min_score: float = typer.Option(
        float(DEFAULT_CONFIG.get("portfolio_min_score", 55.0)),
        "--min-score",
        help="Minimum score for plan inclusion.",
    ),
    min_confidence: int = typer.Option(
        int(DEFAULT_CONFIG.get("portfolio_min_confidence", 3)),
        "--min-confidence",
        min=1,
        max=5,
        help="Minimum confidence for plan inclusion.",
    ),
    long_only: bool = typer.Option(
        True,
        "--long-only/--allow-shorts",
        help="Restrict planned names to long recommendations.",
    ),
    max_weight_per_position: float = typer.Option(
        float(DEFAULT_CONFIG.get("portfolio_max_weight_per_position", 0.25)),
        "--max-weight-per-position",
        min=0.01,
        max=1.0,
        help="Maximum weight cap per position.",
    ),
    include_hedges: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("portfolio_include_hedges", True)),
        "--include-hedges/--skip-hedges",
        help="Include hedge overlay intent in portfolio plan stage.",
    ),
    include_cc_wyckoff: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("portfolio_include_cc_wyckoff", True)),
        "--include-cc-wyckoff/--skip-cc-wyckoff",
        help="Include Covered Call Wyckoff phase intents in portfolio plan stage.",
    ),
    execution_mode: str = typer.Option(
        str(DEFAULT_CONFIG.get("execution_broker_mode", "paper")),
        "--execution-mode",
        help="Execution mode (paper, live, alpaca-paper, alpaca-live).",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        help="Run guided human-operated workflow mode with mandatory manual prompts.",
    ),
    run_execution: bool = typer.Option(
        True,
        "--run-execution/--skip-execution",
        help="Execute plan after portfolio construction.",
    ),
    run_sync: bool = typer.Option(
        True,
        "--run-sync/--skip-sync",
        help="Run execution-sync after execution phase.",
    ),
    apply_exits: bool = typer.Option(
        True,
        "--apply-exits/--skip-exits",
        help="Apply deterministic exits during sync cycle.",
    ),
    require_ready: bool = typer.Option(
        True,
        "--require-ready/--skip-ready-check",
        help="Require readiness pass before submitting exits.",
    ),
    manage_open_orders: bool = typer.Option(
        True,
        "--manage-open-orders/--skip-manage-open-orders",
        help="Run stale open-order management in sync cycle.",
    ),
    manage_open_orders_apply: bool = typer.Option(
        True,
        "--manage-open-orders-apply/--manage-open-orders-dry-run",
        help="Apply stale open-order actions in sync cycle.",
    ),
    sync_shadow_positions: bool = typer.Option(
        True,
        "--sync-shadow-positions/--skip-shadow-positions-sync",
        help="Run broker->shadow position sync in sync cycle.",
    ),
    sync_shadow_positions_apply: bool = typer.Option(
        True,
        "--sync-shadow-positions-apply/--sync-shadow-positions-dry-run",
        help="Apply broker->shadow sync changes in sync cycle.",
    ),
    sync_shadow_positions_drop_missing: bool = typer.Option(
        False,
        "--sync-shadow-positions-drop-missing/--sync-shadow-positions-keep-missing",
        help="Drop missing shadow symbols during sync cycle.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Run dealflow scout ticker workflow."""
    from tradingagents.dealflow.system_halt import is_hands_off_active
    if is_hands_off_active():
        console.print("[bold red]SYSTEM HALT ACTIVE — aborting. Clear halt before retrying.[/bold red]")
        raise typer.Exit(code=1)

    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    run_mode = str(mode or "auto").lower().strip()
    if run_mode not in {"auto", "daily", "event", "manual"}:
        console.print("[red]Error: mode must be auto|daily|event|manual[/red]")
        raise typer.Exit(1)

    try:
        run_profile = _resolve_run_profile(profile)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)

    run_date_hint = str(date or _today_str())
    if interactive:
        _compat("_run_workflow_interactive")(
            run_mode=run_mode,
            run_date_hint=run_date_hint,
            output_format=output_format,
            top_k=int(top_k),
            run_profile=run_profile,
            require_manual_x_feed=bool(require_manual_x_feed),
            include_unselected=bool(include_unselected),
            quick_unselected=bool(quick_unselected),
            per_item_timeout_seconds=int(per_item_timeout_seconds),
            allow_cached_report_on_failure=bool(allow_cached_report_on_failure),
            continue_on_batch_failure=bool(continue_on_batch_failure),
            capital_usd=float(capital_usd),
            max_positions=int(max_positions),
            min_score=float(min_score),
            min_confidence=int(min_confidence),
            long_only=bool(long_only),
            max_weight_per_position=float(max_weight_per_position),
            include_hedges=bool(include_hedges),
            include_cc_wyckoff=bool(include_cc_wyckoff),
            execution_mode=str(execution_mode),
            run_execution=bool(run_execution),
            run_sync=bool(run_sync),
            apply_exits=bool(apply_exits),
            require_ready=bool(require_ready),
            manage_open_orders=bool(manage_open_orders),
            manage_open_orders_apply=bool(manage_open_orders_apply),
            sync_shadow_positions=bool(sync_shadow_positions),
            sync_shadow_positions_apply=bool(sync_shadow_positions_apply),
            sync_shadow_positions_drop_missing=bool(sync_shadow_positions_drop_missing),
        )
        return

    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    workflow: Dict[str, Any] = {
        "started_at": started_at,
        "status": "RUNNING",
        "mode": run_mode,
        "requested_date": str(date or ""),
        "top_k": int(top_k),
        "profile": run_profile,
        "execution_mode": str(execution_mode),
        "steps": {},
    }

    if run_mode == "manual" and require_manual_x_feed:
        from tradingagents.dealflow.sources.x_feed_manual import finalize_x_feed, get_readiness, get_readiness_pre_finalize

        pre_x_feed = get_readiness_pre_finalize(run_date_hint)
        if not pre_x_feed.get("missing_passes") and int(pre_x_feed.get("merged_symbol_count", 0) or 0) > 0:
            finalize_x_feed(run_date_hint)
        x_feed_readiness = get_readiness(run_date_hint)
        workflow["steps"]["manual_x_feed"] = x_feed_readiness
        if not bool(x_feed_readiness.get("ready")):
            workflow["status"] = "BLOCKED_MANUAL_X_FEED"
            workflow["date"] = run_date_hint
            workflow["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            workflow["remediation"] = {
                "command": "aeternus x-feed --status --date "
                + run_date_hint
                + " && aeternus x-feed --generate --date "
                + run_date_hint,
                "missing_passes": list(x_feed_readiness.get("missing_passes", [])),
            }
            workflow_path = _compat("_persist_workflow_run")(workflow)
            workflow["workflow_run_path"] = str(workflow_path)
            if output_format == "json":
                typer.echo(json_lib.dumps(workflow, indent=2))
            else:
                console.print(
                    "[yellow]Workflow blocked[/yellow] | manual X-feed incomplete "
                    f"for {run_date_hint}"
                )
                console.print(
                    "[cyan]Missing passes:[/cyan] "
                    + ", ".join(str(p) for p in x_feed_readiness.get("missing_passes", []))
                )
                console.print(f"[cyan]Workflow artifact:[/cyan] {workflow_path}")
            raise typer.Exit(1)

    run_config = _apply_run_profile_overrides(DEFAULT_CONFIG.copy(), run_profile)
    scheduler = _compat("DealFlowScheduler")(config=run_config)
    force_trigger = None if run_mode == "auto" else run_mode
    orchestration = scheduler.run_once(
        force_trigger=force_trigger,
        as_of_date=date,
        top_k=int(top_k),
    )
    orchestration["run_profile"] = run_profile
    workflow["steps"]["orchestration"] = {
        "ran": bool(orchestration.get("ran")),
        "trigger": orchestration.get("trigger"),
        "reason": orchestration.get("reason"),
        "run_id": orchestration.get("run_id"),
        "signal_count": orchestration.get("signal_count"),
    }

    if not bool(orchestration.get("ran")):
        workflow["status"] = "SKIPPED_ORCHESTRATION"
        workflow["date"] = str(orchestration.get("date") or date or _today_str())
        workflow["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        workflow_path = _compat("_persist_workflow_run")(workflow)
        workflow["workflow_run_path"] = str(workflow_path)
        if output_format == "json":
            typer.echo(json_lib.dumps(workflow, indent=2))
            return
        console.print(
            f"[yellow]Workflow skipped[/yellow] | reason={orchestration.get('reason')} | "
            f"date={workflow.get('date')}"
        )
        console.print(f"[cyan]Workflow artifact:[/cyan] {workflow_path}")
        return

    run_date = str(orchestration.get("date") or date or _today_str())
    workflow["date"] = run_date
    workflow["status"] = "SUCCESS"
    workflow["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    workflow["steps"]["scout_ticker_summary"] = dict(orchestration.get("scout_ticker_summary", {}) or {})
    workflow_path = _compat("_persist_workflow_run")(workflow)
    workflow["workflow_run_path"] = str(workflow_path)

    if output_format == "json":
        typer.echo(json_lib.dumps(workflow, indent=2))
        return
    console.print(
        f"[yellow]Workflow complete[/yellow] | date={run_date} | "
        f"unique_tickers={int(orchestration.get('total_unique_tickers', 0) or 0)}"
    )
    counts = dict(orchestration.get("scout_counts", {}) or {})
    if counts:
        console.print("[cyan]Scout counts:[/cyan] " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    console.print(f"[cyan]Workflow artifact:[/cyan] {workflow_path}")
    return


@app.command("workflow-loop")
def workflow_loop(
    mode: str = typer.Option(
        "auto",
        "--mode",
        help="Deal-flow orchestration mode: auto|daily|event|manual.",
    ),
    date: Optional[str] = typer.Option(
        None,
        "--date",
        help="Optional run date (YYYY-MM-DD). Reused each cycle when provided.",
    ),
    top_k: int = typer.Option(
        1,
        "--top-k",
        min=1,
        help="Deprecated; scout-only dealflow no longer ranks tickers.",
    ),
    profile: str = typer.Option(
        "daily",
        "--profile",
        help="Run profile: daily|max-recall|auto.",
    ),
    require_manual_x_feed: bool = typer.Option(
        True,
        "--require-manual-x-feed/--allow-missing-manual-x-feed",
        help="Require today's manual X-feed passes before running manual workflow mode.",
    ),
    cycles: int = typer.Option(
        int(DEFAULT_CONFIG.get("workflow_loop_default_cycles", 1)),
        "--cycles",
        min=1,
        help="Number of workflow-run cycles.",
    ),
    interval_seconds: int = typer.Option(
        int(DEFAULT_CONFIG.get("workflow_loop_interval_seconds", 900)),
        "--interval-seconds",
        min=0,
        help="Sleep interval between cycles.",
    ),
    stop_on_failure: bool = typer.Option(
        False,
        "--stop-on-failure/--continue-on-failure",
        help="Stop loop when a cycle returns non-zero.",
    ),
    include_unselected: bool = typer.Option(
        True,
        "--include-unselected/--selected-only",
        help="Deprecated; no queue batch run is created.",
    ),
    quick_unselected: bool = typer.Option(
        True,
        "--quick-unselected/--deep-unselected",
        help="Deprecated; scout tickers are not quick-scored.",
    ),
    allow_cached_report_on_failure: bool = typer.Option(
        True,
        "--allow-cached-report-on-failure/--no-allow-cached-report-on-failure",
        help="Allow cached report fallback on analyze failures.",
    ),
    continue_on_batch_failure: bool = typer.Option(
        False,
        "--continue-on-batch-failure/--fail-on-batch-failure",
        help="Deprecated; workflow no longer runs post-scout analysis.",
    ),
    include_hedges: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("portfolio_include_hedges", True)),
        "--include-hedges/--skip-hedges",
        help="Include hedge overlay intent in portfolio plan stage.",
    ),
    execution_mode: str = typer.Option(
        str(DEFAULT_CONFIG.get("execution_broker_mode", "paper")),
        "--execution-mode",
        help="Execution mode (paper, live, alpaca-paper, alpaca-live).",
    ),
    run_execution: bool = typer.Option(
        True,
        "--run-execution/--skip-execution",
        help="Execute plan after portfolio construction.",
    ),
    run_sync: bool = typer.Option(
        True,
        "--run-sync/--skip-sync",
        help="Run execution-sync after execution phase.",
    ),
    apply_exits: bool = typer.Option(
        True,
        "--apply-exits/--skip-exits",
        help="Apply deterministic exits during sync cycle.",
    ),
    require_ready: bool = typer.Option(
        True,
        "--require-ready/--skip-ready-check",
        help="Require readiness pass before submitting exits.",
    ),
    manage_open_orders: bool = typer.Option(
        True,
        "--manage-open-orders/--skip-manage-open-orders",
        help="Run stale open-order management in sync cycle.",
    ),
    manage_open_orders_apply: bool = typer.Option(
        True,
        "--manage-open-orders-apply/--manage-open-orders-dry-run",
        help="Apply stale open-order actions in sync cycle.",
    ),
    sync_shadow_positions: bool = typer.Option(
        True,
        "--sync-shadow-positions/--skip-shadow-positions-sync",
        help="Run broker->shadow position sync in sync cycle.",
    ),
    sync_shadow_positions_apply: bool = typer.Option(
        True,
        "--sync-shadow-positions-apply/--sync-shadow-positions-dry-run",
        help="Apply broker->shadow sync changes in sync cycle.",
    ),
    sync_shadow_positions_drop_missing: bool = typer.Option(
        False,
        "--sync-shadow-positions-drop-missing/--sync-shadow-positions-keep-missing",
        help="Drop missing shadow symbols during sync cycle.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Run workflow-run repeatedly with fixed interval and cycle controls."""
    from tradingagents.dealflow.system_halt import is_hands_off_active
    if is_hands_off_active():
        console.print("[bold red]SYSTEM HALT ACTIVE — aborting. Clear halt before retrying.[/bold red]")
        raise typer.Exit(code=1)

    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cycles_report: List[Dict[str, Any]] = []
    failure_count = 0
    workflow_date = str(date or _today_str())

    for idx in range(int(cycles)):
        cycle_started = datetime.datetime.now(datetime.timezone.utc).isoformat()
        args = [
            "workflow-run",
            "--mode",
            str(mode),
            "--top-k",
            str(int(top_k)),
            "--profile",
            str(profile),
            "--execution-mode",
            str(execution_mode),
        ]
        if date:
            args.extend(["--date", str(date)])
        if include_unselected:
            args.append("--include-unselected")
        else:
            args.append("--selected-only")
        if require_manual_x_feed:
            args.append("--require-manual-x-feed")
        else:
            args.append("--allow-missing-manual-x-feed")
        if quick_unselected:
            args.append("--quick-unselected")
        else:
            args.append("--deep-unselected")
        if allow_cached_report_on_failure:
            args.append("--allow-cached-report-on-failure")
        else:
            args.append("--no-allow-cached-report-on-failure")
        if continue_on_batch_failure:
            args.append("--continue-on-batch-failure")
        else:
            args.append("--fail-on-batch-failure")
        if include_hedges:
            args.append("--include-hedges")
        else:
            args.append("--skip-hedges")
        if run_execution:
            args.append("--run-execution")
        else:
            args.append("--skip-execution")
        if run_sync:
            args.append("--run-sync")
        else:
            args.append("--skip-sync")
        if apply_exits:
            args.append("--apply-exits")
        else:
            args.append("--skip-exits")
        if require_ready:
            args.append("--require-ready")
        else:
            args.append("--skip-ready-check")
        if manage_open_orders:
            args.append("--manage-open-orders")
            if manage_open_orders_apply:
                args.append("--manage-open-orders-apply")
            else:
                args.append("--manage-open-orders-dry-run")
        else:
            args.append("--skip-manage-open-orders")
        if sync_shadow_positions:
            args.append("--sync-shadow-positions")
            if sync_shadow_positions_apply:
                args.append("--sync-shadow-positions-apply")
            else:
                args.append("--sync-shadow-positions-dry-run")
            if sync_shadow_positions_drop_missing:
                args.append("--sync-shadow-positions-drop-missing")
            else:
                args.append("--sync-shadow-positions-keep-missing")
        else:
            args.append("--skip-shadow-positions-sync")

        child = _compat("_run_cli_subcommand_json")(args=args, timeout=None)
        payload = child.get("payload") if isinstance(child.get("payload"), dict) else {}
        cycle_status = str(payload.get("status") or "")
        cycle_date = str(payload.get("date") or workflow_date)
        if cycle_date:
            workflow_date = cycle_date
        cycle_record = {
            "cycle": idx + 1,
            "started_at": cycle_started,
            "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "return_code": int(child.get("return_code", 1)),
            "status": cycle_status,
            "date": cycle_date,
            "workflow_run_path": str(payload.get("workflow_run_path") or ""),
            "processed": int(payload.get("steps", {}).get("analyze_batch", {}).get("processed", 0))
            if isinstance(payload.get("steps"), dict)
            else 0,
            "success_count": int(payload.get("steps", {}).get("analyze_batch", {}).get("success_count", 0))
            if isinstance(payload.get("steps"), dict)
            else 0,
            "failure_count": int(payload.get("steps", {}).get("analyze_batch", {}).get("failure_count", 0))
            if isinstance(payload.get("steps"), dict)
            else 0,
            "stderr_tail": str(child.get("stderr") or "").strip().splitlines()[-1:]
            if str(child.get("stderr") or "").strip()
            else [],
        }
        cycles_report.append(cycle_record)
        if int(cycle_record["return_code"]) != 0:
            failure_count += 1
            if bool(stop_on_failure):
                break

        if idx < int(cycles) - 1 and int(interval_seconds) > 0:
            time.sleep(int(interval_seconds))

    result = {
        "started_at": started_at,
        "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "date": workflow_date,
        "requested_cycles": int(cycles),
        "completed_cycles": len(cycles_report),
        "failure_cycles": int(failure_count),
        "stop_on_failure": bool(stop_on_failure),
        "interval_seconds": int(interval_seconds),
        "cycles": cycles_report,
    }
    result["status"] = "SUCCESS" if int(failure_count) == 0 else "COMPLETED_WITH_FAILURES"
    loop_path = _compat("_persist_workflow_loop_run")(result)
    result["workflow_loop_path"] = str(loop_path)

    if output_format == "json":
        typer.echo(json_lib.dumps(result, indent=2))
        if int(failure_count) > 0:
            raise typer.Exit(1)
        return

    status_color = "green" if int(failure_count) == 0 else "yellow"
    console.print(
        f"[{status_color}]Workflow loop complete[/{status_color}] | "
        f"completed={len(cycles_report)}/{int(cycles)} | failures={int(failure_count)}"
    )
    console.print(f"[cyan]Workflow loop artifact:[/cyan] {loop_path}")

    table = Table(title=f"Workflow Loop ({workflow_date})")
    table.add_column("Cycle", justify="right")
    table.add_column("Date", style="cyan")
    table.add_column("Status", style="yellow")
    table.add_column("Processed", justify="right")
    table.add_column("Success", justify="right")
    table.add_column("Failed", justify="right")
    table.add_column("Exit", justify="right")
    for row in cycles_report:
        table.add_row(
            str(row.get("cycle")),
            str(row.get("date") or ""),
            str(row.get("status") or "UNKNOWN"),
            str(row.get("processed", 0)),
            str(row.get("success_count", 0)),
            str(row.get("failure_count", 0)),
            str(row.get("return_code", 1)),
        )
    console.print(table)

    if int(failure_count) > 0:
        raise typer.Exit(1)
