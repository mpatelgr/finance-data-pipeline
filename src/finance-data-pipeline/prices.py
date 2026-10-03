"""
Price fetching and freshness tracking.
"""

import time
from datetime import datetime, timedelta

import yfinance as yf

from .tickers import register_ticker

# Data sources the pipeline can fetch from. To add a provider, write a fetcher
# for it, then add its name here.
DEFAULT_SOURCE = 'yfinance'
SUPPORTED_SOURCES = ('yfinance',)

# Intervals that are daily or longer (these use start/end dates)
LONG_INTERVALS = ('1d', '1wk', '1mo')

# yfinance only serves limited history for intraday intervals, so these use
# a fixed period instead of a start date
INTRADAY_PERIODS = {
    '1m': '5d', '2m': '1mo', '5m': '1mo', '15m': '1mo',
    '30m': '1mo', '90m': '1mo', '60m': '1y',
}


def default_max_age(interval):
    """
    Return the default staleness threshold for an interval.

    Parameters
    ----------
    interval : str
        Bar size, e.g. "1d" or "5m".

    Returns
    -------
    float
        Hours before data counts as stale: 24 for daily or longer bars,
        0.5 for intraday bars.
    """
    return 24 if interval in LONG_INTERVALS else 0.5


def needs_update(conn, ticker, interval, max_age_hours, force=False,
                 source=DEFAULT_SOURCE):
    """
    Decide whether a ticker's data for a given interval and source should be refreshed.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to the database.
    ticker : str
        Ticker symbol.
    interval : str
        Bar size, e.g. "1d" or "5m".
    max_age_hours : float
        Data older than this counts as stale.
    force : bool, default False
        If True, always report that an update is needed.
    source : str, default "yfinance"
        Data source whose freshness is checked. Each source is tracked
        separately.

    Returns
    -------
    bool
        True if force is set, the ticker/interval/source was never pulled, or
        its last update is older than max_age_hours.
    """
    if force:
        return True

    row = conn.execute(
        "SELECT last_updated FROM update_log "
        "WHERE ticker = ? AND interval = ? AND source = ?",
        (ticker, interval, source)
    ).fetchone()

    if row is None:
        return True  # never pulled before

    age = datetime.now() - datetime.fromisoformat(row[0])
    return age > timedelta(hours=max_age_hours)


def update_ticker_data(conn, ticker, interval="1d", start="2000-01-01",
                       end=None, max_age_hours=None, force=False,
                       source=DEFAULT_SOURCE):
    """
    Fetch price history for one ticker and save it, unless it is still fresh.

    Rows are written with INSERT OR REPLACE, so re-pulling an overlapping date
    range overwrites matching bars instead of duplicating them. Also records
    the update time in update_log and registers the ticker in the masterlist.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to the database.
    ticker : str
        Ticker symbol.
    interval : str, default "1d"
        Bar size, e.g. "1d" or "5m". Intraday intervals ignore start and end
        and use the maximum history Yahoo allows (see INTRADAY_PERIODS).
    start : str, default "2000-01-01"
        First date to fetch, "YYYY-MM-DD". Daily or longer intervals only.
    end : str, optional
        Last date to fetch (exclusive). Defaults to now.
    max_age_hours : float, optional
        Hours before stored data counts as stale. Defaults to 24 for daily
        bars and 0.5 for intraday.
    force : bool, default False
        If True, fetch regardless of freshness.
    source : str, default "yfinance"
        Data source label stored with every row, so data from different
        providers never overwrites each other. Must be in SUPPORTED_SOURCES.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If source is not in SUPPORTED_SOURCES.
    """
    if source not in SUPPORTED_SOURCES:
        raise ValueError(f"Unsupported source '{source}'. Supported: {SUPPORTED_SOURCES}")

    if max_age_hours is None:
        max_age_hours = default_max_age(interval)

    if not needs_update(conn, ticker, interval, max_age_hours, force, source):
        print(f"{ticker} ({interval}) is fresh, skipping.")
        return

    print(f"Fetching {ticker} ({interval})...")
    stock = yf.Ticker(ticker)
    if interval in INTRADAY_PERIODS:
        df = stock.history(period=INTRADAY_PERIODS[interval], interval=interval)
    else:
        df = stock.history(start=start, end=end, interval=interval)

    # An invalid symbol returns an empty table with no columns, so check first
    if df.empty or 'Close' not in df.columns:
        print(f"No data returned for {ticker} ({interval}).")
        return

    df = df.dropna(subset=['Close'])
    if df.empty:
        print(f"No data returned for {ticker} ({interval}).")
        return

    fmt = '%Y-%m-%d' if interval in LONG_INTERVALS else '%Y-%m-%d %H:%M:%S%z'
    df['datetime'] = df.index.strftime(fmt)
    df['ticker'] = ticker
    df['interval'] = interval
    df['source'] = source

    cols = ['ticker', 'interval', 'source', 'datetime',
            'Open', 'High', 'Low', 'Close', 'Volume']
    rows = df[cols].astype(object).values.tolist()

    # INSERT OR REPLACE: on a primary key clash, the old row is overwritten
    conn.executemany(
        "INSERT OR REPLACE INTO price_history "
        "(ticker, interval, source, datetime, Open, High, Low, Close, Volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )
    conn.execute(
        "INSERT OR REPLACE INTO update_log (ticker, interval, source, last_updated) "
        "VALUES (?, ?, ?, ?)",
        (ticker, interval, source, datetime.now().isoformat())
    )
    register_ticker(conn, ticker)  # make sure it is in the masterlist
    conn.commit()


def update_many(conn, tickers, interval="1d", force=False, delay=0.5,
                source=DEFAULT_SOURCE):
    """
    Run update_ticker_data for a list of tickers, continuing past failures.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to the database.
    tickers : list of str
        Ticker symbols to update.
    interval : str, default "1d"
        Bar size passed to update_ticker_data.
    force : bool, default False
        If True, ignore freshness checks.
    delay : float, default 0.5
        Seconds to pause between tickers to avoid provider rate limiting.
    source : str, default "yfinance"
        Data source passed to update_ticker_data.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If source is not in SUPPORTED_SOURCES.
    """
    if source not in SUPPORTED_SOURCES:
        raise ValueError(f"Unsupported source '{source}'. Supported: {SUPPORTED_SOURCES}")

    for ticker in tickers:
        try:
            update_ticker_data(conn, ticker, interval=interval, force=force,
                               source=source)
        except Exception as e:
            print(f"Skipped {ticker}: {e}")
        time.sleep(delay)
