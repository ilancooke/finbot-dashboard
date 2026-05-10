from __future__ import annotations

import pandas as pd
import streamlit as st


def line_chart(frame: pd.DataFrame, x: str, y: str | list[str], height: int = 320) -> None:
    if frame.empty or x not in frame.columns:
        st.info("No chartable data is available.")
        return
    columns = [y] if isinstance(y, str) else y
    available = [column for column in columns if column in frame.columns]
    if not available:
        st.info("The required chart columns are not available.")
        return
    chart = frame[[x, *available]].dropna(subset=[x]).copy()
    if chart.empty:
        st.info("No chartable data is available.")
        return
    st.line_chart(chart.set_index(x)[available], height=height)


def indexed_price_chart(indexed_prices: pd.DataFrame, height: int = 320) -> None:
    if indexed_prices.empty or not {"date", "ticker", "indexed_close"}.issubset(indexed_prices.columns):
        st.info("No peer price comparison is available for this date window.")
        return
    chart = indexed_prices.pivot_table(index="date", columns="ticker", values="indexed_close", aggfunc="last")
    st.line_chart(chart, height=height)


def metric_bar_chart(frame: pd.DataFrame, label_column: str, value_column: str, height: int = 280) -> None:
    if frame.empty or label_column not in frame.columns or value_column not in frame.columns:
        st.info("No comparison data is available.")
        return
    chart = frame[[label_column, value_column]].dropna(subset=[value_column]).copy()
    if chart.empty:
        st.info("No comparison data is available.")
        return
    st.bar_chart(chart.set_index(label_column)[value_column], height=height)

