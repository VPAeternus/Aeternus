"""Pure Python momentum analysis computation engine.

No LLM calls. Loads price/indicator data via data_engine (handles caching),
runs the CC overbought state machine validated over 25 years / 94 stocks, and
returns a structured snapshot dict.

Entry points:
    build_momentum_snapshot(ticker, trade_date) -> dict
    get_regime_state(ticker) -> dict
"""

import numpy as np
import pandas as pd
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(max(lo, min(hi, value)))


# ---------------------------------------------------------------------------
# Acceleration
# ---------------------------------------------------------------------------

def _compute_accel(close_series: pd.Series, sma3_series: pd.Series, lb: int = 5) -> pd.Series:
    slope = (sma3_series - sma3_series.shift(lb)) / (close_series * lb)
    accel = slope - slope.shift(lb)
    return accel


# ---------------------------------------------------------------------------
# Regime-exit state machine
# ---------------------------------------------------------------------------

def _run_cc_overbought_window(
    df: pd.DataFrame, holdout: int = 3, window: int = 504
) -> Dict[str, Any]:
    """Run the CC overbought state machine on the last `window` bars of df.

    Requires a `accel` column already present on df. Also needs close,
    sma3, sma50, sma200. Expanding percentiles computed from the beginning
    of df (full warmup), not just the window.

    Returns invested_pct (0-100 float), exits_ob, exits_fs, exits_dc (ints).
    """
    if len(df) < 10:
        return {"invested_pct": 50.0, "exits_ob": 0, "exits_fs": 0, "exits_dc": 0}

    accel = df["accel"]

    # Expanding percentile ranks on full history (need min 252 periods warm)
    p90 = accel.expanding(min_periods=252).quantile(0.90)
    p97 = accel.expanding(min_periods=252).quantile(0.97)
    p03 = accel.expanding(min_periods=252).quantile(0.03)

    # Slice to last `window` bars for the state machine
    if len(df) > window:
        sub = df.iloc[-window:].copy()
        p90_sub = p90.iloc[-window:].values
        p97_sub = p97.iloc[-window:].values
        p03_sub = p03.iloc[-window:].values
    else:
        sub = df.copy()
        p90_sub = p90.values
        p97_sub = p97.values
        p03_sub = p03.values

    close = sub["close"].values
    sma50 = sub["sma50"].values
    sma200 = sub["sma200"].values
    accel_vals = sub["accel"].values
    n = len(sub)

    invested = True
    holdout_counter = 0
    invested_days = 0
    exits_ob = 0
    exits_fs = 0
    exits_dc = 0

    for i in range(n):
        c = close[i]
        s50 = sma50[i]
        s200 = sma200[i]
        acc = accel_vals[i]
        q90 = p90_sub[i]
        q97 = p97_sub[i]
        q03 = p03_sub[i]

        if invested:
            invested_days += 1

            # Skip exit logic if any threshold is NaN (warm-up period)
            if np.isnan(q90) or np.isnan(q97) or np.isnan(q03) or np.isnan(acc):
                continue

            above_200 = not np.isnan(s200) and c > s200
            above_50 = not np.isnan(s50) and c > s50

            # Exit: overbought (above both + accel > P90)
            if above_200 and above_50 and acc > q90:
                invested = False
                holdout_counter = holdout
                exits_ob += 1

            # Exit: failed support (above 200, below 50, accel < P03)
            elif above_200 and not above_50 and acc < q03:
                invested = False
                holdout_counter = holdout
                exits_fs += 1

            # Exit: dead cat (below 200, accel > P97)
            elif not above_200 and acc > q97:
                invested = False
                holdout_counter = holdout
                exits_dc += 1

            # Stay: capitulation (below 200, accel < P03) — do nothing

        else:
            # Out of market: tick down holdout then check re-entry
            if holdout_counter > 0:
                holdout_counter -= 1
            else:
                # Re-entry: close > sma3
                sma3_val = sub["sma3"].values[i]
                if not np.isnan(sma3_val) and c > sma3_val:
                    invested = True

    total_days = n
    invested_pct = (invested_days / total_days * 100.0) if total_days > 0 else 50.0

    return {
        "invested_pct": round(invested_pct, 2),
        "exits_ob": exits_ob,
        "exits_fs": exits_fs,
        "exits_dc": exits_dc,
        "signal_state": "long" if invested else "cash",
    }


