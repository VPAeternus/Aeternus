"""CLI command: x-feed — manual 15-pass X sector sweep."""
from cli.common import *  # noqa: F401,F403

import json as _json
import sys as _sys

from tradingagents.dealflow.sources.x_feed_browser_runner import run_browser_passes


@app.command("x-feed")
def x_feed(
    generate: bool = typer.Option(False, "--generate", help="Print all 15 Grok prompts"),
    ingest: bool = typer.Option(False, "--ingest", help="Ingest Grok JSON from stdin or --file"),
    status: bool = typer.Option(False, "--status", help="Show manual X-feed readiness for the date"),
    run_browser: bool = typer.Option(False, "--run-browser", help="Run passes in Grok automatically via browser control"),
    file: str = typer.Option("", "--file", help="Path to JSON file (alternative to stdin)"),
    date: str = typer.Option("", "--date", help="Date override (YYYY-MM-DD, defaults to today)"),
    pass_num: int = typer.Option(0, "--pass", help="Pass number (1-15), required for --ingest"),
    start_pass: int = typer.Option(1, "--start-pass", help="First pass to run for --run-browser"),
    end_pass: int = typer.Option(15, "--end-pass", help="Last pass to run for --run-browser"),
    profile: str = typer.Option("Default", "--profile", help="Chrome profile to use for --run-browser"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse and validate without writing"),
):
    """Manual X Feed Scout — 15-pass sector sweep with full archival."""
    import datetime as _dt

    as_of_date = date.strip() or _dt.date.today().strftime("%Y-%m-%d")

    selected_modes = sum(bool(flag) for flag in (generate, ingest, status, run_browser))
    if selected_modes == 0:
        console.print("[red]Specify --generate, --ingest, --status, or --run-browser[/red]")
        raise typer.Exit(1)
    if selected_modes > 1:
        console.print("[red]Choose only one of --generate, --ingest, --status, or --run-browser[/red]")
        raise typer.Exit(1)

    if generate:
        _do_generate()
    elif ingest:
        from tradingagents.dealflow.sources.x_feed_manual import PASS_CONFIGS as _PC
        if pass_num < 1 or pass_num > len(_PC):
            console.print(f"[red]--pass must be 1-{len(_PC)}[/red]")
            raise typer.Exit(1)
        _do_ingest(as_of_date, pass_num, file.strip(), dry_run)
    elif run_browser:
        _do_run_browser(as_of_date, start_pass, end_pass, profile.strip(), dry_run)
    elif status:
        _do_status(as_of_date)


def _do_generate():
    """Print all prompts with numbered headers."""
    from tradingagents.dealflow.sources.x_feed_manual import generate_prompts

    prompts = generate_prompts()
    for pnum, label, prompt in prompts:
        console.rule(f"[bold]Pass {pnum}: {label}[/bold]")
        console.print(prompt)
        console.print()


def _do_status(as_of_date: str):
    from tradingagents.dealflow.sources.x_feed_manual import finalize_x_feed, get_readiness, get_readiness_pre_finalize

    pre = get_readiness_pre_finalize(as_of_date)
    if not pre.get("missing_passes") and int(pre.get("merged_symbol_count", 0) or 0) > 0:
        finalize_x_feed(as_of_date)
    payload = get_readiness(as_of_date)
    status_label = "[green]READY[/green]" if payload.get("ready") else "[yellow]INCOMPLETE[/yellow]"
    console.print(f"{status_label} Manual X Feed — {as_of_date}")
    console.print(f"  Completed passes: {len(payload.get('completed_passes', []))}/{len(payload.get('required_passes', []))}")
    missing = payload.get("missing_passes", [])
    if missing:
        console.print(f"  Missing passes: {', '.join(str(p) for p in missing)}")
    console.print(f"  Merged symbols: {int(payload.get('merged_symbol_count', 0) or 0)}")
    console.print(f"  Finalized: {'yes' if payload.get('finalized') else 'no'}")
    console.print(f"  Merged path: {payload.get('merged_path')}")
    console.print(f"  Theme graph: {payload.get('theme_graph_path')}")


def _do_run_browser(as_of_date: str, start_pass: int, end_pass: int, profile: str, dry_run: bool):
    try:
        payload = run_browser_passes(
            as_of_date,
            start_pass=int(start_pass),
            end_pass=int(end_pass),
            profile=profile or "Default",
            dry_run=bool(dry_run),
        )
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    mode = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]LIVE[/green]"
    console.print(f"{mode} Browser run complete — {as_of_date}")
    console.print(f"  Pass range: {int(payload.get('start_pass', start_pass))}-{int(payload.get('end_pass', end_pass))}")
    completed = list(payload.get("completed_passes", []) or [])
    if completed:
        console.print(f"  Completed passes: {', '.join(str(int(p)) for p in completed)}")
    else:
        console.print("  Completed passes: None")

    for result in list(payload.get("results", []) or []):
        console.print(
            f"  Pass {int(result.get('pass_num', 0) or 0)} | "
            f"parsed={int(result.get('tickers_parsed', 0) or 0)} | "
            f"merged={int(result.get('tickers_merged', 0) or 0)}"
        )

    final_manifest = dict(payload.get("final_manifest") or {})
    if final_manifest:
        console.print(
            f"  Final manifest: symbols={int(final_manifest.get('symbol_count', 0) or 0)} | "
            f"themes={int(final_manifest.get('theme_count', 0) or 0)} | "
            f"edges={int(final_manifest.get('edge_count', 0) or 0)}"
        )
    readiness = dict(payload.get("readiness") or {})
    if readiness:
        ready_label = "yes" if bool(readiness.get("ready")) else "no"
        console.print(f"  Ready: {ready_label}")
        console.print(f"  Merged symbols: {int(readiness.get('merged_symbol_count', 0) or 0)}")


