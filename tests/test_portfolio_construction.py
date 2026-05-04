"""Tests for conviction-tiered portfolio construction engine."""

from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

from tradingagents.graph.paper_execution import (
    _conviction_weights,
    _tier_for_score,
    build_portfolio_plan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(symbol: str, score: float, confidence: int = 5) -> dict:
    """Create a minimal row matching build_portfolio_plan's eligible format."""
    return {
        "symbol": symbol,
        "aeternus_score": score,
        "confidence": confidence,
        "weight_signal": max(0.0, score - 50.0) * max(1.0, float(confidence)),
    }


def _make_prices(symbols: list[str], n_days: int = 60, vols: dict | None = None):
    """Build a synthetic close-price DataFrame for testing.

    Args:
        symbols: Ticker list.
        n_days: Number of trading days.
        vols: Optional {symbol: annualized_vol} for controlling per-symbol vol.
    """
    np.random.seed(42)
    # Use start-based range to guarantee exactly n_days dates
    dates = pd.bdate_range(start="2025-01-02", periods=n_days)
    data = {}
    for sym in symbols:
        daily_vol = (vols or {}).get(sym, 0.20) / np.sqrt(252)
        returns = np.random.normal(0.0005, daily_vol, n_days)
        prices = 100.0 * np.exp(np.cumsum(returns))
        data[sym] = prices
    return pd.DataFrame(data, index=dates)


def _patch_prices(symbols, prices_df):
    """Return a context-manager that patches _fetch_price_matrix to return prices_df."""
    return patch(
        "tradingagents.graph.paper_execution._fetch_price_matrix",
        return_value=prices_df,
    )


# ---------------------------------------------------------------------------
# 1. Tier mapping
# ---------------------------------------------------------------------------

class TestTierForScore:
    def test_marginal_low(self):
        w, tier = _tier_for_score(62.0)
        assert tier == "MARGINAL"
        assert abs(w - 0.05) < 1e-4

    def test_marginal_mid(self):
        w, tier = _tier_for_score(64.0)
        assert tier == "MARGINAL"
        assert 0.05 < w < 0.10

    def test_moderate(self):
        w, tier = _tier_for_score(69.0)
        assert tier == "MODERATE"
        assert 0.10 <= w <= 0.18

    def test_high(self):
        w, tier = _tier_for_score(76.0)
        assert tier == "HIGH"
        assert 0.18 <= w <= 0.25

    def test_conviction(self):
        w, tier = _tier_for_score(85.0)
        assert tier == "CONVICTION"
        assert abs(w - 0.25) < 1e-4


# ---------------------------------------------------------------------------
# 2. Single marginal position → small allocation, ~94% to QQQ
# ---------------------------------------------------------------------------

class TestSingleMarginal:
    def test_single_marginal(self):
        rows = [_row("BMY", 62.5)]
        prices = _make_prices(["BMY"])
        with _patch_prices(["BMY"], prices):
            weights, meta = _conviction_weights(rows)
        assert len(weights) == 1
        assert weights[0] < 0.12  # Should be ~5-10%
        assert weights[0] > 0.02
        assert meta["tiers"]["BMY"] == "MARGINAL"


# ---------------------------------------------------------------------------
# 3. Three marginal positions → sum ~20%, ~80% QQQ
# ---------------------------------------------------------------------------

class TestThreeMarginal:
    def test_sum_well_below_one(self):
        rows = [_row("BMY", 63.2), _row("TSM", 62.6), _row("JNJ", 62.4)]
        prices = _make_prices(["BMY", "TSM", "JNJ"])
        with _patch_prices(["BMY", "TSM", "JNJ"], prices):
            weights, meta = _conviction_weights(rows)
        total = sum(weights)
        assert total < 0.40  # Well under 1.0
        assert total > 0.05  # But not negligible
        for tier in meta["tiers"].values():
            assert tier == "MARGINAL"


# ---------------------------------------------------------------------------
# 4. Mix of tiers → HIGH gets most capital
# ---------------------------------------------------------------------------

class TestMixedTiers:
    def test_high_gets_most(self):
        rows = [_row("NVDA", 75.0), _row("MSFT", 68.0), _row("BMY", 63.0)]
        prices = _make_prices(["NVDA", "MSFT", "BMY"])
        with _patch_prices(["NVDA", "MSFT", "BMY"], prices):
            weights, meta = _conviction_weights(rows)
        assert meta["tiers"]["NVDA"] == "HIGH"
        assert meta["tiers"]["MSFT"] == "MODERATE"
        assert meta["tiers"]["BMY"] == "MARGINAL"
        # NVDA should have highest weight (before vol adjustment could swap)
        # At minimum, base_weight for NVDA > MSFT > BMY
        pre = meta["pre_adj_weights"]
        assert pre["NVDA"] > pre["MSFT"] > pre["BMY"]


# ---------------------------------------------------------------------------
# 5. Vol adjustment — low-vol scaled up, high-vol scaled down
# ---------------------------------------------------------------------------

class TestVolAdjustment:
    def test_low_vol_gets_more(self):
        rows = [_row("LOW", 68.0), _row("HIGH", 68.0)]
        # LOW has 10% vol, HIGH has 40% vol → median = 25%
        prices = _make_prices(["LOW", "HIGH"], vols={"LOW": 0.10, "HIGH": 0.40})
        with _patch_prices(["LOW", "HIGH"], prices):
            weights, meta = _conviction_weights(rows)
        # Both have same score → same base weight.
        # LOW vol should get scaled up, HIGH vol scaled down.
        assert weights[0] > weights[1]


# ---------------------------------------------------------------------------
# 6. Correlation penalty — two 0.9-correlated positions get reduced
# ---------------------------------------------------------------------------

class TestCorrelationPenalty:
    def test_correlated_pair_reduced(self):
        rows = [_row("A", 70.0), _row("B", 70.0)]
        # Build highly correlated prices
        np.random.seed(42)
        n = 60
        dates = pd.bdate_range(start="2025-01-02", periods=n)
        base = np.random.normal(0, 0.01, n)
        prices_a = 100 * np.exp(np.cumsum(base))
        prices_b = 100 * np.exp(np.cumsum(base + np.random.normal(0, 0.001, n)))
        prices_df = pd.DataFrame({"A": prices_a, "B": prices_b}, index=dates)

        with _patch_prices(["A", "B"], prices_df):
            weights_corr, meta_corr = _conviction_weights(rows)

        # Now with uncorrelated prices
        uncorr_prices = _make_prices(["A", "B"])
        with _patch_prices(["A", "B"], uncorr_prices):
            weights_uncorr, _ = _conviction_weights(rows)

        # Correlated pair should have lower total weight
        assert sum(weights_corr) < sum(weights_uncorr)


# ---------------------------------------------------------------------------
# 7. Cap enforcement — score 85 capped at 25%
# ---------------------------------------------------------------------------

class TestCapEnforcement:
    def test_25_pct_cap(self):
        rows = [_row("MEGA", 85.0)]
        prices = _make_prices(["MEGA"], vols={"MEGA": 0.05})  # Very low vol → would scale up
        with _patch_prices(["MEGA"], prices):
            weights, meta = _conviction_weights(rows, max_weight_per_position=0.25)
        assert weights[0] <= 0.25 + 1e-6


# ---------------------------------------------------------------------------
# 8. Fallback on price error — uses base weights when yfinance fails
# ---------------------------------------------------------------------------

class TestFallbackOnPriceError:
    def test_none_prices_uses_base(self):
        rows = [_row("X", 68.0), _row("Y", 72.0)]
        with _patch_prices(["X", "Y"], None):
            weights, meta = _conviction_weights(rows)
        # Should still get weights (base tier weights, no vol/corr adjustments)
        assert len(weights) == 2
        assert all(w > 0 for w in weights)
        assert meta["vol_data"] == {}


# ---------------------------------------------------------------------------
# 9. Total <= 1.0 — even with many HIGH positions
# ---------------------------------------------------------------------------

class TestTotalCap:
    def test_many_high_positions(self):
        rows = [_row(f"T{i}", 76.0) for i in range(10)]
        syms = [f"T{i}" for i in range(10)]
        prices = _make_prices(syms)
        with _patch_prices(syms, prices):
            weights, meta = _conviction_weights(rows)
        assert sum(weights) <= 1.0 + 1e-6


# ---------------------------------------------------------------------------
# 10. Empty input → 100% QQQ
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_empty_rows(self):
        weights, meta = _conviction_weights([])
        assert weights == []
        assert meta["tiers"] == {}


# ---------------------------------------------------------------------------
# 11. Allocation metadata present on orders via build_portfolio_plan
# ---------------------------------------------------------------------------

class TestBuildPortfolioPlanMetadata:
    def test_conviction_fields_on_orders(self):
        """Verify build_portfolio_plan attaches conviction metadata to orders."""
        batch = {
            "date": "2026-03-04",
            "run_id": "test-run",
            "items": [
                {
                    "symbol": "BMY",
                    "status": "SUCCESS",
                    "recommendation": "BUY",
                    "aeternus_score": 63.2,
                    "confidence": 5,
                    "lane": "CORE",
                    "research_playbook": "N/A",
                    "dominant_signal_family": "price_momentum",
                },
            ],
        }

        # Mock both _fetch_reference_price_from_market and _fetch_price_matrix
        prices = _make_prices(["BMY"])
        with (
            patch(
                "tradingagents.graph.paper_execution._fetch_reference_price_from_market",
                return_value=50.0,
            ),
            _patch_prices(["BMY"], prices),
        ):
            plan = build_portfolio_plan(
                batch_summary=batch,
                capital_usd=55000.0,
                max_positions=10,
                min_score=62.0,
                min_confidence=3,
            )

        # Find the BMY order (not QQQ)
        bmy_orders = [o for o in plan["orders"] if o["symbol"] == "BMY"]
        assert len(bmy_orders) == 1
        order = bmy_orders[0]

        # Conviction metadata fields present
        assert order["conviction_tier"] == "MARGINAL"
        assert order["base_weight"] > 0
        assert order["vol_20d_annualized"] >= 0
        assert "correlation_max" in order
        assert order["final_weight"] > 0

        # Allocation summary present on plan
        summary = plan["allocation_summary"]
        assert summary["total_conviction_pct"] < 50.0  # Single marginal → small %
        assert summary["v3_remainder_pct"] > 50.0
        assert "MARGINAL" in summary["tier_distribution"]

        # V3 residual should be large (most capital stays in QQQ)
        assert plan["v3_residual_usd"] > 40000.0


# ---------------------------------------------------------------------------
# 12. Kelly sizing scales weights down when track record has edge
# ---------------------------------------------------------------------------

class TestKellySizing:
    def test_kelly_scales_weights_down(self):
        """When EquityCurveEngine returns a track record with edge,
        Kelly sizing should scale conviction weights below their
        un-Kelly'd values."""
        rows = [_row("NVDA", 75.0), _row("MSFT", 68.0)]
        prices = _make_prices(["NVDA", "MSFT"])

        # Get baseline weights without Kelly
        with _patch_prices(["NVDA", "MSFT"], prices):
            weights_base, _ = _conviction_weights(rows)

        # Simulate Kelly path through build_portfolio_plan
        batch = {
            "date": "2026-03-04",
            "run_id": "test-kelly",
            "items": [
                {
                    "symbol": "NVDA",
                    "status": "SUCCESS",
                    "recommendation": "BUY",
                    "aeternus_score": 75.0,
                    "confidence": 5,
                    "lane": "CORE",
                    "research_playbook": "N/A",
                    "dominant_signal_family": "price_momentum",
                },
                {
                    "symbol": "MSFT",
                    "status": "SUCCESS",
                    "recommendation": "BUY",
                    "aeternus_score": 68.0,
                    "confidence": 5,
                    "lane": "CORE",
                    "research_playbook": "N/A",
                    "dominant_signal_family": "price_momentum",
                },
            ],
        }

        # Mock equity curve to return a moderate edge (60% win, 2:1 ratio)
        mock_curve = {
            "stats": {
                "trade_count": 25,
                "win_rate": 0.60,
                "avg_win_pct": 8.0,
                "avg_loss_pct": -4.0,
            }
        }
        mock_ec = MagicMock()
        mock_ec.build.return_value = mock_curve

        with (
            patch(
                "tradingagents.graph.paper_execution._fetch_reference_price_from_market",
                return_value=100.0,
            ),
            _patch_prices(["NVDA", "MSFT"], prices),
            patch(
                "tradingagents.graph.equity_curve.EquityCurveEngine",
                return_value=mock_ec,
            ),
        ):
            plan = build_portfolio_plan(
                batch_summary=batch,
                capital_usd=100000.0,
                max_positions=10,
                min_score=60.0,
                min_confidence=3,
            )

        # Verify Kelly fraction is < 1.0 (quarter-Kelly of ~0.10)
        alloc = plan.get("allocation_summary", {})
        kelly = alloc.get("kelly", {})
        assert kelly.get("trade_count", 0) == 25
        assert kelly.get("kelly_fraction", 1.0) < 1.0
        assert kelly.get("win_rate", 0.0) == 0.60

        # Find the conviction orders (not QQQ)
        conviction_orders = [
            o for o in plan["orders"]
            if o["symbol"] in ("NVDA", "MSFT")
        ]
        assert len(conviction_orders) == 2

        # Each conviction order weight should be < base weight
        for order in conviction_orders:
            sym = order["symbol"]
            base_idx = 0 if sym == "NVDA" else 1
            assert order["final_weight"] < weights_base[base_idx] + 1e-6
