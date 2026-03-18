from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

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
    build_canonical_line_role_prompt,
)
from cookimport.llm.codex_exec_runner import (
    DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
    CodexExecRunResult,
    CodexExecRunner,
    SubprocessCodexExecRunner,
    summarize_direct_telemetry_rows,
)
from cookimport.llm.codex_farm_runner import (
    CodexFarmRunnerError,
    resolve_codex_farm_output_schema_path,
)
from cookimport.llm.phase_worker_runtime import (
    PhaseManifestV1,
    ShardManifestEntryV1,
    ShardProposalV1,
    WorkerAssignmentV1,
    WorkerExecutionReportV1,
    resolve_phase_worker_count,
)
from cookimport.llm.shard_prompt_targets import resolve_items_per_shard
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate

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
    r"fold|grill|heat|mix|place|pour|reduce|remove|roast|season|serve|simmer|stir|"
    r"transfer|whisk)\b",
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
_VARIANT_EXPLICIT_HEADINGS = {"variation", "for a crowd"}
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
    r"kosher salt|mineral|minerals|moisture|protein|proteins|ratio|salt|"
    r"salinity|simmer|starch|starches|sweetness|taste|texture|textures|"
    r"vinegar|water)\b",
    re.IGNORECASE,
)
_KNOWLEDGE_EXPLANATION_CUE_RE = re.compile(
    r"\b(?:affect|affects|balance|balances|because|control|controls|"
    r"determine|determines|enhance|enhances|explained by|explains|improve|"
    r"improves|means|modify|modifies|relationship|role|this is why|"
    r"without|why)\b",
    re.IGNORECASE,
)
_PEDAGOGICAL_KNOWLEDGE_CUE_RE = re.compile(
    r"\b(?:better cook|cook every day|fundamental|fundamentals|lesson|lessons|"
    r"master|mastering|principle|principles|teach|teaches|teaching)\b",
    re.IGNORECASE,
)
_PEDAGOGICAL_KNOWLEDGE_HEADING_RE = re.compile(
    r"^(?:how to use\b|using recipes\b|kitchen basics\b|cooking lessons\b|"
    r"what to cook\b)$",
    re.IGNORECASE,
)
_KNOWLEDGE_HEADING_FORM_RE = re.compile(
    r"^(?:what is\b|how .+ works\b|using\b|.+ and flavor\b)$",
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
_LINE_ROLE_CACHE_SCHEMA_VERSION = "canonical_line_role_cache.v3"
_LINE_ROLE_CACHE_ROOT_ENV = "COOKIMPORT_LINE_ROLE_CACHE_ROOT"
_LINE_ROLE_PROGRESS_MAX_UPDATES = 100
_LINE_ROLE_CODEX_FARM_PIPELINE_ID = "line-role.canonical.v1"
_LINE_ROLE_CODEX_EXEC_DEFAULT_CMD = "codex exec"
_LINE_ROLE_DIRECT_RUNTIME_ARTIFACT_SCHEMA = "line_role.direct_worker_runtime.v1"
_CODEX_EXECUTABLES = {"codex", "codex.exe", "codex2", "codex2.exe"}
LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT = 240

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

    @model_validator(mode="after")
    def _normalize_metadata(self) -> "CanonicalLineRolePrediction":
        self.escalation_reasons = _unique_string_list(self.escalation_reasons)
        self.reason_tags = _unique_string_list(self.reason_tags)
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

    payload = prediction.model_dump(mode="python")
    payload["escalation_reasons"] = _unique_string_list(reasons)
    return CanonicalLineRolePrediction.model_validate(payload)


@dataclass(frozen=True)
class _LineRoleShardPlan:
    shard_id: str
    prompt_index: int
    candidates: tuple[AtomicLineCandidate, ...]
    baseline_predictions: tuple[CanonicalLineRolePrediction, ...]
    prompt_text: str
    manifest_entry: ShardManifestEntryV1


@dataclass(frozen=True)
class _LineRoleRuntimeResult:
    predictions_by_atomic_index: dict[int, CanonicalLineRolePrediction]
    shard_plans: tuple[_LineRoleShardPlan, ...]
    worker_reports: tuple[WorkerExecutionReportV1, ...]
    runner_results_by_shard_id: dict[str, dict[str, Any]]
    invalid_shard_count: int
    missing_output_shard_count: int
    runtime_root: Path | None


@dataclass(frozen=True)
class _DirectLineRoleWorkerResult:
    report: WorkerExecutionReportV1
    proposals: tuple[ShardProposalV1, ...]
    failures: tuple[dict[str, Any], ...]
    stage_rows: tuple[dict[str, Any], ...]
    runner_results_by_shard_id: dict[str, dict[str, Any]]


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


def build_line_role_codex_execution_plan(
    candidates: Sequence[AtomicLineCandidate],
    settings: RunSettings,
    *,
    codex_batch_size: int = LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT,
) -> dict[str, Any]:
    ordered = list(candidates)
    mode = _line_role_pipeline_name(settings)
    if mode != LINE_ROLE_PIPELINE_SHARD_V1:
        return {
            "enabled": False,
            "pipeline": mode,
            "candidate_count": len(ordered),
            "planned_shard_count": 0,
            "planned_candidate_count": 0,
            "shards": [],
        }
    deterministic_baseline = _build_line_role_deterministic_baseline(
        ordered_candidates=ordered
    )
    shard_plans = _build_line_role_shard_plans(
        ordered_candidates=ordered,
        deterministic_baseline=deterministic_baseline,
        settings=settings,
        codex_batch_size=codex_batch_size,
    )
    planned_shards = [
        {
            "shard_id": plan.shard_id,
            "prompt_index": plan.prompt_index,
            "candidate_count": len(plan.candidates),
            "atomic_indices": [int(candidate.atomic_index) for candidate in plan.candidates],
            "owned_ids": list(plan.manifest_entry.owned_ids),
            "rows": [
                _line_role_plan_row(
                    candidate=candidate,
                    baseline_prediction=deterministic_baseline[int(candidate.atomic_index)],
                )
                for candidate in plan.candidates
            ],
        }
        for plan in shard_plans
    ]

    return {
        "enabled": True,
        "pipeline": mode,
        "candidate_count": len(ordered),
        "planned_candidate_count": len(ordered),
        "planned_shard_count": len(planned_shards),
        "line_role_shard_target_lines": _resolve_line_role_shard_target_lines(
            settings=settings,
            codex_batch_size=codex_batch_size,
            total_candidates=len(ordered),
        ),
        "shards": planned_shards,
    }


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


def _line_role_plan_row(
    *,
    candidate: AtomicLineCandidate,
    baseline_prediction: CanonicalLineRolePrediction,
) -> dict[str, Any]:
    return {
        "atomic_index": int(candidate.atomic_index),
        "block_index": int(candidate.block_index),
        "block_id": str(candidate.block_id),
        "recipe_id": candidate.recipe_id,
        "within_recipe_span": candidate.within_recipe_span,
        "deterministic_label": str(baseline_prediction.label or "OTHER"),
        "rule_tags": list(candidate.rule_tags),
        "escalation_reasons": list(baseline_prediction.escalation_reasons),
        "prev_text": candidate.prev_text,
        "current_line": str(candidate.text),
        "next_text": candidate.next_text,
    }


def _build_line_role_shard_plans(
    *,
    ordered_candidates: Sequence[AtomicLineCandidate],
    deterministic_baseline: dict[int, CanonicalLineRolePrediction],
    settings: RunSettings,
    codex_batch_size: int,
) -> tuple[_LineRoleShardPlan, ...]:
    shard_target_lines = _resolve_line_role_shard_target_lines(
        settings=settings,
        codex_batch_size=codex_batch_size,
        total_candidates=len(ordered_candidates),
    )
    prompt_format = _resolve_line_role_prompt_format()
    plans: list[_LineRoleShardPlan] = []
    for prompt_index, shard_candidates in enumerate(
        _batch(ordered_candidates, max(1, int(shard_target_lines))),
        start=1,
    ):
        if not shard_candidates:
            continue
        baseline_batch = tuple(
            deterministic_baseline[int(candidate.atomic_index)]
            for candidate in shard_candidates
        )
        prompt_text = build_canonical_line_role_prompt(
            shard_candidates,
            prompt_format=prompt_format,
            deterministic_labels_by_atomic_index={
                int(prediction.atomic_index): prediction.label
                for prediction in baseline_batch
            },
            escalation_reasons_by_atomic_index={
                int(prediction.atomic_index): list(prediction.escalation_reasons)
                for prediction in baseline_batch
            },
        )
        first_atomic_index = int(shard_candidates[0].atomic_index)
        last_atomic_index = int(shard_candidates[-1].atomic_index)
        shard_id = (
            f"line-role-shard-{prompt_index:04d}-"
            f"a{first_atomic_index:06d}-a{last_atomic_index:06d}"
        )
        manifest_entry = ShardManifestEntryV1(
            shard_id=shard_id,
            owned_ids=tuple(str(int(candidate.atomic_index)) for candidate in shard_candidates),
            evidence_refs=tuple(
                dict.fromkeys(str(candidate.block_id) for candidate in shard_candidates)
            ),
            input_payload={
                "shard_id": shard_id,
                "phase_key": "line_role",
                "rows": [
                    _line_role_plan_row(
                        candidate=candidate,
                        baseline_prediction=deterministic_baseline[int(candidate.atomic_index)],
                    )
                    for candidate in shard_candidates
                ],
            },
            input_text=prompt_text,
            metadata={
                "prompt_index": prompt_index,
                "first_atomic_index": first_atomic_index,
                "last_atomic_index": last_atomic_index,
                "owned_row_count": len(shard_candidates),
            },
        )
        plans.append(
            _LineRoleShardPlan(
                shard_id=shard_id,
                prompt_index=prompt_index,
                candidates=tuple(shard_candidates),
                baseline_predictions=baseline_batch,
                prompt_text=prompt_text,
                manifest_entry=manifest_entry,
            )
        )
    return tuple(plans)


def _resolve_line_role_shard_target_lines(
    *,
    settings: RunSettings,
    codex_batch_size: int,
    total_candidates: int | None = None,
) -> int:
    if total_candidates is not None and total_candidates > 0:
        return resolve_items_per_shard(
            total_items=total_candidates,
            prompt_target_count=getattr(settings, "line_role_prompt_target_count", None),
            items_per_shard=getattr(settings, "line_role_shard_target_lines", None),
            default_items_per_shard=codex_batch_size,
        )
    configured = getattr(settings, "line_role_shard_target_lines", None)
    resolved = getattr(configured, "value", configured)
    if resolved is not None:
        try:
            return max(1, int(resolved))
        except (TypeError, ValueError):
            pass
    return max(1, int(codex_batch_size))


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
    shard_plans = _build_line_role_shard_plans(
        ordered_candidates=ordered_candidates,
        deterministic_baseline=deterministic_baseline,
        settings=settings,
        codex_batch_size=codex_batch_size,
    )
    if not shard_plans:
        return _LineRoleRuntimeResult(
            predictions_by_atomic_index={},
            shard_plans=(),
            worker_reports=(),
            runner_results_by_shard_id={},
            invalid_shard_count=0,
            missing_output_shard_count=0,
            runtime_root=None,
        )

    prompt_state = _PromptArtifactState(artifact_root=artifact_root)
    for shard_plan in shard_plans:
        prompt_state.write_prompt(
            prompt_index=shard_plan.prompt_index,
            prompt_text=shard_plan.prompt_text,
        )

    if not live_llm_allowed:
        prompt_state.finalize(parse_error_count=len(shard_plans))
        return _LineRoleRuntimeResult(
            predictions_by_atomic_index={},
            shard_plans=shard_plans,
            worker_reports=(),
            runner_results_by_shard_id={},
            invalid_shard_count=len(shard_plans),
            missing_output_shard_count=0,
            runtime_root=None,
        )

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
    output_schema_path = resolve_codex_farm_output_schema_path(
        root_dir=codex_farm_root,
        pipeline_id=_LINE_ROLE_CODEX_FARM_PIPELINE_ID,
    )
    if codex_runner is None:
        runner: CodexExecRunner = SubprocessCodexExecRunner(cmd=codex_exec_cmd)
    else:
        runner = codex_runner

    total_shards = len(shard_plans)
    worker_count = _resolve_line_role_worker_count(
        settings=settings,
        codex_max_inflight=codex_max_inflight,
        shard_count=total_shards,
    )
    _notify_line_role_progress(
        progress_callback=progress_callback,
        completed_tasks=0,
        total_tasks=total_shards,
        running_tasks=min(worker_count, total_shards),
        worker_total=worker_count,
    )
    runtime_root = (
        artifact_root / "line-role-pipeline" / "runtime"
        if artifact_root is not None
        else (
            codex_farm_workspace_root / "line-role-pipeline-runtime"
            if codex_farm_workspace_root is not None
            else Path.cwd() / ".tmp" / "line-role-pipeline-runtime"
        )
    )
    manifest, worker_reports, runner_results_by_shard_id = _run_line_role_direct_workers_v1(
        phase_key="line_role",
        pipeline_id=_LINE_ROLE_CODEX_FARM_PIPELINE_ID,
        run_root=runtime_root,
        shards=[plan.manifest_entry for plan in shard_plans],
        runner=runner,
        worker_count=worker_count,
        env={"CODEX_FARM_ROOT": str(codex_farm_root)},
        model=codex_farm_model,
        reasoning_effort=codex_farm_reasoning_effort,
        output_schema_path=output_schema_path,
        timeout_seconds=max(1, int(codex_timeout_seconds)),
        settings={
            "line_role_pipeline": LINE_ROLE_PIPELINE_SHARD_V1,
            "codex_timeout_seconds": int(codex_timeout_seconds),
            "line_role_shard_target_lines": _resolve_line_role_shard_target_lines(
                settings=settings,
                codex_batch_size=codex_batch_size,
                total_candidates=len(ordered_candidates),
            ),
        },
        runtime_metadata={
            "surface_pipeline": LINE_ROLE_PIPELINE_SHARD_V1,
            "workspace_root": (
                str(codex_farm_workspace_root)
                if codex_farm_workspace_root is not None
                else None
            ),
        },
        progress_callback=progress_callback,
    )
    if worker_reports:
        _notify_line_role_progress(
            progress_callback=progress_callback,
            completed_tasks=total_shards,
            total_tasks=total_shards,
            running_tasks=0,
            worker_total=worker_count,
        )

    predictions_by_atomic_index: dict[int, CanonicalLineRolePrediction] = {}
    invalid_shard_count = 0
    missing_output_shard_count = 0
    proposal_dir = Path(manifest.run_root) / "proposals"
    for shard_plan in shard_plans:
        proposal_path = proposal_dir / f"{shard_plan.shard_id}.json"
        if not proposal_path.exists():
            missing_output_shard_count += 1
            prompt_state.write_failure(
                prompt_index=shard_plan.prompt_index,
                error="missing_output_file",
            )
            continue
        try:
            proposal_payload = json.loads(proposal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            invalid_shard_count += 1
            prompt_state.write_failure(
                prompt_index=shard_plan.prompt_index,
                error="invalid_proposal_payload",
            )
            continue
        response_payload = proposal_payload.get("payload")
        validation_errors = proposal_payload.get("validation_errors") or []
        if validation_errors or not isinstance(response_payload, dict):
            invalid_shard_count += 1
            prompt_state.write_failure(
                prompt_index=shard_plan.prompt_index,
                error=";".join(str(item) for item in validation_errors) or "invalid_proposal",
                response_payload=response_payload,
            )
            continue
        prompt_state.write_response(
            prompt_index=shard_plan.prompt_index,
            response_payload=response_payload,
        )
        rows = response_payload.get("rows")
        if not isinstance(rows, list):
            invalid_shard_count += 1
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
            )
    prompt_state.finalize(parse_error_count=invalid_shard_count + missing_output_shard_count)
    return _LineRoleRuntimeResult(
        predictions_by_atomic_index=predictions_by_atomic_index,
        shard_plans=shard_plans,
        worker_reports=tuple(worker_reports),
        runner_results_by_shard_id=runner_results_by_shard_id,
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


def _notify_line_role_progress(
    *,
    progress_callback: Callable[[str], None] | None,
    completed_tasks: int,
    total_tasks: int,
    running_tasks: int | None = None,
    worker_total: int | None = None,
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
            task_current=completed,
            task_total=total,
            running_workers=running_tasks,
            worker_total=worker_total,
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


def _run_line_role_direct_worker_assignment_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: dict[str, str],
    shard_by_id: dict[str, ShardManifestEntryV1],
    runner: CodexExecRunner,
    pipeline_id: str,
    env: dict[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    timeout_seconds: int,
    shard_completed_callback: Callable[..., None] | None,
) -> _DirectLineRoleWorkerResult:
    worker_root = Path(assignment.workspace_root)
    in_dir = worker_root / "in"
    shard_dir = worker_root / "shards"
    logs_dir = worker_root / "logs"
    in_dir.mkdir(parents=True, exist_ok=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    assigned_shards = [shard_by_id[shard_id] for shard_id in assignment.shard_ids]
    _write_runtime_json(
        worker_root / "assigned_shards.json",
        [_line_role_asdict(shard) for shard in assigned_shards],
    )

    worker_failure_count = 0
    worker_proposal_count = 0
    worker_runner_results: list[dict[str, Any]] = []
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    stage_rows: list[dict[str, Any]] = []
    runner_results_by_shard_id: dict[str, dict[str, Any]] = {}

    for shard in assigned_shards:
        input_path = in_dir / f"{shard.shard_id}.json"
        _write_worker_debug_input(
            path=input_path,
            payload=shard.input_payload,
            input_text=None,
        )
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
        prompt_text = str(shard.input_text or "")
        (shard_root / "prompt.txt").write_text(prompt_text, encoding="utf-8")

        try:
            run_result = runner.run_structured_prompt(
                prompt_text=prompt_text,
                input_payload=_coerce_mapping_dict(shard.input_payload),
                working_dir=worker_root,
                env=env,
                output_schema_path=output_schema_path,
                model=model,
                reasoning_effort=reasoning_effort,
                timeout_seconds=timeout_seconds,
            )
        except CodexFarmRunnerError as exc:
            worker_failure_count += 1
            worker_failures.append(
                {
                    "worker_id": assignment.worker_id,
                    "shard_id": shard.shard_id,
                    "reason": "runner_failed",
                    "error": str(exc),
                }
            )
            worker_proposals.append(
                ShardProposalV1(
                    shard_id=shard.shard_id,
                    worker_id=assignment.worker_id,
                    status="missing_output",
                    proposal_path=None,
                    validation_errors=("runner_failed",),
                    metadata={"error": str(exc)},
                )
            )
            _write_runtime_json(
                shard_root / "status.json",
                {
                    "status": "runner_failed",
                    "error": str(exc),
                    "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                },
            )
            if shard_completed_callback is not None:
                shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)
            continue

        runner_payload = _build_line_role_runner_payload(
            pipeline_id=pipeline_id,
            worker_id=assignment.worker_id,
            shard_id=shard.shard_id,
            run_result=run_result,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        runner_results_by_shard_id[shard.shard_id] = dict(runner_payload)
        worker_runner_results.append(dict(runner_payload))
        telemetry = runner_payload.get("telemetry")
        row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
        if isinstance(row_payloads, list):
            for row_payload in row_payloads:
                if isinstance(row_payload, dict):
                    stage_rows.append(dict(row_payload))
        (shard_root / "events.jsonl").write_text(
            _render_codex_events_jsonl(run_result.events),
            encoding="utf-8",
        )
        _write_runtime_json(shard_root / "last_message.json", {"text": run_result.response_text})
        _write_runtime_json(shard_root / "usage.json", dict(run_result.usage or {}))

        payload: dict[str, Any] | None = None
        validation_errors: tuple[str, ...] = ()
        validation_metadata: dict[str, Any] = {}
        proposal_status = "validated"
        response_text = str(run_result.response_text or "").strip()
        if not response_text:
            validation_errors = ("missing_output_file",)
            proposal_status = "missing_output"
        else:
            try:
                parsed_payload = json.loads(response_text)
            except json.JSONDecodeError as exc:
                validation_errors = ("response_json_invalid",)
                validation_metadata = {"parse_error": str(exc)}
                proposal_status = "invalid"
            else:
                if isinstance(parsed_payload, dict):
                    payload = parsed_payload
                    valid, validation_errors, validation_metadata = _validate_line_role_shard_proposal(
                        shard,
                        parsed_payload,
                    )
                    proposal_status = "validated" if valid else "invalid"
                else:
                    validation_errors = ("response_not_json_object",)
                    validation_metadata = {"response_type": type(parsed_payload).__name__}
                    proposal_status = "invalid"

        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        wrapper_payload = {
            "shard_id": shard.shard_id,
            "worker_id": assignment.worker_id,
            "payload": payload,
            "validation_errors": list(validation_errors),
            "validation_metadata": dict(validation_metadata or {}),
        }
        _write_runtime_json(proposal_path, wrapper_payload)
        _write_runtime_json(
            shard_root / "proposal.json",
            payload
            if payload is not None
            else {
                "error": proposal_status,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
            },
        )
        _write_runtime_json(
            shard_root / "status.json",
            {
                "status": proposal_status,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
            },
        )

        if proposal_status != "validated":
            worker_failure_count += 1
            worker_failures.append(
                {
                    "worker_id": assignment.worker_id,
                    "shard_id": shard.shard_id,
                    "reason": (
                        "proposal_validation_failed"
                        if proposal_status == "invalid"
                        else "missing_output_file"
                    ),
                    "validation_errors": list(validation_errors),
                }
            )
        else:
            worker_proposal_count += 1

        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status=proposal_status,
                proposal_path=_relative_runtime_path(run_root, proposal_path),
                payload=payload,
                validation_errors=validation_errors,
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
                "output_schema_enforced": output_schema_path is not None,
                "tool_affordances_requested": False,
            },
            runner_result=worker_runner_payload,
            metadata={
                "in_dir": _relative_runtime_path(run_root, in_dir),
                "shards_dir": _relative_runtime_path(run_root, shard_dir),
                "log_dir": _relative_runtime_path(run_root, logs_dir),
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
        stage_rows=tuple(stage_rows),
        runner_results_by_shard_id=dict(runner_results_by_shard_id),
    )


def _run_line_role_direct_workers_v1(
    *,
    phase_key: str,
    pipeline_id: str,
    run_root: Path,
    shards: Sequence[ShardManifestEntryV1],
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
) -> tuple[PhaseManifestV1, list[WorkerExecutionReportV1], dict[str, dict[str, Any]]]:
    artifacts = {
        "phase_manifest": "phase_manifest.json",
        "shard_manifest": "shard_manifest.jsonl",
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
    _write_runtime_jsonl(
        run_root / artifacts["shard_manifest"],
        [_line_role_asdict(shard) for shard in shards],
    )
    _write_runtime_json(
        run_root / artifacts["worker_assignments"],
        [_line_role_asdict(assignment) for assignment in assignments],
    )

    all_proposals: list[ShardProposalV1] = []
    failures: list[dict[str, Any]] = []
    worker_reports: list[WorkerExecutionReportV1] = []
    stage_rows: list[dict[str, Any]] = []
    runner_results_by_shard_id: dict[str, dict[str, Any]] = {}
    completed_shards = 0
    total_shards = len(shards)
    progress_lock = threading.Lock()
    pending_shards_by_worker = {
        assignment.worker_id: list(assignment.shard_ids)
        for assignment in assignments
    }

    def _mark_shard_completed(*, worker_id: str, shard_id: str) -> None:
        nonlocal completed_shards
        with progress_lock:
            pending = pending_shards_by_worker.get(worker_id) or []
            if shard_id in pending:
                pending.remove(shard_id)
            completed_shards += 1
            remaining = max(0, total_shards - completed_shards)
            active_tasks: list[str] = []
            for next_assignment in assignments:
                worker_pending = pending_shards_by_worker.get(next_assignment.worker_id) or []
                if worker_pending:
                    active_tasks.append(worker_pending[0])
            _notify_line_role_progress(
                progress_callback=progress_callback,
                completed_tasks=completed_shards,
                total_tasks=total_shards,
                running_tasks=min(len(active_tasks), remaining),
                worker_total=worker_count,
            )

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
                runner=runner,
                pipeline_id=pipeline_id,
                env=env,
                model=model,
                reasoning_effort=reasoning_effort,
                output_schema_path=output_schema_path,
                timeout_seconds=timeout_seconds,
                shard_completed_callback=_mark_shard_completed,
            )
            for assignment in assignments
        }
        for assignment in assignments:
            result = futures_by_worker_id[assignment.worker_id].result()
            worker_reports.append(result.report)
            all_proposals.extend(result.proposals)
            failures.extend(result.failures)
            stage_rows.extend(result.stage_rows)
            runner_results_by_shard_id.update(result.runner_results_by_shard_id)

    promotion_report = {
        "schema_version": "phase_worker_runtime.promotion_report.v1",
        "phase_key": phase_key,
        "pipeline_id": pipeline_id,
        "validated_shards": sum(1 for proposal in all_proposals if proposal.status == "validated"),
        "invalid_shards": sum(1 for proposal in all_proposals if proposal.status == "invalid"),
        "missing_output_shards": sum(
            1 for proposal in all_proposals if proposal.status == "missing_output"
        ),
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
) -> dict[str, Any]:
    payload = run_result.to_payload(worker_id=worker_id, shard_id=shard_id)
    payload["pipeline_id"] = pipeline_id
    payload["process_payload"] = {
        "pipeline_id": pipeline_id,
        "status": "done" if run_result.subprocess_exit_code == 0 else "failed",
        "codex_model": model,
        "codex_reasoning_effort": reasoning_effort,
    }
    return payload


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
            "output_schema_enforced": True,
            "tool_affordances_requested": False,
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

    def _path(self, stem: str, prompt_index: int, suffix: str) -> Path | None:
        if self._prompt_dir is None:
            return None
        return self._prompt_dir / f"{stem}_{prompt_index:04d}{suffix}"

    def write_prompt(self, *, prompt_index: int, prompt_text: str) -> None:
        path = self._path("prompt", prompt_index, ".txt")
        if path is not None:
            path.write_text(prompt_text, encoding="utf-8")

    def write_response(
        self,
        *,
        prompt_index: int,
        response_payload: Mapping[str, Any],
    ) -> None:
        response_path = self._path("response", prompt_index, ".txt")
        parsed_path = self._path("parsed", prompt_index, ".json")
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
            prompt_index=prompt_index,
            response_text=response_text,
        )

    def write_failure(
        self,
        *,
        prompt_index: int,
        error: str,
        response_payload: Any | None = None,
    ) -> None:
        parsed_path = self._path("parsed", prompt_index, ".json")
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
            prompt_index=prompt_index,
            response_text=json.dumps(
                {"error": str(error).strip() or "invalid_proposal"},
                sort_keys=True,
            ),
        )

    def _append_dedup(self, *, prompt_index: int, response_text: str) -> None:
        if self._prompt_dir is None:
            return
        prompt_path = self._path("prompt", prompt_index, ".txt")
        prompt_text = prompt_path.read_text(encoding="utf-8") if prompt_path is not None and prompt_path.exists() else ""
        dedup_path = self._prompt_dir / "codex_prompt_log.dedup.txt"
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
            handle.write(f"{stable_hash}\tprompt_{prompt_index:04d}\n")

    def finalize(self, *, parse_error_count: int) -> None:
        if self._prompt_dir is None:
            return
        (self._prompt_dir / "parse_errors.json").write_text(
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
    telemetry_rows: list[dict[str, Any]] = []
    batch_payloads: list[dict[str, Any]] = []
    for report in runtime_result.worker_reports:
        runner_result = report.runner_result or {}
        telemetry_payload = runner_result.get("telemetry")
        if not isinstance(telemetry_payload, dict):
            continue
        rows = telemetry_payload.get("rows")
        if isinstance(rows, list):
            telemetry_rows.extend(
                dict(row) for row in rows if isinstance(row, dict)
            )
    totals = _sum_runtime_usage(telemetry_rows)
    for plan in runtime_result.shard_plans:
        runner_payload = runtime_result.runner_results_by_shard_id.get(plan.shard_id) or {}
        attempt_usage: dict[str, Any] | None = None
        telemetry_payload = runner_payload.get("telemetry")
        runner_rows = telemetry_payload.get("rows") if isinstance(telemetry_payload, dict) else None
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
                "attempt_count": 1,
                "attempts_with_usage": 1 if attempt_usage is not None else 0,
                "attempts": [
                    {
                        "attempt_index": 1,
                        "response_present": bool(str(runner_payload.get("response_text") or "").strip()),
                        "returncode": _safe_int_value(runner_payload.get("subprocess_exit_code")),
                        "turn_failed_message": runner_payload.get("turn_failed_message"),
                        "usage": attempt_usage,
                        "process_run": runner_payload,
                    }
                ],
            }
        )
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pipeline": LINE_ROLE_PIPELINE_SHARD_V1,
                "codex_backend": "codex_exec_direct",
                "codex_farm_pipeline_id": _LINE_ROLE_CODEX_FARM_PIPELINE_ID,
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "token_usage_enabled": bool(telemetry_rows),
                "summary": {
                    "batch_count": len(runtime_result.shard_plans),
                    "attempt_count": len(telemetry_rows) or len(runtime_result.shard_plans),
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
                    "attempts_without_usage": max(
                        0,
                        (len(telemetry_rows) or len(runtime_result.shard_plans))
                        - sum(
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
                    ),
                    "tokens_input": totals.get("tokens_input"),
                    "tokens_cached_input": totals.get("tokens_cached_input"),
                    "tokens_output": totals.get("tokens_output"),
                    "tokens_reasoning": totals.get("tokens_reasoning"),
                    "tokens_total": totals.get("tokens_total"),
                },
                "batches": batch_payloads,
                "runtime_artifacts": {
                    "runtime_root": (
                        str(runtime_result.runtime_root.relative_to(artifact_root))
                        if runtime_result.runtime_root is not None
                        else None
                    ),
                    "invalid_shard_count": runtime_result.invalid_shard_count,
                    "missing_output_shard_count": runtime_result.missing_output_shard_count,
                    "worker_count": len(runtime_result.worker_reports),
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
    payload: list[dict[str, Any]] = []
    for candidate in candidates:
        payload.append(
            {
                "recipe_id": candidate.recipe_id,
                "block_id": candidate.block_id,
                "block_index": candidate.block_index,
                "atomic_index": candidate.atomic_index,
                "text": candidate.text,
                "within_recipe_span": candidate.within_recipe_span,
                "prev_text": candidate.prev_text,
                "next_text": candidate.next_text,
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
    if "note_prefix" in tags or _looks_note_text(candidate.text):
        return "RECIPE_NOTES", ["note_prefix"]
    if _looks_storage_or_serving_note(candidate.text):
        return "RECIPE_NOTES", ["storage_or_serving_note"]
    if "variant_heading" in tags or _looks_variant_heading_text(candidate.text):
        if (
            _is_outside_recipe_span(candidate)
            and _outside_span_variant_should_be_recipe_title(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        ):
            return "RECIPE_TITLE", ["title_like", "variant_heading_title_override"]
        return "RECIPE_VARIANT", ["variant_heading"]
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
        if _looks_knowledge_prose_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            return "KNOWLEDGE", [
                "outside_recipe_span",
                "prose_like",
                "knowledge_context",
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
        if _looks_knowledge_prose_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            return "KNOWLEDGE", [
                "unknown_recipe_span",
                "prose_like",
                "knowledge_context",
            ]
        return "OTHER", ["unknown_recipe_span", "prose_default_other"]
    if "yield_prefix" in tags:
        return "YIELD_LINE", ["yield_prefix"]
    if "howto_heading" in tags:
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
        if _looks_knowledge_heading_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            return "KNOWLEDGE", ["outside_recipe_span", "knowledge_heading_context"]
        if _looks_knowledge_prose_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            return "KNOWLEDGE", [
                "outside_recipe_span",
                "prose_like",
                "knowledge_context",
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
            if _looks_knowledge_prose_with_context(
                candidate,
                by_atomic_index=by_atomic_index,
            ):
                return "KNOWLEDGE", [
                    "outside_recipe_span",
                    "prose_like",
                    "knowledge_context",
                ]
            return "OTHER", ["outside_recipe_span", "prose_default_other"]
        return "OTHER", ["outside_recipe_span"]
    if candidate.within_recipe_span is None and _looks_knowledge_heading_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "KNOWLEDGE", ["unknown_recipe_span", "knowledge_heading_context"]
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
    if not _looks_recipe_title(candidate.text):
        return False
    if not _looks_compact_heading(candidate.text):
        return False

    prev_candidate = by_atomic_index.get(candidate.atomic_index - 1)
    next_candidate = by_atomic_index.get(candidate.atomic_index + 1)
    if next_candidate is None:
        return False
    if _looks_recipe_start_boundary(next_candidate):
        return False

    prev_flow = _looks_recipe_flow_neighbor(prev_candidate)
    next_instruction = _looks_instructional_neighbor(next_candidate)
    prev_heading = (
        prev_candidate is not None and _looks_compact_heading(prev_candidate.text)
    )
    return next_instruction and (prev_flow or prev_heading)


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


def _looks_note_text(text: str) -> bool:
    return bool(_NOTE_PREFIX_RE.match(text))


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
    lowered = stripped.lower()
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
    return bool(_FIRST_PERSON_RE.search(stripped) and not _RECIPE_CONTEXT_RE.search(stripped))


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
    return domain_cues >= 3


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
    return _knowledge_domain_cue_count(stripped) > 0


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
    lowered = stripped.lower()
    if not any(
        cue in lowered
        for cue in ("book", "cook", "cooking", "kitchen", "meal", "recipe")
    ):
        return False
    return bool(_PEDAGOGICAL_KNOWLEDGE_CUE_RE.search(stripped))


def _looks_knowledge_prose_with_context(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    text = str(candidate.text or "").strip()
    if (
        _looks_explicit_knowledge_cue(text)
        or _looks_domain_knowledge_prose(text)
        or _looks_endorsement_credit(text)
        or _looks_pedagogical_knowledge_prose(text)
    ):
        return True
    if by_atomic_index is None:
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
        seen.add(atomic_index)
        parsed.append({"atomic_index": atomic_index, "label": normalized_label})

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
