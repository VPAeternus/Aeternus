# S-030 — Cost/Quality Frontier: Compressor + Model Tiering

**Status:** pending
**Assignee:** Sonnet (builder)
**Reviewed by:** Opus
**Branch from:** feature/opus46

---

## Goal

Operate at the edge of the quality singularity — eliminate every token that is noise, keep every token that is signal. Target: $2.50 → ~$0.40/run on Anthropic Sonnet+Opus mix, without degrading investment decision quality.

Two independent optimizations:
1. **Compressor** — Replace full analyst report injections with compact `key_claims` structs generated deterministically from computed metrics
2. **Model Tiering** — Route debate nodes to a configurable mid-tier LLM; keep judgment/synthesis nodes at full tier

---

## Background: What the Code Audit Found

Five nodes inject all 4 full analyst reports (`market_report`, `sentiment_report`, `news_report`, `fundamentals_report`) directly into their prompts, **in addition to** the already-present `evidence_brief`:

| Node | Full reports injected? | evidence_brief present? |
|---|---|---|
| `bull_researcher.py` | ✅ YES — all 4 | ✅ yes |
| `bear_researcher.py` | ✅ YES — all 4 | ✅ yes |
| `aggresive_debator.py` | ✅ YES — all 4 | ✅ yes |
| `conservative_debator.py` | likely YES (same pattern) | ✅ yes |
| `neutral_debator.py` | likely YES (same pattern) | ✅ yes |
| `research_manager.py` | ❌ NO — already clean | ✅ yes |
| `trader.py` | ❌ NO — already clean | ✅ yes |
| `risk_manager.py` | ❌ NO — already clean | ✅ yes |

**Existing `evidence_brief` already carries:** F-Score, ROE, Fwd P/E, Current Ratio, D/E, FCF, sentiment polarity, buzz, macro regime, momentum subscores. This is structured numeric signal.

**What full reports add that evidence_brief does NOT:** The Reviewer's *interpretive conclusions* — e.g. "Momentum acceleration zero-crossed to positive 3 days ago, suggesting early regime flip" or "Despite high P/E, expanding margins justify the multiple." This qualitative interpretation lives in the report prose, not in the metrics dict.

**Therefore:** We cannot simply drop the reports. We need a `key_claims` struct — a compact (3-5 bullet) distillation of the Reviewer's interpretive conclusions, generated from the computed metrics dict in deterministic Python (zero extra LLM calls).

---

## Architecture: The Compressor Pattern

### key_claims Format (per dimension)

**Implementation approach: Python formatters from computed metrics dicts. No extra LLM calls.**

**Tradeoff acknowledged:** Python formatters can express what the metrics dict contains — numeric thresholds, regime labels, flag values. They cannot express cross-metric insights that the Reviewer LLM derived through reasoning (e.g. "despite high P/E, expanding margins justify the multiple" — that lives in the report prose, not in the metrics dict). This is an acceptable tradeoff. The `evidence_brief` already carries all numeric signal. `key_claims` adds structured pattern labels and threshold-based interpretive rules. If debate quality measurably degrades after implementation, the upgrade path is to add a `key_claims` field to the Reviewer's LLM prompt output (no architectural change — just replaces the formatter call). Start with Python.

Examples using only what the metrics dicts actually contain:

```
MOMENTUM KEY CLAIMS:
• Regime: BULLISH_TRENDING | trend_strength=72, momentum_health=65
• Volume confirming (vol_confirmation=55 — above neutral threshold)
• Watch: momentum_health declining — potential early exhaustion signal
```

```
FUNDAMENTAL KEY CLAIMS:
• Quality: F-Score 7/9, ROE 28.5%, FCF Positive → strong fundamentals
• Valuation: Fwd P/E 24.1 | D/E 0.42, Current Ratio 1.8 → healthy balance sheet
• No critical red flags in health or cashflow dimensions
```

```
SENTIMENT KEY CLAIMS:
• Polarity 71/100 (BULLISH) | 23 articles | Direction: BULLISH
• AV score 68, text score 74 — both sources aligned, no divergence
• Buzz elevated — above-average coverage volume
```

