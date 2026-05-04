"""CLI command: research-analysts — manual analyst bundle operations."""
from cli.common import *  # noqa: F401,F403

import datetime as _dt
import sys as _sys


@app.command("research-analysts")
def research_analysts(
    generate: bool = typer.Option(False, "--generate", help="Print analyst prompts"),
    ingest: bool = typer.Option(False, "--ingest", help="Ingest analyst JSON from stdin or --file"),
    status: bool = typer.Option(False, "--status", help="Show manual analyst readiness"),
    provider: str = typer.Option("grok_manual", "--provider", help="Manual analyst provider"),
    ticker: str = typer.Option("", "--ticker", help="Ticker symbol"),
    date: str = typer.Option("", "--date", help="Date override (YYYY-MM-DD, defaults to today)"),
    analyst: str = typer.Option("", "--analyst", help="Analyst name for --ingest"),
    file: str = typer.Option("", "--file", help="Path to JSON file (alternative to stdin)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse and validate without writing"),
):
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.codex_research_bridge import (
        ANALYST_NAMES,
        build_analyst_prompt,
        get_manual_bundle_readiness,
        ingest_manual_analyst,
    )

    run_date = date.strip() or _dt.date.today().strftime("%Y-%m-%d")
    symbol = ticker.strip().upper()
    provider_name = provider.strip().lower()
    results_root = Path(DEFAULT_CONFIG.get("results_dir", "./results"))

    if provider_name != "grok_manual":
        console.print("[red]Only grok_manual is supported in v1.[/red]")
        raise typer.Exit(1)
    if not generate and not ingest and not status:
        console.print("[red]Specify --generate, --ingest, or --status[/red]")
        raise typer.Exit(1)
    if not symbol:
        console.print("[red]--ticker is required[/red]")
        raise typer.Exit(1)

    if generate:
        for name in ANALYST_NAMES:
            console.rule(f"[bold]{symbol} {run_date} — {name}[/bold]")
            console.print(build_analyst_prompt(symbol, run_date, name))
            console.print()
        return

    if status:
        payload = get_manual_bundle_readiness(
            results_root=results_root,
            ticker=symbol,
            analysis_date=run_date,
            provider=provider_name,
        )
        status_label = "[green]READY[/green]" if payload.get("ready") else "[yellow]INCOMPLETE[/yellow]"
        console.print(f"{status_label} Manual analyst bundle — {symbol} {run_date}")
        console.print(
            f"  Completed analysts: {len(payload.get('completed_analysts', []))}/{len(payload.get('required_analysts', []))}"
        )
        missing = payload.get("missing_analysts", [])
        if missing:
            console.print(f"  Missing analysts: {', '.join(missing)}")
        return

    analyst_name = analyst.strip().lower()
    if analyst_name not in ANALYST_NAMES:
        console.print(f"[red]--analyst must be one of {', '.join(ANALYST_NAMES)}[/red]")
        raise typer.Exit(1)
    if file.strip():
        raw = Path(file.strip()).read_text()
    else:
        console.print("[dim]Paste JSON below, then press Ctrl+D (EOF):[/dim]")
        raw = _sys.stdin.read()
    if not raw.strip():
        console.print("[red]Empty input[/red]")
        raise typer.Exit(1)
    result = ingest_manual_analyst(
        results_root=results_root,
        ticker=symbol,
        analysis_date=run_date,
        analyst=analyst_name,
        provider=provider_name,
        raw_json=raw,
        dry_run=dry_run,
    )
    mode = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]LIVE[/green]"
    console.print(f"{mode} {symbol} {run_date} {analyst_name}")
    console.print(f"  Artifact: {result['artifact_path']}")
    console.print(f"  Prompt: {result['prompt_path']}")
