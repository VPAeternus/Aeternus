from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from tradingagents.research.fundamental.src.features.llm_packets import build_llm_packets


DEFAULT_PANEL_CSV = Path(
    "outputs/fundamental_backtest/full_complete_panel_2021Q4_2026Q2/"
    "fundamental_complete_prellm_to_top15_2021Q4_2026Q2.csv"
)

MISSING_ROWS_CSV = "historical_llm_backfill_missing_required_rows.csv"
TICKER_LIST_TXT = "historical_llm_backfill_missing_tickers.txt"
SUMMARY_JSON = "historical_llm_backfill_summary.json"
MANIFEST_JSONL = "historical_llm_backfill_missing_manifest.jsonl"
EVIDENCE_PACKETS_JSONL = "historical_llm_backfill_evidence_packets.jsonl"
EVIDENCE_MISSING_CSV = "historical_llm_backfill_evidence_missing.csv"
DEFAULT_SEC_TEXT_ROOT = Path("/Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/sec_docs_text")
EARNINGS_EVIDENCE_FILENAME_TOKENS = (
    "ex99",
    "ex-99",
    "ex_99",
    "exhibit99",
    "exhibit991",
    "earningsrelease",
    "earningsreleaseng",
    "earnings_release",
    "pressrelease",
    "pressrele",
    "press_release",
    "earningsslides",
    "earningspresentation",
    "earningspresentat",
    "earnings991",
    "prearnings",
)
PACKET_ALLOWED_COLUMNS = {
    "ticker",
    "quarter",
    "symbol",
    "cik",
    "company_title",
    "company_name",
    "sector",
    "industry",
    "pre_llm_fundamental_score",
    "pre_llm_fundamental_bucket",
    "pre_llm_score",
    "pre_llm_bucket",
    "tier_1_bucket",
    "tier_2_bucket",
    "tier_3_bucket",
    "tier_4_bucket",
    "hp_production_extension",
    "hp_research_extension",
    "repricing_momentum_extension",
    "repricing_momentum_bucket",
    "hp_bucket",
    "rm_bucket",
    "missing_critical_llm_fields",
    "research_priority",
}


def _quarter_key(value: str) -> tuple[int, int]:
    text = str(value).strip().upper()
    if len(text) != 6 or text[4] != "Q":
        raise ValueError(f"quarter must be YYYYQ#, got {value!r}")
    year = int(text[:4])
    quarter = int(text[5])
    if quarter not in {1, 2, 3, 4}:
        raise ValueError(f"quarter must be YYYYQ1-YYYYQ4, got {value!r}")
    return year, quarter


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _flag(value: Any) -> bool | None:
    text = _clean(value).lower()
    if text == "":
        return None
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    if text in {"0", "false", "f", "no", "n"}:
        return False
    return None


def _is_required(row: dict[str, Any]) -> bool:
    primary = _flag(row.get("llm_required_derived_flag"))
    if primary is not None:
        return primary
    fallback = _flag(row.get("llm_required_for_full_buy_flag"))
    return bool(fallback)


def _is_complete(row: dict[str, Any]) -> bool:
    primary = _flag(row.get("llm_complete_derived_flag"))
    if primary is not None:
        return primary
    return _clean(row.get("llm_status")).lower() == "complete"


def _in_range(row: dict[str, Any], start_key: tuple[int, int], end_key: tuple[int, int]) -> bool:
    quarter = _quarter_key(_clean(row.get("quarter")))
    return start_key <= quarter <= end_key


def _sample_id(row: dict[str, Any]) -> str:
    return f"{_clean(row.get('ticker')).upper()}_{_clean(row.get('quarter')).upper()}"


