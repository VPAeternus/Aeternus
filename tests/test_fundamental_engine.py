"""Tests for tradingagents.agents.utils.fundamental_engine"""

import json
import sys
import types
import pytest

# Stub chromadb before it can be imported (pydantic v1 incompatible with Python 3.14)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []  # make it look like a package
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.agents.utils.fundamental_engine import (
    _num,
    _safe_div,
    _pct_change,
    _trend,
    compute_ratios,
    compute_balance_sheet_metrics,
    compute_cashflow_metrics,
    compute_income_metrics,
    compute_piotroski_fscore,
    compute_yfinance_snapshot,
    build_fundamental_snapshot,
)


# --- Factories ---

def _overview(**overrides):
    base = {
        "PERatio": "25.5",
        "PEGRatio": "1.2",
        "EVToEBITDA": "18.3",
        "ReturnOnEquityTTM": "0.22",
        "ReturnOnAssetsTTM": "0.08",
        "GrossProfitTTM": "50000000",
        "RevenueTTM": "100000000",
        "OperatingMarginTTM": "0.15",
        "ProfitMargin": "0.12",
        "Beta": "1.1",
        "EPS": "5.20",
        "ForwardPE": "22.0",
        "PriceToBookRatio": "8.5",
        "DividendYield": "0.015",
        "QuarterlyEarningsGrowthYOY": "0.12",
        "QuarterlyRevenueGrowthYOY": "0.08",
    }
    base.update(overrides)
    return base


def _bs_report(**overrides):
    base = {
        "fiscalDateEnding": "2024-09-30",
        "totalAssets": "300000000",
        "totalLiabilities": "150000000",
        "totalShareholderEquity": "150000000",
        "totalCurrentAssets": "80000000",
        "totalCurrentLiabilities": "40000000",
        "inventory": "10000000",
        "cashAndCashEquivalentsAtCarryingValue": "30000000",
        "shortTermDebt": "5000000",
        "longTermDebt": "50000000",
        "commonStockSharesOutstanding": "10000000",
    }
    base.update(overrides)
    return base


def _cf_report(**overrides):
    base = {
        "fiscalDateEnding": "2024-09-30",
        "operatingCashflow": "20000000",
        "capitalExpenditures": "5000000",
        "netIncome": "12000000",
    }
    base.update(overrides)
    return base


def _is_report(**overrides):
    base = {
        "fiscalDateEnding": "2024-09-30",
        "totalRevenue": "100000000",
        "grossProfit": "60000000",
        "operatingIncome": "20000000",
        "netIncome": "12000000",
        "ebitda": "25000000",
        "interestExpense": "3000000",
        "researchAndDevelopment": "8000000",
    }
    base.update(overrides)
    return base


# --- _num tests ---

class TestNum:
    def test_valid_float_string(self):
        assert _num("12345.67") == 12345.67

    def test_none_returns_none(self):
        assert _num(None) is None

    def test_string_none(self):
        assert _num("None") is None

    def test_na_string(self):
        assert _num("N/A") is None

    def test_dash(self):
        assert _num("-") is None

    def test_empty_string(self):
        assert _num("") is None

    def test_int_passthrough(self):
        assert _num(42) == 42.0

    def test_float_passthrough(self):
        assert _num(3.14) == 3.14

    def test_negative_string(self):
        assert _num("-500.5") == -500.5

    def test_whitespace(self):
        assert _num("  123  ") == 123.0

    def test_invalid_string(self):
        assert _num("abc") is None


# --- compute_ratios tests ---

class TestComputeRatios:
    def test_happy_path(self):
        r = compute_ratios(_overview())
        assert r["pe"] == 25.5
        assert r["forward_pe"] == 22.0
        assert r["peg"] == 1.2
        assert r["roe"] == 0.22
        assert r["beta"] == 1.1
        assert r["eps"] == 5.20

    def test_missing_fields(self):
        r = compute_ratios({})
        assert r["pe"] is None
        assert r["roe"] is None
        assert r["gross_margin_ratio"] is None

    def test_partial_data(self):
        r = compute_ratios({"PERatio": "30", "EPS": "2.5"})
        assert r["pe"] == 30
        assert r["eps"] == 2.5
        assert r["peg"] is None


