from tradingagents.agents.utils.agent_utils import build_evidence_brief


def create_neutral_debator(llm, memory=None):
    def neutral_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        neutral_history = risk_debate_state.get("neutral_history", "")

        current_risky_response = risk_debate_state.get("current_risky_response", "")
        current_safe_response = risk_debate_state.get("current_safe_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        trader_decision = state["trader_investment_plan"]

        evidence_brief = build_evidence_brief(state)
        pretrade_risk_brief = state.get("pretrade_risk_brief", "")
        portfolio_context = state.get("portfolio_context", "")
        drawdown_mode = state.get("drawdown_mode", False)

        past_memory_str = ""
        if memory:
            curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
            past_memories = memory.get_memories(curr_situation, n_matches=2)
            for rec in past_memories:
                past_memory_str += rec["recommendation"] + "\n\n"

        trade_lessons = state.get("trade_lessons", "")
        if trade_lessons:
            past_memory_str = (past_memory_str + "\n\n" + trade_lessons) if past_memory_str else trade_lessons

        prompt = f"""You are the Neutral Risk Analyst — a risk-adjusted return optimizer focused on Sharpe ratio thinking.

TRADER'S DECISION:
{trader_decision}

YOUR FRAMEWORK — Risk-Adjusted Returns:
- Weigh the risk/reward ratio EXPLICITLY with numbers (expected return vs expected volatility)
- Identify what DATA would resolve the disagreement between aggressive and conservative
- Propose specific position sizing adjustments — not just "moderate approach" but "X% position because Y"
- Find where both sides are wrong: aggressive ignoring real risks, conservative ignoring real opportunities

DEBATE CONTEXT:
Aggressive argument: {current_risky_response}
Conservative argument: {current_safe_response}
History: {history}

DATA:
Market: {market_research_report}
Sentiment: {sentiment_report}
News: {news_report}
Fundamentals: {fundamentals_report}

PORTFOLIO CONTEXT:
Risk brief: {pretrade_risk_brief if pretrade_risk_brief else 'Unavailable'}
Composition: {portfolio_context if portfolio_context else 'Unavailable'}

{"DRAWDOWN MODE: Portfolio is in drawdown. Propose a SPECIFIC re-entry framework: what metrics must improve, by how much, before taking new positions?" if drawdown_mode else ""}

Past lessons: {past_memory_str if past_memory_str else 'None available'}

{evidence_brief}

ANTI-PATTERNS:
- No "balanced approach" without specific numbers — propose exact position size and conditions
- No splitting the difference between aggressive and conservative — synthesize a BETTER answer
- No fence-sitting — identify which side has stronger data and say so

Max 220 words. Cite specific metrics."""

        response = llm.invoke(prompt)

        argument = f"Neutral Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "risky_history": risk_debate_state.get("risky_history", ""),
            "safe_history": risk_debate_state.get("safe_history", ""),
            "neutral_history": neutral_history + "\n" + argument,
            "latest_speaker": "Neutral",
            "current_risky_response": risk_debate_state.get(
                "current_risky_response", ""
            ),
            "current_safe_response": risk_debate_state.get("current_safe_response", ""),
            "current_neutral_response": argument,
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return neutral_node
