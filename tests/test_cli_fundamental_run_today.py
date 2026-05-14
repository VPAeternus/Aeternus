import json
from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()


def test_fundamental_run_today_help_exposes_gate_options():
    result = runner.invoke(app, ["fundamental-run-today", "--help"], env={"COLUMNS": "240"})
    assert result.exit_code == 0
    assert "--mode" in result.output
    assert "--master-universe" in result.output
    assert "--skip-llm" in result.output
    assert "--llm-model" in result.output
    assert "llm-reasoning" in result.output


def test_fundamental_run_today_help_exposes_complete_panel_options():
    result = runner.invoke(app, ["fundamental-run-today", "--help"], env={"COLUMNS": "240"})
    assert result.exit_code == 0
    assert "--emit-complete-panel" in result.output
    assert "--complete-panel-output-root" in result.output


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

    def fake_run_daily_fundamental(cfg, services=None):
        captured["cfg"] = cfg
        return type("Result", (), {"summary": {"final": True, "stopped": False}, "gates": []})()

    monkeypatch.setattr("tradingagents.research.fundamental.src.daily_run.orchestrator.run_daily_fundamental", fake_run_daily_fundamental)

    out = tmp_path / "run"
    result = runner.invoke(app, ["fundamental-run-today", "--mode", "diagnostic-only", "--date", "2026-05-12", "--quarter", "2026Q2", "--output-root", str(out), "--skip-fetch", "--skip-llm", "--min-broad-universe-count", "1", "--format", "json"])

    assert result.exit_code == 0, result.output
    cfg = captured["cfg"]
    assert cfg.master_universe_path is None


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

    result = runner.invoke(app, ["fundamental-run-today", "--mode", "diagnostic-only", "--date", "2026-05-12", "--quarter", "2026Q2", "--output-root", str(out), "--skip-fetch", "--skip-llm", "--min-broad-universe-count", "1", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert not (out / "master_fundamental_universe_2021Q4_active.json").exists()
