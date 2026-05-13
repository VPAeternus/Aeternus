import csv
import json

from tradingagents.research.fundamental.src.daily_run.models import DailyRunConfig, GateStatus
from tradingagents.research.fundamental.src.daily_run.orchestrator import run_daily_fundamental
from tradingagents.research.fundamental.src.daily_run.universe import build_combined_universe


def test_master_universe_accepts_json_items_contract(tmp_path):
    master = tmp_path / "master.json"
    master.write_text(json.dumps({"items": [{"symbol": "abc", "cik": "1", "company_title": "ABC Inc"}]}), encoding="utf-8")
    out = tmp_path / "universe.csv"

    result = build_combined_universe(master_universe_path=master, handoff_path=None, quarter="2026Q2", output_csv=out)

    assert result.rows[0]["ticker"] == "ABC"
    assert result.rows[0]["quarter"] == "2026Q2"
    assert result.rows[0]["master_universe_source"] == "master.json"
    assert out.exists()


def test_master_universe_accepts_json_list_contract(tmp_path):
    master = tmp_path / "master.json"
    master.write_text(json.dumps([{"ticker": "BRK.B", "cik": "2", "title": "Berkshire"}]), encoding="utf-8")

    result = build_combined_universe(master_universe_path=master, handoff_path=None, quarter="2026Q2", output_csv=tmp_path / "out.csv")

    assert result.rows[0]["ticker"] == "BRK-B"
    assert result.rows[0]["company_title"] == "Berkshire"


def test_master_universe_accepts_csv_compatibility_contract(tmp_path):
    master = tmp_path / "master.csv"
    with master.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "cik", "company_title", "cik_status"])
        writer.writeheader()
        writer.writerow({"ticker": "xyz", "cik": "3", "company_title": "XYZ Inc", "cik_status": "resolved"})

    result = build_combined_universe(master_universe_path=master, handoff_path=None, quarter="2026Q2", output_csv=tmp_path / "out.csv")

    assert result.rows[0]["ticker"] == "XYZ"
    assert result.rows[0]["cik"] == "3"
    assert result.rows[0]["master_universe_source"] == "master.csv"


def test_master_universe_rejects_unsupported_extension(tmp_path):
    master = tmp_path / "master.txt"
    master.write_text("AAA", encoding="utf-8")

    try:
        build_combined_universe(master_universe_path=master, handoff_path=None, quarter="2026Q2", output_csv=tmp_path / "out.csv")
    except ValueError as exc:
        assert "JSON" in str(exc)
        assert "CSV" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_master_universe_rejects_csv_without_cik(tmp_path):
    master = tmp_path / "master.csv"
    master.write_text("ticker,company_title\nAAA,AAA Inc\n", encoding="utf-8")

    try:
        build_combined_universe(master_universe_path=master, handoff_path=None, quarter="2026Q2", output_csv=tmp_path / "out.csv")
    except ValueError as exc:
        assert "cik column" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_orchestrator_hard_stops_with_clear_invalid_master_format(tmp_path):
    master = tmp_path / "master.csv"
    master.write_text("company_title\nNo ticker\n", encoding="utf-8")
    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="diagnostic-only",
        output_root=tmp_path / "run",
        master_universe_path=master,
        skip_fetch=True,
        skip_llm=True,
        min_broad_universe_count=1,
    )

    result = run_daily_fundamental(cfg)

    assert result.summary["final"] is False
    assert result.gates[-1].gate_number == 2
    assert result.gates[-1].status == GateStatus.HARD_STOP
    assert result.gates[-1].summary["reason"] == "invalid_master_universe_format"
    assert "ticker or symbol" in result.gates[-1].summary["error"]
