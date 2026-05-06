# Growth Framework Rule Card

## Objective
Build a filing-only framework to identify small or mid-cap companies with credible `10x+` potential before the market fully prices the wave.

Use only:
- SEC filing text
- filing-disclosed numbers
- filing-to-filing deltas
- derived metrics computed from filing data

Do not use:
- news
- web research
- external commentary
- post-filing evidence

---

## Two separate formula-driven modes

### 1) Venture Mode
Purpose:
- catch the wave early
- tolerate messier fundamentals
- accept more false positives in exchange for earlier 10x candidates

### 2) Public-Growth Mode
Purpose:
- require stronger proof before flipping
- still growth-first, but less tolerant of fragile scale stories
- enter later with fewer false positives

These are **not** the same model. They are separate stages with separate thresholds.

---

## Venture Mode — formula rule set

### Score components
Main positive factors score `0-5`.
`Wave Torque / Operating Leverage` scores `0-3`.
Each penalty scores `0` to `-5`.

**Venture Score = Wave Exposure + Asymmetric Upside + Fundable Scaling + Filing Delta + Wave Torque / Operating Leverage + Incumbent Saturation Penalty + False-Promise Penalty**

### Two valid Venture win paths
Venture Mode is one generic framework with two valid internal archetypes:

1. **Expansion Bridge**
   - smaller-base company
   - clear new wave attachment
   - needs financing, policy, deployment, or partner scaffolding to scale
   - can still win early if the bridge looks credible enough

2. **Torque Bottleneck**
   - already-real supplier or platform layer
   - directly exposed to a scaling bottleneck inside the wave
   - upside comes from demand acceleration, utilization recovery, mix shift, or margin torque
   - does not need a dramatic new financing bridge to qualify

Important rule:
- these are both valid `venture-foundation wave rider` paths
- do **not** treat Venture Mode as only a `small-base bridge story` framework

### A. Wave Exposure (`0-5`)
Reward explicit proof in the filing that the company is attached to a major new demand wave.

Scoring guide:
- `0` = no clear connection to a major wave
- `1` = vague thematic relevance only
- `2` = mentions relevant market but not central
- `3` = clear market linkage with repeated discussion
- `4` = explicit demand linkage plus operational/deployment relevance
- `5` = filing shows the company is directly in the bottleneck / enabling layer of the wave

Examples of evidence:
- explicit `AI data center` language
- repeated linkage to data-center power / infrastructure need
- customer class expansion into the wave
- demand framed as structural, not one-off

### B. Asymmetric Upside (`0-5`)
Reward situations where the company is still small enough that success in the wave could change the scale of the business.

Scoring guide:
- `0` = already mature / upside mostly known
- `1` = modest upside from current scale
- `2` = some rerating potential, but not category-changing
- `3` = meaningful multi-year expansion path
- `4` = filing implies large category expansion from a relatively small base
- `5` = plausible order-of-magnitude upside if execution works

Examples of evidence:
- small or emerging position in a very large market
- infrastructure/platform role that can scale with the wave
- language suggesting new demand surface rather than just better execution in old business

### C. Fundable Scaling (`0-5`)
Reward companies that look likely to survive and scale long enough to catch the wave, even if messy.

Scoring guide:
- `0` = no visible bridge to survival or scale
- `1` = severe survivability concerns
- `2` = weak but possible bridge
- `3` = good-enough bridge to survive and build
- `4` = strong partner/policy/capital bridge to scale
- `5` = very strong self-funded or heavily scaffolded scale path

Examples of evidence:
- strategic financing / deployment partners
- multi-year deployment runway
- policy support that materially extends viability
- supplier/manufacturing path that can support growth
- improved liquidity optics versus prior filing

Important rule:
- this factor is **good enough**, not perfection
- messy balance sheet is allowed if the filing shows a credible bridge to scale

### D. Filing Delta (`0-5`)
Reward what is newly improved or newly disclosed versus the prior filing.

