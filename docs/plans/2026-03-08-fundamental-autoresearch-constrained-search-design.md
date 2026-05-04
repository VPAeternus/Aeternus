# Fundamental Autoresearch Constrained Search Design

Date: 2026-03-08

## Purpose

Explore the highest-probability post-baseline search space without opening the full autoresearch loop.

## Search Space

- `health` as a positive signal
- `growth` as an inverted/crowding signal
- `quality` as an inverted/crowding signal

## Method

- deterministic fixed grid
- bounded weights that sum to `1.0`
- same historical dataset
- same sector-neutral `60d` rank IC evaluator

## Why This Slice

The historical baseline comparison showed:
- `health_only` is positive
- positive `growth` / `quality` are weak-to-negative
- inverted `growth` / `quality` variants are stronger

So the highest-probability next move is a constrained search around the surviving factors, not a full open-ended loop.

## Output

- ranked `constrained_search.json`
- each row contains:
  - strategy name
  - component weights
  - primary metric
  - coverage ratio
  - observations

## Success Criteria

- identify whether the best blend is:
  - mostly health
  - health plus inverted growth
  - health plus inverted quality
  - or a balanced three-way blend
