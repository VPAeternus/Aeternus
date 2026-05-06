# Worked Example — NVDA 2025-05-28 vs BE 2025-07-31

## Inputs
- Company A: `NVDA`
- Filing date: `2025-05-28`
- Form: `10-Q`
- Prior filing date: `2025-02-26`
- Company B: `BE`
- Filing date: `2025-07-31`
- Form: `10-Q`
- Prior filing date: `2025-04-30`

---

## Venture Mode Scoring Sheet

### Formula
`Venture Score = Wave Exposure + Asymmetric Upside + Fundable Scaling + Filing Delta + Incumbent Saturation Penalty + False-Promise Penalty`

### Company A — NVDA
| Factor | Score | Evidence from filing only |
|---|---:|---|
| Wave Exposure (0 to 5) | 5 | Filing explicitly ties demand to AI infrastructure buildout and says customer buildout depends on data centers, energy, and capital availability. |
| Asymmetric Upside (0 to 5) | 1 | NVDA is already the obvious winner; upside is continuation, not business transformation from a small base. |
| Fundable Scaling (0 to 5) | 5 | Ongoing prepaid manufacturing and capacity agreements, increasing supply and capacity purchases, supplier expansion. |
| Filing Delta (0 to 5) | 3 | Adds Blackwell Ultra shipment cadence and sharper infrastructure-dependency framing vs prior filing. |
| Incumbent Saturation Penalty (0 to -5) | -5 | Already-dominant mega-cap wave leader; excellence is widely known. |
| False-Promise Penalty (0 to -5) | 0 | No story-without-bridge issue; bridge to scale is fully real. |
| **Total Venture Score** | **9** |  |

### Company B — BE
| Factor | Score | Evidence from filing only |
|---|---:|---|
| Wave Exposure (0 to 5) | 4 | Filing explicitly frames success around the AI data center market and power demand context. |
| Asymmetric Upside (0 to 5) | 5 | Much smaller company attached to a very large wave; if this use case scales, business size can change materially. |
| Fundable Scaling (0 to 5) | 3 | Safe-harbored deployment through 2028 and tax-credit support create a credible enough bridge, even though financing remains messy. |
| Filing Delta (0 to 5) | 4 | Meaningful improvement vs April: AI data-center framing is sharper and deployment runway is more concrete. |
| Incumbent Saturation Penalty (0 to -5) | 0 | Not an incumbent wave winner; still early. |
| False-Promise Penalty (0 to -5) | -2 | Delayed bookings, financing dependence, and policy sensitivity are real fragilities. |
| **Total Venture Score** | **14** |  |

### Venture Mode Early-Flip Override
A company can beat a mature incumbent even with weaker current conversion if all are true:
- `Wave Exposure >= 4` ✅
- `Asymmetric Upside >= 4` ✅
- `Fundable Scaling >= 3` ✅

### Venture Mode Decision
- Winner: `BE`
- Why:
  - BE clears the early-flip override.
  - It is explicitly on the AI data-center power wave.
  - It has much larger asymmetric upside than NVDA.
  - It looks fundable enough to survive and participate.

---

## Public-Growth Mode Scoring Sheet

### Formula
`Public-Growth Score = Wave Exposure + Commercial Proof + Survivability Quality + Filing Delta + Incumbent Saturation Penalty + Fragility Penalty`

### Company A — NVDA
| Factor | Score | Evidence from filing only |
|---|---:|---|
| Wave Exposure (0 to 5) | 5 | Explicit AI infrastructure demand linkage. |
| Commercial Proof (0 to 5) | 5 | Current conversion and monetization are already obvious and proven. |
| Survivability Quality (0 to 5) | 5 | Best-in-class balance-sheet / capacity / supplier bridge to continued scaling. |
| Filing Delta (0 to 5) | 3 | Blackwell Ultra cadence and incremental infrastructure proof. |
| Incumbent Saturation Penalty (0 to -5) | -4 | Mature winner penalty still applies, but less harsh than venture mode. |
| Fragility Penalty (0 to -5) | 0 | No meaningful fragility in the filing-grounded scale path. |
| **Total Public-Growth Score** | **14** |  |

### Company B — BE
| Factor | Score | Evidence from filing only |
|---|---:|---|
| Wave Exposure (0 to 5) | 4 | Explicit AI data-center and deployment-wave linkage. |
| Commercial Proof (0 to 5) | 2 | Better than April, but still limited proof of realized conversion versus the ambition. |
| Survivability Quality (0 to 5) | 2 | Good-enough for venture mode, but still weak for a stricter public-growth standard because financing and bookings remain messy. |
| Filing Delta (0 to 5) | 4 | Strong improvement from prior filing. |
| Incumbent Saturation Penalty (0 to -5) | 0 | No maturity penalty. |
| Fragility Penalty (0 to -5) | -2 | Delayed bookings and policy / financing dependence remain significant. |
| **Total Public-Growth Score** | **10** |  |

### Public-Growth Mode Decision
- Winner: `NVDA`
- Why:
  - BE has the better asymmetry story, but not enough present-tense proof.
  - NVDA still wins on commercial proof and survivability quality.
  - Public-growth mode intentionally waits longer.

---

## Decision Output Block

- Venture Mode winner: `BE`
- Venture Mode score: `14 vs 9`
- Public-Growth Mode winner: `NVDA`
- Public-Growth Mode score: `14 vs 10`
- Final interpretation:
  - if both agree: not applicable
  - if they differ: this is an early-wave divergence case; venture mode wants to enter BE early, public-growth mode says the filing is promising but still too fragile
- Filing signals that mattered most:
  - BE explicit `AI data center` linkage
  - BE secure-through-`2028` deployment runway
  - NVDA Blackwell / capacity / infrastructure proof
  - NVDA incumbent saturation
- What would need to improve in the weaker filing to flip next time:
  - For BE to win public-growth mode: stronger commercial proof, cleaner booking evidence, better survivability optics
