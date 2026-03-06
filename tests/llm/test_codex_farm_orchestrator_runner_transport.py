from __future__ import annotations

import tests.llm.test_codex_farm_orchestrator as _base

# Reuse shared imports/helpers from the base orchestrator test module.
globals().update({
    name: value
    for name, value in _base.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_subprocess_runner_reports_missing_binary(tmp_path: Path) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")

    runner = SubprocessCodexFarmRunner(cmd="definitely-missing-codex-farm-binary")
    with pytest.raises(CodexFarmRunnerError):
        runner.run_pipeline("recipe.chunking.v1", in_dir, out_dir, {})


def test_subprocess_runner_passes_root_and_workspace_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    workspace_root = tmp_path / "workspace"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}
    calls: list[list[str]] = []

    def _fake_run(command, **kwargs):  # noqa: ANN001
        argv = list(command)
        calls.append(argv)
        captured["env"] = kwargs.get("env")
        if argv[1:3] == ["process", "--pipeline"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "run_id": "run-test-passes-root-and-workspace-flags",
                        "status": "completed",
                        "exit_code": 0,
                        "output_schema_path": str(schema_path),
                        "telemetry_report": {
                            "schema_version": 2,
                            "matched_rows": 0,
                            "insights": {},
                            "recommendations": {},
                            "tuning_playbook": {},
                        },
                    }
                ),
                stderr="",
            )
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "run-test-passes-root-and-workspace-flags",
                        "pipeline_id": "recipe.chunking.v1",
                        "flag_overrides": [],
                        "command_preview": "",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    run_result = runner.run_pipeline(
        "recipe.chunking.v1",
        in_dir,
        out_dir,
        {"EXTRA_ENV": "1"},
        root_dir=root_dir,
        workspace_root=workspace_root,
        model="gpt-test-model",
        reasoning_effort="low",
    )
    assert run_result.run_id == "run-test-passes-root-and-workspace-flags"
    assert run_result.process_exit_code == 0
    assert run_result.subprocess_exit_code == 0
    assert run_result.output_schema_path == str(schema_path)
    assert run_result.telemetry_report is not None
    assert run_result.telemetry_report["schema_version"] == 2
    assert run_result.autotune_report is not None
    assert run_result.autotune_report["schema_version"] == 1
    assert run_result.telemetry is not None
    assert run_result.telemetry.get("row_count") == 0

    command = calls[0]
    assert isinstance(command, list)
    assert "--root" in command
    assert str(root_dir) in command
    assert "--workspace-root" in command
    assert str(workspace_root) in command
    assert "--model" in command
    assert "gpt-test-model" in command
    assert "--reasoning-effort" in command
    assert "low" in command
    assert "--output-schema" in command
    assert str(schema_path) in command
    assert calls[1] == [
        "codex-farm",
        "run",
        "autotune",
        "--run-id",
        "run-test-passes-root-and-workspace-flags",
        "--json",
        "--pipeline",
        "recipe.chunking.v1",
    ]


def test_subprocess_runner_appends_benchmark_mode_flag_from_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    calls: list[list[str]] = []

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        calls.append(argv)
        if argv[1:3] == ["process", "--pipeline"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "run_id": "run-benchmark-mode-flag",
                        "status": "completed",
                        "exit_code": 0,
                        "output_schema_path": str(schema_path),
                    }
                ),
                stderr="",
            )
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "run-benchmark-mode-flag",
                        "pipeline_id": "recipe.chunking.v1",
                        "flag_overrides": [],
                        "command_preview": "",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    run_result = runner.run_pipeline(
        "recipe.chunking.v1",
        in_dir,
        out_dir,
        {"COOKIMPORT_CODEX_FARM_RECIPE_MODE": "benchmark"},
        root_dir=root_dir,
    )

    assert run_result.run_id == "run-benchmark-mode-flag"
    process_command = calls[0]
    assert "--benchmark-mode" in process_command
    mode_index = process_command.index("--benchmark-mode")
    assert process_command[mode_index + 1] == "benchmark"


