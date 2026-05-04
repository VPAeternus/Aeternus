import functools
import logging
from tradingagents.agents.utils.agent_utils import build_evidence_brief
from tradingagents.graph.verdict_schemas import TraderVerdict

logger = logging.getLogger(__name__)


def _format_trader_verdict(verdict: TraderVerdict) -> str:
    """Format a TraderVerdict into human-readable text for downstream compatibility."""
    lines = []
    lines.append(f"Decision: {verdict.decision} | Conviction: {verdict.conviction}/5")
    lines.append(f"Position size: {verdict.position_size_pct:.0%}")
    lines.append("")
    lines.append(verdict.reasoning)

    if verdict.scenarios:
        lines.append("")
        lines.append("Scenarios:")
        for s in verdict.scenarios:
            target = ""
            if s.target_return_pct is not None:
                target = f" (target: {s.target_return_pct:+.1f}%)"
            elif s.target_price is not None:
                target = f" (target: ${s.target_price:.2f})"
            lines.append(f"  {s.label} ({s.probability:.0%}){target}: {s.description}")

    if verdict.invalidation_conditions:
        lines.append("")
        lines.append("Invalidation conditions:")
        for ic in verdict.invalidation_conditions:
            lines.append(f"  - {ic.metric} {ic.operator} {ic.threshold}: {ic.description}")

    if verdict.milestones:
        lines.append("")
        lines.append("Milestones:")
        for m in verdict.milestones:
            lines.append(f"  - {m.trigger_type} {m.trigger_value} -> conviction {m.new_conviction}, {m.action}")

    lines.append("")
    lines.append(f"FINAL TRANSACTION PROPOSAL: **{verdict.decision}**")
    return "\n".join(lines)


def create_trader(llm, memory):
    def trader_node(state, name):
        company_name = state["company_of_interest"]
        investment_plan = state["investment_plan"]
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        if past_memories:
            for i, rec in enumerate(past_memories, 1):
                past_memory_str += rec["recommendation"] + "\n\n"

        trade_lessons = state.get("trade_lessons", "")
        if trade_lessons:
            past_memory_str = (past_memory_str + "\n\n" + trade_lessons) if past_memory_str else trade_lessons

        if not past_memory_str:
            past_memory_str = "No past memories found."

        evidence_brief = build_evidence_brief(state)

        context = {
            "role": "user",
            "content": f"Based on a comprehensive analysis by a team of analysts, here is an investment plan tailored for {company_name}. This plan incorporates insights from current technical market trends, macroeconomic indicators, and social media sentiment. Use this plan as a foundation for evaluating your next trading decision.\n\nProposed Investment Plan: {investment_plan}\n\nLeverage these insights to make an informed and strategic decision.\n\n{evidence_brief}",
        }

        messages = [
            {
                "role": "system",
                "content": f"""You are a Portfolio Trader constructing an executable trade. Convert the research team's investment plan into a precise, actionable recommendation.

BEFORE YOUR DECISION — state two things:
1. STRONGEST PREMISE: The single data point most supporting this trade (cite the number)
2. COUNTERFACTUAL: What would make the OPPOSITE trade correct? Name the specific metric/level.
   If you cannot name a counterfactual, your conviction should be 1.

YOUR OUTPUT MUST INCLUDE:
1. Decision: BUY, SELL, or HOLD with conviction (1-5)
   - Conviction 1-2 with a direction = weak signal, strongly consider HOLD instead
   - Conviction 3+ MUST commit to BUY or SELL, not HOLD
2. Invalidation conditions (2-3): FALSIFIABLE metrics that kill the thesis
   - Specific and measurable: "PE > 35", "price < $150", "RSI > 80"
   - NOT vague: "if market turns negative" or "if sentiment changes"
3. Three scenarios (BULL, BASE, BEAR):
   - Probabilities summing to 1.0
   - Specific target return percentage or price level for each
4. Conviction milestones (1-3): price levels or events that change conviction
5. Position size (0.01 to 0.10) based on:
   - Conviction (higher = larger)
   - Stock volatility (higher vol = smaller position)
   - Portfolio context if available

ENTRY TIMING: Is now the right entry, or should we wait? If thesis is right but entry is poor, say so.

ANTI-PATTERNS:
- No conviction 3+ with HOLD — commit to a direction
- No "if market turns negative" as invalidation — be specific
- No scenarios without target prices or returns
- No decision without stating premise + counterfactual first

Lessons from past decisions: {past_memory_str}

Max 220 words. Trade construction, not research restating.""",
            },
            context,
        ]

        # Try structured output, fall back to free-form text
        structured_verdict = {}
        try:
            structured_llm = llm.with_structured_output(TraderVerdict)
            verdict = structured_llm.invoke(messages)
            trader_text = _format_trader_verdict(verdict)
            structured_verdict = verdict.model_dump()
        except Exception as exc:
            logger.warning("Structured trader output failed, falling back to text: %s", exc)
            result = llm.invoke(messages)
            trader_text = result.content

        return {
            "messages": [{"role": "assistant", "content": trader_text}],
            "trader_investment_plan": trader_text,
            "structured_trader_verdict": structured_verdict,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
