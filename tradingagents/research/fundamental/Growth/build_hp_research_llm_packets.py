from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GROWTH = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(GROWTH) not in sys.path:
    sys.path.insert(0, str(GROWTH))

from spec_convex_llm_testset import (
    PACKET_FIELDS,
    SELECTION_FIELDS,
    best_text_doc,
    clean,
    extract_evidence_snippets,
    first_semicolon_value,
    output_path,
    read_csv,
    write_csv,
)


BASE = ROOT / "Growth" / "earnings_8k_sec_parser"
DEFAULT_INPUT = BASE / "combined_all_tiers_hp_extensions_llm_rank_scores_2021Q4_2026Q1_partial.csv"
DEFAULT_OUTPUT_PREFIX = BASE / "llm_hp_research_missing_2021Q4_2026Q1_partial_gpt55_medium"

HP_FIELDS = [
    "hp1_quality_pullback",
    "hp2_dislocation_momentum_priority",
    "hp2_dislocation_momentum_watch",
    "hp3_large_quality_theme_exception",
    "hp4_score_reacceleration_watch",
    "hp_production_extension",
    "hp_research_extension",
]

RM_FIELDS = [
    "rm1_low_price_dislocation_momentum",
    "rm2_weak_acceleration",
    "rm3_mid_price_dislocation_momentum",
    "rm4_persistent_repricing_wave",
    "repricing_momentum_extension",
    "repricing_momentum_priority",
    "market_repricing_score",
]

LLM_TRIGGER_FIELDS = [
    "force_llm_extraction",
    "repricing_started",
    "repricing_confirmed",
    "tier_1_bucket",
    "tier_2_bucket",
    "tier_3_bucket",
    "tier_4_bucket",
]


