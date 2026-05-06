# BE vs LITE vs NVDA Fundamental

## Scope
- Universe: `BE`, `LITE`, `NVDA`
- Method: filing-only growth framework
- Modes tracked:
  - `Venture Mode`
  - `Public-Growth Mode`
- Rule: one filing at a time, point-in-time only, no external data beyond SEC filings and filing-derived metrics.

## Filing set in cache
- `LITE`
  - `2025-02-06` `10-Q`
  - `2025-05-07` `10-Q`
  - `2025-08-19` `10-K`
  - `2025-11-05` `10-Q`
  - `2026-02-04` `10-Q`
- `NVDA`
  - `2025-02-26` `10-K`
  - `2025-05-28` `10-Q`
  - `2025-08-27` `10-Q`
  - `2025-11-19` `10-Q`
  - `2026-02-25` `10-K`
- `BE`
  - `2025-02-27` `10-K`
  - `2025-04-30` `10-Q`
  - `2025-07-31` `10-Q`
  - `2025-10-28` `10-Q`
  - `2026-02-09` `10-K`

## Step 1 — 2025-02-06
### Active filing set
- `LITE` — `2025-02-06` — `10-Q` — `0001628280-25-004288`
- `NVDA` — no filing yet in-window until `2025-02-26`
- `BE` — no filing yet in-window until `2025-02-27`

### Analyst card — LITE
- Company: `LITE`
- Filing date: `2025-02-06`
- Form: `10-Q`
- Core read: provisional only. The cached packet extraction for this filing captured mainly `Risk Factors`, not a clean MD&A section, so this first read is lower-confidence than the BE/NVDA packets.
- What matters from the filing text available:
  - optical communications markets are described as more mature and increasingly commoditized
  - the filing highlights pricing pressure, reliance on limited customers and suppliers, backlog uncertainty, order cancellations/delays, and supply-chain constraints
  - it references strategic transactions including `Cloud Light`
  - it references Huawei/export issues tied to a major networking customer in China
- Growth-framework read:
  - there is real AI / cloud / networking adjacency, but this packet does not yet show the same kind of explicit early-wave language that later helped BE flip
  - the extracted filing evidence currently looks more like `infrastructure supplier with execution and customer concentration risk` than `hidden 10x wave rider`

### Mechanical score snapshot
| Mode | LITE score | Provisional read |
|---|---:|---|
| Venture mode | 6 | Some optical / cloud adjacency, but maturity, commoditization, customer concentration, and thin extracted proof hold it back |
| Public-growth mode | 5 | Too little present-tense proof in the extracted packet |

### Step decision
- Venture Mode winner: `LITE` (provisional, only active filing)
- Public-Growth winner: `LITE` (provisional, only active filing)
- Effective entry date: `2025-02-07 open`
- Important note: this is a weak-confidence starting hold because the available LITE packet extraction is incomplete relative to the richer BE/NVDA packets. We should treat the next active filings as more decision-relevant.

## Step 2 — 2025-02-27 active set
### Active filing set
- `LITE` — `2025-02-06` — `10-Q` — `0001628280-25-004288`
- `NVDA` — `2025-02-26` — `10-K` — `0001045810-25-000023`
- `BE` — `2025-02-27` — `10-K` — `0001628280-25-008747`

### Analyst card — cross-sectional read
- `LITE`
  - optical / cloud / networking adjacency is real, but the filing text available is dominated by commoditization, customer concentration, cancellations/delays, export issues, and financing risk
  - today it reads more like a pressured infrastructure supplier than an early hidden 10x wave rider
- `NVDA`
  - strongest live commercialization and scale proof
  - explicit prepaid capacity, supplier expansion, and durable AI infrastructure demand
  - but heavy maturity / saturation problem in a growth-hunt framework
- `BE`
  - explicit macro framing that power demand is increasing because of `data centers and artificial intelligence`
  - islanded microgrids / time-to-power / bypassing interconnection constraints all map directly to the AI power bottleneck
  - safe-harbored deployment through `2028`
  - financing / policy / gross-margin fragility still exist, but asymmetry is much larger than NVDA and cleaner than LITE's current packet

### Mechanical score snapshot
| Company | Venture mode | Public-growth mode | Read |
|---|---:|---:|---|
| `LITE` | 6 | 5 | wave-adjacent, but too mature/commoditized and too thinly extracted here |
| `NVDA` | 9 | 14 | best proof, but already-known incumbent |
| `BE` | 12 | 8 | early wave-attachment and asymmetry are strong; proof is still weaker than NVDA |

