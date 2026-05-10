from __future__ import annotations

import pandas as pd

from finbot_dashboard.metrics import (
    build_peer_comparison,
    indexed_price_frame,
    prepare_financial_trends,
    safe_divide,
)


def test_safe_divide_handles_zero_and_null_denominators() -> None:
    result = safe_divide(pd.Series([10.0, 10.0, 10.0]), pd.Series([2.0, 0.0, None]))

    assert result.iloc[0] == 5.0
    assert pd.isna(result.iloc[1])
    assert pd.isna(result.iloc[2])


def test_prepare_financial_trends_adds_derived_statement_metrics() -> None:
    income = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "period_end": "2026-03-31",
                "timeframe": "quarterly",
                "revenue": 100.0,
                "gross_profit": 40.0,
                "operating_income": 30.0,
                "ebitda": 35.0,
                "consolidated_net_income_loss": 20.0,
            }
        ]
    )
    cash_flow = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "period_end": "2026-03-31",
                "timeframe": "quarterly",
                "net_cash_from_operating_activities": 25.0,
                "purchase_of_property_plant_and_equipment": -5.0,
            }
        ]
    )
    balance = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "period_end": "2026-03-31",
                "timeframe": "quarterly",
                "cash_and_equivalents": 8.0,
                "debt_current": 4.0,
                "long_term_debt_and_capital_lease_obligations": 6.0,
            }
        ]
    )

    result = prepare_financial_trends(income, cash_flow, balance, "AAPL", "quarterly")

    assert result.loc[0, "gross_margin"] == 0.4
    assert result.loc[0, "operating_margin"] == 0.3
    assert result.loc[0, "ebitda_margin"] == 0.35
    assert result.loc[0, "net_margin"] == 0.2
    assert result.loc[0, "total_debt"] == 10.0
    assert result.loc[0, "net_debt"] == 2.0
    assert result.loc[0, "free_cash_flow_derived"] == 20.0


def test_indexed_price_frame_normalizes_each_ticker_to_first_available_close() -> None:
    bars = pd.DataFrame(
        [
            {"date": "2026-01-01", "symbol": "AAPL", "close": 10.0},
            {"date": "2026-01-02", "symbol": "AAPL", "close": 12.0},
            {"date": "2026-01-02", "symbol": "MSFT", "close": 20.0},
            {"date": "2026-01-03", "symbol": "MSFT", "close": 22.0},
        ]
    )

    result = indexed_price_frame(bars, ["AAPL", "MSFT"], days=None)

    aapl = result.loc[result["ticker"] == "AAPL", "indexed_close"].tolist()
    msft = result.loc[result["ticker"] == "MSFT", "indexed_close"].tolist()
    assert aapl == [100.0, 120.0]
    assert msft == [100.0, 110.00000000000001]


def test_build_peer_comparison_keeps_missing_peer_values_visible() -> None:
    ratios = pd.DataFrame(
        [{"ticker": "AAPL", "date": "2026-05-07", "market_cap": 100.0, "price_to_sales": 5.0}]
    )
    income = pd.DataFrame(
        [
            {"ticker": "AAPL", "period_end": "2025-12-31", "timeframe": "annual", "revenue": 90.0, "ebitda": 18.0},
            {"ticker": "AAPL", "period_end": "2026-12-31", "timeframe": "annual", "revenue": 99.0, "ebitda": 22.0},
        ]
    )

    result = build_peer_comparison(ratios, income, ["AAPL", "MSFT"], "annual")

    assert result["ticker"].tolist() == ["AAPL", "MSFT"]
    assert result.loc[0, "revenue_growth"] == 0.1
    assert pd.isna(result.loc[1, "market_cap"])

