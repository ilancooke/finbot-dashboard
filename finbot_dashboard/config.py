from __future__ import annotations

import os


CATALOG_FILENAME = "dataset_catalog.parquet"
CATALOG_JSON_FILENAME = "dataset_catalog.json"

TICKERS_DATASET = "reference.tickers"
DETAILS_DATASET = "reference.ticker_details"
RELATED_DATASET = "reference.related_tickers"
DAILY_BARS_DATASET = "market.daily_bars.historical"
RATIOS_DATASET = "ratios.ratios"
INCOME_DATASET = "financials.income_statements"
BALANCE_DATASET = "financials.balance_sheets"
CASH_FLOW_DATASET = "financials.cash_flow_statements"

EXPECTED_DATASETS: dict[str, str] = {
    DAILY_BARS_DATASET: "market/daily_bars/historical.parquet",
    RATIOS_DATASET: "ratios/ratios.parquet",
    TICKERS_DATASET: "reference/tickers.parquet",
    DETAILS_DATASET: "reference/ticker_details.parquet",
    RELATED_DATASET: "reference/related_tickers.parquet",
    INCOME_DATASET: "financials/income_statements.parquet",
    BALANCE_DATASET: "financials/balance_sheets.parquet",
    CASH_FLOW_DATASET: "financials/cash_flow_statements.parquet",
}

DATE_RANGES: dict[str, int | None] = {
    "3M": 92,
    "6M": 183,
    "1Y": 365,
    "2Y": 730,
    "Max": None,
}

FINANCIAL_TIMEFRAMES = ["quarterly", "annual", "all"]
CACHE_TTL_SECONDS = int(os.environ.get("FINBOT_DASHBOARD_CACHE_TTL_SECONDS", "120"))

