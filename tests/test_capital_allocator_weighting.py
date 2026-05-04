"""Tests for tradingagents.capital_allocator.weighting."""
from __future__ import annotations

import math
from unittest.mock import patch

import numpy as np
import pytest

from tradingagents.capital_allocator.weighting import (
    _apply_weight_cap,
    risk_parity_weights,
    score_to_weights,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rating(ticker: str, score: float, confidence: int) -> dict:
    return {"ticker": ticker, "aeternus_score": score, "confidence": confidence}


def _identity_cov(symbols: list[str]) -> dict[str, dict[str, float]]:
    """Return a covariance matrix equal to the identity (each asset variance=1, cov=0)."""
    return {si: {sj: 1.0 if si == sj else 0.0 for sj in symbols} for si in symbols}


# ---------------------------------------------------------------------------
# score_to_weights
# ---------------------------------------------------------------------------

class TestScoreToWeights:

    def test_empty_ratings_returns_empty(self):
        assert score_to_weights([]) == {}

    def test_all_below_min_score_returns_empty(self):
        ratings = [
            _rating("AAPL", 30.0, 3),
            _rating("MSFT", 39.9, 4),
        ]
        assert score_to_weights(ratings, min_score=40.0) == {}

    def test_single_ticker_gets_weight_one(self):
        ratings = [_rating("AAPL", 75.0, 4)]
        weights = score_to_weights(ratings)
        assert set(weights.keys()) == {"AAPL"}
        assert math.isclose(weights["AAPL"], 1.0, abs_tol=1e-9)

    def test_two_equal_tickers_roughly_equal_weights(self):
        ratings = [
            _rating("AAPL", 70.0, 3),
            _rating("MSFT", 70.0, 3),
        ]
        weights = score_to_weights(ratings)
        assert set(weights.keys()) == {"AAPL", "MSFT"}
        assert math.isclose(weights["AAPL"], weights["MSFT"], rel_tol=1e-6)
        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)

    def test_higher_score_gets_higher_weight(self):
        ratings = [
            _rating("LOW", 50.0, 3),
            _rating("HIGH", 90.0, 3),
        ]
        # Disable max_weight cap so the raw score ratio is preserved in output weights.
        weights = score_to_weights(ratings, max_weight=1.0)
        assert weights["HIGH"] > weights["LOW"]
        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)

    def test_confidence_multiplier_proportional(self):
        # Same score, confidence 2 vs 4 — weight should be in 1:2 ratio before capping.
        ratings = [
            _rating("LOW_CONF", 60.0, 2),
            _rating("HIGH_CONF", 60.0, 4),
        ]
        weights = score_to_weights(ratings, max_weight=1.0)  # disable cap
        ratio = weights["HIGH_CONF"] / weights["LOW_CONF"]
        assert math.isclose(ratio, 2.0, rel_tol=1e-6)

    def test_max_weight_cap_applied(self):
        # GIANT's uncapped weight is ~0.627.  With cap=0.35 and 3 tickers, the
        # cap IS achievable (3 * 0.35 = 1.05 > 1.0 means there's room to absorb
        # the excess in the two smaller tickers) and the algorithm converges.
        ratings = [
            _rating("GIANT", 99.0, 5),
            _rating("MID", 65.0, 3),
            _rating("SMALL", 50.0, 2),
        ]
        weights = score_to_weights(ratings, min_score=40.0, max_weight=0.35)
        # Allow small floating-point tolerance from iterative redistribution.
        assert weights["GIANT"] <= 0.35 + 1e-6
        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-6)

    def test_weights_sum_to_one(self):
        ratings = [
            _rating("A", 55.0, 3),
            _rating("B", 70.0, 4),
            _rating("C", 85.0, 5),
            _rating("D", 42.0, 2),
        ]
        weights = score_to_weights(ratings)
        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)

    def test_ticker_at_min_score_is_included(self):
        # Ticker with score == min_score must NOT be filtered out.
        ratings = [
            _rating("EXACT", 40.0, 3),
            _rating("BELOW", 39.9, 3),
        ]
        weights = score_to_weights(ratings, min_score=40.0)
        assert "EXACT" in weights
        assert "BELOW" not in weights

    def test_filtered_tickers_absent_from_result(self):
        ratings = [
            _rating("PASS", 60.0, 3),
            _rating("FAIL", 20.0, 5),
        ]
        weights = score_to_weights(ratings, min_score=40.0)
        assert "FAIL" not in weights
        assert "PASS" in weights


# ---------------------------------------------------------------------------
# risk_parity_weights
# ---------------------------------------------------------------------------

class TestRiskParityWeights:

    def test_empty_symbols_returns_empty(self):
        assert risk_parity_weights([], {}) == {}

    def test_single_symbol_returns_one(self):
        cov = {"AAPL": {"AAPL": 0.04}}
        result = risk_parity_weights(["AAPL"], cov)
        assert result == {"AAPL": 1.0}

    def test_identity_covariance_gives_equal_weights(self):
        symbols = ["A", "B", "C", "D"]
        cov = _identity_cov(symbols)
        weights = risk_parity_weights(symbols, cov, max_weight=1.0)
        assert set(weights.keys()) == set(symbols)
        for sym in symbols:
            assert math.isclose(weights[sym], 0.25, abs_tol=1e-4)
        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)

    def test_high_variance_asset_gets_lower_weight(self):
        # Asset B has 4x the variance of A. Risk parity should underweight B.
        symbols = ["A", "B"]
        cov = {
            "A": {"A": 0.01, "B": 0.0},
            "B": {"B": 0.04, "A": 0.0},
        }
        weights = risk_parity_weights(symbols, cov, max_weight=1.0)
        assert weights["A"] > weights["B"]
        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)

    def test_weights_sum_to_one(self):
        symbols = ["X", "Y", "Z"]
        cov = _identity_cov(symbols)
        weights = risk_parity_weights(symbols, cov)
        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)

    def test_max_weight_cap_applied(self):
        # With a 2-asset identity covariance and a 0.30 cap, each should be 0.30
        # after capping (equal weights → both at 0.5 → cap forces redistribution to 0.5).
        # Actually equal weights = 0.5 each, and cap=0.30 → both get capped to 0.30 → renorm to 0.5.
        # So this test uses a skewed covariance to create a dominant asset, then caps it.
        symbols = ["A", "B"]
        cov = {
            "A": {"A": 0.0001, "B": 0.0},  # very low variance → gets large ERC weight
            "B": {"B": 0.25, "A": 0.0},    # very high variance → gets small ERC weight
        }
        weights = risk_parity_weights(symbols, cov, max_weight=0.60)
        for sym in symbols:
            assert weights[sym] <= 0.60 + 1e-9
        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)

    def test_fallback_to_equal_weights_on_failure(self):
        symbols = ["A", "B", "C"]
        cov = _identity_cov(symbols)
        # minimize is imported inside risk_parity_weights, so patch the source module.
        with patch("scipy.optimize.minimize", side_effect=RuntimeError("boom")):
            weights = risk_parity_weights(symbols, cov, fallback_to_equal=True)
        # Should fall back to equal weights (1/3 each).
        assert set(weights.keys()) == set(symbols)
        for sym in symbols:
            assert math.isclose(weights[sym], 1.0 / 3.0, abs_tol=1e-4)

    def test_no_fallback_returns_empty_on_failure(self):
        symbols = ["A", "B"]
        cov = _identity_cov(symbols)
        with patch("scipy.optimize.minimize", side_effect=RuntimeError("boom")):
            result = risk_parity_weights(symbols, cov, fallback_to_equal=False)
        assert result == {}
