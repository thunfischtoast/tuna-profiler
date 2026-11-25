"""Render a Report as Markdown."""

from __future__ import annotations

from tuna.patterns import NamePattern
from tuna.report import (
    PATTERN_CAP,
    Group,
    Report,
    fmt_contents,
    fmt_rows,
    fmt_top,
    fmt_type,
    fmt_value,
    plural,
)

UNMATCHED_CAP = 10


def _cell(v: object) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


def _row(*cells: object) -> str:
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


def _table(header: list[str], rows: list[list[object]]) -> list[str]:
    return [_row(*header), _row(*(["---"] * len(header))), *(_row(*r) for r in rows)]


def _unmatched(names: list[str]) -> str:
    shown = ", ".join(names[:UNMATCHED_CAP])
    if len(names) > UNMATCHED_CAP:
        shown += f", … and {len(names) - UNMATCHED_CAP} more"
    return shown


def _paths(patterns: list[NamePattern], unmatched: list[str]) -> list[str]:
    rows: list[list[object]] = []
    for p in patterns[:PATTERN_CAP]:
        rows.append([f"`{p.pattern}`", p.files, "; ".join(f"{k}: {v}" for k, v in p.ranges.items())])
    if len(patterns) > PATTERN_CAP:
        rows.append([f"… {len(patterns) - PATTERN_CAP} more", "", ""])
    out = _table(["path", "files", "ranges"], rows) + [""] if rows else []
    if unmatched:
        out += [f"Other paths ({len(unmatched)}): " + _unmatched(unmatched), ""]
    return out


def _group(g: Group) -> list[str]:
    title = ", ".join(f.name for f in g.fields[:3]) or "(no fields)"
    out = [
        f"### {g.id}: {title}",
        "",
        (
            f"{plural(g.tables, 'table')} in {plural(g.files, 'file')} · {', '.join(g.formats)} · "
            f"{fmt_rows(g.rows_total)} · {plural(len(g.fields), 'field')}"
        ),
        "",
    ]
    out += _paths(g.paths, g.unmatched)
    if g.sheets:
        out += ["Sheets: " + ", ".join(g.sheets), ""]
    frows = []
    for f in g.fields:
        present = "all" if f.present_in == g.tables else f"{f.present_in}/{g.tables}"
        nulls = "" if f.nulls_pct is None else f"{f.nulls_pct:g}%"
        frows.append([
            f"`{f.name}`", fmt_type(f), present, nulls, fmt_value(f.distinct),
            fmt_value(f.min), fmt_value(f.max), fmt_value(f.mean), fmt_top(f.top),
        ])
    out += _table(["field", "type", "present", "nulls", "distinct", "min", "max", "mean", "top"], frows)
    out.append("")
    return out


def render_markdown(report: Report) -> str:
    """Return the report as a Markdown document."""
    ignored = ", ".join(f"{k} ({v})" for k, v in report.ignored.items()) or "none"
    out = [
        "# tuna report",
        "",
        *_table(["", ""], [
            ["root", f"`{report.root}`"],
            ["scanned at", report.scanned_at],
            ["duration", f"{report.duration_s} s"],
            ["files found", report.files_found],
            ["files profiled", report.files_profiled],
            ["ignored", ignored],
            ["errors", len(report.errors)],
            ["warnings", len(report.warnings)],
            ["structures", len(report.groups)],
        ]),
        "",
        "## Structures",
        "",
    ]
    for g in report.groups:
        out += _group(g)
    if report.file_sets:
        out += ["## File sets", "", "Files with other extensions, listed but not read.", ""]
        for fs in report.file_sets:
            out += [f"### {fs.ext} ({plural(fs.files, 'file')})", ""]
            out += _paths(fs.paths, fs.unmatched)
    out += ["## Folders", ""]
    folder_rows: list[list[object]] = [
        [f"`{f.pattern}`", f.folders, fmt_contents(f.contents)] for f in report.folders[:PATTERN_CAP]
    ]
    if len(report.folders) > PATTERN_CAP:
        folder_rows.append([f"… {len(report.folders) - PATTERN_CAP} more", "", ""])
    out += _table(["folder", "folders", "contents"], folder_rows)
    out.append("")
    if report.errors:
        out += ["## Errors", ""]
        out += _table(["file", "error"], [[e.path, e.message] for e in report.errors])
        out.append("")
    if report.warnings:
        out += ["## Warnings", ""]
        out += _table(["file", "warning"], [[w.path, w.message] for w in report.warnings])
        out.append("")
    return "\n".join(out)
