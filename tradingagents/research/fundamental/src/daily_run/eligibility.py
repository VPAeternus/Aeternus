from __future__ import annotations

from collections import Counter
from typing import Any

from tradingagents.research.fundamental.src.features.llm_packets import build_llm_packets
from tradingagents.research.fundamental.src.features.tiers import assign_tiers


def _key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("ticker", "")).upper(), str(row.get("quarter", ""))


def _has_tier_1_to_4(row: dict[str, Any]) -> bool:
    return any(str(row.get(col, "")).strip() for col in ["tier_1_bucket", "tier_2_bucket", "tier_3_bucket", "tier_4_bucket"])


def assign_daily_tiers(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for row in rows:
        tiers = assign_tiers(row)
        merged = {**row, **tiers}
        for col in ["tier_0_bucket", "tier_1_bucket", "tier_2_bucket", "tier_3_bucket", "tier_4_bucket"]:
            if str(merged.get(col, "")).strip():
                counts[f"{col.replace('_bucket', '')}_count"] += 1
        output.append(merged)
    return output, dict(counts)


def build_llm_eligibility(
    tiered_rows: list[dict[str, Any]],
    coverage_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    coverage = {_key(row): row for row in coverage_rows}
    eligible: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    for row in tiered_rows:
        cov = coverage.get(_key(row), {})
        if not _has_tier_1_to_4(row):
            quarantine.append({**row, "llm_quarantine_reason": "tier0_or_not_tier_1_to_4"})
            continue
        if str(cov.get("coverage_status", "")).upper() != "CACHED_READY":
            quarantine.append({**row, **cov, "llm_quarantine_reason": "llm_evidence_missing"})
            continue
        if not str(cov.get("earnings_8k_accession", "")).strip() or not str(cov.get("earnings_8k_primary_document", "")).strip():
            quarantine.append({**row, **cov, "llm_quarantine_reason": "missing_earnings_8k_or_press_release"})
            continue
        eligible.append({**row, **cov, "llm_eligible": 1})
    summary = {
        "tiered_count": len(tiered_rows),
        "llm_eligible_count": len(eligible),
        "llm_quarantine_count": len(quarantine),
    }
    return eligible, quarantine, summary


def build_tier_filtered_llm_packets(
    eligible_rows: list[dict[str, Any]],
    raw_documents: list[dict[str, Any]],
    *,
    broad_universe_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    packets = build_llm_packets(eligible_rows, raw_documents)
    packet_by_sample = {str(packet.get("sample_id", "")): packet for packet in packets}
    good_packets: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    for row in eligible_rows:
        sample_id = f"{str(row.get('ticker', '')).upper()}_{row.get('quarter', '')}"
        packet = packet_by_sample.get(sample_id)
        if not packet or not packet.get("evidence_snippets"):
            quarantine.append({**row, "llm_quarantine_reason": "empty_evidence_docs"})
            continue
        good_packets.append(packet)
    if good_packets and len(good_packets) >= broad_universe_count:
        raise ValueError("LLM packet count equals/exceeds broad universe count; refusing likely full-universe LLM run")
    summary = {
        "packet_count": len(good_packets),
        "eligible_count": len(eligible_rows),
        "empty_evidence_count": len(quarantine),
        "broad_universe_count": broad_universe_count,
    }
    return good_packets, quarantine, summary
