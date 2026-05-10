from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from finbot_dashboard.data_loader import (
    CATALOG_COLUMNS,
    catalog_path,
    filter_daily_bars_by_ticker,
    filter_date_range,
    filter_ticker,
    filter_tickers,
    find_latest_ticker_row,
    find_ticker_row,
    latest_by_date,
    load_catalog,
    resolve_data_root,
    resolve_dataset_path,
)
from finbot_dashboard.config import CATALOG_FILENAME


def read_dataset(
    catalog: pd.DataFrame,
    dataset_name: str,
    data_root: str | Path,
    columns: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Backward-compatible dataset reader used by older tests.

    New dashboard code calls finbot_dashboard.data_loader.read_dataset directly,
    which loads the catalog internally for Streamlit caching.
    """
    path = resolve_dataset_path(catalog, dataset_name, data_root)
    if path is None or not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_parquet(path, columns=list(columns) if columns is not None else None)
    except (FileNotFoundError, OSError, ValueError, KeyError, ImportError):
        return pd.DataFrame()


__all__ = [
    "CATALOG_COLUMNS",
    "CATALOG_FILENAME",
    "catalog_path",
    "filter_daily_bars_by_ticker",
    "filter_date_range",
    "filter_ticker",
    "filter_tickers",
    "find_latest_ticker_row",
    "find_ticker_row",
    "latest_by_date",
    "load_catalog",
    "read_dataset",
    "resolve_data_root",
    "resolve_dataset_path",
]
