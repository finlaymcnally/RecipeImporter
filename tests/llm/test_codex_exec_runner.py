from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from cookimport.llm.codex_exec_runner import (
    _build_codex_exec_command,
    assess_final_agent_message,
    classify_workspace_worker_command,
    CodexExecRunResult,
    CodexExecLiveSnapshot,
    CodexExecSupervisionDecision,
    FakeCodexExecRunner,
    SubprocessCodexExecRunner,
    is_tolerated_workspace_worker_command,
    prepare_direct_exec_workspace,
    rewrite_direct_exec_prompt_paths,
    should_terminate_workspace_command_loop,
    summarize_direct_telemetry_rows,
)


def test_codex_exec_runner_extracts_command_and_reasoning_pathology() -> None:
    run_result = CodexExecRunResult(
        command=["codex", "exec", "--model", "gpt-5"],
        subprocess_exit_code=0,
        output_schema_path="/tmp/schema.json",
        prompt_text="Label these rows.",
        response_text='{"rows":[{"atomic_index":1,"label":"OTHER"}]}',
        turn_failed_message=None,
        duration_ms=4321,
        started_at_utc="2026-03-19T12:00:00Z",
        finished_at_utc="2026-03-19T12:00:04Z",
        events=(
            {"type": "thread.started"},
            {
                "type": "item.started",
                "item": {
                    "id": "item_0",
                    "type": "command_execution",
                    "command": "/bin/bash -lc ls",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "item_0",
                    "type": "command_execution",
                    "command": "/bin/bash -lc ls",
                    "exit_code": 0,
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "item_1",
                    "type": "reasoning",
                    "text": "I should inspect the file first.",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "item_2",
                    "type": "agent_message",
                    "text": '{"rows":[{"atomic_index":1,"label":"OTHER"}]}',
                },
            },
        ),
        usage={
            "input_tokens": 500,
            "cached_input_tokens": 100,
            "output_tokens": 50,
            "reasoning_tokens": 25,
        },
    )

    row = run_result.telemetry_row(worker_id="worker-001", shard_id="shard-001")
    row["proposal_status"] = "invalid"
    row["prompt_input_mode"] = "workspace_worker"
    row["worker_session_primary_row"] = True

    assert row["command_execution_count"] == 1
    assert row["command_execution_commands"] == ["/bin/bash -lc ls"]
    assert row["reasoning_item_count"] == 1
    assert row["duration_ms"] == 4321
    assert row["started_at_utc"] == "2026-03-19T12:00:00Z"
    assert row["finished_at_utc"] == "2026-03-19T12:00:04Z"
    assert "command_execution_detected" in row["pathological_flags"]
    assert "reasoning_items_detected" in row["pathological_flags"]

    summary = summarize_direct_telemetry_rows([row])

    assert summary["command_execution_count_total"] == 1
    assert summary["command_executing_shard_count"] == 1
    assert summary["reasoning_item_count_total"] == 1
    assert summary["reasoning_heavy_shard_count"] == 1
    assert summary["invalid_output_shard_count"] == 1
    assert summary["invalid_output_tokens_total"] == row["tokens_total"]
    assert summary["workspace_worker_row_count"] == 1
    assert summary["workspace_worker_session_count"] == 1
    assert summary["prompt_input_mode_counts"] == {"workspace_worker": 1}
    assert "command_execution_detected" in summary["pathological_flags"]
    assert "invalid_output_detected" in summary["pathological_flags"]


def test_summarize_direct_telemetry_rows_counts_structured_followups() -> None:
    summary = summarize_direct_telemetry_rows(
        [
            {
                "task_id": "shard-001",
                "tokens_total": 10,
                "prompt_input_mode": "workspace_worker",
                "worker_session_primary_row": True,
            },
            {
                "task_id": "shard-001",
                "tokens_total": 4,
                "prompt_input_mode": "inline_watchdog_retry",
            },
            {
                "task_id": "shard-001.retry",
                "tokens_total": 6,
                "prompt_input_mode": "inline_retry",
            },
            {
                "task_id": "shard-001",
                "tokens_total": 8,
                "prompt_input_mode": "inline_repair",
            },
        ]
    )

    assert summary["call_count"] == 4
    assert summary["workspace_worker_row_count"] == 1
    assert summary["workspace_worker_session_count"] == 1
    assert summary["structured_followup_call_count"] == 3
    assert summary["structured_followup_tokens_total"] == 18
    assert summary["prompt_input_mode_counts"] == {
        "inline_repair": 1,
        "inline_retry": 1,
        "inline_watchdog_retry": 1,
        "workspace_worker": 1,
    }


def test_codex_exec_runner_classifies_final_agent_messages() -> None:
    assert assess_final_agent_message(None).state == "absent"
    malformed = assess_final_agent_message("thinking...\n{\"v\":\"2\"}")
    assert malformed.state == "malformed"
    assert "did not start" in str(malformed.reason)
    json_object = assess_final_agent_message('{"v":"2","bid":"shard-001","r":[]}')
    assert json_object.state == "json_object"
    assert json_object.reason is None


def test_codex_exec_runner_only_kills_pathological_workspace_command_loops() -> None:
    normal_snapshot = CodexExecLiveSnapshot(
        elapsed_seconds=0.1,
        last_event_seconds_ago=0.0,
        event_count=2,
        command_execution_count=6,
        reasoning_item_count=0,
        last_command="/bin/bash -lc cat in/shard-001.json",
        last_command_repeat_count=2,
        has_final_agent_message=False,
        timeout_seconds=30,
    )
    assert should_terminate_workspace_command_loop(snapshot=normal_snapshot) is False

    over_budget_snapshot = CodexExecLiveSnapshot(
        elapsed_seconds=0.2,
        last_event_seconds_ago=0.0,
        event_count=3,
        command_execution_count=300,
        reasoning_item_count=0,
        last_command="/bin/bash -lc cat in/shard-001.json",
        last_command_repeat_count=1,
        has_final_agent_message=False,
        timeout_seconds=30,
    )
    assert should_terminate_workspace_command_loop(snapshot=over_budget_snapshot) is True


