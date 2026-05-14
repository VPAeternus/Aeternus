from __future__ import annotations

import json
import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from tradingagents.research.fundamental.src.features.pre_llm_scores import build_pre_llm_rows
from tradingagents.research.fundamental.src.ingest.xbrl import companyfacts_to_pre_llm_input

from .artifacts import write_csv, write_json_atomic


RAW_PRICE_FIELDS = ("open", "high", "low", "close", "volume")
YAHOO_PRICE_FIELDS = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}


@dataclass
class ReviewListFilterResult:
    rows: list[dict[str, Any]]
    rejected_rows: list[dict[str, Any]]
    pending_rows: list[dict[str, Any]]
    summary: dict[str, Any]
    artifacts: dict[str, str]


def _ticker(value: Any) -> str:
    return str(value or "").upper().replace(".", "-").strip()


def _cik(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(int(float(text)))
    except ValueError:
        return text


def _to_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_sec_ticker_map_rows(path: Path, *, quarter: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, Mapping) and isinstance(payload.get("items"), list):
        raw_items = payload["items"]
    elif isinstance(payload, Mapping):
        raw_items = payload.values()
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raise ValueError("SEC ticker map must be a JSON object or list")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        ticker = _ticker(item.get("ticker") or item.get("symbol"))
        cik = _cik(item.get("cik_str") or item.get("cik"))
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        rows.append(
            {
                "ticker": ticker,
                "symbol": ticker,
                "cik": cik,
                "company_title": str(item.get("title") or item.get("company_title") or "").strip(),
                "cik_status": "resolved" if cik else "missing",
                "quarter": quarter,
                "stock_source_type": "sec_ticker_map",
            }
        )
    return sorted(rows, key=lambda row: row["ticker"])


def write_sec_universe_inputs(rows: list[Mapping[str, Any]], *, output_root: Path, quarter: str) -> dict[str, str]:
    csv_path = output_root / f"sec_universe_{quarter}.csv"
    json_path = output_root / f"sec_universe_{quarter}.json"
    write_csv(csv_path, rows)
    write_json_atomic(json_path, {"items": [dict(row) for row in rows], "source": "sec_company_tickers", "quarter": quarter})
    return {"sec_universe_csv": str(csv_path), "sec_universe_json": str(json_path)}


def _cache_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if not path:
            continue
        expanded = path.expanduser()
        if expanded.is_file() and expanded.suffix.lower() == ".parquet":
            files.append(expanded)
        elif expanded.is_dir():
            files.extend(sorted(expanded.glob("prices*.parquet")))
            files.extend(sorted(expanded.glob("review_price_cache*.parquet")))
            files.extend(sorted(expanded.glob("**/price_history.parquet")))
    seen: set[Path] = set()
    deduped: list[Path] = []
    for path in files:
        resolved = path.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    return deduped


def _date_text(value: Any) -> str:
    try:
        import pandas as pd

        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except Exception:
        return str(value)[:10]


def _wide_cache_rows(frame: Any, *, wanted: set[str], start: str, end: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    available = {str(item).upper() for item in frame.columns.get_level_values(0).unique()}
    for ticker in sorted(wanted & available):
        panel = frame[ticker].rename(columns=YAHOO_PRICE_FIELDS)
        needed = [field for field in RAW_PRICE_FIELDS if field in panel.columns]
        if len(needed) != len(RAW_PRICE_FIELDS):
            continue
        for date_value, values in panel.iterrows():
            date_text = _date_text(date_value)
            if date_text < start or date_text >= end:
                continue
            row = {"ticker": ticker, "date": date_text}
            missing = False
            for field in RAW_PRICE_FIELDS:
                value = _to_float(values.get(field))
                if value is None:
                    missing = True
                    break
                row[field] = value
            if not missing:
                row["dollar_volume"] = row["close"] * row["volume"]
                rows.append(row)
    return rows


def _narrow_cache_rows(frame: Any, *, wanted: set[str], start: str, end: str) -> list[dict[str, Any]]:
    columns = {str(col).lower(): col for col in frame.columns}
    if "ticker" not in columns or "date" not in columns:
        return []
    required = [field for field in RAW_PRICE_FIELDS if field in columns]
    if len(required) != len(RAW_PRICE_FIELDS):
        return []
    rows: list[dict[str, Any]] = []
    for _, values in frame.iterrows():
        ticker = _ticker(values.get(columns["ticker"]))
        if ticker not in wanted:
            continue
        date_text = _date_text(values.get(columns["date"]))
        if date_text < start or date_text >= end:
            continue
        row = {"ticker": ticker, "date": date_text}
        missing = False
        for field in RAW_PRICE_FIELDS:
            value = _to_float(values.get(columns[field]))
            if value is None:
                missing = True
                break
            row[field] = value
        if not missing:
            row["dollar_volume"] = row["close"] * row["volume"]
            rows.append(row)
    return rows


def _parquet_columns_for_wanted(path: Path, wanted: set[str]) -> list[str] | None:
    try:
        import pyarrow.parquet as pq
    except Exception:
        return None
    try:
        names = pq.ParquetFile(path).schema.names
    except Exception:
        return None
    available: dict[str, set[str]] = {}
    saw_wide_columns = False
    for name in names:
        try:
            first, second = ast.literal_eval(name)
        except Exception:
            continue
        saw_wide_columns = True
        ticker = str(first).upper()
        field = str(second)
        if ticker in wanted and field in YAHOO_PRICE_FIELDS:
            available.setdefault(ticker, set()).add(field)
    selected: list[str] = []
    for ticker, fields in available.items():
        if set(YAHOO_PRICE_FIELDS) - fields:
            continue
        selected.extend([f"('{ticker}', '{field}')" for field in YAHOO_PRICE_FIELDS])
    if not selected and saw_wide_columns:
        return []
    if not selected:
        return None
    if "Date" in names:
        selected.append("Date")
    return selected


def _parquet_columns_for_narrow(path: Path) -> list[str] | None:
    try:
        import pyarrow.parquet as pq
    except Exception:
        return None
    try:
        names = pq.ParquetFile(path).schema.names
    except Exception:
        return None
    lowered = {name.lower(): name for name in names}
    wanted = ["ticker", "date", *RAW_PRICE_FIELDS]
    if not all(name in lowered for name in wanted):
        return None
    return [lowered[name] for name in wanted]


def load_cached_review_price_rows(paths: Iterable[Path], *, tickers: list[str], start: str, end: str) -> list[dict[str, Any]]:
    try:
        import pandas as pd
    except Exception:
        return []
    wanted = {_ticker(ticker) for ticker in tickers if _ticker(ticker)}
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for path in _cache_files(paths):
        columns = _parquet_columns_for_wanted(path, wanted)
        if columns == []:
            continue
        if columns is None:
            columns = _parquet_columns_for_narrow(path)
        try:
            frame = pd.read_parquet(path, columns=columns) if columns else pd.read_parquet(path)
        except Exception:
            continue
        if isinstance(frame.columns, pd.MultiIndex):
            rows = _wide_cache_rows(frame, wanted=wanted, start=start, end=end)
        else:
            rows = _narrow_cache_rows(frame, wanted=wanted, start=start, end=end)
        for row in rows:
            by_key[(row["ticker"], row["date"])] = row
    return [by_key[key] for key in sorted(by_key)]


def store_review_price_rows(rows: list[Mapping[str, Any]], *, output_root: Path, quarter: str, as_of: str) -> Path:
    try:
        import pandas as pd
    except Exception as exc:
        raise RuntimeError("pandas is required to store review price cache") from exc
    path = output_root / f"review_price_cache_{quarter}_{as_of}.parquet"
    materialized: list[dict[str, Any]] = []
    for row in rows:
        ticker = _ticker(row.get("ticker"))
        date_text = _date_text(row.get("date"))
        if not ticker or not date_text:
            continue
        out = {"ticker": ticker, "date": date_text}
        missing = False
        for field in RAW_PRICE_FIELDS:
            value = _to_float(row.get(field))
            if value is None:
                missing = True
                break
            out[field] = value
        if not missing:
            out["dollar_volume"] = out["close"] * out["volume"]
            materialized.append(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(materialized).to_parquet(path, index=False)
    return path


def _coverage_reason(row: Mapping[str, Any] | None) -> str:
    if not row:
        return "sec_coverage_not_ready"
    if str(row.get("coverage_status", "")).upper() != "CACHED_READY":
        return "sec_coverage_not_ready"
    if not row.get("earnings_8k_accession") or not row.get("earnings_8k_primary_document"):
        return "missing_earnings_8k"
    if not row.get("earnings_exhibit_document"):
        return "missing_press_release_exhibit"
    if not row.get("periodic_accession") or not row.get("periodic_form") or not row.get("periodic_primary_document"):
        return "missing_periodic_10q_10k"
    if str(row.get("missing_inputs", "")).strip():
        return "sec_coverage_not_ready"
    return ""


def _pending_reason_from_coverage(row: Mapping[str, Any] | None) -> str:
    if not row:
        return "needs_sec_fetch"
    missing = {item for item in str(row.get("missing_inputs", "")).split(";") if item}
    status = str(row.get("coverage_status", "")).upper()
    if missing & {"submissions", "companyfacts", "10q_10k_metadata", "historical_submission_files"}:
        return "needs_sec_fetch"
    if status == "NEEDS_FETCH" or missing & {"archive_index", "primary_8k_document", "earnings_exhibit_document", "periodic_10q_10k_document"}:
        return "needs_document_fetch"
    return ""


def _companyfacts_ready(row: Mapping[str, Any], *, companyfacts_root: Path | None, quarter: str) -> bool:
    if companyfacts_root is None:
        return True
    cik = _cik(row.get("cik"))
    if not cik:
        return False
    facts_path = companyfacts_root / f"CIK{cik.zfill(10)}.json"
    if not facts_path.exists():
        return False
    try:
        facts_input = companyfacts_to_pre_llm_input(
            json.loads(facts_path.read_text(encoding="utf-8")),
            ticker=str(row.get("ticker", "")).upper(),
            quarter=quarter,
        )
        scored = build_pre_llm_rows([{**dict(row), **facts_input, "quarter": quarter}])
    except Exception:
        return False
    if not scored:
        return False
    scored_row = scored[0]
    return (
        str(scored_row.get("pre_llm_fundamental_bucket", "")).strip() != "not_scored"
        and bool(str(scored_row.get("pre_llm_fundamental_score", "")).strip())
        and bool(str(scored_row.get("revenue_bucket", "")).strip())
    )


def _price_stats(
    ticker: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: str,
    min_close: float,
    min_adv60: float,
) -> tuple[str, dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for raw in rows:
        normalized = {str(key).lower(): value for key, value in raw.items()}
        if str(normalized.get("date", "")) > as_of:
            continue
        if not all(_to_float(normalized.get(field)) is not None for field in RAW_PRICE_FIELDS):
            continue
        cleaned.append(normalized)
    cleaned.sort(key=lambda row: str(row.get("date", "")))
    if not cleaned:
        return "raw_yahoo_ohlcv_missing", {}
    if len(cleaned) < 60:
        return "adv60_not_available", {"price_last_date": cleaned[-1].get("date", ""), "adv60_window_days": len(cleaned)}
    latest = cleaned[-1]
    latest_close = _to_float(latest.get("close"))
    if latest_close is None:
        return "raw_yahoo_ohlcv_missing", {}
    last_60 = cleaned[-60:]
    adv60 = sum(float(row["volume"]) for row in last_60) / 60
    stats = {
        "price_last_date": latest.get("date", ""),
        "raw_close": latest_close,
        "adv60": adv60,
        "adv60_window_days": 60,
    }
    if latest_close < min_close:
        return f"raw_close_below_{int(min_close) if min_close.is_integer() else min_close}", stats
    if adv60 < min_adv60:
        return f"adv60_below_{int(min_adv60)}", stats
    return "", stats


def filter_review_list_rows(
    *,
    candidate_rows: list[Mapping[str, Any]],
    coverage_rows: list[Mapping[str, Any]],
    price_rows: list[Mapping[str, Any]],
    companyfacts_root: Path | None,
    quarter: str,
    as_of: str,
    output_root: Path,
    min_close: float = 2.0,
    min_adv60: float = 500_000.0,
    sec_fetch_attempted: bool = True,
    price_fetch_attempted: bool = True,
) -> ReviewListFilterResult:
    coverage_by_ticker = {_ticker(row.get("ticker")): dict(row) for row in coverage_rows}
    price_by_ticker: dict[str, list[Mapping[str, Any]]] = {}
    for row in price_rows:
        ticker = _ticker(row.get("ticker"))
        if ticker:
            price_by_ticker.setdefault(ticker, []).append(row)

    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for item in candidate_rows:
        base = dict(item)
        ticker = _ticker(base.get("ticker") or base.get("symbol"))
        if not ticker:
            continue
        base.update({"ticker": ticker, "symbol": ticker, "quarter": quarter})
        coverage = coverage_by_ticker.get(ticker)
        reason = _coverage_reason(coverage)
        pending_reason = ""
        if reason == "sec_coverage_not_ready":
            pending_reason = _pending_reason_from_coverage(coverage)
            if pending_reason and not sec_fetch_attempted:
                reason = ""
        stats: dict[str, Any] = {}
        if not reason and not pending_reason and not _companyfacts_ready(base, companyfacts_root=companyfacts_root, quarter=quarter):
            reason = "missing_core_fundamental_data"
        if not reason and not pending_reason:
            reason, stats = _price_stats(ticker, price_by_ticker.get(ticker, []), as_of=as_of, min_close=min_close, min_adv60=min_adv60)
            if reason in {"raw_yahoo_ohlcv_missing", "adv60_not_available"} and not price_fetch_attempted:
                pending_reason = "needs_price_fetch"
                reason = ""
        output = {**base, **(coverage or {}), **stats}
        if pending_reason:
            pending.append({**output, "pending_reason": pending_reason})
        elif reason:
            rejected.append({**output, "rejection_reason": reason})
        else:
            kept.append(
                {
                    **output,
                    "cik_status": output.get("cik_status") or ("resolved" if output.get("cik") else "missing"),
                    "stock_source_type": output.get("stock_source_type") or "sec_review_filter",
                }
            )

    reason_counts = Counter(row["rejection_reason"] for row in rejected)
    pending_counts = Counter(row["pending_reason"] for row in pending)
    summary = {
        "sec_universe_count": len(candidate_rows),
        "kept_count": len(kept),
        "rejected_count": len(rejected),
        "pending_count": len(pending),
        "rejection_reason_counts": dict(sorted(reason_counts.items())),
        "pending_reason_counts": dict(sorted(pending_counts.items())),
        "min_raw_close": min_close,
        "min_adv60": min_adv60,
        "rule": "SEC evidence + core company data + raw Yahoo OHLCV + raw close >= 2 + ADV60 >= 500k",
    }
    review_csv = output_root / f"review_stock_list_{quarter}.csv"
    review_json = output_root / f"review_stock_list_{quarter}.json"
    rejected_csv = output_root / f"review_stock_list_rejections_{quarter}.csv"
    pending_csv = output_root / f"review_stock_list_pending_{quarter}.csv"
    summary_json = output_root / f"review_stock_list_summary_{quarter}.json"
    write_csv(review_csv, kept)
    write_json_atomic(review_json, {"items": kept, "source": "sec_review_filter", "quarter": quarter, "summary": summary})
    write_csv(rejected_csv, rejected)
    write_csv(pending_csv, pending)
    write_json_atomic(summary_json, summary)
    return ReviewListFilterResult(
        kept,
        rejected,
        pending,
        summary,
        {
            "review_stock_list_csv": str(review_csv),
            "review_stock_list_json": str(review_json),
            "review_stock_list_rejections_csv": str(rejected_csv),
            "review_stock_list_pending_csv": str(pending_csv),
            "review_stock_list_summary_json": str(summary_json),
        },
    )


def fetch_review_price_rows(
    tickers: list[str],
    *,
    start: str,
    end: str,
    price_provider: Callable[..., list[dict[str, Any]]],
    batch_size: int = 200,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx in range(0, len(tickers), max(1, batch_size)):
        batch = tickers[idx : idx + max(1, batch_size)]
        rows.extend(price_provider(batch, start=start, end=end))
    return rows
