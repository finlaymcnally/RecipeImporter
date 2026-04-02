from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cookimport.config.run_settings import (
    CODEX_EXEC_STYLE_INLINE_JSON_V1,
    normalize_codex_exec_style_value,
)
from . import _shared as _shared_module
from . import planning as _planning_module
from . import recovery as _recovery_module
from ..editable_task_file import (
    TASK_FILE_NAME,
    build_repair_task_file,
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
    build_task_file_answer_feedback,
    build_knowledge_classification_task_file,
    build_knowledge_grouping_task_files,
    combine_knowledge_task_file_outputs,
    validate_knowledge_classification_task_file,
    validate_knowledge_grouping_task_file,
)
from .structured_session_contract import (
    apply_answers_to_task_file as _apply_answers_to_task_file,
    apply_knowledge_same_session_row_metadata as _apply_knowledge_same_session_row_metadata,
    build_knowledge_edited_task_file_from_classification_response as _build_knowledge_edited_task_file_from_classification_response,
    build_knowledge_edited_task_file_from_grouping_response as _build_knowledge_edited_task_file_from_grouping_response,
    build_knowledge_structured_prompt as _build_knowledge_structured_prompt,
    knowledge_failed_unit_ids as _knowledge_failed_unit_ids,
    knowledge_merge_answers as _knowledge_merge_answers,
    knowledge_same_session_grounding_gate_metadata_by_shard as _knowledge_same_session_grounding_gate_metadata_by_shard,
    knowledge_task_file_to_structured_packet as _knowledge_task_file_to_structured_packet,
    render_validation_reason_detail as _render_validation_reason_detail,
    write_knowledge_task_file_snapshot as _write_task_file_snapshot,
)
from ..structured_session_runtime import (
    assert_structured_session_can_resume,
    initialize_structured_session_lineage,
    record_structured_session_turn,
)
from ..task_file_guardrails import (
    build_task_file_guardrail,
    build_worker_session_guardrails,
    summarize_task_file_guardrails,
)

