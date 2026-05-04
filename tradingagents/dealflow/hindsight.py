"""Deal Flow Hindsight Tracker.

Computes 5-day forward returns for ALL tickers sourced by the deal flow pipeline,
segmented by cohort (DEPLOYED, ANALYZED, QUEUED, FILTERED). Measures whether the
scoring/filtering algorithm left alpha on the table.
"""

from __future__ import annotations

import datetime
import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yfinance as yf
from scipy import stats

from .discovery_delta import build_discovery_delta_cohort_scorecards
from .evidence_integrity import build_evidence_integrity_scorecards
from .hypothesis_ledger import enrich_ledger_rows, summarize_ledger_rows

_DEAL_FLOW_DIR = Path("eval_results/deal_flow")
_PLANS_DIR = Path("eval_results/paper_execution/plans")
_HINDSIGHT_DB = _DEAL_FLOW_DIR / "hindsight.db"


def _get_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Open (or create) the hindsight SQLite database, ensuring schema exists."""
    path = db_path or _HINDSIGHT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS hindsight_cycles (
            source_date      TEXT PRIMARY KEY,
            eval_date        TEXT NOT NULL,
            benchmark        TEXT NOT NULL DEFAULT 'QQQ',
            benchmark_return REAL,
            deployed_n       INT,  deployed_mean  REAL,  deployed_edge  REAL,
            analyzed_n       INT,  analyzed_mean  REAL,  analyzed_edge  REAL,
            queued_n         INT,  queued_mean    REAL,  queued_edge    REAL,
            filtered_n       INT,  filtered_mean  REAL,  filtered_edge  REAL,
            ic_core          REAL,
            ic_momentum      REAL,
            ic_triage        REAL,
            missed_count     INT,
            created_at       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS hindsight_misses (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source_date  TEXT NOT NULL,
            ticker       TEXT NOT NULL,
            return_5d    REAL,
            edge         REAL,
            core_score   REAL,
            UNIQUE(source_date, ticker)
        );
    """)
    conn.commit()
    return conn


def _persist_to_db(result: dict, db_path: Path | None = None) -> None:
    """Write a completed hindsight result into the aggregate SQLite database."""
    def _cohort(name: str) -> tuple:
        c = result.get("cohorts", {}).get(name, {})
        return (
            int(c.get("count") or 0),
            c.get("mean_return"),
            c.get("edge_vs_benchmark"),
        )

    ic = result.get("rank_ic", {})
    missed = result.get("missed_opportunities", [])

    conn = _get_db(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO hindsight_cycles VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                result["source_date"],
                result["eval_date"],
                result.get("benchmark", "QQQ"),
                result.get("benchmark_return_5d"),
                *_cohort("DEPLOYED"),
                *_cohort("ANALYZED"),
                *_cohort("QUEUED"),
                *_cohort("FILTERED"),
                ic.get("core_score"),
                ic.get("momentum_score"),
                ic.get("triage_score"),
                len(missed),
                datetime.datetime.utcnow().isoformat(),
            ),
        )
        for m in missed:
            conn.execute(
                """INSERT OR IGNORE INTO hindsight_misses
                   (source_date, ticker, return_5d, edge, core_score) VALUES (?,?,?,?,?)""",
                (result["source_date"], m["ticker"], m.get("return_5d"), m.get("edge"), m.get("core_score")),
            )
        conn.commit()
    finally:
        conn.close()


def _load_json(path: Path) -> Any:
    with open(path) as f:
        return json.load(f)


def _trading_days(source_date: str, n: int) -> tuple[str, str]:
    """Return (T+0, T+n) trading-day dates using pandas market calendar."""
    start = pd.Timestamp(source_date)
    # Generate enough business days to cover holidays
    bdays = pd.bdate_range(start, periods=n + 5)
    # T+0 is first business day >= source_date
    t0 = bdays[0]
    if len(bdays) < n + 1:
        return str(t0.date()), ""
    tn = bdays[n]
    return str(t0.date()), str(tn.date())


def _deployed_tickers(source_date: str) -> set[str]:
    """Find tickers from portfolio plan orders for the given date."""
    plans_dir = _PLANS_DIR / source_date
    if not plans_dir.is_dir():
        return set()
    plan_files = sorted(plans_dir.glob("portfolio_plan_*.json"))
    if not plan_files:
        return set()
    # Use the latest plan file
    try:
        plan = _load_json(plan_files[-1])
    except Exception:
        return set()
    tickers = set()
    for order in plan.get("orders", []):
        sym = str(order.get("symbol", "")).strip().upper()
        if sym:
            tickers.add(sym)
    return tickers


