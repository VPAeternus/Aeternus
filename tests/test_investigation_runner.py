from __future__ import annotations

import json


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_run_investigation_loads_artifacts_and_detects_shortlist_miss(tmp_path, monkeypatch):
    from tradingagents.dealflow.investigation_runner import run_investigation

    monkeypatch.chdir(tmp_path)
    base = tmp_path / "eval_results" / "deal_flow" / "2026-03-17"

    _write_json(
        base / "event_cards.json",
        [
            {
                "event_card_id": "evt_mu_1",
                "direct_entities": [{"entity_id": "MU"}],
                "second_order_entities": [],
            }
        ],
    )
    _write_json(base / "coverage_precheck.json", {"rows": [{"event_card_id": "evt_mu_1", "coverage_status": "PARTIAL"}]})
    _write_json(base / "universe_filter.json", {"symbols": ["MU", "NVDA"]})
    _write_json(base / "all_scored_candidates.json", [{"symbol": "MU", "status": "ACTIVE"}])
    _write_json(base / "shortlist_top20.json", {"candidates": [{"symbol": "NVDA"}]})
    _write_json(base / "research_queue.json", {"items": [{"symbol": "NVDA", "selected_for_deep": True}]})
    _write_json(base / "scout_audit.json", {"signals": [{"symbol": "MU"}]})
    _write_json(base / "discovery_delta.json", {"symbol_records": [{"symbol": "MU"}]})

    packet = {
        "query_type": "reverse_forensic",
        "intent": "missed_alpha_diagnosis",
        "target_entities": ["MU"],
    }
    result = run_investigation(
        investigation_packet=packet,
        as_of_date="2026-03-17",
        base_dir=tmp_path / "eval_results" / "deal_flow",
    )

    assert result["first_miss_stage"] == "shortlist"
    stages = {row["stage"]: row["status"] for row in result["stage_diagnosis"]}
    assert stages["scouts"] == "FOUND"
    assert stages["event_cards"] == "FOUND"
    assert stages["universe_filter"] == "FOUND"
    assert stages["collect"] == "FOUND"
    assert stages["shortlist"] == "MISS"
    assert result["matched_event_cards"] == ["evt_mu_1"]
    shortlist_row = next(row for row in result["stage_diagnosis"] if row["stage"] == "shortlist")
    assert shortlist_row["reason_code"]
    assert "threshold" in shortlist_row
    assert "observed_value" in shortlist_row


def test_run_investigation_marks_missing_when_ticker_never_appears(tmp_path, monkeypatch):
    from tradingagents.dealflow.investigation_runner import run_investigation

    monkeypatch.chdir(tmp_path)
    base = tmp_path / "eval_results" / "deal_flow" / "2026-03-17"
    _write_json(base / "event_cards.json", [])
    _write_json(base / "coverage_precheck.json", {"rows": []})
    _write_json(base / "universe_filter.json", {"symbols": ["NVDA"]})
    _write_json(base / "all_scored_candidates.json", [{"symbol": "NVDA"}])
    _write_json(base / "shortlist_top20.json", {"candidates": [{"symbol": "NVDA"}]})
    _write_json(base / "research_queue.json", {"items": [{"symbol": "NVDA", "selected_for_deep": True}]})
    _write_json(base / "scout_audit.json", {"signals": [{"symbol": "NVDA"}]})
    _write_json(base / "discovery_delta.json", {"symbol_records": [{"symbol": "NVDA"}]})

    packet = {
        "query_type": "reverse_forensic",
        "intent": "missed_alpha_diagnosis",
        "target_entities": ["MU"],
    }
    result = run_investigation(
        investigation_packet=packet,
        as_of_date="2026-03-17",
        base_dir=tmp_path / "eval_results" / "deal_flow",
    )

    assert result["first_miss_stage"] == "scouts"
    stages = {row["stage"]: row["status"] for row in result["stage_diagnosis"]}
    assert stages["scouts"] == "MISS"
    assert all(status == "MISS" for status in stages.values())
    scouts_row = next(row for row in result["stage_diagnosis"] if row["stage"] == "scouts")
    assert scouts_row["reason_code"] == "SCOUT_SIGNAL_ABSENT"
    assert scouts_row["delta_to_pass"] == 1


def test_run_investigation_prefers_earliest_stage_miss_ordering(tmp_path, monkeypatch):
    from tradingagents.dealflow.investigation_runner import run_investigation

    monkeypatch.chdir(tmp_path)
    base = tmp_path / "eval_results" / "deal_flow" / "2026-03-17"
    _write_json(base / "event_cards.json", [{"event_card_id": "evt_mu", "direct_entities": [{"entity_id": "MU"}], "second_order_entities": []}])
    _write_json(base / "coverage_precheck.json", {"rows": [{"event_card_id": "evt_mu", "coverage_status": "COMPLETE"}]})
    _write_json(base / "universe_filter.json", {"symbols": ["NVDA"]})
    _write_json(base / "all_scored_candidates.json", [{"symbol": "MU"}])
    _write_json(base / "shortlist_top20.json", {"candidates": [{"symbol": "MU"}]})
    _write_json(base / "research_queue.json", {"items": [{"symbol": "MU", "selected_for_deep": True}]})
    _write_json(base / "scout_audit.json", {"signals": [{"symbol": "MU"}]})
    _write_json(base / "discovery_delta.json", {"symbol_records": [{"symbol": "MU"}]})

    packet = {
        "query_type": "reverse_forensic",
        "intent": "missed_alpha_diagnosis",
        "target_entities": ["MU"],
    }
    result = run_investigation(
        investigation_packet=packet,
        as_of_date="2026-03-17",
        base_dir=tmp_path / "eval_results" / "deal_flow",
    )

    assert result["first_miss_stage"] == "universe_filter"
    ordered = [row["stage"] for row in result["stage_diagnosis"]]
    assert ordered == ["scouts", "event_cards", "universe_filter", "collect", "shortlist", "deep_selection"]


