from __future__ import annotations

import threading

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
    ]
    agents_text = workspace.agents_path.read_text(encoding="utf-8")
    assert "canonical line-role shard" in agents_text
    assert "npm run docs:list" in agents_text
    assert "not working on the RecipeImport repository" in agents_text
    assert "Do not inspect local files or run discovery commands just to orient yourself." in agents_text
    assert "If `task.json` exists, read it directly" not in agents_text
    assert "Prefer reading the local task file directly" not in agents_text


def test_prepare_direct_exec_workspace_worker_mode_uses_fixed_assignment_manifest(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo" / "runtime" / "workers" / "worker-001"
    (source_root / "in").mkdir(parents=True, exist_ok=True)
    (source_root / "hints").mkdir(parents=True, exist_ok=True)
    (source_root / "examples").mkdir(parents=True, exist_ok=True)
    (source_root / "tools").mkdir(parents=True, exist_ok=True)
    (source_root / "assigned_shards.json").write_text(
        json.dumps(
            [
                {
                    "shard_id": "shard-001",
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
        "assigned_shards.json",
    ]
    assert worker_manifest["assigned_tasks_file"] is None
    assert worker_manifest["current_phase_file"] is None
    assert worker_manifest["current_phase_brief_file"] is None
    assert worker_manifest["current_phase_feedback_file"] is None
    assert worker_manifest["output_contract_file"] == "OUTPUT_CONTRACT.md"
    assert worker_manifest["examples_dir"] == "examples"
    assert worker_manifest["tools_dir"] == "tools"
    assert worker_manifest["hints_dir"] == "hints"
    assert worker_manifest["scratch_dir"] is None
    assert worker_manifest["work_dir"] is None
    assert worker_manifest["repair_dir"] is None
    assert worker_manifest["mirrored_example_files"] == ["valid_repaired_task_output.json"]
    assert worker_manifest["mirrored_tool_files"] == ["line_role_worker.py"]
    assert worker_manifest["workspace_shell_policy"].startswith(
        "Allow ordinary local shell use inside this workspace"
    )
    assert "sed -n '1,120p' assigned_shards.json" in worker_manifest["workspace_local_shell_examples"]
    assert "sed -n '1,80p' hints/<shard_id>.md" in worker_manifest["workspace_local_shell_examples"]
    assert "python3 tools/line_role_worker.py overview" in worker_manifest["workspace_local_shell_examples"]
    assert worker_manifest["workspace_commands_forbidden"] == [
        "repo/network/package-manager commands such as git, curl, wget, ssh, or package managers",
        "non-temp absolute paths outside approved local temp roots",
        "parent-directory traversal",
    ]
    assert worker_manifest["task_file"] is None
    assert "If `task.json` exists, read it directly" in agents_text
    assert "If `task.json` is absent, fall back to the repo-written file named in `worker_manifest.json`." in agents_text
    assert "When `OUTPUT_CONTRACT.md` or `examples/` exists" in agents_text
    assert "When `tools/` exists, prefer its repo-written helper CLI" in agents_text
    assert "Prefer reading the local task file directly instead of opening helper manifests or inventories just to orient yourself." in agents_text
    assert "The happy path is file-first" in agents_text
    assert "Do not reach for shell on the happy path." in agents_text
    assert "The watchdog is boundary-based" in agents_text
    assert "avoid repo/network/package-manager commands such as `git`, `curl`, or `npm`" in agents_text
    assert "`/tmp` or `/var/tmp` for bounded helper files" in agents_text
    assert "dumping whole manifests just to orient yourself" in agents_text
    assert "If a tiny local helper is truly necessary" in agents_text
    assert "start with the smallest prompt-named helper surface first" in agents_text
    assert (workspace.execution_working_dir / "OUTPUT_CONTRACT.md").exists()
    assert (workspace.execution_working_dir / "examples" / "valid_repaired_task_output.json").exists()
    assert (workspace.execution_working_dir / "tools" / "line_role_worker.py").exists()
    assert (workspace.execution_working_dir / "hints" / "shard-001.md").exists()
    assert not (workspace.execution_working_dir / "current_phase.json").exists()


def test_prepare_direct_exec_workspace_worker_mode_mirrors_assigned_tasks_files(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo" / "runtime" / "workers" / "worker-001"
    (source_root / "in").mkdir(parents=True, exist_ok=True)
    (source_root / "hints").mkdir(parents=True, exist_ok=True)
    (source_root / "assigned_tasks.json").write_text(
        json.dumps(
            [
                {
                    "task_id": "task-001",
                    "metadata": {
                        "input_path": "in/task-001.json",
                        "hint_path": "hints/task-001.md",
                        "result_path": "out/task-001.json",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    (source_root / "in" / "task-001.json").write_text(
        json.dumps({"sid": "task-001", "r": []}),
        encoding="utf-8",
    )
    (source_root / "hints" / "task-001.md").write_text(
        "# hint\n",
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
        "assigned_tasks.json",
    ]
    assert worker_manifest["assigned_tasks_file"] == "assigned_tasks.json"
    assert worker_manifest["assigned_shards_file"] is None
    assert worker_manifest["task_file"] is None
    assert worker_manifest["current_packet_file"] is None
    assert worker_manifest["current_hint_file"] is None
    assert worker_manifest["current_result_path_file"] is None
    assert worker_manifest["packet_lease_status_file"] is None
    assert (workspace.execution_working_dir / "assigned_tasks.json").exists()
    assert (workspace.execution_working_dir / "in" / "task-001.json").exists()
    assert (workspace.execution_working_dir / "hints" / "task-001.md").exists()


def test_prepare_direct_exec_workspace_worker_mode_knows_assignment_first_knowledge_helpers(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo" / "runtime" / "workers" / "worker-001"
    (source_root / "in").mkdir(parents=True, exist_ok=True)
    (source_root / "hints").mkdir(parents=True, exist_ok=True)
    (source_root / "assigned_shards.json").write_text(
        json.dumps(
            [
                {
                    "shard_id": "book.ks0000.nr",
                    "metadata": {
                        "input_path": "in/book.ks0000.nr.json",
                        "hint_path": "hints/book.ks0000.nr.md",
                        "result_path": "out/book.ks0000.nr.json",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    (source_root / "in" / "book.ks0000.nr.json").write_text(
        json.dumps({"bid": "book.ks0000.nr", "b": [{"i": 1, "t": "Use low heat."}]}),
        encoding="utf-8",
    )
    (source_root / "hints" / "book.ks0000.nr.md").write_text(
        "# knowledge hint\n",
        encoding="utf-8",
    )
    (source_root / "OUTPUT_CONTRACT.md").write_text("# contract\n", encoding="utf-8")

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
        "assigned_shards.json",
    ]
    assert worker_manifest["assigned_shards_file"] == "assigned_shards.json"
    assert worker_manifest["assigned_tasks_file"] is None
    assert worker_manifest["current_packet_file"] is None
    assert worker_manifest["current_hint_file"] is None
    assert worker_manifest["current_result_path_file"] is None
    assert worker_manifest["packet_lease_status_file"] is None
    assert worker_manifest["workspace_shell_policy"].startswith(
        "Allow ordinary local shell use inside this workspace"
    )
    assert "sed -n '1,120p' assigned_shards.json" in worker_manifest["workspace_local_shell_examples"]
    assert worker_manifest["workspace_commands_forbidden"] == [
        "repo/network/package-manager commands such as git, curl, wget, ssh, or package managers",
        "non-temp absolute paths outside approved local temp roots",
        "parent-directory traversal",
    ]
    assert (workspace.execution_working_dir / "assigned_shards.json").exists()
    assert not (workspace.execution_working_dir / "current_phase.json").exists()
    assert not (workspace.execution_working_dir / "CURRENT_PHASE.md").exists()


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


def test_workspace_boundary_detector_allows_multi_python_heredoc_shell_body() -> None:
    command = (
        "/bin/bash -lc \"python3 - <<'PY1'\n"
        "from pathlib import Path\n"
        "Path('scratch/current_packet.json').write_text('{}\\n')\n"
        "PY1\n"
        "python3 - <<'PY2'\n"
        "from pathlib import Path\n"
        "Path('out/task-001.json').write_text(Path('scratch/current_packet.json').read_text())\n"
        "PY2\""
    )

    assert detect_workspace_worker_boundary_violation(command) is None
    verdict = classify_workspace_worker_command(command)
    assert verdict.allowed is True
    assert verdict.policy == "shell_script_workspace_local"


def test_workspace_boundary_detector_allows_slashy_heredoc_write_payload() -> None:
    command = (
        "/bin/bash -lc \"cat > scratch/current_packet.json <<'EOF'\n"
        "{\\\"task_id\\\":\\\"task-001\\\",\\\"source\\\":\\\"/home/mcnal/projects/recipeimport/data/input/book.pdf\\\","
        "\\\"ratio\\\":\\\"3/4\\\"}\n"
        "EOF\""
    )

    assert detect_workspace_worker_boundary_violation(command) is None
    verdict = classify_workspace_worker_command(command)
    assert verdict.allowed is True
    assert verdict.policy in {
        "shell_script_workspace_local",
        "unclassified_workspace_shell_command",
    }


def test_workspace_boundary_detector_allows_execution_root_cd_and_manifest_reads(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo" / "runtime" / "workers" / "worker-001"
    execution_root = tmp_path / ".codex-recipe" / "runtime" / "worker-001"
    command = (
        f'/bin/bash -lc "cd {execution_root} && '
        'cat worker_manifest.json current_packet.json OUTPUT_CONTRACT.md >/dev/null"'
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


def test_subprocess_workspace_worker_parses_token_usage_from_text_stream(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo" / "runtime" / "workers" / "worker-001"
    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / "assigned_shards.json").write_text(
        json.dumps([{"shard_id": "shard-001"}]),
        encoding="utf-8",
    )
    (source_root / "out").mkdir(parents=True, exist_ok=True)

    class _FakeStdin:
        def __init__(self) -> None:
            self.buffer: list[str] = []

        def write(self, text: str) -> int:
            self.buffer.append(text)
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
        def __init__(self, command, _fake_stdin_cls=_FakeStdin, **kwargs):  # noqa: ANN001
            self.stdin = _fake_stdin_cls()
            self.stdout = _Stream(
                [
                    json.dumps({"type": "thread.started"}) + "\n",
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "agent_message",
                                "text": "Finished local task loop.",
                            },
                        }
                    )
                    + "\n",
                ]
            )
            self.stderr = _Stream(
                [
                    "Token usage: total=130 input=100 (+ 10 cached) output=20 (reasoning 0)\n",
                ]
            )
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
    result = runner.run_workspace_worker(
        prompt_text="Process local task files and write outputs.",
        working_dir=source_root,
        env={"CODEX_HOME": str(tmp_path / ".codex-recipe")},
        workspace_task_label="canonical line-role worker session",
    )

    assert result.usage == {
        "input_tokens": 100,
        "cached_input_tokens": 10,
        "output_tokens": 20,
        "reasoning_tokens": 0,
    }

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
        def __init__(self, command, _fake_stdin_cls=_FakeStdin, **kwargs):  # noqa: ANN001
            captured["command"] = list(command)
            captured["cwd"] = kwargs.get("cwd")
            captured["env"] = dict(kwargs.get("env") or {})
            self.stdin = _fake_stdin_cls()
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
        workspace_task_label="non-recipe finalize shard",
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
    assert "non-recipe finalize shard" in (cwd / "AGENTS.md").read_text(encoding="utf-8")
    assert result.source_working_dir == str(source_root)
    assert result.execution_working_dir == str(cwd)
    assert result.execution_agents_path == str(cwd / "AGENTS.md")


def test_workspace_worker_uses_configured_codex_home_even_under_output_run_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "configured-codex-home"
    monkeypatch.setenv("COOKIMPORT_CODEX_FARM_CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_FARM_CODEX_HOME_RECIPE", str(codex_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    source_root = (
        tmp_path
        / "data"
        / "output"
        / "2026-03-30_10.55.05"
        / "raw"
        / "llm"
        / "book"
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
    )
    (source_root / "in").mkdir(parents=True, exist_ok=True)
    (source_root / "assigned_shards.json").write_text(
        json.dumps([{"shard_id": "shard-001"}]),
        encoding="utf-8",
    )
    (source_root / "in" / "shard-001.json").write_text(
        json.dumps({"shard_id": "shard-001"}),
        encoding="utf-8",
    )

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
        def __init__(self, command, _fake_stdin_cls=_FakeStdin, **kwargs):  # noqa: ANN001
            captured["command"] = list(command)
            captured["cwd"] = kwargs.get("cwd")
            captured["env"] = dict(kwargs.get("env") or {})
            self.stdin = _fake_stdin_cls()
            self.stdout = _Stream(
                [
                    json.dumps({"type": "thread.started"}) + "\n",
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "agent_message",
                                "text": "Completed local workspace task.",
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
    result = runner.run_workspace_worker(
        prompt_text="Process local worker files and write outputs under out/.",
        working_dir=source_root,
        env={},
        workspace_task_label="recipe correction worker session",
    )

    cwd = Path(str(captured["cwd"]))
    env = dict(captured["env"] or {})
    expected_prefix = codex_home / "recipeimport-direct-exec-workspaces"

    assert str(cwd).startswith(str(expected_prefix))
    assert str(cwd).startswith(str(source_root.parent.parent.parent)) is False
    assert env["CODEX_HOME"] == str(codex_home)
    assert env["CODEX_FARM_CODEX_HOME_RECIPE"] == str(codex_home)
    assert result.execution_working_dir == str(cwd)
    assert result.source_working_dir == str(source_root)


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
        def __init__(self, _fake_stdin_cls=_FakeStdin) -> None:
            self.stdin = _fake_stdin_cls()
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
        workspace_task_label="non-recipe finalize shard",
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
    monkeypatch.setattr(
        exec_runner_module,
        "_DIRECT_EXEC_COMPLETED_TERMINATION_GRACE_SECONDS",
        0.05,
    )
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
        def __init__(self, cwd: Path, _fake_stdin_cls=_FakeStdin) -> None:
            self.stdin = _fake_stdin_cls()
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


@pytest.mark.parametrize(
    ("supervision_state", "reason_code"),
    [
        ("completed", "workspace_outputs_stabilized"),
        ("completed_with_failures", "workspace_validated_task_queue_incomplete"),
    ],
)
def test_workspace_worker_completed_supervision_allows_turn_completed_usage_to_arrive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    supervision_state: str,
    reason_code: str,
) -> None:
    monkeypatch.setattr(
        exec_runner_module,
        "_DIRECT_EXEC_COMPLETED_TERMINATION_GRACE_SECONDS",
        0.2,
    )
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

    class _FakeStdin:
        def write(self, text: str) -> int:
            return len(text)

        def close(self) -> None:
            return None

    class _DynamicStream:
        def __init__(self, owner: "_FakeProcess") -> None:
            self._owner = owner
            self._lines: list[str] = []

        def push(self, payload: dict[str, Any]) -> None:
            self._lines.append(json.dumps(payload) + "\n")

        def readline(self) -> str:
            while not self._lines:
                if self._owner.returncode is not None:
                    return ""
                time.sleep(0.01)
            return self._lines.pop(0)

        def close(self) -> None:
            return None

    class _FakeProcess:
        def __init__(self, cwd: Path, _fake_stdin_cls=_FakeStdin) -> None:
            self.stdin = _fake_stdin_cls()
            self.returncode: int | None = None
            self.stdout = _DynamicStream(self)
            self.stderr = _DynamicStream(self)
            self._cwd = cwd
            self.stdout.push({"type": "thread.started"})

            def _writer() -> None:
                time.sleep(0.05)
                out_dir = cwd / "out"
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "shard-001.json").write_text(
                    json.dumps({"v": "2", "bid": "shard-001", "r": []}),
                    encoding="utf-8",
                )
                time.sleep(0.05)
                self.stdout.push(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "Finished."},
                    }
                )
                self.stdout.push(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 10,
                            "output_tokens": 20,
                        },
                    }
                )
                self.returncode = 0

            threading.Thread(target=_writer, daemon=True).start()

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(
        "cookimport.llm.codex_exec_runner.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(Path(str(kwargs["cwd"]))),
    )

    runner = SubprocessCodexExecRunner(cmd="codex exec")
    result = runner.run_workspace_worker(
        prompt_text="Write shard output files locally and stop once done.",
        working_dir=source_root,
        env={"CODEX_HOME": str(tmp_path / ".codex-recipe")},
        workspace_task_label="knowledge worker session",
        supervision_callback=lambda _snapshot: (
            CodexExecSupervisionDecision.terminate(
                reason_code=reason_code,
                reason_detail="worker outputs stabilized",
                retryable=False,
                supervision_state=supervision_state,
            )
            if (source_root / "out" / "shard-001.json").exists()
            else None
        ),
    )

    assert result.subprocess_exit_code == 0
    assert result.usage == {
        "input_tokens": 100,
        "cached_input_tokens": 10,
        "output_tokens": 20,
        "reasoning_tokens": 0,
    }
    assert result.supervision_reason_code == reason_code
    assert result.supervision_state == supervision_state
    assert result.completed_successfully() is True