def _spearman_ic(scores: List[float], returns: List[float]) -> Optional[float]:
    """Spearman rank correlation. Returns None if insufficient data."""
    if len(scores) < 5:
        return None
    # Filter out NaN pairs
    pairs = [(s, r) for s, r in zip(scores, returns) if math.isfinite(s) and math.isfinite(r)]
    if len(pairs) < 5:
        return None
    s_vals, r_vals = zip(*pairs)
    corr, _ = stats.spearmanr(s_vals, r_vals)
    if math.isnan(corr):
        return None
    return round(corr, 4)


def _spearman_ic_with_tstat(
    scores: List[float], returns: List[float]
) -> tuple[Optional[float], Optional[float], int]:
    """Spearman IC with t-statistic. Returns (ic, t_stat, n)."""
    pairs = [
        (s, r)
        for s, r in zip(scores, returns)
        if math.isfinite(s) and math.isfinite(r)
    ]
    n = len(pairs)
    if n < 5:
        return None, None, n
    s_vals, r_vals = zip(*pairs)
    corr, _ = stats.spearmanr(s_vals, r_vals)
    if math.isnan(corr):
        return None, None, n
    ic = round(corr, 4)
    # t = ic * sqrt((n-2) / (1 - ic^2))
    denom = 1.0 - corr * corr
    t_stat = round(corr * math.sqrt((n - 2) / denom), 2) if denom > 0 else None
    return ic, t_stat, n


