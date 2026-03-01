"""Lightweight QualitySuite orchestration with main-effects-first rounds."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import statistics
from dataclasses import dataclass
from functools import cmp_to_key
from pathlib import Path
import re
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cookimport.bench.quality_runner import (
    _expand_experiments,
    _load_experiment_file,
    run_quality_suite,
)
from cookimport.bench.quality_suite import (
    QualitySuite,
    discover_quality_suite,
    write_quality_suite,
)
from cookimport.core.progress_messages import format_task_counter


ProgressCallback = Callable[[str], None]

_EXPERIMENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SUPPORTED_SEARCH_STRATEGIES = {"race", "exhaustive"}
_SERIES_RESOLVED_FILENAME = "lightweight_series_resolved.json"
_SERIES_SUMMARY_FILENAME = "lightweight_series_summary.json"
_SERIES_REPORT_FILENAME = "lightweight_series_report.md"
_FOLD_RESULT_FILENAME = "fold_result.json"
_FOLD_SUMMARY_EXTRACT_FILENAME = "fold_summary_extract.json"
_DEFAULT_COMMAND = "cookimport bench quality-lightweight-series"
_COMBINED_EXPERIMENT_ID = "combined_main_effects"
_INTERACTION_RUNNER_UP_VARIANT_ID = "combined_plus_parser_runner_up"


class LightweightCategoryProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    candidate_experiment_ids: list[str]

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("category.id is required")
        if not _EXPERIMENT_ID_PATTERN.match(cleaned):
            raise ValueError(
                "category.id must be slug-safe: lowercase letters, digits, '_' or '-'"
            )
        return cleaned

    @field_validator("candidate_experiment_ids")
    @classmethod
    def _validate_candidates(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in value:
            cleaned = str(raw or "").strip()
            if not cleaned:
                continue
            if not _EXPERIMENT_ID_PATTERN.match(cleaned):
                raise ValueError(
                    "candidate_experiment_ids must be slug-safe: lowercase letters, "
                    "digits, '_' or '-'"
                )
            if cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        if not normalized:
            raise ValueError("candidate_experiment_ids must contain at least one id")
        return normalized


class LightweightRoundConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed_count: int = Field(default=2, ge=1)
    search_strategy: str = "exhaustive"
    include_deterministic_sweeps: bool = False
    race_probe_targets: int = Field(default=2, ge=1)
    race_mid_targets: int = Field(default=4, ge=1)
    race_keep_ratio: float = Field(default=0.35, gt=0.0, le=1.0)
    race_finalists: int = Field(default=64, ge=1)

    @field_validator("search_strategy")
    @classmethod
    def _validate_search_strategy(cls, value: str) -> str:
        cleaned = str(value or "").strip().lower()
        if cleaned not in _SUPPORTED_SEARCH_STRATEGIES:
            supported = ", ".join(sorted(_SUPPORTED_SEARCH_STRATEGIES))
            raise ValueError(
                f"Unsupported search_strategy {value!r}. Supported: {supported}."
            )
        return cleaned


class LightweightRoundsProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_1_main_effects: LightweightRoundConfig = Field(
        default_factory=LightweightRoundConfig
    )
    round_2_composition: LightweightRoundConfig = Field(
        default_factory=LightweightRoundConfig
    )
    round_3_interaction_smoke: LightweightRoundConfig = Field(
        default_factory=LightweightRoundConfig
    )


class LightweightConfidenceGuardProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    practical_delta_diff_max: float = 0.0015
    strict_delta_diff_max: float = 0.0015


class LightweightCombinedVerdictProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    practical_delta_min: float = -0.0020
    strict_delta_min: float = -0.0020
    source_success_delta_min: float = -0.0100


class LightweightScoringProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    practical_epsilon: float = 0.0010
    strict_epsilon: float = 0.0010
    source_success_epsilon: float = 0.0050
    confidence_guard: LightweightConfidenceGuardProfile = Field(
        default_factory=LightweightConfidenceGuardProfile
    )
    combined_verdict: LightweightCombinedVerdictProfile = Field(
        default_factory=LightweightCombinedVerdictProfile
    )


class LightweightInteractionRiskProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    practical_f1_gain_min: float = 0.0030
    strict_f1_gain_min: float = 0.0030
    source_success_rate_gain_min: float = 0.0200


class LightweightInteractionSmokeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ablation_categories: list[str] = Field(
        default_factory=lambda: [
            "parser",
            "structure",
            "instruction_segmentation",
        ]
    )
    include_parser_runner_up_variant: bool = True
    risk_thresholds: LightweightInteractionRiskProfile = Field(
        default_factory=LightweightInteractionRiskProfile
    )

    @field_validator("ablation_categories")
    @classmethod
    def _validate_ablation_categories(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in value:
            cleaned = str(raw or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized


class LightweightSeriesProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    baseline_experiment_id: str = "baseline"
    categories: list[LightweightCategoryProfile]
    rounds: LightweightRoundsProfile = Field(default_factory=LightweightRoundsProfile)
    scoring: LightweightScoringProfile = Field(default_factory=LightweightScoringProfile)
    interaction_smoke: LightweightInteractionSmokeProfile = Field(
        default_factory=LightweightInteractionSmokeProfile
    )

    @field_validator("baseline_experiment_id")
    @classmethod
    def _validate_baseline_experiment_id(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("baseline_experiment_id is required")
        if not _EXPERIMENT_ID_PATTERN.match(cleaned):
            raise ValueError(
                "baseline_experiment_id must be slug-safe: lowercase letters, digits, '_' or '-'"
            )
        return cleaned

    @field_validator("categories")
    @classmethod
    def _validate_categories(cls, value: list[LightweightCategoryProfile]) -> list[LightweightCategoryProfile]:
        if not value:
            raise ValueError("categories must contain at least one category")
        seen: set[str] = set()
        for category in value:
            if category.id in seen:
                raise ValueError(f"Duplicate category id: {category.id}")
            seen.add(category.id)
        return value


@dataclass(frozen=True)
class _ExperimentCatalog:
    source_payload: dict[str, Any]
    source_schema_version: int
    base_run_settings_file: Path | None
    all_method_runtime: dict[str, Any]
    run_settings_patch_by_id: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class _CandidateMetrics:
    experiment_id: str
    mean_practical_f1_macro: float | None
    mean_strict_f1_macro: float | None
    mean_source_success_rate: float | None
    practical_delta: float | None
    strict_delta: float | None
    source_success_delta: float | None


@dataclass(frozen=True)
class _CategoryRanking:
    category_id: str
    ranked_candidates: list[_CandidateMetrics]
    winner_experiment_id: str
    runner_up_experiment_id: str | None
    confidence: str


def run_quality_lightweight_series(
    *,
    gold_root: Path,
    input_root: Path,
    experiments_file: Path,
    thresholds_file: Path,
    profile_file: Path,
    out_dir: Path,
    resume_series_dir: Path | None = None,
    max_parallel_experiments: int | None = None,
    require_process_workers: bool = False,
    command: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Run a lightweight QualitySuite series and return the series directory."""
    gold_root = Path(gold_root).expanduser()
    input_root = Path(input_root).expanduser()
    experiments_file = Path(experiments_file).expanduser()
    thresholds_file = Path(thresholds_file).expanduser()
    profile_file = Path(profile_file).expanduser()
    out_dir = Path(out_dir).expanduser()
    resume_series_dir = (
        Path(resume_series_dir).expanduser()
        if resume_series_dir is not None
        else None
    )
    if max_parallel_experiments is not None:
        max_parallel_experiments = int(max_parallel_experiments)
        if max_parallel_experiments < 1:
            raise ValueError("--max-parallel-experiments must be >= 1 when provided")

    for path, label in (
        (gold_root, "gold_root"),
        (input_root, "input_root"),
        (experiments_file, "experiments_file"),
        (thresholds_file, "thresholds_file"),
        (profile_file, "profile_file"),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{label} not found: {path}")

    profile = _load_profile(profile_file)
    thresholds_payload = _load_json_object(
        thresholds_file, context="quality lightweight thresholds file"
    )
    suite_seeds = _extract_threshold_seeds(thresholds_payload)
    suite_max_targets = _extract_threshold_max_targets(thresholds_payload)
    suite_prefer_curated = _extract_threshold_prefer_curated(thresholds_payload)
    experiment_catalog = _load_experiment_catalog(experiments_file=experiments_file)
    _validate_profile_candidates(profile=profile, catalog=experiment_catalog)

    run_timestamp: str
    if resume_series_dir is not None:
        run_root = resume_series_dir
        if not run_root.exists() or not run_root.is_dir():
            raise FileNotFoundError(
                f"--resume-series-dir must point to an existing directory: {run_root}"
            )
        run_timestamp = str(run_root.name or "").strip() or _timestamp()
    else:
        run_timestamp = _timestamp()
        run_root = out_dir / run_timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    resolved_payload = _build_resolved_payload(
        run_timestamp=run_timestamp,
        run_root=run_root,
        gold_root=gold_root,
        input_root=input_root,
        experiments_file=experiments_file,
        thresholds_file=thresholds_file,
        profile_file=profile_file,
        profile=profile,
    )
    _write_or_validate_resolved_payload(
        run_root=run_root,
        payload=resolved_payload,
        resume=resume_series_dir is not None,
    )

    warnings: list[str] = []
    command_text = str(command or _DEFAULT_COMMAND).strip() or _DEFAULT_COMMAND

    round_1_ids = _dedupe_preserve_order(
        [
            profile.baseline_experiment_id,
            *[
                candidate_id
                for category in profile.categories
                for candidate_id in category.candidate_experiment_ids
            ],
        ]
    )
    round_1_patches = _select_patches_for_ids(
        experiment_ids=round_1_ids,
        source_patches=experiment_catalog.run_settings_patch_by_id,
    )
    round_1_payload = _build_effective_experiments_payload(
        baseline_experiment_id=profile.baseline_experiment_id,
        ordered_experiment_ids=round_1_ids,
        run_settings_patch_by_id=round_1_patches,
        base_run_settings_file=experiment_catalog.base_run_settings_file,
        all_method_runtime=experiment_catalog.all_method_runtime,
    )
    round_1_seeds = _take_seed_prefix(
        seeds=suite_seeds,
        count=profile.rounds.round_1_main_effects.seed_count,
        context="round_1_main_effects",
    )
    round_1_root = run_root / "round_1_main_effects"
    round_1_folds = _execute_round(
        round_root=round_1_root,
        round_name="round_1_main_effects",
        round_config=profile.rounds.round_1_main_effects,
        seeds=round_1_seeds,
        gold_root=gold_root,
        input_root=input_root,
        suite_max_targets=suite_max_targets,
        suite_prefer_curated=suite_prefer_curated,
        experiments_payload=round_1_payload,
        max_parallel_experiments=max_parallel_experiments,
        require_process_workers=require_process_workers,
        progress_callback=progress_callback,
    )

    round_1_metrics = _aggregate_round_metrics(
        fold_payloads=round_1_folds,
        experiment_ids=round_1_ids,
    )
    initial_rankings = _score_categories(
        profile=profile,
        metrics_by_experiment=round_1_metrics,
    )
    categories_needing_confidence_guard = _confidence_guard_categories(
        rankings=initial_rankings,
        scoring=profile.scoring,
    )

    confidence_guard_seed: int | None = None
    if (
        profile.scoring.confidence_guard.enabled
        and categories_needing_confidence_guard
    ):
        confidence_guard_seed = _next_unused_seed(
            all_seeds=suite_seeds,
            used_seeds=round_1_seeds,
        )
        if confidence_guard_seed is None:
            low_conf = ", ".join(categories_needing_confidence_guard)
            warnings.append(
                "Round 1 confidence guard requested but no additional seed remained: "
                f"{low_conf}"
            )
        else:
            confidence_guard_root = round_1_root / "confidence_guard"
            guard_fold = _run_round_fold(
                fold_root=confidence_guard_root
                / f"fold_{len(round_1_seeds) + 1:02d}_seed_{confidence_guard_seed}",
                round_name="round_1_main_effects_confidence_guard",
                fold_index=len(round_1_seeds) + 1,
                fold_total=len(round_1_seeds) + 1,
                seed=confidence_guard_seed,
                round_config=LightweightRoundConfig(
                    seed_count=1,
                    search_strategy=profile.rounds.round_1_main_effects.search_strategy,
                    include_deterministic_sweeps=profile.rounds.round_1_main_effects.include_deterministic_sweeps,
                    race_probe_targets=profile.rounds.round_1_main_effects.race_probe_targets,
                    race_mid_targets=profile.rounds.round_1_main_effects.race_mid_targets,
                    race_keep_ratio=profile.rounds.round_1_main_effects.race_keep_ratio,
                    race_finalists=profile.rounds.round_1_main_effects.race_finalists,
                ),
                gold_root=gold_root,
                input_root=input_root,
                suite_max_targets=suite_max_targets,
                suite_prefer_curated=suite_prefer_curated,
                experiments_payload=round_1_payload,
                max_parallel_experiments=max_parallel_experiments,
                require_process_workers=require_process_workers,
                progress_callback=progress_callback,
            )
            round_1_folds.append(guard_fold)
            round_1_metrics = _aggregate_round_metrics(
                fold_payloads=round_1_folds,
                experiment_ids=round_1_ids,
            )

    final_round_1_rankings = _score_categories(
        profile=profile,
        metrics_by_experiment=round_1_metrics,
    )
    confidence_low_categories = set()
    if confidence_guard_seed is None:
        confidence_low_categories = set(categories_needing_confidence_guard)
    final_round_1_rankings = [
        _CategoryRanking(
            category_id=row.category_id,
            ranked_candidates=row.ranked_candidates,
            winner_experiment_id=row.winner_experiment_id,
            runner_up_experiment_id=row.runner_up_experiment_id,
            confidence=(
                "low" if row.category_id in confidence_low_categories else "high"
            ),
        )
        for row in final_round_1_rankings
    ]
    ranking_by_category = {row.category_id: row for row in final_round_1_rankings}

    winner_ids_by_category: dict[str, str] = {
        category.id: ranking_by_category[category.id].winner_experiment_id
        for category in profile.categories
    }
    runner_up_ids_by_category: dict[str, str | None] = {
        category.id: ranking_by_category[category.id].runner_up_experiment_id
        for category in profile.categories
    }

    (
        combined_patch,
        combined_provenance,
    ) = _build_combined_patch(
        profile=profile,
        winner_ids_by_category=winner_ids_by_category,
        run_settings_patch_by_id=experiment_catalog.run_settings_patch_by_id,
        baseline_experiment_id=profile.baseline_experiment_id,
    )
    round_2_ids = [profile.baseline_experiment_id]
    for category in profile.categories:
        winner_id = winner_ids_by_category.get(category.id)
        if winner_id and winner_id != profile.baseline_experiment_id:
            round_2_ids.append(winner_id)
    round_2_ids.append(_COMBINED_EXPERIMENT_ID)
    round_2_ids = _dedupe_preserve_order(round_2_ids)
    round_2_patches = _select_patches_for_ids(
        experiment_ids=round_2_ids,
        source_patches=experiment_catalog.run_settings_patch_by_id,
        extra_patches={_COMBINED_EXPERIMENT_ID: combined_patch},
    )
    round_2_payload = _build_effective_experiments_payload(
        baseline_experiment_id=profile.baseline_experiment_id,
        ordered_experiment_ids=round_2_ids,
        run_settings_patch_by_id=round_2_patches,
        base_run_settings_file=experiment_catalog.base_run_settings_file,
        all_method_runtime=experiment_catalog.all_method_runtime,
    )
    round_2_seeds = _take_seed_prefix(
        seeds=suite_seeds,
        count=profile.rounds.round_2_composition.seed_count,
        context="round_2_composition",
    )
    round_2_root = run_root / "round_2_composition"
    round_2_folds = _execute_round(
        round_root=round_2_root,
        round_name="round_2_composition",
        round_config=profile.rounds.round_2_composition,
        seeds=round_2_seeds,
        gold_root=gold_root,
        input_root=input_root,
        suite_max_targets=suite_max_targets,
        suite_prefer_curated=suite_prefer_curated,
        experiments_payload=round_2_payload,
        max_parallel_experiments=max_parallel_experiments,
        require_process_workers=require_process_workers,
        progress_callback=progress_callback,
    )
    round_2_metrics = _aggregate_round_metrics(
        fold_payloads=round_2_folds,
        experiment_ids=round_2_ids,
    )
    round_2_baseline = round_2_metrics.get(profile.baseline_experiment_id) or {}
    round_2_combined = round_2_metrics.get(_COMBINED_EXPERIMENT_ID) or {}
    round_2_deltas = _metrics_delta(
        candidate=round_2_combined,
        baseline=round_2_baseline,
    )
    round_2_verdict = _combined_verdict(
        delta_payload=round_2_deltas,
        thresholds=profile.scoring.combined_verdict,
    )

    round_3_patch_by_variant = _build_round_3_variants(
        profile=profile,
        winner_ids_by_category=winner_ids_by_category,
        runner_up_ids_by_category=runner_up_ids_by_category,
        run_settings_patch_by_id=experiment_catalog.run_settings_patch_by_id,
        baseline_experiment_id=profile.baseline_experiment_id,
    )
    round_3_ids = _dedupe_preserve_order(
        [
            profile.baseline_experiment_id,
            _COMBINED_EXPERIMENT_ID,
            *sorted(round_3_patch_by_variant),
        ]
    )
    round_3_patches = _select_patches_for_ids(
        experiment_ids=round_3_ids,
        source_patches=experiment_catalog.run_settings_patch_by_id,
        extra_patches={
            _COMBINED_EXPERIMENT_ID: combined_patch,
            **round_3_patch_by_variant,
        },
    )
    round_3_payload = _build_effective_experiments_payload(
        baseline_experiment_id=profile.baseline_experiment_id,
        ordered_experiment_ids=round_3_ids,
        run_settings_patch_by_id=round_3_patches,
        base_run_settings_file=experiment_catalog.base_run_settings_file,
        all_method_runtime=experiment_catalog.all_method_runtime,
    )
    round_3_seeds = _take_seed_prefix(
        seeds=suite_seeds,
        count=profile.rounds.round_3_interaction_smoke.seed_count,
        context="round_3_interaction_smoke",
    )
    round_3_root = run_root / "round_3_interaction_smoke"
    round_3_folds = _execute_round(
        round_root=round_3_root,
        round_name="round_3_interaction_smoke",
        round_config=profile.rounds.round_3_interaction_smoke,
        seeds=round_3_seeds,
        gold_root=gold_root,
        input_root=input_root,
        suite_max_targets=suite_max_targets,
        suite_prefer_curated=suite_prefer_curated,
        experiments_payload=round_3_payload,
        max_parallel_experiments=max_parallel_experiments,
        require_process_workers=require_process_workers,
        progress_callback=progress_callback,
    )
    round_3_metrics = _aggregate_round_metrics(
        fold_payloads=round_3_folds,
        experiment_ids=round_3_ids,
    )
    round_3_combined = round_3_metrics.get(_COMBINED_EXPERIMENT_ID) or {}
    round_3_variants = []
    round_3_findings = []
    for variant_id in round_3_ids:
        if variant_id == profile.baseline_experiment_id:
            continue
        candidate_metrics = round_3_metrics.get(variant_id) or {}
        gains = _metrics_delta(candidate=candidate_metrics, baseline=round_3_combined)
        variant_row = {
            "variant_id": variant_id,
            "mean_practical_f1_macro": candidate_metrics.get("mean_practical_f1_macro"),
            "mean_strict_f1_macro": candidate_metrics.get("mean_strict_f1_macro"),
            "mean_source_success_rate": candidate_metrics.get("mean_source_success_rate"),
            "practical_f1_gain_vs_combined": gains.get("practical_delta"),
            "strict_f1_gain_vs_combined": gains.get("strict_delta"),
            "source_success_rate_gain_vs_combined": gains.get("source_success_delta"),
        }
        round_3_variants.append(variant_row)
        if variant_id == _COMBINED_EXPERIMENT_ID:
            continue
        finding = _interaction_smoke_finding(
            variant_id=variant_id,
            gain_payload=gains,
            risk_thresholds=profile.interaction_smoke.risk_thresholds,
        )
        round_3_findings.append(finding)

    interaction_risk_present = any(
        row.get("verdict") == "RISK" for row in round_3_findings
    )
    any_low_confidence = any(
        row.confidence == "low" for row in final_round_1_rankings
    )
    if round_2_verdict != "PASS":
        ship_confidence = "low"
    elif interaction_risk_present or any_low_confidence:
        ship_confidence = "medium"
    else:
        ship_confidence = "high"

    round_1_summary = {
        "folds_planned": len(round_1_seeds)
        + (1 if confidence_guard_seed is not None and categories_needing_confidence_guard else 0),
        "folds_executed": len(round_1_folds),
        "seeds_executed": [int(row.get("seed", 0)) for row in round_1_folds],
        "winners_by_category": {},
    }
    for category in profile.categories:
        ranking = ranking_by_category[category.id]
        winner_metrics = round_1_metrics.get(ranking.winner_experiment_id) or {}
        winner_deltas = _metrics_delta(
            candidate=winner_metrics,
            baseline=round_1_metrics.get(profile.baseline_experiment_id) or {},
        )
        winner_row: dict[str, Any] = {
            "winner_experiment_id": ranking.winner_experiment_id,
            "confidence": ranking.confidence,
            "mean_practical_f1_macro": winner_metrics.get("mean_practical_f1_macro"),
            "mean_strict_f1_macro": winner_metrics.get("mean_strict_f1_macro"),
            "mean_source_success_rate": winner_metrics.get("mean_source_success_rate"),
            "practical_delta": winner_deltas.get("practical_delta"),
            "strict_delta": winner_deltas.get("strict_delta"),
            "source_success_delta": winner_deltas.get("source_success_delta"),
        }
        if ranking.runner_up_experiment_id is not None:
            winner_row["runner_up_experiment_id"] = ranking.runner_up_experiment_id
        round_1_summary["winners_by_category"][category.id] = winner_row

    summary_payload = {
        "schema_version": 1,
        "generated_at": _timestamp(),
        "series_root": str(run_root),
        "command": command_text,
        "inputs": {
            "gold_root": str(gold_root),
            "input_root": str(input_root),
            "experiments_file": str(experiments_file),
            "thresholds_file": str(thresholds_file),
            "profile_file": str(profile_file),
        },
        "round_contract": {
            "round_1_seed_count": profile.rounds.round_1_main_effects.seed_count,
            "round_2_seed_count": profile.rounds.round_2_composition.seed_count,
            "round_3_seed_count": profile.rounds.round_3_interaction_smoke.seed_count,
            "search_strategy": profile.rounds.round_1_main_effects.search_strategy,
            "include_deterministic_sweeps": profile.rounds.round_1_main_effects.include_deterministic_sweeps,
        },
        "categories": [
            {
                "category_id": category.id,
                "candidate_experiment_ids": list(category.candidate_experiment_ids),
            }
            for category in profile.categories
        ],
        "round_1_main_effects": round_1_summary,
        "round_2_composition": {
            "combined_experiment_id": _COMBINED_EXPERIMENT_ID,
            "category_winner_ids": winner_ids_by_category,
            "mean_practical_f1_macro": round_2_combined.get("mean_practical_f1_macro"),
            "mean_strict_f1_macro": round_2_combined.get("mean_strict_f1_macro"),
            "mean_source_success_rate": round_2_combined.get("mean_source_success_rate"),
            "practical_delta": round_2_deltas.get("practical_delta"),
            "strict_delta": round_2_deltas.get("strict_delta"),
            "source_success_delta": round_2_deltas.get("source_success_delta"),
            "verdict": round_2_verdict,
        },
        "round_3_interaction_smoke": {
            "variants": round_3_variants,
            "findings": round_3_findings,
        },
        "final_recommendation": {
            "recommended_combined_experiment_id": _COMBINED_EXPERIMENT_ID,
            "ship_confidence": ship_confidence,
            "interaction_risk": "present"
            if interaction_risk_present
            else "not_obvious",
        },
        "warnings": warnings if warnings else [],
        "combined_patch_provenance": combined_provenance,
    }
    summary_path = run_root / _SERIES_SUMMARY_FILENAME
    report_path = run_root / _SERIES_REPORT_FILENAME
    summary_path.write_text(
        json.dumps(summary_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_path.write_text(
        _format_lightweight_series_report(summary_payload=summary_payload),
        encoding="utf-8",
    )
    return run_root


def _timestamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")


def _load_profile(path: Path) -> LightweightSeriesProfile:
    payload = _load_json_object(path, context="quality lightweight profile file")
    profile = LightweightSeriesProfile.model_validate(payload)
    if profile.schema_version != 1:
        raise ValueError(
            f"Unsupported lightweight profile schema_version {profile.schema_version}. "
            "Supported: 1."
        )
    return profile


def _load_json_object(path: Path, *, context: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to parse {context}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{context} must be a JSON object")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _extract_threshold_seeds(payload: dict[str, Any]) -> list[int]:
    suite = payload.get("suite")
    if not isinstance(suite, dict):
        raise ValueError("thresholds.suite is required and must be an object")
    seeds_raw = suite.get("seeds")
    if not isinstance(seeds_raw, list) or not seeds_raw:
        raise ValueError("thresholds.suite.seeds must be a non-empty array")
    seeds = [int(row) for row in seeds_raw]
    if any(seed <= 0 for seed in seeds):
        raise ValueError("thresholds.suite.seeds must contain positive integers")
    return seeds


def _extract_threshold_max_targets(payload: dict[str, Any]) -> int | None:
    suite = payload.get("suite")
    if not isinstance(suite, dict):
        return None
    raw = suite.get("max_targets")
    if raw is None:
        return None
    value = int(raw)
    return value if value > 0 else None


def _extract_threshold_prefer_curated(payload: dict[str, Any]) -> bool:
    suite = payload.get("suite")
    if not isinstance(suite, dict):
        return True
    return bool(suite.get("prefer_curated", True))


def _load_experiment_catalog(*, experiments_file: Path) -> _ExperimentCatalog:
    source_payload = _load_json_object(
        experiments_file, context="quality lightweight experiments file"
    )
    source_schema_version = int(source_payload.get("schema_version", 1))
    experiment_payload = _load_experiment_file(experiments_file)
    expanded = _expand_experiments(experiment_payload)
    run_settings_patch_by_id: dict[str, dict[str, Any]] = {}
    for row in expanded:
        run_settings_patch_by_id[row.id] = dict(row.run_settings_patch)

    base_run_settings_file_raw = str(
        source_payload.get("base_run_settings_file") or ""
    ).strip()
    base_run_settings_file: Path | None = None
    if base_run_settings_file_raw:
        candidate = Path(base_run_settings_file_raw)
        if not candidate.is_absolute():
            candidate = (experiments_file.parent / candidate).resolve()
        base_run_settings_file = candidate

    all_method_runtime = source_payload.get("all_method_runtime")
    if isinstance(all_method_runtime, dict):
        runtime_payload = dict(all_method_runtime)
    else:
        runtime_payload = {}
    return _ExperimentCatalog(
        source_payload=source_payload,
        source_schema_version=source_schema_version,
        base_run_settings_file=base_run_settings_file,
        all_method_runtime=runtime_payload,
        run_settings_patch_by_id=run_settings_patch_by_id,
    )


def _validate_profile_candidates(
    *,
    profile: LightweightSeriesProfile,
    catalog: _ExperimentCatalog,
) -> None:
    available_ids = set(catalog.run_settings_patch_by_id)
    if profile.baseline_experiment_id not in available_ids:
        available = ", ".join(sorted(available_ids)) or "<none>"
        raise ValueError(
            f"baseline_experiment_id {profile.baseline_experiment_id!r} is missing "
            f"from experiments file (available: {available})"
        )
    owner_by_candidate: dict[str, str] = {}
    for category in profile.categories:
        for candidate_id in category.candidate_experiment_ids:
            if candidate_id not in available_ids:
                available = ", ".join(sorted(available_ids)) or "<none>"
                raise ValueError(
                    f"Category {category.id!r} references unknown experiment id "
                    f"{candidate_id!r} (available: {available})"
                )
            if candidate_id == profile.baseline_experiment_id:
                raise ValueError(
                    f"Category {category.id!r} includes baseline id "
                    f"{profile.baseline_experiment_id!r}; baseline must not be in category lists."
                )
            prior_owner = owner_by_candidate.get(candidate_id)
            if prior_owner is not None and prior_owner != category.id:
                raise ValueError(
                    f"Experiment id {candidate_id!r} appears in multiple categories: "
                    f"{prior_owner!r} and {category.id!r}"
                )
            owner_by_candidate[candidate_id] = category.id

    category_ids = {category.id for category in profile.categories}
    for category_id in profile.interaction_smoke.ablation_categories:
        if category_id not in category_ids:
            raise ValueError(
                "interaction_smoke.ablation_categories references unknown category id: "
                f"{category_id!r}"
            )


def _build_resolved_payload(
    *,
    run_timestamp: str,
    run_root: Path,
    gold_root: Path,
    input_root: Path,
    experiments_file: Path,
    thresholds_file: Path,
    profile_file: Path,
    profile: LightweightSeriesProfile,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": run_timestamp,
        "series_root": str(run_root),
        "inputs": {
            "gold_root": str(gold_root),
            "input_root": str(input_root),
            "experiments_file": str(experiments_file),
            "experiments_sha256": _sha256_file(experiments_file),
            "thresholds_file": str(thresholds_file),
            "thresholds_sha256": _sha256_file(thresholds_file),
            "profile_file": str(profile_file),
            "profile_sha256": _sha256_file(profile_file),
        },
        "baseline_experiment_id": profile.baseline_experiment_id,
    }


def _write_or_validate_resolved_payload(
    *,
    run_root: Path,
    payload: dict[str, Any],
    resume: bool,
) -> None:
    path = run_root / _SERIES_RESOLVED_FILENAME
    if not resume:
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return
    if not path.exists() or not path.is_file():
        raise ValueError(
            f"Resume requires existing {_SERIES_RESOLVED_FILENAME}: {path}"
        )
    existing = _load_json_object(path, context=_SERIES_RESOLVED_FILENAME)
    if existing != payload:
        raise ValueError(
            "resume-series-dir compatibility mismatch: profile/experiments/thresholds/baseline changed."
        )


def _take_seed_prefix(*, seeds: list[int], count: int, context: str) -> list[int]:
    if len(seeds) < count:
        raise ValueError(
            f"{context} requires {count} seeds but thresholds provide {len(seeds)}"
        )
    return list(seeds[:count])


def _next_unused_seed(*, all_seeds: list[int], used_seeds: list[int]) -> int | None:
    used = set(used_seeds)
    for seed in all_seeds:
        if seed in used:
            continue
        return int(seed)
    return None


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def _select_patches_for_ids(
    *,
    experiment_ids: list[str],
    source_patches: dict[str, dict[str, Any]],
    extra_patches: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    extras = extra_patches or {}
    for experiment_id in experiment_ids:
        if experiment_id in extras:
            selected[experiment_id] = dict(extras[experiment_id])
            continue
        if experiment_id not in source_patches:
            raise ValueError(f"Missing run_settings_patch for experiment id: {experiment_id}")
        selected[experiment_id] = dict(source_patches[experiment_id])
    return selected


def _build_effective_experiments_payload(
    *,
    baseline_experiment_id: str,
    ordered_experiment_ids: list[str],
    run_settings_patch_by_id: dict[str, dict[str, Any]],
    base_run_settings_file: Path | None,
    all_method_runtime: dict[str, Any],
) -> dict[str, Any]:
    include_baseline = baseline_experiment_id in ordered_experiment_ids
    experiments_rows = []
    for experiment_id in ordered_experiment_ids:
        if experiment_id == baseline_experiment_id:
            continue
        patch = dict(run_settings_patch_by_id.get(experiment_id) or {})
        experiments_rows.append(
            {
                "id": experiment_id,
                "run_settings_patch": patch,
            }
        )

    payload: dict[str, Any] = {
        "schema_version": 2,
        "include_baseline": include_baseline,
        "baseline_id": baseline_experiment_id,
        "include_all_on": False,
        "all_on_id": "all_on",
        "all_method_runtime": dict(all_method_runtime),
        "experiments": experiments_rows,
        "levers": [],
    }
    if base_run_settings_file is not None:
        payload["base_run_settings_file"] = str(base_run_settings_file)
    return payload


def _execute_round(
    *,
    round_root: Path,
    round_name: str,
    round_config: LightweightRoundConfig,
    seeds: list[int],
    gold_root: Path,
    input_root: Path,
    suite_max_targets: int | None,
    suite_prefer_curated: bool,
    experiments_payload: dict[str, Any],
    max_parallel_experiments: int | None,
    require_process_workers: bool,
    progress_callback: ProgressCallback | None,
) -> list[dict[str, Any]]:
    round_root.mkdir(parents=True, exist_ok=True)
    fold_rows: list[dict[str, Any]] = []
    total = len(seeds)
    for index, seed in enumerate(seeds, start=1):
        fold_root = round_root / f"fold_{index:02d}_seed_{seed}"
        fold_payload = _run_round_fold(
            fold_root=fold_root,
            round_name=round_name,
            fold_index=index,
            fold_total=total,
            seed=seed,
            round_config=round_config,
            gold_root=gold_root,
            input_root=input_root,
            suite_max_targets=suite_max_targets,
            suite_prefer_curated=suite_prefer_curated,
            experiments_payload=experiments_payload,
            max_parallel_experiments=max_parallel_experiments,
            require_process_workers=require_process_workers,
            progress_callback=progress_callback,
        )
        fold_rows.append(fold_payload)
    return fold_rows


def _run_round_fold(
    *,
    fold_root: Path,
    round_name: str,
    fold_index: int,
    fold_total: int,
    seed: int,
    round_config: LightweightRoundConfig,
    gold_root: Path,
    input_root: Path,
    suite_max_targets: int | None,
    suite_prefer_curated: bool,
    experiments_payload: dict[str, Any],
    max_parallel_experiments: int | None,
    require_process_workers: bool,
    progress_callback: ProgressCallback | None,
) -> dict[str, Any]:
    fold_root.mkdir(parents=True, exist_ok=True)
    fold_result_path = fold_root / _FOLD_RESULT_FILENAME
    if fold_result_path.exists() and fold_result_path.is_file():
        existing = _load_json_object(fold_result_path, context=str(fold_result_path))
        run_dir_raw = str(existing.get("run_dir") or "").strip()
        if run_dir_raw:
            run_dir = Path(run_dir_raw)
            if (
                run_dir.exists()
                and run_dir.is_dir()
                and (run_dir / "summary.json").exists()
            ):
                _notify_progress(
                    progress_callback,
                    (
                        f"{format_task_counter(round_name, fold_index, fold_total, noun='task')}: "
                        f"seed={seed} (resume reuse)"
                    ),
                )
                return existing

    _notify_progress(
        progress_callback,
        (
            f"{format_task_counter(round_name, fold_index, fold_total, noun='task')}: "
            f"seed={seed}"
        ),
    )
    suite = _discover_suite_for_seed(
        seed=seed,
        gold_root=gold_root,
        input_root=input_root,
        max_targets=suite_max_targets,
        prefer_curated=suite_prefer_curated,
    )
    suite_path = fold_root / "suite.json"
    write_quality_suite(suite_path, suite)

    effective_experiments_path = fold_root / "experiments_effective.json"
    effective_experiments_path.write_text(
        json.dumps(experiments_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    run_out_dir = fold_root / "quality_runs"
    run_out_dir.mkdir(parents=True, exist_ok=True)
    resume_run_dir = _latest_partial_quality_run_dir(run_out_dir)
    run_dir = run_quality_suite(
        suite,
        run_out_dir,
        experiments_file=effective_experiments_path,
        search_strategy=round_config.search_strategy,
        race_probe_targets=round_config.race_probe_targets,
        race_mid_targets=round_config.race_mid_targets,
        race_keep_ratio=round_config.race_keep_ratio,
        race_finalists=round_config.race_finalists,
        include_deterministic_sweeps_requested=round_config.include_deterministic_sweeps,
        max_parallel_experiments=max_parallel_experiments,
        require_process_workers=require_process_workers,
        resume_run_dir=resume_run_dir,
        progress_callback=progress_callback,
    )
    summary_path = run_dir / "summary.json"
    summary_payload = _load_json_object(summary_path, context=str(summary_path))
    experiment_rows = _extract_experiment_rows(summary_payload)
    fold_summary_extract = {
        "round_name": round_name,
        "seed": seed,
        "run_dir": str(run_dir),
        "summary_path": str(summary_path),
        "experiments": experiment_rows,
    }
    (fold_root / _FOLD_SUMMARY_EXTRACT_FILENAME).write_text(
        json.dumps(fold_summary_extract, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    fold_payload = {
        "round_name": round_name,
        "seed": seed,
        "suite_path": str(suite_path),
        "experiments_effective_path": str(effective_experiments_path),
        "run_out_dir": str(run_out_dir),
        "run_dir": str(run_dir),
        "summary_path": str(summary_path),
        "experiments": experiment_rows,
    }
    fold_result_path.write_text(
        json.dumps(fold_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return fold_payload


def _latest_partial_quality_run_dir(path: Path) -> Path | None:
    if not path.exists() or not path.is_dir():
        return None
    candidates = sorted(
        [entry for entry in path.iterdir() if entry.is_dir()],
        key=lambda row: row.name,
        reverse=True,
    )
    for candidate in candidates:
        has_summary = (
            (candidate / "summary.json").exists()
            and (candidate / "report.md").exists()
        )
        if has_summary:
            continue
        has_runner_metadata = (candidate / "experiments_resolved.json").exists()
        if has_runner_metadata:
            return candidate
    return None


def _discover_suite_for_seed(
    *,
    seed: int,
    gold_root: Path,
    input_root: Path,
    max_targets: int | None,
    prefer_curated: bool,
) -> QualitySuite:
    discover_kwargs: dict[str, Any] = {
        "gold_root": gold_root,
        "input_root": input_root,
        "max_targets": max_targets,
        "seed": int(seed),
    }
    if not prefer_curated:
        discover_kwargs["preferred_target_ids"] = None
    return discover_quality_suite(**discover_kwargs)


def _notify_progress(
    progress_callback: ProgressCallback | None,
    message: str,
) -> None:
    if progress_callback is None:
        return
    progress_callback(message)


def _extract_experiment_rows(summary_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = summary_payload.get("experiments")
    if not isinstance(rows, list):
        return {}
    extracted: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        experiment_id = str(row.get("id") or "").strip()
        if not experiment_id:
            continue
        extracted[experiment_id] = {
            "status": str(row.get("status") or "").strip(),
            "strict_f1_macro": row.get("strict_f1_macro"),
            "practical_f1_macro": row.get("practical_f1_macro"),
            "source_success_rate": row.get("source_success_rate"),
        }
    return extracted


def _aggregate_round_metrics(
    *,
    fold_payloads: list[dict[str, Any]],
    experiment_ids: list[str],
) -> dict[str, dict[str, float | None]]:
    aggregated: dict[str, dict[str, float | None]] = {}
    for experiment_id in experiment_ids:
        practical_values: list[float] = []
        strict_values: list[float] = []
        source_values: list[float] = []
        for fold_payload in fold_payloads:
            rows = fold_payload.get("experiments")
            if not isinstance(rows, dict):
                continue
            row = rows.get(experiment_id)
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "").strip().lower()
            if status != "ok":
                continue
            practical = _as_float(row.get("practical_f1_macro"))
            strict = _as_float(row.get("strict_f1_macro"))
            source_success = _as_float(row.get("source_success_rate"))
            if practical is not None:
                practical_values.append(practical)
            if strict is not None:
                strict_values.append(strict)
            if source_success is not None:
                source_values.append(source_success)

        aggregated[experiment_id] = {
            "mean_practical_f1_macro": _mean_or_none(practical_values),
            "mean_strict_f1_macro": _mean_or_none(strict_values),
            "mean_source_success_rate": _mean_or_none(source_values),
        }
    return aggregated


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.mean(values))


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _score_categories(
    *,
    profile: LightweightSeriesProfile,
    metrics_by_experiment: dict[str, dict[str, float | None]],
) -> list[_CategoryRanking]:
    baseline_metrics = metrics_by_experiment.get(profile.baseline_experiment_id) or {}
    rows: list[_CategoryRanking] = []
    for category in profile.categories:
        candidate_rows = []
        for candidate_id in category.candidate_experiment_ids:
            candidate_metrics = metrics_by_experiment.get(candidate_id) or {}
            deltas = _metrics_delta(
                candidate=candidate_metrics,
                baseline=baseline_metrics,
            )
            candidate_rows.append(
                _CandidateMetrics(
                    experiment_id=candidate_id,
                    mean_practical_f1_macro=candidate_metrics.get("mean_practical_f1_macro"),
                    mean_strict_f1_macro=candidate_metrics.get("mean_strict_f1_macro"),
                    mean_source_success_rate=candidate_metrics.get("mean_source_success_rate"),
                    practical_delta=deltas.get("practical_delta"),
                    strict_delta=deltas.get("strict_delta"),
                    source_success_delta=deltas.get("source_success_delta"),
                )
            )
        ranked = sorted(
            candidate_rows,
            key=cmp_to_key(
                lambda left, right: _compare_candidate_metrics(
                    left,
                    right,
                    scoring=profile.scoring,
                )
            ),
        )
        winner_id = profile.baseline_experiment_id
        runner_up_id: str | None = None
        if ranked:
            top = ranked[0]
            top_non_positive = (
                _is_non_positive_or_none(top.practical_delta)
                and _is_non_positive_or_none(top.strict_delta)
                and _is_non_positive_or_none(top.source_success_delta)
            )
            if top_non_positive:
                winner_id = profile.baseline_experiment_id
                runner_up_id = top.experiment_id
            else:
                winner_id = top.experiment_id
                if len(ranked) > 1:
                    runner_up_id = ranked[1].experiment_id
        rows.append(
            _CategoryRanking(
                category_id=category.id,
                ranked_candidates=ranked,
                winner_experiment_id=winner_id,
                runner_up_experiment_id=runner_up_id,
                confidence="high",
            )
        )
    return rows


def _metrics_delta(
    *,
    candidate: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, float | None]:
    practical_candidate = _as_float(candidate.get("mean_practical_f1_macro"))
    practical_baseline = _as_float(baseline.get("mean_practical_f1_macro"))
    strict_candidate = _as_float(candidate.get("mean_strict_f1_macro"))
    strict_baseline = _as_float(baseline.get("mean_strict_f1_macro"))
    source_candidate = _as_float(candidate.get("mean_source_success_rate"))
    source_baseline = _as_float(baseline.get("mean_source_success_rate"))
    return {
        "practical_delta": _sub_or_none(practical_candidate, practical_baseline),
        "strict_delta": _sub_or_none(strict_candidate, strict_baseline),
        "source_success_delta": _sub_or_none(source_candidate, source_baseline),
    }


def _sub_or_none(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return float(left - right)


def _is_non_positive_or_none(value: float | None) -> bool:
    if value is None:
        return True
    return float(value) <= 0.0


def _compare_candidate_metrics(
    left: _CandidateMetrics,
    right: _CandidateMetrics,
    *,
    scoring: LightweightScoringProfile,
) -> int:
    for key, epsilon in (
        ("practical_delta", scoring.practical_epsilon),
        ("strict_delta", scoring.strict_epsilon),
        ("source_success_delta", scoring.source_success_epsilon),
    ):
        compared = _compare_floats_with_epsilon(
            _metric_value(left, key),
            _metric_value(right, key),
            epsilon=epsilon,
        )
        if compared != 0:
            return -1 if compared > 0 else 1

    for key in (
        "mean_practical_f1_macro",
        "mean_strict_f1_macro",
    ):
        compared = _compare_floats_with_epsilon(
            _metric_value(left, key),
            _metric_value(right, key),
            epsilon=0.0,
        )
        if compared != 0:
            return -1 if compared > 0 else 1

    if left.experiment_id < right.experiment_id:
        return -1
    if left.experiment_id > right.experiment_id:
        return 1
    return 0


def _metric_value(row: _CandidateMetrics, key: str) -> float | None:
    return getattr(row, key)


def _compare_floats_with_epsilon(
    left: float | None,
    right: float | None,
    *,
    epsilon: float,
) -> int:
    if left is None and right is None:
        return 0
    if left is None:
        return -1
    if right is None:
        return 1
    diff = float(left) - float(right)
    if abs(diff) <= float(epsilon):
        return 0
    return 1 if diff > 0 else -1


def _confidence_guard_categories(
    *,
    rankings: list[_CategoryRanking],
    scoring: LightweightScoringProfile,
) -> list[str]:
    triggered: list[str] = []
    for ranking in rankings:
        if len(ranking.ranked_candidates) < 2:
            continue
        first = ranking.ranked_candidates[0]
        second = ranking.ranked_candidates[1]
        if _needs_confidence_guard(
            first=first,
            second=second,
            config=scoring.confidence_guard,
        ):
            triggered.append(ranking.category_id)
    return triggered


def _needs_confidence_guard(
    *,
    first: _CandidateMetrics,
    second: _CandidateMetrics,
    config: LightweightConfidenceGuardProfile,
) -> bool:
    if not config.enabled:
        return False
    practical_diff = _abs_delta(first.practical_delta, second.practical_delta)
    strict_diff = _abs_delta(first.strict_delta, second.strict_delta)
    if practical_diff is None or strict_diff is None:
        return False
    return (
        practical_diff < float(config.practical_delta_diff_max)
        and strict_diff < float(config.strict_delta_diff_max)
    )


def _abs_delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return abs(float(left) - float(right))


def _build_combined_patch(
    *,
    profile: LightweightSeriesProfile,
    winner_ids_by_category: dict[str, str],
    run_settings_patch_by_id: dict[str, dict[str, Any]],
    baseline_experiment_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    combined_patch: dict[str, Any] = {}
    provenance: dict[str, list[dict[str, Any]]] = {}
    for category in profile.categories:
        winner_id = winner_ids_by_category.get(category.id, baseline_experiment_id)
        if winner_id == baseline_experiment_id:
            continue
        winner_patch = dict(run_settings_patch_by_id.get(winner_id) or {})
        for key, value in winner_patch.items():
            if key not in combined_patch:
                combined_patch[key] = value
                provenance.setdefault(key, []).append(
                    {
                        "category_id": category.id,
                        "experiment_id": winner_id,
                        "value": value,
                    }
                )
                continue
            if combined_patch[key] == value:
                provenance.setdefault(key, []).append(
                    {
                        "category_id": category.id,
                        "experiment_id": winner_id,
                        "value": value,
                    }
                )
                continue
            prior = provenance.get(key) or []
            first = prior[0] if prior else {}
            raise ValueError(
                "illegal_overlap: conflicting run_settings_patch key "
                f"{key!r} from {first.get('category_id')}/{first.get('experiment_id')}="
                f"{first.get('value')!r} and {category.id}/{winner_id}={value!r}"
            )
    return combined_patch, provenance


def _build_round_3_variants(
    *,
    profile: LightweightSeriesProfile,
    winner_ids_by_category: dict[str, str],
    runner_up_ids_by_category: dict[str, str | None],
    run_settings_patch_by_id: dict[str, dict[str, Any]],
    baseline_experiment_id: str,
) -> dict[str, dict[str, Any]]:
    variants: dict[str, dict[str, Any]] = {}
    winner_map = dict(winner_ids_by_category)
    for category_id in profile.interaction_smoke.ablation_categories:
        winner_id = winner_map.get(category_id, baseline_experiment_id)
        if winner_id == baseline_experiment_id:
            continue
        minus_map = dict(winner_map)
        minus_map[category_id] = baseline_experiment_id
        patch, _provenance = _build_combined_patch(
            profile=profile,
            winner_ids_by_category=minus_map,
            run_settings_patch_by_id=run_settings_patch_by_id,
            baseline_experiment_id=baseline_experiment_id,
        )
        variants[f"combined_minus_{category_id}"] = patch

    if profile.interaction_smoke.include_parser_runner_up_variant:
        parser_winner_id = winner_map.get("parser", baseline_experiment_id)
        parser_runner_up_id = runner_up_ids_by_category.get("parser")
        if parser_runner_up_id and parser_runner_up_id != parser_winner_id:
            plus_map = dict(winner_map)
            plus_map["parser"] = parser_runner_up_id
            patch, _provenance = _build_combined_patch(
                profile=profile,
                winner_ids_by_category=plus_map,
                run_settings_patch_by_id=run_settings_patch_by_id,
                baseline_experiment_id=baseline_experiment_id,
            )
            variants[_INTERACTION_RUNNER_UP_VARIANT_ID] = patch
    return variants


def _combined_verdict(
    *,
    delta_payload: dict[str, float | None],
    thresholds: LightweightCombinedVerdictProfile,
) -> str:
    practical = _as_float(delta_payload.get("practical_delta"))
    strict = _as_float(delta_payload.get("strict_delta"))
    source_success = _as_float(delta_payload.get("source_success_delta"))
    if (
        practical is None
        or strict is None
        or source_success is None
    ):
        return "FAIL"
    if practical < float(thresholds.practical_delta_min):
        return "FAIL"
    if strict < float(thresholds.strict_delta_min):
        return "FAIL"
    if source_success < float(thresholds.source_success_delta_min):
        return "FAIL"
    return "PASS"


def _interaction_smoke_finding(
    *,
    variant_id: str,
    gain_payload: dict[str, float | None],
    risk_thresholds: LightweightInteractionRiskProfile,
) -> dict[str, Any]:
    practical_gain = _as_float(gain_payload.get("practical_delta"))
    strict_gain = _as_float(gain_payload.get("strict_delta"))
    source_gain = _as_float(gain_payload.get("source_success_delta"))
    triggered: list[str] = []
    if (
        practical_gain is not None
        and practical_gain >= float(risk_thresholds.practical_f1_gain_min)
    ):
        triggered.append("practical_f1_gain")
    if strict_gain is not None and strict_gain >= float(risk_thresholds.strict_f1_gain_min):
        triggered.append("strict_f1_gain")
    if (
        source_gain is not None
        and source_gain >= float(risk_thresholds.source_success_rate_gain_min)
    ):
        triggered.append("source_success_rate_gain")
    return {
        "variant_id": variant_id,
        "verdict": "RISK" if triggered else "NO_OBVIOUS_RISK",
        "triggered_thresholds": triggered,
    }


def _format_lightweight_series_report(*, summary_payload: dict[str, Any]) -> str:
    inputs = summary_payload.get("inputs")
    inputs = dict(inputs) if isinstance(inputs, dict) else {}
    round_contract = summary_payload.get("round_contract")
    round_contract = dict(round_contract) if isinstance(round_contract, dict) else {}
    round_1 = summary_payload.get("round_1_main_effects")
    round_1 = dict(round_1) if isinstance(round_1, dict) else {}
    round_2 = summary_payload.get("round_2_composition")
    round_2 = dict(round_2) if isinstance(round_2, dict) else {}
    round_3 = summary_payload.get("round_3_interaction_smoke")
    round_3 = dict(round_3) if isinstance(round_3, dict) else {}
    recommendation = summary_payload.get("final_recommendation")
    recommendation = dict(recommendation) if isinstance(recommendation, dict) else {}

    lines = [
        "# QualitySuite Lightweight Main-Effects Series Report",
        "",
        "## Inputs and Contracts",
        "",
        f"- Generated at: {summary_payload.get('generated_at')}",
        f"- Series root: {summary_payload.get('series_root')}",
        f"- Command: {summary_payload.get('command')}",
        f"- Gold root: {inputs.get('gold_root')}",
        f"- Input root: {inputs.get('input_root')}",
        f"- Experiments file: {inputs.get('experiments_file')}",
        f"- Thresholds file: {inputs.get('thresholds_file')}",
        f"- Profile file: {inputs.get('profile_file')}",
        f"- Round 1 seeds: {round_contract.get('round_1_seed_count')}",
        f"- Round 2 seeds: {round_contract.get('round_2_seed_count')}",
        f"- Round 3 seeds: {round_contract.get('round_3_seed_count')}",
        f"- Search strategy: {round_contract.get('search_strategy')}",
        (
            "- Deterministic sweeps: "
            f"{'on' if bool(round_contract.get('include_deterministic_sweeps')) else 'off'}"
        ),
        "",
        "## Round 1: Category Screening",
        "",
    ]
    winners = round_1.get("winners_by_category")
    winners = dict(winners) if isinstance(winners, dict) else {}
    if not winners:
        lines.append("- No category winners were recorded.")
    else:
        for category_id in sorted(winners):
            row = winners.get(category_id)
            if not isinstance(row, dict):
                continue
            runner_up_text = ""
            runner_up_id = str(row.get("runner_up_experiment_id") or "").strip()
            if runner_up_id:
                runner_up_text = f", runner_up={runner_up_id}"
            lines.append(
                "- "
                f"{category_id}: winner={row.get('winner_experiment_id')} "
                f"(practical_delta={_format_delta(row.get('practical_delta'))}, "
                f"strict_delta={_format_delta(row.get('strict_delta'))}, "
                f"source_success_delta={_format_delta(row.get('source_success_delta'))}, "
                f"confidence={row.get('confidence')}{runner_up_text})"
            )

    lines.extend(
        [
            "",
            "## Confidence Guard Outcomes",
            "",
        ]
    )
    if not winners:
        lines.append("- No confidence guard outcomes.")
    else:
        for category_id in sorted(winners):
            row = winners.get(category_id)
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- {category_id}: confidence={row.get('confidence')}"
            )

    lines.extend(
        [
            "",
            "## Round 2: Winner Composition",
            "",
            (
                f"- Combined experiment: {round_2.get('combined_experiment_id')} | "
                f"verdict={round_2.get('verdict')}"
            ),
            (
                "- Combined deltas vs baseline: "
                f"practical={_format_delta(round_2.get('practical_delta'))}, "
                f"strict={_format_delta(round_2.get('strict_delta'))}, "
                f"source_success={_format_delta(round_2.get('source_success_delta'))}"
            ),
            "",
            "## Round 3: Interaction Smoke",
            "",
        ]
    )

    findings = round_3.get("findings")
    findings = list(findings) if isinstance(findings, list) else []
    if not findings:
        lines.append("- No interaction findings were emitted.")
    else:
        for row in findings:
            if not isinstance(row, dict):
                continue
            triggers = row.get("triggered_thresholds")
            triggers = list(triggers) if isinstance(triggers, list) else []
            lines.append(
                f"- {row.get('variant_id')}: {row.get('verdict')} "
                f"(triggered={', '.join(triggers) if triggers else 'none'})"
            )

    lines.extend(
        [
            "",
            "## Final Recommendation",
            "",
            (
                f"- Recommended combined experiment: "
                f"{recommendation.get('recommended_combined_experiment_id')}"
            ),
            f"- Ship confidence: {recommendation.get('ship_confidence')}",
            f"- Interaction risk: {recommendation.get('interaction_risk')}",
            "",
            "## Artifact Paths",
            "",
            f"- Summary JSON: {summary_payload.get('series_root')}/{_SERIES_SUMMARY_FILENAME}",
            f"- Report Markdown: {summary_payload.get('series_root')}/{_SERIES_REPORT_FILENAME}",
            f"- Round 1 root: {summary_payload.get('series_root')}/round_1_main_effects",
            f"- Round 2 root: {summary_payload.get('series_root')}/round_2_composition",
            f"- Round 3 root: {summary_payload.get('series_root')}/round_3_interaction_smoke",
        ]
    )
    warnings = summary_payload.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "Warnings:"])
        for warning in warnings:
            lines.append(f"- {warning}")
    lines.append("")
    return "\n".join(lines)


def _format_delta(value: Any) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "n/a"
    return f"{numeric:+.4f}"
