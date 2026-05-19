# PIT Master V2 Column Audit

- generated_at_utc: `2026-05-19T11:07:57.850207+00:00`
- master_csv: `/Users/aeternusholdings/Documents/Aeternus/outputs/fundamental_backtest/pit_master/fundamental_pit_master_v2.csv`
- master_sha256: `be973c75d1ef15eca3680ff056088d4e354795a98773dee7f9d58aaeb00f789b`
- rows: `17651`
- columns: `424`
- fully_blank_columns: `0`
- columns_blank_pct_gte_95: `41`

## Result

Pass: no whole-column blanks remain in `fundamental_pit_master_v2.csv`.

## Sparse Columns

Columns above 95% blank are not automatically wrong. They stay only when at least one row has a value and the value has audit or operator use. Full keep/drop reason is in `master_v2_column_audit.csv`.

- `period_context_missing_reason`: blank_pct `99.9547`, action `keep_sparse`, reason: Traceability/source field. Blank only when that source path does not apply.
- `entry_date_adjustment_reason`: blank_pct `99.9830`, action `keep`, reason: Core row identity, PIT date, entry price, or execution-timing contract field.
- `notes`: blank_pct `99.5184`, action `keep_sparse`, reason: SEC evidence note. Blank means normal evidence path; value flags fallback path used for a small set of rows.
- `tier_4_bucket`: blank_pct `95.9889`, action `keep_sparse`, reason: Signal/theme/risk-model field. Sparse because only some rows trigger each signal.
- `blocking_issues`: blank_pct `95.4790`, action `keep_sparse`, reason: LLM/audit field. Blank for rows that did not need LLM review; populated when LLM evidence exists.
- `positive_repricing_status`: blank_pct `98.7366`, action `keep_sparse`, reason: Reason/status field. Blank means no reason/status applied for that row.
- `warning_reasons`: blank_pct `98.8499`, action `keep_sparse`, reason: Reason/status field. Blank means no reason/status applied for that row.
- `top15_variants_selected`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_variant`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_selection_rank`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_selected_sleeve`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_selected_sleeve_rank`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_right_tail_exception_score`: blank_pct `99.5184`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_right_tail_exception_reason_codes`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_right_tail_exception_warning_codes`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_right_tail_exception_score_contributions`: blank_pct `99.5184`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_bucket`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_bucket_order`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_role`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_model`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_portfolio_treatment`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_operating_setting`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_operating_setting_validation_status`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_reason_codes`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `top15_override_reason_codes`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `shadow_variants_selected`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `shadow_variant`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `shadow_selection_rank`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `shadow_selected_sleeve`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- `shadow_selected_sleeve_rank`: blank_pct `98.5553`, action `keep_sparse`, reason: Selection/shadow field. Blank unless row is selected, reviewed, replaced, or needs PM action.
- ... plus `11` more in CSV audit.

## Files

- Full audit CSV: `/Users/aeternusholdings/Documents/Aeternus/docs/pit_walkforward_review/master_v2_column_audit.csv`
- Summary JSON: `/Users/aeternusholdings/Documents/Aeternus/docs/pit_walkforward_review/master_v2_column_audit_summary.json`
