"""Tests for the macro regime fit deal flow collector.

Tests the Grok-sourced cache path and the neutral-50 fallback.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from tradingagents.dealflow.sources.macro import collect_macro_signals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_universe(symbol: str, sector: str, asset_class: str = "Equity"):
    return {"symbol": symbol, "asset_class": asset_class, "sector": sector, "liquidity_score": 50.0, "aliases": []}


# ---------------------------------------------------------------------------
# 1. No cache → neutral 50 with NO_DATA
# ---------------------------------------------------------------------------

def test_no_cache_returns_neutral():
    """Without a cache file, all stocks get score=50, NO_DATA."""
    universe = [_make_universe("AAPL", "Technology")]
    signals = collect_macro_signals(universe, as_of_date="9999-01-01")

    assert len(signals) == 1
    sig = signals[0]
    assert sig["raw_score"] == 50.0
    assert sig["source_status"] == "NO_DATA"
    assert sig["evidence_count"] == 0
    assert sig["direction"] == "NEUTRAL"
    assert sig["source_name"] == "macro_no_cache"


# ---------------------------------------------------------------------------
# 2. Cache present → sector scores used
# ---------------------------------------------------------------------------

def test_cache_provides_sector_scores(tmp_path):
    """When a Grok cache exists, stocks get their sector's score."""
    cache = {
        "regime": "late_cycle",
        "sectors": {
            "Technology": {"score": 80, "rationale": "AI boom"},
            "Energy": {"score": 30, "rationale": "oil glut"},
        },
    }
    cache_file = tmp_path / "macro_cache_2026-03-06.json"
    cache_file.write_text(json.dumps(cache))

    universe = [
        _make_universe("AAPL", "Technology"),
        _make_universe("XOM", "Energy"),
    ]

    with patch("tradingagents.dealflow.sources.macro._macro_cache_path", return_value=str(cache_file)):
        signals = collect_macro_signals(universe, as_of_date="2026-03-06")

    scores = {s["symbol"]: s for s in signals}
    assert scores["AAPL"]["raw_score"] == 80.0
    assert scores["XOM"]["raw_score"] == 30.0
    assert scores["AAPL"]["source_name"] == "grok_macro_cache"
    assert scores["AAPL"]["source_status"] == "OK"


# ---------------------------------------------------------------------------
# 3. Variant sector names are normalized before cache lookup
# ---------------------------------------------------------------------------

def test_variant_sector_names_normalized(tmp_path):
    """'Basic Materials' normalizes to 'Materials' for cache lookup."""
    cache = {
        "regime": "mid_cycle",
        "sectors": {"Materials": {"score": 65, "rationale": "commodity cycle"}},
    }
    cache_file = tmp_path / "macro_cache_2026-03-06.json"
    cache_file.write_text(json.dumps(cache))

    universe = [_make_universe("FCX", "Basic Materials")]

    with patch("tradingagents.dealflow.sources.macro._macro_cache_path", return_value=str(cache_file)):
        signals = collect_macro_signals(universe, as_of_date="2026-03-06")

    assert signals[0]["raw_score"] == 65.0


# ---------------------------------------------------------------------------
# 4. Sector not in cache → defaults to 50
# ---------------------------------------------------------------------------

def test_missing_sector_defaults_to_50(tmp_path):
    """A stock whose sector isn't in the cache gets neutral 50."""
    cache = {
        "regime": "early_cycle",
        "sectors": {"Technology": {"score": 90, "rationale": "boom"}},
    }
    cache_file = tmp_path / "macro_cache_2026-03-06.json"
    cache_file.write_text(json.dumps(cache))

    universe = [_make_universe("XOM", "Energy")]

    with patch("tradingagents.dealflow.sources.macro._macro_cache_path", return_value=str(cache_file)):
        signals = collect_macro_signals(universe, as_of_date="2026-03-06")

    assert signals[0]["raw_score"] == 50.0


# ---------------------------------------------------------------------------
# 5. All required DealFlowSignal keys present
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {"symbol", "signal_family", "raw_score", "z_score", "direction",
                 "evidence_count", "freshness_hours", "source_status", "source_name"}


def test_signal_has_required_keys():
    universe = [_make_universe("AAPL", "Technology")]
    signals = collect_macro_signals(universe, as_of_date="9999-01-01")

    for key in REQUIRED_KEYS:
        assert key in signals[0], f"Missing key: {key}"
    assert signals[0]["signal_family"] == "macro_regime_fit"
