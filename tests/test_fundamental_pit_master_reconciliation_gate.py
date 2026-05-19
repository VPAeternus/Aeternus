from tradingagents.research.fundamental.src.reconciliation.pit_master_reconcile import (
    validate_pit_master_rows,
)


def _base_row(**extra):
    row = {
        "ticker": "AAA",
        "quarter": "2026Q2",
        "score_producing_flag": "1",
        "accepted_row_flag": "1",
        "decision_date_rule": "full_evidence",
        "decision_date": "2026-05-10",
        "source_available_date": "2026-05-10",
        "target_period_end": "2026-03-31",
        "fiscal_period_start": "2026-01-01",
        "fiscal_period_end": "2026-03-31",
        "period_context_source": "companyfacts_accession",
        "period_context_missing_reason": "",
        "periodic_accession": "0000000000-26-000001",
        "entry_open_date": "2026-05-11",
        "entry_open": "10",
        "tradable_date": "2026-05-11",
        "entry_open_gap_sessions": "0",
        "price_adjustment_mode": "split_adjusted_for_returns",
        "entry_open_price_basis": "raw_open",
        "return_price_basis": "split_adjusted",
        "score_recompute_required_flag": "0",
        "llm_status": "not_required",
        "theme_tailwind_score": "0",
    }
    for field in (
        "revenue_value",
        "net_income_value",
        "assets_value",
        "operating_cash_flow_value",
        "investing_cash_flow_value",
        "financing_cash_flow_value",
    ):
        row[field] = "1"
        row[f"{field}_fact_filed"] = "2026-05-01"
        row[f"{field}_fact_end"] = "2026-03-31"
        row[f"{field}_fact_accession"] = "0000000000-26-000001"
        row[f"{field}_fact_is_consolidated"] = "1"
        row[f"{field}_fact_period_type"] = "quarterly"
    row.update(extra)
    return row


def _codes(result):
    return {error["code"] for error in result["blocking_errors"]}


def test_reconciliation_gate_fails_future_financial_fact():
    result = validate_pit_master_rows(
        [_base_row(revenue_value_fact_filed="2026-05-11")]
    )

    assert "blocking_future_fact_leakage" in _codes(result)
    assert result["status"] == "invalid"


def test_reconciliation_gate_fails_wrong_accession():
    result = validate_pit_master_rows(
        [_base_row(revenue_value_fact_accession="0000000000-26-999999")]
    )

    assert "blocking_wrong_accession" in _codes(result)


def test_reconciliation_gate_fails_missing_period_context_for_accepted_score_row():
    result = validate_pit_master_rows(
        [
            _base_row(
                target_period_end="",
                fiscal_period_start="",
                fiscal_period_end="",
                period_context_source="",
                period_context_missing_reason="ambiguous_period_context",
            )
        ]
    )

    assert "blocking_missing_target_period_end" in _codes(result)
    assert "blocking_missing_fiscal_period_start" in _codes(result)
    assert "blocking_missing_fiscal_period_end" in _codes(result)
    assert "blocking_missing_period_context_source" in _codes(result)
    assert "blocking_period_context_missing_reason_present" in _codes(result)


def test_reconciliation_gate_fails_fact_end_before_target_period():
    result = validate_pit_master_rows(
        [_base_row(assets_value_fact_end="2025-03-31")]
    )

    assert "blocking_fact_end_not_target_period" in _codes(result)


def test_reconciliation_gate_fails_post_score_rewrite_and_tradable_mismatch():
    result = validate_pit_master_rows(
        [
            _base_row(
                score_recompute_required_flag="1",
                tradable_date="2026-05-12",
            )
        ]
    )

    assert "blocking_post_score_financial_rewrite" in _codes(result)
    assert "blocking_tradable_date_mismatch" in _codes(result)


def test_reconciliation_gate_fails_late_llm_theme_and_forbidden_selection():
    result = validate_pit_master_rows(
        [
            _base_row(
                llm_status="complete",
                llm_source_document_dates="2026-05-01;2026-05-11",
                llm_prompt_input_allowed_docs_only="1",
                theme_tailwind_score="5",
                theme_source_available_date="2026-05-12",
                selection_ranking_source_columns="entry_score_0_100,return_90d_pct",
            )
        ]
    )

    assert "blocking_late_llm_source" in _codes(result)
    assert "blocking_late_theme_source" in _codes(result)
    assert "blocking_selection_uses_future_field" in _codes(result)


def test_reconciliation_gate_passes_clean_row():
    result = validate_pit_master_rows([_base_row()])

    assert result["status"] == "valid"
    assert result["blocking_errors"] == []
