from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import pandas as pd
import yfinance as yf

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_pre_llm_fundamental_score import bucket as pre_llm_bucket
from build_pre_llm_fundamental_score import load_price_panels, return_fields
from build_pre_llm_fundamental_score import write_csv
from build_xbrl_universal_features import FIELD_SETS, build_row
from fetch_sec_companyfacts_for_akg import (
    CACHE_DIR as SEC_CACHE_DIR,
    SEC_FACTS_URL,
    load_company_ticker_map,
    request_json,
)
from src.config.cache_paths import market_cache_root
from spec_convex_llm_testset import (
    PACKET_FIELDS,
    best_text_doc,
    clean,
    extract_evidence_snippets,
    first_semicolon_value,
    is_candidate,
    is_demote,
    is_high_priority,
    output_path,
    read_csv,
)


OUT_DIR = ROOT / "Growth" / "earnings_8k_sec_parser"
DEFAULT_MASTER = OUT_DIR / "pre_llm_fundamental_score_2021Q4_2026Q1_partial.csv"
DEFAULT_POST_LLM_MASTER = OUT_DIR / "post_llm_added_tickers_2021Q4_2026Q1_partial.csv"
RETURN_HORIZONS = [10, 20, 30, 60, 90]


def quarter_start(quarter: str) -> date:
    year = int(quarter[:4])
    q = int(quarter[-1])
    return date(year, (q - 1) * 3 + 1, 1)


def current_quarter(today: date | None = None) -> str:
    today = today or date.today()
    return f"{today.year}Q{((today.month - 1) // 3) + 1}"


def quarter_range(start: str, end: str) -> list[str]:
    year = int(start[:4])
    q = int(start[-1])
    end_year = int(end[:4])
    end_q = int(end[-1])
    quarters: list[str] = []
    while (year, q) <= (end_year, end_q):
        quarters.append(f"{year}Q{q}")
        q += 1
        if q == 5:
            year += 1
            q = 1
    return quarters


def prior_quarter(quarter: str) -> str:
    try:
        year = int(quarter[:4])
        q = int(quarter[-1])
    except (TypeError, ValueError):
        return ""
    if q == 1:
        return f"{year - 1}Q4"
    return f"{year}Q{q - 1}"


def read_csv_if_exists(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return read_csv(path)


def run(cmd: list[str], *, dry_run: bool) -> None:
    printable = " ".join(cmd)
    print(printable, flush=True)
    if dry_run:
        return
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    subprocess.run(cmd, cwd=ROOT, check=True, env=env)


def sec_ticker_info(ticker: str, *, refresh: bool) -> dict[str, Any]:
    ticker_map = load_company_ticker_map(refresh=refresh)
    row = ticker_map.get(ticker)
    if not row:
        raise SystemExit(f"missing_sec_ticker_map:{ticker}")
    cik = str(row.get("cik_str", "")).strip()
    if not cik:
        raise SystemExit(f"missing_sec_cik:{ticker}")
    return {"ticker": ticker, "cik": cik, "company_title": row.get("title", "")}


def ensure_companyfacts(ticker: str, cik: str, *, force: bool) -> Path:
    out = SEC_CACHE_DIR / f"facts_{ticker}.json"
    if out.exists() and not force:
        return out
    cik10 = str(cik).zfill(10)
    try:
        facts = request_json(SEC_FACTS_URL.format(cik10=cik10))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SystemExit(f"companyfacts_fetch_failed:{ticker}:{type(exc).__name__}") from exc
    out.write_text(json.dumps(facts, sort_keys=True), encoding="utf-8")
    return out


def ensure_price_cache(ticker: str, *, force: bool, period: str) -> Path:
    out = market_cache_root(f"prices_single_name_{ticker}.parquet")
    if out.exists() and not force:
        return out
    frame = yf.download(
        ticker,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=False,
    )
    if frame is None or frame.empty:
        raise SystemExit(f"price_fetch_empty:{ticker}")
    if not isinstance(frame.columns, pd.MultiIndex):
        frame = pd.concat({ticker: frame}, axis=1)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out)
    return out


def write_one_ticker_universe(path: Path, ticker: str, cik: str) -> None:
    write_csv(path, [{"ticker": ticker, "cik": cik}])


