from __future__ import annotations

import json
import inspect
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from tradingagents.research.fundamental.src.config.cache_paths import sec_cache_root
from tradingagents.research.fundamental.src.features.common import clean
from tradingagents.research.fundamental.src.features.pre_llm_scores import build_pre_llm_rows
from tradingagents.research.fundamental.src.ingest.companyfacts_pit import FIELD_CONCEPTS, select_pit_financials
from tradingagents.research.fundamental.src.ingest.period_context import derive_period_context
from tradingagents.research.fundamental.src.ingest.xbrl import companyfacts_to_pre_llm_input

from .row_contract import build_row_contract
from .artifacts import write_text_atomic


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


def _fallback_facts_path(ticker: str, fallback_root: Path | None) -> Path:
    root = fallback_root or sec_cache_root()
    return root / f"facts_{ticker}.json"


def derive_tradable_date_from_coverage(row: dict[str, Any]) -> str:
    dates = [_parse_date(row.get("earnings_8k_filing_date")), _parse_date(row.get("periodic_filing_date"))]
    valid = [item for item in dates if item is not None]
    if not valid:
        return ""
    return _next_weekday(max(valid)).isoformat()


def materialize_companyfacts_fallbacks(
    *,
    universe_rows: list[dict[str, Any]],
    companyfacts_root: Path,
    fallback_root: Path | None = None,
) -> dict[str, Any]:
    companyfacts_root.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    missing: list[str] = []
    for row in universe_rows:
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper()
        cik10 = _cik10(row.get("cik"))
        if not ticker or not cik10:
            continue
        live_path = companyfacts_root / f"CIK{cik10}.json"
        if live_path.exists():
            continue
        fallback_path = _fallback_facts_path(ticker, fallback_root)
        if not fallback_path.exists():
            missing.append(ticker)
            continue
        payload = fallback_path.read_text(encoding="utf-8")
        write_text_atomic(live_path, payload)
        copied.append(ticker)
    return {
        "companyfacts_fallback_copied_count": len(copied),
        "companyfacts_fallback_missing_count": len(missing),
        "companyfacts_fallback_copied_tickers": copied[:50],
        "companyfacts_fallback_missing_tickers": missing[:50],
        "companyfacts_fallback_root": str(fallback_root or sec_cache_root()),
    }


