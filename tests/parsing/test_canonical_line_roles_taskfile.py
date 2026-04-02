from __future__ import annotations

import tests.parsing.canonical_line_role_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_label_atomic_lines_records_workspace_warnings_without_killing_shards(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:watchdog:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    class _WatchdogRunner(FakeCodexExecRunner):
        def _watchdog_result(
            self,
            result,
            *,
            supervision_callback=None,
            timeout_seconds=None,
        ):  # noqa: ANN001
            decision = None
            if supervision_callback is not None:
                decision = supervision_callback(
                    CodexExecLiveSnapshot(
                        elapsed_seconds=4.2,
                        last_event_seconds_ago=0.0,
                        event_count=84,
                        command_execution_count=21,
                        reasoning_item_count=0,
                        last_command="/bin/bash -lc cat out/line-role-canonical-0001-a000000-a000000.json",
                        last_command_repeat_count=2,
                        has_final_agent_message=False,
                        timeout_seconds=timeout_seconds,
                    )
                )
            return result.__class__(
                command=result.command,
                subprocess_exit_code=result.subprocess_exit_code,
                output_schema_path=result.output_schema_path,
                prompt_text=result.prompt_text,
                response_text=None,
                turn_failed_message=(
                    None
                    if decision is not None
                    and str(decision.supervision_state or "").strip() == "completed"
                    else str(
                        (decision.reason_detail if decision is not None else None)
                        or "taskfile worker completed with warnings"
                    )
                ),
                events=(
                    {"type": "thread.started"},
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "id": "cmd-1",
                            "command": "/bin/bash -lc cat in/line-role-canonical-0001-a000000-a000000.json",
                        },
                    },
                ),
                usage={
                    "input_tokens": 7,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                },
                stderr_text=result.stderr_text,
                stdout_text=result.stdout_text,
                source_working_dir=result.source_working_dir,
                execution_working_dir=result.execution_working_dir,
                execution_agents_path=result.execution_agents_path,
                duration_ms=result.duration_ms,
                started_at_utc=result.started_at_utc,
                finished_at_utc=result.finished_at_utc,
                supervision_state=str(
                    (decision.supervision_state if decision is not None else None)
                    or "completed"
                ),
                supervision_reason_code=str(
                    (decision.reason_code if decision is not None else None)
                    or ""
                ),
                supervision_reason_detail=(
                    None
                    if decision is None
                    else str(decision.reason_detail or "")
                ),
                supervision_retryable=bool(decision.retryable if decision is not None else True),
            )

        def run_packet_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_packet_worker(*args, **kwargs)
            return self._watchdog_result(
                result,
                supervision_callback=kwargs.get("supervision_callback"),
                timeout_seconds=kwargs.get("timeout_seconds"),
            )

        def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_taskfile_worker(*args, **kwargs)
            return self._watchdog_result(
                result,
                supervision_callback=kwargs.get("supervision_callback"),
                timeout_seconds=kwargs.get("timeout_seconds"),
            )

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_WatchdogRunner(
            output_builder=_line_role_runner({0: "RECIPE_NOTES"}).output_builder
        ),
        live_llm_allowed=True,
    )

    assert len(predictions) == 1
    assert predictions[0].decided_by == "codex"
    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert telemetry_payload["summary"]["watchdog_killed_shard_count"] == 0
    assert telemetry_payload["summary"]["watchdog_recovered_shard_count"] == 0
    assert "watchdog_kills_detected" not in telemetry_payload["summary"]["pathological_flags"]
    assert "command_execution_detected" in telemetry_payload["summary"]["pathological_flags"]

    live_status_path = next(
        path
        for path in (tmp_path / "line-role-pipeline" / "runtime").rglob("live_status.json")
        if "shards" in path.parts
    )
    status_path = live_status_path.with_name("status.json")
    status_payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert status_payload["status"] == "validated"
    assert status_payload["state"] == "completed"

    live_status_payload = json.loads(live_status_path.read_text(encoding="utf-8"))
    assert live_status_payload["state"] == "completed_with_warnings"
    assert live_status_payload["warning_codes"] == [
        "single_file_shell_drift",
        "command_loop_without_output",
    ]
    assert live_status_payload["reason_code"] in {None, ""}


