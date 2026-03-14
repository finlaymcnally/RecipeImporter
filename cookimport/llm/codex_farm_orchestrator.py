from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import ConversionResult, RecipeCandidate, RecipeDraftV1
from cookimport.staging.draft_v1 import recipe_candidate_to_draft_v1

from .codex_farm_contracts import (
    BlockLite,
    PatternHint,
    Pass1RecipeChunkingInput,
    Pass1RecipeChunkingOutput,
    Pass2SchemaOrgCompactInput,
    Pass2SchemaOrgInput,
    Pass2SchemaOrgOutput,
    Pass3FinalDraftCompactInput,
    Pass3FinalDraftInput,
    Pass3FinalDraftOutput,
    StructuralAuditResult,
    classify_pass2_structural_audit,
    classify_pass3_structural_audit,
    load_contract_json,
)
from .codex_farm_ids import bundle_filename, ensure_recipe_id, sanitize_for_filename
from .evidence_normalizer import normalize_pass2_evidence
from .codex_farm_transport import build_pass2_transport_selection
from .codex_farm_runner import (
    CodexFarmRunner,
    CodexFarmRunnerError,
    SubprocessCodexFarmRunner,
    as_pipeline_run_result_payload,
    ensure_codex_farm_pipelines_exist,
    resolve_codex_farm_output_schema_path,
)

logger = logging.getLogger(__name__)

DEFAULT_PASS1_PIPELINE_ID = "recipe.chunking.v1"
LEGACY_PASS2_PIPELINE_ID = "recipe.schemaorg.v1"
LEGACY_PASS3_PIPELINE_ID = "recipe.final.v1"
COMPACT_PASS2_PIPELINE_ID = "recipe.schemaorg.compact.v1"
COMPACT_PASS3_PIPELINE_ID = "recipe.final.compact.v1"
DEFAULT_PASS2_PIPELINE_ID = COMPACT_PASS2_PIPELINE_ID
DEFAULT_PASS3_PIPELINE_ID = COMPACT_PASS3_PIPELINE_ID

# Backward-compatible exports used by tests/docs.
PASS1_PIPELINE_ID = DEFAULT_PASS1_PIPELINE_ID
PASS2_PIPELINE_ID = DEFAULT_PASS2_PIPELINE_ID
PASS3_PIPELINE_ID = DEFAULT_PASS3_PIPELINE_ID
_CODEX_FARM_RECIPE_MODE_ENV = "COOKIMPORT_CODEX_FARM_RECIPE_MODE"
_PASS3_PASS2_OK_MIN_NON_PLACEHOLDER_INSTRUCTIONS = 2
_PASS3_PASS2_OK_MIN_CANONICAL_CHARS = 80
_BENCHMARK_SELECTIVE_RETRY_ALLOWED_FAILURE_CATEGORIES = frozenset(
    {"nonzero_exit_no_payload", "timeout"}
)
_ELIGIBILITY_INGREDIENT_LEAD_RE = re.compile(
    r"^\s*(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s+[A-Za-z]"
)
_ELIGIBILITY_INGREDIENT_UNIT_RE = re.compile(
    r"\b(cups?|tbsp|tablespoons?|tsp|teaspoons?|oz|ounces?|lb|lbs|pounds?|"
    r"g|kg|ml|l|cloves?|sticks?|cans?|pinch)\b",
    re.IGNORECASE,
)
_ELIGIBILITY_INSTRUCTION_VERB_RE = re.compile(
    r"^\s*(?:add|bake|beat|blend|boil|braise|bring|combine|cook|cool|cover|drain|"
    r"fold|grill|heat|mix|place|pour|reduce|remove|roast|season|serve|simmer|stir|"
    r"toast|transfer|whisk)\b",
    re.IGNORECASE,
)
_ELIGIBILITY_YIELD_PREFIX_RE = re.compile(
    r"^\s*(?:makes|serves?|servings|yields?)\b",
    re.IGNORECASE,
)
_ELIGIBILITY_TITLE_LIKE_RE = re.compile(r"^[A-Z][A-Z0-9'/:,\- ]{2,}$")
_ELIGIBILITY_CHAPTER_PAGE_HINT_KEYS = (
    "chapter_page_hint",
    "chapter_page_hints",
    "chapter_type",
    "chapter_kind",
    "section_type",
    "section_kind",
    "page_type",
    "page_kind",
    "page_region",
    "layout_region",
    "layout_type",
)
_ELIGIBILITY_TAG_LIST_KEYS = ("heuristic_tags", "reasoning_tags", "tags")
_ELIGIBILITY_CHAPTER_PAGE_NEGATIVE_HINT_TOKENS = (
    "chapter",
    "front_matter",
    "preface",
    "introduction",
    "table_of_contents",
    "toc",
    "index",
    "glossary",
    "appendix",
    "essay",
    "narrative",
    "prose",
    "reference",
    "sidebar",
    "table",
    "chart",
    "mixed_content",
)
_RECIPE_GUARDRAIL_REPORT_SCHEMA_VERSION = "recipe_codex_guardrail_report.v1"


def _effort_override_value(value: object | None) -> str | None:
    if value is None:
        return None
    resolved = getattr(value, "value", value)
    cleaned = str(resolved).strip()
    return cleaned or None


@dataclass
class CodexFarmApplyResult:
    updated_conversion_result: ConversionResult
    intermediate_overrides_by_recipe_id: dict[str, dict[str, Any]]
    final_overrides_by_recipe_id: dict[str, dict[str, Any]]
    llm_report: dict[str, Any]
    llm_raw_dir: Path


@dataclass
class _RecipeState:
    recipe: RecipeCandidate
    recipe_id: str
    bundle_name: str
    heuristic_start: int | None
    heuristic_end: int | None
    pass1_status: str = "pending"
    pass2_status: str = "pending"
    pass3_status: str = "pending"
    start_block_index: int | None = None
    end_block_index: int | None = None
    pass1_raw_start_block_index: int | None = None
    pass1_raw_end_block_index: int | None = None
    pass1_span_loss_metrics: dict[str, Any] | None = None
    pass1_eligibility_status: str | None = None
    pass1_eligibility_action: str | None = None
    pass1_eligibility_score: int | None = None
    pass1_eligibility_score_components: dict[str, Any] | None = None
    pass1_eligibility_reasons: list[str] = field(default_factory=list)
    excluded_block_ids: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    canonical_text: str = ""
    pass2_effective_indices: list[int] = field(default_factory=list)
    pass2_payload_indices: list[int] = field(default_factory=list)
    pass3_fallback_reason: str | None = None
    pass2_output: Pass2SchemaOrgOutput | None = None
    pass2_degradation_reasons: list[str] = field(default_factory=list)
    pass2_degradation_severity: str | None = None
    pass2_promotion_policy: str | None = None
    pass3_execution_mode: str | None = None
    pass3_routing_reason: str | None = None
    pass3_utility_signal: dict[str, Any] | None = None
    structural_status: str = "ok"
    structural_reason_codes: list[str] = field(default_factory=list)


def _recipe_artifact_filename(recipe_id: str) -> str:
    rendered = sanitize_for_filename(str(recipe_id).strip())
    if not rendered:
        rendered = "recipe"
    return f"{rendered}.json"


def _json_bundle_filenames(path: Path) -> list[str]:
    return sorted(child.name for child in path.glob("*.json") if child.is_file())


def _missing_bundle_filenames(expected_bundle_filenames: list[str], out_dir: Path) -> list[str]:
    existing = {path.name for path in out_dir.glob("*.json") if path.is_file()}
    return [name for name in sorted(expected_bundle_filenames) if name not in existing]


