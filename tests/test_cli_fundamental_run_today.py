import json
from typer.testing import CliRunner
from cli.main import app
from tradingagents.research.fundamental.src.daily_run.models import GateResult, GateStatus

runner = CliRunner()


def test_fundamental_run_today_help_exposes_gate_options():
    result = runner.invoke(app, ["fundamental-run-today", "--help"], env={"COLUMNS": "240"})
    assert result.exit_code == 0
    assert "--mode" in result.output
    assert "--master-universe" in result.output
    assert "--allow-missing-handoff" in result.output
    assert "--allow-date-quarter-mismatch" in result.output
    assert "--skip-llm" in result.output
    assert "--llm-model" in result.output
    assert "llm-reasoning" in result.output


def test_fundamental_run_today_help_exposes_complete_panel_options():
    result = runner.invoke(app, ["fundamental-run-today", "--help"], env={"COLUMNS": "240"})
    assert result.exit_code == 0
    assert "--emit-complete-panel" in result.output
    assert "--complete-panel-output-root" in result.output


def test_fundamental_run_smoke_help_exists():
    result = runner.invoke(app, ["fundamental-run-smoke", "--help"], env={"COLUMNS": "240"})
    assert result.exit_code == 0
    assert "--master-universe" in result.output
    assert "--handoff" in result.output
    assert "--prior-final-scores" in result.output


