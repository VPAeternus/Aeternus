"""Tests for the sector rotation deal flow connector.

All yfinance calls are mocked — no real API calls are made.
"""

from __future__ import annotations

from typing import Dict, List
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dealflow.sources.sector_rotation import (
    SECTOR_ETF_MAP,
    _compute_sector_scores,
    _leadership_tag,
    _percentile_rank_map,
    _score_from_percentile,
    collect_sector_rotation_signals,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_universe(symbol: str, sector: str, asset_class: str = "Equity"):
    return {"symbol": symbol, "asset_class": asset_class, "sector": sector, "liquidity_score": 50.0, "aliases": []}


def _make_close_series(length: int = 150, start: float = 100.0, drift: float = 0.001) -> pd.Series:
    """Build a synthetic close series with `length` daily bars."""
    import numpy as np
    prices = [start]
    for _ in range(length - 1):
        prices.append(prices[-1] * (1.0 + drift))
    return pd.Series(prices, dtype=float)


def _build_mock_close_map(sectors_accel: Dict[str, float]) -> Dict[str, pd.Series]:
    """Build a close map where each sector ETF has the requested acceleration.

    acceleration = ret_4w - ret_13w
    We achieve this by setting up a series with 150 bars and controlled prices.
    """
    close_map: Dict[str, pd.Series] = {}
    for sector, etf in SECTOR_ETF_MAP.items():
        # Base price; use acceleration to shape 4w vs 13w returns
        accel = sectors_accel.get(sector, 0.0)
        # Fix 13-week (65-day) return to 10%, vary 4-week to hit target accel
        ret_13w_target = 10.0
        ret_4w_target = ret_13w_target + accel

        # Build series of 150 bars so bar[-66] and bar[-21] are well-defined.
        # We need: (bar[-1] - bar[-66]) / bar[-66] = ret_13w_target / 100
        # and:     (bar[-1] - bar[-21]) / bar[-21] = ret_4w_target / 100
        prices = [100.0] * 150
        # Set the critical anchors; fill rest with 100.
        bar_66 = 100.0
        bar_21 = bar_66 * (1.0 + ret_13w_target / 100.0) / (1.0 + ret_4w_target / 100.0)
        bar_final = bar_66 * (1.0 + ret_13w_target / 100.0)

        prices[-1] = bar_final
        prices[-21] = bar_21
        prices[-66] = bar_66

        # Fill gaps linearly to avoid edge cases in series length checks.
        close_map[etf] = pd.Series(prices, dtype=float)

    return close_map


# ---------------------------------------------------------------------------
# 1. _compute_sector_scores returns dict with sector → score mapping
# ---------------------------------------------------------------------------

def test_compute_sector_scores_returns_all_sectors():
    """All sectors with sufficient data get a score in the output dict."""
    # Give every sector a non-zero acceleration so none are skipped.
    close_map = _build_mock_close_map({s: float(i) for i, s in enumerate(SECTOR_ETF_MAP)})

    with patch(
        "tradingagents.dealflow.sources.sector_rotation._download_sector_closes",
        return_value=close_map,
    ):
        scores, meta = _compute_sector_scores()

    assert scores is not None
    assert len(scores) == len(SECTOR_ETF_MAP)
    for sector in SECTOR_ETF_MAP:
        assert sector in scores
        assert 0.0 <= scores[sector] <= 100.0


# ---------------------------------------------------------------------------
# 2. Score for a leading sector (high acceleration) is > 60
# ---------------------------------------------------------------------------

def test_leading_sector_score_above_60():
    """A sector with the highest acceleration percentile scores above 60."""
    # Give Technology 50% acceleration vs others near 0.
    accel = {s: 0.0 for s in SECTOR_ETF_MAP}
    accel["Technology"] = 50.0

    close_map = _build_mock_close_map(accel)

    with patch(
        "tradingagents.dealflow.sources.sector_rotation._download_sector_closes",
        return_value=close_map,
    ):
        scores, _ = _compute_sector_scores()

    assert scores is not None
    assert scores["Technology"] > 60.0


# ---------------------------------------------------------------------------
# 3. Score for a lagging sector (negative acceleration) is < 40
# ---------------------------------------------------------------------------

def test_lagging_sector_score_below_40():
    """A sector with the lowest acceleration percentile scores below 40."""
    # Give Utilities -50% acceleration vs others near 0.
    accel = {s: 0.0 for s in SECTOR_ETF_MAP}
    accel["Utilities"] = -50.0

    close_map = _build_mock_close_map(accel)

    with patch(
        "tradingagents.dealflow.sources.sector_rotation._download_sector_closes",
        return_value=close_map,
    ):
        scores, _ = _compute_sector_scores()

    assert scores is not None
    assert scores["Utilities"] < 40.0


# ---------------------------------------------------------------------------
# 4. Unknown sector returns score = 50
# ---------------------------------------------------------------------------

def test_unknown_sector_returns_50():
    """A symbol with a sector not in SECTOR_ETF_MAP gets score 50."""
    universe = [_make_universe("XYZ", "Exotic Niche Sector")]
    close_map = _build_mock_close_map({s: float(i) for i, s in enumerate(SECTOR_ETF_MAP)})

    with patch(
        "tradingagents.dealflow.sources.sector_rotation._download_sector_closes",
        return_value=close_map,
    ):
        signals = collect_sector_rotation_signals(universe)

    assert len(signals) == 1
    assert signals[0]["raw_score"] == 50.0


# ---------------------------------------------------------------------------
# 5. collect_sector_rotation_signals returns list of signal dicts
# ---------------------------------------------------------------------------

def test_collect_returns_list_for_all_symbols():
    """One signal per universe symbol is returned."""
    universe = [
        _make_universe("NVDA", "Semiconductors"),
        _make_universe("JPM", "Financials"),
        _make_universe("XOM", "Energy"),
    ]
    close_map = _build_mock_close_map({s: 0.0 for s in SECTOR_ETF_MAP})

    with patch(
        "tradingagents.dealflow.sources.sector_rotation._download_sector_closes",
        return_value=close_map,
    ):
        signals = collect_sector_rotation_signals(universe)

    assert len(signals) == 3
    symbols = {s["symbol"] for s in signals}
    assert symbols == {"NVDA", "JPM", "XOM"}


# ---------------------------------------------------------------------------
# 6. All returned dicts have required keys
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {"symbol", "signal_family", "raw_score", "z_score", "direction",
                 "evidence_count", "freshness_hours", "source_status", "source_name"}


def test_signal_dicts_have_required_keys():
    """Every returned signal dict has all DealFlowSignal keys."""
    universe = [_make_universe("AAPL", "Technology")]
    close_map = _build_mock_close_map({s: float(i) for i, s in enumerate(SECTOR_ETF_MAP)})

    with patch(
        "tradingagents.dealflow.sources.sector_rotation._download_sector_closes",
        return_value=close_map,
    ):
        signals = collect_sector_rotation_signals(universe)

    assert len(signals) == 1
    sig = signals[0]
    for key in REQUIRED_KEYS:
        assert key in sig, f"Missing key: {key}"
    assert sig["signal_family"] == "sector_rotation"


# ---------------------------------------------------------------------------
# 7. Connector returns empty list (not an error) when yfinance fails
# ---------------------------------------------------------------------------

def test_yfinance_failure_returns_no_data_signals_not_exception():
    """When yfinance raises, collect_sector_rotation_signals returns NO_DATA signals."""
    universe = [
        _make_universe("AAPL", "Technology"),
        _make_universe("JPM", "Financials"),
    ]

    with patch(
        "tradingagents.dealflow.sources.sector_rotation._download_sector_closes",
        return_value=None,  # simulate total download failure
    ):
        signals = collect_sector_rotation_signals(universe)

    # Should not raise — returns NO_DATA signals for each symbol.
    assert len(signals) == 2
    for sig in signals:
        assert sig["source_status"] == "NO_DATA"


def test_yfinance_exception_does_not_propagate():
    """Even if yfinance itself raises, collect_sector_rotation_signals never raises."""
    universe = [_make_universe("TSLA", "Consumer Discretionary")]

    with patch(
        "tradingagents.dealflow.sources.sector_rotation.yf.download",
        side_effect=RuntimeError("network error"),
    ):
        # Should not raise.
        signals = collect_sector_rotation_signals(universe)

    assert isinstance(signals, list)
    for sig in signals:
        assert sig["source_status"] == "NO_DATA"


# ---------------------------------------------------------------------------
# 8. Leadership tag is LEADING / LAGGING / NEUTRAL based on percentile
# ---------------------------------------------------------------------------

def test_leadership_tag_leading():
    assert _leadership_tag(67.0) == "LEADING"
    assert _leadership_tag(100.0) == "LEADING"
    assert _leadership_tag(80.0) == "LEADING"


def test_leadership_tag_lagging():
    assert _leadership_tag(0.0) == "LAGGING"
    assert _leadership_tag(32.9) == "LAGGING"


def test_leadership_tag_neutral():
    assert _leadership_tag(33.0) == "NEUTRAL"
    assert _leadership_tag(50.0) == "NEUTRAL"
    assert _leadership_tag(66.0) == "NEUTRAL"


def test_leadership_reflected_in_source_name():
    """The leadership tag appears in source_name for covered sectors."""
    # Technology with very high acceleration → LEADING
    accel = {s: 0.0 for s in SECTOR_ETF_MAP}
    accel["Technology"] = 99.0

    universe = [_make_universe("AAPL", "Technology")]
    close_map = _build_mock_close_map(accel)

    with patch(
        "tradingagents.dealflow.sources.sector_rotation._download_sector_closes",
        return_value=close_map,
    ):
        signals = collect_sector_rotation_signals(universe)

    assert len(signals) == 1
    assert "LEADING" in signals[0]["source_name"]


# ---------------------------------------------------------------------------
# Bonus: score_from_percentile boundary checks
# ---------------------------------------------------------------------------

def test_score_from_percentile_boundaries():
    """Verify score formula ranges match spec."""
    # Leading (pct > 66): score in [60, 100]
    s_top = _score_from_percentile(100.0)
    assert 60.0 <= s_top <= 100.0

    s_high = _score_from_percentile(80.0)
    assert 60.0 <= s_high <= 100.0

    # Lagging (pct < 33): score in [0, 40]
    s_bottom = _score_from_percentile(0.0)
    assert 0.0 <= s_bottom <= 40.0

    s_low = _score_from_percentile(20.0)
    assert 0.0 <= s_low <= 40.0

    # Middle (33–66): score in [40, 70]
    s_mid = _score_from_percentile(50.0)
    assert 40.0 <= s_mid <= 70.0


# ---------------------------------------------------------------------------
# Bonus: empty universe returns empty list
# ---------------------------------------------------------------------------

def test_empty_universe_returns_empty_list():
    """collect_sector_rotation_signals([]) → []"""
    signals = collect_sector_rotation_signals([])
    assert signals == []


# ---------------------------------------------------------------------------
# Sector name normalization
# ---------------------------------------------------------------------------

def test_variant_sector_names_are_normalized():
    """yfinance/GICS variant sector names must normalize to SECTOR_ETF_MAP keys."""
    universe = [
        _make_universe("AMZN", "Consumer Cyclical"),       # → Consumer Discretionary
        _make_universe("PG", "Consumer Defensive"),         # → Consumer Staples
        _make_universe("O", "Real Estate"),                 # → Real Estate (already a key)
        _make_universe("MSFT", "Information Technology"),   # → Technology
        _make_universe("JNJ", "Health Care"),               # → Healthcare
        _make_universe("GS", "Financial Services"),         # → Financials
        _make_universe("FCX", "Basic Materials"),           # → Materials
    ]
    close_map = _build_mock_close_map({s: float(i) for i, s in enumerate(SECTOR_ETF_MAP)})
    with patch(
        "tradingagents.dealflow.sources.sector_rotation._download_sector_closes",
        return_value=close_map,
    ):
        signals = collect_sector_rotation_signals(universe)
    assert len(signals) == 7
    for sig in signals:
        assert sig["source_status"] == "OK"
        assert sig["source_name"] != "sector_rotation:unknown"
