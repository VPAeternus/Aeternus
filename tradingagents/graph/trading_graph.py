# TradingAgents/graph/trading_graph.py

import logging
import os
from pathlib import Path
import json
from datetime import date
from typing import Dict, Any, Tuple, List, Optional

logger = logging.getLogger(__name__)

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.agents.utils.memory import FinancialSituationMemory, TradeMemory
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.dataflows.config import set_config

# Import the new abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    get_stock_data,
    get_indicators,
    get_news,
    get_insider_sentiment,
    get_insider_transactions,
    get_global_news,
)
from tradingagents.agents.utils.options_engine import build_options_snapshot
from tradingagents.agents.utils.flow_toxicity_engine import build_flow_toxicity_snapshot

from .conditional_logic import ConditionalLogic
from .setup import GraphSetup
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor
from .aeternus_scoring import AeternusScorer
from .sector_context import SectorContext
from .thesis_check import ThesisChecker
from .track_record import TrackRecord


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=["market", "news"],
        debug=False,
        config: Dict[str, Any] = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(
            os.path.join(self.config["project_dir"], "dataflows/data_cache"),
            exist_ok=True,
        )

        # Initialize LLMs
        def get_provider_key(provider):
            # OAuth tokens take priority over API keys
            if provider == "openai":
                return (os.environ.get("OPENAI_AUTH_TOKEN") or
                        os.environ.get("OPENAI_API_KEY"))
            if provider == "anthropic":
                return (os.environ.get("ANTHROPIC_AUTH_TOKEN") or
                        os.environ.get("ANTHROPIC_API_KEY"))
            if provider == "minimax":
                return (os.environ.get("MINIMAX_OAUTH_TOKEN") or
                        os.environ.get("MINIMAX_API_KEY"))
            if provider == "google": return os.environ.get("GOOGLE_API_KEY")
            return None

        provider = self.config["llm_provider"].lower()
        api_key = get_provider_key(provider)
        
        # Validation for required keys
        if provider not in ("ollama", "minimax", "claude_cli", "codex_cli") and not api_key:
            raise ValueError(f"{provider.upper()}_API_KEY is missing in environment variables.")
        if api_key and ("your_" in api_key.lower() or api_key.startswith("your_")):
            raise ValueError(f"Invalid {provider.upper()}_API_KEY detected. Please check your .env file.")

        if provider in ["openai", "ollama"]:
            self.deep_thinking_llm = ChatOpenAI(
                model=self.config["deep_think_llm"],
                base_url=self.config["backend_url"],
                api_key=api_key,
                max_retries=3,
                request_timeout=120,
            )
            self.quick_thinking_llm = ChatOpenAI(
                model=self.config["quick_think_llm"],
                base_url=self.config["backend_url"],
                api_key=api_key,
                max_retries=3,
                request_timeout=120,
            )
        elif provider == "minimax":
            _minimax_base = "https://api.minimax.io/anthropic"
            self.deep_thinking_llm = ChatAnthropic(
                model=self.config["deep_think_llm"],
                anthropic_api_key=api_key,
                base_url=_minimax_base,
                max_retries=3,
                timeout=120,
            )
            self.quick_thinking_llm = ChatAnthropic(
                model=self.config["quick_think_llm"],
                anthropic_api_key=api_key,
                base_url=_minimax_base,
                max_retries=3,
                timeout=120,
            )
        elif provider == "anthropic":
            _is_oauth = bool(os.environ.get("ANTHROPIC_AUTH_TOKEN"))
            _anthropic_kwargs = dict(
                max_retries=3,
                timeout=120,
            )
            if _is_oauth:
                # OAuth bearer token — pass via Authorization header; api_key is a dummy.
                _anthropic_kwargs["default_headers"] = {"Authorization": f"Bearer {api_key}"}
                _anthropic_kwargs["anthropic_api_key"] = "oauth-token"
            else:
                _anthropic_kwargs["base_url"] = self.config["backend_url"]
                _anthropic_kwargs["anthropic_api_key"] = api_key

            # Deep thinking LLM — enable adaptive thinking for Opus 4.6+
            _deep_kwargs = dict(_anthropic_kwargs)
            if self.config.get("anthropic_adaptive_thinking", True):
                _deep_kwargs["thinking"] = {"type": "adaptive"}
                _deep_kwargs["max_tokens"] = 16000
                _deep_kwargs["timeout"] = 180  # increased to allow thinking budget

            self.deep_thinking_llm = ChatAnthropic(
                model=self.config["deep_think_llm"],
                **_deep_kwargs,
            )
            self.quick_thinking_llm = ChatAnthropic(
                model=self.config["quick_think_llm"],
                **_anthropic_kwargs,
            )
        elif provider == "google":
            self.deep_thinking_llm = ChatGoogleGenerativeAI(
                model=self.config["deep_think_llm"],
                google_api_key=api_key,
                max_retries=3,
                request_timeout=120,
            )
            self.quick_thinking_llm = ChatGoogleGenerativeAI(
                model=self.config["quick_think_llm"],
                google_api_key=api_key,
                max_retries=3,
                request_timeout=120,
            )
        elif provider == "claude_cli":
            from tradingagents.dataflows.claude_cli import ChatClaudeCLI
            self.deep_thinking_llm = ChatClaudeCLI(
                model=self.config.get("claude_cli_deep_model", "claude-sonnet-4-6"),
                fallback_model=self.config.get("claude_cli_fallback_model", "claude-haiku-4-5-20251001"),
                timeout=int(self.config.get("claude_cli_timeout", 120)),
            )
            self.quick_thinking_llm = ChatClaudeCLI(
                model=self.config.get("claude_cli_quick_model", "claude-haiku-4-5-20251001"),
                fallback_model=self.config.get("claude_cli_fallback_model", "claude-haiku-4-5-20251001"),
                timeout=int(self.config.get("claude_cli_timeout", 60)),
            )
        elif provider == "codex_cli":
            from tradingagents.dataflows.codex_cli import ChatCodexCLI
            self.deep_thinking_llm = ChatCodexCLI(
                model=self.config.get("codex_cli_deep_model", "gpt-5.4"),
                reasoning_effort=str(
                    self.config.get("codex_cli_deep_reasoning_effort", "high")
                ),
                timeout=int(self.config.get("codex_cli_timeout", 180)),
                binary=str(self.config.get("codex_cli_binary", "codex")),
            )
            self.quick_thinking_llm = ChatCodexCLI(
                model=self.config.get("codex_cli_quick_model", "gpt-5.4"),
                reasoning_effort=str(
                    self.config.get("codex_cli_quick_reasoning_effort", "medium")
                ),
                timeout=int(self.config.get("codex_cli_timeout", 180)),
                binary=str(self.config.get("codex_cli_binary", "codex")),
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

        # Override quick_thinking_llm if quick_think_provider differs from llm_provider
        _quick_provider = self.config.get("quick_think_provider", provider).lower()
        if _quick_provider and _quick_provider != provider:
            _quick_key = get_provider_key(_quick_provider)
            if _quick_provider in ("openai", "ollama"):
                self.quick_thinking_llm = ChatOpenAI(
                    model=self.config["quick_think_llm"],
                    api_key=_quick_key,
                    max_retries=3,
                    request_timeout=120,
                )
            elif _quick_provider == "anthropic":
                self.quick_thinking_llm = ChatAnthropic(
                    model=self.config["quick_think_llm"],
                    anthropic_api_key=_quick_key,
                    max_retries=3,
                    timeout=120,
                )
            elif _quick_provider == "minimax":
                self.quick_thinking_llm = ChatAnthropic(
                    model=self.config["quick_think_llm"],
                    anthropic_api_key=_quick_key,
                    base_url="https://api.minimax.io/anthropic",
                    max_retries=3,
                    timeout=120,
                )
            elif _quick_provider == "google":
                self.quick_thinking_llm = ChatGoogleGenerativeAI(
                    model=self.config["quick_think_llm"],
                    google_api_key=_quick_key,
                    max_retries=3,
                    request_timeout=120,
                )
            elif _quick_provider == "claude_cli":
                from tradingagents.dataflows.claude_cli import ChatClaudeCLI
                self.quick_thinking_llm = ChatClaudeCLI(
                    model=self.config.get("claude_cli_quick_model", "claude-haiku-4-5-20251001"),
                    timeout=int(self.config.get("claude_cli_timeout", 60)),
                )
            elif _quick_provider == "codex_cli":
                from tradingagents.dataflows.codex_cli import ChatCodexCLI
                self.quick_thinking_llm = ChatCodexCLI(
                    model=self.config.get("codex_cli_quick_model", "gpt-5.4"),
                    reasoning_effort=str(
                        self.config.get("codex_cli_quick_reasoning_effort", "medium")
                    ),
                    timeout=int(self.config.get("codex_cli_timeout", 180)),
                    binary=str(self.config.get("codex_cli_binary", "codex")),
                )

        # Initialize memories
        self.bull_memory = FinancialSituationMemory("bull_memory", self.config)
        self.bear_memory = FinancialSituationMemory("bear_memory", self.config)
        self.trader_memory = FinancialSituationMemory("trader_memory", self.config)
        self.invest_judge_memory = FinancialSituationMemory("invest_judge_memory", self.config)
        self.risk_manager_memory = FinancialSituationMemory("risk_manager_memory", self.config)
        self.risky_memory = FinancialSituationMemory("risky_memory", self.config)
        self.safe_memory = FinancialSituationMemory("safe_memory", self.config)
        self.neutral_memory = FinancialSituationMemory("neutral_memory", self.config)
        self.trade_memory = TradeMemory()

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=int(self.config.get("max_debate_rounds", 1)),
            max_risk_discuss_rounds=int(self.config.get("max_risk_discuss_rounds", 1)),
            max_tool_iterations_per_analyst=int(
                self.config.get("max_tool_iterations_per_analyst", 6)
            ),
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.bull_memory,
            self.bear_memory,
            self.trader_memory,
            self.invest_judge_memory,
            self.risk_manager_memory,
            risky_memory=self.risky_memory,
            safe_memory=self.safe_memory,
            neutral_memory=self.neutral_memory,
            conditional_logic=self.conditional_logic,
            config=self.config,
        )

        self.propagator = Propagator()
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)
        self.sector_context = SectorContext()
        self.track_record = TrackRecord()
        self.aeternus_scorer = AeternusScorer(
            self.quick_thinking_llm,
            self.sector_context,
            self.track_record,
        )
        self.thesis_checker = ThesisChecker(self.quick_thinking_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Set up the graph
        self.graph = self.graph_setup.setup_graph(selected_analysts)
        self.post_analyst_graph = self.graph_setup.setup_post_analyst_graph()

    def _create_tool_nodes(self) -> Dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods."""
        return {
            "market": ToolNode(
                [
                    # Core stock data tools
                    get_stock_data,
                    # Technical indicators
                    get_indicators,
                ]
            ),
            "news": ToolNode(
                [
                    # News and insider information
                    get_news,
                    get_global_news,
                    get_insider_sentiment,
                    get_insider_transactions,
                ]
            ),
        }

    def propagate(self, company_name, trade_date, dealflow_context=None):
        """Run the trading agents graph for a company on a specific date."""

        self.ticker = company_name

        # Initialize state
        init_agent_state = self.propagator.create_initial_state(
            company_name, trade_date
        )

        # Inject past trade outcomes from track record
        sector = self.sector_context.get_sector(company_name)
        init_agent_state["trade_lessons"] = self.trade_memory.get_lessons(company_name, sector=sector)

        # Inject deal flow provenance so all agents see how this ticker was surfaced
        if dealflow_context:
            init_agent_state["dealflow_context"] = dealflow_context
            from tradingagents.graph.propagation import format_dealflow_provenance
            provenance = format_dealflow_provenance(dealflow_context)
            if provenance:
                init_agent_state["trade_lessons"] = (
                    init_agent_state.get("trade_lessons", "") + "\n\n" + provenance
                ).strip()

        # Build portfolio context for risk debate
        from tradingagents.graph.portfolio_context import build_portfolio_context
        execution_mode = self.config.get("execution_mode", "paper")
        portfolio_ctx = build_portfolio_context(
            execution_mode=execution_mode,
            market_regime=init_agent_state.get("market_regime"),
        )
        init_agent_state["portfolio_context"] = portfolio_ctx
        init_agent_state["drawdown_mode"] = "DRAWDOWN MODE ACTIVE" in portfolio_ctx

        # Pre-fetch research data with quality metadata for analysts
        from tradingagents.graph.research_collectors import (
            collect_market_data, collect_news_data, collect_fundamentals_data,
        )
        init_agent_state["market_raw"] = collect_market_data(company_name, trade_date)
        init_agent_state["news_raw"] = collect_news_data(company_name, trade_date)
        init_agent_state["fundamentals_raw"] = collect_fundamentals_data(company_name, trade_date)

        args = self.propagator.get_graph_args()

        if self.debug:
            # Debug mode with tracing
            trace = []
            for chunk in self.graph.stream(init_agent_state, **args):
                if len(chunk["messages"]) == 0:
                    pass
                else:
                    chunk["messages"][-1].pretty_print()
                    trace.append(chunk)

            final_state = trace[-1]
        else:
            # Standard mode without tracing
            final_state = self.graph.invoke(init_agent_state, **args)

        # Validate agent outputs — log warnings for empty/None fields, but do not crash
        _agent_output_fields = [
            "market_report",
            "news_report",
            "fundamentals_report",
            "trader_investment_plan",
            "investment_plan",
            "final_trade_decision",
        ]
        for field in _agent_output_fields:
            value = final_state.get(field) if isinstance(final_state, dict) else getattr(final_state, field, None)
            if not value:
                logger.warning(
                    "Agent output validation: field '%s' is empty or None for ticker=%s date=%s",
                    field,
                    company_name,
                    trade_date,
                )

        # Fetch options-derived sentiment
        options_metrics = None
        try:
            options_metrics = build_options_snapshot(company_name)
        except Exception as exc:
            logger.warning("Options snapshot failed for %s: %s", company_name, exc)

        # Fetch flow toxicity (BVC-based VPIN proxy)
        flow_toxicity_metrics = None
        try:
            flow_toxicity_metrics = build_flow_toxicity_snapshot(company_name)
        except Exception as exc:
            logger.warning("Flow toxicity snapshot failed for %s: %s", company_name, exc)

        # Fetch current price for track record anchoring
        _price_at_rating = None
        try:
            import yfinance as yf
            _hist = yf.Ticker(company_name).history(period="1d")
            if not _hist.empty:
                _price_at_rating = round(float(_hist["Close"].iloc[-1]), 4)
        except Exception:
            pass

        # Attach Aeternus score + rating
        final_state["aeternus_score"] = self.aeternus_scorer.score(
            final_state,
            ticker=company_name,
            date=trade_date,
            price_at_rating=_price_at_rating,
            fundamental_metrics=final_state.get("fundamental_metrics") or None,
            macro_metrics=final_state.get("macro_metrics") or None,
            momentum_metrics=final_state.get("momentum_metrics") or None,
            options_metrics=options_metrics,
            flow_toxicity_metrics=flow_toxicity_metrics,
        )

        # Write rating to AKG so nodes reach SCORED tier
        try:
            from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
            akg = AeternusKnowledgeGraph.load()
            akg.record_rating(company_name, final_state["aeternus_score"])
            akg.save()
        except Exception as exc:
            logger.warning("AKG rating writeback failed for %s: %s", company_name, exc)

        # Store current state for reflection
        self.curr_state = final_state

        # Log state
        self._log_state(trade_date, final_state)

        # Extract signal from structured verdict if available, else fallback to LLM
        structured = final_state.get("structured_verdict") or {}
        if structured.get("decision") in ("BUY", "SELL", "HOLD"):
            signal = structured["decision"]
        else:
            signal = self.process_signal(final_state["final_trade_decision"])

        return final_state, signal

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "history": final_state["investment_debate_state"]["history"],
                "current_response": final_state["investment_debate_state"][
                    "current_response"
                ],
                "judge_decision": final_state["investment_debate_state"][
                    "judge_decision"
                ],
            },
            "trader_investment_decision": final_state["trader_investment_plan"],
            "risk_debate_state": {
                "risky_history": final_state["risk_debate_state"]["risky_history"],
                "safe_history": final_state["risk_debate_state"]["safe_history"],
                "neutral_history": final_state["risk_debate_state"]["neutral_history"],
                "history": final_state["risk_debate_state"]["history"],
                "judge_decision": final_state["risk_debate_state"]["judge_decision"],
            },
            "investment_plan": final_state["investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
            "fundamental_metrics": final_state.get("fundamental_metrics", {}),
            "macro_metrics": final_state.get("macro_metrics", {}),
            "momentum_metrics": final_state.get("momentum_metrics", {}),
            "dealflow_context": final_state.get("dealflow_context", {}),
            "aeternus_score": final_state.get("aeternus_score", {}),
            "structured_verdict": final_state.get("structured_verdict", {}),
            "structured_trader_verdict": final_state.get("structured_trader_verdict", {}),
            "portfolio_context": final_state.get("portfolio_context", ""),
            "drawdown_mode": final_state.get("drawdown_mode", False),
            "detected_patterns": (final_state.get("aeternus_score") or {}).get("detected_patterns", []),
            "coherence_sub": (final_state.get("aeternus_score") or {}).get("coherence_sub"),
        }

        # Save to file
        directory = Path(f"eval_results/{self.ticker}/TradingAgentsStrategy_logs/")
        directory.mkdir(parents=True, exist_ok=True)

        with open(
            f"eval_results/{self.ticker}/TradingAgentsStrategy_logs/full_states_log_{trade_date}.json",
            "w",
        ) as f:
            json.dump(self.log_states_dict, f, indent=4)

    def reflect_and_remember(self, returns_losses):
        """Reflect on decisions and update memory based on returns."""
        self.reflector.reflect_bull_researcher(
            self.curr_state, returns_losses, self.bull_memory
        )
        self.reflector.reflect_bear_researcher(
            self.curr_state, returns_losses, self.bear_memory
        )
        self.reflector.reflect_trader(
            self.curr_state, returns_losses, self.trader_memory
        )
        self.reflector.reflect_invest_judge(
            self.curr_state, returns_losses, self.invest_judge_memory
        )
        self.reflector.reflect_risk_manager(
            self.curr_state, returns_losses, self.risk_manager_memory
        )
        self.reflector.reflect_risky_debator(
            self.curr_state, returns_losses, self.risky_memory
        )
        self.reflector.reflect_safe_debator(
            self.curr_state, returns_losses, self.safe_memory
        )
        self.reflector.reflect_neutral_debator(
            self.curr_state, returns_losses, self.neutral_memory
        )

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal)
