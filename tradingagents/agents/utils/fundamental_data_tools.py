from langchain_core.tools import tool
from typing import Annotated
import json
import os
from tradingagents.dataflows.interface import route_to_vendor


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    suffix = "\n\n[truncated by Aeternus payload guard]"
    trim_to = max(0, max_chars - len(suffix))
    return value[:trim_to] + suffix


def _limit_report_rows(rows, max_reports: int, max_fields: int):
    if not isinstance(rows, list):
        return rows
    prioritized_keys = [
        "fiscalDateEnding",
        "reportedCurrency",
        "totalRevenue",
        "grossProfit",
        "operatingIncome",
        "netIncome",
        "ebitda",
        "totalAssets",
        "totalLiabilities",
        "totalShareholderEquity",
        "operatingCashflow",
        "capitalExpenditures",
        "freeCashFlow",
    ]
    compact_rows = []
    for row in rows[: max(1, int(max_reports))]:
        if not isinstance(row, dict):
            compact_rows.append(row)
            continue

        compact_row = {}
        for key in prioritized_keys:
            if key in row and len(compact_row) < max_fields:
                compact_row[key] = row[key]
        if len(compact_row) < max_fields:
            for key, value in row.items():
                if key in compact_row:
                    continue
                compact_row[key] = value
                if len(compact_row) >= max_fields:
                    break
        compact_rows.append(compact_row)
    return compact_rows


def _compact_fundamental_payload(
    payload: str,
    *,
    max_chars: int = 12000,
    max_reports: int = 8,
    max_fields: int = 16,
) -> str:
    """Keep fundamental payloads bounded to avoid long-running analyze loops."""
    if not isinstance(payload, str):
        payload = str(payload)
    if len(payload) <= max_chars:
        return payload

    try:
        parsed = json.loads(payload)
    except Exception:
        return _truncate_text(payload, max_chars)

    if isinstance(parsed, dict):
        if "annualReports" in parsed:
            parsed["annualReports"] = _limit_report_rows(
                parsed.get("annualReports", []),
                max_reports=max_reports,
                max_fields=max_fields,
            )
        if "quarterlyReports" in parsed:
            parsed["quarterlyReports"] = _limit_report_rows(
                parsed.get("quarterlyReports", []),
                max_reports=max_reports,
                max_fields=max_fields,
            )

        compact = json.dumps(parsed, separators=(",", ":"))
        if len(compact) <= max_chars:
            return compact

        # Progressive tightening if the payload is still too large.
        for report_cap, field_cap in ((6, 12), (4, 10), (3, 8), (2, 8), (1, 6)):
            if "annualReports" in parsed:
                parsed["annualReports"] = _limit_report_rows(
                    parsed.get("annualReports", []),
                    max_reports=report_cap,
                    max_fields=field_cap,
                )
            if "quarterlyReports" in parsed:
                parsed["quarterlyReports"] = _limit_report_rows(
                    parsed.get("quarterlyReports", []),
                    max_reports=report_cap,
                    max_fields=field_cap,
                )
            compact = json.dumps(parsed, separators=(",", ":"))
            if len(compact) <= max_chars:
                return compact

        return _truncate_text(compact, max_chars)

    return _truncate_text(payload, max_chars)


def _guard_fundamental_payload(payload: str) -> str:
    max_chars = int(os.getenv("AETERNUS_MAX_FUNDAMENTAL_PAYLOAD_CHARS", "12000"))
    max_reports = int(os.getenv("AETERNUS_MAX_FUNDAMENTAL_REPORTS", "8"))
    max_fields = int(os.getenv("AETERNUS_MAX_FUNDAMENTAL_FIELDS_PER_REPORT", "16"))
    return _compact_fundamental_payload(
        payload,
        max_chars=max_chars,
        max_reports=max_reports,
        max_fields=max_fields,
    )


@tool
def get_fundamental_snapshot(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """
    Retrieve computed fundamental metrics for a given ticker symbol.
    Returns pre-computed ratios, balance sheet health, cash flow quality,
    income trends, and Piotroski F-Score — all calculated in Python from raw data.
    Args:
        ticker (str): Ticker symbol of the company
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: JSON with ratios, balance, cashflow, income, piotroski, data_coverage
    """
    from tradingagents.agents.utils.fundamental_engine import build_fundamental_snapshot

    overview = route_to_vendor("get_fundamentals", ticker, curr_date)
    balance_sheet = route_to_vendor("get_balance_sheet", ticker, "quarterly", curr_date)
    cashflow = route_to_vendor("get_cashflow", ticker, "quarterly", curr_date)
    income_stmt = route_to_vendor("get_income_statement", ticker, "quarterly", curr_date)

    snapshot = build_fundamental_snapshot(overview, balance_sheet, cashflow, income_stmt)
    return json.dumps(snapshot, default=str)


@tool
def get_valuation_context(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """
    Retrieve valuation context from yfinance for a given ticker symbol.
    Returns forward PE, P/B, EV/EBITDA, analyst target price, upside %, short ratio.
    Args:
        ticker (str): Ticker symbol of the company
    Returns:
        str: JSON with valuation metrics from yfinance
    """
    from tradingagents.agents.utils.fundamental_engine import compute_yfinance_snapshot
    from tradingagents.dataflows.y_finance import get_ticker_info

    info = get_ticker_info(ticker)
    snapshot = compute_yfinance_snapshot(info)
    return json.dumps(snapshot, default=str)


@tool
def get_fundamentals(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """
    Retrieve comprehensive fundamental data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing comprehensive fundamental data
    """
    payload = route_to_vendor("get_fundamentals", ticker, curr_date)
    return _guard_fundamental_payload(payload)


@tool
def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve balance sheet data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing balance sheet data
    """
    payload = route_to_vendor("get_balance_sheet", ticker, freq, curr_date)
    return _guard_fundamental_payload(payload)


@tool
def get_cashflow(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve cash flow statement data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing cash flow statement data
    """
    payload = route_to_vendor("get_cashflow", ticker, freq, curr_date)
    return _guard_fundamental_payload(payload)


@tool
def get_income_statement(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve income statement data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing income statement data
    """
    payload = route_to_vendor("get_income_statement", ticker, freq, curr_date)
    return _guard_fundamental_payload(payload)
