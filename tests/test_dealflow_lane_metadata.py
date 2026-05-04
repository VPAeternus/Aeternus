from tradingagents.dealflow.pipeline import DealFlowPipeline
from tradingagents.dealflow.scoring import score_candidates


def _universe_row(symbol: str):
    return {
        "symbol": symbol,
        "asset_class": "Equity",
        "sector": "Technology",
        "liquidity_score": 90.0,
        "aliases": [symbol.lower()],
    }


def _signal(symbol: str, family: str, score: float, evidence: int = 5):
    return {
        "symbol": symbol,
        "signal_family": family,
        "raw_score": score,
        "z_score": 0.0,
        "direction": "BULLISH" if score >= 60 else "BEARISH" if score <= 40 else "NEUTRAL",
        "evidence_count": evidence,
        "freshness_hours": 1.0,
        "source_status": "OK",
        "source_name": "test",
    }


def test_score_candidates_emits_phase1_lane_metadata_fields():
    universe = [_universe_row("PLTR")]
    signals = [
        _signal("PLTR", "social_momentum", 84, 6),
        _signal("PLTR", "news_catalyst", 78, 5),
        _signal("PLTR", "macro_regime_fit", 68, 5),
        _signal("PLTR", "smart_money", 74, 5),
        _signal("PLTR", "price_momentum", 88, 5),
        _signal("PLTR", "emergence", 80, 5),
    ]

    _, candidates = score_candidates(
        universe=universe,
        signals=signals,
        min_signal_families=3,
        min_evidence_count=5,
    )

    candidate = candidates[0]
    for field in (
        "upside_3m_score",
        "emergence_proxy_score",
        "narrative_ignition_score",
        "fundamentals_acceleration_score",
        "relative_strength_score",
        "lane_candidates",
    ):
        assert field in candidate
    assert candidate["lane_candidates"]


def test_build_research_queue_carries_phase1_lane_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    pipeline = DealFlowPipeline(
        config={
            "dealflow_deep_k": 1,
            "dealflow_deep_core_quota": 1,
            "dealflow_deep_momentum_quota": 0,
        }
    )
    shortlist = {
        "run_id": "2026-03-06-120000-manual",
        "date": "2026-03-06",
        "candidates": [
            {
                "symbol": "PLTR",
                "asset_class": "Equity",
                "sector": "Technology",
                "liquidity_score": 90.0,
                "subscores": {"price_momentum": 88.0, "news_catalyst": 78.0, "macro_regime_fit": 68.0},
                "deal_flow_score": 81.0,
                "core_score": 81.0,
                "momentum_score": 84.0,
                "asymmetry_score": 80.0,
                "active_families": 5,
                "evidence_count": 8,
                "freshness_hours": 1.0,
                "status": "ACTIVE",
                "risk_tags": ["Standard"],
                "trend_tags": ["theme-artificial-intelligence"],
                "lane": "MOMENTUM",
                "source": "AUTO",
                "source_detail": "AUTO_MODEL",
                "manual_note": "",
                "manual_priority": 0,
                "reason": "test",
                "upside_3m_score": 82.5,
                "emergence_proxy_score": 79.0,
                "narrative_ignition_score": 83.0,
                "fundamentals_acceleration_score": 72.0,
                "relative_strength_score": 86.0,
                "lane_candidates": ["3M_UPSIDE", "EMERGENCE"],
            }
        ],
    }

    queue = pipeline._build_research_queue(shortlist)
    item = queue["items"][0]

    assert item["upside_3m_score"] == 82.5
    assert item["emergence_proxy_score"] == 79.0
    assert item["narrative_ignition_score"] == 83.0
    assert item["fundamentals_acceleration_score"] == 72.0
    assert item["relative_strength_score"] == 86.0
    assert item["lane_candidates"] == ["3M_UPSIDE", "EMERGENCE"]
