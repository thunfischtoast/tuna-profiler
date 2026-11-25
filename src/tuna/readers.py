"""Read data files into TableProfiles."""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fastexcel
import polars as pl
import yaml

from tuna.model import (
    DISTINCT_CAP,
    TOP_CAP,
    FieldStats,
    TableProfile,
    safe_max,
    safe_min,
)
from tuna.types import polars_type_name, python_type_name

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
_TOP_TYPES = {"str", "bool", "int"}
_MINMAX_TYPES = {"int", "float", "date", "datetime", "time", "duration", "str"}


def iso_temporal(v: Any) -> Any:
    """Turn dates and datetimes into ISO strings so they compare with JSON date strings."""
    return v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v


@dataclass
class ReadOptions:
    """How much of each file to read.

    ``sample_rows`` rows feed the stats (``None`` = all rows); the schema of tabular
    files always comes from the first ``schema_rows`` rows.
    """

    sample_rows: int | None = 1000
    stats: bool = True
    schema_rows: int = 1000


def read_file(path: Path, rel: str, fmt: str, opts: ReadOptions) -> list[TableProfile]:
    """Profile one file; raises on unreadable input."""
    if fmt in ("csv", "tsv"):
        return [_read_csv(path, rel, fmt, opts)]
    if fmt == "xlsx":
        return _read_excel(path, rel, opts)
    if fmt == "json":
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            doc = json.load(f)
        return [_profile_doc(doc, rel, fmt, opts)]
    if fmt == "yaml":
        with open(path, encoding="utf-8", errors="replace") as f:
            docs = list(yaml.safe_load_all(f))
        if len(docs) > 1:
            # A trailing or doubled "---" yields empty documents, which are not rows.
            docs = [d for d in docs if d is not None]
        doc = docs[0] if len(docs) == 1 else docs
        return [_profile_doc(doc, rel, fmt, opts)]
    raise ValueError(f"unknown format {fmt}")


# --- tabular ---------------------------------------------------------------


def stats_from_series(s: pl.Series, type_name: str) -> FieldStats:
    """Compute FieldStats for one column."""
    st = FieldStats(nulls=s.null_count())
    s = s.drop_nulls()
    st.count = s.len()
    if st.count == 0:
        return st
    if type_name in _MINMAX_TYPES:
        st.min, st.max = iso_temporal(s.min()), iso_temporal(s.max())
    if type_name in ("int", "float"):
        st.sum = float(s.sum())
    if s.dtype == pl.String:
        lens = s.str.len_chars()
        st.min_len, st.max_len = int(lens.min()), int(lens.max())
    if type_name in _TOP_TYPES:
        # A fixed count column name avoids a clash with a data column named "count".
        vc = s.value_counts(sort=True, name="__tuna_count__").head(TOP_CAP)
        st.top = Counter(dict(zip(vc[s.name].to_list(), vc["__tuna_count__"].to_list())))
    if s.dtype.is_nested() or s.dtype == pl.Object or s.n_unique() > DISTINCT_CAP:
        st.distinct = None
    else:
        st.distinct = set(s.unique().to_list())
    return st


def _reinfer(s: pl.Series) -> pl.Series:
    """Type a string column again after its blank cells became null."""
    nulls = s.null_count()
    if nulls == s.len():
        return s
    lower = s.str.to_lowercase()
    if set(lower.drop_nulls().unique().to_list()) <= {"true", "false"}:
        return lower == "true"
    # Plain inference keeps nan/inf text as str, so blanks must not make it float.
    special = lower.str.strip_chars().str.replace(r"^[+-]", "").is_in(["nan", "inf", "infinity"]).any()
    casts = [
        lambda: s.str.to_integer(strict=False),
        *([] if special else [lambda: s.cast(pl.Float64, strict=False)]),
        lambda: s.str.to_date(strict=False),
        lambda: s.str.to_datetime(strict=False),
    ]
    for cast in casts:
        try:
            out = cast()
        except Exception:  # noqa: BLE001, S112 - polars may fail to guess a format
            continue
        if out.null_count() == nulls:
            return out
    return s


def _blank_to_null(s: pl.Series) -> tuple[pl.Series, int]:
    """Turn empty and whitespace-only strings into nulls; return the series and their count."""
    if s.dtype != pl.String:
        return s, 0
    blank = s.str.strip_chars() == ""
    empty = int(blank.sum() or 0)
    if not empty:
        return s, 0
    return _reinfer(s.clone().set(blank.fill_null(False), None)), empty


def _profile_frame(
    df: pl.DataFrame,
    rel: str,
    sheet: str | None,
    fmt: str,
    rows: int,
    opts: ReadOptions,
    warnings: list[str],
) -> TableProfile:
    fields: dict[str, set[str]] = {}
    stats: dict[str, FieldStats] = {}
    for name in df.columns:
        s, empty = _blank_to_null(df[name])
        t = "null" if s.null_count() == s.len() else polars_type_name(s.dtype)
        fields[name] = {t}
        if opts.stats:
            stats[name] = stats_from_series(s, t)
            stats[name].empty = empty
    return TableProfile(rel, sheet, fmt, rows, fields, stats, warnings)


def _sniff(path: Path, fmt: str) -> str:
    with open(path, "rb") as f:
        head = f.read(65536).decode("utf-8", errors="replace")
    try:
        return csv.Sniffer().sniff(head, delimiters=",;\t|").delimiter
    except csv.Error:
        return "\t" if fmt == "tsv" else ","


