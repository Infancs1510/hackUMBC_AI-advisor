"""Helpers for the dataset's conventions (see data/README.md)."""

from typing import Any

import pandas as pd

NOT_APPLICABLE = "Not Applicable"

# The dataset's "today" is September 15, 2026; Fall 2026 is the in-progress term.
CURRENT_TERM = "Fall 2026"
NEXT_TERM = "Spring 2027"
NEXT_TERM_SEASON = "Spring"


def is_not_applicable(value: Any) -> bool:
    return isinstance(value, str) and value.strip() == NOT_APPLICABLE


def optional_float(value: Any) -> float | None:
    """Parse a numeric cell that may hold the literal 'Not Applicable'.

    'Not Applicable' means "does not apply" -- it is never coerced to 0.
    """
    if value is None or is_not_applicable(value):
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    return float(value)


def optional_str(value: Any) -> str | None:
    if value is None or is_not_applicable(value):
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    return str(value)


def optional_bool(value: Any) -> bool | None:
    """TRUE/FALSE cells load as real booleans, except in columns that also hold 'Not Applicable'."""
    if isinstance(value, bool):
        return value
    text = optional_str(value)
    if text is None:
        return None
    return text.strip().upper() == "TRUE"


def split_pipe(value: Any) -> list[str]:
    """Split a pipe-delimited list cell; 'Not Applicable' yields an empty list."""
    text = optional_str(value)
    if not text:
        return []
    return [part.strip() for part in text.split("|") if part.strip()]


def parse_prerequisites(value: Any) -> list[list[str]]:
    """Parse prerequisite_ids into AND-groups of OR-alternatives.

    'CMSC341|MATH151 or MATH155' -> [['CMSC341'], ['MATH151', 'MATH155']]
    """
    return [
        [alt.strip() for alt in group.split(" or ") if alt.strip()]
        for group in split_pipe(value)
    ]


def term_sort_key(term: str) -> tuple[int, int]:
    """Sort key for terms like 'Fall 2023' (Spring < Summer < Fall within a year)."""
    season, _, year = term.partition(" ")
    order = {"Spring": 0, "Summer": 1, "Fall": 2}
    return (int(year) if year.isdigit() else 0, order.get(season, 3))
