from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from finbot_dashboard import charts
from finbot_dashboard.config import (
    BALANCE_DATASET,
    CASH_FLOW_DATASET,
    DAILY_BARS_DATASET,
    DETAILS_DATASET,
    INCOME_DATASET,
    RATIOS_DATASET,
    RELATED_DATASET,
    TICKERS_DATASET,
)
from finbot_dashboard.data_loader import (
    build_data_quality_frame,
    filter_daily_bars_by_ticker,
    filter_date_range,
    find_ticker_row,
    load_catalog,
    load_catalog_json,
    read_dataset,
    related_ticker_list,
    resolve_data_root,
)
from finbot_dashboard.formatting import (
    format_currency,
    format_percent,
    format_plain,
    format_ratio,
    is_missing,
)
from finbot_dashboard.metrics import (
    build_peer_comparison,
    indexed_price_frame,
    latest_ratio_snapshot,
    prepare_financial_trends,
)
from finbot_dashboard.ui import SidebarState, render_kpi_cards, render_key_value_grid, render_sidebar


@dataclass(frozen=True)
class AppData:
    data_root: Path
    catalog: pd.DataFrame
    catalog_json: list[dict[str, object]]
    tickers: pd.DataFrame
    details: pd.DataFrame
    related: pd.DataFrame
    daily_bars: pd.DataFrame
    ratios: pd.DataFrame
    income: pd.DataFrame
    balance: pd.DataFrame
    cash_flow: pd.DataFrame
    sidebar: SidebarState


def main() -> None:
    st.set_page_config(page_title="Finbot Dashboard", page_icon="FB", layout="wide")

    data_root = resolve_data_root(start_path=Path(__file__).resolve())
    catalog = load_catalog(str(data_root))
    catalog_json = load_catalog_json(str(data_root))

    data = AppData(
        data_root=data_root,
        catalog=catalog,
        catalog_json=catalog_json,
        tickers=read_dataset(str(data_root), TICKERS_DATASET),
        details=read_dataset(str(data_root), DETAILS_DATASET),
        related=read_dataset(str(data_root), RELATED_DATASET),
        daily_bars=read_dataset(str(data_root), DAILY_BARS_DATASET),
        ratios=read_dataset(str(data_root), RATIOS_DATASET),
        income=read_dataset(str(data_root), INCOME_DATASET),
        balance=read_dataset(str(data_root), BALANCE_DATASET),
        cash_flow=read_dataset(str(data_root), CASH_FLOW_DATASET),
        sidebar=render_sidebar(read_dataset(str(data_root), TICKERS_DATASET), data_root),
    )

    def render_overview() -> None:
        overview_page(data)

    def render_price_trends() -> None:
        price_trends_page(data)

    def render_financials() -> None:
        financials_page(data)

    def render_valuation() -> None:
        valuation_page(data)

    def render_peers() -> None:
        peers_page(data)

    def render_data_quality() -> None:
        data_quality_page(data)

    pages = [
        st.Page(render_overview, title="Overview", icon=":material/dashboard:"),
        st.Page(render_price_trends, title="Price Trends", icon=":material/show_chart:"),
        st.Page(render_financials, title="Financials", icon=":material/account_balance:"),
        st.Page(render_valuation, title="Valuation", icon=":material/monitoring:"),
        st.Page(render_peers, title="Peers", icon=":material/groups:"),
        st.Page(render_data_quality, title="Data Quality", icon=":material/database:"),
    ]
    st.navigation(pages, position="sidebar").run()


