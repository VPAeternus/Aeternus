"""KAMA cross replay features for Step 1 recall experiments."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any, Dict, Sequence

import pandas as pd

from .fma_recall import (
    _attach_cross_sectional_scores as _attach_fma_cross_sectional_scores,
    _build_fvg_confirmed_map,
    _build_symbol_rows as _build_fma_symbol_rows,
)
from .fvg_recall import (
    _build_feature_frame as _build_fvg_feature_frame,
    _download_history,
    _normalize_frame,
    _summarize_daily_baskets,
    _summarize_forward_returns,
    normalize_universe_name,
    resolve_fvg_universe_tickers,
)


KAMA_FAST_ER_PERIOD = 1
KAMA_SLOW_ER_PERIOD = 2
KAMA_FAST_PERIOD = 10
KAMA_SLOW_PERIOD = 15
KAMA_FVG_REGIME_MAX_AGE_BARS = 20


def compute_kama_snapshot(
    frame: pd.DataFrame,
    index: int,
    *,
    fast_er_period: int = KAMA_FAST_ER_PERIOD,
    slow_er_period: int = KAMA_SLOW_ER_PERIOD,
    fast_period: int = KAMA_FAST_PERIOD,
    slow_period: int = KAMA_SLOW_PERIOD,
) -> Dict[str, Any]:
    hist = _normalize_frame(frame).iloc[: index + 1].copy()
    if hist.empty or len(hist) < 2:
        return _empty_kama_snapshot()

    close = hist["close"]
    fast_kama = _compute_kama_series(
        close,
        er_period=fast_er_period,
        fast_period=fast_period,
        slow_period=slow_period,
    )
    slow_kama = _compute_kama_series(
        close,
        er_period=slow_er_period,
        fast_period=fast_period,
        slow_period=slow_period,
    )
    if fast_kama.empty or slow_kama.empty:
        return _empty_kama_snapshot()

    fast_value = float(fast_kama.iloc[-1])
    slow_value = float(slow_kama.iloc[-1])
    prev_fast = float(fast_kama.iloc[-2])
    prev_slow = float(slow_kama.iloc[-2])
    spread = fast_value - slow_value
    spread_pct = 0.0 if slow_value == 0.0 else float(spread / slow_value)

    return {
        "valid": True,
        "fast_kama": fast_value,
        "slow_kama": slow_value,
        "kama_spread": float(spread),
        "kama_spread_pct": float(spread_pct),
        "cross_up": bool(fast_value > slow_value and prev_fast <= prev_slow),
        "bullish_state": bool(fast_value > slow_value),
    }


def compute_kama_overlap_bucket_summaries(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    buckets = {
        "kama_only": [
            dict(row)
            for row in rows
            if bool(row.get("kama_active")) and not bool(row.get("fvg_confirmed")) and not bool(row.get("fma_active"))
        ],
        "fvg_only": [
            dict(row)
            for row in rows
            if bool(row.get("fvg_confirmed")) and not bool(row.get("kama_active")) and not bool(row.get("fma_active"))
        ],
        "fma_only": [
            dict(row)
            for row in rows
            if bool(row.get("fma_active")) and not bool(row.get("kama_active")) and not bool(row.get("fvg_confirmed"))
        ],
        "kama_and_fvg": [
            dict(row)
            for row in rows
            if bool(row.get("kama_active")) and bool(row.get("fvg_confirmed")) and not bool(row.get("fma_active"))
        ],
        "kama_and_fma": [
            dict(row)
            for row in rows
            if bool(row.get("kama_active")) and bool(row.get("fma_active")) and not bool(row.get("fvg_confirmed"))
        ],
        "fvg_and_fma": [
            dict(row)
            for row in rows
            if bool(row.get("fvg_confirmed")) and bool(row.get("fma_active")) and not bool(row.get("kama_active"))
        ],
        "kama_and_fvg_and_fma": [
            dict(row)
            for row in rows
            if bool(row.get("kama_active")) and bool(row.get("fvg_confirmed")) and bool(row.get("fma_active"))
        ],
        "any_signal": [
            dict(row)
            for row in rows
            if bool(row.get("kama_active")) or bool(row.get("fvg_confirmed")) or bool(row.get("fma_active"))
        ],
    }
    return {name: _summarize_forward_returns(bucket) for name, bucket in buckets.items()}


def build_bullish_fvg_regime_frame(
    frame: pd.DataFrame,
    *,
    atr_floor: float = 0.25,
    max_age_bars: int = KAMA_FVG_REGIME_MAX_AGE_BARS,
) -> pd.DataFrame:
    features = _build_fvg_feature_frame(frame, benchmark_frame=None, atr_floor=atr_floor)
    bearish_ratio = (features["bear_gap_size"] / features["atr_14"].replace(0.0, pd.NA)).fillna(0.0)
    bearish_fvg_present = ((features["bear_gap_size"] > 0.0) & (bearish_ratio >= atr_floor)).tolist()
    bullish_fvg_present = features["bullish_fvg_present"].fillna(False).tolist()

    active_values: list[bool] = []
    streak_values: list[int] = []
    age_values: list[int] = []

    active = False
    streak = 0
    last_bull_index: int | None = None

    for index, (bullish_event, bearish_event) in enumerate(zip(bullish_fvg_present, bearish_fvg_present)):
        age = 0
        if bool(bearish_event):
            active = False
            streak = 0
            last_bull_index = None

        if bool(bullish_event):
            if active and last_bull_index is not None and (index - last_bull_index) <= int(max_age_bars):
                streak += 1
            else:
                streak = 1
            active = True
            last_bull_index = index
            age = 0
        elif active and last_bull_index is not None:
            age = index - last_bull_index
            if age > int(max_age_bars):
                active = False
                streak = 0
                last_bull_index = None
                age = 0

        active_values.append(bool(active))
        streak_values.append(int(streak))
        age_values.append(int(age))

    return pd.DataFrame(
        {
            "date": features["date"],
            "bullish_fvg_present": pd.Series([bool(value) for value in bullish_fvg_present], dtype=object),
            "bearish_fvg_present": pd.Series([bool(value) for value in bearish_fvg_present], dtype=object),
            "bullish_fvg_regime_active": pd.Series(active_values, dtype=object),
            "bullish_fvg_streak": streak_values,
            "bullish_fvg_regime_age_bars": age_values,
        }
    )


def run_kama_backtest(
    tickers: Sequence[str] | None = None,
    start: str = "2020-01-01",
    end: str | None = None,
    top_n: int = 3,
    artifact_dir: str | Path | None = None,
    benchmark: str = "SMH",
    universe_name: str = "semis_ai_narrow",
    fvg_regime_max_age_bars: int = KAMA_FVG_REGIME_MAX_AGE_BARS,
) -> Dict[str, Any]:
    normalized_universe_name = normalize_universe_name(universe_name)
    symbols = resolve_fvg_universe_tickers(tickers=tickers, universe_name=normalized_universe_name)
    benchmark_symbol = str(benchmark).upper().strip()
    end_date = end or date.today().isoformat()
    base_dir = resolve_kama_artifact_dir(
        artifact_dir=artifact_dir,
        run_date=date.today().isoformat(),
        universe_name=normalized_universe_name,
        benchmark=benchmark_symbol,
    )
    base_dir.mkdir(parents=True, exist_ok=True)

    history = _download_history(symbols + [benchmark_symbol], start=start, end=end_date)
    benchmark_frame = history.get(benchmark_symbol)

    daily_rows: list[Dict[str, Any]] = []
    raw_fma_rows: list[Dict[str, Any]] = []

    for symbol in symbols:
        frame = history.get(symbol)
        if frame is None or frame.empty:
            continue

        fvg_frame = _build_fvg_feature_frame(frame, benchmark_frame=benchmark_frame, atr_floor=0.25)
        fvg_flags = _build_fvg_confirmed_map(fvg_frame)
        fvg_regime_frame = build_bullish_fvg_regime_frame(
            frame,
            atr_floor=0.25,
            max_age_bars=fvg_regime_max_age_bars,
        )
        daily_rows.extend(
            _build_kama_rows(
                symbol=symbol,
                frame=frame,
                fvg_regime_frame=fvg_regime_frame,
                fvg_confirmed_map=fvg_flags,
            )
        )
        raw_fma_rows.extend(
            [
                dict(row)
                for row in _build_fma_symbol_rows(
                    symbol=symbol,
                    frame=frame,
                    benchmark_frame=benchmark_frame,
                    fvg_confirmed_map={},
                )
                if str(row.get("variant")) == "fma_live"
            ]
        )

    fma_rows = _attach_fma_cross_sectional_scores(raw_fma_rows, variant="fma_live")
    fma_active_map = {
        (str(row.get("ticker")), str(row.get("date"))): bool(row.get("fma_active"))
        for row in fma_rows
    }

    for row in daily_rows:
        row["fma_active"] = bool(fma_active_map.get((str(row["ticker"]), str(row["date"])), False))

    event_rows = [dict(row) for row in daily_rows if bool(row.get("kama_active"))]
    union_rows = [
        dict(row)
        for row in daily_rows
        if bool(row.get("kama_active")) or bool(row.get("fvg_confirmed")) or bool(row.get("fma_active"))
    ]

    payload = {
        "universe_name": normalized_universe_name,
        "benchmark": benchmark_symbol,
        "tickers": symbols,
        "start": start,
        "end": end_date,
        "artifact_dir": str(base_dir),
        "parameters": {
            "fast_er_period": KAMA_FAST_ER_PERIOD,
            "slow_er_period": KAMA_SLOW_ER_PERIOD,
            "fast_period": KAMA_FAST_PERIOD,
            "slow_period": KAMA_SLOW_PERIOD,
            "fvg_regime_max_age_bars": int(fvg_regime_max_age_bars),
        },
        "event_summary": _summarize_forward_returns(event_rows),
        "basket_summary": _summarize_daily_baskets(event_rows, top_n=top_n, benchmark_frame=benchmark_frame),
        "overlap_summary": compute_kama_overlap_bucket_summaries(union_rows),
        "union_summary": {
            "event_summary": _summarize_forward_returns(union_rows),
            "basket_summary": _summarize_daily_baskets(union_rows, top_n=top_n, benchmark_frame=benchmark_frame),
        },
    }

    (base_dir / "events.json").write_text(json.dumps(event_rows, indent=2, default=_json_default))
    (base_dir / "daily_rows.json").write_text(json.dumps(daily_rows, indent=2, default=_json_default))
    (base_dir / "summary.json").write_text(json.dumps(payload, indent=2, default=_json_default))
    return payload


def resolve_kama_artifact_dir(
    artifact_dir: str | Path | None,
    run_date: str,
    universe_name: str,
    benchmark: str,
) -> Path:
    if artifact_dir is not None:
        return Path(artifact_dir)
    return Path("eval_results") / "deal_flow" / "kama_backtest" / run_date / f"{universe_name}-vs-{benchmark}"


def _build_kama_rows(
    *,
    symbol: str,
    frame: pd.DataFrame,
    fvg_regime_frame: pd.DataFrame,
    fvg_confirmed_map: Dict[str, bool],
) -> list[Dict[str, Any]]:
    features = _build_kama_feature_frame(frame)
    close = _normalize_frame(frame)["close"]
    regime_map = {
        pd.to_datetime(row["date"]).date().isoformat(): row
        for _, row in fvg_regime_frame.iterrows()
    }
    rows: list[Dict[str, Any]] = []
    for _, row in features.iterrows():
        if not bool(row.get("valid", False)):
            continue
        event_date = pd.to_datetime(row["date"]).date().isoformat()
        regime_row = regime_map.get(event_date, {})
        regime_active = bool(regime_row.get("bullish_fvg_regime_active", False))
        regime_streak = int(regime_row.get("bullish_fvg_streak", 0) or 0)
        regime_age_bars = int(regime_row.get("bullish_fvg_regime_age_bars", 0) or 0)
        rows.append(
            {
                "date": event_date,
                "ticker": symbol,
                "valid": True,
                "fast_kama": float(row.get("fast_kama", 0.0) or 0.0),
                "slow_kama": float(row.get("slow_kama", 0.0) or 0.0),
                "kama_spread": float(row.get("kama_spread", 0.0) or 0.0),
                "kama_spread_pct": float(row.get("kama_spread_pct", 0.0) or 0.0),
                "cross_up": bool(row.get("cross_up", False)),
                "bullish_state": bool(row.get("bullish_state", False)),
                "kama_active": bool(row.get("cross_up", False)) and regime_active,
                "score": float(max(0.0, row.get("kama_spread_pct", 0.0) or 0.0) * 10000.0),
                "fvg_confirmed": bool(fvg_confirmed_map.get(event_date, False)),
                "bullish_fvg_regime_active": regime_active,
                "bullish_fvg_streak": regime_streak,
                "bullish_fvg_regime_age_bars": regime_age_bars,
                **_forward_return_fields(close, index=int(row["_index"])),
            }
        )
    return rows


def _build_kama_feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    features = _normalize_frame(frame).copy()
    close = features["close"]
    features["_index"] = list(range(len(features)))
    features["fast_kama"] = _compute_kama_series(
        close,
        er_period=KAMA_FAST_ER_PERIOD,
        fast_period=KAMA_FAST_PERIOD,
        slow_period=KAMA_SLOW_PERIOD,
    )
    features["slow_kama"] = _compute_kama_series(
        close,
        er_period=KAMA_SLOW_ER_PERIOD,
        fast_period=KAMA_FAST_PERIOD,
        slow_period=KAMA_SLOW_PERIOD,
    )
    features["kama_spread"] = features["fast_kama"] - features["slow_kama"]
    features["kama_spread_pct"] = (
        features["kama_spread"] / features["slow_kama"].replace(0.0, pd.NA)
    ).fillna(0.0)
    features["bullish_state"] = features["fast_kama"] > features["slow_kama"]
    prev_fast = features["fast_kama"].shift(1)
    prev_slow = features["slow_kama"].shift(1)
    features["cross_up"] = (
        features["bullish_state"]
        & prev_fast.notna()
        & prev_slow.notna()
        & (prev_fast <= prev_slow)
    ).fillna(False)
    features["valid"] = features["fast_kama"].notna() & features["slow_kama"].notna()
    return features


def _compute_kama_series(
    close: pd.Series,
    *,
    er_period: int,
    fast_period: int,
    slow_period: int,
) -> pd.Series:
    if close is None or close.empty:
        return pd.Series(dtype=float)

    series = pd.to_numeric(close, errors="coerce").astype(float)
    change = series.diff(er_period).abs()
    volatility = series.diff().abs().rolling(er_period).sum()
    efficiency_ratio = (change / volatility.replace(0.0, pd.NA)).fillna(0.0)
    fast_sc = 2.0 / (float(fast_period) + 1.0)
    slow_sc = 2.0 / (float(slow_period) + 1.0)
    smoothing_constant = (efficiency_ratio * (fast_sc - slow_sc) + slow_sc) ** 2

    kama_values = [float(series.iloc[0])]
    for idx in range(1, len(series)):
        prev = kama_values[-1]
        current = float(series.iloc[idx])
        sc = float(smoothing_constant.iloc[idx])
        kama_values.append(prev + sc * (current - prev))
    return pd.Series(kama_values, index=series.index, dtype=float)


def _empty_kama_snapshot() -> Dict[str, Any]:
    return {
        "valid": False,
        "fast_kama": 0.0,
        "slow_kama": 0.0,
        "kama_spread": 0.0,
        "kama_spread_pct": 0.0,
        "cross_up": False,
        "bullish_state": False,
    }


def _forward_return_fields(close: pd.Series, index: int) -> Dict[str, Any]:
    return {
        "forward_return_20d": _forward_return(close, index=index, bars=20),
        "forward_return_30d": _forward_return(close, index=index, bars=30),
        "forward_return_60d": _forward_return(close, index=index, bars=60),
        "forward_return_90d": _forward_return(close, index=index, bars=90),
    }


def _forward_return(close: pd.Series, index: int, bars: int) -> float | None:
    target = index + bars
    if target >= len(close):
        return None
    start = float(close.iloc[index])
    end = float(close.iloc[target])
    if start <= 0.0:
        return None
    return float((end / start) - 1.0)


def _json_default(value: Any):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)
