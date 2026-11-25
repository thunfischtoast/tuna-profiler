"""Command-line entry point: discover, read, group, render."""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from tuna import __version__
from tuna.discover import FORMATS, discover
from tuna.model import FileError, TableProfile
from tuna.readers import ReadOptions, read_file
from tuna.render_json import render_json
from tuna.render_markdown import render_markdown
from tuna.render_terminal import render_terminal
from tuna.report import build_report

_RENDERERS = {".md": render_markdown, ".json": render_json}
_PARALLEL_MIN_FILES = 8

Job = tuple[str, str, str, ReadOptions]
Result = tuple[list[TableProfile], FileError | None]


def profile_one(job: Job) -> Result:
    """Profile one file; top-level so ProcessPoolExecutor can pickle it on Windows."""
    path, rel, fmt, opts = job
    try:
        return read_file(Path(path), rel, fmt, opts), None
    except Exception as e:  # noqa: BLE001 - one bad file must not stop the scan
        first_line = next(iter(str(e).strip().splitlines()), "")
        return [], FileError(rel, f"{type(e).__name__}: {first_line}")


def _run(jobs: list[Job], workers: int) -> Iterator[Result]:
    if workers > 1 and len(jobs) >= _PARALLEL_MIN_FILES:
        with ProcessPoolExecutor(workers) as ex:
            for fut in as_completed([ex.submit(profile_one, j) for j in jobs]):
                yield fut.result()
    else:
        yield from map(profile_one, jobs)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tuna", description="Profile the structure of data files in a folder.")
    p.add_argument("path", metavar="PATH", type=Path)
    p.add_argument("-o", "--output", action="append", default=[], metavar="FILE", type=Path,
                   help=".md or .json by extension (repeatable)")
    p.add_argument("--full", action="store_true", help="read all rows for stats")
    p.add_argument("--sample-rows", type=int, default=1000, metavar="N", help="rows per file for stats (default 1000)")
    p.add_argument("--no-stats", action="store_true", help="schema and row counts only")
    p.add_argument("--include", action="append", default=[], metavar="GLOB", help="only matching files (repeatable)")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="skip matching files and dirs (repeatable)")
    p.add_argument("--max-depth", type=int, metavar="N", help="0 = only files directly in PATH")
    p.add_argument("--hidden", action="store_true", help="include dot-files and dot-dirs")
    p.add_argument("--min-pattern-files", type=int, default=3, metavar="N",
                   help="files needed for a name pattern (default 3)")
    p.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1, metavar="N",
                   help="worker processes (default: CPU count)")
    p.add_argument("-q", "--quiet", action="store_true", help="no terminal output")
    p.add_argument("--version", action="version", version=f"tuna {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    for out in args.output:
        if out.suffix.lower() not in _RENDERERS:
            parser.error(f"unsupported output format: {out} (use .md or .json)")
    root: Path = args.path
    if not root.exists():
        parser.error(f"path not found: {root}")
    try:
        files, ignored = discover(root, args.include, args.exclude, args.max_depth, args.hidden)
    except ValueError as e:
        parser.error(str(e))

    start = time.perf_counter()
    opts = ReadOptions(sample_rows=None if args.full else args.sample_rows, stats=not args.no_stats)
    base = root.parent if root.is_file() else root
    jobs = [(str(f), f.relative_to(base).as_posix(), FORMATS[f.suffix.lower()], opts) for f in files]

    tables: list[TableProfile] = []
    errors: list[FileError] = []
    show_progress = not args.quiet and sys.stderr.isatty()
    with Progress(console=Console(stderr=True), transient=True, disable=not show_progress) as progress:
        task = progress.add_task("reading", total=len(jobs))
        for result, error in _run(jobs, args.jobs):
            tables.extend(result)
            if error:
                errors.append(error)
            progress.advance(task)
    tables.sort(key=lambda t: (t.path, t.sheet or ""))
    errors.sort(key=lambda e: e.path)

    options = {
        "sample_rows": opts.sample_rows,
        "stats": opts.stats,
        "include": args.include,
        "exclude": args.exclude,
        "max_depth": args.max_depth,
        "hidden": args.hidden,
        "min_pattern_files": args.min_pattern_files,
    }
    report = build_report(str(root), tables, errors, ignored, options, time.perf_counter() - start)
    for out in args.output:
        out.write_text(_RENDERERS[out.suffix.lower()](report), encoding="utf-8")
    if not args.quiet:
        render_terminal(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
