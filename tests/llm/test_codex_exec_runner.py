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


def test_summarize_direct_telemetry_rows_prefers_final_supervision_state() -> None:
    summary = summarize_direct_telemetry_rows(
        [
            {
                "task_id": "shard-001",
                "supervision_state": "watchdog_killed",
                "raw_supervision_state": "watchdog_killed",
                "final_supervision_state": "completed",
                "finalization_path": "watchdog_retry_recovered",
            },
            {
                "task_id": "shard-002",
                "supervision_state": "watchdog_killed",
            },
        ]
    )

    assert summary["watchdog_killed_shard_count"] == 1
    assert summary["watchdog_recovered_shard_count"] == 1
    assert summary["pathological_shard_count"] == 2
    assert "watchdog_kills_detected" in summary["pathological_flags"]


def test_summarize_direct_telemetry_rows_prefers_final_proposal_status() -> None:
    summary = summarize_direct_telemetry_rows(
        [
            {
                "task_id": "shard-001",
                "proposal_status": "invalid",
                "final_proposal_status": "validated",
            },
            {
                "task_id": "shard-001",
                "proposal_status": "validated",
                "repair_status": "repaired",
            },
        ]
    )

    assert summary["invalid_output_shard_count"] == 0
    assert summary["repaired_shard_count"] == 1


def test_summarize_direct_telemetry_rows_counts_same_session_fix_statuses() -> None:
    summary = summarize_direct_telemetry_rows(
        [
            {
                "task_id": "shard-001",
                "same_session_fix_attempted": True,
                "same_session_fix_status": "recovered",
            },
            {
                "task_id": "shard-002",
                "same_session_fix_attempted": True,
                "same_session_fix_status": "budget_exhausted",
            },
        ]
    )

    assert summary["same_session_fix_attempted_task_count"] == 2
    assert summary["same_session_fix_recovered_task_count"] == 1
    assert summary["same_session_fix_escalated_task_count"] == 1
    assert summary["same_session_fix_budget_exhausted_task_count"] == 1


def test_summarize_direct_telemetry_rows_marks_missing_usage_unavailable() -> None:
    summary = summarize_direct_telemetry_rows(
        [
            {
                "task_id": "shard-001",
                "duration_ms": 1200,
                "prompt_input_mode": "workspace_worker",
                "worker_session_primary_row": True,
                "visible_input_tokens": 90,
                "visible_output_tokens": 8,
                "command_execution_count": 3,
                "codex_event_count": 12,
                "tokens_input": 0,
                "tokens_cached_input": 0,
                "tokens_output": 0,
                "tokens_reasoning": 0,
                "tokens_total": 0,
            }
        ]
    )

    assert summary["token_usage_status"] == "unavailable"
    assert summary["token_usage_available_call_count"] == 0
    assert summary["token_usage_missing_call_count"] == 1
    assert summary["tokens_total"] is None
    assert summary["command_execution_tokens_total"] is None
    assert summary["cost_breakdown"]["billed_total_tokens"] is None


def test_summarize_direct_telemetry_rows_marks_partial_usage_unavailable() -> None:
    summary = summarize_direct_telemetry_rows(
        [
            {
                "task_id": "shard-001",
                "prompt_input_mode": "workspace_worker",
                "worker_session_primary_row": True,
                "tokens_input": 100,
                "tokens_cached_input": 10,
                "tokens_output": 20,
                "tokens_reasoning": 0,
                "tokens_total": 130,
            },
            {
                "task_id": "shard-002",
                "duration_ms": 900,
                "prompt_input_mode": "workspace_worker",
                "worker_session_primary_row": True,
                "visible_input_tokens": 60,
                "visible_output_tokens": 4,
                "command_execution_count": 2,
                "tokens_input": 0,
                "tokens_cached_input": 0,
                "tokens_output": 0,
                "tokens_reasoning": 0,
                "tokens_total": 0,
            },
        ]
    )

    assert summary["token_usage_status"] == "partial"
    assert summary["token_usage_available_call_count"] == 1
    assert summary["token_usage_missing_call_count"] == 1
    assert summary["tokens_total"] is None
    assert summary["cost_breakdown"]["billed_total_tokens"] is None


def test_codex_exec_run_result_payload_marks_missing_usage_unavailable() -> None:
    run_result = CodexExecRunResult(
        command=["codex", "exec", "--model", "gpt-5"],
        subprocess_exit_code=0,
        output_schema_path=None,
        prompt_text="Process the local worker queue.",
        response_text="Finished local task loop.",
        turn_failed_message=None,
        duration_ms=1500,
        started_at_utc="2026-03-22T23:00:00Z",
        finished_at_utc="2026-03-22T23:00:02Z",
        events=(
            {"type": "thread.started"},
            {
                "type": "item.completed",
                "item": {
                    "id": "item_0",
                    "type": "command_execution",
                    "command": "/bin/bash -lc 'python3 tools/line_role_worker.py install-phase'",
                    "exit_code": 0,
                },
            },
        ),
        usage=None,
        workspace_mode="workspace_worker",
    )

    payload = run_result.to_payload(worker_id="worker-001", shard_id="shard-001")
    summary = payload["telemetry"]["summary"]

    assert summary["token_usage_status"] == "unavailable"
    assert summary["token_usage_missing_call_count"] == 1
    assert summary["tokens_total"] is None


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

    assert (
        should_terminate_workspace_command_loop(
            snapshot=over_budget_snapshot,
            recent_output_progress=True,
            completed_output_count=2,
        )
        is False
    )


