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
_FULL_PROMPT_TEMPLATE_FALLBACK = """You are labeling cookbook text BLOCKS for a "freeform spans" golden set.

IMPORTANT IMPLEMENTATION CONSTRAINT
- You must assign exactly ONE label to EACH block.
- Downstream will highlight the ENTIRE block for the label you choose.
  So do NOT try to label substrings. Choose the best single label for the whole block.

GOAL
For each block, choose the label that best describes what the block IS, using local context
(neighboring blocks) to determine whether we are inside a recipe or in general/narrative text.

FOCUS SCOPE
{{FOCUS_CONSTRAINTS}}
Focus blocks to label (context blocks may be broader):
{{FOCUS_BLOCK_JSON_LINES}}

RETURN FORMAT (STRICT)
Return STRICT JSON ONLY. No markdown, no commentary, no extra keys.
Output format exactly:
[{"block_index": <int>, "label": "<LABEL>"}]

HARD RULES
1) Return labels only for focus blocks.
2) Keep the SAME ORDER as the focus blocks listed above.
3) Include each focus block_index exactly once.
4) label must be exactly one of:
   {{ALLOWED_LABELS}}
{{UNCERTAINTY_HINT}}

HOW TO DECIDE (STEP-BY-STEP)
A) First, detect whether a recipe is present nearby:
   - Strong recipe signals: RECIPE_TITLE, a run of INGREDIENT_LINE blocks, numbered steps,
     imperative cooking verbs ("mix", "bake", "stir"), "Serves/Makes", "Prep/Cook/Total".
   - If those signals are present, treat contiguous nearby blocks as part of that recipe
     unless they are clearly unrelated noise (page number, copyright, photo credit, etc).

B) Then label each block using the definitions + tie-break rules below.

LABEL DEFINITIONS (WITH HEURISTICS)

RECIPE_TITLE
- The NAME of a specific dish/recipe (usually short).
- Often Title Case or ALL CAPS; may include descriptors like "Classic...", "Quick...".
- NOT this: chapter/section headers ("Sauces", "Breakfast"), running headers/footers,
  "Ingredients", "Directions", "Method", "Notes" by themselves.

INGREDIENT_LINE
- A line (or block mostly composed of lines) listing ingredients, typically with:
  - a quantity and/or unit (1, 1/2, 200 g, tbsp, cup, oz, ml),
  - an ingredient noun (flour, butter, garlic),
  - optional prep descriptors (chopped, minced, room temperature).
- Also includes ingredient sub-lists that are still ingredients (e.g., "For the sauce: ...").
- If the block is a MIX of ingredients and instructions, label OTHER (see "Mixed blocks").

INSTRUCTION_LINE
- A preparation step: actions to perform, often imperative verbs and sentences:
  "Preheat...", "Whisk...", "Bake...", "Stir...", "Serve..."
- Numbered steps ("1.", "Step 2") are instructions.
- Also includes short imperative fragments ("Let rest 10 minutes.").

YIELD_LINE
- Statements about servings or yield / amount produced:
  "Serves 4", "Makes 24 cookies", "Yield: 2 loaves", "Feeds a crowd", "About 1 quart".
- If yield is embedded with time in the SAME block, use the tie-break rule under TIME_LINE.

TIME_LINE
- Statements about time durations, prep/cook/total/chill/rest times:
  "Prep: 10 min", "Cook time 1 hour", "Total: 1:15", "Chill overnight".
- If a single block contains BOTH time and yield:
  - Choose TIME_LINE if any explicit time durations or "prep/cook/total" appear.
  - Otherwise choose YIELD_LINE.

RECIPE_NOTES
- Extra notes specific to the CURRENT recipe (not a distinct alternate version):
- tips, storage, make-ahead, serving suggestions, substitutions that do not define a new variant,
  warnings ("do not overmix"), sourcing for an ingredient used above, etc.
- Often introduced by: "Note:", "Notes:", "Tip:", "Chef's note:", "Serving suggestion:".
- IMPORTANT: If we are clearly inside a recipe, prefer RECIPE_NOTES instead of KNOWLEDGE.

RECIPE_VARIANT
- An alternate version of the recipe that changes ingredients/method in a defined way:
  "Variation: ...", "Variations: ...", "For a vegan version...", "To make it spicy...", "Option B..."
- If it is a small tip and not a distinct version, use RECIPE_NOTES instead.

KNOWLEDGE
- General cooking knowledge NOT tied to a specific recipe instance:
  technique explanations, ingredient/tool background, how-to guidance, rules of thumb.
  Example: "Searing builds flavor by...", "How to choose ripe avocados..."
- Use KNOWLEDGE mainly when the surrounding text is NOT a recipe (chapter intro, technique section).
- If it appears inside a recipe section, only use KNOWLEDGE if it is clearly a standalone
  general sidebar; otherwise use RECIPE_NOTES.

OTHER
- Anything that does not fit the above labels, including:
- chapter titles/section headers, narrative fluff unrelated to cooking knowledge,
- page numbers, headers/footers, copyright, photo credits,
- indexes, tables of contents, references,
- "Ingredients"/"Directions"/"Method" headers by themselves,
- mixed-content blocks where no single recipe label dominates.

MIXED BLOCKS (IMPORTANT)
Because you can only choose ONE label per block:
- If the block is mostly ingredient lines -> INGREDIENT_LINE.
- If the block is mostly instruction steps -> INSTRUCTION_LINE.
- If it is truly mixed (e.g., ingredients + instructions interleaved, or recipe + narrative) -> OTHER.

FINAL CHECK BEFORE YOU ANSWER
- Did you label every provided block_index exactly once?
- Are labels exactly from the allowed set?
- Is the output STRICT JSON only (no trailing commas, no comments)?

Segment id: {{SEGMENT_ID}}
Blocks:
{{BLOCKS_JSON_LINES}}"""
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
def _build_block_map(task: dict[str, Any]) -> dict[int, tuple[int, int]]:
    _segment_id, segment_text, source_blocks = _extract_task_data(task)
    block_map: dict[int, tuple[int, int]] = {}
    for item in source_blocks:
        block_index_raw = item.get("block_index")
        start_raw = item.get("segment_start")
        end_raw = item.get("segment_end")
        try:
            block_index = int(block_index_raw)
            start = int(start_raw)
            end = int(end_raw)
        except (TypeError, ValueError):
            continue
        if start < 0 or end <= start or end > len(segment_text):
            continue
        block_map[block_index] = (start, end)
    return block_map
