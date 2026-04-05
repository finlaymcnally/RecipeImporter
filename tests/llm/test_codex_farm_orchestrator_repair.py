from __future__ import annotations

import tests.llm.codex_farm_orchestrator_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_orchestrator_repairs_near_miss_invalid_recipe_shard_once(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )

    class _NearMissRepairRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
            working_dir = Path(kwargs["working_dir"])
            process_env = exec_runner_module._merge_env(kwargs["env"])
            prepared = exec_runner_module.prepare_direct_exec_workspace(
                source_working_dir=working_dir,
                env=process_env,
                task_label=kwargs.get("workspace_task_label"),
                mode="taskfile",
            )
            execution_working_dir = prepared.execution_working_dir
            execution_prompt_text = exec_runner_module.rewrite_direct_exec_prompt_paths(
                prompt_text=kwargs["prompt_text"],
                source_working_dir=working_dir,
                execution_working_dir=execution_working_dir,
            )
            self.calls.append(
                {
                    "mode": "taskfile",
                    "prompt_text": execution_prompt_text,
                    "input_payload": None,
                    "working_dir": str(working_dir),
                    "execution_working_dir": str(execution_working_dir),
                }
            )
            task_file_payload = exec_runner_module.load_task_file(
                execution_working_dir / "task.json"
            )
            if len(self.calls) == 1:
                _write_workspace_task_file_result(
                    self,
                    working_dir=working_dir,
                    execution_working_dir=execution_working_dir,
                    payload=_blank_recipe_task_file_answers(
                        task_file_payload=task_file_payload,
                    ),
                )
            else:
                _write_workspace_task_file_result(
                    self,
                    working_dir=working_dir,
                    execution_working_dir=execution_working_dir,
                )

            response_text = "Workspace task file updated."
            usage = {
                "input_tokens": max(1, len(execution_prompt_text) // 4),
                "cached_input_tokens": 0,
                "output_tokens": max(1, len(response_text) // 4),
                "reasoning_tokens": 0,
            }
            events = (
                {"type": "thread.started"},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": response_text},
                },
                {"type": "turn.completed", "usage": usage},
            )
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=None,
                prompt_text=execution_prompt_text,
                response_text=response_text,
                turn_failed_message=None,
                events=events,
                usage=usage,
                stdout_text="\n".join(json.dumps(event) for event in events) + "\n",
                source_working_dir=str(working_dir),
                execution_working_dir=str(execution_working_dir),
                execution_agents_path=str(prepared.agents_path),
                duration_ms=1,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:00Z",
                workspace_mode="taskfile",
                supervision_state="completed",
            )

    runner = _NearMissRepairRunner(output_builder=_build_valid_recipe_task_output)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    assert [call["mode"] for call in runner.calls] == [
        "taskfile",
        "taskfile",
    ]

    proposal = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "proposals"
            / "recipe-shard-0000-r0000-r0000.json"
        ).read_text(encoding="utf-8")
    )
    repair_status = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "workers"
            / "worker-001"
            / "shards"
            / "recipe-shard-0000-r0000-r0000"
            / "repair_status.json"
        ).read_text(encoding="utf-8")
    )

    assert proposal["repair_attempted"] is True
    assert proposal["repair_status"] == "repaired"
    assert proposal["validation_errors"] == []
    assert repair_status["repair_status"] == "repaired"
    assert repair_status["validation_errors"] == []
    authoritative_payload = apply_result.authoritative_recipe_payloads_by_recipe_id[
        "urn:recipe:test:toast"
    ]
    assert authoritative_payload.title == "Toast"
    assert authoritative_payload.ingredients == [
        "1 slice bread",
        "1 tablespoon butter",
    ]
    assert authoritative_payload.instructions == [
        "Toast the bread until golden.",
        "Spread with butter and serve hot.",
    ]
    assert authoritative_payload.ingredient_step_mapping_reason == "unclear_alignment"


