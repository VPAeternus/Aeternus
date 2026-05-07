from tradingagents.agents.utils.agent_utils import build_evidence_brief


def create_bear_researcher(llm, memory):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        curr_situation = f"{market_research_report}\n\n{news_report}\n\n{fundamentals_report}"
        evidence_brief = build_evidence_brief(state)
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        trade_lessons = state.get("trade_lessons", "")
        if trade_lessons:
            past_memory_str = (past_memory_str + "\n\n" + trade_lessons) if past_memory_str else trade_lessons

        prompt = f"""You are a Senior Short-Side Analyst conducting due diligence on why this stock may be a poor investment. Find what the market is MISSING or MISPRICING on the downside.

EVIDENCE HIERARCHY:
1. HARD DATA — deteriorating metrics, negative trends, overvaluation signals (strongest)
2. STRUCTURAL RISKS — business model threats, competitive displacement, regulatory exposure
3. CYCLICAL RISKS — macro headwinds, sector rotation, positioning extremes (weakest alone)

YOUR ARGUMENT MUST:
- Identify the DOWNSIDE VARIANT PERCEPTION: what risk is the market underpricing?
- Distinguish STRUCTURAL risks (permanent impairment) from CYCLICAL risks (temporary headwinds)
- If countering the bull, identify their MOST FRAGILE ASSUMPTION and stress-test it with data
- Cite specific deterioration signals: margin compression, cash burn, insider selling, competitive threats

ANALYST REPORTS:
Market/Technical: {market_research_report}
News/Macro: {news_report}
Fundamentals: {fundamentals_report}

DEBATE CONTEXT:
History: {history}
Last bull argument: {current_response}
Past lessons: {past_memory_str}

{evidence_brief}

ANTI-PATTERNS:
- No "valuation is high" without comparing to history, peers, OR growth rate
- No generic "macro uncertainty" without naming the specific threat mechanism
- No catastrophizing without probability — distinguish likely risks from tail risks
- No restating what the bull already conceded — find NEW weaknesses

Max 220 words. Every claim must reference a specific number.
"""

        count = investment_debate_state.get("count", 0)
        if count >= 2:
            prompt += "\n\nCROSS-EXAMINATION ROUND: You MUST directly address and rebut the strongest specific claims from the bull's last argument. Do not introduce entirely new arguments — focus on testing their evidence and reasoning."

        response = llm.invoke(prompt)

        argument = f"Bear Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node
