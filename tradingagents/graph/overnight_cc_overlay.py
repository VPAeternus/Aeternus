"""Overnight CC Tactical Overlay — end-of-day covered call signal for QQQ.

Fires when conditions from the backtested overnight profile are met:
  1. QQQ above SMA200            (bull regime — hold shares)
  2. VIX drops ≥5% intraday      (fear compression = flat overnight)
  3. QQQ up ≥0.5% on the day    (risk-on confirmation)
  4. SMA3 > SMA10                (short-term momentum positive)

Backtest result (5 years, today-like + SMA3>SMA10, N=9):
  Avg overnight: +0.188% | % positive: 44.4% | StdDev: 0.476%
  → 55.6% chance QQQ drifts flat/down overnight (call expires worthless)
  P90 upside: +0.843% → suggested CC strike = current × 1.00843

WARNING: N=9 sample. Use as directional signal, not precise calibration.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import yfinance as yf


class OvernightCCRecommendation(str, Enum):
    SELL_OVERNIGHT_CC   = "SELL_OVERNIGHT_CC"
    HOLD_BEAR_REGIME    = "HOLD_BEAR_REGIME"    # QQQ below SMA200 — don't hold overnight
    HOLD_VIX_FLAT       = "HOLD_VIX_FLAT"       # VIX not compressing intraday
    HOLD_DOWN_DAY       = "HOLD_DOWN_DAY"        # QQQ not up on the day
    HOLD_MOMENTUM_WEAK  = "HOLD_MOMENTUM_WEAK"  # SMA3 < SMA10
    DATA_UNAVAILABLE    = "DATA_UNAVAILABLE"


@dataclass
class OvernightCCResult:
    recommendation: OvernightCCRecommendation
    as_of_date: str
    qqq_price: float
    qqq_open: float
    qqq_day_ret_pct: float          # (current - open) / open × 100
    sma200: float
    sma3: float
    sma10: float
    above_sma200: bool
    sma3_gt_sma10: bool
    vix_open: float
    vix_current: float
    vix_intraday_chg_pct: float     # (current - open) / open × 100
    vix_gate_ok: bool               # vix_intraday_chg_pct ≤ threshold (dropped enough)
    qqq_return_gate_ok: bool        # qqq_day_ret_pct ≥ min_return
    suggested_strike: float         # qqq_price × p90_multiplier, rounded to $0.50
    p90_multiplier: float           # config: overnight_cc_p90_strike_multiplier
    backtest_n: int                 # 9 — always show sample size
    rationale: str
    filter_reason: str
    regime_stats: Optional["RegimeStats"] = None


@dataclass
class RegimeStats:
    n: int
    mean_overnight_pct: float
    median_overnight_pct: float
    pct_positive: float          # 0-100
    pct_flat_down: float         # 0-100
    std_dev: float
    p10: float
    p90: float
    best: float
    worst: float
    vix_regime_label: str        # "low (<20)", "mid (20-28)", "high (>28)"
    vix_regime_n: int
    vix_regime_mean: float
    vix_regime_pct_flat_down: float
    pct_below_strike: float      # % of nights where overnight move < strike threshold
    cc_edge_vs_signal: str
    gate_profile: str            # e.g. "T-F-T-F"


def _vix_band_label(vix: float) -> str:
    if vix < 20:
        return "low (<20)"
    elif vix <= 28:
        return "mid (20-28)"
    else:
        return "high (>28)"


def _vix_in_band(vix: float, band_label: str) -> bool:
    if band_label == "low (<20)":
        return vix < 20
    elif band_label == "mid (20-28)":
        return 20 <= vix <= 28
    else:
        return vix > 28


def compute_regime_stats(
    gate_profile: tuple,
    current_vix: float,
    p90_multiplier: float = 1.00843,
    vix_threshold_pct: float = -5.0,
    qqq_min_return_pct: float = 0.5,
) -> Optional[RegimeStats]:
    """Compute historical overnight return stats for a given gate profile.

    Downloads full QQQ + VIX history via yfinance (period='max') and
    classifies each historical day by its gate profile, then computes
    overnight return (next-day open vs today's close) statistics for
    matching days.
    """
    import numpy as np
    import pandas as pd

    try:
        qqq = yf.download("QQQ", period="max", interval="1d", auto_adjust=True, progress=False)
        vix = yf.download("^VIX", period="max", interval="1d", auto_adjust=True, progress=False)

        if hasattr(qqq.columns, "levels"):
            qqq.columns = qqq.columns.get_level_values(0)
        if hasattr(vix.columns, "levels"):
            vix.columns = vix.columns.get_level_values(0)

        qqq = qqq.dropna(subset=["Open", "Close"])
        vix = vix.dropna(subset=["Open", "Close"])

        if len(qqq) < 250:
            return None

        vix_close = vix["Close"].reindex(qqq.index, method="ffill")
        vix_open = vix["Open"].reindex(qqq.index, method="ffill")

        qqq_close = qqq["Close"]
        qqq_open_col = qqq["Open"]
        sma200 = qqq_close.rolling(200).mean()
        sma3 = qqq_close.rolling(3).mean()
        sma10 = qqq_close.rolling(10).mean()
        day_ret_pct = (qqq_close - qqq_open_col) / qqq_open_col * 100
        vix_intraday_pct = (vix_close - vix_open) / vix_open * 100

        g_above_sma200 = qqq_close > sma200
        g_vix_drop = vix_intraday_pct <= vix_threshold_pct
        g_qqq_up = day_ret_pct >= qqq_min_return_pct
        g_sma3_gt_sma10 = sma3 > sma10

        next_open = qqq_open_col.shift(-1)
        overnight_ret_pct = (next_open - qqq_close) / qqq_close * 100

        df = pd.DataFrame({
            "g1": g_above_sma200,
            "g2": g_vix_drop,
            "g3": g_qqq_up,
            "g4": g_sma3_gt_sma10,
            "overnight": overnight_ret_pct,
            "vix_close": vix_close,
        }).dropna()

        if len(df) < 50:
            return None

        ab, vg, qr, sm = gate_profile
        mask = (df["g1"] == ab) & (df["g2"] == vg) & (df["g3"] == qr) & (df["g4"] == sm)
        matched = df.loc[mask, "overnight"]

        if len(matched) < 5:
            return None

        arr = matched.values
        n = len(arr)
        mean_val = float(np.mean(arr))
        median_val = float(np.median(arr))
        std_val = float(np.std(arr, ddof=1)) if n > 1 else 0.0
        pct_pos = float(np.sum(arr > 0) / n * 100)
        pct_flat_down = 100.0 - pct_pos
        p10 = float(np.percentile(arr, 10))
        p90 = float(np.percentile(arr, 90))
        best = float(np.max(arr))
        worst = float(np.min(arr))

        vix_band = _vix_band_label(current_vix)
        vix_matched = df.loc[mask]
        vix_slice = vix_matched[vix_matched["vix_close"].apply(lambda v: _vix_in_band(v, vix_band))]
        vix_rets = vix_slice["overnight"].values
        vix_n = len(vix_rets)
        vix_mean = float(np.mean(vix_rets)) if vix_n > 0 else 0.0
        vix_pct_flat_down = float(np.sum(vix_rets <= 0) / vix_n * 100) if vix_n > 0 else 0.0

        # CC seller edge: what % of nights stay below the P90 strike?
        strike_threshold_pct = (p90_multiplier - 1.0) * 100  # e.g. 0.843%
        pct_below_strike = float(np.sum(arr < strike_threshold_pct) / n * 100)

        # Compare to all-gates-pass baseline
        all_pass = (df["g1"] == True) & (df["g2"] == True) & (df["g3"] == True) & (df["g4"] == True)
        signal_rets = df.loc[all_pass, "overnight"].values
        if len(signal_rets) >= 5:
            signal_below_strike = float(np.sum(signal_rets < strike_threshold_pct) / len(signal_rets) * 100)
        else:
            signal_below_strike = 0.0

        # Frame edge from CC seller perspective: overnight gap risk
        if pct_below_strike >= 90:
            edge = f"Call opens OTM {pct_below_strike:.0f}% of nights like this — overnight theta captured, still decaying into 4 PM"
        elif pct_below_strike >= 80:
            edge = f"Call opens OTM {pct_below_strike:.0f}% of nights like this — favorable overnight theta"
        elif pct_below_strike >= 70:
            edge = f"Call opens OTM {pct_below_strike:.0f}% of nights like this — moderate overnight theta"
        else:
            edge = f"Call opens OTM only {pct_below_strike:.0f}% of nights like this — gap risk elevated, size down"

        if len(signal_rets) >= 5 and signal_below_strike > 0:
            edge += f" (vs {signal_below_strike:.0f}% on signal days)"

        profile_str = "-".join("T" if g else "F" for g in gate_profile)

        return RegimeStats(
            n=n,
            mean_overnight_pct=mean_val,
            median_overnight_pct=median_val,
            pct_positive=pct_pos,
            pct_flat_down=pct_flat_down,
            std_dev=std_val,
            p10=p10,
            p90=p90,
            best=best,
            worst=worst,
            vix_regime_label=vix_band,
            vix_regime_n=vix_n,
            vix_regime_mean=vix_mean,
            vix_regime_pct_flat_down=vix_pct_flat_down,
            pct_below_strike=pct_below_strike,
            cc_edge_vs_signal=edge,
            gate_profile=profile_str,
        )

    except Exception:
        return None


def evaluate_overnight_cc(
    as_of_date: Optional[str] = None,
    config: Optional[dict] = None,
) -> OvernightCCResult:
    """Evaluate end-of-day conditions for selling an overnight covered call on QQQ.

    Args:
        as_of_date: ISO date string for logging (does not filter data).
        config: Optional config overrides. Keys:
            overnight_cc_vix_drop_threshold_pct  (default -5.0)
            overnight_cc_qqq_min_return_pct      (default 0.5)
            overnight_cc_p90_strike_multiplier   (default 1.00843)

    Returns:
        OvernightCCResult with recommendation and suggested strike.
    """
    import datetime

    cfg = config or {}
    vix_threshold = float(cfg.get("overnight_cc_vix_drop_threshold_pct", -5.0))
    qqq_min_return = float(cfg.get("overnight_cc_qqq_min_return_pct", 0.5))
    p90_multiplier = float(cfg.get("overnight_cc_p90_strike_multiplier", 1.00843))

    date_str = as_of_date or datetime.date.today().isoformat()

    def _unavailable(reason: str) -> OvernightCCResult:
        return OvernightCCResult(
            recommendation=OvernightCCRecommendation.DATA_UNAVAILABLE,
            as_of_date=date_str,
            qqq_price=0.0, qqq_open=0.0, qqq_day_ret_pct=0.0,
            sma200=0.0, sma3=0.0, sma10=0.0,
            above_sma200=False, sma3_gt_sma10=False,
            vix_open=0.0, vix_current=0.0, vix_intraday_chg_pct=0.0,
            vix_gate_ok=False, qqq_return_gate_ok=False,
            suggested_strike=0.0, p90_multiplier=p90_multiplier,
            backtest_n=9,
            rationale=f"Data unavailable: {reason}",
            filter_reason="DATA_ERROR",
        )

    try:
        # QQQ — need 30d for SMA10, today's OHLC
        qqq_raw = yf.download(
            "QQQ", period="260d", interval="1d", auto_adjust=True, progress=False
        )
        vix_raw = yf.download(
            "^VIX", period="5d", interval="1d", auto_adjust=True, progress=False
        )

        if hasattr(qqq_raw.columns, "levels"):
            qqq_raw.columns = qqq_raw.columns.get_level_values(0)
        if hasattr(vix_raw.columns, "levels"):
            vix_raw.columns = vix_raw.columns.get_level_values(0)

        qqq_raw = qqq_raw.dropna()
        vix_raw = vix_raw.dropna()

        if len(qqq_raw) < 10 or len(vix_raw) < 1:
            return _unavailable("Insufficient price history")

        # Current QQQ values
        qqq_price = float(qqq_raw["Close"].iloc[-1])
        qqq_open = float(qqq_raw["Open"].iloc[-1])
        qqq_day_ret_pct = (qqq_price - qqq_open) / qqq_open * 100

        # SMA calculations
        sma200 = float(qqq_raw["Close"].rolling(200).mean().iloc[-1])
        sma10 = float(qqq_raw["Close"].rolling(10).mean().iloc[-1])
        sma3 = float(qqq_raw["Close"].rolling(3).mean().iloc[-1])

        # VIX intraday
        vix_open = float(vix_raw["Open"].iloc[-1])
        vix_current = float(vix_raw["Close"].iloc[-1])
        vix_intraday_chg_pct = (vix_current - vix_open) / vix_open * 100

        # Gate evaluations
        above_sma200 = qqq_price > sma200
        sma3_gt_sma10 = sma3 > sma10
        vix_gate_ok = vix_intraday_chg_pct <= vix_threshold        # VIX dropped enough
        qqq_return_gate_ok = qqq_day_ret_pct >= qqq_min_return     # QQQ up enough

        # Suggested strike: P90 overnight upside, rounded to nearest $0.50
        raw_strike = qqq_price * p90_multiplier
        suggested_strike = round(raw_strike * 2) / 2  # nearest $0.50

        # Compute historical regime stats for today's gate profile
        gate_profile = (above_sma200, vix_gate_ok, qqq_return_gate_ok, sma3_gt_sma10)
        regime_stats = compute_regime_stats(
            gate_profile=gate_profile,
            current_vix=vix_current,
            p90_multiplier=p90_multiplier,
            vix_threshold_pct=vix_threshold,
            qqq_min_return_pct=qqq_min_return,
        )

        # Decision logic — gates in priority order
        if not above_sma200:
            pct_below = (sma200 - qqq_price) / sma200 * 100
            return OvernightCCResult(
                recommendation=OvernightCCRecommendation.HOLD_BEAR_REGIME,
                as_of_date=date_str,
                qqq_price=qqq_price, qqq_open=qqq_open,
                qqq_day_ret_pct=qqq_day_ret_pct,
                sma200=sma200, sma3=sma3, sma10=sma10,
                above_sma200=above_sma200, sma3_gt_sma10=sma3_gt_sma10,
                vix_open=vix_open, vix_current=vix_current,
                vix_intraday_chg_pct=vix_intraday_chg_pct,
                vix_gate_ok=vix_gate_ok, qqq_return_gate_ok=qqq_return_gate_ok,
                suggested_strike=suggested_strike, p90_multiplier=p90_multiplier,
                backtest_n=9,
                rationale=(
                    f"QQQ {pct_below:.1f}% below SMA200 — bear regime. "
                    "Hold cash, no overnight CC."
                ),
                filter_reason="BEAR_REGIME",
                regime_stats=regime_stats,
            )

        if not vix_gate_ok:
            return OvernightCCResult(
                recommendation=OvernightCCRecommendation.HOLD_VIX_FLAT,
                as_of_date=date_str,
                qqq_price=qqq_price, qqq_open=qqq_open,
                qqq_day_ret_pct=qqq_day_ret_pct,
                sma200=sma200, sma3=sma3, sma10=sma10,
                above_sma200=above_sma200, sma3_gt_sma10=sma3_gt_sma10,
                vix_open=vix_open, vix_current=vix_current,
                vix_intraday_chg_pct=vix_intraday_chg_pct,
                vix_gate_ok=vix_gate_ok, qqq_return_gate_ok=qqq_return_gate_ok,
                suggested_strike=suggested_strike, p90_multiplier=p90_multiplier,
                backtest_n=9,
                rationale=(
                    f"VIX intraday change {vix_intraday_chg_pct:+.1f}% "
                    f"(need ≤{vix_threshold:.0f}%). "
                    "VIX not compressing enough — overnight profile inconclusive."
                ),
                filter_reason="VIX_NOT_DROPPING",
                regime_stats=regime_stats,
            )

        if not qqq_return_gate_ok:
            return OvernightCCResult(
                recommendation=OvernightCCRecommendation.HOLD_DOWN_DAY,
                as_of_date=date_str,
                qqq_price=qqq_price, qqq_open=qqq_open,
                qqq_day_ret_pct=qqq_day_ret_pct,
                sma200=sma200, sma3=sma3, sma10=sma10,
                above_sma200=above_sma200, sma3_gt_sma10=sma3_gt_sma10,
                vix_open=vix_open, vix_current=vix_current,
                vix_intraday_chg_pct=vix_intraday_chg_pct,
                vix_gate_ok=vix_gate_ok, qqq_return_gate_ok=qqq_return_gate_ok,
                suggested_strike=suggested_strike, p90_multiplier=p90_multiplier,
                backtest_n=9,
                rationale=(
                    f"QQQ day return {qqq_day_ret_pct:+.2f}% "
                    f"(need ≥+{qqq_min_return:.1f}%). "
                    "Not a strong up day — overnight CC profile not triggered."
                ),
                filter_reason="QQQ_NOT_UP",
                regime_stats=regime_stats,
            )

        if not sma3_gt_sma10:
            return OvernightCCResult(
                recommendation=OvernightCCRecommendation.HOLD_MOMENTUM_WEAK,
                as_of_date=date_str,
                qqq_price=qqq_price, qqq_open=qqq_open,
                qqq_day_ret_pct=qqq_day_ret_pct,
                sma200=sma200, sma3=sma3, sma10=sma10,
                above_sma200=above_sma200, sma3_gt_sma10=sma3_gt_sma10,
                vix_open=vix_open, vix_current=vix_current,
                vix_intraday_chg_pct=vix_intraday_chg_pct,
                vix_gate_ok=vix_gate_ok, qqq_return_gate_ok=qqq_return_gate_ok,
                suggested_strike=suggested_strike, p90_multiplier=p90_multiplier,
                backtest_n=9,
                rationale=(
                    f"SMA3 (${sma3:.2f}) < SMA10 (${sma10:.2f}) — "
                    "momentum not confirmed. Overnight distribution widens without this filter."
                ),
                filter_reason="MOMENTUM_WEAK",
                regime_stats=regime_stats,
            )

        # All gates passed
        pct_above = (qqq_price - sma200) / sma200 * 100
        return OvernightCCResult(
            recommendation=OvernightCCRecommendation.SELL_OVERNIGHT_CC,
            as_of_date=date_str,
            qqq_price=qqq_price, qqq_open=qqq_open,
            qqq_day_ret_pct=qqq_day_ret_pct,
            sma200=sma200, sma3=sma3, sma10=sma10,
            above_sma200=above_sma200, sma3_gt_sma10=sma3_gt_sma10,
            vix_open=vix_open, vix_current=vix_current,
            vix_intraday_chg_pct=vix_intraday_chg_pct,
            vix_gate_ok=vix_gate_ok, qqq_return_gate_ok=qqq_return_gate_ok,
            suggested_strike=suggested_strike, p90_multiplier=p90_multiplier,
            backtest_n=9,
            rationale=(
                f"All gates passed. QQQ {pct_above:.1f}% above SMA200, "
                f"up {qqq_day_ret_pct:+.2f}% today. "
                f"VIX compressed {vix_intraday_chg_pct:+.1f}% intraday. "
                f"SMA3 > SMA10. "
                f"Backtest: 55.6% chance flat/down overnight (N={9}). "
                f"Sell QQQ ${suggested_strike:.2f} call before 4:15 PM ET."
            ),
            filter_reason="",
            regime_stats=regime_stats,
        )

    except Exception as exc:
        return _unavailable(str(exc))
