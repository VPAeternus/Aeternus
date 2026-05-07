#!/usr/bin/env python3
"""Backtest the Aeternus momentum pillar for one ticker.

Purpose: make the momentum test auditable by another model/human.
The script computes each signal using only rows up to that signal date, then
applies the signal to the next close-to-close return.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from tradingagents.phase_engine import data_engine


MOMENTUM_ENGINE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tradingagents"
    / "agents"
    / "utils"
    / "momentum_engine.py"
)


def _load_momentum_engine():
    """Load momentum_engine without importing tradingagents.agents package."""
    spec = importlib.util.spec_from_file_location("momentum_engine", MOMENTUM_ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {MOMENTUM_ENGINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _annualized_stats(returns: Iterable[float]) -> dict:
    r = pd.Series(list(returns), dtype="float64")
    if r.empty:
        return {"total_return_pct": 0.0, "cagr_pct": 0.0, "sharpe": 0.0, "max_drawdown_pct": 0.0}

    equity = (1.0 + r).cumprod()
    total = float(equity.iloc[-1] - 1.0)
    cagr = float((1.0 + total) ** (252.0 / len(r)) - 1.0)
    sharpe = float(r.mean() / r.std() * math.sqrt(252.0)) if r.std() > 0 else 0.0
    max_drawdown = float((equity / equity.cummax() - 1.0).min())
    return {
        "total_return_pct": round(total * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(max_drawdown * 100.0, 2),
    }


def _score_rows(df: pd.DataFrame) -> pd.DataFrame:
    mom = _load_momentum_engine()
    df = df.copy()
    df["accel"] = mom._compute_accel(df["close"], df["sma3"], lb=5)

    rows = []
    for i in range(len(df) - 1):
        hist = df.iloc[: i + 1].copy()
        n = len(hist)
        if n < 252:
            continue

        last = hist.iloc[-1]
        expanding_pct = hist["accel"].expanding(min_periods=252).rank(pct=True)
        last_pct = expanding_pct.iloc[-1]
        accel_pct = float(last_pct) if not pd.isna(last_pct) else 0.5

        state_machine = mom._run_cc_overbought_window(hist, holdout=3, window=504)
        close = float(last["close"])
        sma10 = float(last.get("sma10", np.nan))
        sma20 = float(last.get("sma20", np.nan))
        sma50 = float(last.get("sma50", np.nan))
        sma200 = float(last.get("sma200", np.nan))
        volume = float(last.get("volume", np.nan))
        vol_sma20 = float(last.get("vol_sma20", np.nan))

        trend = mom._score_trend_strength(close, sma10, sma20, sma50, sma200)
        health = mom._score_momentum_health(accel_pct)
        regime_quality = mom._score_regime_quality(
            state_machine["invested_pct"],
            state_machine["exits_ob"],
            state_machine["exits_fs"],
            state_machine["exits_dc"],
        )
        volume_confirmation = mom._score_volume_confirmation(volume, vol_sma20, close, sma20)
        score = mom._clamp(
            trend * 0.40
            + health * 0.30
            + regime_quality * 0.20
            + volume_confirmation * 0.10
        )
        next_close_return = float(df.iloc[i + 1]["close"] / df.iloc[i]["close"] - 1.0)
        next_open_close_return = float(df.iloc[i + 1]["close"] / df.iloc[i + 1]["open"] - 1.0)
        next_open_to_open_return = float(df.iloc[i + 2]["open"] / df.iloc[i + 1]["open"] - 1.0) if i + 2 < len(df) else np.nan

        rows.append(
            {
                "date": last["date"],
                "close": close,
                "score": score,
                "trend_strength": trend,
                "momentum_health": health,
                "regime_quality": regime_quality,
                "volume_confirmation": volume_confirmation,
                "signal_state": state_machine["signal_state"],
                "next_return": next_close_return,
                "next_open_close_return": next_open_close_return,
                "next_open_to_open_return": next_open_to_open_return,
            }
        )

    return pd.DataFrame(rows).dropna()


def walk_forward_audit(ticker: str, start: str, eval_start: str | None = None) -> dict:
    """Compare cached indicator scoring to indicators recomputed on each prefix.

    Use ``start`` as the data warmup start and ``eval_start`` as the first date
    to check. This avoids false mismatches from intentionally-warmed indicators.
    """
    df = data_engine.load(ticker, start).copy()
    raw_cols = [c for c in ["date", "open", "high", "low", "close", "volume", "vix"] if c in df.columns]
    raw = df[raw_cols].copy()
    mom = _load_momentum_engine()

    def score_last(indicator_df: pd.DataFrame) -> dict | None:
        hist = indicator_df.copy()
        if len(hist) < 252:
            return None
        hist["accel"] = mom._compute_accel(hist["close"], hist["sma3"], lb=5)
        last = hist.iloc[-1]
        last_pct = hist["accel"].expanding(min_periods=252).rank(pct=True).iloc[-1]
        accel_pct = float(last_pct) if not pd.isna(last_pct) else 0.5
        state_machine = mom._run_cc_overbought_window(hist, holdout=3, window=504)
        close = float(last["close"])
        sma10 = float(last.get("sma10", np.nan))
        sma20 = float(last.get("sma20", np.nan))
        sma50 = float(last.get("sma50", np.nan))
        sma200 = float(last.get("sma200", np.nan))
        volume = float(last.get("volume", np.nan))
        vol_sma20 = float(last.get("vol_sma20", np.nan))
        trend = mom._score_trend_strength(close, sma10, sma20, sma50, sma200)
        health = mom._score_momentum_health(accel_pct)
        regime_quality = mom._score_regime_quality(
            state_machine["invested_pct"],
            state_machine["exits_ob"],
            state_machine["exits_fs"],
            state_machine["exits_dc"],
        )
        volume_confirmation = mom._score_volume_confirmation(volume, vol_sma20, close, sma20)
        score = mom._clamp(
            trend * 0.40
            + health * 0.30
            + regime_quality * 0.20
            + volume_confirmation * 0.10
        )
        return {
            "score": score,
            "trend_strength": trend,
            "momentum_health": health,
            "regime_quality": regime_quality,
            "volume_confirmation": volume_confirmation,
            "signal_state": str(state_machine["signal_state"]),
        }

    mismatches = []
    material_mismatches = 0
    checked = 0
    first_idx = 0
    if eval_start:
        matches = df.index[df["date"] >= pd.to_datetime(eval_start)]
        if len(matches) == 0:
            raise RuntimeError(f"No rows on/after eval_start={eval_start}")
        first_idx = int(matches[0])

    for i in range(max(first_idx, 251), len(df) - 1):
        if i + 1 < 252:
            continue
        cached = score_last(df.iloc[: i + 1].copy())
        recomputed = data_engine._compute_indicators(raw.iloc[: i + 1].copy())
        walked = score_last(recomputed)
        if cached is None or walked is None:
            continue
        checked += 1
        diffs = {k: (cached[k], walked[k]) for k in cached if cached[k] != walked[k]}
        if diffs:
            mismatches.append({"date": str(df.iloc[i]["date"])[:10], "diffs": diffs})
            material_mismatches += 1

    return {
        "checked_days": checked,
        "mismatch_days": len(mismatches),
        "material_mismatch_days": material_mismatches,
        "first_mismatches": mismatches[:10],
    }


def run(ticker: str, start: str, thresholds: list[int], entry: str = "close") -> dict:
    df = data_engine.load(ticker, start).copy()
    scored = _score_rows(df)
    if scored.empty:
        raise RuntimeError(f"No scored rows for {ticker}")

    return_col = {
        "close": "next_return",
        "next_open": "next_open_close_return",
        "next_open_to_open": "next_open_to_open_return",
    }[entry]
    latest = scored.iloc[-1]
    bucket_rows = []
    for low, high in [(0, 40), (40, 50), (50, 55), (55, 65), (65, 101)]:
        bucket = scored[(scored["score"] >= low) & (scored["score"] < high)]
        if bucket.empty:
            continue
        stats = _annualized_stats(bucket[return_col])
        bucket_rows.append(
            {
                "bucket": f"{low}-{high}",
                "days": int(len(bucket)),
                "avg_next_day_pct": round(float(bucket[return_col].mean() * 100.0), 4),
                "win_rate_pct": round(float((bucket[return_col] > 0).mean() * 100.0), 2),
                **stats,
            }
        )

    strategies = []
    for threshold in thresholds:
        signal = scored["score"] >= threshold
        strategy_returns = np.where(signal, scored[return_col], 0.0)
        strategies.append(
            {
                "threshold": threshold,
                "exposure_pct": round(float(signal.mean() * 100.0), 2),
                "signal_days": int(signal.sum()),
                **_annualized_stats(strategy_returns),
            }
        )

    return {
        "ticker": ticker.upper(),
        "start": str(scored["date"].min())[:10],
        "end": str(scored["date"].max())[:10],
        "days": int(len(scored)),
        "latest": {
            "date": str(latest["date"])[:10],
            "close": round(float(latest["close"]), 4),
            "score": int(latest["score"]),
            "trend_strength": int(latest["trend_strength"]),
            "momentum_health": int(latest["momentum_health"]),
            "regime_quality": int(latest["regime_quality"]),
            "volume_confirmation": int(latest["volume_confirmation"]),
            "signal_state": str(latest["signal_state"]),
        },
        "one_day_ic": {
            "pearson": round(float(scored["score"].corr(scored["next_return"])), 6),
            "spearman": round(float(scored["score"].corr(scored["next_return"], method="spearman")), 6),
        },
        "buckets": bucket_rows,
        "strategies": strategies,
        "entry": entry,
        "buy_hold": _annualized_stats(scored[return_col]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest Aeternus momentum pillar")
    parser.add_argument("--ticker", default="MU")
    parser.add_argument("--start", default="2000-01-01")
    parser.add_argument("--thresholds", default="50,55,60,65,70")
    parser.add_argument("--entry", choices=["close", "next_open", "next_open_to_open"], default="close")
    parser.add_argument("--audit-walk-forward", action="store_true")
    parser.add_argument("--eval-start", default=None, help="First date to check during walk-forward audit")
    args = parser.parse_args()

    if args.audit_walk_forward:
        audit = walk_forward_audit(args.ticker, args.start, args.eval_start)
        print("Walk-forward audit: cached indicators vs recomputed truncated-prefix indicators")
        print(audit)
        return

    thresholds = [int(x.strip()) for x in args.thresholds.split(",") if x.strip()]
    result = run(args.ticker, args.start, thresholds, entry=args.entry)

    print(f"{result['ticker']} momentum pillar backtest")
    print(f"Period: {result['start']} -> {result['end']} ({result['days']} scored days)")
    print(f"Latest: {result['latest']}")
    print(f"Entry mode: {result['entry']}")
    print(f"1-day IC: {result['one_day_ic']}")
    print("\nBuckets:")
    for row in result["buckets"]:
        print(row)
    print("\nStrategies: long if score >= threshold, else cash")
    for row in result["strategies"]:
        print(row)
    print("\nBuy/hold:")
    print(result["buy_hold"])


if __name__ == "__main__":
    main()
