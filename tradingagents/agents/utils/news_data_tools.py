from langchain_core.tools import tool
from typing import Annotated, Optional
from tradingagents.dataflows.interface import route_to_vendor

# Suffixes that should bypass the global vendor chain and use a region-
# specific news source instead. Today only Indonesia is wired; if more
# regional sources land (e.g. .KS for Korea, .SS for Shanghai), add them
# here and route in get_news below.
_REGIONAL_NEWS_SUFFIXES = (".JK",)


@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Uses the configured news_data vendor for global tickers; .JK
    (Indonesia / IDX) tickers route to the Indonesian RSS aggregator
    (Detik Finance + Bisnis Indonesia) for better local coverage.

    Args:
        ticker (str): Ticker symbol (e.g. NVDA, BBCA.JK)
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    if ticker.upper().endswith(_REGIONAL_NEWS_SUFFIXES):
        # Lazy import: indonesia_news pulls in urllib + xml.etree at module
        # load — cheap, but worth keeping out of the import graph for
        # callers (e.g. test collection) that never touch .JK tickers.
        from tradingagents.dataflows.config import get_config
        from tradingagents.dataflows.indonesia_news import get_news_indonesia
        # Honor the user's news_article_limit knob — get_news_yfinance reads
        # the same key. Without this, .JK tickers always get 20 articles
        # regardless of config, which silently surprised the PR #17 reviewer.
        return get_news_indonesia(
            ticker, start_date, end_date,
            max_articles=get_config()["news_article_limit"],
        )
    return route_to_vendor("get_news", ticker, start_date, end_date)

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[Optional[int], "Days to look back; omit to use the configured default"] = None,
    limit: Annotated[Optional[int], "Max articles to return; omit to use the configured default"] = None,
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor. Defaults for look_back_days and
    limit come from DEFAULT_CONFIG (global_news_lookback_days,
    global_news_article_limit); pass explicit values to override.

    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back; omit to inherit config
        limit (int): Maximum number of articles to return; omit to inherit config

    Returns:
        str: A formatted string containing global news data
    """
    return route_to_vendor("get_global_news", curr_date, look_back_days, limit)

@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """
    Retrieve insider transaction information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
    Returns:
        str: A report of insider transaction data
    """
    return route_to_vendor("get_insider_transactions", ticker)
