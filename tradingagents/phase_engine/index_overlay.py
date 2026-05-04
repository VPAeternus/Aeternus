"""
Aeternus — Index Overlay Engine
================================
Production signal module for the v3 Momentum Acceleration Strategy.
Valid only for index ETFs: QQQ and SPY.

Signal is computed from the PREVIOUS bar (iloc[-2]) so it is ready to act
on the NEXT trading day — no lookahead.

Algorithm ported exactly from scripts/backtest_accel_rth.py (run_backtest).

Backtest validation:
  QQQ: +854 pts vs B&H +499  |  SPY: +827 pts vs B&H +543
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


class IndexOverlayEngine:
    INDEX_TICKERS = {"QQQ", "SPY"}
    INSTRUMENT_UNDERLYING = {"TQQQ": "QQQ", "SQQQ": "QQQ", "QLD": "QQQ", "UPRO": "SPY", "SPXS": "SPY"}

    def __init__(self) -> None:
        pass

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_signal(self, ticker: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Get current v3 index signal for next trading day.

        If df is not provided, loads via data_engine.load(ticker).
        Returns {} for non-index tickers or on any failure.
        Signal is based on the previous bar (iloc[-2]).
        """
        t = ticker.upper()
        if t not in self.INDEX_TICKERS:
            return {}

        try:
            if df is None:
                from . import data_engine  # lazy import
                df = data_engine.load(t)

            if df is None or len(df) < 20:
                return {}

            legs = self._check_legs(df)

            # Identify active leg label (priority: leg1 > leg2 > leg3)
            if legs["leg1"]:
                active_leg = "leg1_dip_buy"
            elif legs["leg2"]:
                active_leg = "leg2_stay_long"
            elif legs["leg3"]:
                active_leg = "leg3_uptrend_decel"
            else:
                active_leg = None

            # Previous bar context values for the signal dict
            prev = df.iloc[-2]
            regime_series = self._compute_accel_regime(df)
            prev_regime = regime_series.iloc[-2]

            return {
                "ticker": t,
                "date": str(prev.get("date", ""))[:10],
                "rth": legs["rth"],
                "overnight": legs["overnight"],
                "active_leg": active_leg,
                "leg1": legs["leg1"],
                "leg2": legs["leg2"],
                "leg3": legs["leg3"],
                "vix": float(prev.get("vix", np.nan)),
                "regime": prev_regime,
                "close": float(prev.get("close", np.nan)),
                "sma10": float(prev.get("sma10", np.nan)),
                "sma20": float(prev.get("sma20", np.nan)),
                "is_index": True,
            }

        except Exception:
            return {}

    def get_signal_for_instrument(self, ticker: str) -> Dict[str, Any]:
        """Resolve leveraged ETF to underlying index, then get V3 signal."""
        underlying = self.INSTRUMENT_UNDERLYING.get(ticker.upper(), ticker.upper())
        return self.get_signal(underlying)

    def get_signals(self, tickers: List[str] = None) -> List[Dict[str, Any]]:
        """
        Run on INDEX_TICKERS (or subset if tickers provided).
        Returns list of signal dicts for valid index tickers only.
        """
        try:
            candidates = self.INDEX_TICKERS
            if tickers is not None:
                candidates = {t.upper() for t in tickers} & self.INDEX_TICKERS

            results = []
            for ticker in sorted(candidates):
                sig = self.get_signal(ticker)
                if sig:
                    results.append(sig)
            return results

        except Exception:
            return []

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _compute_accel_regime(self, df: pd.DataFrame, lb: int = 10) -> pd.Series:
        """
        Build persistent regime series from SMA10 acceleration zero-crossings.

        slope = (sma10 - sma10.shift(lb)) / (close * lb)
        accel = slope - slope.shift(lb)

        A zero-crossing into negative territory sets "accel_dn"; into positive
        sets "accel_up". The label persists until the opposite crossing fires.

        Returns pd.Series with values "accel_dn" | "accel_up" | "neutral".
        """
        close = df["close"]
        sma10 = df["sma10"]

        slope = (sma10 - sma10.shift(lb)) / (close * lb)
        accel = slope - slope.shift(lb)
        prev_accel = accel.shift(1)

        accel_dn_signal = (accel < 0) & (prev_accel >= 0)
        accel_up_signal = (accel > 0) & (prev_accel <= 0)

        n = len(df)
        regime = np.full(n, "neutral", dtype=object)
        current = "neutral"
        for i in range(n):
            if accel_dn_signal.iloc[i]:
                current = "accel_dn"
            elif accel_up_signal.iloc[i]:
                current = "accel_up"
            regime[i] = current

        return pd.Series(regime, index=df.index, name="regime")

    def _check_legs(self, df: pd.DataFrame) -> Dict[str, bool]:
        """
        Evaluate all three RTH legs and the overnight leg for the latest bar.

        Uses iloc[-2] (previous bar) to signal for next day — no lookahead.
        Returns dict: {leg1, leg2, leg3, rth, overnight}.
        """
        regime_series = self._compute_accel_regime(df)

        # Previous bar (signal bar — index position -2)
        prev = df.iloc[-2]
        prev_regime = regime_series.iloc[-2]

        prev_close = float(prev.get("close", np.nan))
        prev_sma3 = float(prev.get("sma3", np.nan))
        prev_sma10 = float(prev.get("sma10", np.nan))
        prev_sma20 = float(prev.get("sma20", np.nan))
        prev_sma50 = float(prev.get("sma50", np.nan))
        prev_sma200 = float(prev.get("sma200", np.nan))
        prev_vix = float(prev.get("vix", np.nan))
        prev_volume = float(prev.get("volume", np.nan))

        # 5-bar volume average ending at the previous bar (iloc[-2])
        vol_sma5 = float(df["volume"].rolling(5).mean().iloc[-2])

        def _safe(v: float) -> bool:
            return not (np.isnan(v) or np.isinf(v))

        # ── Leg 1: Dip-Buy ────────────────────────────────────────────────────
        vix_ok_leg1 = (
            (_safe(prev_vix) and 20 <= prev_vix < 25) or
            (_safe(prev_vix) and 30 <= prev_vix < 40) or
            (_safe(prev_vix) and prev_vix >= 40)
        )
        leg1 = (
            prev_regime == "accel_dn" and
            _safe(prev_close) and _safe(prev_sma3) and prev_close < prev_sma3 and
            _safe(prev_sma10) and prev_close < prev_sma10 and
            _safe(prev_sma20) and prev_close < prev_sma20 and
            vix_ok_leg1
        )

        # ── Leg 2: Stay-Long ──────────────────────────────────────────────────
        leg2 = (
            _safe(prev_vix) and prev_vix <= 15 and
            _safe(prev_close) and _safe(prev_sma10) and prev_close > prev_sma10 and
            _safe(prev_sma20) and prev_sma10 > prev_sma20
        )

        # ── Leg 3: Uptrend Decel ──────────────────────────────────────────────
        leg3 = (
            prev_regime == "accel_dn" and
            _safe(prev_close) and _safe(prev_sma3) and prev_close > prev_sma3 and
            _safe(prev_sma10) and prev_close > prev_sma10 and
            _safe(prev_sma20) and prev_close > prev_sma20 and
            _safe(prev_sma50) and prev_close > prev_sma50 and
            _safe(prev_sma200) and prev_close > prev_sma200 and
            _safe(prev_volume) and _safe(vol_sma5) and prev_volume > vol_sma5
        )

        rth = leg1 or leg2 or leg3

        # ── Overnight (default long, skip conditions) ─────────────────────────
        skip1 = (
            _safe(prev_vix) and 30 <= prev_vix < 40 and
            prev_regime == "accel_up"
        )
        skip2 = (
            _safe(prev_vix) and prev_vix >= 40 and
            _safe(prev_close) and _safe(prev_sma20) and prev_close < prev_sma20
        )
        overnight = not (skip1 or skip2)

        return {
            "leg1": bool(leg1),
            "leg2": bool(leg2),
            "leg3": bool(leg3),
            "rth": bool(rth),
            "overnight": bool(overnight),
        }