def _available_block_indices(source_blocks: list[dict[str, Any]]) -> list[int]:
    available: list[int] = []
    seen: set[int] = set()
    for item in source_blocks:
        block_index_raw = item.get("block_index")
        try:
            block_index = int(block_index_raw)
        except (TypeError, ValueError):
            continue
        if block_index in seen:
            continue
        available.append(block_index)
        seen.add(block_index)
    return available
def _resolve_focus_block_indices(
    *,
    source_map: dict[str, Any],
    available_block_indices: list[int],
) -> list[int]:
    raw_focus_indices = source_map.get("focus_row_indices")
    if not isinstance(raw_focus_indices, list):
        raw_focus_indices = source_map.get("focus_block_indices")
    if not isinstance(raw_focus_indices, list):
        return list(available_block_indices)
    available = set(available_block_indices)
    focus_indices: list[int] = []
    seen: set[int] = set()
    for value in raw_focus_indices:
        try:
            block_index = int(value)
        except (TypeError, ValueError):
            continue
        if block_index in seen or block_index not in available:
            continue
        focus_indices.append(block_index)
        seen.add(block_index)
    if focus_indices:
        return focus_indices
    return list(available_block_indices)
def _resolve_focus_block_index_set(
    *,
    source_map: dict[str, Any],
    source_blocks: list[dict[str, Any]],
) -> set[int]:
    available_indices = _available_block_indices(source_blocks)
    return set(
        _resolve_focus_block_indices(
            source_map=source_map,
            available_block_indices=available_indices,
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
    block_index: int,
    start: int,
    end: int,
    label: str,
) -> dict[str, Any]:
    text = segment_text[start:end]
    digest = hashlib.sha256(
        f"{segment_id}|{block_index}|{start}|{end}|{label}".encode("utf-8")
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
def _contiguous_block_index_span(indices: set[int]) -> tuple[int, int] | None:
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
def _candidate_focus_block_indices_for_quote_repair(
    *,
    block_index: int,
    focus_block_indices: set[int],
) -> list[int]:
    if not focus_block_indices:
        return []
    focus_span = _contiguous_block_index_span(focus_block_indices)
    focus_start = focus_span[0] if focus_span is not None else None
    focus_len = (focus_span[1] - focus_span[0] + 1) if focus_span is not None else None

    anchors: list[int] = []
    if block_index in focus_block_indices:
        anchors.append(block_index)
    if focus_start is not None and focus_len is not None:
        if 0 <= block_index < focus_len:
            anchors.append(focus_start + block_index)
        if 1 <= block_index <= focus_len:
            anchors.append(focus_start + (block_index - 1))

    if not anchors:
        ordered_focus = sorted(focus_block_indices)
        anchors.append(min(ordered_focus, key=lambda value: abs(value - block_index)))

    candidates: list[int] = []
    seen: set[int] = set()
    for anchor in anchors:
        for delta in (0, -1, 1, -2, 2):
            candidate = anchor + delta
            if candidate not in focus_block_indices:
                continue
            if candidate in seen:
                continue
            candidates.append(candidate)
            seen.add(candidate)

    return candidates
def _resolve_quote_span_in_block(
    *,
    block_index: int,
    quote: str,
    occurrence: int | None,
    segment_text: str,
    block_map: dict[int, tuple[int, int]],
) -> tuple[int, int] | None:
    block_offsets = block_map.get(block_index)
    if block_offsets is None:
        return None
    block_start, block_end = block_offsets
    block_text = segment_text[block_start:block_end]
    resolved = _resolve_quote_offsets(
        block_text=block_text,
        quote=quote,
        occurrence=occurrence,
    )
    if resolved is None:
        return None
    start = block_start + resolved[0]
    end = block_start + resolved[1]
    if start < 0 or end <= start or end > len(segment_text):
        return None
    return start, end
def _repair_quote_selection(
    *,
    block_index: int,
    quote: str,
    occurrence: int | None,
    segment_text: str,
    block_map: dict[int, tuple[int, int]],
    focus_block_indices: set[int],
) -> tuple[int, int, int] | None:
    candidates = _candidate_focus_block_indices_for_quote_repair(
        block_index=block_index,
        focus_block_indices=focus_block_indices,
    )
    for candidate in candidates:
        resolved = _resolve_quote_span_in_block(
            block_index=candidate,
            quote=quote,
            occurrence=occurrence,
            segment_text=segment_text,
            block_map=block_map,
        )
        if resolved is None:
            continue
        return candidate, resolved[0], resolved[1]

    matches: list[tuple[int, int, int]] = []
    for candidate in sorted(focus_block_indices):
        resolved = _resolve_quote_span_in_block(
            block_index=candidate,
            quote=quote,
            occurrence=occurrence,
            segment_text=segment_text,
            block_map=block_map,
        )
        if resolved is None:
            continue
        matches.append((candidate, resolved[0], resolved[1]))
        if len(matches) > 1:
            break
    if len(matches) == 1:
        return matches[0]
    return None
def _touched_block_indices_for_span(
    *,
    source_blocks: list[dict[str, Any]],
    start: int,
    end: int,
) -> set[int]:
    touched: set[int] = set()
    for item in source_blocks:
        block_index_raw = item.get("block_index")
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
    block_map: dict[int, tuple[int, int]],
    source_blocks: list[dict[str, Any]],
    focus_block_indices: set[int],
    allowed_labels: set[str],
) -> list[dict[str, Any]]:
    seen_keys: set[tuple[str, int, int]] = set()
    generated: list[dict[str, Any]] = []
    for selection in selections:
        label = normalize_freeform_label(str(selection.get("label") or ""))
        if label not in allowed_labels:
            continue
        kind = str(selection.get("kind") or "")
        block_index = -1
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
            touched_block_indices = _touched_block_indices_for_span(
                source_blocks=source_blocks,
                start=start,
                end=end,
            )
            if (
                not touched_block_indices
                or not touched_block_indices.issubset(focus_block_indices)
            ):
                continue
        elif kind == "quote":
            try:
                block_index = int(selection.get("block_index"))
            except (TypeError, ValueError):
                continue
            quote = str(selection.get("quote") or "")
            if not quote:
                continue
            occurrence = _parse_optional_occurrence(selection.get("occurrence"))
            resolved_block_index: int | None = None
            if block_index in focus_block_indices:
                block_offsets = block_map.get(block_index)
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
                        resolved_block_index = block_index
                    elif match_count == 1:
                        resolved = _resolve_quote_offsets(
                            block_text=block_text,
                            quote=quote,
                            occurrence=occurrence,
                        )
                        if resolved is not None:
                            start = block_start + resolved[0]
                            end = block_start + resolved[1]
                            resolved_block_index = block_index

            if resolved_block_index is None:
                repaired = _repair_quote_selection(
                    block_index=block_index,
                    quote=quote,
                    occurrence=occurrence,
                    segment_text=segment_text,
                    block_map=block_map,
                    focus_block_indices=focus_block_indices,
                )
                if repaired is None:
                    continue
                resolved_block_index, start, end = repaired
                block_index = resolved_block_index
        else:
            continue
        if start < 0 or end <= start or end > len(segment_text):
            continue
        result_item = _build_annotation_result_item(
            segment_id=segment_id,
            segment_text=segment_text,
            block_index=block_index,
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
