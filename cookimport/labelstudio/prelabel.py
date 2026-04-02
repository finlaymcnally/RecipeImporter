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
from . import prelabel_codex as _prelabel_codex_module
from . import prelabel_prompt as _prelabel_prompt_module
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

from .prelabel_codex import (
    LlmProvider,
    CodexFarmProvider as _CodexFarmProviderImpl,
    normalize_prelabel_granularity,
    normalize_codex_reasoning_effort,
    _normalize_codex_error_detail,
    is_rate_limit_message,
    _argv_with_json_events,
    _is_codex_executable,
    _split_command_env_and_argv,
    _extract_config_override_value,
    _extract_model_from_config_override,
    _extract_reasoning_effort_from_config_override,
    _dedupe_paths,
    _codex_home_roots,
    _codex_config_paths,
    _codex_models_cache_paths,
    _codex_auth_paths,
    _decode_jwt_claims,
    _claims_email,
    _claims_plan,
    codex_account_info,
    codex_account_summary,
    _argv_has_model_setting,
    _argv_has_reasoning_effort_setting,
    codex_cmd_with_model,
    codex_cmd_with_reasoning_effort,
    codex_model_from_cmd,
    codex_reasoning_effort_from_cmd,
    default_codex_model,
    default_codex_reasoning_effort,
    default_codex_reasoning_effort_for_model,
    _supported_reasoning_efforts_from_model_row,
    list_codex_models,
    resolve_codex_model,
    _resolve_codex_farm_root,
    _resolve_codex_farm_workspace_root,
    _ensure_prelabel_codex_farm_pipeline,
    _coerce_int,
    _codex_farm_return_code,
    _codex_farm_usage_payload,
    run_codex_farm_json_prompt,
    preflight_codex_model_access as _preflight_codex_model_access_impl,
    default_codex_cmd,
)
from .prelabel_parse import (
    extract_first_json_value,
    _coerce_selection_items,
    _normalize_prelabel_selection_label,
    parse_block_label_output,
    _parse_optional_occurrence,
    parse_span_label_output,
)
from .prelabel_mapping import (
    _extract_task_data,
    _build_block_map,
    _available_block_indices,
    _resolve_focus_block_indices,
    _resolve_focus_block_index_set,
    _result_key,
    annotation_labels,
    _build_annotation_result_item,
    _find_substring_matches,
    _resolve_quote_offsets,
    _contiguous_block_index_span,
    _quote_match_count,
    _candidate_focus_block_indices_for_quote_repair,
    _resolve_quote_span_in_block,
    _repair_quote_selection,
    _touched_block_indices_for_span,
    _build_results_for_block_mode,
    _build_results_for_span_mode,
)
from .prelabel_prompt import (
    _load_prompt_template,
    _render_prompt_template,
    _collapse_block_index_ranges,
    _build_focus_marked_block_lines,
    _extract_valid_blocks_from_segment_text,
    _extract_prompt_context_blocks,
    _build_prompt,
    _build_prompt_log_entry,
)

_PROMPT_TEMPLATE_CACHE = _prelabel_prompt_module._PROMPT_TEMPLATE_CACHE


class CodexFarmProvider(_CodexFarmProviderImpl):
    def complete(self, prompt: str) -> str:
        _prelabel_codex_module.run_codex_farm_json_prompt = run_codex_farm_json_prompt
        return super().complete(prompt)


def preflight_codex_model_access(*, cmd: str, timeout_s: int) -> None:
    _prelabel_codex_module.run_codex_farm_json_prompt = run_codex_farm_json_prompt
    _preflight_codex_model_access_impl(cmd=cmd, timeout_s=timeout_s)

def prelabel_freeform_task(
    task: dict[str, Any],
    *,
    provider: LlmProvider,
    allowed_labels: set[str] | None = None,
    prelabel_granularity: str = PRELABEL_GRANULARITY_BLOCK,
    prompt_log_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    """Generate one Label Studio annotation from LLM prelabel suggestions."""
    normalized_allowed = {
        normalize_freeform_label(label)
        for label in (allowed_labels or set(FREEFORM_ALLOWED_LABELS))
    }
    normalized_allowed = {
        label for label in normalized_allowed if label in FREEFORM_ALLOWED_LABELS
    }
    if not normalized_allowed:
        raise ValueError("allowed_labels cannot be empty")
    normalized_granularity = normalize_prelabel_granularity(prelabel_granularity)

    segment_id, segment_text, source_blocks = _extract_task_data(task)
    data = task.get("data")
    if not isinstance(data, dict):
        raise ValueError("task missing data object")
    source_map = data.get("source_map")
    if not isinstance(source_map, dict):
        raise ValueError("task missing data.source_map")
    focus_block_indices = _resolve_focus_block_index_set(
        source_map=source_map,
        source_blocks=source_blocks,
    )
    if not focus_block_indices:
        raise ValueError("task source_map has no valid focus block indices")

    block_map = _build_block_map(task)
    if not block_map:
        raise ValueError("task source_map has no valid block offsets")

    _prelabel_prompt_module._FULL_PROMPT_TEMPLATE_PATH = _FULL_PROMPT_TEMPLATE_PATH
    _prelabel_prompt_module._SPAN_PROMPT_TEMPLATE_PATH = _SPAN_PROMPT_TEMPLATE_PATH
    _prelabel_prompt_module._PROMPT_TEMPLATE_CACHE = _PROMPT_TEMPLATE_CACHE
    _prelabel_codex_module.run_codex_farm_json_prompt = run_codex_farm_json_prompt
    prompt = _build_prompt(
        task=task,
        allowed_labels=normalized_allowed,
        prelabel_granularity=normalized_granularity,
    )
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    if prompt_log_callback is not None:
        prompt_log_callback(
            _build_prompt_log_entry(
                task=task,
                prompt=prompt,
                prompt_hash=prompt_hash,
                allowed_labels=normalized_allowed,
                prelabel_granularity=normalized_granularity,
                focus_block_indices=focus_block_indices,
                provider=provider,
            )
        )

    raw = provider.complete(prompt)
    payload = extract_first_json_value(raw)
    raw_was_empty_array = isinstance(payload, list) and not payload
    if normalized_granularity == PRELABEL_GRANULARITY_SPAN:
        selections = parse_span_label_output(raw)
        generated = _build_results_for_span_mode(
            selections=selections,
            segment_id=segment_id,
            segment_text=segment_text,
            block_map=block_map,
            source_blocks=source_blocks,
            focus_block_indices=focus_block_indices,
            allowed_labels=normalized_allowed,
        )
    else:
        selections = parse_block_label_output(raw)
        generated = _build_results_for_block_mode(
            selections=selections,
            segment_id=segment_id,
            segment_text=segment_text,
            block_map=block_map,
            focus_block_indices=focus_block_indices,
            allowed_labels=normalized_allowed,
        )

    if not generated:
        if raw_was_empty_array:
            return {
                "result": [],
                "meta": {
                    "cookimport_prelabel": True,
                    "mode": "empty",
                    "provider": provider.__class__.__name__,
                    "prompt_hash": prompt_hash,
                    "granularity": normalized_granularity,
                },
            }
        return None

    return {
        "result": generated,
        "meta": {
            "cookimport_prelabel": True,
            "mode": "full",
            "provider": provider.__class__.__name__,
            "prompt_hash": prompt_hash,
            "granularity": normalized_granularity,
        },
    }
