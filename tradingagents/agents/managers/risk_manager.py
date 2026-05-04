import json

from tradingagents.agents.utils.agent_utils import build_evidence_brief
from tradingagents.graph.verdict_schemas import RiskVerdict


def create_risk_manager(llm, memory):
    def risk_manager_node(state) -> dict:

        company_name = state["company_of_interest"]

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        market_research_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        sentiment_report = state["sentiment_report"]
        trader_plan = state["investment_plan"]
        pretrade_risk_brief = state.get("pretrade_risk_brief", "")
        portfolio_context = state.get("portfolio_context", "")
        drawdown_mode = state.get("drawdown_mode", False)
        structured_trader_verdict = state.get("structured_trader_verdict", {})

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        trade_lessons = state.get("trade_lessons", "")
        if trade_lessons:
            past_memory_str = (past_memory_str + "\n\n" + trade_lessons) if past_memory_str else trade_lessons

        evidence_brief = build_evidence_brief(state)

        prompt = f"""You are the Chief Risk Officer making the final risk determination on a proposed trade.

EVIDENCE HIERARCHY:
1. QUANTITATIVE RISK METRICS — portfolio exposure, correlation, drawdown data (strongest)
2. DATA-BACKED ARGUMENTS from the debate — claims supported by specific numbers
3. NARRATIVE RISK ARGUMENTS — qualitative concerns (weakest alone)

DECISION FRAMEWORK:
- Which risk analyst presented the strongest DATA-BACKED argument? Start from their position.
- Review the trader's invalidation conditions — pass through, modify, or add missing ones.
- HOLD requires explicit justification, not "all sides have valid points."

TRADER'S PLAN: {trader_plan}
TRADER'S STRUCTURED VERDICT:
{json.dumps(structured_trader_verdict, indent=2) if structured_trader_verdict else "Free-form (no structured verdict)"}

PORTFOLIO CONTEXT:
Risk brief: {pretrade_risk_brief if pretrade_risk_brief else "Unavailable"}
Composition: {portfolio_context if portfolio_context else "Unavailable"}

{"DRAWDOWN MODE ACTIVE: Portfolio has drawn down 5%+ from HWM. Default to HOLD unless conditions are exceptionally compelling. If recommending BUY, you MUST specify re_entry_conditions explaining what changed." if drawdown_mode else ""}

DEBATE HISTORY:
{history}

Past lessons: {past_memory_str}

{evidence_brief}

YOUR OUTPUT MUST INCLUDE:
1. Decision: BUY, SELL, or HOLD with conviction (1-5) and one-sentence rationale
2. Hedge stance: INCREASE_HEDGE, DECREASE_HEDGE, or NO_CHANGE with instrument (SPY/QQQ) and why
3. Max position size: specific percentage limit for this trade
4. Dissent tracking: which analyst disagreed most strongly, on what topic, and how you resolved it
5. Invalidation conditions: trader's conditions plus any additions

ANTI-PATTERNS:
- No "balanced approach" as a substitute for a decision
- No ignoring portfolio context when sizing the position
- No generic hedge recommendations without citing the specific risk being hedged

Max 300 words. Be decisive."""

        # Try structured output, fall back to text
        try:
            structured_llm = llm.with_structured_output(RiskVerdict)
            verdict = structured_llm.invoke(prompt)
            final_trade_decision = (
                f"Decision: {verdict.decision} | Conviction: {verdict.conviction}/5 "
                f"| Hedge: {verdict.hedge_directive} {verdict.hedge_instrument or ''}\n"
                f"{verdict.reasoning}"
            )
            structured_verdict = {
                "decision": verdict.decision,
                "conviction": verdict.conviction,
                "hedge_directive": verdict.hedge_directive,
                "hedge_instrument": verdict.hedge_instrument,
                "max_position_pct": verdict.max_position_pct,
                "reasoning": verdict.reasoning,
                "dissent_records": [d.model_dump() for d in verdict.dissent_records],
                "invalidation_conditions": [ic.model_dump() for ic in verdict.invalidation_conditions],
                "drawdown_mode": verdict.drawdown_mode,
                "re_entry_conditions": verdict.re_entry_conditions,
            }
        except Exception:
            response = llm.invoke(prompt)
            final_trade_decision = response.content
            structured_verdict = {}

        new_risk_debate_state = {
            "judge_decision": final_trade_decision,
            "history": risk_debate_state["history"],
            "risky_history": risk_debate_state["risky_history"],
            "safe_history": risk_debate_state["safe_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_risky_response": risk_debate_state["current_risky_response"],
            "current_safe_response": risk_debate_state["current_safe_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_trade_decision,
            "structured_verdict": structured_verdict,
        }

    return risk_manager_node
