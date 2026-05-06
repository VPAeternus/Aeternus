# Growth Scoring Template

Use this template to score any filing pair mechanically.

## Inputs
- Company A:
- Filing date:
- Form:
- Prior filing date:
- Company B:
- Filing date:
- Form:
- Prior filing date:

## Comparability gate
Run before scoring:
- `python Growth/check_growth_comparability.py <packet_a.json> <packet_b.json> ...`

Required sections:
- `10-Q`: `item_1a_risk_factors`, `item_2_mda`
- `10-K`: `item_1_business`, `item_1a_risk_factors`, `item_7_mda`

If the guardrail fails:
- stop
- repair extraction
- do not score until packet coverage is comparable

---

## Venture Mode Scoring Sheet

### Formula
`Venture Score = Wave Exposure + Asymmetric Upside + Fundable Scaling + Filing Delta + Wave Torque / Operating Leverage + Incumbent Saturation Penalty + False-Promise Penalty`

### Company A
| Factor | Score | Evidence from filing only |
|---|---:|---|
| Wave Exposure (0 to 5) |  |  |
| Asymmetric Upside (0 to 5) |  |  |
| Fundable Scaling (0 to 5) |  |  |
| Filing Delta (0 to 5) |  |  |
| Wave Torque / Operating Leverage (0 to 3) |  |  |
| Incumbent Saturation Penalty (0 to -5) |  |  |
| False-Promise Penalty (0 to -5) |  |  |
| **Total Venture Score** |  |  |

### Company B
| Factor | Score | Evidence from filing only |
|---|---:|---|
| Wave Exposure (0 to 5) |  |  |
| Asymmetric Upside (0 to 5) |  |  |
| Fundable Scaling (0 to 5) |  |  |
| Filing Delta (0 to 5) |  |  |
| Wave Torque / Operating Leverage (0 to 3) |  |  |
| Incumbent Saturation Penalty (0 to -5) |  |  |
| False-Promise Penalty (0 to -5) |  |  |
| **Total Venture Score** |  |  |

### Venture Mode Early-Flip Override
A company can beat a mature incumbent early through either path:

**Expansion Bridge**
- `Wave Exposure >= 4`
- `Asymmetric Upside >= 4`
- `Fundable Scaling >= 3`

**Torque Bottleneck**
- `Wave Exposure >= 4`
- `Wave Torque / Operating Leverage >= 2`
- `Filing Delta >= 2`

### Venture Mode Decision
- Higher score wins unless evidence is missing.
- If scores are tied, prefer the company with:
  1. higher `Wave Exposure`
  2. then higher `Asymmetric Upside`
  3. then higher `Wave Torque / Operating Leverage`
  4. then lower saturation penalty

---

## Public-Growth Mode Scoring Sheet

### Formula
`Public-Growth Score = Wave Exposure + Commercial Proof + Survivability Quality + Filing Delta + Incumbent Saturation Penalty + Fragility Penalty`

### Company A
| Factor | Score | Evidence from filing only |
|---|---:|---|
| Wave Exposure (0 to 5) |  |  |
| Commercial Proof (0 to 5) |  |  |
| Survivability Quality (0 to 5) |  |  |
| Filing Delta (0 to 5) |  |  |
| Incumbent Saturation Penalty (0 to -5) |  |  |
| Fragility Penalty (0 to -5) |  |  |
| **Total Public-Growth Score** |  |  |

### Company B
| Factor | Score | Evidence from filing only |
|---|---:|---|
| Wave Exposure (0 to 5) |  |  |
| Commercial Proof (0 to 5) |  |  |
| Survivability Quality (0 to 5) |  |  |
| Filing Delta (0 to 5) |  |  |
| Incumbent Saturation Penalty (0 to -5) |  |  |
| Fragility Penalty (0 to -5) |  |  |
| **Total Public-Growth Score** |  |  |

### Public-Growth Mode Decision
- Higher score wins.
- No early-flip override.
- If scores are tied:
  1. if a company has `Commercial Proof >= 3` and `Survivability Quality >= 4`, prefer the company with the lower `Incumbent Saturation Penalty`
  2. otherwise prefer the company with:
     - higher `Commercial Proof`
     - then higher `Survivability Quality`
     - then lower fragility penalty

---

## Mechanical Evidence Checklist

### Wave Exposure evidence
- explicit AI / data-center / power bottleneck linkage
- repeated mention of the wave, not one throwaway line
- operational relevance to the wave

### Asymmetric Upside evidence
- small enough base to be transformed by the wave
- category expansion path is visible in filing language
- company is not already the obvious winner

### Wave Torque / Operating Leverage evidence
- bottleneck supplier or enabling layer already in the deployment stack
- AI / cloud demand already improving the business
- margin / mix / utilization recovery can scale quickly with demand
- installed commercial or manufacturing position can convert volume rapidly

### Fundable Scaling / Survivability Quality evidence
- partnerships
- financing access
- liquidity runway
- deployment runway
- policy runway
- manufacturing / supply support

### Commercial Proof evidence
- booked deployments
- realized conversion
- customer adoption proof
- monetization already visible in the filing

### Delta evidence
- stronger than prior filing
- newly disclosed partner / customer / deployment / policy support
- material shift from aspiration to execution

### Penalty evidence
- already-known dominance
- upside mostly obvious continuation
- financing dependence
- delayed bookings
- policy fragility
- story without bridge
- note: established company status by itself is not enough to trigger a harsh saturation penalty

---

## Decision Output Block

- Venture Mode winner:
- Venture Mode score:
- Public-Growth Mode winner:
- Public-Growth Mode score:
- Final interpretation:
  - if both agree:
  - if they differ:
- Filing signals that mattered most:
- What would need to improve in the weaker filing to flip next time:
