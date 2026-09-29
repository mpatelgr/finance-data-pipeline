"""
Tests for src.prices.

yfinance is mocked throughout, so these tests make no network calls and do
not depend on Yahoo being reachable or rate limits.
"""

import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.database import init_db
from src import prices as prices_module
from src.prices import (
    default_max_age,
    needs_update,
    update_ticker_data,
    update_many,
    SUPPORTED_SOURCES,
)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


class FakeTicker:
    """Stands in for yfinance.Ticker. history() returns canned bars, or an
    empty frame for a ticker symbol of "BAD", to simulate an invalid symbol."""

    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, **kwargs):
        if self.symbol == "BAD":
            return pd.DataFrame()
        idx = pd.date_range("2026-09-21", periods=3, freq="D", tz="America/New_York")
        return pd.DataFrame({
            'Open': [1.0, 2.0, 3.0], 'High': [2.0, 3.0, 4.0],
            'Low': [0.5, 1.5, 2.5], 'Close': [1.5, 2.5, 3.5],
            'Volume': [100, 200, 300],
        }, index=idx)


@pytest.fixture(autouse=True)
def fake_yfinance(monkeypatch):
    """Replace yfinance.Ticker with FakeTicker for every test in this file."""
    monkeypatch.setattr(prices_module.yf, "Ticker", FakeTicker)


# --- default_max_age ---

def test_default_max_age_is_24_hours_for_daily():
    assert default_max_age("1d") == 24


def test_default_max_age_is_short_for_intraday():
    assert default_max_age("5m") == 0.5


# --- needs_update ---

def test_needs_update_is_true_when_never_pulled(conn):
    assert needs_update(conn, "AAPL", "1d", max_age_hours=24) is True


def test_needs_update_is_false_when_recently_updated(conn):
    conn.execute(
        "INSERT INTO update_log (ticker, interval, source, last_updated) "
        "VALUES ('AAPL', '1d', 'yfinance', ?)",
        (datetime.now().isoformat(),)
    )
    assert needs_update(conn, "AAPL", "1d", max_age_hours=24) is False


def test_needs_update_is_true_when_stale(conn):
    old = (datetime.now() - timedelta(hours=48)).isoformat()
    conn.execute(
        "INSERT INTO update_log (ticker, interval, source, last_updated) "
        "VALUES ('AAPL', '1d', 'yfinance', ?)", (old,)
    )
    assert needs_update(conn, "AAPL", "1d", max_age_hours=24) is True


def test_needs_update_force_ignores_freshness(conn):
    conn.execute(
        "INSERT INTO update_log (ticker, interval, source, last_updated) "
        "VALUES ('AAPL', '1d', 'yfinance', ?)",
        (datetime.now().isoformat(),)
    )
    assert needs_update(conn, "AAPL", "1d", max_age_hours=24, force=True) is True


def test_needs_update_tracks_sources_separately(conn):
    conn.execute(
        "INSERT INTO update_log (ticker, interval, source, last_updated) "
        "VALUES ('AAPL', '1d', 'yfinance', ?)",
        (datetime.now().isoformat(),)
    )
    # A different source for the same ticker/interval was never pulled
    assert needs_update(conn, "AAPL", "1d", max_age_hours=24, source="other") is True


# --- update_ticker_data ---

def test_update_ticker_data_saves_rows(conn):
    update_ticker_data(conn, "AAPL")
    count = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    assert count == 3


def test_update_ticker_data_registers_the_ticker(conn):
    update_ticker_data(conn, "AAPL")
    row = conn.execute("SELECT ticker FROM tickers WHERE ticker = 'AAPL'").fetchone()
    assert row is not None


def test_update_ticker_data_logs_the_update_time(conn):
    update_ticker_data(conn, "AAPL")
    row = conn.execute(
        "SELECT source FROM update_log WHERE ticker = 'AAPL' AND interval = '1d'"
    ).fetchone()
    assert row == ("yfinance",)


def test_update_ticker_data_skips_when_fresh(conn, capsys):
    update_ticker_data(conn, "AAPL")
    update_ticker_data(conn, "AAPL")  # second call should skip, not duplicate
    count = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    assert count == 3
    assert "skipping" in capsys.readouterr().out


def test_update_ticker_data_force_overwrites_without_duplicating(conn):
    update_ticker_data(conn, "AAPL")
    update_ticker_data(conn, "AAPL", force=True)
    count = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    assert count == 3  # same 3 dates replaced, not appended


def test_update_ticker_data_handles_an_invalid_symbol_without_raising(conn):
    update_ticker_data(conn, "BAD")  # should not raise
    count = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    assert count == 0


def test_update_ticker_data_rejects_an_unsupported_source(conn):
    with pytest.raises(ValueError):
        update_ticker_data(conn, "AAPL", source="not_a_real_source")


def test_update_ticker_data_keeps_sources_separate(conn):
    update_ticker_data(conn, "AAPL", source="yfinance")
    # A second, made-up source is exercised by temporarily allowing it
    prices_module.SUPPORTED_SOURCES = ("yfinance", "other")
    try:
        update_ticker_data(conn, "AAPL", source="other")
        count = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
        assert count == 6  # 3 rows per source, not merged or overwritten
    finally:
        prices_module.SUPPORTED_SOURCES = SUPPORTED_SOURCES  # restore original


# --- update_many ---

def test_update_many_continues_after_a_failure(conn):
    update_many(conn, ["BAD", "AAPL"], delay=0)
    count = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    assert count == 3  # AAPL's rows saved despite BAD failing first


def test_update_many_rejects_an_unsupported_source_up_front(conn):
    with pytest.raises(ValueError):
        update_many(conn, ["AAPL"], source="not_a_real_source", delay=0)