```
MACRO KEY CLAIMS:
• Regime: RISK_ON | regime_fit=72
• monetary_stress=35 (moderate), rate_headwind=42 (present but not extreme)
• Yield curve spread available — no inversion trigger active
```

Target: ~40-50 words per dimension. 4 dimensions = ~180 words total. Replaces ~2000+ words of full report prose in debate prompts. The tone shifts from "narrative prose" to "structured signal labels" — which is exactly what an argument machine (Bull/Bear) needs to cite facts from.

### State Changes

Add 4 fields to `AgentState` in `agent_states.py`:

```python
momentum_key_claims: Annotated[str, "Compact momentum claims for debate context"]
fundamental_key_claims: Annotated[str, "Compact fundamental claims for debate context"]
sentiment_key_claims: Annotated[str, "Compact sentiment claims for debate context"]
macro_key_claims: Annotated[str, "Compact macro claims for debate context"]
```

These are populated by each Reviewer and consumed by Bull/Bear/Risk Debaters.

### Formatters

Add 4 Python formatter functions to `agent_utils.py`:

```python
def format_momentum_key_claims(momentum_metrics: dict) -> str: ...
def format_fundamental_key_claims(fundamental_metrics: dict) -> str: ...
def format_sentiment_key_claims(sentiment_metrics: dict) -> str: ...
def format_macro_key_claims(macro_metrics: dict) -> str: ...
```

Each reads from the computed metrics dict (already structured). Returns a compact multi-line string. Logic is simple conditional formatting — e.g. if `accel_percentile > 50` → "acceleration POSITIVE". No LLM call.

### Reviewer Changes

Each Reviewer already has the computed metrics dict. After its LLM call, it now also calls the formatter and adds `{dimension}_key_claims` to its return dict:

```python
# In momentum_reviewer.py (after existing LLM call):
from tradingagents.agents.utils.agent_utils import format_momentum_key_claims
key_claims = format_momentum_key_claims(momentum_metrics)
return {
    "market_report": enhanced_report,     # unchanged
    "momentum_metrics": momentum_metrics, # unchanged
    "momentum_key_claims": key_claims,    # NEW
}
```

### Debate Node Prompt Changes

Bull/Bear/Risk Debaters: replace the 4 full report injections with a single `key_claims_context` block:

**Before (Bull):**
```python
f"""...
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
Company fundamentals report: {fundamentals_report}
...
{evidence_brief}
"""
```

**After (Bull):**
```python
# Build key_claims_context from state fields
key_claims_context = "\n\n".join(filter(None, [
    state.get("momentum_key_claims", ""),
    state.get("fundamental_key_claims", ""),
    state.get("sentiment_key_claims", ""),
    state.get("macro_key_claims", ""),
]))

f"""...
Analyst Key Claims:
{key_claims_context}

{evidence_brief}
"""
```

**`curr_situation` for memory lookup** (used by `memory.get_memories()`) stays as the concatenated full reports — this is for vector similarity search, not LLM context. Leave it unchanged.

### Quality Preservation Argument

The debate nodes lose: verbose prose narrative from reports
The debate nodes keep: `evidence_brief` (all numeric metrics), `key_claims` (interpretive conclusions from Reviewer), debate history (full, unchanged), trader/investment plan, portfolio context

The Reviewer's interpretive conclusions are the highest-value content in the report. The prose supporting narrative (data repetition, hedging language, transitions) is noise for debate purposes. Bull/Bear can construct strong evidence-based arguments from claims + metrics. They cannot construct worse arguments — they have more *signal-dense* context, less noise.

---

## Architecture: Model Tiering

### Design

Add a third LLM tier to the pipeline: `debate_llm`. Verified against `setup.py` — current assignments are:

| Node | Current (`setup.py`) | After tiering |
|---|---|---|
| Bull | `quick_thinking_llm` | → `debate_llm` |
| Bear | `quick_thinking_llm` | → `debate_llm` |
| Research Manager | `deep_thinking_llm` | → `deep_thinking_llm` (NO CHANGE — synthesis node) |
| Trader | `quick_thinking_llm` | → `deep_thinking_llm` (**explicit upgrade** — execution-critical) |
| Risky / Neutral / Safe | `quick_thinking_llm` | → `debate_llm` |
| Risk Judge | `deep_thinking_llm` | → `deep_thinking_llm` (NO CHANGE) |

