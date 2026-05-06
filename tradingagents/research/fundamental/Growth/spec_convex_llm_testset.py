from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from statistics import median
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_DIR = ROOT / "Growth" / "earnings_8k_sec_parser"

TARGET_REVENUE_BUCKETS = {"$100M-$500M", "$500M-$1B", "$1B-$2B", "$2B-$10B"}
TARGET_PRE_LLM_BUCKETS = {"weak", "mixed"}

SELECTION_FIELDS = [
    "sample_id",
    "quarter",
    "ticker",
    "event_date",
    "revenue_bucket",
    "pre_llm_fundamental_bucket",
    "pre_llm_fundamental_score",
    "profitability_score",
    "operating_cash_flow_score",
    "financing_dependence_score",
    "tradable_date",
    "entry_open",
    "return_10d_pct",
    "return_20d_pct",
    "return_30d_pct",
    "return_60d_pct",
    "return_90d_pct",
    "accession",
    "exhibit_doc",
    "source_doc_type",
    "text_len",
    "text_path",
    "snippet_count",
    "quality_flags",
]

PACKET_FIELDS = [
    "sample_id",
    "quarter",
    "ticker",
    "event_date",
    "revenue_bucket",
    "pre_llm_fundamental_bucket",
    "pre_llm_fundamental_score",
    "profitability_score",
    "operating_cash_flow_score",
    "financing_dependence_score",
    "evidence_snippets",
]

EXTRACTION_FIELDS = [
    "sample_id",
    "quarter",
    "ticker",
    "event_date",
    "causal_change",
    "proof_alignment",
    "durability",
    "operating_leverage_quality",
    "negative_revision_risk",
    "story_vs_numbers_gap_penalty",
    "narrative_delta_score",
    "narrative_delta_bucket",
    "score_addition",
    "detected_driver_category",
    "detected_driver_name",
    "evidence_positive",
    "evidence_risk",
    "confidence",
    "blocking_issues",
]

POSITIVE_TERMS = re.compile(
    r"\b("
    r"accelerat\w*|adoption|backlog|bookings?|cash flow|customer|demand|ebitda|free cash flow|"
    r"gross margin|guidance|increase[ds]?|margin|momentum|orders?|outlook|pipeline|profitability|"
    r"raise[ds]?|record|recovery|strong|subscription|volume"
    r")\b",
    re.I,
)
NEGATIVE_TERMS = re.compile(
    r"\b("
    r"below|challeng\w*|charge|declin\w*|delay\w*|deteriorat\w*|headwind|impairment|"
    r"inventory|loss|lower|negative|pressure|restructur\w*|risk|shortfall|slow\w*|soft|weak\w*"
    r")\b",
    re.I,
)
HARD_NUMBER_TERMS = re.compile(r"\$?[0-9][0-9,.]*\s?(?:%|percent|million|billion|bps)?", re.I)


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_float(value: object) -> float | None:
    text = clean(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key, "")) for key in fieldnames})


def csv_value(value: object) -> object:
    if isinstance(value, list):
        return " || ".join(clean(item) for item in value)
    return value


def is_spec_convex(row: dict[str, str]) -> bool:
    profitability = parse_float(row.get("profitability_score"))
    return (
        clean(row.get("revenue_bucket")) in TARGET_REVENUE_BUCKETS
        and clean(row.get("pre_llm_fundamental_bucket")) in TARGET_PRE_LLM_BUCKETS
        and profitability == -1.0
    )


def first_semicolon_value(value: object) -> str:
    text = clean(value)
    return clean(text.split(";")[0]) if text else ""


def best_text_doc(fetch_rows: Iterable[dict[str, str]], *, ticker: str, accession: str) -> dict[str, str]:
    candidates = [
        row
        for row in fetch_rows
        if clean(row.get("ticker")).upper() == ticker.upper()
        and clean(row.get("accession")) == accession
        and clean(row.get("text_path"))
    ]
    if not candidates:
        return {}

    def rank(row: dict[str, str]) -> tuple[int, float]:
        doc_type = clean(row.get("doc_type"))
        type_rank = 0 if doc_type == "earnings_exhibit" else 1 if doc_type == "primary_8k" else 2
        text_len = parse_float(row.get("text_len")) or 0
        return (type_rank, -text_len)

    return sorted(candidates, key=rank)[0]


