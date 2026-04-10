from __future__ import annotations

import cookimport.parsing.canonical_line_roles.runtime as root

def _run_line_role_taskfile_assignment_v1(*, run_root: root.Path, assignment: root.WorkerAssignmentV1, artifacts: dict[str, str], assigned_shards: root.Sequence[root.ShardManifestEntryV1], worker_root: root.Path, in_dir: root.Path, debug_dir: root.Path, hints_dir: root.Path, shard_dir: root.Path, logs_dir: root.Path, debug_payload_by_shard_id: root.Mapping[str, root.Any], deterministic_baseline_by_shard_id: root.Mapping[str, root.Mapping[int, root.CanonicalLineRolePrediction]], runner: root.CodexExecRunner, pipeline_id: str, env: dict[str, str], model: str | None, reasoning_effort: str | None, settings: root.Mapping[str, root.Any], output_schema_path: root.Path | None, timeout_seconds: int, cohort_watchdog_state: root._LineRoleCohortWatchdogState, shard_completed_callback: root.Callable[..., None] | None, prompt_state: '_PromptArtifactState' | None, validator: root.Callable[[root.ShardManifestEntryV1, dict[str, root.Any]], tuple[bool, root.Sequence[str], dict[str, root.Any] | None]]) -> root._DirectLineRoleWorkerResult:
    out_dir = worker_root / 'out'
    out_dir.mkdir(parents=True, exist_ok=True)
    worker_failure_count = 0
    worker_proposal_count = 0
    worker_runner_results: list[dict[str, root.Any]] = []
    worker_failures: list[dict[str, root.Any]] = []
    worker_proposals: list[root.ShardProposalV1] = []
    stage_rows: list[dict[str, root.Any]] = []
    runner_results_by_shard_id: dict[str, dict[str, root.Any]] = {}
    runnable_shard_ids: set[str] = set()
    resumed_output_path_by_shard_id: dict[str, root.Path] = {}
    task_status_rows: list[dict[str, root.Any]] = []
    worker_prompt_path: root.Path | None = None
    session_run_result: root.CodexExecRunResult | None = None
    valid_shards: list[root.ShardManifestEntryV1] = []
    task_file_payload: dict[str, root.Any] | None = None
    unit_to_shard_id: dict[str, str] = {}
    unit_to_atomic_index: dict[str, int] = {}
    for shard in assigned_shards:
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
        for stale_artifact_name in ('repair_prompt.txt', 'repair_events.jsonl', 'repair_last_message.json', 'repair_usage.json', 'repair_workspace_manifest.json', 'repair_live_status.json', 'repair_status.json'):
            stale_artifact_path = shard_root / stale_artifact_name
            if stale_artifact_path.exists():
                stale_artifact_path.unlink()
        preflight_failure = root._preflight_line_role_shard(shard)
        if preflight_failure is None:
            valid_shards.append(shard)
            continue
        root._write_runtime_json(shard_root / 'live_status.json', {'state': 'preflight_rejected', 'reason_code': str(preflight_failure.get('reason_code') or 'preflight_rejected'), 'reason_detail': str(preflight_failure.get('reason_detail') or ''), 'retryable': False, 'watchdog_policy': 'taskfile_v1', 'elapsed_seconds': 0.0, 'last_event_seconds_ago': None, 'command_execution_count': 0, 'reasoning_item_count': 0})
        root._write_runtime_json(shard_root / 'status.json', {'status': 'missing_output', 'validation_errors': [str(preflight_failure.get('reason_code') or 'preflight_rejected')], 'validation_metadata': {}, 'runtime_mode': root.DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'watchdog_retry_attempted': False, 'watchdog_retry_status': 'not_attempted', 'repair_attempted': False, 'repair_status': 'not_attempted', 'state': 'preflight_rejected', 'reason_code': str(preflight_failure.get('reason_code') or 'preflight_rejected'), 'reason_detail': str(preflight_failure.get('reason_detail') or ''), 'retryable': False})
        proposal_path = run_root / artifacts['proposals_dir'] / f'{shard.shard_id}.json'
        root._write_runtime_json(proposal_path, {'shard_id': shard.shard_id, 'worker_id': assignment.worker_id, 'payload': None, 'validation_errors': [str(preflight_failure.get('reason_code') or 'preflight_rejected')], 'validation_metadata': {}, 'watchdog_retry_attempted': False, 'watchdog_retry_status': 'not_attempted', 'repair_attempted': False, 'repair_status': 'not_attempted'})
        root._write_runtime_json(shard_root / 'proposal.json', {'error': 'missing_output', 'validation_errors': [str(preflight_failure.get('reason_code') or 'preflight_rejected')], 'validation_metadata': {}})
        worker_failure_count += 1
        worker_failures.append({'worker_id': assignment.worker_id, 'shard_id': shard.shard_id, 'reason': 'preflight_rejected', 'validation_errors': [str(preflight_failure.get('reason_code') or 'preflight_rejected')]})
        worker_proposals.append(root.ShardProposalV1(shard_id=shard.shard_id, worker_id=assignment.worker_id, status='missing_output', proposal_path=root._relative_runtime_path(run_root, proposal_path), payload=None, validation_errors=(str(preflight_failure.get('reason_code') or 'preflight_rejected'),), metadata={}))
        if prompt_state is not None:
            prompt_state.write_failure(phase_key=str((shard.metadata or {}).get('phase_key') or 'line_role').strip(), prompt_stem=str((shard.metadata or {}).get('prompt_stem') or 'prompt').strip(), prompt_index=int((shard.metadata or {}).get('prompt_index') or 0), error=str(preflight_failure.get('reason_detail') or 'preflight rejected'))
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)
    assigned_shard_rows = [root._build_line_role_worker_shard_row(shard=shard) for shard in valid_shards]
    assigned_shard_row_by_shard_id = {str(shard_row.get('shard_id') or '').strip(): shard_row for shard_row in assigned_shard_rows if str(shard_row.get('shard_id') or '').strip()}
    root._write_runtime_json(worker_root / 'assigned_shards.json', assigned_shard_rows)
    for shard in valid_shards:
        shard_id = shard.shard_id
        shard_row = assigned_shard_row_by_shard_id.get(shard_id)
        if shard_row is None:
            continue
        root._write_worker_debug_input(path=in_dir / f'{shard_id}.json', payload=shard.input_payload, input_text=None)
        root._write_worker_debug_input(path=debug_dir / f'{shard_id}.json', payload=debug_payload_by_shard_id.get(shard_id), input_text=None)
        root._write_line_role_worker_hint(path=hints_dir / f'{shard_id}.md', shard=shard, debug_payload=debug_payload_by_shard_id.get(shard_id))
        existing_output_path = root._find_line_role_existing_output_path(run_root=run_root, preferred_worker_root=worker_root, shard_id=shard_id)
        if existing_output_path is None:
            runnable_shard_ids.add(shard_id)
            continue
        try:
            existing_response_text = existing_output_path.read_text(encoding='utf-8')
        except OSError:
            runnable_shard_ids.add(shard_id)
            continue
        existing_payload, _, _, existing_status = root._evaluate_line_role_response_with_pathology_guard(shard=shard, response_text=existing_response_text, validator=validator, deterministic_baseline_by_atomic_index=dict(deterministic_baseline_by_shard_id.get(shard_id) or {}))
        if existing_payload is not None and existing_status == 'validated':
            resumed_output_path_by_shard_id[shard_id] = existing_output_path
        else:
            runnable_shard_ids.add(shard_id)
    runnable_shards = [shard for shard in valid_shards if shard.shard_id in runnable_shard_ids]
    task_file_guardrail: dict[str, root.Any] | None = None
    line_role_same_session_state_payload: dict[str, root.Any] = {}
    fresh_session_retry_count = 0
    fresh_session_retry_status = 'not_attempted'
    fresh_session_recovery_metadata: dict[str, root.Any] = {}
    fresh_worker_replacement_count = 0
    fresh_worker_replacement_status = 'not_attempted'
    fresh_worker_replacement_metadata: dict[str, root.Any] = {}
    if runnable_shards:
        task_file_payload, unit_to_shard_id, unit_to_atomic_index = root._build_line_role_task_file(assignment=assignment, shards=runnable_shards, debug_payload_by_shard_id=debug_payload_by_shard_id, deterministic_baseline_by_shard_id=deterministic_baseline_by_shard_id)
        task_file_guardrail = root.build_task_file_guardrail(payload=task_file_payload, assignment_id=assignment.worker_id, worker_id=assignment.worker_id)
        state_path = root._line_role_same_session_state_path(worker_root)
        root.initialize_line_role_same_session_state(state_path=state_path, assignment_id=assignment.worker_id, worker_id=assignment.worker_id, task_file=task_file_payload, unit_to_shard_id=unit_to_shard_id, unit_to_atomic_index=unit_to_atomic_index, shards=[root.asdict(shard) for shard in runnable_shards], output_dir=out_dir)
        root.write_task_file(path=worker_root / root.TASK_FILE_NAME, payload=task_file_payload)
        worker_prompt_text = root._build_line_role_taskfile_prompt(shards=runnable_shards)
        worker_prompt_path = worker_root / 'prompt.txt'
        worker_prompt_path.write_text(worker_prompt_text, encoding='utf-8')
        worker_live_status_path = worker_root / 'live_status.json'
        shard_live_status_paths = [shard_dir / shard.shard_id / 'live_status.json' for shard in runnable_shards]
        expected_workspace_output_paths = [out_dir / f'{shard.shard_id}.json' for shard in runnable_shards]
        for shard in runnable_shards:
            shard_root = shard_dir / shard.shard_id
            (shard_root / 'prompt.txt').write_text(worker_prompt_text, encoding='utf-8')
            if prompt_state is not None:
                prompt_state.write_prompt(phase_key=str((shard.metadata or {}).get('phase_key') or 'line_role').strip(), prompt_stem=str((shard.metadata or {}).get('prompt_stem') or 'prompt').strip(), prompt_index=int((shard.metadata or {}).get('prompt_index') or 0), prompt_text=worker_prompt_text)

        def _run_workspace_attempt(*, prompt_text: str, prompt_path: root.Path, workspace_task_label: str) -> tuple[root.CodexExecRunResult, root.CodexFarmRunnerError | None, dict[str, root.Any]]:
            attempt_exception: root.CodexFarmRunnerError | None = None
            try:
                run_result = runner.run_taskfile_worker(prompt_text=prompt_text, working_dir=worker_root, env={**dict(env), root.LINE_ROLE_SAME_SESSION_STATE_ENV: str(state_path)}, model=model, reasoning_effort=reasoning_effort, timeout_seconds=timeout_seconds, completed_termination_grace_seconds=float(settings.get('completed_termination_grace_seconds') or 15.0), workspace_task_label=workspace_task_label, supervision_callback=root._build_strict_json_watchdog_callback(live_status_path=worker_live_status_path, live_status_paths=shard_live_status_paths, same_session_state_path=state_path, cohort_watchdog_state=cohort_watchdog_state, watchdog_policy='taskfile_v1', allow_workspace_commands=True, expected_workspace_output_paths=expected_workspace_output_paths, workspace_completion_quiescence_seconds=float(settings.get('workspace_completion_quiescence_seconds') or 15.0), final_message_missing_output_grace_seconds=float(settings.get('workspace_completion_quiescence_seconds') or 15.0)))
            except root.CodexFarmRunnerError as exc:
                attempt_exception = exc
                run_result = root._build_line_role_runner_exception_result(exc=exc, prompt_text=prompt_text, working_dir=worker_root, retryable_reason=root._line_role_retryable_runner_exception_reason(exc))
            run_result = root._normalize_line_role_run_result_after_final_sync(run_result=run_result, state_path=state_path, expected_workspace_output_paths=expected_workspace_output_paths)
            root._finalize_live_status(worker_live_status_path, run_result=run_result, watchdog_policy='taskfile_v1')
            for live_status_path in shard_live_status_paths:
                root._finalize_live_status(live_status_path, run_result=run_result, watchdog_policy='taskfile_v1')
            (worker_root / 'events.jsonl').write_text(root._render_codex_events_jsonl(run_result.events), encoding='utf-8')
            root._write_runtime_json(worker_root / 'last_message.json', {'text': run_result.response_text})
            root._write_runtime_json(worker_root / 'usage.json', dict(run_result.usage or {}))
            root._write_runtime_json(worker_root / 'workspace_manifest.json', run_result.workspace_manifest())
            root._write_optional_runtime_text(worker_root / 'stdout.txt', run_result.stdout_text)
            root._write_optional_runtime_text(worker_root / 'stderr.txt', run_result.stderr_text)
            return (run_result, attempt_exception, root._load_json_dict_safely(state_path))
        session_run_result, initial_runner_exception, line_role_same_session_state_payload = _run_workspace_attempt(prompt_text=worker_prompt_text, prompt_path=worker_prompt_path, workspace_task_label='canonical line-role worker session')
        worker_session_runs: list[dict[str, root.Any]] = [{'run_result': session_run_result, 'prompt_path': worker_prompt_path, 'fresh_session_resume': False, 'fresh_session_resume_reason_code': None, 'fresh_worker_replacement': False, 'fresh_worker_replacement_reason_code': None}]

        def _sync_latest_worker_session_run_result() -> None:
            if worker_session_runs:
                worker_session_runs[-1]['run_result'] = session_run_result
        should_replace_worker, replacement_reason = root._should_attempt_line_role_fresh_worker_replacement(exc=initial_runner_exception, run_result=None if initial_runner_exception is not None else session_run_result, replacement_attempt_count=fresh_worker_replacement_count, same_session_state_payload=line_role_same_session_state_payload)
        if initial_runner_exception is not None or should_replace_worker:
            fresh_worker_replacement_metadata = {'fresh_worker_replacement_attempted': bool(should_replace_worker), 'fresh_worker_replacement_status': 'attempted' if should_replace_worker else 'skipped', 'fresh_worker_replacement_count': 0, 'fresh_worker_replacement_reason_code': replacement_reason if should_replace_worker else None, 'fresh_worker_replacement_error_summary': str(initial_runner_exception) if initial_runner_exception is not None else str(session_run_result.supervision_reason_detail or '').strip() or None, 'fresh_worker_replacement_skipped_reason': None if should_replace_worker else replacement_reason}
            if should_replace_worker:
                fresh_worker_replacement_count = 1
                fresh_worker_replacement_status = 'attempted'
                line_role_same_session_state_payload = root._reset_line_role_workspace_for_fresh_worker_replacement(worker_root=worker_root, out_dir=out_dir, assignment=assignment, runnable_shards=runnable_shards, task_file_payload=task_file_payload, unit_to_shard_id=unit_to_shard_id, unit_to_atomic_index=unit_to_atomic_index)
                replacement_prompt_path = worker_root / 'prompt_fresh_worker_replacement.txt'
                replacement_prompt_text = root._build_line_role_fresh_worker_replacement_prompt(shards=runnable_shards)
                replacement_prompt_path.write_text(replacement_prompt_text, encoding='utf-8')
                session_run_result, _replacement_exception, line_role_same_session_state_payload = _run_workspace_attempt(prompt_text=replacement_prompt_text, prompt_path=replacement_prompt_path, workspace_task_label='canonical line-role worker replacement session')
                recovery_outputs_present = bool(root._summarize_workspace_output_paths(expected_workspace_output_paths).get('complete'))
                fresh_worker_replacement_status = 'recovered' if bool(line_role_same_session_state_payload.get('completed')) or recovery_outputs_present else 'exhausted'
                fresh_worker_replacement_metadata = {**fresh_worker_replacement_metadata, 'fresh_worker_replacement_attempted': True, 'fresh_worker_replacement_status': fresh_worker_replacement_status, 'fresh_worker_replacement_count': 1, 'fresh_worker_replacement_skipped_reason': None}
                worker_session_runs.append({'run_result': session_run_result, 'prompt_path': replacement_prompt_path, 'fresh_session_resume': False, 'fresh_session_resume_reason_code': None, 'fresh_worker_replacement': True, 'fresh_worker_replacement_reason_code': replacement_reason})
        final_message_recovery_assessment_path = worker_root / 'final_message_recovery_assessment.json'
        should_retry = False
        retry_reason = 'not_attempted'
        retry_prompt_path: root.Path | None = None
        retry_prompt_text: str | None = None
        retry_workspace_task_label = 'canonical line-role fresh-session recovery'
        if str(session_run_result.supervision_reason_code or '').strip() in {'workspace_final_message_missing_output', 'workspace_final_message_incomplete_progress'}:
            assessment, assessment_payload = root._assess_line_role_workspace_recovery(worker_root=worker_root, state_path=state_path, run_result=session_run_result, expected_workspace_output_paths=expected_workspace_output_paths)
            authoritative_completion_proved = root._line_role_assessment_proves_authoritative_completion(assessment)
            if authoritative_completion_proved:
                session_run_result = root._override_line_role_missing_output_with_authoritative_completion(run_result=session_run_result)
                _sync_latest_worker_session_run_result()
                root._finalize_live_status(worker_live_status_path, run_result=session_run_result, watchdog_policy='taskfile_v1')
                for live_status_path in shard_live_status_paths:
                    root._finalize_live_status(live_status_path, run_result=session_run_result, watchdog_policy='taskfile_v1')
                should_retry = False
                retry_reason = 'authoritative_completion_already_visible'
            else:
                should_retry, retry_reason = root._should_attempt_line_role_final_message_recovery(run_result=session_run_result, assessment=assessment)
            fresh_session_recovery_metadata = {'fresh_session_recovery_attempted': False, 'fresh_session_recovery_status': 'authoritative_completion' if authoritative_completion_proved else 'attempted' if should_retry else 'skipped', 'fresh_session_recovery_count': 0, 'fresh_session_recovery_skipped_reason': None if should_retry or authoritative_completion_proved else retry_reason, 'shared_retry_budget_spent': int(assessment.fresh_session_retry_count) >= int(assessment.fresh_session_retry_limit), 'prior_session_reason_code': assessment.prior_session_reason_code or None, 'diagnosis_code': assessment.diagnosis_code or None, 'recommended_command': assessment.recommended_command, 'resume_summary': assessment.resume_summary, 'assessment_path': root._relative_runtime_path(run_root, final_message_recovery_assessment_path)}
            root._write_runtime_json(final_message_recovery_assessment_path, {**assessment_payload, 'authoritative_completion_override_applied': authoritative_completion_proved, **fresh_session_recovery_metadata})
            if should_retry:
                retry_prompt_path = worker_root / 'prompt_resume_final_message.txt'
                retry_prompt_text = root._build_line_role_final_message_recovery_prompt(shards=runnable_shards, assessment=assessment)
                retry_workspace_task_label = 'canonical line-role final-message missing-output recovery'
        else:
            should_retry, retry_reason = root._should_attempt_line_role_fresh_session_retry(run_result=session_run_result, task_file_path=worker_root / root.TASK_FILE_NAME, original_task_file=task_file_payload, same_session_state_payload=line_role_same_session_state_payload)
        if should_retry:
            fresh_session_retry_count = 1
            fresh_session_retry_status = 'attempted'
            line_role_same_session_state_payload['fresh_session_retry_count'] = 1
            line_role_same_session_state_payload['fresh_session_retry_status'] = 'attempted'
            fresh_session_retry_history = list(line_role_same_session_state_payload.get('fresh_session_retry_history') or [])
            fresh_session_retry_history.append({'attempt': 1, 'reason_code': retry_reason, 'reason_detail': 'workspace final message was observed without required shard outputs' if retry_reason in {'workspace_final_message_missing_output', 'workspace_final_message_incomplete_progress'} else 'clean first session preserved useful workspace state without completion'})
            line_role_same_session_state_payload['fresh_session_retry_history'] = fresh_session_retry_history
            root._write_runtime_json(state_path, line_role_same_session_state_payload)
            resume_prompt_path = retry_prompt_path or worker_root / 'prompt_resume.txt'
            resume_prompt_text = retry_prompt_text or root._build_line_role_taskfile_prompt(shards=runnable_shards, fresh_session_resume=True)
            resume_prompt_path.write_text(resume_prompt_text, encoding='utf-8')
            session_run_result = runner.run_taskfile_worker(prompt_text=resume_prompt_text, working_dir=worker_root, env={**dict(env), root.LINE_ROLE_SAME_SESSION_STATE_ENV: str(state_path)}, model=model, reasoning_effort=reasoning_effort, timeout_seconds=timeout_seconds, completed_termination_grace_seconds=float(settings.get('completed_termination_grace_seconds') or 15.0), workspace_task_label=retry_workspace_task_label, supervision_callback=root._build_strict_json_watchdog_callback(live_status_path=worker_live_status_path, live_status_paths=shard_live_status_paths, same_session_state_path=state_path, cohort_watchdog_state=cohort_watchdog_state, watchdog_policy='taskfile_v1', allow_workspace_commands=True, expected_workspace_output_paths=expected_workspace_output_paths, workspace_completion_quiescence_seconds=float(settings.get('workspace_completion_quiescence_seconds') or 15.0), final_message_missing_output_grace_seconds=float(settings.get('workspace_completion_quiescence_seconds') or 15.0)))
            session_run_result = root._normalize_line_role_run_result_after_final_sync(run_result=session_run_result, state_path=state_path, expected_workspace_output_paths=expected_workspace_output_paths)
            root._finalize_live_status(worker_live_status_path, run_result=session_run_result, watchdog_policy='taskfile_v1')
            for live_status_path in shard_live_status_paths:
                root._finalize_live_status(live_status_path, run_result=session_run_result, watchdog_policy='taskfile_v1')
            (worker_root / 'events.jsonl').write_text(root._render_codex_events_jsonl(session_run_result.events), encoding='utf-8')
            root._write_runtime_json(worker_root / 'last_message.json', {'text': session_run_result.response_text})
            root._write_runtime_json(worker_root / 'usage.json', dict(session_run_result.usage or {}))
            root._write_runtime_json(worker_root / 'workspace_manifest.json', session_run_result.workspace_manifest())
            root._write_optional_runtime_text(worker_root / 'stdout.txt', session_run_result.stdout_text)
            root._write_optional_runtime_text(worker_root / 'stderr.txt', session_run_result.stderr_text)
            line_role_same_session_state_payload = root._load_json_dict_safely(state_path)
            fresh_session_retry_status = 'completed' if bool(line_role_same_session_state_payload.get('completed')) else 'failed'
            line_role_same_session_state_payload['fresh_session_retry_count'] = 1
            line_role_same_session_state_payload['fresh_session_retry_status'] = fresh_session_retry_status
            line_role_same_session_state_payload['fresh_session_retry_history'] = [{**dict(row), **({'result_completed': bool(line_role_same_session_state_payload.get('completed')), 'result_final_status': line_role_same_session_state_payload.get('final_status')} if index == len(fresh_session_retry_history) - 1 else {})} for index, row in enumerate(fresh_session_retry_history) if isinstance(row, root.Mapping)]
            root._write_runtime_json(state_path, line_role_same_session_state_payload)
            if fresh_session_recovery_metadata:
                recovery_outputs_present = bool(root._summarize_workspace_output_paths(expected_workspace_output_paths).get('complete'))
                fresh_session_recovery_metadata = {**fresh_session_recovery_metadata, 'fresh_session_recovery_attempted': True, 'fresh_session_recovery_status': 'recovered' if bool(line_role_same_session_state_payload.get('completed')) or recovery_outputs_present else 'exhausted', 'fresh_session_recovery_count': 1, 'fresh_session_recovery_skipped_reason': None, 'shared_retry_budget_spent': True}
                existing_assessment_payload = root._load_json_dict_safely(final_message_recovery_assessment_path)
                root._write_runtime_json(final_message_recovery_assessment_path, {**existing_assessment_payload, **fresh_session_recovery_metadata})
            worker_session_runs.append({'run_result': session_run_result, 'prompt_path': resume_prompt_path, 'fresh_session_resume': True, 'fresh_session_resume_reason_code': retry_reason, 'fresh_worker_replacement': False, 'fresh_worker_replacement_reason_code': None})
        shard_count = max(1, len(runnable_shards))
        for session_index, session_row in enumerate(worker_session_runs, start=1):
            session_result = session_row['run_result']
            session_prompt_file = session_row['prompt_path']
            fresh_session_resume = bool(session_row['fresh_session_resume'])
            fresh_session_resume_reason_code = session_row['fresh_session_resume_reason_code']
            fresh_worker_replacement = bool(session_row.get('fresh_worker_replacement'))
            fresh_worker_replacement_reason_code = session_row.get('fresh_worker_replacement_reason_code')
            for shard_index, shard in enumerate(runnable_shards):
                shard_id = shard.shard_id
                input_path = in_dir / f'{shard_id}.json'
                debug_path = debug_dir / f'{shard_id}.json'
                runner_payload = root._build_line_role_workspace_task_runner_payload(pipeline_id=pipeline_id, worker_id=assignment.worker_id, shard_id=shard_id, runtime_shard_id=shard_id, run_result=session_result, model=model, reasoning_effort=reasoning_effort, request_input_file=input_path, debug_input_file=debug_path, worker_prompt_path=session_prompt_file, worker_root=worker_root, task_count=shard_count, task_index=min(shard_index, shard_count - 1))
                telemetry = runner_payload.get('telemetry')
                row_payloads = telemetry.get('rows') if isinstance(telemetry, dict) else None
                if isinstance(row_payloads, list):
                    for row_payload in row_payloads:
                        if isinstance(row_payload, dict):
                            row_payload['fresh_session_resume'] = fresh_session_resume
                            row_payload['fresh_session_resume_reason_code'] = fresh_session_resume_reason_code
                            row_payload['fresh_worker_replacement'] = fresh_worker_replacement
                            row_payload['fresh_worker_replacement_reason_code'] = fresh_worker_replacement_reason_code
                            stage_rows.append(dict(row_payload))
                runner_payload['fresh_session_resume'] = fresh_session_resume
                runner_payload['fresh_session_resume_reason_code'] = fresh_session_resume_reason_code
                runner_payload['fresh_worker_replacement'] = fresh_worker_replacement
                runner_payload['fresh_worker_replacement_reason_code'] = fresh_worker_replacement_reason_code
                process_payload = runner_payload.get('process_payload')
                if isinstance(process_payload, dict):
                    process_payload['fresh_session_resume'] = fresh_session_resume
                    process_payload['fresh_session_resume_reason_code'] = fresh_session_resume_reason_code
                    process_payload['fresh_worker_replacement'] = fresh_worker_replacement
                    process_payload['fresh_worker_replacement_reason_code'] = fresh_worker_replacement_reason_code
                    process_payload['session_index'] = session_index
                worker_runner_results.append(dict(runner_payload))
    else:
        root._write_runtime_json(worker_root / 'live_status.json', {'state': 'completed', 'reason_code': 'resume_existing_outputs' if resumed_output_path_by_shard_id else 'no_shards_assigned', 'reason_detail': 'all canonical line-role shard outputs were already durable on disk' if resumed_output_path_by_shard_id else 'worker had no runnable canonical line-role shards', 'retryable': False, 'watchdog_policy': 'taskfile_v1'})
    for shard_index, shard in enumerate(valid_shards):
        shard_id = shard.shard_id
        input_path = in_dir / f'{shard_id}.json'
        debug_path = debug_dir / f'{shard_id}.json'
        repair_request_path = worker_root / 'repair' / f'{shard_id}.json'
        repair_state_path = worker_root / 'repair' / f'{shard_id}.status.json'
        output_path = out_dir / f'{shard_id}.json'
        current_task_file_missing = session_run_result is not None and shard_id in runnable_shard_ids and (not (worker_root / root.TASK_FILE_NAME).exists())
        response_source_path = None
        if not current_task_file_missing:
            response_source_path = output_path if output_path.exists() else resumed_output_path_by_shard_id.get(shard_id)
        response_text: str | None = None
        if session_run_result is not None and shard_id in runnable_shard_ids:
            matching_rows = [row for row in stage_rows if str(row.get('runtime_shard_id') or '').strip() == shard_id]
            primary_row = matching_rows[-1] if matching_rows else None
            primary_runner_row = primary_row
        else:
            primary_row = None
            primary_runner_row = None
        baseline_by_atomic_index = dict(deterministic_baseline_by_shard_id.get(shard_id) or {})
        if response_source_path is not None and response_source_path.exists():
            response_text = response_source_path.read_text(encoding='utf-8')
            payload, validation_errors, validation_metadata, proposal_status = root._evaluate_line_role_response_with_pathology_guard(shard=shard, response_text=response_text, validator=validator, deterministic_baseline_by_atomic_index=baseline_by_atomic_index)
        else:
            payload, validation_errors, validation_metadata, proposal_status = root._evaluate_line_role_response_with_pathology_guard(shard=shard, response_text=None, validator=validator, deterministic_baseline_by_atomic_index=baseline_by_atomic_index)
        same_session_shard_status = dict(dict(line_role_same_session_state_payload.get('shard_status_by_shard_id') or {}).get(shard_id) or {})
        watchdog_retry_attempted = False
        watchdog_retry_status = 'not_attempted'
        repair_attempted = False
        repair_status = 'not_attempted'
        raw_output_status = proposal_status
        final_validation_errors = tuple(validation_errors)
        final_validation_metadata = dict(validation_metadata or {})
        if proposal_status == 'missing_output' and (not current_task_file_missing) and same_session_shard_status.get('validation_errors'):
            proposal_status = 'invalid'
            raw_output_status = 'invalid'
            final_validation_errors = tuple((str(error).strip() for error in same_session_shard_status.get('validation_errors') or [] if str(error).strip()))
            final_validation_metadata = {**dict(final_validation_metadata or {}), 'same_session_handoff_state': dict(same_session_shard_status), 'same_session_handoff_incomplete': not bool(line_role_same_session_state_payload.get('completed'))}
        task_root = shard_dir / shard_id
        task_root.mkdir(parents=True, exist_ok=True)
        if primary_row is not None:
            primary_row['proposal_status'] = proposal_status
            root._annotate_line_role_final_proposal_status(primary_row, final_proposal_status=proposal_status)
            primary_row['runtime_shard_id'] = shard_id
            primary_row['runtime_parent_shard_id'] = shard_id
        if primary_runner_row is not None:
            primary_runner_row['proposal_status'] = proposal_status
            root._annotate_line_role_final_proposal_status(primary_runner_row, final_proposal_status=proposal_status)
            primary_runner_row['runtime_shard_id'] = shard_id
            primary_runner_row['runtime_parent_shard_id'] = shard_id
        if shard_id in runnable_shard_ids and payload is None and (proposal_status == 'missing_output') and (session_run_result is not None) and root._should_attempt_line_role_watchdog_retry(run_result=session_run_result):
            watchdog_retry_attempted = True
            watchdog_retry_live_status_path = task_root / 'watchdog_retry_live_status.json'
            watchdog_retry_run_result = root._run_line_role_watchdog_retry_attempt(runner=runner, worker_root=worker_root, shard=shard, env=env, output_schema_path=output_schema_path, model=model, reasoning_effort=reasoning_effort, original_reason_code=str(session_run_result.supervision_reason_code or ''), original_reason_detail=str(session_run_result.supervision_reason_detail or ''), successful_examples=list(cohort_watchdog_state.snapshot().get('successful_examples') or []), timeout_seconds=timeout_seconds, pipeline_id=pipeline_id, worker_id=assignment.worker_id, live_status_path=watchdog_retry_live_status_path)
            root._finalize_live_status(watchdog_retry_live_status_path, run_result=watchdog_retry_run_result, watchdog_policy=root._STRICT_JSON_WATCHDOG_POLICY)
            (task_root / 'watchdog_retry_events.jsonl').write_text(root._render_codex_events_jsonl(watchdog_retry_run_result.events), encoding='utf-8')
            root._write_runtime_json(task_root / 'watchdog_retry_last_message.json', {'text': watchdog_retry_run_result.response_text})
            root._write_runtime_json(task_root / 'watchdog_retry_usage.json', dict(watchdog_retry_run_result.usage or {}))
            root._write_runtime_json(task_root / 'watchdog_retry_workspace_manifest.json', watchdog_retry_run_result.workspace_manifest())
            watchdog_retry_runner_payload = root._build_line_role_inline_attempt_runner_payload(pipeline_id=pipeline_id, worker_id=assignment.worker_id, shard_id=shard_id, run_result=watchdog_retry_run_result, model=model, reasoning_effort=reasoning_effort, prompt_input_mode='inline_watchdog_retry', events_path=task_root / 'watchdog_retry_events.jsonl', last_message_path=task_root / 'watchdog_retry_last_message.json', usage_path=task_root / 'watchdog_retry_usage.json', live_status_path=watchdog_retry_live_status_path, workspace_manifest_path=task_root / 'watchdog_retry_workspace_manifest.json')
            watchdog_retry_runner_payload['process_payload']['runtime_shard_id'] = shard_id
            watchdog_retry_runner_payload['process_payload']['runtime_parent_shard_id'] = shard_id
            worker_runner_results.append(dict(watchdog_retry_runner_payload))
            watchdog_retry_telemetry = watchdog_retry_runner_payload.get('telemetry')
            watchdog_retry_row_payloads = watchdog_retry_telemetry.get('rows') if isinstance(watchdog_retry_telemetry, dict) else None
            watchdog_retry_primary_row = None
            if isinstance(watchdog_retry_row_payloads, list):
                for row_payload in watchdog_retry_row_payloads:
                    if isinstance(row_payload, dict):
                        stage_rows.append(dict(row_payload))
                if stage_rows:
                    watchdog_retry_primary_row = stage_rows[-1]
            watchdog_retry_primary_runner_row = watchdog_retry_row_payloads[0] if isinstance(watchdog_retry_row_payloads, list) and watchdog_retry_row_payloads and isinstance(watchdog_retry_row_payloads[0], dict) else None
            watchdog_retry_payload, watchdog_retry_validation_errors, watchdog_retry_validation_metadata, watchdog_retry_proposal_status = root._evaluate_line_role_response_with_pathology_guard(shard=shard, response_text=watchdog_retry_run_result.response_text, validator=validator, deterministic_baseline_by_atomic_index=dict(deterministic_baseline_by_shard_id.get(shard_id) or {}))
            watchdog_retry_status = 'recovered' if watchdog_retry_payload is not None and watchdog_retry_proposal_status == 'validated' else 'failed'
            root._write_runtime_json(task_root / 'watchdog_retry_status.json', {'status': watchdog_retry_proposal_status, 'watchdog_retry_status': watchdog_retry_status, 'watchdog_retry_reason_code': str(session_run_result.supervision_reason_code or ''), 'watchdog_retry_reason_detail': str(session_run_result.supervision_reason_detail or ''), 'retry_validation_errors': list(watchdog_retry_validation_errors), 'retry_validation_metadata': dict(watchdog_retry_validation_metadata or {}), 'state': watchdog_retry_run_result.supervision_state or 'completed', 'reason_code': watchdog_retry_run_result.supervision_reason_code, 'reason_detail': watchdog_retry_run_result.supervision_reason_detail, 'retryable': watchdog_retry_run_result.supervision_retryable})
            if watchdog_retry_primary_row is not None:
                watchdog_retry_primary_row['proposal_status'] = watchdog_retry_proposal_status
                root._annotate_line_role_final_proposal_status(watchdog_retry_primary_row, final_proposal_status=watchdog_retry_proposal_status)
                watchdog_retry_primary_row['watchdog_retry_status'] = watchdog_retry_status
                watchdog_retry_primary_row['runtime_shard_id'] = shard_id
                watchdog_retry_primary_row['runtime_parent_shard_id'] = shard_id
            if watchdog_retry_primary_runner_row is not None:
                watchdog_retry_primary_runner_row['proposal_status'] = watchdog_retry_proposal_status
                root._annotate_line_role_final_proposal_status(watchdog_retry_primary_runner_row, final_proposal_status=watchdog_retry_proposal_status)
                watchdog_retry_primary_runner_row['watchdog_retry_status'] = watchdog_retry_status
                watchdog_retry_primary_runner_row['runtime_shard_id'] = shard_id
                watchdog_retry_primary_runner_row['runtime_parent_shard_id'] = shard_id
            if watchdog_retry_payload is not None and watchdog_retry_proposal_status == 'validated':
                payload = watchdog_retry_payload
                final_validation_errors = tuple(watchdog_retry_validation_errors)
                final_validation_metadata = dict(watchdog_retry_validation_metadata or {})
                proposal_status = watchdog_retry_proposal_status
                raw_output_status = watchdog_retry_proposal_status
                if primary_row is not None:
                    root._annotate_line_role_final_proposal_status(primary_row, final_proposal_status=proposal_status)
                if primary_runner_row is not None:
                    root._annotate_line_role_final_proposal_status(primary_runner_row, final_proposal_status=proposal_status)
            else:
                final_validation_metadata = {**(dict(final_validation_metadata) if isinstance(final_validation_metadata, root.Mapping) else {}), 'watchdog_retry_validation_errors': list(watchdog_retry_validation_errors), 'watchdog_retry_validation_metadata': dict(watchdog_retry_validation_metadata or {})}
        row_resolution_payload, row_resolution_metadata = root._build_line_role_row_resolution(shard=shard, validation_metadata=final_validation_metadata)
        payload = row_resolution_payload
        proposal_status = 'validated' if row_resolution_payload is not None else 'invalid'
        if same_session_shard_status and (not current_task_file_missing):
            repair_attempted = bool(same_session_shard_status.get('repair_attempted'))
            repair_status = str(same_session_shard_status.get('repair_status') or '').strip() or repair_status
        elif current_task_file_missing:
            repair_status = 'not_needed'
        elif repair_attempted:
            repair_status = 'repaired' if proposal_status == 'validated' else 'failed'
        if primary_row is not None:
            primary_row['repair_attempted'] = repair_attempted
            primary_row['repair_status'] = repair_status
        if primary_runner_row is not None:
            primary_runner_row['repair_attempted'] = repair_attempted
            primary_runner_row['repair_status'] = repair_status
        final_validation_metadata = {**dict(final_validation_metadata or {}), 'raw_output_status': raw_output_status, 'raw_output_invalid': raw_output_status != 'validated', 'raw_output_missing': raw_output_status == 'missing_output', 'task_file_missing_after_worker_session': current_task_file_missing, 'row_resolution': dict(row_resolution_metadata), **({'fresh_session_recovery': dict(fresh_session_recovery_metadata)} if fresh_session_recovery_metadata else {}), **({'fresh_worker_replacement': dict(fresh_worker_replacement_metadata)} if fresh_worker_replacement_metadata else {})}
        root._write_runtime_json(task_root / 'repair_status.json', {'repair_attempted': repair_attempted, 'status': repair_status, 'repair_status': repair_status, 'repair_request_path': root._relative_runtime_path(run_root, repair_request_path) if repair_request_path.exists() else None, 'repair_state_path': root._relative_runtime_path(run_root, repair_state_path) if repair_state_path.exists() else None, 'output_path': root._relative_runtime_path(run_root, output_path), 'validation_errors': list(final_validation_errors), 'row_resolution': dict(row_resolution_metadata)})
        if primary_row is not None:
            root._annotate_line_role_final_proposal_status(primary_row, final_proposal_status=proposal_status)
        if primary_runner_row is not None:
            root._annotate_line_role_final_proposal_status(primary_runner_row, final_proposal_status=proposal_status)
        task_status_rows.append(root._build_line_role_shard_status_row(shard=shard, worker_id=assignment.worker_id, state='repair_recovered' if proposal_status == 'validated' and repair_status == 'repaired' else 'validated' if proposal_status == 'validated' else 'repair_failed' if repair_attempted else 'invalid_output', last_attempt_type='repair' if repair_attempted else 'fresh_worker_replacement' if bool(fresh_worker_replacement_metadata.get('fresh_worker_replacement_attempted')) else 'fresh_session_recovery' if bool(fresh_session_recovery_metadata.get('fresh_session_recovery_attempted')) else 'watchdog_retry' if watchdog_retry_attempted else 'resume_existing_output' if shard_id in resumed_output_path_by_shard_id and shard_id not in runnable_shard_ids else 'main_worker', output_path=response_source_path, repair_path=None, validation_errors=final_validation_errors, validation_metadata=final_validation_metadata, row_resolution_metadata=row_resolution_metadata, repair_attempted=repair_attempted, repair_status=repair_status, resumed_from_existing_output=shard_id in resumed_output_path_by_shard_id and shard_id not in runnable_shard_ids, fresh_session_recovery_metadata=fresh_session_recovery_metadata, transport=root.TASKFILE_TRANSPORT))
        normalized_outcome = root._normalize_line_role_shard_outcome(run_result=session_run_result, proposal_status=proposal_status, watchdog_retry_status=watchdog_retry_status, repair_status=repair_status, resumed_from_existing_outputs=shard_id in resumed_output_path_by_shard_id and shard_id not in runnable_shard_ids, row_resolution_metadata=row_resolution_metadata, fresh_session_recovery_metadata=fresh_session_recovery_metadata)
        shard_root = shard_dir / shard.shard_id
        if session_run_result is None and (not (shard_root / 'live_status.json').exists()):
            root._write_runtime_json(shard_root / 'live_status.json', {'state': 'completed', 'reason_code': 'resume_existing_outputs' if shard_id in resumed_output_path_by_shard_id else 'no_shards_assigned', 'reason_detail': 'all canonical line-role shard outputs were already durable on disk' if shard_id in resumed_output_path_by_shard_id else 'worker had no runnable canonical line-role shards', 'retryable': False, 'watchdog_policy': 'taskfile_v1'})
        proposal_path = run_root / artifacts['proposals_dir'] / f'{shard.shard_id}.json'
        valid = payload is not None and proposal_status == 'validated'
        root._write_runtime_json(proposal_path, {'shard_id': shard.shard_id, 'worker_id': assignment.worker_id, 'payload': payload if valid else None, 'validation_errors': list(final_validation_errors), 'validation_metadata': dict(final_validation_metadata or {}), 'watchdog_retry_attempted': watchdog_retry_attempted, 'watchdog_retry_status': watchdog_retry_status, 'repair_attempted': repair_attempted, 'repair_status': repair_status, **dict(fresh_session_recovery_metadata), **dict(fresh_worker_replacement_metadata)})
        root._write_runtime_json(shard_root / 'proposal.json', payload if valid else {'error': proposal_status, 'validation_errors': list(final_validation_errors), 'validation_metadata': dict(final_validation_metadata or {})})
        shard_state = normalized_outcome.get('state')
        shard_reason_code = normalized_outcome.get('reason_code')
        shard_reason_detail = normalized_outcome.get('reason_detail')
        shard_retryable = bool(normalized_outcome.get('retryable'))
        for row in stage_rows:
            if not isinstance(row, dict):
                continue
            if str(row.get('task_id') or '').strip() != shard.shard_id:
                continue
            if str(row.get('prompt_input_mode') or '').strip() != 'taskfile':
                continue
            root._annotate_line_role_final_outcome_row(row, normalized_outcome=normalized_outcome, repair_attempted=repair_attempted, repair_status=repair_status)
        for payload_row in worker_runner_results:
            if not isinstance(payload_row, dict):
                continue
            process_payload = payload_row.get('process_payload')
            if not isinstance(process_payload, root.Mapping):
                continue
            if str(process_payload.get('runtime_parent_shard_id') or '').strip() != shard.shard_id:
                continue
            if str(process_payload.get('prompt_input_mode') or '').strip() != 'taskfile':
                continue
            root._apply_line_role_final_outcome_to_runner_payload(payload_row, shard_id=shard.shard_id, normalized_outcome=normalized_outcome, repair_attempted=repair_attempted, repair_status=repair_status)
        root._write_runtime_json(shard_root / 'status.json', {'status': proposal_status, 'validation_errors': list(final_validation_errors), 'validation_metadata': dict(final_validation_metadata or {}), 'runtime_mode': root.DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'watchdog_retry_attempted': watchdog_retry_attempted, 'watchdog_retry_status': watchdog_retry_status, 'repair_attempted': repair_attempted, 'repair_status': repair_status, **dict(fresh_session_recovery_metadata), **dict(fresh_worker_replacement_metadata), 'finalization_path': normalized_outcome.get('finalization_path'), 'state': shard_state, 'reason_code': shard_reason_code, 'reason_detail': shard_reason_detail, 'retryable': shard_retryable, 'raw_supervision_state': normalized_outcome.get('raw_supervision_state'), 'raw_supervision_reason_code': normalized_outcome.get('raw_supervision_reason_code'), 'raw_supervision_reason_detail': normalized_outcome.get('raw_supervision_reason_detail'), 'raw_supervision_retryable': normalized_outcome.get('raw_supervision_retryable')})
        shard_runner_rows = [dict(row) for row in stage_rows if str(row.get('task_id') or '').strip() == shard.shard_id]
        shard_runner_payload = root._aggregate_line_role_worker_runner_payload(pipeline_id=pipeline_id, worker_runs=[payload_row for payload_row in worker_runner_results if str((payload_row.get('process_payload') or {} if isinstance(payload_row, dict) else {}).get('runtime_parent_shard_id') or '').strip() == shard.shard_id])
        shard_runner_payload['telemetry'] = {'rows': shard_runner_rows, 'summary': root._summarize_direct_rows(shard_runner_rows)}
        shard_runner_payload['response_text'] = root.json.dumps(payload, sort_keys=True)
        shard_runner_payload['subprocess_exit_code'] = session_run_result.subprocess_exit_code if session_run_result is not None else 0
        shard_runner_payload['turn_failed_message'] = session_run_result.turn_failed_message if session_run_result is not None else None
        shard_runner_payload['final_supervision_state'] = normalized_outcome.get('state')
        shard_runner_payload['final_supervision_reason_code'] = normalized_outcome.get('reason_code')
        shard_runner_payload['final_supervision_reason_detail'] = normalized_outcome.get('reason_detail')
        shard_runner_payload['final_supervision_retryable'] = normalized_outcome.get('retryable')
        shard_runner_payload['finalization_path'] = normalized_outcome.get('finalization_path')
        shard_runner_payload['raw_supervision_state'] = normalized_outcome.get('raw_supervision_state')
        shard_runner_payload['raw_supervision_reason_code'] = normalized_outcome.get('raw_supervision_reason_code')
        shard_runner_payload['raw_supervision_reason_detail'] = normalized_outcome.get('raw_supervision_reason_detail')
        shard_runner_payload['raw_supervision_retryable'] = normalized_outcome.get('raw_supervision_retryable')
        if fresh_session_recovery_metadata:
            shard_runner_payload.update(dict(fresh_session_recovery_metadata))
        if fresh_worker_replacement_metadata:
            shard_runner_payload.update(dict(fresh_worker_replacement_metadata))
        runner_results_by_shard_id[shard.shard_id] = shard_runner_payload
        if proposal_status != 'validated' or shard_state != 'completed':
            worker_failure_count += 1
            worker_failures.append({'worker_id': assignment.worker_id, 'shard_id': shard.shard_id, 'reason': root._failure_reason_from_run_result(run_result=session_run_result, proposal_status=proposal_status) if session_run_result is not None else proposal_status, 'validation_errors': list(final_validation_errors), 'state': shard_state, 'reason_code': shard_reason_code, **dict(fresh_session_recovery_metadata), **dict(fresh_worker_replacement_metadata)})
        else:
            worker_proposal_count += 1
            if session_run_result is not None:
                cohort_watchdog_state.record_validated_result(duration_ms=session_run_result.duration_ms, example_payload=root._build_line_role_watchdog_example(shard=shard, payload=payload))
        worker_proposals.append(root.ShardProposalV1(shard_id=shard.shard_id, worker_id=assignment.worker_id, status=proposal_status, proposal_path=root._relative_runtime_path(run_root, proposal_path), payload=payload if valid else None, validation_errors=tuple(final_validation_errors), metadata=dict(final_validation_metadata or {})))
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)
    same_session_repair_rewrite_count = int(
        line_role_same_session_state_payload.get('same_session_repair_rewrite_count')
        or 0
    )
    worker_runner_payload = root._aggregate_line_role_worker_runner_payload(pipeline_id=pipeline_id, worker_runs=worker_runner_results)
    worker_runner_payload['same_session_repair_rewrite_count'] = same_session_repair_rewrite_count
    worker_runner_payload['fresh_session_retry_count'] = fresh_session_retry_count
    worker_runner_payload['fresh_session_retry_status'] = fresh_session_retry_status
    if fresh_session_recovery_metadata:
        worker_runner_payload.update(dict(fresh_session_recovery_metadata))
    worker_runner_payload['fresh_worker_replacement_count'] = fresh_worker_replacement_count
    worker_runner_payload['fresh_worker_replacement_status'] = fresh_worker_replacement_status
    if fresh_worker_replacement_metadata:
        worker_runner_payload.update(dict(fresh_worker_replacement_metadata))
    worker_runner_payload['recovery_policy'] = root.taskfile_recovery_policy_summary(stage_key=root.LINE_ROLE_POLICY_STAGE_KEY)
    worker_runner_payload['repair_recovery_policy'] = root.build_followup_budget_summary(
        stage_key=root.LINE_ROLE_POLICY_STAGE_KEY,
        transport=root.TASKFILE_TRANSPORT,
        spent_attempts_by_kind={
            root.FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE: same_session_repair_rewrite_count,
            root.FOLLOWUP_KIND_FRESH_SESSION_RETRY: fresh_session_retry_count,
            root.FOLLOWUP_KIND_FRESH_WORKER_REPLACEMENT: fresh_worker_replacement_count,
        },
    )
    root._write_runtime_json(worker_root / 'status.json', worker_runner_payload)
    return root._DirectLineRoleWorkerResult(report=root.WorkerExecutionReportV1(worker_id=assignment.worker_id, shard_ids=assignment.shard_ids, workspace_root=root._relative_runtime_path(run_root, worker_root), status='ok' if worker_failure_count == 0 else 'partial_failure', proposal_count=worker_proposal_count, failure_count=worker_failure_count, runtime_mode_audit={'mode': root.DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'status': 'ok', 'output_schema_enforced': False, 'tool_affordances_requested': True}, runner_result=worker_runner_payload, metadata={'in_dir': root._relative_runtime_path(run_root, in_dir), 'debug_dir': root._relative_runtime_path(run_root, debug_dir), 'hints_dir': root._relative_runtime_path(run_root, hints_dir), 'out_dir': root._relative_runtime_path(run_root, out_dir), 'shards_dir': root._relative_runtime_path(run_root, shard_dir), 'log_dir': root._relative_runtime_path(run_root, logs_dir), 'task_file_guardrail': dict(task_file_guardrail or {}), 'same_session_repair_rewrite_count': same_session_repair_rewrite_count, 'fresh_session_retry_count': fresh_session_retry_count, 'fresh_session_retry_status': fresh_session_retry_status, **dict(fresh_session_recovery_metadata), 'fresh_worker_replacement_count': fresh_worker_replacement_count, 'fresh_worker_replacement_status': fresh_worker_replacement_status, **dict(fresh_worker_replacement_metadata)}), proposals=tuple(worker_proposals), failures=tuple(worker_failures), stage_rows=tuple(stage_rows), task_status_rows=tuple(task_status_rows), runner_results_by_shard_id=dict(runner_results_by_shard_id))

