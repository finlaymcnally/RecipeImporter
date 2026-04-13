from __future__ import annotations

import json
import statistics
import threading
import cookimport.parsing.canonical_line_roles as canonical_line_roles_module
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cookimport.config.run_settings import (
    CODEX_EXEC_STYLE_INLINE_JSON_V1,
    LINE_ROLE_PIPELINE_ROUTE_V2,
    RunSettings,
    resolve_codex_exec_style_value,
)
from cookimport.core.progress_messages import format_stage_progress
from cookimport.llm.codex_exec_runner import (
    CodexExecLiveSnapshot,
    CodexExecRunResult,
    CodexExecRunner,
    CodexExecSupervisionDecision,
    DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
    SubprocessCodexExecRunner,
    WorkspaceCommandClassification,
    _summarize_live_codex_events,
    classify_taskfile_worker_command,
    detect_taskfile_worker_boundary_violation,
    format_watchdog_command_loop_reason_detail,
    format_watchdog_command_reason_detail,
    is_single_file_workspace_command_drift_policy,
    should_terminate_workspace_command_loop,
)
from cookimport.llm.codex_farm_runner import (
    CodexFarmRunnerError,
    resolve_codex_farm_output_schema_path,
)
from cookimport.llm.phase_plan import (
    attach_survivability_to_phase_plan,
    build_phase_plan,
    write_phase_plan_artifacts,
)
from cookimport.llm.editable_task_file import (
    TASK_FILE_NAME,
    build_task_file,
    load_task_file,
    validate_edited_task_file,
    write_task_file,
)
from cookimport.llm.single_file_worker_commands import build_single_file_worker_surface
from cookimport.llm.structured_session_runtime import (
    assert_structured_session_can_resume,
    initialize_structured_session_lineage,
    record_structured_session_turn,
)
from cookimport.llm.task_file_guardrails import (
    build_task_file_guardrail,
    build_worker_session_guardrails,
    summarize_task_file_guardrails,
)
from cookimport.llm.taskfile_progress import (
    decorate_active_worker_label,
    start_taskfile_progress_heartbeat,
    summarize_taskfile_health,
)
from cookimport.llm.shard_survivability import (
    ShardSurvivabilityPreflightError,
    attach_observed_telemetry_to_survivability_report,
    count_structural_output_tokens,
    count_tokens_for_model,
    evaluate_stage_survivability,
)
from cookimport.llm.phase_worker_runtime import (
    PhaseManifestV1,
    ShardManifestEntryV1,
    ShardProposalV1,
    WorkerAssignmentV1,
    WorkerExecutionReportV1,
    resolve_phase_worker_count,
)
from cookimport.llm.repair_recovery_policy import (
    FOLLOWUP_KIND_FRESH_SESSION_RETRY,
    FOLLOWUP_KIND_FRESH_WORKER_REPLACEMENT,
    FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE,
    FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP,
    FOLLOWUP_KIND_WATCHDOG_RETRY,
    INLINE_JSON_TRANSPORT,
    LINE_ROLE_POLICY_STAGE_KEY,
    TASKFILE_TRANSPORT,
    build_followup_budget_summary,
    inline_repair_policy_summary,
    structured_repair_followup_limit,
    taskfile_recovery_policy_summary,
)
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate
from . import (
    CANONICAL_LINE_ROLE_ALLOWED_LABELS,
    CanonicalLineRolePrediction,
    LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT,
    LineRoleRepairFailureError,
    _CODEX_EXECUTABLES,
    _DirectLineRoleWorkerResult,
    _EXPLICIT_KNOWLEDGE_CUE_RE,
    _INSTRUCTION_VERB_RE,
    _LINE_ROLE_COHORT_WATCHDOG_MAX_EXAMPLES,
    _LINE_ROLE_COHORT_WATCHDOG_MIN_COMPLETED_SHARDS,
    _LINE_ROLE_CODEX_FARM_PIPELINE_ID,
    _LINE_ROLE_MODEL_PAYLOAD_VERSION,
    _LINE_ROLE_PROGRESS_MAX_UPDATES,
    _LineRolePhaseRuntimeResult,
    _LineRoleRuntimeResult,
    _LineRoleShardPlan,
    _PROSE_WORD_RE,
    _PromptArtifactState,
    _STRICT_JSON_WATCHDOG_POLICY,
    _YIELD_COUNT_HINT_RE,
    _YIELD_PREFIX_RE,
    _annotate_line_role_final_outcome_row,
    _annotate_line_role_final_proposal_status,
    _apply_line_role_final_outcome_to_runner_payload,
    _apply_prediction_decision_metadata,
    _apply_repo_baseline_semantic_policy,
    _build_line_role_canonical_line_table_rows,
    _build_line_role_canonical_plans,
    _build_line_role_row_resolution,
    _build_line_role_shard_status_row,
    _build_line_role_taskfile_prompt,
    _build_line_role_worker_shard_row,
    _coerce_mapping_dict,
    _deterministic_label,
    _distribute_line_role_session_value,
    _evaluate_line_role_response,
    _evaluate_line_role_response_with_pathology_guard,
    _fallback_prediction,
    _find_line_role_existing_output_path,
    _is_outside_recipe_span,
    _line_role_asdict,
    _line_role_pipeline_name,
    _line_role_usage_present,
    _load_cached_predictions,
    _looks_editorial_note,
    _looks_recipe_note_prose,
    _normalize_line_role_shard_outcome,
    _normalize_prediction_metadata,
    _relative_runtime_path,
    _render_codex_events_jsonl,
    _render_line_role_authoritative_rows,
    _resolve_line_role_cache_path,
    _resolve_line_role_codex_exec_cmd,
    _resolve_line_role_codex_farm_model,
    _resolve_line_role_codex_farm_reasoning_effort,
    _resolve_line_role_codex_farm_root,
    _resolve_line_role_requested_shard_count,
    _resolve_line_role_worker_count,
    _sum_runtime_usage,
    _summarize_direct_rows,
    _validate_line_role_shard_proposal,
    _write_cached_predictions,
    _write_line_role_worker_hint,
    _write_optional_runtime_text,
    _write_runtime_json,
    _write_runtime_jsonl,
    _write_worker_debug_input,
    build_canonical_line_role_file_prompt,
    build_line_role_shared_contract_block,
    build_line_role_workspace_scaffold,
)
from .same_session_handoff import (
    LINE_ROLE_SAME_SESSION_STATE_ENV,
    describe_line_role_same_session_doctor,
    describe_line_role_same_session_status,
    initialize_line_role_same_session_state,
)


