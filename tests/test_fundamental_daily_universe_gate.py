import json
from tradingagents.research.fundamental.src.daily_run.models import GateStatus, RunMode
from tradingagents.research.fundamental.src.daily_run.universe import build_combined_universe, validate_universe_gate


def _write_master_json(path):
    path.write_text(json.dumps({"items": [{"symbol": "AAA", "cik": "1", "company_title": "AAA Inc"}, {"symbol": "BBB", "cik": "2", "company_title": "BBB Inc"}, {"symbol": "CCC", "cik": "3", "company_title": "CCC Inc"}]}))


def _write_handoff(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"source_stage": "scout_ticker_summary", "tickers": ["BBB", "DDD"], "metadata_by_ticker": {"DDD": {"scouts": ["breakout_scan"]}}}))


def test_build_combined_universe_appends_scouts_without_replacing_master(tmp_path):
    master = tmp_path / "final_dealflow_tickers_sec_eligible.json"; handoff = tmp_path / "deal_flow" / "final_dealflow_tickers.json"
    _write_master_json(master); _write_handoff(handoff)
    result = build_combined_universe(master_universe_path=master, handoff_path=handoff, quarter="2026Q2", output_csv=tmp_path / "master_fundamental_universe_2026Q2.csv", unresolved_new_scouts={"DDD": {"cik": "4", "company_title": "DDD Inc", "cik_status": "resolved"}})
    assert result.summary["master_count"] == 3
    assert result.summary["scout_count"] == 2
    assert result.summary["combined_count"] == 4
    assert result.summary["new_scout_count"] == 1
    assert [row["ticker"] for row in result.rows] == ["AAA", "BBB", "CCC", "DDD"]
    assert result.rows[-1]["dealflow_source_stage"] == "scout_ticker_summary"


def test_broad_final_hard_stops_when_universe_collapses_to_scout_only(tmp_path):
    rows = [{"ticker": f"S{i}", "cik": str(i), "quarter": "2026Q2"} for i in range(162)]
    gate = validate_universe_gate(rows, run_mode=RunMode.BROAD_MASTER_FINAL, scout_count=162, min_broad_universe_count=1000, artifacts={})
    assert gate.status == GateStatus.HARD_STOP
    assert gate.summary["reason"] == "broad_master_universe_too_small_or_scout_only"
