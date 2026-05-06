from __future__ import annotations

import gzip
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from src.config.cache_paths import sec_cache_root
from src.ingest.documents import classify_doc_quality, html_to_text


SEC_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"
SEC_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"


def next_trading_day(value: datetime | date | str) -> date:
    if isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        current = dt.date()
    elif isinstance(value, datetime):
        current = value.date()
    else:
        current = value
    current += timedelta(days=1)
    while current.weekday() >= 5:
        current += timedelta(days=1)
    return current


def compute_signal_available_datetime(*accepted_datetimes: str) -> str:
    values = [datetime.fromisoformat(item.replace("Z", "+00:00")) for item in accepted_datetimes if item]
    if not values:
        return ""
    return max(values).isoformat()


@dataclass(frozen=True)
class SecFetchConfig:
    cache_root: Path = sec_cache_root("live_sec")
    user_agent: str = "AeternusAutoResearch/1.0 contact@aeternus.local"
    timeout: int = 30
    retries: int = 3
    sleep_seconds: float = 0.12
    force: bool = False


def default_fetcher(url: str, headers: dict[str, str], timeout: int) -> bytes:
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as response:
        payload = response.read()
        if response.headers.get("Content-Encoding", "").lower() == "gzip" or payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
        return payload


class SecClient:
    def __init__(
        self,
        config: SecFetchConfig | None = None,
        *,
        fetcher: Callable[[str, dict[str, str], int], bytes] = default_fetcher,
    ) -> None:
        self.config = config or SecFetchConfig()
        self.fetcher = fetcher

    def _path(self, cache_key: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9/_.-]+", "_", cache_key).strip("/")
        return self.config.cache_root / safe

    def get_bytes(self, url: str, cache_key: str) -> bytes:
        path = self._path(cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not self.config.force:
            return path.read_bytes()
        headers = {"User-Agent": self.config.user_agent, "Accept-Encoding": "gzip, deflate"}
        last_error: Exception | None = None
        for attempt in range(1, self.config.retries + 1):
            try:
                payload = self.fetcher(url, headers, self.config.timeout)
                path.write_bytes(payload)
                if self.config.sleep_seconds:
                    time.sleep(self.config.sleep_seconds)
                return payload
            except Exception as exc:  # noqa: BLE001 - network stack raises mixed transient errors.
                last_error = exc
                if attempt < self.config.retries:
                    time.sleep(self.config.sleep_seconds * attempt)
        raise RuntimeError(f"SEC fetch failed: {url}: {last_error}") from last_error

    def get_text(self, url: str, cache_key: str) -> str:
        return self.get_bytes(url, cache_key).decode("utf-8", errors="ignore")

    def get_json(self, url: str, cache_key: str) -> dict[str, Any]:
        return json.loads(self.get_text(url, cache_key))

    def submissions(self, cik: str) -> dict[str, Any]:
        cik10 = str(cik).zfill(10)
        return self.get_json(f"{SEC_SUBMISSIONS_BASE}/CIK{cik10}.json", f"submissions/CIK{cik10}.json")

    def historical_submission_file(self, name: str) -> dict[str, Any]:
        return self.get_json(f"{SEC_SUBMISSIONS_BASE}/{name}", f"submissions/{name}")

    def archive_index(self, cik: str, accession: str) -> dict[str, Any]:
        compact = accession.replace("-", "")
        return self.get_json(
            f"{SEC_ARCHIVE_BASE}/{int(cik)}/{compact}/index.json",
            f"archive_indexes/{str(cik).zfill(10)}/{compact}.json",
        )

    def archive_document(self, ticker: str, cik: str, accession: str, document: str) -> tuple[Path, str]:
        compact = accession.replace("-", "")
        cache_key = f"documents/{ticker.upper()}_{compact}_{document}"
        text = self.get_text(f"{SEC_ARCHIVE_BASE}/{int(cik)}/{compact}/{document}", cache_key)
        return self._path(cache_key), text

    def companyfacts(self, cik: str) -> dict[str, Any]:
        cik10 = str(cik).zfill(10)
        return self.get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json", f"companyfacts/CIK{cik10}.json")


def quarter_bounds(quarter: str) -> tuple[date, date]:
    year = int(quarter[:4])
    q_num = int(quarter[-1])
    start_month = (q_num - 1) * 3 + 1
    start = date(year, start_month, 1)
    end_month = start_month + 2
    end = date(year, 12, 31) if end_month == 12 else date(year, end_month + 1, 1) - timedelta(days=1)
    return start, end


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def recent_filings(submissions: dict[str, Any]) -> list[dict[str, str]]:
    recent = submissions.get("filings", {}).get("recent", {})
    rows: list[dict[str, str]] = []
    for idx, form in enumerate(recent.get("form", [])):
        def get(name: str) -> str:
            values = recent.get(name, [])
            return str(values[idx]) if idx < len(values) and values[idx] is not None else ""

        rows.append(
            {
                "form": str(form),
                "filing_date": get("filingDate"),
                "report_date": get("reportDate"),
                "acceptance_datetime": get("acceptanceDateTime"),
                "accession": get("accessionNumber"),
                "items": get("items"),
                "primary_document": get("primaryDocument"),
            }
        )
    return rows


def all_submission_filings(client: SecClient, submissions: dict[str, Any]) -> list[dict[str, str]]:
    rows = recent_filings(submissions)
    for file_info in submissions.get("filings", {}).get("files", []) or []:
        name = str(file_info.get("name", ""))
        if not name:
            continue
        try:
            rows.extend(recent_filings({"filings": {"recent": client.historical_submission_file(name)}}))
        except Exception:
            continue
    deduped: dict[str, dict[str, str]] = {}
    for row in rows:
        key = row.get("accession") or "|".join([row.get("form", ""), row.get("filing_date", ""), row.get("primary_document", "")])
        deduped[key] = row
    return list(deduped.values())


def candidate_exhibit_documents(names: list[str]) -> list[str]:
    ignored_suffixes = (".xml", ".xsd", ".css", ".js", ".jpg", ".png", ".xlsx", ".zip", ".txt")
    ignored_tokens = ("index", "headers", "filingsummary", "metalinks", "r1")
    strong_terms = ("ex99", "exhibit99", "press", "release", "earn", "result", "shareholder", "letter", "cfo", "pr")
    html_docs: list[str] = []
    strong: list[str] = []
    for name in names:
        low = name.lower()
        normalized = low.rsplit(".", 1)[0].replace("-", "").replace("_", "")
        if low.endswith(ignored_suffixes) or any(token in normalized for token in ignored_tokens):
            continue
        if not low.endswith((".htm", ".html")):
            continue
        html_docs.append(name)
        if any(term in normalized for term in strong_terms):
            strong.append(name)
    return strong or html_docs


def archive_doc_names(index: dict[str, Any]) -> list[str]:
    return [str(item.get("name", "")) for item in index.get("directory", {}).get("item", []) if item.get("name")]


def discover_required_filings(
    ticker: str,
    cik: str,
    quarter: str,
    submissions: dict[str, Any],
    archive_indexes: dict[str, list[str] | dict[str, Any]],
) -> dict[str, Any]:
    start, end = quarter_bounds(quarter)
    filings = recent_filings(submissions)
    periodic = [
        row for row in filings
        if row["form"] in {"10-Q", "10-K"} and parse_date(row["filing_date"]) and parse_date(row["filing_date"]) <= end
    ]
    periodic.sort(key=lambda row: row["filing_date"])
    item_202 = [
        row for row in filings
        if row["form"] in {"8-K", "8-K/A"}
        and "2.02" in row.get("items", "")
        and parse_date(row["filing_date"])
        and start <= parse_date(row["filing_date"]) <= end  # type: ignore[operator]
    ]
    item_202.sort(key=lambda row: row["filing_date"])

    selected_8k = item_202[0] if item_202 else {}
    selected_periodic = periodic[-1] if periodic else {}
    accession = selected_8k.get("accession", "")
    raw_index = archive_indexes.get(accession, []) if accession else []
    names = archive_doc_names(raw_index) if isinstance(raw_index, dict) else list(raw_index)
    ex_docs = [doc for doc in candidate_exhibit_documents(names) if doc != selected_8k.get("primary_document")]
    periodic_acc = selected_periodic.get("accession", "")
    signal_available = compute_signal_available_datetime(
        selected_8k.get("acceptance_datetime", ""),
        selected_periodic.get("acceptance_datetime", ""),
    )

    reasons: list[str] = []
    if not selected_8k:
        reasons.append("missing_8k_item_202")
    if not selected_periodic:
        reasons.append("missing_10q_10k")
    if not ex_docs:
        reasons.append("missing_earnings_exhibit")

    return {
        "ticker": ticker,
        "cik": cik,
        "quarter": quarter,
        "document_status": "ready_for_fetch" if not reasons else "missing_required_metadata",
        "extraction_quality_failure": int(bool(reasons)),
        "quality_fail_reasons": ";".join(reasons),
        "earnings_8k_accession": accession,
        "earnings_8k_filing_date": selected_8k.get("filing_date", ""),
        "earnings_8k_accepted_datetime": selected_8k.get("acceptance_datetime", ""),
        "earnings_8k_primary_document": selected_8k.get("primary_document", ""),
        "earnings_exhibit_document": ex_docs[0] if ex_docs else "",
        "periodic_accession": periodic_acc,
        "periodic_form": selected_periodic.get("form", ""),
        "periodic_filing_date": selected_periodic.get("filing_date", ""),
        "periodic_accepted_datetime": selected_periodic.get("acceptance_datetime", ""),
        "periodic_primary_document": selected_periodic.get("primary_document", ""),
        "signal_available_datetime": signal_available,
        "tradable_date": next_trading_day(signal_available).isoformat() if signal_available else "",
    }


def fetch_required_documents(client: SecClient, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    docs = [
        ("primary_8k", metadata.get("earnings_8k_accession", ""), metadata.get("earnings_8k_primary_document", "")),
        ("earnings_exhibit", metadata.get("earnings_8k_accession", ""), metadata.get("earnings_exhibit_document", "")),
        ("periodic_10q_10k", metadata.get("periodic_accession", ""), metadata.get("periodic_primary_document", "")),
    ]
    rows: list[dict[str, Any]] = []
    for document_type, accession, document in docs:
        if not accession or not document:
            rows.append(
                {
                    "ticker": metadata.get("ticker", ""),
                    "quarter": metadata.get("quarter", ""),
                    "accession": accession,
                    "document_type": document_type,
                    "document_name": document,
                    "document_status": "missing_metadata",
                    "raw_text": "",
                    "clean_text": "",
                    "text_len": 0,
                    "extraction_ready_flag": 0,
                    "quality_fail_reasons": "missing_metadata",
                    "extraction_quality_failure": 1,
                }
            )
            continue
        try:
            path, raw = client.archive_document(str(metadata.get("ticker", "")), str(metadata.get("cik", "")), str(accession), str(document))
            clean = html_to_text(raw)
            quality = classify_doc_quality(document_type, clean)
            rows.append(
                {
                    "ticker": metadata.get("ticker", ""),
                    "quarter": metadata.get("quarter", ""),
                    "accession": accession,
                    "document_type": document_type,
                    "document_name": document,
                    "document_url": f"{SEC_ARCHIVE_BASE}/{int(str(metadata.get('cik', '0') or 0))}/{str(accession).replace('-', '')}/{document}",
                    "cache_path": str(path),
                    "document_status": "cached_or_fetched",
                    "raw_text": raw,
                    "clean_text": clean,
                    **quality,
                }
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "ticker": metadata.get("ticker", ""),
                    "quarter": metadata.get("quarter", ""),
                    "accession": accession,
                    "document_type": document_type,
                    "document_name": document,
                    "document_status": f"fetch_error_{type(exc).__name__}",
                    "raw_text": "",
                    "clean_text": "",
                    "text_len": 0,
                    "extraction_ready_flag": 0,
                    "quality_fail_reasons": str(exc),
                    "extraction_quality_failure": 1,
                }
            )
    return rows
