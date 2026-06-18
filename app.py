from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from finbot_dashboard.config import ATTENTION_STATUSES, HEALTHY_STATUSES
from finbot_dashboard.data_loader import (
    attention_records,
    coverage_records,
    discovery_counts,
    filter_ops_records,
    load_dataset_catalog,
    load_ops_catalog,
    resolve_data_root,
    status_counts,
)
from finbot_dashboard.formatting import format_plain
from finbot_dashboard.stock_data import (
    VALUATION_METRIC_COLUMNS,
    filter_history_range,
    latest_valuation_metrics,
    load_daily_indicator_info,
    load_price_history,
    load_ticker_reference,
    load_valuation_history,
)


@dataclass(frozen=True)
class AppData:
    data_root: Path
    dataset_catalog: pd.DataFrame
    ops_catalog: pd.DataFrame


@dataclass(frozen=True)
class OpsFilters:
    statuses: list[str]
    discovery_statuses: list[str]
    registered_only: bool
    search: str


def main() -> None:
    st.set_page_config(page_title="Finbot Dashboard", page_icon="FB", layout="wide")

    data_root = resolve_data_root(start_path=Path(__file__).resolve())
    data = AppData(
        data_root=data_root,
        dataset_catalog=load_dataset_catalog(str(data_root)),
        ops_catalog=load_ops_catalog(str(data_root)),
    )
    render_global_sidebar(data)

    def render_data_health() -> None:
        data_health_page(data)

    def render_catalog_explorer() -> None:
        catalog_explorer_page(data)

    def render_stock_overview() -> None:
        stock_overview_page(data)

    pages = [
        st.Page(render_data_health, title="Data Health", icon=":material/monitor_heart:"),
        st.Page(render_catalog_explorer, title="Catalog Explorer", icon=":material/table_view:"),
        st.Page(render_stock_overview, title="Stock Overview", icon=":material/candlestick_chart:"),
    ]
    st.navigation(pages, position="sidebar").run()


def render_global_sidebar(data: AppData) -> None:
    st.sidebar.title("Finbot")
    st.sidebar.caption(f"Data root: `{data.data_root}`")


def render_ops_filters(data: AppData) -> OpsFilters:
    ops = data.ops_catalog
    available_statuses = _unique_values(ops, "status")
    default_statuses = [status for status in available_statuses if status in HEALTHY_STATUSES | ATTENTION_STATUSES]
    st.sidebar.subheader("Ops Filters")
    statuses = st.sidebar.multiselect(
        "Status",
        options=available_statuses,
        default=default_statuses,
        key="ops_status",
    )
    discovery_statuses = st.sidebar.multiselect(
        "Discovery",
        options=_unique_values(ops, "discovery_status"),
        default=[],
        key="ops_discovery",
    )
    registered_only = st.sidebar.toggle("Registered only", value=False, key="ops_registered_only")
    search = st.sidebar.text_input("Search", value="", key="ops_search")
    return OpsFilters(
        statuses=statuses,
        discovery_statuses=discovery_statuses,
        registered_only=registered_only,
        search=search,
    )


def data_health_page(data: AppData) -> None:
    st.title("Data Health")
    st.caption(f"Data root: `{data.data_root}`")

    if data.ops_catalog.empty:
        st.warning("`ops_catalog.parquet` is missing or empty. Rebuild the catalog after data refreshes.")
        return

    filters = render_ops_filters(data)
    filtered = filter_ops_records(
        data.ops_catalog,
        statuses=filters.statuses,
        discovery_statuses=filters.discovery_statuses,
        registered_only=filters.registered_only,
        search=filters.search,
    )

    render_summary(data.ops_catalog)
    render_status_distribution(data.ops_catalog)

    problems = attention_records(data.ops_catalog)
    st.subheader("Attention")
    if problems.empty:
        st.success("All cataloged datasets are fresh.")
    else:
        st.dataframe(_display_frame(problems, ATTENTION_COLUMNS), width="stretch", hide_index=True)

    coverage = coverage_records(data.ops_catalog)
    st.subheader("Latest Coverage")
    if coverage.empty:
        st.info("No latest-date coverage metrics are available.")
    else:
        st.dataframe(
            _display_frame(coverage, COVERAGE_COLUMNS),
            width="stretch",
            hide_index=True,
            column_config={
                "latest_date_coverage_pct": st.column_config.ProgressColumn(
                    "latest_date_coverage_pct",
                    min_value=0.0,
                    max_value=1.0,
                    format="%.1f",
                )
            },
        )

    st.subheader("Dataset State")
    st.dataframe(_display_frame(filtered, STATE_COLUMNS), width="stretch", hide_index=True)


