# TradingAgents/graph/conditional_logic.py

from tradingagents.agents.utils.agent_states import AgentState


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(
        self,
        max_debate_rounds=2,
        max_risk_discuss_rounds=2,
        max_tool_iterations_per_analyst=6,
    ):
        """Initialize with configuration parameters."""
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds
        self.max_tool_iterations_per_analyst = max_tool_iterations_per_analyst

    @staticmethod
    def _tool_call_iterations(messages) -> int:
        count = 0
        for message in messages:
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                count += 1
        return count

    def should_continue_market(self, state: AgentState):
        """Determine if market analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if self._tool_call_iterations(messages) >= self.max_tool_iterations_per_analyst:
            return "Msg Clear Market"
        if last_message.tool_calls:
            return "tools_market"
        return "Msg Clear Market"

    def should_continue_social(self, state: AgentState):
        """Determine if social media analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if self._tool_call_iterations(messages) >= self.max_tool_iterations_per_analyst:
            return "Msg Clear Social"
        if last_message.tool_calls:
            return "tools_social"
        return "Msg Clear Social"

    def should_continue_news(self, state: AgentState):
        """Determine if news analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if self._tool_call_iterations(messages) >= self.max_tool_iterations_per_analyst:
            return "Msg Clear News"
        if last_message.tool_calls:
            return "tools_news"
        return "Msg Clear News"

    def should_continue_fundamentals(self, state: AgentState):
        """Determine if fundamentals analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if self._tool_call_iterations(messages) >= self.max_tool_iterations_per_analyst:
            return "Msg Clear Fundamentals"
        if last_message.tool_calls:
            return "tools_fundamentals"
        return "Msg Clear Fundamentals"

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue."""

        if (
            state["investment_debate_state"]["count"] >= 2 * self.max_debate_rounds
        ):  # 3 rounds of back-and-forth between 2 agents
            return "Research Manager"
        if state["investment_debate_state"]["current_response"].startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue."""
        if (
            state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds
        ):  # 3 rounds of back-and-forth between 3 agents
            return "Risk Judge"
        if state["risk_debate_state"]["latest_speaker"].startswith("Risky"):
            return "Safe Analyst"
        if state["risk_debate_state"]["latest_speaker"].startswith("Safe"):
            return "Neutral Analyst"
        return "Risky Analyst"
