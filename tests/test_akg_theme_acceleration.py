from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph


def test_update_theme_acceleration_signal_writes_fields_and_flags_rescan():
    g = AeternusKnowledgeGraph()
    g.update_theme_acceleration_signal("GLW", {
        "as_of_date": "2026-05-05",
        "primary_theme": "optical_networking",
        "secondary_themes": ["ai_data_center"],
        "theme_role": "infrastructure_provider",
        "theme_confidence": "high",
        "theme_driver_type": "revenue",
        "theme_momentum": "accelerating",
        "theme_evidence": ["Optical segment grew on data-center demand."],
        "theme_acceleration_score": 10,
        "theme_acceleration_reason": "filing_theme_acceleration",
    })
    node = g._nodes["GLW"]
    assert node["primary_theme"] == "optical_networking"
    assert node["secondary_themes"] == ["ai_data_center"]
    assert node["theme_role"] == "infrastructure_provider"
    assert node["theme_confidence"] == "high"
    assert node["theme_evidence"] == ["Optical segment grew on data-center demand."]
    assert node["signal_theme_acceleration_score"] == 10
    assert node["signal_theme_acceleration_updated"] == "2026-05-05"
    assert node["theme_acceleration_rescan_flag"] is True
    assert node["theme_acceleration_research_visibility"] is True


def test_theme_acceleration_research_visibility_requires_score_and_confidence():
    g = AeternusKnowledgeGraph()
    g.update_theme_acceleration_signal("LOW", {
        "as_of_date": "2026-05-05",
        "theme_confidence": "low",
        "theme_acceleration_score": 12,
        "theme_evidence": ["evidence"],
    })
    g.update_theme_acceleration_signal("MED", {
        "as_of_date": "2026-05-05",
        "theme_confidence": "medium",
        "theme_acceleration_score": 10,
        "theme_evidence": ["evidence"],
    })
    g.update_theme_acceleration_signal("SMALL", {
        "as_of_date": "2026-05-05",
        "theme_confidence": "high",
        "theme_acceleration_score": 8,
        "theme_evidence": ["evidence"],
    })
    assert g._nodes["LOW"]["theme_acceleration_rescan_flag"] is True
    assert g._nodes["LOW"]["theme_acceleration_research_visibility"] is False
    assert g._nodes["MED"]["theme_acceleration_research_visibility"] is True
    assert g._nodes["SMALL"]["theme_acceleration_rescan_flag"] is True
    assert g._nodes["SMALL"]["theme_acceleration_research_visibility"] is False


def test_update_theme_acceleration_requires_evidence_for_score():
    g = AeternusKnowledgeGraph()
    g.update_theme_acceleration_signal("GLW", {"as_of_date": "2026-05-05", "theme_acceleration_score": 10, "theme_evidence": []})
    node = g._nodes["GLW"]
    assert node["signal_theme_acceleration_score"] == 0
    assert node["theme_acceleration_rescan_flag"] is not True


def test_get_theme_acceleration_candidates_is_point_in_time():
    g = AeternusKnowledgeGraph()
    g.update_theme_acceleration_signal("OLD", {"as_of_date": "2026-05-01", "theme_acceleration_score": 5, "theme_evidence": ["e"]})
    g.update_theme_acceleration_signal("NEW", {"as_of_date": "2026-05-10", "theme_acceleration_score": 12, "theme_evidence": ["e"]})
    assert [n["id"] for n in g.get_theme_acceleration_candidates("2026-05-05")] == ["OLD"]
    assert [n["id"] for n in g.get_theme_acceleration_candidates("2026-05-10")] == ["NEW", "OLD"]
