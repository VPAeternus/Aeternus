"""Bullish FVG replay features for Step 1 recall experiments."""

from __future__ import annotations

from datetime import date
from io import StringIO
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

import math

import pandas as pd
import requests
import yfinance as yf


DEFAULT_SEMIS_AI_NARROW_UNIVERSE: tuple[str, ...] = (
    "NVDA",
    "AMD",
    "MU",
    "AVGO",
    "TSM",
    "ARM",
    "MRVL",
    "AMAT",
    "LRCX",
    "KLAC",
    "SMCI",
    "PLTR",
    "SNDK",
    "ANET",
)
DEFAULT_QQQ_TOP20_PROXY_LIMIT = 20
DEFAULT_SPY_TOP20_LIMIT = 20

SLICE_NAMES: tuple[str, ...] = (
    "raw_fvg",
    "fvg_plus_rs",
    "fvg_plus_rs_above_sma20",
    "fvg_plus_rs_sma20_above_sma50",
    "fvg_plus_rs_sma50_above_sma200",
    "fvg_plus_rs_full_stack",
    "fvg_plus_rs_trend",
    "fvg_plus_rs_trend_volume",
)


def compute_bullish_fvg_snapshot(
    frame: pd.DataFrame,
    index: int,
    benchmark_frame: pd.DataFrame | None = None,
    atr_floor: float = 0.25,
) -> Dict[str, Any]:
    hist = _normalize_frame(frame).iloc[: index + 1].copy()
    if hist.empty or index < 2 or len(hist) < 3:
        return _empty_snapshot()

    hist["atr_14"] = _atr(hist, period=14)
    hist["bull_gap_size"] = _bull_gap_size(hist)
    hist["bear_gap_size"] = _bear_gap_size(hist)

    current = hist.iloc[-1]
    atr_value = float(current.get("atr_14", 0.0) or 0.0)
    raw_gap = float(current.get("bull_gap_size", 0.0) or 0.0)
    fvg_size_atr = raw_gap / atr_value if atr_value > 0 else 0.0
    bullish_present = raw_gap > 0.0 and fvg_size_atr >= float(atr_floor)

    fvg_midpoint = float("nan")
    if raw_gap > 0.0:
        fvg_midpoint = float(hist["low"].iloc[-1] + hist["high"].iloc[-3]) / 2.0

    valid_bull = ((hist["bull_gap_size"] > 0.0) & (_safe_div(hist["bull_gap_size"], hist["atr_14"]) >= atr_floor)).astype(int)
    valid_bear = ((hist["bear_gap_size"] > 0.0) & (_safe_div(hist["bear_gap_size"], hist["atr_14"]) >= atr_floor)).astype(int)
    last_ten = hist.iloc[-10:]
    same_direction_count = int(valid_bull.iloc[-len(last_ten):].sum())
    alternating_count = int(valid_bear.iloc[-len(last_ten):].sum())

    persistence_days = 0
    if bullish_present and not math.isnan(fvg_midpoint):
        for close in reversed(hist["close"].tolist()):
            if float(close) >= fvg_midpoint:
                persistence_days += 1
            else:
                break

    rs20 = _relative_strength(hist["close"], benchmark_frame, bars=20)
    rs60 = _relative_strength(hist["close"], benchmark_frame, bars=60)
    volume_z = _volume_zscore(hist["volume"], bars=20)
    distance_to_high = _distance_to_52w_high(hist["close"])
    sma20 = _last_sma(hist["close"], 20)
    sma50 = _last_sma(hist["close"], 50)
    sma200 = _last_sma(hist["close"], 200)
    trend_alignment = _trend_alignment(hist["close"])

    return {
        "bullish_fvg_present": bullish_present,
        "fvg_size": raw_gap,
        "fvg_size_atr": float(fvg_size_atr),
        "fvg_midpoint": fvg_midpoint,
        "same_direction_fvg_count_10d": same_direction_count,
        "alternating_gap_count_10d": alternating_count,
        "gap_persistence_days": persistence_days,
        "price_above_gap_midpoint": bool(not math.isnan(fvg_midpoint) and float(hist["close"].iloc[-1]) >= fvg_midpoint),
        "relative_strength_20d": rs20,
        "relative_strength_60d": rs60,
        "volume_zscore_20d": volume_z,
        "distance_to_52w_high": distance_to_high,
        "price_above_sma20": bool(float(hist["close"].iloc[-1]) >= sma20),
        "sma20_above_sma50": bool(sma20 >= sma50),
        "sma50_above_sma200": bool(sma50 >= sma200),
        "trend_alignment_20_50_200": trend_alignment,
    }


def score_bullish_recall_snapshot(snapshot: Dict[str, Any]) -> float:
    fvg_quality = (
        40.0 * (1.0 if snapshot.get("bullish_fvg_present") else 0.0)
        + 20.0 * _bounded_ratio(float(snapshot.get("fvg_size_atr", 0.0)), cap=2.0)
        + 20.0 * _bounded_ratio(float(snapshot.get("same_direction_fvg_count_10d", 0.0)), cap=4.0)
        + 10.0 * _bounded_ratio(float(snapshot.get("gap_persistence_days", 0.0)), cap=5.0)
        + 10.0 * (1.0 if snapshot.get("price_above_gap_midpoint") else 0.0)
    )
    fvg_quality -= 15.0 * _bounded_ratio(float(snapshot.get("alternating_gap_count_10d", 0.0)), cap=4.0)
    fvg_quality = _clamp(fvg_quality, 0.0, 100.0)

    relative_strength = (
        0.6 * _normalize_centered(float(snapshot.get("relative_strength_20d", 0.0)), scale=0.25)
        + 0.4 * _normalize_centered(float(snapshot.get("relative_strength_60d", 0.0)), scale=0.35)
    )
    trend_structure = (
        0.6 * float(snapshot.get("trend_alignment_20_50_200", 50.0))
        + 0.4 * (100.0 - 100.0 * float(snapshot.get("distance_to_52w_high", 1.0)))
    )
    volume_confirmation = _normalize_centered(float(snapshot.get("volume_zscore_20d", 0.0)), scale=2.0)

    score = (
        0.35 * fvg_quality
        + 0.30 * relative_strength
        + 0.20 * trend_structure
        + 0.15 * volume_confirmation
    )
    return float(round(_clamp(score, 0.0, 100.0), 4))


