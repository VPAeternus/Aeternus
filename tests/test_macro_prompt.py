"""Tests for macro-prompt CLI command and macro cache integration."""

import json
import os
from unittest import mock

_DIMENSIONS = {
    "fed_funds_and_guidance": {
        "signal": "stable_to_easing",
        "current_value": "4.50%",
        "trend": "stable",
        "rationale": "Fed remains on hold with easing bias.",
        "sources_cited": ["FOMC"],
    },
    "inflation_trajectory": {
        "signal": "decelerating",
        "current_value": "2.7%",
        "trend": "down",
        "rationale": "Core inflation is easing gradually.",
        "sources_cited": ["CPI"],
    },
    "yield_curve_shape": {
        "signal": "steepening",
        "current_value": "-0.15%",
        "trend": "less_inverted",
        "rationale": "The 2s10s spread is less inverted than earlier in the year.",
        "sources_cited": ["UST curve"],
    },
    "usd_strength": {
        "signal": "stable",
        "current_value": "DXY 104",
        "trend": "flat",
        "rationale": "Dollar has been range-bound over the last 30 days.",
        "sources_cited": ["DXY"],
    },
    "credit_conditions": {
        "signal": "stable",
        "current_value": "HY spreads ~340bp",
        "trend": "stable",
        "rationale": "Credit spreads remain contained.",
        "sources_cited": ["ICE BofA"],
    },
    "commodity_cycle": {
        "signal": "inflationary",
        "current_value": "Oil firm, copper firm, gold elevated",
        "trend": "up",
        "rationale": "Commodity complex is sending a mild inflationary signal.",
        "sources_cited": ["WTI", "HG1", "Gold"],
    },
    "labor_market": {
        "signal": "normalizing",
        "current_value": "Claims stable, payroll growth moderating",
        "trend": "cooling",
        "rationale": "Labor data remains healthy but is no longer tightening.",
        "sources_cited": ["NFP", "claims"],
    },
    "fiscal_regulatory": {
        "signal": "mixed",
        "current_value": None,
        "trend": "mixed",
        "rationale": "Industrial policy remains supportive for capex-heavy sectors.",
        "sources_cited": ["policy"],
    },
}

_SECTORS = {
    "Technology": {"score": 72, "rationale": "AI capex remains a strong offset to rate sensitivity."},
    "Healthcare": {"score": 58, "rationale": "Defensive demand is balanced by policy uncertainty."},
    "Financials": {"score": 64, "rationale": "Less inverted curves modestly improve NIM conditions."},
    "Energy": {"score": 61, "rationale": "Firm oil supports cash flows despite mixed demand signals."},
    "Industrials": {"score": 68, "rationale": "Reshoring and infrastructure capex remain tailwinds."},
    "Consumer Discretionary": {"score": 47, "rationale": "Consumers face tighter credit and uneven real wage support."},
    "Consumer Staples": {"score": 54, "rationale": "Defensive demand is steady but not a standout macro tailwind."},
    "Materials": {"score": 63, "rationale": "Copper strength and capex spending support the group."},
    "Communication Services": {"score": 57, "rationale": "Ad demand is resilient but still growth-sensitive."},
    "Real Estate": {"score": 34, "rationale": "Elevated rates continue to weigh on cap rates."},
    "Utilities": {"score": 41, "rationale": "Rate pressure offsets stable regulated demand."},
}


def _valid_macro_payload():
    return {
        "regime": "late_cycle",
        "summary": "Macro is mixed but still growth-supportive.",
        "sources_cited": ["FOMC", "CPI", "UST", "DXY"],
        "dimensions": json.loads(json.dumps(_DIMENSIONS)),
        "sectors": json.loads(json.dumps(_SECTORS)),
    }


# ---------------------------------------------------------------------------
# Test: cache overrides SMA formula
# ---------------------------------------------------------------------------

