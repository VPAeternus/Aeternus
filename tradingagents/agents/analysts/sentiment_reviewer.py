"""Sentiment Reviewer — deep-thinking critique layer for social sentiment.

Sits between the Social Media Analyst and the Bull/Bear debate.
The analyst gathers sentiment data cheaply; the reviewer applies SOTA reasoning
to interpret, challenge, and enhance the analysis.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from tradingagents.agents.utils.agent_utils import extract_text_content, make_cached_system_message

logger = logging.getLogger(__name__)

# Analyst Discovery data directory (created by scripts/analyst_discovery_engine.py)
_ANALYST_DIR = Path("analyst_discovery_data/analysts")
_ANALYST_INDEX = Path("analyst_discovery_data/analyst_index.json")


_REVIEW_PROMPT = """\
You are a senior sentiment analyst reviewing a junior analyst's social media report.
You have the narrative report AND the raw computed sentiment metrics.

Your job is to CRITIQUE, INTERPRET, and ADD INSIGHT:

1. **Signal vs Noise**: Is the social buzz genuine investor interest or noise/spam?
   Does the evidence count justify the sentiment score?

2. **Sentiment-Price Divergence**: Based on the fundamentals report (if available),
   does social sentiment align with or contradict the financial reality?
   Divergence is the most valuable signal.

3. **Source Quality Assessment**: How much of the sentiment is from structured
   data (AV scores) vs unstructured text? Higher AV coverage = higher confidence.
   If analyst discovery data is provided, weight signals from A/B-tier analysts
   more heavily — their track records justify higher conviction.

4. **Catalyst Proximity**: Are the detected catalysts tradeable events?
   Earnings dates, FDA decisions, M&A rumors — which are actionable?

5. **Conviction**: HIGH/MEDIUM/LOW confidence in the sentiment thesis.
   What would flip the signal?

