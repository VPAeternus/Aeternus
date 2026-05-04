# Registry-Driven Fundamental Factor Design

## Goal

Make the live SEC fundamental connector consume the deterministic autoresearch winner from the fundamental signal registry instead of serving a hardcoded baseline formula.

## Problem

The current live connector in `tradingagents/dealflow/sources/fundamental_factor.py` hardcodes baseline-style formula weights directly into the serving path. The historical SEC harness has already shown that the best current strategy is a health-led anti-crowding blend, not the baseline positive growth/quality formula. If live serving and research use different formulas, the system will drift immediately.

## Decision

The research harness remains the source of truth for:
- strategy name
- component weights
- promotion status

The live connector becomes a runtime adapter that:
- loads the active strategy from the registry
- fetches/caches current SEC data for the active universe
- builds live feature rows using the same harness prep contract
- scores those rows with the active registry weights
- emits a live `DealFlowSignal`

## Live Contract

### Registry states

- `promoted`
  - emitted as `fundamental_factor`
- `shadow`
  - emitted as `fundamental_factor_shadow`
- missing / invalid / rejected
  - emitted as `NOT_CONFIGURED` or `NO_DATA`
  - no hidden fallback to hardcoded weights

### Serving behavior

- Use the registry row's `weights` field when present
- Fall back to built-in named strategy weights only if the registry strategy name maps to a deterministic built-in strategy
- Prefer a `promoted` strategy when available
- Fall back to the best `shadow` strategy when no promoted strategy exists
- Attach clear source metadata indicating whether the signal is `shadow` or `promoted`

## Architecture

### Research side

`tradingagents/research/fundamental_autoresearch/registry.py`
- add helpers to load the latest registry and resolve the active strategy

### Live side

`tradingagents/dealflow/sources/fundamental_factor.py`
- stop owning formula weights
- use harness SEC fetch/cache + prepare layer
- score current rows with registry-driven component weights

### Pipeline side

`tradingagents/dealflow/contracts.py`
- allow `fundamental_factor_shadow`

No scoring-weight changes in this slice. Shadow stays observable only.

## Success Criteria

- the live connector no longer owns a hardcoded formula
- registry is the source of truth for active SEC fundamental weights
- current winner can be served live in `shadow`
- live pipeline sees the shadow factor without affecting capital decisions

## Guardrails

- no hidden fallback to old baseline weights
- no automatic promotion into live scoring
- degrade clearly when the registry is missing or unusable
- keep the slice surgical: governance change first, scoring impact later
