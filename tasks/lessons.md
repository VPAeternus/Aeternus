# Lessons Learned

Patterns to avoid. Review at session start.

**Observation counter:** 16 active lessons (4 graduated to rules on 2026-03-04).
**Threshold:** At ≥8 lessons, Opus must re-read this file before the next architectural decision and flag the review to the user.

---

### 2026-03-03: Plans must default to non-technical presentation

**What happened:** S-082 plan was presented as a technical spec with file paths, line numbers, and code snippets. User corrected: the default mode for plan presentation is non-technical — explain WHAT is being built and WHY in terms the operator can evaluate, not raw implementation details.

**Rule:** When presenting a plan before implementation, lead with the business impact and plain-language description. Technical details (files, line numbers, code) belong in the implementation, not the pitch. The operator needs to understand the change and approve — they don't need to review the diff upfront.

**Applies to:** All plan presentations, task explanations, and pre-implementation proposals.

---

### 2026-03-02: Designed 3 LLM calls where 1 was sufficient

**What happened:** S-076 x_feed_scout was initially spec'd with 3 separate xAI x_search calls using near-identical prompts. One prompt combining all three signal angles gets the same or better result at 1/3 the cost.

**Rule:** Before designing any multi-call LLM pattern, ask: *"Are these calls asking the same underlying question from slightly different angles?"* If yes, consolidate into one prompt. Cost: 1/N. Quality: unchanged or better.

**Applies to:** Any pay-per-call LLM integration. The principle is model-agnostic.

---

### 2026-02-24: Sonnet subagent used 292 tool calls for mechanical replacements — 1.5 hours

**What happened:** Delegated fixing 41 broken patch targets to a Sonnet subagent with a mapping table. Sonnet re-derived the mapping from scratch (292 tool calls). Two Haiku agents completed equivalent-complexity fixes in under 60 seconds each.

**Rule:** For mechanical bulk replacements, give a **directive prompt**, not a research prompt. Use Haiku for pure find-replace — Sonnet over-thinks it. Never let subagents re-investigate when the answer is already known.

**Applies to:** All patch-target fixes, bulk renames, mechanical refactors.

---

### 2026-02-28: Answered financial architecture question from summary, not code

**What happened:** User asked "do V3 and S7a/b overlap?" Answered from subagent summary without reading code. V3 = bull/neutral longs, S7 = bear shorts — clearly opposite regimes. The strategy-first skill would have caught this.

**Rule:** The strategy-first skill applies to ALL financial questions. Read code before answering. "State the strategy in one sentence" surfaces contradictions immediately.

**Applies to:** Every financial/trading question.

---

### 2026-03-02: CC Wyckoff order intents defaulted to enabled with no backtest validation

**What happened:** `CCWyckoffPhaseEngine` was generating automated SELL orders with a 46.5% bleed rate — worse than a coin flip.

**Rule:** Never deploy automated order generation for signals with win rate < 50%. Backtest first with per-signal breakdown. If < 50% hit rate → display-only advisory, not order intent pipeline.

**Applies to:** All execution-grade signal systems.

---

### 2026-03-02: Sentiment data gap depressed coherence scores across all 8 analyzed tickers

**What happened:** Avg sentiment score 39/100 across 8 tickers was a data-quality issue, not bearish signal. Dragged coherence to 46/100, preventing everything from clearing V3 hurdle.

**Rule:** Sentiment score ≤40/100 across ≥5 tickers in a cycle = flag as data gap, not alpha signal. Never allow data scarcity to block all positions.

**Applies to:** AeternusScore pillar weights, coherence engine, V3 hurdle.

---

### 2026-03-02: Large-cap scoring bias — social_momentum + news_catalyst = 30% weight

**Rule:** Acceptable as long as scored explicitly. Review if 3+ consecutive cycles show no mid-cap names in research queue.

**Applies to:** Deal flow scoring, research queue ranking.

---

### 2026-03-02: Proactively trace data dependencies — dead fields waste engineering time