def _process_run_nonzero_exit(process_run: dict[str, Any] | None) -> bool:
    if not isinstance(process_run, dict):
        return False
    for key in ("subprocess_exit_code", "process_exit_code"):
        value = process_run.get(key)
        if value is None:
            continue
        try:
            if int(value) != 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _process_run_failure_category_counts(process_run: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(process_run, dict):
        return {}
    telemetry_payload = process_run.get("telemetry")
    if not isinstance(telemetry_payload, dict):
        return {}
    summary_payload = telemetry_payload.get("summary")
    if not isinstance(summary_payload, dict):
        return {}
    raw_counts = summary_payload.get("failure_category_counts")
    if not isinstance(raw_counts, dict):
        return {}
    counts: dict[str, int] = {}
    for key, value in raw_counts.items():
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            counts[str(key)] = count
    return counts


def _selective_retry_eligible_process_run(process_run: dict[str, Any] | None) -> bool:
    failure_counts = _process_run_failure_category_counts(process_run)
    if not failure_counts or not _process_run_nonzero_exit(process_run):
        return False
    failure_categories = set(failure_counts)
    return (
        "nonzero_exit_no_payload" in failure_categories
        and failure_categories <= _BENCHMARK_SELECTIVE_RETRY_ALLOWED_FAILURE_CATEGORIES
    )


def _recipe_ids_for_bundle_filenames(
    *,
    states_by_bundle_name: dict[str, _RecipeState],
    bundle_filenames: list[str],
) -> list[str]:
    recipe_ids: list[str] = []
    for bundle_name in bundle_filenames:
        state = states_by_bundle_name.get(bundle_name)
        if state is None:
            continue
        recipe_ids.append(state.recipe_id)
    return recipe_ids


def _relative_retry_dir(base_dir: Path, attempt_dir: Path) -> str:
    try:
        return str(attempt_dir.relative_to(base_dir))
    except ValueError:
        return str(attempt_dir)


def _selective_retry_settings_snapshot(
    *,
    run_settings: RunSettings,
    max_attempts: int,
) -> dict[str, Any]:
    return {
        "llm_recipe_pipeline": run_settings.llm_recipe_pipeline.value,
        "codex_farm_recipe_mode": run_settings.codex_farm_recipe_mode.value,
        "codex_farm_failure_mode": run_settings.codex_farm_failure_mode.value,
        "codex_farm_benchmark_selective_retry_enabled": (
            run_settings.codex_farm_benchmark_selective_retry_enabled
        ),
        "codex_farm_benchmark_selective_retry_max_attempts": max_attempts,
        "codex_farm_model": run_settings.codex_farm_model,
        "codex_farm_reasoning_effort": (
            run_settings.codex_farm_reasoning_effort.value
            if run_settings.codex_farm_reasoning_effort is not None
            else None
        ),
    }


def _run_benchmark_selective_retry(
    *,
    pass_name: str,
    pipeline_id: str,
    pass_dir: Path,
    llm_raw_dir: Path,
    original_in_dir: Path,
    original_out_dir: Path,
    expected_bundle_filenames: list[str],
    states_by_bundle_name: dict[str, _RecipeState],
    original_process_run: dict[str, Any] | None,
    run_settings: RunSettings,
    codex_runner: CodexFarmRunner,
    env: dict[str, str],
    pipeline_root: Path,
    workspace_root: Path | None,
    codex_model: str | None,
    codex_reasoning_effort: str | None,
) -> dict[str, Any] | None:
    original_missing_bundle_filenames = _missing_bundle_filenames(
        expected_bundle_filenames,
        original_out_dir,
    )
    if not original_missing_bundle_filenames:
        return None
    if run_settings.codex_farm_recipe_mode.value != "benchmark":
        return None
    if not run_settings.codex_farm_benchmark_selective_retry_enabled:
        return None
    if not _selective_retry_eligible_process_run(original_process_run):
        return None

    max_attempts = int(run_settings.codex_farm_benchmark_selective_retry_max_attempts)
    remaining_missing_bundle_filenames = list(original_missing_bundle_filenames)
    attempts: list[dict[str, Any]] = []
    current_process_run = original_process_run

    for attempt_index in range(1, max_attempts + 1):
        if not remaining_missing_bundle_filenames:
            break
        attempt_dir = pass_dir / f"retry_attempt_{attempt_index:02d}"
        if attempt_dir.exists():
            shutil.rmtree(attempt_dir)
        retry_in_dir = attempt_dir / "in"
        retry_out_dir = attempt_dir / "out"
        retry_in_dir.mkdir(parents=True, exist_ok=True)
        retry_out_dir.mkdir(parents=True, exist_ok=True)

        attempted_bundle_filenames: list[str] = []
        for bundle_name in remaining_missing_bundle_filenames:
            source_path = original_in_dir / bundle_name
            if not source_path.is_file():
                continue
            shutil.copy2(source_path, retry_in_dir / bundle_name)
            attempted_bundle_filenames.append(bundle_name)
        if not attempted_bundle_filenames:
            break

        retry_run = codex_runner.run_pipeline(
            pipeline_id,
            retry_in_dir,
            retry_out_dir,
            env,
            root_dir=pipeline_root,
            workspace_root=workspace_root,
            model=codex_model,
            reasoning_effort=codex_reasoning_effort,
        )
        retry_process_run = as_pipeline_run_result_payload(retry_run)

        copied_output_filenames: list[str] = []
        for bundle_name in attempted_bundle_filenames:
            retry_output_path = retry_out_dir / bundle_name
            original_output_path = original_out_dir / bundle_name
            if not retry_output_path.is_file() or original_output_path.exists():
                continue
            shutil.copy2(retry_output_path, original_output_path)
            copied_output_filenames.append(bundle_name)

        remaining_missing_bundle_filenames = _missing_bundle_filenames(
            expected_bundle_filenames,
            original_out_dir,
        )
        attempts.append(
            {
                "attempt_index": attempt_index,
                "retry_dir": _relative_retry_dir(llm_raw_dir, attempt_dir),
                "attempted_bundle_filenames": list(attempted_bundle_filenames),
                "attempted_recipe_ids": _recipe_ids_for_bundle_filenames(
                    states_by_bundle_name=states_by_bundle_name,
                    bundle_filenames=attempted_bundle_filenames,
                ),
                "copied_output_filenames": list(copied_output_filenames),
                "copied_recipe_ids": _recipe_ids_for_bundle_filenames(
                    states_by_bundle_name=states_by_bundle_name,
                    bundle_filenames=copied_output_filenames,
                ),
                "remaining_missing_bundle_filenames": list(
                    remaining_missing_bundle_filenames
                ),
                "remaining_missing_recipe_ids": _recipe_ids_for_bundle_filenames(
                    states_by_bundle_name=states_by_bundle_name,
                    bundle_filenames=remaining_missing_bundle_filenames,
                ),
                "process_run": retry_process_run,
            }
        )
        current_process_run = retry_process_run
        if not remaining_missing_bundle_filenames:
            break
        if not _selective_retry_eligible_process_run(current_process_run):
            break

    recovered_bundle_filenames = sorted(
        set(original_missing_bundle_filenames) - set(remaining_missing_bundle_filenames)
    )
    unrecovered_bundle_filenames = list(remaining_missing_bundle_filenames)
    return {
        "enabled": True,
        "max_attempts": max_attempts,
        "pass": pass_name,
        "pipeline_id": pipeline_id,
        "settings": _selective_retry_settings_snapshot(
            run_settings=run_settings,
            max_attempts=max_attempts,
        ),
        "allowed_failure_categories": sorted(
            _BENCHMARK_SELECTIVE_RETRY_ALLOWED_FAILURE_CATEGORIES
        ),
        "original_missing_bundle_count": len(original_missing_bundle_filenames),
        "recovered_bundle_count": len(recovered_bundle_filenames),
        "unrecovered_bundle_count": len(unrecovered_bundle_filenames),
        "attempted_bundle_filenames": list(original_missing_bundle_filenames),
        "recovered_bundle_filenames": list(recovered_bundle_filenames),
        "unrecovered_bundle_filenames": list(unrecovered_bundle_filenames),
        "attempted_recipe_ids": _recipe_ids_for_bundle_filenames(
            states_by_bundle_name=states_by_bundle_name,
            bundle_filenames=original_missing_bundle_filenames,
        ),
        "recovered_recipe_ids": _recipe_ids_for_bundle_filenames(
            states_by_bundle_name=states_by_bundle_name,
            bundle_filenames=recovered_bundle_filenames,
        ),
        "unrecovered_recipe_ids": _recipe_ids_for_bundle_filenames(
            states_by_bundle_name=states_by_bundle_name,
            bundle_filenames=unrecovered_bundle_filenames,
        ),
        "attempts": attempts,
    }


def run_codex_farm_recipe_pipeline(
    *,
    conversion_result: ConversionResult,
    run_settings: RunSettings,
    run_root: Path,
    workbook_slug: str,
    runner: CodexFarmRunner | None = None,
    full_blocks: list[dict[str, Any]] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> CodexFarmApplyResult:
    if run_settings.llm_recipe_pipeline.value == "off":
        return CodexFarmApplyResult(
            updated_conversion_result=conversion_result,
            intermediate_overrides_by_recipe_id={},
            final_overrides_by_recipe_id={},
            llm_report={"enabled": False, "pipeline": "off"},
            llm_raw_dir=run_root / "raw" / "llm" / sanitize_for_filename(workbook_slug),
        )

    llm_raw_dir = run_root / "raw" / "llm" / sanitize_for_filename(workbook_slug)
    pass1_in_dir = llm_raw_dir / "pass1_chunking" / "in"
    pass1_out_dir = llm_raw_dir / "pass1_chunking" / "out"
    pass2_in_dir = llm_raw_dir / "pass2_schemaorg" / "in"
    pass2_out_dir = llm_raw_dir / "pass2_schemaorg" / "out"
    pass3_in_dir = llm_raw_dir / "pass3_final" / "in"
    pass3_out_dir = llm_raw_dir / "pass3_final" / "out"
    transport_audit_dir = llm_raw_dir / "transport_audit"
    evidence_normalization_dir = llm_raw_dir / "evidence_normalization"
    pass1_eligibility_diagnostics_path = (
        llm_raw_dir / "pass1_recipe_eligibility_diagnostics.json"
    )
    for path in (
        pass1_in_dir,
        pass1_out_dir,
        pass2_in_dir,
        pass2_out_dir,
        pass3_in_dir,
        pass3_out_dir,
        transport_audit_dir,
        evidence_normalization_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    full_blocks_payload = _prepare_full_blocks(
        full_blocks if full_blocks is not None else _extract_full_blocks(conversion_result)
    )
    if not full_blocks_payload:
        raise CodexFarmRunnerError(
            "Cannot run codex-farm recipe pipeline: no full_text blocks available."
        )
    full_blocks_by_index = {int(block["index"]): block for block in full_blocks_payload}
    max_index = max(full_blocks_by_index)
    total_blocks = max_index + 1

    source_hash = _resolve_source_hash(conversion_result)
    states = _build_states(conversion_result, workbook_slug=workbook_slug)
    pipelines = _resolve_pipeline_ids(run_settings)
    pass1_pattern_hints_enabled = bool(run_settings.codex_farm_pass1_pattern_hints_enabled)
    pass3_skip_pass2_ok_enabled = bool(run_settings.codex_farm_pass3_skip_pass2_ok)
    output_schema_paths: dict[str, str] = {}
    transport_audits: dict[str, dict[str, Any]] = {}
    evidence_normalizations: dict[str, dict[str, Any]] = {}
    if not states:
        recipe_guardrail_report, recipe_guardrail_rows = _build_recipe_guardrail_report(states)
        recipe_guardrail_report_path, recipe_guardrail_rows_path = (
            _write_recipe_guardrail_artifacts(
                llm_raw_dir=llm_raw_dir,
                report=recipe_guardrail_report,
                rows=recipe_guardrail_rows,
            )
        )
        _write_json(
            {
                "schema_version": "pass1_recipe_eligibility.v1",
                "rows": [],
                "counts": {"evaluated": 0, "proceed": 0, "clamp": 0, "drop": 0},
            },
            pass1_eligibility_diagnostics_path,
        )
        llm_manifest = {
            "enabled": True,
            "pipeline": run_settings.llm_recipe_pipeline.value,
            "pipelines": dict(pipelines),
            "output_schema_paths": dict(output_schema_paths),
            "codex_farm_cmd": run_settings.codex_farm_cmd,
            "codex_farm_model": run_settings.codex_farm_model,
            "codex_farm_reasoning_effort": _effort_override_value(
                run_settings.codex_farm_reasoning_effort
            ),
            "codex_farm_root": run_settings.codex_farm_root,
            "codex_farm_workspace_root": run_settings.codex_farm_workspace_root,
            "codex_farm_context_blocks": run_settings.codex_farm_context_blocks,
            "codex_farm_recipe_mode": run_settings.codex_farm_recipe_mode.value,
            "codex_farm_failure_mode": run_settings.codex_farm_failure_mode.value,
            "pass1_pattern_hints_enabled": pass1_pattern_hints_enabled,
            "counts": {
                "recipes_total": 0,
                "pass1_inputs": 0,
                "pass2_inputs": 0,
                "pass2_degraded_soft": 0,
                "pass2_degraded_hard": 0,
                "pass3_inputs": 0,
                "transport_audits": 0,
                "transport_mismatches": 0,
                "evidence_normalization_logs": 0,
                "structural_degraded": 0,
                "structural_failed": 0,
                "runtime_mode_violations": 0,
                "pass3_fallback": 0,
                "pass3_execution_mode_llm": 0,
                "pass3_execution_mode_deterministic": 0,
                "pass3_pass2_ok_utility_rows": 0,
                "pass3_pass2_ok_skip_candidates": 0,
                "pass3_pass2_ok_deterministic_skips": 0,
                "pass3_pass2_ok_llm_calls": 0,
                "selective_retry_attempted": 0,
                "selective_retry_pass2_attempts": 0,
                "selective_retry_pass2_recovered": 0,
                "selective_retry_pass3_attempts": 0,
                "selective_retry_pass3_recovered": 0,
            },
            "timing": {"pass1_seconds": 0.0, "pass2_seconds": 0.0, "pass3_seconds": 0.0},
            "paths": _paths_payload(
                pass1_in_dir=pass1_in_dir,
                pass1_out_dir=pass1_out_dir,
                pass2_in_dir=pass2_in_dir,
                pass2_out_dir=pass2_out_dir,
                pass3_in_dir=pass3_in_dir,
                pass3_out_dir=pass3_out_dir,
                llm_manifest_path=llm_raw_dir / "llm_manifest.json",
                transport_audit_dir=transport_audit_dir,
                evidence_normalization_dir=evidence_normalization_dir,
                pass1_eligibility_diagnostics_path=pass1_eligibility_diagnostics_path,
                recipe_guardrail_report_path=recipe_guardrail_report_path,
                recipe_guardrail_rows_path=recipe_guardrail_rows_path,
            ),
            "process_runs": {},
            "selective_retries": {},
            "recipes": {},
            "transport": {"audits": {}, "mismatches": []},
            "evidence_normalization": {"recipes": {}},
            "runtime_mode": {"violations": {}},
            "recipe_guardrails": {
                "report": recipe_guardrail_report,
                "rows": recipe_guardrail_rows,
            },
            "pass3_policy": {
                "pass2_ok_deterministic_skip_enabled": pass3_skip_pass2_ok_enabled,
                "pass2_ok_min_non_placeholder_instructions": (
                    _PASS3_PASS2_OK_MIN_NON_PLACEHOLDER_INSTRUCTIONS
                ),
                "pass2_ok_min_canonical_chars": _PASS3_PASS2_OK_MIN_CANONICAL_CHARS,
            },
        }
        _write_json(llm_manifest, llm_raw_dir / "llm_manifest.json")
        return CodexFarmApplyResult(
            updated_conversion_result=conversion_result,
            intermediate_overrides_by_recipe_id={},
            final_overrides_by_recipe_id={},
            llm_report={
                "enabled": True,
                "pipeline": run_settings.llm_recipe_pipeline.value,
                "llmRawDir": str(llm_raw_dir),
                "counts": llm_manifest["counts"],
                "output_schema_paths": dict(output_schema_paths),
                "process_runs": {},
                "selective_retries": {},
                "codex_farm_recipe_mode": run_settings.codex_farm_recipe_mode.value,
                "pass1_pattern_hints_enabled": pass1_pattern_hints_enabled,
                "transport": {"recipes_audited": 0, "mismatch_recipes": 0, "mismatch_recipe_ids": []},
                "runtime_mode": {"violations": {}},
                "evidence_normalization": {"recipes_logged": 0},
                "recipe_guardrail_report_path": str(recipe_guardrail_report_path),
                "recipe_guardrail_rows_path": str(recipe_guardrail_rows_path),
                "pass1_recipe_eligibility_diagnostics_path": str(
                    pass1_eligibility_diagnostics_path
                ),
                "pass3_policy": dict(llm_manifest["pass3_policy"]),
                "pass3_fallback_recipe_ids": [],
            },
            llm_raw_dir=llm_raw_dir,
        )

    pipeline_root = _resolve_pipeline_root(run_settings)
    workspace_root = _resolve_workspace_root(run_settings)
    env = {
        "CODEX_FARM_ROOT": str(pipeline_root),
        _CODEX_FARM_RECIPE_MODE_ENV: run_settings.codex_farm_recipe_mode.value,
    }
    codex_runner: CodexFarmRunner = runner or SubprocessCodexFarmRunner(
        cmd=run_settings.codex_farm_cmd,
        progress_callback=progress_callback,
    )
    if runner is None:
        ensure_codex_farm_pipelines_exist(
            cmd=run_settings.codex_farm_cmd,
            root_dir=pipeline_root,
            pipeline_ids=tuple(pipelines.values()),
            env=env,
        )
        output_schema_paths = {
            pass_name: str(
                resolve_codex_farm_output_schema_path(
                    root_dir=pipeline_root,
                    pipeline_id=pipeline_id,
                )
            )
            for pass_name, pipeline_id in pipelines.items()
        }
    codex_model = run_settings.codex_farm_model
    codex_reasoning_effort = _effort_override_value(
        run_settings.codex_farm_reasoning_effort
    )

    pass_timing: dict[str, float] = {
        "pass1_seconds": 0.0,
        "pass2_seconds": 0.0,
        "pass3_seconds": 0.0,
    }
    process_runs: dict[str, dict[str, Any]] = {}
    selective_retries: dict[str, dict[str, Any]] = {}
    intermediate_overrides: dict[str, dict[str, Any]] = {}
    final_overrides: dict[str, dict[str, Any]] = {}

    # Pass 1
    for state in states:
        pattern_hints = (
            _pattern_hints_for_state(state) if pass1_pattern_hints_enabled else []
        )
        pass1_input = Pass1RecipeChunkingInput(
            recipe_id=state.recipe_id,
            workbook_slug=workbook_slug,
            source_hash=source_hash,
            heuristic_start_block_index=state.heuristic_start,
            heuristic_end_block_index=state.heuristic_end,
            blocks_before=_block_lites_for_range(
                full_blocks_by_index,
                start=(state.heuristic_start or 0) - run_settings.codex_farm_context_blocks,
                end=(state.heuristic_start or 0) - 1,
                end_inclusive=True,
            ),
            blocks_candidate=_block_lites_for_range(
                full_blocks_by_index,
                start=state.heuristic_start,
                end=state.heuristic_end,
                end_inclusive=True,
            ),
            blocks_after=_block_lites_for_range(
                full_blocks_by_index,
                start=(state.heuristic_end or 0) + 1,
                end=(
                    (state.heuristic_end or 0)
                    + run_settings.codex_farm_context_blocks
                ),
                end_inclusive=True,
            ),
            pattern_hints=pattern_hints,
        )
        _write_json(
            pass1_input.model_dump(mode="json", by_alias=True),
            pass1_in_dir / state.bundle_name,
        )

    pass1_started = time.perf_counter()
    pass1_run = codex_runner.run_pipeline(
        pipelines["pass1"],
        pass1_in_dir,
        pass1_out_dir,
        env,
        root_dir=pipeline_root,
        workspace_root=workspace_root,
        model=codex_model,
        reasoning_effort=codex_reasoning_effort,
    )
    pass1_payload = as_pipeline_run_result_payload(pass1_run)
    if pass1_payload is not None:
        process_runs["pass1"] = pass1_payload
    pass_timing["pass1_seconds"] = round(time.perf_counter() - pass1_started, 3)
    _consume_pass1_outputs(states, pass1_out_dir, total_blocks=total_blocks)
    pass1_eligibility_payload = _apply_pass1_recipe_eligibility_gate(
        states,
        full_blocks_by_index=full_blocks_by_index,
        total_blocks=total_blocks,
    )
    _write_json(
        pass1_eligibility_payload,
        pass1_eligibility_diagnostics_path,
    )
    _apply_pass1_midpoint_clamps(states, total_blocks=total_blocks)
    _apply_pass1_to_result(conversion_result, states)
    _recompute_non_recipe_blocks(
        conversion_result,
        states=states,
        full_blocks_by_index=full_blocks_by_index,
    )

    # Pass 2
    pass2_states = [state for state in states if state.pass1_status == "ok"]
    for state in pass2_states:
        recipe_artifact_name = _recipe_artifact_filename(state.recipe_id)
        transport_selection = build_pass2_transport_selection(
            recipe_id=state.recipe_id,
            bundle_name=state.bundle_name,
            pass1_status=state.pass1_status,
            source_hash=source_hash,
            start_block_index=state.start_block_index,
            end_block_index=state.end_block_index,
            excluded_block_ids=sorted(state.excluded_block_ids),
            full_blocks_by_index=full_blocks_by_index,
        )
        block_indices = list(transport_selection.effective_indices)
        state.pass2_effective_indices = list(block_indices)
        effective_block_ids = list(transport_selection.effective_block_ids)
        included_blocks = list(transport_selection.included_blocks)
        state.pass2_payload_indices = [int(block.get("index")) for block in included_blocks]
        transport_audit = dict(transport_selection.audit)
        transport_audits[state.recipe_id] = transport_audit
        _write_json(
            transport_audit,
            transport_audit_dir / recipe_artifact_name,
        )
        if transport_audit["mismatch"]:
            _merge_structural_audit(
                state=state,
                audit=StructuralAuditResult(
                    status="failed",
                    severity="hard",
                    reason_codes=list(
                        transport_audit.get("verification", {}).get("reason_codes") or []
                    ),
                ),
            )
            state.pass2_status = "error"
            state.pass2_promotion_policy = "pass2_error"
            if run_settings.codex_farm_failure_mode.value == "fallback":
                state.pass3_status = "fallback"
                state.pass3_fallback_reason = "transport_invariant_failed"
                state.pass3_execution_mode = "deterministic"
                state.pass3_routing_reason = "transport_invariant_failed"
            state.errors.append(
                "transport_invariant_failed: pass1/pass2 effective selection diverged from pass2 payload."
            )
            state.warnings.append(
                _recipe_scoped_failure_mode_note(
                    mode=run_settings.codex_farm_failure_mode.value,
                    reason="transport_invariant_failed",
                )
            )
            continue
        canonical_text = "\n".join(
            str(block.get("text") or "").strip() for block in included_blocks
        ).strip()
        state.canonical_text = canonical_text
        if not canonical_text:
            state.pass2_status = "error"
            state.pass2_promotion_policy = "pass2_error"
            state.errors.append("pass2 input empty after pass1 boundary/exclusion application.")
            continue
        normalization_payload = normalize_pass2_evidence(included_blocks)
        evidence_normalizations[state.recipe_id] = {
            "path": str(evidence_normalization_dir / recipe_artifact_name),
            "stats": dict(normalization_payload.get("stats") or {}),
        }
        _write_json(
            {
                "recipe_id": state.recipe_id,
                "bundle_name": state.bundle_name,
                "stats": dict(normalization_payload.get("stats") or {}),
                "events": list(normalization_payload.get("events") or []),
                "line_rows": list(normalization_payload.get("line_rows") or []),
            },
            evidence_normalization_dir / recipe_artifact_name,
        )
        if _uses_compact_pass2_payload(pipelines["pass2"]):
            pass2_input = _build_pass2_input_compact(
                state=state,
                workbook_slug=workbook_slug,
                source_hash=source_hash,
                included_blocks=included_blocks,
            )
        else:
            pass2_input = _build_pass2_input_legacy(
                state=state,
                workbook_slug=workbook_slug,
                source_hash=source_hash,
                included_blocks=included_blocks,
                normalization_payload=normalization_payload,
            )
        _write_json(
            pass2_input.model_dump(mode="json", by_alias=True),
            pass2_in_dir / state.bundle_name,
        )
    if any(path.suffix == ".json" for path in pass2_in_dir.iterdir()):
        pass2_started = time.perf_counter()
        pass2_run = codex_runner.run_pipeline(
            pipelines["pass2"],
            pass2_in_dir,
            pass2_out_dir,
            env,
            root_dir=pipeline_root,
            workspace_root=workspace_root,
            model=codex_model,
            reasoning_effort=codex_reasoning_effort,
        )
        pass2_payload = as_pipeline_run_result_payload(pass2_run)
        if pass2_payload is not None:
            process_runs["pass2"] = pass2_payload
        pass_timing["pass2_seconds"] = round(time.perf_counter() - pass2_started, 3)
        pass2_selective_retry = _run_benchmark_selective_retry(
            pass_name="pass2",
            pipeline_id=pipelines["pass2"],
            pass_dir=pass2_in_dir.parent,
            llm_raw_dir=llm_raw_dir,
            original_in_dir=pass2_in_dir,
            original_out_dir=pass2_out_dir,
            expected_bundle_filenames=_json_bundle_filenames(pass2_in_dir),
            states_by_bundle_name={state.bundle_name: state for state in pass2_states},
            original_process_run=pass2_payload,
            run_settings=run_settings,
            codex_runner=codex_runner,
            env=env,
            pipeline_root=pipeline_root,
            workspace_root=workspace_root,
            codex_model=codex_model,
            codex_reasoning_effort=codex_reasoning_effort,
        )
        if pass2_selective_retry is not None:
            selective_retries["pass2"] = pass2_selective_retry
    for state in pass2_states:
        if state.pass2_status == "error":
            continue
        out_path = pass2_out_dir / state.bundle_name
        if not out_path.exists():
            state.pass2_status = "error"
            state.pass2_promotion_policy = "pass2_error"
            state.errors.append("missing pass2 output bundle.")
            continue
        try:
            output = load_contract_json(out_path, Pass2SchemaOrgOutput)
        except Exception as exc:  # noqa: BLE001
            state.pass2_status = "error"
            state.pass2_promotion_policy = "pass2_error"
            state.errors.append(f"invalid pass2 output: {exc}")
            continue
        state.pass2_output = output
        guard_warnings = _validate_pass2_guardrails(
            output=output,
            canonical_text=state.canonical_text,
        )
        state.warnings.extend(list(output.warnings))
        state.warnings.extend(guard_warnings)
        structural_audit = classify_pass2_structural_audit(
            output=output,
            guard_warnings=guard_warnings,
            transport_verification=transport_audits.get(state.recipe_id, {}).get("verification"),
        )
        _merge_structural_audit(state=state, audit=structural_audit)
        state.pass2_degradation_reasons = list(structural_audit.reason_codes)
        if state.pass2_degradation_reasons:
            state.pass2_status = "degraded"
            state.pass2_degradation_severity = structural_audit.severity
            state.warnings.extend(
                f"pass2 degraded: {reason}" for reason in state.pass2_degradation_reasons
            )
            if state.pass2_degradation_severity == "hard":
                state.pass2_promotion_policy = "hard_fallback"
                state.pass3_status = "fallback"
                state.pass3_fallback_reason = (
                    "pass2 degraded: " + "; ".join(state.pass2_degradation_reasons)
                )
                state.pass3_execution_mode = "deterministic"
                state.pass3_routing_reason = "pass2_hard_degradation_forced_fallback"
                state.warnings.append(
                    _recipe_scoped_failure_mode_note(
                        mode=run_settings.codex_farm_failure_mode.value,
                        reason="pass2 degraded",
                    )
                )
            else:
                state.pass2_promotion_policy = "soft_degradation_selective_pass3"
        else:
            state.pass2_status = "ok"
            state.pass2_degradation_severity = "none"
            state.pass2_promotion_policy = "pass2_ok"
            state.pass3_utility_signal = _build_pass3_utility_signal_for_pass2_ok(
                output=output,
                canonical_text=state.canonical_text,
            )
        intermediate_overrides[state.recipe_id] = dict(output.schemaorg_recipe)

    # Pass 3
    pass3_llm_states: list[_RecipeState] = []
    pass3_deterministic_states: list[_RecipeState] = []
    for state in states:
        if state.pass2_output is None:
            continue
        if state.pass3_status in {"error", "fallback"}:
            continue
        should_run_pass3, routing_reason = _should_run_pass3_llm(
            state=state,
            pass3_skip_pass2_ok_enabled=pass3_skip_pass2_ok_enabled,
        )
        state.pass3_routing_reason = routing_reason
        if should_run_pass3:
            state.pass3_execution_mode = "llm"
            if state.pass2_status == "degraded":
                state.pass2_promotion_policy = "soft_degradation_llm_pass3"
            elif state.pass2_status == "ok":
                state.pass2_promotion_policy = "pass2_ok_llm_pass3"
            pass3_llm_states.append(state)
        else:
            state.pass3_execution_mode = "deterministic"
            if (
                state.pass2_status == "degraded"
                and state.pass2_degradation_severity == "soft"
            ):
                state.pass2_promotion_policy = (
                    "soft_degradation_deterministic_promotion"
                )
            elif (
                state.pass2_status == "ok"
                and state.pass3_routing_reason == "pass2_ok_high_confidence_deterministic"
            ):
                state.pass2_promotion_policy = "pass2_ok_deterministic_promotion"
            pass3_deterministic_states.append(state)

    for state in pass3_deterministic_states:
        fallback_payload = _build_pass3_deterministic_fallback_payload(state=state)
        if fallback_payload is None:
            state.pass3_status = "error"
            state.errors.append("pass3 deterministic promotion draft_v1 could not be generated.")
            continue
        try:
            fallback_model = RecipeDraftV1.model_validate(fallback_payload)
        except Exception as exc:  # noqa: BLE001
            state.pass3_status = "error"
            state.errors.append(
                f"pass3 deterministic promotion draft_v1 validation failed: {exc}"
            )
            continue
        state.pass3_status = "ok"
        state.warnings.append(
            "pass3 skipped; deterministic promotion applied "
            f"({state.pass3_routing_reason or 'deterministic_path'})."
        )
        final_overrides[state.recipe_id] = fallback_model.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )

    for state in pass3_llm_states:
        assert state.pass2_output is not None
        if _uses_compact_pass3_payload(pipelines["pass3"]):
            pass3_input = _build_pass3_input_compact(
                state=state,
                workbook_slug=workbook_slug,
                source_hash=source_hash,
            )
        else:
            pass3_input = _build_pass3_input_legacy(
                state=state,
                workbook_slug=workbook_slug,
                source_hash=source_hash,
            )
        _write_json(
            pass3_input.model_dump(mode="json", by_alias=True),
            pass3_in_dir / state.bundle_name,
        )
    if any(path.suffix == ".json" for path in pass3_in_dir.iterdir()):
        pass3_started = time.perf_counter()
        pass3_run = codex_runner.run_pipeline(
            pipelines["pass3"],
            pass3_in_dir,
            pass3_out_dir,
            env,
            root_dir=pipeline_root,
            workspace_root=workspace_root,
            model=codex_model,
            reasoning_effort=codex_reasoning_effort,
        )
        pass3_payload = as_pipeline_run_result_payload(pass3_run)
        if pass3_payload is not None:
            process_runs["pass3"] = pass3_payload
        pass_timing["pass3_seconds"] = round(time.perf_counter() - pass3_started, 3)
        pass3_selective_retry = _run_benchmark_selective_retry(
            pass_name="pass3",
            pipeline_id=pipelines["pass3"],
            pass_dir=pass3_in_dir.parent,
            llm_raw_dir=llm_raw_dir,
            original_in_dir=pass3_in_dir,
            original_out_dir=pass3_out_dir,
            expected_bundle_filenames=_json_bundle_filenames(pass3_in_dir),
            states_by_bundle_name={state.bundle_name: state for state in pass3_llm_states},
            original_process_run=pass3_payload,
            run_settings=run_settings,
            codex_runner=codex_runner,
            env=env,
            pipeline_root=pipeline_root,
            workspace_root=workspace_root,
            codex_model=codex_model,
            codex_reasoning_effort=codex_reasoning_effort,
        )
        if pass3_selective_retry is not None:
            selective_retries["pass3"] = pass3_selective_retry
    for state in pass3_llm_states:
        out_path = pass3_out_dir / state.bundle_name
        pass3_error: str | None = None
        pass3_warnings: list[str] = []
        if not out_path.exists():
            pass3_error = "missing pass3 output bundle."
        else:
            try:
                output = load_contract_json(out_path, Pass3FinalDraftOutput)
            except Exception as exc:  # noqa: BLE001
                pass3_error = f"invalid pass3 output: {exc}"
            else:
                pass3_warnings.extend(list(output.warnings))
                draft_payload = _normalize_draft_payload(dict(output.draft_v1))
                if _repair_placeholder_only_steps_from_pass2(
                    draft_payload=draft_payload,
                    pass2_output=state.pass2_output,
                ):
                    pass3_warnings.append(
                        "pass3 placeholder-only steps repaired from pass2 extracted instructions."
                    )
                structural_audit = classify_pass3_structural_audit(
                    draft_payload=draft_payload,
                    pass2_output=state.pass2_output,
                    ingredient_step_mapping=output.ingredient_step_mapping,
                    ingredient_step_mapping_reason=output.ingredient_step_mapping_reason,
                    pass2_reason_codes=state.pass2_degradation_reasons,
                )
                _merge_structural_audit(state=state, audit=structural_audit)
                low_quality_reasons = _render_structural_reason_messages(
                    structural_audit.reason_codes
                )
                if low_quality_reasons:
                    pass3_error = (
                        "pass3 output rejected as low quality: "
                        + "; ".join(low_quality_reasons)
                    )
                    pass3_warnings.extend(low_quality_reasons)
                else:
                    if _patch_recipe_id(draft_payload, recipe_id=state.recipe_id):
                        pass3_warnings.append("pass3 draft id patched to expected recipe_id.")
                    try:
                        draft_model = RecipeDraftV1.model_validate(draft_payload)
                    except Exception as exc:  # noqa: BLE001
                        pass3_error = f"pass3 draft_v1 validation failed: {exc}"
                    else:
                        state.warnings.extend(pass3_warnings)
                        state.pass3_status = "ok"
                        final_overrides[state.recipe_id] = draft_model.model_dump(
                            mode="json",
                            by_alias=True,
                            exclude_none=True,
                        )
                        continue

        fallback_payload = _build_pass3_deterministic_fallback_payload(
            state=state,
        )
        if fallback_payload is not None:
            try:
                fallback_model = RecipeDraftV1.model_validate(fallback_payload)
            except Exception as exc:  # noqa: BLE001
                if pass3_error:
                    state.errors.append(pass3_error)
                state.pass3_status = "error"
                state.errors.append(f"pass3 fallback draft_v1 validation failed: {exc}")
                continue
            if pass3_error:
                state.errors.append(pass3_error)
            state.pass3_status = "fallback"
            state.pass3_execution_mode = "llm_then_deterministic_fallback"
            state.pass3_fallback_reason = pass3_error
            state.warnings.extend(pass3_warnings)
            state.warnings.append(
                _recipe_scoped_failure_mode_note(
                    mode=run_settings.codex_farm_failure_mode.value,
                    reason="pass3 fallback",
                )
            )
            final_overrides[state.recipe_id] = fallback_model.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            )
            continue

        state.pass3_status = "error"
        if pass3_error:
            state.errors.append(pass3_error)

    for state in states:
        if state.pass3_status != "fallback":
            continue
        if state.recipe_id in final_overrides:
            continue
        fallback_payload = _build_pass3_deterministic_fallback_payload(state=state)
        if fallback_payload is None:
            state.pass3_status = "error"
            state.errors.append("pass3 fallback draft_v1 could not be generated.")
            continue
        try:
            fallback_model = RecipeDraftV1.model_validate(fallback_payload)
        except Exception as exc:  # noqa: BLE001
            state.pass3_status = "error"
            state.errors.append(f"pass3 fallback draft_v1 validation failed: {exc}")
            continue
        if not state.pass3_execution_mode:
            state.pass3_execution_mode = "deterministic"
        final_overrides[state.recipe_id] = fallback_model.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )

    llm_manifest_path = llm_raw_dir / "llm_manifest.json"
    recipe_guardrail_report, recipe_guardrail_rows = _build_recipe_guardrail_report(states)
    recipe_guardrail_report_path, recipe_guardrail_rows_path = _write_recipe_guardrail_artifacts(
        llm_raw_dir=llm_raw_dir,
        report=recipe_guardrail_report,
        rows=recipe_guardrail_rows,
    )
    llm_manifest = _build_llm_manifest(
        run_settings=run_settings,
        llm_raw_dir=llm_raw_dir,
        states=states,
        pass_timing=pass_timing,
        pass1_in_dir=pass1_in_dir,
        pass1_out_dir=pass1_out_dir,
        pass2_in_dir=pass2_in_dir,
        pass2_out_dir=pass2_out_dir,
        pass3_in_dir=pass3_in_dir,
        pass3_out_dir=pass3_out_dir,
        llm_manifest_path=llm_manifest_path,
        transport_audit_dir=transport_audit_dir,
        evidence_normalization_dir=evidence_normalization_dir,
        pipelines=pipelines,
        output_schema_paths=output_schema_paths,
        process_runs=process_runs,
        selective_retries=selective_retries,
        pass1_pattern_hints_enabled=pass1_pattern_hints_enabled,
        pass3_skip_pass2_ok_enabled=pass3_skip_pass2_ok_enabled,
        transport_audits=transport_audits,
        evidence_normalizations=evidence_normalizations,
        pass1_eligibility_diagnostics_path=pass1_eligibility_diagnostics_path,
        recipe_guardrail_report_path=recipe_guardrail_report_path,
        recipe_guardrail_rows_path=recipe_guardrail_rows_path,
        recipe_guardrail_report=recipe_guardrail_report,
        recipe_guardrail_rows=recipe_guardrail_rows,
    )
    _write_json(llm_manifest, llm_manifest_path)

    llm_report = {
        "enabled": True,
        "pipeline": run_settings.llm_recipe_pipeline.value,
        "pipelines": dict(pipelines),
        "output_schema_paths": dict(output_schema_paths),
        "llmRawDir": str(llm_raw_dir),
        "counts": llm_manifest["counts"],
        "timing": llm_manifest["timing"],
        "failures": llm_manifest["failures"],
        "process_runs": llm_manifest.get("process_runs", {}),
        "selective_retries": llm_manifest.get("selective_retries", {}),
        "codex_farm_recipe_mode": run_settings.codex_farm_recipe_mode.value,
        "pass1_pattern_hints_enabled": pass1_pattern_hints_enabled,
        "transport": {
            "recipes_audited": llm_manifest["counts"].get("transport_audits", 0),
            "mismatch_recipes": llm_manifest["counts"].get("transport_mismatches", 0),
            "mismatch_recipe_ids": list(llm_manifest.get("transport", {}).get("mismatches", [])),
        },
        "runtime_mode": dict(llm_manifest.get("runtime_mode", {})),
        "evidence_normalization": {
            "recipes_logged": llm_manifest["counts"].get("evidence_normalization_logs", 0),
        },
        "recipe_guardrail_report_path": str(recipe_guardrail_report_path),
        "recipe_guardrail_rows_path": str(recipe_guardrail_rows_path),
        "pass1_recipe_eligibility_diagnostics_path": str(
            pass1_eligibility_diagnostics_path
        ),
        "pass3_policy": dict(llm_manifest.get("pass3_policy", {})),
        "pass3_fallback_recipe_ids": [
            state.recipe_id for state in states if state.pass3_status == "fallback"
        ],
    }

    return CodexFarmApplyResult(
        updated_conversion_result=conversion_result,
        intermediate_overrides_by_recipe_id=intermediate_overrides,
        final_overrides_by_recipe_id=final_overrides,
        llm_report=llm_report,
        llm_raw_dir=llm_raw_dir,
    )