def test_subprocess_runner_retries_extract_without_benchmark_mode_flag_when_unsupported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    process_calls: list[list[str]] = []
    process_attempt = {"count": 0}

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        if argv[1:3] == ["process", "--pipeline"]:
            process_calls.append(argv)
            process_attempt["count"] += 1
            if process_attempt["count"] == 1:
                return SimpleNamespace(
                    returncode=2,
                    stdout="",
                    stderr="error: unrecognized arguments: --benchmark-mode\n",
                )
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "run_id": "run-extract-fallback",
                        "status": "completed",
                        "exit_code": 0,
                        "output_schema_path": str(schema_path),
                    }
                ),
                stderr="",
            )
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "run-extract-fallback",
                        "pipeline_id": "recipe.chunking.v1",
                        "flag_overrides": [],
                        "command_preview": "",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    run_result = runner.run_pipeline(
        "recipe.chunking.v1",
        in_dir,
        out_dir,
        {"COOKIMPORT_CODEX_FARM_RECIPE_MODE": "extract"},
        root_dir=root_dir,
    )

    assert run_result.run_id == "run-extract-fallback"
    assert len(process_calls) == 2
    assert "--benchmark-mode" in process_calls[0]
    assert "--benchmark-mode" not in process_calls[1]


def test_subprocess_runner_fails_when_benchmark_mode_flag_is_unsupported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    process_calls: list[list[str]] = []

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        if argv[1:3] == ["process", "--pipeline"]:
            process_calls.append(argv)
            return SimpleNamespace(
                returncode=2,
                stdout="",
                stderr="error: unrecognized arguments: --benchmark-mode\n",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    with pytest.raises(CodexFarmRunnerError, match="does not support --benchmark-mode"):
        runner.run_pipeline(
            "recipe.chunking.v1",
            in_dir,
            out_dir,
            {"COOKIMPORT_CODEX_FARM_RECIPE_MODE": "benchmark"},
            root_dir=root_dir,
        )
    assert len(process_calls) == 1


def test_subprocess_runner_emits_progress_callback_from_progress_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    popen_command: list[str] | None = None

    class _FakePopen:
        def __init__(self, command, **_kwargs):  # noqa: ANN001
            nonlocal popen_command
            popen_command = list(command)
            self.returncode = 0
            self.stdout = io.StringIO(
                json.dumps(
                    {
                        "run_id": "run-progress-events",
                        "status": "done",
                        "exit_code": 0,
                        "output_schema_path": str(schema_path),
                    }
                )
                + "\n"
            )
            self.stderr = io.StringIO(
                "\n".join(
                    [
                        "__codex_farm_progress__ "
                        + json.dumps(
                            {
                                "event": "run_started",
                                "status": "running",
                                "counts": {
                                    "queued": 1,
                                    "running": 1,
                                    "done": 0,
                                    "error": 0,
                                    "canceled": 0,
                                    "total": 2,
                                },
                                "progress": {"completed": 0},
                                "running_tasks": [
                                    {"input_path": str(in_dir / "r0000.json")},
                                ],
                            },
                            sort_keys=True,
                        ),
                        "__codex_farm_progress__ "
                        + json.dumps(
                            {
                                "event": "run_progress",
                                "status": "running",
                                "counts": {
                                    "queued": 1,
                                    "running": 1,
                                    "done": 0,
                                    "error": 0,
                                    "canceled": 0,
                                    "total": 2,
                                },
                                "progress": {"completed": 0},
                                "running_tasks": [
                                    {"input_path": str(in_dir / "r0001.json")},
                                ],
                            },
                            sort_keys=True,
                        ),
                        "__codex_farm_progress__ "
                        + json.dumps(
                            {
                                "event": "run_progress",
                                "status": "running",
                                "counts": {
                                    "queued": 0,
                                    "running": 1,
                                    "done": 1,
                                    "error": 0,
                                    "canceled": 0,
                                    "total": 2,
                                },
                                "progress": {"completed": 1},
                            },
                            sort_keys=True,
                        ),
                        "__codex_farm_progress__ "
                        + json.dumps(
                            {
                                "event": "run_finished",
                                "status": "done",
                                "counts": {
                                    "queued": 0,
                                    "running": 0,
                                    "done": 2,
                                    "error": 0,
                                    "canceled": 0,
                                    "total": 2,
                                },
                                "progress": {"completed": 2},
                            },
                            sort_keys=True,
                        ),
                    ]
                )
                + "\n"
            )

        def wait(self):  # noqa: D401
            return self.returncode

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "run-progress-events",
                        "pipeline_id": "recipe.chunking.v1",
                        "flag_overrides": [],
                        "command_preview": "",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.Popen", _FakePopen)
    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    progress_messages: list[str] = []
    runner = SubprocessCodexFarmRunner(
        cmd="codex-farm",
        progress_callback=progress_messages.append,
    )
    run_result = runner.run_pipeline(
        "recipe.chunking.v1",
        in_dir,
        out_dir,
        {},
        root_dir=root_dir,
    )

    assert run_result.run_id == "run-progress-events"
    assert popen_command is not None
    assert "--progress-events" in popen_command
    assert any("task 0/2" in message for message in progress_messages)
    assert any("task 1/2" in message for message in progress_messages)
    assert any("task 2/2" in message for message in progress_messages)
    assert sum(1 for message in progress_messages if "task 0/2" in message) >= 1
    assert any("active [r0000.json]" in message for message in progress_messages)
    assert any("active [r0001.json]" in message for message in progress_messages)


def test_subprocess_runner_retries_without_progress_events_when_flag_unsupported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    popen_command: list[str] | None = None
    run_calls: list[list[str]] = []

    class _UnsupportedProgressEventsPopen:
        def __init__(self, command, **_kwargs):  # noqa: ANN001
            nonlocal popen_command
            popen_command = list(command)
            self.returncode = 2
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("error: unrecognized arguments: --progress-events\n")

        def wait(self):  # noqa: D401
            return self.returncode

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        run_calls.append(argv)
        if argv[1:3] == ["process", "--pipeline"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "run_id": "run-progress-events-fallback",
                        "status": "done",
                        "exit_code": 0,
                        "output_schema_path": str(schema_path),
                    }
                ),
                stderr="",
            )
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "run-progress-events-fallback",
                        "pipeline_id": "recipe.chunking.v1",
                        "flag_overrides": [],
                        "command_preview": "",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_runner.subprocess.Popen",
        _UnsupportedProgressEventsPopen,
    )
    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    progress_messages: list[str] = []
    runner = SubprocessCodexFarmRunner(
        cmd="codex-farm",
        progress_callback=progress_messages.append,
    )
    run_result = runner.run_pipeline(
        "recipe.chunking.v1",
        in_dir,
        out_dir,
        {},
        root_dir=root_dir,
    )

    assert run_result.run_id == "run-progress-events-fallback"
    assert popen_command is not None
    assert "--progress-events" in popen_command
    assert run_calls
    assert "--progress-events" not in run_calls[0]
    assert any("--progress-events" in message for message in progress_messages)


