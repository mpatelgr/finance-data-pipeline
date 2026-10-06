"""
Storage for dated fundamentals and analyst-target snapshots.
"""

from datetime import datetime, timedelta

FUNDAMENTAL_KEYS = [
    'sector', 'industry', 'market_cap', 'pe_ratio', 'forward_pe', 'peg_ratio',
    'dividend_yield', 'profit_margin', 'debt_to_equity', 'beta',
]
ANALYST_KEYS = ['target_mean', 'target_high', 'target_low', 'number_of_analysts']


def fundamentals_need_update(conn, ticker, max_age_hours=24, force=False):
    """
    Decide whether a ticker's fundamentals snapshot should be refreshed.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to the database.
    ticker : str
        Ticker symbol.
    max_age_hours : float, default 24
        A snapshot older than this counts as stale.
    force : bool, default False
        If True, always report that an update is needed.

    Returns
    -------
    bool
        True if force is set, no snapshot is stored, or the latest snapshot
        is older than max_age_hours.
    """
    if force:
        return True

    row = conn.execute(
        "SELECT MAX(fetched_at) FROM fundamentals_snapshot WHERE ticker = ?",
        (ticker,)
    ).fetchone()

    if row is None or row[0] is None:
        return True  # never fetched before

    age = datetime.now() - datetime.fromisoformat(row[0])
    return age > timedelta(hours=max_age_hours)


def save_fundamentals_snapshot(conn, ticker, fundamentals, analyst):
    """
    Store one dated fundamentals and analyst-target snapshot.

    Each call adds a new row, so repeated refreshes build a history instead
    of overwriting earlier values.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to the database.
    ticker : str
        Ticker symbol.
    fundamentals : dict
        Output of get_fundamentals.
    analyst : dict
        Output of get_analyst_view.

    Returns
    -------
    str
        The fetched_at timestamp the snapshot was stored under (ISO format).
    """
    fetched_at = datetime.now().isoformat()
    columns = ['ticker', 'fetched_at'] + FUNDAMENTAL_KEYS + ANALYST_KEYS
    values = (
        [ticker, fetched_at]
        + [fundamentals.get(k) for k in FUNDAMENTAL_KEYS]
        + [analyst.get(k) for k in ANALYST_KEYS]
    )
    placeholders = ', '.join('?' * len(columns))
    conn.execute(
        f"INSERT OR REPLACE INTO fundamentals_snapshot ({', '.join(columns)}) "
        f"VALUES ({placeholders})", values
    )
    conn.commit()
    return fetched_at


def load_latest_fundamentals(conn, ticker):
    """
    Read the most recent stored snapshot for a ticker.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to the database.
    ticker : str
        Ticker symbol.

    Returns
    -------
    tuple or None
        (fundamentals, analyst, fetched_at), where fundamentals and analyst
        are dicts shaped like the output of get_fundamentals and
        get_analyst_view. None if nothing is stored for this ticker.
    """
    keys = FUNDAMENTAL_KEYS + ANALYST_KEYS
    row = conn.execute(
        f"SELECT fetched_at, {', '.join(keys)} FROM fundamentals_snapshot "
        "WHERE ticker = ? ORDER BY fetched_at DESC LIMIT 1", (ticker,)
    ).fetchone()

    if row is None:
        return None

    values = dict(zip(keys, row[1:]))
    fundamentals = {k: values[k] for k in FUNDAMENTAL_KEYS}
    analyst = {k: values[k] for k in ANALYST_KEYS}
    return fundamentals, analyst, row[0]