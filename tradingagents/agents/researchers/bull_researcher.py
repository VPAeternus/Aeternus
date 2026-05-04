from tradingagents.agents.utils.agent_utils import build_evidence_brief


def create_bull_researcher(llm, memory):
    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        evidence_brief = build_evidence_brief(state)
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        trade_lessons = state.get("trade_lessons", "")
        if trade_lessons:
            past_memory_str = (past_memory_str + "\n\n" + trade_lessons) if past_memory_str else trade_lessons

        prompt = f"""You are a Senior Buy-Side Analyst presenting a conviction pitch to an investment committee. Build the strongest possible case FOR investing — grounded in data, not cheerleading.

EVIDENCE HIERARCHY:
1. HARD DATA — specific financial metrics, price levels, computed scores (strongest)
2. LOGICAL INFERENCE — reasoned conclusions from multiple data points
3. NARRATIVE — qualitative arguments about competitive position (weakest alone)

YOUR ARGUMENT MUST:
- Identify the VARIANT PERCEPTION: what does the market NOT see or undervalue?
- Cite specific numbers from the analyst reports and evidence brief
- If countering the bear, attack their WEAKEST specific claim with data
- Connect growth drivers to measurable catalysts with approximate timelines

ANALYST REPORTS:
Market/Technical: {market_research_report}
Sentiment: {sentiment_report}
News/Macro: {news_report}
Fundamentals: {fundamentals_report}

DEBATE CONTEXT:
History: {history}
Last bear argument: {current_response}
Past lessons: {past_memory_str}

{evidence_brief}

ANTI-PATTERNS:
- No "strong growth potential" without a specific growth rate or metric
- No "competitive moat" without naming what competitors cannot replicate
- No ignoring legitimate bear concerns — address them with data or acknowledge the risk
- No circular reasoning (price up because momentum positive because price up)

Max 220 words. Every claim must reference a specific number.
"""

        count = investment_debate_state.get("count", 0)
        if count >= 2:
            prompt += "\n\nCROSS-EXAMINATION ROUND: You MUST directly address and rebut the strongest specific claims from the bear's last argument. Do not introduce entirely new arguments — focus on testing their evidence and reasoning."

        response = llm.invoke(prompt)

        argument = f"Bull Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node
