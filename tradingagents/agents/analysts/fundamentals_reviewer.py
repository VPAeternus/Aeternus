"""Fundamental Reviewer — deep-thinking critique layer.

Sits between the Fundamentals Analyst and the Bull/Bear debate.
The analyst gathers data cheaply; the reviewer applies SOTA reasoning
to interpret, challenge, and enhance the analysis.
"""

import json
import logging

from tradingagents.agents.utils.agent_utils import extract_text_content, make_cached_system_message

logger = logging.getLogger(__name__)


_REVIEW_PROMPT = """\
You are a senior fundamental analyst reviewing a junior analyst's report.
You have access to both the narrative report and the raw computed metrics.

Your job is NOT to summarize — the junior analyst already did that.
Your job is to CRITIQUE, INTERPRET, and ADD INSIGHT that requires deep reasoning:

1. **Challenge the narrative**: Does the data actually support the analyst's conclusions?
   Flag any claims not backed by the numbers. Identify spin or cherry-picking.

2. **Quality of earnings assessment**: Are margins sustainable or driven by one-time items?
   Is revenue growth organic or acquisition-fueled? Is the F-Score trajectory concerning?

3. **What the numbers DON'T say**: What risks are invisible in the financials?
   Competitive threats, regulatory exposure, customer concentration, capex requirements.

4. **Historical pattern matching**: Based on your knowledge, what companies with similar
   profiles (F-Score, growth rate, margin trajectory) have done well or poorly?

5. **Conviction assessment**: On a scale of HIGH/MEDIUM/LOW, how confident should we be
   in the fundamental thesis? What would change your mind?

Cite specific numbers from the metrics. Max 400 words. Be direct and opinionated."""


def create_fundamentals_reviewer(deep_thinking_llm):
    """Factory that returns a LangGraph node function for fundamental review.

    The node reads the analyst's fundamentals_report, computes anchored metrics
    via the Python engine, and invokes the deep-thinking LLM for critique.
    """

    def _gather_metrics(ticker: str, trade_date: str) -> dict:
        """Gather computed metrics via vendor routes. Gracefully degrades."""
        try:
            from tradingagents.agents.utils.fundamental_engine import (
                build_fundamental_snapshot,
            )
            from tradingagents.dataflows.interface import route_to_vendor

            overview = route_to_vendor("get_fundamentals", ticker, trade_date)
            balance = route_to_vendor("get_balance_sheet", ticker, "quarterly", trade_date)
            cashflow = route_to_vendor("get_cashflow", ticker, "quarterly", trade_date)
            income = route_to_vendor("get_income_statement", ticker, "quarterly", trade_date)

            return build_fundamental_snapshot(overview, balance, cashflow, income)
        except Exception as exc:
            logger.warning("Fundamental reviewer: metrics gathering failed for %s: %s", ticker, exc)
            return {}

    def _gather_valuation(ticker: str) -> dict:
        """Gather yfinance valuation context. Gracefully degrades."""
        try:
            from tradingagents.agents.utils.fundamental_engine import (
                compute_yfinance_snapshot,
            )
            from tradingagents.dataflows.y_finance import get_ticker_info

            info = get_ticker_info(ticker)
            return compute_yfinance_snapshot(info)
        except Exception as exc:
            logger.warning("Fundamental reviewer: valuation context failed for %s: %s", ticker, exc)
            return {}

    def fundamentals_reviewer_node(state):
        ticker = state["company_of_interest"]
        trade_date = state["trade_date"]
        analyst_report = state.get("fundamentals_report", "")

        # Gather computed metrics and valuation context
        metrics = _gather_metrics(ticker, trade_date)
        valuation = _gather_valuation(ticker)

        # Build the user prompt with all available data
        sections = []
        sections.append(f"## Company: {ticker} | Date: {trade_date}")

        if analyst_report:
            sections.append(f"## Junior Analyst Report\n{analyst_report}")
        else:
            sections.append("## Junior Analyst Report\n(No analyst report available — review metrics only.)")

        if metrics:
            sections.append(f"## Computed Fundamental Metrics\n```json\n{json.dumps(metrics, indent=2, default=str)}\n```")

        if valuation:
            sections.append(f"## Valuation Context (yfinance)\n```json\n{json.dumps(valuation, indent=2, default=str)}\n```")

        user_content = "\n\n".join(sections)

        messages = [
            make_cached_system_message(_REVIEW_PROMPT, deep_thinking_llm),
            ("human", user_content),
        ]

        response = deep_thinking_llm.invoke(messages)
        review = extract_text_content(response)

        # Compose enhanced report: reviewer critique followed by original analyst report
        if analyst_report:
            enhanced = f"## Senior Reviewer Critique\n{review}\n\n---\n\n## Original Analyst Report\n{analyst_report}"
        else:
            enhanced = f"## Senior Reviewer Critique\n{review}"

        return {
            "fundamentals_report": enhanced,
            "fundamental_metrics": metrics,
        }

    return fundamentals_reviewer_node