def test_line_role_strict_watchdog_still_kills_benign_commands_in_structured_mode(
    tmp_path: Path,
) -> None:
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.1,
            last_event_seconds_ago=0.0,
            event_count=2,
            command_execution_count=1,
            reasoning_item_count=0,
            last_command="/bin/bash -lc ls",
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is not None
    assert decision.reason_code == "watchdog_command_execution_forbidden"
    assert "ls" in str(decision.reason_detail or "")


def test_label_atomic_lines_allows_repo_helper_commands_without_immediate_kill(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:workspace-benign:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    class _WorkspaceCommandRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            supervision_callback = kwargs.get("supervision_callback")
            if supervision_callback is not None:
                for command_count, last_command in (
                    (
                        1,
                        "/bin/bash -lc 'python3 -m cookimport.llm.editable_task_file --summary'",
                    ),
                    (
                        2,
                        "/bin/bash -lc 'python3 -m cookimport.llm.editable_task_file --show-unit line::0'",
                    ),
                    (
                        3,
                        "/bin/bash -lc 'python3 -m cookimport.parsing.canonical_line_roles.same_session_handoff --status'",
                    ),
                ):
                    decision = supervision_callback(
                        CodexExecLiveSnapshot(
                            elapsed_seconds=0.1 * command_count,
                            last_event_seconds_ago=0.0,
                            event_count=2 * command_count,
                            command_execution_count=command_count,
                            reasoning_item_count=0,
                            last_command=last_command,
                            last_command_repeat_count=1,
                            has_final_agent_message=False,
                            timeout_seconds=kwargs.get("timeout_seconds"),
                        )
                    )
                    assert decision is None
            return super().run_taskfile_worker(*args, **kwargs)

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_WorkspaceCommandRunner(
            output_builder=_line_role_runner({0: "RECIPE_NOTES"}).output_builder
        ),
        live_llm_allowed=True,
    )

    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"
    assert predictions[0].decided_by == "codex"


def test_label_atomic_lines_allows_line_role_workspace_orientation_commands(
    tmp_path: Path,
) -> None:
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.1,
            last_event_seconds_ago=0.0,
            event_count=2,
            command_execution_count=1,
            reasoning_item_count=0,
            last_command="/bin/bash -lc ls",
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["last_command_policy"] == "single_file_orientation_command"
    assert live_status["last_command_policy_allowed"] is True
    assert live_status["last_command_boundary_violation_detected"] is False
    assert live_status["warning_codes"] == ["single_file_shell_drift"]


def test_line_role_workspace_watchdog_keeps_running_after_repeated_single_file_shell_drift(
    tmp_path: Path,
) -> None:
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
    )

    first = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.1,
            last_event_seconds_ago=0.0,
            event_count=2,
            command_execution_count=1,
            reasoning_item_count=0,
            last_command="/bin/bash -lc 'cat task.json'",
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )
    second = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2,
            last_event_seconds_ago=0.0,
            event_count=4,
            command_execution_count=2,
            reasoning_item_count=0,
            last_command="/bin/bash -lc ls",
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert first is None
    assert second is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["warning_codes"] == ["single_file_shell_drift"]
    assert live_status["last_command_policy"] == "single_file_orientation_command"