def _write_missing_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _accession_no_dashes(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", _clean(value))


def _doc_filename(ticker: str, accession: str, document_name: str) -> str:
    return f"{ticker}_{_accession_no_dashes(accession)}_{Path(_clean(document_name)).name}.txt"


def _read_document(path: Path, row: dict[str, Any], document_type: str, accession: str = "", document_name: str = "") -> dict[str, Any] | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return None
    return {
        "ticker": _clean(row.get("ticker")).upper(),
        "quarter": _clean(row.get("quarter")).upper(),
        "document_type": document_type,
        "accession": accession,
        "document_name": document_name or path.name,
        "document_url": str(path),
        "clean_text": text,
        "raw_text": text,
    }


def _linked_document_paths(row: dict[str, Any], sec_text_root: Path) -> list[tuple[Path, str, str, str]]:
    ticker = _clean(row.get("ticker")).upper()
    accession = _clean(row.get("earnings_8k_accession"))
    out: list[tuple[Path, str, str, str]] = []
    text_path = _clean(row.get("text_path"))
    if text_path:
        path = Path(text_path)
        document_type = _explicit_document_type(path)
        if document_type is not None:
            out.append((path if path.is_absolute() else sec_text_root / path, document_type, accession, path.name))
    for column, document_type in (
        ("earnings_exhibit_document", "earnings_exhibit"),
        ("earnings_8k_primary_document", "primary_8k"),
    ):
        document_name = _clean(row.get(column))
        path = sec_text_root / _doc_filename(ticker, accession, document_name)
        guarded_type = _explicit_document_type(path, fallback=document_type)
        if ticker and accession and document_name and guarded_type is not None:
            out.append((path, guarded_type, accession, document_name))
    return out


def _quarter_filename_tokens(quarter: str) -> list[str]:
    year = quarter[:4]
    q = quarter[-1]
    yy = year[-2:]
    return [
        f"q{q}x{year}",
        f"q{q}-{year}",
        f"q{q}_{year}",
        f"q{q}{year}",
        f"{year}q{q}",
        f"{year}-q{q}",
        f"{year}_q{q}",
        f"{q}q{yy}",
        f"q{q}{yy}",
        f"{q}q{year}",
        f"q{q}x{yy}",
    ]


def _is_generic_periodic(name: str) -> bool:
    return any(token in name for token in ("10q", "10-q", "10k", "10-k"))


def _explicit_document_type(path: Path, fallback: str | None = None) -> str | None:
    name = path.name.lower()
    if _is_generic_periodic(name):
        return None
    if any(token in name for token in EARNINGS_EVIDENCE_FILENAME_TOKENS):
        return "earnings_exhibit"
    if any(token in name for token in ("_8k", "-8k", "d8k", "8-k")):
        return "primary_8k"
    return fallback


def _fallback_document_type(path: Path, quarter: str) -> str | None:
    name = path.name.lower()
    if _is_generic_periodic(name):
        return None
    if not any(token in name for token in _quarter_filename_tokens(quarter.lower())):
        return None
    if any(token in name for token in EARNINGS_EVIDENCE_FILENAME_TOKENS):
        return "earnings_exhibit"
    if any(token in name for token in ("_8k", "-8k", "d8k", "8-k")):
        return "primary_8k"
    return None


def _evidence_documents_for_row(row: dict[str, Any], sec_text_root: Path) -> list[dict[str, Any]]:
    seen: set[Path] = set()
    docs: list[dict[str, Any]] = []
    for path, document_type, accession, document_name in _linked_document_paths(row, sec_text_root):
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        doc = _read_document(path, row, document_type, accession=accession, document_name=document_name)
        if doc is not None:
            docs.append(doc)
            seen.add(resolved)
    if docs:
        return docs

    ticker = _clean(row.get("ticker")).upper()
    quarter = _clean(row.get("quarter")).upper()
    if not ticker or not sec_text_root.is_dir():
        return docs
    for path in sorted(sec_text_root.glob(f"{ticker}_*.txt")):
        resolved = path.resolve()
        if resolved in seen:
            continue
        document_type = _fallback_document_type(path, quarter)
        if document_type is None:
            continue
        doc = _read_document(path, row, document_type)
        if doc is not None:
            docs.append(doc)
            seen.add(resolved)
    return docs


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _sanitize_candidate_for_packet(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if str(key).lower() in PACKET_ALLOWED_COLUMNS}


def validate_historical_post_llm_csv(path: Path, packets_path: Path) -> dict[str, Any]:
    from tradingagents.research.fundamental.src.features.llm_extraction import validate_llm_result

    def _decode_json_fields(row: dict[str, Any]) -> dict[str, Any]:
        decoded = dict(row)
        for field in ("secondary_themes", "theme_tags", "theme_evidence"):
            value = decoded.get(field)
            if not isinstance(value, str) or not value.strip().startswith(("[", "{")):
                continue
            try:
                decoded[field] = json.loads(value)
            except json.JSONDecodeError:
                pass
        return decoded

    packets = [json.loads(line) for line in packets_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    packets_by_id = {str(packet.get("sample_id", "")): packet for packet in packets}
    expected_ids = set(packets_by_id)
    if not path.exists() or path.stat().st_size == 0:
        return {
            "status": "hard_stop",
            "summary": {"reason": "post_llm_missing_or_empty", "expected_count": len(expected_ids), "completed_count": 0},
            "artifacts": {"post_llm_scores": str(path)},
        }
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    seen = [str(row.get("sample_id") or f"{str(row.get('ticker', '')).upper()}_{row.get('quarter', '')}") for row in rows]
    duplicates = sorted({sample_id for sample_id in seen if seen.count(sample_id) > 1})
    missing = sorted(expected_ids - set(seen))
    unexpected = sorted(set(seen) - expected_ids)
    strict_errors: dict[str, str] = {}
    deterministic_mismatches: dict[str, dict[str, dict[str, str]]] = {}
    identity_mismatches: dict[str, dict[str, dict[str, str]]] = {}
    for row, sample_id in zip(rows, seen):
        packet = packets_by_id.get(sample_id)
        if packet is None:
            continue
        identity_errors: dict[str, dict[str, str]] = {}
        for field in ("ticker", "quarter"):
            supplied_identity = _clean(row.get(field))
            if supplied_identity == "":
                continue
            expected_identity = _clean(packet.get(field))
            if field == "ticker":
                supplied_identity = supplied_identity.upper()
                expected_identity = expected_identity.upper()
            if supplied_identity != expected_identity:
                identity_errors[field] = {"supplied": supplied_identity, "expected": expected_identity}
        if identity_errors:
            identity_mismatches[sample_id] = identity_errors
        try:
            normalized = validate_llm_result({**_decode_json_fields(row), "sample_id": sample_id}, packet)
        except Exception as exc:  # noqa: BLE001
            strict_errors[sample_id] = str(exc)
            continue
        for field in (
            "narrative_delta_score",
            "narrative_delta_bucket",
            "score_addition",
            "post_llm_candidate_flag",
            "post_llm_high_priority_flag",
            "post_llm_demote_flag",
            "post_llm_demote_severity",
            "post_llm_demote_reason_code",
            "post_llm_demote_overrideable",
            "theme_acceleration_score",
            "filing_theme_growth_flag",
            "filing_theme_guidance_flag",
            "filing_theme_margin_flag",
            "filing_theme_customer_win_flag",
            "filing_theme_capacity_expansion_flag",
            "theme_tailwind_score",
        ):
            supplied = _clean(row.get(field))
            if supplied == "":
                continue
            expected = _clean(normalized.get(field))
            if supplied != expected:
                deterministic_mismatches.setdefault(sample_id, {})[field] = {
                    "supplied": supplied,
                    "expected": expected,
                }
    status = "pass" if not duplicates and not missing and not unexpected and not strict_errors and not deterministic_mismatches and not identity_mismatches else "hard_stop"
    summary: dict[str, Any] = {
        "expected_count": len(expected_ids),
        "completed_count": len(rows),
        "missing_sample_ids": missing,
        "duplicate_sample_ids": duplicates,
        "unexpected_sample_ids": unexpected,
    }
    if strict_errors:
        summary["strict_value_errors"] = strict_errors
        summary["reason"] = "post_llm_invalid_values"
    if deterministic_mismatches:
        summary["deterministic_mismatches"] = deterministic_mismatches
        summary["reason"] = "post_llm_deterministic_mismatch"
    if identity_mismatches:
        summary["identity_mismatches"] = identity_mismatches
        summary["reason"] = "post_llm_identity_mismatch"
    return {"status": status, "summary": summary, "artifacts": {"post_llm_scores": str(path)}}


def prepare_historical_llm_backfill(
    *,
    panel_csv: str | Path = DEFAULT_PANEL_CSV,
    start_quarter: str = "2021Q4",
    end_quarter: str = "2026Q2",
    output_root: str | Path | None = None,
    sec_text_root: str | Path = DEFAULT_SEC_TEXT_ROOT,
) -> dict[str, Any]:
    """Prepare historical LLM backfill artifacts and evidence packets when source text exists."""
    panel_path = Path(panel_csv)
    if not panel_path.is_file():
        raise FileNotFoundError(f"panel CSV not found: {panel_path}")

    start = start_quarter.strip().upper()
    end = end_quarter.strip().upper()
    start_key = _quarter_key(start)
    end_key = _quarter_key(end)
    if start_key > end_key:
        raise ValueError("start quarter must be before or equal to end quarter")

    out_root = Path(output_root) if output_root is not None else Path(
        f"eval_results/fundamental/llm_backfill_{start}_{end}"
    )
    out_root.mkdir(parents=True, exist_ok=True)

    with panel_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = [{key: value for key, value in row.items() if key is not None} for row in reader]

    scanned_rows = [row for row in rows if _in_range(row, start_key, end_key)]
    missing_rows = [
        row
        for row in scanned_rows
        if _is_required(row) and not _is_complete(row)
    ]
    counts_by_quarter = dict(sorted(Counter(_clean(row.get("quarter")).upper() for row in missing_rows).items()))
    missing_tickers = sorted({_clean(row.get("ticker")).upper() for row in missing_rows if _clean(row.get("ticker"))})

    missing_rows_path = out_root / MISSING_ROWS_CSV
    ticker_list_path = out_root / TICKER_LIST_TXT
    summary_path = out_root / SUMMARY_JSON
    manifest_path = out_root / MANIFEST_JSONL
    evidence_packets_path = out_root / EVIDENCE_PACKETS_JSONL
    evidence_missing_path = out_root / EVIDENCE_MISSING_CSV

    _write_missing_rows(missing_rows_path, missing_rows, fieldnames)
    ticker_list_path.write_text("\n".join(missing_tickers) + ("\n" if missing_tickers else ""), encoding="utf-8")
    sec_text_path = Path(sec_text_root)
    documents: list[dict[str, Any]] = []
    for row in missing_rows:
        documents.extend(_evidence_documents_for_row(row, sec_text_path))
    sanitized_candidates = [_sanitize_candidate_for_packet(row) for row in missing_rows]
    all_packets = build_llm_packets(sanitized_candidates, documents)
    evidence_packets = [packet for packet in all_packets if packet.get("evidence_snippets")]
    packet_ids = {str(packet.get("sample_id", "")) for packet in evidence_packets}
    evidence_missing_rows = [
        {
            "sample_id": _sample_id(row),
            "ticker": _clean(row.get("ticker")).upper(),
            "quarter": _clean(row.get("quarter")).upper(),
            "reason": "source_text_not_found_or_empty",
        }
        for row in missing_rows
        if _sample_id(row) not in packet_ids
    ]
    _write_jsonl(evidence_packets_path, evidence_packets)
    _write_missing_rows(evidence_missing_path, evidence_missing_rows, ["sample_id", "ticker", "quarter", "reason"])

    summary = {
        "panel_csv": str(panel_path),
        "sec_text_root": str(sec_text_path),
        "start_quarter": start,
        "end_quarter": end,
        "total_panel_rows": len(rows),
        "scanned_rows": len(scanned_rows),
        "missing_required_count": len(missing_rows),
        "unique_missing_tickers": len(missing_tickers),
        "evidence_packet_count": len(evidence_packets),
        "evidence_missing_count": len(evidence_missing_rows),
        "llm_runnable_count": len(evidence_packets),
        "counts_by_quarter": counts_by_quarter,
        "note": "Missing-row manifest is not final LLM evidence packets. Use historical_llm_backfill_evidence_packets.jsonl for runnable packets when evidence_packet_count is greater than zero.",
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with manifest_path.open("w", encoding="utf-8") as handle:
        for row in missing_rows:
            packet_stub = {
                "sample_id": _sample_id(row),
                "ticker": _clean(row.get("ticker")).upper(),
                "quarter": _clean(row.get("quarter")).upper(),
                "panel_row": row,
            }
            handle.write(json.dumps(packet_stub, sort_keys=True) + "\n")

    output_paths = {
        "missing_rows_csv": MISSING_ROWS_CSV,
        "ticker_list_txt": TICKER_LIST_TXT,
        "summary_json": SUMMARY_JSON,
        "manifest_jsonl": MANIFEST_JSONL,
        "evidence_packets_jsonl": EVIDENCE_PACKETS_JSONL,
        "evidence_missing_csv": EVIDENCE_MISSING_CSV,
    }
    return {
        "summary": summary,
        "missing_tickers": missing_tickers,
        "output_root": str(out_root),
        "output_paths": output_paths,
    }
