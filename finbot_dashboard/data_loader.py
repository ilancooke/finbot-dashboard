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
    OPS_CATALOG_FILENAME,
    OPS_CATALOG_JSON_FILENAME,
)


DATASET_CATALOG_COLUMNS = [
    "dataset_name",
    "dataset_group",
    "discovery_status",
    "is_registered",
    "owner_repo",
    "producer_job",
    "metadata_path",
    "parquet_path",
    "metadata_exists",
    "parquet_exists",
    "provider",
    "generated_at_utc",
    "write_mode",
    "completeness_profile",
    "primary_key",
    "date_column",
    "entity_column",
    "row_count",
    "entity_count",
    "min_date",
    "max_date",
    "latest_date",
    "latest_date_coverage_count",
    "latest_date_coverage_pct",
    "provider_min_lastupdated",
    "provider_max_lastupdated",
    "duplicate_key_count",
    "missing_required_columns",
    "parquet_columns",
    "parquet_schema",
    "status",
    "status_reason",
    "catalog_built_at",
    "details_json",
]

OPS_CATALOG_COLUMNS = [
    "record_type",
    "dataset_name",
    "dataset_group",
    "status",
    "status_reason",
    "discovery_status",
    "is_registered",
    "owner_repo",
    "producer_job",
    "write_mode",
    "completeness_profile",
    "row_count",
    "entity_count",
    "min_date",
    "max_date",
    "latest_date",
    "latest_date_coverage_count",
    "latest_date_coverage_pct",
    "provider_min_lastupdated",
    "provider_max_lastupdated",
    "duplicate_key_count",
    "missing_required_columns",
    "generated_at_utc",
    "observed_at_utc",
    "details_json",
]


def resolve_data_root(
    env: dict[str, str] | None = None,
    start_path: str | Path | None = None,
) -> Path:
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


def dataset_catalog_path(data_root: str | Path) -> Path:
    return Path(data_root) / "catalog" / CATALOG_FILENAME


def dataset_catalog_json_path(data_root: str | Path) -> Path:
    return Path(data_root) / "catalog" / CATALOG_JSON_FILENAME


def ops_catalog_path(data_root: str | Path) -> Path:
    return Path(data_root) / "catalog" / OPS_CATALOG_FILENAME


def ops_catalog_json_path(data_root: str | Path) -> Path:
    return Path(data_root) / "catalog" / OPS_CATALOG_JSON_FILENAME


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_dataset_catalog(data_root: str | Path) -> pd.DataFrame:
    return _read_catalog_frame(dataset_catalog_path(data_root), DATASET_CATALOG_COLUMNS)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_ops_catalog(data_root: str | Path) -> pd.DataFrame:
    frame = _read_catalog_frame(ops_catalog_path(data_root), OPS_CATALOG_COLUMNS)
    if not frame.empty and "record_type" in frame.columns:
        frame = frame.loc[frame["record_type"].fillna("").astype(str) == "dataset_state"].copy()
    return frame.reset_index(drop=True)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_dataset_catalog_json(data_root: str | Path) -> list[dict[str, object]]:
    return _read_json_records(dataset_catalog_json_path(data_root))


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_ops_catalog_json(data_root: str | Path) -> list[dict[str, object]]:
    return _read_json_records(ops_catalog_json_path(data_root))


def status_counts(ops: pd.DataFrame) -> dict[str, int]:
    if ops.empty or "status" not in ops.columns:
        return {}
    values = ops["status"].fillna("unknown").astype(str).str.lower()
    return {str(status): int(count) for status, count in values.value_counts().sort_index().items()}


def discovery_counts(ops: pd.DataFrame) -> dict[str, int]:
    if ops.empty or "discovery_status" not in ops.columns:
        return {}
    values = ops["discovery_status"].fillna("unknown").astype(str)
    return {str(status): int(count) for status, count in values.value_counts().sort_index().items()}


def attention_records(ops: pd.DataFrame) -> pd.DataFrame:
    if ops.empty or "status" not in ops.columns:
        return pd.DataFrame(columns=ops.columns)
    statuses = ops["status"].fillna("unknown").astype(str).str.lower()
    return ops.loc[statuses != "fresh"].copy().reset_index(drop=True)


def coverage_records(ops: pd.DataFrame) -> pd.DataFrame:
    if ops.empty or "latest_date_coverage_pct" not in ops.columns:
        return pd.DataFrame(columns=ops.columns)
    coverage = pd.to_numeric(ops["latest_date_coverage_pct"], errors="coerce")
    return ops.loc[coverage.notna()].copy().reset_index(drop=True)


def filter_ops_records(
    ops: pd.DataFrame,
    *,
    statuses: Iterable[str] | None = None,
    discovery_statuses: Iterable[str] | None = None,
    registered_only: bool = False,
    search: str = "",
) -> pd.DataFrame:
    if ops.empty:
        return ops.copy()

    result = ops.copy()
    selected_statuses = {value.lower() for value in statuses or []}
    if selected_statuses and "status" in result.columns:
        result = result.loc[result["status"].fillna("unknown").astype(str).str.lower().isin(selected_statuses)]

    selected_discovery = {value for value in discovery_statuses or []}
    if selected_discovery and "discovery_status" in result.columns:
        result = result.loc[result["discovery_status"].fillna("unknown").astype(str).isin(selected_discovery)]

    if registered_only and "is_registered" in result.columns:
        result = result.loc[result["is_registered"].map(_truthy)]

    needle = search.strip().lower()
    if needle:
        searchable_columns = [
            column
            for column in ["dataset_name", "dataset_group", "status", "discovery_status", "owner_repo", "producer_job"]
            if column in result.columns
        ]
        if searchable_columns:
            mask = pd.Series(False, index=result.index)
            for column in searchable_columns:
                mask |= result[column].fillna("").astype(str).str.lower().str.contains(needle, regex=False)
            result = result.loc[mask]

    return result.sort_values(["status", "dataset_name"], na_position="last").reset_index(drop=True)


def _read_catalog_frame(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)

    try:
        frame = pd.read_parquet(path)
    except (FileNotFoundError, OSError, ValueError, ImportError):
        return pd.DataFrame(columns=columns)

    for column in columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[columns]


def _read_json_records(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        records = payload.get("datasets", payload.get("records", []))
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
    return []


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