# ---------------------------------------------------------------------------
# Sub-score: trend_strength
# ---------------------------------------------------------------------------

def _score_trend_strength(close: float, sma10: float, sma20: float, sma50: float, sma200: float) -> int:
    """SMA stack alignment score (0-100)."""
    if any(np.isnan(v) for v in (close, sma10, sma20, sma50, sma200)):
        return 50

    above_200 = close > sma200
    above_50 = close > sma50
    above_20 = close > sma20
    above_10 = close > sma10

    # Compute a continuous variable: distance from sma200 as % of sma200
    dist_pct = (close - sma200) / sma200 if sma200 != 0 else 0.0
    # Cap to [-0.30, 0.30] for scaling
    dist_capped = max(-0.30, min(0.30, dist_pct))
    # Normalized 0-1 within [-0.30, 0.30]
    continuous = (dist_capped + 0.30) / 0.60

    if above_200 and above_50 and above_20 and above_10:
        # Band 90-100
        score = 90.0 + continuous * 10.0
    elif above_200 and above_50 and above_20:
        # Band 80-90
        score = 80.0 + continuous * 10.0
    elif above_200 and above_50:
        # Band 65-80
        score = 65.0 + continuous * 15.0
    elif above_200:
        # Band 50-65
        score = 50.0 + continuous * 15.0
    elif not above_200 and above_50:
        # Band 35-50
        score = 35.0 + continuous * 15.0
    elif not above_200 and not above_50 and above_20:
        # Band 20-35
        score = 20.0 + continuous * 15.0
    else:
        # All below: band 0-20
        score = 0.0 + continuous * 20.0

    return _clamp(score)


# ---------------------------------------------------------------------------
# Sub-score: momentum_health
# ---------------------------------------------------------------------------

def _score_momentum_health(accel_pct_rank: float) -> int:
    """Momentum health from where accel pct rank sits (0-100).

    pct_rank is 0.0-1.0. Sweet spot P15-P80 is healthy.
    """
    r = accel_pct_rank

    if r < 0.05:
        # Deep oversold P0-P05: 45-60
        score = 45.0 + (r / 0.05) * 15.0
    elif r < 0.15:
        # Mildly oversold P05-P15: 55-70
        score = 55.0 + ((r - 0.05) / 0.10) * 15.0
    elif r <= 0.80:
        # Sweet spot P15-P80: 65-85
        score = 65.0 + ((r - 0.15) / 0.65) * 20.0
    elif r <= 0.90:
        # Approaching overbought P80-P90: 45-65
        score = 65.0 - ((r - 0.80) / 0.10) * 20.0
    else:
        # Overbought P90+: 15-45
        score = 45.0 - ((r - 0.90) / 0.10) * 30.0

    return _clamp(score)


# ---------------------------------------------------------------------------
# Sub-score: regime_quality
# ---------------------------------------------------------------------------

