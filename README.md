# finbot-dashboard

A lightweight, read-only Streamlit dashboard for the Finbot project.

The dashboard reads the shared Finbot data root, uses the catalog produced by `finbot-catalog` as its source of truth, and displays dataset health plus stock-specific reference and daily bar data.

## What It Does

- Loads `$FINBOT_DATA_ROOT/catalog/dataset_catalog.parquet`
- Shows catalog health for known and future datasets
- Reads parquet files referenced by the catalog when needed
- Provides ticker search from `reference.tickers`
- Shows basic stock metadata, a close-price chart, recent OHLCV rows, optional latest ratios, optional ticker details, and optional related tickers
- Uses short Streamlit cache TTLs so refreshed data becomes visible without rebuilding or restarting the container

## What It Does Not Do

- It does not copy, move, or own raw datasets
- It does not download data or call external APIs
- It does not compute features, train models, or orchestrate jobs
- It does not require a database, DuckDB, FastAPI, or authentication

## Expected Layout

```text
finbot/
├── data/
│   ├── market/
│   ├── reference/
│   ├── features/
│   ├── models/
│   └── catalog/
└── repos/
    ├── finbot-data/
    ├── finbot-catalog/
    └── finbot-dashboard/
```

The dashboard expects `finbot-catalog` to write:

- `$FINBOT_DATA_ROOT/catalog/dataset_catalog.parquet`
- `$FINBOT_DATA_ROOT/catalog/dataset_catalog.json`

The parquet catalog is used by the app. Dataset paths inside the catalog may be relative to `FINBOT_DATA_ROOT` or absolute.

Stock detail uses these catalog dataset names when present:

- `market.daily_bars.historical`
- `ratios.ratios`
- `reference.tickers`
- `reference.ticker_details`
- `reference.related_tickers`

## Local Run

From this repository:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export FINBOT_DATA_ROOT=/path/to/finbot/data
streamlit run app.py
```

If `FINBOT_DATA_ROOT` is not set, the app tries to infer the standard local layout where this repo lives at `finbot/repos/finbot-dashboard` and data lives at `finbot/data`.

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

Inside Docker, `FINBOT_DATA_ROOT` defaults to `/data`. The image contains app code only; data is supplied by the mounted host directory.

## Data Refresh

The app is read-only and uses `st.cache_data` with a short TTL. By default, cached file reads expire after 120 seconds.

To change the TTL:

```bash
export FINBOT_DASHBOARD_CACHE_TTL_SECONDS=60
```

When `finbot-catalog` or another data process refreshes files under the shared data root, the dashboard sees the new catalog and parquet files after the cache expires. The dashboard container does not need to be rebuilt or restarted for normal data refreshes.

## Tests

```bash
pytest
```

The tests cover data root resolution, catalog loading, catalog path resolution, missing catalog behavior, ticker filtering, daily bar filtering, latest ratio row selection, and graceful handling of optional unavailable datasets.
