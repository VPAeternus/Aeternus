# LONG-TERM MEMORY

> Curated knowledge, architectural decisions, and persistent facts about the Aeternus project.

---

## Fundamental Scoring Input Contract

Permanent contract: `tradingagents/research/fundamental/docs/scoring_input_contract.md` defines required data sources for correct daily fundamental scoring. Use it before judging readiness or final publish. Key rule: required base-score rows need quarterly filing text, Companyfacts/XBRL financials, filing/signal date, and entry price. Official Tier 1-4 LLM / Top 10 + Plus 5 eligibility requires fresh earnings evidence: press release exhibit or primary earnings 8-K. Main LLM extraction packets must include only press-release/8-K evidence, not 10-Q/10-K text. Quarterly filing alone is not enough for high-conviction LLM selection. Daily SEC orchestration must loop fetch/coverage until the fetch queue is empty, because one pass can reveal the next required layer. For `2026Q2` final selection, `2026Q1` prior-quarter context is required for QoQ fields used by HP/RM/shadow-refill logic. Never make the user remember these rules; check the contract before readiness claims.

## Persistent Communication Preference

- Use operator/plain-English language first, especially in live step-by-step workflows.
- Use simple, understandable English going forward. Avoid technical jargon unless the user asks for it.
- When an internal term is unavoidable, define it first in one plain sentence before using it.
- Do not lead with CLI flags, file internals, implementation jargon, or technical mechanics unless the user asks for exact commands.
- Next-step answers should use this default shape: "Next step in plain English:" followed by 1-3 short bullets with business action and reason.
- Use user-facing terms: "main list" not "current universe", "comparison data" not "context names", "ready for LLM" not "eligible packets".
- Next-step answers should say: action, why it matters, expected result. Keep command syntax out of the main answer unless explicitly requested.

## Project Identity

**Name**: Aeternus Platform  
**Type**: AI-Powered Investment Research & Ratings Platform  
**Framework**: TradingAgents (Multi-Agent LLM Framework)

---

## Core Architecture

### TradingAgents Framework
```
CLI → TradingAgentsGraph → Analysts → Researchers → Trader → Risk → PM
                        ↓
                   AeternusScorer → AeternusRating → TrackRecord
```

### Agent Types
1. **Analysts** (parallel): Market, Social, News, Fundamentals
2. **Researchers** (debate): Bullish vs Bearish structured debate
3. **Trader**: Aggregates signals, generates recommendations
4. **Risk Management**: VaR, liquidity, stop-loss validation
5. **Portfolio Manager**: Final approval/rejection

### Aeternus Score Formula
```
AETERNUS_SCORE = (fundamental × 0.30) + (technical × 0.25) + 
                 (macro × 0.20) + (sentiment × 0.15) + (momentum × 0.10)
```

### Rating Thresholds
| Score Range | Rating |
|------------|--------|
| 80-100 | Strong Buy |
| 60-79 | Buy |
| 40-59 | Hold |
| 20-39 | Sell |
| 0-19 | Strong Sell |

---

## Platform Vision (5 Pillars)