def _run_line_role_direct_worker_assignment_v1(*, run_root: root.Path, assignment: root.WorkerAssignmentV1, artifacts: dict[str, str], shard_by_id: dict[str, root.ShardManifestEntryV1], debug_payload_by_shard_id: root.Mapping[str, root.Any], deterministic_baseline_by_shard_id: root.Mapping[str, root.Mapping[int, root.CanonicalLineRolePrediction]], runner: root.CodexExecRunner, pipeline_id: str, env: dict[str, str], model: str | None, reasoning_effort: str | None, settings: root.Mapping[str, root.Any], output_schema_path: root.Path | None, timeout_seconds: int, cohort_watchdog_state: root._LineRoleCohortWatchdogState, shard_completed_callback: root.Callable[..., None] | None, prompt_state: '_PromptArtifactState' | None, validator: root.Callable[[root.ShardManifestEntryV1, dict[str, root.Any]], tuple[bool, root.Sequence[str], dict[str, root.Any] | None]]) -> root._DirectLineRoleWorkerResult:
    worker_root = root.Path(assignment.workspace_root)
    in_dir = worker_root / 'in'
    debug_dir = worker_root / 'debug'
    hints_dir = worker_root / 'hints'
    shard_dir = worker_root / 'shards'
    logs_dir = worker_root / 'logs'
    in_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)
    hints_dir.mkdir(parents=True, exist_ok=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    assigned_shards = [shard_by_id[shard_id] for shard_id in assignment.shard_ids]
    root._write_runtime_json(worker_root / 'assigned_shards.json', [root._line_role_asdict(shard) for shard in assigned_shards])
    if root.resolve_codex_exec_style_value(settings.get('codex_exec_style')) == root.CODEX_EXEC_STYLE_INLINE_JSON_V1:
        return root._run_line_role_structured_assignment_v1(run_root=run_root, assignment=assignment, artifacts=artifacts, assigned_shards=assigned_shards, worker_root=worker_root, in_dir=in_dir, debug_dir=debug_dir, hints_dir=hints_dir, shard_dir=shard_dir, logs_dir=logs_dir, debug_payload_by_shard_id=debug_payload_by_shard_id, deterministic_baseline_by_shard_id=deterministic_baseline_by_shard_id, runner=runner, pipeline_id=pipeline_id, env=env, model=model, reasoning_effort=reasoning_effort, settings=settings, output_schema_path=output_schema_path, timeout_seconds=timeout_seconds, cohort_watchdog_state=cohort_watchdog_state, shard_completed_callback=shard_completed_callback, prompt_state=prompt_state, validator=validator)
    return root._run_line_role_taskfile_assignment_v1(run_root=run_root, assignment=assignment, artifacts=artifacts, assigned_shards=assigned_shards, worker_root=worker_root, in_dir=in_dir, debug_dir=debug_dir, hints_dir=hints_dir, shard_dir=shard_dir, logs_dir=logs_dir, debug_payload_by_shard_id=debug_payload_by_shard_id, deterministic_baseline_by_shard_id=deterministic_baseline_by_shard_id, runner=runner, pipeline_id=pipeline_id, env=env, model=model, reasoning_effort=reasoning_effort, settings=settings, output_schema_path=output_schema_path, timeout_seconds=timeout_seconds, cohort_watchdog_state=cohort_watchdog_state, shard_completed_callback=shard_completed_callback, prompt_state=prompt_state, validator=validator)

def _line_role_structured_input_rows(
    shard: root.ShardManifestEntryV1,
) -> list[tuple[int, str]]:
    rows_payload = root._coerce_mapping_dict(shard.input_payload).get("rows") or []
    rows: list[tuple[int, str]] = []
    for row in rows_payload:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        rows.append((int(row[0]), str(row[1] or "")))
    return rows


def _line_role_structured_row_id(index: int) -> str:
    return f"r{index + 1:02d}"


def _line_role_structured_packet_rows(shard: root.ShardManifestEntryV1) -> list[str]:
    rows: list[str] = []
    for _atomic_index, text in _line_role_structured_input_rows(shard):
        rows.append(text)
    return rows


def _line_role_structured_context_rows(
    *,
    shard: root.ShardManifestEntryV1,
    key: str,
) -> list[str]:
    rows_payload = root._coerce_mapping_dict(shard.input_payload).get(key) or []
    rows: list[str] = []
    for row in rows_payload:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        rows.append(str(row[1] or ""))
    return rows


def _build_line_role_structured_packet(*, shard: root.ShardManifestEntryV1, packet_kind: str, validation_errors: root.Sequence[str] | None=None, validation_metadata: root.Mapping[str, root.Any] | None=None, deterministic_baseline_by_atomic_index: root.Mapping[int, root.CanonicalLineRolePrediction] | None=None) -> dict[str, root.Any]:
    del validation_metadata
    del deterministic_baseline_by_atomic_index
    payload: dict[str, root.Any] = {
        "schema_version": "line_role_structured_packet.v2",
        "stage_key": "line_role",
        "packet_kind": str(packet_kind or "initial"),
        "shard_id": shard.shard_id,
        "rows": root._line_role_structured_packet_rows(shard),
    }
    context_before_rows = _line_role_structured_context_rows(
        shard=shard,
        key="context_before_rows",
    )
    if context_before_rows:
        payload["context_before_rows"] = context_before_rows
    context_after_rows = _line_role_structured_context_rows(
        shard=shard,
        key="context_after_rows",
    )
    if context_after_rows:
        payload["context_after_rows"] = context_after_rows
    if validation_errors:
        payload["validation_errors"] = [str(error).strip() for error in validation_errors if str(error).strip()]
    return payload


def _build_line_role_structured_prompt_packet(
    packet: root.Mapping[str, root.Any],
) -> dict[str, root.Any]:
    prompt_packet: dict[str, root.Any] = {
        "rows": list(packet.get("rows") or []),
    }
    context_before_rows = list(packet.get("context_before_rows") or [])
    if context_before_rows:
        prompt_packet["context_before_rows"] = context_before_rows
    context_after_rows = list(packet.get("context_after_rows") or [])
    if context_after_rows:
        prompt_packet["context_after_rows"] = context_after_rows
    validation_errors = [
        str(error).strip()
        for error in (packet.get("validation_errors") or [])
        if str(error).strip()
    ]
    if validation_errors:
        prompt_packet["validation_errors"] = validation_errors
    return prompt_packet


def _build_line_role_structured_prompt(*, packet: root.Mapping[str, root.Any]) -> str:
    allowed_labels = ", ".join(root.CANONICAL_LINE_ROLE_ALLOWED_LABELS)
    shared_contract = root.build_line_role_shared_contract_block()
    packet_kind = str(packet.get("packet_kind") or "initial").strip()
    repair_note = (
        "This is a repair packet. Only answer the rows shown here; previously accepted rows are already fixed.\n\n"
        if packet_kind != "initial"
        else ""
    )
    context_note = (
        "If nearby context rows are shown, use them only to interpret the owned rows; do not label the context rows themselves.\n- "
        if (packet.get("context_before_rows") or packet.get("context_after_rows"))
        else ""
    )
    owned_rows = packet.get("rows") or []
    owned_row_count = len(owned_rows) if isinstance(owned_rows, list) else 0
    owned_row_count_note = f"This packet has {owned_row_count} owned row(s) in reading order."
    prompt_packet = _build_line_role_structured_prompt_packet(packet)
    return (
        "Return JSON only.\n\n"
        "Review the canonical line-role packet and respond with one JSON object shaped like:\n"
        '{"labels":["<ALLOWED_LABEL>","<ALLOWED_LABEL>"]}\n\n'
        "Shared labeling contract:\n"
        + shared_contract
        + "\n\n"
        + "Rules:\n"
        f"- Allowed labels: {allowed_labels}\n"
        f"- {owned_row_count_note}\n"
        f"- Return exactly {owned_row_count} label(s): one for each owned row shown in `rows`.\n"
        "- `rows` is an ordered array of raw text strings.\n"
        "- Treat `rows` as one contiguous ordered shard slice, not as isolated examples.\n"
        "- Label in one pass, but use the surrounding owned rows to understand local transitions and resets before deciding each row.\n"
        "- Keep the whole shard sequence in mind while labeling, especially around recipe starts, yields, variants, and fresh-title resets.\n"
        "- Keep label order exactly aligned with the packet `rows` order.\n"
        "- The first label applies to `rows[0]`, the second label applies to `rows[1]`, and so on.\n"
        "- Finish the full owned-row list; do not stop early.\n"
        "- Do not copy the placeholder schema literally; replace it with the full ordered label list for this shard.\n"
        f"- {context_note}Do not label any `context_before_rows` or `context_after_rows`; they are reference-only.\n"
        "- Return one JSON object with only the top-level key `labels`.\n"
        "- Do not include commentary, markdown, or extra keys.\n\n"
        + repair_note
        + "Packet JSON:\n"
        + root.json.dumps(prompt_packet, indent=2, ensure_ascii=False)
        + "\n"
    )


def _translate_line_role_structured_labels_payload(
    *,
    labels_payload: root.Sequence[root.Any],
    ordered_atomic_indices: root.Sequence[int],
) -> tuple[list[dict[str, root.Any]], dict[str, root.Any]]:
    translated_rows: list[dict[str, root.Any]] = []
    for index, label_value in enumerate(labels_payload):
        row_payload: dict[str, root.Any] = {"label": label_value}
        if index < len(ordered_atomic_indices):
            row_payload["atomic_index"] = int(ordered_atomic_indices[index])
        translated_rows.append(row_payload)
    return translated_rows, {
        "ordered_label_vector": {
            "applied": True,
            "returned_label_count": len(labels_payload),
            "expected_row_count": len(ordered_atomic_indices),
        }
    }


def _evaluate_line_role_structured_response(
    *,
    shard: root.ShardManifestEntryV1,
    response_text: str | None,
    deterministic_baseline_by_atomic_index: root.Mapping[int, root.CanonicalLineRolePrediction],
    validator: root.Callable[[root.ShardManifestEntryV1, dict[str, root.Any]], tuple[bool, root.Sequence[str], dict[str, root.Any] | None]],
) -> tuple[dict[str, root.Any] | None, tuple[str, ...], dict[str, root.Any], str]:
    cleaned_response_text = str(response_text or "").strip()
    if not cleaned_response_text:
        return None, ("missing_output_file",), {}, "missing_output"
    try:
        parsed_payload = root.json.loads(cleaned_response_text)
    except root.json.JSONDecodeError as exc:
        return None, ("response_json_invalid",), {"parse_error": str(exc)}, "invalid"
    if not isinstance(parsed_payload, dict):
        return (
            None,
            ("response_not_json_object",),
            {"response_type": type(parsed_payload).__name__},
            "invalid",
        )
    labels_payload = parsed_payload.get("labels")
    if not isinstance(labels_payload, list):
        return None, ("labels_missing_or_not_a_list",), {}, "invalid"
    ordered_atomic_indices = [int(value) for value in shard.owned_ids]
    translated_rows, response_contract_metadata = (
        _translate_line_role_structured_labels_payload(
            labels_payload=labels_payload,
            ordered_atomic_indices=ordered_atomic_indices,
        )
    )
    response_contract_error_list: list[str] = []
    if len(labels_payload) != len(ordered_atomic_indices):
        response_contract_error_list.append("wrong_label_count")
        response_contract_metadata = {
            **response_contract_metadata,
            "label_count_mismatch": {
                "expected_row_count": len(ordered_atomic_indices),
                "returned_label_count": len(labels_payload),
            },
        }
    extra_top_level_keys = sorted(
        key for key in parsed_payload.keys() if str(key).strip() != "labels"
    )
    if extra_top_level_keys:
        response_contract_error_list.append("extra_top_level_keys")
        response_contract_metadata = {
            **response_contract_metadata,
            "extra_top_level_keys": extra_top_level_keys,
        }
    response_contract_errors = tuple(dict.fromkeys(response_contract_error_list))
    validation_metadata: dict[str, root.Any] = {}
    validation_errors: tuple[str, ...] = ()
    if translated_rows:
        valid, validation_errors, validation_metadata_raw = validator(
            shard,
            {"rows": translated_rows},
        )
        del valid
        validation_metadata = dict(validation_metadata_raw or {})
    accepted_atomic_indices = [
        int(value)
        for value in (validation_metadata.get("accepted_atomic_indices") or [])
        if str(value).strip()
    ]
    unresolved_atomic_indices = [
        atomic_index
        for atomic_index in [int(value) for value in shard.owned_ids]
        if atomic_index not in set(accepted_atomic_indices)
    ]
    merged_metadata = {
        **validation_metadata,
        **response_contract_metadata,
        "expected_atomic_indices": [int(value) for value in shard.owned_ids],
        "accepted_atomic_indices": accepted_atomic_indices,
        "unresolved_atomic_indices": unresolved_atomic_indices,
    }
    merged_errors = tuple(
        dict.fromkeys(
            [
                *[str(error).strip() for error in response_contract_errors if str(error).strip()],
                *[str(error).strip() for error in validation_errors if str(error).strip()],
            ]
        )
    )
    proposal_status = "validated" if not merged_errors and not unresolved_atomic_indices else "invalid"
    final_validation_errors, final_validation_metadata, final_proposal_status = (
        root._apply_line_role_semantic_guard(
            shard=shard,
            validation_errors=merged_errors,
            validation_metadata=merged_metadata,
            proposal_status=proposal_status,
            payload={"rows": translated_rows},
            deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
        )
    )
    return parsed_payload, final_validation_errors, final_validation_metadata, final_proposal_status

def _build_line_role_repair_shard(*, shard: root.ShardManifestEntryV1, unresolved_atomic_indices: root.Sequence[int]) -> root.ShardManifestEntryV1:
    unresolved_set = {int(value) for value in unresolved_atomic_indices}
    rows = [list(row) for row in root._coerce_mapping_dict(shard.input_payload).get('rows') or [] if isinstance(row, (list, tuple)) and row and (int(row[0]) in unresolved_set)]
    return root.ShardManifestEntryV1(shard_id=shard.shard_id, owned_ids=tuple((str(value) for value in unresolved_atomic_indices)), evidence_refs=tuple(shard.evidence_refs), input_payload={'rows': rows}, input_text=shard.input_text, metadata=dict(shard.metadata or {}))

def _merge_line_role_validation_metadata(*, original_shard: root.ShardManifestEntryV1, initial_metadata: root.Mapping[str, root.Any], repair_metadata: root.Mapping[str, root.Any] | None=None) -> dict[str, root.Any]:
    accepted_rows: list[dict[str, root.Any]] = [dict(row) for row in initial_metadata.get('accepted_rows') or [] if isinstance(row, root.Mapping)]
    if repair_metadata:
        accepted_rows.extend((dict(row) for row in repair_metadata.get('accepted_rows') or [] if isinstance(row, root.Mapping)))
    accepted_by_atomic_index = {int(row['atomic_index']): dict(row) for row in accepted_rows if row.get('atomic_index') is not None and str(row.get('atomic_index')).strip()}
    ordered_atomic_indices = [int(value) for value in original_shard.owned_ids]
    merged_rows = [accepted_by_atomic_index[atomic_index] for atomic_index in ordered_atomic_indices if atomic_index in accepted_by_atomic_index]
    accepted_atomic_indices = [
        int(row['atomic_index'])
        for row in merged_rows
        if row.get('atomic_index') is not None and str(row.get('atomic_index')).strip()
    ]
    accepted_atomic_index_set = set(accepted_atomic_indices)
    unresolved_atomic_indices = [
        atomic_index
        for atomic_index in ordered_atomic_indices
        if atomic_index not in accepted_atomic_index_set
    ]
    accepted_row_ids = [
        _line_role_structured_row_id(index)
        for index, atomic_index in enumerate(ordered_atomic_indices)
        if atomic_index in accepted_atomic_index_set
    ]
    return {
        **dict(initial_metadata or {}),
        **dict(repair_metadata or {}),
        'owned_row_count': len(ordered_atomic_indices),
        'expected_atomic_indices': ordered_atomic_indices,
        'accepted_rows': merged_rows,
        'accepted_atomic_indices': accepted_atomic_indices,
        'accepted_row_ids': accepted_row_ids,
        'returned_row_ids': accepted_row_ids,
        'unresolved_atomic_indices': unresolved_atomic_indices,
        'validated_row_count': len(accepted_atomic_indices),
    }

def _run_line_role_structured_assignment_v1(*, run_root: root.Path, assignment: root.WorkerAssignmentV1, artifacts: dict[str, str], assigned_shards: root.Sequence[root.ShardManifestEntryV1], worker_root: root.Path, in_dir: root.Path, debug_dir: root.Path, hints_dir: root.Path, shard_dir: root.Path, logs_dir: root.Path, debug_payload_by_shard_id: root.Mapping[str, root.Any], deterministic_baseline_by_shard_id: root.Mapping[str, root.Mapping[int, root.CanonicalLineRolePrediction]], runner: root.CodexExecRunner, pipeline_id: str, env: dict[str, str], model: str | None, reasoning_effort: str | None, settings: root.Mapping[str, root.Any], output_schema_path: root.Path | None, timeout_seconds: int, cohort_watchdog_state: root._LineRoleCohortWatchdogState, shard_completed_callback: root.Callable[..., None] | None, prompt_state: '_PromptArtifactState' | None, validator: root.Callable[[root.ShardManifestEntryV1, dict[str, root.Any]], tuple[bool, root.Sequence[str], dict[str, root.Any] | None]]) -> root._DirectLineRoleWorkerResult:
    del debug_payload_by_shard_id, in_dir, debug_dir, hints_dir, logs_dir
    worker_failure_count = 0
    worker_proposal_count = 0
    worker_runner_results: list[dict[str, root.Any]] = []
    worker_failures: list[dict[str, root.Any]] = []
    worker_proposals: list[root.ShardProposalV1] = []
    stage_rows: list[dict[str, root.Any]] = []
    runner_results_by_shard_id: dict[str, dict[str, root.Any]] = {}
    task_status_rows: list[dict[str, root.Any]] = []
    for shard in assigned_shards:
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
        preflight_failure = root._preflight_line_role_shard(shard)
        if preflight_failure is not None:
            reason_code = str(preflight_failure.get('reason_code') or 'preflight_rejected')
            reason_detail = str(preflight_failure.get('reason_detail') or '')
            proposal_path = run_root / artifacts['proposals_dir'] / f'{shard.shard_id}.json'
            root._write_runtime_json(proposal_path, {'shard_id': shard.shard_id, 'worker_id': assignment.worker_id, 'payload': None, 'validation_errors': [reason_code], 'validation_metadata': {}})
            worker_failure_count += 1
            worker_failures.append({'worker_id': assignment.worker_id, 'shard_id': shard.shard_id, 'reason': 'preflight_rejected', 'validation_errors': [reason_code], 'state': 'preflight_rejected', 'reason_code': reason_code})
            worker_proposals.append(root.ShardProposalV1(shard_id=shard.shard_id, worker_id=assignment.worker_id, status='preflight_rejected', proposal_path=root._relative_runtime_path(run_root, proposal_path), payload=None, validation_errors=(reason_code,), metadata={}))
            continue
        session_root = shard_root / 'structured_session'
        session_root.mkdir(parents=True, exist_ok=True)
        packet_path = session_root / 'initial_packet.json'
        prompt_path = session_root / 'prompt_initial.txt'
        response_path = session_root / 'response_initial.json'
        events_path = session_root / 'events_initial.jsonl'
        last_message_path = session_root / 'last_message_initial.json'
        usage_path = session_root / 'usage_initial.json'
        workspace_manifest_path = session_root / 'workspace_manifest_initial.json'
        stdout_path = session_root / 'stdout_initial.txt'
        stderr_path = session_root / 'stderr_initial.txt'
        baseline_by_atomic_index = dict(deterministic_baseline_by_shard_id.get(shard.shard_id) or {})
        initial_packet = root._build_line_role_structured_packet(
            shard=shard,
            packet_kind='initial',
            deterministic_baseline_by_atomic_index=baseline_by_atomic_index,
        )
        packet_path.write_text(root.json.dumps(initial_packet, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        prompt_text = root._build_line_role_structured_prompt(packet=initial_packet)
        prompt_path.write_text(prompt_text, encoding='utf-8')
        if prompt_state is not None:
            prompt_state.write_prompt(phase_key=str((shard.metadata or {}).get('phase_key') or 'line_role').strip(), prompt_stem=str((shard.metadata or {}).get('prompt_stem') or 'prompt').strip(), prompt_index=int((shard.metadata or {}).get('prompt_index') or 0), prompt_text=prompt_text)
        initial_run_result = runner.run_packet_worker(prompt_text=prompt_text, input_payload={**root._coerce_mapping_dict(shard.input_payload), 'shard_id': shard.shard_id, 'owned_ids': list(shard.owned_ids), 'packet_kind': 'initial', 'stage_key': 'line_role', 'structured_packet_rows': list(initial_packet.get('rows') or [])}, working_dir=session_root, env=env, output_schema_path=output_schema_path, model=model, reasoning_effort=reasoning_effort, timeout_seconds=timeout_seconds, workspace_task_label='canonical line-role structured session', persist_session=True)
        execution_workspace = root.Path(initial_run_result.execution_working_dir or session_root)
        root.initialize_structured_session_lineage(worker_root=session_root, assignment_id=f'{assignment.worker_id}:{shard.shard_id}', execution_working_dir=execution_workspace)
        response_path.write_text(str(initial_run_result.response_text or ''), encoding='utf-8')
        events_path.write_text(root._render_codex_events_jsonl(initial_run_result.events), encoding='utf-8')
        root._write_runtime_json(last_message_path, {'text': initial_run_result.response_text})
        root._write_runtime_json(usage_path, dict(initial_run_result.usage or {}))
        root._write_runtime_json(workspace_manifest_path, initial_run_result.workspace_manifest())
        root._write_optional_runtime_text(stdout_path, initial_run_result.stdout_text)
        root._write_optional_runtime_text(stderr_path, initial_run_result.stderr_text)
        root.record_structured_session_turn(worker_root=session_root, execution_working_dir=execution_workspace, turn_kind='initial', packet_path=packet_path, prompt_path=prompt_path, response_path=response_path)
        initial_runner_payload = root._build_line_role_inline_attempt_runner_payload(pipeline_id=pipeline_id, worker_id=assignment.worker_id, shard_id=shard.shard_id, run_result=initial_run_result, model=model, reasoning_effort=reasoning_effort, prompt_input_mode='structured_session_initial', events_path=events_path, last_message_path=last_message_path, usage_path=usage_path, workspace_manifest_path=workspace_manifest_path, stdout_path=stdout_path, stderr_path=stderr_path)
        worker_runner_results.append(initial_runner_payload)
        runner_results_by_shard_id[shard.shard_id] = initial_runner_payload
        _initial_payload, initial_validation_errors, initial_validation_metadata, proposal_status = _evaluate_line_role_structured_response(
            shard=shard,
            response_text=initial_run_result.response_text,
            deterministic_baseline_by_atomic_index=baseline_by_atomic_index,
            validator=validator,
        )
        final_validation_errors = tuple(initial_validation_errors)
        final_validation_metadata = dict(initial_validation_metadata or {})
        current_validation_errors = tuple(initial_validation_errors)
        current_validation_metadata = dict(initial_validation_metadata or {})
        repair_attempted = False
        repair_status = 'not_attempted'
        latest_repair_packet_path: root.Path | None = None
        unresolved_atomic_indices = [
            int(value)
            for value in (
                current_validation_metadata.get('unresolved_atomic_indices')
                or [int(value) for value in shard.owned_ids]
            )
            if str(value).strip()
        ]
        should_attempt_repair = root._should_attempt_line_role_repair(
            proposal_status=proposal_status,
            validation_errors=initial_validation_errors,
        ) or (
            proposal_status == 'invalid' and bool(unresolved_atomic_indices)
        )
        if should_attempt_repair:
            repair_followup_limit = root.structured_repair_followup_limit(stage_key=root.LINE_ROLE_POLICY_STAGE_KEY)
            for repair_attempt_index in range(1, repair_followup_limit + 1):
                if not unresolved_atomic_indices:
                    break
                repair_attempted = True
                repair_shard = root._build_line_role_repair_shard(shard=shard, unresolved_atomic_indices=unresolved_atomic_indices)
                repair_packet = root._build_line_role_structured_packet(
                    shard=repair_shard,
                    packet_kind='repair',
                    validation_errors=current_validation_errors,
                    validation_metadata=current_validation_metadata,
                    deterministic_baseline_by_atomic_index=baseline_by_atomic_index,
                )
                repair_packet_path = session_root / f'repair_packet_{repair_attempt_index:02d}.json'
                repair_prompt_path = session_root / f'repair_prompt_{repair_attempt_index:02d}.txt'
                repair_response_path = session_root / f'repair_response_{repair_attempt_index:02d}.json'
                repair_events_path = session_root / f'repair_events_{repair_attempt_index:02d}.jsonl'
                repair_last_message_path = session_root / f'repair_last_message_{repair_attempt_index:02d}.json'
                repair_usage_path = session_root / f'repair_usage_{repair_attempt_index:02d}.json'
                repair_workspace_manifest_path = session_root / f'repair_workspace_manifest_{repair_attempt_index:02d}.json'
                repair_stdout_path = session_root / f'repair_stdout_{repair_attempt_index:02d}.txt'
                repair_stderr_path = session_root / f'repair_stderr_{repair_attempt_index:02d}.txt'
                latest_repair_packet_path = repair_packet_path
                repair_packet_path.write_text(root.json.dumps(repair_packet, indent=2, sort_keys=True) + '\n', encoding='utf-8')
                repair_prompt_text = root._build_line_role_structured_prompt(packet=repair_packet)
                repair_prompt_path.write_text(repair_prompt_text, encoding='utf-8')
                root.assert_structured_session_can_resume(worker_root=session_root, execution_working_dir=execution_workspace)
                repair_run_result = runner.run_packet_worker(prompt_text=repair_prompt_text, input_payload={**root._coerce_mapping_dict(repair_shard.input_payload), 'shard_id': shard.shard_id, 'owned_ids': list(repair_shard.owned_ids), 'packet_kind': 'repair', 'stage_key': 'line_role', 'validation_errors': list(current_validation_errors), 'structured_packet_rows': list(repair_packet.get('rows') or [])}, working_dir=session_root, env=env, output_schema_path=output_schema_path, model=model, reasoning_effort=reasoning_effort, timeout_seconds=timeout_seconds, workspace_task_label='canonical line-role structured repair session', resume_last=True, prepared_execution_working_dir=execution_workspace)
                repair_response_path.write_text(str(repair_run_result.response_text or ''), encoding='utf-8')
                repair_events_path.write_text(root._render_codex_events_jsonl(repair_run_result.events), encoding='utf-8')
                root._write_runtime_json(repair_last_message_path, {'text': repair_run_result.response_text})
                root._write_runtime_json(repair_usage_path, dict(repair_run_result.usage or {}))
                root._write_runtime_json(repair_workspace_manifest_path, repair_run_result.workspace_manifest())
                root._write_optional_runtime_text(repair_stdout_path, repair_run_result.stdout_text)
                root._write_optional_runtime_text(repair_stderr_path, repair_run_result.stderr_text)
                root.record_structured_session_turn(worker_root=session_root, execution_working_dir=execution_workspace, turn_kind='repair', packet_path=repair_packet_path, prompt_path=repair_prompt_path, response_path=repair_response_path)
                repair_runner_payload = root._build_line_role_inline_attempt_runner_payload(pipeline_id=pipeline_id, worker_id=assignment.worker_id, shard_id=shard.shard_id, run_result=repair_run_result, model=model, reasoning_effort=reasoning_effort, prompt_input_mode='structured_session_repair', events_path=repair_events_path, last_message_path=repair_last_message_path, usage_path=repair_usage_path, workspace_manifest_path=repair_workspace_manifest_path, stdout_path=repair_stdout_path, stderr_path=repair_stderr_path)
                worker_runner_results.append(repair_runner_payload)
                runner_results_by_shard_id[shard.shard_id] = repair_runner_payload
                _repair_payload, repair_validation_errors, repair_validation_metadata, repair_proposal_status = _evaluate_line_role_structured_response(
                    shard=repair_shard,
                    response_text=repair_run_result.response_text,
                    deterministic_baseline_by_atomic_index=baseline_by_atomic_index,
                    validator=validator,
                )
                repair_status = 'repaired' if repair_proposal_status == 'validated' else 'failed'
                final_validation_errors = tuple(repair_validation_errors)
                final_validation_metadata = root._merge_line_role_validation_metadata(original_shard=shard, initial_metadata=current_validation_metadata, repair_metadata=repair_validation_metadata)
                current_validation_errors = final_validation_errors
                current_validation_metadata = dict(final_validation_metadata or {})
                proposal_status = 'validated' if root._build_line_role_row_resolution(shard=shard, validation_metadata=final_validation_metadata)[0] is not None else 'invalid'
                unresolved_atomic_indices = [
                    int(value)
                    for value in (
                        current_validation_metadata.get('unresolved_atomic_indices')
                        or [int(value) for value in shard.owned_ids]
                    )
                    if str(value).strip()
                ]
                if proposal_status == 'validated':
                    break
        row_resolution_payload, row_resolution_metadata = root._build_line_role_row_resolution(shard=shard, validation_metadata=final_validation_metadata)
        proposal_payload = row_resolution_payload
        proposal_status = 'validated' if proposal_payload is not None else 'invalid'
        proposal_path = run_root / artifacts['proposals_dir'] / f'{shard.shard_id}.json'
        root._write_runtime_json(proposal_path, {'shard_id': shard.shard_id, 'worker_id': assignment.worker_id, 'payload': proposal_payload, 'validation_errors': list(final_validation_errors), 'validation_metadata': dict(final_validation_metadata or {}), 'repair_attempted': repair_attempted, 'repair_status': repair_status})
        output_path = worker_root / 'out' / f'{shard.shard_id}.json'
        if proposal_payload is not None:
            root._write_runtime_json(output_path, proposal_payload)
            worker_proposal_count += 1
            cohort_watchdog_state.record_validated_result(duration_ms=root._safe_int_value((runner_results_by_shard_id.get(shard.shard_id) or {}).get('telemetry', {}).get('summary', {}).get('duration_ms')), example_payload=root._build_line_role_watchdog_example(shard=shard, payload=proposal_payload))
        else:
            worker_failure_count += 1
            worker_failures.append({'worker_id': assignment.worker_id, 'shard_id': shard.shard_id, 'reason': 'validation_failed', 'validation_errors': list(final_validation_errors), 'state': 'invalid_output', 'reason_code': 'structured_validation_failed'})
        stage_rows.append(root._build_line_role_shard_status_row(shard=shard, worker_id=assignment.worker_id, state='repair_recovered' if proposal_payload is not None and repair_status == 'repaired' else 'validated' if proposal_payload is not None else 'repair_failed', last_attempt_type='repair' if repair_attempted else 'structured_session_initial', output_path=output_path if proposal_payload is not None else None, repair_path=latest_repair_packet_path if repair_attempted else None, validation_errors=final_validation_errors, validation_metadata=final_validation_metadata, row_resolution_metadata=row_resolution_metadata, repair_attempted=repair_attempted, repair_status=repair_status, resumed_from_existing_output=False, transport=root.INLINE_JSON_TRANSPORT))
        task_status_rows.append(root._build_line_role_shard_status_row(shard=shard, worker_id=assignment.worker_id, state='repair_recovered' if proposal_payload is not None and repair_status == 'repaired' else 'validated' if proposal_payload is not None else 'invalid_output', last_attempt_type='repair' if repair_attempted else 'structured_session_initial', output_path=output_path if proposal_payload is not None else None, repair_path=latest_repair_packet_path if repair_attempted else None, validation_errors=final_validation_errors, validation_metadata=final_validation_metadata, row_resolution_metadata=row_resolution_metadata, repair_attempted=repair_attempted, repair_status=repair_status, resumed_from_existing_output=False, transport=root.INLINE_JSON_TRANSPORT))
        worker_proposals.append(root.ShardProposalV1(shard_id=shard.shard_id, worker_id=assignment.worker_id, status=proposal_status, proposal_path=root._relative_runtime_path(run_root, proposal_path), payload=proposal_payload if proposal_payload is not None else None, validation_errors=tuple(final_validation_errors), metadata=dict(final_validation_metadata or {})))
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)
    worker_runner_payload = root._aggregate_line_role_worker_runner_payload(pipeline_id=pipeline_id, worker_runs=worker_runner_results)
    worker_telemetry_summary = (
        worker_runner_payload.get('telemetry', {}).get('summary', {})
    )
    if not isinstance(worker_telemetry_summary, root.Mapping):
        worker_telemetry_summary = {}
    worker_runner_payload['recovery_policy'] = root.inline_repair_policy_summary(stage_key=root.LINE_ROLE_POLICY_STAGE_KEY)
    worker_runner_payload['repair_recovery_policy'] = root.build_followup_budget_summary(
        stage_key=root.LINE_ROLE_POLICY_STAGE_KEY,
        transport=root.INLINE_JSON_TRANSPORT,
        spent_attempts_by_kind={
            root.FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: int(
                worker_telemetry_summary.get('structured_repair_followup_call_count') or 0
            ),
            root.FOLLOWUP_KIND_WATCHDOG_RETRY: int(
                worker_telemetry_summary.get('watchdog_retry_call_count') or 0
            ),
        },
        allowed_attempts_multiplier_by_kind={
            root.FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: len(assigned_shards),
            root.FOLLOWUP_KIND_WATCHDOG_RETRY: len(assigned_shards),
        },
    )
    root._write_runtime_json(worker_root / 'status.json', worker_runner_payload)
    return root._DirectLineRoleWorkerResult(report=root.WorkerExecutionReportV1(worker_id=assignment.worker_id, shard_ids=assignment.shard_ids, workspace_root=root._relative_runtime_path(run_root, worker_root), status='ok' if worker_failure_count == 0 else 'partial_failure', proposal_count=worker_proposal_count, failure_count=worker_failure_count, runtime_mode_audit={'mode': root.DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'status': 'ok', 'output_schema_enforced': True, 'tool_affordances_requested': False}, runner_result=worker_runner_payload, metadata={'shards_dir': root._relative_runtime_path(run_root, shard_dir), 'codex_exec_style': root.CODEX_EXEC_STYLE_INLINE_JSON_V1}), proposals=tuple(worker_proposals), failures=tuple(worker_failures), stage_rows=tuple(stage_rows), task_status_rows=tuple(task_status_rows), runner_results_by_shard_id=dict(runner_results_by_shard_id))

def _run_line_role_direct_workers_v1(*, phase_key: str, pipeline_id: str, run_root: root.Path, shards: root.Sequence[root.ShardManifestEntryV1], debug_payload_by_shard_id: root.Mapping[str, root.Any], deterministic_baseline_by_shard_id: root.Mapping[str, root.Mapping[int, root.CanonicalLineRolePrediction]], runner: root.CodexExecRunner, worker_count: int, env: dict[str, str], model: str | None, reasoning_effort: str | None, output_schema_path: root.Path | None, timeout_seconds: int, settings: dict[str, root.Any], runtime_metadata: dict[str, root.Any], progress_callback: root.Callable[[str], None] | None, prompt_state: '_PromptArtifactState' | None, validator: root.Callable[[root.ShardManifestEntryV1, dict[str, root.Any]], tuple[bool, root.Sequence[str], dict[str, root.Any] | None]]) -> tuple[root.PhaseManifestV1, list[root.WorkerExecutionReportV1], dict[str, dict[str, root.Any]]]:
    artifacts = {'phase_manifest': 'phase_manifest.json', 'shard_manifest': 'shard_manifest.jsonl', 'shard_status': 'shard_status.jsonl', 'canonical_line_table': 'canonical_line_table.jsonl', 'worker_assignments': 'worker_assignments.json', 'promotion_report': 'promotion_report.json', 'telemetry': 'telemetry.json', 'failures': 'failures.json', 'proposals_dir': 'proposals'}
    run_root.mkdir(parents=True, exist_ok=True)
    shard_by_id = {shard.shard_id: shard for shard in shards}
    assignments = root._assign_line_role_workers_v1(run_root=run_root, shards=shards, worker_count=worker_count)
    root._write_runtime_jsonl(run_root / artifacts['shard_manifest'], [root._line_role_asdict(shard) for shard in shards])
    root._write_runtime_jsonl(run_root / artifacts['canonical_line_table'], root._build_line_role_canonical_line_table_rows(debug_payload_by_shard_id=debug_payload_by_shard_id))
    root._write_runtime_json(run_root / artifacts['worker_assignments'], [root._line_role_asdict(assignment) for assignment in assignments])
    all_proposals: list[root.ShardProposalV1] = []
    failures: list[dict[str, root.Any]] = []
    worker_reports: list[root.WorkerExecutionReportV1] = []
    stage_rows: list[dict[str, root.Any]] = []
    task_status_rows: list[dict[str, root.Any]] = []
    runner_results_by_shard_id: dict[str, dict[str, root.Any]] = {}
    completed_shards = 0
    total_shards = len(shards)
    task_ids_by_worker: dict[str, tuple[str, ...]] = {assignment.worker_id: tuple(assignment.shard_ids) for assignment in assignments}
    total_tasks = sum((len(task_ids) for task_ids in task_ids_by_worker.values()))
    progress_lock = root.threading.Lock()
    cohort_watchdog_state = root._LineRoleCohortWatchdogState()
    pending_shards_by_worker = {assignment.worker_id: list(assignment.shard_ids) for assignment in assignments}
    worker_roots_by_id = {assignment.worker_id: run_root / 'workers' / assignment.worker_id for assignment in assignments}

    def _line_role_worker_followup_status(*, worker_id: str) -> tuple[int, int, int]:
        repair_attempted = 0
        repair_completed = 0
        repair_running = 0
        for task_id in task_ids_by_worker.get(worker_id, ()):
            repair_request_path = run_root / 'workers' / worker_id / 'repair' / f'{task_id}.json'
            repair_state_path = run_root / 'workers' / worker_id / 'repair' / f'{task_id}.status.json'
            repair_state = {}
            if repair_state_path.exists():
                try:
                    loaded_state = root.json.loads(repair_state_path.read_text(encoding='utf-8'))
                except (OSError, root.json.JSONDecodeError):
                    loaded_state = None
                if isinstance(loaded_state, root.Mapping):
                    repair_state = dict(loaded_state)
            repair_state_status = str(repair_state.get('status') or '').strip().lower()
            if repair_request_path.exists() or repair_state_path.exists():
                repair_attempted += 1
            if repair_state_status == 'installed_clean':
                repair_completed += 1
            elif repair_request_path.exists() or repair_state_status in {'requested', 'validated_clean'}:
                repair_running += 1
        return (repair_attempted, repair_completed, repair_running)

    def _render_line_role_progress_label(*, worker_id: str, completed_shard_ids: set[str]) -> str | None:
        worker_shard_ids = task_ids_by_worker.get(worker_id, ())
        if not worker_shard_ids:
            return None
        completed_worker_shards = sum((1 for shard_id in worker_shard_ids if shard_id in completed_shard_ids))
        if completed_worker_shards >= len(worker_shard_ids):
            return None
        pending_shards = pending_shards_by_worker.get(worker_id) or []
        base_label = str((pending_shards[0] if pending_shards else worker_shard_ids[0]) or '').strip() or worker_id
        extra_shard_count = max(0, len(pending_shards) - 1)
        if extra_shard_count > 0:
            base_label = f'{base_label} +{extra_shard_count} more'
        return f'{base_label} ({completed_worker_shards}/{len(worker_shard_ids)} shards)'

    def _emit_progress_locked(*, force: bool=False) -> None:
        worker_health = root.summarize_taskfile_health(worker_roots_by_id=worker_roots_by_id)
        completed_shard_ids: set[str] = set()
        for assignment in assignments:
            out_dir = run_root / 'workers' / assignment.worker_id / 'out'
            if not out_dir.exists():
                continue
            for output_path in out_dir.glob('*.json'):
                completed_shard_ids.add(output_path.stem)
        completed_tasks = min(total_tasks, len(completed_shard_ids))
        active_tasks = [label for assignment in assignments for label in [root.decorate_active_worker_label(_render_line_role_progress_label(worker_id=assignment.worker_id, completed_shard_ids=completed_shard_ids), worker_health.live_activity_summary_by_worker_id.get(assignment.worker_id), worker_health.attention_suffix_by_worker_id.get(assignment.worker_id))] if label is not None]
        running_workers = len(active_tasks)
        completed_workers = max(0, len(assignments) - running_workers)
        repair_attempted = 0
        repair_completed = 0
        repair_running = 0
        finalize_workers = 0
        proposals_dir = run_root / artifacts['proposals_dir']
        proposal_count = len(list(proposals_dir.glob('*.json'))) if proposals_dir.exists() else 0
        for assignment in assignments:
            worker_repair_attempted, worker_repair_completed, worker_repair_running = _line_role_worker_followup_status(worker_id=assignment.worker_id)
            repair_attempted += worker_repair_attempted
            repair_completed += worker_repair_completed
            repair_running += worker_repair_running
            if not any((task_id not in completed_shard_ids for task_id in task_ids_by_worker.get(assignment.worker_id, ()))) and (pending_shards_by_worker.get(assignment.worker_id) or []):
                finalize_workers += 1
        snapshot = (completed_tasks, total_tasks, completed_shards, total_shards, running_workers, completed_workers, repair_attempted, repair_completed, repair_running, finalize_workers, proposal_count, tuple(active_tasks), worker_health.warning_worker_count, worker_health.stalled_worker_count, tuple(worker_health.attention_lines), worker_health.last_activity_at)
        if not force and snapshot == getattr(_emit_progress_locked, '_last_snapshot', None):
            return
        setattr(_emit_progress_locked, '_last_snapshot', snapshot)
        detail_lines = []
        if worker_health.warning_worker_count > 0:
            detail_lines.append(f'watchdog warnings: {worker_health.warning_worker_count}')
        if worker_health.stalled_worker_count > 0:
            detail_lines.append(f'stalled workers: {worker_health.stalled_worker_count}')
        if worker_health.attention_lines:
            detail_lines.append('attention: ' + '; '.join(worker_health.attention_lines))
        root._notify_line_role_progress(progress_callback=progress_callback, completed_units=completed_tasks, total_units=total_tasks, work_unit_label='shard', running_units=running_workers, worker_total=worker_count, worker_running=running_workers, worker_completed=completed_workers, worker_failed=0, followup_running=finalize_workers + repair_running, followup_completed=completed_shards, followup_total=total_shards, followup_label='shard finalization', artifact_counts={'proposal_count': proposal_count, 'repair_attempted': repair_attempted, 'repair_completed': repair_completed, 'repair_running': repair_running, 'shards_completed': completed_shards, 'shards_total': total_shards}, last_activity_at=worker_health.last_activity_at, active_tasks=active_tasks, detail_lines=detail_lines)

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
    heartbeat_stop_event: root.threading.Event | None = None
    heartbeat_thread: root.threading.Thread | None = None
    if progress_callback is not None and assignments:
        heartbeat_stop_event, heartbeat_thread = root.start_taskfile_progress_heartbeat(emit_progress=_heartbeat_emit, thread_name='line-role-progress-heartbeat')
    try:
        with root.ThreadPoolExecutor(max_workers=max(1, len(assignments)), thread_name_prefix='line-role-worker') as executor:
            futures_by_worker_id = {assignment.worker_id: executor.submit(root._run_line_role_direct_worker_assignment_v1, run_root=run_root, assignment=assignment, artifacts=artifacts, shard_by_id=shard_by_id, debug_payload_by_shard_id=debug_payload_by_shard_id, deterministic_baseline_by_shard_id=deterministic_baseline_by_shard_id, runner=runner, pipeline_id=pipeline_id, env=env, model=model, reasoning_effort=reasoning_effort, settings=settings, output_schema_path=output_schema_path, timeout_seconds=timeout_seconds, cohort_watchdog_state=cohort_watchdog_state, shard_completed_callback=_mark_shard_completed, prompt_state=prompt_state, validator=validator) for assignment in assignments}
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
    root._write_runtime_jsonl(run_root / artifacts['shard_status'], task_status_rows)
    llm_authoritative_row_count = sum((int((row.get('metadata') or {} if isinstance(row, dict) else {}).get('llm_authoritative_row_count') or 0) for row in task_status_rows if isinstance(row, dict)))
    unresolved_row_count = sum((int((row.get('metadata') or {} if isinstance(row, dict) else {}).get('unresolved_row_count') or 0) for row in task_status_rows if isinstance(row, dict)))
    suspicious_shard_count = sum((1 for row in task_status_rows if bool((row.get('metadata') or {} if isinstance(row, dict) else {}).get('suspicious_shard'))))
    suspicious_row_count = sum((int((row.get('metadata') or {} if isinstance(row, dict) else {}).get('suspicious_row_count') or 0) for row in task_status_rows if isinstance(row, dict)))
    promotion_report = {'schema_version': 'phase_worker_runtime.promotion_report.v1', 'phase_key': phase_key, 'pipeline_id': pipeline_id, 'validated_shards': sum((1 for proposal in all_proposals if proposal.status == 'validated')), 'invalid_shards': sum((1 for proposal in all_proposals if proposal.status == 'invalid')), 'missing_output_shards': sum((1 for proposal in all_proposals if proposal.status == 'missing_output')), 'shard_state_counts': {state: sum((1 for row in task_status_rows if str((row.get('state') if isinstance(row, dict) else '') or '').strip() == state)) for state in sorted({str((row.get('state') if isinstance(row, dict) else '') or '').strip() for row in task_status_rows if str((row.get('state') if isinstance(row, dict) else '') or '').strip()})}, 'llm_authoritative_row_count': llm_authoritative_row_count, 'unresolved_row_count': unresolved_row_count, 'suspicious_shard_count': suspicious_shard_count, 'suspicious_row_count': suspicious_row_count}
    telemetry = {'schema_version': 'phase_worker_runtime.telemetry.v1', 'phase_key': phase_key, 'pipeline_id': pipeline_id, 'runtime_mode': root.DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'worker_count': len(assignments), 'shard_count': len(shards), 'proposal_count': sum((report.proposal_count for report in worker_reports)), 'failure_count': len(failures), 'fresh_agent_count': len(assignments) + sum((int(dict(report.metadata or {}).get('fresh_worker_replacement_count') or 0) for report in worker_reports)), 'rows': stage_rows, 'summary': root._summarize_direct_rows(stage_rows)}
    task_file_guardrails = root.summarize_task_file_guardrails([dict(report.metadata or {}).get('task_file_guardrail') if isinstance(report.metadata, root.Mapping) else None for report in worker_reports])
    worker_session_guardrails = root.build_worker_session_guardrails(planned_happy_path_worker_cap=len(assignments) * 3, actual_happy_path_worker_sessions=int(telemetry['summary'].get('taskfile_session_count') or 0))
    telemetry['summary']['task_file_guardrails'] = task_file_guardrails
    telemetry['summary']['worker_session_guardrails'] = worker_session_guardrails
    telemetry['summary']['planned_happy_path_worker_cap'] = int(worker_session_guardrails['planned_happy_path_worker_cap'])
    telemetry['summary']['actual_happy_path_worker_sessions'] = int(worker_session_guardrails['actual_happy_path_worker_sessions'])
    same_session_repair_rewrite_count = sum((int(dict(report.metadata or {}).get('same_session_repair_rewrite_count') or 0) for report in worker_reports))
    fresh_session_retry_count = sum((int(dict(report.metadata or {}).get('fresh_session_retry_count') or 0) for report in worker_reports))
    fresh_worker_replacement_count = sum((int(dict(report.metadata or {}).get('fresh_worker_replacement_count') or 0) for report in worker_reports))
    telemetry_summary = telemetry.get('summary') if isinstance(telemetry, root.Mapping) else {}
    if not isinstance(telemetry_summary, root.Mapping):
        telemetry_summary = {}
    if any(str(dict(report.metadata or {}).get('codex_exec_style') or '').strip() == root.CODEX_EXEC_STYLE_INLINE_JSON_V1 for report in worker_reports):
        telemetry['summary']['repair_recovery_policy'] = root.build_followup_budget_summary(
            stage_key=root.LINE_ROLE_POLICY_STAGE_KEY,
            transport=root.INLINE_JSON_TRANSPORT,
            spent_attempts_by_kind={
                root.FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: int(
                    telemetry_summary.get('structured_repair_followup_call_count') or 0
                ),
                root.FOLLOWUP_KIND_WATCHDOG_RETRY: int(
                    telemetry_summary.get('watchdog_retry_call_count') or 0
                ),
            },
            allowed_attempts_multiplier_by_kind={
                root.FOLLOWUP_KIND_STRUCTURED_REPAIR_FOLLOWUP: len(shards),
                root.FOLLOWUP_KIND_WATCHDOG_RETRY: len(shards),
            },
        )
    else:
        telemetry['summary']['repair_recovery_policy'] = root.build_followup_budget_summary(
            stage_key=root.LINE_ROLE_POLICY_STAGE_KEY,
            transport=root.TASKFILE_TRANSPORT,
            spent_attempts_by_kind={
                root.FOLLOWUP_KIND_SAME_SESSION_REPAIR_REWRITE: same_session_repair_rewrite_count,
                root.FOLLOWUP_KIND_FRESH_SESSION_RETRY: fresh_session_retry_count,
                root.FOLLOWUP_KIND_FRESH_WORKER_REPLACEMENT: fresh_worker_replacement_count,
            },
        )
    root._write_runtime_json(run_root / artifacts['promotion_report'], promotion_report)
    root._write_runtime_json(run_root / artifacts['telemetry'], telemetry)
    root._write_runtime_json(run_root / artifacts['failures'], failures)
    runtime_metadata_payload = {**dict(runtime_metadata or {}), 'task_file_guardrails': task_file_guardrails, 'worker_session_guardrails': worker_session_guardrails, 'same_session_repair_rewrite_count': same_session_repair_rewrite_count, 'fresh_session_retry_count': fresh_session_retry_count, 'fresh_worker_replacement_count': fresh_worker_replacement_count}
    manifest = root.PhaseManifestV1(schema_version='phase_worker_runtime.phase_manifest.v1', phase_key=phase_key, pipeline_id=pipeline_id, run_root=str(run_root), worker_count=len(assignments), shard_count=len(shards), assignment_strategy='round_robin_v1', runtime_mode=root.DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, max_turns_per_shard=1, settings=dict(settings or {}), artifact_paths=dict(artifacts), runtime_metadata=runtime_metadata_payload)
    root._write_runtime_json(run_root / artifacts['phase_manifest'], root._line_role_asdict(manifest))
    if bool(worker_session_guardrails.get('cap_exceeded')):
        raise root.LineRoleRepairFailureError(f'Canonical line-role happy-path worker sessions exceeded the planned cap: planned={worker_session_guardrails['planned_happy_path_worker_cap']} actual={worker_session_guardrails['actual_happy_path_worker_sessions']}.')
    return (manifest, worker_reports, runner_results_by_shard_id)

def _assign_line_role_workers_v1(*, run_root: root.Path, shards: root.Sequence[root.ShardManifestEntryV1], worker_count: int) -> list[root.WorkerAssignmentV1]:
    effective_workers = root.resolve_phase_worker_count(requested_worker_count=worker_count, shard_count=len(shards))
    buckets: list[list[str]] = [[] for _ in range(effective_workers)]
    for index, shard in enumerate(shards):
        buckets[index % effective_workers].append(shard.shard_id)
    return [root.WorkerAssignmentV1(worker_id=f'worker-{index + 1:03d}', shard_ids=tuple(bucket), workspace_root=str(run_root / 'workers' / f'worker-{index + 1:03d}')) for index, bucket in enumerate(buckets)]

def _build_line_role_workspace_task_runner_payload(*, pipeline_id: str, worker_id: str, shard_id: str, runtime_shard_id: str, run_result: root.CodexExecRunResult, model: str | None, reasoning_effort: str | None, request_input_file: root.Path | None, debug_input_file: root.Path | None, worker_prompt_path: root.Path | None, worker_root: root.Path, task_count: int, task_index: int) -> dict[str, root.Any]:
    payload = run_result.to_payload(worker_id=worker_id, shard_id=shard_id)
    payload['pipeline_id'] = pipeline_id
    request_input_file_str = str(request_input_file) if request_input_file is not None else None
    request_input_file_bytes = request_input_file.stat().st_size if request_input_file is not None and request_input_file.exists() else None
    debug_input_file_str = str(debug_input_file) if debug_input_file is not None else None
    worker_prompt_file_str = str(worker_prompt_path) if worker_prompt_path is not None else None
    telemetry = payload.get('telemetry')
    row_payloads = telemetry.get('rows') if isinstance(telemetry, dict) else None
    if isinstance(row_payloads, list) and row_payloads and isinstance(row_payloads[0], dict):
        row_payload = dict(row_payloads[0])
        share_fields = ('duration_ms', 'tokens_input', 'tokens_cached_input', 'tokens_output', 'tokens_reasoning', 'visible_input_tokens', 'visible_output_tokens', 'wrapper_overhead_tokens')
        for field_name in share_fields:
            shares = root._distribute_line_role_session_value(row_payload.get(field_name), task_count)
            row_payload[field_name] = shares[task_index]
        token_total_shares = root._distribute_line_role_session_value(root._safe_int_value(row_payload.get('tokens_total')), task_count)
        token_components = (root._safe_int_value(row_payload.get('tokens_input')), root._safe_int_value(row_payload.get('tokens_cached_input')), root._safe_int_value(row_payload.get('tokens_output')), root._safe_int_value(row_payload.get('tokens_reasoning')))
        row_payload['tokens_total'] = sum((int(value) for value in token_components)) if all((value is not None for value in token_components)) else token_total_shares[task_index]
        row_payload['prompt_input_mode'] = 'taskfile'
        row_payload['runtime_shard_id'] = runtime_shard_id
        row_payload['runtime_parent_shard_id'] = shard_id
        row_payload['request_input_file'] = request_input_file_str
        row_payload['request_input_file_bytes'] = request_input_file_bytes
        row_payload['debug_input_file'] = debug_input_file_str
        row_payload['worker_prompt_file'] = worker_prompt_file_str
        row_payload['worker_session_shard_count'] = task_count
        row_payload['worker_session_primary_row'] = task_index == 0
        row_payload['command_execution_policy_counts'] = root._line_role_command_policy_counts(row_payload.get('command_execution_commands'))
        row_payload['command_execution_policy_by_command'] = root._line_role_command_policy_by_command(row_payload.get('command_execution_commands'))
        row_payload['events_path'] = str(worker_root / 'events.jsonl')
        row_payload['last_message_path'] = str(worker_root / 'last_message.json')
        row_payload['usage_path'] = str(worker_root / 'usage.json')
        row_payload['live_status_path'] = str(worker_root / 'live_status.json')
        row_payload['workspace_manifest_path'] = str(worker_root / 'workspace_manifest.json')
        row_payload['stdout_path'] = str(worker_root / 'stdout.txt')
        row_payload['stderr_path'] = str(worker_root / 'stderr.txt')
        if task_index > 0:
            row_payload['command_execution_count'] = 0
            row_payload['command_execution_commands'] = []
            row_payload['command_execution_policy_counts'] = {}
            row_payload['command_execution_policy_by_command'] = []
            row_payload['reasoning_item_count'] = 0
            row_payload['reasoning_item_types'] = []
            row_payload['codex_event_count'] = 0
            row_payload['codex_event_types'] = []
            row_payload['output_preview'] = None
            row_payload['output_preview_chars'] = 0
        telemetry['rows'] = [row_payload]
        telemetry['summary'] = root._summarize_direct_rows([row_payload])
    payload['process_payload'] = {'pipeline_id': pipeline_id, 'status': 'done' if run_result.subprocess_exit_code == 0 else 'failed', 'codex_model': model, 'codex_reasoning_effort': reasoning_effort, 'prompt_input_mode': 'taskfile', 'runtime_shard_id': runtime_shard_id, 'runtime_parent_shard_id': shard_id, 'request_input_file': request_input_file_str, 'request_input_file_bytes': request_input_file_bytes, 'debug_input_file': debug_input_file_str, 'worker_prompt_file': worker_prompt_file_str, 'events_path': str(worker_root / 'events.jsonl'), 'last_message_path': str(worker_root / 'last_message.json'), 'usage_path': str(worker_root / 'usage.json'), 'live_status_path': str(worker_root / 'live_status.json'), 'workspace_manifest_path': str(worker_root / 'workspace_manifest.json'), 'stdout_path': str(worker_root / 'stdout.txt'), 'stderr_path': str(worker_root / 'stderr.txt')}
    return payload

def _line_role_command_policy_by_command(value: root.Any) -> list[dict[str, root.Any]]:
    commands = value if isinstance(value, list) else []
    rows: list[dict[str, root.Any]] = []
    for command in commands:
        command_text = str(command or '').strip()
        if not command_text:
            continue
        verdict = root._classify_line_role_workspace_command(command_text)
        rows.append({'command': command_text, 'allowed': verdict.allowed, 'policy': verdict.policy, 'reason': verdict.reason})
    return rows

def _line_role_command_policy_counts(value: root.Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in root._line_role_command_policy_by_command(value):
        policy = str(row.get('policy') or '').strip()
        if not policy:
            continue
        counts[policy] = int(counts.get(policy) or 0) + 1
    return dict(sorted(counts.items()))

def _line_role_direct_summary_policy_fields(summary: root.Mapping[str, root.Any]) -> dict[str, root.Any]:
    payload: dict[str, root.Any] = {}
    for key in (
        'taskfile_session_count',
        'structured_followup_call_count',
        'structured_repair_followup_call_count',
        'watchdog_retry_call_count',
        'structured_followup_tokens_total',
    ):
        value = root._safe_int_value(summary.get(key))
        if value is not None:
            payload[key] = value
    for key in (
        'codex_transport',
        'codex_policy_mode',
    ):
        value = str(summary.get(key) or '').strip()
        if value:
            payload[key] = value
    shell_tool_enabled = summary.get('codex_shell_tool_enabled')
    if shell_tool_enabled is not None:
        payload['codex_shell_tool_enabled'] = bool(shell_tool_enabled)
    for key in (
        'codex_transport_counts',
        'codex_policy_mode_counts',
        'codex_shell_tool_enabled_counts',
    ):
        counts = summary.get(key)
        if isinstance(counts, dict):
            payload[key] = dict(sorted(counts.items()))
    return payload

def _aggregate_line_role_worker_runner_payload(*, pipeline_id: str, worker_runs: root.Sequence[dict[str, root.Any]]) -> dict[str, root.Any]:
    rows: list[dict[str, root.Any]] = []
    for worker_run in worker_runs:
        telemetry = worker_run.get('telemetry')
        worker_rows = telemetry.get('rows') if isinstance(telemetry, dict) else None
        if isinstance(worker_rows, list):
            rows.extend((dict(row_payload) for row_payload in worker_rows if isinstance(row_payload, dict)))
    uses_taskfile_contract = any((str((payload.get('process_payload') or {} if isinstance(payload, dict) else {}).get('prompt_input_mode') or '').strip() == 'taskfile' for payload in worker_runs if isinstance(payload, dict)))
    return {'runner_kind': 'codex_exec_direct', 'runtime_mode': root.DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'pipeline_id': pipeline_id, 'worker_runs': [dict(payload) for payload in worker_runs], 'telemetry': {'rows': rows, 'summary': root._summarize_direct_rows(rows)}, 'runtime_mode_audit': {'mode': root.DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'status': 'ok', 'output_schema_enforced': not uses_taskfile_contract, 'tool_affordances_requested': uses_taskfile_contract}}

def _write_line_role_telemetry_summary(*, artifact_root: root.Path | None, runtime_result: root._LineRoleRuntimeResult | None) -> None:
    if artifact_root is None or runtime_result is None:
        return
    pipeline_dir = artifact_root / 'line-role-pipeline'
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    summary_path = pipeline_dir / 'telemetry_summary.json'
    all_rows: list[dict[str, root.Any]] = []
    phase_payloads: list[dict[str, root.Any]] = []
    for phase_result in runtime_result.phase_results:
        telemetry_rows: list[dict[str, root.Any]] = []
        batch_payloads: list[dict[str, root.Any]] = []
        for report in phase_result.worker_reports:
            runner_result = report.runner_result or {}
            telemetry_payload = runner_result.get('telemetry')
            if not isinstance(telemetry_payload, dict):
                continue
            rows = telemetry_payload.get('rows')
            if isinstance(rows, list):
                telemetry_rows.extend((dict(row) for row in rows if isinstance(row, dict)))
        all_rows.extend(telemetry_rows)
        phase_direct_summary = root._summarize_direct_rows(telemetry_rows)
        phase_totals = root._sum_runtime_usage(telemetry_rows)
        for plan in phase_result.shard_plans:
            runner_payload = phase_result.runner_results_by_shard_id.get(plan.shard_id) or {}
            attempt_usage: dict[str, root.Any] | None = None
            matching_rows = [row for row in telemetry_rows if str(row.get('task_id') or '').strip() == plan.shard_id]
            telemetry_payload = runner_payload.get('telemetry')
            runner_rows = telemetry_payload.get('rows') if isinstance(telemetry_payload, dict) else None
            if isinstance(runner_rows, list) and runner_rows:
                first_row = runner_rows[0]
                if isinstance(first_row, dict):
                    attempt_usage = {'tokens_input': root._safe_int_value(first_row.get('tokens_input')), 'tokens_cached_input': root._safe_int_value(first_row.get('tokens_cached_input')), 'tokens_output': root._safe_int_value(first_row.get('tokens_output')), 'tokens_reasoning': root._safe_int_value(first_row.get('tokens_reasoning')), 'tokens_total': root._safe_int_value(first_row.get('tokens_total'))}
                    if not root._line_role_usage_present(attempt_usage):
                        attempt_usage = None
            batch_payloads.append({'prompt_index': plan.prompt_index, 'shard_id': plan.shard_id, 'candidate_count': len(plan.candidates), 'requested_atomic_indices': [int(candidate.atomic_index) for candidate in plan.candidates], 'attempt_count': len(matching_rows) or 1, 'attempts_with_usage': 1 if root._line_role_usage_present(attempt_usage) else 0, 'attempts': [{'attempt_index': 1, 'response_present': bool(str(runner_payload.get('response_text') or '').strip()), 'returncode': root._safe_int_value(runner_payload.get('subprocess_exit_code')), 'turn_failed_message': runner_payload.get('turn_failed_message'), 'usage': attempt_usage, 'process_run': runner_payload}]})
        phase_payloads.append({'phase_key': phase_result.phase_key, 'phase_label': phase_result.phase_label, 'summary': {'batch_count': len(phase_result.shard_plans), 'attempt_count': len(telemetry_rows) or len(phase_result.shard_plans), 'attempts_with_usage': sum((1 for row in telemetry_rows if root._line_role_usage_present(row))), 'attempts_without_usage': max(0, (len(telemetry_rows) or len(phase_result.shard_plans)) - sum((1 for row in telemetry_rows if root._line_role_usage_present(row)))), 'tokens_input': phase_totals.get('tokens_input'), 'tokens_cached_input': phase_totals.get('tokens_cached_input'), 'tokens_output': phase_totals.get('tokens_output'), 'tokens_reasoning': phase_totals.get('tokens_reasoning'), 'tokens_total': phase_totals.get('tokens_total'), 'visible_input_tokens': phase_totals.get('visible_input_tokens'), 'visible_output_tokens': phase_totals.get('visible_output_tokens'), 'wrapper_overhead_tokens': phase_totals.get('wrapper_overhead_tokens'), 'command_execution_count_total': phase_direct_summary.get('command_execution_count_total'), 'command_executing_shard_count': phase_direct_summary.get('command_executing_shard_count'), 'command_execution_tokens_total': phase_direct_summary.get('command_execution_tokens_total'), 'reasoning_item_count_total': phase_direct_summary.get('reasoning_item_count_total'), 'reasoning_heavy_shard_count': phase_direct_summary.get('reasoning_heavy_shard_count'), 'reasoning_heavy_tokens_total': phase_direct_summary.get('reasoning_heavy_tokens_total'), 'invalid_output_shard_count': phase_direct_summary.get('invalid_output_shard_count'), 'invalid_output_tokens_total': phase_direct_summary.get('invalid_output_tokens_total'), 'missing_output_shard_count': phase_direct_summary.get('missing_output_shard_count'), 'preflight_rejected_shard_count': phase_direct_summary.get('preflight_rejected_shard_count'), 'watchdog_killed_shard_count': phase_direct_summary.get('watchdog_killed_shard_count'), 'watchdog_recovered_shard_count': phase_direct_summary.get('watchdog_recovered_shard_count'), 'repaired_shard_count': phase_direct_summary.get('repaired_shard_count'), 'pathological_shard_count': phase_direct_summary.get('pathological_shard_count'), 'pathological_flags': phase_direct_summary.get('pathological_flags'), 'prompt_input_mode': 'inline', 'request_input_file_bytes_total': phase_totals.get('request_input_file_bytes_total'), **_line_role_direct_summary_policy_fields(phase_direct_summary)}, 'batches': batch_payloads, 'runtime_artifacts': {'runtime_root': str(phase_result.runtime_root.relative_to(artifact_root)) if phase_result.runtime_root is not None else None, 'invalid_shard_count': phase_result.invalid_shard_count, 'missing_output_shard_count': phase_result.missing_output_shard_count, 'worker_count': len(phase_result.worker_reports)}})
    totals = root._sum_runtime_usage(all_rows)
    direct_summary = root._summarize_direct_rows(all_rows)
    summary_path.write_text(root.json.dumps({'schema_version': 1, 'pipeline': root.LINE_ROLE_PIPELINE_ROUTE_V2, 'codex_backend': 'codex_exec_direct', 'codex_farm_pipeline_id': root._LINE_ROLE_CODEX_FARM_PIPELINE_ID, 'runtime_mode': root.DIRECT_CODEX_EXEC_RUNTIME_MODE_V1, 'token_usage_enabled': bool(all_rows), 'summary': {'batch_count': sum((len(phase_result.shard_plans) for phase_result in runtime_result.phase_results)), 'attempt_count': len(all_rows) or sum((len(phase_result.shard_plans) for phase_result in runtime_result.phase_results)), 'attempts_with_usage': sum((1 for row in all_rows if root._line_role_usage_present(row))), 'attempts_without_usage': max(0, (len(all_rows) or sum((len(phase_result.shard_plans) for phase_result in runtime_result.phase_results))) - sum((1 for row in all_rows if root._line_role_usage_present(row)))), 'tokens_input': totals.get('tokens_input'), 'tokens_cached_input': totals.get('tokens_cached_input'), 'tokens_output': totals.get('tokens_output'), 'tokens_reasoning': totals.get('tokens_reasoning'), 'tokens_total': totals.get('tokens_total'), 'visible_input_tokens': totals.get('visible_input_tokens'), 'visible_output_tokens': totals.get('visible_output_tokens'), 'wrapper_overhead_tokens': totals.get('wrapper_overhead_tokens'), 'command_execution_count_total': direct_summary.get('command_execution_count_total'), 'command_executing_shard_count': direct_summary.get('command_executing_shard_count'), 'command_execution_tokens_total': direct_summary.get('command_execution_tokens_total'), 'reasoning_item_count_total': direct_summary.get('reasoning_item_count_total'), 'reasoning_heavy_shard_count': direct_summary.get('reasoning_heavy_shard_count'), 'reasoning_heavy_tokens_total': direct_summary.get('reasoning_heavy_tokens_total'), 'invalid_output_shard_count': direct_summary.get('invalid_output_shard_count'), 'invalid_output_tokens_total': direct_summary.get('invalid_output_tokens_total'), 'missing_output_shard_count': direct_summary.get('missing_output_shard_count'), 'preflight_rejected_shard_count': direct_summary.get('preflight_rejected_shard_count'), 'watchdog_killed_shard_count': direct_summary.get('watchdog_killed_shard_count'), 'watchdog_recovered_shard_count': direct_summary.get('watchdog_recovered_shard_count'), 'repaired_shard_count': direct_summary.get('repaired_shard_count'), 'pathological_shard_count': direct_summary.get('pathological_shard_count'), 'pathological_flags': direct_summary.get('pathological_flags'), 'prompt_input_mode': 'inline', 'request_input_file_bytes_total': totals.get('request_input_file_bytes_total'), **_line_role_direct_summary_policy_fields(direct_summary)}, 'phases': phase_payloads, 'runtime_artifacts': {'runtime_root': 'line-role-pipeline/runtime', 'phase_count': len(runtime_result.phase_results)}}, indent=2, sort_keys=True), encoding='utf-8')
