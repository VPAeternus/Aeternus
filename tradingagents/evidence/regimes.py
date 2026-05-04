"""Deterministic regime classification for evidence packs."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Iterable, List, Optional, Tuple

REGIME_PRECEDENCE: List[str] = [
    "VOL_SHOCK",
    "BEAR",
    "HIGH_VOL",
    "RISK_OFF",
    "INFLATION_SHOCK",
    "RATES_UPTREND",
    "EUPHORIA",
    "BULL",
    "NEUTRAL",
]

# Regime trigger constants (deterministic, contract-facing).
# VOL_SHOCK
VOL_SHOCK_VIX_THRESHOLD: float = 50.0
VOL_SHOCK_ABS_SPY_RETURN_1D_PCT_THRESHOLD: float = 3.0

# BEAR
BEAR_PRICE_BELOW_SMA200_REQUIRED: bool = True

# HIGH_VOL
HIGH_VOL_VIX_THRESHOLD: float = 30.0

# RISK_OFF (requires explicit VIX and supporting stress)
RISK_OFF_VIX_THRESHOLD: float = 25.0
RISK_OFF_SPY_BELOW_SMA20_REQUIRED: bool = True
RISK_OFF_SUPPORT_SPY_DEVIATION_PCT_THRESHOLD: float = -3.0
RISK_OFF_SUPPORT_CPI_YOY_THRESHOLD: float = 3.0
RISK_OFF_SUPPORT_DGS10_20D_DELTA_THRESHOLD: float = 0.10

# INFLATION_SHOCK
INFLATION_SHOCK_CPI_YOY_THRESHOLD: float = 4.0
INFLATION_SHOCK_CPI_SLOPE_3M_THRESHOLD: float = 0.5

# RATES_UPTREND
RATES_UPTREND_DGS10_LEVEL_THRESHOLD: float = 4.5
RATES_UPTREND_DGS10_20D_DELTA_THRESHOLD: float = 0.20

# EUPHORIA
EUPHORIA_SPY_DEVIATION_PCT_THRESHOLD: float = 5.0
EUPHORIA_VIX_MAX_THRESHOLD: float = 15.0

# BULL
BULL_VIX_MAX_THRESHOLD: float = 20.0

# Macro normalization stale controls (trading-day forward-fill limits).
DGS10_MAX_FFILL_TRADING_DAYS: int = 10
CPI_MAX_FFILL_TRADING_DAYS: int = 45


def normalize_macro_series(
    trading_dates: Iterable[str],
    dgs10_daily: Optional[Dict[str, Any]] = None,
    cpi_monthly: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Align mixed-frequency macro series to trading dates.

    - DGS10 daily: aligned by date and forward-filled across trading dates.
    - CPI monthly: aligned by month and forward-filled across daily dates.
    - Stale caps:
      - DGS10 max forward-fill span: `DGS10_MAX_FFILL_TRADING_DAYS`.
      - CPI max forward-fill span: `CPI_MAX_FFILL_TRADING_DAYS`.
    """
    ordered_dates = sorted({_parse_date(d) for d in trading_dates if _parse_date(d)})
    if not ordered_dates:
        return {}

    dgs_points: List[Tuple[dt.date, float]] = []
    for raw_key, raw_value in (dgs10_daily or {}).items():
        key_date = _parse_date(raw_key)
        value = _safe_float(raw_value)
        if key_date is None or value is None:
            continue
        dgs_points.append((key_date, value))
    dgs_points.sort(key=lambda item: item[0])

    cpi_points: Dict[dt.date, float] = {}
    for raw_key, raw_value in (cpi_monthly or {}).items():
        key_month = _parse_month(raw_key)
        value = _safe_float(raw_value)
        if key_month is None or value is None:
            continue
        cpi_points[key_month] = value

    normalized: Dict[str, Dict[str, Any]] = {}

    # DGS10 forward-fill to trading dates with stale cutoff.
    dgs_idx = 0
    dgs_last: Optional[float] = None
    dgs_last_idx: Optional[int] = None
    dgs_aligned_values: List[Optional[float]] = []
    dgs_stale_flags: List[bool] = []
    for idx, trading_date in enumerate(ordered_dates):
        while dgs_idx < len(dgs_points) and dgs_points[dgs_idx][0] <= trading_date:
            dgs_last = dgs_points[dgs_idx][1]
            dgs_last_idx = idx
            dgs_idx += 1
        is_stale = (
            dgs_last is not None
            and dgs_last_idx is not None
            and (idx - dgs_last_idx) > DGS10_MAX_FFILL_TRADING_DAYS
        )
        dgs_stale_flags.append(bool(is_stale))
        dgs_aligned_values.append(None if is_stale else dgs_last)

    # CPI monthly forward-fill to trading dates with stale cutoff.
    cpi_aligned_values: List[Optional[float]] = []
    cpi_stale_flags: List[bool] = []
    sorted_months = sorted(cpi_points.keys())
    cpi_month_idx = -1
    cpi_last: Optional[float] = None
    cpi_last_idx: Optional[int] = None
    for idx, trading_date in enumerate(ordered_dates):
        month_anchor = dt.date(trading_date.year, trading_date.month, 1)
        while (cpi_month_idx + 1) < len(sorted_months) and sorted_months[cpi_month_idx + 1] <= month_anchor:
            cpi_month_idx += 1
            cpi_last = cpi_points[sorted_months[cpi_month_idx]]
            cpi_last_idx = idx
        is_stale = (
            cpi_last is not None
            and cpi_last_idx is not None
            and (idx - cpi_last_idx) > CPI_MAX_FFILL_TRADING_DAYS
        )
        cpi_stale_flags.append(bool(is_stale))
        cpi_aligned_values.append(None if is_stale else cpi_last)

    for idx, trading_date in enumerate(ordered_dates):
        dgs_today = dgs_aligned_values[idx]
        dgs_prev_20 = dgs_aligned_values[idx - 20] if idx >= 20 else None
        dgs_20d_delta = None
        if dgs_today is not None and dgs_prev_20 is not None:
            dgs_20d_delta = round(dgs_today - dgs_prev_20, 6)

        cpi_today = cpi_aligned_values[idx]
        cpi_prev_3m = None
        month_3m_back = _month_shift(dt.date(trading_date.year, trading_date.month, 1), -3)
        if month_3m_back in cpi_points:
            cpi_prev_3m = cpi_points[month_3m_back]
        cpi_slope_3m = None
        if cpi_today is not None and cpi_prev_3m is not None:
            cpi_slope_3m = round(cpi_today - cpi_prev_3m, 6)

        normalized[trading_date.isoformat()] = {
            "dgs10": dgs_today,
            "dgs10_20d_delta": dgs_20d_delta,
            "cpi_yoy": cpi_today,
            "cpi_slope_3m": cpi_slope_3m,
            "dgs10_stale": bool(dgs_stale_flags[idx]),
            "cpi_stale": bool(cpi_stale_flags[idx]),
            "stale_macro": bool(dgs_stale_flags[idx] or cpi_stale_flags[idx]),
        }

    return normalized