def sentence_candidates(text: str) -> list[str]:
    normalized = clean(text)
    raw_parts = re.split(r"(?<=[.!?])\s+|\n+", normalized)
    return [clean(part) for part in raw_parts if len(clean(part)) >= 40]


def snippet_score(sentence: str) -> int:
    score = 0
    if POSITIVE_TERMS.search(sentence):
        score += 3
    if NEGATIVE_TERMS.search(sentence):
        score += 3
    if HARD_NUMBER_TERMS.search(sentence):
        score += 2
    if re.search(r"\b(guidance|outlook|expects?|forecast|raise[ds]?|lower)\b", sentence, re.I):
        score += 2
    if re.search(r"\b(backlog|bookings?|orders?|pipeline|customer|adoption|demand)\b", sentence, re.I):
        score += 2
    if re.search(r"\b(gross margin|operating margin|ebitda|free cash flow|cash flow|profitability)\b", sentence, re.I):
        score += 2
    return score


def extract_evidence_snippets(text: str, *, limit: int = 18, max_chars: int = 360) -> list[str]:
    scored: list[tuple[int, int, str]] = []
    for idx, sentence in enumerate(sentence_candidates(text)):
        score = snippet_score(sentence)
        if score > 0:
            scored.append((score, idx, sentence[:max_chars]))
    scored.sort(key=lambda item: (-item[0], item[1]))

    snippets: list[str] = []
    seen: set[str] = set()
    for _, _, sentence in scored:
        value = clean(sentence)
        key = value.lower()
        if key in seen:
            continue
        snippets.append(value)
        seen.add(key)
        if len(snippets) >= limit:
            break
    if snippets:
        return snippets
    return [sentence[:max_chars] for sentence in sentence_candidates(text)[: min(limit, 6)]]


def packet_from_record(record: dict[str, object]) -> dict[str, object]:
    return {field: record.get(field, "") for field in PACKET_FIELDS}


def build_records(quarters: list[str], *, base_dir: Path = DEFAULT_BASE_DIR, max_snippets: int = 18) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for quarter in quarters:
        pre_path = base_dir / f"pre_llm_fundamental_score_{quarter}.csv"
        audit_path = base_dir / f"sec_quarter_cache_audit_{quarter}_prod.csv"
        fetch_path = base_dir / f"sec_quarter_cache_fetch_report_{quarter}_prod.csv"
        pre_rows = read_csv(pre_path)
        audit_by_ticker = {clean(row.get("ticker")).upper(): row for row in read_csv(audit_path)}
        fetch_rows = read_csv(fetch_path)

        for row in pre_rows:
            if not is_spec_convex(row):
                continue
            ticker = clean(row.get("ticker")).upper()
            audit = audit_by_ticker.get(ticker, {})
            accession = first_semicolon_value(audit.get("item_202_accessions"))
            event_date = first_semicolon_value(audit.get("item_202_event_dates"))
            doc = best_text_doc(fetch_rows, ticker=ticker, accession=accession)
            text_path = clean(doc.get("text_path"))
            quality_flags: list[str] = []
            text = ""
            path = Path(text_path) if text_path else None
            if not text_path:
                quality_flags.append("missing_text_path")
            elif not path.exists():
                quality_flags.append("text_path_not_found")
            else:
                text = path.read_text(encoding="utf-8", errors="ignore")
            snippets = extract_evidence_snippets(text, limit=max_snippets) if text else []
            if not snippets:
                quality_flags.append("missing_evidence_snippets")

            output.append(
                {
                    "quarter": quarter,
                    "ticker": ticker,
                    "event_date": event_date,
                    "revenue_bucket": row.get("revenue_bucket", ""),
                    "pre_llm_fundamental_bucket": row.get("pre_llm_fundamental_bucket", ""),
                    "pre_llm_fundamental_score": row.get("pre_llm_fundamental_score", ""),
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
                    "accession": accession,
                    "exhibit_doc": doc.get("document", ""),
                    "source_doc_type": doc.get("doc_type", ""),
                    "text_len": doc.get("text_len", ""),
                    "text_path": text_path,
                    "snippet_count": len(snippets),
                    "quality_flags": ";".join(quality_flags),
                    "evidence_snippets": snippets,
                }
            )

    output.sort(key=lambda item: (clean(item.get("quarter")), clean(item.get("ticker"))))
    for idx, row in enumerate(output, start=1):
        row["sample_id"] = f"S{idx:06d}"
    return output