def build_pre_llm_inputs(
    ticker: str,
    quarter: str,
    audit_path: Path,
    work_dir: Path,
) -> tuple[Path, Path, Path, int]:
    rows = read_csv_if_exists(audit_path)
    ready = [
        row
        for row in rows
        if clean(row.get("ticker")).upper() == ticker
        and row.get("ready_for_earnings_extraction") == "True"
        and row.get("ready_for_periodic_extraction") == "True"
    ]
    universe = work_dir / f"pre_llm_universe_{ticker}_{quarter}.csv"
    events = work_dir / f"pre_llm_events_{ticker}_{quarter}.csv"
    returns = work_dir / f"no_llm_earnings_score_{ticker}_{quarter}.csv"
    universe_rows: list[dict[str, str]] = []
    event_rows: list[dict[str, str]] = []
    return_rows: list[dict[str, str]] = []
    for row in ready:
        first_event = first_semicolon_value(row.get("item_202_event_dates"))
        universe_rows.append({"quarter": quarter, "ticker": ticker, "cik": row.get("cik", ""), "asof_date": first_event})
        event_rows.append({"ticker": ticker, "event_dates": row.get("item_202_event_dates", "")})
        return_rows.append({"ticker": ticker})
    write_csv(universe, universe_rows)
    write_csv(events, event_rows)
    write_csv(returns, return_rows)
    return universe, events, returns, len(ready)


def build_xbrl_rows(universe_path: Path, quarter: str, output_path: Path) -> list[dict[str, Any]]:
    rows = []
    asof = quarter_start(quarter)
    for row in read_csv(universe_path):
        rows.append(build_row(row, asof, FIELD_SETS["through_ocf"]))
    write_csv(output_path, rows)
    return rows


def to_float(value: Any) -> float | None:
    try:
        if value in {"", None}:
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return numerator / denominator


def component_scores(row: dict[str, Any]) -> dict[str, Any]:
    revenue = to_float(row.get("revenue_value"))
    net_income = to_float(row.get("net_income_value"))
    assets = to_float(row.get("assets_value"))
    financing_cf = to_float(row.get("financing_cash_flow_value"))
    investing_cf = to_float(row.get("investing_cash_flow_value"))
    operating_cf = to_float(row.get("operating_cash_flow_value"))

    net_margin = ratio(net_income, revenue)
    ocf_margin = ratio(operating_cf, revenue)
    fcf_proxy = None if operating_cf is None or investing_cf is None else operating_cf + investing_cf
    fcf_proxy_margin = ratio(fcf_proxy, revenue)
    financing_dep = ratio(max(financing_cf, 0) if financing_cf is not None else None, revenue)
    asset_turnover = ratio(revenue, assets)

    def profitability(value: float | None) -> int | str:
        if value is None:
            return ""
        return 2 if value > 0.10 else 1 if value >= 0 else -1

    def ocf(value: float | None) -> int | str:
        if value is None:
            return ""
        return 2 if value > 0.10 else 1 if value >= 0 else -1

    def fcf(value: float | None) -> int | str:
        if value is None:
            return ""
        return 2 if value > 0.05 else 1 if value >= 0 else -1

    def financing(value: float | None) -> int | str:
        if value is None:
            return ""
        return 1 if value <= 0 else 0 if value <= 0.10 else -1

    def assets_score(value: float | None) -> int | str:
        if value is None:
            return ""
        return 2 if value > 1.0 else 1 if value >= 0.5 else 0

    scores = {
        "profitability_score": profitability(net_margin),
        "operating_cash_flow_score": ocf(ocf_margin),
        "fcf_proxy_score": fcf(fcf_proxy_margin),
        "financing_dependence_score": financing(financing_dep),
        "asset_efficiency_score": assets_score(asset_turnover),
    }
    missing = [key for key, value in scores.items() if value == ""]
    total = "" if missing else sum(int(value) for value in scores.values())
    return {
        **scores,
        "pre_llm_fundamental_score": total,
        "pre_llm_fundamental_bucket": "not_scored" if missing else pre_llm_bucket(int(total)),
        "pre_llm_fundamental_missing_fields": ";".join(missing),
    }


