from cli.common import *  # noqa: F401,F403
from tradingagents.dealflow.learning_loop import run_learning_cycle


def _compat(name: str):
    import sys

    facade = sys.modules.get("cli.commands.dealflow")
    if facade is not None and hasattr(facade, name):
        return getattr(facade, name)
    return globals()[name]

def _read_multiline_until_end(prompt_label: str = "JSON payload") -> str:
    console.print(
        f"[dim]Paste {prompt_label} below. Type END on its own line when done.[/dim]"
    )
    lines: List[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    raw = "\n".join(lines).strip()
    if not raw:
        raise ValueError("Empty input")
    return raw


def _interactive_complete_macro(as_of_date: str) -> Dict[str, Any]:
    """Compatibility hook for legacy interactive manual macro gap-fill."""
    return {"date": as_of_date, "status": "UNCONFIGURED"}


def _interactive_complete_earnings_options(as_of_date: str) -> Dict[str, Any]:
    """Compatibility hook for legacy interactive earnings/options gap-fill."""
    return {"date": as_of_date, "setup_count": 0, "status": "UNCONFIGURED"}


def _interactive_complete_x_feed(as_of_date: str) -> Dict[str, Any]:
    from tradingagents.dealflow.sources.x_feed_manual import (
        PASS_CONFIGS,
        finalize_x_feed,
        generate_prompts,
        get_readiness,
        ingest_pass,
    )

    prompt_map = {int(pass_num): (label, prompt) for pass_num, label, prompt in generate_prompts(as_of_date)}
    readiness = get_readiness(as_of_date)
    while not bool(readiness.get("ready")):
        missing = list(readiness.get("missing_passes", []))
        if not missing:
            break
        pass_num = int(missing[0])
        label = PASS_CONFIGS[pass_num - 1]["label"] if 1 <= pass_num <= len(PASS_CONFIGS) else "Pass"
        _, prompt = prompt_map.get(pass_num, (label, ""))
        console.rule(f"[bold]X-feed Pass {pass_num}: {label}[/bold]")
        if prompt:
            console.print(prompt)
            console.print()
        try:
            raw = _compat("_read_multiline_until_end")(prompt_label=f"Pass {pass_num} JSON")
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        result = ingest_pass(as_of_date, raw, pass_num, dry_run=False)
        console.print(
            f"[green]Pass {pass_num} ingested[/green] | "
            f"parsed={int(result.get('tickers_parsed', 0) or 0)} | "
            f"merged={int(result.get('tickers_merged', 0) or 0)}"
        )
        readiness = get_readiness(as_of_date)
    if not readiness.get("missing_passes") and int(readiness.get("merged_symbol_count", 0) or 0) > 0:
        finalize_x_feed(as_of_date)
    return readiness


def _render_interactive_discover_summary(summary: Dict[str, Any]) -> None:
    insider = summary.get("insider_summary", {}) if isinstance(summary.get("insider_summary"), dict) else {}
    console.print(
        f"[green]Discovery complete[/green] | universe={int(summary.get('universe_size', 0) or 0)} | "
        f"breakout={int(summary.get('breakout_count', 0) or 0)} | "
        f"technical_ignition={int(summary.get('technical_ignition_count', 0) or 0)}"
    )
    if insider:
        console.print(
            "  "
            f"insider: txns={int(insider.get('new_txns', 0) or 0)} | "
            f"buy_clusters={int(insider.get('buy_clusters', 0) or 0)} | "
            f"sell_clusters={int(insider.get('sell_clusters', 0) or 0)}"
        )
    if summary.get("fvg_recall_symbols") or summary.get("fma_recall_symbols"):
        console.print(
            "  "
            f"technical recall: FVG={len(summary.get('fvg_recall_symbols', []) or [])} | "
            f"FMA={len(summary.get('fma_recall_symbols', []) or [])}"
        )


def _render_interactive_collect_summary(
    shortlist: Dict[str, Any],
    research_queue: Dict[str, Any],
    normalized_signals: List[Dict[str, Any]],
) -> None:
    connector_summary = shortlist.get("connector_health_summary", {})
    ok_count = int(connector_summary.get("ok_count", 0) or 0) if isinstance(connector_summary, dict) else 0
    error_count = int(connector_summary.get("error_count", 0) or 0) if isinstance(connector_summary, dict) else 0
    console.print(
        f"[green]Collect complete[/green] | signals={len(normalized_signals)} | "
        f"shortlist={len(shortlist.get('candidates', []) or [])} | "
        f"queue={len(research_queue.get('items', []) or [])} | "
        f"selected={len(research_queue.get('selected_queue_ids', []) or [])}"
    )
    console.print(f"  connector_health: ok={ok_count} | errors={error_count}")


def _run_workflow_interactive(
    *,
    run_mode: str,
    run_date_hint: str,
    output_format: str,
    top_k: int,
    run_profile: str,
    require_manual_x_feed: bool,
    include_unselected: bool,
    quick_unselected: bool,
    per_item_timeout_seconds: int,
    allow_cached_report_on_failure: bool,
    continue_on_batch_failure: bool,
    capital_usd: float,
    max_positions: int,
    min_score: float,
    min_confidence: int,
    long_only: bool,
    max_weight_per_position: float,
    include_hedges: bool,
    include_cc_wyckoff: bool,
    execution_mode: str,
    run_execution: bool,
    run_sync: bool,
    apply_exits: bool,
    require_ready: bool,
    manage_open_orders: bool,
    manage_open_orders_apply: bool,
    sync_shadow_positions: bool,
    sync_shadow_positions_apply: bool,
    sync_shadow_positions_drop_missing: bool,
) -> None:
    if run_mode != "manual":
        console.print("[red]Error: interactive mode requires --mode manual[/red]")
        raise typer.Exit(1)
    if output_format == "json":
        console.print("[red]Error: interactive mode supports table output only[/red]")
        raise typer.Exit(1)

    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    workflow: Dict[str, Any] = {
        "started_at": started_at,
        "status": "RUNNING",
        "mode": run_mode,
        "date": run_date_hint,
        "top_k": int(top_k),
        "profile": run_profile,
        "execution_mode": str(execution_mode),
        "interactive": True,
        "steps": {},
    }

    if require_manual_x_feed:
        x_feed_readiness = _compat("_interactive_complete_x_feed")(run_date_hint)
        workflow["steps"]["manual_x_feed"] = dict(x_feed_readiness)
        console.print(
            f"[green]Manual X-feed complete[/green] | "
            f"passes={len(x_feed_readiness.get('completed_passes', []) or [])}/"
            f"{len(x_feed_readiness.get('required_passes', []) or [])} | "
            f"merged={int(x_feed_readiness.get('merged_symbol_count', 0) or 0)}"
        )

    macro_fn = _compat("_interactive_complete_macro")
    if macro_fn is not _interactive_complete_macro:
        macro_payload = macro_fn(run_date_hint)
        workflow["steps"]["macro"] = dict(macro_payload)
        console.print("[green]Macro cache saved[/green]")
    earnings_fn = _compat("_interactive_complete_earnings_options")
    if earnings_fn is not _interactive_complete_earnings_options:
        earnings_payload = earnings_fn(run_date_hint)
        workflow["steps"]["earnings_options"] = dict(earnings_payload)
        console.print("[green]Earnings/options scout saved[/green]")

    run_config = _apply_run_profile_overrides(DEFAULT_CONFIG.copy(), run_profile)
    pipeline = _compat("DealFlowPipeline")(config=run_config)

    console.print(
        "Following scouts are now going to run: "
        "breakout, technical_ignition, insider, FVG recall, FMA recall"
    )
    discover_summary = pipeline.discover(as_of_date=run_date_hint, trigger="manual")
    workflow["steps"]["discover"] = dict(discover_summary)
    _render_interactive_discover_summary(discover_summary)

    console.print(
        "Following collectors are now going to run: "
        "social_news, price_momentum, sector_rotation, insider_cluster"
    )
    shortlist, research_queue, normalized_signals, event_state = pipeline.collect(
        as_of_date=run_date_hint,
        trigger="manual",
        top_k=int(top_k),
    )
    workflow["steps"]["orchestration"] = {
        "ran": True,
        "trigger": "manual",
        "reason": "interactive_manual",
        "run_id": str(shortlist.get("run_id") or ""),
        "signal_count": len(normalized_signals),
        "shortlist_size": len(shortlist.get("candidates", []) or []),
        "selected_for_deep": len(research_queue.get("selected_queue_ids", []) or []),
    }
    workflow["steps"]["collect"] = {
        "run_id": str(shortlist.get("run_id") or ""),
        "signal_count": len(normalized_signals),
        "shortlist_size": len(shortlist.get("candidates", []) or []),
        "queue_size": len(research_queue.get("items", []) or []),
        "selected_for_deep": len(research_queue.get("selected_queue_ids", []) or []),
        "event_triggered": bool(event_state.get("triggered")),
    }
    _render_interactive_collect_summary(shortlist, research_queue, normalized_signals)

    analyze_args = [
        "analyze-batch",
        "--queue-date",
        run_date_hint,
        "--per-item-timeout-seconds",
        str(int(per_item_timeout_seconds)),
    ]
    if include_unselected:
        analyze_args.append("--include-unselected")
    else:
        analyze_args.append("--selected-only")
    if quick_unselected:
        analyze_args.append("--quick-unselected")
    else:
        analyze_args.append("--deep-unselected")
    if allow_cached_report_on_failure:
        analyze_args.append("--allow-cached-report-on-failure")
    else:
        analyze_args.append("--no-allow-cached-report-on-failure")

    console.print(
        f"Deep analysis is now going to run: queue={len(research_queue.get('items', []) or [])} | "
        f"selected={len(research_queue.get('selected_queue_ids', []) or [])}"
    )
    analyze_exec = _compat("_run_cli_subcommand_json")(args=analyze_args, timeout=None)
    analyze_payload = analyze_exec.get("payload") if isinstance(analyze_exec.get("payload"), dict) else {}
    analyze_summary: Dict[str, Any] = dict(analyze_payload)
    analyze_summary_path = str(analyze_summary.get("summary_path") or "").strip()
    analyze_used_fallback_summary = False
    if not analyze_summary or not analyze_summary_path:
        try:
            fallback_summary, fallback_path = _load_batch_summary(queue_date=run_date_hint)
            if isinstance(fallback_summary, dict) and fallback_summary:
                merged_summary = dict(fallback_summary)
                for key, value in analyze_summary.items():
                    if value not in (None, "", [], {}):
                        merged_summary[key] = value
                analyze_summary = merged_summary
                analyze_summary_path = str(fallback_path)
                analyze_used_fallback_summary = True
        except FileNotFoundError:
            pass

    analyze_return_code = int(analyze_exec.get("return_code", 1))
    analyze_processed = int(analyze_summary.get("processed", 0) or 0)
    analyze_success_count = int(analyze_summary.get("success_count", 0) or 0)
    analyze_failure_count = int(analyze_summary.get("failure_count", 0) or 0)
    analyze_skipped_count = int(analyze_summary.get("skipped_count", 0) or 0)
    workflow["steps"]["analyze_batch"] = {
        "return_code": analyze_return_code,
        "processed": analyze_processed,
        "success_count": analyze_success_count,
        "failure_count": analyze_failure_count,
        "skipped_count": analyze_skipped_count,
        "summary_path": analyze_summary_path,
        "used_fallback_summary": analyze_used_fallback_summary,
    }
    if analyze_return_code != 0 and not bool(continue_on_batch_failure) and analyze_success_count <= 0:
        workflow["status"] = "FAILED_ANALYZE_BATCH"
        workflow["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        workflow_path = _compat("_persist_workflow_run")(workflow)
        workflow["workflow_run_path"] = str(workflow_path)
        console.print("[red]Workflow failed at analyze-batch[/red]")
        console.print(f"[cyan]Workflow artifact:[/cyan] {workflow_path}")
        raise typer.Exit(1)
    if analyze_return_code != 0:
        if bool(continue_on_batch_failure):
            workflow["steps"]["analyze_batch"]["continue_reason"] = "continue_on_batch_failure"
        elif analyze_success_count > 0:
            workflow["steps"]["analyze_batch"]["continue_reason"] = "partial_success"
    console.print(
        f"[green]Deep analysis complete[/green] | processed={analyze_processed} | "
        f"success={analyze_success_count} | failed={analyze_failure_count}"
    )

    plan_args = [
        "portfolio-plan",
        "--queue-date",
        run_date_hint,
        "--capital-usd",
        str(float(capital_usd)),
        "--max-positions",
        str(int(max_positions)),
        "--min-score",
        str(float(min_score)),
        "--min-confidence",
        str(int(min_confidence)),
        "--max-weight-per-position",
        str(float(max_weight_per_position)),
        "--execution-mode",
        str(execution_mode),
    ]
    if include_hedges:
        plan_args.append("--include-hedges")
    else:
        plan_args.append("--skip-hedges")
    if include_cc_wyckoff:
        plan_args.append("--include-cc-wyckoff")
    else:
        plan_args.append("--skip-cc-wyckoff")
    if long_only:
        plan_args.append("--long-only")
    else:
        plan_args.append("--allow-shorts")

    plan_exec = _compat("_run_cli_subcommand_json")(args=plan_args, timeout=None)
    plan_payload = plan_exec.get("payload") if isinstance(plan_exec.get("payload"), dict) else {}
    hedge_context_payload = (
        plan_payload.get("hedge_context", {})
        if isinstance(plan_payload.get("hedge_context"), dict)
        else {}
    )
    hedge_decision_payload = (
        hedge_context_payload.get("decision", {})
        if isinstance(hedge_context_payload.get("decision"), dict)
        else {}
    )
    cc_wyckoff_payload = (
        plan_payload.get("cc_wyckoff_context", {})
        if isinstance(plan_payload.get("cc_wyckoff_context"), dict)
        else {}
    )
    workflow["steps"]["portfolio_plan"] = {
        "return_code": int(plan_exec.get("return_code", 1)),
        "plan_id": str(plan_payload.get("plan_id") or ""),
        "orders": len(plan_payload.get("orders", [])) if isinstance(plan_payload.get("orders"), list) else 0,
        "plan_path": str(plan_payload.get("plan_path") or ""),
        "hedges_enabled": bool(include_hedges),
        "hedge_status": str(hedge_decision_payload.get("status") or ""),
        "hedge_action": str(hedge_decision_payload.get("action") or ""),
        "hedge_instrument": str(hedge_decision_payload.get("instrument") or ""),
        "cc_wyckoff_enabled": bool(include_cc_wyckoff),
        "cc_wyckoff_signals": int(cc_wyckoff_payload.get("signals", 0) or 0),
    }
    if int(plan_exec.get("return_code", 1)) != 0:
        workflow["status"] = "FAILED_PORTFOLIO_PLAN"
        workflow["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        workflow_path = _compat("_persist_workflow_run")(workflow)
        workflow["workflow_run_path"] = str(workflow_path)
        console.print("[red]Workflow failed at portfolio-plan[/red]")
        console.print(f"[cyan]Workflow artifact:[/cyan] {workflow_path}")
        raise typer.Exit(1)
    console.print(
        f"[green]Portfolio plan complete[/green] | plan_id={workflow['steps']['portfolio_plan']['plan_id'] or 'N/A'} | "
        f"orders={workflow['steps']['portfolio_plan']['orders']}"
    )

    execute_payload: Dict[str, Any] = {}
    if run_execution:
        execute_args = [
            "execute-paper",
            "--execution-mode",
            str(execution_mode),
        ]
        plan_path = str(plan_payload.get("plan_path") or "").strip()
        if plan_path:
            execute_args.extend(["--plan-path", plan_path])
        execute_exec = _compat("_run_cli_subcommand_json")(args=execute_args, timeout=None)
        execute_payload = execute_exec.get("payload") if isinstance(execute_exec.get("payload"), dict) else {}
        workflow["steps"]["execute"] = {
            "return_code": int(execute_exec.get("return_code", 1)),
            "submitted_orders": int(execute_payload.get("submitted_orders", 0) or 0),
            "executed_orders": int(execute_payload.get("executed_orders", 0) or 0),
            "duplicates_skipped": int(execute_payload.get("skipped_duplicate_orders", 0) or 0),
            "risk_check": dict(execute_payload.get("risk_check", {}))
            if isinstance(execute_payload.get("risk_check"), dict)
            else {},
        }
        if int(execute_exec.get("return_code", 1)) != 0:
            workflow["status"] = "FAILED_EXECUTION"
            workflow["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            workflow_path = _compat("_persist_workflow_run")(workflow)
            workflow["workflow_run_path"] = str(workflow_path)
            console.print("[red]Workflow failed at execute-paper[/red]")
            console.print(f"[cyan]Workflow artifact:[/cyan] {workflow_path}")
            raise typer.Exit(1)
        console.print(
            f"[green]Execution complete[/green] | submitted={workflow['steps']['execute']['submitted_orders']} | "
            f"executed={workflow['steps']['execute']['executed_orders']}"
        )
    else:
        workflow["steps"]["execute"] = {"skipped": True}

    normalized_mode = str(execution_mode or "paper").lower().replace("_", "-")
    if run_sync and normalized_mode.startswith("alpaca"):
        sync_args = [
            "execution-sync",
            "--broker",
            "alpaca",
            "--mode",
            normalized_mode,
            "--once",
        ]
        if apply_exits:
            sync_args.append("--apply-exits")
        else:
            sync_args.append("--skip-exits")
        if require_ready:
            sync_args.append("--require-ready")
        else:
            sync_args.append("--skip-ready-check")
        if manage_open_orders:
            sync_args.append("--manage-open-orders")
            if manage_open_orders_apply:
                sync_args.append("--manage-open-orders-apply")
            else:
                sync_args.append("--manage-open-orders-dry-run")
        else:
            sync_args.append("--skip-manage-open-orders")
        if sync_shadow_positions:
            sync_args.append("--sync-shadow-positions")
            if sync_shadow_positions_apply:
                sync_args.append("--sync-shadow-positions-apply")
            else:
                sync_args.append("--sync-shadow-positions-dry-run")
            if sync_shadow_positions_drop_missing:
                sync_args.append("--sync-shadow-positions-drop-missing")
            else:
                sync_args.append("--sync-shadow-positions-keep-missing")
        else:
            sync_args.append("--skip-shadow-positions-sync")

        sync_exec = _compat("_run_cli_subcommand_json")(args=sync_args, timeout=None)
        sync_payload = sync_exec.get("payload") if isinstance(sync_exec.get("payload"), dict) else {}
        workflow["steps"]["execution_sync"] = {
            "return_code": int(sync_exec.get("return_code", 1)),
            "snapshot_orders": int(sync_payload.get("snapshot_orders", 0) or 0),
            "matched_orders": int(sync_payload.get("matched_orders", 0) or 0),
            "fills_applied": int(sync_payload.get("fills_applied", 0) or 0),
            "status_updates": int(sync_payload.get("status_updates", 0) or 0),
            "execution_readiness": dict(sync_payload.get("execution_readiness", {}))
            if isinstance(sync_payload.get("execution_readiness"), dict)
            else {},
        }
        if int(sync_exec.get("return_code", 1)) != 0:
            workflow["status"] = "FAILED_EXECUTION_SYNC"
            workflow["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            workflow_path = _compat("_persist_workflow_run")(workflow)
            workflow["workflow_run_path"] = str(workflow_path)
            console.print("[red]Workflow failed at execution-sync[/red]")
            console.print(f"[cyan]Workflow artifact:[/cyan] {workflow_path}")
            raise typer.Exit(1)
        console.print(
            f"[green]Execution sync complete[/green] | matched={workflow['steps']['execution_sync']['matched_orders']} | "
            f"fills={workflow['steps']['execution_sync']['fills_applied']}"
        )
    else:
        workflow["steps"]["execution_sync"] = {
            "skipped": True,
            "reason": "Execution mode is not alpaca-* or run-sync disabled.",
        }

    learning_result = _compat("run_learning_cycle")(source_date=run_date_hint)
    workflow["steps"]["learning"] = dict(learning_result)
    console.print(
        f"[green]Learning status[/green] | "
        f"{str(learning_result.get('learning_status') or 'UNKNOWN').upper()}"
    )

    analyze_step = dict(workflow["steps"].get("analyze_batch", {}))
    if int(analyze_step.get("failure_count", 0) or 0) > 0:
        workflow["status"] = "COMPLETED_WITH_ANALYZE_FAILURES"
    elif str(learning_result.get("learning_status") or "").upper() in {"DEGRADED", "BLOCKED"}:
        workflow["status"] = "COMPLETED_WITH_LEARNING_DEGRADED"
    else:
        workflow["status"] = "SUCCESS"
    workflow["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    workflow_path = _compat("_persist_workflow_run")(workflow)
    workflow["workflow_run_path"] = str(workflow_path)

    try:
        _compat("RatingAuditLog")().log_event(
            "WORKFLOW_RUN_COMPLETED",
            str(shortlist.get("run_id") or run_date_hint),
            {
                "status": workflow.get("status"),
                "date": run_date_hint,
                "profile": run_profile,
                "execution_mode": normalized_mode,
                "workflow_run_path": str(workflow_path),
            },
        )
    except Exception:
        pass

    console.print(
        f"[yellow]Interactive workflow complete[/yellow] | date={run_date_hint} | "
        f"status={workflow.get('status')}"
    )
    console.print(f"[cyan]Workflow artifact:[/cyan] {workflow_path}")