def _score_regime_quality(invested_pct: float, exits_ob: int, exits_fs: int, exits_dc: int, window: int = 504) -> int:
    """Regime quality from invested % and exit pattern."""
    years = window / 252.0
    exit_frequency = (exits_ob + exits_fs + exits_dc) / years if years > 0 else 0.0

    # Exit frequency quality (0-100)
    if exit_frequency < 3.0:
        exit_freq_score = 80.0
    elif exit_frequency <= 8.0:
        exit_freq_score = 80.0 - ((exit_frequency - 3.0) / 5.0) * 30.0
    else:
        exit_freq_score = 50.0 - min(30.0, (exit_frequency - 8.0) * 3.0)

    # Exit type quality adjustment
    total_exits = exits_ob + exits_fs + exits_dc
    if total_exits > 0:
        fs_pct = exits_fs / total_exits
        dc_pct = exits_dc / total_exits
        # Failed support = worst (trend breakdown), dead cat = negative (below 200)
        exit_type_penalty = fs_pct * 20.0 + dc_pct * 10.0
        exit_freq_score = max(0.0, exit_freq_score - exit_type_penalty)

    exit_quality_component = exit_freq_score

    score = invested_pct * 0.60 + exit_quality_component * 0.40
    return _clamp(score)


# ---------------------------------------------------------------------------
# Sub-score: volume_confirmation
# ---------------------------------------------------------------------------

def _score_volume_confirmation(volume: float, vol_sma20: float, close: float, sma20: float) -> int:
    """Volume confirmation score (0-100)."""
    if np.isnan(vol_sma20) or vol_sma20 <= 0 or np.isnan(volume):
        return 50

    vol_ratio = volume / vol_sma20
    in_uptrend = not np.isnan(sma20) and close > sma20

    if in_uptrend:
        if vol_ratio > 1.5:
            score = 80.0 + min(15.0, (vol_ratio - 1.5) * 10.0)
        elif vol_ratio >= 1.0:
            score = 60.0 + (vol_ratio - 1.0) / 0.5 * 20.0
        else:
            score = 40.0 + vol_ratio * 20.0
    else:
        if vol_ratio > 1.5:
            score = 15.0 + max(0.0, 20.0 - (vol_ratio - 1.5) * 10.0)
        elif vol_ratio >= 1.0:
            score = 30.0 + (1.5 - vol_ratio) / 0.5 * 20.0
        else:
            score = 45.0 + (1.0 - vol_ratio) * 20.0

    return _clamp(score)


# ---------------------------------------------------------------------------
# Regime label helper
# ---------------------------------------------------------------------------

