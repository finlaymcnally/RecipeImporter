from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


def _preflight_line_role_shard(
    shard: ShardManifestEntryV1,
) -> dict[str, Any] | None:
    from . import runtime as root

    payload = root._coerce_mapping_dict(shard.input_payload)
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
    from . import runtime as root

    timestamp = root._format_utc_now()
    return root.CodexExecRunResult(
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
    watchdog_policy: str = "strict_json_no_tools_v1",
    allow_workspace_commands: bool = False,
    expected_workspace_output_paths: Sequence[Path] | None = None,
    workspace_completion_quiescence_seconds: float | None = None,
    final_message_missing_output_grace_seconds: float | None = None,
) -> Callable[[CodexExecLiveSnapshot], CodexExecSupervisionDecision | None]:
    from . import runtime as root

    _runtime_override = root._runtime_override
    canonical_line_roles_module = root.canonical_line_roles_module
    _classify_line_role_workspace_command = root._classify_line_role_workspace_command
    detect_taskfile_worker_boundary_violation = (
        root.detect_taskfile_worker_boundary_violation
    )
    _summarize_workspace_output_paths = root._summarize_workspace_output_paths
    _summarize_line_role_same_session_completion = (
        root._summarize_line_role_same_session_completion
    )
    _line_role_same_session_helper_completion_from_snapshot = (
        root._line_role_same_session_helper_completion_from_snapshot
    )
    _line_role_incomplete_progress_summary_detail = (
        root._line_role_incomplete_progress_summary_detail
    )
    _write_runtime_json = root._write_runtime_json
    is_single_file_workspace_command_drift_policy = (
        root.is_single_file_workspace_command_drift_policy
    )
    should_terminate_workspace_command_loop = (
        root.should_terminate_workspace_command_loop
    )
    format_watchdog_command_loop_reason_detail = (
        root.format_watchdog_command_loop_reason_detail
    )
    format_watchdog_command_reason_detail = root.format_watchdog_command_reason_detail
    CodexExecSupervisionDecision = root.CodexExecSupervisionDecision
    _LINE_ROLE_COHORT_WATCHDOG_MIN_COMPLETED_SHARDS = (
        root._LINE_ROLE_COHORT_WATCHDOG_MIN_COMPLETED_SHARDS
    )

    target_paths: list[Path] = []
    if live_status_path is not None:
        target_paths.append(live_status_path)
    if live_status_paths is not None:
        target_paths.extend(Path(path) for path in live_status_paths)
    completion_quiescence_seconds = float(
        workspace_completion_quiescence_seconds
        if workspace_completion_quiescence_seconds is not None
        else _runtime_override(
            "_LINE_ROLE_WORKSPACE_COMPLETION_QUIESCENCE_SECONDS",
            canonical_line_roles_module._LINE_ROLE_WORKSPACE_COMPLETION_QUIESCENCE_SECONDS,
        )
    )
    missing_output_grace_seconds = float(
        final_message_missing_output_grace_seconds
        if final_message_missing_output_grace_seconds is not None
        else _runtime_override(
            "_LINE_ROLE_FINAL_MESSAGE_MISSING_OUTPUT_GRACE_SECONDS",
            canonical_line_roles_module._LINE_ROLE_FINAL_MESSAGE_MISSING_OUTPUT_GRACE_SECONDS,
        )
    )
    last_complete_workspace_signature: tuple[tuple[str, int, int], ...] | None = None
    workspace_output_stable_passes = 0
    completion_wait_started_elapsed_seconds: float | None = None
    completion_wait_agent_message_count: int | None = None
    completion_wait_turn_completed_count: int | None = None
    final_message_missing_output_started_elapsed_seconds: float | None = None
    final_message_missing_output_deadline_elapsed_seconds: float | None = None
    final_message_missing_output_deadline_passes = 0
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
        nonlocal final_message_missing_output_deadline_passes
        nonlocal last_single_file_command_count
        decision: CodexExecSupervisionDecision | None = None
        command_execution_tolerated = False
        last_command_verdict = _classify_line_role_workspace_command(
            snapshot.last_command,
            single_file_worker_policy=allow_workspace_commands,
        )
        last_command_boundary_violation = detect_taskfile_worker_boundary_violation(
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
        helper_completion = _line_role_same_session_helper_completion_from_snapshot(
            snapshot
        )
        helper_completed_in_event_stream = bool(
            helper_completion.get("helper_completed_in_event_stream")
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
                if (
                    not last_command_verdict.allowed
                    or last_command_boundary_violation is not None
                ):
                    decision = CodexExecSupervisionDecision.terminate(
                        reason_code="boundary_command_execution_forbidden",
                        reason_detail=format_watchdog_command_reason_detail(
                            stage_label="taskfile worker stage",
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
                snapshot.agent_message_count
                > int(completion_wait_agent_message_count or 0)
                or snapshot.turn_completed_count
                > int(completion_wait_turn_completed_count or 0)
            )
            completion_wait_elapsed_seconds = (
                snapshot.elapsed_seconds
                - float(completion_wait_started_elapsed_seconds or 0.0)
            )
            completion_quiescence_reached = (
                completion_wait_elapsed_seconds >= completion_quiescence_seconds
                and (
                    snapshot.last_event_seconds_ago is None
                    or snapshot.last_event_seconds_ago >= completion_quiescence_seconds
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
                    int(snapshot.command_execution_count or 0)
                    > last_single_file_command_count
                )
                if new_command_observed:
                    last_single_file_command_count = int(
                        snapshot.command_execution_count or 0
                    )
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
                        max_command_count=_runtime_override(
                            "_LINE_ROLE_WORKSPACE_MAX_COMMAND_COUNT",
                            canonical_line_roles_module._LINE_ROLE_WORKSPACE_MAX_COMMAND_COUNT,
                        ),
                        max_repeat_count=_runtime_override(
                            "_LINE_ROLE_WORKSPACE_MAX_REPEAT_COUNT",
                            canonical_line_roles_module._LINE_ROLE_WORKSPACE_MAX_REPEAT_COUNT,
                        ),
                    )
                ):
                    _record_warning(
                        "command_loop_without_output",
                        format_watchdog_command_loop_reason_detail(
                            stage_label="taskfile worker stage",
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
                    "taskfile worker emitted repeated reasoning without a final answer",
                )
            else:
                decision = CodexExecSupervisionDecision.terminate(
                    reason_code="watchdog_reasoning_without_output",
                    reason_detail=(
                        "strict JSON stage emitted repeated reasoning without a final answer"
                    ),
                    retryable=True,
                )
        elif (
            cohort_completed_successful_shards
            >= _LINE_ROLE_COHORT_WATCHDOG_MIN_COMPLETED_SHARDS
            and int(cohort_median_duration_ms or 0) > 0
            and (snapshot.elapsed_seconds * 1000.0)
            >= _runtime_override(
                "_LINE_ROLE_COHORT_WATCHDOG_MIN_ELAPSED_MS",
                canonical_line_roles_module._LINE_ROLE_COHORT_WATCHDOG_MIN_ELAPSED_MS,
            )
            and (snapshot.elapsed_seconds * 1000.0)
            >= (
                float(cohort_median_duration_ms)
                * _runtime_override(
                    "_LINE_ROLE_COHORT_WATCHDOG_MEDIAN_FACTOR",
                    canonical_line_roles_module._LINE_ROLE_COHORT_WATCHDOG_MEDIAN_FACTOR,
                )
            )
            and not snapshot.has_final_agent_message
        ):
            if allow_workspace_commands:
                _record_warning(
                    "cohort_runtime_outlier",
                    "taskfile worker exceeded sibling median runtime without reaching final output",
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
            and not helper_completed_in_event_stream
            and not authoritative_same_session_success
            and not workspace_output_status["complete"]
        ):
            incomplete_progress_detail = _line_role_incomplete_progress_summary_detail(
                snapshot.final_agent_message_text
            )
            if incomplete_progress_detail:
                decision = CodexExecSupervisionDecision.terminate(
                    reason_code="workspace_final_message_incomplete_progress",
                    reason_detail=incomplete_progress_detail,
                    retryable=True,
                    supervision_state="watchdog_killed",
                )
            if decision is not None:
                final_message_missing_output_grace_active = False
                final_message_missing_output_deadline_reached = False
            else:
                if final_message_missing_output_started_elapsed_seconds is None:
                    final_message_missing_output_started_elapsed_seconds = (
                        snapshot.elapsed_seconds
                    )
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
                    final_message_missing_output_deadline_passes += 1
                    if final_message_missing_output_deadline_passes >= 2:
                        missing_files = (
                            ", ".join(workspace_output_status["missing_files"])
                            or "[unknown]"
                        )
                        decision = CodexExecSupervisionDecision.terminate(
                            reason_code="workspace_final_message_missing_output",
                            reason_detail=(
                                "taskfile worker emitted a final agent message but the required output files "
                                f"were still missing after {missing_output_grace_seconds:.1f} "
                                f"seconds: {missing_files}"
                            ),
                            retryable=True,
                            supervision_state="watchdog_killed",
                        )
                else:
                    final_message_missing_output_deadline_passes = 0
        else:
            final_message_missing_output_started_elapsed_seconds = None
            final_message_missing_output_deadline_elapsed_seconds = None
            final_message_missing_output_deadline_passes = 0
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
            **helper_completion,
            "workspace_authoritative_completion_ready": authoritative_completion_ready,
            "workspace_waiting_for_helper_visibility": bool(
                helper_completed_in_event_stream and not authoritative_completion_ready
            ),
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
            "final_message_missing_output_deadline_passes": (
                final_message_missing_output_deadline_passes
                if final_message_missing_output_grace_active
                else 0
            ),
            "workspace_completion_waiting_for_exit": completion_waiting_for_exit,
            "workspace_completion_quiescence_seconds": (
                completion_quiescence_seconds
                if completion_waiting_for_exit
                else None
            ),
            "workspace_completion_post_signal_observed": (
                completion_post_signal_observed
            ),
            "workspace_command_loop_max_count": _runtime_override(
                "_LINE_ROLE_WORKSPACE_MAX_COMMAND_COUNT",
                canonical_line_roles_module._LINE_ROLE_WORKSPACE_MAX_COMMAND_COUNT,
            ),
            "workspace_command_loop_max_repeat_count": _runtime_override(
                "_LINE_ROLE_WORKSPACE_MAX_REPEAT_COUNT",
                canonical_line_roles_module._LINE_ROLE_WORKSPACE_MAX_REPEAT_COUNT,
            ),
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
    from . import runtime as root

    return root.classify_taskfile_worker_command(
        command_text,
        single_file_worker_policy=single_file_worker_policy,
        single_file_stage_key="line_role",
    )


def _line_role_resume_reason_fields(
    *, resumed_from_existing_outputs: bool
) -> tuple[str, str]:
    if resumed_from_existing_outputs:
        return (
            "resume_existing_outputs",
            "all canonical line-role shard outputs were already durable on disk",
        )
    return (
        "no_tasks_assigned",
        "worker had no runnable canonical line-role shards",
    )


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
    labels = payload.get("labels")
    if isinstance(labels, list):
        compact_labels = [
            str(label).strip()
            for label in labels[:2]
            if str(label).strip()
        ]
        if not compact_labels:
            return None
        return {
            "shard_id": shard.shard_id,
            "owned_ids": list(shard.owned_ids),
            "output": {
                "labels": compact_labels,
            },
        }
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return None
    compact_labels = [
        str(row_payload.get("label") or "").strip()
        for row_payload in rows[:2]
        if isinstance(row_payload, Mapping) and str(row_payload.get("label") or "").strip()
    ]
    if not compact_labels:
        return None
    return {
        "shard_id": shard.shard_id,
        "owned_ids": list(shard.owned_ids),
        "output": {
            "labels": compact_labels,
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
            "labels_missing_or_not_a_list",
            "wrong_label_count",
            "extra_top_level_keys",
            "rows_missing_or_not_a_list",
            "row_not_a_json_object",
            "atomic_index_missing",
            "row_id_missing",
        }:
            return True
        if str(error).startswith(
            (
                "missing_owned_atomic_indices:",
                "duplicate_atomic_index:",
                "invalid_label:",
                "missing_row_ids:",
                "duplicate_row_id:",
                "unknown_row_id:",
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
    from . import runtime as root

    shard_root = worker_root / "shards" / shard.shard_id
    shard_root.mkdir(parents=True, exist_ok=True)
    (shard_root / "watchdog_retry_prompt.txt").write_text(prompt_text, encoding="utf-8")
    return runner.run_packet_worker(
        prompt_text=prompt_text,
        input_payload={
            "retry_mode": "line_role_watchdog",
            "pipeline_id": pipeline_id,
            "worker_id": worker_id,
            "v": root._LINE_ROLE_MODEL_PAYLOAD_VERSION,
            "shard_id": shard.shard_id,
            "rows": list((shard.input_payload or {}).get("rows") or []),
            "owned_ids": list(shard.owned_ids),
            "retry_reason": {
                "code": original_reason_code,
                "detail": original_reason_detail,
            },
            "successful_examples": [
                dict(example_payload) for example_payload in successful_examples
            ],
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
    from . import runtime as root

    row_count = len(list((shard.input_payload or {}).get("rows") or []))
    allowed_labels = ", ".join(root.CANONICAL_LINE_ROLE_ALLOWED_LABELS)
    authoritative_rows = root._render_line_role_authoritative_rows(shard)
    example_rows = [
        json.dumps(dict(example_payload), ensure_ascii=False, sort_keys=True)
        for example_payload in successful_examples[
            : root._LINE_ROLE_COHORT_WATCHDOG_MAX_EXAMPLES
        ]
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
        f"- Return one JSON object shaped like {{\"labels\":[\"<ALLOWED_LABEL>\"]}} with exactly {row_count} label(s).\n"
        "- Use only the top-level key `labels`.\n"
        "- Keep label order exactly aligned with the authoritative row order shown below.\n"
        "- The first label applies to the first row, the second label applies to the second row, and so on.\n"
        f"- Allowed labels: {allowed_labels}\n"
        "- Finish the full owned-row list; do not stop early.\n\n"
        "- Treat span codes and hint lists as weak hints only, not final truth.\n"
        "- `INGREDIENT_LINE` means quantity/unit ingredients or bare ingredient-list items.\n"
        "- `INSTRUCTION_LINE` means a recipe-local procedural step, not generic cooking advice.\n"
        "- `HOWTO_SECTION` means a recipe-internal subsection heading, not a chapter or topic heading.\n"
        "- `RECIPE_NOTES` means recipe-local prose that belongs with the current recipe.\n"
        "- `NONRECIPE_CANDIDATE` means outside-recipe material that should go to knowledge later.\n"
        "- `NONRECIPE_EXCLUDE` means obvious outside-recipe junk that should never go to knowledge.\n\n"
        f"Previous stop reason: {original_reason_code or '[unknown]'}\n"
        f"Reason detail: {original_reason_detail or '[none recorded]'}\n\n"
        "Authoritative shard rows to relabel:\n"
        "<BEGIN_AUTHORITATIVE_ROWS>\n"
        f"{authoritative_rows}\n"
        "<END_AUTHORITATIVE_ROWS>\n\n"
        "Each authoritative row is rendered as `rXX | block_index | text`.\n"
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
            row_payload["events_path"] = (
                str(events_path) if events_path is not None else None
            )
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
