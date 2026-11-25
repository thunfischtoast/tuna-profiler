"""Infer typed file-name patterns such as ``sales_{date:YYYY-MM-DD}.csv``."""

from __future__ import annotations

import datetime as dt
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

# (kind, regex, strptime format); datetimes come first so their date part is not split off.
_TEMPORAL = [
    ("datetime:YYYYMMDD_HHMMSS", r"\d{8}_\d{6}", "%Y%m%d_%H%M%S"),
    ("datetime:YYYYMMDDTHHMMSS", r"\d{8}T\d{6}", "%Y%m%dT%H%M%S"),
    ("date:YYYY-MM-DD", r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
    ("date:YYYY_MM_DD", r"\d{4}_\d{2}_\d{2}", "%Y_%m_%d"),
    ("date:YYYYMMDD", r"\d{8}", "%Y%m%d"),
    ("date:DD.MM.YYYY", r"\d{2}\.\d{2}\.\d{4}", "%d.%m.%Y"),
    ("date:YYYY-MM", r"\d{4}-\d{2}", "%Y-%m"),
]
_TEMPORAL_RE = [(k, re.compile(rx + r"(?!\d)"), f) for k, rx, f in _TEMPORAL]
_TEMPORAL_FORMATS = {k: f for k, _, f in _TEMPORAL}
_RUN = re.compile(r"\d+|[A-Za-z]+|[^A-Za-z\d]+")


@dataclass
class NamePattern:
    """A name pattern, how many files it covers and the value range per placeholder."""

    pattern: str
    files: int
    ranges: dict[str, str] = field(default_factory=dict)


def _parse_temporal(text: str, fmt: str) -> dt.datetime | None:
    try:
        value = dt.datetime.strptime(text, fmt)  # noqa: DTZ007 - names carry no zone
    except ValueError:
        return None
    # Rejects 8-digit ids such as 12345678 that happen to parse.
    return value if 1900 <= value.year <= 2100 else None


def tokenize(stem: str) -> list[tuple[str, str]]:
    """Split a file stem into (kind, text) tokens.

    Kinds: ``uuid``, ``date:<fmt>``, ``datetime:<fmt>``, ``digits``, ``alpha``, ``other``.
    """
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(stem):
        m = _UUID.match(stem, pos)
        if m:
            tokens.append(("uuid", m.group()))
            pos = m.end()
            continue
        for kind, rx, fmt in _TEMPORAL_RE:
            m = rx.match(stem, pos)
            if m and _parse_temporal(m.group(), fmt):
                tokens.append((kind, m.group()))
                pos = m.end()
                break
        else:
            m = _RUN.match(stem, pos)
            text = m.group()
            kind = "digits" if text[0].isdigit() else "alpha" if text[0].isalpha() else "other"
            tokens.append((kind, text))
            pos = m.end()
    return tokens


def _placeholder(kind: str, values: list[str]) -> tuple[str, str]:
    """Return the placeholder text and a range description for a varying position."""
    if kind == "digits":
        lo, hi = min(values, key=int), max(values, key=int)
        return "{int}", f"{lo} .. {hi}"
    if kind == "alpha":
        return "{alpha}", f"{len(set(values))} distinct"
    if kind == "uuid":
        return "{uuid}", f"{len(set(values))} distinct"
    fmt = _TEMPORAL_FORMATS[kind]
    ordered = sorted(values, key=lambda v: _parse_temporal(v, fmt))
    return "{" + kind + "}", f"{ordered[0]} .. {ordered[-1]}"


def _shape_pattern(names: list[str], tokenized: list[list[tuple[str, str]]], ext: str) -> NamePattern:
    parts: list[str] = []
    ranges: dict[str, str] = {}
    for i, (kind, _) in enumerate(tokenized[0]):
        values = [toks[i][1] for toks in tokenized]
        if kind == "other" or len(set(values)) == 1:
            parts.append(values[0])
            continue
        text, rng = _placeholder(kind, values)
        key = text.strip("{}")
        n = 2
        while key in ranges:
            key = f"{text.strip('{}')}#{n}"
            n += 1
        ranges[key] = rng
        parts.append(text)
    return NamePattern("".join(parts) + ext, len(names), ranges)


def infer_patterns(names: list[str], min_files: int) -> tuple[list[NamePattern], list[str]]:
    """Infer name patterns for a folder's file names.

    Names are bucketed by token shape (token kinds, separators and extension); a bucket
    with at least ``min_files`` names becomes a typed pattern. Remaining names sharing an
    extension fall back to a ``prefix{*}suffix`` pattern if there are ``min_files`` of
    them. Returns the patterns (largest first) and the names no pattern covers.
    """
    shapes: dict[tuple, list[tuple[str, list[tuple[str, str]]]]] = defaultdict(list)
    for name in names:
        stem, ext = os.path.splitext(name)
        toks = tokenize(stem)
        shape = (ext.lower(), tuple((k, t if k == "other" else "") for k, t in toks))
        shapes[shape].append((name, toks))

    patterns: list[NamePattern] = []
    leftover: list[str] = []
    for members in shapes.values():
        if len(members) >= min_files:
            member_names = [n for n, _ in members]
            ext = os.path.splitext(member_names[0])[1]
            patterns.append(_shape_pattern(member_names, [t for _, t in members], ext))
        else:
            leftover.extend(n for n, _ in members)

    by_ext: dict[str, list[str]] = defaultdict(list)
    for name in leftover:
        by_ext[os.path.splitext(name)[1].lower()].append(name)
    unmatched: list[str] = []
    for group in by_ext.values():
        if len(group) < min_files:
            unmatched.extend(group)
            continue
        stems = [os.path.splitext(n)[0] for n in group]
        prefix = os.path.commonprefix(stems)
        rest = [s[len(prefix):] for s in stems]
        suffix = os.path.commonprefix([r[::-1] for r in rest])[::-1]
        patterns.append(NamePattern(f"{prefix}{{*}}{suffix}{os.path.splitext(group[0])[1]}", len(group)))

    patterns.sort(key=lambda p: (-p.files, p.pattern))
    return patterns, sorted(unmatched)
