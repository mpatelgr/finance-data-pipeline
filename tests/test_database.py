"""Tests for src.database."""

import sqlite3

import pandas as pd
import pytest

from src.database import init_db


@pytest.fixture
def conn():
    """An in-memory database with the schema already created."""
    connection = sqlite3.connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


def test_init_db_creates_all_tables_and_view(conn):
    names = pd.read_sql(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')", conn
    )['name'].tolist()
    for expected in ('tickers', 'update_log', 'price_history', 'masterlist'):
        assert expected in names


def test_init_db_is_safe_to_run_twice(conn):
    # Should not raise, and should not duplicate or wipe anything
    init_db(conn)
    tables = pd.read_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table'", conn
    )['name'].tolist()
    assert tables.count('tickers') == 1


def test_masterlist_is_empty_on_a_fresh_database(conn):
    result = pd.read_sql("SELECT * FROM masterlist", conn)
    assert len(result) == 0