def test_line_role_workspace_watchdog_observes_output_stabilization_without_forcing_exit(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / "line-role-canonical-0001-a000000-a000000.json"
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
        expected_workspace_output_paths=[output_path],
    )
    output_path.write_text(
        json.dumps(
            {
                "rows": [
                    {"atomic_index": 0, "label": "RECIPE_NOTES"},
                ]
            }
        ),
        encoding="utf-8",
    )

    first = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.4,
            last_event_seconds_ago=0.0,
            event_count=4,
            command_execution_count=1,
            reasoning_item_count=0,
            last_command="/bin/bash -lc cat out/line-role-canonical-0001-a000000-a000000.json",
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )
    second = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.7,
            last_event_seconds_ago=0.0,
            event_count=5,
            command_execution_count=2,
            reasoning_item_count=0,
            last_command="/bin/bash -lc cat out/line-role-canonical-0001-a000000-a000000.json",
            last_command_repeat_count=2,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )
    second_live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    third = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.9,
            last_event_seconds_ago=0.0,
            event_count=6,
            command_execution_count=2,
            reasoning_item_count=0,
            agent_message_count=1,
            last_command="/bin/bash -lc cat out/line-role-canonical-0001-a000000-a000000.json",
            last_command_repeat_count=2,
            has_final_agent_message=True,
            timeout_seconds=30,
        )
    )

    assert first is None
    assert second is None
    assert second_live_status["state"] == "running_with_warnings"
    assert second_live_status["warning_codes"] == ["single_file_shell_drift"]
    assert second_live_status["workspace_completion_waiting_for_exit"] is False
    assert second_live_status["workspace_completion_post_signal_observed"] is False
    assert third is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["state"] == "running_with_warnings"
    assert live_status["reason_code"] is None
    assert live_status["workspace_output_complete"] is True
    assert live_status["workspace_output_stable_passes"] >= 2
    assert live_status["workspace_completion_post_signal_observed"] is False


def test_line_role_workspace_watchdog_starts_final_message_missing_output_grace_window(
    tmp_path: Path,
) -> None:
    grace_seconds = float(
        canonical_line_roles_module._LINE_ROLE_FINAL_MESSAGE_MISSING_OUTPUT_GRACE_SECONDS  # noqa: SLF001
    )
    output_path = tmp_path / "out" / "line-role-canonical-0001-a000000-a000000.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
        expected_workspace_output_paths=[output_path],
    )

    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=1.0,
            last_event_seconds_ago=0.0,
            event_count=3,
            command_execution_count=0,
            reasoning_item_count=0,
            last_command=None,
            last_command_repeat_count=0,
            has_final_agent_message=True,
            agent_message_count=1,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["final_message_missing_output_grace_active"] is True
    assert (
        live_status["final_message_missing_output_started_at_elapsed_seconds"] == 1.0
    )
    assert live_status["final_message_missing_output_grace_seconds"] == grace_seconds
    assert (
        live_status["final_message_missing_output_deadline_elapsed_seconds"]
        == 1.0 + grace_seconds
    )
    assert live_status["final_message_missing_output_deadline_reached"] is False
    assert live_status["reason_code"] is None


def test_line_role_workspace_watchdog_kills_incomplete_progress_summary_immediately(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "out" / "line-role-canonical-0001-a000000-a000000.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
        expected_workspace_output_paths=[output_path],
    )

    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.3,
            last_event_seconds_ago=0.0,
            event_count=4,
            command_execution_count=2,
            reasoning_item_count=1,
            last_command="/bin/bash -lc 'task-show-unanswered --limit 5'",
            last_command_repeat_count=1,
            has_final_agent_message=True,
            agent_message_count=1,
            timeout_seconds=30,
            final_agent_message_text=(
                "- I reviewed the first chunk and updated `task.json` for those rows.\n"
                "- The rest of the shard still needs labeling, and I haven't run "
                "`task-handoff` yet."
            ),
        )
    )

    assert decision is not None
    assert decision.reason_code == "workspace_final_message_incomplete_progress"
    assert decision.supervision_state == "watchdog_killed"
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["reason_code"] == "workspace_final_message_incomplete_progress"
    assert live_status["final_message_missing_output_grace_active"] is False


def test_line_role_workspace_watchdog_allows_output_to_land_during_final_message_grace_window(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "out" / "line-role-canonical-0001-a000000-a000000.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
        expected_workspace_output_paths=[output_path],
    )

    first = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.4,
            last_event_seconds_ago=0.0,
            event_count=2,
            command_execution_count=0,
            reasoning_item_count=0,
            last_command=None,
            last_command_repeat_count=0,
            has_final_agent_message=True,
            agent_message_count=1,
            timeout_seconds=30,
        )
    )
    output_path.write_text(
        json.dumps({"rows": [{"atomic_index": 0, "label": "RECIPE_NOTES"}]}),
        encoding="utf-8",
    )
    second = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=1.2,
            last_event_seconds_ago=0.0,
            event_count=3,
            command_execution_count=0,
            reasoning_item_count=0,
            last_command=None,
            last_command_repeat_count=0,
            has_final_agent_message=True,
            agent_message_count=1,
            timeout_seconds=30,
        )
    )

    assert first is None
    assert second is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["final_message_missing_output_grace_active"] is False
    assert live_status["workspace_output_complete"] is True
    assert live_status["reason_code"] is None