def tier_labels(row: dict[str, Any]) -> dict[str, str]:
    revenue_bucket = clean(row.get("revenue_bucket"))
    pre_bucket = clean(row.get("pre_llm_fundamental_bucket"))
    entry = to_float(row.get("entry_open"))
    score = to_float(row.get("pre_llm_fundamental_score"))
    allowed = {"<$100M", "$100M-$500M", "$500M-$1B", "$1B-$2B", "$2B-$10B"}

    def base(max_price: float) -> bool:
        return pre_bucket != "not_scored" and entry is not None and entry < max_price and revenue_bucket in allowed

    return {
        "tier_bucket": "Tier 0 - Broad right-tail scouting universe" if base(25) else "",
        "tier_1_bucket": "Tier 1 - Balanced priority feed" if base(15) else "",
        "tier_2_bucket": "Tier 2 - High-priority compact feed" if base(10) else "",
        "tier_3_bucket": "Tier 3 - Revised dislocation feed" if base(15) and score is not None and score <= 0 else "",
        "tier_4_bucket": "Tier 4 - Ultra-distressed tag, not a production tier" if base(5) else "",
    }


def build_pre_llm_scores(
    ticker: str,
    xbrl_rows: list[dict[str, Any]],
    events_path: Path,
    output_path: Path,
) -> list[dict[str, Any]]:
    events = {row["ticker"]: row for row in read_csv(events_path)}
    prices = load_price_panels()
    rows: list[dict[str, Any]] = []
    for row in xbrl_rows:
        event_date = first_semicolon_value(events.get(ticker, {}).get("event_dates", ""))
        returns = return_fields(prices.get(ticker), event_date)
        score = component_scores(row)
        out = {
            "quarter": row.get("quarter", ""),
            "ticker": ticker,
            "revenue_bucket": row.get("revenue_bucket", ""),
            **score,
            "tradable_date": returns.get("tradable_date", ""),
            "entry_open": returns.get("entry_open", ""),
            "return_10d_pct": returns.get("return_10d_pct", ""),
            "return_20d_pct": returns.get("return_20d_pct", ""),
            "return_30d_pct": returns.get("return_30d_pct", ""),
            "return_60d_pct": returns.get("return_60d_pct", ""),
            "return_90d_pct": returns.get("return_90d_pct", ""),
        }
        out = {**out, **tier_labels(out)}
        ordered = {
            "quarter": out["quarter"],
            "ticker": out["ticker"],
            "revenue_bucket": out["revenue_bucket"],
            "profitability_score": out["profitability_score"],
            "operating_cash_flow_score": out["operating_cash_flow_score"],
            "fcf_proxy_score": out["fcf_proxy_score"],
            "financing_dependence_score": out["financing_dependence_score"],
            "asset_efficiency_score": out["asset_efficiency_score"],
            "pre_llm_fundamental_score": out["pre_llm_fundamental_score"],
            "pre_llm_fundamental_bucket": out["pre_llm_fundamental_bucket"],
            "pre_llm_fundamental_missing_fields": out["pre_llm_fundamental_missing_fields"],
            "tier_bucket": out["tier_bucket"],
            "tier_1_bucket": out["tier_1_bucket"],
            "tier_2_bucket": out["tier_2_bucket"],
            "tier_3_bucket": out["tier_3_bucket"],
            "tier_4_bucket": out["tier_4_bucket"],
            "tradable_date": out["tradable_date"],
            "entry_open": out["entry_open"],
            "return_10d_pct": out["return_10d_pct"],
            "return_20d_pct": out["return_20d_pct"],
            "return_30d_pct": out["return_30d_pct"],
            "return_60d_pct": out["return_60d_pct"],
            "return_90d_pct": out["return_90d_pct"],
        }
        rows.append(ordered)
    write_csv(output_path, rows)
    return rows


