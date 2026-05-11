# Question Compiler Chat Backend Design

**Date:** 2026-03-17

**Status:** Approved design, pre-implementation

## Goal

Add a chat-shaped backend to Aeternus that lets an operator ask questions like:

- `MU went up 10% today, why did we miss it?`
- `Trump announced war on Iran, how does this impact our portfolio?`

The UI should feel like a simple chat page, but the backend should behave like a structured investigation engine focused on alpha capture and pipeline diagnosis.

## What We Are Building

We are not building a generic chatbot.

We are building a Python investigation backend with a chat-style entrypoint. Each user message becomes a structured investigation request that is evaluated against real Aeternus state:

- daily Event Cards
- coverage precheck
- scout quality
- discovery artifacts
- universe filter
- collect outputs
- candidate_list / fundamental review list
- fundamental-intake and hindsight helpers
- AKG context when useful

## Why We Are Not Copying MiroFish Chat Literally

MiroFish chat is a report/query layer on top of:

- uploaded documents
- ontology generation
- Zep graph construction
- simulation preparation
- live or completed simulation state
- a report agent with bounded tool calls

That is the right shape for a simulation world. It is the wrong substrate for Aeternus `v1`.

For Aeternus, the primary truth is not a simulated graph report. It is the actual market-intelligence pipeline.

So we will copy the interaction pattern:

- user asks a question
- backend compiles the question
- backend retrieves internal context
- backend uses bounded reasoning/tooling only when needed
- backend returns an answer with traceability

But we will not copy:

- report-first answering
- simulation-agent interviews
- social-world assumptions
- Zep as a required dependency

## Core Architectural Decision

`v1` will be implemented as Python modules, not a Zep-backed agent system.

### No required Zep integration in `v1`

Reasons:

- Aeternus already has structured artifacts and AKG
- the first use case is stage diagnosis, not semantic world simulation
- deterministic artifact inspection will be cheaper, easier to debug, and more aligned with alpha-focused workflows

Zep or a semantic document-memory layer may become useful later for:

- SEC excerpt retrieval
- X/news snippet retrieval
- broader scenario-runtime support

But it is not required for the first backend.

## Product Shape

### Frontend

A simple chat page:

- one input box
- one answer panel
- one lightweight progress/status rail

### Backend

A Python investigation service behind that page.

The backend receives a question and turns it into an investigation job.

## Supported Question Modes in `v1`

### 1. Reverse Forensic

Examples:

- `MU went up 10% today, why did we miss it?`
- `Why didn't we flag NVDA before this move?`

Purpose:

- identify the first miss point
- show what evidence existed
- show what evidence was absent
- propose changes to improve alpha capture

### 2. Forward Scenario

Examples:

- `Trump announced war on Iran, what happens to our portfolio?`
- `This filing implies flash demand is a leading indicator for AI deployment, who benefits?`

Purpose:

- identify direct impacts
- identify second-order candidates
- identify portfolio risk / hedge implications
- identify missing evidence before stronger conclusions

## Backend Components

### 1. `question_compiler.py`

Responsibilities:

- classify the question
- extract target entities, date references, observed move, and intent
- build a normalized `Investigation Packet`

Preferred behavior:

- rules/regex first
- optional bounded LLM fallback only when the question is ambiguous

### 2. `investigation_runner.py`

Responsibilities:

- orchestrate the investigation
- load relevant artifacts
- run stage-by-stage analysis
- assemble final structured findings

### 3. `stage_checkers/`

Responsibilities:

- inspect each pipeline layer independently

Initial stage checkers:

- scouts
- Event Cards
- universe filter
- collect
- candidate_list
- fundamental intake

### 4. `gap_detector.py`

Responsibilities:

- detect whether evidence is sufficient
- list exactly what is missing
- never auto-fetch in `v1`

### 5. `response_synthesizer.py`

Responsibilities:

- convert structured findings into frontend-ready output
- optionally use one bounded LLM call for clearer prose

## Investigation Packet

The `Investigation Packet` is the Aeternus equivalent of MiroFish’s compiled question context.

