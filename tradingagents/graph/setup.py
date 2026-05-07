# TradingAgents/graph/setup.py

from typing import Any, Dict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import create_market_analyst, create_news_analyst, create_trader
from tradingagents.agents.analysts.momentum_reviewer import create_momentum_reviewer
from tradingagents.agents.utils.agent_states import AgentState

from .conditional_logic import ConditionalLogic


class GraphSetup:
    """Handles setup and configuration of the analyst -> trader graph."""

    def __init__(
        self,
        quick_thinking_llm: ChatOpenAI,
        deep_thinking_llm: ChatOpenAI,
        tool_nodes: Dict[str, ToolNode],
        conditional_logic: ConditionalLogic = None,
        config: Dict[str, Any] = None,
    ):
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic
        self.config = config or {}

    def setup_graph(self, selected_analysts=["market", "news"]):
        """Compile analyst/reviewer collection followed directly by Trader."""
        if len(selected_analysts) == 0:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")
        if "fundamentals" in selected_analysts:
            raise ValueError("Fundamentals framework has been removed from this baseline")
        if "social" in selected_analysts:
            raise ValueError("Social analyst has been removed from the scoring pipeline")

        analyst_nodes = {}
        has_market = "market" in selected_analysts
        has_news = "news" in selected_analysts

        if has_market:
            analyst_nodes["market"] = create_market_analyst(self.quick_thinking_llm)
        if has_news:
            analyst_nodes["news"] = create_news_analyst(self.quick_thinking_llm)

        workflow = StateGraph(AgentState)
        for analyst_type, node in analyst_nodes.items():
            workflow.add_node(f"{analyst_type.capitalize()} Analyst", node)

        if has_market:
            workflow.add_node("Momentum Reviewer", create_momentum_reviewer(self.deep_thinking_llm))
        workflow.add_node("research_join", self._build_investment_plan)
        workflow.add_node("Trader", create_trader(self.quick_thinking_llm))

        for analyst_type in selected_analysts:
            workflow.add_edge(START, f"{analyst_type.capitalize()} Analyst")
            if analyst_type == "market" and has_market:
                workflow.add_edge("Market Analyst", "Momentum Reviewer")
            elif analyst_type == "news" and has_news:
                workflow.add_edge("News Analyst", "research_join")

        if has_market:
            workflow.add_edge("Momentum Reviewer", "research_join")
        workflow.add_edge("research_join", "Trader")
        workflow.add_edge("Trader", END)
        return workflow.compile()

    def setup_post_analyst_graph(self):
        """Compile graph that starts after analyst reports already exist."""
        workflow = StateGraph(AgentState)
        workflow.add_node("research_join", self._build_investment_plan)
        workflow.add_node("Trader", create_trader(self.quick_thinking_llm))
        workflow.add_edge(START, "research_join")
        workflow.add_edge("research_join", "Trader")
        workflow.add_edge("Trader", END)
        return workflow.compile()

    @staticmethod
    def _build_investment_plan(state: Dict[str, Any]) -> Dict[str, str]:
        market = state.get("market_report", "")
        news = state.get("news_report", "")
        fundamentals = state.get("fundamentals_report", "")
        plan = state.get("investment_plan") or (
            "Analyst reports collected. Trader should synthesize technical, news, "
            "macro, and fundamental evidence into an executable decision.\n\n"
            f"Market/Technical:\n{market}\n\nNews/Macro:\n{news}\n\nFundamentals:\n{fundamentals}"
        )
        return {"investment_plan": plan}
