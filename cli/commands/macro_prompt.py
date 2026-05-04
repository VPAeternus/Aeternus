"""CLI command: macro-prompt — generate Grok prompt for macro regime data and ingest cached results."""
from cli.common import *  # noqa: F401,F403

import json as _json
import sys as _sys
from typing import Any, Dict, List

# 11 GICS sectors expected in the response.
_GICS_SECTORS = [
    "Technology", "Healthcare", "Financials", "Energy", "Industrials",
    "Consumer Discretionary", "Consumer Staples", "Materials",
    "Communication Services", "Real Estate", "Utilities",
]

_MACRO_DIMENSIONS = [
    "fed_funds_and_guidance",
    "inflation_trajectory",
    "yield_curve_shape",
    "usd_strength",
    "credit_conditions",
    "commodity_cycle",
    "labor_market",
    "fiscal_regulatory",
]

_REGIME_CHOICES = {"early_cycle", "mid_cycle", "late_cycle", "recession", "recovery"}

_MACRO_PROMPT_TEMPLATE = """\
You are a macro strategist at a multi-asset investment firm. Your job is to assess the current US macro regime and score how favorable conditions are for each GICS sector.

DATE: __DATE__

TASK: Using real-time data, evaluate the macro environment across 8 dimensions, then score each of the 11 GICS sectors on macro_regime_fit (0-100).

STEP 1 — Assess these 8 macro dimensions (cite current values where possible):
1. Fed funds rate & forward guidance — where are rates, and where is the Fed signaling next?
2. Inflation trajectory — CPI/PCE trend: accelerating, stable, or decelerating?
3. Yield curve shape — 2s10s spread: inverted, flat, or steepening?
4. USD strength — DXY trend over last 30 days: strengthening, stable, or weakening?
5. Credit conditions — IG/HY spreads: tightening, stable, or widening?
6. Commodity cycle — oil, copper, gold trends: inflationary or deflationary signal?
7. Labor market — payrolls, claims, wage growth: tight, normalizing, or softening?
8. Fiscal/regulatory — any sector-specific policy tailwinds or headwinds (tariffs, subsidies, regulation)?

STEP 2 — Classify the overall regime as exactly one of: early_cycle, mid_cycle, late_cycle, recession, recovery.

STEP 3 — Score each sector. Use these anchor points:
- 85-100: Macro is a strong tailwind. Multiple dimensions favor this sector.
- 65-84: Mild tailwind. More positive factors than negative.
- 45-64: Neutral. Macro is not a meaningful factor either way.
- 25-44: Mild headwind. Rate sensitivity, USD exposure, or cycle position hurts.
- 0-24: Macro is hostile. Multiple dimensions work against this sector.

Sector-specific scoring guidance:
- Technology: rate sensitivity (inverse), AI capex cycle, USD headwind for multinationals
- Healthcare: defensive in downturns, drug pricing policy, Medicare/Medicaid policy
- Financials: net interest margin (rate level + curve shape), credit cycle, loan demand
- Energy: oil/gas prices, OPEC policy, energy transition regulation, USD inverse
- Industrials: capex cycle, infrastructure spending, reshoring/tariff policy
- Consumer Discretionary: consumer confidence, wage growth vs inflation, credit availability
- Consumer Staples: defensive in downturns, input cost inflation, pricing power
- Materials: commodity cycle, construction activity, China demand, USD inverse
- Communication Services: ad spending (GDP-sensitive), regulatory (antitrust), rate sensitivity
- Real Estate: rate sensitivity (strong inverse), cap rates, housing supply/demand
- Utilities: rate sensitivity (inverse, bond proxy), regulatory (rate cases), energy transition

SCOPE: US macro only. Score based on conditions as of __DATE__. Do not forecast — assess current state.

Return JSON only — no prose before or after:

{"regime":"late_cycle","summary":"Macro is mixed but still growth-supportive.","sources_cited":["FOMC","CPI","UST","DXY"],"dimensions":{"fed_funds_and_guidance":{"signal":"stable_to_easing","current_value":"4.50%","trend":"stable","rationale":"Fed remains on hold with easing bias.","sources_cited":["FOMC","Fed speakers"]},"inflation_trajectory":{"signal":"decelerating","current_value":"2.7%","trend":"down","rationale":"Core inflation is easing gradually.","sources_cited":["CPI","PCE"]},"yield_curve_shape":{"signal":"steepening","current_value":"2s10s -15bp","trend":"less_inverted","rationale":"The curve is less inverted than earlier in the year.","sources_cited":["UST curve"]},"usd_strength":{"signal":"stable","current_value":"DXY 104","trend":"flat","rationale":"Dollar has been range-bound over the last 30 days.","sources_cited":["DXY"]},"credit_conditions":{"signal":"stable","current_value":"HY spreads ~340bp","trend":"stable","rationale":"Credit spreads remain contained.","sources_cited":["ICE BofA"]},"commodity_cycle":{"signal":"inflationary","current_value":"Oil firm, copper firm, gold elevated","trend":"up","rationale":"The commodity complex is sending a mild inflationary signal.","sources_cited":["WTI","HG1","Gold"]},"labor_market":{"signal":"normalizing","current_value":"Claims stable, payroll growth moderating","trend":"cooling","rationale":"Labor data remains healthy but is no longer tightening.","sources_cited":["NFP","claims"]},"fiscal_regulatory":{"signal":"mixed","current_value":null,"trend":"mixed","rationale":"Industrial policy remains supportive for capex-heavy sectors.","sources_cited":["policy"]}},"sectors":{"Technology":{"score":72,"rationale":"AI capex remains a strong offset to rate sensitivity."},"Healthcare":{"score":58,"rationale":"Defensive demand is balanced by policy uncertainty."},"Financials":{"score":64,"rationale":"Less inverted curves modestly improve NIM conditions."},"Energy":{"score":61,"rationale":"Firm oil supports cash flows despite mixed demand signals."},"Industrials":{"score":68,"rationale":"Reshoring and infrastructure capex remain tailwinds."},"Consumer Discretionary":{"score":47,"rationale":"Consumers face tighter credit and uneven real wage support."},"Consumer Staples":{"score":54,"rationale":"Defensive demand is steady but not a standout macro tailwind."},"Materials":{"score":63,"rationale":"Copper strength and capex spending support the group."},"Communication Services":{"score":57,"rationale":"Ad demand is resilient but still growth-sensitive."},"Real Estate":{"score":34,"rationale":"Elevated rates continue to weigh on cap rates."},"Utilities":{"score":41,"rationale":"Rate pressure offsets stable regulated demand."}}}

Field rules:
- regime: exactly one of early_cycle, mid_cycle, late_cycle, recession, recovery
- summary: one short sentence summarizing the current macro backdrop
- sources_cited: top-level list of the primary sources used for the macro read
- dimensions: MUST include exactly these 8 keys:
  - fed_funds_and_guidance
  - inflation_trajectory
  - yield_curve_shape
  - usd_strength
  - credit_conditions
  - commodity_cycle
  - labor_market
  - fiscal_regulatory
- each dimensions entry MUST include:
  - signal
  - current_value (string or null)
  - trend
  - rationale
  - sources_cited
- score: integer 0-100, use the full range — do NOT cluster all sectors in 45-65
- rationale: one specific sentence citing the key macro factor, not generic
- You MUST return all 11 sectors listed above. Do not skip any."""


