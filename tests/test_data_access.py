from __future__ import annotations

from pathlib import Path

import pandas as pd

from finbot_dashboard.data_access import (
    attention_records,
    coverage_records,
    dataset_catalog_path,
    filter_ops_records,
    load_dataset_catalog,
    load_ops_catalog,
    ops_catalog_path,
    resolve_data_root,
    status_counts,
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


def test_load_dataset_catalog_returns_empty_frame_when_missing(tmp_path: Path) -> None:
    catalog = load_dataset_catalog(tmp_path)

    assert catalog.empty
    assert "dataset_name" in catalog.columns
    assert "discovery_status" in catalog.columns


def test_load_dataset_catalog_reads_parquet_and_adds_missing_columns(tmp_path: Path) -> None:
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
    ).to_parquet(dataset_catalog_path(tmp_path))

    catalog = load_dataset_catalog(tmp_path)

    assert catalog.loc[0, "dataset_name"] == "reference.tickers"
    assert "status_reason" in catalog.columns
    assert "latest_date_coverage_pct" in catalog.columns


def test_load_ops_catalog_reads_dataset_state_records_only(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    pd.DataFrame(
        [
            {
                "record_type": "dataset_state",
                "dataset_name": "reference.tickers",
                "status": "fresh",
                "discovery_status": "registered_present",
            },
            {
                "record_type": "other_metric",
                "dataset_name": "reference.tickers",
                "status": "fresh",
                "discovery_status": "registered_present",
            },
        ]
    ).to_parquet(ops_catalog_path(tmp_path))

    ops = load_ops_catalog(tmp_path)

    assert ops["record_type"].tolist() == ["dataset_state"]
    assert ops.loc[0, "dataset_name"] == "reference.tickers"


def test_status_counts_and_attention_records() -> None:
    ops = _ops_frame()

    counts = status_counts(ops)
    attention = attention_records(ops)

    assert counts == {"fresh": 1, "missing": 1, "stale": 1}
    assert attention["dataset_name"].tolist() == ["market.daily_bars.historical", "fundamentals.sf1"]


def test_coverage_records_keeps_rows_with_numeric_coverage() -> None:
    ops = _ops_frame()

    coverage = coverage_records(ops)

    assert coverage["dataset_name"].tolist() == ["reference.tickers", "market.daily_bars.historical"]


def test_filter_ops_records_filters_status_registration_and_search() -> None:
    ops = _ops_frame()

    filtered = filter_ops_records(
        ops,
        statuses=["stale"],
        discovery_statuses=["registered_present"],
        registered_only=True,
        search="daily",
    )

    assert filtered["dataset_name"].tolist() == ["market.daily_bars.historical"]


def _ops_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_type": "dataset_state",
                "dataset_name": "reference.tickers",
                "dataset_group": "reference",
                "status": "fresh",
                "discovery_status": "registered_present",
                "is_registered": True,
                "row_count": 2,
                "entity_count": 2,
                "latest_date_coverage_pct": 1.0,
            },
            {
                "record_type": "dataset_state",
                "dataset_name": "market.daily_bars.historical",
                "dataset_group": "market",
                "status": "stale",
                "discovery_status": "registered_present",
                "is_registered": True,
                "row_count": 10,
                "entity_count": 2,
                "latest_date_coverage_pct": 0.5,
            },
            {
                "record_type": "dataset_state",
                "dataset_name": "fundamentals.sf1",
                "dataset_group": "fundamentals",
                "status": "missing",
                "discovery_status": "registered_missing",
                "is_registered": True,
                "row_count": pd.NA,
                "entity_count": pd.NA,
                "latest_date_coverage_pct": pd.NA,
            },
        ]
    )
