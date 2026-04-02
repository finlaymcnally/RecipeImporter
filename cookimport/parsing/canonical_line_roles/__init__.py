from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cookimport.config.prediction_identity import (
    build_line_role_cache_identity_payload,
)
from cookimport.config.runtime_support import resolve_workspace_completion_quiescence_seconds
from cookimport.config.run_settings import (
    LINE_ROLE_PIPELINE_ROUTE_V2,
    RunSettings,
    normalize_line_role_pipeline_value,
)
from cookimport.core.progress_messages import format_stage_progress
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_ALLOWED_LABELS,
    normalize_freeform_label,
)
from cookimport.llm.canonical_line_role_prompt import (
    _render_label_code_legend,
    build_canonical_line_role_file_prompt,
    build_line_role_label_code_by_label,
    build_line_role_shared_contract_block,
)
from cookimport.llm.codex_exec_runner import (
    CodexExecLiveSnapshot,
    DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
    CodexExecRunResult,
    CodexExecRunner,
    CodexExecSupervisionDecision,
    SubprocessCodexExecRunner,
    WorkspaceCommandClassification,
    classify_taskfile_worker_command,
    detect_taskfile_worker_boundary_violation,
    format_watchdog_command_reason_detail,
    format_watchdog_command_loop_reason_detail,
    is_single_file_workspace_command_drift_policy,
    should_terminate_workspace_command_loop,
    summarize_direct_telemetry_rows,
)
from cookimport.llm.codex_farm_runner import (
    CodexFarmRunnerError,
    resolve_codex_farm_output_schema_path,
)
from cookimport.llm.worker_hint_sidecars import (
    preview_text,
    write_worker_hint_markdown,
)
from cookimport.llm.phase_worker_runtime import (
    PhaseManifestV1,
    ShardManifestEntryV1,
    ShardProposalV1,
    TaskManifestEntryV1,
    WorkerAssignmentV1,
    WorkerExecutionReportV1,
    resolve_phase_worker_count,
)
from cookimport.llm.shard_prompt_targets import (
    partition_contiguous_items,
    resolve_shard_count,
)
from cookimport.parsing.recipe_block_atomizer import (
    AtomicLineCandidate,
    build_atomic_index_lookup,
    get_atomic_line_neighbor_texts,
)
from cookimport.parsing.line_role_workspace_tools import (
    build_line_role_workspace_scaffold,
    build_line_role_workspace_shard_metadata,
    validate_line_role_output_payload,
)
from .contracts import (
    CANONICAL_LINE_ROLE_ALLOWED_LABELS,
    CanonicalLineRolePrediction,
    RECIPE_LOCAL_LINE_ROLE_LABELS,
    _normalize_exclusion_reason,
    _unique_string_list,
)
from .artifacts import (
    _PromptArtifactState,
    _line_role_asdict,
    _relative_runtime_path,
    _write_optional_runtime_text,
    _write_runtime_json,
    _write_runtime_jsonl,
    _write_worker_debug_input,
)
from .prompt_inputs import (
    serialize_line_role_debug_context_row,
    serialize_line_role_debug_context_row_from_mapping,
    serialize_line_role_file_row,
    serialize_line_role_model_context_row,
    serialize_line_role_model_row,
)

