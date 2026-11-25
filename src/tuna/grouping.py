"""Group tables that share a tolerant structure."""

from __future__ import annotations

from collections import defaultdict

from tuna.model import TableProfile
from tuna.types import compatible, families

SIMILARITY = 0.8


def _key(t: TableProfile, strict_types: bool) -> frozenset:
    if strict_types:
        return frozenset((name, families(types)) for name, types in t.fields.items())
    return frozenset(t.fields)


def _effective(names: frozenset[str], other: frozenset[str]) -> frozenset[str]:
    """Drop from ``other`` the children of arrays that are empty in ``names``.

    An empty list only yields ``x[]`` without ``x[].*`` fields, so those children say
    nothing about whether the structures differ.
    """
    empty = [p for p in names if p.endswith("[]") and not any(n.startswith(p + ".") for n in names)]
    if not empty:
        return other
    prefixes = tuple(p + "." for p in empty)
    return frozenset(n for n in other if not n.startswith(prefixes))


def similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity of two field-name sets after the empty-array rule."""
    ra, rb = _effective(b, a), _effective(a, b)
    union = ra | rb
    return len(ra & rb) / len(union) if union else 1.0


class _Group:
    def __init__(self, tables: list[TableProfile]) -> None:
        self.names = frozenset(tables[0].fields)
        self.types: dict[str, set[str]] = defaultdict(set)
        self.tables: list[TableProfile] = []
        self.add(tables)

    def add(self, tables: list[TableProfile]) -> None:
        self.tables.extend(tables)
        for t in tables:
            for name, types in t.fields.items():
                self.types[name] |= types


def group_tables(tables: list[TableProfile], strict_types: bool = False) -> list[list[TableProfile]]:
    """Partition tables into structure groups, largest first.

    Tables with identical field names form a bucket (with ``strict_types`` also identical
    type families). A bucket joins the existing group whose founding field set is most
    similar (``similarity`` >= SIMILARITY); with ``strict_types`` every shared field must
    also have compatible types. Otherwise the bucket founds a new group.
    """
    buckets: dict[frozenset, list[TableProfile]] = defaultdict(list)
    for t in tables:
        buckets[_key(t, strict_types)].append(t)
    ordered = sorted(buckets.values(), key=lambda b: (-len(b), b[0].path, b[0].sheet or ""))

    groups: list[_Group] = []
    for bucket in ordered:
        names = frozenset(bucket[0].fields)
        fields = bucket[0].fields
        best, best_score = None, SIMILARITY
        for g in groups:
            if not names or not g.names:
                continue
            score = similarity(names, g.names)
            if score < best_score or (best is not None and score == best_score):
                continue
            if not strict_types or all(compatible(fields[n], g.types[n]) for n in names & g.names):
                best, best_score = g, score
        if best is None:
            groups.append(_Group(bucket))
        else:
            best.add(bucket)
    groups.sort(key=lambda g: -len(g.tables))
    return [g.tables for g in groups]