Scoring guide:
- `0` = no meaningful change
- `1` = slightly better framing only
- `2` = modest new evidence
- `3` = clear improvement in growth path evidence
- `4` = major strengthening of the scale story
- `5` = breakaway filing that changes the interpretation of the company

Examples of evidence:
- new customer class or demand surface explicitly added
- stronger deployment language than prior filing
- new partnerships / financing support / policy runway
- survivability improvements that reduce “story only” risk

### E. Wave Torque / Operating Leverage (`0-3`)
Reward companies already positioned inside the wave where accelerating demand can create sharp earnings, mix, margin, or utilization torque.

Scoring guide:
- `0` = no visible torque setup
- `1` = some operating leverage potential, but weakly evidenced
- `2` = clear torque setup with active wave demand already helping
- `3` = strong bottleneck supplier / installed-position torque with clear filing evidence

Examples of evidence:
- direct role in a bottleneck layer of the wave
- existing product fit into active AI / cloud deployment
- explicit increase in demand from wave customers
- utilization, mix, or margin recovery path as wave demand scales
- commercial / manufacturing position that can convert volume quickly

Rule:
- use this to capture `Torque Bottleneck` winners
- this is not a substitute for Wave Exposure; it is an amplifier when the company is already well-placed in the stack

### F. Incumbent Saturation Penalty (`0` to `-5`)
Penalize companies whose filing mostly confirms already-obvious upside rather than revealing meaningful hidden upside.

Scoring guide:
- `0` = not saturated / still underappreciated
- `-1` = mild continuation already known
- `-2` = moderate continuation already known
- `-3` = strong continuation already known
- `-4` = heavy saturation / upside mostly obvious
- `-5` = fully obvious winner with little hidden upside left

Rule:
- this penalty should be harsh for mega-cap wave leaders and fully obvious continuation stories
- do **not** penalize a company merely for being established
- maturity alone is not saturation
- do not let incumbent excellence dominate a 10x-hunt framework

### G. False-Promise Penalty (`0` to `-5`)
Penalize stories with weak bridge from narrative to survival/scale.

Scoring guide:
- `0` = bridge looks credible
- `-1` = some fragility but still workable
- `-2` = meaningful fragility
- `-3` = major missing pieces
- `-4` = weak survivability / likely story stock
- `-5` = narrative with no credible bridge to scale

Rule:
- only use this to kill **story without bridge**
- do not over-penalize messiness if the company still looks fundable and attached to the wave

### Venture Mode decision threshold
- Prefer company with higher Venture Score
- Early-flip override for **Expansion Bridge** path:
  - if `Wave Exposure >= 4`
  - and `Asymmetric Upside >= 4`
  - and `Fundable Scaling >= 3`
  - then the company can beat a mature incumbent even if current conversion is weaker
- Early-flip override for **Torque Bottleneck** path:
  - if `Wave Exposure >= 4`
  - and `Wave Torque / Operating Leverage >= 2`
  - and `Filing Delta >= 2`
  - then the company can beat a mature incumbent even if it is more established

---

## Public-Growth Mode — formula rule set

### Score components
Each positive factor scores `0-5`.
Each penalty scores `0` to `-5`.

**Public-Growth Score = Wave Exposure + Commercial Proof + Survivability Quality + Filing Delta + Incumbent Saturation Penalty + Fragility Penalty**

### A. Wave Exposure (`0-5`)
Same concept as Venture Mode, but not enough by itself.

### B. Commercial Proof (`0-5`)
Require clearer evidence the company is already converting opportunity into real business progress.

Examples:
- booked deployments
- realized monetization progress
- repeatable customer conversion
- cleaner evidence than just aspiration or positioning

### C. Survivability Quality (`0-5`)
Stricter than Venture Mode.
Requires better confidence in liquidity, financing, booking quality, and scale execution.