def classify_regime(metrics: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Classify one date using deterministic, ordered precedence."""
    spy_close = _safe_float(metrics.get("spy_close"))
    spy_sma20 = _safe_float(metrics.get("spy_sma20"))
    spy_sma200 = _safe_float(metrics.get("spy_sma200"))
    spy_dev_pct = _safe_float(metrics.get("spy_deviation_pct"))
    vix_close = _safe_float(metrics.get("vix_close"))
    spy_return_1d_pct = _safe_float(metrics.get("spy_return_1d_pct"))
    dgs10 = _safe_float(metrics.get("dgs10"))
    dgs10_20d_delta = _safe_float(metrics.get("dgs10_20d_delta"))
    cpi_yoy = _safe_float(metrics.get("cpi_yoy"))
    cpi_slope_3m = _safe_float(metrics.get("cpi_slope_3m"))
    dgs10_stale = bool(metrics.get("dgs10_stale"))
    cpi_stale = bool(metrics.get("cpi_stale"))
    stale_macro = bool(metrics.get("stale_macro") or dgs10_stale or cpi_stale)

    risk_off_support_price_stress = (
        spy_dev_pct is not None and spy_dev_pct <= RISK_OFF_SUPPORT_SPY_DEVIATION_PCT_THRESHOLD
    )
    risk_off_support_macro_stress = (
        (not cpi_stale and cpi_yoy is not None and cpi_yoy >= RISK_OFF_SUPPORT_CPI_YOY_THRESHOLD)
        or (
            not dgs10_stale
            and dgs10_20d_delta is not None
            and dgs10_20d_delta >= RISK_OFF_SUPPORT_DGS10_20D_DELTA_THRESHOLD
        )
    )
    risk_off_support = bool(risk_off_support_price_stress or risk_off_support_macro_stress)

    checks: List[Tuple[str, bool, str]] = [
        (
            "VOL_SHOCK",
            (
                (vix_close is not None and vix_close >= VOL_SHOCK_VIX_THRESHOLD)
                or (
                    spy_return_1d_pct is not None
                    and abs(spy_return_1d_pct) >= VOL_SHOCK_ABS_SPY_RETURN_1D_PCT_THRESHOLD
                )
            ),
            (
                f"vix>={VOL_SHOCK_VIX_THRESHOLD:g} or "
                f"|spy_return_1d|>={VOL_SHOCK_ABS_SPY_RETURN_1D_PCT_THRESHOLD:g}%"
            ),
        ),
        (
            "BEAR",
            (
                spy_close is not None
                and spy_sma200 is not None
                and (spy_close < spy_sma200 if BEAR_PRICE_BELOW_SMA200_REQUIRED else False)
            ),
            "spy_close<spy_sma200",
        ),
        (
            "HIGH_VOL",
            (vix_close is not None and vix_close >= HIGH_VOL_VIX_THRESHOLD),
            f"vix>={HIGH_VOL_VIX_THRESHOLD:g}",
        ),
        (
            "RISK_OFF",
            (
                spy_close is not None
                and spy_sma20 is not None
                and (spy_close < spy_sma20 if RISK_OFF_SPY_BELOW_SMA20_REQUIRED else False)
                and vix_close is not None
                and vix_close >= RISK_OFF_VIX_THRESHOLD
                and risk_off_support
            ),
            (
                f"spy_close<spy_sma20, vix>={RISK_OFF_VIX_THRESHOLD:g}, "
                "and supporting stress (spy_deviation/cpi/dgs10)"
            ),
        ),
        (
            "INFLATION_SHOCK",
            (
                not cpi_stale
                and (
                    (
                        cpi_yoy is not None
                        and cpi_yoy >= INFLATION_SHOCK_CPI_YOY_THRESHOLD
                    )
                    or (
                        cpi_slope_3m is not None
                        and cpi_slope_3m >= INFLATION_SHOCK_CPI_SLOPE_3M_THRESHOLD
                    )
                )
            ),
            (
                f"cpi_yoy>={INFLATION_SHOCK_CPI_YOY_THRESHOLD:g} or "
                f"cpi_slope_3m>={INFLATION_SHOCK_CPI_SLOPE_3M_THRESHOLD:g}"
            ),
        ),
        (
            "RATES_UPTREND",
            (
                not dgs10_stale
                and dgs10 is not None
                and dgs10 >= RATES_UPTREND_DGS10_LEVEL_THRESHOLD
                and dgs10_20d_delta is not None
                and dgs10_20d_delta >= RATES_UPTREND_DGS10_20D_DELTA_THRESHOLD
            ),
            (
                f"dgs10>={RATES_UPTREND_DGS10_LEVEL_THRESHOLD:g} and "
                f"20d delta>={RATES_UPTREND_DGS10_20D_DELTA_THRESHOLD:g}"
            ),
        ),
        (
            "EUPHORIA",
            (
                spy_dev_pct is not None
                and spy_dev_pct >= EUPHORIA_SPY_DEVIATION_PCT_THRESHOLD
                and vix_close is not None
                and vix_close <= EUPHORIA_VIX_MAX_THRESHOLD
            ),
            (
                f"spy_deviation>={EUPHORIA_SPY_DEVIATION_PCT_THRESHOLD:g}% and "
                f"vix<={EUPHORIA_VIX_MAX_THRESHOLD:g}"
            ),
        ),
        (
            "BULL",
            (
                spy_close is not None
                and spy_sma200 is not None
                and spy_sma20 is not None
                and spy_close >= spy_sma200
                and spy_sma20 >= spy_sma200
                and (vix_close is None or vix_close <= BULL_VIX_MAX_THRESHOLD)
            ),
            f"spy_close>=sma200 and sma20>=sma200 with vix<={BULL_VIX_MAX_THRESHOLD:g} (if present)",
        ),
    ]

    for label in REGIME_PRECEDENCE:
        if label == "NEUTRAL":
            continue
        for check_label, matched, reason in checks:
            if check_label == label and matched:
                triggers = [reason]
                if stale_macro:
                    triggers.append("STALE_MACRO")
                return label, triggers
    if stale_macro:
        return "NEUTRAL", ["STALE_MACRO"]
    return "NEUTRAL", ["no higher-precedence trigger"]


def build_regime_report(
    market_snapshots: Dict[str, Dict[str, Any]],
    dgs10_daily: Optional[Dict[str, Any]] = None,
    cpi_monthly: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a deterministic regime report keyed by date."""
    ordered_dates = sorted(
        [date for date in market_snapshots.keys() if _parse_date(date) is not None]
    )
    macro_aligned = normalize_macro_series(ordered_dates, dgs10_daily=dgs10_daily, cpi_monthly=cpi_monthly)

    rows: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {name: 0 for name in REGIME_PRECEDENCE}

    prev_spy_close: Optional[float] = None
    for date_key in ordered_dates:
        snapshot = dict(market_snapshots.get(date_key) or {})
        spy_close = _safe_float(snapshot.get("spy_close"))

        spy_return_1d_pct = None
        if spy_close is not None and prev_spy_close is not None and prev_spy_close != 0.0:
            spy_return_1d_pct = ((spy_close - prev_spy_close) / prev_spy_close) * 100.0
        if spy_close is not None:
            prev_spy_close = spy_close

        merged: Dict[str, Any] = dict(snapshot)
        merged.update(macro_aligned.get(date_key, {}))
        merged["spy_return_1d_pct"] = spy_return_1d_pct

        regime, triggers = classify_regime(merged)
        counts[regime] = counts.get(regime, 0) + 1

        rows.append(
            {
                "date": date_key,
                "regime": regime,
                "triggers": triggers,
                "spy_close": _safe_float(snapshot.get("spy_close")),
                "spy_sma20": _safe_float(snapshot.get("spy_sma20")),
                "spy_sma200": _safe_float(snapshot.get("spy_sma200")),
                "spy_deviation_pct": _safe_float(snapshot.get("spy_deviation_pct")),
                "spy_return_1d_pct": _safe_float(spy_return_1d_pct),
                "vix_close": _safe_float(snapshot.get("vix_close")),
                "dgs10": _safe_float(merged.get("dgs10")),
                "dgs10_20d_delta": _safe_float(merged.get("dgs10_20d_delta")),
                "cpi_yoy": _safe_float(merged.get("cpi_yoy")),
                "cpi_slope_3m": _safe_float(merged.get("cpi_slope_3m")),
                "dgs10_stale": bool(merged.get("dgs10_stale")),
                "cpi_stale": bool(merged.get("cpi_stale")),
                "stale_macro": bool(merged.get("stale_macro")),
                "regime_confidence": "LOW" if bool(merged.get("stale_macro")) else "HIGH",
            }
        )

    total = len(rows)
    regime_slices: List[Dict[str, Any]] = []
    for regime in REGIME_PRECEDENCE:
        count = int(counts.get(regime, 0))
        pct = round((float(count) / float(total)) * 100.0, 4) if total > 0 else 0.0
        regime_slices.append({"regime": regime, "count": count, "pct": pct})

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "precedence": list(REGIME_PRECEDENCE),
        "date_labels": rows,
        "counts": counts,
        "regime_slices": regime_slices,
        "trading_days": total,
        "macro_normalization": {
            "dgs10_aligned": bool(dgs10_daily),
            "cpi_forward_filled": bool(cpi_monthly),
            "dgs10_max_ffill_trading_days": DGS10_MAX_FFILL_TRADING_DAYS,
            "cpi_max_ffill_trading_days": CPI_MAX_FFILL_TRADING_DAYS,
        },
    }


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> Optional[dt.date]:
    if isinstance(value, dt.date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_month(value: Any) -> Optional[dt.date]:
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) == 7 and raw.count("-") == 1:
        raw = f"{raw}-01"
    parsed = _parse_date(raw)
    if parsed is None:
        return None
    return dt.date(parsed.year, parsed.month, 1)


def _month_shift(value: dt.date, months: int) -> dt.date:
    total = value.year * 12 + (value.month - 1) + months
    year = total // 12
    month = total % 12 + 1
    return dt.date(year, month, 1)