1. **Research Engine** - Proprietary scoring, multi-dimensional analysis ⭐ ACTIVE
2. **Index Builder** - Custom index creation, NAV calculation
3. **Ratings System** - Track record transparency, confidence scoring ⭐ ACTIVE
4. **Social Layer** - User profiles, following, discussions
5. **Performance Tracking** - Historical performance, benchmarks

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Workspace | `AeternusAgentsAG` / `AeternusAgents` | Hyphenated version is the active install path; Synced both. |
| Architecture | 4-Phase Research Depth | Incremental build-out of core scoring pillar |
| CLI Framework | Typer + Rich | Modern Python CLI with beautiful output |
| LLM Orchestration | LangGraph | Reliable agent workflows |
| Rating Storage | JSON files | Simple, portable, no DB dependency |
| Test Framework | pytest | Standard Python testing |
| Model Stack | Grok 4.1 + Gemini 3 + Claude 3.5 | SOTA model mixture via Native APIs & OpenRouter |
| Stability | Fault-Tolerant Tooling | Robust `yfinance` & Alpha Vantage fallback logic |
| Embeddings | Smart Provider Selection | Auto-switches to Google/Ollama if xAI (no-embed) is active |
| Reporting | Markdown + JSON | Structured `Equity_Research_Report.md` & full JSON trace |
| **Trust Engine** | **Immutable Audit Trail** | UUID-based rating identity + append-only event log (`audit.py`) |
| **Verification** | **CLI Dashboard** | `track-record` and `performance` commands for transparency |
| **Thesis Validation** | **Analyze-Only Daily Comparator** | LLM comparator answers whether daily data changes the current thesis (`thesis_check.py`) |
| **Confidence Model** | **Deterministic Weighted Factors (1-5)** | Data quality + thesis clarity + catalyst proximity + historical accuracy |
| **Hedging Engine** | **Beta+VaR + Adaptive Regime Overlay** | Deterministic SPY/VIX regime overlay with crash gating and audit logging (`hedging.py`, `market_regime.py`) |
| **Deal Flow Intake** | **Top-20 Ranked Fundamental Review List** | Deterministic multi-family sourcing pipeline (`dealflow/`) feeds research candidate_list before deep analysis |
| **Smart-Money Source of Truth** | **SEC 13F + Congress Composite** | Live connector combines SEC holdings and Congress trade disclosures into `smart_money` family with graceful fallback statuses |
| **Direct Social Feed** | **X API + Influencer Quality** | Direct X connector weights sentiment by author-quality metrics; token-gated and non-fatal on missing credentials |
| **Opportunity Capture** | **Dual-Lane Selection (Core + Momentum)** | Top-20 selection split (`12 CORE / 8 MOMENTUM`) ensures high-upside trend names are not filtered out by weak valuation overlays |
| **Momentum Calibration** | **Theme-aware lane promotion floor** | Scoring now combines strict/price/theme momentum gates and deterministic lane rebalance to avoid `MOMENTUM=0` candidate_lists under sparse social coverage |
| **Momentum Intelligence** | **Post-First Cashtag Stream** | HYBRID cashtag ingestion (xAI scout + direct X budgeted enrichment) drives `cashtag_momentum` and dynamic universe expansion |
| **Manual X Feed Governance** | **16-pass readiness-gated workflow preflight** | Manual X/social ingestion is now explicitly treated as a 16-pass operator workflow (`x-feed`) after adding the blindspot/unmapped-ticker audit pass. `workflow-run --mode manual` blocks with `BLOCKED_MANUAL_X_FEED` until all passes are archived and merged X-feed data exists, preventing fallback into unintended automatic social/news ingestion during manual-mode runs. |
| **Deal Flow Cadence** | **Scheduler Policy (Daily + Event Cooldown)** | `DealFlowScheduler` runs pre-open daily and event-triggered refresh with cooldown + persisted state |
| **Connector Observability** | **Per-Run Telemetry Artifact** | Deal Flow pipeline records connector latency/status/coverage into `connector_health.json` and exposes `connector_health_summary` in candidate_list output |
| **Score Explainability** | **Per-Family Contribution Report** | Pipeline publishes deterministic contribution decomposition (`core`, `momentum`, `asymmetry`) in `family_contributions.json` for each candidate_list run |
| **Batch Attribution** | **Lane + Playbook Outcome Breakdown** | `retired post-scout batch command` emits recommendation/score attribution by lane (`CORE`/`MOMENTUM`) and playbook from per-symbol `analysis_report.json` |
| **Realized Attribution** | **5d/20d horizon edge tracking** | `retired post-scout batch command` now appends realized horizon metrics (return, benchmark return, edge, strategy edge) and aggregates by lane/playbook for post-analysis selection quality monitoring |
| **Signal Attribution** | **Dominant-family edge accounting** | `retired post-scout batch command` now maps each queue item to dominant signal families from dealflow subscores and publishes by-family horizon attribution (`by_signal_family`, `signal_family_counts`) |
| **Sector Canonicalization** | **Static + profile + cache + symbol normalization** | Deal Flow universe now resolves sectors through deterministic baseline, yfinance profile, and persisted cache keyed by normalized symbols; queue items now persist explicit `sector` plus queue-level `canonical_sector_map` |
| **Analyze Sector Fallback** | **Ticker-normalized sector context fallback chain** | `sector_context.py` now normalizes ticker variants and falls back to dealflow baseline + sector cache when yfinance sector metadata is missing, preventing `Unknown` sectors in Aeternus scoring output |
| **House Feed Automation** | **Scheduler-driven PTR refresh + runtime URL wiring** | `DealFlowScheduler` now runs configurable House PTR refresh via `house_feed.py`, mirrors primary/fallback artifacts, and injects generated local source paths for congress ingestion when URLs are unset |
| **Local Congress Source Support** | **HTTP + file path compatible connectors** | Smart-money source loader now accepts `file://` and plain local JSON paths for Senate/House feeds, enabling local primary/fallback validation without external hosting |
| **Manual Idea Overlay** | **Hybrid Merge with slot guarantees** | Deal Flow now merges operator watchlist ideas into Top-20 with deterministic slot policy (`target/min/max`), liquidity + diversification guards, and per-run merge trace (`manual_merge.json`) |
| **Manual Research Priority** | **Manual names forced into fundamental-intake set** | Queue builder now guarantees at least one manual candidate is selected for deep research when manual symbols are present in candidate_list |
| **Manual Inclusion Reliability** | **Low-data and missing-auto manual fallback** | Manual ideas are no longer dropped solely for `LOW_DATA`; when a manual symbol lacks auto candidate coverage, a safe synthesized candidate is created for merge evaluation (still constrained by liquidity/diversification) |
| **Manual Override Policy** | **Force-insert with explicit risk tags** | With `dealflow_manual_force_insert=true`, manual ideas can override diversification/liquidity rejection paths and are tagged (`Manual cap override`, `Manual liquidity override/unchecked`) instead of being silently dropped |
| **X Scope Telemetry** | **Run-level coverage counters** | Cashtag stream now emits scope metadata (`handles`, `symbol_calls`, `expansions`) surfaced in candidate_list JSON and CLI output for budget/coverage diagnostics |
| **Feed Provenance Visibility** | **Source-detail tags in candidate_list/queue** | Deal Flow candidates now expose `source_detail` (`X_FEED`, `WEB_NEWS`, `REDDIT`, `SEC_CONGRESS`, `MANUAL_WATCHLIST`) and CLI tables render a `Source` column for each name |
| **Reddit Live Intake** | **Subreddit-backed social/news augmentation** | `social_news.py` now fetches recent per-symbol posts from configured subreddits (default `wallstreetbets,stocks,investing`) and blends them into social/news evidence and scoring |
| **X Account Discovery** | **Weekly approval-based handle expansion** | `x-discovery` generates ranked non-seed account candidates (`x_account_candidates.json`) using engagement quality, cashtag yield, and downstream edge proxies without auto-follow side effects |
| **Run Cost Control** | **Low-cost default + Max-Recall override** | `source`/`orchestrate` now default to `--profile daily` (LOW_COST), while `--profile max-recall` enables higher-coverage settings; LOW_COST applies stricter X/social/discovery caps for faster routine runs |
| **Provider Throttle Handling** | **Per-method 429 quarantine + fallback continuation** | Dataflow router now disables throttled vendors for the active process after first 429/retry-limit event, so remaining symbols continue on fallback vendors instead of repeatedly hitting the same limit |
| **Batch Vendor Scope** | **xAI-only overrides for non-interactive queue runs** | Queue-driven non-interactive analyze/batch now forces `get_news/get_global_news/get_fundamentals` to xAI when provider is xAI, preventing costly multi-vendor fan-out during backfill and attribution runs |
| **Analyze Loop Guard** | **Tool-iteration cap + payload compaction** | Analyst routing now caps tool-call iterations per stage (`max_tool_iterations_per_analyst`), message resets use neutral placeholder text, and fundamentals tool payloads are compacted to prevent long-horizon stalls |
| **Batch Failure Recovery** | **Cached report fallback (`SUCCESS_CACHED`)** | `retired post-scout batch command` can now reuse existing symbol/date `analysis_report.json` when live execution fails/times out, preserving lane/playbook/signal-family attribution continuity |
| **X Budget Governance** | **Attribution-driven auto tuner with guardrails** | `x_budget.py` computes deterministic X call/budget recommendations from realized by-family attribution (5d/20d), enforces horizon-alignment hold + call/budget clamps, and persists policy artifacts for runtime + audit visibility |
| **Step 1 Readiness Gate** | **Artifact-based go/no-go evaluation** | `readiness.py` + `aeternus step1-readiness` now gate Step 2 transition on deterministic checks: consecutive stable batch cycles, realized attribution sample sufficiency, and connector policy compliance |
| **Congress Feed Resilience** | **Primary + Fallback House URL Chain** | Smart-money source tries Senate + House primary + House fallback URLs with schema/ticker parsing fallbacks |
| **Congress Feed Quality Guard** | **Staleness filter + cross-source dedupe** | Smart-money connector now treats stale House/Senate sources as non-authoritative and dedupes overlapping transactions across Senate/House feeds before scoring |
| **House Feed Bootstrap** | **Official PTR ETL Generator** | `scripts/build_house_ptr_feed.py` creates normalized ticker-level House transactions JSON from House Clerk PTR PDFs for self-hosted primary/fallback URLs |
| **News Fallback Resilience** | **xAI tool-search fallback + vendor prechecks** | `xai.py` now uses xAI Responses API tools (`web_search` + `x_search`) as primary path with chat fallback; `get_news` fallback order prioritizes xAI after Alpha Vantage; interface skips non-configured vendors and reduces repeated fallback noise |
| **Finnhub Utilization** | **Live API-first with cache fallback** | `local.py` now uses live Finnhub endpoints for company news and insider datasets when `FINNHUB_API_KEY` is present, then falls back to file cache |
| **Portfolio Admission Benchmark** | **Conservative V3 hurdle with fail-open missing-proxy policy** | `paper_execution.py` now compares candidate expected-return proxies against the configured V3 benchmark window, blocks only explicit underperformers, and leaves missing-proxy names eligible in v1 with explicit metadata for later tightening |
| **Step 2 Evidence Integrity** | **Read-only all-candidate classification layer** | `evidence_integrity.py` classifies every Step 2 candidate as `CONFIRMED`, `SPARSE_BUT_INTERESTING`, `DATA_DEGRADED`, or `LOW_SIGNAL` using candidate scores, signal statuses, and connector health; persisted as `evidence_integrity.json` without changing the current evidence gate in v1 |
| **Step 2 Evidence Review** | **Summary CLI + cohort scorecards** | Evidence Integrity now mirrors Discovery Delta rollout shape: live CLI summary renders class counts plus top `SPARSE_BUT_INTERESTING` / `DATA_DEGRADED` names, and `hindsight` / `performance_review` now embed `evidence_integrity_cohorts` with baseline and peer comparisons before any Step 2 gate rewrite |
| **Step 3 Candidate List Integrity** | **Read-only candidate_list-boundary artifact** | `candidate_list_integrity.py` now measures the Step 3 cut with `selected_candidate_list`, `near_miss_eligible`, and `legacy_deep_flag`, persists `candidate_list_integrity.json`, and surfaces candidate false negatives without changing ranking behavior |
| **Step 4 Fundamental Intake Integrity** | **Read-only deep-research boundary artifact** | `fundamental_intake_integrity.py` now measures the Step 4 cut with `legacy_deep_flag`, `near_miss_eligible`, and `injected_selected`, persists `fundamental_intake_integrity.json`, and separates auto-selected names from manual / IV / portfolio injections without changing `deep_k` or quota behavior |
| **Step 5 Research Conversion Integrity** | **Read-only research execution / portfolio conversion artifact** | `research_conversion_integrity.py` now measures the Step 5 path from `retired post-scout batch command` into portfolio inclusion, persists `research_conversion_integrity.json`, and separates deep/quick fresh-success, cached, and failed cohorts without changing analysis or portfolio behavior |
| **Industry Disruption First Principles** | **Reusable strategy gate for Zero-to-One company/wedge thinking** | Added `.agents/skills/industry-disruption-first-principles/SKILL.md` plus an Aeternus worked example and memo so future strategy discussions are forced through immutable truths, inherited infrastructure, incumbent waste, wedge, scorecard, and platform-expansion analysis |
| **Autoresearch Decision Gate** | **Reusable optimization gate for brute force vs deterministic search vs autoresearch** | Added `.agents/skills/autoresearch-decision-gate/SKILL.md` plus examples so future optimization work must define the metric, cheapest trustworthy evaluator, search-surface size, best tool, and promotion ladder before any agent-led tuning begins. The hard rule is: tiny enumerable spaces should be brute-forced, not autoresearched. |
| **Aeternus Operating System Thesis** | **Canonical strategic framing for the company** | `docs/research/aeternus-operating-system-thesis.md` is now the easy-access strategic memo: Aeternus is a capital allocation operating system whose edge is faster verified learning, and roadmap items should be judged by whether they improve that loop |
| **Fundamental Pillar Autoresearch Harness** | **Point-in-time sidecar truth engine for the fundamental pillar** | The fundamental pillar should be optimized through a filing-effective deterministic harness, not day-by-day LLM replay. v1 starts at `2009+`, uses structured SEC/XBRL snapshots, evaluates sector-neutral `60d` rank IC, and remains sidecar-only until data hygiene and predictive value are proven. The harness now includes a cache-first SEC layer (`sec_fetch.py` + `prepare.py`) with raw `submissions` / `companyfacts` JSON caching, SEC-official ticker→CIK resolution via `company_tickers.json` with cached SEC fallback only, prepared dataset persistence, and thin CLI commands for cache fill and prep. Reusable SEC acceleration logic must live under `tradingagents/research/fundamental/src/sec_pipeline/`; run-folder `eval_results/fundamental/*/sec_*.py` files are audit wrappers only and must be paired with reproducibility/cleanup manifests. |
| **Fundamental Baseline Comparison** | **Fixed named strategy suite before search/autoresearch** | The fundamental harness now treats baseline comparison as a mandatory gate before any search loop. On the first real `2009+` `large_cap_v1` historical dataset, `health_only` is the only positive baseline (`+0.043759` sector-neutral `60d` rank IC), while the naive `baseline_v1` composite is negative (`-0.055066`). This means the next step should be constrained score iteration or search around the surviving factor families, not more data plumbing or immediate autoresearch over the full original blend. |
| **Fundamental Inverted Factors** | **Negative growth/quality IC should be tested as anti-signals, not discarded** | On the same `2009+` `large_cap_v1` historical dataset, complemented/inverted growth and quality strategies materially outperform their positive versions. The best constrained baselines are now `health_minus_quality` (`+0.074778`) and `health_minus_growth` (`+0.073166`) on sector-neutral `60d` rank IC. For this harness, growth and quality currently look more like overexpectation / crowding variables than direct long signals, so the next constrained search space should center on `health` plus inverted `growth` / `quality`. |
| **Fundamental Constrained Search** | **Health-led model with anti-crowding overlays is the current winning shape** | A deterministic search over `health`, inverted `growth`, and inverted `quality` on the same `2009+` `large_cap_v1` dataset improves the best `60d` sector-neutral rank IC to `+0.087029`. The current winner is `health_0p5__inv_growth_0p1__inv_quality_0p4`, with nearby winners heavily clustered around strong `health`, heavier inverted `quality`, and only a small inverted `growth` sleeve. This suggests the next search/promotion work should center on a health-led model with quality-overexpectation control rather than the original all-positive composite. |
| **Fundamental Strategy Robustness** | **The current health-led anti-crowding model strengthens with longer horizons and survives era/sector slicing** | The current top constrained strategy `health_0p5__inv_growth_0p1__inv_quality_0p4` remains positive across all tested horizons on the `2009+` `large_cap_v1` dataset (`20d +0.056397`, `60d +0.087029`, `120d +0.092488`, `252d +0.116078`) and stays positive across all evaluated sectors and eras, though with weaker readings in Consumer Discretionary and Healthcare. This is strong enough to justify a controlled autoresearch loop inside the constrained health + inverted quality/growth search space, but not yet strong enough for unconstrained full-space search or live pillar promotion. |
| **Fundamental Constrained Autoresearch** | **The constrained loop is now real, but the current winner remains unchanged** | A deterministic constrained autoresearch loop now runs over the validated `health + inverted quality + inverted growth` search space and persists leaderboard, best-strategy, and top-robustness artifacts. On the first real `large_cap_v1` `2009+` run, it searched `28` strategies and confirmed the same winner as the prior constrained search: `health_0p5__inv_growth_0p1__inv_quality_0p4` at `+0.087029` `60d` sector-neutral rank IC. That means the next gain is more likely to come from better features or a carefully broadened constrained search space, not from adding a more elaborate search loop. |
| **Fundamental Feature Refinement** | **More nuanced acceleration/tension/stress features did not beat the simpler health-led winner** | A targeted feature-upgrade slice added growth acceleration, quality-valuation tension, margin-change, and explicit health-stress fields, and wired them into the scoring families. The rerun on the same `2009+` `large_cap_v1` dataset produced a new best strategy of `health_0p4__inv_growth_0p1__inv_quality_0p5` at `+0.084495`, which is weaker than the prior simpler winner `health_0p5__inv_growth_0p1__inv_quality_0p4` at `+0.087029`. This suggests the current bottleneck is not lack of feature nuance in those specific directions; future gains are more likely to come from better source-level features or a carefully broadened constrained search space. |
| **Fundamental Valuation Broadening** | **A small positive valuation sleeve did not beat the standing health-led anti-crowding winner** | The constrained search space was broadened to allow a small positive `valuation` sleeve alongside `health + inverted growth + inverted quality`, while still forcing `health` dominance and fixed weight budgets. On the first real broadened run (`64` strategies), the best overall result was still a no-valuation strategy: `health_0p4__inv_growth_0p1__inv_quality_0p5 = +0.084495`, and the best valuation-bearing strategy reached only `+0.084207`. Both remain below the standing canonical winner `health_0p5__inv_growth_0p1__inv_quality_0p4 = +0.087029`, so valuation has not yet earned promotion in this constrained family. |
| **Fundamental Capital Discipline Broadening** | **A small positive capital-discipline sleeve also failed to beat the current health-led anti-crowding winner** | The constrained search space was next widened to allow a small positive `capital_discipline` sleeve while keeping `health` dominant and `growth` / `quality` inverted-only. On the first real run of that space, the best overall result remained a no-capital-discipline strategy: `health_0p4__inv_growth_0p1__inv_quality_0p5 = +0.084495`, while the best capital-discipline-bearing strategy reached `+0.084207`. Capital discipline may still matter as context, but it has not yet earned promotion into the canonical winner on the current feature set. |
| **Fundamental Live Shadow Overlay** | **Use the health-vs-expectation-risk learning as advisory metadata before live pillar replacement** | The live/session scoring paths now expose a read-only `fundamental_overlay_score` beside the official fundamental pillar. It is computed as `0.5 * health + 0.4 * (100 - quality) + 0.1 * (100 - growth)` and labeled as `UNDERAPPRECIATED_RESILIENCE`, `BALANCED`, or `CROWDING_RISK`. It is intentionally advisory only in v1 so today’s runs can use the harness learning without silently changing the official Aeternus score. |
| **Registry-Driven Fundamental Factor** | **Live SEC connector now serves the promoted/shadow autoresearch winner instead of hardcoded baseline weights** | `tradingagents/dealflow/sources/fundamental_factor.py` no longer owns the live formula. It now builds latest SEC feature rows through the `fundamental_autoresearch` harness and reads the active strategy from `eval_results/fundamental_autoresearch/<date>/fundamental_signals.json` via `get_active_strategy(...)`. In v1 it emits `fundamental_factor_shadow` while the strategy is still shadow-only, and degrades cleanly with `NOT_CONFIGURED` if the registry is missing. This makes the historical harness + promotion gate the source of truth and turns the live connector into a serving adapter. |
| **Project Memory** | **5-tier + control-plane overlay** | Keep `WORKING/MEMORY/daily` as operational memory; add `Prompt/Plans/Architecture/Implement/Documentation` for durable strategy coherence |
| **Architecture Source of Truth** | **DeepWiki Master Article** | `memory/DeepWiki_System_Architecture.md` is the canonical As-Is + Target-State architecture visualization and contract map |
| **Question Investigation Backend** | **Python-first `Question Compiler` over real pipeline state** | The approved MiroFish-inspired next layer is not a generic chatbot and not a required Zep integration. `v1` should compile a user question into an `Investigation Packet`, inspect real Aeternus artifacts stage by stage, return frontend-ready findings, and stop with explicit manual gap-fill requests when evidence is incomplete. LLM usage should remain optional and tightly bounded. |
| **Question Investigation Runtime** | **Manual `question-investigate` CLI now exists as the first chat-backend surface** | The first implemented surface is `python3 -m cli.main question-investigate --question ...`, which runs `compile_question(...) -> run_investigation(...) -> build_investigation_response(...)` against internal artifacts only. It is intentionally manual-only, JSON-friendly, and designed to back a future chat-style frontend without requiring Zep or automatic external retrieval. |

---

## Coding Guidelines (KARPATHY_GUIDELINES.md)

1. **Think Before Coding** - State assumptions, surface tradeoffs
2. **Simplicity First** - Minimum code, no speculation
3. **Surgical Changes** - Touch only what's needed
4. **Goal-Driven** - Define verifiable success criteria
5. **LLM Call Efficiency** - Before making N calls asking the same question from different angles, ask: can one well-crafted prompt combine all angles and return a richer result? Multiple near-identical prompts = waste. One comprehensive prompt = same or better signal at 1/N cost. Apply to xAI x_search, OpenAI, and any pay-per-call LLM integration.

---

## File Locations

| Component | Path |
|-----------|------|
| Scorer | `tradingagents/graph/aeternus_scoring.py` |
| Track Record | `tradingagents/graph/track_record.py` |
| Audit Log | `tradingagents/graph/audit.py` |
| Sector Context | `tradingagents/graph/sector_context.py` |
| Thesis Check | `tradingagents/graph/thesis_check.py` |
| Hedging Engine | `tradingagents/graph/hedging.py` |
| Market Regime | `tradingagents/graph/market_regime.py` |
| Hedging Contracts | `tradingagents/graph/contracts.py` |
| Deal Flow Pipeline | `tradingagents/dealflow/pipeline.py` |
| Deal Flow Scheduler | `tradingagents/dealflow/scheduler.py` |
| Smart Money Source | `tradingagents/dealflow/sources/smart_money.py` |
| X Direct Source | `tradingagents/dealflow/sources/x_social.py` |
| Cashtag Source | `tradingagents/dealflow/sources/cashtag_stream.py` |
| Legacy Pre-Fundamental Scoring | `legacy pre-fundamental scorer` |
| Legacy Pre-Fundamental Selection | `legacy selector` |
| Durable Prompt | `memory/Prompt.md` |
| Durable Plans | `memory/Plans.md` |
| Durable Architecture | `memory/Architecture.md` |
| Implement Playbook | `memory/Implement.md` |
| Milestone Ledger | `memory/Documentation.md` |
| CLI | `cli/main.py` |
| Graph | `tradingagents/graph/trading_graph.py` |
| Tests | `tests/` |
| Vision | `PLATFORM_VISION.md` |
| Guidelines | `KARPATHY_GUIDELINES.md` |

