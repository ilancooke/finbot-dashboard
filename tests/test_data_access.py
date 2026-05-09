from __future__ import annotations

from pathlib import Path

import pandas as pd

from finbot_dashboard.data_access import (
    catalog_path,
    filter_daily_bars_by_ticker,
    filter_tickers,
    load_catalog,
    read_dataset,
    resolve_data_root,
    resolve_dataset_path,
)


def test_resolve_data_root_uses_environment_value(tmp_path: Path) -> None:
    data_root = tmp_path / "finbot-data-root"

    resolved = resolve_data_root(env={"FINBOT_DATA_ROOT": str(data_root)})

    assert resolved == data_root.resolve(strict=False)


def test_resolve_data_root_infers_standard_layout(tmp_path: Path) -> None:
    repo = tmp_path / "finbot" / "repos" / "finbot-dashboard"
    data_root = tmp_path / "finbot" / "data"
    repo.mkdir(parents=True)
    data_root.mkdir(parents=True)

    resolved = resolve_data_root(env={}, start_path=repo)

    assert resolved == data_root.resolve(strict=False)


def test_load_catalog_returns_empty_frame_when_missing(tmp_path: Path) -> None:
    catalog = load_catalog(tmp_path)

    assert catalog.empty
    assert "dataset_name" in catalog.columns


def test_load_catalog_reads_parquet_and_adds_missing_columns(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    pd.DataFrame(
        [
            {
                "dataset_name": "reference.tickers",
                "dataset_group": "reference",
                "parquet_path": "reference/tickers.parquet",
                "parquet_exists": True,
            }
        ]
    ).to_parquet(catalog_path(tmp_path))

    catalog = load_catalog(tmp_path)

    assert catalog.loc[0, "dataset_name"] == "reference.tickers"
    assert "status_reason" in catalog.columns


def test_resolve_dataset_path_uses_catalog_relative_path(tmp_path: Path) -> None:
    catalog = pd.DataFrame(
        [
            {
                "dataset_name": "reference.tickers",
                "parquet_path": "reference/tickers.parquet",
                "parquet_exists": True,
            }
        ]
    )

    resolved = resolve_dataset_path(catalog, "reference.tickers", tmp_path)

    assert resolved == (tmp_path / "reference" / "tickers.parquet").resolve(strict=False)


def test_resolve_dataset_path_returns_none_for_missing_dataset(tmp_path: Path) -> None:
    catalog = pd.DataFrame(
        [
            {
                "dataset_name": "reference.tickers",
                "parquet_path": "reference/tickers.parquet",
                "parquet_exists": False,
            }
        ]
    )

    resolved = resolve_dataset_path(catalog, "reference.tickers", tmp_path)

    assert resolved is None


def test_read_dataset_returns_empty_frame_when_optional_dataset_unavailable(tmp_path: Path) -> None:
    catalog = pd.DataFrame(columns=["dataset_name", "parquet_path", "parquet_exists"])

    data = read_dataset(catalog, "reference.ticker_details", tmp_path)

    assert data.empty


def test_filter_tickers_matches_symbol_and_name_case_insensitively() -> None:
    tickers = pd.DataFrame(
        [
            {"ticker": "AAPL", "name": "Apple Inc."},
            {"ticker": "MSFT", "name": "Microsoft Corporation"},
            {"ticker": "AG", "name": "First Majestic Silver"},
        ]
    )

    result = filter_tickers(tickers, "apple")

    assert result["ticker"].tolist() == ["AAPL"]


def test_filter_daily_bars_by_ticker_filters_case_insensitively_and_sorts_dates() -> None:
    bars = pd.DataFrame(
        [
            {"date": "2026-05-02", "symbol": "AAPL", "close": 2.0},
            {"date": "2026-05-01", "symbol": "aapl", "close": 1.0},
            {"date": "2026-05-01", "symbol": "MSFT", "close": 9.0},
        ]
    )

    result = filter_daily_bars_by_ticker(bars, "AAPL")

    assert result["close"].tolist() == [1.0, 2.0]
    assert str(result.loc[0, "date"].date()) == "2026-05-01"