def run_fvg_backtest(
    tickers: Sequence[str] | None = None,
    start: str = "2020-01-01",
    end: str | None = None,
    top_n: int = 3,
    artifact_dir: str | Path | None = None,
    benchmark: str = "SMH",
    universe_name: str = "semis_ai_narrow",
    atr_floor: float = 0.25,
) -> Dict[str, Any]:
    normalized_universe_name = normalize_universe_name(universe_name)
    symbols = resolve_fvg_universe_tickers(
        tickers=tickers,
        universe_name=normalized_universe_name,
    )
    benchmark_symbol = str(benchmark).upper().strip()

    end_date = end or date.today().isoformat()
    base_dir = resolve_fvg_artifact_dir(
        artifact_dir=artifact_dir,
        run_date=date.today().isoformat(),
        universe_name=normalized_universe_name,
        benchmark=benchmark_symbol,
    )
    base_dir.mkdir(parents=True, exist_ok=True)

    history = _download_history(symbols + [benchmark_symbol], start=start, end=end_date)
    benchmark_frame = history.get(benchmark_symbol)

    event_rows: list[Dict[str, Any]] = []
    daily_rows: list[Dict[str, Any]] = []

    for symbol in symbols:
        frame = history.get(symbol)
        if frame is None or frame.empty:
            continue
        event_rows.extend(
            _build_event_rows(
                symbol=symbol,
                frame=frame,
                benchmark_frame=benchmark_frame,
                atr_floor=atr_floor,
            )
        )
        daily_rows.extend(
            _build_daily_rows(
                symbol=symbol,
                frame=frame,
                benchmark_frame=benchmark_frame,
                atr_floor=atr_floor,
            )
        )

    event_summary = _summarize_forward_returns(event_rows)
    basket_summary = _summarize_daily_baskets(daily_rows, top_n=top_n, benchmark_frame=benchmark_frame)
    basket_by_slice = _summarize_daily_baskets_by_slices(daily_rows, top_n=top_n, benchmark_frame=benchmark_frame)
    top_tickers, bottom_tickers = _rank_tickers(event_rows)
    by_regime = _summarize_rows_by_key(event_rows, key="regime")
    by_era = _summarize_rows_by_era(event_rows)
    by_slice = _summarize_rows_by_slices(event_rows)

    payload = {
        "universe_name": normalized_universe_name,
        "benchmark": benchmark_symbol,
        "tickers": symbols,
        "start": start,
        "end": end_date,
        "artifact_dir": str(base_dir),
        "event_summary": event_summary,
        "basket_summary": basket_summary,
        "basket_by_slice": basket_by_slice,
        "by_regime": by_regime,
        "by_era": by_era,
        "by_slice": by_slice,
        "top_tickers": top_tickers,
        "bottom_tickers": bottom_tickers,
    }

    (base_dir / "events.json").write_text(json.dumps(event_rows, indent=2))
    (base_dir / "daily_scores.json").write_text(json.dumps(daily_rows, indent=2))
    (base_dir / "summary.json").write_text(json.dumps(payload, indent=2))
    return payload


def run_fvg_strategy_backtest(
    ticker: str = "QQQ",
    benchmark: str = "SPY",
    start: str = "1999-01-01",
    end: str | None = None,
    artifact_dir: str | Path | None = None,
    atr_floor: float = 0.25,
    max_hold_days: int = 90,
    exit_mode: str = "exit_c",
    execution_timing: str = "next_open",
) -> Dict[str, Any]:
    symbol = str(ticker).upper().strip()
    benchmark_symbol = str(benchmark).upper().strip()
    end_date = end or date.today().isoformat()
    timing = normalize_execution_timing(execution_timing)
    base_dir = resolve_fvg_strategy_artifact_dir(
        artifact_dir=artifact_dir,
        run_date=date.today().isoformat(),
        ticker=symbol,
        benchmark=benchmark_symbol,
        execution_timing=timing,
    )
    base_dir.mkdir(parents=True, exist_ok=True)

    history = _download_history([symbol, benchmark_symbol], start=start, end=end_date)
    frame = history.get(symbol)
    benchmark_frame = history.get(benchmark_symbol)
    if frame is None or frame.empty:
        raise ValueError(f"Unable to load history for {symbol}")

    features = _build_feature_frame(frame, benchmark_frame=benchmark_frame, atr_floor=atr_floor)
    equity_curve, trades = _simulate_fvg_strategy_trades(
        features,
        max_hold_days=max_hold_days,
        exit_mode=normalize_exit_mode(exit_mode),
        execution_timing=timing,
    )

    exit_reason_counts: Dict[str, int] = {}
    for trade in trades:
        exit_reason = str(trade.get("exit_reason", "unknown"))
        exit_reason_counts[exit_reason] = exit_reason_counts.get(exit_reason, 0) + 1

    trade_returns = [float(trade["trade_return"]) for trade in trades]
    hold_days = [int(trade["hold_days"]) for trade in trades]
    payload = {
        "ticker": symbol,
        "benchmark": benchmark_symbol,
        "execution_timing": timing,
        "start": start,
        "end": end_date,
        "artifact_dir": str(base_dir),
        "total_trades": len(trades),
        "win_rate": _mean_or_none([1.0 if value > 0 else 0.0 for value in trade_returns]) if trade_returns else 0.0,
        "avg_trade_return": _mean_or_none(trade_returns) if trade_returns else 0.0,
        "total_return": float(equity_curve[-1]["equity"] - 1.0) if equity_curve else 0.0,
        "max_drawdown": _max_drawdown([float(point["equity"]) for point in equity_curve]),
        "avg_hold_days": _mean_or_none(hold_days) if hold_days else 0.0,
        "exit_reason_counts": exit_reason_counts,
        "trades": trades,
    }
    (base_dir / "summary.json").write_text(json.dumps(payload, indent=2))
    (base_dir / "trades.json").write_text(json.dumps(trades, indent=2))
    (base_dir / "equity_curve.json").write_text(json.dumps(equity_curve, indent=2))
    return payload


