# autoresearch — fundamental pillar IC optimization

Autonomous agent loop for optimizing the Aeternus fundamental scoring engine.
The agent modifies `score_fundamentals.py`, measures Spearman rank IC against
quarterly filing snapshots with sector-neutral forward returns, keeps
improvements, discards regressions.

## Setup

To set up a new experiment, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `fund-mar8`). The branch `autoresearch-fundamentals/<tag>` must not already exist — this is a fresh run.
2. **Create the branch**: `git checkout -b autoresearch-fundamentals/<tag>` from current branch.
3. **Read the in-scope files**:
   - `autoresearch/prepare_fundamentals.py` — fixed eval harness, EDGAR XBRL data, IC computation. Do not modify.
   - `autoresearch/score_fundamentals.py` — the file you modify. Scoring weights, formulas, transforms.
4. **Verify data exists**: Run `python autoresearch/prepare_fundamentals.py` to download and cache EDGAR data + prices. First run takes ~75 seconds (EDGAR rate-limited at 0.15s/call).
5. **Initialize results_fundamentals.tsv**: Create `autoresearch/results_fundamentals.tsv` with header row and baseline entry. Run `python autoresearch/score_fundamentals.py > autoresearch/run_fundamentals.log 2>&1` to get baseline mean_ic_60d.
6. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experimentation.

## Experimentation

Each experiment takes ~30-60 seconds (no GPU — pure math against cached EDGAR data).
You launch it as: `python autoresearch/score_fundamentals.py > autoresearch/run_fundamentals.log 2>&1`

**What you CAN do:**
- Modify `autoresearch/score_fundamentals.py` — this is the only file you edit. Everything is fair game: weights, nonlinear transforms, interaction terms, entirely new scoring functions, ratio selection.

**What you CANNOT do:**
- Modify `autoresearch/prepare_fundamentals.py`. It is read-only. It contains the fixed evaluation, EDGAR XBRL extraction, ratio computation, and caching.
- Add dependencies. Only numpy, pandas, scipy, and the Python stdlib.
- Modify the evaluation harness. The `evaluate()` function in `prepare_fundamentals.py` is the ground truth metric.

**The goal is simple: get the highest mean_ic_60d.** Higher IC = better stock ranking = more alpha. The 60-day forward return horizon is the primary metric — fundamentals are slower-acting than momentum signals.

**Secondary metric**: mean_ic_252d (annual). Fundamental factors often show stronger signal at longer horizons.

**Simplicity criterion**: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Removing something and getting equal or better results is a simplification win.

## Output format

Once the script finishes it prints:

```
---
mean_ic_20d:         0.0150
mean_ic_60d:         0.0320
mean_ic_120d:        0.0450
mean_ic_252d:        0.0510
t_stat_20d:          1.10
t_stat_60d:          2.20
t_stat_120d:         2.80
t_stat_252d:         3.10
hit_rate_20d:        0.550
hit_rate_60d:        0.600
hit_rate_120d:       0.620
hit_rate_252d:       0.640
n_snapshots:         55
n_tickers_avg:       320
coverage_pct:        85.0
era_stability:       0.85
```

Extract the key metric: `grep "^mean_ic_60d:" autoresearch/run_fundamentals.log`

## Logging results

When an experiment is done, log it to `autoresearch/results_fundamentals.tsv` (tab-separated).

The TSV has a header row and 5 columns:

```
commit	mean_ic_60d	mean_ic_252d	status	description
```

1. git commit hash (short, 7 chars)
2. mean_ic_60d achieved (e.g. 0.0320)
3. mean_ic_252d achieved (e.g. 0.0510)
4. status: `keep`, `discard`, or `crash`
5. short text description of what this experiment tried

## The experiment loop

The experiment runs on a dedicated branch (e.g. `autoresearch-fundamentals/fund-mar8`).

LOOP FOREVER:

1. Look at the git state: the current branch/commit we're on
2. Modify `autoresearch/score_fundamentals.py` with an experimental idea
3. git commit
4. Run: `python autoresearch/score_fundamentals.py > autoresearch/run_fundamentals.log 2>&1`
5. Read results: `grep "^mean_ic_60d:\|^mean_ic_252d:" autoresearch/run_fundamentals.log`
6. If grep is empty, it crashed. Run `tail -n 50 autoresearch/run_fundamentals.log` for the stack trace.
7. Record results in the TSV
8. If mean_ic_60d improved (higher), keep the commit
9. If mean_ic_60d is equal or worse, `git reset --hard HEAD~1` to revert

**Timeout**: Each experiment should take ~60 seconds. If a run exceeds 5 minutes, kill it.

**Crashes**: If it's a typo or import error, fix and re-run. If the idea is fundamentally broken, log "crash" and move on.

**NEVER STOP**: Once the experiment loop has begun, do NOT pause to ask the human if you should continue. The human might be asleep. You are autonomous. If you run out of ideas, think harder.

## Experiment ideas to try

Starting points (not exhaustive — use your judgment):

### Weight redistribution
- What if earnings_momentum is 25% and revenue_growth is 5%?
- What if roe is 25% and fcf_yield is 25%?
- Zero out weak factors — do 4-5 factors beat 8?

### Nonlinear transforms
- `score**2` (reward extremes)
- `log(1 + score)` (compress extremes)
- Winsorize at 5th/95th percentile before ranking
- Sigmoid transform: `1 / (1 + exp(-5*(x-0.5)))`

### Interaction terms
- `revenue_growth × margin_expansion` (profitable growth)
- `roe × (1 - accrual_ratio)` (quality-adjusted returns)
- `fcf_yield × earnings_momentum` (cheap + accelerating)
- `earnings_momentum × (1 - dilution)` (growth without dilution)

### Composite factors
- Quality composite: `0.4*roe + 0.3*(1-accrual) + 0.3*(1-d/e)`
- Growth composite: `0.5*rev_growth + 0.5*earnings_momentum`
- Value composite: `0.5*fcf_yield + 0.5*net_margin`

### Simplification
- Remove weak factors (if IC stays same with fewer factors, keep simpler)
- Binary scoring: above/below median instead of full percentile
- Threshold effects: score=0 below certain quality floor (e.g. negative ROE)

### Sector-relative normalization
- Rank ratios within-sector before cross-sector ranking
- Different weights per sector group (cyclicals vs defensives)

### Regime conditioning
- Different weights in expansion vs contraction (if mean return > 0 vs < 0)
