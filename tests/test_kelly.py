"""Tests for tradingagents.capital_allocator.kelly."""

import pytest


class TestComputeKellyFraction:
    def test_insufficient_trades_returns_zero(self):
        from tradingagents.capital_allocator.kelly import compute_kelly_fraction
        result = compute_kelly_fraction(
            win_rate=0.6, avg_win_pct=8.0, avg_loss_pct=-4.0,
            trade_count=5, min_trades=10,
        )
        assert result == 0.0

    def test_basic_kelly(self):
        from tradingagents.capital_allocator.kelly import compute_kelly_fraction
        # 60% win rate, 2:1 win/loss ratio
        result = compute_kelly_fraction(
            win_rate=0.6, avg_win_pct=8.0, avg_loss_pct=-4.0,
            trade_count=20,
        )
        # f* = (0.6*2 - 0.4)/2 = 0.4, * 0.25 = 0.10
        assert result == pytest.approx(0.10, abs=0.01)

    def test_losing_system_floors_at_001(self):
        from tradingagents.capital_allocator.kelly import compute_kelly_fraction
        # 30% win rate, 1:1 ratio = negative Kelly
        result = compute_kelly_fraction(
            win_rate=0.3, avg_win_pct=5.0, avg_loss_pct=-5.0,
            trade_count=20,
        )
        assert result == 0.01

    def test_avg_loss_zero_returns_fractional(self):
        from tradingagents.capital_allocator.kelly import compute_kelly_fraction
        # All wins, no losses recorded
        result = compute_kelly_fraction(
            win_rate=1.0, avg_win_pct=5.0, avg_loss_pct=0.0,
            trade_count=15,
        )
        assert result == 0.25

    def test_breakeven_system(self):
        from tradingagents.capital_allocator.kelly import compute_kelly_fraction
        # 50% win, 1:1 = f*=0
        result = compute_kelly_fraction(
            win_rate=0.5, avg_win_pct=5.0, avg_loss_pct=-5.0,
            trade_count=20,
        )
        assert result == 0.01  # Floors at 0.01

    def test_high_edge_system(self):
        from tradingagents.capital_allocator.kelly import compute_kelly_fraction
        # 70% win, 3:1 ratio = strong edge
        result = compute_kelly_fraction(
            win_rate=0.7, avg_win_pct=9.0, avg_loss_pct=-3.0,
            trade_count=30,
        )
        assert result > 0.10  # Should be meaningfully positive

    def test_custom_fractional(self):
        from tradingagents.capital_allocator.kelly import compute_kelly_fraction
        half_kelly = compute_kelly_fraction(
            win_rate=0.6, avg_win_pct=8.0, avg_loss_pct=-4.0,
            trade_count=20, fractional=0.5,
        )
        quarter_kelly = compute_kelly_fraction(
            win_rate=0.6, avg_win_pct=8.0, avg_loss_pct=-4.0,
            trade_count=20, fractional=0.25,
        )
        assert half_kelly > quarter_kelly


class TestApplyKellySizing:
    def test_basic_scaling(self):
        """Test that Kelly sizing scales weights proportionally and sums to kelly_fraction."""
        from tradingagents.capital_allocator.kelly import apply_kelly_sizing
        weights = {"AAPL": 0.4, "MSFT": 0.3, "XOM": 0.3}
        result = apply_kelly_sizing(weights, kelly_fraction=0.10)
        
        # Result should sum to kelly_fraction (10% of portfolio)
        assert sum(result.values()) == pytest.approx(0.10, abs=0.01)
        
        # All positions should be ≤ max_position_pct (15% by default)
        assert all(v <= 0.15 for v in result.values())
        
        # Proportions should be preserved: AAPL gets 40% of allocation, etc.
        assert result["AAPL"] == pytest.approx(0.04, abs=0.001)
        assert result["MSFT"] == pytest.approx(0.03, abs=0.001)
        assert result["XOM"] == pytest.approx(0.03, abs=0.001)

    def test_zero_kelly_returns_original(self):
        from tradingagents.capital_allocator.kelly import apply_kelly_sizing
        weights = {"AAPL": 0.5, "MSFT": 0.5}
        result = apply_kelly_sizing(weights, kelly_fraction=0.0)
        assert result == weights

    def test_empty_weights(self):
        from tradingagents.capital_allocator.kelly import apply_kelly_sizing
        result = apply_kelly_sizing({}, kelly_fraction=0.10)
        assert result == {}

    def test_cap_at_max_position(self):
        """Test that individual position caps are enforced within Kelly allocation."""
        from tradingagents.capital_allocator.kelly import apply_kelly_sizing
        weights = {"AAPL": 0.9, "MSFT": 0.1}
        result = apply_kelly_sizing(weights, kelly_fraction=0.25, max_position_pct=0.15)
        
        # Scaled: AAPL=0.225, MSFT=0.025 (sum=0.25)
        # Capped: AAPL=0.15, MSFT=0.025 (sum=0.175)
        # Renormalized to sum to 0.25: AAPL≈0.214, MSFT≈0.036
        
        assert sum(result.values()) == pytest.approx(0.25, abs=0.01)
        # No individual position should exceed its cap
        assert all(v <= 0.15 for v in result.values())
        
    def test_kelly_reduces_concentration(self):
        """Test that Kelly sizing reduces portfolio concentration."""
        from tradingagents.capital_allocator.kelly import apply_kelly_sizing
        weights = {"BIG": 0.6, "SMALL": 0.4}
        kelly_025 = apply_kelly_sizing(weights, kelly_fraction=0.25)
        
        # With kelly_fraction=0.25, portfolio only deploys 25% of capital
        assert sum(kelly_025.values()) == pytest.approx(0.25, abs=0.01)
        
        # BIG gets 60% of 25% = 15% of total portfolio
        assert kelly_025["BIG"] == pytest.approx(0.15, abs=0.001)
        # SMALL gets 40% of 25% = 10% of total portfolio
        assert kelly_025["SMALL"] == pytest.approx(0.10, abs=0.001)
