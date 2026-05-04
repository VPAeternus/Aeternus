from tradingagents.research.fundamental_autoresearch.contracts import FilingSnapshotRow
from tradingagents.research.fundamental_autoresearch.features import build_feature_row


def _row() -> FilingSnapshotRow:
    return FilingSnapshotRow(
        ticker="AAPL",
        cik="0000320193",
        filing_type="10-Q",
        period_end="2025-12-27",
        filed_at="2026-01-29",
        accepted_at="2026-01-29T16:32:10Z",
        effective_market_date="2026-01-30",
        fiscal_period="Q1",
        fiscal_year=2026,
        sector="Technology",
        data_coverage_score=0.9,
        missing_fields=[],
        source_flags=["sec_submissions", "sec_companyfacts"],
        restatement_suspect=False,
    )


def test_build_feature_row_computes_growth_quality_health_and_valuation_features():
    features = build_feature_row(
        _row(),
        current_metrics={
            "revenue": 124_300_000_000.0,
            "gross_profit": 58_300_000_000.0,
            "operating_income": 42_800_000_000.0,
            "free_cash_flow": 31_500_000_000.0,
            "total_debt": 98_200_000_000.0,
            "shareholder_equity": 74_100_000_000.0,
            "current_assets": 152_400_000_000.0,
            "current_liabilities": 139_100_000_000.0,
            "shares_outstanding": 15_100_000_000.0,
            "enterprise_value": 3_450_000_000_000.0,
            "market_cap": 3_300_000_000_000.0,
            "net_income": 36_300_000_000.0,
        },
        previous_metrics={
            "revenue": 119_600_000_000.0,
            "free_cash_flow": 28_200_000_000.0,
            "shares_outstanding": 15_400_000_000.0,
            "shareholder_equity": 70_000_000_000.0,
        },
    )

    assert features["ticker"] == "AAPL"
    assert features["revenue_growth_yoy_pct"] > 0
    assert features["gross_margin"] > 0
    assert features["operating_margin"] > 0
    assert features["debt_to_equity"] > 0
    assert features["current_ratio"] > 0
    assert features["fcf_growth_yoy_pct"] > 0
    assert features["share_count_change_pct"] < 0
    assert features["ev_to_sales"] > 0
    assert features["earnings_yield"] > 0


def test_build_feature_row_tracks_missing_fields_and_coverage():
    features = build_feature_row(
        _row(),
        current_metrics={
            "revenue": 124_300_000_000.0,
            "gross_profit": None,
            "operating_income": None,
            "free_cash_flow": None,
            "total_debt": None,
            "shareholder_equity": None,
            "current_assets": None,
            "current_liabilities": None,
            "shares_outstanding": None,
            "enterprise_value": None,
            "market_cap": None,
            "net_income": None,
        },
        previous_metrics={},
    )

    assert "gross_profit" in features["missing_fields"]
    assert "operating_income" in features["missing_fields"]
    assert features["data_coverage_score"] < 0.2
    assert features["gross_margin"] is None
    assert features["debt_to_equity"] is None


def test_build_feature_row_computes_acceleration_tension_and_stress_features():
    features = build_feature_row(
        _row(),
        current_metrics={
            "revenue": 124_300_000_000.0,
            "gross_profit": 58_300_000_000.0,
            "operating_income": 42_800_000_000.0,
            "free_cash_flow": 31_500_000_000.0,
            "total_debt": 98_200_000_000.0,
            "shareholder_equity": 74_100_000_000.0,
            "current_assets": 152_400_000_000.0,
            "current_liabilities": 139_100_000_000.0,
            "shares_outstanding": 15_100_000_000.0,
            "enterprise_value": 3_450_000_000_000.0,
            "market_cap": 3_300_000_000_000.0,
            "net_income": 36_300_000_000.0,
        },
        previous_metrics={
            "revenue": 119_600_000_000.0,
            "previous_revenue": 110_000_000_000.0,
            "free_cash_flow": 28_200_000_000.0,
            "previous_free_cash_flow": 24_000_000_000.0,
            "shares_outstanding": 15_400_000_000.0,
            "shareholder_equity": 70_000_000_000.0,
            "previous_gross_margin": 0.44,
            "previous_operating_margin": 0.27,
            "previous_current_ratio": 1.02,
            "previous_debt_to_equity": 1.50,
        },
    )

    assert features["revenue_growth_acceleration_pct"] is not None
    assert features["fcf_growth_acceleration_pct"] is not None
    assert features["margin_change_pct"] is not None
    assert features["quality_valuation_tension"] is not None
    assert features["liquidity_stress_score"] is not None
    assert features["leverage_stress_score"] is not None
    assert features["liquidity_stress_score"] < 1.0
    assert features["leverage_stress_score"] < 1.0
