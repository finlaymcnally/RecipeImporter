from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import _shared as _shared_module
from . import planning as _planning_module
from . import recovery as _recovery_module
from ..editable_task_file import (
    TASK_FILE_NAME,
    load_task_file,
    validate_edited_task_file,
    write_task_file,
)
from ..knowledge_same_session_handoff import (
    KNOWLEDGE_SAME_SESSION_STATE_ENV,
    initialize_knowledge_same_session_state,
)
from .task_file_contracts import (
    KNOWLEDGE_CLASSIFY_STAGE_KEY,
    KNOWLEDGE_CLASSIFY_SCHEMA_VERSION,
    KNOWLEDGE_GROUP_STAGE_KEY,
    build_knowledge_classification_task_file,
    validate_knowledge_classification_task_file,
    validate_knowledge_grouping_task_file,
)
from ..task_file_guardrails import (
    build_task_file_guardrail,
    build_worker_session_guardrails,
    summarize_task_file_guardrails,
)

for _module in (
    _shared_module,
    _planning_module,
    _recovery_module,
):
    globals().update(
        {
            name: value
            for name, value in vars(_module).items()
            if not name.startswith("__")
        }
    )


def _render_events_jsonl(events: tuple[dict[str, Any], ...]) -> str:
    if not events:
        return ""
    return "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)


def _attach_worker_guardrail_summary(
    *,
    worker_runner_payload: dict[str, Any],
    task_file_guardrail: Mapping[str, Any] | None,
    planned_happy_path_worker_cap: int = 1,
    repair_followup_call_count: int = 0,
) -> None:
    telemetry = worker_runner_payload.get("telemetry")
    if not isinstance(telemetry, Mapping):
        return
    summary = telemetry.get("summary")
    if not isinstance(summary, dict):
        return
    summary["task_file_guardrails"] = summarize_task_file_guardrails([task_file_guardrail])
    worker_session_guardrails = build_worker_session_guardrails(
        planned_happy_path_worker_cap=max(1, int(planned_happy_path_worker_cap)),
        actual_happy_path_worker_sessions=int(summary.get("workspace_worker_session_count") or 0),
        repair_followup_call_count=repair_followup_call_count,
    )
    summary["worker_session_guardrails"] = worker_session_guardrails
    summary["planned_happy_path_worker_cap"] = int(
        worker_session_guardrails["planned_happy_path_worker_cap"]
    )
    summary["actual_happy_path_worker_sessions"] = int(
        worker_session_guardrails["actual_happy_path_worker_sessions"]
    )
    summary["repair_followup_call_count"] = int(
        worker_session_guardrails["repair_followup_call_count"]
    )


