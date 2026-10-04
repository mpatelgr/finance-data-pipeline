"""
Tests for src.analysis.

yfinance is mocked throughout, so these tests make no network calls.
"""

import numpy as np
import pandas as pd
import pytest

from finance_data_pipeline import analysis as analysis_module
from finance_data_pipeline.analysis import *


class FakeChain:
    """Stands in for yfinance's option_chain() result."""

    def __init__(self):
        self.calls = pd.DataFrame({'impliedVolatility': [0.30, 0.35], 'volume': [100, 50]})
        self.puts = pd.DataFrame({'impliedVolatility': [0.32, 0.31], 'volume': [80, 20]})


class FakeTicker:
    """
    Stands in for yfinance.Ticker.

    Behavior is driven by the symbol: "NOHIST" returns no price history,
    "NOOPT" has no listed options, "NOINFO" has an empty info dict, and
    anything else returns a normal, full set of data.
    """

    def __init__(self, symbol):
        self.symbol = symbol
        self.options = () if symbol == "NOOPT" else ("2026-10-16", "2026-11-20")
        self.info = {} if symbol == "NOINFO" else {
            'sector': 'Technology', 'industry': 'Consumer Electronics',
            'marketCap': 3_000_000_000_000, 'trailingPE': 30.0, 'forwardPE': 28.0,
            'pegRatio': 2.1, 'dividendYield': 0.005, 'profitMargins': 0.25,
            'debtToEquity': 150.0, 'beta': 1.2, 'targetMeanPrice': 350.0,
            'targetHighPrice': 400.0, 'targetLowPrice': 300.0,
            'numberOfAnalystOpinions': 30,
        }

    def history(self, **kwargs):
        if self.symbol == "NOHIST":
            return pd.DataFrame()
        idx = pd.date_range("2024-01-01", periods=300, freq="D")
        rng = np.random.default_rng(0)
        close = 100 + np.cumsum(rng.normal(0, 1, len(idx)))
        return pd.DataFrame(
            {'Open': close, 'High': close + 1, 'Low': close - 1,
             'Close': close, 'Volume': 1000},
            index=idx,
        )

    def option_chain(self, expiration):
        return FakeChain()


@pytest.fixture(autouse=True)
def fake_yfinance(monkeypatch):
    """Replace yfinance.Ticker with FakeTicker for every test in this file."""
    monkeypatch.setattr(analysis_module.yf, "Ticker", FakeTicker)


# --- get_price_technicals ---

def test_get_price_technicals_normal_case():
    result = get_price_technicals("AAPL")
    assert result['current_price'] is not None
    assert result['trend'] in ('bullish', 'bearish')
    assert result['max_drawdown'] <= 0  # a drawdown is zero or negative by definition


def test_get_price_technicals_handles_empty_history():
    result = get_price_technicals("NOHIST")
    assert result['current_price'] is None
    assert result['trend'] is None
    assert result['price_data'].empty


# --- get_fundamentals ---

def test_get_fundamentals_normal_case():
    result = get_fundamentals("AAPL")
    assert result['sector'] == 'Technology'
    assert result['pe_ratio'] == 30.0


def test_get_fundamentals_handles_missing_info():
    result = get_fundamentals("NOINFO")
    assert result['sector'] is None
    assert result['pe_ratio'] is None


# --- get_analyst_view ---

def test_get_analyst_view_normal_case():
    result = get_analyst_view("AAPL")
    assert result['target_mean'] == 350.0
    assert result['number_of_analysts'] == 30


def test_get_analyst_view_handles_missing_info():
    result = get_analyst_view("NOINFO")
    assert result['target_mean'] is None


# --- get_options_summary ---

def test_get_options_summary_normal_case():
    result = get_options_summary("AAPL")
    assert result['nearest_expiration'] == "2026-10-16"
    assert result['put_call_ratio'] == pytest.approx(100 / 150)  # (80+20) / (100+50)


def test_get_options_summary_handles_no_listed_options():
    result = get_options_summary("NOOPT")
    assert result['nearest_expiration'] is None
    assert result['put_call_ratio'] is None


# --- analyze_stock ---

def test_analyze_stock_returns_all_four_sections():
    report = analyze_stock("AAPL")
    assert set(report.keys()) == {'ticker', 'technicals', 'fundamentals', 'analyst', 'options'}
    assert report['ticker'] == "AAPL"


def test_analyze_stock_handles_a_ticker_missing_everything():
    # No history, no options, no info: should not raise
    report = analyze_stock("NOHIST")
    assert report['technicals']['current_price'] is None


# --- print_report ---

def test_print_report_runs_without_raising_on_a_full_report(capsys):
    report = analyze_stock("AAPL")
    print_report(report)
    output = capsys.readouterr().out
    assert "AAPL" in output
    assert "Fundamentals" in output


def test_print_report_runs_without_raising_on_missing_data(capsys):
    report = analyze_stock("NOINFO")
    print_report(report)  # should print 'n/a' values, not raise
    output = capsys.readouterr().out
    assert "n/a" in output