def compute_hindsight(source_date: str, benchmark: str = "QQQ", db_path: Path | None = None) -> dict:
    """Compute 5-day forward returns for all deal-flow tickers, segmented by cohort.

    Args:
        source_date: Deal flow run date (YYYY-MM-DD).
        benchmark: Benchmark ticker for relative comparison.

    Returns:
        Hindsight result dict with cohort stats, rank IC, missed opportunities.
    """
    base = _DEAL_FLOW_DIR / source_date

    # --- 1. Load artifacts ---
    signals_raw: list = _load_json(base / "signals_raw.json")
    research_queue: dict = _load_json(base / "research_queue.json")
    discovery_delta: dict = _load_json(base / "discovery_delta.json") if (base / "discovery_delta.json").exists() else {}
    evidence_integrity: dict = _load_json(base / "evidence_integrity.json") if (base / "evidence_integrity.json").exists() else {}

    batch_path = base / "batch_analyze_latest.json"
    batch_data: dict = _load_json(batch_path) if batch_path.exists() else {"items": []}

    # --- 2. Build ticker registries ---
    # All tickers from signals_raw
    signal_tickers: Dict[str, Dict[str, Any]] = {}
    for sig in signals_raw:
        sym = str(sig.get("symbol", "")).strip().upper()
        if not sym:
            continue
        if sym not in signal_tickers:
            signal_tickers[sym] = {"families": set(), "raw_scores": []}
        signal_tickers[sym]["families"].add(str(sig.get("signal_family", "")))
        signal_tickers[sym]["raw_scores"].append(float(sig.get("raw_score", 0.0)))

    # Research queue items keyed by symbol
    queue_items: Dict[str, dict] = {}
    for item in research_queue.get("items", []):
        sym = str(item.get("symbol", "")).strip().upper()
        if sym:
            queue_items[sym] = item

    # Batch analyzed items keyed by symbol
    analyzed_items: Dict[str, dict] = {}
    for item in batch_data.get("items", []):
        sym = str(item.get("symbol", "")).strip().upper()
        if sym and str(item.get("status", "")).upper() == "SUCCESS":
            analyzed_items[sym] = item

    deployed = _deployed_tickers(source_date)

    # --- 3. Assign cohorts ---
    all_tickers = set(signal_tickers.keys())
    ticker_cohort: Dict[str, str] = {}
    for sym in all_tickers:
        if sym in deployed:
            ticker_cohort[sym] = "DEPLOYED"
        elif sym in analyzed_items:
            ticker_cohort[sym] = "ANALYZED"
        elif sym in queue_items and not bool(queue_items[sym].get("selected_for_deep")):
            ticker_cohort[sym] = "QUEUED"
        elif sym in queue_items and bool(queue_items[sym].get("selected_for_deep")):
            # Selected for deep but not in analyzed = treat as ANALYZED (attempted)
            ticker_cohort[sym] = "ANALYZED"
        elif sym in signal_tickers and len(signal_tickers[sym]["families"]) <= 1:
            ticker_cohort[sym] = "LOW_DATA"
        else:
            ticker_cohort[sym] = "FILTERED"

    # --- 4. Date range ---
    t0_str, t5_str = _trading_days(source_date, 5)
    if not t5_str:
        return {
            "source_date": source_date,
            "eval_date": "",
            "benchmark": benchmark,
            "error": "Could not compute T+5 date",
        }

    # --- 5. Fetch prices ---
    fetch_tickers = sorted(all_tickers | {benchmark})
    # Extend range by 1 day to ensure we capture T+5 close
    end_fetch = str((pd.Timestamp(t5_str) + pd.Timedelta(days=3)).date())
    try:
        prices = yf.download(
            fetch_tickers,
            start=t0_str,
            end=end_fetch,
            progress=False,
            auto_adjust=True,
        )
    except Exception:
        prices = pd.DataFrame()

    if prices.empty:
        return {
            "source_date": source_date,
            "eval_date": t5_str,
            "benchmark": benchmark,
            "error": "No price data returned from yfinance",
        }

    # Extract close prices — handle single vs multi-ticker DataFrame
    if isinstance(prices.columns, pd.MultiIndex):
        close = prices["Close"] if "Close" in prices.columns.get_level_values(0) else prices
    else:
        close = prices[["Close"]] if "Close" in prices.columns else prices
        if len(fetch_tickers) == 1:
            close.columns = fetch_tickers

    # Find actual trading dates closest to T+0 and T+5
    trading_dates = close.index.sort_values()
    t0_ts = pd.Timestamp(t0_str)
    t5_ts = pd.Timestamp(t5_str)

    t0_actual = trading_dates[trading_dates >= t0_ts]
    t5_actual = trading_dates[trading_dates >= t5_ts]

    if len(t0_actual) == 0 or len(t5_actual) == 0:
        return {
            "source_date": source_date,
            "eval_date": t5_str,
            "benchmark": benchmark,
            "error": f"Insufficient trading days in price data (t0={t0_str}, t5={t5_str})",
        }

    t0_date = t0_actual[0]
    t5_date = t5_actual[0]

    # --- 6. Compute returns ---
    def _get_return(ticker: str) -> Optional[float]:
        try:
            p0 = float(close.loc[t0_date, ticker])
            p5 = float(close.loc[t5_date, ticker])
            if p0 <= 0 or math.isnan(p0) or math.isnan(p5):
                return None
            return round((p5 / p0) - 1.0, 6)
        except Exception:
            return None

    benchmark_return = _get_return(benchmark)

    ticker_returns: List[dict] = []
    for sym in sorted(all_tickers):
        ret = _get_return(sym)
        cohort = ticker_cohort.get(sym, "FILTERED")
        q_item = queue_items.get(sym, {})
        a_item = analyzed_items.get(sym, {})
        entry = {
            "ticker": sym,
            "cohort": cohort,
            "return_5d": ret,
            "core_score": round(float(q_item.get("deal_flow_score", 0.0)), 2) if q_item else None,
            "momentum_score": round(float(q_item.get("momentum_score", 0.0)), 2) if q_item else None,
            "triage_score": round(float(q_item.get("triage_score", 0.0)), 2) if q_item else None,
            "aeternus_score": round(float(a_item.get("aeternus_score") or 0.0), 2) if a_item else None,
        }
        ticker_returns.append(entry)

    # --- 7. Cohort stats ---
    cohorts_result: Dict[str, dict] = {}
    for cohort_name in ["DEPLOYED", "ANALYZED", "QUEUED", "FILTERED", "LOW_DATA"]:
        members = [t for t in ticker_returns if t["cohort"] == cohort_name and t["return_5d"] is not None]
        if not members:
            cohorts_result[cohort_name] = {"count": 0, "mean_return": None, "median_return": None, "edge_vs_benchmark": None}
            continue
        rets = [t["return_5d"] for t in members]
        mean_r = round(sum(rets) / len(rets), 6)
        sorted_rets = sorted(rets)
        mid = len(sorted_rets) // 2
        median_r = round(sorted_rets[mid] if len(sorted_rets) % 2 else (sorted_rets[mid - 1] + sorted_rets[mid]) / 2, 6)
        edge = round(mean_r - benchmark_return, 6) if benchmark_return is not None else None
        cohorts_result[cohort_name] = {
            "count": len(members),
            "mean_return": mean_r,
            "median_return": median_r,
            "edge_vs_benchmark": edge,
        }

    # --- 8. Rank IC ---
    scored = [t for t in ticker_returns if t["return_5d"] is not None]
    core_scores = [t["core_score"] for t in scored if t["core_score"] is not None]
    core_rets = [t["return_5d"] for t in scored if t["core_score"] is not None]
    mom_scores = [t["momentum_score"] for t in scored if t["momentum_score"] is not None]
    mom_rets = [t["return_5d"] for t in scored if t["momentum_score"] is not None]
    tri_scores = [t["triage_score"] for t in scored if t["triage_score"] is not None]
    tri_rets = [t["return_5d"] for t in scored if t["triage_score"] is not None]

    rank_ic = {
        "core_score": _spearman_ic(core_scores, core_rets),
        "momentum_score": _spearman_ic(mom_scores, mom_rets),
        "triage_score": _spearman_ic(tri_scores, tri_rets),
    }

    # --- 9. Missed opportunities ---
    threshold = 0.02  # 2% edge over benchmark
    missed: List[dict] = []
    if benchmark_return is not None:
        for t in ticker_returns:
            if t["cohort"] == "FILTERED" and t["return_5d"] is not None:
                edge = t["return_5d"] - benchmark_return
                if edge > threshold:
                    missed.append({
                        "ticker": t["ticker"],
                        "cohort": t["cohort"],
                        "return_5d": t["return_5d"],
                        "edge": round(edge, 6),
                        "core_score": t["core_score"],
                    })
    missed.sort(key=lambda m: -(m.get("edge") or 0))

    # --- 10. Assemble, enrich, and persist ---
    result = {
        "source_date": source_date,
        "eval_date": str(t5_date.date()),
        "benchmark": benchmark,
        "benchmark_return_5d": benchmark_return,
        "cohorts": cohorts_result,
        "rank_ic": rank_ic,
        "missed_opportunities": missed,
        "ticker_returns": ticker_returns,
    }
    result["discovery_delta_cohorts"] = build_discovery_delta_cohort_scorecards(
        discovery_delta=discovery_delta,
        step1_symbols=sorted(all_tickers),
        shortlist_symbols=sorted(queue_items.keys()),
        deep_selection_symbols=[
            sym
            for sym, item in queue_items.items()
            if bool(item.get("selected_for_deep"))
        ],
        forward_returns_by_horizon={
            "5d": {
                str(entry.get("ticker", "")).upper().strip(): float(entry["return_5d"])
                for entry in ticker_returns
                if entry.get("return_5d") is not None
            }
        },
        benchmark_returns_by_horizon={"5d": benchmark_return},
    )
    result["evidence_integrity_cohorts"] = build_evidence_integrity_scorecards(
        evidence_integrity=evidence_integrity,
        step2_symbols=sorted(all_tickers),
        shortlist_symbols=sorted(queue_items.keys()),
        deep_selection_symbols=[
            sym
            for sym, item in queue_items.items()
            if bool(item.get("selected_for_deep"))
        ],
        forward_returns_by_horizon={
            "5d": {
                str(entry.get("ticker", "")).upper().strip(): float(entry["return_5d"])
                for entry in ticker_returns
                if entry.get("return_5d") is not None
            }
        },
        benchmark_returns_by_horizon={"5d": benchmark_return},
    )

    enrich_ledger_rows(
        base_dir=base,
        lane="shared",
        forward_returns_by_horizon={
            "5d": {
                str(entry.get("ticker", "")).upper().strip(): float(entry["return_5d"])
                for entry in ticker_returns
                if entry.get("return_5d") is not None
            }
        },
        winner_horizon="5d",
    )
    result["hypothesis_stage_summary"] = summarize_ledger_rows(base_dir=base, lane="shared")

    out_path = base / "hindsight.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    result["output_path"] = str(out_path)

    # Persist to aggregate SQLite database
    _persist_to_db(result, db_path)

    return result
