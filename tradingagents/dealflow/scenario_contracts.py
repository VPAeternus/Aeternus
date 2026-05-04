from __future__ import annotations

from typing import Any, Dict, List


REQUIRED_EVENT_CARD_FIELDS = [
    "event_card_id",
    "date",
    "title",
    "event_type",
    "summary",
    "source_bundle",
    "source_records",
    "direct_entities",
    "second_order_entities",
    "channels",
    "expected_direction",
    "confidence",
    "urgency",
    "time_horizon",
    "portfolio_relevance",
    "matched_holdings",
    "matched_universe_symbols",
    "coverage_dimensions",
    "missing_dimensions",
    "followup_questions",
]

ALLOWED_COVERAGE_STATUSES = {"COMPLETE", "PARTIAL", "MISSING"}
ALLOWED_WRITEBACK_CANDIDATE_TYPES = {"edge", "event_summary", "entity_alias", "relationship_claim"}
ALLOWED_WRITEBACK_RECOMMENDATIONS = {"safe_later", "needs_review", "temporary_only"}


def validate_event_card(card: Dict[str, Any] | None) -> List[str]:
    payload = dict(card or {})
    return [field for field in REQUIRED_EVENT_CARD_FIELDS if field not in payload]


def validate_coverage_status(status: Any) -> bool:
    return str(status or "").upper().strip() in ALLOWED_COVERAGE_STATUSES


def validate_writeback_candidate(candidate: Dict[str, Any] | None) -> List[str]:
    payload = dict(candidate or {})
    missing = []
    for field in (
        "candidate_id",
        "candidate_type",
        "source_entity",
        "target_entity",
        "relationship",
        "payload",
        "confidence",
        "evidence_event_cards",
        "durability",
        "writeback_recommendation",
    ):
        if field not in payload:
            missing.append(field)
    if payload.get("candidate_type") not in ALLOWED_WRITEBACK_CANDIDATE_TYPES:
        missing.append("candidate_type")
    if payload.get("writeback_recommendation") not in ALLOWED_WRITEBACK_RECOMMENDATIONS:
        missing.append("writeback_recommendation")
    return missing
