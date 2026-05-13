"""QQQ daily decision report: V3, S7 hedge, and CCWyckoff buckets."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from tradingagents.phase_engine import data_engine, phase_engine
from tradingagents.phase_engine.v3_backtest import run_backtest

CC_BUCKET_LABELS = {
    "rth_avoid": "S2",
    "markup_fade": "S3",
    "markdown_crush": "S4",
    "weak_regime_rth": "S7b",
}


def _safe_float(value: Any, default: float = np.nan) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if np.isfinite(out) else default


def _align_qqq_spy(qqq: pd.DataFrame, spy: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    q = qqq.copy().reset_index(drop=True)
    s = spy.copy().reset_index(drop=True)
    q["date"] = pd.to_datetime(q["date"]).dt.normalize()
    s["date"] = pd.to_datetime(s["date"]).dt.normalize()
    common = sorted(set(q["date"]) & set(s["date"]))
    q = q[q["date"].isin(common)].sort_values("date").reset_index(drop=True)
    s = s[s["date"].isin(common)].sort_values("date").reset_index(drop=True)
    if not q["date"].equals(s["date"]):
        raise ValueError("QQQ/SPY dates are not aligned after common-date filtering")
    return q, s


def _select_signal_index(df: pd.DataFrame, as_of: Optional[str]) -> int:
    if df.empty:
        raise ValueError("No QQQ/SPY common dates available")
    dates = pd.to_datetime(df["date"]).dt.normalize()
    if as_of:
        target = pd.Timestamp(as_of).normalize()
        eligible = df.index[dates <= target]
        if len(eligible) == 0:
            raise ValueError(f"No data at or before as_of={as_of}")
        return int(eligible[-1])
    return len(df) - 1


def _accel_regime(df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    close = df["close"]
    sma10 = df["sma10"]
    slope = (sma10 - sma10.shift(lookback)) / (close * lookback)
    accel = slope - slope.shift(lookback)
    prev_accel = accel.shift(1)
    accel_dn = (accel < 0) & (prev_accel >= 0)
    accel_up = (accel > 0) & (prev_accel <= 0)

    regime = np.full(len(df), "neutral", dtype=object)
    current = "neutral"
    for i in range(len(df)):
        if bool(accel_dn.iloc[i]):
            current = "accel_dn"
        elif bool(accel_up.iloc[i]):
            current = "accel_up"
        regime[i] = current
    return pd.Series(regime, index=df.index, name="regime")


def _v3_signal_at(qqq: pd.DataFrame, i: int) -> Dict[str, Any]:
    regime = _accel_regime(qqq)
    row = qqq.iloc[i]
    prev_regime = str(regime.iloc[i])

    close = _safe_float(row.get("close"))
    sma3 = _safe_float(row.get("sma3"))
    sma10 = _safe_float(row.get("sma10"))
    sma20 = _safe_float(row.get("sma20"))
    sma50 = _safe_float(row.get("sma50"))
    sma200 = _safe_float(row.get("sma200"))
    vix = _safe_float(row.get("vix"))
    volume = _safe_float(row.get("volume"))
    vol_sma5 = _safe_float(qqq["volume"].rolling(5).mean().iloc[i]) if "volume" in qqq.columns else np.nan

    def ok(x: float) -> bool:
        return bool(np.isfinite(x))

    vix_ok_leg1 = (ok(vix) and 20 <= vix < 25) or (ok(vix) and 30 <= vix < 40) or (ok(vix) and vix >= 40)
    leg1 = (
        prev_regime == "accel_dn"
        and ok(close) and ok(sma3) and close < sma3
        and ok(sma10) and close < sma10
        and ok(sma20) and close < sma20
        and vix_ok_leg1
    )
    leg2 = ok(vix) and vix <= 15 and ok(close) and ok(sma10) and close > sma10 and ok(sma20) and sma10 > sma20
    leg3 = (
        prev_regime == "accel_dn"
        and ok(close) and ok(sma3) and close > sma3
        and ok(sma10) and close > sma10
        and ok(sma20) and close > sma20
        and ok(sma50) and close > sma50
        and ok(sma200) and close > sma200
        and ok(volume) and ok(vol_sma5) and volume > vol_sma5
    )
    rth = bool(leg1 or leg2 or leg3)

    skip1 = ok(vix) and 30 <= vix < 40 and prev_regime == "accel_up"
    skip2 = ok(vix) and vix >= 40 and ok(close) and ok(sma20) and close < sma20
    overnight_raw = not (skip1 or skip2)

    if leg1:
        active_leg = "leg1_dip_buy"
    elif leg2:
        active_leg = "leg2_stay_long"
    elif leg3:
        active_leg = "leg3_uptrend_decel"
    else:
        active_leg = None

    return {
        "date": str(pd.to_datetime(row.get("date")).date()),
        "rth": bool(rth),
        "overnight_raw": bool(overnight_raw),
        "active_leg": active_leg,
        "leg1": bool(leg1),
        "leg2": bool(leg2),
        "leg3": bool(leg3),
        "regime": prev_regime,
        "close": close,
        "sma10": sma10,
        "sma20": sma20,
        "vix": vix,
    }


def _spy_s7_active_at(spy: pd.DataFrame, i: int) -> Dict[str, bool]:
    phases = pd.Series(index=spy.index, dtype=object)
    s7a = bool(phase_engine.should_short_overnight(spy, phases, i, "SPY"))
    s7b = bool(phase_engine.is_weak_regime_rth(spy, phases, i))
    return {"s7a": s7a, "s7b": s7b, "active": bool(s7a or s7b)}


def _qqq_gate_active_at(qqq: pd.DataFrame, i: int) -> bool:
    row = qqq.iloc[i]
    close = _safe_float(row.get("close"))
    sma200 = _safe_float(row.get("sma200"))
    return bool(np.isfinite(close) and np.isfinite(sma200) and sma200 != 0.0 and close < sma200)


def _cc_bucket_stats(qqq: pd.DataFrame) -> Dict[str, Any]:
    phases = phase_engine.classify_phases(qqq)
    rows: list[dict[str, Any]] = []
    for i in range(len(qqq) - 1):
        sig = phase_engine.should_short_rth(qqq, phases, i, "QQQ")
        if sig not in CC_BUCKET_LABELS:
            continue
        entry = _safe_float(qqq.iloc[i + 1].get("open"))
        exit_price = _safe_float(qqq.iloc[i + 1].get("close"))
        if not np.isfinite(entry) or not np.isfinite(exit_price) or entry <= 0:
            continue
        rows.append({"signal": sig, "ret": (entry - exit_price) / entry, "points": entry - exit_price})

    trades = pd.DataFrame(rows)

    def summarize(frame: pd.DataFrame) -> Dict[str, Any]:
        if frame.empty:
            return {"trades": 0, "return_pct": 0.0, "points": 0.0, "avg_return_pct": 0.0, "win_rate_pct": 0.0}
        ret = frame["ret"].astype(float)
        return {
            "trades": int(len(frame)),
            "return_pct": round(float(ret.sum() * 100.0), 2),
            "points": round(float(frame["points"].sum()), 2),
            "avg_return_pct": round(float(ret.mean() * 100.0), 4),
            "win_rate_pct": round(float((ret > 0).mean() * 100.0), 2),
        }

    buckets = {}
    for signal, label in CC_BUCKET_LABELS.items():
        bucket = summarize(trades[trades["signal"] == signal] if not trades.empty else trades)
        bucket["bucket"] = label
        bucket["signal"] = signal
        buckets[signal] = bucket

    return {
        "date_start": str(pd.to_datetime(qqq["date"].iloc[0]).date()) if len(qqq) else None,
        "date_end": str(pd.to_datetime(qqq["date"].iloc[-1]).date()) if len(qqq) else None,
        "buckets": buckets,
        "all": summarize(trades),
    }


def _v3_suppression_stats(qqq: pd.DataFrame, spy: pd.DataFrame) -> Dict[str, Any]:
    v3 = run_backtest(qqq).reset_index(drop=True)
    spy_phases = phase_engine.classify_phases(spy)
    suppress = np.zeros(len(qqq), dtype=bool)
    for i in range(len(qqq) - 1):
        suppress[i + 1] = _qqq_gate_active_at(qqq, i) and (
            bool(phase_engine.should_short_overnight(spy, spy_phases, i, "SPY"))
            or bool(phase_engine.is_weak_regime_rth(spy, spy_phases, i))
        )

    raw_on_active = v3["on_active"].astype(bool).to_numpy()
    suppressed_mask = suppress & raw_on_active
    v3_supp = v3.copy()
    v3_supp.loc[suppressed_mask, "on_active"] = False
    v3_supp.loc[suppressed_mask, "on_pnl"] = 0.0
    v3_supp["total_pnl"] = v3_supp["rth_pnl"] + v3_supp["on_pnl"]

    start_close = _safe_float(qqq["close"].iloc[0], 0.0)
    bh_points = float(qqq["close"].iloc[-1] - qqq["close"].iloc[0])

    def ret_on_start(points: float) -> float:
        return round((points / start_close) * 100.0, 2) if start_close > 0 else 0.0

    return {
        "date_start": str(pd.to_datetime(qqq["date"].iloc[0]).date()),
        "date_end": str(pd.to_datetime(qqq["date"].iloc[-1]).date()),
        "suppressed_overnight_days": int(suppressed_mask.sum()),
        "removed_overnight_points": round(float(v3.loc[suppressed_mask, "on_pnl"].sum()), 2),
        "no_suppression": {
            "points": round(float(v3["total_pnl"].sum()), 2),
            "return_on_start_pct": ret_on_start(float(v3["total_pnl"].sum())),
        },
        "with_suppression": {
            "points": round(float(v3_supp["total_pnl"].sum()), 2),
            "return_on_start_pct": ret_on_start(float(v3_supp["total_pnl"].sum())),
        },
        "buy_hold": {
            "points": round(bh_points, 2),
            "return_on_start_pct": ret_on_start(bh_points),
        },
    }


def build_qqq_daily_report(
    as_of: Optional[str] = None,
    qqq_df: Optional[pd.DataFrame] = None,
    spy_df: Optional[pd.DataFrame] = None,
    start: str = "1999-01-01",
) -> Dict[str, Any]:
    """Build a deterministic QQQ daily report from one aligned completed signal bar."""
    qqq = qqq_df.copy() if qqq_df is not None else data_engine.load("QQQ", start=start)
    spy = spy_df.copy() if spy_df is not None else data_engine.load("SPY", start=start)
    qqq, spy = _align_qqq_spy(qqq, spy)
    i = _select_signal_index(qqq, as_of)
    qqq = qqq.iloc[: i + 1].reset_index(drop=True)
    spy = spy.iloc[: i + 1].reset_index(drop=True)
    i = len(qqq) - 1

    v3 = _v3_signal_at(qqq, i)
    qqq_gate = _qqq_gate_active_at(qqq, i)
    spy_s7 = _spy_s7_active_at(spy, i)
    hedge_active = bool(qqq_gate and spy_s7["active"])
    v3["overnight"] = bool(v3["overnight_raw"] and not hedge_active)
    v3["overnight_suppressed_by_s7_hedge"] = bool(v3["overnight_raw"] and hedge_active)

    qqq_phases = phase_engine.classify_phases(qqq)
    cc_signal = phase_engine.should_short_rth(qqq, qqq_phases, i, "QQQ")
    cc_bucket = CC_BUCKET_LABELS.get(cc_signal)

    actions = {
        "rth": "LONG_QQQ" if v3["rth"] else "NO_V3_RTH_LONG",
        "overnight": (
            "SUPPRESSED_BY_S7_HEDGE"
            if v3["overnight_suppressed_by_s7_hedge"]
            else ("LONG_QQQ" if v3["overnight"] else "NO_V3_OVERNIGHT_LONG")
        ),
        "hedge": "S7_HEDGE_ON" if hedge_active else "NO_S7_HEDGE",
        "covered_call": f"CC_DAY_{cc_bucket}" if cc_bucket else "NO_CCWYCKOFF_CC_DAY",
    }

    return {
        "generated_at": datetime.now().isoformat(),
        "as_of": str(pd.to_datetime(qqq.iloc[i]["date"]).date()),
        "applies_to": "next_session_after_as_of_close",
        "ticker": "QQQ",
        "v3": v3,
        "s7_hedge": {
            "active": hedge_active,
            "qqq_gate": qqq_gate,
            "spy_s7_active": bool(spy_s7["active"]),
            "spy_s7a": bool(spy_s7["s7a"]),
            "spy_s7b": bool(spy_s7["s7b"]),
            "hedge_gate_symbol": "QQQ",
            "s7_source_symbol": "SPY",
        },
        "ccwyckoff": {
            "cc_day": bool(cc_bucket),
            "bucket": cc_bucket,
            "signal": cc_signal or None,
        },
        "actions": actions,
        "returns": {
            "v3": _v3_suppression_stats(qqq, spy),
            "ccwyckoff": _cc_bucket_stats(qqq),
        },
    }
