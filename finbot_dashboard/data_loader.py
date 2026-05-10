from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

import pandas as pd
import streamlit as st

from finbot_dashboard.config import (
    CACHE_TTL_SECONDS,
    CATALOG_FILENAME,
    CATALOG_JSON_FILENAME,
    EXPECTED_DATASETS,
)

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


def catalog_json_path(data_root: str | Path) -> Path:
    return Path(data_root) / "catalog" / CATALOG_JSON_FILENAME


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_catalog(data_root: str | Path) -> pd.DataFrame:
    """Load the parquet dataset catalog, returning an empty catalog if missing."""
    path = catalog_path(data_root)
    if not path.exists():
        return pd.DataFrame(columns=CATALOG_COLUMNS)

    try:
        catalog = pd.read_parquet(path)
    except (FileNotFoundError, OSError, ValueError, ImportError):
        return pd.DataFrame(columns=CATALOG_COLUMNS)

    for column in CATALOG_COLUMNS:
        if column not in catalog.columns:
            catalog[column] = pd.NA
    return catalog


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_catalog_json(data_root: str | Path) -> list[dict[str, object]]:
    """Load the JSON catalog when available for data-quality display."""
    path = catalog_json_path(data_root)
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, TypeError):
        return []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        records = payload.get("datasets", payload.get("records", []))
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
    return []


