# PIT Acceptance Review Commands

Accepted code commit: `364b91933ff6d6cccc6afa6c64609a5f0cf5a322`

These commands produced the portable evidence summarized in this folder. Large CSVs stay local; hashes are recorded in `artifact_hashes.csv`.

## Focused tests

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_scoring_inputs.py tests/test_fundamental_daily_finalize_gate.py tests/test_fundamental_panel_schema.py tests/test_fundamental_panel_normalize.py tests/test_fundamental_panel_exporter.py tests/test_fundamental_panel_validate.py tests/test_fundamental_pit_master.py tests/test_fundamental_pit_master_reconciliation_gate.py tests/test_fundamental_row_contract.py tests/test_fundamental_panel_financial_values.py tests/test_fundamental_panel_financial_no_rewrite.py tests/test_fundamental_trading_calendar.py -q
git diff --check
```

Result recorded during run: `83 passed`; `git diff --check` passed before code commits.

## 2022Q1 full acceptance

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m cli.main fundamental-run-quarter \
  --mode broad-master-final \
  --date 2022-03-31 \
  --quarter 2022Q1 \
  --master-universe tradingagents/research/fundamental/data/master_fundamental_universe_start_2021Q4.json \
  --prior-final-scores tradingagents/research/fundamental/runs/2021-12-31/2021Q4/walkforward_clean_v1/qoq_context_only_2021Q4.csv \
  --llm-mode post-file \
  --post-llm tradingagents/research/fundamental/runs/2022-03-31/2022Q1/pit_repair_full_acceptance_v1/post_llm_scores_expected_36.csv \
  --allow-missing-handoff \
  --emit-complete-panel \
  --output-root tradingagents/research/fundamental/runs/2022-03-31/2022Q1/pit_repair_full_acceptance_v5 \
  --complete-panel-output-root tradingagents/research/fundamental/runs/2022-03-31/2022Q1/pit_repair_full_acceptance_v5/complete_panel \
  --format json
```

## 2026Q1 full acceptance

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m cli.main fundamental-run-quarter \
  --mode broad-master-final \
  --date 2026-03-31 \
  --quarter 2026Q1 \
  --master-universe tradingagents/research/fundamental/data/master_fundamental_universe_start_2021Q4.json \
  --prior-final-scores tradingagents/research/fundamental/runs/2025-12-31/2025Q4/walkforward_clean_v1/fundamental_final_scores_2025-12-31.csv \
  --llm-mode post-file \
  --post-llm tradingagents/research/fundamental/runs/2026-03-31/2026Q1/pit_repair_full_acceptance_v1/post_llm_scores_expected_78.csv \
  --allow-missing-handoff \
  --emit-complete-panel \
  --output-root tradingagents/research/fundamental/runs/2026-03-31/2026Q1/pit_repair_full_acceptance_v5 \
  --complete-panel-output-root tradingagents/research/fundamental/runs/2026-03-31/2026Q1/pit_repair_full_acceptance_v5/complete_panel \
  --format json
```
