from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from finbot_dashboard.config import CACHE_TTL_SECONDS


TICKERS_DATASET = "reference.tickers"
PRICE_DATASET = "market.daily_bars.historical"
VALUATION_DATASET = "fundamentals.daily_valuation_metrics"

TICKER_COLUMNS = [
    "ticker",
    "name",
    "exchange",
    "sector",
    "industry",
    "scalemarketcap",
    "scalerevenue",
    "currency",
    "location",
    "firstpricedate",
    "lastpricedate",
    "lastquarter",
    "companysite",
    "secfilings",
]

PRICE_COLUMNS = ["date", "symbol", "open", "high", "low", "close", "volume", "closeadj", "closeunadj", "lastupdated"]
VALUATION_COLUMNS = ["ticker", "date", "lastupdated", "ev", "evebit", "evebitda", "marketcap", "pb", "pe", "ps"]
VALUATION_METRIC_COLUMNS = ["marketcap", "ev", "pe", "ps", "pb", "evebit", "evebitda"]


@dataclass(frozen=True)
class IndicatorInfo:
    indicator: str
    title: str
    description: str
    unit_type: str


def dataset_parquet_path(catalog: pd.DataFrame, data_root: str | Path, dataset_name: str) -> Path | None:
    if catalog.empty or "dataset_name" not in catalog.columns or "parquet_path" not in catalog.columns:
        return None

    matches = catalog.loc[catalog["dataset_name"].fillna("").astype(str) == dataset_name]
    if matches.empty:
        return None

    row = matches.iloc[0]
    if "parquet_exists" in row and not _truthy(row["parquet_exists"]):
        return None

    raw_path = row.get("parquet_path")
    if pd.isna(raw_path):
        return None

    return (Path(data_root) / str(raw_path)).resolve(strict=False)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_ticker_reference(data_root: str | Path, catalog: pd.DataFrame) -> pd.DataFrame:
    path = dataset_parquet_path(catalog, data_root, TICKERS_DATASET)
    frame = _read_parquet(path, columns=TICKER_COLUMNS)
    if frame.empty:
        return pd.DataFrame(columns=TICKER_COLUMNS)

    frame = frame.dropna(subset=["ticker"]).copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    if "name" in frame.columns:
        frame["display_name"] = frame["ticker"] + " - " + frame["name"].fillna("").astype(str)
    else:
        frame["display_name"] = frame["ticker"]
    return frame.sort_values("ticker").reset_index(drop=True)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_price_history(data_root: str | Path, catalog: pd.DataFrame, symbol: str) -> pd.DataFrame:
    symbol = symbol.strip().upper()
    path = dataset_parquet_path(catalog, data_root, PRICE_DATASET)
    frame = _read_parquet(path, columns=PRICE_COLUMNS, filters=[("symbol", "=", symbol)])
    if frame.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)

    frame = _with_datetime(frame, "date")
    return frame.sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_valuation_history(data_root: str | Path, catalog: pd.DataFrame, ticker: str) -> pd.DataFrame:
    ticker = ticker.strip().upper()
    path = dataset_parquet_path(catalog, data_root, VALUATION_DATASET)
    frame = _read_parquet(path, columns=VALUATION_COLUMNS, filters=[("ticker", "=", ticker)])
    if frame.empty:
        return pd.DataFrame(columns=VALUATION_COLUMNS)

    frame = _with_datetime(frame, "date")
    return frame.sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_daily_indicator_info(data_root: str | Path) -> dict[str, IndicatorInfo]:
    path = Path(data_root) / "temp" / "SHARADAR-INDICATORS.csv"
    if not path.exists():
        return {}

    try:
        frame = pd.read_csv(path)
    except (OSError, ValueError):
        return {}

    required = {"table", "indicator", "title", "description", "unittype"}
    if not required.issubset(frame.columns):
        return {}

    daily = frame.loc[frame["table"].fillna("").astype(str).str.upper() == "DAILY"]
    result: dict[str, IndicatorInfo] = {}
    for row in daily.to_dict("records"):
        indicator = str(row["indicator"]).lower()
        result[indicator] = IndicatorInfo(
            indicator=indicator,
            title=str(row.get("title") or indicator),
            description=str(row.get("description") or ""),
            unit_type=str(row.get("unittype") or ""),
        )
    return result


def latest_valuation_metrics(valuations: pd.DataFrame, indicators: dict[str, IndicatorInfo]) -> pd.DataFrame:
    columns = ["metric", "label", "value", "unit", "description"]
    if valuations.empty:
        return pd.DataFrame(columns=columns)

    latest = valuations.sort_values("date").iloc[-1]
    rows = []
    for metric in VALUATION_METRIC_COLUMNS:
        if metric not in valuations.columns:
            continue
        info = indicators.get(metric)
        rows.append(
            {
                "metric": metric,
                "label": info.title if info else metric,
                "value": latest.get(metric),
                "unit": info.unit_type if info else "",
                "description": info.description if info else "",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def filter_history_range(frame: pd.DataFrame, years: int | None) -> pd.DataFrame:
    if frame.empty or years is None or "date" not in frame.columns:
        return frame.copy()

    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.dropna().empty:
        return frame.copy()

    cutoff = dates.max() - pd.DateOffset(years=years)
    return frame.loc[dates >= cutoff].copy().reset_index(drop=True)


def _read_parquet(path: Path | None, *, columns: list[str], filters: list[tuple[str, str, object]] | None = None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame(columns=columns)

    try:
        frame = pd.read_parquet(path, columns=columns, filters=filters)
    except (FileNotFoundError, OSError, ValueError, ImportError):
        try:
            frame = pd.read_parquet(path, filters=filters)
        except (FileNotFoundError, OSError, ValueError, ImportError):
            return pd.DataFrame(columns=columns)

    for column in columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[columns]


def _with_datetime(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    result = frame.copy()
    if column in result.columns:
        result[column] = pd.to_datetime(result[column], errors="coerce")
    return result


def _truthy(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return bool(value)