@app.command("macro-prompt")
def macro_prompt(
    generate: bool = typer.Option(False, "--generate", help="Print the Grok prompt for macro regime analysis"),
    ingest: bool = typer.Option(False, "--ingest", help="Read JSON from stdin (or --file) and save to cache"),
    file: str = typer.Option("", "--file", help="Path to JSON file (alternative to stdin for --ingest)"),
    date: str = typer.Option("", "--date", help="Date override (YYYY-MM-DD, defaults to today)"),
):
    """Generate Grok prompts for per-sector macro regime data and ingest cached results."""
    import datetime as _dt

    as_of_date = date.strip() or _dt.date.today().strftime("%Y-%m-%d")

    if not generate and not ingest:
        console.print("[red]Specify --generate or --ingest[/red]")
        raise typer.Exit(1)

    if generate:
        _do_generate(as_of_date)
    elif ingest:
        _do_ingest(as_of_date, file.strip())


def _do_generate(as_of_date: str):
    """Print a ready-to-paste Grok prompt for macro regime analysis."""
    prompt = _MACRO_PROMPT_TEMPLATE.replace("__DATE__", as_of_date)

    console.print(f"[bold]Grok macro prompt for {as_of_date}[/bold]\n")
    console.print(prompt)
    console.print(f"\n[dim]Copy the above, paste into Grok deep research, then run:[/dim]")
    console.print(f"[dim]  aeternus macro-prompt --ingest --date {as_of_date}[/dim]")


