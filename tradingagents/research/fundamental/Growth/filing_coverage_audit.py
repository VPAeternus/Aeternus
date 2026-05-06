from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from sec_document_quality_gate import choose_primary_doc, doc_cache_paths


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = ROOT / "Growth" / "earnings_8k_sec_parser" / "final_pre_extraction_universe_2024Q3.csv"
DEFAULT_METADATA = ROOT / "Growth" / "earnings_8k_sec_parser" / "sec_filing_metadata_2024Q3.csv"
DEFAULT_OUTPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "filing_coverage_audit_2024Q3.csv"
DEFAULT_FETCH_PLAN = ROOT / "Growth" / "earnings_8k_sec_parser" / "missing_doc_fetch_plan_2024Q3.csv"
DEFAULT_REPAIR_REPORT = ROOT / "Growth" / "earnings_8k_sec_parser" / "missing_earnings_docs_fetch_report_2024Q3.csv"


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


def text_len(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return 0


def cache_status(ticker: str, accession: str, document: str) -> dict[str, Any]:
    html_path, text_path = doc_cache_paths(ticker, accession, document)
    return {
        "document": document,
        "html_cached": str(html_path.exists()),
        "text_cached": str(text_path.exists()),
        "text_len": text_len(text_path),
        "html_path": str(html_path),
        "text_path": str(text_path),
    }


def choose_docs(row: dict[str, str]) -> tuple[str, list[str], str]:
    event_accessions = [item for item in str(row.get("item_202_8k_accessions", "")).split(";") if item]
    event_accession = str(row.get("event_accession", "")) or (event_accessions[0] if event_accessions else "")
    primary_doc = str(row.get("primary_8k_doc", ""))
    exhibit_docs = [item for item in str(row.get("exhibit_docs") or row.get("ex99_1_documents", "")).split(";") if item]
    periodic_doc = str(row.get("periodic_doc", ""))
    return event_accession, exhibit_docs[:3], primary_doc or ""


def audit_row(
    row: dict[str, str],
    metadata_by_ticker: dict[str, dict[str, str]],
    repair_by_ticker: dict[str, dict[str, str]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ticker = row["ticker"]
    metadata = metadata_by_ticker.get(ticker, {})
    repair = repair_by_ticker.get(ticker, {})
    cik = row.get("cik", "")
    event_accession, exhibit_docs, primary_doc = choose_docs(row)
    if repair.get("repair_status") == "ready":
        event_accession = repair.get("selected_accession", "") or event_accession
        primary_doc = repair.get("primary_8k_doc", "") or primary_doc
        exhibit_docs = [item for item in repair.get("exhibit_docs", "").split(";") if item] or exhibit_docs
    event_dates = row.get("event_dates") or row.get("item_202_8k_dates", "")
    if repair.get("selected_event_date"):
        event_dates = repair["selected_event_date"]
    periodic_accession = row.get("latest_10q_10k_accession", "") or metadata.get("latest_10q_10k_accession", "")
    periodic_doc = row.get("periodic_doc", "")
    if periodic_accession and not periodic_doc and cik:
        periodic_doc = choose_primary_doc(cik, periodic_accession, set())

    fetch_plan: list[dict[str, Any]] = []
    primary = cache_status(ticker, event_accession, primary_doc) if event_accession and primary_doc else {}
    exhibits = [cache_status(ticker, event_accession, doc) for doc in exhibit_docs if event_accession]
    periodic = cache_status(ticker, periodic_accession, periodic_doc) if periodic_accession and periodic_doc else {}

    primary_cached = bool(primary) and primary["text_cached"] == "True" and int(primary["text_len"]) >= 100
    exhibit_cached_count = sum(item["text_cached"] == "True" and int(item["text_len"]) >= 1500 for item in exhibits)
    exhibit_text_len = sum(int(item["text_len"]) for item in exhibits)
    periodic_cached = bool(periodic) and periodic["text_cached"] == "True" and int(periodic["text_len"]) >= 1000

    reasons: list[str] = []
    if not cik:
        reasons.append("missing_cik")
    if not event_accession:
        reasons.append("missing_event_accession")
    if not primary_doc:
        reasons.append("missing_primary_8k_doc")
    if not primary_cached:
        reasons.append("primary_8k_text_not_cached_or_short")
    if not exhibit_docs:
        reasons.append("missing_exhibit_doc")
    if exhibit_cached_count == 0:
        reasons.append("exhibit_text_not_cached_or_short")
    periodic_reasons: list[str] = []
    if not periodic_accession:
        periodic_reasons.append("missing_periodic_accession")
    if periodic_accession and not periodic_doc:
        periodic_reasons.append("missing_periodic_doc_name")
    if periodic_accession and periodic_doc and not periodic_cached:
        periodic_reasons.append("periodic_text_not_cached_or_short")

    def add_fetch(kind: str, accession: str, document: str, status: dict[str, Any]) -> None:
        if not accession or not document:
            return
        if status.get("text_cached") == "True" and int(status.get("text_len", 0) or 0) > 0:
            return
        fetch_plan.append({
            "ticker": ticker,
            "cik": cik,
            "doc_type": kind,
            "accession": accession,
            "document": document,
            "current_text_len": status.get("text_len", 0),
            "html_path": status.get("html_path", ""),
            "text_path": status.get("text_path", ""),
        })

    if primary:
        add_fetch("primary_8k", event_accession, primary_doc, primary)
    for item in exhibits:
        add_fetch("earnings_exhibit", event_accession, item["document"], item)
    if periodic:
        add_fetch("periodic_10q_10k", periodic_accession, periodic_doc, periodic)

    audit = {
        "quarter": row.get("quarter", ""),
        "ticker": ticker,
        "cik": cik,
        "revenue_bucket": row.get("revenue_bucket", ""),
        "pipeline_status": row.get("pipeline_status", ""),
        "pipeline_missing_reason": row.get("pipeline_missing_reason", ""),
        "repair_status": repair.get("repair_status", ""),
        "repair_notes": repair.get("fetch_notes", ""),
        "event_accession": event_accession,
        "event_dates": event_dates,
        "primary_8k_doc": primary_doc,
        "primary_8k_cached": str(primary_cached),
        "primary_8k_text_len": primary.get("text_len", 0),
        "exhibit_docs": ";".join(exhibit_docs),
        "exhibit_cached_count": exhibit_cached_count,
        "exhibit_doc_count": len(exhibit_docs),
        "exhibit_text_len": exhibit_text_len,
        "periodic_accession": periodic_accession,
        "periodic_doc": periodic_doc,
        "periodic_cached": str(periodic_cached),
        "periodic_text_len": periodic.get("text_len", 0),
        "earnings_event_ready_for_local_extraction": str(
            primary_cached and exhibit_cached_count > 0 and exhibit_text_len >= 1500
        ),
        "periodic_doc_ready": str(periodic_cached),
        "coverage_reasons": ";".join(reasons) if reasons else "ready",
        "periodic_reasons": ";".join(periodic_reasons) if periodic_reasons else "ready",
    }
    return audit, fetch_plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit cached filing coverage and create missing-doc fetch plan")
    parser.add_argument("--input", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--repair-report", type=Path, default=DEFAULT_REPAIR_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fetch-plan", type=Path, default=DEFAULT_FETCH_PLAN)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_csv(args.input)
    metadata_rows = read_csv(args.metadata) if args.metadata.exists() else []
    metadata_by_ticker = {row["ticker"]: row for row in metadata_rows}
    repair_rows = read_csv(args.repair_report) if args.repair_report.exists() else []
    repair_by_ticker = {row["ticker"]: row for row in repair_rows}
    audits: list[dict[str, Any]] = []
    fetch_plan: list[dict[str, Any]] = []
    for row in rows:
        audit, missing = audit_row(row, metadata_by_ticker, repair_by_ticker)
        audits.append(audit)
        fetch_plan.extend(missing)
    write_csv(args.output, audits)
    write_csv(args.fetch_plan, fetch_plan)
    ready = sum(row["earnings_event_ready_for_local_extraction"] == "True" for row in audits)
    print(f"rows={len(audits)} earnings_event_ready_for_local_extraction={ready} not_ready={len(audits)-ready}")
    reason_counts: dict[str, int] = {}
    for row in audits:
        if row["coverage_reasons"] == "ready":
            continue
        for reason in str(row["coverage_reasons"]).split(";"):
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"{reason}: {count}")
    periodic_ready = sum(row["periodic_doc_ready"] == "True" for row in audits)
    print(f"periodic_doc_ready={periodic_ready} periodic_doc_not_ready={len(audits)-periodic_ready}")
    print(f"fetch_plan_rows={len(fetch_plan)}")
    print(f"wrote {args.output}")
    print(f"wrote {args.fetch_plan}")


if __name__ == "__main__":
    main()