def test_codex_exec_runner_allows_relaxed_workspace_shell_commands() -> None:
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'cat assigned_shards.json'") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc cat assigned_shards.json") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'head -n 20 in/shard-001.json'") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'jq .rows[0] in/shard-001.json'") is True
    assert (
        is_tolerated_workspace_worker_command(
            "/bin/bash -lc \"jq '.[0] | keys' assigned_shards.json\""
        )
        is True
    )
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'ls in'") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'ls shards'") is True
    assert is_tolerated_workspace_worker_command(
        "/bin/bash -lc 'rg -n \"shard-001\" assigned_shards.json'"
    ) is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'rg -n \"not_a_recipe\" -n'") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'find . -maxdepth 2'") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'tree .'") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'test -f out/shard-001.json'") is True
    assert (
        is_tolerated_workspace_worker_command(
            "/bin/bash -lc 'if [ -f out/shard-001.json ]; then echo exists; else echo missing; fi'"
        )
        is True
    )
    assert (
        is_tolerated_workspace_worker_command(
            "/bin/bash -lc \"jq '{rows: [.rows[] | {atomic_index: .[0]}]}' in/shard-001.json > out/shard-001.json\""
        )
        is True
    )
    assert (
        is_tolerated_workspace_worker_command(
            "/bin/bash -lc \"cat <<'EOF' > out/shard-001.json\n{\\\"rows\\\": []}\nEOF\""
        )
        is True
    )
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'cat temp.json'") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'cat out/*.json'") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc sed -n '1,20p' in/shard-001.json") is True

    assert is_tolerated_workspace_worker_command("/bin/bash -lc \"python -c 'print(1)'\"") is False
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'env python -c \"print(1)\"'") is False
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'cat ../secret.txt'") is False
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'cat /tmp/secret.txt'") is False
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'git status --short'") is False


def test_codex_exec_runner_classifies_workspace_commands_for_telemetry() -> None:
    helper = classify_workspace_worker_command("/bin/bash -lc 'cat in/shard-001.json'")
    assert helper.allowed is True
    assert helper.policy == "tolerated_workspace_shell_command"

    orientation = classify_workspace_worker_command("/bin/bash -lc ls")
    assert orientation.allowed is True
    assert orientation.policy == "tolerated_orientation_command"

    shell = classify_workspace_worker_command(
        "/bin/bash -lc \"jq '{rows: [.rows[] | {atomic_index: .[0]}]}' in/shard-001.json > out/shard-001.json\""
    )
    assert shell.allowed is True
    assert shell.policy == "tolerated_workspace_shell_command"

    root_relative = classify_workspace_worker_command("/bin/bash -lc 'cat temp.json'")
    assert root_relative.allowed is True
    assert root_relative.policy == "tolerated_workspace_shell_command"

    forbidden = classify_workspace_worker_command(
        "/bin/bash -lc \"python -c 'print(1)'\""
    )
    assert forbidden.allowed is False
    assert forbidden.policy == "forbidden_non_helper_executable"


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
    assert (source_root / "worker_manifest.json").exists()
    assert (workspace.execution_working_dir / "worker_manifest.json").exists()
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
        "absolute paths",
        "parent-directory traversal",
    ]
    assert "Read the local task manifests and input files directly." in agents_text
    assert "Start by reading `worker_manifest.json`" in agents_text
    assert "`assigned_tasks.json`" in agents_text
    assert "`hints/...`" in agents_text
    assert "Workspace-local shell commands are broadly allowed when they materially help" in agents_text
    assert "The watchdog is boundary-based" in agents_text
    assert "avoid repo/network/interpreter commands such as `git`, `python`, `node`, `curl`, or package managers" in agents_text
    assert "approved local output files under `out/`" in agents_text
    assert (workspace.execution_working_dir / "out").exists()
    assert (workspace.execution_working_dir / "hints" / "shard-001.md").exists()


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


def test_build_codex_exec_command_includes_required_direct_exec_flags(tmp_path: Path) -> None:
    working_dir = tmp_path / "runtime-worker"
    schema_path = tmp_path / "schema.json"

    command = _build_codex_exec_command(
        cmd="codex exec",
        working_dir=working_dir,
        output_schema_path=schema_path,
        model="gpt-5.1-codex-mini",
        reasoning_effort="medium",
    )

    assert command[:2] == ["codex", "exec"]
    assert "--json" in command
    assert "--ephemeral" in command
    assert "--skip-git-repo-check" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--cd") + 1] == str(working_dir)
    assert command[command.index("--output-schema") + 1] == str(schema_path)
    assert command[command.index("--model") + 1] == "gpt-5.1-codex-mini"
    assert command[command.index("-c") + 1] == 'model_reasoning_effort="medium"'
    assert command[-1] == "-"


def test_build_codex_exec_command_can_request_workspace_write(tmp_path: Path) -> None:
    working_dir = tmp_path / "runtime-worker"

    command = _build_codex_exec_command(
        cmd="codex exec",
        working_dir=working_dir,
        output_schema_path=None,
        model=None,
        reasoning_effort=None,
        sandbox_mode="workspace-write",
    )

    assert command[command.index("--sandbox") + 1] == "workspace-write"


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
    assert result.supervision_state == "completed"
    assert result.supervision_reason_code == "workspace_outputs_stabilized"
    assert result.completed_successfully() is True
