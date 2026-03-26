from __future__ import annotations

from . import _shared as _shared_module
from . import planning as _planning_module
from . import recovery as _recovery_module
from ..knowledge_phase_workspace_tools import (
    build_pass1_work_ledger,
    build_knowledge_workspace_shard_metadata,
    render_knowledge_current_phase_brief,
    render_knowledge_current_phase_feedback,
    write_knowledge_output_contract,
    write_knowledge_worker_examples,
    write_knowledge_worker_tools,
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


def _phase_row_for_shard(shard_id: str) -> dict[str, Any]:
    return {
        "status": "active",
        "phase": "pass1",
        "shard_id": shard_id,
        "input_path": str(Path("in") / f"{shard_id}.json"),
        "work_path": str(Path("work") / f"{shard_id}.pass1.json"),
        "repair_path": str(Path("repair") / f"{shard_id}.pass1.json"),
        "result_path": str(Path("out") / f"{shard_id}.json"),
        "hint_path": str(Path("hints") / f"{shard_id}.md"),
    }


def _write_phase_surface(
    *,
    worker_root: Path,
    phase_row: Mapping[str, Any],
    completed: bool = False,
) -> None:
    phase_json_path = worker_root / "current_phase.json"
    phase_brief_path = worker_root / "CURRENT_PHASE.md"
    phase_feedback_path = worker_root / "CURRENT_PHASE_FEEDBACK.md"
    _write_json(dict(phase_row), phase_json_path)
    phase_brief_path.write_text(
        render_knowledge_current_phase_brief(dict(phase_row)),
        encoding="utf-8",
    )
    phase_feedback_path.write_text(
        render_knowledge_current_phase_feedback(
            phase_row=dict(phase_row),
            completed=completed,
        ),
        encoding="utf-8",
    )


def _evaluate_phase_knowledge_output(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    if response_text is None or not str(response_text).strip():
        return None, ("missing_output",), {}, "missing_output"
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return None, ("response_json_invalid",), {}, "invalid"
    if not isinstance(payload, Mapping):
        return None, ("response_not_json_object",), {}, "invalid"
    normalized_payload, normalization_metadata = normalize_knowledge_worker_payload(dict(payload))
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
    shard_dir = worker_root / "shards"
    logs_dir = worker_root / "logs"
    out_dir = worker_root / "out"
    work_dir = worker_root / "work"
    repair_dir = worker_root / "repair"
    for path in (in_dir, hints_dir, shard_dir, logs_dir, out_dir, work_dir, repair_dir):
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
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
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
        _write_json(
            {
                "status": "preflight_rejected",
                "validation_errors": [reason_code],
                "validation_metadata": {},
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "state": "preflight_rejected",
                "reason_code": reason_code,
                "reason_detail": reason_detail,
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

    assigned_shard_rows: list[dict[str, Any]] = []
    for shard in assigned_shards:
        shard_id = str(shard.shard_id).strip()
        shard_row = {
            "shard_id": shard_id,
            "owned_ids": list(shard.owned_ids),
            "metadata": build_knowledge_workspace_shard_metadata(
                shard_id=shard_id,
                input_payload=shard.input_payload,
                input_path=str(Path("in") / f"{shard_id}.json"),
                hint_path=str(Path("hints") / f"{shard_id}.md"),
                result_path=str(Path("out") / f"{shard_id}.json"),
            ),
        }
        assigned_shard_rows.append(shard_row)
        _write_worker_input(
            path=in_dir / f"{shard_id}.json",
            payload=shard.input_payload,
            input_text=shard.input_text,
        )
        _write_knowledge_worker_hint(path=hints_dir / f"{shard_id}.md", shard=shard)
        _write_json(
            build_pass1_work_ledger(dict(shard.input_payload or {})),
            work_dir / f"{shard_id}.pass1.json",
        )
        (shard_dir / shard_id).mkdir(parents=True, exist_ok=True)
    _write_json(assigned_shard_rows, worker_root / "assigned_shards.json")
    write_knowledge_worker_examples(worker_root=worker_root)
    write_knowledge_output_contract(worker_root=worker_root)
    write_knowledge_worker_tools(worker_root=worker_root)
    if assigned_shards:
        _write_phase_surface(
            worker_root=worker_root,
            phase_row=_phase_row_for_shard(str(assigned_shards[0].shard_id)),
        )
    else:
        _write_phase_surface(
            worker_root=worker_root,
            phase_row={"status": "completed", "phase": None, "shard_id": None},
            completed=True,
        )
        worker_runner_payload = _aggregate_worker_runner_payload(
            pipeline_id=pipeline_id,
            worker_runs=worker_runner_results,
            stage_rows=stage_rows,
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
                    "shards_dir": _relative_path(run_root, shard_dir),
                    "log_dir": _relative_path(run_root, logs_dir),
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
                    "input_path": str(Path("in") / f"{shard.shard_id}.json"),
                    "hint_path": str(Path("hints") / f"{shard.shard_id}.md"),
                    "result_path": str(Path("out") / f"{shard.shard_id}.json"),
                    "workspace_processing_contract": "knowledge_phase_shard_ledger_v1",
                },
            )

    worker_prompt_text = _build_knowledge_workspace_worker_prompt(shards=assigned_shards)
    worker_prompt_path = worker_root / "prompt.txt"
    worker_prompt_path.write_text(worker_prompt_text, encoding="utf-8")
    phase_queue_controller = _KnowledgeWorkspacePhaseQueueController(
        worker_root=worker_root,
        shard_ids=tuple(str(shard.shard_id) for shard in assigned_shards),
    )
    run_result = runner.run_workspace_worker(
        prompt_text=worker_prompt_text,
        working_dir=worker_root,
        env=env,
        model=model,
        reasoning_effort=reasoning_effort,
        workspace_task_label="knowledge worker session",
        supervision_callback=_build_strict_json_watchdog_callback(
            live_status_path=worker_root / "live_status.json",
            allow_workspace_commands=True,
            execution_workspace_root=worker_root,
            expected_workspace_output_paths=[
                out_dir / f"{shard.shard_id}.json" for shard in assigned_shards
            ],
            task_queue_controller=phase_queue_controller,
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
    _finalize_live_status(
        worker_root / "live_status.json",
        run_result=run_result,
        watchdog_policy="workspace_worker_v1",
    )
    (worker_root / "events.jsonl").write_text(
        _render_events_jsonl(run_result.events),
        encoding="utf-8",
    )
    _write_json({"text": run_result.response_text}, worker_root / "last_message.json")
    _write_json(dict(run_result.usage or {}), worker_root / "usage.json")
    _write_json(run_result.workspace_manifest(), worker_root / "workspace_manifest.json")
    _write_optional_text(worker_root / "stdout.txt", run_result.stdout_text)
    _write_optional_text(worker_root / "stderr.txt", run_result.stderr_text)

    task_total = len(assigned_shards)
    for task_index, shard in enumerate(assigned_shards):
        shard_root = shard_dir / shard.shard_id
        response_path = out_dir / f"{shard.shard_id}.json"
        response_text = (
            response_path.read_text(encoding="utf-8")
            if response_path.exists()
            else None
        )
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
            task_count=task_total,
            task_index=task_index,
        )
        worker_runner_results.append(dict(runner_payload))
        runner_rows = (
            runner_payload.get("telemetry", {}).get("rows")
            if isinstance(runner_payload.get("telemetry"), Mapping)
            else None
        )
        if isinstance(runner_rows, list):
            for row_payload in runner_rows:
                if isinstance(row_payload, Mapping):
                    stage_rows.append(dict(row_payload))
        payload, validation_errors, validation_metadata, proposal_status = (
            _evaluate_phase_knowledge_output(
                shard=shard,
                response_text=response_text,
            )
        )
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
        _write_json(
            {
                "status": proposal_status,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "state": run_result.supervision_state or "completed",
                "reason_code": run_result.supervision_reason_code,
                "reason_detail": run_result.supervision_reason_detail,
                "retryable": run_result.supervision_retryable,
            },
            shard_root / "status.json",
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
            terminal_reason_code, terminal_reason_detail = (
                _terminal_reason_for_knowledge_task(
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                    run_result=run_result,
                    retry_skip_reason_code=None,
                    retry_skip_reason_detail=None,
                    repair_skip_reason_code=None,
                    repair_skip_reason_detail=None,
                )
            )
            task_status_tracker.mark_terminal(
                task_id=shard.shard_id,
                worker_id=assignment.worker_id,
                terminal_state=proposal_status,
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
                "shards_dir": _relative_path(run_root, shard_dir),
                "log_dir": _relative_path(run_root, logs_dir),
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
        stage_rows=tuple(stage_rows),
        worker_runner_payload=worker_runner_payload,
    )
