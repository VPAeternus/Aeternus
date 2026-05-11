from cli.common import *  # noqa: F401,F403


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
    scout_summary: Dict[str, Any],
    normalized_signals: List[Dict[str, Any]],
) -> None:
    console.print(
        f"[green]Collect complete[/green] | signals={len(normalized_signals)} | "
        f"unique_tickers={int(scout_summary.get('total_unique_tickers', 0) or 0)} | "
        f"mentions={int(scout_summary.get('total_mentions', 0) or 0)}"
    )
    counts = dict(scout_summary.get("scout_counts") or {})
    if counts:
        console.print("  scout_counts: " + ", ".join(f"{k}={v}" for k, v in counts.items()))


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

    console.print("Scout ticker handoff is now going to persist. No ranking, queue, or deep research.")
    scout_summary, _, normalized_signals, event_state = pipeline.collect(
        as_of_date=run_date_hint,
        trigger="manual",
        top_k=int(top_k),
    )
    workflow["steps"]["orchestration"] = {
        "ran": True,
        "trigger": "manual",
        "reason": "interactive_manual",
        "run_id": str(scout_summary.get("run_id") or ""),
        "signal_count": len(normalized_signals),
        "total_unique_tickers": int(scout_summary.get("total_unique_tickers", 0) or 0),
        "scout_counts": dict(scout_summary.get("scout_counts", {}) or {}),
    }
    workflow["steps"]["collect"] = {
        "run_id": str(scout_summary.get("run_id") or ""),
        "signal_count": len(normalized_signals),
        "total_unique_tickers": int(scout_summary.get("total_unique_tickers", 0) or 0),
        "scout_counts": dict(scout_summary.get("scout_counts", {}) or {}),
        "event_triggered": bool(event_state.get("triggered")),
    }
    _render_interactive_collect_summary(scout_summary, normalized_signals)

    workflow["status"] = "COMPLETED"
    workflow["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    workflow_path = _compat("_persist_workflow_run")(workflow)
    workflow["workflow_run_path"] = str(workflow_path)
    console.print(f"[cyan]Workflow artifact:[/cyan] {workflow_path}")
    return
