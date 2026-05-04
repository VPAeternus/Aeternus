import json


def test_retrieve_scenario_context_matches_event_cards_and_reports_partial(tmp_path, monkeypatch):
    from tradingagents.dealflow.scenario_retriever import retrieve_scenario_context

    monkeypatch.chdir(tmp_path)
    base = tmp_path / "eval_results" / "deal_flow" / "2026-03-15"
    base.mkdir(parents=True, exist_ok=True)
    (base / "event_cards.json").write_text(
        json.dumps(
            [
                {
                    "event_card_id": "evt_iran",
                    "date": "2026-03-15",
                    "title": "Iran escalation drives oil cluster",
                    "summary": "Oil up, airlines down",
                    "event_type": "geopolitical_supply_shock",
                    "source_bundle": ["x_feed", "macro"],
                    "direct_entities": [{"entity_type": "ticker", "entity_id": "XLE", "label": "XLE"}],
                    "second_order_entities": [{"entity_type": "ticker", "entity_id": "UAL", "label": "UAL"}],
                    "expected_direction": {"XLE": "up", "UAL": "down"},
                    "matched_holdings": ["XLE"],
                    "matched_universe_symbols": ["XLE", "UAL", "SPY"],
                    "missing_dimensions": ["portfolio"],
                    "channels": ["oil", "risk_off"],
                }
            ]
        )
    )
    (base / "coverage_precheck.json").write_text(
        json.dumps(
            {
                "date": "2026-03-15",
                "rows": [
                    {
                        "event_card_id": "evt_iran",
                        "coverage_status": "PARTIAL",
                        "coverage_score": 0.62,
                        "missing_dimensions": ["portfolio"],
                        "ready_for_retrieval": True,
                    }
                ],
            }
        )
    )
    (base / "universe_filter.json").write_text(json.dumps({"symbols": ["XLE", "UAL", "SPY"]}))

    result = retrieve_scenario_context(
        question="Trump announced war on Iran. How does it affect XLE and should we hedge with SPY?",
        as_of_date="2026-03-15",
        base_dir=tmp_path / "eval_results" / "deal_flow",
    )

    assert result["coverage_status"] == "PARTIAL"
    assert result["matched_event_cards"] == ["evt_iran"]
    assert "XLE" in result["matched_entities"]
    assert any(item["entity"] == "XLE" for item in result["direct_impacts"])
    assert any(item["entity"] == "SPY" for item in result["hedge_candidates"])
    assert result["wait_for_user"] is True
    assert "portfolio" in " ".join(result["missing_inputs"]).lower()


def test_retrieve_scenario_context_returns_missing_without_internal_match(tmp_path, monkeypatch):
    from tradingagents.dealflow.scenario_retriever import retrieve_scenario_context

    monkeypatch.chdir(tmp_path)
    base = tmp_path / "eval_results" / "deal_flow" / "2026-03-15"
    base.mkdir(parents=True, exist_ok=True)
    (base / "event_cards.json").write_text("[]")
    (base / "coverage_precheck.json").write_text(json.dumps({"date": "2026-03-15", "rows": []}))

    result = retrieve_scenario_context(
        question="What does a new SEC filing from SNDK imply for AI compute beneficiaries?",
        as_of_date="2026-03-15",
        base_dir=tmp_path / "eval_results" / "deal_flow",
    )

    assert result["coverage_status"] == "MISSING"
    assert result["matched_event_cards"] == []
    assert result["wait_for_user"] is True
    assert result["recommended_manual_gap_fill"]


def test_retrieve_scenario_context_limits_broad_daily_query_to_top_ranked_cards(tmp_path, monkeypatch):
    from tradingagents.dealflow.scenario_retriever import retrieve_scenario_context

    monkeypatch.chdir(tmp_path)
    base = tmp_path / "eval_results" / "deal_flow" / "2026-03-15"
    base.mkdir(parents=True, exist_ok=True)
    event_cards = []
    coverage_rows = []
    for idx in range(7):
        event_cards.append(
            {
                "event_card_id": f"evt_{idx}",
                "date": "2026-03-15",
                "title": f"Scenario {idx}",
                "summary": f"Daily scenario sourced from x_feed {idx}",
                "event_type": "options_flow_signal" if idx == 0 else "breakout_cluster",
                "source_bundle": ["x_feed", "macro"] if idx == 0 else ["x_feed"],
                "direct_entities": [{"entity_type": "ticker", "entity_id": f"T{idx}", "label": f"T{idx}"}],
                "second_order_entities": [],
                "expected_direction": {f"T{idx}": "up"},
                "matched_holdings": [],
                "matched_universe_symbols": [f"T{idx}"],
                "missing_dimensions": [],
                "channels": ["options_flow", "risk_off"] if idx == 0 else ["breakout"],
                "confidence": 0.95 - (idx * 0.05),
                "portfolio_relevance": "high" if idx == 0 else "low",
            }
        )
        coverage_rows.append(
            {
                "event_card_id": f"evt_{idx}",
                "coverage_status": "COMPLETE",
                "coverage_score": 0.9 - (idx * 0.05),
                "missing_dimensions": [],
                "ready_for_retrieval": True,
            }
        )

    (base / "event_cards.json").write_text(json.dumps(event_cards))
    (base / "coverage_precheck.json").write_text(json.dumps({"date": "2026-03-15", "rows": coverage_rows}))
    (base / "universe_filter.json").write_text(json.dumps({"symbols": [f"T{idx}" for idx in range(7)]}))

    result = retrieve_scenario_context(
        question="What are today's most important daily scenarios?",
        as_of_date="2026-03-15",
        base_dir=tmp_path / "eval_results" / "deal_flow",
    )

    assert result["coverage_status"] == "COMPLETE"
    assert len(result["matched_event_cards"]) == 5
    assert result["matched_event_cards"][0] == "evt_0"
