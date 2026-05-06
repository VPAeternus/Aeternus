import json

from tradingagents.dealflow.collect_ledger import write_collect_ledger_rows
from tradingagents.dealflow.hypothesis_ledger import ledger_rows_path


def test_write_collect_ledger_rows_preserves_stage_order_metadata_and_manual_summary(tmp_path):
    universe_ledger = {
        "candidate_drop_symbols": ["AAA"],
        "haystack_drop_symbols": ["BBB"],
        "kept_symbols": ["GLW"],
        "rule_snapshot": {"min_liquidity": 30},
        "drop_metadata_by_symbol": {"AAA": {"reason": "edge"}, "BBB": {"reason": "haystack"}},
    }
    all_scored = [
        {"symbol": "GLW", "status": "ACTIVE", "active_families": ["x"], "evidence_count": 5},
        {"symbol": "LOW", "status": "LOW_DATA", "active_families": ["social"], "evidence_count": 1},
        {"symbol": "DROP", "status": "ACTIVE", "active_families": ["x"], "evidence_count": 5, "momentum_score": 1},
    ]
    shortlist = {
        "run_id": "r1",
        "date": "2026-05-05",
        "top_k": 1,
        "manual_merge_summary": {"inserted": 1},
        "candidates": [{"symbol": "GLW", "momentum_score": 90}],
    }

    rows = write_collect_ledger_rows(
        base_dir=tmp_path,
        as_of_date="2026-05-05",
        shortlist=shortlist,
        all_scored_candidates=all_scored,
        universe_ledger=universe_ledger,
        min_signal_families=3,
        min_evidence_count=5,
    )

    assert [row["stage_id"] for row in rows] == ["universe_gate_edge", "universe_gate_haystack", "evidence_gate", "shortlist_cut"]
    assert rows[0]["dropped_count"] == 1
    assert rows[1]["dropped_count"] == 1
    assert json.loads(rows[2]["dropped_symbols_path"].read_text() if hasattr(rows[2]["dropped_symbols_path"], "read_text") else open(rows[2]["dropped_symbols_path"]).read()) == ["LOW"]
    evidence_meta = json.loads(open(rows[2]["dropped_symbols_metadata_path"]).read())
    assert evidence_meta["LOW"]["observed_value"]["active_families"] == 1
    assert rows[3]["rule_snapshot"]["manual_merge_summary"] == {"inserted": 1}
    persisted = json.loads(ledger_rows_path(base_dir=tmp_path, lane="shared").read_text())
    assert [row["stage_id"] for row in persisted] == ["universe_gate_edge", "universe_gate_haystack", "evidence_gate", "shortlist_cut"]


def test_write_collect_ledger_rows_handles_empty_universe_and_drops(tmp_path):
    rows = write_collect_ledger_rows(
        base_dir=tmp_path,
        as_of_date="2026-05-05",
        shortlist={"run_id": "r1", "date": "2026-05-05", "top_k": 0, "candidates": []},
        all_scored_candidates=[],
        universe_ledger={},
        min_signal_families=3,
        min_evidence_count=5,
    )

    assert len(rows) == 4
    assert all(row["lane"] == "shared" for row in rows)
    assert json.loads(open(rows[0]["kept_symbols_path"]).read()) == []
    assert rows[3]["rule_snapshot"]["manual_merge_summary"] == {}
