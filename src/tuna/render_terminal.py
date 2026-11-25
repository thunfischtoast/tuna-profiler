"""Render a Report to the terminal with rich."""

from __future__ import annotations

from rich import box
from rich.console import Console
from rich.console import Group as RichGroup
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

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

ERROR_CAP = 20
UNMATCHED_CAP = 10


def _paths(label: str, patterns: list[NamePattern], unmatched: list[str], sheets: list[str]) -> Tree:
    tree = Tree(f"[bold]{label}[/]", guide_style="dim")
    for p in patterns[:PATTERN_CAP]:
        ranges = escape("  ".join(f"{k}: {v}" for k, v in p.ranges.items()))
        tree.add(f"[green]{escape(p.pattern)}[/]  [dim]{plural(p.files, 'file')}[/]  {ranges}")
    if len(patterns) > PATTERN_CAP:
        tree.add(f"[dim]… {len(patterns) - PATTERN_CAP} more patterns[/]")
    if unmatched:
        names = escape(", ".join(unmatched[:UNMATCHED_CAP]))
        more = len(unmatched) - UNMATCHED_CAP
        tree.add(names + (f" [dim]… {more} more[/]" if more > 0 else ""))
    if sheets:
        tree.add("[dim]sheets:[/] " + escape(", ".join(sheets)))
    return tree


def _fields(g: Group) -> Table:
    t = Table(box=box.SIMPLE_HEAD, pad_edge=False, show_edge=False)
    t.add_column("field", no_wrap=True)
    t.add_column("type", no_wrap=True)
    for col in ("present", "null%", "distinct"):
        t.add_column(col, justify="right", no_wrap=True)
    t.add_column("min", overflow="fold")
    t.add_column("max / top", overflow="fold")
    for f in g.fields:
        present = "all" if f.present_in == g.tables else f"{f.present_in}/{g.tables}"
        nulls = "" if f.nulls_pct is None else f"{f.nulls_pct:g}"
        last = fmt_value(f.max) if f.max is not None else fmt_top(f.top)
        cells = (f.name, fmt_type(f), present, nulls, fmt_value(f.distinct), fmt_value(f.min), last)
        t.add_row(*(Text(c) for c in cells))
    return t


def render_terminal(report: Report, console: Console | None = None) -> None:
    """Print the report summary."""
    console = console or Console()
    ignored = sum(report.ignored.values())
    console.print(
        f"[bold]tuna[/] {escape(report.root)}  "
        f"{report.files_found} files found · {report.files_profiled} profiled · "
        f"{ignored} ignored · {len(report.errors)} errors · {report.duration_s} s"
    )
    for g in report.groups:
        title = (f"[bold]{g.id}[/]  {plural(g.files, 'file')} · {', '.join(g.formats)} · "
                 f"{fmt_rows(g.rows_total)} · {plural(len(g.fields), 'field')}")
        if g.tables != g.files:
            title += f" · {plural(g.tables, 'table')}"
        console.print(Panel(RichGroup(_paths("paths", g.paths, g.unmatched, g.sheets), _fields(g)), title=title, title_align="left"))
    for fs in report.file_sets:
        title = f"[bold]{escape(fs.ext)}[/]  {plural(fs.files, 'file')} · not read"
        console.print(Panel(_paths("paths", fs.paths, fs.unmatched, []), title=title, title_align="left"))
    if len(report.folders) > 1:
        tree = Tree("[bold]folders[/]", guide_style="dim")
        for f in report.folders[:PATTERN_CAP]:
            tree.add(
                f"[cyan]{escape(f.pattern)}[/]  [dim]{plural(f.folders, 'folder')}[/]  "
                + escape(fmt_contents(f.contents))
            )
        if len(report.folders) > PATTERN_CAP:
            tree.add(f"[dim]… {len(report.folders) - PATTERN_CAP} more[/]")
        console.print(tree)
    if report.errors:
        console.print(Text(f"errors ({len(report.errors)})", style="bold red"))
        for e in report.errors[:ERROR_CAP]:
            console.print(f"  {e.path}: {e.message}", markup=False)
        if len(report.errors) > ERROR_CAP:
            console.print(f"  … {len(report.errors) - ERROR_CAP} more")
    if report.warnings:
        console.print(Text(f"warnings ({len(report.warnings)})", style="bold yellow"))
        for w in report.warnings[:ERROR_CAP]:
            console.print(f"  {w.path}: {w.message}", markup=False)
        if len(report.warnings) > ERROR_CAP:
            console.print(f"  … {len(report.warnings) - ERROR_CAP} more")
