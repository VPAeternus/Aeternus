from tradingagents.agents.utils.agent_utils import build_evidence_brief


def create_safe_debator(llm, memory=None):
    def safe_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        safe_history = risk_debate_state.get("safe_history", "")

        current_risky_response = risk_debate_state.get("current_risky_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        market_research_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        trader_decision = state["trader_investment_plan"]

        evidence_brief = build_evidence_brief(state)
        pretrade_risk_brief = state.get("pretrade_risk_brief", "")
        portfolio_context = state.get("portfolio_context", "")
        drawdown_mode = state.get("drawdown_mode", False)

        past_memory_str = ""
        if memory:
            curr_situation = f"{market_research_report}\n\n{news_report}\n\n{fundamentals_report}"
            past_memories = memory.get_memories(curr_situation, n_matches=2)
            for rec in past_memories:
                past_memory_str += rec["recommendation"] + "\n\n"

        trade_lessons = state.get("trade_lessons", "")
        if trade_lessons:
            past_memory_str = (past_memory_str + "\n\n" + trade_lessons) if past_memory_str else trade_lessons

        prompt = f"""You are the Conservative Risk Analyst — a tail-risk specialist focused on maximum drawdown protection.

TRADER'S DECISION:
{trader_decision}

YOUR FRAMEWORK — Tail Risk & Capital Preservation:
- Identify specific loss scenarios with rough probability estimates (not just "it could go down")
- Assess correlation risk: does this position add diversification or concentration to the portfolio?
- Name the maximum drawdown scenario and how it would affect portfolio recovery time
- Cite specific risk metrics: volatility, debt levels, macro headwinds, positioning extremes

DEBATE CONTEXT:
Aggressive argument: {current_risky_response}
Neutral argument: {current_neutral_response}
History: {history}

DATA:
Market: {market_research_report}
News: {news_report}
Fundamentals: {fundamentals_report}

PORTFOLIO CONTEXT:
Risk brief: {pretrade_risk_brief if pretrade_risk_brief else 'Unavailable'}
Composition: {portfolio_context if portfolio_context else 'Unavailable'}

{"DRAWDOWN MODE: Portfolio is in drawdown. Capital preservation is non-negotiable. Name specific conditions that must improve before ANY new risk. Recovery time is the priority metric." if drawdown_mode else ""}

Past lessons: {past_memory_str if past_memory_str else 'None available'}

{evidence_brief}

ANTI-PATTERNS:
- No generic "the market could crash" without naming the specific mechanism
- No ignoring upside — acknowledge it, then explain why the risk outweighs it
- No position of pure fear — propose a SPECIFIC risk-adjusted alternative (smaller size, hedged, conditional entry)

Max 220 words. Cite specific metrics."""

        response = llm.invoke(prompt)

        argument = f"Safe Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "risky_history": risk_debate_state.get("risky_history", ""),
            "safe_history": safe_history + "\n" + argument,
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Safe",
            "current_risky_response": risk_debate_state.get(
                "current_risky_response", ""
            ),
            "current_safe_response": argument,
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return safe_node