def test_orchestrator_recovers_recipe_validation_failure_via_task_file_repair(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )

    class _TaskFileRepairRecoveryRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
            working_dir = Path(kwargs["working_dir"])
            process_env = exec_runner_module._merge_env(kwargs["env"])
            prepared = exec_runner_module.prepare_direct_exec_workspace(
                source_working_dir=working_dir,
                env=process_env,
                task_label=kwargs.get("workspace_task_label"),
                mode="taskfile",
            )
            execution_working_dir = prepared.execution_working_dir
            execution_prompt_text = exec_runner_module.rewrite_direct_exec_prompt_paths(
                prompt_text=kwargs["prompt_text"],
                source_working_dir=working_dir,
                execution_working_dir=execution_working_dir,
            )
            self.calls.append(
                {
                    "mode": "taskfile",
                    "prompt_text": execution_prompt_text,
                    "input_payload": None,
                    "working_dir": str(working_dir),
                    "execution_working_dir": str(execution_working_dir),
                }
            )
            call_index = len(self.calls)

            def _sync_outputs() -> None:
                exec_runner_module._sync_direct_exec_workspace_paths(  # noqa: SLF001
                    source_working_dir=working_dir,
                    execution_working_dir=execution_working_dir,
                    relative_paths=("out", "scratch"),
                )

            def _sync_controls() -> None:
                exec_runner_module._sync_direct_exec_runtime_control_paths_to_execution(  # noqa: SLF001
                    source_working_dir=working_dir,
                    execution_working_dir=execution_working_dir,
                    relative_paths=exec_runner_module._DIRECT_EXEC_RUNTIME_CONTROL_PATHS,  # noqa: SLF001
                )

            if call_index == 1:
                task_file_payload = exec_runner_module.load_task_file(
                    execution_working_dir / "task.json"
                )
                _write_workspace_task_file_result(
                    self,
                    working_dir=working_dir,
                    execution_working_dir=execution_working_dir,
                    payload=_blank_recipe_task_file_answers(
                        task_file_payload=task_file_payload,
                    ),
                )
            supervision_callback = kwargs.get("supervision_callback")
            if supervision_callback is not None:
                decision = supervision_callback(
                    CodexExecLiveSnapshot(
                        elapsed_seconds=0.1,
                        last_event_seconds_ago=0.0,
                        event_count=1,
                        command_execution_count=0,
                        reasoning_item_count=0,
                        last_command=None,
                        last_command_repeat_count=0,
                        has_final_agent_message=False,
                        timeout_seconds=kwargs.get("timeout_seconds"),
                        source_working_dir=str(working_dir),
                        execution_working_dir=str(execution_working_dir),
                    )
                )
                assert decision is None
                _sync_controls()

            if call_index > 1:
                _write_workspace_task_file_result(
                    self,
                    working_dir=working_dir,
                    execution_working_dir=execution_working_dir,
                )
            if supervision_callback is not None:
                supervision_callback(
                    CodexExecLiveSnapshot(
                        elapsed_seconds=0.2,
                        last_event_seconds_ago=0.0,
                        event_count=2,
                        command_execution_count=0,
                        reasoning_item_count=0,
                        last_command=None,
                        last_command_repeat_count=0,
                        has_final_agent_message=True,
                        timeout_seconds=kwargs.get("timeout_seconds"),
                        source_working_dir=str(working_dir),
                        execution_working_dir=str(execution_working_dir),
                    )
                )
                _sync_controls()

            response_text = "Finished."
            usage = {
                "input_tokens": 10,
                "cached_input_tokens": 0,
                "output_tokens": 2,
                "reasoning_tokens": 0,
            }
            events = (
                {"type": "thread.started"},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": response_text},
                },
                {"type": "turn.completed", "usage": usage},
            )
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=None,
                prompt_text=execution_prompt_text,
                response_text=response_text,
                turn_failed_message=None,
                events=events,
                usage=usage,
                stdout_text="\n".join(json.dumps(event) for event in events) + "\n",
                source_working_dir=str(working_dir),
                execution_working_dir=str(execution_working_dir),
                execution_agents_path=str(prepared.agents_path),
                duration_ms=1,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:00Z",
                workspace_mode="taskfile",
                supervision_state="completed",
            )

    runner = _TaskFileRepairRecoveryRunner(
        output_builder=lambda payload: _build_valid_recipe_task_output(dict(payload or {}))
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    assert [call["mode"] for call in runner.calls] == [
        "taskfile",
        "taskfile",
    ]
    shard_root = (
        apply_result.llm_raw_dir
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
        / "shards"
        / "recipe-shard-0000-r0000-r0000"
    )
    repair_status = json.loads((shard_root / "repair_status.json").read_text(encoding="utf-8"))
    proposal = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "proposals"
            / "recipe-shard-0000-r0000-r0000.json"
        ).read_text(encoding="utf-8")
    )
    promotion_report = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "promotion_report.json"
        ).read_text(encoding="utf-8")
    )

    assert repair_status["repair_status"] == "repaired"
    assert proposal["repair_attempted"] is True
    assert proposal["repair_status"] == "repaired"
    assert proposal["validation_metadata"]["task_status_by_task_id"][
        "recipe-shard-0000-r0000-r0000"
    ]["task_status"] == "validated_after_repair"
    assert promotion_report["task_counts"]["validated_after_repair"] == 1


