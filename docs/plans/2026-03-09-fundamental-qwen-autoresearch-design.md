# Fundamental Qwen Autoresearch Design

## Goal

Add a local-MLX Qwen experiment runner that proposes constrained fundamental weight configurations, then lets the deterministic SEC filing harness evaluate those proposals on the `2009+` historical dataset.

## Why

The constrained deterministic search is already working, but it only explores the fixed grid encoded in the current search generator. Qwen should now enter as an experiment proposer, not as the scoring engine or judge.

## Design

### Core contract

- Qwen runs against a local OpenAI-compatible MLX server.
- Qwen receives:
  - the current top constrained leaderboard
  - the allowed factor set
  - hard constraints on sign and total weight
- Qwen returns JSON proposals for new weight configurations.
- The deterministic evaluator:
  - normalizes and validates each proposal
  - scores the historical filing dataset
  - ranks proposals by the same primary metric used elsewhere

### Constraints

Allowed factors in v1:
- `health` (must stay positive)
- `growth` (must stay non-positive)
- `quality` (must stay non-positive)
- `capital_discipline` (must stay non-negative)
- `valuation` (must stay non-negative)

Normalization rules:
- weights are clipped to allowed sign domains
- weights are normalized to sum to `1.0`
- `health` must remain the dominant positive component

### Output

The runner writes a Qwen-specific autoresearch artifact containing:
- prompt metadata
- raw proposals
- normalized proposals
- evaluated leaderboard
- best strategy
- optional promotion-ready registry rows

### Guardrails

- No live pipeline changes
- No automatic promotion into the registry yet
- Clear failure if the local MLX server is unavailable
- Tests must not depend on a real model server

## Expected result

We get an autonomous local research loop that can search beyond the hand-coded constrained grid while keeping the deterministic evaluator as the source of truth.
