from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import pandas as pd

CATALOG_FILENAME = "dataset_catalog.parquet"

CATALOG_COLUMNS = [
    "dataset_name",
    "dataset_group",
    "metadata_path",
    "parquet_path",
    "metadata_exists",
    "parquet_exists",
    "provider",
    "row_count",
    "symbol_count",
    "data_min_date",
    "data_max_date",
    "collection_timestamp",
    "parquet_columns",
    "parquet_schema",
    "status",
    "status_reason",
    "catalog_built_at",
]


def resolve_data_root(
    env: dict[str, str] | None = None,
    start_path: str | Path | None = None,
) -> Path:
    """Resolve the shared Finbot data root.

    FINBOT_DATA_ROOT wins. Without it, infer the standard layout:
    finbot/repos/finbot-dashboard -> finbot/data.
    """
    env = env if env is not None else os.environ
    configured = env.get("FINBOT_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve(strict=False)

    start = Path(start_path).expanduser() if start_path is not None else Path.cwd()
    start = start.resolve(strict=False)
    search_from = start if start.is_dir() else start.parent

    for parent in [search_from, *search_from.parents]:
        candidate = parent / "data"
        if candidate.exists():
            return candidate.resolve(strict=False)

    return (Path.cwd() / "data").resolve(strict=False)


def catalog_path(data_root: str | Path) -> Path:
    return Path(data_root) / "catalog" / CATALOG_FILENAME


def load_catalog(data_root: str | Path) -> pd.DataFrame:
    path = catalog_path(data_root)
    if not path.exists():
        return pd.DataFrame(columns=CATALOG_COLUMNS)

    catalog = pd.read_parquet(path)
    for column in CATALOG_COLUMNS:
        if column not in catalog.columns:
            catalog[column] = pd.NA
    return catalog


def resolve_dataset_path(
    catalog: pd.DataFrame,
    dataset_name: str,
    data_root: str | Path,
    path_column: str = "parquet_path",
    require_catalog_exists: bool = True,
) -> Path | None:
    if catalog.empty or "dataset_name" not in catalog.columns or path_column not in catalog.columns:
        return None

    matches = catalog.loc[catalog["dataset_name"] == dataset_name]
    if matches.empty:
        return None

    row = matches.iloc[0]
    exists_column = "parquet_exists" if path_column == "parquet_path" else "metadata_exists"
    if require_catalog_exists and exists_column in row and not _truthy(row[exists_column]):
        return None

    value = row.get(path_column)
    if _is_missing(value):
        return None

    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = Path(data_root) / path
    return path.resolve(strict=False)


def read_dataset(
    catalog: pd.DataFrame,
    dataset_name: str,
    data_root: str | Path,
    columns: Iterable[str] | None = None,
) -> pd.DataFrame:
    path = resolve_dataset_path(catalog, dataset_name, data_root)
    if path is None or not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_parquet(path, columns=list(columns) if columns is not None else None)
    except (FileNotFoundError, OSError, ValueError, KeyError, ImportError):
        return pd.DataFrame()


def filter_tickers(tickers: pd.DataFrame, query: str, limit: int = 100) -> pd.DataFrame:
    if tickers.empty:
        return tickers.copy()
    if "ticker" not in tickers.columns:
        return pd.DataFrame(columns=tickers.columns)

    result = tickers.copy()
    if query:
        needle = query.strip().upper()
        ticker_match = result["ticker"].fillna("").astype(str).str.upper().str.contains(needle, regex=False)
        if "name" in result.columns:
            name_match = result["name"].fillna("").astype(str).str.upper().str.contains(needle, regex=False)
            result = result.loc[ticker_match | name_match]
        else:
            result = result.loc[ticker_match]

    return result.sort_values("ticker").head(limit).reset_index(drop=True)


def find_ticker_row(tickers: pd.DataFrame, ticker: str) -> pd.Series | None:
    if tickers.empty or "ticker" not in tickers.columns or not ticker:
        return None

    matches = tickers.loc[tickers["ticker"].fillna("").astype(str).str.upper() == ticker.upper()]
    if matches.empty:
        return None
    return matches.iloc[0]


def filter_daily_bars_by_ticker(daily_bars: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if daily_bars.empty or not ticker:
        return pd.DataFrame(columns=daily_bars.columns)

    symbol_column = _first_present_column(daily_bars, ["symbol", "ticker"])
    if symbol_column is None:
        return pd.DataFrame(columns=daily_bars.columns)

    filtered = daily_bars.loc[
        daily_bars[symbol_column].fillna("").astype(str).str.upper() == ticker.upper()
    ].copy()

    if "date" in filtered.columns:
        filtered["date"] = pd.to_datetime(filtered["date"], errors="coerce")
        filtered = filtered.sort_values("date")
    return filtered.reset_index(drop=True)


def _first_present_column(df: pd.DataFrame, columns: Iterable[str]) -> str | None:
    return next((column for column in columns if column in df.columns), None)


def _truthy(value: object) -> bool:
    if _is_missing(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False
