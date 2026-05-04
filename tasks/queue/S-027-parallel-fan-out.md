# Task: S-027

## Tier
sonnet

## Summary
Parallelize the 4 analysis tracks and 3 risk debaters using LangGraph fan-out/join — the highest-ROI architectural change in the pipeline (4-6x speedup, zero quality risk, zero logic changes).

## Context

**What this task is:**
Pure graph rewiring. Zero changes to any node implementation, prompt, data access, or business logic. Every node continues doing exactly what it does today — they just run concurrently instead of sequentially.

**Current execution order (sequential, 18+ latency slots):**
```
START → Fundamentals Analyst → tools → loop → Msg Clear → Fundamental Reviewer
      → Market Analyst → tools → loop → Msg Clear → Momentum Reviewer
      → Social Analyst → tools → loop → Msg Clear → Sentiment Reviewer
      → News Analyst → tools → loop → Msg Clear → Macro Reviewer
      → Bull Researcher → Bear Researcher → Research Manager → Trader
      → Risky Analyst → Safe Analyst → Neutral Analyst → Risk Judge → END
```

**Target execution order (parallel, 8 latency slots):**
```
START → [4-way parallel fan-out]
          ├── Fundamentals Analyst → tools → loop → Msg Clear → Fundamental Reviewer ──┐
          ├── Market Analyst → tools → loop → Msg Clear → Momentum Reviewer ───────────┤
          ├── Social Analyst → tools → loop → Msg Clear → Sentiment Reviewer ──────────┤
          └── News Analyst → tools → loop → Msg Clear → Macro Reviewer ────────────────┘
      → [research_join barrier]
      → Bull Researcher → Bear Researcher → Research Manager → Trader
      → [3-way parallel fan-out]
          ├── Risky Analyst ──┐
          ├── Safe Analyst ───┤
          └── Neutral Analyst ┘
      → [risk_join barrier]
      → Risk Judge → END
```

**Why Bull/Bear stay sequential:**
Bear reads `current_response` from Bull's last argument (`investment_debate_state["current_response"]`). This is the adversarial mechanism. Do not parallelize them.

**Why Risk debaters CAN be parallelized:**
With `max_risk_discuss_rounds: 1`, only one round fires. In round 1, each debater reads `current_*_response` fields from state — all empty at start of round 1. No sequential dependency in round 1. Running them in parallel loses nothing at the current config.

**Key architectural files:**
- `tradingagents/graph/setup.py` — Primary target. All graph wiring lives here.
- `tradingagents/graph/conditional_logic.py` — Contains `should_continue_risk_analysis` (sequential Risky→Safe→Neutral routing). This routing must be bypassed for parallel risk debaters.
- `tradingagents/agents/utils/agent_states.py` — Read-only reference. `messages` uses `add_messages` reducer (append). Critical consideration below.

**Critical: `messages` field in parallel branches**

The `should_continue_*` functions in `conditional_logic.py` check `state["messages"]` to count tool call iterations and inspect `messages[-1].tool_calls`. In LangGraph parallel fan-out, each branch gets its own copy of the state at the point of dispatch, so each branch's tool-calling loop sees only its own messages. This is correct behavior.

At the join barrier, LangGraph merges branch states using reducers. The `messages` field uses `add_messages` (append), so messages from all 4 parallel branches will be concatenated. This is acceptable — the named report fields (`market_report`, `fundamentals_report`, etc.) are the data that flows downstream, not `messages`. The Msg Clear node in each branch clears its own messages before the Reviewer runs.

After the join, `messages` may contain residual content from all 4 branches. This is fine — the Bull Researcher reads named fields (`market_report`, `sentiment_report`, etc.), not `messages`. Verify this during testing.

## Requirements

### 1. Parallel analysis fan-out (setup.py)

Replace the sequential analyst chain with a parallel fan-out from START.

Use LangGraph's parallel edge support: add multiple edges from a single source to multiple targets. LangGraph executes all targets in parallel when multiple edges leave the same node.

```python
# Fan-out: START → all 4 analysts simultaneously
workflow.add_edge(START, "Fundamentals Analyst")
workflow.add_edge(START, "Market Analyst")
workflow.add_edge(START, "Social Analyst")
workflow.add_edge(START, "News Analyst")
```

Each internal track loop stays exactly as-is (Analyst → conditional → tools → Analyst OR Msg Clear → Reviewer).

Add a passthrough join node after all 4 Reviewers:
```python
workflow.add_node("research_join", lambda state: {})
workflow.add_edge("Fundamental Reviewer", "research_join")
workflow.add_edge("Momentum Reviewer", "research_join")
workflow.add_edge("Sentiment Reviewer", "research_join")
workflow.add_edge("Macro Reviewer", "research_join")
workflow.add_edge("research_join", "Bull Researcher")
```

