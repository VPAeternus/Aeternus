import json

from tradingagents.dealflow.research_queue_builder import (
    build_deep_selection_drop_metadata,
    build_research_queue,
    ensure_manual_deep_selection,
    inject_force_queue_candidates,
    inject_held_positions,
    select_for_deep,
)


def _item(symbol, lane="CORE", score=50, source="AUTO"):
    return {"queue_id": f"r:{symbol}", "symbol": symbol, "lane": lane, "triage_score": score, "source": source, "asset_class": "Equity"}


def _candidate(symbol, lane="CORE", triage=50, source="AUTO"):
    return {
        "symbol": symbol,
        "asset_class": "Equity",
        "sector": "Tech",
        "lane": lane,
        "deal_flow_score": triage,
        "core_score": triage,
        "momentum_score": triage,
        "asymmetry_score": triage,
        "upside_3m_score": 0,
        "emergence_proxy_score": 0,
        "narrative_ignition_score": 0,
        "fundamentals_acceleration_score": 0,
        "relative_strength_score": 0,
        "lane_candidates": [],
        "subscores": {},
        "trend_tags": [],
        "risk_tags": [],
        "active_families": 1,
        "evidence_count": 1,
        "freshness_hours": 1,
        "source": source,
        "source_detail": "TEST",
        "manual_note": "",
    }


def test_select_for_deep_preserves_core_momentum_quota_and_fallback_order():
    items = [_item("C1", "CORE", 90), _item("C2", "CORE", 80), _item("M1", "MOMENTUM", 95), _item("M2", "MOMENTUM", 70)]
    assert select_for_deep(items, deep_k=3, core_quota=1, momentum_quota=1) == ["r:C1", "r:M1", "r:C2"]


def test_manual_deep_selection_displaces_lowest_non_manual():
    items = [_item("AUTO1", score=90), _item("AUTO2", score=10), _item("MAN", score=50, source="MANUAL")]
    assert ensure_manual_deep_selection(items, selected_ids=["r:AUTO1", "r:AUTO2"], deep_k=2) == ["r:AUTO1", "r:MAN"]


def test_force_queue_uses_reserve_quota_without_displacing_autos():
    items = [_item("AUTO1", score=90)]
    new_items, selected = inject_force_queue_candidates(
        items=items,
        selected_ids=["r:AUTO1"],
        deep_k=1,
        reserve_quota=1,
        run_id="r",
        force_queue=[{"symbol": "FORCE", "reason": "iv"}],
        synthesize_candidate=lambda symbol, lane: _candidate(symbol),
        normalize_sector=lambda raw: str(raw),
    )
    assert selected == ["r:AUTO1", "r:FORCE"]
    assert {i["symbol"] for i in new_items} == {"AUTO1", "FORCE"}


def test_held_positions_append_and_skip_etf_symbols(tmp_path):
    positions = tmp_path / "positions.json"
    positions.write_text(json.dumps({"open_positions": {"GLW": {}, "QQQ": {}}}))
    items, selected = inject_held_positions(
        items=[],
        selected_ids=[],
        run_id="r",
        positions_path=positions,
        synthesize_candidate=lambda symbol, lane: _candidate(symbol, triage=50),
        normalize_sector=lambda raw: str(raw),
    )
    assert selected == ["r:GLW"]
    assert [i["symbol"] for i in items] == ["GLW"]


def test_build_research_queue_suppressed_candidates_not_selected_and_metadata_marks_suppression(tmp_path):
    shortlist = {"run_id": "r", "date": "2026-05-05", "candidates": [_candidate("BLOCK", triage=99), _candidate("OK", triage=50)]}
    queue = build_research_queue(
        shortlist=shortlist,
        config={"dealflow_deep_k": 2, "dealflow_deep_core_quota": 2, "dealflow_deep_momentum_quota": 0},
        ledger_base_dir=tmp_path,
        suppressor=lambda symbol, thesis_tags, config: (symbol == "BLOCK", {"constraint_id": "no-optical"}),
    )
    selected = set(queue["selected_queue_ids"])
    assert "r:BLOCK" not in selected
    assert "r:OK" in selected
    assert queue["source_artifact"] == "eval_results/deal_flow/2026-05-05/shortlist_top20.json"
    assert queue["canonical_sector_map"] == {"BLOCK": "Tech", "OK": "Tech"}
    meta = build_deep_selection_drop_metadata(
        items=queue["items"],
        selected_id_set=selected,
        suppressed_queue_ids={"r:BLOCK"},
        deep_selection_rule_snapshot={"final_deep_k": 2},
    )
    assert meta["BLOCK"]["reason_code"] == "NEGATIVE_CONSTRAINT_SUPPRESSED"


def test_build_research_queue_appends_deep_selection_ledger_metadata(tmp_path):
    shortlist = {"run_id": "r", "date": "2026-05-05", "candidates": [_candidate("A", triage=90), _candidate("B", triage=10)]}
    queue = build_research_queue(
        shortlist=shortlist,
        config={"dealflow_deep_k": 1, "dealflow_deep_core_quota": 1, "dealflow_deep_momentum_quota": 0},
        ledger_base_dir=tmp_path,
    )
    rows = json.loads((tmp_path / "hypothesis_ledger" / "shared" / "rows.json").read_text())
    assert rows[-1]["stage_id"] == "deep_selection_cut"
    assert rows[-1]["kept_count"] == 1
    assert rows[-1]["dropped_count"] == 1
    meta = json.loads(open(rows[-1]["dropped_symbols_metadata_path"]).read())
    assert meta["B"]["reason_code"] in {"TRIAGE_RANK_BELOW_DEEP_CUT", "DEEP_SELECTION_POLICY_EXCLUSION"}
    assert queue["selected_queue_ids"] == ["r:A"]
