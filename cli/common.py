from typing import Any, Dict, List, Optional, Tuple
import datetime
import re
import subprocess
import sys
import pandas as pd
import yfinance as yf
import typer
from pathlib import Path
from functools import wraps
from rich.console import Console
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=True)
import os

# Strict placeholder key validation
PLACEHOLDER_PREFIXES = ["OPENAI", "ANTHROPIC", "MINIMAX", "GOOGLE", "XAI"]
for key in os.environ:
    if any(prefix in key for prefix in PLACEHOLDER_PREFIXES):
        val = os.environ[key]
        if val and "your_" in val.lower():
             print(f"\n[bold red]CRITICAL CONFIG ERROR:[/bold red] Environment variable [yellow]{key}[/yellow] is a placeholder.")
             print(f"Current Value: '[cyan]{val}[/cyan]'")
             print(f"Please update your [bold].env[/bold] file or leave it empty.\n")
             raise ValueError(f"Invalid API Key placeholder: {key}")

from rich.panel import Panel
from rich.spinner import Spinner
from rich.live import Live
from rich.columns import Columns
from rich.markdown import Markdown
from rich.layout import Layout
from rich.text import Text
from rich.live import Live
from rich.table import Table
from collections import deque
import time
from rich.tree import Tree
from rich import box
from rich.align import Align
from rich.rule import Rule

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.graph.track_record import TrackRecord
from tradingagents.graph.audit import RatingAuditLog
from tradingagents.graph.hedging import (
    AdaptiveHedgeEngine,
    build_portfolio_risk_snapshot,
)


def _detect_s7_active() -> bool:
    """Check if S7a or S7b bear-regime signal is active on the latest SPY bar."""
    try:
        from tradingagents.phase_engine import data_engine, phase_engine
        spy = data_engine.load("SPY")
        phases = phase_engine.classify_phases(spy)
        i = len(spy) - 1
        if i < 1:
            return False
        s7a = bool(phase_engine.should_short_overnight(spy, phases, i, "SPY"))
        s7b = bool(phase_engine.is_weak_regime_rth(spy, phases, i))
        return s7a or s7b
    except Exception:
        return False
from tradingagents.graph.market_regime import MarketRegimeProvider
from tradingagents.graph.paper_execution import (
    build_hedge_order_intent,
    build_exit_execution_plan,
    build_rebalance_execution_plan,
    build_portfolio_plan,
    cancel_alpaca_order,
    cancel_all_open_orders,
    close_all_positions,
    close_position_with_adapter,
    evaluate_execution_readiness,
    evaluate_pretrade_risk,
    execute_plan_with_adapter,
    fetch_alpaca_orders_snapshot,
    fetch_alpaca_positions_snapshot,
    load_open_positions,
    refresh_positions_market_snapshot,
    reconcile_live_execution,
    submit_alpaca_order,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dealflow import DealFlowPipeline, DealFlowScheduler
from tradingagents.dealflow.account_discovery import (
    persist_x_account_candidates,
    run_x_account_discovery,
)
from tradingagents.dealflow.readiness import (
    evaluate_step1_readiness,
    persist_step1_readiness,
)
from tradingagents.dealflow.manual_watchlist import (
    add_idea as add_watchlist_idea,
    import_ideas as import_watchlist_ideas,
    list_ideas as list_watchlist_ideas,
    remove_idea as remove_watchlist_idea,
)
from tradingagents.evidence import (
    build_evidence_ablation,
    build_evidence_pack,
    build_evidence_regimes,
    build_evidence_telemetry,
    build_evidence_walkforward,
)
from cli.models import AnalystType
from cli.utils import *
import json as json_lib

console = Console()

app = typer.Typer(
    name="TradingAgents",
    help="TradingAgents CLI: Multi-Agents LLM Financial Trading Framework",
    add_completion=True,  # Enable shell completion
)
watchlist_app = typer.Typer(help="Manual deal-flow watchlist operations")
app.add_typer(watchlist_app, name="watchlist")


_POSITION_PATH_WARNING_EMITTED = False


def _warn_position_path_mismatch_once() -> None:
    """Warn operators when paper and live shadow ledgers share the same path."""
    global _POSITION_PATH_WARNING_EMITTED
    if _POSITION_PATH_WARNING_EMITTED:
        return

    paper_raw = str(
        DEFAULT_CONFIG.get(
            "paper_positions_path",
            "eval_results/paper_execution/positions.json",
        )
    ).strip()
    live_raw = str(
        DEFAULT_CONFIG.get(
            "live_positions_shadow_path", "eval_results/live_execution/positions_shadow.json",
        )
    ).strip()
    paper_norm = str(Path(paper_raw).expanduser().resolve(strict=False))
    live_norm = str(Path(live_raw).expanduser().resolve(strict=False))
    if paper_norm == live_norm:
        console.print(
            "[yellow]Startup warning:[/yellow] "
            "paper and live shadow position paths are identical; this can mix live and paper state."
        )
        console.print(f"[yellow]paper_positions_path:[/yellow] {paper_raw}")
        console.print(f"[yellow]live_positions_shadow_path:[/yellow] {live_raw}")
        console.print(
            "[yellow]Recommendation:[/yellow] set `LIVE_POSITIONS_SHADOW_PATH` to "
            "`eval_results/live_execution/positions_shadow.json`."
        )

    _POSITION_PATH_WARNING_EMITTED = True


@app.callback()
def _app_callback() -> None:
    """Global CLI callback used for lightweight startup warnings."""
    _warn_position_path_mismatch_once()


# Create a deque to store recent messages with a maximum length
class MessageBuffer:
    def __init__(self, max_length=100):
        self.messages = deque(maxlen=max_length)
        self.tool_calls = deque(maxlen=max_length)
        self.current_report = None
        self.final_report = None  # Store the complete final report
        self.agent_status = {
            # Analyst Team
            "Market Analyst": "pending",
                    "News Analyst": "pending",
            "Fundamentals Analyst": "pending",
            # Research Team
                                    # Trading Team
            "Trader": "pending",
            # Risk Management Team
                                    # Portfolio Management Team
            "Portfolio Manager": "pending",
        }
        self.current_agent = None
        self.report_sections = {
            "market_report": None,
                    "news_report": None,
            "fundamentals_report": None,
            "investment_plan": None,
            "trader_investment_plan": None,
            "final_trade_decision": None,
            "portfolio_risk_hedge": None,
            "aeternus_score": None,
        }

    def add_message(self, message_type, content):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.messages.append((timestamp, message_type, content))

    def add_tool_call(self, tool_name, args):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.tool_calls.append((timestamp, tool_name, args))

    def update_agent_status(self, agent, status):
        if agent in self.agent_status:
            self.agent_status[agent] = status
            self.current_agent = agent

    def update_report_section(self, section_name, content):
        if section_name in self.report_sections:
            self.report_sections[section_name] = content
            self._update_current_report()

    def _update_current_report(self):
        # For the panel display, only show the most recently updated section
        latest_section = None
        latest_content = None

        # Find the most recently updated section
        for section, content in self.report_sections.items():
            if content is not None:
                latest_section = section
                latest_content = content
               
        if latest_section and latest_content:
            # Format the current section for display
            section_titles = {
                "market_report": "Market Analysis",
                            "news_report": "News Analysis",
                "fundamentals_report": "Fundamentals Analysis",
                "investment_plan": "Research Team Decision",
                "trader_investment_plan": "Trading Team Plan",
                "final_trade_decision": "Portfolio Management Decision",
                "portfolio_risk_hedge": "Portfolio Risk & Hedge Recommendation",
                "aeternus_score": "Aeternus Score",
            }
            self.current_report = (
                f"### {section_titles[latest_section]}\n{latest_content}"
            )

        # Update the final complete report
        self._update_final_report()

    def _update_final_report(self):
        report_parts = []

        # I. Executive Summary: Portfolio Management Decision (Was IV)
        if self.report_sections["final_trade_decision"]:
            report_parts.append("# I. Executive Summary: Portfolio Management Decision\n")
            report_parts.append(self.report_sections["final_trade_decision"] + "\n")

        # II. Portfolio Risk & Hedge Recommendation
        if self.report_sections["portfolio_risk_hedge"]:
            report_parts.append("# II. Portfolio Risk & Hedge Recommendation\n")
            report_parts.append(self.report_sections["portfolio_risk_hedge"] + "\n")

        # III. Aeternus Score & Rating (Was V)
        if self.report_sections["aeternus_score"]:
            report_parts.append("# III. Aeternus Score & Rating\n")
            report_parts.append(self.report_sections["aeternus_score"] + "\n")

        # IV. Analyst Team Reports (Was I)
        if any(
            self.report_sections[section]
            for section in [
                "market_report",
                            "news_report",
                "fundamentals_report",
            ]
        ):
            report_parts.append("# IV. Detailed Analyst Team Reports\n")
            if self.report_sections["market_report"]:
                report_parts.append(f"## Market Analyst\n{self.report_sections['market_report']}\n")
            if self.report_sections["news_report"]:
                report_parts.append(f"## News Analyst\n{self.report_sections['news_report']}\n")
            if self.report_sections["fundamentals_report"]:
                report_parts.append(f"## Fundamentals Analyst\n{self.report_sections['fundamentals_report']}\n")

        # V. Research Team Decision (Was II)
        if self.report_sections["investment_plan"]:
            report_parts.append("# V. Research Team Decision Detail\n")
            report_parts.append(self.report_sections["investment_plan"] + "\n")

        # VI. Trading Team Plan (Was III)
        if self.report_sections["trader_investment_plan"]:
            report_parts.append("# VI. Trading Team Strategic Plan\n")
            report_parts.append(self.report_sections["trader_investment_plan"] + "\n")

        self.final_report = "\n".join(report_parts)

    def get_equity_research_report(self, ticker, date):
        """Build a clean Equity Research Report."""
        header = f"""# Equity Research Report: {ticker}
Date: {date}
Built by: Aeternus Multi-Agent System

---

"""
        if not self.final_report:
            self._update_final_report()
            
        return header + (self.final_report or "Analysis in progress...")


message_buffer = MessageBuffer()


def create_layout():
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=3),
    )
    layout["main"].split_column(
        Layout(name="upper", ratio=3), Layout(name="analysis", ratio=5)
    )
    layout["upper"].split_row(
        Layout(name="progress", ratio=2), Layout(name="messages", ratio=3)
    )
    return layout


