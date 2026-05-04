"""
Aeternus Phase Engine — RTH Covered Call Signal

Per-stock RTH (Regular Trading Hours) return analysis.
Shows SMA regime flags and historical/recent RTH returns
so the user can decide on covered call eligibility.

Usage:
  engine = RTHTimingEngine()
  signal = engine.get_signal("TSLA")
  # -> {ticker, date, above_sma200, above_sma50, above_sma3,
  #     vol_quintile, rth_avg_daily ($), rth_last5d ($)}
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


VOL_THRESHOLDS = [1.13, 1.34, 1.54, 1.83]  # Q1/Q2/Q3/Q4/Q5 boundaries


def _vol_quintile(daily_vol_pct: float) -> int:
    """Classify daily vol into quintile 1-5."""
    for i, threshold in enumerate(VOL_THRESHOLDS):
        if daily_vol_pct < threshold:
            return i + 1
    return 5


class RTHTimingEngine:
    """Per-stock RTH analysis for covered call decision support."""

    WARMUP = 252

    def get_signal(self, ticker: str, df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """Get RTH signal for a ticker.

        Returns dict with:
          ticker, date, above_sma200, above_sma50, above_sma3,
          vol_quintile (1-5), rth_avg_daily ($ avg daily RTH move when
          above all 3 SMAs), rth_last5d ($ avg daily RTH move last 5d).
        Returns {} on failure.
        """
        try:
            if df is None:
                from . import data_engine
                df = data_engine.load(ticker)

            if df is None or len(df) < 200:
                return {}

            close = df["close"].values
            opn = df["open"].values

            # SMA values — use precomputed if available, else compute
            if "sma200" in df.columns:
                sma200 = df["sma200"].values
            else:
                sma200 = pd.Series(close).rolling(200).mean().values

            if "sma50" in df.columns:
                sma50 = df["sma50"].values
            else:
                sma50 = pd.Series(close).rolling(50).mean().values

            if "sma3" in df.columns:
                sma3 = df["sma3"].values
            else:
                sma3 = pd.Series(close).rolling(3).mean().values

            n = len(close)
            last = n - 1

            # Current regime flags
            above_sma200 = bool(close[last] > sma200[last]) if not np.isnan(sma200[last]) else False
            above_sma50 = bool(close[last] > sma50[last]) if not np.isnan(sma50[last]) else False
            above_sma3 = bool(close[last] > sma3[last]) if not np.isnan(sma3[last]) else False

            # Vol quintile (last 60 bars)
            returns = np.diff(close[-61:]) / close[-61:-1]
            daily_vol_pct = float(np.mean(np.abs(returns)) * 100)
            quintile = _vol_quintile(daily_vol_pct)

            # Historical avg daily RTH move in dollars when above all 3 SMAs
            rth_list = []
            start = max(self.WARMUP, 200)
            for i in range(start, n - 1):
                if np.isnan(sma200[i]) or np.isnan(sma50[i]) or np.isnan(sma3[i]):
                    continue
                if close[i] > sma200[i] and close[i] > sma50[i] and close[i] > sma3[i]:
                    rth_list.append(close[i + 1] - opn[i + 1])

            rth_avg_daily = round(float(np.mean(rth_list)), 2) if rth_list else 0.0

            # Last 5 trading days average RTH move in dollars (only days above all 3 SMAs)
            last5_list = []
            for i in range(max(0, n - 5), n):
                if np.isnan(sma200[i]) or np.isnan(sma50[i]) or np.isnan(sma3[i]):
                    continue
                if close[i] > sma200[i] and close[i] > sma50[i] and close[i] > sma3[i]:
                    last5_list.append(close[i] - opn[i])
            rth_last5d = round(float(np.mean(last5_list)), 2) if last5_list else 0.0

            return {
                "ticker": ticker,
                "date": str(df["date"].iloc[-1].date()) if "date" in df.columns else str(pd.Timestamp.now().date()),
                "above_sma200": above_sma200,
                "above_sma50": above_sma50,
                "above_sma3": above_sma3,
                "vol_quintile": quintile,
                "rth_avg_daily": rth_avg_daily,
                "rth_last5d": rth_last5d,
            }
        except Exception:
            return {}

    def get_signals(self, tickers: List[str]) -> List[Dict[str, Any]]:
        """Batch. Skips failures."""
        results = []
        for t in tickers:
            sig = self.get_signal(t)
            if sig:
                results.append(sig)
        return results
