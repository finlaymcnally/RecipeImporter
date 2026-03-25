from __future__ import annotations

from . import _shared as _shared_module
from . import planning as _planning_module
from . import recovery as _recovery_module

for _module in (_shared_module, _planning_module, _recovery_module):
    globals().update(
        {
            name: value
            for name, value in vars(_module).items()
            if not name.startswith("__")
        }
    )


@dataclass(frozen=True, slots=True)
class _KnowledgeWorkspacePreparationResult:
    runnable_shards: tuple[ShardManifestEntryV1, ...]
    runnable_tasks: tuple[_KnowledgeTaskPlan, ...]
    worker_failure_count: int
    worker_proposal_count: int
    worker_failures: tuple[dict[str, Any], ...]
    worker_proposals: tuple[ShardProposalV1, ...]


@dataclass(frozen=True, slots=True)
class _KnowledgeWorkspaceSessionResult:
    run_result: CodexExecRunResult
    worker_runner_results: tuple[dict[str, Any], ...]
    stage_rows: tuple[dict[str, Any], ...]
    relaunch_status_metadata: dict[str, Any]
    workspace_task_entries: tuple[TaskManifestEntryV1, ...]


def _render_events_jsonl(events: tuple[dict[str, Any], ...]) -> str:
    if not events:
        return ""
    return "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)


