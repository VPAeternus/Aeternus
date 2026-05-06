# Spec Convex Full LLM Extraction: 2022Q4 + 2023Q2

## Scope

Input:
- `373` `spec_convex` rows from `2022Q4` and `2023Q2`.
- `188` from `2022Q4`.
- `185` from `2023Q2`.
- Input packets included only filing-time evidence snippets, pre-LLM fundamentals, quarter, ticker, and event date.
- Input packets did not include returns, prices, or winner/loser labels.

LLM runner:
- Model: `gpt-5.4-mini`.
- Batch size: `8`.
- Batches completed: `47`.
- Output rows: `373`.
- Final score math was recomputed deterministically in Python from LLM component scores.

## Files

- Packets: `Growth/earnings_8k_sec_parser/llm_spec_convex_all_2022Q4_2023Q2_packets.jsonl`
- Raw batch outputs: `Growth/earnings_8k_sec_parser/llm_spec_convex_all_2022Q4_2023Q2_llm/`
- LLM extraction CSV: `Growth/earnings_8k_sec_parser/llm_spec_convex_all_2022Q4_2023Q2_extractions.csv`
- Joined score/return CSV: `Growth/earnings_8k_sec_parser/llm_spec_convex_all_2022Q4_2023Q2_joined.csv`
- Candidate CSV: `Growth/earnings_8k_sec_parser/llm_spec_convex_all_2022Q4_2023Q2_candidates.csv`
- High-priority CSV: `Growth/earnings_8k_sec_parser/llm_spec_convex_all_2022Q4_2023Q2_high_priority.csv`
- Demote CSV: `Growth/earnings_8k_sec_parser/llm_spec_convex_all_2022Q4_2023Q2_demote.csv`
- Summary CSV: `Growth/earnings_8k_sec_parser/llm_spec_convex_all_2022Q4_2023Q2_summary.csv`

## Output Quality

Validation:
- Extraction rows: `373`.
- Unique sample IDs: `373`.
- Missing core fields: `0`.
- Formula errors after deterministic recompute: `0`.

Bucket counts:
- `inflecting`: `100`
- `constructive`: `128`
- `neutral`: `91`
- `deteriorating`: `53`
- `unscorable`: `1`

## Performance Read

Base `spec_convex` pool:
- Count: `373`
- Avg 90d return: `+15.94%`
- Median 90d return: `+11.18%`
- 30%+ winner rate: `22.79%`
- -30% loser rate: `1.34%`

Production-style candidate gate:

```text
narrative_delta_bucket in [inflecting, constructive]
and negative_revision_risk <= 3
```

Result:
- Count: `228`
- Avg 90d return: `+17.12%`
- Median 90d return: `+10.15%`
- 30%+ winner rate: `22.37%`
- -30% loser rate: `0.88%`

High-priority gate:

```text
narrative_delta_score >= 7
and proof_alignment >= 3
and operating_leverage_quality >= 2
and negative_revision_risk <= 2
```

Result:
- Count: `85`
- Avg 90d return: `+13.06%`
- Median 90d return: `+9.46%`
- 30%+ winner rate: `21.18%`
- -30% loser rate: `1.18%`

Best simple component cut found:

```text
proof_alignment >= 3
and operating_leverage_quality >= 2
and negative_revision_risk <= 2
```

Result:
- Count: `102`
- Avg 90d return: `+19.36%`
- Median 90d return: `+13.50%`
- 30%+ winner rate: `26.47%`
- -30% loser rate: `0.98%`

## Interpretation

The LLM layer completed successfully, but the first broad `narrative_delta` bucket is not yet a strong enough filter.

Useful signal:
- `proof_alignment` plus `operating_leverage_quality` did improve average return and hit rate modestly.
- Rows with no operating leverage quality were weaker: avg `+6.41%`, median `+2.08%`.

Weak signal:
- `negative_revision_risk` did not cleanly demote losers in these two quarters.
- `inflecting` alone did not outperform the full `spec_convex` pool.
- `high_priority` as currently defined was too broad / not selective enough.

Likely reason:
- `2022Q4` and `2023Q2` were risk-on/rebound-heavy windows.
- Many weak/speculative companies rallied even with imperfect narratives.
- LLM narrative quality alone cannot separate filing quality from regime beta, short-covering, valuation reset, or technical reversal.

## Next Calibration

Do not discard LLM layer. Tighten it.

Next LLM fields should be more discriminating:
- `turnaround_proof`: Is the filing showing actual repair, not just management plan?
- `operating_leverage_conversion`: Does revenue/demand convert into margin/profit/cash?
- `demand_quality`: Is demand durable/end-market/customer-led vs rebound/channel/macro?
- `balance_sheet_overhang`: Is upside capped by dilution/debt/liquidity pressure?
- `expectations_reset_signal`: Is the stock likely washed out because numbers stopped getting worse?
- `technical_confirmation_needed`: Should this require post-filing price confirmation before selection?

Current best next gate to test:

```text
proof_alignment >= 3
and operating_leverage_quality >= 2
and negative_revision_risk <= 2
```

But this is only a candidate, not final. Need test across more quarters, especially bear/chop regimes.
