from __future__ import annotations

import argparse
import csv
import time
from datetime import date
from pathlib import Path
from typing import Any

from sec_document_quality_gate import (
    choose_primary_doc,
    fetch_cached_doc,
    index_doc_names,
)
from sec_filing_metadata_pass import fetch_submissions, parse_date, quarter_bounds, recent_filings


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT = ROOT / "Growth" / "earnings_8k_sec_parser" / "filing_coverage_audit_2024Q3.csv"
DEFAULT_OUTPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "missing_earnings_docs_fetch_report_2024Q3.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
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


def candidate_exhibit_docs(cik: str, accession: str, primary_doc: str) -> list[str]:
    names = index_doc_names(cik, accession)
    ignored_suffixes = (".xml", ".xsd", ".css", ".js", ".jpg", ".png", ".xlsx", ".zip", ".txt")
    ignored_tokens = ("index", "headers", "filingsummary", "metalinks", "r1")
    strong_terms = ("ex99", "exhibit99", "press", "release", "earn", "result", "shareholder", "letter", "cfo", "pr")
    html_docs: list[str] = []
    strong: list[str] = []
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
        html_docs.append(name)
        if any(term in normalized for term in strong_terms):
            strong.append(name)
    return strong or html_docs


def item_202_events(cik: str, quarter: str) -> list[dict[str, str]]:
    start, end = quarter_bounds(quarter)
    submissions = fetch_submissions(cik)
    if not submissions:
        return []
    filings = recent_filings(submissions)
    events = [
        row for row in filings
        if row["form"] in {"8-K", "8-K/A"}
        and "2.02" in row.get("items", "")
        and parse_date(row["filing_date"])
        and start <= parse_date(row["filing_date"]) <= end  # type: ignore[operator]
    ]
    return sorted(events, key=lambda row: row["filing_date"])


def repair_ticker(row: dict[str, str], quarter: str, *, force: bool, sleep_seconds: float) -> dict[str, Any]:
    ticker = row["ticker"]
    cik = row.get("cik", "")
    base: dict[str, Any] = {
        "quarter": quarter,
        "ticker": ticker,
        "cik": cik,
        "repair_status": "",
        "selected_event_date": "",
        "selected_accession": "",
        "primary_8k_doc": "",
        "primary_8k_text_len": 0,
        "exhibit_docs": "",
        "exhibit_text_len": 0,
        "exhibit_doc_count": 0,
        "fetch_notes": "",
    }
    if not cik:
        base["repair_status"] = "missing_cik"
        return base

    events = item_202_events(cik, quarter)
    if not events:
        base["repair_status"] = "no_8k_item_202_in_quarter"
        return base

    failures: list[str] = []
    for event in events:
        accession = event["accession"]
        primary_doc = choose_primary_doc(cik, accession, set()) or event.get("primary_document", "")
        ex_docs = candidate_exhibit_docs(cik, accession, primary_doc)
        primary_result = fetch_cached_doc(ticker, cik, accession, primary_doc, force=force) if primary_doc else {"text_len": 0, "status": "missing_primary"}
        time.sleep(sleep_seconds)
        exhibit_results = []
        for doc in ex_docs[:5]:
            result = fetch_cached_doc(ticker, cik, accession, doc, force=force)
            exhibit_results.append((doc, result))
            time.sleep(sleep_seconds)
        exhibit_text_len = sum(int(result.get("text_len", 0) or 0) for _, result in exhibit_results)
        successful_ex_docs = [
            doc for doc, result in exhibit_results
            if not str(result.get("status", "")).startswith("error") and int(result.get("text_len", 0) or 0) >= 1500
        ]
        primary_ok = int(primary_result.get("text_len", 0) or 0) >= 100
        if primary_ok and successful_ex_docs:
            base.update({
                "repair_status": "ready",
                "selected_event_date": event["filing_date"],
                "selected_accession": accession,
                "primary_8k_doc": primary_doc,
                "primary_8k_text_len": primary_result.get("text_len", 0),
                "exhibit_docs": ";".join(successful_ex_docs),
                "exhibit_text_len": exhibit_text_len,
                "exhibit_doc_count": len(successful_ex_docs),
                "fetch_notes": "matched_docs_by_accession",
            })
            return base
        failures.append(
            f"{event['filing_date']}:{accession}:primary_len={primary_result.get('text_len', 0)}:"
            f"ex_docs={len(ex_docs)}:ex_text_len={exhibit_text_len}"
        )

    base["repair_status"] = "not_ready_after_fetch"
    base["fetch_notes"] = "|".join(failures)
    return base


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch/cache missing 8-K Item 2.02 and earnings exhibit docs")
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--quarter", default="2024Q3")
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = [
        row for row in read_csv(args.audit)
        if row.get("earnings_event_ready_for_local_extraction") != "True"
    ]
    report: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        result = repair_ticker(row, args.quarter, force=args.force, sleep_seconds=args.sleep)
        report.append(result)
        print(f"{idx}/{len(rows)} {result['ticker']} {result['repair_status']} {result.get('selected_accession', '')}", flush=True)
    write_csv(args.output, report)
    counts: dict[str, int] = {}
    for row in report:
        counts[row["repair_status"]] = counts.get(row["repair_status"], 0) + 1
    for status, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"{status}: {count}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
