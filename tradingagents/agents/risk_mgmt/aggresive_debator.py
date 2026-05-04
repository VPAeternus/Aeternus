from tradingagents.agents.utils.agent_utils import build_evidence_brief


def create_risky_debator(llm, memory=None):
    def risky_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        risky_history = risk_debate_state.get("risky_history", "")

        current_safe_response = risk_debate_state.get("current_safe_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

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

        prompt = f"""You are the Aggressive Risk Analyst — an expected-value maximizer focused on asymmetric upside.

TRADER'S DECISION:
{trader_decision}

YOUR FRAMEWORK — Expected Value & Asymmetry:
- Quantify the upside/downside ratio. If upside > 2x downside with reasonable probability, the trade has positive EV.
- Identify what the conservative analyst is WRONG about with specific data
- Name the opportunity cost of NOT taking this position
- Cite specific metrics: growth rates, momentum scores, sentiment direction, valuation relative to growth

DEBATE CONTEXT:
Conservative argument: {current_safe_response}
Neutral argument: {current_neutral_response}
History: {history}

DATA:
Market: {market_research_report}
Sentiment: {sentiment_report}
News: {news_report}
Fundamentals: {fundamentals_report}

PORTFOLIO CONTEXT:
Risk brief: {pretrade_risk_brief if pretrade_risk_brief else 'Unavailable'}
Composition: {portfolio_context if portfolio_context else 'Unavailable'}

{"DRAWDOWN MODE: Portfolio is in drawdown. Even as the aggressive analyst, you must name 2-3 SPECIFIC conditions that must be met before adding risk. Blind aggression during drawdown is reckless, not bold." if drawdown_mode else ""}

Past lessons: {past_memory_str if past_memory_str else 'None available'}

{evidence_brief}

ANTI-PATTERNS:
- No "huge upside potential" without quantifying the expected return
- No dismissing risks without data — counter them with specific numbers
- No ignoring portfolio concentration or correlation risk

Max 220 words. Cite specific metrics."""

        response = llm.invoke(prompt)

        argument = f"Risky Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "risky_history": risky_history + "\n" + argument,
            "safe_history": risk_debate_state.get("safe_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Risky",
            "current_risky_response": argument,
            "current_safe_response": risk_debate_state.get("current_safe_response", ""),
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return risky_node
