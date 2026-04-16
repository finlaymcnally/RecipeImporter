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
from .prelabel_codex import LlmProvider, normalize_prelabel_granularity
from .prelabel_mapping import _resolve_focus_block_indices
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
_SPAN_PROMPT_TEMPLATE_FALLBACK = """You are labeling cookbook text spans for a "freeform spans" golden set.

GOAL
- Return only the specific spans that should be labeled.
- You may return zero, one, or many spans per block.
- Use only these labels:
  {{ALLOWED_LABELS}}

FOCUS SCOPE (READ THIS FIRST)
- The block list appears once at the end as one stream with explicit zone markers.
- Label only spans from blocks between:
  <<<START_LABELING_BLOCKS_HERE>>>
  <<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>>
- Marker legend:
  <<<CONTEXT_BEFORE_LABELING_ONLY>>> = context before focus (read-only)
  <<<CONTEXT_AFTER_LABELING_ONLY>>> = context after focus (read-only)

RETURN FORMAT (STRICT JSON ONLY)
Return ONLY a JSON array. No markdown. No commentary.
Each item must be one of:
1) quote-anchored span (preferred):
   {"block_index": <int>, "label": "<LABEL>", "quote": "<exact text from that block>", "occurrence": <int optional, 1-based>}
2) absolute offset span (advanced fallback):
   {"label": "<LABEL>", "start": <int>, "end": <int>}

RULES
- Return spans only for focus blocks. Non-focus blocks are context only.
- quote text must be copied exactly from block text (case and internal whitespace must match).
- You may omit leading/trailing spaces in quote.
- If the quote appears multiple times in the same block, include occurrence.
- Do not return labels outside the allowed list.

Segment id: {{SEGMENT_ID}}
Blocks (one block per line as "<block_index><TAB><block_text>"):
{{BLOCKS_WITH_FOCUS_MARKERS_COMPACT_LINES}}"""
_PRELABEL_SELECTION_LABEL_ALIASES = {
    "YIELD": "YIELD_LINE",
    "TIME": "TIME_LINE",
    "TIP": "KNOWLEDGE",
    "NOTES": "RECIPE_NOTES",
    "NOTE": "RECIPE_NOTES",
    "VARIANT": "RECIPE_VARIANT",
}

def _load_prompt_template(path: Path, *, fallback: str) -> str:
    cached = _PROMPT_TEMPLATE_CACHE.get(path)
    try:
        mtime_ns = path.stat().st_mtime_ns
        if cached is not None and cached[0] == mtime_ns:
            return cached[1]
        text = path.read_text(encoding="utf-8").strip()
        if text:
            _PROMPT_TEMPLATE_CACHE[path] = (mtime_ns, text)
            return text
    except OSError:
        pass
    return fallback
def _render_prompt_template(
    *,
    path: Path,
    fallback: str,
    replacements: dict[str, str],
) -> str:
    rendered = _load_prompt_template(path, fallback=fallback)
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    return rendered
def _collapse_block_index_ranges(indices: list[int]) -> str:
    if not indices:
        return ""
    ordered = sorted(set(indices))
    ranges: list[str] = []
    start = ordered[0]
    end = ordered[0]
    for value in ordered[1:]:
        if value == end + 1:
            end = value
            continue
        if start == end:
            ranges.append(str(start))
        else:
            ranges.append(f"{start}-{end}")
        start = value
        end = value
    if start == end:
        ranges.append(str(start))
    else:
        ranges.append(f"{start}-{end}")
    return ", ".join(ranges)
def _build_focus_marked_block_lines(
    *,
    valid_blocks: list[tuple[int, str]],
    focus_block_indices: set[int],
) -> list[str]:
    if not valid_blocks:
        return []
    marked: list[str] = []
    in_focus_run = False
    saw_focus = False
    emitted_context_before_marker = False
    emitted_context_after_marker = False
    for block_index, block_text in valid_blocks:
        is_focus = block_index in focus_block_indices
        if not saw_focus and not is_focus and not emitted_context_before_marker:
            marked.append("<<<CONTEXT_BEFORE_LABELING_ONLY>>>")
            emitted_context_before_marker = True
        if is_focus and not in_focus_run:
            marked.append("<<<START_LABELING_BLOCKS_HERE>>>")
            in_focus_run = True
            saw_focus = True
        elif in_focus_run and not is_focus:
            marked.append("<<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>>")
            in_focus_run = False
            if not emitted_context_after_marker:
                marked.append("<<<CONTEXT_AFTER_LABELING_ONLY>>>")
                emitted_context_after_marker = True
        # Keep block text verbatim so quote-copy instructions remain literal.
        marked.append(f"{block_index}\t{block_text}")
    if in_focus_run:
        marked.append("<<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>>")
    return marked
