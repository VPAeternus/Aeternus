from cli.common import *  # noqa: F401,F403


@app.command()
def hindsight(
    source_date: str = typer.Option(..., "--source-date", help="Run date (YYYY-MM-DD) to evaluate."),
    benchmark: str = typer.Option("QQQ", "--benchmark", help="Benchmark ticker."),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Retired old dealflow hindsight command."""
    payload = {
        "status": "retired",
        "source_date": source_date,
        "benchmark": benchmark,
        "reason": "Scout tickers are evaluated only after fundamental framework output exists.",
    }
    if str(format or "table").lower().strip() == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
    else:
        console.print("[yellow]Old dealflow hindsight command retired.[/yellow]")
    raise typer.Exit(1)


@app.command("why-missed")
def why_missed(
    ticker: str,
    last: int = typer.Option(5, "--last", min=1, help="Inspect up to the last N runs."),
    hurdle: float = typer.Option(62.0, "--hurdle", help="Legacy option kept for CLI compatibility."),
    benchmark: str = typer.Option("QQQ", "--benchmark", help="Benchmark ticker."),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Retired old dealflow miss-audit command."""
    del last, hurdle, benchmark
    payload = {
        "status": "retired",
        "ticker": str(ticker).upper(),
        "reason": "Scout tickers are not filtered by old dealflow funnel stages.",
    }
    if str(format or "table").lower().strip() == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
    else:
        console.print("[yellow]Old dealflow miss-audit command retired.[/yellow]")
    raise typer.Exit(1)


@app.command("needle-retro")
def needle_retro(
    last: int = typer.Option(5, "--last", min=1, help="Inspect up to the last N completed cycles."),
    benchmark: str = typer.Option("QQQ", "--benchmark", help="Benchmark ticker."),
    min_edge: float = typer.Option(0.03, "--min-edge", help="Legacy option kept for CLI compatibility."),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Retired old dealflow retro command."""
    del last, benchmark, min_edge
    payload = {"status": "retired", "reason": "Use fundamental framework realized-performance artifacts."}
    if str(format or "table").lower().strip() == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
    else:
        console.print("[yellow]Old dealflow retro command retired.[/yellow]")
    raise typer.Exit(1)


@app.command("hindsight-summary")
def hindsight_summary(
    last: int = typer.Option(10, "--last", min=1, help="Number of cycles to show."),
):
    """Retired old dealflow hindsight summary."""
    del last
    console.print("[yellow]Old dealflow hindsight summary retired.[/yellow]")
    raise typer.Exit(1)