from .runtime_recovery import (
    _LineRoleRecoveryAssessment,
    _assess_line_role_workspace_recovery,
    _build_line_role_final_message_recovery_prompt,
    _build_line_role_fresh_worker_replacement_prompt,
    _build_line_role_runner_exception_result,
    _failure_reason_from_run_result,
    _finalize_live_status,
    _format_utc_now,
    _line_role_assessment_proves_authoritative_completion,
    _line_role_catastrophic_run_result_reason,
    _line_role_completed_same_session_helper_command,
    _line_role_hard_boundary_failure,
    _line_role_recovery_guidance_for_diagnosis,
    _line_role_retryable_runner_exception_reason,
    _line_role_same_session_helper_completed_in_events,
    _line_role_same_session_helper_completion_from_snapshot,
    _line_role_same_session_helper_command_completed,
    _line_role_same_session_state_path,
    _line_role_task_file_useful_progress,
    _load_json_dict_safely,
    _load_json_dict_with_error,
    _load_live_status,
    _normalize_line_role_run_result_after_final_sync,
    _override_line_role_missing_output_with_authoritative_completion,
    _reset_line_role_workspace_for_fresh_worker_replacement,
    _should_attempt_line_role_final_message_recovery,
    _should_attempt_line_role_fresh_session_retry,
    _should_attempt_line_role_fresh_worker_replacement,
    _summarize_line_role_same_session_completion,
    _summarize_workspace_output_paths,
)
from .runtime_taskfile import (
    _build_line_role_task_file,
    _expand_line_role_task_file_outputs,
    _line_role_incomplete_progress_summary_detail,
    _raise_if_line_role_runtime_incomplete,
)
from .runtime_watchdog import (
    _build_line_role_inline_attempt_runner_payload as _build_line_role_inline_attempt_runner_payload_impl,
    _build_line_role_watchdog_example as _build_line_role_watchdog_example_impl,
    _build_line_role_watchdog_retry_prompt as _build_line_role_watchdog_retry_prompt_impl,
    _build_preflight_rejected_run_result as _build_preflight_rejected_run_result_impl,
    _build_strict_json_watchdog_callback as _build_strict_json_watchdog_callback_impl,
    _classify_line_role_workspace_command as _classify_line_role_workspace_command_impl,
    _line_role_resume_reason_fields as _line_role_resume_reason_fields_impl,
    _preflight_line_role_shard as _preflight_line_role_shard_impl,
    _run_line_role_watchdog_retry_attempt as _run_line_role_watchdog_retry_attempt_impl,
    _should_attempt_line_role_repair as _should_attempt_line_role_repair_impl,
    _should_attempt_line_role_watchdog_retry as _should_attempt_line_role_watchdog_retry_impl,
)