def output_path(output_prefix: Path, suffix: str) -> Path:
    return output_prefix.with_name(output_prefix.name + suffix)


def write_outputs(records: list[dict[str, object]], output_prefix: Path) -> None:
    write_csv(output_path(output_prefix, "_selection.csv"), records, SELECTION_FIELDS)

    packets = [packet_from_record(record) for record in records]
    jsonl_path = output_path(output_prefix, "_packets.jsonl")
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for packet in packets:
            handle.write(json.dumps(packet, ensure_ascii=True) + "\n")

    md_lines = ["# Spec Convex LLM Packets", ""]
    for packet in packets:
        md_lines += [
            f"## {packet['sample_id']} {packet['quarter']} {packet['ticker']}",
            "",
            "Metadata:",
            "```json",
            json.dumps({key: value for key, value in packet.items() if key != "evidence_snippets"}, indent=2),
            "```",
            "",
            "Evidence snippets:",
        ]
        for snippet in packet.get("evidence_snippets", []):
            md_lines.append(f"- {snippet}")
        md_lines.append("")
    output_path(output_prefix, "_packets.md").write_text("\n".join(md_lines), encoding="utf-8")

    template_rows = [{field: record.get(field, "") if field in {"sample_id", "quarter", "ticker", "event_date"} else "" for field in EXTRACTION_FIELDS} for record in records]
    write_csv(output_path(output_prefix, "_extractions_template.csv"), template_rows, EXTRACTION_FIELDS)

    quality_rows = [
        {
            "metric": "records",
            "value": len(records),
        },
        {
            "metric": "missing_evidence_snippets",
            "value": sum(1 for record in records if "missing_evidence_snippets" in clean(record.get("quality_flags"))),
        },
        {
            "metric": "missing_text_path",
            "value": sum(1 for record in records if "missing_text_path" in clean(record.get("quality_flags"))),
        },
    ]
    write_csv(output_path(output_prefix, "_quality_report.csv"), quality_rows, ["metric", "value"])


def float_from_row(row: dict[str, str], key: str) -> float | None:
    return parse_float(row.get(key))


