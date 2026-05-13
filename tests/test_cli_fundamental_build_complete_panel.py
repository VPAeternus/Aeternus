import csv
import json

from typer.testing import CliRunner

from cli.main import app


runner = CliRunner()


def _write_tiny_run(run_root):
    run_root.mkdir()
    (run_root / "fundamental_final_scores_2026-05-12.csv").write_text(
        "ticker,quarter,symbol,cik,company_title,entry_score_0_100,confidence,tier_1_bucket,post_llm_candidate_flag,causal_change,negative_revision_risk\n"
        "AAA,2026Q2,AAA,1,AAA Inc,80,high,Tier 1 - Balanced priority feed,1,3,1\n",
        encoding="utf-8",
    )
    (run_root / "high_conviction_top15.csv").write_text(
        "ticker,selection_rank,selected_sleeve,top15_bucket\nAAA,1,core,Top 10 core\n",
        encoding="utf-8",
    )
    (run_root / "high_conviction_top15_core_deterioration_refill_shadow.csv").write_text(
        "ticker,selection_rank,selected_sleeve,shadow_refill_status\nAAA,1,core,shadow_refill_review_only_not_official\n",
        encoding="utf-8",
    )


def test_fundamental_build_complete_panel_help():
    result = runner.invoke(app, ["fundamental-build-complete-panel", "--help"])
    assert result.exit_code == 0
    assert "--run-root" in result.output
    assert "--quarter" in result.output
    assert "--output-root" in result.output


def test_fundamental_build_complete_panel_rejects_missing_run_root(tmp_path):
    result = runner.invoke(app, [
        "fundamental-build-complete-panel",
        "--run-root", str(tmp_path / "missing"),
        "--quarter", "2026Q2",
        "--date", "2026-05-12",
        "--output-root", str(tmp_path / "out"),
    ])
    assert result.exit_code != 0
    assert "run root" in result.output.lower()


def test_fundamental_build_complete_panel_happy_path_writes_csv(tmp_path):
    run_root = tmp_path / "run"
    _write_tiny_run(run_root)

    result = runner.invoke(app, [
        "fundamental-build-complete-panel",
        "--run-root", str(run_root),
        "--quarter", "2026Q2",
        "--date", "2026-05-12",
        "--output-root", str(tmp_path / "out"),
        "--allow-missing-financials",
        "--format", "json",
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["validation"]["passed"] is True
    with open(payload["csv_path"], newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["ticker"] == "AAA"


def test_fundamental_build_complete_panel_validation_failure_exits_nonzero_for_raw_growth_prior_panel(tmp_path):
    run_root = tmp_path / "run"
    _write_tiny_run(run_root)
    prior = tmp_path / "Growth" / "combined_all_tiers.csv"
    prior.parent.mkdir()
    prior.write_text("ticker,quarter\nAAA,2026Q1\n", encoding="utf-8")

    result = runner.invoke(app, [
        "fundamental-build-complete-panel",
        "--run-root", str(run_root),
        "--quarter", "2026Q2",
        "--date", "2026-05-12",
        "--output-root", str(tmp_path / "out"),
        "--prior-panel", str(prior),
        "--allow-missing-financials",
    ])

    assert result.exit_code != 0
    assert "prior_panel_not_canonical" in result.output
