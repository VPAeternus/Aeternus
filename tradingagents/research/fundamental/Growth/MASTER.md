# Growth Framework Master Summary

## Goal
Build a filing-only growth framework that can identify early `10x` / `100x` candidates before the market fully prices the wave.

This framework is **not** trying to find the best current business.
It is trying to find:
- emerging wave riders
- asymmetric upside
- messy but fundable scalers
- companies whose SEC filings reveal a credible path to massive future scale

Use only:
- SEC filing text
- filing-disclosed numbers
- filing-to-filing deltas
- derived metrics from filings

Do not use:
- news
- web search
- external commentary
- post-filing evidence

---

## Core insight from the BE vs NVDA test
The old framework was too biased toward:
- established quality
- cleaner current conversion
- already-proven incumbents

That caused it to prefer `NVDA` too long, even though `BE` produced much better percentage upside during the key early phase.

The new framework must allow:
- early wave exposure to matter more
- asymmetric upside to matter more
- wave torque / operating leverage to matter when a company is already in the bottleneck layer
- incumbent saturation to be penalized more harshly only when the upside is already obvious
- `messy but fundable and scaling` to beat `excellent but already known`

---

## Two formula-based modes

### 1) Venture Mode
Purpose:
- catch the move early
- tolerate messier filings
- accept more false positives
- prioritize asymmetry and wave attachment

### 2) Public-Growth Mode
Purpose:
- require stronger proof before flipping
- still growth-first, but less tolerant of fragility
- enter later, with fewer weak flips

These are separate modes, not one blended discretionary model.

---

## Final formulas

### Venture Mode
`Venture Score = Wave Exposure + Asymmetric Upside + Fundable Scaling + Filing Delta + Wave Torque / Operating Leverage + Incumbent Saturation Penalty + False-Promise Penalty`

#### Venture Mode is generic, not BE-specific
It has two valid internal win paths:
1. `Expansion Bridge`
   - smaller-base company
   - explicit new bridge to scale
   - financing / policy / partner / deployment scaffold matters
2. `Torque Bottleneck`
   - already-real supplier in a bottleneck layer
   - AI / cloud demand can create sharp utilization, mix, margin, or earnings torque
   - does not need a dramatic new financing bridge to qualify

#### Venture early-flip rules
A company can beat a mature incumbent early through either path:

**Expansion Bridge**
- `Wave Exposure >= 4`
- `Asymmetric Upside >= 4`
- `Fundable Scaling >= 3`

**Torque Bottleneck**
- `Wave Exposure >= 4`
- `Wave Torque / Operating Leverage >= 2`
- `Filing Delta >= 2`

### Public-Growth Mode
`Public-Growth Score = Wave Exposure + Commercial Proof + Survivability Quality + Filing Delta + Incumbent Saturation Penalty + Fragility Penalty`

#### Public-Growth tie-break rule
If scores tie:
1. if a company has:
   - `Commercial Proof >= 3`
   - `Survivability Quality >= 4`
   then prefer the company with the lower `Incumbent Saturation Penalty`
2. otherwise prefer:
   - higher `Commercial Proof`
   - then higher `Survivability Quality`
   - then lower `Fragility Penalty`

---

## What flipped the framework in July vs October

### July 2025 — BE venture flip
Relevant filing:
- `BE 2025-07-31 10-Q`

Why venture mode flipped:
- explicit `AI data center` wave attachment
- secure-through-`2028` deployment runway
- clear infrastructure bottleneck relevance
- much larger asymmetry than `NVDA`
- good-enough bridge to survive and participate

Interpretation:
- July is the **early-wave capture signal**
- this is where the aggressive mode should enter

### October 2025 — BE public-growth confirmation
Relevant filing:
- `BE 2025-10-28 10-Q`

What October added:
- stronger partner scaffolding: `Brookfield`, `SK ecoplant`
- restored `30%` tax-credit runway through `2033`
- `FEOC` comfort
- improved survivability optics
- better bridge-to-scale evidence

Interpretation:
- October is the **confirmation signal**
- this is where the stricter mode should flip

---

## Exact lessons from the BE vs NVDA walkforward

### Venture Mode lesson
Ask:
- Is this company clearly on the wave?
- Is the upside much larger because the base is still small?
- Or is it an underappreciated bottleneck supplier with real operating torque if the wave accelerates?
- Is it fundable enough to survive and scale, or already well-positioned enough to convert demand quickly?

If yes, let it beat the mature incumbent early.

### Public-Growth Mode lesson
Ask:
- Has the company now shown enough proof that the scaling path is real?
- Is survivability quality now strong enough?
- Is the challenger now real enough that saturation should beat incumbent proof in a tie?

If yes, allow confirmation-stage flip.

---

## Key files
- Rule card:
  - `Growth/growth_framework_rule_card.md`
- Mechanical template:
  - `Growth/growth_scoring_template.md`
- Worked example — July divergence:
  - `Growth/growth_scored_example_step4.md`
- Worked example — October confirmation:
  - `Growth/growth_scored_example_step6.md`
- Walkforward log:
  - `Growth/nvda_be_walkforward.md`

---

## Return
Use only the BE move from the venture-mode first buy.

- Venture-mode first BE buy trigger: `BE 2025-07-31 10-Q`
- Entry date: `2025-08-01 open`
- Start price: `32.74`
- Current mark: `2026-04-22 close`
- End price: `229.75`
- Total return: `197.01`
- Total % return: `601.74%`

---

## Comparability guardrail
Before any growth comparison is allowed to run:
1. auto-repair missing packet sections from cached SEC HTML
2. if repair still leaves any company missing required sections, block the comparison
3. do **not** score degraded packets against richer packets

Required sections:
- `10-Q`: `item_1a_risk_factors`, `item_2_mda`
- `10-K`: `item_1_business`, `item_1a_risk_factors`, `item_7_mda`

Guardrail command:
- `python Growth/check_growth_comparability.py <packet_a.json> <packet_b.json> ...`

## Practical next workflow
For any future company pair or test case:
1. collect current filing and prior filing for both companies
2. run `python Growth/check_growth_comparability.py ...`
3. score both with `Venture Mode`
4. explicitly note whether the winner qualified through `Expansion Bridge` or `Torque Bottleneck`
5. score both with `Public-Growth Mode`
6. record exact filing evidence for every score
7. compare which mode flips first
8. measure whether early flip produced better percentage return
9. refine only the formula rules, not freeform LLM judgment

---

## Final operating principle
This framework should not ask:
- `Who is the best company today?`

It should ask:
- `Which company's SEC filing shows the most credible path to ride the wave from here into something much bigger than the market currently assumes?`
