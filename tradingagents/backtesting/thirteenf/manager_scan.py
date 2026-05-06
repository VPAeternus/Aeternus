"""Broad 13F manager discovery helpers."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import requests

from .ingest import DEFAULT_HEADERS, normalize_cik

FORM_INDEX_URL = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx"


def recent_quarters(count: int, *, today: dt.date | None = None) -> List[tuple[int, int]]:
    day = today or dt.date.today()
    quarter = (day.month - 1) // 3 + 1
    year = day.year
    out: List[tuple[int, int]] = []
    while len(out) < count:
        out.append((year, quarter))
        quarter -= 1
        if quarter == 0:
            quarter = 4
            year -= 1
    return out


def fetch_form_index(year: int, quarter: int, *, cache_dir: Path | str = Path("eval_results/13f/cache/sec"), headers: Dict[str, str] | None = None) -> str:
    cache_path = Path(cache_dir) / "full-index" / str(year) / f"QTR{quarter}" / "form.idx"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="ignore")
    url = FORM_INDEX_URL.format(year=year, quarter=quarter)
    resp = requests.get(url, headers=headers or DEFAULT_HEADERS, timeout=60)
    resp.raise_for_status()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(resp.text, encoding="utf-8")
    return resp.text


def parse_13f_managers_from_form_index(text: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith(("13F-HR ", "13F-HR/A")):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        form = parts[0]
        cik, filing_date, path = parts[-3], parts[-2], parts[-1]
        name_start = len(form)
        name_end = line.find(cik, len(form))
        name = line[name_start:name_end].strip()
        accession = Path(path).stem
        rows.append({
            "manager_id": normalize_manager_id(name, cik),
            "manager_name": name,
            "manager_cik": normalize_cik(cik),
            "form": form,
            "filing_date": filing_date,
            "accession": accession,
            "source_path": path,
        })
    return rows


DEFAULT_MANAGER_QUALITY_PATH = Path(__file__).with_name("manager_quality_seed.json")

EXCLUDED_MANAGER_TERMS = (
    " bank", "bank ", "bancorp", "trust co", "trust company", "national association",
    "insurance", "assurance", "pension", "provident", "retirement", "state of",
    "treasury", "government", "ministry", "foundation", "endowment", "university",
    "securities ag", "securities llc", "broker", "clearing", "custodian",
    "wealth management", "wealth partners", "financial services", "advisors services", "private client",
    " pte", " plc", " w.l.l", " ag ", " board", "asset management inc"  # override by allowlist later if needed
)

INCLUDED_MANAGER_TERMS = (
    "capital", "partners", "investment", "investments", "management", "advisors", "adviser",
    "fund", "asset management", "family office", "lp", "llc", "l.p.", "ltd"
)


def discover_recent_13f_managers(*, quarters: int = 2, min_recent_filings: int = 1, cache_dir: Path | str = Path("eval_results/13f/cache/sec")) -> List[Dict[str, Any]]:
    by_cik: Dict[str, Dict[str, Any]] = {}
    for year, quarter in recent_quarters(quarters):
        text = fetch_form_index(year, quarter, cache_dir=cache_dir)
        for row in parse_13f_managers_from_form_index(text):
            cik = row["manager_cik"]
            item = by_cik.setdefault(cik, {
                "manager_id": row["manager_id"],
                "manager_name": row["manager_name"],
                "manager_cik": cik,
                "style": "broad_scan",
                "recent_13f_count": 0,
                "latest_filing_date": "",
            })
            item["recent_13f_count"] += 1
            item["latest_filing_date"] = max(item["latest_filing_date"], row.get("filing_date", ""))
    return sorted(
        [row for row in by_cik.values() if int(row.get("recent_13f_count", 0)) >= min_recent_filings],
        key=lambda row: (-int(row.get("recent_13f_count", 0)), str(row.get("manager_name", ""))),
    )


def load_manager_quality_rules(path: Path | str | None = None) -> Dict[str, Any]:
    rules_path = Path(path) if path else DEFAULT_MANAGER_QUALITY_PATH
    if not rules_path.exists():
        return {}
    return json.loads(rules_path.read_text(encoding="utf-8"))


def filter_proper_managers(managers: Iterable[Dict[str, Any]], *, rules: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    rules = rules or {}
    allow_terms = tuple(str(x).lower() for x in rules.get("allow_terms", INCLUDED_MANAGER_TERMS))
    deny_terms = tuple(str(x).lower() for x in rules.get("deny_terms", EXCLUDED_MANAGER_TERMS))
    allowlist_ciks = {normalize_cik(x) for x in rules.get("allowlist_ciks", [])}
    denylist_ciks = {normalize_cik(x) for x in rules.get("denylist_ciks", [])}
    out: List[Dict[str, Any]] = []
    for manager in managers:
        cik = normalize_cik(manager.get("manager_cik", ""))
        if cik in denylist_ciks:
            continue
        if cik in allowlist_ciks:
            out.append(dict(manager))
            continue
        name = f" {str(manager.get('manager_name', '')).lower()} "
        if any(term in name for term in deny_terms):
            continue
        if not any(term in name for term in allow_terms):
            continue
        out.append(dict(manager))
    return out


def manager_aum_summary(holdings: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    latest_by_manager: Dict[str, str] = {}
    rows_by_manager_date: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    for row in holdings:
        manager_id = str(row.get("manager_id", ""))
        report_date = str(row.get("report_date", ""))
        if not manager_id or not report_date:
            continue
        latest_by_manager[manager_id] = max(latest_by_manager.get(manager_id, ""), report_date)
        rows_by_manager_date.setdefault((manager_id, report_date), []).append(row)

    summary: Dict[str, Dict[str, Any]] = {}
    for manager_id, report_date in latest_by_manager.items():
        rows = rows_by_manager_date.get((manager_id, report_date), [])
        values = [_safe_float(row.get("market_value")) for row in rows]
        values = [value for value in values if value > 0]
        total = sum(values)
        top10 = sum(sorted(values, reverse=True)[:10])
        first = rows[0] if rows else {}
        summary[manager_id] = {
            "manager_id": manager_id,
            "manager_name": first.get("manager_name", ""),
            "manager_cik": first.get("manager_cik", ""),
            "latest_report_date": report_date,
            "latest_13f_aum_usd": total,
            "latest_position_count": len(values),
            "top10_concentration": (top10 / total) if total else 0.0,
        }
    return summary


def _safe_float(raw: Any) -> float:
    try:
        return float(raw)
    except Exception:
        return 0.0


def normalize_manager_id(name: str, cik: str) -> str:
    base = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name).strip())
    base = "_".join(part for part in base.split("_") if part)
    return base[:60] or normalize_cik(cik).lstrip("0")
