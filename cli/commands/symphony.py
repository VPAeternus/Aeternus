"""Symphony status command — shows dispatcher state and opens dashboard."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import typer
from rich.table import Table

from cli.common import app, console

STATE_PATH = Path("eval_results/agents/symphony_state.json")
DASHBOARD_URL = "http://localhost:7777"


@app.command("symphony-status")
def symphony_status(
    html: bool = typer.Option(False, "--html", help="Open dashboard in browser (requires running dispatcher)"),
) -> None:
    """Show Symphony dispatcher status — queue, active agents, and history."""
    if html:
        subprocess.run(["open", DASHBOARD_URL], check=False)
        console.print(f"Opened {DASHBOARD_URL}")
        return

    if not STATE_PATH.exists():
        console.print("[yellow]No symphony state found.[/yellow] Run `python scripts/symphony.py` first.")
        raise typer.Exit(1)

    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    # Header
    uptime = state.get("uptime_seconds", 0)
    h, m = divmod(uptime // 60, 60)
    cfg = state.get("config", {})
    console.print(
        f"[bold blue]Symphony[/bold blue] | Uptime: {h}h {m}m | "
        f"Max: {cfg.get('max_concurrent', '?')} | Timeout: {cfg.get('timeout_minutes', '?')}m"
    )
    console.print()

    # Stats
    stats = state.get("stats", {})
    console.print(
        f"Dispatched: [cyan]{stats.get('total_dispatched', 0)}[/cyan]  "
        f"Completed: [green]{stats.get('total_completed', 0)}[/green]  "
        f"Failed: [red]{stats.get('total_failed', 0)}[/red]"
    )
    console.print()

    # Active agents
    active = state.get("active", [])
    if active:
        tbl = Table(title="Active Agents", show_lines=False)
        tbl.add_column("Task", style="bold")
        tbl.add_column("Tier")
        tbl.add_column("Summary")
        tbl.add_column("Elapsed", justify="right")
        tbl.add_column("PID", justify="right")
        for a in active:
            elapsed_m = a.get("elapsed_seconds", 0) // 60
            elapsed_s = a.get("elapsed_seconds", 0) % 60
            tbl.add_row(
                a["task_id"],
                a["tier"],
                a.get("summary", ""),
                f"{elapsed_m}m {elapsed_s}s",
                str(a.get("pid", "")),
            )
        console.print(tbl)
    else:
        console.print("[dim]No active agents.[/dim]")
    console.print()

    # Queue
    queue = state.get("queue", [])
    if queue:
        tbl = Table(title="Queue", show_lines=False)
        tbl.add_column("Task", style="bold")
        tbl.add_column("Tier")
        tbl.add_column("Summary")
        for t in queue:
            tbl.add_row(t["task_id"], t["tier"], t.get("summary", ""))
        console.print(tbl)
    else:
        console.print("[dim]Queue empty.[/dim]")
    console.print()

    # History (last 10)
    history = (state.get("completed", []) + state.get("failed", []))[-10:]
    if history:
        tbl = Table(title="Recent History", show_lines=False)
        tbl.add_column("Task", style="bold")
        tbl.add_column("Tier")
        tbl.add_column("Status")
        tbl.add_column("Duration", justify="right")
        for item in history:
            status = item.get("status", "?")
            style = {"done": "green", "failed": "red", "timed_out": "yellow"}.get(status, "")
            dur = item.get("duration_seconds", 0)
            tbl.add_row(
                item["task_id"],
                item["tier"],
                f"[{style}]{status}[/{style}]" if style else status,
                f"{dur // 60}m {dur % 60}s",
            )
        console.print(tbl)
