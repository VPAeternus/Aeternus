from tradingagents.dealflow.manual_merge_policy import apply_manual_merge_policy


def _candidate(symbol, score=80, sector="Tech", source="AUTO"):
    return {"symbol": symbol, "core_score": score, "deal_flow_score": score, "momentum_score": score, "asymmetry_score": score, "freshness_hours": 1, "sector": sector, "asset_class": "Equity", "source": source, "status": "ACTIVE", "risk_tags": [], "lane": "CORE"}


def test_manual_merge_reinforces_existing_auto_symbol():
    shortlist, summary = apply_manual_merge_policy(
        ranked_auto=[_candidate("GLW", 90)],
        candidates=[_candidate("GLW", 90)],
        manual_ideas=[{"symbol": "GLW", "priority": 5, "note": "watch", "lane_preference": "CORE"}],
        top_k=1,
    )
    assert shortlist[0]["source_detail"] == "MANUAL_REINFORCED"
    assert "Manual reinforced" in shortlist[0]["risk_tags"]
    assert summary["reinforced"] == 1


def test_manual_merge_synthesizes_missing_candidate_and_ranks_deterministically():
    shortlist, summary = apply_manual_merge_policy(
        ranked_auto=[_candidate("AUTO", 10)],
        candidates=[],
        manual_ideas=[{"symbol": "GLW", "priority": 5, "note": "manual", "lane_preference": "CORE"}],
        top_k=1,
        synthesize_manual_candidate=lambda symbol, lane: {**_candidate(symbol, 50), "risk_tags": ["Manual override (no auto coverage)"]},
    )
    assert shortlist[0]["symbol"] == "GLW"
    assert shortlist[0]["rank"] == 1
    assert summary["included"] == 1


def test_manual_merge_liquidity_rejects_when_force_insert_disabled():
    shortlist, summary = apply_manual_merge_policy(
        ranked_auto=[_candidate("AUTO", 10)],
        candidates=[_candidate("GLW", 80)],
        manual_ideas=[{"symbol": "GLW", "priority": 5, "lane_preference": "CORE"}],
        top_k=1,
        config={"dealflow_manual_force_insert": False},
        validate_liquidity=lambda symbol, min_adv_usd: (False, 0.0),
    )
    assert shortlist[0]["symbol"] == "AUTO"
    assert summary["rejected"] == 1
    assert "Liquidity gate failed" in summary["decisions"][0]["reason"]


def test_manual_merge_cap_override_tags_when_force_insert_enabled():
    shortlist, summary = apply_manual_merge_policy(
        ranked_auto=[_candidate("AUTO", 10, sector="Same")],
        candidates=[_candidate("GLW", 80, sector="Same")],
        manual_ideas=[{"symbol": "GLW", "priority": 5, "lane_preference": "CORE"}],
        top_k=1,
        config={"dealflow_manual_force_insert": True, "dealflow_max_sector_count": 0},
    )
    assert shortlist[0]["symbol"] == "GLW"
    assert "Manual cap override" in shortlist[0]["risk_tags"]
    assert summary["included"] == 1