### Step decision
- Venture Mode winner: `BE`
- Public-Growth winner: `NVDA`
- Effective venture entry date: `2025-02-28 open`
- Effective public-growth entry date: `2025-02-28 open` into `NVDA`

### Why BE takes over in Venture Mode
- This is the first 3-way step where `BE` looks like the venture-style wave rider:
  - direct AI/data-center power language
  - clear bottleneck relevance
  - much larger asymmetry than `NVDA`
  - cleaner growth path than the currently extracted `LITE` filing
- So yes: in the venture group, `BE` takes over here.

## Step 3 — 2025-04-30 active set
### Active filing set
- `LITE` — `2025-02-06` — `10-Q` — `0001628280-25-004288`
- `NVDA` — `2025-02-26` — `10-K` — `0001045810-25-000023`
- `BE` — `2025-04-30` — `10-Q` — `0001628280-25-021160`

### Analyst card — cross-sectional read
- `LITE`
  - still constrained by the same problem: the cached packet remains mostly risk-factor extraction
  - what is visible still points to a mature optical market with customer concentration, backlog uncertainty, commoditization, and financing risk
- `NVDA`
  - still has the strongest commercialization and scale proof in the set
  - still heavily penalized for already-known dominance
- `BE`
  - still clearly tied to data-center power demand and large-customer expansion
  - but this specific filing is weaker than the February 10-K on wave specificity
  - it leans more on liquidity, financing, and strategic ambition than on concrete new proof

### Mechanical score snapshot
| Company | Venture mode | Public-growth mode | Read |
|---|---:|---:|---|
| `LITE` | 6 | 5 | no new evidence yet |
| `NVDA` | 9 | 14 | best proof, still saturated |
| `BE` | 8 | 6 | remains venture-relevant, but this filing is not a strong step-up |

### Step decision
- Venture Mode winner: `NVDA`
- Public-Growth winner: `NVDA`
- Effective entry date: `2025-05-01 open`

### Why BE does not hold the lead here
- BE took over in venture mode on the stronger `2025-02-27` filing.
- But the `2025-04-30` filing does **not** strengthen the venture case enough to keep the top spot in a 3-way comparison.
- So for this step, BE loses momentum and `NVDA` retakes the lead until a stronger BE wave-conversion filing appears.

## Step 4 — 2025-05-28 active set
### Active filing set
- `LITE` — `2025-05-07` — `10-Q` — `0001628280-25-022788`
- `NVDA` — `2025-05-28` — `10-Q` — `0001045810-25-000116`
- `BE` — `2025-04-30` — `10-Q` — `0001628280-25-021160`

### Analyst card — cross-sectional read
- `LITE`
  - still has the same extraction limitation: mostly risk factors, not strong current operating proof
  - visible language still points to optical market maturity, commoditization, customer concentration, backlog uncertainty, and financing risk
  - Cloud Light is present, but not enough by itself to make this an early 10x-wave winner in the filing text we have
- `NVDA`
  - gets stronger here because the filing adds `Blackwell Ultra` cadence plus explicit dependence on `data centers, energy, and capital`
  - prepaid manufacturing and capacity agreements reinforce the live AI infrastructure conversion story
- `BE`
  - remains relevant, but the active BE filing is still the weaker `2025-04-30` packet
  - this leaves BE behind NVDA until the stronger later BE filings arrive

### Mechanical score snapshot
| Company | Venture mode | Public-growth mode | Read |
|---|---:|---:|---|
| `LITE` | 6 | 5 | still not enough current filing evidence to beat the others |
| `NVDA` | 10 | 15 | strongest active filing in the set |
| `BE` | 8 | 6 | still waiting on a stronger follow-up filing |

### Step decision
- Venture Mode winner: `NVDA`
- Public-Growth winner: `NVDA`
- Effective entry date: `2025-05-29 open`

### Why LITE still does not challenge
- LITE is wave-adjacent, but the packet evidence available in cache still reads more like `mature optical supplier under pressure` than `venture-style asymmetric winner`.
- So the 3-way contest remains essentially `NVDA` vs `BE`, with `LITE` still below the threshold.

