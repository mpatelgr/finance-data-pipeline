"""Tests for src.tickers."""

import sqlite3

import pandas as pd
import pytest

from src.database import init_db
from src.tickers import standardize_tickers, batch_load_tickers, register_ticker


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


# --- standardize_tickers ---

def test_standardize_tickers_strips_and_uppercases():
    result = standardize_tickers(["  aapl", "msft "])
    assert result['ticker'].tolist() == ["AAPL", "MSFT"]


def test_standardize_tickers_converts_dot_to_dash():
    result = standardize_tickers(["brk.b"])
    assert result['ticker'].tolist() == ["BRK-B"]


def test_standardize_tickers_drops_duplicates():
    result = standardize_tickers(["AAPL", "aapl", "AAPL"])
    assert len(result) == 1


def test_standardize_tickers_drops_blank_entries():
    result = standardize_tickers(["AAPL", "  ", ""])
    assert result['ticker'].tolist() == ["AAPL"]


def test_standardize_tickers_has_standard_columns_for_a_plain_list():
    result = standardize_tickers(["AAPL"])
    assert list(result.columns) == ['ticker', 'company_name', 'sector']
    assert result['company_name'].iloc[0] is None


def test_standardize_tickers_maps_dataframe_columns():
    source = pd.DataFrame({
        'Symbol': ['aapl', 'brk.b'],
        'Security': ['Apple', 'Berkshire'],
        'GICS Sector': ['Technology', 'Financials'],
    })
    result = standardize_tickers(
        source, ticker_col='Symbol', name_col='Security', sector_col='GICS Sector'
    )
    assert result['ticker'].tolist() == ['AAPL', 'BRK-B']
    assert result['company_name'].tolist() == ['Apple', 'Berkshire']


# --- register_ticker ---

def test_register_ticker_adds_a_new_row(conn):
    register_ticker(conn, "AAPL", "Apple Inc.", "Technology")
    row = conn.execute(
        "SELECT company_name, sector FROM tickers WHERE ticker = 'AAPL'"
    ).fetchone()
    assert row == ("Apple Inc.", "Technology")


def test_register_ticker_fills_in_missing_fields_without_erasing(conn):
    register_ticker(conn, "AAPL", "Apple Inc.", "Technology")
    register_ticker(conn, "AAPL")  # no name or sector supplied
    row = conn.execute(
        "SELECT company_name, sector FROM tickers WHERE ticker = 'AAPL'"
    ).fetchone()
    assert row == ("Apple Inc.", "Technology")  # unchanged, not wiped to None


def test_register_ticker_updates_a_field_when_a_new_value_is_given(conn):
    register_ticker(conn, "AAPL", None, None)
    register_ticker(conn, "AAPL", "Apple Inc.", "Technology")
    row = conn.execute(
        "SELECT company_name, sector FROM tickers WHERE ticker = 'AAPL'"
    ).fetchone()
    assert row == ("Apple Inc.", "Technology")


# --- batch_load_tickers ---

def test_batch_load_tickers_loads_all_rows(conn):
    df = standardize_tickers(["AAPL", "MSFT"])
    batch_load_tickers(conn, df)
    count = conn.execute("SELECT COUNT(*) FROM tickers").fetchone()[0]
    assert count == 2


def test_batch_load_tickers_is_safe_to_rerun(conn):
    df = standardize_tickers(["AAPL", "MSFT"])
    batch_load_tickers(conn, df)
    batch_load_tickers(conn, df)  # rerun: should not duplicate
    count = conn.execute("SELECT COUNT(*) FROM tickers").fetchone()[0]
    assert count == 2


def test_batch_load_tickers_raises_on_missing_columns(conn):
    bad_df = pd.DataFrame({'ticker': ['AAPL']})  # missing company_name, sector
    with pytest.raises(ValueError):
        batch_load_tickers(conn, bad_df)