# --- compute_balance_sheet_metrics tests ---

class TestBalanceSheet:
    def test_happy_path(self):
        reports = [_bs_report()]
        m = compute_balance_sheet_metrics(reports)
        assert m["current_ratio"] == 2.0
        assert m["debt_to_equity"] == 1.0
        assert m["debt_to_assets"] == 0.5
        assert m["cash"] == 30000000.0

    def test_empty_reports(self):
        m = compute_balance_sheet_metrics([])
        assert m == {"error": "no_data"}

    def test_missing_current_liabilities(self):
        reports = [_bs_report(totalCurrentLiabilities="None")]
        m = compute_balance_sheet_metrics(reports)
        assert m["current_ratio"] is None
        assert m["quick_ratio"] is None

    def test_equity_trend_improving(self):
        reports = [
            _bs_report(totalShareholderEquity="200000000"),
            _bs_report(totalShareholderEquity="180000000"),
            _bs_report(totalShareholderEquity="160000000"),
            _bs_report(totalShareholderEquity="140000000"),
        ]
        m = compute_balance_sheet_metrics(reports)
        assert m["equity_trend"] == "improving"


# --- compute_cashflow_metrics tests ---

class TestCashflow:
    def test_happy_path(self):
        reports = [_cf_report()]
        m = compute_cashflow_metrics(reports)
        assert m["ocf"] == 20000000.0
        assert m["fcf"] == 15000000.0  # 20M - 5M
        assert m["fcf_positive"] is True
        assert m["net_income"] == 12000000.0

    def test_empty_reports(self):
        m = compute_cashflow_metrics([])
        assert m == {"error": "no_data"}

    def test_negative_fcf(self):
        reports = [_cf_report(operatingCashflow="3000000", capitalExpenditures="5000000")]
        m = compute_cashflow_metrics(reports)
        assert m["fcf"] == -2000000.0
        assert m["fcf_positive"] is False


# --- compute_income_metrics tests ---

class TestIncome:
    def test_happy_path(self):
        reports = [_is_report()]
        m = compute_income_metrics(reports)
        assert m["gross_margin"] == 0.6
        assert m["operating_margin"] == 0.2
        assert m["net_margin"] == 0.12
        assert m["rd_intensity"] == 0.08
        assert m["interest_coverage"] is not None

    def test_empty_reports(self):
        m = compute_income_metrics([])
        assert m == {"error": "no_data"}

    def test_revenue_growth_between_quarters(self):
        reports = [
            _is_report(totalRevenue="120000000"),
            _is_report(totalRevenue="100000000"),
        ]
        m = compute_income_metrics(reports)
        assert m["revenue_growth_qoq"] == 20.0


# --- compute_piotroski_fscore tests ---

