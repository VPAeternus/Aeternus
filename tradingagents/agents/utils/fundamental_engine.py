"""Compatibility fundamental metrics for legacy graph tests.

The current daily fundamental pipeline lives under
``tradingagents.research.fundamental``. These helpers keep older graph tests and
collectors importable without network calls or LLM calls.
"""

from __future__ import annotations

import json
import math
from typing import Any


def _num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in {"none", "n/a", "nan", "-"}:
            return None
        try:
            parsed = float(cleaned)
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100


def _trend(values: list[float | None]) -> str | None:
    clean = [value for value in values if value is not None]
    if len(clean) < 2:
        return None
    diff = clean[0] - clean[-1]
    threshold = abs(clean[-1]) * 0.02 if clean[-1] != 0 else 0.01
    if diff > threshold:
        return "improving"
    if diff < -threshold:
        return "declining"
    return "stable"


def _parse_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _reports(raw: Any) -> list[dict[str, Any]]:
    payload = _parse_json(raw)
    reports = payload.get("quarterlyReports")
    if not isinstance(reports, list):
        return []
    return [row for row in reports if isinstance(row, dict)]


def compute_ratios(overview: dict[str, Any]) -> dict[str, Any]:
    gross_profit = _num(overview.get("GrossProfitTTM"))
    revenue = _num(overview.get("RevenueTTM"))
    return {
        "pe": _num(overview.get("PERatio")),
        "forward_pe": _num(overview.get("ForwardPE")),
        "peg": _num(overview.get("PEGRatio")),
        "ev_ebitda": _num(overview.get("EVToEBITDA")),
        "price_to_book": _num(overview.get("PriceToBookRatio")),
        "roe": _num(overview.get("ReturnOnEquityTTM")),
        "roa": _num(overview.get("ReturnOnAssetsTTM")),
        "gross_margin_ratio": _safe_div(gross_profit, revenue),
        "operating_margin": _num(overview.get("OperatingMarginTTM")),
        "profit_margin": _num(overview.get("ProfitMargin")),
        "beta": _num(overview.get("Beta")),
        "eps": _num(overview.get("EPS")),
        "dividend_yield": _num(overview.get("DividendYield")),
        "quarterly_earnings_growth_yoy": _num(overview.get("QuarterlyEarningsGrowthYOY")),
        "quarterly_revenue_growth_yoy": _num(overview.get("QuarterlyRevenueGrowthYOY")),
    }


def compute_balance_sheet_metrics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    if not reports:
        return {"error": "no_data"}
    latest = reports[0]
    total_assets = _num(latest.get("totalAssets"))
    total_liabilities = _num(latest.get("totalLiabilities"))
    equity = _num(latest.get("totalShareholderEquity"))
    current_assets = _num(latest.get("totalCurrentAssets"))
    current_liabilities = _num(latest.get("totalCurrentLiabilities"))
    inventory = _num(latest.get("inventory"))

    current_ratio = _safe_div(current_assets, current_liabilities)
    quick_assets = (current_assets or 0) - (inventory or 0) if current_assets is not None else None
    da_values = [
        _safe_div(_num(row.get("totalLiabilities")), _num(row.get("totalAssets")))
        for row in reports[:4]
    ]

    return {
        "current_ratio": round(current_ratio, 2) if current_ratio is not None else None,
        "quick_ratio": round(_safe_div(quick_assets, current_liabilities), 2)
        if _safe_div(quick_assets, current_liabilities) is not None
        else None,
        "debt_to_equity": round(_safe_div(total_liabilities, equity), 2)
        if _safe_div(total_liabilities, equity) is not None
        else None,
        "debt_to_assets": round(_safe_div(total_liabilities, total_assets), 2)
        if _safe_div(total_liabilities, total_assets) is not None
        else None,
        "equity": equity,
        "equity_trend": _trend([_num(row.get("totalShareholderEquity")) for row in reports[:4]]),
        "da_trend": _trend(da_values),
        "cash": _num(latest.get("cashAndCashEquivalentsAtCarryingValue"))
        or _num(latest.get("cashAndShortTermInvestments")),
        "short_term_debt": _num(latest.get("shortTermDebt")),
        "long_term_debt": _num(latest.get("longTermDebt")),
        "shares_outstanding": _num(latest.get("commonStockSharesOutstanding")),
    }


def compute_cashflow_metrics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    if not reports:
        return {"error": "no_data"}
    latest = reports[0]
    ocf = _num(latest.get("operatingCashflow"))
    capex = _num(latest.get("capitalExpenditures"))
    net_income = _num(latest.get("netIncome"))
    fcf = ocf - abs(capex) if ocf is not None and capex is not None else None
    return {
        "ocf": ocf,
        "capex": capex,
        "fcf": fcf,
        "fcf_positive": fcf > 0 if fcf is not None else None,
        "ocf_vs_net_income": round(_safe_div(ocf, net_income), 2)
        if _safe_div(ocf, net_income) is not None
        else None,
        "ocf_trend": _trend([_num(row.get("operatingCashflow")) for row in reports[:4]]),
        "fcf_trend": _trend([
            _num(row.get("operatingCashflow")) - abs(_num(row.get("capitalExpenditures")))
            if _num(row.get("operatingCashflow")) is not None
            and _num(row.get("capitalExpenditures")) is not None
            else None
            for row in reports[:4]
        ]),
        "net_income": net_income,
    }