## Step 5 — 2025-07-31 active set
### Active filing set
- `LITE` — `2025-05-07` — `10-Q` — `0001628280-25-022788`
- `NVDA` — `2025-05-28` — `10-Q` — `0001045810-25-000116`
- `BE` — `2025-07-31` — `10-Q` — `0001628280-25-037074`

### Analyst card — cross-sectional read
- `LITE`
  - still not improving in the extracted packet set
  - what remains visible is commodity pressure, backlog uncertainty, customer concentration, financing risk, and Cloud Light optionality without strong current conversion evidence
- `NVDA`
  - still has the strongest present-tense commercialization and scale proof
  - but it is increasingly the already-known incumbent rather than the hidden asymmetric winner
- `BE`
  - now explicitly frames success around the `AI data center market`
  - safe-harbored deployment through `2028` is still present
  - restored `30%` tax-credit runway through `2033` materially extends viability
  - bookings delays and financing dependence still exist, but this is a clear strengthening versus the April filing

### Mechanical score snapshot
| Company | Venture mode | Public-growth mode | Read |
|---|---:|---:|---|
| `LITE` | 6 | 5 | still below threshold |
| `NVDA` | 10 | 15 | strongest incumbent proof |
| `BE` | 14 | 10 | first strong 3-way venture-style wave rider signal |

### Step decision
- Venture Mode winner: `BE`
- Public-Growth winner: `NVDA`
- Effective venture entry date: `2025-08-01 open`
- Effective public-growth entry date: `2025-08-01 open` into `NVDA`

### Why BE retakes the lead here
- This is the first 3-way step where `BE` again clearly beats both `LITE` and `NVDA` in venture terms.
- What changed versus April:
  - the wave is more explicit
  - the deployment runway is still visible
  - the viability bridge is stronger
- So yes: this is the 3-way version of the BE venture inflection.

## Step 6 — 2025-08-27 active set
### Active filing set
- `LITE` — `2025-08-19` — `10-K` — `0001628280-25-040830`
- `NVDA` — `2025-08-27` — `10-Q` — `0001045810-25-000209`
- `BE` — `2025-07-31` — `10-Q` — `0001628280-25-037074`

### Analyst card — cross-sectional read
- `LITE`
  - even with the 10-K, the extracted packet still mostly surfaces risk-factor language
  - what is visible still emphasizes commoditization, customer concentration, backlog uncertainty, financing risk, and Cloud Light integration rather than a clean new AI-wave breakout
  - there is still no strong filing-grounded evidence here that LITE is becoming the best asymmetric venture-style choice in the set
- `NVDA`
  - remains the strongest incumbent on pure proof
  - now adds stronger Blackwell ramp language and U.S.-manufacturing / resiliency detail
  - but is even more clearly a known winner rather than a hidden 10x candidate
- `BE`
  - still has explicit AI data-center wave attachment, secure-through-2028 deployment, and improved policy runway
  - this remains a cleaner asymmetric venture case than either the saturated incumbent (`NVDA`) or the mature/commoditized optical supplier (`LITE`)

### Mechanical score snapshot
| Company | Venture mode | Public-growth mode | Read |
|---|---:|---:|---|
| `LITE` | 6 | 5 | still below threshold |
| `NVDA` | 9 | 14 | stronger incumbent proof, high saturation |
| `BE` | 14 | 10 | strongest venture-style wave rider |

### Step decision
- Venture Mode winner: `BE`
- Public-Growth winner: `NVDA`
- Effective venture entry date: `2025-08-28 open`
- Effective public-growth entry date: `2025-08-28 open` into `NVDA`

### Does LITE ever take over here?
- No.
- At this step, `LITE` still does not beat `BE` in Venture Mode.
- The filing evidence we have for LITE remains too risk-heavy and too mature-market oriented.

## Step 7 — 2025-11-05 active set
### Active filing set
- `LITE` — `2025-11-05` — `10-Q` — `0001628280-25-049073`
- `NVDA` — `2025-08-27` — `10-Q` — `0001045810-25-000209`
- `BE` — `2025-10-28` — `10-Q` — `0001628280-25-046844`

### Analyst card — cross-sectional read
- `LITE`
  - even after the November filing, the extracted packet still mostly exposes risk-factor language rather than strong operating proof
  - what remains visible is still the same cluster: optical commoditization, customer concentration, backlog uncertainty, financing optionality, and Cloud Light integration
  - there is no filing-grounded evidence here that LITE has become the best asymmetric wave rider in the set
