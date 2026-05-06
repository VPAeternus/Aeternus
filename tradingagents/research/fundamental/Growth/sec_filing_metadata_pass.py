from __future__ import annotations

import argparse
import csv
import gzip
import json
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.config.cache_paths import sec_cache_root


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = sec_cache_root()
SUBMISSIONS_DIR = CACHE_DIR / "sec_submissions"
INDEX_DIR = CACHE_DIR / "sec_archive_indexes"
DEFAULT_INPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "akg_quarter_viability_included_2024Q3.csv"
DEFAULT_OUTPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "sec_filing_metadata_2024Q3.csv"
USER_AGENT = "AeternusAutoResearch/1.0 contact@aeternus.local"


def quarter_bounds(quarter: str) -> tuple[date, date]:
    year = int(quarter[:4])
    q = int(quarter[-1])
    start_month = (q - 1) * 3 + 1
    start = date(year, start_month, 1)
    end_month = start_month + 2
    end = date(year, 12, 31) if end_month == 12 else date(year, end_month + 1, 1)
    if end_month != 12:
        end = date.fromordinal(end.toordinal() - 1)
    return start, end


def request_json(url: str, *, timeout: int = 30) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"})
    with urlopen(req, timeout=timeout) as response:
        payload = response.read()
        if response.headers.get("Content-Encoding", "").lower() == "gzip" or payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
        return json.loads(payload.decode("utf-8"))


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


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def submissions_path(cik: str) -> Path:
    return SUBMISSIONS_DIR / f"CIK{str(cik).zfill(10)}.json"


def archive_index_path(cik: str, accession: str) -> Path:
    compact = accession.replace("-", "")
    return INDEX_DIR / str(cik).zfill(10) / f"{compact}.json"