def catalog_explorer_page(data: AppData) -> None:
    st.title("Catalog Explorer")
    st.caption(f"Data root: `{data.data_root}`")

    if data.dataset_catalog.empty:
        st.warning("`dataset_catalog.parquet` is missing or empty.")
        return

    render_catalog_summary(data.dataset_catalog)
    st.subheader("Dataset Catalog")
    st.dataframe(_display_frame(data.dataset_catalog, CATALOG_COLUMNS), width="stretch", hide_index=True)

    with st.expander("Schema And Details", expanded=False):
        selected = st.selectbox(
            "Dataset",
            options=data.dataset_catalog["dataset_name"].dropna().astype(str).sort_values().tolist(),
        )
        row = data.dataset_catalog.loc[data.dataset_catalog["dataset_name"].astype(str) == selected]
        if not row.empty:
            st.json(row.iloc[0].to_dict())


def stock_overview_page(data: AppData) -> None:
    st.title("Stock Overview")
    st.caption(f"Data root: `{data.data_root}`")

    tickers = load_ticker_reference(str(data.data_root), data.dataset_catalog)
    if tickers.empty:
        st.warning("`reference.tickers` is missing or empty. Rebuild the catalog and ticker reference dataset.")
        return

    ticker = st.text_input("Ticker", value="AAPL", max_chars=12).strip().upper()
    if not ticker:
        st.info("Enter a ticker symbol.")
        return

    matches = tickers.loc[tickers["ticker"].astype(str).str.upper() == ticker]
    if matches.empty:
        st.warning(f"`{ticker}` is not in `reference.tickers`.")
        return
    selected = matches.iloc[0]

    range_label = st.segmented_control(
        "History",
        options=["1Y", "3Y", "5Y", "10Y", "Max"],
        default="5Y",
    )
    years = {"1Y": 1, "3Y": 3, "5Y": 5, "10Y": 10, "Max": None}[str(range_label)]

    render_stock_header(selected)

    prices = filter_history_range(load_price_history(str(data.data_root), data.dataset_catalog, ticker), years)
    valuations = filter_history_range(load_valuation_history(str(data.data_root), data.dataset_catalog, ticker), years)
    indicators = load_daily_indicator_info(str(data.data_root))

    render_price_history(ticker, prices)
    render_valuation_history(valuations, indicators)


def render_stock_header(stock: pd.Series) -> None:
    st.subheader(f"{stock.get('ticker', '')} - {stock.get('name', 'Unknown Company')}")
    columns = st.columns(5)
    columns[0].metric("Exchange", format_plain(stock.get("exchange")))
    columns[1].metric("Sector", format_plain(stock.get("sector")))
    columns[2].metric("Industry", format_plain(stock.get("industry")))
    columns[3].metric("Market Cap Scale", format_plain(stock.get("scalemarketcap")))
    columns[4].metric("Last Price Date", format_plain(stock.get("lastpricedate")))


def render_price_history(ticker: str, prices: pd.DataFrame) -> None:
    st.subheader("Price History")
    if prices.empty:
        st.info(f"No price history is available for {ticker}.")
        return

    chart_column = "closeadj" if "closeadj" in prices.columns else "close"
    chart_frame = prices.dropna(subset=["date", chart_column]).set_index("date")[[chart_column]]
    st.line_chart(chart_frame, height=320)

    with st.expander("Price Records", expanded=False):
        st.dataframe(_display_frame(prices.tail(250), PRICE_DISPLAY_COLUMNS), width="stretch", hide_index=True)


def render_valuation_history(valuations: pd.DataFrame, indicators: dict) -> None:
    st.subheader("Valuation")
    if valuations.empty:
        st.info("No daily valuation history is available for this stock.")
        return

    latest_metrics = latest_valuation_metrics(valuations, indicators)
    st.dataframe(
        _format_metric_values(latest_metrics),
        width="stretch",
        hide_index=True,
        column_config={
            "description": st.column_config.TextColumn("description", width="large"),
        },
    )

    metric_options = [metric for metric in VALUATION_METRIC_COLUMNS if metric in valuations.columns]
    selected_metrics = st.multiselect(
        "Valuation chart metrics",
        options=metric_options,
        default=[metric for metric in ["pe", "ps", "pb"] if metric in metric_options],
        format_func=lambda metric: indicators.get(metric).title if metric in indicators else metric,
    )
    if selected_metrics:
        chart_frame = valuations.dropna(subset=["date"]).set_index("date")[selected_metrics]
        st.line_chart(chart_frame, height=300)

    with st.expander("Valuation Records", expanded=False):
        display = valuations.copy()
        display = display.rename(columns={metric: indicators[metric].title for metric in indicators if metric in display.columns})
        st.dataframe(_display_frame(display.tail(250), list(display.columns)), width="stretch", hide_index=True)


