from cli.common import *  # noqa: F401,F403
from tradingagents.dealflow.scenario_retriever import retrieve_scenario_context
from tradingagents.dealflow.question_compiler import compile_question
from tradingagents.dealflow.investigation_runner import run_investigation
from tradingagents.dealflow.investigation_response import build_investigation_response


def _compat(name: str):
    """Return facade-patched symbol when legacy tests monkeypatch cli.commands.dealflow."""
    import sys

    facade = sys.modules.get("cli.commands.dealflow")
    if facade is not None and hasattr(facade, name):
        return getattr(facade, name)
    return globals()[name]


def _render_scout_ticker_summary(summary: Dict[str, Any]) -> None:
    console.print(
        f"[cyan]Scout tickers:[/cyan] unique={int(summary.get('total_unique_tickers', 0) or 0)} | "
        f"mentions={int(summary.get('total_mentions', 0) or 0)}"
    )
    counts = dict(summary.get("scout_counts") or {})
    if counts:
        labels = [f"{name}={count}" for name, count in counts.items()]
        console.print(f"[cyan]Scout counts:[/cyan] {', '.join(labels)}")
    tickers = list(summary.get("tickers", []) or [])
    if tickers:
        console.print(f"[cyan]Ticker handoff:[/cyan] {', '.join(str(t) for t in tickers[:60])}")

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

    pipeline = _compat("DealFlowPipeline")(config=DEFAULT_CONFIG.copy())
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

    payload = _compat("retrieve_scenario_context")(
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

    investigation_packet = _compat("compile_question")(
        question=question,
        as_of_date=run_date,
    )
    investigation_result = _compat("run_investigation")(
        investigation_packet=investigation_packet,
        as_of_date=run_date,
    )
    payload = _compat("build_investigation_response")(investigation_result=investigation_result)

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
        1,
        "--top-k",
        min=1,
        help="Deprecated; scout-only dealflow ignores this selection cap",
    ),
    trigger: str = typer.Option("manual", help="Trigger mode: daily|event|manual"),
    profile: str = typer.Option("daily", "--profile", help="Run profile: daily|max-recall|auto"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Persist scout ticker totals after discover."""
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
    pipeline = _compat("DealFlowPipeline")(config=run_config)
    scout_summary, _, normalized_signals, event_state = pipeline.collect(
        as_of_date=run_date,
        trigger=trigger_mode,
        top_k=top_k,
    )

    if output_format == "json":
        typer.echo(
            json_lib.dumps(
                {
                    "scout_ticker_summary": scout_summary,
                    "event_trigger": event_state,
                    "signal_count": len(normalized_signals),
                    "run_profile": run_profile,
                },
                indent=2,
            )
        )
        return

    console.print(
        f"[green]Collection complete[/green] | run_id={scout_summary.get('run_id')} | "
        f"signals={len(normalized_signals)}"
    )
    console.print(f"[cyan]Run profile:[/cyan] {run_profile}")
    _render_scout_ticker_summary(scout_summary)


@app.command()
def source(
    date: Optional[str] = typer.Option(None, help="Run date (YYYY-MM-DD), defaults to today"),
    top_k: int = typer.Option(
        1,
        "--top-k",
        min=1,
        help="Deprecated; scout-only dealflow ignores this selection cap",
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
    """Generate deal-flow scout ticker totals and final ticker handoff."""
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
    pipeline = _compat("DealFlowPipeline")(config=run_config)
    scout_summary, _, normalized_signals, event_state = pipeline.run(
        as_of_date=run_date,
        trigger=trigger_mode,
        top_k=top_k,
    )

    try:
        _compat("RatingAuditLog")().log_event(
            "DEALFLOW_SCOUT_TICKERS_GENERATED",
            scout_summary.get("run_id", run_date),
            {
                "total_unique_tickers": int(scout_summary.get("total_unique_tickers", 0) or 0),
                "scout_counts": dict(scout_summary.get("scout_counts", {}) or {}),
                "event_triggered": scout_summary.get("event_triggered"),
                "event_reasons": scout_summary.get("event_reasons", []),
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
                    "scout_ticker_summary": scout_summary,
                    "event_trigger": event_state,
                    "signal_count": len(normalized_signals),
                    "run_profile": run_profile,
                },
                indent=2,
            )
        )
        return

    console.print(
        f"[green]Deal-flow run complete[/green] | run_id={scout_summary.get('run_id')} | "
        f"signals={len(normalized_signals)} | event_triggered={scout_summary.get('event_triggered')}"
    )
    console.print(f"[cyan]Run profile:[/cyan] {run_profile}")
    _render_scout_ticker_summary(scout_summary)
    if scout_summary.get("event_reasons"):
        console.print(f"[cyan]Event reasons:[/cyan] {', '.join(scout_summary.get('event_reasons', []))}")
    _render_discovery_delta_summary(getattr(pipeline, "_last_discovery_delta", {}))


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
        1,
        "--top-k",
        min=1,
        help="Deprecated; scout-only dealflow no longer ranks tickers",
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
    scheduler = _compat("DealFlowScheduler")(config=run_config)
    force_trigger = None if run_mode == "auto" else run_mode
    result = scheduler.run_once(force_trigger=force_trigger, as_of_date=date, top_k=top_k)
    result["run_profile"] = run_profile

    try:
        audit_type = "DEALFLOW_ORCHESTRATION_RUN" if result.get("ran") else "DEALFLOW_ORCHESTRATION_SKIPPED"
        _compat("RatingAuditLog")().log_event(
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
    scout_summary = result.get("scout_ticker_summary", {})
    if isinstance(scout_summary, dict):
        _render_scout_ticker_summary(scout_summary)
        if scout_summary.get("event_reasons"):
            console.print(f"[cyan]Event reasons:[/cyan] {', '.join(scout_summary.get('event_reasons', []))}")


@app.command()
def queue(
    date: Optional[str] = typer.Option(None, help="Queue date (YYYY-MM-DD). Defaults to latest."),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """View latest or dated scout ticker summary generated by deal-flow."""
    output_format = format.lower()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    root = Path("eval_results") / "deal_flow"
    if date:
        queue_path = root / date / "scout_ticker_summary.json"
    else:
        queue_path = root / "latest_scout_ticker_summary.json"
    if not queue_path.exists():
        console.print(f"[red]Scout ticker summary not found: {queue_path}[/red]")
        raise typer.Exit(1)
    queue_data = json_lib.loads(queue_path.read_text())

    if output_format == "json":
        print(json_lib.dumps(queue_data, indent=2))
        return

    console.print(f"[green]Loaded scout ticker summary[/green] from {queue_path}")
    _render_scout_ticker_summary(queue_data)