# ── Module-level convenience ───────────────────────────────────────────────────

def get_index_signals() -> List[Dict[str, Any]]:
    """Scan both QQQ and SPY. Returns list of signal dicts."""
    return IndexOverlayEngine().get_signals()


def v3_benchmark_stats(
    ticker: str = "QQQ",
    lookback_days: int | None = 252,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> Dict[str, Any]:
    """
    V3 benchmark metrics for portfolio-plan display.

    Loads cached data via data_engine (free), runs backtest, slices to
    rolling window for stats. Returns {} on any failure or non-index ticker.

    Returns:
        {ticker, total_pts, bh_pts, annualized_pts_per_yr,
         rth_skip_rate_pct, on_active_rate_pct,
         current_rth, current_overnight, current_leg, period_days,
         date_start, date_end, v3_total_return_pct, bh_total_return_pct,
         v3_cagr_pct, bh_cagr_pct}
    """
    t = ticker.upper()
    if t not in IndexOverlayEngine.INDEX_TICKERS:
        return {}

    try:
        from . import data_engine
        from .v3_backtest import run_backtest

        df = data_engine.load(t)
        if df is None or len(df) < 50:
            return {}

        results = run_backtest(df)

        if "date" in df.columns:
            date_series = pd.to_datetime(df["date"]).dt.normalize()
            mask = pd.Series(True, index=df.index)
            if date_start:
                mask &= date_series >= pd.Timestamp(date_start).normalize()
            if date_end:
                mask &= date_series <= pd.Timestamp(date_end).normalize()
            if not bool(mask.any()):
                return {}
            df = df.loc[mask].reset_index(drop=True)
            results = results.loc[mask].reset_index(drop=True)

        if df is None or len(df) < 2 or len(results) < 2:
            return {}

        # Slice to rolling window (0 or None = full history)
        if lookback_days and lookback_days > 0 and len(results) > lookback_days:
            results = results.iloc[-lookback_days:].reset_index(drop=True)
            df_slice = df.iloc[-lookback_days:].reset_index(drop=True)
        else:
            df_slice = df

        n = len(results)
        if n < 2:
            return {}

        total_pts = float(results["total_pnl"].sum())
        bh_pts = float(df_slice["close"].iloc[-1] - df_slice["close"].iloc[0])
        period_days = n
        years = period_days / 252.0
        annualized = total_pts / years if years > 0 else 0.0
        start_close = float(df_slice["close"].iloc[0])
        v3_total_return = (total_pts / start_close) if start_close > 0 else 0.0
        bh_total_return = (bh_pts / start_close) if start_close > 0 else 0.0
        v3_cagr = ((1.0 + v3_total_return) ** (1.0 / years) - 1.0) if years > 0 and (1.0 + v3_total_return) > 0 else 0.0
        bh_cagr = ((1.0 + bh_total_return) ** (1.0 / years) - 1.0) if years > 0 and (1.0 + bh_total_return) > 0 else 0.0

        total_bars = n - 1  # first bar has no signal
        rth_active = int(results["rth_cond"].iloc[1:].sum())
        rth_skip_rate = (1.0 - rth_active / total_bars) * 100 if total_bars > 0 else 0.0
        on_active_ct = int(results["on_active"].iloc[1:].sum())
        on_active_rate = (on_active_ct / total_bars) * 100 if total_bars > 0 else 0.0

        # Current-day signal from existing production engine
        engine = IndexOverlayEngine()
        signal = engine.get_signal(t, df)

        return {
            "ticker": t,
            "total_pts": round(total_pts, 2),
            "bh_pts": round(bh_pts, 2),
            "annualized_pts_per_yr": round(annualized, 2),
            "date_start": str(pd.to_datetime(df_slice["date"].iloc[0]).date()) if "date" in df_slice.columns else None,
            "date_end": str(pd.to_datetime(df_slice["date"].iloc[-1]).date()) if "date" in df_slice.columns else None,
            "v3_total_return_pct": round(v3_total_return * 100.0, 2),
            "bh_total_return_pct": round(bh_total_return * 100.0, 2),
            "v3_cagr_pct": round(v3_cagr * 100.0, 2),
            "bh_cagr_pct": round(bh_cagr * 100.0, 2),
            "rth_skip_rate_pct": round(rth_skip_rate, 1),
            "on_active_rate_pct": round(on_active_rate, 1),
            "current_rth": signal.get("rth", False),
            "current_overnight": signal.get("overnight", True),
            "current_leg": signal.get("active_leg"),
            "period_days": period_days,
        }

    except Exception:
        return {}
