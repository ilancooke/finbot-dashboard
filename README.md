# finbot-dashboard

A read-only Streamlit dashboard for Finbot data operations.

The app reads only local catalog files under `FINBOT_DATA_ROOT`. It does not call external APIs,
download data, mutate datasets, compute features, or orchestrate jobs.

## Purpose

This dashboard shows the current state of local Finbot datasets:

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

## Expected Data Layout

```text
finbot/
├── data/
│   └── catalog/
│       ├── dataset_catalog.parquet
│       ├── dataset_catalog.json
│       ├── ops_catalog.parquet
│       └── ops_catalog.json
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

## Code Layout

- `app.py`: Streamlit navigation shell and ops pages.
- `finbot_dashboard/data_loader.py`: data-root resolution, catalog loading, and ops filtering.
- `finbot_dashboard/formatting.py`: display formatting helpers.
- `finbot_dashboard/config.py`: catalog filenames and cache settings.

## Tests

```bash
pytest
```

Tests cover data-root resolution, catalog loading, ops loading, status summaries, attention
records, coverage records, and ops filtering.
