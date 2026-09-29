"""
Database schema setup for the finance data pipeline.

Tables
------
tickers        : masterlist registry of every ticker the project knows about
update_log     : when each (ticker, interval, source) was last refreshed
price_history  : price bars, one row per ticker, interval, source, and timestamp

Views
-----
masterlist     : tickers joined to update_log, one row per ticker
"""


def init_db(conn):
    """
    Create the database tables and the masterlist view.

    Safe to run every session. Tables are only created if missing, and the
    masterlist view is rebuilt each time so its definition stays current.
    Existing tables are never altered, so a database created before the
    source column was added needs update_log and price_history dropped first.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to the database.

    Returns
    -------
    None
    """
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS tickers (
        ticker TEXT PRIMARY KEY,
        company_name TEXT,
        sector TEXT,
        added_at TEXT
    );

    CREATE TABLE IF NOT EXISTS update_log (
        ticker TEXT,
        interval TEXT,
        source TEXT,
        last_updated TEXT,
        PRIMARY KEY (ticker, interval, source)
    );

    CREATE TABLE IF NOT EXISTS price_history (
        ticker TEXT,
        interval TEXT,
        source TEXT,
        datetime TEXT,
        Open REAL, High REAL, Low REAL, Close REAL, Volume INTEGER,
        PRIMARY KEY (ticker, interval, source, datetime)
    );

    DROP VIEW IF EXISTS masterlist;
    CREATE VIEW masterlist AS
    SELECT t.ticker, t.company_name, t.sector,
           GROUP_CONCAT(DISTINCT u.interval) AS intervals_stored,
           GROUP_CONCAT(DISTINCT u.source) AS sources_stored,
           MAX(u.last_updated) AS last_updated
    FROM tickers t
    LEFT JOIN update_log u ON t.ticker = u.ticker
    GROUP BY t.ticker;
    """)
    conn.commit()
