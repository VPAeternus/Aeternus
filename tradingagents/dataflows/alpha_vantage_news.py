from .alpha_vantage_common import _make_api_request, format_datetime_for_api

def get_news(ticker, start_date, end_date) -> dict[str, str] | str:
    """Returns live and historical market news & sentiment data from premier news outlets worldwide.

    Covers stocks, cryptocurrencies, forex, and topics like fiscal policy, mergers & acquisitions, IPOs.

    Args:
        ticker: Stock symbol for news articles.
        start_date: Start date for news search.
        end_date: End date for news search.

    Returns:
        Dictionary containing news sentiment data or JSON string.
    """

    params = {
        "tickers": ticker,
        "time_from": format_datetime_for_api(start_date),
        "time_to": format_datetime_for_api(end_date),
        "sort": "LATEST",
        "limit": "50",
    }
    
    return _make_api_request("NEWS_SENTIMENT", params)

def get_insider_transactions(symbol: str) -> dict[str, str] | str:
    """Returns latest and historical insider transactions by key stakeholders.

    Covers transactions by founders, executives, board members, etc.

    Args:
        symbol: Ticker symbol. Example: "IBM".

    Returns:
        Dictionary containing insider transaction data or JSON string.
    """

    params = {
        "symbol": symbol,
    }

    return _make_api_request("INSIDER_TRANSACTIONS", params)

def get_global_news(curr_date: str, look_back_days: int = 7, limit: int = 5) -> dict[str, str] | str:
    """Returns global/macro news and sentiment data.
    
    Args:
        curr_date: Current date in yyyy-mm-dd format.
        look_back_days: Number of days to look back.
        limit: Maximum number of articles to return.
        
    Returns:
        News sentiment data.
    """
    from datetime import datetime
    from dateutil.relativedelta import relativedelta
    
    date_obj = datetime.strptime(curr_date, "%Y-%m-%d")
    before = date_obj - relativedelta(days=look_back_days)
    
    params = {
        "time_from": format_datetime_for_api(before.strftime("%Y-%m-%d")),
        "time_to": format_datetime_for_api(curr_date),
        "sort": "LATEST",
        "limit": str(limit),
    }
    
    return _make_api_request("NEWS_SENTIMENT", params)