# autoresearch — scoring IC optimization

Autonomous agent loop for optimizing the Aeternus scoring engine.
The agent modifies `score.py`, measures Spearman rank IC against 100 weeks
of historical forward returns, keeps improvements, discards regressions.

## Setup

To set up a new experiment, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar7`). The branch `autoresearch/<tag>` must not already exist — this is a fresh run.
2. **Create the branch**: `git checkout -b autoresearch/<tag>` from current branch.
3. **Read the in-scope files**:
   - `autoresearch/prepare.py` — fixed eval harness, data download, IC computation. Do not modify.
   - `autoresearch/score.py` — the file you modify. Scoring weights, formulas, transforms.
4. **Verify data exists**: Run `python autoresearch/prepare.py` to download and cache data. If the cache already exists, this is instant.
5. **Initialize results.tsv**: Create `autoresearch/results.tsv` with header row and baseline entry. Run `python autoresearch/score.py > autoresearch/run.log 2>&1` to get the baseline mean_ic_20d.
6. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experimentation.

## Experimentation

Each experiment takes ~30-60 seconds (no GPU needed — pure math against cached data).
You launch it as: `python autoresearch/score.py > autoresearch/run.log 2>&1`

**What you CAN do:**
- Modify `autoresearch/score.py` — this is the only file you edit. Everything is fair game: weights, nonlinear transforms, interaction terms, entirely new scoring functions, momentum_score vs core_score vs asymmetry_score as the output.

**What you CANNOT do:**
- Modify `autoresearch/prepare.py`. It is read-only. It contains the fixed evaluation, data download, signal computation, and caching.
- Add dependencies. Only numpy, pandas, scipy, and the Python stdlib.
- Modify the evaluation harness. The `evaluate()` function in `prepare.py` is the ground truth metric.

**The goal is simple: get the highest mean_ic_20d.** Higher IC = better stock ranking = more alpha. The 20-day forward return horizon is our holding period.

**Simplicity criterion**: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Removing something and getting equal or better results is a simplification win. A 0.001 IC improvement that adds 20 lines of hacky code? Probably not. A 0.001 IC improvement from deleting code? Definitely keep.

## Output format

Once the script finishes it prints:

```
---
mean_ic_5d:          0.0750
mean_ic_20d:         0.0920
t_stat_5d:           2.93
t_stat_20d:          3.51
hit_rate_5d:         0.650
hit_rate_20d:        0.680
n_snapshots:         100
n_tickers_avg:       95
```

Extract the key metric: `grep "^mean_ic_20d:" autoresearch/run.log`

## Logging results

When an experiment is done, log it to `autoresearch/results.tsv` (tab-separated).

The TSV has a header row and 5 columns:

```
commit	mean_ic_20d	mean_ic_5d	status	description
```

1. git commit hash (short, 7 chars)
2. mean_ic_20d achieved (e.g. 0.0920)
3. mean_ic_5d achieved (e.g. 0.0750)
4. status: `keep`, `discard`, or `crash`
5. short text description of what this experiment tried

Example:

```
commit	mean_ic_20d	mean_ic_5d	status	description
a1b2c3d	0.0920	0.0750	keep	baseline production weights
b2c3d4e	0.1050	0.0810	keep	bump price_momentum to 40%
c3d4e5f	0.0800	0.0600	discard	nonlinear sqrt transform
```

## The experiment loop

The experiment runs on a dedicated branch (e.g. `autoresearch/mar7`).

LOOP FOREVER:

1. Look at the git state: the current branch/commit we're on
2. Modify `autoresearch/score.py` with an experimental idea
3. git commit
4. Run: `python autoresearch/score.py > autoresearch/run.log 2>&1`
5. Read results: `grep "^mean_ic_20d:\|^mean_ic_5d:" autoresearch/run.log`
6. If grep is empty, it crashed. Run `tail -n 50 autoresearch/run.log` for the stack trace.
7. Record results in the TSV
8. If mean_ic_20d improved (higher), keep the commit
9. If mean_ic_20d is equal or worse, `git reset --hard HEAD~1` to revert

**Timeout**: Each experiment should take ~60 seconds. If a run exceeds 5 minutes, kill it.

**Crashes**: If it's a typo or import error, fix and re-run. If the idea is fundamentally broken, log "crash" and move on.

**NEVER STOP**: Once the experiment loop has begun, do NOT pause to ask the human if you should continue. The human might be asleep. You are autonomous. If you run out of ideas, think harder — try combining previous near-misses, try more radical approaches, try removing things. The loop runs until the human interrupts you.

## Experiment ideas to try

Starting points (not exhaustive — use your judgment):
- Change weight distribution (what if price_momentum is 50%? 20%?)
- Give breakout_discovery nonzero weight (it has real signal!)
- Nonlinear transforms: `score**2`, `log(score+1)`, sigmoid, thresholds
- Interaction terms: `price_momentum * breakout_discovery`
- Use momentum_score or asymmetry_score formula as output instead of weighted core
- Remove families (simpler = better if IC holds)
- Percentile-rank the composite score across tickers
- Min-family gate: what if MIN_SIGNAL_FAMILIES = 1 or 5?
- Asymmetric weights: penalize low scores more than rewarding high ones
