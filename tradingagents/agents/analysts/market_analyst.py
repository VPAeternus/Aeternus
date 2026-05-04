from datetime import datetime, timedelta
from tradingagents.agents.utils.agent_utils import get_stock_data, get_indicators, extract_text_content

STANDARD_INDICATORS = [
    "close_50_sma", "close_200_sma", "macd", "macds",
    "rsi", "boll_ub", "boll_lb", "atr",
]


def create_market_analyst(llm):
    def market_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]

        # Use pre-fetched data if available, otherwise fall back to direct vendor calls
        market_raw = state.get("market_raw") or {}
        if market_raw.get("price_data"):
            price_data = market_raw["price_data"]
            indicator_sections = []
            for ind, data in market_raw.get("indicators", {}).items():
                indicator_sections.append(f"**{ind}**:\n{data}")
            indicators_text = "\n\n".join(indicator_sections)
            q = market_raw.get("quality", {})
            quality_header = (
                f"DATA QUALITY (assess first):\n"
                f"- Price rows: {q.get('price_rows', '?')} (expect ~60; flag if <20)\n"
                f"- Indicators: {q.get('indicators_fetched', '?')}/8 fetched"
            )
            missing = q.get("indicators_missing", [])
            if missing:
                quality_header += f", missing: {', '.join(missing)}"
            quality_header += "\nIf quality is LOW, note gaps and moderate your confidence.\n\n"
        else:
            # Fallback: direct vendor calls (pre-collector behavior)
            start_date = (
                datetime.strptime(current_date, "%Y-%m-%d") - timedelta(days=60)
            ).strftime("%Y-%m-%d")
            price_data = get_stock_data.invoke(
                {"symbol": ticker, "start_date": start_date, "end_date": current_date}
            )
            indicator_sections = []
            for ind in STANDARD_INDICATORS:
                try:
                    data = get_indicators.invoke(
                        {"symbol": ticker, "indicator": ind, "curr_date": current_date, "look_back_days": 30}
                    )
                    indicator_sections.append(f"**{ind}**:\n{data}")
                except Exception:
                    pass
            indicators_text = "\n\n".join(indicator_sections)
            quality_header = ""

        prompt = (
            f"You are a Senior Technical Analyst at an institutional equity research desk "
            f"producing a technical analysis for {ticker} as of {current_date}.\n\n"
            "EVIDENCE HIERARCHY (weight your analysis accordingly):\n"
            "1. HARD DATA — price levels, volume, indicator values with specific numbers (strongest)\n"
            "2. COMPUTED SIGNALS — RSI divergence, MACD crossovers, Bollinger band position\n"
            "3. PATTERN RECOGNITION — chart patterns, support/resistance levels (weakest — requires confirmation)\n\n"
            f"{quality_header}"
            f"FETCHED DATA:\nPrice Data (OHLCV):\n{price_data}\n\n"
            f"Technical Indicators:\n{indicators_text}\n\n"
            "YOUR REPORT MUST CONTAIN EXACTLY THESE SECTIONS:\n\n"
            "## Thesis\n"
            "One sentence: what is the dominant technical regime (bullish/bearish/neutral) and WHY.\n\n"
            "## What Matters Most\n"
            "The 2-3 technical signals that will drive the next move. Why these matter more than everything else right now.\n\n"
            "## Evidence\n"
            "Cite specific numbers from indicators. For each claim, reference the exact data point:\n"
            "- Price relative to key moving averages (50-SMA, 200-SMA) with exact values\n"
            "- Momentum indicators (RSI, MACD) with exact values and what they signal\n"
            "- Volatility context (ATR, Bollinger band position)\n"
            "- Volume trends supporting or undermining price moves\n\n"
            "CALIBRATION:\n"
            "- RSI > 70 = overbought (mean-reversion risk) | RSI < 30 = oversold (potential entry)\n"
            "- Price > 200-SMA = long-term uptrend | Price < 200-SMA = long-term downtrend\n"
            "- MACD > signal line = bullish momentum | MACD < signal line = bearish momentum\n"
            "- Price at upper Bollinger = extended | Price at lower Bollinger = compressed\n\n"
            "EVIDENCE GATE: If an indicator is missing from the fetched data, write "
            "'INDICATOR UNAVAILABLE — [name]' and do NOT infer its value from price action alone.\n\n"
            "EXAMPLE OF GOOD EVIDENCE:\n"
            "'Price at $142.30, sitting 3.2% above 50-SMA ($137.85) and 12.1% above 200-SMA ($126.90) — "
            "confirmed long-term uptrend. RSI at 63, below overbought threshold. MACD 1.24 vs signal "
            "0.89, bullish crossover 3 days ago. ATR $3.41, in line with 20-day average — no volatility expansion.'\n\n"
            "EXAMPLE OF BAD EVIDENCE (do NOT write like this):\n"
            "'The stock is trading above its moving averages which suggests an uptrend. Momentum "
            "indicators look healthy and volatility is normal.'\n\n"
            "## Risks & Disconfirming Evidence (MANDATORY — do not skip)\n"
            "Name the STRONGEST technical signal that CONTRADICTS your thesis. Cite the specific value.\n"
            "Then explain why your thesis survives despite it. If you cannot refute it with data, "
            "lower your conviction in the Bottom Line.\n\n"
            "## Bottom Line\n"
            "One-paragraph conviction statement with specific price levels to watch.\n"
            "Your conclusion must trace to the evidence above — no claims that weren't established in Evidence.\n\n"
            "ANTI-PATTERNS (do NOT do these):\n"
            "- Do not say 'trends are mixed' without explaining which trend dominates and why\n"
            "- Do not list indicators without interpreting what they mean for the trade\n"
            "- Do not ignore contradictory signals — address them head-on\n"
            "- Do not make claims without citing the specific number from the data\n"
            "- Do not describe indicator direction without the actual value\n\n"
            "Append a Markdown summary table.\n"
            "Treat the fetched data as authoritative."
        )

        result = llm.invoke(prompt)
        report = extract_text_content(result)
        return {"market_report": report}

    return market_analyst_node
