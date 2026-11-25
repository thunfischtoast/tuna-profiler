"""Render a Report as Markdown."""

from __future__ import annotations

from tuna.report import Group, Report, fmt_rows, fmt_top, fmt_value, plural

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


def _group(g: Group) -> list[str]:
    title = ", ".join(f.name for f in g.fields[:3]) or "(no fields)"
    out = [
        f"### {g.id} — {title}",
        "",
        (
            f"{plural(g.tables, 'table')} in {plural(g.files, 'file')} · {', '.join(g.formats)} · "
            f"{fmt_rows(g.rows_total)} · {plural(len(g.fields), 'field')}"
        ),
        "",
    ]
    rows = []
    for loc in g.locations:
        for p in loc.patterns:
            ranges = "; ".join(f"{k}: {v}" for k, v in p.ranges.items())
            rows.append([loc.folder, p.files, f"`{p.pattern}`", ranges])
        if loc.unmatched:
            rows.append([loc.folder, len(loc.unmatched), _unmatched(loc.unmatched), ""])
        if loc.sheets:
            rows.append([loc.folder, "", "sheets: " + ", ".join(loc.sheets), ""])
    out += _table(["folder", "files", "pattern", "ranges"], rows)
    out.append("")
    frows = []
    for f in g.fields:
        present = "all" if f.present_in == g.tables else f"{f.present_in}/{g.tables}"
        nulls = "" if f.nulls_pct is None else f"{f.nulls_pct:g}%"
        frows.append([
            f"`{f.name}`", f.type, present, nulls, fmt_value(f.distinct),
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
            ["structures", len(report.groups)],
        ]),
        "",
        "## Structures",
        "",
    ]
    for g in report.groups:
        out += _group(g)
    out += ["## Folders", ""]
    out += _table(
        ["folder", "files", "structures"],
        [[f.folder, f.files, ", ".join(f"{gid} ({n})" for gid, n in f.groups)] for f in report.folders],
    )
    out.append("")
    if report.errors:
        out += ["## Errors", ""]
        out += _table(["file", "error"], [[e.path, e.message] for e in report.errors])
        out.append("")
    return "\n".join(out)
