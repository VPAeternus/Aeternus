"""Tests for fiscal_calendar module.

Pure Python tests for fiscal year/quarter resolution with no LLM, network, or
conftest.py dependencies. Uses pytest conventions with monkeypatch factories
where needed.
"""

import sys
import types

import pytest

# Stub chromadb (Python 3.14 compatibility)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.agents.utils.fiscal_calendar import (
    FISCAL_YEAR_END_MONTH,
    get_fiscal_year_end_month,
    resolve_fiscal_quarter,
)
from tradingagents.agents.utils.fundamental_engine import build_fundamental_snapshot


class TestGetFiscalYearEndMonth:
    """Tests for get_fiscal_year_end_month."""

    def test_aapl_is_september(self):
        """AAPL FYE = September (month 9)."""
        assert get_fiscal_year_end_month("AAPL") == 9

    def test_msft_is_june(self):
        """MSFT FYE = June (month 6)."""
        assert get_fiscal_year_end_month("MSFT") == 6

    def test_unknown_defaults_to_december(self):
        """Unknown tickers default to month 12 (calendar year)."""
        assert get_fiscal_year_end_month("ZZZZ") == 12

    def test_case_insensitive(self):
        """Ticker lookup should be case-insensitive."""
        assert get_fiscal_year_end_month("aapl") == 9
        assert get_fiscal_year_end_month("Msft") == 6
        assert get_fiscal_year_end_month("AAPL") == 9
        assert get_fiscal_year_end_month("AaPL") == 9  # mixed case is uppercased to AAPL

    def test_all_values_are_valid_months(self):
        """All FYE months must be between 1 and 12."""
        for ticker, month in FISCAL_YEAR_END_MONTH.items():
            assert 1 <= month <= 12, f"{ticker} has invalid month {month}"

    def test_dict_has_no_december_entries(self):
        """Dictionary should not store month 12 (calendar year default)."""
        for ticker, month in FISCAL_YEAR_END_MONTH.items():
            assert month != 12, f"{ticker} should not be in dict with month 12 (use default)"

    def test_known_tickers_present(self):
        """Verify key non-December FYE companies are in the dict."""
        assert "AAPL" in FISCAL_YEAR_END_MONTH
        assert "MSFT" in FISCAL_YEAR_END_MONTH
        assert "NKE" in FISCAL_YEAR_END_MONTH
        assert "COST" in FISCAL_YEAR_END_MONTH


