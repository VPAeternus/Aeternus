import csv
import json

from tradingagents.research.fundamental.src.panel.exporter import build_complete_panel


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
