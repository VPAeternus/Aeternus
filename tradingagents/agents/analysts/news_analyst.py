from datetime import datetime, timedelta
from tradingagents.agents.utils.agent_utils import get_news, get_global_news, extract_text_content


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]

        # Use pre-fetched data if available, otherwise fall back to direct vendor calls
        news_raw = state.get("news_raw") or {}
        if news_raw.get("company_news") or news_raw.get("global_news"):
            company_news = news_raw.get("company_news", "")
            global_news = news_raw.get("global_news", "")
            q = news_raw.get("quality", {})
            co_avail = "available" if q.get("company_news_available") else "empty"
            gl_avail = "available" if q.get("global_news_available") else "empty"
            quality_header = (
                f"DATA QUALITY (assess first):\n"
                f"- Company news: {co_avail} ({q.get('company_news_chars', 0)} chars)\n"
                f"- Global news: {gl_avail} ({q.get('global_news_chars', 0)} chars)\n"
                "If either source is empty, note the gap and limit claims about news flow.\n\n"
            )
        else:
            # Fallback: direct vendor calls (pre-collector behavior)
            start_date = (
                datetime.strptime(current_date, "%Y-%m-%d") - timedelta(days=7)
            ).strftime("%Y-%m-%d")
            company_news = get_news.invoke(
                {"ticker": ticker, "start_date": start_date, "end_date": current_date}
            )
            global_news = get_global_news.invoke(
                {"curr_date": current_date, "look_back_days": 7, "limit": 5}
            )
            quality_header = ""

        prompt = (
            f"You are a Senior Macro/News Analyst at an institutional equity research desk "
            f"analyzing recent developments for {ticker} as of {current_date}.\n\n"
            "EVIDENCE HIERARCHY (weight your analysis accordingly):\n"
            "1. CONFIRMED EVENTS — earnings releases, regulatory filings, official announcements (strongest)\n"
            "2. CREDIBLE REPORTING — major news outlets with named sources\n"
            "3. MARKET COMMENTARY — analyst notes, opinion pieces (weakest — often backward-looking)\n\n"
            f"{quality_header}"
            f"FETCHED DATA:\nCompany News ({ticker}):\n{company_news}\n\n"
            f"Global Macro News:\n{global_news}\n\n"
            "YOUR REPORT MUST CONTAIN EXACTLY THESE SECTIONS:\n\n"
            "## Thesis\n"
            "One sentence: what is the dominant news narrative and how does it affect the investment case?\n\n"
            "## What Matters Most\n"
            "The 1-2 news developments that could materially move the stock. "
            "Not everything that happened — just what is tradeable.\n\n"
            "## Evidence\n"
            "Every claim MUST include a date and source attribution. Format: 'On [date], [source] reported [fact].'\n"
            "If no date is available for a claim, write 'DATE UNKNOWN' — do not omit silently.\n\n"
            "- Company-specific news: cite dates, sources, and specific facts\n"
            "- Macro developments: how do current economic/geopolitical conditions affect this company specifically?\n"
            "- Sector developments: any peer news that creates read-through for this ticker?\n"
            "- Regulatory/policy: any upcoming decisions or rule changes that could impact operations?\n\n"
            "EXAMPLE OF GOOD EVIDENCE:\n"
            "'On Mar 3, Reuters reported NVDA received $2.1B in new Blackwell orders from Microsoft, "
            "bringing Q1 backlog to $8.4B. On Mar 5, the company filed an 8-K disclosing a $500M "
            "accelerated buyback program.'\n\n"
            "EXAMPLE OF BAD EVIDENCE (do NOT write like this):\n"
            "'There has been positive news around the company recently. Analysts are optimistic "
            "about the sector outlook and management commentary has been encouraging.'\n\n"
            "EVIDENCE GATE: If the fetched data contains no company-specific news, state "
            "'NO COMPANY NEWS AVAILABLE — analysis limited to macro context' and do not fabricate events.\n\n"
            "## Risks & Disconfirming Evidence (MANDATORY — do not skip)\n"
            "Name the STRONGEST news item or upcoming event that CONTRADICTS your thesis. "
            "Be specific: date, source, and why it matters.\n"
            "Then explain why your thesis survives despite it. If you cannot, say so and lower conviction.\n\n"
            "## Bottom Line\n"
            "One-paragraph assessment: is the news flow net positive or negative, and what is the one event to watch?\n"
            "Your conclusion must trace to the evidence above — no claims that weren't established in Evidence.\n\n"
            "ANTI-PATTERNS (do NOT do these):\n"
            "- Do not summarize every news item equally — prioritize by materiality\n"
            "- Do not speculate about future news without flagging it as speculation\n"
            "- Do not conflate global macro trends with company-specific impact without explaining the linkage\n"
            "- Do not ignore the absence of news — silence on a topic can be informative\n"
            "- Do not cite news without a date — every event must be anchored in time\n\n"
            "Append a Markdown summary table.\n"
            "Treat the fetched data as authoritative."
        )

        result = llm.invoke(prompt)
        report = extract_text_content(result)
        return {"news_report": report}

    return news_analyst_node
