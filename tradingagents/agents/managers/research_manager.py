from tradingagents.agents.utils.agent_utils import build_evidence_brief
from tradingagents.graph.verdict_schemas import InvestmentVerdict


def create_research_manager(llm, memory):
    def research_manager_node(state) -> dict:
        history = state["investment_debate_state"].get("history", "")
        market_research_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        investment_debate_state = state["investment_debate_state"]

        curr_situation = f"{market_research_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        trade_lessons = state.get("trade_lessons", "")
        if trade_lessons:
            past_memory_str = (past_memory_str + "\n\n" + trade_lessons) if past_memory_str else trade_lessons

        evidence_brief = build_evidence_brief(state)

        prompt = f"""You are the Chief Investment Officer synthesizing a bull/bear debate into a definitive investment recommendation.

USE SEMI-FORMAL REASONING — your decision must be a verifiable certificate, not a narrative.

STEP 1 — PREMISES (state before concluding):
P1: [strongest bull data point with specific number]
P2: [strongest bear data point with specific number]
P3: [the single most important unresolved question]

STEP 2 — TRACE (connect evidence to conclusion):
For each premise, state whether it SUPPORTS or UNDERMINES the investment thesis and WHY.
Do not skip any premise — every stated fact must connect to the conclusion.

STEP 3 — COUNTERFACTUAL TEST (mandatory):
State the strongest argument for the OPPOSITE of your decision.
Explain specifically why your premises outweigh it. If you cannot, your decision is wrong.

STEP 4 — CONCLUSION (must derive from Steps 1-3):
Decision: BUY, SELL, or HOLD with conviction (1-5) and one-sentence justification.
The conclusion MUST follow from the premises — no new evidence allowed here.

DECISION RULES:
- Which side presented MORE FALSIFIABLE, DATA-BACKED claims? That side wins by default.
- You MUST commit to BUY or SELL unless BOTH sides presented equally strong data-backed cases
- HOLD requires explicit justification — "both sides have valid points" is NOT sufficient

DEBATE HISTORY:
{history}

PAST LESSONS:
{past_memory_str}

{evidence_brief}

ALSO INCLUDE:
- Investment plan: concrete steps for the trader — entry approach, key levels, timeline
- Flip condition: the single data point that would reverse your recommendation

ANTI-PATTERNS:
- No conclusion that doesn't trace to stated premises
- No skipping the counterfactual test
- No "balanced approach" that avoids commitment — pick a side
- No investment plan without specific price levels or timeframes

Max 320 words. Be decisive — ambiguity costs money."""

        # Try structured output, fall back to text
        try:
            structured_llm = llm.with_structured_output(InvestmentVerdict)
            verdict = structured_llm.invoke(prompt)
            investment_plan = verdict.reasoning
            judge_decision = (
                f"Decision: {verdict.decision} | Conviction: {verdict.conviction}/5 "
                f"| Bull Strength: {verdict.bull_strength}/5 "
                f"| Bear Strength: {verdict.bear_strength}/5\n{verdict.reasoning}"
            )
        except Exception:
            response = llm.invoke(prompt)
            investment_plan = response.content
            judge_decision = response.content

        new_investment_debate_state = {
            "judge_decision": judge_decision,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": judge_decision,
            "count": investment_debate_state["count"],
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
        }

    return research_manager_node
