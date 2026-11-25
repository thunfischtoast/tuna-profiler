"""Read data files into TableProfiles."""

from __future__ import annotations

import csv
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


@dataclass
class ReadOptions:
    """How much of each file to read: ``sample_rows=None`` means all rows."""

    sample_rows: int | None = 1000
    stats: bool = True


def read_file(path: Path, rel: str, fmt: str, opts: ReadOptions) -> list[TableProfile]:
    """Profile one file; raises on unreadable input."""
    if fmt in ("csv", "tsv"):
        return [_read_csv(path, rel, fmt, opts)]
    if fmt == "xlsx":
        return _read_excel(path, rel, opts)
    if fmt == "json":
        with open(path, encoding="utf-8", errors="replace") as f:
            doc = json.load(f)
        return [_profile_doc(doc, rel, fmt, opts)]
    if fmt == "yaml":
        with open(path, encoding="utf-8", errors="replace") as f:
            docs = list(yaml.safe_load_all(f))
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
    if type_name in ("int", "float", "date", "datetime", "time", "str"):
        st.min, st.max = s.min(), s.max()
    if type_name in ("int", "float"):
        st.sum = float(s.sum())
    if type_name == "str":
        lens = s.str.len_chars()
        st.min_len, st.max_len = int(lens.min()), int(lens.max())
    if type_name in _TOP_TYPES:
        vc = s.value_counts(sort=True).head(TOP_CAP)
        st.top = Counter(dict(zip(vc[s.name].to_list(), vc["count"].to_list())))
    if s.dtype.is_nested() or s.n_unique() > DISTINCT_CAP:
        st.distinct = None
    else:
        st.distinct = set(s.unique().to_list())
    return st


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
        s = df[name]
        t = "null" if s.null_count() == s.len() else polars_type_name(s.dtype)
        fields[name] = {t}
        if opts.stats:
            stats[name] = stats_from_series(s, t)
    return TableProfile(rel, sheet, fmt, rows, fields, stats, warnings)


def _sniff(path: Path, fmt: str) -> str:
    with open(path, "rb") as f:
        head = f.read(65536).decode("utf-8", errors="replace")
    try:
        return csv.Sniffer().sniff(head, delimiters=",;\t|").delimiter
    except csv.Error:
        return "\t" if fmt == "tsv" else ","


def _read_csv(path: Path, rel: str, fmt: str, opts: ReadOptions) -> TableProfile:
    sep = _sniff(path, fmt)
    n = opts.sample_rows
    common: dict[str, Any] = {"separator": sep, "encoding": "utf8-lossy", "truncate_ragged_lines": True}
    warnings: list[str] = []
    try:
        kw = dict(common, infer_schema_length=n or 10000, try_parse_dates=True)
        df = pl.read_csv(path, n_rows=n, **kw)
    except Exception as e:  # noqa: BLE001 - any inference failure falls back to text
        warnings.append(f"type inference failed, read as text: {str(e).splitlines()[0]}")
        kw = dict(common, infer_schema=False)
        df = pl.read_csv(path, n_rows=n, **kw)
    if df.columns and df.columns[0].startswith("﻿"):
        df = df.rename({df.columns[0]: df.columns[0].lstrip("﻿")})
    if n is None or df.height < n:
        rows = df.height
    else:
        rows = pl.scan_csv(path, **kw).select(pl.len()).collect().item()
    return _profile_frame(df, rel, None, fmt, rows, opts, warnings)


def _read_excel(path: Path, rel: str, opts: ReadOptions) -> list[TableProfile]:
    reader = fastexcel.read_excel(path)
    out = []
    skipped = []
    for name in reader.sheet_names:
        sheet = reader.load_sheet(name, n_rows=opts.sample_rows)
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
        st.count += 1
        t = python_type_name(v)
        if t in ("object", "array"):
            st.distinct = None
            continue
        if t != "bool":
            st.min, st.max = safe_min(st.min, v), safe_max(st.max, v)
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
