"""Momentum Reviewer — deep-thinking critique layer for momentum regime analysis.

Sits between the Market Analyst (technical) and the analyst discussion.
The market analyst gathers technical data cheaply; the reviewer applies SOTA reasoning
to interpret, challenge, and enhance the analysis using computed momentum metrics.
"""

import json
import logging

from tradingagents.agents.utils.agent_utils import extract_text_content, make_cached_system_message

logger = logging.getLogger(__name__)


_REVIEW_PROMPT = """\
You are a Senior Momentum Analyst reviewing a market/technical analyst report through the lens \
of quantitative regime analysis and second-derivative momentum signals.

Your job is to CRITIQUE, INTERPRET, and ADD INSIGHT across these dimensions:

1. **Regime Classification**: What regime is the ticker in (BULLISH/NEUTRAL/BEARISH)? \
   Does the analyst's technical narrative align with the computed regime classification? \
   Name any conflict explicitly — narrative and quant diverge more than people expect.

2. **Acceleration Percentile Position**: Where does accel_percentile sit relative to \
   overbought (>80) or oversold (<20) thresholds? \
   Overbought momentum is a mean-reversion risk, not a buy signal. \
   Oversold momentum in an uptrend regime is often the optimal entry.

3. **Signal State (Long / Cash / Short)**: Is the current signal state consistent \
   with the momentum sub-scores? \
   A "long" signal with declining trend_strength warrants skepticism. \
   A "cash" signal with rising momentum_health is a potential re-entry setup.

4. **Trend Quality — invested_pct_2y**: What fraction of the past 2 years has the \
   strategy been invested? High invested_pct_2y (>70%) signals persistent trend quality. \
   Low invested_pct_2y (<40%) signals choppy, low-conviction price action.

5. **Volume Confirmation**: Is price momentum supported by volume_confirmation sub-score? \
   Price moves without volume are suspect. Volume divergence (rising price, falling volume) \
   is a distribution signal.

6. **Cross-Pillar Divergence**: Does the momentum regime conflict with the fundamentals \
   narrative (if provided)? Momentum leading fundamentals is bullish. \
   Fundamentals leading momentum is a lagging entry risk.

Cite specific numbers from the metrics. \
Give a concise momentum verdict: BULLISH / NEUTRAL / BEARISH with key supporting evidence. \
Assign HIGH/MEDIUM/LOW conviction. \
Keep your critique under 300 words — precise and actionable. \
Focus on: regime classification, acceleration percentile, signal state, \
invested_pct_2y as trend quality signal, and any divergence with the analyst's narrative."""


def create_momentum_reviewer(deep_thinking_llm):
    """Factory that returns a LangGraph node function for momentum review."""

    def _gather_momentum_metrics(ticker: str, trade_date: str) -> dict:
        """Gather computed momentum metrics via the momentum engine. Gracefully degrades."""
        try:
            from tradingagents.agents.utils.momentum_engine import build_momentum_snapshot
            return build_momentum_snapshot(ticker, trade_date)
        except Exception as exc:
            logger.warning(
                "Momentum reviewer: metrics gathering failed for %s: %s", ticker, exc
            )
            return {}

    def _metrics_from_dealflow(ctx: dict, ticker: str, trade_date: str) -> dict:
        """Build momentum metrics from deal flow composite + real engine sub-scores.

        Uses the dealflow price_momentum as headline composite but calls
        build_momentum_snapshot() for independent sub-scores (trend_strength,
        momentum_health, regime_quality, volume_confirmation).
        Falls back to composite for all 4 if the engine fails.
        """
        subscores = ctx.get("subscores", {})
        pm = subscores.get("price_momentum")
        if pm is None:
            return {}

        direction = "BULLISH" if pm >= 60 else ("BEARISH" if pm <= 40 else "NEUTRAL")

        # Try real engine for independent sub-scores
        engine_subs = None
        try:
            from tradingagents.agents.utils.momentum_engine import build_momentum_snapshot
            snap = build_momentum_snapshot(ticker, trade_date)
            if snap and snap.get("subscores"):
                engine_subs = snap["subscores"]
        except Exception as exc:
            logger.debug("Momentum engine fallback for %s: %s", ticker, exc)

        if engine_subs:
            sub_dict = {
                "trend_strength": int(engine_subs.get("trend_strength", pm)),
                "momentum_health": int(engine_subs.get("momentum_health", pm)),
                "regime_quality": int(engine_subs.get("regime_quality", pm)),
                "volume_confirmation": int(engine_subs.get("volume_confirmation", pm)),
            }
        else:
            sub_dict = {
                "trend_strength": int(pm),
                "momentum_health": int(pm),
                "regime_quality": int(pm),
                "volume_confirmation": int(pm),
            }

        return {
            "source": "dealflow",
            "composite_score": int(pm),
            "direction": direction,
            "subscores": sub_dict,
            "data_coverage": 1.0,
        }

    def momentum_reviewer_node(state):
        ticker = state["company_of_interest"]
        trade_date = state["trade_date"]
        market_report = state.get("market_report", "")
        fundamentals_report = state.get("fundamentals_report", "")
        dealflow_ctx = state.get("dealflow_context", {})

        # Use deal flow price_momentum when available — skip vendor routes
        if dealflow_ctx.get("subscores", {}).get("price_momentum") is not None:
            metrics = _metrics_from_dealflow(dealflow_ctx, ticker, trade_date)
        else:
            metrics = _gather_momentum_metrics(ticker, trade_date)

        # Build the user prompt with all available data
        sections = []
        sections.append(f"## Company: {ticker} | Date: {trade_date}")

        if metrics:
            sections.append(
                f"## Computed Momentum Metrics\n```json\n{json.dumps(metrics, indent=2, default=str)}\n```"
            )
        else:
            sections.append(
                "## Computed Momentum Metrics\n(Quantitative metrics unavailable — critique narrative only.)"
            )

        if market_report:
            market_summary = market_report[:1000]
            if len(market_report) > 1000:
                market_summary += "\n... (truncated)"
            sections.append(f"## Original Market Analyst Report\n{market_summary}")
        else:
            sections.append(
                "## Original Market Analyst Report\n(No market report available — review metrics only.)"
            )

        if fundamentals_report:
            fund_summary = fundamentals_report[:400]
            if len(fundamentals_report) > 400:
                fund_summary += "\n... (truncated)"
            sections.append(f"## Fundamentals Context\n{fund_summary}")

        if dealflow_ctx.get("subscores"):
            sub_lines = "\n".join(
                f"  - {k}: {v}/100"
                for k, v in dealflow_ctx["subscores"].items()
            )
            sections.append(
                f"## Deal Flow Signals\n"
                f"Subscores:\n{sub_lines}\n"
                f"Why Now: {dealflow_ctx.get('why_now', 'N/A')}"
            )

        user_content = "\n\n".join(sections)

        messages = [
            make_cached_system_message(_REVIEW_PROMPT, deep_thinking_llm),
            ("human", user_content),
        ]

        response = deep_thinking_llm.invoke(messages)
        review = extract_text_content(response)

        # Compose enhanced report: reviewer critique followed by original market report
        if market_report:
            enhanced = (
                f"## Senior Momentum Reviewer Critique\n{review}\n\n"
                f"---\n\n## Original Market Report\n{market_report}"
            )
        else:
            enhanced = f"## Senior Momentum Reviewer Critique\n{review}"

        return {
            "market_report": enhanced,
            "momentum_metrics": metrics,
        }

    return momentum_reviewer_node
