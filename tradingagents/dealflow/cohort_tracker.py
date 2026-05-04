"""Cohort Portfolio Tracker — Filter Alpha Measurement.

Tracks three equal-weight paper portfolios built from the same pipeline run
and compares their forward returns to measure whether each filter stage
adds value.

Cohorts:
  ENTERED    — everything in the research queue
  SELECTED   — tickers selected for deep analysis
  V3_CLEARED — selected AND aeternus_score >= 62.0
  V3_REJECTED — selected AND analyzed, but below the V3 hurdle
"""

from __future__ import annotations

import datetime
import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yfinance as yf


_DEAL_FLOW_DIR = Path("eval_results/deal_flow")
_RESULTS_DIR = Path("results")
_COHORT_DB = _DEAL_FLOW_DIR / "cohort_tracker.db"
_V3_HURDLE = 62.0


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------

def _get_db(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or _COHORT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cohort_snapshots (
            source_date       TEXT NOT NULL,
            eval_date         TEXT NOT NULL,
            cohort            TEXT NOT NULL,
            ticker_count      INT,
            eq_weight_return  REAL,
            score_weight_return REAL,
            benchmark_return  REAL,
            filter_alpha      REAL,
            best_ticker       TEXT,
            best_return       REAL,
            worst_ticker      TEXT,
            worst_return      REAL,
            tickers_json      TEXT,
            created_at        TEXT NOT NULL,
            PRIMARY KEY (source_date, eval_date, cohort)
        );
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    with open(path) as f:
        return json.load(f)


def _find_analysis_score(ticker: str, source_date: str) -> Optional[float]:
    """Find aeternus_score for a ticker from analysis reports near source_date."""
    sd = pd.Timestamp(source_date)
    # Check source_date and up to 5 days after for report
    for offset in range(6):
        d = (sd + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")
        report = _RESULTS_DIR / ticker / d / "analysis_report.json"
        if report.exists():
            try:
                data = _load_json(report)
                score_block = data.get("aeternus_score", {})
                if isinstance(score_block, dict):
                    return float(score_block.get("aeternus_score", 0.0))
                return float(score_block)
            except Exception:
                return None
    return None


def _score_weighted_return(
    tickers: list[dict],
) -> Optional[float]:
    """Compute score-weighted mean return. Falls back to equal-weight if no scores."""
    pairs = [
        (t["ret"], t.get("score") or 0.0)
        for t in tickers
        if t["ret"] is not None
    ]
    if not pairs:
        return None
    total_score = sum(abs(s) for _, s in pairs)
    if total_score == 0:
        # Fall back to equal weight
        return round(sum(r for r, _ in pairs) / len(pairs), 6)
    weighted = sum(r * abs(s) for r, s in pairs) / total_score
    return round(weighted, 6)


# ---------------------------------------------------------------------------
# Main compute
# ---------------------------------------------------------------------------

def compute_cohort_returns(
    source_date: str,
    eval_date: str | None = None,
    benchmark: str = "QQQ",
    db_path: Path | None = None,
) -> dict:
    """Compute forward returns for 3 pipeline cohorts.

    Args:
        source_date: Deal flow run date (YYYY-MM-DD).
        eval_date: Date to measure returns to. Defaults to today.
        benchmark: Benchmark ticker.

    Returns:
        Dict with per-cohort stats, filter alpha, and ticker details.
    """
    base = _DEAL_FLOW_DIR / source_date
    rq_path = base / "research_queue.json"
    if not rq_path.exists():
        return {"source_date": source_date, "error": f"No research_queue.json for {source_date}"}

    rq = _load_json(rq_path)
    items = rq.get("items", [])
    if not items:
        return {"source_date": source_date, "error": "Empty research queue"}

    eval_date = eval_date or datetime.date.today().isoformat()

    # --- Build cohorts ---
    entered, selected, v3_cleared, v3_rejected = [], [], [], []

    for item in items:
        sym = str(item.get("symbol", "")).strip().upper()
        if not sym:
            continue
        score = float(item.get("deal_flow_score") or item.get("momentum_score") or 0.0)
        entry = {"ticker": sym, "score": score, "ret": None}
        entered.append(entry)

        if item.get("selected_for_deep"):
            selected.append(dict(entry))
            # Check for V3 score
            aeternus_score = _find_analysis_score(sym, source_date)
            if aeternus_score is not None and aeternus_score >= _V3_HURDLE:
                v3_entry = dict(entry)
                v3_entry["aeternus_score"] = aeternus_score
                v3_entry["score"] = aeternus_score  # Use aeternus_score for weighting
                v3_cleared.append(v3_entry)
            elif aeternus_score is not None and aeternus_score < _V3_HURDLE:
                rejected_entry = dict(entry)
                rejected_entry["aeternus_score"] = aeternus_score
                rejected_entry["score"] = aeternus_score
                v3_rejected.append(rejected_entry)

    # --- Fetch prices ---
    all_tickers = sorted({e["ticker"] for e in entered} | {benchmark})
    start_str = source_date
    end_str = str((pd.Timestamp(eval_date) + pd.Timedelta(days=3)).date())

    try:
        prices = yf.download(
            all_tickers,
            start=start_str,
            end=end_str,
            progress=False,
            auto_adjust=True,
        )
    except Exception:
        prices = pd.DataFrame()

    if prices.empty:
        return {"source_date": source_date, "eval_date": eval_date, "error": "No price data"}

    # Extract close
    if isinstance(prices.columns, pd.MultiIndex):
        close = prices["Close"] if "Close" in prices.columns.get_level_values(0) else prices
    else:
        close = prices[["Close"]] if "Close" in prices.columns else prices
        if len(all_tickers) == 1:
            close.columns = all_tickers

    trading_dates = close.index.sort_values()
    t0_ts = pd.Timestamp(source_date)
    te_ts = pd.Timestamp(eval_date)
    t0_actual = trading_dates[trading_dates >= t0_ts]
    te_actual = trading_dates[trading_dates >= te_ts]

    if len(t0_actual) == 0 or len(te_actual) == 0:
        return {"source_date": source_date, "eval_date": eval_date, "error": "Insufficient trading days"}

    t0_date = t0_actual[0]
    te_date = te_actual[0]

    def _ret(ticker: str) -> Optional[float]:
        try:
            p0 = float(close.loc[t0_date, ticker])
            pe = float(close.loc[te_date, ticker])
            if p0 <= 0 or math.isnan(p0) or math.isnan(pe):
                return None
            return round((pe / p0) - 1.0, 6)
        except Exception:
            return None

    bm_return = _ret(benchmark)

    # Fill returns into cohort entries
    for cohort_list in (entered, selected, v3_cleared, v3_rejected):
        for entry in cohort_list:
            entry["ret"] = _ret(entry["ticker"])

    # --- Compute stats per cohort ---
    def _cohort_stats(name: str, members: list[dict]) -> dict:
        valid = [m for m in members if m["ret"] is not None]
        if not valid:
            return {"cohort": name, "ticker_count": len(members), "eq_weight_return": None,
                    "score_weight_return": None, "benchmark_return": bm_return,
                    "filter_alpha": None, "best_ticker": None, "best_return": None,
                    "worst_ticker": None, "worst_return": None, "tickers": [m["ticker"] for m in members]}

        rets = [m["ret"] for m in valid]
        eq_ret = round(sum(rets) / len(rets), 6)
        sw_ret = _score_weighted_return(valid)
        best = max(valid, key=lambda m: m["ret"])
        worst = min(valid, key=lambda m: m["ret"])
        fa = round(eq_ret - bm_return, 6) if bm_return is not None else None

        return {
            "cohort": name,
            "ticker_count": len(members),
            "eq_weight_return": eq_ret,
            "score_weight_return": sw_ret,
            "benchmark_return": bm_return,
            "filter_alpha": fa,
            "best_ticker": best["ticker"],
            "best_return": best["ret"],
            "worst_ticker": worst["ticker"],
            "worst_return": worst["ret"],
            "tickers": [m["ticker"] for m in members],
        }

    cohorts = {
        "ENTERED": _cohort_stats("ENTERED", entered),
        "SELECTED": _cohort_stats("SELECTED", selected),
        "V3_CLEARED": _cohort_stats("V3_CLEARED", v3_cleared),
        "V3_REJECTED": _cohort_stats("V3_REJECTED", v3_rejected),
    }

    # Filter alpha between stages
    e_ret = cohorts["ENTERED"].get("eq_weight_return")
    s_ret = cohorts["SELECTED"].get("eq_weight_return")
    v_ret = cohorts["V3_CLEARED"].get("eq_weight_return")

    inter_stage = {}
    if e_ret is not None and s_ret is not None:
        inter_stage["entered_to_selected"] = round(s_ret - e_ret, 6)
    if s_ret is not None and v_ret is not None:
        inter_stage["selected_to_v3"] = round(v_ret - s_ret, 6)
    rejected_ret = cohorts["V3_REJECTED"].get("eq_weight_return")
    if bm_return is not None and rejected_ret is not None:
        inter_stage["benchmark_to_v3_rejected"] = round(bm_return - rejected_ret, 6)

    actual_eval = str(te_date.date())
    days = (te_date - t0_date).days

    result = {
        "source_date": source_date,
        "eval_date": actual_eval,
        "days": days,
        "benchmark": benchmark,
        "benchmark_return": bm_return,
        "cohorts": cohorts,
        "inter_stage_alpha": inter_stage,
    }

    # Persist to SQLite
    conn = _get_db(db_path)
    try:
        for c in cohorts.values():
            conn.execute(
                """INSERT OR REPLACE INTO cohort_snapshots VALUES
                   (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    source_date, actual_eval, c["cohort"], c["ticker_count"],
                    c.get("eq_weight_return"), c.get("score_weight_return"),
                    c.get("benchmark_return"), c.get("filter_alpha"),
                    c.get("best_ticker"), c.get("best_return"),
                    c.get("worst_ticker"), c.get("worst_return"),
                    json.dumps(c.get("tickers", [])),
                    datetime.datetime.utcnow().isoformat(),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return result


def compare_cohorts(db_path: Path | None = None) -> list[dict]:
    """Read all cohort snapshots grouped by source_date for cross-cycle comparison."""
    conn = _get_db(db_path)
    try:
        rows = conn.execute(
            """SELECT source_date, eval_date, cohort, ticker_count,
                      eq_weight_return, score_weight_return, benchmark_return, filter_alpha
               FROM cohort_snapshots ORDER BY source_date, cohort"""
        ).fetchall()
    finally:
        conn.close()

    cycles: dict[str, list[dict]] = {}
    for row in rows:
        sd = row[0]
        entry = {
            "source_date": sd,
            "eval_date": row[1],
            "cohort": row[2],
            "ticker_count": row[3],
            "eq_weight_return": row[4],
            "score_weight_return": row[5],
            "benchmark_return": row[6],
            "filter_alpha": row[7],
        }
        cycles.setdefault(sd, []).append(entry)

    return [{"source_date": sd, "cohorts": entries} for sd, entries in sorted(cycles.items())]
