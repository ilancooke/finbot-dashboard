from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from finbot_dashboard.data_access import (
    CATALOG_COLUMNS,
    catalog_path,
    filter_daily_bars_by_ticker,
    filter_tickers,
    find_latest_ticker_row,
    find_ticker_row,
    load_catalog,
    read_dataset,
    resolve_data_root,
)

TICKERS_DATASET = "reference.tickers"
DETAILS_DATASET = "reference.ticker_details"
RELATED_DATASET = "reference.related_tickers"
DAILY_BARS_DATASET = "market.daily_bars.historical"
RATIOS_DATASET = "ratios.ratios"
CACHE_TTL_SECONDS = int(os.environ.get("FINBOT_DASHBOARD_CACHE_TTL_SECONDS", "120"))
PERCENT_RATIO_FIELDS = {
    "dividend_yield",
    "return_on_assets",
    "return_on_equity",
}
MONEY_RATIO_FIELDS = {
    "price",
    "market_cap",
    "earnings_per_share",
    "enterprise_value",
    "free_cash_flow",
}
COMPACT_RATIO_FIELDS = {
    "average_volume",
}


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def cached_catalog(data_root: str) -> pd.DataFrame:
    return load_catalog(data_root)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def cached_dataset(data_root: str, catalog_records: tuple[tuple[object, ...], ...], dataset_name: str) -> pd.DataFrame:
    catalog = pd.DataFrame.from_records(catalog_records, columns=CATALOG_COLUMNS)
    return read_dataset(catalog, dataset_name, data_root)


def main() -> None:
    st.set_page_config(page_title="Finbot Dashboard", layout="wide")
    st.title("Finbot Dashboard")

    data_root = resolve_data_root()
    st.caption(f"Data root: `{data_root}`")

    catalog = cached_catalog(str(data_root))
    if catalog.empty:
        st.error(f"No catalog found at `{catalog_path(data_root)}`.")
        st.info("Set FINBOT_DATA_ROOT to the shared Finbot data directory, or mount it to /data in Docker.")
        return

    catalog_records = tuple(tuple(row) for row in catalog.reindex(columns=CATALOG_COLUMNS).itertuples(index=False, name=None))

    tickers = cached_dataset(str(data_root), catalog_records, TICKERS_DATASET)
    details = cached_dataset(str(data_root), catalog_records, DETAILS_DATASET)
    related = cached_dataset(str(data_root), catalog_records, RELATED_DATASET)
    daily_bars = cached_dataset(str(data_root), catalog_records, DAILY_BARS_DATASET)
    ratios = cached_dataset(str(data_root), catalog_records, RATIOS_DATASET)

    selected_ticker = ticker_selector(tickers)

    overview_tab, lookup_tab, detail_tab = st.tabs(["Data Health", "Stock Lookup", "Stock Detail"])
    with overview_tab:
        render_catalog_overview(catalog, data_root)
    with lookup_tab:
        render_stock_lookup(tickers, selected_ticker)
    with detail_tab:
        render_stock_detail(selected_ticker, tickers, details, related, daily_bars, ratios)


def ticker_selector(tickers: pd.DataFrame) -> str | None:
    st.sidebar.header("Ticker")
    if tickers.empty or "ticker" not in tickers.columns:
        st.sidebar.warning("Ticker dataset is unavailable.")
        return None

    query = st.sidebar.text_input("Search", value="")
    matches = filter_tickers(tickers, query, limit=250)
    if matches.empty:
        st.sidebar.info("No matching tickers.")
        return None

    options = matches["ticker"].dropna().astype(str).tolist()
    current = st.session_state.get("selected_ticker")
    index = options.index(current) if current in options else 0
    selected = st.sidebar.selectbox("Select ticker", options=options, index=index, format_func=lambda value: ticker_label(matches, value))
    st.session_state["selected_ticker"] = selected
    return selected


