"""Red Team Agent — finds logical flaws in the dominant investment thesis.

Fires between Research Manager and Trader. Reads the bull/bear debate history
and Research Manager synthesis. Identifies internal contradictions and unsupported
assumptions in the dominant thesis.

Unlike the Bear side (which argues the opposing view), the Red Team specifically
hunts for LOGICAL FLAWS in the leading thesis — inconsistencies, unsupported
assumptions, and contradictions with known data.
"""


def create_red_team_agent(llm):
    def red_team_node(state) -> dict:
        investment_plan = state.get("investment_plan", "")
        investment_debate_state = state.get("investment_debate_state", {})
        bull_history = investment_debate_state.get("bull_history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        # Determine dominant thesis direction
        plan_upper = investment_plan.upper()
        if "BUY" in plan_upper:
            direction = "BULLISH"
            debate_history = bull_history
        elif "SELL" in plan_upper:
            direction = "BEARISH"
            debate_history = bear_history
        else:
            direction = "NEUTRAL"
            debate_history = (bull_history + "\n\n" + bear_history).strip()

        prompt = f"""You are the Red Team Analyst. Your ONLY job is to find logical flaws, unsupported assumptions, and internal contradictions in the dominant investment thesis below.

DO NOT argue for the opposite direction. DO NOT restate what the other side already said.
ONLY find specific flaws in the logic and evidence presented.

Research synthesis (dominant thesis):
{investment_plan}

Full debate history:
{debate_history}

Your analysis must:
1. Identify 2-4 specific logical flaws or unsupported assumptions
2. For each flaw: state the claim being made, why it's flawed or unsupported, and which data would be needed to verify it
3. Assign a confidence impact per flaw: LOW (surface concern) | MEDIUM (meaningful gap) | HIGH (thesis-threatening)
4. Conclude with: "NET IMPACT: [MINOR/MODERATE/SIGNIFICANT] — [1 sentence on whether the flaws change the recommendation]"

Be surgical. Max 200 words. No restating the thesis."""

        response = llm.invoke(prompt)

        return {
            "red_team_critique": {
                "critique_text": response.content,
                "dominant_thesis_direction": direction,
            }
        }

    return red_team_node