def test_codex_exec_runner_allows_relaxed_workspace_shell_commands() -> None:
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'cat assigned_shards.json'") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc cat assigned_shards.json") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'cat current_task.json'") is True
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
    assert (
        is_tolerated_workspace_worker_command(
            "/bin/bash -lc \"python3 -c "
            "'from pathlib import Path; "
            "Path(\\\"out/task-001.json\\\").write_text(Path(\\\"in/task-001.json\\\").read_text())'\""
        )
        is True
    )
    assert (
        is_tolerated_workspace_worker_command(
            "/bin/bash -lc \"python3 - <<'PY'\n"
            "from pathlib import Path\n"
            "Path('out/task-001.json').write_text(Path('in/task-001.json').read_text())\n"
            "PY\""
        )
        is True
    )
    assert (
        is_tolerated_workspace_worker_command(
            "/bin/bash -lc \"node -e "
            "\\\"const fs=require('fs'); "
            "fs.writeFileSync('out/task-001.json', fs.readFileSync('in/task-001.json', 'utf8'));\\\"\""
        )
        is True
    )

    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'pip install foo'") is False
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'curl https://example.com'") is False
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'cat ../secret.txt'") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'cat /tmp/secret.txt'") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'cat /var/tmp/helper.txt'") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'git status --short'") is True
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'git pull origin main'") is False
    assert is_tolerated_workspace_worker_command("/bin/bash -lc 'cat /etc/passwd'") is True


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

    recipe_bundle_read = classify_workspace_worker_command(
        "/bin/bash -lc \"cat hints/task-001.md && echo '---' && cat in/task-001.json && echo '---' && cat scratch/task-001.json\""
    )
    assert recipe_bundle_read.allowed is True
    assert recipe_bundle_read.policy == "recipe_task_bundle_read_command"

    recipe_contract_read = classify_workspace_worker_command(
        "/bin/bash -lc \"cat OUTPUT_CONTRACT.md && echo '---' && cat examples/valid_repaired_task_output.json\""
    )
    assert recipe_contract_read.allowed is True
    assert recipe_contract_read.policy == "recipe_contract_lookup_command"

    root_relative = classify_workspace_worker_command("/bin/bash -lc 'cat temp.json'")
    assert root_relative.allowed is True
    assert root_relative.policy == "tolerated_workspace_shell_command"

    python_transform = classify_workspace_worker_command(
        "/bin/bash -lc \"python3 -c "
        "'from pathlib import Path; "
        "Path(\\\"out/task-001.json\\\").write_text(Path(\\\"in/task-001.json\\\").read_text())'\""
    )
    assert python_transform.allowed is True
    assert python_transform.policy == "tolerated_workspace_shell_command"

    forbidden = classify_workspace_worker_command("/bin/bash -lc 'pip install foo'")
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

    assert (
        detect_workspace_worker_boundary_violation(
            "/bin/bash -lc \"python3 -c "
            "'from pathlib import Path; "
            "Path(\\\"out/task-001.json\\\").write_text(Path(\\\"in/task-001.json\\\").read_text())'\""
        )
        is None
    )
    assert (
        detect_workspace_worker_boundary_violation(
            "/bin/bash -lc \"node -e "
            "\\\"const fs=require('fs'); "
            "fs.writeFileSync('out/task-001.json', fs.readFileSync('in/task-001.json', 'utf8'));\\\"\""
        )
        is None
    )

    forbidden_tool = detect_workspace_worker_boundary_violation(
        "/bin/bash -lc 'pip install foo'"
    )
    assert forbidden_tool is not None
    assert forbidden_tool.policy == "forbidden_non_helper_executable"

    forbidden_git_mutation = detect_workspace_worker_boundary_violation(
        "/bin/bash -lc 'git pull origin main'"
    )
    assert forbidden_git_mutation is not None
    assert forbidden_git_mutation.policy == "forbidden_non_helper_executable"

    tolerated_temp_path = detect_workspace_worker_boundary_violation(
        "/bin/bash -lc 'cat /tmp/secret.txt'"
    )
    assert tolerated_temp_path is None

    assert detect_workspace_worker_boundary_violation("/bin/bash -lc 'cat /etc/passwd'") is None


