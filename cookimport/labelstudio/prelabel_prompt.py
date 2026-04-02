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
PRELABEL_GRANULARITY_BLOCK = "block"
PRELABEL_GRANULARITY_SPAN = "span"
_PRELABEL_GRANULARITY_ALIASES = {
    PRELABEL_GRANULARITY_BLOCK: PRELABEL_GRANULARITY_BLOCK,
    PRELABEL_GRANULARITY_SPAN: PRELABEL_GRANULARITY_SPAN,
}
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
    prelabel_granularity: str = PRELABEL_GRANULARITY_BLOCK,
) -> str:
    data = task.get("data") if isinstance(task, dict) else {}
    if not isinstance(data, dict):
        raise ValueError("task missing data")
    segment_text = str(data.get("segment_text") or "")
    segment_id = str(data.get("segment_id") or "")
    source_map = data.get("source_map")
    if not isinstance(source_map, dict):
        raise ValueError("task missing source_map")
    blocks = source_map.get("blocks")
    if not isinstance(blocks, list):
        raise ValueError("task source_map.blocks missing")

    focus_valid_blocks = _extract_valid_blocks_from_segment_text(
        segment_text=segment_text,
        blocks=blocks,
    )
    context_before_blocks = _extract_prompt_context_blocks(
        source_map.get("context_before_blocks")
    )
    context_after_blocks = _extract_prompt_context_blocks(
        source_map.get("context_after_blocks")
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
    if normalized_granularity == PRELABEL_GRANULARITY_SPAN:
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

    if "OTHER" in ordered_allowed_labels and "RECIPE_NOTES" in ordered_allowed_labels:
        uncertainty_hint = (
            "5) If uncertain, prefer OTHER (or RECIPE_NOTES if clearly inside a recipe)."
        )
    elif "OTHER" in ordered_allowed_labels:
        uncertainty_hint = "5) If uncertain, prefer OTHER."
    else:
        uncertainty_hint = "5) If uncertain, choose the closest allowed label."

    return _render_prompt_template(
        path=_FULL_PROMPT_TEMPLATE_PATH,
        fallback=_FULL_PROMPT_TEMPLATE_FALLBACK,
        replacements={
            "{{ALLOWED_LABELS}}": allowed_labels_text,
            "{{UNCERTAINTY_HINT}}": uncertainty_hint,
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
    source_blocks = source_map.get("blocks")
    if not isinstance(source_blocks, list):
        source_blocks = []
    context_before_blocks = source_map.get("context_before_blocks")
    if not isinstance(context_before_blocks, list):
        context_before_blocks = []
    context_after_blocks = source_map.get("context_after_blocks")
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
    template_name = (
        _SPAN_PROMPT_TEMPLATE_PATH.name
        if normalized_granularity == PRELABEL_GRANULARITY_SPAN
        else _FULL_PROMPT_TEMPLATE_PATH.name
    )
    if normalized_granularity == PRELABEL_GRANULARITY_SPAN:
        prompt_payload_description = (
            "Prompt includes allowed labels, focus constraints, focus marker rules, "
            "focus index summary, and one markerized context-before/focus/context-after "
            "block text stream (<block_index><TAB><block_text>) "
            "for quote/offset span resolution."
        )
    else:
        prompt_payload_description = (
            "Prompt includes allowed labels, uncertainty guidance, focus constraints, "
            "focus block JSON lines, and full context block JSON lines for block labels."
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
