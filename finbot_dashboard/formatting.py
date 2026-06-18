from __future__ import annotations

import pandas as pd


def is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def format_plain(value: object) -> str:
    if is_missing(value):
        return "N/A"
    if isinstance(value, float):
        return f"{value:,.2f}"
    timestamp = pd.to_datetime(value, errors="coerce")
    if not pd.isna(timestamp) and not isinstance(value, int | float):
        return str(timestamp.date())
    return str(value)
