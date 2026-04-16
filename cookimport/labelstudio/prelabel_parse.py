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

        block_index_raw = item.get("block_index")
        quote_raw = item.get("quote")
        if quote_raw is None:
            quote_raw = item.get("text") or item.get("span")
        if block_index_raw is None or quote_raw is None:
            continue
        try:
            block_index = int(block_index_raw)
        except (TypeError, ValueError):
            continue
        quote = str(quote_raw)
        if not quote:
            continue
        occurrence = _parse_optional_occurrence(item.get("occurrence"))
        key = ("quote", block_index, label, quote, occurrence)
        if key in seen:
            continue
        seen.add(key)
        parsed.append(
            {
                "kind": "quote",
                "block_index": block_index,
                "label": label,
                "quote": quote,
                "occurrence": occurrence,
            }
        )
    return parsed