def _runtime_override(name: str, default: Any) -> Any:
    return getattr(canonical_line_roles_module, name, default)


def _build_line_role_shard_survivability_report(
    *,
    shard_plans: Sequence[_LineRoleShardPlan],
    requested_shard_count: int | None,
    model_name: str | None,
) -> dict[str, Any]:
    resolved_model_name = str(model_name or "").strip()
    shard_estimates: list[dict[str, Any]] = []
    for shard_plan in shard_plans:
        input_payload = (
            dict(shard_plan.manifest_entry.input_payload)
            if isinstance(shard_plan.manifest_entry.input_payload, Mapping)
            else {}
        )
        prompt_path = Path("in") / f"{shard_plan.shard_id}.json"
        prompt_text = build_canonical_line_role_file_prompt(
            input_path=prompt_path,
            input_payload=input_payload,
        )
        shard_estimates.append(
            {
                "shard_id": shard_plan.shard_id,
                "owned_unit_count": len(shard_plan.candidates),
                "estimated_input_tokens": count_tokens_for_model(
                    prompt_text,
                    model_name=resolved_model_name,
                ),
                "estimated_output_tokens": count_structural_output_tokens(
                    pipeline_id=shard_plan.runtime_pipeline_id,
                    input_payload=input_payload,
                    model_name=resolved_model_name,
                ),
                "metadata": {
                    "owned_ids": list(shard_plan.manifest_entry.owned_ids),
                },
            }
        )
    return evaluate_stage_survivability(
        stage_key="line_role",
        shard_estimates=shard_estimates,
        requested_shard_count=requested_shard_count or len(shard_plans),
        stage_label_override="Canonical Line Role",
    )


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