def resolve_dataset_path(
    catalog: pd.DataFrame,
    dataset_name: str,
    data_root: str | Path,
    path_column: str = "parquet_path",
    require_catalog_exists: bool = True,
) -> Path | None:
    """Resolve a dataset path from the catalog, falling back to expected paths."""
    if not catalog.empty and {"dataset_name", path_column}.issubset(catalog.columns):
        matches = catalog.loc[catalog["dataset_name"] == dataset_name]
        if not matches.empty:
            row = matches.iloc[0]
            exists_column = "parquet_exists" if path_column == "parquet_path" else "metadata_exists"
            if require_catalog_exists and exists_column in row and not _truthy(row[exists_column]):
                return None

            value = row.get(path_column)
            if not _is_missing(value):
                path = Path(str(value)).expanduser()
                if not path.is_absolute():
                    path = Path(data_root) / path
                return path.resolve(strict=False)

    if path_column == "parquet_path" and dataset_name in EXPECTED_DATASETS:
        return (Path(data_root) / EXPECTED_DATASETS[dataset_name]).resolve(strict=False)
    return None


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def read_dataset(
    data_root: str | Path,
    dataset_name: str,
    columns: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Read a local parquet dataset by catalog name.

    The catalog is preferred, but known v1 dataset paths are used as a fallback so the
    dashboard can still explain missing or stale catalog state.
    """
    catalog = load_catalog(data_root)
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


def filter_ticker(frame: pd.DataFrame, ticker: str, column: str | None = None) -> pd.DataFrame:
    """Return rows for a ticker from either ticker or symbol keyed data."""
    if frame.empty or not ticker:
        return pd.DataFrame(columns=frame.columns)

    key = column or _first_present_column(frame, ["ticker", "symbol"])
    if key is None:
        return pd.DataFrame(columns=frame.columns)

    filtered = frame.loc[frame[key].fillna("").astype(str).str.upper() == ticker.upper()].copy()
    if "date" in filtered.columns:
        filtered["date"] = pd.to_datetime(filtered["date"], errors="coerce")
    if "period_end" in filtered.columns:
        filtered["period_end"] = pd.to_datetime(filtered["period_end"], errors="coerce")
    return filtered.reset_index(drop=True)


def filter_date_range(frame: pd.DataFrame, date_column: str, days: int | None) -> pd.DataFrame:
    """Filter a dataframe to the trailing day window based on its own max date."""
    if frame.empty or days is None or date_column not in frame.columns:
        return frame.copy()

    result = frame.copy()
    dates = pd.to_datetime(result[date_column], errors="coerce")
    max_date = dates.max()
    if pd.isna(max_date):
        return result
    start_date = max_date - pd.Timedelta(days=days)
    return result.loc[dates >= start_date].reset_index(drop=True)


def find_ticker_row(tickers: pd.DataFrame, ticker: str) -> pd.Series | None:
    if tickers.empty or "ticker" not in tickers.columns or not ticker:
        return None

    matches = tickers.loc[tickers["ticker"].fillna("").astype(str).str.upper() == ticker.upper()]
    if matches.empty:
        return None
    return matches.iloc[0]


def latest_by_date(
    frame: pd.DataFrame,
    date_column: str = "date",
    group_column: str | None = None,
) -> pd.DataFrame:
    """Return latest rows by date, optionally one per group."""
    if frame.empty:
        return frame.copy()
    if date_column not in frame.columns:
        return frame.drop_duplicates(subset=[group_column]).copy() if group_column else frame.tail(1).copy()

    result = frame.copy()
    result["_sort_date"] = pd.to_datetime(result[date_column], errors="coerce")
    result = result.sort_values("_sort_date", ascending=False, na_position="last")
    if group_column and group_column in result.columns:
        result = result.drop_duplicates(subset=[group_column], keep="first")
    else:
        result = result.head(1)
    return result.drop(columns=["_sort_date"], errors="ignore").reset_index(drop=True)


def find_latest_ticker_row(
    frame: pd.DataFrame,
    ticker: str,
    date_column: str = "date",
) -> pd.Series | None:
    matches = filter_ticker(frame, ticker)
    if matches.empty:
        return None

    latest = latest_by_date(matches, date_column=date_column)
    if latest.empty:
        return None
    return latest.iloc[0]


def filter_daily_bars_by_ticker(daily_bars: pd.DataFrame, ticker: str) -> pd.DataFrame:
    filtered = filter_ticker(daily_bars, ticker, column=_first_present_column(daily_bars, ["symbol", "ticker"]))
    if not filtered.empty and "date" in filtered.columns:
        filtered = filtered.sort_values("date").reset_index(drop=True)
    return filtered


def related_ticker_list(related: pd.DataFrame, ticker: str) -> list[str]:
    """Return related tickers in provider result order."""
    rows = filter_ticker(related, ticker)
    if rows.empty or "related_ticker" not in rows.columns:
        return []
    if "result_order" in rows.columns:
        rows = rows.sort_values("result_order")
    return rows["related_ticker"].dropna().astype(str).str.upper().drop_duplicates().tolist()


def build_data_quality_frame(data_root: str | Path, catalog: pd.DataFrame) -> pd.DataFrame:
    """Build data-quality records from the catalog plus expected local paths."""
    root = Path(data_root)
    records: list[dict[str, object]] = []

    if not catalog.empty and "dataset_name" in catalog.columns:
        for _, row in catalog.iterrows():
            dataset_name = str(row.get("dataset_name", ""))
            path = resolve_dataset_path(catalog, dataset_name, root, require_catalog_exists=False)
            records.append(
                {
                    "dataset_name": dataset_name,
                    "provider": row.get("provider", pd.NA),
                    "status": row.get("status", pd.NA),
                    "row_count": row.get("row_count", pd.NA),
                    "symbol_count": row.get("symbol_count", pd.NA),
                    "data_min_date": row.get("data_min_date", pd.NA),
                    "data_max_date": row.get("data_max_date", pd.NA),
                    "collection_timestamp": row.get("collection_timestamp", pd.NA),
                    "parquet_path": str(path) if path is not None else row.get("parquet_path", pd.NA),
                    "file_exists_locally": bool(path and path.exists()),
                }
            )

    seen = {record["dataset_name"] for record in records}
    for dataset_name, relative_path in EXPECTED_DATASETS.items():
        if dataset_name in seen:
            continue
        path = (root / relative_path).resolve(strict=False)
        records.append(
            {
                "dataset_name": dataset_name,
                "provider": pd.NA,
                "status": "uncataloged" if path.exists() else "missing",
                "row_count": pd.NA,
                "symbol_count": pd.NA,
                "data_min_date": pd.NA,
                "data_max_date": pd.NA,
                "collection_timestamp": pd.NA,
                "parquet_path": str(path),
                "file_exists_locally": path.exists(),
            }
        )

    return pd.DataFrame(records).sort_values("dataset_name").reset_index(drop=True)


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
