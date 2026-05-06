"""Historical 13F fetch + quarter-over-quarter delta builder."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .ingest import (
    DEFAULT_HEADERS,
    discover_13f_filings,
    fetch_13f_holding_rows,
    fetch_submissions,
    load_manager_seed,
    read_normalized_holdings,
    write_normalized_holdings,
)


def fetch_historical_13f_holdings(
    *,
    manager_seed_path: Path | str | None = None,
    out_path: Path | str = Path("eval_results/13f/holdings_raw.csv"),
    cusip_ticker_map: Optional[Dict[str, str]] = None,
    start_report_date: str = "",
    end_report_date: str = "",
    max_filings_per_manager: int = 0,
    sleep_seconds: float = 0.12,
    headers: Optional[Dict[str, str]] = None,
    cache_dir: Path | str | None = Path("eval_results/13f/cache/sec"),
) -> Dict[str, Any]:
    """Fetch historical 13F holdings for seeded managers.

    Returns a manifest. Rows are raw normalized holdings at filing level; deltas
    are added by build_13f_deltas().
    """
    managers = load_manager_seed(manager_seed_path)
    all_rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    headers = headers or DEFAULT_HEADERS

    for manager in managers:
        try:
            try:
                submissions = fetch_submissions(str(manager.get("manager_cik", "")), headers=headers, cache_dir=cache_dir)
            except TypeError:
                submissions = fetch_submissions(str(manager.get("manager_cik", "")), headers=headers)
            filings = discover_13f_filings(submissions, manager=manager)
            filings = _filter_filings(filings, start_report_date=start_report_date, end_report_date=end_report_date)
            if max_filings_per_manager > 0:
                filings = filings[-max_filings_per_manager:]
        except Exception as exc:
            errors.append({"manager_id": manager.get("manager_id"), "stage": "submissions", "error": str(exc)})
            continue
        for filing in filings:
            try:
                try:
                    rows = fetch_13f_holding_rows(
                        manager=manager,
                        filing=filing,
                        cusip_ticker_map=cusip_ticker_map,
                        headers=headers,
                        cache_dir=cache_dir,
                    )
                except TypeError:
                    rows = fetch_13f_holding_rows(
                        manager=manager,
                        filing=filing,
                        cusip_ticker_map=cusip_ticker_map,
                        headers=headers,
                    )
                all_rows.extend(rows)
                if sleep_seconds > 0:
                    time.sleep(float(sleep_seconds))
            except Exception as exc:
                errors.append({
                    "manager_id": manager.get("manager_id"),
                    "accession": filing.get("accession"),
                    "stage": "holding_rows",
                    "error": str(exc),
                })

    out = write_normalized_holdings(out_path, all_rows)
    manifest = {
        "manager_count": len(managers),
        "row_count": len(all_rows),
        "out_path": str(out),
        "errors": errors,
        "start_report_date": start_report_date,
        "end_report_date": end_report_date,
        "max_filings_per_manager": max_filings_per_manager,
        "cache_dir": str(cache_dir) if cache_dir else "",
    }
    Path(out).with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def build_13f_deltas(
    *,
    holdings_path: Path | str,
    out_path: Path | str = Path("eval_results/13f/holdings_delta.csv"),
    min_value_usd: float = 0.0,
    resolved_only: bool = True,
) -> Dict[str, Any]:
    """Build quarter-over-quarter deltas by manager+ticker from holdings rows."""
    rows = read_normalized_holdings(holdings_path)
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        ticker = str(row.get("ticker", "")).upper().strip()
        if resolved_only and not ticker:
            continue
        value = _to_float(row.get("market_value")) or 0.0
        if value < min_value_usd:
            continue
        filtered.append({**row, "ticker": ticker, "market_value": value, "shares": _to_float(row.get("shares")) or 0.0})

    aggregated = _aggregate_filing_holdings(filtered)

    delta_rows = _build_manager_panel_deltas(aggregated)

    out = write_normalized_holdings(out_path, delta_rows)
    manifest = {
        "holdings_path": str(holdings_path),
        "out_path": str(out),
        "input_rows": len(rows),
        "filtered_rows": len(filtered),
        "aggregated_rows": len(aggregated),
        "delta_rows": len(delta_rows),
        "min_value_usd": float(min_value_usd),
        "resolved_only": bool(resolved_only),
    }
    Path(out).with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def _build_manager_panel_deltas(aggregated: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_manager_date: Dict[str, Dict[tuple[str, str], Dict[str, Dict[str, Any]]]] = defaultdict(lambda: defaultdict(dict))
    for row in aggregated:
        manager_id = str(row.get("manager_id", ""))
        report_date = str(row.get("report_date", ""))
        filing_date = str(row.get("filing_date", ""))
        security_key = str(row.get("ticker") or row.get("cusip") or "").upper().strip()
        if manager_id and report_date and security_key:
            by_manager_date[manager_id][(report_date, filing_date)][security_key] = row

    out: List[Dict[str, Any]] = []
    for manager_id, date_map in by_manager_date.items():
        ordered_dates = sorted(date_map.keys())
        prev_holdings: Dict[str, Dict[str, Any]] = {}
        for date_index, date_key in enumerate(ordered_dates):
            current = date_map[date_key]
            security_keys = sorted(set(prev_holdings) | set(current))
            for security_key in security_keys:
                row = dict(current.get(security_key) or prev_holdings.get(security_key) or {})
                if security_key not in current:
                    row = dict(row)
                    row["report_date"], row["filing_date"] = date_key
                    row["shares"] = 0.0
                    row["market_value"] = 0.0
                    row["source_row_count"] = 0
                prev = prev_holdings.get(security_key)
                prev_shares = _to_float(prev.get("shares")) if prev else 0.0
                prev_value = _to_float(prev.get("market_value")) if prev else 0.0
                shares = _to_float(row.get("shares")) or 0.0
                value = _to_float(row.get("market_value")) or 0.0
                out.append({
                    **row,
                    "previous_shares": prev_shares,
                    "previous_market_value": prev_value,
                    "delta_shares": shares - (prev_shares or 0.0),
                    "delta_market_value": value - (prev_value or 0.0),
                    "is_initial_observation": bool(date_index == 0 and prev is None),
                    "is_new_position": bool(date_index > 0 and (prev_shares or 0.0) <= 0 and shares > 0),
                    "is_add": bool(prev is not None and shares > (prev_shares or 0.0)),
                    "is_reduce": bool(prev is not None and 0 < shares < (prev_shares or 0.0)),
                    "is_exit": bool(prev is not None and (prev_shares or 0.0) > 0 and shares <= 0),
                })
            prev_holdings = {k: v for k, v in current.items() if (_to_float(v.get("shares")) or 0.0) > 0}
    return sorted(out, key=lambda row: (str(row.get("manager_id", "")), str(row.get("report_date", "")), str(row.get("ticker") or row.get("cusip") or "")))


def _aggregate_filing_holdings(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[str, str, str, str], Dict[str, Any]] = {}
    for row in rows:
        security_key = str(row.get("ticker") or row.get("cusip") or "").upper().strip()
        key = (
            str(row.get("manager_id", "")),
            str(row.get("report_date", "")),
            str(row.get("filing_date", "")),
            security_key,
        )
        if key not in grouped:
            grouped[key] = dict(row)
            grouped[key]["shares"] = 0.0
            grouped[key]["market_value"] = 0.0
            grouped[key]["source_row_count"] = 0
        grouped[key]["shares"] += _to_float(row.get("shares")) or 0.0
        grouped[key]["market_value"] += _to_float(row.get("market_value")) or 0.0
        grouped[key]["source_row_count"] += 1
    return sorted(grouped.values(), key=lambda row: (str(row.get("manager_id", "")), str(row.get("report_date", "")), str(row.get("ticker") or row.get("cusip") or "")))


def _filter_filings(filings: Iterable[Dict[str, Any]], *, start_report_date: str, end_report_date: str) -> List[Dict[str, Any]]:
    rows = []
    for filing in filings:
        report_date = str(filing.get("report_date", ""))
        if start_report_date and report_date < start_report_date:
            continue
        if end_report_date and report_date > end_report_date:
            continue
        rows.append(filing)
    return rows


def _to_float(raw: Any) -> Optional[float]:
    try:
        if raw in {None, ""}:
            return None
        return float(raw)
    except Exception:
        return None
