"""Compatibility sentiment reviewer node for legacy graph tests."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from tradingagents.agents.utils.agent_utils import extract_text_content, make_cached_system_message

logger = logging.getLogger(__name__)

_ANALYST_DIR = Path("analyst_discovery_data/analysts")

_REVIEW_PROMPT = """\
You are a senior sentiment analyst reviewing a junior analyst's social media report.
Critique signal quality, sentiment-price divergence, source quality, catalyst
proximity, and conviction. Cite specific numbers when available."""


def _gather_analyst_context(ticker: str) -> dict:
    if not _ANALYST_DIR.exists():
        return {}

    ticker_upper = ticker.upper()
    covering = []
    for path in _ANALYST_DIR.glob("*.json"):
        try:
            profile = json.loads(path.read_text())
        except Exception:
            continue
        covered = [str(item).upper() for item in profile.get("tickers_covered", [])]
        if ticker_upper not in covered:
            continue
        covering.append(
            {
                "handle": profile.get("handle", path.stem),
                "tier": profile.get("tier", "D"),
                "quality": profile.get("avg_quality_score", 0),
                "consistency": profile.get("consistency_score", 0),
                "followers": profile.get("follower_count", 0),
                "promoted": profile.get("promoted_to_dealflow", False),
            }
        )

    if not covering:
        return {}

    covering.sort(key=lambda row: row["quality"], reverse=True)
    tier_counts: dict[str, int] = {}
    for analyst in covering:
        tier = analyst["tier"]
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    return {
        "ticker": ticker_upper,
        "analyst_count": len(covering),
        "avg_analyst_quality": round(sum(row["quality"] for row in covering) / len(covering), 1),
        "promoted_to_dealflow": sum(1 for row in covering if row["promoted"]),
        "tier_distribution": tier_counts,
        "top_analysts": covering[:5],
    }


def _metrics_from_dealflow(ctx: dict) -> dict:
    subscores = ctx.get("subscores", {})
    evidence = ctx.get("evidence", {})
    social_momentum = subscores.get("social_momentum", 50)
    if social_momentum >= 60:
        direction = "BULLISH"
    elif social_momentum <= 40:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    return {
        "source": "dealflow",
        "social_momentum": social_momentum,
        "cashtag_momentum": subscores.get("cashtag_momentum", 50),
        "news_catalyst": subscores.get("news_catalyst", 50),
        "deal_flow_score": ctx.get("deal_flow_score", 0),
        "evidence_count": evidence.get("evidence_count", 0),
        "freshness_hours": evidence.get("freshness_hours", 0),
        "direction": direction,
        "data_coverage": 1.0,
    }


def _gather_metrics(ticker: str, trade_date: str) -> dict:
    try:
        from tradingagents.agents.utils.sentiment_engine import build_sentiment_snapshot
        from tradingagents.dataflows.interface import route_to_vendor

        start_date = (
            datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)
        ).strftime("%Y-%m-%d")

        try:
            av_raw = route_to_vendor("get_news", ticker, start_date, trade_date)
        except Exception:
            av_raw = ""
        try:
            xai_raw = route_to_vendor(
                "get_news",
                f"${ticker} social media sentiment",
                start_date,
                trade_date,
            )
        except Exception:
            xai_raw = ""
        return build_sentiment_snapshot(av_raw or "", xai_raw or "", ticker)
    except Exception as exc:
        logger.warning("Sentiment reviewer metrics failed for %s: %s", ticker, exc)
        return {}


def create_sentiment_reviewer(deep_thinking_llm):
    def sentiment_reviewer_node(state):
        ticker = state["company_of_interest"]
        trade_date = state["trade_date"]
        analyst_report = state.get("sentiment_report", "")
        fundamentals_report = state.get("fundamentals_report", "")
        dealflow_ctx = state.get("dealflow_context", {})

        metrics = (
            _metrics_from_dealflow(dealflow_ctx)
            if dealflow_ctx.get("subscores")
            else _gather_metrics(ticker, trade_date)
        )
        analyst_ctx = _gather_analyst_context(ticker)

        sections = [f"## Company: {ticker} | Date: {trade_date}"]
        if analyst_report:
            sections.append(f"## Junior Analyst Report\n{analyst_report}")
        else:
            sections.append("## Junior Analyst Report\nNo analyst report available.")
        if metrics:
            sections.append(f"## Computed Sentiment Metrics\n{json.dumps(metrics, indent=2, default=str)}")
        if fundamentals_report:
            sections.append(f"## Fundamentals Context\n{fundamentals_report[:500]}")
        if analyst_ctx:
            sections.append(f"## Analyst Discovery Context\n{json.dumps(analyst_ctx, indent=2, default=str)}")
        if dealflow_ctx.get("subscores"):
            sub_lines = "\n".join(
                f"  - {key}: {value}/100"
                for key, value in dealflow_ctx["subscores"].items()
            )
            sections.append(
                "## Deal Flow Signals\n"
                "Source: Direct X API + cashtag velocity analysis\n"
                f"Deal Flow Score: {dealflow_ctx.get('deal_flow_score', 'N/A')}/100\n"
                f"Subscores:\n{sub_lines}\n"
                f"Why Now: {dealflow_ctx.get('why_now', 'N/A')}\n"
                f"Thesis Tags: {', '.join(dealflow_ctx.get('thesis_tags', []))}\n"
                f"Evidence Count: {dealflow_ctx.get('evidence', {}).get('evidence_count', 'N/A')}"
            )

        messages = [
            make_cached_system_message(_REVIEW_PROMPT, deep_thinking_llm),
            ("human", "\n\n".join(sections)),
        ]
        review = extract_text_content(deep_thinking_llm.invoke(messages))
        if analyst_report:
            report = (
                f"## Senior Sentiment Reviewer Critique\n{review}\n\n"
                f"---\n\n## Original Analyst Report\n{analyst_report}"
            )
        else:
            report = f"## Senior Sentiment Reviewer Critique\n{review}"
        return {"sentiment_report": report, "sentiment_metrics": metrics}

    return sentiment_reviewer_node
