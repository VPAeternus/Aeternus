#!/usr/bin/env python3
"""Backtest bullish-FVG support-break shorts.

Adaptive V2 research logic.

Locked structure:
- Bullish FVG forms when low[t] > high[t-2].
- Support line = low of latest active bullish FVG.
- Support only ratchets higher when a newer bullish FVG low is higher.
- When daily close breaks below support, that support dies.
- Short entry = next day open.
- Stop = max(break-day high, broken support).
- Skip trade if next open is at/above stop.
- Default target = 3R.

Important execution assumption:
- Gap filters use the next day's actual open.
- This assumes execution after the opening print / immediately at open liquidity,
  not a blind market-on-open order submitted before the open.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

import data_cache


DEFAULT_VARIANT = "r3-v5-priority"
DEFAULT_R_MULTIPLES = [3.0]


VARIANT_CHOICES = [
    "adaptive-v1",
    "adaptive-v2",
    "adaptive-v2-extreme-research",
    "legacy",
    "r3-core",
    "r3-v5-broad",
    "r3-v5-priority",
    "r3-v5-conviction",
    "r3-v5-a-plus",
    "r3-v5-fresh",
    # Backward-compatible alias.
    "r3-v5-high-conviction",
]


@dataclass
class SupportBreakTrade:
    ticker: str
    variant: str

    # FVG/support anatomy
    fvg_form_date: pd.Timestamp
    fvg_age_bars: int
    fvg_age_calendar_days: int
    fvg_low: float
    fvg_gap_size: float
    fvg_gap_pct: float
    support_ratcheted_count: int

    # Break-day anatomy
    break_date: pd.Timestamp
    broken_support: float
    break_high: float
    break_low: float
    break_close: float
    break_range_pct: float
    support_distance_pct: float
    stop_source: str

    # Entry/exit
    entry_date: pd.Timestamp
    entry: float
    stop: float
    risk: float
    r_multiple: float
    target: float
    exit_date: pd.Timestamp
    exit_price: float
    reason: str
    pnl: float
    realized_R: float
    hold_days: int

    # Diagnostics / filters
    prior_close: float
    prior_sma5: float
    prior_sma10: float
    prior_sma20: float
    prior_sma200: float
    ret5: float
    gap_pct: float
    risk_pct: float
    close_vs_sma5: float
    close_vs_sma10: float
    sma10_sma20_spread: float
    sma20_sma200_spread: float
    atr14: float
    risk_atr: float
    volume_zscore_20: float
    vol_profile: str
    vol_regime: str
    atr_pct: float
    atr_pct_252_median: float
    bearish_fvg: bool
    bearish_fvg_gap_size: float
    bearish_fvg_gap_pct: float
    bearish_fvg_count_3: float
    bearish_fvg_count_5: float
    bearish_fvg_count_since_support: int
    bearish_fvg_sequence_max_since_support: int
    last_bearish_fvg_age_bars: int
    bearish_fvg_gap_sum_since_support: float
    bearish_fvg_gap_max_since_support: float
    bearish_fvg_after_support_before_break: bool
    bearish_confirmation_source: str
    has_break_day_bearish_fvg: bool
    has_bearish_fvg_sequence: bool
    has_bearish_fvg_since_support: bool
    has_range_displacement: bool


@dataclass
class BearishConfirmation:
    source: str
    has_break_day_bearish_fvg: bool
    has_bearish_fvg_sequence: bool
    has_bearish_fvg_since_support: bool
    has_range_displacement: bool


@dataclass
class AdaptiveV2Check:
    passed: bool
    vol_profile: str
    reject_reasons: list[str]
    bearish_confirmation_source: str
    has_break_day_bearish_fvg: bool
    has_bearish_fvg_sequence: bool
    has_bearish_fvg_since_support: bool
    has_range_displacement: bool


def _ratio(numerator: float, denominator: float) -> float:
    if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
        return float("nan")
    return float(numerator) / float(denominator)


def normalize_variant(variant: str) -> str:
    """Keep old CLI name working, but map it to the final conviction variant."""
    if variant == "r3-v5-high-conviction":
        return "r3-v5-conviction"
    return variant


def variant_metrics(row: pd.Series, entry: float, stop: float) -> dict[str, float]:
    close = float(row["close"])
    sma5 = float(row["sma5"])
    sma10 = float(row["sma10"])
    sma20 = float(row["sma20"])
    sma200 = float(row["sma200"])
    atr14 = float(row["atr14"]) if not pd.isna(row["atr14"]) else float("nan")
    risk = stop - entry

    return {
        "ret5": float(row["ret5"]) if not pd.isna(row["ret5"]) else float("nan"),
        "gap_pct": _ratio(entry - close, close),
        "risk_pct": _ratio(risk, entry),
        "close_vs_sma5": _ratio(close - sma5, sma5),
        "close_vs_sma10": _ratio(close - sma10, sma10),
        "sma10_sma20_spread": _ratio(sma10 - sma20, sma20),
        "sma20_sma200_spread": _ratio(sma20 - sma200, sma200),
        "risk_atr": _ratio(risk, atr14),
        "atr_pct": float(row["atr_pct"]) if "atr_pct" in row and not pd.isna(row["atr_pct"]) else float("nan"),
    }


def has_required_indicators(row: pd.Series) -> bool:
    required = ["sma5", "sma10", "sma20", "sma200", "ret5", "atr14"]
    return all(col in row and not pd.isna(row[col]) for col in required)


def old_r3_core_ok(row: pd.Series, metrics: dict[str, float]) -> bool:
    """Original R3-style structural filter."""
    return bool(
        metrics["gap_pct"] > 0
        and metrics["ret5"] <= 0.018
        and float(row["sma10"]) > float(row["sma20"]) > float(row["sma200"])
        and (
            float(row["close"]) > float(row["sma10"])
            or (
                float(row["close"]) < float(row["sma20"])
                and float(row["close"]) > float(row["sma200"])
            )
        )
    )


def classify_vol_profile(row: pd.Series) -> str:
    """Point-in-time volatility profile from break-day ATR%."""
    atr_pct = float(row["atr_pct"]) if "atr_pct" in row and not pd.isna(row["atr_pct"]) else float("nan")

    if pd.isna(atr_pct):
        return "UNKNOWN_VOL"
    if atr_pct < 0.018:
        return "LOW_VOL"
    if atr_pct < 0.030:
        return "MID_VOL"
    if atr_pct < 0.060:
        return "HIGH_VOL"
    return "EXTREME_VOL"


def classify_vol_regime(row: pd.Series) -> str:
    """Relative volatility regime versus ticker's own 252-day ATR% median."""
    atr_pct = float(row["atr_pct"]) if "atr_pct" in row and not pd.isna(row["atr_pct"]) else float("nan")
    atr_median = (
        float(row["atr_pct_252_median"])
        if "atr_pct_252_median" in row and not pd.isna(row["atr_pct_252_median"])
        else float("nan")
    )

    if pd.isna(atr_pct) or pd.isna(atr_median) or atr_median <= 0:
        return "UNKNOWN_RELATIVE_VOL"

    vol_ratio = atr_pct / atr_median

    if vol_ratio > 1.75:
        return "ELEVATED_RELATIVE_VOL"
    if vol_ratio < 0.75:
        return "QUIET_RELATIVE_VOL"
    return "NORMAL_RELATIVE_VOL"


