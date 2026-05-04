# Fundamental Autoresearch Baseline Comparison Plan

Date: 2026-03-08

## Tasks

1. Add deterministic named scoring strategies to `score.py`.
2. Add a comparison helper that evaluates the fixed strategy suite on one prepared dataset.
3. Add an artifact writer for `baseline_comparison.json`.
4. Add `fundamental-research-compare-baselines` CLI command.
5. Add focused tests for strategy scoring and comparison output.
6. Run the baseline suite on the real `large_cap_v1-2009plus` dataset.

## Verification

- focused strategy/comparison/CLI test sweep
- real comparison artifact on the historical dataset
- ranked best-to-worst output

## Goal

Determine which fundamental factor families deserve to survive before building any automated score-search loop.