**Handle the `selected_analysts` variable subset case:** The current code supports running with fewer than 4 analysts (e.g., `["market"]` only for the `score` command). The fan-out must only dispatch to the analysts in `selected_analysts`. The join must only wait for those that were dispatched.

```python
# Fan-out only selected analysts
for analyst_type in selected_analysts:
    workflow.add_edge(START, f"{analyst_type.capitalize()} Analyst")

# Join: only selected reviewers feed into research_join
if has_fundamentals:
    workflow.add_edge("Fundamental Reviewer", "research_join")
if has_market:
    workflow.add_edge("Momentum Reviewer", "research_join")
if has_social:
    workflow.add_edge("Sentiment Reviewer", "research_join")
if has_news:
    workflow.add_edge("Macro Reviewer", "research_join")

workflow.add_edge("research_join", "Bull Researcher")
```

Remove the old sequential `for i, analyst_type in enumerate(selected_analysts)` chain that wired analysts in sequence.

### 2. Parallel risk fan-out (setup.py + conditional_logic.py)

Replace the sequential `Risky → Safe → Neutral` routing with a parallel fan-out from Trader.

In setup.py:
```python
# Fan-out: Trader → all 3 risk debaters simultaneously
workflow.add_edge("Trader", "Risky Analyst")
workflow.add_edge("Trader", "Safe Analyst")
workflow.add_edge("Trader", "Neutral Analyst")

# Join barrier
workflow.add_node("risk_join", lambda state: {})
workflow.add_edge("Risky Analyst", "risk_join")
workflow.add_edge("Safe Analyst", "risk_join")
workflow.add_edge("Neutral Analyst", "risk_join")
workflow.add_edge("risk_join", "Risk Judge")
```

Remove the conditional edges from Risky, Safe, and Neutral that implement the sequential loop (`should_continue_risk_analysis`). These are replaced by direct edges to `risk_join`.

In conditional_logic.py: `should_continue_risk_analysis` becomes dead code once the conditional edges are removed. Leave the method in place (removing it requires changing `ConditionalLogic.__init__` callers) but it will no longer be wired into the graph.

### 3. Do NOT change

- Any node implementation (`fundamentals_analyst.py`, `social_media_analyst.py`, `macro_reviewer.py`, etc.)
- Any prompt text
- Any data fetching logic
- `should_continue_market/social/news/fundamentals` logic in conditional_logic.py (still needed for tool loop within each track)
- `should_continue_debate` logic (Bull → Bear routing unchanged)
- AgentState fields
- The debate structure (Bull sequential → Bear sequential → Research Manager)

## Files to Touch

- `tradingagents/graph/setup.py` — Primary. Replace sequential chain with parallel fan-out/join.
- `tradingagents/graph/conditional_logic.py` — Remove the conditional edges wiring for `should_continue_risk_analysis` (the method stays, just no longer wired).

## Testing

After implementation, run:
```bash
# Unit tests — must all pass
python -m pytest tests/ -v --tb=short

# Smoke test: single analyst (score command path)
python -m cli.main score AAPL --format table

# Integration test: verify parallel fan-out compiles without error
python3 -c "
from tradingagents.graph.trading_graph import TradingAgentsGraph
g = TradingAgentsGraph(['market', 'social', 'news', 'fundamentals'])
print('Graph compiled OK')
print('Nodes:', list(g.graph.nodes))
"

# Verify research_join and risk_join nodes exist
python3 -c "
from tradingagents.graph.trading_graph import TradingAgentsGraph
g = TradingAgentsGraph(['market', 'social', 'news', 'fundamentals'])
nodes = list(g.graph.nodes)
assert 'research_join' in nodes, 'research_join missing'
assert 'risk_join' in nodes, 'risk_join missing'
print('Join nodes confirmed:', [n for n in nodes if 'join' in n])
"

# Verify single-analyst subset still works
python3 -c "
from tradingagents.graph.trading_graph import TradingAgentsGraph
g = TradingAgentsGraph(['market'])
print('Single-analyst graph compiled OK')
"
```

## Acceptance Criteria

- [ ] All existing tests pass: `python -m pytest tests/ -v`
- [ ] `TradingAgentsGraph(['market', 'social', 'news', 'fundamentals'])` compiles without error
- [ ] `TradingAgentsGraph(['market'])` compiles without error (subset path)
- [ ] `research_join` node present in compiled graph
- [ ] `risk_join` node present in compiled graph
- [ ] No node implementations modified (diff shows only `setup.py` and `conditional_logic.py` changed)
- [ ] `score` CLI command still runs end-to-end without error

## Status
done