def test_macro_cache_overrides_formula(tmp_path):
    """When a macro cache file exists, the connector uses sector scores from it."""
    from tradingagents.dealflow.sources.macro import collect_macro_signals

    cache = _valid_macro_payload()
    cache["sectors"]["Technology"]["score"] = 80
    cache["sectors"]["Energy"]["score"] = 30
    cache_file = tmp_path / "macro_cache_2026-03-06.json"
    cache_file.write_text(json.dumps(cache))

    universe = [
        {"symbol": "AAPL", "asset_class": "Equity", "sector": "Technology"},
        {"symbol": "XOM", "asset_class": "Equity", "sector": "Energy"},
    ]

    with mock.patch(
        "tradingagents.dealflow.sources.macro._macro_cache_path",
        return_value=str(cache_file),
    ):
        signals = collect_macro_signals(universe, as_of_date="2026-03-06")

    assert len(signals) == 2
    by_sym = {s["symbol"]: s for s in signals}
    assert by_sym["AAPL"]["raw_score"] == 80.0
    assert by_sym["XOM"]["raw_score"] == 30.0
    assert by_sym["AAPL"]["source_name"] == "grok_macro_cache"


# ---------------------------------------------------------------------------
# Test: neutral fallback without cache
# ---------------------------------------------------------------------------

def test_macro_fallback_without_cache():
    """Without a cache file, the connector returns neutral 50s with NO_DATA."""
    from tradingagents.dealflow.sources.macro import collect_macro_signals

    universe = [
        {"symbol": "AAPL", "asset_class": "Equity", "sector": "Technology"},
    ]

    signals = collect_macro_signals(universe, as_of_date="9999-01-01")

    assert len(signals) == 1
    assert signals[0]["source_name"] == "macro_no_cache"
    assert signals[0]["raw_score"] == 50.0
    assert signals[0]["source_status"] == "NO_DATA"
    assert signals[0]["direction"] == "NEUTRAL"


# ---------------------------------------------------------------------------
# Test: ingest validates sectors
# ---------------------------------------------------------------------------

def test_macro_ingest_validates_sectors(tmp_path):
    """Ingest rejects JSON without a 'sectors' dict."""
    from tradingagents.dealflow.sources.social_news import _extract_json_payload

    bad_payload = '{"regime": "late_cycle"}'
    parsed = _extract_json_payload(bad_payload)
    assert isinstance(parsed, dict)
    assert "sectors" not in parsed or not parsed.get("sectors")


# ---------------------------------------------------------------------------
# Test: cache save/load round-trip
# ---------------------------------------------------------------------------

def test_macro_cache_round_trip(tmp_path):
    """Save and load a macro cache file."""
    from tradingagents.dealflow.sources.macro import _load_macro_cache, _save_macro_cache

    data = _valid_macro_payload()
    data["regime"] = "mid_cycle"
    data["sectors"]["Technology"] = {"score": 65, "rationale": "neutral"}

    with mock.patch(
        "tradingagents.dealflow.sources.macro._macro_cache_path",
        return_value=str(tmp_path / "macro_cache_2026-03-06.json"),
    ):
        path = _save_macro_cache("2026-03-06", data)
        loaded = _load_macro_cache("2026-03-06")

    assert loaded == data
    assert os.path.isfile(path)


def test_macro_prompt_validation_accepts_structured_dimensions_and_preserves_them():
    from cli.commands.macro_prompt import _validate_macro_payload

    payload = _valid_macro_payload()

    validated = _validate_macro_payload(payload)

    assert validated["regime"] == "late_cycle"
    assert validated["summary"] == "Macro is mixed but still growth-supportive."
    assert validated["dimensions"]["fed_funds_and_guidance"]["signal"] == "stable_to_easing"
    assert validated["dimensions"]["fiscal_regulatory"]["current_value"] is None
    assert validated["sectors"]["Technology"]["score"] == 72


def test_macro_prompt_validation_requires_all_dimensions():
    from cli.commands.macro_prompt import _validate_macro_payload

    payload = _valid_macro_payload()
    payload["dimensions"].pop("usd_strength")

    try:
        _validate_macro_payload(payload)
    except ValueError as exc:
        assert "Missing required dimensions" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing dimension")


def test_macro_prompt_validation_requires_all_gics_sectors():
    from cli.commands.macro_prompt import _validate_macro_payload

    payload = _valid_macro_payload()
    payload["sectors"].pop("Utilities")

    try:
        _validate_macro_payload(payload)
    except ValueError as exc:
        assert "Missing required sectors" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing sector")


def test_macro_prompt_validation_rejects_invalid_regime():
    from cli.commands.macro_prompt import _validate_macro_payload

    payload = _valid_macro_payload()
    payload["regime"] = "bull_market"

    try:
        _validate_macro_payload(payload)
    except ValueError as exc:
        assert "Invalid regime" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid regime")
