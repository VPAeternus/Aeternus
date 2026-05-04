"""Pure Python fundamental analysis computation engine.

No LLM calls, no network calls. Functions accept parsed dict inputs
(Alpha Vantage JSON payloads) and return typed dicts.
"""

from typing import Any, Dict, List, Optional


def _num(value: Any) -> Optional[float]:
    """Parse an Alpha Vantage string value to float, returning None for missing/invalid."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in ("none", "n/a", "-", ""):
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """Safe division returning None if inputs are missing or denominator is zero."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """Compute percentage change, returning None if inputs are missing."""
    if current is None or previous is None or previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100


def _trend(values: List[Optional[float]]) -> Optional[str]:
    """Classify trend from a list of values (most recent first).

    Returns 'improving', 'declining', 'stable', or None if insufficient data.
    """
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return None
    # Compare most recent to oldest
    diff = clean[0] - clean[-1]
    threshold = abs(clean[-1]) * 0.02 if clean[-1] != 0 else 0.01
    if diff > threshold:
        return "improving"
    if diff < -threshold:
        return "declining"
    return "stable"


def compute_ratios(overview: Dict[str, Any]) -> Dict[str, Any]:
    """Compute valuation and profitability ratios from AV OVERVIEW dict."""
    pe = _num(overview.get("PERatio"))
    peg = _num(overview.get("PEGRatio"))
    ev_ebitda = _num(overview.get("EVToEBITDA"))
    roe = _num(overview.get("ReturnOnEquityTTM"))
    roa = _num(overview.get("ReturnOnAssetsTTM"))
    gross_margin = _num(overview.get("GrossProfitTTM"))
    revenue_ttm = _num(overview.get("RevenueTTM"))
    operating_margin = _num(overview.get("OperatingMarginTTM"))
    profit_margin = _num(overview.get("ProfitMargin"))
    beta = _num(overview.get("Beta"))
    eps = _num(overview.get("EPS"))
    forward_pe = _num(overview.get("ForwardPE"))
    price_to_book = _num(overview.get("PriceToBookRatio"))
    dividend_yield = _num(overview.get("DividendYield"))
    quarterly_earnings_growth = _num(overview.get("QuarterlyEarningsGrowthYOY"))
    quarterly_revenue_growth = _num(overview.get("QuarterlyRevenueGrowthYOY"))

    # Compute gross margin ratio if raw values present
    gross_margin_ratio = _safe_div(gross_margin, revenue_ttm)

    return {
        "pe": pe,
        "forward_pe": forward_pe,
        "peg": peg,
        "ev_ebitda": ev_ebitda,
        "price_to_book": price_to_book,
        "roe": roe,
        "roa": roa,
        "gross_margin_ratio": gross_margin_ratio,
        "operating_margin": operating_margin,
        "profit_margin": profit_margin,
        "beta": beta,
        "eps": eps,
        "dividend_yield": dividend_yield,
        "quarterly_earnings_growth_yoy": quarterly_earnings_growth,
        "quarterly_revenue_growth_yoy": quarterly_revenue_growth,
    }


def compute_balance_sheet_metrics(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute balance sheet metrics from AV quarterlyReports list."""
    if not reports:
        return {"error": "no_data"}

    latest = reports[0]

    total_assets = _num(latest.get("totalAssets"))
    total_liabilities = _num(latest.get("totalLiabilities"))
    equity = _num(latest.get("totalShareholderEquity"))
    current_assets = _num(latest.get("totalCurrentAssets"))
    current_liabilities = _num(latest.get("totalCurrentLiabilities"))
    inventory = _num(latest.get("inventory"))
    cash = _num(latest.get("cashAndCashEquivalentsAtCarryingValue"))
    if cash is None:
        cash = _num(latest.get("cashAndShortTermInvestments"))
    short_term_debt = _num(latest.get("shortTermDebt"))
    long_term_debt = _num(latest.get("longTermDebt"))
    shares = _num(latest.get("commonStockSharesOutstanding"))

    current_ratio = _safe_div(current_assets, current_liabilities)
    quick_assets = (current_assets or 0) - (inventory or 0) if current_assets is not None else None
    quick_ratio = _safe_div(quick_assets, current_liabilities)
    debt_to_equity = _safe_div(total_liabilities, equity)
    debt_to_assets = _safe_div(total_liabilities, total_assets)

    # Equity trend across quarters
    equity_values = [_num(r.get("totalShareholderEquity")) for r in reports[:4]]
    equity_trend = _trend(equity_values)

    # Debt-to-assets trend
    da_values = []
    for r in reports[:4]:
        ta = _num(r.get("totalAssets"))
        tl = _num(r.get("totalLiabilities"))
        da_values.append(_safe_div(tl, ta))
    da_trend = _trend(da_values)

    return {
        "current_ratio": round(current_ratio, 2) if current_ratio is not None else None,
        "quick_ratio": round(quick_ratio, 2) if quick_ratio is not None else None,
        "debt_to_equity": round(debt_to_equity, 2) if debt_to_equity is not None else None,
        "debt_to_assets": round(debt_to_assets, 2) if debt_to_assets is not None else None,
        "equity": equity,
        "equity_trend": equity_trend,
        "da_trend": da_trend,
        "cash": cash,
        "short_term_debt": short_term_debt,
        "long_term_debt": long_term_debt,
        "shares_outstanding": shares,
    }


