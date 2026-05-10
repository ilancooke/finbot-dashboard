# finbot-dashboard

A read-only Streamlit dashboard for local Finbot stock research.

The app reads only local parquet datasets and the catalog under `FINBOT_DATA_ROOT`. It does
not call external APIs, scrape websites, download data, mutate datasets, compute training
features, or orchestrate jobs.

## Purpose

This dashboard is a useful v1 for answering:

- What is this company?
- How has the stock price performed?
- Is the business growing?
- Is the business profitable?
- Is the stock expensive or cheap relative to related tickers?
- Is the data fresh and complete enough to trust?

## Pages

- **Overview**: company profile, description, key valuation/profitability KPI cards, and a
  compact recent close-price chart.
- **Price Trends**: close price, volume, and indexed comparison against related tickers.
- **Financials**: statement trends for revenue, profitability, cash flow, cash, total debt,
  and temporary derived margins.
- **Valuation**: current point-in-time ratio snapshot for the selected ticker.
- **Peers**: related ticker list, peer comparison table, and indexed peer price chart.
- **Data Quality**: catalog records plus local file-existence checks for expected datasets.

## Expected Data Layout

```text
finbot/
├── data/
│   ├── catalog/
│   │   ├── dataset_catalog.parquet
│   │   └── dataset_catalog.json
│   ├── financials/
│   │   ├── balance_sheets.parquet
│   │   ├── cash_flow_statements.parquet
│   │   └── income_statements.parquet
│   ├── market/
│   │   └── daily_bars/
│   │       └── historical.parquet
│   ├── ratios/
│   │   └── ratios.parquet
│   └── reference/
│       ├── related_tickers.parquet
│       ├── ticker_details.parquet
│       └── tickers.parquet
└── repos/
    └── finbot-dashboard/
```

The app prefers catalog paths from `catalog/dataset_catalog.parquet`. If a dataset is not
listed in the catalog, it falls back to the expected v1 paths above so the Data Quality page
can still explain what exists locally.

## Local Run

From this repository:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
export FINBOT_DATA_ROOT=/path/to/finbot/data
streamlit run app.py
```

If `FINBOT_DATA_ROOT` is not set, the app tries to infer the standard local layout where this
repo lives at `finbot/repos/finbot-dashboard` and data lives at `finbot/data`.

## Docker Run

Build:

```bash
docker build -t finbot-dashboard .
```

Run:

```bash
docker run --rm \
  -p 8501:8501 \
  -v /path/to/finbot/data:/data \
  finbot-dashboard
```

Inside Docker, `FINBOT_DATA_ROOT` defaults to `/data`. The image contains app code only; data
is supplied by the mounted host directory.

## Data Refresh

The app uses `st.cache_data` for local dataframe reads. By default, cached reads expire after
120 seconds:

```bash
export FINBOT_DASHBOARD_CACHE_TTL_SECONDS=60
```

After `finbot-data` writes new parquet files and `finbot-catalog` rebuilds the catalog, the
dashboard sees the refreshed data after the cache expires. The dashboard container does not
need to be rebuilt or restarted for normal data refreshes.

## Code Layout

- `app.py`: Streamlit navigation shell and page renderers.
- `finbot_dashboard/data_loader.py`: data-root resolution, catalog loading, parquet reads,
  ticker/date filtering, and data-quality records.
- `finbot_dashboard/metrics.py`: temporary derived calculations used by the dashboard.
- `finbot_dashboard/formatting.py`: display formatting helpers.
- `finbot_dashboard/charts.py`: Streamlit chart wrappers.
- `finbot_dashboard/ui.py`: shared sidebar and reusable UI components.

Financial formulas belong in `metrics.py`, not in Streamlit page functions. This keeps the
temporary calculation layer easy to move into a future `finbot-features` package.

## Known Limitations

- Peer mode only uses `reference.related_tickers`.
- Ratios are displayed as a snapshot because the current `ratios.ratios` dataset is
  point-in-time.
- Peer valuation quality depends on which related tickers are present in the local ratios,
  financials, and daily bars datasets.
- Financial statement datasets can contain partial ticker coverage and mixed quarterly or
  annual rows; missing values are shown rather than invented.
- The dashboard does not create datasets. Rebuild the catalog after data-producing packages
  add or materially change local parquet files.

## Tests

```bash
pytest
```

The tests cover data-root resolution, catalog loading, catalog path resolution, missing
dataset behavior, ticker filtering, daily bar filtering, latest-row selection, safe math,
derived financial metrics, indexed price normalization, and peer comparison fallbacks.

