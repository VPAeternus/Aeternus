"""X Feed Discovery Scout — scans financial X for trending cashtags via xAI x_search.

Designed to run on a schedule (every 4-8 hours) or on-demand via CLI.
Writes discovered tickers directly to AKG. Cost: ~$0.005 per run.
"""

from __future__ import annotations
import datetime as dt
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

TICKER_RE = re.compile(r"^[A-Z]{1,5}$")

# Skip crypto, forex, indices
SKIP_SYMBOLS = {
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "DOT", "AVAX", "MATIC", "LINK",
    "USD", "EUR", "GBP", "JPY", "CNY", "SPX", "NDX", "DJI", "VIX", "RUT",
    "HODL", "FOMO", "YOLO", "IMO", "LMAO", "NYSE", "NASDAQ",
}

SENTIMENT_MAP = {
    "VERY_BULLISH": 0.9,
    "BULLISH": 0.5,
    "NEUTRAL": 0.0,
    "BEARISH": -0.5,
    "VERY_BEARISH": -0.9,
}

DISCOVERY_PROMPT = (
    "Search X for financial discussions in the last 24 hours. "
    "Which US stock tickers (equities only — no crypto, no forex, no indices) are: "
    "(1) getting the most total mentions, "
    "(2) showing unusual mention volume spikes vs their baseline, or "
    "(3) generating the most debate and excitement among traders and financial accounts? "
    "Combine all three signals into a single ranked list. "
    "Also identify the dominant macro and thematic investment themes driving these tickers right now. "
    "Return active_themes: each theme has a name (snake_case), linked sectors, conviction (0-1), "
    "and one-sentence reasoning. Only include themes that are genuinely active in the current market regime. "
    "Return JSON only: "
    '{"trending": [{"ticker": "NVDA", "buzz_rank": 1, "sentiment": "BULLISH", '
    '"context": "brief reason for attention", "themes": ["AI_infrastructure"]}, ...], '
    '"active_themes": [{"theme": "AI_infrastructure", "sectors": ["Technology", "Semiconductors"], '
    '"conviction": 0.9, "reasoning": "hyperscaler capex guidance raising demand"}]}. '
    "Top 30 tickers. No BTC, ETH, or other crypto. "
    "buzz_rank is an ordinal: 1 = most talked about, 30 = least. "
    "sentiment is one of: VERY_BULLISH, BULLISH, NEUTRAL, BEARISH, VERY_BEARISH."
)


