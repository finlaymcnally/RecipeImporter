from __future__ import annotations

from typing import Protocol

from . import _shared as _shared_module
from .planning import (
    _KnowledgeFollowupDecision,
    _KnowledgeWorkspaceStageCommandViolation,
    _knowledge_packet_payloads,
)
from ..editable_task_file import TASK_FILE_NAME, load_task_file
from ..knowledge_runtime_state import knowledge_reason_is_explicit_no_final_output

globals().update(
    {
        name: value
        for name, value in vars(_shared_module).items()
        if not name.startswith("__")
    }
)


def _runtime_constant(name: str, default: Any) -> Any:
    return getattr(_shared_module, name, default)


def _format_knowledge_followup_label(
    *,
    parent_shard_id: str,
    attempt_label: str,
    task_id: str | None = None,
) -> str:
    cleaned_parent = str(parent_shard_id).strip()
    cleaned_attempt = str(attempt_label).strip()
    cleaned_task_id = str(task_id or "").strip()
    if cleaned_task_id and cleaned_task_id != cleaned_parent:
        return f"{cleaned_parent} {cleaned_attempt} {cleaned_task_id}".strip()
    return f"{cleaned_parent} {cleaned_attempt}".strip()


def _build_knowledge_workspace_progress_watchdog_callback(
    *,
    worker_id: str,
    progress_state: _KnowledgePhaseProgressState | None,
    expected_output_paths: Sequence[Path],
    live_status_path: Path,
    live_status_paths: Sequence[Path] | None = None,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState | None = None,
    watchdog_policy: str | None = None,
    allow_workspace_commands: bool = False,
) -> Callable[[CodexExecLiveSnapshot], CodexExecSupervisionDecision | None]:
    watchdog_callback = _build_strict_json_watchdog_callback(
        live_status_path=live_status_path,
        live_status_paths=live_status_paths,
        cohort_watchdog_state=cohort_watchdog_state,
        watchdog_policy=watchdog_policy,
        allow_workspace_commands=allow_workspace_commands,
        expected_workspace_output_paths=expected_output_paths,
    )
    expected_count = len(expected_output_paths)

    def _callback(
        snapshot: CodexExecLiveSnapshot,
    ) -> CodexExecSupervisionDecision | None:
        if progress_state is not None:
            progress_state.observe_workspace_outputs(
                worker_id=worker_id,
                present_count=sum(1 for path in expected_output_paths if path.exists()),
                expected_count=expected_count,
            )
        return watchdog_callback(snapshot)

    return _callback

@dataclass(slots=True)
class _KnowledgeRecoveryGovernor:
    lock: threading.Lock = field(default_factory=threading.Lock)
    worker_failure_signatures_by_id: dict[str, list[str]] = field(default_factory=dict)
    poisoned_workers: dict[str, dict[str, str]] = field(default_factory=dict)
    followup_attempts_by_kind: dict[str, int] = field(default_factory=dict)
    followup_successes_by_kind: dict[str, int] = field(default_factory=dict)
    repeated_failure_attempts_by_kind: dict[str, dict[str, int]] = field(default_factory=dict)

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
            signatures = self.worker_failure_signatures_by_id.setdefault(cleaned_worker_id, [])
            signatures.append(cleaned_signature)
            recent_signatures = signatures[-_KNOWLEDGE_POISONED_WORKER_MIN_FAILURES :]
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
                repeated = dict(self.repeated_failure_attempts_by_kind.get(cleaned_kind) or {})
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
            row["proposal_status"] = str(proposal_status).strip() if proposal_status is not None else None
            row["validation_errors"] = [
                str(error).strip()
                for error in validation_errors
                if str(error).strip()
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
                row["last_attempt_type"] = row.get("active_attempt_type") or row.get("last_attempt_type")
                row["active_attempt_type"] = None
                metadata = dict(row.get("metadata") or {})
                metadata["interruption_cause"] = "operator_interrupt"
                row["metadata"] = metadata
                row["terminal_reason_code"] = "cancelled_stage_interrupt"
                row["terminal_reason_detail"] = "stage interrupted before this packet reached a terminal outcome"
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


class _KnowledgeWorkspaceQueueController(Protocol):
    def observe_current_output(self) -> dict[str, Any]:
        ...

    def is_complete(self) -> bool:
        ...


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


def _combine_workspace_worker_run_results(
    run_results: Sequence[CodexExecRunResult],
) -> CodexExecRunResult:
    if len(run_results) == 1:
        return run_results[0]
    first = run_results[0]
    last = run_results[-1]
    usage = {
        "input_tokens": sum(int((result.usage or {}).get("input_tokens") or 0) for result in run_results),
        "cached_input_tokens": sum(
            int((result.usage or {}).get("cached_input_tokens") or 0)
            for result in run_results
        ),
        "output_tokens": sum(int((result.usage or {}).get("output_tokens") or 0) for result in run_results),
        "reasoning_tokens": sum(
            int((result.usage or {}).get("reasoning_tokens") or 0)
            for result in run_results
        ),
    }
    stdout_parts = [str(result.stdout_text or "").strip() for result in run_results if str(result.stdout_text or "").strip()]
    stderr_parts = [str(result.stderr_text or "").strip() for result in run_results if str(result.stderr_text or "").strip()]
    return CodexExecRunResult(
        command=list(last.command or first.command),
        subprocess_exit_code=last.subprocess_exit_code,
        output_schema_path=last.output_schema_path or first.output_schema_path,
        prompt_text=last.prompt_text or first.prompt_text,
        response_text=last.response_text,
        turn_failed_message=last.turn_failed_message,
        events=tuple(
            event
            for result in run_results
            for event in result.events
        ),
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
    task_state_counts = _load_task_status_state_counts(stage_root / _KNOWLEDGE_TASK_STATUS_FILE_NAME)
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
        grandparent_name = live_status_path.parent.parent.name if live_status_path.parent.parent else ""
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
    interrupted_before_finalization = finalization_completeness == "interrupted_before_finalization"
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
            "pre_kill_failure_counts": _collect_knowledge_pre_kill_failure_counts(stage_root),
        },
        stage_root / _KNOWLEDGE_STAGE_STATUS_FILE_NAME,
    )


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