**Rule:** After building anything that writes data, trace: **who reads these fields?** If nothing reads them, the write is dead code. Trace the full read-write chain before shipping.

**Applies to:** Any data pipeline, AKG field writes, connector outputs, scorer inputs.

---

### 2026-03-02: 0DTE CC roll timing — roll at extrinsic < 10% of credit, not at expiry

**Rule:** On 0DTE CCs, the roll trigger is "extrinsic < 10% of original credit." Once underlying crosses strike by >1 credit premium, you are paying intrinsic, not theta. Use `roll_check` command. Do not chase.

**Applies to:** All 0DTE CC positions.

---

### 2026-03-04: Breakout volume weight was inversely correlated with forward returns

**What happened:** Backtest of breakout discovery scanner (6,183 events, 30 mega-caps, 10 years) showed volume ratio at breakout is inversely correlated with forward returns. Quiet breakouts (vol < 1x) had 65.2% win rate at 60d, vs 54.5% for 3x+ volume. The volume component (30% weight) was actively promoting worse-performing events.

**Fix:** Zeroed volume weight in scoring formula. Redistributed 30 points to near_high component (40→70). Score = near_high(70) + trend(30). Backtest script: `scripts/backtest_breakout_discovery.py`.

**Rule:** Backtest signal components individually before weighting them. "Intuitive" inputs (e.g., heavy volume confirms breakout) can be empirically wrong. Always measure forward returns by component bucket.

**Applies to:** All signal scoring formulas, any new connector weight assignments.

---

### 2026-03-04: Never override established cost figures with one-off observations

**What happened:** Memory file states xAI x_search = $0.005/call. User reported one run cost "0.22 cents." Instead of using the established $0.005 figure, I adopted "0.22 cents" as the new canonical cost and repeated it multiple times — fabricating a number from a single observation.

**Rule:** Established cost/pricing figures in memory or docs are the source of truth. A single observation does not override them. If an observed cost differs from the documented cost, note the discrepancy — don't silently adopt the new number as fact. Never echo back a user's number as if you independently verified it.

**Applies to:** All cost estimates, pricing quotes, financial figures, performance metrics — any number with an authoritative source.

---

### 2026-03-04: Swapped return values in _market_shock_metrics — VIX labeled as SPY

**What happened:** `_market_shock_metrics()` returns `(spy_move, vix_jump)` but the caller unpacked as `vix_jump, spy_move = ...`. VIX dropped -12.3% (normal behavior), but pipeline labeled it "SPY move -12.30%" and falsely triggered an event. I then repeated the false claim to the user ("SPY dropped 12%") without checking whether that was remotely plausible.

**Fix:** Swapped unpacking order on pipeline.py line 910 to `spy_move, vix_jump = ...`.

**Rule:** When a financial metric looks extreme (SPY -12% in a day = historic crash), sanity-check it before repeating it. A 12% single-day SPY move has happened ~3 times in history. If something looks extraordinary, verify the data pipeline, don't just announce it.

**Applies to:** All financial data assertions, event trigger outputs, any number that crosses an implausibility threshold.

---

### 2026-03-04: Never override V3 benchmark hurdle without user approval and proven data

**What happened:** Lowered portfolio-plan `--min-score` from 62.0 to 60.0 to include more tickers. This let COHR (61.1) and HCA (60.4) into the plan — both below the V3 benchmark hurdle. There's no point selling QQQ to buy something that can't beat it.

**Rule:** The V3 hurdle (currently 62.0) is a hard gate. Never override it. Only adjust it with proven hindsight data showing the threshold should move. The hurdle exists to ensure every position justifies its opportunity cost vs holding QQQ.

**Applies to:** All portfolio-plan runs, min-score parameters, any threshold that gates capital allocation.

---

### 2026-03-04: Recommended statistical tools without checking data thresholds

