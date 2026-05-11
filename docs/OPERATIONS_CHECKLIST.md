# Aeternus Daily Operations Checklist

Review this every session. Each item is a thing that MUST be true for that stage to work.
Mark items with current status: OK / DEGRADED / BROKEN / NOT_CONFIGURED.

---

## PRE-FLIGHT (Before Any Pipeline Run)

### Environment

| # | Check | How to Verify | Expected |
|---|---|---|---|
| 1 | AKG is seeded and has company nodes | `python3 -c "import json; d=json.load(open('eval_results/control/knowledge_graph.json')); print(len([v for v in d['nodes'].values() if v.get('node_type')=='company']), 'company nodes')"` | 5,000+ |
| 2 | LLM provider is set and reachable | `echo $AETERNUS_LLM_PROVIDER` then `claude -p "ping"` | `claude_cli` + response |
| 3 | Alpha Vantage key is set | `python3 -c "import os; print('SET' if os.getenv('ALPHA_VANTAGE_API_KEY') else 'MISSING')"` | SET |
| 4 | Positions file is valid JSON | `python3 -c "import json; p=json.load(open('eval_results/paper_execution/positions.json')); print(len(p.get('open_positions',{})), 'open')"` | Number >= 0 |
| 5 | knowledge_graph.json is not corrupted | AKG loads without error (check #1 covers this) | No parse error |

### Data Freshness

| # | Check | How to Verify | Expected |
|---|---|---|---|
| 6 | Social/Grok cache exists for today | `ls eval_results/deal_flow/xai_social_cache_$(date +%Y-%m-%d).json` | File exists |
| 7 | Insider sweep rolling store exists | `python3 -c "import json; d=json.load(open('eval_results/deal_flow/insider_sweep_rolling.json')); print(len(d.get('transactions',[])), 'transactions')"` | > 0 transactions |
| 8 | Anchor set cache is fresh (< 7 days) | `python3 -c "import json,datetime; d=json.load(open('eval_results/deal_flow/anchor_set_cache.json')); print(d.get('cached_at','MISSING'))"` | Within 7 days |

---

## STAGE 1: Universe Discovery

**What it does:** Filters 5,345 AKG nodes into ~300-450 investable symbols across 6 tiers.

| # | Must Be True | Failure Sign | Fix |
|---|---|---|---|
| 9 | AKG has company nodes with metadata | Universe returns 0 symbols | Run `aeternus akg-seed` |
| 10 | yfinance can fetch SPY/QQQ holdings | T1 ANCHOR tier is only DOW_30 (30 stocks instead of ~100) | Check network; cache auto-refreshes |
| 11 | Breakout scanner ran during discover | No ATMOSPHERE+ nodes promoted | Check AKG save after discover |
| 12 | Insider sweep ran during discover | Rolling store not updated | Check SEC EDGAR reachability |
| 13 | Portfolio positions injected as T6 | Open positions not in universe, won't get re-scored | `positions.json` must exist and be valid |

**Verify:** `aeternus source --date YYYY-MM-DD --trigger manual --top-k 30 --format table`
Look for log line: `[pipeline] filtered universe: N symbols (T1=X T2=Y ...)`
Expected: 300-450 total.

---

## STAGE 2: Signal Collection

**What it does:** 8 connectors run in parallel, each producing scored signals per symbol.

| # | Connector | Weight | External Dep | Must Be True | Known Issue |
|---|---|---|---|---|---|
| 14 | price_momentum | 30% | yfinance | Returns OK for majority of universe | yfinance rate limits on large batches |
| 15 | social_news | 10% + 15% | Grok cache file | Cache file exists for today's date | Without cache: 25% of score weight is zero AND 2 evidence gate families lost |
| 16 | macro_regime_fit | 14% | yfinance (SPY, QQQ, TLT, UUP, DBC) | Regime data fetched successfully | yfinance downtime |
| 17 | smart_money | 11% | SEC EDGAR + Senate GitHub | At least one 13F or congress source returns data | EDGAR rate limit (429); data is 45-90 days stale by nature |
| 18 | sector_rotation | 8% | yfinance sector ETFs | Sector ETF prices fetched | yfinance downtime |
| 19 | insider_cluster | 5% | SEC EDGAR + rolling store | Rolling store populated from Stage 1 sweep | First run ever: no rolling store yet |
| 20 | emergence | 7% | AKG (local) | AKG has ATMOSPHERE+ nodes | No scouts ran = no emergence data |
| 21 | breakout_discovery | (feeds emergence) | yfinance | 252 days of OHLCV per symbol | New/recent IPOs lack history |
| 22 | value_overlay | 0% (dead weight) | — | Runs but contributes nothing | Can be ignored |

**Verify:** Check `eval_results/deal_flow/YYYY-MM-DD/connector_health.json` — all connectors should show `status: OK`.

**Critical degradation:** If social_news is NO_DATA (no Grok cache), the evidence gate becomes much harder to pass. Symbols need ALL of macro + smart_money + price_momentum + emergence to reach the 3-family minimum. Expect significantly fewer ACTIVE candidates.

---

## STAGE 3: Scout Ticker Handoff

**What it does:** Dedupes every ticker found by scouts and writes the authoritative dealflow handoff. No scout-sourced ticker is scored or ranked here.

| # | Must Be True | Failure Sign | Fix |
|---|---|---|---|
| 23 | `scout_ticker_summary.json` exists | No scout totals | Check scout artifacts and manual X-feed output |
| 24 | `final_dealflow_tickers.json` exists | No downstream handoff | Re-run collect after scout artifacts exist |
| 25 | Handoff contains only ticker metadata | Score/rank fields appear | Stop run and inspect dealflow cleanup |
| 26 | Latest pointers update | UI or fundamental adapter reads stale names | Check `latest_final_dealflow_tickers.json` |

**Verify:**
```
python3 -c "import json; h=json.load(open('eval_results/deal_flow/latest_final_dealflow_tickers.json')); print(len(h.get('tickers', [])), 'tickers')"
```

---

## STAGE 4: Fundamental Framework Entry

**What it does:** Fundamental research consumes the scout ticker handoff, resolves CIKs, and performs the first legitimate scoring step.

| # | Must Be True | Failure Sign | Fix |
|---|---|---|---|
| 27 | Adapter input is `final_dealflow_tickers.json` | Adapter reads stale dealflow artifacts | Use `--handoff` or latest handoff pointer |
| 28 | Universe CSV has no pre-fundamental score/rank fields | Pre-fundamental scoring leaked in | Fail the run and inspect adapter output |
| 29 | CIK status is visible per ticker | SEC pipeline misses names silently | Check `cik_status` in universe CSV |
| 30 | Fundamental output carries its own scores | No score after research | Debug fundamental framework, not dealflow |

**Verify:** `python3 -m cli.main fundamental from-dealflow --date YYYY-MM-DD --handoff eval_results/deal_flow/YYYY-MM-DD/final_dealflow_tickers.json`

---

## STAGE 5: Deep Analysis

**What it does:** Multi-agent debate produces an Aeternus score (0-100) per ticker.

| # | Must Be True | Failure Sign | Fix |
|---|---|---|---|
| 32 | LLM provider responds within timeout (120s) | Analysis times out, batch_summary shows failures | Check `claude -p "ping"`, increase timeout if needed |
| 33 | Alpha Vantage returns fundamental data | Analyst falls back to yfinance (less detailed) | Check API key, rate limit (5/min free tier) |
| 34 | Ensemble weights load correctly | All scores use identical weight profile | Check `eval_results/control/ensemble_weights.json` |
| 35 | Regime detection is sensible | Weights don't match market conditions | Check regime in batch_summary output |
| 36 | V3 hurdle (score >= 62) filters weak picks | Too many low-conviction picks in portfolio plan | Verify `portfolio_min_score=62` |

**Verify:** `cat eval_results/paper_execution/batch_summary_YYYY-MM-DD.json | python3 -c "import json,sys; s=json.load(sys.stdin); items=s.get('items',[]); ok=[x for x in items if x.get('status')=='SUCCESS']; print(f'{len(ok)}/{len(items)} succeeded')"`

---

## STAGE 6: Portfolio Plan

**What it does:** Converts analysis results into sized order intents.

| # | Must Be True | Failure Sign | Fix |
|---|---|---|---|
| 37 | Batch summary has SUCCESS items with score >= 62 | Plan has 0 orders (only V3 residual) | Check Stage 5 output |
| 38 | yfinance returns current prices for reference_price | Orders skipped (quantity = 0) | Network issue |
| 39 | Capital is configured correctly | Position sizes wrong | Check `portfolio_capital_usd` (default $100k) |
| 40 | Max position weight capped at 25% | Single position too large | Check `portfolio_max_weight_per_position` |

**Verify:** Plan file in `eval_results/paper_execution/plans/YYYY-MM-DD/` — should have orders with reasonable quantities and prices.

---

## STAGE 7: Execution (Paper)

**What it does:** Fills orders into positions.json, detects closures.

| # | Must Be True | Failure Sign | Fix |
|---|---|---|---|
| 41 | Liquidity gate passes for most orders | Log shows "LIQUIDITY GATE: rejected N orders" for everything | yfinance rate limit; retry later |
| 42 | Idempotency check prevents duplicate fills | Same order filled twice | Check `order_intent_id` uniqueness |
| 43 | Position closure detection works | Closed positions not in closed_trades.json | Check `_apply_fill_to_position` logic |
| 44 | AKG writeback fires on BUY fill | AKG `current_position` not set after trade | Check try/except in paper_execution.py (new code) |
| 45 | AKG writeback fires on position close | `outcome_weight` stays at 1.0 forever | Check try/except in paper_execution.py (new code) |
| 46 | Drawdown monitor logs but never blocks | Execution halted by drawdown check | Drawdown is informational only |

**Verify:** `aeternus paper-positions` — shows current open positions with entry prices.

---

## STAGE 8: Exit Management

**What it does:** Checks open positions against stop-loss, take-profit, and max-hold rules.

| # | Must Be True | Failure Sign | Fix |
|---|---|---|---|
| 47 | Stop loss at 8% | Losing position held past -8% | Run `aeternus manage-exits` |
| 48 | Take profit at 20% | Winner not locked in at +20% | Run `aeternus manage-exits` |
| 49 | Max hold 20 days | Stale position lingers | Run `aeternus manage-exits` |
| 50 | Exit orders create proper close events | closed_trades.json not updated | Check manage-exits output |

**Verify:** `aeternus manage-exits --date YYYY-MM-DD` — should show actions taken or "no exits triggered."

---

## STAGE 9: Fundamental Performance Review

**What it does:** Measures whether fundamental recommendations added value. Dealflow scout handoff itself is counted, not scored.

| # | Must Be True | Failure Sign | Fix |
|---|---|---|---|
| 51 | Scout handoff exists for source_date | Cohort returns "0 tickers" | Ensure scout collect ran on that date |
| 52 | yfinance returns 5-day forward prices | Returns are all NaN | Run after 5 trading days have passed |
| 53 | Fundamental recommendation artifact exists | No scored cohort | Run fundamental framework first |
| 54 | Performance rows accumulate | Review summary missing names | Check fundamental output paths |

**Verify:** compare fundamental recommendations against forward returns after enough trading days.

**Schedule:** Run weekly, every Monday, for the source date from 5+ trading days ago.

---

## STAGE 10: Morning Brief

**What it does:** Dashboard summary of portfolio, performance, risk, signals, and funnel health.

| # | Must Be True | Failure Sign | Fix |
|---|---|---|---|
| 56 | Brief renders without error | Command crashes | All sections are try/except wrapped — if it crashes, something is very wrong |
| 57 | Funnel health section shows data (after hindsight cycles) | "No funnel data yet" forever | Run hindsight + performance-review |
| 58 | Position P&L estimates are reasonable | Wild numbers | Check positions.json has correct avg_price values |
| 59 | Deal flow section shows latest candidates | "N/A" for queue date | No recent `source` run |

**Verify:** `aeternus brief`

---

## LEARNING LOOP (Automated, Check Periodically)

These are deferred triggers that fire automatically once thresholds are met.

| # | Trigger | Threshold | Current State | How to Check |
|---|---|---|---|---|
| 60 | IC auto-write (scoring weight adjustment) | >= 10 hindsight cycles + >= 3 families with \|t_stat\| > 2.0 | 2 cycles (need 8 more) | `ls eval_results/control/ic_signal_weights.json` |
| 61 | Ensemble weight evolution | >= 10 closed trades | Check closed count below | `cat eval_results/control/ensemble_weights.json \| python3 -c "import json,sys; print(json.load(sys.stdin).get('evolution_count', 0))"` |
| 62 | AKG Hebbian weights moving | Trades opening and closing via paper execution | Check any node's `outcome_weight` | `python3 -c "import json; d=json.load(open('eval_results/control/knowledge_graph.json')); ex=[v.get('outcome_weight') for v in d['nodes'].values() if v.get('outcome_weight') and v['outcome_weight']!=1.0]; print(len(ex), 'nodes with adjusted weights')"` |
| 63 | Funnel health visible in brief | >= 1 performance review cycle | After first hindsight run with chained perf-review | `aeternus brief` — look for Funnel Health panel |

**Closed trade count (run every session):**
```bash
python3 -c "import json; t=json.load(open('eval_results/paper_execution/track_record.json')); closed=[x for x in t.get('trades',[]) if x.get('status')=='CLOSED']; print(len(closed), 'closed trades')"
```

---

## NOT_CONFIGURED (Known Gaps, March 2026)

These are accepted gaps — not bugs. Track them so you know what's degraded.

| # | Component | Impact | When to Fix |
|---|---|---|---|
| 64 | x_feed_scout + cashtag_enricher (xAI API disabled by policy) | No automated discovery of trending tickers; no per-ticker social enrichment on AKG. Manual Grok paste covers the collector side (`social_news.py`) but not the scout side. | Policy decision — manual workflow is intentional. Re-enable if xAI API quality improves. |
| 65 | (removed — cashtag_stream fully deleted) | — | — |
| 66 | (removed — House congressional code deleted, Senate-only by design) | — | — |
| 67 | GARCH vol estimation (needs 60+ trading days) | Options strike selection uses historical P90 only | ~3 months of trading data |
| 68 | value_overlay connector (weight = 0) | Runs but contributes nothing to scores | Remove or assign weight when value strategy is designed |

---

## DAILY OPERATING RHYTHM

| Time (ET) | Action | Command |
|---|---|---|
| 08:00 | Generate social prompt, paste into Grok, save output | `aeternus social-prompt` |
| 08:30 | Run full pipeline | `aeternus workflow-run --mode auto --profile daily` |
| 09:30 | Review morning brief | `aeternus brief` |
| 15:45 | Check overnight CC overlay (if applicable) | Display-only |
| 16:00 | Check options rolls | `aeternus roll-check` |
| 16:30 | Run exit management | `aeternus manage-exits` |
| Monday | Run hindsight for last week's source date | `aeternus hindsight YYYY-MM-DD` |

---

## QUICK HEALTH CHECK (Copy-Paste Block)

Run this entire block to get a snapshot:

```bash
echo "=== AKG ===" && \
python3 -c "import json; d=json.load(open('eval_results/control/knowledge_graph.json')); nodes=[v for v in d['nodes'].values() if v.get('node_type')=='company']; scored=[n for n in nodes if n.get('pipeline_scored_at')]; hw=[n for n in nodes if n.get('outcome_weight',1.0)!=1.0]; print(f'{len(nodes)} companies, {len(scored)} scored, {len(hw)} with Hebbian adjustment')" && \
echo "=== POSITIONS ===" && \
python3 -c "import json; p=json.load(open('eval_results/paper_execution/positions.json')); print(len(p.get('open_positions',{})), 'open positions')" && \
echo "=== CLOSED TRADES ===" && \
python3 -c "import json; t=json.load(open('eval_results/paper_execution/track_record.json')); closed=[x for x in t.get('trades',[]) if x.get('status')=='CLOSED']; print(len(closed), 'closed trades')" && \
echo "=== LAST SCOUT HANDOFF ===" && \
ls -la eval_results/deal_flow/latest_final_dealflow_tickers.json 2>/dev/null || echo "NO SCOUT HANDOFF FOUND" && \
echo "=== SOCIAL CACHE ===" && \
ls eval_results/deal_flow/xai_social_cache_$(date +%Y-%m-%d).json 2>/dev/null && echo "TODAY'S CACHE EXISTS" || echo "NO CACHE FOR TODAY" && \
echo "=== HINDSIGHT CYCLES ===" && \
python3 -c "import sqlite3; c=sqlite3.connect('eval_results/deal_flow/hindsight.db'); print(c.execute('SELECT COUNT(*) FROM hindsight_cycles').fetchone()[0], 'cycles')" 2>/dev/null || echo "0 cycles (DB not yet created)" && \
echo "=== IC WEIGHTS ===" && \
ls eval_results/control/ic_signal_weights.json 2>/dev/null && echo "IC WEIGHTS FILE EXISTS" || echo "NOT YET (need 10+ cycles)" && \
echo "=== LLM PROVIDER ===" && \
echo "Provider: ${AETERNUS_LLM_PROVIDER:-NOT_SET}"
```

---

*Last updated: 2026-03-05*
*Covers: Universe → Signals → Scoring → Ranking → Analysis → Plan → Execute → Learn → Brief*