def compute_cashflow_metrics(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute cash flow metrics from AV quarterlyReports list."""
    if not reports:
        return {"error": "no_data"}

    latest = reports[0]

    ocf = _num(latest.get("operatingCashflow"))
    capex = _num(latest.get("capitalExpenditures"))
    net_income = _num(latest.get("netIncome"))

    # FCF = OCF - |capex| (capex is sometimes negative in AV data)
    fcf = None
    if ocf is not None and capex is not None:
        fcf = ocf - abs(capex)

    fcf_positive = fcf > 0 if fcf is not None else None
    ocf_vs_ni = _safe_div(ocf, net_income) if net_income and net_income != 0 else None

    # OCF trend across quarters
    ocf_values = [_num(r.get("operatingCashflow")) for r in reports[:4]]
    ocf_trend = _trend(ocf_values)

    # FCF trend
    fcf_values = []
    for r in reports[:4]:
        r_ocf = _num(r.get("operatingCashflow"))
        r_capex = _num(r.get("capitalExpenditures"))
        if r_ocf is not None and r_capex is not None:
            fcf_values.append(r_ocf - abs(r_capex))
        else:
            fcf_values.append(None)
    fcf_trend = _trend(fcf_values)

    return {
        "ocf": ocf,
        "capex": capex,
        "fcf": fcf,
        "fcf_positive": fcf_positive,
        "ocf_vs_net_income": round(ocf_vs_ni, 2) if ocf_vs_ni is not None else None,
        "ocf_trend": ocf_trend,
        "fcf_trend": fcf_trend,
        "net_income": net_income,
    }


def compute_income_metrics(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute income statement metrics from AV quarterlyReports list."""
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
    operating_margin = _safe_div(operating_income, revenue)
    net_margin = _safe_div(net_income, revenue)
    rd_intensity = _safe_div(rd_expense, revenue)
    interest_coverage = _safe_div(ebitda, interest_expense) if interest_expense and interest_expense > 0 else None

    # Revenue trend
    rev_values = [_num(r.get("totalRevenue")) for r in reports[:4]]
    revenue_trend = _trend(rev_values)

    # Revenue growth (most recent vs prior quarter)
    rev_growth = _pct_change(
        _num(reports[0].get("totalRevenue")) if len(reports) > 0 else None,
        _num(reports[1].get("totalRevenue")) if len(reports) > 1 else None,
    )

    # Gross margin trend
    gm_values = []
    for r in reports[:4]:
        gp = _num(r.get("grossProfit"))
        rv = _num(r.get("totalRevenue"))
        gm_values.append(_safe_div(gp, rv))
    margin_trend = _trend(gm_values)

    return {
        "revenue": revenue,
        "gross_profit": gross_profit,
        "operating_income": operating_income,
        "net_income": net_income,
        "ebitda": ebitda,
        "gross_margin": round(gross_margin, 4) if gross_margin is not None else None,
        "operating_margin": round(operating_margin, 4) if operating_margin is not None else None,
        "net_margin": round(net_margin, 4) if net_margin is not None else None,
        "rd_intensity": round(rd_intensity, 4) if rd_intensity is not None else None,
        "interest_coverage": round(interest_coverage, 2) if interest_coverage is not None else None,
        "revenue_trend": revenue_trend,
        "revenue_growth_qoq": round(rev_growth, 2) if rev_growth is not None else None,
        "margin_trend": margin_trend,
    }


def compute_piotroski_fscore(
    income: Dict[str, Any],
    balance: Dict[str, Any],
    cashflow: Dict[str, Any],
    ratios: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute Piotroski F-Score (0-9) from computed metrics.

    Criteria:
      Profitability (4): net income > 0, ROA > 0, FCF > 0, OCF > net income
      Leverage (3): D/A decreasing, current ratio > 1.0, no dilution (shares stable/decreasing)
      Efficiency (2): gross margin improving, revenue growing
    """
    criteria = {}
    missing = 0

    # --- Profitability ---
    ni = income.get("net_income")
    if ni is not None:
        criteria["net_income_positive"] = ni > 0
    else:
        criteria["net_income_positive"] = None
        missing += 1

    roa = ratios.get("roa")
    if roa is not None:
        criteria["roa_positive"] = roa > 0
    else:
        criteria["roa_positive"] = None
        missing += 1

    fcf_pos = cashflow.get("fcf_positive")
    if fcf_pos is not None:
        criteria["fcf_positive"] = fcf_pos
    else:
        criteria["fcf_positive"] = None
        missing += 1

    ocf = cashflow.get("ocf")
    cf_ni = cashflow.get("net_income")
    if ocf is not None and cf_ni is not None:
        criteria["ocf_exceeds_net_income"] = ocf > cf_ni
    else:
        criteria["ocf_exceeds_net_income"] = None
        missing += 1

    # --- Leverage ---
    da_trend = balance.get("da_trend")
    if da_trend is not None:
        criteria["da_decreasing"] = da_trend == "declining"
    else:
        criteria["da_decreasing"] = None
        missing += 1

    cr = balance.get("current_ratio")
    if cr is not None:
        criteria["current_ratio_above_1"] = cr > 1.0
    else:
        criteria["current_ratio_above_1"] = None
        missing += 1

    # No dilution: shares outstanding not increasing — approximate via equity trend
    eq_trend = balance.get("equity_trend")
    if eq_trend is not None:
        criteria["no_dilution"] = eq_trend != "declining"
    else:
        criteria["no_dilution"] = None
        missing += 1

    # --- Efficiency ---
    margin_trend = income.get("margin_trend")
    if margin_trend is not None:
        criteria["gross_margin_improving"] = margin_trend == "improving"
    else:
        criteria["gross_margin_improving"] = None
        missing += 1

    rev_trend = income.get("revenue_trend")
    if rev_trend is not None:
        criteria["revenue_growing"] = rev_trend == "improving"
    else:
        criteria["revenue_growing"] = None
        missing += 1

    # Compute score (count True values, skip None)
    score = sum(1 for v in criteria.values() if v is True)

    return {
        "fscore": score,
        "criteria": criteria,
        "missing_criteria": missing,
    }


def compute_yfinance_snapshot(info: Dict[str, Any]) -> Dict[str, Any]:
    """Compute valuation snapshot from yfinance Ticker.info dict."""
    if not info:
        return {"error": "no_data"}

    forward_pe = _num(info.get("forwardPE"))
    price_to_book = _num(info.get("priceToBook"))
    ev_ebitda = _num(info.get("enterpriseToEbitda"))
    target_mean = _num(info.get("targetMeanPrice"))
    current_price = _num(info.get("currentPrice"))
    short_ratio = _num(info.get("shortRatio"))
    recommendation = info.get("recommendationKey")

    upside_pct = _pct_change(target_mean, current_price) if target_mean and current_price else None

    return {
        "forward_pe": round(forward_pe, 2) if forward_pe is not None else None,
        "price_to_book": round(price_to_book, 2) if price_to_book is not None else None,
        "ev_ebitda": round(ev_ebitda, 2) if ev_ebitda is not None else None,
        "analyst_target": target_mean,
        "current_price": current_price,
        "upside_pct": round(upside_pct, 2) if upside_pct is not None else None,
        "short_ratio": round(short_ratio, 2) if short_ratio is not None else None,
        "recommendation": recommendation,
    }


def build_fundamental_snapshot(
    overview_json: str,
    balance_sheet_json: str,
    cashflow_json: str,
    income_statement_json: str,
) -> Dict[str, Any]:
    """Build combined fundamental snapshot from 4 AV JSON strings.

    Returns a dict with: ratios, balance, cashflow, income, piotroski, data_coverage.
    """
    import json

    def _parse(raw: str) -> dict:
        if not raw or not isinstance(raw, str):
            return {}
        try:
            result = json.loads(raw)
            return result if isinstance(result, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    overview = _parse(overview_json)
    bs_data = _parse(balance_sheet_json)
    cf_data = _parse(cashflow_json)
    is_data = _parse(income_statement_json)

    # Extract quarterly reports
    bs_reports = bs_data.get("quarterlyReports", [])
    cf_reports = cf_data.get("quarterlyReports", [])
    is_reports = is_data.get("quarterlyReports", [])

    ratios = compute_ratios(overview)
    balance = compute_balance_sheet_metrics(bs_reports)
    cashflow = compute_cashflow_metrics(cf_reports)
    income = compute_income_metrics(is_reports)
    piotroski = compute_piotroski_fscore(income, balance, cashflow, ratios)

    # Data coverage: count non-None values across all sections
    all_values = []
    for section in (ratios, balance, cashflow, income):
        for v in section.values():
            if isinstance(v, str) and v in ("improving", "declining", "stable"):
                all_values.append(True)
            elif v is not None and v != "no_data":
                all_values.append(True)
            else:
                all_values.append(False)

    total = len(all_values)
    present = sum(all_values)
    coverage = round(present / total, 2) if total > 0 else 0

    # Extract fiscal period metadata from first balance sheet report
    fiscal_period = None
    if bs_reports:
        fde = bs_reports[0].get("fiscalDateEnding")
        if fde and isinstance(fde, str) and len(fde) >= 10:
            fiscal_period = {"fiscal_date_ending": fde}

    return {
        "ratios": ratios,
        "balance": balance,
        "cashflow": cashflow,
        "income": income,
        "piotroski": piotroski,
        "data_coverage": coverage,
        "fiscal_period": fiscal_period,
    }