def test_orchestrator_marks_task_failed_after_repair_budget_exhausted(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )

    def _output_builder(payload: dict[str, object] | None) -> dict[str, object]:
        assert payload is not None
        if payload.get("repair_mode") == "recipe":
            return _build_valid_recipe_task_output(payload["authoritative_input"])
        return _build_valid_recipe_task_output(payload)

    class _BudgetExhaustedRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
            working_dir = Path(kwargs["working_dir"])
            process_env = exec_runner_module._merge_env(kwargs["env"])
            prepared = exec_runner_module.prepare_direct_exec_workspace(
                source_working_dir=working_dir,
                env=process_env,
                task_label=kwargs.get("workspace_task_label"),
                mode="taskfile",
            )
            execution_working_dir = prepared.execution_working_dir
            execution_prompt_text = exec_runner_module.rewrite_direct_exec_prompt_paths(
                prompt_text=kwargs["prompt_text"],
                source_working_dir=working_dir,
                execution_working_dir=execution_working_dir,
            )
            self.calls.append(
                {
                    "mode": "taskfile",
                    "prompt_text": execution_prompt_text,
                    "input_payload": None,
                    "working_dir": str(working_dir),
                    "execution_working_dir": str(execution_working_dir),
                }
            )
            call_index = len(self.calls)

            def _sync_outputs() -> None:
                exec_runner_module._sync_direct_exec_workspace_paths(  # noqa: SLF001
                    source_working_dir=working_dir,
                    execution_working_dir=execution_working_dir,
                    relative_paths=("out", "scratch"),
                )

            def _sync_controls() -> None:
                exec_runner_module._sync_direct_exec_runtime_control_paths_to_execution(  # noqa: SLF001
                    source_working_dir=working_dir,
                    execution_working_dir=execution_working_dir,
                    relative_paths=exec_runner_module._DIRECT_EXEC_RUNTIME_CONTROL_PATHS,  # noqa: SLF001
                )

            task_file_payload = exec_runner_module.load_task_file(
                execution_working_dir / "task.json"
            )
            supervision_callback = kwargs.get("supervision_callback")
            termination_decision = None
            invalid_task_file = _blank_recipe_task_file_answers(
                task_file_payload=task_file_payload,
            )
            invalid_attempt_count = 2 if call_index > 1 else 1
            for index in range(1, invalid_attempt_count + 1):
                _write_workspace_task_file_result(
                    self,
                    working_dir=working_dir,
                    execution_working_dir=execution_working_dir,
                    payload=invalid_task_file,
                )
                if supervision_callback is not None:
                    termination_decision = supervision_callback(
                        CodexExecLiveSnapshot(
                            elapsed_seconds=0.1 * index,
                            last_event_seconds_ago=0.0,
                            event_count=index,
                            command_execution_count=0,
                            reasoning_item_count=0,
                            last_command=None,
                            last_command_repeat_count=0,
                            has_final_agent_message=False,
                            timeout_seconds=kwargs.get("timeout_seconds"),
                            source_working_dir=str(working_dir),
                            execution_working_dir=str(execution_working_dir),
                        )
                    )
                    _sync_controls()
            if termination_decision is None:
                termination_decision = exec_runner_module.CodexExecSupervisionDecision.terminate(
                    reason_code="workspace_current_task_validation_budget_exhausted",
                    supervision_state="completed",
                )
            response_text = "Stopped after local budget exhaustion."
            usage = {
                "input_tokens": 10,
                "cached_input_tokens": 0,
                "output_tokens": 3,
                "reasoning_tokens": 0,
            }
            events = (
                {"type": "thread.started"},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": response_text},
                },
                {"type": "turn.completed", "usage": usage},
            )
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=None,
                prompt_text=execution_prompt_text,
                response_text=response_text,
                turn_failed_message=None,
                events=events,
                usage=usage,
                stdout_text="\n".join(json.dumps(event) for event in events) + "\n",
                source_working_dir=str(working_dir),
                execution_working_dir=str(execution_working_dir),
                execution_agents_path=str(prepared.agents_path),
                duration_ms=1,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:00Z",
                workspace_mode="taskfile",
                supervision_state=termination_decision.supervision_state,
                supervision_reason_code=termination_decision.reason_code,
                supervision_reason_detail=termination_decision.reason_detail,
                supervision_retryable=termination_decision.retryable,
            )

    runner = _BudgetExhaustedRunner(output_builder=_output_builder)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    assert [call["mode"] for call in runner.calls] == [
        "taskfile",
        "taskfile",
    ]
    shard_root = (
        apply_result.llm_raw_dir
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
        / "shards"
        / "recipe-shard-0000-r0000-r0000"
    )
    repair_status = json.loads((shard_root / "repair_status.json").read_text(encoding="utf-8"))
    proposal = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "proposals"
            / "recipe-shard-0000-r0000-r0000.json"
        ).read_text(encoding="utf-8")
    )
    promotion_report = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "promotion_report.json"
        ).read_text(encoding="utf-8")
    )

    assert repair_status["repair_status"] == "failed"
    assert proposal["repair_attempted"] is True
    assert proposal["validation_metadata"]["task_status_by_task_id"][
        "recipe-shard-0000-r0000-r0000"
    ]["task_status"] == "failed_after_repair"
    assert promotion_report["task_counts"]["failed_after_repair"] == 1