---

## Environment Notes

- Python project with `pyproject.toml`
- Uses `uv` for package management
- Requires API keys for LLM providers (via .env)

---

## Recent Addendum (2026-02-06)

- `retired post-scout batch command` now has deterministic per-item timeout control in `cli/main.py` via `--per-item-timeout-seconds` (env: `AETERNUS_ANALYZE_BATCH_ITEM_TIMEOUT_SECONDS`, default `420`).
- Timeout behavior is fail-fast per item (status `FAILED`, return code `124`) while allowing the batch loop to continue and persist attribution summaries.

---

*Last Curated: 2026-02-06T22:56:00Z*

## Recent Addendum (2026-02-06T23:21:54Z)

- Added Step 2 execution abstraction in `tradingagents/graph/paper_execution.py` with a stable broker boundary (`ExecutionAdapter` + `PaperExecutionAdapter`) so paper execution and future live brokerage share the same order/close interface.
- Added idempotent order execution by `order_intent_id` and broker-compatible order metadata (`client_order_id`, `idempotency_key`, `order_type`, `time_in_force`) to reduce integration risk when switching to live order routing.
- Added Step 2 CLI execution chain in `cli/main.py`:
  - `portfolio-plan` -> deterministic order intents from `retired post-scout batch command`
  - `execute-paper` -> fill intents through adapter
  - `paper-positions` -> inspect open ledger
  - `close-paper` -> close position and propagate to `TrackRecord.update_outcome`

## Recent Addendum (2026-02-07T19:55:00Z)

- Step 1 hardening moved Deal Flow default candidate_list size from Top-20 to Top-30:
  - `legacy_top_count=30`
  - lane quotas updated to `18 CORE / 12 MOMENTUM` in `tradingagents/default_config.py`.
- Added discovered-cashtag symbol sanitization in `tradingagents/dealflow/pipeline.py` using configurable min/max length and denylist gates to reduce non-tradable token ingress.
- Added connector timeout/retry guards in `tradingagents/dealflow/pipeline.py` (`dealflow_connector_timeout_seconds`, `dealflow_connector_max_attempts`) to prevent single-source stalls from blocking candidate_list generation.
- Hardened yfinance-heavy connectors (`price_momentum.py`, `macro.py`) with batched downloads, suppressed noisy stderr/stdout output, and non-threaded fetches for more stable runtime behavior in max-recall conditions.

## Recent Addendum (2026-02-07T01:42:07Z)

- `retired post-scout batch command` in `cli/main.py` now supports dual-pass execution in one run:
  - `DEEP` analysis for queue items where `legacy_deep_flag=true`

## Recent Addendum (2026-03-11T12:40:00Z)

- The `SPY + QQQ + DOW` technical signal cache is now designed to support both forward appends and historical prepends in the same SQLite store. This allows a later operator request for an older start date (for example `1999-01-01`) to backfill missing early history into `eval_results/control/technical_signal_cache.db` without wiping or rebuilding the existing cache.

## Recent Addendum (2026-03-11T15:10:00Z)

- `KAMA + bullish FVG regime` now has a first-class discovery role in Aeternus as a discovery-only `technical_ignition` scout. It is intentionally not a `collect` signal family yet. Fresh `BUY_TRIGGER` / `BUY_ZONE` states are promoted into the filtered universe through dedicated tier `T3D_TECHNICAL_IGNITION`, while `TREND_UP_NOT_FRESH` remains audit-only context. The scout writes through existing `scout_audit -> universe_filter -> discovery_delta` paths instead of introducing a separate artifact stack.
  - `QUICK` analysis for non-selected items (default behavior)
- New CLI control flags:
  - `--include-unselected/--selected-only`
  - `--quick-unselected/--deep-unselected`
- Batch summary schema now includes:
  - per-item `analysis_mode`
  - run-level `analysis_mode_counts`
- `score` command now uses provider-aware non-interactive resolution (`_build_noninteractive_selections`) so queue/batch quick mode honors xAI fallback and avoids OpenAI-only environment failures.

## Recent Addendum (2026-03-18T12:15:13Z)

- `why-missed` / `question-investigate` now has authoritative stage-native reject metadata sourced at pipeline write-time, not only inferred at investigation-time.
- `hypothesis_ledger.make_ledger_row(...)` now supports optional per-symbol drop payloads and persists `dropped_symbols_metadata_path` alongside kept/dropped symbol snapshots.
- Dealflow stage writers now emit canonical per-symbol reject metadata for:
  - `universe_gate_edge`
  - `universe_gate_haystack`
  - `evidence_gate`
  - `candidate_list_cut`
  - `fundamental_intake_cut`
- Investigation now prefers this canonical payload (`reason_code`, `reason_text`, `threshold`, `observed_value`, `delta_to_pass`) and only falls back to heuristic inference when metadata is absent.

## Recent Addendum (2026-03-18T14:24:07Z)

- Manual `x-feed` pass-14 ingest now supports options-flow-only payloads. If `trending` is empty but `options_flow` contains tickers, the pipeline now synthesizes minimal ticker entries so those names are merged and written to AKG instead of being dropped by early-return logic.
- Manual pass summaries for empty-pass and pass-15 gex-only paths now report the true existing merged-symbol count instead of always returning `0`, reducing operator confusion during low-signal days.

## Recent Addendum (2026-02-07T02:10:17Z)

- Step 2 execution safety now includes deterministic pre-trade risk checks in `tradingagents/graph/paper_execution.py` via `evaluate_pretrade_risk(...)`.
- `execute-paper` in `cli/main.py` now:
  - applies pre-trade acceptance/rejection before execution,
  - persists risk artifacts under `eval_results/paper_execution/risk_checks/<date>/`,
  - emits risk summary in command output and audit.
- Added new execution risk defaults in `tradingagents/default_config.py`:
  - `execution_max_gross_exposure_pct`
  - `execution_max_single_position_pct`
  - `execution_max_open_positions`
  - `execution_max_new_orders_per_run`

## Recent Addendum (2026-03-06T22:30:00Z)

- Phase 1 hypothesis-ledger instrumentation is now outcome-aware instead of write-time only:
  - `tradingagents/dealflow/hypothesis_ledger.py` can re-open persisted kept/dropped symbol snapshots and enrich stage rows later via `enrich_ledger_rows(...)`.
- Forward-return ownership is now split deliberately:
  - `tradingagents/dealflow/hindsight.py` enriches shared-lane stage rows with realized `5d` returns.
  - `tradingagents/dealflow/performance_tracker.py` enriches shared-lane stage rows with realized `5d`, `20d`, and available `3m` return maps plus benchmark context.
- This keeps the funnel instrumentation append-only while letting later scorecards evaluate candidate_list/fundamental-intake/portfolio cuts against actual outcomes without recomputing stage membership.

## Recent Addendum (2026-03-06T22:55:00Z)

- Phase 1 stage coverage is now complete across the current funnel:
  - `universe_gate_edge`
  - `universe_gate_haystack`
  - `evidence_gate`
  - `candidate_list_cut`
  - `fundamental_intake_cut`
  - `portfolio_inclusion_cut`
- `tradingagents/dealflow/akg_universe.py` now preserves last-run universe filter snapshots so the pipeline can log early-stage cuts without rebuilding AKG state.
- Universe-gate semantics are intentionally split:
  - `universe_gate_edge` uses a fair dropped pool for kept-vs-dropped edge.
  - `universe_gate_haystack` uses the whole excluded haystack for recall and false-negative cost.
  - `execution_block_short_orders`

## Recent Addendum (2026-03-07T18:20:00Z)

- Discovery Delta v1 is now fully measurable inside the standard review surfaces:
  - `tradingagents/dealflow/hindsight.py` embeds `discovery_delta_cohorts` for `5d`
  - `tradingagents/dealflow/performance_tracker.py` embeds `discovery_delta_cohorts` for `5d`, `20d`, and `3m`
- The shared cohort scorecard logic lives in `tradingagents/dealflow/discovery_delta.py`.
- The measured cohorts are:
  - `scout_only`
  - `technical_only`
  - `multi_channel`
- Each cohort is now compared two ways:
  - against the full Step 1 kept-universe baseline
  - against the average of the other Delta cohorts
- The review artifacts also track:
  - `candidate_list_conversion`
  - `fundamental_intake_conversion`
- This keeps Discovery Delta read-only while making it possible to determine whether multi-channel discovery is genuinely stronger or whether later funnel stages are suppressing a good discovery cohort.

## Recent Addendum (2026-02-07T15:21:17Z)

- Added stale-order remediation control plane in `cli/main.py`:
  - `manage-open-orders` performs deterministic stale detection over pending outbox orders, supports cancel-only or cancel+replace, enforces per-symbol retry caps, and persists artifacts to `eval_results/live_execution/open_orders/...`.
- Added broker-shadow auto-heal control plane in `cli/main.py`:
  - `sync-positions-from-broker` rebuilds shadow positions from broker position snapshots, preserves strategy metadata where available, and persists artifacts to `eval_results/live_execution/positions_sync/...`.
- Added new execution defaults in `tradingagents/default_config.py` (with `.env.example` mirrors):
  - `execution_open_orders_max_age_minutes`
  - `execution_open_orders_replace_stale`
  - `execution_open_orders_replacement_order_type`
  - `execution_open_orders_limit_price_offset_bps`
  - `execution_open_orders_max_retries_per_symbol_per_day`
- Added new audit event coverage for operations accountability:
  - `OPEN_ORDER_STALE_DETECTED`
  - `OPEN_ORDER_CANCELED`
  - `OPEN_ORDER_REPLACED`
  - `OPEN_ORDER_RETRY_EXHAUSTED`
  - `OPEN_ORDER_MANAGEMENT_COMPLETED`
  - `LIVE_POSITIONS_SHADOW_SYNCED`

## Recent Addendum (2026-03-06T08:15:00Z)

- Approved a new target architecture for deal-flow evolution: a **multi-lane probability funnel** with a shared `L0` feature store, shared `L1` recall scan, and lane split beginning at `L2`.
- Defined two explicit optimization lanes:
  - `3-Month Upside` for tactical outperformance over `1-3 months`
  - `Emergence` for early detection of future large winners using proxy-first, truth-anchored validation
- Added a durable architectural requirement: every major funnel cut must become a **hypothesis-ledger** entry with kept-vs-dropped symbol snapshots and later outcome evaluation.
- New first-class metrics:
  - `future winner recall by stage`
  - `false-negative cost by filter`
  - `kept-vs-dropped edge` by horizon
- Rollout decision: instrument the current funnel first, add lane metadata second, split orchestration only after Phase 1 metrics are proven.

## Recent Addendum (2026-02-07T15:39:49Z)

- `execution-sync` in `cli/main.py` now supports a full pre-readiness operations chain:
  - optional stale open-order management (`manage-open-orders` logic embedded),
  - optional broker->shadow position sync (`sync-positions-from-broker` logic embedded),
  - then readiness gating and optional exit submission.
- New execution-sync option surface:
  - `--manage-open-orders` (+ apply/dry-run and stale/replacement controls),
  - `--sync-shadow-positions` (+ apply/dry-run and drop-missing control),
  - `--broker-positions-snapshot-path` for explicit snapshot wiring.
- New default controls in `tradingagents/default_config.py`:
  - `execution_sync_manage_open_orders`
  - `execution_sync_manage_open_orders_apply`
  - `execution_sync_sync_shadow_positions`
  - `execution_sync_sync_shadow_positions_apply`
- Outcome: operators can now run one deterministic sync command to handle stale pending orders, heal shadow drift, evaluate readiness, and trigger exits in a single cycle.

## Recent Addendum (2026-02-07T15:50:12Z)

## Recent Addendum (2026-03-05T22:30:00Z)

- **Research Execution Mode** | **Local Codex bridge for deep analyst runs** | Deep analysis now supports a Codex-driven path where the app shells out to local `codex exec`, one ticker at a time, with four parallel analyst jobs (`market`, `social`, `news`, `fundamentals`) writing structured artifacts under `results/{ticker}/{date}/codex_research/`.
- **Graph Handoff Contract** | **Post-analyst downstream graph** | `TradingAgentsGraph` now exposes a post-analyst graph entry point so Codex-generated analyst reports can be injected into state and the existing debate/trader/risk flow can continue without re-running analyst nodes.
- **Social/X Policy** | **Manual Grok only** | No xAI API is used for dealflow/social ingestion going forward. X/social intelligence remains manual: prompt generation in-repo, operator paste into Grok, operator paste back into ingest path.
- **Codex Runtime Defaults** | **`research_execution_mode=codex_bridge` + `gpt-5.4` + `xhigh`** | Deep analysis defaults now point at the local Codex bridge, with configurable binary/model/reasoning/timeout via `AETERNUS_CODEX_*` env vars.
- **Batch Summary Compatibility** | **Emit both `symbol` and `ticker`** | `write_batch_summary()` now writes both keys so downstream consumers and legacy tests remain compatible.

## Recent Addendum (2026-02-07T23:35:32Z)