def build_llm_packets(
    ticker: str,
    pre_rows: list[dict[str, Any]],
    work_dir: Path,
    output_prefix: Path,
    max_snippets: int,
) -> int:
    records: list[dict[str, Any]] = []
    for idx, row in enumerate(pre_rows, start=1):
        quarter = clean(row.get("quarter"))
        audit_path = work_dir / f"sec_quarter_cache_audit_{ticker}_{quarter}.csv"
        fetch_path = work_dir / f"sec_quarter_cache_fetch_report_{ticker}_{quarter}.csv"
        audit_rows = read_csv_if_exists(audit_path)
        fetch_rows = read_csv_if_exists(fetch_path)
        audit = audit_rows[0] if audit_rows else {}
        accession = first_semicolon_value(audit.get("item_202_accessions"))
        event_date = first_semicolon_value(audit.get("item_202_event_dates"))
        doc = best_text_doc(fetch_rows, ticker=ticker, accession=accession)
        text_path = clean(doc.get("text_path"))
        quality_flags: list[str] = []
        text = ""
        path = Path(text_path) if text_path else None
        if not accession:
            quality_flags.append("missing_accession")
        if not text_path:
            quality_flags.append("missing_text_path")
        elif path and not path.exists():
            quality_flags.append("text_path_not_found")
        else:
            text = path.read_text(encoding="utf-8", errors="ignore") if path else ""
        snippets = extract_evidence_snippets(text, limit=max_snippets) if text else []
        if not snippets:
            quality_flags.append("missing_evidence_snippets")
        records.append(
            {
                "sample_id": f"{ticker}{idx:06d}",
                "quarter": quarter,
                "ticker": ticker,
                "event_date": event_date,
                "revenue_bucket": row.get("revenue_bucket", ""),
                "pre_llm_fundamental_bucket": row.get("pre_llm_fundamental_bucket", ""),
                "pre_llm_fundamental_score": row.get("pre_llm_fundamental_score", ""),
                "profitability_score": row.get("profitability_score", ""),
                "operating_cash_flow_score": row.get("operating_cash_flow_score", ""),
                "financing_dependence_score": row.get("financing_dependence_score", ""),
                "tradable_date": row.get("tradable_date", ""),
                "entry_open": row.get("entry_open", ""),
                "return_10d_pct": row.get("return_10d_pct", ""),
                "return_20d_pct": row.get("return_20d_pct", ""),
                "return_30d_pct": row.get("return_30d_pct", ""),
                "return_60d_pct": row.get("return_60d_pct", ""),
                "return_90d_pct": row.get("return_90d_pct", ""),
                "tier_bucket": row.get("tier_bucket", ""),
                "tier_1_bucket": row.get("tier_1_bucket", ""),
                "tier_2_bucket": row.get("tier_2_bucket", ""),
                "tier_3_bucket": row.get("tier_3_bucket", ""),
                "tier_4_bucket": row.get("tier_4_bucket", ""),
                "accession": accession,
                "exhibit_doc": doc.get("document", ""),
                "source_doc_type": doc.get("doc_type", ""),
                "text_len": doc.get("text_len", ""),
                "text_path": text_path,
                "snippet_count": len(snippets),
                "quality_flags": ";".join(quality_flags),
                "evidence_snippets": snippets,
            }
        )

    selection_fields = [
        "sample_id", "quarter", "ticker", "event_date", "revenue_bucket", "pre_llm_fundamental_bucket",
        "pre_llm_fundamental_score", "profitability_score", "operating_cash_flow_score",
        "financing_dependence_score", "tradable_date", "entry_open", "return_10d_pct", "return_20d_pct",
        "return_30d_pct", "return_60d_pct", "return_90d_pct", "tier_bucket", "tier_1_bucket", "tier_2_bucket",
        "tier_3_bucket", "tier_4_bucket", "accession", "exhibit_doc", "source_doc_type", "text_len", "text_path",
        "snippet_count", "quality_flags",
    ]
    write_csv(output_path(output_prefix, "_selection.csv"), records)
    with output_path(output_prefix, "_packets.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps({field: record.get(field, "") for field in PACKET_FIELDS}, ensure_ascii=True) + "\n")
    write_csv(
        output_path(output_prefix, "_quality_report.csv"),
        [
            {"metric": "records", "value": len(records)},
            {"metric": "missing_accession", "value": sum("missing_accession" in clean(r.get("quality_flags")) for r in records)},
            {"metric": "missing_text_path", "value": sum("missing_text_path" in clean(r.get("quality_flags")) for r in records)},
            {"metric": "missing_evidence_snippets", "value": sum("missing_evidence_snippets" in clean(r.get("quality_flags")) for r in records)},
        ],
    )
    # Re-write selection with stable field order after dynamic quality rows.
    write_csv(output_path(output_prefix, "_selection.csv"), [{field: r.get(field, "") for field in selection_fields} for r in records])
    return len(records)


def join_llm_outputs(selection_csv: Path, extraction_csv: Path, output_prefix: Path) -> Path:
    selection = {row["sample_id"]: row for row in read_csv(selection_csv)}
    rows: list[dict[str, str]] = []
    for extraction in read_csv(extraction_csv):
        base = selection.get(extraction.get("sample_id", ""))
        if base:
            rows.append({**base, **extraction})
    joined = output_path(output_prefix, "_joined.csv")
    write_csv(joined, rows)
    return joined


def write_post_llm_scores(joined_csv: Path, output_path_: Path) -> list[dict[str, Any]]:
    rows = read_csv(joined_csv)
    output: list[dict[str, Any]] = []
    addition_by_ticker_quarter = {
        (clean(row.get("ticker")).upper(), clean(row.get("quarter"))): int(float(row.get("score_addition") or 0))
        for row in rows
    }
    for row in rows:
        base_score = int(float(row.get("pre_llm_fundamental_score") or 0))
        addition = int(float(row.get("score_addition") or 0))
        post_score = base_score + addition
        risk = int(float(row.get("negative_revision_risk") or 0))
        gap = int(float(row.get("story_vs_numbers_gap_penalty") or 0))
        causal_change = int(float(row.get("causal_change") or 0))
        narrative_delta_bucket = clean(row.get("narrative_delta_bucket"))
        candidate_flag = int(is_candidate(row))
        high_priority_flag = int(is_high_priority(row))
        tier_1_base = bool(row.get("tier_1_bucket"))
        tier_1_1 = tier_1_base and candidate_flag == 1
        tier_1_2 = tier_1_base and causal_change == 3
        tier_1_3 = tier_1_base and candidate_flag == 1 and causal_change == 3 and risk <= 2
        tier_1_4 = tier_1_base and high_priority_flag == 1
        tier_2_base = bool(row.get("tier_2_bucket"))
        tier_2_1 = tier_2_base and candidate_flag == 1
        tier_2_2 = tier_2_base and causal_change == 3
        tier_2_3 = tier_2_base and candidate_flag == 1 and causal_change == 3 and risk <= 2
        tier_3_base = bool(row.get("tier_3_bucket"))
        tier_3_1 = tier_3_base and candidate_flag == 1
        tier_3_2 = tier_3_base and (high_priority_flag == 1 or narrative_delta_bucket == "inflecting")
        prior_addition = addition_by_ticker_quarter.get(
            (clean(row.get("ticker")).upper(), prior_quarter(clean(row.get("quarter"))))
        )
        tier_3_3 = tier_3_base and addition > 0 and prior_addition is not None and prior_addition > 0
        tier_3_4 = tier_3_base and high_priority_flag == 1 and prior_addition is not None and prior_addition > 0
        tier_4_base = bool(row.get("tier_4_bucket"))
        tier_4_1 = tier_4_base and candidate_flag == 1
        tier_4_2 = tier_4_base and causal_change == 3
        tier_4_3 = tier_4_base and high_priority_flag == 1
        sub_tiers = []
        if tier_1_1:
            sub_tiers.append("Tier 1.1 - LLM-supported candidate")
        if tier_1_2:
            sub_tiers.append("Tier 1.2 - Causal re-rating candidate")
        if tier_1_3:
            sub_tiers.append("Tier 1.3 - Best balanced production subset")
        if tier_1_4:
            sub_tiers.append("Tier 1.4 - Clean high-priority subset")
        if tier_2_1:
            sub_tiers.append("Tier 2.1 - LLM-supported")
        if tier_2_2:
            sub_tiers.append("Tier 2.2 - Causal re-rating")
        if tier_2_3:
            sub_tiers.append("Tier 2.3 - Best balanced LLM subset")
        if tier_3_1:
            sub_tiers.append("Tier 3.1 - Cleaner LLM-positive Tier 3")
        if tier_3_2:
            sub_tiers.append("Tier 3.2 - LLM inflection / high priority")
        if tier_3_3:
            sub_tiers.append("Tier 3.3 - Persistent re-rating setup")
        if tier_3_4:
            sub_tiers.append("Tier 3.4 - Persistent high-priority re-rating")
        if tier_4_1:
            sub_tiers.append("Tier 4.1 - LLM-supported aggressive")
        if tier_4_2:
            sub_tiers.append("Tier 4.2 - Causal re-rating candidate")
        if tier_4_3:
            sub_tiers.append("Tier 4.3 - Clean high-priority")
        output.append(
            {
                **row,
                "post_llm_fundamental_score": post_score,
                "post_llm_fundamental_bucket": pre_llm_bucket(post_score),
                "post_llm_score_delta": addition,
                "post_llm_candidate_flag": candidate_flag,
                "post_llm_high_priority_flag": high_priority_flag,
                "post_llm_demote_flag": int(risk >= 4 or gap >= 2 or is_demote(row)),
                "post_llm_tier_1_1_flag": int(tier_1_1),
                "post_llm_tier_1_2_flag": int(tier_1_2),
                "post_llm_tier_1_3_flag": int(tier_1_3),
                "post_llm_tier_1_4_flag": int(tier_1_4),
                "post_llm_tier_2_1_flag": int(tier_2_1),
                "post_llm_tier_2_2_flag": int(tier_2_2),
                "post_llm_tier_2_3_flag": int(tier_2_3),
                "post_llm_tier_3_1_flag": int(tier_3_1),
                "post_llm_tier_3_2_flag": int(tier_3_2),
                "post_llm_tier_3_3_flag": int(tier_3_3),
                "post_llm_tier_3_4_flag": int(tier_3_4),
                "post_llm_tier_4_1_flag": int(tier_4_1),
                "post_llm_tier_4_2_flag": int(tier_4_2),
                "post_llm_tier_4_3_flag": int(tier_4_3),
                "post_llm_sub_tier_bucket": ";".join(sub_tiers),
            }
        )
    write_csv(output_path_, output)
    return output


def append_dedupe(master_path: Path, add_path: Path, output_path_: Path) -> int:
    rows = read_csv_if_exists(master_path) + read_csv_if_exists(add_path)
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        key = (row.get("quarter", ""), row.get("ticker", ""))
        if key in seen:
            deduped = [existing for existing in deduped if (existing.get("quarter", ""), existing.get("ticker", "")) != key]
        seen.add(key)
        deduped.append(row)
    write_csv(output_path_, [{key: row.get(key, "") for key in fieldnames} for row in deduped])
    return len(deduped)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add one ticker to SEC/pre-LLM/LLM universe")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--start-quarter", default="2021Q4")
    parser.add_argument("--end-quarter", default="latest")
    parser.add_argument("--master-pre-llm", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--output-master-pre-llm", type=Path, default=None)
    parser.add_argument("--master-post-llm", type=Path, default=DEFAULT_POST_LLM_MASTER)
    parser.add_argument("--output-master-post-llm", type=Path, default=None)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--sleep", type=float, default=0.1)
    parser.add_argument("--force-facts", action="store_true")
    parser.add_argument("--force-prices", action="store_true")
    parser.add_argument("--refresh-sec-map", action="store_true")
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ticker = args.ticker.upper().strip()
    end = current_quarter() if args.end_quarter == "latest" else args.end_quarter
    quarters = quarter_range(args.start_quarter, end)
    work_dir = OUT_DIR / "add_ticker" / ticker
    work_dir.mkdir(parents=True, exist_ok=True)

    info = sec_ticker_info(ticker, refresh=args.refresh_sec_map)
    cik = str(info["cik"])
    if args.dry_run:
        facts_path = SEC_CACHE_DIR / f"facts_{ticker}.json"
        price_path = market_cache_root(f"prices_single_name_{ticker}.parquet")
        print(f"DRY_RUN ticker={ticker} cik={cik} facts={facts_path} prices={price_path}")
    else:
        facts_path = ensure_companyfacts(ticker, cik, force=args.force_facts)
        price_path = ensure_price_cache(ticker, force=args.force_prices, period="max")
        print(f"ticker={ticker} cik={cik} facts={facts_path} prices={price_path}")

    universe_path = work_dir / f"universe_{ticker}.csv"
    write_one_ticker_universe(universe_path, ticker, cik)

    all_pre_rows: list[dict[str, Any]] = []
    for quarter in quarters:
        audit = work_dir / f"sec_quarter_cache_audit_{ticker}_{quarter}.csv"
        fetch = work_dir / f"sec_quarter_cache_fetch_report_{ticker}_{quarter}.csv"
        run(
            [
                str(ROOT / ".venv" / "bin" / "python"),
                "Growth/sec_quarter_cache_manager.py",
                "--quarter",
                quarter,
                "--universe",
                str(universe_path),
                "--audit-output",
                str(audit),
                "--fetch-report",
                str(fetch),
                "--sleep",
                str(args.sleep),
                "--retries",
                "3",
                "--checkpoint-every",
                "1",
                "--metadata-source",
                "hybrid",
                "--issuer-mode",
                "auto",
                "--ticker-timeout-seconds",
                "180",
                "--resume-existing",
            ],
            dry_run=args.dry_run,
        )
        if args.dry_run:
            continue
        universe, events, _, ready_count = build_pre_llm_inputs(ticker, quarter, audit, work_dir)
        if ready_count == 0:
            print(f"{quarter} ready=0 skip scoring")
            continue
        xbrl_path = work_dir / f"xbrl_universal_features_through_ocf_{ticker}_{quarter}.csv"
        xbrl_rows = build_xbrl_rows(universe, quarter, xbrl_path)
        score_path = work_dir / f"pre_llm_fundamental_score_{ticker}_{quarter}.csv"
        all_pre_rows.extend(build_pre_llm_scores(ticker, xbrl_rows, events, score_path))

    pre_all = work_dir / f"pre_llm_fundamental_score_{ticker}_{args.start_quarter}_{end}.csv"
    if all_pre_rows:
        write_csv(pre_all, all_pre_rows)
    print(f"pre_llm_rows={len(all_pre_rows)} wrote={pre_all}")

    output_master = args.output_master_pre_llm or OUT_DIR / f"{args.master_pre_llm.stem}_plus_{ticker}.csv"
    if not args.dry_run and all_pre_rows:
        append_dedupe(args.master_pre_llm, pre_all, output_master)
        print(f"wrote_master_pre_llm={output_master}")

    if args.skip_llm or args.dry_run or not all_pre_rows:
        return

    prefix = work_dir / f"llm_all_{ticker}_{args.start_quarter}_{end}_{args.model.replace('.', '')}_{args.reasoning_effort}"
    packet_count = build_llm_packets(ticker, all_pre_rows, work_dir, prefix, max_snippets=18)
    print(f"llm_packets={packet_count} prefix={prefix}")
    if packet_count == 0:
        return
    extraction_csv = output_path(prefix, "_extractions.csv")
    run(
        [
            str(ROOT / ".venv" / "bin" / "python"),
            "Growth/run_spec_convex_llm_extraction.py",
            "--packets",
            str(output_path(prefix, "_packets.jsonl")),
            "--output-dir",
            str(output_path(prefix, "_llm")),
            "--output-csv",
            str(extraction_csv),
            "--model",
            args.model,
            "--reasoning-effort",
            args.reasoning_effort,
            "--batch-size",
            str(args.batch_size),
            "--max-attempts",
            "2",
        ],
        dry_run=args.dry_run,
    )
    joined = join_llm_outputs(output_path(prefix, "_selection.csv"), extraction_csv, prefix)
    post = output_path(prefix, "_post_llm_scores.csv")
    post_rows = write_post_llm_scores(joined, post)
    print(f"post_llm_rows={len(post_rows)} wrote={post}")
    output_master_post = args.output_master_post_llm or args.master_post_llm
    if post_rows:
        append_dedupe(args.master_post_llm, post, output_master_post)
        print(f"wrote_master_post_llm={output_master_post}")


if __name__ == "__main__":
    main()
