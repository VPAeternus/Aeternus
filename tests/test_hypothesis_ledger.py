from pathlib import Path
import json

from tradingagents.dealflow.hypothesis_ledger import (
    build_stage_snapshot_paths,
    make_ledger_row,
)


def test_build_stage_snapshot_paths_are_deterministic(tmp_path: Path):
    kept_path, dropped_path = build_stage_snapshot_paths(
        base_dir=tmp_path,
        lane="shared",
        stage_id="scout_handoff",
    )

    assert kept_path == tmp_path / "hypothesis_ledger" / "shared" / "scout_handoff.kept.json"
    assert dropped_path == tmp_path / "hypothesis_ledger" / "shared" / "scout_handoff.dropped.json"


def test_make_ledger_row_sets_counts_and_writes_snapshots(tmp_path: Path):
    row = make_ledger_row(
        run_id="2026-03-06-123000-manual",
        source_date="2026-03-06",
        lane="shared",
        stage_id="scout_handoff",
        rule_snapshot={"top_k": 30},
        kept_symbols=["AAPL", "NVDA"],
        dropped_symbols=["MU"],
        base_dir=tmp_path,
        drop_metadata_by_symbol={
            "MU": {
                "reason_code": "RANK_BELOW_SHORTLIST_CUT",
                "reason_text": "Rank was below top_k.",
                "threshold": {"top_k": 30},
                "observed_value": {"rank": 31},
                "delta_to_pass": 1,
            }
        },
    )

    assert row["run_id"] == "2026-03-06-123000-manual"
    assert row["source_date"] == "2026-03-06"
    assert row["lane"] == "shared"
    assert row["stage_id"] == "scout_handoff"
    assert row["input_count"] == 3
    assert row["kept_count"] == 2
    assert row["dropped_count"] == 1

    kept_path = Path(row["kept_symbols_path"])
    dropped_path = Path(row["dropped_symbols_path"])
    dropped_metadata_path = Path(row["dropped_symbols_metadata_path"])
    assert json.loads(kept_path.read_text()) == ["AAPL", "NVDA"]
    assert json.loads(dropped_path.read_text()) == ["MU"]
    assert json.loads(dropped_metadata_path.read_text())["MU"]["reason_code"] == "RANK_BELOW_SHORTLIST_CUT"