class TestResolveFiscalQuarter:
    """Tests for resolve_fiscal_quarter."""

    def test_apple_q1_fy2026(self):
        """AAPL FYE=Sep, so Dec 2025 quarter = Q1 FY2026."""
        result = resolve_fiscal_quarter("AAPL", "2025-12-31")
        assert result["fiscal_quarter"] == "1"
        assert result["fiscal_year"] == "2026"
        assert "Q1" in result["label"]
        assert "2026" in result["label"]

    def test_apple_q4_fy2025(self):
        """AAPL FYE=Sep, so Sep 2025 quarter = Q4 FY2025."""
        result = resolve_fiscal_quarter("AAPL", "2025-09-30")
        assert result["fiscal_quarter"] == "4"
        assert result["fiscal_year"] == "2025"

    def test_apple_q2_fy2026(self):
        """AAPL FYE=Sep, so Mar 2026 quarter = Q2 FY2026."""
        result = resolve_fiscal_quarter("AAPL", "2026-03-31")
        assert result["fiscal_quarter"] == "2"
        assert result["fiscal_year"] == "2026"

    def test_apple_q3_fy2026(self):
        """AAPL FYE=Sep, so Jun 2026 quarter = Q3 FY2026."""
        result = resolve_fiscal_quarter("AAPL", "2026-06-30")
        assert result["fiscal_quarter"] == "3"
        assert result["fiscal_year"] == "2026"

    def test_calendar_year_q4(self):
        """JPM FYE=Dec, so Dec 2024 quarter = Q4 FY2024."""
        result = resolve_fiscal_quarter("JPM", "2024-12-31")
        assert result["fiscal_quarter"] == "4"
        assert result["fiscal_year"] == "2024"

    def test_calendar_year_q1(self):
        """JPM FYE=Dec, so Mar 2024 quarter = Q1 FY2024."""
        result = resolve_fiscal_quarter("JPM", "2024-03-31")
        assert result["fiscal_quarter"] == "1"
        assert result["fiscal_year"] == "2024"

    def test_calendar_year_q2(self):
        """JPM FYE=Dec, so Jun 2024 quarter = Q2 FY2024."""
        result = resolve_fiscal_quarter("JPM", "2024-06-30")
        assert result["fiscal_quarter"] == "2"
        assert result["fiscal_year"] == "2024"

    def test_start_end_dates_present(self):
        """Result must include start and end keys."""
        result = resolve_fiscal_quarter("AAPL", "2025-12-31")
        assert "start" in result
        assert "end" in result
        assert result["end"] == "2025-12-31"

    def test_start_date_logic(self):
        """Start date should be 3 months prior to end date."""
        result = resolve_fiscal_quarter("AAPL", "2025-12-31")
        assert result["start"] == "2025-10-01"

    def test_label_format(self):
        """Label should follow 'QN FYYYYY' format."""
        result = resolve_fiscal_quarter("AAPL", "2025-12-31")
        assert isinstance(result["label"], str)
        assert len(result["label"]) > 0
        assert "Q1" in result["label"]
        assert "FY2026" in result["label"] or "2026" in result["label"]

    def test_invalid_date_returns_unknown(self):
        """Malformed date string should return all 'unknown' values."""
        result = resolve_fiscal_quarter("AAPL", "not-a-date")
        assert result["start"] == "unknown"
        assert result["end"] == "unknown"
        assert result["label"] == "unknown"
        assert result["fiscal_year"] == "unknown"
        assert result["fiscal_quarter"] == "unknown"

    def test_empty_date_returns_unknown(self):
        """Empty date string should return all 'unknown' values."""
        result = resolve_fiscal_quarter("AAPL", "")
        assert result["fiscal_quarter"] == "unknown"
        assert result["fiscal_year"] == "unknown"

    def test_malformed_date_formats(self):
        """Various malformed dates should return unknown."""
        bad_dates = [
            "2025-13-01",  # invalid month
            "2025-01-32",  # invalid day
            "2025/01/01",  # wrong separator
            "01-01-2025",  # wrong order
            "2025-1-1",    # missing zero-padding
        ]
        for bad_date in bad_dates:
            result = resolve_fiscal_quarter("AAPL", bad_date)
            assert result["fiscal_quarter"] == "unknown", f"Expected unknown for {bad_date}"

    def test_msft_all_four_quarters(self):
        """MSFT FYE=Jun: verify all 4 quarters resolve correctly.

        For MSFT FYE=Jun (month 6):
          Q1: Jul-Sep (ends Sep=9)
          Q2: Oct-Dec (ends Dec=12)
          Q3: Jan-Mar (ends Mar=3)
          Q4: Apr-Jun (ends Jun=6)
        """
        # Q1: Oct-Dec 2024, ending Dec → offset=(6-12)%12=6 → Q2 (not Q1)
        # Actually, let me recalculate:
        # FYE=6, end_month=9 (Sep): offset=(6-9)%12=9 → Q1. So Sep is Q1 FY2025.
        q1 = resolve_fiscal_quarter("MSFT", "2024-09-30")
        assert q1["fiscal_quarter"] == "1"
        assert q1["fiscal_year"] == "2025"

        # FYE=6, end_month=12 (Dec): offset=(6-12)%12=6 → Q2.
        q2 = resolve_fiscal_quarter("MSFT", "2024-12-31")
        assert q2["fiscal_quarter"] == "2"
        assert q2["fiscal_year"] == "2025"

        # FYE=6, end_month=3 (Mar): offset=(6-3)%12=3 → Q3.
        q3 = resolve_fiscal_quarter("MSFT", "2025-03-31")
        assert q3["fiscal_quarter"] == "3"
        assert q3["fiscal_year"] == "2025"

        # FYE=6, end_month=6 (Jun): offset=(6-6)%12=0 → Q4.
        q4 = resolve_fiscal_quarter("MSFT", "2025-06-30")
        assert q4["fiscal_quarter"] == "4"
        assert q4["fiscal_year"] == "2025"

    def test_nike_may_fiscal_year(self):
        """NKE FYE=May (month 5).

        For NKE FYE=May (month 5):
          Q1: Jun-Aug (ends Aug=8)
          Q2: Sep-Nov (ends Nov=11)
          Q3: Dec-Feb (ends Feb=2)
          Q4: Mar-May (ends May=5)
        """
        # May end = Q4 FY2024
        q4 = resolve_fiscal_quarter("NKE", "2024-05-31")
        assert q4["fiscal_quarter"] == "4"
        assert q4["fiscal_year"] == "2024"

        # Aug end = Q1 FY2025
        q1 = resolve_fiscal_quarter("NKE", "2024-08-31")
        assert q1["fiscal_quarter"] == "1"
        assert q1["fiscal_year"] == "2025"

    def test_case_insensitive_ticker_resolution(self):
        """Ticker lookup should be case-insensitive."""
        result_upper = resolve_fiscal_quarter("AAPL", "2025-12-31")
        result_lower = resolve_fiscal_quarter("aapl", "2025-12-31")
        assert result_upper["fiscal_quarter"] == result_lower["fiscal_quarter"]
        assert result_upper["fiscal_year"] == result_lower["fiscal_year"]

    def test_partial_date_string_handled(self):
        """Dates with extra characters after YYYY-MM-DD should still parse."""
        result = resolve_fiscal_quarter("AAPL", "2025-12-31T00:00:00")
        # Should only use first 10 characters
        assert result["fiscal_quarter"] == "1"
        assert result["fiscal_year"] == "2026"


