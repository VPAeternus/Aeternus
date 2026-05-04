from datetime import datetime, timedelta
from tradingagents.agents.utils.agent_utils import (
    get_fundamental_snapshot, get_valuation_context, extract_text_content,
)


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]

        # Use pre-fetched data if available, otherwise fall back to direct vendor calls
        fund_raw = state.get("fundamentals_raw") or {}
        if fund_raw.get("snapshot") or fund_raw.get("valuation"):
            snapshot = fund_raw.get("snapshot", "")
            valuation = fund_raw.get("valuation", "")
            q = fund_raw.get("quality", {})
            piotroski_status = "available" if q.get("piotroski_available") else "missing"
            quality_header = (
                f"DATA QUALITY (assess first):\n"
                f"- Data coverage: {q.get('data_coverage', '?')}\n"
                f"- Piotroski F-Score: {piotroski_status}\n"
                f"- Valuation fields: {q.get('valuation_fields', 0)} present\n"
                "If coverage < 0.5, state which sections are missing and limit financial claims.\n\n"
            )
        else:
            # Fallback: direct vendor calls (pre-collector behavior)
            snapshot = get_fundamental_snapshot.invoke({"ticker": ticker, "curr_date": current_date})
            valuation = get_valuation_context.invoke({"ticker": ticker})
            quality_header = ""

        prompt = (
            f"You are a Senior Fundamental Analyst at an institutional equity research desk "
            f"producing a fundamental analysis for {ticker} as of {current_date}.\n\n"
            "EVIDENCE HIERARCHY (weight your analysis accordingly):\n"
            "1. HARD NUMBERS — reported financials, ratios from filings (strongest)\n"
            "2. COMPUTED METRICS — Piotroski F-Score, growth rates, margin trends\n"
            "3. ANALYST ESTIMATES — forward PE, target prices (weakest — these are opinions)\n\n"
            f"{quality_header}"
            f"FETCHED DATA:\nFundamental Snapshot:\n{snapshot}\n\n"
            f"Valuation Context:\n{valuation}\n\n"
            "YOUR REPORT MUST CONTAIN EXACTLY THESE SECTIONS:\n\n"
            "## Thesis\n"
            "One sentence: is this a quality business at a fair price? State the core argument.\n\n"
            "## What Matters Most\n"
            "The 2-3 fundamental factors that will determine whether this is a good investment. "
            "Not everything — just what is decisive.\n\n"
            "## Evidence\n"
            "### Quality (Piotroski F-Score and Profitability)\n"
            "Report the F-Score (0-9) and key components. Cite ROE, ROA, profit margins. "
            "What does the score trajectory tell us?\n\n"
            "CALIBRATION:\n"
            "- F-Score 7-9 = strong quality | 4-6 = moderate | 0-3 = weak\n"
            "- ROE > 15% = good | 8-15% = acceptable | < 8% = poor\n"
            "- Operating margin expanding YoY = positive signal\n\n"
            "### Growth (Revenue/Earnings Trends)\n"
            "Cite revenue growth rate, earnings growth, margin trends. "
            "Organic vs acquisition-fueled? Sustainable or one-time?\n\n"
            "### Health (Balance Sheet and Cash Flow)\n"
            "Cite current ratio, debt-to-equity, FCF, OCF trend. Can this company survive a downturn?\n\n"
            "### Valuation (Multiples and Context)\n"
            "Cite PE, forward PE, EV/EBITDA, analyst target price vs current price. "
            "Compare to sector averages if available.\n\n"
            "EVIDENCE GATE: If a metric is not available in the fetched data, write "
            "'DATA UNAVAILABLE — [metric name]' and do NOT estimate or guess the value. "
            "Limit claims in that section accordingly.\n\n"
            "EXAMPLE OF GOOD EVIDENCE PARAGRAPH:\n"
            "'F-Score = 7/9 (up from 5 last quarter). ROE 24.3%, above sector median 18.1%. "
            "Operating margin expanded 210bps YoY to 31.5%. The two failing components are "
            "leverage increase (+0.3x) and share dilution (2.1M new shares).'\n\n"
            "EXAMPLE OF BAD EVIDENCE PARAGRAPH (do NOT write like this):\n"
            "'The company has a solid F-Score and strong profitability metrics. Margins are "
            "healthy and the balance sheet looks reasonable.'\n\n"
            "## Risks & Disconfirming Evidence (MANDATORY — do not skip)\n"
            "Name the STRONGEST fundamental argument AGAINST your thesis. Cite the specific metric.\n"
            "Then explain why your thesis survives despite it. If you cannot refute it with data, "
            "lower your conviction in the Bottom Line.\n"
            "A bullish thesis without a named bear case is INVALID. A bearish thesis without a named bull case is INVALID.\n\n"
            "## Bottom Line\n"
            "One-paragraph conviction statement: quality rating, fair value assessment, key upcoming catalyst.\n"
            "Your conclusion must trace to the evidence above — no claims that weren't established in Evidence.\n\n"
            "ANTI-PATTERNS (do NOT do these):\n"
            "- Do not present ratios without interpreting them (PE of 25 means nothing without context)\n"
            "- Do not ignore missing data — state what is unavailable and how it limits your analysis\n"
            "- Do not confuse trailing and forward metrics\n"
            "- Do not cite analyst targets as fact — they are estimates\n\n"
            "Append a Markdown summary table.\n"
            "Treat the fetched data as authoritative."
        )

        result = llm.invoke(prompt)
        report = extract_text_content(result)
        return {"fundamentals_report": report}

    return fundamentals_analyst_node
