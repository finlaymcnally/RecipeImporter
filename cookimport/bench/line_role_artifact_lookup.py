from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_WHITESPACE_RE = re.compile(r"\s+")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_line_text(value: Any) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "").strip())


class LineRoleArtifactLookup:
    def __init__(
        self,
        *,
        prediction_rows: list[dict[str, Any]],
        joined_line_rows: list[dict[str, Any]],
    ) -> None:
        self.predictions_by_atomic_index: dict[int, dict[str, Any]] = {}
        self.predictions_by_explicit_line_index: dict[int, dict[str, Any]] = {}
        self.joined_line_indices: set[int] = set()
        self.joined_atomic_index_by_line_index: dict[int, int] = {}
        self._unique_atomic_index_by_text: dict[str, int] = {}

        text_counts: dict[str, int] = {}
        text_atomic_candidates: dict[str, int] = {}
        for row in prediction_rows:
            atomic_index = _coerce_int(row.get("atomic_index"))
            if atomic_index is not None and atomic_index not in self.predictions_by_atomic_index:
                self.predictions_by_atomic_index[atomic_index] = row
            line_index = _coerce_int(row.get("line_index"))
            if line_index is not None and line_index not in self.predictions_by_explicit_line_index:
                self.predictions_by_explicit_line_index[line_index] = row
            normalized_text = _normalize_line_text(row.get("text"))
            if normalized_text:
                text_counts[normalized_text] = text_counts.get(normalized_text, 0) + 1
                if atomic_index is not None and normalized_text not in text_atomic_candidates:
                    text_atomic_candidates[normalized_text] = atomic_index

        for normalized_text, count in text_counts.items():
            if count == 1 and normalized_text in text_atomic_candidates:
                self._unique_atomic_index_by_text[normalized_text] = text_atomic_candidates[
                    normalized_text
                ]

        for row in joined_line_rows:
            line_index = _coerce_int(row.get("line_index"))
            if line_index is None:
                continue
            self.joined_line_indices.add(line_index)
            atomic_index = _coerce_int(row.get("line_role_prediction_atomic_index"))
            if atomic_index is not None:
                self.joined_atomic_index_by_line_index[line_index] = atomic_index

    @classmethod
    def from_run_dir(cls, run_dir: Path) -> "LineRoleArtifactLookup":
        line_role_dir = run_dir / "line-role-pipeline"
        return cls(
            prediction_rows=_read_jsonl(line_role_dir / "line_role_predictions.jsonl"),
            joined_line_rows=_read_jsonl(line_role_dir / "joined_line_table.jsonl"),
        )

    def resolve_atomic_index(
        self,
        *,
        line_index: int,
        line_text: Any = None,
    ) -> int | None:
        if line_index in self.joined_line_indices:
            return self.joined_atomic_index_by_line_index.get(line_index)

        explicit_row = self.predictions_by_explicit_line_index.get(line_index)
        if explicit_row is not None:
            return _coerce_int(explicit_row.get("atomic_index"))

        normalized_text = _normalize_line_text(line_text)
        if normalized_text:
            return self._unique_atomic_index_by_text.get(normalized_text)
        return None

    def resolve_prediction_row(
        self,
        *,
        line_index: int,
        line_text: Any = None,
    ) -> dict[str, Any] | None:
        if line_index in self.joined_line_indices:
            atomic_index = self.joined_atomic_index_by_line_index.get(line_index)
            if atomic_index is None:
                return None
            return self.predictions_by_atomic_index.get(atomic_index)

        explicit_row = self.predictions_by_explicit_line_index.get(line_index)
        if explicit_row is not None:
            return explicit_row

        atomic_index = self.resolve_atomic_index(line_index=line_index, line_text=line_text)
        if atomic_index is None:
            return None
        return self.predictions_by_atomic_index.get(atomic_index)
