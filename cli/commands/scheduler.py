"""CLI commands for the Aeternus autonomous agent scheduler."""
from cli.common import *  # noqa: F401,F403
import time
from pathlib import Path


BUS_DB_PATH = Path("eval_results/control/agent_bus.db")


def _build_scheduler():
    """Instantiate scheduler with all registered agents."""
    from tradingagents.scheduler.agent_bus import AgentBus
    from tradingagents.scheduler.supervisor import AeternusScheduler
    from tradingagents.scheduler.agents import (
        DealFlowScoutAgent,
        RiskSentinelAgent,
        PortfolioMonitorAgent,
        DocumentationAgent,
    )
    from tradingagents.scheduler.agents.research_agent import ResearchAgent
    from tradingagents.scheduler.agents.content_distiller import ContentDistillerAgent
    from tradingagents.scheduler.agents.portfolio_agent import PortfolioAgent
    from tradingagents.scheduler.agents.execution_agent import ExecutionAgent
    from tradingagents.scheduler.agents.investment_committee import InvestmentCommitteeAgent

    bus = AgentBus(db_path=str(BUS_DB_PATH))
    scheduler = AeternusScheduler(bus=bus)

    scheduler.register(DealFlowScoutAgent(bus), cron="0 6 * * 1-5")
    scheduler.register(ResearchAgent(bus), interval_seconds=600)
    scheduler.register(PortfolioAgent(bus), interval_seconds=600)
    scheduler.register(ExecutionAgent(bus), interval_seconds=600)
    scheduler.register(RiskSentinelAgent(bus), interval_seconds=300)
    scheduler.register(PortfolioMonitorAgent(bus), interval_seconds=600)
    scheduler.register(DocumentationAgent(bus), interval_seconds=60)
    scheduler.register(ContentDistillerAgent(bus), interval_seconds=600)
    scheduler.register(InvestmentCommitteeAgent(bus), cron="0 7 * * 0")  # weekly Sunday 7am

    return scheduler, bus


@app.command("scheduler-start")
def scheduler_start() -> None:
    """Start all autonomous agents. Blocks until Ctrl+C."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # noqa: F401
    except ImportError:
        console.print("[bold red]APScheduler not installed.[/bold red] Run: pip install apscheduler")
        raise typer.Exit(1)

    scheduler, bus = _build_scheduler()
    scheduler.start()
    console.print("[bold green]Aeternus Scheduler started.[/bold green] Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        scheduler.stop()
        console.print("\n[bold yellow]Scheduler stopped.[/bold yellow]")


@app.command("scheduler-status")
def scheduler_status(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of recent signals to show"),
) -> None:
    """Show recent autonomous agent activity from the signal bus."""
    from tradingagents.scheduler.agent_bus import AgentBus

    bus = AgentBus(db_path=str(BUS_DB_PATH))
    signals = bus.recent(limit=limit)

    if not signals:
        console.print("[dim]No signals found. Has the scheduler run yet?[/dim]")
        return

    table = Table(
        title="Agent Bus — Recent Signals",
        box=box.ROUNDED, show_header=True,
    )
    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Type", style="bold cyan", no_wrap=True)
    table.add_column("From", style="white", no_wrap=True)
    table.add_column("To", style="dim", no_wrap=True)
    table.add_column("Summary", style="white")

    for sig in signals:
        payload = sig.payload or {}
        summary_parts = [f"{k}={v}" for k, v in payload.items() if k != "started_at"]
        summary = ", ".join(summary_parts[:3]) or "—"
        created = sig.created_at[:19] if sig.created_at else "—"
        to_agent = sig.to_agent or "broadcast"
        table.add_row(created, sig.signal_type, sig.from_agent, to_agent, summary)

    console.print(table)


@app.command("scheduler-stop")
def scheduler_stop() -> None:
    """Instructions for stopping a running scheduler."""
    console.print(
        "[bold yellow]To stop the scheduler:[/bold yellow]\n"
        "  Press [bold]Ctrl+C[/bold] in the terminal where "
        "[cyan]aeternus scheduler-start[/cyan] is running.\n"
        "  Or send SIGTERM to the scheduler process."
    )


@app.command("scheduler-trigger")
def scheduler_trigger(
    agent: str = typer.Argument(..., help="Agent name to trigger (e.g. DealFlowScout)"),
) -> None:
    """Manually trigger one agent cycle immediately."""
    scheduler, bus = _build_scheduler()
    console.print(f"Triggering agent: [bold cyan]{agent}[/bold cyan]")

    try:
        result = scheduler.trigger(agent)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        valid = ", ".join(scheduler._agents.keys())
        console.print(f"Valid agents: [cyan]{valid}[/cyan]")
        raise typer.Exit(1)

    status = "[bold green]SUCCESS[/bold green]" if result.success else "[bold red]FAILED[/bold red]"
    console.print(f"Result: {status}")
    console.print(f"Duration: {result.started_at} → {result.completed_at}")
    if result.summary:
        console.print(f"Summary: {result.summary}")
    if result.error:
        console.print(f"[red]Error: {result.error}[/red]")


@app.command("content-queue")
def content_queue_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="Items to show"),
    status: str = typer.Option("pending", "--status", help="Filter by status: pending, approved, published, rejected"),
) -> None:
    """Show queued content items waiting for review or publishing."""
    from tradingagents.scheduler.agent_bus import AgentBus

    bus = AgentBus(db_path=str(BUS_DB_PATH))
    items = bus.get_pending_content(limit=limit, status=status)

    if not items:
        console.print(f"[dim]No content items with status '{status}'.[/dim]")
        return

    table = Table(
        title=f"Content Queue — {status}",
        box=box.ROUNDED, show_header=True,
    )
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Date", style="dim", no_wrap=True)
    table.add_column("Ticker", style="bold cyan", no_wrap=True)
    table.add_column("Type", style="white", no_wrap=True)
    table.add_column("Status", style="yellow", no_wrap=True)
    table.add_column("Preview", style="white")

    for item in items:
        preview = item["content"][:80].replace("\n", " ")
        if len(item["content"]) > 80:
            preview += "…"
        table.add_row(
            str(item["id"]),
            item["trade_date"],
            item["ticker"],
            item["content_type"],
            item["status"],
            preview,
        )

    console.print(table)


@app.command("content-approve")
def content_approve_cmd(
    content_id: int = typer.Argument(..., help="Content ID to approve"),
) -> None:
    """Approve a content item (marks it ready for publishing)."""
    from tradingagents.scheduler.agent_bus import AgentBus

    bus = AgentBus(db_path=str(BUS_DB_PATH))
    bus.approve_content(content_id)
    console.print(f"[green]Content #{content_id} approved.[/green]")