def run_fvg_strategy_exit_comparison(
    ticker: str = "QQQ",
    benchmark: str = "SPY",
    start: str = "1999-01-01",
    end: str | None = None,
    artifact_dir: str | Path | None = None,
    atr_floor: float = 0.25,
    max_hold_days: int = 90,
    execution_timing: str = "next_open",
) -> Dict[str, Any]:
    symbol = str(ticker).upper().strip()
    benchmark_symbol = str(benchmark).upper().strip()
    end_date = end or date.today().isoformat()
    timing = normalize_execution_timing(execution_timing)
    base_dir = resolve_fvg_strategy_artifact_dir(
        artifact_dir=artifact_dir,
        run_date=date.today().isoformat(),
        ticker=symbol,
        benchmark=benchmark_symbol,
        execution_timing=timing,
    )
    base_dir.mkdir(parents=True, exist_ok=True)

    history = _download_history([symbol, benchmark_symbol], start=start, end=end_date)
    frame = history.get(symbol)
    benchmark_frame = history.get(benchmark_symbol)
    if frame is None or frame.empty:
        raise ValueError(f"Unable to load history for {symbol}")

    strategies = {
        "exit_c": run_fvg_strategy_backtest(
            ticker=symbol,
            benchmark=benchmark_symbol,
            start=start,
            end=end_date,
            artifact_dir=base_dir / "exit_c",
            atr_floor=atr_floor,
            max_hold_days=max_hold_days,
            exit_mode="exit_c",
            execution_timing=timing,
        ),
        "sma50_only": run_fvg_strategy_backtest(
            ticker=symbol,
            benchmark=benchmark_symbol,
            start=start,
            end=end_date,
            artifact_dir=base_dir / "sma50_only",
            atr_floor=atr_floor,
            max_hold_days=max_hold_days,
            exit_mode="sma50_only",
            execution_timing=timing,
        ),
        "timeout_90d_only": run_fvg_strategy_backtest(
            ticker=symbol,
            benchmark=benchmark_symbol,
            start=start,
            end=end_date,
            artifact_dir=base_dir / "timeout_90d_only",
            atr_floor=atr_floor,
            max_hold_days=max_hold_days,
            exit_mode="timeout_90d_only",
            execution_timing=timing,
        ),
        "buy_and_hold": _buy_and_hold_strategy_summary(_normalize_frame(frame)),
    }
    payload = {
        "ticker": symbol,
        "benchmark": benchmark_symbol,
        "execution_timing": timing,
        "start": start,
        "end": end_date,
        "artifact_dir": str(base_dir),
        "strategies": strategies,
    }
    (base_dir / "comparison.json").write_text(json.dumps(payload, indent=2))
    return payload


def normalize_exit_mode(value: str | None) -> str:
    mode = str(value or "exit_c").strip().lower().replace("-", "_")
    if mode not in {"exit_c", "sma50_only", "timeout_90d_only"}:
        raise ValueError(f"Unsupported exit mode: {value}")
    return mode


def normalize_execution_timing(value: str | None) -> str:
    timing = str(value or "next_open").strip().lower().replace("-", "_")
    if timing not in {"next_open", "signal_close"}:
        raise ValueError(f"Unsupported execution timing: {value}")
    return timing


def normalize_universe_name(universe_name: str | None) -> str:
    name = str(universe_name or "semis_ai").strip().lower().replace("-", "_")
    aliases = {
        "semis_ai_narrow": "semis_ai",
        "semis_ai": "semis_ai",
        "qqq_top20_proxy": "qqq_top20",
        "qqq_top20": "qqq_top20",
        "spy_top20_proxy": "spy_top20",
        "spy_top20": "spy_top20",
    }
    return aliases.get(name or "semis_ai", name or "semis_ai")


def resolve_fvg_universe_tickers(
    tickers: Sequence[str] | None,
    universe_name: str,
) -> list[str]:
    if tickers:
        symbols = [str(symbol).upper().strip() for symbol in tickers]
        return [symbol for symbol in dict.fromkeys(symbols) if symbol]

    if universe_name == "qqq_top20":
        return get_current_qqq_top_holdings(limit=DEFAULT_QQQ_TOP20_PROXY_LIMIT)
    if universe_name == "spy_top20":
        return get_current_spy_top_holdings(limit=DEFAULT_SPY_TOP20_LIMIT)
    if universe_name == "semis_ai":
        return [symbol for symbol in DEFAULT_SEMIS_AI_NARROW_UNIVERSE]
    raise ValueError(f"Unsupported FVG universe: {universe_name}")


def get_current_qqq_top_holdings(limit: int = DEFAULT_QQQ_TOP20_PROXY_LIMIT) -> list[str]:
    holdings = getattr(yf.Ticker("QQQ").funds_data, "top_holdings", None)
    symbols = _extract_holdings_symbols(holdings.index.tolist() if holdings is not None and not holdings.empty else [])
    if len(symbols) >= limit:
        return symbols[:limit]

    fallback_symbols = _fetch_stockanalysis_qqq_holdings(limit=limit)
    merged = list(dict.fromkeys([*symbols, *fallback_symbols]))
    if len(merged) < limit:
        raise ValueError("Unable to load current QQQ top holdings")
    return merged[:limit]


def get_current_spy_top_holdings(limit: int = DEFAULT_SPY_TOP20_LIMIT) -> list[str]:
    holdings = getattr(yf.Ticker("SPY").funds_data, "top_holdings", None)
    symbols = _extract_holdings_symbols(holdings.index.tolist() if holdings is not None and not holdings.empty else [])
    if len(symbols) >= limit:
        return symbols[:limit]

    fallback_symbols = _fetch_stockanalysis_spy_holdings(limit=limit)
    merged = list(dict.fromkeys([*symbols, *fallback_symbols]))
    if len(merged) < limit:
        raise ValueError("Unable to load current SPY top holdings")
    return merged[:limit]


def resolve_fvg_artifact_dir(
    artifact_dir: str | Path | None,
    run_date: str,
    universe_name: str,
    benchmark: str,
) -> Path:
    if artifact_dir is not None:
        return Path(artifact_dir)
    return Path("eval_results") / "deal_flow" / "fvg_backtest" / run_date / f"{universe_name}-vs-{benchmark}"


def resolve_fvg_strategy_artifact_dir(
    artifact_dir: str | Path | None,
    run_date: str,
    ticker: str,
    benchmark: str,
    execution_timing: str = "next_open",
) -> Path:
    if artifact_dir is not None:
        return Path(artifact_dir)
    return (
        Path("eval_results")
        / "deal_flow"
        / "fvg_strategy_backtest"
        / run_date
        / f"{ticker}-vs-{benchmark}-{execution_timing}"
    )


def _extract_holdings_symbols(values: Iterable[Any]) -> list[str]:
    symbols = [str(symbol).upper().strip().replace(".", "-") for symbol in values]
    return [symbol for symbol in dict.fromkeys(symbols) if symbol]


