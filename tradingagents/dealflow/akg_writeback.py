"""AKG writeback helpers for DealFlowPipeline outputs."""

from __future__ import annotations

from typing import Dict, List

_DIRECTION_MAP = {"BULLISH": "bullish", "BEARISH": "bearish", "NEUTRAL": "neutral"}
_REGIME_MAP = {"BULLISH": "risk_on", "BEARISH": "risk_off", "NEUTRAL": "neutral"}


def writeback_scores_to_akg(
    akg,
    candidates: List[Dict],
    normalized_signals: List[Dict],
    as_of_date: str,
) -> int:
    """Write composite scores and source provenance to AKG nodes after scoring."""
    source_tags: Dict[str, set] = {}
    for sig in normalized_signals:
        if str(sig.get("source_status", "")) != "OK":
            continue
        sym = str(sig.get("symbol", "")).upper().strip()
        src = str(sig.get("source_name", "")).strip()
        if sym and src:
            source_tags.setdefault(sym, set()).add(src)

    count = 0
    for cand in candidates:
        ticker = str(cand.get("symbol", "")).upper().strip()
        node = akg.get_node(ticker) if hasattr(akg, "get_node") else getattr(akg, "_nodes", {}).get(ticker)
        if not ticker or node is None:
            continue
        node["pipeline_core_score"] = round(float(cand.get("core_score", 0)), 4)
        node["pipeline_momentum_score"] = round(float(cand.get("momentum_score", 0)), 4)
        node["pipeline_asymmetry_score"] = round(float(cand.get("asymmetry_score", 0)), 4)
        node["pipeline_lane"] = str(cand.get("lane", "CORE"))
        node["pipeline_scored_at"] = as_of_date
        tags = source_tags.get(ticker, set())
        if tags:
            node["pipeline_source_tags"] = sorted(tags)
        count += 1
    return count


def writeback_signals_to_akg(akg, signals: List[Dict], as_of_date: str) -> int:
    """Write pipeline signal dicts back to AKG nodes via enrich_node_* methods."""
    social_news_pairs: Dict[str, Dict[str, float]] = {}
    write_count = 0

    for sig in signals:
        if sig.get("source_status") != "OK":
            continue
        ticker = str(sig.get("symbol", "")).upper().strip()
        if not ticker:
            continue
        family = sig.get("signal_family", "")
        score = float(sig.get("raw_score", 0))
        direction = str(sig.get("direction", "NEUTRAL"))

        if family == "price_momentum":
            akg.enrich_node_price_momentum(ticker, score, rs_spy=0.0, as_of_date=as_of_date)
            write_count += 1
        elif family == "smart_money":
            akg.enrich_node_smart_money(ticker, score, direction=_DIRECTION_MAP.get(direction, "neutral"), as_of_date=as_of_date)
            write_count += 1
        elif family == "insider_cluster":
            buyer = int(sig.get("cluster_size") or sig.get("evidence_count", 0))
            akg.enrich_node_insider_cluster(ticker, score, buyer_count=buyer, as_of_date=as_of_date)
            write_count += 1
        elif family == "social_momentum":
            social_news_pairs.setdefault(ticker, {"social": 0.0, "news": 0.0})["social"] = score
        elif family == "news_catalyst":
            social_news_pairs.setdefault(ticker, {"social": 0.0, "news": 0.0})["news"] = score
        elif family == "sector_rotation":
            akg.enrich_node_sector_rotation(ticker, score, as_of_date=as_of_date)
            write_count += 1
        elif family == "macro_regime_fit":
            akg.enrich_node_macro_regime(ticker, score, regime_tag=_REGIME_MAP.get(direction, "neutral"), as_of_date=as_of_date)
            write_count += 1

    for sn_ticker, sn_scores in social_news_pairs.items():
        akg.enrich_node_social_news(sn_ticker, social_score=sn_scores["social"], news_catalyst_score=sn_scores["news"], as_of_date=as_of_date)
        write_count += 1

    return write_count
