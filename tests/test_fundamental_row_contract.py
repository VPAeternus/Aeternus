from tradingagents.research.fundamental.src.daily_run.row_contract import (
    build_row_contract,
    validate_row_contract,
)


def _valid_row(**overrides):
    row = {
        "quarter": "2022Q1",
        "ticker": "ABC",
        "event_date": "2022-02-20",
        "earnings_8k_filing_date": "2022-02-20",
        "periodic_filing_date": "2022-03-10",
        "periodic_form": "10-Q",
        "periodic_accession": "0001193125-22-123456",
        "periodic_primary_document": "abc-20220131.htm",
        "fiscal_year": "2022",
        "fiscal_period": "Q1",
        "fiscal_period_start": "2021-11-01",
        "fiscal_period_end": "2022-01-31",
        "target_period_end": "2022-01-31",
        "period_context_source": "companyfacts_accession",
        "period_context_confidence": "high",
        "source_available_date": "2022-03-10",
        "financial_cutoff_date": "2022-03-10",
        "decision_date": "2022-03-10",
        "decision_date_rule": "full_evidence",
        "entry_open_date": "2022-03-11",
        "entry_open": "12.34",
        "score_producing_flag": "1",
        "accepted_row_flag": "1",
        "diagnostic_only_flag": "0",
        "price_reference_used_for_scoring_flag": "0",
        "score_timestamp": "2022-03-10T16:30:00",
        "execution_date": "2022-03-11",
        "execution_price": "12.34",
        "execution_after_score_timestamp_flag": "1",
        "cik": "123456",
        "cik10": "0000123456",
        "security_id": "ABC-common",
        "ticker_as_of_decision_date": "ABC",
        "ticker_mapping_source": "pit_security_master",
        "ticker_mapping_effective_date": "2020-01-01",
        "ticker_mapping_pit_valid_flag": "1",
        "price_ticker_used": "ABC",
        "facts_cik_used": "0000123456",
        "ticker_cik_mapping_confidence": "high",
        "universe_membership_source": "master_start",
        "universe_membership_effective_date": "2021-12-31",
        "retrospective_universe_backfill_flag": "0",
        "not_eligible_for_historical_selection_validation": "0",
        "prior_context_source": "bootstrap",
        "prior_context_pit_valid_flag": "1",
    }
    row.update(overrides)
    return row


def test_full_evidence_contract_requires_periodic_accession_and_fiscal_period():
    contract = build_row_contract(
        _valid_row(
            periodic_accession="",
            fiscal_period_end="",
            target_period_end="",
        ),
        decision_date_rule="full_evidence",
    )

    issues = validate_row_contract(contract)

    assert "missing_periodic_accession" in issues
    assert "missing_fiscal_period_metadata" in issues


def test_financial_cutoff_cannot_be_after_decision_date():
    contract = build_row_contract(
        _valid_row(financial_cutoff_date="2022-03-11"),
        decision_date_rule="full_evidence",
    )

    assert "financial_cutoff_after_decision_date" in validate_row_contract(contract)


def test_retrospective_universe_membership_is_diagnostic_only():
    contract = build_row_contract(
        _valid_row(
            decision_date="2022-03-10",
            universe_membership_effective_date="2026-01-01",
            retrospective_universe_backfill_flag="1",
            diagnostic_only_flag="0",
            not_eligible_for_historical_selection_validation="0",
        ),
        decision_date_rule="full_evidence",
    )

    issues = validate_row_contract(contract)

    assert "retrospective_universe_backfill_not_diagnostic" in issues


def test_bootstrap_initial_quarter_allows_missing_prior_context_only_with_reason():
    allowed = build_row_contract(
        _valid_row(
            prior_context_source="",
            prior_context_pit_valid_flag="",
            prior_context_missing_reason="bootstrap_initial_quarter_missing_prior_context",
        ),
        decision_date_rule="full_evidence",
    )
    blocked = build_row_contract(
        _valid_row(
            prior_context_source="",
            prior_context_pit_valid_flag="",
            prior_context_missing_reason="",
        ),
        decision_date_rule="full_evidence",
    )

    assert "missing_prior_context" not in validate_row_contract(allowed)
    assert "missing_prior_context" in validate_row_contract(blocked)


def test_entry_open_scoring_requires_later_execution_price_or_research_label():
    contract = build_row_contract(
        _valid_row(
            price_reference_used_for_scoring_flag="1",
            score_timing_mode="post_open_research_score",
            execution_timing_mode="same_open",
            execution_after_score_timestamp_flag="0",
            diagnostic_only_flag="0",
        ),
        decision_date_rule="full_evidence",
    )

    assert "execution_not_after_score_timestamp" in validate_row_contract(contract)


def test_ticker_mapping_must_be_effective_by_decision_date():
    contract = build_row_contract(
        _valid_row(ticker_mapping_effective_date="2026-01-01"),
        decision_date_rule="full_evidence",
    )

    assert "ticker_mapping_after_decision_date" in validate_row_contract(contract)


def test_price_ticker_and_facts_cik_must_map_to_same_security():
    contract = build_row_contract(
        _valid_row(
            price_ticker_used="XYZ",
            ticker_as_of_decision_date="ABC",
        ),
        decision_date_rule="full_evidence",
    )

    assert "price_ticker_facts_cik_mismatch" in validate_row_contract(contract)
