from cli.common import *  # noqa: F401,F403


@watchlist_app.command("add")
def watchlist_add(
    symbols: List[str],
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Add one or more ticker symbols to the manual watchlist."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    watchlist_path = _watchlist_path_from_config()
    normalized_symbols = _normalize_symbol_args(symbols)
    if not normalized_symbols:
        console.print("[red]Error: provide at least one ticker symbol[/red]")
        raise typer.Exit(1)

    ideas = [
        add_watchlist_idea(
            symbol=symbol,
            path=watchlist_path,
        )
        for symbol in normalized_symbols
    ]
    payload = {
        "action": "added",
        "count": len(ideas),
        "watchlist_path": str(watchlist_path),
        "items": ideas,
    }
    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
        return

    table = Table(title="Manual Watchlist Update")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Action", "added")
    table.add_row("Count", str(len(ideas)))
    table.add_row("Symbols", ", ".join(str(item.get("symbol", "")) for item in ideas))
    table.add_row("Path", str(watchlist_path))
    console.print(table)


@watchlist_app.command("remove")
def watchlist_remove(
    symbols: List[str],
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Deactivate one or more manual watchlist ideas by symbol."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    watchlist_path = _watchlist_path_from_config()
    normalized_symbols = _normalize_symbol_args(symbols)
    if not normalized_symbols:
        console.print("[red]Error: provide at least one ticker symbol[/red]")
        raise typer.Exit(1)

    removed_symbols = [
        symbol for symbol in normalized_symbols
        if remove_watchlist_idea(symbol=symbol, path=watchlist_path)
    ]
    payload = {
        "action": "removed" if removed_symbols else "not_found",
        "count": len(removed_symbols),
        "symbols": removed_symbols,
        "watchlist_path": str(watchlist_path),
    }
    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
        return

    if removed_symbols:
        console.print(f"[green]Removed from manual watchlist:[/green] {', '.join(removed_symbols)}")
    else:
        console.print("[yellow]No provided symbols were active in the watchlist.[/yellow]")


def _normalize_symbol_args(raw_symbols: List[str]) -> list[str]:
    normalized_symbols: list[str] = []
    seen: set[str] = set()
    for raw in raw_symbols or []:
        for part in str(raw or "").split(","):
            token = str(part or "").upper().strip().replace(".", "-")
            if not token or token in seen:
                continue
            seen.add(token)
            normalized_symbols.append(token)
    return normalized_symbols


@watchlist_app.command("list")
def watchlist_list(
    active_only: bool = typer.Option(
        True,
        "--active-only/--all",
        help="Show active watchlist entries only by default; use --all to include inactive entries.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """List manual watchlist ideas."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    watchlist_path = _watchlist_path_from_config()
    rows = list_watchlist_ideas(include_inactive=not active_only, path=watchlist_path)
    payload = {
        "watchlist_path": str(watchlist_path),
        "count": len(rows),
        "items": rows,
    }
    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
        return

    table = Table(title="Manual Watchlist")
    table.add_column("Symbol", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Sector", style="magenta")
    table.add_column("Score", justify="right")
    table.add_column("Active", justify="center")
    table.add_column("Created", style="green")
    for row in rows:
        snapshot = dict(row.get("context_snapshot", {}) or {})
        score = snapshot.get("aeternus_score")
        try:
            score_text = f"{float(score):.2f}"
        except (TypeError, ValueError):
            score_text = "None"
        table.add_row(
            str(row.get("symbol", "")),
            str(snapshot.get("display_name", "") or ""),
            str(snapshot.get("sector", "") or ""),
            score_text,
            "yes" if bool(row.get("active", True)) else "no",
            str(row.get("created_at", "")),
        )
    console.print(table)
    console.print(f"[dim]Path: {watchlist_path}[/dim]")


@watchlist_app.command("import")
def watchlist_import(
    file: Path = typer.Option(..., "--file", exists=True, readable=True, help="Input file path."),
    ttl_days: Optional[int] = typer.Option(
        None,
        "--ttl-days",
        min=1,
        help="Default TTL for imported rows without ttl_days.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Import manual watchlist ideas from JSON/line-delimited file."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    watchlist_path = _watchlist_path_from_config()
    ttl = int(ttl_days or DEFAULT_CONFIG.get("dealflow_manual_default_ttl_days", 30))
    imported, skipped = import_watchlist_ideas(file_path=file, ttl_days=ttl, path=watchlist_path)
    payload = {
        "watchlist_path": str(watchlist_path),
        "import_file": str(file),
        "imported": imported,
        "skipped": skipped,
    }
    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2))
        return

    console.print(
        f"[green]Watchlist import complete[/green] | imported={imported} | skipped={skipped}"
    )
    console.print(f"[dim]Path: {watchlist_path}[/dim]")
