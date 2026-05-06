from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
import warnings
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, FeatureNotFound, XMLParsedAsHTMLWarning

from src.config.cache_paths import sec_cache_root


warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = sec_cache_root()
INDEX_DIR = CACHE_DIR / "sec_archive_indexes"
DOC_HTML_DIR = CACHE_DIR / "sec_docs_html"
DOC_TEXT_DIR = CACHE_DIR / "sec_docs_text"
DEFAULT_INPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "sec_filing_metadata_passed_2024Q3.csv"
DEFAULT_OUTPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "sec_document_quality_2024Q3.csv"
USER_AGENT = "AeternusAutoResearch/1.0 contact@aeternus.local"


def read_rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


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


def clean_text(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(raw or "")).strip()


def html_to_text(raw: str) -> str:
    try:
        soup = BeautifulSoup(raw or "", "lxml")
    except FeatureNotFound:
        soup = BeautifulSoup(raw or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return clean_text(soup.get_text(" "))


def count_tables(raw: str) -> int:
    try:
        try:
            soup = BeautifulSoup(raw or "", "lxml")
        except FeatureNotFound:
            soup = BeautifulSoup(raw or "", "html.parser")
        return len(soup.find_all("table"))
    except Exception:
        return 0


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=45) as response:
        return response.read().decode("utf-8", errors="ignore")


def safe_doc_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def accession_compact(accession: str) -> str:
    return accession.replace("-", "")


def archive_url(cik: str, accession: str, document: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_compact(accession)}/{document}"


def doc_cache_paths(ticker: str, accession: str, document: str) -> tuple[Path, Path]:
    safe = f"{ticker}_{accession_compact(accession)}_{safe_doc_name(document)}"
    return DOC_HTML_DIR / f"{safe}.html", DOC_TEXT_DIR / f"{safe}.txt"


def cached_archive_index(cik: str, accession: str) -> dict[str, Any]:
    path = INDEX_DIR / str(cik).zfill(10) / f"{accession_compact(accession)}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def index_doc_names(cik: str, accession: str) -> list[str]:
    index = cached_archive_index(cik, accession)
    return [str(item.get("name", "")) for item in index.get("directory", {}).get("item", []) if item.get("name")]


def choose_primary_doc(cik: str, accession: str, excluded_docs: set[str]) -> str:
    names = index_doc_names(cik, accession)
    ignored_suffixes = (".xml", ".xsd", ".css", ".js", ".jpg", ".png", ".xlsx", ".zip", ".txt")
    ignored_tokens = ("index", "headers", "filingsummary", "metalinks", "r1")
    candidates = []
    for name in names:
        low = name.lower()
        normalized = low.replace("-", "").replace("_", "")
        if name in excluded_docs:
            continue
        if low.endswith(ignored_suffixes):
            continue
        if any(token in normalized for token in ignored_tokens):
            continue
        if low.endswith((".htm", ".html")):
            candidates.append(name)
    return candidates[0] if candidates else ""


def fetch_cached_doc(ticker: str, cik: str, accession: str, document: str, *, force: bool) -> dict[str, Any]:
    html_path, text_path = doc_cache_paths(ticker, accession, document)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    status = "cached"
    raw = ""
    if html_path.exists() and text_path.exists() and not force:
        try:
            text = text_path.read_text(encoding="utf-8", errors="ignore")
            raw = html_path.read_text(encoding="utf-8", errors="ignore")
            return {
                "status": status,
                "html_path": str(html_path),
                "text_path": str(text_path),
                "text_len": len(text),
                "table_count": count_tables(raw),
            }
        except OSError:
            pass
    try:
        raw = fetch_text(archive_url(cik, accession, document))
        text = html_to_text(raw)
        html_path.write_text(raw, encoding="utf-8")
        text_path.write_text(text, encoding="utf-8")
        status = "fetched"
        return {
            "status": status,
            "html_path": str(html_path),
            "text_path": str(text_path),
            "text_len": len(text),
            "table_count": count_tables(raw),
        }
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {
            "status": f"error_{type(exc).__name__}",
            "html_path": str(html_path),
            "text_path": str(text_path),
            "text_len": 0,
            "table_count": 0,
        }