def test_subprocess_runner_collects_codex_exec_activity_telemetry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    data_dir = tmp_path / "farm-data"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    telemetry_csv = data_dir / "codex_exec_activity.csv"

    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    fieldnames = [
        "logged_at_utc",
        "started_at_utc",
        "finished_at_utc",
        "duration_ms",
        "status",
        "exit_code",
        "accepted_nonzero_exit",
        "output_payload_present",
        "output_bytes",
        "output_sha256",
        "output_preview",
        "output_preview_chars",
        "output_preview_truncated",
        "codex_event_count",
        "codex_event_types_json",
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_total",
        "prompt_sha256",
        "prompt_chars",
        "pipeline_id",
        "run_id",
        "task_id",
        "worker_id",
        "input_path",
        "output_path",
        "heads_up_applied",
        "heads_up_tip_count",
        "heads_up_input_signature",
        "heads_up_tip_ids_json",
        "heads_up_tip_texts_json",
        "heads_up_tip_scores_json",
        "attempt_index",
        "retry_context_applied",
        "retry_previous_error",
        "retry_previous_error_chars",
        "retry_previous_error_sha256",
        "failure_category",
        "rate_limit_suspected",
        "stderr_tail",
        "stdout_tail",
    ]
    with telemetry_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "logged_at_utc": "2026-02-28T09:00:00.000Z",
                "started_at_utc": "2026-02-28T08:59:58.000Z",
                "finished_at_utc": "2026-02-28T09:00:00.000Z",
                "duration_ms": "2000",
                "status": "ok",
                "exit_code": "0",
                "accepted_nonzero_exit": "false",
                "output_payload_present": "true",
                "output_bytes": "321",
                "output_sha256": "abc123",
                "output_preview": "{\"bundle_version\":\"1\"}",
                "output_preview_chars": "22",
                "output_preview_truncated": "false",
                "codex_event_count": "4",
                "codex_event_types_json": json.dumps(
                    ["thread.started", "turn.completed"],
                    sort_keys=True,
                ),
                "tokens_input": "100",
                "tokens_cached_input": "20",
                "tokens_output": "30",
                "tokens_total": "130",
                "prompt_sha256": "prompt-sha",
                "prompt_chars": "999",
                "pipeline_id": "recipe.chunking.v1",
                "run_id": "run-123",
                "task_id": "task-1",
                "worker_id": "worker-a",
                "input_path": "/tmp/in.json",
                "output_path": "/tmp/out.json",
                "heads_up_applied": "true",
                "heads_up_tip_count": "2",
                "heads_up_input_signature": "sig-1",
                "heads_up_tip_ids_json": json.dumps(["tip-a", "tip-b"], sort_keys=True),
                "heads_up_tip_texts_json": json.dumps(["Tip A", "Tip B"], sort_keys=True),
                "heads_up_tip_scores_json": json.dumps([0.9, 0.2], sort_keys=True),
                "attempt_index": "2",
                "retry_context_applied": "true",
                "retry_previous_error": "schema validation failed",
                "retry_previous_error_chars": "24",
                "retry_previous_error_sha256": "retry-sha",
                "failure_category": "accepted_nonzero_exit",
                "rate_limit_suspected": "false",
                "stderr_tail": "",
                "stdout_tail": "",
            }
        )

    calls: list[list[str]] = []

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        calls.append(argv)
        if "process" in argv and "--pipeline" in argv:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "run_id": "run-123",
                        "status": "completed",
                        "exit_code": 0,
                        "output_schema_path": str(schema_path),
                        "telemetry_report": {
                            "schema_version": 2,
                            "matched_rows": 1,
                            "insights": {
                                "pass_forward_effectiveness": {
                                    "retry_context": {"rows_applied": 1},
                                }
                            },
                            "recommendations": {},
                            "tuning_playbook": {},
                        },
                    }
                ),
                stderr="",
            )
        if "run" in argv and "autotune" in argv:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "run-123",
                        "pipeline_id": "recipe.chunking.v1",
                        "flag_overrides": [
                            {
                                "flag": "--workers",
                                "current": "8",
                                "suggested": "4",
                            }
                        ],
                        "command_preview": "codex-farm process ... --workers 4",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd=f"codex-farm --data-dir {data_dir}")
    run_result = runner.run_pipeline(
        "recipe.chunking.v1",
        in_dir,
        out_dir,
        {},
        root_dir=root_dir,
    )

    assert run_result.run_id == "run-123"
    assert run_result.telemetry_report is not None
    assert run_result.telemetry_report["schema_version"] == 2
    assert run_result.telemetry_report["matched_rows"] == 1
    assert run_result.autotune_report is not None
    assert run_result.autotune_report["schema_version"] == 1
    assert run_result.autotune_report["flag_overrides"][0]["flag"] == "--workers"
    assert run_result.telemetry is not None
    assert run_result.telemetry["row_count"] == 1
    assert run_result.telemetry["summary"]["attempt_index_counts"] == {"2": 1}
    assert run_result.telemetry["summary"]["failure_category_counts"] == {
        "accepted_nonzero_exit": 1
    }
    rows = run_result.telemetry["rows"]
    assert len(rows) == 1
    assert rows[0]["heads_up_tip_ids"] == ["tip-a", "tip-b"]
    assert rows[0]["retry_context_applied"] is True
    assert rows[0]["output_sha256"] == "abc123"
    assert rows[0]["codex_event_types"] == ["thread.started", "turn.completed"]
    assert calls[1] == [
        "codex-farm",
        "--data-dir",
        str(data_dir),
        "run",
        "autotune",
        "--run-id",
        "run-123",
        "--json",
        "--pipeline",
        "recipe.chunking.v1",
    ]


