from cli.common import *  # noqa: F401,F403


def _compat(name: str):
    import sys

    facade = sys.modules.get("cli.commands.dealflow")
    if facade is not None and hasattr(facade, name):
        return getattr(facade, name)
    return globals()[name]


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
    payload = _compat("run_x_account_discovery")(
        as_of_date=run_date,
        config=DEFAULT_CONFIG.copy(),
    )
    out_path = _compat("persist_x_account_candidates")(payload=payload, as_of_date=run_date)
    result = dict(payload)
    result["output_path"] = str(out_path)

    try:
        _compat("RatingAuditLog")().log_event(
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
