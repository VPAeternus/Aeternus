"""Node/edge templates and small helpers for Aeternus Knowledge Graph."""

from __future__ import annotations

import datetime as dt
from typing import Optional


def node_template(node_id: str, node_type: str = "company", sector: Optional[str] = None,
                  display_name: Optional[str] = None, metadata: Optional[dict] = None) -> dict:
    return {
        "id": node_id,
        "node_type": node_type,
        "sector": sector,
        "display_name": display_name or node_id,
        "signal_strength": 0.0,
        "centrality": 0.0,
        "times_surfaced": 0,
        "last_surfaced": None,
        "aeternus_score": None,
        "thesis_track_record": {"confirmed": 0, "invalidated": 0},
        "metadata": metadata or {},
        "cashtag_velocity_z": None,
        "cashtag_mentions_7d": None,
        "cashtag_velocity_trend": None,
        "cashtag_sentiment": None,
        "cashtag_last_updated": None,
        "sec_event_type": None,
        "sec_event_date": None,
        "emergence_score": None,
        "emergence_tier": None,
        "emergence_n_sources": 0,
        "active": False,
        "activation_date": None,
        "deactivation_date": None,
        "macro_trigger": None,
        "conviction": 0.0,
        "expected_duration_months": None,
        "active_themes": [],
        "priority_score": 0.0,
        "activated_date": None,
        "deactivated_date": None,
        "last_aeternus_score": None,
        "last_aeternus_rating": None,
        "last_scored_date": None,
        "last_conviction": None,
        "last_catalyst": None,
        "score_history": [],
        "current_position": None,
        "last_closed_position": None,
        "fundamentals_snapshot": None,
        "fundamentals_fetched_at": None,
        "earnings_date_next": None,
        "outcome_weight": 1.0,
        "outcome_stats": None,
        "cluster_strength": 0.0,
        "cluster_avg_emergence": 0.0,
        "cluster_rising_count": 0,
        "cluster_total_nodes": 0,
        "cluster_last_computed": None,
        "cluster_candidate": False,
        "cluster_theme_name": None,
        "cluster_theme_hypothesis": None,
        "cluster_theme_named_at": None,
        "cluster_theme_strength_at_naming": 0.0,
        "cluster_theme_is_coincidence": None,
        "cluster_theme_confidence": None,
        "cluster_theme_missing_players": None,
        "perplexity_enrichment": None,
        "perplexity_enriched_at": None,
        "market_ignorance_score_real": None,
        "analyst_count": None,
        "institutional_pct": None,
        "market_ignorance_cached_at": None,
        "breakout_score": None,
        "breakout_near_high": None,
        "breakout_vol_ratio": None,
        "breakout_last_updated": None,
        "iv_implied_move_pct": None,
        "iv_historical_move_pct": None,
        "iv_divergence": None,
        "iv_signal": None,
        "iv_earnings_date": None,
        "iv_scanned_at": None,
        "asset_class": None,
        "sector_gics": None,
        "aliases": [],
        "liquidity_score": None,
        "liquidity_cached_at": None,
        "signal_sec_catalyst_score": None,
        "signal_sec_catalyst_direction": None,
        "signal_sec_catalyst_updated": None,
        "signal_insider_score": None,
        "signal_insider_buyer_count": None,
        "signal_insider_updated": None,
        "signal_smart_money_score": None,
        "signal_smart_money_direction": None,
        "signal_smart_money_updated": None,
        "signal_momentum_score": None,
        "signal_momentum_rs_spy": None,
        "signal_momentum_updated": None,
        "signal_sector_rotation_score": None,
        "signal_sector_rotation_updated": None,
        "signal_social_score": None,
        "signal_news_catalyst_score": None,
        "signal_social_news_updated": None,
        "signal_value_score": None,
        "signal_value_updated": None,
        "signal_macro_score": None,
        "signal_macro_regime_tag": None,
        "signal_macro_updated": None,
    }


def edge_template(source: str, target: str, relationship: str,
                  confidence: float, evidence_source: str) -> dict:
    return {
        "source": source,
        "target": target,
        "relationship": relationship,
        "weight": round(min(1.0, max(0.0, confidence)), 6),
        "evidence_count": 1,
        "last_confirmed": dt.date.today().isoformat(),
        "evidence_sources": [evidence_source],
    }


def clamp_float(value, lo: float = 0.0, hi: float = 100.0) -> float:
    try:
        v = float(value)
    except Exception:
        v = lo
    return max(lo, min(hi, v))


def sanitize_filename(name: str) -> str:
    for ch in r"/\:":
        name = str(name).replace(ch, "_")
    return name
