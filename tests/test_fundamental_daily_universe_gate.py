import json
from tradingagents.research.fundamental.src.daily_run.identity import IdentityResolution
from tradingagents.research.fundamental.src.daily_run.models import DailyRunConfig, GateStatus, RunMode
from tradingagents.research.fundamental.src.daily_run.orchestrator import DailyRunServices, _default_identity_resolver, run_daily_fundamental
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


def test_build_combined_universe_rejects_unresolved_new_scouts(tmp_path):
    master = tmp_path / "final_dealflow_tickers_sec_eligible.json"
    handoff = tmp_path / "deal_flow" / "final_dealflow_tickers.json"
    _write_master_json(master)
    _write_handoff(handoff)

    result = build_combined_universe(
        master_universe_path=master,
        handoff_path=handoff,
        quarter="2026Q2",
        output_csv=tmp_path / "master_fundamental_universe_2026Q2.csv",
        rejected_new_scouts={"DDD": {"identity_status": "ticker_or_name_unresolved", "rejection_reason": "no SEC filer found"}},
    )

    assert result.summary["combined_count"] == 3
    assert result.summary["rejected_new_scout_count"] == 1
    assert [row["ticker"] for row in result.rows] == ["AAA", "BBB", "CCC"]
    assert (tmp_path / "dealflow_identity_rejections.csv").read_text(encoding="utf-8")


def test_orchestrator_resolves_new_dealflow_before_gate2(tmp_path):
    master = tmp_path / "master.json"
    handoff = tmp_path / "handoff.json"
    _write_master_json(master)
    handoff.write_text(json.dumps({"source_stage": "daily_scout", "tickers": ["DDD", "EEE"], "metadata_by_ticker": {}}))

    def resolver(ticker: str) -> IdentityResolution:
        if ticker == "DDD":
            return IdentityResolution("DDD", "DDD", "DDD", "", "4", "DDD Inc", "resolved_from_sec_ticker_map", "")
        return IdentityResolution("EEE", "", "", "", "", "", "ticker_or_name_unresolved", "no SEC filer found")

    def coverage(**kwargs):
        return {"ticker_count": 4, "status_counts": {}, "missing_input_counts": {}, "fetch_queue_count": 0, "blocked_tickers": [], "outputs": {}}

    def prices(tickers, *, start, end):
        return []

    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="diagnostic-only",
        output_root=tmp_path / "run",
        master_universe_path=master,
        handoff_path=handoff,
        skip_fetch=True,
        skip_llm=True,
        min_broad_universe_count=1,
        master_additions_ledger_path=tmp_path / "additions.jsonl",
    )
    result = run_daily_fundamental(cfg, services=DailyRunServices(price_provider=prices, run_coverage=coverage, resolve_identity=resolver))
    gate2 = next(g for g in result.gates if g.gate_number == 2)

    assert gate2.status == GateStatus.PASS
    assert gate2.summary["identity_resolved_new_count"] == 1
    assert gate2.summary["identity_rejected_new_count"] == 1
    assert "DDD" in (cfg.output_root / "master_fundamental_universe_2026Q2.csv").read_text(encoding="utf-8")
    assert "EEE" in (cfg.output_root / "dealflow_identity_rejections.csv").read_text(encoding="utf-8")
    snapshot = json.loads((cfg.output_root / "master_fundamental_universe_2026Q2.json").read_text(encoding="utf-8"))
    assert snapshot["type"] == "combined_master_for_daily_run"
    assert [row["ticker"] for row in snapshot["items"]] == ["AAA", "BBB", "CCC", "DDD"]


def test_orchestrator_identity_prepass_handles_csv_master(tmp_path):
    master = tmp_path / "master.csv"
    handoff = tmp_path / "handoff.json"
    master.write_text("ticker,cik,company_title\nAAA,1,AAA Inc\nBBB,2,BBB Inc\n", encoding="utf-8")
    handoff.write_text(json.dumps({"source_stage": "daily_scout", "tickers": ["BBB", "DDD"], "metadata_by_ticker": {}}))
    calls = []

    def resolver(ticker: str) -> IdentityResolution:
        calls.append(ticker)
        return IdentityResolution("DDD", "DDD", "DDD", "", "4", "DDD Inc", "resolved_from_sec_ticker_map", "")

    def coverage(**kwargs):
        return {"ticker_count": 3, "status_counts": {}, "missing_input_counts": {}, "fetch_queue_count": 0, "blocked_tickers": [], "outputs": {}}

    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="diagnostic-only",
        output_root=tmp_path / "run",
        master_universe_path=master,
        handoff_path=handoff,
        skip_fetch=True,
        skip_llm=True,
        min_broad_universe_count=1,
    )

    result = run_daily_fundamental(cfg, services=DailyRunServices(price_provider=lambda *args, **kwargs: [], run_coverage=coverage, resolve_identity=resolver))

    assert result.summary["final"] is False
    assert calls == ["DDD"]
    snapshot = json.loads((cfg.output_root / "master_fundamental_universe_2026Q2.json").read_text(encoding="utf-8"))
    assert [row["ticker"] for row in snapshot["items"]] == ["AAA", "BBB", "DDD"]


