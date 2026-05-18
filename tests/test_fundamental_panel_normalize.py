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


def test_normalize_derives_pre_llm_and_aggregate_flags():
    rows = [
        {
            "ticker": "T1",
            "quarter": "2026Q2",
            "tier_1_bucket": "Tier 1 - Balanced priority feed",
            "hp1_quality_pullback": "1",
            "repricing_momentum_extension": "1",
        },
        {
            "ticker": "HPX",
            "quarter": "2026Q2",
            "hp_production_extension": "1",
        },
        {
            "ticker": "T0",
            "quarter": "2026Q2",
            "tier_0_bucket": "Tier 0 - Broad right-tail scouting universe",
            "hp0_high_price_broad": "1",
        },
    ]
    out, _ = normalize_complete_panel_rows(rows, source_name="daily_final_scores")
    by_ticker = {row["ticker"]: row for row in out}

    assert by_ticker["T1"]["pre_llm_candidate_flag"] == "1"
    assert by_ticker["T1"]["tier_0_to_4_any_flag"] == "1"
    assert by_ticker["T1"]["tier_1_to_4_any_flag"] == "1"
    assert by_ticker["T1"]["hp_any_flag"] == "1"
    assert by_ticker["T1"]["rm_any_flag"] == "1"
    assert by_ticker["HPX"]["pre_llm_candidate_flag"] == "1"
    assert by_ticker["T0"]["pre_llm_candidate_flag"] == "0"
    assert by_ticker["T0"]["tier_0_to_4_any_flag"] == "1"
    assert by_ticker["T0"]["tier_1_to_4_any_flag"] == "0"
    assert by_ticker["T0"]["hp_any_flag"] == "1"


def test_normalize_derives_llm_flags_and_quarter_ranks():
    rows = [
        {
            "ticker": "BBB",
            "quarter": "2026Q2",
            "tier_1_bucket": "Tier 1 - Balanced priority feed",
            "pre_llm_fundamental_score": "5",
            "entry_score_0_100": "80",
            "llm_status": "complete",
            "post_llm_candidate_flag": "1",
            "causal_change": "3",
        },
        {
            "ticker": "AAA",
            "quarter": "2026Q2",
            "tier_1_bucket": "Tier 1 - Balanced priority feed",
            "pre_llm_fundamental_score": "7",
            "entry_score_0_100": "60",
            "llm_status": "pending",
        },
        {
            "ticker": "CCC",
            "quarter": "2026Q2",
            "pre_llm_fundamental_score": "9",
            "entry_score_0_100": "95",
            "llm_status": "not_required",
        },
        {
            "ticker": "DDD",
            "quarter": "2026Q1",
            "tier_2_bucket": "Tier 2 - High-priority compact feed",
            "pre_llm_fundamental_score": "4",
            "entry_score_0_100": "70",
            "llm_status": "complete",
            "post_llm_demote_flag": "1",
        },
    ]
    out, _ = normalize_complete_panel_rows(rows, source_name="daily_final_scores")
    by_ticker = {row["ticker"]: row for row in out}

    assert by_ticker["AAA"]["pre_llm_rank_by_score_quarter"] == "1"
    assert by_ticker["BBB"]["pre_llm_rank_by_score_quarter"] == "2"
    assert by_ticker["CCC"]["pre_llm_rank_by_score_quarter"] == ""
    assert by_ticker["DDD"]["pre_llm_rank_by_score_quarter"] == "1"
    assert by_ticker["CCC"]["entry_score_rank_by_quarter"] == "1"
    assert by_ticker["BBB"]["entry_score_rank_by_quarter"] == "2"
    assert by_ticker["AAA"]["entry_score_rank_by_quarter"] == "3"
    assert by_ticker["DDD"]["entry_score_rank_by_quarter"] == "1"
    assert by_ticker["AAA"]["llm_required_derived_flag"] == "1"
    assert by_ticker["AAA"]["llm_complete_derived_flag"] == "0"
    assert by_ticker["BBB"]["llm_required_derived_flag"] == "1"
    assert by_ticker["BBB"]["llm_complete_derived_flag"] == "1"
    assert by_ticker["BBB"]["has_post_llm"] == "1"
    assert by_ticker["BBB"]["post_llm_any_flag"] == "1"
    assert by_ticker["DDD"]["post_llm_any_flag"] == "1"
    assert by_ticker["CCC"]["llm_required_derived_flag"] == "0"


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
    assert out[0]["panel_build_id"] == "panel_abc123"
    assert out[0]["panel_build_timestamp"]
    assert out[0]["feature_schema_path"] == "tradingagents/research/fundamental/src/panel/schema.py"
    assert out[0]["entry_score_0_100"] == "88"
    assert summary["rows"] == 1


def test_normalize_fills_legacy_entry_score_aliases():
    out, _ = normalize_complete_panel_rows(
        [{"ticker": "AAA", "quarter": "2026Q2", "entry_raw_score": "42", "entry_score_0_100": "88"}],
        source_name="daily_final_scores",
    )

    assert out[0]["base_entry_raw_score"] == "42"
    assert out[0]["base_entry_score_0_100"] == "88"
    assert out[0]["compatibility_alias_source"] == "current_entry_score"


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
