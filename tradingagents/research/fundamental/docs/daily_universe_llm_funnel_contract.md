# Fundamental Daily Universe + LLM Funnel Contract

This document is the operating contract for daily fundamental scoring. Do not run Top15 from only the daily scout tickers unless explicitly doing a narrow scout-only smoke test.

Detailed daily gate sequence: `tradingagents/research/fundamental/docs/daily_run_gate_sequence.md`.

## Non-negotiable bottom line

Top15 must be selected from the broad persistent fundamental universe, not only from the daily scout handoff.

Daily scouts are an append/update source into the master universe. They are not the full universe.

LLM extraction must not run on the full 1,200+ universe by default. LLM extraction runs only on Tier 1–4 candidates after the pre-LLM filter.

## Correct daily sequence

1. Start from the persistent master fundamental universe.
   - Expected size: ~1,200+ tickers.
   - Canonical input format: JSON list or JSON object with `items`; each item needs `ticker` or `symbol`, `cik`, and company title metadata.
   - Compatibility input: CSV with `ticker` or `symbol` plus `cik`.
   - Current example artifact: `final_dealflow_tickers_sec_eligible.json` had `1,276` tickers.

2. Append daily scout tickers into the master universe.
   - Daily scout tickers are new evidence/discovery inputs.
   - Deduplicate by ticker.
   - Preserve CIK/company metadata.
   - Do not replace the master universe with only daily scouts.

3. Refresh SEC/cache coverage for the combined master universe.
   - Use SEC cached submissions/companyfacts/documents where possible.
   - Fetch missing required docs.
   - Foreign/no-domestic-filing blockers remain documented, not silently removed.

4. Build pre-LLM fundamental rows for the combined master universe.
   - Compute raw fundamental features.
   - Compute pre-LLM score/bucket.
   - Attach filing/document status.
   - Attach entry/tradable date and price data where required for scoring.

5. Apply Tier 0–4 filter before LLM.
   - Tier 0: no LLM by default; archive/low-priority/insufficient evidence.
   - Tier 1–4: LLM eligible.
   - LLM packets are created only for Tier 1–4.
   - Never create LLM packets for all 1,200+ tickers by default.

6. Run LLM extraction only on Tier 1–4 packets.
   - Output must be one standard `post_llm_scores.csv`.
   - Validate one row per expected LLM packet/sample_id.
   - Resume batch files when interrupted.

7. Merge post-LLM results back into the full master scored universe.
   - Tier 0 rows remain scored with no/post-LLM-neutral fields.
   - Tier 1–4 rows get LLM evidence fields.
   - Final scoring output must include the broad universe, not just LLM rows.

8. Compute HP buckets.
   - HP buckets are high-priority structural/quality/repricing groups.
   - HP is applied after pre-LLM + post-LLM evidence is available.
   - HP is not a replacement for the Tier 0–4 LLM gate.

9. Compute RM buckets.
   - RM buckets represent re-rating momentum/right-tail exception signals.
   - RM bucket logic feeds exception sleeve eligibility and priority.
   - RM is applied after HP/post-LLM/final score fields are available.

10. Run Top10 + Plus5 + shadow refill.
    - Top10 core: primary buy-underwriting candidates.
    - Plus5 exception: right-tail research/starter candidates.
    - Shadow refill: review-only replacement test for deteriorating core names.
    - Selection input must be the broad final scores CSV.

## Required labels

Use clear operator-facing labels in output CSVs:

- `top15_bucket = Top 10 core`
- `top15_bucket = Plus 5 exception`
- `shadow_refill_status = official_top15_selection`
- `shadow_refill_status = shadow_refill_review_only_not_official`

Avoid confusing labels like only `core shadow` or `exception shadow` without the Top10 + Plus5 context.

## What went wrong on 2026-05-11

The SEC fetch covered the broad universe:

- `final_dealflow_tickers_sec_eligible.json`: `1,276` tickers

But the fundamental scoring run used only daily scout/dealflow rows:

- `dealflow_universe.csv`: `162` tickers
- `post_llm_scores.csv`: `162` rows
- `fundamental_final_scores_2026-05-11.csv`: `162` rows
- Top15 selected from those `162`, not from all `1,276`.

This is acceptable only as a scout-only smoke run. It is not the final daily fundamental Top15 process.

## CLI behavior that must exist

The CLI must support these separate concepts:

1. Master-universe input/output.
2. Daily scout append/update.
3. Tier 0–4 pre-LLM classification.
4. LLM extraction limited to Tier 1–4.
5. Post-LLM merge into full broad final scores.
6. HP bucket assignment.
7. RM bucket assignment.
8. Top10 + Plus5 + shadow refill from broad final scores.

Current partial fix:

- `--llm-mode skip|post-file|in-session|external|subagent` exists.
- It can run external Codex LLM extraction and post-file scoring.
- It still needs explicit broad-universe + Tier 0–4 LLM filter wiring.

## Hard guardrails for future agents

Before claiming a daily fundamental run is final, verify:

1. Broad universe row count is ~1,200+ or explicitly documented otherwise.
2. Daily scout tickers were appended/deduped into the broad universe.
3. LLM packet count is less than broad universe count unless user explicitly requested full-universe LLM.
4. LLM packet count equals Tier 1–4 count.
5. Final scores row count equals broad universe count, not LLM packet count.
6. Top15 input path is the broad final scores CSV.
7. Official Top15 publish requires prior-quarter comparison data: every LLM-complete row must have `entry_qoq_pct`, `score_change`, and `prior_pre_llm_fundamental_score`.
7. Output labels show `Top 10 core`, `Plus 5 exception`, and `shadow refill` clearly.

If any check fails, do not call the CSV final.
