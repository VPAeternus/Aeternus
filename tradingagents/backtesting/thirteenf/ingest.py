"""13F ingestion helpers.

Small first slice: manager seed loading, SEC submissions discovery, and normalized
placeholder/persist helpers. Full infotable XML parsing and CUSIP mapping can plug
into the normalized schema used by core.py.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd
import requests

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVE_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
SEC_ARCHIVE_FILE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{filename}"
DEFAULT_HEADERS = {"User-Agent": "Aeternus Research contact@aeternus.local"}
DEFAULT_SEC_CACHE_DIR = Path("eval_results/13f/cache/sec")


def load_manager_seed(path: Path | str | None = None) -> List[Dict[str, Any]]:
    seed_path = Path(path) if path else Path(__file__).with_name("managers_seed.json")
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("manager seed must be a list")
    rows = []
    for raw in payload:
        cik = normalize_cik(raw.get("manager_cik") or raw.get("cik"))
        if not cik:
            continue
        rows.append({**raw, "manager_cik": cik, "manager_id": str(raw.get("manager_id") or cik)})
    return rows


def normalize_cik(raw: Any) -> str:
    text = str(raw or "").strip().lstrip("0")
    if not text.isdigit():
        return ""
    return text.zfill(10)


def fetch_submissions(cik: str, *, headers: Dict[str, str] | None = None, timeout: float = 30.0, cache_dir: Path | str | None = DEFAULT_SEC_CACHE_DIR) -> Dict[str, Any]:
    cik_norm = normalize_cik(cik)
    cache_path = _cache_path(cache_dir, "submissions", f"CIK{cik_norm}.json")
    if cache_path and cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    url = SEC_SUBMISSIONS_URL.format(cik=cik_norm)
    resp = requests.get(url, headers=headers or DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    out = payload if isinstance(payload, dict) else {}
    if cache_path:
        _write_text(cache_path, json.dumps(out, indent=2))
    return out


def discover_13f_filings(submissions: Dict[str, Any], *, manager: Dict[str, Any]) -> List[Dict[str, Any]]:
    recent = dict((submissions.get("filings") or {}).get("recent") or {})
    forms = list(recent.get("form", []) or [])
    accession_numbers = list(recent.get("accessionNumber", []) or [])
    filing_dates = list(recent.get("filingDate", []) or [])
    report_dates = list(recent.get("reportDate", []) or [])
    primary_docs = list(recent.get("primaryDocument", []) or [])
    rows: List[Dict[str, Any]] = []
    for idx, form in enumerate(forms):
        if str(form).upper() not in {"13F-HR", "13F-HR/A"}:
            continue
        accession = accession_numbers[idx] if idx < len(accession_numbers) else ""
        rows.append(
            {
                "manager_id": manager.get("manager_id"),
                "manager_name": manager.get("manager_name"),
                "manager_cik": manager.get("manager_cik"),
                "form": form,
                "accession": accession,
                "filing_date": filing_dates[idx] if idx < len(filing_dates) else "",
                "report_date": report_dates[idx] if idx < len(report_dates) else "",
                "primary_document": primary_docs[idx] if idx < len(primary_docs) else "",
            }
        )
    return sorted(rows, key=lambda row: row.get("filing_date", ""))


def fetch_archive_index(cik: str, accession: str, *, headers: Dict[str, str] | None = None, timeout: float = 30.0, cache_dir: Path | str | None = DEFAULT_SEC_CACHE_DIR) -> Dict[str, Any]:
    cik_int = str(int(normalize_cik(cik)))
    accession_clean = str(accession).replace("-", "")
    cache_path = _cache_path(cache_dir, "archives", cik_int, accession_clean, "index.json")
    if cache_path and cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    url = SEC_ARCHIVE_INDEX_URL.format(cik=cik_int, accession=accession_clean)
    resp = requests.get(url, headers=headers or DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    out = payload if isinstance(payload, dict) else {}
    if cache_path:
        _write_text(cache_path, json.dumps(out, indent=2))
    return out


def info_table_filenames(index_payload: Dict[str, Any]) -> List[str]:
    items = ((index_payload.get("directory") or {}).get("item") or [])
    names: List[str] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        lower = name.lower()
        if not lower.endswith(".xml"):
            continue
        if lower.startswith("xsl") or "primary_doc" in lower or "filingsummary" in lower:
            continue
        names.append(name)
    return names


def fetch_archive_file(cik: str, accession: str, filename: str, *, headers: Dict[str, str] | None = None, timeout: float = 30.0, cache_dir: Path | str | None = DEFAULT_SEC_CACHE_DIR) -> str:
    cik_int = str(int(normalize_cik(cik)))
    accession_clean = str(accession).replace("-", "")
    cache_path = _cache_path(cache_dir, "archives", cik_int, accession_clean, filename)
    if cache_path and cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="ignore")
    url = SEC_ARCHIVE_FILE_URL.format(cik=cik_int, accession=accession_clean, filename=filename)
    resp = requests.get(url, headers=headers or DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    if cache_path:
        _write_text(cache_path, resp.text)
    return resp.text


def parse_info_table_xml(
    xml_text: str,
    *,
    manager: Dict[str, Any],
    filing: Dict[str, Any],
    cusip_ticker_map: Dict[str, str] | None = None,
) -> List[Dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    mapper = {str(k).upper().strip(): str(v).upper().strip() for k, v in dict(cusip_ticker_map or {}).items()}
    rows: List[Dict[str, Any]] = []
    for node in root.iter():
        if _strip_ns(node.tag) != "infoTable":
            continue
        cusip = _child_text(node, "cusip").upper().strip()
        ticker = mapper.get(cusip, "")
        rows.append(
            {
                "manager_id": manager.get("manager_id", ""),
                "manager_name": manager.get("manager_name", ""),
                "manager_cik": manager.get("manager_cik", ""),
                "accession": filing.get("accession", ""),
                "filing_date": filing.get("filing_date", ""),
                "report_date": filing.get("report_date", ""),
                "issuer_name": _child_text(node, "nameOfIssuer"),
                "class_title": _child_text(node, "titleOfClass"),
                "cusip": cusip,
                "ticker": ticker,
                "ticker_status": "resolved" if ticker else "unresolved_cusip",
                "market_value": _to_float(_child_text(node, "value"), scale=1000.0),
                "shares": _to_float(_child_text(node, "sshPrnamt")),
                "share_type": _child_text(node, "sshPrnamtType"),
                "put_call": _child_text(node, "putCall"),
                "investment_discretion": _child_text(node, "investmentDiscretion"),
            }
        )
    return rows


def fetch_13f_holding_rows(
    *,
    manager: Dict[str, Any],
    filing: Dict[str, Any],
    cusip_ticker_map: Dict[str, str] | None = None,
    headers: Dict[str, str] | None = None,
    cache_dir: Path | str | None = DEFAULT_SEC_CACHE_DIR,
) -> List[Dict[str, Any]]:
    index_payload = fetch_archive_index(str(manager.get("manager_cik", "")), str(filing.get("accession", "")), headers=headers, cache_dir=cache_dir)
    for filename in info_table_filenames(index_payload):
        xml_text = fetch_archive_file(str(manager.get("manager_cik", "")), str(filing.get("accession", "")), filename, headers=headers, cache_dir=cache_dir)
        rows = parse_info_table_xml(xml_text, manager=manager, filing=filing, cusip_ticker_map=cusip_ticker_map)
        if rows:
            return rows
    return []


def _child_text(node: ET.Element, target: str) -> str:
    for child in node.iter():
        if _strip_ns(child.tag) == target and child.text:
            return child.text.strip()
    return ""


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _to_float(raw: Any, *, scale: float = 1.0) -> float:
    try:
        return float(str(raw).replace(",", "")) * scale
    except Exception:
        return 0.0


def _cache_path(cache_dir: Path | str | None, *parts: str) -> Path | None:
    if cache_dir is None:
        return None
    return Path(cache_dir).joinpath(*parts)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_normalized_holdings(path: Path | str, rows: Iterable[Dict[str, Any]]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(list(rows))
    if out.suffix == ".parquet":
        frame.to_parquet(out, index=False)
    else:
        frame.to_csv(out, index=False)
    return out


def read_normalized_holdings(path: Path | str) -> List[Dict[str, Any]]:
    src = Path(path)
    if src.suffix == ".parquet":
        return pd.read_parquet(src).fillna("").to_dict("records")
    return pd.read_csv(src).fillna("").to_dict("records")