**What happened:** After analyzing a quant career article, recommended 4 quantitative enhancements: Bayesian coherence updating, eigendecomposition for position sizing, statistical significance tests, and ADF stationarity tests. Three of four fail the same test: we don't have enough data to calibrate them. N=2 hindsight cycles, 6-12 positions, paper trading — the deferred triggers in the system already gate these capabilities behind data thresholds (10, 30+ closed trades) for exactly this reason.

**Specific failures:**
- Bayesian updating: 120 possible pillar orderings, uncalibrated likelihoods = weighted average with extra opacity
- Eigendecomposition at N=8 positions: estimation error on small covariance matrices dominates any signal
- ADF test: wrong tool entirely — prices always have unit root, returns always don't. The real question (has signal-return relationship changed?) needs structural break tests or rolling IC

**Rule:** Before recommending any quantitative tool, check: *"Do we have enough observations to calibrate this?"* Every statistical method has a minimum sample size. If we're below it, the tool produces noise, not insight. Respect the deferred triggers already in the system — they exist because this question was already answered.

**Applies to:** All quantitative/statistical recommendations, evidence layer enhancements, any proposal involving estimation from data.

---

### 2026-03-05: Opus acting as expensive secretary — executing plans without architectural ownership

**What happened:** User handed a complete implementation plan. I implemented it mechanically, ran the tests, reported success. Then when asked to evaluate a workflow prompt, I produced a comparison table and said "you already have it" — passing the ball back. That's Sonnet work. The Architect tier exists to see the system, find gaps proactively, connect dots across subsystems, and drive the roadmap. Not to wait for instructions.

**Specific failures:**
- Didn't check what the discover/collect decomposition unlocks or breaks across the rest of the system
- Didn't look at whether the scheduler (`DealFlowScheduler`) should use `discover()`/`collect()` independently
- Didn't check if other test files that call `run()` still pass
- Didn't think about what to build next — just sat there waiting
- When reviewing the workflow prompt, did analysis instead of action

**Rule:** After completing any task, the Architect must answer three questions before reporting done: (1) What does this change unlock or break elsewhere in the system? (2) What's the next highest-leverage thing to build? (3) What gap did I just discover that the operator hasn't seen yet? If you can't answer all three, you haven't finished thinking.

**Applies to:** Every task completion, every session. This is the difference between Opus and Sonnet.

---

### 2026-03-05: `claude -p` cannot nest inside Claude Code sessions

**What happened:** `analyze-batch` with `claude_cli` provider spawns `claude -p` subprocesses. These inherit the `CLAUDECODE` env var from the parent Claude Code session, causing every subprocess to exit with code 120 ("cannot launch inside another session"). All 14 tickers silently failed. The earlier "provider mapping" fix was necessary but not sufficient — the real blocker was nesting.

**Root cause:** The `ChatClaudeCLI` class runs `subprocess.run(["claude", "-p", ...])` which inherits environment. Claude Code CLI v2+ blocks nested sessions by detecting `CLAUDECODE` in env.

**Workaround applied:** Use session mode (`/session-analysis` skill) when inside Claude Code — this uses Sonnet subagents instead of `claude -p` subprocesses. `analyze-batch` with `claude_cli` provider works fine from a standalone terminal.

**Rule:** When running inside a Claude Code session, always use session mode for deep analysis. Reserve `analyze-batch --selected-only` for standalone terminal execution (e.g., cron jobs, manual runs outside Claude Code). The two modes produce identical output format — downstream tools (`portfolio-plan`, `execute-paper`) don't care which path generated the report.

**Applies to:** Any command that uses `ChatClaudeCLI` (i.e., `llm_provider=claude_cli`) — currently `analyze`, `analyze-batch`, `workflow-run`.

---

## Graduated Lessons (absorbed into rules files, 2026-03-04)

- ~~Plan persistence~~ → `workflow.md` §Plan Persistence
- ~~Task sizing ≤3 files, ≤5 min~~ → `workflow.md` §Task Sizing
- ~~Model tier delegation~~ → `workflow.md` §Subagent Strategy + `CLAUDE.md`
- ~~Hooks format schema~~ → `settings.json` is now correct; lesson obsolete
