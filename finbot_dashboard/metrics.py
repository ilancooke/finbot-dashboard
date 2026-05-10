from __future__ import annotations

import numpy as np
import pandas as pd

from finbot_dashboard.data_loader import filter_ticker, latest_by_date


def safe_divide(numerator: object, denominator: object) -> object:
    """Divide while returning NA for missing or zero denominators."""
    num = pd.to_numeric(numerator, errors="coerce")
    den = pd.to_numeric(denominator, errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        result = num / den

    if isinstance(result, pd.Series):
        return result.where((den != 0) & den.notna())
    if pd.isna(den) or den == 0 or pd.isna(result):
        return pd.NA
    return result


def add_statement_metrics(financials: pd.DataFrame) -> pd.DataFrame:
    """Add temporary derived financial metrics for dashboard v1."""
    result = financials.copy()
    result["net_income_metric"] = _net_income(result)
    result["gross_margin"] = safe_divide(_col(result, "gross_profit"), _col(result, "revenue"))
    result["operating_margin"] = safe_divide(_col(result, "operating_income"), _col(result, "revenue"))
    result["ebitda_margin"] = safe_divide(_col(result, "ebitda"), _col(result, "revenue"))
    result["net_margin"] = safe_divide(result["net_income_metric"], _col(result, "revenue"))
    current_debt = _col(result, "debt_current")
    long_term_debt = _col(result, "long_term_debt_and_capital_lease_obligations")
    result["total_debt"] = (current_debt.fillna(0) + long_term_debt.fillna(0)).where(
        current_debt.notna() | long_term_debt.notna()
    )
    result["net_debt"] = result["total_debt"] - _col(result, "cash_and_equivalents").fillna(0)
    result["free_cash_flow_derived"] = _col(result, "net_cash_from_operating_activities") - _col(
        result, "purchase_of_property_plant_and_equipment"
    ).abs()
    return result


def prepare_financial_trends(
    income: pd.DataFrame,
    cash_flow: pd.DataFrame,
    balance: pd.DataFrame,
    ticker: str,
    timeframe: str,
) -> pd.DataFrame:
    """Merge statement datasets into one period-indexed trend table."""
    income_rows = _filter_statement(income, ticker, timeframe)
    cash_rows = _filter_statement(cash_flow, ticker, timeframe)
    balance_rows = _filter_statement(balance, ticker, timeframe)

    if income_rows.empty and cash_rows.empty and balance_rows.empty:
        return pd.DataFrame()

    keys = ["ticker", "period_end", "timeframe"]
    income_cols = keys + _available(
        income_rows,
        [
            "revenue",
            "gross_profit",
            "operating_income",
            "ebitda",
            "consolidated_net_income_loss",
            "net_income_loss_attributable_common_shareholders",
        ],
    )
    cash_cols = keys + _available(
        cash_rows,
        [
            "net_cash_from_operating_activities",
            "purchase_of_property_plant_and_equipment",
            "net_income",
        ],
    )
    balance_cols = keys + _available(
        balance_rows,
        [
            "cash_and_equivalents",
            "debt_current",
            "long_term_debt_and_capital_lease_obligations",
        ],
    )

    merged = _select(income_rows, income_cols)
    for rows, cols in [(_select(cash_rows, cash_cols), cash_cols), (_select(balance_rows, balance_cols), balance_cols)]:
        if rows.empty:
            continue
        if merged.empty:
            merged = rows
        else:
            merged = merged.merge(rows, on=keys, how="outer")

    if merged.empty:
        return merged
    merged = add_statement_metrics(merged)
    return merged.sort_values(["period_end", "timeframe"]).reset_index(drop=True)


def latest_ratio_snapshot(ratios: pd.DataFrame, ticker: str) -> pd.Series | None:
    rows = filter_ticker(ratios, ticker)
    if rows.empty:
        return None
    latest = latest_by_date(rows, date_column="date")
    return None if latest.empty else latest.iloc[0]


def latest_ratio_table(ratios: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    if ratios.empty or "ticker" not in ratios.columns:
        return pd.DataFrame()

    rows = ratios.loc[ratios["ticker"].fillna("").astype(str).str.upper().isin([t.upper() for t in tickers])].copy()
    if rows.empty:
        return pd.DataFrame()
    rows["ticker"] = rows["ticker"].astype(str).str.upper()
    return latest_by_date(rows, date_column="date", group_column="ticker")


def indexed_price_frame(daily_bars: pd.DataFrame, tickers: list[str], days: int | None) -> pd.DataFrame:
    """Return close prices normalized to 100 at each ticker's first window date."""
    if daily_bars.empty or "close" not in daily_bars.columns or "date" not in daily_bars.columns:
        return pd.DataFrame()

    symbol_column = "symbol" if "symbol" in daily_bars.columns else "ticker" if "ticker" in daily_bars.columns else None
    if symbol_column is None:
        return pd.DataFrame()

    symbols = [ticker.upper() for ticker in tickers]
    rows = daily_bars.loc[daily_bars[symbol_column].fillna("").astype(str).str.upper().isin(symbols)].copy()
    if rows.empty:
        return pd.DataFrame()

    rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
    rows[symbol_column] = rows[symbol_column].astype(str).str.upper()
    rows = rows.dropna(subset=["date", "close"])
    if days is not None and not rows.empty:
        max_date = rows["date"].max()
        rows = rows.loc[rows["date"] >= max_date - pd.Timedelta(days=days)]

    pieces: list[pd.DataFrame] = []
    for symbol, group in rows.sort_values("date").groupby(symbol_column):
        first_close = pd.to_numeric(group["close"], errors="coerce").dropna()
        if first_close.empty or first_close.iloc[0] == 0:
            continue
        indexed = group[["date", "close"]].copy()
        indexed["ticker"] = symbol
        indexed["indexed_close"] = pd.to_numeric(indexed["close"], errors="coerce") / first_close.iloc[0] * 100
        pieces.append(indexed[["date", "ticker", "indexed_close"]])

    if not pieces:
        return pd.DataFrame()
    return pd.concat(pieces, ignore_index=True)


def revenue_growth(income: pd.DataFrame, ticker: str, timeframe: str) -> object:
    rows = _filter_statement(income, ticker, timeframe)
    if rows.empty or "revenue" not in rows.columns:
        return pd.NA

    rows = rows.dropna(subset=["period_end"]).sort_values("period_end")
    revenues = pd.to_numeric(rows["revenue"], errors="coerce").dropna()
    if len(revenues) < 2:
        return pd.NA
    return safe_divide(revenues.iloc[-1] - revenues.iloc[-2], revenues.iloc[-2])


def latest_ebitda_margin(income: pd.DataFrame, ticker: str, timeframe: str) -> object:
    rows = _filter_statement(income, ticker, timeframe)
    if rows.empty:
        return pd.NA
    latest = latest_by_date(rows, date_column="period_end")
    if latest.empty:
        return pd.NA
    row = latest.iloc[0]
    return safe_divide(row.get("ebitda", pd.NA), row.get("revenue", pd.NA))


def build_peer_comparison(
    ratios: pd.DataFrame,
    income: pd.DataFrame,
    tickers: list[str],
    timeframe: str,
) -> pd.DataFrame:
    """Combine latest ratios with lightweight derived peer financial metrics."""
    if not tickers:
        return pd.DataFrame()

    ratio_rows = latest_ratio_table(ratios, tickers)
    if ratio_rows.empty:
        ratio_rows = pd.DataFrame({"ticker": tickers})

    ratio_rows["ticker"] = ratio_rows["ticker"].astype(str).str.upper()
    ratio_rows = ratio_rows.drop_duplicates(subset=["ticker"], keep="first")
    missing = [ticker for ticker in tickers if ticker.upper() not in set(ratio_rows["ticker"])]
    if missing:
        ratio_rows = pd.concat([ratio_rows, pd.DataFrame({"ticker": missing})], ignore_index=True)

    ratio_rows["revenue_growth"] = [revenue_growth(income, ticker, timeframe) for ticker in ratio_rows["ticker"]]
    ratio_rows["ebitda_margin"] = [latest_ebitda_margin(income, ticker, timeframe) for ticker in ratio_rows["ticker"]]
    return ratio_rows


def _filter_statement(frame: pd.DataFrame, ticker: str, timeframe: str) -> pd.DataFrame:
    rows = filter_ticker(frame, ticker)
    if rows.empty:
        return rows
    if "period_end" in rows.columns:
        rows["period_end"] = pd.to_datetime(rows["period_end"], errors="coerce")
    if timeframe != "all" and "timeframe" in rows.columns:
        rows = rows.loc[rows["timeframe"].fillna("").astype(str).str.lower() == timeframe]
    return rows.sort_values("period_end").reset_index(drop=True)


def _net_income(frame: pd.DataFrame) -> pd.Series:
    for column in [
        "consolidated_net_income_loss",
        "net_income_loss_attributable_common_shareholders",
        "net_income",
    ]:
        if column in frame.columns:
            return pd.to_numeric(frame[column], errors="coerce")
    return pd.Series(pd.NA, index=frame.index, dtype="Float64")


def _col(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _available(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    return [column for column in columns if column in frame.columns]


def _select(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    available = [column for column in columns if column in frame.columns]
    if not available:
        return pd.DataFrame()
    return frame[available].copy()
