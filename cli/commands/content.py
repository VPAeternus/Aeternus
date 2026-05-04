"""Content review and generation commands."""
import json
from pathlib import Path
from typing import Optional

from cli.common import *  # noqa: F401,F403


@app.command("content-review")
def content_review(
    date: Optional[str] = typer.Option(None, "--date", help="Date (YYYY-MM-DD), defaults to today"),
    ticker: Optional[str] = typer.Option(None, "--ticker", help="Filter to a single ticker"),
    tier: Optional[str] = typer.Option(None, "--tier", help="Post tier: hook, analysis, or article"),
    show: bool = typer.Option(False, "--show", help="Display full post text"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Review generated content posts for a given date."""
    import datetime as dt

    if not date:
        date = dt.datetime.now().strftime("%Y-%m-%d")

    results_dir = Path("results")
    if not results_dir.exists():
        console.print("[red]No results directory found.[/red]")
        raise typer.Exit(1)

    # Find all tickers with posts for this date
    items = []
    for ticker_dir in sorted(results_dir.iterdir()):
        if not ticker_dir.is_dir():
            continue
        if ticker and ticker_dir.name.upper() != ticker.upper():
            continue
        posts_dir = ticker_dir / date / "posts"
        report_path = ticker_dir / date / "analysis_report.json"
        if not posts_dir.exists():
            # Try to generate if report exists but posts don't
            if report_path.exists():
                try:
                    from tradingagents.graph.content_posts import generate_all_posts
                    generate_all_posts(ticker_dir.name, date)
                except Exception:
                    continue
            else:
                continue
        # Re-check after potential generation
        if not posts_dir.exists():
            continue

        hook_path = posts_dir / "post_1_hook.txt"
        analysis_path = posts_dir / "post_2_analysis.txt"
        article_path = posts_dir / "post_3_article.md"

        # Load score from report
        score_val = None
        rating_val = None
        if report_path.exists():
            try:
                rpt = json.loads(report_path.read_text())
                score_val = rpt.get("aeternus_score", {}).get("aeternus_score")
                rating_val = rpt.get("aeternus_score", {}).get("rating")
            except Exception:
                pass

        item = {
            "ticker": ticker_dir.name,
            "score": score_val,
            "rating": rating_val,
            "hook_chars": len(hook_path.read_text()) if hook_path.exists() else 0,
            "analysis_chars": len(analysis_path.read_text()) if analysis_path.exists() else 0,
            "article_words": len(article_path.read_text().split()) if article_path.exists() else 0,
            "hook_path": str(hook_path),
            "analysis_path": str(analysis_path),
            "article_path": str(article_path),
        }
        items.append(item)

    if not items:
        console.print(f"[yellow]No content found for {date}.[/yellow]")
        raise typer.Exit(0)

    output_format = str(format or "table").lower().strip()

    if output_format == "json":
        typer.echo(json.dumps({"date": date, "tickers": items}, indent=2))
        return

    console.print(f"\n[bold]Content for {date}[/bold] — {len(items)} ticker{'s' if len(items) != 1 else ''}\n")

    for item in items:
        score_str = f"{item['score']:.1f}" if item["score"] is not None else "N/A"
        rating_str = item["rating"] or "N/A"
        console.print(f"[bold cyan]{item['ticker']}[/bold cyan] (Score: {score_str}, {rating_str})")
        console.print(f"  Hook:     {item['hook_path']} ({item['hook_chars']:,} chars)")
        console.print(f"  Analysis: {item['analysis_path']} ({item['analysis_chars']:,} chars)")
        console.print(f"  Article:  {item['article_path']} ({item['article_words']:,} words)")
        console.print()

    if show:
        if not ticker:
            console.print("[yellow]Please specify --ticker when using --show[/yellow]")
            return

        # Find the matching item
        matching = [i for i in items if i["ticker"].upper() == ticker.upper()]
        if not matching:
            console.print(f"[yellow]No content found for {ticker} on {date}[/yellow]")
            return

        item = matching[0]

        # Map tiers to file paths
        tier_map = {
            "hook": ("Hook Post", item.get("hook_path", "")),
            "analysis": ("Analysis Post", item.get("analysis_path", "")),
            "article": ("Full Article", item.get("article_path", "")),
        }

        tiers_to_show = [tier.lower()] if tier else ["hook", "analysis", "article"]

        for t in tiers_to_show:
            if t not in tier_map:
                console.print(f"[red]Unknown tier: {t}. Use hook, analysis, or article.[/red]")
                continue
            label, path = tier_map[t]
            p = Path(path)
            if not p.exists():
                console.print(f"[yellow]{label} not found at {path}[/yellow]")
                continue
            text = p.read_text()
            console.print(Panel(text, title=f"[bold]{item['ticker']}[/bold] — {label}", border_style="cyan"))
            console.print()


@app.command("content-generate")
def content_generate(
    date: Optional[str] = typer.Option(None, "--date", help="Date (YYYY-MM-DD), defaults to today"),
    ticker: Optional[str] = typer.Option(None, "--ticker", help="Generate for a single ticker"),
):
    """Generate content posts from existing analysis reports."""
    import datetime as dt

    if not date:
        date = dt.datetime.now().strftime("%Y-%m-%d")

    results_dir = Path("results")
    if not results_dir.exists():
        console.print("[red]No results directory found.[/red]")
        raise typer.Exit(1)

    generated = 0
    failed = 0

    for ticker_dir in sorted(results_dir.iterdir()):
        if not ticker_dir.is_dir():
            continue
        if ticker and ticker_dir.name.upper() != ticker.upper():
            continue
        report_path = ticker_dir / date / "analysis_report.json"
        if not report_path.exists():
            continue

        try:
            from tradingagents.graph.content_posts import generate_all_posts
            result = generate_all_posts(ticker_dir.name, date)
            hook_len = len(result["hook"])
            article_words = len(result["article"].split())
            console.print(
                f"[green]Generated[/green] {ticker_dir.name}: "
                f"hook={hook_len} chars, article={article_words} words"
            )
            generated += 1
        except Exception as exc:
            console.print(f"[red]Failed[/red] {ticker_dir.name}: {exc}")
            failed += 1

    console.print(f"\n[bold]Done.[/bold] Generated: {generated}, Failed: {failed}")


@app.command("track-record-dashboard")
def track_record_dashboard(
    output: str = typer.Option("docs/track_record.html", "--output", "-o", help="Output HTML file path"),
    track_record_path: str = typer.Option(
        "eval_results/track_record.json", "--track-record-path", help="Track record JSON path"
    ),
    spy_benchmark: bool = typer.Option(True, "--spy-benchmark/--no-spy-benchmark", help="Include SPY benchmark"),
    open_browser: bool = typer.Option(False, "--open", help="Open dashboard in browser after generation"),
):
    """Generate a static HTML track record dashboard."""
    from tradingagents.graph.track_record_dashboard import generate_dashboard

    result_path = generate_dashboard(
        track_record_path=track_record_path,
        output_path=output,
        spy_benchmark=spy_benchmark,
    )
    console.print(f"[green]Dashboard generated:[/green] {result_path}")

    if open_browser:
        import webbrowser
        webbrowser.open(f"file://{Path(result_path).resolve()}")
