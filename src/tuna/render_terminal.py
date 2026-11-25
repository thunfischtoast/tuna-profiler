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

from tuna.report import Group, Report, fmt_rows, fmt_top, fmt_value, plural

ERROR_CAP = 20
UNMATCHED_CAP = 5


def _locations(g: Group) -> Tree:
    tree = Tree("[bold]locations[/]", guide_style="dim")
    for loc in g.locations:
        node = tree.add(f"[cyan]{escape(loc.folder)}[/]  [dim]{plural(loc.files, 'file')}[/]")
        for p in loc.patterns:
            ranges = escape("  ".join(f"{k}: {v}" for k, v in p.ranges.items()))
            node.add(f"[green]{escape(p.pattern)}[/]  [dim]{plural(p.files, 'file')}[/]  {ranges}")
        if loc.unmatched:
            names = escape(", ".join(loc.unmatched[:UNMATCHED_CAP]))
            more = len(loc.unmatched) - UNMATCHED_CAP
            node.add(names + (f" [dim]… {more} more[/]" if more > 0 else ""))
        if loc.sheets:
            node.add("[dim]sheets:[/] " + escape(", ".join(loc.sheets)))
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
        cells = (f.name, f.type, present, nulls, fmt_value(f.distinct), fmt_value(f.min), last)
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
        console.print(Panel(RichGroup(_locations(g), _fields(g)), title=title, title_align="left"))
    if len(report.folders) > 1:
        tree = Tree("[bold]folders[/]", guide_style="dim")
        for f in report.folders:
            groups = ", ".join(f"{gid} ({n})" for gid, n in f.groups)
            tree.add(f"[cyan]{escape(f.folder)}[/]  [dim]{plural(f.files, 'file')}[/]  {groups}")
        console.print(tree)
    if report.errors:
        console.print(Text(f"errors ({len(report.errors)})", style="bold red"))
        for e in report.errors[:ERROR_CAP]:
            console.print(f"  {e.path}: {e.message}", markup=False)
        if len(report.errors) > ERROR_CAP:
            console.print(f"  … {len(report.errors) - ERROR_CAP} more")