def _extract_valid_blocks_from_segment_text(
    *,
    segment_text: str,
    blocks: list[Any],
) -> list[tuple[int, str]]:
    valid_blocks: list[tuple[int, str]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_index_raw = block.get("block_index")
        start_raw = block.get("segment_start")
        end_raw = block.get("segment_end")
        try:
            block_index = int(block_index_raw)
            start = int(start_raw)
            end = int(end_raw)
        except (TypeError, ValueError):
            continue
        if start < 0 or end <= start or end > len(segment_text):
            continue
        block_text = segment_text[start:end]
        valid_blocks.append((block_index, block_text))
    return valid_blocks
def _extract_prompt_context_blocks(raw_blocks: Any) -> list[tuple[int, str]]:
    if not isinstance(raw_blocks, list):
        return []
    parsed: list[tuple[int, str]] = []
    for item in raw_blocks:
        if not isinstance(item, dict):
            continue
        block_index_raw = item.get("block_index")
        try:
            block_index = int(block_index_raw)
        except (TypeError, ValueError):
            continue
        parsed.append((block_index, str(item.get("text") or "")))
    return parsed
def _build_prompt(
    *,
    task: dict[str, Any],
    allowed_labels: set[str],
    prelabel_granularity: str = PRELABEL_GRANULARITY_SPAN,
) -> str:
    data = task.get("data") if isinstance(task, dict) else {}
    if not isinstance(data, dict):
        raise ValueError("task missing data")
    segment_text = str(data.get("segment_text") or "")
    segment_id = str(data.get("segment_id") or "")
    source_map = data.get("source_map")
    if not isinstance(source_map, dict):
        raise ValueError("task missing source_map")
    blocks = source_map.get("rows")
    if not isinstance(blocks, list):
        raise ValueError("task source_map.rows missing")

    focus_valid_blocks = _extract_valid_blocks_from_segment_text(
        segment_text=segment_text,
        blocks=blocks,
    )
    context_before_blocks = _extract_prompt_context_blocks(
        source_map.get("context_before_rows")
    )
    context_after_blocks = _extract_prompt_context_blocks(
        source_map.get("context_after_rows")
    )

    if context_before_blocks or context_after_blocks:
        valid_blocks = [
            *context_before_blocks,
            *focus_valid_blocks,
            *context_after_blocks,
        ]
    else:
        valid_blocks = list(focus_valid_blocks)

    lines = [
        json.dumps({"block_index": block_index, "text": block_text}, ensure_ascii=False)
        for block_index, block_text in valid_blocks
    ]

    available_block_indices = [
        block_index for block_index, _text in focus_valid_blocks
    ]
    focus_block_indices = _resolve_focus_block_indices(
        source_map=source_map,
        available_block_indices=available_block_indices,
    )
    focus_block_index_set = set(focus_block_indices)
    focus_lines = [
        json.dumps({"block_index": block_index, "text": block_text}, ensure_ascii=False)
        for block_index, block_text in focus_valid_blocks
        if block_index in focus_block_index_set
    ]
    if not focus_lines:
        focus_lines = list(lines)
        focus_block_index_set = {block_index for block_index, _text in valid_blocks}
        focus_block_indices = sorted(focus_block_index_set)

    ordered_allowed_labels = [
        label for label in FREEFORM_LABELS if label in set(allowed_labels)
    ]
    allowed_labels_text = ", ".join(ordered_allowed_labels)
    blocks_json_lines = "\n".join(lines)
    focus_blocks_json_lines = "\n".join(focus_lines)
    blocks_with_focus_markers_compact_lines = "\n".join(
        _build_focus_marked_block_lines(
            valid_blocks=valid_blocks,
            focus_block_indices=focus_block_index_set,
        )
    )
    focus_block_indices_text = _collapse_block_index_ranges(focus_block_indices) or "none"
    all_block_indices = [block_index for block_index, _text in valid_blocks]
    if focus_block_indices:
        first_focus_block = focus_block_indices[0]
        last_focus_block = focus_block_indices[-1]
        context_before_block_indices_text = (
            _collapse_block_index_ranges(
                [block_index for block_index in all_block_indices if block_index < first_focus_block]
            )
            or "none"
        )
        context_after_block_indices_text = (
            _collapse_block_index_ranges(
                [block_index for block_index in all_block_indices if block_index > last_focus_block]
            )
            or "none"
        )
    else:
        context_before_block_indices_text = "none"
        context_after_block_indices_text = "none"
    if len(focus_lines) == len(lines):
        focus_constraints = (
            "- Focus equals context for this task: label all listed blocks.\n"
            f"- Focus block indices: {focus_block_indices_text}."
        )
        focus_marker_rules = "- START/STOP markers wrap the full block list for this task."
    else:
        focus_constraints = (
            f"- Label only focus blocks for this task: {focus_block_indices_text}.\n"
            f"- Context-only blocks BEFORE focus: {context_before_block_indices_text}.\n"
            f"- Context-only blocks AFTER focus: {context_after_block_indices_text}."
        )
        focus_marker_rules = (
            "- <<<CONTEXT_BEFORE_LABELING_ONLY>>> marks read-only context before focus.\n"
            "- <<<START_LABELING_BLOCKS_HERE>>> begins the labelable focus window.\n"
            "- <<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>> ends the labelable focus window.\n"
            "- <<<CONTEXT_AFTER_LABELING_ONLY>>> marks read-only context after focus."
        )

    normalized_granularity = normalize_prelabel_granularity(prelabel_granularity)
    return _render_prompt_template(
        path=_SPAN_PROMPT_TEMPLATE_PATH,
        fallback=_SPAN_PROMPT_TEMPLATE_FALLBACK,
        replacements={
            "{{ALLOWED_LABELS}}": allowed_labels_text,
            "{{FOCUS_CONSTRAINTS}}": focus_constraints,
            "{{FOCUS_BLOCK_JSON_LINES}}": focus_blocks_json_lines,
            "{{FOCUS_BLOCK_INDICES}}": focus_block_indices_text,
            "{{FOCUS_MARKER_RULES}}": focus_marker_rules,
            "{{SEGMENT_ID}}": segment_id,
            "{{BLOCKS_JSON_LINES}}": blocks_json_lines,
            "{{BLOCKS_WITH_FOCUS_MARKERS_COMPACT_LINES}}": blocks_with_focus_markers_compact_lines,
        },
    )
def _build_prompt_log_entry(
    *,
    task: dict[str, Any],
    prompt: str,
    prompt_hash: str,
    allowed_labels: set[str],
    prelabel_granularity: str,
    focus_block_indices: set[int],
    provider: LlmProvider,
) -> dict[str, Any]:
    data = task.get("data") if isinstance(task, dict) else {}
    if not isinstance(data, dict):
        data = {}
    source_map = data.get("source_map")
    if not isinstance(source_map, dict):
        source_map = {}
    source_blocks = source_map.get("rows")
    if not isinstance(source_blocks, list):
        source_blocks = []
    context_before_blocks = source_map.get("context_before_rows")
    if not isinstance(context_before_blocks, list):
        context_before_blocks = []
    context_after_blocks = source_map.get("context_after_rows")
    if not isinstance(context_after_blocks, list):
        context_after_blocks = []
    block_indices: list[int] = []
    for block in source_blocks:
        if not isinstance(block, dict):
            continue
        try:
            block_indices.append(int(block.get("block_index")))
        except (TypeError, ValueError):
            continue
    context_before_indices: list[int] = []
    for block in context_before_blocks:
        if not isinstance(block, dict):
            continue
        try:
            context_before_indices.append(int(block.get("block_index")))
        except (TypeError, ValueError):
            continue
    context_after_indices: list[int] = []
    for block in context_after_blocks:
        if not isinstance(block, dict):
            continue
        try:
            context_after_indices.append(int(block.get("block_index")))
        except (TypeError, ValueError):
            continue
    ordered_allowed_labels = [
        label for label in FREEFORM_LABELS if label in set(allowed_labels)
    ]
    normalized_granularity = normalize_prelabel_granularity(prelabel_granularity)
    template_name = _SPAN_PROMPT_TEMPLATE_PATH.name
    prompt_payload_description = (
        "Prompt includes allowed labels, focus constraints, focus marker rules, "
        "focus index summary, and one markerized context-before/focus/context-after "
        "row text stream (<row_index><TAB><row_text>) "
        "for quote/offset span resolution."
    )
    return {
        "task_scope": "freeform-spans",
        "segment_id": str(data.get("segment_id") or ""),
        "source_file": data.get("source_file"),
        "source_hash": data.get("source_hash"),
        "book_id": data.get("book_id"),
        "granularity": normalized_granularity,
        "prompt_template": template_name,
        "prompt_hash": prompt_hash,
        "prompt": prompt,
        "included_with_prompt": {
            "segment_text_char_count": len(str(data.get("segment_text") or "")),
            "segment_block_count": len(block_indices),
            "segment_block_indices": block_indices,
            "context_before_block_count": len(context_before_indices),
            "context_before_block_indices": context_before_indices,
            "context_after_block_count": len(context_after_indices),
            "context_after_block_indices": context_after_indices,
            "focus_block_count": len(focus_block_indices),
            "focus_block_indices": sorted(focus_block_indices),
            "allowed_labels": ordered_allowed_labels,
            "provider_class": provider.__class__.__name__,
            "provider_cmd": getattr(provider, "cmd", None),
            "provider_model": getattr(provider, "model", None),
        },
        "included_with_prompt_description": prompt_payload_description,
    }
