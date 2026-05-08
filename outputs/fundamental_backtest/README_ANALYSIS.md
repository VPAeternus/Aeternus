# Fundamental PIT Backtest Panel

`pit_fundamental_panel.csv` separates selection-time features from outcome labels.

- Selection schema: `feature_schema.json`
- Outcome schema: `label_schema.json`
- Audit manifest: `run_manifest.json`

Guardrails:
- Outcome labels are not selection features.
- `winner_90d_30pct` and `loser_90d_minus30pct` derive only from `return_90d_pct`.
- `eligible_for_backtest` is false for missing key selection fields, future-date anomalies, or missing 90-day return labels.
- Missing PIT-unproven theme/macro fields stay blank in the panel and diagnostic in `run_manifest.json`.
