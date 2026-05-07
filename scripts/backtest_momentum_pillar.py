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
        next_return = float(df.iloc[i + 1]["close"] / df.iloc[i]["close"] - 1.0)

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
                "next_return": next_return,
            }
        )

    return pd.DataFrame(rows).dropna()


def run(ticker: str, start: str, thresholds: list[int]) -> dict:
    df = data_engine.load(ticker, start).copy()
    scored = _score_rows(df)
    if scored.empty:
        raise RuntimeError(f"No scored rows for {ticker}")

    latest = scored.iloc[-1]
    bucket_rows = []
    for low, high in [(0, 40), (40, 50), (50, 55), (55, 65), (65, 101)]:
        bucket = scored[(scored["score"] >= low) & (scored["score"] < high)]
        if bucket.empty:
            continue
        stats = _annualized_stats(bucket["next_return"])
        bucket_rows.append(
            {
                "bucket": f"{low}-{high}",
                "days": int(len(bucket)),
                "avg_next_day_pct": round(float(bucket["next_return"].mean() * 100.0), 4),
                "win_rate_pct": round(float((bucket["next_return"] > 0).mean() * 100.0), 2),
                **stats,
            }
        )

    strategies = []
    for threshold in thresholds:
        signal = scored["score"] >= threshold
        strategy_returns = np.where(signal, scored["next_return"], 0.0)
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
        "buy_hold": _annualized_stats(scored["next_return"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest Aeternus momentum pillar")
    parser.add_argument("--ticker", default="MU")
    parser.add_argument("--start", default="2000-01-01")
    parser.add_argument("--thresholds", default="50,55,60,65,70")
    args = parser.parse_args()

    thresholds = [int(x.strip()) for x in args.thresholds.split(",") if x.strip()]
    result = run(args.ticker, args.start, thresholds)

    print(f"{result['ticker']} momentum pillar backtest")
    print(f"Period: {result['start']} -> {result['end']} ({result['days']} scored days)")
    print(f"Latest: {result['latest']}")
    print(f"1-day IC: {result['one_day_ic']}")
    print("\nBuckets:")
    for row in result["buckets"]:
        print(row)
    print("\nStrategies: long next day if score >= threshold, else cash")
    for row in result["strategies"]:
        print(row)
    print("\nBuy/hold:")
    print(result["buy_hold"])


if __name__ == "__main__":
    main()