for _module in (_shared_module, _planning_module, _recovery_module):
    globals().update(
        {name: value for name, value in vars(_module).items() if not name.startswith("__")}
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
        actual_happy_path_worker_sessions=int(summary.get("taskfile_session_count") or 0),
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


def _knowledge_retryable_runner_exception_reason(
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


def _knowledge_catastrophic_run_result_reason(
    run_result: CodexExecRunResult,
) -> str | None:
    if not _knowledge_hard_boundary_failure(run_result):
        return None
    reason_code = str(run_result.supervision_reason_code or "").strip()
    if reason_code:
        return reason_code
    if str(run_result.supervision_state or "").strip() == "watchdog_killed":
        return "watchdog_killed"
    return "catastrophic_worker_failure"


def _should_attempt_knowledge_fresh_worker_replacement(
    *,
    run_result: CodexExecRunResult | None = None,
    exc: CodexFarmRunnerError | None = None,
    replacement_attempt_count: int,
    same_session_state_payload: Mapping[str, Any],
) -> tuple[bool, str]:
    if int(replacement_attempt_count) >= 1:
        return False, "fresh_worker_replacement_budget_spent"
    if bool(same_session_state_payload.get("completed")):
        return False, "same_session_already_completed"
    if exc is not None:
        retry_reason = _knowledge_retryable_runner_exception_reason(exc)
        if retry_reason is None:
            return False, "runner_exception_not_retryable"
        return True, retry_reason
    if run_result is not None:
        retry_reason = _knowledge_catastrophic_run_result_reason(run_result)
        if retry_reason is None:
            return False, "worker_session_not_catastrophic"
        return True, retry_reason
    return False, "fresh_worker_replacement_not_applicable"


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


def _build_knowledge_runner_exception_result(
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
        events=(),
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


def _reset_knowledge_workspace_for_fresh_worker_replacement(
    *,
    worker_root: Path,
    assignment: WorkerAssignmentV1,
    assigned_shards: Sequence[ShardManifestEntryV1],
    task_file_payload: Mapping[str, Any],
    unit_to_shard_id: Mapping[str, str],
    out_dir: Path,
) -> dict[str, Any]:
    for artifact_name in (
        "events.jsonl",
        "last_message.json",
        "usage.json",
        "workspace_manifest.json",
        "stdout.txt",
        "stderr.txt",
        "prompt_grouping.txt",
        "prompt_resume.txt",
        "prompt_fresh_worker_replacement.txt",
    ):
        artifact_path = worker_root / artifact_name
        if artifact_path.exists():
            artifact_path.unlink()
    for shard in assigned_shards:
        output_path = out_dir / f"{shard.shard_id}.json"
        if output_path.exists():
            output_path.unlink()
    state_path = _knowledge_same_session_state_path(worker_root)
    replacement_state = initialize_knowledge_same_session_state(
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
    return replacement_state


def _build_knowledge_fresh_worker_replacement_prompt(
    *,
    shards: Sequence[ShardManifestEntryV1],
) -> str:
    return (
        "The previous knowledge worker session was stopped before completion. "
        "Start over from the fresh `task.json` that the repo has restored in this workspace. "
        "Do not rely on prior partial outputs or shell state.\n\n"
        + _build_knowledge_taskfile_prompt(
            stage_key=KNOWLEDGE_CLASSIFY_STAGE_KEY,
            shards=shards,
        )
    )


def _run_phase_knowledge_structured_worker_assignment_v1(
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
    settings: Mapping[str, Any],
    shard_completed_callback: Callable[..., None] | None,
    progress_state: _KnowledgePhaseProgressState | None,
) -> _DirectKnowledgeWorkerResult:
    worker_root = Path(assignment.workspace_root)
    out_dir = worker_root / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    shard_dir = worker_root / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)

    worker_failure_count = 0
    worker_proposal_count = 0
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    worker_runner_results: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    requested_shards = [shard_by_id[shard_id] for shard_id in assignment.shard_ids]

    for shard in requested_shards:
        preflight_failure = _preflight_knowledge_shard(shard)
        if preflight_failure is not None:
            reason_code = str(preflight_failure.get("reason_code") or "preflight_rejected")
            proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
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
            continue

        session_root = shard_dir / shard.shard_id / "structured_session"
        session_root.mkdir(parents=True, exist_ok=True)
        classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
            assignment=assignment,
            shards=[shard],
            knowledge_group_task_max_units=int(
                settings.get("knowledge_group_task_max_units") or 40
            ),
            knowledge_group_task_max_evidence_chars=int(
                settings.get("knowledge_group_task_max_evidence_chars") or 12000
            ),
        )
        classification_packet = _knowledge_task_file_to_structured_packet(
            task_file_payload=classification_task_file,
            packet_kind="classification_initial",
        )
        classification_prompt = _build_knowledge_structured_prompt(
            task_file_payload=classification_task_file,
            packet=classification_packet,
        )
        classification_packet_path = session_root / "classification_initial_packet.json"
        classification_prompt_path = session_root / "classification_initial_prompt.txt"
        classification_response_path = session_root / "classification_initial_response.json"
        classification_events_path = session_root / "classification_initial_events.jsonl"
        classification_last_message_path = session_root / "classification_initial_last_message.json"
        classification_usage_path = session_root / "classification_initial_usage.json"
        classification_workspace_manifest_path = (
            session_root / "classification_initial_workspace_manifest.json"
        )
        classification_packet_path.write_text(
            json.dumps(classification_packet, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        classification_prompt_path.write_text(classification_prompt, encoding="utf-8")
        initial_run_result = runner.run_packet_worker(
            prompt_text=classification_prompt,
            input_payload=classification_packet,
            working_dir=session_root,
            env=env,
            output_schema_path=None,
            model=model,
            reasoning_effort=reasoning_effort,
            persist_session=True,
            workspace_task_label="knowledge structured classification session",
        )
        execution_workspace = Path(initial_run_result.execution_working_dir or session_root)
        initialize_structured_session_lineage(
            worker_root=session_root,
            assignment_id=f"{assignment.worker_id}:{shard.shard_id}",
            execution_working_dir=execution_workspace,
        )
        classification_response_path.write_text(
            str(initial_run_result.response_text or ""),
            encoding="utf-8",
        )
        classification_events_path.write_text(
            _render_events_jsonl(initial_run_result.events),
            encoding="utf-8",
        )
        _write_json(
            {"text": initial_run_result.response_text},
            classification_last_message_path,
        )
        _write_json(dict(initial_run_result.usage or {}), classification_usage_path)
        _write_json(
            initial_run_result.workspace_manifest(),
            classification_workspace_manifest_path,
        )
        record_structured_session_turn(
            worker_root=session_root,
            execution_working_dir=execution_workspace,
            turn_kind="classification_initial",
            packet_path=classification_packet_path,
            prompt_path=classification_prompt_path,
            response_path=classification_response_path,
        )
        worker_runner_results.append(
            _build_knowledge_inline_attempt_runner_payload(
                pipeline_id=pipeline_id,
                worker_id=assignment.worker_id,
                shard_id=shard.shard_id,
                run_result=initial_run_result,
                model=model,
                reasoning_effort=reasoning_effort,
                prompt_input_mode="structured_session_classification_initial",
                events_path=classification_events_path,
                last_message_path=classification_last_message_path,
                usage_path=classification_usage_path,
                workspace_manifest_path=classification_workspace_manifest_path,
            )
        )

        edited_classification_task_file, parse_errors, parse_metadata = (
            _build_knowledge_edited_task_file_from_classification_response(
                original_task_file=classification_task_file,
                response_text=initial_run_result.response_text,
            )
        )
        classification_answers_by_unit_id: dict[str, dict[str, Any]] = {}
        classification_validation_errors: tuple[str, ...] = ()
        classification_validation_metadata: dict[str, Any] = {}
        if edited_classification_task_file is None:
            classification_validation_errors = tuple(parse_errors)
            classification_validation_metadata = dict(parse_metadata)
        else:
            (
                answers_by_unit_id,
                validation_errors,
                validation_metadata,
            ) = validate_knowledge_classification_task_file(
                original_task_file=classification_task_file,
                edited_task_file=edited_classification_task_file,
            )
            classification_answers_by_unit_id = _knowledge_merge_answers(
                {},
                dict(validation_metadata.get("validated_answers_by_unit_id") or {}),
            )
            classification_answers_by_unit_id = _knowledge_merge_answers(
                classification_answers_by_unit_id,
                answers_by_unit_id,
            )
            classification_validation_errors = tuple(validation_errors)
            classification_validation_metadata = dict(validation_metadata)

        if classification_validation_errors or classification_validation_metadata.get("error_details"):
            repair_task_file = build_repair_task_file(
                original_task_file=classification_task_file,
                failed_unit_ids=_knowledge_failed_unit_ids(
                    task_file_payload=classification_task_file,
                    validation_metadata=classification_validation_metadata,
                ),
                previous_answers_by_unit_id=classification_answers_by_unit_id,
                validation_feedback_by_unit_id=build_task_file_answer_feedback(
                    validation_errors=classification_validation_errors,
                    validation_metadata=classification_validation_metadata,
                ),
            )
            repair_packet = _knowledge_task_file_to_structured_packet(
                task_file_payload=repair_task_file,
                packet_kind="classification_repair",
                validation_errors=classification_validation_errors,
            )
            repair_prompt = _build_knowledge_structured_prompt(
                task_file_payload=repair_task_file,
                packet=repair_packet,
            )
            repair_packet_path = session_root / "classification_repair_packet_01.json"
            repair_prompt_path = session_root / "classification_repair_prompt_01.txt"
            repair_response_path = session_root / "classification_repair_response_01.json"
            repair_events_path = session_root / "classification_repair_events_01.jsonl"
            repair_last_message_path = session_root / "classification_repair_last_message_01.json"
            repair_usage_path = session_root / "classification_repair_usage_01.json"
            repair_workspace_manifest_path = (
                session_root / "classification_repair_workspace_manifest_01.json"
            )
            repair_packet_path.write_text(
                json.dumps(repair_packet, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            repair_prompt_path.write_text(repair_prompt, encoding="utf-8")
            assert_structured_session_can_resume(
                worker_root=session_root,
                execution_working_dir=execution_workspace,
            )
            repair_run_result = runner.run_packet_worker(
                prompt_text=repair_prompt,
                input_payload=repair_packet,
                working_dir=session_root,
                env=env,
                output_schema_path=None,
                model=model,
                reasoning_effort=reasoning_effort,
                resume_last=True,
                prepared_execution_working_dir=execution_workspace,
                workspace_task_label="knowledge structured classification repair session",
            )
            repair_response_path.write_text(
                str(repair_run_result.response_text or ""),
                encoding="utf-8",
            )
            repair_events_path.write_text(
                _render_events_jsonl(repair_run_result.events),
                encoding="utf-8",
            )
            _write_json({"text": repair_run_result.response_text}, repair_last_message_path)
            _write_json(dict(repair_run_result.usage or {}), repair_usage_path)
            _write_json(
                repair_run_result.workspace_manifest(),
                repair_workspace_manifest_path,
            )
            record_structured_session_turn(
                worker_root=session_root,
                execution_working_dir=execution_workspace,
                turn_kind="classification_repair",
                packet_path=repair_packet_path,
                prompt_path=repair_prompt_path,
                response_path=repair_response_path,
            )
            worker_runner_results.append(
                _build_knowledge_inline_attempt_runner_payload(
                    pipeline_id=pipeline_id,
                    worker_id=assignment.worker_id,
                    shard_id=shard.shard_id,
                    run_result=repair_run_result,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    prompt_input_mode="structured_session_classification_repair",
                    events_path=repair_events_path,
                    last_message_path=repair_last_message_path,
                    usage_path=repair_usage_path,
                    workspace_manifest_path=repair_workspace_manifest_path,
                )
            )
            repair_edited_task_file, repair_parse_errors, repair_parse_metadata = (
                _build_knowledge_edited_task_file_from_classification_response(
                    original_task_file=repair_task_file,
                    response_text=repair_run_result.response_text,
                )
            )
            if repair_edited_task_file is None:
                classification_validation_errors = tuple(repair_parse_errors)
                classification_validation_metadata = dict(repair_parse_metadata)
            else:
                (
                    repair_answers_by_unit_id,
                    _repair_errors,
                    repair_validation_metadata,
                ) = validate_knowledge_classification_task_file(
                    original_task_file=repair_task_file,
                    edited_task_file=repair_edited_task_file,
                )
                classification_answers_by_unit_id = _knowledge_merge_answers(
                    classification_answers_by_unit_id,
                    dict(repair_validation_metadata.get("validated_answers_by_unit_id") or {}),
                )
                classification_answers_by_unit_id = _knowledge_merge_answers(
                    classification_answers_by_unit_id,
                    repair_answers_by_unit_id,
                )
                final_classification_task_file = _apply_answers_to_task_file(
                    original_task_file=classification_task_file,
                    answers_by_unit_id=classification_answers_by_unit_id,
                )
                (
                    _final_answers,
                    classification_validation_errors,
                    classification_validation_metadata,
                ) = validate_knowledge_classification_task_file(
                    original_task_file=classification_task_file,
                    edited_task_file=final_classification_task_file,
                )
                classification_answers_by_unit_id = _knowledge_merge_answers(
                    classification_answers_by_unit_id,
                    dict(
                        classification_validation_metadata.get("validated_answers_by_unit_id") or {}
                    ),
                )

        if classification_validation_errors or classification_validation_metadata.get("error_details"):
            worker_failure_count += 1
            worker_failures.append(
                {
                    "worker_id": assignment.worker_id,
                    "shard_id": shard.shard_id,
                    "reason": "classification_validation_failed",
                    "validation_errors": list(classification_validation_errors),
                }
            )
            proposal_payload = None
            proposal_status = "invalid"
            proposal_metadata = dict(classification_validation_metadata)
            proposal_errors = tuple(classification_validation_errors)
        else:
            grouping_answers_by_unit_id: dict[str, dict[str, Any]] = {}
            grouping_task_files, _grouping_unit_to_shard_id, _grouping_batches = (
                build_knowledge_grouping_task_files(
                    assignment_id=str(classification_task_file.get("assignment_id") or ""),
                    worker_id=str(classification_task_file.get("worker_id") or ""),
                    classification_task_file=classification_task_file,
                    classification_answers_by_unit_id=classification_answers_by_unit_id,
                    unit_to_shard_id=unit_to_shard_id,
                    max_units_per_batch=int(
                        settings.get("knowledge_group_task_max_units") or 40
                    ),
                    max_evidence_chars_per_batch=int(
                        settings.get("knowledge_group_task_max_evidence_chars") or 12000
                    ),
                )
            )
            grouping_failed = False
            for batch_index, grouping_task_file in enumerate(grouping_task_files, start=1):
                grouping_packet = _knowledge_task_file_to_structured_packet(
                    task_file_payload=grouping_task_file,
                    packet_kind=f"grouping_{batch_index}",
                )
                grouping_prompt = _build_knowledge_structured_prompt(
                    task_file_payload=grouping_task_file,
                    packet=grouping_packet,
                )
                grouping_packet_path = session_root / f"grouping_packet_{batch_index:02d}.json"
                grouping_prompt_path = session_root / f"grouping_prompt_{batch_index:02d}.txt"
                grouping_response_path = session_root / f"grouping_response_{batch_index:02d}.json"
                grouping_events_path = session_root / f"grouping_events_{batch_index:02d}.jsonl"
                grouping_last_message_path = session_root / f"grouping_last_message_{batch_index:02d}.json"
                grouping_usage_path = session_root / f"grouping_usage_{batch_index:02d}.json"
                grouping_workspace_manifest_path = (
                    session_root / f"grouping_workspace_manifest_{batch_index:02d}.json"
                )
                grouping_packet_path.write_text(
                    json.dumps(grouping_packet, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                grouping_prompt_path.write_text(grouping_prompt, encoding="utf-8")
                assert_structured_session_can_resume(
                    worker_root=session_root,
                    execution_working_dir=execution_workspace,
                )
                grouping_run_result = runner.run_packet_worker(
                    prompt_text=grouping_prompt,
                    input_payload=grouping_packet,
                    working_dir=session_root,
                    env=env,
                    output_schema_path=None,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    resume_last=True,
                    prepared_execution_working_dir=execution_workspace,
                    workspace_task_label="knowledge structured grouping session",
                )
                grouping_response_path.write_text(
                    str(grouping_run_result.response_text or ""),
                    encoding="utf-8",
                )
                grouping_events_path.write_text(
                    _render_events_jsonl(grouping_run_result.events),
                    encoding="utf-8",
                )
                _write_json({"text": grouping_run_result.response_text}, grouping_last_message_path)
                _write_json(dict(grouping_run_result.usage or {}), grouping_usage_path)
                _write_json(
                    grouping_run_result.workspace_manifest(),
                    grouping_workspace_manifest_path,
                )
                record_structured_session_turn(
                    worker_root=session_root,
                    execution_working_dir=execution_workspace,
                    turn_kind=f"grouping_{batch_index}",
                    packet_path=grouping_packet_path,
                    prompt_path=grouping_prompt_path,
                    response_path=grouping_response_path,
                )
                worker_runner_results.append(
                    _build_knowledge_inline_attempt_runner_payload(
                        pipeline_id=pipeline_id,
                        worker_id=assignment.worker_id,
                        shard_id=shard.shard_id,
                        run_result=grouping_run_result,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        prompt_input_mode="structured_session_grouping",
                        events_path=grouping_events_path,
                        last_message_path=grouping_last_message_path,
                        usage_path=grouping_usage_path,
                        workspace_manifest_path=grouping_workspace_manifest_path,
                    )
                )
                grouping_edited_task_file, grouping_parse_errors, grouping_parse_metadata = (
                    _build_knowledge_edited_task_file_from_grouping_response(
                        original_task_file=grouping_task_file,
                        response_text=grouping_run_result.response_text,
                    )
                )
                if grouping_edited_task_file is None:
                    grouping_validation_errors = tuple(grouping_parse_errors)
                    grouping_validation_metadata = dict(grouping_parse_metadata)
                else:
                    (
                        grouping_batch_answers_by_unit_id,
                        grouping_validation_errors,
                        grouping_validation_metadata,
                    ) = validate_knowledge_grouping_task_file(
                        original_task_file=grouping_task_file,
                        edited_task_file=grouping_edited_task_file,
                    )
                    grouping_answers_by_unit_id = _knowledge_merge_answers(
                        grouping_answers_by_unit_id,
                        dict(
                            grouping_validation_metadata.get("validated_answers_by_unit_id") or {}
                        ),
                    )
                    grouping_answers_by_unit_id = _knowledge_merge_answers(
                        grouping_answers_by_unit_id,
                        grouping_batch_answers_by_unit_id,
                    )
                if grouping_validation_errors or grouping_validation_metadata.get("error_details"):
                    grouping_failed = True
                    proposal_payload = None
                    proposal_status = "invalid"
                    proposal_metadata = dict(grouping_validation_metadata)
                    proposal_errors = tuple(grouping_validation_errors)
                    break
            if not grouping_failed:
                proposal_payload = combine_knowledge_task_file_outputs(
                    classification_task_file=classification_task_file,
                    classification_answers_by_unit_id=classification_answers_by_unit_id,
                    grouping_answers_by_unit_id=grouping_answers_by_unit_id,
                    unit_to_shard_id=unit_to_shard_id,
                ).get(shard.shard_id)
                proposal_status = "validated" if proposal_payload is not None else "invalid"
                proposal_metadata = dict(classification_validation_metadata)
                proposal_errors = ()

        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        _write_json(
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": proposal_payload,
                "validation_errors": list(proposal_errors),
                "validation_metadata": proposal_metadata,
            },
            proposal_path,
        )
        if proposal_payload is not None:
            _write_json(proposal_payload, out_dir / f"{shard.shard_id}.json")
            worker_proposal_count += 1
        else:
            worker_failure_count += 1
            worker_failures.append(
                {
                    "worker_id": assignment.worker_id,
                    "shard_id": shard.shard_id,
                    "reason": "structured_validation_failed",
                    "validation_errors": list(proposal_errors),
                }
            )
        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status=proposal_status,
                proposal_path=_relative_path(run_root, proposal_path),
                payload=proposal_payload if proposal_payload is not None else None,
                validation_errors=tuple(proposal_errors),
                metadata=dict(proposal_metadata or {}),
            )
        )
        if progress_state is not None:
            progress_state.mark_task_packet_terminal(
                worker_id=assignment.worker_id,
                task_id=shard.shard_id,
            )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    worker_runner_payload = _aggregate_worker_runner_payload(
        pipeline_id=pipeline_id,
        worker_runs=worker_runner_results,
        stage_rows=stage_rows if stage_rows else None,
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
                "output_schema_enforced": True,
                "tool_affordances_requested": False,
            },
            runner_result=worker_runner_payload,
            metadata={
                "out_dir": _relative_path(run_root, out_dir),
                "codex_exec_style": CODEX_EXEC_STYLE_INLINE_JSON_V1,
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
        stage_rows=tuple(stage_rows),
        worker_runner_payload=worker_runner_payload,
    )


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
    settings: Mapping[str, Any],
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
    if (
        normalize_codex_exec_style_value(settings.get("codex_exec_style"))
        == CODEX_EXEC_STYLE_INLINE_JSON_V1
    ):
        return _run_phase_knowledge_structured_worker_assignment_v1(
            run_root=run_root,
            assignment=assignment,
            artifacts=artifacts,
            shard_by_id=shard_by_id,
            runner=runner,
            pipeline_id=pipeline_id,
            env=env,
            model=model,
            reasoning_effort=reasoning_effort,
            settings=settings,
            shard_completed_callback=shard_completed_callback,
            progress_state=progress_state,
        )

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
            knowledge_group_task_max_units=int(
                settings.get("knowledge_group_task_max_units") or 40
            ),
            knowledge_group_task_max_evidence_chars=int(
                settings.get("knowledge_group_task_max_evidence_chars") or 12000
            ),
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
    worker_session_runs: list[dict[str, Any]] = []
    fresh_session_retry_count = 0
    fresh_session_retry_status = "not_attempted"
    same_session_state_payload: dict[str, Any] = {}
    fresh_worker_replacement_count = 0
    fresh_worker_replacement_status = "not_attempted"
    fresh_worker_replacement_metadata: dict[str, Any] = {}
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
        classification_prompt_text = _build_knowledge_taskfile_prompt(
            stage_key=KNOWLEDGE_CLASSIFY_STAGE_KEY,
            shards=assigned_shards,
        )
        prompt_path = worker_root / "prompt_classification.txt"
        prompt_path.write_text(classification_prompt_text, encoding="utf-8")
        watchdog_callback = _build_strict_json_watchdog_callback(
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
            workspace_completion_quiescence_seconds=float(
                settings.get("workspace_completion_quiescence_seconds") or 15.0
            ),
        )

        def _run_workspace_attempt(
            *,
            prompt_text: str,
            workspace_task_label: str,
        ) -> tuple[CodexExecRunResult, CodexFarmRunnerError | None, dict[str, Any]]:
            attempt_exception: CodexFarmRunnerError | None = None
            try:
                current_run_result = runner.run_taskfile_worker(
                    prompt_text=prompt_text,
                    working_dir=worker_root,
                    env={
                        **dict(env),
                        KNOWLEDGE_SAME_SESSION_STATE_ENV: str(state_path),
                    },
                    model=model,
                    reasoning_effort=reasoning_effort,
                    completed_termination_grace_seconds=float(
                        settings.get("completed_termination_grace_seconds") or 15.0
                    ),
                    workspace_task_label=workspace_task_label,
                    supervision_callback=watchdog_callback,
                )
            except CodexFarmRunnerError as exc:
                attempt_exception = exc
                current_run_result = _build_knowledge_runner_exception_result(
                    exc=exc,
                    prompt_text=prompt_text,
                    working_dir=worker_root,
                    retryable_reason=_knowledge_retryable_runner_exception_reason(exc),
                )
            semantic_run_results.append(current_run_result)
            _finalize_live_status(
                worker_root / "live_status.json",
                run_result=current_run_result,
                watchdog_policy="taskfile_v1",
            )
            (worker_root / "events.jsonl").write_text(
                _render_events_jsonl(current_run_result.events),
                encoding="utf-8",
            )
            _write_json(
                {"text": current_run_result.response_text},
                worker_root / "last_message.json",
            )
            _write_json(dict(current_run_result.usage or {}), worker_root / "usage.json")
            _write_json(
                current_run_result.workspace_manifest(),
                worker_root / "workspace_manifest.json",
            )
            _write_optional_text(worker_root / "stdout.txt", current_run_result.stdout_text)
            _write_optional_text(worker_root / "stderr.txt", current_run_result.stderr_text)
            return current_run_result, attempt_exception, _load_json_dict_safely(state_path)

        run_result, initial_runner_exception, same_session_state_payload = _run_workspace_attempt(
            prompt_text=classification_prompt_text,
            workspace_task_label="knowledge same-session worker session",
        )
        worker_session_runs: list[dict[str, Any]] = [
            {
                "run_result": run_result,
                "prompt_path": prompt_path,
                "fresh_session_resume": False,
                "fresh_worker_replacement": False,
                "fresh_worker_replacement_reason_code": None,
            }
        ]
        should_replace_worker, replacement_reason = _should_attempt_knowledge_fresh_worker_replacement(
            run_result=None if initial_runner_exception is not None else run_result,
            exc=initial_runner_exception,
            replacement_attempt_count=fresh_worker_replacement_count,
            same_session_state_payload=same_session_state_payload,
        )
        fresh_worker_replacement_metadata = {
            "fresh_worker_replacement_attempted": bool(should_replace_worker),
            "fresh_worker_replacement_status": (
                "attempted" if should_replace_worker else "skipped"
            ),
            "fresh_worker_replacement_count": 0,
            "fresh_worker_replacement_reason_code": (
                replacement_reason if should_replace_worker else None
            ),
            "fresh_worker_replacement_error_summary": (
                str(initial_runner_exception)
                if initial_runner_exception is not None
                else str(run_result.supervision_reason_detail or "").strip() or None
            ),
            "fresh_worker_replacement_skipped_reason": (
                None if should_replace_worker else replacement_reason
            ),
        }
        if should_replace_worker:
            fresh_worker_replacement_count = 1
            fresh_worker_replacement_status = "attempted"
            same_session_state_payload = _reset_knowledge_workspace_for_fresh_worker_replacement(
                worker_root=worker_root,
                assignment=assignment,
                assigned_shards=assigned_shards,
                task_file_payload=task_file_payload,
                unit_to_shard_id=unit_to_shard_id,
                out_dir=out_dir,
            )
            replacement_prompt_path = worker_root / "prompt_fresh_worker_replacement.txt"
            replacement_prompt_text = _build_knowledge_fresh_worker_replacement_prompt(
                shards=assigned_shards,
            )
            replacement_prompt_path.write_text(
                replacement_prompt_text,
                encoding="utf-8",
            )
            run_result, _replacement_exception, same_session_state_payload = _run_workspace_attempt(
                prompt_text=replacement_prompt_text,
                workspace_task_label="knowledge fresh-worker replacement session",
            )
            worker_session_runs.append(
                {
                    "run_result": run_result,
                    "prompt_path": replacement_prompt_path,
                    "fresh_session_resume": False,
                    "fresh_worker_replacement": True,
                    "fresh_worker_replacement_reason_code": replacement_reason,
                }
            )
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
            same_session_state_payload["fresh_session_retry_history"] = (
                fresh_session_retry_history
            )
            _write_json(same_session_state_payload, state_path)
            current_task_file = load_task_file(worker_root / TASK_FILE_NAME)
            resume_prompt_path = worker_root / "prompt_resume.txt"
            resume_prompt_text = _build_knowledge_taskfile_prompt(
                stage_key=str(
                    current_task_file.get("stage_key")
                    or same_session_state_payload.get("current_stage_key")
                    or KNOWLEDGE_CLASSIFY_STAGE_KEY
                ),
                shards=assigned_shards,
                fresh_session_resume=True,
            )
            resume_prompt_path.write_text(resume_prompt_text, encoding="utf-8")
            run_result, _resume_exception, same_session_state_payload = _run_workspace_attempt(
                prompt_text=resume_prompt_text,
                workspace_task_label="knowledge fresh-session worker recovery",
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
                            "result_completed": bool(
                                same_session_state_payload.get("completed")
                            ),
                            "result_final_status": same_session_state_payload.get(
                                "final_status"
                            ),
                        }
                        if index == len(fresh_session_retry_history) - 1
                        else {}
                    ),
                }
                for index, row in enumerate(fresh_session_retry_history)
                if isinstance(row, Mapping)
            ]
            _write_json(same_session_state_payload, state_path)
            worker_session_runs.append(
                {
                    "run_result": run_result,
                    "prompt_path": resume_prompt_path,
                    "fresh_session_resume": True,
                    "fresh_worker_replacement": False,
                    "fresh_worker_replacement_reason_code": None,
                }
            )
        for session_index, session_row in enumerate(worker_session_runs, start=1):
            session_run_result = session_row["run_result"]
            session_prompt_path = session_row["prompt_path"]
            fresh_session_resume = bool(session_row.get("fresh_session_resume"))
            fresh_worker_replacement = bool(
                session_row.get("fresh_worker_replacement")
            )
            fresh_worker_replacement_reason_code = session_row.get(
                "fresh_worker_replacement_reason_code"
            )
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
                        row["fresh_worker_replacement"] = (
                            fresh_worker_replacement
                        )
                        row["fresh_worker_replacement_reason_code"] = (
                            fresh_worker_replacement_reason_code
                        )
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
            worker_runner_payload["fresh_worker_replacement"] = (
                fresh_worker_replacement
            )
            worker_runner_payload["fresh_worker_replacement_reason_code"] = (
                fresh_worker_replacement_reason_code
            )
            _attach_worker_guardrail_summary(
                worker_runner_payload=worker_runner_payload,
                task_file_guardrail=task_file_guardrail,
                planned_happy_path_worker_cap=3,
            )
            worker_runner_results.append(worker_runner_payload)
        classify_answers_by_unit_id = (
            dict(same_session_state_payload.get("classification_answers_by_unit_id") or {})
            or None
        )
        grouping_answers_by_unit_id = dict(
            same_session_state_payload.get("grouping_answers_by_unit_id") or {}
        )
        if fresh_worker_replacement_count > 0:
            recovered_output_count = sum(
                1
                for shard in assigned_shards
                if (out_dir / f"{shard.shard_id}.json").exists()
            )
            fresh_worker_replacement_status = (
                "recovered"
                if recovered_output_count > 0 or bool(same_session_state_payload.get("completed"))
                else "exhausted"
            )
            fresh_worker_replacement_metadata = {
                **fresh_worker_replacement_metadata,
                "fresh_worker_replacement_attempted": True,
                "fresh_worker_replacement_status": fresh_worker_replacement_status,
                "fresh_worker_replacement_count": fresh_worker_replacement_count,
                "fresh_worker_replacement_skipped_reason": None,
            }

    task_total = len(assigned_shards)
    run_result = semantic_run_results[-1]
    worker_prompt_path = Path(
        worker_session_runs[-1]["prompt_path"]
        if task_file_payload is not None and worker_session_runs
        else (
            worker_root / "prompt_grouping.txt"
            if (worker_root / "prompt_grouping.txt").exists()
            else worker_root / "prompt_classification.txt"
        )
    )
    task_file_errors_by_shard: dict[str, tuple[tuple[str, ...], dict[str, Any]]] = {}
    same_session_grounding_gate_metadata_by_shard: dict[str, dict[str, Any]] = {}
    if task_file_payload is not None:
        same_session_grounding_gate_metadata_by_shard = (
            _knowledge_same_session_grounding_gate_metadata_by_shard(
                initial_task_file=task_file_payload,
                state_payload=same_session_state_payload,
            )
        )
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
        if shard.shard_id in same_session_grounding_gate_metadata_by_shard:
            validation_metadata.update(
                dict(same_session_grounding_gate_metadata_by_shard[shard.shard_id])
            )
        if fresh_worker_replacement_metadata:
            validation_metadata["fresh_worker_replacement"] = dict(
                fresh_worker_replacement_metadata
            )
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
    worker_runner_payload["fresh_worker_replacement_count"] = (
        fresh_worker_replacement_count
    )
    worker_runner_payload["fresh_worker_replacement_status"] = (
        fresh_worker_replacement_status
    )
    if fresh_worker_replacement_metadata:
        worker_runner_payload.update(dict(fresh_worker_replacement_metadata))
    _attach_worker_guardrail_summary(
        worker_runner_payload=worker_runner_payload,
        task_file_guardrail=task_file_guardrail,
        planned_happy_path_worker_cap=3,
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
                "fresh_worker_replacement_count": fresh_worker_replacement_count,
                "fresh_worker_replacement_status": fresh_worker_replacement_status,
                **dict(fresh_worker_replacement_metadata),
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
        stage_rows=tuple(stage_rows),
        worker_runner_payload=worker_runner_payload,
    )
