from __future__ import annotations

import sys
from dataclasses import asdict, dataclass

from cookimport.llm.editable_task_file import (
    TASK_FILE_NAME,
    build_task_file,
    load_task_file,
    validate_edited_task_file,
    write_task_file,
)
from cookimport.llm.task_file_guardrails import (
    build_task_file_guardrail,
    build_worker_session_guardrails,
    summarize_task_file_guardrails,
)
from cookimport.llm.workspace_worker_progress import (
    decorate_active_worker_label,
    start_workspace_worker_progress_heartbeat,
    summarize_workspace_worker_health,
)
from .same_session_handoff import (
    LINE_ROLE_SAME_SESSION_STATE_ENV,
    describe_line_role_same_session_doctor,
    describe_line_role_same_session_status,
    initialize_line_role_same_session_state,
)

runtime = sys.modules["cookimport.parsing.canonical_line_roles"]
globals().update(
    {
        name: value
        for name, value in vars(runtime).items()
        if not name.startswith("__")
    }
)


def _runtime_attr(name: str, default: Any) -> Any:
    return getattr(runtime, name, default)


_LINE_ROLE_SAME_SESSION_STATE_FILE_NAME = "line_role_same_session_state.json"


def _line_role_same_session_state_path(worker_root: Path) -> Path:
    return worker_root / "_repo_control" / _LINE_ROLE_SAME_SESSION_STATE_FILE_NAME


