from __future__ import annotations

from pathlib import Path

import pandas as pd

from finbot_dashboard.stock_data import (
    PRICE_DATASET,
    TICKERS_DATASET,
    VALUATION_DATASET,
    dataset_parquet_path,
    filter_history_range,
    latest_valuation_metrics,
    load_daily_indicator_info,
    load_price_history,
    load_ticker_reference,
    load_valuation_history,
)


def test_dataset_parquet_path_resolves_registered_dataset(tmp_path: Path) -> None:
    catalog = _catalog_frame()

    path = dataset_parquet_path(catalog, tmp_path, PRICE_DATASET)

    assert path == (tmp_path / "market/daily_bars/historical.parquet").resolve(strict=False)


def test_load_ticker_reference_adds_display_name(tmp_path: Path) -> None:
    catalog = _catalog_frame()
    tickers_path = tmp_path / "reference" / "tickers.parquet"
    tickers_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {"ticker": "MSFT", "name": "MICROSOFT CORP", "exchange": "NASDAQ"},
            {"ticker": "AAPL", "name": "APPLE INC", "exchange": "NASDAQ"},
        ]
    ).to_parquet(tickers_path)

    tickers = load_ticker_reference(tmp_path, catalog)

    assert tickers["ticker"].tolist() == ["AAPL", "MSFT"]
    assert tickers.loc[0, "display_name"] == "AAPL - APPLE INC"


def test_load_price_history_filters_by_symbol(tmp_path: Path) -> None:
    catalog = _catalog_frame()
    price_path = tmp_path / "market" / "daily_bars" / "historical.parquet"
    price_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {"date": "2024-01-02", "symbol": "AAPL", "closeadj": 100.0},
            {"date": "2024-01-03", "symbol": "MSFT", "closeadj": 200.0},
            {"date": "2024-01-04", "symbol": "AAPL", "closeadj": 101.0},
        ]
    ).to_parquet(price_path)

    prices = load_price_history(tmp_path, catalog, "aapl")

    assert prices["symbol"].tolist() == ["AAPL", "AAPL"]
    assert prices["closeadj"].tolist() == [100.0, 101.0]


def test_load_valuation_history_filters_by_ticker(tmp_path: Path) -> None:
    catalog = _catalog_frame()
    valuation_path = tmp_path / "fundamentals" / "daily_valuation_metrics.parquet"
    valuation_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {"date": "2024-01-02", "ticker": "AAPL", "pe": 28.0, "marketcap": 3000.0},
            {"date": "2024-01-03", "ticker": "MSFT", "pe": 35.0, "marketcap": 2800.0},
            {"date": "2024-01-04", "ticker": "AAPL", "pe": 29.0, "marketcap": 3050.0},
        ]
    ).to_parquet(valuation_path)

    valuations = load_valuation_history(tmp_path, catalog, "aapl")

    assert valuations["ticker"].tolist() == ["AAPL", "AAPL"]
    assert valuations["pe"].tolist() == [28.0, 29.0]


def test_load_daily_indicator_info_and_latest_metrics(tmp_path: Path) -> None:
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    (temp_dir / "SHARADAR-INDICATORS.csv").write_text(
        "\n".join(
            [
                "table,indicator,isfilter,isprimarykey,title,description,unittype",
                "DAILY,pe,N,N,Price Earnings - Daily,Price to earnings ratio,ratio",
                "DAILY,marketcap,N,N,Market Capitalization - Daily,Market value,USD millions",
            ]
        ),
        encoding="utf-8",
    )
    valuations = pd.DataFrame(
        [
            {"date": pd.Timestamp("2024-01-02"), "pe": 28.0, "marketcap": 3000.0},
            {"date": pd.Timestamp("2024-01-03"), "pe": 29.0, "marketcap": 3050.0},
        ]
    )

    indicators = load_daily_indicator_info(tmp_path)
    metrics = latest_valuation_metrics(valuations, indicators)

    assert indicators["pe"].title == "Price Earnings - Daily"
    assert metrics.loc[metrics["metric"] == "pe", "value"].iloc[0] == 29.0
    assert metrics.loc[metrics["metric"] == "marketcap", "unit"].iloc[0] == "USD millions"


def test_filter_history_range_keeps_recent_years() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2023-01-01", "2024-01-01"]),
            "closeadj": [1.0, 2.0, 3.0],
        }
    )

    filtered = filter_history_range(frame, years=1)

    assert filtered["closeadj"].tolist() == [2.0, 3.0]


def _catalog_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "dataset_name": TICKERS_DATASET,
                "parquet_path": "reference/tickers.parquet",
                "parquet_exists": True,
            },
            {
                "dataset_name": PRICE_DATASET,
                "parquet_path": "market/daily_bars/historical.parquet",
                "parquet_exists": True,
            },
            {
                "dataset_name": VALUATION_DATASET,
                "parquet_path": "fundamentals/daily_valuation_metrics.parquet",
                "parquet_exists": True,
            },
        ]
    )