def _read_csv(path: Path, rel: str, fmt: str, opts: ReadOptions) -> TableProfile:
    common: dict[str, Any] = {
        "separator": _sniff(path, fmt),
        "encoding": "utf8-lossy",
        "truncate_ragged_lines": True,
    }
    m = opts.schema_rows
    n = opts.sample_rows
    warnings: list[str] = []
    try:
        schema = pl.scan_csv(path, infer_schema_length=m, try_parse_dates=True, **common).collect_schema()
    except Exception as e:  # noqa: BLE001 - any inference failure falls back to text
        warnings.append(f"type inference failed, read as text: {str(e).splitlines()[0]}")
        schema = pl.scan_csv(path, infer_schema=False, **common).collect_schema()
    # The schema always comes from the first schema_rows rows, also with --full.
    kw = dict(common, schema=schema, n_rows=n)
    try:
        df = pl.read_csv(path, **kw)
    except Exception:  # noqa: BLE001 - later values that do not fit the schema become null
        df = pl.read_csv(path, ignore_errors=True, **kw)
        warnings.append("some values did not match the type inferred from the first rows; read as null")
    if n is not None and df.height == n:
        rows = pl.scan_csv(path, infer_schema=False, **common).select(pl.len()).collect().item()
    else:
        rows = df.height
    if df.columns and df.columns[0].startswith("﻿"):
        df = df.rename({df.columns[0]: df.columns[0].lstrip("﻿")})
    return _profile_frame(df, rel, None, fmt, rows, opts, warnings)


def _read_excel(path: Path, rel: str, opts: ReadOptions) -> list[TableProfile]:
    reader = fastexcel.read_excel(path)
    out = []
    skipped = []
    for name in reader.sheet_names:
        sheet = reader.load_sheet(
            name, n_rows=opts.sample_rows, schema_sample_rows=opts.schema_rows, whitespace_as_null=True
        )
        df = sheet.to_polars()
        if df.width == 0:
            skipped.append(name)
            continue
        out.append(_profile_frame(df, rel, name, "xlsx", sheet.total_height, opts, []))
    if not out:
        raise ValueError("no sheet has columns")
    if skipped:
        out[0].warnings.append(f"skipped sheets without columns: {', '.join(skipped)}")
    return out


# --- nested documents ------------------------------------------------------


class _Collector:
    """Accumulates field types over all records and values over sampled ones."""

    def __init__(self) -> None:
        self.types: dict[str, set[str]] = {}
        self.values: dict[str, list[Any]] = {}
        self.all_date: dict[str, bool] = {}
        self.all_datetime: dict[str, bool] = {}
        self.sampling = True

    def mark(self, path: str, type_name: str) -> None:
        self.types.setdefault(path, set()).add(type_name)
        if self.sampling:
            self.values.setdefault(path, [])

    def add(self, path: str, value: Any) -> None:
        t = python_type_name(value)
        if t == "str" and not value.strip():
            t = "null"  # blank strings count as null (and as empty in the stats)
        self.mark(path, t)
        if t == "str":
            self.all_date[path] = self.all_date.get(path, True) and bool(_ISO_DATE.match(value))
            self.all_datetime[path] = self.all_datetime.get(path, True) and bool(
                _ISO_DATETIME.match(value)
            )
        if self.sampling:
            self.values[path].append(value)

    def walk(self, prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            if not value:
                self.mark(prefix or "value", "object")
            for k, v in value.items():
                self.walk(f"{prefix}.{k}" if prefix else str(k), v)
        elif isinstance(value, list):
            path = f"{prefix}[]"
            # Containers of records are marked "array"; their children carry the values.
            if not value or any(isinstance(v, (dict, list)) for v in value):
                self.mark(path, "array")
            for v in value:
                if isinstance(v, (dict, list)):
                    self.walk(path, v)
                else:
                    self.add(path, v)
        else:
            self.add(prefix or "value", value)

    def field_types(self) -> dict[str, set[str]]:
        out = {}
        for path, types in self.types.items():
            if "str" in types and self.all_date.get(path):
                types = (types - {"str"}) | {"date"}
            elif "str" in types and self.all_datetime.get(path):
                types = (types - {"str"}) | {"datetime"}
            out[path] = set(types)
        return out


def flatten_records(doc: Any) -> tuple[list[Any], int]:
    """Split a parsed document into records: a root list is many, anything else one."""
    records = doc if isinstance(doc, list) else [doc]
    return records, len(records)


def stats_from_values(values: list[Any]) -> FieldStats:
    """Compute FieldStats from plain Python values."""
    st = FieldStats()
    for v in values:
        if v is None:
            st.nulls += 1
            continue
        if isinstance(v, str) and not v.strip():
            st.nulls += 1
            st.empty += 1
            continue
        st.count += 1
        t = python_type_name(v)
        if t in ("object", "array"):
            st.distinct = None
            continue
        if t != "bool":
            iv = iso_temporal(v)
            st.min, st.max = safe_min(st.min, iv), safe_max(st.max, iv)
        if t in ("int", "float"):
            st.sum += v
        if t == "str":
            st.min_len = safe_min(st.min_len, len(v))
            st.max_len = safe_max(st.max_len, len(v))
        if t in _TOP_TYPES:
            st.top[v] += 1
        if st.distinct is not None:
            st.distinct.add(v)
            if len(st.distinct) > DISTINCT_CAP:
                st.distinct = None
    if len(st.top) > TOP_CAP:
        st.top = Counter(dict(st.top.most_common(TOP_CAP)))
    return st


def _profile_doc(doc: Any, rel: str, fmt: str, opts: ReadOptions) -> TableProfile:
    records, rows = flatten_records(doc)
    col = _Collector()
    for i, rec in enumerate(records):
        col.sampling = opts.stats and (opts.sample_rows is None or i < opts.sample_rows)
        col.walk("", rec)
    stats = {p: stats_from_values(col.values.get(p, [])) for p in col.types} if opts.stats else {}
    return TableProfile(rel, None, fmt, rows, col.field_types(), stats, [])
