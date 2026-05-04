from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor

@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    return route_to_vendor("get_news", ticker, start_date, end_date)

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of days to look back"] = 7,
    limit: Annotated[int, "Maximum number of articles to return"] = 5,
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor.
    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back (default 7)
        limit (int): Maximum number of articles to return (default 5)
    Returns:
        str: A formatted string containing global news data
    """
    return route_to_vendor("get_global_news", curr_date, look_back_days, limit)

@tool
def get_insider_sentiment(
    ticker: Annotated[str, "ticker symbol for the company"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """
    Retrieve insider sentiment information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A report of insider sentiment data
    """
    return route_to_vendor("get_insider_sentiment", ticker, curr_date)

@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """
    Retrieve insider transaction information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A report of insider transaction data
    """
    return route_to_vendor("get_insider_transactions", ticker, curr_date)


@tool
def get_sentiment_snapshot(
    ticker: Annotated[str, "Ticker symbol"],
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
) -> str:
    """Compute structured sentiment metrics from AV NEWS_SENTIMENT + xAI social data.

    Returns JSON with av_sentiment scores, text sentiment analysis,
    buzz metrics, composite score, and direction.
    """
    import json
    from datetime import datetime, timedelta

    start_date = (datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")

    # Get AV news data
    av_raw = ""
    try:
        av_raw = route_to_vendor("get_news", ticker, start_date, curr_date)
    except Exception:
        pass

    # Get xAI social data (separate query for social/X content)
    xai_raw = ""
    try:
        xai_raw = route_to_vendor("get_news", f"${ticker} social media sentiment", start_date, curr_date)
    except Exception:
        pass

    from tradingagents.agents.utils.sentiment_engine import build_sentiment_snapshot
    snapshot = build_sentiment_snapshot(av_raw or "", xai_raw or "", ticker)
    return json.dumps(snapshot, indent=2)


@tool
def get_social_sentiment(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Retrieve social media and X.com sentiment narrative via news vendors.

    Returns social media discussion, sentiment narrative, and catalyst/risk callouts.
    """
    try:
        result = route_to_vendor("get_news", f"${ticker} X.com twitter social media sentiment", start_date, end_date)
        return str(result or "No social sentiment data available.")
    except Exception:
        return "Social sentiment data unavailable."
