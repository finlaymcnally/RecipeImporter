from __future__ import annotations

import cookimport.llm.codex_exec_runner as exec_runner_module
import tests.llm.test_codex_exec_runner as _base

# Reuse shared imports/helpers from the base direct-exec runner test module.
globals().update({
    name: value
    for name, value in _base.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_prepare_direct_exec_workspace_mirrors_local_inputs_and_writes_agents(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo" / "runtime" / "workers" / "worker-001"
    (source_root / "in").mkdir(parents=True, exist_ok=True)
    (source_root / "debug").mkdir(parents=True, exist_ok=True)
    (source_root / "assigned_shards.json").write_text(
        json.dumps([{"shard_id": "shard-001"}]),
        encoding="utf-8",
    )
    (source_root / "assigned_tasks.json").write_text(
        json.dumps(
            [
                {
                    "task_id": "shard-001",
                    "parent_shard_id": "shard-001",
                    "metadata": {
                        "input_path": "in/shard-001.json",
                        "hint_path": "hints/shard-001.md",
                        "result_path": "out/shard-001.json",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    (source_root / "in" / "shard-001.json").write_text(
        json.dumps({"shard_id": "shard-001"}),
        encoding="utf-8",
    )
    (source_root / "debug" / "shard-001.json").write_text(
        json.dumps({"phase_key": "line_role"}),
        encoding="utf-8",
    )

    workspace = prepare_direct_exec_workspace(
        source_working_dir=source_root,
        env={"CODEX_HOME": str(tmp_path / ".codex-recipe")},
        task_label="canonical line-role shard",
    )

    assert workspace.execution_working_dir.exists()
    assert workspace.execution_working_dir != source_root
    assert str(workspace.execution_working_dir).startswith(
        str(tmp_path / ".codex-recipe" / "recipeimport-direct-exec-workspaces")
    )
    assert (
        workspace.execution_working_dir / "assigned_shards.json"
    ).read_text(encoding="utf-8") == (
        source_root / "assigned_shards.json"
    ).read_text(encoding="utf-8")
    assert (
        workspace.execution_working_dir / "in" / "shard-001.json"
    ).read_text(encoding="utf-8") == (
        source_root / "in" / "shard-001.json"
    ).read_text(encoding="utf-8")
    assert (
        workspace.execution_working_dir / "debug" / "shard-001.json"
    ).read_text(encoding="utf-8") == (
        source_root / "debug" / "shard-001.json"
    ).read_text(encoding="utf-8")
    source_manifest = json.loads((source_root / "worker_manifest.json").read_text(encoding="utf-8"))
    execution_manifest = json.loads(
        (workspace.execution_working_dir / "worker_manifest.json").read_text(encoding="utf-8")
    )
    assert source_manifest == execution_manifest
    assert source_manifest["entry_files"] == [
        "worker_manifest.json",
        "assigned_shards.json",
        "assigned_tasks.json",
    ]
    agents_text = workspace.agents_path.read_text(encoding="utf-8")
    assert "canonical line-role shard" in agents_text
    assert "npm run docs:list" in agents_text
    assert "not working on the RecipeImport repository" in agents_text
    assert "Do not inspect local files or run discovery commands just to orient yourself." in agents_text
    assert "Prefer reading the local task file directly" not in agents_text


def test_prepare_direct_exec_workspace_worker_mode_permits_local_task_loop(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo" / "runtime" / "workers" / "worker-001"
    (source_root / "in").mkdir(parents=True, exist_ok=True)
    (source_root / "hints").mkdir(parents=True, exist_ok=True)
    (source_root / "examples").mkdir(parents=True, exist_ok=True)
    (source_root / "tools").mkdir(parents=True, exist_ok=True)
    (source_root / "assigned_shards.json").write_text(
        json.dumps([{"shard_id": "shard-001"}]),
        encoding="utf-8",
    )
    (source_root / "assigned_tasks.json").write_text(
        json.dumps([{"task_id": "shard-001", "parent_shard_id": "shard-001"}]),
        encoding="utf-8",
    )
    (source_root / "in" / "shard-001.json").write_text(
        json.dumps({"shard_id": "shard-001"}),
        encoding="utf-8",
    )
    (source_root / "hints" / "shard-001.md").write_text(
        "# worker hints\n",
        encoding="utf-8",
    )
    (source_root / "OUTPUT_CONTRACT.md").write_text(
        "# contract\n",
        encoding="utf-8",
    )
    (source_root / "examples" / "valid_repaired_task_output.json").write_text(
        json.dumps({"v": "1", "sid": "shard-001", "r": []}),
        encoding="utf-8",
    )
    (source_root / "tools" / "line_role_worker.py").write_text(
        "print('helper')\n",
        encoding="utf-8",
    )

    workspace = prepare_direct_exec_workspace(
        source_working_dir=source_root,
        env={"CODEX_HOME": str(tmp_path / ".codex-recipe")},
        task_label="canonical line-role worker session",
        mode="workspace_worker",
    )

    agents_text = workspace.agents_path.read_text(encoding="utf-8")
    worker_manifest = json.loads(
        (workspace.execution_working_dir / "worker_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert worker_manifest["entry_files"] == [
        "worker_manifest.json",
        "current_task.json",
        "assigned_shards.json",
        "assigned_tasks.json",
    ]
    assert worker_manifest["current_task_file"] == "current_task.json"
    assert worker_manifest["output_contract_file"] == "OUTPUT_CONTRACT.md"
    assert worker_manifest["examples_dir"] == "examples"
    assert worker_manifest["tools_dir"] == "tools"
    assert worker_manifest["hints_dir"] == "hints"
    assert worker_manifest["scratch_dir"] == "scratch"
    assert worker_manifest["mirrored_example_files"] == ["valid_repaired_task_output.json"]
    assert worker_manifest["mirrored_tool_files"] == ["line_role_worker.py"]
    assert worker_manifest["workspace_shell_policy"].startswith(
        "Allow ordinary local shell use inside this workspace"
    )
    assert worker_manifest["workspace_local_shell_examples"] == [
        "sed -n '1,80p' hints/<task>.md",
        "python3 -c \"import json; from pathlib import Path; row=json.loads(Path('current_task.json').read_text()); print(row['task_id'])\"",
        "jq '.metadata' current_task.json",
        "python3 tools/line_role_worker.py overview",
        "python3 -c \"import json; from pathlib import Path; row=json.loads(Path('current_task.json').read_text()); print(row.get('metadata', {}).get('scratch_draft_path', ''))\"",
        "python3 tools/line_role_worker.py finalize scratch/<task>.json",
        "python3 tools/line_role_worker.py finalize-all scratch/",
    ]
    assert worker_manifest["workspace_commands_forbidden"] == [
        "repo/network/package-manager commands such as git, curl, wget, ssh, or package managers",
        "non-temp absolute paths outside approved local temp roots",
        "parent-directory traversal",
    ]
    assert "Read the local task manifests and input files directly." in agents_text
    assert "Start by reading `worker_manifest.json`" in agents_text
    assert "When `OUTPUT_CONTRACT.md` or `examples/` exists" in agents_text
    assert "When `tools/` exists, prefer its repo-written helper CLI" in agents_text
    assert "When the workspace includes `current_task.json`, `CURRENT_TASK.md`, or `CURRENT_TASK_FEEDBACK.md`" in agents_text
    assert "`assigned_tasks.json`" in agents_text
    assert "`current_packet.json`, `current_hint.md`, and `current_result_path.txt`" in agents_text
    assert "Workspace-local shell commands are broadly allowed when they materially help" in agents_text
    assert "The watchdog is boundary-based" in agents_text
    assert "avoid repo/network/package-manager commands such as `git`, `curl`, or `npm`" in agents_text
    assert "`/tmp` or `/var/tmp` for bounded helper files" in agents_text
    assert "dumping whole manifests just to orient yourself" in agents_text
    assert "prefer a short local `python3` helper" in agents_text
    assert "repo-written `complete-current` or `check-current` helper" in agents_text
    current_task = json.loads(
        (workspace.execution_working_dir / "current_task.json").read_text(encoding="utf-8")
    )
    assert current_task["task_id"] == "shard-001"
    assert (workspace.execution_working_dir / "out").exists()
    assert (workspace.execution_working_dir / "OUTPUT_CONTRACT.md").exists()
    assert (workspace.execution_working_dir / "examples" / "valid_repaired_task_output.json").exists()
    assert (workspace.execution_working_dir / "tools" / "line_role_worker.py").exists()
    assert (workspace.execution_working_dir / "hints" / "shard-001.md").exists()
    assert (workspace.execution_working_dir / "scratch").exists()


def test_prepare_direct_exec_workspace_worker_mode_mirrors_packet_lease_files(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo" / "runtime" / "workers" / "worker-001"
    (source_root / "scratch").mkdir(parents=True, exist_ok=True)
    (source_root / "current_packet.json").write_text(
        json.dumps({"task_id": "task-001", "result_path": "out/task-001.json"}),
        encoding="utf-8",
    )
    (source_root / "current_hint.md").write_text(
        "# hint\n",
        encoding="utf-8",
    )
    (source_root / "current_result_path.txt").write_text(
        "out/task-001.json\n",
        encoding="utf-8",
    )
    (source_root / "packet_lease_status.json").write_text(
        json.dumps({"worker_state": "leased_current_packet", "current_task_id": "task-001"}),
        encoding="utf-8",
    )

    workspace = prepare_direct_exec_workspace(
        source_working_dir=source_root,
        env={"CODEX_HOME": str(tmp_path / ".codex-recipe")},
        task_label="knowledge worker session",
        mode="workspace_worker",
    )

    worker_manifest = json.loads(
        (workspace.execution_working_dir / "worker_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert worker_manifest["entry_files"] == [
        "worker_manifest.json",
        "current_packet.json",
        "current_hint.md",
        "current_result_path.txt",
        "packet_lease_status.json",
        "assigned_shards.json",
        "assigned_tasks.json",
    ]
    assert worker_manifest["current_task_file"] is None
    assert worker_manifest["current_packet_file"] == "current_packet.json"
    assert worker_manifest["current_hint_file"] == "current_hint.md"
    assert worker_manifest["current_result_path_file"] == "current_result_path.txt"
    assert worker_manifest["packet_lease_status_file"] == "packet_lease_status.json"
    assert worker_manifest["scratch_dir"] == "scratch"
    assert (workspace.execution_working_dir / "current_packet.json").exists()
    assert (workspace.execution_working_dir / "current_hint.md").exists()
    assert (workspace.execution_working_dir / "current_result_path.txt").exists()
    assert (workspace.execution_working_dir / "packet_lease_status.json").exists()
    assert not (workspace.execution_working_dir / "current_task.json").exists()
    assert (workspace.execution_working_dir / "scratch").exists()


def test_workspace_boundary_detector_allows_jq_fallback_operator_with_output_redirection() -> None:
    command = (
        "/bin/bash -lc \"jq '{rows: .rows | map({atomic_index: .[0], "
        "label: ({\\\"L0\\\":\\\"RECIPE_TITLE\\\"}[.[1]] // \\\"UNKNOWN\\\")})}' "
        "in/task-001.json > out/task-001.json\""
    )

    assert detect_workspace_worker_boundary_violation(command) is None
    verdict = classify_workspace_worker_command(command)
    assert verdict.allowed is True
    assert verdict.policy in {
        "shell_script_workspace_local",
        "tolerated_workspace_shell_command",
    }


def test_workspace_boundary_detector_allows_workspace_tool_helper() -> None:
    command = (
        "/bin/bash -lc "
        "\"python3 tools/line_role_worker.py scaffold task-001 --dest scratch/task-001.json\""
    )

    assert detect_workspace_worker_boundary_violation(command) is None
    verdict = classify_workspace_worker_command(command)
    assert verdict.allowed is True


def test_workspace_boundary_detector_allows_bounded_python_and_node_transforms() -> None:
    for command in (
        "/bin/bash -lc \"python3 -c "
        "'from pathlib import Path; "
        "Path(\\\"out/task-001.json\\\").write_text(Path(\\\"in/task-001.json\\\").read_text())'\"",
        "/bin/bash -lc \"python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "Path('out/task-001.json').write_text(Path('in/task-001.json').read_text())\n"
        "PY\"",
        "/bin/bash -lc \"node -e "
        "\\\"const fs=require('fs'); "
        "fs.writeFileSync('out/task-001.json', fs.readFileSync('in/task-001.json', 'utf8'));\\\"\"",
    ):
        assert detect_workspace_worker_boundary_violation(command) is None
        verdict = classify_workspace_worker_command(command)
        assert verdict.allowed is True
        assert verdict.policy in {
            "shell_script_workspace_local",
            "tolerated_workspace_shell_command",
        }


def test_workspace_boundary_detector_allows_execution_root_cd_and_manifest_reads(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo" / "runtime" / "workers" / "worker-001"
    execution_root = tmp_path / ".codex-recipe" / "runtime" / "worker-001"
    command = (
        f'/bin/bash -lc "cd {execution_root} && '
        'cat worker_manifest.json current_task.json OUTPUT_CONTRACT.md >/dev/null"'
    )

    assert (
        detect_workspace_worker_boundary_violation(
            command,
            allowed_absolute_roots=[source_root, execution_root],
        )
        is None
    )
    verdict = classify_workspace_worker_command(
        command,
        allowed_absolute_roots=[source_root, execution_root],
    )
    assert verdict.allowed is True
    assert verdict.policy in {
        "shell_script_workspace_local",
        "tolerated_workspace_shell_command",
    }


def test_workspace_boundary_detector_allows_local_cp_and_mv_between_scratch_and_out() -> None:
    for command in (
        '/bin/bash -lc "cp scratch/task-001.json out/task-001.json"',
        '/bin/bash -lc "mv scratch/task-001.json out/task-001.json"',
    ):
        assert detect_workspace_worker_boundary_violation(command) is None
        verdict = classify_workspace_worker_command(command)
        assert verdict.allowed is True
        assert verdict.policy in {
            "shell_script_workspace_local",
            "tolerated_workspace_shell_command",
        }


def test_fake_workspace_worker_reads_local_inputs_and_syncs_outputs(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo" / "runtime" / "workers" / "worker-001"
    (source_root / "in").mkdir(parents=True, exist_ok=True)
    (source_root / "assigned_shards.json").write_text(
        json.dumps([{"shard_id": "shard-001"}]),
        encoding="utf-8",
    )
    (source_root / "assigned_tasks.json").write_text(
        json.dumps([{"task_id": "shard-001", "parent_shard_id": "shard-001"}]),
        encoding="utf-8",
    )
    (source_root / "in" / "shard-001.json").write_text(
        json.dumps({"rows": [[1, "L9", "hello"]]}),
        encoding="utf-8",
    )

    runner = FakeCodexExecRunner(
        output_builder=lambda payload: {
            "rows": [
                {"atomic_index": int(row[0]), "label": "OTHER"}
                for row in (payload.get("rows") or [])
            ]
        }
    )
    result = runner.run_workspace_worker(
        prompt_text="Process every local shard file and write outputs under out/.",
        working_dir=source_root,
        env={"CODEX_HOME": str(tmp_path / ".codex-recipe")},
        workspace_task_label="canonical line-role worker session",
    )

    assert runner.calls[0]["mode"] == "workspace_worker"
    assert result.source_working_dir == str(source_root)
    assert result.execution_working_dir != str(source_root)
    synced_output = json.loads(
        (source_root / "out" / "shard-001.json").read_text(encoding="utf-8")
    )
    assert synced_output == {"rows": [{"atomic_index": 1, "label": "OTHER"}]}


def test_workspace_supervision_pushes_advanced_current_task_bundle_back_to_execution_root(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo" / "runtime" / "workers" / "worker-001"
    execution_root = tmp_path / ".codex-recipe" / "runtime" / "worker-001"
    source_root.mkdir(parents=True, exist_ok=True)
    execution_root.mkdir(parents=True, exist_ok=True)
    for root in (source_root, execution_root):
        (root / "out").mkdir(parents=True, exist_ok=True)
        (root / "current_task.json").write_text(
            json.dumps({"task_id": "task-001", "metadata": {"result_path": "out/task-001.json"}}),
            encoding="utf-8",
        )
        (root / "CURRENT_TASK.md").write_text(
            "# Current Knowledge Task\n\nTask id: `task-001`\n",
            encoding="utf-8",
        )
        (root / "CURRENT_TASK_FEEDBACK.md").write_text(
            "# Current Task Feedback\n\nTask id: `task-001`\nValidation status: OK.\n",
            encoding="utf-8",
        )
    (execution_root / "out" / "task-001.json").write_text(
        json.dumps({"packet_id": "task-001", "chunk_results": []}),
        encoding="utf-8",
    )

    callback_calls: list[int] = []

    def _callback(snapshot: CodexExecLiveSnapshot) -> CodexExecSupervisionDecision | None:
        callback_calls.append(len(callback_calls) + 1)
        assert snapshot.source_working_dir == str(source_root)
        assert snapshot.execution_working_dir == str(execution_root)
        if len(callback_calls) == 1:
            (source_root / "current_task.json").write_text(
                json.dumps(
                    {"task_id": "task-002", "metadata": {"result_path": "out/task-002.json"}}
                ),
                encoding="utf-8",
            )
            (source_root / "CURRENT_TASK.md").write_text(
                "# Current Knowledge Task\n\nTask id: `task-002`\n",
                encoding="utf-8",
            )
            (source_root / "CURRENT_TASK_FEEDBACK.md").write_text(
                (
                    "# Current Task Feedback\n\n"
                    "Task id: `task-002`\n"
                    "No repo-written validation feedback exists yet for this task.\n"
                ),
                encoding="utf-8",
            )
        return None

    wrapped = exec_runner_module._wrap_workspace_supervision_callback(  # noqa: SLF001
        supervision_callback=_callback,
        workspace_mode="workspace_worker",
        source_working_dir=source_root,
        execution_working_dir=execution_root,
        sync_output_paths=("out",),
        sync_source_paths=(
            "current_task.json",
            "CURRENT_TASK.md",
            "CURRENT_TASK_FEEDBACK.md",
        ),
    )

    assert wrapped is not None
    snapshot = CodexExecLiveSnapshot(
        elapsed_seconds=0.1,
        last_event_seconds_ago=0.0,
        event_count=1,
        command_execution_count=1,
        reasoning_item_count=0,
        last_command="/bin/bash -lc python3 tools/knowledge_worker.py install-current",
        last_command_repeat_count=1,
        has_final_agent_message=False,
        timeout_seconds=30,
    )

    wrapped(snapshot)
    wrapped(snapshot)

    assert callback_calls == [1, 2]
    assert json.loads((source_root / "current_task.json").read_text(encoding="utf-8"))["task_id"] == (
        "task-002"
    )
    assert json.loads((execution_root / "current_task.json").read_text(encoding="utf-8"))[
        "task_id"
    ] == "task-002"
    assert "task-002" in (source_root / "CURRENT_TASK.md").read_text(encoding="utf-8")
    assert "task-002" in (execution_root / "CURRENT_TASK.md").read_text(encoding="utf-8")
    assert "task-002" in (
        execution_root / "CURRENT_TASK_FEEDBACK.md"
    ).read_text(encoding="utf-8")


def test_rewrite_direct_exec_prompt_paths_retargets_worker_root(tmp_path: Path) -> None:
    source_root = tmp_path / "repo" / "worker-001"
    execution_root = tmp_path / ".codex-recipe" / "runtime" / "worker-001"
    prompt_text = (
        "Read `/tmp/nope` and "
        f"`{source_root}/in/shard-001.json`, then return JSON for `{source_root}`."
    )

    rewritten = rewrite_direct_exec_prompt_paths(
        prompt_text=prompt_text,
        source_working_dir=source_root,
        execution_working_dir=execution_root,
    )

    assert str(source_root) not in rewritten
    assert f"{execution_root}/in/shard-001.json" in rewritten
    assert "/tmp/nope" in rewritten


def test_subprocess_runner_uses_sterile_execution_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo" / "runtime" / "workers" / "worker-001"
    (source_root / "in").mkdir(parents=True, exist_ok=True)
    (source_root / "assigned_shards.json").write_text(
        json.dumps([{"shard_id": "shard-001"}]),
        encoding="utf-8",
    )
    input_path = source_root / "in" / "shard-001.json"
    input_path.write_text(json.dumps({"shard_id": "shard-001"}), encoding="utf-8")
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    class _FakeStdin:
        def write(self, text: str) -> int:
            captured["input"] = text
            return len(text)

        def close(self) -> None:
            return None

    class _Stream:
        def __init__(self, lines: list[str]) -> None:
            self._lines = list(lines)

        def readline(self) -> str:
            if self._lines:
                return self._lines.pop(0)
            return ""

        def close(self) -> None:
            return None

    class _FakeProcess:
        def __init__(self, command, **kwargs):  # noqa: ANN001
            captured["command"] = list(command)
            captured["cwd"] = kwargs.get("cwd")
            captured["env"] = dict(kwargs.get("env") or {})
            self.stdin = _FakeStdin()
            self.stdout = _Stream(
                [
                    json.dumps({"type": "thread.started"}) + "\n",
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "agent_message",
                                "text": '{"rows":[{"atomic_index":1,"label":"OTHER"}]}',
                            },
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "usage": {
                                "input_tokens": 100,
                                "cached_input_tokens": 10,
                                "output_tokens": 20,
                                "reasoning_tokens": 0,
                            },
                        }
                    )
                    + "\n",
                ]
            )
            self.stderr = _Stream([])
            self.returncode = 0

        def poll(self) -> int:
            return self.returncode

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(
        "cookimport.llm.codex_exec_runner.subprocess.Popen",
        _FakeProcess,
    )

    runner = SubprocessCodexExecRunner(cmd="codex exec")
    result = runner.run_structured_prompt(
        prompt_text=f"Read the task file at `{input_path}` and return JSON only.",
        input_payload={"shard_id": "shard-001"},
        working_dir=source_root,
        env={"CODEX_HOME": str(tmp_path / ".codex-recipe")},
        output_schema_path=schema_path,
        workspace_task_label="knowledge review shard",
    )

    command = captured["command"]
    cwd = Path(str(captured["cwd"]))
    stdin_text = str(captured["input"])
    assert isinstance(command, list)
    assert str(source_root) not in stdin_text
    assert str(source_root) not in str(cwd)
    assert str(cwd).startswith(
        str(tmp_path / ".codex-recipe" / "recipeimport-direct-exec-workspaces")
    )
    assert command[command.index("--cd") + 1] == str(cwd)
    assert "--skip-git-repo-check" in command
    assert f"{cwd}/in/shard-001.json" in stdin_text
    assert (cwd / "AGENTS.md").exists()
    assert "knowledge review shard" in (cwd / "AGENTS.md").read_text(encoding="utf-8")
    assert result.source_working_dir == str(source_root)
    assert result.execution_working_dir == str(cwd)
    assert result.execution_agents_path == str(cwd / "AGENTS.md")


def test_subprocess_runner_can_terminate_from_streamed_watchdog_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo" / "runtime" / "workers" / "worker-001"
    (source_root / "in").mkdir(parents=True, exist_ok=True)
    (source_root / "assigned_shards.json").write_text(
        json.dumps([{"shard_id": "shard-001"}]),
        encoding="utf-8",
    )
    input_path = source_root / "in" / "shard-001.json"
    input_path.write_text(json.dumps({"shard_id": "shard-001"}), encoding="utf-8")
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")

    class _FakeStdin:
        def __init__(self) -> None:
            self.buffer = ""

        def write(self, text: str) -> int:
            self.buffer += text
            return len(text)

        def close(self) -> None:
            return None

    class _BlockingStream:
        def __init__(self, owner: "_FakeProcess", lines: list[str]) -> None:
            self._owner = owner
            self._lines = list(lines)

        def readline(self) -> str:
            if self._lines:
                return self._lines.pop(0)
            while self._owner.returncode is None:
                time.sleep(0.01)
            return ""

        def close(self) -> None:
            return None

    class _FakeProcess:
        def __init__(self) -> None:
            self.stdin = _FakeStdin()
            self.returncode: int | None = None
            self.stdout = _BlockingStream(
                self,
                [
                    json.dumps(
                        {
                            "type": "item.started",
                            "item": {
                                "id": "cmd-1",
                                "type": "command_execution",
                                "command": "/bin/bash -lc ls",
                            },
                        }
                    )
                    + "\n"
                ],
            )
            self.stderr = _BlockingStream(self, [])

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(
        "cookimport.llm.codex_exec_runner.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )

    runner = SubprocessCodexExecRunner(cmd="codex exec")
    result = runner.run_structured_prompt(
        prompt_text=f"Read the task file at `{input_path}` and return JSON only.",
        input_payload={"shard_id": "shard-001"},
        working_dir=source_root,
        env={"CODEX_HOME": str(tmp_path / ".codex-recipe")},
        output_schema_path=schema_path,
        workspace_task_label="knowledge review shard",
        supervision_callback=lambda snapshot: (
            CodexExecSupervisionDecision.terminate(
                reason_code="watchdog_command_execution_forbidden",
                reason_detail="strict JSON stages must not use tools",
                retryable=True,
            )
            if snapshot.command_execution_count > 0
            else None
        ),
    )

    assert result.subprocess_exit_code == -15
    assert result.response_text is None
    assert result.supervision_state == "watchdog_killed"
    assert result.supervision_reason_code == "watchdog_command_execution_forbidden"
    assert result.supervision_retryable is True
    assert result.events[0]["type"] == "item.started"
    assert isinstance(result.duration_ms, int)
    assert result.duration_ms >= 0
    assert str(result.started_at_utc or "").endswith("Z")
    assert str(result.finished_at_utc or "").endswith("Z")


def test_workspace_worker_supervision_syncs_live_outputs_before_callback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo" / "runtime" / "workers" / "worker-001"
    (source_root / "in").mkdir(parents=True, exist_ok=True)
    (source_root / "assigned_shards.json").write_text(
        json.dumps([{"shard_id": "shard-001"}]),
        encoding="utf-8",
    )
    (source_root / "in" / "shard-001.json").write_text(
        json.dumps({"shard_id": "shard-001"}),
        encoding="utf-8",
    )
    written = {"started": False}

    class _FakeStdin:
        def write(self, text: str) -> int:
            return len(text)

        def close(self) -> None:
            return None

    class _BlockingStream:
        def __init__(self, owner: "_FakeProcess", lines: list[str]) -> None:
            self._owner = owner
            self._lines = list(lines)

        def readline(self) -> str:
            if self._lines:
                return self._lines.pop(0)
            while self._owner.returncode is None:
                time.sleep(0.01)
            return ""

        def close(self) -> None:
            return None

    class _FakeProcess:
        def __init__(self, cwd: Path) -> None:
            self.stdin = _FakeStdin()
            self.returncode: int | None = None
            self.stdout = _BlockingStream(
                self,
                [json.dumps({"type": "thread.started"}) + "\n"],
            )
            self.stderr = _BlockingStream(self, [])
            self._cwd = cwd

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

    def _fake_popen(command, **kwargs):  # noqa: ANN001
        cwd = Path(str(kwargs["cwd"]))
        process = _FakeProcess(cwd)
        if not written["started"]:
            written["started"] = True

            def _writer() -> None:
                time.sleep(0.15)
                out_dir = cwd / "out"
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "shard-001.json").write_text(
                    json.dumps({"v": "2", "bid": "shard-001", "r": []}),
                    encoding="utf-8",
                )

            import threading

            threading.Thread(target=_writer, daemon=True).start()
        return process

    monkeypatch.setattr(
        "cookimport.llm.codex_exec_runner.subprocess.Popen",
        _fake_popen,
    )

    runner = SubprocessCodexExecRunner(cmd="codex exec")
    result = runner.run_workspace_worker(
        prompt_text="Write shard output files locally and stop once done.",
        working_dir=source_root,
        env={"CODEX_HOME": str(tmp_path / ".codex-recipe")},
        workspace_task_label="knowledge worker session",
        supervision_callback=lambda _snapshot: (
            CodexExecSupervisionDecision.terminate(
                reason_code="workspace_outputs_stabilized",
                reason_detail="worker outputs stabilized",
                retryable=False,
                supervision_state="completed",
            )
            if (source_root / "out" / "shard-001.json").exists()
            else None
        ),
    )

    assert (source_root / "out" / "shard-001.json").exists()
    assert json.loads((source_root / "out" / "shard-001.json").read_text(encoding="utf-8")) == {
        "v": "2",
        "bid": "shard-001",
        "r": [],
    }
    assert result.supervision_state == "completed"
    assert result.supervision_reason_code == "workspace_outputs_stabilized"
    assert result.completed_successfully() is True