def fetch_submissions(cik: str, *, force: bool = False) -> dict[str, Any] | None:
    SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = submissions_path(cik)
    if path.exists() and not force:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    try:
        payload = request_json(f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json")
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return payload
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None


def fetch_archive_index(cik: str, accession: str, *, force: bool = False) -> dict[str, Any] | None:
    path = archive_index_path(cik, accession)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    compact = accession.replace("-", "")
    try:
        payload = request_json(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{compact}/index.json")
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return payload
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def recent_filings(submissions: dict[str, Any]) -> list[dict[str, str]]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    rows: list[dict[str, str]] = []
    for idx, form in enumerate(forms):
        def get(name: str) -> str:
            values = recent.get(name, [])
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


def has_ex99_1(cik: str, accession: str, *, force_index: bool, sleep_seconds: float) -> tuple[bool, str]:
    index = fetch_archive_index(cik, accession, force=force_index)
    time.sleep(sleep_seconds)
    if not index:
        return False, ""
    names = [
        str(item.get("name", ""))
        for item in index.get("directory", {}).get("item", [])
    ]
    ignored_suffixes = (".xml", ".xsd", ".css", ".js", ".jpg", ".png", ".xlsx", ".zip", ".txt")
    ignored_names = ("index", "headers", "filingsummary", "metalinks", "r1")
    release_terms = ("ex99", "exhibit99", "press", "release", "earn", "result", "shareholder", "letter", "cfo", "pr")
    matches: list[str] = []
    for name in names:
        low = name.lower()
        stem = low.rsplit(".", 1)[0]
        normalized = stem.replace("-", "").replace("_", "")
        if low.endswith(ignored_suffixes):
            continue
        if any(token in normalized for token in ignored_names):
            continue
        if any(term in normalized for term in release_terms):
            matches.append(name)
    return bool(matches), ";".join(matches)


def summarize_ticker(
    ticker_row: dict[str, str],
    quarter: str,
    *,
    force_submissions: bool,
    force_index: bool,
    sleep_seconds: float,
) -> dict[str, Any]:
    start, end = quarter_bounds(quarter)
    ticker = ticker_row["ticker"]
    cik = ticker_row.get("cik", "")
    base: dict[str, Any] = {
        "quarter": quarter,
        "ticker": ticker,
        "cik": cik,
        "metadata_status": "",
        "has_10q_10k_before_or_in_qtr": "False",
        "latest_10q_10k_form": "",
        "latest_10q_10k_filing_date": "",
        "latest_10q_10k_accession": "",
        "item_202_8k_count_in_qtr": 0,
        "item_202_8k_with_ex99_count": 0,
        "item_202_8k_dates": "",
        "item_202_8k_accessions": "",
        "ex99_1_documents": "",
        "passes_metadata_gate": "False",
        "metadata_gate_reason": "",
    }
    if not cik:
        base["metadata_status"] = "missing_cik"
        base["metadata_gate_reason"] = "missing_cik"
        return base
    submissions = fetch_submissions(cik, force=force_submissions)
    time.sleep(sleep_seconds)
    if not submissions:
        base["metadata_status"] = "missing_submissions"
        base["metadata_gate_reason"] = "missing_submissions"
        return base
    filings = recent_filings(submissions)
    periodic = [
        row for row in filings
        if row["form"] in {"10-Q", "10-K"}
        and parse_date(row["filing_date"])
        and parse_date(row["filing_date"]) <= end
    ]
    periodic.sort(key=lambda row: row["filing_date"])
    if periodic:
        latest = periodic[-1]
        base["has_10q_10k_before_or_in_qtr"] = "True"
        base["latest_10q_10k_form"] = latest["form"]
        base["latest_10q_10k_filing_date"] = latest["filing_date"]
        base["latest_10q_10k_accession"] = latest["accession"]

    item_202 = [
        row for row in filings
        if row["form"] in {"8-K", "8-K/A"}
        and "2.02" in row.get("items", "")
        and parse_date(row["filing_date"])
        and start <= parse_date(row["filing_date"]) <= end  # type: ignore[operator]
    ]
    item_202.sort(key=lambda row: row["filing_date"])

    ex_docs: list[str] = []
    with_ex99 = 0
    for row in item_202:
        has_ex, docs = has_ex99_1(cik, row["accession"], force_index=force_index, sleep_seconds=sleep_seconds)
        if has_ex:
            with_ex99 += 1
            ex_docs.extend(docs.split(";") if docs else [])

    base["metadata_status"] = "ok"
    base["item_202_8k_count_in_qtr"] = len(item_202)
    base["item_202_8k_with_ex99_count"] = with_ex99
    base["item_202_8k_dates"] = ";".join(row["filing_date"] for row in item_202)
    base["item_202_8k_accessions"] = ";".join(row["accession"] for row in item_202)
    base["ex99_1_documents"] = ";".join(ex_docs)

    reasons: list[str] = []
    if not periodic:
        reasons.append("missing_10q_10k_before_or_in_qtr")
    if not item_202:
        reasons.append("missing_8k_item_202_in_qtr")
    if item_202 and with_ex99 == 0:
        reasons.append("missing_ex99_1_for_item_202")
    base["passes_metadata_gate"] = str(not reasons)
    base["metadata_gate_reason"] = ";".join(reasons) if reasons else "included"
    return base


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SEC filing metadata pass; no filing document extraction")
    parser.add_argument("--quarter", default="2024Q3")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--force-submissions", action="store_true")
    parser.add_argument("--force-index", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_rows(args.input)
    if args.limit is not None:
        rows = rows[: args.limit]
    output_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        result = summarize_ticker(
            row,
            args.quarter,
            force_submissions=args.force_submissions,
            force_index=args.force_index,
            sleep_seconds=args.sleep,
        )
        output_rows.append(result)
        if idx % 25 == 0 or result["passes_metadata_gate"] == "True":
            print(
                f"{idx}/{len(rows)} {result['ticker']} status={result['metadata_status']} "
                f"8k202={result['item_202_8k_count_in_qtr']} ex99={result['item_202_8k_with_ex99_count']} "
                f"pass={result['passes_metadata_gate']}",
                flush=True,
            )
    write_csv(args.output, output_rows)
    included = sum(row["passes_metadata_gate"] == "True" for row in output_rows)
    reasons: dict[str, int] = {}
    for row in output_rows:
        if row["passes_metadata_gate"] == "True":
            continue
        for reason in str(row["metadata_gate_reason"]).split(";"):
            reasons[reason] = reasons.get(reason, 0) + 1
    print(f"quarter={args.quarter} tickers={len(output_rows)} passes_metadata_gate={included}")
    for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0])):
        print(f"{reason}: {count}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