def low_vol_profile_ok(
    row: pd.Series,
    metrics: dict[str, float],
    stop_source: str,
    break_range_pct: float,
    fvg_age_bars: int,
) -> bool:
    old_core = old_r3_core_ok(row, metrics)

    return bool(
        old_core
        and 0.0025 <= metrics["risk_pct"] <= 0.025
        and -0.015 < metrics["close_vs_sma10"] <= 0.0125
        and metrics["sma20_sma200_spread"] > 0.085
        and metrics["risk_atr"] <= 1.5
        and stop_source == "BREAK_HIGH"
        and metrics["gap_pct"] >= 0.0025
    )


def mid_vol_profile_ok(
    row: pd.Series,
    metrics: dict[str, float],
    stop_source: str,
    break_range_pct: float,
    fvg_age_bars: int,
) -> bool:
    atr_pct = float(row["atr_pct"])
    trend_ok = (
        float(row["sma20"]) > float(row["sma200"])
        and metrics["sma20_sma200_spread"] > 0.06
    )
    ret5_ok = metrics["ret5"] <= max(0.018, 0.75 * atr_pct)
    close_location_ok = -0.020 < metrics["close_vs_sma10"] <= 0.015

    return bool(
        trend_ok
        and ret5_ok
        and close_location_ok
        and 0.0035 <= metrics["risk_pct"] <= 0.035
        and 0.15 <= metrics["risk_atr"] <= 1.75
        and stop_source == "BREAK_HIGH"
        and metrics["gap_pct"] >= 0.0025
    )


def high_vol_profile_ok(
    row: pd.Series,
    metrics: dict[str, float],
    stop_source: str,
    break_range_pct: float,
    fvg_age_bars: int,
) -> bool:
    atr_pct = float(row["atr_pct"])
    long_term_trend_ok = (
        float(row["close"]) > float(row["sma200"])
        and metrics["sma20_sma200_spread"] > 0.05
    )
    ret5_ok = metrics["ret5"] <= max(0.025, 1.00 * atr_pct)
    close_location_ok = -0.035 < metrics["close_vs_sma10"] <= 0.020
    risk_ok = (
        0.005 <= metrics["risk_pct"] <= min(0.075, 1.50 * atr_pct)
        and 0.15 <= metrics["risk_atr"] <= 1.75
    )
    gap_ok = metrics["gap_pct"] >= max(0.005, 0.15 * atr_pct)
    bearish_displacement_ok = (
        float(row.get("bearish_fvg_count_3", 0)) >= 1
        or float(row.get("bearish_fvg_count_5", 0)) >= 2
        or break_range_pct >= 0.75 * atr_pct
    )

    return bool(
        long_term_trend_ok
        and ret5_ok
        and close_location_ok
        and risk_ok
        and gap_ok
        and bearish_displacement_ok
        and stop_source == "BREAK_HIGH"
    )


def extreme_vol_profile_ok(
    row: pd.Series,
    metrics: dict[str, float],
    stop_source: str,
    break_range_pct: float,
    fvg_age_bars: int,
) -> bool:
    atr_pct = float(row["atr_pct"])
    trend_ok = float(row["close"]) > float(row["sma200"])
    ret5_ok = metrics["ret5"] <= max(0.04, 1.25 * atr_pct)
    risk_ok = (
        0.0075 <= metrics["risk_pct"] <= min(0.10, 1.75 * atr_pct)
        and 0.10 <= metrics["risk_atr"] <= 2.00
    )
    gap_ok = metrics["gap_pct"] >= max(0.0075, 0.12 * atr_pct)
    bearish_displacement_ok = (
        float(row.get("bearish_fvg_count_3", 0)) >= 1
        or float(row.get("bearish_fvg_count_5", 0)) >= 2
        or break_range_pct >= 0.80 * atr_pct
    )

    return bool(
        trend_ok
        and ret5_ok
        and risk_ok
        and gap_ok
        and bearish_displacement_ok
        and stop_source == "BREAK_HIGH"
    )


def adaptive_profile_ok(
    row: pd.Series,
    entry: float,
    stop: float,
    stop_source: str,
    fvg_age_bars: int,
    break_range_pct: float,
) -> tuple[bool, str]:
    """Return whether trade passes and which volatility profile was used."""
    if not has_required_indicators(row):
        return False, "MISSING_INDICATORS"

    risk = stop - entry
    if risk <= 0:
        return False, "INVALID_RISK"

    metrics = variant_metrics(row, entry, stop)
    profile = classify_vol_profile(row)

    if profile == "LOW_VOL":
        return low_vol_profile_ok(row, metrics, stop_source, break_range_pct, fvg_age_bars), profile
    if profile == "MID_VOL":
        return mid_vol_profile_ok(row, metrics, stop_source, break_range_pct, fvg_age_bars), profile
    if profile == "HIGH_VOL":
        return high_vol_profile_ok(row, metrics, stop_source, break_range_pct, fvg_age_bars), profile
    if profile == "EXTREME_VOL":
        return extreme_vol_profile_ok(row, metrics, stop_source, break_range_pct, fvg_age_bars), profile

    return False, profile


def get_bearish_confirmation(
    row: pd.Series,
    atr_pct: float,
    break_range_pct: float,
    bearish_fvg_count_since_support: int,
    bearish_fvg_sequence_max_since_support: int,
) -> BearishConfirmation:
    has_break_day_bearish_fvg = bool(row.get("bearish_fvg", False))
    has_bearish_fvg_sequence = bearish_fvg_sequence_max_since_support >= 2
    has_bearish_fvg_since_support = bearish_fvg_count_since_support >= 1
    has_range_displacement = bool(
        not pd.isna(break_range_pct)
        and not pd.isna(atr_pct)
        and break_range_pct >= 0.75 * atr_pct
    )

    if has_break_day_bearish_fvg:
        source = "BREAK_DAY_BEARISH_FVG"
    elif has_bearish_fvg_sequence:
        source = "BEARISH_FVG_SEQUENCE"
    elif has_bearish_fvg_since_support:
        source = "BEARISH_FVG_SINCE_SUPPORT"
    elif has_range_displacement:
        source = "RANGE_DISPLACEMENT"
    else:
        source = "NONE"

    return BearishConfirmation(
        source=source,
        has_break_day_bearish_fvg=has_break_day_bearish_fvg,
        has_bearish_fvg_sequence=has_bearish_fvg_sequence,
        has_bearish_fvg_since_support=has_bearish_fvg_since_support,
        has_range_displacement=has_range_displacement,
    )


def _adaptive_v2_result(
    passed: bool,
    profile: str,
    reasons: list[str],
    confirmation: BearishConfirmation | None = None,
) -> AdaptiveV2Check:
    if confirmation is None:
        confirmation = BearishConfirmation("NONE", False, False, False, False)

    return AdaptiveV2Check(
        passed=passed,
        vol_profile=profile,
        reject_reasons=[] if passed else reasons,
        bearish_confirmation_source=confirmation.source,
        has_break_day_bearish_fvg=confirmation.has_break_day_bearish_fvg,
        has_bearish_fvg_sequence=confirmation.has_bearish_fvg_sequence,
        has_bearish_fvg_since_support=confirmation.has_bearish_fvg_since_support,
        has_range_displacement=confirmation.has_range_displacement,
    )


