"""Render a Report as JSON."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from typing import Any

from tuna.report import Report


def _default(o: Any) -> Any:
    if isinstance(o, (dt.date, dt.time)):
        return o.isoformat()
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=str)
    return str(o)


def render_json(report: Report) -> str:
    """Return the report as indented JSON."""
    return json.dumps(asdict(report), default=_default, indent=2, ensure_ascii=False)
