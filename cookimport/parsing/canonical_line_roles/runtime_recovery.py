from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.llm.codex_exec_runner import (
    CodexExecLiveSnapshot,
    CodexExecRecentCommandCompletion,
    CodexExecRunResult,
    _summarize_live_codex_events,
)
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.llm.editable_task_file import (
    TASK_FILE_NAME,
    load_task_file,
    validate_edited_task_file,
    write_task_file,
)

from .planning import _build_line_role_taskfile_prompt
from .same_session_handoff import (
    describe_line_role_same_session_doctor,
    describe_line_role_same_session_status,
    initialize_line_role_same_session_state,
)
from . import (
    ShardManifestEntryV1,
    WorkerAssignmentV1,
    _STRICT_JSON_WATCHDOG_POLICY,
    _write_runtime_json,
)


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


def _line_role_same_session_helper_completion_from_snapshot(
    snapshot: CodexExecLiveSnapshot,
) -> dict[str, Any]:
    command = _line_role_completed_same_session_helper_command(
        last_completed_stage_helper_command=snapshot.last_completed_stage_helper_command,
        last_completed_command=snapshot.last_completed_command,
    )
    if command is None:
        return {
            "helper_completed_in_event_stream": False,
            "helper_completion_command": None,
            "helper_completion_exit_code": None,
            "helper_completion_status": None,
            "helper_completion_final_status": None,
            "helper_completion_parsed_output": None,
        }
    return {
        "helper_completed_in_event_stream": True,
        "helper_completion_command": command.command,
        "helper_completion_exit_code": command.exit_code,
        "helper_completion_status": command.status,
        "helper_completion_final_status": command.reported_final_status,
        "helper_completion_parsed_output": dict(command.parsed_output or {}),
    }


def _line_role_same_session_helper_command_completed(
    command: CodexExecRecentCommandCompletion | None,
) -> bool:
    return bool(
        command is not None
        and str(command.python_module or "").strip()
        == "cookimport.parsing.canonical_line_roles.same_session_handoff"
        and command.exit_code == 0
        and (
            command.reported_completed
            or str(command.reported_final_status or "").strip() == "completed"
        )
    )


def _line_role_completed_same_session_helper_command(
    *,
    last_completed_stage_helper_command: CodexExecRecentCommandCompletion | None,
    last_completed_command: CodexExecRecentCommandCompletion | None,
) -> CodexExecRecentCommandCompletion | None:
    if _line_role_same_session_helper_command_completed(
        last_completed_stage_helper_command
    ):
        return last_completed_stage_helper_command
    if _line_role_same_session_helper_command_completed(last_completed_command):
        return last_completed_command
    return None


def _line_role_same_session_helper_completed_in_events(
    run_result: CodexExecRunResult,
) -> bool:
    live_summary = _summarize_live_codex_events(run_result.events)
    return (
        _line_role_completed_same_session_helper_command(
            last_completed_stage_helper_command=live_summary.get(
                "last_completed_stage_helper_command"
            ),
            last_completed_command=live_summary.get("last_completed_command"),
        )
        is not None
    )


def _normalize_line_role_run_result_after_final_sync(
    *,
    run_result: CodexExecRunResult,
    state_path: Path,
    expected_workspace_output_paths: Sequence[Path],
) -> CodexExecRunResult:
    if (
        str(run_result.supervision_reason_code or "").strip()
        != "workspace_final_message_missing_output"
    ):
        return run_result
    if not _line_role_same_session_helper_completed_in_events(run_result):
        return run_result
    same_session_completion = _summarize_line_role_same_session_completion(state_path)
    workspace_output_status = _summarize_workspace_output_paths(expected_workspace_output_paths)
    if not (
        bool(same_session_completion.get("same_session_completed"))
        and str(same_session_completion.get("same_session_final_status") or "").strip()
        == "completed"
        and bool(workspace_output_status.get("complete"))
    ):
        return run_result
    return replace(
        run_result,
        supervision_state="completed",
        supervision_reason_code=None,
        supervision_reason_detail=None,
        supervision_retryable=False,
    )


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
    if int(metadata.get("changed_unit_count") or 0) > 0:
        return True
    return False


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
    if (
        str(same_session_state_payload.get("final_status") or "").strip()
        == "repair_exhausted"
    ):
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


def _line_role_retryable_runner_exception_reason(
    exc: CodexFarmRunnerError,
) -> str | None:
    message = " ".join(str(exc or "").strip().lower().split())
    if not message:
        return None
    if "timed out" in message:
        return "codex_exec_timeout"
    if "killed" in message or "terminated" in message or "interrupt" in message:
        return "codex_exec_killed"
    return None


def _line_role_catastrophic_run_result_reason(
    run_result: CodexExecRunResult,
) -> str | None:
    if not _line_role_hard_boundary_failure(run_result):
        return None
    reason_code = str(run_result.supervision_reason_code or "").strip()
    if reason_code:
        return reason_code
    if str(run_result.supervision_state or "").strip() == "boundary_interrupted":
        return "boundary_interrupted"
    return "catastrophic_worker_failure"


