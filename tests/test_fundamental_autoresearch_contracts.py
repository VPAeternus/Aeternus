from tradingagents.research.fundamental_autoresearch.contracts import (
    FilingSnapshotRow,
    FundamentalEvaluationSummary,
    FundamentalScoreResult,
)


def test_filing_snapshot_row_contract_shape():
    row = FilingSnapshotRow(
        ticker="AAPL",
        cik="0000320193",
        filing_type="10-Q",
        period_end="2025-12-27",
        filed_at="2026-01-29T16:32:10Z",
        accepted_at="2026-01-29T16:32:10Z",
        effective_market_date="2026-01-30",
        fiscal_period="Q1",
        fiscal_year=2026,
        sector="Technology",
        data_coverage_score=0.92,
        missing_fields=[],
        source_flags=["sec_companyfacts"],
        restatement_suspect=False,
    )

    assert row.ticker == "AAPL"
    assert row.filing_type == "10-Q"
    assert row.fiscal_year == 2026
    assert row.data_coverage_score == 0.92


def test_fundamental_score_result_contract_shape():
    result = FundamentalScoreResult(
        ticker="AAPL",
        effective_market_date="2026-01-30",
        fundamental_score=72.5,
        growth_score=80.0,
        quality_score=75.0,
        health_score=60.0,
        capital_discipline_score=70.0,
        valuation_score=55.0,
        score_version="baseline_v1",
    )

    assert result.ticker == "AAPL"
    assert result.fundamental_score == 72.5
    assert result.score_version == "baseline_v1"


def test_fundamental_evaluation_summary_contract_shape():
    summary = FundamentalEvaluationSummary(
        dataset_name="sec_large_cap_v1",
        score_version="baseline_v1",
        primary_metric_name="rank_ic_60d_sector_neutral",
        primary_metric_value=0.071,
        coverage_ratio=0.88,
        observations=34120,
    )

    assert summary.dataset_name == "sec_large_cap_v1"
    assert summary.primary_metric_name == "rank_ic_60d_sector_neutral"
    assert summary.observations == 34120