def _write_worker_input(path: Path, *, payload: Any, input_text: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if input_text is not None:
        path.write_text(str(input_text), encoding="utf-8")
        return
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
        return
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _relative_path(base: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _build_knowledge_workspace_worker_prompt(
    *,
    stage_key: str,
    shards: Sequence[ShardManifestEntryV1] | None = None,
    tasks: Sequence[TaskManifestEntryV1] | None = None,
    fresh_session_resume: bool = False,
) -> str:
    del tasks
    shard_ids = [
        str(shard.shard_id).strip()
        for shard in (shards or [])
        if str(getattr(shard, "shard_id", "") or "").strip()
    ]
    lines = [
        "You are processing non-recipe finalize shards inside one bounded local workspace.",
        (
            "Resume from the existing `task.json` and current workspace state."
            if fresh_session_resume
            else (
                "Start with `task-summary`."
                " Then follow the repo-owned helper workflow shown there, edit only "
                f"`/units/*/answer` in `{TASK_FILE_NAME}`, save the same file, and run "
                "`task-handoff`."
            )
        ),
        "`task.json` is the whole job at each step. You do not need to discover extra control files or hidden repo state before editing it.",
        "",
        "The current working directory is already the workspace root.",
        "The helper is the only repo-side handoff seam. It validates the edited file and either finishes the assignment or rewrites `task.json` for the next step.",
        "",
        "Worker contract:",
        "- Start with `task.json`.",
        "- Prefer `task-summary` before opening raw file contents.",
        "- If you need orientation first, run `task-status`.",
        "- If the workspace feels inconsistent, run `task-doctor` before inventing shell scripts.",
        "- Edit only the `answer` object inside each unit.",
        "- After each edit pass, run `task-handoff` from the workspace root.",
        "- After the helper returns, trust the current `task.json` as the new whole job. You do not need to inspect other files to figure out what changed.",
        "- If the helper reports `repair_required` or `advance_to_grouping`, reopen the rewritten `task.json` immediately and continue in the same session.",
        "- Stop only after the helper reports `completed_without_grouping` or `completed_with_grouping`.",
        "- Do not invent queue advancement, control files, helper ledgers, or alternate output files.",
        "- `previous_answer` and `validation_feedback`, when present, are repair-only immutable context.",
        "- If you briefly reread part of `task.json` or make a small local false start, correct it and continue. Harmless local retries are not the point of failure here.",
        "- Do not dump `task.json` with `cat` or `sed`, do not use `ls` or `find` just to orient yourself, and do not write ad hoc inline Python, Node, or heredoc rewrites against `task.json`.",
        "- Other than repo-owned helper commands and tiny local temp helpers, do not use shell helpers on the happy path.",
        "- Stay inside this workspace: do not inspect parent directories or the repository, keep every visible path local, and do not use repo/network/package-manager commands such as `git`, `curl`, or `npm`.",
        "",
        "Shard semantics:",
        "- The repo does not know the `knowledge` versus `other` answer ahead of time; you make that semantic call from the owned shard text.",
        "- You are doing close semantic review, not building a heuristic classifier for the whole packet.",
        "- Read the actual owned block text before deciding. That text is primary evidence.",
        "- Use nearby rows only to disambiguate edge cases; do not force nearby rows into the same answer just because they are adjacent.",
        "- Treat `candidate_tag_keys`, heading shape, and packet position as weak hints only, not votes or proof.",
        "- If you feel tempted to invent a rule that covers many rows at once, stop and reread the actual owned rows instead.",
    ]
    if stage_key == "nonrecipe_classify":
        lines.extend(
            [
                "- This is the classification step. Decide each block on its own merits before any grouping happens.",
                "- Use `task-show-current` for the current owned block, `task-show-neighbors` only when nearby context is genuinely needed, and `task-answer-current '<answer_json>'` to record one decision at a time.",
                "- Use `task-next` to confirm the next actionable block after each decision. Do not synthesize `answers.json`, `task-apply`, `jq`, or looped bulk-review flows for this step.",
                "- Answer each unit with `category`, `reviewer_category`, `retrieval_concept`, and `grounding`.",
                f"- Final categories must be exactly one of `{'`, `'.join(ALLOWED_KNOWLEDGE_FINAL_CATEGORIES)}`.",
                "- If `category` is `knowledge`, `reviewer_category` must also be `knowledge`.",
                "- If `category` is `knowledge`, `retrieval_concept` must be a short standalone concept and `grounding` must include at least one existing `tag_key` or one proposed tag.",
                "- If `category` is `other`, `reviewer_category` must be a non-knowledge reviewer category or `other`.",
                "- If `category` is `other`, leave `retrieval_concept` null and keep grounding empty.",
                "- Short conceptual headings can still be `knowledge` when they introduce real explanatory content; shortness alone is not enough to drop a block.",
                "- `grounding.category_keys` are optional support only; category-only grounding is not enough to keep a block.",
                "- Proposed tags are allowed only for real retrieval-grade concepts that do not fit an existing tag; use an existing `category_key` and a normalized slug `key`.",
                "- Do not compress the packet into one global keep/drop rule, one heading rule, or one candidate-tag rule.",
                "- Do not invent `group_key`, `topic_label`, packet summaries, or cross-unit grouping notes in this step.",
                "- The owned block rows are authoritative. Nearby context is informational only.",
            ]
        )
    else:
        lines.extend(
            [
                "- This is the grouping-only step. Every unit already passed classification as `knowledge`.",
                "- Inspect specific rows with `task-show-unit <unit_id>` or `task-show-unanswered --limit 5`.",
                "- If batch authoring helps, run `task-template answers.json`, fill only the answer payloads, then run `task-apply answers.json` before `task-handoff`.",
                "- Answer each unit with `group_key` and `topic_label` only.",
                "- `group_key` and `topic_label` must both be non-empty strings.",
                "- Use concise group labels; the repo canonicalizes final group ids during deterministic expansion.",
                "- Do not revisit keep/drop classification in this step.",
            ]
        )
    lines.extend(
        [
        "",
        (
            "Assigned shard ids represented in this task file: "
            f"`{', '.join(shard_ids) if shard_ids else '[none]'}`."
        ),
        "",
        "Do not return shard outputs in your final message. The authoritative result is the edited task file.",
        ]
    )
    return "\n".join(lines)


_KNOWLEDGE_HINT_EXAMPLE_FILES = (
    "valid_semantic_packet.json",
    "valid_all_other_low_utility_packet.json",
    "valid_all_other_framing_packet.json",
    "valid_heading_with_useful_body_packet.json",
    "valid_all_other_navigation_packet.json",
)


def _looks_knowledge_hint_heading_like(
    *,
    text: str,
    heading_level: Any,
) -> bool:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return False
    if heading_level is not None:
        return True
    if len(cleaned) > 80:
        return False
    if cleaned.endswith("?"):
        return True
    alpha_chars = [char for char in cleaned if char.isalpha()]
    if alpha_chars and cleaned == cleaned.upper():
        return True
    return "." not in cleaned and len(cleaned.split()) <= 8


def _build_knowledge_hint_attention_lines(
    packet_blocks: Sequence[Mapping[str, Any]],
) -> list[str]:
    attention_lines: list[str] = []
    previous_index: int | None = None
    for block in packet_blocks:
        try:
            block_index = int(block.get("i"))
        except (TypeError, ValueError):
            continue
        text = str(block.get("t") or "").strip()
        if not text:
            continue
        heading_level = block.get("hl")
        cues: list[str] = []
        if _looks_knowledge_hint_heading_like(text=text, heading_level=heading_level):
            cues.append("heading_like")
        if isinstance(block.get("th"), Mapping):
            cues.append("table_hint")
        if len(text) >= 240:
            cues.append("long_prose")
        if previous_index is not None:
            gap = int(block_index) - int(previous_index)
            if gap > 8:
                cues.append(f"gap_from_prev={gap}")
        previous_index = block_index
        if not cues or len(attention_lines) >= 10:
            continue
        attention_lines.append(
            f"`{block_index}` `{preview_text(text, max_chars=90)}` -> cues `{', '.join(cues)}`"
        )
    if attention_lines:
        return attention_lines
    return [
        "No special attention rows were flagged. Read the owned block text in order and classify each block on its own merits."
    ]


def _build_knowledge_hint_profile_and_policy(
    packet_blocks: Sequence[Mapping[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    block_indices: list[int] = []
    heading_count = 0
    table_hint_count = 0
    long_prose_count = 0
    heading_like_count = 0
    large_gap_count = 0
    previous_index: int | None = None
    for block in packet_blocks:
        try:
            block_index = int(block.get("i"))
        except (TypeError, ValueError):
            continue
        block_indices.append(block_index)
        text = str(block.get("t") or "").strip()
        if block.get("hl") is not None:
            heading_count += 1
        if isinstance(block.get("th"), Mapping):
            table_hint_count += 1
        if len(text) >= 240:
            long_prose_count += 1
        if _looks_knowledge_hint_heading_like(text=text, heading_level=block.get("hl")):
            heading_like_count += 1
        if previous_index is not None and (block_index - previous_index) > 8:
            large_gap_count += 1
        previous_index = block_index

    owned_block_range = (
        f"{block_indices[0]}..{block_indices[-1]}" if block_indices else "unknown"
    )
    profile_lines = [
        f"Owned blocks: {len(block_indices)} (`{owned_block_range}`).",
        (
            "Packet shape cues: "
            f"`heading_like={heading_like_count}`, "
            f"`explicit_heading={heading_count}`, "
            f"`table_hint={table_hint_count}`, "
            f"`long_prose={long_prose_count}`."
        ),
        f"Large source gaps (>8 rows): `{large_gap_count}`.",
    ]
    if table_hint_count > 0:
        shard_summary = "Reference-style packet with table cues."
    elif heading_like_count > 0 and long_prose_count > 0:
        shard_summary = "Heading-plus-body packet."
    elif long_prose_count >= max(2, len(block_indices) // 2):
        shard_summary = "Long-form prose packet."
    else:
        shard_summary = "Mixed non-recipe packet."
    interpretation_lines = [
        shard_summary,
        "Use packet order and neighboring rows as weak context only, not as proof that blocks belong together.",
    ]
    decision_policy = [
        "Decide `knowledge` versus `other` block-by-block before thinking about grouping.",
        "Use your own semantic judgment; the repo will validate only structure and coverage.",
        "Do not turn heading shape, candidate tags, or packet profile into a bulk heuristic; read the actual owned block text.",
        "If a short heading feels ambiguous, ask whether it introduces portable cooking knowledge, not whether it is merely short.",
        "Open `examples/` only when you need a contrast case or tie-breaker.",
    ]
    return profile_lines, interpretation_lines, decision_policy


def _write_knowledge_worker_hint(
    *,
    path: Path,
    shard: ShardManifestEntryV1,
) -> None:
    payload = _coerce_dict(shard.input_payload)
    packet_blocks = [
        dict(block)
        for block in (payload.get("b") or [])
        if isinstance(block, Mapping)
    ]
    nearby_recipe_blocks: list[int] = []
    for value in (_coerce_dict(payload.get("g")).get("r") or []):
        try:
            nearby_recipe_blocks.append(int(value))
        except (TypeError, ValueError):
            continue
    packet_id = str(payload.get("bid") or shard.shard_id).strip() or "[unknown packet]"
    block_indices = [
        int(block.get("i", 0))
        for block in packet_blocks
        if block.get("i") is not None
    ]
    shard_profile, shard_interpretation, decision_policy = (
        _build_knowledge_hint_profile_and_policy(packet_blocks)
    )
    attention_lines = _build_knowledge_hint_attention_lines(packet_blocks)
    shard_examples = [f"`examples/{name}`" for name in _KNOWLEDGE_HINT_EXAMPLE_FILES]
    write_worker_hint_markdown(
        path,
        title=f"Knowledge review hints for {shard.shard_id}",
        summary_lines=[
            "This sidecar is worker guidance only; `in/<shard_id>.json` remains authoritative.",
            f"Packet id: `{packet_id}`. Owned blocks: `{len(packet_blocks)}`.",
            (
                "Nearby recipe guardrail block indices: `"
                + (
                    ", ".join(str(value) for value in nearby_recipe_blocks[:12])
                    if nearby_recipe_blocks
                    else "none"
                )
                + "`."
            ),
        ],
        sections=[
            ("Shard profile", shard_profile),
            ("Shard interpretation", shard_interpretation),
            ("Decision policy", decision_policy),
            ("Shard examples", shard_examples),
            ("Attention rows", attention_lines),
        ],
    )


def _distribute_knowledge_session_value(value: Any, task_count: int) -> list[int]:
    normalized_task_count = max(1, int(task_count))
    total = int(value or 0)
    base, remainder = divmod(total, normalized_task_count)
    return [base + (1 if index < remainder else 0) for index in range(normalized_task_count)]


def _build_knowledge_workspace_task_runner_payload(
    *,
    pipeline_id: str,
    worker_id: str,
    shard_id: str,
    runtime_task_id: str,
    run_result: CodexExecRunResult,
    model: str | None,
    reasoning_effort: str | None,
    request_input_file: Path,
    worker_prompt_path: Path,
    worker_root: Path,
    task_count: int,
    task_index: int,
) -> dict[str, Any]:
    payload = run_result.to_payload(worker_id=worker_id, shard_id=shard_id)
    telemetry = payload.get("telemetry")
    row_payload = None
    if isinstance(telemetry, Mapping):
        rows = telemetry.get("rows")
        if isinstance(rows, list) and rows:
            first_row = rows[0]
            if isinstance(first_row, Mapping):
                row_payload = dict(first_row)
    request_input_file_str = str(request_input_file)
    request_input_file_bytes = (
        request_input_file.stat().st_size if request_input_file.exists() else None
    )
    worker_prompt_file_str = str(worker_prompt_path)
    if row_payload is not None:
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
            shares = _distribute_knowledge_session_value(row_payload.get(field_name), task_count)
            row_payload[field_name] = shares[task_index]
        row_payload["tokens_total"] = (
            int(row_payload.get("tokens_input") or 0)
            + int(row_payload.get("tokens_cached_input") or 0)
            + int(row_payload.get("tokens_output") or 0)
            + int(row_payload.get("tokens_reasoning") or 0)
        )
        row_payload["prompt_input_mode"] = "workspace_worker"
        row_payload["request_input_file"] = request_input_file_str
        row_payload["request_input_file_bytes"] = request_input_file_bytes
        row_payload["worker_prompt_file"] = worker_prompt_file_str
        row_payload["worker_session_task_count"] = task_count
        row_payload["worker_session_primary_row"] = task_index == 0
        row_payload["runtime_task_id"] = runtime_task_id
        row_payload["runtime_parent_shard_id"] = shard_id
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
        "status": _run_result_process_status(run_result),
        "codex_model": model,
        "codex_reasoning_effort": reasoning_effort,
        "prompt_input_mode": "workspace_worker",
        "request_input_file": request_input_file_str,
        "request_input_file_bytes": request_input_file_bytes,
        "worker_prompt_file": worker_prompt_file_str,
        "runtime_task_id": runtime_task_id,
        "runtime_parent_shard_id": shard_id,
        "events_path": str(worker_root / "events.jsonl"),
        "last_message_path": str(worker_root / "last_message.json"),
        "usage_path": str(worker_root / "usage.json"),
        "live_status_path": str(worker_root / "live_status.json"),
        "workspace_manifest_path": str(worker_root / "workspace_manifest.json"),
        "stdout_path": str(worker_root / "stdout.txt"),
        "stderr_path": str(worker_root / "stderr.txt"),
    }
    return payload


def _build_knowledge_inline_attempt_runner_payload(
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
        "status": _run_result_process_status(run_result),
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

def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _load_knowledge_response_json_object(
    response_text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cleaned_response_text = str(response_text or "").strip()
    candidate_texts: list[tuple[str, dict[str, Any]]] = [(cleaned_response_text, {})]
    if cleaned_response_text.endswith("EOF"):
        trimmed = cleaned_response_text.removesuffix("EOF").rstrip()
        if trimmed:
            candidate_texts.append((trimmed, {"response_trailing_eof_trimmed": True}))
    salvaged_object_text, salvage_metadata = _salvage_knowledge_json_object_suffix(
        cleaned_response_text
    )
    if salvaged_object_text is not None:
        candidate_texts.append((salvaged_object_text, dict(salvage_metadata or {})))
    last_json_error: json.JSONDecodeError | None = None
    for candidate_text, candidate_metadata in candidate_texts:
        try:
            parsed_payload = json.loads(candidate_text)
        except json.JSONDecodeError as exc:
            last_json_error = exc
            continue
        if not isinstance(parsed_payload, dict):
            raise TypeError(type(parsed_payload).__name__)
        return dict(parsed_payload), dict(candidate_metadata or {})
    if last_json_error is not None:
        raise last_json_error
    raise json.JSONDecodeError("Expected JSON object", cleaned_response_text, 0)


def _evaluate_knowledge_response(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    payload: dict[str, Any] | None = None
    validation_errors: tuple[str, ...] = ()
    validation_metadata: dict[str, Any] = {}
    proposal_status = "validated"
    cleaned_response_text = str(response_text or "").strip()
    if not cleaned_response_text:
        return None, ("missing_output_file",), {}, "no_final_output"
    try:
        parsed_payload, response_parse_metadata = _load_knowledge_response_json_object(
            cleaned_response_text
        )
    except json.JSONDecodeError as exc:
        return None, ("response_json_invalid",), {"parse_error": str(exc)}, "invalid"
    except TypeError as exc:
        return (
            None,
            ("response_not_json_object",),
            {"response_type": str(exc)},
            "invalid",
        )
    try:
        payload, normalization_metadata = normalize_knowledge_worker_payload(parsed_payload)
    except Exception as exc:  # noqa: BLE001
        return None, ("schema_invalid",), {"parse_error": str(exc)}, "invalid"
    valid, validation_errors, validation_metadata = validate_knowledge_shard_output(
        shard,
        parsed_payload,
    )
    validation_metadata = {
        **dict(validation_metadata or {}),
        **dict(response_parse_metadata or {}),
        **dict(normalization_metadata or {}),
    }
    proposal_status = "validated" if valid else "invalid"
    return payload, tuple(validation_errors), dict(validation_metadata or {}), proposal_status


def _preflight_knowledge_shard(
    shard: ShardManifestEntryV1,
) -> dict[str, Any] | None:
    payload = _coerce_dict(shard.input_payload)
    owned_ids = [str(value).strip() for value in shard.owned_ids if str(value).strip()]
    if not owned_ids:
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "knowledge shard has no owned packet ids",
        }
    if (
        not str(payload.get("bid") or payload.get("packet_id") or "").strip()
        and isinstance(payload.get("b"), list)
    ):
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "knowledge shard is missing `bid`",
        }
    packet_payloads = _knowledge_packet_payloads(payload)
    if not packet_payloads:
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "knowledge shard has no model-facing packets",
        }
    packet_ids: list[str] = []
    for packet_payload in packet_payloads:
        packet_id = str(packet_payload.get("bid") or packet_payload.get("packet_id") or "").strip()
        if not packet_id:
            return {
                "reason_code": "preflight_invalid_shard_payload",
                "reason_detail": "knowledge shard contains a packet without `bid`",
            }
        packet_ids.append(packet_id)
        blocks = packet_payload.get("b")
        if not isinstance(blocks, list) or not blocks:
            return {
                "reason_code": "preflight_invalid_shard_payload",
                "reason_detail": "knowledge shard contains an empty model-facing packet",
            }
        for block in blocks:
            if not isinstance(block, Mapping):
                return {
                    "reason_code": "preflight_invalid_shard_payload",
                    "reason_detail": "knowledge shard contains a non-object block payload",
                }
            block_index = block.get("i")
            if block_index is None:
                return {
                    "reason_code": "preflight_invalid_shard_payload",
                    "reason_detail": "knowledge shard contains a block without `i`",
                }
    if sorted(owned_ids) != sorted(packet_ids):
        return {
            "reason_code": "preflight_invalid_shard_payload",
            "reason_detail": "knowledge shard owned ids do not match packet payload ids",
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
    cohort_watchdog_state: _KnowledgeCohortWatchdogState | None = None,
    shard_id: str | None = None,
    watchdog_policy: str = _STRICT_JSON_WATCHDOG_POLICY,
    allow_workspace_commands: bool = False,
    execution_workspace_root: Path | None = None,
    forbid_inline_python_heredocs: bool = False,
    silence_timeout_seconds: float | None = None,
    expected_workspace_output_paths: Sequence[Path] | None = None,
    task_queue_controller: _KnowledgeWorkspaceQueueController | None = None,
    workspace_output_observer: Callable[[int, int], None] | None = None,
    workspace_completion_quiescence_seconds: float | None = None,
) -> Callable[[CodexExecLiveSnapshot], CodexExecSupervisionDecision | None]:
    target_paths: list[Path] = []
    if live_status_path is not None:
        target_paths.append(live_status_path)
    if live_status_paths is not None:
        target_paths.extend(Path(path) for path in live_status_paths)
    completion_quiescence_seconds = float(
        workspace_completion_quiescence_seconds
        if workspace_completion_quiescence_seconds is not None
        else _KNOWLEDGE_WORKSPACE_COMPLETION_QUIESCENCE_SECONDS
    )
    workspace_output_paths = [Path(path) for path in (expected_workspace_output_paths or [])]
    last_complete_workspace_signature: tuple[tuple[str, int, int], ...] | None = None
    workspace_output_stable_passes = 0
    last_workspace_signature: tuple[tuple[str, int, int], ...] | None = None
    last_workspace_present_count = 0
    last_output_progress_command_count: int | None = None
    completion_wait_started_elapsed_seconds: float | None = None
    completion_wait_agent_message_count: int | None = None
    completion_wait_turn_completed_count: int | None = None
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
        nonlocal last_workspace_signature
        nonlocal last_workspace_present_count
        nonlocal last_output_progress_command_count
        nonlocal completion_wait_started_elapsed_seconds
        nonlocal completion_wait_agent_message_count
        nonlocal completion_wait_turn_completed_count
        nonlocal last_single_file_command_count
        decision: CodexExecSupervisionDecision | None = None
        command_execution_tolerated = False
        last_command_stage_violation: _KnowledgeWorkspaceStageCommandViolation | None = None
        current_workspace_stage_key = _workspace_task_stage_key(execution_workspace_root)
        allowed_absolute_roots = (
            [execution_workspace_root]
            if execution_workspace_root is not None
            else None
        )
        last_command_verdict = classify_workspace_worker_command(
            snapshot.last_command,
            allowed_absolute_roots=allowed_absolute_roots,
            single_file_worker_policy=allow_workspace_commands,
        )
        last_command_boundary_violation = detect_workspace_worker_boundary_violation(
            snapshot.last_command,
            allowed_absolute_roots=allowed_absolute_roots,
        )
        final_agent_message_state = str(snapshot.final_agent_message_state or "absent")
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
        workspace_output_status = _summarize_workspace_output_paths(workspace_output_paths)
        if workspace_output_observer is not None:
            workspace_output_observer(
                int(workspace_output_status["present_count"]),
                int(workspace_output_status["expected_count"]),
            )
        current_workspace_signature = tuple(workspace_output_status["signature"])
        current_workspace_present_count = int(workspace_output_status["present_count"])
        task_queue_observation = (
            task_queue_controller.observe_current_output()
            if task_queue_controller is not None
            else None
        )
        workspace_output_progress_observed = False
        if current_workspace_present_count > last_workspace_present_count:
            workspace_output_progress_observed = True
        elif current_workspace_signature and current_workspace_signature != last_workspace_signature:
            workspace_output_progress_observed = True
        if workspace_output_progress_observed:
            last_output_progress_command_count = int(snapshot.command_execution_count or 0)
        last_workspace_present_count = current_workspace_present_count
        last_workspace_signature = current_workspace_signature or None
        recent_workspace_output_progress = (
            last_output_progress_command_count is not None
            and int(snapshot.command_execution_count or 0) - last_output_progress_command_count
            <= _KNOWLEDGE_WORKSPACE_PROGRESS_GRACE_COMMANDS
        )
        if workspace_output_status["complete"]:
            if current_workspace_signature == last_complete_workspace_signature:
                workspace_output_stable_passes += 1
            else:
                last_complete_workspace_signature = current_workspace_signature
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
        completion_waiting_for_exit = False
        completion_post_signal_observed = False
        completion_queue_completed = bool(
            allow_workspace_commands
            and task_queue_controller is not None
            and task_queue_controller.is_complete()
        )
        completion_outputs_completed = bool(
            allow_workspace_commands
            and task_queue_controller is None
            and workspace_output_status["complete"]
        )
        if completion_queue_completed or completion_outputs_completed:
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
                    or completion_outputs_completed
                )
            )
            if completion_post_signal_observed or completion_quiescence_reached:
                decision = CodexExecSupervisionDecision.terminate(
                    reason_code=(
                        "workspace_validated_task_queue_completed"
                        if completion_queue_completed
                        else "workspace_expected_outputs_completed"
                    ),
                    reason_detail=(
                        "knowledge workspace worker produced repo-validated outputs for "
                        "every assigned current task and the session either emitted "
                        "a post-install completion signal or went quiet while waiting to exit"
                        if completion_queue_completed
                        else (
                            "knowledge workspace worker produced every expected shard "
                            "output and the session either emitted a post-output "
                            "completion signal or remained in completion-wait long "
                            "enough to treat the assignment as done"
                        )
                    ),
                    retryable=False,
                    supervision_state="completed",
                )
        if snapshot.command_execution_count > 0:
            if decision is None and allow_workspace_commands:
                last_command_stage_violation = _detect_knowledge_workspace_stage_violation(
                    snapshot.last_command,
                    current_stage_key=current_workspace_stage_key,
                )
                if (
                    forbid_inline_python_heredocs
                    and re.search(
                        r"\bpython3?\b\s+-\s*<<['\"]?PY['\"]?",
                        str(snapshot.last_command or ""),
                    )
                ):
                    _record_warning(
                        "inline_python_heredoc_used",
                        "workspace worker used inline python heredoc execution instead "
                        "of a short local file or direct task-file editing",
                    )
                if (
                    decision is None
                    and last_command_stage_violation is not None
                    and last_command_stage_violation.enforce
                ):
                    decision = CodexExecSupervisionDecision.terminate(
                        reason_code=str(
                            last_command_stage_violation.reason_code or "stage_violation"
                        ),
                        reason_detail=last_command_stage_violation.reason,
                        retryable=False,
                    )
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
                if decision is None and last_command_boundary_violation is None:
                    command_execution_tolerated = True
                elif decision is None:
                    decision = CodexExecSupervisionDecision.terminate(
                        reason_code="boundary_command_execution_forbidden",
                        reason_detail=format_watchdog_command_reason_detail(
                            stage_label="workspace worker stage",
                            last_command=snapshot.last_command,
                        ),
                        retryable=False,
                        supervision_state="boundary_interrupted",
                    )
                if (
                    decision is None
                    and should_terminate_workspace_command_loop(
                        snapshot=snapshot,
                        recent_output_progress=recent_workspace_output_progress,
                        completed_output_count=current_workspace_present_count,
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
        elif not allow_workspace_commands and final_agent_message_state == "malformed":
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_malformed_final_output",
                reason_detail=(
                    snapshot.final_agent_message_reason
                    or "strict JSON stage emitted malformed pseudo-final output"
                ),
                retryable=True,
            )
        elif snapshot.reasoning_item_count >= 2 and final_agent_message_state != "json_object":
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
            silence_timeout_seconds is not None
            and snapshot.last_event_seconds_ago is not None
            and snapshot.last_event_seconds_ago >= float(silence_timeout_seconds)
            and final_agent_message_state != "json_object"
        ):
            decision = CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_no_activity_timeout",
                reason_detail=(
                    "strict JSON stage emitted no new activity for "
                    f"{int(float(silence_timeout_seconds))} seconds without reaching final output"
                ),
                retryable=True,
            )
        elif (
            cohort_completed_successful_shards >= _KNOWLEDGE_COHORT_WATCHDOG_MIN_COMPLETED_SHARDS
            and int(cohort_median_duration_ms or 0) > 0
            and (snapshot.elapsed_seconds * 1000.0)
            >= float(
                _runtime_constant(
                    "_KNOWLEDGE_COHORT_WATCHDOG_MIN_ELAPSED_MS",
                    _KNOWLEDGE_COHORT_WATCHDOG_MIN_ELAPSED_MS,
                )
            )
            and (snapshot.elapsed_seconds * 1000.0)
            >= (
                float(cohort_median_duration_ms)
                * float(
                    _runtime_constant(
                        "_KNOWLEDGE_COHORT_WATCHDOG_MEDIAN_FACTOR",
                        _KNOWLEDGE_COHORT_WATCHDOG_MEDIAN_FACTOR,
                    )
                )
            )
            and final_agent_message_state != "json_object"
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
            "last_command_stage_violation_detected": (
                last_command_stage_violation is not None
            ),
            "last_command_stage_policy": (
                last_command_stage_violation.policy
                if last_command_stage_violation is not None
                else None
            ),
            "last_command_stage_reason": (
                last_command_stage_violation.reason
                if last_command_stage_violation is not None
                else None
            ),
            "last_command_stage_violation_enforced": (
                bool(last_command_stage_violation.enforce)
                if last_command_stage_violation is not None
                else None
            ),
            "reasoning_item_count": snapshot.reasoning_item_count,
            "last_command": snapshot.last_command,
            "last_command_repeat_count": snapshot.last_command_repeat_count,
            "live_activity_summary": snapshot.live_activity_summary,
            "has_final_agent_message": snapshot.has_final_agent_message,
            "final_agent_message_state": final_agent_message_state,
            "final_agent_message_reason": snapshot.final_agent_message_reason,
            "timeout_seconds": snapshot.timeout_seconds,
            "silence_timeout_seconds": (
                round(float(silence_timeout_seconds), 3)
                if silence_timeout_seconds is not None
                else None
            ),
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
            "workspace_output_progress_observed": workspace_output_progress_observed,
            "workspace_recent_output_progress": recent_workspace_output_progress,
            "workspace_completion_waiting_for_exit": completion_waiting_for_exit,
            "workspace_completion_quiescence_seconds": (
                completion_quiescence_seconds
                if completion_waiting_for_exit
                else None
            ),
            "workspace_completion_post_signal_observed": completion_post_signal_observed,
            **(
                task_queue_controller.status_payload()
                if task_queue_controller is not None
                else {}
            ),
            "queue_current_output_present": (
                bool(task_queue_observation.get("current_output_present"))
                if isinstance(task_queue_observation, Mapping)
                else None
            ),
            "queue_last_observed_task_id": (
                task_queue_observation.get("current_task_id")
                if isinstance(task_queue_observation, Mapping)
                else None
            ),
            "queue_last_observation_advanced": (
                bool(task_queue_observation.get("advanced"))
                if isinstance(task_queue_observation, Mapping)
                else None
            ),
            "reason_code": decision.reason_code if decision is not None else None,
            "reason_detail": decision.reason_detail if decision is not None else None,
            "retryable": decision.retryable if decision is not None else False,
            "warning_codes": list(persistent_warning_codes),
            "warning_details": list(persistent_warning_details),
            "warning_count": len(persistent_warning_codes),
        }
        for path in target_paths:
            _write_live_status(path, status_payload)
        return decision

    return _callback


def _detect_knowledge_workspace_stage_violation(
    command_text: str | None,
    *,
    current_stage_key: str | None = None,
) -> _KnowledgeWorkspaceStageCommandViolation | None:
    cleaned_command = str(command_text or "").strip()
    if not cleaned_command:
        return None
    normalized_command = re.sub(r"\s+", " ", cleaned_command.lower())
    cleaned_stage_key = str(current_stage_key or "").strip()

    if cleaned_stage_key == "nonrecipe_classify":
        if any(
            marker in normalized_command
            for marker in (
                "task-apply",
                "--apply-answers-file",
                "task-template",
                "--show-unanswered",
                "task-show-unanswered",
                "answers.json",
            )
        ):
            return _KnowledgeWorkspaceStageCommandViolation(
                policy="knowledge_classification_batch_synthesis",
                reason_code="watchdog_packet_contract_bypass_batch_classification",
                reason=(
                    "knowledge classification is queue-style review. Use "
                    "`task-show-current`, `task-answer-current`, and `task-next` "
                    "instead of batch answer files or broad unanswered-unit dumps"
                ),
            )
        if (
            ("jq" in normalized_command or "python3 -c" in normalized_command or "python -c" in normalized_command)
            and "task.json" in normalized_command
        ):
            return _KnowledgeWorkspaceStageCommandViolation(
                policy="knowledge_classification_bulk_synthesis",
                reason_code="watchdog_packet_contract_bypass_bulk_classification",
                reason=(
                    "knowledge classification must stay block-by-block. Do not script "
                    "task.json synthesis; use `task-show-current` and "
                    "`task-answer-current`"
                ),
            )
        if (
            ("for " in normalized_command or "while " in normalized_command or "$(seq" in normalized_command)
            and any(
                marker in normalized_command
                for marker in ("task.json", "answers.json", "task-show-current")
            )
        ):
            return _KnowledgeWorkspaceStageCommandViolation(
                policy="knowledge_classification_looped_bulk_review",
                reason_code="watchdog_packet_contract_bypass_bulk_classification",
                reason=(
                    "knowledge classification should not invent looped queue walkers. "
                    "Review one current block at a time with the repo-owned queue helpers"
                ),
            )

    if "assigned_shards.json" in normalized_command:
        return _KnowledgeWorkspaceStageCommandViolation(
            policy="knowledge_assigned_shards_inventory_dump",
            reason_code="watchdog_phase_contract_bypass_inventory_dump",
            reason=(
                "knowledge task-file workers should not dump or script broadly against "
                "`assigned_shards.json`; use `task.json` first and treat "
                "`assigned_shards.json` as fallback ownership context only"
            ),
            enforce=False,
        )

    if (
        ("for " in normalized_command or "while " in normalized_command or "$(seq" in normalized_command)
        and any(
                marker in normalized_command
                for marker in (
                    "out/",
                    "task.json",
                    "assigned_shards.json",
                )
            )
    ):
        return _KnowledgeWorkspaceStageCommandViolation(
            policy="knowledge_packet_shell_scheduler_bypass",
            reason_code="watchdog_packet_contract_bypass_shell_scheduler",
            reason=(
                "knowledge task-file workers should avoid inventing queue/output schedulers "
                "or broad validation loops over assignment/output files; keep any local "
                "automation bounded to the current task file and shard outputs"
            ),
            enforce=False,
        )

    rewrites_runtime_control = any(
        marker in normalized_command
        for marker in (
            "> live_status.json",
            ">> live_status.json",
            "> knowledge_same_session_state.json",
            ">> knowledge_same_session_state.json",
            "path('live_status.json').write_text(",
            'path("live_status.json").write_text(',
            "path('knowledge_same_session_state.json').write_text(",
            'path("knowledge_same_session_state.json").write_text(',
        )
    )
    if rewrites_runtime_control:
        return _KnowledgeWorkspaceStageCommandViolation(
            policy="knowledge_task_file_runtime_control_rewrite",
            reason_code="watchdog_packet_contract_bypass_runtime_control_rewrite",
            reason=(
                "knowledge task-file workers must not rewrite repo-owned runtime state "
                "such as `live_status.json` or same-session state files; the repo owns "
                "task progression"
            ),
        )

    return None


def _finalize_live_status(
    live_status_path: Path,
    *,
    run_result: CodexExecRunResult,
    watchdog_policy: str = _STRICT_JSON_WATCHDOG_POLICY,
) -> None:
    existing_payload = _load_live_status(live_status_path)
    final_agent_message = assess_final_agent_message(
        run_result.response_text,
        workspace_mode=run_result.workspace_mode,
    )
    state = str(run_result.supervision_state or "completed").strip() or "completed"
    reason_code = run_result.supervision_reason_code
    reason_detail = run_result.supervision_reason_detail
    if state == "completed" and not str(reason_code or "").strip():
        reason_code = "process_exited_without_watchdog_intervention"
        reason_detail = (
            str(reason_detail or "").strip()
            or "worker process exited without watchdog intervention"
        )
    if state == "completed" and existing_payload.get("warning_count"):
        state = "completed_with_warnings"
    _write_live_status(
        live_status_path,
        {
            "state": state,
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "retryable": run_result.supervision_retryable,
            "duration_ms": run_result.duration_ms,
            "started_at_utc": run_result.started_at_utc,
            "finished_at_utc": run_result.finished_at_utc,
            "watchdog_policy": watchdog_policy,
            "has_final_agent_message": final_agent_message.state != "absent",
            "final_agent_message_state": final_agent_message.state,
            "final_agent_message_reason": final_agent_message.reason,
            "warning_codes": list(existing_payload.get("warning_codes") or []),
            "warning_details": list(existing_payload.get("warning_details") or []),
            "warning_count": int(existing_payload.get("warning_count") or 0),
        },
    )


def _workspace_task_stage_key(workspace_root: Path | None) -> str | None:
    if workspace_root is None:
        return None
    task_file_path = Path(workspace_root) / TASK_FILE_NAME
    if not task_file_path.exists():
        return None
    try:
        payload = load_task_file(task_file_path)
    except Exception:  # noqa: BLE001
        return None
    cleaned = str(payload.get("stage_key") or "").strip()
    return cleaned or None


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
        return str(repair_skip_reason_code).strip(), str(repair_skip_reason_detail or "").strip() or None
    if str(retry_skip_reason_code or "").strip():
        return str(retry_skip_reason_code).strip(), str(retry_skip_reason_detail or "").strip() or None
    if str(run_result.supervision_reason_code or "").strip():
        return str(run_result.supervision_reason_code).strip(), str(run_result.supervision_reason_detail or "").strip() or None
    metadata = dict(validation_metadata or {})
    if proposal_status == "validated":
        return "validated", None
    if proposal_status == "no_final_output":
        return "no_final_output", None
    if validation_errors:
        return str(validation_errors[0]).strip(), str(metadata.get("parse_error") or "").strip() or None
    return str(proposal_status).strip() or None, None


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


def _run_result_process_status(run_result: CodexExecRunResult) -> str:
    return "done" if run_result.completed_successfully() else "failed"


def _classify_knowledge_watchdog_retry_size(
    *,
    shard: ShardManifestEntryV1,
) -> dict[str, Any]:
    metadata = dict(shard.metadata or {})
    payload = _coerce_dict(shard.input_payload)
    packet_block_count = max(
        0,
        int(metadata.get("owned_block_count") or metadata.get("packet_block_count") or len(payload.get("b") or [])),
    )
    char_count = max(0, int(metadata.get("char_count") or 0))
    oversized = (
        packet_block_count > 1
        and (
            packet_block_count > _KNOWLEDGE_RETRY_MAX_CHUNKS_PER_SHARD
            or char_count > _KNOWLEDGE_RETRY_MAX_CHARS_PER_SHARD
        )
    )
    if not oversized:
        return {
            "oversized": False,
            "reason_code": None,
            "reason_detail": None,
            "packet_block_count": packet_block_count,
            "char_count": char_count,
        }
    return {
        "oversized": True,
        "reason_code": "watchdog_retry_oversized_skipped",
        "reason_detail": (
            "skipped monolithic strict JSON watchdog retry because the shard owns "
            "multiple packet blocks and exceeds the retry-safe size policy "
            f"(packet_block_count={packet_block_count}, char_count={char_count}, "
            f"limits={_KNOWLEDGE_RETRY_MAX_CHUNKS_PER_SHARD} blocks / "
            f"{_KNOWLEDGE_RETRY_MAX_CHARS_PER_SHARD} chars)"
        ),
        "packet_block_count": packet_block_count,
        "char_count": char_count,
    }


def _format_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _salvage_knowledge_json_object_suffix(
    response_text: str,
) -> tuple[str | None, dict[str, Any]]:
    cleaned_response_text = str(response_text or "").strip()
    if not cleaned_response_text.startswith("{"):
        return None, {}
    decoder = json.JSONDecoder()
    try:
        parsed_payload, end_index = decoder.raw_decode(cleaned_response_text)
    except json.JSONDecodeError:
        return None, {}
    if not isinstance(parsed_payload, dict):
        return None, {}
    trailing_text = cleaned_response_text[end_index:].strip()
    if not trailing_text or not _looks_like_salvageable_wrapper_noise(trailing_text):
        return None, {}
    return cleaned_response_text[:end_index], {
        "response_shell_wrapper_noise_trimmed": True,
        "response_shell_wrapper_noise_preview": trailing_text[:120],
    }


def _looks_like_salvageable_wrapper_noise(trailing_text: str) -> bool:
    cleaned = str(trailing_text or "").strip()
    if not cleaned:
        return False
    if "{" in cleaned or "[" in cleaned:
        return False
    wrapper_lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not wrapper_lines:
        return False
    return all(
        line == "EOF"
        or line.startswith(("EOF ", "$ ", "# ", "> ", "sh:", "bash:", "/bin/bash:", "done", "exit"))
        for line in wrapper_lines
    )


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


def _knowledge_failure_signature(
    *,
    proposal_status: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
    run_result: CodexExecRunResult | None = None,
) -> str:
    if proposal_status == "validated":
        return "validated"
    errors = {str(error).strip() for error in validation_errors if str(error).strip()}
    metadata = dict(validation_metadata or {})
    reason_code = str(
        ((run_result.supervision_reason_code) if run_result is not None else "") or ""
    ).strip()
    failure_classification = classify_knowledge_validation_failure(
        validation_errors=validation_errors,
        validation_metadata=metadata,
    )
    terminal_reason_code = str(metadata.get("terminal_reason_code") or "").strip()
    if terminal_reason_code == "packet_result_validation_blocked":
        return "validation_blocked"
    if terminal_reason_code == "repair_packet_exhausted":
        return "repair_exhausted"
    if proposal_status == "no_final_output" or "missing_output_file" in errors:
        return "no_final_output"
    if reason_code == "watchdog_command_execution_forbidden":
        return "watchdog_boundary"
    if reason_code == "watchdog_command_loop_without_output":
        return "watchdog_command_loop"
    if bool(failure_classification.get("snippet_copy_only")):
        return "snippet_copy_only"
    if "response_json_invalid" in errors or "response_not_json_object" in errors:
        return "invalid_json"
    if "schema_invalid" in errors:
        return "schema_invalid"
    if errors.intersection(
        {
            "missing_owned_block_decisions",
            "unexpected_block_decisions",
            "block_decision_order_mismatch",
            "knowledge_block_missing_group",
            "knowledge_block_group_conflict",
            "group_contains_other_block",
            "unknown_grounding_tag_key",
            "unknown_grounding_category_key",
            "invalid_proposed_tag_key",
            "invalid_proposed_tag_display_name",
            "proposed_tag_key_conflicts_existing",
            "idea_group_out_of_surface",
        }
    ):
        return "coverage_mismatch"
    return "invalid_output"


def _is_knowledge_near_miss(
    *,
    proposal_status: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
) -> bool:
    if proposal_status != "invalid":
        return False
    failure_classification = classify_knowledge_validation_failure(
        validation_errors=validation_errors,
        validation_metadata=validation_metadata,
    )
    return bool(failure_classification.get("repairable_near_miss"))


def _should_attempt_knowledge_snippet_repair(
    *,
    proposal_status: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
) -> bool:
    if proposal_status != "invalid":
        return False
    failure_classification = classify_knowledge_validation_failure(
        validation_errors=validation_errors,
        validation_metadata=validation_metadata,
    )
    return bool(failure_classification.get("snippet_only_repair"))


def _should_attempt_knowledge_watchdog_retry(
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


def _build_knowledge_watchdog_example(
    *,
    shard: ShardManifestEntryV1,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    block_decisions = payload.get("d")
    idea_groups = payload.get("g")
    if not isinstance(block_decisions, list) or not isinstance(idea_groups, list):
        return None
    return {
        "shard_id": shard.shard_id,
        "owned_ids": list(shard.owned_ids),
        "output": {
            "v": str(payload.get("v") or "3"),
            "bid": str(payload.get("bid") or shard.shard_id),
            "d": [
                dict(row_payload)
                for row_payload in block_decisions[:8]
                if isinstance(row_payload, Mapping)
            ],
            "g": [
                dict(row_payload)
                for row_payload in idea_groups[:3]
                if isinstance(row_payload, Mapping)
            ],
        },
    }


def _is_pathological_knowledge_response_text(
    response_text: str,
    *,
    owned_block_count: int,
    returned_decision_count: int,
) -> bool:
    cleaned = str(response_text or "")
    if not cleaned.strip():
        return False
    if re.search(rf"\s{{{_KNOWLEDGE_PATHOLOGICAL_WHITESPACE_RUN},}}", cleaned):
        return True
    effective_rows = max(1, int(returned_decision_count or 0))
    chars_per_row = len(cleaned) / effective_rows
    if (
        int(owned_block_count or 0) > effective_rows
        and chars_per_row >= _KNOWLEDGE_PATHOLOGICAL_CHARS_PER_RETURNED_ROW
    ):
        return True
    return False


def _should_retry_knowledge_shard_split(
    *,
    shard: ShardManifestEntryV1,
    proposal_status: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
    response_text: str | None,
) -> bool:
    if proposal_status != "invalid":
        return False
    owned_block_count = int(validation_metadata.get("owned_block_count") or 0)
    if owned_block_count <= 1:
        return False
    errors = {str(error) for error in validation_errors}
    if not errors.intersection(
        {
            "missing_owned_block_decisions",
            "unexpected_block_decisions",
            "response_json_invalid",
            "response_not_json_object",
        }
    ):
        return False
    returned_decision_count = int(validation_metadata.get("result_block_decision_count") or 0)
    if "missing_owned_block_decisions" in errors and returned_decision_count < owned_block_count:
        return True
    return _is_pathological_knowledge_response_text(
        str(response_text or ""),
        owned_block_count=max(1, owned_block_count),
        returned_decision_count=max(1, returned_decision_count),
    )


def _split_failed_knowledge_shard_for_retry(
    shard: ShardManifestEntryV1,
    *,
    max_retry_chunk_count: int,
    max_retry_chars: int,
) -> tuple[ShardManifestEntryV1, ...]:
    payload = _coerce_dict(shard.input_payload)
    blocks = [dict(block) for block in (payload.get("b") or []) if isinstance(block, Mapping)]
    if not blocks:
        return ()
    normalized_max_chunks = max(1, int(max_retry_chunk_count or 1))
    normalized_max_chars = max(1, int(max_retry_chars or 1))
    retry_shards: list[ShardManifestEntryV1] = []
    current_group: list[dict[str, Any]] = []
    current_group_chars = 0

    def _flush_group(group: list[dict[str, Any]]) -> None:
        if not group:
            return
        retry_index = len(retry_shards) + 1
        retry_shard_id = f"{shard.shard_id}.retry{retry_index:02d}"
        retry_payload: dict[str, Any] = {
            "v": str(payload.get("v") or "1"),
            "bid": retry_shard_id,
            "b": [dict(block) for block in group],
        }
        if "x" in payload:
            retry_payload["x"] = payload["x"]
        if "g" in payload:
            retry_payload["g"] = payload["g"]
        owned_ids = (retry_shard_id,)
        owned_block_indices = sorted(
            int(block.get("i"))
            for block in group
            if isinstance(block, Mapping) and block.get("i") is not None
        )
        char_count = sum(
            len(str(block.get("t") or ""))
            for block in group
            if isinstance(block, Mapping)
        )
        retry_shards.append(
            ShardManifestEntryV1(
                shard_id=retry_shard_id,
                owned_ids=owned_ids,
                evidence_refs=tuple(f"block:{index}" for index in owned_block_indices),
                input_payload=retry_payload,
                metadata={
                    **dict(shard.metadata or {}),
                    "ordered_packet_ids": list(owned_ids),
                    "owned_block_indices": list(owned_block_indices),
                    "packet_count": len(owned_ids),
                    "char_count": char_count,
                    "retry_parent_shard_id": shard.shard_id,
                    **_subset_knowledge_shard_metadata(
                        metadata=shard.metadata,
                        owned_ids=owned_ids,
                    ),
                },
            )
        )

    for block in blocks:
        block_char_count = len(str(block.get("t") or ""))
        if current_group and (
            len(current_group) >= normalized_max_chunks
            or current_group_chars + block_char_count > normalized_max_chars
        ):
            _flush_group(current_group)
            current_group = []
            current_group_chars = 0
        current_group.append(dict(block))
        current_group_chars += block_char_count
    _flush_group(current_group)
    return tuple(retry_shards)


def _subset_knowledge_shard_metadata(
    *,
    metadata: Mapping[str, Any] | None,
    owned_ids: Sequence[str],
) -> dict[str, Any]:
    source = dict(metadata or {})
    owned_id_set = {str(packet_id).strip() for packet_id in owned_ids if str(packet_id).strip()}
    subset: dict[str, Any] = {}
    for key in ("ordered_packet_ids", "source_span_ids", "context_blocks"):
        value = source.get(key)
        if value is None:
            continue
        subset[key] = value
    for key in ("packet_block_indices_by_id", "packet_char_count_by_id"):
        raw_mapping = source.get(key)
        if not isinstance(raw_mapping, Mapping):
            continue
        subset[key] = {
            str(packet_id): value
            for packet_id, value in raw_mapping.items()
            if str(packet_id).strip() in owned_id_set
        }
    return subset


def _should_attempt_knowledge_repair(
    *,
    proposal_status: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None = None,
) -> bool:
    if proposal_status != "invalid":
        return False
    failure_classification = classify_knowledge_validation_failure(
        validation_errors=validation_errors,
        validation_metadata=validation_metadata,
    )
    if bool(failure_classification.get("snippet_only_repair")):
        return False
    repairable_errors = {
        "response_json_invalid",
        "response_not_json_object",
        "schema_invalid",
        "missing_owned_block_decisions",
        "unexpected_block_decisions",
        "block_decision_order_mismatch",
        "knowledge_block_missing_group",
        "knowledge_block_group_conflict",
        "group_contains_other_block",
        "unknown_grounding_tag_key",
        "unknown_grounding_category_key",
        "invalid_proposed_tag_key",
        "invalid_proposed_tag_display_name",
        "proposed_tag_key_conflicts_existing",
    }
    return bool(set(validation_errors).intersection(repairable_errors))


def _run_knowledge_snippet_repair_attempt(
    *,
    runner: CodexExecRunner,
    worker_root: Path,
    shard: ShardManifestEntryV1,
    env: Mapping[str, str],
    output_schema_path: Path | None,
    model: str | None,
    reasoning_effort: str | None,
    original_response_text: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
    live_status_path: Path | None = None,
) -> CodexExecRunResult:
    prompt_text = _build_knowledge_snippet_repair_prompt(
        shard=shard,
        original_response_text=original_response_text,
        validation_errors=validation_errors,
        validation_metadata=validation_metadata,
    )
    (worker_root / "shards" / shard.shard_id / "snippet_repair_prompt.txt").write_text(
        prompt_text,
        encoding="utf-8",
    )
    return runner.run_structured_prompt(
        prompt_text=prompt_text,
        input_payload={
            "repair_mode": "knowledge_snippet_only",
            "bid": shard.shard_id,
            "shard_id": shard.shard_id,
            "owned_ids": list(shard.owned_ids),
            "validation_errors": list(validation_errors),
            "validation_metadata": dict(validation_metadata or {}),
            "authoritative_input": _coerce_dict(shard.input_payload),
            "previous_output": _truncate_for_repair(original_response_text),
        },
        working_dir=worker_root,
        env=env,
        output_schema_path=output_schema_path,
        model=model,
        reasoning_effort=reasoning_effort,
        workspace_task_label="knowledge snippet repair shard",
        supervision_callback=(
            _build_strict_json_watchdog_callback(live_status_path=live_status_path)
            if live_status_path is not None
            else None
        ),
    )


def _run_knowledge_repair_attempt(
    *,
    runner: CodexExecRunner,
    worker_root: Path,
    shard: ShardManifestEntryV1,
    env: Mapping[str, str],
    output_schema_path: Path | None,
    model: str | None,
    reasoning_effort: str | None,
    original_response_text: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
    live_status_path: Path | None = None,
) -> CodexExecRunResult:
    prompt_text = _build_knowledge_repair_prompt(
        shard=shard,
        original_response_text=original_response_text,
        validation_errors=validation_errors,
        validation_metadata=validation_metadata,
    )
    (worker_root / "shards" / shard.shard_id / "repair_prompt.txt").write_text(
        prompt_text,
        encoding="utf-8",
    )
    return runner.run_structured_prompt(
        prompt_text=prompt_text,
        input_payload={
            "repair_mode": "knowledge",
            "bid": shard.shard_id,
            "shard_id": shard.shard_id,
            "owned_ids": list(shard.owned_ids),
            "validation_errors": list(validation_errors),
            "validation_metadata": dict(validation_metadata or {}),
            "authoritative_input": _coerce_dict(shard.input_payload),
            "previous_output": _truncate_for_repair(original_response_text),
        },
        working_dir=worker_root,
        env=env,
        output_schema_path=output_schema_path,
        model=model,
        reasoning_effort=reasoning_effort,
        workspace_task_label="knowledge repair shard",
        supervision_callback=(
            _build_strict_json_watchdog_callback(live_status_path=live_status_path)
            if live_status_path is not None
            else None
        ),
    )


def _run_knowledge_watchdog_retry_attempt(
    *,
    runner: CodexExecRunner,
    worker_root: Path,
    shard: ShardManifestEntryV1,
    env: Mapping[str, str],
    output_schema_path: Path | None,
    model: str | None,
    reasoning_effort: str | None,
    reason_code: str,
    reason_detail: str,
    successful_examples: Sequence[Mapping[str, Any]],
    live_status_path: Path | None = None,
) -> CodexExecRunResult:
    prompt_text = _build_knowledge_watchdog_retry_prompt(
        shard=shard,
        reason_code=reason_code,
        reason_detail=reason_detail,
        successful_examples=successful_examples,
    )
    retry_root = worker_root / "shards" / shard.shard_id / "watchdog_retry"
    retry_root.mkdir(parents=True, exist_ok=True)
    (retry_root / "prompt.txt").write_text(prompt_text, encoding="utf-8")
    return runner.run_structured_prompt(
        prompt_text=prompt_text,
        input_payload={
            "retry_mode": "knowledge_watchdog",
            "bid": shard.shard_id,
            "shard_id": shard.shard_id,
            "owned_ids": list(shard.owned_ids),
            "retry_reason": {
                "code": reason_code,
                "detail": reason_detail,
            },
            "successful_examples": [dict(example_payload) for example_payload in successful_examples],
            "authoritative_input": _coerce_dict(shard.input_payload),
        },
        working_dir=worker_root,
        env=env,
        output_schema_path=output_schema_path,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=_KNOWLEDGE_WATCHDOG_RETRY_TIMEOUT_SECONDS,
        workspace_task_label="knowledge watchdog retry shard",
        supervision_callback=(
            _build_strict_json_watchdog_callback(
                live_status_path=live_status_path,
                silence_timeout_seconds=_KNOWLEDGE_WATCHDOG_RETRY_SILENCE_TIMEOUT_SECONDS,
            )
            if live_status_path is not None
            else None
        ),
    )


def _build_knowledge_watchdog_retry_prompt(
    *,
    shard: ShardManifestEntryV1,
    reason_code: str,
    reason_detail: str,
    successful_examples: Sequence[Mapping[str, Any]],
) -> str:
    owned_ids = ", ".join(str(packet_id) for packet_id in shard.owned_ids)
    example_rows = [
        json.dumps(dict(example_payload), ensure_ascii=False, sort_keys=True)
        for example_payload in successful_examples[:_KNOWLEDGE_COHORT_WATCHDOG_MAX_EXAMPLES]
        if isinstance(example_payload, Mapping)
    ]
    examples_block = (
        "\n".join(example_rows)
        if example_rows
        else "[no sibling examples available]"
    )
    authoritative_input = json.dumps(
        _coerce_dict(shard.input_payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        "Retry the strict JSON knowledge shard after the previous attempt was stopped.\n\n"
        "Rules:\n"
        "- Return JSON only.\n"
        "- Return compact minified JSON on a single line.\n"
        "- Do not run shell commands, Python, or any other tools.\n"
        "- The first emitted character must be `{`.\n"
        f"- `bid` must be `{shard.shard_id}`.\n"
        "- Return one packet result covering the owned block surface exactly once.\n"
        f"- Owned packet ids: {owned_ids}\n"
        "- Preserve packet-local evidence and do not invent synthetic ids.\n\n"
        f"Previous stop reason: {reason_code or '[unknown]'}\n"
        f"Reason detail: {reason_detail or '[none recorded]'}\n\n"
        "Successful sibling examples:\n"
        "<BEGIN_SUCCESSFUL_SIBLING_EXAMPLES>\n"
        f"{examples_block}\n"
        "<END_SUCCESSFUL_SIBLING_EXAMPLES>\n\n"
        "Authoritative shard input:\n"
        "<BEGIN_INPUT_JSON>\n"
        f"{authoritative_input}\n"
        "<END_INPUT_JSON>\n"
    )


def _build_knowledge_repair_prompt(
    *,
    shard: ShardManifestEntryV1,
    original_response_text: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
) -> str:
    owned_ids = ", ".join(str(packet_id) for packet_id in shard.owned_ids)
    missing_indices = ", ".join(
        str(block_index)
        for block_index in (validation_metadata.get("missing_owned_block_indices") or [])
    )
    authoritative_input = json.dumps(
        _coerce_dict(shard.input_payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        "Repair the invalid knowledge shard output.\n\n"
        "Rules:\n"
        "- Return JSON only.\n"
        "- Return compact minified JSON on a single line.\n"
        "- Do not run shell commands, Python, or any other tools.\n"
        "- The first emitted character must be `{`.\n"
        f"- `bid` must be `{shard.shard_id}`.\n"
        "- Return one packet result covering the owned block surface exactly once.\n"
        f"- Owned packet ids: {owned_ids}\n"
        "- Preserve packet-local evidence and do not invent synthetic ids.\n\n"
        f"Validator errors: {json.dumps(list(validation_errors), sort_keys=True)}\n\n"
        f"Missing owned block indices: {missing_indices or '[none recorded]'}\n\n"
        "Authoritative shard input:\n"
        "<BEGIN_INPUT_JSON>\n"
        f"{authoritative_input}\n"
        "<END_INPUT_JSON>\n\n"
        "Previous invalid output:\n"
        "<BEGIN_PREVIOUS_OUTPUT>\n"
        f"{_truncate_for_repair(original_response_text)}\n"
        "<END_PREVIOUS_OUTPUT>\n"
    )


def _build_knowledge_snippet_repair_prompt(
    *,
    shard: ShardManifestEntryV1,
    original_response_text: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
) -> str:
    owned_ids = ", ".join(str(packet_id) for packet_id in shard.owned_ids)
    echoed_group_ids = ", ".join(
        str(group_id)
        for group_id in (
            validation_metadata.get("echoed_idea_group_ids")
            or validation_metadata.get("copied_quote_idea_group_ids")
            or []
        )
    )
    authoritative_input = json.dumps(
        _coerce_dict(shard.input_payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        "Repair the invalid knowledge shard output by rewriting snippet bodies only.\n\n"
        "Rules:\n"
        "- Return JSON only.\n"
        "- Return compact minified JSON on a single line.\n"
        "- Do not run shell commands, Python, or any other tools.\n"
        "- The first emitted character must be `{`.\n"
        f"- `bid` must be `{shard.shard_id}`.\n"
        "- Return one packet result covering the owned block surface exactly once.\n"
        f"- Owned packet ids: {owned_ids}\n"
        "- Preserve every existing `block_decisions`, `idea_groups[*].block_indices`, and evidence pointer.\n"
        "- Rewrite only `idea_groups[*].snippets[*].body`.\n"
        "- Each rewritten snippet body must be a short grounded extraction, not copied evidence prose.\n"
        "- Do not add new snippets, drop snippets, or change evidence quotes.\n\n"
        f"Validator errors: {json.dumps(list(validation_errors), sort_keys=True)}\n\n"
        f"Copied-snippet idea group ids: {echoed_group_ids or '[none recorded]'}\n\n"
        "Authoritative shard input:\n"
        "<BEGIN_INPUT_JSON>\n"
        f"{authoritative_input}\n"
        "<END_INPUT_JSON>\n\n"
        "Previous invalid output:\n"
        "<BEGIN_PREVIOUS_OUTPUT>\n"
        f"{_truncate_for_repair(original_response_text)}\n"
        "<END_PREVIOUS_OUTPUT>\n"
    )


def _truncate_for_repair(text: str, *, max_chars: int = 20_000) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 15].rstrip() + "\n...[truncated]"