def compute_income_metrics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    if not reports:
        return {"error": "no_data"}
    latest = reports[0]
    revenue = _num(latest.get("totalRevenue"))
    gross_profit = _num(latest.get("grossProfit"))
    operating_income = _num(latest.get("operatingIncome"))
    net_income = _num(latest.get("netIncome"))
    ebitda = _num(latest.get("ebitda"))
    interest_expense = _num(latest.get("interestExpense"))
    rd_expense = _num(latest.get("researchAndDevelopment"))
    gross_margin = _safe_div(gross_profit, revenue)

    margin_values = [
        _safe_div(_num(row.get("grossProfit")), _num(row.get("totalRevenue")))
        for row in reports[:4]
    ]
    return {
        "revenue": revenue,
        "gross_profit": gross_profit,
        "operating_income": operating_income,
        "net_income": net_income,
        "ebitda": ebitda,
        "gross_margin": round(gross_margin, 4) if gross_margin is not None else None,
        "operating_margin": round(_safe_div(operating_income, revenue), 4)
        if _safe_div(operating_income, revenue) is not None
        else None,
        "net_margin": round(_safe_div(net_income, revenue), 4)
        if _safe_div(net_income, revenue) is not None
        else None,
        "rd_intensity": round(_safe_div(rd_expense, revenue), 4)
        if _safe_div(rd_expense, revenue) is not None
        else None,
        "interest_coverage": round(_safe_div(ebitda, interest_expense), 2)
        if interest_expense and interest_expense > 0 and _safe_div(ebitda, interest_expense) is not None
        else None,
        "revenue_trend": _trend([_num(row.get("totalRevenue")) for row in reports[:4]]),
        "revenue_growth_qoq": round(
            _pct_change(
                _num(reports[0].get("totalRevenue")) if len(reports) > 0 else None,
                _num(reports[1].get("totalRevenue")) if len(reports) > 1 else None,
            ),
            2,
        )
        if _pct_change(
            _num(reports[0].get("totalRevenue")) if len(reports) > 0 else None,
            _num(reports[1].get("totalRevenue")) if len(reports) > 1 else None,
        )
        is not None
        else None,
        "margin_trend": _trend(margin_values),
    }


def compute_piotroski_fscore(
    income: dict[str, Any],
    balance: dict[str, Any],
    cashflow: dict[str, Any],
    ratios: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "net_income_positive": None if income.get("net_income") is None else income["net_income"] > 0,
        "roa_positive": None if ratios.get("roa") is None else ratios["roa"] > 0,
        "fcf_positive": cashflow.get("fcf_positive"),
        "ocf_exceeds_net_income": None
        if cashflow.get("ocf") is None or cashflow.get("net_income") is None
        else cashflow["ocf"] > cashflow["net_income"],
        "da_decreasing": None if balance.get("da_trend") is None else balance["da_trend"] == "declining",
        "current_ratio_above_1": None
        if balance.get("current_ratio") is None
        else balance["current_ratio"] > 1.0,
        "no_dilution": None if balance.get("equity_trend") is None else balance["equity_trend"] != "declining",
        "gross_margin_improving": None
        if income.get("margin_trend") is None
        else income["margin_trend"] == "improving",
        "revenue_growing": None
        if income.get("revenue_trend") is None
        else income["revenue_trend"] == "improving",
    }
    return {
        "fscore": sum(1 for value in checks.values() if value is True),
        "criteria": checks,
        "missing_criteria": sum(1 for value in checks.values() if value is None),
    }


def _fiscal_period(ticker: str, balance_reports: list[dict[str, Any]]) -> dict[str, str] | None:
    if not balance_reports:
        return None
    fiscal_date_ending = balance_reports[0].get("fiscalDateEnding")
    if not fiscal_date_ending:
        return None
    from tradingagents.agents.utils.fiscal_calendar import resolve_fiscal_quarter

    resolved = resolve_fiscal_quarter(ticker or "", str(fiscal_date_ending))
    return {"fiscal_date_ending": str(fiscal_date_ending), **resolved}


def build_fundamental_snapshot(
    overview_json: Any,
    balance_sheet_json: Any,
    cashflow_json: Any,
    income_statement_json: Any,
    ticker: str = "",
) -> dict[str, Any]:
    overview = _parse_json(overview_json)
    balance_reports = _reports(balance_sheet_json)
    cashflow_reports = _reports(cashflow_json)
    income_reports = _reports(income_statement_json)

    ratios = compute_ratios(overview)
    balance = compute_balance_sheet_metrics(balance_reports)
    cashflow = compute_cashflow_metrics(cashflow_reports)
    income = compute_income_metrics(income_reports)
    piotroski = compute_piotroski_fscore(income, balance, cashflow, ratios)

    source_count = sum(
        [
            bool(overview),
            bool(balance_reports),
            bool(cashflow_reports),
            bool(income_reports),
        ]
    )
    resolved_ticker = ticker or str(overview.get("Symbol") or "")
    return {
        "ratios": ratios,
        "balance": balance,
        "cashflow": cashflow,
        "income": income,
        "piotroski": piotroski,
        "data_coverage": source_count / 4.0,
        "fiscal_period": _fiscal_period(resolved_ticker, balance_reports),
    }