- **Order Lifecycle Canonicalization**: broker status normalization now standardizes partial fills as `PARTIALLY_FILLED` and treats `REPLACED` as terminal in reconciliation/control-plane flows (`tradingagents/graph/paper_execution.py`, `cli/main.py`).
- **Workflow Hedge Control**: `workflow-run` now exposes explicit hedge inclusion control (`--include-hedges/--skip-hedges`) and persists hedge decision telemetry in workflow plan-step status.
- **Workflow Automation Wrapper**: added `workflow-loop` for repeated end-to-end cycles with interval and failure controls; persists loop-level artifacts under live execution workflow paths (`cli/main.py`).
- **Manual Sector Fallback Hardening**: dealflow manual synth no longer defaults to `Unknown`; it now uses deterministic baseline sector inference and falls back to `Unclassified Equity` (`tradingagents/dealflow/pipeline.py`).
- **Loop Defaults**: introduced `workflow_loop_default_cycles` and `workflow_loop_interval_seconds` configuration keys (`tradingagents/default_config.py`).

## Recent Addendum (2026-02-07T16:25:32Z)

- Hedge recommendations are now execution-path aware:
  - `portfolio-plan` (`cli/main.py`) can append deterministic hedge intents via `--include-hedges` using current portfolio risk snapshot + market regime + hedge decision.
  - Hedge intents are tagged with `intent_category=HEDGE` and carry hedge metadata (`hedge_mode`, target pct, regime, reason) for downstream audit and attribution.
- Pre-trade risk checks now treat hedges as a dedicated risk bucket in `tradingagents/graph/paper_execution.py`:
  - `execution_allow_hedge_short_orders` allows defensive hedge shorts while preserving short-block policy for alpha orders.
  - `execution_max_hedge_notional_pct` caps hedge notional independently from alpha gross/single-position limits.
- Execution record fidelity improved:
  - paper/live/alpaca submission records persist `intent_category` + hedge metadata.
  - audit trail now emits hedge-specific execution events (`HEDGE_INTENT_CREATED`, `HEDGE_ORDER_SUBMITTED`, `HEDGE_ORDER_EXECUTED`, `HEDGE_ORDER_REJECTED_RISK`).
- Hedge state closure now happens on execution path:
  - `execute-paper` updates hedge state/order via `AdaptiveHedgeEngine.persist_state_and_orders(...)` when hedge intents are actually processed, reducing drift between recommendation and execution state.
- Risk guardrails now distinguish `SELL-to-reduce` vs `SELL-to-open-short`:
  - pre-trade checks in `paper_execution.py` are signed-exposure aware, allowing long reductions while still blocking net short creation when shorting is disabled.
- Hedge operations now have dedicated CLI controls:
  - `hedge-evaluate` (one-shot deterministic hedge decision run)
  - `hedge-status` (persisted hedge state + recent hedge orders)

- Added full one-command workflow orchestration in `cli/main.py`:
  - new command `workflow-run` executes:
    - scheduler orchestration (`auto|daily|event|manual`)
    - `retired post-scout batch command`
    - `portfolio-plan`
    - `execute-paper` (optional)
    - `execution-sync` (optional)
- Added deterministic workflow status model:
  - `SUCCESS`
  - `SKIPPED_ORCHESTRATION`
  - `FAILED_ANALYZE_BATCH`
  - `FAILED_PORTFOLIO_PLAN`
  - `FAILED_EXECUTION`
  - `FAILED_EXECUTION_SYNC`
- Added workflow artifact persistence:
  - `eval_results/live_execution/workflow/<date>/workflow_run_<time>.json`
  - `eval_results/live_execution/latest_workflow_run.json`
- Purpose: allow unattended operator-grade automation from sourcing through execution/sync in a single CLI entrypoint with stage-level traceability.
- Added audit coverage for risk control path:
  - `PAPER_PRETRADE_RISK_CHECK`
  - `PAPER_ORDER_REJECTED_RISK`

## Recent Addendum (2026-02-07T16:12:49Z)

- Portfolio-risk context is now computed before graph execution in `cli/main.py` via `build_pretrade_risk_context()` and injected into state keys:
  - `pretrade_risk_brief`
  - `portfolio_snapshot`
  - `market_regime`
  - `hedge_signal`
  - `hedge_decision`
- Risk Judge prompt (`tradingagents/agents/managers/risk_manager.py`) now explicitly consumes this context and requires a hedge stance (increase/decrease/no-change with instrument).
- Analyze reports now include a dedicated `Portfolio Risk & Hedge Recommendation` section in CLI and markdown export, rendered by `format_portfolio_risk_hedge_markdown(...)`.
- Hedging policy (`tradingagents/graph/hedging.py`) now includes deterministic regime classification (`CRASH`, `BEAR_STRESS`, `VOLATILITY_SHOCK`, `RISK_OFF`, etc.) plus additional defensive target floors for volatility/drawdown/VAR stress escalation.

## Recent Addendum (2026-02-08T22:06:18Z)

- **Mirror Handshake Foundation (Sprint A)**:
  - Added deterministic non-discretionary follow path using SQLite WAL consent/challenge ledger:
    - `mirror_challenges`
    - `user_consent_log`
  - Confirm flow is hash-bound (`challenge_id` + `client_preview_hash`) and atomic:
    - consent log write + challenge consume + intent transition (`VALIDATED -> SUBMITTED`) in one transaction.
  - Added gateway endpoints on existing control-plane stack (no parallel API):
    - `POST /ops/mirror-intents/{intent_id}/challenge`
    - `POST /ops/mirror-intents/{intent_id}/confirm`
    - `POST /ops/intent/{intent_id}/confirm` (alias)
  - Added humanized status dictionary for concierge-style UX messaging in API payloads.
  - Added broker adapter scaffold (`disabled|mock`) to avoid premature live coupling.

- **Legal/operational design invariant (locked)**:
  - User confirmation is mandatory to move from model-ready to submitted state.
  - `operator_gateway_require_legal_consent=true` blocks confirm without explicit legal consent marker.
  - Existing triage/operator endpoints remain for backward compatibility.

- **P1 Strategic backlog (deferred until current primitives proven)**:
  - Build true multi-asset capital allocator primitives after current listed-market system proves stability:
    - asset-agnostic capital model (liquidity horizons, settlement/funding constraints, tax-lot intelligence),
    - ADV/impact-aware execution planning beyond fixed-bps assumptions,
    - balance-sheet/float-like capital-priority engine with dynamic hurdle rates.
  - Rationale: prevent overfitting architecture to unproven complexity before read/write control plane and public-market allocator telemetry are production-stable.

## Recent Addendum (2026-02-08T22:21:59Z)

- **Alignment Pulse Primitive Added**:
  - Bootstrap contract now includes deterministic portfolio drift fields (`portfolio_drift_*`) computed from model-vs-broker allocation artifacts.
  - Drift status buckets are explicit (`ALIGNED`, `DRIFTING`, `DISCONNECTED`, `UNKNOWN`) with stale/missing-data fallback to `UNKNOWN`.
  - This is intentionally non-invasive: no execution semantics changed, only read-plane observability.

- **Mirror Preview Contract Added**:
  - New endpoint `GET /ops/mirror-intents/{intent_id}` returns:
    - current intent summary and user-safe status message,
    - latest challenge metadata,
    - drift pulse snapshot.
  - Purpose: power "Tap to review" UX before hold-to-confirm, with no additional mutation side effects.

- **Design Invariant Clarification**:
  - "Not followed" does not map to synthetic rejection codes.
  - System truth remains:
    - no confirm => no submit
    - expiry/no-confirm represented by `EXPIRED_INTENT` or unchanged validated state.

## Recent Addendum (2026-02-08T22:29:20Z)

- **Drift Sensitivity Control Plane Added**:
  - Drift thresholds are now operator-configurable through gateway settings endpoints (`/ops/settings/drift-sensitivity`).
  - Bootstrap returns active sensitivity values plus drift status to drive pulse UX deterministically.

- **Mirror Preview Delta Contract Added**:
  - Preview endpoint now emits side-by-side symbol delta (`current_weight_pct`, `target_weight_pct`, `delta_weight_pct`) for clear pre-confirm visualization.
  - This formalizes the “Context → Delta → Action” UI pattern without exposing internal model math.

- **Operational Primitive Added**:
  - Gateway now supports background drift snapshot refresh for low-latency alignment status reads.

## Recent Addendum (2026-02-08T22:42:36Z)

- **Drift Impact Contract Added**:
  - New read endpoint `GET /ops/drift-impact` returns symbol-level model-vs-broker deltas and explicit non-model exposure classification.
  - Bootstrap now carries `portfolio_non_model_exposure_count` for fast top-level pulse/intel.

- **P1 Broker Connectivity Decision Locked**:
  - Live Robinhood/Public/Webull OAuth adapters are deferred to P1.
  - Reason: implement only after compliance, secure credential custody, and broker reconciliation/idempotency contracts are finalized.
  - Current canonical path remains non-discretionary mirror with deterministic consent ledger + mock adapter.
- Portfolio risk snapshot derivation now prefers live paper-position ledger data (`eval_results/paper_execution/positions.json`) when available, reducing proxy drift from track-record-only estimation.

## Recent Addendum (2026-02-07T04:05:34Z)

- `portfolio-plan` source summary resolution now prefers latest non-`dry_run` batch artifacts, avoiding accidental empty plans after dry-run executions.
- Order intent generation now includes deterministic market-price fallback when `analysis_report` lacks pricing fields, and records `reference_price_source` (`analysis_report` vs `market_fallback`) for traceability.

## Recent Addendum (2026-02-07T04:14:50Z)

- Step 2 execution now defaults to delta rebalancing:
  - `execute-paper` transforms plan intents to gap-to-target deltas before risk checks.
  - repeated runs against already-matched positions now safely no-op instead of re-issuing full-size intents.
- Added execution controls:
  - `execution_rebalance_to_target`
  - `execution_min_rebalance_notional_usd`
  - `execution_close_missing_positions`

## Recent Addendum (2026-02-07T04:22:39Z)

- Added live execution scaffold in `tradingagents/graph/paper_execution.py`:
  - `LiveExecutionAdapter` supports queue-only order submission (no broker placement/fill assumptions).
  - `execute_plan_with_adapter(...)` now supports both `paper` and `live` mode routing.
- Updated `execute-paper` in `cli/main.py` for live mode:
  - resolves mode-aware ledger paths (`live_execution_outbox_path`, `live_positions_shadow_path`),
  - reports both `executed_orders` and `submitted_orders`.
- Added live-mode defaults in `tradingagents/default_config.py`:
  - `live_execution_outbox_path`
  - `live_positions_shadow_path`
- Added live scaffold regression coverage:
  - CLI live-path test in `tests/test_cli_dealflow.py`
  - live queue/idempotency test in `tests/test_paper_execution.py`

## Recent Addendum (2026-02-07T11:39:49Z)

- Added Step 2 reconciliation loop in `tradingagents/graph/paper_execution.py`:
  - `reconcile_live_execution(...)` now reconciles broker order snapshots to live outbox intents.
  - applies normalized status transitions and idempotent fill-delta application into shadow positions.
  - persists live fill events for downstream attribution/ledger traceability.
- Added reconciliation command in `cli/main.py`:
  - `aeternus reconcile-execution --broker-snapshot-path <path>`
  - writes persisted reconciliation artifacts under `eval_results/live_execution/reconciliation/<date>/`.
- Added live reconciliation config surface:
  - `live_execution_fills_path`
  - `live_broker_orders_snapshot_path`
- Added reconciliation audit events:
  - `LIVE_RECONCILIATION_COMPLETED`
  - `LIVE_ORDER_RECONCILED`
  - `LIVE_FILL_APPLIED`

## Recent Addendum (2026-02-07T12:25:21Z)

- Added Alpaca broker adapter support in `tradingagents/graph/paper_execution.py`:
  - execution modes `alpaca-paper` and `alpaca-live`
  - broker submission path writes normalized outbox records with broker order ids/status metadata
  - idempotent duplicate suppression remains anchored to `order_intent_id`
- Added broker snapshot retrieval for reconciliation:
  - `fetch_alpaca_orders_snapshot(...)` fetches Alpaca `/v2/orders` and persists snapshot JSON
  - `pull-broker-orders` command in `cli/main.py` now supports Alpaca snapshot fetch flow
- Updated execution routing semantics:
  - `execute-paper --execution-mode alpaca-paper|alpaca-live` routes through live outbox/shadow ledgers
  - intended sequence is now:
    - `portfolio-plan`
    - `execute-paper --execution-mode alpaca-paper`
    - `pull-broker-orders --broker alpaca`
    - `reconcile-execution`

## Recent Addendum (2026-02-07T12:39:31Z)

- Hardened Alpaca base URL handling in `tradingagents/graph/paper_execution.py`:
  - `_normalize_alpaca_base_url(...)` strips trailing `/v2` from configured base URLs.
  - prevents accidental `.../v2/v2/orders` path composition and 404 failures when operators set `ALPACA_API_BASE_URL` to a versioned endpoint.

## Recent Addendum (2026-02-07T12:54:08Z)

- Added whole-share submission policy for Alpaca in `tradingagents/graph/paper_execution.py`:
  - default `ALPACA_ENFORCE_WHOLE_SHARES=true` now rounds submission quantity down to integer shares.
  - sub-1-share intents that round to zero are rejected with explicit reason (`WHOLE_SHARE_ROUND_DOWN_TO_ZERO`) instead of sending invalid fractional orders.
