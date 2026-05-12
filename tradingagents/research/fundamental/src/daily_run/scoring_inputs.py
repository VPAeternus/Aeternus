from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from tradingagents.research.fundamental.src.features.pre_llm_scores import build_pre_llm_rows
from tradingagents.research.fundamental.src.ingest.xbrl import companyfacts_to_pre_llm_input


def _cik10(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(int(float(text))).zfill(10)
    except ValueError:
        return text.zfill(10)


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _next_weekday(value: date) -> date:
    current = value + timedelta(days=1)
    while current.weekday() >= 5:
        current += timedelta(days=1)
    return current


def derive_tradable_date_from_coverage(row: dict[str, Any]) -> str:
    dates = [_parse_date(row.get("earnings_8k_filing_date")), _parse_date(row.get("periodic_filing_date"))]
    valid = [item for item in dates if item is not None]
    if not valid:
        return ""
    return _next_weekday(max(valid)).isoformat()


def build_pre_llm_from_companyfacts_cache(
    *,
    universe_rows: list[dict[str, Any]],
    companyfacts_root: Path,
    quarter: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    input_rows: list[dict[str, Any]] = []
    cached = 0
    for row in universe_rows:
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper()
        cik10 = _cik10(row.get("cik"))
        facts_path = companyfacts_root / f"CIK{cik10}.json" if cik10 else None
        facts_input: dict[str, Any] = {"ticker": ticker, "quarter": quarter}
        if facts_path and facts_path.exists():
            cached += 1
            facts_input.update(
                companyfacts_to_pre_llm_input(
                    json.loads(facts_path.read_text(encoding="utf-8")),
                    ticker=ticker,
                    quarter=quarter,
                )
            )
        input_rows.append({**row, **facts_input, "ticker": ticker, "quarter": quarter})

    scored = build_pre_llm_rows(input_rows)
    summary = {
        "universe_rows": len(universe_rows),
        "companyfacts_cached": cached,
        "pre_llm_scored": sum(1 for row in scored if row.get("pre_llm_fundamental_bucket") != "not_scored"),
        "pre_llm_not_scored": sum(1 for row in scored if row.get("pre_llm_fundamental_bucket") == "not_scored"),
    }
    return scored, summary


def attach_entry_prices(
    rows: list[dict[str, Any]],
    *,
    as_of: str,
    price_provider: Callable[..., list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    needs = [row for row in rows if row.get("ticker") and row.get("tradable_date") and not row.get("entry_open")]
    tickers = sorted({str(row["ticker"]).upper() for row in needs})
    dates = [str(row["tradable_date"]) for row in needs]
    price_rows = price_provider(tickers, start=min(dates), end=as_of) if tickers and dates else []
    open_by_key = {
        (str(item.get("ticker", "")).upper(), str(item.get("date", ""))): item.get("open", "")
        for item in price_rows
    }
    output: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    for row in rows:
        out = dict(row)
        if out.get("tradable_date") and not out.get("entry_open"):
            value = open_by_key.get((str(out.get("ticker", "")).upper(), str(out.get("tradable_date", ""))))
            if value not in {None, ""}:
                out["entry_open"] = value
                out["entry_open_source"] = "price_provider_open"
        if not out.get("entry_open"):
            quarantine.append({"ticker": out.get("ticker", ""), "quarter": out.get("quarter", ""), "quarantine_reason": "missing_entry_open"})
        output.append(out)
    summary = {"rows": len(rows), "entry_open_ready": len(rows) - len(quarantine), "missing_entry_open": len(quarantine)}
    return output, quarantine, summary
