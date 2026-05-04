"""Tests for tradingagents/dealflow/sources/breakout_scanner.py."""

from __future__ import annotations

import json
import datetime as dt
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pandas as pd
import pytest

from tradingagents.dealflow.sources.breakout_scanner import (
    _NEAR_HIGH_THRESHOLD,
    _SCORE_THRESHOLD,
    _ADV_MIN_USD,
    _AKG_MIN_CENTRALITY,
    _MAX_BARS,
    compute_breakout_score,
    scan_breakout_discovery,
    _get_scan_universe,
    _filter_by_adv,
    _update_ohlcv_cache,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_close_series(n: int = 380, trend: str = "flat", near_high_pct: float = 1.0) -> pd.Series:
    """Build a synthetic daily close series of length n.

    trend='up'   — steadily rising (so latest is near the high)
    trend='flat' — constant value 100.0
    near_high_pct controls how close the last close is to the series max.
    """
    idx = pd.date_range(end="2026-02-24", periods=n, freq="B")
    if trend == "up":
        closes = np.linspace(80.0, 100.0, n)
    else:
        closes = np.full(n, 100.0)

    # Adjust last value so that close[-1] / max(close[-252:]) == near_high_pct
    series = pd.Series(closes, index=idx)
    high_252 = float(series.iloc[-252:].max())
    series.iloc[-1] = high_252 * near_high_pct
    return series


def _make_volume_series(n: int = 380, vol_ratio: float = 1.0, baseline: float = 1_000_000.0) -> pd.Series:
    """Build synthetic volume where volume[-1] == baseline * vol_ratio."""
    idx = pd.date_range(end="2026-02-24", periods=n, freq="B")
    volumes = np.full(n, baseline)
    volumes[-1] = baseline * vol_ratio
    return pd.Series(volumes, index=idx)


# ---------------------------------------------------------------------------
# 1. compute_breakout_score returns 0 when stock is far from 52-week high
# ---------------------------------------------------------------------------

def test_score_zero_when_far_from_high():
    # near_high = 0.70 (30% below high) → near_high_component = 0
    # vol_ratio = 1.0 → volume_component = 0
    # above_sma200=False, sma50_above_sma200=False → trend=0
    score = compute_breakout_score(
        near_high=0.70,
        vol_ratio=1.0,
        above_sma200=False,
        sma50_above_sma200=False,
    )
    assert score == 0.0


# ---------------------------------------------------------------------------
# 2. Score increases as near_high_pct approaches 1.0
# ---------------------------------------------------------------------------

def test_score_increases_with_near_high():
    s90 = compute_breakout_score(near_high=0.90, vol_ratio=1.0, above_sma200=False, sma50_above_sma200=False)
    s95 = compute_breakout_score(near_high=0.95, vol_ratio=1.0, above_sma200=False, sma50_above_sma200=False)
    s100 = compute_breakout_score(near_high=1.00, vol_ratio=1.0, above_sma200=False, sma50_above_sma200=False)
    assert s90 < s95 < s100


# ---------------------------------------------------------------------------
# 3. Volume ratio has no effect on score (zeroed after backtest)
# ---------------------------------------------------------------------------

def test_vol_ratio_has_no_effect_on_score():
    s1 = compute_breakout_score(near_high=0.97, vol_ratio=1.0, above_sma200=False, sma50_above_sma200=False)
    s2 = compute_breakout_score(near_high=0.97, vol_ratio=2.0, above_sma200=False, sma50_above_sma200=False)
    s3 = compute_breakout_score(near_high=0.97, vol_ratio=3.0, above_sma200=False, sma50_above_sma200=False)
    assert s1 == s2 == s3


# ---------------------------------------------------------------------------
# 4. above_sma200=True adds points
# ---------------------------------------------------------------------------

def test_above_sma200_adds_points():
    without = compute_breakout_score(near_high=0.97, vol_ratio=2.0, above_sma200=False, sma50_above_sma200=False)
    with_ = compute_breakout_score(near_high=0.97, vol_ratio=2.0, above_sma200=True, sma50_above_sma200=False)
    assert with_ > without
    assert with_ - without == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# 5. sma50_above_sma200 adds golden-cross bonus
# ---------------------------------------------------------------------------

def test_golden_cross_adds_points():
    without = compute_breakout_score(near_high=0.97, vol_ratio=2.0, above_sma200=True, sma50_above_sma200=False)
    with_ = compute_breakout_score(near_high=0.97, vol_ratio=2.0, above_sma200=True, sma50_above_sma200=True)
    assert with_ > without
    assert with_ - without == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# 6. Score caps at 100 (no overflow)
# ---------------------------------------------------------------------------

def test_score_caps_at_100():
    # max possible inputs: near_high=1.0, vol_ratio=3.0 (or more), both trend flags True
    score = compute_breakout_score(
        near_high=1.0,
        vol_ratio=100.0,
        above_sma200=True,
        sma50_above_sma200=True,
    )
    assert score == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 7. _get_scan_universe includes base symbols when AKG fails
# ---------------------------------------------------------------------------

def test_scan_universe_empty_when_akg_fails():
    with patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph.load", side_effect=FileNotFoundError("no graph")):
        universe = _get_scan_universe()

    # AKG is the sole source — if it fails, universe is empty
    assert universe == []


# ---------------------------------------------------------------------------
# 8. _get_scan_universe filters by centrality
# ---------------------------------------------------------------------------

def test_scan_universe_filters_by_centrality():
    mock_akg = MagicMock()
    mock_akg._nodes = {
        "LOWC": {"id": "LOWC", "node_type": "company", "centrality": 0.03},
        "HIGHC": {"id": "HIGHC", "node_type": "company", "centrality": 0.10},
    }
    with patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph.load", return_value=mock_akg):
        universe = _get_scan_universe()

    assert "HIGHC" in universe
    assert "LOWC" not in universe


# ---------------------------------------------------------------------------
# 9. ADV filter excludes illiquid symbols
# ---------------------------------------------------------------------------

def test_adv_filter_excludes_illiquid():
    cache = {
        "ILLIQ": {
            "close": [5.0] * 30,
            "volume": [100_000.0] * 30,  # ADV = $500K
        },
        "LIQUID": {
            "close": [100.0] * 30,
            "volume": [500_000.0] * 30,  # ADV = $50M
        },
    }
    result = _filter_by_adv(cache, ["ILLIQ", "LIQUID"])
    assert "LIQUID" in result
    assert "ILLIQ" not in result


# ---------------------------------------------------------------------------
# 10. Discovery writes to AKG for qualifying breakouts
# ---------------------------------------------------------------------------

def test_discovery_writes_to_akg():
    # Build cache entry with a strong breakout (near high, high vol)
    n = _MAX_BARS
    closes = list(np.linspace(80.0, 100.0, n))
    volumes = [1_000_000.0] * n
    volumes[-1] = 3_000_000.0  # 3x vol ratio → qualifying
    # ADV = 100 * 1M = $100M (liquid)
    cache = {
        "TEST": {
            "last_date": "2026-03-02",
            "close": closes,
            "volume": volumes,
        },
    }

    mock_akg = MagicMock()
    mock_akg._nodes = {}

    with (
        patch("tradingagents.dealflow.sources.breakout_scanner._get_scan_universe", return_value=["TEST"]),
        patch("tradingagents.dealflow.sources.breakout_scanner._load_ohlcv_cache", return_value=cache),
        patch("tradingagents.dealflow.sources.breakout_scanner._save_ohlcv_cache"),
        patch("tradingagents.dealflow.sources.breakout_scanner._filter_by_adv", return_value=["TEST"]),
        patch("tradingagents.dealflow.sources.breakout_scanner._update_ohlcv_cache", return_value=cache),
        patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph.load", return_value=mock_akg),
    ):
        result = scan_breakout_discovery(trade_date="2026-03-02")

    assert result["count"] == 1
    assert result["alerts"][0]["ticker"] == "TEST"
    mock_akg.enrich_node_breakout.assert_called_once()
    mock_akg.save.assert_called_once()


# ---------------------------------------------------------------------------
# 11. No AKG write when no breakouts found
# ---------------------------------------------------------------------------

def test_no_akg_write_when_no_breakouts():
    # Declining stock — far from 52w high → no breakout
    n = _MAX_BARS
    closes = list(np.linspace(100.0, 70.0, n))  # declining
    volumes = [1_000_000.0] * n
    cache = {
        "DECL": {
            "last_date": "2026-03-02",
            "close": closes,
            "volume": volumes,
        },
    }

    with (
        patch("tradingagents.dealflow.sources.breakout_scanner._get_scan_universe", return_value=["DECL"]),
        patch("tradingagents.dealflow.sources.breakout_scanner._load_ohlcv_cache", return_value=cache),
        patch("tradingagents.dealflow.sources.breakout_scanner._save_ohlcv_cache"),
        patch("tradingagents.dealflow.sources.breakout_scanner._filter_by_adv", return_value=["DECL"]),
        patch("tradingagents.dealflow.sources.breakout_scanner._update_ohlcv_cache", return_value=cache),
        patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph.load") as mock_load,
    ):
        result = scan_breakout_discovery(trade_date="2026-03-02")

    assert result["count"] == 0
    assert result["alerts"] == []
    mock_load.assert_not_called()


# ---------------------------------------------------------------------------
# 12. Incremental cache appends bars (capped at 252)
# ---------------------------------------------------------------------------

def test_incremental_cache_appends_bars():
    n = 250
    existing_closes = list(np.linspace(80.0, 99.0, n))
    existing_volumes = [1_000_000.0] * n

    # Build a 30-day download response with dates after the stale entry
    new_n = 5
    idx = pd.date_range(start="2026-02-25", periods=new_n, freq="B")
    new_close = pd.Series([99.5, 100.0, 100.5, 101.0, 101.5], index=idx)
    new_volume = pd.Series([1_100_000.0] * new_n, index=idx)

    cache = {
        "SYM": {
            "last_date": "2026-02-24",
            "close": existing_closes,
            "volume": existing_volumes,
        },
    }

    with patch(
        "tradingagents.dealflow.sources.breakout_scanner._download_ohlcv",
        return_value=({"SYM": new_close}, {"SYM": new_volume}),
    ):
        updated = _update_ohlcv_cache(cache, ["SYM"], "2026-03-02")

    entry = updated["SYM"]
    assert entry["last_date"] == "2026-03-03"  # last business day from date_range
    assert len(entry["close"]) == min(n + new_n, _MAX_BARS)
    assert entry["close"][-1] == 101.5


# ---------------------------------------------------------------------------
# 13. First run downloads full 380d history
# ---------------------------------------------------------------------------

def test_first_run_downloads_full_history():
    n = 380
    idx = pd.date_range(end="2026-03-02", periods=n, freq="B")
    close = pd.Series(np.linspace(80.0, 100.0, n), index=idx)
    volume = pd.Series(np.full(n, 1_000_000.0), index=idx)

    with patch(
        "tradingagents.dealflow.sources.breakout_scanner._download_ohlcv",
        return_value=({"NEW": close}, {"NEW": volume}),
    ) as mock_dl:
        cache = _update_ohlcv_cache({}, ["NEW"], "2026-03-02")

    mock_dl.assert_called_once_with(["NEW"], period="380d")
    assert "NEW" in cache
    assert len(cache["NEW"]["close"]) == _MAX_BARS