def test_fundamental_run_smoke_uses_scout_smoke_skip_llm(monkeypatch, tmp_path):
    captured = {}

    def fake_run_daily_fundamental(cfg, services=None):
        captured["cfg"] = cfg
        return type(
            "Result",
            (),
            {
                "summary": {"final": False, "stopped": "", "artifacts": {}},
                "gates": [],
            },
        )()

    monkeypatch.setattr("tradingagents.research.fundamental.src.daily_run.orchestrator.run_daily_fundamental", fake_run_daily_fundamental)
    master = tmp_path / "master.json"
    master.write_text(json.dumps({"items": [{"symbol": "AAA", "cik": "1", "company_title": "AAA Inc"}]}))
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps({"tickers": ["AAA"], "metadata_by_ticker": {}, "source_stage": "daily_scout"}))
    prior = tmp_path / "prior.csv"
    prior.write_text("ticker,quarter,entry_open,entry_qoq_pct,pre_llm_fundamental_score\nAAA,2026Q1,10,0,1\n")

    result = runner.invoke(
        app,
        [
            "fundamental-run-smoke",
            "--date",
            "2026-05-12",
            "--quarter",
            "2026Q2",
            "--master-universe",
            str(master),
            "--handoff",
            str(handoff),
            "--prior-final-scores",
            str(prior),
            "--output-root",
            str(tmp_path / "run"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["cfg"].mode == "scout-smoke"
    assert captured["cfg"].skip_llm is True
    assert captured["cfg"].skip_fetch is True
    assert captured["cfg"].review_allow_live_price_fetch is False
    assert captured["cfg"].prior_context_path == prior


def test_fundamental_run_smoke_enforces_minimum_broad_universe(tmp_path):
    master = tmp_path / "master.json"
    master.write_text(json.dumps({"items": [{"symbol": "AAA", "cik": "1", "company_title": "AAA Inc"}]}))
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps({"tickers": ["AAA"], "metadata_by_ticker": {}, "source_stage": "daily_scout"}))

    result = runner.invoke(
        app,
        [
            "fundamental-run-smoke",
            "--date",
            "2026-05-12",
            "--quarter",
            "2026Q2",
            "--master-universe",
            str(master),
            "--handoff",
            str(handoff),
            "--output-root",
            str(tmp_path / "run"),
            "--min-broad-universe-count",
            "2",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
    assert "smoke_master_universe_too_small" in result.output


def test_fundamental_run_today_rejects_missing_mode(tmp_path):
    result = runner.invoke(app, ["fundamental-run-today", "--mode", "", "--output-root", str(tmp_path)])
    assert result.exit_code != 0
    assert "mode" in result.output.lower()


def test_fundamental_run_today_diagnostic_writes_manifest(tmp_path):
    master = tmp_path / "master.json"
    master.write_text(json.dumps({"items": [{"symbol": "AAA", "cik": "1", "company_title": "AAA Inc"}]}))
    out = tmp_path / "run"
    result = runner.invoke(app, ["fundamental-run-today", "--mode", "diagnostic-only", "--date", "2026-05-12", "--quarter", "2026Q2", "--master-universe", str(master), "--output-root", str(out), "--skip-fetch", "--skip-llm", "--min-broad-universe-count", "1", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert (out / "run_manifest.json").exists()


def test_fundamental_run_today_defaults_to_start_plus_additions(monkeypatch, tmp_path):
    captured = {}

    def fake_materialize_master_universe(*, output_root, start_path=None, additions_path=None):
        captured["materialize"] = {
            "output_root": output_root,
            "start_path": start_path,
            "additions_path": additions_path,
        }
        out = output_root / "master_fundamental_universe_2021Q4_active.json"
        out.write_text(json.dumps({"items": [{"ticker": "AAA"}]}), encoding="utf-8")
        return out

    def fake_build_combined_universe(*, master_universe_path, handoff_path, quarter, output_csv, **kwargs):
        output_csv.write_text("ticker,quarter\nAAA,2026Q2\n", encoding="utf-8")
        return type(
            "Universe",
            (),
            {"rows": [{"ticker": "AAA"}], "summary": {"scout_count": 0}, "artifacts": {}},
        )()

    def fake_validate_universe_gate(rows, **kwargs):
        return GateResult(2, "Universe construction and drift control", GateStatus.PASS, {}, {})

    def fake_coverage_runner(**kwargs):
        return {"fetch_queue_count": 0, "missing_input_counts": {"companyfacts": 0}, "outputs": {}}

    monkeypatch.setattr("tradingagents.research.fundamental.src.daily_run.orchestrator.materialize_master_universe", fake_materialize_master_universe)
    monkeypatch.setattr("tradingagents.research.fundamental.src.daily_run.orchestrator.build_combined_universe", fake_build_combined_universe)
    monkeypatch.setattr("tradingagents.research.fundamental.src.daily_run.orchestrator.validate_universe_gate", fake_validate_universe_gate)
    monkeypatch.setattr("tradingagents.research.fundamental.src.daily_run.orchestrator.run_sec_coverage_manifest", fake_coverage_runner)

    out = tmp_path / "run"
    result = runner.invoke(app, ["fundamental-run-today", "--mode", "diagnostic-only", "--date", "2026-05-12", "--quarter", "2026Q2", "--output-root", str(out), "--skip-fetch", "--skip-llm", "--min-broad-universe-count", "1", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert captured["materialize"]["output_root"] == out
    assert captured["materialize"]["start_path"] is None


def test_fundamental_run_today_explicit_master_universe_wins(monkeypatch, tmp_path):
    captured = {}

    def fake_run_daily_fundamental(cfg, services=None):
        captured["cfg"] = cfg
        return type("Result", (), {"summary": {"final": True, "stopped": False}, "gates": []})()

    monkeypatch.setattr("tradingagents.research.fundamental.src.daily_run.orchestrator.run_daily_fundamental", fake_run_daily_fundamental)

    master = tmp_path / "custom.json"
    master.write_text(json.dumps({"items": [{"symbol": "ZZZ", "cik": "9", "company_title": "ZZZ Inc"}]}))
    out = tmp_path / "run"
    result = runner.invoke(app, ["fundamental-run-today", "--mode", "diagnostic-only", "--date", "2026-05-12", "--quarter", "2026Q2", "--master-universe", str(master), "--output-root", str(out), "--skip-fetch", "--skip-llm", "--min-broad-universe-count", "1", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert captured["cfg"].master_universe_path == master


def test_fundamental_run_today_does_not_materialize_after_final_run_block(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    (out / "run_manifest.json").write_text(json.dumps({"final": True}), encoding="utf-8")
    before = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())

    result = runner.invoke(app, ["fundamental-run-today", "--mode", "diagnostic-only", "--date", "2026-05-12", "--quarter", "2026Q2", "--output-root", str(out), "--skip-fetch", "--skip-llm", "--min-broad-universe-count", "1", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert not (out / "master_fundamental_universe_2021Q4_active.json").exists()
    after = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert after == before


def test_fundamental_run_today_broad_final_hard_stops_without_expected_handoff(tmp_path):
    master = tmp_path / "master.json"
    master.write_text(json.dumps({"items": [{"symbol": "AAA", "cik": "1", "company_title": "AAA Inc"}]}))
    out = tmp_path / "run"
    result = runner.invoke(app, ["fundamental-run-today", "--mode", "broad-master-final", "--date", "2026-05-12", "--quarter", "2026Q2", "--master-universe", str(master), "--output-root", str(out), "--skip-fetch", "--skip-llm", "--min-broad-universe-count", "1", "--format", "json"])
    assert result.exit_code != 0
    assert "handoff" in result.output.lower()
    assert "missing" in result.output.lower()
