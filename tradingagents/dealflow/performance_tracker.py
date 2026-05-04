"""Performance Intelligence — Funnel Report Card.

Measures whether each pipeline filter cut (scored → queued → analyzed → deployed)
added or destroyed alpha, and computes per-signal-family IC with t-statistics.
"""

from __future__ import annotations

import datetime
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yfinance as yf

from .discovery_delta import build_discovery_delta_cohort_scorecards
from .evidence_integrity import build_evidence_integrity_scorecards
from .hypothesis_ledger import enrich_ledger_rows, summarize_ledger_rows
from .hindsight import (
    _DEAL_FLOW_DIR,
    _HINDSIGHT_DB,
    _deployed_tickers,
    _load_json,
    _spearman_ic_with_tstat,
    _trading_days,
)

_RETURN_HORIZONS = (5, 20, 60)


def _get_db(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or _HINDSIGHT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS performance_cycles (
            source_date TEXT PRIMARY KEY, eval_date TEXT,
            benchmark_return_5d REAL, benchmark_return_20d REAL,
            scored_n INT, scored_mean_5d REAL, scored_mean_20d REAL, scored_edge_5d REAL,
            queued_n INT, queued_mean_5d REAL, queued_mean_20d REAL, queued_edge_5d REAL,
            filter_alpha_scored_queued_5d REAL,
            analyzed_n INT, analyzed_mean_5d REAL, analyzed_mean_20d REAL, analyzed_edge_5d REAL,
            filter_alpha_queued_analyzed_5d REAL,
            deployed_n INT, deployed_mean_5d REAL, deployed_mean_20d REAL, deployed_edge_5d REAL,
            filter_alpha_analyzed_deployed_5d REAL,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS signal_family_ic (
            source_date TEXT, signal_family TEXT,
            ic REAL, t_stat REAL, n INT,
            UNIQUE(source_date, signal_family)
        );
    """)
    conn.commit()
    return conn


def compute_performance_review(
    source_date: str,
    benchmark: str = "QQQ",
    db_path: Path | None = None,
) -> dict:
    """Compute funnel report card for a deal-flow cycle.

    Returns dict with per-stage stats, filter alpha, and signal family IC.
    """
    base = _DEAL_FLOW_DIR / source_date

    # --- 1. Load funnel artifacts ---
    signals_raw: list = _load_json(base / "signals_raw.json")
    discovery_delta: dict = _load_json(base / "discovery_delta.json") if (base / "discovery_delta.json").exists() else {}
    evidence_integrity: dict = _load_json(base / "evidence_integrity.json") if (base / "evidence_integrity.json").exists() else {}

    scored_path = base / "all_scored_candidates.json"
    scored_data: list = _load_json(scored_path) if scored_path.exists() else []

    queue_path = base / "research_queue.json"
    queue_data: dict = _load_json(queue_path) if queue_path.exists() else {"items": []}

    batch_path = base / "batch_analyze_latest.json"
    batch_data: dict = _load_json(batch_path) if batch_path.exists() else {"items": []}

    deployed = _deployed_tickers(source_date)

    # --- 2. Build ticker sets per stage ---
    step1_symbols = sorted(
        {
            str(item.get("symbol", "")).strip().upper()
            for item in signals_raw
            if str(item.get("symbol", "")).strip().upper()
        }
    )
    scored_syms: Dict[str, dict] = {}
    for item in scored_data:
        sym = str(item.get("symbol", "")).strip().upper()
        if sym and item.get("status") != "LOW_DATA":
            scored_syms[sym] = item

    queued_syms: set = set()
    for item in queue_data.get("items", []):
        sym = str(item.get("symbol", "")).strip().upper()
        if sym:
            queued_syms.add(sym)

    analyzed_syms: set = set()
    for item in batch_data.get("items", []):
        sym = str(item.get("symbol", "")).strip().upper()
        if sym and str(item.get("status", "")).upper() == "SUCCESS":
            analyzed_syms.add(sym)

    # Assign cohorts (highest stage wins)
    all_syms = set(scored_syms.keys())
    cohort_map: Dict[str, str] = {}
    for sym in all_syms:
        if sym in deployed:
            cohort_map[sym] = "DEPLOYED"
        elif sym in analyzed_syms:
            cohort_map[sym] = "ANALYZED"
        elif sym in queued_syms:
            cohort_map[sym] = "QUEUED"
        else:
            cohort_map[sym] = "SCORED"

    # --- 3. Fetch forward returns ---
    t0_5, t5 = _trading_days(source_date, 5)
    t0_20, t20 = _trading_days(source_date, 20)
    t0_60, t60 = _trading_days(source_date, 60)

    fetch_tickers = sorted(set(step1_symbols) | all_syms | {benchmark})
    end_candidates = [candidate for candidate in (t5, t20, t60) if candidate]
    end_date = max(end_candidates) if end_candidates else ""
    if not end_date:
        return {"source_date": source_date, "error": "Cannot compute trading day range"}

    end_fetch = str((pd.Timestamp(end_date) + pd.Timedelta(days=3)).date())
    try:
        prices = yf.download(fetch_tickers, start=t0_5, end=end_fetch, progress=False, auto_adjust=True)
    except Exception:
        prices = pd.DataFrame()

    if prices.empty:
        return {"source_date": source_date, "error": "No price data from yfinance"}

    # Extract close
    if isinstance(prices.columns, pd.MultiIndex):
        close = prices["Close"] if "Close" in prices.columns.get_level_values(0) else prices
    else:
        close = prices[["Close"]] if "Close" in prices.columns else prices
        if len(fetch_tickers) == 1:
            close.columns = fetch_tickers

    trading_dates = close.index.sort_values()

    def _return_at(ticker: str, t0_str: str, tn_str: str) -> Optional[float]:
        if not t0_str or not tn_str:
            return None
        try:
            t0_ts = pd.Timestamp(t0_str)
            tn_ts = pd.Timestamp(tn_str)
            t0_actual = trading_dates[trading_dates >= t0_ts]
            tn_actual = trading_dates[trading_dates >= tn_ts]
            if len(t0_actual) == 0 or len(tn_actual) == 0:
                return None
            p0 = float(close.loc[t0_actual[0], ticker])
            pn = float(close.loc[tn_actual[0], ticker])
            if p0 <= 0 or math.isnan(p0) or math.isnan(pn):
                return None
            return round((pn / p0) - 1.0, 6)
        except Exception:
            return None

    bm_5d = _return_at(benchmark, t0_5, t5)
    bm_20d = _return_at(benchmark, t0_20, t20)
    bm_3m = _return_at(benchmark, t0_60, t60)

    # Per-ticker returns
    ticker_data: List[dict] = []
    for sym in sorted(all_syms):
        r5 = _return_at(sym, t0_5, t5)
        r20 = _return_at(sym, t0_20, t20)
        r3m = _return_at(sym, t0_60, t60)
        ticker_data.append({
            "ticker": sym,
            "cohort": cohort_map.get(sym, "SCORED"),
            "return_5d": r5,
            "return_20d": r20,
            "return_3m": r3m,
        })

    # --- 4. Per-stage stats ---
    stages = ["SCORED", "QUEUED", "ANALYZED", "DEPLOYED"]
    stage_stats: Dict[str, dict] = {}
    for stage in stages:
        members = [t for t in ticker_data if t["cohort"] == stage and t["return_5d"] is not None]
        members_20 = [t for t in ticker_data if t["cohort"] == stage and t["return_20d"] is not None]
        n = len(members)
        mean_5d = round(sum(t["return_5d"] for t in members) / n, 6) if n else None
        mean_20d = round(sum(t["return_20d"] for t in members_20) / len(members_20), 6) if members_20 else None
        edge_5d = round(mean_5d - bm_5d, 6) if mean_5d is not None and bm_5d is not None else None
        stage_stats[stage] = {"n": n, "mean_5d": mean_5d, "mean_20d": mean_20d, "edge_5d": edge_5d}

    # Filter alpha: mean(kept) - mean(rejected at that cut)
    def _filter_alpha(kept_stage: str, all_at_prev: list[str]) -> Optional[float]:
        kept = [t for t in ticker_data if t["cohort"] == kept_stage and t["return_5d"] is not None]
        rejected = [t for t in ticker_data if t["cohort"] in all_at_prev and t["return_5d"] is not None]
        if not kept or not rejected:
            return None
        mean_kept = sum(t["return_5d"] for t in kept) / len(kept)
        mean_rej = sum(t["return_5d"] for t in rejected) / len(rejected)
        return round(mean_kept - mean_rej, 6)

    fa_sq = _filter_alpha("QUEUED", ["SCORED"])
    fa_qa = _filter_alpha("ANALYZED", ["QUEUED"])
    fa_ad = _filter_alpha("DEPLOYED", ["ANALYZED"])

    # --- 5. Signal family IC ---
    # Build per-symbol aggregated raw_score by family
    family_scores: Dict[str, Dict[str, float]] = defaultdict(dict)
    for sig in signals_raw:
        sym = str(sig.get("symbol", "")).strip().upper()
        fam = str(sig.get("signal_family", ""))
        raw = float(sig.get("raw_score", 0.0))
        if sym and fam and sym in scored_syms:
            family_scores[fam][sym] = raw

    # Map ticker → 5d return (scored universe only)
    ret_map = {t["ticker"]: t["return_5d"] for t in ticker_data if t["return_5d"] is not None}

    family_ic_results: List[dict] = []
    for fam, sym_scores in sorted(family_scores.items()):
        scores_list = []
        returns_list = []
        for sym, raw in sym_scores.items():
            if sym in ret_map:
                scores_list.append(raw)
                returns_list.append(ret_map[sym])
        ic, t_stat, n = _spearman_ic_with_tstat(scores_list, returns_list)
        family_ic_results.append({
            "signal_family": fam,
            "ic": ic,
            "t_stat": t_stat,
            "n": n,
        })

    # --- 6. Persist ---
    eval_date = t5 or ""
    conn = _get_db(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO performance_cycles VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_date, eval_date,
                bm_5d, bm_20d,
                stage_stats["SCORED"]["n"], stage_stats["SCORED"]["mean_5d"],
                stage_stats["SCORED"]["mean_20d"], stage_stats["SCORED"]["edge_5d"],
                stage_stats["QUEUED"]["n"], stage_stats["QUEUED"]["mean_5d"],
                stage_stats["QUEUED"]["mean_20d"], stage_stats["QUEUED"]["edge_5d"],
                fa_sq,
                stage_stats["ANALYZED"]["n"], stage_stats["ANALYZED"]["mean_5d"],
                stage_stats["ANALYZED"]["mean_20d"], stage_stats["ANALYZED"]["edge_5d"],
                fa_qa,
                stage_stats["DEPLOYED"]["n"], stage_stats["DEPLOYED"]["mean_5d"],
                stage_stats["DEPLOYED"]["mean_20d"], stage_stats["DEPLOYED"]["edge_5d"],
                fa_ad,
                datetime.datetime.utcnow().isoformat(),
            ),
        )
        for fic in family_ic_results:
            conn.execute(
                """INSERT OR REPLACE INTO signal_family_ic VALUES (?,?,?,?,?)""",
                (source_date, fic["signal_family"], fic["ic"], fic["t_stat"], fic["n"]),
            )
        conn.commit()
    finally:
        conn.close()

    # --- 7. Enrich stage rows and write artifact ---
    result = {
        "source_date": source_date,
        "eval_date": eval_date,
        "benchmark": benchmark,
        "benchmark_return_5d": bm_5d,
        "benchmark_return_20d": bm_20d,
        "benchmark_return_3m": bm_3m,
        "stages": stage_stats,
        "filter_alpha": {
            "scored_to_queued_5d": fa_sq,
            "queued_to_analyzed_5d": fa_qa,
            "analyzed_to_deployed_5d": fa_ad,
        },
        "signal_family_ic": family_ic_results,
        "ticker_data": ticker_data,
    }
    result["discovery_delta_cohorts"] = build_discovery_delta_cohort_scorecards(
        discovery_delta=discovery_delta,
        step1_symbols=step1_symbols,
        shortlist_symbols=sorted(queued_syms),
        deep_selection_symbols=[
            str(item.get("symbol", "")).strip().upper()
            for item in queue_data.get("items", [])
            if str(item.get("symbol", "")).strip().upper() and bool(item.get("selected_for_deep"))
        ],
        forward_returns_by_horizon={
            "5d": {
                symbol: float(value)
                for symbol, value in (
                    (str(ticker.get("ticker", "")).upper().strip(), ticker.get("return_5d"))
                    for ticker in ticker_data
                )
                if symbol and value is not None
            },
            "20d": {
                symbol: float(value)
                for symbol, value in (
                    (str(ticker.get("ticker", "")).upper().strip(), ticker.get("return_20d"))
                    for ticker in ticker_data
                )
                if symbol and value is not None
            },
            "3m": {
                symbol: float(value)
                for symbol, value in (
                    (str(ticker.get("ticker", "")).upper().strip(), ticker.get("return_3m"))
                    for ticker in ticker_data
                )
                if symbol and value is not None
            },
        },
        benchmark_returns_by_horizon={
            "5d": bm_5d,
            "20d": bm_20d,
            "3m": bm_3m,
        },
    )
    result["evidence_integrity_cohorts"] = build_evidence_integrity_scorecards(
        evidence_integrity=evidence_integrity,
        step2_symbols=step1_symbols,
        shortlist_symbols=sorted(queued_syms),
        deep_selection_symbols=[
            str(item.get("symbol", "")).strip().upper()
            for item in queue_data.get("items", [])
            if str(item.get("symbol", "")).strip().upper() and bool(item.get("selected_for_deep"))
        ],
        forward_returns_by_horizon={
            "5d": {
                symbol: float(value)
                for symbol, value in (
                    (str(ticker.get("ticker", "")).upper().strip(), ticker.get("return_5d"))
                    for ticker in ticker_data
                )
                if symbol and value is not None
            },
            "20d": {
                symbol: float(value)
                for symbol, value in (
                    (str(ticker.get("ticker", "")).upper().strip(), ticker.get("return_20d"))
                    for ticker in ticker_data
                )
                if symbol and value is not None
            },
            "3m": {
                symbol: float(value)
                for symbol, value in (
                    (str(ticker.get("ticker", "")).upper().strip(), ticker.get("return_3m"))
                    for ticker in ticker_data
                )
                if symbol and value is not None
            },
        },
        benchmark_returns_by_horizon={
            "5d": bm_5d,
            "20d": bm_20d,
            "3m": bm_3m,
        },
    )

    returns_3m = {
        t["ticker"]: float(t["return_3m"])
        for t in ticker_data
        if t.get("return_3m") is not None
    }
    winner_horizon = "3m" if returns_3m else "20d"
    enrich_ledger_rows(
        base_dir=base,
        lane="shared",
        forward_returns_by_horizon={
            "5d": {
                t["ticker"]: float(t["return_5d"])
                for t in ticker_data
                if t.get("return_5d") is not None
            },
            "20d": {
                t["ticker"]: float(t["return_20d"])
                for t in ticker_data
                if t.get("return_20d") is not None
            },
            "3m": returns_3m,
        },
        winner_horizon=winner_horizon,
    )
    result["hypothesis_stage_summary"] = summarize_ledger_rows(base_dir=base, lane="shared")

    out_path = base / "performance_review.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    result["output_path"] = str(out_path)

    return result