def _regime_label(close: float, sma50: float, sma200: float) -> str:
    if np.isnan(sma50) or np.isnan(sma200):
        return "UNKNOWN"
    above_200 = close > sma200
    above_50 = close > sma50
    if above_200 and above_50:
        return "ABOVE_BOTH"
    if above_200 and not above_50:
        return "ABOVE_200_BELOW_50"
    if not above_200 and above_50:
        return "BELOW_200_ABOVE_50"
    return "BELOW_BOTH"


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def build_momentum_snapshot(ticker: str, trade_date: str = None) -> Dict[str, Any]:
    """Load price history, compute regime-exit metrics, return structured dict.

    If trade_date is provided (YYYY-MM-DD), only rows up to and including that
    date are used. Returns {} on any failure.
    """
    try:
        from tradingagents.phase_engine import data_engine

        df = data_engine.load(ticker)

        if df is None or df.empty:
            return {}

        if trade_date is not None:
            cutoff = pd.to_datetime(trade_date)
            df = df[df["date"] <= cutoff].reset_index(drop=True)

        if df.empty:
            return {}

        n = len(df)

        # Data coverage tier
        if n < 252:
            data_coverage = 0.0
        elif n < 504:
            data_coverage = 0.5
        else:
            data_coverage = 1.0

        # Compute acceleration on full history (needed for expanding percentile)
        df = df.copy()
        df["accel"] = _compute_accel(df["close"], df["sma3"], lb=5)

        # Expanding percentile rank for momentum_health
        accel_pct_rank: float
        if n >= 252:
            expanding_pct = df["accel"].expanding(min_periods=252).rank(pct=True)
            last_pct = expanding_pct.iloc[-1]
            if np.isnan(last_pct):
                accel_pct_rank = 0.5
            else:
                accel_pct_rank = float(last_pct)
        else:
            accel_pct_rank = 0.5

        # Current row values
        last = df.iloc[-1]
        close = float(last["close"])
        sma3 = float(last["sma3"]) if "sma3" in df.columns else float("nan")
        sma10 = float(last["sma10"]) if "sma10" in df.columns else float("nan")
        sma20 = float(last["sma20"]) if "sma20" in df.columns else float("nan")
        sma50 = float(last["sma50"]) if "sma50" in df.columns else float("nan")
        sma200 = float(last["sma200"]) if "sma200" in df.columns else float("nan")
        volume = float(last["volume"]) if "volume" in df.columns else float("nan")
        vol_sma20 = float(last["vol_sma20"]) if "vol_sma20" in df.columns else float("nan")
        accel_value = float(last["accel"]) if not np.isnan(float(last["accel"])) else 0.0

        # CC overbought state machine on last 504 bars
        sm_result = _run_cc_overbought_window(df, holdout=3, window=504)
        invested_pct_2y = sm_result["invested_pct"]
        exits_ob = sm_result["exits_ob"]
        exits_fs = sm_result["exits_fs"]
        exits_dc = sm_result["exits_dc"]
        signal_state = sm_result["signal_state"]

        # Sub-scores
        trend_strength = _score_trend_strength(close, sma10, sma20, sma50, sma200)
        momentum_health = _score_momentum_health(accel_pct_rank) if n >= 252 else 50
        regime_quality = _score_regime_quality(invested_pct_2y, exits_ob, exits_fs, exits_dc)
        volume_confirmation = _score_volume_confirmation(volume, vol_sma20, close, sma20)

        # Composite
        composite_score = _clamp(
            trend_strength * 0.40
            + momentum_health * 0.30
            + regime_quality * 0.20
            + volume_confirmation * 0.10
        )

        if composite_score >= 65:
            direction = "BULLISH"
        elif composite_score <= 38:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        regime = _regime_label(close, sma50, sma200)

        return {
            "regime": regime,
            "signal_state": signal_state,
            "accel_percentile": round(accel_pct_rank, 4),
            "accel_value": round(accel_value, 8),
            "invested_pct_2y": invested_pct_2y,
            "days_of_history": n,
            "subscores": {
                "trend_strength": trend_strength,
                "momentum_health": momentum_health,
                "regime_quality": regime_quality,
                "volume_confirmation": volume_confirmation,
            },
            "composite_score": composite_score,
            "direction": direction,
            "data_coverage": data_coverage,
        }

    except Exception:
        return {}


def get_regime_state(ticker: str) -> Dict[str, Any]:
    """Lightweight regime check: regime, signal_state, accel_percentile.

    Used by CLI momentum-scan. Returns {} on failure.
    """
    try:
        from tradingagents.phase_engine import data_engine

        df = data_engine.load(ticker)

        if df is None or df.empty:
            return {}

        n = len(df)

        df = df.copy()
        df["accel"] = _compute_accel(df["close"], df["sma3"], lb=5)

        last = df.iloc[-1]
        close = float(last["close"])
        sma50 = float(last["sma50"]) if "sma50" in df.columns else float("nan")
        sma200 = float(last["sma200"]) if "sma200" in df.columns else float("nan")

        accel_pct_rank: float
        if n >= 252:
            expanding_pct = df["accel"].expanding(min_periods=252).rank(pct=True)
            last_pct = expanding_pct.iloc[-1]
            accel_pct_rank = float(last_pct) if not np.isnan(float(last_pct)) else 0.5
        else:
            accel_pct_rank = 0.5

        sm_result = _run_cc_overbought_window(df, holdout=3, window=504)
        signal_state = sm_result["signal_state"]
        regime = _regime_label(close, sma50, sma200)

        return {
            "regime": regime,
            "signal_state": signal_state,
            "accel_percentile": round(accel_pct_rank, 4),
        }

    except Exception:
        return {}
