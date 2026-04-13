from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cookimport.config.run_settings import (
    CODEX_EXEC_STYLE_INLINE_JSON_V1,
    normalize_codex_exec_style_value,
    normalize_structured_repair_transcript_mode_value,
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
from ..repair_recovery_policy import (
    FOLLOWUP_KIND_FRESH_SESSION_RETRY,
    FOLLOWUP_KIND_FRESH_WORKER_REPLACEMENT,
    FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE,
    FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP,
    INLINE_JSON_TRANSPORT,
    KNOWLEDGE_CLASSIFY_STEP_KEY,
    KNOWLEDGE_GROUP_STEP_KEY,
    KNOWLEDGE_POLICY_STAGE_KEY,
    TASKFILE_TRANSPORT,
    build_followup_budget_summary,
    inline_repair_policy_summary,
    should_attempt_taskfile_fresh_session_retry,
    should_attempt_taskfile_fresh_worker_replacement,
    structured_repair_followup_limit,
    taskfile_same_session_repair_rewrite_limit,
    taskfile_recovery_policy_summary,
    taskfile_structured_repair_policy_summary,
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
    canonicalize_knowledge_grouping_answer_ids,
    combine_knowledge_task_file_outputs,
    collect_knowledge_resolution_metadata_by_shard,
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
    knowledge_same_session_resolution_metadata_by_shard as _knowledge_same_session_resolution_metadata_by_shard,
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
from ..codex_farm_knowledge_ingest import sanitize_knowledge_worker_payload_for_shard

for _module in (_shared_module, _planning_module, _recovery_module):
    globals().update(
        {name: value for name, value in vars(_module).items() if not name.startswith("__")}
    )


def _render_events_jsonl(events: tuple[dict[str, Any], ...]) -> str:
    if not events:
        return ""
    return "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)


def _knowledge_inline_repair_should_resume(settings: Mapping[str, Any]) -> bool:
    return normalize_structured_repair_transcript_mode_value(
        settings.get("knowledge_inline_repair_transcript_mode")
    ) == "resume"


_KNOWLEDGE_FINAL_VALIDATION_BLOCK_METADATA_KEYS: tuple[tuple[str, str], ...] = (
    (
        "knowledge_blocks_missing_group",
        "this kept row is still missing a valid final group after shard merge.",
    ),
    (
        "knowledge_group_grounding_mismatch_blocks",
        "this row's final group grounding does not match the row grounding after shard merge.",
    ),
    (
        "knowledge_blocks_with_group_conflicts",
        "this row ended up assigned to conflicting groups after shard merge.",
    ),
    (
        "group_blocks_out_of_surface",
        "this final group references a row that does not belong in a knowledge group.",
    ),
    (
        "knowledge_grounding_existing_tag_required_blocks",
        "this row must use an existing tag because the proposed tag conflicts with the catalog.",
    ),
    (
        "missing_owned_block_indices",
        "this row is missing from the final merged shard output.",
    ),
)


def _knowledge_task_file_unit_ids(task_file_payload: Mapping[str, Any]) -> list[str]:
    return [
        str(unit.get("unit_id") or "").strip()
        for unit in (task_file_payload.get("units") or [])
        if isinstance(unit, Mapping) and str(unit.get("unit_id") or "").strip()
    ]


def _build_knowledge_whole_shard_grouping_validation_feedback(
    *,
    task_file_payload: Mapping[str, Any],
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    unit_id_by_block_index: dict[int, str] = {}
    for unit in task_file_payload.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_id = str(unit.get("unit_id") or "").strip()
        evidence = _coerce_dict(unit.get("evidence"))
        block_index = evidence.get("block_index")
        if not unit_id or block_index is None:
            continue
        unit_id_by_block_index[int(block_index)] = unit_id

    feedback_by_unit_id: dict[str, dict[str, Any]] = {}

    def _append_feedback(
        *,
        unit_id: str,
        error_code: str,
        block_index: int,
        message: str,
    ) -> None:
        row = feedback_by_unit_id.setdefault(
            unit_id,
            {
                "validation_errors": [],
                "error_details": [],
            },
        )
        validation_error_rows = row.setdefault("validation_errors", [])
        if error_code not in validation_error_rows:
            validation_error_rows.append(error_code)
        row.setdefault("error_details", []).append(
            {
                "code": error_code,
                "block_index": int(block_index),
                "message": message,
            }
        )

    for metadata_key, message in _KNOWLEDGE_FINAL_VALIDATION_BLOCK_METADATA_KEYS:
        for block_index in validation_metadata.get(metadata_key) or []:
            unit_id = unit_id_by_block_index.get(int(block_index))
            if unit_id is None:
                continue
            for error_code in validation_errors:
                _append_feedback(
                    unit_id=unit_id,
                    error_code=str(error_code).strip(),
                    block_index=int(block_index),
                    message=message,
                )
    return feedback_by_unit_id


def _build_knowledge_whole_shard_grouping_repair_task_file(
    *,
    assignment_id: str,
    worker_id: str,
    shard_id: str,
    classification_task_file: Mapping[str, Any],
    classification_answers_by_unit_id: Mapping[str, Mapping[str, Any]],
    grouping_answers_by_unit_id: Mapping[str, Mapping[str, Any]],
    unit_to_shard_id: Mapping[str, str],
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    shard_unit_to_shard_id = {
        str(unit_id): str(owner_shard_id)
        for unit_id, owner_shard_id in dict(unit_to_shard_id).items()
        if str(unit_id).strip() and str(owner_shard_id).strip() == str(shard_id).strip()
    }
    if not shard_unit_to_shard_id:
        return None, None
    shard_grouping_task_files, _grouping_unit_to_shard_id, _batch_unit_ids = (
        build_knowledge_grouping_task_files(
            assignment_id=assignment_id,
            worker_id=worker_id,
            classification_task_file=classification_task_file,
            classification_answers_by_unit_id=classification_answers_by_unit_id,
            unit_to_shard_id=shard_unit_to_shard_id,
            max_units_per_batch=max(1, len(shard_unit_to_shard_id)),
            max_evidence_chars_per_batch=10**9,
        )
    )
    if not shard_grouping_task_files:
        return None, None
    shard_grouping_task_file = dict(shard_grouping_task_files[0])
    shard_unit_ids = _knowledge_task_file_unit_ids(shard_grouping_task_file)
    if not shard_unit_ids:
        return None, None
    repair_task_file = build_repair_task_file(
        original_task_file=shard_grouping_task_file,
        failed_unit_ids=shard_unit_ids,
        previous_answers_by_unit_id={
            unit_id: dict(grouping_answers_by_unit_id.get(unit_id) or {})
            for unit_id in shard_unit_ids
            if isinstance(grouping_answers_by_unit_id.get(unit_id), Mapping)
        },
        validation_feedback_by_unit_id=_build_knowledge_whole_shard_grouping_validation_feedback(
            task_file_payload=shard_grouping_task_file,
            validation_errors=validation_errors,
            validation_metadata=validation_metadata,
        ),
        repair_validation_errors=validation_errors,
        repair_validation_metadata=validation_metadata,
    )
    return repair_task_file, shard_grouping_task_file


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


def _knowledge_validation_blocked(
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
) -> bool:
    return bool(validation_errors) or bool(validation_metadata.get("error_details"))


def _knowledge_same_session_repair_counts_by_step(
    state_payload: Mapping[str, Any],
) -> dict[str, int]:
    counts = {
        KNOWLEDGE_CLASSIFY_STEP_KEY: 0,
        KNOWLEDGE_GROUP_STEP_KEY: 0,
    }
    for transition_row in state_payload.get("transition_history") or ():
        if not isinstance(transition_row, Mapping):
            continue
        if str(transition_row.get("status") or "").strip() != "repair_required":
            continue
        current_stage_key = str(transition_row.get("current_stage_key") or "").strip()
        if current_stage_key in counts:
            counts[current_stage_key] += 1
    return counts


def _merge_knowledge_response_contract_diagnostics(
    *,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
    parse_errors: Sequence[str],
    parse_metadata: Mapping[str, Any],
) -> tuple[tuple[str, ...], dict[str, Any]]:
    merged_errors = [
        str(error).strip()
        for error in validation_errors
        if str(error).strip()
    ]
    for error in parse_errors:
        cleaned = str(error).strip()
        if cleaned:
            merged_errors.append(cleaned)
    merged_metadata = dict(validation_metadata)
    merged_error_details = [
        dict(detail)
        for detail in (validation_metadata.get("error_details") or [])
        if isinstance(detail, Mapping)
    ]
    merged_error_details.extend(
        dict(detail)
        for detail in (parse_metadata.get("error_details") or [])
        if isinstance(detail, Mapping)
    )
    if merged_error_details:
        merged_metadata["error_details"] = merged_error_details
    if parse_metadata.get("parse_error") is not None:
        merged_metadata["parse_error"] = parse_metadata.get("parse_error")
    for key in (
        "failed_unit_ids",
        "unresolved_block_indices",
        "missing_block_indices",
        "unexpected_block_indices",
        "duplicate_block_indices",
        "missing_row_ids",
        "unknown_row_ids",
        "duplicate_row_ids",
    ):
        existing_values = [
            value for value in (validation_metadata.get(key) or []) if value is not None
        ]
        next_values = [value for value in (parse_metadata.get(key) or []) if value is not None]
        if existing_values or next_values:
            merged_metadata[key] = sorted(
                {value for value in [*existing_values, *next_values] if value is not None}
            )
    return tuple(dict.fromkeys(merged_errors)), merged_metadata


def _knowledge_repair_root_cause_summary(
    *,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    cleaned_errors = [
        str(error).strip() for error in validation_errors if str(error).strip()
    ]
    if cleaned_errors:
        summary["validation_errors"] = cleaned_errors
    error_details = [
        {
            key: value
            for key, value in dict(detail).items()
            if key in {"code", "message", "path", "row_id", "block_index"}
            and value not in (None, "", [], {})
        }
        for detail in (validation_metadata.get("error_details") or [])
        if isinstance(detail, Mapping)
    ]
    error_details = [detail for detail in error_details if detail]
    if error_details:
        summary["error_details"] = error_details
    if error_details:
        first_detail = error_details[0]
        code = str(first_detail.get("code") or "").strip()
        message = str(first_detail.get("message") or "").strip()
        path = str(first_detail.get("path") or "").strip()
        summary["message"] = " | ".join(part for part in (code, message, path) if part)
    elif cleaned_errors:
        summary["message"] = ",".join(cleaned_errors)
    return summary


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
    return should_attempt_taskfile_fresh_worker_replacement(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        replacement_attempt_count=replacement_attempt_count,
        same_session_completed=bool(same_session_state_payload.get("completed")),
        retryable_exception_reason=(
            _knowledge_retryable_runner_exception_reason(exc)
            if exc is not None
            else None
        ),
        catastrophic_run_result_reason=(
            _knowledge_catastrophic_run_result_reason(run_result)
            if run_result is not None
            else None
        ),
    )


def _should_attempt_knowledge_fresh_session_retry(
    *,
    run_result: CodexExecRunResult,
    task_file_path: Path,
    original_task_file: Mapping[str, Any],
    same_session_state_payload: Mapping[str, Any],
) -> tuple[bool, str]:
    return should_attempt_taskfile_fresh_session_retry(
        stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
        retry_attempt_count=int(
            same_session_state_payload.get("fresh_session_retry_count") or 0
        ),
        same_session_completed=bool(same_session_state_payload.get("completed")),
        final_status=str(same_session_state_payload.get("final_status") or "").strip(),
        hard_boundary_failure=_knowledge_hard_boundary_failure(run_result),
        session_completed_successfully=run_result.completed_successfully(),
        useful_progress=_knowledge_task_file_useful_progress(
            task_file_path=task_file_path,
            original_task_file=original_task_file,
            same_session_state_payload=same_session_state_payload,
        ),
    )


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
        normalized_payload, normalization_metadata = sanitize_knowledge_worker_payload_for_shard(
            shard,
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
    task_status_tracker: _KnowledgeTaskStatusTracker | None,
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
    inline_repair_should_resume = _knowledge_inline_repair_should_resume(settings)
    classification_repair_followup_count = 0
    grouping_repair_followup_count = 0
    whole_shard_grouping_repair_followup_count = 0

    def _record_structured_attempt(
        *,
        run_result: CodexExecRunResult,
        shard_id: str,
        prompt_input_mode: str,
        semantic_step_key: str,
        owned_row_count: int,
        validation_count: int,
        is_repair_attempt: bool,
        events_path: Path,
        last_message_path: Path,
        usage_path: Path,
        workspace_manifest_path: Path,
    ) -> None:
        runner_payload = _build_knowledge_inline_attempt_runner_payload(
            pipeline_id=pipeline_id,
            worker_id=assignment.worker_id,
            shard_id=shard_id,
            run_result=run_result,
            model=model,
            reasoning_effort=reasoning_effort,
            prompt_input_mode=prompt_input_mode,
            events_path=events_path,
            last_message_path=last_message_path,
            usage_path=usage_path,
            workspace_manifest_path=workspace_manifest_path,
        )
        worker_runner_results.append(runner_payload)
        telemetry = runner_payload.get("telemetry")
        if not isinstance(telemetry, Mapping):
            return
        rows = telemetry.get("rows")
        if not isinstance(rows, list):
            return
        for row in rows:
            if isinstance(row, Mapping):
                row_payload = dict(row)
                row_payload["knowledge_semantic_step"] = semantic_step_key
                row_payload["is_repair_attempt"] = bool(is_repair_attempt)
                row_payload["owned_row_count"] = int(max(owned_row_count, 0))
                row_payload["classification_owned_row_count"] = (
                    int(max(owned_row_count, 0))
                    if semantic_step_key == KNOWLEDGE_CLASSIFY_STEP_KEY
                    else 0
                )
                row_payload["grouping_owned_row_count"] = (
                    int(max(owned_row_count, 0))
                    if semantic_step_key == KNOWLEDGE_GROUP_STEP_KEY
                    else 0
                )
                row_payload["classification_validation_count"] = (
                    int(max(validation_count, 0))
                    if semantic_step_key == KNOWLEDGE_CLASSIFY_STEP_KEY
                    else 0
                )
                row_payload["grouping_validation_count"] = (
                    int(max(validation_count, 0))
                    if semantic_step_key == KNOWLEDGE_GROUP_STEP_KEY
                    else 0
                )
                stage_rows.append(row_payload)

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
            if task_status_tracker is not None:
                task_status_tracker.mark_terminal(
                    task_id=shard.shard_id,
                    worker_id=assignment.worker_id,
                    terminal_state="preflight_rejected",
                    attempt_type="preflight",
                    proposal_status="preflight_rejected",
                    validation_errors=(reason_code,),
                    metadata={
                        "reason_detail": str(
                            preflight_failure.get("reason_detail") or ""
                        ).strip()
                        or None,
                    },
                    terminal_reason_code=reason_code,
                    terminal_reason_detail=str(
                        preflight_failure.get("reason_detail") or ""
                    ).strip()
                    or None,
                )
            continue

        session_root = shard_dir / shard.shard_id / "structured_session"
        session_root.mkdir(parents=True, exist_ok=True)
        if task_status_tracker is not None:
            task_status_tracker.start_attempt(
                task_id=shard.shard_id,
                worker_id=assignment.worker_id,
                attempt_type="main_worker",
                metadata={
                    "workspace_processing_contract": "knowledge_structured_session_v1",
                },
            )
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
            workspace_task_label="knowledge structured classification session",
            persist_session=inline_repair_should_resume,
        )
        terminal_run_result = initial_run_result
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
        _record_structured_attempt(
            run_result=initial_run_result,
            shard_id=shard.shard_id,
            prompt_input_mode="structured_session_classification_initial",
            semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
            owned_row_count=len(classification_task_file.get("units") or []),
            validation_count=1,
            is_repair_attempt=False,
            events_path=classification_events_path,
            last_message_path=classification_last_message_path,
            usage_path=classification_usage_path,
            workspace_manifest_path=classification_workspace_manifest_path,
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
            (
                classification_validation_errors,
                classification_validation_metadata,
            ) = _merge_knowledge_response_contract_diagnostics(
                validation_errors=classification_validation_errors,
                validation_metadata=classification_validation_metadata,
                parse_errors=parse_errors,
                parse_metadata=parse_metadata,
            )

        classification_repair_limit = structured_repair_followup_limit(
            stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
            semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
        )
        if _knowledge_validation_blocked(
            classification_validation_errors,
            classification_validation_metadata,
        ):
            for repair_attempt_index in range(
                1, classification_repair_limit + 1
            ):
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
                    repair_validation_errors=classification_validation_errors,
                    repair_validation_metadata=classification_validation_metadata,
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
                repair_packet_path = (
                    session_root / f"classification_repair_packet_{repair_attempt_index:02d}.json"
                )
                repair_prompt_path = (
                    session_root / f"classification_repair_prompt_{repair_attempt_index:02d}.txt"
                )
                repair_response_path = (
                    session_root / f"classification_repair_response_{repair_attempt_index:02d}.json"
                )
                repair_events_path = (
                    session_root / f"classification_repair_events_{repair_attempt_index:02d}.jsonl"
                )
                repair_last_message_path = (
                    session_root
                    / f"classification_repair_last_message_{repair_attempt_index:02d}.json"
                )
                repair_usage_path = (
                    session_root / f"classification_repair_usage_{repair_attempt_index:02d}.json"
                )
                repair_workspace_manifest_path = (
                    session_root
                    / f"classification_repair_workspace_manifest_{repair_attempt_index:02d}.json"
                )
                repair_packet_path.write_text(
                    json.dumps(repair_packet, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                repair_prompt_path.write_text(repair_prompt, encoding="utf-8")
                if inline_repair_should_resume:
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
                    resume_last=inline_repair_should_resume,
                    persist_session=inline_repair_should_resume,
                    prepared_execution_working_dir=execution_workspace,
                    workspace_task_label="knowledge structured classification repair session",
                )
                classification_repair_followup_count += 1
                terminal_run_result = repair_run_result
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
                    turn_kind=(
                        "classification_repair"
                        if repair_attempt_index == 1
                        else f"classification_repair_{repair_attempt_index}"
                    ),
                    packet_path=repair_packet_path,
                    prompt_path=repair_prompt_path,
                    response_path=repair_response_path,
                )
                _record_structured_attempt(
                    run_result=repair_run_result,
                    shard_id=shard.shard_id,
                    prompt_input_mode="structured_session_classification_repair",
                    semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
                    owned_row_count=len(repair_task_file.get("units") or []),
                    validation_count=0,
                    is_repair_attempt=True,
                    events_path=repair_events_path,
                    last_message_path=repair_last_message_path,
                    usage_path=repair_usage_path,
                    workspace_manifest_path=repair_workspace_manifest_path,
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
                    continue
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
                        classification_validation_metadata.get("validated_answers_by_unit_id")
                        or {}
                    ),
                )
                (
                    classification_validation_errors,
                    classification_validation_metadata,
                ) = _merge_knowledge_response_contract_diagnostics(
                    validation_errors=classification_validation_errors,
                    validation_metadata=classification_validation_metadata,
                    parse_errors=repair_parse_errors,
                    parse_metadata=repair_parse_metadata,
                )
                if not _knowledge_validation_blocked(
                    classification_validation_errors,
                    classification_validation_metadata,
                ):
                    break

        if _knowledge_validation_blocked(
            classification_validation_errors,
            classification_validation_metadata,
        ):
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
            (
                grouping_task_files,
                _grouping_unit_to_shard_id,
                _grouping_batches,
            ) = build_knowledge_grouping_task_files(
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
                grouping_run_result = runner.run_packet_worker(
                    prompt_text=grouping_prompt,
                    input_payload=grouping_packet,
                    working_dir=session_root,
                    env=env,
                    output_schema_path=None,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    prepared_execution_working_dir=execution_workspace,
                    workspace_task_label="knowledge structured grouping session",
                    persist_session=inline_repair_should_resume,
                )
                terminal_run_result = grouping_run_result
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
                _record_structured_attempt(
                    run_result=grouping_run_result,
                    shard_id=shard.shard_id,
                    prompt_input_mode="structured_session_grouping",
                    semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
                    owned_row_count=len(grouping_task_file.get("units") or []),
                    validation_count=1,
                    is_repair_attempt=False,
                    events_path=grouping_events_path,
                    last_message_path=grouping_last_message_path,
                    usage_path=grouping_usage_path,
                    workspace_manifest_path=grouping_workspace_manifest_path,
                )
                grouping_edited_task_file, grouping_parse_errors, grouping_parse_metadata = (
                    _build_knowledge_edited_task_file_from_grouping_response(
                        original_task_file=grouping_task_file,
                        response_text=grouping_run_result.response_text,
                    )
                )
                grouping_batch_answers_by_unit_id: dict[str, dict[str, Any]] = {}
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
                    grouping_batch_answers_by_unit_id = _knowledge_merge_answers(
                        dict(
                            grouping_validation_metadata.get("validated_answers_by_unit_id") or {}
                        ),
                        grouping_batch_answers_by_unit_id,
                    )
                    (
                        grouping_validation_errors,
                        grouping_validation_metadata,
                    ) = _merge_knowledge_response_contract_diagnostics(
                        validation_errors=grouping_validation_errors,
                        validation_metadata=grouping_validation_metadata,
                        parse_errors=grouping_parse_errors,
                        parse_metadata=grouping_parse_metadata,
                    )
                grouping_repair_limit = structured_repair_followup_limit(
                    stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                    semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
                )
                if _knowledge_validation_blocked(
                    grouping_validation_errors,
                    grouping_validation_metadata,
                ):
                    grouping_repair_root_cause_summary = _knowledge_repair_root_cause_summary(
                        validation_errors=grouping_validation_errors,
                        validation_metadata=grouping_validation_metadata,
                    )
                    for repair_attempt_index in range(
                        1, grouping_repair_limit + 1
                    ):
                        repair_grouping_task_file = build_repair_task_file(
                            original_task_file=grouping_task_file,
                            failed_unit_ids=_knowledge_failed_unit_ids(
                                task_file_payload=grouping_task_file,
                                validation_metadata=grouping_validation_metadata,
                            ),
                            previous_answers_by_unit_id=grouping_batch_answers_by_unit_id,
                            validation_feedback_by_unit_id=build_task_file_answer_feedback(
                                validation_errors=grouping_validation_errors,
                                validation_metadata=grouping_validation_metadata,
                            ),
                            repair_validation_errors=grouping_validation_errors,
                            repair_validation_metadata=grouping_validation_metadata,
                        )
                        repair_grouping_task_file["repair_root_cause_summary"] = dict(
                            grouping_repair_root_cause_summary
                        )
                        repair_grouping_packet = _knowledge_task_file_to_structured_packet(
                            task_file_payload=repair_grouping_task_file,
                            packet_kind=f"grouping_{batch_index}_repair",
                            validation_errors=grouping_validation_errors,
                        )
                        repair_grouping_prompt = _build_knowledge_structured_prompt(
                            task_file_payload=repair_grouping_task_file,
                            packet=repair_grouping_packet,
                        )
                        repair_grouping_packet_path = (
                            session_root
                            / f"grouping_repair_packet_{batch_index:02d}_{repair_attempt_index:02d}.json"
                        )
                        repair_grouping_prompt_path = (
                            session_root
                            / f"grouping_repair_prompt_{batch_index:02d}_{repair_attempt_index:02d}.txt"
                        )
                        repair_grouping_response_path = (
                            session_root
                            / f"grouping_repair_response_{batch_index:02d}_{repair_attempt_index:02d}.json"
                        )
                        repair_grouping_events_path = (
                            session_root
                            / f"grouping_repair_events_{batch_index:02d}_{repair_attempt_index:02d}.jsonl"
                        )
                        repair_grouping_last_message_path = (
                            session_root
                            / f"grouping_repair_last_message_{batch_index:02d}_{repair_attempt_index:02d}.json"
                        )
                        repair_grouping_usage_path = (
                            session_root
                            / f"grouping_repair_usage_{batch_index:02d}_{repair_attempt_index:02d}.json"
                        )
                        repair_grouping_workspace_manifest_path = (
                            session_root
                            / f"grouping_repair_workspace_manifest_{batch_index:02d}_{repair_attempt_index:02d}.json"
                        )
                        repair_grouping_packet_path.write_text(
                            json.dumps(repair_grouping_packet, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                        repair_grouping_prompt_path.write_text(
                            repair_grouping_prompt,
                            encoding="utf-8",
                        )
                        if inline_repair_should_resume:
                            assert_structured_session_can_resume(
                                worker_root=session_root,
                                execution_working_dir=execution_workspace,
                            )
                        repair_grouping_run_result = runner.run_packet_worker(
                            prompt_text=repair_grouping_prompt,
                            input_payload=repair_grouping_packet,
                            working_dir=session_root,
                            env=env,
                            output_schema_path=None,
                            model=model,
                            reasoning_effort=reasoning_effort,
                            resume_last=inline_repair_should_resume,
                            persist_session=inline_repair_should_resume,
                            prepared_execution_working_dir=execution_workspace,
                            workspace_task_label="knowledge structured grouping repair session",
                        )
                        grouping_repair_followup_count += 1
                        terminal_run_result = repair_grouping_run_result
                        repair_grouping_response_path.write_text(
                            str(repair_grouping_run_result.response_text or ""),
                            encoding="utf-8",
                        )
                        repair_grouping_events_path.write_text(
                            _render_events_jsonl(repair_grouping_run_result.events),
                            encoding="utf-8",
                        )
                        _write_json(
                            {"text": repair_grouping_run_result.response_text},
                            repair_grouping_last_message_path,
                        )
                        _write_json(
                            dict(repair_grouping_run_result.usage or {}),
                            repair_grouping_usage_path,
                        )
                        _write_json(
                            repair_grouping_run_result.workspace_manifest(),
                            repair_grouping_workspace_manifest_path,
                        )
                        record_structured_session_turn(
                            worker_root=session_root,
                            execution_working_dir=execution_workspace,
                            turn_kind=(
                                f"grouping_{batch_index}_repair"
                                if repair_attempt_index == 1
                                else f"grouping_{batch_index}_repair_{repair_attempt_index}"
                            ),
                            packet_path=repair_grouping_packet_path,
                            prompt_path=repair_grouping_prompt_path,
                            response_path=repair_grouping_response_path,
                        )
                        _record_structured_attempt(
                            run_result=repair_grouping_run_result,
                            shard_id=shard.shard_id,
                            prompt_input_mode="structured_session_grouping_repair",
                            semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
                            owned_row_count=len(repair_grouping_task_file.get("units") or []),
                            validation_count=0,
                            is_repair_attempt=True,
                            events_path=repair_grouping_events_path,
                            last_message_path=repair_grouping_last_message_path,
                            usage_path=repair_grouping_usage_path,
                            workspace_manifest_path=repair_grouping_workspace_manifest_path,
                        )
                        (
                            repair_grouping_edited_task_file,
                            repair_grouping_parse_errors,
                            repair_grouping_parse_metadata,
                        ) = _build_knowledge_edited_task_file_from_grouping_response(
                            original_task_file=repair_grouping_task_file,
                            response_text=repair_grouping_run_result.response_text,
                        )
                        if repair_grouping_edited_task_file is None:
                            grouping_validation_errors = tuple(repair_grouping_parse_errors)
                            grouping_validation_metadata = dict(repair_grouping_parse_metadata)
                            continue
                        (
                            repair_grouping_answers_by_unit_id,
                            _repair_grouping_errors,
                            repair_grouping_validation_metadata,
                        ) = validate_knowledge_grouping_task_file(
                            original_task_file=repair_grouping_task_file,
                            edited_task_file=repair_grouping_edited_task_file,
                        )
                        grouping_batch_answers_by_unit_id = _knowledge_merge_answers(
                            grouping_batch_answers_by_unit_id,
                            dict(
                                repair_grouping_validation_metadata.get(
                                    "validated_answers_by_unit_id"
                                )
                                or {}
                            ),
                        )
                        grouping_batch_answers_by_unit_id = _knowledge_merge_answers(
                            grouping_batch_answers_by_unit_id,
                            repair_grouping_answers_by_unit_id,
                        )
                        grouping_batch_answers_by_unit_id = (
                            canonicalize_knowledge_grouping_answer_ids(
                                original_task_file=grouping_task_file,
                                answers_by_unit_id=grouping_batch_answers_by_unit_id,
                            )
                        )
                        final_grouping_task_file = _apply_answers_to_task_file(
                            original_task_file=grouping_task_file,
                            answers_by_unit_id=grouping_batch_answers_by_unit_id,
                        )
                        (
                            _final_grouping_answers,
                            grouping_validation_errors,
                            grouping_validation_metadata,
                        ) = validate_knowledge_grouping_task_file(
                            original_task_file=grouping_task_file,
                            edited_task_file=final_grouping_task_file,
                        )
                        grouping_batch_answers_by_unit_id = _knowledge_merge_answers(
                            grouping_batch_answers_by_unit_id,
                            dict(
                                grouping_validation_metadata.get("validated_answers_by_unit_id")
                                or {}
                            ),
                        )
                        (
                            grouping_validation_errors,
                            grouping_validation_metadata,
                        ) = _merge_knowledge_response_contract_diagnostics(
                            validation_errors=grouping_validation_errors,
                            validation_metadata=grouping_validation_metadata,
                            parse_errors=repair_grouping_parse_errors,
                            parse_metadata=repair_grouping_parse_metadata,
                        )
                        if not _knowledge_validation_blocked(
                            grouping_validation_errors,
                            grouping_validation_metadata,
                        ):
                            break
                grouping_answers_by_unit_id = _knowledge_merge_answers(
                    grouping_answers_by_unit_id,
                    grouping_batch_answers_by_unit_id,
                )
                if _knowledge_validation_blocked(
                    grouping_validation_errors,
                    grouping_validation_metadata,
                ):
                    grouping_failed = True
                    proposal_payload = None
                    proposal_status = "invalid"
                    proposal_metadata = dict(grouping_validation_metadata)
                    proposal_errors = tuple(grouping_validation_errors)
                    break
            if not grouping_failed:

                def _assemble_and_validate_grouped_shard_proposal(
                    *,
                    current_grouping_answers_by_unit_id: Mapping[str, Mapping[str, Any]],
                ) -> tuple[dict[str, Any] | None, str, tuple[str, ...], dict[str, Any]]:
                    raw_proposal_payload = combine_knowledge_task_file_outputs(
                        classification_task_file=classification_task_file,
                        classification_answers_by_unit_id=classification_answers_by_unit_id,
                        grouping_answers_by_unit_id=current_grouping_answers_by_unit_id,
                        unit_to_shard_id=unit_to_shard_id,
                    ).get(shard.shard_id)
                    current_proposal_metadata = {
                        **dict(classification_validation_metadata),
                        **dict(
                            collect_knowledge_resolution_metadata_by_shard(
                                classification_task_file=classification_task_file,
                                classification_answers_by_unit_id=classification_answers_by_unit_id,
                                grouping_answers_by_unit_id=current_grouping_answers_by_unit_id,
                                unit_to_shard_id=unit_to_shard_id,
                            ).get(shard.shard_id)
                            or {}
                        ),
                    }
                    if raw_proposal_payload is None:
                        return None, "invalid", ("missing_output_file",), current_proposal_metadata
                    try:
                        sanitized_proposal_payload, normalization_metadata = (
                            sanitize_knowledge_worker_payload_for_shard(
                                shard,
                                raw_proposal_payload,
                            )
                        )
                    except Exception as exc:  # noqa: BLE001
                        return (
                            None,
                            "invalid",
                            ("schema_invalid",),
                            {
                                **current_proposal_metadata,
                                "parse_error": str(exc),
                            },
                        )
                    valid, validation_errors, validation_metadata = (
                        validate_knowledge_shard_output(
                            shard,
                            sanitized_proposal_payload,
                        )
                    )
                    current_proposal_metadata = {
                        **current_proposal_metadata,
                        **dict(validation_metadata or {}),
                        **dict(normalization_metadata or {}),
                    }
                    if valid:
                        return (
                            sanitized_proposal_payload,
                            "validated",
                            (),
                            current_proposal_metadata,
                        )
                    current_proposal_metadata["failure_classification"] = (
                        classify_knowledge_validation_failure(
                            validation_errors=validation_errors,
                            validation_metadata=current_proposal_metadata,
                        )
                    )
                    return (
                        None,
                        "invalid",
                        tuple(validation_errors),
                        current_proposal_metadata,
                    )

                (
                    proposal_payload,
                    proposal_status,
                    proposal_errors,
                    proposal_metadata,
                ) = _assemble_and_validate_grouped_shard_proposal(
                    current_grouping_answers_by_unit_id=grouping_answers_by_unit_id,
                )

                if proposal_status == "invalid":
                    (
                        whole_shard_grouping_repair_task_file,
                        whole_shard_grouping_task_file,
                    ) = _build_knowledge_whole_shard_grouping_repair_task_file(
                        assignment_id=str(classification_task_file.get("assignment_id") or ""),
                        worker_id=str(classification_task_file.get("worker_id") or ""),
                        shard_id=shard.shard_id,
                        classification_task_file=classification_task_file,
                        classification_answers_by_unit_id=classification_answers_by_unit_id,
                        grouping_answers_by_unit_id=grouping_answers_by_unit_id,
                        unit_to_shard_id=unit_to_shard_id,
                        validation_errors=proposal_errors,
                        validation_metadata=proposal_metadata,
                    )
                    if (
                        whole_shard_grouping_repair_task_file is not None
                        and whole_shard_grouping_task_file is not None
                    ):
                        whole_shard_grouping_repair_task_file[
                            "repair_root_cause_summary"
                        ] = _knowledge_repair_root_cause_summary(
                            validation_errors=proposal_errors,
                            validation_metadata=proposal_metadata,
                        )
                        repair_packet = _knowledge_task_file_to_structured_packet(
                            task_file_payload=whole_shard_grouping_repair_task_file,
                            packet_kind="grouping_final_repair",
                            validation_errors=proposal_errors,
                        )
                        repair_prompt = _build_knowledge_structured_prompt(
                            task_file_payload=whole_shard_grouping_repair_task_file,
                            packet=repair_packet,
                        )
                        repair_packet_path = session_root / "grouping_final_repair_packet.json"
                        repair_prompt_path = session_root / "grouping_final_repair_prompt.txt"
                        repair_response_path = session_root / "grouping_final_repair_response.json"
                        repair_events_path = session_root / "grouping_final_repair_events.jsonl"
                        repair_last_message_path = (
                            session_root / "grouping_final_repair_last_message.json"
                        )
                        repair_usage_path = session_root / "grouping_final_repair_usage.json"
                        repair_workspace_manifest_path = (
                            session_root / "grouping_final_repair_workspace_manifest.json"
                        )
                        repair_packet_path.write_text(
                            json.dumps(repair_packet, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                        repair_prompt_path.write_text(repair_prompt, encoding="utf-8")
                        if inline_repair_should_resume:
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
                            resume_last=inline_repair_should_resume,
                            persist_session=inline_repair_should_resume,
                            prepared_execution_working_dir=execution_workspace,
                            workspace_task_label=(
                                "knowledge structured whole-shard grouping repair session"
                            ),
                        )
                        whole_shard_grouping_repair_followup_count += 1
                        terminal_run_result = repair_run_result
                        repair_response_path.write_text(
                            str(repair_run_result.response_text or ""),
                            encoding="utf-8",
                        )
                        repair_events_path.write_text(
                            _render_events_jsonl(repair_run_result.events),
                            encoding="utf-8",
                        )
                        _write_json(
                            {"text": repair_run_result.response_text},
                            repair_last_message_path,
                        )
                        _write_json(dict(repair_run_result.usage or {}), repair_usage_path)
                        _write_json(
                            repair_run_result.workspace_manifest(),
                            repair_workspace_manifest_path,
                        )
                        record_structured_session_turn(
                            worker_root=session_root,
                            execution_working_dir=execution_workspace,
                            turn_kind="grouping_final_repair",
                            packet_path=repair_packet_path,
                            prompt_path=repair_prompt_path,
                            response_path=repair_response_path,
                        )
                        _record_structured_attempt(
                            run_result=repair_run_result,
                            shard_id=shard.shard_id,
                            prompt_input_mode="structured_session_grouping_final_repair",
                            semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
                            owned_row_count=len(
                                whole_shard_grouping_repair_task_file.get("units") or []
                            ),
                            validation_count=0,
                            is_repair_attempt=True,
                            events_path=repair_events_path,
                            last_message_path=repair_last_message_path,
                            usage_path=repair_usage_path,
                            workspace_manifest_path=repair_workspace_manifest_path,
                        )
                        (
                            repair_edited_task_file,
                            repair_parse_errors,
                            repair_parse_metadata,
                        ) = _build_knowledge_edited_task_file_from_grouping_response(
                            original_task_file=whole_shard_grouping_repair_task_file,
                            response_text=repair_run_result.response_text,
                        )
                        proposal_metadata = {
                            **dict(proposal_metadata or {}),
                            "whole_shard_grouping_repair_attempted": True,
                        }
                        if repair_edited_task_file is None:
                            proposal_payload = None
                            proposal_status = "invalid"
                            proposal_errors = tuple(repair_parse_errors)
                            proposal_metadata = {
                                **proposal_metadata,
                                **dict(repair_parse_metadata or {}),
                                "whole_shard_grouping_repair_recovered": False,
                            }
                        else:
                            (
                                repair_grouping_answers_by_unit_id,
                                _repair_grouping_errors,
                                repair_grouping_validation_metadata,
                            ) = validate_knowledge_grouping_task_file(
                                original_task_file=whole_shard_grouping_repair_task_file,
                                edited_task_file=repair_edited_task_file,
                            )
                            final_grouping_answers_by_unit_id = _knowledge_merge_answers(
                                grouping_answers_by_unit_id,
                                dict(
                                    repair_grouping_validation_metadata.get(
                                        "validated_answers_by_unit_id"
                                    )
                                    or {}
                                ),
                            )
                            final_grouping_answers_by_unit_id = _knowledge_merge_answers(
                                final_grouping_answers_by_unit_id,
                                repair_grouping_answers_by_unit_id,
                            )
                            final_grouping_answers_by_unit_id = (
                                canonicalize_knowledge_grouping_answer_ids(
                                    original_task_file=whole_shard_grouping_task_file,
                                    answers_by_unit_id=final_grouping_answers_by_unit_id,
                                )
                            )
                            final_grouping_task_file = _apply_answers_to_task_file(
                                original_task_file=whole_shard_grouping_task_file,
                                answers_by_unit_id=final_grouping_answers_by_unit_id,
                            )
                            (
                                _validated_final_grouping_answers,
                                final_grouping_validation_errors,
                                final_grouping_validation_metadata,
                            ) = validate_knowledge_grouping_task_file(
                                original_task_file=whole_shard_grouping_task_file,
                                edited_task_file=final_grouping_task_file,
                            )
                            (
                                final_grouping_validation_errors,
                                final_grouping_validation_metadata,
                            ) = _merge_knowledge_response_contract_diagnostics(
                                validation_errors=final_grouping_validation_errors,
                                validation_metadata=final_grouping_validation_metadata,
                                parse_errors=repair_parse_errors,
                                parse_metadata=repair_parse_metadata,
                            )
                            if _knowledge_validation_blocked(
                                final_grouping_validation_errors,
                                final_grouping_validation_metadata,
                            ):
                                proposal_payload = None
                                proposal_status = "invalid"
                                proposal_errors = tuple(final_grouping_validation_errors)
                                proposal_metadata = {
                                    **proposal_metadata,
                                    **dict(final_grouping_validation_metadata or {}),
                                    "whole_shard_grouping_repair_recovered": False,
                                }
                            else:
                                grouping_answers_by_unit_id = _knowledge_merge_answers(
                                    grouping_answers_by_unit_id,
                                    final_grouping_answers_by_unit_id,
                                )
                                (
                                    proposal_payload,
                                    proposal_status,
                                    proposal_errors,
                                    proposal_metadata_after_repair,
                                ) = _assemble_and_validate_grouped_shard_proposal(
                                    current_grouping_answers_by_unit_id=grouping_answers_by_unit_id,
                                )
                                proposal_metadata = {
                                    **dict(proposal_metadata_after_repair or {}),
                                    "whole_shard_grouping_repair_attempted": True,
                                    "whole_shard_grouping_repair_recovered": (
                                        proposal_status == "validated"
                                    ),
                                }

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
        if task_status_tracker is not None:
            terminal_reason_code, terminal_reason_detail = _terminal_reason_for_knowledge_task(
                proposal_status=proposal_status,
                validation_errors=proposal_errors,
                validation_metadata=proposal_metadata,
                run_result=terminal_run_result,
            )
            task_status_tracker.mark_terminal(
                task_id=shard.shard_id,
                worker_id=assignment.worker_id,
                terminal_state=_terminal_knowledge_task_state(
                    proposal_status=proposal_status,
                    supervision_state=terminal_run_result.supervision_state,
                    terminal_reason_code=terminal_reason_code,
                ),
                attempt_type="main_worker",
                proposal_status=proposal_status,
                validation_errors=proposal_errors,
                metadata=dict(proposal_metadata or {}),
                terminal_reason_code=terminal_reason_code,
                terminal_reason_detail=terminal_reason_detail,
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
    worker_runner_payload["recovery_policy"] = {
        "classification": inline_repair_policy_summary(
            stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
            semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
        ),
        "grouping": inline_repair_policy_summary(
            stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
            semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
        ),
    }
    worker_runner_payload["repair_recovery_policy"] = {
        "active_transport": INLINE_JSON_TRANSPORT,
        "worker_assignment": build_followup_budget_summary(
            stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
            transport=INLINE_JSON_TRANSPORT,
            allowed_attempts_multiplier_by_kind={
                FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: len(requested_shards),
            },
            spent_attempts_by_kind={
                FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: (
                    whole_shard_grouping_repair_followup_count
                ),
            },
        ),
        "semantic_steps": {
            KNOWLEDGE_CLASSIFY_STEP_KEY: build_followup_budget_summary(
                stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                transport=INLINE_JSON_TRANSPORT,
                semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
                allowed_attempts_multiplier_by_kind={
                    FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: len(requested_shards),
                },
                spent_attempts_by_kind={
                    FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: (
                        classification_repair_followup_count
                    ),
                },
            ),
            KNOWLEDGE_GROUP_STEP_KEY: build_followup_budget_summary(
                stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                transport=INLINE_JSON_TRANSPORT,
                semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
                allowed_attempts_multiplier_by_kind={
                    FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: len(requested_shards),
                },
                spent_attempts_by_kind={
                    FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: (
                        grouping_repair_followup_count
                    ),
                },
            ),
        },
    }
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
            task_status_tracker=task_status_tracker,
        )

    worker_failure_count = 0
    worker_proposal_count = 0
    post_taskfile_repair_followup_count = 0
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
        worker_runner_payload["recovery_policy"] = {
            **taskfile_recovery_policy_summary(stage_key=KNOWLEDGE_POLICY_STAGE_KEY),
            **taskfile_structured_repair_policy_summary(
                stage_key=KNOWLEDGE_POLICY_STAGE_KEY
            ),
            "same_session_repair_rewrite_limits": {
                KNOWLEDGE_CLASSIFY_STEP_KEY: taskfile_same_session_repair_rewrite_limit(
                    stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                    semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
                ),
                KNOWLEDGE_GROUP_STEP_KEY: taskfile_same_session_repair_rewrite_limit(
                    stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                    semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
                ),
            },
        }
        worker_runner_payload["repair_recovery_policy"] = {
            "active_transport": TASKFILE_TRANSPORT,
            "worker_assignment": build_followup_budget_summary(
                stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                transport=TASKFILE_TRANSPORT,
                allowed_attempts_multiplier_by_kind={
                    FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: len(assigned_shards),
                },
            ),
            "semantic_steps": {
                KNOWLEDGE_CLASSIFY_STEP_KEY: build_followup_budget_summary(
                    stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                    transport=TASKFILE_TRANSPORT,
                    semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
                ),
                KNOWLEDGE_GROUP_STEP_KEY: build_followup_budget_summary(
                    stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                    transport=TASKFILE_TRANSPORT,
                    semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
                ),
            },
        }
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
    same_session_resolution_metadata_by_shard: dict[str, dict[str, Any]] = {}
    if task_file_payload is not None:
        same_session_resolution_metadata_by_shard = (
            _knowledge_same_session_resolution_metadata_by_shard(
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
            post_taskfile_repair_followup_count += 1
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
        if shard.shard_id in same_session_resolution_metadata_by_shard:
            validation_metadata.update(
                dict(same_session_resolution_metadata_by_shard[shard.shard_id])
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
    same_session_repair_rewrite_count = int(
        same_session_state_payload.get("same_session_repair_rewrite_count") or 0
    )
    same_session_repair_counts_by_step = _knowledge_same_session_repair_counts_by_step(
        same_session_state_payload
    )
    worker_runner_payload["same_session_repair_rewrite_count"] = (
        same_session_repair_rewrite_count
    )
    worker_runner_payload["same_session_repair_rewrite_counts_by_step"] = dict(
        same_session_repair_counts_by_step
    )
    worker_runner_payload["recovery_policy"] = {
        **taskfile_recovery_policy_summary(stage_key=KNOWLEDGE_POLICY_STAGE_KEY),
        **taskfile_structured_repair_policy_summary(
            stage_key=KNOWLEDGE_POLICY_STAGE_KEY
        ),
        "same_session_repair_rewrite_limits": {
            KNOWLEDGE_CLASSIFY_STEP_KEY: taskfile_same_session_repair_rewrite_limit(
                stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
            ),
            KNOWLEDGE_GROUP_STEP_KEY: taskfile_same_session_repair_rewrite_limit(
                stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
            ),
        },
    }
    worker_runner_payload["repair_recovery_policy"] = {
        "active_transport": TASKFILE_TRANSPORT,
        "worker_assignment": build_followup_budget_summary(
            stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
            transport=TASKFILE_TRANSPORT,
            spent_attempts_by_kind={
                FOLLOWUP_KIND_FRESH_SESSION_RETRY: fresh_session_retry_count,
                FOLLOWUP_KIND_FRESH_WORKER_REPLACEMENT: fresh_worker_replacement_count,
                FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: (
                    post_taskfile_repair_followup_count
                ),
            },
            allowed_attempts_multiplier_by_kind={
                FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: len(assigned_shards),
            },
        ),
        "semantic_steps": {
            KNOWLEDGE_CLASSIFY_STEP_KEY: build_followup_budget_summary(
                stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                transport=TASKFILE_TRANSPORT,
                semantic_step_key=KNOWLEDGE_CLASSIFY_STEP_KEY,
                spent_attempts_by_kind={
                    FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE: same_session_repair_counts_by_step.get(
                        KNOWLEDGE_CLASSIFY_STEP_KEY,
                        0,
                    ),
                },
            ),
            KNOWLEDGE_GROUP_STEP_KEY: build_followup_budget_summary(
                stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
                transport=TASKFILE_TRANSPORT,
                semantic_step_key=KNOWLEDGE_GROUP_STEP_KEY,
                spent_attempts_by_kind={
                    FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE: same_session_repair_counts_by_step.get(
                        KNOWLEDGE_GROUP_STEP_KEY,
                        0,
                    ),
                },
            ),
        },
    }
    if fresh_worker_replacement_metadata:
        worker_runner_payload.update(dict(fresh_worker_replacement_metadata))
    _attach_worker_guardrail_summary(
        worker_runner_payload=worker_runner_payload,
        task_file_guardrail=task_file_guardrail,
        planned_happy_path_worker_cap=2,
        repair_followup_call_count=post_taskfile_repair_followup_count,
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
                "same_session_repair_rewrite_count": same_session_repair_rewrite_count,
                "same_session_repair_rewrite_counts_by_step": dict(
                    same_session_repair_counts_by_step
                ),
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
