from typing import Annotated
from datetime import datetime
from dateutil.relativedelta import relativedelta
from .googlenews_utils import getNewsData

DATE_FMT = "%Y-%m-%d"


def _is_iso_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, DATE_FMT)
        return True
    except ValueError:
        return False


def get_google_news(
    query: Annotated[str, "Query to search with"],
    curr_date: Annotated[str, "Curr date in yyyy-mm-dd format OR start date when end date is passed as arg3"],
    look_back_days: Annotated[int, "how many days to look back OR end date string in yyyy-mm-dd"],
) -> str:
    # Compatibility note:
    # - Legacy call: get_google_news(query, curr_date, look_back_days:int)
    # - get_news fallback call: get_google_news(query, start_date, end_date)
    if _is_iso_date(curr_date) and _is_iso_date(look_back_days):
        start_str = curr_date
        end_str = look_back_days
    else:
        end_str = curr_date
        end_dt = datetime.strptime(end_str, DATE_FMT)
        lookback = int(look_back_days)
        start_dt = end_dt - relativedelta(days=lookback)
        start_str = start_dt.strftime(DATE_FMT)

    query = query.replace(" ", "+")

    news_results = getNewsData(query, start_str, end_str)

    news_str = ""

    for news in news_results:
        news_str += (
            f"### {news['title']} (source: {news['source']}) \n\n{news['snippet']}\n\n"
        )

    if len(news_results) == 0:
        return ""

    return f"## {query} Google News, from {start_str} to {end_str}:\n\n{news_str}"