def test_line_role_workspace_watchdog_kills_after_final_message_missing_output_grace_window(
    tmp_path: Path,
) -> None:
    grace_seconds = float(
        canonical_line_roles_module._LINE_ROLE_FINAL_MESSAGE_MISSING_OUTPUT_GRACE_SECONDS  # noqa: SLF001
    )
    output_path = tmp_path / "out" / "line-role-canonical-0001-a000000-a000000.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
        expected_workspace_output_paths=[output_path],
    )

    first = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2,
            last_event_seconds_ago=0.0,
            event_count=2,
            command_execution_count=0,
            reasoning_item_count=0,
            last_command=None,
            last_command_repeat_count=0,
            has_final_agent_message=True,
            agent_message_count=1,
            timeout_seconds=30,
        )
    )
    second = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2 + grace_seconds + 0.1,
            last_event_seconds_ago=0.0,
            event_count=3,
            command_execution_count=0,
            reasoning_item_count=0,
            last_command=None,
            last_command_repeat_count=0,
            has_final_agent_message=True,
            agent_message_count=1,
            timeout_seconds=30,
        )
    )
    third = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2 + grace_seconds + 0.2,
            last_event_seconds_ago=0.0,
            event_count=4,
            command_execution_count=0,
            reasoning_item_count=0,
            last_command=None,
            last_command_repeat_count=0,
            has_final_agent_message=True,
            agent_message_count=1,
            timeout_seconds=30,
        )
    )

    assert first is None
    assert second is None
    assert third is not None
    assert third.reason_code == "workspace_final_message_missing_output"
    assert third.supervision_state == "watchdog_killed"
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["final_message_missing_output_deadline_reached"] is True
    assert live_status["final_message_missing_output_deadline_passes"] == 2
    assert live_status["reason_code"] == "workspace_final_message_missing_output"


def test_line_role_workspace_watchdog_completes_after_authoritative_same_session_success(
    tmp_path: Path,
) -> None:
    quiescence_seconds = float(
        canonical_line_roles_module._LINE_ROLE_WORKSPACE_COMPLETION_QUIESCENCE_SECONDS  # noqa: SLF001
    )
    output_path = tmp_path / "out" / "line-role-canonical-0001-a000000-a000000.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text('{"rows":[{"atomic_index":0,"label":"RECIPE_NOTES"}]}\n', encoding="utf-8")
    state_path = tmp_path / "_repo_control" / "line_role_same_session_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "completed": True,
                "final_status": "completed",
                "completed_shard_count": 1,
                "same_session_transition_count": 1,
                "validation_count": 1,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        same_session_state_path=state_path,
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
        expected_workspace_output_paths=[output_path],
        workspace_completion_quiescence_seconds=2.0,
    )

    first = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2,
            last_event_seconds_ago=0.0,
            event_count=2,
            command_execution_count=0,
            reasoning_item_count=0,
            last_command=None,
            last_command_repeat_count=0,
            has_final_agent_message=True,
            agent_message_count=1,
            timeout_seconds=30,
        )
    )
    second = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2 + quiescence_seconds + 0.1,
            last_event_seconds_ago=quiescence_seconds + 0.1,
            event_count=3,
            command_execution_count=0,
            reasoning_item_count=0,
            last_command=None,
            last_command_repeat_count=0,
            has_final_agent_message=True,
            agent_message_count=1,
            timeout_seconds=30,
        )
    )

    assert first is None
    assert second is not None
    assert second.supervision_state == "completed"
    assert second.reason_code in {None, ""}
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["state"] == "completed"
    assert live_status["same_session_completed"] is True
    assert live_status["workspace_authoritative_completion_ready"] is True
    assert live_status["workspace_completion_waiting_for_exit"] is True
    assert live_status["reason_code"] in {None, ""}


