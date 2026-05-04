"""
CLI commands for the Structural Force Engine (S-052/S-054).

aeternus forces list                        — list all forces with conviction + acceleration
aeternus forces dark-matter                 — show top dark matter candidates right now
aeternus forces show <force_id>             — show full causal chain for one force
aeternus forces propose-extension <force_id> — propose a missing causal step (S-054)
"""

import os

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from cli.common import app as _root_app

forces_app = typer.Typer(name="forces", help="Structural Force Engine commands.")
_root_app.add_typer(forces_app, name="forces")

console = Console()


@forces_app.command("list")
def forces_list():
    """List all structural forces with conviction and acceleration rate."""
    from tradingagents.graph.structural_forces import STRUCTURAL_FORCES

    table = Table(
        title="Structural Force Registry",
        box=box.SIMPLE_HEAD,
        show_lines=False,
    )
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Display Name", style="white")
    table.add_column("Conviction", justify="right", style="green")
    table.add_column("Acceleration", style="yellow")
    table.add_column("Horizon (mo)", justify="right")
    table.add_column("Steps", justify="right")
    table.add_column("Last Reviewed")

    for force in STRUCTURAL_FORCES:
        accel_color = {
            "accelerating": "green",
            "stable": "yellow",
            "decelerating": "red",
        }.get(force.acceleration_rate, "white")

        table.add_row(
            force.force_id,
            force.display_name,
            f"{force.conviction:.2f}",
            f"[{accel_color}]{force.acceleration_rate}[/{accel_color}]",
            str(force.horizon_months),
            str(len(force.causal_chain)),
            force.last_reviewed,
        )

    console.print(table)
    console.print(
        f"[dim]{len(STRUCTURAL_FORCES)} forces in registry. "
        f"Use 'forces show <id>' for full causal chain.[/dim]"
    )


@forces_app.command("show")
def forces_show(
    force_id: str = typer.Argument(..., help="Force ID (e.g. ai_compute_demand)"),
):
    """Show full causal chain and metadata for a single structural force."""
    from tradingagents.graph.structural_forces import get_force

    force = get_force(force_id)
    if force is None:
        console.print(f"[red]Force not found: {force_id}[/red]")
        console.print("[dim]Use 'forces list' to see available force IDs.[/dim]")
        raise typer.Exit(1)

    # Header
    console.print(f"\n[bold cyan]{force.display_name}[/bold cyan]  [dim]({force.force_id})[/dim]")
    console.print(f"[white]{force.description}[/white]\n")

    # Metadata table
    meta_table = Table(box=box.SIMPLE_HEAD, show_header=False, padding=(0, 1))
    meta_table.add_column("Field", style="cyan")
    meta_table.add_column("Value")
    meta_table.add_row("Conviction", f"{force.conviction:.2f}")
    meta_table.add_row("Acceleration", force.acceleration_rate)
    meta_table.add_row("Horizon", f"{force.horizon_months} months")
    meta_table.add_row("Last Reviewed", force.last_reviewed)
    console.print(meta_table)

    # Why durable
    console.print(f"\n[bold]Why Durable:[/bold] {force.why_durable}\n")

    # Must-be-true conditions
    console.print("[bold]Must Be True:[/bold]")
    for condition in force.must_be_true:
        console.print(f"  - {condition}")

    # Causal chain
    console.print(f"\n[bold]Causal Chain ({len(force.causal_chain)} steps):[/bold]")
    chain_table = Table(box=box.SIMPLE_HEAD, show_lines=True)
    chain_table.add_column("Step", justify="right", style="dim")
    chain_table.add_column("Description")
    chain_table.add_column("Tickers", style="cyan")
    chain_table.add_column("Necessity", justify="right", style="green")
    chain_table.add_column("Reasoning")

    for step in force.causal_chain:
        chain_table.add_row(
            str(step.step),
            step.description,
            ", ".join(step.derived_tickers),
            f"{step.necessity_score:.2f}",
            step.reasoning,
        )
    console.print(chain_table)

    # Anti-fragile
    if force.anti_fragile_to:
        console.print("\n[bold]Anti-Fragile To:[/bold]")
        for item in force.anti_fragile_to:
            console.print(f"  - {item}")
    console.print()


