# System Loop Audit — March 2026

> Every prompt and response in this audit is recorded here in sequence.
> Nothing lives only in conversation context.

---

## Audit Context

**Date started:** 2026-03-02
**Triggered by:** Architectural confusion — scouts vs connectors conflated, emergence tiers disconnected from pipeline, pipeline never writes back to AKG. Things are "all over the place."

**Goal:** Step-by-step audit of every piece of the system loop before implementing any fixes.

---

## Pre-Audit Findings (from initial scout/connector inventory)

**Scouts (7)** — broad-net, scheduler-driven, designed to write TO AKG:
1. `cashtag_enricher` — enriches top-centrality nodes via xAI x_search. WRITES to AKG (velocity/sentiment/emergence tiers). 4h schedule.
2. `theme_scanner` — evaluates AKG theme nodes via xAI. WRITES to AKG (activates/deactivates themes/sectors). Weekly schedule.
3. `sector_scout` — sweeps active sectors for new tickers via xAI. WRITES to AKG (flags outlier nodes). 20h schedule. Disabled by default.
4. `commodity_shock_scout` — scans geopolitical clusters for commodity positioning. WRITES to AKG (causal events). Daily.
5. `dod_contract_scout` — scans USASpending.gov for defense contract spikes. WRITES to AKG (causal events). Daily.
6. `breakout_scanner` — scans hardcoded 90-symbol watchlist for 52-week breakouts. Does NOT write to AKG.
7. `iv_scanner` — scans ~100 tickers for IV divergence around earnings. Does NOT write to AKG.

**Connectors (14)** — deep-signal, pipeline-driven, run on pre-selected universe:
`cashtag_stream`, `price_momentum`, `macro`, `smart_money`, `sec_catalyst`, `sector_rotation`, `social_news`, `finviz`, `causal_chain`, `forward_earnings`, `earnings_catalyst`, `insider_cluster`, `value_overlay`, `x_social` (retired)

**Three Critical Breaks Identified:**
1. `record_pipeline_score()` — exists in AKG, has ZERO callers. Pipeline never writes scores back.
2. `get_emerging_planets()` — exists in AKG, never called. Pipeline uses raw centrality gate instead.
3. `cashtag_enricher` (main tier-progression driver) — has 3 blockers: active-sector circular dependency, no scheduler, wrong model name. All 784 nodes stuck at DARK.

---

## Audit Steps (sequential — each prompt/response pair recorded below)

### Step 1: Seed AKG with Full Universe

**Prompt:** Filling up the AKG is step 1. Give me instructions to tell Sonnet to do in another session.

**Response:** Task spec written to `tasks/queue/S-075-seed-akg-full-universe.md`. Sources: S&P500 (wikipedia), full NASDAQ (public API/CSV), Russell 2000 (iShares IWM holdings CSV), Dow 30 (static), ARKK+ARKG (ARK daily CSV), sector ETF holdings (yfinance per ETF), sector+EM+commodity ETF tickers (static), growth watchlist (user-maintained JSON). Expected outcome: AKG grows from ~784 to ~5,000–6,000 company nodes, all DARK, with `metadata.seed_sources` tracking origin. Pipeline behavior unchanged — Opus modifies the gate after this lands.

**Status:** DONE. Sonnet implemented. Opus verified: 10/10 tests passing (one test mock mismatch fixed by Opus). Files created: `universe_seeder.py`, `cli/commands/universe_seeder.py`, `eval_results/control/growth_watchlist.json`, `tests/test_universe_seeder.py`.

---

### Step 2: Audit All Scouts

**Prompt:** Let's now look at all the scouts one by one. How many do we have?

**Response:** Seven scouts identified:

| # | Scout | File | Writes to AKG? | Status |
|---|---|---|---|---|
| 1 | Cashtag Enricher | `sources/cashtag_enricher.py` | Yes — velocity, sentiment, emergence tiers | Needs X_BEARER_TOKEN (frozen) |
| 2 | Theme Scanner | `sources/theme_scanner.py` | Yes — activates/deactivates themes & sectors | Weekly schedule, uses xAI |
| 3 | Sector Scout | `sources/sector_scout.py` | Yes — flags outlier nodes | Disabled by default, uses xAI |
| 4 | Commodity Shock Scout | `sources/commodity_shock_scout.py` | Yes — writes causal events | Daily schedule |
| 5 | DoD Contract Scout | `sources/dod_contract_scout.py` | Yes — writes causal events | Daily schedule |
| 6 | Breakout Scanner | `sources/breakout_scanner.py` | No | Hardcoded 90-symbol watchlist |
| 7 | IV Scanner | `sources/iv_scanner.py` | No | Hardcoded ~100 tickers |