def joined_rows(selection_rows: list[dict[str, str]], extraction_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    selection_by_id = {row["sample_id"]: row for row in selection_rows}
    output: list[dict[str, str]] = []
    for extraction in extraction_rows:
        sample_id = extraction.get("sample_id", "")
        selection = selection_by_id.get(sample_id)
        if not selection:
            continue
        if not clean(extraction.get("narrative_delta_bucket")):
            continue
        output.append({**selection, **extraction})
    return output


def is_candidate(row: dict[str, str]) -> bool:
    risk = float_from_row(row, "negative_revision_risk")
    return clean(row.get("narrative_delta_bucket")) in {"inflecting", "constructive"} and risk is not None and risk <= 3


def is_high_priority(row: dict[str, str]) -> bool:
    score = float_from_row(row, "narrative_delta_score")
    proof = float_from_row(row, "proof_alignment")
    op_leverage = float_from_row(row, "operating_leverage_quality")
    risk = float_from_row(row, "negative_revision_risk")
    return (
        score is not None
        and proof is not None
        and op_leverage is not None
        and risk is not None
        and score >= 7
        and proof >= 3
        and op_leverage >= 2
        and risk <= 2
    )


def is_demote(row: dict[str, str]) -> bool:
    risk = float_from_row(row, "negative_revision_risk")
    gap = float_from_row(row, "story_vs_numbers_gap_penalty")
    return (risk is not None and risk >= 4) or (gap is not None and gap >= 2)


def return_stats(rows: list[dict[str, str]]) -> dict[str, object]:
    values = [value for value in (float_from_row(row, "return_90d_pct") for row in rows) if value is not None]
    if not values:
        return {"n": len(rows), "avg_return_90d_pct": "", "median_return_90d_pct": "", "win30_rate_pct": "", "loss30_rate_pct": ""}
    return {
        "n": len(rows),
        "avg_return_90d_pct": round(sum(values) / len(values), 4),
        "median_return_90d_pct": round(median(values), 4),
        "win30_rate_pct": round(sum(value >= 30 for value in values) / len(values) * 100, 4),
        "loss30_rate_pct": round(sum(value <= -30 for value in values) / len(values) * 100, 4),
    }


def evaluate_joined_results(selection_rows: list[dict[str, str]], extraction_rows: list[dict[str, str]]) -> dict[str, object]:
    rows = joined_rows(selection_rows, extraction_rows)
    candidate_rows = [row for row in rows if is_candidate(row)]
    high_priority_rows = [row for row in rows if is_high_priority(row)]
    demote_rows = [row for row in rows if is_demote(row)]
    return {
        "completed_count": len(rows),
        "candidate_count": len(candidate_rows),
        "high_priority_count": len(high_priority_rows),
        "demote_count": len(demote_rows),
        "all_rows": rows,
        "candidate_rows": candidate_rows,
        "high_priority_rows": high_priority_rows,
        "demote_rows": demote_rows,
        "summary_rows": [
            {"group": "all_completed", **return_stats(rows)},
            {"group": "candidate", **return_stats(candidate_rows)},
            {"group": "high_priority", **return_stats(high_priority_rows)},
            {"group": "demote", **return_stats(demote_rows)},
        ],
    }


def write_evaluation(selection_csv: Path, extraction_csv: Path, output_prefix: Path) -> None:
    result = evaluate_joined_results(read_csv(selection_csv), read_csv(extraction_csv))
    write_csv(output_path(output_prefix, "_joined.csv"), result["all_rows"])  # type: ignore[arg-type]
    write_csv(output_path(output_prefix, "_candidates.csv"), result["candidate_rows"])  # type: ignore[arg-type]
    write_csv(output_path(output_prefix, "_high_priority.csv"), result["high_priority_rows"])  # type: ignore[arg-type]
    write_csv(output_path(output_prefix, "_demote.csv"), result["demote_rows"])  # type: ignore[arg-type]
    write_csv(output_path(output_prefix, "_summary.csv"), result["summary_rows"])  # type: ignore[arg-type]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build/evaluate spec_convex LLM testset packets")
    parser.add_argument("--quarters", nargs="+", default=["2022Q4", "2023Q2"])
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=DEFAULT_BASE_DIR / "llm_spec_convex_all_2022Q4_2023Q2",
    )
    parser.add_argument("--max-snippets", type=int, default=18)
    parser.add_argument("--selection-csv", type=Path, default=None)
    parser.add_argument("--extractions-csv", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.extractions_csv:
        selection_csv = args.selection_csv or output_path(args.output_prefix, "_selection.csv")
        write_evaluation(selection_csv, args.extractions_csv, args.output_prefix)
        print(f"wrote evaluation outputs with prefix {args.output_prefix}")
        return
    records = build_records(args.quarters, base_dir=args.base_dir, max_snippets=args.max_snippets)
    write_outputs(records, args.output_prefix)
    print(f"wrote {len(records)} spec_convex packets with prefix {args.output_prefix}")


if __name__ == "__main__":
    main()
