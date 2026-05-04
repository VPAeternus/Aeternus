# Question Compiler Chat Backend Frontend Contract

**Date:** 2026-03-17

## Purpose

Define the request/response shape for the first chat-style Aeternus investigation UI.

This contract is intentionally backend-first and manual-only. It is designed to support a simple page where the user asks a question and the backend returns a structured investigation result.

## Request

### JSON request

```json
{
  "date": "2026-03-11",
  "question": "MU went up 10% today, why did we miss it?"
}
```

### Rules

- `date` is optional; default to today in the operator timezone
- `question` is required
- no automatic external retrieval is allowed in `v1`

## Backend phases for progress UI

The frontend can render these phases in order:

1. `compile_question`
2. `load_internal_artifacts`
3. `run_stage_diagnosis`
4. `detect_gaps`
5. `build_response`

`v1` does not require token streaming. Simple phase/status updates are enough.

## Response

### JSON response

```json
{
  "summary": "Investigation is partial for MU; first likely miss point is scouts.",
  "coverage_status": "PARTIAL",
  "query_type": "reverse_forensic",
  "matched_entities": ["MU"],
  "stage_diagnosis": [
    {"stage": "scouts", "status": "MISS"},
    {"stage": "event_cards", "status": "FOUND"},
    {"stage": "universe_filter", "status": "MISS"},
    {"stage": "collect", "status": "FOUND"},
    {"stage": "shortlist", "status": "MISS"},
    {"stage": "deep_selection", "status": "MISS"}
  ],
  "evidence_found": ["event_cards", "collect"],
  "evidence_missing": ["scouts", "universe_filter", "shortlist", "deep_selection"],
  "recommended_changes": [
    "Expand discovery triggers for target entities and relevant catalysts."
  ],
  "manual_gap_fill_requests": [
    "manual_event_specific_x_feed_pass",
    "manual_universe_context_confirm",
    "manual_selection_threshold_review"
  ],
  "confidence": 0.65
}
```

## Coverage status semantics

- `COMPLETE`: enough internal evidence exists to answer responsibly
- `PARTIAL`: some evidence exists, but important evidence or stage coverage is missing
- `MISSING`: internal evidence is too weak to answer responsibly

## Frontend rendering guidance

### Required UI sections

- summary
- coverage badge
- matched entities
- stage diagnosis timeline
- recommended changes
- manual gap-fill requests

### Required operator behavior

If `coverage_status != COMPLETE`, the UI should visibly show:

- that the answer is incomplete
- that no external retrieval has been run
- what manual gap-fill is recommended next

## Non-goals in `v1`

- no true live agent conversation loop
- no automatic scout reruns
- no automatic external fetching
- no required Zep integration
- no simulation runtime
