# Fundamental Framework

Standalone fundamental stock-screening and underwriting framework.

## Dealflow handoff

Dealflow sends a prioritized ticker queue. The fundamental framework converts that queue into a universe CSV, resolves SEC CIKs, fetches required filings, computes fundamental scores, and writes score/decision artifacts.

Default CLI path:

```bash
python -m cli.main fundamental --date YYYY-MM-DD
```

Main outputs are written under:

```text
eval_results/fundamental/<date>/lake/
```

Key tables:

- `universe.parquet` — dealflow tickers, CIKs, and provenance metadata
- `filing_events.parquet` — selected SEC 8-K / exhibit / 10-Q or 10-K metadata
- `raw_documents.parquet` — fetched document text and quality flags
- `pre_llm_scores.parquet` — pre-LLM fundamental score and bucket
- `candidate_scores.parquet` — entry score, gate results, and decision fields
- `investment_decisions.parquet` — PM-underwriting-ready decision rows
- `research_memos.parquet` — memo-ready summaries

## Required SEC documents

For each ticker and quarter, the framework looks for:

1. Earnings 8-K
   - form `8-K` or `8-K/A`
   - includes Item `2.02`
   - filed inside the target quarter

2. Earnings exhibit
   - selected from the 8-K archive index
   - prefers HTML exhibit names containing terms like `ex99`, `press`, `release`, `earn`, `result`, `shareholder`, `letter`, `cfo`, or `pr`

3. Periodic filing
   - latest `10-Q` or `10-K` filed on/before quarter end

Fetched document types:

- `primary_8k`
- `earnings_exhibit`
- `periodic_10q_10k`

## Buy/pass/starter decision

Buy/pass/starter decision = **Stage 5A underwriting**, after `entry_score_0_100`.

Core logic:

- `entry_score >= 75` → buy underwriting queue
- `entry_score 65-74` → fundamental review list / possible starter
- `entry_score 50-64` → watchlist
- `<50` → pass / low priority

Score alone is not enough.

Buy needs gates pass:

- catalyst clear: why now
- price still ok vs signal price
- valuation upside/downside ok
- liquidity ok
- LLM causal support strong
- revision/demote risk acceptable
- macro/theme allowed
- invalidation trigger defined

Starter = score decent but uncertainty remains:

- `65-74`, or
- `>=75` but price moved too far / thesis needs confirmation / risk elevated

Pass = fail gate:

- kill_review
- expired signal
- no catalyst
- weak LLM causal support
- high negative revision risk
- liquidity bad
- price already chased
- undefined invalidation trigger

Current framework creates **eligibility/rank**. Final buy/starter/pass = PM underwriting layer, not automatic.
