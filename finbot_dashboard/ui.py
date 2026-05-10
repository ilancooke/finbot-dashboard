from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from finbot_dashboard.config import DATE_RANGES, FINANCIAL_TIMEFRAMES
from finbot_dashboard.data_loader import filter_tickers, find_ticker_row
from finbot_dashboard.formatting import format_plain, is_missing


@dataclass(frozen=True)
class SidebarState:
    ticker: str | None
    price_range_label: str
    price_range_days: int | None
    financial_timeframe: str
    peer_mode: str


def render_sidebar(tickers: pd.DataFrame, data_root: Path) -> SidebarState:
    st.sidebar.title("Finbot")
    st.sidebar.caption(f"Data root: `{data_root}`")

    ticker = _ticker_selector(tickers)
    price_range_label = st.sidebar.segmented_control(
        "Price range",
        options=list(DATE_RANGES),
        default=st.session_state.get("price_range_label", "1Y"),
        key="price_range_label",
    )
    timeframe = st.sidebar.selectbox(
        "Financial timeframe",
        options=FINANCIAL_TIMEFRAMES,
        index=FINANCIAL_TIMEFRAMES.index(st.session_state.get("financial_timeframe", "quarterly"))
        if st.session_state.get("financial_timeframe", "quarterly") in FINANCIAL_TIMEFRAMES
        else 0,
        key="financial_timeframe",
    )
    peer_mode = st.sidebar.selectbox("Peer mode", options=["Related tickers only"], index=0)

    return SidebarState(
        ticker=ticker,
        price_range_label=price_range_label,
        price_range_days=DATE_RANGES[price_range_label],
        financial_timeframe=timeframe,
        peer_mode=peer_mode,
    )


def render_kpi_cards(metrics: list[tuple[str, str]]) -> None:
    if not metrics:
        return
    for start in range(0, len(metrics), 5):
        columns = st.columns(5)
        for column, (label, value) in zip(columns, metrics[start : start + 5]):
            column.metric(label, value)


def render_key_value_grid(row: pd.Series | None, fields: list[tuple[str, str]], columns: int = 4) -> None:
    if row is None:
        return
    cols = st.columns(columns)
    for index, (label, key) in enumerate(fields):
        cols[index % columns].metric(label, format_plain(row.get(key)))


def ticker_label(tickers: pd.DataFrame, ticker: str) -> str:
    row = find_ticker_row(tickers, ticker)
    if row is None:
        return ticker
    name = row.get("name")
    return ticker if is_missing(name) else f"{ticker} - {name}"


def warn_missing_dataset(frame: pd.DataFrame, dataset_name: str) -> None:
    if frame.empty:
        st.warning(f"`{dataset_name}` is missing, empty, or unreadable.")


def _ticker_selector(tickers: pd.DataFrame) -> str | None:
    st.sidebar.header("Ticker")
    if tickers.empty or "ticker" not in tickers.columns:
        st.sidebar.warning("Ticker reference data is unavailable.")
        return None

    query = st.sidebar.text_input("Search", value=st.session_state.get("ticker_search", ""), key="ticker_search")
    matches = filter_tickers(tickers, query, limit=300)
    if matches.empty:
        st.sidebar.info("No matching tickers.")
        return None

    options = matches["ticker"].dropna().astype(str).str.upper().drop_duplicates().tolist()
    previous = st.session_state.get("selected_ticker")
    if previous not in options:
        st.session_state["selected_ticker"] = options[0]
        previous = options[0]
    index = options.index(previous)
    selected = st.sidebar.selectbox(
        "Select ticker",
        options=options,
        index=index,
        format_func=lambda value: ticker_label(matches, value),
        key="selected_ticker",
    )
    return selected
