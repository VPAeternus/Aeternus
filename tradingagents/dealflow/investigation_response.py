from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _manual_gap_fill_requests(missing_stages: Iterable[str]) -> List[str]:
    requests: List[str] = []
    missing = {str(stage or "").strip().lower() for stage in missing_stages}
    if "scouts" in missing or "event_cards" in missing:
        requests.append("manual_event_specific_x_feed_pass")
    if "universe_filter" in missing or "collect" in missing:
        requests.append("manual_universe_context_confirm")
    if "shortlist" in missing or "deep_selection" in missing:
        requests.append("manual_selection_threshold_review")
    if not requests and missing:
        requests.append("manual_context_upload")
    return requests


def _recommended_changes(first_miss_stage: str | None, query_type: str) -> List[str]:
    stage = str(first_miss_stage or "").strip().lower()
    if stage == "scouts":
        return ["Expand discovery triggers for target entities and relevant catalysts."]
    if stage == "event_cards":
        return ["Improve cross-scout consolidation so qualifying signals form daily Event Cards."]
    if stage == "universe_filter":
        return ["Revisit universe filter inclusion thresholds and source overlap gates."]
    if stage == "collect":
        return ["Review collector coverage and scoring thresholds for sparse-but-moving names."]
    if stage == "shortlist":
        return ["Tune shortlist cut logic to reduce false negatives on high-momentum candidates."]
    if stage == "deep_selection":
        return ["Adjust deep-selection criteria to preserve high-conviction opportunities."]
    if str(query_type).strip().lower() == "forward_scenario":
        return ["Add focused scenario evidence before acting on forward-impact conclusions."]
    return []


def _coverage_status(first_miss_stage: str | None, stage_diagnosis: List[Dict[str, Any]]) -> str:
    if not stage_diagnosis:
        return "MISSING"
    if first_miss_stage is None:
        return "COMPLETE"
    if str(first_miss_stage).strip().lower() == "scouts":
        found_count = sum(1 for row in stage_diagnosis if str(row.get("status", "")).upper() == "FOUND")
        return "PARTIAL" if found_count > 0 else "MISSING"
    return "PARTIAL"


def _confidence_for(status: str) -> float:
    if status == "COMPLETE":
        return 0.85
    if status == "PARTIAL":
        return 0.65
    return 0.35


def _summary(status: str, first_miss_stage: str | None, targets: List[str]) -> str:
    target_text = ", ".join(targets) if targets else "target entities"
    if status == "COMPLETE":
        return f"Investigation is complete for {target_text}; no miss point was detected across monitored stages."
    if status == "PARTIAL":
        return f"Investigation is partial for {target_text}; first likely miss point is {first_miss_stage}."
    return f"Investigation is missing critical evidence for {target_text}; first miss point is {first_miss_stage}."


def build_investigation_response(*, investigation_result: Dict[str, Any]) -> Dict[str, Any]:
    query_type = str(investigation_result.get("query_type", "")).strip()
    stage_diagnosis = list(investigation_result.get("stage_diagnosis", []) or [])
    first_miss_stage = investigation_result.get("first_miss_stage")
    matched_entities = list(investigation_result.get("target_entities", []) or [])
    evidence_found = list(investigation_result.get("evidence_found", []) or [])
    evidence_missing = list(investigation_result.get("evidence_missing", []) or [])

    coverage_status = _coverage_status(str(first_miss_stage or "") or None, stage_diagnosis)
    manual_gap_fill = _manual_gap_fill_requests(evidence_missing if coverage_status != "COMPLETE" else [])
    confidence = _confidence_for(coverage_status)

    return {
        "summary": _summary(coverage_status, str(first_miss_stage or "") or None, matched_entities),
        "coverage_status": coverage_status,
        "query_type": query_type,
        "matched_entities": matched_entities,
        "stage_diagnosis": stage_diagnosis,
        "evidence_found": evidence_found,
        "evidence_missing": evidence_missing,
        "recommended_changes": _recommended_changes(str(first_miss_stage or "") or None, query_type),
        "manual_gap_fill_requests": manual_gap_fill,
        "confidence": confidence,
    }

