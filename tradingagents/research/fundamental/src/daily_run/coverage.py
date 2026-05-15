from __future__ import annotations

import csv
import contextlib
import io
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from tradingagents.research.fundamental.src.config.cache_paths import sec_cache_root

from .artifacts import write_text_atomic
from .models import GateResult, GateStatus


def should_continue_fetch(*, fetch_queue_count: int, missing_input_counts: Mapping[str, int]) -> bool:
    return fetch_queue_count > 0


def classify_coverage_summary(*, ticker_count: int, companyfacts_ready_count: int, coverage_status_counts: Mapping[str, int], missing_input_counts: Mapping[str, int], fetch_queue_count: int, blocked_tickers: list[str]) -> dict[str, Any]:
    pre_llm_blocked = companyfacts_ready_count < max(1, int(ticker_count * 0.90))
    return {"ticker_count": ticker_count, "companyfacts_ready_count": companyfacts_ready_count, "llm_doc_ready_count": int(coverage_status_counts.get("CACHED_READY", 0)), "coverage_status_counts": dict(coverage_status_counts), "missing_input_counts": dict(missing_input_counts), "fetch_queue_count": fetch_queue_count, "blocked_tickers": blocked_tickers, "pre_llm_blocked": pre_llm_blocked, "remaining_work_type": "fetchable" if fetch_queue_count else "metadata_or_parser_routing", "gate_status": (GateStatus.HARD_STOP if pre_llm_blocked else GateStatus.PASS).value}


def normalize_coverage_summary(raw: Mapping[str, Any], *, universe_count: int, companyfacts_ready_count: int) -> dict[str, Any]:
    summary = classify_coverage_summary(ticker_count=int(raw.get("ticker_count") or universe_count), companyfacts_ready_count=companyfacts_ready_count, coverage_status_counts=raw.get("status_counts", {}) or raw.get("coverage_status_counts", {}), missing_input_counts=raw.get("missing_input_counts", {}), fetch_queue_count=int(raw.get("fetch_queue_count", 0) or 0), blocked_tickers=list(raw.get("blocked_tickers", []) or []))
    summary["outputs"] = dict(raw.get("outputs", {}) or {})
    return summary


def run_sec_coverage_manifest(*, out_root: Path, universe_csv: Path, eligible_json: Path, quarter: str, live_sec_root: Path, as_of: str | None = None) -> dict[str, Any]:
    from tradingagents.research.fundamental.src.sec_pipeline import cache_coverage_manifest as manifest
    out_root.mkdir(parents=True, exist_ok=True)
    target = out_root / "final_dealflow_tickers_sec_eligible.json"
    if eligible_json.resolve() != target.resolve():
        shutil.copy2(eligible_json, target)
    manifest.configure(out=out_root, live=live_sec_root, quarters=[quarter], as_of=as_of); manifest.UNIVERSE_CSV = universe_csv; manifest.TICKERS_JSON = target
    with contextlib.redirect_stdout(io.StringIO()):
        manifest.main()
    summary_path = out_root / "sec_coverage_summary.json"
    return json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {"ticker_count": 0, "status_counts": {}, "missing_input_counts": {}, "fetch_queue_count": 0, "outputs": {}}


def run_sec_fetch_once(*, out_root: Path, live_sec_root: Path) -> dict[str, Any]:
    from tradingagents.research.fundamental.src.sec_pipeline import cache_download_queue as download
    download.configure(out=out_root, live=live_sec_root); download.DOWNLOAD_MANIFEST_PATH = out_root / "sec_download_manifest_daily_run.json"
    with contextlib.redirect_stdout(io.StringIO()):
        download.main()
    return json.loads(download.DOWNLOAD_MANIFEST_PATH.read_text(encoding="utf-8"))


def coverage_gate_result(summary: Mapping[str, Any], *, artifact_paths: Mapping[str, str]) -> GateResult:
    return GateResult(3, "Filing and companyfacts coverage", GateStatus(summary.get("gate_status", GateStatus.PASS.value)), dict(summary), dict(artifact_paths))


def _default_document_roots() -> list[Path]:
    return [
        sec_cache_root("sec_docs_text"),
        sec_cache_root("sec_docs_html"),
        sec_cache_root("earnings_8k_raw"),
    ]


def _find_extra_document(file_name: str, ticker: str, roots: list[Path]) -> Path | None:
    for root in roots:
        if not root.exists():
            continue
        direct = root / file_name
        if direct.exists():
            return direct
        ticker_root = root / ticker
        ticker_direct = ticker_root / file_name
        if ticker_direct.exists():
            return ticker_direct
        if ticker_root.exists():
            for path in ticker_root.rglob(file_name):
                if path.is_file():
                    return path
    return None


def load_raw_documents_from_coverage(
    manifest_csv: Path,
    live_sec_root: Path,
    *,
    extra_document_roots: list[Path] | None = None,
    materialize_to_live: bool = True,
) -> list[dict[str, Any]]:
    try:
        from tradingagents.research.fundamental.src.ingest.documents import classify_doc_quality, html_to_text
    except Exception:
        classify_doc_quality = lambda document_type, clean_text: {}
        html_to_text = lambda raw: raw
    rows: list[dict[str, Any]] = []
    if not manifest_csv.exists():
        return rows
    live_documents_root = live_sec_root / "documents"
    extra_roots = extra_document_roots if extra_document_roots is not None else _default_document_roots()
    with manifest_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            ticker = str(row.get("ticker", "")).upper(); quarter = str(row.get("quarter", ""))
            docs = [("primary_8k", row.get("earnings_8k_accession", ""), row.get("earnings_8k_primary_document", "")), ("earnings_exhibit", row.get("earnings_8k_accession", ""), row.get("earnings_exhibit_document", "")), ("periodic_10q_10k", row.get("periodic_accession", ""), row.get("periodic_primary_document", ""))]
            for document_type, accession, document in docs:
                if not accession or not document: continue
                file_name = f"{ticker}_{accession.replace('-', '')}_{document}"
                path = live_documents_root / file_name
                if not path.exists():
                    path = _find_extra_document(file_name, ticker, extra_roots) or path
                if not path.exists(): continue
                raw = path.read_text(encoding="utf-8", errors="ignore"); clean = html_to_text(raw)
                if materialize_to_live and path.parent != live_documents_root:
                    write_text_atomic(live_documents_root / file_name, raw)
                rows.append({"ticker": ticker, "quarter": quarter, "accession": accession, "document_type": document_type, "document_name": document, "cache_path": str(path), "document_status": "cached_or_fetched", "raw_text": raw, "clean_text": clean, **classify_doc_quality(document_type, clean)})
    return rows
