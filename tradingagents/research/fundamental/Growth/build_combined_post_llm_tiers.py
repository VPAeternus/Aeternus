from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pandas as pd

from src.features.post_llm_subtiers import (
    POST_LLM_SUBTIER_FLAGS,
    POST_LLM_SUBTIER_LABELS,
    add_post_llm_subtiers,
)

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "Growth" / "earnings_8k_sec_parser"

INPUTS = [
    ("tier1", BASE / "post_llm_tier1_2021Q4_2026Q1_partial_gpt55_medium_scores.csv"),
    ("tier2", BASE / "post_llm_tier2_2021Q4_2026Q1_partial_gpt55_high_scores.csv"),
    ("tier3", BASE / "post_llm_tier3_2021Q4_2026Q1_partial_gpt55_high_scores.csv"),
    ("tier4", BASE / "post_llm_tier4_2021Q4_2026Q1_partial_gpt55_high_scores.csv"),
]
OUTPUT = BASE / "post_llm_tier1_tier2_tier3_tier4_2021Q4_2026Q1_partial_gpt55_mixed_combined.csv"
SUMMARY = BASE / "post_llm_tier1_tier2_tier3_tier4_2021Q4_2026Q1_partial_gpt55_mixed_combined_summary.csv"

TIER_FLAG_COLUMNS = POST_LLM_SUBTIER_FLAGS
SUB_TIER_LABELS = list(POST_LLM_SUBTIER_LABELS.values())

BASE_TIER_LABELS = {
    "tier1": ("tier_1_bucket", "Tier 1 - Balanced priority feed"),
    "tier2": ("tier_2_bucket", "Tier 2 - High-priority compact feed"),
    "tier3": ("tier_3_bucket", "Tier 3 - Revised dislocation feed"),
    "tier4": ("tier_4_bucket", "Tier 4 - Ultra-distressed tag, not a production tier"),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def merge_labels(existing: str, incoming: str) -> str:
    labels: list[str] = []
    for value in [existing, incoming]:
        for label in str(value or "").split(";"):
            label = label.strip()
            if label and label not in labels:
                labels.append(label)
    return ";".join(labels)


def tier_source_column(source: str) -> str:
    return f"in_{source}_post_llm_file"


def is_one(value: Any) -> bool:
    return str(value).strip() == "1"


def main() -> None:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    source_counts: dict[str, int] = {}

    for source, path in INPUTS:
        rows = read_csv(path)
        source_counts[source] = len(rows)
        for row in rows:
            key = (row.get("quarter", ""), row.get("ticker", ""))
            if key not in by_key:
                by_key[key] = dict(row)
                by_key[key]["post_llm_sub_tier_bucket"] = ""
                for flag in TIER_FLAG_COLUMNS:
                    by_key[key].setdefault(flag, "0")
                for source_name, _ in INPUTS:
                    by_key[key][tier_source_column(source_name)] = "0"

            merged = by_key[key]
            merged[tier_source_column(source)] = "1"
            base_tier_column, base_tier_label = BASE_TIER_LABELS[source]
            merged[base_tier_column] = base_tier_label

            # Keep the broadest available LLM pass as the base value, then layer
            # narrower sub-tier flags on top.
            if source == "tier1":
                for field, value in row.items():
                    if value != "":
                        merged[field] = value
            else:
                for field, value in row.items():
                    if field in TIER_FLAG_COLUMNS and value == "1":
                        merged[field] = "1"
                    elif field.startswith("tier_") and value and not merged.get(field):
                        merged[field] = value
                    elif field not in merged:
                        merged[field] = value

            merged["post_llm_sub_tier_bucket"] = merge_labels(
                merged.get("post_llm_sub_tier_bucket", ""),
                row.get("post_llm_sub_tier_bucket", ""),
            )

    rows = sorted(by_key.values(), key=lambda row: (row.get("quarter", ""), row.get("ticker", "")))
    if rows:
        rows = add_post_llm_subtiers(pd.DataFrame(rows)).to_dict("records")

    preferred = [
        "quarter",
        "ticker",
        "revenue_bucket",
        "pre_llm_fundamental_score",
        "pre_llm_fundamental_bucket",
        "post_llm_fundamental_score",
        "post_llm_fundamental_bucket",
        "post_llm_score_delta",
        "causal_change",
        "narrative_delta_bucket",
        "negative_revision_risk",
        "story_vs_numbers_gap_penalty",
        "post_llm_candidate_flag",
        "post_llm_high_priority_flag",
        "post_llm_demote_flag",
        "tier_bucket",
        "tier_1_bucket",
        "tier_2_bucket",
        "tier_3_bucket",
        "tier_4_bucket",
        *TIER_FLAG_COLUMNS,
        "post_llm_sub_tier_bucket",
        "in_tier1_post_llm_file",
        "in_tier2_post_llm_file",
        "in_tier3_post_llm_file",
        "in_tier4_post_llm_file",
    ]
    remaining = [key for key in dict.fromkeys(k for row in rows for k in row) if key not in preferred]
    write_csv(OUTPUT, rows, preferred + remaining)

    summary_rows = [
        {"metric": "source_rows", "bucket": source, "value": count}
        for source, count in source_counts.items()
    ]
    summary_rows.append({"metric": "combined_unique_rows", "bucket": "", "value": len(rows)})
    for source, _ in INPUTS:
        column = tier_source_column(source)
        summary_rows.append({"metric": "combined_source_membership", "bucket": source, "value": sum(is_one(row.get(column)) for row in rows)})
    for flag, label in zip(TIER_FLAG_COLUMNS, SUB_TIER_LABELS, strict=True):
        summary_rows.append({"metric": "combined_sub_tier_count", "bucket": label, "value": sum(is_one(row.get(flag)) for row in rows)})
    write_csv(SUMMARY, summary_rows, ["metric", "bucket", "value"])

    print(f"wrote {OUTPUT} rows={len(rows)}")
    print(f"wrote {SUMMARY}")


if __name__ == "__main__":
    main()