def render_summary(ops: pd.DataFrame) -> None:
    counts = status_counts(ops)
    total = int(len(ops))
    fresh = counts.get("fresh", 0)
    attention = sum(counts.get(status, 0) for status in ATTENTION_STATUSES)
    missing = counts.get("missing", 0)
    coverage = pd.to_numeric(ops.get("latest_date_coverage_pct"), errors="coerce")
    average_coverage = coverage.dropna().mean()

    columns = st.columns(5)
    columns[0].metric("Datasets", total)
    columns[1].metric("Fresh", fresh)
    columns[2].metric("Attention", attention)
    columns[3].metric("Missing", missing)
    columns[4].metric("Avg Coverage", "N/A" if pd.isna(average_coverage) else f"{average_coverage * 100:.1f}%")


def render_status_distribution(ops: pd.DataFrame) -> None:
    left, right = st.columns(2)
    status_frame = _counts_frame(status_counts(ops), "status")
    discovery_frame = _counts_frame(discovery_counts(ops), "discovery_status")
    with left:
        st.subheader("Status")
        if status_frame.empty:
            st.info("No status values are available.")
        else:
            st.bar_chart(status_frame.set_index("status")["count"], height=220)
    with right:
        st.subheader("Discovery")
        if discovery_frame.empty:
            st.info("No discovery values are available.")
        else:
            st.bar_chart(discovery_frame.set_index("discovery_status")["count"], height=220)


def render_catalog_summary(catalog: pd.DataFrame) -> None:
    registered = int(catalog["is_registered"].fillna(False).astype(bool).sum()) if "is_registered" in catalog else 0
    parquet_present = int(catalog["parquet_exists"].fillna(False).astype(bool).sum()) if "parquet_exists" in catalog else 0
    metadata_present = int(catalog["metadata_exists"].fillna(False).astype(bool).sum()) if "metadata_exists" in catalog else 0
    columns = st.columns(4)
    columns[0].metric("Catalog Records", int(len(catalog)))
    columns[1].metric("Registered", registered)
    columns[2].metric("Parquet Present", parquet_present)
    columns[3].metric("Metadata Present", metadata_present)


def _display_frame(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    available = [column for column in columns if column in frame.columns]
    result = frame[available].copy() if available else frame.copy()
    for column in [
        "date",
        "lastupdated",
        "generated_at_utc",
        "observed_at_utc",
        "min_date",
        "max_date",
        "latest_date",
        "provider_max_lastupdated",
    ]:
        if column in result.columns:
            result[column] = result[column].map(format_plain)
    return result


def _counts_frame(counts: dict[str, int], label: str) -> pd.DataFrame:
    return pd.DataFrame([{label: key, "count": value} for key, value in counts.items()])


def _unique_values(frame: pd.DataFrame, column: str) -> list[str]:
    if frame.empty or column not in frame.columns:
        return []
    return sorted(frame[column].dropna().astype(str).unique().tolist())


def _format_metric_values(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "value" in result.columns:
        result["value"] = result["value"].map(format_plain)
    return result


STATE_COLUMNS = [
    "dataset_name",
    "status",
    "discovery_status",
    "is_registered",
    "row_count",
    "entity_count",
    "max_date",
    "latest_date",
    "latest_date_coverage_pct",
    "provider_max_lastupdated",
    "duplicate_key_count",
    "status_reason",
]

ATTENTION_COLUMNS = [
    "dataset_name",
    "status",
    "discovery_status",
    "status_reason",
    "row_count",
    "max_date",
    "provider_max_lastupdated",
    "missing_required_columns",
]

COVERAGE_COLUMNS = [
    "dataset_name",
    "status",
    "latest_date",
    "latest_date_coverage_count",
    "latest_date_coverage_pct",
    "entity_count",
    "provider_max_lastupdated",
]

CATALOG_COLUMNS = [
    "dataset_name",
    "dataset_group",
    "discovery_status",
    "is_registered",
    "owner_repo",
    "producer_job",
    "provider",
    "write_mode",
    "completeness_profile",
    "row_count",
    "entity_count",
    "min_date",
    "max_date",
    "status",
    "status_reason",
    "parquet_path",
    "metadata_path",
]

PRICE_DISPLAY_COLUMNS = [
    "date",
    "open",
    "high",
    "low",
    "close",
    "closeadj",
    "closeunadj",
    "volume",
    "lastupdated",
]


if __name__ == "__main__":
    main()
