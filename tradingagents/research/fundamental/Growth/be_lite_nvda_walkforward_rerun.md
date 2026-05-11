# BE / LITE / NVDA walkforward — apples-to-apples rerun

This rerun supersedes the earlier LITE reads that were based on degraded packet coverage.

Guardrail applied before scoring:
- auto-repair packet sections from cached SEC HTML
- block the run if any filing still lacks required sections
- no degraded-vs-rich packet comparisons allowed

Verification command used:
- `PYTHONPATH=. python Growth/check_growth_comparability.py /Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/filing_packets/LITE_000162828025004288.json /Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/filing_packets/LITE_000162828025022788.json /Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/filing_packets/LITE_000162828025040830.json /Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/filing_packets/LITE_000162828025049073.json /Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/filing_packets/LITE_000162828026005129.json /Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/filing_packets/BE_000162828025021160.json /Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/filing_packets/BE_000162828025037074.json /Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/filing_packets/BE_000162828025046844.json /Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/filing_packets/BE_000162828026006516.json /Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/filing_packets/NVDA_000104581025000023.json /Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/filing_packets/NVDA_000104581025000116.json /Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/filing_packets/NVDA_000104581025000209.json /Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/filing_packets/NVDA_000104581025000230.json /Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec/filing_packets/NVDA_000104581026000021.json`

## What changed after repair
- `LITE` is no longer a `risk-factors only` story.
- The repaired `2025-08-19 10-K` materially improves the LITE read:
  - explicit cloud data center / AI-ML infrastructure exposure
  - optical links for cloud computing and data-center interconnect
  - increasing demand from AI and cloud customers as they expand data centers
  - stronger liquidity than the earlier degraded packet implied
- But the rerun still does **not** make LITE the Venture Mode winner at any step.

## Step-by-step rerun

| Step | Active set | Venture Mode | Venture archetype | Public-Growth | LITE verdict |
|---|---|---|---|---|---|
| 1 | `LITE 2025-02-06` only | `LITE` provisional | `Torque Bottleneck` provisional | `LITE` provisional | only active name |
| 2 | `LITE 2025-02-06`, `NVDA 2025-02-26`, `BE 2025-02-27` | `BE` | `Expansion Bridge` | `NVDA` | relevant, but not strongest |
| 3 | `LITE 2025-02-06`, `NVDA 2025-02-26`, `BE 2025-04-30` | `NVDA` | none; incumbent holds | `NVDA` | still below winner threshold |
| 4 | `LITE 2025-05-07`, `NVDA 2025-05-28`, `BE 2025-04-30` | `NVDA` | none; incumbent holds | `NVDA` | still below winner threshold |
| 5 | `LITE 2025-05-07`, `NVDA 2025-05-28`, `BE 2025-07-31` | `BE` | `Expansion Bridge` | `NVDA` | BE gets the venture flip first |
| 6 | `LITE 2025-08-19`, `NVDA 2025-08-27`, `BE 2025-07-31` | `BE` | `Expansion Bridge` | `NVDA` | repaired 10-K helps, but not enough |
| 7 | `LITE 2025-11-05`, `NVDA 2025-08-27`, `BE 2025-10-28` | `BE` | `Expansion Bridge` | `BE` | BE stronger on asymmetry + scale bridge |
| 8 | `LITE 2026-02-04`, `NVDA 2025-11-19`, `BE 2026-02-09` | `BE` | `Expansion Bridge` | `BE` | BE decisively ahead |
| 9 | `LITE 2026-02-04`, `NVDA 2026-02-25`, `BE 2026-02-09` | `BE` | `Expansion Bridge` | `BE` | LITE never takes over |

## Rerun under the formalized Venture framework
- `LITE` is now evaluated through the correct internal path:
  - `Torque Bottleneck`
- `BE` is evaluated through:
  - `Expansion Bridge`
- Result after rerun:
  - the framework is now conceptually correct about *how* to evaluate `LITE`
  - but `LITE` still does not beat `BE` on the filing evidence available in this window

## Updated LITE interpretation by phase

### Early 2025 (`2025-02-06`, `2025-05-07`)
- Repair gets us formal comparability, but the repaired `10-Q` MD&A sections are still thin and mostly introductory.
- LITE reads as:
  - AI / cloud-adjacent
  - optical-network beneficiary
  - but not yet a clearly emerging asymmetric winner from the filing text alone
- So the early rerun does **not** change the ranking outcome.

### August 2025 (`2025-08-19 10-K`)
This is the important rerun change.

What the repaired filing now clearly shows:
- LITE serves `cloud data center operators` and `AI/ML infrastructure providers`
- products enable `high-capacity optical links` and `data center interconnect`
- management says fiscal 2025 saw `increasing demand from AI and cloud customers as they continue to expand their data centers`
- liquidity is much better than the degraded packet suggested:
  - `cash and cash equivalents` around `$520.7 million`

What that means under the new archetype logic:
- LITE now clearly qualifies for consideration as a `Torque Bottleneck` candidate
- it has:
  - direct bottleneck-layer exposure
  - active AI / cloud demand support
  - real operating-leverage potential if demand keeps strengthening

Why that still does not flip Venture Mode:
- LITE also describes itself as an `industry leader based on revenue and market share`
- that reduces hidden-asymmetry versus `BE`
- the filing still carries material drag:
  - optical market maturity / commoditization
  - customer inventory normalization
  - margin pressure / underutilized capacity
  - export restriction and China-related friction
- the filing delta is real, but still not strong enough to beat BE's stronger `Expansion Bridge` path
- So repaired LITE becomes a **credible Torque Bottleneck wave beneficiary**, but not the best overall venture winner in this walkforward window.

### Late 2025 to February 2026 (`2025-11-05`, `2026-02-04`)
- The repaired `10-Q` packets remain low-information compared with the richer LITE `10-K`.
- They do not add a new breakaway filing delta.
- Meanwhile `BE` keeps adding exactly what Venture Mode rewards:
  - explicit AI data-center power bottleneck role
  - deployment runway
  - financing / partner scaffolding
  - then `AEP` and `Brookfield`
- So once `BE` flips, repaired late LITE still does not take it back.

## Final rerun judgment
LITE failed to take over in Venture Mode **even after apples-to-apples repair and after formalizing the correct `Torque Bottleneck` path**.

That means the earlier result was directionally right, but for the wrong reasons.

Corrected interpretation:
- old conclusion: `LITE lost because its packet was degraded`
- second conclusion: `LITE lost because the framework was too BE-shaped`
- rerun conclusion: `LITE is now being evaluated through the right generic Venture archetype, but even then it still does not beat BE in this filing-only framework window`

## Why repaired LITE still loses to BE
1. `LITE` has real AI / cloud / optical exposure, but less hidden asymmetry.
2. `LITE` is more mature and more obviously established.
3. `LITE` still carries commoditization and margin-pressure baggage.
4. `BE` has the stronger filing delta and stronger explicit bridge to scaled deployment.
5. `BE` looks more like the venture-style `small base + wave bottleneck + funding bridge` winner this framework is designed to catch.

## What would have been needed for LITE to win
The filings would have needed clearer proof of at least one of these:
- specific hyperscaler / AI-cluster optical deployment acceleration
- unmistakable demand persistence tied to AI interconnect buildout
- stronger new commercial proof versus prior filing
- clearer operating leverage or margin improvement from the AI wave
- a fresh filing delta strong enough to offset LITE's greater maturity
