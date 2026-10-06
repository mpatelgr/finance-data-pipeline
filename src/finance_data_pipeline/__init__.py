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
from .analysis import (
    get_price_technicals,
    get_fundamentals,
    get_analyst_view,
    get_options_summary,
    load_price_data,
    analyze_stock,
    print_report,
    plot_technicals,
)

from .fundamentals import (
    fundamentals_need_update, 
    save_fundamentals_snapshot, 
    load_latest_fundamentals,
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
    "get_price_technicals",
    "get_fundamentals",
    "get_analyst_view",
    "get_options_summary",
    "load_price_data",
    "analyze_stock",
    "print_report",
    "plot_technicals",
    "fundamentals_need_update",
     "save_fundamentals_snapshot", 
     "load_latest_fundamentals",
]