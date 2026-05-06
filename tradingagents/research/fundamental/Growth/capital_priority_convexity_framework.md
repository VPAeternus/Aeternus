# Capital Priority / Convexity Framework

Goal:
Use the earnings + venture combo framework to choose the best use of limited capital, not just identify good companies.

Core problem:
`combo_bucket` can find strong signals, but limited capital needs rank ordering. If multiple companies benefit from the same wave, prefer the ticker where the wave can move the whole company the most.

## Core Idea

Same signal quality, prefer the company with more return convexity.

```text
signal_convexity_score =
  combo_signal_strength
  x business_torque
  x valuation_sensitivity
  x beneficiary_purity
  / market_cap_scale
```

Plain English:
Find companies where one new demand wave can change the whole company trajectory, not merely add growth to an already huge base.

Example:
- `NVDA`: massive base, obvious winner, already scaled.
- `BE`: smaller base, possible data-center power beneficiary, wave may change entire company.

The same AI/data-center wave can create very different stock torque depending on company scale, purity, backlog, margins, and obviousness.

## New Columns

```text
market_cap_bucket
revenue_base_bucket
wave_revenue_purity
backlog_to_revenue_ratio
guide_step_up_pct
operating_leverage_inflection
beneficiary_position
signal_convexity_score
capital_priority_score
capital_priority_bucket
```

## Key Concepts

### market_cap_scale

Smaller market cap can be more convex.

Important:
Small alone is not bullish. Small plus proof is bullish.

High score requires:
- smaller market cap
- real demand evidence
- real revenue/backlog/guidance proof
- manageable execution risk

### wave_revenue_purity

Measures how much of the company is tied to the relevant wave.

Question:
If the wave accelerates, how much of this company benefits?

Examples:
- Pure beneficiary: most revenue/backlog tied to wave.
- Mixed beneficiary: important segment benefits, but company has many unrelated drivers.
- Low purity: wave mention exists, but little revenue linkage.

### backlog_to_revenue_ratio

Measures future demand relative to current size.

```text
backlog_to_revenue_ratio = backlog / trailing annual revenue
```

Why it matters:
Backlog that dwarfs revenue can imply multi-year conversion potential.

This is especially useful for smaller industrial / infrastructure names where earnings may lag orders.

### incremental_wave_materiality

Question:
If this wave continues, does it change the entire company or only one segment?

High score:
- wave demand can materially change company revenue, margins, cash flow, or backlog.

Low score:
- wave demand is real but company already huge, diversified, and fully recognized.

### obviousness_discount

Already-consensus winners get lower convexity.

This is not bearish. It just says the easy return may already be priced.

Examples:
- NVDA can still compound.
- Smaller derivative beneficiaries may have more discovery upside.

## Derivative Beneficiary Score

Most important addition:

```text
derivative_beneficiary_score =
  wave_dependency
+ bottleneck_position
+ revenue_base_smallness
+ backlog_materiality
+ margin_inflection
- financing_execution_risk
- obviousness
```

Question:
Who gets more stock torque from the same wave: the leader or the bottleneck supplier?

This is the direct NVDA vs BE problem.

## Capital Priority Score

```text
capital_priority_score =
  combo_score
+ narrative_adjusted_earnings_score
+ venture_score
+ backlog_to_revenue_score
+ wave_purity_score
+ small_base_convexity_score
+ derivative_beneficiary_score
- obvious_incumbent_penalty
- balance_sheet_risk_penalty
- liquidity_risk_penalty
```

## Buckets

```text
A1 = scarce-capital buy candidate
A2 = good, but not best
B = watchlist
C = avoid / wait
```

## Interpretation

`combo_bucket` answers:
Is this a good signal?

`capital_priority_bucket` answers:
Is this the best place to deploy scarce capital?

## Practical Rule

Prefer:

```text
strong combo signal
+ high venture durability
+ high wave purity
+ high backlog/revenue materiality
+ small-to-mid market cap
+ improving margins or operating leverage
- low warning / financing / liquidity risk
```

Avoid:

```text
good story
+ huge market cap
+ low incremental materiality
+ no backlog proof
+ story already obvious
+ high execution risk
```

## Next Implementation Step

Add `capital_priority_score` to the earnings combo CSV using:

- market cap
- trailing revenue
- backlog, if disclosed
- combo bucket
- venture score
- warning penalties
- derivative beneficiary logic

Then rank tickers by `capital_priority_score`, not raw earnings or venture score.

