from cli.common import *  # noqa: F401,F403


def _compat(name: str):
    import sys

    facade = sys.modules.get("cli.commands.dealflow")
    if facade is not None and hasattr(facade, name):
        return getattr(facade, name)
    return globals()[name]


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
    snapshot = _compat("evaluate_step1_readiness")(
        config=DEFAULT_CONFIG.copy(),
        as_of_date=run_date,
    )
    output_path = None
    if persist:
        output_path = _compat("persist_step1_readiness")(snapshot, as_of_date=run_date)
        snapshot["output_path"] = str(output_path)

    try:
        _compat("RatingAuditLog")().log_event(
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
        report, artifacts = _compat("build_evidence_telemetry")(
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
