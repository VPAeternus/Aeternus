# Aeternus Implement Prompt (Execution Playbook)

Use this prompt to run implementation sessions with consistent quality.

## Implementation Prompt

You are implementing Aeternus features in a production-bound research and trading intelligence system.

### Read order before coding

1. `memory/Prompt.md`
2. `memory/Plans.md`
3. `memory/Architecture.md`
4. `memory/WORKING.md`
5. latest `memory/YYYY-MM-DD.md`

### Objective selection

1. Select the highest-priority open milestone from `memory/Plans.md`.
2. Confirm the objective and explicit acceptance criteria.
3. Do not start lower-priority milestones until active milestone exit criteria are met.

### Execution standards

1. Prefer deterministic logic for scoring/risk/controls.
2. Keep changes surgical and backward-compatible.
3. Add or update tests for every changed behavior.
4. Emit/extend audit events for critical lifecycle transitions.
5. Fail gracefully when external data sources are unavailable.

### Required validations

1. Run targeted tests for touched modules.
2. Run full regression suite before handoff.
3. Run command-level smoke tests for changed CLI surfaces.

### Memory updates before handoff

1. Update `memory/WORKING.md` with:
   - objective
   - completed actions
   - next steps
   - blockers
2. Append the day log in `memory/YYYY-MM-DD.md`.
3. Update `memory/Documentation.md`:
   - milestone status
   - key architectural decisions
4. Update `memory/MEMORY.md` only for enduring architecture decisions.

### Response format for handoff

1. What changed (files and behavior).
2. Validation run (commands and results).
3. Residual risks or known gaps.
4. Next 1-3 concrete actions.