def overview_page(data: AppData) -> None:
    ticker = require_ticker(data)
    if ticker is None:
        return

    ticker_row = find_ticker_row(data.tickers, ticker)
    detail_row = find_ticker_row(data.details, ticker)
    ratio_row = latest_ratio_snapshot(data.ratios, ticker)

    title = _first_value(detail_row, ticker_row, "name", fallback=ticker)
    st.title(f"{title}")
    st.caption(f"{ticker} | {_first_value(detail_row, ticker_row, 'primary_exchange')} | {_first_value(detail_row, ticker_row, 'sic_description')}")

    if data.details.empty:
        st.warning("Ticker details are unavailable, so company metadata is limited.")
    if ratio_row is None:
        st.warning("Ratio data is unavailable for this ticker, so valuation KPI cards are incomplete.")

    homepage = _first_value(detail_row, ticker_row, "homepage_url")
    description = _first_value(detail_row, ticker_row, "description")
    if homepage != "N/A":
        st.markdown(f"[Company homepage]({homepage})")
    if description != "N/A":
        st.write(description)

    price = _latest_price(data.daily_bars, ticker)
    render_kpi_cards(
        [
            ("Price", format_currency(_ratio_value(ratio_row, "price", price))),
            ("Market cap", format_currency(_ratio_value(ratio_row, "market_cap"))),
            ("Enterprise value", format_currency(_ratio_value(ratio_row, "enterprise_value"))),
            ("P/E", format_ratio(_ratio_value(ratio_row, "price_to_earnings"))),
            ("EPS", format_currency(_ratio_value(ratio_row, "earnings_per_share"))),
            ("Price/Sales", format_ratio(_ratio_value(ratio_row, "price_to_sales"))),
            ("EV/EBITDA", format_ratio(_ratio_value(ratio_row, "ev_to_ebitda"))),
            ("Free cash flow", format_currency(_ratio_value(ratio_row, "free_cash_flow"))),
            ("ROE", format_percent(_ratio_value(ratio_row, "return_on_equity"))),
            ("Debt/Equity", format_ratio(_ratio_value(ratio_row, "debt_to_equity"))),
        ]
    )

    st.subheader("Company Profile")
    render_key_value_grid(
        detail_row if detail_row is not None else ticker_row,
        [
            ("Ticker", "ticker"),
            ("Exchange", "primary_exchange"),
            ("SIC", "sic_description"),
            ("CIK", "cik"),
            ("Employees", "total_employees"),
            ("List date", "list_date"),
            ("Currency", "currency_name"),
            ("Active", "active"),
        ],
    )

    st.subheader("Recent Close Price")
    bars = filter_date_range(filter_daily_bars_by_ticker(data.daily_bars, ticker), "date", data.sidebar.price_range_days)
    charts.line_chart(bars, "date", "close", height=260)


def price_trends_page(data: AppData) -> None:
    ticker = require_ticker(data)
    if ticker is None:
        return

    st.title("Price Trends")
    st.caption(f"{ticker} | {data.sidebar.price_range_label}")

    bars = filter_date_range(filter_daily_bars_by_ticker(data.daily_bars, ticker), "date", data.sidebar.price_range_days)
    if bars.empty:
        st.warning("No price bars are available for the selected ticker and date range.")
    else:
        st.subheader("Close Price")
        charts.line_chart(bars, "date", "close")
        st.subheader("Volume")
        charts.line_chart(bars, "date", "volume", height=220)

    peers = [ticker, *related_ticker_list(data.related, ticker)]
    st.subheader("Indexed Price vs Related Tickers")
    st.caption("Each series is normalized to 100 at its first available date in the selected window.")
    indexed = indexed_price_frame(data.daily_bars, peers, data.sidebar.price_range_days)
    charts.indexed_price_chart(indexed)
    if len(peers) == 1:
        st.info("No related tickers are available for this symbol.")


