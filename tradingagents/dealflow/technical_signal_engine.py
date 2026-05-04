"""Canonical KAMA + bullish FVG regime signal state computation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .kama_recall import _build_kama_feature_frame, build_bullish_fvg_regime_frame
from .technical_signal_store import SQLiteTechnicalSignalStore


def build_signal_rows(
    ticker: str,
    frame: pd.DataFrame,
    *,
    computed_at_utc: str,
    freshness_bars: int = 10,
    fvg_regime_max_age_bars: int = 20,
) -> list[dict[str, Any]]:
    features = _build_kama_feature_frame(frame).reset_index(drop=True)
    regime = build_bullish_fvg_regime_frame(
        frame,
        atr_floor=0.25,
        max_age_bars=fvg_regime_max_age_bars,
    ).reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    last_cross_idx: int | None = None

    for idx, feature in features.iterrows():
        if not bool(feature.get("valid", False)):
            continue
        if bool(feature.get("cross_up", False)):
            last_cross_idx = idx
        regime_active = bool(regime.loc[idx, "bullish_fvg_regime_active"])
        regime_streak = int(regime.loc[idx, "bullish_fvg_streak"] or 0)
        regime_age = int(regime.loc[idx, "bullish_fvg_regime_age_bars"] or 0)
        bullish_state = bool(feature.get("bullish_state", False))
        bars_since_cross = None if last_cross_idx is None else idx - last_cross_idx
        status_label, buy_zone, reason = _classify_row_state(
            cross_up=bool(feature.get("cross_up", False)),
            bullish_state=bullish_state,
            regime_active=regime_active,
            bars_since_cross=bars_since_cross,
            freshness_bars=freshness_bars,
        )
        rows.append(
            {
                "ticker": str(ticker or "").upper().strip(),
                "date": pd.to_datetime(feature["date"]).date().isoformat(),
                "fast_kama": float(feature.get("fast_kama", 0.0) or 0.0),
                "slow_kama": float(feature.get("slow_kama", 0.0) or 0.0),
                "kama_spread_pct": float(feature.get("kama_spread_pct", 0.0) or 0.0),
                "cross_up": bool(feature.get("cross_up", False)),
                "bullish_state": bullish_state,
                "bullish_fvg_regime_active": regime_active,
                "bullish_fvg_streak": regime_streak,
                "bullish_fvg_regime_age_bars": regime_age,
                "buy_zone": buy_zone,
                "buy_zone_reason": reason,
                "status_label": status_label,
                "last_cross_up_date": None
                if last_cross_idx is None
                else pd.to_datetime(features.loc[last_cross_idx, "date"]).date().isoformat(),
                "score": float(max(0.0, feature.get("kama_spread_pct", 0.0) or 0.0) * 10000.0),
                "computed_at_utc": str(computed_at_utc).strip(),
            }
        )
    return rows


def classify_buy_zone_state(
    signal_rows: list[dict[str, Any]],
    *,
    freshness_bars: int = 10,
) -> dict[str, Any] | None:
    if not signal_rows:
        return None
    latest = dict(signal_rows[-1])
    return {
        "ticker": latest["ticker"],
        "as_of_date": latest["date"],
        "in_buy_zone": int(bool(latest.get("buy_zone", False))),
        "status_label": latest.get("status_label", "NOT_IN_BUY_ZONE"),
        "reason": latest.get("buy_zone_reason", ""),
        "last_cross_up_date": latest.get("last_cross_up_date"),
        "bullish_fvg_regime_active": int(bool(latest.get("bullish_fvg_regime_active", False))),
        "bullish_fvg_streak": int(latest.get("bullish_fvg_streak", 0) or 0),
        "bullish_fvg_regime_age_bars": int(latest.get("bullish_fvg_regime_age_bars", 0) or 0),
        "fast_kama": float(latest.get("fast_kama", 0.0) or 0.0),
        "slow_kama": float(latest.get("slow_kama", 0.0) or 0.0),
        "score": float(latest.get("score", 0.0) or 0.0),
        "updated_at_utc": latest.get("computed_at_utc", ""),
    }


def recompute_signal_state(
    store: SQLiteTechnicalSignalStore,
    ticker: str,
    *,
    computed_at_utc: str,
    recompute_tail_bars: int = 250,
    freshness_bars: int = 10,
    fvg_regime_max_age_bars: int = 20,
) -> dict[str, Any]:
    history_rows = store.load_market_history(ticker)
    if not history_rows:
        return {"ticker": str(ticker or "").upper().strip(), "signal_rows_recomputed": 0}

    frame = pd.DataFrame(history_rows)
    frame["date"] = pd.to_datetime(frame["date"])
    signal_rows = build_signal_rows(
        ticker,
        frame,
        computed_at_utc=computed_at_utc,
        freshness_bars=freshness_bars,
        fvg_regime_max_age_bars=fvg_regime_max_age_bars,
    )
    if not signal_rows:
        return {"ticker": str(ticker or "").upper().strip(), "signal_rows_recomputed": 0}

    start_index = max(0, len(signal_rows) - int(recompute_tail_bars))
    tail_rows = signal_rows[start_index:]
    store.replace_signal_rows(str(ticker or "").upper().strip(), tail_rows[0]["date"], tail_rows)
    current_state = classify_buy_zone_state(signal_rows, freshness_bars=freshness_bars)
    if current_state:
        store.upsert_buy_zone_state([current_state])
    return {
        "ticker": str(ticker or "").upper().strip(),
        "signal_rows_recomputed": len(tail_rows),
        "status_label": None if current_state is None else current_state.get("status_label"),
    }


def _classify_row_state(
    *,
    cross_up: bool,
    bullish_state: bool,
    regime_active: bool,
    bars_since_cross: int | None,
    freshness_bars: int,
) -> tuple[str, bool, str]:
    if cross_up and regime_active:
        return ("BUY_TRIGGER", True, "Fresh KAMA cross inside bullish FVG regime")
    if bullish_state and regime_active and bars_since_cross is not None and bars_since_cross <= int(freshness_bars):
        return ("BUY_ZONE", True, "Bullish KAMA state inside active bullish FVG regime")
    if bullish_state and regime_active and bars_since_cross is not None:
        return ("TREND_UP_NOT_FRESH", False, "Trend remains bullish but the trigger is no longer fresh")
    return ("NOT_IN_BUY_ZONE", False, "No active KAMA buy-zone condition")