- Added config/docs exposure:
  - `alpaca_enforce_whole_shares` in `tradingagents/default_config.py`
  - `ALPACA_ENFORCE_WHOLE_SHARES` in `.env.example`

## Recent Addendum (2026-02-07T13:54:50Z)

- Added one-command Step 2 lifecycle sync in `cli/main.py`:
  - `aeternus execution-sync`
  - orchestrates broker snapshot pull + reconciliation + position mark/PnL refresh in one cycle.
  - supports `--once` and `--loop --interval-sec <n> --max-loops <n>` for operational polling.
- Added shadow-position mark-to-market refresher in `tradingagents/graph/paper_execution.py`:
  - `refresh_positions_market_snapshot(...)`
  - updates `last_mark_price`, `market_value_usd`, `unrealized_pnl_usd`, `unrealized_return_pct`, `mark_to_market_at`.
- Added sync-cycle audit event:
  - `LIVE_EXECUTION_SYNC_CYCLE`

## Recent Addendum (2026-02-07T14:42:13Z)

- Added deterministic exit management primitives in `tradingagents/graph/paper_execution.py`:
  - `build_exit_execution_plan(...)` emits rule-driven EXIT intents using:
    - stop loss
    - take profit
    - max hold days
    - trailing stop
  - carries explicit exit metadata (`intent_category`, `exit_rule`, `exit_reason`) for audit/reconciliation traceability.
- Added broker execution readiness gate in `tradingagents/graph/paper_execution.py`:
  - `evaluate_execution_readiness(...)` enforces deterministic go/no-go checks:
    - credentials present
    - account active + buying power threshold
    - stale pending order threshold
    - pending-vs-broker open order match threshold
    - broker-vs-shadow position drift threshold
- Extended operational CLI in `cli/main.py`:
  - `manage-exits` for deterministic exit preview/submit.
  - `execution-readiness` for standalone readiness evaluation with optional hard-fail exit code.
  - `execution-sync` now supports integrated readiness gating + optional exit submission (`--apply-exits --require-ready`).
- Expanded execution config surface in `tradingagents/default_config.py`:
  - `execution_exit_*`
  - `execution_readiness_*`

## Recent Addendum (2026-02-07T15:05:00Z)

- Added broker position snapshot fetch support:
  - `fetch_alpaca_positions_snapshot(...)` in `tradingagents/graph/paper_execution.py`.
  - new CLI command: `pull-broker-positions` in `cli/main.py`.
  - new config key: `live_broker_positions_snapshot_path`.
- Added explicit live-shadow position inspection command:
  - `live-positions` in `cli/main.py` (reads `live_positions_shadow_path` ledger directly).
- Added startup guardrail warning in `cli/main.py`:
  - emits one-time warning when `paper_positions_path` and `live_positions_shadow_path` differ, to reduce operator confusion during mixed paper/live workflows.

## Recent Addendum (2026-02-07T15:04:05Z)

- Added explicit broker-vs-shadow drift comparator in `cli/main.py`:
  - `positions-drift` command compares broker snapshot positions against `live_positions_shadow_path`.
  - outputs deterministic per-symbol drift (`qty_drift`, `notional_drift_usd`) and run-level summary (`drift_count`, `total_notional_drift_usd`).
  - supports operational gating via `--fail-on-drift` (exit code `2` when drift exists).
- Added persisted drift artifacts:
  - `eval_results/live_execution/positions_drift/<date>/positions_drift_<time>.json`
  - `eval_results/live_execution/latest_positions_drift.json`
- Added corresponding audit event:
  - `LIVE_POSITIONS_DRIFT_EVALUATED`

## Recent Addendum (2026-02-07T20:48:37Z)

- Added pre-submit parity guardrail for broker-connected execution in `cli/main.py` (`execute-paper`):
  - compares Alpaca broker positions snapshot vs shadow positions before submission,
  - emits structured `position_parity` payload in execution output,
  - optional hard block path rejects submissions on parity drift/errors.
- New parity control surface (config + CLI):
  - `execution_require_position_parity_for_live`
  - `execution_block_on_position_drift`
  - `execution_position_parity_refresh_snapshot`
  - `execution_position_parity_qty_tolerance`
  - `execution_position_parity_notional_tolerance_usd`
- Added parity audit events:
  - `LIVE_POSITION_PARITY_EVALUATED`
  - `PAPER_EXECUTION_BLOCKED_POSITION_PARITY`
- Strengthened portfolio-manager visibility in `portfolio-plan`:
  - persisted `portfolio_risk_summary` artifact block,
  - terminal output now renders full “Portfolio Risk & Hedge Recommendation” panel directly from computed hedge context.

## Incremental Architecture Note (2026-02-07T21:11:52Z)

- `execution-sync` now includes deterministic readiness self-healing when `--require-ready` is active:
  - stale/unmatched pending blockers trigger automatic open-order management apply flow;
  - position-drift blockers trigger automatic broker->shadow position sync apply flow;
  - readiness is re-evaluated in-cycle and persisted as the final gate state.
- This closes a key operator gap where readiness previously required multiple manual commands to unblock.

## Incremental Architecture Note (2026-02-07T21:28:07Z)

- Live reconciliation is now lifecycle-complete for filled exits:
  - broker fill reconciliation updates outbox + shadow positions + fill ledger,
  - and now also materializes closed-trade events and propagates rating outcomes in track record.
- This removes a prior gap where execution fills could flatten positions without creating deterministic close/outcome artifacts.

## Incremental Architecture Note (2026-02-07T21:43:00Z)

- Live execution now defaults to a dedicated shadow ledger path (`eval_results/live_execution/positions_shadow.json`) instead of sharing paper positions.
- This removes a systemic risk where readiness/parity/drift gates could be evaluated on mixed-state ledgers.
- CLI startup diagnostics now correctly flag only true contamination cases (paper path == live path).

## Incremental Architecture Note (2026-02-08T00:18:00Z)

- Added Step 2 Evidence Pack v1.1 subsystem (`tradingagents/evidence/`) as deterministic post-run validation layer.
- New evidence outputs are now first-class artifacts:
  - `evidence_pack.json`
  - `regime_report.json`
  - `walkforward_report.json`
  - `ablation_report.json`
  - `metrics_by_lane_playbook.csv`
  - `metrics_by_regime.csv`
- Regime engine now formalizes precedence and mixed-frequency normalization:
  - precedence order is deterministic and fixed.
  - CPI monthly is forward-filled to trading dates.
  - DGS10 daily series is aligned to trading dates (and supports optional local series injection).
- Step 1 readiness now includes `evidence_quality` gate sourced from persisted evidence artifacts with explicit thresholds for:
  - walkforward window count,
  - regime slice coverage,
  - 5d/20d edge decay.
- This introduces a hard governance boundary: promotion to later phases can be blocked by low evidence quality even when connector/runtime stability gates pass.



## Architecture Addendum (2026-02-08T12:44:50Z) — Operator Gateway Anti-Corruption Read Layer

- Added gateway transformer boundary (`tradingagents/operator_gateway/transformers.py`) to sanitize raw artifacts into stable UI DTOs.
- Added SnapshotEnvelope propagation on read endpoints with both canonical and raw hashes for lineage continuity between read views and triage mutations.
- Read path is intentionally fail-soft (`Data Unavailable` defaults) to prevent API hard failures from missing/renamed artifact fields.
- Security/moat posture: raw prompts, internal vectors, and non-essential debug internals are not exposed through UI DTOs.

## Architecture Backlog Addendum (2026-02-08T15:24:09Z) — P1 North Star

- Long-term objective remains a true multi-asset capital allocator, but implementation is intentionally staged.
- Decision: do **not** force full multi-asset allocator semantics until current public-market primitives are empirically proven.
- Rationale: avoid false precision before core constraints are modeled (reliability-adjusted expected return, lane budgets/cash floor, impact-aware sizing, liquidity horizon constraints, tax-aware objective, durable transactional persistence).
- P1 trigger condition: current primitives show stable, repeatable evidence quality and operational reliability.
- Once triggered, allocator roadmap priority:
  1. Confidence/reliability-adjusted return model.
  2. Deterministic capital policy (core floor, momentum cap, cash/hedge reserves).
  3. Market-impact/slippage-aware sizing.
  4. Time-to-liquidity and liquidity mismatch controls.
  5. Tax-aware optimization penalties.
  6. SQLite WAL durability for critical intent/execution state.
  7. Controlled expansion to additional asset classes/venues.

## Recent Addendum (2026-02-08T15:26:40Z)

- **Operator Bootstrap Contract**: `GET /ops/bootstrap` is now the primary command-center poll endpoint, aggregating schedule truth, snapshot validity, queue summary, top candidates, pending intent counts, and blocking/non-blocking alerts.
- **Bootstrap Efficiency**: Gateway now supports deterministic ETag/304 for `/ops/bootstrap` with configurable bucketing (`operator_gateway_bootstrap_etag_bucket_seconds`) to reduce repeated payload serialization.
- **Gateway Security Baseline**: Optional shared-secret auth can now be enforced for all `/ops/*` endpoints (`operator_gateway_enforce_api_key`, `operator_gateway_api_key_header`, `operator_gateway_api_key`) with CORS origin controls (`operator_gateway_cors_origins`).
- **Operator Interaction Safety**: Week 2 UI shell enforces deliberate high-stakes actions (`APPROVE`/`BLOCK` long-press confirmation), while `DEFER` remains low-friction tap.
- **Read-First Shell Principle**: `operator_ui/` continues as a read-first command-center shell against frozen gateway DTOs; mutation safety remains server-authoritative (`No Data = No Trade`, schedule guard, halt guard).

## Architecture Addendum (2026-02-08T15:51:29Z) — Capital Allocator v1 Foundation

- Added a new isolated allocator module (`tradingagents/capital_allocator`) to formalize deterministic capital decision primitives independent of LLM prompt behavior.
- Reliability engine now supports lane-specific hybrid decay (time + decision count), regime shock scaling, and calibrated reliability composition for adjusted expected return.
- Added deterministic sovereign gates:
  - covariance/group concentration veto,
  - settlement-aware funding gate,
  - price-latency/slippage safety guard.
- Introduced SQLite WAL allocator outbox with lifecycle tables for intents, validations, orders, fills, and terminal receipts, including active funding reservation uniqueness to prevent double-spend.
- This is intentionally additive scaffolding and not yet execution-wired; broker semantics remain unchanged.

## Architecture Addendum (2026-02-08T17:03:56Z) — Allocator Asset-Agnostic Hardening

- Capital allocator contracts now encode asset-agnostic intent metadata (`asset_id`, `asset_class_id`, `valuation_methodology`, `execution_mode`) so allocation math can remain cross-asset even while execution adapters remain listed-market focused.
- Added deterministic liquidity/impact governance:
  - `ImpactGate` enforces ADV participation cap (1% hard veto) with lane-specific impact coefficient assumptions.
- Added deterministic liability/carry layer (`liability_engine.py`):
  - non-linear liquidity premium,
  - regime/risk-free hurdle composition,
  - stale shadow-valuation haircut,
  - net-edge breakdown for sovereign allocator decisions.
- SQLite WAL allocator persistence now includes market snapshot cache and tax-lot anchoring:
  - `market_snapshot` cache table (price, ADV30, vol20d, spread, latency),
  - `allocator_fills` stores `broker_fill_id` and `tax_lot_id` for synthetic audit alignment.

## Architecture Addendum (2026-02-08T17:15:31Z) — Operator Funding-State Observability + Chaos Coverage

- Operator gateway now exposes allocator intent settlement state for command-center workflows:
  - new endpoint: `GET /ops/allocator-intents/status`.
  - bootstrap contract now includes:
    - `allocator_pending_funding_count`
    - `allocator_pending_count`
  - bootstrap emits non-blocking `ALLOCATOR_PENDING_FUNDING` alert when settlement-backed intents are waiting.
- Bootstrap cache coherence now includes allocator DB fingerprint in ETag generation, so UI cache invalidates on allocator-state changes.
- Operator UI command center now surfaces funding/settlement state via dedicated KPI card and info panel, reducing "execution blind spot" during pending-funding windows.
- SQLite WAL allocator reliability is now covered by explicit race/lock tests:
  - concurrent same-reservation insert race behaves deterministically (single winner),
  - writer-lock contention recovers without hangs under busy-timeout semantics.

## Architecture Addendum (2026-02-08T17:22:50Z) — Deterministic Snapshot Cache Seeding

- Added `tradingagents/capital_allocator/market_snapshot_seed.py` as an explicit pre-simulation cache initializer for allocator market data.
- Default seed set is intentionally mixed-liquidity (HIGH/MEDIUM/LOW ADV) so `ImpactGate` behavior is observable during dry runs and crisis drills instead of defaulting to missing-data rejections.
- Added operator-facing script `scripts/seed_allocator_market_snapshot.py` to populate `market_snapshot` table before Day-1/Day-3 validation loops.
- This formalizes a reproducible prerequisite for allocator audits: seed cache first, then evaluate veto/hurdle behavior.

## Architecture Addendum (2026-02-08T17:27:13Z) — Missing ADV Hardening

- `ImpactGate` now treats missing/non-positive ADV as a hard liquidity unknown:
  - default behavior is immediate `REJECTED_IMPACT_VETO` with infinite-participation semantics.
  - explicit exception is limited to `PRIVATE_EQUITY + SHADOW` intents for non-executable shadow bookkeeping flows.
- `LiabilityEngine` participation now maps missing ADV to infinity and handles infinite impact deterministically.
- Added deterministic test proof that liquidity premium alone can reject a trade even when expected edge is positive (DoD hardening for optionality-over-noisy-alpha behavior).