def _load_json_dict_safely(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


_KNOWLEDGE_SAME_SESSION_STATE_FILE_NAME = "knowledge_same_session_state.json"


def _knowledge_same_session_state_path(worker_root: Path) -> Path:
    return worker_root / "_repo_control" / _KNOWLEDGE_SAME_SESSION_STATE_FILE_NAME


def _knowledge_task_file_useful_progress(
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
        expected_schema_version=str(original_task_file.get("schema_version") or ""),
        allow_immutable_field_changes=True,
    )
    return bool(int(metadata.get("changed_unit_count") or 0) > 0)


def _knowledge_hard_boundary_failure(run_result: CodexExecRunResult) -> bool:
    if str(run_result.supervision_state or "").strip() == "watchdog_killed":
        return True
    reason_code = str(run_result.supervision_reason_code or "").strip()
    return reason_code.startswith("watchdog_") or "boundary" in reason_code


def _should_attempt_knowledge_fresh_session_retry(
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
    if _knowledge_hard_boundary_failure(run_result):
        return False, "hard_boundary_failure"
    if not run_result.completed_successfully():
        return False, "worker_session_not_clean"
    if not _knowledge_task_file_useful_progress(
        task_file_path=task_file_path,
        original_task_file=original_task_file,
        same_session_state_payload=same_session_state_payload,
    ):
        return False, "no_preserved_progress"
    return True, "preserved_progress_without_completion"


def _task_file_answer_feedback(
    *,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    failed_unit_ids = {
        str(unit_id).strip()
        for unit_id in (validation_metadata.get("failed_unit_ids") or [])
        if str(unit_id).strip()
    }
    if not failed_unit_ids:
        return {}
    feedback = {
        "validation_errors": [
            str(error).strip() for error in validation_errors if str(error).strip()
        ]
    }
    details = list(validation_metadata.get("error_details") or [])
    feedback_by_unit_id: dict[str, dict[str, Any]] = {}
    for unit_id in failed_unit_ids:
        unit_feedback = dict(feedback)
        unit_feedback["error_details"] = [
            dict(detail)
            for detail in details
            if f"/units/{unit_id}/" in str(detail.get("path") or "")
        ]
        feedback_by_unit_id[unit_id] = unit_feedback
    return feedback_by_unit_id


def _render_validation_reason_detail(
    *,
    prefix: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
) -> str:
    cleaned_errors = [
        str(error).strip() for error in validation_errors if str(error).strip()
    ]
    parse_error = str(validation_metadata.get("parse_error") or "").strip()
    unresolved_block_indices = [
        int(value)
        for value in (validation_metadata.get("unresolved_block_indices") or [])
        if value is not None
    ]
    detail_parts = [str(prefix).strip() or "validation blocked promotion"]
    if cleaned_errors:
        detail_parts.append("errors=" + ",".join(cleaned_errors))
    if unresolved_block_indices:
        detail_parts.append(
            "unresolved_block_indices=" + ",".join(str(value) for value in unresolved_block_indices)
        )
    if parse_error:
        detail_parts.append(f"parse_error={parse_error}")
    return "; ".join(part for part in detail_parts if part)


def _evaluate_knowledge_output_file(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    if response_text is None or not str(response_text).strip():
        return None, ("missing_output_file",), {}, "no_final_output"
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return None, ("response_json_invalid",), {}, "invalid"
    if not isinstance(payload, Mapping):
        return None, ("response_not_json_object",), {}, "invalid"
    try:
        normalized_payload, normalization_metadata = normalize_knowledge_worker_payload(
            dict(payload)
        )
    except Exception as exc:  # noqa: BLE001
        return None, ("schema_invalid",), {"parse_error": str(exc)}, "invalid"
    valid, validation_errors, validation_metadata = validate_knowledge_shard_output(
        shard,
        normalized_payload,
    )
    combined_metadata = {
        **dict(validation_metadata or {}),
        **normalization_metadata,
    }
    if not valid:
        combined_metadata["failure_classification"] = classify_knowledge_validation_failure(
            validation_errors=validation_errors,
            validation_metadata=combined_metadata,
        )
        return None, tuple(validation_errors), combined_metadata, "invalid"
    return normalized_payload, (), combined_metadata, "validated"


def _classify_missing_packet_result(
    *,
    worker_root: Path,
    shard: ShardManifestEntryV1,
    run_result: CodexExecRunResult,
    shard_summary: Mapping[str, Any] | None = None,
) -> tuple[str, str | None, dict[str, Any]]:
    live_status = _load_json_dict_safely(worker_root / "live_status.json")
    workspace_manifest = _load_json_dict_safely(worker_root / "workspace_manifest.json")
    same_session_state = _load_json_dict_safely(_knowledge_same_session_state_path(worker_root))
    summary = dict(shard_summary or {})
    metadata = {
        "live_status": live_status,
        "workspace_manifest": workspace_manifest,
        "same_session_handoff_state": same_session_state,
    }
    supervision_reason_code = str(run_result.supervision_reason_code or "").strip()
    supervision_reason_detail = str(run_result.supervision_reason_detail or "").strip() or None
    if (
        supervision_reason_code
        and str(run_result.supervision_state or "").strip() == "watchdog_killed"
    ):
        return supervision_reason_code, supervision_reason_detail, metadata

    current_task_id = str(summary.get("current_task_id") or "").strip()
    current_stage_key = str(same_session_state.get("current_stage_key") or "").strip()
    current_packet_state = str(summary.get("current_packet_state") or "").strip()
    current_result_relpath = str(summary.get("current_result_relpath") or "").strip()
    current_result_observed = bool(summary.get("current_result_observed"))
    promotion_attempted = bool(summary.get("promotion_attempted"))
    repair_attempted = bool(summary.get("repair_attempted"))
    validation_errors = [
        str(error).strip()
        for error in (summary.get("last_validation_errors") or [])
        if str(error).strip()
    ]
    validation_metadata = _coerce_dict(summary.get("last_validation_metadata"))
    terminal_reason_code = str(summary.get("terminal_reason_code") or "").strip()
    terminal_reason_detail = str(summary.get("terminal_reason_detail") or "").strip() or None
    worker_state = str(live_status.get("state") or "").strip()

    if terminal_reason_code == "repair_packet_exhausted":
        return terminal_reason_code, terminal_reason_detail, metadata
    if terminal_reason_code == "packet_result_validation_blocked":
        return terminal_reason_code, terminal_reason_detail, metadata

    if current_packet_state == "failed" and repair_attempted:
        return (
            "repair_packet_exhausted",
            terminal_reason_detail
            or _render_validation_reason_detail(
                prefix="repair task-file rewrite was exhausted without a promotable final output",
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
            ),
            metadata,
        )
    if current_packet_state in {"failed", "validation_blocked"} and (
        current_result_observed or promotion_attempted or validation_errors
    ):
        return (
            "packet_result_validation_blocked",
            terminal_reason_detail
            or _render_validation_reason_detail(
                prefix="task-file result existed but structural validation blocked promotion",
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
            ),
            metadata,
        )
    if current_packet_state in {"leased", "running"} or (
        worker_state in {"running", "running_with_warnings"} and current_task_id
    ):
        detail = (
            "worker exited before the current knowledge assignment completed"
            f" (task_id={current_task_id or '[unknown]'}, "
            f"stage_key={current_stage_key or '[unknown]'}, "
            f"output_path={current_result_relpath or '[unknown]'})"
        )
        return "worker_exited_with_packet_still_leased", detail, metadata
    if same_session_state and not bool(same_session_state.get("completed")):
        return (
            "same_session_handoff_incomplete",
            (
                "worker exited before the same-session knowledge handoff produced final shard outputs"
                f" (current_stage_key={current_stage_key}, "
                f"same_session_transition_count={int(same_session_state.get('same_session_transition_count') or 0)})"
            ),
            metadata,
        )
    return (
        "process_exited_without_final_packet_state",
        "worker exited without a promotable shard output and without enough task-file state evidence for a stronger classification",
        metadata,
    )


def _validate_knowledge_task_file_step(
    *,
    original_task_file: Mapping[str, Any],
    edited_task_file: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]] | None, tuple[str, ...], dict[str, Any]]:
    stage_key = str(original_task_file.get("stage_key") or "").strip()
    if stage_key == KNOWLEDGE_CLASSIFY_STAGE_KEY:
        return validate_knowledge_classification_task_file(
            original_task_file=original_task_file,
            edited_task_file=edited_task_file,
        )
    if stage_key == KNOWLEDGE_GROUP_STAGE_KEY:
        return validate_knowledge_grouping_task_file(
            original_task_file=original_task_file,
            edited_task_file=edited_task_file,
        )
    return None, ("unsupported_stage_key",), {"stage_key": stage_key}


def _task_file_prompt_name(task_file_payload: Mapping[str, Any]) -> str:
    stage_key = str(task_file_payload.get("stage_key") or "").strip()
    if stage_key == KNOWLEDGE_CLASSIFY_STAGE_KEY:
        return "classify"
    if stage_key == KNOWLEDGE_GROUP_STAGE_KEY:
        return "group"
    return "task"


def _write_task_file_snapshot(
    *,
    worker_root: Path,
    step_name: str,
    suffix: str,
    payload: Mapping[str, Any],
) -> None:
    _write_json(dict(payload), worker_root / f"task_{step_name}.{suffix}.json")


def _apply_knowledge_same_session_row_metadata(
    *,
    row: dict[str, Any],
    initial_task_file: Mapping[str, Any],
    state_payload: Mapping[str, Any],
) -> None:
    classification_validation_count = int(
        state_payload.get("classification_validation_count") or 0
    )
    grouping_validation_count = int(state_payload.get("grouping_validation_count") or 0)
    same_session_repair_rewrite_count = int(
        state_payload.get("same_session_repair_rewrite_count") or 0
    )
    row["knowledge_same_session"] = True
    row["knowledge_same_session_status"] = str(state_payload.get("final_status") or "").strip() or None
    row["same_session_transition_count"] = int(
        state_payload.get("same_session_transition_count") or 0
    )
    row["classification_validation_count"] = classification_validation_count
    row["grouping_validation_count"] = grouping_validation_count
    row["same_session_repair_rewrite_count"] = same_session_repair_rewrite_count
    row["grouping_transition_count"] = int(
        state_payload.get("grouping_transition_count") or 0
    )
    row["classification_step_count"] = 1 if classification_validation_count > 0 else 0
    row["grouping_step_count"] = grouping_validation_count
    row["workspace_packet_count"] = (
        classification_validation_count + grouping_validation_count
    )
    row["workspace_repair_packet_count"] = same_session_repair_rewrite_count
    row["owned_row_count"] = int(len(initial_task_file.get("units") or []))
    row["classification_owned_row_count"] = int(len(initial_task_file.get("units") or []))
    row["grouping_owned_row_count"] = int(state_payload.get("grouping_unit_count") or 0)
    row["final_output_shard_count"] = int(state_payload.get("final_output_shard_count") or 0)


def _run_phase_knowledge_worker_assignment_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: Mapping[str, str],
    shard_by_id: Mapping[str, ShardManifestEntryV1],
    runner: CodexExecRunner,
    pipeline_id: str,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState,
    shard_completed_callback: Callable[..., None] | None,
    progress_state: _KnowledgePhaseProgressState | None,
    task_status_tracker: _KnowledgeTaskStatusTracker | None,
) -> _DirectKnowledgeWorkerResult:
    worker_root = Path(assignment.workspace_root)
    in_dir = worker_root / "in"
    hints_dir = worker_root / "hints"
    logs_dir = worker_root / "logs"
    out_dir = worker_root / "out"
    scratch_dir = worker_root / "scratch"
    for path in (in_dir, hints_dir, logs_dir, out_dir, scratch_dir):
        path.mkdir(parents=True, exist_ok=True)
    requested_shards = [shard_by_id[shard_id] for shard_id in assignment.shard_ids]

    worker_failure_count = 0
    worker_proposal_count = 0
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    worker_runner_results: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    assigned_shards: list[ShardManifestEntryV1] = []

    for shard in requested_shards:
        preflight_failure = _preflight_knowledge_shard(shard)
        if preflight_failure is None:
            assigned_shards.append(shard)
            continue
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        reason_code = str(preflight_failure.get("reason_code") or "preflight_rejected")
        reason_detail = str(preflight_failure.get("reason_detail") or "")
        _write_json(
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": None,
                "validation_errors": [reason_code],
                "validation_metadata": {},
            },
            proposal_path,
        )
        worker_failure_count += 1
        worker_failures.append(
            {
                "worker_id": assignment.worker_id,
                "shard_id": shard.shard_id,
                "reason": "preflight_rejected",
                "validation_errors": [reason_code],
                "state": "preflight_rejected",
                "reason_code": reason_code,
            }
        )
        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status="preflight_rejected",
                proposal_path=_relative_path(run_root, proposal_path),
                payload=None,
                validation_errors=(reason_code,),
                metadata={},
            )
        )
        if task_status_tracker is not None:
            task_status_tracker.mark_terminal(
                task_id=shard.shard_id,
                worker_id=assignment.worker_id,
                terminal_state="preflight_rejected",
                attempt_type="preflight",
                proposal_status="preflight_rejected",
                validation_errors=(reason_code,),
                metadata={"reason_detail": reason_detail},
                terminal_reason_code=reason_code,
                terminal_reason_detail=reason_detail,
            )
        if progress_state is not None:
            progress_state.mark_task_packet_terminal(
                worker_id=assignment.worker_id,
                task_id=shard.shard_id,
            )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    task_file_payload: dict[str, Any] | None = None
    task_file_guardrail: dict[str, Any] | None = None
    unit_to_shard_id: dict[str, str] = {}
    if assigned_shards:
        task_file_payload, unit_to_shard_id = build_knowledge_classification_task_file(
            assignment=assignment,
            shards=assigned_shards,
        )
        task_file_guardrail = build_task_file_guardrail(
            payload=task_file_payload,
            assignment_id=assignment.worker_id,
            worker_id=assignment.worker_id,
        )

    if not assigned_shards:
        _write_json(
            {"state": "completed", "reason_code": "no_shards_assigned"},
            worker_root / "live_status.json",
        )
        worker_runner_payload = _aggregate_worker_runner_payload(
            pipeline_id=pipeline_id,
            worker_runs=worker_runner_results,
            stage_rows=stage_rows,
        )
        _attach_worker_guardrail_summary(
            worker_runner_payload=worker_runner_payload,
            task_file_guardrail=task_file_guardrail,
            planned_happy_path_worker_cap=1,
        )
        _write_json(worker_runner_payload, worker_root / "status.json")
        return _DirectKnowledgeWorkerResult(
            report=WorkerExecutionReportV1(
                worker_id=assignment.worker_id,
                shard_ids=assignment.shard_ids,
                workspace_root=_relative_path(run_root, worker_root),
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
                    "in_dir": _relative_path(run_root, in_dir),
                    "hints_dir": _relative_path(run_root, hints_dir),
                    "out_dir": _relative_path(run_root, out_dir),
                    "scratch_dir": _relative_path(run_root, scratch_dir),
                    "task_file_guardrail": dict(task_file_guardrail or {}),
                },
            ),
            proposals=tuple(worker_proposals),
            failures=tuple(worker_failures),
            stage_rows=tuple(stage_rows),
            worker_runner_payload=worker_runner_payload,
        )

    if task_status_tracker is not None:
        for shard in assigned_shards:
            task_status_tracker.start_attempt(
                task_id=shard.shard_id,
                worker_id=assignment.worker_id,
                attempt_type="main_worker",
                metadata={
                    "task_file": TASK_FILE_NAME,
                    "workspace_processing_contract": "knowledge_split_task_file_v1",
                },
            )
    classify_answers_by_unit_id: dict[str, dict[str, Any]] | None = None
    grouping_answers_by_unit_id: dict[str, dict[str, Any]] | None = None
    classification_validation_errors: tuple[str, ...] = ()
    classification_validation_metadata: dict[str, Any] = {}
    grouping_validation_errors: tuple[str, ...] = ()
    grouping_validation_metadata: dict[str, Any] = {}
    semantic_run_results: list[CodexExecRunResult] = []
    fresh_session_retry_count = 0
    fresh_session_retry_status = "not_attempted"
    same_session_state_payload: dict[str, Any] = {}
    if task_file_payload is not None:
        state_path = _knowledge_same_session_state_path(worker_root)
        initialize_knowledge_same_session_state(
            state_path=state_path,
            assignment_id=assignment.worker_id,
            worker_id=assignment.worker_id,
            classification_task_file=task_file_payload,
            unit_to_shard_id=unit_to_shard_id,
            output_dir=out_dir,
        )
        write_task_file(path=worker_root / TASK_FILE_NAME, payload=task_file_payload)
        _write_task_file_snapshot(
            worker_root=worker_root,
            step_name="classification",
            suffix="initial",
            payload=task_file_payload,
        )
        classification_prompt_text = _build_knowledge_workspace_worker_prompt(
            stage_key=KNOWLEDGE_CLASSIFY_STAGE_KEY,
            shards=assigned_shards,
        )
        prompt_path = worker_root / "prompt_classification.txt"
        prompt_path.write_text(classification_prompt_text, encoding="utf-8")
        run_result = runner.run_workspace_worker(
            prompt_text=classification_prompt_text,
            working_dir=worker_root,
            env={
                **dict(env),
                KNOWLEDGE_SAME_SESSION_STATE_ENV: str(state_path),
            },
            model=model,
            reasoning_effort=reasoning_effort,
            workspace_task_label="knowledge same-session worker session",
            supervision_callback=_build_strict_json_watchdog_callback(
                live_status_path=worker_root / "live_status.json",
                allow_workspace_commands=True,
                execution_workspace_root=worker_root,
                expected_workspace_output_paths=[
                    out_dir / f"{shard.shard_id}.json" for shard in assigned_shards
                ],
                workspace_output_observer=(
                    None
                    if progress_state is None
                    else lambda present_count, expected_count, _worker_id=assignment.worker_id: (
                        progress_state.observe_workspace_outputs(
                            worker_id=_worker_id,
                            present_count=present_count,
                            expected_count=expected_count,
                        )
                    )
                ),
            ),
        )
        semantic_run_results.append(run_result)
        _finalize_live_status(
            worker_root / "live_status.json",
            run_result=run_result,
            watchdog_policy="workspace_worker_v1",
        )
        same_session_state_payload = _load_json_dict_safely(state_path)
        final_run_result = semantic_run_results[-1]
        (worker_root / "events.jsonl").write_text(
            _render_events_jsonl(final_run_result.events),
            encoding="utf-8",
        )
        _write_json({"text": final_run_result.response_text}, worker_root / "last_message.json")
        _write_json(dict(final_run_result.usage or {}), worker_root / "usage.json")
        _write_json(
            final_run_result.workspace_manifest(),
            worker_root / "workspace_manifest.json",
        )
        _write_optional_text(worker_root / "stdout.txt", final_run_result.stdout_text)
        _write_optional_text(worker_root / "stderr.txt", final_run_result.stderr_text)
        worker_session_runs: list[tuple[CodexExecRunResult, Path, bool]] = [
            (run_result, prompt_path, False)
        ]
        should_retry, retry_reason = _should_attempt_knowledge_fresh_session_retry(
            run_result=run_result,
            task_file_path=worker_root / TASK_FILE_NAME,
            original_task_file=task_file_payload,
            same_session_state_payload=same_session_state_payload,
        )
        if should_retry:
            fresh_session_retry_count = 1
            fresh_session_retry_status = "attempted"
            same_session_state_payload["fresh_session_retry_count"] = 1
            same_session_state_payload["fresh_session_retry_status"] = "attempted"
            fresh_session_retry_history = list(
                same_session_state_payload.get("fresh_session_retry_history") or []
            )
            fresh_session_retry_history.append(
                {
                    "attempt": 1,
                    "reason_code": retry_reason,
                    "reason_detail": "clean first session preserved useful workspace state without completion",
                }
            )
            same_session_state_payload["fresh_session_retry_history"] = fresh_session_retry_history
            _write_json(same_session_state_payload, state_path)
            current_task_file = load_task_file(worker_root / TASK_FILE_NAME)
            resume_prompt_path = worker_root / "prompt_resume.txt"
            resume_prompt_text = _build_knowledge_workspace_worker_prompt(
                stage_key=str(
                    current_task_file.get("stage_key")
                    or same_session_state_payload.get("current_stage_key")
                    or KNOWLEDGE_CLASSIFY_STAGE_KEY
                ),
                shards=assigned_shards,
                fresh_session_resume=True,
            )
            resume_prompt_path.write_text(resume_prompt_text, encoding="utf-8")
            run_result = runner.run_workspace_worker(
                prompt_text=resume_prompt_text,
                working_dir=worker_root,
                env={
                    **dict(env),
                    KNOWLEDGE_SAME_SESSION_STATE_ENV: str(state_path),
                },
                model=model,
                reasoning_effort=reasoning_effort,
                workspace_task_label="knowledge fresh-session worker recovery",
                supervision_callback=_build_strict_json_watchdog_callback(
                    live_status_path=worker_root / "live_status.json",
                    allow_workspace_commands=True,
                    execution_workspace_root=worker_root,
                    expected_workspace_output_paths=[
                        out_dir / f"{shard.shard_id}.json" for shard in assigned_shards
                    ],
                    workspace_output_observer=(
                        None
                        if progress_state is None
                        else lambda present_count, expected_count, _worker_id=assignment.worker_id: (
                            progress_state.observe_workspace_outputs(
                                worker_id=_worker_id,
                                present_count=present_count,
                                expected_count=expected_count,
                            )
                        )
                    ),
                ),
            )
            semantic_run_results.append(run_result)
            _finalize_live_status(
                worker_root / "live_status.json",
                run_result=run_result,
                watchdog_policy="workspace_worker_v1",
            )
            same_session_state_payload = _load_json_dict_safely(state_path)
            fresh_session_retry_status = (
                "completed"
                if bool(same_session_state_payload.get("completed"))
                else "failed"
            )
            same_session_state_payload["fresh_session_retry_count"] = 1
            same_session_state_payload["fresh_session_retry_status"] = fresh_session_retry_status
            same_session_state_payload["fresh_session_retry_history"] = [
                {
                    **dict(row),
                    **(
                        {
                            "result_completed": bool(same_session_state_payload.get("completed")),
                            "result_final_status": same_session_state_payload.get("final_status"),
                        }
                        if index == len(fresh_session_retry_history) - 1
                        else {}
                    ),
                }
                for index, row in enumerate(fresh_session_retry_history)
                if isinstance(row, Mapping)
            ]
            _write_json(same_session_state_payload, state_path)
            worker_session_runs.append((run_result, resume_prompt_path, True))
            final_run_result = semantic_run_results[-1]
            (worker_root / "events.jsonl").write_text(
                _render_events_jsonl(final_run_result.events),
                encoding="utf-8",
            )
            _write_json({"text": final_run_result.response_text}, worker_root / "last_message.json")
            _write_json(dict(final_run_result.usage or {}), worker_root / "usage.json")
            _write_json(
                final_run_result.workspace_manifest(),
                worker_root / "workspace_manifest.json",
            )
            _write_optional_text(worker_root / "stdout.txt", final_run_result.stdout_text)
            _write_optional_text(worker_root / "stderr.txt", final_run_result.stderr_text)
        for session_index, (session_run_result, session_prompt_path, fresh_session_resume) in enumerate(worker_session_runs, start=1):
            worker_runner_payload = _build_knowledge_workspace_task_runner_payload(
                pipeline_id=pipeline_id,
                worker_id=assignment.worker_id,
                shard_id=f"{assignment.worker_id}.same_session.{session_index:02d}",
                runtime_task_id=f"{assignment.worker_id}.same_session.{session_index:02d}",
                run_result=session_run_result,
                model=model,
                reasoning_effort=reasoning_effort,
                request_input_file=worker_root / TASK_FILE_NAME,
                worker_prompt_path=session_prompt_path,
                worker_root=worker_root,
                task_count=1,
                task_index=0,
            )
            telemetry = worker_runner_payload.get("telemetry")
            if isinstance(telemetry, Mapping):
                rows = telemetry.get("rows")
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        row["fresh_session_resume"] = fresh_session_resume
                        _apply_knowledge_same_session_row_metadata(
                            row=row,
                            initial_task_file=task_file_payload,
                            state_payload=same_session_state_payload,
                        )
                        stage_rows.append(dict(row))
                    telemetry["summary"] = _summarize_direct_rows(
                        [dict(row) for row in rows if isinstance(row, Mapping)]
                    )
            worker_runner_payload["fresh_session_resume"] = fresh_session_resume
            _attach_worker_guardrail_summary(
                worker_runner_payload=worker_runner_payload,
                task_file_guardrail=task_file_guardrail,
                planned_happy_path_worker_cap=2,
            )
            worker_runner_results.append(worker_runner_payload)
        classify_answers_by_unit_id = (
            dict(same_session_state_payload.get("classification_answers_by_unit_id") or {})
            or None
        )
        grouping_answers_by_unit_id = dict(
            same_session_state_payload.get("grouping_answers_by_unit_id") or {}
        )

    task_total = len(assigned_shards)
    run_result = semantic_run_results[-1]
    worker_prompt_path = (
        worker_root / "prompt_grouping.txt"
        if (worker_root / "prompt_grouping.txt").exists()
        else worker_root / "prompt_classification.txt"
    )
    task_file_errors_by_shard: dict[str, tuple[tuple[str, ...], dict[str, Any]]] = {}
    for unit_id in classification_validation_metadata.get("failed_unit_ids") or []:
        shard_id = str(unit_to_shard_id.get(str(unit_id)) or "").strip()
        if shard_id:
            task_file_errors_by_shard[shard_id] = (
                classification_validation_errors,
                dict(classification_validation_metadata),
            )
    for unit_id in grouping_validation_metadata.get("failed_unit_ids") or []:
        shard_id = str(unit_to_shard_id.get(str(unit_id)) or "").strip()
        if shard_id:
            task_file_errors_by_shard[shard_id] = (
                grouping_validation_errors,
                dict(grouping_validation_metadata),
            )
    for task_index, shard in enumerate(assigned_shards):
        response_path = out_dir / f"{shard.shard_id}.json"
        response_text = (
            response_path.read_text(encoding="utf-8")
            if response_path.exists()
            else None
        )
        shard_summary = {
            "packet_count": 1 if response_text is not None else 0,
            "repair_packet_count": 0,
            "repair_attempted": False,
            "repair_recovered": False,
            "current_task_id": None,
            "current_packet_kind": None,
            "current_result_relpath": str(Path("out") / f"{shard.shard_id}.json"),
            "current_packet_state": (
                "completed" if response_text is not None else "missing_output"
            ),
            "current_result_observed": response_text is not None,
            "promotion_attempted": response_text is not None,
            "promotion_succeeded": False,
            "last_runtime_action": (
                "assignment_completed"
                if response_text is not None
                else "assignment_missing_output"
            ),
            "terminal_status": "pending",
            "terminal_reason_code": None,
            "terminal_reason_detail": None,
            "last_validation_errors": [],
            "last_validation_metadata": {},
        }
        runner_payload = _build_knowledge_workspace_task_runner_payload(
            pipeline_id=pipeline_id,
            worker_id=assignment.worker_id,
            shard_id=shard.shard_id,
            runtime_task_id=shard.shard_id,
            run_result=run_result,
            model=model,
            reasoning_effort=reasoning_effort,
            request_input_file=in_dir / f"{shard.shard_id}.json",
            worker_prompt_path=worker_prompt_path,
            worker_root=worker_root,
            task_count=task_total,
            task_index=task_index,
        )
        if shard.shard_id in task_file_errors_by_shard and response_text is None:
            validation_errors, validation_metadata = task_file_errors_by_shard[shard.shard_id]
            payload = None
            proposal_status = "invalid"
        else:
            payload, validation_errors, validation_metadata, proposal_status = (
                _evaluate_knowledge_output_file(
                    shard=shard,
                    response_text=response_text,
                )
            )
        task_root = worker_root / "shards" / shard.shard_id
        explicit_terminal_reason_code: str | None = None
        explicit_terminal_reason_detail: str | None = None
        explicit_terminal_reason_metadata: dict[str, Any] = {}
        if proposal_status == "no_final_output":
            (
                explicit_terminal_reason_code,
                explicit_terminal_reason_detail,
                explicit_terminal_reason_metadata,
            ) = _classify_missing_packet_result(
                worker_root=worker_root,
                shard=shard,
                run_result=run_result,
                shard_summary=shard_summary,
            )
        elif proposal_status == "invalid":
            task_root.mkdir(parents=True, exist_ok=True)
            repair_run_result = _run_knowledge_repair_attempt(
                runner=runner,
                worker_root=worker_root,
                shard=shard,
                env=env,
                output_schema_path=None,
                model=model,
                reasoning_effort=reasoning_effort,
                original_response_text=str(response_text or ""),
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
                live_status_path=task_root / "repair_live_status.json",
            )
            _write_json(
                {"text": repair_run_result.response_text},
                task_root / "repair_last_message.json",
            )
            _write_json(
                dict(repair_run_result.usage or {}),
                task_root / "repair_usage.json",
            )
            (
                repair_payload,
                repair_validation_errors,
                repair_validation_metadata,
                repair_proposal_status,
            ) = _evaluate_knowledge_output_file(
                shard=shard,
                response_text=repair_run_result.response_text,
            )
            shard_summary.update(
                {
                    "repair_packet_count": 1,
                    "repair_attempted": True,
                    "repair_recovered": (
                        repair_proposal_status == "validated" and repair_payload is not None
                    ),
                }
            )
            if repair_proposal_status == "validated" and repair_payload is not None:
                _write_json(dict(repair_payload), response_path)
                payload = repair_payload
                validation_errors = ()
                validation_metadata = dict(repair_validation_metadata or {})
                proposal_status = "validated"
                _write_json(
                    {
                        "shard_id": shard.shard_id,
                        "repair_status": "repaired",
                        "validation_errors": [],
                    },
                    task_root / "repair_status.json",
                )
            else:
                payload = None
                validation_errors = tuple(repair_validation_errors or validation_errors)
                validation_metadata = {
                    **dict(validation_metadata or {}),
                    **dict(repair_validation_metadata or {}),
                }
                proposal_status = "invalid"
                explicit_terminal_reason_code = (
                    str(repair_run_result.supervision_reason_code or "").strip()
                    or "repair_packet_exhausted"
                )
                explicit_terminal_reason_detail = (
                    str(repair_run_result.supervision_reason_detail or "").strip()
                    or _render_validation_reason_detail(
                        prefix="repair task-file rewrite was exhausted without a promotable final output",
                        validation_errors=validation_errors,
                        validation_metadata=validation_metadata,
                    )
                )
                _write_json(
                    {
                        "shard_id": shard.shard_id,
                        "repair_status": "failed",
                        "validation_errors": list(validation_errors),
                    },
                    task_root / "repair_status.json",
                )
        validation_metadata = {
            **dict(validation_metadata or {}),
            **dict(shard_summary),
            **dict(explicit_terminal_reason_metadata or {}),
        }
        if proposal_status == "validated":
            validation_metadata["promotion_succeeded"] = True
            validation_metadata["terminal_status"] = "validated"
            validation_metadata["terminal_reason_code"] = "validated"
        elif proposal_status != "no_final_output":
            validation_metadata["terminal_status"] = "failed"
        if explicit_terminal_reason_code:
            validation_metadata["terminal_reason_code"] = explicit_terminal_reason_code
            validation_metadata["terminal_reason_detail"] = explicit_terminal_reason_detail
        runner_payload["packet_lease"] = dict(shard_summary)
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        _write_json(
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": payload,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
            },
            proposal_path,
        )
        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status=proposal_status,
                proposal_path=_relative_path(run_root, proposal_path),
                payload=payload,
                validation_errors=tuple(validation_errors),
                metadata=dict(validation_metadata or {}),
            )
        )
        worker_proposal_count += 1
        if proposal_status != "validated":
            worker_failure_count += 1
            worker_failures.append(
                {
                    "worker_id": assignment.worker_id,
                    "shard_id": shard.shard_id,
                    "reason": (
                        str(explicit_terminal_reason_code or "").strip()
                        or str(shard_summary.get("terminal_reason_code") or "").strip()
                        or _failure_reason_from_run_result(
                            run_result=run_result,
                            proposal_status=proposal_status,
                        )
                    ),
                    "validation_errors": list(validation_errors),
                    "state": run_result.supervision_state or "completed",
                    "reason_code": (
                        str(explicit_terminal_reason_code or "").strip()
                        or str(shard_summary.get("terminal_reason_code") or "").strip()
                        or run_result.supervision_reason_code
                    ),
                }
            )
        else:
            cohort_watchdog_state.record_validated_result(
                duration_ms=run_result.duration_ms,
                example_payload=_build_knowledge_watchdog_example(
                    shard=shard,
                    payload=payload,
                ),
            )
        if progress_state is not None:
            progress_state.mark_task_packet_terminal(
                worker_id=assignment.worker_id,
                task_id=shard.shard_id,
            )
        if task_status_tracker is not None:
            terminal_reason_code, terminal_reason_detail = _terminal_reason_for_knowledge_task(
                proposal_status=proposal_status,
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
                run_result=run_result,
                repair_skip_reason_code=(
                    str(explicit_terminal_reason_code or "").strip()
                    or str(shard_summary.get("terminal_reason_code") or "").strip()
                    or None
                ),
                repair_skip_reason_detail=(
                    str(explicit_terminal_reason_detail or "").strip()
                    or str(shard_summary.get("terminal_reason_detail") or "").strip()
                    or None
                ),
            )
            task_status_tracker.mark_terminal(
                task_id=shard.shard_id,
                worker_id=assignment.worker_id,
                terminal_state=_terminal_knowledge_task_state(
                    proposal_status=proposal_status,
                    supervision_state=run_result.supervision_state,
                    terminal_reason_code=terminal_reason_code,
                ),
                attempt_type="main_worker",
                proposal_status=proposal_status,
                validation_errors=validation_errors,
                metadata=dict(validation_metadata or {}),
                terminal_reason_code=terminal_reason_code,
                terminal_reason_detail=terminal_reason_detail,
            )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    worker_runner_payload = _aggregate_worker_runner_payload(
        pipeline_id=pipeline_id,
        worker_runs=worker_runner_results,
        stage_rows=stage_rows,
    )
    worker_runner_payload["fresh_session_retry_count"] = fresh_session_retry_count
    worker_runner_payload["fresh_session_retry_status"] = fresh_session_retry_status
    _attach_worker_guardrail_summary(
        worker_runner_payload=worker_runner_payload,
        task_file_guardrail=task_file_guardrail,
        planned_happy_path_worker_cap=2,
        repair_followup_call_count=int(
            worker_runner_payload.get("telemetry", {})
            .get("summary", {})
            .get("structured_followup_call_count")
            or 0
        ),
    )
    _write_json(worker_runner_payload, worker_root / "status.json")
    return _DirectKnowledgeWorkerResult(
        report=WorkerExecutionReportV1(
            worker_id=assignment.worker_id,
            shard_ids=assignment.shard_ids,
            workspace_root=_relative_path(run_root, worker_root),
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
                "in_dir": _relative_path(run_root, in_dir),
                "hints_dir": _relative_path(run_root, hints_dir),
                "out_dir": _relative_path(run_root, out_dir),
                "scratch_dir": _relative_path(run_root, scratch_dir),
                "packet_history_path": _relative_path(
                    run_root,
                    worker_root / "packet_history.jsonl",
                ),
                "task_file_guardrail": dict(task_file_guardrail or {}),
                "fresh_session_retry_count": fresh_session_retry_count,
                "fresh_session_retry_status": fresh_session_retry_status,
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
        stage_rows=tuple(stage_rows),
        worker_runner_payload=worker_runner_payload,
    )
