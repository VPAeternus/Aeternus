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
PRE_LLM = BASE / "pre_llm_fundamental_score_2021Q4_2026Q1_partial.csv"
POST_LLM = BASE / "post_llm_tier1_tier2_tier3_tier4_2021Q4_2026Q1_partial_gpt55_mixed_combined.csv"
OUTPUT = BASE / "combined_tier0_tier1_tier2_tier3_tier4_2021Q4_2026Q1_partial_gpt55_mixed.csv"
SUMMARY = BASE / "combined_tier0_tier1_tier2_tier3_tier4_2021Q4_2026Q1_partial_gpt55_mixed_summary.csv"

BASE_TIER_COLUMNS = ["tier_bucket", "tier_1_bucket", "tier_2_bucket", "tier_3_bucket", "tier_4_bucket"]
POST_SUB_TIER_FLAGS = POST_LLM_SUBTIER_FLAGS


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def is_one(value: Any) -> bool:
    return str(value).strip() == "1"


def main() -> None:
    pre_rows = read_csv(PRE_LLM)
    post_by_key = {
        (row.get("quarter", ""), row.get("ticker", "")): row
        for row in read_csv(POST_LLM)
    }

    rows: list[dict[str, Any]] = []
    for pre in pre_rows:
        key = (pre.get("quarter", ""), pre.get("ticker", ""))
        post = post_by_key.get(key, {})
        merged = dict(pre)
        for field, value in post.items():
            if field in BASE_TIER_COLUMNS:
                continue
            merged[field] = value
        for flag in POST_SUB_TIER_FLAGS:
            merged.setdefault(flag, "0")
        merged.setdefault("post_llm_sub_tier_bucket", "")
        merged.setdefault("in_tier1_post_llm_file", "0")
        merged.setdefault("in_tier2_post_llm_file", "0")
        merged.setdefault("in_tier3_post_llm_file", "0")
        merged.setdefault("in_tier4_post_llm_file", "0")
        merged["has_post_llm"] = "1" if post else "0"
        rows.append(merged)

    if rows:
        rows = add_post_llm_subtiers(pd.DataFrame(rows)).to_dict("records")

    fieldnames = [
        "quarter",
        "ticker",
        "revenue_bucket",
        "event_date",
        "profitability_score",
        "operating_cash_flow_score",
        "fcf_proxy_score",
        "financing_dependence_score",
        "asset_efficiency_score",
        "pre_llm_fundamental_score",
        "pre_llm_fundamental_bucket",
        "pre_llm_fundamental_missing_fields",
        *BASE_TIER_COLUMNS,
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
        *POST_SUB_TIER_FLAGS,
        "post_llm_sub_tier_bucket",
        "has_post_llm",
        "in_tier1_post_llm_file",
        "in_tier2_post_llm_file",
        "in_tier3_post_llm_file",
        "in_tier4_post_llm_file",
        "snippet_count",
        "quality_flags",
        "proof_alignment",
        "durability",
        "operating_leverage_quality",
        "narrative_delta_score",
        "score_addition",
        "detected_driver_category",
        "detected_driver_name",
        "evidence_positive",
        "evidence_risk",
        "confidence",
        "blocking_issues",
        "tradable_date",
        "entry_open",
        "return_10d_pct",
        "return_20d_pct",
        "return_30d_pct",
        "return_60d_pct",
        "return_90d_pct",
    ]
    write_csv(OUTPUT, rows, fieldnames)

    summary_rows = [
        {"metric": "combined_rows", "bucket": "", "value": len(rows)},
        {"metric": "base_rows", "bucket": "All pre-LLM rows", "value": len(rows)},
        {"metric": "base_tier_count", "bucket": "No Tier", "value": sum(not row.get("tier_bucket") for row in rows)},
        {"metric": "base_tier_count", "bucket": "Tier 0", "value": sum(bool(row.get("tier_bucket")) for row in rows)},
        {"metric": "base_tier_count", "bucket": "Tier 1", "value": sum(bool(row.get("tier_1_bucket")) for row in rows)},
        {"metric": "base_tier_count", "bucket": "Tier 2", "value": sum(bool(row.get("tier_2_bucket")) for row in rows)},
        {"metric": "base_tier_count", "bucket": "Tier 3", "value": sum(bool(row.get("tier_3_bucket")) for row in rows)},
        {"metric": "base_tier_count", "bucket": "Tier 4", "value": sum(bool(row.get("tier_4_bucket")) for row in rows)},
        {"metric": "post_llm_coverage", "bucket": "has_post_llm", "value": sum(is_one(row.get("has_post_llm")) for row in rows)},
        {"metric": "post_llm_coverage", "bucket": "in_tier1_post_llm_file", "value": sum(is_one(row.get("in_tier1_post_llm_file")) for row in rows)},
    ]
    for flag, label in POST_LLM_SUBTIER_LABELS.items():
        summary_rows.append({"metric": "post_llm_sub_tier_count", "bucket": label, "value": sum(is_one(row.get(flag)) for row in rows)})
    write_csv(SUMMARY, summary_rows, ["metric", "bucket", "value"])

    print(f"wrote {OUTPUT} rows={len(rows)}")
    print(f"wrote {SUMMARY}")


if __name__ == "__main__":
    main()