def render_catalog_overview(catalog: pd.DataFrame, data_root: Path) -> None:
    st.subheader("Data Health / Catalog Overview")
    st.write(f"Catalog: `{catalog_path(data_root)}`")

    statuses = catalog["status"].fillna("unknown").astype(str).str.lower() if "status" in catalog.columns else pd.Series(dtype=str)
    columns = st.columns(5)
    for column, status in zip(columns, ["fresh", "stale", "partial", "failed", "missing"]):
        column.metric(status.title(), int((statuses == status).sum()))

    visible_columns = [
        "dataset_name",
        "dataset_group",
        "status",
        "status_reason",
        "row_count",
        "symbol_count",
        "collection_timestamp",
        "data_min_date",
        "data_max_date",
        "metadata_path",
        "parquet_path",
    ]
    available_columns = [column for column in visible_columns if column in catalog.columns]
    view = catalog[available_columns].copy()
    st.dataframe(view.style.apply(highlight_status, axis=1), width="stretch", hide_index=True)


def render_stock_lookup(tickers: pd.DataFrame, selected_ticker: str | None) -> None:
    st.subheader("Stock Lookup")
    if tickers.empty:
        st.warning("The reference.tickers dataset is unavailable.")
        return
    if not selected_ticker:
        st.info("Search for a ticker in the sidebar.")
        return

    row = find_ticker_row(tickers, selected_ticker)
    if row is None:
        st.warning(f"No ticker record found for `{selected_ticker}`.")
        return

    st.markdown(f"### {value(row, 'ticker')} - {value(row, 'name')}")
    fields = [
        ("Exchange", "primary_exchange"),
        ("Type", "type"),
        ("Active", "active"),
        ("Currency", "currency_name"),
        ("Market", "market"),
        ("CIK", "cik"),
        ("Composite FIGI", "composite_figi"),
        ("Share Class FIGI", "share_class_figi"),
    ]
    render_fields(row, fields)


def render_stock_detail(
    selected_ticker: str | None,
    tickers: pd.DataFrame,
    details: pd.DataFrame,
    related: pd.DataFrame,
    daily_bars: pd.DataFrame,
    ratios: pd.DataFrame,
) -> None:
    st.subheader("Stock Detail")
    if not selected_ticker:
        st.info("Search for a ticker in the sidebar.")
        return

    ticker_row = find_ticker_row(tickers, selected_ticker)
    name = value(ticker_row, "name") if ticker_row is not None else "Unknown security"
    st.markdown(f"### {selected_ticker} - {name}")

    ticker_bars = filter_daily_bars_by_ticker(daily_bars, selected_ticker)
    if ticker_bars.empty:
        st.info(f"No daily bars are available for `{selected_ticker}`.")
    else:
        render_price_history(ticker_bars)

    render_latest_ratios(ratios, selected_ticker)
    render_ticker_details(details, selected_ticker)
    render_related_tickers(related, selected_ticker)


def render_price_history(ticker_bars: pd.DataFrame) -> None:
    if "date" not in ticker_bars.columns or "close" not in ticker_bars.columns:
        st.info("Daily bars are present, but date/close columns are not available for charting.")
        return

    clean = ticker_bars.dropna(subset=["date", "close"]).copy()
    if clean.empty:
        st.info("Daily bars are present, but no close prices are available for charting.")
        return

    start = clean["date"].min().date()
    end = clean["date"].max().date()
    st.caption(f"Available range: {start} to {end}")
    st.line_chart(clean.set_index("date")["close"], height=320)

    recent_columns = [column for column in ["date", "open", "high", "low", "close", "volume"] if column in clean.columns]
    recent = clean[recent_columns].sort_values("date", ascending=False).head(30)
    st.markdown("#### Recent OHLCV")
    st.dataframe(recent, width="stretch", hide_index=True)


def render_ticker_details(details: pd.DataFrame, ticker: str) -> None:
    st.markdown("#### Company Details")
    row = find_ticker_row(details, ticker)
    if row is None:
        st.info("No ticker details are available for this symbol.")
        return

    description = value(row, "description")
    if description != "N/A":
        st.write(description)

    fields = [
        ("SIC", "sic_code"),
        ("SIC Description", "sic_description"),
        ("Market Cap", "market_cap"),
        ("Homepage", "homepage_url"),
        ("Employees", "total_employees"),
        ("Listing Date", "list_date"),
        ("Phone", "phone_number"),
    ]
    render_fields(row, fields)


