"""Decision tracing for chunking/segmentation.

Records structured events so failures can be explained in terms of
specific rule/threshold decisions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TraceCollector:
    """Collects structured trace events during chunking."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def record(
        self,
        event_type: str,
        block_index: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._events.append({
            "event_type": event_type,
            "block_index": block_index,
            "details": details or {},
        })

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def write(self, path: Path) -> None:
        """Write events as JSONL."""
        lines = [json.dumps(evt) for evt in self._events]
        path.write_text(
            "\n".join(lines) + "\n" if lines else "", encoding="utf-8"
        )

    def clear(self) -> None:
        self._events.clear()