def test_subprocess_runner_fails_before_process_when_output_schema_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/missing.schema.json",
            }
        ),
        encoding="utf-8",
    )

    called = {"value": False}

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        called["value"] = True
        raise AssertionError(f"subprocess.run should not be called: {command}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    with pytest.raises(CodexFarmRunnerError) as exc_info:
        runner.run_pipeline(
            "recipe.chunking.v1",
            in_dir,
            out_dir,
            {},
            root_dir=root_dir,
        )

    assert "Expected file path does not exist" in str(exc_info.value)
    assert called["value"] is False


def test_subprocess_runner_rejects_process_payload_missing_output_schema_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    def _fake_run(_command, **_kwargs):  # noqa: ANN001
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "run_id": "run-123",
                    "status": "completed",
                    "exit_code": 0,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    with pytest.raises(CodexFarmRunnerError) as exc_info:
        runner.run_pipeline(
            "recipe.chunking.v1",
            in_dir,
            out_dir,
            {},
            root_dir=root_dir,
        )
    assert "missing output_schema_path" in str(exc_info.value)


def test_list_codex_farm_models_uses_json_cli_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_run(command, **kwargs):  # noqa: ANN001
        captured["command"] = list(command)
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "slug": "gpt-5.3-codex",
                        "display_name": "GPT-5.3",
                        "description": "frontier",
                        "supported_reasoning_efforts": ["low", "medium"],
                    }
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    rows = list_codex_farm_models(cmd="/tmp/codex-farm")

    assert rows == [
        {
            "slug": "gpt-5.3-codex",
            "display_name": "GPT-5.3",
            "description": "frontier",
            "supported_reasoning_efforts": ["low", "medium"],
        }
    ]
    command = captured.get("command")
    assert isinstance(command, list)
    assert command == ["/tmp/codex-farm", "models", "list", "--json"]
    kwargs = captured.get("kwargs")
    assert isinstance(kwargs, dict)
    assert kwargs.get("text") is True
    assert kwargs.get("capture_output") is True
    assert kwargs.get("check") is False


