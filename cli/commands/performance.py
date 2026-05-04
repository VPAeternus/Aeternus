from cli.common import *  # noqa: F401,F403

@app.command()
def track_record(
    ticker: Optional[str] = typer.Option(None, help="Filter by ticker"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """View rating history and performance statistics."""
    tr = TrackRecord()
    history = tr.get_history(ticker)
    
    if format == "json":
        print(json_lib.dumps(history, indent=2))
        return

    table = Table(title=f"Track Record {'(' + ticker + ')' if ticker else ''}")
    table.add_column("Date", style="cyan")
    table.add_column("Ticker", style="green")
    table.add_column("Rating", style="magenta")
    table.add_column("Score", justify="right")
    table.add_column("Status", style="yellow")
    table.add_column("Return", justify="right")

    for entry in history:
        # Calculate return if closed
        ret_str = "-"
        if entry.get("status") == "CLOSED" and entry.get("close_price") and entry.get("price_at_rating"):
             p_open = entry["price_at_rating"]
             p_close = entry["close_price"]
             ret = ((p_close - p_open) / p_open) * 100
             color = "green" if ret > 0 else "red"
             ret_str = f"[{color}]{ret:+.2f}%[/{color}]"

        table.add_row(
            entry.get("date", "N/A"),
            entry.get("ticker", "N/A"),
            entry.get("rating", "N/A"),
            str(entry.get("aeternus_score", "N/A")),
            entry.get("status", "OPEN"),
            ret_str
        )

    console.print(table)


@app.command()
def performance(
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Show win rate, average return, and rating distribution."""
    # Note: In a real implementation, we would fetch live prices here to evaluate open positions.
    # For Phase 1, we only evaluate CLOSED positions or just show stats based on existing data.
    tr = TrackRecord()
    
    # Mock current prices for demo (in production would use yfinance)
    # real_prices = fetch_real_prices(tr.get_active_tickers()) 
    real_prices = {} 
    
    stats = tr.compute_performance(real_prices)
    basic_stats = tr.get_stats()
    
    if format == "json":
        print(json_lib.dumps({**stats, **basic_stats}, indent=2))
        return

    # 1. Performance Metrics
    perf_table = Table(title="Performance Metrics (Evaluated Trades)")
    perf_table.add_column("Metric", style="cyan")
    perf_table.add_column("Value", style="bold white")
    
    win_rate = stats.get("win_rate", 0.0) * 100
    avg_return = stats.get("avg_return", 0.0) * 100
    
    perf_table.add_row("Total Ratings", str(basic_stats.get("count", 0)))
    perf_table.add_row("Evaluated Trades", str(stats.get("total_evaluated", 0)))
    perf_table.add_row("Win Rate", f"{win_rate:.1f}%")
    perf_table.add_row("Avg Return", f"{avg_return:.2f}%")
    
    console.print(perf_table)
    console.print()

    # 2. Rating Distribution
    dist_table = Table(title="Rating Distribution")
    dist_table.add_column("Rating", style="magenta")
    dist_table.add_column("Count", justify="right")
    
    for r, count in basic_stats.get("ratings", {}).items():
        dist_table.add_row(r, str(count))

    console.print(dist_table)

    # 3. V3 benchmark comparison over the actual track-record window
    if DEFAULT_CONFIG.get("v3_benchmark_enabled", True):
        try:
            v3 = tr.compute_v3_benchmark()
            if v3 and v3.get("period_days", 0) > 0:
                console.print()
                ticker = str(v3.get("ticker", DEFAULT_CONFIG.get("v3_benchmark_ticker", "QQQ"))).strip().upper() or "QQQ"
                v3_table = Table(title=f"V3 {ticker} Benchmark (Track-Record Window)")
                v3_table.add_column("Metric", style="cyan")
                v3_table.add_column("Value", style="bold white")
                window_start = str(v3.get("date_start", "")).strip()
                window_end = str(v3.get("date_end", "")).strip()
                v3_table.add_row(
                    "Window",
                    f"{window_start} -> {window_end}" if window_start and window_end else "N/A",
                )
                v3_table.add_row(
                    "V3 Total Return",
                    f"{float(v3.get('v3_total_return_pct', 0.0)):+.2f}%",
                )
                v3_table.add_row(
                    "Buy & Hold Return",
                    f"{float(v3.get('bh_total_return_pct', 0.0)):+.2f}%",
                )
                v3_table.add_row(
                    "V3 CAGR",
                    f"{float(v3.get('v3_cagr_pct', 0.0)):+.2f}%",
                )
                v3_table.add_row(
                    "Buy & Hold CAGR",
                    f"{float(v3.get('bh_cagr_pct', 0.0)):+.2f}%",
                )
                v3_table.add_row("Period", f"{v3.get('period_days', 0)} trading days")
                console.print(v3_table)
        except Exception:
            pass


@app.command()
def rating_history(
    rating_id: str,
):
    """View full audit history for a specific rating ID."""
    from tradingagents.graph.audit import RatingAuditLog
    
    audit = RatingAuditLog()
    history = audit.get_rating_history(rating_id)
    
    if not history:
        console.print(f"[yellow]No history found for Rating ID: {rating_id}[/yellow]")
        return

    table = Table(title=f"Audit History: {rating_id}")
    table.add_column("Timestamp", style="cyan")
    table.add_column("Event", style="bold magenta")
    table.add_column("Details", style="white")

    for event in history:
        data_str = json_lib.dumps(event.get_data(), indent=2) if hasattr(event, "get_data") else json_lib.dumps(event.get("data", {}))
        # Truncate if too long
        if len(data_str) > 100:
            data_str = data_str[:97] + "..."
            
        table.add_row(
            event.get("timestamp", "N/A"),
            event.get("event_type", "UNKNOWN"),
            data_str
        )

    console.print(table)


@app.command("post-mortem")
def post_mortem(
    ticker: Optional[str] = typer.Option(None, "--ticker", "-t", help="Filter by ticker"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max trades to show"),
    full: bool = typer.Option(False, "--full", help="Show full narrative per trade"),
    regime_table: bool = typer.Option(False, "--regime-table", help="Show regime x pillar accuracy matrix"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
):
    """Attribute closed-trade outcomes to pillars, agents, and regimes."""
    from tradingagents.graph.post_mortem import PostMortemEngine

    engine = PostMortemEngine()
    attributions = engine.analyze_all()

    if not attributions:
        console.print("[yellow]No closed trades found.[/yellow]")
        return

    if ticker:
        attributions = [a for a in attributions if a["ticker"].upper() == ticker.upper()]
        if not attributions:
            console.print(f"[yellow]No closed trades for {ticker}.[/yellow]")
            return

    if format == "json":
        print(json_lib.dumps(attributions[:limit], indent=2))
        return

    if regime_table:
        rt = engine.build_regime_accuracy_table(attributions)
        if not rt:
            console.print("[yellow]No regime data to display.[/yellow]")
            return
        rt_table = Table(title="Regime x Pillar Accuracy Matrix")
        rt_table.add_column("Regime", style="cyan")
        for p in ("fundamental", "coherence", "macro", "sentiment", "momentum"):
            rt_table.add_column(p.title(), justify="right")
        for regime_name, pillars in sorted(rt.items()):
            row = [regime_name]
            for p in ("fundamental", "coherence", "macro", "sentiment", "momentum"):
                cell = pillars.get(p, {})
                acc = cell.get("accuracy", 0.0)
                r_count = cell.get("right", 0)
                w_count = cell.get("wrong", 0)
                color = "green" if acc >= 60 else ("red" if acc < 40 else "yellow")
                row.append(f"[{color}]{acc:.0f}%[/{color}] ({r_count}R/{w_count}W)")
            rt_table.add_row(*row)
        console.print(rt_table)
        return

    # Default: summary table
    summary_table = Table(title="Post-Mortem Attribution")
    summary_table.add_column("Ticker", style="green")
    summary_table.add_column("Close Date", style="cyan")
    summary_table.add_column("Return", justify="right")
    summary_table.add_column("Score", justify="right")
    summary_table.add_column("Regime", style="magenta")
    summary_table.add_column("Inv Judge", justify="center")
    summary_table.add_column("Risk Judge", justify="center")
    summary_table.add_column("Trader", justify="center")
    summary_table.add_column("Pillars R/W/N", justify="center")

    for attr in attributions[:limit]:
        ret = attr.get("return_pct", 0.0)
        color = "green" if ret > 0 else "red"
        ret_str = f"[{color}]{ret:+.2f}%[/{color}]"

        ps = attr.get("pillar_summary", {})
        pillar_str = f"{ps.get('right_count', 0)}/{ps.get('wrong_count', 0)}/{ps.get('neutral_count', 0)}"

        aa = attr.get("agent_accuracy", {})
        inv_v = aa.get("investment_judge", {}).get("verdict", "-")
        risk_v = aa.get("risk_judge", {}).get("verdict", "-")
        trader_v = aa.get("trader", {}).get("verdict", "-")

        summary_table.add_row(
            attr.get("ticker", ""),
            attr.get("close_date", ""),
            ret_str,
            str(attr.get("entry_score", "")),
            attr.get("weight_regime", ""),
            inv_v,
            risk_v,
            trader_v,
            pillar_str,
        )

    console.print(summary_table)

    if full:
        for attr in attributions[:limit]:
            console.print()
            console.print(Panel(attr.get("narrative", ""), title=f"Post-Mortem: {attr.get('ticker', '')}"))


@app.command("exit-autopsy")
def exit_autopsy(
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
):
    """Show win/loss breakdown by exit rule from closed trades."""
    from tradingagents.graph.exit_autopsy import ExitAutopsyLedger

    ledger = ExitAutopsyLedger()
    data = ledger.build()

    if data["trade_count"] == 0:
        console.print("[yellow]No closed trades found.[/yellow]")
        return

    if format == "json":
        print(json_lib.dumps(data, indent=2))
        return

    brief = ledger.build_autopsy_brief()
    if brief:
        console.print(Panel(brief, title="Exit Autopsy Ledger"))
        console.print()

    by_rule = data.get("by_exit_rule", {})
    table = Table(title="Exit Rule Accuracy")
    table.add_column("Exit Rule", style="cyan")
    table.add_column("Accuracy", justify="right")
    table.add_column("W/L", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Avg Return", justify="right")

    for rule, stats in sorted(by_rule.items(), key=lambda x: -x[1]["total"]):
        acc = stats.get("accuracy", 0.5)
        color = "green" if acc >= 0.55 else ("red" if acc < 0.45 else "yellow")
        avg_ret = stats.get("avg_return", 0.0)
        ret_color = "green" if avg_ret > 0 else "red"
        table.add_row(
            rule,
            f"[{color}]{acc:.0%}[/{color}]",
            f"{stats['wins']}/{stats['losses']}",
            str(stats["total"]),
            f"[{ret_color}]{avg_ret:+.2f}%[/{ret_color}]",
        )

    console.print(table)


@app.command("stress-test")
def stress_test(
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
):
    """Run portfolio stress test — CVaR, named scenarios, concentration."""
    from tradingagents.graph.stress_test import compute_stress_metrics

    metrics = compute_stress_metrics()

    if format == "json":
        print(json_lib.dumps(metrics, indent=2))
        return

    if metrics["positions_analyzed"] == 0:
        console.print("[yellow]No open positions to stress test.[/yellow]")
        return

    # Risk metrics table
    risk_table = Table(title="Portfolio Stress Test")
    risk_table.add_column("Metric", style="cyan")
    risk_table.add_column("Value", style="bold white")
    risk_table.add_row("VaR (95%, 1-day)", f"{metrics['portfolio_var_95']:.2f}%")
    risk_table.add_row("CVaR (95%, 1-day)", f"{metrics['portfolio_cvar_95']:.2f}%")
    risk_table.add_row("Portfolio Beta", f"{metrics['portfolio_beta']:.3f}")
    risk_table.add_row("Max Drawdown", f"{metrics['max_drawdown_pct']:.2f}%")
    risk_table.add_row("Current Drawdown", f"{metrics['current_drawdown_pct']:.2f}%")
    risk_table.add_row("Top Position %", f"{metrics['concentration']['top_position_pct']:.1f}%")
    risk_table.add_row("Top 3 Positions %", f"{metrics['concentration']['top_3_pct']:.1f}%")
    risk_table.add_row("Positions Analyzed", str(metrics["positions_analyzed"]))
    console.print(risk_table)

    # Scenario table
    scenarios = metrics.get("scenario_results", {})
    if scenarios:
        console.print()
        scenario_table = Table(title="Scenario Analysis")
        scenario_table.add_column("Scenario", style="cyan")
        scenario_table.add_column("Impact %", justify="right")
        scenario_table.add_column("Impact $", justify="right")
        scenario_table.add_column("Worst Position", style="yellow")
        for name, result in scenarios.items():
            impact = result["impact_pct"]
            color = "red" if impact < 0 else "green"
            scenario_table.add_row(
                name,
                f"[{color}]{impact:+.2f}%[/{color}]",
                f"[{color}]${result['impact_usd']:+,.0f}[/{color}]",
                result["worst_position"],
            )
        console.print(scenario_table)

    for w in metrics.get("warnings", []):
        console.print(f"[yellow]WARNING: {w}[/yellow]")


@app.command("equity-curve")
def equity_curve(
    initial_capital: float = typer.Option(200_000.0, "--capital", help="Initial capital"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
):
    """Show equity curve, NAV, and portfolio statistics."""
    from tradingagents.graph.equity_curve import EquityCurveEngine

    engine = EquityCurveEngine(initial_capital=initial_capital)
    data = engine.build()

    if format == "json":
        print(json_lib.dumps(data, indent=2))
        return

    stats = data["stats"]
    if stats["trade_count"] == 0:
        console.print("[yellow]No closed trades yet.[/yellow]")
        return

    # NAV summary
    nav_table = Table(title="Equity Curve")
    nav_table.add_column("Metric", style="cyan")
    nav_table.add_column("Value", style="bold white")
    nav_table.add_row("Initial Capital", f"${data['initial_capital']:,.0f}")
    nav_table.add_row("Current NAV", f"${data['current_nav']:,.0f}")
    nav_table.add_row("Realized P&L", f"${data['realized_pnl']:+,.0f}")
    nav_table.add_row("Unrealized P&L", f"${data['unrealized_pnl']:+,.0f}")
    ret_color = "green" if stats["total_return_pct"] >= 0 else "red"
    nav_table.add_row("Total Return", f"[{ret_color}]{stats['total_return_pct']:+.2f}%[/{ret_color}]")
    console.print(nav_table)
    console.print()

    # Stats table
    stats_table = Table(title="Portfolio Statistics")
    stats_table.add_column("Metric", style="cyan")
    stats_table.add_column("Value", style="bold white")
    stats_table.add_row("Trades", str(stats["trade_count"]))
    stats_table.add_row("Win Rate", f"{stats['win_rate']:.0%}")
    stats_table.add_row("Avg Win", f"{stats['avg_win_pct']:+.2f}%")
    stats_table.add_row("Avg Loss", f"{stats['avg_loss_pct']:+.2f}%")
    stats_table.add_row("Profit Factor", str(stats["profit_factor"]))
    stats_table.add_row("Sharpe Ratio", str(stats["sharpe_ratio"]))
    stats_table.add_row("Sortino Ratio", str(stats["sortino_ratio"]))
    stats_table.add_row("Calmar Ratio", str(stats["calmar_ratio"]))
    stats_table.add_row("Max Drawdown", f"{stats['max_drawdown_pct']:.2f}%")
    console.print(stats_table)

    # Monthly returns
    monthly = data.get("monthly_returns", {})
    if monthly:
        console.print()
        month_table = Table(title="Monthly Returns")
        month_table.add_column("Month", style="cyan")
        month_table.add_column("Return", justify="right")
        for m, ret in sorted(monthly.items()):
            color = "green" if ret >= 0 else "red"
            month_table.add_row(m, f"[{color}]{ret:+.2f}%[/{color}]")
        console.print(month_table)


@app.command("impl-shortfall")
def impl_shortfall(
    orders_path: str = typer.Option(
        "eval_results/paper_execution/orders.json",
        "--orders", help="Path to orders JSON file",
    ),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
):
    """Show implementation shortfall — slippage between reference and filled prices."""
    from tradingagents.graph.impl_shortfall import compute_impl_shortfall

    data = compute_impl_shortfall(orders_path=orders_path)

    if format == "json":
        print(json_lib.dumps(data, indent=2))
        return

    if data["order_count"] == 0:
        console.print("[yellow]No filled orders with reference prices found.[/yellow]")
        return

    # Summary table
    summary = Table(title="Implementation Shortfall")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="bold white")
    summary.add_row("Orders Analyzed", str(data["order_count"]))
    mean_color = "red" if data["mean_slippage_bps"] > 5 else ("green" if data["mean_slippage_bps"] < 0 else "yellow")
    summary.add_row("Mean Slippage", f"[{mean_color}]{data['mean_slippage_bps']:+.1f} bps[/{mean_color}]")
    summary.add_row("Median Slippage", f"{data['median_slippage_bps']:+.1f} bps")
    summary.add_row("Std Slippage", f"{data['std_slippage_bps']:.1f} bps")
    drag_color = "red" if data["cumulative_drag_bps"] > 0 else "green"
    summary.add_row("Cumulative Drag", f"[{drag_color}]{data['cumulative_drag_bps']:+.1f} bps[/{drag_color}]")
    console.print(summary)

    # Worst slippage
    worst = data.get("worst_slippage")
    if worst:
        console.print(f"\nWorst: {worst['symbol']} on {worst['date']} ({worst['slippage_bps']:+.1f} bps)")

    # By side
    by_side = data.get("by_side", {})
    if by_side:
        console.print()
        side_table = Table(title="By Side")
        side_table.add_column("Side", style="cyan")
        side_table.add_column("Mean Slippage", justify="right")
        side_table.add_column("Orders", justify="right")
        for side, info in sorted(by_side.items()):
            side_table.add_row(side, f"{info['mean_bps']:+.1f} bps", str(info["count"]))
        console.print(side_table)

    # By lane
    by_lane = data.get("by_lane", {})
    if by_lane:
        console.print()
        lane_table = Table(title="By Lane")
        lane_table.add_column("Lane", style="cyan")
        lane_table.add_column("Mean Slippage", justify="right")
        lane_table.add_column("Orders", justify="right")
        for lane, info in sorted(by_lane.items()):
            lane_table.add_row(lane, f"{info['mean_bps']:+.1f} bps", str(info["count"]))
        console.print(lane_table)

    if abs(data["mean_slippage_bps"]) > 5.0:
        console.print("\n[yellow]WARNING: Mean slippage exceeds 5 bps threshold. Review execution quality.[/yellow]")


@app.command("credibility")
def credibility(
    regime: Optional[str] = typer.Option(None, "--regime", "-r", help="Filter by regime (e.g. BULL, BEAR, NEUTRAL)"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
):
    """Show per-agent and per-pillar credibility scores from post-mortem data."""
    from tradingagents.graph.credibility_ledger import CredibilityLedger

    ledger = CredibilityLedger()
    data = ledger.build()

    if data["trade_count"] == 0:
        console.print("[yellow]No closed trades found.[/yellow]")
        return

    if format == "json":
        print(json_lib.dumps(data, indent=2))
        return

    # Brief mode (with regime filter)
    regime_label = (regime or "NEUTRAL").upper()
    brief = ledger.build_credibility_brief(regime=regime_label)
    if brief:
        console.print(Panel(brief, title="Agent Credibility Ledger"))
        console.print()

    # Agent table
    agents = data.get("agent_scores", {})
    agent_table = Table(title="Agent Accuracy")
    agent_table.add_column("Agent", style="cyan")
    agent_table.add_column("Overall", justify="right")
    agent_table.add_column("Wins/Total", justify="right")
    if regime_label:
        agent_table.add_column(f"In {regime_label}", justify="right")

    for agent_key in ("investment_judge", "risk_judge", "trader", "bull_side", "bear_side"):
        info = agents.get(agent_key, {})
        overall = info.get("overall", {})
        acc = overall.get("accuracy", 0.5)
        wins = overall.get("wins", 0)
        total = overall.get("total", 0)
        color = "green" if acc >= 0.55 else ("red" if acc < 0.45 else "yellow")
        row = [
            agent_key.replace("_", " ").title(),
            f"[{color}]{acc:.0%}[/{color}]",
            f"{wins}/{total}",
        ]
        if regime_label:
            r_info = info.get("by_regime", {}).get(regime_label, {})
            r_acc = r_info.get("accuracy", 0.5)
            r_total = r_info.get("total", 0)
            r_wins = r_info.get("wins", 0)
            if r_total > 0:
                r_color = "green" if r_acc >= 0.55 else ("red" if r_acc < 0.45 else "yellow")
                row.append(f"[{r_color}]{r_acc:.0%}[/{r_color}] ({r_wins}/{r_total})")
            else:
                row.append("-")
        agent_table.add_row(*row)

    console.print(agent_table)
    console.print()

    # Pillar table
    pillars = data.get("pillar_scores", {})
    pillar_table = Table(title="Pillar Accuracy")
    pillar_table.add_column("Pillar", style="cyan")
    pillar_table.add_column("Overall", justify="right")
    pillar_table.add_column("Wins/Total", justify="right")
    if regime_label:
        pillar_table.add_column(f"In {regime_label}", justify="right")

    for pillar in ("fundamental", "coherence", "macro", "sentiment", "momentum"):
        info = pillars.get(pillar, {})
        overall = info.get("overall", {})
        acc = overall.get("accuracy", 0.5)
        wins = overall.get("wins", 0)
        total = overall.get("total", 0)
        color = "green" if acc >= 0.55 else ("red" if acc < 0.45 else "yellow")
        row = [
            pillar.title(),
            f"[{color}]{acc:.0%}[/{color}]",
            f"{wins}/{total}",
        ]
        if regime_label:
            r_info = info.get("by_regime", {}).get(regime_label, {})
            r_acc = r_info.get("accuracy", 0.5)
            r_total = r_info.get("total", 0)
            r_wins = r_info.get("wins", 0)
            if r_total > 0:
                r_color = "green" if r_acc >= 0.55 else ("red" if r_acc < 0.45 else "yellow")
                row.append(f"[{r_color}]{r_acc:.0%}[/{r_color}] ({r_wins}/{r_total})")
            else:
                row.append("-")
        pillar_table.add_row(*row)

    console.print(pillar_table)


@app.command("performance-review")
def performance_review(
    source_date: str = typer.Option(..., "--source-date", "-d", help="Deal flow run date (YYYY-MM-DD)"),
    benchmark_ticker: str = typer.Option("QQQ", "--benchmark", "-b", help="Benchmark ticker"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
):
    """Funnel report card — measures whether each pipeline filter cut added alpha."""
    from tradingagents.dealflow.performance_tracker import compute_performance_review
    from tradingagents.dealflow.scoring import CORE_SCORE_WEIGHTS

    result = compute_performance_review(source_date, benchmark=benchmark_ticker)

    if result.get("error"):
        console.print(f"[red]Error: {result['error']}[/red]")
        return

    if format == "json":
        print(json_lib.dumps(result, indent=2))
        return

    bm_5d = result.get("benchmark_return_5d")
    bm_label = f"vs {benchmark_ticker} {bm_5d:+.1%}" if bm_5d is not None else ""
    console.print(f"\n[bold]FUNNEL REPORT CARD — {source_date} ({bm_label})[/bold]\n")

    # Stage table
    stage_table = Table()
    stage_table.add_column("Stage", style="cyan")
    stage_table.add_column("N", justify="right")
    stage_table.add_column("Mean 5d", justify="right")
    stage_table.add_column("Mean 20d", justify="right")
    stage_table.add_column("Edge 5d", justify="right")
    stage_table.add_column("Filter Alpha", justify="right")

    stages = result.get("stages", {})
    fa = result.get("filter_alpha", {})
    fa_keys = [None, "scored_to_queued_5d", "queued_to_analyzed_5d", "analyzed_to_deployed_5d"]

    for i, stage_name in enumerate(["SCORED", "QUEUED", "ANALYZED", "DEPLOYED"]):
        s = stages.get(stage_name, {})
        n = s.get("n", 0)
        m5 = f"{s['mean_5d']:+.1%}" if s.get("mean_5d") is not None else "—"
        m20 = f"{s['mean_20d']:+.1%}" if s.get("mean_20d") is not None else "—"
        edge = f"{s['edge_5d']:+.1%}" if s.get("edge_5d") is not None else "—"

        fa_key = fa_keys[i]
        if fa_key and fa.get(fa_key) is not None:
            fa_val = fa[fa_key]
            mark = "[green]" + u"\u2713" + "[/green]" if fa_val > 0 else "[red]" + u"\u2717" + "[/red]"
            fa_str = f"{fa_val:+.1%}  {mark}"
        else:
            fa_str = "(baseline)" if i == 0 else "—"

        stage_table.add_row(stage_name, str(n), m5, m20, edge, fa_str)

    console.print(stage_table)
    _render_hypothesis_stage_summary(result.get("hypothesis_stage_summary", {}))
    _render_discovery_delta_cohort_scorecards(result.get("discovery_delta_cohorts", {}))
    _render_evidence_integrity_cohort_scorecards(result.get("evidence_integrity_cohorts", {}))

    # Signal family IC table
    fic = result.get("signal_family_ic", [])
    if fic:
        console.print()
        fic_n = fic[0].get("n", 0) if fic else 0
        ic_table = Table(title=f"SIGNAL FAMILY IC (5d, n={fic_n})")
        ic_table.add_column("Family", style="cyan")
        ic_table.add_column("IC", justify="right")
        ic_table.add_column("t-stat", justify="right")
        ic_table.add_column("Weight", justify="right")

        for row in sorted(fic, key=lambda x: -(x.get("ic") or 0)):
            fam = row["signal_family"]
            ic_val = f"{row['ic']:+.2f}" if row.get("ic") is not None else "—"
            t_val = f"{row['t_stat']:.2f}" if row.get("t_stat") is not None else "—"
            weight = CORE_SCORE_WEIGHTS.get(fam, 0.0)
            ic_table.add_row(fam, ic_val, t_val, f"{weight:.0f}%")

        console.print(ic_table)
