from langchain_core.messages import HumanMessage, RemoveMessage


def make_cached_system_message(text, llm=None):
    """Create a system message with Anthropic prompt caching when applicable.

    When the LLM is ChatAnthropic, returns a dict with cache_control hints
    so the system prompt is cached server-side for 1 hour (90% cost reduction
    on repeated calls across batch analysis runs).
    Otherwise returns a standard LangChain tuple message.
    """
    try:
        from langchain_anthropic import ChatAnthropic as _CA
        if isinstance(llm, _CA):
            return {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
    except ImportError:
        pass
    return ("system", text)


def extract_text_content(response) -> str:
    """Extract text from LLM response, handling extended thinking blocks.

    When adaptive/extended thinking is enabled, response.content is a list
    of blocks: [{"type": "thinking", ...}, {"type": "text", "text": "..."}].
    When thinking is disabled, response.content is a plain string.
    """
    content = getattr(response, "content", "") or ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif isinstance(block, str):
                texts.append(block)
        return "\n".join(texts) if texts else ""
    return str(content) if content else ""

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_sentiment,
    get_insider_transactions,
    get_global_news,
    get_sentiment_snapshot,
    get_social_sentiment,
)

def build_evidence_brief(state: dict) -> str:
    """Format Python-computed metrics into a compact evidence string for debate prompts."""
    lines = ["--- EVIDENCE BRIEF (Computed Metrics) ---"]

    fm = state.get("fundamental_metrics") or {}
    if fm:
        piotroski = fm.get("piotroski", {})
        ratios = fm.get("ratios", {})
        balance = fm.get("balance", {})
        cashflow = fm.get("cashflow", {})
        parts = []
        if piotroski.get("fscore") is not None:
            parts.append(f"F-Score {piotroski['fscore']}/9")
        if ratios.get("roe") is not None:
            parts.append(f"ROE {ratios['roe']:.1f}%")
        if ratios.get("forward_pe") is not None:
            parts.append(f"Fwd P/E {ratios['forward_pe']:.1f}")
        elif ratios.get("pe") is not None:
            parts.append(f"P/E {ratios['pe']:.1f}")
        if balance.get("current_ratio") is not None:
            parts.append(f"Current Ratio {balance['current_ratio']:.2f}")
        if balance.get("debt_to_equity") is not None:
            parts.append(f"D/E {balance['debt_to_equity']:.2f}")
        if cashflow.get("fcf_positive") is not None:
            parts.append(f"FCF {'Positive' if cashflow['fcf_positive'] else 'Negative'}")
        lines.append(f"Fundamental: {', '.join(parts) if parts else 'Unavailable'}")
    else:
        lines.append("Fundamental: Unavailable")

    sm = state.get("sentiment_metrics") or {}
    if sm:
        parts = []
        if sm.get("composite_score") is not None:
            parts.append(f"Polarity {sm['composite_score']}/100")
        buzz = sm.get("buzz", {})
        if buzz.get("total_articles") is not None:
            parts.append(f"Articles {buzz['total_articles']}")
        if sm.get("direction"):
            parts.append(f"Direction {sm['direction']}")
        lines.append(f"Sentiment: {', '.join(parts) if parts else 'Unavailable'}")
    else:
        lines.append("Sentiment: Unavailable")

    mm = state.get("macro_metrics") or {}
    if mm:
        parts = []
        if mm.get("regime"):
            parts.append(f"Regime {mm['regime']}")
        subs = mm.get("subscores", {})
        for k in ["regime_fit", "monetary_stress", "rate_headwind", "commodity_cycle"]:
            if subs.get(k) is not None:
                parts.append(f"{k.replace('_', ' ').title()} {subs[k]}")
        lines.append(f"Macro: {', '.join(parts) if parts else 'Unavailable'}")
    else:
        lines.append("Macro: Unavailable")

    mom = state.get("momentum_metrics") or {}
    if mom:
        parts = []
        subs = mom.get("subscores", {})
        for k in ["trend_strength", "momentum_health", "regime_quality", "volume_confirmation"]:
            if subs.get(k) is not None:
                parts.append(f"{k.replace('_', ' ').title()} {subs[k]}")
        if mom.get("days_of_history") is not None:
            parts.append(f"History {mom['days_of_history']}d")
        lines.append(f"Momentum: {', '.join(parts) if parts else 'Unavailable'}")
    else:
        lines.append("Momentum: Unavailable")

    lines.append("---")
    return "\n".join(lines)


def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]
        
        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]
        
        # Add a neutral placeholder message to reset context between analyst stages.
        placeholder = HumanMessage(content="Proceed with the assigned analysis task.")
        
        return {"messages": removal_operations + [placeholder]}
    
    return delete_messages


        