def test_subprocess_runner_uses_run_errors_followup_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")

    calls: list[list[str]] = []

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        calls.append(argv)
        if argv[1:3] == ["process", "--pipeline"]:
            return SimpleNamespace(
                returncode=1,
                stdout=json.dumps(
                    {
                        "run_id": "run-123",
                        "status": "failed",
                        "exit_code": 1,
                        "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
                    }
                ),
                stderr="pipeline failed",
            )
        if argv[1:3] == ["run", "errors"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "errors": [
                            {"message": "simulated worker error"},
                        ]
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    with pytest.raises(CodexFarmRunnerError) as exc_info:
        runner.run_pipeline("recipe.chunking.v1", in_dir, out_dir, {})

    assert "run-123" in str(exc_info.value)
    assert "simulated worker error" in str(exc_info.value)
    assert len(calls) == 2
    assert calls[1] == ["codex-farm", "run", "errors", "--run-id", "run-123", "--json"]


def test_subprocess_runner_surfaces_precheck_stderr_when_failure_has_no_run_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")

    def _fake_run(_command, **_kwargs):  # noqa: ANN001
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=(
                "codex execution precheck failed before `process`: "
                "OpenAI Codex v0.111.0 (research preview)\n"
                "--------\n"
                "workdir: /home/mcnal/projects/recipeimport\n"
                "model: gpt-5.3-codex-spark\n"
                "reasoning effort: high\n"
                "user\n"
                "Reply with exactly: OK\n"
                "ERROR: You've hit your usage limit for GPT-5.3-Codex-Spark.\n"
                "Run `codex` once and confirm non-interactive `codex exec` works before retrying.\n"
            ),
        )

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    with pytest.raises(CodexFarmRunnerError) as exc_info:
        runner.run_pipeline("recipe.chunking.v1", in_dir, out_dir, {})

    message = str(exc_info.value)
    assert "codex-farm failed for recipe.chunking.v1" in message
    assert "subprocess_exit=1" in message
    assert "stderr_summary=codex execution precheck failed before `process`" in message
    assert "usage limit for GPT-5.3-Codex-Spark" in message


