"""Group tables that share a tolerant structure."""

from __future__ import annotations

from collections import defaultdict

from tuna.model import TableProfile
from tuna.types import compatible, families

SIMILARITY = 0.8


def _key(t: TableProfile) -> frozenset:
    return frozenset((name, families(types)) for name, types in t.fields.items())


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


def group_tables(tables: list[TableProfile]) -> list[list[TableProfile]]:
    """Partition tables into structure groups, largest first.

    Tables with identical field names and type families form a bucket. A bucket joins
    the existing group whose founding field set is most similar (Jaccard >= SIMILARITY)
    provided every shared field has compatible types; otherwise it founds a new group.
    """
    buckets: dict[frozenset, list[TableProfile]] = defaultdict(list)
    for t in tables:
        buckets[_key(t)].append(t)
    ordered = sorted(buckets.values(), key=lambda b: (-len(b), b[0].path, b[0].sheet or ""))

    groups: list[_Group] = []
    for bucket in ordered:
        names = frozenset(bucket[0].fields)
        fields = bucket[0].fields
        best, best_score = None, SIMILARITY
        for g in groups:
            if not names or not g.names:
                continue
            score = len(names & g.names) / len(names | g.names)
            if score < best_score or (best is not None and score == best_score):
                continue
            if all(compatible(fields[n], g.types[n]) for n in names & g.names):
                best, best_score = g, score
        if best is None:
            groups.append(_Group(bucket))
        else:
            best.add(bucket)
    groups.sort(key=lambda g: -len(g.tables))
    return [g.tables for g in groups]
