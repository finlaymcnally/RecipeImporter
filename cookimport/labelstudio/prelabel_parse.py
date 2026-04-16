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
- You may return zero, one, or many spans per row.
- Use only these labels:
  {{ALLOWED_LABELS}}

FOCUS SCOPE (READ THIS FIRST)
- The row list appears once at the end as one stream with explicit zone markers.
- Label only spans from rows between:
  <<<START_LABELING_ROWS_HERE>>>
  <<<STOP_LABELING_ROWS_HERE_CONTEXT_ONLY>>>
- Marker legend:
  <<<CONTEXT_BEFORE_LABELING_ONLY>>> = context before focus (read-only)
  <<<CONTEXT_AFTER_LABELING_ONLY>>> = context after focus (read-only)

RETURN FORMAT (STRICT JSON ONLY)
Return ONLY a JSON array. No markdown. No commentary.
Each item must be one of:
1) quote-anchored span (preferred):
   {"row_index": <int>, "label": "<LABEL>", "quote": "<exact text from that row>", "occurrence": <int optional, 1-based>}
2) absolute offset span (advanced fallback):
   {"label": "<LABEL>", "start": <int>, "end": <int>}

RULES
- Return spans only for focus rows. Non-focus rows are context only.
- quote text must be copied exactly from row text (case and internal whitespace must match).
- You may omit leading/trailing spaces in quote.
- If the quote appears multiple times in the same row, include occurrence.
- Do not return labels outside the allowed list.

Segment id: {{SEGMENT_ID}}
Rows (one row per line as "<row_index><TAB><row_text>"):
{{ROWS_WITH_FOCUS_MARKERS_COMPACT_LINES}}"""
_PRELABEL_SELECTION_LABEL_ALIASES = {
    "YIELD": "YIELD_LINE",
    "TIME": "TIME_LINE",
    "TIP": "KNOWLEDGE",
    "NOTES": "RECIPE_NOTES",
    "NOTE": "RECIPE_NOTES",
    "VARIANT": "RECIPE_VARIANT",
}

def extract_first_json_value(raw: str) -> Any:
    """Extract the first JSON array/object embedded in model output."""
    decoder = json.JSONDecoder()
    for index, ch in enumerate(raw):
        if ch not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        return value
    raise ValueError("No JSON object/array found in model output")
def _coerce_selection_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("selections", "labels", "items", "blocks"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]
def _normalize_prelabel_selection_label(raw: str) -> str:
    normalized = normalize_freeform_label(raw)
    return _PRELABEL_SELECTION_LABEL_ALIASES.get(normalized, normalized)
def _parse_optional_occurrence(value: Any) -> int | None:
    if value is None:
        return None
    try:
        occurrence = int(value)
    except (TypeError, ValueError):
        return None
    if occurrence < 1:
        return None
    return occurrence
def parse_span_label_output(raw: str) -> list[dict[str, Any]]:
    """Parse model output into quote-anchored and absolute span selections."""
    payload = extract_first_json_value(raw)
    items = _coerce_selection_items(payload)
    parsed: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in items:
        label_raw = item.get("label") or item.get("tag") or item.get("category")
        if not label_raw:
            continue
        label = _normalize_prelabel_selection_label(str(label_raw))
        start_raw = item.get("start")
        end_raw = item.get("end")
        if start_raw is not None and end_raw is not None:
            try:
                start = int(start_raw)
                end = int(end_raw)
            except (TypeError, ValueError):
                continue
            key = ("absolute", label, start, end)
            if key in seen:
                continue
            seen.add(key)
            parsed.append(
                {
                    "kind": "absolute",
                    "label": label,
                    "start": start,
                    "end": end,
                }
            )
            continue

        row_index_raw = item.get("row_index")
        quote_raw = item.get("quote")
        if quote_raw is None:
            quote_raw = item.get("text") or item.get("span")
        if row_index_raw is None or quote_raw is None:
            continue
        try:
            row_index = int(row_index_raw)
        except (TypeError, ValueError):
            continue
        quote = str(quote_raw)
        if not quote:
            continue
        occurrence = _parse_optional_occurrence(item.get("occurrence"))
        key = ("quote", row_index, label, quote, occurrence)
        if key in seen:
            continue
        seen.add(key)
        parsed.append(
            {
                "kind": "quote",
                "row_index": row_index,
                "label": label,
                "quote": quote,
                "occurrence": occurrence,
            }
        )
    return parsed
