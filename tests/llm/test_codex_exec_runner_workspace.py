from __future__ import annotations

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
        json.dumps([{"task_id": "shard-001", "parent_shard_id": "shard-001"}]),
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
        "assigned_tasks.json",
    ]
    assert worker_manifest["hints_dir"] == "hints"
    assert worker_manifest["scratch_dir"] == "scratch"
    assert worker_manifest["workspace_shell_policy"].startswith(
        "Allow ordinary local shell use inside this workspace."
    )
    assert worker_manifest["workspace_local_shell_examples"] == [
        "rg -n \"needle\" -n",
        "jq '.[0] | keys' assigned_shards.json",
        "jq '.[0] | keys' assigned_tasks.json",
        "jq '{rows: ...}' in/<shard>.json > out/<shard>.json",
        "cat <<'EOF' > out/<shard>.json",
    ]
    assert worker_manifest["workspace_commands_forbidden"] == [
        "repo/network/interpreter commands such as git, python, node, curl, wget, or package managers",
        "inline interpreters such as python - <<'PY' or python -c",
        "absolute paths",
        "/tmp paths",
        "parent-directory traversal",
    ]
    assert "Read the local task manifests and input files directly." in agents_text
    assert "Start by reading `worker_manifest.json`" in agents_text
    assert "`assigned_tasks.json`" in agents_text
    assert "`current_packet.json`, `current_hint.md`, and `current_result_path.txt`" in agents_text
    assert "Workspace-local shell commands are broadly allowed when they materially help" in agents_text
    assert "The watchdog is boundary-based" in agents_text
    assert "avoid repo/network/interpreter commands such as `git`, `python`, `node`, `curl`, or package managers" in agents_text
    assert "Use `scratch/` for bounded helper files." in agents_text
    assert (workspace.execution_working_dir / "out").exists()
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
    assert worker_manifest["current_packet_file"] == "current_packet.json"
    assert worker_manifest["current_hint_file"] == "current_hint.md"
    assert worker_manifest["current_result_path_file"] == "current_result_path.txt"
    assert worker_manifest["packet_lease_status_file"] == "packet_lease_status.json"
    assert worker_manifest["scratch_dir"] == "scratch"
    assert (workspace.execution_working_dir / "current_packet.json").exists()
    assert (workspace.execution_working_dir / "current_hint.md").exists()
    assert (workspace.execution_working_dir / "current_result_path.txt").exists()
    assert (workspace.execution_working_dir / "packet_lease_status.json").exists()
    assert (workspace.execution_working_dir / "scratch").exists()


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