def _do_ingest(as_of_date: str, file_path: str):
    """Read JSON from file or stdin, validate, and save to macro cache."""
    from tradingagents.dealflow.sources.social_news import _extract_json_payload

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
        result = _validate_macro_payload(parsed)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    from tradingagents.dealflow.sources.macro import _save_macro_cache
    path = _save_macro_cache(as_of_date, result)
    console.print(f"[green]Saved {len(result['sectors'])} sectors and {len(result['dimensions'])} dimensions to {path}[/green]")


def _validate_macro_payload(parsed: Dict[str, Any]) -> Dict[str, Any]:
    regime = str(parsed.get("regime", "") or "").strip()
    if regime not in _REGIME_CHOICES:
        raise ValueError(f"Invalid regime: {regime or '<empty>'}")

    dimensions = parsed.get("dimensions")
    if not isinstance(dimensions, dict) or not dimensions:
        raise ValueError("JSON must contain a 'dimensions' dict with entries")

    sectors = parsed.get("sectors")
    if not isinstance(sectors, dict) or not sectors:
        raise ValueError("JSON must contain a 'sectors' dict with entries")

    missing_dimensions = [name for name in _MACRO_DIMENSIONS if name not in dimensions]
    if missing_dimensions:
        raise ValueError(f"Missing required dimensions: {', '.join(missing_dimensions)}")

    missing_sectors = [name for name in _GICS_SECTORS if name not in sectors]
    if missing_sectors:
        raise ValueError(f"Missing required sectors: {', '.join(missing_sectors)}")

    result: Dict[str, Any] = {
        "regime": regime,
        "summary": str(parsed.get("summary", "") or "").strip() or None,
        "sources_cited": _normalize_sources_list(parsed.get("sources_cited")),
        "dimensions": {},
        "sectors": {},
    }

    for dimension_name in _MACRO_DIMENSIONS:
        result["dimensions"][dimension_name] = _normalize_dimension_entry(
            dimension_name,
            dimensions.get(dimension_name),
        )

    for sector_name in _GICS_SECTORS:
        result["sectors"][sector_name] = _normalize_sector_entry(
            sector_name,
            sectors.get(sector_name),
        )

    return result


def _normalize_dimension_entry(dimension_name: str, payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"Dimension '{dimension_name}' must be a dict")

    for field_name in ("signal", "trend", "rationale", "sources_cited"):
        if field_name not in payload:
            raise ValueError(f"Dimension '{dimension_name}' missing '{field_name}'")

    current_value = payload.get("current_value")
    if current_value is not None:
        current_value = str(current_value).strip() or None

    rationale = str(payload.get("rationale", "") or "").strip()
    if not rationale:
        raise ValueError(f"Dimension '{dimension_name}' has empty rationale")

    return {
        "signal": str(payload.get("signal", "") or "").strip(),
        "current_value": current_value,
        "trend": str(payload.get("trend", "") or "").strip(),
        "rationale": rationale,
        "sources_cited": _normalize_sources_list(payload.get("sources_cited")),
    }


def _normalize_sector_entry(sector_name: str, payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"Sector '{sector_name}' must be a dict")
    if "score" not in payload:
        raise ValueError(f"Sector '{sector_name}' missing 'score'")
    try:
        score = max(0, min(100, int(payload["score"])))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Sector '{sector_name}' has invalid score") from exc
    rationale = str(payload.get("rationale", "") or "").strip()
    if not rationale:
        raise ValueError(f"Sector '{sector_name}' has empty rationale")
    return {"score": score, "rationale": rationale}


def _normalize_sources_list(value: Any) -> List[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        return [str(value).strip()] if str(value).strip() else []
    return [str(item).strip() for item in value if str(item).strip()]
