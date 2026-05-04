# Capital Discipline Search and Shadow Overlay Design

**Date:** 2026-03-09

## Goal

Add `capital_discipline` as the next constrained moderator in the fundamental autoresearch harness, and add a read-only shadow fundamental overlay to today's live scoring path.

## Scope

Two tightly scoped tracks:

1. Fundamental autoresearch
- widen the constrained search space so `capital_discipline` can carry a small positive weight
- keep `health` dominant
- keep `growth` and `quality` inverted-only
- set `valuation` back to zero for this slice

2. Live scoring / session analysis
- compute a shadow overlay from anchored fundamental subscores
- persist the overlay beside the existing `fundamental_sub`
- do not change the official fundamental pillar score

## Approach

### Capital Discipline Search

The constrained generator in `tradingagents/research/fundamental_autoresearch/search.py` will be widened to allow:

- `health > 0`
- `growth <= 0`
- `quality <= 0`
- `capital_discipline >= 0`
- `valuation = 0`

Guardrails:

- `health >= 0.4`
- `health >= capital_discipline`
- absolute weights sum to `1.0`

Success is only claimed if the new best strategy beats the current canonical winner:

- `health_0p5__inv_growth_0p1__inv_quality_0p4 = +0.087029`

### Shadow Overlay

The live and session-analysis paths will compute a read-only overlay from anchored fundamental subscores:

`overlay = 0.5 * health + 0.4 * (100 - quality) + 0.1 * (100 - growth)`

Persisted fields:

- `fundamental_overlay_score`
- `fundamental_overlay_label`
- `fundamental_overlay_notes`

The overlay is advisory only in v1. It does not feed the official Aeternus score, portfolio decisions, or ranking.

## Files

### Autoresearch

- Modify: `tradingagents/research/fundamental_autoresearch/search.py`
- Modify: `tests/test_fundamental_autoresearch_search.py`
- Modify: `tests/test_fundamental_autoresearch_autoresearch.py`

### Live scoring

- Modify: `tradingagents/graph/session_assembler.py`
- Modify: `tradingagents/graph/aeternus_scoring.py`
- Modify: `tests/test_session_assembler.py`
- Modify: `tests/test_aeternus_scoring.py`

## Risks

- search-space broadening could overfit if constraints are loosened too far
- shadow overlay could accidentally leak into the official score if inserted carelessly
- live/session output drift if the overlay is implemented in only one path

## Verification

- focused autoresearch search/autoresearch tests
- focused session/scorer tests for overlay presence and non-interference
- combined focused regression over both tracks
