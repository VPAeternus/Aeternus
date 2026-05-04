"""Macro Reviewer — deep-thinking critique layer for macro regime analysis.

Sits between the News Analyst and the next analyst (or Bull Researcher).
The news analyst gathers macro/geopolitical data cheaply; the reviewer applies SOTA reasoning
to interpret, challenge, and enhance the analysis using computed macro metrics.
"""

import json
import logging

from tradingagents.agents.utils.agent_utils import extract_text_content, make_cached_system_message

logger = logging.getLogger(__name__)


_REVIEW_PROMPT = """\
You are a senior macro strategist applying Ray Dalio's "Big Cycle" framework AND the \
Capital Flows risk-curve model to critique a junior analyst's news report. \
You have the narrative report AND raw computed macro metrics \
(regime classification, monetary stress, rate headwind, commodity cycle, credit spreads, \
real rates, and fiscal indicators).

Your job is to CRITIQUE, INTERPRET, and ADD INSIGHT across these dimensions:

1. **Dalio Big Cycle Position**: Where are we in the long-term debt/monetary cycle? \
   Assess the debt-to-GDP level and deficit trajectory (if available in metrics). \
   Are we in the printing/debasement phase or the tightening/austerity phase? \
   Dalio's principle: "Wars are financed by borrowing and printing money, which devalues \
   debt and money." Is gold/BTC outperformance signaling this?

2. **Five Wars Escalation Assessment**: Dalio identifies 5 types of inter-power conflict \
   that escalate in sequence: trade/economic wars → technology wars → capital wars → \
   geopolitical wars → military wars. Based on the news narrative, which stages are \
   currently active? Are sanctions, tariffs, or capital restrictions intensifying? \
   Historical pattern: economic wars precede shooting wars by ~10 years.

3. **Regime Coherence**: Does the news narrative match the computed macro regime? \
   (e.g., news says "recession fears" but SPY>SMA200 and VIX=16 → conflict) \
   Name the conflict explicitly. Markets can diverge from geopolitical reality for \
   extended periods — is the current market regime masking underlying disorder?

4. **Monetary Stress & Safe-Haven Flows**: Is gold/BTC outperformance a structural \
   fiat-confidence signal (Dalio's "alternative money" thesis) or just tactical risk-off? \
   Dalio's principle: "Sell out of all debt and buy gold" applies when the debt cycle \
   reaches the monetization phase. Is USD weakness (UUP trend) confirming debasement?

5. **Rate Impact & Fiscal Sustainability**: How do current rates affect THIS ticker? \
   Consider the "guns vs butter" tradeoff — can the government sustain both military \
   spending and social programs without destabilizing the currency? Is the deficit \
   trajectory sustainable? What does this mean for long-duration vs short-duration assets? \
   Also assess `real_rate` (dgs10 - cpi_yoy): rising real rates are headwinds for \
   growth stocks, crypto, and long-duration bonds. Falling real rates are tailwinds.

6. **Commodity Pass-through & Resource Competition**: Is the commodity cycle a margin \
   headwind or revenue tailwind for this company? Dalio's framework emphasizes that \
   resource competition intensifies during periods of great-power conflict — is DBC \
   momentum signaling supply disruption or demand strength?

7. **Credit Spread & Capital Flow Risk Curve**: Credit spreads are the PRIMARY \
   leading indicator — they widen 3–6 months before equity sell-offs. \
   Check `credit_spread_regime` (TIGHTENING/STABLE/WIDENING). \
   `hyg_vs_tlt` < 0 means HY spreads widening → capital retreating from risk. \
   `lqd_vs_tlt` < 0 means IG spreads widening → broader systemic credit stress. \
   Capital Flows framework: risk curve = Bills → Bonds → IG → HY → Equities → Alts → Crypto. \
   Risk-off = capital flows inward toward safety; where does THIS ticker sit on that curve? \
   A Financial sector company benefits when credit tightens; a high-leverage tech \
   company is among the first abandoned when HY spreads blow out. \
   Name the single metric that would FALSIFY the bullish macro case for this ticker.

8. **Cross-Asset Correlation Regime**: Check `correlation_regime.broken_pairs`. When \
   traditional correlations BREAK (state = DECOUPLED or INVERTED), any thesis that chains \
   those asset classes is unreliable. Examples: \
   - dollar_gold INVERTED → "USD rally kills gold" thesis is invalid \
   - dollar_em DECOUPLED → "strong dollar hurts EM" thesis has no current support \
   - equity_bond INVERTED → bonds no longer hedge equities (happened 2022) \
   Name which pairs are broken and what this means for the investment thesis. \
   A thesis built on a broken correlation is a thesis built on sand.

Cite specific numbers from the metrics. Reference Dalio's framework where applicable. \
Max 600 words. Be direct and opinionated. Assign HIGH/MEDIUM/LOW conviction \
for the macro thesis impact on this specific ticker."""