**Note on Trader upgrade:** Trader currently uses `quick_thinking_llm` which would accidentally land on `debate_llm` (Sonnet) when tiering is enabled. Trader produces structured invalidation conditions and position sizing that feed execution. Must be on Full. This is a semantic misassignment in the current code that tiering makes visible — fix it explicitly.

**Note on Research Manager:** Stays at `deep_thinking_llm`. It synthesizes the Bull/Bear debate and produces `investment_plan` — the single input the Trader consumes. Downgrading to Sonnet saves ~$0.02/run and risks missing a subtle swing point in the debate chain. Not worth it.

| Tier | Role | Default | Who uses it |
|---|---|---|---|
| `deep_thinking_llm` | Full model, deep reasoning | minimax-m2.5 | Reviewers, Research Manager, Trader, Risk Judge |
| `debate_llm` | Mid-tier, structured argument | configurable | Bull, Bear, 3 Risk Debaters |
| `llm` | (legacy quick tier, rarely used directly) | minimax-m2.5 | Analysts (already single-call, kept as-is) |

### Config Changes (`default_config.py`)

```python
# Debate tier — mid-tier model for Bull/Bear/Risk Debaters/Research Manager
"debate_llm": os.getenv("AETERNUS_DEBATE_MODEL", os.getenv("AETERNUS_DEEP_MODEL", "minimax-m2.5")),
"debate_provider": os.getenv(
    "AETERNUS_DEBATE_PROVIDER",
    os.getenv("AETERNUS_LLM_PROVIDER", "minimax"),
),
"debate_backend_url": os.getenv(
    "AETERNUS_DEBATE_BACKEND_URL",
    os.getenv("AETERNUS_BACKEND_URL", "https://api.minimax.io/anthropic"),
),
```

Default: same as current (no behavior change unless env vars set). To activate Sonnet for debate nodes:

```bash
# .env additions
AETERNUS_DEBATE_PROVIDER=anthropic
AETERNUS_DEBATE_MODEL=claude-sonnet-4-6
```

### Graph Wiring (`trading_graph.py`)

In `TradingAgentsGraph.__init__`, after constructing `self.deep_thinking_llm`:

```python
# Debate tier (mid-tier: Bull, Bear, Research Manager, Risk Debaters)
debate_provider = config.get("debate_provider", config.get("llm_provider", "openai"))
debate_model = config.get("debate_llm", config.get("quick_think_llm"))
debate_backend = config.get("debate_backend_url", config.get("backend_url"))

if debate_provider == "anthropic":
    self.debate_llm = ChatAnthropic(model=debate_model, ...)
else:
    self.debate_llm = ChatOpenAI(
        model=debate_model,
        openai_api_key=get_provider_key(debate_provider),
        base_url=debate_backend,
    )
```

Then in `setup.py` (where nodes are created), change assignments as follows:

```python
# debate_llm tier (5 debate nodes — argument machines, not analysts)
bull_researcher_node  = create_bull_researcher(self.debate_llm, self.bull_memory)
bear_researcher_node  = create_bear_researcher(self.debate_llm, self.bear_memory)
risky_analyst         = create_risky_debator(self.debate_llm, self.risky_memory)
neutral_analyst       = create_neutral_debator(self.debate_llm, self.neutral_memory)
safe_analyst          = create_safe_debator(self.debate_llm, self.safe_memory)

# deep_thinking_llm tier — UNCHANGED or explicitly upgraded
research_manager_node = create_research_manager(self.deep_thinking_llm, self.invest_judge_memory)  # NO CHANGE
trader_node           = create_trader(self.deep_thinking_llm, self.trader_memory)  # UPGRADE from quick_thinking_llm
risk_manager_node     = create_risk_manager(self.deep_thinking_llm, self.risk_manager_memory)  # NO CHANGE
```

