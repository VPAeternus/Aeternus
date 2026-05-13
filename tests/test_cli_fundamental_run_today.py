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