def _line_role_partial_authority_rows(
    proposal_metadata: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    accepted_rows = [
        dict(row)
        for row in (proposal_metadata or {}).get("accepted_rows", [])
        if isinstance(row, Mapping)
    ]
    return accepted_rows


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
        completed_units=0,
        total_units=deterministic_total,
        work_unit_label="row",
    )
    by_atomic_index = {int(candidate.atomic_index): candidate for candidate in ordered}
    mode = _line_role_pipeline_name(settings)
    cache_path: Path | None = None
    if mode == LINE_ROLE_PIPELINE_ROUTE_V2:
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
                row_id=candidate.row_id,
                block_id=str(candidate.block_id),
                block_index=int(candidate.block_index),
                atomic_index=int(candidate.atomic_index),
                row_ordinal=int(candidate.row_ordinal),
                start_char_in_block=int(candidate.start_char_in_block),
                end_char_in_block=int(candidate.end_char_in_block),
                text=str(candidate.text),
                within_recipe_span=candidate.within_recipe_span,
                label=label,
                decided_by="rule",
                reason_tags=tags,
            )
        baseline_prediction = _apply_repo_baseline_semantic_policy(
            prediction=baseline_prediction,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
        baseline_prediction = _normalize_prediction_metadata(
            prediction=baseline_prediction,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
        baseline_prediction = _apply_prediction_decision_metadata(
            prediction=baseline_prediction,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
        deterministic_baseline[candidate.atomic_index] = baseline_prediction
        if mode != LINE_ROLE_PIPELINE_ROUTE_V2:
            predictions[candidate.atomic_index] = baseline_prediction
        if (
            candidate_index == deterministic_total
            or candidate_index % deterministic_interval == 0
        ):
            _notify_line_role_progress(
                progress_callback=progress_callback,
                completed_units=candidate_index,
                total_units=deterministic_total,
                work_unit_label="row",
            )

    codex_targets = ordered if mode == LINE_ROLE_PIPELINE_ROUTE_V2 else []
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
        _write_line_role_telemetry_summary(
            artifact_root=artifact_root,
            runtime_result=runtime_result,
        )
        if live_llm_allowed:
            _raise_if_line_role_runtime_incomplete(
                ordered_candidates=ordered,
                runtime_result=runtime_result,
                predictions_by_atomic_index=predictions,
            )
        else:
            for candidate in ordered:
                if candidate.atomic_index not in predictions:
                    predictions[candidate.atomic_index] = deterministic_baseline[
                        candidate.atomic_index
                    ]
    else:
        for candidate in ordered:
            if candidate.atomic_index not in predictions:
                predictions[candidate.atomic_index] = deterministic_baseline[
                    candidate.atomic_index
                ]

    sanitized_by_index: dict[int, CanonicalLineRolePrediction] = {}
    for candidate in ordered:
        current = predictions[candidate.atomic_index]
        current = _normalize_prediction_metadata(
            prediction=current,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
        current = _apply_prediction_decision_metadata(
            prediction=current,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
        sanitized_by_index[candidate.atomic_index] = current
    sanitized = [sanitized_by_index[candidate.atomic_index] for candidate in ordered]
    sanitized_baseline = [
        deterministic_baseline[candidate.atomic_index] for candidate in ordered
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
    codex_farm_workspace_root = _runtime_override(
        "_resolve_line_role_codex_farm_workspace_root",
        canonical_line_roles_module._resolve_line_role_codex_farm_workspace_root,
    )(settings=settings)
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
    survivability_report = _runtime_override(
        "_build_line_role_shard_survivability_report",
        canonical_line_roles_module._build_line_role_shard_survivability_report,
    )(
        shard_plans=shard_plans,
        requested_shard_count=getattr(settings, "line_role_prompt_target_count", None),
        model_name=codex_farm_model,
    )
    (runtime_root / "line_role").mkdir(parents=True, exist_ok=True)
    _write_runtime_json(
        runtime_root / "line_role" / "shard_survivability_report.json",
        survivability_report,
    )
    if str(survivability_report.get("survivability_verdict") or "") != "safe":
        raise ShardSurvivabilityPreflightError(survivability_report)
    worker_count = _resolve_line_role_worker_count(
        settings=settings,
        codex_max_inflight=codex_max_inflight,
        shard_count=len(shard_plans),
    )
    requested_shard_count = getattr(settings, "line_role_prompt_target_count", None)
    budget_native_shard_count = len(shard_plans) or 1
    phase_plan = build_phase_plan(
        stage_key="line_role",
        stage_label=shard_plans[0].phase_label,
        stage_order=2,
        surface_pipeline=LINE_ROLE_PIPELINE_ROUTE_V2,
        runtime_pipeline_id=shard_plans[0].runtime_pipeline_id,
        worker_count=worker_count,
        requested_shard_count=(
            int(requested_shard_count) if requested_shard_count is not None else len(shard_plans)
        ),
        budget_native_shard_count=budget_native_shard_count,
        launch_shard_count=len(shard_plans),
        planning_warnings=list(survivability_report.get("warnings") or []),
        shard_specs=[
            {
                "shard_id": shard_plan.shard_id,
                "owned_ids": [str(candidate.atomic_index) for candidate in shard_plan.candidates],
                "call_ids": [shard_plan.shard_id],
                "prompt_chars": len(
                    build_canonical_line_role_file_prompt(
                        input_path=Path("in") / f"{shard_plan.shard_id}.json",
                        input_payload=(
                            dict(shard_plan.manifest_entry.input_payload)
                            if isinstance(shard_plan.manifest_entry.input_payload, Mapping)
                            else {}
                        ),
                    )
                ),
                "task_prompt_chars": len(
                    json.dumps(
                        (
                            dict(shard_plan.manifest_entry.input_payload)
                            if isinstance(shard_plan.manifest_entry.input_payload, Mapping)
                            else {}
                        ),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                ),
                "work_unit_count": len(shard_plan.candidates),
                "work_unit_label": "lines",
            }
            for shard_plan in shard_plans
        ],
    )
    phase_plan = attach_survivability_to_phase_plan(
        phase_plan=phase_plan,
        survivability_report=survivability_report,
    )
    phase_plan_path, phase_plan_summary_path = write_phase_plan_artifacts(
        stage_dir=runtime_root / "line_role",
        phase_plan=phase_plan,
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
        runtime_metadata={
            "requested_shard_count": (
                int(requested_shard_count) if requested_shard_count is not None else len(shard_plans)
            ),
            "budget_native_shard_count": budget_native_shard_count,
            "phase_plan_path": str(phase_plan_path),
            "phase_plan_summary_path": str(phase_plan_summary_path),
        },
        progress_callback=progress_callback,
        validator=_validate_line_role_shard_proposal,
    )
    telemetry_rows: list[Mapping[str, Any]] = []
    for report in phase_result.worker_reports:
        runner_result = report.runner_result or {}
        telemetry_payload = (
            runner_result.get("telemetry")
            if isinstance(runner_result, Mapping)
            else None
        )
        rows = telemetry_payload.get("rows") if isinstance(telemetry_payload, Mapping) else None
        if isinstance(rows, list):
            telemetry_rows.extend(row for row in rows if isinstance(row, Mapping))
    survivability_report = attach_observed_telemetry_to_survivability_report(
        survivability_report,
        telemetry_rows=telemetry_rows,
    )
    _write_runtime_json(
        runtime_root / "line_role" / "shard_survivability_report.json",
        survivability_report,
    )

    predictions_by_atomic_index: dict[int, CanonicalLineRolePrediction] = {}
    for shard_plan in shard_plans:
        response_payload = phase_result.response_payloads_by_shard_id.get(shard_plan.shard_id)
        proposal_metadata = dict(
            phase_result.proposal_metadata_by_shard_id.get(shard_plan.shard_id) or {}
        )
        rows = response_payload.get("rows") if isinstance(response_payload, dict) else None
        if not isinstance(rows, list):
            rows = _line_role_partial_authority_rows(proposal_metadata)
        if not isinstance(rows, list):
            continue
        candidate_by_atomic_index = {
            int(candidate.atomic_index): candidate for candidate in shard_plan.candidates
        }
        for row in rows:
            atomic_index = int(row["atomic_index"])
            candidate = candidate_by_atomic_index[atomic_index]
            predictions_by_atomic_index[atomic_index] = CanonicalLineRolePrediction(
                recipe_id=candidate.recipe_id,
                row_id=candidate.row_id,
                block_id=str(candidate.block_id),
                block_index=int(candidate.block_index),
                atomic_index=atomic_index,
                row_ordinal=int(candidate.row_ordinal),
                start_char_in_block=int(candidate.start_char_in_block),
                end_char_in_block=int(candidate.end_char_in_block),
                text=str(candidate.text),
                within_recipe_span=candidate.within_recipe_span,
                label=str(row["label"] or "NONRECIPE_CANDIDATE"),
                decided_by="codex",
                reason_tags=["codex_line_role"],
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
    runtime_metadata: Mapping[str, Any] | None = None,
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
        completed_units=0,
        total_units=len(shard_plans),
        work_unit_label="shard",
        running_units=min(worker_count, len(shard_plans)),
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
            "line_role_pipeline": LINE_ROLE_PIPELINE_ROUTE_V2,
            "codex_exec_style": resolve_codex_exec_style_value(
                settings.line_role_codex_exec_style,
            ),
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
            "workspace_completion_quiescence_seconds": getattr(
                settings,
                "workspace_completion_quiescence_seconds",
                15.0,
            ),
            "completed_termination_grace_seconds": getattr(
                settings,
                "completed_termination_grace_seconds",
                15.0,
            ),
        },
        runtime_metadata={
            "surface_pipeline": LINE_ROLE_PIPELINE_ROUTE_V2,
            "phase_label": shard_plans[0].phase_label,
            "workspace_root": (
                str(codex_farm_workspace_root)
                if codex_farm_workspace_root is not None
                else None
            ),
            **dict(runtime_metadata or {}),
        },
        progress_callback=progress_callback,
        prompt_state=prompt_state,
        validator=validator,
    )
    invalid_shard_count = 0
    missing_output_shard_count = 0
    raw_output_issue_count = 0
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
        proposal_validation_metadata = dict(
            proposal_payload.get("validation_metadata") or {}
        )
        proposal_metadata_by_shard_id[shard_plan.shard_id] = proposal_validation_metadata
        if proposal_validation_metadata.get("raw_output_invalid") or proposal_validation_metadata.get(
            "raw_output_missing"
        ):
            raw_output_issue_count += 1
        if not isinstance(response_payload, dict):
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
    prompt_state.finalize(
        phase_key=shard_plans[0].phase_key,
        parse_error_count=raw_output_issue_count + missing_output_shard_count,
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
















def _notify_line_role_progress(
    *,
    progress_callback: Callable[[str], None] | None,
    completed_units: int,
    total_units: int,
    work_unit_label: str = "row",
    running_units: int | None = None,
    worker_total: int | None = None,
    worker_running: int | None = None,
    worker_completed: int | None = None,
    worker_failed: int | None = None,
    followup_running: int | None = None,
    followup_completed: int | None = None,
    followup_total: int | None = None,
    followup_label: str | None = None,
    artifact_counts: dict[str, Any] | None = None,
    last_activity_at: str | None = None,
    active_tasks: list[str] | None = None,
    detail_lines: list[str] | None = None,
) -> None:
    if progress_callback is None:
        return
    total = max(0, int(total_units))
    completed = max(0, min(total, int(completed_units)))
    unit_label = str(work_unit_label or "row").strip() or "row"
    message = f"Running canonical line-role pipeline... {unit_label} {completed}/{total}"
    if running_units is not None:
        running = max(0, int(running_units))
        message = f"{message} | running {running}"
    remaining = max(0, total - completed)
    resolved_detail_lines = [
        f"queued {unit_label}s: {remaining}",
    ]
    if worker_total is not None:
        resolved_detail_lines.insert(0, f"configured workers: {max(0, int(worker_total))}")
    for value in detail_lines or []:
        cleaned = str(value).strip()
        if cleaned and cleaned not in resolved_detail_lines:
            resolved_detail_lines.append(cleaned)
    progress_callback(
        format_stage_progress(
            message,
            stage_label="canonical line-role pipeline",
            work_unit_label=unit_label,
            task_current=completed,
            task_total=total,
            running_workers=running_units,
            worker_total=worker_total,
            worker_running=worker_running,
            worker_completed=worker_completed,
            worker_failed=worker_failed,
            followup_running=followup_running,
            followup_completed=followup_completed,
            followup_total=followup_total,
            followup_label=followup_label,
            artifact_counts=artifact_counts,
            last_activity_at=(
                str(last_activity_at or "").strip()
                or datetime.now(timezone.utc).isoformat(timespec="seconds")
            ),
            active_tasks=active_tasks,
            detail_lines=resolved_detail_lines,
        )
    )


def _line_role_progress_interval(total_tasks: int) -> int:
    total = max(1, int(total_tasks))
    # Keep progress updates frequent enough for responsive ETA while avoiding
    # excessive callback chatter on large books.
    return max(1, (total + _LINE_ROLE_PROGRESS_MAX_UPDATES - 1) // _LINE_ROLE_PROGRESS_MAX_UPDATES)


def _load_line_role_workspace_frozen_rows(
    *,
    repair_path: Path,
) -> list[dict[str, Any]] | None:
    if not repair_path.exists():
        return None
    try:
        payload = json.loads(repair_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    frozen_rows = payload.get("frozen_rows")
    if not isinstance(frozen_rows, list):
        return None
    return [dict(row) for row in frozen_rows if isinstance(row, Mapping)]


def _line_role_workspace_validation_metadata_from_frozen_rows(
    frozen_rows: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    accepted_rows = [dict(row) for row in frozen_rows or [] if isinstance(row, Mapping)]
    accepted_atomic_indices = [
        int(row["atomic_index"])
        for row in accepted_rows
        if row.get("atomic_index") is not None and str(row.get("atomic_index")).strip()
    ]
    return {
        "accepted_rows": accepted_rows,
        "accepted_atomic_indices": accepted_atomic_indices,
        "frozen_atomic_indices": accepted_atomic_indices,
    }


def _line_role_workspace_ledger_has_authoritative_edits(
    *,
    response_text: str | None,
    shard: ShardManifestEntryV1,
    frozen_rows: Sequence[Mapping[str, Any]] | None,
) -> bool:
    if frozen_rows:
        return True
    cleaned_response_text = str(response_text or "").strip()
    if not cleaned_response_text:
        return False
    try:
        payload = json.loads(cleaned_response_text)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, Mapping):
        return False
    scaffold_payload = build_line_role_workspace_scaffold(
        {"input_payload": shard.input_payload}
    )
    return payload != scaffold_payload




def _looks_like_codex_exec_command(command_text: str) -> bool:
    tokens = str(command_text or "").strip().split()
    if not tokens:
        return False
    executable = Path(tokens[0]).name.lower()
    return executable in _CODEX_EXECUTABLES


from .runtime_workers import (
    _aggregate_line_role_worker_runner_payload as _aggregate_line_role_worker_runner_payload_impl,
    _assign_line_role_workers_v1 as _assign_line_role_workers_v1_impl,
    _build_line_role_repair_shard as _build_line_role_repair_shard_impl,
    _build_line_role_structured_packet as _build_line_role_structured_packet_impl,
    _build_line_role_structured_prompt as _build_line_role_structured_prompt_impl,
    _build_line_role_workspace_task_runner_payload as _build_line_role_workspace_task_runner_payload_impl,
    _line_role_command_policy_by_command as _line_role_command_policy_by_command_impl,
    _line_role_command_policy_counts as _line_role_command_policy_counts_impl,
    _line_role_structured_packet_rows as _line_role_structured_packet_rows_impl,
    _merge_line_role_validation_metadata as _merge_line_role_validation_metadata_impl,
    _run_line_role_direct_worker_assignment_v1 as _run_line_role_direct_worker_assignment_v1_impl,
    _run_line_role_direct_workers_v1 as _run_line_role_direct_workers_v1_impl,
    _run_line_role_structured_assignment_v1 as _run_line_role_structured_assignment_v1_impl,
    _run_line_role_taskfile_assignment_v1 as _run_line_role_taskfile_assignment_v1_impl,
    _write_line_role_telemetry_summary as _write_line_role_telemetry_summary_impl,
)


def _run_line_role_taskfile_assignment_v1(*args, **kwargs):
    return _run_line_role_taskfile_assignment_v1_impl(*args, **kwargs)


def _run_line_role_direct_worker_assignment_v1(*args, **kwargs):
    return _run_line_role_direct_worker_assignment_v1_impl(*args, **kwargs)


def _line_role_structured_packet_rows(*args, **kwargs):
    return _line_role_structured_packet_rows_impl(*args, **kwargs)


def _build_line_role_structured_packet(*args, **kwargs):
    return _build_line_role_structured_packet_impl(*args, **kwargs)


def _build_line_role_structured_prompt(*args, **kwargs):
    return _build_line_role_structured_prompt_impl(*args, **kwargs)


def _build_line_role_repair_shard(*args, **kwargs):
    return _build_line_role_repair_shard_impl(*args, **kwargs)


def _merge_line_role_validation_metadata(*args, **kwargs):
    return _merge_line_role_validation_metadata_impl(*args, **kwargs)


def _run_line_role_structured_assignment_v1(*args, **kwargs):
    return _run_line_role_structured_assignment_v1_impl(*args, **kwargs)


def _run_line_role_direct_workers_v1(*args, **kwargs):
    return _run_line_role_direct_workers_v1_impl(*args, **kwargs)


def _assign_line_role_workers_v1(*args, **kwargs):
    return _assign_line_role_workers_v1_impl(*args, **kwargs)


def _build_line_role_workspace_task_runner_payload(*args, **kwargs):
    return _build_line_role_workspace_task_runner_payload_impl(*args, **kwargs)


def _line_role_command_policy_by_command(*args, **kwargs):
    return _line_role_command_policy_by_command_impl(*args, **kwargs)


def _line_role_command_policy_counts(*args, **kwargs):
    return _line_role_command_policy_counts_impl(*args, **kwargs)


def _aggregate_line_role_worker_runner_payload(*args, **kwargs):
    return _aggregate_line_role_worker_runner_payload_impl(*args, **kwargs)




def _preflight_line_role_shard(
    shard: ShardManifestEntryV1,
) -> dict[str, Any] | None:
    return _preflight_line_role_shard_impl(shard)


def _build_preflight_rejected_run_result(
    *,
    prompt_text: str,
    output_schema_path: Path | None,
    working_dir: Path,
    reason_code: str,
    reason_detail: str,
) -> CodexExecRunResult:
    return _build_preflight_rejected_run_result_impl(
        prompt_text=prompt_text,
        output_schema_path=output_schema_path,
        working_dir=working_dir,
        reason_code=reason_code,
        reason_detail=reason_detail,
    )


def _build_strict_json_watchdog_callback(
    *,
    live_status_path: Path | None = None,
    live_status_paths: Sequence[Path] | None = None,
    same_session_state_path: Path | None = None,
    cohort_watchdog_state: _LineRoleCohortWatchdogState | None = None,
    shard_id: str | None = None,
    watchdog_policy: str = _STRICT_JSON_WATCHDOG_POLICY,
    allow_workspace_commands: bool = False,
    expected_workspace_output_paths: Sequence[Path] | None = None,
    workspace_completion_quiescence_seconds: float | None = None,
    final_message_missing_output_grace_seconds: float | None = None,
) -> Callable[[CodexExecLiveSnapshot], CodexExecSupervisionDecision | None]:
    return _build_strict_json_watchdog_callback_impl(
        live_status_path=live_status_path,
        live_status_paths=live_status_paths,
        same_session_state_path=same_session_state_path,
        cohort_watchdog_state=cohort_watchdog_state,
        shard_id=shard_id,
        watchdog_policy=watchdog_policy,
        allow_workspace_commands=allow_workspace_commands,
        expected_workspace_output_paths=expected_workspace_output_paths,
        workspace_completion_quiescence_seconds=workspace_completion_quiescence_seconds,
        final_message_missing_output_grace_seconds=final_message_missing_output_grace_seconds,
    )


def _classify_line_role_workspace_command(
    command_text: str | None,
    *,
    single_file_worker_policy: bool = False,
) -> WorkspaceCommandClassification:
    return _classify_line_role_workspace_command_impl(
        command_text,
        single_file_worker_policy=single_file_worker_policy,
    )


def _line_role_resume_reason_fields(*, resumed_from_existing_outputs: bool) -> tuple[str, str]:
    return _line_role_resume_reason_fields_impl(
        resumed_from_existing_outputs=resumed_from_existing_outputs
    )

def _should_attempt_line_role_watchdog_retry(
    *,
    run_result: CodexExecRunResult,
) -> bool:
    return _should_attempt_line_role_watchdog_retry_impl(run_result=run_result)


def _build_line_role_watchdog_example(
    *,
    shard: ShardManifestEntryV1,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    return _build_line_role_watchdog_example_impl(
        shard=shard,
        payload=payload,
    )


def _should_attempt_line_role_repair(
    *,
    proposal_status: str,
    validation_errors: Sequence[str],
) -> bool:
    return _should_attempt_line_role_repair_impl(
        proposal_status=proposal_status,
        validation_errors=validation_errors,
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
    return _run_line_role_watchdog_retry_attempt_impl(
        runner=runner,
        worker_root=worker_root,
        shard=shard,
        env=env,
        output_schema_path=output_schema_path,
        model=model,
        reasoning_effort=reasoning_effort,
        original_reason_code=original_reason_code,
        original_reason_detail=original_reason_detail,
        successful_examples=successful_examples,
        timeout_seconds=timeout_seconds,
        pipeline_id=pipeline_id,
        worker_id=worker_id,
        live_status_path=live_status_path,
    )


def _build_line_role_watchdog_retry_prompt(
    *,
    shard: ShardManifestEntryV1,
    original_reason_code: str,
    original_reason_detail: str,
    successful_examples: Sequence[Mapping[str, Any]],
) -> str:
    return _build_line_role_watchdog_retry_prompt_impl(
        shard=shard,
        original_reason_code=original_reason_code,
        original_reason_detail=original_reason_detail,
        successful_examples=successful_examples,
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
    events_path: Path | None = None,
    last_message_path: Path | None = None,
    usage_path: Path | None = None,
    live_status_path: Path | None = None,
    workspace_manifest_path: Path | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
) -> dict[str, Any]:
    return _build_line_role_inline_attempt_runner_payload_impl(
        pipeline_id=pipeline_id,
        worker_id=worker_id,
        shard_id=shard_id,
        run_result=run_result,
        model=model,
        reasoning_effort=reasoning_effort,
        prompt_input_mode=prompt_input_mode,
        events_path=events_path,
        last_message_path=last_message_path,
        usage_path=usage_path,
        live_status_path=live_status_path,
        workspace_manifest_path=workspace_manifest_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )


def _write_line_role_telemetry_summary(*args, **kwargs):
    return _write_line_role_telemetry_summary_impl(*args, **kwargs)




def _safe_int_value(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None






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
