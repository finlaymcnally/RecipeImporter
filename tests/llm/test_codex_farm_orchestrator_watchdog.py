from __future__ import annotations

import tests.llm.codex_farm_orchestrator_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_orchestrator_marks_watchdog_killed_recipe_shards_in_summary(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )

    class _WatchdogRunner(FakeCodexExecRunner):
        def _watchdog_result(
            self,
            result,
            *,
            supervision_callback=None,
            timeout_seconds=None,
        ):  # noqa: ANN001
            if supervision_callback is not None:
                supervision_callback(
                    CodexExecLiveSnapshot(
                        elapsed_seconds=0.1,
                        last_event_seconds_ago=0.0,
                        event_count=2,
                        command_execution_count=1,
                        reasoning_item_count=0,
                        last_command="python -c 'print(1)'",
                        last_command_repeat_count=1,
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
                turn_failed_message="strict JSON stage attempted tool use",
                events=(
                    {"type": "thread.started"},
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "id": "cmd-1",
                            "command": "python -c 'print(1)'",
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
                supervision_state="watchdog_killed",
                supervision_reason_code="watchdog_command_execution_forbidden",
                supervision_reason_detail="strict JSON stage attempted tool use",
                supervision_retryable=False,
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

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=_WatchdogRunner(
            output_builder=lambda payload: {
                "v": "1",
                "sid": payload.get("sid") if payload is not None else None,
                "r": [],
            }
        ),
    )

    process_summary = apply_result.llm_report["process_runs"]["recipe_correction"][
        "telemetry_report"
    ]["summary"]
    assert process_summary["watchdog_killed_shard_count"] == 1
    assert "watchdog_kills_detected" in process_summary["pathological_flags"]
    assert "command_execution_detected" in process_summary["pathological_flags"]

    shard_root = (
        apply_result.llm_raw_dir
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
        / "shards"
        / "recipe-shard-0000-r0000-r0000"
    )
    status_payload = json.loads((shard_root / "status.json").read_text(encoding="utf-8"))
    assert status_payload["status"] == "invalid"
    assert status_payload["state"] == "watchdog_killed"
    assert status_payload["reason_code"] == "watchdog_command_execution_forbidden"

    live_status_payload = json.loads(
        (shard_root / "live_status.json").read_text(encoding="utf-8")
    )
    assert live_status_payload["state"] == "watchdog_killed"
    assert live_status_payload["reason_code"] == "watchdog_command_execution_forbidden"


def _run_retryable_watchdog_fixture(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    )

    class _RetryingWatchdogRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_taskfile_worker(*args, **kwargs)
            working_dir = Path(kwargs["working_dir"])
            for output_path in (working_dir / "out").glob("*.json"):
                output_path.unlink()
            supervision_callback = kwargs.get("supervision_callback")
            if supervision_callback is not None:
                supervision_callback(
                    CodexExecLiveSnapshot(
                        elapsed_seconds=0.1,
                        last_event_seconds_ago=0.0,
                        event_count=2,
                        command_execution_count=1,
                        reasoning_item_count=0,
                        last_command=(
                            "/bin/bash -lc \"python3 - <<'PY'\n"
                            "from pathlib import Path\n"
                            "(Path('scratch') / 'task-001.json').read_text()\n"
                            "PY\""
                        ),
                        last_command_repeat_count=1,
                        has_final_agent_message=False,
                        timeout_seconds=kwargs.get("timeout_seconds"),
                    )
                )
            return result.__class__(
                command=result.command,
                subprocess_exit_code=result.subprocess_exit_code,
                output_schema_path=result.output_schema_path,
                prompt_text=result.prompt_text,
                response_text=None,
                turn_failed_message="taskfile worker attempted a forbidden command",
                events=(
                    {"type": "thread.started"},
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "id": "cmd-1",
                            "command": "python3 - <<'PY' ...",
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
                supervision_state="watchdog_killed",
                supervision_reason_code="watchdog_command_execution_forbidden",
                supervision_reason_detail="taskfile worker attempted a forbidden command",
                supervision_retryable=True,
            )

    runner = _RetryingWatchdogRunner(
        output_builder=lambda payload: {
            "v": "1",
            "sid": payload.get("sid") if payload is not None else None,
            "r": [
                {
                    "v": "1",
                    "rid": payload["authoritative_input"]["r"][0]["rid"]
                    if payload and payload.get("retry_mode") == "recipe_watchdog"
                    else payload["r"][0]["rid"],
                    "st": "repaired",
                    "sr": None,
                    "cr": {
                        "t": "Toast",
                        "i": ["1 slice bread", "1 tablespoon butter"],
                        "s": [
                            "Toast the bread until golden.",
                            "Spread with butter and serve hot.",
                        ],
                        "d": None,
                        "y": None,
                    },
                    "m": [],
                    "mr": "retry_pass",
                    "g": [],
                    "w": [],
                }
            ],
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    assert [call["mode"] for call in runner.calls] == ["taskfile"]
    process_summary = apply_result.llm_report["process_runs"]["recipe_correction"][
        "telemetry_report"
    ]["summary"]
    assert process_summary["watchdog_killed_shard_count"] == 1
    assert process_summary["watchdog_recovered_shard_count"] == 0

    shard_root = (
        apply_result.llm_raw_dir
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
        / "shards"
        / "recipe-shard-0000-r0000-r0000"
    )
    status_payload = json.loads((shard_root / "status.json").read_text(encoding="utf-8"))
    proposal_payload = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "proposals"
            / "recipe-shard-0000-r0000-r0000.json"
        ).read_text(encoding="utf-8")
    )
    retry_status_path = (
        apply_result.llm_raw_dir
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
        / "shards"
        / "recipe-shard-0000-r0000-r0000"
        / "watchdog_retry"
        / "status.json"
    )
    retry_status = (
        json.loads(retry_status_path.read_text(encoding="utf-8"))
        if retry_status_path.exists()
        else None
    )
    return {
        "runner": runner,
        "apply_result": apply_result,
        "process_summary": process_summary,
        "status_payload": status_payload,
        "proposal_payload": proposal_payload,
        "retry_status": retry_status,
    }


def test_orchestrator_recovers_retryable_watchdog_killed_recipe_shard(
    tmp_path: Path,
) -> None:
    fixture = _run_retryable_watchdog_fixture(tmp_path)
    runner = fixture["runner"]
    process_summary = fixture["process_summary"]

    assert [call["mode"] for call in runner.calls] == ["taskfile"]
    assert process_summary["watchdog_killed_shard_count"] == 1
    assert process_summary["watchdog_recovered_shard_count"] == 0


def test_orchestrator_persists_recovered_watchdog_shard_status_artifacts(
    tmp_path: Path,
) -> None:
    fixture = _run_retryable_watchdog_fixture(tmp_path)
    status_payload = fixture["status_payload"]
    proposal_payload = fixture["proposal_payload"]
    retry_status = fixture["retry_status"]

    assert status_payload["status"] == "validated"
    assert status_payload["state"] == "completed"
    assert status_payload["reason_code"] == "workspace_outputs_recovered"
    assert status_payload["raw_supervision_state"] == "watchdog_killed"
    assert status_payload["final_supervision_state"] == "completed"
    assert status_payload["finalization_path"] == "validated_after_watchdog"
    assert status_payload["repair_status"] == "not_attempted"
    assert proposal_payload["repair_status"] == "not_attempted"
    assert "watchdog_retry_status" not in status_payload
    assert "watchdog_retry_status" not in proposal_payload
    assert retry_status is None


def _run_packed_watchdog_retry_fixture(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    result.recipes.append(
        RecipeCandidate(
            name="Tea",
            identifier="urn:recipe:test:tea",
            recipeIngredient=["1 cup water", "1 tea bag"],
            recipeInstructions=["Boil the water.", "Steep the tea bag."],
            provenance={"location": {"start_block": 6, "end_block": 9}},
        )
    )
    result.raw_artifacts[0].content["blocks"].extend(
        [
            {"index": 6, "text": "Tea"},
            {"index": 7, "text": "1 cup water"},
            {"index": 8, "text": "1 tea bag"},
            {"index": 9, "text": "Boil the water. Steep the tea bag."},
        ]
    )
    settings = _build_run_settings(
        tmp_path / "pack",
        llm_recipe_pipeline=SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    ).model_copy(update={"recipe_worker_count": 1})

    class _PackedRetryRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
            result = super().run_taskfile_worker(**kwargs)
            out_dir = Path(str(kwargs["working_dir"])) / "out"
            for output_path in out_dir.glob("*.json"):
                output_path.unlink()
            return CodexExecRunResult(
                command=list(result.command),
                subprocess_exit_code=1,
                output_schema_path=result.output_schema_path,
                prompt_text=result.prompt_text,
                response_text=None,
                turn_failed_message="taskfile worker attempted a forbidden command",
                events=result.events
                + (
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "cmd_startup",
                            "type": "command_execution",
                            "command": "/bin/bash -lc 'pip install nope'",
                            "exit_code": 1,
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
                workspace_mode=result.workspace_mode,
                supervision_state="watchdog_killed",
                supervision_reason_code="watchdog_command_execution_forbidden",
                supervision_reason_detail="taskfile worker attempted a forbidden command",
                supervision_retryable=True,
            )

    runner = _PackedRetryRunner(
        output_builder=lambda payload: {
            "v": "1",
            "sid": payload.get("sid") if payload is not None else None,
            "r": [
                {
                    "v": "1",
                    "rid": recipe_payload["rid"],
                    "st": "repaired",
                    "sr": None,
                    "cr": {
                        "t": recipe_payload.get("h", {}).get("n") or recipe_payload["rid"],
                        "i": recipe_payload.get("h", {}).get("i", []),
                        "s": recipe_payload.get("h", {}).get("s", []),
                        "d": None,
                        "y": None,
                    },
                    "m": [],
                    "mr": "packed_retry_pass",
                    "g": [],
                    "w": [],
                }
                for recipe_payload in (
                    payload["authoritative_input"]["r"]
                    if payload and payload.get("retry_mode") == "recipe_watchdog"
                    else payload.get("r", [])
                )
            ],
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    assert [call["mode"] for call in runner.calls] == ["taskfile"]
    process_summary = apply_result.llm_report["process_runs"]["recipe_correction"][
        "telemetry_report"
    ]["summary"]
    assert process_summary["structured_followup_call_count"] == 0
    assert process_summary["watchdog_killed_shard_count"] == 1
    assert process_summary["watchdog_recovered_shard_count"] == 0

    shard_root = (
        apply_result.llm_raw_dir
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
        / "shards"
        / "recipe-shard-0000-r0000-r0000"
    )
    status_payload = json.loads((shard_root / "status.json").read_text(encoding="utf-8"))
    retry_status_path = shard_root / "watchdog_retry" / "status.json"
    retry_status = (
        json.loads(retry_status_path.read_text(encoding="utf-8"))
        if retry_status_path.exists()
        else None
    )
    return {
        "runner": runner,
        "process_summary": process_summary,
        "status_payload": status_payload,
        "retry_status": retry_status,
    }


def test_orchestrator_uses_one_packed_watchdog_retry_for_early_multi_task_worker_death(
    tmp_path: Path,
) -> None:
    fixture = _run_packed_watchdog_retry_fixture(tmp_path)
    runner = fixture["runner"]
    process_summary = fixture["process_summary"]

    assert [call["mode"] for call in runner.calls] == ["taskfile"]
    assert process_summary["structured_followup_call_count"] == 0
    assert process_summary["watchdog_killed_shard_count"] == 1
    assert process_summary["watchdog_recovered_shard_count"] == 0


def test_orchestrator_omits_legacy_watchdog_retry_fields_from_status_artifacts(
    tmp_path: Path,
) -> None:
    fixture = _run_packed_watchdog_retry_fixture(tmp_path)
    status_payload = fixture["status_payload"]
    retry_status = fixture["retry_status"]

    assert status_payload["status"] == "validated"
    assert status_payload["repair_status"] == "not_attempted"
    assert status_payload["finalization_path"] == "validated_after_watchdog"
    assert "watchdog_retry_status" not in status_payload
    assert "watchdog_retry_mode" not in status_payload
    assert retry_status is None