def test_subprocess_runner_tolerates_no_last_agent_message_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")

    calls: list[list[str]] = []

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        calls.append(argv)
        if argv[1:3] == ["process", "--pipeline"]:
            return SimpleNamespace(
                returncode=1,
                stdout=json.dumps(
                    {
                        "run_id": "run-123",
                        "status": "failed",
                        "exit_code": 1,
                    }
                ),
                stderr="pipeline failed",
            )
        if argv[1:3] == ["run", "errors"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "errors": [
                            {
                                "message": (
                                    "codex exec failed (exit=1): Warning: no last agent message; "
                                    "wrote empty content to /tmp/file.tmp"
                                )
                            }
                        ]
                    }
                ),
                stderr="",
            )
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(returncode=1, stdout="{}", stderr="unsupported")
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    run_result = runner.run_pipeline("recipe.chunking.v1", in_dir, out_dir, {})

    assert run_result.run_id == "run-123"
    assert run_result.subprocess_exit_code == 1
    assert run_result.process_exit_code == 1
    assert len(calls) == 3
    assert calls[1] == ["codex-farm", "run", "errors", "--run-id", "run-123", "--json"]
    assert calls[2] == [
        "codex-farm",
        "run",
        "autotune",
        "--run-id",
        "run-123",
        "--json",
        "--pipeline",
        "recipe.chunking.v1",
    ]


def test_subprocess_runner_routes_recoverable_partial_output_warning_to_progress_callback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")

    process_calls: list[list[str]] = []

    def _fake_stream(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        process_calls.append(argv)
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps(
                {
                    "run_id": "run-progress-123",
                    "status": "failed",
                    "exit_code": 1,
                }
            ),
            stderr="pipeline failed",
        )

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        process_calls.append(argv)
        if argv[1:3] == ["run", "errors"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "errors": [
                            {
                                "message": (
                                    "codex auth failed: run `codex` once and sign in with ChatGPT, "
                                    "then retry this run. Warning: no last agent message; wrote empty "
                                    "content to /tmp/file.tmp"
                                )
                            }
                        ]
                    }
                ),
                stderr="",
            )
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(returncode=1, stdout="{}", stderr="unsupported")
        raise AssertionError(f"Unexpected command: {argv}")

    progress_messages: list[str] = []
    warning_messages: list[str] = []
    debug_messages: list[str] = []

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_runner._run_codex_farm_command_streaming",
        _fake_stream,
    )
    monkeypatch.setattr("cookimport.llm.codex_farm_runner._run_codex_farm_command", _fake_run)
    monkeypatch.setattr(
        "cookimport.llm.codex_farm_runner.logger.warning",
        lambda message, *args: warning_messages.append(
            message % args if args else str(message)
        ),
    )
    monkeypatch.setattr(
        "cookimport.llm.codex_farm_runner.logger.debug",
        lambda message, *args: debug_messages.append(
            message % args if args else str(message)
        ),
    )

    runner = SubprocessCodexFarmRunner(
        cmd="codex-farm",
        progress_callback=progress_messages.append,
    )
    run_result = runner.run_pipeline("recipe.chunking.v1", in_dir, out_dir, {})

    assert run_result.run_id == "run-progress-123"
    assert run_result.subprocess_exit_code == 1
    assert run_result.process_exit_code == 1
    assert warning_messages == []
    assert debug_messages
    assert any(
        "recoverable non-zero exit; continuing with partial outputs" in message
        for message in progress_messages
    )
    assert any("run-progress-123" in message for message in progress_messages)


