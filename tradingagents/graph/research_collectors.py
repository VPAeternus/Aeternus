"""Research collectors — pre-fetch vendor data with quality metadata.

Each collector calls the same route_to_vendor() functions the analysts use,
wraps in try/except for graceful degradation, and returns quality metadata
so analysts can assess data quality before writing reports.
"""

import json
import logging
from datetime import datetime, timedelta

from tradingagents.dataflows.interface import route_to_vendor

logger = logging.getLogger(__name__)

STANDARD_INDICATORS = [
    "close_50_sma", "close_200_sma", "macd", "macds",
    "rsi", "boll_ub", "boll_lb", "atr",
]


def collect_market_data(ticker: str, trade_date: str) -> dict:
    """Collect OHLCV price data and technical indicators for a ticker."""
    errors = []
    start_date = (
        datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=60)
    ).strftime("%Y-%m-%d")

    # Price data
    price_data = ""
    price_rows = 0
    try:
        raw = route_to_vendor("get_stock_data", ticker, start_date, trade_date)
        price_data = str(raw) if raw else ""
        if price_data:
            price_rows = price_data.count("\n")
    except Exception as e:
        errors.append(f"price: {e}")

    # Technical indicators
    indicators = {}
    indicators_missing = []
    for ind in STANDARD_INDICATORS:
        try:
            raw = route_to_vendor("get_indicators", ticker, ind, trade_date, 30)
            if raw:
                indicators[ind] = str(raw)
            else:
                indicators_missing.append(ind)
        except Exception:
            indicators_missing.append(ind)

    return {
        "price_data": price_data,
        "indicators": indicators,
        "quality": {
            "price_rows": price_rows,
            "indicators_fetched": len(indicators),
            "indicators_missing": indicators_missing,
            "fetch_errors": errors,
        },
    }


def collect_news_data(ticker: str, trade_date: str) -> dict:
    """Collect company and global news for a ticker."""
    errors = []
    start_date = (
        datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)
    ).strftime("%Y-%m-%d")

    company_news = ""
    try:
        raw = route_to_vendor("get_news", ticker, start_date, trade_date)
        company_news = str(raw) if raw else ""
    except Exception as e:
        errors.append(f"company_news: {e}")

    global_news = ""
    try:
        raw = route_to_vendor("get_global_news", trade_date, 7, 5)
        global_news = str(raw) if raw else ""
    except Exception as e:
        errors.append(f"global_news: {e}")

    return {
        "company_news": company_news,
        "global_news": global_news,
        "quality": {
            "company_news_chars": len(company_news),
            "global_news_chars": len(global_news),
            "company_news_available": bool(company_news.strip()),
            "global_news_available": bool(global_news.strip()),
            "fetch_errors": errors,
        },
    }


def collect_fundamentals_data(ticker: str, trade_date: str) -> dict:
    """Collect fundamental snapshot and valuation context for a ticker."""
    from tradingagents.agents.utils.fundamental_data_tools import _guard_fundamental_payload
    from tradingagents.agents.utils.fundamental_engine import (
        build_fundamental_snapshot,
        compute_yfinance_snapshot,
    )
    from tradingagents.dataflows.y_finance import get_ticker_info

    errors = []

    # Fundamental snapshot (same logic as get_fundamental_snapshot tool)
    snapshot = ""
    data_coverage = 0.0
    piotroski_available = False
    try:
        overview = route_to_vendor("get_fundamentals", ticker, trade_date)
        balance_sheet = route_to_vendor("get_balance_sheet", ticker, "quarterly", trade_date)
        cashflow = route_to_vendor("get_cashflow", ticker, "quarterly", trade_date)
        income_stmt = route_to_vendor("get_income_statement", ticker, "quarterly", trade_date)
        snap = build_fundamental_snapshot(overview, balance_sheet, cashflow, income_stmt)
        data_coverage = snap.get("data_coverage", 0.0)
        piotroski_available = snap.get("piotroski", {}).get("fscore") is not None
        snapshot = _guard_fundamental_payload(json.dumps(snap, default=str))
    except Exception as e:
        errors.append(f"snapshot: {e}")

    # Valuation context (same logic as get_valuation_context tool)
    valuation = ""
    valuation_fields = 0
    try:
        info = get_ticker_info(ticker)
        val = compute_yfinance_snapshot(info)
        valuation_fields = sum(1 for v in val.values() if v is not None)
        valuation = json.dumps(val, default=str)
    except Exception as e:
        errors.append(f"valuation: {e}")

    return {
        "snapshot": snapshot,
        "valuation": valuation,
        "quality": {
            "data_coverage": data_coverage,
            "piotroski_available": piotroski_available,
            "valuation_fields": valuation_fields,
            "fetch_errors": errors,
        },
    }
