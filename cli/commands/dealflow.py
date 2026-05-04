from cli.common import *  # noqa: F401,F403
from tradingagents.dealflow.scenario_retriever import retrieve_scenario_context
from tradingagents.dealflow.learning_loop import run_learning_cycle
from tradingagents.dealflow.question_compiler import compile_question
from tradingagents.dealflow.investigation_runner import run_investigation
from tradingagents.dealflow.investigation_response import build_investigation_response

@watchlist_app.command("add")
def watchlist_add(
    symbols: List[str],
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Add one or more ticker symbols to the manual watchlist."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    watchlist_path = _watchlist_path_from_config()
    normalized_symbols = _normalize_symbol_args(symbols)
    if not normalized_symbols:
        console.print("[red]Error: provide at least one ticker symbol[/red]")
        raise typer.Exit(1)

    ideas = [
        add_watchlist_idea(
            symbol=symbol,
            path=watchlist_path,
        )
        for symbol in normalized_symbols
    ]
    payload = {
        "action": "added",
        "count": len(ideas),
        "watchlist_path": str(watchlist_path),
        "items": ideas,
    }
    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
        return

    table = Table(title="Manual Watchlist Update")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Action", "added")
    table.add_row("Count", str(len(ideas)))
    table.add_row("Symbols", ", ".join(str(item.get("symbol", "")) for item in ideas))
    table.add_row("Path", str(watchlist_path))
    console.print(table)


@watchlist_app.command("remove")
def watchlist_remove(
    symbols: List[str],
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Deactivate one or more manual watchlist ideas by symbol."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    watchlist_path = _watchlist_path_from_config()
    normalized_symbols = _normalize_symbol_args(symbols)
    if not normalized_symbols:
        console.print("[red]Error: provide at least one ticker symbol[/red]")
        raise typer.Exit(1)

    removed_symbols = [
        symbol for symbol in normalized_symbols
        if remove_watchlist_idea(symbol=symbol, path=watchlist_path)
    ]
    payload = {
        "action": "removed" if removed_symbols else "not_found",
        "count": len(removed_symbols),
        "symbols": removed_symbols,
        "watchlist_path": str(watchlist_path),
    }
    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
        return

    if removed_symbols:
        console.print(f"[green]Removed from manual watchlist:[/green] {', '.join(removed_symbols)}")
    else:
        console.print("[yellow]No provided symbols were active in the watchlist.[/yellow]")


def _normalize_symbol_args(raw_symbols: List[str]) -> list[str]:
    normalized_symbols: list[str] = []
    seen: set[str] = set()
    for raw in raw_symbols or []:
        for part in str(raw or "").split(","):
            token = str(part or "").upper().strip().replace(".", "-")
            if not token or token in seen:
                continue
            seen.add(token)
            normalized_symbols.append(token)
    return normalized_symbols


@watchlist_app.command("list")
def watchlist_list(
    active_only: bool = typer.Option(
        True,
        "--active-only/--all",
        help="Show active watchlist entries only by default; use --all to include inactive entries.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """List manual watchlist ideas."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    watchlist_path = _watchlist_path_from_config()
    rows = list_watchlist_ideas(include_inactive=not active_only, path=watchlist_path)
    payload = {
        "watchlist_path": str(watchlist_path),
        "count": len(rows),
        "items": rows,
    }
    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
        return

    table = Table(title="Manual Watchlist")
    table.add_column("Symbol", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Sector", style="magenta")
    table.add_column("Score", justify="right")
    table.add_column("Active", justify="center")
    table.add_column("Created", style="green")
    for row in rows:
        snapshot = dict(row.get("context_snapshot", {}) or {})
        score = snapshot.get("aeternus_score")
        try:
            score_text = f"{float(score):.2f}"
        except (TypeError, ValueError):
            score_text = "None"
        table.add_row(
            str(row.get("symbol", "")),
            str(snapshot.get("display_name", "") or ""),
            str(snapshot.get("sector", "") or ""),
            score_text,
            "yes" if bool(row.get("active", True)) else "no",
            str(row.get("created_at", "")),
        )
    console.print(table)
    console.print(f"[dim]Path: {watchlist_path}[/dim]")


@watchlist_app.command("import")
def watchlist_import(
    file: Path = typer.Option(..., "--file", exists=True, readable=True, help="Input file path."),
    ttl_days: Optional[int] = typer.Option(
        None,
        "--ttl-days",
        min=1,
        help="Default TTL for imported rows without ttl_days.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Import manual watchlist ideas from JSON/line-delimited file."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    watchlist_path = _watchlist_path_from_config()
    ttl = int(ttl_days or DEFAULT_CONFIG.get("dealflow_manual_default_ttl_days", 30))
    imported, skipped = import_watchlist_ideas(file_path=file, ttl_days=ttl, path=watchlist_path)
    payload = {
        "watchlist_path": str(watchlist_path),
        "import_file": str(file),
        "imported": imported,
        "skipped": skipped,
    }
    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
        return

    console.print(
        f"[green]Watchlist import complete[/green] | imported={imported} | skipped={skipped}"
    )
    console.print(f"[dim]Path: {watchlist_path}[/dim]")


@app.command()
def discover(
    date: Optional[str] = typer.Option(None, help="Run date (YYYY-MM-DD), defaults to today"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Run all scouts (breakout, IV, insider) and build universe.  No collectors."""
    run_date = date or _today_str()
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    pipeline = DealFlowPipeline(config=DEFAULT_CONFIG.copy())
    summary = pipeline.discover(as_of_date=run_date, trigger="manual")

    if output_format == "json":
        typer.echo(json_lib.dumps(summary, indent=2, default=str))
        return

    console.print(f"[green]Discovery complete[/green] | date={run_date}")
    console.print(f"  Universe size: {summary.get('universe_size', 0)}")
    console.print(f"  Breakout discoveries: {summary.get('breakout_count', 0)}")
    console.print(f"  Technical ignition setups: {summary.get('technical_ignition_count', 0)}")
    console.print(f"  IV force-queue candidates: {summary.get('iv_force_queue_count', 0)}")
    insider = summary.get("insider_summary", {})
    if insider:
        console.print(
            f"  Insider sweep: {insider.get('new_txns', 0)} txns, "
            f"{insider.get('buy_clusters', 0)} buy / {insider.get('sell_clusters', 0)} sell clusters"
        )
    manual = summary.get("manual_symbols", [])
    if manual:
        console.print(f"  Manual watchlist: {', '.join(manual)}")
    scenario_sidecar = summary.get("scenario_sidecar_summary", {}) or {}
    if scenario_sidecar:
        console.print(
            "  Daily scenarios: "
            f"{int(scenario_sidecar.get('event_card_count', 0) or 0)} cards "
            f"(complete={int(scenario_sidecar.get('complete_count', 0) or 0)} "
            f"partial={int(scenario_sidecar.get('partial_count', 0) or 0)} "
            f"missing={int(scenario_sidecar.get('missing_count', 0) or 0)})"
        )
    scout_quality = summary.get("scout_quality_summary", {}) or {}
    if scout_quality:
        console.print(
            f"  Scout quality rows: {int(scout_quality.get('row_count', 0) or 0)}"
        )
    _render_universe_filter_summary(summary.get("universe_filter", {}))
    _render_discovery_delta_summary(summary.get("discovery_delta", {}))
    _render_evidence_integrity_summary(summary.get("evidence_integrity_summary", {}))


@app.command("scenario-retrieve")
def scenario_retrieve(
    date: Optional[str] = typer.Option(None, help="Run date (YYYY-MM-DD), defaults to today"),
    question: str = typer.Option(..., "--question", help="Scenario question to answer from internal state."),
    event_card_id: Optional[str] = typer.Option(None, "--event-card-id", help="Optional event card id to expand."),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Retrieve scenario context from internal daily artifacts without external fetches."""
    run_date = date or _today_str()
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    payload = retrieve_scenario_context(
        question=question,
        as_of_date=run_date,
        event_card_id=event_card_id,
    )

    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
        return

    console.print(f"[green]Scenario retrieval complete[/green] | date={run_date}")
    console.print(f"  Coverage: {payload.get('coverage_status')}")
    matched_cards = list(payload.get("matched_event_cards", []) or [])
    if matched_cards:
        console.print(f"  Matched cards: {', '.join(matched_cards)}")
    matched_entities = list(payload.get("matched_entities", []) or [])
    if matched_entities:
        console.print(f"  Matched entities: {', '.join(matched_entities[:10])}")
    missing_inputs = list(payload.get("missing_inputs", []) or [])
    if missing_inputs:
        console.print(f"  Missing inputs: {', '.join(missing_inputs)}")
    if bool(payload.get("wait_for_user")):
        console.print("[yellow]Waiting for user-supplied gap fill before any external retrieval.[/yellow]")


@app.command("question-investigate")
def question_investigate(
    date: Optional[str] = typer.Option(None, help="Run date (YYYY-MM-DD), defaults to today"),
    question: str = typer.Option(..., "--question", help="Question to investigate against internal pipeline artifacts."),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Run a manual question investigation over internal artifacts only."""
    run_date = date or _today_str()
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    investigation_packet = compile_question(
        question=question,
        as_of_date=run_date,
    )
    investigation_result = run_investigation(
        investigation_packet=investigation_packet,
        as_of_date=run_date,
    )
    payload = build_investigation_response(investigation_result=investigation_result)

    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
        return

    console.print(f"[green]Question investigation complete[/green] | date={run_date}")
    console.print(f"  Coverage: {payload.get('coverage_status')}")
    matched_entities = list(payload.get("matched_entities", []) or [])
    if matched_entities:
        console.print(f"  Matched entities: {', '.join(matched_entities[:10])}")
    summary = str(payload.get("summary", "")).strip()
    if summary:
        console.print(f"  Summary: {summary}")
    missing = list(payload.get("evidence_missing", []) or [])
    if missing:
        console.print(f"  Missing stages: {', '.join(missing)}")
    gap_fill_requests = list(payload.get("manual_gap_fill_requests", []) or [])
    if gap_fill_requests:
        console.print(f"  Manual gap fill requests: {', '.join(gap_fill_requests)}")
    if str(payload.get("coverage_status", "")).upper() != "COMPLETE":
        console.print("[yellow]Waiting for user-supplied gap fill before any external retrieval.[/yellow]")


@app.command("universe-filter")
def universe_filter(
    date: Optional[str] = typer.Option(None, help="Run date (YYYY-MM-DD), defaults to today"),
    status: bool = typer.Option(False, "--status", help="Show first-universe filter readiness and counts"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Inspect the first universe filter artifact produced by discover()."""
    from tradingagents.dealflow.universe_filter import load_universe_filter_report

    run_date = date or _today_str()
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    try:
        payload = load_universe_filter_report(run_date)
    except FileNotFoundError:
        console.print(
            f"[red]Universe filter artifact missing for {run_date}.[/red] "
            "Run `aeternus discover --date "
            f"{run_date}` first."
        )
        raise typer.Exit(1)

    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
        return

    if status:
        ready = bool(payload.get("overall_ready"))
        status_label = "[green]READY[/green]" if ready else "[yellow]CHECK[/yellow]"
        console.print(f"{status_label} First Universe Filter — {run_date}")

    _render_universe_filter_summary(payload)


@app.command()
def collect(
    date: Optional[str] = typer.Option(None, help="Run date (YYYY-MM-DD), defaults to today"),
    top_k: int = typer.Option(
        int(DEFAULT_CONFIG.get("dealflow_top_k", 20)),
        "--top-k",
        min=1,
        help="Shortlist size",
    ),
    trigger: str = typer.Option("manual", help="Trigger mode: daily|event|manual"),
    profile: str = typer.Option("daily", "--profile", help="Run profile: daily|max-recall|auto"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Run collectors, scoring, and ranking (no scouts).  Use after discover."""
    run_date = date or _today_str()
    trigger_mode = str(trigger or "manual").lower().strip()
    output_format = str(format or "table").lower().strip()

    if trigger_mode not in {"daily", "event", "manual"}:
        console.print("[red]Error: trigger must be one of daily|event|manual[/red]")
        raise typer.Exit(1)
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    try:
        run_profile = _resolve_run_profile(profile)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)

    run_config = _apply_run_profile_overrides(DEFAULT_CONFIG.copy(), run_profile)
    pipeline = DealFlowPipeline(config=run_config)
    shortlist, research_queue, normalized_signals, event_state = pipeline.collect(
        as_of_date=run_date,
        trigger=trigger_mode,
        top_k=top_k,
    )

    if output_format == "json":
        typer.echo(
            json_lib.dumps(
                {
                    "shortlist": shortlist,
                    "research_queue": research_queue,
                    "event_trigger": event_state,
                    "signal_count": len(normalized_signals),
                    "run_profile": run_profile,
                },
                indent=2,
            )
        )
        return

    console.print(
        f"[green]Collection complete[/green] | run_id={shortlist.get('run_id')} | "
        f"signals={len(normalized_signals)}"
    )
    console.print(f"[cyan]Run profile:[/cyan] {run_profile}")
    lane_counts = _lane_summary(shortlist.get("candidates", []))
    console.print(
        f"[cyan]Lane mix:[/cyan] CORE={lane_counts.get('CORE', 0)} | "
        f"MOMENTUM={lane_counts.get('MOMENTUM', 0)}"
    )
    _render_shortlist_table(shortlist)
    _render_fundamental_shadow_summary(shortlist.get("fundamental_shadow_summary", {}))


@app.command()
def source(
    date: Optional[str] = typer.Option(None, help="Run date (YYYY-MM-DD), defaults to today"),
    top_k: int = typer.Option(
        int(DEFAULT_CONFIG.get("dealflow_top_k", 20)),
        "--top-k",
        min=1,
        help="Shortlist size",
    ),
    trigger: str = typer.Option(
        "daily",
        help="Trigger mode: daily|event|manual",
    ),
    profile: str = typer.Option(
        "daily",
        "--profile",
        help="Run profile: daily|max-recall|auto",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Generate deal-flow shortlist and research queue artifacts."""
    run_date = date or _today_str()
    trigger_mode = trigger.lower()
    output_format = format.lower()

    if trigger_mode not in {"daily", "event", "manual"}:
        console.print("[red]Error: trigger must be one of daily|event|manual[/red]")
        raise typer.Exit(1)

    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    try:
        run_profile = _resolve_run_profile(profile)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)

    run_config = _apply_run_profile_overrides(DEFAULT_CONFIG.copy(), run_profile)
    pipeline = DealFlowPipeline(config=run_config)
    shortlist, research_queue, normalized_signals, event_state = pipeline.run(
        as_of_date=run_date,
        trigger=trigger_mode,
        top_k=top_k,
    )

    try:
        RatingAuditLog().log_event(
            "DEALFLOW_QUEUE_GENERATED",
            shortlist.get("run_id", run_date),
            {
                "shortlist_size": len(shortlist.get("candidates", [])),
                "deep_k": research_queue.get("deep_k"),
                "event_triggered": shortlist.get("event_triggered"),
                "event_reasons": shortlist.get("event_reasons", []),
                "signal_count": len(normalized_signals),
                "run_profile": run_profile,
            },
        )
    except Exception:
        pass

    if output_format == "json":
        typer.echo(
            json_lib.dumps(
                {
                    "shortlist": shortlist,
                    "research_queue": research_queue,
                    "event_trigger": event_state,
                    "signal_count": len(normalized_signals),
                    "run_profile": run_profile,
                },
                indent=2,
            )
        )
        return

    console.print(
        f"[green]Deal-flow run complete[/green] | run_id={shortlist.get('run_id')} | "
        f"signals={len(normalized_signals)} | event_triggered={shortlist.get('event_triggered')}"
    )
    console.print(f"[cyan]Run profile:[/cyan] {run_profile}")
    lane_counts = _lane_summary(shortlist.get("candidates", []))
    console.print(
        f"[cyan]Lane mix:[/cyan] CORE={lane_counts.get('CORE', 0)} | "
        f"MOMENTUM={lane_counts.get('MOMENTUM', 0)}"
    )
    top_momentum = [
        c for c in shortlist.get("candidates", []) if str(c.get("lane", "CORE")).upper() == "MOMENTUM"
    ]
    top_momentum.sort(key=lambda c: -float(c.get("asymmetry_score", 0.0)))
    if top_momentum:
        labels = ", ".join(str(c.get("symbol", "N/A")) for c in top_momentum[:5])
        console.print(f"[cyan]Top momentum names:[/cyan] {labels}")
    if shortlist.get("event_reasons"):
        console.print(f"[cyan]Event reasons:[/cyan] {', '.join(shortlist.get('event_reasons', []))}")
    connector_summary = shortlist.get("connector_health_summary")
    if isinstance(connector_summary, dict):
        statuses = connector_summary.get("status_totals", {})
        console.print(
            "[cyan]Connector health:[/cyan] "
            f"ok={statuses.get('OK', 0)} "
            f"no_data={statuses.get('NO_DATA', 0)} "
            f"errors={statuses.get('ERROR', 0)} "
            f"not_configured={statuses.get('NOT_CONFIGURED', 0)}"
        )
    x_scope = shortlist.get("x_scope_summary")
    if isinstance(x_scope, dict):
        console.print(
            "[cyan]X scope:[/cyan] "
            f"handles={int(x_scope.get('handles', 0) or 0)} "
            f"symbol_calls={int(x_scope.get('symbol_calls', 0) or 0)} "
            f"expansions={int(x_scope.get('expansions', 0) or 0)}"
        )
    manual_summary = shortlist.get("manual_merge_summary")
    if isinstance(manual_summary, dict):
        console.print(
            "[cyan]Manual merge:[/cyan] "
            f"requested={int(manual_summary.get('requested', 0) or 0)} "
            f"included={int(manual_summary.get('included', 0) or 0)} "
            f"reinforced={int(manual_summary.get('reinforced', 0) or 0)} "
            f"rejected={int(manual_summary.get('rejected', 0) or 0)}"
        )
    _render_discovery_delta_summary(getattr(pipeline, "_last_discovery_delta", {}))
    _render_evidence_integrity_summary(shortlist.get("evidence_integrity_summary", {}))
    _render_shortlist_table(shortlist)


@app.command()
def orchestrate(
    mode: str = typer.Option(
        "auto",
        help="Run mode: auto|daily|event|manual",
    ),
    date: Optional[str] = typer.Option(
        None,
        help="Optional run date (YYYY-MM-DD) for forced modes",
    ),
    top_k: int = typer.Option(
        int(DEFAULT_CONFIG.get("dealflow_top_k", 20)),
        "--top-k",
        min=1,
        help="Shortlist size when run executes",
    ),
    profile: str = typer.Option(
        "daily",
        "--profile",
        help="Run profile: daily|max-recall|auto",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Run deal-flow orchestration with daily pre-open + event cooldown policy."""
    run_mode = mode.lower().strip()
    output_format = format.lower().strip()

    if run_mode not in {"auto", "daily", "event", "manual"}:
        console.print("[red]Error: mode must be auto|daily|event|manual[/red]")
        raise typer.Exit(1)

    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    try:
        run_profile = _resolve_run_profile(profile)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)

    run_config = _apply_run_profile_overrides(DEFAULT_CONFIG.copy(), run_profile)
    scheduler = DealFlowScheduler(config=run_config)
    force_trigger = None if run_mode == "auto" else run_mode
    result = scheduler.run_once(force_trigger=force_trigger, as_of_date=date, top_k=top_k)
    result["run_profile"] = run_profile

    try:
        audit_type = "DEALFLOW_ORCHESTRATION_RUN" if result.get("ran") else "DEALFLOW_ORCHESTRATION_SKIPPED"
        RatingAuditLog().log_event(
            audit_type,
            str(result.get("run_id") or result.get("date") or "orchestrate"),
            {
                "mode": run_mode,
                "trigger": result.get("trigger"),
                "ran": bool(result.get("ran")),
                "reason": result.get("reason"),
                "signal_count": result.get("signal_count"),
                "event_trigger": result.get("event_trigger", {}),
                "house_feed_refresh": result.get("house_feed_refresh", {}),
                "x_budget_policy": result.get("x_budget_policy", {}),
                "run_profile": run_profile,
            },
        )
    except Exception:
        pass

    if output_format == "json":
        typer.echo(json_lib.dumps(result, indent=2))
        return

    if not result.get("ran"):
        console.print(
            f"[yellow]Orchestration skipped[/yellow] | date={result.get('date')} | "
            f"reason={result.get('reason')}"
        )
        console.print(f"[cyan]Run profile:[/cyan] {run_profile}")
        refresh = result.get("house_feed_refresh")
        if isinstance(refresh, dict) and refresh.get("enabled"):
            console.print(
                f"[cyan]House feed refresh:[/cyan] attempted={bool(refresh.get('attempted'))} | "
                f"refreshed={bool(refresh.get('refreshed'))} | reason={refresh.get('reason')}"
            )
        return

    console.print(
        f"[green]Orchestration run complete[/green] | trigger={result.get('trigger')} | "
        f"run_id={result.get('run_id')} | signals={result.get('signal_count')}"
    )
    console.print(f"[cyan]Run profile:[/cyan] {run_profile}")
    refresh = result.get("house_feed_refresh")
    if isinstance(refresh, dict) and refresh.get("enabled"):
        console.print(
            f"[cyan]House feed refresh:[/cyan] attempted={bool(refresh.get('attempted'))} | "
            f"refreshed={bool(refresh.get('refreshed'))} | reason={refresh.get('reason')}"
        )
    x_policy = result.get("x_budget_policy")
    if isinstance(x_policy, dict):
        rec = x_policy.get("recommended", {})
        console.print(
            f"[cyan]X budget policy:[/cyan] action={x_policy.get('action')} | "
            f"horizon={x_policy.get('horizon_used') or 'N/A'} | "
            f"calls={rec.get('max_api_calls_per_run')} | budget=${rec.get('daily_budget_usd')}"
        )
    shortlist = result.get("shortlist", {})
    if isinstance(shortlist, dict):
        lane_counts = _lane_summary(shortlist.get("candidates", []))
        console.print(
            f"[cyan]Lane mix:[/cyan] CORE={lane_counts.get('CORE', 0)} | "
            f"MOMENTUM={lane_counts.get('MOMENTUM', 0)}"
        )
        if shortlist.get("event_reasons"):
            console.print(f"[cyan]Event reasons:[/cyan] {', '.join(shortlist.get('event_reasons', []))}")
        connector_summary = shortlist.get("connector_health_summary")
        if isinstance(connector_summary, dict):
            statuses = connector_summary.get("status_totals", {})
            console.print(
                "[cyan]Connector health:[/cyan] "
                f"ok={statuses.get('OK', 0)} "
                f"no_data={statuses.get('NO_DATA', 0)} "
                f"errors={statuses.get('ERROR', 0)} "
                f"not_configured={statuses.get('NOT_CONFIGURED', 0)}"
            )
        x_scope = shortlist.get("x_scope_summary")
        if isinstance(x_scope, dict):
            console.print(
                "[cyan]X scope:[/cyan] "
                f"handles={int(x_scope.get('handles', 0) or 0)} "
                f"symbol_calls={int(x_scope.get('symbol_calls', 0) or 0)} "
                f"expansions={int(x_scope.get('expansions', 0) or 0)}"
            )
        manual_summary = shortlist.get("manual_merge_summary")
        if isinstance(manual_summary, dict):
            console.print(
                "[cyan]Manual merge:[/cyan] "
                f"requested={int(manual_summary.get('requested', 0) or 0)} "
                f"included={int(manual_summary.get('included', 0) or 0)} "
                f"reinforced={int(manual_summary.get('reinforced', 0) or 0)} "
                f"rejected={int(manual_summary.get('rejected', 0) or 0)}"
            )
        _render_shortlist_table(shortlist)


@app.command()
def queue(
    date: Optional[str] = typer.Option(None, help="Queue date (YYYY-MM-DD). Defaults to latest."),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """View latest or dated research queue generated by deal-flow."""
    output_format = format.lower()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    try:
        queue_data, queue_path = _load_research_queue(date)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if output_format == "json":
        print(json_lib.dumps(queue_data, indent=2))
        return

    console.print(f"[green]Loaded queue[/green] from {queue_path}")
    _render_queue_table(queue_data, title_suffix=f"({queue_data.get('date', 'N/A')})")


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


def _interactive_complete_x_feed(as_of_date: str) -> Dict[str, Any]:
    from tradingagents.dealflow.sources.x_feed_manual import (
        PASS_CONFIGS,
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
            raw = _read_multiline_until_end(prompt_label=f"Pass {pass_num} JSON")
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
    return readiness


def _interactive_complete_macro(as_of_date: str) -> Dict[str, Any]:
    from cli.commands.macro_prompt import _MACRO_PROMPT_TEMPLATE, _validate_macro_payload
    from tradingagents.dealflow.sources.macro import _load_macro_cache, _save_macro_cache
    from tradingagents.dealflow.sources.social_news import _extract_json_payload

    existing = _load_macro_cache(as_of_date)
    if isinstance(existing, dict) and isinstance(existing.get("sectors"), dict) and existing.get("sectors"):
        return {
            "regime": str(existing.get("regime") or ""),
            "sector_count": len(existing.get("sectors", {})),
            "dimension_count": len(existing.get("dimensions", {})) if isinstance(existing.get("dimensions"), dict) else 0,
            "path": str(Path("eval_results") / "deal_flow" / f"macro_cache_{as_of_date}.json"),
            "source": "existing",
        }

    console.rule("[bold]Macro Prompt[/bold]")
    console.print(_MACRO_PROMPT_TEMPLATE.replace("__DATE__", as_of_date))
    console.print()
    try:
        raw = _read_multiline_until_end(prompt_label="macro JSON")
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    parsed = _extract_json_payload(raw)
    if not isinstance(parsed, dict):
        console.print("[red]Invalid JSON — could not parse a JSON object[/red]")
        raise typer.Exit(1)
    try:
        result = _validate_macro_payload(parsed)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    path = _save_macro_cache(as_of_date, result)
    return {
        "regime": str(result.get("regime") or ""),
        "sector_count": len(result.get("sectors", {})),
        "dimension_count": len(result.get("dimensions", {})),
        "path": str(path),
        "source": "ingested",
    }


def _interactive_complete_earnings_options(as_of_date: str) -> Dict[str, Any]:
    from cli.commands.earnings_options_prompt import _PROMPT_TEMPLATE, _validate_payload
    from tradingagents.dealflow.sources.earnings_options_scout import (
        load_earnings_options_scout,
        save_earnings_options_scout,
    )
    from tradingagents.dealflow.sources.social_news import _extract_json_payload

    existing = load_earnings_options_scout(as_of_date)
    if isinstance(existing, dict) and isinstance(existing.get("trending"), list):
        return {
            "setup_count": len(existing.get("trending", [])),
            "path": str(Path("eval_results") / "deal_flow" / f"earnings_options_scout_{as_of_date}.json"),
            "source": "existing",
        }

    console.rule("[bold]Earnings / Options Prompt[/bold]")
    console.print(_PROMPT_TEMPLATE.replace("__DATE__", as_of_date))
    console.print()
    try:
        raw = _read_multiline_until_end(prompt_label="earnings/options JSON")
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    parsed = _extract_json_payload(raw)
    if not isinstance(parsed, dict):
        console.print("[red]Invalid JSON — could not parse a JSON object[/red]")
        raise typer.Exit(1)
    try:
        result = _validate_payload(parsed)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    path = save_earnings_options_scout(as_of_date, result)
    return {
        "setup_count": len(result.get("trending", [])),
        "path": str(path),
        "source": "ingested",
    }


def _render_interactive_discover_summary(summary: Dict[str, Any]) -> None:
    insider = summary.get("insider_summary", {}) if isinstance(summary.get("insider_summary"), dict) else {}
    console.print(
        f"[green]Discovery complete[/green] | universe={int(summary.get('universe_size', 0) or 0)} | "
        f"breakout={int(summary.get('breakout_count', 0) or 0)} | "
        f"technical_ignition={int(summary.get('technical_ignition_count', 0) or 0)} | "
        f"earnings_options={int(summary.get('earnings_options_count', 0) or 0)}"
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
        x_feed_readiness = _interactive_complete_x_feed(run_date_hint)
        workflow["steps"]["manual_x_feed"] = dict(x_feed_readiness)
        console.print(
            f"[green]Manual X-feed complete[/green] | "
            f"passes={len(x_feed_readiness.get('completed_passes', []) or [])}/"
            f"{len(x_feed_readiness.get('required_passes', []) or [])} | "
            f"merged={int(x_feed_readiness.get('merged_symbol_count', 0) or 0)}"
        )

    macro_result = _interactive_complete_macro(run_date_hint)
    workflow["steps"]["macro_prompt"] = dict(macro_result)
    console.print(
        f"[green]Macro cache saved[/green] | regime={macro_result.get('regime') or 'N/A'} | "
        f"sectors={int(macro_result.get('sector_count', 0) or 0)}"
    )

    earnings_options_result = _interactive_complete_earnings_options(run_date_hint)
    workflow["steps"]["earnings_options_prompt"] = dict(earnings_options_result)
    console.print(
        f"[green]Earnings/options scout saved[/green] | "
        f"setups={int(earnings_options_result.get('setup_count', 0) or 0)}"
    )

    run_config = _apply_run_profile_overrides(DEFAULT_CONFIG.copy(), run_profile)
    pipeline = DealFlowPipeline(config=run_config)

    console.print(
        "Following scouts are now going to run: "
        "breakout, technical_ignition, insider, FVG recall, FMA recall, earnings_options"
    )
    discover_summary = pipeline.discover(as_of_date=run_date_hint, trigger="manual")
    workflow["steps"]["discover"] = dict(discover_summary)
    _render_interactive_discover_summary(discover_summary)

    console.print(
        "Following collectors are now going to run: "
        "social_news, price_momentum, macro, smart_money, sector_rotation, "
        "fundamental_factor_shadow, insider_cluster"
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
    analyze_exec = _run_cli_subcommand_json(args=analyze_args, timeout=None)
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
        workflow_path = _persist_workflow_run(workflow)
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

    plan_exec = _run_cli_subcommand_json(args=plan_args, timeout=None)
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
        workflow_path = _persist_workflow_run(workflow)
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
        execute_exec = _run_cli_subcommand_json(args=execute_args, timeout=None)
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
            workflow_path = _persist_workflow_run(workflow)
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

        sync_exec = _run_cli_subcommand_json(args=sync_args, timeout=None)
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
            workflow_path = _persist_workflow_run(workflow)
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

    learning_result = run_learning_cycle(source_date=run_date_hint)
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
    workflow_path = _persist_workflow_run(workflow)
    workflow["workflow_run_path"] = str(workflow_path)

    try:
        RatingAuditLog().log_event(
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
        int(DEFAULT_CONFIG.get("dealflow_top_k", 20)),
        "--top-k",
        min=1,
        help="Shortlist size target for orchestration.",
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
        help="Include unselected queue names in batch run.",
    ),
    quick_unselected: bool = typer.Option(
        True,
        "--quick-unselected/--deep-unselected",
        help="Use quick path for non-selected queue names.",
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
        help="Continue workflow when analyze-batch returns non-zero.",
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
    """Run full automated workflow: orchestrate -> analyze-batch -> plan -> execute -> sync."""
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
        _run_workflow_interactive(
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
        from tradingagents.dealflow.sources.x_feed_manual import get_readiness

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
            workflow_path = _persist_workflow_run(workflow)
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
    scheduler = DealFlowScheduler(config=run_config)
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
        workflow_path = _persist_workflow_run(workflow)
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

    analyze_args = [
        "analyze-batch",
        "--queue-date",
        run_date,
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

    analyze_exec = _run_cli_subcommand_json(args=analyze_args, timeout=None)
    analyze_payload = analyze_exec.get("payload") if isinstance(analyze_exec.get("payload"), dict) else {}
    analyze_summary: Dict[str, Any] = dict(analyze_payload)
    analyze_summary_path = str(analyze_summary.get("summary_path") or "").strip()
    analyze_used_fallback_summary = False
    if not analyze_summary or not analyze_summary_path:
        try:
            fallback_summary, fallback_path = _load_batch_summary(queue_date=run_date)
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

    analyze_hard_failure = (
        analyze_return_code != 0
        and not bool(continue_on_batch_failure)
        and analyze_success_count <= 0
    )
    if analyze_hard_failure:
        workflow["status"] = "FAILED_ANALYZE_BATCH"
        workflow["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        workflow["steps"]["analyze_batch"]["stderr_tail"] = (
            str(analyze_exec.get("stderr") or "").strip().splitlines()[-1:]
        )
        workflow_path = _persist_workflow_run(workflow)
        workflow["workflow_run_path"] = str(workflow_path)
        if output_format == "json":
            typer.echo(json_lib.dumps(workflow, indent=2))
        else:
            console.print("[red]Workflow failed at analyze-batch[/red]")
            console.print(f"[cyan]Workflow artifact:[/cyan] {workflow_path}")
        raise typer.Exit(1)
    if analyze_return_code != 0:
        if bool(continue_on_batch_failure):
            workflow["steps"]["analyze_batch"]["continue_reason"] = "continue_on_batch_failure"
        elif analyze_success_count > 0:
            workflow["steps"]["analyze_batch"]["continue_reason"] = "partial_success"

    plan_args = [
        "portfolio-plan",
        "--queue-date",
        run_date,
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

    plan_exec = _run_cli_subcommand_json(args=plan_args, timeout=None)
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
        workflow_path = _persist_workflow_run(workflow)
        workflow["workflow_run_path"] = str(workflow_path)
        if output_format == "json":
            typer.echo(json_lib.dumps(workflow, indent=2))
        else:
            console.print("[red]Workflow failed at portfolio-plan[/red]")
            console.print(f"[cyan]Workflow artifact:[/cyan] {workflow_path}")
        raise typer.Exit(1)

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
        execute_exec = _run_cli_subcommand_json(args=execute_args, timeout=None)
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
            workflow_path = _persist_workflow_run(workflow)
            workflow["workflow_run_path"] = str(workflow_path)
            if output_format == "json":
                typer.echo(json_lib.dumps(workflow, indent=2))
            else:
                console.print("[red]Workflow failed at execute-paper[/red]")
                console.print(f"[cyan]Workflow artifact:[/cyan] {workflow_path}")
            raise typer.Exit(1)
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

        sync_exec = _run_cli_subcommand_json(args=sync_args, timeout=None)
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
            workflow_path = _persist_workflow_run(workflow)
            workflow["workflow_run_path"] = str(workflow_path)
            if output_format == "json":
                typer.echo(json_lib.dumps(workflow, indent=2))
            else:
                console.print("[red]Workflow failed at execution-sync[/red]")
                console.print(f"[cyan]Workflow artifact:[/cyan] {workflow_path}")
            raise typer.Exit(1)
    else:
        workflow["steps"]["execution_sync"] = {
            "skipped": True,
            "reason": "Execution mode is not alpaca-* or run-sync disabled.",
        }

    learning_result = run_learning_cycle(source_date=run_date)
    workflow["steps"]["learning"] = dict(learning_result)

    analyze_step = dict(workflow["steps"].get("analyze_batch", {}))
    if int(analyze_step.get("failure_count", 0) or 0) > 0:
        workflow["status"] = "COMPLETED_WITH_ANALYZE_FAILURES"
    elif str(learning_result.get("learning_status") or "").upper() in {"DEGRADED", "BLOCKED"}:
        workflow["status"] = "COMPLETED_WITH_LEARNING_DEGRADED"
    else:
        workflow["status"] = "SUCCESS"
    workflow["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    workflow_path = _persist_workflow_run(workflow)
    workflow["workflow_run_path"] = str(workflow_path)

    try:
        RatingAuditLog().log_event(
            "WORKFLOW_RUN_COMPLETED",
            str(orchestration.get("run_id") or run_date),
            {
                "status": workflow.get("status"),
                "date": run_date,
                "profile": run_profile,
                "execution_mode": normalized_mode,
                "workflow_run_path": str(workflow_path),
                "steps": {
                    name: {"status": step.get("return_code", 0), **step}
                    for name, step in dict(workflow.get("steps", {})).items()
                    if isinstance(step, dict)
                },
            },
        )
    except Exception:
        pass

    if output_format == "json":
        typer.echo(json_lib.dumps(workflow, indent=2))
        return

    status_color = "green" if workflow.get("status") == "SUCCESS" else "yellow"
    console.print(
        f"[{status_color}]Workflow run complete[/{status_color}] | date={run_date} | "
        f"profile={run_profile} | status={workflow.get('status')}"
    )
    console.print(f"[cyan]Workflow artifact:[/cyan] {workflow_path}")
    orchestration_step = dict(workflow["steps"].get("orchestration", {}))
    analyze_step = dict(workflow["steps"].get("analyze_batch", {}))
    plan_step = dict(workflow["steps"].get("portfolio_plan", {}))
    execute_step = dict(workflow["steps"].get("execute", {}))
    sync_step = dict(workflow["steps"].get("execution_sync", {}))
    console.print(
        f"[cyan]Orchestration:[/cyan] ran={orchestration_step.get('ran')} | "
        f"trigger={orchestration_step.get('trigger')} | signals={orchestration_step.get('signal_count', 0)}"
    )
    console.print(
        f"[cyan]Batch:[/cyan] processed={analyze_step.get('processed', 0)} | "
        f"success={analyze_step.get('success_count', 0)} | "
        f"failed={analyze_step.get('failure_count', 0)}"
    )
    console.print(
        f"[cyan]Plan:[/cyan] orders={plan_step.get('orders', 0)} | "
        f"plan_id={plan_step.get('plan_id', 'N/A')}"
    )
    if not bool(execute_step.get("skipped")):
        console.print(
            f"[cyan]Execute:[/cyan] submitted={execute_step.get('submitted_orders', 0)} | "
            f"executed={execute_step.get('executed_orders', 0)} | "
            f"duplicates={execute_step.get('duplicates_skipped', 0)}"
        )
    if not bool(sync_step.get("skipped")):
        readiness = sync_step.get("execution_readiness", {})
        ready_flag = bool(readiness.get("overall_ready")) if isinstance(readiness, dict) else None
        console.print(
            f"[cyan]Sync:[/cyan] matched={sync_step.get('matched_orders', 0)} | "
            f"fills={sync_step.get('fills_applied', 0)} | ready={ready_flag}"
        )


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
        int(DEFAULT_CONFIG.get("dealflow_top_k", 30)),
        "--top-k",
        min=1,
        help="Shortlist size target for orchestration.",
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
        help="Include unselected queue names in batch run.",
    ),
    quick_unselected: bool = typer.Option(
        True,
        "--quick-unselected/--deep-unselected",
        help="Use quick path for non-selected queue names.",
    ),
    allow_cached_report_on_failure: bool = typer.Option(
        True,
        "--allow-cached-report-on-failure/--no-allow-cached-report-on-failure",
        help="Allow cached report fallback on analyze failures.",
    ),
    continue_on_batch_failure: bool = typer.Option(
        False,
        "--continue-on-batch-failure/--fail-on-batch-failure",
        help="Continue workflow when analyze-batch returns non-zero.",
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

        child = _run_cli_subcommand_json(args=args, timeout=None)
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
    loop_path = _persist_workflow_loop_run(result)
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


@app.command("x-discovery")
def x_discovery(
    date: Optional[str] = typer.Option(
        None,
        "--date",
        help="Discovery date (YYYY-MM-DD), defaults to today.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Run weekly X account discovery candidate generation."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    run_date = date or _today_str()
    payload = run_x_account_discovery(
        as_of_date=run_date,
        config=DEFAULT_CONFIG.copy(),
    )
    out_path = persist_x_account_candidates(payload=payload, as_of_date=run_date)
    result = dict(payload)
    result["output_path"] = str(out_path)

    try:
        RatingAuditLog().log_event(
            "DEALFLOW_X_DISCOVERY_GENERATED",
            run_date,
            {
                "date": run_date,
                "candidate_count": len(payload.get("candidates", [])),
                "output_path": str(out_path),
            },
        )
    except Exception:
        pass

    if output_format == "json":
        print(json_lib.dumps(result, indent=2))
        return

    candidates = list(payload.get("candidates", []))
    console.print(
        f"[green]X discovery generated[/green] | candidates={len(candidates)} | output={out_path}"
    )
    table = Table(title=f"X Discovery Candidates ({run_date})")
    table.add_column("Rank", justify="right")
    table.add_column("Handle", style="cyan")
    table.add_column("Composite", justify="right")
    table.add_column("Quality", justify="right")
    table.add_column("Posts", justify="right")
    table.add_column("Yield", justify="right")
    table.add_column("Edge%", justify="right")
    for idx, row in enumerate(candidates, start=1):
        edge = row.get("downstream_edge_pct")
        edge_str = "N/A" if edge is None else f"{float(edge):.2f}"
        table.add_row(
            str(idx),
            str(row.get("handle", "")),
            f"{float(row.get('composite_score', 0.0)):.2f}",
            f"{float(row.get('quality_score', 0.0)):.2f}",
            str(int(row.get("posts", 0) or 0)),
            f"{float(row.get('cashtag_yield', 0.0)):.2f}",
            edge_str,
        )
    console.print(table)


@app.command("step1-readiness")
def step1_readiness(
    date: Optional[str] = typer.Option(
        None,
        "--date",
        help="Readiness date (YYYY-MM-DD), defaults to today.",
    ),
    persist: bool = typer.Option(
        True,
        "--persist/--no-persist",
        help="Persist readiness artifact to eval_results/deal_flow.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Evaluate Step 1 completion gates for Deal Flow."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    run_date = date or _today_str()
    snapshot = evaluate_step1_readiness(
        config=DEFAULT_CONFIG.copy(),
        as_of_date=run_date,
    )
    output_path = None
    if persist:
        output_path = persist_step1_readiness(snapshot, as_of_date=run_date)
        snapshot["output_path"] = str(output_path)

    try:
        RatingAuditLog().log_event(
            "DEALFLOW_STEP1_READINESS_EVALUATED",
            run_date,
            {
                "overall_ready": bool(snapshot.get("overall_ready")),
                "gates": snapshot.get("gates", {}),
                "blockers": snapshot.get("blockers", []),
                "output_path": str(output_path) if output_path else "",
            },
        )
    except Exception:
        pass

    if output_format == "json":
        print(json_lib.dumps(snapshot, indent=2))
        return

    ready = bool(snapshot.get("overall_ready"))
    status_label = "[green]READY[/green]" if ready else "[yellow]NOT READY[/yellow]"
    console.print(f"[cyan]Step 1 Readiness:[/cyan] {status_label} (as_of={run_date})")
    if output_path:
        console.print(f"[cyan]Artifact:[/cyan] {output_path}")

    gates = snapshot.get("gates", {})
    stability = gates.get("stability", {})
    attribution = gates.get("attribution_sample", {})
    connector = gates.get("connector_policy", {})
    evidence = gates.get("evidence_quality", {})

    gate_table = Table(title="Step 1 Gate Status")
    gate_table.add_column("Gate", style="cyan")
    gate_table.add_column("Pass", justify="center")
    gate_table.add_column("Observed", style="white")
    gate_table.add_column("Required", style="magenta")
    gate_table.add_row(
        "Stability",
        "yes" if bool(stability.get("pass")) else "no",
        str(stability.get("consecutive_stable_cycles", 0)),
        str(stability.get("required_stable_cycles", 0)),
    )
    gate_table.add_row(
        "Attribution 5d",
        "yes" if int(attribution.get("evaluated_5d", 0)) >= int(attribution.get("required_5d", 0)) else "no",
        str(attribution.get("evaluated_5d", 0)),
        str(attribution.get("required_5d", 0)),
    )
    gate_table.add_row(
        "Attribution 20d",
        "yes" if int(attribution.get("evaluated_20d", 0)) >= int(attribution.get("required_20d", 0)) else "no",
        str(attribution.get("evaluated_20d", 0)),
        str(attribution.get("required_20d", 0)),
    )
    gate_table.add_row(
        "Connector Policy",
        "yes" if bool(connector.get("pass")) else "no",
        f"missing={len(connector.get('missing_connectors', []))}, degraded={len(connector.get('degraded_connectors', []))}",
        "0 missing/degraded",
    )
    gate_table.add_row(
        "Evidence Quality",
        "yes" if bool(evidence.get("pass")) else "no",
        (
            f"windows={evidence.get('walkforward_windows', 0)}, "
            f"regimes={evidence.get('regime_slices', 0)}, "
            f"status={evidence.get('status', 'N/A')}"
        ),
        (
            f"windows>={evidence.get('required_walkforward_windows', 'N/A')}, "
            f"regimes>={evidence.get('required_regime_slices', 'N/A')}"
        ),
    )
    console.print(gate_table)

    targets = snapshot.get("production_targets", {})
    target_table = Table(title="Target Sample Progress")
    target_table.add_column("Horizon", style="cyan")
    target_table.add_column("Observed", justify="right")
    target_table.add_column("Target", justify="right")
    target_table.add_column("Met", justify="center")
    target_table.add_row(
        "5d",
        str(attribution.get("evaluated_5d", 0)),
        str(targets.get("evaluated_5d_target", 0)),
        "yes" if bool(targets.get("evaluated_5d_met")) else "no",
    )
    target_table.add_row(
        "20d",
        str(attribution.get("evaluated_20d", 0)),
        str(targets.get("evaluated_20d_target", 0)),
        "yes" if bool(targets.get("evaluated_20d_met")) else "no",
    )
    console.print(target_table)

    blockers = list(snapshot.get("blockers", []))
    if blockers:
        console.print("[yellow]Blocking items:[/yellow]")
        for blocker in blockers:
            console.print(f"- {blocker}")


@app.command("evidence-pack")
def evidence_pack(
    from_date: Optional[str] = typer.Option(
        None,
        "--from-date",
        help="Evidence start date (YYYY-MM-DD). Defaults to --to-date.",
    ),
    to_date: Optional[str] = typer.Option(
        None,
        "--to-date",
        help="Evidence end date (YYYY-MM-DD). Defaults to today.",
    ),
    extra_benchmark: List[str] = typer.Option(
        [],
        "--extra-benchmark",
        help="Optional extra benchmark symbol. Repeatable.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Build and persist the full Step 2 evidence pack."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    run_to_date = str(to_date or _today_str())
    run_from_date = str(from_date or run_to_date)
    try:
        pack, artifacts = build_evidence_pack(
            from_date=run_from_date,
            to_date=run_to_date,
            config=DEFAULT_CONFIG.copy(),
            extra_benchmarks=extra_benchmark,
        )
    except Exception as exc:
        console.print(f"[red]Evidence pack failed:[/red] {exc}")
        raise typer.Exit(1)

    if output_format == "json":
        print(json_lib.dumps(pack, indent=2))
        return

    console.print(
        "[green]Evidence pack generated[/green] | "
        f"status={pack.get('status')} | sample_days={pack.get('sample_days')}"
    )
    console.print(f"[cyan]Evidence artifact:[/cyan] {artifacts.get('evidence_pack')}")
    table = Table(title=f"Evidence Pack ({pack.get('from_date')} -> {pack.get('to_date')})")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")
    readiness = pack.get("readiness_summary", {})
    table.add_row("Status", str(pack.get("status", "UNKNOWN")))
    table.add_row("Sample Days", str(pack.get("sample_days", 0)))
    table.add_row("Walkforward Windows", str(readiness.get("walkforward_windows", 0)))
    table.add_row("Regime Slices", str(readiness.get("regime_slices", 0)))
    table.add_row("Edge Decay 5d", str(readiness.get("edge_decay_5d_pct")))
    table.add_row("Edge Decay 20d", str(readiness.get("edge_decay_20d_pct")))
    table.add_row("Primary Benchmark", str((pack.get("benchmarks") or {}).get("primary", "SPY")))
    table.add_row("Secondary Benchmark", str((pack.get("benchmarks") or {}).get("secondary", "QQQ")))
    table.add_row("Extra Benchmarks", ", ".join((pack.get("benchmarks") or {}).get("extra", [])) or "None")
    console.print(table)


@app.command("evidence-regimes")
def evidence_regimes(
    date: Optional[str] = typer.Option(
        None,
        "--date",
        help="Regime date (YYYY-MM-DD). Defaults to today.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Build deterministic regime report for a date."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    run_date = str(date or _today_str())
    try:
        report, path = build_evidence_regimes(
            date=run_date,
            config=DEFAULT_CONFIG.copy(),
        )
    except Exception as exc:
        console.print(f"[red]Evidence regimes failed:[/red] {exc}")
        raise typer.Exit(1)

    if output_format == "json":
        print(json_lib.dumps(report, indent=2))
        return

    console.print(f"[green]Evidence regimes generated[/green] | artifact={path}")
    table = Table(title=f"Regime Report ({run_date})")
    table.add_column("Date", style="cyan")
    table.add_column("Regime", style="yellow")
    table.add_column("SPY", justify="right")
    table.add_column("VIX", justify="right")
    table.add_column("DGS10", justify="right")
    table.add_column("CPI YoY", justify="right")
    for row in report.get("date_labels", []):
        if not isinstance(row, dict):
            continue
        table.add_row(
            str(row.get("date", "")),
            str(row.get("regime", "NEUTRAL")),
            "N/A" if row.get("spy_close") is None else f"{float(row.get('spy_close')):.2f}",
            "N/A" if row.get("vix_close") is None else f"{float(row.get('vix_close')):.2f}",
            "N/A" if row.get("dgs10") is None else f"{float(row.get('dgs10')):.2f}",
            "N/A" if row.get("cpi_yoy") is None else f"{float(row.get('cpi_yoy')):.2f}",
        )
    console.print(table)


@app.command("evidence-walkforward")
def evidence_walkforward(
    from_date: str = typer.Option(
        ...,
        "--from-date",
        help="Walkforward start date (YYYY-MM-DD).",
    ),
    to_date: str = typer.Option(
        ...,
        "--to-date",
        help="Walkforward end date (YYYY-MM-DD).",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Build walk-forward report from persisted batch artifacts."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    try:
        report, path = build_evidence_walkforward(
            from_date=from_date,
            to_date=to_date,
            config=DEFAULT_CONFIG.copy(),
        )
    except Exception as exc:
        console.print(f"[red]Evidence walkforward failed:[/red] {exc}")
        raise typer.Exit(1)

    if output_format == "json":
        print(json_lib.dumps(report, indent=2))
        return

    console.print(
        "[green]Evidence walkforward generated[/green] | "
        f"status={report.get('status')} | windows={report.get('windows_count', 0)} | artifact={path}"
    )
    table = Table(title=f"Walkforward Windows ({from_date} -> {to_date})")
    table.add_column("Window", style="cyan")
    table.add_column("Train", style="white")
    table.add_column("Test", style="white")
    table.add_column("Drift 5d", justify="right")
    table.add_column("Drift 20d", justify="right")
    for row in report.get("windows", []):
        if not isinstance(row, dict):
            continue
        table.add_row(
            str(row.get("window_id", "")),
            f"{row.get('train_start', '')}..{row.get('train_end', '')}",
            f"{row.get('test_start', '')}..{row.get('test_end', '')}",
            "N/A" if row.get("drift_5d_pct") is None else f"{float(row.get('drift_5d_pct')):.3f}",
            "N/A" if row.get("drift_20d_pct") is None else f"{float(row.get('drift_20d_pct')):.3f}",
        )
    console.print(table)


@app.command("evidence-ablation")
def evidence_ablation(
    from_date: str = typer.Option(
        ...,
        "--from-date",
        help="Ablation start date (YYYY-MM-DD).",
    ),
    to_date: str = typer.Option(
        ...,
        "--to-date",
        help="Ablation end date (YYYY-MM-DD).",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Build signal-family ablation report from persisted batch artifacts."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    try:
        report, path = build_evidence_ablation(
            from_date=from_date,
            to_date=to_date,
            config=DEFAULT_CONFIG.copy(),
        )
    except Exception as exc:
        console.print(f"[red]Evidence ablation failed:[/red] {exc}")
        raise typer.Exit(1)

    if output_format == "json":
        print(json_lib.dumps(report, indent=2))
        return

    console.print(
        "[green]Evidence ablation generated[/green] | "
        f"families={report.get('family_count', 0)} | runs={report.get('runs_evaluated', 0)} | artifact={path}"
    )
    table = Table(title=f"Ablation ({from_date} -> {to_date})")
    table.add_column("Family", style="cyan")
    table.add_column("Runs", justify="right")
    table.add_column("Turnover", justify="right")
    table.add_column("Delta 5d", justify="right")
    table.add_column("Delta 20d", justify="right")
    table.add_column("Lane Delta (M)", justify="right")
    for row in report.get("families", []):
        if not isinstance(row, dict):
            continue
        lane_mix = row.get("lane_mix_delta", {})
        table.add_row(
            str(row.get("family", "")),
            str(int(row.get("runs_evaluated", 0) or 0)),
            f"{float(row.get('avg_selection_turnover', 0.0)):.3f}",
            "N/A" if row.get("avg_edge_delta_5d_pct") is None else f"{float(row.get('avg_edge_delta_5d_pct')):.3f}",
            "N/A" if row.get("avg_edge_delta_20d_pct") is None else f"{float(row.get('avg_edge_delta_20d_pct')):.3f}",
            f"{float((lane_mix or {}).get('MOMENTUM', 0.0)):.3f}",
        )
    console.print(table)


@app.command("evidence-telemetry")
def evidence_telemetry(
    from_date: str = typer.Option(
        ...,
        "--from-date",
        help="Telemetry start date (YYYY-MM-DD).",
    ),
    to_date: str = typer.Option(
        ...,
        "--to-date",
        help="Telemetry end date (YYYY-MM-DD).",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Build Step 3 cost/alpha telemetry and feature-family dashboard artifacts."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    try:
        report, artifacts = build_evidence_telemetry(
            from_date=from_date,
            to_date=to_date,
            config=DEFAULT_CONFIG.copy(),
        )
    except Exception as exc:
        console.print(f"[red]Evidence telemetry failed:[/red] {exc}")
        raise typer.Exit(1)

    if output_format == "json":
        print(json_lib.dumps(report, indent=2))
        return

    totals = report.get("totals", {}) if isinstance(report, dict) else {}
    alpha = report.get("alpha", {}) if isinstance(report, dict) else {}
    efficiency = report.get("efficiency", {}) if isinstance(report, dict) else {}
    dashboard = report.get("feature_family_dashboard", {}) if isinstance(report, dict) else {}
    source_ablation = report.get("source_ablation", {}) if isinstance(report, dict) else {}
    dashboard_rows = dashboard.get("rows", []) if isinstance(dashboard, dict) else []
    if not isinstance(dashboard_rows, list):
        dashboard_rows = []
    source_rows = source_ablation.get("sources", []) if isinstance(source_ablation, dict) else []
    if not isinstance(source_rows, list):
        source_rows = []

    console.print(
        "[green]Evidence telemetry generated[/green] | "
        f"sample_days={report.get('sample_days', 0)} | "
        f"estimated_x_cost=${float(totals.get('estimated_x_cost_usd', 0.0) or 0.0):.2f}"
    )
    console.print(f"[cyan]Telemetry artifact:[/cyan] {artifacts.get('cost_alpha_telemetry')}")
    console.print(f"[cyan]Dashboard artifact:[/cyan] {artifacts.get('feature_family_dashboard')}")
    console.print(f"[cyan]Source ablation artifact:[/cyan] {artifacts.get('source_ablation_report')}")

    summary_table = Table(title=f"Cost/Alpha Telemetry ({from_date} -> {to_date})")
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", style="white")
    summary_table.add_row("Sample Days", str(report.get("sample_days", 0)))
    summary_table.add_row("Processed", str(int(totals.get("processed", 0) or 0)))
    summary_table.add_row("Success", str(int(totals.get("success_count", 0) or 0)))
    summary_table.add_row("Failures", str(int(totals.get("failure_count", 0) or 0)))
    summary_table.add_row("Estimated X API Calls", str(int(totals.get("estimated_x_api_calls", 0) or 0)))
    summary_table.add_row(
        "Estimated X Cost (USD)",
        f"{float(totals.get('estimated_x_cost_usd', 0.0) or 0.0):.2f}",
    )
    hz5 = alpha.get("5d", {}) if isinstance(alpha, dict) else {}
    hz20 = alpha.get("20d", {}) if isinstance(alpha, dict) else {}
    summary_table.add_row(
        "Alpha 5d (edge %)",
        "N/A"
        if hz5.get("avg_strategy_edge_vs_benchmark_pct") is None
        else f"{float(hz5.get('avg_strategy_edge_vs_benchmark_pct')):.3f}",
    )
    summary_table.add_row(
        "Alpha 20d (edge %)",
        "N/A"
        if hz20.get("avg_strategy_edge_vs_benchmark_pct") is None
        else f"{float(hz20.get('avg_strategy_edge_vs_benchmark_pct')):.3f}",
    )
    summary_table.add_row(
        "Efficiency 5d (bps/USD)",
        "N/A"
        if (efficiency.get("5d_edge_bps_per_usd") is None)
        else f"{float(efficiency.get('5d_edge_bps_per_usd')):.3f}",
    )
    summary_table.add_row(
        "Efficiency 20d (bps/USD)",
        "N/A"
        if (efficiency.get("20d_edge_bps_per_usd") is None)
        else f"{float(efficiency.get('20d_edge_bps_per_usd')):.3f}",
    )
    console.print(summary_table)

    family_table = Table(title="Feature-Family Dashboard (Top Priority)")
    family_table.add_column("Rank", justify="right")
    family_table.add_column("Family", style="cyan")
    family_table.add_column("Share", justify="right")
    family_table.add_column("Cost USD", justify="right")
    family_table.add_column("Abl Δ20d", justify="right")
    family_table.add_column("Edge 20d", justify="right")
    family_table.add_column("Eff 20d", justify="right")
    for row in dashboard_rows[:10]:
        if not isinstance(row, dict):
            continue
        family_table.add_row(
            str(int(row.get("rank", 0) or 0)),
            str(row.get("family", "")),
            f"{float(row.get('signal_share', 0.0) or 0.0):.3f}",
            f"{float(row.get('allocated_cost_usd', 0.0) or 0.0):.2f}",
            "N/A"
            if row.get("ablation_delta_20d_pct") is None
            else f"{float(row.get('ablation_delta_20d_pct')):.3f}",
            "N/A"
            if row.get("alpha_edge_20d_pct") is None
            else f"{float(row.get('alpha_edge_20d_pct')):.3f}",
            "N/A"
            if row.get("efficiency_20d_edge_bps_per_usd") is None
            else f"{float(row.get('efficiency_20d_edge_bps_per_usd')):.3f}",
        )
    console.print(family_table)

    source_table = Table(title="Source Alpha per Dollar (Top Priority)")
    source_table.add_column("Rank", justify="right")
    source_table.add_column("Source", style="cyan")
    source_table.add_column("Cost USD", justify="right")
    source_table.add_column("Contrib 20d", justify="right")
    source_table.add_column("ROI 20d", justify="right")
    source_table.add_column("Turnover", justify="right")
    for row in source_rows[:10]:
        if not isinstance(row, dict):
            continue
        source_table.add_row(
            str(int(row.get("rank", 0) or 0)),
            str(row.get("source", "")),
            f"{float(row.get('estimated_cost_usd', 0.0) or 0.0):.2f}",
            "N/A"
            if row.get("alpha_contribution_20d_pct") is None
            else f"{float(row.get('alpha_contribution_20d_pct')):.3f}",
            "N/A"
            if row.get("alpha_per_dollar_20d_bps") is None
            else f"{float(row.get('alpha_per_dollar_20d_bps')):.3f}",
            f"{float(row.get('avg_selection_turnover', 0.0) or 0.0):.3f}",
        )
    console.print(source_table)


@app.command("hindsight")
def hindsight(
    source_date: str = typer.Option(
        ...,
        "--source-date",
        help="Deal flow run date (YYYY-MM-DD) to evaluate.",
    ),
    benchmark: str = typer.Option("QQQ", "--benchmark", help="Benchmark ticker."),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Evaluate 5-day forward returns for all deal-flow tickers vs scoring filter."""
    from tradingagents.dealflow.hindsight import compute_hindsight

    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    try:
        result = compute_hindsight(source_date=source_date, benchmark=benchmark)
    except FileNotFoundError as exc:
        console.print(f"[red]Missing artifact:[/red] {exc}")
        raise typer.Exit(1)

    if result.get("error"):
        console.print(f"[yellow]{result['error']}[/yellow]")
        if "T+5" in str(result.get("error", "")) or "Insufficient" in str(result.get("error", "")):
            console.print(f"[dim]Run after eval_date passes (source={source_date})[/dim]")
        if output_format == "json":
            typer.echo(json_lib.dumps(result, indent=2))
        raise typer.Exit(1)

    if output_format == "json":
        typer.echo(json_lib.dumps(result, indent=2))
        return

    bm_ret = result.get("benchmark_return_5d")
    bm_str = "N/A" if bm_ret is None else f"{bm_ret * 100:.2f}%"
    console.print(
        f"[green]Hindsight report[/green] | source={result['source_date']} | "
        f"eval={result['eval_date']} | benchmark={result['benchmark']} ({bm_str})"
    )
    if result.get("output_path"):
        console.print(f"[dim]Artifact: {result['output_path']}[/dim]")

    # Cohort summary table
    cohort_table = Table(title="Cohort Performance (5-day forward)")
    cohort_table.add_column("Cohort", style="cyan")
    cohort_table.add_column("Count", justify="right")
    cohort_table.add_column("Mean Return", justify="right")
    cohort_table.add_column("Median Return", justify="right")
    cohort_table.add_column("Edge vs BM", justify="right")
    for name in ["DEPLOYED", "ANALYZED", "QUEUED", "FILTERED", "LOW_DATA"]:
        c = result.get("cohorts", {}).get(name, {})
        if int(c.get("count", 0)) == 0:
            continue
        cohort_table.add_row(
            name,
            str(c.get("count", 0)),
            "N/A" if c.get("mean_return") is None else f"{c['mean_return'] * 100:.2f}%",
            "N/A" if c.get("median_return") is None else f"{c['median_return'] * 100:.2f}%",
            "N/A" if c.get("edge_vs_benchmark") is None else f"{c['edge_vs_benchmark'] * 100:.2f}%",
        )
    console.print(cohort_table)

    _render_hypothesis_stage_summary(result.get("hypothesis_stage_summary", {}))
    _render_discovery_delta_cohort_scorecards(result.get("discovery_delta_cohorts", {}))
    _render_evidence_integrity_cohort_scorecards(result.get("evidence_integrity_cohorts", {}))

    # Rank IC
    ic = result.get("rank_ic", {})
    console.print(
        f"[cyan]Rank IC:[/cyan] core={ic.get('core_score', 'N/A')} | "
        f"momentum={ic.get('momentum_score', 'N/A')} | "
        f"triage={ic.get('triage_score', 'N/A')}"
    )

    # Missed opportunities
    missed = result.get("missed_opportunities", [])
    if missed:
        miss_table = Table(title="Missed Opportunities (FILTERED, edge > 2%)")
        miss_table.add_column("Ticker", style="cyan")
        miss_table.add_column("5d Return", justify="right")
        miss_table.add_column("Edge", justify="right")
        miss_table.add_column("Core Score", justify="right")
        for m in missed[:15]:
            miss_table.add_row(
                str(m.get("ticker", "")),
                f"{m['return_5d'] * 100:.2f}%",
                f"{m['edge'] * 100:.2f}%",
                "N/A" if m.get("core_score") is None else f"{m['core_score']:.1f}",
            )
        console.print(miss_table)
    else:
        console.print("[dim]No missed opportunities (FILTERED edge > 2%)[/dim]")


@app.command("why-missed")
def why_missed(
    ticker: str,
    last: int = typer.Option(
        5,
        "--last",
        min=1,
        help="Inspect up to the last N runs. Hard-capped at 5.",
    ),
    hurdle: float = typer.Option(
        62.0,
        "--hurdle",
        help="Aeternus score hurdle used to classify V3 rejections.",
    ),
    benchmark: str = typer.Option("QQQ", "--benchmark", help="Benchmark ticker for forward-edge review."),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Audit why a ticker did not make it through the recent pipeline."""
    from tradingagents.dealflow.why_missed import compute_why_missed

    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    result = compute_why_missed(ticker=ticker, last=last, hurdle=hurdle, benchmark=benchmark)
    if output_format == "json":
        typer.echo(json_lib.dumps(result, indent=2))
        return

    console.print(
        f"[green]Why Missed: {result['ticker']}[/green] | "
        f"flagged={result.get('flagged_run_count', 0)}/{result.get('lookback_runs_used', 0)} recent runs | "
        f"requested={result.get('lookback_runs_requested', 0)} capped_to={result.get('lookback_runs_used', 0)}"
    )

    summary_table = Table(title="Recent Run Audit")
    summary_table.add_column("Date", style="cyan")
    summary_table.add_column("Highest Stage", style="yellow", no_wrap=True)
    summary_table.add_column("Root Cause", style="magenta", no_wrap=True)
    summary_table.add_column("Target", style="green", no_wrap=True)
    summary_table.add_column("5d Edge", justify="right")
    summary_table.add_column("X", justify="center")
    summary_table.add_column("Sig", justify="center")
    summary_table.add_column("Score", justify="center")
    summary_table.add_column("Queue", justify="center")
    summary_table.add_column("Deep", justify="center")
    summary_table.add_column("Analyzed", justify="center")
    summary_table.add_column("V3", justify="center")
    summary_table.add_column("Deployed", justify="center")
    for row in result.get("runs", []):
        summary_table.add_row(
            str(row.get("source_date", "")),
            str(row.get("highest_stage", "")),
            str(row.get("root_cause", "")),
            str(row.get("improvement_target", "") or "-"),
            "N/A"
            if row.get("edge_vs_benchmark_5d") is None
            else f"{float(row.get('edge_vs_benchmark_5d')) * 100:+.2f}%",
            "Y" if row.get("x_feed_seen") else "-",
            "Y" if row.get("signals_seen") else "-",
            "Y" if row.get("scored_seen") else "-",
            "Y" if row.get("queue_seen") else "-",
            "Y" if row.get("selected_for_deep") else "-",
            "Y" if row.get("analyzed_success") else "-",
            "Y" if row.get("v3_hurdle_cleared") else "-",
            "Y" if row.get("deployed") else "-",
        )
    console.print(summary_table)
    for row in result.get("runs", []):
        console.print(
            f"[dim]{row.get('source_date', '')}: {row.get('root_cause', '')} | "
            f"{row.get('highest_stage', '')} | target={row.get('improvement_target', '-') or '-'}[/dim]"
        )
        if row.get("review_reason"):
            console.print(f"[yellow]{row.get('review_reason')}[/yellow]")
    console.print("[dim]Operator tags: step1_baseline | shortlist_cut | review threshold: +1.00% forward edge[/dim]")


@app.command("needle-retro")
def needle_retro(
    last: int = typer.Option(5, "--last", min=1, help="Inspect up to the last N completed cycles. Hard-capped at 5."),
    benchmark: str = typer.Option("QQQ", "--benchmark", help="Benchmark ticker."),
    min_edge: float = typer.Option(0.03, "--min-edge", help="Minimum 5-day edge vs benchmark to count as a needle."),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Review recent realized false negatives to improve needle finding."""
    from tradingagents.dealflow.needle_retro import compute_needle_retro

    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    result = compute_needle_retro(last=last, benchmark=benchmark, min_edge=min_edge)
    if output_format == "json":
        typer.echo(json_lib.dumps(result, indent=2))
        return

    console.print(
        f"[green]Needle Retro[/green] | completed={result.get('cycles_completed', 0)}/{result.get('cycles_requested', 0)} | "
        f"benchmark={result.get('benchmark', benchmark)} | min_edge={float(result.get('min_edge', min_edge)) * 100:.2f}%"
    )

    stage_table = Table(title="Improvement Targets")
    stage_table.add_column("Target", style="cyan")
    stage_table.add_column("Count", justify="right")
    stage_table.add_column("Avg 5d Edge", justify="right")
    stage_table.add_column("Total 5d Edge", justify="right")
    for row in result.get("stage_summary", []):
        stage_table.add_row(
            str(row.get("improvement_target", "")),
            str(int(row.get("count", 0) or 0)),
            f"{float(row.get('avg_edge_5d', 0.0) or 0.0) * 100:+.2f}%",
            f"{float(row.get('total_edge_5d', 0.0) or 0.0) * 100:+.2f}%",
        )
    console.print(stage_table)

    opp_table = Table(title="Top False Negatives")
    opp_table.add_column("Date", style="cyan")
    opp_table.add_column("Ticker", style="green")
    opp_table.add_column("Cohort", style="yellow")
    opp_table.add_column("Root Cause", style="magenta", no_wrap=True)
    opp_table.add_column("Target", style="white", no_wrap=True)
    opp_table.add_column("5d Edge", justify="right")
    for row in result.get("opportunities", [])[:20]:
        opp_table.add_row(
            str(row.get("source_date", "")),
            str(row.get("ticker", "")),
            str(row.get("cohort", "")),
            str(row.get("root_cause", "")),
            str(row.get("improvement_target", "")),
            f"{float(row.get('edge_vs_benchmark_5d', 0.0) or 0.0) * 100:+.2f}%",
        )
    console.print(opp_table)


@app.command("hindsight-summary")
def hindsight_summary(
    last: int = typer.Option(30, "--last", help="Show last N cycles."),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Rolling summary of hindsight results from the aggregate SQLite database."""
    import sqlite3
    from tradingagents.dealflow.hindsight import _HINDSIGHT_DB

    output_format = str(format or "table").lower().strip()
    db_path = _HINDSIGHT_DB

    if not db_path.exists():
        console.print("[yellow]No hindsight database found. Run 'aeternus hindsight' for at least one cycle first.[/yellow]")
        raise typer.Exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cycles = conn.execute(
            "SELECT * FROM hindsight_cycles ORDER BY source_date DESC LIMIT ?", (last,)
        ).fetchall()
        top_misses = conn.execute(
            """SELECT ticker, COUNT(*) as appearances, AVG(return_5d) as avg_ret, AVG(edge) as avg_edge
               FROM hindsight_misses GROUP BY ticker ORDER BY appearances DESC, avg_edge DESC LIMIT 20"""
        ).fetchall()
    finally:
        conn.close()

    if not cycles:
        console.print("[yellow]No cycles in database yet.[/yellow]")
        raise typer.Exit(0)

    if output_format == "json":
        typer.echo(json_lib.dumps([dict(r) for r in cycles], indent=2))
        return

    # --- Rolling IC table ---
    ic_table = Table(title=f"Hindsight — Rolling IC & Cohort Edge (last {len(cycles)} cycles)")
    ic_table.add_column("Date", style="cyan")
    ic_table.add_column("QQQ 5d", justify="right")
    ic_table.add_column("Core IC", justify="right")
    ic_table.add_column("Mom IC", justify="right")
    ic_table.add_column("ANALYZED edge", justify="right")
    ic_table.add_column("FILTERED edge", justify="right")
    ic_table.add_column("Missed n", justify="right")

    for row in reversed(cycles):
        def _fmt_ic(v):
            if v is None:
                return "[dim]N/A[/dim]"
            color = "green" if v > 0.1 else ("red" if v < -0.1 else "yellow")
            return f"[{color}]{v:+.2f}[/{color}]"

        def _fmt_edge(v):
            if v is None:
                return "[dim]N/A[/dim]"
            color = "green" if v > 0 else "red"
            return f"[{color}]{v * 100:+.2f}%[/{color}]"

        bm = row["benchmark_return"]
        ic_table.add_row(
            row["source_date"],
            "N/A" if bm is None else f"{bm * 100:+.2f}%",
            _fmt_ic(row["ic_core"]),
            _fmt_ic(row["ic_momentum"]),
            _fmt_edge(row["analyzed_edge"]),
            _fmt_edge(row["filtered_edge"]),
            str(row["missed_count"] or 0),
        )
    console.print(ic_table)

    # --- Avg IC across all cycles ---
    valid_core = [r["ic_core"] for r in cycles if r["ic_core"] is not None]
    valid_mom = [r["ic_momentum"] for r in cycles if r["ic_momentum"] is not None]
    if valid_core:
        avg_core = sum(valid_core) / len(valid_core)
        flag = "  [red]⚠ Inverted signal — investigate score weights[/red]" if avg_core < -0.1 else ""
        console.print(f"[bold]Avg core IC:[/bold] {avg_core:+.3f} over {len(valid_core)} cycle(s){flag}")
    if valid_mom:
        avg_mom = sum(valid_mom) / len(valid_mom)
        console.print(f"[bold]Avg momentum IC:[/bold] {avg_mom:+.3f} over {len(valid_mom)} cycle(s)")

    # --- Repeat misses ---
    if top_misses:
        miss_table = Table(title="Repeat Missed Tickers (FILTERED across cycles, >2% edge)")
        miss_table.add_column("Ticker", style="yellow")
        miss_table.add_column("Appearances", justify="right")
        miss_table.add_column("Avg 5d Return", justify="right")
        miss_table.add_column("Avg Edge", justify="right")
        for m in top_misses:
            miss_table.add_row(
                m["ticker"],
                str(m["appearances"]),
                f"{m['avg_ret'] * 100:.1f}%" if m["avg_ret"] else "N/A",
                f"+{m['avg_edge'] * 100:.1f}%" if m["avg_edge"] else "N/A",
            )
        console.print(miss_table)


@app.command("stage-diagnosis")
def stage_diagnosis(
    last: int = typer.Option(20, "--last", min=1, help="Inspect the last N dated deal-flow cycles."),
    lane: str = typer.Option("shared", "--lane", help="Lane to inspect."),
    top: int = typer.Option(5, "--top", min=1, help="Number of stage rows and worst cycles to show."),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Rolling diagnosis of which funnel stages are leaking the most optionality."""
    from tradingagents.dealflow.stage_diagnosis import compute_stage_diagnosis

    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    report = compute_stage_diagnosis(last=int(last), lane=str(lane), top=int(top))

    if output_format == "json":
        typer.echo(json_lib.dumps(report, indent=2))
        return

    _render_stage_diagnosis(report)