def adaptive_v2_check(
    variant: str,
    row: pd.Series,
    entry: float,
    stop: float,
    stop_source: str,
    fvg_age_bars: int,
    break_range_pct: float,
    support_distance_pct: float,
    bearish_fvg_count_since_support: int = 0,
    bearish_fvg_sequence_max_since_support: int = 0,
    bearish_fvg_gap_sum_since_support: float = 0.0,
    bearish_fvg_gap_max_since_support: float = 0.0,
) -> AdaptiveV2Check:
    del bearish_fvg_gap_sum_since_support, bearish_fvg_gap_max_since_support
    variant = normalize_variant(variant)

    if not has_required_indicators(row):
        return _adaptive_v2_result(False, "MISSING_INDICATORS", ["MISSING_INDICATORS"])

    risk = stop - entry
    if risk <= 0:
        return _adaptive_v2_result(False, "INVALID_RISK", ["INVALID_RISK"])

    metrics = variant_metrics(row, entry, stop)
    profile = classify_vol_profile(row)
    atr_pct = metrics["atr_pct"]
    confirmation = get_bearish_confirmation(
        row=row,
        atr_pct=atr_pct,
        break_range_pct=break_range_pct,
        bearish_fvg_count_since_support=bearish_fvg_count_since_support,
        bearish_fvg_sequence_max_since_support=bearish_fvg_sequence_max_since_support,
    )
    reasons: list[str] = []

    if profile not in {"LOW_VOL", "MID_VOL", "HIGH_VOL", "EXTREME_VOL"}:
        return _adaptive_v2_result(False, profile, ["UNKNOWN_VOL_PROFILE"], confirmation)

    if variant == "adaptive-v2-extreme-research" and profile != "EXTREME_VOL":
        return _adaptive_v2_result(False, profile, ["NOT_EXTREME_VOL"], confirmation)

    if variant == "adaptive-v2" and profile == "EXTREME_VOL":
        return _adaptive_v2_result(False, profile, ["EXTREME_VOL_DISABLED"], confirmation)

    if variant == "adaptive-v2-extreme-research":
        trend_ok = float(row["close"]) > float(row["sma200"])
        ret5_ok = metrics["ret5"] <= max(0.04, 1.25 * atr_pct)
        risk_pct_ok = 0.0075 <= metrics["risk_pct"] <= min(0.10, 1.75 * atr_pct)
        risk_atr_ok = 0.25 <= metrics["risk_atr"] <= 0.75
        gap_ok = max(0.0075, 0.12 * atr_pct) <= metrics["gap_pct"] <= 0.020
        support_distance_ok = -0.015 <= support_distance_pct < 0
        fvg_age_ok = fvg_age_bars <= 3
        bearish_ok = confirmation.source != "NONE"

        if not trend_ok:
            reasons.append("TREND")
        if not ret5_ok:
            reasons.append("RET5")
        if not risk_pct_ok:
            reasons.append("RISK_PCT")
        if not risk_atr_ok:
            reasons.append("RISK_ATR")
        if not gap_ok:
            reasons.append("GAP")
        if not support_distance_ok:
            reasons.append("SUPPORT_DISTANCE")
        if not fvg_age_ok:
            reasons.append("FVG_AGE")
        if stop_source != "BREAK_HIGH":
            reasons.append("STOP_SOURCE")
        if not bearish_ok:
            reasons.append("BEARISH_SEQUENCE")

        return _adaptive_v2_result(not reasons, profile, reasons, confirmation)

    if profile == "LOW_VOL":
        old_core = old_r3_core_ok(row, metrics)
        risk_pct_ok = 0.0025 <= metrics["risk_pct"] <= 0.025
        close_vs_sma10_ok = -0.015 < metrics["close_vs_sma10"] <= 0.0125
        trend_spread_ok = metrics["sma20_sma200_spread"] > 0.085
        risk_atr_ok = 0.25 <= metrics["risk_atr"] <= 1.00
        gap_ok = 0.0025 <= metrics["gap_pct"] <= 0.010
        support_distance_ok = -0.010 <= support_distance_pct < 0
        fvg_age_ok = fvg_age_bars <= 1

        if not old_core or not trend_spread_ok:
            reasons.append("TREND")
        if metrics["ret5"] > 0.018:
            reasons.append("RET5")
        if not risk_pct_ok:
            reasons.append("RISK_PCT")
        if not risk_atr_ok:
            reasons.append("RISK_ATR")
        if not gap_ok:
            reasons.append("GAP")
        if not close_vs_sma10_ok:
            reasons.append("CLOSE_VS_SMA10")
        if stop_source != "BREAK_HIGH":
            reasons.append("STOP_SOURCE")
        if not support_distance_ok:
            reasons.append("SUPPORT_DISTANCE")
        if not fvg_age_ok:
            reasons.append("FVG_AGE")

        return _adaptive_v2_result(not reasons, profile, reasons, confirmation)

    if profile == "MID_VOL":
        trend_ok = float(row["sma20"]) > float(row["sma200"]) and metrics["sma20_sma200_spread"] > 0.06
        ret5_ok = metrics["ret5"] <= max(0.018, 0.75 * atr_pct)
        close_vs_sma10_ok = -0.020 < metrics["close_vs_sma10"] <= 0.015
        risk_pct_ok = 0.0035 <= metrics["risk_pct"] <= 0.035
        risk_atr_ok = 0.25 <= metrics["risk_atr"] <= 1.00
        gap_ok = 0.0025 <= metrics["gap_pct"] <= 0.010
        support_distance_ok = -0.010 <= support_distance_pct < 0
        fvg_age_ok = fvg_age_bars <= 1

        if not trend_ok:
            reasons.append("TREND")
        if not ret5_ok:
            reasons.append("RET5")
        if not close_vs_sma10_ok:
            reasons.append("CLOSE_VS_SMA10")
        if not risk_pct_ok:
            reasons.append("RISK_PCT")
        if not risk_atr_ok:
            reasons.append("RISK_ATR")
        if stop_source != "BREAK_HIGH":
            reasons.append("STOP_SOURCE")
        if not gap_ok:
            reasons.append("GAP")
        if not support_distance_ok:
            reasons.append("SUPPORT_DISTANCE")
        if not fvg_age_ok:
            reasons.append("FVG_AGE")

        return _adaptive_v2_result(not reasons, profile, reasons, confirmation)

    if profile == "HIGH_VOL":
        near_sma10 = 0.0 < metrics["close_vs_sma10"] <= 0.0125
        below_sma10_range = -0.020 < metrics["close_vs_sma10"] <= 0.0
        below_sma10_confirmed = (
            below_sma10_range
            and fvg_age_bars <= 3
            and 0.25 <= metrics["risk_atr"] <= 0.75
            and metrics["gap_pct"] <= 0.010
        )
        trend_ok = float(row["close"]) > float(row["sma200"]) and metrics["sma20_sma200_spread"] > 0.05
        ret5_ok = metrics["ret5"] <= max(0.025, 1.00 * atr_pct)
        risk_pct_ok = 0.005 <= metrics["risk_pct"] <= min(0.075, 1.50 * atr_pct)
        risk_atr_ok = 0.25 <= metrics["risk_atr"] <= 1.00
        gap_ok = 0.005 <= metrics["gap_pct"] <= 0.020
        shallow_break = -0.015 <= support_distance_pct < 0
        fvg_age_ok = fvg_age_bars <= 3
        bearish_ok = confirmation.source != "NONE"

        if not trend_ok:
            reasons.append("TREND")
        if not ret5_ok:
            reasons.append("RET5")
        if metrics["close_vs_sma10"] > 0 and not near_sma10:
            reasons.append("HIGH_VOL_NEAR_SMA10")
        elif metrics["close_vs_sma10"] <= 0:
            if not below_sma10_range:
                reasons.append("CLOSE_VS_SMA10")
            elif not below_sma10_confirmed:
                reasons.append("HIGH_VOL_BELOW_SMA10_CONFIRMATION")
        if not risk_pct_ok:
            reasons.append("RISK_PCT")
        if not risk_atr_ok:
            reasons.append("RISK_ATR")
        if not gap_ok:
            reasons.append("GAP")
        if not shallow_break:
            reasons.append("SUPPORT_DISTANCE")
        if not fvg_age_ok:
            reasons.append("FVG_AGE")
        if not bearish_ok:
            reasons.append("BEARISH_SEQUENCE")
        if stop_source != "BREAK_HIGH":
            reasons.append("STOP_SOURCE")

        return _adaptive_v2_result(not reasons, profile, reasons, confirmation)

    return _adaptive_v2_result(False, profile, ["UNKNOWN_VOL_PROFILE"], confirmation)