def financials_page(data: AppData) -> None:
    ticker = require_ticker(data)
    if ticker is None:
        return

    st.title("Financials")
    st.caption(f"{ticker} | {data.sidebar.financial_timeframe}")
    _warn_financial_missing(data)

    trends = prepare_financial_trends(data.income, data.cash_flow, data.balance, ticker, data.sidebar.financial_timeframe)
    if trends.empty:
        st.warning("No statement rows are available for this ticker and timeframe.")
        return

    st.subheader("Income Statement Trends")
    charts.line_chart(
        trends,
        "period_end",
        ["revenue", "gross_profit", "operating_income", "ebitda", "net_income_metric"],
    )

    st.subheader("Cash Flow and Balance Sheet Trends")
    charts.line_chart(
        trends,
        "period_end",
        ["net_cash_from_operating_activities", "free_cash_flow_derived", "cash_and_equivalents", "total_debt"],
    )

    st.subheader("Margins")
    margin_view = trends[["period_end", "timeframe", "gross_margin", "operating_margin", "ebitda_margin", "net_margin"]].copy()
    for column in ["gross_margin", "operating_margin", "ebitda_margin", "net_margin"]:
        margin_view[column] = margin_view[column].map(format_percent)
    st.dataframe(margin_view.sort_values("period_end", ascending=False), width="stretch", hide_index=True)

    st.subheader("Recent Statement Rows")
    display_columns = [
        "period_end",
        "timeframe",
        "revenue",
        "gross_profit",
        "operating_income",
        "ebitda",
        "net_income_metric",
        "net_cash_from_operating_activities",
        "free_cash_flow_derived",
        "cash_and_equivalents",
        "total_debt",
    ]
    st.dataframe(
        _format_money_columns(trends[[column for column in display_columns if column in trends.columns]]),
        width="stretch",
        hide_index=True,
    )


def valuation_page(data: AppData) -> None:
    ticker = require_ticker(data)
    if ticker is None:
        return

    st.title("Valuation")
    st.caption("Snapshot view. The ratios dataset currently appears to be point-in-time rather than a history.")

    ratio_row = latest_ratio_snapshot(data.ratios, ticker)
    if ratio_row is None:
        st.warning("No ratio snapshot is available for this ticker.")
        return

    if "date" in ratio_row:
        st.info(f"Snapshot date: {format_plain(ratio_row.get('date'))}")

    render_kpi_cards(
        [
            ("Price", format_currency(ratio_row.get("price"))),
            ("Market cap", format_currency(ratio_row.get("market_cap"))),
            ("Enterprise value", format_currency(ratio_row.get("enterprise_value"))),
            ("Dividend yield", format_percent(ratio_row.get("dividend_yield"))),
            ("ROE", format_percent(ratio_row.get("return_on_equity"))),
        ]
    )

    metrics = [
        ("P/E", "price_to_earnings", format_ratio),
        ("Price/Sales", "price_to_sales", format_ratio),
        ("Price/Book", "price_to_book", format_ratio),
        ("EV/Sales", "ev_to_sales", format_ratio),
        ("EV/EBITDA", "ev_to_ebitda", format_ratio),
        ("Price/FCF", "price_to_free_cash_flow", format_ratio),
        ("Dividend yield", "dividend_yield", format_percent),
    ]
    rows = [
        {"Metric": label, "Value": ratio_row.get(column), "Display": formatter(ratio_row.get(column))}
        for label, column, formatter in metrics
    ]
    metric_frame = pd.DataFrame(rows)

    st.subheader("Valuation Metrics")
    charts.metric_bar_chart(metric_frame, "Metric", "Value", height=300)
    st.dataframe(metric_frame[["Metric", "Display"]], width="stretch", hide_index=True)