## Architecture Addendum (2026-02-08T17:33:55Z) — Alpha Simulation Runtime Controls

- Added file-backed allocator regime override controls (`regime_override.py`) to inject deterministic shock states without schema changes.
- Added operator scripts:
  - `scripts/run_allocator_alpha_day1.py` for deterministic Day-1 intent generation + allocator validation audit.
  - `scripts/inject_regime_shock.py` for Day-3 `CRISIS` override injection.
- Chosen design explicitly avoids adding a `regime` column to `market_snapshot`; shock control is artifact-driven to keep the current SQLite schema stable during AT-01.

## Architecture Addendum (2026-02-08T20:27:16Z) — Regime Crossover Probe

- Added a deterministic crossover probe vector in the alpha simulation harness so regime shock has observable, testable behavioral impact.
- Probe guarantee: same intent profile is accepted in `NORMAL` and rejected via `REJECTED_LIABILITY_HURDLE` in `CRISIS`.
- This closes the prior false-negative where shock state toggled but produced no practical status divergence in allocator outputs.

## Architecture Addendum (2026-02-08T20:38:21Z) — Concentration Wall Validation

- Added Day-5 concentration stress harness (`run_allocator_alpha_day5_concentration.py`) to validate crisis cap enforcement under correlated-sector add-on risk.
- Crisis wall behavior is now explicitly regression-tested:
  - same SEMIS add-on vector passes in `NORMAL`,
  - fails in `CRISIS` with `REJECTED_COVARIANCE_VETO`.
- Important architectural clarification captured: covariance gate consumes `PortfolioSnapshot` provider state, not `allocator_fills`; fill-ledger injection does not drive concentration veto behavior in current design.

## Architecture Addendum (2026-02-08T20:43:32Z) — Directional Covariance Exit Semantics

- Covariance gate now supports directional risk reduction when portfolio is already above cap:
  - risk-additive intents in breached groups remain vetoed,
  - risk-reducing intents are allowed to pass concentration wall checks.
- This prevents a "Roach Motel" failure mode (positions can exit under stress) while retaining independent liquidity impact vetoes on oversized illiquid sells.

## Recent Addendum (2026-02-08T20:58:12Z)

- **Gateway Architecture Decision**: Kept a single FastAPI surface by extending `tradingagents/operator_gateway` (controller + service), explicitly avoiding a parallel API stack to prevent contract drift.
- **Controller Pattern**: Added `SystemController` (`tradingagents/operator_gateway/controller.py`) as route-facing façade; business logic remains in `OperatorGatewayService`.
- **Operator API Expansion**:
  - `GET /ops/allocator/report-card` for deterministic 7-day allocator telemetry summary.
  - `POST /ops/system/shock` for controlled regime override writes via gateway.
- **Allocator Reporting Primitive**: Added `tradingagents/capital_allocator/reporting.py` with deterministic SQL report-card aggregation (status/lane counts, validation/veto rates, reason-code ranking, pending funding, execution-mode split).
- **Day-7 Protocol Primitive**: Added `scripts/run_allocator_alpha_day7_report.py` to emit `capital_allocator_alpha_day7_report.json` from SQLite WAL ledger.
- **UI Data-Plane Hardening**: Operator Expo shell now consumes allocator status/report-card endpoints and renders a veto dashboard + recent funding-state intents in command center.

## Recent Addendum (2026-02-08T21:03:20Z)

- **Frozen Baseline**: Allocator AT-01 + Week2 First-Light control-plane/data-plane state is frozen in Git commit `5fc5db7` on `origin/main`.
- **Verification Snapshot**: Full test suite at freeze point passed (`280 passed`).

## Architecture Addendum (2026-03-06T13:54:54-0500) — Stage Summary Review Surfaces

- `hindsight.json` and `performance_review.json` are now the source-of-truth review artifacts for compact funnel-stage diagnostics; no separate summary artifact was introduced.
- Shared-lane hypothesis rows are summarized in-place via `summarize_ledger_rows(...)` in `tradingagents/dealflow/hypothesis_ledger.py`.
- Both review paths now persist `hypothesis_stage_summary` with ordered stage metrics:
  - `kept_count`
  - `dropped_count`
  - `edge_5d`
  - `edge_20d`
  - `edge_3m`
  - `future_winner_recall`
  - `false_negative_cost`
- Operator-facing CLI commands now render the same summary block directly from those artifacts:
  - `aeternus hindsight`
  - `aeternus performance-review`
- Architectural intent: filter diagnosis should happen from standard review artifacts first, not by opening raw `hypothesis_ledger/shared/rows.json`.

## Architecture Addendum (2026-03-06T14:15:00-0500) — Rolling Stage Diagnosis

- Added a read-only rolling diagnosis layer in `tradingagents/dealflow/stage_diagnosis.py`.
- Source of truth remains the existing per-cycle review artifacts:
  - `performance_review.json`
  - `hindsight.json`
- Preference order is intentional:
  - use `performance_review.json` first for richer horizon coverage
  - fall back to `hindsight.json` when only the 5d summary exists
- Added operator command:
  - `aeternus stage-diagnosis`
- The command aggregates recent `hypothesis_stage_summary` blocks by `stage_id` and ranks them using a pragmatic priority score driven primarily by:
  - cumulative false-negative cost
  - weak future-winner recall
  - negative medium-horizon edge when present
- Architectural intent: the operator should be able to decide which filter to challenge next without reading raw ledger rows or waiting for a dashboard layer.

## Architecture Addendum (2026-03-06T18:25:00-0500) — Bullish FVG Step 1 Replay Harness

- Added a replay-only bullish FVG experiment surface in `tradingagents/dealflow/fvg_recall.py`.
- The harness is intentionally not wired into live Step 1 behavior yet.
- It supports:
  - deterministic bullish FVG snapshot extraction
  - narrow semis/AI replay universe
  - event-study summaries
  - daily top-`N` basket summaries
  - artifact persistence under `eval_results/deal_flow/fvg_backtest/<date>/`
- Added operator command:
  - `aeternus fvg-backtest`
- Architectural intent:
  - validate or reject the user's FVG hypothesis with point-in-time replay before modifying live funnel logic
  - keep FVG as evidence-generating infrastructure first, not as a hard gate
- Important runtime note:
  - the first long-history implementation was compute-bound because it rebuilt rolling features per bar
  - the accepted design precomputes rolling feature columns once per symbol, preserving the tested snapshot API while making 1999-era replay viable

## Architecture Addendum (2026-03-07T10:30:00-0500) — Separate FMA Step 1 Recall Channel

- Added a separate live Step 1 recall channel for `F=MA` beside the existing `FVG_RECALL` channel.
- Discovery layer now computes and persists:
  - `fvg_recall.json`
  - `fma_recall.json`
- Universe build now supports two separate additive technical recall tiers:
  - `T3B_FVG_RECALL`
  - `T3C_FMA_RECALL`
- `FMA_RECALL` is intentionally not folded into `FVG_RECALL` because attribution matters:
  - future scorecards need to compare `FVG only`, `FMA only`, and overlap behavior independently
- Universe ledger snapshots now capture:
  - `fma_recall_selected_count`
  - `fma_recall_overlap_with_fvg_count`
- Current architectural read from replay:
  - strict `FVG and FMA` overlap is strongest in narrow semis/AI slices
  - on broader large-cap proxies, overlap is too restrictive
  - the practical live Step 1 shape is additive union with separate attribution, not mandatory overlap

## Architecture Addendum (2026-03-07T16:40:00-0500) — Discovery Delta Engine (Read-Only v1)

- Approved a new read-only discovery-layer normalization surface:
  - `tradingagents/dealflow/discovery_delta.py`
- The engine is intentionally read-only in v1.
- Inputs:
  - scout outputs
  - `FVG_RECALL`
  - `FMA_RECALL`
- Outputs:
  - symbol-level normalized delta signals
  - aggregated symbol-level delta records
  - `discovery_delta.json` under `eval_results/deal_flow/<date>/`
- First-class cohort breakdown in v1:
  - `scout_only`
  - `technical_only`
  - `multi_channel`
- Architectural intent:
  - give the discovery layer a common language for state change and non-consensus signal agreement
  - keep attribution clean
  - avoid changing Step 1 membership until the new layer proves itself in live cycles and scorecards
- Runtime integration in v1:
  - `DealFlowPipeline.discover()` now builds and persists `discovery_delta.json`
  - `discover()` exposes a compact `discovery_delta_summary`
  - the engine is intentionally artifact-first and read-only; no quota, tier, or ranking behavior changes were introduced
- Operator visibility in v1:
  - `dealflow discover`
  - `dealflow source`
  now render the Delta cohorts and top ranked delta symbols through the shared CLI renderer in `cli/common.py`

## Architecture Addendum (2026-03-07T19:05:00-0500) — V3 Benchmark Contract Cleanup

- The V3 benchmark philosophy remains unchanged:
  - default capital can live in the V3 index sleeve
  - active allocations must justify pulling capital away from that default
- The track-record benchmark path is now aligned to that philosophy:
  - same window as the actual track-record period
  - configured benchmark ticker, not hardcoded QQQ
  - return-based metrics for operator decisions
- `tradingagents/phase_engine/index_overlay.py` now supports explicit `date_start` / `date_end` slicing and emits both:
  - tactical point-based metrics for the portfolio V3 overlay
  - return-based metrics (`v3_total_return_pct`, `bh_total_return_pct`, `v3_cagr_pct`, `bh_cagr_pct`) for benchmarking
- `tradingagents/graph/track_record.py` now uses:
  - `DEFAULT_CONFIG["v3_benchmark_ticker"]`
  - the actual track-record window derived from `date` or `trade_date`
- `cli/commands/performance.py` now renders the benchmark as:
  - `V3 <ticker> Benchmark (Track-Record Window)`
  - window
  - V3 total return
  - buy-and-hold total return
  - V3 CAGR
  - buy-and-hold CAGR
- Architectural intent:
  - tactical overlay math stays available for the index sleeve
  - operator benchmark decisions are now made in the same unit as portfolio opportunity-cost decisions

## Architecture Addendum (2026-03-08T21:55:00-0500) — Fundamental Harness Market Attachment

- The Fundamental Pillar Autoresearch Harness now has a deterministic bridge from filing snapshots to evaluable outcomes:
  - static `large_cap_v1` sector identities in [tradingagents/research/fundamental_autoresearch/sector_map.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/research/fundamental_autoresearch/sector_map.py)
  - adjusted-close forward-return attachment in [tradingagents/research/fundamental_autoresearch/market_data.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/research/fundamental_autoresearch/market_data.py)
- Return attachment contract:
  - anchor = first tradable session on or after `effective_market_date`
  - attached fields:
    - `return_20d`
    - `return_60d`
    - `return_120d`
    - `return_252d`
- CLI contract:
  - `fundamental-research-prepare` auto-applies the static `large_cap_v1` sector map when no custom map is provided
  - `fundamental-research-attach-returns` enriches prepared rows with market outcomes without mutating the SEC prep logic
- Data-quality note:
  - yfinance dotted tickers are normalized to hyphen aliases for market downloads, e.g. `BRK.B -> BRK-B`
- Architectural read:
  - the harness is now end-to-end evaluable on real SEC + market data
  - the current latest-only dataset is too fresh for meaningful `60d+` scientific judgment
  - the next architectural milestone is historical filing snapshot backfill, not additional scorer complexity

## Architecture Addendum (2026-03-08T23:15:00-0500) — Fundamental Historical Backfill

- The Fundamental Pillar Autoresearch Harness now supports historical SEC submissions shards.
- Cache contract additions in [sec_fetch.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/research/fundamental_autoresearch/sec_fetch.py):
  - `submissions_history/<ticker>/<file>.json`
  - `fetch_submissions_history_payload(...)`
  - `cache_submissions_history_payload(...)`
  - `fill_sec_cache_for_universe(..., include_history=True)`
- Prep contract additions in [prepare.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/research/fundamental_autoresearch/prepare.py):
  - `include_history`
  - `latest_only`
  - `start_year`
- All-filings mode now:
  - loads base submissions plus cached shard files
  - deduplicates supported filings
  - builds point-in-time feature rows for all supported filings since the requested year
- CLI contract additions:
  - `fundamental-research-cache-fill --include-history`
  - `fundamental-research-prepare --all-filings --start-year <year>`
- First real historical dataset result:
  - `1611` filing snapshots for `large_cap_v1`
  - effective market dates from `2009-03-10` to `2026-03-03`
  - `1588` usable `60d` observations
  - baseline `60d` sector-neutral rank IC: `-0.055066`
- Architectural read:
  - the harness is no longer just operationally complete; it is now scientifically usable
  - the naive deterministic baseline is currently weak/negative on a real sample
  - the next architectural step is score iteration and baseline comparison, not more SEC ingestion plumbing

## Architecture Addendum (2026-03-09T09:35:00-0400) — First Universe Filter Audit

- The first universe filter remains operationally inside `discover()`, but it is now exposed as a first-class read-only operator stage.
- New module:
  - [tradingagents/dealflow/universe_filter.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/universe_filter.py)
- New artifact:
  - `eval_results/deal_flow/<date>/universe_filter.json`
- New operator surface:
  - `python3 -m cli.main universe-filter --date YYYY-MM-DD --status`
- The report standardizes the first-filter checkpoint into:
  - tier counts
  - source counts
  - overlap counts
  - explicit health checks
