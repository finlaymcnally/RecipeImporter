from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in {0, 1}:
            return bool(value)
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no"}:
            return False
    return None


def _excerpt(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3] + "..."


def _clip_strings_deep(value: Any, *, excerpt_limit: int, max_depth: int = 8) -> Any:
    if max_depth <= 0:
        return "<clipped: max depth>"
    if isinstance(value, str):
        return _excerpt(value, max_len=excerpt_limit)
    if isinstance(value, list):
        return [
            _clip_strings_deep(item, excerpt_limit=excerpt_limit, max_depth=max_depth - 1)
            for item in value
        ]
    if isinstance(value, dict):
        clipped: dict[str, Any] = {}
        for key, item in value.items():
            clipped[str(key)] = _clip_strings_deep(
                item,
                excerpt_limit=excerpt_limit,
                max_depth=max_depth - 1,
            )
        return clipped
    return value


def _clip_large_text_fields(row: dict[str, Any], *, excerpt_limit: int) -> dict[str, Any]:
    clipped = dict(row)
    for key in ("line_text_excerpt", "block_text_excerpt", "selected_text", "text"):
        value = clipped.get(key)
        if isinstance(value, str):
            clipped[key] = _excerpt(value, max_len=excerpt_limit)
    return clipped


def _sample_rows_evenly(rows: list[dict[str, Any]], sample_limit: int) -> list[dict[str, Any]]:
    selected_indices = _sample_indices_evenly(len(rows), sample_limit)
    return [rows[index] for index in selected_indices]


def _sample_indices_evenly(total_count: int, sample_limit: int) -> list[int]:
    if total_count <= 0 or sample_limit <= 0:
        return []
    if sample_limit >= total_count:
        return list(range(total_count))
    if sample_limit == 1:
        return [0]

    last_index = total_count - 1
    selected_indices = {
        int(round(position * last_index / (sample_limit - 1))) for position in range(sample_limit)
    }
    if len(selected_indices) < sample_limit:
        extras = [index for index in range(total_count) if index not in selected_indices][
            : sample_limit - len(selected_indices)
        ]
        selected_indices.update(extras)
    return sorted(selected_indices)[:sample_limit]


def _write_jsonl_sample(
    *,
    source_path: Path,
    output_path: Path,
    sample_limit: int,
    excerpt_limit: int,
) -> dict[str, int]:
    rows = _iter_jsonl(source_path)
    sampled_raw = _sample_rows_evenly(rows, sample_limit)
    sampled = [_clip_large_text_fields(row, excerpt_limit=excerpt_limit) for row in sampled_raw]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in sampled:
            handle.write(json.dumps(row))
            handle.write("\n")
    return {"total_rows": len(rows), "sample_rows": len(sampled)}


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row))
            handle.write("\n")


def _jsonl_row_count(path: Path) -> int:
    count = 0
    if not path.is_file():
        return count
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            if raw_line.strip():
                count += 1
    return count