def test_codex_exec_runner_allows_workspace_local_python_heredoc_edits() -> None:
    command = (
        "/bin/bash -lc \"python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "import json\n"
        "base = Path('scratch')\n"
        "doc = json.loads((base / 'task-001.json').read_text())\n"
        "doc['r'][0]['sr'] = 'insufficient source detail'\n"
        "doc['r'][0]['cr'] = None\n"
        "doc['r'][0]['mr'] = 'not_applicable_fragmentary'\n"
        "doc['r'][0]['st'] = 'fragmentary'\n"
        "(base / 'task-001.json').write_text(json.dumps(doc) + '\\n')\n"
        "yield_text = '1 1/4 cups'\n"
        "PY\""
    )

    assert detect_workspace_worker_boundary_violation(command) is None
    classification = classify_workspace_worker_command(command)
    assert classification.allowed is True
    assert classification.policy == "shell_script_workspace_local"


def test_codex_exec_runner_allows_python_heredoc_with_absolute_path_literals_under_relaxed_policy() -> None:
    command = (
        "/bin/bash -lc \"python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "Path('/etc/passwd').read_text()\n"
        "PY\""
    )

    assert detect_workspace_worker_boundary_violation(command) is None
    classification = classify_workspace_worker_command(command)
    assert classification.allowed is True
    assert classification.policy == "shell_script_workspace_local"


def test_codex_exec_runner_allows_absolute_paths_inside_explicit_execution_root() -> None:
    execution_root = Path(
        "/home/mcnal/.codex-recipe/recipeimport-direct-exec-workspaces/worker-004"
    )
    startup_command = (
        '/bin/bash -lc "cd '
        f"{execution_root}"
        ' && printf \'=== worker_manifest.json\\n\' && sed -n \'1,220p\' worker_manifest.json"'
    )
    helper_command = (
        '/bin/bash -lc "python3 '
        f"{execution_root / 'tools' / 'line_role_worker.py'}"
        ' overview"'
    )

    for command in (startup_command, helper_command):
        assert detect_workspace_worker_boundary_violation(command) is None

        assert (
            detect_workspace_worker_boundary_violation(
                command,
                allowed_absolute_roots=[execution_root],
            )
            is None
        )
        classification = classify_workspace_worker_command(
            command,
            allowed_absolute_roots=[execution_root],
        )
        assert classification.allowed is True
        assert classification.policy in {
            "shell_script_workspace_local",
            "tolerated_workspace_shell_command",
        }


def test_codex_exec_runner_keeps_outside_roots_and_absolute_out_paths_forbidden() -> None:
    execution_root = Path(
        "/home/mcnal/.codex-recipe/recipeimport-direct-exec-workspaces/worker-004"
    )
    outside_root = Path("/home/mcnal/projects/recipeimport")
    outside_command = (
        '/bin/bash -lc "cd '
        f"{outside_root}"
        ' && sed -n \'1,40p\' pyproject.toml"'
    )
    assert (
        detect_workspace_worker_boundary_violation(
            outside_command,
            allowed_absolute_roots=[execution_root],
        )
        is None
    )

    out_path_command = (
        '/bin/bash -lc "sed -n \'1,20p\' '
        f"{execution_root / 'out' / 'task-001.json'}"
        '"'
    )
    assert (
        detect_workspace_worker_boundary_violation(
            out_path_command,
            allow_output_paths=False,
            allowed_absolute_roots=[execution_root],
        )
        is None
    )


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


def test_codex_exec_runner_allows_multi_python_heredoc_shell_body() -> None:
    command = (
        "/bin/bash -lc \"python3 - <<'PY1'\n"
        "from pathlib import Path\n"
        "Path('scratch/current_task.json').write_text('{}\\n')\n"
        "PY1\n"
        "python3 - <<'PY2'\n"
        "from pathlib import Path\n"
        "Path('out/task-001.json').write_text(Path('scratch/current_task.json').read_text())\n"
        "PY2\""
    )

    assert detect_workspace_worker_boundary_violation(command) is None
    classification = classify_workspace_worker_command(command)
    assert classification.allowed is True
    assert classification.policy == "shell_script_workspace_local"


def test_codex_exec_runner_allows_slashy_heredoc_shell_write_payload() -> None:
    command = (
        "/bin/bash -lc \"cat > scratch/current_task.json <<'EOF'\n"
        "{\\\"task_id\\\":\\\"task-001\\\",\\\"source\\\":\\\"/home/mcnal/projects/recipeimport/data/input/book.pdf\\\","
        "\\\"ratio\\\":\\\"3/4\\\"}\n"
        "EOF\""
    )

    assert detect_workspace_worker_boundary_violation(command) is None
    classification = classify_workspace_worker_command(command)
    assert classification.allowed is True
    assert classification.policy in {
        "shell_script_workspace_local",
        "unclassified_workspace_shell_command",
    }


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
