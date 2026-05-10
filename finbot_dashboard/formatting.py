from __future__ import annotations

import pandas as pd


def is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def format_large_number(value: object) -> str:
    if is_missing(value):
        return "N/A"
    number = float(value)
    absolute = abs(number)
    for suffix, divisor in [("T", 1_000_000_000_000), ("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)]:
        if absolute >= divisor:
            return f"{number / divisor:,.2f}{suffix}"
    return f"{number:,.2f}"


def format_currency(value: object) -> str:
    if is_missing(value):
        return "N/A"
    return f"${format_large_number(value)}"


def format_percent(value: object) -> str:
    if is_missing(value):
        return "N/A"
    return f"{float(value) * 100:,.2f}%"


def format_ratio(value: object) -> str:
    if is_missing(value):
        return "N/A"
    return f"{float(value):,.2f}x"


def format_plain(value: object) -> str:
    if is_missing(value):
        return "N/A"
    if isinstance(value, float):
        return f"{value:,.2f}"
    timestamp = pd.to_datetime(value, errors="coerce")
    if not pd.isna(timestamp) and not isinstance(value, int | float):
        return str(timestamp.date())
    return str(value)