def _read_csv_if_exists(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _packet_from_record(record: dict[str, Any]) -> dict[str, Any]:
    return {field: record.get(field, "") for field in PACKET_FIELDS}


def _candidate_audit_paths(base_dir: Path, quarter: str) -> list[Path]:
    paths = [
        base_dir / f"sec_quarter_cache_audit_{quarter}_prod.csv",
        base_dir / f"sec_quarter_cache_audit_{quarter}.csv",
    ]
    paths.extend(sorted((base_dir / "add_ticker").glob(f"*/sec_quarter_cache_audit*{quarter}.csv")))
    existing = [path for path in paths if path.exists()]
    return sorted(existing, key=lambda path: path.stat().st_mtime, reverse=True)


def _fetch_path_for_audit(path: Path) -> Path | None:
    candidates = [
        Path(str(path).replace("sec_quarter_cache_audit", "sec_quarter_cache_fetch_report")),
        path.with_name(path.name.replace("audit", "fetch_report")),
    ]
    return next((candidate for candidate in candidates if candidate.exists()), None)


def _audit_and_fetch_for_ticker(base_dir: Path, quarter: str, ticker: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    fallback: tuple[dict[str, str], list[dict[str, str]]] = ({}, [])
    for audit_path in _candidate_audit_paths(base_dir, quarter):
        audit_rows = _read_csv_if_exists(audit_path)
        audit = next((row for row in audit_rows if clean(row.get("ticker")).upper() == ticker.upper()), None)
        if audit is None:
            continue
        fetch_path = _fetch_path_for_audit(audit_path)
        fetch_rows = _read_csv_if_exists(fetch_path) if fetch_path else []
        if fallback[0] == {}:
            fallback = (audit, fetch_rows)
        if first_semicolon_value(audit.get("item_202_accessions")) and fetch_rows:
            return audit, fetch_rows
    return fallback


def _selected_rows(input_csv: Path, tickers: set[str]) -> list[dict[str, str]]:
    rows = read_csv(input_csv)
    output = []
    for row in rows:
        ticker = clean(row.get("ticker")).upper()
        if tickers and ticker not in tickers:
            continue
        if clean(row.get("has_post_llm")) == "1":
            continue
        force_trigger = any(_truthy(row.get(field)) for field in [*LLM_TRIGGER_FIELDS, "hp_production_extension", "hp_research_extension", "repricing_momentum_extension"])
        if not force_trigger:
            continue
        output.append(row)
    return sorted(output, key=lambda row: (clean(row.get("quarter")), clean(row.get("ticker"))))


def _truthy(value: Any) -> bool:
    text = clean(value).strip()
    return text not in {"", "0", "0.0", "false", "False", "FALSE", "nan", "NaN", "None"}


def build_records(
    input_csv: Path,
    *,
    base_dir: Path,
    tickers: set[str],
    sample_prefix: str,
    max_snippets: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in _selected_rows(input_csv, tickers):
        quarter = clean(row.get("quarter"))
        ticker = clean(row.get("ticker")).upper()
        audit, fetch_rows = _audit_and_fetch_for_ticker(base_dir, quarter, ticker)
        accession = first_semicolon_value(audit.get("item_202_accessions"))
        event_date = first_semicolon_value(audit.get("item_202_event_dates")) or clean(row.get("event_date"))
        doc = best_text_doc(fetch_rows, ticker=ticker, accession=accession)
        text_path = clean(doc.get("text_path"))
        quality_flags: list[str] = []
        text = ""
        path = Path(text_path) if text_path else None
        if not accession:
            quality_flags.append("missing_accession")
        if not text_path:
            quality_flags.append("missing_text_path")
        elif path and not path.exists():
            quality_flags.append("text_path_not_found")
        else:
            text = path.read_text(encoding="utf-8", errors="ignore") if path else ""
        snippets = extract_evidence_snippets(text, limit=max_snippets) if text else []
        if not snippets:
            quality_flags.append("missing_evidence_snippets")

        records.append(
            {
                "quarter": quarter,
                "ticker": ticker,
                "event_date": event_date,
                "revenue_bucket": row.get("revenue_bucket", ""),
                "pre_llm_fundamental_bucket": row.get("pre_llm_fundamental_bucket", ""),
                "pre_llm_fundamental_score": row.get("pre_llm_fundamental_score", ""),
                "score_change": row.get("score_change", ""),
                "entry_qoq_pct": row.get("entry_qoq_pct", ""),
                "profitability_score": row.get("profitability_score", ""),
                "operating_cash_flow_score": row.get("operating_cash_flow_score", ""),
                "financing_dependence_score": row.get("financing_dependence_score", ""),
                "tradable_date": row.get("tradable_date", ""),
                "entry_open": row.get("entry_open", ""),
                "return_10d_pct": row.get("return_10d_pct", ""),
                "return_20d_pct": row.get("return_20d_pct", ""),
                "return_30d_pct": row.get("return_30d_pct", ""),
                "return_60d_pct": row.get("return_60d_pct", ""),
                "return_90d_pct": row.get("return_90d_pct", ""),
                "tier_bucket": row.get("tier_bucket", ""),
                "tier_1_bucket": row.get("tier_1_bucket", ""),
                "tier_2_bucket": row.get("tier_2_bucket", ""),
                "tier_3_bucket": row.get("tier_3_bucket", ""),
                "tier_4_bucket": row.get("tier_4_bucket", ""),
                "accession": accession,
                "exhibit_doc": doc.get("document", ""),
                "source_doc_type": doc.get("doc_type", ""),
                "text_len": doc.get("text_len", ""),
                "text_path": text_path,
                "snippet_count": len(snippets),
                "quality_flags": ";".join(quality_flags),
                "evidence_snippets": snippets,
                **{field: row.get(field, "") for field in [*HP_FIELDS, *RM_FIELDS, *LLM_TRIGGER_FIELDS]},
            }
        )

    for idx, record in enumerate(records, start=1):
        record["sample_id"] = f"{sample_prefix}{idx:06d}"
    return records


def write_packet_outputs(records: list[dict[str, Any]], output_prefix: Path) -> None:
    selection_fields = list(dict.fromkeys([*SELECTION_FIELDS, "score_change", "entry_qoq_pct", *HP_FIELDS, *RM_FIELDS, *LLM_TRIGGER_FIELDS]))
    write_csv(output_path(output_prefix, "_selection.csv"), records, selection_fields)

    with output_path(output_prefix, "_packets.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(_packet_from_record(record), ensure_ascii=True) + "\n")

    quality_rows = [
        {"metric": "records", "value": len(records)},
        {"metric": "missing_accession", "value": sum("missing_accession" in clean(r.get("quality_flags")) for r in records)},
        {"metric": "missing_text_path", "value": sum("missing_text_path" in clean(r.get("quality_flags")) for r in records)},
        {"metric": "text_path_not_found", "value": sum("text_path_not_found" in clean(r.get("quality_flags")) for r in records)},
        {
            "metric": "missing_evidence_snippets",
            "value": sum("missing_evidence_snippets" in clean(r.get("quality_flags")) for r in records),
        },
    ]
    write_csv(output_path(output_prefix, "_quality_report.csv"), quality_rows, ["metric", "value"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build HP research LLM packets for rows missing post-LLM extraction")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--base-dir", type=Path, default=BASE)
    parser.add_argument("--output-prefix", type=Path, default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--tickers", default="")
    parser.add_argument("--sample-prefix", default="HPX")
    parser.add_argument("--max-snippets", type=int, default=18)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tickers = {clean(ticker).upper() for ticker in args.tickers.split(",") if clean(ticker)}
    records = build_records(
        args.input_csv,
        base_dir=args.base_dir,
        tickers=tickers,
        sample_prefix=args.sample_prefix,
        max_snippets=args.max_snippets,
    )
    write_packet_outputs(records, args.output_prefix)
    print(f"wrote {len(records)} HP research LLM packets with prefix {args.output_prefix}")


if __name__ == "__main__":
    main()
