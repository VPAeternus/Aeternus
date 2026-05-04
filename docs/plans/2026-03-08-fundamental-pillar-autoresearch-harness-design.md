# Fundamental Pillar Autoresearch Harness Design

## Goal

Build a point-in-time, filing-driven research harness that can optimize the Aeternus fundamental pillar against real forward returns using structured SEC data without introducing LLM cost, timing ambiguity, or data leakage into the inner loop.

This is not a live pillar replacement in v1. It is a sidecar truth engine that produces reproducible evidence about what fundamental signals actually work.

## Why This Matters

The current live fundamental pillar is a mix of:
- live data acquisition
- deterministic metric synthesis
- analyst/reviewer interpretation

That is useful for end-to-end analysis, but it is not the right shape for fast scientific optimization.

If we want the fundamental pillar to become a genuine edge, we need:
- point-in-time inputs
- deterministic scoring
- objective evaluation
- repeatable experiments

That is the role of this harness.

## Core First-Principles Decision

The correct unit is not:
- ticker x day

The correct unit is:
- ticker x filing/event snapshot

Fundamentals do not update meaningfully every day. The information set changes when filings arrive, are accepted by the SEC, and become tradable to the market. The harness should therefore anchor every observation to an effective market date derived from the filing timestamp.

## Recommended Scope

### Phase 1 Scope

Build a read-only, event-driven harness for:
- `10-Q`
- `10-K`
- optionally selected structured filing-derived events later, but not in v1

Time coverage:
- start at `2009-01-01`

Universe:
- stable liquid large-cap universe first
- not full US equities in v1

Outputs:
- point-in-time filing dataset
- deterministic score
- forward-return evaluation
- experiment artifacts

Excluded from v1:
- no LLM in the scoring loop
- no pre-2009 legacy parsing
- no live graph integration
- no automatic promotion into portfolio decisions

## Data Model

The canonical row should be a filing-effective snapshot with fields like:

- `ticker`
- `cik`
- `filing_type`
- `period_end`
- `filed_at`
- `accepted_at`
- `effective_market_date`
- `fiscal_period`
- `fiscal_year`
- `sector`
- normalized fundamentals
- price context at effective date
- benchmark context
- forward returns

### Fundamental Feature Families

#### Growth
- revenue growth YoY
- earnings growth YoY
- FCF growth YoY

#### Quality
- gross margin
- operating margin
- margin expansion/contraction
- ROA / ROE / ROIC where feasible
- accrual proxy

#### Balance Sheet / Health
- debt/equity
- current ratio
- liquidity proxies
- leverage improvement/deterioration

#### Capital Discipline
- share count dilution / buyback trend
- capex context
- FCF quality

#### Valuation Context
- EV/sales
- earnings yield / P/E proxy
- FCF yield

### Data Quality Fields

Every row should also carry:
- `data_coverage_score`
- `missing_fields`
- `source_flags`
- `restatement_suspect`

These fields are required to prevent sparse or suspect accounting data from silently masquerading as clean input.

## Time and Trading Semantics

This harness must be point-in-time correct.

### Effective Date Rule

`effective_market_date` should be the first tradable session after the filing became knowable to the market.

Implications:
- filing accepted during market hours: same-day close anchoring may be acceptable only if explicitly modeled
- filing accepted after market close: next trading day is the anchor

To keep the system conservative and consistent, v1 should default to next-tradable-session semantics.

### Forward Return Horizons

Recommended horizons:
- `20d`
- `60d`
- `120d`
- `252d`

Rationale:
- `20d` captures faster repricing
- `60d` is the recommended primary horizon for optimization
- `120d` and `252d` capture slower fundamental absorption

## Scoring Architecture

The scoring layer should be one deterministic module that the autoresearch loop can mutate safely.

Expected outputs:
- `fundamental_score`
- optional sub-scores:
  - `growth`
  - `quality`
  - `health`
  - `capital_discipline`
  - `valuation`

### Initial Optimization Contract

Primary objective:
- sector-neutral rank IC at `60d`

Secondary diagnostics:
- rank IC at `20d`, `120d`, `252d`
- quintile spread
- top-decile hit rate
- stability by era
- stability by sector
- coverage retention

### Why Sector-Neutral 60d

This is the best first optimization target because:
- it is less noisy than `20d`
- it is much faster than waiting for `252d`
- it reduces “the whole sector moved” contamination
- it fits the filing/event nature of the signal

## Research Loop Design

The Karpathy-style loop should be adapted like this:

1. fixed prepared dataset
2. one mutable score module
3. one evaluator
4. one experiment artifact
5. keep/discard based on metric improvement and robustness

The harness should optimize scoring logic, not re-run large ingestion each experiment.

## Aeternus Integration Strategy

### v1

Research sidecar only:
- lives outside the live graph
- produces evidence artifacts
- compares against naive baselines
- compares against current fundamental pillar where feasible

### v2

If the harness proves useful:
- use as a benchmark truth engine for current pillar
- use as a feature source for dealflow / deep research
- possibly replace portions of the current deterministic fundamental scoring layer

### v3

Only after the deterministic core is proven:
- consider LLM residual analysis for qualitative deltas not captured by structured data

## Major Risks

### 1. Point-in-Time Leakage

The single biggest risk.

Examples:
- using revised data as if it were known originally
- using current index constituents as historical universe
- incorrect filing-to-trading alignment

### 2. Coverage Illusion

A formula can “win” by scoring fewer names.

Guardrail:
- coverage reporting must be part of every evaluation

### 3. Sector and Era Fragility

Signals may work only in one sector or one macro era.

Guardrail:
- every experiment should report by sector and by era

### 4. Harness Becoming A Side Project

This must remain tied to the Aeternus operating system thesis.

The harness should improve the fundamental pillar through verified learning, not become an isolated quant toy.

## Shipping Standard for v1

The first successful release should deliver:
- one reproducible point-in-time dataset
- one deterministic scoring baseline
- one evaluator with robust diagnostics
- one experiment artifact contract
- one clear go/no-go answer on whether the harness is predictive enough to continue

## Recommendation

Build the harness now, but keep it:
- event-driven
- deterministic
- point-in-time
- sidecar-only in v1

This is one of the highest-leverage research systems available to Aeternus because it turns the fundamental pillar from a narrative-heavy component into an experimentally improvable scoring engine.
