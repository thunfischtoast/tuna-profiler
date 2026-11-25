"""Infer typed path patterns such as ``data/sales_{date:YYYY-MM-DD}.csv``."""

from __future__ import annotations

import datetime as dt
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache

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
_UID = re.compile(r"\d+(?:\.\d+){3,}(?![\d.])")
_HEX = re.compile(r"(?<![0-9a-fA-F])(?:[0-9a-f]{6,}|[0-9A-F]{6,})(?![0-9a-fA-F])")
_RUN = re.compile(r"\d+|[A-Za-z]+|[^A-Za-z\d]+")
_EXT = re.compile(r"\.[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*$")
_DISTINCT_KINDS = {"alpha": "{alpha}", "uuid": "{uuid}", "hex": "{hex}", "uid": "{uid}"}


@dataclass
class NamePattern:
    """A path pattern, how many paths it covers and the value range per placeholder."""

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


def _is_hex(text: str) -> bool:
    return any(c.isdigit() for c in text) and any(c.isalpha() for c in text)


@lru_cache(maxsize=65536)
def _tokenize_segment(segment: str) -> tuple[tuple[str, str], ...]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(segment):
        m = _UUID.match(segment, pos)
        if m:
            tokens.append(("uuid", m.group()))
            pos = m.end()
            continue
        for kind, rx, fmt in _TEMPORAL_RE:
            m = rx.match(segment, pos)
            if m and _parse_temporal(m.group(), fmt):
                tokens.append((kind, m.group()))
                pos = m.end()
                break
        else:
            m = _UID.match(segment, pos)
            if m:
                tokens.append(("uid", m.group()))
                pos = m.end()
                continue
            m = _HEX.match(segment, pos)
            if m and _is_hex(m.group()):
                tokens.append(("hex", m.group()))
                pos = m.end()
                continue
            m = _RUN.match(segment, pos)
            end = m.end()
            if segment[pos].isalpha():
                # A hex id may start with letters, as in ANONffe12a90: end the word before it.
                for j in range(pos + 1, end):
                    h = _HEX.match(segment, j)
                    if h and _is_hex(h.group()):
                        end = j
                        break
            text = segment[pos:end]
            kind = "digits" if text[0].isdigit() else "alpha" if text[0].isalpha() else "other"
            tokens.append((kind, text))
            pos = end
    return tuple(tokens)


def tokenize(stem: str) -> list[tuple[str, str]]:
    """Split a path without extension into (kind, text) tokens.

    Kinds: ``uuid``, ``date:<fmt>``, ``datetime:<fmt>``, ``uid``, ``hex``, ``digits``,
    ``alpha``, ``other``. Each ``/`` is its own ``other`` token; segments are tokenized
    once and cached, because large trees repeat the same folder names many times.
    """
    tokens: list[tuple[str, str]] = []
    for i, segment in enumerate(stem.split("/")):
        if i:
            tokens.append(("other", "/"))
        tokens.extend(_tokenize_segment(segment))
    return tokens


def split_ext(path: str) -> tuple[str, str]:
    """Split the extension off the last path segment; it must contain a letter."""
    m = _EXT.search(path.rsplit("/", 1)[-1])
    if not m or m.start() == 0:
        return path, ""
    return path[: len(path) - len(m.group())], m.group()


def _placeholder(kind: str, values: list[str]) -> tuple[str, str]:
    """Return the placeholder text and a range description for a varying position."""
    if kind == "digits":
        lo, hi = min(values, key=int), max(values, key=int)
        return "{int}", f"{lo} .. {hi}"
    if kind in _DISTINCT_KINDS:
        return _DISTINCT_KINDS[kind], f"{len(set(values))} distinct"
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


def infer_patterns(paths: list[str], min_files: int) -> tuple[list[NamePattern], list[str]]:
    """Infer patterns over relative posix paths.

    Paths are bucketed by token shape (token kinds, separators including ``/`` and
    extension); a bucket with at least ``min_files`` paths becomes a typed pattern.
    Remaining paths sharing an extension fall back to a ``prefix{*}suffix`` pattern if
    there are ``min_files`` of them. Returns the patterns (largest first) and the paths
    no pattern covers.
    """
    shapes: dict[tuple, list[tuple[str, list[tuple[str, str]]]]] = defaultdict(list)
    for name in paths:
        stem, ext = split_ext(name)
        toks = tokenize(stem)
        shape = (ext.lower(), tuple((k, t if k == "other" else "") for k, t in toks))
        shapes[shape].append((name, toks))

    patterns: list[NamePattern] = []
    leftover: list[str] = []
    for members in shapes.values():
        if len(members) >= min_files:
            member_names = [n for n, _ in members]
            ext = split_ext(member_names[0])[1]
            patterns.append(_shape_pattern(member_names, [t for _, t in members], ext))
        else:
            leftover.extend(n for n, _ in members)

    by_ext: dict[str, list[str]] = defaultdict(list)
    for name in leftover:
        by_ext[split_ext(name)[1].lower()].append(name)
    unmatched: list[str] = []
    for group in by_ext.values():
        if len(group) < min_files:
            unmatched.extend(group)
            continue
        stems = [split_ext(n)[0] for n in group]
        prefix = os.path.commonprefix(stems)
        rest = [s[len(prefix):] for s in stems]
        suffix = os.path.commonprefix([r[::-1] for r in rest])[::-1]
        patterns.append(NamePattern(f"{prefix}{{*}}{suffix}{split_ext(group[0])[1]}", len(group)))

    patterns.sort(key=lambda p: (-p.files, p.pattern))
    return patterns, sorted(unmatched)
