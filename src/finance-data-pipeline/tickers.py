"""
Ticker registry: standardizing, loading, and updating the tickers table.
"""

from datetime import datetime

import pandas as pd

STANDARD_COLUMNS = ['ticker', 'company_name', 'sector']


def register_ticker(conn, ticker, company_name=None, sector=None):
    """
    Add a ticker to the tickers table, or fill in its missing details.

    If the ticker already exists, a provided name or sector fills in the
    stored value, and a missing (None) value never overwrites existing data.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to the database.
    ticker : str
        Ticker symbol in yfinance format, e.g. "BRK-B".
    company_name : str, optional
        Company name.
    sector : str, optional
        Sector name.

    Returns
    -------
    None
    """
    conn.execute("""
        INSERT INTO tickers (ticker, company_name, sector, added_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            company_name = COALESCE(excluded.company_name, tickers.company_name),
            sector = COALESCE(excluded.sector, tickers.sector)
    """, (ticker, company_name, sector, datetime.now().isoformat()))
    conn.commit()


def standardize_tickers(data, ticker_col='ticker', name_col=None, sector_col=None):
    """
    Convert a list or DataFrame of tickers into the standard format.

    The standard format is a DataFrame with columns ticker, company_name, and
    sector. Only ticker is required; the others may be empty. Tickers are
    stripped, uppercased, converted to yfinance style (BRK.B becomes BRK-B),
    and de-duplicated.

    Parameters
    ----------
    data : list, tuple, pd.Series, or pd.DataFrame
        A plain collection of ticker symbols, or a table containing them.
    ticker_col : str, default 'ticker'
        Name of the ticker column in data (DataFrame input only).
    name_col : str, optional
        Name of the company name column in data, if there is one.
    sector_col : str, optional
        Name of the sector column in data, if there is one.

    Returns
    -------
    pd.DataFrame
        Columns ['ticker', 'company_name', 'sector'], one row per unique ticker.
    """
    if isinstance(data, (list, tuple, pd.Series)):
        df = pd.DataFrame({'ticker': list(data)})
    else:
        df = pd.DataFrame({'ticker': data[ticker_col]})
        if name_col:
            df['company_name'] = data[name_col]
        if sector_col:
            df['sector'] = data[sector_col]

    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df['ticker'] = (df['ticker'].astype(str).str.strip()
                    .str.upper().str.replace('.', '-', regex=False))
    df = df[df['ticker'] != ''].drop_duplicates(subset='ticker')
    return df[STANDARD_COLUMNS].reset_index(drop=True)


def batch_load_tickers(conn, df):
    """
    Load a standard-format DataFrame into the tickers table.

    Existing tickers are updated rather than duplicated: a provided name or
    sector fills in the stored value, and a missing value never erases
    existing data.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to the database.
    df : pd.DataFrame
        Output of standardize_tickers, with columns ticker, company_name, sector.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If df is missing any of the standard columns.
    """
    missing = [c for c in STANDARD_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Missing columns: {missing}. Run the data through standardize_tickers first."
        )

    subset = df[STANDARD_COLUMNS]
    clean = subset.astype(object).where(subset.notna(), None)
    now = datetime.now().isoformat()
    rows = [(*r, now) for r in clean.values.tolist()]

    conn.executemany("""
        INSERT INTO tickers (ticker, company_name, sector, added_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            company_name = COALESCE(excluded.company_name, tickers.company_name),
            sector = COALESCE(excluded.sector, tickers.sector)
    """, rows)
    conn.commit()
    print(f"Loaded {len(rows)} tickers.")