- Architectural intent:
  - discovery and first-universe filtering stay coupled in runtime for now
  - but the operator no longer has to infer whether the first filter ran correctly from `discover()` alone

## Architecture Addendum (2026-03-09T11:20:00-0400) — Shared Market Cache for Collectors

- Added a shared cache-first market data layer in:
  - [tradingagents/dealflow/market_cache.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/market_cache.py)
- The cache contract is per-symbol OHLCV CSV under:
  - `eval_results/deal_flow/market_cache/`
- Architectural rule:
  - collectors should read from the shared local market cache
  - only the cache layer should talk to yfinance directly
  - cached histories are refreshed by appending recent windows, not by redownloading long history every run
- Hot-path consumers patched:
  - [tradingagents/dealflow/pipeline.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/pipeline.py)
    - `_market_shock_metrics()` now reads cached `SPY` / `^VIX` history and fails open to `(None, None)` on fetch/cache issues
  - [tradingagents/dealflow/sources/price_momentum.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dealflow/sources/price_momentum.py)
    - now uses cache-backed OHLCV history for its F=MA inputs
    - current fetch contract is `min_bars=90`, `full_period=180d`, `batch_size=10`
- Important resilience improvement:
  - the cache layer normalizes both raw yfinance `DataFrame` outputs and per-symbol dict outputs so connector code can reuse it safely
- Operational result:
  - first cache-backed `collect` run still paid the cold-cache cost
  - immediate warm-cache rerun dropped `price_momentum` latency from about `47.8s` to about `4.5s`
  - remaining failures are isolated symbol-level Yahoo misses, not collector-wide rate-limit collapse

## Architecture Addendum (2026-03-09T14:25:00-0400) — Deep Analysis Provider Plug

- Deep analysis now uses an explicit two-plug provider contract:
  - `analyst_provider`
  - `post_analyst_provider`
- The analyst layer and the post-analyst graph are no longer treated as one hidden provider decision.
- New GPT post-analyst graph backend:
  - [tradingagents/dataflows/codex_cli.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/dataflows/codex_cli.py)
  - `ChatCodexCLI` wraps `codex exec` as a LangChain-compatible chat model using output-file capture to avoid noisy stdout parsing
- [tradingagents/graph/trading_graph.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/graph/trading_graph.py) now supports `codex_cli` as a first-class provider for deep and quick post-analyst execution.
- [tradingagents/graph/codex_research_bridge.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/graph/codex_research_bridge.py) is now a provider-aware analyst bundle layer:
  - `gpt`
  - `claude`
  - `grok_manual`
  with provider-specific artifact directories and manual readiness checks.
- New operator surface:
  - [cli/commands/research_analysts.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/cli/commands/research_analysts.py)
  - commands:
    - `research-analysts --generate`
    - `research-analysts --status`
    - `research-analysts --ingest`
- [cli/commands/scoring.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/cli/commands/scoring.py) now exposes:
  - `--analyst-provider`
  - `--post-analyst-provider`
  on both `analyze` and `retired post-scout batch command`
- Current supported combinations:
  - `GPT analysts + Claude post-analyst`
  - `GPT analysts + GPT post-analyst`
  - `Claude analysts + Claude post-analyst`
  - `Grok manual analysts + GPT post-analyst`
  - `Grok manual analysts + Claude post-analyst`
- `Gemini` is intentionally surfaced only as a future placeholder and remains blocked in v1.
- Architectural rule:
  - LLMs are the plug
  - prompts are the play
  - no hidden provider fallback should decide the deep-analysis stack during audit-sensitive runs

## Architecture Addendum (2026-03-09T19:35:00-0400) — Qwen Feature Lab

- Qwen should not be used for tiny enumerable weight spaces that can be brute-forced more cheaply and more reliably.
- The deterministic SEC filing harness remains the judge; Qwen is the bounded proposer.
- Added a bounded Qwen Feature Lab:
  - [tradingagents/research/fundamental_autoresearch/qwen_feature_lab.py](/Users/aeternusholdings/Documents/AeternusAgents-opus46/tradingagents/research/fundamental_autoresearch/qwen_feature_lab.py)
- The feature lab keeps the canonical base strategy fixed:
  - `health_0p5__inv_growth_0p1__inv_quality_0p4`
- Qwen is only allowed to propose bounded overlays from a fixed experimental component catalog:
  - `growth_acceleration`
  - `margin_expansion`
  - `quality_tension_inverse`
  - `balance_sheet_resilience`
- Architectural rule:
  - brute force tiny weight spaces
  - use Qwen for bounded feature / interaction proposal work
  - keep promotion / registry governance above the live connector

## Architecture Addendum (2026-03-10T15:20:00-0400) — Replay-First KAMA Experiment

- KAMA should enter the system the same way FVG and FMA did:
  - replay first
  - live promotion later only if the measured edge is real
- Added a replay-only module:
  - `tradingagents/dealflow/kama_recall.py`
- Added operator surface:
  - `python3 -m cli.main kama-backtest`
- Current contract:
  - bullish KAMA event = `(1,10,15)` KAMA crossing above `(2,10,15)` KAMA
  - outputs:
    - `event_summary`
    - `basket_summary`
    - `overlap_summary`
    - `union_summary`
- Architectural rule:
  - KAMA is currently evidence and recall research only
  - it is not yet a live discovery source or direct portfolio admission trigger
  - promotion should depend on measured overlap/uniqueness versus existing FVG/FMA recall channels

## Architecture Addendum (2026-03-10T20:55:00-0400) — KAMA Trigger, FVG Regime

- The replay boundary for KAMA was tightened:
  - `FVG` defines regime
  - `KAMA` is the trigger inside the regime
- Current regime contract in `tradingagents/dealflow/kama_recall.py`:
  - bullish FVG increments a bullish streak
  - bearish FVG resets the regime immediately
  - regime expires after `20` bars without a new bullish FVG
- Architectural rule:
  - do not treat `KAMA + FVG` as loose same-day overlap
  - evaluate `KAMA cross inside bullish FVG regime` as the actual candidate admission pattern

## Architecture Addendum (2026-03-11T11:00:00-0400) — Technical Signal Cache v1

- Added a new operational boundary for technical screening:
  - current-universe membership
  - cached OHLCV history
  - canonical daily `KAMA + bullish FVG regime` state
  - current buy-zone snapshot
- Persistence contract:
  - SQLite DB at `eval_results/control/technical_signal_cache.db`
- First tables:
  - `universe_membership_current`
  - `market_history_daily`
  - `signal_kama_fvg_daily`
  - `buy_zone_state_current`
- Architectural rule:
  - live technical screening should query cached state first, not rerun ad hoc full-history replays
  - replay research and current-state screening should share the same signal computation path
- Current operator surface:
  - `technical-universe-refresh`
  - `technical-signal-sync`
  - `buy-zone`
  - `buy-zone-summary`
- Scope note:
  - v1 intentionally uses current constituents only for `SPY + QQQ + DOW`
  - historical statistics from this engine must be labeled `current-constituent replay`
  - point-in-time membership reconstruction remains a later research-quality upgrade

## Architecture Addendum (2026-03-11T12:43:15-0400) — Yahoo Symbol Status in Technical Cache

- Added a new technical-cache persistence layer:
  - `yahoo_symbol_status`
- Purpose:
  - distinguish truly invalid Yahoo symbols from valid names with later listing dates
  - stop re-fetching known-empty pre-history windows
- Stored fields:
  - `is_invalid`
  - `invalid_reason`
  - `no_data_before_date`
  - `checked_through_date`
  - `updated_at_utc`
- Operational rule:
  - if a ticker has valid history, cache the first available bar as `no_data_before_date`
  - future syncs must skip prepend windows fully before that date
  - only mark a ticker invalid if recent Yahoo validation is also empty
  - invalid names must be purged from the technical current-universe cache and excluded from future universe refreshes / syncs
- Architectural effect:
  - current-universe screening is now quieter and deterministic across reruns
  - “possibly delisted” Yahoo noise is no longer treated as equivalent to a dead symbol

## Architecture Addendum (2026-03-11T13:10:00-0400) — Structured Grok Macro Cache

- The manual Grok macro workflow now uses a richer persisted schema in `macro_cache_<date>.json`.
- Purpose:
  - preserve Grok’s higher-quality web/X evidence instead of collapsing everything into sector scores only
  - keep the downstream macro collector contract stable
- New persisted fields:
  - `regime`
  - `summary`
  - `sources_cited`
  - `dimensions`
  - `sectors`
- `dimensions` now store the 8 macro inputs explicitly, each with:
  - `signal`
  - `current_value`
  - `trend`
  - `rationale`
  - `sources_cited`
- Operational rule:
  - macro ingest should be strict and reject incomplete Grok payloads
  - macro scoring in `dealflow/sources/macro.py` remains sector-score-driven and ignores richer fields unless later surfaced in audits/briefs
- Architectural effect:
  - Grok becomes a higher-fidelity macro evidence source without breaking `collect`
  - future audit/brief/report layers can consume saved macro dimensions directly from cache

## Architecture Addendum (2026-03-11T15:35:00-0400) — Earnings/Options Scout in Discover, IV Math in Collect

- The earnings/options workflow now uses a split boundary:
  - `manual Grok scout` in discovery
  - `deterministic IV divergence collector` in collect
- New manual artifact:
  - `earnings_options_scout_<date>.json`
- Purpose:
  - let Grok handle public X/web recall for earnings/options setups
  - keep exact option-chain and historical-earnings math as deterministic confirmation

- Discovery rule:
  - `discover()` should only use the manual earnings/options artifact as a scout contribution
  - discovery must not run the expensive quantitative IV scan by default
  - promoted symbols receive a dedicated universe tier:
    - `T3E_EARNINGS_OPTIONS`

- Collector rule:
  - exact earnings-window checks and implied-vs-historical move math belong in `collect`
  - the signal family is:
    - `earnings_iv_divergence`
  - this is a normal scored connector, not a force-queue override

- Migration rule:
  - legacy discover-time IV scan is now default-off
  - legacy IV force-queue injection is now default-off
  - legacy helpers remain available behind config flags for controlled fallback/debugging

- Architectural effect:
  - scout stage becomes cheaper and higher-recall
  - collector stage becomes the correct home for exact event-volatility confirmation
  - Grok is used where it has edge (public X/web search), while deterministic math remains the trust anchor

## Architecture Addendum (2026-03-11T18:05:00-0400) — Manual X-Feed Is The Only Live Social Source; Yahoo Earnings IV Removed

- The March 11 follow-up simplified the design further:
  - the manual Grok earnings/options scout remains
  - the Yahoo-finance `earnings_iv` collector path is removed from active dealflow behavior
  - `social_news` now reads only from manual X-feed merged artifacts

- Operational rule:
  - manual X-feed is now the single live source of `social_momentum` and `news_catalyst`
  - there is no xAI social cache/API dependency in the live collector path
  - there is no live `earnings_iv` connector in `collect`
  - the old `earnings-scan` CLI surface is removed

- Architectural effect:
  - operator-curated Grok research is the source of truth for public social/news context
  - the pipeline is simpler and cheaper because it no longer runs a low-value Yahoo options-volatility pass
  - the remaining legacy `iv_scanner.py` module exists only as a compatibility stub for tests/imports and is not part of active runtime behavior

## Architecture Addendum (2026-03-12T11:35:00-0400) — Workflow Learning Is Fail-Open; Source Attribution And Observed Edges Are First-Class Artifacts

- The workflow now has an explicit post-run learning phase:
  - hindsight
  - performance review / `signal_family_ic`
  - signal-family weight writeback
  - source attribution build
  - observed edge reinforcement

- Policy:
  - learning is **fail-open**
  - market operations are not blocked by hindsight/backfill issues
  - workflow marks `COMPLETED_WITH_LEARNING_DEGRADED` when the learning phase cannot finish cleanly
  - weight activation is still **fail-closed** for malformed outputs

- New artifacts:
  - `eval_results/deal_flow/<date>/learning_status.json`
  - `eval_results/deal_flow/<date>/source_attribution.json`
  - `eval_results/control/ic_signal_weights.json`

- Learning writeback:
  - `signal_family_ic` is now the measured source-quality input for deal-flow weight adjustments
  - the writeback is conservative, sample-gated, bounded, and skip-safe
  - no new control file is written when data is insufficient

- Graph growth:
  - the first observed-edge builder is intentionally narrow and high precision
  - explicit `$TICKER` mentions inside manual X-feed catalyst text reinforce AKG `co_mentioned` edges
  - this is meant to grow decision-useful relationships, not chase raw edge count

## Architecture Addendum (2026-03-12T12:10:00-0400) — `workflow-run` Now Has An Explicit Human-Operated Interactive Mode

- The workflow boundary is now explicit:
  - default `workflow-run` remains machine-friendly and non-interactive
  - human-guided runs use:
    - `workflow-run --interactive --mode manual`

- Interactive mode is intentionally separate rather than changing default behavior:
  - automation and loop tooling must not block on stdin
  - operators do need staged prompts, validation, and immediate progress feedback

- Manual artifact policy in interactive mode:
  - X-feed
  - macro
  - earnings/options
  - are handled directly inside the workflow command instead of requiring separate operator commands

- UX contract:
  - prompts are printed inline
  - pasted JSON ends with `END`
  - each manual stage validates and ingests before advancing
  - scouts / collectors / analyze / portfolio / learning now emit short stage summaries

- Architectural effect:
  - one workflow surface now serves both machine-mode and operator-mode cleanly
  - the pipeline stays composable for automation
  - the operator is no longer blind during manual daily runs