def test_run_investigation_uses_hypothesis_ledger_drop_for_universe_reason(tmp_path, monkeypatch):
    from tradingagents.dealflow.hypothesis_ledger import append_ledger_row, make_ledger_row
    from tradingagents.dealflow.investigation_runner import run_investigation

    monkeypatch.chdir(tmp_path)
    base = tmp_path / "eval_results" / "deal_flow" / "2026-03-17"
    _write_json(base / "event_cards.json", [{"event_card_id": "evt_mu", "direct_entities": [{"entity_id": "MU"}], "second_order_entities": []}])
    _write_json(base / "coverage_precheck.json", {"rows": [{"event_card_id": "evt_mu", "coverage_status": "COMPLETE"}]})
    _write_json(base / "universe_filter.json", {"symbols": ["NVDA"], "rule_snapshot": {"filter_enabled": True}})
    _write_json(base / "all_scored_candidates.json", [])
    _write_json(base / "shortlist_top20.json", {"candidates": []})
    _write_json(base / "research_queue.json", {"items": []})
    _write_json(base / "scout_audit.json", {"signals": [{"symbol": "MU"}]})
    _write_json(base / "discovery_delta.json", {"symbol_records": [{"symbol": "MU"}]})

    ledger_row = make_ledger_row(
        run_id="run-1",
        source_date="2026-03-17",
        lane="shared",
        stage_id="universe_gate_haystack",
        rule_snapshot={"filter_enabled": True, "haystack_drop_count": 42},
        kept_symbols=["NVDA"],
        dropped_symbols=["MU"],
        base_dir=base,
    )
    append_ledger_row(base_dir=base, lane="shared", row=ledger_row)

    packet = {
        "query_type": "reverse_forensic",
        "intent": "missed_alpha_diagnosis",
        "target_entities": ["MU"],
    }
    result = run_investigation(
        investigation_packet=packet,
        as_of_date="2026-03-17",
        base_dir=tmp_path / "eval_results" / "deal_flow",
    )

    universe_row = next(row for row in result["stage_diagnosis"] if row["stage"] == "universe_filter")
    assert universe_row["status"] == "MISS"
    assert universe_row["reason_code"] == "UNIVERSE_GATE_HAYSTACK_DROPPED"
    assert universe_row["threshold"]["filter_enabled"] is True


def test_run_investigation_prefers_drop_metadata_reason_payload(tmp_path, monkeypatch):
    from tradingagents.dealflow.hypothesis_ledger import append_ledger_row, make_ledger_row
    from tradingagents.dealflow.investigation_runner import run_investigation

    monkeypatch.chdir(tmp_path)
    base = tmp_path / "eval_results" / "deal_flow" / "2026-03-17"
    _write_json(base / "event_cards.json", [{"event_card_id": "evt_mu", "direct_entities": [{"entity_id": "MU"}], "second_order_entities": []}])
    _write_json(base / "coverage_precheck.json", {"rows": [{"event_card_id": "evt_mu", "coverage_status": "COMPLETE"}]})
    _write_json(base / "universe_filter.json", {"symbols": ["NVDA"]})
    _write_json(base / "all_scored_candidates.json", [])
    _write_json(base / "shortlist_top20.json", {"candidates": []})
    _write_json(base / "research_queue.json", {"items": []})
    _write_json(base / "scout_audit.json", {"signals": [{"symbol": "MU"}]})
    _write_json(base / "discovery_delta.json", {"symbol_records": [{"symbol": "MU"}]})

    ledger_row = make_ledger_row(
        run_id="run-2",
        source_date="2026-03-17",
        lane="shared",
        stage_id="universe_gate_haystack",
        rule_snapshot={"filter_enabled": True},
        kept_symbols=["NVDA"],
        dropped_symbols=["MU"],
        base_dir=base,
        drop_metadata_by_symbol={
            "MU": {
                "reason_code": "UNIVERSE_NOT_IN_ACTIVE_TIERS",
                "reason_text": "Symbol was not mapped into active universe tiers.",
                "threshold": {"required_tier_membership": True},
                "observed_value": {"in_tier_map": False},
                "delta_to_pass": 1,
            }
        },
    )
    append_ledger_row(base_dir=base, lane="shared", row=ledger_row)

    packet = {
        "query_type": "reverse_forensic",
        "intent": "missed_alpha_diagnosis",
        "target_entities": ["MU"],
    }
    result = run_investigation(
        investigation_packet=packet,
        as_of_date="2026-03-17",
        base_dir=tmp_path / "eval_results" / "deal_flow",
    )

    universe_row = next(row for row in result["stage_diagnosis"] if row["stage"] == "universe_filter")
    assert universe_row["status"] == "MISS"
    assert universe_row["reason_code"] == "UNIVERSE_NOT_IN_ACTIVE_TIERS"
    assert universe_row["threshold"]["required_tier_membership"] is True
    assert universe_row["observed_value"]["in_tier_map"] is False