def _should_attempt_line_role_fresh_worker_replacement(
    *,
    exc: CodexFarmRunnerError | None = None,
    run_result: CodexExecRunResult | None = None,
    replacement_attempt_count: int,
    same_session_state_payload: Mapping[str, Any],
) -> tuple[bool, str]:
    if int(replacement_attempt_count) >= 1:
        return False, "fresh_worker_replacement_budget_spent"
    if bool(same_session_state_payload.get("completed")):
        return False, "same_session_already_completed"
    if exc is not None:
        retry_reason = _line_role_retryable_runner_exception_reason(exc)
        if retry_reason is None:
            return False, "runner_exception_not_retryable"
        return True, retry_reason
    if run_result is not None:
        retry_reason = _line_role_catastrophic_run_result_reason(run_result)
        if retry_reason is None:
            return False, "worker_session_not_catastrophic"
        return True, retry_reason
    return False, "fresh_worker_replacement_not_applicable"


def _build_line_role_runner_exception_result(
    *,
    exc: CodexFarmRunnerError,
    prompt_text: str,
    working_dir: Path,
    retryable_reason: str | None,
) -> CodexExecRunResult:
    return CodexExecRunResult(
        command=["codex", "exec"],
        subprocess_exit_code=1,
        output_schema_path=None,
        prompt_text=prompt_text,
        response_text=None,
        turn_failed_message=str(exc),
        usage={
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
        },
        stderr_text=str(exc),
        stdout_text=None,
        source_working_dir=str(working_dir),
        execution_working_dir=str(working_dir),
        execution_agents_path=None,
        duration_ms=0,
        started_at_utc=_format_utc_now(),
        finished_at_utc=_format_utc_now(),
        workspace_mode="taskfile",
        supervision_state="worker_exception",
        supervision_reason_code=retryable_reason or "codex_exec_runner_exception",
        supervision_reason_detail=str(exc),
        supervision_retryable=retryable_reason is not None,
    )


def _reset_line_role_workspace_for_fresh_worker_replacement(
    *,
    worker_root: Path,
    out_dir: Path,
    assignment: WorkerAssignmentV1,
    runnable_shards: Sequence[ShardManifestEntryV1],
    task_file_payload: Mapping[str, Any],
    unit_to_shard_id: Mapping[str, str],
) -> dict[str, Any]:
    for artifact_name in (
        "events.jsonl",
        "last_message.json",
        "usage.json",
        "workspace_manifest.json",
        "stdout.txt",
        "stderr.txt",
    ):
        artifact_path = worker_root / artifact_name
        if artifact_path.exists():
            artifact_path.unlink()
    for shard in runnable_shards:
        output_path = out_dir / f"{shard.shard_id}.json"
        if output_path.exists():
            output_path.unlink()
    state_path = _line_role_same_session_state_path(worker_root)
    replacement_state = initialize_line_role_same_session_state(
        state_path=state_path,
        assignment_id=assignment.worker_id,
        worker_id=assignment.worker_id,
        task_file=task_file_payload,
        unit_to_shard_id=unit_to_shard_id,
        shards=[asdict(shard) for shard in runnable_shards],
        output_dir=out_dir,
    )
    write_task_file(path=worker_root / TASK_FILE_NAME, payload=task_file_payload)
    return replacement_state


def _build_line_role_fresh_worker_replacement_prompt(
    *,
    shards: Sequence[ShardManifestEntryV1],
) -> str:
    return (
        "The previous canonical line-role worker session was stopped before completion. "
        "Start over from the fresh `task.json` that the repo has restored in this workspace. "
        "Do not rely on prior scratch files or prior shell loops.\n\n"
        + _build_line_role_taskfile_prompt(
            shards=shards,
            fresh_session_resume=False,
        )
    )


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


def _line_role_assessment_proves_authoritative_completion(
    assessment: _LineRoleRecoveryAssessment,
) -> bool:
    return bool(
        assessment.same_session_completed
        and assessment.outputs_present
        and str(assessment.diagnosis_code or "").strip() == "completed"
    )


def _override_line_role_missing_output_with_authoritative_completion(
    *,
    run_result: CodexExecRunResult,
) -> CodexExecRunResult:
    return replace(
        run_result,
        supervision_state="completed",
        supervision_reason_code=None,
        supervision_reason_detail=None,
        supervision_retryable=False,
    )


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
    recommended_command = (
        str(doctor_payload.get("recommended_command") or "").strip() or None
    )
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
    if str(run_result.supervision_reason_code or "").strip() not in {
        "workspace_final_message_missing_output",
        "workspace_final_message_incomplete_progress",
    }:
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
        "- Reopen `task.json`, keep editing only the answer objects in place, and stay inside the same workspace.\n"
        f"- Follow the repo-owned recommended command: `{recommended_command}`.\n"
        "- Prefer direct task-file editing over shell scripting.\n"
        "- Stop as soon as the helper reports `completed`.\n\n"
        f"Recovery diagnosis: {assessment.diagnosis_code or '[unknown]'}\n"
        f"Resume summary: {assessment.resume_summary or '[none available]'}\n\n"
        "Assigned shard ids represented in this task file:\n"
        f"{assignments}\n"
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
        signature.append(
            (path_obj.name, int(stat_result.st_size), int(stat_result.st_mtime_ns))
        )
    return {
        "expected_count": expected_count,
        "present_count": present_count,
        "complete": complete and present_count == expected_count,
        "missing_files": sorted(missing_files),
        "signature": tuple(signature),
    }


def _load_live_status(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


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


def _format_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
