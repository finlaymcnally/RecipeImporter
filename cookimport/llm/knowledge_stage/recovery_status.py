from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..codex_exec_runner import CodexExecRunResult
from ..knowledge_runtime_state import knowledge_reason_is_explicit_no_final_output
from ..phase_worker_runtime import TaskManifestEntryV1
from ._shared import (
    _KNOWLEDGE_FOLLOWUP_CIRCUIT_BREAKER_MIN_ATTEMPTS,
    _KNOWLEDGE_FOLLOWUP_CIRCUIT_BREAKER_MIN_SUCCESS_RATE,
    _KNOWLEDGE_POISONED_WORKER_MIN_FAILURES,
    _KNOWLEDGE_STAGE_STATUS_FILE_NAME,
    _KNOWLEDGE_STAGE_STATUS_SCHEMA_VERSION,
    _KNOWLEDGE_TASK_STATUS_FILE_NAME,
    _KNOWLEDGE_TASK_STATUS_SCHEMA_VERSION,
)
from .planning import _KnowledgeFollowupDecision
from .reporting import _load_json_dict, _write_json


def _format_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _poison_reason_for_failure_signature(
    failure_signature: str,
) -> tuple[str, str] | None:
    normalized = str(failure_signature or "").strip()
    if normalized in {"invalid_json", "schema_invalid"}:
        return (
            "poisoned_worker_uniform_malformed_outputs",
            "worker repeatedly produced malformed or schema-invalid packet outputs",
        )
    if normalized in {"watchdog_boundary", "watchdog_command_loop"}:
        return (
            "poisoned_worker_repeated_boundary_failures",
            "worker repeatedly died on the same watchdog boundary failure before producing usable packets",
        )
    if normalized == "no_final_output":
        return (
            "poisoned_worker_zero_output",
            "worker repeatedly produced no usable packet output",
        )
    return None


