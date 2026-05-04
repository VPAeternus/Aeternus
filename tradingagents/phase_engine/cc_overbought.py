"""
Aeternus Phase Engine — CC Overbought State Machine
Ports the backtested covered-call overbought exit strategy into a production module.

Stock-only engine:
  Intended for individual equities. Index ETFs such as QQQ/SPY/IWM are
  explicitly out of scope and should use the dedicated index overlay path.

Backtest summary: 25 years / 94 stocks — 86/94 (91%) beat buy-and-hold.

Algorithm:
  Default state: LONG
  Acceleration = SMA3-based slope-of-slope, expanding percentile thresholds.

  Exit (LONG → CASH) rules by regime:
    ABOVE_BOTH          : accel > P90   (overbought reversal)
    ABOVE_200_BELOW_50  : accel < P03   (failed support crash)
    BELOW_200           : accel > P97   (dead cat bounce)
                          accel < P03 → STAY IN (capitulation recovery)

  Re-entry (CASH → LONG):
    close > sma3  AND  days_out >= holdout
"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd


_INDEX_ETF_TICKERS: frozenset[str] = frozenset({"QQQ", "SPY", "IWM"})


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _classify_regime(close: float, sma50: float, sma200: float) -> str:
    """Classify regime from scalar price levels."""
    above_200 = close > sma200
    above_50  = close > sma50
    if above_200 and above_50:
        return "ABOVE_BOTH"
    if above_200 and not above_50:
        return "ABOVE_200_BELOW_50"
    if not above_200 and above_50:
        return "BELOW_200_ABOVE_50"
    return "BELOW_BOTH"


def _compute_accel(df: pd.DataFrame, lb: int = 5) -> pd.Series:
    """
    SMA3 acceleration.
      slope = (sma3 - sma3.shift(lb)) / (close * lb)
      accel = slope - slope.shift(lb)
    """
    sma3  = df["close"].rolling(3).mean()
    slope = (sma3 - sma3.shift(lb)) / (df["close"] * lb)
    accel = slope - slope.shift(lb)
    return accel


def _expanding_quantiles(series: pd.Series, min_periods: int = 252) -> pd.DataFrame:
    """
    Compute P03, P90, P97 expanding quantiles with no lookahead.
    Returns DataFrame with columns p03, p90, p97 aligned to series index.
    """
    p03 = series.expanding(min_periods=min_periods).quantile(0.03)
    p90 = series.expanding(min_periods=min_periods).quantile(0.90)
    p97 = series.expanding(min_periods=min_periods).quantile(0.97)
    return pd.DataFrame({"p03": p03, "p90": p90, "p97": p97}, index=series.index)


def _run_state_machine(
    df: pd.DataFrame,
    accel: pd.Series,
    pcts: pd.DataFrame,
    holdout: int,
    warmup: int,
) -> Dict[str, Any]:
    """
    Run the CC overbought state machine over the full DataFrame.
    Returns final state dict.
    """
    close_arr   = df["close"].values
    sma3_arr    = df["close"].rolling(3).mean().values
    sma50_arr   = df["close"].rolling(50).mean().values
    sma200_arr  = df["close"].rolling(200).mean().values
    accel_arr   = accel.values
    p03_arr     = pcts["p03"].values
    p90_arr     = pcts["p90"].values
    p97_arr     = pcts["p97"].values

    n = len(df)

    # State variables
    state      = "long"
    days_out   = 0
    last_exit  = None

    # Counters
    exits_ob   = 0   # overbought exits
    exits_fs   = 0   # failed support exits
    exits_dc   = 0   # dead cat exits
    bars_long  = 0
    bars_total = 0

    for i in range(warmup, n):
        close  = close_arr[i]
        sma3   = sma3_arr[i]
        sma50  = sma50_arr[i]
        sma200 = sma200_arr[i]
        a      = accel_arr[i]
        p03    = p03_arr[i]
        p90    = p90_arr[i]
        p97    = p97_arr[i]

        # Skip bars where thresholds are not yet valid (expanding not warmed up)
        if np.isnan(p03) or np.isnan(p90) or np.isnan(p97):
            continue
        if np.isnan(a) or np.isnan(sma3) or np.isnan(sma50) or np.isnan(sma200):
            continue

        bars_total += 1

        regime = _classify_regime(close, sma50, sma200)

        if state == "long":
            bars_long += 1
            # Exit rules
            if regime == "ABOVE_BOTH" and a > p90:
                state     = "cash"
                days_out  = 0
                last_exit = "overbought"
                exits_ob  += 1
            elif regime == "ABOVE_200_BELOW_50" and a < p03:
                state     = "cash"
                days_out  = 0
                last_exit = "failed_support"
                exits_fs  += 1
            elif regime in ("BELOW_200_ABOVE_50", "BELOW_BOTH"):
                # Dead-cat-bounce exit — but capitulation recovery keeps us in
                if a < p03:
                    pass  # capitulation recovery — stay long
                elif a > p97:
                    state     = "cash"
                    days_out  = 0
                    last_exit = "dead_cat"
                    exits_dc  += 1

        else:  # state == "cash"
            days_out += 1
            # Re-entry: close > sma3 AND days_out >= holdout
            if days_out >= holdout and close > sma3:
                state    = "long"
                days_out = 0

    # Current bar values for the signal dict
    last_idx   = n - 1
    last_row   = df.iloc[last_idx]
    last_accel = float(accel_arr[last_idx]) if not np.isnan(accel_arr[last_idx]) else float("nan")
    last_p03   = float(p03_arr[last_idx])
    last_p90   = float(p90_arr[last_idx])
    last_p97   = float(p97_arr[last_idx])

    # Compute current accel percentile rank in expanding window
    accel_pct = float("nan")
    if not np.isnan(last_accel) and not np.isnan(last_p03):
        # Use the rank within the valid history up to last bar
        valid = accel.dropna()
        if len(valid) >= 1:
            rank = float((valid <= last_accel).sum()) / len(valid)
            accel_pct = round(rank, 4)

    invested_pct = round(bars_long / bars_total * 100, 2) if bars_total > 0 else float("nan")

    last_close  = float(last_row["close"])
    last_sma3   = float(sma3_arr[last_idx])  if not np.isnan(sma3_arr[last_idx])  else float("nan")
    last_sma50  = float(sma50_arr[last_idx]) if not np.isnan(sma50_arr[last_idx]) else float("nan")
    last_sma200 = float(sma200_arr[last_idx]) if not np.isnan(sma200_arr[last_idx]) else float("nan")

    regime = _classify_regime(last_close, last_sma50, last_sma200)

    return {
        "state":            state,
        "regime":           regime,
        "accel_percentile": accel_pct,
        "accel_value":      round(last_accel, 8) if not np.isnan(last_accel) else None,
        "days_out":         days_out,
        "last_exit_type":   last_exit,
        "exits_ob":         exits_ob,
        "exits_fs":         exits_fs,
        "exits_dc":         exits_dc,
        "invested_pct":     invested_pct,
        "close":            round(last_close, 4),
        "sma3":             round(last_sma3, 4)   if not np.isnan(last_sma3)   else None,
        "sma50":            round(last_sma50, 4)  if not np.isnan(last_sma50)  else None,
        "sma200":           round(last_sma200, 4) if not np.isnan(last_sma200) else None,
    }


# ─── Engine class ─────────────────────────────────────────────────────────────

class CCOverboughtEngine:
    """
    Production CC overbought signal engine for individual equities only.

    Runs the SMA3-acceleration state machine (backtested: 91% beat buy-and-hold)
    to determine whether each stock ticker should currently be LONG or in CASH.
    Index ETFs such as QQQ/SPY/IWM are intentionally excluded and should route
    through the dedicated index overlay engine.
    """

    def __init__(self, holdout: int = 3, warmup: int = 252):
        self.holdout = holdout
        self.warmup  = warmup

    # ── Public API ────────────────────────────────────────────────────────────

    def get_signal(self, ticker: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Get current CC overbought signal for a stock ticker.
        If df not provided, loads via data_engine.load(ticker).
        Returns {} for index ETFs because this engine is stock-only.
        Returns {} on any failure.
        """
        try:
            normalized = str(ticker or "").upper().strip()
            if normalized in _INDEX_ETF_TICKERS:
                return {}

            if df is None:
                from . import data_engine
                df = data_engine.load(normalized)

            if df is None or len(df) < self.warmup + 50:
                return {}

            df = df.reset_index(drop=True)

            accel = _compute_accel(df)
            pcts  = _expanding_quantiles(accel, min_periods=self.warmup)
            state = _run_state_machine(df, accel, pcts, self.holdout, self.warmup)

            date_val = df.iloc[-1]["date"]
            date_str = str(date_val)[:10]

            return {
                "ticker":            normalized,
                "date":              date_str,
                "state":             state["state"],
                "regime":            state["regime"],
                "accel_percentile":  state["accel_percentile"],
                "accel_value":       state["accel_value"],
                "days_out":          state["days_out"],
                "last_exit_type":    state["last_exit_type"],
                "exits_ob":          state["exits_ob"],
                "exits_fs":          state["exits_fs"],
                "exits_dc":          state["exits_dc"],
                "invested_pct":      state["invested_pct"],
                "close":             state["close"],
                "sma3":              state["sma3"],
                "sma50":             state["sma50"],
                "sma200":            state["sma200"],
                "holdout":           self.holdout,
            }

        except Exception:
            return {}

    def get_signals(self, tickers: List[str]) -> List[Dict[str, Any]]:
        """
        Run get_signal on a list of tickers. Skips failures silently.
        Returns list of signal dicts (only successful ones).
        """
        results = []
        for ticker in tickers:
            sig = self.get_signal(ticker)
            if sig:
                results.append(sig)
        return results

    # ── Private helpers (exposed for testing) ─────────────────────────────────

    def _compute_accel(self, df: pd.DataFrame) -> pd.Series:
        return _compute_accel(df)

    def _classify_regime(self, close: float, sma50: float, sma200: float) -> str:
        return _classify_regime(close, sma50, sma200)

    def _run_state_machine(self, df: pd.DataFrame) -> Dict[str, Any]:
        accel = _compute_accel(df)
        pcts  = _expanding_quantiles(accel, min_periods=self.warmup)
        return _run_state_machine(df, accel, pcts, self.holdout, self.warmup)


# ─── Module-level convenience ─────────────────────────────────────────────────

def get_cc_overbought_signals(tickers: List[str] = None, holdout: int = 3) -> List[Dict]:
    """
    Module-level convenience. Uses config.UNIVERSE if tickers not provided.
    Returns list of signal dicts sorted by ticker.
    """
    try:
        if tickers is None:
            from . import config
            tickers = config.UNIVERSE
        engine  = CCOverboughtEngine(holdout=holdout)
        results = engine.get_signals(tickers)
        return sorted(results, key=lambda x: x.get("ticker", ""))
    except Exception:
        return []
