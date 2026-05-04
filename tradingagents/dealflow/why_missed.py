"""Recent-run audit for "why didn't we pick this stock?" questions."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import pandas as pd
import yfinance as yf

from .hindsight import _trading_days

_DEAL_FLOW_DIR = Path("eval_results/deal_flow")
_X_FEED_DIR = Path("eval_results/x_feed")
_PLANS_DIR = Path("eval_results/paper_execution/plans")
_MAX_LOOKBACK_RUNS = 5
_REVIEW_EDGE_THRESHOLD = 0.01
_STAGE_ORDER = {
    "universe_gate_edge": 0,
    "universe_gate_haystack": 1,
    "evidence_gate": 2,
    "shortlist_cut": 3,
    "deep_selection_cut": 4,
    "portfolio_inclusion_cut": 5,
}


def _load_json(path: Path) -> Any:
    with open(path) as handle:
        return json.load(handle)


def _normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _iter_dated_dirs(base_dir: Path) -> Iterable[Path]:
    if not base_dir.is_dir():
        return []
    return (
        path
        for path in base_dir.iterdir()
        if path.is_dir() and len(path.name) == 10 and path.name.count("-") == 2
    )


def _recent_source_dates(*roots: Path, last: int) -> List[str]:
    dates: Set[str] = set()
    for root in roots:
        for path in _iter_dated_dirs(root):
            dates.add(path.name)
    capped = max(1, min(int(last or _MAX_LOOKBACK_RUNS), _MAX_LOOKBACK_RUNS))
    return sorted(dates, reverse=True)[:capped]


def _load_x_feed_symbols(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    try:
        payload = _load_json(path)
    except Exception:
        return set()
    if isinstance(payload, dict):
        return {_normalize_symbol(key) for key in payload.keys()}
    if isinstance(payload, list):
        return {
            _normalize_symbol(row.get("ticker") or row.get("symbol"))
            for row in payload
            if isinstance(row, dict)
        }
    return set()


def _load_signal_symbols(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    try:
        payload = _load_json(path)
    except Exception:
        return set()
    if not isinstance(payload, list):
        return set()
    return {
        _normalize_symbol(row.get("symbol") or row.get("ticker"))
        for row in payload
        if isinstance(row, dict)
    }


def _load_scored_rows(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = _load_json(path)
    except Exception:
        return {}
    if not isinstance(payload, list):
        return {}
    rows: Dict[str, Dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        symbol = _normalize_symbol(row.get("symbol") or row.get("ticker"))
        if symbol:
            rows[symbol] = row
    return rows


def _load_queue_rows(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = _load_json(path)
    except Exception:
        return {}
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return {}
    rows: Dict[str, Dict[str, Any]] = {}
    for row in items:
        if not isinstance(row, dict):
            continue
        symbol = _normalize_symbol(row.get("symbol") or row.get("ticker"))
        if symbol:
            rows[symbol] = row
    return rows


def _load_batch_rows(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = _load_json(path)
    except Exception:
        return {}
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return {}
    rows: Dict[str, Dict[str, Any]] = {}
    for row in items:
        if not isinstance(row, dict):
            continue
        symbol = _normalize_symbol(row.get("symbol") or row.get("ticker"))
        if symbol:
            rows[symbol] = row
    return rows


def _latest_plan_symbols(plans_dir: Path) -> Set[str]:
    if not plans_dir.is_dir():
        return set()
    plan_files = sorted(plans_dir.glob("portfolio_plan_*.json"))
    if not plan_files:
        return set()
    try:
        payload = _load_json(plan_files[-1])
    except Exception:
        return set()
    orders = payload.get("orders", []) if isinstance(payload, dict) else []
    if not isinstance(orders, list):
        return set()
    return {
        _normalize_symbol(row.get("symbol") or row.get("ticker"))
        for row in orders
        if isinstance(row, dict)
    }


def _is_success_status(status: Any) -> bool:
    value = str(status or "").strip().upper()
    return value.startswith("SUCCESS")


def _coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_snapshot_symbols(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    try:
        payload = _load_json(path)
    except Exception:
        return set()
    if not isinstance(payload, list):
        return set()
    return {_normalize_symbol(value) for value in payload if _normalize_symbol(value)}


def _stage_drops(base_dir: Path, symbol: str) -> List[Dict[str, Any]]:
    root = Path(base_dir) / "hypothesis_ledger"
    if not root.is_dir():
        return []
    drops: List[Dict[str, Any]] = []
    for lane_dir in root.iterdir():
        if not lane_dir.is_dir():
            continue
        rows_path = lane_dir / "rows.json"
        if not rows_path.exists():
            continue
        try:
            rows = _load_json(rows_path)
        except Exception:
            continue
        if not isinstance(rows, list):
            continue
        for raw_row in rows:
            if not isinstance(raw_row, dict):
                continue
            dropped_symbols = _load_snapshot_symbols(Path(raw_row.get("dropped_symbols_path", "")))
            if symbol not in dropped_symbols:
                continue
            stage_id = str(raw_row.get("stage_id", "")).strip()
            drops.append(
                {
                    "lane": str(lane_dir.name),
                    "stage_id": stage_id,
                    "rule_snapshot": dict(raw_row.get("rule_snapshot", {})),
                    "kept_count": int(raw_row.get("kept_count", 0) or 0),
                    "dropped_count": int(raw_row.get("dropped_count", 0) or 0),
                    "edge_5d": raw_row.get("edge_5d"),
                    "edge_20d": raw_row.get("edge_20d"),
                    "edge_3m": raw_row.get("edge_3m"),
                    "future_winner_recall": raw_row.get("future_winner_recall"),
                    "false_negative_cost": raw_row.get("false_negative_cost"),
                }
            )
    drops.sort(key=lambda row: (_STAGE_ORDER.get(str(row.get("stage_id", "")), 999), str(row.get("lane", ""))))
    return drops


def _forward_return_summary(symbol: str, source_date: str, benchmark: str = "QQQ") -> Dict[str, Any]:
    t0_str, t5_str = _trading_days(source_date, 5)
    if not t5_str:
        return {"eval_date": "", "return_5d": None, "benchmark_return_5d": None, "edge_vs_benchmark_5d": None, "status": "UNAVAILABLE"}

    if pd.Timestamp(t5_str) > pd.Timestamp.today().normalize():
        return {
            "eval_date": t5_str,
            "return_5d": None,
            "benchmark_return_5d": None,
            "edge_vs_benchmark_5d": None,
            "status": "PENDING",
        }

    end_fetch = str((pd.Timestamp(t5_str) + pd.Timedelta(days=3)).date())
    try:
        prices = yf.download(
            sorted({_normalize_symbol(symbol), _normalize_symbol(benchmark)}),
            start=t0_str,
            end=end_fetch,
            progress=False,
            auto_adjust=True,
        )
    except Exception:
        prices = pd.DataFrame()

    if prices.empty:
        return {
            "eval_date": t5_str,
            "return_5d": None,
            "benchmark_return_5d": None,
            "edge_vs_benchmark_5d": None,
            "status": "NO_PRICE_DATA",
        }

    if isinstance(prices.columns, pd.MultiIndex):
        close = prices["Close"] if "Close" in prices.columns.get_level_values(0) else prices
    else:
        close = prices[["Close"]] if "Close" in prices.columns else prices
        tickers = sorted({_normalize_symbol(symbol), _normalize_symbol(benchmark)})
        if len(tickers) == 1:
            close.columns = tickers

    trading_dates = close.index.sort_values()
    t0_actual = trading_dates[trading_dates >= pd.Timestamp(t0_str)]
    t5_actual = trading_dates[trading_dates >= pd.Timestamp(t5_str)]
    if len(t0_actual) == 0 or len(t5_actual) == 0:
        return {
            "eval_date": t5_str,
            "return_5d": None,
            "benchmark_return_5d": None,
            "edge_vs_benchmark_5d": None,
            "status": "INSUFFICIENT_TRADING_DAYS",
        }

    t0_date = t0_actual[0]
    t5_date = t5_actual[0]

    def _calc_return(ticker: str) -> Optional[float]:
        try:
            p0 = float(close.loc[t0_date, ticker])
            p5 = float(close.loc[t5_date, ticker])
            if p0 <= 0 or math.isnan(p0) or math.isnan(p5):
                return None
            return round((p5 / p0) - 1.0, 6)
        except Exception:
            return None

    symbol_ret = _calc_return(_normalize_symbol(symbol))
    benchmark_ret = _calc_return(_normalize_symbol(benchmark))
    edge = (
        round(float(symbol_ret) - float(benchmark_ret), 6)
        if symbol_ret is not None and benchmark_ret is not None
        else None
    )
    return {
        "eval_date": str(t5_date.date()),
        "return_5d": symbol_ret,
        "benchmark_return_5d": benchmark_ret,
        "edge_vs_benchmark_5d": edge,
        "status": "READY" if symbol_ret is not None else "NO_SYMBOL_DATA",
    }


def _improvement_target(root_cause: str, primary_stage_drop: Optional[str]) -> Optional[str]:
    if primary_stage_drop:
        return primary_stage_drop
    mapping = {
        "PIPELINE_NOT_RUN": "daily_run_completeness",
        "DISCOVERY_CUT": "discovery_sources",
        "SIGNAL_FILTER_CUT": "evidence_gate",
        "SHORTLIST_CUT": "shortlist_cut",
        "DEEP_SELECTION_CUT": "deep_selection_cut",
        "ANALYSIS_NOT_COMPLETED": "analysis_execution",
        "V3_HURDLE_REJECTED": "portfolio_inclusion_cut",
        "PORTFOLIO_CONSTRUCTION_CUT": "portfolio_inclusion_cut",
        "NOT_FLAGGED": "discovery_sources",
    }
    return mapping.get(str(root_cause or "").strip().upper())


def _review_reason(
    *,
    symbol: str,
    improvement_target: Optional[str],
    edge_vs_benchmark_5d: Optional[float],
    benchmark: str,
) -> Optional[str]:
    if not improvement_target or edge_vs_benchmark_5d is None:
        return None
    return (
        f"{improvement_target} dropped {symbol} before a "
        f"{edge_vs_benchmark_5d * 100:+.2f}% edge vs {benchmark}"
    )


def _highest_stage(row: Dict[str, Any]) -> str:
    if row["deployed"]:
        return "DEPLOYED"
    if row["analyzed_success"]:
        return "ANALYZED"
    if row["selected_for_deep"]:
        return "SELECTED"
    if row["queue_seen"]:
        return "QUEUED"
    if row["scored_seen"]:
        return "SCORED"
    if row["signals_seen"]:
        return "SIGNALED"
    if row["x_feed_seen"]:
        return "X_FEED"
    return "NOT_FLAGGED"


def _root_cause(row: Dict[str, Any]) -> str:
    if row["x_feed_seen"] and not row.get("dealflow_cycle_found", False):
        return "PIPELINE_NOT_RUN"
    if row["deployed"]:
        return "DEPLOYED"
    if row["analyzed_success"]:
        return "PORTFOLIO_CONSTRUCTION_CUT" if row["v3_hurdle_cleared"] else "V3_HURDLE_REJECTED"
    if row["selected_for_deep"]:
        return "ANALYSIS_NOT_COMPLETED"
    if row["queue_seen"]:
        return "DEEP_SELECTION_CUT"
    if row["scored_seen"]:
        return "SHORTLIST_CUT"
    if row["signals_seen"]:
        return "SIGNAL_FILTER_CUT"
    if row["x_feed_seen"]:
        return "DISCOVERY_CUT"
    return "NOT_FLAGGED"


def audit_ticker_run(
    ticker: str,
    source_date: str,
    *,
    base_dir: Path = _DEAL_FLOW_DIR,
    x_feed_base_dir: Path = _X_FEED_DIR,
    plans_base_dir: Path = _PLANS_DIR,
    hurdle: float = 62.0,
    benchmark: str = "QQQ",
    review_edge_threshold: float = _REVIEW_EDGE_THRESHOLD,
    include_forward_returns: bool = True,
) -> Dict[str, Any]:
    """Audit a single ticker on a single source date."""
    symbol = _normalize_symbol(ticker)
    cycle_dir = Path(base_dir) / source_date
    x_feed_symbols = _load_x_feed_symbols(Path(x_feed_base_dir) / source_date / "merged.json")
    signal_symbols = _load_signal_symbols(cycle_dir / "signals_raw.json")
    scored_rows = _load_scored_rows(cycle_dir / "all_scored_candidates.json")
    queue_rows = _load_queue_rows(cycle_dir / "research_queue.json")
    batch_rows = _load_batch_rows(cycle_dir / "batch_analyze_latest.json")
    deployed_symbols = _latest_plan_symbols(Path(plans_base_dir) / source_date)

    queue_row = queue_rows.get(symbol, {})
    batch_row = batch_rows.get(symbol, {})
    analyzed_score = _coerce_float(batch_row.get("aeternus_score"))
    stage_drops = _stage_drops(cycle_dir, symbol)
    if include_forward_returns:
        forward_summary = _forward_return_summary(symbol, source_date, benchmark=benchmark)
    else:
        forward_summary = {
            "eval_date": None,
            "status": "SKIPPED",
            "return_5d": None,
            "benchmark_return_5d": None,
            "edge_vs_benchmark_5d": None,
        }

    row: Dict[str, Any] = {
        "source_date": source_date,
        "dealflow_cycle_found": cycle_dir.is_dir(),
        "x_feed_seen": symbol in x_feed_symbols,
        "signals_seen": symbol in signal_symbols,
        "scored_seen": symbol in scored_rows,
        "queue_seen": symbol in queue_rows,
        "selected_for_deep": bool(queue_row.get("selected_for_deep", False)),
        "analyzed_success": _is_success_status(batch_row.get("status")),
        "deployed": symbol in deployed_symbols,
        "v3_hurdle_cleared": bool(analyzed_score is not None and analyzed_score >= float(hurdle)),
        "analysis_status": str(batch_row.get("status", "")),
        "aeternus_score": analyzed_score,
        "recommendation": batch_row.get("recommendation"),
        "rating": batch_row.get("rating"),
        "deal_flow_score": _coerce_float(queue_row.get("deal_flow_score")),
        "lane": queue_row.get("lane") or scored_rows.get(symbol, {}).get("lane"),
        "stage_drops": stage_drops,
        "primary_stage_drop": stage_drops[-1]["stage_id"] if stage_drops else None,
        "forward_eval_date": forward_summary.get("eval_date"),
        "forward_status": forward_summary.get("status"),
        "return_5d": forward_summary.get("return_5d"),
        "benchmark_return_5d": forward_summary.get("benchmark_return_5d"),
        "edge_vs_benchmark_5d": forward_summary.get("edge_vs_benchmark_5d"),
    }
    row["highest_stage"] = _highest_stage(row)
    row["root_cause"] = _root_cause(row)
    row["improvement_target"] = _improvement_target(row["root_cause"], row.get("primary_stage_drop"))
    row["review_recommended"] = bool(
        row.get("improvement_target")
        and row.get("edge_vs_benchmark_5d") is not None
        and float(row["edge_vs_benchmark_5d"]) >= float(review_edge_threshold)
    )
    row["review_reason"] = _review_reason(
        symbol=symbol,
        improvement_target=row.get("improvement_target"),
        edge_vs_benchmark_5d=row.get("edge_vs_benchmark_5d"),
        benchmark=benchmark,
    )
    return row


def compute_why_missed(
    ticker: str,
    last: int = _MAX_LOOKBACK_RUNS,
    *,
    base_dir: Path = _DEAL_FLOW_DIR,
    x_feed_base_dir: Path = _X_FEED_DIR,
    plans_base_dir: Path = _PLANS_DIR,
    hurdle: float = 62.0,
    benchmark: str = "QQQ",
    review_edge_threshold: float = _REVIEW_EDGE_THRESHOLD,
) -> Dict[str, Any]:
    """Audit the recent dealflow path for a ticker using at most 5 dated runs."""
    symbol = _normalize_symbol(ticker)
    source_dates = _recent_source_dates(base_dir, x_feed_base_dir, plans_base_dir, last=last)
    runs = [
        audit_ticker_run(
            symbol,
            source_date,
            base_dir=base_dir,
            x_feed_base_dir=x_feed_base_dir,
            plans_base_dir=plans_base_dir,
            hurdle=hurdle,
            benchmark=benchmark,
            review_edge_threshold=review_edge_threshold,
            include_forward_returns=True,
        )
        for source_date in source_dates
    ]

    flagged_run_count = sum(
        1
        for row in runs
        if row["x_feed_seen"]
        or row["signals_seen"]
        or row["scored_seen"]
        or row["queue_seen"]
        or row["analyzed_success"]
        or row["deployed"]
    )
    return {
        "ticker": symbol,
        "lookback_runs_requested": int(last),
        "lookback_runs_used": len(runs),
        "flagged_run_count": flagged_run_count,
        "ever_flagged": flagged_run_count > 0,
        "max_lookback_runs": _MAX_LOOKBACK_RUNS,
        "benchmark": benchmark,
        "review_edge_threshold": float(review_edge_threshold),
        "review_candidates": [
            {
                "source_date": row["source_date"],
                "improvement_target": row.get("improvement_target"),
                "edge_vs_benchmark_5d": row.get("edge_vs_benchmark_5d"),
                "review_reason": row.get("review_reason"),
            }
            for row in runs
            if row.get("review_recommended")
        ],
        "runs": runs,
    }