def score_row(row: dict[str, str], *, force: bool, sleep_seconds: float) -> dict[str, Any]:
    ticker = row["ticker"]
    cik = row["cik"]
    accessions = [x for x in row.get("item_202_8k_accessions", "").split(";") if x]
    ex_docs = [x for x in row.get("ex99_1_documents", "").split(";") if x]
    latest_periodic_acc = row.get("latest_10q_10k_accession", "")

    # Current metadata gate is ticker-level. Use the first event accession for this quarter.
    event_accession = accessions[0] if accessions else ""
    event_ex_docs = ex_docs
    primary_doc = choose_primary_doc(cik, event_accession, set(event_ex_docs)) if event_accession else ""
    periodic_doc = choose_primary_doc(cik, latest_periodic_acc, set()) if latest_periodic_acc else ""

    docs: dict[str, dict[str, Any]] = {}
    if primary_doc:
        docs["primary_8k"] = fetch_cached_doc(ticker, cik, event_accession, primary_doc, force=force)
        time.sleep(sleep_seconds)
    for idx, doc in enumerate(event_ex_docs[:3], start=1):
        docs[f"exhibit_{idx}"] = fetch_cached_doc(ticker, cik, event_accession, doc, force=force)
        time.sleep(sleep_seconds)
    if periodic_doc:
        docs["periodic"] = fetch_cached_doc(ticker, cik, latest_periodic_acc, periodic_doc, force=force)
        time.sleep(sleep_seconds)

    primary = docs.get("primary_8k", {})
    exhibits = [value for key, value in docs.items() if key.startswith("exhibit_")]
    periodic = docs.get("periodic", {})
    ex_text_len = sum(int(doc.get("text_len", 0) or 0) for doc in exhibits)
    ex_tables = sum(int(doc.get("table_count", 0) or 0) for doc in exhibits)
    primary_error = str(primary.get("status", "")).startswith("error")
    successful_exhibits = [
        doc for doc in exhibits
        if not str(doc.get("status", "")).startswith("error") and int(doc.get("text_len", 0) or 0) > 0
    ]

    reasons: list[str] = []
    if primary_error or not primary_doc or int(primary.get("text_len", 0) or 0) < 100:
        reasons.append("primary_8k_text_too_short")
    if not successful_exhibits or ex_text_len < 1500:
        reasons.append("earnings_exhibit_text_too_short")

    return {
        "quarter": row.get("quarter", ""),
        "ticker": ticker,
        "cik": cik,
        "event_accession": event_accession,
        "event_dates": row.get("item_202_8k_dates", ""),
        "primary_8k_doc": primary_doc,
        "exhibit_docs": ";".join(event_ex_docs[:3]),
        "periodic_doc": periodic_doc,
        "primary_8k_text_len": primary.get("text_len", 0),
        "exhibit_text_len": ex_text_len,
        "periodic_text_len": periodic.get("text_len", 0),
        "exhibit_table_count": ex_tables,
        "exhibit_table_flag": "has_tables" if ex_tables > 0 else "no_tables_detected",
        "doc_statuses": ";".join(f"{key}:{value.get('status')}" for key, value in docs.items()),
        "quality_pass": str(not reasons),
        "quality_reason": ";".join(reasons) if reasons else "included",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch/cache SEC docs and run Python quality gate before LLM")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.03)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_rows(args.input)
    if args.limit is not None:
        rows = rows[: args.limit]
    out_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        result = score_row(row, force=args.force, sleep_seconds=args.sleep)
        out_rows.append(result)
        if idx % 25 == 0 or result["quality_pass"] == "False":
            print(f"{idx}/{len(rows)} {result['ticker']} pass={result['quality_pass']} reason={result['quality_reason']}", flush=True)
    write_csv(args.output, out_rows)
    passed = sum(row["quality_pass"] == "True" for row in out_rows)
    reasons: dict[str, int] = {}
    for row in out_rows:
        if row["quality_pass"] == "True":
            continue
        for reason in str(row["quality_reason"]).split(";"):
            reasons[reason] = reasons.get(reason, 0) + 1
    print(f"rows={len(out_rows)} quality_pass={passed}")
    for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0])):
        print(f"{reason}: {count}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
