"""Find supported data files below a root path."""

from __future__ import annotations

import fnmatch
import os
from collections import Counter
from pathlib import Path

FORMATS: dict[str, str] = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
}


def _matches(rel: str, globs: list[str]) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(name, g) for g in globs)


def discover(
    root: Path,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    max_depth: int | None = None,
    hidden: bool = False,
) -> tuple[list[Path], Counter]:
    """Return supported files (sorted) and a counter of ignored extensions.

    ``include``/``exclude`` globs match the path relative to ``root`` (posix) or the
    basename; ``exclude`` also prunes directories. ``max_depth=0`` keeps only files
    directly in ``root``. A file ``root`` is returned as-is if its extension is supported.
    """
    include = include or []
    exclude = exclude or []
    ignored: Counter = Counter()
    if root.is_file():
        if root.suffix.lower() not in FORMATS:
            raise ValueError(f"unsupported file type: {root.suffix or root.name}")
        return [root], ignored

    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        rel_dir = here.relative_to(root).as_posix()
        depth = 0 if rel_dir == "." else rel_dir.count("/") + 1
        prefix = "" if rel_dir == "." else rel_dir + "/"
        keep = []
        for d in sorted(dirnames):
            if not hidden and d.startswith("."):
                continue
            if max_depth is not None and depth >= max_depth:
                continue
            if _matches(prefix + d, exclude):
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in filenames:
            if not hidden and f.startswith("."):
                continue
            if fnmatch.fnmatch(f.lower(), "~$*.xls*"):  # Excel owner/lock files
                continue
            rel = prefix + f
            if _matches(rel, exclude) or (include and not _matches(rel, include)):
                continue
            ext = Path(f).suffix.lower()
            if ext in FORMATS:
                found.append(here / f)
            else:
                ignored[ext or "(none)"] += 1
    found.sort(key=lambda p: p.relative_to(root).as_posix())
    return found, ignored
