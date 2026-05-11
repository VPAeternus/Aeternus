from cli.common import *  # noqa: F401,F403
from tradingagents.graph.codex_research_bridge import (
    get_manual_bundle_readiness,
    ingest_manual_analyst,
    load_ticker_bundle_reports,
    run_ticker_bundle,
)
from tradingagents.dealflow.research_conversion_integrity import (
    build_research_conversion_integrity_report,
)


def _load_same_date_portfolio_plan(run_date: str) -> tuple[Optional[Dict[str, Any]], Optional[Path]]:
    plans_dir = _paper_execution_base_dir() / "plans" / str(run_date).strip()
    if not plans_dir.exists():
        return None, None
    candidates = sorted(plans_dir.glob("portfolio_plan_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            return _read_json(path), path
        except Exception:
            continue
    return None, None


def _persist_research_conversion_integrity(run_date: str, summary: Dict[str, Any]) -> Optional[Path]:
    if not str(run_date).strip():
        return None
    portfolio_plan, portfolio_path = _load_same_date_portfolio_plan(run_date)
    report = build_research_conversion_integrity_report(
        as_of_date=str(run_date).strip(),
        batch_summary=summary,
        portfolio_plan=portfolio_plan,
    )
    if portfolio_path is not None:
        report["portfolio_plan_path"] = str(portfolio_path)
    base = _dealflow_base_dir() / str(run_date).strip()
    base.mkdir(parents=True, exist_ok=True)
    path = base / "research_conversion_integrity.json"
    path.write_text(json_lib.dumps(report, indent=2))
    return path


def _run_session_engine_analysis(
    selections: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
):
    from tradingagents.graph.session_research_engine import run_session_research
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

    runtime_config = dict(DEFAULT_CONFIG)
    if isinstance(config, dict):
        runtime_config.update(config)

    provider = str(
        selections.get("analyst_provider")
        or runtime_config.get("research_analyst_provider", "claude")
    ).strip().lower()
    report_path = run_session_research(
        ticker=str(selections["ticker"]).upper().strip(),
        analysis_date=str(selections["analysis_date"]).strip(),
        provider=provider,
        source_context=selections.get("source_context"),
        config=runtime_config,
    )
    try:
        payload = _read_json(Path(report_path))
    except Exception:
        payload = {}

    score_block = payload.get("aeternus_score") if isinstance(payload, dict) else {}
    score_data = score_block if isinstance(score_block, dict) else {}
    recommendation = _extract_recommendation(str(payload.get("final_trade_decision", "")))
    if recommendation == "UNKNOWN":
        recommendation = _fallback_recommendation_from_rating(
            rating=score_data.get("rating"),
            score=score_data.get("aeternus_score"),
        )
    if score_data:
        score_data["recommendation"] = recommendation

    try:
        if score_data:
            TrackRecord().append(score_data)
    except Exception:
        pass

    try:
        rating_id = score_data.get("rating_id")
        if rating_id:
            RatingAuditLog().log_event("RATING_CREATED", rating_id, score_data)
    except Exception:
        pass

    try:
        if score_data:
            akg = AeternusKnowledgeGraph.load()
            akg.record_rating(str(selections["ticker"]).upper().strip(), score_data)
            akg.save()
    except Exception:
        pass

    console.print(
        f"[green]Session research complete[/green] | "
        f"symbol={str(selections['ticker']).upper().strip()} | "
        f"date={str(selections['analysis_date']).strip()} | "
        f"report={report_path}"
    )
    return report_path

def run_analysis(selections: Optional[Dict[str, Any]] = None):
    # Use interactive selection flow unless explicit selections are provided.
    if selections is None:
        selections = get_user_selections()

    # Create config with selected research depth
    config = DEFAULT_CONFIG.copy()
    config["quick_think_llm"] = selections["shallow_thinker"]
    config["deep_think_llm"] = selections["deep_thinker"]
    config["backend_url"] = selections["backend_url"]
    config["llm_provider"] = selections["llm_provider"].lower()
    analyst_provider = str(
        selections.get("analyst_provider")
        or config.get("research_analyst_provider", "gpt")
    ).strip().lower()
    post_analyst_provider = str(
        selections.get("post_analyst_provider")
        or config.get("research_post_analyst_provider", "claude")
    ).strip().lower()
    if post_analyst_provider == "gemini":
        raise RuntimeError("Gemini post-analyst provider is not implemented yet.")
    if post_analyst_provider == "gpt":
        config["llm_provider"] = "codex_cli"
        config["quick_think_provider"] = "codex_cli"
        config["backend_url"] = "codex_cli"
        config["quick_think_llm"] = str(config.get("codex_cli_quick_model", "gpt-5.4"))
        config["deep_think_llm"] = str(config.get("codex_cli_deep_model", "gpt-5.4"))
    elif post_analyst_provider == "claude":
        config["llm_provider"] = "claude_cli"
        config["quick_think_provider"] = "claude_cli"
        config["backend_url"] = "claude_cli"
    tool_overrides = selections.get("tool_vendors_override")
    if isinstance(tool_overrides, dict) and tool_overrides:
        merged_tool_vendors = dict(config.get("tool_vendors", {}))
        merged_tool_vendors.update({str(k): str(v) for k, v in tool_overrides.items()})
        config["tool_vendors"] = merged_tool_vendors

    use_codex_bridge = (
        analyst_provider in {"gpt", "claude", "grok_manual"}
    )
    research_execution_mode = str(
        selections.get("research_execution_mode")
        or config.get("research_execution_mode", "session_engine")
    ).strip().lower()
    if (
        research_execution_mode == "session_engine"
        and analyst_provider in {"claude", "gpt"}
    ):
        return _run_session_engine_analysis(selections, config=config)

    # Initialize the graph
    graph = TradingAgentsGraph(
        [analyst.value for analyst in selections["analysts"]], config=config, debug=True
    )

    # Create result directory
    results_dir = Path(config["results_dir"]) / selections["ticker"] / selections["analysis_date"]
    results_dir.mkdir(parents=True, exist_ok=True)
    report_dir = results_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    log_file = results_dir / "message_tool.log"
    log_file.touch(exist_ok=True)

    def save_message_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, message_type, content = obj.messages[-1]
            # Ensure content is a string
            content_str = extract_content_string(content).replace("\n", " ")
            with open(log_file, "a") as f:
                f.write(f"{timestamp} [{message_type}] {content_str}\n")
        return wrapper
    
    def save_tool_call_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, tool_name, args = obj.tool_calls[-1]
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            with open(log_file, "a") as f:
                f.write(f"{timestamp} [Tool Call] {tool_name}({args_str})\n")
        return wrapper

    def save_report_section_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(section_name, content):
            func(section_name, content)
            if section_name in obj.report_sections and obj.report_sections[section_name] is not None:
                val = obj.report_sections[section_name]
                if val:
                    # Defensive: convert dict/list to string before writing
                    if isinstance(val, (dict, list)):
                        val = json_lib.dumps(val, indent=2)
                    
                    file_name = f"{section_name}.md"
                    with open(report_dir / file_name, "w") as f:
                        f.write(str(val))
        return wrapper

    message_buffer.add_message = save_message_decorator(message_buffer, "add_message")
    message_buffer.add_tool_call = save_tool_call_decorator(message_buffer, "add_tool_call")
    message_buffer.update_report_section = save_report_section_decorator(message_buffer, "update_report_section")

    # Now start the display layout
    layout = create_layout()

    with Live(layout, refresh_per_second=4) as live:
        # Initial display
        update_display(layout)

        # Add initial messages
        message_buffer.add_message("System", f"Selected ticker: {selections['ticker']}")
        message_buffer.add_message(
            "System", f"Analysis date: {selections['analysis_date']}"
        )
        message_buffer.add_message(
            "System",
            f"Selected analysts: {', '.join(analyst.value for analyst in selections['analysts'])}",
        )
        source_context = selections.get("source_context")
        if source_context:
            message_buffer.add_message(
                "System",
                "Source context: "
                f"sector={source_context.get('sector', 'N/A')} | "
                f"lane={source_context.get('lane', 'N/A')} | "
                f"playbook={source_context.get('research_playbook', 'N/A')}",
            )
        update_display(layout)

        # Reset agent statuses
        for agent in message_buffer.agent_status:
            message_buffer.update_agent_status(agent, "pending")

        # Reset report sections
        for section in message_buffer.report_sections:
            message_buffer.report_sections[section] = None
        message_buffer.current_report = None
        message_buffer.final_report = None

        # Update agent status to in_progress for the first analyst
        first_analyst = f"{selections['analysts'][0].value.capitalize()} Analyst"
        if not use_codex_bridge:
            message_buffer.update_agent_status(first_analyst, "in_progress")
        update_display(layout)

        # Create spinner text
        spinner_text = (
            f"Analyzing {selections['ticker']} on {selections['analysis_date']}..."
        )
        update_display(layout, spinner_text)

        # Initialize state and get graph args
        init_agent_state = graph.propagator.create_initial_state(
            selections["ticker"], selections["analysis_date"]
        )
        (
            pretrade_snapshot,
            pretrade_market,
            pretrade_signal,
            pretrade_decision,
            pretrade_brief,
        ) = build_pretrade_risk_context()
        init_agent_state["portfolio_snapshot"] = pretrade_snapshot
        init_agent_state["market_regime"] = pretrade_market
        init_agent_state["hedge_signal"] = pretrade_signal
        init_agent_state["hedge_decision"] = pretrade_decision
        init_agent_state["pretrade_risk_brief"] = pretrade_brief
        if selections.get("source_context"):
            init_agent_state["source_context"] = dict(selections["source_context"])
        message_buffer.add_message(
            "System",
            "Pre-trade risk context loaded: "
            f"beta={_format_number(pretrade_snapshot.get('portfolio_beta_60d'), 3)} | "
            f"var95={_format_number(pretrade_snapshot.get('var_95_1d_pct_nav'))}% | "
            f"hedge_action={pretrade_decision.get('action', 'NO_CHANGE')} "
            f"{pretrade_decision.get('instrument', 'SPY')} "
            f"to {_format_number(pretrade_decision.get('final_target_hedge_pct'))}%",
        )
        if use_codex_bridge:
            analyst_model = (
                str(config.get("codex_cli_model", "gpt-5.4"))
                if analyst_provider == "gpt"
                else str(config.get("claude_cli_deep_model", "claude-sonnet-4-6"))
            )
            analyst_fallback_model = (
                None
                if analyst_provider == "gpt"
                else str(config.get("claude_cli_fallback_model", analyst_model))
            )
            analyst_reasoning = (
                str(config.get("codex_cli_reasoning_effort", "xhigh"))
                if analyst_provider == "gpt"
                else "n/a"
            )
            analyst_timeout = (
                int(config.get("codex_cli_timeout_seconds", 180))
                if analyst_provider == "gpt"
                else int(
                    config.get(
                        "claude_cli_analyst_timeout",
                        config.get("claude_cli_timeout", 120),
                    )
                )
            )
            analyst_retry_count = (
                0
                if analyst_provider == "gpt"
                else int(config.get("claude_cli_retry_count", 1))
            )
            bundle = run_ticker_bundle(
                repo_root=_repo_root(),
                results_root=Path(config["results_dir"]),
                ticker=selections["ticker"],
                analysis_date=selections["analysis_date"],
                provider=analyst_provider,
                model=analyst_model,
                fallback_model=analyst_fallback_model,
                reasoning_effort=analyst_reasoning,
                timeout_seconds=analyst_timeout,
                retry_count=analyst_retry_count,
            )
            if not bundle.get("complete"):
                failures = bundle.get("failures", [])
                raise RuntimeError(
                    f"Codex bridge incomplete for {selections['ticker']}: {failures}"
                )
            bundle_reports = load_ticker_bundle_reports(bundle)
            init_agent_state.update(bundle_reports)

            for section_name, content in bundle_reports.items():
                message_buffer.update_report_section(section_name, content)
            message_buffer.update_agent_status("Market Analyst", "completed")
            message_buffer.update_agent_status("News Analyst", "completed")
            message_buffer.update_agent_status("Fundamentals Analyst", "completed")
            update_research_team_status("in_progress")

        args = graph.propagator.get_graph_args()
        target_graph = graph.post_analyst_graph if use_codex_bridge else graph.graph

        # Stream the analysis
        trace = []
        for chunk in target_graph.stream(init_agent_state, **args):
            if len(chunk["messages"]) > 0:
                # Get the last message from the chunk
                last_message = chunk["messages"][-1]

                # Extract message content and type
                if hasattr(last_message, "content"):
                    content = extract_content_string(last_message.content)  # Use the helper function
                    msg_type = "Reasoning"
                else:
                    content = str(last_message)
                    msg_type = "System"

                # Add message to buffer
                message_buffer.add_message(msg_type, content)                

                # If it's a tool call, add it to tool calls
                if hasattr(last_message, "tool_calls"):
                    for tool_call in last_message.tool_calls:
                        # Handle both dictionary and object tool calls
                        if isinstance(tool_call, dict):
                            message_buffer.add_tool_call(
                                tool_call["name"], tool_call["args"]
                            )
                        else:
                            message_buffer.add_tool_call(tool_call.name, tool_call.args)

                # Update reports and agent status based on chunk content
                # Analyst Team Reports
                if not use_codex_bridge:
                    if "market_report" in chunk and chunk["market_report"]:
                        message_buffer.update_report_section(
                            "market_report", chunk["market_report"]
                        )
                        message_buffer.update_agent_status("Market Analyst", "completed")
                    if "news_report" in chunk and chunk["news_report"]:
                        message_buffer.update_report_section(
                            "news_report", chunk["news_report"]
                        )
                        message_buffer.update_agent_status("News Analyst", "completed")
                        # Set next analyst to in_progress
                        if "fundamentals" in selections["analysts"]:
                            message_buffer.update_agent_status(
                                "Fundamentals Analyst", "in_progress"
                            )

                    if "fundamentals_report" in chunk and chunk["fundamentals_report"]:
                        message_buffer.update_report_section(
                            "fundamentals_report", chunk["fundamentals_report"]
                        )
                        message_buffer.update_agent_status(
                            "Fundamentals Analyst", "completed"
                        )
                        # Set all research team members to in_progress
                        update_research_team_status("in_progress")

                # Trading Team
                if (
                    "trader_investment_plan" in chunk
                    and chunk["trader_investment_plan"]
                ):
                    message_buffer.update_report_section(
                        "trader_investment_plan", chunk["trader_investment_plan"]
                    )
                    message_buffer.update_agent_status("Trader", "completed")

                # Update the display
                update_display(layout)

            trace.append(chunk)

        # Get final state and decision
        final_state = trace[-1]
        if use_codex_bridge:
            for report_key in (
                "market_report",
                        "news_report",
                "fundamentals_report",
            ):
                if report_key not in final_state and report_key in init_agent_state:
                    final_state[report_key] = init_agent_state[report_key]
        decision = graph.process_signal(final_state["final_trade_decision"])

        # Score once with explicit identity fields for stable reporting.
        final_state["aeternus_score"] = graph.aeternus_scorer.score(
            final_state,
            ticker=selections["ticker"],
            date=selections["analysis_date"],
            fundamental_metrics=final_state.get("fundamental_metrics") or None,
            )

        # Extract thesis summary from trader plan for AKG storage
        trader_plan = final_state.get("trader_investment_plan", "")
        if trader_plan:
            first_sentence = trader_plan.split(".")[0].strip()
            thesis_summary = first_sentence[:150] if first_sentence else ""
            if thesis_summary:
                final_state["aeternus_score"]["thesis_summary"] = thesis_summary

        # Daily thesis-change check (analyze only)
        final_state["thesis_check"] = graph.thesis_checker.check(
            final_state,
            ticker=selections["ticker"],
            date=selections["analysis_date"],
        )

        # Log creation event for this rating.
        try:
            rating_id = final_state["aeternus_score"].get("rating_id")
            if rating_id:
                RatingAuditLog().log_event(
                    "RATING_CREATED",
                    rating_id,
                    final_state["aeternus_score"],
                )
        except Exception:
            pass

        # Record rating to AKG (knowledge graph)
        try:
            from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
            akg = AeternusKnowledgeGraph.load()
            akg.record_rating(selections["ticker"], final_state["aeternus_score"])
            akg.save()
        except Exception:
            pass

        try:
            (
                portfolio_snapshot,
                market_regime,
                hedge_signal,
                hedge_decision,
            ) = run_hedging_cycle(
                final_state.get("aeternus_score", {}).get("rating_id")
            )
        except Exception:
            portfolio_snapshot = {}
            market_regime = {}
            hedge_signal = {}
            hedge_decision = {
                "final_target_hedge_pct": 0.0,
                "instrument": "SPY",
                "action": "NO_CHANGE",
                "delta_hedge_pct": 0.0,
                "delta_notional_usd": 0.0,
                "reason": "Hedging cycle failed; fallback no-op applied.",
                "status": "DATA_INSUFFICIENT",
            }

        final_state["portfolio_snapshot"] = portfolio_snapshot
        final_state["market_regime"] = market_regime
        final_state["hedge_signal"] = hedge_signal
        final_state["hedge_decision"] = hedge_decision
        final_state["pretrade_risk_brief"] = init_agent_state.get("pretrade_risk_brief", "")

        # Update all agent statuses to completed
        for agent in message_buffer.agent_status:
            message_buffer.update_agent_status(agent, "completed")

        message_buffer.add_message(
            "Analysis", f"Completed analysis for {selections['analysis_date']}"
        )

        # Update final report sections
        for section in message_buffer.report_sections.keys():
            if section in final_state and section != "aeternus_score":
                val = final_state[section]
                # Ensure we only pass strings to the report sections (which trigger file writes)
                if isinstance(val, (str, list)):
                    message_buffer.update_report_section(section, extract_content_string(val))

        # Render Aeternus score for display/export
        if final_state.get("aeternus_score"):
            message_buffer.update_report_section(
                "aeternus_score",
                format_aeternus_score_markdown(
                    final_state["aeternus_score"],
                    final_state.get("thesis_check"),
                ),
            )

        # Render portfolio risk + hedge recommendation for display/export
        message_buffer.update_report_section(
            "portfolio_risk_hedge",
            format_portfolio_risk_hedge_markdown(
                final_state.get("portfolio_snapshot", {}),
                final_state.get("market_regime", {}),
                final_state.get("hedge_signal", {}),
                final_state.get("hedge_decision", {}),
            ),
        )

        # 1. Save full trace/state as JSON
        json_path = results_dir / "analysis_report.json"
        with open(json_path, "w") as f:
            def json_serial(obj):
                if isinstance(obj, (datetime.datetime, datetime.date)):
                    return obj.isoformat()
                return str(obj)
            json_lib.dump(final_state, f, indent=2, default=json_serial)

        # 2. Save Equity Research Report (MD)
        equity_report = message_buffer.get_equity_research_report(selections["ticker"], selections["analysis_date"])
        equity_report_path = results_dir / "Equity_Research_Report.md"
        with open(equity_report_path, "w") as f:
            f.write(equity_report)

        # Display the complete final report
        display_complete_report(final_state)

        message_buffer.add_message("System", f"Results saved to: {results_dir}")
        update_display(layout)




@app.command()
def score(
    ticker: str,
    date: str = typer.Option(None, help="Analysis date (YYYY-MM-DD), defaults to today"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Get Aeternus score and rating for a ticker."""

    # Use today if no date provided
    if not date:
        date = datetime.datetime.now().strftime("%Y-%m-%d")

    # Create provider-aware config for non-interactive reliability
    selections = _build_noninteractive_selections(ticker, date)
    config = DEFAULT_CONFIG.copy()
    config["quick_think_llm"] = selections["shallow_thinker"]
    config["deep_think_llm"] = selections["deep_thinker"]
    config["backend_url"] = selections["backend_url"]
    config["llm_provider"] = str(selections["llm_provider"]).lower()
    tool_overrides = selections.get("tool_vendors_override")
    if isinstance(tool_overrides, dict) and tool_overrides:
        merged_tool_vendors = dict(config.get("tool_vendors", {}))
        merged_tool_vendors.update({str(k): str(v) for k, v in tool_overrides.items()})
        config["tool_vendors"] = merged_tool_vendors

    # Initialize graph with minimal analysts for speed
    graph = TradingAgentsGraph(["market"], config=config, debug=False)

    # Create initial state
    init_state = graph.propagator.create_initial_state(ticker, date)
    args = graph.propagator.get_graph_args()

    # Run analysis
    console.print(f"[yellow]Analyzing {ticker} for {date}...[/yellow]")
    final_state = None
    for chunk in graph.graph.stream(init_state, **args):
        final_state = chunk
    
    if not final_state:
        console.print("[red]Error: Analysis failed[/red]")
        raise typer.Exit(1)
    
    # Get price if available
    price = None
    if "market_data" in final_state and final_state["market_data"]:
        price = final_state["market_data"].get("close")
    
    # Compute Aeternus rating
    rating = graph.aeternus_scorer.score(
        final_state,
        ticker=ticker,
        date=date,
        price_at_rating=price
    )

    # Extract thesis summary from trader plan for AKG storage
    trader_plan = final_state.get("trader_investment_plan", "")
    if trader_plan:
        # Take first sentence (up to first period, or first 150 chars)
        first_sentence = trader_plan.split(".")[0].strip()
        thesis_summary = first_sentence[:150] if first_sentence else ""
        if thesis_summary:
            rating["thesis_summary"] = thesis_summary

    recommendation = _extract_recommendation(str(final_state.get("final_trade_decision", "")))
    if recommendation == "UNKNOWN":
        recommendation = _fallback_recommendation_from_rating(
            rating=rating.get("rating"),
            score=rating.get("aeternus_score"),
        )
    rating["recommendation"] = recommendation

    # Log to track record
    track_record = TrackRecord()
    track_record.append(rating)
    try:
        rating_id = rating.get("rating_id")
        if rating_id:
            RatingAuditLog().log_event("RATING_CREATED", rating_id, rating)
    except Exception:
        pass

    # Record rating to AKG (knowledge graph)
    try:
        from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
        akg = AeternusKnowledgeGraph.load()
        akg.record_rating(ticker, rating)
        akg.save()
    except Exception:
        pass

    # Output
    if format == "json":
        print(json_lib.dumps(rating, indent=2))
    else:
        # Table format
        table = Table(title=f"Aeternus Rating: {ticker}")
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Ticker", rating["ticker"])
        table.add_row("Date", rating["date"])
        table.add_row("Score", f"{rating['aeternus_score']:.2f}")
        table.add_row("Rating", rating["rating"])
        table.add_row("Confidence", f"{rating['confidence']}/5")
        table.add_row("Price", f"${rating['price_at_rating']:.2f}" if rating["price_at_rating"] else "N/A")
        
        console.print(table)
        
        # Breakdown table
        breakdown_table = Table(title="Score Breakdown")
        breakdown_table.add_column("Dimension", style="cyan")
        breakdown_table.add_column("Score", style="green")
        
        for dim, score in rating["breakdown"].items():
            breakdown_table.add_row(dim.capitalize(), str(score))
        
        console.print(breakdown_table)

        sector_table = Table(title="Sector Context")
        sector_table.add_column("Metric", style="cyan")
        sector_table.add_column("Value", style="green")
        peer_data_raw = rating.get("peer_comparison", {})
        peer_data = peer_data_raw if isinstance(peer_data_raw, dict) else {}
        sector_table.add_row("Sector", str(rating.get("sector", "N/A")))
        sector_table.add_row(
            "Valuation",
            str(peer_data.get("valuation_status") or peer_data.get("status", "N/A")),
        )
        sector_table.add_row("Peer Avg P/E", _format_number(peer_data.get("peer_average_pe")))
        sector_table.add_row("Target P/E", _format_number(peer_data.get("target_pe")))
        sector_table.add_row(
            "Premium/Discount %",
            _format_number(peer_data.get("premium_discount_percent")),
        )
        console.print(sector_table)

        peer_rows = peer_data.get("details", []) if isinstance(peer_data, dict) else []
        if peer_rows:
            peers_table = Table(title="Peer Snapshot")
            peers_table.add_column("Peer", style="cyan")
            peers_table.add_column("P/E", justify="right")
            peers_table.add_column("P/B", justify="right")
            peers_table.add_column("Market Cap", justify="right")
            for peer in peer_rows[:5]:
                peers_table.add_row(
                    str(peer.get("ticker", "N/A")),
                    _format_number(peer.get("pe")),
                    _format_number(peer.get("price_to_book")),
                    str(peer.get("market_cap", "N/A")),
                )
            console.print(peers_table)


@app.command()
def analyze(
    analyst_provider: str = typer.Option(
        "",
        "--analyst-provider",
        help="Analyst provider: gpt|claude|grok_manual",
    ),
    post_analyst_provider: str = typer.Option(
        "",
        "--post-analyst-provider",
        help="Post-analyst graph provider: gpt|claude|gemini",
    ),
):
    selections = get_user_selections()
    if analyst_provider.strip():
        selections["analyst_provider"] = analyst_provider.strip().lower()
    if post_analyst_provider.strip():
        selections["post_analyst_provider"] = post_analyst_provider.strip().lower()
        selections["llm_provider"] = (
            "codex_cli"
            if selections["post_analyst_provider"] == "gpt"
            else "claude_cli"
            if selections["post_analyst_provider"] == "claude"
            else selections["post_analyst_provider"]
        )
    run_analysis(selections)
