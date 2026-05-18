import csv
import hashlib
import inspect
import json

from typer.testing import CliRunner

from cli.main import app
from tradingagents.research.fundamental.src.panel.pit_master import (
    append_pit_master,
    infer_run_id,
)


runner = CliRunner()


def _write_panel(tmp_path, *, quarter="2022Q1", tickers=("AAA", "BBB"), validation_passed=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    panel = tmp_path / f"fundamental_complete_prellm_to_top15_{quarter}.csv"
    with panel.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "quarter",
                "ticker",
                "entry_score_0_100",
                "top15_selected",
                "shadow_selected",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        for i, ticker in enumerate(tickers):
            writer.writerow(
                {
                    "quarter": quarter,
                    "ticker": ticker,
                    "entry_score_0_100": str(80 - i),
                    "top15_selected": "1" if i == 0 else "0",
                    "shadow_selected": "0",
                }
            )
        writer.writerow(
            {
                "quarter": "2022Q2",
                "ticker": "OTHER",
                "entry_score_0_100": "10",
                "top15_selected": "0",
                "shadow_selected": "0",
            }
        )
    panel_hash = hashlib.sha256(panel.read_bytes()).hexdigest()
    panel.with_name(f"{panel.stem}_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "fundamental_complete_panel_v1",
                "row_count": len(tickers) + 1,
                "output_sha256": panel_hash,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    panel.with_name(f"{panel.stem}_columns.json").write_text(
        json.dumps({"schema_version": "fundamental_complete_panel_v1", "columns": ["quarter", "ticker"]}) + "\n",
        encoding="utf-8",
    )
    panel.with_name(f"{panel.stem}_validation.json").write_text(
        json.dumps({"passed": validation_passed, "errors": [] if validation_passed else [{"code": "bad"}]}) + "\n",
        encoding="utf-8",
    )
    return panel


def test_append_pit_master_filters_target_quarter_and_marks_latest(tmp_path):
    panel = _write_panel(tmp_path, quarter="2022Q1", tickers=("AAA", "BBB"))
    master = tmp_path / "pit_master.csv"

    first = append_pit_master(
        panel_csv=panel,
        master_csv=master,
        quarter="2022Q1",
        as_of="2022-02-15",
        run_id="run-a",
        official_latest=True,
    )

    assert first["rows_written"] == 2
    with master.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["ticker"] for row in rows] == ["AAA", "BBB"]
    assert {row["pit_official_latest"] for row in rows} == {"1"}
    assert {row["pit_run_id"] for row in rows} == {"run-a"}

    second_panel = _write_panel(tmp_path / "second", quarter="2022Q1", tickers=("CCC",))
    second = append_pit_master(
        panel_csv=second_panel,
        master_csv=master,
        quarter="2022Q1",
        as_of="2022-05-15",
        run_id="run-b",
        official_latest=True,
    )

    assert second["rows_written"] == 3
    with master.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    latest = [row for row in rows if row["pit_official_latest"] == "1"]
    old = [row for row in rows if row["pit_run_id"] == "run-a"]
    assert [row["ticker"] for row in latest] == ["CCC"]
    assert {row["pit_official_latest"] for row in old} == {"0"}


def test_append_pit_master_replaces_same_quarter_asof_run(tmp_path):
    panel = _write_panel(tmp_path, quarter="2022Q1", tickers=("AAA", "BBB"))
    master = tmp_path / "pit_master.csv"
    append_pit_master(panel_csv=panel, master_csv=master, quarter="2022Q1", as_of="2022-02-15", run_id="run-a")

    replacement = _write_panel(tmp_path / "replacement", quarter="2022Q1", tickers=("CCC",))
    result = append_pit_master(panel_csv=replacement, master_csv=master, quarter="2022Q1", as_of="2022-02-15", run_id="run-a")

    assert result["replaced_rows"] == 2
    with master.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["ticker"] for row in rows] == ["CCC"]


def test_append_pit_master_rejects_failed_validation(tmp_path):
    panel = _write_panel(tmp_path, validation_passed=False)
    master = tmp_path / "pit_master.csv"

    try:
        append_pit_master(panel_csv=panel, master_csv=master, quarter="2022Q1", as_of="2022-02-15", run_id="run-a")
    except ValueError as exc:
        assert "validation" in str(exc)
    else:
        raise AssertionError("expected failed validation to be rejected")


def test_append_pit_master_rejects_stale_manifest_hash(tmp_path):
    panel = _write_panel(tmp_path)
    panel.write_text(panel.read_text(encoding="utf-8") + "2022Q1,ZZZ,1,0,0\n")

    try:
        append_pit_master(
            panel_csv=panel,
            master_csv=tmp_path / "pit_master.csv",
            quarter="2022Q1",
            as_of="2022-02-15",
            run_id="run-a",
        )
    except ValueError as exc:
        assert "hash" in str(exc)
    else:
        raise AssertionError("expected stale manifest hash to be rejected")


def test_infer_run_id_uses_run_folder_when_panel_is_in_complete_panel(tmp_path):
    panel = (
        tmp_path
        / "run-a"
        / "complete_panel"
        / "fundamental_complete_prellm_to_top15_2022Q1.csv"
    )
    panel.parent.mkdir(parents=True)
    panel.write_text("quarter,ticker\n2022Q1,AAA\n", encoding="utf-8")

    assert infer_run_id(None, panel) == "run-a"
    assert infer_run_id(tmp_path / "run-a", panel) == "run-a"


def test_fundamental_run_quarter_alias_and_pit_append_help():
    alias = runner.invoke(app, ["fundamental-run-quarter", "--help"], env={"COLUMNS": "240"})
    assert alias.exit_code == 0
    run_quarter = _registered_command_callback("fundamental-run-quarter")
    assert "quarter" in inspect.signature(run_quarter).parameters
    assert "emit_complete_panel" in inspect.signature(run_quarter).parameters

    append = runner.invoke(app, ["fundamental-append-pit-master", "--help"], env={"COLUMNS": "240"})
    assert append.exit_code == 0
    append_pit = _registered_command_callback("fundamental-append-pit-master")
    assert "panel_csv" in inspect.signature(append_pit).parameters
    assert "master_csv" in inspect.signature(append_pit).parameters


def _registered_command_callback(name: str):
    for command in app.registered_commands:
        if command.name == name:
            return command.callback
    raise AssertionError(f"missing command: {name}")


def test_fundamental_run_quarter_allows_date_quarter_mismatch(monkeypatch, tmp_path):
    captured = {}

    def fake_run_daily_fundamental(cfg, services=None):
        captured["cfg"] = cfg
        return type("Result", (), {"summary": {"final": False, "stopped": "", "artifacts": {}}, "gates": []})()

    monkeypatch.setattr("tradingagents.research.fundamental.src.daily_run.orchestrator.run_daily_fundamental", fake_run_daily_fundamental)
    master = tmp_path / "master.json"
    master.write_text(json.dumps({"items": [{"symbol": "AAA", "cik": "1", "company_title": "AAA Inc"}]}))
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps({"tickers": ["AAA"], "metadata_by_ticker": {}, "source_stage": "daily_scout"}))

    result = runner.invoke(
        app,
        [
            "fundamental-run-quarter",
            "--mode",
            "diagnostic-only",
            "--date",
            "2022-05-15",
            "--quarter",
            "2022Q1",
            "--master-universe",
            str(master),
            "--handoff",
            str(handoff),
            "--output-root",
            str(tmp_path / "run"),
            "--skip-fetch",
            "--skip-llm",
            "--min-broad-universe-count",
            "1",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["cfg"].allow_date_quarter_mismatch is True
