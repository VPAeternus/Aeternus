from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Iterable

from build_pre_llm_fundamental_score import bucket as pre_llm_bucket
from spec_convex_llm_testset import (
    EXTRACTION_FIELDS,
    PACKET_FIELDS,
    SELECTION_FIELDS,
    best_text_doc,
    clean,
    extract_evidence_snippets,
    first_semicolon_value,
    is_candidate,
    is_demote,
    is_high_priority,
    output_path,
    read_csv,
    write_csv,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_DIR = ROOT / "Growth" / "earnings_8k_sec_parser"
DEFAULT_INPUT = DEFAULT_BASE_DIR / "pre_llm_fundamental_score_2021Q4_2026Q1_partial.csv"
DEFAULT_OUTPUT_PREFIX = DEFAULT_BASE_DIR / "llm_tier3_2021Q4_2026Q1_partial"
TIER_FIELDS = ["tier_bucket", "tier_1_bucket", "tier_2_bucket", "tier_3_bucket", "tier_4_bucket"]


def packet_from_record(record: dict[str, object]) -> dict[str, object]:
    return {field: record.get(field, "") for field in PACKET_FIELDS}


def quarter_rows(rows: Iterable[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    output: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        output.setdefault(clean(row.get("quarter")), []).append(row)
    return output


def prior_quarter(quarter: str) -> str:
    try:
        year = int(quarter[:4])
        q = int(quarter[-1])
    except (TypeError, ValueError):
        return ""
    if q == 1:
        return f"{year - 1}Q4"
    return f"{year}Q{q - 1}"


def build_records(
    input_csv: Path,
    *,
    base_dir: Path,
    max_snippets: int,
    tier_column: str,
    sample_prefix: str,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    tier_rows = [row for row in read_csv(input_csv) if clean(row.get(tier_column))]

    for quarter, rows in sorted(quarter_rows(tier_rows).items()):
        audit_path = base_dir / f"sec_quarter_cache_audit_{quarter}_prod.csv"
        fetch_path = base_dir / f"sec_quarter_cache_fetch_report_{quarter}_prod.csv"
        audit_by_ticker = {clean(row.get("ticker")).upper(): row for row in read_csv(audit_path)}
        fetch_rows = read_csv(fetch_path)

        for row in rows:
            ticker = clean(row.get("ticker")).upper()
            audit = audit_by_ticker.get(ticker, {})
            accession = first_semicolon_value(audit.get("item_202_accessions"))
            event_date = first_semicolon_value(audit.get("item_202_event_dates"))
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
                }
            )

    records.sort(key=lambda item: (clean(item.get("quarter")), clean(item.get("ticker"))))
    for idx, row in enumerate(records, start=1):
        row["sample_id"] = f"{sample_prefix}{idx:06d}"
    return records


def write_packet_outputs(records: list[dict[str, object]], output_prefix: Path, *, tier_label: str) -> None:
    selection_fields = list(dict.fromkeys([*SELECTION_FIELDS, *TIER_FIELDS]))
    write_csv(output_path(output_prefix, "_selection.csv"), records, selection_fields)

    packets = [packet_from_record(record) for record in records]
    jsonl_path = output_path(output_prefix, "_packets.jsonl")
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for packet in packets:
            handle.write(json.dumps(packet, ensure_ascii=True) + "\n")

    md_lines = [f"# {tier_label} LLM Packets", ""]
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

    quality_rows = [
        {"metric": "records", "value": len(records)},
        {
            "metric": "missing_accession",
            "value": sum(1 for record in records if "missing_accession" in clean(record.get("quality_flags"))),
        },
        {
            "metric": "missing_text_path",
            "value": sum(1 for record in records if "missing_text_path" in clean(record.get("quality_flags"))),
        },
        {
            "metric": "text_path_not_found",
            "value": sum(1 for record in records if "text_path_not_found" in clean(record.get("quality_flags"))),
        },
        {
            "metric": "missing_evidence_snippets",
            "value": sum(1 for record in records if "missing_evidence_snippets" in clean(record.get("quality_flags"))),
        },
    ]
    write_csv(output_path(output_prefix, "_quality_report.csv"), quality_rows, ["metric", "value"])


def joined_rows(selection_rows: list[dict[str, str]], extraction_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    selection_by_id = {row["sample_id"]: row for row in selection_rows}
    output: list[dict[str, str]] = []
    for extraction in extraction_rows:
        sample_id = extraction.get("sample_id", "")
        selection = selection_by_id.get(sample_id)
        if selection:
            output.append({**selection, **extraction})
    return output


def write_evaluation(selection_csv: Path, extraction_csv: Path, output_prefix: Path) -> None:
    rows = joined_rows(read_csv(selection_csv), read_csv(extraction_csv))
    write_csv(output_path(output_prefix, "_joined.csv"), rows)

    bucket_counts: dict[str, int] = {}
    for row in rows:
        bucket = clean(row.get("narrative_delta_bucket")) or "missing"
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    candidate_rows = [row for row in rows if is_candidate(row)]
    high_priority_rows = [row for row in rows if is_high_priority(row)]
    demote_rows = [row for row in rows if is_demote(row)]
    summary_rows = [
        {"metric": "completed_rows", "bucket": "", "value": len(rows)},
        {"metric": "candidate_count", "bucket": "", "value": len(candidate_rows)},
        {"metric": "high_priority_count", "bucket": "", "value": len(high_priority_rows)},
        {"metric": "demote_count", "bucket": "", "value": len(demote_rows)},
    ]
    summary_rows.extend(
        {"metric": "narrative_delta_bucket", "bucket": bucket, "value": count}
        for bucket, count in sorted(bucket_counts.items())
    )
    write_csv(output_path(output_prefix, "_summary.csv"), summary_rows, ["metric", "bucket", "value"])


def write_post_llm_scores(joined_csv: Path, scores_csv: Path, summary_csv: Path) -> None:
    rows = read_csv(joined_csv)
    output: list[dict[str, object]] = []
    is_tier1_output = any("tier1" in path.name.lower() or "tier_1" in path.name.lower() for path in [joined_csv, scores_csv])
    is_tier2_output = any("tier2" in path.name.lower() or "tier_2" in path.name.lower() for path in [joined_csv, scores_csv])
    is_tier3_output = any("tier3" in path.name.lower() or "tier_3" in path.name.lower() for path in [joined_csv, scores_csv])
    is_tier4_output = any("tier4" in path.name.lower() or "tier_4" in path.name.lower() for path in [joined_csv, scores_csv])
    is_scoped_tier_output = is_tier1_output or is_tier2_output or is_tier3_output or is_tier4_output
    addition_by_ticker_quarter = {
        (clean(row.get("ticker")).upper(), clean(row.get("quarter"))): int(float(row.get("score_addition") or 0))
        for row in rows
    }
    for row in rows:
        base_score = int(float(row.get("pre_llm_fundamental_score") or 0))
        addition = int(float(row.get("score_addition") or 0))
        post_score = base_score + addition
        risk = int(float(row.get("negative_revision_risk") or 0))
        gap = int(float(row.get("story_vs_numbers_gap_penalty") or 0))
        causal_change = int(float(row.get("causal_change") or 0))
        narrative_delta_bucket = clean(row.get("narrative_delta_bucket"))
        candidate_flag = int(is_candidate(row))
        high_priority_flag = int(is_high_priority(row))
        tier_1_base = (bool(row.get("tier_1_bucket")) and not is_scoped_tier_output) or is_tier1_output
        tier_1_1 = tier_1_base and candidate_flag == 1
        tier_1_2 = tier_1_base and causal_change == 3
        tier_1_3 = tier_1_base and candidate_flag == 1 and causal_change == 3 and risk <= 2
        tier_1_4 = tier_1_base and high_priority_flag == 1
        tier_2_base = (bool(row.get("tier_2_bucket")) and not is_scoped_tier_output) or is_tier2_output
        tier_2_1 = tier_2_base and candidate_flag == 1
        tier_2_2 = tier_2_base and causal_change == 3
        tier_2_3 = tier_2_base and candidate_flag == 1 and causal_change == 3 and risk <= 2
        tier_3_base = (bool(row.get("tier_3_bucket")) and not is_scoped_tier_output) or is_tier3_output
        tier_3_1 = tier_3_base and candidate_flag == 1
        tier_3_2 = tier_3_base and (high_priority_flag == 1 or narrative_delta_bucket == "inflecting")
        prior_addition = addition_by_ticker_quarter.get(
            (clean(row.get("ticker")).upper(), prior_quarter(clean(row.get("quarter"))))
        )
        tier_3_3 = tier_3_base and addition > 0 and prior_addition is not None and prior_addition > 0
        tier_3_4 = tier_3_base and high_priority_flag == 1 and prior_addition is not None and prior_addition > 0
        tier_4_base = (bool(row.get("tier_4_bucket")) and not is_scoped_tier_output) or is_tier4_output
        tier_4_1 = tier_4_base and candidate_flag == 1
        tier_4_2 = tier_4_base and causal_change == 3
        tier_4_3 = tier_4_base and high_priority_flag == 1
        sub_tiers = []
        if tier_1_1:
            sub_tiers.append("Tier 1.1 - LLM-supported candidate")
        if tier_1_2:
            sub_tiers.append("Tier 1.2 - Causal re-rating candidate")
        if tier_1_3:
            sub_tiers.append("Tier 1.3 - Best balanced production subset")
        if tier_1_4:
            sub_tiers.append("Tier 1.4 - Clean high-priority subset")
        if tier_2_1:
            sub_tiers.append("Tier 2.1 - LLM-supported")
        if tier_2_2:
            sub_tiers.append("Tier 2.2 - Causal re-rating")
        if tier_2_3:
            sub_tiers.append("Tier 2.3 - Best balanced LLM subset")
        if tier_3_1:
            sub_tiers.append("Tier 3.1 - Cleaner LLM-positive Tier 3")
        if tier_3_2:
            sub_tiers.append("Tier 3.2 - LLM inflection / high priority")
        if tier_3_3:
            sub_tiers.append("Tier 3.3 - Persistent re-rating setup")
        if tier_3_4:
            sub_tiers.append("Tier 3.4 - Persistent high-priority re-rating")
        if tier_4_1:
            sub_tiers.append("Tier 4.1 - LLM-supported aggressive")
        if tier_4_2:
            sub_tiers.append("Tier 4.2 - Causal re-rating candidate")
        if tier_4_3:
            sub_tiers.append("Tier 4.3 - Clean high-priority")
        output.append(
            {
                **row,
                "post_llm_fundamental_score": post_score,
                "post_llm_fundamental_bucket": pre_llm_bucket(post_score),
                "post_llm_score_delta": addition,
                "post_llm_candidate_flag": candidate_flag,
                "post_llm_high_priority_flag": high_priority_flag,
                "post_llm_demote_flag": int(risk >= 4 or gap >= 2 or is_demote(row)),
                "post_llm_tier_1_1_flag": int(tier_1_1),
                "post_llm_tier_1_2_flag": int(tier_1_2),
                "post_llm_tier_1_3_flag": int(tier_1_3),
                "post_llm_tier_1_4_flag": int(tier_1_4),
                "post_llm_tier_2_1_flag": int(tier_2_1),
                "post_llm_tier_2_2_flag": int(tier_2_2),
                "post_llm_tier_2_3_flag": int(tier_2_3),
                "post_llm_tier_3_1_flag": int(tier_3_1),
                "post_llm_tier_3_2_flag": int(tier_3_2),
                "post_llm_tier_3_3_flag": int(tier_3_3),
                "post_llm_tier_3_4_flag": int(tier_3_4),
                "post_llm_tier_4_1_flag": int(tier_4_1),
                "post_llm_tier_4_2_flag": int(tier_4_2),
                "post_llm_tier_4_3_flag": int(tier_4_3),
                "post_llm_sub_tier_bucket": ";".join(sub_tiers),
            }
        )
    write_csv(scores_csv, output)

    bucket_counts: dict[str, int] = {}
    for row in output:
        bucket = clean(row.get("post_llm_fundamental_bucket")) or "missing"
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
    summary_rows = [
        {"metric": "post_llm_rows", "bucket": "", "value": len(output)},
        {"metric": "post_llm_candidate_count", "bucket": "", "value": sum(int(row["post_llm_candidate_flag"]) for row in output)},
        {
            "metric": "post_llm_high_priority_count",
            "bucket": "",
            "value": sum(int(row["post_llm_high_priority_flag"]) for row in output),
        },
        {"metric": "post_llm_demote_count", "bucket": "", "value": sum(int(row["post_llm_demote_flag"]) for row in output)},
        {
            "metric": "post_llm_sub_tier_count",
            "bucket": "Tier 1.1 - LLM-supported candidate",
            "value": sum(int(row["post_llm_tier_1_1_flag"]) for row in output),
        },
        {
            "metric": "post_llm_sub_tier_count",
            "bucket": "Tier 1.2 - Causal re-rating candidate",
            "value": sum(int(row["post_llm_tier_1_2_flag"]) for row in output),
        },
        {
            "metric": "post_llm_sub_tier_count",
            "bucket": "Tier 1.3 - Best balanced production subset",
            "value": sum(int(row["post_llm_tier_1_3_flag"]) for row in output),
        },
        {
            "metric": "post_llm_sub_tier_count",
            "bucket": "Tier 1.4 - Clean high-priority subset",
            "value": sum(int(row["post_llm_tier_1_4_flag"]) for row in output),
        },
        {
            "metric": "post_llm_sub_tier_count",
            "bucket": "Tier 2.1 - LLM-supported",
            "value": sum(int(row["post_llm_tier_2_1_flag"]) for row in output),
        },
        {
            "metric": "post_llm_sub_tier_count",
            "bucket": "Tier 2.2 - Causal re-rating",
            "value": sum(int(row["post_llm_tier_2_2_flag"]) for row in output),
        },
        {
            "metric": "post_llm_sub_tier_count",
            "bucket": "Tier 2.3 - Best balanced LLM subset",
            "value": sum(int(row["post_llm_tier_2_3_flag"]) for row in output),
        },
        {
            "metric": "post_llm_sub_tier_count",
            "bucket": "Tier 3.1 - Cleaner LLM-positive Tier 3",
            "value": sum(int(row["post_llm_tier_3_1_flag"]) for row in output),
        },
        {
            "metric": "post_llm_sub_tier_count",
            "bucket": "Tier 3.2 - LLM inflection / high priority",
            "value": sum(int(row["post_llm_tier_3_2_flag"]) for row in output),
        },
        {
            "metric": "post_llm_sub_tier_count",
            "bucket": "Tier 3.3 - Persistent re-rating setup",
            "value": sum(int(row["post_llm_tier_3_3_flag"]) for row in output),
        },
        {
            "metric": "post_llm_sub_tier_count",
            "bucket": "Tier 3.4 - Persistent high-priority re-rating",
            "value": sum(int(row["post_llm_tier_3_4_flag"]) for row in output),
        },
        {
            "metric": "post_llm_sub_tier_count",
            "bucket": "Tier 4.1 - LLM-supported aggressive",
            "value": sum(int(row["post_llm_tier_4_1_flag"]) for row in output),
        },
        {
            "metric": "post_llm_sub_tier_count",
            "bucket": "Tier 4.2 - Causal re-rating candidate",
            "value": sum(int(row["post_llm_tier_4_2_flag"]) for row in output),
        },
        {
            "metric": "post_llm_sub_tier_count",
            "bucket": "Tier 4.3 - Clean high-priority",
            "value": sum(int(row["post_llm_tier_4_3_flag"]) for row in output),
        },
    ]
    summary_rows.extend(
        {"metric": "post_llm_fundamental_bucket", "bucket": bucket, "value": count}
        for bucket, count in sorted(bucket_counts.items())
    )
    write_csv(summary_csv, summary_rows, ["metric", "bucket", "value"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build/evaluate tier LLM packets")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--output-prefix", type=Path, default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--tier-column", default="tier_3_bucket")
    parser.add_argument("--sample-prefix", default="T3")
    parser.add_argument("--tier-label", default="Tier 3")
    parser.add_argument("--max-snippets", type=int, default=18)
    parser.add_argument("--selection-csv", type=Path, default=None)
    parser.add_argument("--extractions-csv", type=Path, default=None)
    parser.add_argument("--post-scores-csv", type=Path, default=None)
    parser.add_argument("--post-summary-csv", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.extractions_csv:
        selection_csv = args.selection_csv or output_path(args.output_prefix, "_selection.csv")
        write_evaluation(selection_csv, args.extractions_csv, args.output_prefix)
        if args.post_scores_csv and args.post_summary_csv:
            write_post_llm_scores(output_path(args.output_prefix, "_joined.csv"), args.post_scores_csv, args.post_summary_csv)
        print(f"wrote evaluation outputs with prefix {args.output_prefix}")
        return

    records = build_records(
        args.input_csv,
        base_dir=args.base_dir,
        max_snippets=args.max_snippets,
        tier_column=args.tier_column,
        sample_prefix=args.sample_prefix,
    )
    write_packet_outputs(records, args.output_prefix, tier_label=args.tier_label)
    print(f"wrote {len(records)} {args.tier_label.lower()} packets with prefix {args.output_prefix}")


if __name__ == "__main__":
    main()
