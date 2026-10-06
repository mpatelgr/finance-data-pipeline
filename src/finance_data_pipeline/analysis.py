"""
Single-ticker research report.

Pulls together price history, technicals, fundamentals, and options context
for one ticker, to support (not replace) an investment decision. Nothing
here recommends buying or selling; it gathers the inputs a trader would
otherwise have to look up individually.
"""

import re
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf

from .prices import (
    DEFAULT_SOURCE, 
    update_ticker_data,
)

from .fundamentals import (
    fundamentals_need_update,
    load_latest_fundamentals,
    save_fundamentals_snapshot,
)


def _safe_get(d, key, default=None):
    """
    Look up a key in a dict-like object without raising if it is missing.

    Parameters
    ----------
    d : dict or None
        The dictionary to read from. A missing dict (None) is treated the
        same as a missing key.
    key : str
        Key to look up.
    default : any, optional
        Value to return if the key (or the dict itself) is missing.

    Returns
    -------
    any
        The stored value, or default.
    """
    if not d:
        return default
    return d.get(key, default)


def _period_start(period):
    """
    Convert a yfinance-style period string into a start date.

    Parameters
    ----------
    period : str
        History window such as "30d", "6mo", "2y", or "max".

    Returns
    -------
    str or None
        Start date as "YYYY-MM-DD", or None for "max" (no cutoff).

    Raises
    ------
    ValueError
        If period is not in a supported format.
    """
    if period == 'max':
        return None
    match = re.fullmatch(r'(\d+)(d|mo|y)', period)
    if not match:
        raise ValueError(
            f"Unsupported period '{period}'. Use e.g. '30d', '6mo', '2y', or 'max'."
        )
    days = {'d': 1, 'mo': 30, 'y': 365}[match.group(2)] * int(match.group(1))
    return (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')


def _price_data_live(ticker, period):
    """
    Fetch price history straight from yfinance, without touching the database.

    Parameters
    ----------
    ticker : str
        Ticker symbol.
    period : str
        History window passed to yfinance, e.g. "1y", "2y", "5y".

    Returns
    -------
    pd.DataFrame
        Price bars with a Date column, or an empty DataFrame if yfinance
        returned nothing.
    """
    price_data = yf.Ticker(ticker).history(period=period)

    # An incomplete current-day bar (market still open) can come back with a
    # NaN close; drop it so the latest real price is used instead.
    price_data = price_data.dropna(subset=['Close']) if not price_data.empty else price_data
    if price_data.empty:
        return price_data

    price_data = price_data.reset_index()
    # yfinance names the date index 'Date' for daily bars, but be explicit
    # rather than assuming, in case that ever differs.
    date_col = price_data.columns[0]
    if date_col != 'Date':
        price_data = price_data.rename(columns={date_col: 'Date'})
    return price_data


def _price_data_from_db(conn, ticker, period, force):
    """
    Refresh a ticker's stored prices if stale, then read them from the database.

    If the refresh fails (for example, no network), the existing stored
    data is used and a warning is printed.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to the database.
    ticker : str
        Ticker symbol.
    period : str
        History window, e.g. "30d", "6mo", "2y", or "max".
    force : bool
        If True, refresh regardless of freshness.

    Returns
    -------
    pd.DataFrame
        Price bars from load_price_data.
    """
    try:
        update_ticker_data(conn, ticker, force=force)
    except Exception as e:
        print(f"Could not refresh {ticker}, using stored data: {e}")
    return load_price_data(conn, ticker, period=period)


def _compute_technicals(price_data):
    """
    Compute trend, volatility, and drawdown stats from price bars.

    Parameters
    ----------
    price_data : pd.DataFrame
        Price bars with Date and Close columns. May be empty.

    Returns
    -------
    dict
        Keys: price_data (pd.DataFrame), current_price, sma_20, sma_50,
        trend, volatility_annualized, max_drawdown, 52wk_high, 52wk_low.
        Values are None if price_data is empty.
    """
    if price_data.empty:
        return {
            'price_data': price_data, 'current_price': None, 'sma_20': None,
            'sma_50': None, 'trend': None, 'volatility_annualized': None,
            'max_drawdown': None, '52wk_high': None, '52wk_low': None,
        }

    price_data = price_data.copy()
    price_data['daily_return'] = price_data['Close'].pct_change()
    price_data['SMA_20'] = price_data['Close'].rolling(20).mean()
    price_data['SMA_50'] = price_data['Close'].rolling(50).mean()

    cumulative_max = price_data['Close'].cummax()
    drawdown = (price_data['Close'] - cumulative_max) / cumulative_max

    sma_20 = price_data['SMA_20'].iloc[-1]
    sma_50 = price_data['SMA_50'].iloc[-1]
    trend = None
    if pd.notna(sma_20) and pd.notna(sma_50):
        trend = 'bullish' if sma_20 > sma_50 else 'bearish'

    return {
        'price_data': price_data,
        'current_price': price_data['Close'].iloc[-1],
        'sma_20': sma_20,
        'sma_50': sma_50,
        'trend': trend,
        'volatility_annualized': price_data['daily_return'].std() * (252 ** 0.5),
        'max_drawdown': drawdown.min(),
        '52wk_high': price_data['Close'].tail(252).max(),
        '52wk_low': price_data['Close'].tail(252).min(),
    }


def _fundamentals_from_db(conn, ticker, force):
    """
    Refresh a ticker's fundamentals snapshot if stale, then return the latest.

    If the refresh fails or yfinance returns no data, the most recent stored
    snapshot is used and a message is printed. Empty responses are never
    stored. If nothing is stored either, every value comes back as None.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to the database.
    ticker : str
        Ticker symbol.
    force : bool
        If True, refresh regardless of freshness.

    Returns
    -------
    tuple
        (fundamentals, analyst, fetched_at). fetched_at is an ISO timestamp,
        or None if no data was available.
    """
    if fundamentals_need_update(conn, ticker, force=force):
        try:
            info = yf.Ticker(ticker).info
            if not info:
                raise ValueError("yfinance returned no data")
            fundamentals = get_fundamentals(ticker, info=info)
            analyst = get_analyst_view(ticker, info=info)
            fetched_at = save_fundamentals_snapshot(conn, ticker, fundamentals, analyst)
            return fundamentals, analyst, fetched_at
        except Exception as e:
            print(f"Could not refresh fundamentals for {ticker}, using stored data: {e}")

    stored = load_latest_fundamentals(conn, ticker)
    if stored is None:
        return get_fundamentals(ticker, info={}), get_analyst_view(ticker, info={}), None
    return stored


def load_price_data(conn, ticker, period="2y", interval="1d",
                    source=DEFAULT_SOURCE):
    """
    Read stored price bars for one ticker from the database.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to the database.
    ticker : str
        Ticker symbol.
    period : str, default "2y"
        History window, e.g. "30d", "6mo", "2y", or "max".
    interval : str, default "1d"
        Bar size to load.
    source : str, default "yfinance"
        Data source to load.

    Returns
    -------
    pd.DataFrame
        Columns Date, Open, High, Low, Close, Volume, sorted by date. Empty
        if nothing is stored for this ticker, interval, and source.
    """
    query = (
        "SELECT datetime AS Date, Open, High, Low, Close, Volume "
        "FROM price_history WHERE ticker = ? AND interval = ? AND source = ?"
    )
    params = [ticker, interval, source]
    start = _period_start(period)
    if start:
        query += " AND datetime >= ?"
        params.append(start)
    query += " ORDER BY datetime"

    df = pd.read_sql_query(query, conn, params=params)
    df['Date'] = pd.to_datetime(df['Date'])
    return df


def get_price_technicals(ticker, period="2y", conn=None, force=False):
    """
    Get price history and compute trend, volatility, and drawdown stats.

    With a database connection, stale data is refreshed and the stats are
    computed from the stored prices. Without one, prices come live from
    yfinance.

    Parameters
    ----------
    ticker : str
        Ticker symbol, e.g. "AAPL".
    period : str, default "2y"
        History window, e.g. "1y", "2y", "5y".
    conn : sqlite3.Connection, optional
        Open database connection. If given, the database is used.
    force : bool, default False
        If True, refresh the database regardless of freshness. Ignored
        when conn is not given.

    Returns
    -------
    dict
        Keys: price_data (pd.DataFrame), current_price, sma_20, sma_50,
        trend, volatility_annualized, max_drawdown, 52wk_high, 52wk_low.
        Values are None if no price history was available.
    """
    if conn is not None:
        price_data = _price_data_from_db(conn, ticker, period, force)
    else:
        price_data = _price_data_live(ticker, period)
    return _compute_technicals(price_data)


def get_fundamentals(ticker, info=None):
    """
    Pull valuation, profitability, and sizing fundamentals for a ticker.

    Parameters
    ----------
    ticker : str
        Ticker symbol, e.g. "AAPL".
    info : dict, optional
        Pre-fetched yfinance info dict for this ticker. If not given, it is
        fetched here. Pass it in to avoid a duplicate network request when
        several functions need the same data.

    Returns
    -------
    dict
        Keys: sector, industry, market_cap, pe_ratio, forward_pe, peg_ratio,
        dividend_yield, profit_margin, debt_to_equity, beta. A key's value is
        None if yfinance does not report it for this ticker.
    """
    if info is None:
        info = yf.Ticker(ticker).info
    return {
        'sector': _safe_get(info, 'sector'),
        'industry': _safe_get(info, 'industry'),
        'market_cap': _safe_get(info, 'marketCap'),
        'pe_ratio': _safe_get(info, 'trailingPE'),
        'forward_pe': _safe_get(info, 'forwardPE'),
        'peg_ratio': _safe_get(info, 'pegRatio'),
        'dividend_yield': _safe_get(info, 'dividendYield'),
        'profit_margin': _safe_get(info, 'profitMargins'),
        'debt_to_equity': _safe_get(info, 'debtToEquity'),
        'beta': _safe_get(info, 'beta'),
    }


def get_analyst_view(ticker, info=None):
    """
    Pull analyst price targets for a ticker.

    Parameters
    ----------
    ticker : str
        Ticker symbol, e.g. "AAPL".
    info : dict, optional
        Pre-fetched yfinance info dict for this ticker. If not given, it is
        fetched here. Pass it in to avoid a duplicate network request when
        several functions need the same data.

    Returns
    -------
    dict
        Keys: target_mean, target_high, target_low, number_of_analysts.
        Values are None if yfinance does not report analyst targets for
        this ticker.
    """
    if info is None:
        info = yf.Ticker(ticker).info
    return {
        'target_mean': _safe_get(info, 'targetMeanPrice'),
        'target_high': _safe_get(info, 'targetHighPrice'),
        'target_low': _safe_get(info, 'targetLowPrice'),
        'number_of_analysts': _safe_get(info, 'numberOfAnalystOpinions'),
    }


def get_options_summary(ticker):
    """
    Summarize the nearest options expiration: implied volatility and the
    put-call volume ratio.

    Parameters
    ----------
    ticker : str
        Ticker symbol, e.g. "AAPL".

    Returns
    -------
    dict
        Keys: nearest_expiration, avg_call_iv, avg_put_iv, put_call_ratio.
        All values are None if the ticker has no listed options or the
        nearest chain has no volume.
    """
    stock = yf.Ticker(ticker)
    expirations = stock.options

    if not expirations:
        return {
            'nearest_expiration': None, 'avg_call_iv': None,
            'avg_put_iv': None, 'put_call_ratio': None,
        }

    nearest = expirations[0]
    chain = stock.option_chain(nearest)

    call_volume = chain.calls['volume'].sum()
    put_volume = chain.puts['volume'].sum()
    put_call_ratio = (put_volume / call_volume) if call_volume else None

    return {
        'nearest_expiration': nearest,
        'avg_call_iv': chain.calls['impliedVolatility'].mean(),
        'avg_put_iv': chain.puts['impliedVolatility'].mean(),
        'put_call_ratio': put_call_ratio,
    }


def analyze_stock(ticker, period="2y", conn=None, force=False):
    """
    Build a one-ticker research report: technicals, fundamentals, analyst
    view, and an options summary.

    With a database connection, prices and fundamentals are refreshed only
    when stale and otherwise read from the database. Options are always
    fetched live and never stored. Without a connection, everything is
    fetched live, with the yfinance info dict fetched once and shared by the
    fundamentals and analyst sections. This gathers the inputs a trader
    would otherwise look up individually. It does not score or recommend;
    forming a buy or sell judgment from these numbers is left to the person
    reading the report.

    Parameters
    ----------
    ticker : str
        Ticker symbol, e.g. "AAPL".
    period : str, default "2y"
        History window used for the technicals, e.g. "1y", "2y", "5y".
    conn : sqlite3.Connection, optional
        Open database connection. If given, prices and fundamentals use the
        database. If not, everything is fetched live.
    force : bool, default False
        If True, refresh stored prices and fundamentals regardless of
        freshness. Ignored when conn is not given.

    Returns
    -------
    dict
        Keys: ticker, technicals, fundamentals, analyst, options,
        fundamentals_as_of. The first five are dicts; see
        get_price_technicals, get_fundamentals, get_analyst_view, and
        get_options_summary. fundamentals_as_of is the ISO timestamp the
        fundamentals and analyst data were fetched, or None if they were
        fetched live or unavailable.
    """
    technicals = get_price_technicals(ticker, period=period, conn=conn, force=force)

    if conn is not None:
        fundamentals, analyst, as_of = _fundamentals_from_db(conn, ticker, force)
    else:
        info = yf.Ticker(ticker).info
        fundamentals = get_fundamentals(ticker, info=info)
        analyst = get_analyst_view(ticker, info=info)
        as_of = None

    return {
        'ticker': ticker,
        'technicals': technicals,
        'fundamentals': fundamentals,
        'analyst': analyst,
        'options': get_options_summary(ticker),
        'fundamentals_as_of': as_of,
    }


def plot_technicals(report, ax=None):
    """
    Plot price, moving averages, and 52-week high/low for an analyze_stock report.

    Parameters
    ----------
    report : dict
        Output of analyze_stock.
    ax : matplotlib.axes.Axes, optional
        Axes to draw on. A new figure and axes are created if not given.

    Returns
    -------
    matplotlib.axes.Axes or None
        The axes the chart was drawn on, or None if the report has no
        price history to plot.
    """
    price_data = report['technicals']['price_data']
    if price_data is None or price_data.empty:
        print(f"No price history available to plot for {report['ticker']}.")
        return None

    if ax is None:
        _, ax = plt.subplots(figsize=(10, 5))

    ax.plot(price_data['Date'], price_data['Close'], label='Close', color='black', linewidth=1.3)
    if 'SMA_20' in price_data:
        ax.plot(price_data['Date'], price_data['SMA_20'], label='SMA 20', linewidth=1)
    if 'SMA_50' in price_data:
        ax.plot(price_data['Date'], price_data['SMA_50'], label='SMA 50', linewidth=1)

    high = report['technicals']['52wk_high']
    low = report['technicals']['52wk_low']
    if high is not None:
        ax.axhline(high, color='green', linestyle='--', linewidth=1, label=f'52wk High (${high:.2f})')
    if low is not None:
        ax.axhline(low, color='red', linestyle='--', linewidth=1, label=f'52wk Low (${low:.2f})')

    ax.set_title(f"{report['ticker']} Price & Trend")
    ax.set_xlabel('Date')
    ax.set_ylabel('Price ($)')
    ax.legend()
    plt.tight_layout()
    return ax


def print_report(report):
    """
    Print an analyze_stock report in a readable, labeled format.

    Parameters
    ----------
    report : dict
        Output of analyze_stock.

    Returns
    -------
    None
    """
    t = report['technicals']
    f = report['fundamentals']
    a = report['analyst']
    o = report['options']

    as_of = report.get('fundamentals_as_of')
    label = f" (as of {as_of[:16].replace('T', ' ')})" if as_of else ""

    def fmt(value, kind='num'):
        """
        Format a report value as a display string.

        Parameters
        ----------
        value : float, int, str, or None
            Value to format. None and NaN are shown as "n/a".
        kind : {'num', 'pct', 'in_pct', 'money', 'big_money'}, default 'num'
            How to format the value. 'pct' treats value as a fraction and
            multiplies by 100 (0.25 becomes "25.00%"). 'in_pct' treats value as
            already in percentage points and only appends the sign. 'money'
            shows dollars with cents, and 'big_money' shows whole dollars.

        Returns
        -------
        str
            The formatted value.
        """
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "n/a"
        if kind == 'in_pct':
            return f"{value:,.2f}%"
        if kind == 'pct':
            return f"{value * 100:.2f}%"
        if kind == 'money':
            return f"${value:,.2f}"
        if kind == 'big_money':
            return f"${value:,.0f}"
        return f"{value:.2f}" if isinstance(value, float) else str(value)

    print(f"=== {report['ticker']} ===\n")

    print("--- Price & Trend ---")
    print(f"Current price:     {fmt(t['current_price'], 'money')}")
    print(f"52-week range:     {fmt(t['52wk_low'], 'money')} - {fmt(t['52wk_high'], 'money')}")
    print(f"20/50-day SMA:     {fmt(t['sma_20'], 'money')} / {fmt(t['sma_50'], 'money')}")
    print(f"Trend:             {t['trend'] or 'n/a'}")
    print(f"Ann. volatility:   {fmt(t['volatility_annualized'], 'pct')}")
    print(f"Max drawdown:      {fmt(t['max_drawdown'], 'pct')}")

    print(f"\n--- Fundamentals{label} ---")
    print(f"Sector / Industry: {f['sector'] or 'n/a'} / {f['industry'] or 'n/a'}")
    print(f"Market cap:        {fmt(f['market_cap'], 'big_money')}")
    print(f"P/E (trailing):    {fmt(f['pe_ratio'])}")
    print(f"P/E (forward):     {fmt(f['forward_pe'])}")
    print(f"PEG ratio:         {fmt(f['peg_ratio'])}")
    print(f"Dividend yield:    {fmt(f['dividend_yield'], 'in_pct')}")
    print(f"Profit margin:     {fmt(f['profit_margin'], 'pct')}")
    print(f"Debt / equity:     {fmt(f['debt_to_equity'])}")
    print(f"Beta:              {fmt(f['beta'])}")

    print(f"\n--- Analyst View{label} ---")
    print(f"Target (low/mean/high): "
          f"{fmt(a['target_low'], 'money')} / {fmt(a['target_mean'], 'money')} / "
          f"{fmt(a['target_high'], 'money')}")
    print(f"Number of analysts:     {a['number_of_analysts'] or 'n/a'}")

    print("\n--- Options (nearest expiration) ---")
    print(f"Expiration:        {o['nearest_expiration'] or 'n/a'}")
    print(f"Avg call IV:       {fmt(o['avg_call_iv'], 'pct')}")
    print(f"Avg put IV:        {fmt(o['avg_put_iv'], 'pct')}")
    print(f"Put/call ratio:    {fmt(o['put_call_ratio'])}")

