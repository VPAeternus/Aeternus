# Session Handoff — 2026-04-24

## Current Goal
Continue hardening and using the deterministic Venture Mode scorer for filing-only growth comparison work.

## What Was Completed
- Built / reviewed `rule engine v2` in:
  - `Growth/venture_mechanical_scorer.py`
- Added deterministic trigger-audit columns to source output:
  - `wave_exposure_audit`
  - `asymmetric_upside_audit`
  - `fundable_scaling_audit`
  - `wave_torque_operating_leverage_audit`
  - `incumbent_saturation_penalty_audit`
  - `false_promise_penalty_audit`
- Added optional extraction mode flag:
  - `--extraction-mode packet|edgartools`
- Added timing fields to source output:
  - `earnings_date`
  - `filing_date`
  - `tradable_date`
- Fixed buy CSV export so:
  - `winner_tradable_date` = row/effective evaluation date
- Ran scorer on full `BE/LITE/NVDA/SNDK` set and regenerated:
  - `Growth/be_lte_nvda_sndk_venture_score_source.csv`
  - `Growth/be_lte_nvda_sndk_venture_buys.csv`
- Added `AAOI` test flow and generated:
  - `Growth/be_lte_nvda_sndk_aaoi_venture_score_source.csv`
  - `Growth/be_lte_nvda_sndk_aaoi_venture_buys.csv`
- Verified `AAOI` cached SEC packets exist and extract correctly.

## Latest Verified Commands
```bash
PYTHONPATH=. python Growth/venture_mechanical_scorer.py --tickers BE,LITE,NVDA,SNDK --source-output Growth/be_lte_nvda_sndk_venture_score_source.csv
PYTHONPATH=. python Growth/build_be_lte_nvda_sndk_venture_buys.py --source Growth/be_lte_nvda_sndk_venture_score_source.csv --output Growth/be_lte_nvda_sndk_venture_buys.csv --tickers BE,LTE,NVDA,SNDK

PYTHONPATH=. python Growth/venture_mechanical_scorer.py --tickers BE,LITE,NVDA,SNDK,AAOI --source-output Growth/be_lte_nvda_sndk_aaoi_venture_score_source.csv
PYTHONPATH=. python Growth/build_be_lte_nvda_sndk_venture_buys.py --source Growth/be_lte_nvda_sndk_aaoi_venture_score_source.csv --output Growth/be_lte_nvda_sndk_aaoi_venture_buys.csv --tickers BE,LTE,NVDA,SNDK,AAOI

python -m py_compile Growth/venture_mechanical_scorer.py Growth/build_be_lte_nvda_sndk_venture_buys.py
PYTHONPATH=. pytest -q tests/test_venture_mechanical_scorer.py
```

## Current Test Status
- `PYTHONPATH=. pytest -q tests/test_venture_mechanical_scorer.py`
  - passing (`7 passed` at last run)
- `python -m py_compile ...`
  - passing

## Current Key Files
- Scorer:
  - `Growth/venture_mechanical_scorer.py`
- Buy CSV builder:
  - `Growth/build_be_lte_nvda_sndk_venture_buys.py`
- Trigger rubric:
  - `Growth/venture_mechanical_triggers.md`
- Tests:
  - `tests/test_venture_mechanical_scorer.py`
- Main outputs:
  - `Growth/be_lte_nvda_sndk_venture_score_source.csv`
  - `Growth/be_lte_nvda_sndk_venture_buys.csv`
  - `Growth/be_lte_nvda_sndk_aaoi_venture_score_source.csv`
  - `Growth/be_lte_nvda_sndk_aaoi_venture_buys.csv`

## Important Current Caveats
- `quarter` in generated CSVs is really the evaluation/event date, not a fiscal quarter label.
- `tradable_date` currently skips weekends only, not market holidays.
- `source_mode=edgartools` path exists, but fallback provenance should be reviewed if edgartools extraction partially fails.
- Torque numeric detection still uses broad percentage/numeric regex and may overfire on unrelated percentages.

## Active Environment / Tooling Issue
Pi extension load problem observed:
- file:
  - `/opt/homebrew/lib/node_modules/pi-web-access/index.ts`
- error:
  - `Failed to load extension: ENOENT: no such file or directory, open '/opt/homebrew/lib/node_modules/@mariozechner/pi-coding-agent/node_modules/@sinclair/typebox/build/cjs/index.js'`

### Diagnosis
- `@mariozechner/pi-coding-agent` currently has:
  - `node_modules/typebox`
- but does **not** have:
  - `node_modules/@sinclair/typebox/build/cjs/index.js`
- old `@sinclair/typebox` does exist elsewhere, e.g.:
  - `/opt/homebrew/lib/node_modules/@mariozechner/pi/node_modules/@sinclair/typebox/build/cjs/index.js`

### Suggested Workaround
```bash
mkdir -p /opt/homebrew/lib/node_modules/@mariozechner/pi-coding-agent/node_modules/@sinclair
ln -s /opt/homebrew/lib/node_modules/@mariozechner/pi/node_modules/@sinclair/typebox \
  /opt/homebrew/lib/node_modules/@mariozechner/pi-coding-agent/node_modules/@sinclair/typebox
```
Then restart Pi.

## Best Next Steps After Restart
1. Fix / verify the `typebox` extension issue.
2. Re-open this handoff file.
3. Resume from deterministic scorer work.
4. Likely next improvement tasks:
   - make `tradable_date` market-holiday aware
   - tighten numeric torque detection
   - make fallback `source_mode` provenance truthful
   - consider renaming `quarter` to `evaluation_date`

## Resume Prompt
Use this after restart:

```text
Resume from Growth/session_handoff_2026-04-24.md.
Primary context: deterministic Venture Mode scorer in Growth/venture_mechanical_scorer.py.
Latest outputs already regenerated for BE/LTE/NVDA/SNDK and BE/LTE/NVDA/SNDK/AAOI.
First help fix or verify the pi-web-access typebox extension issue if still present, then continue scorer hardening.
```
