"""
Real market ignorance scoring from live data (S-056).
Replaces centrality-proxy in structural force dark matter discovery.
"""
from __future__ import annotations
import datetime as dt
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph


def compute_market_ignorance(ticker: str, akg: "AeternusKnowledgeGraph") -> float:
    """
    Compute market ignorance score (0.0=fully known, 1.0=completely invisible).

    Sources:
    - analyst_count: yfinance numberOfAnalystOpinions (free)
    - inst_pct: yfinance heldPercentInstitutions (free, same API call)
    - news_count_30d: AKG node field written by cashtag enricher

    Result cached 7 days on AKG node under:
      market_ignorance_score_real, analyst_count, institutional_pct,
      market_ignorance_cached_at

    Falls back to centrality-proxy if yfinance unavailable.
    Tickers not in AKG return 1.0 immediately (maximum ignorance).
    """
    # Ticker not in AKG → completely unknown, max ignorance
    node = akg._nodes.get(ticker)
    if node is None:
        return 1.0

    # 7-day cache hit
    cached_at = node.get("market_ignorance_cached_at")
    if cached_at:
        try:
            age_days = (dt.date.today() - dt.date.fromisoformat(cached_at)).days
            if age_days < 7:
                cached = node.get("market_ignorance_score_real")
                if cached is not None:
                    return float(cached)
        except (ValueError, TypeError):
            pass

    # yfinance fetch
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info

        analyst_count = int(info.get("numberOfAnalystOpinions") or 0)
        inst_pct      = float(info.get("heldPercentInstitutions") or 0.0)
        news_count    = int(node.get("news_count_30d") or 0)

        analyst_ig = max(0.0, 1.0 - analyst_count / 30.0)
        inst_ig    = max(0.0, 1.0 - inst_pct / 0.90)
        news_ig    = max(0.0, 1.0 - min(news_count / 20.0, 1.0))

        score = round(0.50 * analyst_ig + 0.35 * inst_ig + 0.15 * news_ig, 4)

        # Write back to AKG node (cache)
        node["market_ignorance_score_real"] = score
        node["analyst_count"]               = analyst_count
        node["institutional_pct"]           = inst_pct
        node["market_ignorance_cached_at"]  = dt.date.today().isoformat()

        return score

    except Exception:
        # Fallback: centrality proxy (S-052 original logic)
        centrality    = float(node.get("centrality") or 0.0)
        times_surfaced = int(node.get("times_surfaced") or 0)
        return max(0.0, 1.0 - min(centrality + times_surfaced / 100.0, 1.0))
