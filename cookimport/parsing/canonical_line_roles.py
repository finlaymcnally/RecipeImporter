from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cookimport.config.prediction_identity import (
    build_line_role_cache_identity_payload,
)
from cookimport.config.run_settings import (
    LINE_ROLE_PIPELINE_SHARD_V1,
    RunSettings,
    normalize_line_role_pipeline_value,
)
from cookimport.core.progress_messages import format_stage_progress
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_ALLOWED_LABELS,
    FREEFORM_LABELS,
    normalize_freeform_label,
)
from cookimport.llm.canonical_line_role_prompt import (
    LineRolePromptFormat,
    _render_label_code_legend,
    build_canonical_line_role_file_prompt,
    build_line_role_label_code_by_label,
    serialize_line_role_model_row,
)
from cookimport.llm.codex_exec_runner import (
    CodexExecLiveSnapshot,
    DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
    CodexExecRunResult,
    CodexExecRunner,
    CodexExecSupervisionDecision,
    SubprocessCodexExecRunner,
    WorkspaceCommandClassification,
    classify_workspace_worker_command,
    detect_workspace_worker_boundary_violation,
    format_watchdog_command_reason_detail,
    format_watchdog_command_loop_reason_detail,
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
    LINE_ROLE_OUTPUT_CONTRACT_MARKDOWN,
    LINE_ROLE_VALID_OUTPUT_EXAMPLE_FILENAME,
    LINE_ROLE_VALID_OUTPUT_EXAMPLE_PAYLOAD,
    LINE_ROLE_WORKER_TOOL_FILENAME,
    build_line_role_scratch_draft_path,
    build_line_role_seed_output,
    build_line_role_workspace_task_metadata,
    render_line_role_worker_script,
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
_LINE_ROLE_TASK_TARGET_ROWS = 80
_LINE_ROLE_TASK_CONTEXT_OVERLAP_ROWS = 3
_LINE_ROLE_PATHOLOGY_MIN_ROWS = 4
_LINE_ROLE_PATHOLOGY_MIN_BASELINE_DISTINCT_LABELS = 3
_LINE_ROLE_PATHOLOGY_NEAR_UNIFORM_MIN_ROWS = 8
_LINE_ROLE_PACKET_EXAMPLE_FILES: tuple[tuple[str, str], ...] = (
    (
        "01-lesson-prose-vs-howto.md",
        "# Lesson prose vs recipe how-to\n\n"
        "- Keep lesson headings such as `Balancing Fat` or `WHAT IS ACID?` as `KNOWLEDGE` when nearby rows are explanatory prose.\n"
        "- Declarative lesson prose about reusable cooking rules, such as `Salt, Fat, Acid, and Heat were the four elements ...`, should stay `KNOWLEDGE` even when the narration uses `I` or `we`.\n"
        "- Upgrade a heading to `HOWTO_SECTION` only when immediate neighboring rows are recipe-local ingredients or method subsections.\n"
        "- A heading by itself is weak evidence.\n",
    ),
    (
        "02-memoir-vs-knowledge.md",
        "# Memoir vs knowledge\n\n"
        "- First-person narrative or autobiographical prose is usually `OTHER`.\n"
        "- Use `KNOWLEDGE` only when the prose is clearly teaching a reusable cooking idea.\n"
        "- Do not turn memoir into recipe structure.\n",
    ),
    (
        "03-recipe-internal-sections.md",
        "# Recipe-internal section headings\n\n"
        "- `FOR THE SAUCE`, `FOR SERVING`, or similar headings become `HOWTO_SECTION` only when the packet is clearly inside one recipe.\n"
        "- A full sentence beginning with `To make ...` or `To serve ...` is usually variant or procedural prose, not a subsection heading.\n"
        "- Front-matter or contents title lists such as `Winter: Roasted Radicchio and Roquefort` stay `OTHER` until nearby ingredient or instruction rows prove a live recipe.\n"
        "- Ingredient lines, yield lines, and imperative steps are strong recipe-local evidence.\n"
        "- Preserve structured recipe labels when those strong signals are present.\n",
    ),
    (
        "04-book-optional-howto.md",
        "# HOWTO_SECTION is book-optional\n\n"
        "- Some books legitimately use zero `HOWTO_SECTION` labels.\n"
        "- Do not invent subsection structure just because the label exists in the global taxonomy.\n"
        "- Prefer a conservative non-structural label unless the local packet shows immediate recipe-local support.\n",
    ),
)
_LINE_ROLE_OUTPUT_EXAMPLE_FILES: tuple[tuple[str, str], ...] = (
    (
        LINE_ROLE_VALID_OUTPUT_EXAMPLE_FILENAME,
        json.dumps(LINE_ROLE_VALID_OUTPUT_EXAMPLE_PAYLOAD, indent=2, sort_keys=True) + "\n",
    ),
)
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
    r"simmer|slice|stir|toss|transfer|whisk)\b",
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
_LINE_ROLE_CACHE_SCHEMA_VERSION = "canonical_line_role_cache.v6"
_LINE_ROLE_CACHE_ROOT_ENV = "COOKIMPORT_LINE_ROLE_CACHE_ROOT"
_LINE_ROLE_PROGRESS_MAX_UPDATES = 100
_LINE_ROLE_CODEX_FARM_PIPELINE_ID = "line-role.canonical.v1"
_LINE_ROLE_CODEX_EXEC_DEFAULT_CMD = "codex exec"
_LINE_ROLE_DIRECT_RUNTIME_ARTIFACT_SCHEMA = "line_role.direct_worker_runtime.v1"
_CODEX_EXECUTABLES = {"codex", "codex.exe", "codex2", "codex2.exe"}
LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT = 240
_LINE_ROLE_MODEL_PAYLOAD_VERSION = 1
_REVIEW_EXCLUSION_REASON_CODES = frozenset(
    {
        "navigation",
        "front_matter",
        "publishing_metadata",
        "copyright_legal",
        "endorsement",
        "page_furniture",
    }
)
_PAGE_FURNITURE_RE = re.compile(r"^\s*(?:\d{1,4}|[ivxlcdm]{1,8})\s*$", re.IGNORECASE)
_COPYRIGHT_LEGAL_RE = re.compile(
    r"\b(?:copyright|all rights reserved|used by permission|no part of this)\b",
    re.IGNORECASE,
)
_PUBLISHING_METADATA_RE = re.compile(
    r"\b(?:isbn(?:-1[03])?|library of congress|cataloging-in-publication|published by|printed in)\b",
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

class CanonicalLineRolePrediction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    recipe_id: str | None = None
    block_id: str
    block_index: int | None = None
    atomic_index: int
    text: str
    within_recipe_span: bool | None = None
    label: str
    decided_by: Literal["rule", "codex", "fallback"]
    reason_tags: list[str] = Field(default_factory=list)
    escalation_reasons: list[str] = Field(default_factory=list)
    review_exclusion_reason: str | None = None

    @model_validator(mode="after")
    def _normalize_metadata(self) -> "CanonicalLineRolePrediction":
        self.escalation_reasons = _unique_string_list(self.escalation_reasons)
        self.reason_tags = _unique_string_list(self.reason_tags)
        self.review_exclusion_reason = _normalize_review_exclusion_reason(
            self.review_exclusion_reason
        )
        return self


def _unique_string_list(values: Sequence[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        rendered = str(value or "").strip()
        if not rendered or rendered in seen:
            continue
        seen.add(rendered)
        output.append(rendered)
    return output


def _normalize_review_exclusion_reason(value: Any) -> str | None:
    rendered = str(value or "").strip().lower()
    if not rendered:
        return None
    if rendered not in _REVIEW_EXCLUSION_REASON_CODES:
        raise ValueError(f"unknown review exclusion reason: {rendered}")
    return rendered


def _prediction_has_reason_tag(
    prediction: CanonicalLineRolePrediction,
    fragment: str,
) -> bool:
    return any(fragment in str(tag) for tag in prediction.reason_tags)


def _is_within_recipe_span(candidate: AtomicLineCandidate | CanonicalLineRolePrediction) -> bool:
    return candidate.within_recipe_span is True


def _is_outside_recipe_span(candidate: AtomicLineCandidate | CanonicalLineRolePrediction) -> bool:
    return candidate.within_recipe_span is False


def _apply_prediction_decision_metadata(
    *,
    prediction: CanonicalLineRolePrediction,
    candidate: AtomicLineCandidate,
    by_atomic_index: dict[int, AtomicLineCandidate],
    baseline_prediction: CanonicalLineRolePrediction | None = None,
) -> CanonicalLineRolePrediction:
    label = str(prediction.label or "OTHER")

    reasons: list[str] = []
    if _prediction_has_reason_tag(prediction, "deterministic_unresolved") or _prediction_has_reason_tag(
        prediction,
        "deterministic_unavailable",
    ):
        reasons.append("deterministic_unresolved")
    if prediction.decided_by == "fallback":
        reasons.append("fallback_decision")
    if _is_outside_recipe_span(candidate) and label in _RECIPEISH_OUTSIDE_SPAN_LABELS:
        reasons.append("outside_span_structured_label")
    if baseline_prediction is not None:
        baseline_label = str(baseline_prediction.label or "OTHER")
        if (
            prediction.decided_by == "codex"
            and baseline_label
            and baseline_label != label
        ):
            reasons.append("codex_disagreed_with_rule")
    if _prediction_has_reason_tag(prediction, "sanitized_"):
        reasons.append("sanitized_label_adjustment")
    if prediction.review_exclusion_reason is not None:
        reasons.append("knowledge_review_excluded")

    payload = prediction.model_dump(mode="python")
    payload["escalation_reasons"] = _unique_string_list(reasons)
    return CanonicalLineRolePrediction.model_validate(payload)


@dataclass(frozen=True)
class _LineRoleShardPlan:
    phase_key: str
    phase_label: str
    runtime_pipeline_id: str
    prompt_stem: str
    shard_id: str
    prompt_index: int
    candidates: tuple[AtomicLineCandidate, ...]
    baseline_predictions: tuple[CanonicalLineRolePrediction, ...]
    debug_input_payload: dict[str, Any]
    manifest_entry: ShardManifestEntryV1


@dataclass(frozen=True)
class _LineRoleTaskPlan:
    task_id: str
    parent_shard_id: str
    manifest_entry: ShardManifestEntryV1
    debug_input_payload: dict[str, Any]


@dataclass(frozen=True)
class _LineRolePhaseRuntimeResult:
    phase_key: str
    phase_label: str
    shard_plans: tuple[_LineRoleShardPlan, ...]
    worker_reports: tuple[WorkerExecutionReportV1, ...]
    runner_results_by_shard_id: dict[str, dict[str, Any]]
    response_payloads_by_shard_id: dict[str, dict[str, Any]]
    proposal_metadata_by_shard_id: dict[str, dict[str, Any]]
    invalid_shard_count: int
    missing_output_shard_count: int
    runtime_root: Path | None


@dataclass(frozen=True)
class _LineRoleRuntimeResult:
    predictions_by_atomic_index: dict[int, CanonicalLineRolePrediction]
    phase_results: tuple[_LineRolePhaseRuntimeResult, ...]


@dataclass(frozen=True)
class _DirectLineRoleWorkerResult:
    report: WorkerExecutionReportV1
    proposals: tuple[ShardProposalV1, ...]
    failures: tuple[dict[str, Any], ...]
    stage_rows: tuple[dict[str, Any], ...]
    task_status_rows: tuple[dict[str, Any], ...]
    runner_results_by_shard_id: dict[str, dict[str, Any]]


@dataclass(slots=True)
class _LineRoleCohortWatchdogState:
    durations_ms: list[int] = field(default_factory=list)
    successful_examples: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            durations_ms = list(self.durations_ms)
            examples = [
                dict(example_payload)
                for example_payload in self.successful_examples[-_LINE_ROLE_COHORT_WATCHDOG_MAX_EXAMPLES :]
            ]
        median_duration_ms = (
            int(statistics.median(durations_ms))
            if durations_ms
            else None
        )
        return {
            "completed_successful_shards": len(durations_ms),
            "median_duration_ms": median_duration_ms,
            "successful_examples": examples,
        }

    def record_validated_result(
        self,
        *,
        duration_ms: int | None,
        example_payload: Mapping[str, Any] | None,
    ) -> None:
        normalized_duration_ms = int(duration_ms or 0)
        if normalized_duration_ms <= 0:
            return
        with self.lock:
            self.durations_ms.append(normalized_duration_ms)
            if isinstance(example_payload, Mapping):
                self.successful_examples.append(dict(example_payload))
                self.successful_examples = self.successful_examples[
                    -_LINE_ROLE_COHORT_WATCHDOG_MAX_EXAMPLES :
                ]


def _label_atomic_lines_internal(
    candidates: Sequence[AtomicLineCandidate],
    settings: RunSettings,
    *,
    artifact_root: Path | None = None,
    source_hash: str | None = None,
    live_llm_allowed: bool = False,
    cache_root: Path | None = None,
    codex_timeout_seconds: int = 600,
    codex_batch_size: int = LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT,
    codex_max_inflight: int | None = None,
    codex_cmd: str | None = None,
    codex_runner: CodexExecRunner | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[list[CanonicalLineRolePrediction], list[CanonicalLineRolePrediction]]:
    ordered = list(candidates)
    if not ordered:
        return [], []
    deterministic_total = len(ordered)
    deterministic_interval = _line_role_progress_interval(deterministic_total)
    _notify_line_role_progress(
        progress_callback=progress_callback,
        completed_tasks=0,
        total_tasks=deterministic_total,
    )
    by_atomic_index = {int(candidate.atomic_index): candidate for candidate in ordered}
    mode = _line_role_pipeline_name(settings)
    cache_path: Path | None = None
    if mode == LINE_ROLE_PIPELINE_SHARD_V1:
        cache_path = _resolve_line_role_cache_path(
            source_hash=source_hash,
            settings=settings,
            ordered_candidates=ordered,
            artifact_root=artifact_root,
            cache_root=cache_root,
            codex_timeout_seconds=codex_timeout_seconds,
            codex_batch_size=codex_batch_size,
        )
        if cache_path is not None:
            cached_predictions = _load_cached_predictions(
                cache_path=cache_path,
                expected_candidates=ordered,
            )
            if cached_predictions is not None:
                return cached_predictions

    predictions: dict[int, CanonicalLineRolePrediction] = {}
    deterministic_baseline: dict[int, CanonicalLineRolePrediction] = {}
    for candidate_index, candidate in enumerate(ordered, start=1):
        label, tags = _deterministic_label(
            candidate,
            by_atomic_index=by_atomic_index,
        )
        if label is None:
            baseline_prediction = _fallback_prediction(
                candidate,
                reason="deterministic_unresolved",
                by_atomic_index=by_atomic_index,
            )
        else:
            baseline_prediction = CanonicalLineRolePrediction(
                recipe_id=candidate.recipe_id,
                block_id=str(candidate.block_id),
                block_index=int(candidate.block_index),
                atomic_index=int(candidate.atomic_index),
                text=str(candidate.text),
                within_recipe_span=candidate.within_recipe_span,
                label=label,
                decided_by="rule",
                reason_tags=tags,
            )
        baseline_prediction = _apply_prediction_decision_metadata(
            prediction=baseline_prediction,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
        deterministic_baseline[candidate.atomic_index] = baseline_prediction
        if mode != LINE_ROLE_PIPELINE_SHARD_V1:
            predictions[candidate.atomic_index] = baseline_prediction
        if (
            candidate_index == deterministic_total
            or candidate_index % deterministic_interval == 0
        ):
            _notify_line_role_progress(
                progress_callback=progress_callback,
                completed_tasks=candidate_index,
                total_tasks=deterministic_total,
            )

    codex_targets = ordered if mode == LINE_ROLE_PIPELINE_SHARD_V1 else []
    runtime_result: _LineRoleRuntimeResult | None = None
    if codex_targets:
        runtime_result = _run_line_role_shard_runtime(
            ordered_candidates=codex_targets,
            deterministic_baseline=deterministic_baseline,
            settings=settings,
            artifact_root=artifact_root,
            live_llm_allowed=live_llm_allowed,
            codex_timeout_seconds=codex_timeout_seconds,
            codex_batch_size=codex_batch_size,
            codex_max_inflight=codex_max_inflight,
            codex_cmd=codex_cmd,
            codex_runner=codex_runner,
            progress_callback=progress_callback,
        )
        predictions.update(runtime_result.predictions_by_atomic_index)

    for candidate in ordered:
        if candidate.atomic_index not in predictions:
            predictions[candidate.atomic_index] = deterministic_baseline[
                candidate.atomic_index
            ]

    sanitized_by_index: dict[int, CanonicalLineRolePrediction] = {}
    sanitized_baseline_by_index: dict[int, CanonicalLineRolePrediction] = {}
    for candidate in ordered:
        current = predictions[candidate.atomic_index]
        baseline = deterministic_baseline[candidate.atomic_index]
        sanitized_baseline = _sanitize_prediction(
            prediction=baseline,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
        sanitized_current = _sanitize_prediction(
            prediction=current,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
        sanitized_baseline = _apply_prediction_decision_metadata(
            prediction=sanitized_baseline,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
        sanitized_current = _apply_prediction_decision_metadata(
            prediction=sanitized_current,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
            baseline_prediction=sanitized_baseline,
        )
        sanitized_by_index[candidate.atomic_index] = sanitized_current
        sanitized_baseline_by_index[candidate.atomic_index] = sanitized_baseline
    if mode == LINE_ROLE_PIPELINE_SHARD_V1:
        _write_line_role_telemetry_summary(
            artifact_root=artifact_root,
            runtime_result=runtime_result,
        )
    sanitized = [sanitized_by_index[candidate.atomic_index] for candidate in ordered]
    sanitized_baseline = [
        sanitized_baseline_by_index[candidate.atomic_index] for candidate in ordered
    ]
    _write_cached_predictions(
        cache_path=cache_path,
        predictions=sanitized,
        baseline_predictions=sanitized_baseline,
    )
    return sanitized, sanitized_baseline


def label_atomic_lines(
    candidates: Sequence[AtomicLineCandidate],
    settings: RunSettings,
    *,
    artifact_root: Path | None = None,
    source_hash: str | None = None,
    live_llm_allowed: bool = False,
    cache_root: Path | None = None,
    codex_timeout_seconds: int = 600,
    codex_batch_size: int = LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT,
    codex_max_inflight: int | None = None,
    codex_cmd: str | None = None,
    codex_runner: CodexExecRunner | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> list[CanonicalLineRolePrediction]:
    predictions, _baseline = _label_atomic_lines_internal(
        candidates,
        settings,
        artifact_root=artifact_root,
        source_hash=source_hash,
        live_llm_allowed=live_llm_allowed,
        cache_root=cache_root,
        codex_timeout_seconds=codex_timeout_seconds,
        codex_batch_size=codex_batch_size,
        codex_max_inflight=codex_max_inflight,
        codex_cmd=codex_cmd,
        codex_runner=codex_runner,
        progress_callback=progress_callback,
    )
    return predictions


def label_atomic_lines_with_baseline(
    candidates: Sequence[AtomicLineCandidate],
    settings: RunSettings,
    *,
    artifact_root: Path | None = None,
    source_hash: str | None = None,
    live_llm_allowed: bool = False,
    cache_root: Path | None = None,
    codex_timeout_seconds: int = 600,
    codex_batch_size: int = LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT,
    codex_max_inflight: int | None = None,
    codex_cmd: str | None = None,
    codex_runner: CodexExecRunner | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[list[CanonicalLineRolePrediction], list[CanonicalLineRolePrediction]]:
    return _label_atomic_lines_internal(
        candidates,
        settings,
        artifact_root=artifact_root,
        source_hash=source_hash,
        live_llm_allowed=live_llm_allowed,
        cache_root=cache_root,
        codex_timeout_seconds=codex_timeout_seconds,
        codex_batch_size=codex_batch_size,
        codex_max_inflight=codex_max_inflight,
        codex_cmd=codex_cmd,
        codex_runner=codex_runner,
        progress_callback=progress_callback,
    )


def _build_line_role_deterministic_baseline(
    *,
    ordered_candidates: Sequence[AtomicLineCandidate],
) -> dict[int, CanonicalLineRolePrediction]:
    by_atomic_index = {
        int(candidate.atomic_index): candidate for candidate in ordered_candidates
    }
    baseline: dict[int, CanonicalLineRolePrediction] = {}
    for candidate in ordered_candidates:
        label, tags = _deterministic_label(
            candidate,
            by_atomic_index=by_atomic_index,
        )
        if label is None:
            prediction = _fallback_prediction(
                candidate,
                reason="deterministic_unresolved",
                by_atomic_index=by_atomic_index,
            )
        else:
            prediction = CanonicalLineRolePrediction(
                recipe_id=candidate.recipe_id,
                block_id=str(candidate.block_id),
                block_index=int(candidate.block_index),
                atomic_index=int(candidate.atomic_index),
                text=str(candidate.text),
                within_recipe_span=candidate.within_recipe_span,
                label=label,
                decided_by="rule",
                reason_tags=list(tags),
            )
        baseline[int(candidate.atomic_index)] = _apply_prediction_decision_metadata(
            prediction=prediction,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
    return baseline


def serialize_line_role_file_row(
    *,
    candidate: AtomicLineCandidate,
    deterministic_label: str,
    escalation_reasons: Sequence[str],
) -> dict[str, Any]:
    return {
        "atomic_index": int(candidate.atomic_index),
        "block_index": int(candidate.block_index),
        "block_id": str(candidate.block_id),
        "recipe_id": candidate.recipe_id,
        "within_recipe_span": candidate.within_recipe_span,
        "deterministic_label": str(deterministic_label or "OTHER"),
        "rule_tags": list(candidate.rule_tags),
        "escalation_reasons": list(escalation_reasons),
        "current_line": str(candidate.text),
    }


def serialize_line_role_debug_context_row(
    *,
    candidate: AtomicLineCandidate,
) -> dict[str, Any]:
    return {
        "atomic_index": int(candidate.atomic_index),
        "current_line": str(candidate.text),
    }


def serialize_line_role_debug_context_row_from_mapping(
    row: Mapping[str, Any],
) -> dict[str, Any] | None:
    try:
        atomic_index = int(row.get("atomic_index"))
    except (AttributeError, TypeError, ValueError):
        return None
    return {
        "atomic_index": atomic_index,
        "current_line": str(row.get("current_line") or ""),
    }


def serialize_line_role_model_context_row(
    *,
    candidate: AtomicLineCandidate,
) -> list[Any]:
    return [
        int(candidate.atomic_index),
        str(candidate.text),
    ]


def build_line_role_debug_input_payload(
    *,
    shard_id: str,
    candidates: Sequence[AtomicLineCandidate],
    deterministic_baseline: Mapping[int, CanonicalLineRolePrediction],
    book_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [
        serialize_line_role_file_row(
            candidate=candidate,
            deterministic_label=str(
                deterministic_baseline[int(candidate.atomic_index)].label
                or "OTHER"
            ),
            escalation_reasons=deterministic_baseline[
                int(candidate.atomic_index)
            ].escalation_reasons,
        )
        for candidate in candidates
    ]
    packet_context = _build_line_role_packet_context(
        rows=rows,
        book_context=book_context,
    )
    return {
        "shard_id": shard_id,
        "phase_key": "line_role",
        **packet_context,
        "rows": rows,
    }


def build_line_role_model_input_payload(
    *,
    shard_id: str,
    candidates: Sequence[AtomicLineCandidate],
    deterministic_baseline: Mapping[int, CanonicalLineRolePrediction],
    debug_rows: Sequence[Mapping[str, Any]] | None = None,
    book_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    label_code_by_label = build_line_role_label_code_by_label(FREEFORM_LABELS)
    packet_context = _build_line_role_packet_context(
        rows=debug_rows or (),
        book_context=book_context,
    )
    return {
        "v": _LINE_ROLE_MODEL_PAYLOAD_VERSION,
        "shard_id": shard_id,
        **packet_context,
        "rows": [
            serialize_line_role_model_row(
                atomic_index=int(candidate.atomic_index),
                deterministic_label=str(
                    deterministic_baseline[int(candidate.atomic_index)].label
                    or "OTHER"
                ),
                current_line=str(candidate.text),
                label_code_by_label=label_code_by_label,
            )
            for candidate in candidates
        ],
    }


def _build_line_role_packet_context(
    *,
    rows: Sequence[Mapping[str, Any]],
    book_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    packet_mode, context_confidence = _classify_line_role_packet_mode(rows=rows)
    resolved_book_context = dict(book_context or {})
    return {
        "packet_mode": packet_mode,
        "context_confidence": context_confidence,
        "packet_summary": _line_role_packet_summary(packet_mode=packet_mode),
        "default_posture": _line_role_default_posture(packet_mode=packet_mode),
        "strong_signals": _line_role_strong_signals(packet_mode=packet_mode),
        "weak_signals": _line_role_weak_signals(),
        "flip_policy": _line_role_flip_policy(
            packet_mode=packet_mode,
            book_context=resolved_book_context,
        ),
        "example_files": _line_role_example_files(packet_mode=packet_mode),
        "howto_section_availability": str(
            resolved_book_context.get("howto_section_availability")
            or "absent_or_unproven"
        ),
        "howto_section_evidence_count": int(
            resolved_book_context.get("howto_section_evidence_count") or 0
        ),
        "howto_section_policy": str(
            resolved_book_context.get("howto_section_policy")
            or "This book may legitimately use zero `HOWTO_SECTION` labels."
        ),
    }


def _classify_line_role_packet_mode(
    *,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    label_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    row_count = 0
    span_inside = 0
    span_outside = 0
    first_person_count = 0
    recipe_structure_count = 0
    recipe_signal_row_count = 0
    ingredient_signal_row_count = 0
    instruction_signal_row_count = 0
    note_like_count = 0
    front_matter_heading_count = 0
    navigation_entry_count = 0
    prose_line_count = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        row_count += 1
        label = str(row.get("deterministic_label") or "OTHER").strip() or "OTHER"
        label_counts[label] = label_counts.get(label, 0) + 1
        within_recipe_span = row.get("within_recipe_span")
        if within_recipe_span is True:
            span_inside += 1
        elif within_recipe_span is False:
            span_outside += 1
        current_line = str(row.get("current_line") or "")
        if _FIRST_PERSON_RE.search(current_line):
            first_person_count += 1
        if _looks_prose(current_line):
            prose_line_count += 1
        row_tags = {
            str(tag).strip()
            for tag in (row.get("rule_tags") or ())
            if str(tag).strip()
        }
        for tag in row_tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        if label in {
            "RECIPE_TITLE",
            "RECIPE_VARIANT",
            "YIELD_LINE",
            "TIME_LINE",
            "INGREDIENT_LINE",
            "INSTRUCTION_LINE",
            "HOWTO_SECTION",
        }:
            recipe_structure_count += 1
        if label == "RECIPE_NOTES" or "note_like_prose" in row_tags:
            note_like_count += 1
        ingredient_signal = label == "INGREDIENT_LINE" or "ingredient_like" in row_tags
        instruction_signal = label == "INSTRUCTION_LINE" or "instruction_like" in row_tags
        recipe_metadata_signal = label in {"YIELD_LINE", "TIME_LINE"}
        if ingredient_signal:
            ingredient_signal_row_count += 1
        if instruction_signal:
            instruction_signal_row_count += 1
        if ingredient_signal or instruction_signal or recipe_metadata_signal:
            recipe_signal_row_count += 1
        if _looks_front_matter_navigation_heading(current_line):
            front_matter_heading_count += 1
        if _looks_navigation_title_list_entry(current_line):
            navigation_entry_count += 1

    knowledge_count = label_counts.get("KNOWLEDGE", 0)
    other_count = label_counts.get("OTHER", 0)
    title_like_count = tag_counts.get("title_like", 0)
    explicit_prose_count = tag_counts.get("explicit_prose", 0)
    span_unknown = max(0, row_count - span_inside - span_outside)
    all_span_status_unknown = row_count > 0 and span_unknown == row_count
    contents_navigation_packet = span_inside == 0 and (
        (
            front_matter_heading_count >= 2
            and recipe_signal_row_count <= max(10, row_count // 8)
        )
        or (
            all_span_status_unknown
            and navigation_entry_count >= max(6, row_count // 4)
            and recipe_signal_row_count <= max(10, row_count // 8)
            and prose_line_count <= max(4, row_count // 6)
        )
    )
    strong_unknown_recipe_body = (
        all_span_status_unknown
        and ingredient_signal_row_count >= 2
        and instruction_signal_row_count >= 2
        and recipe_signal_row_count >= 5
        and recipe_structure_count >= 4
        and navigation_entry_count < max(5, row_count // 5)
    )

    if contents_navigation_packet:
        confidence = (
            "high"
            if front_matter_heading_count >= 2
            or navigation_entry_count >= max(8, row_count // 3)
            else "medium"
        )
        return "front_matter_navigation", confidence
    if recipe_structure_count >= 2 and (span_inside > 0 or strong_unknown_recipe_body):
        if note_like_count > 0 and knowledge_count + other_count > 0:
            return "recipe_adjacent_notes", "medium"
        confidence = (
            "high"
            if ingredient_signal_row_count + instruction_signal_row_count >= 4
            else "medium"
        )
        return "recipe_body", confidence
    if first_person_count > 0 and recipe_structure_count == 0 and other_count >= max(1, knowledge_count):
        confidence = "high" if other_count >= 2 or first_person_count >= 2 else "medium"
        return "memoir_front_matter", confidence
    if knowledge_count >= max(2, other_count) and recipe_structure_count <= 1 and (
        title_like_count > 0 or explicit_prose_count > 0
    ):
        confidence = "high" if knowledge_count >= 3 or title_like_count > 0 else "medium"
        return "lesson_prose", confidence
    if note_like_count > 0 and recipe_structure_count > 0:
        return "recipe_adjacent_notes", "medium"
    return "mixed_boundaries", "low"


def _line_role_packet_summary(*, packet_mode: str) -> str:
    summaries = {
        "front_matter_navigation": (
            "This packet reads like front matter, navigation, or table-of-contents material, "
            "not recipe-local structure."
        ),
        "recipe_body": (
            "This packet reads like recipe-local structure: ingredient lines, step lines, "
            "or recipe-internal headings dominate."
        ),
        "recipe_adjacent_notes": (
            "This packet mixes real recipe structure with nearby notes or explanatory prose."
        ),
        "lesson_prose": (
            "This packet reads like cookbook lesson prose: explanatory teaching around a topic, "
            "not recipe-local structure."
        ),
        "memoir_front_matter": (
            "This packet reads like memoir/front matter or narrative prose, not recipe-local structure."
        ),
        "mixed_boundaries": (
            "This packet is mixed: some rows look structural and some look like surrounding prose."
        ),
    }
    return summaries.get(packet_mode, summaries["mixed_boundaries"])


def _line_role_default_posture(*, packet_mode: str) -> str:
    postures = {
        "front_matter_navigation": (
            "Default to `OTHER` or `KNOWLEDGE`; treat contents lists, seasonal menus, and part/chapter headings as navigation until multiple adjacent rows form one concrete recipe component."
        ),
        "recipe_body": (
            "Preserve recipe-structure labels unless a row clearly reads as note text or explanatory prose."
        ),
        "recipe_adjacent_notes": (
            "Keep recipe-body rows structured, but treat surrounding prose conservatively."
        ),
        "lesson_prose": (
            "Default to `OTHER`; upgrade to `KNOWLEDGE` when a row teaches reusable cooking explanation/reference prose, even if it uses brief first-person framing. Only promote to recipe structure when immediate neighboring rows are clearly recipe-local."
        ),
        "memoir_front_matter": (
            "Default to `OTHER`; upgrade only if a row clearly teaches reusable cooking knowledge."
        ),
        "mixed_boundaries": (
            "Make the smallest safe correction and leave ambiguous rows near the deterministic seed."
        ),
    }
    return postures.get(packet_mode, postures["mixed_boundaries"])


def _line_role_strong_signals(*, packet_mode: str) -> list[str]:
    signals = {
        "front_matter_navigation": [
            "Contents/front-matter headings such as `CONTENTS`, `Foreword`, `Introduction`, or `PART ONE`.",
            "Dense lists of short title-like entries with little or no local ingredient/step flow.",
            "Seasonal or menu-style title lists are stronger evidence for navigation than for live recipe titles.",
        ],
        "recipe_body": [
            "Immediate ingredient lines, yield/time metadata, or imperative recipe steps.",
            "Recipe-internal headings such as `FOR THE SAUCE` with nearby structured rows.",
        ],
        "recipe_adjacent_notes": [
            "A real recipe body remains visible, but one or two note/prose rows interrupt it.",
            "Keep the structured cluster and isolate the explanatory rows instead of flattening everything.",
        ],
        "lesson_prose": [
            "A topic heading followed by explanatory prose about technique, science, or broad culinary guidance.",
            "Declarative lesson prose about reusable cooking rules can still be `KNOWLEDGE` even if it briefly uses `I` or `we`.",
            "Repeated `KNOWLEDGE` rows are a stronger signal than title casing alone.",
        ],
        "memoir_front_matter": [
            "First-person narrative, acknowledgments, dedication-style prose, or autobiographical sentences.",
            "Narrative voice is a stronger signal than a stray cooking verb.",
        ],
        "mixed_boundaries": [
            "Trust immediate neighboring rows more than one isolated heading or verb phrase.",
            "Prefer the smallest locally grounded correction.",
        ],
    }
    return list(signals.get(packet_mode, signals["mixed_boundaries"]))


def _line_role_weak_signals() -> list[str]:
    return [
        "Title casing or all caps by itself is weak evidence.",
        "A dish-like name inside a front-matter or contents list is weak evidence for `RECIPE_TITLE`.",
        "Generic verbs such as `use`, `choose`, `let`, or `remember` do not make prose an instruction line.",
        "Unknown recipe-span status is not permission to invent recipe structure.",
    ]


def _line_role_flip_policy(
    *,
    packet_mode: str,
    book_context: Mapping[str, Any] | None = None,
) -> list[str]:
    howto_availability = str(
        dict(book_context or {}).get("howto_section_availability")
        or "absent_or_unproven"
    )
    policy = [
        "Treat the deterministic label as a strong prior, not a neutral starting guess.",
        "Only flip a row when packet-local evidence is clearer than the seed label.",
        "A heading alone is weak evidence; promote to `HOWTO_SECTION` only with immediate recipe-local support.",
        "Generic advice or science explanations are `KNOWLEDGE`/`OTHER`, not `INSTRUCTION_LINE`.",
    ]
    if howto_availability == "absent_or_unproven":
        policy.append(
            "This book may legitimately use zero `HOWTO_SECTION` labels. Do not invent subsection structure without strong local recipe support."
        )
    elif howto_availability == "sparse":
        policy.append(
            "`HOWTO_SECTION` appears sparse in this book. Use it only when the heading has immediate component-level support."
        )
    else:
        policy.append(
            "`HOWTO_SECTION` is available in this book, but it still needs immediate recipe-local support in this packet."
        )
    if packet_mode == "lesson_prose":
        policy.append(
            "Lesson headings such as `Balancing Fat` or `WHAT IS ACID?` should stay `KNOWLEDGE` when surrounding rows are explanatory prose."
        )
        policy.append(
            "Do not flatten reusable cooking lesson prose to `OTHER` just because it includes brief first-person framing around a general rule."
        )
        policy.append(
            "Memoir, blurbs, endorsements, book-framing encouragement, and broad action-verb advice are usually `OTHER`, not `KNOWLEDGE`."
        )
    elif packet_mode == "front_matter_navigation":
        policy.append(
            "Do not over-structure recipe-name lists, part/chapter headings, or front matter blurbs into live recipe labels."
        )
        policy.append(
            "Contents-style runs like `Winter: ...`, `Spring: ...`, `Torn Croutons`, or `Red Wine Vinaigrette` stay `OTHER` until nearby rows prove one live recipe."
        )
    elif packet_mode == "memoir_front_matter":
        policy.append(
            "First-person narrative should stay `OTHER` unless the row clearly teaches a reusable cooking concept."
        )
    elif packet_mode == "recipe_body":
        policy.append(
            "When strong recipe-local structure is present, preserve ingredient/instruction labels unless a row clearly breaks pattern."
        )
    return policy


def _line_role_example_files(*, packet_mode: str) -> list[str]:
    packet_specific = {
        "front_matter_navigation": [
            "02-memoir-vs-knowledge.md",
            "01-lesson-prose-vs-howto.md",
            "04-book-optional-howto.md",
        ],
        "recipe_body": [
            "03-recipe-internal-sections.md",
            "01-lesson-prose-vs-howto.md",
            "04-book-optional-howto.md",
        ],
        "recipe_adjacent_notes": [
            "03-recipe-internal-sections.md",
            "02-memoir-vs-knowledge.md",
            "04-book-optional-howto.md",
        ],
        "lesson_prose": [
            "01-lesson-prose-vs-howto.md",
            "02-memoir-vs-knowledge.md",
            "04-book-optional-howto.md",
        ],
        "memoir_front_matter": [
            "02-memoir-vs-knowledge.md",
            "01-lesson-prose-vs-howto.md",
            "04-book-optional-howto.md",
        ],
        "mixed_boundaries": [
            "01-lesson-prose-vs-howto.md",
            "03-recipe-internal-sections.md",
            "04-book-optional-howto.md",
        ],
    }
    return list(packet_specific.get(packet_mode, packet_specific["mixed_boundaries"]))


def _looks_front_matter_navigation_heading(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered in _FRONT_MATTER_NAVIGATION_HEADINGS:
        return True
    if lowered.startswith("how to use this book"):
        return True
    return bool(_NAVIGATION_SECTION_RE.match(stripped))


def _looks_navigation_title_list_entry(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _looks_front_matter_navigation_heading(stripped):
        return True
    if (
        _NOTE_PREFIX_RE.match(stripped)
        or _YIELD_PREFIX_RE.match(stripped)
        or _TIME_PREFIX_RE.search(stripped)
        or _QUANTITY_LINE_RE.match(stripped)
        or _NUMBERED_STEP_RE.match(stripped)
        or stripped[-1:] in {".", "!", "?"}
    ):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if not words or len(words) > 8:
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        return False
    if ":" in stripped:
        return True
    if len(words) == 1:
        return words[0][:1].isupper()
    return _looks_recipe_title(stripped) or _looks_compact_heading(stripped)


def _looks_page_furniture(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    return _PAGE_FURNITURE_RE.match(stripped) is not None


def _looks_publishing_metadata(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    return _PUBLISHING_METADATA_RE.search(stripped) is not None


def _looks_copyright_legal(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    return _COPYRIGHT_LEGAL_RE.search(stripped) is not None


def _looks_front_matter_exclusion_heading(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered in _FRONT_MATTER_EXCLUSION_HEADINGS:
        return True
    return lowered.startswith("how to use this book")


def _looks_navigation_exclusion_candidate(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if _looks_table_of_contents_entry(text):
        return True
    if _looks_front_matter_navigation_heading(text) and not _looks_front_matter_exclusion_heading(
        text
    ):
        return True
    if by_atomic_index is None or not _looks_navigation_title_list_entry(text):
        return False
    navigation_like_neighbors = 0
    lesson_like_neighbors = 0
    for offset in (-2, -1, 1, 2):
        neighbor = by_atomic_index.get(int(candidate.atomic_index) + offset)
        if neighbor is None or _is_within_recipe_span(neighbor):
            continue
        neighbor_text = str(neighbor.text or "").strip()
        if (
            _looks_table_of_contents_entry(neighbor_text)
            or _looks_front_matter_navigation_heading(neighbor_text)
            or _looks_navigation_title_list_entry(neighbor_text)
        ):
            navigation_like_neighbors += 1
        if _looks_knowledge_heading_with_context(
            neighbor,
            by_atomic_index=by_atomic_index,
        ) or _looks_knowledge_prose_with_context(
            neighbor,
            by_atomic_index=by_atomic_index,
        ):
            lesson_like_neighbors += 1
    return navigation_like_neighbors >= 1 and lesson_like_neighbors == 0


def _outside_recipe_review_exclusion_reason(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> str | None:
    if _is_within_recipe_span(candidate):
        return None
    text = str(candidate.text or "").strip()
    if not text:
        return None
    if _looks_page_furniture(text):
        return "page_furniture"
    if _looks_copyright_legal(text):
        return "copyright_legal"
    if _looks_publishing_metadata(text):
        return "publishing_metadata"
    if _looks_endorsement_credit(text):
        return "endorsement"
    if _looks_front_matter_exclusion_heading(text):
        return "front_matter"
    if _looks_navigation_exclusion_candidate(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "navigation"
    return None


def _build_line_role_book_context(
    *,
    candidates: Sequence[AtomicLineCandidate],
) -> dict[str, Any]:
    by_atomic_index = {
        int(candidate.atomic_index): candidate for candidate in candidates
    }
    evidence_count = sum(
        1
        for candidate in candidates
        if _has_recipe_local_howto_support(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    )
    if evidence_count >= 3:
        availability = "available"
        policy = (
            "`HOWTO_SECTION` is available in this book, but it remains a high-evidence label tied to local recipe structure."
        )
    elif evidence_count >= 1:
        availability = "sparse"
        policy = (
            "`HOWTO_SECTION` appears sparse in this book. Prefer non-structural labels unless the local heading clearly splits one recipe into components or step families."
        )
    else:
        availability = "absent_or_unproven"
        policy = (
            "This book may legitimately use zero `HOWTO_SECTION` labels. Treat the label as optional and require strong local recipe evidence before using it."
        )
    return {
        "howto_section_availability": availability,
        "howto_section_evidence_count": evidence_count,
        "howto_section_policy": policy,
    }


def _build_line_role_canonical_plans(
    *,
    ordered_candidates: Sequence[AtomicLineCandidate],
    deterministic_baseline: dict[int, CanonicalLineRolePrediction],
    settings: RunSettings,
    codex_batch_size: int,
) -> tuple[_LineRoleShardPlan, ...]:
    if not ordered_candidates:
        return ()
    requested_shard_count = _resolve_line_role_requested_shard_count(
        settings=settings,
        codex_batch_size=codex_batch_size,
        total_candidates=len(ordered_candidates),
    )
    book_context = _build_line_role_book_context(candidates=ordered_candidates)
    prompt_format = _resolve_line_role_prompt_format()
    plans: list[_LineRoleShardPlan] = []
    for prompt_index, shard_candidates in enumerate(
        partition_contiguous_items(
            ordered_candidates,
            shard_count=requested_shard_count,
        ),
        start=1,
    ):
        if not shard_candidates:
            continue
        baseline_batch = tuple(
            deterministic_baseline[int(candidate.atomic_index)]
            for candidate in shard_candidates
        )
        first_atomic_index = int(shard_candidates[0].atomic_index)
        last_atomic_index = int(shard_candidates[-1].atomic_index)
        shard_id = (
            f"line-role-canonical-{prompt_index:04d}-"
            f"a{first_atomic_index:06d}-a{last_atomic_index:06d}"
        )
        debug_input_payload = build_line_role_debug_input_payload(
            shard_id=shard_id,
            candidates=shard_candidates,
            deterministic_baseline=deterministic_baseline,
            book_context=book_context,
        )
        manifest_entry = ShardManifestEntryV1(
            shard_id=shard_id,
            owned_ids=tuple(
                str(int(candidate.atomic_index)) for candidate in shard_candidates
            ),
            evidence_refs=tuple(
                dict.fromkeys(str(candidate.block_id) for candidate in shard_candidates)
            ),
            input_payload=build_line_role_model_input_payload(
                shard_id=shard_id,
                candidates=shard_candidates,
                deterministic_baseline=deterministic_baseline,
                debug_rows=list(debug_input_payload.get("rows") or []),
                book_context=book_context,
            ),
            metadata={
                "phase_key": "line_role",
                "prompt_index": prompt_index,
                "prompt_stem": "line_role_prompt",
                "first_atomic_index": first_atomic_index,
                "last_atomic_index": last_atomic_index,
                "owned_row_count": len(shard_candidates),
                "prompt_format": prompt_format,
            },
        )
        plans.append(
            _LineRoleShardPlan(
                phase_key="line_role",
                phase_label="Canonical Line Role",
                runtime_pipeline_id=_LINE_ROLE_CODEX_FARM_PIPELINE_ID,
                prompt_stem="line_role_prompt",
                shard_id=shard_id,
                prompt_index=prompt_index,
                candidates=tuple(shard_candidates),
                baseline_predictions=baseline_batch,
                debug_input_payload=debug_input_payload,
                manifest_entry=manifest_entry,
            )
        )
    return tuple(plans)


def _line_role_execution_plan_phase(
    shard_plans: Sequence[_LineRoleShardPlan],
) -> dict[str, Any]:
    if not shard_plans:
        return {
            "phase_key": None,
            "phase_label": None,
            "runtime_pipeline_id": None,
            "planned_shard_count": 0,
            "planned_candidate_count": 0,
            "shards": [],
        }
    return {
        "phase_key": shard_plans[0].phase_key,
        "phase_label": shard_plans[0].phase_label,
        "runtime_pipeline_id": shard_plans[0].runtime_pipeline_id,
        "planned_shard_count": len(shard_plans),
        "planned_candidate_count": sum(len(plan.candidates) for plan in shard_plans),
        "shards": [
            {
                "shard_id": plan.shard_id,
                "prompt_index": plan.prompt_index,
                "candidate_count": len(plan.candidates),
                "atomic_indices": [int(candidate.atomic_index) for candidate in plan.candidates],
                "owned_ids": list(plan.manifest_entry.owned_ids),
                "rows": list(plan.debug_input_payload.get("rows") or []),
            }
            for plan in shard_plans
        ],
    }


def _resolve_line_role_requested_shard_count(
    *,
    settings: RunSettings,
    codex_batch_size: int,
    total_candidates: int | None = None,
) -> int:
    if total_candidates is not None and total_candidates > 0:
        return resolve_shard_count(
            total_items=total_candidates,
            prompt_target_count=getattr(settings, "line_role_prompt_target_count", None),
            items_per_shard=getattr(settings, "line_role_shard_target_lines", None),
            default_items_per_shard=codex_batch_size,
        )
    configured = getattr(settings, "line_role_shard_target_lines", None)
    resolved = getattr(configured, "value", configured)
    if resolved is not None:
        try:
            return 1
        except (TypeError, ValueError):
            pass
    prompt_target = getattr(settings, "line_role_prompt_target_count", None)
    resolved_prompt_target = getattr(prompt_target, "value", prompt_target)
    if resolved_prompt_target is not None:
        try:
            return max(1, int(resolved_prompt_target))
        except (TypeError, ValueError):
            pass
    return 1


def _resolve_line_role_worker_count(
    *,
    settings: RunSettings,
    codex_max_inflight: int | None,
    shard_count: int,
) -> int:
    if codex_max_inflight is not None:
        return resolve_phase_worker_count(
            requested_worker_count=_normalize_line_role_codex_max_inflight_value(
                codex_max_inflight
            ),
            shard_count=shard_count,
        )
    configured = getattr(settings, "line_role_worker_count", None)
    resolved = getattr(configured, "value", configured)
    if resolved is not None:
        try:
            return resolve_phase_worker_count(
                requested_worker_count=max(1, min(int(resolved), 256)),
                shard_count=shard_count,
            )
        except (TypeError, ValueError):
            pass
    raw_env = str(os.getenv(_LINE_ROLE_CODEX_MAX_INFLIGHT_ENV) or "").strip()
    if raw_env:
        return resolve_phase_worker_count(
            requested_worker_count=_normalize_line_role_codex_max_inflight_value(raw_env),
            shard_count=shard_count,
        )
    return resolve_phase_worker_count(
        requested_worker_count=None,
        shard_count=shard_count,
    )


def _run_line_role_shard_runtime(
    *,
    ordered_candidates: Sequence[AtomicLineCandidate],
    deterministic_baseline: dict[int, CanonicalLineRolePrediction],
    settings: RunSettings,
    artifact_root: Path | None,
    live_llm_allowed: bool,
    codex_timeout_seconds: int,
    codex_batch_size: int,
    codex_max_inflight: int | None,
    codex_cmd: str | None,
    codex_runner: CodexExecRunner | None,
    progress_callback: Callable[[str], None] | None,
) -> _LineRoleRuntimeResult:
    shard_plans = _build_line_role_canonical_plans(
        ordered_candidates=ordered_candidates,
        deterministic_baseline=deterministic_baseline,
        settings=settings,
        codex_batch_size=codex_batch_size,
    )
    if not shard_plans:
        return _LineRoleRuntimeResult(
            predictions_by_atomic_index={},
            phase_results=(),
        )

    prompt_state = _PromptArtifactState(artifact_root=artifact_root)
    codex_exec_cmd = _resolve_line_role_codex_exec_cmd(
        settings=settings,
        codex_cmd_override=codex_cmd,
    )
    codex_farm_root = _resolve_line_role_codex_farm_root(settings=settings)
    codex_farm_workspace_root = _resolve_line_role_codex_farm_workspace_root(
        settings=settings
    )
    codex_farm_model = _resolve_line_role_codex_farm_model(settings=settings)
    codex_farm_reasoning_effort = _resolve_line_role_codex_farm_reasoning_effort(
        settings=settings
    )
    if codex_runner is None:
        runner: CodexExecRunner = SubprocessCodexExecRunner(cmd=codex_exec_cmd)
    else:
        runner = codex_runner

    runtime_root = (
        artifact_root / "line-role-pipeline" / "runtime"
        if artifact_root is not None
        else (
            codex_farm_workspace_root / "line-role-pipeline-runtime"
            if codex_farm_workspace_root is not None
            else Path.cwd() / ".tmp" / "line-role-pipeline-runtime"
        )
    )
    phase_result = _run_line_role_phase_runtime(
        shard_plans=shard_plans,
        artifact_root=artifact_root,
        runtime_root=runtime_root / "line_role",
        live_llm_allowed=live_llm_allowed,
        prompt_state=prompt_state,
        runner=runner,
        codex_farm_root=codex_farm_root,
        codex_farm_workspace_root=codex_farm_workspace_root,
        codex_farm_model=codex_farm_model,
        codex_farm_reasoning_effort=codex_farm_reasoning_effort,
        timeout_seconds=codex_timeout_seconds,
        settings=settings,
        codex_batch_size=codex_batch_size,
        codex_max_inflight=codex_max_inflight,
        progress_callback=progress_callback,
        validator=_validate_line_role_shard_proposal,
    )

    predictions_by_atomic_index: dict[int, CanonicalLineRolePrediction] = {}
    for shard_plan in shard_plans:
        response_payload = phase_result.response_payloads_by_shard_id.get(shard_plan.shard_id)
        if not isinstance(response_payload, dict):
            continue
        proposal_metadata = dict(
            phase_result.proposal_metadata_by_shard_id.get(shard_plan.shard_id) or {}
        )
        task_aggregation_metadata = dict(proposal_metadata.get("task_aggregation") or {})
        fallback_atomic_indices = {
            int(value)
            for value in task_aggregation_metadata.get("baseline_fallback_atomic_indices") or []
            if str(value).strip()
        }
        rows = response_payload.get("rows")
        if not isinstance(rows, list):
            continue
        baseline_by_atomic_index = {
            int(prediction.atomic_index): prediction
            for prediction in shard_plan.baseline_predictions
        }
        candidate_by_atomic_index = {
            int(candidate.atomic_index): candidate for candidate in shard_plan.candidates
        }
        for row in rows:
            atomic_index = int(row["atomic_index"])
            candidate = candidate_by_atomic_index[atomic_index]
            baseline_prediction = baseline_by_atomic_index[atomic_index]
            if atomic_index in fallback_atomic_indices:
                fallback_payload = baseline_prediction.model_dump(mode="python")
                fallback_payload["reason_tags"] = list(baseline_prediction.reason_tags) + [
                    "task_packet_fallback",
                ]
                predictions_by_atomic_index[atomic_index] = CanonicalLineRolePrediction.model_validate(
                    fallback_payload
                )
                continue
            predictions_by_atomic_index[atomic_index] = CanonicalLineRolePrediction(
                recipe_id=candidate.recipe_id,
                block_id=str(candidate.block_id),
                block_index=int(candidate.block_index),
                atomic_index=atomic_index,
                text=str(candidate.text),
                within_recipe_span=candidate.within_recipe_span,
                label=str(row["label"] or baseline_prediction.label or "OTHER"),
                decided_by="codex",
                reason_tags=["codex_line_role"],
                review_exclusion_reason=row.get("review_exclusion_reason"),
            )
    return _LineRoleRuntimeResult(
        predictions_by_atomic_index=predictions_by_atomic_index,
        phase_results=(phase_result,),
    )


def _run_line_role_phase_runtime(
    *,
    shard_plans: Sequence[_LineRoleShardPlan],
    artifact_root: Path | None,
    runtime_root: Path,
    live_llm_allowed: bool,
    prompt_state: "_PromptArtifactState",
    runner: CodexExecRunner,
    codex_farm_root: Path,
    codex_farm_workspace_root: Path | None,
    codex_farm_model: str | None,
    codex_farm_reasoning_effort: str | None,
    timeout_seconds: int,
    settings: RunSettings,
    codex_batch_size: int,
    codex_max_inflight: int | None,
    progress_callback: Callable[[str], None] | None,
    validator: Callable[[ShardManifestEntryV1, dict[str, Any]], tuple[bool, Sequence[str], dict[str, Any] | None]],
) -> _LineRolePhaseRuntimeResult:
    if not shard_plans:
        return _LineRolePhaseRuntimeResult(
            phase_key="",
            phase_label="",
            shard_plans=(),
            worker_reports=(),
            runner_results_by_shard_id={},
            response_payloads_by_shard_id={},
            proposal_metadata_by_shard_id={},
            invalid_shard_count=0,
            missing_output_shard_count=0,
            runtime_root=None,
        )
    if not live_llm_allowed:
        for shard_plan in shard_plans:
            prompt_state.write_failure(
                phase_key=shard_plan.phase_key,
                prompt_stem=shard_plan.prompt_stem,
                prompt_index=shard_plan.prompt_index,
                error="live_llm_not_allowed",
            )
        prompt_state.finalize(
            phase_key=shard_plans[0].phase_key,
            parse_error_count=len(shard_plans),
        )
        return _LineRolePhaseRuntimeResult(
            phase_key=shard_plans[0].phase_key,
            phase_label=shard_plans[0].phase_label,
            shard_plans=tuple(shard_plans),
            worker_reports=(),
            runner_results_by_shard_id={},
            response_payloads_by_shard_id={},
            proposal_metadata_by_shard_id={},
            invalid_shard_count=len(shard_plans),
            missing_output_shard_count=0,
            runtime_root=None,
        )
    worker_count = _resolve_line_role_worker_count(
        settings=settings,
        codex_max_inflight=codex_max_inflight,
        shard_count=len(shard_plans),
    )
    _notify_line_role_progress(
        progress_callback=progress_callback,
        completed_tasks=0,
        total_tasks=len(shard_plans),
        running_tasks=min(worker_count, len(shard_plans)),
        worker_total=worker_count,
    )
    output_schema_path = resolve_codex_farm_output_schema_path(
        root_dir=codex_farm_root,
        pipeline_id=shard_plans[0].runtime_pipeline_id,
    )
    manifest, worker_reports, runner_results_by_shard_id = _run_line_role_direct_workers_v1(
        phase_key=shard_plans[0].phase_key,
        pipeline_id=shard_plans[0].runtime_pipeline_id,
        run_root=runtime_root,
        shards=[plan.manifest_entry for plan in shard_plans],
        debug_payload_by_shard_id={
            plan.shard_id: plan.debug_input_payload for plan in shard_plans
        },
        deterministic_baseline_by_shard_id={
            plan.shard_id: {
                int(prediction.atomic_index): prediction
                for prediction in plan.baseline_predictions
            }
            for plan in shard_plans
        },
        runner=runner,
        worker_count=worker_count,
        env={"CODEX_FARM_ROOT": str(codex_farm_root)},
        model=codex_farm_model,
        reasoning_effort=codex_farm_reasoning_effort,
        output_schema_path=output_schema_path,
        timeout_seconds=max(1, int(timeout_seconds)),
        settings={
            "line_role_pipeline": LINE_ROLE_PIPELINE_SHARD_V1,
            "codex_timeout_seconds": int(timeout_seconds),
            "line_role_prompt_target_count": getattr(
                settings,
                "line_role_prompt_target_count",
                None,
            ),
            "line_role_worker_count": getattr(settings, "line_role_worker_count", None),
            "line_role_shard_target_lines": _resolve_line_role_requested_shard_count(
                settings=settings,
                codex_batch_size=codex_batch_size,
                total_candidates=sum(len(plan.candidates) for plan in shard_plans),
            ),
        },
        runtime_metadata={
            "surface_pipeline": LINE_ROLE_PIPELINE_SHARD_V1,
            "phase_label": shard_plans[0].phase_label,
            "workspace_root": (
                str(codex_farm_workspace_root)
                if codex_farm_workspace_root is not None
                else None
            ),
        },
        progress_callback=progress_callback,
        prompt_state=prompt_state,
        validator=validator,
    )
    invalid_shard_count = 0
    missing_output_shard_count = 0
    response_payloads_by_shard_id: dict[str, dict[str, Any]] = {}
    proposal_metadata_by_shard_id: dict[str, dict[str, Any]] = {}
    proposal_dir = Path(manifest.run_root) / "proposals"
    for shard_plan in shard_plans:
        proposal_path = proposal_dir / f"{shard_plan.shard_id}.json"
        if not proposal_path.exists():
            missing_output_shard_count += 1
            prompt_state.write_failure(
                phase_key=shard_plan.phase_key,
                prompt_stem=shard_plan.prompt_stem,
                prompt_index=shard_plan.prompt_index,
                error="missing_output_file",
            )
            continue
        try:
            proposal_payload = json.loads(proposal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            invalid_shard_count += 1
            prompt_state.write_failure(
                phase_key=shard_plan.phase_key,
                prompt_stem=shard_plan.prompt_stem,
                prompt_index=shard_plan.prompt_index,
                error="invalid_proposal_payload",
            )
            continue
        response_payload = proposal_payload.get("payload")
        validation_errors = proposal_payload.get("validation_errors") or []
        if validation_errors or not isinstance(response_payload, dict):
            invalid_shard_count += 1
            prompt_state.write_failure(
                phase_key=shard_plan.phase_key,
                prompt_stem=shard_plan.prompt_stem,
                prompt_index=shard_plan.prompt_index,
                error=";".join(str(item) for item in validation_errors) or "invalid_proposal",
                response_payload=response_payload,
            )
            continue
        valid, validator_errors, _ = validator(shard_plan.manifest_entry, response_payload)
        if not valid:
            invalid_shard_count += 1
            prompt_state.write_failure(
                phase_key=shard_plan.phase_key,
                prompt_stem=shard_plan.prompt_stem,
                prompt_index=shard_plan.prompt_index,
                error=";".join(str(item) for item in validator_errors) or "invalid_proposal",
                response_payload=response_payload,
            )
            continue
        prompt_state.write_response(
            phase_key=shard_plan.phase_key,
            prompt_stem=shard_plan.prompt_stem,
            prompt_index=shard_plan.prompt_index,
            response_payload=response_payload,
        )
        response_payloads_by_shard_id[shard_plan.shard_id] = response_payload
        proposal_metadata_by_shard_id[shard_plan.shard_id] = dict(
            proposal_payload.get("validation_metadata") or {}
        )
    prompt_state.finalize(
        phase_key=shard_plans[0].phase_key,
        parse_error_count=invalid_shard_count + missing_output_shard_count,
    )
    return _LineRolePhaseRuntimeResult(
        phase_key=shard_plans[0].phase_key,
        phase_label=shard_plans[0].phase_label,
        shard_plans=tuple(shard_plans),
        worker_reports=tuple(worker_reports),
        runner_results_by_shard_id=runner_results_by_shard_id,
        response_payloads_by_shard_id=response_payloads_by_shard_id,
        proposal_metadata_by_shard_id=proposal_metadata_by_shard_id,
        invalid_shard_count=invalid_shard_count,
        missing_output_shard_count=missing_output_shard_count,
        runtime_root=Path(manifest.run_root),
    )


def _validate_line_role_shard_proposal(
    shard: ShardManifestEntryV1,
    payload: dict[str, Any],
) -> tuple[bool, Sequence[str], dict[str, Any] | None]:
    if not isinstance(payload, dict):
        return False, ("proposal_not_a_json_object",), None
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return False, ("rows_missing_or_not_a_list",), None
    owned_atomic_indices = [int(value) for value in shard.owned_ids]
    expected_owned = set(owned_atomic_indices)
    seen_owned: set[int] = set()
    errors: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append("row_not_a_json_object")
            continue
        try:
            atomic_index = int(row.get("atomic_index"))
        except (TypeError, ValueError):
            errors.append("atomic_index_missing")
            continue
        label = str(row.get("label") or "").strip()
        if not label:
            errors.append(f"missing_label:{atomic_index}")
        elif label not in FREEFORM_ALLOWED_LABELS:
            errors.append(f"invalid_label:{atomic_index}:{label}")
        review_exclusion_reason = row.get("review_exclusion_reason")
        try:
            normalized_review_exclusion_reason = _normalize_review_exclusion_reason(
                review_exclusion_reason
            )
        except ValueError as exc:
            errors.append(f"invalid_review_exclusion_reason:{atomic_index}:{exc}")
            normalized_review_exclusion_reason = None
        if normalized_review_exclusion_reason is not None and label != "OTHER":
            errors.append(f"review_exclusion_reason_requires_other:{atomic_index}")
        if atomic_index not in expected_owned:
            errors.append(f"unowned_atomic_index:{atomic_index}")
            continue
        if atomic_index in seen_owned:
            errors.append(f"duplicate_atomic_index:{atomic_index}")
            continue
        seen_owned.add(atomic_index)
    missing_owned = sorted(expected_owned - seen_owned)
    if missing_owned:
        errors.append(
            "missing_owned_atomic_indices:" + ",".join(str(value) for value in missing_owned)
        )
    metadata = {
        "owned_row_count": len(expected_owned),
        "returned_row_count": len(rows),
        "validated_row_count": len(seen_owned),
    }
    return len(errors) == 0, tuple(errors), metadata


def _render_line_role_authoritative_rows(shard: ShardManifestEntryV1) -> str:
    rows = list((_coerce_mapping_dict(shard.input_payload)).get("rows") or [])
    rendered_rows: list[str] = []
    for row in rows:
        if isinstance(row, (list, tuple)):
            rendered_rows.append(json.dumps(list(row), ensure_ascii=False))
        elif isinstance(row, Mapping):
            rendered_rows.append(
                json.dumps(dict(row), ensure_ascii=False, sort_keys=True)
            )
    return "\n".join(rendered_rows) if rendered_rows else "[no shard rows available]"


def _build_line_role_task_plans(
    *,
    shard: ShardManifestEntryV1,
    debug_payload: Any,
    target_rows: int | None = None,
) -> tuple[_LineRoleTaskPlan, ...]:
    input_payload = _coerce_mapping_dict(shard.input_payload)
    input_rows = list(input_payload.get("rows") or [])
    debug_rows = list(_coerce_mapping_dict(debug_payload).get("rows") or [])
    if not input_rows:
        return ()
    normalized_target_rows = max(1, int(target_rows or _LINE_ROLE_TASK_TARGET_ROWS or 1))
    debug_row_by_atomic_index: dict[int, dict[str, Any]] = {}
    for row in debug_rows:
        if not isinstance(row, Mapping):
            continue
        try:
            atomic_index = int(row.get("atomic_index"))
        except (TypeError, ValueError):
            continue
        debug_row_by_atomic_index[atomic_index] = dict(row)
    task_plans: list[_LineRoleTaskPlan] = []
    task_count = max(1, (len(input_rows) + normalized_target_rows - 1) // normalized_target_rows)
    for task_index, start in enumerate(range(0, len(input_rows), normalized_target_rows), start=1):
        task_rows = input_rows[start : start + normalized_target_rows]
        owned_ids: list[str] = []
        task_debug_rows: list[dict[str, Any]] = []
        for row in task_rows:
            if not isinstance(row, (list, tuple)) or not row:
                continue
            try:
                atomic_index = int(row[0])
            except (TypeError, ValueError):
                continue
            owned_ids.append(str(atomic_index))
            debug_row = debug_row_by_atomic_index.get(atomic_index)
            if debug_row is not None:
                task_debug_rows.append(dict(debug_row))
        if not owned_ids:
            continue
        task_id = (
            shard.shard_id
            if task_count == 1
            else f"{shard.shard_id}.task-{task_index:03d}"
        )
        overlap = max(0, int(_LINE_ROLE_TASK_CONTEXT_OVERLAP_ROWS))
        task_end = start + len(task_rows)
        task_input_context_before = [
            list(row)
            for row in input_rows[max(0, start - overlap) : start]
            if isinstance(row, (list, tuple)) and len(row) >= 3
        ]
        task_input_context_before = [
            [int(row[0]), str(row[2])]
            for row in task_input_context_before
        ]
        task_input_context_after = [
            list(row)
            for row in input_rows[task_end : task_end + overlap]
            if isinstance(row, (list, tuple)) and len(row) >= 3
        ]
        task_input_context_after = [
            [int(row[0]), str(row[2])]
            for row in task_input_context_after
        ]
        task_debug_context_before: list[dict[str, Any]] = []
        for row in debug_rows[max(0, start - overlap) : start]:
            if not isinstance(row, Mapping):
                continue
            serialized = serialize_line_role_debug_context_row_from_mapping(row)
            if serialized is not None:
                task_debug_context_before.append(serialized)
        task_debug_context_after: list[dict[str, Any]] = []
        for row in debug_rows[task_end : task_end + overlap]:
            if not isinstance(row, Mapping):
                continue
            serialized = serialize_line_role_debug_context_row_from_mapping(row)
            if serialized is not None:
                task_debug_context_after.append(serialized)
        task_input_payload = {
            **input_payload,
            "shard_id": task_id,
            "parent_shard_id": shard.shard_id,
            **_build_line_role_packet_context(rows=task_debug_rows),
            "context_before_rows": task_input_context_before,
            "context_after_rows": task_input_context_after,
            "rows": task_rows,
        }
        task_debug_payload = {
            **_coerce_mapping_dict(debug_payload),
            "shard_id": task_id,
            "parent_shard_id": shard.shard_id,
            **_build_line_role_packet_context(rows=task_debug_rows),
            "context_before_rows": task_debug_context_before,
            "context_after_rows": task_debug_context_after,
            "rows": task_debug_rows,
        }
        task_manifest = ShardManifestEntryV1(
            shard_id=task_id,
            owned_ids=tuple(owned_ids),
            evidence_refs=shard.evidence_refs,
            input_payload=task_input_payload,
            metadata={
                **_coerce_mapping_dict(shard.metadata),
                "parent_shard_id": shard.shard_id,
                "task_id": task_id,
                "task_index": task_index,
                "task_count": task_count,
                "owned_row_count": len(owned_ids),
                "context_before_row_count": len(task_input_context_before),
                "context_after_row_count": len(task_input_context_after),
            },
        )
        task_plans.append(
            _LineRoleTaskPlan(
                task_id=task_id,
                parent_shard_id=shard.shard_id,
                manifest_entry=task_manifest,
                debug_input_payload=task_debug_payload,
            )
        )
    return tuple(task_plans)


def _aggregate_line_role_task_payloads(
    *,
    shard: ShardManifestEntryV1,
    task_payloads_by_task_id: Mapping[str, dict[str, Any] | None],
    task_validation_errors_by_task_id: Mapping[str, Sequence[str]],
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
) -> tuple[dict[str, Any], dict[str, Any]]:
    ordered_atomic_indices = [int(value) for value in shard.owned_ids]
    output_rows: list[dict[str, Any]] = []
    accepted_task_ids: list[str] = []
    fallback_task_ids: list[str] = []
    task_payload_row_by_atomic_index: dict[int, dict[str, Any]] = {}
    task_id_by_atomic_index: dict[int, str] = {}
    for task_id, payload in task_payloads_by_task_id.items():
        rows = payload.get("rows") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            continue
        accepted_task_ids.append(task_id)
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            try:
                atomic_index = int(row.get("atomic_index"))
            except (TypeError, ValueError):
                continue
            task_payload_row_by_atomic_index[atomic_index] = {
                "atomic_index": atomic_index,
                "label": str(row.get("label") or "").strip(),
            }
            task_id_by_atomic_index[atomic_index] = task_id
    missing_atomic_indices: list[int] = []
    baseline_fallback_atomic_indices: list[int] = []
    for atomic_index in ordered_atomic_indices:
        task_row = task_payload_row_by_atomic_index.get(atomic_index)
        if task_row is not None and str(task_row.get("label") or "").strip():
            output_rows.append(dict(task_row))
            continue
        baseline_prediction = deterministic_baseline_by_atomic_index.get(atomic_index)
        if baseline_prediction is None:
            missing_atomic_indices.append(atomic_index)
            continue
        output_rows.append(
            {
                "atomic_index": atomic_index,
                "label": str(baseline_prediction.label or "OTHER").strip() or "OTHER",
            }
        )
        baseline_fallback_atomic_indices.append(atomic_index)
    fallback_task_ids = sorted(
        {
            str(task_id).strip()
            for task_id, errors in task_validation_errors_by_task_id.items()
            if errors or task_id not in accepted_task_ids
        }
    )
    all_task_ids = sorted(
        {
            str(task_id).strip()
            for task_id in [*task_payloads_by_task_id.keys(), *task_validation_errors_by_task_id.keys()]
            if str(task_id).strip()
        }
    )
    metadata = {
        "task_count": len(all_task_ids),
        "accepted_task_count": len(accepted_task_ids),
        "fallback_task_count": len(fallback_task_ids),
        "accepted_task_ids": sorted(accepted_task_ids),
        "task_ids": all_task_ids,
        "fallback_task_ids": fallback_task_ids,
        "baseline_fallback_atomic_indices": baseline_fallback_atomic_indices,
        "missing_atomic_indices": missing_atomic_indices,
        "task_validation_errors_by_task_id": {
            task_id: list(errors)
            for task_id, errors in task_validation_errors_by_task_id.items()
            if errors
        },
        "task_id_by_atomic_index": {
            str(atomic_index): task_id
            for atomic_index, task_id in sorted(task_id_by_atomic_index.items())
        },
    }
    return {"rows": output_rows}, metadata


def _line_role_task_aggregation_validation_errors(
    aggregation_metadata: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    if not isinstance(aggregation_metadata, Mapping):
        return ()
    task_errors_by_task_id = aggregation_metadata.get("task_validation_errors_by_task_id")
    if not isinstance(task_errors_by_task_id, Mapping):
        return ()
    errors: list[str] = []
    seen_errors: set[str] = set()
    for task_id in sorted(task_errors_by_task_id):
        task_errors = task_errors_by_task_id.get(task_id)
        if not isinstance(task_errors, list | tuple):
            continue
        for error in task_errors:
            cleaned = str(error).strip()
            if not cleaned or cleaned in seen_errors:
                continue
            seen_errors.add(cleaned)
            errors.append(cleaned)
    return tuple(errors)


def _build_line_role_task_manifest_entry(
    task_plan: _LineRoleTaskPlan,
) -> TaskManifestEntryV1:
    task_manifest = task_plan.manifest_entry
    metadata = build_line_role_workspace_task_metadata(
        task_id=task_plan.task_id,
        parent_shard_id=task_plan.parent_shard_id,
        input_payload=_coerce_mapping_dict(task_manifest.input_payload),
        input_path=f"in/{task_plan.task_id}.json",
        hint_path=f"hints/{task_plan.task_id}.md",
        result_path=f"out/{task_plan.task_id}.json",
        scratch_draft_path=build_line_role_scratch_draft_path(task_plan.task_id),
    )
    return TaskManifestEntryV1(
        task_id=task_plan.task_id,
        task_kind="line_role_label_packet",
        parent_shard_id=task_plan.parent_shard_id,
        owned_ids=tuple(task_manifest.owned_ids),
        input_payload=task_manifest.input_payload,
        input_text=task_manifest.input_text,
        metadata={
            **_coerce_mapping_dict(task_manifest.metadata),
            **metadata,
        },
    )


def _validate_line_role_payload_semantics(
    *,
    payload: Mapping[str, Any],
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
) -> tuple[tuple[str, ...], dict[str, Any]]:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return (), {}
    candidate_label_by_atomic_index: dict[int, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            atomic_index = int(row.get("atomic_index"))
        except (TypeError, ValueError):
            continue
        label = str(row.get("label") or "").strip().upper()
        if label:
            candidate_label_by_atomic_index[atomic_index] = label
    total_rows = len(candidate_label_by_atomic_index)
    if total_rows < _LINE_ROLE_PATHOLOGY_MIN_ROWS:
        return (
            (),
            {
                "guard_applied": False,
                "reason": "too_few_rows",
                "candidate_row_count": total_rows,
            },
        )

    candidate_counts: dict[str, int] = {}
    baseline_counts: dict[str, int] = {}
    for atomic_index, label in candidate_label_by_atomic_index.items():
        candidate_counts[label] = candidate_counts.get(label, 0) + 1
        baseline_prediction = deterministic_baseline_by_atomic_index.get(atomic_index)
        if baseline_prediction is None:
            continue
        baseline_label = str(baseline_prediction.label or "").strip().upper()
        if baseline_label:
            baseline_counts[baseline_label] = baseline_counts.get(baseline_label, 0) + 1

    if not candidate_counts or not baseline_counts:
        return (
            (),
            {
                "guard_applied": False,
                "reason": "missing_label_counts",
                "candidate_row_count": total_rows,
            },
        )

    dominant_label, dominant_count = max(
        candidate_counts.items(),
        key=lambda item: (item[1], item[0]),
    )
    baseline_same_label_count = baseline_counts.get(dominant_label, 0)
    metadata = {
        "guard_applied": True,
        "candidate_row_count": total_rows,
        "candidate_distinct_label_count": len(candidate_counts),
        "candidate_dominant_label": dominant_label,
        "candidate_dominant_count": dominant_count,
        "baseline_distinct_label_count": len(baseline_counts),
        "baseline_matching_label_count": baseline_same_label_count,
    }

    if (
        len(candidate_counts) == 1
        and len(baseline_counts) >= _LINE_ROLE_PATHOLOGY_MIN_BASELINE_DISTINCT_LABELS
        and baseline_same_label_count <= (total_rows - 2)
    ):
        return (
            (f"pathological_uniform_label_output:{dominant_label}",),
            metadata,
        )

    if (
        dominant_count >= total_rows - 1
        and total_rows >= _LINE_ROLE_PATHOLOGY_NEAR_UNIFORM_MIN_ROWS
        and len(baseline_counts)
        >= (_LINE_ROLE_PATHOLOGY_MIN_BASELINE_DISTINCT_LABELS + 1)
        and baseline_same_label_count <= (total_rows - 3)
    ):
        return (
            (f"pathological_near_uniform_label_output:{dominant_label}",),
            metadata,
        )

    return (), metadata


def _evaluate_line_role_response_with_pathology_guard(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
    validator: Callable[
        [ShardManifestEntryV1, dict[str, Any]],
        tuple[bool, Sequence[str], dict[str, Any] | None],
    ],
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    payload, validation_errors, validation_metadata, proposal_status = (
        _evaluate_line_role_response(
            shard=shard,
            response_text=response_text,
            validator=validator,
        )
    )
    if proposal_status != "validated" or payload is None:
        return payload, validation_errors, validation_metadata, proposal_status
    semantic_errors, semantic_metadata = _validate_line_role_payload_semantics(
        payload=payload,
        deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
    )
    if semantic_metadata:
        validation_metadata = {
            **dict(validation_metadata or {}),
            "semantic_validation": semantic_metadata,
        }
    if semantic_errors:
        validation_metadata = {
            **dict(validation_metadata or {}),
            "semantic_diagnostics": list(semantic_errors),
        }
    return payload, validation_errors, validation_metadata, proposal_status


def _build_line_role_canonical_line_table_rows(
    *,
    debug_payload_by_shard_id: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows_by_atomic_index: dict[int, dict[str, Any]] = {}
    for shard_id, debug_payload in debug_payload_by_shard_id.items():
        payload_rows = list(_coerce_mapping_dict(debug_payload).get("rows") or [])
        for row in payload_rows:
            if not isinstance(row, Mapping):
                continue
            try:
                atomic_index = int(row.get("atomic_index"))
            except (TypeError, ValueError):
                continue
            rows_by_atomic_index[atomic_index] = {
                "line_id": str(atomic_index),
                "atomic_index": atomic_index,
                "block_id": str(row.get("block_id") or ""),
                "block_index": int(row.get("block_index") or 0),
                "recipe_id": row.get("recipe_id"),
                "within_recipe_span": row.get("within_recipe_span"),
                "current_line": str(row.get("current_line") or ""),
                "deterministic_label": str(row.get("deterministic_label") or "OTHER").strip()
                or "OTHER",
                "rule_tags": [
                    str(tag).strip()
                    for tag in row.get("rule_tags") or []
                    if str(tag).strip()
                ],
                "escalation_reasons": [
                    str(reason).strip()
                    for reason in row.get("escalation_reasons") or []
                    if str(reason).strip()
                ],
                "source_shard_id": str(shard_id),
            }
    return [rows_by_atomic_index[key] for key in sorted(rows_by_atomic_index)]


def _find_line_role_existing_output_path(
    *,
    run_root: Path,
    preferred_worker_root: Path,
    task_id: str,
) -> Path | None:
    candidate_paths: list[Path] = []
    preferred_path = preferred_worker_root / "out" / f"{task_id}.json"
    if preferred_path.exists():
        candidate_paths.append(preferred_path)
    candidate_paths.extend(
        path
        for path in sorted(run_root.glob(f"workers/*/out/{task_id}.json"))
        if path != preferred_path
    )
    for path in candidate_paths:
        if path.exists():
            return path
    return None


def _build_line_role_task_status_row(
    *,
    task_manifest: ShardManifestEntryV1,
    worker_id: str,
    state: str,
    last_attempt_type: str,
    output_path: Path | None,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
    repair_attempted: bool,
    repair_status: str,
    resumed_from_existing_output: bool,
) -> dict[str, Any]:
    semantic_diagnostics = [
        str(value).strip()
        for value in (validation_metadata or {}).get("semantic_diagnostics", [])
        if str(value).strip()
    ]
    owned_row_count = len(tuple(task_manifest.owned_ids))
    llm_authoritative = state in {"validated", "repair_recovered"}
    fallback_row_count = 0 if llm_authoritative else owned_row_count
    metadata = {
        "repair_attempted": bool(repair_attempted),
        "repair_status": str(repair_status or "not_attempted"),
        "output_path": str(output_path) if output_path is not None else None,
        "owned_row_count": owned_row_count,
        "llm_authoritative_row_count": owned_row_count if llm_authoritative else 0,
        "fallback_row_count": fallback_row_count,
        "suspicious_row_count": owned_row_count if semantic_diagnostics else 0,
        "suspicious_packet": bool(semantic_diagnostics),
        "semantic_diagnostics": semantic_diagnostics,
        "resumed_from_existing_output": bool(resumed_from_existing_output),
        "validation_errors": [
            str(error).strip() for error in validation_errors if str(error).strip()
        ],
    }
    if validation_metadata:
        metadata["validation_metadata"] = dict(validation_metadata)
    return {
        "task_id": task_manifest.shard_id,
        "parent_shard_id": str(
            (task_manifest.metadata or {}).get("parent_shard_id") or task_manifest.shard_id
        ),
        "worker_id": worker_id,
        "owned_ids": [str(value).strip() for value in task_manifest.owned_ids if str(value).strip()],
        "state": state,
        "terminal_outcome": state,
        "last_attempt_type": last_attempt_type,
        "metadata": metadata,
    }


def _notify_line_role_progress(
    *,
    progress_callback: Callable[[str], None] | None,
    completed_tasks: int,
    total_tasks: int,
    running_tasks: int | None = None,
    worker_total: int | None = None,
    worker_running: int | None = None,
    worker_completed: int | None = None,
    worker_failed: int | None = None,
    followup_running: int | None = None,
    followup_completed: int | None = None,
    followup_total: int | None = None,
    followup_label: str | None = None,
    artifact_counts: dict[str, Any] | None = None,
    active_tasks: list[str] | None = None,
) -> None:
    if progress_callback is None:
        return
    total = max(0, int(total_tasks))
    completed = max(0, min(total, int(completed_tasks)))
    message = f"Running canonical line-role pipeline... task {completed}/{total}"
    if running_tasks is not None:
        running = max(0, int(running_tasks))
        message = f"{message} | running {running}"
    remaining = max(0, total - completed)
    detail_lines = [
        f"queued shards: {remaining}",
    ]
    if worker_total is not None:
        detail_lines.insert(0, f"configured workers: {max(0, int(worker_total))}")
    progress_callback(
        format_stage_progress(
            message,
            stage_label="canonical line-role pipeline",
            work_unit_label="task packet",
            task_current=completed,
            task_total=total,
            running_workers=running_tasks,
            worker_total=worker_total,
            worker_running=worker_running,
            worker_completed=worker_completed,
            worker_failed=worker_failed,
            followup_running=followup_running,
            followup_completed=followup_completed,
            followup_total=followup_total,
            followup_label=followup_label,
            artifact_counts=artifact_counts,
            last_activity_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            active_tasks=active_tasks,
            detail_lines=detail_lines,
        )
    )


def _line_role_progress_interval(total_tasks: int) -> int:
    total = max(1, int(total_tasks))
    # Keep progress updates frequent enough for responsive ETA while avoiding
    # excessive callback chatter on large books.
    return max(1, (total + _LINE_ROLE_PROGRESS_MAX_UPDATES - 1) // _LINE_ROLE_PROGRESS_MAX_UPDATES)


def _resolve_line_role_prompt_format() -> LineRolePromptFormat:
    return "compact_v1"


def _resolve_line_role_codex_exec_cmd(
    *,
    settings: RunSettings,
    codex_cmd_override: str | None,
) -> str:
    override = str(codex_cmd_override or "").strip()
    if override:
        return override
    configured = str(getattr(settings, "codex_farm_cmd", "") or "").strip()
    if configured and _looks_like_codex_exec_command(configured):
        return configured
    if configured and Path(configured).name == "fake-codex-farm.py":
        return configured
    return _LINE_ROLE_CODEX_EXEC_DEFAULT_CMD


def _resolve_line_role_codex_farm_root(*, settings: RunSettings) -> Path:
    configured = str(getattr(settings, "codex_farm_root", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "llm_pipelines"


def _resolve_line_role_codex_farm_workspace_root(
    *,
    settings: RunSettings,
) -> Path | None:
    configured = str(getattr(settings, "codex_farm_workspace_root", "") or "").strip()
    if not configured:
        return None
    return Path(configured).expanduser()


def _resolve_line_role_codex_farm_model(*, settings: RunSettings) -> str | None:
    configured = str(getattr(settings, "codex_farm_model", "") or "").strip()
    return configured or None


def _resolve_line_role_codex_farm_reasoning_effort(
    *,
    settings: RunSettings,
) -> str | None:
    raw_value = getattr(settings, "codex_farm_reasoning_effort", None)
    if raw_value is None:
        return None
    resolved = getattr(raw_value, "value", raw_value)
    cleaned = str(resolved or "").strip()
    return cleaned or None


def _looks_like_codex_exec_command(command_text: str) -> bool:
    tokens = str(command_text or "").strip().split()
    if not tokens:
        return False
    executable = Path(tokens[0]).name.lower()
    return executable in _CODEX_EXECUTABLES


def _run_line_role_workspace_worker_assignment_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: dict[str, str],
    assigned_shards: Sequence[ShardManifestEntryV1],
    worker_root: Path,
    in_dir: Path,
    debug_dir: Path,
    hints_dir: Path,
    shard_dir: Path,
    logs_dir: Path,
    debug_payload_by_shard_id: Mapping[str, Any],
    deterministic_baseline_by_shard_id: Mapping[
        str, Mapping[int, CanonicalLineRolePrediction]
    ],
    runner: CodexExecRunner,
    pipeline_id: str,
    env: dict[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    timeout_seconds: int,
    cohort_watchdog_state: _LineRoleCohortWatchdogState,
    shard_completed_callback: Callable[..., None] | None,
    prompt_state: "_PromptArtifactState" | None,
    validator: Callable[[ShardManifestEntryV1, dict[str, Any]], tuple[bool, Sequence[str], dict[str, Any] | None]],
) -> _DirectLineRoleWorkerResult:
    out_dir = worker_root / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir = worker_root / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    worker_failure_count = 0
    worker_proposal_count = 0
    worker_runner_results: list[dict[str, Any]] = []
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    stage_rows: list[dict[str, Any]] = []
    runner_results_by_shard_id: dict[str, dict[str, Any]] = {}
    all_task_plans_by_shard_id: dict[str, tuple[_LineRoleTaskPlan, ...]] = {}
    all_task_plans: list[_LineRoleTaskPlan] = []
    runnable_task_ids: set[str] = set()
    resumed_output_path_by_task_id: dict[str, Path] = {}
    task_status_rows: list[dict[str, Any]] = []
    worker_prompt_path: Path | None = None
    session_run_result: CodexExecRunResult | None = None

    for shard in assigned_shards:
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
        preflight_failure = _preflight_line_role_shard(shard)
        if preflight_failure is None:
            task_plans = _build_line_role_task_plans(
                shard=shard,
                debug_payload=debug_payload_by_shard_id.get(shard.shard_id),
            )
            if task_plans:
                all_task_plans_by_shard_id[shard.shard_id] = task_plans
                all_task_plans.extend(task_plans)
            continue
        _write_runtime_json(
            shard_root / "live_status.json",
            {
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
                "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                "retryable": False,
                "watchdog_policy": "workspace_worker_v1",
                "elapsed_seconds": 0.0,
                "last_event_seconds_ago": None,
                "command_execution_count": 0,
                "reasoning_item_count": 0,
            },
        )
        _write_runtime_json(
            shard_root / "status.json",
            {
                "status": "missing_output",
                "validation_errors": [
                    str(preflight_failure.get("reason_code") or "preflight_rejected")
                ],
                "validation_metadata": {},
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "watchdog_retry_attempted": False,
                "watchdog_retry_status": "not_attempted",
                "repair_attempted": False,
                "repair_status": "not_attempted",
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
                "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                "retryable": False,
            },
        )
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        _write_runtime_json(
            proposal_path,
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": None,
                "validation_errors": [
                    str(preflight_failure.get("reason_code") or "preflight_rejected")
                ],
                "validation_metadata": {},
                "watchdog_retry_attempted": False,
                "watchdog_retry_status": "not_attempted",
                "repair_attempted": False,
                "repair_status": "not_attempted",
            },
        )
        _write_runtime_json(
            shard_root / "proposal.json",
            {
                "error": "missing_output",
                "validation_errors": [
                    str(preflight_failure.get("reason_code") or "preflight_rejected")
                ],
                "validation_metadata": {},
            },
        )
        worker_failure_count += 1
        worker_failures.append(
            {
                "worker_id": assignment.worker_id,
                "shard_id": shard.shard_id,
                "reason": "preflight_rejected",
                "validation_errors": [
                    str(preflight_failure.get("reason_code") or "preflight_rejected")
                ],
            }
        )
        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status="missing_output",
                proposal_path=_relative_runtime_path(run_root, proposal_path),
                payload=None,
                validation_errors=(
                    str(preflight_failure.get("reason_code") or "preflight_rejected"),
                ),
                metadata={},
            )
        )
        if prompt_state is not None:
            prompt_state.write_failure(
                phase_key=str((shard.metadata or {}).get("phase_key") or "line_role").strip(),
                prompt_stem=str((shard.metadata or {}).get("prompt_stem") or "prompt").strip(),
                prompt_index=int((shard.metadata or {}).get("prompt_index") or 0),
                error=str(preflight_failure.get("reason_detail") or "preflight rejected"),
            )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    assigned_task_rows = [
        _line_role_asdict(_build_line_role_task_manifest_entry(task))
        for task in all_task_plans
    ]
    assigned_task_row_by_task_id = {
        str(task_row.get("task_id") or "").strip(): task_row
        for task_row in assigned_task_rows
        if str(task_row.get("task_id") or "").strip()
    }
    _write_runtime_json(worker_root / "assigned_tasks.json", assigned_task_rows)
    _write_line_role_worker_examples(worker_root=worker_root)
    _write_line_role_output_contract(worker_root=worker_root)
    _write_line_role_worker_tools(worker_root=worker_root)
    for task in all_task_plans:
        task_manifest = task.manifest_entry
        task_id = task_manifest.shard_id
        task_row = assigned_task_row_by_task_id.get(task_id)
        if task_row is not None:
            draft_path = worker_root / build_line_role_scratch_draft_path(task_id)
            _write_runtime_json(
                draft_path,
                build_line_role_seed_output(task_row),
            )
        _write_worker_debug_input(
            path=in_dir / f"{task_id}.json",
            payload=task_manifest.input_payload,
            input_text=None,
        )
        _write_worker_debug_input(
            path=debug_dir / f"{task_id}.json",
            payload=task.debug_input_payload,
            input_text=None,
        )
        _write_line_role_worker_hint(
            path=hints_dir / f"{task_id}.md",
            shard=task_manifest,
            debug_payload=task.debug_input_payload,
        )
        existing_output_path = _find_line_role_existing_output_path(
            run_root=run_root,
            preferred_worker_root=worker_root,
            task_id=task_id,
        )
        if existing_output_path is None:
            runnable_task_ids.add(task_id)
            continue
        try:
            existing_response_text = existing_output_path.read_text(encoding="utf-8")
        except OSError:
            runnable_task_ids.add(task_id)
            continue
        existing_payload, _, _, existing_status = (
            _evaluate_line_role_response_with_pathology_guard(
                shard=task_manifest,
                response_text=existing_response_text,
                validator=validator,
                deterministic_baseline_by_atomic_index=dict(
                    deterministic_baseline_by_shard_id.get(task.parent_shard_id) or {}
                ),
            )
        )
        if existing_payload is not None and existing_status == "validated":
            resumed_output_path_by_task_id[task_id] = existing_output_path
        else:
            runnable_task_ids.add(task_id)

    runnable_tasks = [
        task for task in all_task_plans if task.task_id in runnable_task_ids
    ]
    runnable_shards = [
        shard
        for shard in assigned_shards
        if shard.shard_id
        in {task.parent_shard_id for task in runnable_tasks}
    ]

    if runnable_shards and runnable_tasks:
        worker_prompt_text = _build_line_role_workspace_worker_prompt(
            tasks=[
                _build_line_role_task_manifest_entry(task)
                for task in runnable_tasks
            ]
        )
        worker_prompt_path = worker_root / "prompt.txt"
        worker_prompt_path.write_text(worker_prompt_text, encoding="utf-8")
        worker_live_status_path = worker_root / "live_status.json"
        shard_live_status_paths = [
            shard_dir / shard.shard_id / "live_status.json" for shard in runnable_shards
        ]
        for shard in runnable_shards:
            shard_root = shard_dir / shard.shard_id
            (shard_root / "prompt.txt").write_text(worker_prompt_text, encoding="utf-8")
            if prompt_state is not None:
                prompt_state.write_prompt(
                    phase_key=str((shard.metadata or {}).get("phase_key") or "line_role").strip(),
                    prompt_stem=str((shard.metadata or {}).get("prompt_stem") or "prompt").strip(),
                    prompt_index=int((shard.metadata or {}).get("prompt_index") or 0),
                    prompt_text=worker_prompt_text,
                )

        session_run_result = runner.run_workspace_worker(
            prompt_text=worker_prompt_text,
            working_dir=worker_root,
            env=env,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
            workspace_task_label="canonical line-role worker session",
            supervision_callback=_build_strict_json_watchdog_callback(
                live_status_path=worker_live_status_path,
                live_status_paths=shard_live_status_paths,
                cohort_watchdog_state=cohort_watchdog_state,
                watchdog_policy="workspace_worker_v1",
                allow_workspace_commands=True,
                expected_workspace_output_paths=[
                    out_dir / f"{task.task_id}.json" for task in runnable_tasks
                ],
            ),
        )
        _finalize_live_status(
            worker_live_status_path,
            run_result=session_run_result,
            watchdog_policy="workspace_worker_v1",
        )
        for live_status_path in shard_live_status_paths:
            _finalize_live_status(
                live_status_path,
                run_result=session_run_result,
                watchdog_policy="workspace_worker_v1",
            )
        (worker_root / "events.jsonl").write_text(
            _render_codex_events_jsonl(session_run_result.events),
            encoding="utf-8",
        )
        _write_runtime_json(
            worker_root / "last_message.json",
            {"text": session_run_result.response_text},
        )
        _write_runtime_json(worker_root / "usage.json", dict(session_run_result.usage or {}))
        _write_runtime_json(
            worker_root / "workspace_manifest.json",
            session_run_result.workspace_manifest(),
        )
    else:
        _write_runtime_json(
            worker_root / "live_status.json",
            {
                "state": "completed",
                "reason_code": (
                    "resume_existing_outputs"
                    if resumed_output_path_by_task_id
                    else "no_tasks_assigned"
                ),
                "reason_detail": (
                    "all canonical line-role packet outputs were already durable on disk"
                    if resumed_output_path_by_task_id
                    else "worker had no runnable canonical line-role packets"
                ),
                "retryable": False,
                "watchdog_policy": "workspace_worker_v1",
            },
        )

    task_count = max(1, len(runnable_tasks))
    task_payloads_by_shard_id: dict[str, dict[str, dict[str, Any]]] = {}
    task_validation_errors_by_shard_id: dict[str, dict[str, tuple[str, ...]]] = {}
    task_watchdog_retry_status_by_shard_id: dict[str, dict[str, str]] = {}
    task_repair_status_by_shard_id: dict[str, dict[str, str]] = {}
    task_repair_validation_errors_by_shard_id: dict[str, dict[str, tuple[str, ...]]] = {}
    for task_index, task in enumerate(all_task_plans):
        task_manifest = task.manifest_entry
        parent_shard_id = task.parent_shard_id
        input_path = in_dir / f"{task_manifest.shard_id}.json"
        debug_path = debug_dir / f"{task_manifest.shard_id}.json"
        output_path = out_dir / f"{task_manifest.shard_id}.json"
        response_source_path = (
            output_path if output_path.exists() else resumed_output_path_by_task_id.get(task_manifest.shard_id)
        )
        response_text = (
            response_source_path.read_text(encoding="utf-8")
            if response_source_path is not None and response_source_path.exists()
            else None
        )
        if (
            session_run_result is not None
            and task.task_id in runnable_task_ids
            and worker_prompt_path is not None
        ):
            runner_payload = _build_line_role_workspace_task_runner_payload(
                pipeline_id=pipeline_id,
                worker_id=assignment.worker_id,
                shard_id=parent_shard_id,
                runtime_task_id=task_manifest.shard_id,
                run_result=session_run_result,
                model=model,
                reasoning_effort=reasoning_effort,
                request_input_file=input_path,
                debug_input_file=debug_path,
                worker_prompt_path=worker_prompt_path,
                task_count=task_count,
                task_index=min(task_index, task_count - 1),
            )
            worker_runner_results.append(dict(runner_payload))
            telemetry = runner_payload.get("telemetry")
            row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
            if isinstance(row_payloads, list):
                for row_payload in row_payloads:
                    if isinstance(row_payload, dict):
                        stage_rows.append(dict(row_payload))
            primary_row = stage_rows[-1] if stage_rows else None
            primary_runner_row = (
                row_payloads[0]
                if isinstance(row_payloads, list)
                and row_payloads
                and isinstance(row_payloads[0], dict)
                else None
            )
        else:
            primary_row = None
            primary_runner_row = None

        payload, validation_errors, validation_metadata, proposal_status = (
            _evaluate_line_role_response_with_pathology_guard(
                shard=task_manifest,
                response_text=response_text,
                validator=validator,
                deterministic_baseline_by_atomic_index=dict(
                    deterministic_baseline_by_shard_id.get(parent_shard_id) or {}
                ),
            )
        )
        watchdog_retry_attempted = False
        watchdog_retry_status = "not_attempted"
        repair_attempted = False
        repair_status = "not_attempted"
        final_validation_errors = tuple(validation_errors)
        final_validation_metadata = dict(validation_metadata or {})
        task_root = shard_dir / task_manifest.shard_id
        task_root.mkdir(parents=True, exist_ok=True)
        if primary_row is not None:
            primary_row["proposal_status"] = proposal_status
            _annotate_line_role_final_proposal_status(
                primary_row,
                final_proposal_status=proposal_status,
            )
            primary_row["runtime_task_id"] = task_manifest.shard_id
            primary_row["runtime_parent_shard_id"] = parent_shard_id
        if primary_runner_row is not None:
            primary_runner_row["proposal_status"] = proposal_status
            _annotate_line_role_final_proposal_status(
                primary_runner_row,
                final_proposal_status=proposal_status,
            )
            primary_runner_row["runtime_task_id"] = task_manifest.shard_id
            primary_runner_row["runtime_parent_shard_id"] = parent_shard_id
        if (
            task.task_id in runnable_task_ids
            and payload is None
            and proposal_status == "missing_output"
            and session_run_result is not None
            and _should_attempt_line_role_watchdog_retry(
                run_result=session_run_result,
            )
        ):
            watchdog_retry_attempted = True
            watchdog_retry_live_status_path = task_root / "watchdog_retry_live_status.json"
            watchdog_retry_run_result = _run_line_role_watchdog_retry_attempt(
                runner=runner,
                worker_root=worker_root,
                shard=task_manifest,
                env=env,
                output_schema_path=output_schema_path,
                model=model,
                reasoning_effort=reasoning_effort,
                original_reason_code=str(
                    session_run_result.supervision_reason_code or ""
                ),
                original_reason_detail=str(
                    session_run_result.supervision_reason_detail or ""
                ),
                successful_examples=list(
                    cohort_watchdog_state.snapshot().get("successful_examples") or []
                ),
                timeout_seconds=timeout_seconds,
                pipeline_id=pipeline_id,
                worker_id=assignment.worker_id,
                live_status_path=watchdog_retry_live_status_path,
            )
            _finalize_live_status(
                watchdog_retry_live_status_path,
                run_result=watchdog_retry_run_result,
                watchdog_policy=_STRICT_JSON_WATCHDOG_POLICY,
            )
            (task_root / "watchdog_retry_events.jsonl").write_text(
                _render_codex_events_jsonl(watchdog_retry_run_result.events),
                encoding="utf-8",
            )
            _write_runtime_json(
                task_root / "watchdog_retry_last_message.json",
                {"text": watchdog_retry_run_result.response_text},
            )
            _write_runtime_json(
                task_root / "watchdog_retry_usage.json",
                dict(watchdog_retry_run_result.usage or {}),
            )
            _write_runtime_json(
                task_root / "watchdog_retry_workspace_manifest.json",
                watchdog_retry_run_result.workspace_manifest(),
            )
            watchdog_retry_runner_payload = _build_line_role_inline_attempt_runner_payload(
                pipeline_id=pipeline_id,
                worker_id=assignment.worker_id,
                shard_id=parent_shard_id,
                run_result=watchdog_retry_run_result,
                model=model,
                reasoning_effort=reasoning_effort,
                prompt_input_mode="inline_watchdog_retry",
            )
            watchdog_retry_runner_payload["process_payload"]["runtime_task_id"] = (
                task_manifest.shard_id
            )
            watchdog_retry_runner_payload["process_payload"]["runtime_parent_shard_id"] = (
                parent_shard_id
            )
            worker_runner_results.append(dict(watchdog_retry_runner_payload))
            watchdog_retry_telemetry = watchdog_retry_runner_payload.get("telemetry")
            watchdog_retry_row_payloads = (
                watchdog_retry_telemetry.get("rows")
                if isinstance(watchdog_retry_telemetry, dict)
                else None
            )
            watchdog_retry_primary_row = None
            if isinstance(watchdog_retry_row_payloads, list):
                for row_payload in watchdog_retry_row_payloads:
                    if isinstance(row_payload, dict):
                        stage_rows.append(dict(row_payload))
                if stage_rows:
                    watchdog_retry_primary_row = stage_rows[-1]
            watchdog_retry_primary_runner_row = (
                watchdog_retry_row_payloads[0]
                if isinstance(watchdog_retry_row_payloads, list)
                and watchdog_retry_row_payloads
                and isinstance(watchdog_retry_row_payloads[0], dict)
                else None
            )
            watchdog_retry_payload, watchdog_retry_validation_errors, watchdog_retry_validation_metadata, watchdog_retry_proposal_status = (
                _evaluate_line_role_response_with_pathology_guard(
                    shard=task_manifest,
                    response_text=watchdog_retry_run_result.response_text,
                    validator=validator,
                    deterministic_baseline_by_atomic_index=dict(
                        deterministic_baseline_by_shard_id.get(parent_shard_id) or {}
                    ),
                )
            )
            watchdog_retry_status = (
                "recovered"
                if watchdog_retry_payload is not None
                and watchdog_retry_proposal_status == "validated"
                else "failed"
            )
            task_watchdog_retry_status_by_shard_id.setdefault(parent_shard_id, {})[
                task_manifest.shard_id
            ] = watchdog_retry_status
            _write_runtime_json(
                task_root / "watchdog_retry_status.json",
                {
                    "status": watchdog_retry_proposal_status,
                    "watchdog_retry_status": watchdog_retry_status,
                    "watchdog_retry_reason_code": str(
                        session_run_result.supervision_reason_code or ""
                    ),
                    "watchdog_retry_reason_detail": str(
                        session_run_result.supervision_reason_detail or ""
                    ),
                    "retry_validation_errors": list(watchdog_retry_validation_errors),
                    "retry_validation_metadata": dict(
                        watchdog_retry_validation_metadata or {}
                    ),
                    "state": watchdog_retry_run_result.supervision_state or "completed",
                    "reason_code": watchdog_retry_run_result.supervision_reason_code,
                    "reason_detail": watchdog_retry_run_result.supervision_reason_detail,
                    "retryable": watchdog_retry_run_result.supervision_retryable,
                },
            )
            if watchdog_retry_primary_row is not None:
                watchdog_retry_primary_row["proposal_status"] = (
                    watchdog_retry_proposal_status
                )
                _annotate_line_role_final_proposal_status(
                    watchdog_retry_primary_row,
                    final_proposal_status=watchdog_retry_proposal_status,
                )
                watchdog_retry_primary_row["watchdog_retry_status"] = (
                    watchdog_retry_status
                )
                watchdog_retry_primary_row["runtime_task_id"] = task_manifest.shard_id
                watchdog_retry_primary_row["runtime_parent_shard_id"] = parent_shard_id
            if watchdog_retry_primary_runner_row is not None:
                watchdog_retry_primary_runner_row["proposal_status"] = (
                    watchdog_retry_proposal_status
                )
                _annotate_line_role_final_proposal_status(
                    watchdog_retry_primary_runner_row,
                    final_proposal_status=watchdog_retry_proposal_status,
                )
                watchdog_retry_primary_runner_row["watchdog_retry_status"] = (
                    watchdog_retry_status
                )
                watchdog_retry_primary_runner_row["runtime_task_id"] = (
                    task_manifest.shard_id
                )
                watchdog_retry_primary_runner_row["runtime_parent_shard_id"] = (
                    parent_shard_id
                )
            if (
                watchdog_retry_payload is not None
                and watchdog_retry_proposal_status == "validated"
            ):
                payload = watchdog_retry_payload
                final_validation_errors = tuple(watchdog_retry_validation_errors)
                final_validation_metadata = dict(
                    watchdog_retry_validation_metadata or {}
                )
                proposal_status = watchdog_retry_proposal_status
                if primary_row is not None:
                    _annotate_line_role_final_proposal_status(
                        primary_row,
                        final_proposal_status=proposal_status,
                    )
                if primary_runner_row is not None:
                    _annotate_line_role_final_proposal_status(
                        primary_runner_row,
                        final_proposal_status=proposal_status,
                    )
            else:
                final_validation_metadata = {
                    **(
                        dict(final_validation_metadata)
                        if isinstance(final_validation_metadata, Mapping)
                        else {}
                    ),
                    "watchdog_retry_validation_errors": list(
                        watchdog_retry_validation_errors
                    ),
                    "watchdog_retry_validation_metadata": dict(
                        watchdog_retry_validation_metadata or {}
                    ),
                }
        if (
            task.task_id in runnable_task_ids
            and _should_attempt_line_role_repair(
                proposal_status=proposal_status,
                validation_errors=validation_errors,
            )
        ):
            repair_attempted = True
            repair_live_status_path = task_root / "repair_live_status.json"
            repair_run_result = _run_line_role_repair_attempt(
                runner=runner,
                worker_root=worker_root,
                shard=task_manifest,
                env=env,
                output_schema_path=output_schema_path,
                model=model,
                reasoning_effort=reasoning_effort,
                original_response_text=str(response_text or ""),
                validation_errors=validation_errors,
                timeout_seconds=timeout_seconds,
                pipeline_id=pipeline_id,
                worker_id=assignment.worker_id,
                live_status_path=repair_live_status_path,
            )
            _finalize_live_status(
                repair_live_status_path,
                run_result=repair_run_result,
                watchdog_policy=_STRICT_JSON_WATCHDOG_POLICY,
            )
            (task_root / "repair_events.jsonl").write_text(
                _render_codex_events_jsonl(repair_run_result.events),
                encoding="utf-8",
            )
            _write_runtime_json(
                task_root / "repair_last_message.json",
                {"text": repair_run_result.response_text},
            )
            _write_runtime_json(
                task_root / "repair_usage.json",
                dict(repair_run_result.usage or {}),
            )
            _write_runtime_json(
                task_root / "repair_workspace_manifest.json",
                repair_run_result.workspace_manifest(),
            )
            repair_runner_payload = _build_line_role_inline_attempt_runner_payload(
                pipeline_id=pipeline_id,
                worker_id=assignment.worker_id,
                shard_id=parent_shard_id,
                run_result=repair_run_result,
                model=model,
                reasoning_effort=reasoning_effort,
                prompt_input_mode="inline_repair",
            )
            repair_runner_payload["process_payload"]["runtime_task_id"] = (
                task_manifest.shard_id
            )
            repair_runner_payload["process_payload"]["runtime_parent_shard_id"] = (
                parent_shard_id
            )
            worker_runner_results.append(dict(repair_runner_payload))
            repair_telemetry = repair_runner_payload.get("telemetry")
            repair_row_payloads = (
                repair_telemetry.get("rows")
                if isinstance(repair_telemetry, dict)
                else None
            )
            repair_primary_row = None
            if isinstance(repair_row_payloads, list):
                for row_payload in repair_row_payloads:
                    if isinstance(row_payload, dict):
                        stage_rows.append(dict(row_payload))
                if stage_rows:
                    repair_primary_row = stage_rows[-1]
            repair_primary_runner_row = (
                repair_row_payloads[0]
                if isinstance(repair_row_payloads, list)
                and repair_row_payloads
                and isinstance(repair_row_payloads[0], dict)
                else None
            )
            repair_payload, repair_validation_errors, repair_validation_metadata, repair_proposal_status = (
                _evaluate_line_role_response_with_pathology_guard(
                    shard=task_manifest,
                    response_text=repair_run_result.response_text,
                    validator=validator,
                    deterministic_baseline_by_atomic_index=dict(
                        deterministic_baseline_by_shard_id.get(parent_shard_id) or {}
                    ),
                )
            )
            repair_status = (
                "repaired"
                if repair_payload is not None and repair_proposal_status == "validated"
                else "failed"
            )
            final_validation_errors = tuple(repair_validation_errors)
            task_repair_status_by_shard_id.setdefault(parent_shard_id, {})[
                task_manifest.shard_id
            ] = repair_status
            task_repair_validation_errors_by_shard_id.setdefault(parent_shard_id, {})[
                task_manifest.shard_id
            ] = final_validation_errors
            _write_runtime_json(
                task_root / "repair_status.json",
                {
                    "status": repair_status,
                    "repair_validation_errors": list(final_validation_errors),
                    "repair_validation_metadata": dict(repair_validation_metadata or {}),
                    "state": repair_run_result.supervision_state or "completed",
                    "reason_code": repair_run_result.supervision_reason_code,
                    "reason_detail": repair_run_result.supervision_reason_detail,
                    "retryable": repair_run_result.supervision_retryable,
                },
            )
            if repair_primary_row is not None:
                repair_primary_row["proposal_status"] = repair_proposal_status
                _annotate_line_role_final_proposal_status(
                    repair_primary_row,
                    final_proposal_status=repair_proposal_status,
                )
                repair_primary_row["repair_status"] = repair_status
                repair_primary_row["runtime_task_id"] = task_manifest.shard_id
                repair_primary_row["runtime_parent_shard_id"] = parent_shard_id
            if repair_primary_runner_row is not None:
                repair_primary_runner_row["proposal_status"] = repair_proposal_status
                _annotate_line_role_final_proposal_status(
                    repair_primary_runner_row,
                    final_proposal_status=repair_proposal_status,
                )
                repair_primary_runner_row["repair_status"] = repair_status
                repair_primary_runner_row["runtime_task_id"] = task_manifest.shard_id
                repair_primary_runner_row["runtime_parent_shard_id"] = parent_shard_id
            if repair_payload is not None and repair_proposal_status == "validated":
                payload = repair_payload
                final_validation_metadata = dict(repair_validation_metadata or {})
                proposal_status = repair_proposal_status
                if primary_row is not None:
                    _annotate_line_role_final_proposal_status(
                        primary_row,
                        final_proposal_status=proposal_status,
                    )
                if primary_runner_row is not None:
                    _annotate_line_role_final_proposal_status(
                        primary_runner_row,
                        final_proposal_status=proposal_status,
                    )
            else:
                final_validation_metadata = {
                    **(
                        dict(final_validation_metadata)
                        if isinstance(final_validation_metadata, Mapping)
                        else {}
                    ),
                    "repair_validation_errors": list(final_validation_errors),
                    "repair_validation_metadata": dict(repair_validation_metadata or {}),
                }
        task_validation_errors_by_shard_id.setdefault(parent_shard_id, {})[
            task_manifest.shard_id
        ] = final_validation_errors
        if payload is not None and proposal_status == "validated":
            task_payloads_by_shard_id.setdefault(parent_shard_id, {})[
                task_manifest.shard_id
            ] = payload
        task_status_rows.append(
            _build_line_role_task_status_row(
                task_manifest=task_manifest,
                worker_id=assignment.worker_id,
                state=(
                    "repair_recovered"
                    if payload is not None
                    and proposal_status == "validated"
                    and repair_status == "repaired"
                    else (
                        "validated"
                        if payload is not None and proposal_status == "validated"
                        else (
                            "repair_failed"
                            if repair_attempted
                            else (
                                "missing_output"
                                if proposal_status == "missing_output"
                                else "invalid_output"
                            )
                        )
                    )
                ),
                last_attempt_type=(
                    "repair"
                    if repair_attempted
                    else (
                        "watchdog_retry"
                        if watchdog_retry_attempted
                        else (
                            "resume_existing_output"
                            if task_manifest.shard_id in resumed_output_path_by_task_id
                            and task.task_id not in runnable_task_ids
                            else "main_worker"
                        )
                    )
                ),
                output_path=response_source_path,
                validation_errors=final_validation_errors,
                validation_metadata=final_validation_metadata,
                repair_attempted=repair_attempted,
                repair_status=repair_status,
                resumed_from_existing_output=(
                    task_manifest.shard_id in resumed_output_path_by_task_id
                    and task.task_id not in runnable_task_ids
                ),
            )
        )

    for shard in assigned_shards:
        if shard.shard_id not in all_task_plans_by_shard_id:
            continue
        shard_root = shard_dir / shard.shard_id
        if session_run_result is None and not (shard_root / "live_status.json").exists():
            resumed = any(
                task.task_id in resumed_output_path_by_task_id
                for task in all_task_plans_by_shard_id.get(shard.shard_id, ())
            )
            _write_runtime_json(
                shard_root / "live_status.json",
                {
                    "state": "completed",
                    "reason_code": "resume_existing_outputs" if resumed else "no_tasks_assigned",
                    "reason_detail": (
                        "all canonical line-role packet outputs were already durable on disk"
                        if resumed
                        else "worker had no runnable canonical line-role packets"
                    ),
                    "retryable": False,
                    "watchdog_policy": "workspace_worker_v1",
                },
            )
        task_payloads = task_payloads_by_shard_id.get(shard.shard_id, {})
        task_errors = task_validation_errors_by_shard_id.get(shard.shard_id, {})
        task_watchdog_retry_statuses = task_watchdog_retry_status_by_shard_id.get(
            shard.shard_id, {}
        )
        task_repair_statuses = task_repair_status_by_shard_id.get(shard.shard_id, {})
        task_repair_errors = task_repair_validation_errors_by_shard_id.get(
            shard.shard_id, {}
        )
        payload, aggregation_metadata = _aggregate_line_role_task_payloads(
            shard=shard,
            task_payloads_by_task_id=task_payloads,
            task_validation_errors_by_task_id=task_errors,
            deterministic_baseline_by_atomic_index=dict(
                deterministic_baseline_by_shard_id.get(shard.shard_id) or {}
            ),
        )
        valid, validation_errors, validator_metadata = validator(shard, payload)
        validation_metadata = {
            "task_aggregation": aggregation_metadata,
            **(
                dict(validator_metadata or {})
                if isinstance(validator_metadata, Mapping)
                else {}
            ),
        }
        watchdog_retry_attempted = any(
            str(status).strip() != "not_attempted"
            for status in task_watchdog_retry_statuses.values()
        )
        watchdog_retry_status = (
            "recovered"
            if any(
                str(status).strip() == "recovered"
                for status in task_watchdog_retry_statuses.values()
            )
            else ("failed" if watchdog_retry_attempted else "not_attempted")
        )
        repair_attempted = any(
            str(status).strip() != "not_attempted"
            for status in task_repair_statuses.values()
        )
        repair_status = (
            "repaired"
            if any(
                str(status).strip() == "repaired"
                for status in task_repair_statuses.values()
            )
            else ("failed" if repair_attempted else "not_attempted")
        )
        repair_validation_errors = sorted(
            {
                str(error).strip()
                for errors in task_repair_errors.values()
                for error in errors
                if str(error).strip()
            }
        )
        if task_repair_statuses:
            validation_metadata["task_repair_status_by_task_id"] = {
                task_id: status
                for task_id, status in sorted(task_repair_statuses.items())
            }
        if task_watchdog_retry_statuses:
            validation_metadata["task_watchdog_retry_status_by_task_id"] = {
                task_id: status
                for task_id, status in sorted(task_watchdog_retry_statuses.items())
            }
        if repair_validation_errors:
            validation_metadata["repair_validation_errors"] = repair_validation_errors
        proposal_status = "validated" if valid else "invalid"
        resumed_from_existing_outputs = any(
            task.task_id in resumed_output_path_by_task_id
            for task in all_task_plans_by_shard_id.get(shard.shard_id, ())
        )
        normalized_outcome = _normalize_line_role_shard_outcome(
            run_result=session_run_result,
            proposal_status=proposal_status,
            watchdog_retry_status=watchdog_retry_status,
            repair_status=repair_status,
            resumed_from_existing_outputs=resumed_from_existing_outputs,
            aggregation_metadata=aggregation_metadata,
        )
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        _write_runtime_json(
            proposal_path,
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": payload if valid else None,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
                "watchdog_retry_attempted": watchdog_retry_attempted,
                "watchdog_retry_status": watchdog_retry_status,
                "repair_attempted": repair_attempted,
                "repair_status": repair_status,
            },
        )
        _write_runtime_json(
            shard_root / "proposal.json",
            payload
            if valid
            else {
                "error": proposal_status,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
            },
        )
        shard_state = normalized_outcome.get("state")
        shard_reason_code = normalized_outcome.get("reason_code")
        shard_reason_detail = normalized_outcome.get("reason_detail")
        shard_retryable = bool(normalized_outcome.get("retryable"))
        for row in stage_rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("task_id") or "").strip() != shard.shard_id:
                continue
            if str(row.get("prompt_input_mode") or "").strip() != "workspace_worker":
                continue
            _annotate_line_role_final_outcome_row(
                row,
                normalized_outcome=normalized_outcome,
            )
        for payload_row in worker_runner_results:
            if not isinstance(payload_row, dict):
                continue
            process_payload = payload_row.get("process_payload")
            if not isinstance(process_payload, Mapping):
                continue
            if str(process_payload.get("runtime_parent_shard_id") or "").strip() != shard.shard_id:
                continue
            if str(process_payload.get("prompt_input_mode") or "").strip() != "workspace_worker":
                continue
            _apply_line_role_final_outcome_to_runner_payload(
                payload_row,
                shard_id=shard.shard_id,
                normalized_outcome=normalized_outcome,
            )
        _write_runtime_json(
            shard_root / "status.json",
            {
                "status": proposal_status,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "watchdog_retry_attempted": watchdog_retry_attempted,
                "watchdog_retry_status": watchdog_retry_status,
                "repair_attempted": repair_attempted,
                "repair_status": repair_status,
                "finalization_path": normalized_outcome.get("finalization_path"),
                "state": shard_state,
                "reason_code": shard_reason_code,
                "reason_detail": shard_reason_detail,
                "retryable": shard_retryable,
                "raw_supervision_state": normalized_outcome.get("raw_supervision_state"),
                "raw_supervision_reason_code": normalized_outcome.get(
                    "raw_supervision_reason_code"
                ),
                "raw_supervision_reason_detail": normalized_outcome.get(
                    "raw_supervision_reason_detail"
                ),
                "raw_supervision_retryable": normalized_outcome.get(
                    "raw_supervision_retryable"
                ),
            },
        )
        shard_runner_rows = [
            dict(row)
            for row in stage_rows
            if str(row.get("task_id") or "").strip() == shard.shard_id
        ]
        shard_runner_payload = _aggregate_line_role_worker_runner_payload(
            pipeline_id=pipeline_id,
            worker_runs=[
                payload_row
                for payload_row in worker_runner_results
                if str(
                    (
                        (payload_row.get("process_payload") or {})
                        if isinstance(payload_row, dict)
                        else {}
                    ).get("runtime_parent_shard_id")
                    or ""
                ).strip()
                == shard.shard_id
            ],
        )
        shard_runner_payload["telemetry"] = {
            "rows": shard_runner_rows,
            "summary": _summarize_direct_rows(shard_runner_rows),
        }
        shard_runner_payload["response_text"] = json.dumps(payload, sort_keys=True)
        shard_runner_payload["subprocess_exit_code"] = (
            session_run_result.subprocess_exit_code if session_run_result is not None else 0
        )
        shard_runner_payload["turn_failed_message"] = (
            session_run_result.turn_failed_message if session_run_result is not None else None
        )
        shard_runner_payload["final_supervision_state"] = normalized_outcome.get("state")
        shard_runner_payload["final_supervision_reason_code"] = normalized_outcome.get(
            "reason_code"
        )
        shard_runner_payload["final_supervision_reason_detail"] = normalized_outcome.get(
            "reason_detail"
        )
        shard_runner_payload["final_supervision_retryable"] = normalized_outcome.get(
            "retryable"
        )
        shard_runner_payload["finalization_path"] = normalized_outcome.get(
            "finalization_path"
        )
        shard_runner_payload["raw_supervision_state"] = normalized_outcome.get(
            "raw_supervision_state"
        )
        shard_runner_payload["raw_supervision_reason_code"] = normalized_outcome.get(
            "raw_supervision_reason_code"
        )
        shard_runner_payload["raw_supervision_reason_detail"] = normalized_outcome.get(
            "raw_supervision_reason_detail"
        )
        shard_runner_payload["raw_supervision_retryable"] = normalized_outcome.get(
            "raw_supervision_retryable"
        )
        runner_results_by_shard_id[shard.shard_id] = shard_runner_payload
        if proposal_status != "validated" or shard_state != "completed":
            worker_failure_count += 1
            worker_failures.append(
                {
                    "worker_id": assignment.worker_id,
                    "shard_id": shard.shard_id,
                    "reason": (
                        _failure_reason_from_run_result(
                            run_result=session_run_result,
                            proposal_status=proposal_status,
                        )
                        if session_run_result is not None
                        else proposal_status
                    ),
                    "validation_errors": list(validation_errors),
                    "state": shard_state,
                    "reason_code": shard_reason_code,
                }
            )
        else:
            worker_proposal_count += 1
            if session_run_result is not None:
                cohort_watchdog_state.record_validated_result(
                    duration_ms=session_run_result.duration_ms,
                    example_payload=_build_line_role_watchdog_example(
                        shard=shard,
                        payload=payload,
                    ),
                )
        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status=proposal_status,
                proposal_path=_relative_runtime_path(run_root, proposal_path),
                payload=payload if valid else None,
                validation_errors=tuple(validation_errors),
                metadata=dict(validation_metadata or {}),
            )
        )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    worker_runner_payload = _aggregate_line_role_worker_runner_payload(
        pipeline_id=pipeline_id,
        worker_runs=worker_runner_results,
    )
    _write_runtime_json(worker_root / "status.json", worker_runner_payload)
    return _DirectLineRoleWorkerResult(
        report=WorkerExecutionReportV1(
            worker_id=assignment.worker_id,
            shard_ids=assignment.shard_ids,
            workspace_root=_relative_runtime_path(run_root, worker_root),
            status="ok" if worker_failure_count == 0 else "partial_failure",
            proposal_count=worker_proposal_count,
            failure_count=worker_failure_count,
            runtime_mode_audit={
                "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "status": "ok",
                "output_schema_enforced": False,
                "tool_affordances_requested": True,
            },
            runner_result=worker_runner_payload,
            metadata={
                "in_dir": _relative_runtime_path(run_root, in_dir),
                "debug_dir": _relative_runtime_path(run_root, debug_dir),
                "hints_dir": _relative_runtime_path(run_root, hints_dir),
                "out_dir": _relative_runtime_path(run_root, out_dir),
                "shards_dir": _relative_runtime_path(run_root, shard_dir),
                "log_dir": _relative_runtime_path(run_root, logs_dir),
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
        stage_rows=tuple(stage_rows),
        task_status_rows=tuple(task_status_rows),
        runner_results_by_shard_id=dict(runner_results_by_shard_id),
    )


def _run_line_role_direct_worker_assignment_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: dict[str, str],
    shard_by_id: dict[str, ShardManifestEntryV1],
    debug_payload_by_shard_id: Mapping[str, Any],
    deterministic_baseline_by_shard_id: Mapping[
        str, Mapping[int, CanonicalLineRolePrediction]
    ],
    runner: CodexExecRunner,
    pipeline_id: str,
    env: dict[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    timeout_seconds: int,
    cohort_watchdog_state: _LineRoleCohortWatchdogState,
    shard_completed_callback: Callable[..., None] | None,
    prompt_state: "_PromptArtifactState" | None,
    validator: Callable[[ShardManifestEntryV1, dict[str, Any]], tuple[bool, Sequence[str], dict[str, Any] | None]],
) -> _DirectLineRoleWorkerResult:
    worker_root = Path(assignment.workspace_root)
    in_dir = worker_root / "in"
    debug_dir = worker_root / "debug"
    hints_dir = worker_root / "hints"
    shard_dir = worker_root / "shards"
    logs_dir = worker_root / "logs"
    in_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)
    hints_dir.mkdir(parents=True, exist_ok=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    assigned_shards = [shard_by_id[shard_id] for shard_id in assignment.shard_ids]
    _write_runtime_json(
        worker_root / "assigned_shards.json",
        [_line_role_asdict(shard) for shard in assigned_shards],
    )
    return _run_line_role_workspace_worker_assignment_v1(
        run_root=run_root,
        assignment=assignment,
        artifacts=artifacts,
        assigned_shards=assigned_shards,
        worker_root=worker_root,
        in_dir=in_dir,
        debug_dir=debug_dir,
        hints_dir=hints_dir,
        shard_dir=shard_dir,
        logs_dir=logs_dir,
        debug_payload_by_shard_id=debug_payload_by_shard_id,
        deterministic_baseline_by_shard_id=deterministic_baseline_by_shard_id,
        runner=runner,
        pipeline_id=pipeline_id,
        env=env,
        model=model,
        reasoning_effort=reasoning_effort,
        output_schema_path=output_schema_path,
        timeout_seconds=timeout_seconds,
        cohort_watchdog_state=cohort_watchdog_state,
        shard_completed_callback=shard_completed_callback,
        prompt_state=prompt_state,
        validator=validator,
    )


def _run_line_role_direct_workers_v1(
    *,
    phase_key: str,
    pipeline_id: str,
    run_root: Path,
    shards: Sequence[ShardManifestEntryV1],
    debug_payload_by_shard_id: Mapping[str, Any],
    deterministic_baseline_by_shard_id: Mapping[
        str, Mapping[int, CanonicalLineRolePrediction]
    ],
    runner: CodexExecRunner,
    worker_count: int,
    env: dict[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    timeout_seconds: int,
    settings: dict[str, Any],
    runtime_metadata: dict[str, Any],
    progress_callback: Callable[[str], None] | None,
    prompt_state: "_PromptArtifactState" | None,
    validator: Callable[[ShardManifestEntryV1, dict[str, Any]], tuple[bool, Sequence[str], dict[str, Any] | None]],
) -> tuple[PhaseManifestV1, list[WorkerExecutionReportV1], dict[str, dict[str, Any]]]:
    artifacts = {
        "phase_manifest": "phase_manifest.json",
        "shard_manifest": "shard_manifest.jsonl",
        "task_manifest": "task_manifest.jsonl",
        "task_status": "task_status.jsonl",
        "canonical_line_table": "canonical_line_table.jsonl",
        "worker_assignments": "worker_assignments.json",
        "promotion_report": "promotion_report.json",
        "telemetry": "telemetry.json",
        "failures": "failures.json",
        "proposals_dir": "proposals",
    }
    run_root.mkdir(parents=True, exist_ok=True)
    shard_by_id = {shard.shard_id: shard for shard in shards}
    assignments = _assign_line_role_workers_v1(
        run_root=run_root,
        shards=shards,
        worker_count=worker_count,
    )
    task_plans_by_shard_id = {
        shard.shard_id: _build_line_role_task_plans(
            shard=shard,
            debug_payload=debug_payload_by_shard_id.get(shard.shard_id),
        )
        for shard in shards
    }
    _write_runtime_jsonl(
        run_root / artifacts["shard_manifest"],
        [_line_role_asdict(shard) for shard in shards],
    )
    _write_runtime_jsonl(
        run_root / artifacts["task_manifest"],
        [
            _line_role_asdict(_build_line_role_task_manifest_entry(task_plan))
            for shard in shards
            for task_plan in task_plans_by_shard_id.get(shard.shard_id, ())
        ],
    )
    _write_runtime_jsonl(
        run_root / artifacts["canonical_line_table"],
        _build_line_role_canonical_line_table_rows(
            debug_payload_by_shard_id=debug_payload_by_shard_id,
        ),
    )
    _write_runtime_json(
        run_root / artifacts["worker_assignments"],
        [_line_role_asdict(assignment) for assignment in assignments],
    )

    all_proposals: list[ShardProposalV1] = []
    failures: list[dict[str, Any]] = []
    worker_reports: list[WorkerExecutionReportV1] = []
    stage_rows: list[dict[str, Any]] = []
    task_status_rows: list[dict[str, Any]] = []
    runner_results_by_shard_id: dict[str, dict[str, Any]] = {}
    completed_shards = 0
    total_shards = len(shards)
    task_ids_by_worker: dict[str, tuple[str, ...]] = {
        assignment.worker_id: tuple(
            task_plan.task_id
            for shard_id in assignment.shard_ids
            for task_plan in task_plans_by_shard_id.get(shard_id, ())
        )
        for assignment in assignments
    }
    total_tasks = sum(len(task_ids) for task_ids in task_ids_by_worker.values())
    progress_lock = threading.Lock()
    cohort_watchdog_state = _LineRoleCohortWatchdogState()
    pending_shards_by_worker = {
        assignment.worker_id: list(assignment.shard_ids)
        for assignment in assignments
    }

    def _line_role_worker_followup_status(
        *,
        worker_id: str,
    ) -> tuple[int, int, int]:
        repair_attempted = 0
        repair_completed = 0
        repair_running = 0
        for task_id in task_ids_by_worker.get(worker_id, ()):
            task_root = run_root / "workers" / worker_id / "shards" / task_id
            repair_prompt_path = task_root / "repair_prompt.txt"
            repair_status_path = task_root / "repair_status.json"
            if repair_prompt_path.exists():
                repair_attempted += 1
            if repair_status_path.exists():
                repair_completed += 1
            elif repair_prompt_path.exists():
                repair_running += 1
        return repair_attempted, repair_completed, repair_running

    def _render_line_role_progress_label(
        *,
        worker_id: str,
        completed_task_ids: set[str],
    ) -> str | None:
        worker_task_ids = task_ids_by_worker.get(worker_id, ())
        if not worker_task_ids:
            return None
        completed_worker_tasks = sum(
            1 for task_id in worker_task_ids if task_id in completed_task_ids
        )
        if completed_worker_tasks >= len(worker_task_ids):
            return None
        pending_shards = pending_shards_by_worker.get(worker_id) or []
        base_label = str((pending_shards[0] if pending_shards else worker_task_ids[0]) or "").strip() or worker_id
        extra_shard_count = max(0, len(pending_shards) - 1)
        if extra_shard_count > 0:
            base_label = f"{base_label} +{extra_shard_count} more"
        return f"{base_label} ({completed_worker_tasks}/{len(worker_task_ids)} task packets)"

    def _emit_progress_locked(*, force: bool = False) -> None:
        completed_task_ids: set[str] = set()
        for assignment in assignments:
            out_dir = run_root / "workers" / assignment.worker_id / "out"
            if not out_dir.exists():
                continue
            for output_path in out_dir.glob("*.json"):
                completed_task_ids.add(output_path.stem)
        completed_tasks = min(total_tasks, len(completed_task_ids))
        active_tasks = [
            label
            for assignment in assignments
            for label in [
                _render_line_role_progress_label(
                    worker_id=assignment.worker_id,
                    completed_task_ids=completed_task_ids,
                )
            ]
            if label is not None
        ]
        running_workers = len(active_tasks)
        completed_workers = max(0, len(assignments) - running_workers)
        repair_attempted = 0
        repair_completed = 0
        repair_running = 0
        finalize_workers = 0
        proposals_dir = run_root / artifacts["proposals_dir"]
        proposal_count = len(list(proposals_dir.glob("*.json"))) if proposals_dir.exists() else 0
        for assignment in assignments:
            worker_repair_attempted, worker_repair_completed, worker_repair_running = (
                _line_role_worker_followup_status(worker_id=assignment.worker_id)
            )
            repair_attempted += worker_repair_attempted
            repair_completed += worker_repair_completed
            repair_running += worker_repair_running
            if not any(
                task_id not in completed_task_ids
                for task_id in task_ids_by_worker.get(assignment.worker_id, ())
            ) and (pending_shards_by_worker.get(assignment.worker_id) or []):
                finalize_workers += 1
        snapshot = (
            completed_tasks,
            total_tasks,
            completed_shards,
            total_shards,
            running_workers,
            completed_workers,
            repair_attempted,
            repair_completed,
            repair_running,
            finalize_workers,
            proposal_count,
            tuple(active_tasks),
        )
        if not force and snapshot == getattr(_emit_progress_locked, "_last_snapshot", None):
            return
        setattr(_emit_progress_locked, "_last_snapshot", snapshot)
        _notify_line_role_progress(
            progress_callback=progress_callback,
            completed_tasks=completed_tasks,
            total_tasks=total_tasks,
            running_tasks=running_workers,
            worker_total=worker_count,
            worker_running=running_workers,
            worker_completed=completed_workers,
            worker_failed=0,
            followup_running=finalize_workers + repair_running,
            followup_completed=completed_shards,
            followup_total=total_shards,
            followup_label="shard finalization",
            artifact_counts={
                "proposal_count": proposal_count,
                "repair_attempted": repair_attempted,
                "repair_completed": repair_completed,
                "repair_running": repair_running,
                "shards_completed": completed_shards,
                "shards_total": total_shards,
            },
            active_tasks=active_tasks,
        )

    def _mark_shard_completed(*, worker_id: str, shard_id: str) -> None:
        nonlocal completed_shards
        with progress_lock:
            pending = pending_shards_by_worker.get(worker_id) or []
            if shard_id in pending:
                pending.remove(shard_id)
            completed_shards += 1
            _emit_progress_locked()

    if progress_callback is not None and total_tasks > 0:
        _emit_progress_locked(force=True)

    with ThreadPoolExecutor(
        max_workers=max(1, len(assignments)),
        thread_name_prefix="line-role-worker",
    ) as executor:
        futures_by_worker_id = {
            assignment.worker_id: executor.submit(
                _run_line_role_direct_worker_assignment_v1,
                run_root=run_root,
                assignment=assignment,
                artifacts=artifacts,
                shard_by_id=shard_by_id,
                debug_payload_by_shard_id=debug_payload_by_shard_id,
                deterministic_baseline_by_shard_id=deterministic_baseline_by_shard_id,
                runner=runner,
                pipeline_id=pipeline_id,
                env=env,
                model=model,
                reasoning_effort=reasoning_effort,
                output_schema_path=output_schema_path,
                timeout_seconds=timeout_seconds,
                cohort_watchdog_state=cohort_watchdog_state,
                shard_completed_callback=_mark_shard_completed,
                prompt_state=prompt_state,
                validator=validator,
            )
            for assignment in assignments
        }
        for assignment in assignments:
            result = futures_by_worker_id[assignment.worker_id].result()
            worker_reports.append(result.report)
            all_proposals.extend(result.proposals)
            failures.extend(result.failures)
            stage_rows.extend(result.stage_rows)
            task_status_rows.extend(result.task_status_rows)
            runner_results_by_shard_id.update(result.runner_results_by_shard_id)

    _write_runtime_jsonl(run_root / artifacts["task_status"], task_status_rows)

    llm_authoritative_row_count = sum(
        int(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("llm_authoritative_row_count") or 0)
        for row in task_status_rows
        if isinstance(row, dict)
    )
    fallback_row_count = sum(
        int(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("fallback_row_count") or 0)
        for row in task_status_rows
        if isinstance(row, dict)
    )
    suspicious_packet_count = sum(
        1
        for row in task_status_rows
        if bool(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("suspicious_packet"))
    )
    suspicious_row_count = sum(
        int(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("suspicious_row_count") or 0)
        for row in task_status_rows
        if isinstance(row, dict)
    )

    promotion_report = {
        "schema_version": "phase_worker_runtime.promotion_report.v1",
        "phase_key": phase_key,
        "pipeline_id": pipeline_id,
        "validated_shards": sum(1 for proposal in all_proposals if proposal.status == "validated"),
        "invalid_shards": sum(1 for proposal in all_proposals if proposal.status == "invalid"),
        "missing_output_shards": sum(
            1 for proposal in all_proposals if proposal.status == "missing_output"
        ),
        "task_state_counts": {
            state: sum(
                1
                for row in task_status_rows
                if str((row.get("state") if isinstance(row, dict) else "") or "").strip() == state
            )
            for state in sorted(
                {
                    str((row.get("state") if isinstance(row, dict) else "") or "").strip()
                    for row in task_status_rows
                    if str((row.get("state") if isinstance(row, dict) else "") or "").strip()
                }
            )
        },
        "llm_authoritative_row_count": llm_authoritative_row_count,
        "fallback_row_count": fallback_row_count,
        "suspicious_packet_count": suspicious_packet_count,
        "suspicious_row_count": suspicious_row_count,
    }
    telemetry = {
        "schema_version": "phase_worker_runtime.telemetry.v1",
        "phase_key": phase_key,
        "pipeline_id": pipeline_id,
        "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        "worker_count": len(assignments),
        "shard_count": len(shards),
        "proposal_count": sum(report.proposal_count for report in worker_reports),
        "failure_count": len(failures),
        "fresh_agent_count": len(assignments),
        "rows": stage_rows,
        "summary": _summarize_direct_rows(stage_rows),
    }
    _write_runtime_json(run_root / artifacts["promotion_report"], promotion_report)
    _write_runtime_json(run_root / artifacts["telemetry"], telemetry)
    _write_runtime_json(run_root / artifacts["failures"], failures)

    manifest = PhaseManifestV1(
        schema_version="phase_worker_runtime.phase_manifest.v1",
        phase_key=phase_key,
        pipeline_id=pipeline_id,
        run_root=str(run_root),
        worker_count=len(assignments),
        shard_count=len(shards),
        assignment_strategy="round_robin_v1",
        runtime_mode=DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        max_turns_per_shard=1,
        settings=dict(settings or {}),
        artifact_paths=dict(artifacts),
        runtime_metadata=dict(runtime_metadata or {}),
    )
    _write_runtime_json(run_root / artifacts["phase_manifest"], _line_role_asdict(manifest))
    return manifest, worker_reports, runner_results_by_shard_id


def _assign_line_role_workers_v1(
    *,
    run_root: Path,
    shards: Sequence[ShardManifestEntryV1],
    worker_count: int,
) -> list[WorkerAssignmentV1]:
    effective_workers = resolve_phase_worker_count(
        requested_worker_count=worker_count,
        shard_count=len(shards),
    )
    buckets: list[list[str]] = [[] for _ in range(effective_workers)]
    for index, shard in enumerate(shards):
        buckets[index % effective_workers].append(shard.shard_id)
    return [
        WorkerAssignmentV1(
            worker_id=f"worker-{index + 1:03d}",
            shard_ids=tuple(bucket),
            workspace_root=str(run_root / "workers" / f"worker-{index + 1:03d}"),
        )
        for index, bucket in enumerate(buckets)
    ]


def _build_line_role_runner_payload(
    *,
    pipeline_id: str,
    worker_id: str,
    shard_id: str,
    run_result: CodexExecRunResult,
    model: str | None,
    reasoning_effort: str | None,
    request_input_file: Path | None,
    debug_input_file: Path | None,
) -> dict[str, Any]:
    payload = run_result.to_payload(worker_id=worker_id, shard_id=shard_id)
    payload["pipeline_id"] = pipeline_id
    request_input_file_str = (
        str(request_input_file)
        if request_input_file is not None
        else None
    )
    request_input_file_bytes = (
        request_input_file.stat().st_size
        if request_input_file is not None and request_input_file.exists()
        else None
    )
    debug_input_file_str = (
        str(debug_input_file)
        if debug_input_file is not None
        else None
    )
    telemetry = payload.get("telemetry")
    row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
    if isinstance(row_payloads, list):
        for row_payload in row_payloads:
            if not isinstance(row_payload, dict):
                continue
            row_payload["prompt_input_mode"] = "inline"
            row_payload["request_input_file"] = request_input_file_str
            row_payload["request_input_file_bytes"] = request_input_file_bytes
            row_payload["debug_input_file"] = debug_input_file_str
    summary_payload = telemetry.get("summary") if isinstance(telemetry, dict) else None
    if isinstance(summary_payload, dict):
        summary_payload["prompt_input_mode"] = "inline"
        summary_payload["request_input_file_bytes_total"] = request_input_file_bytes
    payload["process_payload"] = {
        "pipeline_id": pipeline_id,
        "status": "done" if run_result.subprocess_exit_code == 0 else "failed",
        "codex_model": model,
        "codex_reasoning_effort": reasoning_effort,
        "prompt_input_mode": "inline",
        "request_input_file": request_input_file_str,
        "request_input_file_bytes": request_input_file_bytes,
        "debug_input_file": debug_input_file_str,
    }
    return payload


def _build_line_role_file_prompt_for_shard(
    *,
    input_path: Path,
    input_payload: Mapping[str, Any] | None,
) -> str:
    return build_canonical_line_role_file_prompt(
        input_path=input_path,
        input_payload=input_payload,
    )


def _build_line_role_workspace_worker_prompt(
    *,
    tasks: Sequence[TaskManifestEntryV1],
) -> str:
    assignments = "\n".join(
        f"- `{task.task_id}`: read `hints/{task.task_id}.md`, then `in/{task.task_id}.json`, then write `out/{task.task_id}.json`"
        for task in tasks
    )
    return (
        "You are processing many canonical line-role task packets inside one local worker workspace.\n\n"
        "Worker contract:\n"
        "- The current working directory is already the workspace root.\n"
        "- Start by opening `worker_manifest.json`, then `current_task.json`, then `OUTPUT_CONTRACT.md`.\n"
        "- The normal path is repo-written already: open `hints/<task_id>.md`, `in/<task_id>.json`, and the `metadata.scratch_draft_path` named in `current_task.json`; edit that prewritten draft only where the deterministic seed is wrong; then run `python3 tools/line_role_worker.py finalize <draft_path>`.\n"
        "- If several prewritten drafts are ready, `python3 tools/line_role_worker.py finalize-all scratch/` is the preferred bulk completion path.\n"
        "- If `tools/line_role_worker.py` exists, use it as the paved road before inventing ad hoc shell helpers.\n"
        "- `python3 tools/line_role_worker.py overview`, `show <task_id>`, `check <json_path>`, `prepare-all --dest-dir scratch/`, and `scaffold <task_id> --dest scratch/<task_id>.json` are fallback/debug tools, not the default starting path.\n"
        "- Long handwritten `jq` transforms are unnecessary here because the helper can already expand the deterministic label codes into the correct output shape.\n"
        "- Prefer opening the named files directly. If you still need shell helpers, keep them narrow and grounded on the named local files only.\n"
        "- Stay inside this workspace: do not inspect parent directories or the repository, keep every visible path local, and do not use repo/network/package-manager commands such as `git`, `curl`, or `npm`.\n"
        "- Treat `current_task.json` as the cheapest repo-written next task row. Open its named files first.\n"
        "- Use `assigned_tasks.json` for the ordered queue and `assigned_shards.json` only for shard ownership context.\n"
        "- For each assigned task, open `hints/<task_id>.md` first, then open `in/<task_id>.json`.\n"
        "- Treat `hints/<task_id>.md` as guidance and `in/<task_id>.json` as the authoritative task packet for that worker step.\n"
        "- Treat each packet's deterministic label code as a strong prior. Make the smallest safe correction rather than hunting for novelty.\n"
        "- If `OUTPUT_CONTRACT.md` or `examples/` exists, use those repo-written files as the authoritative output-shape reference.\n"
        "- If `examples/*.md` exists, use those contrast examples for calibration only; do not copy them into outputs.\n"
        "- Write exactly one JSON object to `out/<task_id>.json`.\n"
        "- If `out/<task_id>.json` already exists and is complete, leave it alone and continue.\n"
        "- Do not modify files under `in/`, `debug/`, or `hints/`.\n"
        "- Stay inside this workspace; do not inspect parent directories or the repository.\n"
        "- Keep working through the assigned task files until all of them are handled or you truly cannot proceed.\n\n"
        "Each task input file has this shape:\n"
        '{"v":1,"shard_id":"line-role-canonical-0001-a000123-a000456.task-001","parent_shard_id":"line-role-canonical-0001-a000123-a000456","context_before_rows":[[120,"Earlier row"],[121,"More context"]],"rows":[[123,"L4","1 cup flour"]],"context_after_rows":[[124,"Later row"],[125,"More later context"]]}\n\n'
        "Each output file must have this shape:\n"
        '{"rows":[{"atomic_index":123,"label":"INGREDIENT_LINE"}]}\n\n'
        "Rules:\n"
        "- Use only the keys `rows`, `atomic_index`, and `label` in each output file.\n"
        "- `context_before_rows` and `context_after_rows` are reference-only neighboring rows. Read them if helpful, but never emit labels for them.\n"
        "- Return one result for every owned input row in `rows`, in the same order.\n"
        "- Convert `label_code` into the correct full label string. The helper scaffold already does this deterministically.\n"
        "- `INGREDIENT_LINE`: quantity/unit ingredients and bare ingredient items in ingredient lists.\n"
        "- `INSTRUCTION_LINE`: recipe-local imperative action sentences, even when they include time.\n"
        "- `TIME_LINE`: stand-alone timing or temperature lines, not full instruction sentences.\n"
        "- `HOWTO_SECTION`: recipe-internal subsection headings such as `FOR THE SAUCE`, `TO FINISH`, or `FOR SERVING`.\n"
        "- `HOWTO_SECTION` is book-optional: some books legitimately use zero of them, so emit it only with immediate recipe-local support.\n"
        "- `RECIPE_VARIANT`: alternate recipe names or variant headers inside a recipe.\n"
        "- `KNOWLEDGE`: explanatory or reference prose, not ordinary recipe structure.\n"
        "- `OTHER`: navigation, memoir, marketing, dedications, table of contents, or decorative matter.\n"
        "- Never label a quantity ingredient line as `KNOWLEDGE`.\n"
        "- Never label an imperative recipe step as `KNOWLEDGE`.\n"
        "- Do not use `INSTRUCTION_LINE` for generic culinary advice or cookbook teaching prose.\n"
        "- Generic cooking advice that spans many dishes belongs in `KNOWLEDGE` or `OTHER`, not `INSTRUCTION_LINE`.\n"
        "- Do not use `HOWTO_SECTION` for chapter, topic, or cookbook-lesson headings such as `Salt and Pepper`, `Cooking Acids`, or `Starches`.\n"
        "- A heading by itself is weak evidence. Keep topic headings such as `Balancing Fat` or `WHAT IS ACID?` as `KNOWLEDGE` when nearby rows are explanatory prose.\n"
        "- First-person narrative or memoir prose is usually `OTHER`, not recipe structure.\n\n"
        "Do not return task labels in your final message. The authoritative results are the `out/<task_id>.json` files.\n\n"
        "Assigned task files:\n"
        f"{assignments}\n"
    )


def _write_line_role_worker_examples(*, worker_root: Path) -> list[str]:
    examples_dir = worker_root / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[str] = []
    for filename, content in (
        *_LINE_ROLE_PACKET_EXAMPLE_FILES,
        *_LINE_ROLE_OUTPUT_EXAMPLE_FILES,
    ):
        (examples_dir / filename).write_text(content, encoding="utf-8")
        written_files.append(filename)
    return written_files


def _write_line_role_output_contract(*, worker_root: Path) -> None:
    (worker_root / "OUTPUT_CONTRACT.md").write_text(
        LINE_ROLE_OUTPUT_CONTRACT_MARKDOWN,
        encoding="utf-8",
    )


def _write_line_role_worker_tools(*, worker_root: Path) -> list[str]:
    tools_dir = worker_root / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    tool_path = tools_dir / LINE_ROLE_WORKER_TOOL_FILENAME
    tool_path.write_text(render_line_role_worker_script(), encoding="utf-8")
    return [LINE_ROLE_WORKER_TOOL_FILENAME]


def _write_line_role_worker_hint(
    *,
    path: Path,
    shard: ShardManifestEntryV1,
    debug_payload: Any,
) -> None:
    input_rows = list(_coerce_mapping_dict(shard.input_payload).get("rows") or [])
    debug_rows = list(_coerce_mapping_dict(debug_payload).get("rows") or [])
    input_row_by_atomic_index: dict[int, tuple[str, str, str]] = {}
    ordered_atomic_indices: list[int] = []
    code_by_label = build_line_role_label_code_by_label()
    label_by_code = {str(code): str(label) for label, code in code_by_label.items()}
    for row in input_rows:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        try:
            atomic_index = int(row[0])
        except (TypeError, ValueError):
            continue
        input_row_by_atomic_index[atomic_index] = (
            atomic_index,
            str(row[1]),
            str(row[2]),
        )
        ordered_atomic_indices.append(atomic_index)
    order_lookup = {atomic_index: idx for idx, atomic_index in enumerate(ordered_atomic_indices)}

    label_counts: dict[str, int] = {}
    flagged_count = 0
    span_inside = 0
    span_outside = 0
    span_unknown = 0
    attention_lines: list[str] = []
    packet_context = _build_line_role_packet_context(rows=debug_rows)
    for row in debug_rows:
        if not isinstance(row, Mapping):
            continue
        try:
            atomic_index = int(row.get("atomic_index"))
        except (TypeError, ValueError):
            continue
        deterministic_label = str(row.get("deterministic_label") or "OTHER").strip() or "OTHER"
        label_counts[deterministic_label] = label_counts.get(deterministic_label, 0) + 1
        within_recipe_span = row.get("within_recipe_span")
        if within_recipe_span is True:
            span_inside += 1
        elif within_recipe_span is False:
            span_outside += 1
        else:
            span_unknown += 1
        rule_tags = [
            str(tag).strip()
            for tag in row.get("rule_tags") or []
            if str(tag).strip()
        ]
        escalation_reasons = [
            str(reason).strip()
            for reason in row.get("escalation_reasons") or []
            if str(reason).strip()
        ]
        if escalation_reasons or rule_tags:
            flagged_count += 1
        if len(attention_lines) >= 12 or (not escalation_reasons and not rule_tags):
            continue
        current_line = str(row.get("current_line") or "").strip()
        input_code = input_row_by_atomic_index.get(atomic_index, ("", "", ""))[1]
        packet_index = order_lookup.get(atomic_index)
        prev_line = "[start]"
        next_line = "[end]"
        if packet_index is not None:
            if packet_index > 0:
                prev_atomic_index = ordered_atomic_indices[packet_index - 1]
                prev_line = input_row_by_atomic_index.get(prev_atomic_index, ("", "", ""))[2]
            if packet_index < (len(ordered_atomic_indices) - 1):
                next_atomic_index = ordered_atomic_indices[packet_index + 1]
                next_line = input_row_by_atomic_index.get(next_atomic_index, ("", "", ""))[2]
        attention_lines.append(
            f"`{atomic_index}` `{preview_text(current_line, max_chars=90)}` -> deterministic `{deterministic_label}`, input code `{input_code}` ({label_by_code.get(input_code, 'unknown')}), tags `{', '.join(rule_tags) or 'none'}`, escalation `{', '.join(escalation_reasons) or 'none'}`, prev `{preview_text(prev_line, max_chars=60)}`, next `{preview_text(next_line, max_chars=60)}`"
        )

    packet_profile = [
        f"Owned rows: {len(input_row_by_atomic_index)}.",
        f"Deterministic label mix: {', '.join(f'{label}={count}' for label, count in sorted(label_counts.items())) or 'none'}.",
        f"Rows with rule tags or escalation reasons: {flagged_count}.",
        f"Recipe-span status mix: inside={span_inside}, outside={span_outside}, unknown={span_unknown}.",
        "Use this file to decode compact rows quickly, then rely on `in/<shard_id>.json` for the full owned row list.",
    ]
    legend_lines = [
        f"`{code}` = `{label}`"
        for label, code in sorted(code_by_label.items(), key=lambda item: item[1])
    ]
    packet_interpretation = [
        str(packet_context.get("packet_summary") or "No packet summary available."),
        (
            "Confidence: "
            f"{str(packet_context.get('context_confidence') or 'low')}. "
            f"Packet mode: {str(packet_context.get('packet_mode') or 'mixed_boundaries')}."
        ),
        str(packet_context.get("default_posture") or "Make conservative packet-local corrections."),
    ]
    decision_policy = list(packet_context.get("flip_policy") or [])
    decision_policy.extend(
        f"Strong signal: {value}"
        for value in list(packet_context.get("strong_signals") or [])
    )
    decision_policy.extend(
        f"Weak signal: {value}"
        for value in list(packet_context.get("weak_signals") or [])
    )
    packet_examples = [
        f"`examples/{filename}`"
        for filename in list(packet_context.get("example_files") or [])
    ] or ["Worker-local examples are not available for this packet."]
    if not attention_lines:
        attention_lines = [
            "No special attention rows were flagged. Read the authoritative rows in order and use nearby neighbors for disambiguation."
        ]
    write_worker_hint_markdown(
        path,
        title=f"Canonical line-role hints for {shard.shard_id}",
        summary_lines=[
            "This sidecar is worker guidance only.",
            "Open this file first, then open the authoritative `in/<shard_id>.json` file.",
            "Use nearby rows to disambiguate front matter, lesson prose, headings, and recipe-local structure.",
        ],
        sections=[
            ("Packet profile", packet_profile),
            ("Packet interpretation", packet_interpretation),
            ("Decision policy", decision_policy),
            ("Packet examples", packet_examples),
            ("Label code legend", legend_lines),
            ("Attention rows", attention_lines),
        ],
    )


def _distribute_line_role_session_value(total: int | None, parts: int) -> list[int]:
    normalized_parts = max(1, int(parts))
    normalized_total = max(0, int(total or 0))
    base, remainder = divmod(normalized_total, normalized_parts)
    return [base + (1 if index < remainder else 0) for index in range(normalized_parts)]


def _build_line_role_workspace_task_runner_payload(
    *,
    pipeline_id: str,
    worker_id: str,
    shard_id: str,
    runtime_task_id: str,
    run_result: CodexExecRunResult,
    model: str | None,
    reasoning_effort: str | None,
    request_input_file: Path | None,
    debug_input_file: Path | None,
    worker_prompt_path: Path | None,
    task_count: int,
    task_index: int,
) -> dict[str, Any]:
    payload = run_result.to_payload(worker_id=worker_id, shard_id=shard_id)
    payload["pipeline_id"] = pipeline_id
    request_input_file_str = str(request_input_file) if request_input_file is not None else None
    request_input_file_bytes = (
        request_input_file.stat().st_size
        if request_input_file is not None and request_input_file.exists()
        else None
    )
    debug_input_file_str = str(debug_input_file) if debug_input_file is not None else None
    worker_prompt_file_str = str(worker_prompt_path) if worker_prompt_path is not None else None
    telemetry = payload.get("telemetry")
    row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
    if isinstance(row_payloads, list) and row_payloads and isinstance(row_payloads[0], dict):
        row_payload = dict(row_payloads[0])
        share_fields = (
            "duration_ms",
            "tokens_input",
            "tokens_cached_input",
            "tokens_output",
            "tokens_reasoning",
            "visible_input_tokens",
            "visible_output_tokens",
            "wrapper_overhead_tokens",
        )
        for field_name in share_fields:
            shares = _distribute_line_role_session_value(row_payload.get(field_name), task_count)
            row_payload[field_name] = shares[task_index]
        row_payload["tokens_total"] = (
            int(row_payload.get("tokens_input") or 0)
            + int(row_payload.get("tokens_cached_input") or 0)
            + int(row_payload.get("tokens_output") or 0)
            + int(row_payload.get("tokens_reasoning") or 0)
        )
        row_payload["prompt_input_mode"] = "workspace_worker"
        row_payload["runtime_task_id"] = runtime_task_id
        row_payload["runtime_parent_shard_id"] = shard_id
        row_payload["request_input_file"] = request_input_file_str
        row_payload["request_input_file_bytes"] = request_input_file_bytes
        row_payload["debug_input_file"] = debug_input_file_str
        row_payload["worker_prompt_file"] = worker_prompt_file_str
        row_payload["worker_session_task_count"] = task_count
        row_payload["worker_session_primary_row"] = task_index == 0
        row_payload["command_execution_policy_counts"] = _line_role_command_policy_counts(
            row_payload.get("command_execution_commands")
        )
        row_payload["command_execution_policy_by_command"] = _line_role_command_policy_by_command(
            row_payload.get("command_execution_commands")
        )
        if task_index > 0:
            row_payload["command_execution_count"] = 0
            row_payload["command_execution_commands"] = []
            row_payload["command_execution_policy_counts"] = {}
            row_payload["command_execution_policy_by_command"] = []
            row_payload["reasoning_item_count"] = 0
            row_payload["reasoning_item_types"] = []
            row_payload["codex_event_count"] = 0
            row_payload["codex_event_types"] = []
            row_payload["output_preview"] = None
            row_payload["output_preview_chars"] = 0
        telemetry["rows"] = [row_payload]
        telemetry["summary"] = _summarize_direct_rows([row_payload])
    payload["process_payload"] = {
        "pipeline_id": pipeline_id,
        "status": "done" if run_result.subprocess_exit_code == 0 else "failed",
        "codex_model": model,
        "codex_reasoning_effort": reasoning_effort,
        "prompt_input_mode": "workspace_worker",
        "runtime_task_id": runtime_task_id,
        "runtime_parent_shard_id": shard_id,
        "request_input_file": request_input_file_str,
        "request_input_file_bytes": request_input_file_bytes,
        "debug_input_file": debug_input_file_str,
        "worker_prompt_file": worker_prompt_file_str,
    }
    return payload


def _line_role_command_policy_by_command(value: Any) -> list[dict[str, Any]]:
    commands = value if isinstance(value, list) else []
    rows: list[dict[str, Any]] = []
    for command in commands:
        command_text = str(command or "").strip()
        if not command_text:
            continue
        verdict = _classify_line_role_workspace_command(command_text)
        rows.append(
            {
                "command": command_text,
                "allowed": verdict.allowed,
                "policy": verdict.policy,
                "reason": verdict.reason,
            }
        )
    return rows


def _line_role_command_policy_counts(value: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in _line_role_command_policy_by_command(value):
        policy = str(row.get("policy") or "").strip()
        if not policy:
            continue
        counts[policy] = int(counts.get(policy) or 0) + 1
    return dict(sorted(counts.items()))


def _aggregate_line_role_worker_runner_payload(
    *,
    pipeline_id: str,
    worker_runs: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for worker_run in worker_runs:
        telemetry = worker_run.get("telemetry")
        worker_rows = telemetry.get("rows") if isinstance(telemetry, dict) else None
        if isinstance(worker_rows, list):
            rows.extend(
                dict(row_payload)
                for row_payload in worker_rows
                if isinstance(row_payload, dict)
            )
    uses_workspace_worker = any(
        str(
            ((payload.get("process_payload") or {}) if isinstance(payload, dict) else {}).get(
                "prompt_input_mode"
            )
            or ""
        ).strip()
        == "workspace_worker"
        for payload in worker_runs
        if isinstance(payload, dict)
    )
    return {
        "runner_kind": "codex_exec_direct",
        "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        "pipeline_id": pipeline_id,
        "worker_runs": [dict(payload) for payload in worker_runs],
        "telemetry": {
            "rows": rows,
            "summary": _summarize_direct_rows(rows),
        },
        "runtime_mode_audit": {
            "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
            "status": "ok",
            "output_schema_enforced": not uses_workspace_worker,
            "tool_affordances_requested": uses_workspace_worker,
        },
    }


def _summarize_direct_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return summarize_direct_telemetry_rows(rows)


def _render_codex_events_jsonl(events: Sequence[dict[str, Any]]) -> str:
    if not events:
        return ""
    return "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)


def _coerce_mapping_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _evaluate_line_role_response(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
    validator: Callable[[ShardManifestEntryV1, dict[str, Any]], tuple[bool, Sequence[str], dict[str, Any] | None]],
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    payload: dict[str, Any] | None = None
    validation_errors: tuple[str, ...] = ()
    validation_metadata: dict[str, Any] = {}
    proposal_status = "validated"
    cleaned_response_text = str(response_text or "").strip()
    if not cleaned_response_text:
        return None, ("missing_output_file",), {}, "missing_output"
    try:
        parsed_payload = json.loads(cleaned_response_text)
    except json.JSONDecodeError as exc:
        return None, ("response_json_invalid",), {"parse_error": str(exc)}, "invalid"
    if not isinstance(parsed_payload, dict):
        return (
            None,
            ("response_not_json_object",),
            {"response_type": type(parsed_payload).__name__},
            "invalid",
        )
    payload = parsed_payload
    valid, validation_errors, validation_metadata = validator(
        shard,
        parsed_payload,
    )
    proposal_status = "validated" if valid else "invalid"
    return payload, tuple(validation_errors), dict(validation_metadata or {}), proposal_status


def _preflight_line_role_shard(
    shard: ShardManifestEntryV1,
) -> dict[str, Any] | None:
    payload = _coerce_mapping_dict(shard.input_payload)
    owned_ids = [str(value).strip() for value in shard.owned_ids if str(value).strip()]
    rows = payload.get("rows")
    if not owned_ids:
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "line-role shard has no owned row ids",
        }
    if not isinstance(rows, list) or not rows:
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "line-role shard has no model-facing rows",
        }
    row_ids: list[str] = []
    for row in rows:
        if not isinstance(row, list | tuple) or len(row) < 1:
            return {
                "reason_code": "preflight_invalid_shard_payload",
                "reason_detail": "line-role shard contains an invalid row tuple",
            }
        row_ids.append(str(row[0]).strip())
    if sorted(row_ids) != sorted(owned_ids):
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "line-role shard owned ids do not match row tuple ids",
        }
    return None


def _build_preflight_rejected_run_result(
    *,
    prompt_text: str,
    output_schema_path: Path | None,
    working_dir: Path,
    reason_code: str,
    reason_detail: str,
) -> CodexExecRunResult:
    timestamp = _format_utc_now()
    return CodexExecRunResult(
        command=[],
        subprocess_exit_code=0,
        output_schema_path=str(output_schema_path) if output_schema_path is not None else None,
        prompt_text=prompt_text,
        response_text=None,
        turn_failed_message=reason_detail,
        events=(),
        usage={
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
        },
        source_working_dir=str(working_dir),
        execution_working_dir=None,
        execution_agents_path=None,
        duration_ms=0,
        started_at_utc=timestamp,
        finished_at_utc=timestamp,
        supervision_state="preflight_rejected",
        supervision_reason_code=reason_code,
        supervision_reason_detail=reason_detail,
        supervision_retryable=False,
    )


def _build_strict_json_watchdog_callback(
    *,
    live_status_path: Path | None = None,
    live_status_paths: Sequence[Path] | None = None,
    cohort_watchdog_state: _LineRoleCohortWatchdogState | None = None,
    shard_id: str | None = None,
    watchdog_policy: str = _STRICT_JSON_WATCHDOG_POLICY,
    allow_workspace_commands: bool = False,
    expected_workspace_output_paths: Sequence[Path] | None = None,
) -> Callable[[CodexExecLiveSnapshot], CodexExecSupervisionDecision | None]:
    target_paths: list[Path] = []
    if live_status_path is not None:
        target_paths.append(live_status_path)
    if live_status_paths is not None:
        target_paths.extend(Path(path) for path in live_status_paths)
    last_complete_workspace_signature: tuple[tuple[str, int, int], ...] | None = None
    workspace_output_stable_passes = 0

    def _callback(snapshot: CodexExecLiveSnapshot) -> CodexExecSupervisionDecision | None:
        nonlocal last_complete_workspace_signature
        nonlocal workspace_output_stable_passes
        decision: CodexExecSupervisionDecision | None = None
        command_execution_tolerated = False
        last_command_verdict = _classify_line_role_workspace_command(snapshot.last_command)
        last_command_boundary_violation = detect_workspace_worker_boundary_violation(
            snapshot.last_command,
        )
        cohort_snapshot = (
            cohort_watchdog_state.snapshot()
            if cohort_watchdog_state is not None
            else {}
        )
        cohort_completed_successful_shards = int(
            cohort_snapshot.get("completed_successful_shards") or 0
        )
        cohort_median_duration_ms = cohort_snapshot.get("median_duration_ms")
        cohort_elapsed_ratio = None
        if int(cohort_median_duration_ms or 0) > 0:
            cohort_elapsed_ratio = round(
                (snapshot.elapsed_seconds * 1000.0) / float(cohort_median_duration_ms),
                3,
            )
        workspace_output_status = _summarize_workspace_output_paths(
            expected_workspace_output_paths or ()
        )
        if workspace_output_status["complete"]:
            current_signature = tuple(workspace_output_status["signature"])
            if current_signature == last_complete_workspace_signature:
                workspace_output_stable_passes += 1
            else:
                last_complete_workspace_signature = current_signature
                workspace_output_stable_passes = 1
        else:
            last_complete_workspace_signature = None
            workspace_output_stable_passes = 0
        if (
            allow_workspace_commands
            and workspace_output_status["complete"]
            and workspace_output_stable_passes >= _LINE_ROLE_WORKSPACE_OUTPUT_STABLE_PASSES
        ):
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="workspace_outputs_stabilized",
                reason_detail=(
                    "line-role workspace worker wrote every assigned output file and the "
                    "files stabilized across consecutive supervision snapshots"
                ),
                retryable=False,
                supervision_state="completed",
            )
        if snapshot.command_execution_count > 0:
            if decision is None and allow_workspace_commands:
                if not last_command_verdict.allowed:
                    decision = CodexExecSupervisionDecision.terminate(
                        reason_code="watchdog_command_execution_forbidden",
                        reason_detail=format_watchdog_command_reason_detail(
                            stage_label="workspace worker stage",
                            last_command=snapshot.last_command,
                        ),
                        retryable=True,
                    )
                elif last_command_boundary_violation is None:
                    command_execution_tolerated = True
                else:
                    decision = CodexExecSupervisionDecision.terminate(
                        reason_code="watchdog_command_execution_forbidden",
                        reason_detail=format_watchdog_command_reason_detail(
                            stage_label="workspace worker stage",
                            last_command=snapshot.last_command,
                        ),
                        retryable=True,
                    )
                if decision is None and should_terminate_workspace_command_loop(
                    snapshot=snapshot,
                    max_command_count=_LINE_ROLE_WORKSPACE_MAX_COMMAND_COUNT,
                    max_repeat_count=_LINE_ROLE_WORKSPACE_MAX_REPEAT_COUNT,
                ):
                    decision = CodexExecSupervisionDecision.terminate(
                        reason_code="watchdog_command_loop_without_output",
                        reason_detail=format_watchdog_command_loop_reason_detail(
                            stage_label="workspace worker stage",
                            snapshot=snapshot,
                        ),
                        retryable=True,
                    )
            elif decision is None:
                decision = CodexExecSupervisionDecision.terminate(
                    reason_code="watchdog_command_execution_forbidden",
                    reason_detail=format_watchdog_command_reason_detail(
                        stage_label="strict JSON stage",
                        last_command=snapshot.last_command,
                    ),
                    retryable=True,
                )
        elif snapshot.reasoning_item_count >= 2 and not snapshot.has_final_agent_message:
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_reasoning_without_output",
                reason_detail="strict JSON stage emitted repeated reasoning without a final answer",
                retryable=True,
            )
        elif (
            cohort_completed_successful_shards >= _LINE_ROLE_COHORT_WATCHDOG_MIN_COMPLETED_SHARDS
            and int(cohort_median_duration_ms or 0) > 0
            and (snapshot.elapsed_seconds * 1000.0) >= _LINE_ROLE_COHORT_WATCHDOG_MIN_ELAPSED_MS
            and (snapshot.elapsed_seconds * 1000.0)
            >= (float(cohort_median_duration_ms) * _LINE_ROLE_COHORT_WATCHDOG_MEDIAN_FACTOR)
            and not snapshot.has_final_agent_message
        ):
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_cohort_runtime_outlier",
                reason_detail=(
                    "strict JSON stage exceeded sibling median runtime without reaching final output"
                ),
                retryable=True,
            )
        status_payload = {
            "state": (
                "completed"
                if isinstance(decision, CodexExecSupervisionDecision)
                and decision.action == "terminate"
                and str(decision.supervision_state or "").strip() == "completed"
                else "watchdog_killed"
                if isinstance(decision, CodexExecSupervisionDecision)
                and decision.action == "terminate"
                else "running"
            ),
            "elapsed_seconds": round(snapshot.elapsed_seconds, 3),
            "last_event_seconds_ago": (
                round(snapshot.last_event_seconds_ago, 3)
                if snapshot.last_event_seconds_ago is not None
                else None
            ),
            "event_count": snapshot.event_count,
            "command_execution_count": snapshot.command_execution_count,
            "command_execution_tolerated": command_execution_tolerated,
            "last_command_policy": last_command_verdict.policy,
            "last_command_policy_allowed": last_command_verdict.allowed,
            "last_command_policy_reason": last_command_verdict.reason,
            "last_command_boundary_violation_detected": (
                last_command_boundary_violation is not None
            ),
            "last_command_boundary_policy": (
                last_command_boundary_violation.policy
                if last_command_boundary_violation is not None
                else None
            ),
            "last_command_boundary_reason": (
                last_command_boundary_violation.reason
                if last_command_boundary_violation is not None
                else None
            ),
            "reasoning_item_count": snapshot.reasoning_item_count,
            "last_command": snapshot.last_command,
            "last_command_repeat_count": snapshot.last_command_repeat_count,
            "has_final_agent_message": snapshot.has_final_agent_message,
            "timeout_seconds": snapshot.timeout_seconds,
            "watchdog_policy": watchdog_policy,
            "shard_id": shard_id,
            "cohort_completed_successful_shards": cohort_completed_successful_shards,
            "cohort_median_duration_ms": cohort_median_duration_ms,
            "cohort_elapsed_ratio": cohort_elapsed_ratio,
            "workspace_output_expected_count": workspace_output_status["expected_count"],
            "workspace_output_present_count": workspace_output_status["present_count"],
            "workspace_output_complete": workspace_output_status["complete"],
            "workspace_output_missing_files": workspace_output_status["missing_files"],
            "workspace_output_stable_passes": workspace_output_stable_passes,
            "workspace_command_loop_max_count": _LINE_ROLE_WORKSPACE_MAX_COMMAND_COUNT,
            "workspace_command_loop_max_repeat_count": _LINE_ROLE_WORKSPACE_MAX_REPEAT_COUNT,
            "reason_code": decision.reason_code if decision is not None else None,
            "reason_detail": decision.reason_detail if decision is not None else None,
            "retryable": decision.retryable if decision is not None else False,
        }
        for path in target_paths:
            _write_runtime_json(path, status_payload)
        return decision

    return _callback


def _classify_line_role_workspace_command(
    command_text: str | None,
) -> WorkspaceCommandClassification:
    return classify_workspace_worker_command(command_text)


def _summarize_workspace_output_paths(paths: Sequence[Path]) -> dict[str, Any]:
    expected_count = len(paths)
    if expected_count <= 0:
        return {
            "expected_count": 0,
            "present_count": 0,
            "complete": False,
            "missing_files": [],
            "signature": (),
        }
    present_count = 0
    missing_files: list[str] = []
    signature: list[tuple[str, int, int]] = []
    complete = True
    for path in paths:
        path_obj = Path(path)
        if not path_obj.exists() or not path_obj.is_file():
            complete = False
            missing_files.append(path_obj.name)
            continue
        try:
            stat_result = path_obj.stat()
        except OSError:
            complete = False
            missing_files.append(path_obj.name)
            continue
        if int(stat_result.st_size or 0) <= 0:
            complete = False
            missing_files.append(path_obj.name)
            continue
        try:
            payload = json.loads(path_obj.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            complete = False
            missing_files.append(path_obj.name)
            continue
        if not isinstance(payload, Mapping):
            complete = False
            missing_files.append(path_obj.name)
            continue
        present_count += 1
        signature.append((path_obj.name, int(stat_result.st_size), int(stat_result.st_mtime_ns)))
    return {
        "expected_count": expected_count,
        "present_count": present_count,
        "complete": complete and present_count == expected_count,
        "missing_files": sorted(missing_files),
        "signature": tuple(signature),
    }


def _finalize_live_status(
    live_status_path: Path,
    *,
    run_result: CodexExecRunResult,
    watchdog_policy: str = _STRICT_JSON_WATCHDOG_POLICY,
) -> None:
    _write_runtime_json(
        live_status_path,
        {
            "state": run_result.supervision_state or "completed",
            "reason_code": run_result.supervision_reason_code,
            "reason_detail": run_result.supervision_reason_detail,
            "retryable": run_result.supervision_retryable,
            "duration_ms": run_result.duration_ms,
            "started_at_utc": run_result.started_at_utc,
            "finished_at_utc": run_result.finished_at_utc,
            "watchdog_policy": watchdog_policy,
        },
    )


def _failure_reason_from_run_result(
    *,
    run_result: CodexExecRunResult,
    proposal_status: str,
) -> str:
    if str(run_result.supervision_reason_code or "").strip():
        return str(run_result.supervision_reason_code)
    if str(run_result.supervision_state or "").strip() in {
        "preflight_rejected",
        "watchdog_killed",
    }:
        return str(run_result.supervision_state)
    return (
        "proposal_validation_failed"
        if proposal_status == "invalid"
        else "missing_output_file"
    )


def _line_role_resume_reason_fields(*, resumed_from_existing_outputs: bool) -> tuple[str, str]:
    if resumed_from_existing_outputs:
        return (
            "resume_existing_outputs",
            "all canonical line-role packet outputs were already durable on disk",
        )
    return (
        "no_tasks_assigned",
        "worker had no runnable canonical line-role packets",
    )


def _normalize_line_role_shard_outcome(
    *,
    run_result: CodexExecRunResult | None,
    proposal_status: str,
    watchdog_retry_status: str,
    repair_status: str,
    resumed_from_existing_outputs: bool,
    aggregation_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    raw_supervision_state = (
        str(run_result.supervision_state or "").strip() or None
        if run_result is not None
        else None
    )
    raw_supervision_reason_code = (
        str(run_result.supervision_reason_code or "").strip() or None
        if run_result is not None
        else None
    )
    raw_supervision_reason_detail = (
        str(run_result.supervision_reason_detail or "").strip() or None
        if run_result is not None
        else None
    )
    raw_supervision_retryable = (
        bool(run_result.supervision_retryable)
        if run_result is not None
        else False
    )
    fallback_task_count = int(
        (
            aggregation_metadata.get("fallback_task_count")
            if isinstance(aggregation_metadata, Mapping)
            else 0
        )
        or 0
    )

    if proposal_status == "validated":
        if (
            str(raw_supervision_state or "").lower() == "watchdog_killed"
            and fallback_task_count > 0
        ):
            return {
                "state": str(raw_supervision_state or "watchdog_killed"),
                "reason_code": raw_supervision_reason_code,
                "reason_detail": raw_supervision_reason_detail,
                "retryable": raw_supervision_retryable,
                "finalization_path": "session_result",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            }
        if str(repair_status).strip() == "repaired":
            detail = "line-role shard validated after a repair attempt corrected the final packet output."
            if raw_supervision_reason_code:
                detail += f" Original workspace reason: {raw_supervision_reason_code}."
            return {
                "state": "completed",
                "reason_code": "repair_recovered",
                "reason_detail": detail,
                "retryable": False,
                "finalization_path": "repair_recovered",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            }
        if str(watchdog_retry_status).strip() == "recovered":
            detail = (
                "line-role shard validated after a watchdog retry recovered missing packet outputs."
            )
            if raw_supervision_reason_code:
                detail += f" Original workspace reason: {raw_supervision_reason_code}."
            return {
                "state": "completed",
                "reason_code": "watchdog_retry_recovered",
                "reason_detail": detail,
                "retryable": False,
                "finalization_path": "watchdog_retry_recovered",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            }
        if run_result is None:
            reason_code, reason_detail = _line_role_resume_reason_fields(
                resumed_from_existing_outputs=resumed_from_existing_outputs
            )
            return {
                "state": "completed",
                "reason_code": reason_code,
                "reason_detail": reason_detail,
                "retryable": False,
                "finalization_path": reason_code,
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            }
        if str(raw_supervision_state or "").lower() == "watchdog_killed":
            detail = (
                "line-role shard validated using durable packet outputs even though the main "
                "workspace worker was killed before it terminated cleanly."
            )
            if raw_supervision_reason_code:
                detail += f" Original workspace reason: {raw_supervision_reason_code}."
            return {
                "state": "completed",
                "reason_code": "validated_after_watchdog_kill",
                "reason_detail": detail,
                "retryable": False,
                "finalization_path": "validated_after_watchdog_kill",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            }
        return {
            "state": str(raw_supervision_state or "completed"),
            "reason_code": raw_supervision_reason_code,
            "reason_detail": raw_supervision_reason_detail,
            "retryable": False,
            "finalization_path": "session_completed",
            "raw_supervision_state": raw_supervision_state,
            "raw_supervision_reason_code": raw_supervision_reason_code,
            "raw_supervision_reason_detail": raw_supervision_reason_detail,
            "raw_supervision_retryable": raw_supervision_retryable,
        }

    if run_result is None:
        reason_code, reason_detail = _line_role_resume_reason_fields(
            resumed_from_existing_outputs=resumed_from_existing_outputs
        )
        return {
            "state": "completed",
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "retryable": False,
            "finalization_path": reason_code,
            "raw_supervision_state": raw_supervision_state,
            "raw_supervision_reason_code": raw_supervision_reason_code,
            "raw_supervision_reason_detail": raw_supervision_reason_detail,
            "raw_supervision_retryable": raw_supervision_retryable,
        }

    return {
        "state": str(raw_supervision_state or "completed"),
        "reason_code": raw_supervision_reason_code,
        "reason_detail": raw_supervision_reason_detail,
        "retryable": raw_supervision_retryable,
        "finalization_path": "session_result",
        "raw_supervision_state": raw_supervision_state,
        "raw_supervision_reason_code": raw_supervision_reason_code,
        "raw_supervision_reason_detail": raw_supervision_reason_detail,
        "raw_supervision_retryable": raw_supervision_retryable,
    }


def _annotate_line_role_final_outcome_row(
    row: dict[str, Any],
    *,
    normalized_outcome: Mapping[str, Any],
) -> None:
    row["final_supervision_state"] = normalized_outcome.get("state")
    row["final_supervision_reason_code"] = normalized_outcome.get("reason_code")
    row["final_supervision_reason_detail"] = normalized_outcome.get("reason_detail")
    row["final_supervision_retryable"] = normalized_outcome.get("retryable")
    row["finalization_path"] = normalized_outcome.get("finalization_path")
    row["raw_supervision_state"] = normalized_outcome.get("raw_supervision_state")
    row["raw_supervision_reason_code"] = normalized_outcome.get(
        "raw_supervision_reason_code"
    )
    row["raw_supervision_reason_detail"] = normalized_outcome.get(
        "raw_supervision_reason_detail"
    )
    row["raw_supervision_retryable"] = normalized_outcome.get(
        "raw_supervision_retryable"
    )


def _annotate_line_role_final_proposal_status(
    row: dict[str, Any],
    *,
    final_proposal_status: str,
) -> None:
    raw_proposal_status = str(row.get("proposal_status") or "").strip()
    row["raw_proposal_status"] = raw_proposal_status or None
    row["final_proposal_status"] = str(final_proposal_status or "").strip() or None


def _apply_line_role_final_outcome_to_runner_payload(
    payload: dict[str, Any],
    *,
    shard_id: str,
    normalized_outcome: Mapping[str, Any],
) -> None:
    telemetry = payload.get("telemetry")
    row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
    changed = False
    if isinstance(row_payloads, list):
        for row_payload in row_payloads:
            if not isinstance(row_payload, dict):
                continue
            if str(row_payload.get("task_id") or "").strip() != str(shard_id).strip():
                continue
            if str(row_payload.get("prompt_input_mode") or "").strip() != "workspace_worker":
                continue
            _annotate_line_role_final_outcome_row(
                row_payload,
                normalized_outcome=normalized_outcome,
            )
            changed = True
        if changed:
            telemetry["summary"] = _summarize_direct_rows(row_payloads)


def _format_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _should_attempt_line_role_watchdog_retry(
    *,
    run_result: CodexExecRunResult,
) -> bool:
    if str(run_result.supervision_state or "").strip() != "watchdog_killed":
        return False
    if not run_result.supervision_retryable:
        return False
    return str(run_result.supervision_reason_code or "").strip() in {
        "watchdog_command_execution_forbidden",
        "watchdog_command_loop_without_output",
        "watchdog_reasoning_without_output",
        "watchdog_cohort_runtime_outlier",
    }


def _build_line_role_watchdog_example(
    *,
    shard: ShardManifestEntryV1,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return None
    compact_rows = [
        dict(row_payload)
        for row_payload in rows[:2]
        if isinstance(row_payload, Mapping)
    ]
    if not compact_rows:
        return None
    return {
        "shard_id": shard.shard_id,
        "owned_ids": list(shard.owned_ids),
        "output": {
            "rows": compact_rows,
        },
    }


def _should_attempt_line_role_repair(
    *,
    proposal_status: str,
    validation_errors: Sequence[str],
) -> bool:
    if proposal_status != "invalid":
        return False
    for error in validation_errors:
        if error in {
            "response_json_invalid",
            "response_not_json_object",
            "rows_missing_or_not_a_list",
            "row_not_a_json_object",
            "atomic_index_missing",
        }:
            return True
        if str(error).startswith(
            (
                "missing_owned_atomic_indices:",
                "duplicate_atomic_index:",
                "invalid_label:",
            )
        ):
            return True
    return False


def _run_line_role_repair_attempt(
    *,
    runner: CodexExecRunner,
    worker_root: Path,
    shard: ShardManifestEntryV1,
    env: Mapping[str, str],
    output_schema_path: Path | None,
    model: str | None,
    reasoning_effort: str | None,
    original_response_text: str,
    validation_errors: Sequence[str],
    timeout_seconds: int | None,
    pipeline_id: str,
    worker_id: str,
    live_status_path: Path | None = None,
) -> CodexExecRunResult:
    prompt_text = _build_line_role_repair_prompt(
        shard=shard,
        original_response_text=original_response_text,
        validation_errors=validation_errors,
    )
    shard_root = worker_root / "shards" / shard.shard_id
    shard_root.mkdir(parents=True, exist_ok=True)
    (shard_root / "repair_prompt.txt").write_text(prompt_text, encoding="utf-8")
    return runner.run_structured_prompt(
        prompt_text=prompt_text,
        input_payload={
            "repair_mode": "line_role",
            "pipeline_id": pipeline_id,
            "worker_id": worker_id,
            "v": _LINE_ROLE_MODEL_PAYLOAD_VERSION,
            "shard_id": shard.shard_id,
            "rows": list((shard.input_payload or {}).get("rows") or []),
            "owned_ids": list(shard.owned_ids),
            "validation_errors": list(validation_errors),
            "previous_output": _truncate_repair_text(original_response_text),
        },
        working_dir=worker_root,
        env=env,
        output_schema_path=output_schema_path,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        workspace_task_label="canonical line-role repair shard",
        supervision_callback=(
            _build_strict_json_watchdog_callback(live_status_path=live_status_path)
            if live_status_path is not None
            else None
        ),
    )


def _run_line_role_watchdog_retry_attempt(
    *,
    runner: CodexExecRunner,
    worker_root: Path,
    shard: ShardManifestEntryV1,
    env: Mapping[str, str],
    output_schema_path: Path | None,
    model: str | None,
    reasoning_effort: str | None,
    original_reason_code: str,
    original_reason_detail: str,
    successful_examples: Sequence[Mapping[str, Any]],
    timeout_seconds: int | None,
    pipeline_id: str,
    worker_id: str,
    live_status_path: Path | None = None,
) -> CodexExecRunResult:
    prompt_text = _build_line_role_watchdog_retry_prompt(
        shard=shard,
        original_reason_code=original_reason_code,
        original_reason_detail=original_reason_detail,
        successful_examples=successful_examples,
    )
    shard_root = worker_root / "shards" / shard.shard_id
    shard_root.mkdir(parents=True, exist_ok=True)
    (shard_root / "watchdog_retry_prompt.txt").write_text(prompt_text, encoding="utf-8")
    return runner.run_structured_prompt(
        prompt_text=prompt_text,
        input_payload={
            "retry_mode": "line_role_watchdog",
            "pipeline_id": pipeline_id,
            "worker_id": worker_id,
            "v": _LINE_ROLE_MODEL_PAYLOAD_VERSION,
            "shard_id": shard.shard_id,
            "rows": list((shard.input_payload or {}).get("rows") or []),
            "owned_ids": list(shard.owned_ids),
            "retry_reason": {
                "code": original_reason_code,
                "detail": original_reason_detail,
            },
            "successful_examples": [dict(example_payload) for example_payload in successful_examples],
        },
        working_dir=worker_root,
        env=env,
        output_schema_path=output_schema_path,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        workspace_task_label="canonical line-role watchdog retry shard",
        supervision_callback=(
            _build_strict_json_watchdog_callback(live_status_path=live_status_path)
            if live_status_path is not None
            else None
        ),
    )


def _build_line_role_watchdog_retry_prompt(
    *,
    shard: ShardManifestEntryV1,
    original_reason_code: str,
    original_reason_detail: str,
    successful_examples: Sequence[Mapping[str, Any]],
) -> str:
    owned_ids = ", ".join(str(value) for value in shard.owned_ids)
    allowed_labels = ", ".join(FREEFORM_ALLOWED_LABELS)
    label_code_legend = _render_label_code_legend(
        build_line_role_label_code_by_label(FREEFORM_LABELS)
    )
    authoritative_rows = _render_line_role_authoritative_rows(shard)
    example_rows = [
        json.dumps(dict(example_payload), ensure_ascii=False, sort_keys=True)
        for example_payload in successful_examples[:_LINE_ROLE_COHORT_WATCHDOG_MAX_EXAMPLES]
        if isinstance(example_payload, Mapping)
    ]
    examples_block = (
        "\n".join(example_rows)
        if example_rows
        else "[no sibling examples available]"
    )
    return (
        "Retry the strict JSON canonical line-role shard after the previous attempt was stopped.\n\n"
        "Rules:\n"
        "- Return strict JSON only.\n"
        "- Do not run shell commands, Python, or any other tools.\n"
        "- Do not describe your plan, reasoning, or heuristics.\n"
        "- Do not think step-by-step out loud.\n"
        "- The first emitted character must be `{`.\n"
        "- Your first response must be the final JSON object.\n"
        "- Return one JSON object shaped like {\"rows\":[{\"atomic_index\":<int>,\"label\":\"<ALLOWED_LABEL>\"}]}.\n"
        f"- Return each owned atomic_index exactly once, in input order: {owned_ids}\n"
        f"- Allowed labels: {allowed_labels}\n"
        "- Use only the keys `rows`, `atomic_index`, and `label`.\n\n"
        f"Label code legend: {label_code_legend}\n"
        "- Treat each row's `label_code` as a weak deterministic hint only, not final truth.\n"
        "- `INGREDIENT_LINE` means quantity/unit ingredients or bare ingredient-list items.\n"
        "- `INSTRUCTION_LINE` means a recipe-local procedural step, not generic cooking advice.\n"
        "- `HOWTO_SECTION` means a recipe-internal subsection heading, not a chapter or topic heading.\n"
        "- `KNOWLEDGE` means explanatory/reference prose.\n"
        "- `OTHER` means navigation, memoir, decorative matter, or other non-structure text.\n\n"
        f"Previous stop reason: {original_reason_code or '[unknown]'}\n"
        f"Reason detail: {original_reason_detail or '[none recorded]'}\n\n"
        "Authoritative shard rows to relabel (each row is [atomic_index, label_code, current_line]):\n"
        "<BEGIN_AUTHORITATIVE_ROWS>\n"
        f"{authoritative_rows}\n"
        "<END_AUTHORITATIVE_ROWS>\n\n"
        "Recompute the full shard from those rows. Do not copy sibling examples verbatim.\n\n"
        "Successful sibling examples:\n"
        "<BEGIN_SUCCESSFUL_SIBLING_EXAMPLES>\n"
        f"{examples_block}\n"
        "<END_SUCCESSFUL_SIBLING_EXAMPLES>\n"
    )


def _build_line_role_repair_prompt(
    *,
    shard: ShardManifestEntryV1,
    original_response_text: str,
    validation_errors: Sequence[str],
) -> str:
    owned_ids = ", ".join(str(value) for value in shard.owned_ids)
    allowed_labels = ", ".join(FREEFORM_ALLOWED_LABELS)
    label_code_legend = _render_label_code_legend(
        build_line_role_label_code_by_label(FREEFORM_LABELS)
    )
    authoritative_rows = _render_line_role_authoritative_rows(shard)
    return (
        "Repair the invalid canonical line-role shard output.\n\n"
        "Rules:\n"
        "- Return strict JSON only.\n"
        "- Do not run shell commands, Python, or any other tools.\n"
        "- Do not describe your plan, reasoning, or heuristics.\n"
        "- Do not think step-by-step out loud.\n"
        "- The first emitted character must be `{`.\n"
        "- Your first response must be the final JSON object.\n"
        "- Return one JSON object shaped like {\"rows\":[{\"atomic_index\":<int>,\"label\":\"<ALLOWED_LABEL>\"}]}.\n"
        f"- Return each owned atomic_index exactly once, in input order: {owned_ids}\n"
        f"- Allowed labels: {allowed_labels}\n"
        "- Use only the keys `rows`, `atomic_index`, and `label`.\n\n"
        f"Label code legend: {label_code_legend}\n"
        "- Treat each row's `label_code` as a weak deterministic hint only, not final truth.\n"
        "- `INGREDIENT_LINE` means quantity/unit ingredients or bare ingredient-list items.\n"
        "- `INSTRUCTION_LINE` means a recipe-local procedural step, not generic cooking advice.\n"
        "- `HOWTO_SECTION` means a recipe-internal subsection heading, not a chapter or topic heading.\n"
        "- `KNOWLEDGE` means explanatory/reference prose.\n"
        "- `OTHER` means navigation, memoir, decorative matter, or other non-structure text.\n\n"
        "Authoritative shard rows to relabel (each row is [atomic_index, label_code, current_line]):\n"
        "<BEGIN_AUTHORITATIVE_ROWS>\n"
        f"{authoritative_rows}\n"
        "<END_AUTHORITATIVE_ROWS>\n\n"
        "Recompute the full shard from those rows. Do not copy the previous output.\n\n"
        f"Validator errors: {json.dumps(list(validation_errors), sort_keys=True)}\n\n"
        "Previous invalid output:\n"
        "<BEGIN_PREVIOUS_OUTPUT>\n"
        f"{_truncate_repair_text(original_response_text)}\n"
        "<END_PREVIOUS_OUTPUT>\n"
    )


def _build_line_role_inline_attempt_runner_payload(
    *,
    pipeline_id: str,
    worker_id: str,
    shard_id: str,
    run_result: CodexExecRunResult,
    model: str | None,
    reasoning_effort: str | None,
    prompt_input_mode: str,
) -> dict[str, Any]:
    payload = run_result.to_payload(worker_id=worker_id, shard_id=shard_id)
    payload["pipeline_id"] = pipeline_id
    telemetry = payload.get("telemetry")
    row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
    if isinstance(row_payloads, list):
        for row_payload in row_payloads:
            if not isinstance(row_payload, dict):
                continue
            row_payload["prompt_input_mode"] = prompt_input_mode
            row_payload["request_input_file"] = None
            row_payload["request_input_file_bytes"] = None
            row_payload["debug_input_file"] = None
    summary_payload = telemetry.get("summary") if isinstance(telemetry, dict) else None
    if isinstance(summary_payload, dict):
        summary_payload["prompt_input_mode"] = prompt_input_mode
        summary_payload["request_input_file_bytes_total"] = None
    payload["process_payload"] = {
        "pipeline_id": pipeline_id,
        "status": "done" if run_result.subprocess_exit_code == 0 else "failed",
        "codex_model": model,
        "codex_reasoning_effort": reasoning_effort,
        "prompt_input_mode": prompt_input_mode,
    }
    return payload


def _truncate_repair_text(text: str, *, max_chars: int = 20_000) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 15].rstrip() + "\n...[truncated]"


def _write_runtime_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_runtime_jsonl(path: Path, rows: Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def _write_worker_debug_input(path: Path, *, payload: Any, input_text: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if input_text is not None:
        path.write_text(str(input_text), encoding="utf-8")
        return
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
        return
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _relative_runtime_path(base: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _line_role_asdict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _line_role_asdict(getattr(value, key))
            for key in value.__dataclass_fields__
        }
    if isinstance(value, dict):
        return {key: _line_role_asdict(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_line_role_asdict(item) for item in value]
    if isinstance(value, list):
        return [_line_role_asdict(item) for item in value]
    return value


class _PromptArtifactState:
    def __init__(self, *, artifact_root: Path | None) -> None:
        self._prompt_dir = (
            None
            if artifact_root is None
            else artifact_root / "line-role-pipeline" / "prompts"
        )
        if self._prompt_dir is not None:
            self._prompt_dir.mkdir(parents=True, exist_ok=True)

    def _phase_dir(self, phase_key: str) -> Path | None:
        if self._prompt_dir is None:
            return None
        path = self._prompt_dir / phase_key
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _path(
        self,
        phase_key: str,
        stem: str,
        prompt_index: int,
        suffix: str,
    ) -> Path | None:
        if self._prompt_dir is None:
            return None
        phase_dir = self._phase_dir(phase_key)
        if phase_dir is None:
            return None
        return phase_dir / f"{stem}_{prompt_index:04d}{suffix}"

    def write_prompt(
        self,
        *,
        phase_key: str,
        prompt_stem: str,
        prompt_index: int,
        prompt_text: str,
    ) -> None:
        path = self._path(phase_key, prompt_stem, prompt_index, ".txt")
        if path is not None:
            path.write_text(prompt_text, encoding="utf-8")

    def write_response(
        self,
        *,
        phase_key: str,
        prompt_stem: str,
        prompt_index: int,
        response_payload: Mapping[str, Any],
    ) -> None:
        response_path = self._path(phase_key, f"{prompt_stem}_response", prompt_index, ".txt")
        parsed_path = self._path(phase_key, f"{prompt_stem}_parsed", prompt_index, ".json")
        response_text = json.dumps(
            response_payload.get("rows") if isinstance(response_payload.get("rows"), list) else response_payload,
            ensure_ascii=False,
            sort_keys=True,
        )
        if response_path is not None:
            response_path.write_text(response_text, encoding="utf-8")
        if parsed_path is not None:
            parsed_path.write_text(
                json.dumps(response_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        self._append_dedup(
            phase_key=phase_key,
            prompt_stem=prompt_stem,
            prompt_index=prompt_index,
            response_text=response_text,
        )

    def write_failure(
        self,
        *,
        phase_key: str,
        prompt_stem: str,
        prompt_index: int,
        error: str,
        response_payload: Any | None = None,
    ) -> None:
        parsed_path = self._path(phase_key, f"{prompt_stem}_parsed", prompt_index, ".json")
        if parsed_path is not None:
            parsed_path.write_text(
                json.dumps(
                    {
                        "error": str(error).strip() or "invalid_proposal",
                        "response_payload": response_payload,
                        "fallback_applied": True,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        self._append_dedup(
            phase_key=phase_key,
            prompt_stem=prompt_stem,
            prompt_index=prompt_index,
            response_text=json.dumps(
                {"error": str(error).strip() or "invalid_proposal"},
                sort_keys=True,
            ),
        )

    def _append_dedup(
        self,
        *,
        phase_key: str,
        prompt_stem: str,
        prompt_index: int,
        response_text: str,
    ) -> None:
        if self._prompt_dir is None:
            return
        prompt_path = self._path(phase_key, prompt_stem, prompt_index, ".txt")
        prompt_text = prompt_path.read_text(encoding="utf-8") if prompt_path is not None and prompt_path.exists() else ""
        dedup_path = self._phase_dir(phase_key) / "codex_prompt_log.dedup.txt"
        stable_hash = hashlib.sha256(
            f"{prompt_text}\n---\n{response_text}".encode("utf-8")
        ).hexdigest()
        existing_hashes: set[str] = set()
        if dedup_path.exists():
            try:
                for line in dedup_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    existing_hashes.add(line.split("\t", 1)[0].strip())
            except OSError:
                existing_hashes = set()
        if stable_hash in existing_hashes:
            return
        with dedup_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stable_hash}\t{prompt_stem}_{prompt_index:04d}\n")

    def finalize(self, *, phase_key: str, parse_error_count: int) -> None:
        phase_dir = self._phase_dir(phase_key)
        if phase_dir is None:
            return
        (phase_dir / "parse_errors.json").write_text(
            json.dumps(
                {
                    "parse_error_count": int(parse_error_count),
                    "parse_error_present": bool(parse_error_count > 0),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )


def _write_line_role_telemetry_summary(
    *,
    artifact_root: Path | None,
    runtime_result: _LineRoleRuntimeResult | None,
) -> None:
    if artifact_root is None or runtime_result is None:
        return
    pipeline_dir = artifact_root / "line-role-pipeline"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    summary_path = pipeline_dir / "telemetry_summary.json"
    all_rows: list[dict[str, Any]] = []
    phase_payloads: list[dict[str, Any]] = []
    for phase_result in runtime_result.phase_results:
        telemetry_rows: list[dict[str, Any]] = []
        batch_payloads: list[dict[str, Any]] = []
        for report in phase_result.worker_reports:
            runner_result = report.runner_result or {}
            telemetry_payload = runner_result.get("telemetry")
            if not isinstance(telemetry_payload, dict):
                continue
            rows = telemetry_payload.get("rows")
            if isinstance(rows, list):
                telemetry_rows.extend(
                    dict(row) for row in rows if isinstance(row, dict)
                )
        all_rows.extend(telemetry_rows)
        phase_direct_summary = _summarize_direct_rows(telemetry_rows)
        phase_totals = _sum_runtime_usage(telemetry_rows)
        for plan in phase_result.shard_plans:
            runner_payload = phase_result.runner_results_by_shard_id.get(plan.shard_id) or {}
            attempt_usage: dict[str, Any] | None = None
            matching_rows = [
                row
                for row in telemetry_rows
                if str(row.get("task_id") or "").strip() == plan.shard_id
            ]
            telemetry_payload = runner_payload.get("telemetry")
            runner_rows = (
                telemetry_payload.get("rows") if isinstance(telemetry_payload, dict) else None
            )
            if isinstance(runner_rows, list) and runner_rows:
                first_row = runner_rows[0]
                if isinstance(first_row, dict):
                    attempt_usage = {
                        "tokens_input": _safe_int_value(first_row.get("tokens_input")),
                        "tokens_cached_input": _safe_int_value(first_row.get("tokens_cached_input")),
                        "tokens_output": _safe_int_value(first_row.get("tokens_output")),
                        "tokens_reasoning": _safe_int_value(first_row.get("tokens_reasoning")),
                        "tokens_total": _safe_int_value(first_row.get("tokens_total")),
                    }
            batch_payloads.append(
                {
                    "prompt_index": plan.prompt_index,
                    "shard_id": plan.shard_id,
                    "candidate_count": len(plan.candidates),
                    "requested_atomic_indices": [
                        int(candidate.atomic_index) for candidate in plan.candidates
                    ],
                    "attempt_count": len(matching_rows) or 1,
                    "attempts_with_usage": 1 if attempt_usage is not None else 0,
                    "attempts": [
                        {
                            "attempt_index": 1,
                            "response_present": bool(
                                str(runner_payload.get("response_text") or "").strip()
                            ),
                            "returncode": _safe_int_value(
                                runner_payload.get("subprocess_exit_code")
                            ),
                            "turn_failed_message": runner_payload.get("turn_failed_message"),
                            "usage": attempt_usage,
                            "process_run": runner_payload,
                        }
                    ],
                }
            )
        phase_payloads.append(
            {
                "phase_key": phase_result.phase_key,
                "phase_label": phase_result.phase_label,
                "summary": {
                    "batch_count": len(phase_result.shard_plans),
                    "attempt_count": len(telemetry_rows) or len(phase_result.shard_plans),
                    "attempts_with_usage": sum(
                        1
                        for row in telemetry_rows
                        if any(
                            _safe_int_value(row.get(key)) is not None
                            for key in (
                                "tokens_input",
                                "tokens_cached_input",
                                "tokens_output",
                                "tokens_reasoning",
                            )
                        )
                    ),
                    "tokens_input": phase_totals.get("tokens_input"),
                    "tokens_cached_input": phase_totals.get("tokens_cached_input"),
                    "tokens_output": phase_totals.get("tokens_output"),
                    "tokens_reasoning": phase_totals.get("tokens_reasoning"),
                    "tokens_total": phase_totals.get("tokens_total"),
                    "visible_input_tokens": phase_totals.get("visible_input_tokens"),
                    "visible_output_tokens": phase_totals.get("visible_output_tokens"),
                    "wrapper_overhead_tokens": phase_totals.get("wrapper_overhead_tokens"),
                    "command_execution_count_total": phase_direct_summary.get(
                        "command_execution_count_total"
                    ),
                    "command_executing_shard_count": phase_direct_summary.get(
                        "command_executing_shard_count"
                    ),
                    "command_execution_tokens_total": phase_direct_summary.get(
                        "command_execution_tokens_total"
                    ),
                    "reasoning_item_count_total": phase_direct_summary.get(
                        "reasoning_item_count_total"
                    ),
                    "reasoning_heavy_shard_count": phase_direct_summary.get(
                        "reasoning_heavy_shard_count"
                    ),
                    "reasoning_heavy_tokens_total": phase_direct_summary.get(
                        "reasoning_heavy_tokens_total"
                    ),
                    "invalid_output_shard_count": phase_direct_summary.get(
                        "invalid_output_shard_count"
                    ),
                    "invalid_output_tokens_total": phase_direct_summary.get(
                        "invalid_output_tokens_total"
                    ),
                    "missing_output_shard_count": phase_direct_summary.get(
                        "missing_output_shard_count"
                    ),
                    "preflight_rejected_shard_count": phase_direct_summary.get(
                        "preflight_rejected_shard_count"
                    ),
                    "watchdog_killed_shard_count": phase_direct_summary.get(
                        "watchdog_killed_shard_count"
                    ),
                    "watchdog_recovered_shard_count": phase_direct_summary.get(
                        "watchdog_recovered_shard_count"
                    ),
                    "repaired_shard_count": phase_direct_summary.get(
                        "repaired_shard_count"
                    ),
                    "pathological_shard_count": phase_direct_summary.get(
                        "pathological_shard_count"
                    ),
                    "pathological_flags": phase_direct_summary.get("pathological_flags"),
                    "prompt_input_mode": "inline",
                    "request_input_file_bytes_total": phase_totals.get(
                        "request_input_file_bytes_total"
                    ),
                },
                "batches": batch_payloads,
                "runtime_artifacts": {
                    "runtime_root": (
                        str(phase_result.runtime_root.relative_to(artifact_root))
                        if phase_result.runtime_root is not None
                        else None
                    ),
                    "invalid_shard_count": phase_result.invalid_shard_count,
                    "missing_output_shard_count": phase_result.missing_output_shard_count,
                    "worker_count": len(phase_result.worker_reports),
                },
            }
        )
    totals = _sum_runtime_usage(all_rows)
    direct_summary = _summarize_direct_rows(all_rows)
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pipeline": LINE_ROLE_PIPELINE_SHARD_V1,
                "codex_backend": "codex_exec_direct",
                "codex_farm_pipeline_id": _LINE_ROLE_CODEX_FARM_PIPELINE_ID,
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "token_usage_enabled": bool(all_rows),
                "summary": {
                    "batch_count": sum(
                        len(phase_result.shard_plans)
                        for phase_result in runtime_result.phase_results
                    ),
                    "attempt_count": len(all_rows)
                    or sum(len(phase_result.shard_plans) for phase_result in runtime_result.phase_results),
                    "attempts_with_usage": sum(
                        1
                        for row in all_rows
                        if any(
                            _safe_int_value(row.get(key)) is not None
                            for key in (
                                "tokens_input",
                                "tokens_cached_input",
                                "tokens_output",
                                "tokens_reasoning",
                            )
                        )
                    ),
                    "attempts_without_usage": max(
                        0,
                        (
                            len(all_rows)
                            or sum(
                                len(phase_result.shard_plans)
                                for phase_result in runtime_result.phase_results
                            )
                        )
                        - sum(
                            1
                            for row in all_rows
                            if any(
                                _safe_int_value(row.get(key)) is not None
                                for key in (
                                    "tokens_input",
                                    "tokens_cached_input",
                                    "tokens_output",
                                    "tokens_reasoning",
                                )
                            )
                        ),
                    ),
                    "tokens_input": totals.get("tokens_input"),
                    "tokens_cached_input": totals.get("tokens_cached_input"),
                    "tokens_output": totals.get("tokens_output"),
                    "tokens_reasoning": totals.get("tokens_reasoning"),
                    "tokens_total": totals.get("tokens_total"),
                    "visible_input_tokens": totals.get("visible_input_tokens"),
                    "visible_output_tokens": totals.get("visible_output_tokens"),
                    "wrapper_overhead_tokens": totals.get("wrapper_overhead_tokens"),
                    "command_execution_count_total": direct_summary.get(
                        "command_execution_count_total"
                    ),
                    "command_executing_shard_count": direct_summary.get(
                        "command_executing_shard_count"
                    ),
                    "command_execution_tokens_total": direct_summary.get(
                        "command_execution_tokens_total"
                    ),
                    "reasoning_item_count_total": direct_summary.get(
                        "reasoning_item_count_total"
                    ),
                    "reasoning_heavy_shard_count": direct_summary.get(
                        "reasoning_heavy_shard_count"
                    ),
                    "reasoning_heavy_tokens_total": direct_summary.get(
                        "reasoning_heavy_tokens_total"
                    ),
                    "invalid_output_shard_count": direct_summary.get(
                        "invalid_output_shard_count"
                    ),
                    "invalid_output_tokens_total": direct_summary.get(
                        "invalid_output_tokens_total"
                    ),
                    "missing_output_shard_count": direct_summary.get(
                        "missing_output_shard_count"
                    ),
                    "preflight_rejected_shard_count": direct_summary.get(
                        "preflight_rejected_shard_count"
                    ),
                    "watchdog_killed_shard_count": direct_summary.get(
                        "watchdog_killed_shard_count"
                    ),
                    "watchdog_recovered_shard_count": direct_summary.get(
                        "watchdog_recovered_shard_count"
                    ),
                    "repaired_shard_count": direct_summary.get("repaired_shard_count"),
                    "pathological_shard_count": direct_summary.get(
                        "pathological_shard_count"
                    ),
                    "pathological_flags": direct_summary.get("pathological_flags"),
                    "prompt_input_mode": "inline",
                    "request_input_file_bytes_total": totals.get(
                        "request_input_file_bytes_total"
                    ),
                },
                "phases": phase_payloads,
                "runtime_artifacts": {
                    "runtime_root": "line-role-pipeline/runtime",
                    "phase_count": len(runtime_result.phase_results),
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _sum_runtime_usage(rows: Sequence[dict[str, Any]]) -> dict[str, int | None]:
    totals: dict[str, int | None] = {
        "tokens_input": None,
        "tokens_cached_input": None,
        "tokens_output": None,
        "tokens_reasoning": None,
        "tokens_total": None,
        "visible_input_tokens": None,
        "visible_output_tokens": None,
        "wrapper_overhead_tokens": None,
        "request_input_file_bytes_total": None,
    }
    for row in rows:
        tokens_input = _safe_int_value(row.get("tokens_input"))
        tokens_cached_input = _safe_int_value(row.get("tokens_cached_input"))
        tokens_output = _safe_int_value(row.get("tokens_output"))
        tokens_reasoning = _safe_int_value(row.get("tokens_reasoning"))
        values = {
            "tokens_input": tokens_input,
            "tokens_cached_input": tokens_cached_input,
            "tokens_output": tokens_output,
            "tokens_reasoning": tokens_reasoning,
            "tokens_total": _safe_int_value(row.get("tokens_total"))
            or (
                tokens_input + tokens_cached_input + tokens_output + tokens_reasoning
                if all(
                    value is not None
                    for value in (
                        tokens_input,
                        tokens_cached_input,
                        tokens_output,
                        tokens_reasoning,
                    )
                )
                else None
            ),
            "visible_input_tokens": _safe_int_value(row.get("visible_input_tokens")),
            "visible_output_tokens": _safe_int_value(row.get("visible_output_tokens")),
            "wrapper_overhead_tokens": _safe_int_value(row.get("wrapper_overhead_tokens")),
            "request_input_file_bytes_total": _safe_int_value(
                row.get("request_input_file_bytes")
            ),
        }
        for key, value in values.items():
            if value is None:
                continue
            current = totals.get(key)
            totals[key] = value if current is None else current + value
    return totals


def _safe_int_value(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_line_role_codex_max_inflight() -> int:
    raw_value = str(os.getenv(_LINE_ROLE_CODEX_MAX_INFLIGHT_ENV) or "").strip()
    if not raw_value:
        return _LINE_ROLE_CODEX_MAX_INFLIGHT_DEFAULT
    return _normalize_line_role_codex_max_inflight_value(raw_value)


def _normalize_line_role_codex_max_inflight_value(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return _LINE_ROLE_CODEX_MAX_INFLIGHT_DEFAULT
    return max(1, min(parsed, 32))


def _resolve_line_role_cache_path(
    *,
    source_hash: str | None,
    settings: RunSettings,
    ordered_candidates: Sequence[AtomicLineCandidate],
    artifact_root: Path | None,
    cache_root: Path | None,
    codex_timeout_seconds: int,
    codex_batch_size: int,
) -> Path | None:
    normalized_source_hash = str(source_hash or "").strip()
    if not normalized_source_hash:
        return None
    resolved_root = _resolve_line_role_cache_root(
        artifact_root=artifact_root,
        cache_root=cache_root,
    )
    if resolved_root is None:
        return None
    candidate_fingerprint = _canonical_candidate_fingerprint(ordered_candidates)
    key_payload = {
        "schema_version": _LINE_ROLE_CACHE_SCHEMA_VERSION,
        "source_hash": normalized_source_hash,
        "line_role_identity": build_line_role_cache_identity_payload(settings),
        "candidate_fingerprint": candidate_fingerprint,
        "codex_timeout_seconds": int(codex_timeout_seconds),
        "codex_batch_size": int(codex_batch_size),
    }
    digest = hashlib.sha256(
        json.dumps(
            key_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return resolved_root / digest[:2] / f"{digest}.json"


def _resolve_line_role_cache_root(
    *,
    artifact_root: Path | None,
    cache_root: Path | None,
) -> Path | None:
    if cache_root is not None:
        return cache_root.expanduser()
    override = str(os.getenv(_LINE_ROLE_CACHE_ROOT_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    if artifact_root is None:
        return None
    resolved_artifact_root = artifact_root.expanduser().resolve()
    for parent in (resolved_artifact_root, *resolved_artifact_root.parents):
        if parent.name in {"benchmark-vs-golden", "sent-to-labelstudio"}:
            return parent / ".cache" / "canonical_line_role"
    return resolved_artifact_root / ".cache" / "canonical_line_role"


def _canonical_candidate_fingerprint(
    candidates: Sequence[AtomicLineCandidate],
) -> str:
    by_atomic_index = build_atomic_index_lookup(candidates)
    payload: list[dict[str, Any]] = []
    for candidate in candidates:
        prev_text, next_text = get_atomic_line_neighbor_texts(
            candidate,
            by_atomic_index=by_atomic_index,
        )
        payload.append(
            {
                "recipe_id": candidate.recipe_id,
                "block_id": candidate.block_id,
                "block_index": candidate.block_index,
                "atomic_index": candidate.atomic_index,
                "text": candidate.text,
                "within_recipe_span": candidate.within_recipe_span,
                "prev_text": prev_text,
                "next_text": next_text,
                "rule_tags": list(candidate.rule_tags),
            }
        )
    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _load_cached_predictions(
    *,
    cache_path: Path,
    expected_candidates: Sequence[AtomicLineCandidate],
) -> tuple[list[CanonicalLineRolePrediction], list[CanonicalLineRolePrediction]] | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != _LINE_ROLE_CACHE_SCHEMA_VERSION:
        return None
    raw_predictions = payload.get("predictions")
    if not isinstance(raw_predictions, list):
        return None
    raw_baseline_predictions = payload.get("baseline_predictions")
    if raw_baseline_predictions is None:
        raw_baseline_predictions = raw_predictions
    if not isinstance(raw_baseline_predictions, list):
        return None
    predictions: list[CanonicalLineRolePrediction] = []
    baseline_predictions: list[CanonicalLineRolePrediction] = []
    try:
        for row in raw_predictions:
            predictions.append(CanonicalLineRolePrediction.model_validate(row))
        for row in raw_baseline_predictions:
            baseline_predictions.append(CanonicalLineRolePrediction.model_validate(row))
    except Exception:
        return None
    if (
        len(predictions) != len(expected_candidates)
        or len(baseline_predictions) != len(expected_candidates)
    ):
        return None
    for candidate, prediction in zip(expected_candidates, predictions):
        if int(candidate.atomic_index) != int(prediction.atomic_index):
            return None
        if str(candidate.text) != str(prediction.text):
            return None
    return predictions, baseline_predictions


def _write_cached_predictions(
    *,
    cache_path: Path | None,
    predictions: Sequence[CanonicalLineRolePrediction],
    baseline_predictions: Sequence[CanonicalLineRolePrediction],
) -> None:
    if cache_path is None:
        return
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _LINE_ROLE_CACHE_SCHEMA_VERSION,
            "predictions": [row.model_dump(mode="json") for row in predictions],
            "baseline_predictions": [
                row.model_dump(mode="json") for row in baseline_predictions
            ],
        }
        tmp_path = cache_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(cache_path)
    except OSError:
        return


def _line_role_pipeline_name(settings: RunSettings) -> str:
    value = getattr(settings, "line_role_pipeline", "off")
    return normalize_line_role_pipeline_value(value)


def _deterministic_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None = None,
) -> tuple[str | None, list[str]]:
    tags = {str(tag) for tag in candidate.rule_tags}
    howto_prose_label, howto_prose_reason_tags = _classify_non_heading_howto_prose(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if howto_prose_label is not None:
        return howto_prose_label, howto_prose_reason_tags
    variant_context_label, variant_context_reason_tags = _classify_variant_run_context(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if variant_context_label is not None:
        return variant_context_label, variant_context_reason_tags
    if "note_prefix" in tags or _looks_note_text(candidate.text):
        return "RECIPE_NOTES", ["note_prefix"]
    if _looks_storage_or_serving_note(candidate.text):
        return "RECIPE_NOTES", ["storage_or_serving_note"]
    if _looks_editorial_note(candidate.text):
        if _is_within_recipe_span(candidate):
            return "RECIPE_NOTES", ["editorial_note"]
        return "RECIPE_NOTES", ["outside_recipe_editorial_note"]
    if (
        _is_outside_recipe_span(candidate)
        and _looks_recipe_note_prose(candidate.text)
        and "ingredient_like" not in tags
        and "yield_prefix" not in tags
        and "howto_heading" not in tags
    ):
        return "RECIPE_NOTES", ["outside_recipe_note_prose"]
    if (
        _is_outside_recipe_span(candidate)
        and _looks_prose(candidate.text)
        and "ingredient_like" not in tags
        and "yield_prefix" not in tags
        and "howto_heading" not in tags
    ):
        if _looks_narrative_prose(candidate.text):
            return "OTHER", ["outside_recipe_narrative"]
        if _outside_recipe_knowledge_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            return "KNOWLEDGE", [
                "outside_recipe_span",
                "knowledge_high_evidence",
            ]
        return "OTHER", ["outside_recipe_span", "prose_default_other"]
    if (
        candidate.within_recipe_span is None
        and _looks_prose(candidate.text)
        and "ingredient_like" not in tags
        and "yield_prefix" not in tags
        and "howto_heading" not in tags
    ):
        if _looks_narrative_prose(candidate.text):
            return "OTHER", ["unknown_recipe_span", "narrative_default_other"]
        if _outside_recipe_knowledge_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            return "KNOWLEDGE", [
                "unknown_recipe_span",
                "knowledge_high_evidence",
            ]
        return "OTHER", ["unknown_recipe_span", "prose_default_other"]
    if "yield_prefix" in tags:
        return "YIELD_LINE", ["yield_prefix"]
    if "howto_heading" in tags and _howto_section_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "HOWTO_SECTION", ["howto_heading"]
    if _looks_subsection_heading_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        if (
            _is_outside_recipe_span(candidate)
            and _looks_recipe_title_with_context(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        ):
            return "RECIPE_TITLE", ["title_like", "subsection_heading_title_override"]
        return "HOWTO_SECTION", ["subsection_heading_context"]
    if "note_like_prose" in tags:
        return "RECIPE_NOTES", ["note_like_prose"]
    if "ingredient_like" in tags:
        if _looks_recipe_title_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            return "RECIPE_TITLE", ["title_like", "ingredient_heading_override"]
        return "INGREDIENT_LINE", ["ingredient_like"]
    if "instruction_with_time" in tags:
        return "INSTRUCTION_LINE", ["instruction_with_time"]
    if "instruction_like" in tags:
        if (
            _is_outside_recipe_span(candidate)
            and _looks_recipe_title_with_context(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        ):
            return "RECIPE_TITLE", ["title_like", "instruction_heading_override"]
        return "INSTRUCTION_LINE", ["instruction_like"]
    if "time_metadata" in tags and _is_primary_time_line(candidate.text):
        return "TIME_LINE", ["time_metadata"]
    if _is_outside_recipe_span(candidate):
        if _outside_recipe_knowledge_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            return "KNOWLEDGE", [
                "outside_recipe_span",
                "knowledge_high_evidence",
            ]
    if "outside_recipe_span" in tags:
        if _looks_recipe_title_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            return "RECIPE_TITLE", ["title_like", "outside_recipe_span"]
        if _looks_prose(candidate.text):
            if _looks_narrative_prose(candidate.text):
                return "OTHER", ["outside_recipe_narrative", "outside_recipe_span"]
            if _outside_recipe_knowledge_label_allowed(
                candidate,
                by_atomic_index=by_atomic_index,
            ):
                return "KNOWLEDGE", [
                    "outside_recipe_span",
                    "knowledge_high_evidence",
                ]
            return "OTHER", ["outside_recipe_span", "prose_default_other"]
        return "OTHER", ["outside_recipe_span"]
    if candidate.within_recipe_span is None and _outside_recipe_knowledge_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "KNOWLEDGE", ["unknown_recipe_span", "knowledge_high_evidence"]
    if (
        "title_like" in tags or _looks_recipe_title(candidate.text)
    ) and _looks_recipe_title_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "RECIPE_TITLE", ["title_like"]
    return None, ["needs_disambiguation"]


def _fallback_prediction(
    candidate: AtomicLineCandidate,
    *,
    reason: str,
    by_atomic_index: dict[int, AtomicLineCandidate] | None = None,
) -> CanonicalLineRolePrediction:
    if by_atomic_index is None:
        by_atomic_index = {int(candidate.atomic_index): candidate}
    deterministic_label, deterministic_tags = _deterministic_label(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if deterministic_label is not None and deterministic_label in FREEFORM_ALLOWED_LABELS:
        label = deterministic_label
        reason_tags = [reason, "deterministic_recovered", *deterministic_tags]
    else:
        label = "OTHER"
        reason_tags = [reason, "deterministic_unavailable"]
    return CanonicalLineRolePrediction(
        recipe_id=candidate.recipe_id,
        block_id=str(candidate.block_id),
        block_index=int(candidate.block_index),
        atomic_index=int(candidate.atomic_index),
        text=str(candidate.text),
        within_recipe_span=candidate.within_recipe_span,
        label=label,
        decided_by="fallback",
        reason_tags=reason_tags,
    )

def _sanitize_prediction(
    *,
    prediction: CanonicalLineRolePrediction,
    candidate: AtomicLineCandidate,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> CanonicalLineRolePrediction:
    label = prediction.label if prediction.label in FREEFORM_ALLOWED_LABELS else "OTHER"
    reason_tags = list(prediction.reason_tags)
    decided_by = prediction.decided_by
    review_exclusion_reason = prediction.review_exclusion_reason
    if (
        label == "KNOWLEDGE"
        and _is_within_recipe_span(candidate)
        and not _knowledge_allowed_inside_recipe(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        label = "OTHER"
        decided_by = "fallback"
        reason_tags.append("sanitized_knowledge_inside_recipe")
    if label == "KNOWLEDGE" and not _is_within_recipe_span(candidate):
        label = "OTHER"
        decided_by = "fallback"
        reason_tags.append("sanitized_outside_recipe_knowledge_to_reviewable_other")
    if label == "TIME_LINE" and not _is_primary_time_line(candidate.text):
        label = "OTHER" if _is_outside_recipe_span(candidate) else "INSTRUCTION_LINE"
        decided_by = "fallback"
        reason_tags.append(
            "sanitized_time_to_instruction"
            if not _is_outside_recipe_span(candidate)
            else "sanitized_time_to_other"
        )
    if (
        label in {"OTHER", "KNOWLEDGE", "RECIPE_NOTES", "INSTRUCTION_LINE", "TIME_LINE"}
        and _should_rescue_neighbor_ingredient_fragment(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        label = "INGREDIENT_LINE"
        decided_by = "fallback"
        reason_tags.append("sanitized_neighbor_ingredient_fragment")
    if label == "YIELD_LINE":
        if _looks_obvious_ingredient(candidate):
            label = "INGREDIENT_LINE"
            decided_by = "fallback"
            reason_tags.append("sanitized_yield_to_ingredient")
        elif not _looks_strict_yield_header(candidate.text):
            label = _yield_fallback_label(candidate)
            decided_by = "fallback"
            reason_tags.append(
                "sanitized_yield_to_instruction"
                if label == "INSTRUCTION_LINE"
                else "sanitized_yield_non_header"
            )
    if (
        label == "RECIPE_TITLE"
        and _is_outside_recipe_span(candidate)
        and not _looks_recipe_title_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        label = _outside_span_nonstructured_fallback_label(
            candidate,
            by_atomic_index=by_atomic_index,
        )
        decided_by = "fallback"
        reason_tags.append("sanitized_title_without_local_support")
    if label == "RECIPE_VARIANT" and not _variant_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        label = _variant_fallback_label(
            candidate,
            by_atomic_index=by_atomic_index,
        )
        decided_by = "fallback"
        reason_tags.append("sanitized_variant_without_local_support")
    if label == "OTHER":
        if _variant_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            label = "RECIPE_VARIANT"
            decided_by = "fallback"
            reason_tags.append("rescued_other_to_variant")
        elif _should_rescue_other_to_knowledge_label(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            label = "KNOWLEDGE"
            decided_by = "fallback"
            reason_tags.append("rescued_other_to_knowledge")
        elif _should_rescue_other_to_instruction_label(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            label = "INSTRUCTION_LINE"
            decided_by = "fallback"
            reason_tags.append("rescued_other_to_instruction")
    if (
        _is_outside_recipe_span(candidate)
        and label in _RECIPEISH_OUTSIDE_SPAN_LABELS
        and not _outside_span_structured_label_allowed(
            label=label,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        if prediction.decided_by != "codex":
            fallback_label = _outside_span_nonstructured_fallback_label(
                candidate,
                by_atomic_index=by_atomic_index,
            )
            if fallback_label != label:
                label = fallback_label
                decided_by = "fallback"
                reason_tags.append("sanitized_outside_span_structured_label")
    if label == "HOWTO_SECTION" and not _howto_section_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        label = _howto_section_fallback_label(
            candidate,
            by_atomic_index=by_atomic_index,
        )
        decided_by = "fallback"
        reason_tags.append("sanitized_howto_without_local_support")
    if label == "INSTRUCTION_LINE" and not _instruction_line_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        label = _instruction_line_fallback_label(
            candidate,
            by_atomic_index=by_atomic_index,
        )
        decided_by = "fallback"
        reason_tags.append("sanitized_instruction_without_local_support")
    if label == "KNOWLEDGE" and not _is_within_recipe_span(candidate):
        label = "OTHER"
        decided_by = "fallback"
        if "sanitized_outside_recipe_knowledge_to_reviewable_other" not in reason_tags:
            reason_tags.append("sanitized_outside_recipe_knowledge_to_reviewable_other")
    if label != "OTHER" or _is_within_recipe_span(candidate):
        review_exclusion_reason = None
    else:
        review_exclusion_reason = (
            review_exclusion_reason
            or _outside_recipe_review_exclusion_reason(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        )
    return CanonicalLineRolePrediction(
        recipe_id=prediction.recipe_id,
        block_id=prediction.block_id,
        block_index=prediction.block_index,
        atomic_index=prediction.atomic_index,
        text=prediction.text,
        within_recipe_span=prediction.within_recipe_span,
        label=label,
        decided_by=decided_by,
        reason_tags=reason_tags,
        review_exclusion_reason=review_exclusion_reason,
    )

def _should_escalate_candidate(
    *,
    candidate: AtomicLineCandidate,
    deterministic_label: str | None,
    escalation_reasons: Sequence[str],
) -> bool:
    if _is_outside_recipe_span(candidate):
        return False
    if deterministic_label in {"RECIPE_TITLE", "RECIPE_VARIANT"}:
        return False
    if not escalation_reasons:
        return False
    return True

def _outside_span_has_neighboring_recipe_evidence(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
    radius: int = 2,
) -> bool:
    center = int(candidate.atomic_index)
    lower = int(candidate.atomic_index) - max(1, int(radius))
    upper = int(candidate.atomic_index) + max(1, int(radius))
    for atomic_index in range(lower, upper + 1):
        if atomic_index == center:
            continue
        row = by_atomic_index.get(atomic_index)
        if row is None:
            continue
        tags = {str(tag) for tag in row.rule_tags}
        if {
            "ingredient_like",
            "instruction_like",
            "instruction_with_time",
            "yield_prefix",
            "howto_heading",
            "variant_heading",
        } & tags:
            return True
        if _looks_obvious_ingredient(row) or _looks_instructional_neighbor(row):
            return True
        if _looks_recipe_start_boundary(row):
            return True
    return False


def _outside_span_structured_label_allowed(
    *,
    label: str,
    candidate: AtomicLineCandidate,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    text = str(candidate.text or "").strip()
    has_neighboring_recipe_evidence = _outside_span_has_neighboring_recipe_evidence(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    has_neighboring_component_structure = _outside_span_has_neighboring_component_structure(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if label == "RECIPE_TITLE":
        return _looks_recipe_title_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    if label == "RECIPE_VARIANT":
        return _variant_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        ) or has_neighboring_component_structure
    if label == "HOWTO_SECTION":
        return _howto_section_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    if label == "INGREDIENT_LINE":
        return _looks_obvious_ingredient(candidate) or has_neighboring_recipe_evidence
    if label == "INSTRUCTION_LINE":
        return _instruction_line_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    if label == "YIELD_LINE":
        return _looks_strict_yield_header(text)
    return True


def _outside_span_nonstructured_fallback_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> str:
    text = str(candidate.text or "").strip()
    if _looks_knowledge_heading_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ) or _looks_knowledge_prose_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "KNOWLEDGE"
    if _looks_recipe_note_prose(text) or _looks_editorial_note(text):
        return "RECIPE_NOTES"
    return "OTHER"


def _should_rescue_other_to_knowledge_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    if not _is_within_recipe_span(candidate):
        return False
    if not _knowledge_allowed_inside_recipe(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return False
    if _looks_recipe_title_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return False
    return not _variant_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    )


def _should_rescue_other_to_instruction_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    text = str(candidate.text or "").strip()
    tags = {str(tag) for tag in candidate.rule_tags}
    if not text:
        return False
    if not _instruction_line_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return False
    if (
        _looks_recipe_note_prose(text)
        or _looks_storage_or_serving_note(text)
        or _looks_recipe_title_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        )
        or _outside_recipe_knowledge_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        return False
    if _looks_direct_instruction_start(candidate) or _looks_non_heading_howto_prose(text):
        return True
    if _is_outside_recipe_span(candidate):
        return bool(
            {"instruction_like", "instruction_with_time"} & tags
        ) and _outside_span_has_neighboring_component_structure(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    return bool({"instruction_like", "instruction_with_time"} & tags)


def _outside_span_has_neighboring_component_structure(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
    radius: int = 2,
) -> bool:
    center = int(candidate.atomic_index)
    lower = center - max(1, int(radius))
    upper = center + max(1, int(radius))
    for atomic_index in range(lower, upper + 1):
        if atomic_index == center:
            continue
        row = by_atomic_index.get(atomic_index)
        if row is None:
            continue
        tags = {str(tag) for tag in row.rule_tags}
        if {
            "ingredient_like",
            "yield_prefix",
            "howto_heading",
            "variant_heading",
        } & tags:
            return True
        if _looks_obvious_ingredient(row):
            return True
        if _looks_recipe_start_boundary(row):
            return True
        if _looks_direct_instruction_start(row):
            return True
    return False


def _classify_non_heading_howto_prose(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> tuple[str | None, list[str]]:
    text = str(candidate.text or "").strip()
    if not _looks_non_heading_howto_prose(text):
        return None, []
    lowered = text.lower()
    if lowered.startswith("to make "):
        is_named_variant = _looks_named_variant_recipe_name_prefix(text)
        is_generic_make_step = _looks_generic_to_make_step(text)
        has_variant_cue = _looks_explicit_variant_prose(text)
        has_neighboring_variant_heading = (
            by_atomic_index is not None
            and _has_neighboring_variant_heading(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        )
        if _is_within_recipe_span(candidate):
            if is_named_variant or has_neighboring_variant_heading or has_variant_cue:
                return "RECIPE_VARIANT", [
                    "howto_prefix_prose",
                    "recipe_local_variant_prose",
                ]
            reason_tags = ["howto_prefix_prose", "recipe_local_make_step"]
            if is_generic_make_step:
                reason_tags.append("generic_to_make_step")
            return "INSTRUCTION_LINE", reason_tags
        has_neighboring_component_structure = (
            by_atomic_index is not None
            and _outside_span_has_neighboring_component_structure(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        )
        if (
            is_named_variant
            or has_neighboring_variant_heading
            or (has_variant_cue and has_neighboring_component_structure)
        ):
            return "RECIPE_VARIANT", [
                "howto_prefix_prose",
                "outside_recipe_variant_prose",
            ]
        if (
            by_atomic_index is not None
            and _instruction_line_label_allowed(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        ):
            reason_tags = ["howto_prefix_prose", "outside_recipe_make_step"]
            if is_generic_make_step:
                reason_tags.append("generic_to_make_step")
            return "INSTRUCTION_LINE", reason_tags
        if (
            by_atomic_index is not None
            and _outside_recipe_knowledge_label_allowed(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        ):
            return "KNOWLEDGE", ["howto_prefix_prose", "knowledge_high_evidence"]
        if _is_outside_recipe_span(candidate):
            return "OTHER", ["howto_prefix_prose", "outside_recipe_default_other"]
        return "OTHER", ["howto_prefix_prose", "default_other"]
    if lowered.startswith("to serve"):
        if _is_within_recipe_span(candidate):
            return "INSTRUCTION_LINE", ["howto_prefix_prose", "serving_step_prose"]
        if (
            by_atomic_index is not None
            and _outside_recipe_knowledge_label_allowed(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        ):
            return "KNOWLEDGE", ["howto_prefix_prose", "knowledge_high_evidence"]
        if _is_outside_recipe_span(candidate):
            return "OTHER", ["howto_prefix_prose", "outside_recipe_serving_prose"]
        return "OTHER", ["howto_prefix_prose", "default_other"]
    if _looks_storage_or_serving_note(text) or _looks_recipe_note_prose(text):
        return "RECIPE_NOTES", ["howto_prefix_prose", "note_like_prose"]
    if (
        by_atomic_index is not None
        and _outside_recipe_knowledge_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        return "KNOWLEDGE", ["howto_prefix_prose", "knowledge_high_evidence"]
    if _is_outside_recipe_span(candidate):
        return "OTHER", ["howto_prefix_prose", "outside_recipe_default_other"]
    return "OTHER", ["howto_prefix_prose", "default_other"]


def _classify_variant_run_context(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> tuple[str | None, list[str]]:
    text = str(candidate.text or "").strip()
    if _variant_heading_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        if (
            _is_outside_recipe_span(candidate)
            and _outside_span_variant_should_be_recipe_title(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        ):
            return "RECIPE_TITLE", ["title_like", "variant_heading_title_override"]
        tags = ["variant_heading"]
        if _normalized_variant_heading_text(text) in _VARIANT_GENERIC_HEADINGS:
            tags.append("variant_heading_supported")
        return "RECIPE_VARIANT", tags
    if by_atomic_index is not None and _is_within_variant_run(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "RECIPE_VARIANT", ["variant_run_continuation"]
    return None, []


def _howto_section_label_allowed(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if by_atomic_index is None:
        return False
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if _looks_non_heading_howto_prose(text):
        return False
    if _HOWTO_PREFIX_RE.match(text):
        if not _looks_howto_heading_shape(text):
            return False
    elif not _looks_compact_heading(text):
        return False
    if _looks_knowledge_heading_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return False
    return _has_recipe_local_howto_support(
        candidate,
        by_atomic_index=by_atomic_index,
    )


def _has_recipe_local_howto_support(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    text = str(candidate.text or "").strip()
    if not text:
        return False
    explicit_prefix = bool(_HOWTO_PREFIX_RE.match(text))
    if not explicit_prefix:
        if not _looks_recipe_title(text):
            return False
        if not _looks_compact_heading(text):
            return False
    elif not _looks_howto_heading_shape(text):
        return False
    prev_candidate = by_atomic_index.get(int(candidate.atomic_index) - 1)
    next_candidate = by_atomic_index.get(int(candidate.atomic_index) + 1)
    if prev_candidate is None and next_candidate is None:
        return False

    prev_component = _is_component_level_recipe_neighbor(prev_candidate)
    next_component = _is_component_level_recipe_neighbor(next_candidate)
    prev_flow = _looks_recipe_flow_neighbor(prev_candidate)
    next_flow = _looks_recipe_flow_neighbor(next_candidate)

    if explicit_prefix:
        return prev_component or next_component or (prev_flow and next_flow)
    return (
        (prev_component and next_component)
        or (_neighbor_is_ingredient_dominant(prev_candidate) and _looks_instructional_neighbor_or_boundary(next_candidate))
        or (_neighbor_is_ingredient_dominant(next_candidate) and _looks_instructional_neighbor_or_boundary(prev_candidate))
    )


def _is_component_level_recipe_neighbor(candidate: AtomicLineCandidate | None) -> bool:
    if candidate is None:
        return False
    return (
        _neighbor_is_ingredient_dominant(candidate)
        or _looks_instructional_neighbor(candidate)
        or _looks_recipe_start_boundary(candidate)
    )


def _looks_instructional_neighbor_or_boundary(
    candidate: AtomicLineCandidate | None,
) -> bool:
    if candidate is None:
        return False
    return _looks_instructional_neighbor(candidate) or _looks_recipe_start_boundary(
        candidate
    )


def _instruction_line_label_allowed(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    if _is_within_recipe_span(candidate):
        return True
    if not (
        _looks_direct_instruction_start(candidate)
        or _looks_instructional_neighbor(candidate)
    ):
        return False
    return _outside_span_has_neighboring_component_structure(
        candidate,
        by_atomic_index=by_atomic_index,
    )


def _howto_section_fallback_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> str:
    howto_prose_label, _ = _classify_non_heading_howto_prose(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if howto_prose_label is not None:
        return howto_prose_label
    text = str(candidate.text or "").strip()
    if _looks_variant_heading_text(text):
        return "RECIPE_VARIANT"
    if _is_outside_recipe_span(candidate):
        return _outside_span_nonstructured_fallback_label(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    return "OTHER"


def _instruction_line_fallback_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> str:
    text = str(candidate.text or "").strip()
    if _looks_recipe_note_prose(text) or _looks_storage_or_serving_note(text):
        return "RECIPE_NOTES"
    if _looks_knowledge_prose_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ) or _looks_knowledge_heading_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "KNOWLEDGE"
    if _looks_narrative_prose(text):
        return "OTHER"
    if _is_outside_recipe_span(candidate):
        return _outside_span_nonstructured_fallback_label(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    return "OTHER"


def _variant_fallback_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> str:
    howto_prose_label, _ = _classify_non_heading_howto_prose(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if howto_prose_label is not None and howto_prose_label != "RECIPE_VARIANT":
        return howto_prose_label
    if _looks_recipe_title_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "RECIPE_TITLE"
    if _looks_obvious_ingredient(candidate):
        return "INGREDIENT_LINE"
    if _instruction_line_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "INSTRUCTION_LINE"
    if _looks_storage_or_serving_note(candidate.text) or _looks_recipe_note_prose(
        candidate.text
    ):
        return "RECIPE_NOTES"
    if _is_outside_recipe_span(candidate):
        return _outside_span_nonstructured_fallback_label(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    if _looks_direct_instruction_start(candidate) or _looks_instructional_neighbor(
        candidate
    ):
        return "INSTRUCTION_LINE"
    return "OTHER"

def _is_primary_time_line(text: str) -> bool:
    if _TIME_PREFIX_RE.search(text):
        return True
    if _INSTRUCTION_VERB_RE.match(text):
        return False
    words = _PROSE_WORD_RE.findall(text)
    if len(words) <= 8 and re.search(
        r"\b\d+\s*(?:sec|secs|second|seconds|min|mins|minute|minutes|hour|hours)\b",
        text,
        re.IGNORECASE,
    ):
        return True
    return False


def _looks_prose(text: str) -> bool:
    words = _PROSE_WORD_RE.findall(text)
    if len(words) < 10:
        return False
    if _QUANTITY_LINE_RE.match(text):
        return False
    if _INSTRUCTION_VERB_RE.match(text):
        return False
    return "." in text or "," in text


def _knowledge_allowed_inside_recipe(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    if not _is_within_recipe_span(candidate):
        return True
    if not _has_explicit_prose_tag(candidate):
        return False
    prev_candidate = by_atomic_index.get(candidate.atomic_index - 1)
    next_candidate = by_atomic_index.get(candidate.atomic_index + 1)
    if prev_candidate is None or next_candidate is None:
        return False
    return _has_explicit_prose_tag(prev_candidate) and _has_explicit_prose_tag(
        next_candidate
    )


def _has_explicit_prose_tag(candidate: AtomicLineCandidate) -> bool:
    return "explicit_prose" in {str(tag) for tag in candidate.rule_tags}


def _looks_obvious_ingredient(candidate: AtomicLineCandidate) -> bool:
    tags = {str(tag) for tag in candidate.rule_tags}
    if "ingredient_like" in tags:
        return True
    text = str(candidate.text or "")
    if _QUANTITY_LINE_RE.match(text) and _INGREDIENT_UNIT_RE.search(text):
        return True
    return False


def _looks_quantity_unit_fragment(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if not _QUANTITY_LINE_RE.match(stripped):
        return False
    if not _INGREDIENT_UNIT_RE.search(stripped):
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    return 1 <= len(words) <= 4


def _looks_short_ingredient_name_fragment(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _QUANTITY_LINE_RE.match(stripped):
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        return False
    if _TIME_PREFIX_RE.search(stripped):
        return False
    if re.search(
        r"\b\d+\s*(?:sec|secs|second|seconds|min|mins|minute|minutes|hour|hours)\b",
        stripped,
        re.IGNORECASE,
    ):
        return False
    if any(ch in stripped for ch in ",;:.!?"):
        return False
    if not _INGREDIENT_NAME_FRAGMENT_RE.match(stripped):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if not (1 <= len(words) <= 3):
        return False
    lowered = {word.lower() for word in words}
    return not lowered.issubset(_INGREDIENT_FRAGMENT_STOPWORDS)


def _neighbor_is_ingredient_dominant(candidate: AtomicLineCandidate | None) -> bool:
    if candidate is None:
        return False
    tags = {str(tag) for tag in candidate.rule_tags}
    if "ingredient_like" in tags:
        return True
    if _looks_obvious_ingredient(candidate):
        return True
    return False


def _should_rescue_neighbor_ingredient_fragment(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    if _is_outside_recipe_span(candidate):
        return False
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if text[-1:] in {".", "!", "?"}:
        return False

    quantity_fragment = _looks_quantity_unit_fragment(text)
    short_name_fragment = _looks_short_ingredient_name_fragment(text)
    if not (quantity_fragment or short_name_fragment):
        return False

    prev_candidate = by_atomic_index.get(candidate.atomic_index - 1)
    next_candidate = by_atomic_index.get(candidate.atomic_index + 1)
    neighbors = [row for row in (prev_candidate, next_candidate) if row is not None]
    if not neighbors:
        return False

    ingredient_neighbor_count = sum(
        1 for row in neighbors if _neighbor_is_ingredient_dominant(row)
    )
    if ingredient_neighbor_count <= 0:
        return False

    if short_name_fragment:
        has_adjacent_quantity_fragment = any(
            _looks_quantity_unit_fragment(str(row.text or "")) for row in neighbors
        )
        if not has_adjacent_quantity_fragment:
            return ingredient_neighbor_count >= 2
    return True


def _looks_recipe_title(text: str) -> bool:
    stripped = str(text or "").strip()
    words = _PROSE_WORD_RE.findall(stripped)
    if not words or len(words) < 2 or len(words) > 12:
        return False
    if _NOTE_PREFIX_RE.match(stripped):
        return False
    if _YIELD_PREFIX_RE.match(stripped):
        return False
    if _HOWTO_PREFIX_RE.match(stripped):
        return False
    if _HOW_TO_TITLE_PREFIX_RE.match(stripped):
        return False
    if _NUMBERED_STEP_RE.match(stripped):
        return False
    if _QUANTITY_LINE_RE.match(stripped):
        return False
    if _TIME_PREFIX_RE.search(stripped):
        return False
    if stripped[-1:] in {".", "!", "?"}:
        return False
    uppercase_words = sum(1 for word in words if word.upper() == word)
    title_case_words = sum(1 for word in words if word[:1].isupper())
    lowercase_connector_words = sum(
        1
        for word in words
        if word.islower() and word.lower() in _TITLE_CONNECTOR_WORDS
    )
    heading_like = uppercase_words >= max(2, len(words) // 2) or title_case_words >= max(
        2, len(words) - 1
    )
    if not heading_like and title_case_words >= 2:
        heading_like = (title_case_words + lowercase_connector_words) == len(words)
    if not heading_like:
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        alpha_chars = sum(1 for ch in stripped if ch.isalpha())
        uppercase_chars = sum(1 for ch in stripped if ch.isupper())
        uppercase_ratio = (uppercase_chars / alpha_chars) if alpha_chars else 0.0
        if len(words) < 4 and uppercase_ratio < 0.72:
            return False
    return True


def _looks_recipe_title_with_context(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if not _looks_recipe_title(candidate.text):
        return False
    if by_atomic_index is None:
        return _looks_compact_heading(candidate.text)
    saw_neighbor = False
    for offset in range(1, 4):
        next_candidate = by_atomic_index.get(candidate.atomic_index + offset)
        if next_candidate is None:
            break
        saw_neighbor = True
        if _supports_recipe_title_context(next_candidate):
            return True
        if _is_within_recipe_span(candidate) and _is_recipe_note_context_line(next_candidate):
            return True
        if _is_skippable_title_context_line(
            next_candidate,
            title_text=str(candidate.text or ""),
        ):
            continue
        next_tags = {str(tag) for tag in next_candidate.rule_tags}
        next_text = str(next_candidate.text or "")
        if _looks_narrative_prose(next_text):
            return False
        if "outside_recipe_span" in next_tags and _looks_prose(next_text):
            return False
        break
    if not saw_neighbor and _is_within_recipe_span(candidate):
        return True
    return False


def _looks_subsection_heading_context(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if by_atomic_index is None:
        return False
    return _howto_section_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    )


def _supports_recipe_title_context(candidate: AtomicLineCandidate) -> bool:
    tags = {str(tag) for tag in candidate.rule_tags}
    if _looks_recipe_start_boundary(candidate):
        return True
    if _neighbor_is_ingredient_dominant(candidate) and not _looks_table_of_contents_entry(
        str(candidate.text or "")
    ):
        return True
    if _looks_direct_instruction_start(candidate):
        return True
    return bool(
        {
            "yield_prefix",
            "howto_heading",
        }
        & tags
    )


def _is_skippable_title_context_line(
    candidate: AtomicLineCandidate,
    *,
    title_text: str,
) -> bool:
    text = str(candidate.text or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered == str(title_text or "").strip().lower():
        return True
    if _looks_note_text(text):
        return True
    if _looks_editorial_note(text):
        return True
    return _looks_recipe_note_prose(text)


def _is_recipe_note_context_line(candidate: AtomicLineCandidate) -> bool:
    text = str(candidate.text or "").strip()
    if not text:
        return False
    tags = {str(tag) for tag in candidate.rule_tags}
    if "note_like_prose" in tags:
        return True
    return (
        _looks_note_text(text)
        or _looks_editorial_note(text)
        or _looks_recipe_note_prose(text)
    )


def _looks_direct_instruction_start(candidate: AtomicLineCandidate) -> bool:
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if _NUMBERED_STEP_RE.match(text):
        return True
    if _INSTRUCTION_VERB_RE.match(text):
        return True
    if _INSTRUCTION_LEADIN_RE.match(text) and _RECIPE_ACTION_CUE_RE.search(text):
        return True
    return False


def _looks_table_of_contents_entry(text: str) -> bool:
    stripped = str(text or "").strip()
    if not re.match(r"^\d+\s+", stripped):
        return False
    lowered = stripped.lower()
    if "science of" in lowered:
        return True
    words = _PROSE_WORD_RE.findall(stripped)
    uppercase_words = sum(1 for word in words if word.upper() == word)
    return len(words) >= 4 and uppercase_words >= 2


def _outside_span_variant_should_be_recipe_title(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if by_atomic_index is None:
        return False
    stripped = str(candidate.text or "").strip()
    lowered = stripped.lower()
    if not stripped:
        return False
    if lowered in _VARIANT_EXPLICIT_HEADINGS or lowered.startswith("with "):
        return False
    return _looks_recipe_title_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    )


def _looks_recipe_start_boundary(candidate: AtomicLineCandidate) -> bool:
    tags = {str(tag) for tag in candidate.rule_tags}
    if "yield_prefix" in tags:
        return True
    return bool(_YIELD_PREFIX_RE.match(str(candidate.text or "")))


def _looks_recipe_flow_neighbor(candidate: AtomicLineCandidate | None) -> bool:
    if candidate is None:
        return False
    tags = {str(tag) for tag in candidate.rule_tags}
    if {
        "ingredient_like",
        "instruction_like",
        "instruction_with_time",
        "howto_heading",
        "yield_prefix",
    } & tags:
        return True
    if _looks_obvious_ingredient(candidate):
        return True
    if _looks_instructional_neighbor(candidate):
        return True
    return False


def _looks_instructional_neighbor(candidate: AtomicLineCandidate) -> bool:
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if _INSTRUCTION_VERB_RE.match(text):
        return True
    if _RECIPE_ACTION_CUE_RE.match(text):
        return True
    if _FIRST_PERSON_RE.search(text):
        return False
    if _INSTRUCTION_LEADIN_RE.match(text) and _RECIPE_ACTION_CUE_RE.search(text):
        return True
    if "." in text and _RECIPE_ACTION_CUE_RE.search(text):
        return True
    return False


def _looks_compact_heading(text: str) -> bool:
    stripped = str(text or "").strip()
    words = _PROSE_WORD_RE.findall(stripped)
    if len(words) < 2 or len(words) > 5:
        return False
    alpha_chars = sum(1 for ch in stripped if ch.isalpha())
    if alpha_chars <= 0:
        return False
    uppercase_chars = sum(1 for ch in stripped if ch.isupper())
    return (uppercase_chars / alpha_chars) >= 0.68


def _looks_howto_heading_shape(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or not _HOWTO_PREFIX_RE.match(stripped):
        return False
    if stripped[-1:] in {".", "!", "?"}:
        return False
    heading_text = stripped[:-1].rstrip() if stripped.endswith(":") else stripped
    if not heading_text:
        return False
    if any(mark in heading_text for mark in ",;()"):
        return False
    words = _PROSE_WORD_RE.findall(heading_text)
    if not (2 <= len(words) <= 8):
        return False
    if len(heading_text) > 72:
        return False
    return True


def _looks_non_heading_howto_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    return (
        bool(stripped)
        and _HOWTO_PREFIX_RE.match(stripped) is not None
        and not _looks_howto_heading_shape(stripped)
    )


def _looks_note_text(text: str) -> bool:
    return bool(_NOTE_PREFIX_RE.match(text))


def _normalized_variant_heading_text(text: str) -> str:
    return str(text or "").strip().rstrip(":").lower()


def _looks_variant_heading_text(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _looks_note_text(stripped):
        return False
    if _YIELD_PREFIX_RE.match(stripped):
        return False
    if _HOWTO_PREFIX_RE.match(stripped):
        return False
    if _NUMBERED_STEP_RE.match(stripped):
        return False
    if _QUANTITY_LINE_RE.match(stripped):
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        return False
    if _TIME_PREFIX_RE.search(stripped):
        return False
    if stripped[-1:] in {".", "!", "?"}:
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if not words or len(words) > 8:
        return False
    lowered = _normalized_variant_heading_text(stripped)
    if lowered in _VARIANT_EXPLICIT_HEADINGS:
        return True
    if lowered.startswith("with "):
        return True
    upper_text = stripped.upper()
    if any(upper_text.endswith(suffix) for suffix in _VARIANT_RECIPE_SUFFIXES):
        alpha_chars = sum(1 for ch in stripped if ch.isalpha())
        uppercase_chars = sum(1 for ch in stripped if ch.isupper())
        uppercase_ratio = (uppercase_chars / alpha_chars) if alpha_chars else 0.0
        return uppercase_ratio >= 0.70
    return False


def _looks_named_variant_recipe_name_prefix(text: str) -> bool:
    stripped = str(text or "").strip()
    match = re.match(r"^\s*To make\s+(.+)$", stripped, re.IGNORECASE)
    if match is None:
        return False
    remainder = match.group(1).strip()
    if not remainder:
        return False
    words = _PROSE_WORD_RE.findall(remainder)
    if len(words) < 2:
        return False
    lead_words = list(words[:6])
    while lead_words and lead_words[0].lower() in {"a", "an", "the"}:
        lead_words.pop(0)
    if len(lead_words) < 2:
        return False
    capitalized_word_count = 0
    consumed_any = False
    for word in lead_words:
        lowered = word.lower()
        if word[:1].isupper() or word.upper() == word:
            capitalized_word_count += 1
            consumed_any = True
            continue
        if consumed_any and lowered in _TITLE_CONNECTOR_WORDS:
            continue
        break
    return capitalized_word_count >= 2


def _looks_generic_to_make_step(text: str) -> bool:
    stripped = str(text or "").strip()
    if not (
        stripped.lower().startswith("to make ")
        and _looks_non_heading_howto_prose(stripped)
    ):
        return False
    if _looks_named_variant_recipe_name_prefix(stripped):
        return False
    remainder = stripped[8:].strip()
    words = _PROSE_WORD_RE.findall(remainder)
    if not words:
        return False
    first_word = words[0]
    if first_word.lower() in {"the", "this", "these", "those", "your"}:
        return True
    return first_word[:1].islower()


def _looks_explicit_variant_prose(text: str) -> bool:
    lowered = f" {str(text or '').strip().lower()} "
    return any(
        cue in lowered
        for cue in (
            " substitute ",
            " instead",
            " variation",
            " variations",
            " version",
            " omit ",
            " skip ",
            " swap ",
        )
    )


def _looks_variant_adjustment_leadin(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    if lowered.startswith("to add ") and "," in lowered:
        return True
    if lowered.startswith("to evoke ") and "," in lowered:
        return True
    if lowered.startswith("to make it ") and "," in lowered:
        return True
    return False


def _has_neighboring_variant_heading(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
    radius: int = 2,
) -> bool:
    center = int(candidate.atomic_index)
    for offset in range(1, max(1, int(radius)) + 1):
        for neighbor_index in (center - offset, center + offset):
            neighbor = by_atomic_index.get(neighbor_index)
            if neighbor is None:
                continue
            if _looks_variant_heading_text(neighbor.text):
                return True
    return False


def _looks_variant_run_body_line(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    text = str(candidate.text or "").strip()
    lowered = text.lower()
    if not text:
        return False
    if _looks_obvious_ingredient(candidate):
        return True
    if lowered.startswith("to make ") and _looks_non_heading_howto_prose(text):
        if _looks_named_variant_recipe_name_prefix(text):
            return True
        return _looks_explicit_variant_prose(text)
    if _looks_variant_adjustment_leadin(text):
        return True
    if _looks_direct_instruction_start(candidate) or _looks_instructional_neighbor(
        candidate
    ):
        return _looks_explicit_variant_prose(text) or _looks_variant_adjustment_leadin(
            text
        )
    if not _looks_prose(text):
        return False
    if (
        _looks_editorial_note(text)
        or _looks_narrative_prose(text)
        or _looks_book_framing_or_exhortation_prose(text)
        or _outside_recipe_knowledge_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        return False
    if _looks_named_variant_recipe_name_prefix(text):
        return True
    if lowered.startswith("if you don't have "):
        return True
    if lowered.startswith("for ") and "," in text:
        return True
    return _looks_explicit_variant_prose(text)


def _variant_heading_label_allowed(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    text = str(candidate.text or "").strip()
    if not _looks_variant_heading_text(text):
        return False
    if _normalized_variant_heading_text(text) not in _VARIANT_GENERIC_HEADINGS:
        return True
    if by_atomic_index is None:
        return False
    center = int(candidate.atomic_index)
    for offset in range(1, 3):
        for neighbor_index in (center - offset, center + offset):
            neighbor = by_atomic_index.get(neighbor_index)
            if neighbor is None:
                continue
            if _looks_variant_run_body_line(
                neighbor,
                by_atomic_index=by_atomic_index,
            ):
                return True
    return False


def _looks_variant_run_anchor(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    text = str(candidate.text or "").strip()
    lowered = text.lower()
    if (
        _normalized_variant_heading_text(text) in _VARIANT_GENERIC_HEADINGS
        and _variant_heading_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        return True
    if not (lowered.startswith("to make ") and _looks_non_heading_howto_prose(text)):
        return False
    if _is_within_recipe_span(candidate):
        return True
    if _looks_named_variant_recipe_name_prefix(text):
        return True
    return _outside_span_has_neighboring_component_structure(
        candidate,
        by_atomic_index=by_atomic_index,
    ) or _has_neighboring_variant_heading(
        candidate,
        by_atomic_index=by_atomic_index,
    )


def _is_within_variant_run(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
    max_distance: int = 6,
) -> bool:
    if _looks_variant_run_anchor(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return False
    if not _looks_variant_run_body_line(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return False
    center = int(candidate.atomic_index)
    for offset in range(1, max(1, int(max_distance)) + 1):
        previous = by_atomic_index.get(center - offset)
        if previous is None:
            break
        if _looks_variant_run_anchor(
            previous,
            by_atomic_index=by_atomic_index,
        ):
            return True
        if not _looks_variant_run_body_line(
            previous,
            by_atomic_index=by_atomic_index,
        ):
            break
    return False


def _variant_label_allowed(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    howto_prose_label, _ = _classify_non_heading_howto_prose(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if howto_prose_label == "RECIPE_VARIANT":
        return True
    variant_context_label, _ = _classify_variant_run_context(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    return variant_context_label == "RECIPE_VARIANT"


def _looks_editorial_note(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _looks_note_text(stripped):
        return True
    if _QUANTITY_LINE_RE.match(stripped):
        return False
    if _NUMBERED_STEP_RE.match(stripped):
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if len(words) < 8:
        return False
    lowered = stripped.lower()
    if any(lowered.startswith(prefix) for prefix in _EDITORIAL_NOTE_PREFIXES):
        return True
    if lowered.startswith("you ") and "want" in lowered and len(words) >= 10:
        return True
    return False


def _looks_recipe_note_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _looks_storage_or_serving_note(stripped):
        return True
    lowered = stripped.lower()
    if any(lowered.startswith(prefix) for prefix in _NON_RECIPE_PROSE_PREFIXES):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if len(words) < 12:
        return False
    if not _RECIPE_CONTEXT_RE.search(stripped):
        return False
    if _FIRST_PERSON_RE.search(stripped):
        return bool(_RECIPE_NOTE_ADVISORY_CUE_RE.search(stripped))
    if "you can" in lowered or "make sure" in lowered:
        return True
    if "don't" in lowered or "it's important" in lowered:
        return True
    if "the key is" in lowered:
        return True
    if any(
        lowered.startswith(prefix)
        for prefix in ("well,", "but ", "whatever liquid you choose")
    ):
        return True
    return False


def _looks_storage_or_serving_note(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _QUANTITY_LINE_RE.match(stripped):
        return False
    lowered = stripped.lower()
    if _STORAGE_NOTE_PREFIX_RE.match(stripped):
        return True
    if not _SERVING_NOTE_PREFIX_RE.match(stripped):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if not words or len(words) > 40:
        return False
    if "ideal for everyday cooking" in lowered:
        return False
    if "ideal for use in food" in lowered:
        return False
    return any(
        cue in lowered
        for cue in (
            "salad",
            "slaw",
            "lettuce",
            "lettuces",
            "vegetable",
            "vegetables",
            "fish",
            "chicken",
            "bread",
            "dip",
            "dipping",
            "drizzling",
            "drizzle",
            "sauce",
            "steak",
            "cucumber",
            "cucumbers",
            "tomato",
            "tomatoes",
            "leftover",
            "leftovers",
        )
    )


def _looks_narrative_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or not _looks_prose(stripped):
        return False
    lowered = stripped.lower()
    if any(lowered.startswith(prefix) for prefix in _NON_RECIPE_PROSE_PREFIXES):
        return True
    if _FIRST_PERSON_SINGULAR_RE.search(stripped):
        return not (
            _looks_explicit_knowledge_cue(stripped)
            or _looks_domain_knowledge_prose(stripped)
            or _looks_pedagogical_knowledge_prose(stripped)
        )
    if _FIRST_PERSON_RE.search(stripped) and not (
        _looks_explicit_knowledge_cue(stripped)
        or _looks_domain_knowledge_prose(stripped)
        or _looks_pedagogical_knowledge_prose(stripped)
    ):
        return True
    return False


def _looks_book_framing_or_exhortation_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or not _looks_prose(stripped):
        return False
    if _looks_editorial_note(stripped) or _looks_recipe_note_prose(stripped):
        return False
    lowered = stripped.lower()
    second_person_count = len(_SECOND_PERSON_RE.findall(stripped))
    if "this book" in lowered and _FIRST_PERSON_RE.search(stripped):
        return True
    if _BOOK_FRAMING_EXHORTATION_CUE_RE.search(stripped):
        return True
    if (
        second_person_count >= 2
        and any(
            cue in lowered
            for cue in (
                "better",
                "learn",
                "teach",
                "for you",
                "pay attention",
            )
        )
        and not _KNOWLEDGE_EXPLANATION_CUE_RE.search(stripped)
    ):
        return True
    if (
        (_INSTRUCTION_VERB_RE.match(stripped) or lowered.startswith("let "))
        and second_person_count >= 1
        and not _KNOWLEDGE_EXPLANATION_CUE_RE.search(stripped)
    ):
        return True
    return False


def _knowledge_domain_cue_count(text: str) -> int:
    return len(
        {match.group(0).lower() for match in _KNOWLEDGE_DOMAIN_CUE_RE.finditer(text)}
    )


def _looks_domain_knowledge_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _looks_editorial_note(stripped) or _looks_recipe_note_prose(stripped):
        return False
    domain_cues = _knowledge_domain_cue_count(stripped)
    if domain_cues <= 0:
        return False
    if _looks_prose(stripped) and _KNOWLEDGE_EXPLANATION_CUE_RE.search(stripped):
        return True
    words = _PROSE_WORD_RE.findall(stripped)
    if (
        3 <= len(words) <= 10
        and _KNOWLEDGE_EXPLANATION_CUE_RE.search(stripped)
        and not _INSTRUCTION_VERB_RE.match(stripped)
        and not _QUANTITY_LINE_RE.match(stripped)
    ):
        return True
    if not _looks_prose(stripped):
        return False
    if _KNOWLEDGE_EXPLANATION_CUE_RE.search(stripped):
        return True
    return False


def _looks_knowledge_heading_shape(text: str) -> bool:
    stripped = str(text or "").strip()
    words = _PROSE_WORD_RE.findall(stripped)
    if not (1 <= len(words) <= 6):
        return False
    if _QUANTITY_LINE_RE.match(stripped):
        return False
    if _NOTE_PREFIX_RE.match(stripped):
        return False
    if _YIELD_PREFIX_RE.match(stripped):
        return False
    if stripped[-1:] in {".", "!"}:
        return False
    uppercase_words = sum(1 for word in words if word.upper() == word)
    title_case_words = sum(1 for word in words if word[:1].isupper())
    lowercase_connector_words = sum(
        1
        for word in words
        if word.islower() and word.lower() in _TITLE_CONNECTOR_WORDS
    )
    return uppercase_words == len(words) or (
        title_case_words + lowercase_connector_words
    ) == len(words)


def _looks_obvious_knowledge_heading(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or not _looks_knowledge_heading_shape(stripped):
        return False
    lowered = stripped.rstrip("?").lower()
    if _PEDAGOGICAL_KNOWLEDGE_HEADING_RE.match(lowered):
        return True
    if _KNOWLEDGE_HEADING_FORM_RE.match(lowered):
        return True
    return False


def _looks_knowledge_heading_with_context(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if _is_within_recipe_span(candidate):
        return False
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if _looks_obvious_knowledge_heading(text):
        return True
    if by_atomic_index is None:
        return False
    if not _looks_knowledge_heading_shape(text):
        return False
    for offset in (-1, 1):
        neighbor = by_atomic_index.get(int(candidate.atomic_index) + offset)
        if neighbor is None or _is_within_recipe_span(neighbor):
            continue
        neighbor_text = str(neighbor.text or "")
        if _looks_domain_knowledge_prose(neighbor_text) or _looks_explicit_knowledge_cue(
            neighbor_text
        ):
            return True
    return False


def _looks_endorsement_credit(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if not stripped.startswith("-"):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if not (5 <= len(words) <= 18):
        return False
    lowered = stripped.lower()
    return any(
        cue in lowered
        for cue in (
            "author of",
            "bestselling author",
            "chef",
            "co-founder",
            "cofounder",
            "editor",
            "founder",
            "steward of",
            "stewards of",
        )
    )


def _looks_pedagogical_knowledge_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or not _looks_prose(stripped):
        return False
    if _looks_editorial_note(stripped) or _looks_recipe_note_prose(stripped):
        return False
    if _looks_book_framing_or_exhortation_prose(stripped):
        return False
    lowered = stripped.lower()
    if not any(
        cue in lowered
        for cue in ("book", "cook", "cooking", "kitchen", "meal", "recipe")
    ):
        return False
    if not _PEDAGOGICAL_KNOWLEDGE_CUE_RE.search(stripped):
        return False
    return bool(
        _KNOWLEDGE_EXPLANATION_CUE_RE.search(stripped)
        or _EXPLICIT_KNOWLEDGE_CUE_RE.search(stripped)
    )


def _looks_knowledge_prose_with_context(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    text = str(candidate.text or "").strip()
    if (
        _looks_narrative_prose(text)
        or _looks_endorsement_credit(text)
        or _looks_book_framing_or_exhortation_prose(text)
    ):
        return False
    if (
        _looks_explicit_knowledge_cue(text)
        or _looks_domain_knowledge_prose(text)
        or _looks_pedagogical_knowledge_prose(text)
    ):
        return True
    if by_atomic_index is None:
        return False
    words = _PROSE_WORD_RE.findall(text)
    if _looks_prose(text) and len(words) > 8 and not _looks_knowledge_heading_shape(text):
        return False
    for offset in (-1, 1):
        neighbor = by_atomic_index.get(int(candidate.atomic_index) + offset)
        if neighbor is None or _is_within_recipe_span(neighbor):
            continue
        neighbor_text = str(neighbor.text or "")
        if _looks_explicit_knowledge_cue(neighbor_text) or _looks_domain_knowledge_prose(
            neighbor_text
        ):
            return True
        if _looks_knowledge_heading_with_context(
            neighbor,
            by_atomic_index=by_atomic_index,
        ):
            return True
    return False


def _outside_recipe_knowledge_label_allowed(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if _is_within_recipe_span(candidate):
        return False
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if (
        _looks_recipe_note_prose(text)
        or _looks_editorial_note(text)
        or _looks_endorsement_credit(text)
        or _looks_narrative_prose(text)
        or _looks_book_framing_or_exhortation_prose(text)
    ):
        return False
    return _looks_knowledge_heading_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ) or _looks_knowledge_prose_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    )


def _looks_strict_yield_header(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    match = _YIELD_PREFIX_RE.match(stripped)
    if match is None:
        return False
    if stripped[-1:] in {".", "!", "?"}:
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if not (1 <= len(words) <= 10):
        return False
    if len(stripped) > 72:
        return False
    suffix = stripped[match.end() :].strip(" :-")
    if not suffix:
        return False
    return bool(_YIELD_COUNT_HINT_RE.search(suffix))


def _yield_fallback_label(candidate: AtomicLineCandidate) -> str:
    text = str(candidate.text or "").strip()
    lowered = text.lower()
    if _INSTRUCTION_VERB_RE.match(text) or lowered.startswith("serves "):
        return "OTHER" if _is_outside_recipe_span(candidate) else "INSTRUCTION_LINE"
    if _looks_recipe_note_prose(text) or _looks_editorial_note(text):
        return "RECIPE_NOTES"
    return "OTHER"


def _looks_explicit_knowledge_cue(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    return bool(_EXPLICIT_KNOWLEDGE_CUE_RE.search(stripped))


def _parse_codex_line_role_response(
    raw_response: str,
    *,
    requested: Sequence[AtomicLineCandidate],
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        return [], f"invalid_json:{exc.msg}"
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            payload = rows
    if not isinstance(payload, list):
        return [], "payload_not_list"

    requested_indices = [int(candidate.atomic_index) for candidate in requested]
    requested_by_index = {
        int(candidate.atomic_index): candidate for candidate in requested
    }
    seen: set[int] = set()
    parsed: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            return [], "row_not_object"
        raw_index = row.get("atomic_index")
        try:
            atomic_index = int(raw_index)
        except (TypeError, ValueError):
            return [], "missing_or_invalid_atomic_index"
        if atomic_index in seen:
            return [], "duplicate_atomic_index"
        if atomic_index not in requested_indices:
            return [], "unexpected_atomic_index"
        normalized_label = normalize_freeform_label(str(row.get("label") or ""))
        if normalized_label not in FREEFORM_ALLOWED_LABELS:
            return [], f"unknown_label:{normalized_label}"
        candidate = requested_by_index[atomic_index]
        review_exclusion_reason = row.get("review_exclusion_reason")
        try:
            normalized_review_exclusion_reason = _normalize_review_exclusion_reason(
                review_exclusion_reason
            )
        except ValueError as exc:
            return [], str(exc)
        if normalized_review_exclusion_reason is not None:
            if normalized_label != "OTHER":
                return [], "review_exclusion_reason_requires_other"
            if _is_within_recipe_span(candidate):
                return [], "review_exclusion_reason_requires_outside_recipe"
        seen.add(atomic_index)
        parsed.append(
            {
                "atomic_index": atomic_index,
                "label": normalized_label,
                "review_exclusion_reason": normalized_review_exclusion_reason,
            }
        )

    if seen != set(requested_indices):
        return [], "missing_atomic_index_rows"
    ordered_parsed = sorted(parsed, key=lambda row: requested_indices.index(row["atomic_index"]))
    return ordered_parsed, None


def _batch(
    rows: Sequence[AtomicLineCandidate],
    batch_size: int,
) -> list[list[AtomicLineCandidate]]:
    output: list[list[AtomicLineCandidate]] = []
    current: list[AtomicLineCandidate] = []
    for row in rows:
        current.append(row)
        if len(current) >= batch_size:
            output.append(current)
            current = []
    if current:
        output.append(current)
    return output