5 write to AKG, 2 don't.

**CORRECTION:** Original table listed Cashtag Enricher as "Needs X_BEARER_TOKEN" — WRONG. It uses `XAI_API_KEY` with xAI `x_search`. The X_BEARER_TOKEN issue is `cashtag_stream.py` (a connector, not a scout).

---

### Step 2a: Cashtag Enricher Deep Dive

**Prompt:** What does Cashtag Enricher do? Why does it use X_BEARER_TOKEN instead of xAI API?

**Response:** Correction issued — enricher uses `XAI_API_KEY` + xAI `x_search`, NOT X_BEARER_TOKEN. That was my error.

**What it does:**
1. Gets top-N AKG nodes by centrality (default 50)
2. Filters to active sectors only — bails if none active
3. Skips nodes enriched within 4h TTL
4. Calls xAI x_search per symbol: gets velocity_z, mentions_7d, velocity_trend, sentiment
5. Writes to AKG via `enrich_node_cashtag()`
6. Recomputes all emergence scores — THIS is what promotes DARK → HABITABLE

**Three blockers preventing it from running:**
1. **Active-sector gate:** Depends on Theme Scanner having activated sectors. If Theme Scanner never ran → no active sectors → enricher bails immediately. Circular dependency.
2. **No scheduler running it:** Designed for 4h schedule, but nothing triggers it.
3. **Wrong model name:** Default `grok-4-1-fast-non-reasoning` is not a valid xAI model. Should be `grok-4-1-fast-reasoning`. Would silently fail on every call.

**Cost:** ~50 symbols × $0.005/x_search = ~$0.25 per run.

---

### Step 2b: Do we have a broad X feed scanner?

**Prompt:** Do we have a scout that scans the entire finance X feed for tickers, analysis, and what is being talked about the most?

**Response:** No. Nothing in the codebase does broad X feed discovery.

