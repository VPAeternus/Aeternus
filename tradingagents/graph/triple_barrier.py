"""
triple_barrier.py — Standalone stop-loss / take-profit / trailing-stop position simulator.

No imports from other tradingagents modules. Dependencies: numpy, pandas, dataclasses, math.

OHLC-correct: a stop is triggered when the intrabar low/high crosses the threshold,
not just the close. On bars where both stop-loss and take-profit would trigger,
stop-loss takes priority (conservative).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TrailingStop:
    """Trailing stop configuration.

    activation_pct: price must move this fraction in-direction before trailing activates.
                    e.g. 0.02 means the position must be up 2% before the trail starts.
    delta_pct:      the stop trails this fraction below the peak (long) or above the trough (short).
                    e.g. 0.03 means trail is set 3% below the running peak high.
    """
    activation_pct: float
    delta_pct: float


@dataclass
class TripleBarrierConfig:
    """Full barrier configuration for a position.

    stop_loss_pct:   fractional stop-loss distance from entry. e.g. 0.05 = 5%.
    take_profit_pct: fractional take-profit distance from entry. e.g. 0.10 = 10%.
    time_limit_bars: maximum number of bars to hold before forced exit (None = no limit).
    trailing_stop:   optional TrailingStop; replaces the fixed stop once activated.
    """
    stop_loss_pct: float
    take_profit_pct: float
    time_limit_bars: Optional[int] = None
    trailing_stop: Optional[TrailingStop] = None

    def with_vol_scaling(self, current_vol: float, baseline_vol: float) -> "TripleBarrierConfig":
        """Return a new config with all barriers scaled proportionally to vol.

        Barriers widen when current volatility exceeds baseline, and narrow when
        current volatility is below baseline.

        Args:
            current_vol:  realized volatility of the instrument (same units as baseline).
            baseline_vol: reference volatility against which current_vol is measured.

        Returns:
            New TripleBarrierConfig with scaled values.
        """
        if baseline_vol <= 0:
            return self
        factor = current_vol / baseline_vol
        ts: Optional[TrailingStop] = None
        if self.trailing_stop is not None:
            ts = TrailingStop(
                activation_pct=self.trailing_stop.activation_pct * factor,
                delta_pct=self.trailing_stop.delta_pct * factor,
            )
        return TripleBarrierConfig(
            stop_loss_pct=self.stop_loss_pct * factor,
            take_profit_pct=self.take_profit_pct * factor,
            time_limit_bars=self.time_limit_bars,
            trailing_stop=ts,
        )


# ---------------------------------------------------------------------------
# Core simulation
# ---------------------------------------------------------------------------

def simulate_position(
    df: pd.DataFrame,
    entry_idx: int,
    side: str,
    config: TripleBarrierConfig,
    entry_price: Optional[float] = None,
) -> dict:
    """Simulate a single position with OHLC-correct barrier evaluation.

    Args:
        df:          DataFrame with columns open, high, low, close (lowercase).
                     Index may be DatetimeIndex or integer.
        entry_idx:   integer iloc position where the trade is entered.
        side:        "long" or "short".
        config:      TripleBarrierConfig defining the barriers.
        entry_price: override for the entry price; defaults to df.iloc[entry_idx]["close"].

    Returns:
        dict with keys:
            entry_idx, exit_idx, entry_price, exit_price, pnl_pct, bars_held,
            exit_type, max_favorable_excursion, max_adverse_excursion.

    Exit types: "stop_loss", "take_profit", "time_limit", "trailing_stop", "end_of_data".
    """
    if side not in ("long", "short"):
        raise ValueError(f"side must be 'long' or 'short', got {side!r}")

    n = len(df)

    # Edge case: entry at or past last bar → nothing to simulate.
    if entry_idx >= n - 1:
        ep = float(df.iloc[entry_idx]["close"]) if entry_price is None else float(entry_price)
        return {
            "entry_idx": entry_idx,
            "exit_idx": entry_idx,
            "entry_price": ep,
            "exit_price": ep,
            "pnl_pct": 0.0,
            "bars_held": 0,
            "exit_type": "end_of_data",
            "max_favorable_excursion": 0.0,
            "max_adverse_excursion": 0.0,
        }

    ep = float(df.iloc[entry_idx]["close"]) if entry_price is None else float(entry_price)

    # Compute fixed barrier levels from entry price.
    if side == "long":
        stop_price = ep * (1.0 - config.stop_loss_pct)
        tp_price = ep * (1.0 + config.take_profit_pct)
        side_sign = 1.0
    else:  # short
        stop_price = ep * (1.0 + config.stop_loss_pct)
        tp_price = ep * (1.0 - config.take_profit_pct)
        side_sign = -1.0

    # Trailing stop state.
    trail_active = False
    trail_level: Optional[float] = None
    if config.trailing_stop is not None:
        peak_price = ep  # tracks best price in-direction

    # Excursion tracking.
    mfe = 0.0  # max favorable excursion (best % gain)
    mae = 0.0  # max adverse excursion (worst % drawdown, stored as positive)

    # Determine search range.
    start = entry_idx + 1
    end = n  # exclusive
    if config.time_limit_bars is not None:
        end = min(n, entry_idx + config.time_limit_bars + 1)

    exit_idx: Optional[int] = None
    exit_price: Optional[float] = None
    exit_type: Optional[str] = None

    for i in range(start, end):
        row_high = float(df.iloc[i]["high"])
        row_low = float(df.iloc[i]["low"])
        row_close = float(df.iloc[i]["close"])

        # Update excursions.
        if side == "long":
            favorable_pct = (row_high - ep) / ep
            adverse_pct = (ep - row_low) / ep
        else:
            favorable_pct = (ep - row_low) / ep
            adverse_pct = (row_high - ep) / ep

        if favorable_pct > mfe:
            mfe = favorable_pct
        if adverse_pct > mae:
            mae = adverse_pct

        # Update trailing stop state.
        # just_activated: if the trail activates on this bar, don't check the trail
        # on the same bar — intrabar sequencing is ambiguous and we cannot know whether
        # the favorable move that activated the trail preceded the adverse move.
        just_activated = False
        if config.trailing_stop is not None:
            ts_cfg = config.trailing_stop
            if side == "long":
                in_direction_price = row_high
                # Activate trailing stop once activation threshold is hit.
                if not trail_active:
                    if in_direction_price >= ep * (1.0 + ts_cfg.activation_pct):
                        trail_active = True
                        just_activated = True
                        peak_price = in_direction_price
                        trail_level = peak_price * (1.0 - ts_cfg.delta_pct)
                else:
                    # Update peak and trail level.
                    if in_direction_price > peak_price:
                        peak_price = in_direction_price
                        trail_level = peak_price * (1.0 - ts_cfg.delta_pct)
            else:  # short
                in_direction_price = row_low
                if not trail_active:
                    if in_direction_price <= ep * (1.0 - ts_cfg.activation_pct):
                        trail_active = True
                        just_activated = True
                        peak_price = in_direction_price
                        trail_level = peak_price * (1.0 + ts_cfg.delta_pct)
                else:
                    if in_direction_price < peak_price:
                        peak_price = in_direction_price
                        trail_level = peak_price * (1.0 + ts_cfg.delta_pct)

        # Evaluate barriers — stop-loss takes priority if both trigger same bar.

        # Check trailing stop (only if active and not just activated this bar).
        trail_triggered = False
        if trail_active and not just_activated and trail_level is not None:
            if side == "long" and row_low <= trail_level:
                trail_triggered = True
            elif side == "short" and row_high >= trail_level:
                trail_triggered = True

        # Determine if fixed stop is triggered.
        fixed_stop_triggered = False
        if side == "long" and row_low <= stop_price:
            fixed_stop_triggered = True
        elif side == "short" and row_high >= stop_price:
            fixed_stop_triggered = True

        # Determine if take-profit is triggered.
        tp_triggered = False
        if side == "long" and row_high >= tp_price:
            tp_triggered = True
        elif side == "short" and row_low <= tp_price:
            tp_triggered = True

        # Priority: stop_loss > trailing_stop > take_profit (conservative).
        if fixed_stop_triggered:
            exit_idx = i
            # Exit at the stop price (slippage-free, worst case is open, but we use stop level).
            exit_price = stop_price
            exit_type = "stop_loss"
            break
        elif trail_triggered:
            exit_idx = i
            exit_price = float(trail_level)
            exit_type = "trailing_stop"
            break
        elif tp_triggered:
            exit_idx = i
            exit_price = tp_price
            exit_type = "take_profit"
            break

    # If no barrier was hit in the search window, check whether we hit the time limit
    # or simply ran out of data.
    if exit_idx is None:
        last_i = end - 1
        exit_idx = last_i
        exit_price = float(df.iloc[last_i]["close"])
        if config.time_limit_bars is not None and (last_i - entry_idx) >= config.time_limit_bars:
            exit_type = "time_limit"
        else:
            exit_type = "end_of_data"

    bars_held = exit_idx - entry_idx
    pnl_pct = (exit_price - ep) / ep * side_sign

    return {
        "entry_idx": entry_idx,
        "exit_idx": exit_idx,
        "entry_price": ep,
        "exit_price": exit_price,
        "pnl_pct": pnl_pct,
        "bars_held": bars_held,
        "exit_type": exit_type,
        "max_favorable_excursion": mfe,
        "max_adverse_excursion": mae,
    }


# ---------------------------------------------------------------------------
# Batch convenience
# ---------------------------------------------------------------------------

def simulate_signals(
    df: pd.DataFrame,
    signal_indices: list,
    side: str,
    config: TripleBarrierConfig,
) -> list:
    """Run simulate_position for each signal index.

    Skips any index where fewer than 2 bars remain after entry (i.e. entry_idx >= len(df)-1).

    Args:
        df:             DataFrame with open, high, low, close columns.
        signal_indices: list of integer iloc indices where entries occur.
        side:           "long" or "short".
        config:         TripleBarrierConfig to apply to every position.

    Returns:
        list of result dicts from simulate_position, one per valid signal.
    """
    n = len(df)
    results = []
    for idx in signal_indices:
        if idx >= n - 1:
            continue  # < 2 bars remain, skip
        results.append(simulate_position(df, idx, side, config))
    return results


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def summarize_results(position_results: list) -> dict:
    """Aggregate statistics over a list of simulate_position output dicts.

    Args:
        position_results: list of dicts as returned by simulate_position.

    Returns:
        dict with aggregated metrics. Returns a zeroed dict if list is empty.
    """
    if not position_results:
        return {
            "n_positions": 0,
            "win_rate": 0.0,
            "mean_pnl_pct": 0.0,
            "median_pnl_pct": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "mean_bars_held": 0.0,
            "exit_type_breakdown": {},
            "sharpe": 0.0,
            "sortino": 0.0,
            "expectancy_pct": 0.0,
        }

    pnls = [r["pnl_pct"] for r in position_results]
    maes = [r["max_adverse_excursion"] for r in position_results]
    bars = [r["bars_held"] for r in position_results]
    n = len(pnls)

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / n
    mean_pnl = sum(pnls) / n
    median_pnl = float(np.median(pnls))

    sum_wins = sum(wins)
    sum_losses = abs(sum(losses))
    if sum_losses == 0:
        profit_factor = math.inf if sum_wins > 0 else 0.0
    else:
        profit_factor = sum_wins / sum_losses

    max_drawdown = max(maes)

    mean_bars = sum(bars) / n

    exit_type_breakdown: dict = {}
    for r in position_results:
        et = r["exit_type"]
        exit_type_breakdown[et] = exit_type_breakdown.get(et, 0) + 1

    # Sharpe: mean / std of pnl_pct (no annualisation — per-position Sharpe proxy).
    if n > 1:
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / (n - 1)
        std_pnl = math.sqrt(variance)
    else:
        std_pnl = 0.0
    sharpe = mean_pnl / std_pnl if std_pnl > 0 else 0.0

    # Sortino: mean / downside std.
    downside_sq = [p ** 2 for p in pnls if p < 0]
    if len(downside_sq) > 0:
        downside_variance = sum(downside_sq) / len(downside_sq)
        downside_std = math.sqrt(downside_variance)
    else:
        downside_std = 0.0
    sortino = mean_pnl / downside_std if downside_std > 0 else 0.0

    # Expectancy.
    mean_win = sum(wins) / len(wins) if wins else 0.0
    mean_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    expectancy = win_rate * mean_win - (1.0 - win_rate) * mean_loss

    return {
        "n_positions": n,
        "win_rate": win_rate,
        "mean_pnl_pct": mean_pnl,
        "median_pnl_pct": median_pnl,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_drawdown,
        "mean_bars_held": mean_bars,
        "exit_type_breakdown": exit_type_breakdown,
        "sharpe": sharpe,
        "sortino": sortino,
        "expectancy_pct": expectancy,
    }