def test_subprocess_runner_recovers_high_coverage_benchmark_partial_timeout_mix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    for index in range(5):
        (in_dir / f"r{index:04d}.json").write_text("{}", encoding="utf-8")
    for index in range(4):
        (out_dir / f"r{index:04d}.json").write_text("{}", encoding="utf-8")

    def _fake_stream(command, **_kwargs):  # noqa: ANN001
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps(
                {
                    "run_id": "run-benchmark-123",
                    "status": "failed",
                    "exit_code": 1,
                }
            ),
            stderr="pipeline failed",
        )

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        if argv[1:3] == ["run", "errors"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "errors": [
                            {
                                "message": (
                                    "codex content_filter blocked response stream (exit=1): "
                                    "Warning: no last agent message; wrote empty content to /tmp/file.tmp"
                                )
                            }
                        ]
                    }
                ),
                stderr="",
            )
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(returncode=1, stdout="{}", stderr="unsupported")
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_runner._run_codex_farm_command_streaming",
        _fake_stream,
    )
    monkeypatch.setattr("cookimport.llm.codex_farm_runner._run_codex_farm_command", _fake_run)
    monkeypatch.setattr(
        "cookimport.llm.codex_farm_runner._collect_codex_exec_run_telemetry",
        lambda **_kwargs: {
            "row_count": 5,
            "summary": {
                "failure_category_counts": {
                    "nonzero_exit_no_payload": 1,
                    "timeout": 1,
                }
            },
        },
    )

    progress_messages: list[str] = []
    debug_messages: list[str] = []
    monkeypatch.setattr(
        "cookimport.llm.codex_farm_runner.logger.debug",
        lambda message, *args: debug_messages.append(
            message % args if args else str(message)
        ),
    )

    runner = SubprocessCodexFarmRunner(
        cmd="codex-farm",
        progress_callback=progress_messages.append,
    )
    run_result = runner.run_pipeline(
        "recipe.schemaorg.compact.v1",
        in_dir,
        out_dir,
        {"COOKIMPORT_CODEX_FARM_RECIPE_MODE": "benchmark"},
    )

    assert run_result.run_id == "run-benchmark-123"
    assert run_result.subprocess_exit_code == 1
    assert run_result.process_exit_code == 1
    assert debug_messages
    assert any("4/5 bundles written; 1 missing" in message for message in progress_messages)
    assert any("run-benchmark-123" in message for message in progress_messages)


def test_subprocess_runner_keeps_timeout_mixed_partial_failure_hard_outside_benchmark_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    for index in range(5):
        (in_dir / f"r{index:04d}.json").write_text("{}", encoding="utf-8")
    for index in range(4):
        (out_dir / f"r{index:04d}.json").write_text("{}", encoding="utf-8")

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        if argv[1] == "process":
            return SimpleNamespace(
                returncode=1,
                stdout=json.dumps(
                    {
                        "run_id": "run-extract-123",
                        "status": "failed",
                        "exit_code": 1,
                    }
                ),
                stderr="pipeline failed",
            )
        if argv[1:3] == ["run", "errors"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "errors": [
                            {
                                "message": (
                                    "codex content_filter blocked response stream (exit=1): "
                                    "Warning: no last agent message; wrote empty content to /tmp/file.tmp"
                                )
                            }
                        ]
                    }
                ),
                stderr="",
            )
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(returncode=1, stdout="{}", stderr="unsupported")
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner._run_codex_farm_command", _fake_run)
    monkeypatch.setattr(
        "cookimport.llm.codex_farm_runner._collect_codex_exec_run_telemetry",
        lambda **_kwargs: {
            "row_count": 5,
            "summary": {
                "failure_category_counts": {
                    "nonzero_exit_no_payload": 1,
                    "timeout": 1,
                }
            },
        },
    )

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    with pytest.raises(CodexFarmRunnerError, match="failure_categories=nonzero_exit_no_payload:1,timeout:1"):
        runner.run_pipeline("recipe.schemaorg.compact.v1", in_dir, out_dir, {})


def test_ensure_codex_farm_pipelines_exist_queries_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "pack"
    pack_root.mkdir(parents=True, exist_ok=True)
    captured: dict[str, object] = {}

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        captured["command"] = list(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {"pipeline_id": "recipe.chunking.v1"},
                    {"pipeline_id": "recipe.schemaorg.v1"},
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    ensure_codex_farm_pipelines_exist(
        cmd="codex-farm",
        root_dir=pack_root,
        pipeline_ids=("recipe.chunking.v1",),
    )

    command = captured.get("command")
    assert isinstance(command, list)
    assert command == [
        "codex-farm",
        "pipelines",
        "list",
        "--root",
        str(pack_root),
        "--json",
    ]


def test_ensure_codex_farm_pipelines_exist_raises_for_missing_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "pack"
    pack_root.mkdir(parents=True, exist_ok=True)

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps([{"pipeline_id": "recipe.chunking.v1"}]),
            stderr="",
        )

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    with pytest.raises(CodexFarmRunnerError) as exc_info:
        ensure_codex_farm_pipelines_exist(
            cmd="codex-farm",
            root_dir=pack_root,
            pipeline_ids=("recipe.final.compact.v1",),
        )
    assert "recipe.final.compact.v1" in str(exc_info.value)