def _load_json_dict_safely(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _summarize_line_role_same_session_completion(
    state_path: Path | None,
) -> dict[str, Any]:
    path = Path(state_path) if state_path is not None else None
    state_payload = _load_json_dict_safely(path) if path is not None else {}
    final_status = str(state_payload.get("final_status") or "").strip() or None
    return {
        "same_session_state_path": str(path) if path is not None else None,
        "same_session_state_available": bool(path is not None and path.exists()),
        "same_session_completed": bool(state_payload.get("completed")),
        "same_session_final_status": final_status,
        "same_session_completed_shard_count": int(
            state_payload.get("completed_shard_count") or 0
        ),
        "same_session_transition_count": int(
            state_payload.get("same_session_transition_count") or 0
        ),
        "same_session_validation_count": int(state_payload.get("validation_count") or 0),
    }


def _line_role_task_file_useful_progress(
    *,
    task_file_path: Path,
    original_task_file: Mapping[str, Any],
    same_session_state_payload: Mapping[str, Any],
) -> bool:
    if not task_file_path.exists():
        return False
    if int(same_session_state_payload.get("same_session_transition_count") or 0) > 0:
        return True
    try:
        edited_task_file = load_task_file(task_file_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    _answers_by_unit_id, _errors, metadata = validate_edited_task_file(
        original_task_file=original_task_file,
        edited_task_file=edited_task_file,
        allow_immutable_field_changes=True,
    )
    return bool(int(metadata.get("changed_unit_count") or 0) > 0)


def _line_role_hard_boundary_failure(run_result: CodexExecRunResult) -> bool:
    reason_code = str(run_result.supervision_reason_code or "").strip()
    if reason_code == "workspace_final_message_missing_output":
        return False
    if str(run_result.supervision_state or "").strip() == "boundary_interrupted":
        return True
    return reason_code.startswith("watchdog_") or "boundary" in reason_code


def _should_attempt_line_role_fresh_session_retry(
    *,
    run_result: CodexExecRunResult,
    task_file_path: Path,
    original_task_file: Mapping[str, Any],
    same_session_state_payload: Mapping[str, Any],
) -> tuple[bool, str]:
    retry_limit = int(same_session_state_payload.get("fresh_session_retry_limit") or 0)
    retry_count = int(same_session_state_payload.get("fresh_session_retry_count") or 0)
    if retry_limit <= retry_count:
        return False, "fresh_session_retry_budget_spent"
    if bool(same_session_state_payload.get("completed")):
        return False, "same_session_already_completed"
    if str(same_session_state_payload.get("final_status") or "").strip() == "repair_exhausted":
        return False, "same_session_repair_exhausted"
    if _line_role_hard_boundary_failure(run_result):
        return False, "hard_boundary_failure"
    if not run_result.completed_successfully():
        return False, "worker_session_not_clean"
    if not _line_role_task_file_useful_progress(
        task_file_path=task_file_path,
        original_task_file=original_task_file,
        same_session_state_payload=same_session_state_payload,
    ):
        return False, "no_preserved_progress"
    return True, "preserved_progress_without_completion"


@dataclass(frozen=True)
class _LineRoleRecoveryAssessment:
    prior_session_reason_code: str
    recoverable_by_fresh_session: bool
    diagnosis_code: str
    recommended_command: str | None
    same_session_completed: bool
    outputs_present: bool
    fresh_session_retry_limit: int
    fresh_session_retry_count: int
    resume_summary: str | None
    blocked_reason: str | None = None


def _line_role_recovery_guidance_for_diagnosis(
    diagnosis_code: str | None,
) -> tuple[bool, str | None]:
    code = str(diagnosis_code or "").strip()
    if code == "completed":
        return False, "same-session helper already completed this workspace"
    if code == "answers_present_helper_not_run":
        return (
            True,
            "task.json contains saved answers but the same-session helper has not produced out/<shard_id>.json yet",
        )
    if code == "ready_for_validation":
        return (
            True,
            "answers are present and the same-session helper still needs to validate and install out/<shard_id>.json",
        )
    if code == "repair_ready_helper_not_run":
        return (
            True,
            "repair answers are present but the same-session helper has not installed out/<shard_id>.json yet",
        )
    if code == "awaiting_answers":
        return False, "task.json still has blank answer objects"
    if code == "repair_answers_missing":
        return False, "repair mode is active but corrected answers are still missing"
    return False, None


def _load_json_dict_with_error(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, str(exc)
    return (dict(payload) if isinstance(payload, Mapping) else {}), None


def _assess_line_role_workspace_recovery(
    *,
    worker_root: Path,
    state_path: Path,
    run_result: CodexExecRunResult,
    expected_workspace_output_paths: Sequence[Path],
) -> tuple[_LineRoleRecoveryAssessment, dict[str, Any]]:
    prior_session_reason_code = str(run_result.supervision_reason_code or "").strip()
    output_status = _summarize_workspace_output_paths(expected_workspace_output_paths)
    outputs_present = bool(output_status.get("complete"))
    state_payload, state_error = _load_json_dict_with_error(state_path)
    task_file_path = worker_root / TASK_FILE_NAME
    task_file_error: str | None = None
    if task_file_path.exists():
        try:
            load_task_file(task_file_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            task_file_error = str(exc)
    else:
        task_file_error = "missing"
    retry_limit = int(state_payload.get("fresh_session_retry_limit") or 0)
    retry_count = int(state_payload.get("fresh_session_retry_count") or 0)
    status_payload: dict[str, Any] = {}
    doctor_payload: dict[str, Any] = {}
    status_error: str | None = None
    doctor_error: str | None = None
    if state_error is None:
        try:
            status_payload = describe_line_role_same_session_status(
                workspace_root=worker_root,
                state_path=state_path,
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            status_error = str(exc)
        try:
            doctor_payload = describe_line_role_same_session_doctor(
                workspace_root=worker_root,
                state_path=state_path,
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            doctor_error = str(exc)
    diagnosis_code = str(doctor_payload.get("diagnosis_code") or "unavailable").strip()
    recommended_command = str(doctor_payload.get("recommended_command") or "").strip() or None
    same_session_completed = bool(
        status_payload.get("same_session_completed")
        if status_payload
        else state_payload.get("completed")
    )
    recoverable_by_diagnosis, resume_summary = _line_role_recovery_guidance_for_diagnosis(
        diagnosis_code
    )
    blocked_reason: str | None = None
    if state_error is not None:
        blocked_reason = "same_session_state_unavailable"
    elif task_file_error is not None:
        blocked_reason = "task_file_unavailable"
    elif _line_role_hard_boundary_failure(run_result):
        blocked_reason = "hard_boundary_failure"
    elif outputs_present:
        blocked_reason = "outputs_already_present"
    elif retry_limit <= retry_count:
        blocked_reason = "fresh_session_retry_budget_spent"
    elif not recoverable_by_diagnosis:
        blocked_reason = (
            f"diagnosis_{diagnosis_code}" if diagnosis_code else "diagnosis_unknown"
        )
    assessment = _LineRoleRecoveryAssessment(
        prior_session_reason_code=prior_session_reason_code,
        recoverable_by_fresh_session=blocked_reason is None and recoverable_by_diagnosis,
        diagnosis_code=diagnosis_code,
        recommended_command=recommended_command,
        same_session_completed=same_session_completed,
        outputs_present=outputs_present,
        fresh_session_retry_limit=retry_limit,
        fresh_session_retry_count=retry_count,
        resume_summary=resume_summary,
        blocked_reason=blocked_reason,
    )
    artifact_payload = {
        "created_at_utc": _format_utc_now(),
        "prior_session_supervision_state": str(run_result.supervision_state or "").strip()
        or None,
        "prior_session_reason_code": prior_session_reason_code or None,
        "prior_session_reason_detail": str(run_result.supervision_reason_detail or "").strip()
        or None,
        "prior_session_retryable": bool(run_result.supervision_retryable),
        "same_session_state_path": str(state_path),
        "same_session_state_available": state_error is None,
        "same_session_state_error": state_error,
        "task_file_path": str(task_file_path),
        "task_file_available": task_file_error is None,
        "task_file_error": task_file_error,
        "workspace_output_status": dict(output_status),
        "status_payload": dict(status_payload),
        "status_error": status_error,
        "doctor_payload": dict(doctor_payload),
        "doctor_error": doctor_error,
        "assessment": asdict(assessment),
    }
    return assessment, artifact_payload


def _should_attempt_line_role_final_message_recovery(
    *,
    run_result: CodexExecRunResult,
    assessment: _LineRoleRecoveryAssessment,
) -> tuple[bool, str]:
    if str(run_result.supervision_reason_code or "").strip() != "workspace_final_message_missing_output":
        return False, "not_final_message_missing_output"
    if not assessment.recoverable_by_fresh_session:
        return False, str(assessment.blocked_reason or "not_recoverable")
    return True, "workspace_final_message_missing_output"


def _build_line_role_final_message_recovery_prompt(
    *,
    shards: Sequence[ShardManifestEntryV1],
    assessment: _LineRoleRecoveryAssessment,
) -> str:
    assignments = "\n".join(f"- `{shard.shard_id}`" for shard in shards)
    recommended_command = (
        assessment.recommended_command
        or "python3 -m cookimport.parsing.canonical_line_roles.same_session_handoff"
    )
    return (
        "Resume the existing canonical line-role workspace after the previous session emitted a final message without writing the required shard output.\n\n"
        "Do this exactly:\n"
        "- First run `python3 -m cookimport.parsing.canonical_line_roles.same_session_handoff --status`.\n"
        "- If the next step is still unclear, run `python3 -m cookimport.parsing.canonical_line_roles.same_session_handoff --doctor`.\n"
        f"- Follow the repo-owned recommended command: `{recommended_command}`.\n"
        "- Prefer repo-owned helper commands over shell scripting.\n"
        "- Stop as soon as the helper reports `completed`.\n\n"
        f"Recovery diagnosis: {assessment.diagnosis_code or '[unknown]'}\n"
        f"Resume summary: {assessment.resume_summary or '[none available]'}\n\n"
        "Assigned shard ids represented in this task file:\n"
        f"{assignments}\n"
    )


def _build_line_role_task_file(
    *,
    assignment: WorkerAssignmentV1,
    shards: Sequence[ShardManifestEntryV1],
    debug_payload_by_shard_id: Mapping[str, Any],
    deterministic_baseline_by_shard_id: Mapping[str, Mapping[int, CanonicalLineRolePrediction]],
) -> tuple[dict[str, Any], dict[str, str]]:
    del deterministic_baseline_by_shard_id
    units: list[dict[str, Any]] = []
    unit_to_shard_id: dict[str, str] = {}
    for shard in shards:
        debug_rows = list(_coerce_mapping_dict(debug_payload_by_shard_id.get(shard.shard_id)).get("rows") or [])
        debug_row_by_atomic_index = {
            int(row.get("atomic_index")): dict(row)
            for row in debug_rows
            if isinstance(row, Mapping) and row.get("atomic_index") is not None
        }
        for row in _coerce_mapping_dict(shard.input_payload).get("rows") or []:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            atomic_index = int(row[0])
            text = str(row[1] or "")
            debug_row = debug_row_by_atomic_index.get(atomic_index) or {}
            unit_id = f"line::{atomic_index}"
            unit_to_shard_id[unit_id] = shard.shard_id
            units.append(
                {
                    "unit_id": unit_id,
                    "owned_id": str(atomic_index),
                    "evidence": {
                        "atomic_index": atomic_index,
                        "block_id": str(debug_row.get("block_id") or ""),
                        "text": text,
                        "within_recipe_span": debug_row.get("within_recipe_span"),
                    },
                    "answer": {},
                }
            )
    return (
        build_task_file(
            stage_key="line_role",
            assignment_id=assignment.worker_id,
            worker_id=assignment.worker_id,
            units=units,
            helper_commands={
                "summary": "python3 -m cookimport.llm.editable_task_file --summary",
                "show_unit": (
                    "python3 -m cookimport.llm.editable_task_file --show-unit <unit_id>"
                ),
                "show_unanswered": (
                    "python3 -m cookimport.llm.editable_task_file --show-unanswered --limit 5"
                ),
                "apply_answer_json": (
                    "python3 -m cookimport.llm.editable_task_file --set-answer "
                    "<unit_id> '<answer_json>'"
                ),
                "apply_answers_file": (
                    "python3 -m cookimport.llm.editable_task_file --apply-answers-file answers.json"
                ),
                "status": (
                    "python3 -m cookimport.parsing.canonical_line_roles.same_session_handoff "
                    "--status"
                ),
                "doctor": (
                    "python3 -m cookimport.parsing.canonical_line_roles.same_session_handoff "
                    "--doctor"
                ),
                "handoff": (
                    "python3 -m cookimport.parsing.canonical_line_roles.same_session_handoff"
                ),
            },
            next_action=(
                "Set every /units/*/answer object, then run "
                "python3 -m cookimport.parsing.canonical_line_roles.same_session_handoff."
            ),
            answer_schema={
                "editable_pointer_pattern": "/units/*/answer",
                "required_keys": ["label"],
                "optional_keys": ["exclusion_reason"],
                "allowed_values": {
                    "label": [
                        "RECIPE_TITLE",
                        "INGREDIENT_LINE",
                        "INSTRUCTION_LINE",
                        "TIME_LINE",
                        "HOWTO_SECTION",
                        "YIELD_LINE",
                        "RECIPE_VARIANT",
                        "RECIPE_NOTES",
                        "NONRECIPE_CANDIDATE",
                        "NONRECIPE_EXCLUDE",
                    ],
                    "exclusion_reason": [
                        "navigation",
                        "front_matter",
                        "publishing_metadata",
                        "copyright_legal",
                        "endorsement",
                        "publisher_promo",
                        "page_furniture",
                    ],
                },
                "example_answers": [
                    {"label": "RECIPE_NOTES"},
                    {
                        "label": "NONRECIPE_EXCLUDE",
                        "exclusion_reason": "navigation",
                    },
                ],
            },
        ),
        unit_to_shard_id,
    )


def _expand_line_role_task_file_outputs(
    *,
    original_task_file: Mapping[str, Any],
    task_file_path: Path,
    unit_to_shard_id: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    try:
        edited_task_file = load_task_file(task_file_path)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {}
    answers_by_unit_id, validation_errors, _validation_metadata = validate_edited_task_file(
        original_task_file=original_task_file,
        edited_task_file=edited_task_file,
        allow_immutable_field_changes=True,
    )
    if validation_errors:
        return {}
    shard_rows: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for unit in original_task_file.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_id = str(unit.get("unit_id") or "").strip()
        shard_id = str(unit_to_shard_id.get(unit_id) or "").strip()
        if not shard_id:
            continue
        evidence = dict(unit.get("evidence") or {})
        answer = dict((answers_by_unit_id or {}).get(unit_id) or {})
        shard_rows.setdefault(shard_id, []).append(
            (int(evidence.get("atomic_index") or 0), answer)
        )
    return {
        shard_id: {
            "rows": [
                {
                    **{
                        "atomic_index": atomic_index,
                        "label": str(answer.get("label") or ""),
                    },
                    **(
                        {"exclusion_reason": answer.get("exclusion_reason")}
                        if answer.get("exclusion_reason") is not None
                        else {}
                    ),
                }
                for atomic_index, answer in sorted(rows, key=lambda row: row[0])
            ]
        }
        for shard_id, rows in shard_rows.items()
    }


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


def _raise_if_line_role_runtime_incomplete(
    *,
    ordered_candidates: Sequence[AtomicLineCandidate],
    runtime_result: _LineRoleRuntimeResult | None,
) -> None:
    if runtime_result is None:
        return
    missing_atomic_indices = [
        int(candidate.atomic_index)
        for candidate in ordered_candidates
        if int(candidate.atomic_index)
        not in runtime_result.predictions_by_atomic_index
    ]
    if not missing_atomic_indices:
        return
    failed_shards: list[str] = []
    runtime_roots: list[str] = []
    for phase_result in runtime_result.phase_results:
        if phase_result.runtime_root is None:
            continue
        runtime_roots.append(str(phase_result.runtime_root))
        shard_status_path = phase_result.runtime_root / "shard_status.jsonl"
        if not shard_status_path.exists():
            continue
        for line in shard_status_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, Mapping):
                continue
            state = str(row.get("state") or "").strip()
            shard_id = str(row.get("shard_id") or "").strip()
            reason_code = str(
                (
                    (row.get("metadata") or {})
                    if isinstance(row.get("metadata"), Mapping)
                    else {}
                ).get("repair_status")
                or row.get("reason_code")
                or ""
            ).strip()
            if state in {"validated", "repair_recovered"}:
                continue
            detail = shard_id or "<unknown-shard>"
            if state:
                detail += f" state={state}"
            if reason_code:
                detail += f" repair_status={reason_code}"
            failed_shards.append(detail)
    detail_suffix = ""
    if failed_shards:
        detail_suffix = " Failed shards: " + "; ".join(failed_shards[:5]) + "."
    runtime_root_suffix = ""
    if runtime_roots:
        runtime_root_suffix = " Runtime roots: " + ", ".join(runtime_roots) + "."
    raise LineRoleRepairFailureError(
        "canonical line-role failed closed because one or more shards ended without a clean installed ledger."
        f" Missing atomic indices: {', '.join(str(value) for value in missing_atomic_indices)}."
        f"{detail_suffix}{runtime_root_suffix}"
    )


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
                block_id=str(candidate.block_id),
                block_index=int(candidate.block_index),
                atomic_index=int(candidate.atomic_index),
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
    codex_farm_workspace_root = _runtime_attr(
        "_resolve_line_role_codex_farm_workspace_root",
        _resolve_line_role_codex_farm_workspace_root,
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
        rows = response_payload.get("rows")
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
                block_id=str(candidate.block_id),
                block_index=int(candidate.block_index),
                atomic_index=atomic_index,
                text=str(candidate.text),
                within_recipe_span=candidate.within_recipe_span,
                label=str(row["label"] or "NONRECIPE_CANDIDATE"),
                decided_by="codex",
                reason_tags=["codex_line_role"],
                exclusion_reason=row.get("exclusion_reason"),
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
        proposal_metadata_by_shard_id[shard_plan.shard_id] = proposal_validation_metadata
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
    settings: Mapping[str, Any],
    output_schema_path: Path | None,
    timeout_seconds: int,
    cohort_watchdog_state: _LineRoleCohortWatchdogState,
    shard_completed_callback: Callable[..., None] | None,
    prompt_state: "_PromptArtifactState" | None,
    validator: Callable[[ShardManifestEntryV1, dict[str, Any]], tuple[bool, Sequence[str], dict[str, Any] | None]],
) -> _DirectLineRoleWorkerResult:
    out_dir = worker_root / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    worker_failure_count = 0
    worker_proposal_count = 0
    worker_runner_results: list[dict[str, Any]] = []
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    stage_rows: list[dict[str, Any]] = []
    runner_results_by_shard_id: dict[str, dict[str, Any]] = {}
    runnable_shard_ids: set[str] = set()
    resumed_output_path_by_shard_id: dict[str, Path] = {}
    task_status_rows: list[dict[str, Any]] = []
    worker_prompt_path: Path | None = None
    session_run_result: CodexExecRunResult | None = None
    valid_shards: list[ShardManifestEntryV1] = []
    task_file_payload: dict[str, Any] | None = None
    unit_to_shard_id: dict[str, str] = {}

    for shard in assigned_shards:
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
        for stale_artifact_name in (
            "repair_prompt.txt",
            "repair_events.jsonl",
            "repair_last_message.json",
            "repair_usage.json",
            "repair_workspace_manifest.json",
            "repair_live_status.json",
            "repair_status.json",
        ):
            stale_artifact_path = shard_root / stale_artifact_name
            if stale_artifact_path.exists():
                stale_artifact_path.unlink()
        preflight_failure = _preflight_line_role_shard(shard)
        if preflight_failure is None:
            valid_shards.append(shard)
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

    assigned_shard_rows = [
        _build_line_role_worker_shard_row(shard=shard) for shard in valid_shards
    ]
    assigned_shard_row_by_shard_id = {
        str(shard_row.get("shard_id") or "").strip(): shard_row
        for shard_row in assigned_shard_rows
        if str(shard_row.get("shard_id") or "").strip()
    }
    _write_runtime_json(worker_root / "assigned_shards.json", assigned_shard_rows)
    for shard in valid_shards:
        shard_id = shard.shard_id
        shard_row = assigned_shard_row_by_shard_id.get(shard_id)
        if shard_row is None:
            continue
        _write_worker_debug_input(
            path=in_dir / f"{shard_id}.json",
            payload=shard.input_payload,
            input_text=None,
        )
        _write_worker_debug_input(
            path=debug_dir / f"{shard_id}.json",
            payload=debug_payload_by_shard_id.get(shard_id),
            input_text=None,
        )
        _write_line_role_worker_hint(
            path=hints_dir / f"{shard_id}.md",
            shard=shard,
            debug_payload=debug_payload_by_shard_id.get(shard_id),
        )
        existing_output_path = _find_line_role_existing_output_path(
            run_root=run_root,
            preferred_worker_root=worker_root,
            shard_id=shard_id,
        )
        if existing_output_path is None:
            runnable_shard_ids.add(shard_id)
            continue
        try:
            existing_response_text = existing_output_path.read_text(encoding="utf-8")
        except OSError:
            runnable_shard_ids.add(shard_id)
            continue
        existing_payload, _, _, existing_status = (
            _evaluate_line_role_response_with_pathology_guard(
                shard=shard,
                response_text=existing_response_text,
                validator=validator,
                deterministic_baseline_by_atomic_index=dict(
                    deterministic_baseline_by_shard_id.get(shard_id) or {}
                ),
            )
        )
        if existing_payload is not None and existing_status == "validated":
            resumed_output_path_by_shard_id[shard_id] = existing_output_path
        else:
            runnable_shard_ids.add(shard_id)

    runnable_shards = [shard for shard in valid_shards if shard.shard_id in runnable_shard_ids]
    task_file_guardrail: dict[str, Any] | None = None
    line_role_same_session_state_payload: dict[str, Any] = {}
    fresh_session_retry_count = 0
    fresh_session_retry_status = "not_attempted"
    fresh_session_recovery_metadata: dict[str, Any] = {}
    if runnable_shards:
        task_file_payload, unit_to_shard_id = _build_line_role_task_file(
            assignment=assignment,
            shards=runnable_shards,
            debug_payload_by_shard_id=debug_payload_by_shard_id,
            deterministic_baseline_by_shard_id=deterministic_baseline_by_shard_id,
        )
        task_file_guardrail = build_task_file_guardrail(
            payload=task_file_payload,
            assignment_id=assignment.worker_id,
            worker_id=assignment.worker_id,
        )
        state_path = _line_role_same_session_state_path(worker_root)
        initialize_line_role_same_session_state(
            state_path=state_path,
            assignment_id=assignment.worker_id,
            worker_id=assignment.worker_id,
            task_file=task_file_payload,
            unit_to_shard_id=unit_to_shard_id,
            shards=[asdict(shard) for shard in runnable_shards],
            output_dir=out_dir,
        )
        write_task_file(path=worker_root / TASK_FILE_NAME, payload=task_file_payload)
        worker_prompt_text = _build_line_role_workspace_worker_prompt(
            shards=runnable_shards,
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
            env={
                **dict(env),
                LINE_ROLE_SAME_SESSION_STATE_ENV: str(state_path),
            },
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
            completed_termination_grace_seconds=float(
                settings.get("completed_termination_grace_seconds") or 15.0
            ),
            workspace_task_label="canonical line-role worker session",
            supervision_callback=_build_strict_json_watchdog_callback(
                live_status_path=worker_live_status_path,
                live_status_paths=shard_live_status_paths,
                same_session_state_path=state_path,
                cohort_watchdog_state=cohort_watchdog_state,
                watchdog_policy="workspace_worker_v1",
                allow_workspace_commands=True,
                expected_workspace_output_paths=[
                    out_dir / f"{shard.shard_id}.json" for shard in runnable_shards
                ],
                workspace_completion_quiescence_seconds=float(
                    settings.get("workspace_completion_quiescence_seconds") or 15.0
                ),
                final_message_missing_output_grace_seconds=float(
                    settings.get("workspace_completion_quiescence_seconds") or 15.0
                ),
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
        _write_optional_runtime_text(worker_root / "stdout.txt", session_run_result.stdout_text)
        _write_optional_runtime_text(worker_root / "stderr.txt", session_run_result.stderr_text)
        line_role_same_session_state_payload = _load_json_dict_safely(state_path)
        expected_workspace_output_paths = [
            out_dir / f"{shard.shard_id}.json" for shard in runnable_shards
        ]
        worker_session_runs: list[tuple[CodexExecRunResult, Path, bool, str | None]] = [
            (session_run_result, worker_prompt_path, False, None)
        ]
        final_message_recovery_assessment_path = (
            worker_root / "final_message_recovery_assessment.json"
        )
        should_retry = False
        retry_reason = "not_attempted"
        retry_prompt_path: Path | None = None
        retry_prompt_text: str | None = None
        retry_workspace_task_label = "canonical line-role fresh-session recovery"
        if (
            str(session_run_result.supervision_reason_code or "").strip()
            == "workspace_final_message_missing_output"
        ):
            assessment, assessment_payload = _assess_line_role_workspace_recovery(
                worker_root=worker_root,
                state_path=state_path,
                run_result=session_run_result,
                expected_workspace_output_paths=expected_workspace_output_paths,
            )
            should_retry, retry_reason = _should_attempt_line_role_final_message_recovery(
                run_result=session_run_result,
                assessment=assessment,
            )
            fresh_session_recovery_metadata = {
                "fresh_session_recovery_attempted": False,
                "fresh_session_recovery_status": "attempted" if should_retry else "skipped",
                "fresh_session_recovery_count": 0,
                "fresh_session_recovery_skipped_reason": (
                    None if should_retry else retry_reason
                ),
                "shared_retry_budget_spent": (
                    int(assessment.fresh_session_retry_count)
                    >= int(assessment.fresh_session_retry_limit)
                ),
                "prior_session_reason_code": assessment.prior_session_reason_code or None,
                "diagnosis_code": assessment.diagnosis_code or None,
                "recommended_command": assessment.recommended_command,
                "resume_summary": assessment.resume_summary,
                "assessment_path": _relative_runtime_path(
                    run_root, final_message_recovery_assessment_path
                ),
            }
            _write_runtime_json(
                final_message_recovery_assessment_path,
                {
                    **assessment_payload,
                    **fresh_session_recovery_metadata,
                },
            )
            if should_retry:
                retry_prompt_path = worker_root / "prompt_resume_final_message.txt"
                retry_prompt_text = _build_line_role_final_message_recovery_prompt(
                    shards=runnable_shards,
                    assessment=assessment,
                )
                retry_workspace_task_label = (
                    "canonical line-role final-message missing-output recovery"
                )
        else:
            should_retry, retry_reason = _should_attempt_line_role_fresh_session_retry(
                run_result=session_run_result,
                task_file_path=worker_root / TASK_FILE_NAME,
                original_task_file=task_file_payload,
                same_session_state_payload=line_role_same_session_state_payload,
            )
        if should_retry:
            fresh_session_retry_count = 1
            fresh_session_retry_status = "attempted"
            line_role_same_session_state_payload["fresh_session_retry_count"] = 1
            line_role_same_session_state_payload["fresh_session_retry_status"] = "attempted"
            fresh_session_retry_history = list(
                line_role_same_session_state_payload.get("fresh_session_retry_history") or []
            )
            fresh_session_retry_history.append(
                {
                    "attempt": 1,
                    "reason_code": retry_reason,
                    "reason_detail": (
                        "workspace final message was observed without required shard outputs"
                        if retry_reason == "workspace_final_message_missing_output"
                        else "clean first session preserved useful workspace state without completion"
                    ),
                }
            )
            line_role_same_session_state_payload["fresh_session_retry_history"] = fresh_session_retry_history
            _write_runtime_json(state_path, line_role_same_session_state_payload)
            resume_prompt_path = retry_prompt_path or (worker_root / "prompt_resume.txt")
            resume_prompt_text = retry_prompt_text or _build_line_role_workspace_worker_prompt(
                shards=runnable_shards,
                fresh_session_resume=True,
            )
            resume_prompt_path.write_text(resume_prompt_text, encoding="utf-8")
            session_run_result = runner.run_workspace_worker(
                prompt_text=resume_prompt_text,
                working_dir=worker_root,
                env={
                    **dict(env),
                    LINE_ROLE_SAME_SESSION_STATE_ENV: str(state_path),
                },
                model=model,
                reasoning_effort=reasoning_effort,
                timeout_seconds=timeout_seconds,
                completed_termination_grace_seconds=float(
                    settings.get("completed_termination_grace_seconds") or 15.0
                ),
                workspace_task_label=retry_workspace_task_label,
                supervision_callback=_build_strict_json_watchdog_callback(
                    live_status_path=worker_live_status_path,
                    live_status_paths=shard_live_status_paths,
                    same_session_state_path=state_path,
                    cohort_watchdog_state=cohort_watchdog_state,
                    watchdog_policy="workspace_worker_v1",
                    allow_workspace_commands=True,
                    expected_workspace_output_paths=expected_workspace_output_paths,
                    workspace_completion_quiescence_seconds=float(
                        settings.get("workspace_completion_quiescence_seconds") or 15.0
                    ),
                    final_message_missing_output_grace_seconds=float(
                        settings.get("workspace_completion_quiescence_seconds") or 15.0
                    ),
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
            _write_optional_runtime_text(worker_root / "stdout.txt", session_run_result.stdout_text)
            _write_optional_runtime_text(worker_root / "stderr.txt", session_run_result.stderr_text)
            line_role_same_session_state_payload = _load_json_dict_safely(state_path)
            fresh_session_retry_status = (
                "completed"
                if bool(line_role_same_session_state_payload.get("completed"))
                else "failed"
            )
            line_role_same_session_state_payload["fresh_session_retry_count"] = 1
            line_role_same_session_state_payload["fresh_session_retry_status"] = fresh_session_retry_status
            line_role_same_session_state_payload["fresh_session_retry_history"] = [
                {
                    **dict(row),
                    **(
                        {
                            "result_completed": bool(line_role_same_session_state_payload.get("completed")),
                            "result_final_status": line_role_same_session_state_payload.get("final_status"),
                        }
                        if index == len(fresh_session_retry_history) - 1
                        else {}
                    ),
                }
                for index, row in enumerate(fresh_session_retry_history)
                if isinstance(row, Mapping)
            ]
            _write_runtime_json(state_path, line_role_same_session_state_payload)
            if fresh_session_recovery_metadata:
                recovery_outputs_present = bool(
                    _summarize_workspace_output_paths(expected_workspace_output_paths).get(
                        "complete"
                    )
                )
                fresh_session_recovery_metadata = {
                    **fresh_session_recovery_metadata,
                    "fresh_session_recovery_attempted": True,
                    "fresh_session_recovery_status": (
                        "recovered"
                        if bool(line_role_same_session_state_payload.get("completed"))
                        or recovery_outputs_present
                        else "exhausted"
                    ),
                    "fresh_session_recovery_count": 1,
                    "fresh_session_recovery_skipped_reason": None,
                    "shared_retry_budget_spent": True,
                }
                existing_assessment_payload = _load_json_dict_safely(
                    final_message_recovery_assessment_path
                )
                _write_runtime_json(
                    final_message_recovery_assessment_path,
                    {
                        **existing_assessment_payload,
                        **fresh_session_recovery_metadata,
                    },
                )
            worker_session_runs.append(
                (session_run_result, resume_prompt_path, True, retry_reason)
            )
        shard_count = max(1, len(runnable_shards))
        for session_index, (
            session_result,
            session_prompt_file,
            fresh_session_resume,
            fresh_session_resume_reason_code,
        ) in enumerate(worker_session_runs, start=1):
            for shard_index, shard in enumerate(runnable_shards):
                shard_id = shard.shard_id
                input_path = in_dir / f"{shard_id}.json"
                debug_path = debug_dir / f"{shard_id}.json"
                runner_payload = _build_line_role_workspace_task_runner_payload(
                    pipeline_id=pipeline_id,
                    worker_id=assignment.worker_id,
                    shard_id=shard_id,
                    runtime_shard_id=shard_id,
                    run_result=session_result,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    request_input_file=input_path,
                    debug_input_file=debug_path,
                    worker_prompt_path=session_prompt_file,
                    worker_root=worker_root,
                    task_count=shard_count,
                    task_index=min(shard_index, shard_count - 1),
                )
                telemetry = runner_payload.get("telemetry")
                row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
                if isinstance(row_payloads, list):
                    for row_payload in row_payloads:
                        if isinstance(row_payload, dict):
                            row_payload["fresh_session_resume"] = fresh_session_resume
                            row_payload["fresh_session_resume_reason_code"] = (
                                fresh_session_resume_reason_code
                            )
                            stage_rows.append(dict(row_payload))
                runner_payload["fresh_session_resume"] = fresh_session_resume
                runner_payload["fresh_session_resume_reason_code"] = (
                    fresh_session_resume_reason_code
                )
                process_payload = runner_payload.get("process_payload")
                if isinstance(process_payload, dict):
                    process_payload["fresh_session_resume"] = fresh_session_resume
                    process_payload["fresh_session_resume_reason_code"] = (
                        fresh_session_resume_reason_code
                    )
                    process_payload["session_index"] = session_index
                worker_runner_results.append(dict(runner_payload))
    else:
        _write_runtime_json(
            worker_root / "live_status.json",
            {
                "state": "completed",
                "reason_code": (
                    "resume_existing_outputs"
                    if resumed_output_path_by_shard_id
                    else "no_shards_assigned"
                ),
                "reason_detail": (
                    "all canonical line-role shard outputs were already durable on disk"
                    if resumed_output_path_by_shard_id
                    else "worker had no runnable canonical line-role shards"
                ),
                "retryable": False,
                "watchdog_policy": "workspace_worker_v1",
            },
        )

    for shard_index, shard in enumerate(valid_shards):
        shard_id = shard.shard_id
        input_path = in_dir / f"{shard_id}.json"
        debug_path = debug_dir / f"{shard_id}.json"
        repair_request_path = worker_root / "repair" / f"{shard_id}.json"
        repair_state_path = worker_root / "repair" / f"{shard_id}.status.json"
        output_path = out_dir / f"{shard_id}.json"
        current_task_file_missing = (
            session_run_result is not None
            and shard_id in runnable_shard_ids
            and not (worker_root / TASK_FILE_NAME).exists()
        )
        response_source_path = None
        if not current_task_file_missing:
            response_source_path = (
                output_path
                if output_path.exists()
                else resumed_output_path_by_shard_id.get(shard_id)
            )
        response_text: str | None = None
        if session_run_result is not None and shard_id in runnable_shard_ids:
            matching_rows = [
                row
                for row in stage_rows
                if str(row.get("runtime_shard_id") or "").strip() == shard_id
            ]
            primary_row = matching_rows[-1] if matching_rows else None
            primary_runner_row = primary_row
        else:
            primary_row = None
            primary_runner_row = None

        baseline_by_atomic_index = dict(
            deterministic_baseline_by_shard_id.get(shard_id) or {}
        )
        if response_source_path is not None and response_source_path.exists():
            response_text = response_source_path.read_text(encoding="utf-8")
            payload, validation_errors, validation_metadata, proposal_status = (
                _evaluate_line_role_response_with_pathology_guard(
                    shard=shard,
                    response_text=response_text,
                    validator=validator,
                    deterministic_baseline_by_atomic_index=baseline_by_atomic_index,
                )
            )
        else:
            payload, validation_errors, validation_metadata, proposal_status = (
                _evaluate_line_role_response_with_pathology_guard(
                    shard=shard,
                    response_text=None,
                    validator=validator,
                    deterministic_baseline_by_atomic_index=baseline_by_atomic_index,
                )
            )
        same_session_shard_status = dict(
            (
                dict(line_role_same_session_state_payload.get("shard_status_by_shard_id") or {})
                .get(shard_id)
                or {}
            )
        )
        watchdog_retry_attempted = False
        watchdog_retry_status = "not_attempted"
        repair_attempted = False
        repair_status = "not_attempted"
        raw_output_status = proposal_status
        final_validation_errors = tuple(validation_errors)
        final_validation_metadata = dict(validation_metadata or {})
        if (
            proposal_status == "missing_output"
            and not current_task_file_missing
            and same_session_shard_status.get("validation_errors")
        ):
            proposal_status = "invalid"
            raw_output_status = "invalid"
            final_validation_errors = tuple(
                str(error).strip()
                for error in (same_session_shard_status.get("validation_errors") or [])
                if str(error).strip()
            )
            final_validation_metadata = {
                **dict(final_validation_metadata or {}),
                "same_session_handoff_state": dict(same_session_shard_status),
                "same_session_handoff_incomplete": not bool(
                    line_role_same_session_state_payload.get("completed")
                ),
            }
        task_root = shard_dir / shard_id
        task_root.mkdir(parents=True, exist_ok=True)
        if primary_row is not None:
            primary_row["proposal_status"] = proposal_status
            _annotate_line_role_final_proposal_status(
                primary_row,
                final_proposal_status=proposal_status,
            )
            primary_row["runtime_shard_id"] = shard_id
            primary_row["runtime_parent_shard_id"] = shard_id
        if primary_runner_row is not None:
            primary_runner_row["proposal_status"] = proposal_status
            _annotate_line_role_final_proposal_status(
                primary_runner_row,
                final_proposal_status=proposal_status,
            )
            primary_runner_row["runtime_shard_id"] = shard_id
            primary_runner_row["runtime_parent_shard_id"] = shard_id
        if (
            shard_id in runnable_shard_ids
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
                shard=shard,
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
                shard_id=shard_id,
                run_result=watchdog_retry_run_result,
                model=model,
                reasoning_effort=reasoning_effort,
                prompt_input_mode="inline_watchdog_retry",
                events_path=task_root / "watchdog_retry_events.jsonl",
                last_message_path=task_root / "watchdog_retry_last_message.json",
                usage_path=task_root / "watchdog_retry_usage.json",
                live_status_path=watchdog_retry_live_status_path,
                workspace_manifest_path=task_root / "watchdog_retry_workspace_manifest.json",
            )
            watchdog_retry_runner_payload["process_payload"]["runtime_shard_id"] = shard_id
            watchdog_retry_runner_payload["process_payload"]["runtime_parent_shard_id"] = shard_id
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
                    shard=shard,
                    response_text=watchdog_retry_run_result.response_text,
                    validator=validator,
                    deterministic_baseline_by_atomic_index=dict(
                        deterministic_baseline_by_shard_id.get(shard_id) or {}
                    ),
                )
            )
            watchdog_retry_status = (
                "recovered"
                if watchdog_retry_payload is not None
                and watchdog_retry_proposal_status == "validated"
                else "failed"
            )
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
                watchdog_retry_primary_row["runtime_shard_id"] = shard_id
                watchdog_retry_primary_row["runtime_parent_shard_id"] = shard_id
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
                watchdog_retry_primary_runner_row["runtime_shard_id"] = shard_id
                watchdog_retry_primary_runner_row["runtime_parent_shard_id"] = shard_id
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
                raw_output_status = watchdog_retry_proposal_status
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
        row_resolution_payload, row_resolution_metadata = _build_line_role_row_resolution(
            shard=shard,
            validation_metadata=final_validation_metadata,
        )
        payload = row_resolution_payload
        proposal_status = "validated" if row_resolution_payload is not None else "invalid"
        if same_session_shard_status:
            repair_attempted = bool(same_session_shard_status.get("repair_attempted"))
            repair_status = (
                str(same_session_shard_status.get("repair_status") or "").strip()
                or repair_status
            )
        elif repair_attempted:
            repair_status = "repaired" if proposal_status == "validated" else "failed"
        if primary_row is not None:
            primary_row["repair_attempted"] = repair_attempted
            primary_row["repair_status"] = repair_status
        if primary_runner_row is not None:
            primary_runner_row["repair_attempted"] = repair_attempted
            primary_runner_row["repair_status"] = repair_status
        final_validation_metadata = {
            **dict(final_validation_metadata or {}),
            "raw_output_status": raw_output_status,
            "raw_output_invalid": raw_output_status != "validated",
            "raw_output_missing": raw_output_status == "missing_output",
            "task_file_missing_after_worker_session": current_task_file_missing,
            "row_resolution": dict(row_resolution_metadata),
            **(
                {"fresh_session_recovery": dict(fresh_session_recovery_metadata)}
                if fresh_session_recovery_metadata
                else {}
            ),
        }
        _write_runtime_json(
            task_root / "repair_status.json",
            {
                "repair_attempted": repair_attempted,
                "status": repair_status,
                "repair_status": repair_status,
                "repair_request_path": (
                    _relative_runtime_path(run_root, repair_request_path)
                    if repair_request_path.exists()
                    else None
                ),
                "repair_state_path": (
                    _relative_runtime_path(run_root, repair_state_path)
                    if repair_state_path.exists()
                    else None
                ),
                "output_path": _relative_runtime_path(run_root, output_path),
                "validation_errors": list(final_validation_errors),
                "row_resolution": dict(row_resolution_metadata),
            },
        )
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
        task_status_rows.append(
            _build_line_role_shard_status_row(
                shard=shard,
                worker_id=assignment.worker_id,
                state=(
                    "repair_recovered"
                    if proposal_status == "validated" and repair_status == "repaired"
                    else (
                        "validated"
                        if proposal_status == "validated"
                        else (
                            "repair_failed"
                            if repair_attempted
                            else "invalid_output"
                        )
                    )
                ),
                last_attempt_type=(
                    "repair"
                    if repair_attempted
                    else (
                        "fresh_session_recovery"
                        if bool(
                            fresh_session_recovery_metadata.get(
                                "fresh_session_recovery_attempted"
                            )
                        )
                        else (
                        "watchdog_retry"
                        if watchdog_retry_attempted
                        else (
                            "resume_existing_output"
                            if shard_id in resumed_output_path_by_shard_id
                            and shard_id not in runnable_shard_ids
                            else "main_worker"
                        )
                        )
                    )
                ),
                output_path=response_source_path,
                repair_path=None,
                validation_errors=final_validation_errors,
                validation_metadata=final_validation_metadata,
                row_resolution_metadata=row_resolution_metadata,
                repair_attempted=repair_attempted,
                repair_status=repair_status,
                resumed_from_existing_output=(
                    shard_id in resumed_output_path_by_shard_id
                    and shard_id not in runnable_shard_ids
                ),
                fresh_session_recovery_metadata=fresh_session_recovery_metadata,
            )
        )
        normalized_outcome = _normalize_line_role_shard_outcome(
            run_result=session_run_result,
            proposal_status=proposal_status,
            watchdog_retry_status=watchdog_retry_status,
            repair_status=repair_status,
            resumed_from_existing_outputs=(
                shard_id in resumed_output_path_by_shard_id
                and shard_id not in runnable_shard_ids
            ),
            row_resolution_metadata=row_resolution_metadata,
            fresh_session_recovery_metadata=fresh_session_recovery_metadata,
        )
        shard_root = shard_dir / shard.shard_id
        if session_run_result is None and not (shard_root / "live_status.json").exists():
            _write_runtime_json(
                shard_root / "live_status.json",
                {
                    "state": "completed",
                    "reason_code": (
                        "resume_existing_outputs"
                        if shard_id in resumed_output_path_by_shard_id
                        else "no_shards_assigned"
                    ),
                    "reason_detail": (
                        "all canonical line-role shard outputs were already durable on disk"
                        if shard_id in resumed_output_path_by_shard_id
                        else "worker had no runnable canonical line-role shards"
                    ),
                    "retryable": False,
                    "watchdog_policy": "workspace_worker_v1",
                },
            )
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        valid = payload is not None and proposal_status == "validated"
        _write_runtime_json(
            proposal_path,
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": payload if valid else None,
                "validation_errors": list(final_validation_errors),
                "validation_metadata": dict(final_validation_metadata or {}),
                "watchdog_retry_attempted": watchdog_retry_attempted,
                "watchdog_retry_status": watchdog_retry_status,
                "repair_attempted": repair_attempted,
                "repair_status": repair_status,
                **dict(fresh_session_recovery_metadata),
            },
        )
        _write_runtime_json(
            shard_root / "proposal.json",
            payload
            if valid
            else {
                "error": proposal_status,
                "validation_errors": list(final_validation_errors),
                "validation_metadata": dict(final_validation_metadata or {}),
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
                repair_attempted=repair_attempted,
                repair_status=repair_status,
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
                repair_attempted=repair_attempted,
                repair_status=repair_status,
            )
        _write_runtime_json(
            shard_root / "status.json",
            {
                "status": proposal_status,
                "validation_errors": list(final_validation_errors),
                "validation_metadata": dict(final_validation_metadata or {}),
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "watchdog_retry_attempted": watchdog_retry_attempted,
                "watchdog_retry_status": watchdog_retry_status,
                "repair_attempted": repair_attempted,
                "repair_status": repair_status,
                **dict(fresh_session_recovery_metadata),
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
        if fresh_session_recovery_metadata:
            shard_runner_payload.update(dict(fresh_session_recovery_metadata))
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
                    "validation_errors": list(final_validation_errors),
                    "state": shard_state,
                    "reason_code": shard_reason_code,
                    **dict(fresh_session_recovery_metadata),
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
                validation_errors=tuple(final_validation_errors),
                metadata=dict(final_validation_metadata or {}),
            )
        )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    worker_runner_payload = _aggregate_line_role_worker_runner_payload(
        pipeline_id=pipeline_id,
        worker_runs=worker_runner_results,
    )
    worker_runner_payload["fresh_session_retry_count"] = fresh_session_retry_count
    worker_runner_payload["fresh_session_retry_status"] = fresh_session_retry_status
    if fresh_session_recovery_metadata:
        worker_runner_payload.update(dict(fresh_session_recovery_metadata))
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
                "task_file_guardrail": dict(task_file_guardrail or {}),
                "fresh_session_retry_count": fresh_session_retry_count,
                "fresh_session_retry_status": fresh_session_retry_status,
                **dict(fresh_session_recovery_metadata),
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
    settings: Mapping[str, Any],
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
        settings=settings,
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
        "shard_status": "shard_status.jsonl",
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
    _write_runtime_jsonl(
        run_root / artifacts["shard_manifest"],
        [_line_role_asdict(shard) for shard in shards],
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
        assignment.worker_id: tuple(assignment.shard_ids)
        for assignment in assignments
    }
    total_tasks = sum(len(task_ids) for task_ids in task_ids_by_worker.values())
    progress_lock = threading.Lock()
    cohort_watchdog_state = _LineRoleCohortWatchdogState()
    pending_shards_by_worker = {
        assignment.worker_id: list(assignment.shard_ids)
        for assignment in assignments
    }
    worker_roots_by_id = {
        assignment.worker_id: run_root / "workers" / assignment.worker_id
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
            repair_request_path = (
                run_root / "workers" / worker_id / "repair" / f"{task_id}.json"
            )
            repair_state_path = (
                run_root / "workers" / worker_id / "repair" / f"{task_id}.status.json"
            )
            repair_state = {}
            if repair_state_path.exists():
                try:
                    loaded_state = json.loads(
                        repair_state_path.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError):
                    loaded_state = None
                if isinstance(loaded_state, Mapping):
                    repair_state = dict(loaded_state)
            repair_state_status = str(repair_state.get("status") or "").strip().lower()
            if repair_request_path.exists() or repair_state_path.exists():
                repair_attempted += 1
            if repair_state_status == "installed_clean":
                repair_completed += 1
            elif repair_request_path.exists() or repair_state_status in {
                "requested",
                "validated_clean",
            }:
                repair_running += 1
        return repair_attempted, repair_completed, repair_running

    def _render_line_role_progress_label(
        *,
        worker_id: str,
        completed_shard_ids: set[str],
    ) -> str | None:
        worker_shard_ids = task_ids_by_worker.get(worker_id, ())
        if not worker_shard_ids:
            return None
        completed_worker_shards = sum(
            1 for shard_id in worker_shard_ids if shard_id in completed_shard_ids
        )
        if completed_worker_shards >= len(worker_shard_ids):
            return None
        pending_shards = pending_shards_by_worker.get(worker_id) or []
        base_label = str((pending_shards[0] if pending_shards else worker_shard_ids[0]) or "").strip() or worker_id
        extra_shard_count = max(0, len(pending_shards) - 1)
        if extra_shard_count > 0:
            base_label = f"{base_label} +{extra_shard_count} more"
        return f"{base_label} ({completed_worker_shards}/{len(worker_shard_ids)} shards)"

    def _emit_progress_locked(*, force: bool = False) -> None:
        worker_health = summarize_workspace_worker_health(
            worker_roots_by_id=worker_roots_by_id,
        )
        completed_shard_ids: set[str] = set()
        for assignment in assignments:
            out_dir = run_root / "workers" / assignment.worker_id / "out"
            if not out_dir.exists():
                continue
            for output_path in out_dir.glob("*.json"):
                completed_shard_ids.add(output_path.stem)
        completed_tasks = min(total_tasks, len(completed_shard_ids))
        active_tasks = [
            label
            for assignment in assignments
            for label in [
                decorate_active_worker_label(
                    _render_line_role_progress_label(
                        worker_id=assignment.worker_id,
                        completed_shard_ids=completed_shard_ids,
                    ),
                    worker_health.live_activity_summary_by_worker_id.get(
                        assignment.worker_id
                    ),
                    worker_health.attention_suffix_by_worker_id.get(assignment.worker_id),
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
                task_id not in completed_shard_ids
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
            worker_health.warning_worker_count,
            worker_health.stalled_worker_count,
            tuple(worker_health.attention_lines),
            worker_health.last_activity_at,
        )
        if not force and snapshot == getattr(_emit_progress_locked, "_last_snapshot", None):
            return
        setattr(_emit_progress_locked, "_last_snapshot", snapshot)
        detail_lines = []
        if worker_health.warning_worker_count > 0:
            detail_lines.append(
                f"watchdog warnings: {worker_health.warning_worker_count}"
            )
        if worker_health.stalled_worker_count > 0:
            detail_lines.append(
                f"stalled workers: {worker_health.stalled_worker_count}"
            )
        if worker_health.attention_lines:
            detail_lines.append(
                "attention: " + "; ".join(worker_health.attention_lines)
            )
        _notify_line_role_progress(
            progress_callback=progress_callback,
            completed_units=completed_tasks,
            total_units=total_tasks,
            work_unit_label="shard",
            running_units=running_workers,
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
            last_activity_at=worker_health.last_activity_at,
            active_tasks=active_tasks,
            detail_lines=detail_lines,
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

    def _heartbeat_emit() -> None:
        with progress_lock:
            _emit_progress_locked()

    heartbeat_stop_event: threading.Event | None = None
    heartbeat_thread: threading.Thread | None = None
    if progress_callback is not None and assignments:
        heartbeat_stop_event, heartbeat_thread = start_workspace_worker_progress_heartbeat(
            emit_progress=_heartbeat_emit,
            thread_name="line-role-progress-heartbeat",
        )

    try:
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
                    settings=settings,
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
    finally:
        if heartbeat_stop_event is not None:
            heartbeat_stop_event.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=2.0)
    if progress_callback is not None and total_tasks > 0:
        with progress_lock:
            _emit_progress_locked(force=True)

    _write_runtime_jsonl(run_root / artifacts["shard_status"], task_status_rows)

    llm_authoritative_row_count = sum(
        int(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("llm_authoritative_row_count") or 0)
        for row in task_status_rows
        if isinstance(row, dict)
    )
    unresolved_row_count = sum(
        int(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("unresolved_row_count") or 0)
        for row in task_status_rows
        if isinstance(row, dict)
    )
    suspicious_shard_count = sum(
        1
        for row in task_status_rows
        if bool(((row.get("metadata") or {}) if isinstance(row, dict) else {}).get("suspicious_shard"))
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
        "shard_state_counts": {
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
        "unresolved_row_count": unresolved_row_count,
        "suspicious_shard_count": suspicious_shard_count,
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
    task_file_guardrails = summarize_task_file_guardrails(
        [
            (
                dict(report.metadata or {}).get("task_file_guardrail")
                if isinstance(report.metadata, Mapping)
                else None
            )
            for report in worker_reports
        ]
    )
    worker_session_guardrails = build_worker_session_guardrails(
        planned_happy_path_worker_cap=len(assignments) * 2,
        actual_happy_path_worker_sessions=int(
            telemetry["summary"].get("workspace_worker_session_count") or 0
        ),
    )
    telemetry["summary"]["task_file_guardrails"] = task_file_guardrails
    telemetry["summary"]["worker_session_guardrails"] = worker_session_guardrails
    telemetry["summary"]["planned_happy_path_worker_cap"] = int(
        worker_session_guardrails["planned_happy_path_worker_cap"]
    )
    telemetry["summary"]["actual_happy_path_worker_sessions"] = int(
        worker_session_guardrails["actual_happy_path_worker_sessions"]
    )
    _write_runtime_json(run_root / artifacts["promotion_report"], promotion_report)
    _write_runtime_json(run_root / artifacts["telemetry"], telemetry)
    _write_runtime_json(run_root / artifacts["failures"], failures)

    runtime_metadata_payload = {
        **dict(runtime_metadata or {}),
        "task_file_guardrails": task_file_guardrails,
        "worker_session_guardrails": worker_session_guardrails,
        "fresh_session_retry_count": sum(
            int(dict(report.metadata or {}).get("fresh_session_retry_count") or 0)
            for report in worker_reports
        ),
    }
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
        runtime_metadata=runtime_metadata_payload,
    )
    _write_runtime_json(run_root / artifacts["phase_manifest"], _line_role_asdict(manifest))
    if bool(worker_session_guardrails.get("cap_exceeded")):
        raise LineRoleRepairFailureError(
            "Canonical line-role happy-path worker sessions exceeded the planned cap: "
            f"planned={worker_session_guardrails['planned_happy_path_worker_cap']} "
            f"actual={worker_session_guardrails['actual_happy_path_worker_sessions']}."
        )
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




def _build_line_role_workspace_task_runner_payload(
    *,
    pipeline_id: str,
    worker_id: str,
    shard_id: str,
    runtime_shard_id: str,
    run_result: CodexExecRunResult,
    model: str | None,
    reasoning_effort: str | None,
    request_input_file: Path | None,
    debug_input_file: Path | None,
    worker_prompt_path: Path | None,
    worker_root: Path,
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
        token_total_shares = _distribute_line_role_session_value(
            _safe_int_value(row_payload.get("tokens_total")),
            task_count,
        )
        token_components = (
            _safe_int_value(row_payload.get("tokens_input")),
            _safe_int_value(row_payload.get("tokens_cached_input")),
            _safe_int_value(row_payload.get("tokens_output")),
            _safe_int_value(row_payload.get("tokens_reasoning")),
        )
        row_payload["tokens_total"] = (
            sum(int(value) for value in token_components)
            if all(value is not None for value in token_components)
            else token_total_shares[task_index]
        )
        row_payload["prompt_input_mode"] = "workspace_worker"
        row_payload["runtime_shard_id"] = runtime_shard_id
        row_payload["runtime_parent_shard_id"] = shard_id
        row_payload["request_input_file"] = request_input_file_str
        row_payload["request_input_file_bytes"] = request_input_file_bytes
        row_payload["debug_input_file"] = debug_input_file_str
        row_payload["worker_prompt_file"] = worker_prompt_file_str
        row_payload["worker_session_shard_count"] = task_count
        row_payload["worker_session_primary_row"] = task_index == 0
        row_payload["command_execution_policy_counts"] = _line_role_command_policy_counts(
            row_payload.get("command_execution_commands")
        )
        row_payload["command_execution_policy_by_command"] = _line_role_command_policy_by_command(
            row_payload.get("command_execution_commands")
        )
        row_payload["events_path"] = str(worker_root / "events.jsonl")
        row_payload["last_message_path"] = str(worker_root / "last_message.json")
        row_payload["usage_path"] = str(worker_root / "usage.json")
        row_payload["live_status_path"] = str(worker_root / "live_status.json")
        row_payload["workspace_manifest_path"] = str(worker_root / "workspace_manifest.json")
        row_payload["stdout_path"] = str(worker_root / "stdout.txt")
        row_payload["stderr_path"] = str(worker_root / "stderr.txt")
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
        "runtime_shard_id": runtime_shard_id,
        "runtime_parent_shard_id": shard_id,
        "request_input_file": request_input_file_str,
        "request_input_file_bytes": request_input_file_bytes,
        "debug_input_file": debug_input_file_str,
        "worker_prompt_file": worker_prompt_file_str,
        "events_path": str(worker_root / "events.jsonl"),
        "last_message_path": str(worker_root / "last_message.json"),
        "usage_path": str(worker_root / "usage.json"),
        "live_status_path": str(worker_root / "live_status.json"),
        "workspace_manifest_path": str(worker_root / "workspace_manifest.json"),
        "stdout_path": str(worker_root / "stdout.txt"),
        "stderr_path": str(worker_root / "stderr.txt"),
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
    same_session_state_path: Path | None = None,
    cohort_watchdog_state: _LineRoleCohortWatchdogState | None = None,
    shard_id: str | None = None,
    watchdog_policy: str = _STRICT_JSON_WATCHDOG_POLICY,
    allow_workspace_commands: bool = False,
    expected_workspace_output_paths: Sequence[Path] | None = None,
    workspace_completion_quiescence_seconds: float | None = None,
    final_message_missing_output_grace_seconds: float | None = None,
) -> Callable[[CodexExecLiveSnapshot], CodexExecSupervisionDecision | None]:
    target_paths: list[Path] = []
    if live_status_path is not None:
        target_paths.append(live_status_path)
    if live_status_paths is not None:
        target_paths.extend(Path(path) for path in live_status_paths)
    completion_quiescence_seconds = float(
        workspace_completion_quiescence_seconds
        if workspace_completion_quiescence_seconds is not None
        else _LINE_ROLE_WORKSPACE_COMPLETION_QUIESCENCE_SECONDS
    )
    missing_output_grace_seconds = float(
        final_message_missing_output_grace_seconds
        if final_message_missing_output_grace_seconds is not None
        else _LINE_ROLE_FINAL_MESSAGE_MISSING_OUTPUT_GRACE_SECONDS
    )
    last_complete_workspace_signature: tuple[tuple[str, int, int], ...] | None = None
    workspace_output_stable_passes = 0
    completion_wait_started_elapsed_seconds: float | None = None
    completion_wait_agent_message_count: int | None = None
    completion_wait_turn_completed_count: int | None = None
    final_message_missing_output_started_elapsed_seconds: float | None = None
    final_message_missing_output_deadline_elapsed_seconds: float | None = None
    persistent_warning_codes: list[str] = []
    persistent_warning_details: list[str] = []
    last_single_file_command_count = 0

    def _record_warning(code: str, detail: str) -> None:
        if code not in persistent_warning_codes:
            persistent_warning_codes.append(code)
        if detail and detail not in persistent_warning_details:
            persistent_warning_details.append(detail)

    def _callback(snapshot: CodexExecLiveSnapshot) -> CodexExecSupervisionDecision | None:
        nonlocal last_complete_workspace_signature
        nonlocal workspace_output_stable_passes
        nonlocal completion_wait_started_elapsed_seconds
        nonlocal completion_wait_agent_message_count
        nonlocal completion_wait_turn_completed_count
        nonlocal final_message_missing_output_started_elapsed_seconds
        nonlocal final_message_missing_output_deadline_elapsed_seconds
        nonlocal last_single_file_command_count
        decision: CodexExecSupervisionDecision | None = None
        command_execution_tolerated = False
        last_command_verdict = _classify_line_role_workspace_command(
            snapshot.last_command,
            single_file_worker_policy=allow_workspace_commands,
        )
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
        same_session_completion = _summarize_line_role_same_session_completion(
            same_session_state_path
        )
        authoritative_same_session_success = bool(
            allow_workspace_commands
            and same_session_completion.get("same_session_completed")
            and str(same_session_completion.get("same_session_final_status") or "").strip()
            == "completed"
        )
        if workspace_output_status["complete"]:
            current_signature = tuple(workspace_output_status["signature"])
            if current_signature == last_complete_workspace_signature:
                workspace_output_stable_passes += 1
            else:
                last_complete_workspace_signature = current_signature
                workspace_output_stable_passes = 1
                completion_wait_started_elapsed_seconds = None
                completion_wait_agent_message_count = None
                completion_wait_turn_completed_count = None
        else:
            last_complete_workspace_signature = None
            workspace_output_stable_passes = 0
            completion_wait_started_elapsed_seconds = None
            completion_wait_agent_message_count = None
            completion_wait_turn_completed_count = None
        final_message_missing_output_grace_active = False
        final_message_missing_output_deadline_reached = False
        completion_waiting_for_exit = False
        completion_post_signal_observed = False
        if snapshot.command_execution_count > 0:
            if decision is None and allow_workspace_commands:
                if not last_command_verdict.allowed or last_command_boundary_violation is not None:
                    decision = CodexExecSupervisionDecision.terminate(
                        reason_code="boundary_command_execution_forbidden",
                        reason_detail=format_watchdog_command_reason_detail(
                            stage_label="workspace worker stage",
                            last_command=snapshot.last_command,
                        ),
                        retryable=False,
                        supervision_state="boundary_interrupted",
                    )
                else:
                    command_execution_tolerated = True
        authoritative_completion_ready = bool(
            authoritative_same_session_success and workspace_output_status["complete"]
        )
        if decision is None and authoritative_completion_ready:
            completion_waiting_for_exit = True
            if completion_wait_started_elapsed_seconds is None:
                completion_wait_started_elapsed_seconds = snapshot.elapsed_seconds
                completion_wait_agent_message_count = snapshot.agent_message_count
                completion_wait_turn_completed_count = snapshot.turn_completed_count
            completion_post_signal_observed = (
                snapshot.agent_message_count > int(completion_wait_agent_message_count or 0)
                or snapshot.turn_completed_count > int(completion_wait_turn_completed_count or 0)
            )
            completion_wait_elapsed_seconds = (
                snapshot.elapsed_seconds
                - float(completion_wait_started_elapsed_seconds or 0.0)
            )
            completion_quiescence_reached = (
                completion_wait_elapsed_seconds
                >= completion_quiescence_seconds
                and (
                    snapshot.last_event_seconds_ago is None
                    or snapshot.last_event_seconds_ago
                    >= completion_quiescence_seconds
                    or workspace_output_stable_passes >= 2
                )
            )
            if completion_post_signal_observed or completion_quiescence_reached:
                decision = CodexExecSupervisionDecision.terminate(
                    reason_code="",
                    reason_detail=(
                        "canonical line-role same-session helper already completed "
                        "and repo-owned shard outputs are durable"
                    ),
                    retryable=False,
                    supervision_state="completed",
                )
        if snapshot.command_execution_count > 0:
            if decision is None and allow_workspace_commands:
                new_command_observed = (
                    int(snapshot.command_execution_count or 0) > last_single_file_command_count
                )
                if new_command_observed:
                    last_single_file_command_count = int(snapshot.command_execution_count or 0)
                if (
                    decision is None
                    and new_command_observed
                    and is_single_file_workspace_command_drift_policy(
                        last_command_verdict.policy
                    )
                ):
                    drift_detail = str(last_command_verdict.reason or "").strip() or (
                        "single-file worker drifted off the helper-first task-file contract"
                    )
                    _record_warning("single_file_shell_drift", drift_detail)
                if (
                    decision is None
                    and should_terminate_workspace_command_loop(
                        snapshot=snapshot,
                        max_command_count=_LINE_ROLE_WORKSPACE_MAX_COMMAND_COUNT,
                        max_repeat_count=_LINE_ROLE_WORKSPACE_MAX_REPEAT_COUNT,
                    )
                ):
                    _record_warning(
                        "command_loop_without_output",
                        format_watchdog_command_loop_reason_detail(
                            stage_label="workspace worker stage",
                            snapshot=snapshot,
                        ),
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
            if allow_workspace_commands:
                _record_warning(
                    "reasoning_without_output",
                    "workspace worker emitted repeated reasoning without a final answer",
                )
            else:
                decision = CodexExecSupervisionDecision.terminate(
                    reason_code="watchdog_reasoning_without_output",
                    reason_detail="strict JSON stage emitted repeated reasoning without a final answer",
                    retryable=True,
                )
        elif (
            cohort_completed_successful_shards >= _LINE_ROLE_COHORT_WATCHDOG_MIN_COMPLETED_SHARDS
            and int(cohort_median_duration_ms or 0) > 0
            and (snapshot.elapsed_seconds * 1000.0)
            >= _runtime_attr(
                "_LINE_ROLE_COHORT_WATCHDOG_MIN_ELAPSED_MS",
                _LINE_ROLE_COHORT_WATCHDOG_MIN_ELAPSED_MS,
            )
            and (snapshot.elapsed_seconds * 1000.0)
            >= (
                float(cohort_median_duration_ms)
                * _runtime_attr(
                    "_LINE_ROLE_COHORT_WATCHDOG_MEDIAN_FACTOR",
                    _LINE_ROLE_COHORT_WATCHDOG_MEDIAN_FACTOR,
                )
            )
            and not snapshot.has_final_agent_message
        ):
            if allow_workspace_commands:
                _record_warning(
                    "cohort_runtime_outlier",
                    "workspace worker exceeded sibling median runtime without reaching final output",
                )
            else:
                decision = CodexExecSupervisionDecision.terminate(
                    reason_code="watchdog_cohort_runtime_outlier",
                    reason_detail=(
                        "strict JSON stage exceeded sibling median runtime without reaching final output"
                    ),
                    retryable=True,
                )
        if (
            decision is None
            and allow_workspace_commands
            and int(workspace_output_status["expected_count"] or 0) > 0
            and snapshot.has_final_agent_message
            and not authoritative_same_session_success
            and not workspace_output_status["complete"]
        ):
            if final_message_missing_output_started_elapsed_seconds is None:
                final_message_missing_output_started_elapsed_seconds = snapshot.elapsed_seconds
                final_message_missing_output_deadline_elapsed_seconds = (
                    snapshot.elapsed_seconds + missing_output_grace_seconds
                )
            final_message_missing_output_grace_active = True
            final_message_missing_output_deadline_reached = (
                final_message_missing_output_deadline_elapsed_seconds is not None
                and snapshot.elapsed_seconds
                >= final_message_missing_output_deadline_elapsed_seconds
            )
            if final_message_missing_output_deadline_reached:
                missing_files = ", ".join(workspace_output_status["missing_files"]) or "[unknown]"
                decision = CodexExecSupervisionDecision.terminate(
                    reason_code="workspace_final_message_missing_output",
                    reason_detail=(
                        "workspace worker emitted a final agent message but the required output files "
                        f"were still missing after {missing_output_grace_seconds:.1f} "
                        f"seconds: {missing_files}"
                    ),
                    retryable=True,
                    supervision_state="watchdog_killed",
                )
        else:
            final_message_missing_output_started_elapsed_seconds = None
            final_message_missing_output_deadline_elapsed_seconds = None
        status_payload = {
            "state": (
                str(decision.supervision_state or "boundary_interrupted").strip()
                if isinstance(decision, CodexExecSupervisionDecision)
                and decision.action == "terminate"
                else "running_with_warnings"
                if persistent_warning_codes
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
            "live_activity_summary": snapshot.live_activity_summary,
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
            **same_session_completion,
            "workspace_authoritative_completion_ready": authoritative_completion_ready,
            "final_message_missing_output_grace_active": (
                final_message_missing_output_grace_active
            ),
            "final_message_missing_output_started_at_elapsed_seconds": (
                round(final_message_missing_output_started_elapsed_seconds, 3)
                if final_message_missing_output_started_elapsed_seconds is not None
                else None
            ),
            "final_message_missing_output_grace_seconds": (
                missing_output_grace_seconds
                if final_message_missing_output_grace_active
                else None
            ),
            "final_message_missing_output_deadline_elapsed_seconds": (
                round(final_message_missing_output_deadline_elapsed_seconds, 3)
                if final_message_missing_output_deadline_elapsed_seconds is not None
                else None
            ),
            "final_message_missing_output_deadline_reached": (
                final_message_missing_output_deadline_reached
            ),
            "workspace_completion_waiting_for_exit": completion_waiting_for_exit,
            "workspace_completion_quiescence_seconds": (
                completion_quiescence_seconds
                if completion_waiting_for_exit
                else None
            ),
            "workspace_completion_post_signal_observed": completion_post_signal_observed,
            "workspace_command_loop_max_count": _LINE_ROLE_WORKSPACE_MAX_COMMAND_COUNT,
            "workspace_command_loop_max_repeat_count": _LINE_ROLE_WORKSPACE_MAX_REPEAT_COUNT,
            "warning_codes": list(persistent_warning_codes),
            "warning_details": list(persistent_warning_details),
            "warning_count": len(persistent_warning_codes),
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
    *,
    single_file_worker_policy: bool = False,
) -> WorkspaceCommandClassification:
    return classify_workspace_worker_command(
        command_text,
        single_file_worker_policy=single_file_worker_policy,
    )


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
    existing_payload = _load_live_status(live_status_path)
    state = run_result.supervision_state or "completed"
    if state == "completed" and existing_payload.get("warning_count"):
        state = "completed_with_warnings"
    _write_runtime_json(
        live_status_path,
        {
            "state": state,
            "reason_code": run_result.supervision_reason_code,
            "reason_detail": run_result.supervision_reason_detail,
            "retryable": run_result.supervision_retryable,
            "duration_ms": run_result.duration_ms,
            "started_at_utc": run_result.started_at_utc,
            "finished_at_utc": run_result.finished_at_utc,
            "watchdog_policy": watchdog_policy,
            "warning_codes": list(existing_payload.get("warning_codes") or []),
            "warning_details": list(existing_payload.get("warning_details") or []),
            "warning_count": int(existing_payload.get("warning_count") or 0),
        },
    )


def _load_live_status(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


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
            "all canonical line-role shard outputs were already durable on disk",
        )
    return (
        "no_tasks_assigned",
        "worker had no runnable canonical line-role shards",
    )




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
    allowed_labels = ", ".join(CANONICAL_LINE_ROLE_ALLOWED_LABELS)
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
        "- Treat span codes and hint lists as weak hints only, not final truth.\n"
        "- `INGREDIENT_LINE` means quantity/unit ingredients or bare ingredient-list items.\n"
        "- `INSTRUCTION_LINE` means a recipe-local procedural step, not generic cooking advice.\n"
        "- `HOWTO_SECTION` means a recipe-internal subsection heading, not a chapter or topic heading.\n"
        "- `RECIPE_NOTES` means recipe-local prose that belongs with the current recipe.\n"
        "- `NONRECIPE_CANDIDATE` means outside-recipe material that should go to knowledge later.\n"
        "- `NONRECIPE_EXCLUDE` means obvious outside-recipe junk that should never go to knowledge.\n\n"
        f"Previous stop reason: {original_reason_code or '[unknown]'}\n"
        f"Reason detail: {original_reason_detail or '[none recorded]'}\n\n"
        "Authoritative shard rows to relabel (each row is [atomic_index, current_line]):\n"
        "<BEGIN_AUTHORITATIVE_ROWS>\n"
        f"{authoritative_rows}\n"
        "<END_AUTHORITATIVE_ROWS>\n\n"
        "Recompute the full shard from those rows. Do not copy sibling examples verbatim.\n\n"
        "Successful sibling examples:\n"
        "<BEGIN_SUCCESSFUL_SIBLING_EXAMPLES>\n"
        f"{examples_block}\n"
        "<END_SUCCESSFUL_SIBLING_EXAMPLES>\n"
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
            row_payload["events_path"] = str(events_path) if events_path is not None else None
            row_payload["last_message_path"] = (
                str(last_message_path) if last_message_path is not None else None
            )
            row_payload["usage_path"] = str(usage_path) if usage_path is not None else None
            row_payload["live_status_path"] = (
                str(live_status_path) if live_status_path is not None else None
            )
            row_payload["workspace_manifest_path"] = (
                str(workspace_manifest_path)
                if workspace_manifest_path is not None
                else None
            )
            row_payload["stdout_path"] = str(stdout_path) if stdout_path is not None else None
            row_payload["stderr_path"] = str(stderr_path) if stderr_path is not None else None
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
        "events_path": str(events_path) if events_path is not None else None,
        "last_message_path": str(last_message_path) if last_message_path is not None else None,
        "usage_path": str(usage_path) if usage_path is not None else None,
        "live_status_path": str(live_status_path) if live_status_path is not None else None,
        "workspace_manifest_path": (
            str(workspace_manifest_path) if workspace_manifest_path is not None else None
        ),
        "stdout_path": str(stdout_path) if stdout_path is not None else None,
        "stderr_path": str(stderr_path) if stderr_path is not None else None,
    }
    return payload


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
                    if not _line_role_usage_present(attempt_usage):
                        attempt_usage = None
            batch_payloads.append(
                {
                    "prompt_index": plan.prompt_index,
                    "shard_id": plan.shard_id,
                    "candidate_count": len(plan.candidates),
                    "requested_atomic_indices": [
                        int(candidate.atomic_index) for candidate in plan.candidates
                    ],
                    "attempt_count": len(matching_rows) or 1,
                    "attempts_with_usage": 1 if _line_role_usage_present(attempt_usage) else 0,
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
                        1 for row in telemetry_rows if _line_role_usage_present(row)
                    ),
                    "attempts_without_usage": max(
                        0,
                        (len(telemetry_rows) or len(phase_result.shard_plans))
                        - sum(1 for row in telemetry_rows if _line_role_usage_present(row)),
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
                "pipeline": LINE_ROLE_PIPELINE_ROUTE_V2,
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
                        1 for row in all_rows if _line_role_usage_present(row)
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
                        - sum(1 for row in all_rows if _line_role_usage_present(row)),
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
