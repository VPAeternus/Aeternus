"""CLI command: earnings-options-prompt — generate Grok prompt and ingest cached results."""
from cli.common import *  # noqa: F401,F403

import sys as _sys
from typing import Any, Dict, List


_SENTIMENT_CHOICES = {"VERY_BULLISH", "BULLISH", "NEUTRAL", "BEARISH", "VERY_BEARISH"}
_VELOCITY_CHOICES = {"ACCELERATING", "STEADY", "FADING"}

_PROMPT_TEMPLATE = """\
You are an earnings-event and unusual-options analyst scanning X (Twitter) and the public web right now.

DATE: __DATE__

TASK: Find US stock tickers with high-quality public earnings/options setups in the next 7-14 calendar days.

WHAT COUNTS:
- Stocks with an earnings date inside the next 7-14 days that are drawing unusual public trader attention
- Stocks with specific unusual options flow from real flow accounts
- Stocks where both earnings attention and options flow reinforce each other

PRIORITY SOURCES:
- X accounts like @unusual_whales, @PellegriniFlow, @optionflow, @FlowAlgo, @caborotate, @DarkPoolData, @OptionsHawk, @ConvexValue, and similar real flow trackers
- Public earnings-calendar discussion from credible market accounts
- News or catalysts directly tied to the earnings event

DO NOT INCLUDE:
- Generic mega-cap chatter with no earnings or options-event setup
- Indexes or ETFs
- Price action commentary without a concrete event or flow detail
- Fabricated accounts, fabricated flow, or unsupported claims

LOW DATA RULE:
- If there are fewer than 10 real setups, return only what you find. Do not pad the list.

Return JSON only — no prose before or after:

{"trending":[{"ticker":"MU","buzz_rank":1,"sentiment":"BULLISH","velocity":"ACCELERATING","catalyst":"Micron earnings on 2026-03-18 with multiple public options-flow accounts highlighting bullish call activity","sector":"Technology","earnings_date":"2026-03-18","setup_type":"earnings_options","flow_summary":"$3.2M April call sweep from public flow accounts","accounts_flagged":3}]}

Field rules:
- trending: list of zero or more setup entries
- ticker: uppercase US stock ticker
- buzz_rank: integer, 1 = strongest setup
- sentiment: VERY_BULLISH | BULLISH | NEUTRAL | BEARISH | VERY_BEARISH
- velocity: ACCELERATING | STEADY | FADING
- catalyst: one sentence with the concrete setup
- sector: GICS sector label
- earnings_date: optional YYYY-MM-DD
- setup_type: optional string, usually earnings_options
- flow_summary: optional short sentence on the public flow setup
- accounts_flagged: optional integer count of distinct public flow accounts
"""


@app.command("earnings-options-prompt")
def earnings_options_prompt(
    generate: bool = typer.Option(False, "--generate", help="Print the Grok prompt for manual earnings/options scouting"),
    ingest: bool = typer.Option(False, "--ingest", help="Read JSON from stdin (or --file) and save to cache"),
    file: str = typer.Option("", "--file", help="Path to JSON file (alternative to stdin for --ingest)"),
    date: str = typer.Option("", "--date", help="Date override (YYYY-MM-DD, defaults to today)"),
):
    """Generate Grok prompt for manual earnings/options scout and ingest cached results."""
    import datetime as _dt

    as_of_date = date.strip() or _dt.date.today().strftime("%Y-%m-%d")

    if not generate and not ingest:
        console.print("[red]Specify --generate or --ingest[/red]")
        raise typer.Exit(1)

    if generate:
        _do_generate(as_of_date)
    else:
        _do_ingest(as_of_date, file.strip())


def _do_generate(as_of_date: str):
    prompt = _PROMPT_TEMPLATE.replace("__DATE__", as_of_date)
    console.print(f"[bold]Grok earnings/options prompt for {as_of_date}[/bold]\n")
    console.print(prompt)
    console.print(f"\n[dim]Copy the above, paste into Grok deep research, then run:[/dim]")
    console.print(f"[dim]  aeternus earnings-options-prompt --ingest --date {as_of_date}[/dim]")


def _do_ingest(as_of_date: str, file_path: str):
    from tradingagents.dealflow.sources.social_news import _extract_json_payload
    from tradingagents.dealflow.sources.earnings_options_scout import save_earnings_options_scout

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

    parsed = _extract_json_payload(raw)
    if not isinstance(parsed, dict):
        console.print("[red]Invalid JSON — could not parse a JSON object[/red]")
        raise typer.Exit(1)

    try:
        result = _validate_payload(parsed)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    path = save_earnings_options_scout(as_of_date, result)
    console.print(f"[green]Saved {len(result['trending'])} earnings/options setups to {path}[/green]")


def _validate_payload(parsed: Dict[str, Any]) -> Dict[str, Any]:
    trending = parsed.get("trending")
    if not isinstance(trending, list):
        raise ValueError("JSON must contain a 'trending' list")

    normalized: List[Dict[str, Any]] = []
    for idx, entry in enumerate(trending, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Entry {idx} must be an object")
        normalized.append(_normalize_entry(idx, entry))

    normalized.sort(key=lambda row: (int(row["buzz_rank"]), row["ticker"]))
    return {"trending": normalized}


def _normalize_entry(idx: int, entry: Dict[str, Any]) -> Dict[str, Any]:
    for field_name in ("ticker", "buzz_rank", "sentiment", "velocity", "catalyst", "sector"):
        if field_name not in entry:
            raise ValueError(f"Entry {idx} missing '{field_name}'")

    ticker = str(entry.get("ticker", "") or "").upper().strip()
    if not ticker:
        raise ValueError(f"Entry {idx} has empty ticker")

    try:
        buzz_rank = int(entry.get("buzz_rank"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Entry {idx} has invalid buzz_rank") from exc

    sentiment = str(entry.get("sentiment", "") or "").upper().strip()
    if sentiment not in _SENTIMENT_CHOICES:
        raise ValueError(f"Entry {idx} has invalid sentiment")

    velocity = str(entry.get("velocity", "") or "").upper().strip()
    if velocity not in _VELOCITY_CHOICES:
        raise ValueError(f"Entry {idx} has invalid velocity")

    catalyst = str(entry.get("catalyst", "") or "").strip()
    sector = str(entry.get("sector", "") or "").strip()
    if not catalyst:
        raise ValueError(f"Entry {idx} has empty catalyst")
    if not sector:
        raise ValueError(f"Entry {idx} has empty sector")

    earnings_date = str(entry.get("earnings_date", "") or "").strip() or None
    flow_summary = str(entry.get("flow_summary", "") or "").strip() or None
    setup_type = str(entry.get("setup_type", "earnings_options") or "earnings_options").strip()
    try:
        accounts_flagged = int(entry.get("accounts_flagged", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Entry {idx} has invalid accounts_flagged") from exc

    return {
        "ticker": ticker,
        "buzz_rank": buzz_rank,
        "sentiment": sentiment,
        "velocity": velocity,
        "catalyst": catalyst,
        "sector": sector,
        "earnings_date": earnings_date,
        "setup_type": setup_type,
        "flow_summary": flow_summary,
        "accounts_flagged": accounts_flagged,
    }
