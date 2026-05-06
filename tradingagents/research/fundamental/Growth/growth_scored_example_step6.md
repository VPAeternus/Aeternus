# Worked Example — NVDA 2025-08-27 vs BE 2025-10-28

## Inputs
- Company A: `NVDA`
- Filing date: `2025-08-27`
- Form: `10-Q`
- Prior filing date: `2025-05-28`
- Company B: `BE`
- Filing date: `2025-10-28`
- Form: `10-Q`
- Prior filing date: `2025-07-31`

---

## Venture Mode Scoring Sheet

### Formula
`Venture Score = Wave Exposure + Asymmetric Upside + Fundable Scaling + Filing Delta + Incumbent Saturation Penalty + False-Promise Penalty`

### Company A — NVDA
| Factor | Score | Evidence from filing only |
|---|---:|---|
| Wave Exposure (0 to 5) | 5 | Filing again ties demand to AI infrastructure and says customer buildout depends on data centers, energy, and capital. |
| Asymmetric Upside (0 to 5) | 1 | NVDA remains the already-known incumbent winner; upside is continuation, not transformation from a small base. |
| Fundable Scaling (0 to 5) | 5 | Plans to increase U.S.-based manufacturing, invest in specialized equipment, and strengthen resiliency and redundancy. |
| Filing Delta (0 to 5) | 2 | Some new domestic-manufacturing detail, but mostly continuation rather than a new hidden upside leg. |
| Incumbent Saturation Penalty (0 to -5) | -5 | Dominant wave leader; upside is increasingly obvious and saturated in a 10x hunt. |
| False-Promise Penalty (0 to -5) | 0 | No bridge problem; business is fully real. |
| **Total Venture Score** | **8** |  |

### Company B — BE
| Factor | Score | Evidence from filing only |
|---|---:|---|
| Wave Exposure (0 to 5) | 4 | Filing again explicitly ties BE to AI data-center demand and on-site power relevance. |
| Asymmetric Upside (0 to 5) | 5 | Still much smaller than NVDA and still capable of business-scale transformation if the data-center power wave expands. |
| Fundable Scaling (0 to 5) | 4 | Brookfield and SK ecoplant partnership scaffolding, secure-through-2028 deployment volume, restored 30% tax credit through 2033, FEOC comfort, and no factoring in 2025 improve bridge-to-scale quality. |
| Filing Delta (0 to 5) | 3 | October improves survivability and scale-bridge evidence versus July, but is not a totally new wave-discovery filing. |
| Incumbent Saturation Penalty (0 to -5) | 0 | Still early, not saturated. |
| False-Promise Penalty (0 to -5) | -1 | Bookings timing and financing fragility remain, but the bridge is now much more credible. |
| **Total Venture Score** | **15** |  |

### Venture Mode Early-Flip Override
A company can beat a mature incumbent even with weaker current conversion if all are true:
- `Wave Exposure >= 4` ✅
- `Asymmetric Upside >= 4` ✅
- `Fundable Scaling >= 3` ✅

### Venture Mode Decision
- Winner: `BE`
- Why:
  - BE still has the larger asymmetric path.
  - The bridge to scale is now stronger than in July.
  - NVDA remains excellent, but too saturated for a venture-style 10x hunt.

---

## Public-Growth Mode Scoring Sheet

### Formula
`Public-Growth Score = Wave Exposure + Commercial Proof + Survivability Quality + Filing Delta + Incumbent Saturation Penalty + Fragility Penalty`

### Company A — NVDA
| Factor | Score | Evidence from filing only |
|---|---:|---|
| Wave Exposure (0 to 5) | 5 | Explicit AI infrastructure linkage remains strong. |
| Commercial Proof (0 to 5) | 5 | Conversion is fully proven. |
| Survivability Quality (0 to 5) | 5 | Elite manufacturing, supplier, and capital bridge quality. |
| Filing Delta (0 to 5) | 2 | Incremental rather than breakaway improvement. |
| Incumbent Saturation Penalty (0 to -5) | -4 | Mature winner penalty still applies. |
| Fragility Penalty (0 to -5) | 0 | No meaningful fragility in the scaling path. |
| **Total Public-Growth Score** | **13** |  |

### Company B — BE
| Factor | Score | Evidence from filing only |
|---|---:|---|
| Wave Exposure (0 to 5) | 4 | Explicit AI data-center / on-site power linkage remains central. |
| Commercial Proof (0 to 5) | 3 | Still weaker than NVDA, but safe-harbored future deployment volume plus stronger partner/policy scaffolding move BE above mere aspiration. |
| Survivability Quality (0 to 5) | 4 | Brookfield mention, policy runway through 2033, FEOC comfort, and improved liquidity optics materially strengthen survivability quality. |
| Filing Delta (0 to 5) | 3 | Clear improvement versus July in bridge-to-scale credibility. |
| Incumbent Saturation Penalty (0 to -5) | 0 | No maturity penalty. |
| Fragility Penalty (0 to -5) | -1 | Bookings and financing risk still exist, but less severe than before. |
| **Total Public-Growth Score** | **13** |  |

### Public-Growth Mode Decision
- Winner: `BE`
- Why:
  - BE now clears the stricter proof threshold.
  - July had wave plus asymmetry; October adds enough survivability and bridge-to-scale evidence for public-growth mode to stop waiting.
  - Under the final tie-break rule, BE wins because it has `Commercial Proof >= 3`, `Survivability Quality >= 4`, and a much lower `Incumbent Saturation Penalty` than NVDA.

### Public-Growth tie-break application
Scores are tied at `13`.
Apply final tie-break logic:
1. check if a company has `Commercial Proof >= 3` and `Survivability Quality >= 4`
2. if yes, prefer the company with the lower `Incumbent Saturation Penalty`

Result:
- `BE` satisfies the threshold and has lower incumbent saturation than `NVDA`
- therefore `BE` wins the tie mechanically under the final framework

---

## Decision Output Block

- Venture Mode winner: `BE`
- Venture Mode score: `15 vs 8`
- Public-Growth Mode winner: `BE`
- Public-Growth Mode score: `13 vs 13`
- Final interpretation:
  - if both agree: by October both modes can support BE once survivability and bridge-to-scale evidence improve enough
  - if they differ: the disagreement is now mostly tie-break mechanics, not core filing interpretation
- Filing signals that mattered most:
  - BE Brookfield / SK ecoplant scaffolding
  - BE restored 30% tax-credit runway through 2033
  - BE FEOC comfort
  - BE no factoring in 2025
  - NVDA domestic manufacturing / resiliency continuation
- What would need to improve in the weaker filing to flip next time:
  - For BE to beat NVDA cleanly without tie-break changes: stronger present-tense commercial proof or cleaner booking conversion evidence
