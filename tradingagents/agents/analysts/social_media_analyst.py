from datetime import datetime, timedelta
from tradingagents.agents.utils.agent_utils import (
    get_sentiment_snapshot, get_social_sentiment, extract_text_content
)


def create_social_media_analyst(llm):
    def social_media_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        dealflow_ctx = state.get("dealflow_context", {})
        dealflow_subscores = dealflow_ctx.get("subscores", {})
        start_date = (
            datetime.strptime(current_date, "%Y-%m-%d") - timedelta(days=7)
        ).strftime("%Y-%m-%d")

        if dealflow_subscores:
            # Build snapshot from dealflow data — mirrors sentiment_reviewer pattern.
            # Avoids live vendor calls (AV, xAI) that return empty when not configured.
            evidence = dealflow_ctx.get("evidence", {})
            sm = dealflow_subscores.get("social_momentum", 50)
            nc = dealflow_subscores.get("news_catalyst", 50)
            ev_count = evidence.get("evidence_count", 0)
            freshness = evidence.get("freshness_hours", 0)
            direction = "BULLISH" if sm >= 60 else ("BEARISH" if sm <= 40 else "NEUTRAL")
            sentiment_snapshot = (
                f'{{"source": "dealflow", "composite_score": {sm}, '
                f'"direction": "{direction}", '
                f'"data_coverage": 1.0, '
                f'"total_articles": {ev_count}, '
                f'"social_momentum": {sm}, "news_catalyst": {nc}, '
                f'"freshness_hours": {freshness}}}'
            )
            social_narrative = (
                f"Deal flow signals: {ev_count} evidence items, "
                f"social_momentum={sm}/100, news_catalyst={nc}/100, "
                f"freshness={freshness}h. Direction: {direction}."
            )
        else:
            sentiment_snapshot = get_sentiment_snapshot.invoke(
                {"ticker": ticker, "curr_date": current_date}
            )
            social_narrative = get_social_sentiment.invoke(
                {"ticker": ticker, "start_date": start_date, "end_date": current_date}
            )

        dealflow_block = ""
        if dealflow_subscores:
            sub_lines = "\n".join(f"  - {k}: {v}/100" for k, v in dealflow_subscores.items())
            evidence = dealflow_ctx.get("evidence", {})
            tags = dealflow_ctx.get("thesis_tags", [])
            why_now = dealflow_ctx.get("why_now", "")
            lane = dealflow_ctx.get("lane", "")
            playbook = dealflow_ctx.get("research_playbook", "")
            df_score = dealflow_ctx.get("deal_flow_score", "N/A")
            dealflow_block = (
                "## Deal Flow Signals (PRIMARY DATA SOURCE)\n"
                "Deal flow signals from direct X API and cashtag velocity analysis:\n\n"
                f"**Deal Flow Score**: {df_score}/100\n"
                f"**Subscores**:\n{sub_lines}\n"
                f"**Evidence**: {evidence.get('evidence_count', 'N/A')} items, "
                f"freshness {evidence.get('freshness_hours', 'N/A')}h\n"
                f"**Thesis Tags**: {', '.join(tags) if tags else 'None'}\n"
                f"**Why Now**: {why_now or 'N/A'}\n"
                f"**Lane**: {lane or 'N/A'}\n"
                f"**Research Playbook**: {playbook or 'N/A'}\n\n"
                "Use these as your PRIMARY data source for sentiment assessment.\n\n"
            )

        prompt = (
            f"You are a Senior Sentiment Analyst at an institutional equity research desk "
            f"analyzing market sentiment for {ticker} as of {current_date}.\n\n"
            "EVIDENCE HIERARCHY (weight your analysis accordingly):\n"
            "1. QUANTITATIVE SENTIMENT — computed scores, article counts, momentum metrics (strongest)\n"
            "2. DEAL FLOW SIGNALS — evidence counts, freshness, thesis tags from screening pipeline\n"
            "3. QUALITATIVE NARRATIVE — descriptions of social buzz, tone (weakest — subjective)\n\n"
            f"{dealflow_block}"
            f"FETCHED DATA:\nSentiment Snapshot (computed metrics):\n{sentiment_snapshot}\n\n"
            f"Social Narrative:\n{social_narrative}\n\n"
            "YOUR REPORT MUST CONTAIN EXACTLY THESE SECTIONS:\n\n"
            "## Thesis\n"
            "One sentence: is sentiment confirming or diverging from the fundamental/technical picture?\n\n"
            "## What Matters Most\n"
            "Is sentiment a leading indicator here (predicting a move) or a lagging indicator (reacting to one)? "
            "This is the most important question.\n\n"
            "## Evidence\n"
            "### Sentiment Polarity\n"
            "Report computed composite score and direction (bullish/bearish/neutral). Cite article count and relevance.\n\n"
            "CALIBRATION:\n"
            "- Score >= 70 = strong bullish | 55-69 = mild bullish | 45-54 = neutral\n"
            "- Score 30-44 = mild bearish | <= 29 = strong bearish\n"
            "- Evidence count < 3 = LOW CONFIDENCE — flag this prominently\n\n"
            "### Social Engagement\n"
            "Volume of discussion relative to baseline. Is attention unusual? Source quality assessment.\n\n"
            "### Catalyst Events\n"
            "Specific catalysts detected (earnings, FDA, M&A, guidance). Which are tradeable?\n\n"
            "### Narrative Context\n"
            "Key themes driving sentiment. Are they grounded in facts or speculation?\n\n"
            "LOW DATA GATE: If the sentiment snapshot has fewer than 3 data points or "
            "evidence_count < 3, state 'LOW DATA — sentiment signal unreliable' at the top "
            "of this section. Report only what the numbers say — do not pad with generic "
            "sentiment commentary to fill space.\n\n"
            "EXAMPLE OF GOOD EVIDENCE:\n"
            "'Composite score 72/100 (BULLISH), based on 14 articles and deal flow evidence "
            "count of 8. Social momentum 65/100, up from 45 last week. News catalyst score "
            "78/100 driven by FDA approval catalyst (tradeable, binary event on Apr 12).'\n\n"
            "EXAMPLE OF BAD EVIDENCE (do NOT write like this):\n"
            "'Sentiment appears to be positive with growing interest from retail investors. "
            "The overall mood on social media is optimistic about the company\\'s prospects.'\n\n"
            "## Risks & Disconfirming Evidence (MANDATORY — do not skip)\n"
            "Name the STRONGEST sentiment signal that CONTRADICTS your thesis (divergence, extreme, "
            "or counter-narrative). Cite the specific metric or data point.\n"
            "Then explain why your thesis survives despite it. If you cannot, say so and lower conviction.\n\n"
            "## Bottom Line\n"
            "One-paragraph assessment: sentiment signal strength, whether it is actionable, and key risk.\n"
            "Your conclusion must trace to the evidence above — no claims that weren't established in Evidence.\n\n"
            "ANTI-PATTERNS (do NOT do these):\n"
            "- Do not treat sentiment as directional without noting it can be wrong (crowds overshoot)\n"
            "- Do not cite social buzz without assessing source quality\n"
            "- Do not conflate volume of discussion with quality of signal\n"
            "- Do not present deal flow scores as absolute — they are relative to the screening universe\n"
            "- Do not pad thin data with generic commentary — say 'LOW DATA' and keep it short\n\n"
            "Append a Markdown summary table."
        )

        result = llm.invoke(prompt)
        report = extract_text_content(result)
        return {"sentiment_report": report}

    return social_media_analyst_node