def test_line_role_workspace_watchdog_waits_when_helper_completed_but_outputs_not_yet_present(
    tmp_path: Path,
) -> None:
    quiescence_seconds = float(
        canonical_line_roles_module._LINE_ROLE_WORKSPACE_COMPLETION_QUIESCENCE_SECONDS  # noqa: SLF001
    )
    output_path = tmp_path / "out" / "line-role-canonical-0001-a000000-a000000.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    state_path = tmp_path / "_repo_control" / "line_role_same_session_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "completed": True,
                "final_status": "completed",
                "completed_shard_count": 1,
                "same_session_transition_count": 1,
                "validation_count": 1,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        same_session_state_path=state_path,
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
        expected_workspace_output_paths=[output_path],
        workspace_completion_quiescence_seconds=2.0,
    )

    first = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2,
            last_event_seconds_ago=0.0,
            event_count=2,
            command_execution_count=0,
            reasoning_item_count=0,
            last_command=None,
            last_command_repeat_count=0,
            has_final_agent_message=True,
            agent_message_count=1,
            timeout_seconds=30,
        )
    )
    second = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2 + quiescence_seconds + 0.1,
            last_event_seconds_ago=quiescence_seconds + 0.1,
            event_count=3,
            command_execution_count=0,
            reasoning_item_count=0,
            last_command=None,
            last_command_repeat_count=0,
            has_final_agent_message=True,
            agent_message_count=1,
            timeout_seconds=30,
        )
    )

    assert first is None
    assert second is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["same_session_completed"] is True
    assert live_status["workspace_authoritative_completion_ready"] is False
    assert live_status["reason_code"] is None
    assert live_status["final_message_missing_output_grace_active"] is False


def test_line_role_workspace_watchdog_waits_for_output_visibility_after_helper_reports_completed(
    tmp_path: Path,
) -> None:
    quiescence_seconds = float(
        canonical_line_roles_module._LINE_ROLE_WORKSPACE_COMPLETION_QUIESCENCE_SECONDS  # noqa: SLF001
    )
    output_path = tmp_path / "out" / "line-role-canonical-0001-a000000-a000000.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    state_path = tmp_path / "_repo_control" / "line_role_same_session_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    helper_summary = _completed_line_role_helper_command()
    summary_command = _completed_task_file_summary_command()
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        same_session_state_path=state_path,
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
        expected_workspace_output_paths=[output_path],
        workspace_completion_quiescence_seconds=2.0,
    )

    first = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2,
            last_event_seconds_ago=0.0,
            event_count=2,
            command_execution_count=2,
            reasoning_item_count=0,
            last_command=summary_command.command,
            last_command_repeat_count=1,
            has_final_agent_message=True,
            agent_message_count=1,
            timeout_seconds=30,
            last_completed_command=summary_command,
            last_completed_stage_helper_command=helper_summary,
        )
    )

    state_path.write_text(
        json.dumps(
            {
                "completed": True,
                "final_status": "completed",
                "completed_shard_count": 1,
                "same_session_transition_count": 1,
                "validation_count": 1,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    output_path.write_text(
        json.dumps({"rows": [{"atomic_index": 0, "label": "RECIPE_NOTES"}]}),
        encoding="utf-8",
    )

    second = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.6,
            last_event_seconds_ago=0.0,
            event_count=3,
            command_execution_count=2,
            reasoning_item_count=0,
            last_command=summary_command.command,
            last_command_repeat_count=1,
            has_final_agent_message=True,
            agent_message_count=1,
            timeout_seconds=30,
            last_completed_command=summary_command,
            last_completed_stage_helper_command=helper_summary,
        )
    )
    third = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.6 + quiescence_seconds + 0.1,
            last_event_seconds_ago=quiescence_seconds + 0.1,
            event_count=4,
            command_execution_count=2,
            reasoning_item_count=0,
            last_command=summary_command.command,
            last_command_repeat_count=1,
            has_final_agent_message=True,
            agent_message_count=1,
            timeout_seconds=30,
            last_completed_command=summary_command,
            last_completed_stage_helper_command=helper_summary,
        )
    )

    assert first is None
    assert second is None
    assert third is not None
    assert third.supervision_state == "completed"
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["helper_completed_in_event_stream"] is True
    assert live_status["workspace_waiting_for_helper_visibility"] is False
    assert live_status["reason_code"] in {None, ""}


