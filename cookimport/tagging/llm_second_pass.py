"""LLM second-pass helpers for optional codex-farm tag suggestion."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from cookimport.llm.codex_farm_runner import CodexFarmRunner, CodexFarmRunnerError
from cookimport.tagging.catalog import TagCatalog
from cookimport.tagging.codex_farm_tags_provider import (
    CodexFarmTagsJob,
    CodexFarmTagsPassResult,
    TagCandidate,
    run_codex_farm_tags_pass,
)
from cookimport.tagging.engine import TagSuggestion
from cookimport.tagging.signals import RecipeSignalPack, normalize_text_for_matching

logger = logging.getLogger(__name__)

DEFAULT_TAGS_PIPELINE_ID = "recipe.tags.v1"
DEFAULT_FAILURE_MODE = "fallback"


@dataclass(frozen=True, slots=True)
class LlmSecondPassConfig:
    enabled: bool = False
    pipeline_id: str = DEFAULT_TAGS_PIPELINE_ID
    codex_farm_cmd: str = "codex-farm"
    codex_farm_root: Path | str | None = None
    codex_farm_workspace_root: Path | str | None = None
    failure_mode: str = DEFAULT_FAILURE_MODE
    runner: CodexFarmRunner | None = None


@dataclass(frozen=True, slots=True)
class LlmSecondPassRequest:
    recipe_key: str
    signals: RecipeSignalPack
    missing_categories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LlmSecondPassBatchResult:
    suggestions_by_recipe: dict[str, list[TagSuggestion]]
    new_tag_proposals_by_recipe: dict[str, list[dict[str, str]]]
    llm_validation: dict[str, Any]
    llm_report: dict[str, Any]

    @classmethod
    def empty(cls) -> "LlmSecondPassBatchResult":
        return cls(
            suggestions_by_recipe={},
            new_tag_proposals_by_recipe={},
            llm_validation={
                "jobs_requested": 0,
                "jobs_executed": 0,
                "outputs_read": 0,
                "missing_output_files": 0,
                "schema_invalid_outputs": 0,
                "selected_entries_seen": 0,
                "selected_entries_accepted": 0,
                "selected_entries_dropped": 0,
                "drop_reasons": {},
            },
            llm_report={"enabled": False, "pipeline": "off"},
        )


def _build_candidate_shortlist(
    catalog: TagCatalog,
    signals: RecipeSignalPack,
    category_key: str,
    max_candidates: int = 10,
) -> list[TagCandidate]:
    """Build a shortlist of candidate tag key_norms for a category via token overlap."""
    cat = catalog.categories_by_key.get(category_key)
    if cat is None:
        return []

    tags_in_category = catalog.tags_by_category_id.get(cat.id, [])
    if not tags_in_category:
        return []

    # Combined recipe text for matching
    combined = normalize_text_for_matching(
        " ".join([signals.title, signals.description, signals.notes]
                 + signals.ingredients + signals.instructions)
    )
    combined_tokens = set(combined.split())

    scored: list[tuple[TagCandidate, float]] = []
    for tag in tags_in_category:
        tag_tokens = set(normalize_text_for_matching(tag.display_name).split())
        if not tag_tokens:
            continue
        overlap = len(tag_tokens & combined_tokens)
        score = overlap / len(tag_tokens)
        if score > 0:
            scored.append(
                (
                    TagCandidate(tag_key_norm=tag.key_norm, display_name=tag.display_name),
                    score,
                )
            )

    scored.sort(key=lambda x: -x[1])
    shortlisted = [candidate for candidate, _ in scored[:max_candidates]]
    if shortlisted:
        return shortlisted

    fallback = [
        TagCandidate(tag_key_norm=tag.key_norm, display_name=tag.display_name)
        for tag in tags_in_category[:max_candidates]
    ]
    return fallback


def suggest_tags_with_llm_batch(
    requests: Sequence[LlmSecondPassRequest],
    catalog: TagCatalog,
    *,
    config: LlmSecondPassConfig | None = None,
    raw_pass_dir: Path | None = None,
) -> LlmSecondPassBatchResult:
    if not requests:
        return LlmSecondPassBatchResult.empty()

    effective = config or LlmSecondPassConfig(enabled=True)
    if not effective.enabled:
        return LlmSecondPassBatchResult.empty()

    normalized_failure_mode = _normalize_failure_mode(effective.failure_mode)

    jobs: list[CodexFarmTagsJob] = []
    for request in requests:
        candidates_by_category: dict[str, tuple[TagCandidate, ...]] = {}
        for category_key in request.missing_categories:
            candidates = _build_candidate_shortlist(catalog, request.signals, category_key)
            if candidates:
                candidates_by_category[category_key] = tuple(candidates)
        if not candidates_by_category:
            continue
        recipe_id = str(request.signals.recipe_id or request.recipe_key).strip()
        if not recipe_id:
            recipe_id = request.recipe_key
        jobs.append(
            CodexFarmTagsJob(
                recipe_key=request.recipe_key,
                recipe_id=recipe_id,
                signals=request.signals,
                missing_categories=tuple(sorted(candidates_by_category.keys())),
                candidates_by_category=candidates_by_category,
            )
        )

    if not jobs:
        return LlmSecondPassBatchResult.empty()

    try:
        provider_result = run_codex_farm_tags_pass(
            jobs=jobs,
            catalog=catalog,
            pipeline_id=effective.pipeline_id or DEFAULT_TAGS_PIPELINE_ID,
            codex_farm_cmd=effective.codex_farm_cmd or "codex-farm",
            codex_farm_root=effective.codex_farm_root,
            codex_farm_workspace_root=effective.codex_farm_workspace_root,
            runner=effective.runner,
            raw_pass_dir=raw_pass_dir,
        )
    except CodexFarmRunnerError as exc:
        if normalized_failure_mode == "fallback":
            logger.warning(
                "LLM second pass failed; falling back to deterministic-only suggestions: %s",
                exc,
            )
            return LlmSecondPassBatchResult(
                suggestions_by_recipe={},
                new_tag_proposals_by_recipe={},
                llm_validation={
                    "jobs_requested": len(jobs),
                    "jobs_executed": 0,
                    "outputs_read": 0,
                    "missing_output_files": 0,
                    "schema_invalid_outputs": 0,
                    "selected_entries_seen": 0,
                    "selected_entries_accepted": 0,
                    "selected_entries_dropped": 0,
                    "drop_reasons": {"codex_farm_error": 1},
                },
                llm_report={
                    "enabled": True,
                    "pipeline": "codex-farm-tags-v1",
                    "pipeline_id": effective.pipeline_id or DEFAULT_TAGS_PIPELINE_ID,
                    "fallbackApplied": True,
                    "fatalError": str(exc),
                },
            )
        raise

    return _from_provider_result(provider_result)


def suggest_tags_with_llm(
    signals: RecipeSignalPack,
    catalog: TagCatalog,
    missing_categories: list[str],
    deterministic: list[TagSuggestion],
    *,
    config: LlmSecondPassConfig | None = None,
    raw_pass_dir: Path | None = None,
    recipe_key: str = "recipe",
) -> list[TagSuggestion]:
    """Run LLM second pass for missing categories. Returns additional suggestions.

    deterministic is accepted for backward compatibility with old call sites.
    """
    _ = deterministic
    if not missing_categories:
        return []
    result = suggest_tags_with_llm_batch(
        [
            LlmSecondPassRequest(
                recipe_key=recipe_key,
                signals=signals,
                missing_categories=tuple(missing_categories),
            )
        ],
        catalog,
        config=config,
        raw_pass_dir=raw_pass_dir,
    )
    return list(result.suggestions_by_recipe.get(recipe_key, []))


def _from_provider_result(result: CodexFarmTagsPassResult) -> LlmSecondPassBatchResult:
    return LlmSecondPassBatchResult(
        suggestions_by_recipe=dict(result.suggestions_by_recipe),
        new_tag_proposals_by_recipe=dict(result.new_tag_proposals_by_recipe),
        llm_validation=dict(result.llm_validation),
        llm_report={
            "enabled": True,
            "pipeline": "codex-farm-tags-v1",
            **dict(result.llm_report),
        },
    )


def _normalize_failure_mode(value: str) -> str:
    rendered = str(value).strip().lower()
    if rendered not in {"fail", "fallback"}:
        raise ValueError(
            f"Invalid failure_mode for LLM second pass: {value!r}. Expected fail or fallback."
        )
    return rendered