def build_pre_llm_from_companyfacts_cache(
    *,
    universe_rows: list[dict[str, Any]],
    companyfacts_root: Path,
    quarter: str,
    fallback_root: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    input_rows: list[dict[str, Any]] = []
    cached = 0
    fallback_cached = 0
    for row in universe_rows:
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper()
        cik10 = _cik10(row.get("cik"))
        facts_path = companyfacts_root / f"CIK{cik10}.json" if cik10 else None
        facts_input: dict[str, Any] = {"ticker": ticker, "quarter": quarter}
        if facts_path and not facts_path.exists() and ticker:
            fallback_path = _fallback_facts_path(ticker, fallback_root)
            if fallback_path.exists():
                companyfacts_root.mkdir(parents=True, exist_ok=True)
                write_text_atomic(facts_path, fallback_path.read_text(encoding="utf-8"))
                fallback_cached += 1
        if facts_path and facts_path.exists():
            cached += 1
            companyfacts = json.loads(facts_path.read_text(encoding="utf-8"))
            if _has_pit_financial_context(row):
                facts_input.update(_pit_companyfacts_to_pre_llm_input(companyfacts, row={**row, "ticker": ticker, "quarter": quarter}))
            else:
                facts_input.update(
                    companyfacts_to_pre_llm_input(
                        companyfacts,
                        ticker=ticker,
                        quarter=quarter,
                    )
                )
        input_rows.append({**row, **facts_input, "ticker": ticker, "quarter": quarter})

    scored = build_pre_llm_rows(input_rows)
    summary = {
        "universe_rows": len(universe_rows),
        "companyfacts_cached": cached,
        "companyfacts_fallback_cached": fallback_cached,
        "pre_llm_scored": sum(1 for row in scored if row.get("pre_llm_fundamental_bucket") != "not_scored"),
        "pre_llm_not_scored": sum(1 for row in scored if row.get("pre_llm_fundamental_bucket") == "not_scored"),
    }
    return scored, summary


def _has_pit_financial_context(row: dict[str, Any]) -> bool:
    return clean(row.get("periodic_accession")) or clean(row.get("target_period_end")) or clean(row.get("periodic_filing_date"))


def _pit_companyfacts_to_pre_llm_input(companyfacts: dict[str, Any], *, row: dict[str, Any]) -> dict[str, Any]:
    context = dict(row)
    if not clean(context.get("target_period_end")):
        context.update(
            derive_period_context(
                companyfacts,
                periodic_accession=context.get("periodic_accession", ""),
                periodic_form=context.get("periodic_form", ""),
                periodic_filing_date=context.get("periodic_filing_date", ""),
            )
        )
    source_available_date = context.get("source_available_date") or _latest_date(
        context.get("earnings_8k_filing_date"),
        context.get("periodic_filing_date"),
    )
    context["source_available_date"] = source_available_date
    context["financial_cutoff_date"] = context.get("financial_cutoff_date") or source_available_date
    context["decision_date"] = context.get("decision_date") or source_available_date
    contract = build_row_contract(context, decision_date_rule=str(context.get("decision_date_rule") or "full_evidence"))
    selected = select_pit_financials(companyfacts, contract, fields=FIELD_CONCEPTS)
    missing_fields = [field for field in FIELD_CONCEPTS if not clean(selected.get(field))]
    if missing_fields:
        selected["score_input_quarantine_reason"] = _append_reason(
            selected.get("score_input_quarantine_reason"),
            "missing_pit_financial_provenance",
        )
        selected["pit_financial_missing_fields"] = ";".join(missing_fields)
    return selected


def _latest_date(*values: Any) -> str:
    parsed = sorted(item.isoformat() for item in (_parse_date(value) for value in values) if item is not None)
    return parsed[-1] if parsed else ""


def _append_reason(existing: Any, reason: str) -> str:
    reasons = {item for item in str(existing or "").split(";") if item}
    reasons.add(reason)
    return ";".join(sorted(reasons))


def split_score_ready_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    ready: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    for row in rows:
        reasons: list[str] = []
        if not clean(row.get("tradable_date")):
            reasons.append("missing_tradable_date")
        if not clean(row.get("entry_open")):
            reasons.append("missing_entry_open")
        if not clean(row.get("periodic_accession")) or not clean(row.get("periodic_primary_document")):
            reasons.append("missing_quarterly_filing")
        if clean(row.get("pre_llm_fundamental_bucket")) == "not_scored" or not clean(row.get("pre_llm_fundamental_score")):
            reasons.append("missing_fundamental_score_inputs")
        if not clean(row.get("revenue_bucket")):
            reasons.append("missing_revenue_bucket")
        if reasons:
            quarantine.append({**row, "score_input_quarantine_reason": ";".join(sorted(set(reasons)))})
        else:
            ready.append(row)
    return ready, quarantine, {"score_input_ready": len(ready), "score_input_quarantine_count": len(quarantine)}


def attach_entry_prices(
    rows: list[dict[str, Any]],
    *,
    as_of: str,
    price_provider: Callable[..., list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    needs = [row for row in rows if clean(row.get("ticker")) and clean(row.get("tradable_date")) and not clean(row.get("entry_open"))]
    tickers = sorted({str(row["ticker"]).upper() for row in needs})
    dates = [str(row["tradable_date"]) for row in needs]
    required_start_by_ticker: dict[str, str] = {}
    for row in needs:
        ticker = str(row["ticker"]).upper()
        tradable_date = str(row["tradable_date"])
        if ticker not in required_start_by_ticker or tradable_date < required_start_by_ticker[ticker]:
            required_start_by_ticker[ticker] = tradable_date
    # Yahoo-style providers treat end as exclusive; request one extra calendar day so as_of opens are available.
    end_exclusive = (date.fromisoformat(as_of) + timedelta(days=1)).isoformat()
    if tickers and dates:
        kwargs = {"start": min(dates), "end": end_exclusive}
        if _accepts_required_start_by_ticker(price_provider):
            kwargs["required_start_by_ticker"] = required_start_by_ticker
        price_rows = price_provider(tickers, **kwargs)
    else:
        price_rows = []
    rows_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for item in price_rows:
        ticker = str(item.get("ticker", "")).upper()
        if ticker:
            rows_by_ticker.setdefault(ticker, []).append(item)
    for ticker_rows in rows_by_ticker.values():
        ticker_rows.sort(key=lambda item: str(item.get("date", "")))
    output: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    for row in rows:
        out = dict(row)
        if clean(out.get("tradable_date")) and not clean(out.get("entry_open")):
            ticker = str(out.get("ticker", "")).upper()
            tradable_date = str(out.get("tradable_date", ""))
            match = next(
                (
                    item for item in rows_by_ticker.get(ticker, [])
                    if tradable_date <= str(item.get("date", "")) <= as_of
                    and clean(item.get("open"))
                ),
                None,
            )
            if match is not None:
                out["entry_open"] = match.get("open")
                out["entry_open_date"] = match.get("date", tradable_date)
                out["entry_open_source"] = "price_provider_open"
        if not clean(out.get("entry_open")):
            quarantine.append({"ticker": out.get("ticker", ""), "quarter": out.get("quarter", ""), "quarantine_reason": "missing_entry_open"})
        output.append(out)
    summary = {"rows": len(rows), "entry_open_ready": len(rows) - len(quarantine), "missing_entry_open": len(quarantine)}
    return output, quarantine, summary


def _accepts_required_start_by_ticker(price_provider: Callable[..., list[dict[str, Any]]]) -> bool:
    try:
        parameters = inspect.signature(price_provider).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD or parameter.name == "required_start_by_ticker"
        for parameter in parameters
    )
