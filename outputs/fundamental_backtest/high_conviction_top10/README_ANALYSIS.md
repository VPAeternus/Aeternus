# High-Conviction Top-10 Fundamental Backtest

Artifacts:
- `selected_names_by_quarter.csv`: selected variant-quarter-rank rows with diagnostic labels.
- `strategy_by_quarter.csv`: per-variant, per-quarter return and winner/loser aggregates.
- `strategy_summary.csv`: aggregate strategy performance by variant.
- `variant_summary.csv`: locked config and shortfall counts.
- `misses_analysis.csv`: top non-selected eligible names with diagnostic labels and miss reason.
- `theme_bucket_summary.csv`: selected pick performance by theme bucket.
- `rm_hp_tier_contribution.csv`: selected pick performance by HP/RM/tier signal-count buckets.
- `run_manifest.json`: input/output hashes, run metadata, locked configs, guardrail evidence.

Labels/outcomes are diagnostic only. Selection never receives forward returns, winner/loser labels, or other forbidden outcome columns; labels are attached after tickers/ranks are frozen.
