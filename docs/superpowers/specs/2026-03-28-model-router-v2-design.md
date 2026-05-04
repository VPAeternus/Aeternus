# Model Router V2 Design

**Date:** 2026-03-28

## Goal
Build a safer Pi model-router extension that routes prompts to better-fit models without surprising the user.

## Scope
This design covers one Pi extension with:
- conservative auto-routing
- weighted route detection
- fallback model chains
- manual lock behavior after explicit model selection
- persisted `autoRoutingEnabled`
- balanced notifications and status updates
- local config overrides
- commands/tools for inspection, testing, validation, and switching

## Non-Goals
- per-turn temporary model swaps only
- rich analytics/history dashboards
- complex UI configuration editors
- persistence of lock state or route history

## Behavior Summary
- Auto-routing runs before agent start only when `autoRoutingEnabled=true` and router is not locked.
- Prompt classification uses weighted strong/weak/negative term scoring with a confidence threshold and ambiguity margin.
- Router only switches when the current model is materially mismatched for the winning route.
- If the primary target is unavailable, the router tries route fallbacks in order.
- Manual model selection or manual `switch_model` tool use locks the router until explicitly unlocked.
- The extension persists only `autoRoutingEnabled` via session custom entries.

## Architecture
### 1. Defaults + Config
Keep built-in route defaults in code. Load optional overrides from:
- project-local: `.pi/model-router.json`
- user-global: `~/.pi/agent/model-router.json`

Project-local overrides user-global. Invalid files warn and fall back to defaults.

### 2. Classifier
Each route has:
- primary target + fallbacks
- thinking level
- strong/weak/negative phrase lists
- route description/example

Classifier outputs:
- scores by route
- matched terms by route
- winning route
- confidence (`none|medium|high`)
- ambiguity state

### 3. Policy
Routing policy decides whether to switch based on:
- auto-routing enabled
- lock state
- classifier confidence
- ambiguity margin
- current model match quality
- availability of primary/fallback targets

### 4. Persistence
Persist only:
- `autoRoutingEnabled`

Do not persist:
- lock state
- previous route
- transient route history

### 5. Commands
- `/model-router`
- `/model-router-auto on|off`
- `/model-router-lock on|off`
- `/model-router-test <prompt>`
- `/model-router-validate`
- `/model-router-reset`

### 6. Tools
- `get_current_model_info`
- `list_available_models`
- `switch_model`
- `recommend_model_for_task`

Manual tool switching should lock the router, matching manual `/model` intent.

## Default Routes
- `hard_reasoning`
  - primary: `openai-codex/gpt-5.4`
  - fallbacks: `anthropic/claude-sonnet-4-6`
- `fast_code`
  - primary: `openai-codex/gpt-5.3-codex-spark`
  - fallbacks: `anthropic/claude-haiku-4-5`
- `smart_small_refactor`
  - primary: `openai-codex/gpt-5.4-mini`
  - fallbacks: `anthropic/claude-sonnet-4-6`
- `frontend_design`
  - primary: `anthropic/claude-opus-4-6`
  - fallbacks: `anthropic/claude-sonnet-4-6`

## Error Handling
- Invalid config: warn, use defaults.
- Missing target/fallback models: warn, stay on current model.
- No UI: routing still works; notifications are skipped naturally.

## Testing Strategy
Use Node test runner with `--experimental-strip-types` against exported pure functions:
- weighted scoring
- ambiguity detection
- conservative mismatch policy
- fallback resolution
- config merge behavior

## Success Criteria
- Strong prompts route to the intended model family.
- Ambiguous prompts do not auto-switch.
- Manual model selection prevents future auto-routing until unlocked.
- Router survives unavailable models via fallbacks.
- `/reload` and session restart preserve only the auto-routing enabled setting.