@dataclass(slots=True)
class _KnowledgeRecoveryGovernor:
    lock: threading.Lock = field(default_factory=threading.Lock)
    worker_failure_signatures_by_id: dict[str, list[str]] = field(default_factory=dict)
    poisoned_workers: dict[str, dict[str, str]] = field(default_factory=dict)
    followup_attempts_by_kind: dict[str, int] = field(default_factory=dict)
    followup_successes_by_kind: dict[str, int] = field(default_factory=dict)
    repeated_failure_attempts_by_kind: dict[str, dict[str, int]] = field(
        default_factory=dict
    )

    def observe_main_failure(
        self,
        *,
        worker_id: str,
        failure_signature: str,
    ) -> dict[str, str] | None:
        cleaned_worker_id = str(worker_id).strip()
        cleaned_signature = str(failure_signature).strip()
        if not cleaned_worker_id or not cleaned_signature:
            return None
        with self.lock:
            poisoned = self.poisoned_workers.get(cleaned_worker_id)
            if poisoned is not None:
                return dict(poisoned)
            signatures = self.worker_failure_signatures_by_id.setdefault(
                cleaned_worker_id, []
            )
            signatures.append(cleaned_signature)
            recent_signatures = signatures[-_KNOWLEDGE_POISONED_WORKER_MIN_FAILURES:]
            if len(recent_signatures) < _KNOWLEDGE_POISONED_WORKER_MIN_FAILURES:
                return None
            if len(set(recent_signatures)) != 1:
                return None
            signature = recent_signatures[-1]
            poison_reason = _poison_reason_for_failure_signature(signature)
            if poison_reason is None:
                return None
            reason_code, reason_detail = poison_reason
            payload = {
                "reason_code": reason_code,
                "reason_detail": reason_detail,
            }
            self.poisoned_workers[cleaned_worker_id] = payload
            return dict(payload)

    def allow_followup(
        self,
        *,
        kind: str,
        worker_id: str,
        failure_signature: str,
        near_miss: bool = True,
    ) -> _KnowledgeFollowupDecision:
        cleaned_kind = str(kind).strip().lower()
        cleaned_worker_id = str(worker_id).strip()
        cleaned_signature = str(failure_signature).strip() or "unknown_failure"
        with self.lock:
            poisoned = self.poisoned_workers.get(cleaned_worker_id)
            if poisoned is not None:
                return _KnowledgeFollowupDecision(
                    allowed=False,
                    reason_code=f"{cleaned_kind}_skipped_poisoned_worker",
                    reason_detail=str(poisoned.get("reason_detail") or "").strip()
                    or "worker already classified as poisoned",
                )
            if cleaned_kind == "repair" and not near_miss:
                return _KnowledgeFollowupDecision(
                    allowed=False,
                    reason_code="repair_skipped_not_near_miss",
                    reason_detail=(
                        "packet failed closed because the validator errors were not a "
                        "small repairable near miss"
                    ),
                )
            attempts = int(self.followup_attempts_by_kind.get(cleaned_kind) or 0)
            successes = int(self.followup_successes_by_kind.get(cleaned_kind) or 0)
            success_rate = (successes / attempts) if attempts > 0 else 1.0
            repeated_failures = int(
                (
                    self.repeated_failure_attempts_by_kind.get(cleaned_kind, {}).get(
                        cleaned_signature
                    )
                )
                or 0
            )
            if (
                attempts >= _KNOWLEDGE_FOLLOWUP_CIRCUIT_BREAKER_MIN_ATTEMPTS
                and success_rate < _KNOWLEDGE_FOLLOWUP_CIRCUIT_BREAKER_MIN_SUCCESS_RATE
            ) or repeated_failures >= _KNOWLEDGE_FOLLOWUP_CIRCUIT_BREAKER_MIN_ATTEMPTS:
                return _KnowledgeFollowupDecision(
                    allowed=False,
                    reason_code=f"{cleaned_kind}_skipped_circuit_breaker",
                    reason_detail=(
                        "bounded recovery circuit breaker opened after repeated low-yield "
                        f"{cleaned_kind} attempts for failure class {cleaned_signature}"
                    ),
                )
        return _KnowledgeFollowupDecision(allowed=True)

    def record_followup_outcome(
        self,
        *,
        kind: str,
        failure_signature: str,
        recovered: bool,
    ) -> None:
        cleaned_kind = str(kind).strip().lower()
        cleaned_signature = str(failure_signature).strip() or "unknown_failure"
        if not cleaned_kind:
            return
        with self.lock:
            self.followup_attempts_by_kind[cleaned_kind] = (
                int(self.followup_attempts_by_kind.get(cleaned_kind) or 0) + 1
            )
            if recovered:
                self.followup_successes_by_kind[cleaned_kind] = (
                    int(self.followup_successes_by_kind.get(cleaned_kind) or 0) + 1
                )
            else:
                repeated = dict(
                    self.repeated_failure_attempts_by_kind.get(cleaned_kind) or {}
                )
                repeated[cleaned_signature] = int(repeated.get(cleaned_signature) or 0) + 1
                self.repeated_failure_attempts_by_kind[cleaned_kind] = repeated


