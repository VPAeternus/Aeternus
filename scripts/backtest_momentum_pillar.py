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
import hashlib
import contextlib
import io

import numpy as np
import pandas as pd

from tradingagents.phase_engine import data_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOMENTUM_ENGINE_PATH = PROJECT_ROOT / "tradingagents" / "agents" / "utils" / "momentum_engine.py"
SCORE_CACHE_DIR = PROJECT_ROOT / ".cache" / "momentum_pillar_scores"
SCORE_CACHE_VERSION = "v2_balanced_no_volume"


def _load_momentum_engine():
    """Load momentum_engine without importing tradingagents.agents package."""
    spec = importlib.util.spec_from_file_location("momentum_engine", MOMENTUM_ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {MOMENTUM_ENGINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WEIGHT_SETS = {
    "legacy_40_30_20_10": {"trend_strength": 0.40, "momentum_health": 0.30, "regime_quality": 0.20, "volume_confirmation": 0.10},
    "regime_30_20_40_10": {"trend_strength": 0.30, "momentum_health": 0.20, "regime_quality": 0.40, "volume_confirmation": 0.10},
    "regime_30_15_45_10": {"trend_strength": 0.30, "momentum_health": 0.15, "regime_quality": 0.45, "volume_confirmation": 0.10},
    "balanced_30_25_35_10": {"trend_strength": 0.30, "momentum_health": 0.25, "regime_quality": 0.35, "volume_confirmation": 0.10},
}


def _constrained_weight_grid(step: int = 10) -> dict[str, dict[str, float]]:
    """Small ex-ante grid to avoid arbitrary formulas and limit data snooping."""
    out = {}
    for trend in range(20, 61, step):
        for health in range(10, 51, step):
            for regime in range(20, 61, step):
                for volume in range(0, 11, step):
                    if trend + health + regime + volume != 100:
                        continue
                    name = f"grid_{trend}_{health}_{regime}_{volume}"
                    out[name] = {
                        "trend_strength": trend / 100.0,
                        "momentum_health": health / 100.0,
                        "regime_quality": regime / 100.0,
                        "volume_confirmation": volume / 100.0,
                    }
    return out


CONSTRAINED_WEIGHT_GRID = _constrained_weight_grid()


def _weight_candidates(weight_mode: str) -> dict[str, dict[str, float]]:
    if weight_mode == "predefined":
        return WEIGHT_SETS
    if weight_mode == "constrained":
        return CONSTRAINED_WEIGHT_GRID
    raise ValueError("weight_mode must be 'predefined' or 'constrained'")


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


def _cache_path(ticker: str, start: str, df: pd.DataFrame) -> Path:
    first = str(df["date"].min())[:10] if "date" in df.columns and not df.empty else "none"
    last = str(df["date"].max())[:10] if "date" in df.columns and not df.empty else "none"
    source_hash = hashlib.sha256(
        Path(__file__).read_bytes() + MOMENTUM_ENGINE_PATH.read_bytes()
    ).hexdigest()[:16]
    key = f"{SCORE_CACHE_VERSION}|{source_hash}|{ticker.upper()}|{start}|{len(df)}|{first}|{last}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return SCORE_CACHE_DIR / f"{ticker.upper()}_{digest}.pkl"


def _score_rows_cached(ticker: str, start: str) -> pd.DataFrame:
    df = data_engine.load(ticker, start).copy()
    path = _cache_path(ticker, start, df)
    if path.exists():
        return pd.read_pickle(path)
    scored = _score_rows(df)
    SCORE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    scored.to_pickle(path)
    return scored


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
            trend * 0.33
            + health * 0.34
            + regime_quality * 0.33
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
            trend * 0.33
            + health * 0.34
            + regime_quality * 0.33
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


def _apply_weights(scored: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    return (
        scored["trend_strength"] * weights["trend_strength"]
        + scored["momentum_health"] * weights["momentum_health"]
        + scored["regime_quality"] * weights["regime_quality"]
        + scored["volume_confirmation"] * weights["volume_confirmation"]
    ).clip(0, 100).astype(int)


def _return_column(entry: str) -> str:
    return {
        "close": "next_return",
        "next_open": "next_open_close_return",
        "next_open_to_open": "next_open_to_open_return",
    }[entry]


def _strategy_returns(scored: pd.DataFrame, score: pd.Series, threshold: int, return_col: str) -> pd.Series:
    signal = score >= threshold
    return pd.Series(np.where(signal, scored[return_col], 0.0), index=scored.index)


def walk_forward_weight_grid(
    ticker: str,
    start: str,
    entry: str,
    thresholds: list[int],
    train_years: int = 5,
    test_years: int = 1,
    rebalance: str = "annual",
    select_metric: str = "sharpe",
    weight_mode: str = "predefined",
) -> dict:
    """Walk-forward select weight set + threshold on train, apply to unseen test.

    Rebalance cadence: annual by default. That matches slow-moving regime quality;
    monthly/quarterly would invite overfitting and unnecessary turnover.
    """
    if select_metric not in {"sharpe", "cagr"}:
        raise ValueError("select_metric must be 'sharpe' or 'cagr'")
    if rebalance != "annual":
        raise ValueError("Only annual rebalance is supported for now")
    weight_sets = _weight_candidates(weight_mode)

    scored = _score_rows_cached(ticker, start).dropna().reset_index(drop=True)
    return_col = _return_column(entry)
    scored = scored.dropna(subset=[return_col]).reset_index(drop=True)
    scored["year"] = pd.to_datetime(scored["date"]).dt.year
    years = sorted(scored["year"].unique())

    folds = []
    oos_returns = []
    for idx in range(train_years, len(years), test_years):
        train_year_set = set(years[idx - train_years:idx])
        test_year_set = set(years[idx:idx + test_years])
        train = scored[scored["year"].isin(train_year_set)]
        test = scored[scored["year"].isin(test_year_set)]
        if train.empty or test.empty:
            continue

        candidates = []
        for weight_name, weights in weight_sets.items():
            train_score = _apply_weights(train, weights)
            for threshold in thresholds:
                stats = _annualized_stats(_strategy_returns(train, train_score, threshold, return_col))
                primary = stats["cagr_pct"] if select_metric == "cagr" else stats["sharpe"]
                secondary = stats["sharpe"] if select_metric == "cagr" else stats["cagr_pct"]
                candidates.append((primary, secondary, weight_name, threshold, weights))
        candidates.sort(reverse=True)
        _, _, weight_name, threshold, weights = candidates[0]

        test_score = _apply_weights(test, weights)
        test_returns = _strategy_returns(test, test_score, threshold, return_col)
        oos_returns.extend(test_returns.tolist())
        test_stats = _annualized_stats(test_returns)
        folds.append({
            "train_years": f"{min(train_year_set)}-{max(train_year_set)}",
            "test_years": f"{min(test_year_set)}-{max(test_year_set)}",
            "weight_set": weight_name,
            "threshold": threshold,
            **test_stats,
        })

    buy_hold = _annualized_stats(scored[return_col])
    oos = _annualized_stats(oos_returns)
    return {
        "ticker": ticker.upper(),
        "entry": entry,
        "rebalance": rebalance,
        "select_metric": select_metric,
        "weight_mode": weight_mode,
        "weight_candidate_count": len(weight_sets),
        "train_years": train_years,
        "test_years": test_years,
        "folds": folds,
        "oos": oos,
        "buy_hold": buy_hold,
        "fold_count": len(folds),
    }


def run(ticker: str, start: str, thresholds: list[int], entry: str = "close") -> dict:
    scored = _score_rows_cached(ticker, start)
    if scored.empty:
        raise RuntimeError(f"No scored rows for {ticker}")

    return_col = _return_column(entry)
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


def _default_top_unique() -> list[str]:
    # Current large-weight QQQ/SPY holdings, manually fixed for reproducibility.
    # Use hyphenated share-class tickers because data_engine/yfinance accepts them.
    qqq_top = [
        "MSFT", "NVDA", "AAPL", "AMZN", "META", "AVGO", "GOOGL", "GOOG", "TSLA", "COST",
        "NFLX", "TMUS", "PLTR", "CSCO", "AMD", "LIN", "PEP", "ISRG", "INTU", "BKNG",
        "QCOM", "TXN", "AMGN", "AMAT", "ADBE", "HON", "GILD", "PANW", "CMCSA", "ADP",
        "MELI", "VRTX", "SBUX", "ADI", "LRCX", "MU", "KLAC", "CRWD", "CDNS", "CEG",
        "MDLZ", "MAR", "ORLY", "ABNB", "CTAS", "DASH", "SNPS", "PYPL", "REGN", "FTNT",
    ]
    spy_top = [
        "MSFT", "NVDA", "AAPL", "AMZN", "META", "AVGO", "GOOGL", "BRK-B", "GOOG", "TSLA",
        "JPM", "LLY", "V", "NFLX", "XOM", "MA", "COST", "WMT", "PG", "JNJ",
        "HD", "ABBV", "BAC", "KO", "PM", "PLTR", "UNH", "GE", "CSCO", "IBM",
        "WFC", "CVX", "ABT", "CRM", "MS", "LIN", "AXP", "MCD", "MRK", "DIS",
        "T", "GS", "NOW", "UBER", "RTX", "PEP", "INTU", "BX", "AMD", "VZ",
    ]
    out = []
    for qqq_ticker, spy_ticker in zip(qqq_top, spy_top):
        for ticker in (qqq_ticker, spy_ticker):
            if ticker not in out:
                out.append(ticker)
            if len(out) >= 50:
                return out
    return out[:50]


def _run_batch(tickers: list[str], start: str, thresholds: list[int], entry: str) -> None:
    rows = []
    for ticker in tickers:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                result = run(ticker, start, thresholds, entry=entry)
            if isinstance(result.get("strategies"), list):
                best = max(result["strategies"], key=lambda row: row["sharpe"])
                buy_hold = result["buy_hold"]
                rows.append({
                    "ticker": result["ticker"],
                    "best_threshold": best["threshold"],
                    "best_cagr_pct": best["cagr_pct"],
                    "best_sharpe": best["sharpe"],
                    "best_max_dd_pct": best["max_drawdown_pct"],
                    "best_exposure_pct": best["exposure_pct"],
                    "buy_hold_cagr_pct": buy_hold["cagr_pct"],
                    "buy_hold_sharpe": buy_hold["sharpe"],
                    "buy_hold_max_dd_pct": buy_hold["max_drawdown_pct"],
                })
            else:
                buy_hold = result["buy_hold"]
                oos = result["oos"]
                rows.append({
                    "ticker": result["ticker"],
                    "fold_count": result["fold_count"],
                    "weight_mode": result.get("weight_mode"),
                    "weight_candidate_count": result.get("weight_candidate_count"),
                    "best_cagr_pct": oos["cagr_pct"],
                    "best_sharpe": oos["sharpe"],
                    "best_max_dd_pct": oos["max_drawdown_pct"],
                    "buy_hold_cagr_pct": buy_hold["cagr_pct"],
                    "buy_hold_sharpe": buy_hold["sharpe"],
                    "buy_hold_max_dd_pct": buy_hold["max_drawdown_pct"],
                })
            print(rows[-1])
        except Exception as exc:
            print({"ticker": ticker, "error": str(exc)})
    if rows:
        frame = pd.DataFrame(rows)
        print("\nBatch summary")
        print({
            "tickers": len(frame),
            "avg_best_cagr_pct": round(float(frame["best_cagr_pct"].mean()), 2),
            "avg_best_sharpe": round(float(frame["best_sharpe"].mean()), 3),
            "avg_best_max_dd_pct": round(float(frame["best_max_dd_pct"].mean()), 2),
            "avg_buy_hold_cagr_pct": round(float(frame["buy_hold_cagr_pct"].mean()), 2),
            "avg_buy_hold_sharpe": round(float(frame["buy_hold_sharpe"].mean()), 3),
            "avg_buy_hold_max_dd_pct": round(float(frame["buy_hold_max_dd_pct"].mean()), 2),
            "outperformed_cagr_count": int((frame["best_cagr_pct"] > frame["buy_hold_cagr_pct"]).sum()),
            "outperformed_sharpe_count": int((frame["best_sharpe"] > frame["buy_hold_sharpe"]).sum()),
        })


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest Aeternus momentum pillar")
    parser.add_argument("--ticker", default="MU")
    parser.add_argument("--start", default="2000-01-01")
    parser.add_argument("--thresholds", default="50,55,60,65,70")
    parser.add_argument("--entry", choices=["close", "next_open", "next_open_to_open"], default="close")
    parser.add_argument("--audit-walk-forward", action="store_true")
    parser.add_argument("--batch-top-qqq-spy", action="store_true", help="Run top 50 unique current QQQ/SPY holdings")
    parser.add_argument("--walk-forward-grid", action="store_true", help="Walk-forward select momentum weights/threshold")
    parser.add_argument("--train-years", type=int, default=5)
    parser.add_argument("--test-years", type=int, default=1)
    parser.add_argument("--select-metric", choices=["sharpe", "cagr"], default="sharpe")
    parser.add_argument("--weight-mode", choices=["predefined", "constrained"], default="predefined")
    parser.add_argument("--eval-start", default=None, help="First date to check during walk-forward audit")
    args = parser.parse_args()

    if args.batch_top_qqq_spy:
        thresholds = [int(x.strip()) for x in args.thresholds.split(",") if x.strip()]
        if args.walk_forward_grid:
            original_run = run
            try:
                globals()["run"] = lambda ticker, start, thresholds, entry="close": walk_forward_weight_grid(
                    ticker,
                    start,
                    entry,
                    thresholds,
                    train_years=args.train_years,
                    test_years=args.test_years,
                    select_metric=args.select_metric,
                    weight_mode=args.weight_mode,
                )
                _run_batch(_default_top_unique(), args.start, thresholds, args.entry)
            finally:
                globals()["run"] = original_run
        else:
            _run_batch(_default_top_unique(), args.start, thresholds, args.entry)
        return

    if args.walk_forward_grid:
        thresholds = [int(x.strip()) for x in args.thresholds.split(",") if x.strip()]
        result = walk_forward_weight_grid(
            args.ticker,
            args.start,
            args.entry,
            thresholds,
            train_years=args.train_years,
            test_years=args.test_years,
            select_metric=args.select_metric,
            weight_mode=args.weight_mode,
        )
        print(result)
        return

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
