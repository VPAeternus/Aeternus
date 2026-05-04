# Task: S-028

## Tier
sonnet

## Summary
Replace analyst tool-calling loops with single-call nodes. Each analyst fetches data directly via Python tool invocations, then makes one LLM call to synthesize the report. Eliminates tool nodes, Msg Clear nodes, and conditional routing for all 4 analyst tracks.

## Context

Phase A (S-027) parallelized the 4 analyst tracks. Phase B (this task) removes the tool-calling loop from each analyst track.

**Current per-analyst execution (3-5 LLM calls per track):**
```
Analyst → [tool_call] → ToolNode → Analyst → [tool_call] → ToolNode → Analyst → [synthesis]
       → Msg Clear → Reviewer
```

**Target per-analyst execution (1 LLM call per track):**
```
Analyst [fetch data in Python, single LLM synthesis] → Reviewer
```

**Why this is safe:**
- Tool order within each analyst is always identical — the LLM does not make genuine routing decisions about which tools to call. It always calls the same 2-3 tools in the same order. Making that sequence explicit in Python eliminates the overhead.
- For the market analyst, indicator selection appears agentic but is actually always a fixed subset. Hardcoding a standard set eliminates wasted round-trips.
- The Reviewer nodes remain unchanged — they read named state fields (market_report, fundamentals_report, etc.), not messages.

**What changes:**
- Each Analyst node fetches required data via `tool.invoke({...})` directly
- Then makes a single `llm.invoke(prompt)` call
- Does NOT write to `state["messages"]` (no tool messages to accumulate)
- `setup.py`: remove ToolNode wiring, Msg Clear nodes, and conditional edges for all analyst tracks