def adaptive_v2_profile_ok(
    row: pd.Series,
    entry: float,
    stop: float,
    stop_source: str,
    fvg_age_bars: int,
    break_range_pct: float,
    support_distance_pct: float,
    bearish_fvg_count_since_support: int = 0,
    bearish_fvg_sequence_max_since_support: int = 0,
    bearish_fvg_gap_sum_since_support: float = 0.0,
    bearish_fvg_gap_max_since_support: float = 0.0,
    variant: str = "adaptive-v2",
) -> tuple[bool, str]:
    """Compatibility wrapper around shared adaptive-v2 audit/check logic."""
    result = adaptive_v2_check(
        variant=variant,
        row=row,
        entry=entry,
        stop=stop,
        stop_source=stop_source,
        fvg_age_bars=fvg_age_bars,
        break_range_pct=break_range_pct,
        support_distance_pct=support_distance_pct,
        bearish_fvg_count_since_support=bearish_fvg_count_since_support,
        bearish_fvg_sequence_max_since_support=bearish_fvg_sequence_max_since_support,
        bearish_fvg_gap_sum_since_support=bearish_fvg_gap_sum_since_support,
        bearish_fvg_gap_max_since_support=bearish_fvg_gap_max_since_support,
    )
    return result.passed, result.vol_profile


def target_r_for_profile(profile: str, row: pd.Series) -> float:
    if profile in {"LOW_VOL", "MID_VOL"}:
        return 3.0
    if profile == "HIGH_VOL":
        return 3.0
    if profile == "EXTREME_VOL":
        return 3.0
    return 3.0


def passes_variant_filter(
    variant: str,
    row: pd.Series,
    entry: float,
    stop: float,
    stop_source: str,
    fvg_age_bars: int,
    break_range_pct: float,
    support_distance_pct: float | None = None,
) -> bool:
    """Final filter stack: V5.1 = old R3 core + quality filters."""
    variant = normalize_variant(variant)

    if not has_required_indicators(row):
        return False

    risk = stop - entry
    if risk <= 0:
        return False

    metrics = variant_metrics(row, entry, stop)

    if variant == "adaptive-v1":
        return adaptive_profile_ok(
            row=row,
            entry=entry,
            stop=stop,
            stop_source=stop_source,
            fvg_age_bars=fvg_age_bars,
            break_range_pct=break_range_pct,
        )[0]

    if variant in {"adaptive-v2", "adaptive-v2-extreme-research"}:
        if support_distance_pct is None:
            support_distance_pct = _ratio(float(row["close"]) - float(row.get("broken_support", float("nan"))), float(row["close"]))
        return adaptive_v2_profile_ok(
            row=row,
            entry=entry,
            stop=stop,
            stop_source=stop_source,
            fvg_age_bars=fvg_age_bars,
            break_range_pct=break_range_pct,
            support_distance_pct=support_distance_pct,
            variant=variant,
        )[0]

    if variant == "legacy":
        return bool(
            float(row["close"]) > float(row["sma10"]) > float(row["sma20"]) > float(row["sma200"])
        )

    old_core = old_r3_core_ok(row, metrics)

    if variant == "r3-core":
        return old_core

    v5_base = bool(
        old_core
        and 0.0025 <= metrics["risk_pct"] <= 0.025
        and -0.015 < metrics["close_vs_sma10"] <= 0.0125
        and metrics["sma20_sma200_spread"] > 0.085
        and metrics["risk_atr"] <= 1.5
        and stop_source == "BREAK_HIGH"
    )

    if variant == "r3-v5-broad":
        return v5_base

    if variant == "r3-v5-priority":
        return bool(v5_base and metrics["gap_pct"] >= 0.0025)

    if variant == "r3-v5-conviction":
        return bool(v5_base and metrics["gap_pct"] >= 0.005)

    if variant == "r3-v5-a-plus":
        return bool(
            v5_base
            and metrics["gap_pct"] >= 0.005
            and break_range_pct >= 0.02
        )

    if variant == "r3-v5-fresh":
        return bool(
            v5_base
            and metrics["gap_pct"] >= 0.005
            and fvg_age_bars <= 1
        )

    raise ValueError(f"Unknown variant: {variant}")


