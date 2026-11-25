"""Build the report model from table profiles, plus shared value formatting."""

from __future__ import annotations

import datetime as dt
import posixpath
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from tuna.grouping import group_tables
from tuna.model import FieldStats, FileError, TableProfile
from tuna.patterns import NamePattern, infer_patterns
from tuna.types import display_type

_MINMAX_TYPES = {"int", "float", "date", "datetime", "time"}


@dataclass
class FieldSummary:
    """One field of a group, with stats merged over all members."""

    name: str
    type: str
    present_in: int
    nulls_pct: float | None = None
    distinct: int | str | None = None
    min: Any = None
    max: Any = None
    mean: float | None = None
    min_len: int | None = None
    max_len: int | None = None
    top: list[list[Any]] | None = None


@dataclass
class Location:
    """Where a group occurs: one folder, its name patterns and unpatterned files."""

    folder: str
    files: int
    patterns: list[NamePattern]
    unmatched: list[str]
    sheets: list[str]


@dataclass
class Member:
    """One table of a group (JSON output only)."""

    path: str
    sheet: str | None
    rows: int


@dataclass
class Group:
    """A set of tables with the same tolerant structure."""

    id: str
    tables: int
    files: int
    formats: list[str]
    rows_total: int
    fields: list[FieldSummary]
    locations: list[Location]
    members: list[Member]


@dataclass
class FolderSummary:
    """Which groups occur in a folder: (group id, table count) pairs."""

    folder: str
    files: int
    groups: list[tuple[str, int]]


@dataclass
class Report:
    """Everything a renderer needs."""

    root: str
    scanned_at: str
    duration_s: float
    files_found: int
    files_profiled: int
    ignored: dict[str, int]
    errors: list[FileError]
    groups: list[Group]
    folders: list[FolderSummary]
    options: dict[str, Any]


def _folder(path: str) -> str:
    return posixpath.dirname(path) or "."


def _field_order(members: list[TableProfile]) -> list[str]:
    largest = max(members, key=lambda t: (t.rows, len(t.fields)))
    order = dict.fromkeys(largest.fields)
    for t in members:
        order.update(dict.fromkeys(f for f in t.fields if f not in order))
    return list(order)


def _summarize_field(name: str, members: list[TableProfile]) -> FieldSummary:
    having = [t for t in members if name in t.fields]
    types: set[str] = set().union(*(t.fields[name] for t in having))
    shown = display_type(types)
    fs = FieldSummary(name, shown, len(having))
    parts = [t.stats[name] for t in having if name in t.stats]
    if not parts:
        return fs
    st = FieldStats()
    for p in parts:
        st.merge(p)
    seen = st.count + st.nulls
    fs.nulls_pct = round(100 * st.nulls / seen, 1) if seen else None
    fs.distinct = len(st.distinct) if st.distinct is not None else ">=10000"
    if set(shown.split("|")) <= _MINMAX_TYPES:
        fs.min, fs.max = st.min, st.max
    if shown in ("int", "float") and st.count:
        fs.mean = st.sum / st.count
    fs.min_len, fs.max_len = st.min_len, st.max_len
    if st.top:
        fs.top = [[v, c] for v, c in st.top.most_common(5)]
    return fs


def _locations(members: list[TableProfile], min_files: int) -> list[Location]:
    by_folder: dict[str, list[TableProfile]] = defaultdict(list)
    for t in members:
        by_folder[_folder(t.path)].append(t)
    out = []
    for folder in sorted(by_folder):
        tables = by_folder[folder]
        sheets_per_file: dict[str, set[str]] = defaultdict(set)
        for t in tables:
            sheets_per_file[posixpath.basename(t.path)].add(t.sheet or "")
        names = sorted(sheets_per_file)
        patterns, unmatched = infer_patterns(names, min_files)
        sheet_sets = {frozenset(s) for s in sheets_per_file.values()}
        sheets: list[str] = []
        if len(sheet_sets) == 1 and "" not in next(iter(sheet_sets)):
            sheets = sorted(next(iter(sheet_sets)))
        out.append(Location(folder, len(names), patterns, unmatched, sheets))
    return out


def build_report(
    root: str,
    tables: list[TableProfile],
    errors: list[FileError],
    ignored: Counter,
    opts: dict[str, Any],
    duration: float,
) -> Report:
    """Group the tables and summarize groups, locations and folders."""
    min_files = opts.get("min_pattern_files", 3)
    groups = []
    for i, members in enumerate(group_tables(tables), 1):
        fields = [_summarize_field(n, members) for n in _field_order(members)]
        groups.append(
            Group(
                id=f"S{i}",
                tables=len(members),
                files=len({t.path for t in members}),
                formats=sorted({t.format for t in members}),
                rows_total=sum(t.rows for t in members),
                fields=fields,
                locations=_locations(members, min_files),
                members=[Member(t.path, t.sheet, t.rows) for t in members],
            )
        )

    folder_files: dict[str, set[str]] = defaultdict(set)
    folder_groups: dict[str, Counter] = defaultdict(Counter)
    for g in groups:
        for m in g.members:
            folder_files[_folder(m.path)].add(m.path)
            folder_groups[_folder(m.path)][g.id] += 1
    order = {g.id: i for i, g in enumerate(groups)}
    folders = [
        FolderSummary(f, len(folder_files[f]), sorted(folder_groups[f].items(), key=lambda x: order[x[0]]))
        for f in sorted(folder_files)
    ]
    profiled = {t.path for t in tables}
    return Report(
        root=root,
        scanned_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        duration_s=round(duration, 2),
        files_found=len(profiled) + len(errors),
        files_profiled=len(profiled),
        ignored=dict(sorted(ignored.items())),
        errors=errors,
        groups=groups,
        folders=folders,
        options=opts,
    )


def fmt_value(v: Any, width: int = 30) -> str:
    """Format a stat value for display, truncated to ``width`` characters."""
    if v is None:
        return ""
    if isinstance(v, float):
        s = f"{v:.6g}"
    elif isinstance(v, (dt.date, dt.time)):
        s = v.isoformat()
    else:
        s = str(v)
    return s if len(s) <= width else s[: width - 1] + "…"


def fmt_count(n: int) -> str:
    """Format a count compactly: 950, 12.3k, 1.2M."""
    for div, unit in ((1_000_000_000, "G"), (1_000_000, "M"), (1_000, "k")):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return str(n)


def fmt_rows(n: int) -> str:
    """``1 row``, ``2.0k rows``."""
    return "1 row" if n == 1 else f"{fmt_count(n)} rows"


def plural(n: int, word: str) -> str:
    """``1 file``, ``2 files``."""
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def fmt_top(top: list[list[Any]] | None, n: int = 3) -> str:
    """Format the most common values as ``a (5), b (3)``; empty if no value repeats."""
    if not top or (top[0][1] == 1 and len(top) > 1):
        return ""
    return ", ".join(f"{fmt_value(v, 15)} ({c})" for v, c in top[:n])
