# Aeternus Harness v1 (Deep-Research Spec)

## Objective
Build one runtime that turns a natural-language investment question into:

1. a deterministic execution path,
2. a policy-gated recommendation,
3. an auditable artifact trail,
4. a learning record for hindsight.

This is the "ask -> execute -> explain -> learn" product layer.

---

## Research Takeaways (Perplexity Computer + Manus)

### Source-backed patterns we should adopt
- **Single conversation to multi-step execution**:
  - Perplexity positions Computer as end-to-end execution in one thread (research/design/code/deploy/manage).
- **Parallel decomposition over long-context brute force**:
  - Perplexity and Manus both emphasize parallel research/sub-agent decomposition for multi-item tasks.
- **Sandboxed execution**:
  - Both products frame isolated execution environments as core safety architecture.
- **Reusable skills as first-class control objects**:
  - Perplexity supports built-in + uploaded `SKILL.md` style skills.
  - Manus supports Project Skills as a bounded project-level skill library.
- **Connector-native workflow automation**:
  - Both expose broad connector surfaces and asynchronous workflows.
- **Operator control and auditability**:
  - Perplexity Enterprise surfaces SOC2 posture, audit logs, admin controls.
  - Manus Browser Operator requires explicit local authorization and supports intervention.

### What we should not copy blindly
- **Generic task breadth over decision quality**:
  - Aeternus should stay narrow: investment decisions, portfolio actions, scenario response, and miss diagnosis.
- **Unbounded automation**:
  - v1 should remain recommendation-first (no automatic brokerage execution).
- **Opaque "agent magic"**:
  - Every stage must emit explicit progress and reasons for passes/failures.

---

## Harness v1 Product Contract

## 1) Single Entry Runtime
`POST /harness/query`

Request:
- `question` (required)
- `symbols` (optional)
- `as_of_date` (optional)
- `portfolio_context` (optional; defaults to latest snapshot)
- `allow_external_search` (bool)
- `mode_hint` (optional: `DECIDE|SCENARIO|DIAGNOSE_MISS|PORTFOLIO_ACTION`)

Response:
- `run_id`
- `mode`
- `execution_level` (`L0_PRECHECK|L1_PIPELINE|L2_DEEP_RESEARCH`)
- `execution_gate`
- `answer`
- `decision_payload`
- `artifacts`
- `known_gaps`
- `next_actions`

## 2) Mode Compiler
Classify question into:
- `DECIDE`: buy/hold/watchlist for ticker(s)
- `SCENARIO`: exogenous shock and cascade impact
- `DIAGNOSE_MISS`: root cause for missed move / false negative
- `PORTFOLIO_ACTION`: add/trim/hedge/rotate now

Rules:
- if confidence `< mode_threshold`: ask one forced clarification.
- if `mode_hint` exists and conflicts with classifier, record both and continue with higher-confidence path.

## 3) Execution Levels
- **L0_PRECHECK** (always first):
  - freshness
  - coverage completeness
  - artifact availability
  - manual-input readiness
- **L1_PIPELINE** (standard run):
  - discovery -> collect -> candidate_list -> fundamental-intake -> analysis synthesis
- **L2_DEEP_RESEARCH** (gated escalation):
  - committee debate + optional web enrichment + scenario expansion

Promotion:
- L2 only when decision-critical gaps remain after L0/L1.

---

## Runtime Architecture

## A) Control Plane
- `HarnessRouter`:
  - owns run lifecycle and state machine
  - emits progress events
- `PolicyGate`:
  - enforces stale-context blocks, action downgrades, trigger requirements
- `ManualInputManager`:
  - prints exact prompt
  - pauses in WAIT state
  - validates pasteback
  - resumes run

## B) Data Plane
- `ContextAssembler`:
  - latest portfolio + macro state
  - x-feed/manual scout artifacts
  - pipeline artifacts
  - pre/post-LLM score deltas
  - stage diagnosis metadata
- `ModeEngines`:
  - `DecideEngine`
  - `ScenarioEngine`
  - `MissEngine`
  - `PortfolioActionEngine`