def _fetch_stockanalysis_qqq_holdings(limit: int) -> list[str]:
    response = requests.get(
        "https://stockanalysis.com/etf/qqq/holdings/",
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    if not tables:
        return []
    table = tables[0]
    if "Symbol" not in table.columns:
        return []
    return _extract_holdings_symbols(table["Symbol"].tolist())[:limit]


def _fetch_stockanalysis_spy_holdings(limit: int) -> list[str]:
    response = requests.get(
        "https://stockanalysis.com/etf/spy/holdings/",
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    if not tables:
        return []
    table = tables[0]
    if "Symbol" not in table.columns:
        return []
    return _extract_holdings_symbols(table["Symbol"].tolist())[:limit]


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    hist = frame.copy()
    for column in ("open", "high", "low", "close", "volume"):
        hist[column] = pd.to_numeric(hist[column], errors="coerce")
    if "date" in hist.columns:
        hist["date"] = pd.to_datetime(hist["date"])
        hist = hist.sort_values("date")
    return hist.dropna(subset=["high", "low", "close", "volume"]).reset_index(drop=True)


def _atr(frame: pd.DataFrame, period: int) -> pd.Series:
    high = frame["high"]
    low = frame["low"]
    close = frame["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period, min_periods=1).mean()
    return atr.replace(0.0, pd.NA).ffill().bfill().fillna(1e-9)


def _bull_gap_size(frame: pd.DataFrame) -> pd.Series:
    return (frame["low"] - frame["high"].shift(2)).clip(lower=0.0).fillna(0.0)


def _bear_gap_size(frame: pd.DataFrame) -> pd.Series:
    return (frame["low"].shift(2) - frame["high"]).clip(lower=0.0).fillna(0.0)


def _relative_strength(close: pd.Series, benchmark_frame: pd.DataFrame | None, bars: int) -> float:
    if benchmark_frame is None:
        return 0.0
    bench = _normalize_frame(benchmark_frame)["close"]
    if len(close) <= bars or len(bench) <= bars:
        return 0.0
    stock_ret = (float(close.iloc[-1]) / float(close.iloc[-bars - 1])) - 1.0
    bench_ret = (float(bench.iloc[-1]) / float(bench.iloc[-bars - 1])) - 1.0
    return float(stock_ret - bench_ret)


def _volume_zscore(volume: pd.Series, bars: int) -> float:
    if len(volume) < 3:
        return 0.0
    sample = volume.iloc[-bars:] if len(volume) >= bars else volume
    mean = float(sample.mean())
    std = float(sample.std(ddof=0))
    if std <= 0.0:
        return 0.0
    return float((float(sample.iloc[-1]) - mean) / std)


def _distance_to_52w_high(close: pd.Series) -> float:
    if close.empty:
        return 1.0
    trailing_high = float(close.iloc[-252:].max())
    current = float(close.iloc[-1])
    if trailing_high <= 0.0:
        return 1.0
    distance = (trailing_high - current) / trailing_high
    return float(_clamp(distance, 0.0, 1.0))


def _trend_alignment(close: pd.Series) -> float:
    if close.empty:
        return 50.0
    current = float(close.iloc[-1])
    sma20 = _last_sma(close, 20)
    sma50 = _last_sma(close, 50)
    sma200 = _last_sma(close, 200)
    score = 50.0
    if current >= sma20:
        score += 15.0
    if sma20 >= sma50:
        score += 20.0
    if sma50 >= sma200:
        score += 15.0
    return float(_clamp(score, 0.0, 100.0))


def _last_sma(close: pd.Series, bars: int) -> float:
    if len(close) >= bars:
        return float(close.iloc[-bars:].mean())
    return float(close.mean())


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    result = numerator / denominator.replace(0.0, pd.NA)
    return result.fillna(0.0)


def _bounded_ratio(value: float, cap: float) -> float:
    if cap <= 0.0:
        return 0.0
    return _clamp(value / cap, 0.0, 1.0)


def _normalize_centered(value: float, scale: float) -> float:
    if scale <= 0.0:
        return 50.0
    normalized = 50.0 + 50.0 * (value / scale)
    return float(_clamp(normalized, 0.0, 100.0))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _empty_snapshot() -> Dict[str, Any]:
    return {
        "bullish_fvg_present": False,
        "fvg_size": 0.0,
        "fvg_size_atr": 0.0,
        "fvg_midpoint": float("nan"),
        "same_direction_fvg_count_10d": 0,
        "alternating_gap_count_10d": 0,
        "gap_persistence_days": 0,
        "price_above_gap_midpoint": False,
        "relative_strength_20d": 0.0,
        "relative_strength_60d": 0.0,
        "volume_zscore_20d": 0.0,
        "distance_to_52w_high": 1.0,
        "price_above_sma20": False,
        "sma20_above_sma50": False,
        "sma50_above_sma200": False,
        "trend_alignment_20_50_200": 50.0,
    }


def _download_history(symbols: Iterable[str], start: str, end: str) -> Dict[str, pd.DataFrame]:
    history: Dict[str, pd.DataFrame] = {}
    deduped = [symbol for symbol in dict.fromkeys(str(symbol).upper().strip() for symbol in symbols) if symbol]
    if not deduped:
        return history

    frame = yf.download(
        deduped,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=False,
    )
    if frame is None or frame.empty:
        return history

    for symbol in deduped:
        extracted = _extract_ohlcv_frame(frame, symbol)
        if extracted is not None and not extracted.empty:
            history[symbol] = extracted
    return history


def _extract_ohlcv_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame | None:
    try:
        if isinstance(frame.columns, pd.MultiIndex):
            if symbol in frame.columns.get_level_values(0):
                sub = frame[symbol].copy()
            else:
                fields = {}
                for field in ("Open", "High", "Low", "Close", "Volume"):
                    if (field, symbol) in frame.columns:
                        fields[field] = frame[(field, symbol)]
                if len(fields) != 5:
                    return None
                sub = pd.DataFrame(fields)
        else:
            if symbol != str(symbol).upper():
                return None
            sub = frame.copy()
        result = pd.DataFrame(
            {
                "date": pd.to_datetime(sub.index),
                "open": pd.to_numeric(sub["Open"], errors="coerce"),
                "high": pd.to_numeric(sub["High"], errors="coerce"),
                "low": pd.to_numeric(sub["Low"], errors="coerce"),
                "close": pd.to_numeric(sub["Close"], errors="coerce"),
                "volume": pd.to_numeric(sub["Volume"], errors="coerce"),
            }
        )
        return result.dropna(subset=["high", "low", "close", "volume"]).reset_index(drop=True)
    except Exception:
        return None


def _build_event_rows(
    symbol: str,
    frame: pd.DataFrame,
    benchmark_frame: pd.DataFrame | None,
    atr_floor: float,
) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    norm = _normalize_frame(frame)
    features = _build_feature_frame(norm, benchmark_frame=benchmark_frame, atr_floor=atr_floor)
    for index in range(2, len(features)):
        row = features.iloc[index]
        snapshot = _snapshot_from_feature_row(row)
        if not bool(snapshot["bullish_fvg_present"]):
            continue
        slice_flags = build_confirmation_slice_flags(
            bullish_fvg_present=bool(snapshot["bullish_fvg_present"]),
            relative_strength_20d=float(snapshot["relative_strength_20d"]),
            trend_alignment_20_50_200=float(snapshot["trend_alignment_20_50_200"]),
            volume_zscore_20d=float(snapshot["volume_zscore_20d"]),
            price_above_sma20=bool(snapshot["price_above_sma20"]),
            sma20_above_sma50=bool(snapshot["sma20_above_sma50"]),
            sma50_above_sma200=bool(snapshot["sma50_above_sma200"]),
        )
        rows.append(
            {
                "ticker": symbol,
                "event_date": pd.to_datetime(row["date"]).date().isoformat(),
                "score": float(row["score"]),
                "regime": str(row.get("regime", "unknown")),
                **slice_flags,
                **_serialize_snapshot(snapshot),
                **_forward_return_fields(features["close"], index=index),
            }
        )
    return rows


def _build_daily_rows(
    symbol: str,
    frame: pd.DataFrame,
    benchmark_frame: pd.DataFrame | None,
    atr_floor: float,
) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    norm = _normalize_frame(frame)
    features = _build_feature_frame(norm, benchmark_frame=benchmark_frame, atr_floor=atr_floor)
    for index in range(2, len(features)):
        row = features.iloc[index]
        snapshot = _snapshot_from_feature_row(row)
        slice_flags = build_confirmation_slice_flags(
            bullish_fvg_present=bool(snapshot["bullish_fvg_present"]),
            relative_strength_20d=float(snapshot["relative_strength_20d"]),
            trend_alignment_20_50_200=float(snapshot["trend_alignment_20_50_200"]),
            volume_zscore_20d=float(snapshot["volume_zscore_20d"]),
            price_above_sma20=bool(snapshot["price_above_sma20"]),
            sma20_above_sma50=bool(snapshot["sma20_above_sma50"]),
            sma50_above_sma200=bool(snapshot["sma50_above_sma200"]),
        )
        rows.append(
            {
                "date": pd.to_datetime(row["date"]).date().isoformat(),
                "ticker": symbol,
                "score": float(row["score"]),
                "regime": str(row.get("regime", "unknown")),
                **slice_flags,
                **_serialize_snapshot(snapshot),
                **_forward_return_fields(features["close"], index=index),
            }
        )
    return rows


def _build_feature_frame(
    frame: pd.DataFrame,
    benchmark_frame: pd.DataFrame | None,
    atr_floor: float,
) -> pd.DataFrame:
    features = _normalize_frame(frame).copy()
    features["atr_14"] = _atr(features, period=14)
    features["bull_gap_size"] = _bull_gap_size(features)
    features["bear_gap_size"] = _bear_gap_size(features)
    features["fvg_size_atr"] = _safe_div(features["bull_gap_size"], features["atr_14"])
    features["bullish_fvg_present"] = (
        (features["bull_gap_size"] > 0.0) & (features["fvg_size_atr"] >= atr_floor)
    )
    features["fvg_midpoint"] = ((features["low"] + features["high"].shift(2)) / 2.0).where(
        features["bull_gap_size"] > 0.0
    )
    valid_bull = ((features["bull_gap_size"] > 0.0) & (features["fvg_size_atr"] >= atr_floor)).astype(int)
    valid_bear = (
        (features["bear_gap_size"] > 0.0)
        & (_safe_div(features["bear_gap_size"], features["atr_14"]) >= atr_floor)
    ).astype(int)
    features["same_direction_fvg_count_10d"] = valid_bull.rolling(10, min_periods=1).sum().astype(int)
    features["alternating_gap_count_10d"] = valid_bear.rolling(10, min_periods=1).sum().astype(int)
    features["price_above_gap_midpoint"] = (
        features["fvg_midpoint"].notna() & (features["close"] >= features["fvg_midpoint"])
    )
    features["gap_persistence_days"] = _gap_persistence_days(features)

    relative_strength = _relative_strength_frame(features, benchmark_frame)
    features["relative_strength_20d"] = relative_strength["relative_strength_20d"]
    features["relative_strength_60d"] = relative_strength["relative_strength_60d"]
    features["regime"] = _aligned_regime_series(features, benchmark_frame)

    volume_roll = features["volume"].rolling(20, min_periods=3)
    volume_mean = volume_roll.mean()
    volume_std = volume_roll.std(ddof=0).replace(0.0, pd.NA)
    features["volume_zscore_20d"] = _safe_div(features["volume"] - volume_mean, volume_std).fillna(0.0)

    rolling_high = features["close"].rolling(252, min_periods=1).max().replace(0.0, pd.NA)
    features["distance_to_52w_high"] = ((rolling_high - features["close"]) / rolling_high).clip(0.0, 1.0).fillna(1.0)

    sma20 = features["close"].rolling(20, min_periods=1).mean()
    sma50 = features["close"].rolling(50, min_periods=1).mean()
    sma200 = features["close"].rolling(200, min_periods=1).mean()
    trend_score = (
        50.0
        + 15.0 * (features["close"] >= sma20).astype(float)
        + 20.0 * (sma20 >= sma50).astype(float)
        + 15.0 * (sma50 >= sma200).astype(float)
    )
    features["price_above_sma20"] = (features["close"] >= sma20)
    features["sma20_above_sma50"] = (sma20 >= sma50)
    features["sma50_above_sma200"] = (sma50 >= sma200)
    features["sma20"] = sma20
    features["sma50"] = sma50
    features["sma200"] = sma200
    features["trend_alignment_20_50_200"] = trend_score.clip(0.0, 100.0)

    features["score"] = features.apply(
        lambda row: score_bullish_recall_snapshot(_snapshot_from_feature_row(row)),
        axis=1,
    )
    return features


def _simulate_fvg_strategy_trades(
    features: pd.DataFrame,
    *,
    max_hold_days: int,
    exit_mode: str,
    execution_timing: str,
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    trades: list[Dict[str, Any]] = []
    equity_curve: list[Dict[str, Any]] = []
    cash = 1.0
    shares = 0.0
    open_trade: Dict[str, Any] | None = None

    for index, row in features.iterrows():
        current_date = pd.to_datetime(row["date"]).date().isoformat()
        close_price = float(row["close"])
        equity = cash if open_trade is None else shares * close_price
        equity_curve.append({"date": current_date, "equity": equity})

        if open_trade is not None:
            exit_reason = _strategy_exit_reason(
                row=row,
                entry_midpoint=float(open_trade["entry_fvg_midpoint"]),
                entry_index=int(open_trade["entry_index"]),
                current_index=index,
                max_hold_days=max_hold_days,
                exit_mode=exit_mode,
            )
            if exit_reason is not None and index + 1 < len(features):
                if execution_timing == "signal_close":
                    exit_row = row
                    exit_price = close_price
                    hold_days = int(index - int(open_trade["entry_index"]))
                else:
                    exit_row = features.iloc[index + 1]
                    exit_price = float(exit_row["open"])
                    hold_days = int((index + 1) - int(open_trade["entry_index"]))
                cash = shares * exit_price
                trades.append(
                    {
                        "entry_date": str(open_trade["entry_date"]),
                        "exit_date": pd.to_datetime(exit_row["date"]).date().isoformat(),
                        "entry_price": float(open_trade["entry_price"]),
                        "exit_price": exit_price,
                        "hold_days": hold_days,
                        "trade_return": float((cash / float(open_trade["starting_equity"])) - 1.0),
                        "exit_reason": exit_reason,
                    }
                )
                shares = 0.0
                open_trade = None

        if open_trade is None and _strategy_entry_signal(row) and (
            execution_timing == "signal_close" or index + 1 < len(features)
        ):
            starting_equity = cash
            if execution_timing == "signal_close":
                entry_row = row
                entry_index = index
                entry_price = close_price
            else:
                entry_row = features.iloc[index + 1]
                entry_index = index + 1
                entry_price = float(entry_row["open"])
            shares = 0.0 if entry_price <= 0.0 else cash / entry_price
            cash = 0.0
            open_trade = {
                "entry_index": entry_index,
                "entry_date": pd.to_datetime(entry_row["date"]).date().isoformat(),
                "entry_price": entry_price,
                "entry_fvg_midpoint": float(row["fvg_midpoint"]),
                "starting_equity": starting_equity,
                "execution_timing": execution_timing,
            }

    return equity_curve, trades


def _strategy_entry_signal(row: pd.Series) -> bool:
    midpoint = row.get("fvg_midpoint")
    return bool(
        row.get("bullish_fvg_present", False)
        and midpoint is not None
        and not (isinstance(midpoint, float) and math.isnan(midpoint))
        and float(row.get("relative_strength_20d", 0.0) or 0.0) > 0.0
        and bool(row.get("sma50_above_sma200", False))
    )


def _strategy_exit_reason(
    *,
    row: pd.Series,
    entry_midpoint: float,
    entry_index: int,
    current_index: int,
    max_hold_days: int,
    exit_mode: str,
) -> str | None:
    close_price = float(row.get("close", 0.0) or 0.0)
    sma50 = float(row.get("sma50", 0.0) or 0.0)
    rs20 = float(row.get("relative_strength_20d", 0.0) or 0.0)

    mode = normalize_exit_mode(exit_mode)
    if mode in {"exit_c", "sma50_only"} and close_price < sma50:
        return "close_below_sma50"
    if mode == "exit_c" and close_price < float(entry_midpoint) and rs20 < 0.0:
        return "fvg_midpoint_rs_break"
    if mode in {"exit_c", "timeout_90d_only"} and (current_index - entry_index) >= int(max_hold_days):
        return "timeout_90d"
    return None


def _aligned_regime_series(frame: pd.DataFrame, benchmark_frame: pd.DataFrame | None) -> pd.Series:
    if benchmark_frame is None or benchmark_frame.empty:
        return pd.Series(["unknown"] * len(frame), index=frame.index, dtype="object")

    benchmark = _normalize_frame(benchmark_frame)[["date"]].copy()
    benchmark["regime"] = _build_regime_series(benchmark_frame).tolist()
    merged = frame[["date"]].merge(benchmark, on="date", how="left")
    return merged["regime"].fillna("unknown").astype("object")


def classify_simple_regime(benchmark_frame: pd.DataFrame, index: int) -> str:
    series = _build_regime_series(benchmark_frame)
    if series.empty or index >= len(series):
        return "unknown"
    return str(series.iloc[index])


def market_era_label(value: str | pd.Timestamp) -> str:
    year = pd.to_datetime(value).year
    if year <= 2002:
        return "1999_2002_dotcom"
    if year <= 2007:
        return "2003_2007_pre_gfc"
    if year <= 2012:
        return "2008_2012_crisis_recovery"
    if year <= 2019:
        return "2013_2019_qe_bull"
    if year <= 2021:
        return "2020_2021_covid_liquidity"
    if year <= 2023:
        return "2022_2023_rate_reset"
    return "2024_2026_ai_cycle"


def build_confirmation_slice_flags(
    *,
    bullish_fvg_present: bool,
    relative_strength_20d: float,
    trend_alignment_20_50_200: float,
    volume_zscore_20d: float,
    price_above_sma20: bool,
    sma20_above_sma50: bool,
    sma50_above_sma200: bool,
) -> Dict[str, bool]:
    raw_fvg = bool(bullish_fvg_present)
    plus_rs = raw_fvg and float(relative_strength_20d) >= 0.03
    plus_above_sma20 = plus_rs and bool(price_above_sma20)
    plus_sma20_above_sma50 = plus_rs and bool(sma20_above_sma50)
    plus_sma50_above_sma200 = plus_rs and bool(sma50_above_sma200)
    plus_full_stack = plus_rs and bool(price_above_sma20) and bool(sma20_above_sma50) and bool(sma50_above_sma200)
    plus_trend = plus_rs and float(trend_alignment_20_50_200) >= 75.0
    plus_volume = plus_trend and float(volume_zscore_20d) >= 1.0
    return {
        "raw_fvg": raw_fvg,
        "fvg_plus_rs": plus_rs,
        "fvg_plus_rs_above_sma20": plus_above_sma20,
        "fvg_plus_rs_sma20_above_sma50": plus_sma20_above_sma50,
        "fvg_plus_rs_sma50_above_sma200": plus_sma50_above_sma200,
        "fvg_plus_rs_full_stack": plus_full_stack,
        "fvg_plus_rs_trend": plus_trend,
        "fvg_plus_rs_trend_volume": plus_volume,
    }


def _relative_strength_frame(frame: pd.DataFrame, benchmark_frame: pd.DataFrame | None) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    result["relative_strength_20d"] = 0.0
    result["relative_strength_60d"] = 0.0
    if benchmark_frame is None or benchmark_frame.empty:
        return result

    benchmark = _normalize_frame(benchmark_frame)[["date", "close"]].rename(columns={"close": "benchmark_close"})
    merged = frame[["date", "close"]].merge(benchmark, on="date", how="left").ffill()

    for bars in (20, 60):
        stock_ret = (merged["close"] / merged["close"].shift(bars)) - 1.0
        bench_ret = (merged["benchmark_close"] / merged["benchmark_close"].shift(bars)) - 1.0
        result[f"relative_strength_{bars}d"] = (stock_ret - bench_ret).fillna(0.0)
    return result


def _build_regime_series(benchmark_frame: pd.DataFrame | None) -> pd.Series:
    if benchmark_frame is None or benchmark_frame.empty:
        return pd.Series(dtype="object")

    benchmark = _normalize_frame(benchmark_frame).copy()
    close = benchmark["close"]
    sma50 = close.rolling(50, min_periods=1).mean()
    sma200 = close.rolling(200, min_periods=1).mean()
    atr = _atr(benchmark, period=14)
    atr_pct = _safe_div(atr, close.replace(0.0, pd.NA)).fillna(0.0)

    labels: list[str] = []
    for idx in range(len(benchmark)):
        recent_high_vol = float(atr_pct.iloc[max(0, idx - 2): idx + 1].max())
        if recent_high_vol >= 0.03:
            labels.append("high_vol")
        elif float(close.iloc[idx]) < float(sma200.iloc[idx]) and float(sma50.iloc[idx]) <= float(sma200.iloc[idx]):
            labels.append("bear")
        else:
            labels.append("bull")
    return pd.Series(labels, index=benchmark.index)


def _gap_persistence_days(frame: pd.DataFrame) -> pd.Series:
    persistence = [0] * len(frame)
    closes = frame["close"].tolist()
    midpoints = frame["fvg_midpoint"].tolist()
    bullish = frame["bullish_fvg_present"].tolist()
    for index in range(len(frame)):
        midpoint = midpoints[index]
        if not bullish[index] or midpoint is None or (isinstance(midpoint, float) and math.isnan(midpoint)):
            continue
        count = 0
        for prior in range(index, -1, -1):
            if float(closes[prior]) >= float(midpoint):
                count += 1
            else:
                break
        persistence[index] = count
    return pd.Series(persistence, index=frame.index)


def _snapshot_from_feature_row(row: pd.Series) -> Dict[str, Any]:
    return {
        "bullish_fvg_present": bool(row.get("bullish_fvg_present", False)),
        "fvg_size": float(row.get("bull_gap_size", 0.0) or 0.0),
        "fvg_size_atr": float(row.get("fvg_size_atr", 0.0) or 0.0),
        "fvg_midpoint": row.get("fvg_midpoint"),
        "same_direction_fvg_count_10d": int(row.get("same_direction_fvg_count_10d", 0) or 0),
        "alternating_gap_count_10d": int(row.get("alternating_gap_count_10d", 0) or 0),
        "gap_persistence_days": int(row.get("gap_persistence_days", 0) or 0),
        "price_above_gap_midpoint": bool(row.get("price_above_gap_midpoint", False)),
        "relative_strength_20d": float(row.get("relative_strength_20d", 0.0) or 0.0),
        "relative_strength_60d": float(row.get("relative_strength_60d", 0.0) or 0.0),
        "volume_zscore_20d": float(row.get("volume_zscore_20d", 0.0) or 0.0),
        "distance_to_52w_high": float(row.get("distance_to_52w_high", 1.0) or 1.0),
        "price_above_sma20": bool(row.get("price_above_sma20", False)),
        "sma20_above_sma50": bool(row.get("sma20_above_sma50", False)),
        "sma50_above_sma200": bool(row.get("sma50_above_sma200", False)),
        "trend_alignment_20_50_200": float(row.get("trend_alignment_20_50_200", 50.0) or 50.0),
    }


def _slice_benchmark(benchmark_frame: pd.DataFrame | None, current_date: pd.Timestamp) -> pd.DataFrame | None:
    if benchmark_frame is None or benchmark_frame.empty:
        return None
    bench = _normalize_frame(benchmark_frame)
    return bench[bench["date"] <= current_date].reset_index(drop=True)


def _forward_return_fields(close: pd.Series, index: int) -> Dict[str, Any]:
    return {
        "forward_return_5d": _forward_return(close, index=index, bars=5),
        "forward_return_20d": _forward_return(close, index=index, bars=20),
        "forward_return_30d": _forward_return(close, index=index, bars=30),
        "forward_return_60d": _forward_return(close, index=index, bars=60),
        "forward_return_90d": _forward_return(close, index=index, bars=90),
    }


def _forward_return(close: pd.Series, index: int, bars: int) -> float | None:
    target = index + bars
    if target >= len(close):
        return None
    start_price = float(close.iloc[index])
    end_price = float(close.iloc[target])
    if start_price <= 0.0:
        return None
    return float((end_price / start_price) - 1.0)


def _summarize_forward_returns(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {"event_count": len(rows)}
    for horizon in (5, 20, 30, 60, 90):
        key = f"forward_return_{horizon}d"
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        summary[f"mean_forward_return_{horizon}d"] = _mean_or_none(values)
        summary[f"median_forward_return_{horizon}d"] = _median_or_none(values)
        summary[f"hit_rate_{horizon}d"] = _mean_or_none([1.0 if value > 0 else 0.0 for value in values]) if values else None
    return summary


def _summarize_rows_by_key(rows: Sequence[Dict[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[str, list[Dict[str, Any]]] = {}
    for row in rows:
        label = str(row.get(key, "unknown"))
        buckets.setdefault(label, []).append(dict(row))
    return {label: _summarize_forward_returns(bucket) for label, bucket in sorted(buckets.items())}


def _summarize_rows_by_era(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[str, list[Dict[str, Any]]] = {}
    for row in rows:
        label = market_era_label(str(row.get("event_date", row.get("date", ""))))
        buckets.setdefault(label, []).append(dict(row))
    return {label: _summarize_forward_returns(bucket) for label, bucket in sorted(buckets.items())}


def _summarize_rows_by_slices(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    for slice_name in SLICE_NAMES:
        bucket = [dict(row) for row in rows if bool(row.get(slice_name, False))]
        summary[slice_name] = _summarize_forward_returns(bucket)
    return summary


def _summarize_daily_baskets(
    rows: Sequence[Dict[str, Any]],
    top_n: int,
    benchmark_frame: pd.DataFrame | None = None,
) -> Dict[str, Any]:
    grouped: Dict[str, list[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["date"]), []).append(dict(row))
    benchmark_returns = _benchmark_forward_return_map(benchmark_frame)

    basket_rows: list[Dict[str, Any]] = []
    for as_of_date, bucket in grouped.items():
        ranked = sorted(bucket, key=lambda row: (-float(row.get("score", 0.0)), str(row.get("ticker", ""))))[:top_n]
        benchmark_row = benchmark_returns.get(as_of_date, {})
        avg_forward_return_5d = _mean_or_none([row["forward_return_5d"] for row in ranked if row.get("forward_return_5d") is not None])
        avg_forward_return_20d = _mean_or_none([row["forward_return_20d"] for row in ranked if row.get("forward_return_20d") is not None])
        avg_forward_return_30d = _mean_or_none([row["forward_return_30d"] for row in ranked if row.get("forward_return_30d") is not None])
        avg_forward_return_60d = _mean_or_none([row["forward_return_60d"] for row in ranked if row.get("forward_return_60d") is not None])
        avg_forward_return_90d = _mean_or_none([row["forward_return_90d"] for row in ranked if row.get("forward_return_90d") is not None])
        basket_rows.append(
            {
                "date": as_of_date,
                "tickers": [row["ticker"] for row in ranked],
                "avg_forward_return_5d": avg_forward_return_5d,
                "avg_forward_return_20d": avg_forward_return_20d,
                "avg_forward_return_30d": avg_forward_return_30d,
                "avg_forward_return_60d": avg_forward_return_60d,
                "avg_forward_return_90d": avg_forward_return_90d,
                "benchmark_forward_return_5d": benchmark_row.get("forward_return_5d"),
                "benchmark_forward_return_20d": benchmark_row.get("forward_return_20d"),
                "benchmark_forward_return_30d": benchmark_row.get("forward_return_30d"),
                "benchmark_forward_return_60d": benchmark_row.get("forward_return_60d"),
                "benchmark_forward_return_90d": benchmark_row.get("forward_return_90d"),
                "avg_edge_vs_benchmark_5d": _subtract_or_none(avg_forward_return_5d, benchmark_row.get("forward_return_5d")),
                "avg_edge_vs_benchmark_20d": _subtract_or_none(avg_forward_return_20d, benchmark_row.get("forward_return_20d")),
                "avg_edge_vs_benchmark_30d": _subtract_or_none(avg_forward_return_30d, benchmark_row.get("forward_return_30d")),
                "avg_edge_vs_benchmark_60d": _subtract_or_none(avg_forward_return_60d, benchmark_row.get("forward_return_60d")),
                "avg_edge_vs_benchmark_90d": _subtract_or_none(avg_forward_return_90d, benchmark_row.get("forward_return_90d")),
            }
        )

    summary = {
        "top_n": int(top_n),
        "sample_days": len(basket_rows),
    }
    for horizon in (5, 20, 30, 60, 90):
        return_key = f"avg_forward_return_{horizon}d"
        edge_key = f"avg_edge_vs_benchmark_{horizon}d"
        benchmark_key = f"benchmark_forward_return_{horizon}d"
        return_values = [float(row[return_key]) for row in basket_rows if row.get(return_key) is not None]
        edge_values = [float(row[edge_key]) for row in basket_rows if row.get(edge_key) is not None]
        benchmark_values = [float(row[benchmark_key]) for row in basket_rows if row.get(benchmark_key) is not None]
        summary[return_key] = _mean_or_none(return_values)
        summary[benchmark_key] = _mean_or_none(benchmark_values)
        summary[edge_key] = _mean_or_none(edge_values)
    return summary


def _summarize_daily_baskets_by_slices(
    rows: Sequence[Dict[str, Any]],
    top_n: int,
    benchmark_frame: pd.DataFrame | None = None,
) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    for slice_name in SLICE_NAMES:
        bucket = [dict(row) for row in rows if bool(row.get(slice_name, False))]
        summary[slice_name] = _summarize_daily_baskets(bucket, top_n=top_n, benchmark_frame=benchmark_frame)
    return summary


def _benchmark_forward_return_map(benchmark_frame: pd.DataFrame | None) -> Dict[str, Dict[str, float | None]]:
    if benchmark_frame is None or benchmark_frame.empty:
        return {}
    bench = _normalize_frame(benchmark_frame)
    result: Dict[str, Dict[str, float | None]] = {}
    for index, row in bench.iterrows():
        as_of_date = pd.to_datetime(row["date"]).date().isoformat()
        result[as_of_date] = _forward_return_fields(bench["close"], index=index)
    return result


def _rank_tickers(rows: Sequence[Dict[str, Any]]) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    grouped: Dict[str, list[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["ticker"]), []).append(dict(row))

    ranked: list[Dict[str, Any]] = []
    for ticker, bucket in grouped.items():
        returns_20d = [float(row["forward_return_20d"]) for row in bucket if row.get("forward_return_20d") is not None]
        returns_60d = [float(row["forward_return_60d"]) for row in bucket if row.get("forward_return_60d") is not None]
        ranked.append(
            {
                "ticker": ticker,
                "event_count": len(bucket),
                "mean_forward_return_20d": _mean_or_none(returns_20d),
                "mean_forward_return_60d": _mean_or_none(returns_60d),
            }
        )
    ranked.sort(
        key=lambda row: (
            float(row.get("mean_forward_return_60d") if row.get("mean_forward_return_60d") is not None else -999.0),
            float(row.get("mean_forward_return_20d") if row.get("mean_forward_return_20d") is not None else -999.0),
        ),
        reverse=True,
    )
    return ranked[:5], list(reversed(ranked[-5:])) if ranked else []


def _serialize_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    serialized = dict(snapshot)
    for key, value in list(serialized.items()):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            serialized[key] = None
    return serialized


def _mean_or_none(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def _max_drawdown(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    peak = float(values[0])
    max_drawdown = 0.0
    for value in values:
        current = float(value)
        peak = max(peak, current)
        if peak <= 0.0:
            continue
        drawdown = (current / peak) - 1.0
        max_drawdown = min(max_drawdown, drawdown)
    return float(max_drawdown)


def _buy_and_hold_strategy_summary(frame: pd.DataFrame) -> Dict[str, Any]:
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if close.empty:
        return {
            "total_return": 0.0,
            "max_drawdown": 0.0,
        }
    start_price = float(close.iloc[0])
    end_price = float(close.iloc[-1])
    total_return = 0.0 if start_price <= 0.0 else float((end_price / start_price) - 1.0)
    return {
        "total_return": total_return,
        "max_drawdown": _max_drawdown(close.tolist()),
    }


def _subtract_or_none(lhs: float | None, rhs: float | None) -> float | None:
    if lhs is None or rhs is None:
        return None
    return float(lhs - rhs)


def _median_or_none(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)
