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
    detect_workspace_worker_boundary_violation,
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
    informational = assess_final_agent_message(
        "Finished local task loop.",
        workspace_mode="workspace_worker",
    )
    assert informational.state == "informational"
    assert "informational only" in str(informational.reason)
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
    assert (
        is_tolerated_workspace_worker_command(
            "/bin/bash -lc \"jq -r '.[].task_id' assigned_tasks.json | while read -r task; do\n"
            "  cat \\\"hints/$task.md\\\" >/dev/null\n"
            "  jq -M -c '{v: \\\"1\\\"}' \\\"in/$task.json\\\" > \\\"out/$task.json\\\"\n"
            "done\""
        )
        is True
    )
    assert (
        is_tolerated_workspace_worker_command(
            "/bin/bash -lc \"cat hints/saltfatacidheatcutdown.ks0009.nr.task-001.md >/dev/null\n"
            "jq --arg task \\\"saltfatacidheatcutdown.ks0009.nr.task-001\\\" "
            "--slurpfile meta \\\"in/saltfatacidheatcutdown.ks0009.nr.task-001.json\\\" "
            "'.' > \\\"out/saltfatacidheatcutdown.ks0009.nr.task-001.json\\\"\""
        )
        is True
    )

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

    off_task_orientation = classify_workspace_worker_command(
        "/bin/bash -lc 'find . -maxdepth 2'",
        allow_orientation_commands=False,
    )
    assert off_task_orientation.allowed is False
    assert off_task_orientation.policy == "forbidden_orientation_command"

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


def test_codex_exec_runner_detects_boundary_violations_separately_from_telemetry() -> None:
    assert (
        detect_workspace_worker_boundary_violation(
            "/bin/bash -lc 'jq .rows[0] in/shard-001.json > out/shard-001.json'"
        )
        is None
    )
    assert (
        detect_workspace_worker_boundary_violation(
            "/bin/bash -lc 'cat <<'\"'\"'EOF'\"'\"' > out/shard-001.json\n"
            "{\"rows\":[]}\n"
            "EOF"
        )
        is None
    )

    forbidden_tool = detect_workspace_worker_boundary_violation(
        "/bin/bash -lc \"python -c 'print(1)'\""
    )
    assert forbidden_tool is not None
    assert forbidden_tool.policy == "forbidden_non_helper_executable"

    forbidden_path = detect_workspace_worker_boundary_violation(
        "/bin/bash -lc 'cat /tmp/secret.txt'"
    )
    assert forbidden_path is not None
    assert forbidden_path.policy == "forbidden_absolute_path"


def test_codex_exec_runner_keeps_unparseable_but_bounded_shell_unclassified() -> None:
    command = (
        "/bin/bash -lc 'cat <<\"EOF\" > out/shard-001.json\n"
        "{\"rows\":[]}\n"
        "EOF"
    )

    assert detect_workspace_worker_boundary_violation(command) is None

    classification = classify_workspace_worker_command(command)
    assert classification.allowed is True
    assert classification.policy == "unclassified_workspace_shell_command"


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