**`llm_supports_structured_output` guard:** Already implemented on Research Manager, Trader, Risk Judge. When `debate_llm` is Anthropic Sonnet, `llm_supports_structured_output(debate_llm)` returns True for Bull/Bear (but they don't use structured output — no change needed there).

**`llm_supports_structured_output` guard**: The 3 structured output nodes (Research Manager, Trader, Risk Judge) already have this guard (implemented in the session prior to this plan). When `debate_llm` is Anthropic Sonnet, `llm_supports_structured_output` will return True for Research Manager → structured output will be attempted. This is correct behavior.

---

## Task Decomposition (≤3 files each)

### S-030a — Compressor: Formatters + State Fields
**Files:** `agent_utils.py`, `agent_states.py`
- Add `format_momentum_key_claims`, `format_fundamental_key_claims`, `format_sentiment_key_claims`, `format_macro_key_claims` to `agent_utils.py`
- Add 4 new `*_key_claims: str` fields to `AgentState` in `agent_states.py`
- Add empty-string initializations in `propagation.py` initial state

### S-030b — Compressor: Reviewer Emissions
**Files:** `momentum_reviewer.py`, `fundamentals_reviewer.py`
- Import and call formatters in each Reviewer's return dict
- Add `{dimension}_key_claims` to return

### S-030c — Compressor: Remaining Reviewer Emissions
**Files:** `sentiment_reviewer.py`, `macro_reviewer.py`
- Same as S-030b for sentiment and macro reviewers

### S-030d — Compressor: Bull/Bear Switch to key_claims
**Files:** `bull_researcher.py`, `bear_researcher.py`
- Replace 4 full report injections with `key_claims_context` block
- Keep `curr_situation` (for memory lookup) unchanged — it still uses full reports

### S-030e — Compressor: Risk Debaters Switch to key_claims
**Files:** `aggresive_debator.py`, `conservative_debator.py`, `neutral_debator.py`
- Same as S-030d for the 3 risk debaters

### S-031a — Tiering: Config + Graph
**Files:** `default_config.py`, `tradingagents/graph/trading_graph.py`
- Add `debate_*` config keys with env var fallback chain
- Instantiate `self.debate_llm` in `TradingAgentsGraph.__init__`

### S-031b — Tiering: Wire to Nodes
**Files:** `tradingagents/graph/setup.py`
- Pass `self.debate_llm` to Bull, Bear, 3 Risk Debaters (5 nodes)
- **Explicitly upgrade Trader** from `quick_thinking_llm` → `deep_thinking_llm` (currently misassigned — execution-critical node should be on Full tier)
- Research Manager and Risk Judge already on `deep_thinking_llm` — verify, no change needed

### H-030 — Tests
**Files:** `tests/test_compressor.py` (new)
- Test each `format_*_key_claims` formatter with real metric dicts
- Test that key_claims fields are non-empty after Reviewer nodes fire
- Test that debate nodes don't break when key_claims present
- Test `debate_llm` instantiation when env vars set to Anthropic

---

## Implementation Notes for Builder

1. **propagation.py initial state**: When adding `*_key_claims` fields to `AgentState`, also add empty-string initializations in `tradingagents/graph/propagation.py` where the initial state dict is built. Missing these causes `KeyError` on first run. Exact location: the dict passed to `graph.invoke({...})` in `TradingAgentsGraph.propagate()`.

2. **Risk debaters fire in parallel (Phase A)**: All 3 risk debaters (Risky/Safe/Neutral) are wired to fire simultaneously from the Trader node. They do not see each other's responses during their own call. The `key_claims` context is identical for all 3 — no ordering dependency. Compressor change is safe for parallel execution.

3. **`curr_situation` for memory lookup stays unchanged**: In Bull, Bear, and Risk Debaters, the `curr_situation = f"{market_research_report}..."` string used for `memory.get_memories()` is vector similarity search input, NOT LLM context. Leave it reading full reports. Only the LLM prompt injection changes.

4. **Upgrade path if Python key_claims prove insufficient**: If debate quality degrades after go-live, the upgrade path is: add a `key_claims` field to each Reviewer's LLM output prompt (structured output or end-of-response tag), parse it, store in state. The consuming code (Bull/Bear/Debaters) doesn't change — they read `state["momentum_key_claims"]` regardless of how it got there. No architectural change required.

---

## Explicit Non-Changes (Do Not Touch)

- `curr_situation` strings used for `memory.get_memories()` — leave as full reports (vector search needs prose)
- Full reports in `AgentState` — they stay; only the prompt injection changes
- `evidence_brief` — stays in all debate prompts unchanged
- Debate history accumulation — full transcript preserved, no compression
- Trader, Research Manager (prompt), Risk Judge (prompt) — already clean, no changes
- Analysts — untouched

---

## Verification Criteria

1. `python3 -m cli.main score AAPL --format table` runs end-to-end without error
2. All 4 `*_key_claims` fields are non-empty in the final state
3. Token count instrumentation shows debate node input drops by ≥50% vs baseline
4. Investment decision quality: score is reasonable (30–80 range), conviction is set, decision is Buy/Sell/Hold
5. `python -m pytest tests/ -q` — no new failures vs current baseline (66 pre-existing failures)
6. With `AETERNUS_DEBATE_PROVIDER=anthropic AETERNUS_DEBATE_MODEL=claude-sonnet-4-6` in env: Bull/Bear/Risk Debaters use Sonnet, Trader/Risk Judge use MiniMax/Opus

---

## Cost Projection at Operating Point

**Important: debate runs 2 rounds by default (`max_debate_rounds=1` → Bull→Bear→Bull→Bear→Research Manager = 4 debate calls). Token savings compound across all 4 calls, not just 1. The table below reflects full debate, not per-call.**

| Config | Est. Input Tokens | Model mix | Est. Cost |
|---|---|---|---|
| Current (baseline) | ~95K in / ~15K out | MiniMax full throughout | $2.50 |
| Compressor only (4 debate rounds × reduced context) | ~42K in / ~15K out | MiniMax full throughout | ~$1.10 |
| Tiering only (5 debate nodes → Sonnet, Trader upgraded to Full) | ~95K in / ~15K out | Full + Sonnet mix | ~$0.75 (Anthropic) |
| **Both (operating point)** | **~42K in / ~15K out** | **Full: Reviewers+ResearchMgr+Trader+RiskJudge; Sonnet: 5 debate nodes** | **~$0.30–0.40** |

MiniMax pricing at current levels with both optimizations: ~$0.75–1.00/run.
Anthropic Sonnet+Opus mix with both: ~$0.30–0.40/run.

**Note on Trader upgrade cost impact:** Moving Trader from `quick_thinking_llm` → `deep_thinking_llm` increases Trader's cost. Currently both are the same model (MiniMax-M2.5), so zero cost change today. With tiering enabled (debate→Sonnet, deep→Opus), Trader goes from Sonnet-tier to Opus-tier — adds ~$0.03/run. Justified by execution-critical nature of invalidation conditions and position sizing.

---

## One-More-Cut Analysis (Quality Cliff Below This Point)

These optimizations are explicitly excluded because they cross the quality cliff:

| Rejected optimization | Why it degrades quality |
|---|---|
| Compress debate history | Research Manager and Risk Judge derive synthesis quality from reading full argument chains, not summaries |
| Drop Reviewers to Sonnet | Reviewers are the analytical moat — Druckenmiller-style second-derivative interpretation, Piotroski with sector context. This is where SOTA reasoning earns its keep. |
| Drop Trader to Sonnet | Invalidation conditions are execution-critical. A missed condition costs real capital. Full model here. |
| Drop Risk Judge to Sonnet | Final execution gate. Reads compressed context so token cost is already low after compressor. Keep at full. |
| key_claims below 30 words/dimension | Debate nodes start constructing arguments from incomplete signal. Wrong call with good justification is worse than acknowledged uncertainty. |
| Haiku for debate nodes | Haiku may not detect contradictions between input facts (e.g. F-Score 8 + P/E 200 = anomaly that Haiku might not flag). Sonnet catches it. |