## Architecture Addendum (2026-03-15T15:30:00-0400) — Scout Compiler And Scenario Retriever Become The Planned Bridge Between Ambient Sensing And Scenario Runtime

- The MiroFish audit clarified the missing Aeternus layer:
  - Aeternus already has stronger ambient sensing, AKG memory, and learning loops
  - MiroFish is ahead on question-conditioned compilation into a temporary scenario world
  - the planned bridge is:
    - `Scout Compiler`
    - `Scenario Retriever`

- Planned `Scout Compiler` role:
  - runs after scouts
  - compiles multi-scout evidence into daily scenario artifacts / `Event Card` JSON
  - normalizes entities, extracts events, consolidates narratives, emits scenario seeds
  - starts as a **shadow sidecar** so it does not change current pipeline behavior initially

- Planned `Scenario Retriever` role:
  - exists from day 1 as a separate lane from the compiler
  - searches internal state first:
    - daily compiled scenario artifacts
    - AKG
    - universe
    - portfolio
    - cached research artifacts
  - returns coverage states:
    - `COMPLETE`
    - `PARTIAL`
    - `MISSING`

- Operating rule:
  - if coverage is incomplete, the retriever must list missing evidence and wait for the user
  - it must **not** automatically trigger external/API scouting, to avoid waste and preserve operator control

- Product implication:
  - every daily run should become a daily scenario
  - cross-scout relationships can become first-class signal artifacts before a full scenario runtime exists

## Architecture Addendum (2026-03-15T16:05:00-0400) — `v1` Scenario Layer Is Artifact-Only, With Automatic Coverage Precheck And Manual Retrieval

- The first concrete contracts are now locked:
  - automatic:
    - `Scout Compiler`
    - `Coverage Precheck`
  - manual/on-demand:
    - `Scenario Retriever`

- `v1` non-interference policy:
  - the new layer is sidecar-only
  - it must not change universe construction, collector inputs, scoring, candidate_list, or portfolio behavior
  - it must not mutate AKG in `v1`

- Approved sidecar artifacts:
  - `eval_results/deal_flow/<date>/event_cards.json`
  - `eval_results/deal_flow/<date>/coverage_precheck.json`
  - `eval_results/deal_flow/<date>/scout_compiler_debug.json`
  - `eval_results/deal_flow/<date>/akg_writeback_candidates.json`

- `akg_writeback_candidates.json` is preview-only:
  - it exists so compiler-inferred durable relationships can be inspected before any future AKG writeback is allowed
  - it is not a recommendation artifact and must not affect live pipeline decisions

## Architecture Addendum (2026-03-15T16:45:00-0400) — `Scout Compiler v1` And `Scenario Retriever v1` Are Now Live As A Shadow Scenario Layer

- The planned bridge is now implemented in code as a non-interfering `v1` scenario layer:
  - `tradingagents/dealflow/scout_compiler.py`
  - `tradingagents/dealflow/scenario_retriever.py`
  - `tradingagents/dealflow/scenario_contracts.py`
  - `tradingagents/dealflow/scout_quality.py`

- Runtime behavior:
  - `discover()` now automatically runs a shadow `Scout Compiler` at the end of the scout/discovery phase
  - it does not alter universe construction, collectors, scoring, candidate_list, or portfolio behavior
  - it emits:
    - `event_cards.json`
    - `coverage_precheck.json`
    - `scout_compiler_debug.json`
    - `akg_writeback_candidates.json`
    - `scout_quality_daily.json`

- `Scenario Retriever v1` is CLI-first and internal-only:
  - command:
    - `python3 -m cli.main scenario-retrieve --date <YYYY-MM-DD> --question "<question>" --format json`
  - it searches internal daily artifacts first
  - it returns:
    - `COMPLETE`
    - `PARTIAL`
    - `MISSING`
  - it never auto-runs scouts or external retrieval
  - on coverage gaps, it lists missing evidence and waits for the user

- `Scout Compiler v1` compilation policy:
  - deterministic theme grouping, not one-card-per-symbol
  - generic singleton x-feed records are skipped
  - grouped daily themes currently include:
    - geopolitical / defense / oil
    - AI infrastructure / leading-indicator clusters
    - private-credit stress
    - nuclear / uranium
    - biotech regulatory
    - unusual options flow
    - daily breakout cluster
    - technical recall cluster
    - earnings/options cluster

- `Scenario Retriever v1` retrieval policy:
  - broad “what matters today?” questions return top-ranked Event Cards rather than matching all cards
  - ranking is based on confidence, coverage score, source breadth, direct-entity breadth, and portfolio relevance

- `Scout Quality v1` now measures grouped source contribution:
  - uses direct scout detections when available
  - falls back to grouped `source_records` inside Event Cards so manual X-feed and grouped scenario sources are still measurable

- Important reliability fix:
  - `discover()` had been silently failing scout-audit creation because `_iv_results` was referenced before initialization in the post-IV-removal path
  - fixing that restored breakout and earnings-options evidence into:
    - `scout_audit.json`
    - discovery delta
    - universe-filter readiness
    - scenario sidecar artifacts

- Retrieval rule:
  - if internal coverage is incomplete, the retriever must list missing evidence and wait for the user
  - it must not automatically trigger external/API scouting, to avoid waste and preserve operator control

## Architecture Addendum (2026-03-17T20:42:31-0400) — Operator Gateway Becomes MissionControl Scaffold (E2E Stage Map + Scout Control API)

- `operator_gateway` now has a first MissionControl surface designed for eventual end-to-end orchestration visibility, not scout-only control.

- New gateway contracts were added:
  - `MissionControlResponse` with stage-level telemetry
  - `ScoutInventoryResponse`, `ScoutDetailResponse`, `ScoutPromptResponse`, `ScoutIngestResponse`
  - `OperatorGatewayNotFoundError` for clean 404 behavior on unknown scout IDs

- New API surfaces now live in `operator_gateway`:
  - `GET /ops/mission-control`
  - `GET /ops/scouts`
  - `GET /ops/scouts/{scout_id}`
  - `GET /ops/scouts/{scout_id}/prompt`
  - `POST /ops/scouts/{scout_id}/ingest`

- MissionControl stage model currently maps the full daily pipeline chain:
  - `scouts`
  - `discover`
  - `collect`
  - `research`
  - `portfolio`
  - `execution`
  - `learning`

- Pathing decision:
  - gateway now resolves artifacts from configured roots (via `operator_gateway_dealflow_base_dir`) and derives sibling roots for `x_feed`, `paper_execution`, and `live_execution`.
  - this keeps operator telemetry coherent across local/dev sandboxes and avoids hard-coding `eval_results/...` assumptions in the gateway layer.

- Manual scout ingest decision:
  - macro and earnings/options ingest writebacks are now normalized through gateway-managed paths so they honor configured dealflow roots.
  - manual x-feed ingest remains routed through existing `x_feed_manual.ingest_pass(...)` behavior for v1 compatibility.

## Architecture Addendum (2026-03-18T08:02:52-0400) — Question Investigation Now Emits Stage-Native Miss Reasons

- `question-investigate` no longer returns only `FOUND/MISS` stage markers.
- `tradingagents/dealflow/investigation_runner.py` now emits deterministic stage diagnostics with:
  - `reason_code`
  - `reason_text`
  - `threshold`
  - `observed_value`
  - `delta_to_pass`
  - `artifacts`

## Architecture Addendum (2026-05-13T17:10:02-04:00) — Fundamental Review List Can Start From SEC Universe

- Fundamental daily runs can now build the review stock list from the SEC company ticker map instead of inheriting the old historical ticker list.
- Operator switch: `fundamental-run-today --build-review-list-from-sec`.
- The new review-list filter lives in `tradingagents/research/fundamental/src/daily_run/review_list_filter.py`.
- Required keep rules:
  - earnings `8-K`
  - press-release exhibit
  - periodic filing
  - core company data needed before scoring
  - raw Yahoo OHLCV
  - raw close `>= 2`
  - `ADV60 >= 500,000` shares
- Rejected tickers are saved with clear reasons in `review_stock_list_rejections_<quarter>.csv`.
- Review-list price checks use cached parquet data by default from `/Users/aeternusholdings/.cache/autoresearch_fundamentals`.
- Live Yahoo review-list fetch is disabled unless `--allow-live-review-price-fetch` is passed.
- 2026Q2 cache-only count result: `10,348` SEC map names -> `1,148` strict SEC-ready -> `1,132` company-data-ready -> `1,115` cached-price names -> `791` final after close/ADV.

- The investigation backend now consumes hypothesis-ledger evidence for reject reasoning where available:
  - `universe_gate_edge` / `universe_gate_haystack`
  - `evidence_gate`
  - `candidate_list_cut`
  - `fundamental_intake_cut`

- This closes the major observability gap captured in the 2026-03-17 savepoint:
  - before: robust `where` diagnostics, weak `why` precision
  - now: stage-level deterministic miss reasons for the core discovery/selection funnel

- Additional candidate_list precision:
  - reconstructed score ranks from `legacy_scored_artifact` to quantify candidate_list cutoff misses
  - includes anomaly detection when a symbol ranks inside `top_k` but is absent from candidate_list output

## Architecture Addendum (2026-03-18T20:20:54-0400) — Session Engine Now Persists Pre/Post LLM Score Influence

- `tradingagents/graph/session_research_engine.py` now explicitly separates:
  - deterministic base scoring before the LLM synthesis call
  - final scoring after LLM outputs are available

- Implementation detail:
  - base score: `build_session_score(computation_data, {})`
  - post-LLM score: `build_session_score(computation_data, normalized_outputs)`
  - persisted diagnostics: `aeternus_score.llm_influence`

- `llm_influence` contract captures exactly where LLM changed outcomes:
  - `base_score_pre_llm`, `final_score_post_llm`, `score_delta`
  - `base_confidence_pre_llm`, `final_confidence_post_llm`, `confidence_delta`
  - per-component debate deltas:
    - `research_debate`
    - `trader_verdict`
    - `risk_verdict`
  - report completeness counts

- Operational effect:
  - score influence from LLM overlays is now observable/auditable at report time instead of being implicit.

## Architecture Addendum (2026-03-20T18:22:00-0400) — Harness v1 Is Now the Canonical Product Unification Layer

- Aeternus now has an explicit harness architecture plan that unifies the existing components under one runtime contract:
  - `/Users/aeternusholdings/Documents/AeternusAgents-codex/docs/plans/2026-03-20-aeternus-harness-v1.md`

- Core architectural shape locked:
  - single entry runtime (`/harness/query`)
  - mode compiler (`DECIDE`, `SCENARIO`, `DIAGNOSE_MISS`, `PORTFOLIO_ACTION`)
  - deterministic run state machine with progress events
  - manual WAIT/RESUME loop for human-input scouts
  - policy-gated outputs with numeric triggers
  - replayable run artifacts linked to hindsight/learning

- Strategic grounding memo added:
  - `/Users/aeternusholdings/Documents/AeternusAgents-codex/docs/research/2026-03-20-perplexity-manus-harness-review.md`
  - captures what to adopt from Perplexity Computer and Manus harness patterns, and what Aeternus should intentionally not copy (generic breadth over decision quality).

## Architecture Addendum (2026-04-27T00:00:00) — Macro Backtest v1 Is Research-Only and Pure-Core

- Macro framework validation now has a dedicated research-only backtesting package:
  - `tradingagents/backtesting/macro/`
  - orchestration script: `scripts/backtest_macro_framework.py`

- Architectural boundary:
  - pure modules accept preloaded pandas data and do not perform network I/O
  - script handles yfinance/FRED CSV loading and artifact writing
  - outputs must carry the disclaimer `research_only_not_true_pit_unless_inputs_are_vintage_or_release_aligned`

- Default forward-return horizons are now:
  - `(5, 10, 20, 30, 60, 90)` trading days

- Bias controls in v1:
  - signal returns enter on the next trading bar after snapshot date
  - snapshots slice price/FRED-like data at or before as-of date
  - optional FRED release lag is supported, but true PIT requires vintage/release-aligned inputs
  - missing SPY price history fails closed

- Dealflow macro ablation contract:
  - macro-on uses candidate subscores as supplied
  - macro-neutral forces `macro_regime_fit=50`
  - downstream core/momentum/asymmetry/lane values are recomputed
  - selection uses production `legacy_rank_function`, not a standalone score sort

## Architecture Addendum (2026-05-14T00:00:00) — Fundamental Daily Run Is the Single Recovery Path

- `fundamental-run-today` is the main daily path for the fundamental framework; do not create a separate recovery pipeline for normal daily needs.
- Daily dealflow tickers are checked against the main list, then resolved to ticker/company/CIK before Gate 2; unresolved new names are rejected before scoring with a clear reason.
- The current-quarter master JSON is the full combined daily list and is the JSON handed to later SEC coverage steps.
- SEC/Yahoo gaps are handled inside the daily run:
  - companyfacts fallback uses shared `cache/sec/facts_TICKER.json`.
  - raw SEC document fallback uses shared SEC raw document roots.
  - price lookup checks cache first, fetches only missing names, then writes fetched rows back to cache.
- LLM evidence recovery happens before packet hard-stop; default SEC fetch only runs when a fetch queue/service exists.
- Daily status/reason output is `daily_ticker_status.csv`.
- Broad-final Gate 7 must hard-stop when LLM-required rows remain without usable evidence after recovery; those rows cannot silently bypass Gate 8.
- Persistent master additions ledger is for resolved new dealflow tickers that reached final scored rows after successful publish, not merely tickers resolved at Gate 2.