@dataclass(slots=True)
class _KnowledgeTaskStatusTracker:
    path: Path
    rows_by_task_id: dict[str, dict[str, Any]]
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self._write_locked()

    def start_attempt(
        self,
        *,
        task_id: str,
        worker_id: str,
        attempt_type: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        cleaned_task_id = str(task_id).strip()
        if not cleaned_task_id:
            return
        with self.lock:
            row = self.rows_by_task_id.get(cleaned_task_id)
            if row is None or bool(row.get("terminal")):
                return
            cleaned_attempt_type = str(attempt_type).strip() or None
            row["worker_id"] = str(worker_id).strip() or None
            row["active_attempt_type"] = cleaned_attempt_type
            row["last_attempt_type"] = cleaned_attempt_type
            row["attempt_state"] = "running"
            if cleaned_attempt_type == "main_worker":
                row["state"] = "leased"
            merged_metadata = dict(row.get("metadata") or {})
            merged_metadata.update(dict(metadata or {}))
            row["metadata"] = merged_metadata
            row["updated_at_utc"] = _format_utc_now()
            self._write_locked()

    def mark_main_output_written(
        self,
        *,
        task_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        cleaned_task_id = str(task_id).strip()
        if not cleaned_task_id:
            return
        with self.lock:
            row = self.rows_by_task_id.get(cleaned_task_id)
            if row is None or bool(row.get("terminal")):
                return
            row["state"] = "main_output_written"
            merged_metadata = dict(row.get("metadata") or {})
            merged_metadata.update(dict(metadata or {}))
            row["metadata"] = merged_metadata
            row["updated_at_utc"] = _format_utc_now()
            self._write_locked()

    def mark_terminal(
        self,
        *,
        task_id: str,
        worker_id: str,
        terminal_state: str,
        attempt_type: str,
        proposal_status: str | None,
        validation_errors: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        terminal_reason_code: str | None = None,
        terminal_reason_detail: str | None = None,
    ) -> None:
        cleaned_task_id = str(task_id).strip()
        if not cleaned_task_id:
            return
        with self.lock:
            row = self.rows_by_task_id.get(cleaned_task_id)
            if row is None:
                return
            row["worker_id"] = str(worker_id).strip() or None
            row["state"] = str(terminal_state).strip() or "unknown"
            row["terminal"] = True
            row["active_attempt_type"] = None
            row["last_attempt_type"] = str(attempt_type).strip() or None
            row["attempt_state"] = "completed"
            row["proposal_status"] = (
                str(proposal_status).strip() if proposal_status is not None else None
            )
            row["validation_errors"] = [
                str(error).strip() for error in validation_errors if str(error).strip()
            ]
            row["metadata"] = dict(metadata or {})
            row["terminal_reason_code"] = str(terminal_reason_code).strip() or None
            row["terminal_reason_detail"] = str(terminal_reason_detail).strip() or None
            row["updated_at_utc"] = _format_utc_now()
            self._write_locked()

    def mark_interrupted(self) -> None:
        with self.lock:
            changed = False
            interrupted_at = _format_utc_now()
            for row in self.rows_by_task_id.values():
                if bool(row.get("terminal")):
                    continue
                row["state"] = "cancelled_due_to_interrupt"
                row["terminal"] = True
                row["attempt_state"] = "cancelled"
                row["last_attempt_type"] = row.get("active_attempt_type") or row.get(
                    "last_attempt_type"
                )
                row["active_attempt_type"] = None
                metadata = dict(row.get("metadata") or {})
                metadata["interruption_cause"] = "operator_interrupt"
                row["metadata"] = metadata
                row["terminal_reason_code"] = "cancelled_stage_interrupt"
                row["terminal_reason_detail"] = (
                    "stage interrupted before this packet reached a terminal outcome"
                )
                row["updated_at_utc"] = interrupted_at
                changed = True
            if changed:
                self._write_locked()

    def state_counts(self) -> dict[str, int]:
        with self.lock:
            counts: dict[str, int] = {}
            for row in self.rows_by_task_id.values():
                state = str(row.get("state") or "").strip()
                if not state:
                    continue
                counts[state] = counts.get(state, 0) + 1
            return counts

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            for task_id in sorted(self.rows_by_task_id):
                handle.write(json.dumps(self.rows_by_task_id[task_id], sort_keys=True))
                handle.write("\n")
        tmp_path.replace(self.path)


def _build_knowledge_task_status_tracker(
    *,
    path: Path,
    task_entries: Sequence[TaskManifestEntryV1],
) -> _KnowledgeTaskStatusTracker:
    created_at = _format_utc_now()
    rows_by_task_id: dict[str, dict[str, Any]] = {}
    for task_entry in task_entries:
        task_id = str(task_entry.task_id).strip()
        if not task_id:
            continue
        rows_by_task_id[task_id] = {
            "schema_version": _KNOWLEDGE_TASK_STATUS_SCHEMA_VERSION,
            "task_id": task_id,
            "task_kind": str(task_entry.task_kind).strip() or None,
            "parent_shard_id": str(task_entry.parent_shard_id).strip() or None,
            "owned_ids": [str(value) for value in task_entry.owned_ids],
            "worker_id": None,
            "state": "pending",
            "terminal": False,
            "active_attempt_type": None,
            "last_attempt_type": None,
            "attempt_state": "pending",
            "proposal_status": None,
            "validation_errors": [],
            "metadata": dict(task_entry.metadata or {}),
            "terminal_reason_code": None,
            "terminal_reason_detail": None,
            "updated_at_utc": created_at,
        }
    return _KnowledgeTaskStatusTracker(path=path, rows_by_task_id=rows_by_task_id)


def _load_live_status(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _write_live_status(path: Path, payload: Mapping[str, Any]) -> None:
    _write_json(dict(payload), path)


def _merge_live_status_metadata(path: Path, *, payload: Mapping[str, Any]) -> None:
    if not path.exists():
        return
    current_payload = _load_json_dict(path)
    if not current_payload:
        return
    merged = {
        **dict(current_payload),
        **dict(payload),
    }
    _write_live_status(path, merged)


def _combine_taskfile_worker_run_results(
    run_results: Sequence[CodexExecRunResult],
) -> CodexExecRunResult:
    if len(run_results) == 1:
        return run_results[0]
    first = run_results[0]
    last = run_results[-1]
    usage = {
        "input_tokens": sum(
            int((result.usage or {}).get("input_tokens") or 0) for result in run_results
        ),
        "cached_input_tokens": sum(
            int((result.usage or {}).get("cached_input_tokens") or 0)
            for result in run_results
        ),
        "output_tokens": sum(
            int((result.usage or {}).get("output_tokens") or 0) for result in run_results
        ),
        "reasoning_tokens": sum(
            int((result.usage or {}).get("reasoning_tokens") or 0)
            for result in run_results
        ),
    }
    stdout_parts = [
        str(result.stdout_text or "").strip()
        for result in run_results
        if str(result.stdout_text or "").strip()
    ]
    stderr_parts = [
        str(result.stderr_text or "").strip()
        for result in run_results
        if str(result.stderr_text or "").strip()
    ]
    return CodexExecRunResult(
        command=list(last.command or first.command),
        subprocess_exit_code=last.subprocess_exit_code,
        output_schema_path=last.output_schema_path or first.output_schema_path,
        prompt_text=last.prompt_text or first.prompt_text,
        response_text=last.response_text,
        turn_failed_message=last.turn_failed_message,
        events=tuple(event for result in run_results for event in result.events),
        usage=usage,
        stderr_text="\n".join(stderr_parts) if stderr_parts else None,
        stdout_text="\n".join(stdout_parts) if stdout_parts else None,
        source_working_dir=last.source_working_dir or first.source_working_dir,
        execution_working_dir=last.execution_working_dir or first.execution_working_dir,
        execution_agents_path=last.execution_agents_path or first.execution_agents_path,
        duration_ms=sum(int(result.duration_ms or 0) for result in run_results),
        started_at_utc=first.started_at_utc,
        finished_at_utc=last.finished_at_utc,
        workspace_mode=last.workspace_mode,
        supervision_state=last.supervision_state,
        supervision_reason_code=last.supervision_reason_code,
        supervision_reason_detail=last.supervision_reason_detail,
        supervision_retryable=last.supervision_retryable,
    )


def _load_task_status_state_counts(path: Path) -> dict[str, int]:
    if not path.exists() or not path.is_file():
        return {}
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, Mapping):
            continue
        state = str(payload.get("state") or "").strip()
        if not state:
            continue
        counts[state] = counts.get(state, 0) + 1
    return counts


def _knowledge_artifact_dir_has_files(path: Path) -> bool:
    return path.exists() and path.is_dir() and any(child.is_file() for child in path.iterdir())


def _collect_knowledge_pre_kill_failure_counts(stage_root: Path) -> dict[str, Any]:
    worker_terminal_states: dict[str, int] = {}
    worker_reason_codes: dict[str, int] = {}
    worker_relaunch_reason_codes: dict[str, int] = {}
    for live_status_path in stage_root.rglob("*live_status.json"):
        payload = _load_json_dict(live_status_path)
        if not payload:
            continue
        state = str(payload.get("state") or "").strip()
        reason_code = str(payload.get("reason_code") or "").strip()
        if state:
            worker_terminal_states[state] = worker_terminal_states.get(state, 0) + 1
        if reason_code:
            worker_reason_codes[reason_code] = worker_reason_codes.get(reason_code, 0) + 1
        for code in payload.get("workspace_relaunch_reason_codes") or []:
            cleaned = str(code or "").strip()
            if not cleaned:
                continue
            worker_relaunch_reason_codes[cleaned] = (
                worker_relaunch_reason_codes.get(cleaned, 0) + 1
            )
    task_state_counts = _load_task_status_state_counts(
        stage_root / _KNOWLEDGE_TASK_STATUS_FILE_NAME
    )
    return {
        "worker_terminal_states": worker_terminal_states,
        "worker_reason_codes": worker_reason_codes,
        "worker_relaunch_reason_codes": worker_relaunch_reason_codes,
        "task_terminal_states": task_state_counts,
    }


def _finalize_stale_followup_attempt(
    *,
    followup_kind: str,
    live_status_path: Path,
    status_path: Path,
    terminal_reason_code: str,
    terminal_reason_detail: str,
) -> bool:
    payload = _load_json_dict(live_status_path)
    if not payload or str(payload.get("state") or "").strip() not in {"running", "pending"}:
        return False
    finished_at = _format_utc_now()
    payload["state"] = str(terminal_reason_code).strip() or "superseded_by_terminal_packet"
    payload["reason_code"] = str(terminal_reason_code).strip() or None
    payload["reason_detail"] = str(terminal_reason_detail).strip() or None
    payload["retryable"] = False
    payload["finished_at_utc"] = finished_at
    _write_json(dict(payload), live_status_path)
    status_payload: dict[str, Any] = {
        "status": str(terminal_reason_code).strip() or "superseded_by_terminal_packet",
        "state": str(terminal_reason_code).strip() or "superseded_by_terminal_packet",
        "reason_code": str(terminal_reason_code).strip() or None,
        "reason_detail": str(terminal_reason_detail).strip() or None,
        "retryable": False,
    }
    if str(followup_kind).strip() == "repair":
        status_payload["attempted"] = True
    _write_json(status_payload, status_path)
    return True


def _finalize_terminal_followups_for_task_root(
    task_root: Path,
    *,
    terminal_reason_code: str,
    terminal_reason_detail: str,
) -> None:
    _finalize_stale_followup_attempt(
        followup_kind="watchdog_retry",
        live_status_path=task_root / "watchdog_retry" / "live_status.json",
        status_path=task_root / "watchdog_retry" / "status.json",
        terminal_reason_code=terminal_reason_code,
        terminal_reason_detail=terminal_reason_detail,
    )
    _finalize_stale_followup_attempt(
        followup_kind="repair",
        live_status_path=task_root / "repair_live_status.json",
        status_path=task_root / "repair_status.json",
        terminal_reason_code=terminal_reason_code,
        terminal_reason_detail=terminal_reason_detail,
    )


def _mark_running_knowledge_status_files_interrupted(stage_root: Path) -> None:
    for live_status_path in stage_root.rglob("*live_status.json"):
        if live_status_path.name == "repair_live_status.json":
            _finalize_stale_followup_attempt(
                followup_kind="repair",
                live_status_path=live_status_path,
                status_path=live_status_path.parent / "repair_status.json",
                terminal_reason_code="cancelled_stage_interrupt",
                terminal_reason_detail="stage interrupted before repair completed",
            )
            continue
        if live_status_path.name != "live_status.json":
            continue
        parent_name = live_status_path.parent.name
        grandparent_name = (
            live_status_path.parent.parent.name if live_status_path.parent.parent else ""
        )
        if parent_name == "watchdog_retry" or grandparent_name == "retry_shards":
            _finalize_stale_followup_attempt(
                followup_kind="watchdog_retry",
                live_status_path=live_status_path,
                status_path=live_status_path.parent / "status.json",
                terminal_reason_code="cancelled_stage_interrupt",
                terminal_reason_detail="stage interrupted before follow-up completed",
            )
            continue
        payload = _load_json_dict(live_status_path)
        if not payload or str(payload.get("state") or "").strip() != "running":
            continue
        payload["state"] = "cancelled_due_to_interrupt"
        payload["reason_code"] = "operator_interrupt"
        payload["reason_detail"] = "stage interrupted before this attempt completed"
        payload["retryable"] = False
        payload["finished_at_utc"] = _format_utc_now()
        _write_json(dict(payload), live_status_path)


def _write_knowledge_stage_status(
    *,
    stage_root: Path,
    manifest_path: Path,
    stage_state: str,
    termination_cause: str,
    finalization_completeness: str,
) -> None:
    artifact_paths = {
        "phase_manifest.json": stage_root / "phase_manifest.json",
        "shard_manifest.jsonl": stage_root / "shard_manifest.jsonl",
        "task_manifest.jsonl": stage_root / "task_manifest.jsonl",
        "task_status.jsonl": stage_root / _KNOWLEDGE_TASK_STATUS_FILE_NAME,
        "worker_assignments.json": stage_root / "worker_assignments.json",
        "promotion_report.json": stage_root / "promotion_report.json",
        "telemetry.json": stage_root / "telemetry.json",
        "failures.json": stage_root / "failures.json",
        "knowledge_manifest.json": manifest_path,
        "proposals/*": stage_root / "proposals",
    }
    interrupted_before_finalization = (
        finalization_completeness == "interrupted_before_finalization"
    )
    artifact_states: dict[str, str] = {}
    for artifact_key, path in artifact_paths.items():
        present = (
            _knowledge_artifact_dir_has_files(path)
            if artifact_key == "proposals/*"
            else path.exists()
        )
        if present:
            artifact_states[artifact_key] = "present"
        elif interrupted_before_finalization:
            artifact_states[artifact_key] = "skipped_due_to_interrupt"
        else:
            artifact_states[artifact_key] = "unexpectedly_missing"
    _write_json(
        {
            "schema_version": _KNOWLEDGE_STAGE_STATUS_SCHEMA_VERSION,
            "stage_key": "nonrecipe_finalize",
            "stage_state": str(stage_state).strip() or None,
            "termination_cause": str(termination_cause).strip() or None,
            "finalization_completeness": str(finalization_completeness).strip() or None,
            "artifact_states": artifact_states,
            "pre_kill_failure_counts": _collect_knowledge_pre_kill_failure_counts(
                stage_root
            ),
        },
        stage_root / _KNOWLEDGE_STAGE_STATUS_FILE_NAME,
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
        else "no_final_output_file"
    )


def _terminal_reason_for_knowledge_task(
    *,
    proposal_status: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
    run_result: CodexExecRunResult,
    retry_skip_reason_code: str | None = None,
    retry_skip_reason_detail: str | None = None,
    repair_skip_reason_code: str | None = None,
    repair_skip_reason_detail: str | None = None,
) -> tuple[str | None, str | None]:
    if str(repair_skip_reason_code or "").strip():
        return (
            str(repair_skip_reason_code).strip(),
            str(repair_skip_reason_detail or "").strip() or None,
        )
    if str(retry_skip_reason_code or "").strip():
        return (
            str(retry_skip_reason_code).strip(),
            str(retry_skip_reason_detail or "").strip() or None,
        )
    if str(run_result.supervision_reason_code or "").strip():
        return (
            str(run_result.supervision_reason_code).strip(),
            str(run_result.supervision_reason_detail or "").strip() or None,
        )
    metadata = dict(validation_metadata or {})
    if proposal_status == "validated":
        return "validated", None
    if proposal_status == "no_final_output":
        return "no_final_output", None
    if validation_errors:
        return (
            str(validation_errors[0]).strip(),
            str(metadata.get("parse_error") or "").strip() or None,
        )
    return str(proposal_status).strip() or None, None


def _terminal_knowledge_task_state(
    *,
    proposal_status: str,
    supervision_state: str | None,
    terminal_reason_code: str | None = None,
    watchdog_retry_status: str = "not_attempted",
    retry_status: str = "not_attempted",
    repair_status: str = "not_attempted",
) -> str:
    cleaned_terminal_reason_code = str(terminal_reason_code or "").strip()
    if proposal_status == "validated":
        if repair_status == "repaired":
            return "repair_recovered"
        if retry_status == "recovered" or watchdog_retry_status == "recovered":
            return "retry_recovered"
        return "validated"
    if repair_status == "failed":
        return "repair_failed"
    if retry_status == "failed" or watchdog_retry_status == "failed":
        return "retry_failed"
    if str(supervision_state or "").strip() == "watchdog_killed":
        return "watchdog_killed"
    if proposal_status == "no_final_output":
        if knowledge_reason_is_explicit_no_final_output(cleaned_terminal_reason_code):
            return cleaned_terminal_reason_code
        return "no_final_output"
    return "invalid_output"


def _terminal_knowledge_attempt_type(
    *,
    watchdog_retry_status: str = "not_attempted",
    retry_status: str = "not_attempted",
    repair_status: str = "not_attempted",
) -> str:
    if repair_status != "not_attempted":
        return "repair"
    if retry_status != "not_attempted":
        return "retry_split"
    if watchdog_retry_status != "not_attempted":
        return "watchdog_retry"
    return "main_worker"