@pytest.mark.parametrize(
    ("supervision_state", "continuation_state", "terminal_reason"),
    [
        (
            "watchdog_killed",
            "continuation_impossible",
            "worker_stopped_after_validation_failure",
        ),
        (
            "completed",
            "continuation_unavailable",
            "worker_session_ended_after_validation_failure",
        ),
    ],
)
def test_orchestrator_repairs_after_task_file_continuation_is_lost(
    tmp_path: Path,
    supervision_state: str,
    continuation_state: str,
    terminal_reason: str,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )

    def _output_builder(payload: dict[str, object] | None) -> dict[str, object]:
        assert payload is not None
        if payload.get("repair_mode") == "recipe":
            return _build_valid_recipe_task_output(payload["authoritative_input"])
        return _build_valid_recipe_task_output(payload)

    class _ContinuationLostRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
            working_dir = Path(kwargs["working_dir"])
            process_env = exec_runner_module._merge_env(kwargs["env"])
            prepared = exec_runner_module.prepare_direct_exec_workspace(
                source_working_dir=working_dir,
                env=process_env,
                task_label=kwargs.get("workspace_task_label"),
                mode="taskfile",
            )
            execution_working_dir = prepared.execution_working_dir
            execution_prompt_text = exec_runner_module.rewrite_direct_exec_prompt_paths(
                prompt_text=kwargs["prompt_text"],
                source_working_dir=working_dir,
                execution_working_dir=execution_working_dir,
            )
            self.calls.append(
                {
                    "mode": "taskfile",
                    "prompt_text": execution_prompt_text,
                    "input_payload": None,
                    "working_dir": str(working_dir),
                    "execution_working_dir": str(execution_working_dir),
                }
            )
            call_index = len(self.calls)

            def _sync_outputs() -> None:
                exec_runner_module._sync_direct_exec_workspace_paths(  # noqa: SLF001
                    source_working_dir=working_dir,
                    execution_working_dir=execution_working_dir,
                    relative_paths=("out", "scratch"),
                )

            def _sync_controls() -> None:
                exec_runner_module._sync_direct_exec_runtime_control_paths_to_execution(  # noqa: SLF001
                    source_working_dir=working_dir,
                    execution_working_dir=execution_working_dir,
                    relative_paths=exec_runner_module._DIRECT_EXEC_RUNTIME_CONTROL_PATHS,  # noqa: SLF001
                )

            if call_index == 1:
                task_file_payload = exec_runner_module.load_task_file(
                    execution_working_dir / "task.json"
                )
                _write_workspace_task_file_result(
                    self,
                    working_dir=working_dir,
                    execution_working_dir=execution_working_dir,
                    payload=_blank_recipe_task_file_answers(
                        task_file_payload=task_file_payload,
                    ),
                )
            supervision_callback = kwargs.get("supervision_callback")
            if supervision_callback is not None:
                decision = supervision_callback(
                    CodexExecLiveSnapshot(
                        elapsed_seconds=0.1,
                        last_event_seconds_ago=0.0,
                        event_count=1,
                        command_execution_count=0,
                        reasoning_item_count=0,
                        last_command=None,
                        last_command_repeat_count=0,
                        has_final_agent_message=False,
                        timeout_seconds=kwargs.get("timeout_seconds"),
                        source_working_dir=str(working_dir),
                        execution_working_dir=str(execution_working_dir),
                    )
                )
                assert decision is None
                _sync_controls()

            response_text = "Stopped after validation failure."
            usage = {
                "input_tokens": 10,
                "cached_input_tokens": 0,
                "output_tokens": 2,
                "reasoning_tokens": 0,
            }
            events = (
                {"type": "thread.started"},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": response_text},
                },
                {"type": "turn.completed", "usage": usage},
            )
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=None,
                prompt_text=execution_prompt_text,
                response_text=response_text,
                turn_failed_message=None,
                events=events,
                usage=usage,
                stdout_text="\n".join(json.dumps(event) for event in events) + "\n",
                source_working_dir=str(working_dir),
                execution_working_dir=str(execution_working_dir),
                execution_agents_path=str(prepared.agents_path),
                duration_ms=1,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:00Z",
                workspace_mode="taskfile",
                supervision_state=supervision_state,
                supervision_reason_code=f"{supervision_state}_after_validation_failure",
                supervision_reason_detail="worker stopped before rewriting the invalid draft",
                supervision_retryable=False,
            )

    runner = _ContinuationLostRunner(output_builder=_output_builder)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    assert [call["mode"] for call in runner.calls] == [
        "taskfile",
        "taskfile",
    ]
    shard_root = (
        apply_result.llm_raw_dir
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
        / "shards"
        / "recipe-shard-0000-r0000-r0000"
    )
    repair_status = json.loads((shard_root / "repair_status.json").read_text(encoding="utf-8"))
    proposal = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "proposals"
            / "recipe-shard-0000-r0000-r0000.json"
        ).read_text(encoding="utf-8")
    )

    assert repair_status["repair_status"] == "not_attempted"
    assert proposal["repair_attempted"] is False
    assert proposal["state"] == supervision_state
    assert [call["mode"] for call in runner.calls] == [
        "taskfile",
        "taskfile",
    ]
    expected_task_status = (
        "assigned_to_worker" if supervision_state == "watchdog_killed" else "invalid"
    )
    assert proposal["validation_metadata"]["task_status_by_task_id"][
        "recipe-shard-0000-r0000-r0000"
    ]["task_status"] == expected_task_status


def test_preflight_recipe_shard_rejects_missing_model_facing_recipes() -> None:
    shard = ShardManifestEntryV1(
        shard_id="recipe-shard-0000-r0000-r0000",
        owned_ids=("urn:recipe:test:toast",),
        input_payload={"v": "1", "sid": "recipe-shard-0000-r0000-r0000", "r": []},
    )

    assert _preflight_recipe_shard(shard) == {
        "reason_code": "preflight_invalid_shard_payload",
        "reason_detail": "recipe shard has no model-facing recipes",
    }