**What does NOT change:**
- Any Reviewer node (fundamentals_reviewer.py, momentum_reviewer.py, sentiment_reviewer.py, macro_reviewer.py)
- All debate/trader/risk nodes
- The parallel fan-out (START → 4 analysts) from Phase A
- The research_join and risk_join barrier nodes from Phase A
- `conditional_logic.py` — leave all methods in place (they become dead code, same pattern as Phase A's `should_continue_risk_analysis`)
- `trading_graph.py` — ToolNodes still constructed, just no longer wired into the graph

## Tool Signatures (Direct Invocation)

All tools are LangChain `@tool` decorated functions. Call via `.invoke({...})`:

```python
# Fundamentals
get_fundamental_snapshot.invoke({"ticker": ticker, "curr_date": current_date})  # → JSON string
get_valuation_context.invoke({"ticker": ticker})                                  # → JSON string

# Market
get_stock_data.invoke({"symbol": ticker, "start_date": start_date, "end_date": current_date})  # → CSV string
get_indicators.invoke({"symbol": ticker, "indicator": ind, "curr_date": current_date, "look_back_days": 30})  # → string (ONE indicator at a time)

# Social
get_sentiment_snapshot.invoke({"ticker": ticker, "curr_date": current_date})                             # → JSON string
get_social_sentiment.invoke({"ticker": ticker, "start_date": start_date, "end_date": current_date})      # → string

# News
get_news.invoke({"ticker": ticker, "start_date": start_date, "end_date": current_date})  # → string
get_global_news.invoke({"curr_date": current_date, "look_back_days": 7, "limit": 5})     # → string
```

Date range helper (use wherever start_date is needed):
```python
from datetime import datetime, timedelta
start_date = (datetime.strptime(current_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
```

## Analyst Implementations

### 1. fundamentals_analyst.py

Replace entirely with:

```python
from datetime import datetime, timedelta
from tradingagents.agents.utils.agent_utils import (
    get_fundamental_snapshot, get_valuation_context, extract_text_content
)


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]

        snapshot = get_fundamental_snapshot.invoke({"ticker": ticker, "curr_date": current_date})
        valuation = get_valuation_context.invoke({"ticker": ticker})

        prompt = (
            f"You are a fundamental analyst producing a structured investment report.\n\n"
            f"FETCHED DATA:\nFundamental Snapshot:\n{snapshot}\n\n"
            f"Valuation Context:\n{valuation}\n\n"
            "Using the data above, produce a concise investment report (max 600 words) "
            "with exactly these four sections, citing specific numbers:\n\n"
            "## Quality (Piotroski F-Score and Profitability)\n"
            "Report the F-Score (0-9) and its key components. Cite ROE, ROA, profit margins.\n\n"
            "## Growth (Revenue/Earnings Trends)\n"
            "Cite revenue growth rate, earnings growth, margin trends (improving/declining/stable).\n\n"
            "## Health (Balance Sheet and Cash Flow)\n"
            "Cite current ratio, debt-to-equity, FCF positive/negative, OCF trend.\n\n"
            "## Valuation (Multiples and Analyst Targets)\n"
            "Cite PE, forward PE, EV/EBITDA, analyst target price, upside %. "
            "Compare to sector averages if available.\n\n"
            "Append a Markdown summary table. Treat the fetched data as authoritative.\n"
            f"Ticker: {ticker} | Date: {current_date}"
        )

        result = llm.invoke(prompt)
        report = extract_text_content(result)
        return {"fundamentals_report": report}

    return fundamentals_analyst_node
```

### 2. market_analyst.py

Replace entirely with:

```python
from datetime import datetime, timedelta
from tradingagents.agents.utils.agent_utils import get_stock_data, get_indicators, extract_text_content

STANDARD_INDICATORS = [
    "close_50_sma", "close_200_sma", "macd", "macds",
    "rsi", "boll_ub", "boll_lb", "atr",
]


def create_market_analyst(llm):
    def market_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        start_date = (
            datetime.strptime(current_date, "%Y-%m-%d") - timedelta(days=60)
        ).strftime("%Y-%m-%d")

        price_data = get_stock_data.invoke(
            {"symbol": ticker, "start_date": start_date, "end_date": current_date}
        )

        indicator_sections = []
        for ind in STANDARD_INDICATORS:
            try:
                data = get_indicators.invoke(
                    {"symbol": ticker, "indicator": ind, "curr_date": current_date, "look_back_days": 30}
                )
                indicator_sections.append(f"**{ind}**:\n{data}")
            except Exception:
                pass
        indicators_text = "\n\n".join(indicator_sections)

        prompt = (
            "You are a market analyst writing a detailed technical analysis report.\n\n"
            f"FETCHED DATA:\nPrice Data (OHLCV):\n{price_data}\n\n"
            f"Technical Indicators:\n{indicators_text}\n\n"
            "Write a very detailed and nuanced report of the trends you observe (max 500 words). "
            "Include specific, fine-grained insights that may help traders make decisions. "
            "Do not simply state trends are mixed.\n\n"
            "Append a Markdown table summarizing key points.\n"
            "Treat the fetched data as authoritative.\n"
            f"Ticker: {ticker} | Date: {current_date}"
        )

        result = llm.invoke(prompt)
        report = extract_text_content(result)
        return {"market_report": report}

    return market_analyst_node
```

### 3. social_media_analyst.py

Replace entirely with (preserve dealflow_context block exactly):

```python
from datetime import datetime, timedelta
from tradingagents.agents.utils.agent_utils import (
    get_sentiment_snapshot, get_social_sentiment, extract_text_content
)


def create_social_media_analyst(llm):
    def social_media_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        dealflow_ctx = state.get("dealflow_context", {})
        dealflow_subscores = dealflow_ctx.get("subscores", {})
        start_date = (
            datetime.strptime(current_date, "%Y-%m-%d") - timedelta(days=7)
        ).strftime("%Y-%m-%d")

        sentiment_snapshot = get_sentiment_snapshot.invoke(
            {"ticker": ticker, "curr_date": current_date}
        )
        social_narrative = get_social_sentiment.invoke(
            {"ticker": ticker, "start_date": start_date, "end_date": current_date}
        )

        dealflow_block = ""
        if dealflow_subscores:
            sub_lines = "\n".join(f"  - {k}: {v}/100" for k, v in dealflow_subscores.items())
            evidence = dealflow_ctx.get("evidence", {})
            tags = dealflow_ctx.get("thesis_tags", [])
            why_now = dealflow_ctx.get("why_now", "")
            lane = dealflow_ctx.get("lane", "")
            playbook = dealflow_ctx.get("research_playbook", "")
            df_score = dealflow_ctx.get("deal_flow_score", "N/A")
            dealflow_block = (
                "## Deal Flow Signals (PRIMARY DATA SOURCE)\n"
                "Deal flow signals from direct X API and cashtag velocity analysis:\n\n"
                f"**Deal Flow Score**: {df_score}/100\n"
                f"**Subscores**:\n{sub_lines}\n"
                f"**Evidence**: {evidence.get('evidence_count', 'N/A')} items, "
                f"freshness {evidence.get('freshness_hours', 'N/A')}h\n"
                f"**Thesis Tags**: {', '.join(tags) if tags else 'None'}\n"
                f"**Why Now**: {why_now or 'N/A'}\n"
                f"**Lane**: {lane or 'N/A'}\n"
                f"**Research Playbook**: {playbook or 'N/A'}\n\n"
                "Use these as your PRIMARY data source for sentiment assessment.\n\n"
            )

        prompt = (
            f"You are a social sentiment analyst.\n\n"
            f"{dealflow_block}"
            f"FETCHED DATA:\nSentiment Snapshot (computed metrics):\n{sentiment_snapshot}\n\n"
            f"Social Narrative:\n{social_narrative}\n\n"
            "Produce a concise report (max 500 words) with exactly these four sections:\n\n"
            "## Sentiment Polarity (Bullish/Bearish/Neutral)\n"
            "Report the computed composite score and AV sentiment label. Cite article count, relevance.\n\n"
            "## Social Buzz & Engagement\n"
            "Volume of social discussion. Is this ticker getting unusual attention? "
            "Source quality assessment (AV structured vs text-only).\n\n"
            "## Catalyst Events\n"
            "Cite specific catalysts detected (earnings, FDA, M&A, guidance changes). "
            "Catalyst score from computed metrics.\n\n"
            "## Narrative Context\n"
            "Key narratives on social media and what's driving sentiment. "
            "Cite specific sources from the social sentiment response.\n\n"
            "Append a Markdown summary table.\n"
            f"Ticker: {ticker} | Date: {current_date}"
        )

        result = llm.invoke(prompt)
        report = extract_text_content(result)
        return {"sentiment_report": report}

    return social_media_analyst_node
```

### 4. news_analyst.py

Replace entirely with:

```python
from datetime import datetime, timedelta
from tradingagents.agents.utils.agent_utils import get_news, get_global_news, extract_text_content


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        start_date = (
            datetime.strptime(current_date, "%Y-%m-%d") - timedelta(days=7)
        ).strftime("%Y-%m-%d")

        company_news = get_news.invoke(
            {"ticker": ticker, "start_date": start_date, "end_date": current_date}
        )
        global_news = get_global_news.invoke(
            {"curr_date": current_date, "look_back_days": 7, "limit": 5}
        )

        prompt = (
            "You are a news researcher tasked with analyzing recent news and trends.\n\n"
            f"FETCHED DATA:\nCompany News ({ticker}):\n{company_news}\n\n"
            f"Global Macro News:\n{global_news}\n\n"
            "Write a comprehensive report (max 500 words) on the current state of the world "
            "relevant for trading and macroeconomics. Provide detailed, fine-grained analysis "
            "— do not simply state that trends are mixed.\n\n"
            "Append a Markdown table of key points.\n"
            "Treat the fetched data as authoritative.\n"
            f"Ticker: {ticker} | Date: {current_date}"
        )

        result = llm.invoke(prompt)
        report = extract_text_content(result)
        return {"news_report": report}

    return news_analyst_node
```

## setup.py Changes

### 1. Remove `delete_nodes` dict entirely

Remove this initialization and all assignments:
```python
# REMOVE:
delete_nodes = {}
# REMOVE all: delete_nodes["market"] = create_msg_delete()  etc.
```

### 2. Remove `tool_nodes` local dict entirely

Remove the internal `tool_nodes` dict and all assignments:
```python
# REMOVE:
tool_nodes = {}
# REMOVE all: tool_nodes["market"] = self.tool_nodes["market"]  etc.
```
Note: `self.tool_nodes` (constructor parameter) stays untouched.

### 3. In the node-creation loop, remove Msg Clear and ToolNode additions

The `for analyst_type, node in analyst_nodes.items()` loop currently adds 3 nodes per analyst. After Phase B it adds 1:

```python
# KEEP:
workflow.add_node(f"{analyst_type.capitalize()} Analyst", node)
# REMOVE:
workflow.add_node(f"Msg Clear {analyst_type.capitalize()}", delete_nodes[analyst_type])
workflow.add_node(f"tools_{analyst_type}", tool_nodes[analyst_type])
```

### 4. Replace the edge-wiring loop

Current loop (lines ~165-187) sets up conditional edges for each analyst. Replace with direct Analyst → Reviewer edges:

```python
# REPLACE the entire second for-loop block with:
for analyst_type in selected_analysts:
    current_analyst = f"{analyst_type.capitalize()} Analyst"

    if analyst_type == "fundamentals" and has_fundamentals:
        workflow.add_edge(current_analyst, "Fundamental Reviewer")
    elif analyst_type == "social" and has_social:
        workflow.add_edge(current_analyst, "Sentiment Reviewer")
    elif analyst_type == "news" and has_news:
        workflow.add_edge(current_analyst, "Macro Reviewer")
    elif analyst_type == "market" and has_market:
        workflow.add_edge(current_analyst, "Momentum Reviewer")
```

Remove: `current_tools`, `current_clear` local variables, `workflow.add_conditional_edges(...)`, `workflow.add_edge(current_tools, current_analyst)`.

### 5. Also remove create_msg_delete import

`create_msg_delete` is imported via `from tradingagents.agents import *`. After Phase B it is unused in setup.py. Leave the wildcard import as-is (removing it would require auditing all names it provides).

## Do NOT Change

- `conditional_logic.py` — all 6 methods stay (4 analyst ones become dead code; same as Phase A)
- `trading_graph.py` — ToolNodes still constructed, just not wired
- All Reviewer node files
- All researcher/trader/risk node files
- `AgentState` schema
- research_join, risk_join from Phase A

## Testing

```bash
# All unit tests
python -m pytest tests/ -v --tb=short

# Graph compilation — 4-analyst
python3 -c "
from tradingagents.graph.trading_graph import TradingAgentsGraph
g = TradingAgentsGraph(['market', 'social', 'news', 'fundamentals'])
print('Full graph compiled OK')
nodes = sorted(g.graph.nodes)
print('Nodes:', nodes)
"

# Graph compilation — single-analyst subset
python3 -c "
from tradingagents.graph.trading_graph import TradingAgentsGraph
g = TradingAgentsGraph(['market'])
print('Single-analyst graph compiled OK')
"

# Verify tool/Msg Clear nodes removed, join nodes preserved
python3 -c "
from tradingagents.graph.trading_graph import TradingAgentsGraph
g = TradingAgentsGraph(['market', 'social', 'news', 'fundamentals'])
nodes = set(g.graph.nodes)
for removed in ['tools_market','tools_social','tools_news','tools_fundamentals',
                'Msg Clear Market','Msg Clear Social','Msg Clear News','Msg Clear Fundamentals']:
    assert removed not in nodes, f'{removed} should be removed'
for required in ['research_join', 'risk_join']:
    assert required in nodes, f'{required} must remain'
print('All node assertions passed')
print('Final node set:', sorted(nodes))
"
```

## Acceptance Criteria

- [ ] All existing tests pass: `python -m pytest tests/ -v`
- [ ] Full 4-analyst graph compiles without error
- [ ] Single-analyst subset (`['market']`) compiles without error
- [ ] No ToolNode nodes in compiled graph (tools_market/social/news/fundamentals removed)
- [ ] No Msg Clear nodes in compiled graph (all 4 removed)
- [ ] research_join and risk_join still present (Phase A preserved)
- [ ] Only 5 files modified: 4 analyst files + setup.py
- [ ] No Reviewer/researcher/trader/risk files touched

## Status
done
