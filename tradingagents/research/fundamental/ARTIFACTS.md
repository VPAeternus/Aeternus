# Fundamental Artifact Contract

## Canonical run root

New CLI defaults write generated artifacts under:

`tradingagents/research/fundamental/runs/<date>/<quarter>/<workflow>/`

Examples:

- `runs/2026-05-12/2026Q2/daily/`
- `runs/2026-05-12/2026Q2/legacy_scout/`
- `runs/2026-05-12/selection/`
- `runs/backtests/`

`runs/` is git-ignored. Commit code, tests, docs, and small fixtures only. Tests may override the framework root with `AETERNUS_FUNDAMENTAL_ROOT`.

## Stable final filenames

Official Top 10 + Plus 5 publish files must use stable names:

- `high_conviction_top15.csv`
- `high_conviction_top15.json`
- `high_conviction_top15_daily_recommendation.md`
- `high_conviction_top15_core_deterioration_refill_shadow.csv`
- `core_deterioration_refill_shadow_replacements.csv`
- `publish_guard_summary.json`
- `publish_guard_summary.md`

The date/quarter belongs in the folder path, not the final filename.

## Daily workflow layout

A broad daily final run should organize files like this:

```text
runs/<date>/<quarter>/daily/
  inputs/
  diagnostics/
  lake/
  llm_batches/
  final/
  run_manifest.json
  daily_fundamental_run_report.md
```

Current orchestrator still writes several artifacts at the run root for backward compatibility. New work should move toward the layout above without breaking existing readers.

## Diagnostics vs final outputs

Diagnostics may include QoQ merge tables, score-ready tables, identity reviews, quarantine tables, and coverage manifests. They must be clearly labeled and kept separate from official final files.

Bad pattern:

- `fundamental_final_scores_2026-05-12_qoq_llm_complete_selection_input.csv` as a user-facing final output.

Good pattern:

- `diagnostics/qoq_selection_input.csv`
- `final/high_conviction_top15.csv`

## Legacy artifact locations

Historical runs may still exist under:

- `/eval_results/fundamental/`
- `/outputs/fundamental_backtest/`

Those are legacy archive locations, not the forward default for new fundamental CLI runs or backtest generators.

## Retention policy

- Keep final publish artifacts and run manifests.
- Keep diagnostics only when they support audit/reproducibility.
- Delete temporary packets, failed scratch outputs, and duplicate CSVs once a stable final artifact exists.
- Promote only small deterministic fixtures into git.
