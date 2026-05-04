"""F=MA replay features for Step 1 recall experiments."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

import pandas as pd
import yfinance as yf

from .fvg_recall import (
    _build_feature_frame as _build_fvg_feature_frame,
    _download_history,
    _normalize_frame,
    _summarize_daily_baskets,
    _summarize_forward_returns,
    build_confirmation_slice_flags,
    normalize_universe_name,
    resolve_fvg_universe_tickers,
)


FMA_VARIANTS: tuple[str, ...] = ("fma_live", "fma_best_shadow")
FMA_EVENT_SCORE_THRESHOLD = 60.0


def compute_fma_snapshot(
    frame: pd.DataFrame,
    index: int,
    benchmark_frame: pd.DataFrame | None = None,
    variant: str = "fma_live",
) -> Dict[str, Any]:
    hist = _normalize_frame(frame).iloc[: index + 1].copy()
    if hist.empty:
        return _empty_fma_snapshot(variant=variant)

    current_date = pd.to_datetime(hist.iloc[-1]["date"])
    benchmark_hist = None
    if benchmark_frame is not None and not benchmark_frame.empty:
        benchmark_hist = _normalize_frame(benchmark_frame)
        benchmark_hist = benchmark_hist[benchmark_hist["date"] <= current_date].reset_index(drop=True)

    close = hist["close"]
    volume = hist["volume"]
    velocity = _return_pct(close, 60)
    accel = _accel_value(close, variant=variant)
    mass = _mass_ratio(close, volume)
    rs60 = _relative_strength_60d(close, benchmark_hist)
    valid = velocity is not None and accel is not None and mass is not None
    force = None if accel is None or mass is None else mass * accel

    return {
        "variant": normalize_variant_name(variant),
        "valid": bool(valid),
        "velocity_60d": float(velocity or 0.0),
        "accel_value": float(accel or 0.0),
        "mass_ratio": float(mass or 0.0),
        "force_value": float(force or 0.0),
        "relative_strength_60d": float(rs60 or 0.0),
    }


def score_fma_cross_section(
    snapshots: Sequence[Dict[str, Any]],
    variant: str = "fma_live",
) -> Dict[str, float]:
    target_variant = normalize_variant_name(variant)
    eligible = [
        snapshot
        for snapshot in snapshots
        if bool(snapshot.get("valid")) and str(snapshot.get("variant")) == target_variant
    ]
    if not eligible:
        return {}

    vel_rank = _percentile_rank_map({str(s["ticker"]): float(s["velocity_60d"]) for s in eligible})
    accel_rank = _percentile_rank_map({str(s["ticker"]): float(s["accel_value"]) for s in eligible})
    mass_rank = _percentile_rank_map({str(s["ticker"]): float(s["mass_ratio"]) for s in eligible})
    force_rank = _percentile_rank_map({str(s["ticker"]): float(s["force_value"]) for s in eligible})
    rs_rank = _percentile_rank_map({str(s["ticker"]): float(s["relative_strength_60d"]) for s in eligible})

    scores: Dict[str, float] = {}
    for snapshot in eligible:
        ticker = str(snapshot["ticker"])
        score = (
            0.20 * (100.0 * vel_rank.get(ticker, 0.5))
            + 0.30 * (100.0 * accel_rank.get(ticker, 0.5))
            + 0.20 * (100.0 * mass_rank.get(ticker, 0.5))
            + 0.20 * (100.0 * force_rank.get(ticker, 0.5))
            + 0.10 * (100.0 * rs_rank.get(ticker, 0.5))
        )
        scores[ticker] = float(round(_clamp(score, 0.0, 100.0), 4))
    return scores


def compute_overlap_bucket_summaries(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    buckets = {
        "fvg_only": [dict(row) for row in rows if bool(row.get("fvg_confirmed")) and not bool(row.get("fma_active"))],
        "fma_only": [dict(row) for row in rows if bool(row.get("fma_active")) and not bool(row.get("fvg_confirmed"))],
        "fvg_and_fma": [dict(row) for row in rows if bool(row.get("fma_active")) and bool(row.get("fvg_confirmed"))],
        "fvg_or_fma": [dict(row) for row in rows if bool(row.get("fma_active")) or bool(row.get("fvg_confirmed"))],
    }
    return {name: _summarize_forward_returns(bucket) for name, bucket in buckets.items()}


def run_fma_backtest(
    tickers: Sequence[str] | None = None,
    start: str = "2020-01-01",
    end: str | None = None,
    top_n: int = 3,
    artifact_dir: str | Path | None = None,
    benchmark: str = "SMH",
    universe_name: str = "semis_ai_narrow",
) -> Dict[str, Any]:
    normalized_universe_name = normalize_universe_name(universe_name)
    symbols = resolve_fvg_universe_tickers(tickers=tickers, universe_name=normalized_universe_name)
    benchmark_symbol = str(benchmark).upper().strip()
    end_date = end or date.today().isoformat()
    base_dir = resolve_fma_artifact_dir(
        artifact_dir=artifact_dir,
        run_date=date.today().isoformat(),
        universe_name=normalized_universe_name,
        benchmark=benchmark_symbol,
    )
    base_dir.mkdir(parents=True, exist_ok=True)

    history = _download_history(symbols + [benchmark_symbol], start=start, end=end_date)
    benchmark_frame = history.get(benchmark_symbol)

    raw_rows_by_variant: Dict[str, list[Dict[str, Any]]] = {variant: [] for variant in FMA_VARIANTS}
    fvg_rows_all: list[Dict[str, Any]] = []

    for symbol in symbols:
        frame = history.get(symbol)
        if frame is None or frame.empty:
            continue
        fvg_frame = _build_fvg_feature_frame(frame, benchmark_frame=benchmark_frame, atr_floor=0.25)
        fvg_flags = _build_fvg_confirmed_map(fvg_frame)
        symbol_rows = _build_symbol_rows(
            symbol=symbol,
            frame=frame,
            benchmark_frame=benchmark_frame,
            fvg_confirmed_map=fvg_flags,
        )
        for variant in FMA_VARIANTS:
            raw_rows_by_variant[variant].extend([dict(row) for row in symbol_rows if row["variant"] == variant])
        fvg_rows_all.extend([dict(row) for row in symbol_rows if row["variant"] == "fma_live"])

    variant_summaries: Dict[str, Dict[str, Any]] = {}
    rows_payload: Dict[str, list[Dict[str, Any]]] = {}
    basket_union_source: list[Dict[str, Any]] = []

    for variant, rows in raw_rows_by_variant.items():
        scored_rows = _attach_cross_sectional_scores(rows=rows, variant=variant)
        event_rows = [dict(row) for row in scored_rows if bool(row.get("fma_active"))]
        variant_summaries[variant] = {
            "event_summary": _summarize_forward_returns(event_rows),
            "basket_summary": _summarize_daily_baskets(scored_rows, top_n=top_n, benchmark_frame=benchmark_frame),
        }
        rows_payload[variant] = scored_rows
        if variant == "fma_live":
            basket_union_source = scored_rows

    overlap_summary = compute_overlap_bucket_summaries([dict(row) for row in rows_payload.get("fma_live", []) if bool(row.get("fma_active")) or bool(row.get("fvg_confirmed"))])
    union_rows = [dict(row) for row in basket_union_source if bool(row.get("fma_active")) or bool(row.get("fvg_confirmed"))]
    union_summary = {
        "event_summary": _summarize_forward_returns(union_rows),
        "basket_summary": _summarize_daily_baskets(union_rows, top_n=top_n, benchmark_frame=benchmark_frame),
    }

    payload = {
        "universe_name": normalized_universe_name,
        "benchmark": benchmark_symbol,
        "tickers": symbols,
        "start": start,
        "end": end_date,
        "artifact_dir": str(base_dir),
        "shadow_variant_matches_live": True,
        "variant_summaries": variant_summaries,
        "overlap_summary": overlap_summary,
        "union_summary": union_summary,
    }

    (base_dir / "rows_by_variant.json").write_text(json.dumps(rows_payload, indent=2, default=_json_default))
    (base_dir / "summary.json").write_text(json.dumps(payload, indent=2, default=_json_default))
    return payload


def normalize_variant_name(variant: str | None) -> str:
    value = str(variant or "fma_live").strip().lower()
    if value not in set(FMA_VARIANTS):
        raise ValueError(f"Unsupported FMA variant: {variant}")
    return value


def resolve_fma_artifact_dir(
    artifact_dir: str | Path | None,
    run_date: str,
    universe_name: str,
    benchmark: str,
) -> Path:
    if artifact_dir is not None:
        return Path(artifact_dir)
    return Path("eval_results") / "deal_flow" / "fma_backtest" / run_date / f"{universe_name}-vs-{benchmark}"


def _build_symbol_rows(
    *,
    symbol: str,
    frame: pd.DataFrame,
    benchmark_frame: pd.DataFrame | None,
    fvg_confirmed_map: Dict[str, bool],
) -> list[Dict[str, Any]]:
    norm = _normalize_frame(frame)
    rows: list[Dict[str, Any]] = []
    feature_frames = {
        variant: _build_fma_feature_frame(norm, benchmark_frame=benchmark_frame, variant=variant)
        for variant in FMA_VARIANTS
    }
    for variant in FMA_VARIANTS:
        feature_frame = feature_frames[variant]
        for _, row in feature_frame.iterrows():
            if not bool(row.get("valid", False)):
                continue
            event_date = pd.to_datetime(row["date"]).date().isoformat()
            rows.append(
                {
                    "date": event_date,
                    "ticker": symbol,
                    "variant": variant,
                    "fvg_confirmed": bool(fvg_confirmed_map.get(event_date, False)),
                    "valid": True,
                    "velocity_60d": float(row.get("velocity_60d", 0.0) or 0.0),
                    "accel_value": float(row.get("accel_value", 0.0) or 0.0),
                    "mass_ratio": float(row.get("mass_ratio", 0.0) or 0.0),
                    "force_value": float(row.get("force_value", 0.0) or 0.0),
                    "relative_strength_60d": float(row.get("relative_strength_60d", 0.0) or 0.0),
                    **_forward_return_fields(norm["close"], index=int(row["_index"])),
                }
            )
    return rows


def _build_fvg_confirmed_map(frame: pd.DataFrame) -> Dict[str, bool]:
    flags: Dict[str, bool] = {}
    for _, row in frame.iterrows():
        slices = build_confirmation_slice_flags(
            bullish_fvg_present=bool(row.get("bullish_fvg_present", False)),
            relative_strength_20d=float(row.get("relative_strength_20d", 0.0) or 0.0),
            trend_alignment_20_50_200=float(row.get("trend_alignment_20_50_200", 50.0) or 50.0),
            volume_zscore_20d=float(row.get("volume_zscore_20d", 0.0) or 0.0),
            price_above_sma20=bool(row.get("price_above_sma20", False)),
            sma20_above_sma50=bool(row.get("sma20_above_sma50", False)),
            sma50_above_sma200=bool(row.get("sma50_above_sma200", False)),
        )
        event_date = pd.to_datetime(row["date"]).date().isoformat()
        flags[event_date] = bool(slices.get("fvg_plus_rs_sma50_above_sma200", False))
    return flags


def _build_fma_feature_frame(
    frame: pd.DataFrame,
    *,
    benchmark_frame: pd.DataFrame | None,
    variant: str,
) -> pd.DataFrame:
    _ = normalize_variant_name(variant)
    features = _normalize_frame(frame).copy()
    close = features["close"]
    volume = features["volume"]
    dollar_volume = close * volume

    features["_index"] = list(range(len(features)))
    features["velocity_60d"] = (close / close.shift(60)) - 1.0

    sma20 = close.rolling(20).mean()
    slope_recent = (sma20 - sma20.shift(20)) / sma20.shift(20).replace(0.0, pd.NA)
    slope_prior = (sma20.shift(20) - sma20.shift(40)) / sma20.shift(40).replace(0.0, pd.NA)
    features["accel_value"] = (slope_recent - slope_prior).fillna(0.0)

    dv_5 = dollar_volume.rolling(5).mean()
    dv_60 = dollar_volume.rolling(60).mean().replace(0.0, pd.NA)
    features["mass_ratio"] = (dv_5 / dv_60).fillna(0.0)
    features["force_value"] = features["mass_ratio"] * features["accel_value"]

    if benchmark_frame is None or benchmark_frame.empty:
        features["relative_strength_60d"] = 0.0
    else:
        benchmark = _normalize_frame(benchmark_frame)[["date", "close"]].rename(columns={"close": "benchmark_close"})
        merged = features[["date", "close"]].merge(benchmark, on="date", how="left").ffill()
        stock_ret = (merged["close"] / merged["close"].shift(60)) - 1.0
        bench_ret = (merged["benchmark_close"] / merged["benchmark_close"].shift(60)) - 1.0
        features["relative_strength_60d"] = (stock_ret - bench_ret).fillna(0.0)

    features["valid"] = (
        features["velocity_60d"].notna()
        & features["mass_ratio"].notna()
        & features["accel_value"].notna()
    )
    return features


def _attach_cross_sectional_scores(rows: Sequence[Dict[str, Any]], variant: str) -> list[Dict[str, Any]]:
    by_date: Dict[str, list[Dict[str, Any]]] = {}
    for row in rows:
        by_date.setdefault(str(row["date"]), []).append(dict(row))

    scored_rows: list[Dict[str, Any]] = []
    for _, bucket in sorted(by_date.items()):
        scores = score_fma_cross_section(bucket, variant=variant)
        for row in bucket:
            ticker = str(row["ticker"])
            score = float(scores.get(ticker, 0.0))
            row["score"] = score
            row["fma_active"] = bool(score >= FMA_EVENT_SCORE_THRESHOLD)
            scored_rows.append(row)
    return scored_rows


def _empty_fma_snapshot(*, variant: str) -> Dict[str, Any]:
    return {
        "variant": normalize_variant_name(variant),
        "valid": False,
        "velocity_60d": 0.0,
        "accel_value": 0.0,
        "mass_ratio": 0.0,
        "force_value": 0.0,
        "relative_strength_60d": 0.0,
    }


def _return_pct(close: pd.Series, bars: int) -> float | None:
    if close is None or len(close) <= bars:
        return None
    start = float(close.iloc[-bars - 1])
    end = float(close.iloc[-1])
    if start <= 0.0:
        return None
    return float((end / start) - 1.0)


def _accel_value(close: pd.Series, *, variant: str) -> float | None:
    # Current best historical IC variant is identical to the live formula.
    _ = normalize_variant_name(variant)
    if close is None or len(close) < 61:
        return None
    sma20 = close.rolling(20).mean()
    sma_now = sma20.iloc[-1]
    sma_mid = sma20.iloc[-21]
    sma_far = sma20.iloc[-41]
    if pd.isna(sma_now) or pd.isna(sma_mid) or pd.isna(sma_far):
        return None
    if float(sma_mid) == 0.0 or float(sma_far) == 0.0:
        return None
    slope_recent = (float(sma_now) - float(sma_mid)) / float(sma_mid)
    slope_prior = (float(sma_mid) - float(sma_far)) / float(sma_far)
    return float(slope_recent - slope_prior)


def _mass_ratio(close: pd.Series, volume: pd.Series) -> float | None:
    if close is None or volume is None or len(close) < 60 or len(volume) < 60:
        return None
    common = close.index.intersection(volume.index)
    if len(common) < 60:
        return None
    c = close.reindex(common)
    v = volume.reindex(common)
    dollar_volume = c * v
    dv_5 = float(dollar_volume.tail(5).mean())
    dv_60 = float(dollar_volume.tail(60).mean())
    if dv_60 <= 0.0:
        return None
    return float(dv_5 / dv_60)


def _relative_strength_60d(close: pd.Series, benchmark_frame: pd.DataFrame | None) -> float | None:
    if benchmark_frame is None or benchmark_frame.empty or len(close) <= 60:
        return 0.0
    benchmark_close = _normalize_frame(benchmark_frame)["close"]
    if len(benchmark_close) <= 60:
        return 0.0
    stock_return = _return_pct(close, 60)
    benchmark_return = _return_pct(benchmark_close, 60)
    if stock_return is None or benchmark_return is None:
        return 0.0
    return float(stock_return - benchmark_return)


def _percentile_rank_map(values: Dict[str, float]) -> Dict[str, float]:
    if not values:
        return {}
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 1.0}
    return {key: idx / float(n - 1) for idx, (key, _) in enumerate(items)}


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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _json_default(value: Any):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)