Example shape:

```json
{
  "query_type": "reverse_forensic",
  "intent": "missed_alpha_diagnosis",
  "raw_question": "MU went up 10% today, why did we miss it?",
  "target_entities": ["MU"],
  "observation": {
    "kind": "price_move",
    "value": "+10%",
    "date": "2026-03-17"
  },
  "required_stages": [
    "scouts",
    "event_cards",
    "universe_filter",
    "collect",
    "candidate_list",
    "fundamental_intake"
  ],
  "required_dimensions": [
    "social",
    "technical",
    "macro",
    "filing",
    "options",
    "portfolio"
  ],
  "manual_only": true
}
```

## End-to-End Flow

When the user types:

`MU went up 10% today, why did we miss it?`

the flow should be:

1. frontend submits question to backend
2. `question_compiler.py` classifies the question as `reverse_forensic`
3. backend creates the `Investigation Packet`
4. backend loads internal artifacts
5. stage checkers run in order
6. backend determines the first likely miss point
7. backend builds fix proposals
8. backend checks whether evidence is incomplete
9. backend returns structured answer

If evidence is incomplete, the backend must stop and explicitly say so.

## Required Internal Sources

`v1` should inspect only internal state first.

Primary sources:

- `event_cards.json`
- `coverage_precheck.json`
- `scout_quality_daily.json`
- `scout_compiler_debug.json`
- `discovery_delta.json`
- `universe_filter.json`
- scored-candidate / collect artifacts
- candidate_list artifacts
- fundamental review list artifacts
- hindsight / why-missed helpers
- AKG context when available and cheap

## Response Shape

The response must be frontend-ready.

Minimum fields:

```json
{
  "summary": "MU was first missed in the scout lane; no event card or downstream ranking chance existed.",
  "coverage_status": "PARTIAL",
  "query_type": "reverse_forensic",
  "matched_entities": ["MU"],
  "stage_diagnosis": [],
  "evidence_found": [],
  "evidence_missing": [],
  "recommended_changes": [],
  "manual_gap_fill_requests": [],
  "confidence": 0.74
}
```

## LLM Usage Policy

The backend should be mostly deterministic.

### Required principle

Use Python for facts. Use LLM only for ambiguity or language.

### Expected `v1` usage

- `0` LLM calls for stage retrieval
- `0` LLM calls for deterministic stage diagnosis
- `0-1` LLM calls for question parsing
- `0-1` LLM calls for final synthesis

Typical question:

- best case: `0` calls
- normal case: `1` call
- hard upper bound in `v1`: `2` calls

## Relation to Existing Fundamental Computation

This follows the same principle as the current fundamental engine.

`tradingagents/agents/utils/fundamental_engine.py` is already:

- pure Python
- no LLM calls
- deterministic feature computation from vendor payloads

The new chat backend should follow the same approach:

- structured Python computation for evidence and diagnosis
- optional LLM only at boundaries

## Error Handling and Guardrails

### `v1` rules

- never auto-run scouts
- never auto-fetch external data
- never auto-trigger gap fill
- always return explicit missing evidence lists
- prefer incomplete-but-honest over speculative answers

### Coverage statuses

- `COMPLETE`: enough internal evidence to answer responsibly
- `PARTIAL`: some answer possible, but important evidence missing or stale
- `MISSING`: not enough internal evidence to answer responsibly

## Why This Design Fits the Frontend MVP

The frontend can look like chat, but the backend remains structured and auditable.

This gives us:

- operator-friendly UX
- alpha-focused diagnostics
- bounded cost
- explainable answers
- future compatibility with richer scenario runtime work

## Future Extensions

Not part of `v1`, but intentionally compatible:

- manual gap-fill workflow
- richer question threading
- semantic document retrieval layer
- actor compiler
- full scenario runtime
- Event Card influence on discovery and ranking

## Approved Boundaries

- manual mode only
- Python-first backend
- no required Zep integration
- no automatic external retrieval
- optimized first for alpha-forensics, not general chat
