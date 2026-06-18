# finbot-dashboard

A read-only Streamlit dashboard for Finbot data operations and stock research views.

The app reads only local catalog files under `FINBOT_DATA_ROOT`. It does not call external APIs,
download data, mutate datasets, compute features, or orchestrate jobs.

## Purpose

This dashboard shows the current state of local Finbot datasets and provides local stock research
views backed by cataloged parquet datasets.

The ops pages show:

- Which expected datasets are present or missing.
- Which datasets are fresh, stale, partial, failed, or unknown.
- Which datasets are registered versus only discovered by scanning.
- Latest dataset date, provider update bounds, row counts, entity counts, duplicate key counts,
  and latest-date coverage where available.

## Pages

- **Data Health**: status counts, discovery counts, attention table, latest coverage table, and
  filtered dataset-state records from `ops_catalog.parquet`.
- **Catalog Explorer**: compact view of `dataset_catalog.parquet`, including paths, ownership,
  schema metadata, and detailed record JSON.
- **Stock Overview**: ticker lookup, company metadata, adjusted price history, latest valuation
  metrics, valuation history charts, and Sharadar metric descriptions.

## Expected Data Layout

```text
finbot/
├── data/
│   └── catalog/
│       ├── dataset_catalog.parquet
│       ├── dataset_catalog.json
│       ├── ops_catalog.parquet
│       └── ops_catalog.json
│   ├── fundamentals/
│   │   └── daily_valuation_metrics.parquet
│   ├── market/
│   │   └── daily_bars/
│   │       └── historical.parquet
│   ├── reference/
│   │   └── tickers.parquet
│   └── temp/
│       └── SHARADAR-INDICATORS.csv
└── repos/
    └── finbot-dashboard/
```

Rebuild the catalog after data-producing packages add or materially change parquet files:

```bash
cd /Users/ilan/workspace/finbot/repos/finbot-catalog
FINBOT_DATA_ROOT=/Users/ilan/workspace/finbot/data \
.venv/bin/python scripts/build_catalog.py
```

## Local Run

From this repository:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
export FINBOT_DATA_ROOT=/Users/ilan/workspace/finbot/data
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

Inside Docker, `FINBOT_DATA_ROOT` defaults to `/data`. The image contains app code only; data is
supplied by the mounted host directory.

## Data Refresh

The app uses `st.cache_data` for local catalog reads. By default, cached reads expire after 120
seconds:

```bash
export FINBOT_DASHBOARD_CACHE_TTL_SECONDS=60
```

After `finbot-data` writes parquet files and `finbot-catalog` rebuilds the catalog, the dashboard
sees refreshed data after the cache expires.

## Stock Overview Data

The Stock Overview page resolves its parquet inputs from `dataset_catalog.parquet`:

- `reference.tickers`: stock selector and company metadata.
- `market.daily_bars.historical`: price history keyed by `symbol` and `date`.
- `fundamentals.daily_valuation_metrics`: valuation history keyed by `ticker` and `date`.

It also reads `temp/SHARADAR-INDICATORS.csv` for friendly valuation metric names and descriptions.
All reads are local and filtered to the selected ticker.

## Code Layout

- `app.py`: Streamlit navigation shell and ops pages.
- `finbot_dashboard/data_loader.py`: data-root resolution, catalog loading, and ops filtering.
- `finbot_dashboard/stock_data.py`: stock-reference, price-history, valuation-history, and
  Sharadar indicator loading.
- `finbot_dashboard/formatting.py`: display formatting helpers.
- `finbot_dashboard/config.py`: catalog filenames and cache settings.

## Tests

```bash
pytest
```

Tests cover data-root resolution, catalog loading, ops loading, status summaries, attention
records, coverage records, ops filtering, stock dataset path resolution, ticker lookup, price
history, valuation history, and Sharadar indicator labels.
