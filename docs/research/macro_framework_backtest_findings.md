# Macro Framework Backtest Findings

Source of truth for the Aeternus macro framework backtest research project. Append new findings here instead of scattering notes across chat/memory.

---

## 2026-04-27 — Step 1: Market-Data-Only Regime Backtest

### Scope

Tested the market-data-only macro regime engine.

Included:

- SPY trend / moving averages
- VIX level
- cross-asset ETFs already used by the macro engine
- weekly snapshots
- forward return horizons: `5, 10, 20, 30, 60, 90` trading days

Excluded:

- FRED macro data
- CPI/jobs/rates releases
- Grok macro cache
- LLM Macro Reviewer
- point-in-time vintage macro series

Command:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 scripts/backtest_macro_framework.py \
  --start 2018-01-01 \
  --end 2026-04-27 \
  --frequency W-FRI \
  --output-dir eval_results/macro_backtest/step1_research
```

Artifacts:

```text
eval_results/macro_backtest/step1_research/
  macro_snapshots_labeled.csv
  regime_performance.csv
  sector_performance.csv
  manifest.json
```

Important caveat:

This is **not a production-grade point-in-time macro backtest**. It is research-only. Since no FRED data was used, the signal/features are market-data-only and avoid macro-release lookahead, but labels are forward returns by design.

---

## Dataset Summary

Snapshots:

```text
434 weekly snapshots
2018-01-05 → 2026-04-24
```

Regime counts:

```text
BULL:      143
NEUTRAL:   103
EUPHORIA:   85
BEAR:       78
RISK_OFF:   10
VOL_SHOCK:   8
HIGH_VOL:    7
```

SPY forward label counts:

```text
5d:  432
10d: 431
20d: 429
30d: 427
60d: 421
90d: 414
```

Baseline SPY average forward returns:

```text
5d:   +0.29%
10d:  +0.58%
20d:  +1.15%
30d:  +1.74%
60d:  +3.41%
90d:  +5.20%
```

Interpretation: the market generally went up over the tested period. Regime usefulness should be judged against this baseline, not just against zero.

---

## Main Finding

The current macro regime classifier is not behaving like:

```text
BULL = buy
BEAR = sell
```

It is behaving more like:

```text
panic = potential rebound setup
euphoria = lower forward reward / chase risk
```

The scary regimes had the best forward returns. The comfortable regimes had weaker forward returns.

---

## SPY Forward Returns by Regime

### 20-Day Forward Returns

Baseline SPY 20d return: `+1.15%`

```text
VOL_SHOCK: +7.46%
HIGH_VOL:  +4.77%
RISK_OFF:  +2.22%
BEAR:      +2.02%
NEUTRAL:   +0.85%
BULL:      +0.73%
EUPHORIA:  +0.39%
```

Plain English:

- `VOL_SHOCK`, `HIGH_VOL`, `RISK_OFF`, and `BEAR` often occurred after the market had already sold off.
- A lot of bad news was already priced in.
- Forward returns often reflected rebound/mean reversion.

### 60-Day Forward Returns

Baseline SPY 60d return: `+3.41%`

```text
VOL_SHOCK: +15.42%
HIGH_VOL:  +8.04%
BEAR:      +5.01%
RISK_OFF:  +4.93%
NEUTRAL:   +3.70%
BULL:      +2.92%
EUPHORIA:  +0.78%
```

### 90-Day Forward Returns

Baseline SPY 90d return: `+5.20%`

```text
VOL_SHOCK: +18.06%
HIGH_VOL:  +10.67%
RISK_OFF:  +7.88%
BEAR:      +6.66%
NEUTRAL:   +5.61%
BULL:      +4.69%
EUPHORIA:  +2.20%
```

---

## Why “Bearish” Labels Were Not Bearish Forward

The regime labels describe **current condition**, not necessarily future direction.

Example:

```text
BEAR / RISK_OFF / VOL_SHOCK = current pain is already visible
```

By the time these labels fire, the market may already have sold off significantly. Future returns can then be strong because conditions are washed out and rebound-prone.

Examples from the sample:

```text
2020-03-13 VOL_SHOCK → SPY +19.0% next 20d
2020-03-20 VOL_SHOCK → SPY +22.5% next 20d
2025-04-04 VOL_SHOCK → SPY +10.8% next 20d
```

But not always:

```text
2022-08-26 VOL_SHOCK → SPY -9.4% next 20d
```

Conclusion:

```text
Do not read VOL_SHOCK as “sell.”
Read it as “panic/forced-selling context; possible asymmetric rebound, but needs quality/risk filter.”
```

---

## Euphoria Finding

`EUPHORIA` was the weakest major regime.

SPY forward returns:

```text
20d: +0.39% vs baseline +1.15%
60d: +0.78% vs baseline +3.41%
90d: +2.20% vs baseline +5.20%
```

Plain English:

```text
When the market is already extended and calm, future returns are still often positive, but the reward is much weaker.
```

Euphoria is not necessarily a crash signal. It is a chase-risk signal.

Possible operating interpretation:

```text
EUPHORIA = reduce chase tolerance, demand better entry, require stronger catalyst.
```

---

## Bull Regime Finding

`BULL` had positive returns but did not beat baseline.

```text
20d: +0.73% vs baseline +1.15%
60d: +2.92% vs baseline +3.41%
90d: +4.69% vs baseline +5.20%
```

Plain English:

```text
BULL means the market is already healthy. It does not mean future returns are especially attractive.
```

Potential implication:

```text
BULL should be treated as neutral-positive context, not a major alpha boost.
```

---

## Composite Score Finding

Composite score buckets suggested that lower macro scores sometimes had better forward returns.

### 20-Day SPY Return by Composite Bucket

```text
<=40:  +2.97%
41-50: +1.51%
51-60: +0.64%
61-70: +1.01%
```

Plain English:

```text
The current macro score is a current-condition score, not a clean expected-return score.
```

Stressful current conditions can lead to stronger forward returns because of mean reversion.

Potential implication:

```text
Using “higher macro score = better expected return” may be wrong.
```

Better interpretation:

```text
high macro score = comfortable current backdrop
low macro score = stressful backdrop / possible rebound setup
```

---

## Sector Findings

The best 20-day sector/regime combinations were mostly after `VOL_SHOCK`.

Top examples:

```text
VOL_SHOCK + Energy:                 +11.78%
VOL_SHOCK + Consumer Discretionary:  +8.23%
VOL_SHOCK + Technology:              +8.18%
VOL_SHOCK + Healthcare:              +8.17%
VOL_SHOCK + Materials:               +8.02%
```

Plain English:

```text
After panic, almost everything bounced. Cyclicals and high-beta sectors bounced hardest.
```

Weak examples were mostly during `EUPHORIA`:

```text
EUPHORIA + Consumer Discretionary: -0.48%
EUPHORIA + Energy:                 -0.23%
EUPHORIA + Materials:              -0.17%
```

Plain English:

```text
When the market was already stretched/calm, chasing cyclicals looked worse.
```

---

## Operating Interpretation for Aeternus

The macro engine is currently best understood as a **market context / behavior modifier**, not an absolute buy/sell signal.

Suggested interpretation:

### EUPHORIA

```text
- lower chase tolerance
- penalize crowded momentum
- require stronger catalyst
- prefer pullbacks over fresh entries
```

### VOL_SHOCK / HIGH_VOL / RISK_OFF

```text
- flag potential rebound opportunity
- prefer quality names sold off too hard
- do not auto-reject all risk
- use balance-sheet/liquidity filters
```

### BEAR

```text
- mixed signal
- may contain rebound opportunities
- requires extra filter to separate falling knife vs priced-in rebound
```

Possible second filter needed:

```text
BEAR + credit spreads widening = dangerous
BEAR + volatility peaking/stabilizing = rebound candidate
```

### BULL

```text
- neutral-positive context
- not a major alpha signal by itself
```

---

## What Not To Conclude

Do not conclude:

```text
Always buy VOL_SHOCK.
```

Reasons:

- only 8 `VOL_SHOCK` samples
- `HIGH_VOL` has only 7 samples
- results are heavily influenced by crisis rebound periods
- overlapping weekly forward returns inflate apparent sample size
- no transaction costs/slippage
- no FRED/vintage macro data yet

Do conclude:

```text
The current macro signal has contrarian behavior and should not be interpreted as simple risk-on/risk-off expected return.
```

---

## Next Research Questions

1. Is the panic-rebound effect real outside 2020?
2. Does `EUPHORIA` underperform consistently across years?
3. Does `BEAR` work only after deep selloffs?
4. Can credit spreads / HYG-vs-TLT separate dangerous bear markets from rebound bear markets?
5. Should Aeternus invert or reshape part of the macro score for ranking?
6. Should macro become a context modifier rather than a direct score boost/penalty?

Next table to run:

```text
regime performance by year
```

Focus:

```text
VOL_SHOCK/HIGH_VOL outside 2020
EUPHORIA behavior across 2019, 2023, 2024, 2025, 2026
BEAR behavior in 2022 vs other years
```