class TestFundamentalEngineIntegration:
    """Test fiscal_calendar integration with fundamental_engine.

    Verifies that build_fundamental_snapshot returns fiscal_period key with
    correct structure.
    """

    def _make_bs_json(self, fiscal_date_ending="2024-09-30"):
        """Factory for balance sheet JSON with optional fiscal date."""
        import json

        return json.dumps({
            "quarterlyReports": [
                {
                    "fiscalDateEnding": fiscal_date_ending,
                    "totalAssets": "100000",
                    "totalLiabilities": "50000",
                    "totalShareholderEquity": "50000",
                    "totalCurrentAssets": "30000",
                    "totalCurrentLiabilities": "20000",
                }
            ]
        })

    def test_fiscal_period_key_present(self):
        """fiscal_period key must be present in result."""
        result = build_fundamental_snapshot(
            overview_json="{}",
            balance_sheet_json=self._make_bs_json(),
            cashflow_json="{}",
            income_statement_json="{}",
        )
        assert "fiscal_period" in result

    def test_fiscal_period_not_none_with_data(self):
        """fiscal_period should not be None when balance sheet reports exist."""
        result = build_fundamental_snapshot(
            overview_json="{}",
            balance_sheet_json=self._make_bs_json(),
            cashflow_json="{}",
            income_statement_json="{}",
        )
        assert result["fiscal_period"] is not None

    def test_fiscal_period_has_fiscal_date_ending(self):
        """fiscal_period dict should include fiscal_date_ending key."""
        result = build_fundamental_snapshot(
            overview_json="{}",
            balance_sheet_json=self._make_bs_json("2024-09-30"),
            cashflow_json="{}",
            income_statement_json="{}",
        )
        assert "fiscal_date_ending" in result["fiscal_period"]
        assert result["fiscal_period"]["fiscal_date_ending"] == "2024-09-30"

    def test_fiscal_period_tracks_latest_report(self):
        """fiscal_period should use the first (most recent) report's date."""
        import json

        bs_json = json.dumps({
            "quarterlyReports": [
                {
                    "fiscalDateEnding": "2024-12-31",
                    "totalAssets": "100000",
                    "totalLiabilities": "50000",
                    "totalShareholderEquity": "50000",
                },
                {
                    "fiscalDateEnding": "2024-09-30",
                    "totalAssets": "95000",
                    "totalLiabilities": "48000",
                    "totalShareholderEquity": "47000",
                },
            ]
        })
        result = build_fundamental_snapshot(
            overview_json="{}",
            balance_sheet_json=bs_json,
            cashflow_json="{}",
            income_statement_json="{}",
        )
        assert result["fiscal_period"]["fiscal_date_ending"] == "2024-12-31"

    def test_no_reports_fiscal_period_is_none(self):
        """fiscal_period should be None when no balance sheet reports exist."""
        result = build_fundamental_snapshot(
            overview_json="{}",
            balance_sheet_json="{}",
            cashflow_json="{}",
            income_statement_json="{}",
        )
        assert "fiscal_period" in result
        assert result["fiscal_period"] is None

    def test_empty_quarterly_reports_fiscal_period_is_none(self):
        """fiscal_period should be None when quarterlyReports array is empty."""
        import json

        bs_json = json.dumps({"quarterlyReports": []})
        result = build_fundamental_snapshot(
            overview_json="{}",
            balance_sheet_json=bs_json,
            cashflow_json="{}",
            income_statement_json="{}",
        )
        assert result["fiscal_period"] is None

    def test_original_keys_preserved(self):
        """Original 6 keys must still be present in result."""
        result = build_fundamental_snapshot(
            overview_json="{}",
            balance_sheet_json="{}",
            cashflow_json="{}",
            income_statement_json="{}",
        )
        expected_keys = ("ratios", "balance", "cashflow", "income", "piotroski", "data_coverage")
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_result_structure_with_all_data(self):
        """Result should have both original keys and fiscal_period."""
        result = build_fundamental_snapshot(
            overview_json="{}",
            balance_sheet_json=self._make_bs_json(),
            cashflow_json="{}",
            income_statement_json="{}",
        )
        # 6 original keys + fiscal_period = 7 keys
        assert len(result) == 7
        assert "fiscal_period" in result
        assert "ratios" in result

    def test_fiscal_period_format_consistency(self):
        """fiscal_period dict should have consistent structure across calls."""
        result1 = build_fundamental_snapshot(
            overview_json="{}",
            balance_sheet_json=self._make_bs_json("2024-09-30"),
            cashflow_json="{}",
            income_statement_json="{}",
        )
        result2 = build_fundamental_snapshot(
            overview_json="{}",
            balance_sheet_json=self._make_bs_json("2024-12-31"),
            cashflow_json="{}",
            income_statement_json="{}",
        )
        # Both should have the same keys
        if result1["fiscal_period"] is not None and result2["fiscal_period"] is not None:
            assert set(result1["fiscal_period"].keys()) == set(result2["fiscal_period"].keys())

    def test_no_fiscal_period_when_json_invalid(self):
        """Invalid JSON should not break fiscal_period extraction."""
        result = build_fundamental_snapshot(
            overview_json="invalid json",
            balance_sheet_json="also invalid",
            cashflow_json="nope",
            income_statement_json="broken",
        )
        assert "fiscal_period" in result
        assert result["fiscal_period"] is None