### D. Filing Delta (`0-5`)
Same as above.

### E. Incumbent Saturation Penalty (`0` to `-5`)
Same logic, but usually slightly less dominant than in Venture Mode.

### F. Fragility Penalty (`0` to `-5`)
More aggressive than Venture Mode on:
- financing dependence
- delayed bookings
- policy dependence
- weak current proof

### Public-Growth decision threshold
- Prefer company with higher Public-Growth Score
- No early-flip override
- The company must show stronger present-tense proof than Venture Mode requires
- Tie-break rule:
  1. if a company has `Commercial Proof >= 3` and `Survivability Quality >= 4`, prefer the company with the lower `Incumbent Saturation Penalty`
  2. otherwise prefer higher `Commercial Proof`, then higher `Survivability Quality`, then lower `Fragility Penalty`

---

## Why July 2025 BE passed Venture Mode but missed Public-Growth Mode

### July 2025 BE filing signals that passed Venture Mode
- explicit `AI data center` linkage
- secure-through-`2028` deployment runway via safe-harbor language
- clear attachment to a real infrastructure bottleneck
- much greater asymmetry than NVDA
- enough survivability to matter, even if not clean

### What blocked Public-Growth Mode in July
- delayed bookings still visible
- financing dependence still mattered
- policy support was important enough to be a risk
- conversion proof was improving but still not strong enough

### Plain-English difference
- Venture Mode asks:
  - `Is this company clearly on the wave and likely able to survive long enough to benefit?`
- Public-Growth Mode asks:
  - `Has this company already shown enough proof that the scale path is working?`

---

## BE vs NVDA flip map from the fundamental

### Venture Mode
- flips at `BE 2025-07-31 10-Q`

Why:
- wave attachment became explicit
- asymmetry was obvious
- deployment runway looked real enough
- NVDA was increasingly a known winner, not a hidden 10x

### Public-Growth Mode
- flips at `BE 2025-10-28 10-Q`

Why:
- stronger partner scaffolding
- longer policy runway
- better survivability optics
- enough bridge-to-scale evidence to clear a stricter proof bar

---

## Venture Mode archetype guide

### Expansion Bridge archetype
Use when the filing shows:
- small or emerging base
- explicit new wave attachment
- credible partner / policy / financing / deployment bridge
- much larger upside if the bridge works

### Torque Bottleneck archetype
Use when the filing shows:
- direct role in a bottleneck supplier layer
- existing AI / cloud / infrastructure demand already helping the business
- realistic margin / mix / utilization torque if the cycle strengthens
- underappreciated upside despite being established

Plain-English distinction:
- `Expansion Bridge` = the company needs the bridge to reach scale
- `Torque Bottleneck` = the company already sits in the stack and the wave can torque earnings power faster than the market assumes

---

## Operating checklist for future filings

### Hard comparability gate
Before scoring any company set:
1. auto-repair packet coverage from cached SEC HTML
2. if any company is still missing required sections, stop
3. never compare a degraded packet against a richer packet

Required sections:
- `10-Q`: `item_1a_risk_factors`, `item_2_mda`
- `10-K`: `item_1_business`, `item_1a_risk_factors`, `item_7_mda`

Run:
- `python Growth/check_growth_comparability.py <packet_a.json> <packet_b.json> ...`

For each company, answer:
1. Is the filing explicitly tied to a major wave?
2. Is the company small enough that the wave can still transform its scale?
3. Does the filing show a credible bridge to survival and scale?
4. What is new versus the prior filing?
5. Is this a hidden emerging winner or an already-obvious incumbent?
6. Is this messy-but-fundable, or story-without-bridge?

Then score both modes separately.

---

## Practical interpretation
- Use `Venture Mode` when hunting 10x / 100x candidates early
- Use `Public-Growth Mode` when you want stronger validation before acting
- Do not merge them into one fuzzy discretionary judgment
- Keep them as separate formula-based stages
