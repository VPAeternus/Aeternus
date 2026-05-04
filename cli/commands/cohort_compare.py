from cli.common import *  # noqa: F401,F403


@app.command("cohort-compare")
def cohort_compare(
    date: Optional[str] = typer.Option(None, "--date", "-d", help="Source date (YYYY-MM-DD). Defaults to latest."),
    eval_date: Optional[str] = typer.Option(None, "--eval-date", "-e", help="Eval date. Defaults to today."),
    history: bool = typer.Option(False, "--history", help="Show all cycles side by side."),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
):
    """Compare cohort returns — does each pipeline filter add alpha?"""
    from tradingagents.dealflow.cohort_tracker import compare_cohorts, compute_cohort_returns

    if history:
        cycles = compare_cohorts()
        if not cycles:
            console.print("[yellow]No cohort data yet. Run cohort-compare --date <date> first.[/yellow]")
            return
        if format == "json":
            print(json_lib.dumps(cycles, indent=2))
            return
        for cycle in cycles:
            _print_cycle(cycle["source_date"], cycle["cohorts"])
            console.print()
        return

    # Determine source date
    if not date:
        deal_flow_dir = Path("eval_results/deal_flow")
        dated = sorted(
            [d.name for d in deal_flow_dir.iterdir()
             if d.is_dir() and len(d.name) == 10 and d.name[4] == "-"],
            reverse=True,
        )
        if not dated:
            console.print("[red]No deal flow runs found.[/red]")
            return
        date = dated[0]

    result = compute_cohort_returns(date, eval_date=eval_date)

    if result.get("error"):
        console.print(f"[red]Error: {result['error']}[/red]")
        return

    if format == "json":
        print(json_lib.dumps(result, indent=2))
        return

    cohorts = result["cohorts"]
    rows = [cohorts[k] for k in ("ENTERED", "SELECTED", "V3_CLEARED", "V3_REJECTED") if k in cohorts]
    _print_cohort_table(result["source_date"], result["eval_date"], result["days"], rows)

    # Inter-stage alpha
    isa = result.get("inter_stage_alpha", {})
    parts = []
    e2s = isa.get("entered_to_selected")
    s2v = isa.get("selected_to_v3")
    if e2s is not None:
        color = "green" if e2s > 0 else "red"
        parts.append(f"Entered\u2192Selected [{color}]{e2s:+.1%}[/{color}]")
    if s2v is not None:
        color = "green" if s2v > 0 else "red"
        parts.append(f"Selected\u2192V3 [{color}]{s2v:+.1%}[/{color}]")
    b2r = isa.get("benchmark_to_v3_rejected")
    if b2r is not None:
        color = "green" if b2r > 0 else "red"
        benchmark_label = (
            str(result.get("benchmark")).upper()
            if result.get("benchmark")
            else "Benchmark"
        )
        parts.append(f"{benchmark_label}\u2192V3 Rejected [{color}]{b2r:+.1%}[/{color}]")
    if parts:
        console.print(f"\nFilter Alpha: {' | '.join(parts)}")


def _print_cohort_table(source_date: str, eval_date: str, days: int, rows: list[dict]) -> None:
    title = f"Cohort Comparison \u2014 {source_date} \u2192 {eval_date} ({days}d)"
    table = Table(title=title)
    table.add_column("Cohort", style="cyan")
    table.add_column("N", justify="right")
    table.add_column("EW Return", justify="right")
    table.add_column("SW Return", justify="right")
    table.add_column("QQQ", justify="right")
    table.add_column("Filter \u03b1", justify="right")

    for r in rows:
        ew = f"{r['eq_weight_return']:+.1%}" if r.get("eq_weight_return") is not None else "\u2014"
        sw = f"{r['score_weight_return']:+.1%}" if r.get("score_weight_return") is not None else "\u2014"
        bm = f"{r['benchmark_return']:+.1%}" if r.get("benchmark_return") is not None else "\u2014"
        fa = r.get("filter_alpha")
        if fa is not None:
            fa_color = "green" if fa > 0 else "red"
            fa_str = f"[{fa_color}]{fa:+.1%}[/{fa_color}]"
        else:
            fa_str = "\u2014"

        table.add_row(r["cohort"], str(r["ticker_count"]), ew, sw, bm, fa_str)

    console.print(table)


def _print_cycle(source_date: str, cohort_rows: list[dict]) -> None:
    eval_date = cohort_rows[0].get("eval_date", "?") if cohort_rows else "?"
    table = Table(title=f"{source_date} \u2192 {eval_date}")
    table.add_column("Cohort", style="cyan")
    table.add_column("N", justify="right")
    table.add_column("EW Return", justify="right")
    table.add_column("SW Return", justify="right")
    table.add_column("Filter \u03b1", justify="right")

    for r in cohort_rows:
        ew = f"{r['eq_weight_return']:+.1%}" if r.get("eq_weight_return") is not None else "\u2014"
        sw = f"{r['score_weight_return']:+.1%}" if r.get("score_weight_return") is not None else "\u2014"
        fa = r.get("filter_alpha")
        if fa is not None:
            fa_color = "green" if fa > 0 else "red"
            fa_str = f"[{fa_color}]{fa:+.1%}[/{fa_color}]"
        else:
            fa_str = "\u2014"
        table.add_row(r["cohort"], str(r.get("ticker_count", 0)), ew, sw, fa_str)

    console.print(table)