def add_fvg_displacement_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["bullish_fvg"] = False
    df["bearish_fvg"] = False
    df["bearish_fvg_gap_size"] = 0.0
    df["bearish_fvg_gap_pct"] = 0.0

    if len(df) >= 3:
        bull = df["low"] > df["high"].shift(2)
        bear = df["high"] < df["low"].shift(2)

        df.loc[bull, "bullish_fvg"] = True
        df.loc[bear, "bearish_fvg"] = True

        bear_gap = df["low"].shift(2) - df["high"]
        df.loc[bear, "bearish_fvg_gap_size"] = bear_gap[bear]
        df.loc[bear, "bearish_fvg_gap_pct"] = bear_gap[bear] / df["low"].shift(2)[bear]

    df["bearish_fvg_count_3"] = df["bearish_fvg"].rolling(3).sum()
    df["bearish_fvg_count_5"] = df["bearish_fvg"].rolling(5).sum()

    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    required_cols = {"open", "high", "low", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")

    df = df.sort_index().copy()

    df["sma5"] = df["close"].rolling(5).mean()
    df["sma10"] = df["close"].rolling(10).mean()
    df["sma20"] = df["close"].rolling(20).mean()
    df["sma200"] = df["close"].rolling(200).mean()
    df["ret5"] = df["close"].pct_change(5)

    prev_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr14"] = true_range.rolling(14).mean()
    df["atr_pct"] = df["atr14"] / df["close"]
    df["atr_pct_252_median"] = df["atr_pct"].rolling(252).median()

    volume_mean_20 = df["volume"].rolling(20).mean()
    volume_std_20 = df["volume"].rolling(20).std()
    safe_volume_std_20 = volume_std_20.mask(volume_std_20 == 0)
    df["volume_zscore_20"] = (df["volume"] - volume_mean_20) / safe_volume_std_20
    df = add_fvg_displacement_columns(df)

    return df


def build_trades(
    ticker: str,
    df: pd.DataFrame,
    start_date: str = "2000-01-01",
    max_hold_days: int = 20,
    r_multiple: float = 3.0,
    variant: str = DEFAULT_VARIANT,
) -> list[SupportBreakTrade]:
    variant = normalize_variant(variant)
    start_ts = pd.to_datetime(start_date)
    df = add_indicators(df)

    support: float | None = None
    support_form_index: int | None = None
    support_form_date: pd.Timestamp | None = None
    support_gap_size: float | None = None
    support_gap_pct: float | None = None
    support_ratcheted_count = 0
    bearish_fvg_count_since_support = 0
    bearish_fvg_sequence_current_since_support = 0
    bearish_fvg_sequence_max_since_support = 0
    last_bearish_fvg_index_since_support: int | None = None
    bearish_fvg_gap_sum_since_support = 0.0
    bearish_fvg_gap_max_since_support = 0.0

    trades: list[SupportBreakTrade] = []

    for i in range(len(df)):
        row = df.iloc[i]
        date = df.index[i]

        if support is not None and float(row["close"]) < support:
            can_emit_trade = date >= start_ts and i + 1 < len(df)

            if can_emit_trade:
                next_row = df.iloc[i + 1]
                entry_date = df.index[i + 1]
                entry = float(next_row["open"])
                stop = max(float(row["high"]), float(support))
                risk = stop - entry

                if risk > 0:
                    stop_source = "BREAK_HIGH" if float(row["high"]) >= float(support) else "SUPPORT"
                    fvg_age_bars = i - int(support_form_index)
                    break_range_pct = _ratio(float(row["high"]) - float(row["low"]), float(row["close"]))
                    support_distance_pct = _ratio(float(row["close"]) - float(support), float(row["close"]))
                    last_bearish_fvg_age_bars = (
                        i - last_bearish_fvg_index_since_support
                        if last_bearish_fvg_index_since_support is not None
                        else -1
                    )

                    adaptive_v2_result: AdaptiveV2Check | None = None

                    if variant == "adaptive-v1":
                        passed, vol_profile = adaptive_profile_ok(
                            row=row,
                            entry=entry,
                            stop=stop,
                            stop_source=stop_source,
                            fvg_age_bars=fvg_age_bars,
                            break_range_pct=break_range_pct,
                        )
                    elif variant in {"adaptive-v2", "adaptive-v2-extreme-research"}:
                        adaptive_v2_result = adaptive_v2_check(
                            variant=variant,
                            row=row,
                            entry=entry,
                            stop=stop,
                            stop_source=stop_source,
                            fvg_age_bars=fvg_age_bars,
                            break_range_pct=break_range_pct,
                            support_distance_pct=support_distance_pct,
                            bearish_fvg_count_since_support=bearish_fvg_count_since_support,
                            bearish_fvg_sequence_max_since_support=bearish_fvg_sequence_max_since_support,
                            bearish_fvg_gap_sum_since_support=bearish_fvg_gap_sum_since_support,
                            bearish_fvg_gap_max_since_support=bearish_fvg_gap_max_since_support,
                        )
                        passed = adaptive_v2_result.passed
                        vol_profile = adaptive_v2_result.vol_profile
                    else:
                        passed = passes_variant_filter(
                            variant=variant,
                            row=row,
                            entry=entry,
                            stop=stop,
                            stop_source=stop_source,
                            fvg_age_bars=fvg_age_bars,
                            break_range_pct=break_range_pct,
                            support_distance_pct=support_distance_pct,
                        )
                        vol_profile = classify_vol_profile(row)

                    if passed:
                        metrics = variant_metrics(row, entry, stop)
                        bearish_confirmation = (
                            adaptive_v2_result
                            if adaptive_v2_result is not None
                            else _adaptive_v2_result(
                                True,
                                vol_profile,
                                [],
                                get_bearish_confirmation(
                                    row=row,
                                    atr_pct=metrics["atr_pct"],
                                    break_range_pct=break_range_pct,
                                    bearish_fvg_count_since_support=bearish_fvg_count_since_support,
                                    bearish_fvg_sequence_max_since_support=bearish_fvg_sequence_max_since_support,
                                ),
                            )
                        )
                        atr14 = float(row["atr14"]) if not pd.isna(row["atr14"]) else float("nan")
                        effective_r = target_r_for_profile(vol_profile, row) if variant.startswith("adaptive-") else r_multiple
                        vol_regime = classify_vol_regime(row)
                        target = entry - risk * effective_r

                        exit_price: float | None = None
                        exit_date: pd.Timestamp | None = None
                        reason: str | None = None
                        last_exit_index = min(i + max_hold_days, len(df) - 1)

                        for j in range(i + 1, min(i + 1 + max_hold_days, len(df))):
                            future = df.iloc[j]
                            future_date = df.index[j]

                            if float(future["open"]) >= stop:
                                exit_price = float(future["open"])
                                exit_date = future_date
                                reason = "GAP_STOP"
                                break

                            if float(future["high"]) >= stop:
                                exit_price = stop
                                exit_date = future_date
                                reason = "STOP"
                                break

                            if float(future["low"]) <= target:
                                exit_price = target
                                exit_date = future_date
                                reason = f"TARGET_{effective_r:g}R"
                                break

                        if exit_price is None:
                            exit_price = float(df.iloc[last_exit_index]["close"])
                            exit_date = df.index[last_exit_index]
                            reason = "TIME_EXIT"

                        pnl = entry - exit_price
                        realized_r = pnl / risk if risk > 0 else float("nan")
                        hold_days = int((exit_date - entry_date).days)

                        trades.append(
                            SupportBreakTrade(
                                ticker=ticker,
                                variant=variant,
                                fvg_form_date=support_form_date,
                                fvg_age_bars=fvg_age_bars,
                                fvg_age_calendar_days=int((date - support_form_date).days),
                                fvg_low=float(support),
                                fvg_gap_size=float(support_gap_size),
                                fvg_gap_pct=float(support_gap_pct),
                                support_ratcheted_count=support_ratcheted_count,
                                break_date=date,
                                broken_support=float(support),
                                break_high=float(row["high"]),
                                break_low=float(row["low"]),
                                break_close=float(row["close"]),
                                break_range_pct=break_range_pct,
                                support_distance_pct=support_distance_pct,
                                stop_source=stop_source,
                                entry_date=entry_date,
                                entry=entry,
                                stop=stop,
                                risk=risk,
                                r_multiple=effective_r,
                                target=target,
                                exit_date=exit_date,
                                exit_price=exit_price,
                                reason=reason,
                                pnl=pnl,
                                realized_R=realized_r,
                                hold_days=hold_days,
                                prior_close=float(row["close"]),
                                prior_sma5=float(row["sma5"]),
                                prior_sma10=float(row["sma10"]),
                                prior_sma20=float(row["sma20"]),
                                prior_sma200=float(row["sma200"]),
                                ret5=metrics["ret5"],
                                gap_pct=metrics["gap_pct"],
                                risk_pct=metrics["risk_pct"],
                                close_vs_sma5=metrics["close_vs_sma5"],
                                close_vs_sma10=metrics["close_vs_sma10"],
                                sma10_sma20_spread=metrics["sma10_sma20_spread"],
                                sma20_sma200_spread=metrics["sma20_sma200_spread"],
                                atr14=atr14,
                                risk_atr=metrics["risk_atr"],
                                volume_zscore_20=(
                                    float(row["volume_zscore_20"])
                                    if not pd.isna(row["volume_zscore_20"])
                                    else float("nan")
                                ),
                                vol_profile=vol_profile,
                                vol_regime=vol_regime,
                                atr_pct=(
                                    float(row["atr_pct"])
                                    if not pd.isna(row["atr_pct"])
                                    else float("nan")
                                ),
                                atr_pct_252_median=(
                                    float(row["atr_pct_252_median"])
                                    if not pd.isna(row["atr_pct_252_median"])
                                    else float("nan")
                                ),
                                bearish_fvg=bool(row["bearish_fvg"]),
                                bearish_fvg_gap_size=float(row["bearish_fvg_gap_size"]),
                                bearish_fvg_gap_pct=float(row["bearish_fvg_gap_pct"]),
                                bearish_fvg_count_3=(
                                    float(row["bearish_fvg_count_3"])
                                    if not pd.isna(row["bearish_fvg_count_3"])
                                    else 0.0
                                ),
                                bearish_fvg_count_5=(
                                    float(row["bearish_fvg_count_5"])
                                    if not pd.isna(row["bearish_fvg_count_5"])
                                    else 0.0
                                ),
                                bearish_fvg_count_since_support=bearish_fvg_count_since_support,
                                bearish_fvg_sequence_max_since_support=bearish_fvg_sequence_max_since_support,
                                last_bearish_fvg_age_bars=last_bearish_fvg_age_bars,
                                bearish_fvg_gap_sum_since_support=bearish_fvg_gap_sum_since_support,
                                bearish_fvg_gap_max_since_support=bearish_fvg_gap_max_since_support,
                                bearish_fvg_after_support_before_break=bearish_fvg_count_since_support > 0,
                                bearish_confirmation_source=bearish_confirmation.bearish_confirmation_source,
                                has_break_day_bearish_fvg=bearish_confirmation.has_break_day_bearish_fvg,
                                has_bearish_fvg_sequence=bearish_confirmation.has_bearish_fvg_sequence,
                                has_bearish_fvg_since_support=bearish_confirmation.has_bearish_fvg_since_support,
                                has_range_displacement=bearish_confirmation.has_range_displacement,
                            )
                        )

            support = None
            support_form_index = None
            support_form_date = None
            support_gap_size = None
            support_gap_pct = None
            support_ratcheted_count = 0
            bearish_fvg_count_since_support = 0
            bearish_fvg_sequence_current_since_support = 0
            bearish_fvg_sequence_max_since_support = 0
            last_bearish_fvg_index_since_support = None
            bearish_fvg_gap_sum_since_support = 0.0
            bearish_fvg_gap_max_since_support = 0.0

        if i >= 2:
            prev2 = df.iloc[i - 2]

            if support is not None:
                if bool(row["bearish_fvg"]):
                    bearish_fvg_count_since_support += 1
                    bearish_fvg_sequence_current_since_support += 1
                    bearish_fvg_sequence_max_since_support = max(
                        bearish_fvg_sequence_max_since_support,
                        bearish_fvg_sequence_current_since_support,
                    )
                    last_bearish_fvg_index_since_support = i
                    bearish_gap = float(row["bearish_fvg_gap_size"])
                    bearish_fvg_gap_sum_since_support += bearish_gap
                    bearish_fvg_gap_max_since_support = max(
                        bearish_fvg_gap_max_since_support,
                        bearish_gap,
                    )
                else:
                    bearish_fvg_sequence_current_since_support = 0

            if float(row["low"]) > float(prev2["high"]):
                new_support = float(row["low"])
                fvg_gap_size = new_support - float(prev2["high"])
                fvg_gap_pct = _ratio(fvg_gap_size, float(prev2["high"]))

                if support is None or new_support > support:
                    if support is not None:
                        support_ratcheted_count += 1

                    support = new_support
                    support_form_index = i
                    support_form_date = date
                    support_gap_size = fvg_gap_size
                    support_gap_pct = fvg_gap_pct
                    bearish_fvg_count_since_support = 0
                    bearish_fvg_sequence_current_since_support = 0
                    bearish_fvg_sequence_max_since_support = 0
                    last_bearish_fvg_index_since_support = None
                    bearish_fvg_gap_sum_since_support = 0.0
                    bearish_fvg_gap_max_since_support = 0.0

    return trades


def reject_reasons_for_candidate(
    variant: str,
    row: pd.Series,
    entry: float,
    stop: float,
    stop_source: str,
    fvg_age_bars: int,
    break_range_pct: float,
    support_distance_pct: float,
    bearish_fvg_count_since_support: int = 0,
    bearish_fvg_sequence_max_since_support: int = 0,
    bearish_fvg_gap_sum_since_support: float = 0.0,
    bearish_fvg_gap_max_since_support: float = 0.0,
) -> list[str]:
    variant = normalize_variant(variant)
    reasons: list[str] = []

    if not has_required_indicators(row):
        return ["MISSING_INDICATORS"]

    metrics = variant_metrics(row, entry, stop)
    profile = classify_vol_profile(row)

    if stop - entry <= 0:
        return ["INVALID_RISK"]

    if variant in {"adaptive-v2", "adaptive-v2-extreme-research"}:
        return adaptive_v2_check(
            variant=variant,
            row=row,
            entry=entry,
            stop=stop,
            stop_source=stop_source,
            fvg_age_bars=fvg_age_bars,
            break_range_pct=break_range_pct,
            support_distance_pct=support_distance_pct,
            bearish_fvg_count_since_support=bearish_fvg_count_since_support,
            bearish_fvg_sequence_max_since_support=bearish_fvg_sequence_max_since_support,
            bearish_fvg_gap_sum_since_support=bearish_fvg_gap_sum_since_support,
            bearish_fvg_gap_max_since_support=bearish_fvg_gap_max_since_support,
        ).reject_reasons

    if variant in {"adaptive-v1", "r3-v5-broad", "r3-v5-priority", "r3-v5-conviction", "r3-v5-a-plus", "r3-v5-fresh"}:
        if stop_source != "BREAK_HIGH":
            reasons.append("STOP_SOURCE")
        if metrics["gap_pct"] <= 0:
            reasons.append("NO_GAP")
        if not (0.0025 <= metrics["risk_pct"] <= 0.025):
            reasons.append("RISK_PCT")
        if metrics["risk_atr"] > 1.5:
            reasons.append("RISK_ATR")
        if not (-0.015 < metrics["close_vs_sma10"] <= 0.0125):
            reasons.append("CLOSE_VS_SMA10")
        if not old_r3_core_ok(row, metrics) and not variant.startswith("adaptive-"):
            reasons.append("OLD_R3_CORE")
    return reasons or ["VARIANT_RULE"]


def build_candidates(
    ticker: str,
    df: pd.DataFrame,
    start_date: str = "2000-01-01",
    variant: str = DEFAULT_VARIANT,
) -> list[dict]:
    variant = normalize_variant(variant)
    start_ts = pd.to_datetime(start_date)
    df = add_indicators(df)

    support = None
    support_form_index = None
    support_form_date = None
    support_gap_size = None
    support_gap_pct = None
    support_ratcheted_count = 0
    bearish_fvg_count_since_support = 0
    bearish_fvg_sequence_current_since_support = 0
    bearish_fvg_sequence_max_since_support = 0
    last_bearish_fvg_index_since_support = None
    bearish_fvg_gap_sum_since_support = 0.0
    bearish_fvg_gap_max_since_support = 0.0
    candidates: list[dict] = []

    for i in range(len(df)):
        row = df.iloc[i]
        date = df.index[i]
        if support is not None and float(row["close"]) < support:
            if date >= start_ts and i + 1 < len(df):
                entry = float(df.iloc[i + 1]["open"])
                stop = max(float(row["high"]), float(support))
                stop_source = "BREAK_HIGH" if float(row["high"]) >= float(support) else "SUPPORT"
                fvg_age_bars = i - int(support_form_index)
                break_range_pct = _ratio(float(row["high"]) - float(row["low"]), float(row["close"]))
                support_distance_pct = _ratio(float(row["close"]) - float(support), float(row["close"]))
                vol_profile = classify_vol_profile(row)
                vol_regime = classify_vol_regime(row)
                adaptive_v2_result: AdaptiveV2Check | None = None
                if variant in {"adaptive-v2", "adaptive-v2-extreme-research"}:
                    adaptive_v2_result = adaptive_v2_check(
                        variant=variant,
                        row=row,
                        entry=entry,
                        stop=stop,
                        stop_source=stop_source,
                        fvg_age_bars=fvg_age_bars,
                        break_range_pct=break_range_pct,
                        support_distance_pct=support_distance_pct,
                        bearish_fvg_count_since_support=bearish_fvg_count_since_support,
                        bearish_fvg_sequence_max_since_support=bearish_fvg_sequence_max_since_support,
                        bearish_fvg_gap_sum_since_support=bearish_fvg_gap_sum_since_support,
                        bearish_fvg_gap_max_since_support=bearish_fvg_gap_max_since_support,
                    )
                    passed = adaptive_v2_result.passed
                    vol_profile = adaptive_v2_result.vol_profile
                elif variant == "adaptive-v1":
                    passed, vol_profile = adaptive_profile_ok(row, entry, stop, stop_source, fvg_age_bars, break_range_pct)
                else:
                    passed = passes_variant_filter(variant, row, entry, stop, stop_source, fvg_age_bars, break_range_pct, support_distance_pct)
                metrics = variant_metrics(row, entry, stop) if has_required_indicators(row) else {}
                if adaptive_v2_result is None:
                    bearish_confirmation = _adaptive_v2_result(
                        True,
                        vol_profile,
                        [],
                        get_bearish_confirmation(
                            row=row,
                            atr_pct=metrics.get("atr_pct", float("nan")),
                            break_range_pct=break_range_pct,
                            bearish_fvg_count_since_support=bearish_fvg_count_since_support,
                            bearish_fvg_sequence_max_since_support=bearish_fvg_sequence_max_since_support,
                        ),
                    )
                    reasons = [] if passed else reject_reasons_for_candidate(
                        variant,
                        row,
                        entry,
                        stop,
                        stop_source,
                        fvg_age_bars,
                        break_range_pct,
                        support_distance_pct,
                        bearish_fvg_count_since_support,
                        bearish_fvg_sequence_max_since_support,
                        bearish_fvg_gap_sum_since_support,
                        bearish_fvg_gap_max_since_support,
                    )
                else:
                    bearish_confirmation = adaptive_v2_result
                    reasons = adaptive_v2_result.reject_reasons
                candidates.append(
                    {
                        "ticker": ticker,
                        "variant": variant,
                        "break_date": date,
                        "entry_date": df.index[i + 1],
                        "passed_variant": passed,
                        "reject_reasons": ";".join(reasons),
                        "vol_profile": vol_profile,
                        "vol_regime": vol_regime,
                        "broken_support": float(support),
                        "support_distance_pct": support_distance_pct,
                        "fvg_age_bars": fvg_age_bars,
                        "support_ratcheted_count": support_ratcheted_count,
                        "stop_source": stop_source,
                        "entry": entry,
                        "stop": stop,
                        "risk": stop - entry,
                        "gap_pct": metrics.get("gap_pct", float("nan")),
                        "risk_pct": metrics.get("risk_pct", float("nan")),
                        "risk_atr": metrics.get("risk_atr", float("nan")),
                        "close_vs_sma10": metrics.get("close_vs_sma10", float("nan")),
                        "ret5": metrics.get("ret5", float("nan")),
                        "atr_pct": metrics.get("atr_pct", float("nan")),
                        "break_range_pct": break_range_pct,
                        "bearish_fvg_count_since_support": bearish_fvg_count_since_support,
                        "bearish_fvg_sequence_max_since_support": bearish_fvg_sequence_max_since_support,
                        "last_bearish_fvg_age_bars": (
                            i - last_bearish_fvg_index_since_support
                            if last_bearish_fvg_index_since_support is not None
                            else -1
                        ),
                        "bearish_fvg_gap_sum_since_support": bearish_fvg_gap_sum_since_support,
                        "bearish_fvg_gap_max_since_support": bearish_fvg_gap_max_since_support,
                        "bearish_confirmation_source": bearish_confirmation.bearish_confirmation_source,
                        "has_break_day_bearish_fvg": bearish_confirmation.has_break_day_bearish_fvg,
                        "has_bearish_fvg_sequence": bearish_confirmation.has_bearish_fvg_sequence,
                        "has_bearish_fvg_since_support": bearish_confirmation.has_bearish_fvg_since_support,
                        "has_range_displacement": bearish_confirmation.has_range_displacement,
                    }
                )

            support = None
            support_form_index = None
            support_form_date = None
            support_gap_size = None
            support_gap_pct = None
            support_ratcheted_count = 0
            bearish_fvg_count_since_support = 0
            bearish_fvg_sequence_current_since_support = 0
            bearish_fvg_sequence_max_since_support = 0
            last_bearish_fvg_index_since_support = None
            bearish_fvg_gap_sum_since_support = 0.0
            bearish_fvg_gap_max_since_support = 0.0

        if i >= 2:
            prev2 = df.iloc[i - 2]
            if support is not None:
                if bool(row["bearish_fvg"]):
                    bearish_fvg_count_since_support += 1
                    bearish_fvg_sequence_current_since_support += 1
                    bearish_fvg_sequence_max_since_support = max(bearish_fvg_sequence_max_since_support, bearish_fvg_sequence_current_since_support)
                    last_bearish_fvg_index_since_support = i
                    bearish_gap = float(row["bearish_fvg_gap_size"])
                    bearish_fvg_gap_sum_since_support += bearish_gap
                    bearish_fvg_gap_max_since_support = max(bearish_fvg_gap_max_since_support, bearish_gap)
                else:
                    bearish_fvg_sequence_current_since_support = 0
            if float(row["low"]) > float(prev2["high"]):
                new_support = float(row["low"])
                if support is None or new_support > support:
                    if support is not None:
                        support_ratcheted_count += 1
                    support = new_support
                    support_form_index = i
                    support_form_date = date
                    support_gap_size = new_support - float(prev2["high"])
                    support_gap_pct = _ratio(support_gap_size, float(prev2["high"]))
                    bearish_fvg_count_since_support = 0
                    bearish_fvg_sequence_current_since_support = 0
                    bearish_fvg_sequence_max_since_support = 0
                    last_bearish_fvg_index_since_support = None
                    bearish_fvg_gap_sum_since_support = 0.0
                    bearish_fvg_gap_max_since_support = 0.0

    return candidates


def summarize(trades: list[SupportBreakTrade]) -> dict:
    if not trades:
        return {
            "trades": 0,
            "total_R": 0.0,
            "avg_R": 0.0,
            "pf_R": 0.0,
            "win_rate": 0.0,
            "target_rate": 0.0,
            "stop_rate": 0.0,
            "gap_stop_rate": 0.0,
            "time_exit_rate": 0.0,
            "avg_hold_days": 0.0,
            "target_3R_count": 0,
            "target_4R_count": 0,
            "avg_effective_r": 0.0,
            "pnl": 0.0,
            "avg_trade": 0.0,
        }

    df = pd.DataFrame([t.__dict__ for t in trades])
    winners_r = df.loc[df["realized_R"] > 0, "realized_R"].sum()
    losers_r = -df.loc[df["realized_R"] < 0, "realized_R"].sum()

    return {
        "trades": len(df),
        "total_R": df["realized_R"].sum(),
        "avg_R": df["realized_R"].mean(),
        "pf_R": winners_r / losers_r if losers_r else float("inf"),
        "win_rate": (df["realized_R"] > 0).mean(),
        "target_rate": df["reason"].astype(str).str.startswith("TARGET").mean(),
        "stop_rate": (df["reason"] == "STOP").mean(),
        "gap_stop_rate": (df["reason"] == "GAP_STOP").mean(),
        "time_exit_rate": (df["reason"] == "TIME_EXIT").mean(),
        "avg_hold_days": df["hold_days"].mean(),
        "target_3R_count": int((df["r_multiple"] == 3.0).sum()),
        "target_4R_count": int((df["r_multiple"] == 4.0).sum()),
        "avg_effective_r": df["r_multiple"].mean(),
        "pnl": df["pnl"].sum(),
        "avg_trade": df["pnl"].mean(),
    }


def slug(value: str) -> str:
    return value.lower().replace(" ", "_").replace("-", "_")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest bullish-FVG support-break short rule")
    parser.add_argument("tickers", nargs="+", help="Ticker symbols, e.g. AAPL MSFT NVDA")
    parser.add_argument("--start-date", default="2000-01-01")
    parser.add_argument("--max-hold-days", type=int, default=20)
    parser.add_argument(
        "--variant",
        choices=VARIANT_CHOICES,
        default=DEFAULT_VARIANT,
        help=(
            "Entry filter variant. Default: r3-v5-priority. "
            "Use adaptive-v1/adaptive-v2/adaptive-v2-extreme-research for research."
        ),
    )
    parser.add_argument(
        "--r",
        nargs="+",
        type=float,
        default=DEFAULT_R_MULTIPLES,
        help="R targets to test. Default: 3.0. Example: --r 3 4",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save combined trade CSV for all tickers/R targets.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output CSV path used with --save.",
    )
    parser.add_argument(
        "--save-candidates",
        action="store_true",
        help="Save structural support-break candidates with pass/fail and reject reasons.",
    )
    parser.add_argument(
        "--candidates-output",
        default=None,
        help="Optional candidate audit CSV path used with --save-candidates.",
    )

    args = parser.parse_args()
    variant = normalize_variant(args.variant)
    r_values = [DEFAULT_R_MULTIPLES[0]] if variant.startswith("adaptive-") else args.r

    summary_rows = []
    all_trades: list[SupportBreakTrade] = []
    all_candidates: list[dict] = []

    for ticker in [t.upper().strip() for t in args.tickers]:
        df = data_cache.get_cached_ticker_data(ticker, args.start_date)

        if df is None or df.empty:
            print(f"[!] No data for {ticker}")
            continue

        if args.save_candidates:
            all_candidates.extend(
                build_candidates(
                    ticker=ticker,
                    df=df,
                    start_date=args.start_date,
                    variant=variant,
                )
            )

        for r_multiple in r_values:
            trades = build_trades(
                ticker=ticker,
                df=df,
                start_date=args.start_date,
                max_hold_days=args.max_hold_days,
                r_multiple=r_multiple,
                variant=variant,
            )

            stats = summarize(trades)
            summary_rows.append(
                {
                    "ticker": ticker,
                    "variant": variant,
                    "r": r_multiple,
                    **stats,
                }
            )
            all_trades.extend(trades)

    out = pd.DataFrame(summary_rows)

    if not out.empty:
        print(
            out.to_string(
                index=False,
                formatters={
                    "r": "{:.2f}".format,
                    "trades": "{:,.0f}".format,
                    "total_R": "{:.2f}".format,
                    "avg_R": "{:.3f}".format,
                    "pf_R": "{:.3f}".format,
                    "win_rate": "{:.1%}".format,
                    "target_rate": "{:.1%}".format,
                    "stop_rate": "{:.1%}".format,
                    "gap_stop_rate": "{:.1%}".format,
                    "time_exit_rate": "{:.1%}".format,
                    "avg_hold_days": "{:.1f}".format,
                    "target_3R_count": "{:,.0f}".format,
                    "target_4R_count": "{:,.0f}".format,
                    "avg_effective_r": "{:.2f}".format,
                    "pnl": "{:.2f}".format,
                    "avg_trade": "{:.3f}".format,
                },
            )
        )

    if args.save:
        if all_trades:
            trades_df = pd.DataFrame([t.__dict__ for t in all_trades])

            if args.output:
                output_path = Path(args.output)
            else:
                r_slug = "_".join(str(r).replace(".", "p") for r in r_values)
                output_path = Path(f"support_break_{slug(variant)}_{r_slug}R_trades.csv")

            trades_df.to_csv(output_path, index=False)
            print(f"\n[+] Saved trades: {output_path.resolve()}")
        else:
            print("\n[!] No trades to save.")

    if args.save_candidates:
        if all_candidates:
            candidates_df = pd.DataFrame(all_candidates)
            if args.candidates_output:
                candidates_path = Path(args.candidates_output)
            else:
                candidates_path = Path(f"support_break_{slug(variant)}_candidates.csv")
            candidates_df.to_csv(candidates_path, index=False)
            print(f"[+] Saved candidates: {candidates_path.resolve()}")
        else:
            print("[!] No candidates to save.")


if __name__ == "__main__":
    main()
