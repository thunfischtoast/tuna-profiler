"""Type names, type families and display rules.

Type names: null, bool, int, float, str, date, datetime, time, duration, object, array;
other Polars dtypes keep their lowercased name (e.g. binary).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import polars as pl

_FAMILIES = {"int": "numeric", "float": "numeric", "date": "temporal", "datetime": "temporal"}


def polars_type_name(dtype: pl.DataType) -> str:
    """Map a Polars dtype to a tuna type name."""
    if dtype == pl.Boolean:
        return "bool"
    if dtype.is_integer():
        return "int"
    if dtype.is_float() or dtype.is_decimal():
        return "float"
    if dtype == pl.Date:
        return "date"
    if dtype == pl.Datetime:
        return "datetime"
    if dtype == pl.Time:
        return "time"
    if dtype in (pl.List, pl.Array):
        return "array"
    if dtype == pl.Struct:
        return "object"
    if dtype == pl.Duration:
        return "duration"
    if dtype == pl.Null:
        return "null"
    if dtype in (pl.String, pl.Categorical, pl.Enum):
        return "str"
    return dtype.base_type().__name__.lower()


def python_type_name(value: Any) -> str:
    """Map a parsed JSON/YAML value to a tuna type name."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, dt.datetime):
        return "datetime"
    if isinstance(value, dt.date):
        return "date"
    if isinstance(value, dt.time):
        return "time"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "str"


def family(type_name: str) -> str:
    """Return the compatibility family of a type name."""
    return _FAMILIES.get(type_name, type_name)


def families(types: set[str]) -> frozenset[str]:
    """Families of the non-null types in ``types``."""
    return frozenset(family(t) for t in types if t != "null")


def compatible(a: set[str], b: set[str]) -> bool:
    """True if two observed type sets may belong to the same field.

    A null-only side is compatible with anything; otherwise the families must match.
    """
    fa, fb = families(a), families(b)
    return not fa or not fb or fa == fb


def display_type(types: set[str]) -> str:
    """Merge observed type names into one display string."""
    shown = set(types) - {"null"} or {"null"}
    if shown == {"int", "float"}:
        return "float"
    if shown == {"date", "datetime"}:
        return "datetime"
    return "|".join(sorted(shown))
