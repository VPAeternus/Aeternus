# Qwen Feature Lab Design

Date: 2026-03-09

## Problem

The existing Qwen autoresearch loop was spending effort on tiny, mostly enumerable weight perturbations around a very small constrained space. That is useful as a smoke test, but it is not the highest-value use of a local model.

## Decision

Move Qwen up one layer:

- keep brute force / deterministic search for tiny weight spaces
- use Qwen for bounded feature and interaction proposal work
- keep the deterministic SEC filing harness as the judge

## V1 Shape

Add a bounded Qwen Feature Lab:

- fixed base strategy:
  - `health_0p5__inv_growth_0p1__inv_quality_0p4`
- fixed experimental component catalog:
  - `growth_acceleration`
  - `margin_expansion`
  - `quality_tension_inverse`
  - `balance_sheet_resilience`
- Qwen proposes only:
  - `base_weight`
  - zero, one, or two experimental overlays

Guardrails:

- base strategy remains dominant
- no arbitrary code generation
- no open-ended factor invention
- deterministic evaluator remains the judge

## Why

This keeps Qwen in the part of the problem where it can add real value:

- proposing bounded new feature combinations
- not wasting cycles rediscovering tiny local weight tweaks we can brute-force

## Outputs

- new module:
  - `tradingagents/research/fundamental_autoresearch/qwen_feature_lab.py`
- new CLI:
  - `fundamental-research-qwen-feature-lab`
- standard autoresearch artifacts:
  - `autoresearch_summary.json`
  - `best_strategy.json`
  - `leaderboard.json`