def build_codex_farm_recipe_execution_plan(
    *,
    conversion_result: ConversionResult,
    run_settings: RunSettings,
    workbook_slug: str,
    full_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if run_settings.llm_recipe_pipeline.value == "off":
        return {
            "enabled": False,
            "pipeline": "off",
            "recipe_count": len(conversion_result.recipes),
            "planned_tasks": [],
        }

    full_blocks_payload = _prepare_full_blocks(
        full_blocks if full_blocks is not None else _extract_full_blocks(conversion_result)
    )
    full_blocks_by_index = {int(block["index"]): block for block in full_blocks_payload}
    source_hash = _resolve_source_hash(conversion_result)
    states = _build_states(conversion_result, workbook_slug=workbook_slug)
    pipelines = _resolve_pipeline_ids(run_settings)
    pass1_pattern_hints_enabled = bool(run_settings.codex_farm_pass1_pattern_hints_enabled)
    planned_tasks: list[dict[str, Any]] = []

    for recipe_index, state in enumerate(states):
        pattern_hints = (
            _pattern_hints_for_state(state) if pass1_pattern_hints_enabled else []
        )
        pass1_input = Pass1RecipeChunkingInput(
            recipe_id=state.recipe_id,
            workbook_slug=workbook_slug,
            source_hash=source_hash,
            heuristic_start_block_index=state.heuristic_start,
            heuristic_end_block_index=state.heuristic_end,
            blocks_before=_block_lites_for_range(
                full_blocks_by_index,
                start=(state.heuristic_start or 0) - run_settings.codex_farm_context_blocks,
                end=(state.heuristic_start or 0) - 1,
                end_inclusive=True,
            ),
            blocks_candidate=_block_lites_for_range(
                full_blocks_by_index,
                start=state.heuristic_start,
                end=state.heuristic_end,
                end_inclusive=True,
            ),
            blocks_after=_block_lites_for_range(
                full_blocks_by_index,
                start=(state.heuristic_end or 0) + 1,
                end=(
                    (state.heuristic_end or 0)
                    + run_settings.codex_farm_context_blocks
                ),
                end_inclusive=True,
            ),
            pattern_hints=pattern_hints,
        )
        pass1_payload = pass1_input.model_dump(mode="json", by_alias=True)
        planned_tasks.append(
            {
                "recipe_id": state.recipe_id,
                "recipe_index": recipe_index,
                "bundle_name": state.bundle_name,
                "planned_passes": [
                    {
                        "pass": "pass1",
                        "pipeline_id": pipelines["pass1"],
                        "input_fingerprint": _codex_plan_fingerprint(pass1_payload),
                        "input_block_count": (
                            len(pass1_payload.get("blocks_before") or [])
                            + len(pass1_payload.get("blocks_candidate") or [])
                            + len(pass1_payload.get("blocks_after") or [])
                        ),
                        "contingent": False,
                    },
                    {
                        "pass": "pass2",
                        "pipeline_id": pipelines["pass2"],
                        "depends_on": "pass1",
                        "heuristic_block_range": [state.heuristic_start, state.heuristic_end],
                        "contingent": True,
                    },
                    {
                        "pass": "pass3",
                        "pipeline_id": pipelines["pass3"],
                        "depends_on": "pass2",
                        "heuristic_block_range": [state.heuristic_start, state.heuristic_end],
                        "contingent": True,
                    },
                ],
            }
        )

    return {
        "enabled": True,
        "pipeline": run_settings.llm_recipe_pipeline.value,
        "recipe_count": len(states),
        "pipelines": dict(pipelines),
        "codex_farm_model": run_settings.codex_farm_model,
        "codex_farm_reasoning_effort": _effort_override_value(
            run_settings.codex_farm_reasoning_effort
        ),
        "planned_tasks": planned_tasks,
    }


def _codex_plan_fingerprint(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _paths_payload(
    *,
    pass1_in_dir: Path,
    pass1_out_dir: Path,
    pass2_in_dir: Path,
    pass2_out_dir: Path,
    pass3_in_dir: Path,
    pass3_out_dir: Path,
    llm_manifest_path: Path,
    transport_audit_dir: Path | None = None,
    evidence_normalization_dir: Path | None = None,
    pass1_eligibility_diagnostics_path: Path | None = None,
    recipe_guardrail_report_path: Path | None = None,
    recipe_guardrail_rows_path: Path | None = None,
) -> dict[str, str]:
    payload = {
        "pass1_in": str(pass1_in_dir),
        "pass1_out": str(pass1_out_dir),
        "pass2_in": str(pass2_in_dir),
        "pass2_out": str(pass2_out_dir),
        "pass3_in": str(pass3_in_dir),
        "pass3_out": str(pass3_out_dir),
        "llm_manifest": str(llm_manifest_path),
    }
    if transport_audit_dir is not None:
        payload["transport_audit_dir"] = str(transport_audit_dir)
    if evidence_normalization_dir is not None:
        payload["evidence_normalization_dir"] = str(evidence_normalization_dir)
    if pass1_eligibility_diagnostics_path is not None:
        payload["pass1_recipe_eligibility_diagnostics"] = str(
            pass1_eligibility_diagnostics_path
        )
    if recipe_guardrail_report_path is not None:
        payload["recipe_guardrail_report"] = str(recipe_guardrail_report_path)
    if recipe_guardrail_rows_path is not None:
        payload["recipe_guardrail_rows"] = str(recipe_guardrail_rows_path)
    return payload


def _build_recipe_guardrail_rows(states: list[_RecipeState]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for state in states:
        if state.pass1_eligibility_action in {"clamp", "drop"}:
            rows.append(
                {
                    "recipe_id": state.recipe_id,
                    "guardrail_type": "pass1_eligibility",
                    "applied": True,
                    "decision": state.pass1_eligibility_action,
                    "reasons": list(state.pass1_eligibility_reasons),
                }
            )
        if state.pass3_routing_reason == "transport_invariant_failed":
            rows.append(
                {
                    "recipe_id": state.recipe_id,
                    "guardrail_type": "transport_invariant",
                    "applied": True,
                    "decision": "deterministic_fallback",
                    "reasons": ["transport_invariant_failed"],
                }
            )
        if state.pass2_status == "degraded":
            rows.append(
                {
                    "recipe_id": state.recipe_id,
                    "guardrail_type": "pass2_degradation",
                    "applied": True,
                    "decision": state.pass2_degradation_severity or "degraded",
                    "reasons": list(state.pass2_degradation_reasons),
                }
            )
        if state.pass3_execution_mode == "deterministic" and state.pass3_routing_reason:
            rows.append(
                {
                    "recipe_id": state.recipe_id,
                    "guardrail_type": "pass3_routing",
                    "applied": True,
                    "decision": state.pass3_routing_reason,
                    "reasons": (
                        list(state.pass2_degradation_reasons)
                        if state.pass2_degradation_reasons
                        else []
                    ),
                }
            )
    return rows


def _build_recipe_guardrail_report(
    states: list[_RecipeState],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = _build_recipe_guardrail_rows(states)
    report = {
        "schema_version": _RECIPE_GUARDRAIL_REPORT_SCHEMA_VERSION,
        "guardrail_name": "recipe_codex_routing",
        "mode": "enforce",
        "preview_only": False,
        "applied": bool(rows),
        "would_change_rows": len(rows),
        "summary": {
            "recipes_total": len(states),
            "pass1_eligibility_rows": sum(
                1 for row in rows if row["guardrail_type"] == "pass1_eligibility"
            ),
            "transport_rows": sum(
                1 for row in rows if row["guardrail_type"] == "transport_invariant"
            ),
            "pass2_degradation_rows": sum(
                1 for row in rows if row["guardrail_type"] == "pass2_degradation"
            ),
            "pass3_routing_rows": sum(
                1 for row in rows if row["guardrail_type"] == "pass3_routing"
            ),
        },
    }
    return report, rows


def _write_recipe_guardrail_artifacts(
    *,
    llm_raw_dir: Path,
    report: dict[str, Any],
    rows: list[dict[str, Any]],
) -> tuple[Path, Path]:
    report_path = llm_raw_dir / "guardrail_report.json"
    rows_path = llm_raw_dir / "guardrail_rows.jsonl"
    _write_json(report, report_path)
    rows_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return report_path, rows_path


def _build_llm_manifest(
    *,
    run_settings: RunSettings,
    llm_raw_dir: Path,
    states: list[_RecipeState],
    pass_timing: dict[str, float],
    pass1_in_dir: Path,
    pass1_out_dir: Path,
    pass2_in_dir: Path,
    pass2_out_dir: Path,
    pass3_in_dir: Path,
    pass3_out_dir: Path,
    llm_manifest_path: Path,
    transport_audit_dir: Path,
    evidence_normalization_dir: Path,
    pipelines: dict[str, str],
    output_schema_paths: dict[str, str],
    process_runs: dict[str, dict[str, Any]],
    selective_retries: dict[str, dict[str, Any]],
    pass1_pattern_hints_enabled: bool,
    pass3_skip_pass2_ok_enabled: bool,
    transport_audits: dict[str, dict[str, Any]],
    evidence_normalizations: dict[str, dict[str, Any]],
    pass1_eligibility_diagnostics_path: Path,
    recipe_guardrail_report_path: Path,
    recipe_guardrail_rows_path: Path,
    recipe_guardrail_report: dict[str, Any],
    recipe_guardrail_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    recipe_rows: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    for state in states:
        row = {
            "pass1": state.pass1_status,
            "pass2": state.pass2_status,
            "pass3": state.pass3_status,
            "warnings": list(state.warnings),
            "errors": list(state.errors),
        }
        transport_row = transport_audits.get(state.recipe_id)
        if isinstance(transport_row, dict):
            row["transport_audit"] = dict(transport_row)
        normalization_row = evidence_normalizations.get(state.recipe_id)
        if isinstance(normalization_row, dict):
            row["evidence_normalization"] = dict(normalization_row)
        if state.pass2_degradation_reasons:
            row["pass2_degradation_reasons"] = list(state.pass2_degradation_reasons)
        if state.pass2_degradation_severity:
            row["pass2_degradation_severity"] = state.pass2_degradation_severity
        if state.pass2_promotion_policy:
            row["pass2_promotion_policy"] = state.pass2_promotion_policy
        if state.pass3_execution_mode:
            row["pass3_execution_mode"] = state.pass3_execution_mode
        if state.pass3_routing_reason:
            row["pass3_routing_reason"] = state.pass3_routing_reason
        if isinstance(state.pass3_utility_signal, dict):
            row["pass3_utility_signal"] = dict(state.pass3_utility_signal)
        if state.pass3_fallback_reason:
            row["pass3_fallback_reason"] = state.pass3_fallback_reason
        if isinstance(state.pass1_span_loss_metrics, dict):
            row["pass1_span_loss_metrics"] = dict(state.pass1_span_loss_metrics)
        if state.pass1_eligibility_status:
            row["eligibility_status"] = state.pass1_eligibility_status
        if state.pass1_eligibility_action:
            row["eligibility_action"] = state.pass1_eligibility_action
        if state.pass1_eligibility_score is not None:
            row["eligibility_score"] = int(state.pass1_eligibility_score)
        if isinstance(state.pass1_eligibility_score_components, dict):
            row["eligibility_score_components"] = dict(
                state.pass1_eligibility_score_components
            )
        if state.pass1_eligibility_reasons:
            row["eligibility_reasons"] = list(state.pass1_eligibility_reasons)
        row["structural_status"] = state.structural_status
        row["structural_reason_codes"] = list(state.structural_reason_codes)
        recipe_rows[state.recipe_id] = row
        if state.errors:
            failures.append({"recipe_id": state.recipe_id, "errors": list(state.errors)})
    mismatch_recipe_ids = sorted(
        recipe_id
        for recipe_id, audit in transport_audits.items()
        if isinstance(audit, dict) and bool(audit.get("mismatch"))
    )
    pass2_retry_payload = (
        selective_retries.get("pass2") if isinstance(selective_retries.get("pass2"), dict) else None
    )
    pass3_retry_payload = (
        selective_retries.get("pass3") if isinstance(selective_retries.get("pass3"), dict) else None
    )
    counts = {
        "recipes_total": len(states),
        "pass1_inputs": len(list(pass1_in_dir.glob("*.json"))),
        "pass1_ok": sum(1 for state in states if state.pass1_status == "ok"),
        "pass1_dropped": sum(1 for state in states if state.pass1_status == "dropped"),
        "pass1_errors": sum(1 for state in states if state.pass1_status == "error"),
        "pass1_eligibility_proceed": sum(
            1 for state in states if state.pass1_eligibility_action == "proceed"
        ),
        "pass1_eligibility_clamp": sum(
            1 for state in states if state.pass1_eligibility_action == "clamp"
        ),
        "pass1_eligibility_drop": sum(
            1 for state in states if state.pass1_eligibility_action == "drop"
        ),
        "pass2_inputs": len(list(pass2_in_dir.glob("*.json"))),
        "pass2_ok": sum(1 for state in states if state.pass2_status == "ok"),
        "pass2_degraded": sum(1 for state in states if state.pass2_status == "degraded"),
        "pass2_degraded_soft": sum(
            1
            for state in states
            if state.pass2_status == "degraded"
            and state.pass2_degradation_severity == "soft"
        ),
        "pass2_degraded_hard": sum(
            1
            for state in states
            if state.pass2_status == "degraded"
            and state.pass2_degradation_severity == "hard"
        ),
        "pass2_errors": sum(1 for state in states if state.pass2_status == "error"),
        "pass3_inputs": len(list(pass3_in_dir.glob("*.json"))),
        "pass3_ok": sum(1 for state in states if state.pass3_status == "ok"),
        "pass3_fallback": sum(1 for state in states if state.pass3_status == "fallback"),
        "pass3_errors": sum(1 for state in states if state.pass3_status == "error"),
        "pass3_execution_mode_llm": sum(
            1
            for state in states
            if state.pass3_execution_mode in {"llm", "llm_then_deterministic_fallback"}
        ),
        "pass3_execution_mode_deterministic": sum(
            1 for state in states if state.pass3_execution_mode == "deterministic"
        ),
        "pass3_pass2_ok_utility_rows": sum(
            1
            for state in states
            if state.pass2_status == "ok" and isinstance(state.pass3_utility_signal, dict)
        ),
        "pass3_pass2_ok_skip_candidates": sum(
            1
            for state in states
            if state.pass2_status == "ok"
            and isinstance(state.pass3_utility_signal, dict)
            and bool(state.pass3_utility_signal.get("deterministic_low_risk"))
        ),
        "pass3_pass2_ok_deterministic_skips": sum(
            1
            for state in states
            if state.pass2_status == "ok"
            and state.pass3_execution_mode == "deterministic"
            and state.pass3_routing_reason == "pass2_ok_high_confidence_deterministic"
        ),
        "pass3_pass2_ok_llm_calls": sum(
            1
            for state in states
            if state.pass2_status == "ok"
            and state.pass3_execution_mode in {"llm", "llm_then_deterministic_fallback"}
        ),
        "selective_retry_attempted": int(
            bool(pass2_retry_payload) or bool(pass3_retry_payload)
        ),
        "selective_retry_pass2_attempts": len(
            list(pass2_retry_payload.get("attempts") or [])
        )
        if isinstance(pass2_retry_payload, dict)
        else 0,
        "selective_retry_pass2_recovered": int(
            pass2_retry_payload.get("recovered_bundle_count") or 0
        )
        if isinstance(pass2_retry_payload, dict)
        else 0,
        "selective_retry_pass3_attempts": len(
            list(pass3_retry_payload.get("attempts") or [])
        )
        if isinstance(pass3_retry_payload, dict)
        else 0,
        "selective_retry_pass3_recovered": int(
            pass3_retry_payload.get("recovered_bundle_count") or 0
        )
        if isinstance(pass3_retry_payload, dict)
        else 0,
        "transport_audits": len(transport_audits),
        "transport_mismatches": len(mismatch_recipe_ids),
        "evidence_normalization_logs": len(evidence_normalizations),
        "structural_degraded": sum(
            1 for state in states if state.structural_status == "degraded"
        ),
        "structural_failed": sum(
            1 for state in states if state.structural_status == "failed"
        ),
        "runtime_mode_violations": sum(
            1
            for payload in process_runs.values()
            if isinstance(payload, dict)
            and isinstance(payload.get("runtime_mode_audit"), dict)
            and str(payload["runtime_mode_audit"].get("status") or "").strip().lower()
            not in {"", "ok"}
        ),
    }
    runtime_mode_violations = {
        pass_name: dict(payload.get("runtime_mode_audit"))
        for pass_name, payload in process_runs.items()
        if isinstance(payload, dict)
        and isinstance(payload.get("runtime_mode_audit"), dict)
        and str(payload["runtime_mode_audit"].get("status") or "").strip().lower()
        not in {"", "ok"}
    }
    return {
        "enabled": True,
        "pipeline": run_settings.llm_recipe_pipeline.value,
        "codex_farm_cmd": run_settings.codex_farm_cmd,
        "codex_farm_model": run_settings.codex_farm_model,
        "codex_farm_reasoning_effort": _effort_override_value(
            run_settings.codex_farm_reasoning_effort
        ),
        "codex_farm_root": run_settings.codex_farm_root,
        "codex_farm_workspace_root": run_settings.codex_farm_workspace_root,
        "codex_farm_context_blocks": run_settings.codex_farm_context_blocks,
        "codex_farm_recipe_mode": run_settings.codex_farm_recipe_mode.value,
        "codex_farm_failure_mode": run_settings.codex_farm_failure_mode.value,
        "pass1_pattern_hints_enabled": pass1_pattern_hints_enabled,
        "pipelines": dict(pipelines),
        "output_schema_paths": dict(output_schema_paths),
        "counts": counts,
        "timing": pass_timing,
        "paths": _paths_payload(
            pass1_in_dir=pass1_in_dir,
            pass1_out_dir=pass1_out_dir,
            pass2_in_dir=pass2_in_dir,
            pass2_out_dir=pass2_out_dir,
            pass3_in_dir=pass3_in_dir,
            pass3_out_dir=pass3_out_dir,
            llm_manifest_path=llm_manifest_path,
            transport_audit_dir=transport_audit_dir,
            evidence_normalization_dir=evidence_normalization_dir,
            pass1_eligibility_diagnostics_path=pass1_eligibility_diagnostics_path,
            recipe_guardrail_report_path=recipe_guardrail_report_path,
            recipe_guardrail_rows_path=recipe_guardrail_rows_path,
        ),
        "process_runs": dict(process_runs),
        "selective_retries": dict(selective_retries),
        "failures": failures,
        "recipes": recipe_rows,
        "llm_raw_dir": str(llm_raw_dir),
        "transport": {
            "mismatches": mismatch_recipe_ids,
            "audits": dict(transport_audits),
        },
        "evidence_normalization": {"recipes": dict(evidence_normalizations)},
        "runtime_mode": {
            "violations": runtime_mode_violations,
        },
        "recipe_guardrails": {
            "report": dict(recipe_guardrail_report),
            "rows": list(recipe_guardrail_rows),
        },
        "pass3_policy": {
            "pass2_ok_deterministic_skip_enabled": pass3_skip_pass2_ok_enabled,
            "pass2_ok_min_non_placeholder_instructions": (
                _PASS3_PASS2_OK_MIN_NON_PLACEHOLDER_INSTRUCTIONS
            ),
            "pass2_ok_min_canonical_chars": _PASS3_PASS2_OK_MIN_CANONICAL_CHARS,
        },
    }


def _write_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


_STRUCTURAL_STATUS_PRECEDENCE = {"ok": 0, "degraded": 1, "failed": 2}


def _merge_structural_audit(
    *,
    state: _RecipeState,
    audit: StructuralAuditResult,
) -> None:
    for reason_code in audit.reason_codes:
        if reason_code not in state.structural_reason_codes:
            state.structural_reason_codes.append(reason_code)
    current_rank = _STRUCTURAL_STATUS_PRECEDENCE.get(state.structural_status, 0)
    new_rank = _STRUCTURAL_STATUS_PRECEDENCE.get(audit.status, 0)
    if new_rank > current_rank:
        state.structural_status = audit.status


def _build_pass2_input_legacy(
    *,
    state: _RecipeState,
    workbook_slug: str,
    source_hash: str,
    included_blocks: list[dict[str, Any]],
    normalization_payload: dict[str, Any],
) -> Pass2SchemaOrgInput:
    return Pass2SchemaOrgInput(
        recipe_id=state.recipe_id,
        workbook_slug=workbook_slug,
        source_hash=source_hash,
        canonical_text=state.canonical_text,
        blocks=[_to_block_lite(block) for block in included_blocks],
        normalized_evidence_text=str(
            normalization_payload.get("normalized_evidence_text") or ""
        ),
        normalized_evidence_lines=[
            str(line)
            for line in list(normalization_payload.get("normalized_evidence_lines") or [])
        ],
        normalization_stats={
            str(key): int(value)
            for key, value in dict(normalization_payload.get("stats") or {}).items()
            if isinstance(value, (int, float))
        },
    )


def _build_pass2_input_compact(
    *,
    state: _RecipeState,
    workbook_slug: str,
    source_hash: str,
    included_blocks: list[dict[str, Any]],
) -> Pass2SchemaOrgCompactInput:
    return Pass2SchemaOrgCompactInput(
        recipe_id=state.recipe_id,
        workbook_slug=workbook_slug,
        source_hash=source_hash,
        evidence_rows=[
            (int(block.get("index", 0)), str(block.get("text") or "").strip())
            for block in included_blocks
        ],
    )


def _build_pass3_input_legacy(
    *,
    state: _RecipeState,
    workbook_slug: str,
    source_hash: str,
) -> Pass3FinalDraftInput:
    assert state.pass2_output is not None
    return Pass3FinalDraftInput(
        recipe_id=state.recipe_id,
        workbook_slug=workbook_slug,
        source_hash=source_hash,
        schemaorg_recipe=state.pass2_output.schemaorg_recipe,
        extracted_ingredients=list(state.pass2_output.extracted_ingredients),
        extracted_instructions=list(state.pass2_output.extracted_instructions),
    )


def _build_pass3_recipe_metadata(schemaorg_recipe: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in dict(schemaorg_recipe).items()
        if str(key) not in {"recipeIngredient", "recipeInstructions"}
    }


def _build_pass3_input_compact(
    *,
    state: _RecipeState,
    workbook_slug: str,
    source_hash: str,
) -> Pass3FinalDraftCompactInput:
    assert state.pass2_output is not None
    return Pass3FinalDraftCompactInput(
        recipe_id=state.recipe_id,
        workbook_slug=workbook_slug,
        source_hash=source_hash,
        recipe_metadata=_build_pass3_recipe_metadata(state.pass2_output.schemaorg_recipe),
        extracted_ingredients=list(state.pass2_output.extracted_ingredients),
        extracted_instructions=list(state.pass2_output.extracted_instructions),
    )


def _uses_compact_pass2_payload(pipeline_id: str) -> bool:
    return pipeline_id == COMPACT_PASS2_PIPELINE_ID


def _uses_compact_pass3_payload(pipeline_id: str) -> bool:
    return pipeline_id == COMPACT_PASS3_PIPELINE_ID


def _resolve_pipeline_root(run_settings: RunSettings) -> Path:
    if run_settings.codex_farm_root:
        root = Path(run_settings.codex_farm_root).expanduser()
    else:
        root = Path(__file__).resolve().parents[2] / "llm_pipelines"
    required = ("pipelines", "prompts", "schemas")
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        raise CodexFarmRunnerError(
            "Invalid codex-farm pipeline root "
            f"{root}: missing {', '.join(missing)}."
        )
    return root


def _resolve_workspace_root(run_settings: RunSettings) -> Path | None:
    value = run_settings.codex_farm_workspace_root
    if not value:
        return None
    root = Path(value).expanduser()
    if not root.exists() or not root.is_dir():
        raise CodexFarmRunnerError(
            "Invalid codex-farm workspace root "
            f"{root}: path does not exist or is not a directory."
        )
    return root


def _resolve_pipeline_ids(run_settings: RunSettings) -> dict[str, str]:
    return {
        "pass1": _non_empty(
            run_settings.codex_farm_pipeline_pass1,
            fallback=DEFAULT_PASS1_PIPELINE_ID,
        ),
        "pass2": _non_empty(
            run_settings.codex_farm_pipeline_pass2,
            fallback=DEFAULT_PASS2_PIPELINE_ID,
        ),
        "pass3": _non_empty(
            run_settings.codex_farm_pipeline_pass3,
            fallback=DEFAULT_PASS3_PIPELINE_ID,
        ),
    }


def _non_empty(value: Any, *, fallback: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    return rendered or fallback


def _resolve_source_hash(result: ConversionResult) -> str:
    for artifact in result.raw_artifacts:
        if artifact.source_hash:
            return str(artifact.source_hash)
    for recipe in result.recipes:
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        source_hash = provenance.get("file_hash") or provenance.get("fileHash")
        if source_hash:
            return str(source_hash)
    return "unknown"


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _recipe_location(recipe: RecipeCandidate) -> dict[str, Any]:
    provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
    location = provenance.get("location")
    if not isinstance(location, dict):
        location = {}
        provenance["location"] = location
        recipe.provenance = provenance
    return location


def _pattern_hints_for_state(state: _RecipeState) -> list[PatternHint]:
    location = _recipe_location(state.recipe)
    start = _coerce_int(location.get("start_block"))
    if start is None:
        start = _coerce_int(location.get("startBlock"))
    end = _coerce_int(location.get("end_block"))
    if end is None:
        end = _coerce_int(location.get("endBlock"))

    hints: list[PatternHint] = []
    seen: set[tuple[str, int | None, int | None, str | None]] = set()

    raw_flags = location.get("pattern_flags")
    if isinstance(raw_flags, str):
        candidate_flags = [part.strip() for part in raw_flags.split(",")]
    elif isinstance(raw_flags, list):
        candidate_flags = [str(flag).strip() for flag in raw_flags]
    else:
        candidate_flags = []
    for flag in candidate_flags:
        if not flag:
            continue
        key = (flag, start, end, None)
        if key in seen:
            continue
        seen.add(key)
        hints.append(
            PatternHint(
                hint_type=flag,
                start_block_index=start,
                end_block_index=end,
                note="deterministic pattern detector flag",
            )
        )

    raw_actions = location.get("pattern_actions")
    if isinstance(raw_actions, list):
        for raw_action in raw_actions:
            if not isinstance(raw_action, dict):
                continue
            action_name = str(raw_action.get("action") or "").strip()
            if not action_name:
                continue
            action_start = _coerce_int(raw_action.get("original_start_block"))
            action_end = _coerce_int(raw_action.get("trimmed_start_block"))
            if action_start is None:
                action_start = start
            if action_end is None:
                action_end = end
            note = f"deterministic action: {action_name}"
            key = (action_name, action_start, action_end, note)
            if key in seen:
                continue
            seen.add(key)
            hints.append(
                PatternHint(
                    hint_type=action_name,
                    start_block_index=action_start,
                    end_block_index=action_end,
                    note=note,
                )
            )

    return hints


def _build_states(
    result: ConversionResult,
    *,
    workbook_slug: str,
) -> list[_RecipeState]:
    states: list[_RecipeState] = []
    for index, recipe in enumerate(result.recipes):
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        recipe_id = ensure_recipe_id(
            recipe.identifier or provenance.get("@id") or provenance.get("id"),
            workbook_slug=workbook_slug,
            recipe_index=index,
        )
        recipe.identifier = recipe_id
        if not isinstance(recipe.provenance, dict):
            recipe.provenance = {}
        recipe.provenance["@id"] = recipe_id
        if "id" in recipe.provenance:
            recipe.provenance["id"] = recipe_id
        location = _recipe_location(recipe)
        start_raw = (
            location.get("start_block")
            if "start_block" in location
            else location.get("startBlock")
        )
        end_raw = (
            location.get("end_block")
            if "end_block" in location
            else location.get("endBlock")
        )
        heuristic_start = _coerce_int(start_raw)
        heuristic_end = _coerce_int(end_raw)
        states.append(
            _RecipeState(
                recipe=recipe,
                recipe_id=recipe_id,
                bundle_name=bundle_filename(recipe_id, recipe_index=index),
                heuristic_start=heuristic_start,
                heuristic_end=heuristic_end,
            )
        )
    return states


def _extract_full_blocks(result: ConversionResult) -> list[dict[str, Any]]:
    by_index: dict[int, dict[str, Any]] = {}
    artifacts = sorted(
        result.raw_artifacts,
        key=lambda item: 0 if str(item.location_id) == "full_text" else 1,
    )
    for artifact in artifacts:
        content = artifact.content
        if not isinstance(content, dict):
            continue
        blocks = content.get("blocks")
        if isinstance(blocks, list) and blocks:
            candidate_rows: list[Any] = blocks
        elif str(artifact.location_id) == "full_text":
            # Older cached prediction payloads may persist line rows without
            # `full_text.blocks`; synthesize minimal blocks from line indices.
            lines = content.get("lines")
            candidate_rows = lines if isinstance(lines, list) else []
        else:
            candidate_rows = []
        for raw_block in candidate_rows:
            if not isinstance(raw_block, dict):
                continue
            index = _coerce_int(raw_block.get("index"))
            if index is None:
                continue
            if index in by_index:
                continue
            payload = dict(raw_block)
            payload["index"] = index
            payload["text"] = str(payload.get("text") or "")
            by_index[index] = payload
    return [by_index[index] for index in sorted(by_index)]


def _prepare_full_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        index = _coerce_int(block.get("index"))
        if index is None:
            continue
        payload = dict(block)
        payload["index"] = index
        block_id = payload.get("block_id") or payload.get("id")
        if not isinstance(block_id, str) or not block_id.strip():
            block_id = f"b{index}"
        payload["block_id"] = block_id.strip()
        prepared.append(payload)
    prepared.sort(key=lambda item: int(item["index"]))
    return prepared


def _to_block_lite(block: dict[str, Any]) -> BlockLite:
    features = block.get("features")
    if not isinstance(features, dict):
        features = {}
    page = _coerce_int(block.get("page"))
    spine_index = _coerce_int(block.get("spine_index"))
    if spine_index is None:
        spine_index = _coerce_int(features.get("spine_index"))
    heading_level = _coerce_int(block.get("heading_level"))
    if heading_level is None:
        heading_level = _coerce_int(features.get("heading_level"))
    return BlockLite(
        index=int(block["index"]),
        block_id=str(block.get("block_id") or f"b{int(block['index'])}"),
        text=str(block.get("text") or ""),
        page=page,
        spine_index=spine_index,
        heading_level=heading_level,
    )


def _block_lites_for_range(
    blocks_by_index: dict[int, dict[str, Any]],
    *,
    start: int | None,
    end: int | None,
    end_inclusive: bool = False,
) -> list[BlockLite]:
    start_value = _coerce_int(start)
    end_value = _coerce_int(end)
    if start_value is None or end_value is None:
        return []
    lo = min(start_value, end_value)
    hi = max(start_value, end_value)
    if end_inclusive:
        hi += 1
    result: list[BlockLite] = []
    for idx in range(lo, hi):
        block = blocks_by_index.get(idx)
        if block is None:
            continue
        result.append(_to_block_lite(block))
    return result


def _consume_pass1_outputs(
    states: list[_RecipeState],
    pass1_out_dir: Path,
    *,
    total_blocks: int,
) -> None:
    for state in states:
        out_path = pass1_out_dir / state.bundle_name
        if not out_path.exists():
            state.pass1_status = "error"
            state.errors.append("missing pass1 output bundle.")
            continue
        try:
            output = load_contract_json(out_path, Pass1RecipeChunkingOutput)
        except Exception as exc:  # noqa: BLE001
            state.pass1_status = "error"
            state.errors.append(f"invalid pass1 output: {exc}")
            continue
        if not output.is_recipe:
            state.pass1_status = "dropped"
            state.start_block_index = None
            state.end_block_index = None
            continue
        start = _coerce_int(output.start_block_index)
        end = _coerce_int(output.end_block_index)
        if start is None or end is None:
            state.pass1_status = "error"
            state.errors.append("pass1 returned null start/end for accepted recipe.")
            continue
        max_index = max(total_blocks - 1, 0)
        start = max(0, min(start, max_index))
        end = max(0, min(end, max_index))
        if end < start:
            end = start
        state.pass1_raw_start_block_index = start
        state.pass1_raw_end_block_index = end
        state.start_block_index = start
        state.end_block_index = end
        state.excluded_block_ids = {
            str(block_id)
            for block_id in output.excluded_block_ids
            if isinstance(block_id, str) and block_id.strip()
        }
        if isinstance(output.title, str) and output.title.strip():
            state.recipe.name = output.title.strip()
        state.pass1_status = "ok"


def _apply_pass1_recipe_eligibility_gate(
    states: list[_RecipeState],
    *,
    full_blocks_by_index: dict[int, dict[str, Any]],
    total_blocks: int,
) -> dict[str, Any]:
    max_index = max(total_blocks - 1, 0)
    rows: list[dict[str, Any]] = []
    counts = {"evaluated": 0, "proceed": 0, "clamp": 0, "drop": 0}
    for state in states:
        row = {"recipe_id": state.recipe_id, "pass1_status_before": state.pass1_status}
        if state.pass1_status != "ok":
            state.pass1_eligibility_status = "skipped"
            state.pass1_eligibility_action = "skip"
            row["eligibility_status"] = "skipped"
            row["eligibility_action"] = "skip"
            rows.append(row)
            continue

        included_blocks = _pass1_eligibility_blocks_for_state(
            state,
            full_blocks_by_index=full_blocks_by_index,
        )
        score_components, reasons = _pass1_eligibility_components(included_blocks)
        score = int(
            score_components["ingredient_like_score"]
            + score_components["instruction_like_score"]
            + score_components["heading_or_yield_context_score"]
            + score_components["prose_dominance_score"]
            + score_components["chapter_page_negative_score"]
        )
        if score >= 3:
            action = "proceed"
        elif score <= 0:
            action = "drop"
        else:
            action = "clamp"

        state.pass1_eligibility_status = "evaluated"
        state.pass1_eligibility_action = action
        state.pass1_eligibility_score = score
        state.pass1_eligibility_score_components = dict(score_components)
        state.pass1_eligibility_reasons = list(reasons)
        counts["evaluated"] += 1
        counts[action] += 1

        if action == "drop":
            state.pass1_status = "dropped"
            state.start_block_index = None
            state.end_block_index = None
            state.warnings.append(
                "pass1 eligibility gate dropped recipe before pass2 (low structural evidence)."
            )
        elif action == "clamp":
            target_start = (
                state.heuristic_start
                if state.heuristic_start is not None
                else state.start_block_index
            )
            target_end = (
                state.heuristic_end
                if state.heuristic_end is not None
                else state.end_block_index
            )
            if target_start is None:
                target_start = 0
            if target_end is None:
                target_end = target_start
            target_start = max(0, min(int(target_start), max_index))
            target_end = max(target_start, min(int(target_end), max_index))
            state.start_block_index = target_start
            state.end_block_index = target_end
            state.warnings.append(
                "pass1 eligibility gate clamped boundaries to heuristic range before pass2."
            )

        row.update(
            {
                "eligibility_status": state.pass1_eligibility_status,
                "eligibility_action": state.pass1_eligibility_action,
                "eligibility_score": state.pass1_eligibility_score,
                "eligibility_score_components": dict(
                    state.pass1_eligibility_score_components or {}
                ),
                "eligibility_reasons": list(state.pass1_eligibility_reasons),
                "pass1_status_after": state.pass1_status,
                "start_block_index_after": state.start_block_index,
                "end_block_index_after": state.end_block_index,
            }
        )
        rows.append(row)

    return {
        "schema_version": "pass1_recipe_eligibility.v1",
        "counts": counts,
        "rows": rows,
    }


def _pass1_eligibility_blocks_for_state(
    state: _RecipeState,
    *,
    full_blocks_by_index: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    start = state.start_block_index
    end = state.end_block_index
    if start is None or end is None:
        return []
    lo = min(int(start), int(end))
    hi = max(int(start), int(end))
    excluded = {str(block_id) for block_id in state.excluded_block_ids}
    blocks: list[dict[str, Any]] = []
    for idx in range(lo, hi + 1):
        block = full_blocks_by_index.get(idx)
        if block is None:
            continue
        block_id = str(block.get("block_id") or "")
        if block_id and block_id in excluded:
            continue
        blocks.append(dict(block))
    return blocks


def _pass1_eligibility_components(
    blocks: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    lines = [str(block.get("text") or "").strip() for block in blocks]
    lines = [line for line in lines if line]
    ingredient_hits = sum(1 for line in lines if _eligibility_looks_ingredient_line(line))
    instruction_hits = sum(1 for line in lines if _eligibility_looks_instruction_line(line))
    heading_yield_hits = sum(1 for line in lines if _eligibility_has_heading_or_yield_context(line))
    prose_hits = sum(1 for line in lines if _eligibility_looks_prose_line(line))
    line_count = len(lines)

    has_ingredient_like = ingredient_hits > 0
    has_instruction_like = instruction_hits > 0
    has_heading_or_yield_context = heading_yield_hits > 0
    chapter_page_negative_hits = sum(
        1
        for block in blocks
        if _eligibility_has_chapter_page_negative_metadata(block)
    )
    block_count = len(blocks)
    prose_dominance_high = (
        line_count > 0
        and prose_hits >= max(2, (line_count * 2) // 3)
        and ingredient_hits == 0
        and instruction_hits <= 1
    )
    chapter_page_negative_evidence_high = (
        block_count > 0
        and chapter_page_negative_hits >= max(1, (block_count + 1) // 2)
        and ingredient_hits == 0
        and instruction_hits <= 1
    )

    components = {
        "ingredient_like": has_ingredient_like,
        "instruction_like": has_instruction_like,
        "heading_or_yield_context": has_heading_or_yield_context,
        "prose_dominance_high": prose_dominance_high,
        "chapter_page_negative_evidence_high": chapter_page_negative_evidence_high,
        "ingredient_like_score": 2 if has_ingredient_like else 0,
        "instruction_like_score": 2 if has_instruction_like else 0,
        "heading_or_yield_context_score": 1 if has_heading_or_yield_context else 0,
        "prose_dominance_score": -2 if prose_dominance_high else 0,
        "chapter_page_negative_score": -2 if chapter_page_negative_evidence_high else 0,
        "line_count": line_count,
        "block_count": block_count,
        "ingredient_hits": ingredient_hits,
        "instruction_hits": instruction_hits,
        "heading_or_yield_hits": heading_yield_hits,
        "prose_hits": prose_hits,
        "chapter_page_negative_hits": chapter_page_negative_hits,
    }
    reasons: list[str] = []
    if has_ingredient_like:
        reasons.append("ingredient_like_evidence_present")
    else:
        reasons.append("ingredient_like_evidence_missing")
    if has_instruction_like:
        reasons.append("instruction_like_evidence_present")
    else:
        reasons.append("instruction_like_evidence_missing")
    if has_heading_or_yield_context:
        reasons.append("heading_or_yield_context_present")
    if prose_dominance_high:
        reasons.append("prose_dominance_high")
    if chapter_page_negative_evidence_high:
        reasons.append("chapter_page_metadata_negative_evidence_high")
    return components, reasons


def _eligibility_iter_metadata_hint_values(container: object) -> list[str]:
    if not isinstance(container, dict):
        return []
    values: list[str] = []
    for key in _ELIGIBILITY_CHAPTER_PAGE_HINT_KEYS:
        raw_value = container.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            values.append(raw_value.strip())
        elif isinstance(raw_value, (list, tuple, set)):
            for item in raw_value:
                if isinstance(item, str) and item.strip():
                    values.append(item.strip())
    for key in _ELIGIBILITY_TAG_LIST_KEYS:
        raw_value = container.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            values.append(raw_value.strip())
        elif isinstance(raw_value, (list, tuple, set)):
            for item in raw_value:
                if isinstance(item, str) and item.strip():
                    values.append(item.strip())
    return values


def _eligibility_has_chapter_page_negative_metadata(block: dict[str, Any]) -> bool:
    features = block.get("features")
    metadata = block.get("metadata")
    hint_values: list[str] = []
    hint_values.extend(_eligibility_iter_metadata_hint_values(block))
    hint_values.extend(_eligibility_iter_metadata_hint_values(features))
    hint_values.extend(_eligibility_iter_metadata_hint_values(metadata))
    for raw_value in hint_values:
        normalized = re.sub(r"[^a-z0-9]+", "_", raw_value.strip().lower()).strip("_")
        if not normalized:
            continue
        for token in _ELIGIBILITY_CHAPTER_PAGE_NEGATIVE_HINT_TOKENS:
            padded_normalized = f"_{normalized}_"
            padded_token = f"_{token}_"
            if padded_token in padded_normalized:
                return True
    return False


def _eligibility_looks_ingredient_line(text: str) -> bool:
    if _ELIGIBILITY_INSTRUCTION_VERB_RE.match(text):
        return False
    if _ELIGIBILITY_INGREDIENT_LEAD_RE.match(text):
        return True
    if _ELIGIBILITY_INGREDIENT_UNIT_RE.search(text) and re.search(r"\d", text):
        return True
    return False


def _eligibility_looks_instruction_line(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _ELIGIBILITY_TITLE_LIKE_RE.match(stripped) and "." not in stripped:
        return False
    if _ELIGIBILITY_INSTRUCTION_VERB_RE.match(stripped):
        return True
    if re.match(r"^\s*(?:step\s*)?\d+[.)]\s+", stripped, flags=re.IGNORECASE):
        return True
    return False


def _eligibility_has_heading_or_yield_context(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _ELIGIBILITY_YIELD_PREFIX_RE.match(stripped):
        return True
    return bool(_ELIGIBILITY_TITLE_LIKE_RE.match(stripped) and "." not in stripped)


def _eligibility_looks_prose_line(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'/-]*", stripped)
    if len(words) < 10:
        return False
    if _ELIGIBILITY_INSTRUCTION_VERB_RE.match(stripped):
        return False
    if _ELIGIBILITY_INGREDIENT_LEAD_RE.match(stripped):
        return False
    return "." in stripped or "," in stripped


def _apply_pass1_midpoint_clamps(states: list[_RecipeState], *, total_blocks: int) -> None:
    active = [state for state in states if state.pass1_status == "ok"]
    if not active:
        return
    active.sort(
        key=lambda state: (
            state.start_block_index
            if state.start_block_index is not None
            else (
                state.heuristic_start
                if state.heuristic_start is not None
                else 0
            )
        )
    )
    max_index = max(total_blocks - 1, 0)

    adjusted_bounds: list[list[int]] = []
    raw_bounds: list[tuple[int, int]] = []
    for state in active:
        raw_start = (
            state.start_block_index
            if state.start_block_index is not None
            else 0
        )
        raw_end = (
            state.end_block_index
            if state.end_block_index is not None
            else raw_start
        )
        clamped_start = max(0, min(int(raw_start), max_index))
        clamped_end = max(clamped_start, min(int(raw_end), max_index))
        adjusted_bounds.append([clamped_start, clamped_end])
        raw_bounds.append((clamped_start, clamped_end))

    # Resolve pairwise overlap by splitting the overlap window midpoint.
    for index in range(len(adjusted_bounds) - 1):
        current_start, current_end = adjusted_bounds[index]
        next_start, next_end = adjusted_bounds[index + 1]
        if current_end < next_start:
            continue
        overlap_start = next_start
        overlap_end = current_end
        split = (overlap_start + overlap_end) // 2
        new_current_end = max(current_start, split)
        new_next_start = min(next_end, split + 1)
        if new_next_start <= new_current_end:
            new_next_start = min(next_end, new_current_end + 1)
        if new_next_start > next_end:
            new_next_start = next_end
            if new_current_end >= new_next_start:
                new_current_end = max(current_start, new_next_start - 1)
        adjusted_bounds[index][1] = new_current_end
        adjusted_bounds[index + 1][0] = new_next_start

    for state, (adjusted_start_inclusive, adjusted_end_inclusive), (
        raw_start_inclusive,
        raw_end_inclusive,
    ) in zip(active, adjusted_bounds, raw_bounds, strict=False):
        if adjusted_end_inclusive < adjusted_start_inclusive:
            adjusted_end_inclusive = adjusted_start_inclusive
        if (
            adjusted_start_inclusive != raw_start_inclusive
            or adjusted_end_inclusive != raw_end_inclusive
        ):
            state.warnings.append(
                "pass1 boundaries clamped to resolve overlap while preserving pass1 evidence."
            )
        state.start_block_index = adjusted_start_inclusive
        state.end_block_index = adjusted_end_inclusive
        state.pass1_span_loss_metrics = _compute_span_loss_metrics(
            raw_start_block_index=state.pass1_raw_start_block_index,
            raw_end_block_index=state.pass1_raw_end_block_index,
            clamped_start_block_index=adjusted_start_inclusive,
            clamped_end_block_index=adjusted_end_inclusive,
        )


def _apply_pass1_to_result(result: ConversionResult, states: list[_RecipeState]) -> None:
    kept_states = [state for state in states if state.pass1_status != "dropped"]
    kept_states.sort(key=_state_sort_key)
    for state in kept_states:
        if state.pass1_status != "ok":
            continue
        location = _recipe_location(state.recipe)
        location["start_block"] = state.start_block_index
        location["end_block"] = state.end_block_index
        if "startBlock" in location:
            location["startBlock"] = state.start_block_index
        if "endBlock" in location:
            location["endBlock"] = state.end_block_index
    result.recipes = [state.recipe for state in kept_states]


def _state_sort_key(state: _RecipeState) -> tuple[int, int]:
    if state.start_block_index is not None:
        return (0, state.start_block_index)
    if state.heuristic_start is not None:
        return (1, state.heuristic_start)
    return (2, 0)


def _recompute_non_recipe_blocks(
    result: ConversionResult,
    *,
    states: list[_RecipeState],
    full_blocks_by_index: dict[int, dict[str, Any]],
) -> None:
    if not full_blocks_by_index:
        return
    max_index = max(full_blocks_by_index)
    mask = [False] * (max_index + 1)
    block_id_to_index = {
        str(block.get("block_id")): int(block["index"])
        for block in full_blocks_by_index.values()
        if isinstance(block.get("block_id"), str)
    }

    for state in states:
        if state.pass1_status == "dropped":
            continue
        start = state.start_block_index
        end = state.end_block_index
        if start is None or end is None:
            start = state.heuristic_start
            end = state.heuristic_end
        if start is None or end is None:
            continue
        lo = max(0, min(int(start), max_index))
        hi = max(lo, min(int(end), max_index))
        for idx in range(lo, hi + 1):
            mask[idx] = True
        for block_id in state.excluded_block_ids:
            block_index = block_id_to_index.get(block_id)
            if block_index is None:
                continue
            if 0 <= block_index < len(mask):
                mask[block_index] = False

    non_recipe_blocks: list[dict[str, Any]] = []
    for idx in range(len(mask)):
        block = full_blocks_by_index.get(idx)
        if block is None:
            continue
        if mask[idx]:
            continue
        non_recipe_blocks.append(dict(block))
    result.non_recipe_blocks = non_recipe_blocks


def _included_indices_for_state(
    state: _RecipeState,
    *,
    full_blocks_by_index: dict[int, dict[str, Any]],
) -> list[int]:
    selection = build_pass2_transport_selection(
        recipe_id=state.recipe_id,
        bundle_name=state.bundle_name,
        pass1_status=state.pass1_status,
        start_block_index=state.start_block_index,
        end_block_index=state.end_block_index,
        excluded_block_ids=sorted(state.excluded_block_ids),
        full_blocks_by_index=full_blocks_by_index,
    )
    return list(selection.effective_indices)


def _build_transport_audit(
    *,
    state: _RecipeState,
    block_indices: list[int],
    effective_block_ids: list[str],
    included_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    payload_indices = [int(block.get("index")) for block in included_blocks]
    payload_block_ids = [
        str(block.get("block_id") or f"b{int(block.get('index') or 0)}")
        for block in included_blocks
    ]
    mismatch_reasons: list[str] = []
    if payload_indices != block_indices:
        mismatch_reasons.append("effective_indices_vs_payload_indices")
    if payload_block_ids != effective_block_ids:
        mismatch_reasons.append("effective_block_ids_vs_payload_block_ids_values")
    if len(payload_indices) != len(block_indices):
        mismatch_reasons.append("effective_count_vs_payload_count")
    if len(payload_block_ids) != len(effective_block_ids):
        mismatch_reasons.append("effective_block_ids_vs_payload_block_ids")
    return {
        "recipe_id": state.recipe_id,
        "bundle_name": state.bundle_name,
        "pass1_status": state.pass1_status,
        "start_block_index": state.start_block_index,
        "end_block_index": state.end_block_index,
        "start_block_index_inclusive": state.start_block_index,
        "end_block_index_inclusive": state.end_block_index,
        "end_index_semantics": "inclusive",
        "excluded_block_ids": sorted(state.excluded_block_ids),
        "effective_indices": list(block_indices),
        "effective_block_ids": effective_block_ids,
        "payload_indices": payload_indices,
        "payload_block_ids": payload_block_ids,
        "effective_count": len(block_indices),
        "payload_count": len(payload_indices),
        "mismatch": bool(mismatch_reasons),
        "mismatch_reasons": mismatch_reasons,
    }


def _compute_span_loss_metrics(
    *,
    raw_start_block_index: int | None,
    raw_end_block_index: int | None,
    clamped_start_block_index: int | None,
    clamped_end_block_index: int | None,
) -> dict[str, Any]:
    raw_span_count = _inclusive_span_count(raw_start_block_index, raw_end_block_index)
    clamped_span_count = _inclusive_span_count(
        clamped_start_block_index,
        clamped_end_block_index,
    )
    clamped_block_loss_count = max(0, raw_span_count - clamped_span_count)
    clamped_block_loss_ratio = (
        float(clamped_block_loss_count) / float(raw_span_count)
        if raw_span_count > 0
        else 0.0
    )
    return {
        "raw_start_block_index": raw_start_block_index,
        "raw_end_block_index": raw_end_block_index,
        "raw_span_count": raw_span_count,
        "clamped_start_block_index": clamped_start_block_index,
        "clamped_end_block_index": clamped_end_block_index,
        "clamped_span_count": clamped_span_count,
        "clamped_block_loss_count": clamped_block_loss_count,
        "clamped_block_loss_ratio": round(clamped_block_loss_ratio, 6),
        "boundaries_clamped": bool(clamped_block_loss_count > 0),
    }


def _inclusive_span_count(start: int | None, end: int | None) -> int:
    if start is None or end is None:
        return 0
    lo = min(int(start), int(end))
    hi = max(int(start), int(end))
    return (hi - lo) + 1


def _recipe_scoped_failure_mode_note(*, mode: str, reason: str) -> str:
    if mode == "fallback":
        return f"{reason}: recipe-level fallback engaged; deterministic writer path remains active."
    return f"{reason}: recorded as recipe-level error; run-level fail mode remains strict."


def _normalize_for_match(value: str) -> str:
    return " ".join(value.casefold().split())


_PLACEHOLDER_STEP_TEXTS = {
    _normalize_for_match("See original recipe for details."),
}
_PASS2_DEGRADING_WARNING_BUCKETS = {
    "missing_instructions",
    "split_line_boundary",
    "ingredient_fragment",
    "page_or_layout_artifact",
}
_PASS2_SOFT_DEGRADATION_REASONS = {
    "warning_bucket:page_or_layout_artifact",
}
_STRUCTURAL_REASON_MESSAGES = {
    "empty_mapping_without_reason": "ingredient_step_mapping empty without a declared reason.",
    "extractive_text_not_in_transport_span": (
        "pass2 extractive text does not match the transported source span."
    ),
    "missing_instructions": "pass2 missing instruction evidence.",
    "missing_steps": "draft_v1 has no non-empty step instructions.",
    "placeholder_instructions_only": "pass2 instructions are placeholder-only.",
    "placeholder_steps_only": "draft_v1 step instructions are placeholder-only.",
    "placeholder_title": "recipe title is still a placeholder.",
    "step_matches_schema_description": (
        "step instruction matches schema description/headnote text."
    ),
    "upstream_missing_instruction_evidence": (
        "pass2 degraded due to missing instruction evidence."
    ),
}


def _normalized_nonempty_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = _normalize_for_match(str(value))
        if normalized:
            result.append(normalized)
    return result


def _render_structural_reason_messages(reason_codes: list[str]) -> list[str]:
    messages: list[str] = []
    for reason_code in reason_codes:
        rendered = str(reason_code or "").strip()
        if not rendered:
            continue
        messages.append(_STRUCTURAL_REASON_MESSAGES.get(rendered, rendered.replace("_", " ")))
    return messages


def _is_placeholder_instruction(value: str) -> bool:
    normalized = _normalize_for_match(value)
    if not normalized:
        return True
    return normalized in _PLACEHOLDER_STEP_TEXTS


def _pass2_warning_bucket(text: str) -> str | None:
    lowered = _normalize_for_match(text).replace(" ", "_")
    if not lowered:
        return None
    if "missing_instruction" in lowered:
        return "missing_instructions"
    if "split_line_boundary" in lowered or "split_line" in lowered:
        return "split_line_boundary"
    if "ingredient_fragment" in lowered:
        return "ingredient_fragment"
    if (
        "ocr" in lowered
        or "page_artifact" in lowered
        or "page_marker" in lowered
    ):
        return "page_or_layout_artifact"
    return None


def _validate_pass2_guardrails(
    *,
    output: Pass2SchemaOrgOutput,
    canonical_text: str,
) -> list[str]:
    warnings: list[str] = []
    canonical = _normalize_for_match(canonical_text)
    for index, ingredient in enumerate(output.extracted_ingredients):
        target = _normalize_for_match(str(ingredient))
        if target and target not in canonical:
            warnings.append(
                f"pass2 ingredient[{index}] not found in canonical_text: {ingredient!r}"
            )
    for index, instruction in enumerate(output.extracted_instructions):
        target = _normalize_for_match(str(instruction))
        if target and target not in canonical:
            warnings.append(
                f"pass2 instruction[{index}] not found in canonical_text: {instruction!r}"
            )
    return warnings


def _pass2_degradation_reasons(
    *,
    output: Pass2SchemaOrgOutput,
    guard_warnings: list[str],
) -> list[str]:
    reasons: list[str] = []
    normalized_instructions = _normalized_nonempty_texts(output.extracted_instructions)
    non_placeholder_instructions = [
        text for text in normalized_instructions if not _is_placeholder_instruction(text)
    ]

    if not normalized_instructions:
        reasons.append("missing_instructions")
    elif not non_placeholder_instructions:
        reasons.append("placeholder_instructions_only")

    warning_buckets = {
        bucket
        for warning in [*output.warnings, *guard_warnings]
        if isinstance(warning, str)
        for bucket in [_pass2_warning_bucket(warning)]
        if bucket is not None
    }
    for bucket in sorted(warning_buckets):
        if bucket in _PASS2_DEGRADING_WARNING_BUCKETS:
            reasons.append(f"warning_bucket:{bucket}")
    return reasons


def _pass2_degradation_severity(reasons: list[str]) -> str:
    normalized = [str(reason).strip() for reason in reasons if str(reason).strip()]
    if not normalized:
        return "none"
    if all(reason in _PASS2_SOFT_DEGRADATION_REASONS for reason in normalized):
        return "soft"
    return "hard"


def _has_non_placeholder_pass2_instructions(output: Pass2SchemaOrgOutput) -> bool:
    for instruction in output.extracted_instructions:
        text = str(instruction).strip()
        if text and not _is_placeholder_instruction(text):
            return True
    return False


def _is_soft_degradation_low_risk_for_deterministic(
    output: Pass2SchemaOrgOutput,
) -> bool:
    if not _has_non_placeholder_pass2_instructions(output):
        return False
    ingredient_count = sum(
        1 for item in output.extracted_ingredients if str(item).strip()
    )
    if ingredient_count > 0:
        return True
    schema_name = str(output.schemaorg_recipe.get("name") or "").strip()
    return bool(schema_name)


def _build_pass3_utility_signal_for_pass2_ok(
    *,
    output: Pass2SchemaOrgOutput,
    canonical_text: str,
) -> dict[str, Any]:
    normalized_instructions = _normalized_nonempty_texts(output.extracted_instructions)
    non_placeholder_instruction_count = sum(
        1 for text in normalized_instructions if not _is_placeholder_instruction(text)
    )
    ingredient_count = sum(1 for item in output.extracted_ingredients if str(item).strip())
    schema_name = str(output.schemaorg_recipe.get("name") or "").strip()
    warning_count = sum(1 for warning in output.warnings if str(warning).strip())
    canonical_char_count = len(str(canonical_text).strip())

    risk_reasons: list[str] = []
    if non_placeholder_instruction_count < _PASS3_PASS2_OK_MIN_NON_PLACEHOLDER_INSTRUCTIONS:
        risk_reasons.append(
            "insufficient_non_placeholder_instructions"
        )
    if ingredient_count <= 0:
        risk_reasons.append("missing_ingredient_evidence")
    if not schema_name:
        risk_reasons.append("missing_schemaorg_name")
    if warning_count > 0:
        risk_reasons.append("pass2_warnings_present")
    if canonical_char_count < _PASS3_PASS2_OK_MIN_CANONICAL_CHARS:
        risk_reasons.append("short_canonical_text")

    return {
        "status": "pass2_ok",
        "instruction_count": len(normalized_instructions),
        "non_placeholder_instruction_count": non_placeholder_instruction_count,
        "ingredient_count": ingredient_count,
        "schema_name_present": bool(schema_name),
        "warning_count": warning_count,
        "canonical_char_count": canonical_char_count,
        "deterministic_low_risk": len(risk_reasons) == 0,
        "risk_reasons": risk_reasons,
    }


def _should_run_pass3_llm(
    *,
    state: _RecipeState,
    pass3_skip_pass2_ok_enabled: bool,
) -> tuple[bool, str]:
    if state.pass2_output is None:
        return False, "pass2_output_missing"
    if state.pass2_status == "ok":
        if state.pass3_utility_signal is None:
            state.pass3_utility_signal = _build_pass3_utility_signal_for_pass2_ok(
                output=state.pass2_output,
                canonical_text=state.canonical_text,
            )
        if pass3_skip_pass2_ok_enabled and bool(
            state.pass3_utility_signal.get("deterministic_low_risk")
        ):
            return False, "pass2_ok_high_confidence_deterministic"
        if pass3_skip_pass2_ok_enabled:
            return True, "pass2_ok_requires_llm"
        return True, "pass2_ok"
    if state.pass2_status != "degraded":
        return False, "pass2_not_eligible"
    severity = state.pass2_degradation_severity or _pass2_degradation_severity(
        state.pass2_degradation_reasons
    )
    if severity == "hard":
        return False, "pass2_hard_degradation"
    if _is_soft_degradation_low_risk_for_deterministic(state.pass2_output):
        return False, "pass2_soft_degradation_low_risk"
    return True, "pass2_soft_degradation_needs_llm"


def _pass3_low_quality_reasons(
    *,
    draft_payload: dict[str, Any],
    pass2_output: Pass2SchemaOrgOutput | None,
    ingredient_step_mapping: dict[str, Any] | None,
    pass2_degradation_reasons: list[str] | None = None,
) -> list[str]:
    if pass2_output is None:
        return []

    low_quality_reasons: list[str] = []
    pass2_degradation_reasons = pass2_degradation_reasons or []
    if any(
        reason in {"missing_instructions", "placeholder_instructions_only"}
        for reason in pass2_degradation_reasons
    ):
        low_quality_reasons.append("pass2 degraded due to missing instruction evidence.")

    blocked_snippets: set[str] = set()

    description = pass2_output.schemaorg_recipe.get("description")
    if isinstance(description, str):
        normalized = _normalize_for_match(description)
        if len(normalized) >= 20:
            blocked_snippets.add(normalized)

    comment_payload = pass2_output.schemaorg_recipe.get("comment")
    if isinstance(comment_payload, str):
        normalized = _normalize_for_match(comment_payload)
        if len(normalized) >= 20:
            blocked_snippets.add(normalized)
    elif isinstance(comment_payload, list):
        for item in comment_payload:
            if isinstance(item, str):
                normalized = _normalize_for_match(item)
            elif isinstance(item, dict):
                normalized = _normalize_for_match(str(item.get("text") or ""))
            else:
                normalized = ""
            if len(normalized) >= 20:
                blocked_snippets.add(normalized)

    extracted_instruction_set = {
        _normalize_for_match(str(item))
        for item in pass2_output.extracted_instructions
        if _normalize_for_match(str(item))
    }

    steps = draft_payload.get("steps")
    if not isinstance(steps, list):
        low_quality_reasons.append("draft_v1.steps missing or invalid.")
        return low_quality_reasons

    rendered_steps: list[str] = []
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        raw_instruction = str(step.get("instruction") or "")
        instruction = _normalize_for_match(raw_instruction)
        if not instruction:
            continue
        rendered_steps.append(raw_instruction)
        for blocked in blocked_snippets:
            if blocked == instruction or blocked in instruction or instruction in blocked:
                if instruction not in extracted_instruction_set:
                    low_quality_reasons.append(
                        f"step[{idx}] instruction matches schema description/headnote text."
                    )
                    break

    if not rendered_steps:
        low_quality_reasons.append("draft_v1 has no non-empty step instructions.")
    elif all(_is_placeholder_instruction(step) for step in rendered_steps):
        low_quality_reasons.append("draft_v1 step instructions are placeholder-only.")

    mapping_payload = (
        ingredient_step_mapping if isinstance(ingredient_step_mapping, dict) else {}
    )
    if not mapping_payload:
        has_step_evidence = bool(rendered_steps)
        pass2_instruction_evidence = _normalized_nonempty_texts(
            pass2_output.extracted_instructions
        )
        has_instruction_evidence = bool(pass2_instruction_evidence)
        if (not has_step_evidence) or (not has_instruction_evidence):
            low_quality_reasons.append(
                "ingredient_step_mapping empty while step/instruction evidence is missing."
            )

    return low_quality_reasons


def _repair_placeholder_only_steps_from_pass2(
    *,
    draft_payload: dict[str, Any],
    pass2_output: Pass2SchemaOrgOutput | None,
) -> bool:
    if pass2_output is None:
        return False
    steps = draft_payload.get("steps")
    if not isinstance(steps, list) or not steps:
        return False

    rendered_steps: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        instruction = str(step.get("instruction") or "").strip()
        if instruction:
            rendered_steps.append(instruction)
    if not rendered_steps:
        return False
    if not all(_is_placeholder_instruction(text) for text in rendered_steps):
        return False

    replacement_instructions = [
        str(text).strip()
        for text in pass2_output.extracted_instructions
        if str(text).strip() and not _is_placeholder_instruction(str(text))
    ]
    if not replacement_instructions:
        return False

    repaired_steps: list[dict[str, Any]] = []
    for index, instruction in enumerate(replacement_instructions):
        ingredient_lines: list[Any] = []
        if index < len(steps) and isinstance(steps[index], dict):
            existing_lines = steps[index].get("ingredient_lines")
            if isinstance(existing_lines, list):
                ingredient_lines = list(existing_lines)
        repaired_steps.append(
            {
                "instruction": instruction,
                "ingredient_lines": ingredient_lines,
            }
        )
    draft_payload["steps"] = repaired_steps
    return True


def _build_pass3_deterministic_fallback_payload(
    *,
    state: _RecipeState,
) -> dict[str, Any] | None:
    fallback_candidate = state.recipe.model_copy(deep=True)
    fallback_candidate.identifier = state.recipe_id
    fallback_candidate.provenance = dict(state.recipe.provenance or {})
    fallback_candidate.provenance["@id"] = state.recipe_id

    pass2_output = state.pass2_output
    if pass2_output is not None:
        if pass2_output.extracted_ingredients:
            candidate_ingredients = [
                str(item).strip() for item in pass2_output.extracted_ingredients if str(item).strip()
            ]
            if candidate_ingredients:
                fallback_candidate.ingredients = candidate_ingredients
        candidate_instructions = [
            str(item).strip()
            for item in pass2_output.extracted_instructions
            if str(item).strip()
        ]
        if candidate_instructions and not all(
            _is_placeholder_instruction(item) for item in candidate_instructions
        ):
            fallback_candidate.instructions = candidate_instructions
        if not fallback_candidate.name:
            schema_name = str(pass2_output.schemaorg_recipe.get("name") or "").strip()
            if schema_name:
                fallback_candidate.name = schema_name

    run_config = RunSettings().to_run_config_dict()
    payload = recipe_candidate_to_draft_v1(
        fallback_candidate,
        ingredient_parser_options=run_config,
        instruction_step_options=run_config,
    )
    payload = _normalize_draft_payload(dict(payload))
    _patch_recipe_id(payload, recipe_id=state.recipe_id)
    return payload


def _as_nonempty_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _coerce_schema_version(value: Any) -> int:
    if isinstance(value, int):
        return value if value > 0 else 1
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.isdigit():
            parsed = int(cleaned)
            return parsed if parsed > 0 else 1
    return 1


def _extract_instruction_text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, dict):
        for key in ("instruction", "text"):
            candidate = _as_nonempty_text(value.get(key))
            if candidate:
                return candidate
    return None


def _normalize_draft_steps_from_payload(steps_payload: Any) -> list[dict[str, Any]]:
    normalized_steps: list[dict[str, Any]] = []
    if not isinstance(steps_payload, list):
        return normalized_steps
    for step in steps_payload:
        if isinstance(step, dict):
            instruction = _extract_instruction_text(step)
            if not instruction:
                continue
            ingredient_lines = step.get("ingredient_lines")
            if not isinstance(ingredient_lines, list):
                ingredient_lines = []
            normalized_steps.append(
                {
                    **step,
                    "instruction": instruction,
                    "ingredient_lines": ingredient_lines,
                }
            )
            continue
        instruction = _extract_instruction_text(step)
        if instruction:
            normalized_steps.append(
                {
                    "instruction": instruction,
                    "ingredient_lines": [],
                }
            )
    return normalized_steps


def _instruction_texts_from_payload(value: Any) -> list[str]:
    if isinstance(value, list):
        return [instruction for instruction in (_extract_instruction_text(item) for item in value) if instruction]
    instruction = _extract_instruction_text(value)
    return [instruction] if instruction else []


def _instruction_texts_from_draft_payload(payload: dict[str, Any]) -> list[str]:
    instructions: list[str] = []
    seen: set[str] = set()
    candidates: list[Any] = [
        payload.get("instructions"),
        payload.get("recipeInstructions"),
        payload.get("extracted_instructions"),
    ]
    schemaorg_payload = payload.get("schemaorg_recipe")
    if isinstance(schemaorg_payload, dict):
        candidates.append(schemaorg_payload.get("recipeInstructions"))
    for candidate in candidates:
        for instruction in _instruction_texts_from_payload(candidate):
            if instruction in seen:
                continue
            seen.add(instruction)
            instructions.append(instruction)
    return instructions


def _draft_title_from_payload(payload: dict[str, Any], recipe_payload: dict[str, Any]) -> str:
    title_candidates = [
        recipe_payload.get("title"),
        recipe_payload.get("name"),
        payload.get("title"),
        payload.get("name"),
    ]
    schemaorg_payload = payload.get("schemaorg_recipe")
    if isinstance(schemaorg_payload, dict):
        title_candidates.append(schemaorg_payload.get("name"))
    for candidate in title_candidates:
        rendered = _as_nonempty_text(candidate)
        if rendered:
            return rendered
    return "Untitled Recipe"


def _normalize_draft_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["schema_v"] = _coerce_schema_version(normalized.get("schema_v"))

    source = normalized.get("source")
    if isinstance(source, str):
        source = source.strip() or None
    else:
        source = None if source is None else str(source)
    normalized["source"] = source

    recipe_payload = normalized.get("recipe")
    if not isinstance(recipe_payload, dict):
        recipe_payload = {}
    recipe_payload["title"] = _draft_title_from_payload(normalized, recipe_payload)
    normalized["recipe"] = recipe_payload

    normalized_steps = _normalize_draft_steps_from_payload(normalized.get("steps"))
    if not normalized_steps:
        normalized_steps = [
            {
                "instruction": instruction,
                "ingredient_lines": [],
            }
            for instruction in _instruction_texts_from_draft_payload(normalized)
        ]
    if not normalized_steps:
        normalized_steps = [
            {
                "instruction": "See original recipe for details.",
                "ingredient_lines": [],
            }
        ]
    normalized["steps"] = normalized_steps
    return normalized


def _patch_recipe_id(payload: dict[str, Any], *, recipe_id: str) -> bool:
    patched = False
    existing = payload.get("id")
    if isinstance(existing, str) and existing.strip() and existing.strip() != recipe_id:
        payload["id"] = recipe_id
        patched = True

    recipe_payload = payload.get("recipe")
    if isinstance(recipe_payload, dict):
        recipe_id_value = recipe_payload.get("id")
        if (
            isinstance(recipe_id_value, str)
            and recipe_id_value.strip()
            and recipe_id_value.strip() != recipe_id
        ):
            recipe_payload["id"] = recipe_id
            patched = True
    return patched