Cite specific numbers. Max 400 words. Be direct and opinionated."""


def _gather_analyst_context(ticker: str) -> dict:
    """Read analyst discovery profiles for this ticker. Gracefully returns {} if absent.

    Scans analyst_discovery_data/analysts/*.json for profiles covering this ticker.
    Returns a summary dict with analyst consensus, quality distribution, and top voices.
    """
    if not _ANALYST_DIR.exists():
        return {}

    ticker_upper = ticker.upper()
    covering = []

    for path in _ANALYST_DIR.glob("*.json"):
        try:
            profile = json.loads(path.read_text())
        except Exception:
            continue

        tickers_covered = [t.upper() for t in profile.get("tickers_covered", [])]
        if ticker_upper not in tickers_covered:
            continue

        covering.append({
            "handle": profile.get("handle", path.stem),
            "tier": profile.get("tier", "D"),
            "quality": profile.get("avg_quality_score", 0),
            "consistency": profile.get("consistency_score", 0),
            "followers": profile.get("follower_count", 0),
            "promoted": profile.get("promoted_to_dealflow", False),
        })

    if not covering:
        return {}

    covering.sort(key=lambda a: a["quality"], reverse=True)

    tier_counts = {}
    for a in covering:
        tier_counts[a["tier"]] = tier_counts.get(a["tier"], 0) + 1

    avg_quality = sum(a["quality"] for a in covering) / len(covering)
    promoted_count = sum(1 for a in covering if a["promoted"])

    return {
        "ticker": ticker_upper,
        "analyst_count": len(covering),
        "avg_analyst_quality": round(avg_quality, 1),
        "promoted_to_dealflow": promoted_count,
        "tier_distribution": tier_counts,
        "top_analysts": covering[:5],
    }


def _metrics_from_dealflow(ctx: dict) -> dict:
    """Build sentiment metrics directly from deal flow subscores.

    Skips all vendor routes — deal flow signals are already computed
    from direct X API and cashtag velocity analysis.
    """
    subscores = ctx.get("subscores", {})
    evidence = ctx.get("evidence", {})

    direction = "NEUTRAL"
    sm = subscores.get("social_momentum", 50)
    if sm >= 60:
        direction = "BULLISH"
    elif sm <= 40:
        direction = "BEARISH"

    return {
        "source": "dealflow",
        "social_momentum": subscores.get("social_momentum", 50),
        "news_catalyst": subscores.get("news_catalyst", 50),
        "deal_flow_score": ctx.get("deal_flow_score", 0),
        "evidence_count": evidence.get("evidence_count", 0),
        "freshness_hours": evidence.get("freshness_hours", 0),
        "direction": direction,
        "data_coverage": 1.0,
    }


def create_sentiment_reviewer(deep_thinking_llm):
    """Factory that returns a LangGraph node function for sentiment review.

    The node reads the analyst's sentiment_report, computes anchored metrics
    via the Python engine, and invokes the deep-thinking LLM for critique.
    """

    def _gather_metrics(ticker: str, trade_date: str) -> dict:
        """Gather computed sentiment metrics via vendor routes. Gracefully degrades."""
        try:
            from tradingagents.agents.utils.sentiment_engine import build_sentiment_snapshot
            from tradingagents.dataflows.interface import route_to_vendor

            start_date = (
                datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)
            ).strftime("%Y-%m-%d")

            av_raw = ""
            try:
                av_raw = route_to_vendor("get_news", ticker, start_date, trade_date)
            except Exception:
                pass

            xai_raw = ""
            try:
                xai_raw = route_to_vendor(
                    "get_news",
                    f"${ticker} social media sentiment",
                    start_date,
                    trade_date,
                )
            except Exception:
                pass

            return build_sentiment_snapshot(av_raw or "", xai_raw or "", ticker)
        except Exception as exc:
            logger.warning(
                "Sentiment reviewer: metrics gathering failed for %s: %s",
                ticker,
                exc,
            )
            return {}

    def sentiment_reviewer_node(state):
        ticker = state["company_of_interest"]
        trade_date = state["trade_date"]
        analyst_report = state.get("sentiment_report", "")
        fundamentals_report = state.get("fundamentals_report", "")

        # Use deal flow metrics when available, skip vendor routes
        dealflow_ctx = state.get("dealflow_context", {})
        if dealflow_ctx.get("subscores"):
            metrics = _metrics_from_dealflow(dealflow_ctx)
        else:
            metrics = _gather_metrics(ticker, trade_date)
        analyst_ctx = _gather_analyst_context(ticker)

        # Build the user prompt with all available data
        sections = []
        sections.append(f"## Company: {ticker} | Date: {trade_date}")

        if analyst_report:
            sections.append(f"## Junior Analyst Report\n{analyst_report}")
        else:
            sections.append(
                "## Junior Analyst Report\n(No analyst report available — review metrics only.)"
            )

        if metrics:
            sections.append(
                f"## Computed Sentiment Metrics\n```json\n{json.dumps(metrics, indent=2, default=str)}\n```"
            )

        if fundamentals_report:
            # Provide a brief fundamentals context for divergence analysis
            # Truncate to first 500 chars to keep prompt reasonable
            fund_summary = fundamentals_report[:500]
            if len(fundamentals_report) > 500:
                fund_summary += "\n... (truncated)"
            sections.append(f"## Fundamentals Context\n{fund_summary}")

        if analyst_ctx:
            sections.append(
                f"## Analyst Discovery Context\n"
                f"```json\n{json.dumps(analyst_ctx, indent=2, default=str)}\n```\n"
                f"Note: {analyst_ctx['analyst_count']} tracked analyst(s) cover this ticker. "
                f"Average quality: {analyst_ctx['avg_analyst_quality']}/100. "
                f"{analyst_ctx['promoted_to_dealflow']} promoted to deal flow. "
                f"Use analyst quality tiers to weight social signal credibility."
            )

        if dealflow_ctx.get("subscores"):
            sub_lines = "\n".join(
                f"  - {k}: {v}/100"
                for k, v in dealflow_ctx["subscores"].items()
            )
            sections.append(
                f"## Deal Flow Signals\n"
                f"Source: Direct X API + cashtag velocity analysis\n"
                f"Deal Flow Score: {dealflow_ctx.get('deal_flow_score', 'N/A')}/100\n"
                f"Subscores:\n{sub_lines}\n"
                f"Why Now: {dealflow_ctx.get('why_now', 'N/A')}\n"
                f"Thesis Tags: {', '.join(dealflow_ctx.get('thesis_tags', []))}\n"
                f"Evidence Count: {dealflow_ctx.get('evidence', {}).get('evidence_count', 'N/A')}"
            )

        user_content = "\n\n".join(sections)

        messages = [
            make_cached_system_message(_REVIEW_PROMPT, deep_thinking_llm),
            ("human", user_content),
        ]

        response = deep_thinking_llm.invoke(messages)
        review = extract_text_content(response)

        # Compose enhanced report: reviewer critique followed by original analyst report
        if analyst_report:
            enhanced = (
                f"## Senior Sentiment Reviewer Critique\n{review}\n\n"
                f"---\n\n## Original Analyst Report\n{analyst_report}"
            )
        else:
            enhanced = f"## Senior Sentiment Reviewer Critique\n{review}"

        return {
            "sentiment_report": enhanced,
            "sentiment_metrics": metrics,
        }

    return sentiment_reviewer_node
