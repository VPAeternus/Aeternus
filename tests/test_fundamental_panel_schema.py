from tradingagents.research.fundamental.src.panel.schema import (
    COMPLETE_PANEL_SCHEMA_VERSION,
    REQUIRED_COMPLETE_PANEL_COLUMNS,
    REQUIRED_NONBLANK_FIELDS,
    FLAG_FIELDS,
    default_for_field,
    missing_reason_field,
)


def test_complete_panel_schema_includes_operator_required_groups():
    required = set(REQUIRED_COMPLETE_PANEL_COLUMNS)
    for field in [
        "ticker",
        "quarter",
        "symbol",
        "cik",
        "cik10",
        "ticker_mapping_source",
        "ticker_mapping_effective_date",
        "price_ticker_used",
        "facts_cik_used",
        "company_title",
        "decision_date_rule",
        "source_available_date",
        "financial_cutoff_date",
        "entry_open_raw",
        "entry_open_adjusted_for_return_calc",
        "entry_open_price_basis",
        "return_price_basis",
        "revenue_value",
        "net_income_value",
        "assets_value",
        "operating_cash_flow_value",
        "investing_cash_flow_value",
        "financing_cash_flow_value",
        "financial_values_namespace",
        "financial_values_concepts",
        "source_run_root",
        "source_artifact",
        "source_artifact_sha256",
        "pre_llm_fundamental_score",
        "tier_1_bucket",
        "hp_production_extension",
        "llm_status",
        "post_llm_candidate_flag",
        "post_llm_tier_1_1_flag",
        "repricing_momentum_extension",
        "top15_selected",
        "shadow_selected",
        "field_population_status",
    ]:
        assert field in required
    assert COMPLETE_PANEL_SCHEMA_VERSION.startswith("fundamental_complete_panel_v")


def test_required_nonblank_fields_have_missing_reason_fields():
    for field in REQUIRED_NONBLANK_FIELDS:
        assert missing_reason_field(field) in REQUIRED_COMPLETE_PANEL_COLUMNS


def test_flag_fields_default_to_zero():
    for field in FLAG_FIELDS:
        assert default_for_field(field) == "0"


def test_numeric_llm_fields_are_not_flags():
    for field in ["causal_change", "negative_revision_risk"]:
        assert field not in FLAG_FIELDS
        assert default_for_field(field) == ""