def test_master_additions_ledger_not_written_when_later_gate_hard_stops(tmp_path):
    master = tmp_path / "master.json"
    handoff = tmp_path / "handoff.json"
    ledger = tmp_path / "additions.jsonl"
    _write_master_json(master)
    handoff.write_text(json.dumps({"source_stage": "daily_scout", "tickers": ["DDD"], "metadata_by_ticker": {}}))

    def resolver(ticker: str) -> IdentityResolution:
        return IdentityResolution("DDD", "DDD", "DDD", "", "4", "DDD Inc", "resolved_from_sec_ticker_map", "")

    def coverage(**kwargs):
        return {
            "ticker_count": 4,
            "status_counts": {},
            "missing_input_counts": {"companyfacts": 4},
            "fetch_queue_count": 0,
            "blocked_tickers": [],
            "outputs": {},
        }

    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="broad-master-final",
        output_root=tmp_path / "run",
        master_universe_path=master,
        handoff_path=handoff,
        skip_fetch=True,
        skip_llm=True,
        min_broad_universe_count=1,
        master_additions_ledger_path=ledger,
    )

    result = run_daily_fundamental(cfg, services=DailyRunServices(price_provider=lambda *args, **kwargs: [], run_coverage=coverage, resolve_identity=resolver))

    assert result.summary["final"] is False
    assert not ledger.exists()


def test_broad_final_hard_stops_when_universe_collapses_to_scout_only(tmp_path):
    rows = [{"ticker": f"S{i}", "cik": str(i), "quarter": "2026Q2"} for i in range(162)]
    gate = validate_universe_gate(rows, run_mode=RunMode.BROAD_MASTER_FINAL, scout_count=162, min_broad_universe_count=1000, artifacts={})
    assert gate.status == GateStatus.HARD_STOP
    assert gate.summary["reason"] == "broad_master_universe_too_small_or_scout_only"


def test_default_identity_resolver_checks_trusted_panel_before_rejecting(tmp_path):
    sec_map = tmp_path / "sec_company_tickers.json"
    sec_map.write_text(json.dumps({"0": {"ticker": "OTHER", "cik_str": "1", "title": "Other Inc."}}))
    panel = tmp_path / "trusted_panel.csv"
    panel.write_text("ticker,cik,company_title\nEXAS,1124140,EXACT SCIENCES CORP\n", encoding="utf-8")
    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="diagnostic-only",
        output_root=tmp_path / "run",
        sec_ticker_map_path=sec_map,
        identity_complete_panel_path=panel,
    )

    result = _default_identity_resolver(cfg)("EXAS")

    assert result.identity_status == "resolved_from_complete_panel"
    assert result.cik == "1124140"
    assert result.company_title == "EXACT SCIENCES CORP"


def test_default_identity_resolver_uses_sec_direct_lookup_last(tmp_path):
    sec_map = tmp_path / "sec_company_tickers.json"
    sec_map.write_text(json.dumps({"0": {"ticker": "OTHER", "cik_str": "1", "title": "Other Inc."}}))
    calls = []
    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="diagnostic-only",
        output_root=tmp_path / "run",
        sec_ticker_map_path=sec_map,
        identity_complete_panel_path=tmp_path / "missing_panel.csv",
    )

    def direct_lookup(ticker):
        calls.append(ticker)
        return {"ticker": ticker, "cik": "999999", "company_title": "Direct Lookup Inc."}

    result = _default_identity_resolver(cfg, sec_direct_lookup=direct_lookup)("NEWC")

    assert calls == ["NEWC"]
    assert result.identity_status == "resolved_from_sec_direct"
    assert result.cik == "999999"