## C) Learning Plane
- `RunRecorder`:
  - persists normalized run artifact
- `OutcomeLinker`:
  - links recommendation IDs to hindsight outcomes
- `AttributionWriter`:
  - appends source/scout attribution and stage drop reasons

---

## Harness State Machine (Deterministic)

1. `RECEIVED`
2. `MODE_CLASSIFIED`
3. `PRECHECK_RUNNING`
4. `PRECHECK_COMPLETE`
5. `WAITING_MANUAL_INPUT` (optional, repeatable)
6. `PIPELINE_RUNNING`
7. `DEEP_RESEARCH_RUNNING` (optional)
8. `POLICY_GATING`
9. `NARRATIVE_COMPOSE`
10. `PERSISTED`
11. `COMPLETED` or `BLOCKED`

Every transition writes timestamped event rows.

---

## Terminal UX Contract (v1)

Required progress checkpoints:
1. `Mode: <...> (confidence: x.xx)`
2. `Precheck: PASS|DEGRADED|BLOCKED`
3. `Coverage: pipeline=<...> xfeed=<...> portfolio=<...>`
4. `Running stage: <name>`
5. `Manual input required: <collector>`
6. `Manual input validated: <collector>`
7. `Policy gate: <result>`
8. `Final action set: <...>`

Manual loop behavior:
- emit copy/paste prompt block,
- pause until payload is pasted,
- validate schema immediately,
- if invalid: show exact parse error + retry prompt,
- if valid: persist and continue automatically.

---

## Decision Payload Contract (v1)

```json
{
  "mode": "DECIDE",
  "execution_gate": {
    "status": "PASS",
    "reasons": []
  },
  "decision": {
    "symbol": "AAPL",
    "action": "WATCHLIST",
    "confidence": 0.62,
    "rating": "Buy",
    "score_context": {
      "pre_llm_score": 61.1,
      "post_llm_score": 62.8,
      "delta": 1.7
    },
    "entry_trigger_numeric": [
      {"metric": "vix_close", "operator": "<=", "value": 20.0}
    ],
    "invalidation_trigger_numeric": [
      {"metric": "final_score", "operator": "<", "value": 60.0}
    ],
    "review_trigger_numeric": [
      {"metric": "days_since_decision", "operator": ">=", "value": 5}
    ]
  },
  "known_gaps": [],
  "data_freshness": {
    "portfolio_snapshot_stale": false
  },
  "artifacts": {
    "analysis_report": "results/AAPL/<date>/analysis_report.json",
    "stage_diagnosis": "eval_results/.../stage_diagnosis.json"
  }
}
```

---

## v1 Safety Rules (Non-negotiable)

- No auto brokerage execution.
- No OPEN/INCREASE if `execution_gate.status != PASS`.
- No recommendation without numeric entry/invalidation/review triggers.
- External search can enrich, never silently overwrite packet facts.
- All outputs must include `known_gaps`, `data_freshness`, `source_trace`.

---

## Build Plan (v1)

1. Implement `HarnessRouter` + run state machine.
2. Integrate mode compiler and `mode_hint` override logic.
3. Unify precheck gate (freshness/coverage/manual readiness).
4. Wire `DecideEngine` and `MissEngine` first.
5. Add `ScenarioEngine` and `PortfolioActionEngine`.
6. Add terminal progress event bus + manual wait/paste loop.
7. Persist run artifact schema + hindsight linkage.
8. Add contract tests for all four modes and all gate statuses.

---

## Definition of Done

- One query triggers one observable deterministic run.
- Operators can see exactly where the system is and why.
- `DIAGNOSE_MISS` cites authoritative stage-drop metadata.
- `SCENARIO` returns impact + confidence penalties when coverage is partial.
- Artifacts are replayable and policy-verifiable.

---

## Direct Thesis Fit

Perplexity and Manus show that harness quality is the multiplier.
Aeternus v1 applies that pattern to one narrow high-value vertical:

- capital allocation decisions for individuals,
- with transparent gates, not black-box output.