def _prepare_taskized_workspace_assignment(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: Mapping[str, str],
    assigned_shards: Sequence[ShardManifestEntryV1],
    task_plans_by_shard_id: Mapping[str, tuple[_KnowledgeTaskPlan, ...]],
    shard_dir: Path,
    worker_root: Path,
    output_schema_path: Path | None,
    progress_state: _KnowledgePhaseProgressState | None,
    task_status_tracker: _KnowledgeTaskStatusTracker | None,
    shard_completed_callback: Callable[..., None] | None,
) -> _KnowledgeWorkspacePreparationResult:
    worker_failure_count = 0
    worker_proposal_count = 0
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    runnable_shards: list[ShardManifestEntryV1] = []
    runnable_tasks: list[_KnowledgeTaskPlan] = []

    for shard in assigned_shards:
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
        preflight_failure = _preflight_knowledge_shard(shard)
        if preflight_failure is None:
            task_plans = task_plans_by_shard_id.get(shard.shard_id, ())
            if task_plans:
                runnable_shards.append(shard)
                runnable_tasks.extend(task_plans)
            continue
        preflight_result = _build_preflight_rejected_run_result(
            prompt_text="knowledge worker preflight rejected",
            output_schema_path=output_schema_path,
            working_dir=worker_root,
            reason_code=str(preflight_failure.get("reason_code") or "preflight_rejected"),
            reason_detail=str(
                preflight_failure.get("reason_detail") or "knowledge shard failed preflight"
            ),
        )
        _write_live_status(
            shard_root / "live_status.json",
            {
                "state": "preflight_rejected",
                "reason_code": preflight_result.supervision_reason_code,
                "reason_detail": preflight_result.supervision_reason_detail,
                "retryable": preflight_result.supervision_retryable,
                "watchdog_policy": "workspace_worker_v1",
                "elapsed_seconds": 0.0,
                "last_event_seconds_ago": None,
                "command_execution_count": 0,
                "reasoning_item_count": 0,
            },
        )
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        _write_json(
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
                "retry_attempted": False,
                "retry_status": "not_attempted",
                "retry_child_shard_ids": [],
                "repair_attempted": False,
                "repair_status": "not_attempted",
            },
            proposal_path,
        )
        _write_json(
            {
                "status": "missing_output",
                "validation_errors": [
                    str(preflight_failure.get("reason_code") or "preflight_rejected")
                ],
                "validation_metadata": {},
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "watchdog_retry_attempted": False,
                "watchdog_retry_status": "not_attempted",
                "retry_attempted": False,
                "retry_status": "not_attempted",
                "retry_child_shard_ids": [],
                "repair_attempted": False,
                "repair_status": "not_attempted",
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
                "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                "retryable": False,
            },
            shard_root / "status.json",
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
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
            }
        )
        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status="missing_output",
                proposal_path=_relative_path(run_root, proposal_path),
                payload=None,
                validation_errors=(
                    str(preflight_failure.get("reason_code") or "preflight_rejected"),
                ),
                metadata={
                    "watchdog_retry_attempted": False,
                    "watchdog_retry_status": "not_attempted",
                    "retry_attempted": False,
                    "retry_status": "not_attempted",
                    "repair_attempted": False,
                    "repair_status": "not_attempted",
                },
            )
        )
        if task_status_tracker is not None:
            for task_id in _progress_task_ids_for_knowledge_shard(
                shard_id=shard.shard_id,
                task_plans_by_shard_id=task_plans_by_shard_id,
            ):
                task_status_tracker.mark_terminal(
                    task_id=task_id,
                    worker_id=assignment.worker_id,
                    terminal_state="preflight_rejected",
                    attempt_type="preflight",
                    proposal_status="missing_output",
                    validation_errors=(
                        str(preflight_failure.get("reason_code") or "preflight_rejected"),
                    ),
                    metadata={
                        "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                    },
                )
        if progress_state is not None:
            progress_state.mark_task_packets_terminal(
                worker_id=assignment.worker_id,
                task_ids=_progress_task_ids_for_knowledge_shard(
                    shard_id=shard.shard_id,
                    task_plans_by_shard_id=task_plans_by_shard_id,
                ),
            )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    return _KnowledgeWorkspacePreparationResult(
        runnable_shards=tuple(runnable_shards),
        runnable_tasks=tuple(runnable_tasks),
        worker_failure_count=worker_failure_count,
        worker_proposal_count=worker_proposal_count,
        worker_failures=tuple(worker_failures),
        worker_proposals=tuple(worker_proposals),
    )


def _run_taskized_workspace_session(
    *,
    assignment: WorkerAssignmentV1,
    runnable_shards: Sequence[ShardManifestEntryV1],
    runnable_tasks: Sequence[_KnowledgeTaskPlan],
    worker_root: Path,
    in_dir: Path,
    hints_dir: Path,
    shard_dir: Path,
    out_dir: Path,
    runner: CodexExecRunner,
    pipeline_id: str,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState,
    progress_state: _KnowledgePhaseProgressState | None,
    task_status_tracker: _KnowledgeTaskStatusTracker | None,
    interruption_requested: threading.Event | None,
) -> _KnowledgeWorkspaceSessionResult | None:
    if not runnable_shards or not runnable_tasks:
        return None

    workspace_task_entries = _build_knowledge_workspace_task_runtime_entries(runnable_tasks)
    inventory_task_rows = [
        build_workspace_inventory_task_row(asdict(task_entry))
        for task_entry in workspace_task_entries
    ]
    _write_json(inventory_task_rows, worker_root / "assigned_tasks.json")
    (worker_root / _KNOWLEDGE_SCRATCH_DIR_NAME).mkdir(parents=True, exist_ok=True)
    write_knowledge_workspace_sidecars(
        worker_root=worker_root,
        tasks=[asdict(task_entry) for task_entry in workspace_task_entries],
    )
    for task in runnable_tasks:
        task_manifest = task.manifest_entry
        _write_worker_input(
            in_dir / f"{task_manifest.shard_id}.json",
            payload=task_manifest.input_payload,
            input_text=task_manifest.input_text,
        )
        _write_knowledge_worker_hint(
            path=hints_dir / f"{task_manifest.shard_id}.md",
            shard=task_manifest,
        )

    task_queue_controller = _KnowledgeWorkspaceTaskQueueController(
        worker_root=worker_root,
        task_entries=tuple(workspace_task_entries),
        worker_id=assignment.worker_id,
        task_status_tracker=task_status_tracker,
    )
    worker_prompt_text = _build_knowledge_workspace_worker_prompt(tasks=workspace_task_entries)
    worker_prompt_path = worker_root / "prompt.txt"
    worker_prompt_path.write_text(worker_prompt_text, encoding="utf-8")
    worker_live_status_path = worker_root / "live_status.json"
    shard_live_status_paths = [
        shard_dir / shard.shard_id / "live_status.json" for shard in runnable_shards
    ]
    for shard in runnable_shards:
        (shard_dir / shard.shard_id / "prompt.txt").write_text(worker_prompt_text, encoding="utf-8")
    if task_status_tracker is not None:
        for task_entry in workspace_task_entries:
            task_metadata = dict(task_entry.metadata or {})
            task_status_tracker.start_attempt(
                task_id=task_entry.task_id,
                worker_id=assignment.worker_id,
                attempt_type="main_worker",
                metadata={
                    "lease_sequence": int(task_metadata.get("lease_sequence") or 0),
                    "lease_total": int(
                        task_metadata.get("lease_total") or len(workspace_task_entries)
                    ),
                    "input_path": task_metadata.get("input_path"),
                    "hint_path": task_metadata.get("hint_path"),
                    "result_path": task_metadata.get("result_path"),
                    "workspace_processing_contract": task_metadata.get(
                        "workspace_processing_contract"
                    ),
                },
            )

    workspace_session_results: list[CodexExecRunResult] = []
    workspace_relaunch_count = 0
    workspace_relaunch_history: list[dict[str, Any]] = []
    cap_reached_payload: dict[str, Any] | None = None
    while True:
        current_task_id_before_run = task_queue_controller.current_task_id()
        validated_task_count_before_run = task_queue_controller.validated_task_count
        session_result = runner.run_workspace_worker(
            prompt_text=worker_prompt_text,
            working_dir=worker_root,
            env=env,
            model=model,
            reasoning_effort=reasoning_effort,
            workspace_task_label="knowledge worker session",
            supervision_callback=_build_strict_json_watchdog_callback(
                live_status_path=worker_live_status_path,
                live_status_paths=shard_live_status_paths,
                cohort_watchdog_state=cohort_watchdog_state,
                watchdog_policy="workspace_worker_v1",
                allow_workspace_commands=True,
                execution_workspace_root=worker_root,
                forbid_inline_python_heredocs=False,
                expected_workspace_output_paths=[
                    out_dir / f"{task.task_id}.json" for task in runnable_tasks
                ],
                task_queue_controller=task_queue_controller,
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
        workspace_session_results.append(session_result)
        relaunch_payload = _detect_knowledge_workspace_premature_clean_exit(
            run_result=session_result,
            task_queue_controller=task_queue_controller,
            current_task_id_before_run=current_task_id_before_run,
            validated_task_count_before_run=validated_task_count_before_run,
        )
        if relaunch_payload is None:
            break
        if workspace_relaunch_count >= _KNOWLEDGE_WORKSPACE_PREMATURE_EXIT_MAX_RELAUNCHES:
            cap_reached_payload = _build_knowledge_workspace_relaunch_cap_reached_payload(
                premature_clean_exit_payload=relaunch_payload,
                task_queue_controller=task_queue_controller,
            )
            break
        workspace_relaunch_count += 1
        workspace_relaunch_history.append(
            _knowledge_workspace_relaunch_history_entry(relaunch_payload)
        )
        relaunch_status_metadata = _knowledge_workspace_relaunch_metadata(
            workspace_relaunch_history,
        )
        _write_live_status(
            worker_live_status_path,
            {
                **relaunch_payload,
                **relaunch_status_metadata,
            },
        )
        for live_status_path in shard_live_status_paths:
            _write_live_status(
                live_status_path,
                {
                    **relaunch_payload,
                    **relaunch_status_metadata,
                },
            )
    run_result = _combine_workspace_worker_run_results(workspace_session_results)
    _finalize_live_status(
        worker_live_status_path,
        run_result=run_result,
        watchdog_policy="workspace_worker_v1",
    )
    for live_status_path in shard_live_status_paths:
        _finalize_live_status(
            live_status_path,
            run_result=run_result,
            watchdog_policy="workspace_worker_v1",
        )
    relaunch_status_metadata = _knowledge_workspace_relaunch_metadata(
        workspace_relaunch_history,
        cap_reached=cap_reached_payload is not None,
    )
    if relaunch_status_metadata["workspace_relaunch_count"] > 0:
        _merge_live_status_metadata(
            worker_live_status_path,
            payload=relaunch_status_metadata,
        )
        for live_status_path in shard_live_status_paths:
            _merge_live_status_metadata(
                live_status_path,
                payload=relaunch_status_metadata,
            )
    if str(run_result.supervision_state or "completed").strip() == "completed" and task_queue_controller.is_complete():
        completed_payload = {
            "state": "completed",
            "reason_code": "workspace_validated_task_queue_completed",
            "reason_detail": (
                "knowledge workspace worker produced repo-validated outputs for "
                "every assigned current task"
            ),
            "retryable": False,
            "watchdog_policy": "workspace_worker_v1",
            "workspace_relaunch_count": workspace_relaunch_count,
            **relaunch_status_metadata,
            **task_queue_controller.status_payload(),
        }
        _write_live_status(worker_live_status_path, completed_payload)
        for live_status_path in shard_live_status_paths:
            _write_live_status(live_status_path, completed_payload)
    elif (
        str(run_result.supervision_state or "completed").strip() == "completed"
        and cap_reached_payload is not None
    ):
        capped_payload = {
            **cap_reached_payload,
            **relaunch_status_metadata,
            **task_queue_controller.status_payload(),
        }
        _write_live_status(worker_live_status_path, capped_payload)
        for live_status_path in shard_live_status_paths:
            _write_live_status(live_status_path, capped_payload)
    elif str(run_result.supervision_state or "completed").strip() == "completed":
        incomplete_payload = {
            "state": "completed_with_failures",
            "reason_code": "workspace_validated_task_queue_incomplete",
            "reason_detail": (
                "knowledge workspace worker exited before every current task "
                "was individually validated by the repo-owned checker"
            ),
            "retryable": True,
            "watchdog_policy": "workspace_worker_v1",
            "workspace_relaunch_count": workspace_relaunch_count,
            **relaunch_status_metadata,
            **task_queue_controller.status_payload(),
        }
        _write_live_status(worker_live_status_path, incomplete_payload)
        for live_status_path in shard_live_status_paths:
            _write_live_status(live_status_path, incomplete_payload)
    (worker_root / "events.jsonl").write_text(
        _render_events_jsonl(run_result.events),
        encoding="utf-8",
    )
    _write_json({"text": run_result.response_text}, worker_root / "last_message.json")
    _write_json(dict(run_result.usage or {}), worker_root / "usage.json")
    _write_json(run_result.workspace_manifest(), worker_root / "workspace_manifest.json")
    _write_optional_text(worker_root / "stdout.txt", run_result.stdout_text)
    _write_optional_text(worker_root / "stderr.txt", run_result.stderr_text)
    if task_status_tracker is not None:
        for task_entry in workspace_task_entries:
            task_metadata = dict(task_entry.metadata or {})
            result_path = str(task_metadata.get("result_path") or "").strip()
            if not result_path:
                continue
            output_path = worker_root / result_path
            if output_path.exists():
                task_status_tracker.mark_main_output_written(
                    task_id=task_entry.task_id,
                    metadata={
                        "leased_packet_result_path": result_path,
                    },
                )
    return _KnowledgeWorkspaceSessionResult(
        run_result=run_result,
        worker_runner_results=(),
        stage_rows=(),
        relaunch_status_metadata=relaunch_status_metadata,
        workspace_task_entries=tuple(workspace_task_entries),
    )


def _finalize_taskized_workspace_assignment(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: Mapping[str, str],
    runnable_shards: Sequence[ShardManifestEntryV1],
    runnable_tasks: Sequence[_KnowledgeTaskPlan],
    task_plans_by_shard_id: Mapping[str, tuple[_KnowledgeTaskPlan, ...]],
    worker_root: Path,
    in_dir: Path,
    out_dir: Path,
    shard_dir: Path,
    runner: CodexExecRunner,
    pipeline_id: str,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    run_result: CodexExecRunResult,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState,
    recovery_governor: _KnowledgeRecoveryGovernor,
    shard_completed_callback: Callable[..., None] | None,
    progress_state: _KnowledgePhaseProgressState | None,
    task_status_tracker: _KnowledgeTaskStatusTracker | None,
    interruption_requested: threading.Event | None,
    worker_failure_count: int,
    worker_proposal_count: int,
    worker_failures: list[dict[str, Any]],
    worker_proposals: list[ShardProposalV1],
    worker_runner_results: list[dict[str, Any]],
    stage_rows: list[dict[str, Any]],
) -> tuple[int, int]:
    task_count = len(runnable_tasks)
    worker_prompt_path = worker_root / "prompt.txt"
    task_payloads_by_shard_id: dict[str, dict[str, dict[str, Any]]] = {}
    task_validation_errors_by_shard_id: dict[str, dict[str, tuple[str, ...]]] = {}
    task_watchdog_retry_status_by_shard_id: dict[str, dict[str, str]] = {}
    task_watchdog_retry_skip_reason_by_shard_id: dict[str, dict[str, str]] = {}
    task_repair_status_by_shard_id: dict[str, dict[str, str]] = {}
    task_repair_mode_by_shard_id: dict[str, dict[str, str]] = {}
    task_repair_skip_reason_by_shard_id: dict[str, dict[str, str]] = {}
    task_repair_validation_errors_by_shard_id: dict[str, dict[str, tuple[str, ...]]] = {}
    for task_index, task in enumerate(runnable_tasks):
        task_manifest = task.manifest_entry
        parent_shard_id = task.parent_shard_id
        task_root = shard_dir / task_manifest.shard_id
        task_root.mkdir(parents=True, exist_ok=True)
        input_path = in_dir / f"{task_manifest.shard_id}.json"
        output_path = out_dir / f"{task_manifest.shard_id}.json"
        response_text = output_path.read_text(encoding="utf-8") if output_path.exists() else None
        runner_payload = _build_knowledge_workspace_task_runner_payload(
            pipeline_id=pipeline_id,
            worker_id=assignment.worker_id,
            shard_id=parent_shard_id,
            runtime_task_id=task_manifest.shard_id,
            run_result=run_result,
            model=model,
            reasoning_effort=reasoning_effort,
            request_input_file=input_path,
            worker_prompt_path=worker_prompt_path,
            task_count=task_count,
            task_index=task_index,
        )
        worker_runner_results.append(dict(runner_payload))
        telemetry = runner_payload.get("telemetry")
        row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
        if isinstance(row_payloads, list):
            for row_payload in row_payloads:
                if isinstance(row_payload, dict):
                    stage_rows.append(dict(row_payload))
        primary_row = stage_rows[-1] if stage_rows else None
        primary_runner_row = (
            row_payloads[0]
            if isinstance(row_payloads, list)
            and row_payloads
            and isinstance(row_payloads[0], dict)
            else None
        )
        if interruption_requested is not None and interruption_requested.is_set():
            break
        payload, validation_errors, validation_metadata, proposal_status = _evaluate_knowledge_response(
            shard=task_manifest,
            response_text=response_text,
        )
        initial_proposal_status = proposal_status
        active_response_text = response_text
        main_failure_signature = _knowledge_failure_signature(
            proposal_status=proposal_status,
            validation_errors=validation_errors,
            validation_metadata=validation_metadata,
            run_result=run_result,
        )
        if proposal_status != "validated":
            poisoned_worker_reason = recovery_governor.observe_main_failure(
                worker_id=assignment.worker_id,
                failure_signature=main_failure_signature,
            )
            if poisoned_worker_reason is not None:
                validation_metadata = {
                    **dict(validation_metadata or {}),
                    "poisoned_worker_reason_code": poisoned_worker_reason["reason_code"],
                    "poisoned_worker_reason_detail": poisoned_worker_reason["reason_detail"],
                }
        watchdog_retry_attempted = False
        watchdog_retry_status = "not_attempted"
        watchdog_retry_skip_reason_code: str | None = None
        watchdog_retry_skip_reason_detail: str | None = None
        if (
            (interruption_requested is None or not interruption_requested.is_set())
            and _should_attempt_knowledge_watchdog_retry(run_result=run_result)
        ):
            retry_followup_decision = recovery_governor.allow_followup(
                kind="retry",
                worker_id=assignment.worker_id,
                failure_signature=main_failure_signature,
            )
            if not retry_followup_decision.allowed:
                watchdog_retry_status = "skipped"
                watchdog_retry_skip_reason_code = retry_followup_decision.reason_code
                watchdog_retry_skip_reason_detail = retry_followup_decision.reason_detail
                validation_metadata = {
                    **dict(validation_metadata or {}),
                    "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                    "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                }
            else:
                watchdog_retry_attempted = True
                if progress_state is not None:
                    progress_state.begin_followup(
                        worker_id=assignment.worker_id,
                        label=_format_knowledge_followup_label(
                            parent_shard_id=parent_shard_id,
                            attempt_label="watchdog retry",
                            task_id=task_manifest.shard_id,
                        ),
                        followup_kind="retry",
                    )
                if task_status_tracker is not None:
                    task_status_tracker.start_attempt(
                        task_id=task_manifest.shard_id,
                        worker_id=assignment.worker_id,
                        attempt_type="watchdog_retry",
                    )
                try:
                    watchdog_retry_run_result = _run_knowledge_watchdog_retry_attempt(
                        runner=runner,
                        worker_root=worker_root,
                        shard=task_manifest,
                        env=env,
                        output_schema_path=output_schema_path,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        reason_code=str(run_result.supervision_reason_code or ""),
                        reason_detail=str(run_result.supervision_reason_detail or ""),
                        successful_examples=cohort_watchdog_state.snapshot().get("successful_examples") or [],
                        live_status_path=task_root / "watchdog_retry" / "live_status.json",
                    )
                finally:
                    if progress_state is not None:
                        progress_state.end_followup(
                            worker_id=assignment.worker_id,
                            followup_kind="retry",
                        )
                retry_root = task_root / "watchdog_retry"
                _finalize_live_status(
                    retry_root / "live_status.json",
                    run_result=watchdog_retry_run_result,
                )
                retry_payload_wrapper = _build_knowledge_inline_attempt_runner_payload(
                    pipeline_id=pipeline_id,
                    worker_id=assignment.worker_id,
                    shard_id=parent_shard_id,
                    run_result=watchdog_retry_run_result,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    prompt_input_mode="inline_watchdog_retry",
                )
                retry_payload_wrapper["process_payload"]["runtime_task_id"] = task_manifest.shard_id
                retry_payload_wrapper["process_payload"]["runtime_parent_shard_id"] = parent_shard_id
                worker_runner_results.append(dict(retry_payload_wrapper))
                retry_rows = (
                    retry_payload_wrapper.get("telemetry", {}).get("rows")
                    if isinstance(retry_payload_wrapper.get("telemetry"), dict)
                    else None
                )
                if isinstance(retry_rows, list):
                    for row_payload in retry_rows:
                        if not isinstance(row_payload, dict):
                            continue
                        row_payload["watchdog_retry_attempted"] = True
                        row_payload["runtime_task_id"] = task_manifest.shard_id
                        row_payload["runtime_parent_shard_id"] = parent_shard_id
                        stage_rows.append(dict(row_payload))
                (retry_root / "events.jsonl").write_text(
                    _render_events_jsonl(watchdog_retry_run_result.events),
                    encoding="utf-8",
                )
                _write_json({"text": watchdog_retry_run_result.response_text}, retry_root / "last_message.json")
                _write_json(dict(watchdog_retry_run_result.usage or {}), retry_root / "usage.json")
                _write_json(watchdog_retry_run_result.workspace_manifest(), retry_root / "workspace_manifest.json")
                payload, validation_errors, validation_metadata, proposal_status = _evaluate_knowledge_response(
                    shard=task_manifest,
                    response_text=watchdog_retry_run_result.response_text,
                )
                watchdog_retry_status = "recovered" if proposal_status == "validated" else "failed"
                recovery_governor.record_followup_outcome(
                    kind="retry",
                    failure_signature=main_failure_signature,
                    recovered=proposal_status == "validated",
                )
                _write_json(
                    {
                        "status": proposal_status,
                        "watchdog_retry_reason_code": run_result.supervision_reason_code,
                        "validation_errors": list(validation_errors),
                        "validation_metadata": dict(validation_metadata or {}),
                    },
                    retry_root / "status.json",
                )
                active_response_text = watchdog_retry_run_result.response_text
                task_watchdog_retry_status_by_shard_id.setdefault(parent_shard_id, {})[
                    task_manifest.shard_id
                ] = watchdog_retry_status
            if watchdog_retry_skip_reason_code:
                task_watchdog_retry_skip_reason_by_shard_id.setdefault(parent_shard_id, {})[
                    task_manifest.shard_id
                ] = watchdog_retry_skip_reason_code

        repair_attempted = False
        repair_status = "not_attempted"
        repair_mode: str | None = None
        repair_skip_reason_code: str | None = None
        repair_skip_reason_detail: str | None = None
        if (
            (interruption_requested is None or not interruption_requested.is_set())
            and proposal_status == "invalid"
        ):
            snippet_repair_applicable = _should_attempt_knowledge_snippet_repair(
                proposal_status=proposal_status,
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
            )
            current_failure_signature = _knowledge_failure_signature(
                proposal_status=proposal_status,
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
                run_result=run_result,
            )
            repair_followup_decision = recovery_governor.allow_followup(
                kind="repair",
                worker_id=assignment.worker_id,
                failure_signature=current_failure_signature,
                near_miss=_is_knowledge_near_miss(
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                ),
            )
            if not repair_followup_decision.allowed:
                repair_status = "skipped"
                repair_skip_reason_code = repair_followup_decision.reason_code
                repair_skip_reason_detail = repair_followup_decision.reason_detail
                validation_metadata = {
                    **dict(validation_metadata or {}),
                    "repair_skip_reason_code": repair_skip_reason_code,
                    "repair_skip_reason_detail": repair_skip_reason_detail,
                }
            else:
                repair_attempted = True
                repair_mode = "snippet_only" if snippet_repair_applicable else "general"
                if progress_state is not None:
                    progress_state.begin_followup(
                        worker_id=assignment.worker_id,
                        label=_format_knowledge_followup_label(
                            parent_shard_id=parent_shard_id,
                            attempt_label="repair",
                            task_id=task_manifest.shard_id,
                        ),
                        followup_kind="repair",
                    )
                if task_status_tracker is not None:
                    task_status_tracker.start_attempt(
                        task_id=task_manifest.shard_id,
                        worker_id=assignment.worker_id,
                        attempt_type="repair",
                    )
                try:
                    if snippet_repair_applicable:
                        repair_run_result = _run_knowledge_snippet_repair_attempt(
                            runner=runner,
                            worker_root=worker_root,
                            shard=task_manifest,
                            env=env,
                            output_schema_path=output_schema_path,
                            model=model,
                            reasoning_effort=reasoning_effort,
                            original_response_text=active_response_text,
                            validation_errors=validation_errors,
                            validation_metadata=validation_metadata,
                            live_status_path=task_root / "repair_live_status.json",
                        )
                    else:
                        repair_run_result = _run_knowledge_repair_attempt(
                            runner=runner,
                            worker_root=worker_root,
                            shard=task_manifest,
                            env=env,
                            output_schema_path=output_schema_path,
                            model=model,
                            reasoning_effort=reasoning_effort,
                            original_response_text=active_response_text,
                            validation_errors=validation_errors,
                            validation_metadata=validation_metadata,
                            live_status_path=task_root / "repair_live_status.json",
                        )
                finally:
                    if progress_state is not None:
                        progress_state.end_followup(
                            worker_id=assignment.worker_id,
                            followup_kind="repair",
                        )
                _finalize_live_status(
                    task_root / "repair_live_status.json",
                    run_result=repair_run_result,
                )
                repair_payload = _build_knowledge_inline_attempt_runner_payload(
                    pipeline_id=pipeline_id,
                    worker_id=assignment.worker_id,
                    shard_id=parent_shard_id,
                    run_result=repair_run_result,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    prompt_input_mode=(
                        "inline_snippet_repair"
                        if snippet_repair_applicable
                        else "inline_repair"
                    ),
                )
                repair_payload["process_payload"]["runtime_task_id"] = task_manifest.shard_id
                repair_payload["process_payload"]["runtime_parent_shard_id"] = parent_shard_id
                worker_runner_results.append(dict(repair_payload))
                repair_runner_rows = (
                    repair_payload.get("telemetry", {}).get("rows")
                    if isinstance(repair_payload.get("telemetry"), dict)
                    else None
                )
                if isinstance(repair_runner_rows, list):
                    for row_payload in repair_runner_rows:
                        if not isinstance(row_payload, dict):
                            continue
                        row_payload["repair_attempted"] = True
                        row_payload["runtime_task_id"] = task_manifest.shard_id
                        row_payload["runtime_parent_shard_id"] = parent_shard_id
                        stage_rows.append(dict(row_payload))
                (task_root / "repair_events.jsonl").write_text(
                    _render_events_jsonl(repair_run_result.events),
                    encoding="utf-8",
                )
                _write_json({"text": repair_run_result.response_text}, task_root / "repair_last_message.json")
                _write_json(dict(repair_run_result.usage or {}), task_root / "repair_usage.json")
                _write_json(repair_run_result.workspace_manifest(), task_root / "repair_workspace_manifest.json")
                payload, repair_errors, repair_metadata, repair_proposal_status = _evaluate_knowledge_response(
                    shard=task_manifest,
                    response_text=repair_run_result.response_text,
                )
                repair_status = "repaired" if repair_proposal_status == "validated" else "failed"
                recovery_governor.record_followup_outcome(
                    kind="repair",
                    failure_signature=current_failure_signature,
                    recovered=repair_proposal_status == "validated",
                )
                validation_errors = repair_errors
                validation_metadata = dict(repair_metadata or {})
                proposal_status = repair_proposal_status
                active_response_text = repair_run_result.response_text
                _write_json(
                    {
                        "attempted": True,
                        "status": repair_status,
                        "repair_mode": repair_mode,
                        "repair_validation_errors": list(repair_errors),
                        "state": repair_run_result.supervision_state or "completed",
                        "reason_code": repair_run_result.supervision_reason_code,
                        "reason_detail": repair_run_result.supervision_reason_detail,
                        "retryable": repair_run_result.supervision_retryable,
                    },
                    task_root / "repair_status.json",
                )
                task_repair_status_by_shard_id.setdefault(parent_shard_id, {})[
                    task_manifest.shard_id
                ] = repair_status
                if repair_mode:
                    task_repair_mode_by_shard_id.setdefault(parent_shard_id, {})[
                        task_manifest.shard_id
                    ] = repair_mode
                task_repair_validation_errors_by_shard_id.setdefault(parent_shard_id, {})[
                    task_manifest.shard_id
                ] = tuple(repair_errors if repair_status == "failed" else ())
            if repair_skip_reason_code:
                task_repair_skip_reason_by_shard_id.setdefault(parent_shard_id, {})[
                    task_manifest.shard_id
                ] = repair_skip_reason_code

        if primary_row is not None:
            primary_row["proposal_status"] = (
                initial_proposal_status if watchdog_retry_attempted or repair_attempted else proposal_status
            )
            primary_row["final_proposal_status"] = proposal_status
            primary_row["watchdog_retry_attempted"] = watchdog_retry_attempted
            primary_row["watchdog_retry_status"] = watchdog_retry_status
            primary_row["watchdog_retry_skip_reason_code"] = watchdog_retry_skip_reason_code
            primary_row["watchdog_retry_skip_reason_detail"] = watchdog_retry_skip_reason_detail
            primary_row["repair_attempted"] = repair_attempted
            primary_row["repair_status"] = repair_status
            primary_row["repair_mode"] = repair_mode
            primary_row["repair_skip_reason_code"] = repair_skip_reason_code
            primary_row["repair_skip_reason_detail"] = repair_skip_reason_detail
        if primary_runner_row is not None:
            primary_runner_row["proposal_status"] = (
                initial_proposal_status if watchdog_retry_attempted or repair_attempted else proposal_status
            )
            primary_runner_row["final_proposal_status"] = proposal_status
            primary_runner_row["watchdog_retry_attempted"] = watchdog_retry_attempted
            primary_runner_row["watchdog_retry_status"] = watchdog_retry_status
            primary_runner_row["watchdog_retry_skip_reason_code"] = watchdog_retry_skip_reason_code
            primary_runner_row["watchdog_retry_skip_reason_detail"] = watchdog_retry_skip_reason_detail
            primary_runner_row["repair_attempted"] = repair_attempted
            primary_runner_row["repair_status"] = repair_status
            primary_runner_row["repair_mode"] = repair_mode
            primary_runner_row["repair_skip_reason_code"] = repair_skip_reason_code
            primary_runner_row["repair_skip_reason_detail"] = repair_skip_reason_detail
        task_validation_errors_by_shard_id.setdefault(parent_shard_id, {})[
            task_manifest.shard_id
        ] = tuple(validation_errors)
        if task_status_tracker is not None:
            task_status_tracker.mark_terminal(
                task_id=task_manifest.shard_id,
                worker_id=assignment.worker_id,
                terminal_state=_terminal_knowledge_task_state(
                    proposal_status=proposal_status,
                    supervision_state=run_result.supervision_state,
                    watchdog_retry_status=watchdog_retry_status,
                    repair_status=repair_status,
                ),
                attempt_type=_terminal_knowledge_attempt_type(
                    watchdog_retry_status=watchdog_retry_status,
                    repair_status=repair_status,
                ),
                proposal_status=proposal_status,
                validation_errors=validation_errors,
                metadata={
                    "watchdog_retry_status": watchdog_retry_status,
                    "repair_status": repair_status,
                },
                terminal_reason_code=_terminal_reason_for_knowledge_task(
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                    run_result=run_result,
                    retry_skip_reason_code=watchdog_retry_skip_reason_code,
                    retry_skip_reason_detail=watchdog_retry_skip_reason_detail,
                    repair_skip_reason_code=repair_skip_reason_code,
                    repair_skip_reason_detail=repair_skip_reason_detail,
                )[0],
                terminal_reason_detail=_terminal_reason_for_knowledge_task(
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                    run_result=run_result,
                    retry_skip_reason_code=watchdog_retry_skip_reason_code,
                    retry_skip_reason_detail=watchdog_retry_skip_reason_detail,
                    repair_skip_reason_code=repair_skip_reason_code,
                    repair_skip_reason_detail=repair_skip_reason_detail,
                )[1],
            )
        _finalize_terminal_followups_for_task_root(
            task_root,
            terminal_reason_code="superseded_by_terminal_packet",
            terminal_reason_detail="packet reached a terminal state before older follow-up work could finish",
        )
        if progress_state is not None:
            progress_state.mark_task_packet_terminal(
                worker_id=assignment.worker_id,
                task_id=task_manifest.shard_id,
            )
        if payload is not None and proposal_status == "validated":
            semantic_payload, _ = _load_knowledge_response_json_object(
                str(active_response_text or "")
            )
            task_payloads_by_shard_id.setdefault(parent_shard_id, {})[
                task_manifest.shard_id
            ] = semantic_payload

    for shard in runnable_shards:
        if interruption_requested is not None and interruption_requested.is_set():
            break
        shard_root = shard_dir / shard.shard_id
        task_payloads = task_payloads_by_shard_id.get(shard.shard_id, {})
        task_errors = task_validation_errors_by_shard_id.get(shard.shard_id, {})
        task_watchdog_statuses = task_watchdog_retry_status_by_shard_id.get(shard.shard_id, {})
        task_watchdog_skip_reasons = task_watchdog_retry_skip_reason_by_shard_id.get(shard.shard_id, {})
        task_repair_statuses = task_repair_status_by_shard_id.get(shard.shard_id, {})
        task_repair_modes = task_repair_mode_by_shard_id.get(shard.shard_id, {})
        task_repair_skip_reasons = task_repair_skip_reason_by_shard_id.get(shard.shard_id, {})
        task_repair_errors = task_repair_validation_errors_by_shard_id.get(shard.shard_id, {})
        payload, aggregation_metadata = _aggregate_knowledge_task_payloads(
            shard=shard,
            task_payloads_by_task_id=task_payloads,
            task_validation_errors_by_task_id=task_errors,
        )
        payload_candidate, validation_errors, validation_metadata, proposal_status = _evaluate_knowledge_response(
            shard=shard,
            response_text=json.dumps(payload, sort_keys=True),
        )
        watchdog_retry_attempted = bool(task_watchdog_statuses)
        watchdog_retry_status = (
            "recovered"
            if any(status == "recovered" for status in task_watchdog_statuses.values())
            else ("failed" if watchdog_retry_attempted else "not_attempted")
        )
        watchdog_retry_skip_reason_code = (
            sorted({reason for reason in task_watchdog_skip_reasons.values() if reason})[0]
            if task_watchdog_skip_reasons
            else None
        )
        watchdog_retry_skip_reason_detail = (
            f"task-level skip reasons: {dict(sorted(task_watchdog_skip_reasons.items()))}"
            if task_watchdog_skip_reasons
            else None
        )
        repair_attempted = any(
            str(status).strip() != "not_attempted"
            for status in task_repair_statuses.values()
        )
        repair_status = (
            "repaired"
            if any(str(status).strip() == "repaired" for status in task_repair_statuses.values())
            else ("failed" if repair_attempted else "not_attempted")
        )
        repair_skip_reason_code = (
            sorted({reason for reason in task_repair_skip_reasons.values() if reason})[0]
            if task_repair_skip_reasons
            else None
        )
        repair_mode = (
            "snippet_only"
            if any(str(mode).strip() == "snippet_only" for mode in task_repair_modes.values())
            else (
                "general"
                if any(str(mode).strip() == "general" for mode in task_repair_modes.values())
                else None
            )
        )
        repair_skip_reason_detail = (
            f"task-level skip reasons: {dict(sorted(task_repair_skip_reasons.items()))}"
            if task_repair_skip_reasons
            else None
        )
        validation_metadata = {
            "task_aggregation": aggregation_metadata,
            **dict(validation_metadata or {}),
        }
        if task_watchdog_statuses:
            validation_metadata["task_watchdog_retry_status_by_task_id"] = {
                task_id: status
                for task_id, status in sorted(task_watchdog_statuses.items())
            }
        if task_watchdog_skip_reasons:
            validation_metadata["task_watchdog_retry_skip_reason_by_task_id"] = {
                task_id: reason_code
                for task_id, reason_code in sorted(task_watchdog_skip_reasons.items())
            }
        if task_repair_statuses:
            validation_metadata["task_repair_status_by_task_id"] = {
                task_id: status
                for task_id, status in sorted(task_repair_statuses.items())
            }
        if task_repair_modes:
            validation_metadata["task_repair_mode_by_task_id"] = {
                task_id: mode
                for task_id, mode in sorted(task_repair_modes.items())
            }
        if task_repair_skip_reasons:
            validation_metadata["task_repair_skip_reason_by_task_id"] = {
                task_id: reason_code
                for task_id, reason_code in sorted(task_repair_skip_reasons.items())
            }
        repair_validation_errors = sorted(
            {
                str(error).strip()
                for errors in task_repair_errors.values()
                for error in errors
                if str(error).strip()
            }
        )
        if repair_validation_errors:
            validation_metadata["repair_validation_errors"] = repair_validation_errors
        promotable_invalid_bundle = (
            extract_promotable_knowledge_bundles(
                payload=payload_candidate,
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
            )
            if proposal_status != "validated"
            else None
        )
        final_payload = (
            payload_candidate
            if proposal_status == "validated" or promotable_invalid_bundle is not None
            else None
        )
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        _write_json(
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": final_payload,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
                "watchdog_retry_attempted": watchdog_retry_attempted,
                "watchdog_retry_status": watchdog_retry_status,
                "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                "retry_attempted": False,
                "retry_status": "not_attempted",
                "retry_child_shard_ids": [],
                "repair_attempted": repair_attempted,
                "repair_status": repair_status,
                "repair_mode": repair_mode,
                "repair_skip_reason_code": repair_skip_reason_code,
                "repair_skip_reason_detail": repair_skip_reason_detail,
            },
            proposal_path,
        )
        _write_json(
            {
                "status": proposal_status,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "watchdog_retry_attempted": watchdog_retry_attempted,
                "watchdog_retry_status": watchdog_retry_status,
                "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                "retry_attempted": False,
                "retry_status": "not_attempted",
                "retry_child_shard_ids": [],
                "repair_attempted": repair_attempted,
                "repair_status": repair_status,
                "repair_skip_reason_code": repair_skip_reason_code,
                "repair_skip_reason_detail": repair_skip_reason_detail,
                "state": run_result.supervision_state or "completed",
                "reason_code": run_result.supervision_reason_code,
                "reason_detail": run_result.supervision_reason_detail,
                "retryable": run_result.supervision_retryable,
            },
            shard_root / "status.json",
        )
        if proposal_status != "validated":
            worker_failure_count += 1
            worker_failures.append(
                {
                    "worker_id": assignment.worker_id,
                    "shard_id": shard.shard_id,
                    "reason": _failure_reason_from_run_result(
                        run_result=run_result,
                        proposal_status=proposal_status,
                    ),
                    "validation_errors": list(validation_errors),
                    "state": run_result.supervision_state or "completed",
                    "reason_code": run_result.supervision_reason_code,
                }
            )
        else:
            worker_proposal_count += 1
            cohort_watchdog_state.record_validated_result(
                duration_ms=run_result.duration_ms,
                example_payload=_build_knowledge_watchdog_example(
                    shard=shard,
                    payload=final_payload,
                ),
            )
        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status=proposal_status,
                proposal_path=_relative_path(run_root, proposal_path),
                payload=final_payload,
                validation_errors=validation_errors,
                metadata={
                    **dict(validation_metadata or {}),
                    "watchdog_retry_attempted": watchdog_retry_attempted,
                    "watchdog_retry_status": watchdog_retry_status,
                    "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                    "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                    "retry_attempted": False,
                    "retry_status": "not_attempted",
                    "retry_child_shard_ids": [],
                    "repair_attempted": repair_attempted,
                    "repair_status": repair_status,
                    "repair_skip_reason_code": repair_skip_reason_code,
                    "repair_skip_reason_detail": repair_skip_reason_detail,
                },
            )
        )
        if progress_state is not None:
            progress_state.mark_task_packets_terminal(
                worker_id=assignment.worker_id,
                task_ids=_progress_task_ids_for_knowledge_shard(
                    shard_id=shard.shard_id,
                    task_plans_by_shard_id=task_plans_by_shard_id,
                ),
            )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    return worker_failure_count, worker_proposal_count
