# Fundamental Autoresearch Baseline Comparison Design

Date: 2026-03-08

## Objective

Compare a small deterministic suite of baseline scoring strategies on the same historical `2009+` filing dataset before introducing any automated search loop.

## Why

The first real historical run produced a weak naive baseline:

- `rank_ic_60d_sector_neutral = -0.055066`
- `observations = 1588`

Before searching weights automatically, the system should determine which factor families deserve to survive at all.

## Strategy Suite

- `baseline_v1`
- `growth_only`
- `quality_only`
- `health_only`
- `capital_discipline_only`
- `valuation_only`
- `growth_quality`
- `quality_valuation`

## Scoring Contract

Keep one scoring implementation path:

- `score_feature_row(features, strategy="baseline_v1")`

Sub-score definitions stay fixed.
Only the deterministic blend weights change.

## Evaluation Contract

Each strategy is evaluated on the same prepared dataset using the existing evaluator:

- primary metric:
  - `rank_ic_60d_sector_neutral`
- same coverage accounting
- same observation counts

## Output

Write one comparison artifact:

- `baseline_comparison.json`

Each row includes:

- `strategy`
- `primary_metric_name`
- `primary_metric_value`
- `coverage_ratio`
- `observations`

Sorted best-to-worst by primary metric.

## CLI

Add:

- `fundamental-research-compare-baselines`

Inputs:

- `--prepared-json`
- `--results-root`
- `--run-date`
- `--experiment-name`

## Success Criteria

- fixed baseline suite runs on the real historical dataset
- comparison artifact is reproducible
- results show which factor families help or hurt
- no search loop yet
- no live pillar changes yet