def create_macro_reviewer(deep_thinking_llm):
    """Factory that returns a LangGraph node function for macro review."""

    def _gather_macro_metrics(ticker: str, sector: str) -> dict:
        """Gather computed macro metrics via the macro engine. Gracefully degrades."""
        try:
            from tradingagents.agents.utils.macro_engine import build_macro_snapshot
            return build_macro_snapshot(ticker, sector=sector)
        except Exception as exc:
            logger.warning(
                "Macro reviewer: metrics gathering failed for %s: %s", ticker, exc
            )
            return {}

    def _resolve_sector(ticker: str, state: dict) -> str:
        """Resolve the ticker's sector. Sources in priority order:
        1. state["dealflow_context"].get("sector")
        2. yf.Ticker(ticker).info.get("sector")
        3. Default to ""
        """
        # Try dealflow context first
        dealflow_ctx = state.get("dealflow_context", {})
        sector = dealflow_ctx.get("sector", "")
        if sector:
            return sector

        # Fallback to yfinance
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info
            return info.get("sector", "")
        except Exception:
            return ""

    def macro_reviewer_node(state):
        ticker = state["company_of_interest"]
        trade_date = state["trade_date"]
        news_report = state.get("news_report", "")

        # Resolve sector for asset-class-sensitive scoring
        sector = _resolve_sector(ticker, state)

        # Compute macro metrics
        metrics = _gather_macro_metrics(ticker, sector)

        # Build sections for the prompt
        sections = []
        sections.append(f"## Company: {ticker} | Date: {trade_date}")

        if news_report:
            # Truncate to keep prompt reasonable
            news_summary = news_report[:800]
            if len(news_report) > 800:
                news_summary += "\n... (truncated)"
            sections.append(f"## News Analyst Report\n{news_summary}")
        else:
            sections.append("## News Analyst Report\n(No news report available — review metrics only.)")

        if metrics:
            sections.append(
                f"## Computed Macro Metrics\n```json\n{json.dumps(metrics, indent=2, default=str)}\n```"
            )

        # Add fundamentals context for cross-reference
        fundamentals_report = state.get("fundamentals_report", "")
        if fundamentals_report:
            fund_summary = fundamentals_report[:500]
            if len(fundamentals_report) > 500:
                fund_summary += "\n... (truncated)"
            sections.append(f"## Fundamentals Context\n{fund_summary}")

        user_content = "\n\n".join(sections)

        messages = [
            make_cached_system_message(_REVIEW_PROMPT, deep_thinking_llm),
            ("human", user_content),
        ]

        response = deep_thinking_llm.invoke(messages)
        review = extract_text_content(response)

        # Compose enhanced report
        if news_report:
            enhanced = (
                f"## Senior Macro Reviewer Critique\n{review}\n\n"
                f"---\n\n## Original News Report\n{news_report}"
            )
        else:
            enhanced = f"## Senior Macro Reviewer Critique\n{review}"

        return {
            "news_report": enhanced,
            "macro_metrics": metrics,
        }

    return macro_reviewer_node