- `NVDA`
  - still elite on commercialization and scale
  - but remains heavily saturated as an already-known incumbent
- `BE`
  - now has the strongest venture-style profile in the set
  - AI data-center demand is explicit
  - Brookfield partnership scaffolding appears
  - secure-through-2028 deployment, 2033 tax-credit runway, and FEOC comfort strengthen the bridge to scale materially

### Mechanical score snapshot
| Company | Venture mode | Public-growth mode | Read |
|---|---:|---:|---|
| `LITE` | 6 | 5 | still below threshold |
| `NVDA` | 9 | 14 | strongest incumbent proof, still saturated |
| `BE` | 15 | 13 | strongest asymmetric wave rider with now-credible bridge |

### Step decision
- Venture Mode winner: `BE`
- Public-Growth winner: `BE`
- Effective entry date: `2025-11-06 open`

### Does LITE take over here?
- No.
- By this point, `BE` is stronger on both asymmetry and bridge-to-scale, while `LITE` still looks too mature and too risk-dominated in the packet evidence available.

## Step 8 — 2026-02-09 active set
### Active filing set
- `LITE` — `2026-02-04` — `10-Q` — `0001628280-26-005129`
- `NVDA` — `2025-11-19` — `10-Q` — `0001045810-25-000230`
- `BE` — `2026-02-09` — `10-K` — `0001628280-26-006516`

### Analyst card — cross-sectional read
- `LITE`
  - even in February 2026, the extracted packet is still mostly risk-factor language
  - visible evidence remains the same: optical commoditization, customer concentration, backlog uncertainty, financing optionality, and Cloud Light integration
  - there is still no explicit filing-grounded breakout signal that would justify taking Venture Mode leadership away from BE
- `NVDA`
  - continues to look elite on proof and scale, but remains the already-known incumbent
- `BE`
  - now has the strongest filing in the whole 3-way test
  - AEP up to `1 GW`, including `100 MW` initial order
  - AEP acting as channel and financing partner
  - Brookfield up to `$5.0 billion` financing framework
  - 2033 tax-credit runway and FEOC comfort
  - this is no longer just asymmetry; it is asymmetry plus a strong institutional bridge to scale

### Mechanical score snapshot
| Company | Venture mode | Public-growth mode | Read |
|---|---:|---:|---|
| `LITE` | 6 | 5 | still below threshold |
| `NVDA` | 9 | 14 | elite incumbent proof, high saturation |
| `BE` | 18 | 16 | strongest wave rider and strongest bridge to scale |

### Step decision
- Venture Mode winner: `BE`
- Public-Growth winner: `BE`
- Effective entry date: `2026-02-10 open`

### Does LITE take over here?
- No.
- February 2026 is the moment you expected LITE might take over, but the filing evidence we have does not support it.
- Instead, BE becomes even stronger.

## Step 9 — 2026-02-25 active set
### Active filing set
- `LITE` — `2026-02-04` — `10-Q` — `0001628280-26-005129`
- `NVDA` — `2026-02-25` — `10-K` — `0001045810-26-000021`
- `BE` — `2026-02-09` — `10-K` — `0001628280-26-006516`

### Analyst card — cross-sectional read
- `LITE`
  - still does not materially improve in the extracted packet set
  - still reads more like mature optical exposure with risk-heavy disclosure than the best venture-style opportunity
- `NVDA`
  - adds Rubin and more Blackwell Ultra / supplier-capacity detail
  - remains outstanding on proof, but still saturated in a 10x-hunt framework
- `BE`
  - still has the strongest combination of explicit AI data-center power demand, asymmetry, financing bridge, and deployment runway
  - the 2026 NVDA 10-K does not dislodge that

### Mechanical score snapshot
| Company | Venture mode | Public-growth mode | Read |
|---|---:|---:|---|
| `LITE` | 6 | 5 | never crosses threshold in this test |
| `NVDA` | 8 | 13 | excellent incumbent, still saturated |
| `BE` | 18 | 16 | still the strongest 3-way choice |

### Step decision
- Venture Mode winner: `BE`
- Public-Growth winner: `BE`
- Effective entry date: `2026-02-26 open`

### Final answer on LITE
- In this cached 3-way filing test, `LITE` does **not** take over in Venture Mode at any point.
- The decisive reason is not lack of thematic relevance; it is lack of strong filing-grounded breakout evidence in the packet text available, combined with repeated signs of maturity, commoditization, concentration, and financing risk.