@forces_app.command("dark-matter")
def forces_dark_matter(
    min_score: float = typer.Option(0.5, help="Minimum discovery score threshold"),
    top_k: int = typer.Option(20, help="Maximum candidates to display"),
    akg_path: str = typer.Option(
        "eval_results/control/knowledge_graph.json",
        help="Path to AKG JSON file",
    ),
    enrich: bool = typer.Option(
        False,
        "--enrich/--no-enrich",
        help="Call compute_market_ignorance() live for each candidate (shows analyst_count + institutional_pct).",
    ),
):
    """Show top dark matter candidates — tickers causally necessary but invisible to capital."""
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

    console.print(f"[yellow]Loading AKG from {akg_path}...[/yellow]")
    try:
        akg = AeternusKnowledgeGraph.load(akg_path)
    except Exception as exc:
        console.print(f"[red]Failed to load AKG: {exc}[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Deriving dark matter candidates (min_score={min_score})...[/yellow]")
    candidates = akg.get_dark_matter_candidates(
        min_discovery_score=min_score,
        top_k=top_k,
    )

    if not candidates:
        console.print("[yellow]No dark matter candidates above threshold.[/yellow]")
        return

    # Optional live enrichment: compute real market ignorance and write back to AKG
    if enrich:
        from tradingagents.graph.market_ignorance import compute_market_ignorance
        console.print(f"[yellow]Enriching {len(candidates)} candidates with live market data...[/yellow]")
        for c in candidates:
            ticker = c.get("ticker", "")
            if ticker:
                compute_market_ignorance(ticker, akg)

    table = Table(
        title=f"Dark Matter Candidates (top {len(candidates)})",
        box=box.SIMPLE_HEAD,
        show_lines=False,
    )
    table.add_column("Ticker", style="cyan", no_wrap=True)
    table.add_column("Force", style="white")
    table.add_column("Step", justify="right")
    table.add_column("Necessity", justify="right", style="green")
    table.add_column("Ignorance", justify="right", style="yellow")
    table.add_column("Discovery", justify="right", style="bold green")
    table.add_column("In AKG", justify="center")
    if enrich:
        table.add_column("Analysts", justify="right")
        table.add_column("Inst %", justify="right")
    table.add_column("Reasoning")

    for c in candidates:
        in_akg_str = "[green]YES[/green]" if c.get("already_in_akg") else "[dim]NO[/dim]"
        ticker = str(c.get("ticker", ""))
        row = [
            ticker,
            str(c.get("force_id", "")),
            str(c.get("causal_step", "")),
            f"{c.get('necessity_score', 0):.3f}",
            f"{c.get('market_ignorance_score', 0):.3f}",
            f"{c.get('discovery_score', 0):.3f}",
            in_akg_str,
        ]
        if enrich:
            node = akg._nodes.get(ticker) or {}
            analyst_count = node.get("analyst_count")
            inst_pct = node.get("institutional_pct")
            row.append(str(analyst_count) if analyst_count is not None else "-")
            row.append(f"{inst_pct:.1%}" if inst_pct is not None else "-")
        row.append(str(c.get("reasoning", ""))[:80])
        table.add_row(*row)

    console.print(table)
    console.print(
        f"[dim]{len(candidates)} candidates surfaced. "
        f"Enable structural_force_engine_enabled=True to inject into pipeline.[/dim]"
    )


@forces_app.command("propose-extension")
def forces_propose_extension(
    force_id: str = typer.Argument(..., help="Force ID (e.g. ai_compute_demand)"),
):
    """
    Propose a missing causal step for a structural force using LLM reasoning.
    Returns a PROPOSED step for operator review — NOT automatically added to the registry.
    Routes through claude_cli (free) when AETERNUS_LLM_PROVIDER=claude_cli, else xAI.
    """
    provider = os.environ.get("AETERNUS_LLM_PROVIDER", "").strip().lower()
    if provider != "claude_cli":
        api_key = os.environ.get("XAI_API_KEY", "").strip()
        if not api_key:
            console.print("[red]XAI_API_KEY is not set and AETERNUS_LLM_PROVIDER is not claude_cli.[/red]")
            raise typer.Exit(1)

    from tradingagents.graph.structural_forces import propose_causal_extension, get_force

    force = get_force(force_id)
    if force is None:
        console.print(f"[red]Force not found: {force_id}[/red]")
        console.print("[dim]Use 'forces list' to see available force IDs.[/dim]")
        raise typer.Exit(1)

    console.print(f"[yellow]Querying LLM for missing causal step in '{force.display_name}'...[/yellow]")
    proposal = propose_causal_extension(force_id)

    if proposal is None:
        console.print("[red]Failed to get a valid proposal. Check provider config and try again.[/red]")
        raise typer.Exit(1)

    tickers_str = ", ".join(proposal.get("tickers") or []) or "(none)"
    body = (
        f"[bold red]PROPOSED — NOT YET ADDED TO REGISTRY[/bold red]\n\n"
        f"[bold]Step Description:[/bold] {proposal.get('step_description', '')}\n"
        f"[bold]Sector:[/bold] {proposal.get('sector', '')}\n"
        f"[bold]Tickers:[/bold] [cyan]{tickers_str}[/cyan]\n"
        f"[bold]Necessity Score:[/bold] {proposal.get('necessity_score', 0):.2f}\n\n"
        f"[bold]Reasoning:[/bold]\n{proposal.get('reasoning', '')}\n\n"
        f"[dim]To add: manually insert a CausalStep into STRUCTURAL_FORCES['{force_id}'].causal_chain "
        f"in tradingagents/graph/structural_forces.py[/dim]"
    )

    console.print(
        Panel(
            body,
            title=f"Proposed Extension — {force.display_name}",
            border_style="yellow",
        )
    )


@forces_app.command("export-vault")
def export_vault(
    vault_path: str = typer.Argument(
        "docs/akg_vault",
        help="Output directory for the Obsidian vault.",
    ),
):
    """Export the full AKG as an Obsidian-compatible Markdown vault."""
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

    console.print("Loading AKG...")
    akg = AeternusKnowledgeGraph.load()
    count = akg.to_obsidian(vault_path)
    console.print(f"[green]Wrote {count} files to {vault_path}/[/green]")
    console.print(f"[dim]Open in Obsidian: File > Open vault > {vault_path}[/dim]")