def update_display(layout, spinner_text=None):
    # Header with welcome message
    layout["header"].update(
        Panel(
            "[bold green]Welcome to TradingAgents CLI[/bold green]\n"
            "[dim]© [Tauric Research](https://github.com/TauricResearch)[/dim]",
            title="Welcome to TradingAgents",
            border_style="green",
            padding=(1, 2),
            expand=True,
        )
    )

    # Progress panel showing agent status
    progress_table = Table(
        show_header=True,
        header_style="bold magenta",
        show_footer=False,
        box=box.SIMPLE_HEAD,  # Use simple header with horizontal lines
        title=None,  # Remove the redundant Progress title
        padding=(0, 2),  # Add horizontal padding
        expand=True,  # Make table expand to fill available space
    )
    progress_table.add_column("Team", style="cyan", justify="center", width=20)
    progress_table.add_column("Agent", style="green", justify="center", width=20)
    progress_table.add_column("Status", style="yellow", justify="center", width=20)

    # Group agents by team
    teams = {
        "Analyst Team": [
            "Market Analyst",
            "News Analyst",
            "Fundamentals Analyst",
        ],
        "Trading Team": ["Trader"],
        "Portfolio Management": ["Portfolio Manager"],
    }

    for team, agents in teams.items():
        # Add first agent with team name
        first_agent = agents[0]
        status = message_buffer.agent_status[first_agent]
        if status == "in_progress":
            spinner = Spinner(
                "dots", text="[blue]in_progress[/blue]", style="bold cyan"
            )
            status_cell = spinner
        else:
            status_color = {
                "pending": "yellow",
                "completed": "green",
                "error": "red",
            }.get(status, "white")
            status_cell = f"[{status_color}]{status}[/{status_color}]"
        progress_table.add_row(team, first_agent, status_cell)

        # Add remaining agents in team
        for agent in agents[1:]:
            status = message_buffer.agent_status[agent]
            if status == "in_progress":
                spinner = Spinner(
                    "dots", text="[blue]in_progress[/blue]", style="bold cyan"
                )
                status_cell = spinner
            else:
                status_color = {
                    "pending": "yellow",
                    "completed": "green",
                    "error": "red",
                }.get(status, "white")
                status_cell = f"[{status_color}]{status}[/{status_color}]"
            progress_table.add_row("", agent, status_cell)

        # Add horizontal line after each team
        progress_table.add_row("─" * 20, "─" * 20, "─" * 20, style="dim")

    layout["progress"].update(
        Panel(progress_table, title="Progress", border_style="cyan", padding=(1, 2))
    )

    # Messages panel showing recent messages and tool calls
    messages_table = Table(
        show_header=True,
        header_style="bold magenta",
        show_footer=False,
        expand=True,  # Make table expand to fill available space
        box=box.MINIMAL,  # Use minimal box style for a lighter look
        show_lines=True,  # Keep horizontal lines
        padding=(0, 1),  # Add some padding between columns
    )
    messages_table.add_column("Time", style="cyan", width=8, justify="center")
    messages_table.add_column("Type", style="green", width=10, justify="center")
    messages_table.add_column(
        "Content", style="white", no_wrap=False, ratio=1
    )  # Make content column expand

    # Combine tool calls and messages
    all_messages = []

    # Add tool calls
    for timestamp, tool_name, args in message_buffer.tool_calls:
        # Truncate tool call args if too long
        if isinstance(args, str) and len(args) > 100:
            args = args[:97] + "..."
        all_messages.append((timestamp, "Tool", f"{tool_name}: {args}"))

    # Add regular messages
    for timestamp, msg_type, content in message_buffer.messages:
        # Convert content to string if it's not already
        content_str = content
        if isinstance(content, list):
            # Handle list of content blocks (Anthropic format)
            text_parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get('type') == 'text':
                        text_parts.append(item.get('text', ''))
                    elif item.get('type') == 'tool_use':
                        text_parts.append(f"[Tool: {item.get('name', 'unknown')}]")
                else:
                    text_parts.append(str(item))
            content_str = ' '.join(text_parts)
        elif not isinstance(content_str, str):
            content_str = str(content)
            
        # Truncate message content if too long
        if len(content_str) > 200:
            content_str = content_str[:197] + "..."
        all_messages.append((timestamp, msg_type, content_str))

    # Sort by timestamp
    all_messages.sort(key=lambda x: x[0])

    # Calculate how many messages we can show based on available space
    # Start with a reasonable number and adjust based on content length
    max_messages = 12  # Increased from 8 to better fill the space

    # Get the last N messages that will fit in the panel
    recent_messages = all_messages[-max_messages:]

    # Add messages to table
    for timestamp, msg_type, content in recent_messages:
        # Format content with word wrapping
        wrapped_content = Text(content, overflow="fold")
        messages_table.add_row(timestamp, msg_type, wrapped_content)

    if spinner_text:
        messages_table.add_row("", "Spinner", spinner_text)

    # Add a footer to indicate if messages were truncated
    if len(all_messages) > max_messages:
        messages_table.footer = (
            f"[dim]Showing last {max_messages} of {len(all_messages)} messages[/dim]"
        )

    layout["messages"].update(
        Panel(
            messages_table,
            title="Messages & Tools",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # Analysis panel showing current report
    if message_buffer.current_report:
        layout["analysis"].update(
            Panel(
                Markdown(message_buffer.current_report),
                title="Current Report",
                border_style="green",
                padding=(1, 2),
            )
        )
    else:
        layout["analysis"].update(
            Panel(
                "[italic]Waiting for analysis report...[/italic]",
                title="Current Report",
                border_style="green",
                padding=(1, 2),
            )
        )

    # Footer with statistics
    tool_calls_count = len(message_buffer.tool_calls)
    llm_calls_count = sum(
        1 for _, msg_type, _ in message_buffer.messages if msg_type == "Reasoning"
    )
    reports_count = sum(
        1 for content in message_buffer.report_sections.values() if content is not None
    )

    stats_table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
    stats_table.add_column("Stats", justify="center")
    stats_table.add_row(
        f"Tool Calls: {tool_calls_count} | LLM Calls: {llm_calls_count} | Generated Reports: {reports_count}"
    )

    layout["footer"].update(Panel(stats_table, border_style="grey50"))


def get_user_selections():
    """Get all user selections before starting the analysis display."""
    # Display ASCII art welcome message
    with open("./cli/static/welcome.txt", "r") as f:
        welcome_ascii = f.read()

    # Create welcome box content
    welcome_content = f"{welcome_ascii}\n"
    welcome_content += "[bold green]TradingAgents: Multi-Agents LLM Financial Trading Framework - CLI[/bold green]\n\n"
    welcome_content += "[bold]Workflow Steps:[/bold]\n"
    welcome_content += "I. Analyst Team → II. Research Team → III. Trader → IV. Risk Management → V. Portfolio Management\n\n"
    welcome_content += (
        "[dim]Built by [Tauric Research](https://github.com/TauricResearch)[/dim]"
    )

    # Create and center the welcome box
    welcome_box = Panel(
        welcome_content,
        border_style="green",
        padding=(1, 2),
        title="Welcome to TradingAgents",
        subtitle="Multi-Agents LLM Financial Trading Framework",
    )
    console.print(Align.center(welcome_box))
    console.print()  # Add a blank line after the welcome box

    # Create a boxed questionnaire for each step
    def create_question_box(title, prompt, default=None):
        box_content = f"[bold]{title}[/bold]\n"
        box_content += f"[dim]{prompt}[/dim]"
        if default:
            box_content += f"\n[dim]Default: {default}[/dim]"
        return Panel(box_content, border_style="blue", padding=(1, 2))

    # Step 1: Ticker symbol
    console.print(
        create_question_box(
            "Step 1: Ticker Symbol", "Enter the ticker symbol to analyze", "SPY"
        )
    )
    selected_ticker = get_ticker()

    # Step 2: Analysis date
    default_date = datetime.datetime.now().strftime("%Y-%m-%d")
    console.print(
        create_question_box(
            "Step 2: Analysis Date",
            "Enter the analysis date (YYYY-MM-DD)",
            default_date,
        )
    )
    analysis_date = get_analysis_date()

    # Step 3: Select analysts
    console.print(
        create_question_box(
            "Step 3: Analysts Team", "Select your LLM analyst agents for the analysis"
        )
    )
    selected_analysts = select_analysts()
    console.print(
        f"[green]Selected analysts:[/green] {', '.join(analyst.value for analyst in selected_analysts)}"
    )

    # Step 4: Research depth
    console.print(
        create_question_box(
            "Step 4: Research Depth", "Select your research depth level"
        )
    )
    selected_research_depth = select_research_depth()

    # Step 5: OpenAI backend
    console.print(
        create_question_box(
            "Step 5: OpenAI backend", "Select which service to talk to"
        )
    )
    selected_llm_provider, backend_url = select_llm_provider()
    
    # Step 6: Thinking agents
    console.print(
        create_question_box(
            "Step 6: Thinking Agents", "Select your thinking agents for analysis"
        )
    )
    selected_shallow_thinker = select_shallow_thinking_agent(selected_llm_provider)
    selected_deep_thinker = select_deep_thinking_agent(selected_llm_provider)

    return {
        "ticker": selected_ticker,
        "analysis_date": analysis_date,
        "analysts": selected_analysts,
        "research_depth": selected_research_depth,
        "llm_provider": selected_llm_provider.lower(),
        "backend_url": backend_url,
        "shallow_thinker": selected_shallow_thinker,
        "deep_thinker": selected_deep_thinker,
    }


def get_ticker():
    """Get ticker symbol from user input."""
    return typer.prompt("", default="SPY")


def get_analysis_date():
    """Get the analysis date from user input."""
    while True:
        date_str = typer.prompt(
            "", default=datetime.datetime.now().strftime("%Y-%m-%d")
        )
        try:
            # Validate date format and ensure it's not in the future
            analysis_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            if analysis_date.date() > datetime.datetime.now().date():
                console.print("[red]Error: Analysis date cannot be in the future[/red]")
                continue
            return date_str
        except ValueError:
            console.print(
                "[red]Error: Invalid date format. Please use YYYY-MM-DD[/red]"
            )


def display_complete_report(final_state):
    """Display the complete analysis report with team-based panels."""
    console.print("\n[bold green]Complete Analysis Report[/bold green]\n")

    # I. Analyst Team Reports
    analyst_reports = []

    # Market Analyst Report
    if final_state.get("market_report"):
        analyst_reports.append(
            Panel(
                Markdown(final_state["market_report"]),
                title="Market Analyst",
                border_style="blue",
                padding=(1, 2),
            )
        )

    # News Analyst Report
    if final_state.get("news_report"):
        analyst_reports.append(
            Panel(
                Markdown(final_state["news_report"]),
                title="News Analyst",
                border_style="blue",
                padding=(1, 2),
            )
        )

    # Fundamentals Analyst Report
    if final_state.get("fundamentals_report"):
        analyst_reports.append(
            Panel(
                Markdown(final_state["fundamentals_report"]),
                title="Fundamentals Analyst",
                border_style="blue",
                padding=(1, 2),
            )
        )

    if analyst_reports:
        console.print(
            Panel(
                Columns(analyst_reports, equal=True, expand=True),
                title="I. Analyst Team Reports",
                border_style="cyan",
                padding=(1, 2),
            )
        )

    # III. Trading Team Reports
    if final_state.get("trader_investment_plan"):
        console.print(
            Panel(
                Panel(
                    Markdown(final_state["trader_investment_plan"]),
                    title="Trader",
                    border_style="blue",
                    padding=(1, 2),
                ),
                title="III. Trading Team Plan",
                border_style="yellow",
                padding=(1, 2),
            )
        )

    # VI. Portfolio Risk & Hedge Recommendation
    if final_state.get("portfolio_snapshot") or final_state.get("hedge_decision"):
        console.print(
            Panel(
                Markdown(
                    format_portfolio_risk_hedge_markdown(
                        final_state.get("portfolio_snapshot", {}),
                        final_state.get("market_regime", {}),
                        final_state.get("hedge_signal", {}),
                        final_state.get("hedge_decision", {}),
                    )
                ),
                title="VI. Portfolio Risk & Hedge Recommendation",
                border_style="yellow",
                padding=(1, 2),
            )
        )

    # VII. Aeternus Score
    if final_state.get("aeternus_score"):
        console.print(
            Panel(
                Markdown(
                    format_aeternus_score_markdown(
                        final_state["aeternus_score"],
                        final_state.get("thesis_check"),
                    )
                ),
                title="VII. Aeternus Score",
                border_style="bright_cyan",
                padding=(1, 2),
            )
        )


def _format_number(value, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "N/A"


def _format_currency(value, digits: int = 2) -> str:
    try:
        return f"${float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "N/A"


def format_portfolio_risk_hedge_markdown(
    portfolio_snapshot: dict,
    market_regime: dict,
    hedge_signal: dict,
    hedge_decision: dict,
    heading: str = "### Portfolio Risk & Hedge Recommendation",
) -> str:
    """Render portfolio risk metrics and hedge recommendation as markdown."""
    portfolio_snapshot = portfolio_snapshot or {}
    market_regime = market_regime or {}
    hedge_signal = hedge_signal or {}
    hedge_decision = hedge_decision or {}

    lines = [
        heading,
        "",
        "#### Portfolio Risk Snapshot",
        "| Metric | Value |",
        "|---|---|",
        f"| Gross Exposure | {_format_currency(portfolio_snapshot.get('gross_exposure_usd'))} |",
        f"| Net Exposure | {_format_currency(portfolio_snapshot.get('net_exposure_usd'))} |",
        f"| Beta (60d) | {_format_number(portfolio_snapshot.get('portfolio_beta_60d'), 3)} |",
        f"| VaR 95% (1d % NAV) | {_format_number(portfolio_snapshot.get('var_95_1d_pct_nav'))}% |",
        f"| Drawdown (20d) | {_format_number(portfolio_snapshot.get('drawdown_20d_pct'))}% |",
        f"| Tech Concentration | {_format_number(portfolio_snapshot.get('tech_concentration_pct'))}% |",
        f"| Current Hedge | {_format_number(portfolio_snapshot.get('current_hedge_pct'))}% |",
    ]

    if market_regime:
        lines.extend(
            [
                "",
                "#### Market Regime Snapshot",
                "| Metric | Value |",
                "|---|---|",
                f"| SPY Close | {_format_number(market_regime.get('spy_close'))} |",
                f"| SPY SMA20 | {_format_number(market_regime.get('spy_sma20'))} |",
                f"| SPY SMA200 | {_format_number(market_regime.get('spy_sma200'))} |",
                f"| SPY Deviation % | {_format_number(market_regime.get('spy_deviation_pct'))}% |",
                f"| VIX Close | {_format_number(market_regime.get('vix_close'))} |",
            ]
        )

    lines.extend(
        [
            "",
            "#### Hedge Recommendation",
            "| Metric | Value |",
            "|---|---|",
            f"| Regime | {hedge_signal.get('market_regime', 'UNKNOWN')} |",
            f"| Mode | {hedge_signal.get('mode', 'BULL')} |",
            f"| Action | {hedge_decision.get('action', 'NO_CHANGE')} |",
            f"| Instrument | {hedge_decision.get('instrument', 'SPY')} |",
            f"| Target Hedge % | {_format_number(hedge_decision.get('final_target_hedge_pct'))}% |",
            f"| Delta Hedge % | {_format_number(hedge_decision.get('delta_hedge_pct'))}% |",
            f"| Delta Notional | {_format_currency(hedge_decision.get('delta_notional_usd'))} |",
            f"| Status | {hedge_decision.get('status', 'UNKNOWN')} |",
            f"| Reason | {hedge_decision.get('reason', 'N/A')} |",
        ]
    )
    return "\n".join(lines)


def build_portfolio_risk_summary(
    portfolio_snapshot: dict,
    hedge_signal: dict,
    hedge_decision: dict,
    market_snapshot: Optional[dict] = None,
) -> dict:
    """Build a compact, machine-friendly risk + hedge summary for plan artifacts."""
    portfolio_snapshot = portfolio_snapshot or {}
    hedge_signal = hedge_signal or {}
    hedge_decision = hedge_decision or {}
    market_snapshot = market_snapshot or {}
    return {
        "gross_exposure_usd": float(portfolio_snapshot.get("gross_exposure_usd", 0.0) or 0.0),
        "net_exposure_usd": float(portfolio_snapshot.get("net_exposure_usd", 0.0) or 0.0),
        "portfolio_beta_60d": float(portfolio_snapshot.get("portfolio_beta_60d", 0.0) or 0.0),
        "var_95_1d_pct_nav": float(portfolio_snapshot.get("var_95_1d_pct_nav", 0.0) or 0.0),
        "drawdown_20d_pct": float(portfolio_snapshot.get("drawdown_20d_pct", 0.0) or 0.0),
        "tech_concentration_pct": float(portfolio_snapshot.get("tech_concentration_pct", 0.0) or 0.0),
        "current_hedge_pct": float(portfolio_snapshot.get("current_hedge_pct", 0.0) or 0.0),
        "market_regime": str(hedge_signal.get("market_regime", "UNKNOWN")),
        "hedge_mode": str(hedge_signal.get("mode", "BULL")),
        "hedge_action": str(hedge_decision.get("action", "NO_CHANGE")),
        "hedge_instrument": str(hedge_decision.get("instrument", "SPY")),
        "target_hedge_pct": float(hedge_decision.get("final_target_hedge_pct", 0.0) or 0.0),
        "delta_hedge_pct": float(hedge_decision.get("delta_hedge_pct", 0.0) or 0.0),
        "delta_notional_usd": float(hedge_decision.get("delta_notional_usd", 0.0) or 0.0),
        "hedge_status": str(hedge_decision.get("status", "UNKNOWN")),
        "hedge_reason": str(hedge_decision.get("reason", "")),
        "spy_close": float(market_snapshot.get("spy_close", 0.0) or 0.0),
        "vix_close": float(market_snapshot.get("vix_close", 0.0) or 0.0),
    }


def build_pretrade_risk_context() -> tuple[dict, dict, dict, dict, str]:
    """Compute non-persistent risk/hedge context for portfolio-manager reasoning."""
    try:
        portfolio_snapshot = build_portfolio_risk_snapshot()
        market_snapshot = MarketRegimeProvider().get_market_regime_snapshot()
        engine = AdaptiveHedgeEngine()
        s7_active = _detect_s7_active()
        hedge_signal = engine.compute_hedge_signal(portfolio_snapshot, market_snapshot, s7_active=s7_active)
        hedge_decision = engine.decide_hedge(hedge_signal, portfolio_snapshot)
        risk_brief = format_portfolio_risk_hedge_markdown(
            portfolio_snapshot,
            market_snapshot or {},
            hedge_signal,
            hedge_decision,
            heading="### Pre-Trade Portfolio Risk Context",
        )
        return portfolio_snapshot, market_snapshot or {}, hedge_signal, hedge_decision, risk_brief
    except Exception:
        fallback_snapshot = {}
        fallback_regime = {}
        fallback_signal = {
            "market_regime": "UNKNOWN",
            "mode": "BULL",
            "target_hedge_pct_pre_hysteresis": 0.0,
            "data_sufficient": False,
        }
        fallback_decision = {
            "final_target_hedge_pct": 0.0,
            "instrument": "SPY",
            "action": "NO_CHANGE",
            "delta_hedge_pct": 0.0,
            "delta_notional_usd": 0.0,
            "reason": "Pre-trade risk context unavailable.",
            "status": "DATA_INSUFFICIENT",
        }
        fallback_brief = format_portfolio_risk_hedge_markdown(
            fallback_snapshot,
            fallback_regime,
            fallback_signal,
            fallback_decision,
            heading="### Pre-Trade Portfolio Risk Context",
        )
        return fallback_snapshot, fallback_regime, fallback_signal, fallback_decision, fallback_brief


def format_thesis_check_markdown(thesis_check: dict) -> str:
    """Format daily thesis comparison results for reports."""
    if not isinstance(thesis_check, dict):
        return ""

    thesis_change = str(thesis_check.get("thesis_change", "NO")).upper()
    reason = thesis_check.get("reason", "No rationale provided.")
    confidence = thesis_check.get("confidence", "N/A")
    signals = thesis_check.get("daily_signals", []) or []

    lines = [
        "### Daily Thesis Check",
        "| Question | Answer |",
        "|---|---|",
        f"| Based on daily data, would the current thesis change? | {thesis_change} |",
    ]

    if thesis_change == "YES":
        lines.append(f"| If yes, why? | {reason} |")
    else:
        lines.append(f"| If no, why? | {reason} |")

    lines.append(f"| Thesis-check confidence | {confidence}/5 |")

    if signals:
        lines.extend(["", "**Daily Signals Considered:**"])
        for signal in signals[:5]:
            lines.append(f"- {signal}")

    return "\n".join(lines)


def format_aeternus_score_markdown(score_payload: dict, thesis_check: dict = None) -> str:
    """Format the Aeternus score payload into a markdown block."""
    if not isinstance(score_payload, dict):
        return "No Aeternus score available."

    score = score_payload.get("aeternus_score", "N/A")
    rating = score_payload.get("rating", "N/A")
    confidence = score_payload.get("confidence", "N/A")
    breakdown = score_payload.get("breakdown", {}) or {}
    rationales = score_payload.get("rationales", {}) or {}
    sector = score_payload.get("sector") or "N/A"
    peer_comparison = score_payload.get("peer_comparison", {}) or {}
    peer_details = peer_comparison.get("details", []) if isinstance(peer_comparison, dict) else []
    valuation_status = (
        peer_comparison.get("valuation_status")
        or peer_comparison.get("status")
        or "N/A"
    ) if isinstance(peer_comparison, dict) else "N/A"

    lines = [
        f"**Aeternus Score:** {score}",
        f"**Rating:** {rating}",
        f"**Confidence:** {confidence}/5",
        "",
        "### Breakdown",
        "| Dimension | Score | Rationale |",
        "|---|---:|---|",
        f"| Fundamental | {breakdown.get('fundamental', 'N/A')} | {rationales.get('fundamental', '')} |",
        f"| Technical | {breakdown.get('technical', 'N/A')} | {rationales.get('technical', '')} |",
        f"| Macro | {breakdown.get('macro', 'N/A')} | {rationales.get('macro', '')} |",
        f"| Momentum | {breakdown.get('momentum', 'N/A')} | {rationales.get('momentum', '')} |",
        "",
        "### Sector Context",
        "| Metric | Value |",
        "|---|---|",
        f"| Sector | {sector} |",
        f"| Valuation Status | {valuation_status} |",
        f"| Peer Avg P/E | {_format_number(peer_comparison.get('peer_average_pe')) if isinstance(peer_comparison, dict) else 'N/A'} |",
        f"| Target P/E | {_format_number(peer_comparison.get('target_pe')) if isinstance(peer_comparison, dict) else 'N/A'} |",
        f"| Premium/Discount % | {_format_number(peer_comparison.get('premium_discount_percent')) if isinstance(peer_comparison, dict) else 'N/A'} |",
    ]

    if peer_details:
        lines.extend(
            [
                "",
                "### Peer Snapshot",
                "| Peer | P/E | P/B | Market Cap |",
                "|---|---:|---:|---:|",
            ]
        )
        for peer in peer_details[:5]:
            lines.append(
                f"| {peer.get('ticker', 'N/A')} | "
                f"{_format_number(peer.get('pe'))} | "
                f"{_format_number(peer.get('price_to_book'))} | "
                f"{peer.get('market_cap', 'N/A')} |"
            )

    thesis_md = format_thesis_check_markdown(thesis_check)
    if thesis_md:
        lines.extend(["", thesis_md])

    return "\n".join(lines)


def run_hedging_cycle(rating_id: Optional[str] = None):
    """Run deterministic hedging signal/decision flow and emit audit events."""
    portfolio_snapshot = build_portfolio_risk_snapshot()
    market_snapshot = MarketRegimeProvider().get_market_regime_snapshot()

    engine = AdaptiveHedgeEngine()
    s7_active = _detect_s7_active()
    hedge_signal, hedge_decision, hedge_order = engine.evaluate(
        portfolio_snapshot,
        market_snapshot,
        s7_active=s7_active,
    )

    try:
        audit_rating_id = rating_id or "UNKNOWN"
        audit = RatingAuditLog()
        audit.log_event(
            "HEDGE_SIGNAL_GENERATED",
            audit_rating_id,
            {
                "portfolio_snapshot": portfolio_snapshot,
                "market_regime": market_snapshot or {},
                "hedge_signal": hedge_signal,
            },
        )

        if hedge_decision.get("status") == "EXECUTED":
            previous_hedge = float(portfolio_snapshot.get("current_hedge_pct", 0.0))
            event_type = "HEDGE_APPLIED" if previous_hedge == 0.0 else "HEDGE_REBALANCED"
            audit.log_event(
                event_type,
                audit_rating_id,
                {
                    "hedge_decision": hedge_decision,
                    "hedge_order": hedge_order or {},
                },
            )
        elif hedge_decision.get("status") == "SKIPPED_HYSTERESIS":
            audit.log_event(
                "HEDGE_SKIPPED_HYSTERESIS",
                audit_rating_id,
                {"hedge_decision": hedge_decision},
            )
    except Exception:
        pass

    return portfolio_snapshot, market_snapshot or {}, hedge_signal, hedge_decision



import uuid  # noqa: E402 - missing from original, used in _run_manage_open_orders_once

def _today_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d")


def _provider_default_backend(provider: str) -> str:
    provider = (provider or "openai").lower()
    mapping = {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com/",
        "minimax": "https://api.minimax.io/anthropic",
        "xai": "https://api.x.ai/v1",
        "google": "https://generativelanguage.googleapis.com/v1",
        "ollama": "http://localhost:11434/v1",
        "claude_cli": "claude_cli",
        "codex_cli": "codex_cli",
    }
    return mapping.get(provider, DEFAULT_CONFIG.get("backend_url", "https://api.openai.com/v1"))


def _provider_default_models(provider: str) -> Tuple[str, str]:
    provider = (provider or "openai").lower()
    mapping = {
        "openai": ("gpt-4o-mini", "o4-mini"),
        "anthropic": ("claude-haiku-4-5-20251001", "claude-opus-4-6"),
        "minimax": ("MiniMax-M2.5", "MiniMax-M2.5"),
        "xai": ("grok-4-1-fast-reasoning", "grok-4-1-fast-reasoning"),
        "google": ("gemini-2.0-flash", "gemini-2.5-pro"),
        "ollama": ("llama3.1", "qwen3"),
        "claude_cli": ("claude-sonnet-4-6", "claude-sonnet-4-6"),
        "codex_cli": (
            str(DEFAULT_CONFIG.get("codex_cli_quick_model", "gpt-5.4")),
            str(DEFAULT_CONFIG.get("codex_cli_deep_model", "gpt-5.4")),
        ),
    }
    return mapping.get(
        provider,
        (
            str(DEFAULT_CONFIG.get("quick_think_llm", "gpt-4o-mini")),
            str(DEFAULT_CONFIG.get("deep_think_llm", "o4-mini")),
        ),
    )


def _resolve_noninteractive_provider() -> str:
    """Resolve the LLM provider for non-interactive (batch/queue) runs.

    Priority order:
    1. OAuth tokens (ANTHROPIC_AUTH_TOKEN, OPENAI_AUTH_TOKEN)
    2. Explicit provider env vars (AETERNUS_LLM_PROVIDER, TRADINGAGENTS_LLM_PROVIDER, LLM_PROVIDER)
    3. Configured default provider (from DEFAULT_CONFIG.llm_provider) if its API key is available
    4. First available provider key in fallback order (claude_cli > anthropic > minimax > google)
    5. claude_cli (zero cost default)
    """
    # OAuth tokens take priority over everything
    if os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return "anthropic"
    if os.getenv("OPENAI_AUTH_TOKEN"):
        return "openai"

    # Explicit env var provider setting (if present, trust it)
    provider_env = (
        os.getenv("AETERNUS_LLM_PROVIDER")
        or os.getenv("TRADINGAGENTS_LLM_PROVIDER")
        or os.getenv("LLM_PROVIDER")
    )
    if provider_env:
        return str(provider_env).lower()

    # For batch/queue runs: if configured provider has its API key, use it
    # Otherwise fall back to the first available key in priority order
    configured_provider = str(DEFAULT_CONFIG.get("llm_provider", "openai")).lower()

    # Map providers to their API key env vars
    provider_api_keys = {
        "anthropic": "ANTHROPIC_API_KEY",
        "minimax": "MINIMAX_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
    }

    # Check if configured provider has its API key available
    if configured_provider in provider_api_keys:
        if os.getenv(provider_api_keys[configured_provider]):
            return configured_provider

    # Fallback: try providers in priority order
    provider_key_fallbacks = (
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("minimax", "MINIMAX_API_KEY"),
        ("google", "GOOGLE_API_KEY"),
    )
    for fallback_provider, env_key in provider_key_fallbacks:
        if os.getenv(env_key):
            return fallback_provider

    # Last resort: claude_cli (zero cost, always available)
    return "claude_cli"

def _build_noninteractive_selections(
    ticker: str,
    analysis_date: str,
    analyst_provider: Optional[str] = None,
    post_analyst_provider: Optional[str] = None,
) -> Dict[str, Any]:
    selected_analyst_provider = str(
        analyst_provider or DEFAULT_CONFIG.get("research_analyst_provider", "gpt")
    ).strip().lower()
    selected_post_provider = str(
        post_analyst_provider or DEFAULT_CONFIG.get("research_post_analyst_provider", "claude")
    ).strip().lower()
    provider = "codex_cli" if selected_post_provider == "gpt" else (
        "claude_cli" if selected_post_provider == "claude" else selected_post_provider
    )
    if provider not in {"codex_cli", "claude_cli", "gemini"}:
        provider = _resolve_noninteractive_provider()

    backend_url = (
        os.getenv("AETERNUS_BACKEND_URL")
        or os.getenv("TRADINGAGENTS_BACKEND_URL")
        or os.getenv("BACKEND_URL")
        or _provider_default_backend(provider)
    )
    default_quick, default_deep = _provider_default_models(provider)
    quick_model = (
        os.getenv("AETERNUS_QUICK_MODEL")
        or os.getenv("TRADINGAGENTS_QUICK_MODEL")
        or default_quick
    )
    deep_model = (
        os.getenv("AETERNUS_DEEP_MODEL")
        or os.getenv("TRADINGAGENTS_DEEP_MODEL")
        or default_deep
    )
    if (
        provider == "xai"
        and not os.getenv("AETERNUS_DEEP_MODEL")
        and not os.getenv("TRADINGAGENTS_DEEP_MODEL")
    ):
        # Non-interactive runs favor deterministic completion speed.
        deep_model = quick_model

    selections = {
        "ticker": ticker,
        "analysis_date": analysis_date,
        "analysts": [
            AnalystType.MARKET,
            AnalystType.SOCIAL,
            AnalystType.NEWS,
            AnalystType.FUNDAMENTALS,
        ],
        "research_depth": 1,
        "llm_provider": provider,
        "backend_url": backend_url,
        "shallow_thinker": quick_model,
        "deep_thinker": deep_model,
        "analyst_provider": selected_analyst_provider,
        "post_analyst_provider": selected_post_provider,
    }
    if provider == "xai":
        # Prevent expensive multi-vendor news fan-out in non-interactive runs.
        selections["tool_vendors_override"] = {
            "get_news": "xai",
            "get_global_news": "xai",
            "get_fundamentals": "xai",
        }
    return selections


def _dealflow_base_dir() -> Path:
    return Path("eval_results") / "deal_flow"


def _watchlist_path_from_config() -> Path:
    configured = str(DEFAULT_CONFIG.get("dealflow_manual_watchlist_path", "")).strip()
    if configured:
        return Path(configured)
    return _dealflow_base_dir() / "manual_watchlist.json"


def _normalize_run_profile(raw: str) -> str:
    value = str(raw or "auto").strip().lower()
    aliases = {
        "auto": "AUTO",
        "daily": "LOW_COST",
        "low": "LOW_COST",
        "low-cost": "LOW_COST",
        "low_cost": "LOW_COST",
        "max": "MAX_RECALL",
        "max-recall": "MAX_RECALL",
        "max_recall": "MAX_RECALL",
    }
    resolved = aliases.get(value)
    if not resolved:
        raise ValueError("profile must be one of auto|daily|max-recall")
    return resolved


def _is_interactive_terminal() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def _resolve_run_profile(profile: str) -> str:
    normalized = _normalize_run_profile(profile)
    if normalized != "AUTO":
        return normalized

    if not _is_interactive_terminal():
        return "LOW_COST"

    selected = typer.prompt(
        "Deal-flow run profile [daily|max-recall]",
        default="daily",
    )
    return _normalize_run_profile(selected)


def _apply_run_profile_overrides(base_config: Dict[str, Any], run_profile: str) -> Dict[str, Any]:
    config = dict(base_config)

    def as_int(name: str, fallback: int) -> int:
        try:
            return int(config.get(name, fallback))
        except Exception:
            return fallback

    if run_profile == "MAX_RECALL":
        config["dealflow_x_max_api_calls_per_run"] = max(as_int("dealflow_x_max_api_calls_per_run", 8), 12)
        config["dealflow_dynamic_universe_max_extra_symbols"] = max(
            as_int("dealflow_dynamic_universe_max_extra_symbols", 60), 120
        )
        config["dealflow_x_enrich_top_posts"] = max(as_int("dealflow_x_enrich_top_posts", 20), 30)
    else:
        config["dealflow_x_max_api_calls_per_run"] = max(0, min(as_int("dealflow_x_max_api_calls_per_run", 8), 1))
        config["dealflow_dynamic_universe_max_extra_symbols"] = max(
            8, min(as_int("dealflow_dynamic_universe_max_extra_symbols", 60), 15)
        )
        config["dealflow_x_enrich_top_posts"] = max(2, min(as_int("dealflow_x_enrich_top_posts", 20), 5))

    config["dealflow_run_profile"] = run_profile
    return config


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> Dict[str, Any]:
    return json_lib.loads(path.read_text())


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _load_analysis_summary(summary_path: Path) -> Tuple[Dict[str, Any], Path]:
    path = Path(summary_path)
    if not path.exists():
        raise FileNotFoundError(f"Analysis summary not found: {path}")
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"Analysis summary must be a JSON object: {path}")
    return payload, path


def _results_base_dir() -> Path:
    return Path(str(DEFAULT_CONFIG.get("results_dir", "./results")))


def _analysis_report_path(symbol: str, analysis_date: str) -> Path:
    return _results_base_dir() / str(symbol).upper().strip() / str(analysis_date).strip() / "analysis_report.json"


def _paper_execution_base_dir() -> Path:
    return Path("eval_results") / "paper_execution"


def _live_execution_base_dir() -> Path:
    return Path("eval_results") / "live_execution"


def _persist_portfolio_plan(plan: Dict[str, Any]) -> Path:
    plan_date = str(plan.get("date") or _today_str())
    base = _paper_execution_base_dir() / "plans" / plan_date
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%H%M%S")
    path = base / f"portfolio_plan_{stamp}.json"
    payload = dict(plan)
    payload["plan_path"] = str(path)
    path.write_text(json_lib.dumps(payload, indent=2))
    latest = _paper_execution_base_dir() / "latest_plan.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json_lib.dumps(payload, indent=2))
    return path


def _persist_pretrade_risk(report: Dict[str, Any]) -> Path:
    report_date = str(report.get("date") or _today_str())
    base = _paper_execution_base_dir() / "risk_checks" / report_date
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%H%M%S")
    path = base / f"pretrade_risk_{stamp}.json"
    payload = dict(report)
    payload["risk_check_path"] = str(path)
    path.write_text(json_lib.dumps(payload, indent=2))
    latest = _paper_execution_base_dir() / "latest_pretrade_risk.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json_lib.dumps(payload, indent=2))
    return path


def _persist_execution_reconciliation(report: Dict[str, Any]) -> Path:
    stamp = datetime.datetime.now().strftime("%H%M%S")
    report_date = str(report.get("date") or _today_str())
    base = _live_execution_base_dir() / "reconciliation" / report_date
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"reconcile_{stamp}.json"
    payload = dict(report)
    payload["reconciliation_path"] = str(path)
    path.write_text(json_lib.dumps(payload, indent=2))
    latest = _live_execution_base_dir() / "latest_reconciliation.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json_lib.dumps(payload, indent=2))
    return path


def _persist_exit_management(report: Dict[str, Any]) -> Path:
    stamp = datetime.datetime.now().strftime("%H%M%S")
    report_date = str(report.get("date") or _today_str())
    base = _live_execution_base_dir() / "exits" / report_date
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"manage_exits_{stamp}.json"
    payload = dict(report)
    payload["exit_management_path"] = str(path)
    path.write_text(json_lib.dumps(payload, indent=2))
    latest = _live_execution_base_dir() / "latest_exit_management.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json_lib.dumps(payload, indent=2))
    return path


def _persist_execution_readiness(report: Dict[str, Any]) -> Path:
    stamp = datetime.datetime.now().strftime("%H%M%S")
    report_date = str(report.get("date") or _today_str())
    base = _live_execution_base_dir() / "readiness" / report_date
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"execution_readiness_{stamp}.json"
    payload = dict(report)
    payload["execution_readiness_path"] = str(path)
    path.write_text(json_lib.dumps(payload, indent=2))
    latest = _live_execution_base_dir() / "latest_execution_readiness.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json_lib.dumps(payload, indent=2))
    return path


def _persist_positions_drift(report: Dict[str, Any]) -> Path:
    stamp = datetime.datetime.now().strftime("%H%M%S")
    report_date = str(report.get("date") or _today_str())
    base = _live_execution_base_dir() / "positions_drift" / report_date
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"positions_drift_{stamp}.json"
    payload = dict(report)
    payload["positions_drift_path"] = str(path)
    path.write_text(json_lib.dumps(payload, indent=2))
    latest = _live_execution_base_dir() / "latest_positions_drift.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json_lib.dumps(payload, indent=2))
    return path


def _persist_open_orders_management(report: Dict[str, Any]) -> Path:
    stamp = datetime.datetime.now().strftime("%H%M%S")
    report_date = str(report.get("date") or _today_str())
    base = _live_execution_base_dir() / "open_orders" / report_date
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"manage_open_orders_{stamp}.json"
    payload = dict(report)
    payload["open_orders_management_path"] = str(path)
    path.write_text(json_lib.dumps(payload, indent=2))
    latest = _live_execution_base_dir() / "latest_open_orders_management.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json_lib.dumps(payload, indent=2))
    return path


def _persist_positions_sync(report: Dict[str, Any]) -> Path:
    stamp = datetime.datetime.now().strftime("%H%M%S")
    report_date = str(report.get("date") or _today_str())
    base = _live_execution_base_dir() / "positions_sync" / report_date
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"sync_positions_{stamp}.json"
    payload = dict(report)
    payload["positions_sync_path"] = str(path)
    path.write_text(json_lib.dumps(payload, indent=2))
    latest = _live_execution_base_dir() / "latest_positions_sync.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json_lib.dumps(payload, indent=2))
    return path


def _persist_workflow_run(report: Dict[str, Any]) -> Path:
    stamp = datetime.datetime.now().strftime("%H%M%S")
    report_date = str(report.get("date") or _today_str())
    base = _live_execution_base_dir() / "workflow" / report_date
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"workflow_run_{stamp}.json"
    payload = dict(report)
    payload["workflow_run_path"] = str(path)
    path.write_text(json_lib.dumps(payload, indent=2))
    latest = _live_execution_base_dir() / "latest_workflow_run.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json_lib.dumps(payload, indent=2))
    return path


def _persist_workflow_loop_run(report: Dict[str, Any]) -> Path:
    stamp = datetime.datetime.now().strftime("%H%M%S")
    report_date = str(report.get("date") or _today_str())
    base = _live_execution_base_dir() / "workflow" / report_date
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"workflow_loop_{stamp}.json"
    payload = dict(report)
    payload["workflow_loop_path"] = str(path)
    path.write_text(json_lib.dumps(payload, indent=2))
    latest = _live_execution_base_dir() / "latest_workflow_loop.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json_lib.dumps(payload, indent=2))
    return path


def _run_cli_subcommand_json(
    args: List[str],
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    cmd = [sys.executable or "python", "-m", "cli.main", *args, "--format", "json"]
    run_kwargs: Dict[str, Any] = {
        "cwd": str(_repo_root()),
        "capture_output": True,
        "text": True,
    }
    if timeout is not None:
        run_kwargs["timeout"] = int(timeout)

    completed = subprocess.run(cmd, **run_kwargs)
    stdout = str(completed.stdout or "")
    stderr = str(completed.stderr or "")
    payload = _extract_json_object_from_output(stdout)
    return {
        "cmd": cmd,
        "return_code": int(completed.returncode),
        "payload": payload,
        "stdout": stdout,
        "stderr": stderr,
    }


def _load_portfolio_plan(plan_path: Optional[Path] = None) -> Tuple[Dict[str, Any], Path]:
    if plan_path is not None:
        path = Path(plan_path)
        if not path.exists():
            raise FileNotFoundError(f"Portfolio plan not found: {path}")
        return _read_json(path), path

    latest = _paper_execution_base_dir() / "latest_plan.json"
    if latest.exists():
        return _read_json(latest), latest

    candidates = sorted((_paper_execution_base_dir() / "plans").glob("*/portfolio_plan_*.json"))
    if not candidates:
        raise FileNotFoundError(
            "No portfolio plan found. Run `aeternus portfolio-plan` first."
        )
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    return _read_json(path), path


def _resolve_execution_paths_for_mode(mode: str) -> Tuple[str, str]:
    normalized_mode = str(mode or "paper").strip().lower().replace("_", "-")
    live_submission_modes = {"live", "alpaca-paper", "alpaca-live"}
    if normalized_mode in live_submission_modes:
        orders_path = str(
            DEFAULT_CONFIG.get("live_execution_outbox_path", "eval_results/live_execution/outbox.json")
        )
        positions_path = str(
            DEFAULT_CONFIG.get("live_positions_shadow_path", "eval_results/live_execution/positions_shadow.json")
        )
        return orders_path, positions_path

    orders_path = str(DEFAULT_CONFIG.get("paper_orders_path", "eval_results/paper_execution/orders.json"))
    positions_path = str(DEFAULT_CONFIG.get("paper_positions_path", "eval_results/paper_execution/positions.json"))
    return orders_path, positions_path


def _render_v3_benchmark_panel(stats: Dict[str, Any]) -> None:
    """Render V3 index benchmark panel above the portfolio plan table."""
    if not stats:
        return
    ticker = stats.get("ticker", "QQQ")
    period = stats.get("period_days", 252)

    rth_label = "YES" if stats.get("current_rth") else "NO (covered call day)"
    on_label = "YES" if stats.get("current_overnight") else "NO"
    leg = stats.get("current_leg")
    leg_label = f" [{leg}]" if leg else ""

    total = stats.get("total_pts", 0)
    bh = stats.get("bh_pts", 0)
    sign_t = "+" if total >= 0 else ""
    sign_b = "+" if bh >= 0 else ""

    hurdle = DEFAULT_CONFIG.get("v3_hurdle_min_score", 62.0)

    v3_ret = stats.get("v3_total_return_pct", 0)
    bh_ret = stats.get("bh_total_return_pct", 0)
    v3_cagr = stats.get("v3_cagr_pct", 0)
    bh_cagr = stats.get("bh_cagr_pct", 0)
    sign_vr = "+" if v3_ret >= 0 else ""
    sign_br = "+" if bh_ret >= 0 else ""

    lines = [
        f"Today: RTH={rth_label}{leg_label} | Overnight={on_label}",
        f"Rolling {period}d: V3 {sign_t}{total:.1f} pts vs B&H {sign_b}{bh:.1f} pts",
        f"Returns: V3 {sign_vr}{v3_ret:.1f}% vs B&H {sign_br}{bh_ret:.1f}%",
        f"CAGR: V3 {v3_cagr:.2f}% vs B&H {bh_cagr:.2f}%",
        f"RTH skip rate: {stats.get('rth_skip_rate_pct', 0):.1f}% | "
        f"Overnight active: {stats.get('on_active_rate_pct', 0):.1f}%",
        f"HURDLE: Score >= {hurdle:.0f} to justify capital withdrawal from {ticker}",
    ]

    date_start = stats.get("date_start")
    date_end = stats.get("date_end")
    if date_start and date_end:
        lines.insert(4, f"Window: {date_start} → {date_end} ({period} days)")
    console.print(
        Panel(
            "\n".join(lines),
            title=f"V3 {ticker} Benchmark ({period}-day rolling)",
            border_style="blue",
            padding=(0, 2),
        )
    )


def _render_cc_scanner_panel(signals: List[Dict[str, Any]]) -> None:
    """Render Covered Call Opportunities panel from cc_scanner signals."""
    if not signals:
        return
    _LABEL_MAP = {
        "cc_overbought": "CC Overbought",
        "cc_wyckoff": "CC Wyckoff",
        "v3_rth_skip": "V3 RTH Skip",
    }
    table = Table(
        title=f"Covered Call Opportunities ({len(signals)} signal{'s' if len(signals) != 1 else ''})",
        box=box.SIMPLE_HEAVY,
    )
    table.add_column("Ticker", style="cyan")
    table.add_column("Signal", style="yellow")
    table.add_column("Detail", style="white")
    table.add_column("Regime", style="magenta")
    table.add_column("Close", justify="right")
    for s in signals:
        close_val = s.get("close")
        close_str = f"{float(close_val):.2f}" if close_val is not None else "N/A"
        table.add_row(
            str(s.get("ticker", "")),
            _LABEL_MAP.get(s.get("signal_type", ""), s.get("signal_type", "")),
            str(s.get("signal_detail", "")),
            str(s.get("regime", "")),
            close_str,
        )
    console.print(table)


def format_csp_overlay_panel(result: "CspOverlayResult") -> None:
    """Render the QQQ CSP Tactical Overlay panel to console."""
    from tradingagents.graph.csp_overlay import CspRecommendation

    # ── Regime Status section ────────────────────────────────────────────────
    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    tbl.add_column("Label", style="dim", min_width=22)
    tbl.add_column("Value", min_width=50)

    # QQQ price vs SMA200
    if result.sma200 > 0:
        pct_diff = (result.qqq_price - result.sma200) / result.sma200 * 100
        sign = "+" if pct_diff >= 0 else ""
        sma_rel = f"{sign}{pct_diff:.1f}% {'above' if pct_diff >= 0 else 'below'}"
        price_color = "green" if not result.below_sma200 else "red"
        price_str = f"[{price_color}]${result.qqq_price:.2f}[/{price_color}]  vs SMA200 ${result.sma200:.2f}  ({sma_rel})"
    else:
        price_str = "N/A"
    tbl.add_row("QQQ Price", price_str)

    below_str = "[red]YES[/red]" if result.below_sma200 else "[green]NO[/green]"
    tbl.add_row("Below SMA200", below_str)

    vix_color = "yellow" if result.vix_in_band else "dim"
    tbl.add_row("VIX", f"[{vix_color}]{result.vix:.2f}[/{vix_color}]  (optimal band: 25-40)")

    roc_color = "green" if result.roc_ok else "red"
    roc_sign = "+" if result.roc_20d_pct >= 0 else ""
    tbl.add_row("20-day ROC", f"[{roc_color}]{roc_sign}{result.roc_20d_pct:.1f}%[/{roc_color}]  (threshold: > -8%)")

    vix_gate = "[green]PASS[/green]" if result.vix_in_band else "[red]FAIL[/red]"
    roc_gate = "[green]PASS[/green]" if result.roc_ok else "[red]FAIL[/red]"
    tbl.add_row("VIX Gate", vix_gate)
    tbl.add_row("ROC Gate", roc_gate)

    # ── Recommendation section ───────────────────────────────────────────────
    tbl.add_row("", "")  # separator

    is_active = result.recommendation == CspRecommendation.SELL_CSP
    if is_active:
        status_str = "[bold green]SELL_CSP[/bold green]"
    else:
        status_str = f"[dim]HOLD_SHARES ({result.recommendation.value})[/dim]"
    tbl.add_row("Status", status_str)
    tbl.add_row("Rationale", result.rationale)

    # ── CSP Parameters (only if SELL_CSP) ───────────────────────────────────
    if is_active:
        tbl.add_row("", "")
        tbl.add_row(
            "Strike",
            f"${result.csp_strike:.2f} (10% OTM, 30 DTE)",
        )
        tbl.add_row(
            "Est. Premium",
            f"~${result.estimated_premium_usd:.0f}/contract (Black-Scholes, VIX={result.vix:.1f})",
        )
        tbl.add_row(
            "Alpha Window",
            f"{result.alpha_window_days} days (Technology sector)",
        )
        tbl.add_row(
            "Action",
            "Sell 1 contract (100 shares) when this scan runs pre-market",
        )

    # ── Research Basis ───────────────────────────────────────────────────────
    tbl.add_row("", "")
    tbl.add_row(
        "[dim]Research Basis[/dim]",
        "[dim]Backtest 2010-2024 · +1,140% vs +1,040% B&H · 0.886 Sharpe vs 0.818 · 0% assignment rate (8 active months)[/dim]",
    )
    tbl.add_row(
        "[dim]Filter Logic[/dim]",
        "[dim]Filters: Below SMA200 + VIX 25-40 + 20-day descent < 8% (no fast crash)[/dim]",
    )

    console.print(
        Panel(
            tbl,
            title="QQQ Tactical Overlay — Cash Secured Put Regime Monitor",
            border_style="magenta",
            padding=(1, 2),
        )
    )


def format_overnight_cc_panel(result: "OvernightCCResult") -> None:
    """Render the QQQ Overnight CC Tactical Overlay panel to console."""
    from tradingagents.graph.overnight_cc_overlay import OvernightCCRecommendation

    is_active = result.recommendation == OvernightCCRecommendation.SELL_OVERNIGHT_CC
    border = "green" if is_active else "yellow"

    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    tbl.add_column("Label", style="dim", min_width=22)
    tbl.add_column("Value", min_width=50)

    # QQQ price vs SMA200
    if result.sma200 > 0:
        pct_diff = (result.qqq_price - result.sma200) / result.sma200 * 100
        sign = "+" if pct_diff >= 0 else ""
        color = "green" if result.above_sma200 else "red"
        tbl.add_row(
            "QQQ Price",
            f"[{color}]${result.qqq_price:.2f}[/{color}]  "
            f"open ${result.qqq_open:.2f}  "
            f"day {result.qqq_day_ret_pct:+.2f}%  "
            f"vs SMA200 ${result.sma200:.2f} ({sign}{pct_diff:.1f}%)",
        )

    # SMA3 vs SMA10
    mom_color = "green" if result.sma3_gt_sma10 else "red"
    mom_gate = "✓" if result.sma3_gt_sma10 else "✗"
    tbl.add_row(
        "SMA3 vs SMA10",
        f"[{mom_color}]{mom_gate} SMA3 ${result.sma3:.2f}  SMA10 ${result.sma10:.2f}[/{mom_color}]",
    )

    # VIX intraday
    vix_color = "green" if result.vix_gate_ok else "red"
    vix_gate = "✓" if result.vix_gate_ok else "✗"
    tbl.add_row(
        "VIX Intraday",
        f"[{vix_color}]{vix_gate} open {result.vix_open:.2f} → {result.vix_current:.2f} "
        f"({result.vix_intraday_chg_pct:+.1f}%)[/{vix_color}]",
    )

    # Gate summary
    gates = [
        ("Above SMA200", result.above_sma200),
        ("VIX drop ≥5%", result.vix_gate_ok),
        (f"QQQ up ≥0.5%", result.qqq_return_gate_ok),
        ("SMA3 > SMA10", result.sma3_gt_sma10),
    ]
    gate_str = "  ".join(
        f"[green]✓ {g}[/green]" if ok else f"[red]✗ {g}[/red]"
        for g, ok in gates
    )
    tbl.add_row("Gates", gate_str)

    tbl.add_row("", "")

    # Recommendation
    rec_color = "green" if is_active else "yellow"
    tbl.add_row(
        "Signal",
        f"[{rec_color}][bold]{result.recommendation.value}[/bold][/{rec_color}]",
    )
    tbl.add_row("Rationale", result.rationale)

    # Strike suggestion (only if active)
    if is_active:
        tbl.add_row("", "")
        tbl.add_row(
            "Suggested Strike",
            f"${result.suggested_strike:.2f}  (P90 overnight upside × {result.p90_multiplier})",
        )
        tbl.add_row(
            "Action",
            f"Sell QQQ ${result.suggested_strike:.2f} call before 4:15 PM ET today",
        )

    # Research basis
    tbl.add_row("", "")
    tbl.add_row(
        "[dim]Research Basis[/dim]",
        f"[dim]Backtest 5y · today-like + SMA3>SMA10 · N={result.backtest_n} · "
        "55.6% flat/down overnight · StdDev 0.476% · P90 upside +0.843%[/dim]",
    )
    tbl.add_row(
        "[dim]⚠ Sample Size[/dim]",
        f"[dim]N={result.backtest_n} — directional signal only, not precise calibration[/dim]",
    )

    # ── Historical Regime Stats ───────────────────────────────────────────
    rs = getattr(result, "regime_stats", None)
    if rs is not None:
        gate_labels = [
            ("QQQ>SMA200", result.above_sma200),
            ("VIX>=5%", result.vix_gate_ok),
            ("QQQ>=0.5%", result.qqq_return_gate_ok),
            ("SMA3>SMA10", result.sma3_gt_sma10),
        ]
        profile_str = "  ".join(
            f"[green]{lbl} \u2713[/green]" if ok else f"[red]{lbl} \u2717[/red]"
            for lbl, ok in gate_labels
        )

        tbl.add_row("", "")
        tbl.add_row(
            "[bold]Historical Profile[/bold]",
            "[bold]\u2500\u2500\u2500 Match (1999\u2013present) \u2500\u2500\u2500[/bold]",
        )
        tbl.add_row("Profile", profile_str)
        tbl.add_row(
            "Matching Nights",
            f"N={rs.n} | Mean {rs.mean_overnight_pct:+.3f}% | "
            f"Median {rs.median_overnight_pct:+.3f}% | StdDev {rs.std_dev:.2f}%",
        )
        tbl.add_row(
            "",
            f"{rs.pct_flat_down:.0f}% flat/down overnight | "
            f"P10 {rs.p10:+.2f}% | P90 {rs.p90:+.2f}%",
        )
        if rs.vix_regime_n > 0:
            tbl.add_row(
                "VIX Regime",
                f"VIX {rs.vix_regime_label}: N={rs.vix_regime_n} | "
                f"Mean {rs.vix_regime_mean:+.3f}% | "
                f"{rs.vix_regime_pct_flat_down:.0f}% flat/down",
            )
        # Strike safety — the key metric for CC sellers
        pct_bs = getattr(rs, "pct_below_strike", None)
        if pct_bs is not None:
            if pct_bs >= 90:
                bs_color = "green"
            elif pct_bs >= 80:
                bs_color = "green"
            elif pct_bs >= 70:
                bs_color = "yellow"
            else:
                bs_color = "red"
            tbl.add_row(
                "Theta Capture",
                f"[{bs_color}]{pct_bs:.0f}% of nights call opens OTM \u2014 "
                f"overnight theta collected, still decaying into 4 PM[/{bs_color}]",
            )
        tbl.add_row("CC Edge", rs.cc_edge_vs_signal)
        tbl.add_row(
            "Strike",
            f"${result.suggested_strike:.2f} (P90 upside from current price)",
        )
        if rs.vix_regime_n < 30:
            tbl.add_row(
                "[dim]Caveat[/dim]",
                f"[dim]N={rs.vix_regime_n} for VIX regime slice \u2014 directional, not precise[/dim]",
            )

    console.print(
        Panel(
            tbl,
            title="QQQ Tactical Overlay \u2014 Overnight Covered Call Signal",
            border_style=border,
            padding=(1, 2),
        )
    )


def _render_portfolio_plan_table(plan: Dict[str, Any]) -> None:
    table = Table(title=f"Portfolio Plan ({plan.get('date', 'N/A')})")
    table.add_column("#", justify="right")
    table.add_column("Symbol", style="cyan")
    table.add_column("Intent", style="white")
    table.add_column("Side", justify="center")
    table.add_column("Weight", justify="right")
    table.add_column("Notional($)", justify="right")
    table.add_column("Qty", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Lane", style="yellow")
    table.add_column("Playbook", style="magenta")
    table.add_column("CC", justify="center")

    for idx, order in enumerate(plan.get("orders", []), start=1):
        quantity = float(order.get("target_quantity", 0.0) or 0.0)
        quantity_policy = str(order.get("quantity_policy", "")).upper().strip()
        if quantity_policy == "WHOLE_SHARES" or abs(quantity - round(quantity)) < 1e-9:
            qty_text = f"{int(round(quantity)):,d}"
        else:
            qty_text = f"{quantity:.4f}"
        table.add_row(
            str(idx),
            str(order.get("symbol", "N/A")),
            str(order.get("intent_category", "ALPHA")),
            str(order.get("side", "N/A")),
            f"{100.0 * float(order.get('target_weight', 0.0)):.2f}%",
            f"{float(order.get('target_notional_usd', 0.0)):,.2f}",
            qty_text,
            f"{float(order.get('reference_price', 0.0)):.4f}",
            str(order.get("lane", "N/A")),
            str(order.get("research_playbook", "N/A")),
            "[green]Y[/green]" if order.get("cc_eligible") else "N",
        )

    console.print(table)


def _render_executed_orders_table(result: Dict[str, Any]) -> None:
    table = Table(title=f"Paper Execution ({result.get('date', 'N/A')})")
    table.add_column("#", justify="right")
    table.add_column("Symbol", style="cyan")
    table.add_column("Intent", style="white")
    table.add_column("Side", justify="center")
    table.add_column("Filled Qty", justify="right")
    table.add_column("Fill Price", justify="right")
    table.add_column("Notional($)", justify="right")
    table.add_column("Lane", style="yellow")
    table.add_column("Playbook", style="magenta")
    table.add_column("Status", justify="center")

    for idx, order in enumerate(result.get("orders", []), start=1):
        filled_qty = float(order.get("filled_quantity", order.get("target_quantity", 0.0)) or 0.0)
        if abs(filled_qty - round(filled_qty)) < 1e-9:
            qty_text = f"{int(round(filled_qty)):,d}"
        else:
            qty_text = f"{filled_qty:.4f}"
        table.add_row(
            str(idx),
            str(order.get("symbol", "N/A")),
            str(order.get("intent_category", "ALPHA")),
            str(order.get("side", "N/A")),
            qty_text,
            f"{float(order.get('filled_price', 0.0)):.4f}",
            f"{float(order.get('filled_notional_usd', 0.0)):,.2f}",
            str(order.get("lane", "N/A")),
            str(order.get("research_playbook", "N/A")),
            str(order.get("status", "N/A")),
        )

    console.print(table)


def _render_positions_table(
    positions_payload: Dict[str, Any],
    title: str = "Paper Positions",
) -> None:
    table = Table(title=title)
    table.add_column("Symbol", style="cyan")
    table.add_column("Direction", justify="center")
    table.add_column("Net Qty", justify="right")
    table.add_column("Avg Px", justify="right")
    table.add_column("Mkt Value($)", justify="right")
    table.add_column("Lane", style="yellow")
    table.add_column("Playbook", style="magenta")
    table.add_column("Rating IDs", style="white")

    open_positions = positions_payload.get("open_positions", {})
    if not isinstance(open_positions, dict):
        open_positions = {}
    rows = sorted(open_positions.values(), key=lambda row: str(row.get("symbol", "")))
    for row in rows:
        rating_ids = row.get("rating_ids", [])
        if isinstance(rating_ids, list):
            rid = ",".join(str(value) for value in rating_ids[:2])
            if len(rating_ids) > 2:
                rid = f"{rid},+{len(rating_ids) - 2}"
        else:
            rid = ""
        table.add_row(
            str(row.get("symbol", "N/A")),
            str(row.get("direction", "N/A")),
            f"{float(row.get('net_quantity', 0.0)):.4f}",
            f"{float(row.get('avg_price', 0.0)):.4f}",
            f"{float(row.get('market_value_usd', 0.0)):,.2f}",
            str(row.get("lane", "N/A")),
            str(row.get("research_playbook", "N/A")),
            rid,
        )

    console.print(table)


def _render_execution_reconciliation_table(report: Dict[str, Any]) -> None:
    summary = Table(title=f"Execution Reconciliation ({report.get('date', 'N/A')})")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Outbox Orders", str(report.get("outbox_orders", 0)))
    summary.add_row("Broker Orders Seen", str(report.get("broker_orders_seen", 0)))
    summary.add_row("Matched Orders", str(report.get("matched_orders", 0)))
    summary.add_row("Unmatched Orders", str(report.get("unmatched_orders", 0)))
    summary.add_row("Status Updates", str(report.get("status_updates", 0)))
    summary.add_row("Fills Applied", str(report.get("fills_applied", 0)))
    summary.add_row("Filled Notional($)", f"{float(report.get('filled_notional_usd', 0.0)):,.2f}")
    summary.add_row("Closed Positions", str(report.get("closed_positions", 0)))
    summary.add_row("Outcomes Updated", str(report.get("outcomes_updated", 0)))
    summary.add_row(
        "Positions Touched",
        ", ".join(str(symbol) for symbol in report.get("positions_touched", [])) or "None",
    )
    summary.add_row(
        "Closed Symbols",
        ", ".join(str(symbol) for symbol in report.get("closed_symbols", [])) or "None",
    )
    summary.add_row(
        "Status Counts",
        ", ".join(
            f"{status}:{count}"
            for status, count in sorted(dict(report.get("status_counts", {})).items())
        )
        or "None",
    )
    console.print(summary)

    fills = list(report.get("fills", []))
    if fills:
        table = Table(title="Applied Fills")
        table.add_column("#", justify="right")
        table.add_column("Intent ID", style="cyan")
        table.add_column("Symbol", style="green")
        table.add_column("Side", justify="center")
        table.add_column("Qty", justify="right")
        table.add_column("Price", justify="right")
        table.add_column("Notional($)", justify="right")
        table.add_column("Lane", style="yellow")
        table.add_column("Playbook", style="magenta")

        for idx, fill in enumerate(fills, start=1):
            table.add_row(
                str(idx),
                str(fill.get("order_intent_id", "N/A")),
                str(fill.get("symbol", "N/A")),
                str(fill.get("side", "N/A")),
                f"{float(fill.get('filled_quantity', 0.0)):.4f}",
                f"{float(fill.get('filled_price', 0.0)):.4f}",
                f"{float(fill.get('filled_notional_usd', 0.0)):,.2f}",
                str(fill.get("lane", "N/A")),
                str(fill.get("research_playbook", "N/A")),
            )

        console.print(table)

    closed_trades = list(report.get("closed_trades", []))
    if closed_trades:
        closed_table = Table(title="Closed Positions")
        closed_table.add_column("#", justify="right")
        closed_table.add_column("Symbol", style="green")
        closed_table.add_column("Qty", justify="right")
        closed_table.add_column("Close Px", justify="right")
        closed_table.add_column("PnL($)", justify="right")
        closed_table.add_column("Return %", justify="right")
        closed_table.add_column("Outcome Updates", justify="right")
        closed_table.add_column("Playbook", style="magenta")
        for idx, row in enumerate(closed_trades, start=1):
            closed_table.add_row(
                str(idx),
                str(row.get("symbol", "N/A")),
                f"{float(row.get('net_quantity', 0.0)):.4f}",
                f"{float(row.get('close_price', 0.0)):.4f}",
                f"{float(row.get('pnl_usd', 0.0)):,.2f}",
                f"{float(row.get('return_pct', 0.0)):.2f}",
                str(len(row.get("updated_rating_ids", []))),
                str(row.get("research_playbook", "N/A")),
            )
        console.print(closed_table)


def _build_positions_drift_report(
    broker_snapshot: Dict[str, Any],
    shadow_positions_payload: Dict[str, Any],
    qty_tolerance: float,
    notional_tolerance_usd: float,
) -> Dict[str, Any]:
    broker_rows = broker_snapshot.get("positions", [])
    if not isinstance(broker_rows, list):
        broker_rows = []
    shadow_map = shadow_positions_payload.get("open_positions", {})
    if not isinstance(shadow_map, dict):
        shadow_map = {}

    broker_map: Dict[str, Dict[str, Any]] = {}
    for row in broker_rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        qty = _to_float(row.get("qty"))
        market_value = abs(_to_float(row.get("market_value")))
        current_price = _to_float(row.get("current_price"))
        if current_price <= 0.0 and qty != 0.0 and market_value > 0.0:
            current_price = market_value / abs(qty)
        avg_price = _to_float(row.get("avg_entry_price"))
        broker_map[symbol] = {
            "qty": qty,
            "market_value_usd": market_value,
            "current_price": current_price,
            "avg_price": avg_price,
        }

    symbols = sorted(set(broker_map.keys()) | {str(k).upper().strip() for k in shadow_map.keys() if str(k).strip()})
    rows: List[Dict[str, Any]] = []
    drift_symbols: List[str] = []
    total_notional_drift = 0.0

    for symbol in symbols:
        broker = broker_map.get(symbol, {})
        shadow_raw = shadow_map.get(symbol, {})
        shadow = shadow_raw if isinstance(shadow_raw, dict) else {}

        broker_qty = _to_float(broker.get("qty"))
        shadow_qty = _to_float(shadow.get("net_quantity"))
        qty_drift = broker_qty - shadow_qty

        mark_price = _to_float(shadow.get("last_mark_price"))
        if mark_price <= 0.0:
            mark_price = _to_float(broker.get("current_price"))
        if mark_price <= 0.0:
            mark_price = _to_float(shadow.get("avg_price"))
        if mark_price <= 0.0:
            mark_price = _to_float(broker.get("avg_price"))

        broker_mv = abs(_to_float(broker.get("market_value_usd")))
        shadow_mv = abs(_to_float(shadow.get("market_value_usd")))
        notional_drift = abs(qty_drift) * max(0.0, mark_price)
        if notional_drift <= 0.0:
            notional_drift = abs(broker_mv - shadow_mv)

        status = "MATCH"
        if abs(qty_drift) > float(qty_tolerance) or notional_drift > float(notional_tolerance_usd):
            status = "DRIFT"
            drift_symbols.append(symbol)
        total_notional_drift += notional_drift

        rows.append(
            {
                "symbol": symbol,
                "broker_qty": float(round(broker_qty, 6)),
                "shadow_qty": float(round(shadow_qty, 6)),
                "qty_drift": float(round(qty_drift, 6)),
                "mark_price": float(round(mark_price, 6)),
                "broker_market_value_usd": float(round(broker_mv, 2)),
                "shadow_market_value_usd": float(round(shadow_mv, 2)),
                "notional_drift_usd": float(round(notional_drift, 2)),
                "status": status,
            }
        )

    rows.sort(key=lambda row: (-float(row.get("notional_drift_usd", 0.0)), str(row.get("symbol", ""))))
    return {
        "date": _today_str(),
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "broker": str(broker_snapshot.get("source", "alpaca")),
        "mode": str(broker_snapshot.get("mode", "")),
        "qty_tolerance": float(qty_tolerance),
        "notional_tolerance_usd": float(notional_tolerance_usd),
        "symbols_compared": int(len(rows)),
        "drift_count": int(len(drift_symbols)),
        "drift_symbols": drift_symbols,
        "total_notional_drift_usd": float(round(total_notional_drift, 2)),
        "all_clear": len(drift_symbols) == 0,
        "rows": rows,
    }


def _alpaca_credentials_configured() -> bool:
    key_id = str(
        DEFAULT_CONFIG.get("alpaca_api_key_id")
        or os.getenv("APCA_API_KEY_ID")
        or os.getenv("ALPACA_API_KEY_ID")
        or ""
    ).strip()
    secret = str(
        DEFAULT_CONFIG.get("alpaca_api_secret_key")
        or os.getenv("APCA_API_SECRET_KEY")
        or os.getenv("ALPACA_API_SECRET_KEY")
        or ""
    ).strip()
    return bool(key_id and secret)


def _evaluate_position_parity_gate(
    execution_mode: str,
    positions_path: str,
    broker_positions_snapshot_path: str,
    refresh_snapshot: bool,
    qty_tolerance: float,
    notional_tolerance_usd: float,
) -> Dict[str, Any]:
    """Compare broker vs shadow positions before submission to prevent drifted execution."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    normalized_mode = str(execution_mode or "paper").strip().lower().replace("_", "-")
    payload: Dict[str, Any] = {
        "checked_at": now_iso,
        "execution_mode": normalized_mode,
        "status": "SKIPPED_MODE",
        "all_clear": True,
        "drift_count": 0,
        "symbols_compared": 0,
        "drift_symbols": [],
        "total_notional_drift_usd": 0.0,
        "broker_positions_snapshot_path": str(broker_positions_snapshot_path),
        "positions_path": str(positions_path),
    }
    if not normalized_mode.startswith("alpaca"):
        return payload

    if not _alpaca_credentials_configured():
        payload["status"] = "SKIPPED_NO_CREDENTIALS"
        payload["all_clear"] = True
        return payload

    snapshot_path = Path(str(broker_positions_snapshot_path))
    if bool(refresh_snapshot):
        try:
            fetch_alpaca_positions_snapshot(
                out_path=str(snapshot_path),
                mode=normalized_mode,
            )
        except Exception as exc:
            payload["status"] = "ERROR"
            payload["all_clear"] = False
            payload["error"] = str(exc)
            return payload

    if not snapshot_path.exists():
        payload["status"] = "ERROR"
        payload["all_clear"] = False
        payload["error"] = f"Broker positions snapshot not found: {snapshot_path}"
        return payload

    try:
        broker_snapshot = _read_json(snapshot_path)
        shadow_payload = load_open_positions(positions_path=str(positions_path))
        drift_report = _build_positions_drift_report(
            broker_snapshot=broker_snapshot,
            shadow_positions_payload=shadow_payload,
            qty_tolerance=float(qty_tolerance),
            notional_tolerance_usd=float(notional_tolerance_usd),
        )
        drift_report["broker_positions_snapshot_path"] = str(snapshot_path)
        drift_report["positions_path"] = str(positions_path)
        drift_path = _persist_positions_drift(drift_report)
    except Exception as exc:
        payload["status"] = "ERROR"
        payload["all_clear"] = False
        payload["error"] = str(exc)
        return payload

    payload.update(
        {
            "status": "CLEAR" if bool(drift_report.get("all_clear")) else "DRIFT_DETECTED",
            "all_clear": bool(drift_report.get("all_clear")),
            "drift_count": int(drift_report.get("drift_count", 0)),
            "symbols_compared": int(drift_report.get("symbols_compared", 0)),
            "drift_symbols": list(drift_report.get("drift_symbols", [])),
            "total_notional_drift_usd": float(drift_report.get("total_notional_drift_usd", 0.0)),
            "positions_drift_path": str(drift_path),
        }
    )
    return payload


def _render_positions_drift_table(report: Dict[str, Any]) -> None:
    summary = Table(title=f"Positions Drift ({report.get('date', 'N/A')})")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Broker", str(report.get("broker", "N/A")))
    summary.add_row("Mode", str(report.get("mode", "N/A")))
    summary.add_row("Symbols Compared", str(report.get("symbols_compared", 0)))
    summary.add_row("Drift Count", str(report.get("drift_count", 0)))
    summary.add_row("Total Notional Drift($)", f"{float(report.get('total_notional_drift_usd', 0.0)):,.2f}")
    summary.add_row(
        "Drift Symbols",
        ", ".join(str(symbol) for symbol in report.get("drift_symbols", [])) or "None",
    )
    summary.add_row(
        "Status",
        "ALL_CLEAR" if bool(report.get("all_clear")) else "DRIFT_DETECTED",
    )
    console.print(summary)

    rows = list(report.get("rows", []))
    if not rows:
        return

    table = Table(title="Per-Symbol Drift")
    table.add_column("Symbol", style="cyan")
    table.add_column("Broker Qty", justify="right")
    table.add_column("Shadow Qty", justify="right")
    table.add_column("Qty Drift", justify="right")
    table.add_column("Mark Px", justify="right")
    table.add_column("Broker MV($)", justify="right")
    table.add_column("Shadow MV($)", justify="right")
    table.add_column("Drift($)", justify="right")
    table.add_column("Status", justify="center")
    for row in rows:
        status = str(row.get("status", "N/A"))
        status_color = "green" if status == "MATCH" else "yellow"
        table.add_row(
            str(row.get("symbol", "N/A")),
            f"{float(row.get('broker_qty', 0.0)):.4f}",
            f"{float(row.get('shadow_qty', 0.0)):.4f}",
            f"{float(row.get('qty_drift', 0.0)):.4f}",
            f"{float(row.get('mark_price', 0.0)):.4f}",
            f"{float(row.get('broker_market_value_usd', 0.0)):,.2f}",
            f"{float(row.get('shadow_market_value_usd', 0.0)):,.2f}",
            f"{float(row.get('notional_drift_usd', 0.0)):,.2f}",
            f"[{status_color}]{status}[/{status_color}]",
        )
    console.print(table)


def _render_open_orders_management_table(report: Dict[str, Any]) -> None:
    summary = Table(title=f"Open Orders Management ({report.get('date', 'N/A')})")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Broker", str(report.get("broker", "N/A")))
    summary.add_row("Mode", str(report.get("mode", "N/A")))
    summary.add_row("Apply Changes", "yes" if bool(report.get("apply_changes")) else "no")
    summary.add_row("Broker Open Orders", str(report.get("broker_open_orders", 0)))
    summary.add_row("Pending Outbox Considered", str(report.get("pending_outbox_considered", 0)))
    summary.add_row("Unmatched Pending", str(report.get("unmatched_pending", 0)))
    summary.add_row("Stale Candidates", str(report.get("stale_candidates_count", 0)))
    summary.add_row("Canceled", str(report.get("canceled_count", 0)))
    summary.add_row("Replaced", str(report.get("replaced_count", 0)))
    summary.add_row("Retry Exhausted", str(report.get("retry_exhausted_count", 0)))
    summary.add_row("Errors", str(report.get("errors_count", 0)))
    console.print(summary)

    stale_candidates = list(report.get("stale_candidates", []))
    if stale_candidates:
        stale_table = Table(title="Stale Candidates")
        stale_table.add_column("Intent ID", style="cyan")
        stale_table.add_column("Symbol", style="green")
        stale_table.add_column("Side", justify="center")
        stale_table.add_column("Age Min", justify="right")
        stale_table.add_column("Status", justify="center")
        stale_table.add_column("Broker Order ID", style="white")
        for row in stale_candidates:
            stale_table.add_row(
                str(row.get("order_intent_id", "N/A")),
                str(row.get("symbol", "N/A")),
                str(row.get("side", "N/A")),
                f"{float(row.get('age_minutes', 0.0)):.2f}",
                str(row.get("status", "N/A")),
                str(row.get("broker_order_id", "N/A")),
            )
        console.print(stale_table)

    replaced = list(report.get("replaced", []))
    if replaced:
        replaced_table = Table(title="Replacement Orders")
        replaced_table.add_column("Symbol", style="cyan")
        replaced_table.add_column("Type", justify="center")
        replaced_table.add_column("Qty", justify="right")
        replaced_table.add_column("Apply", justify="center")
        replaced_table.add_column("OK", justify="center")
        replaced_table.add_column("Seq", justify="right")
        for row in replaced:
            replaced_table.add_row(
                str(row.get("symbol", "N/A")),
                str(row.get("order_type", "N/A")),
                f"{float(row.get('target_quantity', 0.0)):.4f}",
                "yes" if bool(row.get("apply")) else "no",
                "yes" if bool(row.get("ok")) else "no",
                str(row.get("replacement_sequence", "N/A")),
            )
        console.print(replaced_table)

    errors = list(report.get("errors", []))
    if errors:
        errors_table = Table(title="Management Errors")
        errors_table.add_column("Symbol", style="cyan")
        errors_table.add_column("Stage", justify="center")
        errors_table.add_column("Error", style="red")
        for row in errors:
            errors_table.add_row(
                str(row.get("symbol", "N/A")),
                str(row.get("stage", "N/A")),
                str(row.get("error", "UNKNOWN")),
            )
        console.print(errors_table)


def _render_positions_sync_table(report: Dict[str, Any]) -> None:
    summary = Table(title=f"Positions Sync ({report.get('date', 'N/A')})")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Broker", str(report.get("broker", "N/A")))
    summary.add_row("Mode", str(report.get("mode", "N/A")))
    summary.add_row("Apply Changes", "yes" if bool(report.get("apply_changes")) else "no")
    summary.add_row("Drop Missing", "yes" if bool(report.get("drop_missing")) else "no")
    summary.add_row("Broker Positions", str(report.get("broker_positions_count", 0)))
    summary.add_row("Shadow Before", str(report.get("shadow_positions_before", 0)))
    summary.add_row("Shadow After", str(report.get("shadow_positions_after", 0)))
    summary.add_row("Added", str(report.get("added_count", 0)))
    summary.add_row("Updated", str(report.get("updated_count", 0)))
    summary.add_row("Removed", str(report.get("removed_count", 0)))
    console.print(summary)

    rows: List[Tuple[str, str]] = []
    rows.extend((str(symbol), "ADDED") for symbol in report.get("added_symbols", []))
    rows.extend((str(symbol), "UPDATED") for symbol in report.get("updated_symbols", []))
    rows.extend((str(symbol), "REMOVED") for symbol in report.get("removed_symbols", []))
    if not rows:
        return

    table = Table(title="Per-Symbol Sync Changes")
    table.add_column("Symbol", style="cyan")
    table.add_column("Change", justify="center")
    for symbol, change in rows:
        color = "green" if change == "ADDED" else "yellow" if change == "UPDATED" else "red"
        table.add_row(symbol, f"[{color}]{change}[/{color}]")
    console.print(table)


def _audit_live_broker_snapshot(
    source: str,
    snapshot: Dict[str, Any],
    out_path: str,
) -> None:
    try:
        RatingAuditLog().log_event(
            "LIVE_BROKER_SNAPSHOT_FETCHED",
            str(snapshot.get("fetched_at") or _today_str()),
            {
                "broker": source,
                "mode": str(snapshot.get("mode")),
                "orders": len(snapshot.get("orders", [])),
                "status": str(snapshot.get("status", "all")),
                "out_path": str(out_path),
            },
        )
    except Exception:
        pass


def _audit_live_reconciliation(
    report: Dict[str, Any],
    snapshot_path: Path,
    reconciliation_path: Path,
) -> None:
    try:
        audit = RatingAuditLog()
        audit.log_event(
            "LIVE_RECONCILIATION_COMPLETED",
            str(report.get("date") or "live-reconcile"),
            {
                "reconciliation_path": str(reconciliation_path),
                "broker_snapshot_path": str(snapshot_path),
                "matched_orders": int(report.get("matched_orders", 0)),
                "unmatched_orders": int(report.get("unmatched_orders", 0)),
                "status_updates": int(report.get("status_updates", 0)),
                "fills_applied": int(report.get("fills_applied", 0)),
                "filled_notional_usd": float(report.get("filled_notional_usd", 0.0)),
                "closed_positions": int(report.get("closed_positions", 0)),
                "outcomes_updated": int(report.get("outcomes_updated", 0)),
            },
        )
        for order_intent_id in report.get("status_updated_order_intent_ids", []):
            audit.log_event(
                "LIVE_ORDER_RECONCILED",
                str(order_intent_id),
                {
                    "order_intent_id": str(order_intent_id),
                    "reconciliation_path": str(reconciliation_path),
                },
            )
        for fill in report.get("fills", []):
            if not isinstance(fill, dict):
                continue
            audit.log_event(
                "LIVE_FILL_APPLIED",
                str(fill.get("order_intent_id") or fill.get("rating_id") or report.get("date")),
                fill,
            )
        for close_event in report.get("closed_trades", []):
            if not isinstance(close_event, dict):
                continue
            audit.log_event(
                "LIVE_POSITION_CLOSED",
                str(close_event.get("close_id") or close_event.get("symbol") or report.get("date")),
                close_event,
            )
    except Exception:
        pass


def _run_execution_sync_cycle(
    broker: str,
    mode: str,
    status: str,
    limit: int,
    snapshot_out_path: str,
    outbox_path: str,
    positions_path: str,
    fills_path: str,
    closed_trades_path: str,
) -> Dict[str, Any]:
    source = str(broker or "").strip().lower()
    if source != "alpaca":
        raise ValueError(f"Unsupported broker: {broker}")

    snapshot = fetch_alpaca_orders_snapshot(
        out_path=str(snapshot_out_path),
        mode=str(mode),
        status=str(status),
        limit=int(limit),
    )
    _audit_live_broker_snapshot(source=source, snapshot=snapshot, out_path=str(snapshot_out_path))

    snapshot_path = Path(snapshot_out_path)
    broker_snapshot = _read_json(snapshot_path)
    report = reconcile_live_execution(
        broker_snapshot=broker_snapshot,
        outbox_path=str(outbox_path),
        positions_path=str(positions_path),
        fills_path=str(fills_path),
        closed_trades_path=str(closed_trades_path),
        track_record=TrackRecord(),
    )
    report["date"] = _today_str()
    report["broker_snapshot_path"] = str(snapshot_path)
    report["broker"] = source
    report["mode"] = str(mode)
    report["snapshot_orders"] = int(len(snapshot.get("orders", [])))
    reconciliation_path = _persist_execution_reconciliation(report)
    report["reconciliation_path"] = str(reconciliation_path)

    position_refresh = refresh_positions_market_snapshot(positions_path=str(positions_path))
    report["position_refresh"] = position_refresh
    _audit_live_reconciliation(
        report=report,
        snapshot_path=snapshot_path,
        reconciliation_path=reconciliation_path,
    )
    try:
        RatingAuditLog().log_event(
            "LIVE_EXECUTION_SYNC_CYCLE",
            str(report.get("reconciled_at") or report.get("date") or "live-sync"),
            {
                "broker": source,
                "mode": str(mode),
                "snapshot_path": str(snapshot_path),
                "reconciliation_path": str(reconciliation_path),
                "snapshot_orders": int(report.get("snapshot_orders", 0)),
                "matched_orders": int(report.get("matched_orders", 0)),
                "status_updates": int(report.get("status_updates", 0)),
                "fills_applied": int(report.get("fills_applied", 0)),
                "closed_positions": int(report.get("closed_positions", 0)),
                "outcomes_updated": int(report.get("outcomes_updated", 0)),
                "positions_refreshed": int(position_refresh.get("refreshed_count", 0)),
            },
        )
    except Exception:
        pass

    return report


def _run_manage_exits_once(
    execution_mode: str,
    orders_path: str,
    positions_path: str,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_hold_days: int,
    trailing_stop_pct: float,
    min_position_notional_usd: float,
    max_exit_orders_per_run: int,
    submit: bool,
    slippage_bps: float,
) -> Dict[str, Any]:
    normalized_mode = str(execution_mode or "paper").strip().lower().replace("_", "-")
    enforce_whole_shares = bool(DEFAULT_CONFIG.get("alpaca_enforce_whole_shares", True))
    use_whole_shares = normalized_mode.startswith("alpaca") and enforce_whole_shares

    exit_plan = build_exit_execution_plan(
        execution_mode=normalized_mode,
        positions_path=str(positions_path),
        outbox_path=str(orders_path),
        stop_loss_pct=float(stop_loss_pct),
        take_profit_pct=float(take_profit_pct),
        max_hold_days=int(max_hold_days),
        trailing_stop_pct=float(trailing_stop_pct),
        min_position_notional_usd=float(min_position_notional_usd),
        max_exit_orders_per_run=int(max_exit_orders_per_run),
        enforce_whole_shares=bool(use_whole_shares),
    )
    date_value = str(exit_plan.get("date") or _today_str())
    report: Dict[str, Any] = {
        "date": date_value,
        "execution_mode": normalized_mode,
        "submitted": False,
        "signals_generated": int(len(exit_plan.get("signals", []))),
        "orders_generated": int(len(exit_plan.get("orders", []))),
        "signals": list(exit_plan.get("signals", [])),
        "orders": list(exit_plan.get("orders", [])),
        "skipped": list(exit_plan.get("skipped", [])),
        "rules": dict(exit_plan.get("rules", {})),
    }

    for signal in report.get("signals", []):
        if not isinstance(signal, dict):
            continue
        try:
            RatingAuditLog().log_event(
                "EXIT_SIGNAL_GENERATED",
                str(signal.get("symbol") or signal.get("exit_signal_id") or date_value),
                signal,
            )
        except Exception:
            pass

    if submit and report["orders_generated"] > 0:
        try:
            execution_result = execute_plan_with_adapter(
                plan=exit_plan,
                execution_mode=normalized_mode,
                orders_path=str(orders_path),
                positions_path=str(positions_path),
                fill_price_slippage_bps=float(slippage_bps),
            )
        except ValueError as exc:
            report["error"] = str(exc)
            report["submitted"] = False
            exit_management_path = _persist_exit_management(report)
            report["exit_management_path"] = str(exit_management_path)
            return report

        report["submitted"] = True
        report["execution_result"] = execution_result
        report["orders_submitted"] = int(execution_result.get("submitted_orders", 0))
        report["orders_executed"] = int(execution_result.get("executed_orders", 0))
        report["failed_orders"] = int(execution_result.get("failed_orders", 0) or 0)
        for row in execution_result.get("orders", []):
            if not isinstance(row, dict):
                continue
            try:
                RatingAuditLog().log_event(
                    "EXIT_ORDER_SUBMITTED",
                    str(row.get("order_intent_id") or row.get("rating_id") or date_value),
                    row,
                )
            except Exception:
                pass
    else:
        report["orders_submitted"] = 0
        report["orders_executed"] = 0
        report["failed_orders"] = 0

    exit_management_path = _persist_exit_management(report)
    report["exit_management_path"] = str(exit_management_path)
    return report


def _parse_iso_datetime(raw: Any) -> Optional[datetime.datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _run_manage_open_orders_once(
    broker: str,
    mode: str,
    outbox_path: str,
    broker_snapshot_path: str,
    refresh_snapshot: bool,
    max_age_minutes: int,
    replace_stale: bool,
    replacement_order_type: str,
    limit_price_offset_bps: float,
    max_retries_per_symbol_per_day: int,
    apply_changes: bool,
) -> Dict[str, Any]:
    source = str(broker or "").strip().lower()
    if source != "alpaca":
        raise ValueError(f"Unsupported broker: {broker}")

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_dt.isoformat()
    today = now_dt.date().isoformat()
    normalized_mode = str(mode or "alpaca-paper").strip().lower().replace("_", "-")
    snapshot_path = Path(str(broker_snapshot_path))

    if bool(refresh_snapshot):
        fetch_alpaca_orders_snapshot(
            out_path=str(snapshot_path),
            mode=normalized_mode,
            status="open",
            limit=500,
        )
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Broker snapshot not found: {snapshot_path}")

    broker_snapshot = _read_json(snapshot_path)
    broker_orders = broker_snapshot.get("orders", [])
    if not isinstance(broker_orders, list):
        broker_orders = []

    broker_by_id: Dict[str, Dict[str, Any]] = {}
    broker_by_client: Dict[str, Dict[str, Any]] = {}
    for row in broker_orders:
        if not isinstance(row, dict):
            continue
        order_id = str(row.get("id") or row.get("order_id") or "").strip()
        client_id = str(row.get("client_order_id") or "").strip()
        if order_id:
            broker_by_id[order_id] = row
        if client_id:
            broker_by_client[client_id] = row

    outbox_file = Path(str(outbox_path))
    if outbox_file.exists():
        outbox_rows = _read_json(outbox_file)
        if not isinstance(outbox_rows, list):
            outbox_rows = []
    else:
        outbox_rows = []

    terminal_statuses = {"FILLED", "CANCELED", "REJECTED", "EXPIRED", "REPLACED"}
    symbol_retries_today: Dict[str, int] = {}
    for row in outbox_rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        retry_source = str(row.get("replacement_for_order_intent_id") or "").strip()
        submitted_day = (_parse_iso_datetime(row.get("submitted_at")) or now_dt).date().isoformat()
        if retry_source and submitted_day == today:
            symbol_retries_today[symbol] = symbol_retries_today.get(symbol, 0) + 1

    stale_candidates: List[Dict[str, Any]] = []
    canceled_rows: List[Dict[str, Any]] = []
    replaced_rows: List[Dict[str, Any]] = []
    retry_exhausted_rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    unmatched_pending = 0
    stale_count = 0

    for row in outbox_rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "SUBMITTED").upper().strip()
        if status in terminal_statuses:
            continue

        broker_order_id = str(row.get("broker_order_id") or "").strip()
        client_order_id = str(row.get("client_order_id") or "").strip()
        broker_row = broker_by_id.get(broker_order_id) or broker_by_client.get(client_order_id)
        if broker_row is None:
            unmatched_pending += 1
            continue

        submitted_at = _parse_iso_datetime(row.get("submitted_at")) or now_dt
        age_minutes = max(0.0, (now_dt - submitted_at).total_seconds() / 60.0)
        if age_minutes < float(max_age_minutes):
            continue
        stale_count += 1

        symbol = str(row.get("symbol") or "").upper().strip()
        side = str(row.get("side") or "").upper().strip()
        target_qty = float(row.get("target_quantity", 0.0) or 0.0)
        stale_candidates.append(
            {
                "order_intent_id": str(row.get("order_intent_id") or ""),
                "broker_order_id": broker_order_id,
                "symbol": symbol,
                "side": side,
                "age_minutes": float(round(age_minutes, 2)),
                "status": status,
            }
        )

        canceled_ok = False
        if apply_changes:
            try:
                cancel_result = cancel_alpaca_order(
                    broker_order_id=broker_order_id,
                    mode=normalized_mode,
                )
                canceled_ok = bool(cancel_result.get("canceled"))
                if canceled_ok:
                    row["status"] = "CANCELED"
                    row["status_updated_at"] = now_iso
                    row["canceled_at"] = now_iso
                    row["cancel_reason"] = "STALE_OPEN_ORDER"
                canceled_rows.append(
                    {
                        "symbol": symbol,
                        "broker_order_id": broker_order_id,
                        "order_intent_id": str(row.get("order_intent_id") or ""),
                        "apply": True,
                        "ok": canceled_ok,
                    }
                )
            except Exception as exc:
                errors.append(
                    {
                        "symbol": symbol,
                        "broker_order_id": broker_order_id,
                        "stage": "cancel",
                        "error": str(exc),
                    }
                )
        else:
            canceled_ok = True
            canceled_rows.append(
                {
                    "symbol": symbol,
                    "broker_order_id": broker_order_id,
                    "order_intent_id": str(row.get("order_intent_id") or ""),
                    "apply": False,
                    "ok": True,
                }
            )

        if not bool(replace_stale):
            continue
        if not canceled_ok:
            continue

        retries_used = int(symbol_retries_today.get(symbol, 0))
        if retries_used >= int(max_retries_per_symbol_per_day):
            retry_exhausted_rows.append(
                {
                    "symbol": symbol,
                    "order_intent_id": str(row.get("order_intent_id") or ""),
                    "retries_used": retries_used,
                    "max_retries": int(max_retries_per_symbol_per_day),
                }
            )
            continue

        if target_qty <= 0.0:
            errors.append(
                {
                    "symbol": symbol,
                    "stage": "replace",
                    "error": "NON_POSITIVE_TARGET_QTY",
                }
            )
            continue

        replacement_type = str(replacement_order_type or "market").lower().strip()
        if replacement_type not in {"market", "limit"}:
            replacement_type = "market"
        tif = str(row.get("time_in_force") or "DAY").lower().strip()
        new_order_intent_id = str(uuid.uuid4())
        client_seed = str(row.get("client_order_id") or symbol or "order").replace(" ", "-")
        replacement_seq = retries_used + 1
        new_client_order_id = f"{client_seed}-r{replacement_seq}"[:48]

        limit_price = None
        if replacement_type == "limit":
            reference_price = float(row.get("reference_price", 0.0) or 0.0)
            if reference_price <= 0.0:
                reference_price = float(_to_float(broker_row.get("limit_price") or broker_row.get("avg_fill_price")))
            if reference_price <= 0.0:
                errors.append(
                    {
                        "symbol": symbol,
                        "stage": "replace",
                        "error": "MISSING_REFERENCE_PRICE_FOR_LIMIT",
                    }
                )
                continue
            offset = abs(float(limit_price_offset_bps)) / 10000.0
            if side == "BUY":
                limit_price = reference_price * (1.0 + offset)
            else:
                limit_price = reference_price * (1.0 - offset)

        replacement_payload = {
            "symbol": symbol,
            "side": side,
            "target_quantity": float(round(target_qty, 6)),
            "order_type": replacement_type.upper(),
            "time_in_force": tif.upper(),
        }
        if limit_price is not None:
            replacement_payload["limit_price"] = float(round(limit_price, 4))

        if apply_changes:
            try:
                response = submit_alpaca_order(
                    symbol=symbol,
                    side=side,
                    quantity=target_qty,
                    mode=normalized_mode,
                    order_type=replacement_type,
                    time_in_force=tif,
                    client_order_id=new_client_order_id,
                    limit_price=limit_price,
                )
                broker_status = str(response.get("status") or "submitted").upper().strip()
                replacement_entry = {
                    "submission_id": str(uuid.uuid4()),
                    "submitted_at": now_iso,
                    "plan_id": row.get("plan_id"),
                    "date": row.get("date") or today,
                    "order_intent_id": new_order_intent_id,
                    "client_order_id": str(response.get("client_order_id") or new_client_order_id),
                    "idempotency_key": new_order_intent_id,
                    "symbol": symbol,
                    "side": side,
                    "order_type": replacement_type.upper(),
                    "time_in_force": tif.upper(),
                    "execution_mode": normalized_mode,
                    "target_quantity": float(round(target_qty, 6)),
                    "target_notional_usd": float(_to_float(row.get("target_notional_usd"))),
                    "reference_price": float(_to_float(row.get("reference_price"))),
                    "queue_id": row.get("queue_id"),
                    "rating_id": row.get("rating_id"),
                    "lane": row.get("lane"),
                    "research_playbook": row.get("research_playbook"),
                    "dominant_signal_family": row.get("dominant_signal_family"),
                    "intent_category": row.get("intent_category"),
                    "exit_rule": row.get("exit_rule"),
                    "exit_reason": row.get("exit_reason"),
                    "status": broker_status,
                    "broker_order_id": str(response.get("id") or ""),
                    "broker_status_raw": str(response.get("status") or ""),
                    "note": "OPEN_ORDER_REPLACEMENT",
                    "replacement_for_order_intent_id": str(row.get("order_intent_id") or ""),
                    "replacement_sequence": int(replacement_seq),
                }
                outbox_rows.append(replacement_entry)
                symbol_retries_today[symbol] = replacement_seq
                replaced_rows.append(
                    {
                        "symbol": symbol,
                        "order_intent_id": replacement_entry["order_intent_id"],
                        "replacement_sequence": replacement_seq,
                        "apply": True,
                        "ok": True,
                        **replacement_payload,
                    }
                )
            except Exception as exc:
                errors.append(
                    {
                        "symbol": symbol,
                        "stage": "replace",
                        "error": str(exc),
                    }
                )
        else:
            replaced_rows.append(
                {
                    "symbol": symbol,
                    "order_intent_id": new_order_intent_id,
                    "replacement_sequence": replacement_seq,
                    "apply": False,
                    "ok": True,
                    **replacement_payload,
                }
            )

    if apply_changes:
        outbox_file.parent.mkdir(parents=True, exist_ok=True)
        outbox_file.write_text(json_lib.dumps(outbox_rows, indent=2))

    return {
        "date": today,
        "managed_at": now_iso,
        "broker": source,
        "mode": normalized_mode,
        "apply_changes": bool(apply_changes),
        "outbox_path": str(outbox_file),
        "broker_snapshot_path": str(snapshot_path),
        "broker_open_orders": int(len(broker_orders)),
        "pending_outbox_considered": int(
            len(
                [
                    row
                    for row in outbox_rows
                    if isinstance(row, dict)
                    and str(row.get("status") or "SUBMITTED").upper().strip() not in terminal_statuses
                ]
            )
        ),
        "unmatched_pending": int(unmatched_pending),
        "stale_candidates_count": int(stale_count),
        "canceled_count": int(len(canceled_rows)),
        "replaced_count": int(len(replaced_rows)),
        "retry_exhausted_count": int(len(retry_exhausted_rows)),
        "errors_count": int(len(errors)),
        "stale_candidates": stale_candidates,
        "canceled": canceled_rows,
        "replaced": replaced_rows,
        "retry_exhausted": retry_exhausted_rows,
        "errors": errors,
    }


def _run_sync_positions_from_broker_once(
    broker: str,
    mode: str,
    broker_positions_snapshot_path: str,
    positions_path: str,
    refresh_snapshot: bool,
    drop_missing: bool,
    apply_changes: bool,
) -> Dict[str, Any]:
    source = str(broker or "").strip().lower()
    if source != "alpaca":
        raise ValueError(f"Unsupported broker: {broker}")

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_dt.isoformat()
    today = now_dt.date().isoformat()
    normalized_mode = str(mode or "alpaca-paper").strip().lower().replace("_", "-")

    snapshot_path = Path(str(broker_positions_snapshot_path))
    if bool(refresh_snapshot):
        fetch_alpaca_positions_snapshot(
            out_path=str(snapshot_path),
            mode=normalized_mode,
        )
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Broker positions snapshot not found: {snapshot_path}")

    snapshot = _read_json(snapshot_path)
    broker_rows = snapshot.get("positions", [])
    if not isinstance(broker_rows, list):
        broker_rows = []

    existing_payload = load_open_positions(positions_path=str(positions_path))
    existing_map = existing_payload.get("open_positions", {})
    if not isinstance(existing_map, dict):
        existing_map = {}

    rebuilt_map: Dict[str, Dict[str, Any]] = {}
    for row in broker_rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        qty = _to_float(row.get("qty"))
        if abs(qty) <= 1e-12:
            continue
        existing = existing_map.get(symbol, {})
        existing = existing if isinstance(existing, dict) else {}
        avg_price = _to_float(row.get("avg_entry_price"))
        mark_price = _to_float(row.get("current_price"))
        market_value = abs(_to_float(row.get("market_value")))
        if market_value <= 0.0 and mark_price > 0.0:
            market_value = abs(qty) * mark_price
        if mark_price <= 0.0 and market_value > 0.0:
            mark_price = market_value / abs(qty)
        if avg_price <= 0.0:
            avg_price = _to_float(existing.get("avg_price"))
        if mark_price <= 0.0:
            mark_price = _to_float(existing.get("last_mark_price"))

        opened_at = str(existing.get("opened_at") or "").strip()
        prev_qty = _to_float(existing.get("net_quantity"))
        if not opened_at or (prev_qty * qty < 0):
            opened_at = now_iso

        if qty > 0:
            prev_high = _to_float(existing.get("high_watermark_price"))
            if prev_high <= 0.0:
                prev_high = mark_price
            high_watermark = max(prev_high, mark_price)
            low_watermark = None
            direction = "LONG"
        else:
            prev_low = _to_float(existing.get("low_watermark_price"))
            if prev_low <= 0.0:
                prev_low = mark_price
            low_watermark = min(prev_low, mark_price)
            high_watermark = None
            direction = "SHORT"

        rebuilt_map[symbol] = {
            "symbol": symbol,
            "net_quantity": float(round(qty, 6)),
            "avg_price": float(round(avg_price, 6)),
            "market_value_usd": float(round(market_value, 2)),
            "last_mark_price": float(round(mark_price, 6)),
            "opened_at": opened_at,
            "high_watermark_price": float(round(high_watermark, 6)) if high_watermark is not None else None,
            "low_watermark_price": float(round(low_watermark, 6)) if low_watermark is not None else None,
            "direction": direction,
            "rating_ids": list(existing.get("rating_ids") or []),
            "lane": existing.get("lane"),
            "research_playbook": existing.get("research_playbook"),
            "updated_at": now_iso,
        }

    if not bool(drop_missing):
        for symbol, row in existing_map.items():
            ticker = str(symbol).upper().strip()
            if ticker in rebuilt_map:
                continue
            if isinstance(row, dict):
                rebuilt_map[ticker] = dict(row)

    existing_symbols = {str(symbol).upper().strip() for symbol in existing_map.keys()}
    rebuilt_symbols = set(rebuilt_map.keys())
    added_symbols = sorted(rebuilt_symbols - existing_symbols)
    removed_symbols = sorted(existing_symbols - rebuilt_symbols) if bool(drop_missing) else []
    updated_symbols: List[str] = []
    for symbol in sorted(existing_symbols & rebuilt_symbols):
        old_row = existing_map.get(symbol, {})
        new_row = rebuilt_map.get(symbol, {})
        if not isinstance(old_row, dict) or not isinstance(new_row, dict):
            continue
        if (
            abs(_to_float(old_row.get("net_quantity")) - _to_float(new_row.get("net_quantity"))) > 1e-9
            or abs(_to_float(old_row.get("avg_price")) - _to_float(new_row.get("avg_price"))) > 1e-9
            or abs(_to_float(old_row.get("market_value_usd")) - _to_float(new_row.get("market_value_usd"))) > 1e-6
        ):
            updated_symbols.append(symbol)

    if apply_changes:
        payload = {
            "updated_at": now_iso,
            "open_positions": rebuilt_map,
            "source": "broker_sync",
            "source_mode": normalized_mode,
            "source_broker": source,
            "source_snapshot_path": str(snapshot_path),
        }
        target = Path(str(positions_path))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json_lib.dumps(payload, indent=2))

    return {
        "date": today,
        "synced_at": now_iso,
        "broker": source,
        "mode": normalized_mode,
        "apply_changes": bool(apply_changes),
        "drop_missing": bool(drop_missing),
        "broker_positions_snapshot_path": str(snapshot_path),
        "positions_path": str(positions_path),
        "broker_positions_count": int(len([row for row in broker_rows if isinstance(row, dict)])),
        "shadow_positions_before": int(len(existing_symbols)),
        "shadow_positions_after": int(len(rebuilt_symbols)),
        "added_count": int(len(added_symbols)),
        "updated_count": int(len(updated_symbols)),
        "removed_count": int(len(removed_symbols)),
        "added_symbols": added_symbols,
        "updated_symbols": updated_symbols,
        "removed_symbols": removed_symbols,
        "synced_symbols": sorted(rebuilt_symbols),
    }


REALIZED_HORIZONS = (5, 20)
SIGNAL_FAMILY_ORDER = [
    "price_momentum",
    "social_momentum",
    "news_catalyst",
    "macro_regime_fit",
    "smart_money",
    "liquidity_tradability",
]


def _extract_recommendation(final_trade_decision: str) -> str:
    text = str(final_trade_decision or "")
    patterns = [
        r"Recommendation:\s*\*\*([^*]+)\*\*",
        r"FINAL TRANSACTION PROPOSAL:\s*\*\*([^*]+)\*\*",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        label = re.sub(r"\s+", " ", match.group(1)).strip().upper()
        return label or "UNKNOWN"
    return "UNKNOWN"


def _fallback_recommendation_from_rating(
    rating: Optional[str],
    score: Optional[float],
) -> str:
    label = str(rating or "").upper()
    if "SELL" in label:
        return "SELL"
    if "BUY" in label:
        return "BUY"
    if "HOLD" in label:
        return "HOLD"
    if isinstance(score, (int, float)):
        value = float(score)
        if value >= 60.0:
            return "BUY"
        if value < 40.0:
            return "SELL"
        return "HOLD"
    return "UNKNOWN"


def _extract_analysis_outcome(symbol: str, analysis_date: str) -> Dict[str, Any]:
    report_path = _analysis_report_path(symbol, analysis_date)
    if not report_path.exists():
        return {
            "analysis_report_path": str(report_path),
            "analysis_report_found": False,
            "rating_id": None,
            "recommendation": "UNKNOWN",
            "recommendation_side": "UNKNOWN",
            "aeternus_score": None,
            "confidence": None,
            "rating": None,
        }

    try:
        payload = _read_json(report_path)
    except Exception:
        return {
            "analysis_report_path": str(report_path),
            "analysis_report_found": False,
            "rating_id": None,
            "recommendation": "UNKNOWN",
            "recommendation_side": "UNKNOWN",
            "aeternus_score": None,
            "confidence": None,
            "rating": None,
        }

    score_block = payload.get("aeternus_score")
    score_data = score_block if isinstance(score_block, dict) else {}
    recommendation = _extract_recommendation(str(payload.get("final_trade_decision", "")))
    score_value = score_data.get("aeternus_score")
    rating_value = score_data.get("rating")
    if recommendation == "UNKNOWN":
        recommendation = _fallback_recommendation_from_rating(
            rating=rating_value,
            score=score_value,
        )

    return {
        "analysis_report_path": str(report_path),
        "analysis_report_found": True,
        "rating_id": score_data.get("rating_id"),
        "recommendation": recommendation,
        "recommendation_side": _recommendation_side(recommendation),
        "aeternus_score": score_value,
        "confidence": score_data.get("confidence"),
        "rating": rating_value,
    }


def _extract_json_object_from_output(text: str) -> Optional[Dict[str, Any]]:
    raw = str(text or "")
    if not raw:
        return None

    # Prefer tolerant raw decoding so leading/trailing logs do not break parsing.
    decoder = json_lib.JSONDecoder()
    for idx, ch in enumerate(raw):
        if ch != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(raw[idx:])
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload

    # Line-based fallback for unusual stdout formatting.
    lines = raw.strip().splitlines()
    for idx, line in enumerate(lines):
        if not line.strip().startswith("{"):
            continue
        candidate = "\n".join(lines[idx:])
        try:
            payload = json_lib.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _quick_outcome_from_score_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    score_value = payload.get("aeternus_score")
    rating_value = payload.get("rating")
    recommendation = _fallback_recommendation_from_rating(
        rating=rating_value,
        score=score_value,
    )
    return {
        "analysis_report_path": None,
        "analysis_report_found": False,
        "rating_id": payload.get("rating_id"),
        "recommendation": recommendation,
        "recommendation_side": _recommendation_side(recommendation),
        "aeternus_score": score_value,
        "confidence": payload.get("confidence"),
        "rating": rating_value,
    }


def _recommendation_side(recommendation: str) -> str:
    label = str(recommendation or "").upper()
    if "SELL" in label:
        return "SHORT"
    if "BUY" in label:
        return "LONG"
    if "HOLD" in label:
        return "NEUTRAL"
    return "UNKNOWN"


def _parse_iso_date(value: str) -> Optional[datetime.date]:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _download_batch_prices(symbols: List[str], anchor_date: datetime.date):
    if not symbols:
        return None
    start_date = (anchor_date - datetime.timedelta(days=7)).isoformat()
    end_date = (datetime.datetime.now(datetime.timezone.utc).date() + datetime.timedelta(days=2)).isoformat()
    try:
        return yf.download(
            symbols,
            start=start_date,
            end=end_date,
            interval="1d",
            auto_adjust=False,
            progress=False,
            group_by="ticker",
        )
    except Exception:
        return None


def _extract_close_series(frame: pd.DataFrame, symbol: str):
    if frame is None or frame.empty:
        return None
    try:
        if isinstance(frame.columns, pd.MultiIndex):
            if (symbol, "Close") in frame.columns:
                return pd.to_numeric(frame[(symbol, "Close")], errors="coerce").dropna()
            if ("Close", symbol) in frame.columns:
                return pd.to_numeric(frame[("Close", symbol)], errors="coerce").dropna()
            if symbol in frame.columns.get_level_values(0):
                sub = frame[symbol]
                if "Close" in sub.columns:
                    return pd.to_numeric(sub["Close"], errors="coerce").dropna()
            if "Close" in frame.columns.get_level_values(0):
                sub = frame.xs("Close", axis=1, level=0)
                if symbol in sub.columns:
                    return pd.to_numeric(sub[symbol], errors="coerce").dropna()
            return None
        if "Close" in frame.columns:
            return pd.to_numeric(frame["Close"], errors="coerce").dropna()
    except Exception:
        return None
    return None


def _first_session_index(series, anchor_date: datetime.date) -> Optional[int]:
    if series is None or series.empty:
        return None
    for idx, ts in enumerate(series.index):
        try:
            session_date = pd.Timestamp(ts).date()
        except Exception:
            continue
        if session_date >= anchor_date:
            return idx
    return None


def _evaluate_realized_horizon(
    series,
    benchmark_series,
    anchor_date: datetime.date,
    horizon_days: int,
    side: str,
) -> Dict[str, Any]:
    base = {
        "status": "NO_DATA",
        "trading_days": int(horizon_days),
        "entry_date": None,
        "entry_price": None,
        "target_date": None,
        "target_price": None,
        "return_pct": None,
        "benchmark_return_pct": None,
        "edge_vs_benchmark_pct": None,
        "recommendation_side": side,
        "strategy_return_pct": None,
        "strategy_edge_vs_benchmark_pct": None,
    }
    if series is None or series.empty:
        return base

    entry_idx = _first_session_index(series, anchor_date)
    if entry_idx is None:
        return base

    entry_date = pd.Timestamp(series.index[entry_idx]).date().isoformat()
    entry_price = float(series.iloc[entry_idx])
    base["entry_date"] = entry_date
    base["entry_price"] = round(entry_price, 6)
    if entry_price == 0.0:
        return base

    target_idx = entry_idx + int(horizon_days)
    if target_idx >= len(series):
        base["status"] = "PENDING"
        return base

    target_date = pd.Timestamp(series.index[target_idx]).date().isoformat()
    target_price = float(series.iloc[target_idx])
    ret = ((target_price - entry_price) / entry_price) * 100.0

    base["status"] = "READY"
    base["target_date"] = target_date
    base["target_price"] = round(target_price, 6)
    base["return_pct"] = round(ret, 4)

    benchmark_ret = None
    if benchmark_series is not None and not benchmark_series.empty:
        bench_entry_idx = _first_session_index(benchmark_series, anchor_date)
        if bench_entry_idx is not None:
            bench_target_idx = bench_entry_idx + int(horizon_days)
            if bench_target_idx < len(benchmark_series):
                bench_entry = float(benchmark_series.iloc[bench_entry_idx])
                bench_target = float(benchmark_series.iloc[bench_target_idx])
                if bench_entry != 0.0:
                    benchmark_ret = ((bench_target - bench_entry) / bench_entry) * 100.0
                    base["benchmark_return_pct"] = round(benchmark_ret, 4)
                    base["edge_vs_benchmark_pct"] = round(ret - benchmark_ret, 4)

    if side == "LONG":
        strategy_ret = ret
    elif side == "SHORT":
        strategy_ret = -ret
    else:
        strategy_ret = None

    if strategy_ret is not None:
        base["strategy_return_pct"] = round(strategy_ret, 4)
        if benchmark_ret is not None:
            base["strategy_edge_vs_benchmark_pct"] = round(strategy_ret - benchmark_ret, 4)

    return base


def _attach_realized_horizons(items: List[Dict[str, Any]], analysis_date: str) -> None:
    run_date = _parse_iso_date(analysis_date)
    if run_date is None:
        for item in items:
            if not _is_success_status(str(item.get("status"))):
                continue
            item["realized_horizons"] = {
                f"{h}d": {
                    "status": "NO_DATA",
                    "trading_days": int(h),
                    "entry_date": None,
                    "entry_price": None,
                    "target_date": None,
                    "target_price": None,
                    "return_pct": None,
                    "benchmark_return_pct": None,
                    "edge_vs_benchmark_pct": None,
                    "recommendation_side": _recommendation_side(str(item.get("recommendation", ""))),
                    "strategy_return_pct": None,
                    "strategy_edge_vs_benchmark_pct": None,
                }
                for h in REALIZED_HORIZONS
            }
        return

    success_items = [item for item in items if _is_success_status(str(item.get("status")))]
    symbols = sorted({str(item.get("symbol", "")).upper().strip() for item in success_items if item.get("symbol")})
    if not symbols:
        return

    price_frame = _download_batch_prices(symbols + ["SPY"], run_date)
    benchmark = _extract_close_series(price_frame, "SPY")
    close_map = {sym: _extract_close_series(price_frame, sym) for sym in symbols}

    for item in success_items:
        symbol = str(item.get("symbol", "")).upper().strip()
        side = _recommendation_side(str(item.get("recommendation", "")))
        series = close_map.get(symbol)
        item["realized_horizons"] = {
            f"{h}d": _evaluate_realized_horizon(
                series=series,
                benchmark_series=benchmark,
                anchor_date=run_date,
                horizon_days=h,
                side=side,
            )
            for h in REALIZED_HORIZONS
        }


def _mean_or_none(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _is_success_status(status: str) -> bool:
    return str(status).upper().startswith("SUCCESS")


def _normalized_subscores(subscores: Any) -> Dict[str, float]:
    if not isinstance(subscores, dict):
        return {}
    normalized: Dict[str, float] = {}
    for key in SIGNAL_FAMILY_ORDER:
        value = subscores.get(key)
        if isinstance(value, (int, float)):
            normalized[key] = float(value)
    return normalized


def _dominant_signal_families(subscores: Any, top_k: int = 3) -> List[str]:
    normalized = _normalized_subscores(subscores)
    if not normalized:
        return []
    ranked = sorted(
        normalized.items(),
        key=lambda kv: (-float(kv[1]), SIGNAL_FAMILY_ORDER.index(kv[0])),
    )
    return [family for family, _ in ranked[: max(1, int(top_k))]]


def _dominant_signal_family(subscores: Any) -> str:
    top = _dominant_signal_families(subscores, top_k=1)
    if not top:
        return "UNKNOWN"
    return top[0]


def _aggregate_realized_horizons(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    for horizon in REALIZED_HORIZONS:
        key = f"{horizon}d"
        rows = [
            (item.get("realized_horizons") or {}).get(key)
            for item in items
            if _is_success_status(str(item.get("status")))
        ]
        rows = [r for r in rows if isinstance(r, dict)]
        ready = [r for r in rows if str(r.get("status")) == "READY"]
        pending_count = sum(1 for r in rows if str(r.get("status")) == "PENDING")
        no_data_count = sum(1 for r in rows if str(r.get("status")) == "NO_DATA")

        returns = [float(r["return_pct"]) for r in ready if isinstance(r.get("return_pct"), (int, float))]
        bench = [
            float(r["benchmark_return_pct"])
            for r in ready
            if isinstance(r.get("benchmark_return_pct"), (int, float))
        ]
        edges = [
            float(r["edge_vs_benchmark_pct"])
            for r in ready
            if isinstance(r.get("edge_vs_benchmark_pct"), (int, float))
        ]
        strategy_returns = [
            float(r["strategy_return_pct"])
            for r in ready
            if isinstance(r.get("strategy_return_pct"), (int, float))
        ]
        strategy_edges = [
            float(r["strategy_edge_vs_benchmark_pct"])
            for r in ready
            if isinstance(r.get("strategy_edge_vs_benchmark_pct"), (int, float))
        ]

        side_counts = {"LONG": 0, "SHORT": 0, "NEUTRAL": 0, "UNKNOWN": 0}
        for row in ready:
            side = str(row.get("recommendation_side", "UNKNOWN")).upper()
            if side not in side_counts:
                side = "UNKNOWN"
            side_counts[side] += 1

        summary[key] = {
            "evaluated_count": len(ready),
            "pending_count": int(pending_count),
            "no_data_count": int(no_data_count),
            "avg_return_pct": _mean_or_none(returns),
            "avg_benchmark_return_pct": _mean_or_none(bench),
            "avg_edge_vs_benchmark_pct": _mean_or_none(edges),
            "edge_win_rate": round(sum(1 for v in edges if v > 0.0) / len(edges), 4) if edges else None,
            "avg_strategy_return_pct": _mean_or_none(strategy_returns),
            "avg_strategy_edge_vs_benchmark_pct": _mean_or_none(strategy_edges),
            "strategy_edge_win_rate": (
                round(sum(1 for v in strategy_edges if v > 0.0) / len(strategy_edges), 4)
                if strategy_edges
                else None
            ),
            "side_counts": side_counts,
        }

    return summary


def _group_batch_outcomes(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    success_items = [item for item in items if _is_success_status(str(item.get("status")))]
    recommendation_counts: Dict[str, int] = {}
    for item in success_items:
        rec = str(item.get("recommendation", "UNKNOWN")).upper()
        recommendation_counts[rec] = recommendation_counts.get(rec, 0) + 1

    score_values = []
    confidence_values = []
    for item in success_items:
        score = item.get("aeternus_score")
        confidence = item.get("confidence")
        if isinstance(score, (int, float)):
            score_values.append(float(score))
        if isinstance(confidence, (int, float)):
            confidence_values.append(float(confidence))

    avg_score = round(sum(score_values) / len(score_values), 4) if score_values else None
    avg_conf = round(sum(confidence_values) / len(confidence_values), 4) if confidence_values else None

    return {
        "count": len(items),
        "success_count": len(success_items),
        "failure_count": sum(1 for item in items if str(item.get("status")).upper() == "FAILED"),
        "skipped_count": sum(1 for item in items if str(item.get("status")) == "SKIPPED"),
        "recommendation_counts": recommendation_counts,
        "avg_aeternus_score": avg_score,
        "avg_confidence": avg_conf,
        "realized_horizons": _aggregate_realized_horizons(success_items),
    }


def _build_batch_attribution(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_lane: Dict[str, Any] = {}
    by_playbook: Dict[str, Any] = {}
    by_signal_family: Dict[str, Any] = {}

    lanes = sorted({str(item.get("lane", "UNKNOWN")).upper() for item in items})
    for lane in lanes:
        lane_items = [item for item in items if str(item.get("lane", "UNKNOWN")).upper() == lane]
        by_lane[lane] = _group_batch_outcomes(lane_items)

    playbooks = sorted({str(item.get("research_playbook", "UNKNOWN")) for item in items})
    for playbook in playbooks:
        pb_items = [item for item in items if str(item.get("research_playbook", "UNKNOWN")) == playbook]
        by_playbook[playbook] = _group_batch_outcomes(pb_items)

    families = sorted({str(item.get("dominant_signal_family", "UNKNOWN")) for item in items})
    family_counts: Dict[str, int] = {}
    for family in families:
        fam_items = [item for item in items if str(item.get("dominant_signal_family", "UNKNOWN")) == family]
        by_signal_family[family] = _group_batch_outcomes(fam_items)
        family_counts[family] = len(fam_items)

    return {
        "overall": _group_batch_outcomes(items),
        "by_lane": by_lane,
        "by_playbook": by_playbook,
        "by_signal_family": by_signal_family,
        "signal_family_counts": family_counts,
    }


def _lane_summary(candidates: List[Dict[str, Any]]) -> Dict[str, int]:
    summary: Dict[str, int] = {"CORE": 0, "MOMENTUM": 0}
    for candidate in candidates:
        lane = str(candidate.get("lane", "CORE")).upper()
        if lane not in summary:
            summary[lane] = 0
        summary[lane] += 1
    return summary


def update_research_team_status(status):
    """Update status for all research team members and trader."""
    research_team = ["Trader"]
    for agent in research_team:
        message_buffer.update_agent_status(agent, status)

def extract_content_string(content):
    """Extract string content from various message formats."""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # Handle Anthropic's list format
        text_parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get('type') == 'text':
                    text_parts.append(item.get('text', ''))
                elif item.get('type') == 'tool_use':
                    text_parts.append(f"[Tool: {item.get('name', 'unknown')}]")
            else:
                text_parts.append(str(item))
        return ' '.join(text_parts)
    else:
        return str(content)



def run_kerberos_cycle():
    """Run one Kerberos %B overlay evaluation cycle and return results."""
    from tradingagents.graph.kerberos_overlay import KerberosOverlayEngine
    engine = KerberosOverlayEngine(
        put_dte=int(DEFAULT_CONFIG.get("kerberos_put_dte", 14)),
        risk_free_rate=float(DEFAULT_CONFIG.get("kerberos_risk_free_rate", 0.04)),
        iv_multiplier=float(DEFAULT_CONFIG.get("kerberos_iv_multiplier", 1.5)),
    )
    signal, decision, order = engine.evaluate()
    return signal, decision, order


def format_kerberos_overlay_panel(
    signal: dict,
    decision: dict,
    state: Optional[dict] = None,
) -> None:
    """Render the Kerberos %B Vol Overlay panel to console."""
    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    tbl.add_column("Label", style="dim", min_width=22)
    tbl.add_column("Value", min_width=50)

    vxx_spot = float(signal.get("vxx_close", 0.0))
    vix_close = float(signal.get("vix_close", 0.0))
    pct_b_2sd = float(signal.get("pct_b_2sd", 0.0))
    pct_b_1sd = float(signal.get("pct_b_1sd", 0.0))

    tbl.add_row("VXX Spot", f"${vxx_spot:.2f}")
    tbl.add_row("VIX", f"{vix_close:.2f}")

    b2_color = "red" if pct_b_2sd > 1.0 else "green"
    tbl.add_row("%B(20,2)", f"[{b2_color}]{pct_b_2sd:.4f}[/{b2_color}]  (entry > 1.0)")

    b1_color = "green" if pct_b_1sd < 1.0 else "yellow"
    tbl.add_row("%B(20,1)", f"[{b1_color}]{pct_b_1sd:.4f}[/{b1_color}]  (exit < 1.0)")

    # Signal direction
    if signal.get("entry_triggered"):
        sig_str = "[bold red]ENTRY[/bold red] — %B(20,2) crossed above 1"
    elif signal.get("exit_triggered"):
        sig_str = "[bold green]EXIT[/bold green] — %B(20,1) crossed below 1"
    else:
        sig_str = "[dim]FLAT — no crossover[/dim]"
    tbl.add_row("Signal", sig_str)

    tbl.add_row("", "")

    # Decision
    action = str(decision.get("action", "NO_SIGNAL"))
    status = str(decision.get("status", "NO_SIGNAL"))
    if status == "EXECUTED":
        action_color = "green" if action == "CLOSE_PUT" else "red"
        status_str = f"[bold {action_color}]{action}[/bold {action_color}]"
    else:
        status_str = f"[dim]{action} ({status})[/dim]"
    tbl.add_row("Decision", status_str)
    tbl.add_row("Reason", str(decision.get("reason", "")))

    # Put parameters (on OPEN_PUT)
    if action == "OPEN_PUT" and status == "EXECUTED":
        tbl.add_row("", "")
        tbl.add_row("Strike", f"${decision.get('put_strike', 0.0):.0f} (ATM)")
        tbl.add_row("Premium", f"${decision.get('put_premium', 0.0):.2f}/share")
        tbl.add_row("DTE", f"{decision.get('put_dte', 0)} days")
        tbl.add_row("IV", f"{decision.get('put_iv', 0.0):.1%}")

    # Position state
    if state and state.get("position_open"):
        tbl.add_row("", "")
        entry_date = state.get("entry_date", "N/A")
        entry_strike = float(state.get("entry_put_strike", 0.0))
        entry_premium = float(state.get("entry_put_premium", 0.0))
        expiry = state.get("entry_expiry_date", "N/A")
        tbl.add_row("Position", "[bold yellow]OPEN[/bold yellow]")
        tbl.add_row("Entry Date", str(entry_date))
        tbl.add_row("Entry Strike", f"${entry_strike:.0f}")
        tbl.add_row("Entry Premium", f"${entry_premium:.2f}")
        tbl.add_row("Expiry", str(expiry))

    # Research basis
    tbl.add_row("", "")
    tbl.add_row(
        "[dim]Backtest[/dim]",
        "[dim]78% WR | PF 11.41 | avg +137%/trade (VXX ATM puts, 14-day DTE)[/dim]",
    )

    border = "red" if signal.get("entry_triggered") else "cyan"
    console.print(
        Panel(
            tbl,
            title="Kerberos %B Vol Overlay — VXX Put Signal",
            border_style=border,
            padding=(1, 2),
        )
    )


def _render_hypothesis_stage_summary(summary: Dict[str, Any]) -> None:
    stages = list((summary or {}).get("stages") or [])
    if not stages:
        return

    def _fmt_pct(value: Any) -> str:
        if value is None:
            return "—"
        pct = float(value) * 100.0
        color = "green" if pct > 0 else ("red" if pct < 0 else "yellow")
        return f"[{color}]{pct:+.2f}%[/{color}]"

    def _fmt_ratio(value: Any) -> str:
        if value is None:
            return "—"
        pct = float(value) * 100.0
        color = "green" if pct >= 50.0 else ("red" if pct < 25.0 else "yellow")
        return f"[{color}]{pct:.1f}%[/{color}]"

    def _fmt_cost(value: Any) -> str:
        if value is None:
            return "—"
        cost = float(value) * 100.0
        color = "red" if cost > 0 else ("green" if cost < 0 else "yellow")
        return f"[{color}]{cost:+.2f}%[/{color}]"

    lane = str((summary or {}).get("lane", "shared")).strip() or "shared"
    table = Table(title=f"Hypothesis Ledger Summary ({lane})")
    table.add_column("Stage", style="cyan")
    table.add_column("Keep", justify="right")
    table.add_column("Drop", justify="right")
    table.add_column("5d Edge", justify="right")
    table.add_column("20d Edge", justify="right")
    table.add_column("3m Edge", justify="right")
    table.add_column("Recall", justify="right")
    table.add_column("FN Cost", justify="right")

    for stage in stages:
        table.add_row(
            str(stage.get("stage_id", "")),
            str(int(stage.get("kept_count", 0) or 0)),
            str(int(stage.get("dropped_count", 0) or 0)),
            _fmt_pct(stage.get("edge_5d")),
            _fmt_pct(stage.get("edge_20d")),
            _fmt_pct(stage.get("edge_3m")),
            _fmt_ratio(stage.get("future_winner_recall")),
            _fmt_cost(stage.get("false_negative_cost")),
        )

    console.print(table)
    stage_ids = [str(stage.get("stage_id", "")).strip() for stage in stages if str(stage.get("stage_id", "")).strip()]
    if stage_ids:
        console.print(f"[dim]Stage IDs: {', '.join(stage_ids)}[/dim]")


def _render_stage_diagnosis(report: Dict[str, Any]) -> None:
    stages = list((report or {}).get("stages") or [])
    worst_cycles = list((report or {}).get("worst_cycles") or [])
    diagnosis = str((report or {}).get("diagnosis", "")).strip()
    cycles_considered = int((report or {}).get("cycles_considered", 0) or 0)
    lane = str((report or {}).get("lane", "shared")).strip() or "shared"

    console.print(
        f"[bold green]Stage Diagnosis[/bold green] | lane={lane} | cycles={cycles_considered}"
    )

    def _fmt_pct(value: Any) -> str:
        if value is None:
            return "—"
        pct = float(value) * 100.0
        color = "green" if pct > 0 else ("red" if pct < 0 else "yellow")
        return f"[{color}]{pct:+.2f}%[/{color}]"

    def _fmt_ratio(value: Any) -> str:
        if value is None:
            return "—"
        pct = float(value) * 100.0
        color = "green" if pct >= 70.0 else ("red" if pct < 50.0 else "yellow")
        return f"[{color}]{pct:.1f}%[/{color}]"

    if stages:
        table = Table(title="Priority Ranking")
        table.add_column("Stage", style="cyan", no_wrap=True)
        table.add_column("Cycles", justify="right")
        table.add_column("Recall", justify="right")
        table.add_column("5d", justify="right")
        table.add_column("20d", justify="right")
        table.add_column("3m", justify="right")
        table.add_column("FN Cost", justify="right")
        table.add_column("Priority", justify="right")
        for stage in stages:
            table.add_row(
                str(stage.get("stage_id", "")),
                str(int(stage.get("cycles_seen", 0) or 0)),
                _fmt_ratio(stage.get("avg_recall")),
                _fmt_pct(stage.get("avg_edge_5d")),
                _fmt_pct(stage.get("avg_edge_20d")),
                _fmt_pct(stage.get("avg_edge_3m")),
                _fmt_pct(stage.get("total_false_negative_cost")),
                str(round(float(stage.get("priority_score", 0.0) or 0.0), 2)),
            )
        console.print(table)

    if worst_cycles:
        miss_table = Table(title="Worst Recent Misses")
        miss_table.add_column("Date", style="cyan")
        miss_table.add_column("Stage", style="yellow", no_wrap=True)
        miss_table.add_column("Recall", justify="right")
        miss_table.add_column("5d", justify="right")
        miss_table.add_column("20d", justify="right")
        miss_table.add_column("3m", justify="right")
        miss_table.add_column("FN Cost", justify="right")
        for cycle in worst_cycles:
            miss_table.add_row(
                str(cycle.get("source_date", "")),
                str(cycle.get("stage_id", "")),
                _fmt_ratio(cycle.get("future_winner_recall")),
                _fmt_pct(cycle.get("edge_5d")),
                _fmt_pct(cycle.get("edge_20d")),
                _fmt_pct(cycle.get("edge_3m")),
                _fmt_pct(cycle.get("false_negative_cost")),
            )
        console.print(miss_table)

    if diagnosis:
        console.print(f"[bold]Current Diagnosis:[/bold] {diagnosis}")


def _render_discovery_delta_summary(report: Dict[str, Any]) -> None:
    payload = dict(report or {})
    top_symbols = list(payload.get("top_delta_symbols") or [])
    cohorts = dict(payload.get("cohorts") or {})
    if not top_symbols and not cohorts:
        return

    console.print("[bold green]Discovery Delta[/bold green]")

    cohort_table = Table(title="Delta Cohorts")
    cohort_table.add_column("Cohort", style="cyan")
    cohort_table.add_column("Count", justify="right")
    cohort_table.add_column("Symbols", style="white")
    for cohort_name in ("scout_only", "technical_only", "multi_channel"):
        symbols = [str(symbol) for symbol in list(cohorts.get(cohort_name, []) or [])]
        cohort_table.add_row(
            cohort_name,
            str(len(symbols)),
            ", ".join(symbols[:5]) if symbols else "—",
        )
    console.print(cohort_table)

    if top_symbols:
        table = Table(title="Top Delta Symbols")
        table.add_column("Symbol", style="cyan", no_wrap=True)
        table.add_column("Delta Score", justify="right")
        table.add_column("Channels", justify="right")
        table.add_column("Sources", style="white")
        for row in top_symbols[:10]:
            table.add_row(
                str(row.get("symbol", "")),
                str(round(float(row.get("delta_score", 0.0) or 0.0), 2)),
                str(int(row.get("independent_channel_count", 0) or 0)),
                ", ".join([str(source) for source in list(row.get("sources_fired", []) or [])]) or "—",
            )
        console.print(table)


def _render_universe_filter_summary(report: Dict[str, Any]) -> None:
    payload = dict(report or {})
    tier_counts = dict(payload.get("tier_counts") or {})
    source_counts = dict(payload.get("source_counts") or {})
    overlap_counts = dict(payload.get("overlap_counts") or {})
    health_checks = dict(payload.get("health_checks") or {})
    if not tier_counts and not source_counts and not overlap_counts:
        return

    console.print("[bold green]First Universe Filter[/bold green]")

    if health_checks:
        ready = bool(payload.get("overall_ready"))
        status_label = "[green]READY[/green]" if ready else "[yellow]CHECK[/yellow]"
        console.print(f"  Status: {status_label} | universe={int(payload.get('universe_size', 0) or 0)}")

        gate_table = Table(title="Universe Filter Health")
        gate_table.add_column("Check", style="cyan")
        gate_table.add_column("Pass", justify="center")
        gate_table.add_column("Observed", style="white")
        gate_table.add_column("Required", style="magenta")
        for key in (
            "universe_nonzero",
            "tier_diversity_ok",
            "technical_recall_present",
            "manual_xfeed_present",
            "scout_activity_present",
        ):
            row = dict(health_checks.get(key) or {})
            gate_table.add_row(
                key,
                "yes" if bool(row.get("pass")) else "no",
                str(row.get("observed", "—")),
                str(row.get("required", "—")),
            )
        console.print(gate_table)

    if tier_counts:
        tier_table = Table(title="Universe Tier Counts")
        tier_table.add_column("Tier", style="cyan")
        tier_table.add_column("Count", justify="right")
        for tier_name in (
            "T1_ANCHOR",
            "T2_NEIGHBOR",
            "T3_SCOUT",
            "T3B_FVG_RECALL",
            "T3C_FMA_RECALL",
            "T4_DARK",
            "T5_RESCAN",
            "T6_PORTFOLIO",
            "MANUAL",
        ):
            tier_table.add_row(tier_name, str(int(tier_counts.get(tier_name, 0) or 0)))
        console.print(tier_table)

    if source_counts:
        source_table = Table(title="Universe Filter Sources")
        source_table.add_column("Source", style="cyan")
        source_table.add_column("Count", justify="right")
        for source_name in (
            "manual_symbols",
            "x_feed_merged_symbols",
            "breakout_alerts",
            "iv_force_queue",
            "insider_buy_clusters",
            "insider_sell_clusters",
            "scout_signal_symbols",
            "fvg_recall_selected",
            "fma_recall_selected",
        ):
            source_table.add_row(source_name, str(int(source_counts.get(source_name, 0) or 0)))
        console.print(source_table)

    if overlap_counts:
        overlap_table = Table(title="Universe Filter Overlaps")
        overlap_table.add_column("Overlap", style="cyan")
        overlap_table.add_column("Count", justify="right")
        for overlap_name in (
            "fvg_fma_overlap",
            "manual_technical_overlap",
            "scout_technical_overlap",
        ):
            overlap_table.add_row(overlap_name, str(int(overlap_counts.get(overlap_name, 0) or 0)))
        console.print(overlap_table)


def _render_discovery_delta_cohort_scorecards(report: Dict[str, Any]) -> None:
    payload = dict(report or {})
    cohorts = dict(payload.get("cohorts") or {})
    baseline = dict(payload.get("step1_baseline") or {})
    comparisons = dict(payload.get("comparisons") or {})
    if not cohorts:
        return

    def _fmt_pct(value: Any) -> str:
        if value is None:
            return "—"
        pct = float(value) * 100.0
        color = "green" if pct > 0 else ("red" if pct < 0 else "yellow")
        return f"[{color}]{pct:+.2f}%[/{color}]"

    console.print("[bold green]Discovery Delta Cohort Scorecards[/bold green]")

    metric_table = Table(title="Delta Cohort Performance")
    metric_table.add_column("Cohort", style="cyan")
    metric_table.add_column("Count", justify="right")
    metric_table.add_column("5d", justify="right")
    metric_table.add_column("20d", justify="right")
    metric_table.add_column("3m", justify="right")

    for cohort_name in ("scout_only", "technical_only", "multi_channel"):
        row = dict(cohorts.get(cohort_name) or {})
        metric_table.add_row(
            cohort_name,
            str(int(row.get("count", 0) or 0)),
            _fmt_pct(row.get("mean_return_5d")),
            _fmt_pct(row.get("mean_return_20d")),
            _fmt_pct(row.get("mean_return_3m")),
        )

    metric_table.add_row(
        "step1_baseline",
        str(int(baseline.get("count", 0) or 0)),
        _fmt_pct(baseline.get("mean_return_5d")),
        _fmt_pct(baseline.get("mean_return_20d")),
        _fmt_pct(baseline.get("mean_return_3m")),
    )
    console.print(metric_table)

    comparison_table = Table(title="Delta Cohort Deltas")
    comparison_table.add_column("Cohort", style="cyan")
    comparison_table.add_column("Vs Step1 5d", justify="right")
    comparison_table.add_column("Vs Step1 20d", justify="right")
    comparison_table.add_column("Vs Step1 3m", justify="right")
    comparison_table.add_column("Vs Peers 5d", justify="right")
    comparison_table.add_column("Vs Peers 20d", justify="right")
    comparison_table.add_column("Vs Peers 3m", justify="right")

    vs_baseline = dict(comparisons.get("vs_step1_baseline") or {})
    vs_peers = dict(comparisons.get("vs_other_cohorts") or {})
    for cohort_name in ("scout_only", "technical_only", "multi_channel"):
        baseline_row = dict(vs_baseline.get(cohort_name) or {})
        peer_row = dict(vs_peers.get(cohort_name) or {})
        comparison_table.add_row(
            cohort_name,
            _fmt_pct(baseline_row.get("mean_return_5d_delta")),
            _fmt_pct(baseline_row.get("mean_return_20d_delta")),
            _fmt_pct(baseline_row.get("mean_return_3m_delta")),
            _fmt_pct(peer_row.get("mean_return_5d_delta")),
            _fmt_pct(peer_row.get("mean_return_20d_delta")),
            _fmt_pct(peer_row.get("mean_return_3m_delta")),
        )
    console.print(comparison_table)


def _render_fundamental_shadow_summary(report: Dict[str, Any]) -> None:
    payload = dict(report or {})
    coverage = dict(payload.get("coverage_summary") or {})
    top_signals = list(payload.get("top_signals") or [])
    strategy_name = str(payload.get("strategy_name", "") or "").strip()
    if not strategy_name and not coverage and not top_signals:
        return

    console.print("[bold green]Fundamental Shadow[/bold green]")
    if strategy_name:
        console.print(f"[cyan]Strategy:[/cyan] {strategy_name}")
    console.print(
        "[cyan]Coverage:[/cyan] "
        f"signals={int(coverage.get('signal_count', 0) or 0)} "
        f"ok={int(coverage.get('ok_count', 0) or 0)} "
        f"handoff_overlap={int(coverage.get('handoff_overlap_count', 0) or 0)}"
    )
    if top_signals:
        labels = ", ".join(
            f"{row.get('symbol', 'N/A')} ({float(row.get('raw_score', 0.0) or 0.0):.1f})"
            for row in top_signals[:5]
        )
        console.print(f"[cyan]Top shadow names:[/cyan] {labels}")

# Export all names (including private helpers) for submodule use
__all__ = [k for k in vars().keys() if not k.startswith('__')]
