from __future__ import annotations

from tradingagents.dealflow.investigation_response import build_investigation_response


def test_build_investigation_response_complete():
    payload = build_investigation_response(
        investigation_result={
            "query_type": "reverse_forensic",
            "target_entities": ["MU"],
            "first_miss_stage": None,
            "stage_diagnosis": [
                {"stage": "scouts", "status": "FOUND"},
                {"stage": "event_cards", "status": "FOUND"},
                {"stage": "universe_filter", "status": "FOUND"},
                {"stage": "collect", "status": "FOUND"},
                {"stage": "scout_handoff", "status": "FOUND"},
                {"stage": "fundamental_intake", "status": "FOUND"},
            ],
            "matched_event_cards": ["evt_mu_1"],
            "evidence_found": ["scouts", "event_cards", "scout_handoff"],
            "evidence_missing": [],
        }
    )

    assert payload["coverage_status"] == "COMPLETE"
    assert payload["manual_gap_fill_requests"] == []
    assert payload["confidence"] >= 0.8


def test_build_investigation_response_partial_with_missing_inputs():
    payload = build_investigation_response(
        investigation_result={
            "query_type": "reverse_forensic",
            "target_entities": ["MU"],
            "first_miss_stage": "scout_handoff",
            "stage_diagnosis": [
                {"stage": "scouts", "status": "FOUND"},
                {"stage": "event_cards", "status": "FOUND"},
                {"stage": "universe_filter", "status": "FOUND"},
                {"stage": "collect", "status": "FOUND"},
                {"stage": "scout_handoff", "status": "MISS"},
                {"stage": "fundamental_intake", "status": "MISS"},
            ],
            "matched_event_cards": ["evt_mu_1"],
            "evidence_found": ["scouts", "event_cards", "collect"],
            "evidence_missing": ["scout_handoff", "fundamental_intake"],
        }
    )

    assert payload["coverage_status"] == "PARTIAL"
    assert payload["manual_gap_fill_requests"]
    assert "scout_handoff" in " ".join(payload["evidence_missing"]).lower()


def test_build_investigation_response_missing():
    payload = build_investigation_response(
        investigation_result={
            "query_type": "reverse_forensic",
            "target_entities": ["MU"],
            "first_miss_stage": "scouts",
            "stage_diagnosis": [
                {"stage": "scouts", "status": "MISS"},
                {"stage": "event_cards", "status": "MISS"},
                {"stage": "universe_filter", "status": "MISS"},
                {"stage": "collect", "status": "MISS"},
                {"stage": "scout_handoff", "status": "MISS"},
                {"stage": "fundamental_intake", "status": "MISS"},
            ],
            "matched_event_cards": [],
            "evidence_found": [],
            "evidence_missing": ["scouts", "event_cards", "universe_filter", "collect", "scout_handoff", "fundamental_intake"],
        }
    )

    assert payload["coverage_status"] == "MISSING"
    assert payload["manual_gap_fill_requests"]
    assert payload["confidence"] <= 0.4


def test_build_investigation_response_payload_shape():
    payload = build_investigation_response(
        investigation_result={
            "query_type": "forward_scenario",
            "target_entities": ["XLE"],
            "first_miss_stage": "collect",
            "stage_diagnosis": [
                {"stage": "scouts", "status": "FOUND"},
                {"stage": "event_cards", "status": "FOUND"},
                {"stage": "universe_filter", "status": "FOUND"},
                {"stage": "collect", "status": "MISS"},
                {"stage": "scout_handoff", "status": "MISS"},
                {"stage": "fundamental_intake", "status": "MISS"},
            ],
            "matched_event_cards": ["evt_iran"],
            "evidence_found": ["scouts", "event_cards", "universe_filter"],
            "evidence_missing": ["collect", "scout_handoff", "fundamental_intake"],
        }
    )

    for key in (
        "summary",
        "coverage_status",
        "query_type",
        "matched_entities",
        "stage_diagnosis",
        "evidence_found",
        "evidence_missing",
        "recommended_changes",
        "manual_gap_fill_requests",
        "confidence",
    ):
        assert key in payload
