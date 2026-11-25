"""Build the report model from table profiles, plus shared value formatting."""

from __future__ import annotations

import datetime as dt
import posixpath
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from tuna.grouping import group_tables
from tuna.model import FieldStats, FileError, TableProfile
from tuna.patterns import NamePattern, infer_pattern_members, infer_patterns, split_ext
from tuna.types import display_type, families

_MINMAX_TYPES = {"int", "float", "date", "datetime", "time", "duration"}


@dataclass
class FieldSummary:
    """One field of a group, with stats merged over all members."""

    name: str
    type: str
    present_in: int
    nulls_pct: float | None = None
    empty: int | None = None
    distinct: int | str | None = None
    min: Any = None
    max: Any = None
    mean: float | None = None
    min_len: int | None = None
    max_len: int | None = None
    top: list[list[Any]] | None = None
    type_variants: dict[str, int] | None = None  # display type -> tables, only on conflicts


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
    paths: list[NamePattern]
    unmatched: list[str]
    sheets: list[str]
    members: list[Member]


@dataclass
class FileSet:
    """Unsupported files of one extension, listed but not read."""

    ext: str
    files: int
    paths: list[NamePattern]
    unmatched: list[str]


@dataclass
class FolderPattern:
    """Folders with the same contents: (structure id or file-set ext, file count) pairs."""

    pattern: str
    folders: int
    contents: list[tuple[str, int]]


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
    warnings: list[FileError]
    groups: list[Group]
    file_sets: list[FileSet]
    folders: list[FolderPattern]
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
    variants = Counter(display_type(t.fields[name]) for t in having if families(t.fields[name]))
    if len({families(set(v.split("|"))) for v in variants}) > 1:
        fs.type_variants = dict(sorted(variants.items(), key=lambda v: (-v[1], v[0])))
    parts = [t.stats[name] for t in having if name in t.stats]
    if not parts:
        return fs
    st = FieldStats()
    for p in parts:
        st.merge(p)
    seen = st.count + st.nulls
    fs.nulls_pct = round(100 * st.nulls / seen, 1) if seen else None
    fs.empty = st.empty
    fs.distinct = len(st.distinct) if st.distinct is not None else ">=10000"
    if set(shown.split("|")) <= _MINMAX_TYPES:
        fs.min, fs.max = st.min, st.max
    if shown in ("int", "float") and st.count:
        fs.mean = st.sum / st.count
    fs.min_len, fs.max_len = st.min_len, st.max_len
    if st.top:
        fs.top = [[v, c] for v, c in st.top.most_common(5)]
    return fs


def _sheets(members: list[TableProfile]) -> list[str]:
    if any(t.sheet is None for t in members):
        return []
    per_file: dict[str, set[str]] = defaultdict(set)
    for t in members:
        if t.sheet is not None:
            per_file[t.path].add(t.sheet)
    sets = {frozenset(v) for v in per_file.values()}
    return sorted(next(iter(sets))) if len(sets) == 1 else []


def ext_of(path: str) -> str:
    """Lowercased extension of a path's last segment, ``(none)`` if it has none."""
    return split_ext(path)[1].lower() or "(none)"


def _file_sets(ignored: dict[str, str], min_files: int) -> list[FileSet]:
    by_ext: dict[str, list[str]] = defaultdict(list)
    for path, ext in ignored.items():
        by_ext[ext].append(path)
    sets = []
    for ext, paths in by_ext.items():
        patterns, unmatched = infer_patterns(sorted(paths), min_files)
        sets.append(FileSet(ext, len(paths), patterns, unmatched))
    sets.sort(key=lambda f: (-f.files, f.ext))
    return sets


def _folder_patterns(
    folder_contents: dict[str, Counter], order: dict[str, int], min_files: int
) -> list[FolderPattern]:
    """Collapse folders with the same content signature into folder-path patterns."""
    by_sig: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for folder, contents in folder_contents.items():
        by_sig[tuple(sorted(contents, key=order.__getitem__))].append(folder)

    def summed(folders: list[str]) -> list[tuple[str, int]]:
        total: Counter = Counter()
        for f in folders:
            total.update(folder_contents[f])
        return sorted(total.items(), key=lambda x: order[x[0]])

    out = []
    for folders in by_sig.values():
        covered, unmatched = infer_pattern_members(sorted(folders), min_files)
        out += [FolderPattern(p.pattern, p.files, summed(members)) for p, members in covered]
        out += [FolderPattern(f, 1, summed([f])) for f in unmatched]
    out.sort(key=lambda f: (-f.folders, f.pattern))
    return out


def build_report(
    root: str,
    tables: list[TableProfile],
    errors: list[FileError],
    ignored: list[str],
    opts: dict[str, Any],
    duration: float,
) -> Report:
    """Group the tables and summarize groups, file sets and folders.

    ``ignored`` holds the relative paths of unsupported files.
    """
    min_files = opts.get("min_pattern_files", 3)
    groups = []
    folder_contents: dict[str, Counter] = defaultdict(Counter)
    for i, members in enumerate(group_tables(tables, opts.get("strict_types", False)), 1):
        gid = f"S{i}"
        files = sorted({t.path for t in members})
        for f in files:
            folder_contents[_folder(f)][gid] += 1
        paths, unmatched = infer_patterns(files, min_files)
        groups.append(
            Group(
                id=gid,
                tables=len(members),
                files=len(files),
                formats=sorted({t.format for t in members}),
                rows_total=sum(t.rows for t in members),
                fields=[_summarize_field(n, members) for n in _field_order(members)],
                paths=paths,
                unmatched=unmatched,
                sheets=_sheets(members),
                members=[Member(t.path, t.sheet, t.rows) for t in members],
            )
        )
    exts = {path: ext_of(path) for path in ignored}
    file_sets = _file_sets(exts, min_files)
    for path, ext in exts.items():
        folder_contents[_folder(path)][ext] += 1
    order = {g.id: i for i, g in enumerate(groups)}
    order.update({fs.ext: len(groups) + i for i, fs in enumerate(file_sets)})

    profiled = {t.path for t in tables}
    return Report(
        root=root,
        scanned_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        duration_s=round(duration, 2),
        files_found=len(profiled) + len(errors),
        files_profiled=len(profiled),
        ignored=dict(sorted(Counter(exts.values()).items())),
        errors=errors,
        warnings=[
            FileError(f"{t.path} [{t.sheet}]" if t.sheet else t.path, w) for t in tables for w in t.warnings
        ],
        groups=groups,
        file_sets=file_sets,
        folders=_folder_patterns(folder_contents, order, min_files),
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


PATTERN_CAP = 20


def fmt_type(f: FieldSummary) -> str:
    """Field type plus the minority type variants, as ``int|str (str in 3/511)``."""
    if not f.type_variants:
        return f.type
    typed = sum(f.type_variants.values())  # tables having the field with a non-null type
    minority = list(f.type_variants.items())[1:]
    return f.type + " " + ", ".join(f"({t} in {n}/{typed})" for t, n in minority)


def fmt_contents(contents: list[tuple[str, int]]) -> str:
    """``S1 (40), .dcm (2000)``."""
    return ", ".join(f"{k} ({n})" for k, n in contents)