def scan_x_feed(
    config: Optional[dict] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Scan financial X via xAI x_search for trending tickers and active macro themes.
    Write discoveries to AKG.

    Returns:
        {
            "ran": bool,
            "reason": str,
            "calls_made": int,
            "tickers_found": int,
            "new_nodes_created": int,
            "existing_nodes_updated": int,
            "tickers": [{"ticker": str, "mentions_estimate": int, "context": str, "is_new": bool}],
            "themes_activated": [str],
            "themes_deactivated": [str],
            "errors": [str],
        }
    """
    cfg = config or {}
    api_key = str(os.getenv("XAI_API_KEY", "")).strip()
    if not api_key or OpenAI is None:
        return {
            "ran": False, "reason": "no_xai_api_key", "calls_made": 0,
            "tickers_found": 0, "new_nodes_created": 0, "existing_nodes_updated": 0,
            "tickers": [], "themes_activated": [], "themes_deactivated": [],
            "outlier_flags": [], "sentiment_reversals": [], "errors": [],
        }

    model = cfg.get("x_feed_scout_model", "grok-4-1-fast-reasoning")

    # --- Fetch phase — single x_search call ---
    all_tickers: Dict[str, Dict[str, Any]] = {}
    active_themes: List[Dict[str, Any]] = []
    sentiment_reversals: List[Dict[str, Any]] = []
    calls_made = 0
    errors: List[str] = []

    client = OpenAI(base_url="https://api.x.ai/v1", api_key=api_key)

    try:
        response = client.responses.create(
            model=model,
            instructions="You are a financial markets analyst. Search X for real data. Return valid JSON only.",
            input=[{"role": "user", "content": DISCOVERY_PROMPT}],
            tools=[{"type": "x_search"}],
            temperature=0.0,
            max_output_tokens=2000,
        )
        calls_made = 1
        content = response.output_text or ""
        parsed = _extract_json_payload(content)

        if isinstance(parsed, dict):
            for entry in parsed.get("trending", []):
                ticker = str(entry.get("ticker", "")).strip().upper().replace(".", "-")
                if not _is_valid_ticker(ticker):
                    continue
                buzz_rank = int(entry.get("buzz_rank", 0) or 0)
                context = str(entry.get("context", ""))[:200]
                raw_sentiment = str(entry.get("sentiment", "")).strip().upper()
                sentiment = SENTIMENT_MAP.get(raw_sentiment, 0.0)
                all_tickers[ticker] = {
                    "ticker": ticker,
                    "mentions_estimate": buzz_rank,  # ordinal rank, preserves downstream compat
                    "sentiment": sentiment,
                    "context": context,
                }
            for theme_entry in parsed.get("active_themes", []):
                theme_id = str(theme_entry.get("theme", "")).strip()
                if not theme_id:
                    continue
                try:
                    conviction = float(theme_entry.get("conviction", 0.5))
                    conviction = max(0.0, min(1.0, conviction))
                except (ValueError, TypeError):
                    conviction = 0.5
                active_themes.append({
                    "theme": theme_id,
                    "sectors": list(theme_entry.get("sectors", [])),
                    "conviction": conviction,
                    "reasoning": str(theme_entry.get("reasoning", ""))[:200],
                })
    except Exception as exc:
        errors.append(f"x_search call failed: {exc}")
        calls_made = 1

    if not all_tickers:
        return {
            "ran": True, "reason": "no_tickers_found", "calls_made": calls_made,
            "tickers_found": 0, "new_nodes_created": 0, "existing_nodes_updated": 0,
            "tickers": [], "themes_activated": [], "themes_deactivated": [],
            "outlier_flags": [], "sentiment_reversals": [], "errors": errors,
        }

    # --- Write phase ---
    if dry_run:
        ticker_list = sorted(all_tickers.values(), key=lambda t: t["mentions_estimate"])
        for t in ticker_list:
            t["is_new"] = True  # can't check without loading AKG
        return {
            "ran": True, "reason": "dry_run", "calls_made": calls_made,
            "tickers_found": len(ticker_list), "new_nodes_created": 0,
            "existing_nodes_updated": 0, "tickers": ticker_list,
            "themes_activated": [], "themes_deactivated": [],
            "outlier_flags": [], "sentiment_reversals": sentiment_reversals, "errors": errors,
        }

    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
    akg = AeternusKnowledgeGraph.load()
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

    # Snapshot prior sentiment for local reversal detection
    prior_sentiments: Dict[str, float] = {}
    for ticker in all_tickers:
        if ticker in akg._nodes:
            prior_sent = akg._nodes[ticker].get("cashtag_sentiment")
            if prior_sent is not None:
                try:
                    prior_sentiments[ticker] = float(prior_sent)
                except (ValueError, TypeError):
                    pass

    new_count = 0
    updated_count = 0
    ticker_list = []

    _compute_batch_velocity_z(all_tickers)

    for ticker, entry in sorted(all_tickers.items(), key=lambda kv: kv[1]["mentions_estimate"]):
        is_new = ticker not in akg._nodes
        if is_new:
            akg.add_node(
                ticker,
                node_type="company",
                metadata={
                    "seed_sources": ["x_feed_scout"],
                    "discovered_at": now_iso,
                    "discovery_context": entry["context"],
                },
            )
            new_count += 1
        else:
            updated_count += 1

        # Write emergence-relevant fields via enrich_node_cashtag
        akg.enrich_node_cashtag(
            ticker=ticker,
            velocity_z=entry.get("velocity_z", 0.0),
            mentions_7d=entry["mentions_estimate"],
            velocity_trend="rising" if entry.get("velocity_z", 0) > 0.5 else "stable",
            sentiment=entry.get("sentiment", 0.0),
            as_of_date=now_iso,
        )

        # Keep x_trending fields for display/audit
        akg.update_node_field(ticker, "x_trending_at", now_iso)
        akg.update_node_field(ticker, "x_trending_mentions", entry["mentions_estimate"])
        akg.update_node_field(ticker, "x_trending_context", entry["context"])

        entry["is_new"] = is_new
        ticker_list.append(entry)

    # --- Theme processing ---
    themes_activated: List[str] = []
    themes_deactivated: List[str] = []
    discovered_theme_ids: set = set()

    for theme_entry in active_themes:
        theme_id = theme_entry["theme"]
        discovered_theme_ids.add(theme_id)

        # Create theme node if it doesn't exist
        if theme_id not in akg._nodes:
            akg.add_node(theme_id, node_type="theme", metadata={
                "discovered_by": "x_feed_scout",
                "discovered_at": now_iso,
            })

        # Activate theme
        akg.activate_theme(
            theme_id=theme_id,
            macro_trigger=theme_entry.get("reasoning", "")[:200],
            conviction=theme_entry.get("conviction", 0.5),
        )
        themes_activated.append(theme_id)

        # Activate linked sectors
        for sector_id in theme_entry.get("sectors", []):
            if sector_id not in akg._nodes:
                akg.add_node(sector_id, node_type="sector")
            akg.activate_sector(
                sector_id=sector_id,
                theme_ids=[theme_id],
                priority_score=theme_entry.get("conviction", 0.5),
            )

    # Deactivate themes NOT in this scan's results
    existing_themes = akg.get_nodes_by_type("theme")
    for theme_node in existing_themes:
        tid = theme_node["id"]
        if tid not in discovered_theme_ids and theme_node.get("active", False):
            akg.deactivate_theme(theme_id=tid)
            themes_deactivated.append(tid)

    # --- Local sentiment reversal detection ---
    sentiment_reversals = []
    for ticker, entry in all_tickers.items():
        if ticker not in prior_sentiments:
            continue
        prior = prior_sentiments[ticker]
        new_sent = entry.get("sentiment", 0.0)
        if abs(new_sent - prior) >= 0.4:
            sentiment_reversals.append({
                "ticker": ticker,
                "from_sentiment": prior,
                "to_sentiment": new_sent,
                "catalyst": entry.get("context", "")[:200],
            })
            if ticker in akg._nodes:
                akg.update_node_field(ticker, "x_sentiment_reversal_from", prior)
                akg.update_node_field(ticker, "x_sentiment_reversal_to", new_sent)
                akg.update_node_field(ticker, "x_sentiment_reversal_catalyst", entry.get("context", "")[:200])
                akg.update_node_field(ticker, "x_sentiment_reversal_at", now_iso)

    # --- Dormant-sector outlier detection ---
    # Flag high-velocity company nodes in inactive sectors (potential new themes).
    outlier_flags = _detect_dormant_sector_outliers(akg, cfg)

    akg.save()

    return {
        "ran": True,
        "reason": "ok",
        "calls_made": calls_made,
        "tickers_found": len(ticker_list),
        "new_nodes_created": new_count,
        "existing_nodes_updated": updated_count,
        "tickers": ticker_list,
        "themes_activated": themes_activated,
        "themes_deactivated": themes_deactivated,
        "outlier_flags": outlier_flags,
        "sentiment_reversals": sentiment_reversals,
        "errors": errors,
    }


def _is_valid_ticker(ticker: str) -> bool:
    """Return True if ticker looks like a valid US equity symbol."""
    if not ticker or not TICKER_RE.match(ticker):
        return False
    if ticker in SKIP_SYMBOLS:
        return False
    return True


def _compute_batch_velocity_z(tickers: Dict[str, Dict[str, Any]]) -> None:
    """Compute velocity z-score in-place from buzz_rank (stored as mentions_estimate).

    Rank-based linear spread: z = (N + 1 - 2*rank) / (N - 1) * 3.
    N=30: rank 1 -> z ~ 2.9, rank 15 -> z ~ 0.1, rank 30 -> z ~ -2.9.
    """
    N = len(tickers)
    if N <= 1:
        for entry in tickers.values():
            entry["velocity_z"] = 0.0
        return
    ranks = [e["mentions_estimate"] for e in tickers.values()]
    if len(set(ranks)) == 1:
        # All same rank — no differentiation possible
        for entry in tickers.values():
            entry["velocity_z"] = 0.0
        return
    for entry in tickers.values():
        rank = entry["mentions_estimate"]
        entry["velocity_z"] = round((N + 1 - 2 * rank) / (N - 1) * 3, 4)


def _detect_dormant_sector_outliers(akg, config: dict) -> List[Dict[str, Any]]:
    """Flag company nodes with high cashtag velocity in inactive sectors.

    High velocity in a dormant sector = potential new theme forming.
    Returns list of {ticker, sector, velocity_z, flag_reason}.
    """
    active_sector_ids = akg.get_active_sector_ids()
    threshold = float(config.get("sector_scout_outlier_velocity_z", 3.0))
    outliers: List[Dict[str, Any]] = []
    for node in akg.get_nodes_by_type("company"):
        sector = node.get("sector")
        if sector and sector not in active_sector_ids:
            vz = node.get("cashtag_velocity_z") or 0.0
            if vz >= threshold:
                outliers.append({
                    "ticker": node["id"],
                    "sector": sector,
                    "velocity_z": vz,
                    "flag_reason": "high_velocity_in_dormant_sector",
                })
                akg.update_node_field(node["id"], "sector_outlier_flagged", True)
    return outliers


def _extract_json_payload(content: str):
    """Extract a JSON object from an LLM response string."""
    raw = str(content or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            return None
    return None
