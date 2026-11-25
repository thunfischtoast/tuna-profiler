"""Picklable data model shared by readers, grouping and report building."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

DISTINCT_CAP = 10_000
TOP_CAP = 1000


def safe_min(a: Any, b: Any) -> Any:
    """Smaller of two values; None and incomparable values never replace a value."""
    if a is None:
        return b
    if b is None:
        return a
    try:
        return min(a, b)
    except TypeError:
        return a


def safe_max(a: Any, b: Any) -> Any:
    """Larger of two values; None and incomparable values never replace a value."""
    if a is None:
        return b
    if b is None:
        return a
    try:
        return max(a, b)
    except TypeError:
        return a


@dataclass
class FieldStats:
    """Mergeable partial aggregate of one field's values.

    ``empty`` counts blank strings, which are also counted in ``nulls``. Its meaning
    depends on the format: CSV counts whitespace-only cells (empty cells are plain
    nulls), Excel always counts 0 (fastexcel turns blanks into nulls), and JSON/YAML
    count empty and whitespace-only strings.
    """

    count: int = 0
    nulls: int = 0
    empty: int = 0
    min: Any = None
    max: Any = None
    sum: float = 0.0
    min_len: int | None = None
    max_len: int | None = None
    distinct: set | None = field(default_factory=set)
    top: Counter = field(default_factory=Counter)

    def merge(self, other: FieldStats) -> None:
        """Fold ``other`` into this aggregate in place."""
        self.count += other.count
        self.nulls += other.nulls
        self.empty += other.empty
        self.sum += other.sum
        self.min = safe_min(self.min, other.min)
        self.max = safe_max(self.max, other.max)
        self.min_len = safe_min(self.min_len, other.min_len)
        self.max_len = safe_max(self.max_len, other.max_len)
        if self.distinct is None or other.distinct is None:
            self.distinct = None
        else:
            self.distinct |= other.distinct
            if len(self.distinct) > DISTINCT_CAP:
                self.distinct = None
        self.top.update(other.top)
        if len(self.top) > TOP_CAP:
            self.top = Counter(dict(self.top.most_common(TOP_CAP)))


@dataclass
class TableProfile:
    """Schema and stats of one CSV file, one Excel sheet or one JSON/YAML file."""

    path: str
    sheet: str | None
    format: str
    rows: int
    fields: dict[str, set[str]]
    stats: dict[str, FieldStats]
    warnings: list[str] = field(default_factory=list)


@dataclass
class FileError:
    """A message about one file: a read error, or a warning from a table that was read."""

    path: str
    message: str
