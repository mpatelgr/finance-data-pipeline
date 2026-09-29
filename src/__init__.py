"""
finance-data-pipeline source package.

Re-exports the functions notebooks use, so a single import line reaches
everything:

    from src import init_db, standardize_tickers, batch_load_tickers, \
        register_ticker, update_ticker_data, update_many
"""

from .database import init_db
from .tickers import register_ticker, standardize_tickers, batch_load_tickers
from .prices import (
    default_max_age,
    needs_update,
    update_ticker_data,
    update_many,
    DEFAULT_SOURCE,
    SUPPORTED_SOURCES,
)

__all__ = [
    "init_db",
    "register_ticker",
    "standardize_tickers",
    "batch_load_tickers",
    "default_max_age",
    "needs_update",
    "update_ticker_data",
    "update_many",
    "DEFAULT_SOURCE",
    "SUPPORTED_SOURCES",
]