@pytest.mark.parametrize(
    ("diagnosis_code", "recoverable", "summary"),
    [
        ("completed", False, "same-session helper already completed this workspace"),
        (
            "answers_present_helper_not_run",
            True,
            "task.json contains saved answers but the same-session helper has not produced out/<shard_id>.json yet",
        ),
        (
            "ready_for_validation",
            True,
            "answers are present and the same-session helper still needs to validate and install out/<shard_id>.json",
        ),
        (
            "repair_ready_helper_not_run",
            True,
            "repair answers are present but the same-session helper has not installed out/<shard_id>.json yet",
        ),
        ("awaiting_answers", False, "task.json still has blank answer objects"),
        (
            "repair_answers_missing",
            False,
            "repair mode is active but corrected answers are still missing",
        ),
        ("unknown_code", False, None),
    ],
)
def test_line_role_recovery_guidance_maps_diagnosis_codes(
    diagnosis_code: str,
    recoverable: bool,
    summary: str | None,
) -> None:
    assert _line_role_recovery_guidance_for_diagnosis(diagnosis_code) == (
        recoverable,
        summary,
    )


def test_label_atomic_lines_allows_line_role_jq_fallback_operator_output_command(
    tmp_path: Path,
) -> None:
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.1,
            last_event_seconds_ago=0.0,
            event_count=2,
            command_execution_count=1,
            reasoning_item_count=0,
            last_command=(
                "/bin/bash -lc \"jq '{rows: .rows | map({atomic_index: .[0], "
                "label: ({\\\"L0\\\":\\\"RECIPE_TITLE\\\",\\\"L1\\\":\\\"INGREDIENT_LINE\\\"}"
                "[.[1]] // \\\"OTHER\\\")})}' "
                "in/line-role-canonical-0001-a000000-a000000.json "
                "> out/line-role-canonical-0001-a000000-a000000.json\""
            ),
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["state"] == "running_with_warnings"
    assert live_status["last_command_policy"] == "single_file_task_ad_hoc_transform"
    assert live_status["last_command_policy_allowed"] is True
    assert live_status["last_command_boundary_violation_detected"] is False
    assert live_status["warning_codes"] == ["single_file_shell_drift"]


def test_label_atomic_lines_allows_line_role_workspace_cp_between_scratch_and_out(
    tmp_path: Path,
) -> None:
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.1,
            last_event_seconds_ago=0.0,
            event_count=2,
            command_execution_count=1,
            reasoning_item_count=0,
            last_command=(
                '/bin/bash -lc "cp scratch/line-role-canonical-0001-a000000-a000294.task-001.json '
                'out/line-role-canonical-0001-a000000-a000294.task-001.json"'
            ),
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["last_command_policy_allowed"] is True
    assert live_status["last_command_boundary_violation_detected"] is False


def test_label_atomic_lines_allows_line_role_node_transform(
    tmp_path: Path,
) -> None:
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.1,
            last_event_seconds_ago=0.0,
            event_count=2,
            command_execution_count=1,
            reasoning_item_count=0,
            last_command=(
                "/bin/bash -lc \"node -e "
                "\\\"const fs=require('fs'); "
                "fs.writeFileSync('out/line-role-canonical-0001-a000000-a000000.json', "
                "fs.readFileSync('in/line-role-canonical-0001-a000000-a000000.json', 'utf8'));\\\"\""
            ),
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["state"] == "running_with_warnings"
    assert live_status["last_command_policy"] == "single_file_task_ad_hoc_transform"
    assert live_status["last_command_policy_allowed"] is True
    assert live_status["last_command_boundary_violation_detected"] is False
    assert live_status["warning_codes"] == ["single_file_shell_drift"]