def peers_page(data: AppData) -> None:
    ticker = require_ticker(data)
    if ticker is None:
        return

    st.title("Peers")
    st.caption(data.sidebar.peer_mode)

    peers = related_ticker_list(data.related, ticker)
    if not peers:
        st.warning("No related tickers are available for this ticker.")
    else:
        st.write(", ".join(peers))

    peer_tickers = [ticker, *[peer for peer in peers if peer != ticker]]
    comparison = build_peer_comparison(data.ratios, data.income, peer_tickers, data.sidebar.financial_timeframe)
    columns = [
        "ticker",
        "market_cap",
        "price_to_earnings",
        "price_to_sales",
        "ev_to_ebitda",
        "return_on_equity",
        "debt_to_equity",
        "revenue_growth",
        "ebitda_margin",
    ]
    st.subheader("Peer Comparison")
    st.dataframe(_format_peer_table(comparison[[column for column in columns if column in comparison.columns]]), width="stretch", hide_index=True)

    st.subheader("Indexed Peer Price")
    indexed = indexed_price_frame(data.daily_bars, peer_tickers, data.sidebar.price_range_days)
    charts.indexed_price_chart(indexed)


def data_quality_page(data: AppData) -> None:
    st.title("Data Quality")
    st.caption(f"Data root: `{data.data_root}`")

    if data.catalog_json:
        catalog = pd.DataFrame(data.catalog_json)
        st.caption("Using the JSON catalog for this page.")
    else:
        catalog = data.catalog
        st.warning("Catalog JSON is missing. File existence is inferred from expected dataset paths when catalog rows are unavailable.")

    quality = build_data_quality_frame(data.data_root, catalog)
    if quality.empty:
        st.warning("No dataset quality records could be built.")
        return

    statuses = quality["status"].fillna("unknown").astype(str).str.lower()
    for column, status in zip(st.columns(5), ["fresh", "stale", "partial", "missing", "uncataloged"]):
        column.metric(status.title(), int((statuses == status).sum()))

    st.dataframe(quality, width="stretch", hide_index=True)


def require_ticker(data: AppData) -> str | None:
    if data.sidebar.ticker:
        return data.sidebar.ticker
    st.title("Finbot Dashboard")
    st.info("Select a ticker in the sidebar to begin.")
    return None


def _latest_price(daily_bars: pd.DataFrame, ticker: str) -> object:
    bars = filter_daily_bars_by_ticker(daily_bars, ticker)
    if bars.empty or "close" not in bars.columns or "date" not in bars.columns:
        return pd.NA
    bars = bars.dropna(subset=["date"]).sort_values("date")
    if bars.empty:
        return pd.NA
    return bars.iloc[-1].get("close", pd.NA)


def _ratio_value(row: pd.Series | None, key: str, fallback: object = pd.NA) -> object:
    if row is None or key not in row or is_missing(row.get(key)):
        return fallback
    return row.get(key)


def _first_value(primary: pd.Series | None, secondary: pd.Series | None, key: str, fallback: str = "N/A") -> str:
    for row in [primary, secondary]:
        if row is not None and key in row and not is_missing(row.get(key)):
            return str(row.get(key))
    return fallback


def _warn_financial_missing(data: AppData) -> None:
    missing = []
    for frame, name in [
        (data.income, INCOME_DATASET),
        (data.cash_flow, CASH_FLOW_DATASET),
        (data.balance, BALANCE_DATASET),
    ]:
        if frame.empty:
            missing.append(name)
    if missing:
        st.warning("Missing or unreadable financial datasets: " + ", ".join(f"`{name}`" for name in missing))


def _format_money_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        if column not in {"period_end", "timeframe"}:
            result[column] = result[column].map(format_currency)
    if "period_end" in result.columns:
        result["period_end"] = result["period_end"].map(format_plain)
    return result.sort_values("period_end", ascending=False)


def _format_peer_table(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    formatters = {
        "market_cap": format_currency,
        "price_to_earnings": format_ratio,
        "price_to_sales": format_ratio,
        "ev_to_ebitda": format_ratio,
        "return_on_equity": format_percent,
        "debt_to_equity": format_ratio,
        "revenue_growth": format_percent,
        "ebitda_margin": format_percent,
    }
    for column, formatter in formatters.items():
        if column in result.columns:
            result[column] = result[column].map(formatter)
    return result.fillna("N/A")


if __name__ == "__main__":
    main()
