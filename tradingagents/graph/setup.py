# TradingAgents/graph/setup.py

from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.analysts.momentum_reviewer import create_momentum_reviewer

from .conditional_logic import ConditionalLogic


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: ChatOpenAI,
        deep_thinking_llm: ChatOpenAI,
        tool_nodes: Dict[str, ToolNode],
        bull_memory,
        bear_memory,
        trader_memory,
        invest_judge_memory,
        risk_manager_memory,
        risky_memory=None,
        safe_memory=None,
        neutral_memory=None,
        conditional_logic: ConditionalLogic = None,
        config: Dict[str, Any] = None,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.bull_memory = bull_memory
        self.bear_memory = bear_memory
        self.trader_memory = trader_memory
        self.invest_judge_memory = invest_judge_memory
        self.risk_manager_memory = risk_manager_memory
        self.risky_memory = risky_memory
        self.safe_memory = safe_memory
        self.neutral_memory = neutral_memory
        self.conditional_logic = conditional_logic
        self.config = config or {}

    def setup_graph(
        self, selected_analysts=["market", "news"]
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst
                - "news": News analyst
        """
        if len(selected_analysts) == 0:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")

        # Create analyst nodes
        analyst_nodes = {}
        if "fundamentals" in selected_analysts:
            raise ValueError("Fundamentals framework has been removed from this baseline")
        if "social" in selected_analysts:
            raise ValueError("Social analyst has been removed from the scoring pipeline")
        has_market = "market" in selected_analysts

        if "market" in selected_analysts:
            analyst_nodes["market"] = create_market_analyst(
                self.quick_thinking_llm
            )

        if "news" in selected_analysts:
            analyst_nodes["news"] = create_news_analyst(
                self.quick_thinking_llm
            )


        # Create researcher and manager nodes
        bull_researcher_node = create_bull_researcher(
            self.quick_thinking_llm, self.bull_memory
        )
        bear_researcher_node = create_bear_researcher(
            self.quick_thinking_llm, self.bear_memory
        )
        research_manager_node = create_research_manager(
            self.deep_thinking_llm, self.invest_judge_memory
        )
        trader_node = create_trader(self.quick_thinking_llm, self.trader_memory)

        # Create risk analysis nodes
        risky_analyst = create_risky_debator(self.quick_thinking_llm, self.risky_memory)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm, self.neutral_memory)
        safe_analyst = create_safe_debator(self.quick_thinking_llm, self.safe_memory)
        risk_manager_node = create_risk_manager(
            self.deep_thinking_llm, self.risk_manager_memory
        )

        # Create workflow
        workflow = StateGraph(AgentState)

        # Add analyst nodes to the graph
        for analyst_type, node in analyst_nodes.items():
            workflow.add_node(f"{analyst_type.capitalize()} Analyst", node)

        has_news = "news" in selected_analysts
        # Add Momentum Reviewer node (deep-thinking critique layer)
        if has_market:
            momentum_reviewer_node = create_momentum_reviewer(self.deep_thinking_llm)
            workflow.add_node("Momentum Reviewer", momentum_reviewer_node)

        # Add other nodes
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Risky Analyst", risky_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Safe Analyst", safe_analyst)
        workflow.add_node("Risk Judge", risk_manager_node)

        # Define edges
        # Parallel fan-out: START → all selected analysts simultaneously
        for analyst_type in selected_analysts:
            workflow.add_edge(START, f"{analyst_type.capitalize()} Analyst")

        # Wire each analyst track: Analyst → Reviewer directly
        for analyst_type in selected_analysts:
            current_analyst = f"{analyst_type.capitalize()} Analyst"

            if analyst_type == "news" and has_news:
                workflow.add_edge(current_analyst, "research_join")
            elif analyst_type == "market" and has_market:
                workflow.add_edge(current_analyst, "Momentum Reviewer")

        # research_join barrier: all selected reviewers converge here
        workflow.add_node("research_join", lambda state: {})
        if has_market:
            workflow.add_edge("Momentum Reviewer", "research_join")
        workflow.add_edge("research_join", "Bull Researcher")

        # Add remaining edges
        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bear Researcher": "Bear Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bull Researcher": "Bull Researcher",
                "Research Manager": "Research Manager",
            },
        )
        if self.config.get("enable_red_team_agent", False):
            from tradingagents.agents.researchers.red_team_agent import create_red_team_agent
            red_team_node = create_red_team_agent(self.quick_thinking_llm)
            workflow.add_node("Red Team Agent", red_team_node)
            workflow.add_edge("Research Manager", "Red Team Agent")
            workflow.add_edge("Red Team Agent", "Trader")
        else:
            workflow.add_edge("Research Manager", "Trader")

        # Parallel fan-out: Trader → all 3 risk debaters simultaneously
        workflow.add_edge("Trader", "Risky Analyst")
        workflow.add_edge("Trader", "Safe Analyst")
        workflow.add_edge("Trader", "Neutral Analyst")

        # risk_join barrier: all 3 risk debaters converge here
        workflow.add_node("risk_join", lambda state: {})
        workflow.add_edge("Risky Analyst", "risk_join")
        workflow.add_edge("Safe Analyst", "risk_join")
        workflow.add_edge("Neutral Analyst", "risk_join")
        workflow.add_edge("risk_join", "Risk Judge")

        workflow.add_edge("Risk Judge", END)

        # Compile and return
        return workflow.compile()

    def setup_post_analyst_graph(self):
        """Compile a graph that starts after analyst collection.

        The initial state is expected to already contain analyst report fields.
        """
        bull_researcher_node = create_bull_researcher(
            self.quick_thinking_llm, self.bull_memory
        )
        bear_researcher_node = create_bear_researcher(
            self.quick_thinking_llm, self.bear_memory
        )
        research_manager_node = create_research_manager(
            self.deep_thinking_llm, self.invest_judge_memory
        )
        trader_node = create_trader(self.quick_thinking_llm, self.trader_memory)

        risky_analyst = create_risky_debator(self.quick_thinking_llm, self.risky_memory)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm, self.neutral_memory)
        safe_analyst = create_safe_debator(self.quick_thinking_llm, self.safe_memory)
        risk_manager_node = create_risk_manager(
            self.deep_thinking_llm, self.risk_manager_memory
        )

        workflow = StateGraph(AgentState)
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Risky Analyst", risky_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Safe Analyst", safe_analyst)
        workflow.add_node("Risk Judge", risk_manager_node)

        workflow.add_edge(START, "Bull Researcher")
        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bear Researcher": "Bear Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bull Researcher": "Bull Researcher",
                "Research Manager": "Research Manager",
            },
        )
        if self.config.get("enable_red_team_agent", False):
            from tradingagents.agents.researchers.red_team_agent import create_red_team_agent

            red_team_node = create_red_team_agent(self.quick_thinking_llm)
            workflow.add_node("Red Team Agent", red_team_node)
            workflow.add_edge("Research Manager", "Red Team Agent")
            workflow.add_edge("Red Team Agent", "Trader")
        else:
            workflow.add_edge("Research Manager", "Trader")

        workflow.add_edge("Trader", "Risky Analyst")
        workflow.add_edge("Trader", "Safe Analyst")
        workflow.add_edge("Trader", "Neutral Analyst")

        workflow.add_node("risk_join", lambda state: {})
        workflow.add_edge("Risky Analyst", "risk_join")
        workflow.add_edge("Safe Analyst", "risk_join")
        workflow.add_edge("Neutral Analyst", "risk_join")
        workflow.add_edge("risk_join", "Risk Judge")
        workflow.add_edge("Risk Judge", END)

        return workflow.compile()
