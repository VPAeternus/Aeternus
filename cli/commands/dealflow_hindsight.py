from cli.common import *  # noqa: F401,F403

@app.command()
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
