from __future__ import annotations

import argparse
import csv
import gzip
import signal
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import FrameType
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sec_document_quality_gate import (
    CACHE_DIR,
    USER_AGENT,
    choose_primary_doc,
    fetch_cached_doc,
    index_doc_names,
)
from sec_filing_metadata_pass import (
    fetch_archive_index,
    fetch_submissions,
    parse_date,
    quarter_bounds,
    recent_filings,
    request_json,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "Growth" / "earnings_8k_sec_parser"
DEFAULT_UNIVERSE = OUT_DIR / "final_active_universe_2024Q3.csv"
SEC_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
SEC_MASTER_INDEX_BASE = "https://www.sec.gov/Archives/edgar/full-index"
MASTER_INDEX_DIR = CACHE_DIR / "sec_master_indexes"
EARNINGS_TEXT_TERMS = (
    "earnings",
    "results",
    "revenue",
    "sales",
    "quarter",
    "fiscal",
    "guidance",
    "outlook",
    "conference call",
)


class TickerTimeoutError(TimeoutError):
    """Raised when one ticker exceeds its wall-clock processing budget."""


@contextmanager
def ticker_timeout(seconds: int | None, ticker: str):
    if not seconds or seconds <= 0:
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)

    def handle_timeout(signum: int, frame: FrameType | None) -> None:  # noqa: ARG001
        raise TickerTimeoutError(f"ticker_timeout_seconds={seconds};ticker={ticker}")

    signal.signal(signal.SIGALRM, handle_timeout)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def read_csv_if_exists(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return read_csv(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def request_json_with_retry(url: str, *, retries: int = 3, sleep: float = 0.5) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return request_json(url)
        except Exception as exc:  # noqa: BLE001 - network layer raises several transient types.
            last_exc = exc
            if attempt < retries:
                time.sleep(sleep * attempt)
    if last_exc:
        raise last_exc
    return {}


def quarter_number(quarter: str) -> int:
    return int(str(quarter)[-1])


def master_index_url(quarter: str) -> str:
    year = str(quarter)[:4]
    return f"{SEC_MASTER_INDEX_BASE}/{year}/QTR{quarter_number(quarter)}/master.gz"


def master_index_path(quarter: str) -> Path:
    return MASTER_INDEX_DIR / f"master_{quarter}.gz"


def fetch_master_index(quarter: str, *, force: bool = False, retries: int = 3, sleep: float = 0.5) -> str:
    MASTER_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    path = master_index_path(quarter)
    if path.exists() and not force:
        return gzip.decompress(path.read_bytes()).decode("latin-1", errors="ignore")
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(master_index_url(quarter), headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=45) as response:
                payload = response.read()
            path.write_bytes(payload)
            return gzip.decompress(payload).decode("latin-1", errors="ignore")
        except (HTTPError, URLError, TimeoutError, OSError, gzip.BadGzipFile) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(sleep * attempt)
    if last_exc:
        raise last_exc
    return ""


def parse_master_index(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    in_data = False
    for line in text.splitlines():
        if not in_data:
            if line.startswith("---"):
                in_data = True
            continue
        parts = line.split("|")
        if len(parts) != 5:
            continue
        cik, company_name, form, filing_date, filename = [part.strip() for part in parts]
        accession = Path(filename).stem
        rows.append({
            "cik": str(int(cik)) if cik.isdigit() else cik,
            "company_name": company_name,
            "form": form,
            "filing_date": filing_date,
            "report_date": "",
            "acceptance_datetime": "",
            "accession": accession,
            "items": "",
            "primary_document": "",
            "filename": filename,
        })
    return rows


def master_filings_by_cik(quarter: str, *, retries: int = 3, sleep: float = 0.5, force: bool = False) -> dict[str, list[dict[str, str]]]:
    rows = parse_master_index(fetch_master_index(quarter, force=force, retries=retries, sleep=sleep))
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["cik"], []).append(row)
    return grouped


def rows_from_filing_arrays(payload: dict[str, Any]) -> list[dict[str, str]]:
    forms = payload.get("form", [])
    rows: list[dict[str, str]] = []
    for idx, form in enumerate(forms):
        def get(name: str) -> str:
            values = payload.get(name, [])
            return str(values[idx]) if idx < len(values) and values[idx] is not None else ""

        rows.append({
            "form": str(form),
            "filing_date": get("filingDate"),
            "report_date": get("reportDate"),
            "acceptance_datetime": get("acceptanceDateTime"),
            "accession": get("accessionNumber"),
            "items": get("items"),
            "primary_document": get("primaryDocument"),
        })
    return rows


def all_submission_filings(submissions: dict[str, Any], *, retries: int = 3, sleep: float = 0.5) -> list[dict[str, str]]:
    filings = recent_filings(submissions)
    for file_info in submissions.get("filings", {}).get("files", []) or []:
        name = str(file_info.get("name", ""))
        if not name:
            continue
        try:
            historical = request_json_with_retry(f"{SEC_SUBMISSIONS_BASE}/{name}", retries=retries, sleep=sleep)
        except Exception:
            continue
        filings.extend(rows_from_filing_arrays(historical))
    deduped: dict[str, dict[str, str]] = {}
    for row in filings:
        key = row.get("accession") or "|".join([row.get("form", ""), row.get("filing_date", ""), row.get("primary_document", "")])
        deduped[key] = row
    return list(deduped.values())


def read_doc_text(result: dict[str, Any]) -> str:
    path = Path(str(result.get("text_path", "")))
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def validate_doc_quality(doc_type: str, result: dict[str, Any], *, expected_form: str = "") -> tuple[bool, list[str]]:
    reasons: list[str] = []
    status = str(result.get("status", ""))
    text_len = int(result.get("text_len", 0) or 0)
    document = str(result.get("document", "")).lower()
    text = read_doc_text(result).lower()
    haystack = f"{document} {text}"

    if status.startswith("error"):
        reasons.append(status)
    if doc_type == "primary_8k":
        if text_len < 100:
            reasons.append("primary_8k_too_short")
        expected = expected_form.lower()
        if expected and expected not in haystack[:5000]:
            reasons.append("primary_8k_form_not_confirmed")
    elif doc_type == "earnings_exhibit":
        if text_len < 1500:
            reasons.append("earnings_exhibit_too_short")
        term_hits = sum(1 for term in EARNINGS_TEXT_TERMS if term in haystack)
        if term_hits < 3:
            reasons.append("exhibit_not_earnings_like")
    elif doc_type == "periodic_10q_10k":
        if text_len < 1000:
            reasons.append("periodic_doc_too_short")
    return not reasons, reasons


def compute_fail_threshold_exit_code(
    audits: list[dict[str, Any]],
    *,
    min_earnings_ready: float | None,
    min_periodic_ready: float | None,
) -> int:
    if not audits:
        return 2
    earnings_rate = sum(row["ready_for_earnings_extraction"] == "True" for row in audits) / len(audits)
    periodic_rate = sum(row["ready_for_periodic_extraction"] == "True" for row in audits) / len(audits)
    if min_earnings_ready is not None and earnings_rate < min_earnings_ready:
        return 2
    if min_periodic_ready is not None and periodic_rate < min_periodic_ready:
        return 2
    return 0


def candidate_exhibit_docs(cik: str, accession: str, primary_doc: str) -> list[str]:
    names = index_doc_names(cik, accession)
    ignored_suffixes = (".xml", ".xsd", ".css", ".js", ".jpg", ".png", ".xlsx", ".zip", ".txt")
    ignored_tokens = ("index", "headers", "filingsummary", "metalinks", "r1")
    release_terms = ("ex99", "exhibit99", "press", "release", "earn", "result", "shareholder", "letter", "cfo", "pr")
    strong: list[str] = []
    fallback_html: list[str] = []
    for name in names:
        low = name.lower()
        stem = low.rsplit(".", 1)[0]
        normalized = stem.replace("-", "").replace("_", "")
        if low.endswith(ignored_suffixes):
            continue
        if any(token in normalized for token in ignored_tokens):
            continue
        if not low.endswith((".htm", ".html")):
            continue
        if name == primary_doc:
            continue
        fallback_html.append(name)
        if any(term in normalized for term in release_terms):
            strong.append(name)
    return strong or fallback_html


def choose_filing_primary_doc(cik: str, accession: str, submission_primary_doc: str = "") -> str:
    """Prefer SEC submissions primaryDocument; archive index order can list exhibits first."""
    names = set(index_doc_names(cik, accession))
    if submission_primary_doc and submission_primary_doc in names:
        return submission_primary_doc
    return choose_primary_doc(cik, accession, set()) or submission_primary_doc


def selected_filings(
    cik: str,
    quarter: str,
    *,
    retries: int = 3,
    sleep: float = 0.5,
    master_rows: list[dict[str, str]] | None = None,
    issuer_mode: str = "us",
) -> dict[str, Any]:
    start, end = quarter_bounds(quarter)
    master_rows = master_rows or []
    filings: list[dict[str, str]] = list(master_rows)
    master_8k_candidates = [
        row for row in master_rows
        if row["form"] in {"8-K", "8-K/A"}
        and parse_date(row["filing_date"])
        and start <= parse_date(row["filing_date"]) <= end  # type: ignore[operator]
    ]
    master_6k_candidates = [
        row for row in master_rows
        if row["form"] == "6-K"
        and parse_date(row["filing_date"])
        and start <= parse_date(row["filing_date"]) <= end  # type: ignore[operator]
    ]
    submissions: dict[str, Any] | None = None
    if not master_rows or master_8k_candidates or master_6k_candidates:
        submissions = fetch_submissions(cik)
        if not submissions and not master_rows:
            return {"status": "missing_submissions", "periodic": None, "events": []}
        if submissions:
            filings.extend(all_submission_filings(submissions, retries=retries, sleep=sleep))
    deduped_filings: dict[str, dict[str, str]] = {}
    for filing in filings:
        key = filing.get("accession") or "|".join(
            [filing.get("form", ""), filing.get("filing_date", ""), filing.get("primary_document", "")]
        )
        deduped_filings[key] = filing
    filings = list(deduped_filings.values())
    us_periodic = [
        row for row in filings
        if row["form"] in {"10-Q", "10-K"}
        and parse_date(row["filing_date"])
        and parse_date(row["filing_date"]) <= end
    ]
    us_periodic.sort(key=lambda row: row["filing_date"])
    us_events = [
        row for row in filings
        if row["form"] in {"8-K", "8-K/A"}
        and "2.02" in row.get("items", "")
        and parse_date(row["filing_date"])
        and start <= parse_date(row["filing_date"]) <= end  # type: ignore[operator]
    ]
    us_events.sort(key=lambda row: row["filing_date"])
    foreign_periodic = [
        row for row in filings
        if row["form"] == "20-F"
        and parse_date(row["filing_date"])
        and parse_date(row["filing_date"]) <= end
    ]
    foreign_periodic.sort(key=lambda row: row["filing_date"])
    foreign_events = [
        row for row in filings
        if row["form"] == "6-K"
        and parse_date(row["filing_date"])
        and start <= parse_date(row["filing_date"]) <= end  # type: ignore[operator]
    ]
    foreign_events.sort(key=lambda row: row["filing_date"])
    resolved_mode = issuer_mode
    if issuer_mode == "auto":
        resolved_mode = "us" if (us_events or us_periodic) else "foreign"
    if resolved_mode == "foreign":
        periodic = foreign_periodic
        events = foreign_events
    else:
        periodic = us_periodic
        events = us_events
    events.sort(key=lambda row: row["filing_date"])
    return {"status": "ok", "issuer_mode": resolved_mode, "periodic": periodic[-1] if periodic else None, "events": events}


def is_earnings_result_text(text: str) -> bool:
    compact = " ".join(text.lower().split())
    if not compact:
        return False
    scheduling_terms = [
        "results release scheduled",
        "will be releasing",
        "conference call scheduled",
        "scheduled for",
    ]
    result_terms = [
        "financial results",
        "reported its financial results",
        "reports fourth quarter",
        "reports first quarter",
        "reports second quarter",
        "reports third quarter",
        "reports 20",
        "quarter ended",
        "year ended",
        "earnings release",
    ]
    return any(term in compact for term in result_terms) and not any(term in compact[:1200] for term in scheduling_terms)


def is_primary_earnings_doc_text(text: str) -> bool:
    """Allow primary Item 2.02 docs when no EX-99.1 exists but the filing has actual/preliminary results."""
    compact = " ".join(text.lower().split())
    if "item 2.02" not in compact[:3000]:
        return False
    terms = [
        "anticipated revenues",
        "anticipated revenue",
        "anticipated net income",
        "anticipated net loss",
        "preliminary results",
        "preliminary financial results",
        "revenues for the three months ended",
        "revenue for the three months ended",
        "net loss per share",
        "net income per share",
    ]
    return is_earnings_result_text(text) or any(term in compact for term in terms)


def fetch_doc(
    ticker: str,
    cik: str,
    accession: str,
    document: str,
    doc_type: str,
    *,
    force: bool,
    sleep: float,
    retries: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for attempt in range(1, retries + 1):
        result = fetch_cached_doc(ticker, cik, accession, document, force=force if attempt == 1 else True)
        time.sleep(sleep * attempt)
        if not str(result.get("status", "")).startswith("error"):
            break
    return {
        "ticker": ticker,
        "cik": cik,
        "doc_type": doc_type,
        "accession": accession,
        "document": document,
        "status": result.get("status", ""),
        "text_len": result.get("text_len", 0),
        "table_count": result.get("table_count", 0),
        "html_path": result.get("html_path", ""),
        "text_path": result.get("text_path", ""),
    }


def process_ticker(
    row: dict[str, str],
    quarter: str,
    *,
    force: bool,
    sleep: float,
    fetch: bool,
    retries: int,
    master_rows: list[dict[str, str]] | None = None,
    issuer_mode: str = "us",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ticker = row.get("ticker") or row.get("Ticker")
    cik = row.get("cik", "")
    audit: dict[str, Any] = {
        "quarter": quarter,
        "ticker": ticker,
        "cik": cik,
        "metadata_status": "",
        "issuer_mode": "",
        "item_202_8k_count": 0,
        "item_202_event_dates": "",
        "item_202_accessions": "",
        "primary_8k_docs": "",
        "earnings_exhibit_docs": "",
        "earnings_exhibit_doc_count": 0,
        "latest_periodic_form": "",
        "latest_periodic_filing_date": "",
        "latest_periodic_accession": "",
        "latest_periodic_doc": "",
        "primary_8k_cached_count": 0,
        "earnings_exhibit_cached_count": 0,
        "periodic_cached": "False",
        "ready_for_earnings_extraction": "False",
        "ready_for_periodic_extraction": "False",
        "quality_fail_reasons": "",
        "audit_reasons": "",
    }
    report: list[dict[str, Any]] = []
    if not ticker:
        audit["metadata_status"] = "missing_ticker"
        audit["audit_reasons"] = "missing_ticker"
        return audit, report
    if not cik:
        audit["metadata_status"] = "missing_cik"
        audit["audit_reasons"] = "missing_cik"
        return audit, report

    selected = selected_filings(cik, quarter, retries=retries, sleep=sleep, master_rows=master_rows, issuer_mode=issuer_mode)
    audit["metadata_status"] = selected["status"]
    audit["issuer_mode"] = selected.get("issuer_mode", issuer_mode)
    if selected["status"] != "ok":
        audit["audit_reasons"] = selected["status"]
        return audit, report

    events = selected["events"]
    periodic = selected["periodic"]
    reasons: list[str] = []
    primary_cached = 0
    exhibit_cached = 0
    primary_docs: list[str] = []
    exhibit_docs: list[str] = []
    kept_events: list[dict[str, str]] = []
    quality_failures: list[str] = []
    primary_earnings_doc_count = 0
    for event in events:
        accession = event["accession"]
        fetch_archive_index(cik, accession, force=False)
        time.sleep(sleep)
        primary_doc = choose_filing_primary_doc(cik, accession, event.get("primary_document", ""))
        event_primary_cached = 0
        event_exhibit_cached = 0
        event_primary_docs: list[str] = []
        event_exhibit_docs: list[str] = []
        event_quality_failures: list[str] = []
        event_texts: list[str] = []
        event_primary_earnings_doc = False
        if primary_doc:
            event_primary_docs.append(primary_doc)
            if fetch:
                result = fetch_doc(ticker, cik, accession, primary_doc, "primary_8k", force=force, sleep=sleep, retries=retries)
                report.append(result)
                if result.get("text_path"):
                    primary_text = Path(str(result["text_path"])).read_text(encoding="utf-8", errors="ignore")
                    event_texts.append(primary_text)
                    event_primary_earnings_doc = is_primary_earnings_doc_text(primary_text)
                ok, doc_reasons = validate_doc_quality("primary_8k", {**result, "document": primary_doc}, expected_form=event["form"])
                if ok:
                    event_primary_cached += 1
                else:
                    event_quality_failures.extend(f"primary_8k:{reason}" for reason in doc_reasons)
        ex_docs = candidate_exhibit_docs(cik, accession, primary_doc)
        for doc in ex_docs[:3]:
            event_exhibit_docs.append(doc)
            if fetch:
                result = fetch_doc(ticker, cik, accession, doc, "earnings_exhibit", force=force, sleep=sleep, retries=retries)
                report.append(result)
                if result.get("text_path"):
                    event_texts.append(Path(str(result["text_path"])).read_text(encoding="utf-8", errors="ignore"))
                ok, doc_reasons = validate_doc_quality("earnings_exhibit", {**result, "document": doc}, expected_form="")
                if ok:
                    event_exhibit_cached += 1
                else:
                    event_quality_failures.extend(f"earnings_exhibit:{reason}" for reason in doc_reasons)
        if audit["issuer_mode"] == "foreign" and not any(is_earnings_result_text(text) for text in event_texts):
            continue
        kept_events.append(event)
        primary_docs.extend(event_primary_docs)
        exhibit_docs.extend(event_exhibit_docs)
        primary_cached += event_primary_cached
        exhibit_cached += event_exhibit_cached
        primary_earnings_doc_count += int(event_primary_cached > 0 and event_primary_earnings_doc)
        quality_failures.extend(event_quality_failures)

    audit["item_202_8k_count"] = len(kept_events)
    audit["item_202_event_dates"] = ";".join(event["filing_date"] for event in kept_events)
    audit["item_202_accessions"] = ";".join(event["accession"] for event in kept_events)

    if not kept_events:
        reasons.append("missing_earnings_event")
    if kept_events and not exhibit_docs and primary_earnings_doc_count == 0:
        reasons.append("missing_earnings_exhibit_doc")

    audit["primary_8k_docs"] = ";".join(primary_docs)
    audit["earnings_exhibit_docs"] = ";".join(exhibit_docs)
    audit["earnings_exhibit_doc_count"] = len(exhibit_docs)
    audit["primary_8k_cached_count"] = primary_cached
    audit["earnings_exhibit_cached_count"] = exhibit_cached
    audit["ready_for_earnings_extraction"] = str(primary_cached > 0 and (exhibit_cached > 0 or primary_earnings_doc_count > 0))

    if periodic:
        accession = periodic["accession"]
        audit["latest_periodic_form"] = periodic["form"]
        audit["latest_periodic_filing_date"] = periodic["filing_date"]
        audit["latest_periodic_accession"] = accession
        fetch_archive_index(cik, accession, force=False)
        time.sleep(sleep)
        periodic_doc = choose_filing_primary_doc(cik, accession, periodic.get("primary_document", ""))
        audit["latest_periodic_doc"] = periodic_doc
        if periodic_doc and fetch:
            result = fetch_doc(ticker, cik, accession, periodic_doc, "periodic_10q_10k", force=force, sleep=sleep, retries=retries)
            report.append(result)
            ok, doc_reasons = validate_doc_quality("periodic_10q_10k", {**result, "document": periodic_doc}, expected_form=periodic["form"])
            audit["periodic_cached"] = str(ok)
            audit["ready_for_periodic_extraction"] = audit["periodic_cached"]
            if not ok:
                quality_failures.extend(f"periodic_10q_10k:{reason}" for reason in doc_reasons)
    else:
        reasons.append("missing_10q_10k_before_or_in_qtr")

    if audit["ready_for_earnings_extraction"] != "True":
        reasons.append("earnings_docs_not_ready")
    if audit["ready_for_periodic_extraction"] != "True":
        reasons.append("periodic_doc_not_ready")
    if quality_failures and (
        audit["ready_for_earnings_extraction"] != "True"
        or audit["ready_for_periodic_extraction"] != "True"
    ):
        reasons.append("quality_check_failed")
    audit["quality_fail_reasons"] = ";".join(dict.fromkeys(quality_failures))
    audit["audit_reasons"] = ";".join(dict.fromkeys(reasons)) if reasons else "ready"
    return audit, report


def failed_ticker_audit(row: dict[str, str], quarter: str, reason: str) -> dict[str, Any]:
    ticker = row.get("ticker") or row.get("Ticker") or ""
    cik = row.get("cik", "")
    return {
        "quarter": quarter,
        "ticker": ticker,
        "cik": cik,
        "metadata_status": reason,
        "item_202_8k_count": 0,
        "item_202_event_dates": "",
        "item_202_accessions": "",
        "primary_8k_docs": "",
        "earnings_exhibit_docs": "",
        "earnings_exhibit_doc_count": 0,
        "latest_periodic_form": "",
        "latest_periodic_filing_date": "",
        "latest_periodic_accession": "",
        "latest_periodic_doc": "",
        "primary_8k_cached_count": 0,
        "earnings_exhibit_cached_count": 0,
        "periodic_cached": "False",
        "ready_for_earnings_extraction": "False",
        "ready_for_periodic_extraction": "False",
        "quality_fail_reasons": reason,
        "audit_reasons": reason,
    }


def failed_ticker_report(row: dict[str, str], quarter: str, reason: str) -> dict[str, Any]:
    return {
        "ticker": row.get("ticker") or row.get("Ticker") or "",
        "cik": row.get("cik", ""),
        "doc_type": "ticker_level",
        "accession": "",
        "document": "",
        "status": reason,
        "text_len": 0,
        "table_count": 0,
        "html_path": "",
        "text_path": "",
        "quarter": quarter,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit/fetch required SEC docs for a quarter and universe")
    parser.add_argument("--quarter", required=True)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--audit-output", type=Path, default=None)
    parser.add_argument("--fetch-report", type=Path, default=None)
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--min-earnings-ready-rate", type=float, default=None)
    parser.add_argument("--min-periodic-ready-rate", type=float, default=None)
    parser.add_argument("--metadata-source", choices=["hybrid", "submissions"], default="hybrid")
    parser.add_argument("--issuer-mode", choices=["us", "foreign", "auto"], default="us")
    parser.add_argument("--force-master-index", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-fetch", action="store_true", help="Audit only; do not fetch missing docs")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--resume-existing",
        action="store_true",
        help="Load existing audit/fetch outputs and skip tickers already audited.",
    )
    parser.add_argument(
        "--ticker-timeout-seconds",
        type=int,
        default=180,
        help="Hard wall-clock limit per ticker; use 0 to disable.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audit_output = args.audit_output or OUT_DIR / f"sec_quarter_cache_audit_{args.quarter}.csv"
    fetch_report_output = args.fetch_report or OUT_DIR / f"sec_quarter_cache_fetch_report_{args.quarter}.csv"
    rows = read_csv(args.universe)
    if args.limit is not None:
        rows = rows[: args.limit]
    master_by_cik: dict[str, list[dict[str, str]]] = {}
    if args.metadata_source == "hybrid":
        try:
            master_by_cik = master_filings_by_cik(args.quarter, retries=args.retries, sleep=args.sleep, force=args.force_master_index)
            print(f"master_index_rows={sum(len(value) for value in master_by_cik.values())}", flush=True)
        except Exception as exc:  # noqa: BLE001 - fallback keeps the production run alive.
            print(f"master_index_unavailable={type(exc).__name__};fallback=submissions", flush=True)
    existing_audits = read_csv_if_exists(audit_output) if args.resume_existing else []
    completed_by_ticker = {
        str(row.get("ticker", "") or row.get("Ticker", "")).upper(): row
        for row in existing_audits
        if row.get("ticker") or row.get("Ticker")
    }
    completed_tickers = set(completed_by_ticker)
    audits: list[dict[str, Any]] = [
        completed_by_ticker[ticker]
        for row in rows
        for ticker in [str(row.get("ticker", "") or row.get("Ticker", "")).upper()]
        if ticker in completed_by_ticker
    ]
    reports: list[dict[str, Any]] = read_csv_if_exists(fetch_report_output) if args.resume_existing else []
    if args.resume_existing:
        print(
            f"resume_existing_audit_rows={len(audits)} resume_existing_fetch_rows={len(reports)} "
            f"remaining={len(rows) - len(completed_tickers)}",
            flush=True,
        )
    for idx, row in enumerate(rows, start=1):
        ticker = row.get("ticker") or row.get("Ticker") or ""
        if str(ticker).upper() in completed_tickers:
            continue
        started = time.monotonic()
        try:
            with ticker_timeout(args.ticker_timeout_seconds, ticker):
                audit, report = process_ticker(
                    row,
                    args.quarter,
                    force=args.force,
                    sleep=args.sleep,
                    fetch=not args.no_fetch,
                    retries=args.retries,
                    master_rows=master_by_cik.get(str(row.get("cik", "")).lstrip("0")) if master_by_cik else None,
                    issuer_mode=args.issuer_mode,
                )
        except TickerTimeoutError as exc:
            reason = f"ticker_timeout:{args.ticker_timeout_seconds}s"
            audit = failed_ticker_audit(row, args.quarter, reason)
            report = [failed_ticker_report(row, args.quarter, reason)]
            print(f"{idx}/{len(rows)} {ticker} skipped={type(exc).__name__} reason={reason}", flush=True)
        except Exception as exc:  # noqa: BLE001 - production run must skip one bad ticker and continue.
            reason = f"ticker_error:{type(exc).__name__}"
            audit = failed_ticker_audit(row, args.quarter, reason)
            report = [failed_ticker_report(row, args.quarter, reason)]
            print(f"{idx}/{len(rows)} {ticker} skipped={type(exc).__name__} reason={reason}", flush=True)
        audit["elapsed_seconds"] = f"{time.monotonic() - started:.2f}"
        audits.append(audit)
        reports.extend(report)
        if args.checkpoint_every and idx % args.checkpoint_every == 0:
            write_csv(audit_output, audits)
            write_csv(fetch_report_output, reports)
        if idx % 25 == 0 or audit["ready_for_earnings_extraction"] != "True":
            print(
                f"{idx}/{len(rows)} {audit['ticker']} earnings_ready={audit['ready_for_earnings_extraction']} "
                f"periodic_ready={audit['ready_for_periodic_extraction']} reasons={audit['audit_reasons']}",
                flush=True,
            )
    write_csv(audit_output, audits)
    write_csv(fetch_report_output, reports)
    earnings_ready = sum(row["ready_for_earnings_extraction"] == "True" for row in audits)
    periodic_ready = sum(row["ready_for_periodic_extraction"] == "True" for row in audits)
    print(f"rows={len(audits)} earnings_ready={earnings_ready} periodic_ready={periodic_ready}")
    reason_counts: dict[str, int] = {}
    for row in audits:
        if row["audit_reasons"] == "ready":
            continue
        for reason in str(row["audit_reasons"]).split(";"):
            if reason:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
    for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"{reason}: {count}")
    print(f"fetch_report_rows={len(reports)}")
    print(f"wrote {audit_output}")
    print(f"wrote {fetch_report_output}")
    exit_code = compute_fail_threshold_exit_code(
        audits,
        min_earnings_ready=args.min_earnings_ready_rate,
        min_periodic_ready=args.min_periodic_ready_rate,
    )
    if exit_code:
        print("fail_threshold_not_met")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