def render_latest_ratios(ratios: pd.DataFrame, ticker: str) -> None:
    st.markdown("#### Latest Ratios")
    row = find_latest_ticker_row(ratios, ticker)
    if row is None:
        st.info("No ratios are available for this symbol.")
        return

    date = ratio_value(row, "date")
    price = ratio_value(row, "price")
    st.caption(f"Ratio date: {date} | Price: {price}")

    valuation_fields = [
        ("Market Cap", "market_cap"),
        ("P/E", "price_to_earnings"),
        ("P/B", "price_to_book"),
        ("P/S", "price_to_sales"),
        ("EV/Sales", "ev_to_sales"),
        ("EV/EBITDA", "ev_to_ebitda"),
    ]
    profitability_fields = [
        ("EPS", "earnings_per_share"),
        ("Dividend Yield", "dividend_yield"),
        ("ROA", "return_on_assets"),
        ("ROE", "return_on_equity"),
        ("Free Cash Flow", "free_cash_flow"),
    ]
    liquidity_fields = [
        ("Debt/Equity", "debt_to_equity"),
        ("Current", "current"),
        ("Quick", "quick"),
        ("Cash", "cash"),
        ("Average Volume", "average_volume"),
    ]

    render_ratio_fields(row, valuation_fields)
    with st.expander("Profitability and liquidity ratios", expanded=False):
        render_ratio_fields(row, profitability_fields)
        render_ratio_fields(row, liquidity_fields)


def render_related_tickers(related: pd.DataFrame, ticker: str) -> None:
    st.markdown("#### Related Tickers")
    if related.empty or "ticker" not in related.columns or "related_ticker" not in related.columns:
        st.info("No related ticker dataset is available.")
        return

    rows = related.loc[related["ticker"].fillna("").astype(str).str.upper() == ticker.upper()].copy()
    if rows.empty:
        st.info("No related tickers are available for this symbol.")
        return
    if "result_order" in rows.columns:
        rows = rows.sort_values("result_order")
    st.write(", ".join(rows["related_ticker"].dropna().astype(str).tolist()))


def render_fields(row: pd.Series, fields: list[tuple[str, str]]) -> None:
    cols = st.columns(4)
    for index, (label, key) in enumerate(fields):
        cols[index % 4].metric(label, value(row, key))


def render_ratio_fields(row: pd.Series, fields: list[tuple[str, str]]) -> None:
    cols = st.columns(4)
    for index, (label, key) in enumerate(fields):
        cols[index % 4].metric(label, ratio_value(row, key))


def value(row: pd.Series | None, key: str) -> str:
    if row is None or key not in row:
        return "N/A"
    item = row[key]
    if pd.isna(item):
        return "N/A"
    if isinstance(item, float):
        return f"{item:,.2f}"
    return str(item)


def ratio_value(row: pd.Series | None, key: str) -> str:
    if row is None or key not in row:
        return "N/A"
    item = row[key]
    if pd.isna(item):
        return "N/A"
    if key == "date":
        parsed = pd.to_datetime(item, errors="coerce")
        if pd.isna(parsed):
            return str(item)
        return str(parsed.date())
    if key in PERCENT_RATIO_FIELDS:
        return f"{float(item) * 100:,.2f}%"
    if key in MONEY_RATIO_FIELDS:
        return compact_number(float(item), prefix="$")
    if key in COMPACT_RATIO_FIELDS:
        return compact_number(float(item))
    if isinstance(item, int | float):
        return f"{item:,.2f}"
    return str(item)


def compact_number(number: float, prefix: str = "") -> str:
    absolute = abs(number)
    for suffix, divisor in [("T", 1_000_000_000_000), ("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)]:
        if absolute >= divisor:
            return f"{prefix}{number / divisor:,.2f}{suffix}"
    return f"{prefix}{number:,.2f}"


def ticker_label(matches: pd.DataFrame, ticker: str) -> str:
    row = find_ticker_row(matches, ticker)
    if row is None:
        return ticker
    name = value(row, "name")
    return ticker if name == "N/A" else f"{ticker} - {name}"


def highlight_status(row: pd.Series) -> list[str]:
    status = str(row.get("status", "")).lower()
    colors = {
        "fresh": "background-color: #e6f4ea",
        "stale": "background-color: #fff4ce",
        "partial": "background-color: #e8f0fe",
        "failed": "background-color: #fce8e6",
        "missing": "background-color: #f1f3f4",
    }
    return [colors.get(status, "") for _ in row]


if __name__ == "__main__":
    main()