_PROSE_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'/-]*")
_QUANTITY_LINE_RE = re.compile(
    r"^\s*(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?(?:\s*(?:to|-)\s*\d+(?:\.\d+)?)?)\s+",
    re.IGNORECASE,
)
_INGREDIENT_UNIT_RE = re.compile(
    r"\b(cups?|tbsp|tablespoons?|tsp|teaspoons?|oz|ounces?|lb|lbs|pounds?|"
    r"g|kg|ml|l|cloves?|sticks?|cans?|pinch)\b",
    re.IGNORECASE,
)
_INGREDIENT_NAME_FRAGMENT_RE = re.compile(
    r"^[A-Za-z][A-Za-z'/-]*(?:\s+[A-Za-z][A-Za-z'/-]*){0,2}$"
)
_INGREDIENT_FRAGMENT_STOPWORDS = {
    "and",
    "at",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "step",
    "the",
    "to",
    "with",
}
_STRICT_JSON_WATCHDOG_POLICY = "strict_json_no_tools_v1"
_LINE_ROLE_COHORT_WATCHDOG_MIN_COMPLETED_SHARDS = 3
_LINE_ROLE_COHORT_WATCHDOG_MIN_ELAPSED_MS = 1_000
_LINE_ROLE_COHORT_WATCHDOG_MEDIAN_FACTOR = 4.0
_LINE_ROLE_COHORT_WATCHDOG_MAX_EXAMPLES = 2
_LINE_ROLE_WORKSPACE_MAX_COMMAND_COUNT = 16
_LINE_ROLE_WORKSPACE_MAX_REPEAT_COUNT = 4
_LINE_ROLE_WORKSPACE_OUTPUT_STABLE_PASSES = 2
_LINE_ROLE_WORKSPACE_COMPLETION_QUIESCENCE_SECONDS = (
    resolve_workspace_completion_quiescence_seconds()
)
_LINE_ROLE_FINAL_MESSAGE_MISSING_OUTPUT_GRACE_SECONDS = (
    resolve_workspace_completion_quiescence_seconds()
)
_LINE_ROLE_PATHOLOGY_MIN_ROWS = 4
_LINE_ROLE_PATHOLOGY_MIN_BASELINE_DISTINCT_LABELS = 3
_LINE_ROLE_PATHOLOGY_NEAR_UNIFORM_MIN_ROWS = 8
_TITLE_CONNECTOR_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
_HOW_TO_TITLE_PREFIX_RE = re.compile(r"^\s*how to\b", re.IGNORECASE)
_TIME_PREFIX_RE = re.compile(
    r"^\s*(?:prep time|cook time|total time|active time|ready in)\b",
    re.IGNORECASE,
)
_INSTRUCTION_VERB_RE = re.compile(
    r"^\s*(?:add|bake|beat|blend|boil|braise|bring|combine|cook|cool|cover|drain|"
    r"fold|grill|heat|mix|place|pour|quarter|reduce|remove|roast|season|serve|"
    r"simmer|slice|stir|toast|toss|transfer|whisk)\b",
    re.IGNORECASE,
)
_RECIPE_ACTION_CUE_RE = re.compile(
    r"\b(?:add|allow|arrange|bake|beat|blend|boil|braise|bring|chop|clean|coat|"
    r"combine|cook|cool|cover|crush|cut|deglaze|drain|dress|ferment|fill|flip|"
    r"fold|garnish|grill|hang|heat|knead|mix|place|plate|poach|pour|preheat|"
    r"reduce|remove|rinse|roast|sear|season|serve|set|simmer|slice|soak|stir|"
    r"strain|tie|toast|transfer|trim|wash|whisk)\b",
    re.IGNORECASE,
)
_INSTRUCTION_LEADIN_RE = re.compile(
    r"^\s*(?:in|on|with|while|once|when|after|before)\b",
    re.IGNORECASE,
)
_NOTE_PREFIX_RE = re.compile(r"^\s*notes?\s*:\s*", re.IGNORECASE)
_NUMBERED_STEP_RE = re.compile(r"^\s*(?:step\s*)?\d{1,2}[.)]\s+", re.IGNORECASE)
_YIELD_PREFIX_RE = re.compile(
    r"^\s*(?:makes|serves?|servings|yields?)\b",
    re.IGNORECASE,
)
_HOWTO_PREFIX_RE = re.compile(
    r"^\s*(?:to make|to serve|for serving|for garnish|for the)\b",
    re.IGNORECASE,
)
_STORAGE_NOTE_PREFIX_RE = re.compile(
    r"^\s*(?:cover and )?(?:refrigerate|freeze|store)\s+leftover(?:s|\b| dressing\b)",
    re.IGNORECASE,
)
_SERVING_NOTE_PREFIX_RE = re.compile(
    r"^\s*(?:ideal for|serve with)\b",
    re.IGNORECASE,
)
_VARIANT_GENERIC_HEADINGS = {"variation", "variations"}
_VARIANT_EXPLICIT_HEADINGS = {*_VARIANT_GENERIC_HEADINGS, "for a crowd"}
_VARIANT_RECIPE_SUFFIXES = (
    "OMELET",
    "HASH",
    "PANCAKES",
    "WAFFLES",
    "BISCUITS",
    "SCONES",
    "SOUP",
)
_EDITORIAL_NOTE_PREFIXES = (
    "bottom line",
    "the best part",
    "for a long time",
    "your soup is essentially done",
    "whatever liquid you choose",
)
_NON_RECIPE_PROSE_PREFIXES = (
    "to the ",
    "and to ",
    "preface",
    "introduction",
    "contents",
    "acknowledgments",
    "index",
    "conversions",
)
_FRONT_MATTER_NAVIGATION_HEADINGS = {
    "about the author",
    "acknowledgments",
    "acknowledgements",
    "contents",
    "epigraph",
    "foreword",
    "index",
    "introduction",
    "preface",
    "recipes",
    "table of contents",
}
_RECIPE_NOTE_ADVISORY_CUE_RE = re.compile(
    r"\b(?:be sure|don't|do not|i don't recommend|i like to|i prefer|"
    r"i recommend|i use|it's important|make sure|remember|the key is|"
    r"you can|you don't need|you should)\b",
    re.IGNORECASE,
)
_RECIPE_CONTEXT_RE = re.compile(
    r"\b(?:egg|eggs|omelet|omelette|soup|chicken|stock|broth|sauce|gravy|"
    r"hollandaise|poach|boil|fry|roast|braise|biscuits?|scones?|pancakes?|"
    r"waffles?|hash|onion|garlic|tomato|cheese|pasta|bean|mushroom|broccoli|"
    r"potato|anchov|parsley|bacon|ham|buttermilk|yolk|rice|noodles)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_RE = re.compile(
    r"\b(?:i|i'm|i'd|i've|my|me|we|we're|our)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_SINGULAR_RE = re.compile(
    r"\b(?:i|i'm|i'd|i've|my|me)\b",
    re.IGNORECASE,
)
_SECOND_PERSON_RE = re.compile(
    r"\b(?:you|you'd|you'll|you're|you've|your)\b",
    re.IGNORECASE,
)
_EXPLICIT_KNOWLEDGE_CUE_RE = re.compile(
    r"\b(?:conduct heat|heat transfer|this means|which means|in other words|"
    r"for example|for instance|as a rule|in general|rule of thumb|ratio|"
    r"temperature|emulsion)\b",
    re.IGNORECASE,
)
_KNOWLEDGE_DOMAIN_CUE_RE = re.compile(
    r"\b(?:acid|aroma|aromas|bitter|bitterness|bland|boil|boiling|braise|"
    r"braising|brown|browning|chemistry|conduct|conduction|crisp|crust|"
    r"emulsion|evaporate|evaporation|fat|flavor|flavors|heat|iodized|"
    r"kosher salt|method|methods|mineral|minerals|moisture|protein|proteins|"
    r"ratio|salt|salinity|simmer|starch|starches|sweetness|taste|technique|"
    r"techniques|texture|textures|vinegar|water)\b",
    re.IGNORECASE,
)
_KNOWLEDGE_EXPLANATION_CUE_RE = re.compile(
    r"\b(?:affect|affects|balance|balances|because|control|controls|"
    r"decrease|decreases|determine|determines|distinguish|distinguishes|"
    r"emphasize|emphasizes|enhance|enhances|explained by|explains|"
    r"guide|guided|guides|highlight|highlights|improve|improves|increase|"
    r"increases|means|modify|modifies|pattern|patterns|reduce|reduces|"
    r"relationship|role|secondary effect|this is why|without|why)\b",
    re.IGNORECASE,
)
_PEDAGOGICAL_KNOWLEDGE_CUE_RE = re.compile(
    r"\b(?:better cook|cook every day|fundamental|fundamentals|lesson|lessons|"
    r"master|mastering|method|methods|principle|principles|teach|teaches|"
    r"teaching|technique|techniques)\b",
    re.IGNORECASE,
)
_PEDAGOGICAL_KNOWLEDGE_HEADING_RE = re.compile(
    r"^(?:how to use\b|using recipes\b|kitchen basics\b|cooking lessons\b|"
    r"what to cook\b)$",
    re.IGNORECASE,
)
_NAVIGATION_SECTION_RE = re.compile(
    r"^(?:part|chapter)\s+(?:[a-z0-9ivxlcdm]+)\b",
    re.IGNORECASE,
)
_KNOWLEDGE_HEADING_FORM_RE = re.compile(
    r"^(?:what is\b|how .+ works\b|using\b|.+ and flavor\b)$",
    re.IGNORECASE,
)
_BOOK_FRAMING_EXHORTATION_CUE_RE = re.compile(
    r"\b(?:better cook|cook every day|discover|discoveries|guide|improve "
    r"anything you eat|initial leap of faith|journey|keep reading|learn|"
    r"master(?:ing)?|pay attention|teach(?:es|ing)?|taste,? not price|"
    r"the only way to learn|you've scored)\b",
    re.IGNORECASE,
)
_RECIPEISH_OUTSIDE_SPAN_LABELS = {
    "RECIPE_TITLE",
    "RECIPE_VARIANT",
    "HOWTO_SECTION",
    "INSTRUCTION_LINE",
    "INGREDIENT_LINE",
}
_YIELD_COUNT_HINT_RE = re.compile(
    r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"about|approximately|approx\.?|around|up to|at least|at most)\b",
    re.IGNORECASE,
)
_LINE_ROLE_CODEX_MAX_INFLIGHT_DEFAULT = 4
_LINE_ROLE_CODEX_MAX_INFLIGHT_ENV = "COOKIMPORT_LINE_ROLE_CODEX_MAX_INFLIGHT"
_LINE_ROLE_CACHE_SCHEMA_VERSION = "canonical_line_role_cache.v7"
_LINE_ROLE_CACHE_ROOT_ENV = "COOKIMPORT_LINE_ROLE_CACHE_ROOT"
_LINE_ROLE_PROGRESS_MAX_UPDATES = 100
_LINE_ROLE_CODEX_FARM_PIPELINE_ID = "line-role.canonical.v1"
_LINE_ROLE_CODEX_EXEC_DEFAULT_CMD = "codex exec"
_LINE_ROLE_DIRECT_RUNTIME_ARTIFACT_SCHEMA = "line_role.direct_worker_runtime.v1"
_CODEX_EXECUTABLES = {"codex", "codex.exe", "codex2", "codex2.exe"}
LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT = 240
_LINE_ROLE_MODEL_PAYLOAD_VERSION = 2
_PAGE_FURNITURE_RE = re.compile(r"^\s*(?:\d{1,4}|[ivxlcdm]{1,8})\s*$", re.IGNORECASE)
_COPYRIGHT_LEGAL_RE = re.compile(
    r"\b(?:copyright|all rights reserved|used by permission|no part of this)\b",
    re.IGNORECASE,
)
_PUBLISHING_METADATA_RE = re.compile(
    r"\b(?:isbn(?:-1[03])?|library of congress|cataloging-in-publication|published by|printed in)\b",
    re.IGNORECASE,
)
_PUBLISHER_PROMO_RE = re.compile(
    r"\b(?:download(?:ing|ed)?\s+(?:this|the)\s+ebook|mailing list|sign up|"
    r"register this ebook|recommended reads|exclusive offers|new releases|"
    r"terms and conditions|subscriber|subscribe|inbox|free ebook|click here)\b",
    re.IGNORECASE,
)
_ENDORSEMENT_BLURB_CUE_RE = re.compile(
    r"\b(?:a must for anyone wanting to be a better cook|book\b|guide to|"
    r"guide readers|guide to employing|wildly informative|fun illustrations|"
    r"beautiful storytelling|powerful art|joyful to read|new-generation culinary resource|"
    r"perfect mixture|pitch-perfect combination|better cook)\b",
    re.IGNORECASE,
)
_FRONT_MATTER_EXCLUSION_HEADINGS = {
    "about the author",
    "acknowledgments",
    "acknowledgements",
    "dedication",
    "epigraph",
    "foreword",
    "introduction",
    "preface",
}


class LineRoleRepairFailureError(RuntimeError):
    """Raised when canonical line-role exits without a clean installed shard ledger."""


for _module_name in ("policy", "planning", "validation", "runtime"):
    _module = importlib.import_module(f"{__package__}.{_module_name}")
    globals().update(
        {
            name: value
            for name, value in vars(_module).items()
            if not name.startswith("__")
        }
    )
