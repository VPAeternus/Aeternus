"""
test_triple_barrier.py — Tests for tradingagents.graph.triple_barrier

All DataFrames are constructed inline. No external fixtures.
"""

import math
import sys
import types
import pytest
import pandas as pd

# Stub chromadb before the import chain loads it (pydantic v1 incompatible with Python 3.14).
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.graph.triple_barrier import (
    TrailingStop,
    TripleBarrierConfig,
    simulate_position,
    simulate_signals,
    summarize_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(rows):
    """Build a DataFrame from a list of (open, high, low, close) tuples."""
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def _flat_df(price: float, n: int) -> pd.DataFrame:
    """All bars flat at `price`."""
    return _make_df([(price, price, price, price)] * n)


def _config(sl=0.05, tp=0.10, time_limit=None, trailing=None):
    return TripleBarrierConfig(
        stop_loss_pct=sl,
        take_profit_pct=tp,
        time_limit_bars=time_limit,
        trailing_stop=trailing,
    )


# ---------------------------------------------------------------------------
# 1. Basic long stop-loss trigger
# ---------------------------------------------------------------------------

class TestLongStopLoss:
    def test_stop_triggered_by_low(self):
        """Stop-loss hits when bar low crosses below stop_price."""
        # Entry at close=100. SL=5% → stop at 95.
        # Bar 1: high=102, low=94 → stop triggered.
        df = _make_df([
            (100, 100, 100, 100),  # entry bar
            (101, 102, 94, 101),   # low=94 < 95 → stop
            (101, 103, 99, 103),   # would not trigger
        ])
        cfg = _config(sl=0.05, tp=0.20)
        result = simulate_position(df, entry_idx=0, side="long", config=cfg)
        assert result["exit_type"] == "stop_loss"
        assert result["exit_idx"] == 1
        assert result["bars_held"] == 1
        assert abs(result["exit_price"] - 95.0) < 1e-9
        assert result["pnl_pct"] < 0

    def test_stop_not_triggered_when_low_above_stop(self):
        """Stop-loss does NOT trigger when bar low stays above stop level."""
        # Entry=100, SL=5% → stop=95. Low=96 each bar — never triggered.
        rows = [(100, 100, 100, 100)] + [(99, 103, 96, 102)] * 3
        df = _make_df(rows)
        cfg = _config(sl=0.05, tp=0.20, time_limit=3)
        result = simulate_position(df, entry_idx=0, side="long", config=cfg)
        assert result["exit_type"] in ("time_limit", "end_of_data", "take_profit")
        assert result["exit_type"] != "stop_loss"


# ---------------------------------------------------------------------------
# 2. Basic long take-profit trigger
# ---------------------------------------------------------------------------

class TestLongTakeProfit:
    def test_tp_triggered_by_high(self):
        """Take-profit triggers when bar high crosses above tp_price."""
        # Entry=100, TP=10% → tp=110. Bar 1: high=111 → TP.
        df = _make_df([
            (100, 100, 100, 100),
            (101, 111, 99, 109),
        ])
        cfg = _config(sl=0.05, tp=0.10)
        result = simulate_position(df, entry_idx=0, side="long", config=cfg)
        assert result["exit_type"] == "take_profit"
        assert result["exit_idx"] == 1
        assert abs(result["exit_price"] - 110.0) < 1e-9
        assert result["pnl_pct"] > 0

    def test_tp_pnl_correct(self):
        """TP pnl_pct = (tp_price - entry) / entry."""
        df = _make_df([
            (50, 50, 50, 50),
            (51, 56, 49, 55),  # high=56 > tp=55
        ])
        cfg = _config(sl=0.05, tp=0.10)  # tp at 55
        result = simulate_position(df, entry_idx=0, side="long", config=cfg)
        assert result["exit_type"] == "take_profit"
        expected_pnl = (55.0 - 50.0) / 50.0
        assert abs(result["pnl_pct"] - expected_pnl) < 1e-9


# ---------------------------------------------------------------------------
# 3. Time limit exit
# ---------------------------------------------------------------------------

class TestTimeLimitExit:
    def test_time_limit_triggers_at_correct_bar(self):
        """After time_limit_bars bars, exit at last bar's close."""
        # 6 bars total, entry at 0, time_limit=3 → exit at bar 3 close.
        rows = [(100, 100, 100, 100)] + [(100, 101, 99, 100 + i) for i in range(5)]
        df = _make_df(rows)
        cfg = _config(sl=0.20, tp=0.20, time_limit=3)
        result = simulate_position(df, entry_idx=0, side="long", config=cfg)
        assert result["exit_type"] == "time_limit"
        assert result["exit_idx"] == 3
        assert result["bars_held"] == 3

    def test_time_limit_exit_price_is_close(self):
        """Exit price at time limit equals close of the exit bar."""
        rows = [(100, 100, 100, 100)] + [(100, 102, 99, 105 + i) for i in range(4)]
        df = _make_df(rows)
        cfg = _config(sl=0.30, tp=0.30, time_limit=2)
        result = simulate_position(df, entry_idx=0, side="long", config=cfg)
        assert result["exit_type"] == "time_limit"
        assert result["exit_price"] == df.iloc[result["exit_idx"]]["close"]


# ---------------------------------------------------------------------------
# 4. Trailing stop — activation and trail
# ---------------------------------------------------------------------------

class TestTrailingStop:
    def test_trailing_stop_activates_and_trails(self):
        """Trailing stop activates once price moves activation_pct in-direction, then trails."""
        # Entry=100, activation=5% → activates when high >= 105. delta=3% → trail = peak*(1-0.03).
        # Bar 1: high=106 → activates, peak=106, trail=106*0.97=102.82
        # Bar 2: high=108 → peak=108, trail=108*0.97=104.76
        # Bar 3: high=107, low=104 → low=104 < trail=104.76 → trailing stop triggers.
        df = _make_df([
            (100, 100, 100, 100),  # entry
            (101, 106, 100, 105),  # activates trail
            (106, 108, 106, 107),  # peak=108, trail=104.76
            (107, 107, 104, 106),  # low=104 < 104.76 → exit
            (106, 110, 105, 109),  # not reached
        ])
        ts = TrailingStop(activation_pct=0.05, delta_pct=0.03)
        cfg = _config(sl=0.30, tp=0.30, trailing=ts)
        result = simulate_position(df, entry_idx=0, side="long", config=cfg)
        assert result["exit_type"] == "trailing_stop"
        assert result["exit_idx"] == 3
        assert result["pnl_pct"] > 0  # still profitable

    def test_trailing_stop_does_not_activate_early(self):
        """Trailing stop does not activate before activation_pct is reached."""
        # Price never gets to activation threshold, so trail never activates.
        # Fixed SL should catch it instead.
        df = _make_df([
            (100, 100, 100, 100),  # entry
            (100, 103, 100, 102),  # high=103, activation needs 105
            (102, 104, 100, 103),  # high=104, still below 105
            (103, 104, 92, 93),    # low=92 → fixed stop at 95 triggers
        ])
        ts = TrailingStop(activation_pct=0.05, delta_pct=0.02)
        cfg = _config(sl=0.05, tp=0.30, trailing=ts)
        result = simulate_position(df, entry_idx=0, side="long", config=cfg)
        # Should be stop_loss (fixed), not trailing_stop
        assert result["exit_type"] == "stop_loss"
        assert result["exit_idx"] == 3

    def test_trailing_stop_short_side(self):
        """Trailing stop works correctly for short positions."""
        # Entry=100 short. activation=5% → activates when low <= 95. delta=2% → trail = trough*(1+0.02).
        # Bar 1: low=94 → activates (just_activated, skip check). trough=94, trail=94*1.02=95.88.
        # Bar 2: high=93, low=93. trail update: 93 < trough=94 → trough=93, trail=93*1.02=94.86.
        #         check: high=93 < 94.86 → no trigger.
        # Bar 3: high=95 → high=95 >= trail=94.86 → trailing stop triggers.
        df = _make_df([
            (100, 100, 100, 100),
            (98, 94, 94, 94),   # low=94 activates (just_activated). trough=94, trail=95.88.
            (94, 93, 93, 93),   # low=93 < trough=94 → trough=93, trail=94.86. high=93 < 94.86 → no trigger.
            (93, 95, 93, 94),   # high=95 > trail=94.86 → trailing stop fires here.
            (94, 97, 93, 95),   # not reached
        ])
        ts = TrailingStop(activation_pct=0.05, delta_pct=0.02)
        cfg = _config(sl=0.30, tp=0.30, trailing=ts)
        result = simulate_position(df, entry_idx=0, side="short", config=cfg)
        assert result["exit_type"] == "trailing_stop"
        assert result["exit_idx"] == 3
        assert result["pnl_pct"] > 0


# ---------------------------------------------------------------------------
# 5. Short side logic
# ---------------------------------------------------------------------------

class TestShortSide:
    def test_short_stop_loss_triggers_on_high(self):
        """For short, stop-loss triggers when bar high >= stop_price."""
        # Entry=100 short, SL=5% → stop=105. Bar 1: high=106 → SL.
        df = _make_df([
            (100, 100, 100, 100),
            (101, 106, 100, 105),
        ])
        cfg = _config(sl=0.05, tp=0.10)
        result = simulate_position(df, entry_idx=0, side="short", config=cfg)
        assert result["exit_type"] == "stop_loss"
        assert result["pnl_pct"] < 0

    def test_short_take_profit_triggers_on_low(self):
        """For short, take-profit triggers when bar low <= tp_price."""
        # Entry=100 short, TP=10% → tp=90. Bar 1: low=89 → TP.
        df = _make_df([
            (100, 100, 100, 100),
            (98, 99, 89, 90),
        ])
        cfg = _config(sl=0.05, tp=0.10)
        result = simulate_position(df, entry_idx=0, side="short", config=cfg)
        assert result["exit_type"] == "take_profit"
        assert result["exit_price"] == 90.0
        assert result["pnl_pct"] > 0

    def test_short_pnl_sign_correct(self):
        """Short PnL is positive when price falls."""
        df = _make_df([
            (100, 100, 100, 100),
            (91, 92, 88, 89),  # low=88 < tp=90 → TP
        ])
        cfg = _config(sl=0.10, tp=0.10)
        result = simulate_position(df, entry_idx=0, side="short", config=cfg)
        assert result["pnl_pct"] > 0
        assert result["exit_type"] == "take_profit"


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_entry_at_last_bar_returns_end_of_data(self):
        """Entry at the very last bar returns end_of_data immediately."""
        df = _flat_df(100.0, 3)
        cfg = _config()
        result = simulate_position(df, entry_idx=2, side="long", config=cfg)
        assert result["exit_type"] == "end_of_data"
        assert result["bars_held"] == 0
        assert result["pnl_pct"] == 0.0

    def test_entry_at_second_to_last_bar_runs_one_bar(self):
        """Entry one bar before the end — exactly one bar to evaluate."""
        df = _make_df([
            (100, 100, 100, 100),
            (100, 100, 100, 100),
            (100, 115, 100, 112),  # high=115 > tp=110
        ])
        cfg = _config(sl=0.05, tp=0.10)
        result = simulate_position(df, entry_idx=1, side="long", config=cfg)
        assert result["exit_type"] == "take_profit"
        assert result["exit_idx"] == 2

    def test_end_of_data_exit_when_no_barriers_hit(self):
        """Returns end_of_data when no barrier is hit and no time limit set."""
        df = _flat_df(100.0, 5)
        cfg = _config(sl=0.50, tp=0.50)  # enormous barriers — never trigger
        result = simulate_position(df, entry_idx=0, side="long", config=cfg)
        assert result["exit_type"] == "end_of_data"
        assert result["exit_idx"] == 4
        assert result["bars_held"] == 4

    def test_stop_priority_over_tp_same_bar(self):
        """When both stop and TP trigger on the same bar, stop-loss wins."""
        # Entry=100. SL=5% → stop=95. TP=5% → tp=105.
        # A bar with high=106 AND low=94 triggers both → stop wins.
        df = _make_df([
            (100, 100, 100, 100),
            (100, 106, 94, 100),
        ])
        cfg = _config(sl=0.05, tp=0.05)
        result = simulate_position(df, entry_idx=0, side="long", config=cfg)
        assert result["exit_type"] == "stop_loss"

    def test_custom_entry_price(self):
        """Custom entry_price overrides the bar close."""
        df = _make_df([
            (100, 100, 100, 100),
            (100, 120, 100, 115),  # high=120 > tp based on entry_price=110
        ])
        cfg = _config(sl=0.05, tp=0.10)
        # entry_price=110 → tp=121. high=120 < 121 → should NOT trigger TP.
        result = simulate_position(df, entry_idx=0, side="long", config=cfg, entry_price=110.0)
        assert result["entry_price"] == 110.0
        assert result["exit_type"] != "take_profit"


# ---------------------------------------------------------------------------
# 7. summarize_results metrics
# ---------------------------------------------------------------------------

class TestSummarizeResults:
    def _sample_results(self):
        """Three positions: one win, one loss, one break-even."""
        return [
            {
                "entry_idx": 0, "exit_idx": 3, "entry_price": 100.0,
                "exit_price": 110.0, "pnl_pct": 0.10, "bars_held": 3,
                "exit_type": "take_profit",
                "max_favorable_excursion": 0.12, "max_adverse_excursion": 0.02,
            },
            {
                "entry_idx": 5, "exit_idx": 7, "entry_price": 100.0,
                "exit_price": 95.0, "pnl_pct": -0.05, "bars_held": 2,
                "exit_type": "stop_loss",
                "max_favorable_excursion": 0.01, "max_adverse_excursion": 0.05,
            },
            {
                "entry_idx": 10, "exit_idx": 15, "entry_price": 100.0,
                "exit_price": 100.0, "pnl_pct": 0.00, "bars_held": 5,
                "exit_type": "time_limit",
                "max_favorable_excursion": 0.03, "max_adverse_excursion": 0.02,
            },
        ]

    def test_n_positions(self):
        s = summarize_results(self._sample_results())
        assert s["n_positions"] == 3

    def test_win_rate(self):
        s = summarize_results(self._sample_results())
        # 1 positive pnl out of 3
        assert abs(s["win_rate"] - 1 / 3) < 1e-9

    def test_profit_factor(self):
        s = summarize_results(self._sample_results())
        # sum_wins=0.10, sum_losses=0.05 → pf=2.0
        assert abs(s["profit_factor"] - 2.0) < 1e-9

    def test_max_drawdown(self):
        s = summarize_results(self._sample_results())
        assert abs(s["max_drawdown_pct"] - 0.05) < 1e-9

    def test_exit_type_breakdown(self):
        s = summarize_results(self._sample_results())
        assert s["exit_type_breakdown"]["take_profit"] == 1
        assert s["exit_type_breakdown"]["stop_loss"] == 1
        assert s["exit_type_breakdown"]["time_limit"] == 1

    def test_sharpe_nonzero(self):
        s = summarize_results(self._sample_results())
        # Mean pnl = (0.10 - 0.05 + 0.00) / 3 = 0.05/3. Std is nonzero.
        assert isinstance(s["sharpe"], float)
        assert s["sharpe"] != 0.0

    def test_sortino_nonzero(self):
        s = summarize_results(self._sample_results())
        assert isinstance(s["sortino"], float)
        # downside: only -0.05, downside_std = sqrt(0.0025) = 0.05
        # mean_pnl = 0.05/3, sortino = (0.05/3) / 0.05 = 1/3
        expected_sortino = (0.05 / 3) / 0.05
        assert abs(s["sortino"] - expected_sortino) < 1e-6

    def test_empty_input_returns_zeroed_dict(self):
        s = summarize_results([])
        assert s["n_positions"] == 0
        assert s["win_rate"] == 0.0
        assert s["profit_factor"] == 0.0

    def test_all_wins_profit_factor_is_inf(self):
        results = [
            {"entry_idx": 0, "exit_idx": 1, "entry_price": 100.0,
             "exit_price": 110.0, "pnl_pct": 0.10, "bars_held": 1,
             "exit_type": "take_profit",
             "max_favorable_excursion": 0.10, "max_adverse_excursion": 0.0},
        ]
        s = summarize_results(results)
        assert s["profit_factor"] == math.inf


# ---------------------------------------------------------------------------
# 8. with_vol_scaling
# ---------------------------------------------------------------------------

class TestVolScaling:
    def test_vol_scaling_proportional(self):
        """All barriers scale by current_vol / baseline_vol."""
        cfg = TripleBarrierConfig(
            stop_loss_pct=0.05,
            take_profit_pct=0.10,
            time_limit_bars=10,
            trailing_stop=TrailingStop(activation_pct=0.03, delta_pct=0.02),
        )
        scaled = cfg.with_vol_scaling(current_vol=0.30, baseline_vol=0.20)
        factor = 0.30 / 0.20  # 1.5
        assert abs(scaled.stop_loss_pct - 0.05 * factor) < 1e-9
        assert abs(scaled.take_profit_pct - 0.10 * factor) < 1e-9
        assert scaled.time_limit_bars == 10  # unchanged
        assert abs(scaled.trailing_stop.activation_pct - 0.03 * factor) < 1e-9
        assert abs(scaled.trailing_stop.delta_pct - 0.02 * factor) < 1e-9

    def test_vol_scaling_zero_baseline_returns_self(self):
        """Zero baseline vol returns original config unchanged."""
        cfg = _config(sl=0.05, tp=0.10)
        result = cfg.with_vol_scaling(current_vol=0.20, baseline_vol=0.0)
        assert result is cfg

    def test_vol_scaling_no_trailing_stop(self):
        """Scaling without trailing stop produces correct output without error."""
        cfg = _config(sl=0.04, tp=0.08)
        scaled = cfg.with_vol_scaling(current_vol=0.10, baseline_vol=0.20)
        assert abs(scaled.stop_loss_pct - 0.02) < 1e-9
        assert scaled.trailing_stop is None


# ---------------------------------------------------------------------------
# 9. simulate_signals convenience wrapper
# ---------------------------------------------------------------------------

class TestSimulateSignals:
    def test_skips_last_bar(self):
        """Indices at or past last bar are skipped silently."""
        df = _flat_df(100.0, 5)
        cfg = _config(sl=0.50, tp=0.50)
        results = simulate_signals(df, signal_indices=[0, 4], side="long", config=cfg)
        # idx=4 is the last bar → skipped
        assert len(results) == 1
        assert results[0]["entry_idx"] == 0

    def test_multiple_signals_all_valid(self):
        """Multiple valid signal indices each produce a result."""
        df = _flat_df(100.0, 20)
        cfg = _config(sl=0.50, tp=0.50, time_limit=3)
        results = simulate_signals(df, signal_indices=[0, 5, 10], side="long", config=cfg)
        assert len(results) == 3
        assert [r["entry_idx"] for r in results] == [0, 5, 10]

    def test_empty_signals_returns_empty(self):
        """Empty signal list returns empty list."""
        df = _flat_df(100.0, 10)
        cfg = _config()
        results = simulate_signals(df, signal_indices=[], side="long", config=cfg)
        assert results == []

    def test_mfe_mae_computed_for_signals(self):
        """MFE and MAE are non-trivially computed for signal results."""
        df = _make_df([
            (100, 100, 100, 100),   # entry
            (100, 108, 97, 103),    # favorable=8%, adverse=3%
            (103, 105, 99, 101),    # time limit bar
        ])
        cfg = _config(sl=0.20, tp=0.20, time_limit=2)
        results = simulate_signals(df, signal_indices=[0], side="long", config=cfg)
        r = results[0]
        # MFE should be at least 8% (from bar 1 high)
        assert r["max_favorable_excursion"] >= 0.08 - 1e-9
        # MAE should be at least 3% (from bar 1 low)
        assert r["max_adverse_excursion"] >= 0.03 - 1e-9
