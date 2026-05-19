# PIT Periodfix Walkforward Commands

Fix validation added:
- accepted score-producing rows require `target_period_end`, `fiscal_period_start`, `fiscal_period_end`, and `period_context_source`
- `period_context_missing_reason` must be blank for accepted score-producing rows
- every selected financial fact end must equal `target_period_end`
- CompanyFacts selector fails closed when target period is missing

Rerun range:
- `2022Q3-2026Q2`, chained from `2022Q2 fix2` prior
- run roots use `walkforward_pit_v2_periodfix_20260519`
- LLM mode used `post-file` with the already accepted per-quarter `post_llm_scores.csv`; no new LLM extraction was run

Command pattern:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m cli.main fundamental-run-quarter \
  --mode broad-master-final \
  --date <as_of> \
  --quarter <quarter> \
  --master-universe tradingagents/research/fundamental/data/master_fundamental_universe_start_2021Q4.json \
  --prior-final-scores <prior_fixed_quarter_final_scores.csv> \
  --llm-mode post-file \
  --post-llm <prior_accepted_post_llm_scores.csv> \
  --allow-missing-handoff \
  --emit-complete-panel \
  --output-root tradingagents/research/fundamental/runs/<as_of>/<quarter>/walkforward_pit_v2_periodfix_20260519 \
  --complete-panel-output-root tradingagents/research/fundamental/runs/<as_of>/<quarter>/walkforward_pit_v2_periodfix_20260519/complete_panel \
  --format json
```

Focused verification:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_companyfacts_pit_selector.py tests/test_fundamental_pit_master_reconciliation_gate.py -q
```
