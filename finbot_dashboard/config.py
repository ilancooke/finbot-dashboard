from __future__ import annotations

import os


CATALOG_FILENAME = "dataset_catalog.parquet"
CATALOG_JSON_FILENAME = "dataset_catalog.json"
OPS_CATALOG_FILENAME = "ops_catalog.parquet"
OPS_CATALOG_JSON_FILENAME = "ops_catalog.json"

HEALTHY_STATUSES = {"fresh"}
ATTENTION_STATUSES = {"stale", "missing", "partial", "failed", "unknown"}
CACHE_TTL_SECONDS = int(os.environ.get("FINBOT_DASHBOARD_CACHE_TTL_SECONDS", "120"))