def _do_ingest(as_of_date: str, pass_num: int, file_path: str, dry_run: bool):
    """Read JSON, call ingest_pass, print summary."""
    from tradingagents.dealflow.sources.x_feed_manual import ingest_pass, PASS_CONFIGS

    if file_path:
        try:
            with open(file_path, "r") as f:
                raw = f.read()
        except FileNotFoundError:
            console.print(f"[red]File not found: {file_path}[/red]")
            raise typer.Exit(1)
    else:
        console.print("[dim]Paste JSON below, then press Ctrl+D (EOF):[/dim]")
        raw = _sys.stdin.read()

    if not raw.strip():
        console.print("[red]Empty input[/red]")
        raise typer.Exit(1)

    label = PASS_CONFIGS[pass_num - 1]["label"] if 1 <= pass_num <= len(PASS_CONFIGS) else "?"
    result = ingest_pass(as_of_date, raw, pass_num, dry_run=dry_run)

    mode = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]LIVE[/green]"
    console.print(f"\n{mode} Pass {pass_num} ({label}) — {as_of_date}")
    console.print(f"  Raw archived: {result['raw_path']}")
    console.print(f"  Tickers parsed: {result['tickers_parsed']}")
    console.print(f"  Merged total: {result['tickers_merged']}")
    console.print(f"  AKG written: {result['akg_written']}")

    if result.get("themes"):
        console.print(f"  Themes: {len(result['themes'])}")

    if result.get("options_flow"):
        console.print(f"  Options flow entries: {len(result['options_flow'])}")

    # Print ticker table
    if result["entries"]:
        from rich.table import Table
        table = Table(title=f"Pass {pass_num} Tickers")
        table.add_column("Ticker", style="bold")
        table.add_column("Rank", justify="right")
        table.add_column("Sentiment")
        table.add_column("Velocity")
        table.add_column("v_z", justify="right")
        table.add_column("Catalyst")
        for e in sorted(result["entries"], key=lambda x: x.get("mentions_estimate", 99)):
            sent_val = e.get("sentiment", 0)
            sent_color = "green" if sent_val > 0 else ("red" if sent_val < 0 else "white")
            table.add_row(
                e["ticker"],
                str(e.get("mentions_estimate", "")),
                f"[{sent_color}]{sent_val:+.1f}[/{sent_color}]",
                e.get("velocity_trend", ""),
                f"{e.get('velocity_z', 0):.2f}",
                (e.get("catalyst", "") or "")[:60],
            )
        console.print(table)
