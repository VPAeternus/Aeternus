from datetime import date

from tradingagents.research.fundamental.src.panel.normalize import normalize_complete_panel_rows
from tradingagents.research.fundamental.src.panel.schema import REQUIRED_COMPLETE_PANEL_COLUMNS


def test_normalize_derives_legacy_post_llm_subtiers_from_canonical_fields():
    rows = [{
        "ticker": "AAA",
        "quarter": "2026Q2",
        "tier_1_bucket": "Tier 1 - Balanced priority feed",
        "post_llm_candidate_flag": "1",
        "post_llm_high_priority_flag": "1",
        "causal_change": "3",
        "negative_revision_risk": "1",
        "narrative_delta_bucket": "constructive",
        "score_addition": "3",
        "prior_score_addition": "1",
    }]
    out, summary = normalize_complete_panel_rows(rows, source_name="daily_final_scores")
    row = out[0]
    assert row["post_llm_tier_1_1_flag"] == "1"
    assert row["post_llm_tier_1_2_flag"] == "1"
    assert row["post_llm_tier_1_3_flag"] == "1"
    assert row["post_llm_tier_1_4_flag"] == "1"
    assert summary["rows"] == 1


def test_normalize_fills_flag_blanks_with_zero():
    rows = [{"ticker": "BBB", "quarter": "2026Q2", "post_llm_candidate_flag": ""}]
    out, _ = normalize_complete_panel_rows(rows, source_name="daily_final_scores")
    assert out[0]["top15_selected"] == "0"
    assert out[0]["shadow_selected"] == "0"
    assert out[0]["post_llm_candidate_flag"] == "0"


def test_normalize_converts_label_values_in_flag_fields_to_one():
    rows = [{
        "ticker": "LBL",
        "quarter": "2026Q2",
        "hp0_high_price_broad": "HP0 - High-price broad watchlist",
        "extended_candidate_universe": "Extended candidate universe",
    }]
    out, _ = normalize_complete_panel_rows(rows, source_name="daily_final_scores")
    assert out[0]["hp0_high_price_broad"] == "1"
    assert out[0]["extended_candidate_universe"] == "1"


def test_normalize_returns_complete_schema_rows_without_mutating_input():
    rows = [{"ticker": "ccc", "quarter": "2026Q2", "entry_score_0_100": "88"}]
    out, summary = normalize_complete_panel_rows(
        rows,
        source_name="daily_final_scores",
        source_run_root="eval_results/fundamental/run",
        source_artifact="fundamental_final_scores.csv",
        source_artifact_sha256="abc123",
    )
    assert rows == [{"ticker": "ccc", "quarter": "2026Q2", "entry_score_0_100": "88"}]
    assert set(REQUIRED_COMPLETE_PANEL_COLUMNS).issubset(out[0])
    assert out[0]["ticker"] == "CCC"
    assert out[0]["symbol"] == "CCC"
    assert out[0]["panel_row_source"] == "daily_final_scores"
    assert out[0]["source_run_root"] == "eval_results/fundamental/run"
    assert out[0]["source_artifact"] == "fundamental_final_scores.csv"
    assert out[0]["source_artifact_sha256"] == "abc123"
    assert out[0]["entry_score_0_100"] == "88"
    assert summary["rows"] == 1


def test_normalize_uses_companyfacts_when_supplied():
    rows = [{"ticker": "AAA", "quarter": "2026Q2", "entry_open_date": "2026-05-12"}]
    facts = {
        "AAA": {
            "facts": {"us-gaap": {
                "Revenues": {"units": {"USD": [{"filed": "2026-05-01", "end": "2026-03-31", "val": 100}]}},
                "NetIncomeLoss": {"units": {"USD": [{"filed": "2026-05-01", "end": "2026-03-31", "val": 10}]}},
                "Assets": {"units": {"USD": [{"filed": "2026-05-01", "end": "2026-03-31", "val": 500}]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"filed": "2026-05-01", "end": "2026-03-31", "val": 20}]}},
                "NetCashProvidedByUsedInInvestingActivities": {"units": {"USD": [{"filed": "2026-05-01", "end": "2026-03-31", "val": -5}]}},
                "NetCashProvidedByUsedInFinancingActivities": {"units": {"USD": [{"filed": "2026-05-01", "end": "2026-03-31", "val": -2}]}},
            }},
            "entityName": "AAA Inc",
            "cik": "1",
        },
    }
    out, summary = normalize_complete_panel_rows(
        rows,
        source_name="daily_final_scores",
        facts_by_ticker=facts,
        as_of=date(2026, 5, 12),
    )
    assert out[0]["revenue_value"] == "100"
    assert out[0]["net_income_value"] == "10"
    assert out[0]["assets_value"] == "500"
    assert out[0]["operating_cash_flow_value"] == "20"
    assert out[0]["investing_cash_flow_value"] == "-5"
    assert out[0]["financing_cash_flow_value"] == "-2"
    assert summary["financial_values"]["rows_with_any_missing_financial_value"] == 0
