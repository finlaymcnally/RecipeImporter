from __future__ import annotations
import base64
import binascii
import hashlib
import json
import os
import re
import shlex
import subprocess
import threading
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Protocol
from cookimport.config.runtime_support import resolve_prelabel_cache_dir
from cookimport.llm.codex_farm_runner import (
    CodexFarmRunner,
    SubprocessCodexFarmRunner,
    as_pipeline_run_result_payload,
    ensure_codex_farm_pipelines_exist,
)
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_ALLOWED_LABELS,
    FREEFORM_LABELS,
    FREEFORM_LABEL_CONTROL_NAME,
    FREEFORM_LABEL_RESULT_TYPE,
    FREEFORM_TEXT_NAME,
    normalize_freeform_label,
)
from .prelabel_parse import _parse_optional_occurrence
_MODEL_CONFIG_LINE_RE = re.compile(r"^\s*model\s*=\s*['\"]([^'\"]+)['\"]\s*$")
_MODEL_REASONING_EFFORT_CONFIG_LINE_RE = re.compile(
    r"^\s*model_reasoning_effort\s*=\s*['\"]([^'\"]+)['\"]\s*$"
)
_CODEX_EXECUTABLES = {"codex", "codex.exe", "codex2", "codex2.exe"}
_CODEX_ALT_EXECUTABLE_RE = re.compile(r"^codex[0-9]+(?:\.exe)?$")
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_PRELABEL_CODEX_FARM_PIPELINE_ID = "prelabel.freeform.v1"
_PRELABEL_CODEX_FARM_DEFAULT_CMD = "codex-farm"
_PROMPT_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "llm_pipelines" / "prompts"
_FULL_PROMPT_TEMPLATE_PATH = _PROMPT_TEMPLATE_DIR / "freeform-prelabel-full.prompt.md"
_SPAN_PROMPT_TEMPLATE_PATH = _PROMPT_TEMPLATE_DIR / "freeform-prelabel-span.prompt.md"
_PROMPT_TEMPLATE_CACHE: dict[Path, tuple[int, str]] = {}
PRELABEL_GRANULARITY_SPAN = "span"
CODEX_REASONING_EFFORT_VALUES = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)
_RATE_LIMIT_MESSAGE_RE = re.compile(
    r"\b429\b|too many requests|rate[ -]?limit(?:ed|ing)?",
    re.IGNORECASE,
)
def _extract_task_data(task: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    data = task.get("data")
    if not isinstance(data, dict):
        raise ValueError("task missing data object")
    segment_id = str(data.get("segment_id") or "")
    if not segment_id:
        raise ValueError("task missing data.segment_id")
    segment_text = str(data.get("segment_text") or "")
    source_map = data.get("source_map")
    if not isinstance(source_map, dict):
        raise ValueError("task missing data.source_map")
    blocks = source_map.get("rows")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("task source_map.rows missing/empty")
    source_blocks = [item for item in blocks if isinstance(item, dict)]
    if not source_blocks:
        raise ValueError("task source_map.rows has no valid entries")
    return segment_id, segment_text, source_blocks
def _build_row_map(task: dict[str, Any]) -> dict[int, tuple[int, int]]:
    _segment_id, segment_text, source_blocks = _extract_task_data(task)
    row_map: dict[int, tuple[int, int]] = {}
    for item in source_blocks:
        row_index_raw = item.get("row_index", item.get("block_index"))
        start_raw = item.get("segment_start")
        end_raw = item.get("segment_end")
        try:
            row_index = int(row_index_raw)
            start = int(start_raw)
            end = int(end_raw)
        except (TypeError, ValueError):
            continue
        if start < 0 or end <= start or end > len(segment_text):
            continue
        row_map[row_index] = (start, end)
    return row_map
def _available_row_indices(source_blocks: list[dict[str, Any]]) -> list[int]:
    available: list[int] = []
    seen: set[int] = set()
    for item in source_blocks:
        row_index_raw = item.get("row_index", item.get("block_index"))
        try:
            row_index = int(row_index_raw)
        except (TypeError, ValueError):
            continue
        if row_index in seen:
            continue
        available.append(row_index)
        seen.add(row_index)
    return available
def _resolve_focus_row_indices(
    *,
    source_map: dict[str, Any],
    available_row_indices: list[int],
) -> list[int]:
    raw_focus_indices = source_map.get("focus_row_indices")
    if not isinstance(raw_focus_indices, list):
        return list(available_row_indices)
    available = set(available_row_indices)
    focus_indices: list[int] = []
    seen: set[int] = set()
    for value in raw_focus_indices:
        try:
            row_index = int(value)
        except (TypeError, ValueError):
            continue
        if row_index in seen or row_index not in available:
            continue
        focus_indices.append(row_index)
        seen.add(row_index)
    if focus_indices:
        return focus_indices
    return list(available_row_indices)
def _resolve_focus_row_index_set(
    *,
    source_map: dict[str, Any],
    source_blocks: list[dict[str, Any]],
) -> set[int]:
    available_indices = _available_row_indices(source_blocks)
    return set(
        _resolve_focus_row_indices(
            source_map=source_map,
            available_row_indices=available_indices,
        )
    )
def _result_key(result_item: dict[str, Any]) -> tuple[str, int, int]:
    value = result_item.get("value")
    if not isinstance(value, dict):
        return ("", -1, -1)
    labels = value.get("labels")
    if not isinstance(labels, list) or not labels:
        return ("", -1, -1)
    label = normalize_freeform_label(str(labels[0]))
    try:
        start = int(value.get("start"))
        end = int(value.get("end"))
    except (TypeError, ValueError):
        return ("", -1, -1)
    return (label, start, end)
def annotation_labels(annotation: dict[str, Any] | None) -> set[str]:
    """Return canonical label names used in an annotation."""
    if not isinstance(annotation, dict):
        return set()
    labels: set[str] = set()
    for item in annotation.get("result") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        for label in value.get("labels") or []:
            labels.add(normalize_freeform_label(str(label)))
    return labels
def _build_annotation_result_item(
    *,
    segment_id: str,
    segment_text: str,
    row_index: int,
    start: int,
    end: int,
    label: str,
) -> dict[str, Any]:
    text = segment_text[start:end]
    digest = hashlib.sha256(
        f"{segment_id}|{row_index}|{start}|{end}|{label}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "id": f"cookimport-prelabel-{digest}",
        "from_name": FREEFORM_LABEL_CONTROL_NAME,
        "to_name": FREEFORM_TEXT_NAME,
        "type": FREEFORM_LABEL_RESULT_TYPE,
        "value": {
            "start": start,
            "end": end,
            "text": text,
            "labels": [label],
        },
    }
def _find_substring_matches(text: str, needle: str) -> list[tuple[int, int]]:
    if not needle:
        return []
    matches: list[tuple[int, int]] = []
    cursor = 0
    while cursor <= len(text) - len(needle):
        found = text.find(needle, cursor)
        if found < 0:
            break
        matches.append((found, found + len(needle)))
        cursor = found + 1
    return matches
def _resolve_quote_offsets(
    *,
    block_text: str,
    quote: str,
    occurrence: int | None,
) -> tuple[int, int] | None:
    candidates = [quote]
    stripped = quote.strip()
    if stripped and stripped != quote:
        candidates.append(stripped)

    for needle in candidates:
        matches = _find_substring_matches(block_text, needle)
        if not matches:
            continue
        if len(matches) == 1:
            return matches[0]
        if occurrence is None:
            return None
        if 1 <= occurrence <= len(matches):
            return matches[occurrence - 1]
        return None
    return None
def _contiguous_row_index_span(indices: set[int]) -> tuple[int, int] | None:
    if not indices:
        return None
    ordered = sorted(indices)
    start = ordered[0]
    end = ordered[-1]
    if end - start + 1 != len(ordered):
        return None
    return start, end
def _quote_match_count(block_text: str, quote: str) -> int:
    if not quote:
        return 0
    candidates = [quote]
    stripped = quote.strip()
    if stripped and stripped != quote:
        candidates.append(stripped)
    for needle in candidates:
        matches = _find_substring_matches(block_text, needle)
        if matches:
            return len(matches)
    return 0
def _candidate_focus_row_indices_for_quote_repair(
    *,
    row_index: int,
    focus_row_indices: set[int],
) -> list[int]:
    if not focus_row_indices:
        return []
    focus_span = _contiguous_row_index_span(focus_row_indices)
    focus_start = focus_span[0] if focus_span is not None else None
    focus_len = (focus_span[1] - focus_span[0] + 1) if focus_span is not None else None

    anchors: list[int] = []
    if row_index in focus_row_indices:
        anchors.append(row_index)
    if focus_start is not None and focus_len is not None:
        if 0 <= row_index < focus_len:
            anchors.append(focus_start + row_index)
        if 1 <= row_index <= focus_len:
            anchors.append(focus_start + (row_index - 1))

    if not anchors:
        ordered_focus = sorted(focus_row_indices)
        anchors.append(min(ordered_focus, key=lambda value: abs(value - row_index)))

    candidates: list[int] = []
    seen: set[int] = set()
    for anchor in anchors:
        for delta in (0, -1, 1, -2, 2):
            candidate = anchor + delta
            if candidate not in focus_row_indices:
                continue
            if candidate in seen:
                continue
            candidates.append(candidate)
            seen.add(candidate)

    return candidates
def _resolve_quote_span_in_row(
    *,
    row_index: int,
    quote: str,
    occurrence: int | None,
    segment_text: str,
    row_map: dict[int, tuple[int, int]],
) -> tuple[int, int] | None:
    row_offsets = row_map.get(row_index)
    if row_offsets is None:
        return None
    row_start, row_end = row_offsets
    block_text = segment_text[row_start:row_end]
    resolved = _resolve_quote_offsets(
        block_text=block_text,
        quote=quote,
        occurrence=occurrence,
    )
    if resolved is None:
        return None
    start = row_start + resolved[0]
    end = row_start + resolved[1]
    if start < 0 or end <= start or end > len(segment_text):
        return None
    return start, end
def _repair_quote_selection(
    *,
    row_index: int,
    quote: str,
    occurrence: int | None,
    segment_text: str,
    row_map: dict[int, tuple[int, int]],
    focus_row_indices: set[int],
) -> tuple[int, int, int] | None:
    candidates = _candidate_focus_row_indices_for_quote_repair(
        row_index=row_index,
        focus_row_indices=focus_row_indices,
    )
    for candidate in candidates:
        resolved = _resolve_quote_span_in_row(
            row_index=candidate,
            quote=quote,
            occurrence=occurrence,
            segment_text=segment_text,
            row_map=row_map,
        )
        if resolved is None:
            continue
        return candidate, resolved[0], resolved[1]

    matches: list[tuple[int, int, int]] = []
    for candidate in sorted(focus_row_indices):
        resolved = _resolve_quote_span_in_row(
            row_index=candidate,
            quote=quote,
            occurrence=occurrence,
            segment_text=segment_text,
            row_map=row_map,
        )
        if resolved is None:
            continue
        matches.append((candidate, resolved[0], resolved[1]))
        if len(matches) > 1:
            break
    if len(matches) == 1:
        return matches[0]
    return None
def _touched_row_indices_for_span(
    *,
    source_blocks: list[dict[str, Any]],
    start: int,
    end: int,
) -> set[int]:
    touched: set[int] = set()
    for item in source_blocks:
        block_index_raw = item.get("row_index", item.get("block_index"))
        block_start_raw = item.get("segment_start")
        block_end_raw = item.get("segment_end")
        try:
            block_index = int(block_index_raw)
            block_start = int(block_start_raw)
            block_end = int(block_end_raw)
        except (TypeError, ValueError):
            continue
        if end <= block_start or start >= block_end:
            continue
        touched.add(block_index)
    return touched
def _build_results_for_span_mode(
    *,
    selections: list[dict[str, Any]],
    segment_id: str,
    segment_text: str,
    row_map: dict[int, tuple[int, int]],
    source_blocks: list[dict[str, Any]],
    focus_row_indices: set[int],
    allowed_labels: set[str],
) -> list[dict[str, Any]]:
    seen_keys: set[tuple[str, int, int]] = set()
    generated: list[dict[str, Any]] = []
    for selection in selections:
        label = normalize_freeform_label(str(selection.get("label") or ""))
        if label not in allowed_labels:
            continue
        kind = str(selection.get("kind") or "")
        row_index = -1
        start = -1
        end = -1
        if kind == "absolute":
            try:
                start = int(selection.get("start"))
                end = int(selection.get("end"))
            except (TypeError, ValueError):
                continue
            if start < 0 or end <= start or end > len(segment_text):
                continue
            touched_row_indices = _touched_row_indices_for_span(
                source_blocks=source_blocks,
                start=start,
                end=end,
            )
            if (
                not touched_row_indices
                or not touched_row_indices.issubset(focus_row_indices)
            ):
                continue
        elif kind == "quote":
            try:
                row_index = int(selection.get("row_index", selection.get("block_index")))
            except (TypeError, ValueError):
                continue
            quote = str(selection.get("quote") or "")
            if not quote:
                continue
            occurrence = _parse_optional_occurrence(selection.get("occurrence"))
            resolved_block_index: int | None = None
            if row_index in focus_row_indices:
                block_offsets = row_map.get(row_index)
                if block_offsets is not None:
                    block_start, block_end = block_offsets
                    block_text = segment_text[block_start:block_end]
                    match_count = _quote_match_count(block_text, quote)
                    if match_count > 1 and occurrence is None:
                        continue
                    if match_count > 0 and occurrence is not None:
                        resolved = _resolve_quote_offsets(
                            block_text=block_text,
                            quote=quote,
                            occurrence=occurrence,
                        )
                        if resolved is None:
                            continue
                        start = block_start + resolved[0]
                        end = block_start + resolved[1]
                        resolved_block_index = row_index
                    elif match_count == 1:
                        resolved = _resolve_quote_offsets(
                            block_text=block_text,
                            quote=quote,
                            occurrence=occurrence,
                        )
                        if resolved is not None:
                            start = block_start + resolved[0]
                            end = block_start + resolved[1]
                            resolved_block_index = row_index

            if resolved_block_index is None:
                repaired = _repair_quote_selection(
                    row_index=row_index,
                    quote=quote,
                    occurrence=occurrence,
                    segment_text=segment_text,
                    row_map=row_map,
                    focus_row_indices=focus_row_indices,
                )
                if repaired is None:
                    continue
                resolved_block_index, start, end = repaired
                row_index = resolved_block_index
        else:
            continue
        if start < 0 or end <= start or end > len(segment_text):
            continue
        result_item = _build_annotation_result_item(
            segment_id=segment_id,
            segment_text=segment_text,
            row_index=row_index,
            start=start,
            end=end,
            label=label,
        )
        result_key = _result_key(result_item)
        if result_key in seen_keys:
            continue
        generated.append(result_item)
        seen_keys.add(result_key)
    return generated