**What exists (and why it's not the same thing):**
- `cashtag_stream.py` — CONNECTOR, not scout. Queries specific handles about specific tickers from our existing universe. Needs X_BEARER_TOKEN (direct Twitter API). Narrow — only finds what we already know to look for.
- `cashtag_enricher.py` — SCOUT but not discovery. Enriches existing AKG nodes with xAI x_search. Only works on nodes already in AKG.
- `sector_scout.py` — Closest thing. Uses xAI x_search by sector. But gated behind active sectors (Theme Scanner dependency), disabled by default.

**What's missing:** A wide-net discovery scout that asks xAI x_search:
> "What stock tickers are getting the most unusual mention volume on X in the last 24 hours?"

One call = $0.005. Returns actual trending cashtags from real X feed. Those tickers get written to AKG — lighting up existing DARK nodes or creating new ones. This is the fundamental discovery mechanism that feeds the entire emergence tier system.

**Status:** DONE. Sonnet implemented. Opus verified: 8/8 tests passing. Smart deviation: consolidated 3 x_search calls into 1 unified prompt (cost $0.005/run instead of $0.015). Files created: `x_feed_scout.py`, `cli/commands/x_feed_scout.py`, `tests/test_x_feed_scout.py`. Config keys added to `default_config.py`. CLI wired in `main.py`.

---

### Step 3: X Feed Scout → AKG Data Gap

**Prompt:** Confirm X Feed Discovery Scout is connected to AKG and what it does with the info.

**Response:** Scout IS connected to AKG. It calls `add_node()` for new tickers and `update_node_field()` for all tickers. But there is a **critical data gap**:

**What the scout writes:**
- `x_trending_at` (timestamp)
- `x_trending_mentions` (int)
- `x_trending_context` (string)

**What the emergence formula reads** (`compute_emergence_score`, line 837):
- `centrality` (40%) — graph structure
- `cashtag_velocity_z` (40%) — **only written by cashtag_enricher**
- `cashtag_sentiment` (20%) — **only written by cashtag_enricher**

**The scout's fields (`x_trending_*`) are dead data.** Nothing reads them. The emergence formula ignores them entirely. So the scout adds nodes to AKG but cannot move them through tiers.

**Decision: DELETE cashtag_enricher from the loop. Upgrade x_feed_scout to write emergence-relevant fields.**

| | X Feed Scout (current) | Cashtag Enricher (broken) |
|---|---|---|
| Calls per run | 1 | 50 |
| Cost per run | $0.005 | $0.25 |
| Status | Working | 3 blockers |
| Writes emergence fields? | No (dead data) | Yes (but never runs) |

**Fix:** Modify x_feed_scout to:
1. Ask xAI for `sentiment` (-1 to +1) per ticker in the JSON response
2. Compute `velocity_z` from `mentions_estimate` using batch z-score
3. Write `cashtag_velocity_z` and `cashtag_sentiment` to AKG nodes
4. Emergence tiers actually progress — $0.005 per run, zero blockers

Cashtag enricher becomes redundant. 50x cheaper. Same outcome.

---

## Master Checklist — All Audit Tasks

> Every task from this audit, tracked to completion. Nothing gets lost.

### Seeding & Discovery (populate AKG with the full universe)

- [x] **S-075: Seed AKG with full universe** — S&P500 + NASDAQ + R2000 + Dow + ARK + ETFs + growth watchlist → ~5,000-6,000 company nodes. Sonnet built, Opus verified (10/10 tests). DONE.
- [x] **S-076: X Feed Discovery Scout** — broad-net scout scanning financial X for trending cashtags via xAI x_search. Writes new/updated nodes to AKG. Sonnet built, Opus verified (8/8 tests). Consolidated to 1 call ($0.005/run). DONE.

### Scout Audit (7 scouts — verify each works or document what's broken)

- [x] **Audit: Cashtag Enricher** — Deep dive complete. 3 blockers, $0.25/run, writes the only fields emergence reads. **VERDICT: DELETE from loop.** Upgrade x_feed_scout to write emergence fields instead ($0.005/run, zero blockers).
- [x] **Audit: Theme Scanner** — Broken: wrong model name, wrong API pattern, depends on pre-seeded theme nodes nobody creates. **VERDICT: Merged into X Feed Scout.** Scout now discovers themes + sectors in same $0.005 call. Theme Scanner is dead code. 16/16 tests.
- [x] **Audit: Sector Scout** — Wrong model name (`grok-4-1-fast-non-reasoning`), expensive (1 xAI call PER sector), redundant with X Feed Scout. Only unique value: dormant-sector outlier detection (pure AKG graph query, zero API cost). **VERDICT: Extracted `_detect_dormant_sector_outliers()` into X Feed Scout, deleted rest.** 17/17 tests.
- [x] **Audit: Commodity Shock Scout** — Logic clean ($0.00/run, yfinance). **BUG FOUND & FIXED:** `akg=None` default meant CLI and scheduler never wrote events to AKG. Fix: auto-load AKG internally when not passed. Added `akg.save()`. 9/9 tests.
- [x] **Audit: DoD Contract Scout** — Logic clean ($0.00/run, USASpending API). **Same `akg=None` bug, FIXED.** Auto-load + save. 7/7 tests.
- [x] **Audit: Breakout Scanner** — Wired in pipeline (line 113). Reads AKG (centrality ≥ 0.05), writes via `enrich_node_breakout()`, saves AKG. DONE.
- [x] **Audit: IV Scanner** — Wired in pipeline (after breakout). Reads AKG (sp500/dow seed_sources), writes via `enrich_node_iv()`, saves AKG. `BASE_UNIVERSE` deleted, 503 tickers from AKG. 6/6 tests. DONE.

### Connector Audit (14 connectors — verify each is wired correctly)

- [x] **Audit: All 14 connectors** (2026-03-03)

#### Healthy Connectors (no action needed)

| Connector | Family | Data Source | Cost | Notes |
|---|---|---|---|---|
| price_momentum | `price_momentum` | yfinance OHLCV 380d | Free | Solid. 30-symbol batches. |
| macro | `macro_regime_fit` | yfinance (SPY,QQQ,TLT,UUP,DBC) | Free | Coarse (SMA20 deviation, evidence=4 hard-coded). Functional. |
| sector_rotation | `sector_rotation` | yfinance (14 sector ETFs) | Free | Solid. Unknown sectors get neutral 50 (inflates evidence slightly). |

#### Working But With Issues

| Connector | Family | Issue | Severity |
|---|---|---|---|
| smart_money | `smart_money` | Only 4 hard-coded managers (BRK,BW,Soros,Scion). Fuzzy name matching risk on short names. | LOW |
| social_news | `social_momentum` + `news_catalyst` | xAI/Grok cache-first. Symbols with no xAI data emit NO_DATA signals. Reddit removed March 2026. | LOW |
| cashtag_stream | `cashtag_momentum` | NOT_CONFIGURED (no X_BEARER_TOKEN). Runs TWICE per pipeline (pre+post universe expansion) — doubles cost when configured. LLM rate-limit flag not thread-safe. | LOW (not configured) |
| causal_chain | `causal_chain` | Uses `AeternusKnowledgeGraph()` not `.load()` — reads empty graph. Evidence=hop_distance (semantic mismatch). | MEDIUM |
| finviz_insider | `smart_money` | Uses `AeternusKnowledgeGraph()` not `.load()` for insider alpha lookup. Duplicate family with smart_money.py. | LOW |
| finviz_sector | `sector_rotation` | Duplicate family with sector_rotation.py. Only 3-tier scoring (72/50/30) — very coarse. | LOW |

#### Dead Weight / Broken

| Connector | Family | Issue | Severity | Action |
|---|---|---|---|---|
| value_overlay | `value_overlay` | Weight = 0 in CORE_SCORE_WEIGHTS. Serial `yf.Ticker().info` per symbol — SLOWEST connector by far on 5K universe. | HIGH | **Remove from pipeline tasks** or disable by config |
| earnings_catalyst | `earnings_catalyst` | Family NOT in CORE_SCORE_WEIGHTS — signals emitted but have zero scoring impact. Reads `akg._edges` (private attribute). | MEDIUM | Wire into scoring or remove |
| forward_earnings | `forward_earnings_anticipation` | Family NOT in CORE_SCORE_WEIGHTS — same zero-impact issue. | MEDIUM | Wire into scoring or remove |
| insider_cluster | `insider_cluster` | EDGAR URL construction malformed (`CIK{cik}/0{accession}.json` — wrong path). Serial `yf.Ticker().info` for market cap (25-100s latency). Likely returns 0 signals in practice. | HIGH | Fix EDGAR fetch or replace |
| x_social | `social_momentum` | Disabled by default (`dealflow_use_symbol_x=False`). Duplicate family with social_news. $1/call. | LOW | Correct as-is (disabled) |

#### Orphaned (not in pipeline.py at all)

| File | What it does | Status |
|---|---|---|
| sec_catalyst.py | 8-K EDGAR + Form 4 + supply chain propagation | NOT imported, NOT in `__init__.py`. Completely dead code. |

#### Non-Signal Writers (wired in pipeline but not via connector tasks)

| Writer | Wired | Writes AKG | Issue |
|---|---|---|---|
| breakout_scanner | Yes (line 112) | Yes | Healthy. Now includes ATMOSPHERE/HABITABLE nodes. |
| iv_scanner | Yes (line 122) | Yes | **force_queue output is silently discarded** — results fetched and printed but never fed into signals list. Dead output. |

#### Duplicate Signal Families (same family from multiple connectors)

- `smart_money`: smart_money.py (SEC 13F) + finviz_connector.py (finviz insider)
- `sector_rotation`: sector_rotation.py (ETF model) + finviz_connector.py (finviz weekly perf)
- `social_momentum`: social_news.py (xAI/Grok cache-first)

Scoring's `_best_signal_per_symbol_family()` picks the highest-scoring signal per family per symbol — so duplicates don't double-count, but the weaker connector's work is wasted.

#### Critical Findings Requiring Fixes

| # | Finding | Files | Priority |
|---|---|---|---|
| C-1 | value_overlay runs but weight=0. Serial yf.Ticker().info on 5K universe = hours of latency for zero scoring impact. | pipeline.py, value_overlay.py | P0 — remove from pipeline |
| C-2 | insider_cluster EDGAR fetch URL is malformed. Likely 0 signals in production. | insider_cluster.py | P1 — fix or disable |
| C-3 | iv_scanner force_queue silently discarded — candidates never reach scoring. | pipeline.py | P1 — wire into signals |
| C-4 | causal_chain uses `AeternusKnowledgeGraph()` not `.load()` — reads empty graph. | causal_chain.py | P1 — fix to `.load()` |
| C-5 | earnings_catalyst + forward_earnings families not in CORE_SCORE_WEIGHTS — dead signals. | scoring.py | P2 — add weights or remove |
| C-6 | social_news silently skips symbols with no data (no NO_DATA signal) — coverage gap. | social_news.py | P2 |
| C-7 | sec_catalyst.py completely orphaned — dead code. | sources/sec_catalyst.py | P3 — delete or wire |

### Pipeline Wiring (the critical loop that's broken)

- [x] **S-077: Upgrade x_feed_scout to write emergence fields** — Sentiment in prompt, batch velocity_z, calls `enrich_node_cashtag()`. Sonnet built, Opus verified (12/12 tests). DONE.
- [x] **Retire cashtag_enricher** — Superseded by x_feed_scout. File kept as dead code.

#### GAP 1: Score writeback is broken — `record_pipeline_score()` has zero callers

- [x] **Fix D: CLI score writeback to AKG** (2026-03-03)
- [x] **Fix E: Engine score writeback to AKG (trading_graph.py)** (2026-03-03)

`record_pipeline_score()` (knowledge_graph.py:1293) and `record_rating()` (knowledge_graph.py:1299) exist but are never called from the analysis pipeline. `trading_graph.py` — the engine running `propagate(ticker, date)` — has zero references to either method. Analysis produces a score, writes it to `results/<ticker>/<date>/`... and the AKG never learns about it.

The CLI (`scoring.py`) does call `record_rating()` at lines 434 and 606, but with a fatal bug: it does `akg = AeternusKnowledgeGraph()` (fresh empty graph) instead of `AeternusKnowledgeGraph.load()`, and never calls `akg.save()`. The writeback writes to a throwaway in-memory object that gets garbage collected.

**Impact:** Nodes never reach SCORED tier. AKG can't distinguish "already analyzed" from "never seen." Pipeline could re-analyze the same ticker every day.

**Fix D (CLI writeback — DONE 2026-03-03):** `scoring.py` lines 432-436 and 604-608 — changed `AeternusKnowledgeGraph()` to `.load()` + added `.save()`. Both `analyze` and `score` commands now persist ratings. 1870 tests pass.

**Fix E (Engine writeback — DONE 2026-03-03):** `trading_graph.py` line 440-447 — added `AeternusKnowledgeGraph.load()` → `record_rating()` → `save()` after `aeternus_scorer.score()` completes. Wrapped in try/except with logger.warning. Same pattern as CLI Fix D. Both `analyze` (CLI) and `analyze-batch` (engine) paths now write ratings to AKG. 168 KG tests pass, import clean.

#### GAP 2: Emergence tier system is write-only — `get_emerging_planets()` never called

- [x] **Fix: Pipeline reads emergence tiers as a signal family** (2026-03-03)

`get_emerging_planets()` (knowledge_graph.py:972) was designed to be the bridge between scouts enriching nodes and the pipeline picking them up. It filters by emergence tier (ATMOSPHERE/HABITABLE), excludes already-scored nodes, and returns best candidates sorted by emergence_score.

Nobody calls it. The breakout scanner — the only scanner that reads from AKG — uses a raw centrality gate:
```python
# breakout_scanner.py:39
float(n.get("centrality") or 0) >= 0.05
```

Centrality is a static graph-structure metric (how connected a node is). It never changes when scouts enrich nodes. So the breakout scanner scans the same ~500 high-centrality nodes every time, regardless of what X Feed Scout, IV Scanner, or Commodity Shock Scout discovered.

**Impact:** The entire emergence tier system (DARK → ROCKY → ATMOSPHERE → HABITABLE → SCORED) is write-only. Scouts write enrichment, emergence scores compute, tiers progress — and nothing downstream reads them.

**Fix scope:** Breakout scanner and/or pipeline should call `get_emerging_planets()` (or at least filter by tier) to prioritize nodes that scouts have lit up with signals.

**Fix design (2026-03-03):** Make emergence a first-class signal family. Three files:

1. **`breakout_scanner.py`** — `_get_scan_universe()` adds ATMOSPHERE/HABITABLE nodes alongside centrality filter. Breakout scanner now discovers patterns in emerging tickers, not just well-connected ones.
2. **`pipeline.py`** — After connectors run and before `score_candidates()`, call `get_emerging_planets()` and inject synthetic emergence signals. Each ATMOSPHERE/HABITABLE node gets an `emergence` signal with `raw_score = emergence_score * 100`, `evidence_count = 2`.
3. **`scoring.py`** — Add `"emergence"` to GATING_FAMILIES, CORE_SIGNAL_FAMILIES, CORE_SCORE_WEIGHTS (7% weight, same as breakout_discovery). Emergence counts toward the ≥3 signal families gate.

**Effect:** A HABITABLE ticker with emergence_score=0.6 gets a 60.0 emergence signal. Combined with even 2 other signal families, it passes the evidence gate. Scouts write → tiers progress → pipeline reads tiers as signals → ranking considers them. The loop closes.

#### GAP 3: No end-to-end loop test

- [x] **Write end-to-end loop integration test** (2026-03-03)

Each piece passes its own tests individually (seeder: 10/10, x_feed: 12/12, breakout: integrated, IV: 6/6, emergence: tested, `get_emerging_planets`: tested). But no test validates the chain is connected:

```
seed node → scout enrichment → emergence_score computed → tier progresses
  → pipeline reads HABITABLE → analysis runs → score written back → tier = SCORED
```

Gaps 1 and 2 prove the chain isn't connected. An integration test with mocked data that walks a single ticker through all stages would catch this class of bug permanently.

**Fix scope:** Single test file, ~100 lines. Mock data, no API calls. Creates node, enriches with scout data, verifies tier progression, simulates pipeline read via `get_emerging_planets()`, simulates score writeback via `record_rating()`, verifies SCORED tier.

### Verification (post-fix)

- [ ] **Run `aeternus akg-seed`** — Seed AKG with full universe (live execution).
- [ ] **Run `aeternus x-discover --dry-run`** — Verify X feed scout works.
- [x] **End-to-end loop test** — `test_emergence_loop.py` 4/4 pass. DONE.

---

## Status Summary (as of 2026-03-03)

### Completed

| Item | Status |
|---|---|
| Scout audit (7 scouts) | DONE — all AKG-integrated |
| Connector audit (14 connectors) | DONE — 7 critical findings |
| Gap 1: Score writeback | DONE — Fix D (CLI) + Fix E (engine) |
| Gap 2: Emergence reader | DONE — emergence signal family (7% weight) |
| Gap 3: Loop test | DONE — 4/4 tests pass |

### Open — Connector Fixes (from audit)

| # | Finding | Priority | Status |
|---|---|---|---|
| C-1 | value_overlay: weight=0, serial yf.info on 5K universe = hours latency for nothing | P0 | [x] Removed from pipeline (Sonnet) |
| C-2 | insider_cluster: EDGAR URL correct but Form 4 parsing + serial yf.info broken | P1 | [ ] Needs deeper rewrite — deferred |
| C-3 | iv_scanner: force_queue silently discarded, never reaches scoring | P1 | [x] S-083: force_queue → iv_divergence signals, weight 0.0 (observability) |
| C-4 | causal_chain: `AeternusKnowledgeGraph()` not `.load()` — reads empty graph | P1 | [x] Fixed in causal_chain + 3 siblings (earnings_catalyst, forward_earnings, finviz) |
| C-5 | earnings_catalyst + forward_earnings: families not in CORE_SCORE_WEIGHTS — dead signals | P2 | [x] S-084 Phase 1: added at weight 0.0. Phase 2 blocked on hindsight IC. |
| C-6 | social_news: silently skips symbols with no data (no NO_DATA signal) | P2 | [x] Fixed: emit NO_DATA signals for both families instead of silent `continue` |
| C-7 | sec_catalyst.py: completely orphaned dead code | P3 | [x] Deleted (Sonnet, commit ac24e9f6) |

### Ranking Audit (2026-03-03)

Applied Elon's 5-step algorithm + Karpathy guidelines to `ranking.py` (191 lines).

| # | Finding | Priority | Fix |
|---|---|---|---|
| R-1 | `_lane_rank_score` returns `core_score` for CORE (IC=-0.52) — fallback + hedge eviction sort by worst-performers-first | P0 | Fixed: returns `momentum_score` for CORE, `asymmetry_score` for MOMENTUM |
| R-2 | `max_asset_class_count=8` caps shortlist at ~15 on 5K universe (97% Equity) | P0 | Fixed: removed parameter entirely. Macro hedge minimum already ensures non-Equity diversity. |
| R-3 | Config divergence — `max_sector_count` hardcoded default, not in config, not passed from pipeline | P1 | Fixed: added `dealflow_max_sector_count` to config, pipeline passes it. |
| R-4 | Function defaults (12/8) don't match config (18/12) | P2 | Fixed: aligned to 18/12. |
| R-5 | `DealFlowSignal.signal_family` missing 4 families | P3 | Fixed: added emergence, causal_chain, earnings_catalyst, forward_earnings_anticipation. |

**Files changed:** `ranking.py` (191→174 lines), `default_config.py`, `pipeline.py`, `contracts.py`
**Tests:** 14/14 momentum + 4/4 emergence = 18/18 pass.

### Open — Verification

| Item | Status |
|---|---|
| Run `aeternus akg-seed` (live) | [ ] |
| Run `aeternus x-discover --dry-run` | [ ] |

---

