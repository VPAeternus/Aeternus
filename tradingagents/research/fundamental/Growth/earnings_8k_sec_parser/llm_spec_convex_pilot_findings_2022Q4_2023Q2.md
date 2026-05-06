# Spec Convex LLM Pilot: 2022Q4 + 2023Q2

## Scope

Pilot set:
- 24 `spec_convex` rows from `2022Q4` and `2023Q2`.
- 12 largest 90-day winners.
- 12 worst 90-day losers.
- Scoring used only cached `8-K / EX-99.1` evidence packets.

Important caveat:
- This is an in-session LLM pilot, not automated API extraction.
- Outcomes/returns are included only for evaluation after scoring.
- Production prompt must not include future return or winner/loser label.

## Output Files

- Selection: `Growth/earnings_8k_sec_parser/llm_spec_convex_pilot_selection_2022Q4_2023Q2.csv`
- Evidence packets: `Growth/earnings_8k_sec_parser/llm_spec_convex_pilot_packets_2022Q4_2023Q2.md`
- LLM extraction: `Growth/earnings_8k_sec_parser/llm_spec_convex_pilot_extractions_2022Q4_2023Q2.csv`

## Scoring

Used existing `narrative_delta` formula:

```text
narrative_delta_score =
  causal_change
+ proof_alignment
+ durability
+ operating_leverage_quality
- negative_revision_risk
- story_vs_numbers_gap_penalty
```

Bucket rules:
- `inflecting`: score `>= 7`
- `constructive`: score `3` to `6`
- `neutral`: score `0` to `2`
- `deteriorating`: score `< 0`

Hard override:
- If `negative_revision_risk >= 4`, `score_addition = -3`.

## What Worked

Most true winners had one of these filing-level patterns:
- Clear operating leverage inflection: CVNA, PTON, TDAY, LTH.
- Guidance raise or guidance beat with proof: EXAS, PLTR, TDAY.
- Backlog / bookings / demand recovery: MTRX, ATRO.
- Secular demand wave plus margin conversion: VRT.

Strongest positive archetype:

```text
demand/guidance shock
+ hard-number proof
+ margin/cash conversion
+ multi-quarter durability
- low negative revision risk
```

## Pilot Results

Post-score evaluation:

| Bucket | Count | Avg 90d Return | 30%+ Winners | -30% Losers |
|---|---:|---:|---:|---:|
| `inflecting` | 10 | `+71.18%` | `6/10` | `2/10` |
| `constructive` | 3 | `+86.24%` | `3/3` | `0/3` |
| `neutral` | 3 | `+8.37%` | `1/3` | `1/3` |
| `deteriorating` | 8 | `-1.74%` | `2/8` | `2/8` |

Extra cuts:
- `negative_revision_risk <= 2`: `11` rows, avg `+73.41%`, median `+81.79%`, `7/11` were 30%+ winners.
- `negative_revision_risk >= 4`: `9` rows, avg `-4.79%`, median `-28.90%`, `2/9` were 30%+ winners.
- `score >= 7`, `risk <= 2`, `operating_leverage_quality >= 2`, `proof_alignment >= 3`: `9` rows, avg `+68.77%`, median `+81.00%`, `5/9` were 30%+ winners.

Interpretation:
- Positive narrative quality helped in this pilot.
- Negative revision risk was the cleanest demotion signal.
- False positives remain material, so this cannot be final picker alone.

## What Failed

False negatives:
- GRPN and COMP looked weak in filings but had large positive returns.
- Likely driver was distressed rebound / positioning / macro beta, not clean filing evidence.

False positives:
- DRVN, RRGB, NDLS, HIMS had strong filing narratives but negative 90-day returns.
- Filing evidence did not capture valuation, crowded expectations, sector pressure, or post-filing technical failure.

Main lesson:
- LLM narrative layer is useful, but not enough alone.
- Need combine with pre-LLM fundamentals, regime, valuation/expectations proxy, and price reaction/technical confirmation.

## Candidate Production Signal

Use LLM layer as `event_quality`, not final buy/sell.

Best next composite gate:

```text
spec_convex_candidate =
  revenue_bucket in [$100M, $10B]
  and pre_llm_fundamental_bucket in [weak, mixed]
  and narrative_delta_bucket in [inflecting, constructive]
  and negative_revision_risk <= 3
```

High priority:

```text
narrative_delta_score >= 7
and operating_leverage_quality >= 2
and proof_alignment >= 3
and negative_revision_risk <= 2
```

Avoid / demote:

```text
negative_revision_risk >= 4
or story_vs_numbers_gap_penalty >= 2
```

## Next Step

Run this narrative extraction on all `spec_convex` rows for `2022Q4` and `2023Q2`, then compare:
- `inflecting` vs `constructive` vs `neutral` vs `deteriorating`
- hit rate for `return_90d_pct >= 30`
- big-loss rate for `return_90d_pct <= -30`
- median and average 90-day return
- false-positive clusters by sector/story type
