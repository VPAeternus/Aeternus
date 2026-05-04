#!/usr/bin/env python3
"""
Analyst Discovery Report Generator

Generates comprehensive reports on:
- Which analysts are recommending which stocks
- Quality scores and track records
- Analyst consensus by ticker
- Recent analyst activity
- Top performing analysts

Usage:
  # Generate full report
  python analyst_discovery_report.py generate --output report.md

  # Show ticker consensus
  python analyst_discovery_report.py consensus --ticker NVDA

  # Show analyst activity
  python analyst_discovery_report.py activity --analyst microcap_mike

  # Export to JSON
  python analyst_discovery_report.py export --format json
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict
import statistics

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.tree import Tree
from rich import box

console = Console()
app = typer.Typer(help="Analyst Discovery Report Generator")

# Data paths
ANALYST_DIR = Path("./analyst_discovery_data/analysts")
INDEX_FILE = Path("./analyst_discovery_data/analyst_index.json")
SOCIAL_DIR = Path("./social_dealflow_data")


class AnalystReportGenerator:
    """Generate comprehensive analyst discovery reports."""
    
    def __init__(self):
        self.analysts = self._load_all_analysts()
        self.signals = self._load_recent_signals()
    
    def _load_all_analysts(self) -> Dict[str, dict]:
        """Load all analyst profiles."""
        analysts = {}
        if not ANALYST_DIR.exists():
            return analysts
        
        for file_path in ANALYST_DIR.glob("*.json"):
            try:
                data = json.loads(file_path.read_text())
                analysts[data['handle']] = data
            except Exception:
                continue
        
        return analysts
    
    def _load_recent_signals(self) -> List[Dict]:
        """Load recent analyst signals."""
        signals = []
        # This would load from social_dealflow_data in production
        return signals
    
    def get_ticker_coverage(self) -> Dict[str, List[Dict]]:
        """Get all tickers covered by analysts."""
        coverage = defaultdict(list)
        
        for handle, analyst in self.analysts.items():
            tickers = analyst.get('tickers_covered', [])
            quality = analyst.get('avg_quality_score', 0)
            tier = analyst.get('tier', 'C')
            
            for ticker in tickers:
                coverage[ticker].append({
                    'analyst': handle,
                    'quality': quality,
                    'tier': tier,
                    'followers': analyst.get('follower_count', 0),
                    'promoted': analyst.get('promoted_to_dealflow', False)
                })
        
        return dict(coverage)
    
    def get_analyst_leaderboard(self) -> List[Dict]:
        """Get analysts ranked by quality and consistency."""
        leaderboard = []
        
        for handle, analyst in self.analysts.items():
            scores = analyst.get('quality_scores', [])
            if len(scores) >= 3:  # Minimum track record
                leaderboard.append({
                    'handle': handle,
                    'tier': analyst.get('tier', 'C'),
                    'quality': analyst.get('avg_quality_score', 0),
                    'consistency': analyst.get('consistency_score', 0),
                    'followers': analyst.get('follower_count', 0),
                    'posts_analyzed': len(scores),
                    'tickers_covered': len(analyst.get('tickers_covered', [])),
                    'promoted': analyst.get('promoted_to_dealflow', False),
                    'discovery_date': analyst.get('discovered_at', '')[:10]
                })
        
        # Sort by quality score descending
        leaderboard.sort(key=lambda x: (x['quality'], x['consistency']), reverse=True)
        return leaderboard
    
    def get_ticker_consensus(self, ticker: str) -> Dict:
        """Get analyst consensus for a specific ticker."""
        coverage = self.get_ticker_coverage()
        
        if ticker not in coverage:
            return {'ticker': ticker, 'coverage_count': 0, 'analysts': []}
        
        analysts_covering = coverage[ticker]
        
        # Calculate weighted consensus
        total_weight = sum(a['quality'] for a in analysts_covering)
        avg_quality = total_weight / len(analysts_covering) if analysts_covering else 0
        
        # Count by tier
        tier_breakdown = defaultdict(int)
        for a in analysts_covering:
            tier_breakdown[a['tier']] += 1
        
        # Get top analysts
        top_analysts = sorted(analysts_covering, key=lambda x: x['quality'], reverse=True)[:5]
        
        return {
            'ticker': ticker,
            'coverage_count': len(analysts_covering),
            'average_analyst_quality': round(avg_quality, 1),
            'tier_breakdown': dict(tier_breakdown),
            'top_analysts': top_analysts,
            'in_dealflow': sum(1 for a in analysts_covering if a['promoted'])
        }
    
    def generate_markdown_report(self) -> str:
        """Generate comprehensive markdown report."""
        lines = []
        
        # Header
        lines.append("# Analyst Discovery Report")
        lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Analysts Tracked:** {len(self.analysts)}")
        lines.append(f"**Data Source:** Analyst Discovery Engine v1.0")
        lines.append("\n---\n")
        
        # Executive Summary
        lines.append("## Executive Summary\n")
        
        tier_counts = defaultdict(int)
        promoted_count = 0
        total_tickers = set()
        
        for analyst in self.analysts.values():
            tier_counts[analyst.get('tier', 'C')] += 1
            if analyst.get('promoted_to_dealflow', False):
                promoted_count += 1
            total_tickers.update(analyst.get('tickers_covered', []))
        
        lines.append(f"- **Total Analysts:** {len(self.analysts)}")
        lines.append(f"- **Elite (A-tier):** {tier_counts.get('A', 0)}")
        lines.append(f"- **Established (B-tier):** {tier_counts.get('B', 0)}")
        lines.append(f"- **Rising (C-tier):** {tier_counts.get('C', 0)}")
        lines.append(f"- **Emerging (D-tier):** {tier_counts.get('D', 0)}")
        lines.append(f"- **Promoted to Deal Flow:** {promoted_count}")
        lines.append(f"- **Unique Tickers Covered:** {len(total_tickers)}")
        lines.append("\n---\n")
        
        # Top Analysts Leaderboard
        lines.append("## Top Analysts Leaderboard\n")
        lines.append("| Rank | Analyst | Tier | Quality | Consistency | Followers | Tickers | Status |")
        lines.append("|------|---------|------|---------|-------------|-----------|---------|--------|")
        
        leaderboard = self.get_analyst_leaderboard()
        for i, analyst in enumerate(leaderboard[:20], 1):
            status = "✓ Deal Flow" if analyst['promoted'] else "○ Monitoring"
            lines.append(
                f"| {i} | @{analyst['handle']} | {analyst['tier']} | "
                f"{analyst['quality']:.0f} | {analyst['consistency']:.0f} | "
                f"{analyst['followers']:,} | {analyst['tickers_covered']} | {status} |"
            )
        
        lines.append("\n---\n")
        
        # Ticker Coverage
        lines.append("## Ticker Coverage by Analysts\n")
        coverage = self.get_ticker_coverage()
        
        # Sort tickers by number of analysts covering
        sorted_tickers = sorted(
            coverage.items(), 
            key=lambda x: len(x[1]), 
            reverse=True
        )
        
        lines.append("### Most Covered Tickers\n")
        lines.append("| Ticker | Analysts Covering | Avg Quality | Top Analyst |")
        lines.append("|--------|-------------------|-------------|-------------|")
        
        for ticker, analysts in sorted_tickers[:30]:
            avg_quality = sum(a['quality'] for a in analysts) / len(analysts)
            top_analyst = max(analysts, key=lambda x: x['quality'])
            lines.append(
                f"| {ticker} | {len(analysts)} | {avg_quality:.0f} | "
                f"@{top_analyst['analyst']} ({top_analyst['quality']:.0f}) |"
            )
        
        lines.append("\n---\n")
        
        # Recently Discovered Analysts
        lines.append("## Recently Discovered Analysts\n")
        
        recent = sorted(
            self.analysts.items(),
            key=lambda x: x[1].get('discovered_at', ''),
            reverse=True
        )[:10]
        
        lines.append("| Analyst | Discovered | Tier | Quality | Followers | Tickers |")
        lines.append("|---------|------------|------|---------|-----------|---------|")
        
        for handle, analyst in recent:
            lines.append(
                f"| @{handle} | {analyst.get('discovered_at', '')[:10]} | "
                f"{analyst.get('tier', 'C')} | {analyst.get('avg_quality_score', 0):.0f} | "
                f"{analyst.get('follower_count', 0):,} | "
                f"{len(analyst.get('tickers_covered', []))} |"
            )
        
        lines.append("\n---\n")
        
        # Analyst Recommendations by Ticker
        lines.append("## Detailed Analyst Recommendations\n")
        
        for ticker, analysts in sorted_tickers[:15]:
            lines.append(f"\n### {ticker}\n")
            
            consensus = self.get_ticker_consensus(ticker)
            lines.append(f"**Analyst Coverage:** {consensus['coverage_count']} analysts")
            lines.append(f"**Average Quality:** {consensus['average_analyst_quality']:.0f}/100")
            lines.append(f"**In Deal Flow:** {consensus['in_dealflow']}/{consensus['coverage_count']} analysts")
            
            lines.append("\n**Covering Analysts:**")
            for a in sorted(analysts, key=lambda x: x['quality'], reverse=True):
                status = "✓" if a['promoted'] else "○"
                lines.append(f"- {status} @{a['analyst']} (Quality: {a['quality']:.0f}, Tier: {a['tier']})")
            
            lines.append("")
        
        lines.append("\n---\n")
        lines.append(f"*Report generated by Analyst Discovery Engine*")
        lines.append(f"*For questions or updates, run: `python analyst_discovery_report.py --help`*")
        
        return "\n".join(lines)
    
    def generate_json_export(self) -> Dict:
        """Generate JSON export of all data."""
        return {
            'generated_at': datetime.now().isoformat(),
            'summary': {
                'total_analysts': len(self.analysts),
                'tickers_covered': len(self.get_ticker_coverage()),
                'avg_analyst_quality': statistics.mean([
                    a.get('avg_quality_score', 0) for a in self.analysts.values()
                ]) if self.analysts else 0
            },
            'analysts': self.analysts,
            'ticker_coverage': {
                k: [{**a, 'promoted': a['promoted']} for a in v]
                for k, v in self.get_ticker_coverage().items()
            },
            'leaderboard': self.get_analyst_leaderboard()
        }


@app.command()
def generate(
    output: str = typer.Option("analyst_discovery_report.md", help="Output file"),
    format: str = typer.Option("markdown", help="Format (markdown/json)"),
):
    """Generate comprehensive analyst discovery report."""
    console.print("[yellow]Generating Analyst Discovery Report...[/yellow]")
    
    generator = AnalystReportGenerator()
    
    if format == "json":
        data = generator.generate_json_export()
        Path(output).write_text(json.dumps(data, indent=2, default=str))
        console.print(f"[green]✓ JSON report saved to {output}[/green]")
    else:
        report = generator.generate_markdown_report()
        Path(output).write_text(report)
        console.print(f"[green]✓ Markdown report saved to {output}[/green]")
        
        # Show preview
        console.print("\n[bold]Report Preview:[/bold]")
        console.print(report[:2000] + "\n...")


@app.command()
def consensus(
    ticker: str = typer.Argument(..., help="Ticker to analyze"),
):
    """Show analyst consensus for a specific ticker."""
    generator = AnalystReportGenerator()
    consensus = generator.get_ticker_consensus(ticker.upper())
    
    if consensus['coverage_count'] == 0:
        console.print(f"[yellow]No analysts covering {ticker}[/yellow]")
        return
    
    console.print(Panel(
        f"[bold]{ticker.upper()} - Analyst Consensus[/bold]\n\n"
        f"Analysts Covering: {consensus['coverage_count']}\n"
        f"Average Quality: {consensus['average_analyst_quality']:.0f}/100\n"
        f"In Deal Flow: {consensus['in_dealflow']}/{consensus['coverage_count']}",
        box=box.ROUNDED
    ))
    
    table = Table(title=f"Analysts Covering {ticker}")
    table.add_column("Analyst", style="cyan")
    table.add_column("Tier", style="bold")
    table.add_column("Quality", justify="right")
    table.add_column("Followers", justify="right")
    table.add_column("Status")
    
    for a in sorted(consensus['top_analysts'], key=lambda x: x['quality'], reverse=True):
        status = "✓ Deal Flow" if a['promoted'] else "○ Monitoring"
        table.add_row(
            f"@{a['analyst']}",
            a['tier'],
            f"{a['quality']:.0f}",
            f"{a['followers']:,}",
            status
        )
    
    console.print(table)


@app.command()
def leaderboard(
    min_posts: int = typer.Option(3, help="Minimum posts for ranking"),
    tier: Optional[str] = typer.Option(None, help="Filter by tier"),
):
    """Show analyst quality leaderboard."""
    generator = AnalystReportGenerator()
    leaders = generator.get_analyst_leaderboard()
    
    if tier:
        leaders = [l for l in leaders if l['tier'] == tier]
    
    if not leaders:
        console.print("[yellow]No analysts meet criteria[/yellow]")
        return
    
    table = Table(title="Analyst Quality Leaderboard")
    table.add_column("Rank", justify="right")
    table.add_column("Analyst", style="cyan")
    table.add_column("Tier", style="bold")
    table.add_column("Quality", justify="right")
    table.add_column("Consistency", justify="right")
    table.add_column("Posts", justify="right")
    table.add_column("Tickers", justify="right")
    table.add_column("Status")
    
    for i, a in enumerate(leaders[:25], 1):
        status = "✓ Deal Flow" if a['promoted'] else "○ Monitoring"
        tier_color = {
            'A': 'bright_green',
            'B': 'green',
            'C': 'yellow',
            'D': 'dim'
        }.get(a['tier'], 'white')
        
        table.add_row(
            str(i),
            f"@{a['handle']}",
            f"[{tier_color}]{a['tier']}[/{tier_color}]",
            f"{a['quality']:.0f}",
            f"{a['consistency']:.0f}",
            str(a['posts_analyzed']),
            str(a['tickers_covered']),
            status
        )
    
    console.print(table)


@app.command()
def tickers(
    min_analysts: int = typer.Option(1, help="Minimum analysts covering"),
    sort_by: str = typer.Option("coverage", help="Sort by (coverage/quality)"),
):
    """Show all tickers covered by analysts."""
    generator = AnalystReportGenerator()
    coverage = generator.get_ticker_coverage()
    
    # Filter
    filtered = {k: v for k, v in coverage.items() if len(v) >= min_analysts}
    
    if not filtered:
        console.print("[yellow]No tickers meet criteria[/yellow]")
        return
    
    # Sort
    if sort_by == "coverage":
        sorted_items = sorted(filtered.items(), key=lambda x: len(x[1]), reverse=True)
    else:
        sorted_items = sorted(
            filtered.items(),
            key=lambda x: sum(a['quality'] for a in x[1]) / len(x[1]),
            reverse=True
        )
    
    table = Table(title=f"Tickers Covered by Analysts (min {min_analysts} analyst(s))")
    table.add_column("Ticker", style="cyan")
    table.add_column("Analysts", justify="right")
    table.add_column("Avg Quality", justify="right")
    table.add_column("Top Analyst")
    table.add_column("In Deal Flow", justify="right")
    
    for ticker, analysts in sorted_items[:50]:
        avg_quality = sum(a['quality'] for a in analysts) / len(analysts)
        top = max(analysts, key=lambda x: x['quality'])
        in_dealflow = sum(1 for a in analysts if a['promoted'])
        
        table.add_row(
            ticker,
            str(len(analysts)),
            f"{avg_quality:.0f}",
            f"@{top['analyst']}",
            f"{in_dealflow}/{len(analysts)}"
        )
    
    console.print(table)


@app.command()
def export(
    format: str = typer.Option("json", help="Export format (json/csv)"),
    output: str = typer.Option("analyst_export", help="Output filename (without extension)"),
):
    """Export analyst data for external use."""
    generator = AnalystReportGenerator()
    
    if format == "json":
        data = generator.generate_json_export()
        filename = f"{output}.json"
        Path(filename).write_text(json.dumps(data, indent=2, default=str))
        console.print(f"[green]✓ Exported to {filename}[/green]")
    
    elif format == "csv":
        # Generate CSV
        lines = ["handle,tier,quality,consistency,followers,tickers_covered,promoted"]
        
        for handle, analyst in generator.analysts.items():
            lines.append(
                f"{handle},"
                f"{analyst.get('tier', 'C')},"
                f"{analyst.get('avg_quality_score', 0):.1f},"
                f"{analyst.get('consistency_score', 0):.1f},"
                f"{analyst.get('follower_count', 0)},"
                f"{len(analyst.get('tickers_covered', []))},"
                f"{analyst.get('promoted_to_dealflow', False)}"
            )
        
        filename = f"{output}.csv"
        Path(filename).write_text("\n".join(lines))
        console.print(f"[green]✓ Exported to {filename}[/green]")


if __name__ == "__main__":
    app()
