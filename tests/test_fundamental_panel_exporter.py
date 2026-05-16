import csv
import hashlib
import json

from tradingagents.research.fundamental.src.panel.exporter import (
    build_complete_panel,
    _ordered_row,
    _portable_manifest_path,
    _portable_run_root_path,
    _portable_source_artifact_path,
)


def test_build_complete_panel_writes_csv_manifest_columns_and_validation(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    final_scores = run / "fundamental_final_scores_2026-05-12.csv"
    final_scores.write_text(
        "ticker,quarter,symbol,cik,company_title,entry_score_0_100,confidence,tier_1_bucket,post_llm_candidate_flag,causal_change,negative_revision_risk\n"
        "AAA,2026Q2,AAA,1,AAA Inc,80,high,Tier 1 - Balanced priority feed,1,3,1\n"
    )
    top15 = run / "high_conviction_top15.csv"
    top15.write_text("ticker,selection_rank,selected_sleeve,top15_bucket\nAAA,1,core,Top 10 core\n")
    shadow = run / "high_conviction_top15_core_deterioration_refill_shadow.csv"
    shadow.write_text("ticker,selection_rank,selected_sleeve,shadow_refill_status\nAAA,1,core,shadow_refill_review_only_not_official\n")

    result = build_complete_panel(
        run_root=run,
        output_root=tmp_path / "out",
        quarter="2026Q2",
        as_of="2026-05-12",
        prior_panel_path=None,
        allow_missing_financials=True,
    )

    assert result["validation"]["passed"] is True
    assert result["csv_path"].endswith(".csv")
    assert result["manifest_path"].endswith("_manifest.json")
    assert result["columns_path"].endswith("_columns.json")
    assert result["validation_path"].endswith("_validation.json")

    with open(result["csv_path"], newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["ticker"] == "AAA"
    assert rows[0]["top15_selected"] == "1"
    assert rows[0]["shadow_selected"] == "1"

    with open(result["manifest_path"], encoding="utf-8") as handle:
        manifest = json.load(handle)
    assert manifest["row_counts_by_quarter"] == {"2026Q2": 1}
    assert manifest["top15_selected_count"] == 1
    assert manifest["shadow_selected_count"] == 1

    with open(result["validation_path"], encoding="utf-8") as handle:
        validation = json.load(handle)
    assert validation["passed"] is True

    with open(result["columns_path"], encoding="utf-8") as handle:
        columns = json.load(handle)
    assert columns["schema_version"]
    assert columns["columns"]


def test_portable_manifest_path_mirrors_external_selection_source(tmp_path):
    repo_root = tmp_path / "repo"
    output_root = repo_root / "outputs" / "panel"
    external = tmp_path / "external"
    external.mkdir()
    top15 = external / "high_conviction_top15.csv"
    top15.write_text("ticker,selection_rank\nAAA,1\n")

    portable = _portable_manifest_path(str(top15), output_root, repo_root)

    assert portable == "outputs/panel/selection_sources/high_conviction_top15.csv"
    assert (repo_root / portable).read_text() == top15.read_text()


def test_portable_source_artifact_mirrors_external_run_file(tmp_path):
    repo_root = tmp_path / "repo"
    output_root = repo_root / "outputs" / "panel"
    external_run = tmp_path / "external" / "daily-run"
    external_run.mkdir(parents=True)
    final_scores = external_run / "fundamental_final_scores_2026-05-12.csv"
    final_scores.write_text("ticker,quarter\nAAA,2026Q2\n")

    run_root_path = _portable_run_root_path(external_run, output_root, repo_root)
    artifact_path = _portable_source_artifact_path(final_scores, output_root, repo_root)

    assert run_root_path == "outputs/panel/source_artifacts/daily-run"
    assert artifact_path == (
        "outputs/panel/source_artifacts/daily-run/"
        "fundamental_final_scores_2026-05-12.csv"
    )
    assert (repo_root / artifact_path).read_text() == final_scores.read_text()


def test_ordered_row_fills_blank_flag_defaults():
    row = _ordered_row(
        {
            "ticker": "AAA",
            "quarter": "2026Q2",
            "top15_selected": "",
            "shadow_core_deterioration_review_flag": "",
        }
    )

    assert row["top15_selected"] == "0"
    assert row["shadow_core_deterioration_review_flag"] == "0"


def test_build_complete_panel_rejects_raw_growth_prior_panel(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    final_scores = run / "fundamental_final_scores_2026-05-12.csv"
    final_scores.write_text("ticker,quarter\nAAA,2026Q2\n")
    growth_prior = tmp_path / "Growth" / "combined_all_tiers.csv"
    growth_prior.parent.mkdir()
    growth_prior.write_text("ticker,quarter\nAAA,2026Q1\n")

    result = build_complete_panel(
        run_root=run,
        output_root=tmp_path / "out",
        quarter="2026Q2",
        as_of="2026-05-12",
        prior_panel_path=growth_prior,
        allow_missing_financials=True,
    )

    assert result["validation"]["passed"] is False
    assert any(error["code"] == "prior_panel_not_canonical" for error in result["validation"]["errors"])


def test_build_complete_panel_rejects_selector_leakage_metadata(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    final_scores = run / "fundamental_final_scores_2026-05-12.csv"
    final_scores.write_text(
        "ticker,quarter,selection_ranking_source_columns\n"
        'AAA,2026Q2,"entry_score_0_100,return_90d_pct"\n'
    )

    result = build_complete_panel(
        run_root=run,
        output_root=tmp_path / "out",
        quarter="2026Q2",
        as_of="2026-05-12",
        prior_panel_path=None,
        allow_missing_financials=True,
    )

    assert result["validation"]["passed"] is False
    assert any(
        error["code"] == "forbidden_selection_column"
        and error["column"] == "return_90d_pct"
        for error in result["validation"]["errors"]
    )


def test_build_complete_panel_rejects_prior_panel_missing_manifest(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    final_scores = run / "fundamental_final_scores_2026-05-12.csv"
    final_scores.write_text("ticker,quarter\nAAA,2026Q2\n")
    prior = tmp_path / "fundamental_complete_prellm_to_top15_2026Q1.csv"
    prior.write_text("ticker,quarter\nAAA,2026Q1\n")

    result = build_complete_panel(
        run_root=run,
        output_root=tmp_path / "out",
        quarter="2026Q2",
        as_of="2026-05-12",
        prior_panel_path=prior,
        allow_missing_financials=True,
    )

    assert result["validation"]["passed"] is False
    assert any(
        error["code"] == "prior_panel_manifest_missing"
        for error in result["validation"]["errors"]
    )


def test_build_complete_panel_normalizes_prior_blank_flags_before_validation(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    final_scores = run / "fundamental_final_scores_2026-05-12.csv"
    final_scores.write_text("ticker,quarter,post_llm_candidate_flag\nNEW,2026Q2,0\n")

    prior = tmp_path / "fundamental_complete_prellm_to_top15_2026Q1.csv"
    with prior.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ticker",
                "quarter",
                "revenue_value",
                "net_income_value",
                "assets_value",
                "operating_cash_flow_value",
                "investing_cash_flow_value",
                "financing_cash_flow_value",
                "llm_status",
                "post_llm_candidate_flag",
                "top15_selected",
                "shadow_core_deterioration_review_flag",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(
                {
                    "ticker": "OLD",
                    "quarter": "2026Q1",
                    "revenue_value": "0",
                    "net_income_value": "0",
                    "assets_value": "0",
                    "operating_cash_flow_value": "0",
                    "investing_cash_flow_value": "0",
                    "financing_cash_flow_value": "0",
                    "llm_status": "complete",
                    "post_llm_candidate_flag": "0",
                    "top15_selected": "0",
                    "shadow_core_deterioration_review_flag": "",
                }
        )
    prior_hash = hashlib.sha256(prior.read_bytes()).hexdigest()
    prior.with_name(f"{prior.stem}_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "fundamental_complete_panel_v1",
                "output_sha256": prior_hash,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    prior.with_name(f"{prior.stem}_validation.json").write_text(
        json.dumps({"passed": True, "errors": []}) + "\n",
        encoding="utf-8",
    )

    result = build_complete_panel(
        run_root=run,
        output_root=tmp_path / "out",
        quarter="2026Q2",
        as_of="2026-05-12",
        prior_panel_path=prior,
        allow_missing_financials=True,
    )

    assert result["validation"]["passed"] is True
    with open(result["csv_path"], newline="", encoding="utf-8") as handle:
        rows = {row["ticker"]: row for row in csv.DictReader(handle)}
    assert rows["OLD"]["shadow_core_deterioration_review_flag"] == "0"


def test_existing_2026q2_run_exports_complete_panel_contract(tmp_path):
    import pytest
    from pathlib import Path
    from tradingagents.research.fundamental.src.panel.exporter import build_complete_panel

    run_root = Path("eval_results/fundamental/2026-05-12_2026Q2_hp_rm_final_v3")
    if not run_root.exists():
        pytest.skip("local 2026Q2 run artifact not present")

    result = build_complete_panel(
        run_root=run_root,
        output_root=tmp_path / "panel",
        quarter="2026Q2",
        as_of="2026-05-12",
        prior_panel_path=None,
        allow_missing_financials=True,
    )

    assert result["validation"]["passed"] is True
    assert result["validation"]["duplicate_ticker_quarter_count"] == 0
    assert result["validation"]["required_columns_missing"] == []
    assert result["validation"]["top15_selected_count"] == 15
    assert result["validation"]["shadow_selected_count"] == 15