class TestPiotroski:
    def test_healthy_company(self):
        income = compute_income_metrics([
            _is_report(totalRevenue="120000000", grossProfit="75000000"),
            _is_report(totalRevenue="110000000", grossProfit="65000000"),
            _is_report(totalRevenue="105000000", grossProfit="62000000"),
            _is_report(totalRevenue="100000000", grossProfit="58000000"),
        ])
        balance = compute_balance_sheet_metrics([
            _bs_report(totalLiabilities="140000000", totalShareholderEquity="160000000"),
            _bs_report(totalLiabilities="145000000", totalShareholderEquity="155000000"),
            _bs_report(totalLiabilities="148000000", totalShareholderEquity="152000000"),
            _bs_report(totalLiabilities="150000000", totalShareholderEquity="150000000"),
        ])
        cashflow = compute_cashflow_metrics([_cf_report()])
        ratios = compute_ratios(_overview())

        p = compute_piotroski_fscore(income, balance, cashflow, ratios)
        assert 0 <= p["fscore"] <= 9
        assert p["missing_criteria"] == 0
        assert isinstance(p["criteria"], dict)
        assert len(p["criteria"]) == 9

    def test_distressed_company(self):
        income = compute_income_metrics([
            _is_report(netIncome="-5000000", totalRevenue="80000000", grossProfit="30000000"),
            _is_report(netIncome="-3000000", totalRevenue="90000000", grossProfit="35000000"),
        ])
        balance = compute_balance_sheet_metrics([
            _bs_report(totalCurrentAssets="30000000", totalCurrentLiabilities="50000000"),
        ])
        cashflow = compute_cashflow_metrics([
            _cf_report(operatingCashflow="-2000000", netIncome="-5000000"),
        ])
        ratios = compute_ratios({"ReturnOnAssetsTTM": "-0.05"})

        p = compute_piotroski_fscore(income, balance, cashflow, ratios)
        assert p["fscore"] <= 4
        assert p["criteria"]["net_income_positive"] is False

    def test_missing_data(self):
        p = compute_piotroski_fscore(
            {"error": "no_data"},
            {"error": "no_data"},
            {"error": "no_data"},
            {},
        )
        assert p["fscore"] == 0
        assert p["missing_criteria"] == 9


# --- compute_yfinance_snapshot tests ---

class TestYfinanceSnapshot:
    def test_happy_path(self):
        info = {
            "forwardPE": 22.5,
            "priceToBook": 8.0,
            "enterpriseToEbitda": 18.0,
            "targetMeanPrice": 200.0,
            "currentPrice": 170.0,
            "shortRatio": 1.5,
            "recommendationKey": "buy",
        }
        s = compute_yfinance_snapshot(info)
        assert s["forward_pe"] == 22.5
        assert s["current_price"] == 170.0
        assert s["upside_pct"] is not None
        assert s["upside_pct"] > 0
        assert s["recommendation"] == "buy"

    def test_empty_dict(self):
        s = compute_yfinance_snapshot({})
        assert s == {"error": "no_data"}

    def test_none_input(self):
        s = compute_yfinance_snapshot(None)
        assert s == {"error": "no_data"}


# --- build_fundamental_snapshot tests ---

class TestBuildSnapshot:
    def test_integration(self):
        overview = json.dumps(_overview())
        bs = json.dumps({"quarterlyReports": [_bs_report()]})
        cf = json.dumps({"quarterlyReports": [_cf_report()]})
        is_ = json.dumps({"quarterlyReports": [_is_report()]})

        result = build_fundamental_snapshot(overview, bs, cf, is_)

        assert "ratios" in result
        assert "balance" in result
        assert "cashflow" in result
        assert "income" in result
        assert "piotroski" in result
        assert "data_coverage" in result
        assert 0 <= result["data_coverage"] <= 1

    def test_empty_inputs(self):
        result = build_fundamental_snapshot("", "", "", "")
        assert result["data_coverage"] >= 0
        assert result["piotroski"]["missing_criteria"] == 9

    def test_invalid_json(self):
        result = build_fundamental_snapshot("not json", "{}", "[]", "null")
        assert "ratios" in result
        assert "piotroski" in result

    def test_size_budget(self):
        """Snapshot JSON should fit within a reasonable size budget."""
        overview = json.dumps(_overview())
        bs = json.dumps({"quarterlyReports": [_bs_report() for _ in range(8)]})
        cf = json.dumps({"quarterlyReports": [_cf_report() for _ in range(8)]})
        is_ = json.dumps({"quarterlyReports": [_is_report() for _ in range(8)]})

        result = build_fundamental_snapshot(overview, bs, cf, is_)
        serialized = json.dumps(result)
        assert len(serialized) < 5000  # computed metrics should be compact
