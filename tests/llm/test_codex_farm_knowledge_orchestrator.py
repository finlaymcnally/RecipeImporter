from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from cookimport.config.run_settings import RunSettings
from cookimport.core.progress_messages import parse_stage_progress
from cookimport.core.models import ChunkLane, ConversionReport, ConversionResult, KnowledgeChunk, RawArtifact
from cookimport.llm import codex_farm_knowledge_orchestrator as knowledge_module
from cookimport.llm.codex_farm_knowledge_orchestrator import (
    _preflight_knowledge_shard,
    _is_pathological_knowledge_response_text,
    _run_direct_knowledge_workers_v1,
    run_codex_farm_nonrecipe_knowledge_review,
)
from cookimport.llm.codex_exec_runner import CodexExecLiveSnapshot, FakeCodexExecRunner
from cookimport.llm.codex_exec_runner import CodexExecRunResult
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.llm.fake_codex_farm_runner import build_structural_pipeline_output
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1
from cookimport.llm.phase_worker_runtime import TaskManifestEntryV1
from cookimport.parsing.label_source_of_truth import RecipeSpan
from cookimport.staging.nonrecipe_stage import NonRecipeSpan, NonRecipeStageResult


def _semantic_packet_output(
    *,
    packet_id: str,
    chunk_id: str,
    block_indices: list[int],
    useful: bool = True,
    snippet_body: str = "Fake knowledge snippet.",
    evidence_quote: str = "Fake knowledge snippet.",
) -> dict[str, object]:
    return {
        "packet_id": packet_id,
        "chunk_results": [
            {
                "chunk_id": chunk_id,
                "is_useful": useful,
                "block_decisions": [
                    {
                        "block_index": block_index,
                        "category": "knowledge" if useful else "other",
                    }
                    for block_index in block_indices
                ],
                "snippets": (
                    [
                        {
                            "body": snippet_body,
                            "evidence": [
                                {
                                    "block_index": block_indices[0],
                                    "quote": evidence_quote,
                                }
                            ],
                        }
                    ]
                    if useful
                    else []
                ),
                "reason_code": "grounded_useful" if useful else "all_other",
            }
        ],
    }


class _NoFinalWorkspaceMessageRunner(FakeCodexExecRunner):
    def run_workspace_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
        result = super().run_workspace_worker(**kwargs)
        return CodexExecRunResult(
            command=list(result.command),
            subprocess_exit_code=result.subprocess_exit_code,
            output_schema_path=result.output_schema_path,
            prompt_text=result.prompt_text,
            response_text=None,
            turn_failed_message=result.turn_failed_message,
            events=tuple(
                event
                for event in result.events
                if event.get("item", {}).get("type") != "agent_message"
            ),
            usage=dict(result.usage or {}),
            stderr_text=result.stderr_text,
            stdout_text=result.stdout_text,
            source_working_dir=result.source_working_dir,
            execution_working_dir=result.execution_working_dir,
            execution_agents_path=result.execution_agents_path,
            duration_ms=result.duration_ms,
            started_at_utc=result.started_at_utc,
            finished_at_utc=result.finished_at_utc,
            workspace_mode=result.workspace_mode,
            supervision_state=result.supervision_state,
            supervision_reason_code=result.supervision_reason_code,
            supervision_reason_detail=result.supervision_reason_detail,
            supervision_retryable=result.supervision_retryable,
        )


def test_knowledge_workspace_watchdog_allows_shell_work_until_command_loop(
    tmp_path: Path,
) -> None:
    callback = knowledge_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.4,
            last_event_seconds_ago=0.0,
            event_count=12,
            command_execution_count=6,
            reasoning_item_count=0,
            last_command="/bin/bash -lc cat in/book.ks0000.nr.json",
            last_command_repeat_count=2,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["last_command_policy"] == "tolerated_workspace_shell_command"
    assert live_status["last_command_policy_allowed"] is True
    assert live_status["last_command_boundary_violation_detected"] is False


def test_knowledge_workspace_watchdog_allows_orientation_and_helper_scripts(
    tmp_path: Path,
) -> None:
    callback = knowledge_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.7,
            last_event_seconds_ago=0.0,
            event_count=18,
            command_execution_count=7,
            reasoning_item_count=0,
            last_command=(
                "/bin/bash -lc \"pwd\n"
                "find . -maxdepth 2 -type f | head -n 5 >/dev/null\n"
                "cat <<'EOF' > scratch/helper.sh\n"
                "jq -M -c '{v: \\\"2\\\", bid: .task_id, r: []}' current_packet.json > \\\"$1\\\"\n"
                "EOF\""
            ),
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["last_command_policy_allowed"] is True
    assert live_status["last_command_policy"] in {
        "shell_script_workspace_local",
        "tolerated_orientation_command",
        "tolerated_workspace_shell_command",
    }
    assert live_status["last_command_boundary_violation_detected"] is False


def test_knowledge_workspace_watchdog_allows_jq_fallback_operator_output_command(
    tmp_path: Path,
) -> None:
    callback = knowledge_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.7,
            last_event_seconds_ago=0.0,
            event_count=18,
            command_execution_count=7,
            reasoning_item_count=0,
            last_command=(
                "/bin/bash -lc \"jq '{rows: .rows | map({atomic_index: .[0], "
                "label: ({\\\"L8\\\":\\\"KNOWLEDGE\\\"}[.[1]] // \\\"OTHER\\\")})}' "
                "current_packet.json > out/task-001.json\""
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


def test_knowledge_workspace_watchdog_allows_bounded_python_heredoc(
    tmp_path: Path,
) -> None:
    callback = knowledge_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.7,
            last_event_seconds_ago=0.0,
            event_count=18,
            command_execution_count=7,
            reasoning_item_count=0,
            last_command=(
                "/bin/bash -lc \"python3 - <<'PY'\n"
                "from pathlib import Path\n"
                "Path('out/task-001.json').write_text(Path('current_packet.json').read_text())\n"
                "PY\""
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


def test_knowledge_workspace_watchdog_can_forbid_inline_python_heredoc(
    tmp_path: Path,
) -> None:
    callback = knowledge_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
        allow_workspace_commands=True,
        forbid_inline_python_heredocs=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.7,
            last_event_seconds_ago=0.0,
            event_count=18,
            command_execution_count=7,
            reasoning_item_count=0,
            last_command=(
                "/bin/bash -lc \"python3 - <<'PY'\n"
                "from pathlib import Path\n"
                "Path('out/task-001.json').write_text(Path('current_task.json').read_text())\n"
                "PY\""
            ),
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is not None
    assert decision.reason_code == "watchdog_inline_python_heredoc_forbidden"


def test_knowledge_workspace_watchdog_allows_execution_root_cd_prefix(
    tmp_path: Path,
) -> None:
    worker_root = Path(
        "/home/mcnal/.codex-recipe/recipeimport-direct-exec-workspaces/worker-root"
    )
    callback = knowledge_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
        allow_workspace_commands=True,
        execution_workspace_root=worker_root,
    )
    command = (
        '/bin/bash -lc "cd '
        f"{worker_root}"
        ' && printf \'=== worker_manifest.json\\n\' && sed -n \'1,220p\' worker_manifest.json"'
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.8,
            last_event_seconds_ago=0.0,
            event_count=18,
            command_execution_count=7,
            reasoning_item_count=0,
            last_command=command,
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["last_command_policy_allowed"] is True
    assert live_status["last_command_boundary_violation_detected"] is False


def test_knowledge_workspace_watchdog_still_rejects_absolute_paths_outside_execution_root(
    tmp_path: Path,
) -> None:
    worker_root = Path(
        "/home/mcnal/.codex-recipe/recipeimport-direct-exec-workspaces/worker-root"
    )
    outside_root = Path("/home/mcnal/projects/recipeimport")
    callback = knowledge_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
        allow_workspace_commands=True,
        execution_workspace_root=worker_root,
    )
    command = (
        '/bin/bash -lc "cd '
        f"{outside_root}"
        ' && printf \'=== worker_manifest.json\\n\' && sed -n \'1,220p\' worker_manifest.json"'
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.8,
            last_event_seconds_ago=0.0,
            event_count=18,
            command_execution_count=7,
            reasoning_item_count=0,
            last_command=command,
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is not None
    assert decision.reason_code == "watchdog_command_execution_forbidden"
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["last_command_policy"] == "forbidden_absolute_path"
    assert live_status["last_command_boundary_violation_detected"] is True


def test_knowledge_strict_json_watchdog_kills_silent_retry(
    tmp_path: Path,
) -> None:
    callback = knowledge_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        silence_timeout_seconds=90,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=95.0,
            last_event_seconds_ago=91.0,
            event_count=2,
            command_execution_count=0,
            reasoning_item_count=0,
            last_command=None,
            last_command_repeat_count=0,
            has_final_agent_message=False,
            timeout_seconds=300,
        )
    )

    assert decision is not None
    assert decision.reason_code == "watchdog_no_activity_timeout"
    assert "90 seconds" in str(decision.reason_detail)
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["state"] == "watchdog_killed"
    assert live_status["reason_code"] == "watchdog_no_activity_timeout"
    assert live_status["silence_timeout_seconds"] == 90.0


def test_knowledge_strict_json_watchdog_kills_malformed_pseudo_final(
    tmp_path: Path,
) -> None:
    callback = knowledge_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=4.0,
            last_event_seconds_ago=0.1,
            event_count=3,
            command_execution_count=0,
            reasoning_item_count=0,
            last_command=None,
            last_command_repeat_count=0,
            has_final_agent_message=True,
            timeout_seconds=300,
            final_agent_message_state="malformed",
            final_agent_message_reason="final agent message did not start with `{`",
        )
    )

    assert decision is not None
    assert decision.reason_code == "watchdog_malformed_final_output"
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["state"] == "watchdog_killed"
    assert live_status["final_agent_message_state"] == "malformed"
    assert "did not start" in str(live_status["final_agent_message_reason"])


def test_knowledge_workspace_watchdog_stops_after_outputs_stabilize(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / "book.ks0000.nr.json"
    callback = knowledge_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
        allow_workspace_commands=True,
        expected_workspace_output_paths=[output_path],
    )
    output_path.write_text(
        json.dumps({"v": "2", "bid": "book.ks0000.nr", "r": []}),
        encoding="utf-8",
    )

    first = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.4,
            last_event_seconds_ago=0.0,
            event_count=4,
            command_execution_count=1,
            reasoning_item_count=0,
            last_command="/bin/bash -lc cat out/book.ks0000.nr.json",
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )
    first_live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    second = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.7,
            last_event_seconds_ago=0.0,
            event_count=5,
            command_execution_count=2,
            reasoning_item_count=0,
            last_command="/bin/bash -lc cat out/book.ks0000.nr.json",
            last_command_repeat_count=2,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert first is None
    assert second is not None
    assert second.reason_code == "workspace_outputs_stabilized"
    assert second.supervision_state == "completed"
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["state"] == "completed"
    assert live_status["reason_code"] == "workspace_outputs_stabilized"
    assert live_status["workspace_output_complete"] is True
    assert live_status["workspace_output_stable_passes"] >= 2
    assert live_status["last_command_boundary_violation_detected"] is False


def test_knowledge_workspace_watchdog_completes_only_after_live_task_validation(
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    task_id = "book.ks0000.nr.task-001"
    input_payload = {
        "v": "2",
        "bid": task_id,
        "c": [
            {
                "cid": "chunk-001",
                "b": [
                    {
                        "i": 0,
                        "t": "Use low heat to keep the milk from curdling.",
                    }
                ],
            }
        ],
    }
    (in_dir / f"{task_id}.json").write_text(
        json.dumps(input_payload),
        encoding="utf-8",
    )
    (tmp_path / "assigned_tasks.json").write_text(
        json.dumps(
            [
                {
                    "task_id": task_id,
                    "parent_shard_id": "book.ks0000.nr",
                    "owned_ids": ["chunk-001"],
                    "metadata": {
                        "input_path": f"in/{task_id}.json",
                        "hint_path": f"hints/{task_id}.md",
                        "result_path": f"out/{task_id}.json",
                        "task_sequence": 1,
                        "task_total": 1,
                        "workspace_processing_contract": "ordered_task_queue_v1",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    (out_dir / f"{task_id}.json").write_text(
        json.dumps(
            _semantic_packet_output(
                packet_id=task_id,
                chunk_id="chunk-001",
                block_indices=[0],
                snippet_body="Use low heat to keep milk from curdling.",
                evidence_quote="Use low heat to keep the milk from curdling.",
            )
        ),
        encoding="utf-8",
    )
    controller = knowledge_module._KnowledgeWorkspaceTaskQueueController(  # noqa: SLF001
        worker_root=tmp_path,
        task_entries=(
            TaskManifestEntryV1(
                task_id=task_id,
                task_kind="knowledge_review_chunk_packet",
                parent_shard_id="book.ks0000.nr",
                owned_ids=("chunk-001",),
                input_payload=input_payload,
                metadata={
                    "input_path": f"in/{task_id}.json",
                    "hint_path": f"hints/{task_id}.md",
                    "result_path": f"out/{task_id}.json",
                    "task_sequence": 1,
                    "task_total": 1,
                    "workspace_processing_contract": "ordered_task_queue_v1",
                },
            ),
        ),
    )
    callback = knowledge_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
        allow_workspace_commands=True,
        expected_workspace_output_paths=[out_dir / f"{task_id}.json"],
        task_queue_controller=controller,
    )

    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.4,
            last_event_seconds_ago=0.0,
            event_count=4,
            command_execution_count=1,
            reasoning_item_count=0,
            last_command="/bin/bash -lc python3 tools/knowledge_worker.py install-current",
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is not None
    assert decision.reason_code == "workspace_validated_task_queue_completed"
    assert decision.supervision_state == "completed"
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["state"] == "completed"
    assert live_status["queue_complete"] is True
    assert live_status["queue_validated_task_count"] == 1
    assert live_status["current_task_id"] is None
    assert not (tmp_path / "current_task.json").exists()


def test_knowledge_workspace_watchdog_gives_recent_output_progress_extra_budget(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / "book.ks0000.nr.task-001.json"
    missing_output_path = out_dir / "book.ks0000.nr.task-002.json"
    callback = knowledge_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
        allow_workspace_commands=True,
        expected_workspace_output_paths=[output_path, missing_output_path],
    )
    output_path.write_text(
        json.dumps({"packet_id": "book.ks0000.nr.task-001", "chunk_results": []}),
        encoding="utf-8",
    )

    first = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.4,
            last_event_seconds_ago=0.0,
            event_count=4,
            command_execution_count=250,
            reasoning_item_count=0,
            last_command="/bin/bash -lc cat current_task.json",
            last_command_repeat_count=4,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )
    first_live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    second = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.7,
            last_event_seconds_ago=0.0,
            event_count=5,
            command_execution_count=305,
            reasoning_item_count=0,
            last_command="/bin/bash -lc cat current_task.json",
            last_command_repeat_count=20,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )
    second_live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    third = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=1.0,
            last_event_seconds_ago=0.0,
            event_count=6,
            command_execution_count=406,
            reasoning_item_count=0,
            last_command="/bin/bash -lc cat current_task.json",
            last_command_repeat_count=32,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert first is None
    assert second is None
    assert third is not None
    assert third.reason_code == "watchdog_command_loop_without_output"
    assert first_live_status["workspace_output_progress_observed"] is True
    assert first_live_status["workspace_recent_output_progress"] is True
    assert second_live_status["workspace_recent_output_progress"] is False


def test_finalize_live_status_normalizes_completed_reason_code(tmp_path: Path) -> None:
    live_status_path = tmp_path / "live_status.json"
    knowledge_module._finalize_live_status(  # noqa: SLF001
        live_status_path,
        run_result=CodexExecRunResult(
            command=["codex", "exec"],
            subprocess_exit_code=0,
            output_schema_path=None,
            prompt_text="knowledge worker prompt",
            response_text="not json",
            turn_failed_message=None,
            duration_ms=125,
            started_at_utc="2026-03-20T15:26:25Z",
            finished_at_utc="2026-03-20T15:26:26Z",
            supervision_state="completed",
            supervision_reason_code=None,
            supervision_reason_detail=None,
            supervision_retryable=False,
        ),
        watchdog_policy="workspace_worker_v1",
    )

    live_status = json.loads(live_status_path.read_text(encoding="utf-8"))
    assert live_status["state"] == "completed"
    assert (
        live_status["reason_code"]
        == "process_exited_without_watchdog_intervention"
    )
    assert "without watchdog intervention" in str(live_status["reason_detail"])
    assert live_status["final_agent_message_state"] == "malformed"


def test_evaluate_knowledge_response_accepts_semantic_packet_with_trailing_eof() -> None:
    payload, validation_errors, validation_metadata, proposal_status = (
        knowledge_module._evaluate_knowledge_response(  # noqa: SLF001
            shard=ShardManifestEntryV1(
                shard_id="book.ks0000.nr.task-001",
                owned_ids=("book.c0000.nr",),
                metadata={
                    "owned_block_indices": [4],
                    "ordered_chunk_ids": ["book.c0000.nr"],
                    "chunk_block_indices_by_id": {"book.c0000.nr": [4]},
                },
            ),
            response_text=(
                json.dumps(
                    _semantic_packet_output(
                        packet_id="book.ks0000.nr.task-001",
                        chunk_id="book.c0000.nr",
                        block_indices=[4],
                    ),
                    sort_keys=True,
                )
                + "\nEOF\n"
            ),
        )
    )

    assert proposal_status == "validated"
    assert validation_errors == ()
    assert validation_metadata["response_trailing_eof_trimmed"] is True
    assert validation_metadata["worker_output_contract"] == "semantic_packet_result_v1"
    assert payload == {
        "v": "2",
        "bid": "book.ks0000.nr.task-001",
        "r": [
            {
                "cid": "book.c0000.nr",
                "u": True,
                "d": [{"i": 4, "c": "knowledge", "rc": "knowledge"}],
                "s": [
                    {
                        "b": "Fake knowledge snippet.",
                        "e": [{"i": 4, "q": "Fake knowledge snippet."}],
                    }
                ],
            }
        ],
    }


def test_knowledge_workspace_task_runtime_entries_add_ordered_queue_metadata() -> None:
    shard = ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.c0000.nr", "book.c0001.nr"),
        input_payload={
            "v": "2",
            "bid": "book.ks0000.nr",
            "c": [
                {"cid": "book.c0000.nr", "b": [{"i": 4, "t": "Heat the oil."}]},
                {"cid": "book.c0001.nr", "b": [{"i": 5, "t": "Whisk in the stock."}]},
            ],
        },
        metadata={
            "ordered_chunk_ids": ["book.c0000.nr", "book.c0001.nr"],
            "chunk_block_indices_by_id": {
                "book.c0000.nr": [4],
                "book.c0001.nr": [5],
            },
            "owned_block_indices": [4, 5],
        },
    )

    task_plans = knowledge_module._build_knowledge_task_plans(shard)  # noqa: SLF001
    runtime_entries = knowledge_module._build_knowledge_workspace_task_runtime_entries(  # noqa: SLF001
        task_plans
    )

    assert [entry.task_id for entry in runtime_entries] == [
        "book.ks0000.nr.task-001",
        "book.ks0000.nr.task-002",
    ]
    first_metadata = dict(runtime_entries[0].metadata or {})
    second_metadata = dict(runtime_entries[1].metadata or {})
    assert first_metadata["input_path"] == "in/book.ks0000.nr.task-001.json"
    assert first_metadata["hint_path"] == "hints/book.ks0000.nr.task-001.md"
    assert first_metadata["result_path"] == "out/book.ks0000.nr.task-001.json"
    assert first_metadata["lease_sequence"] == 1
    assert first_metadata["lease_total"] == 2
    assert first_metadata["workspace_processing_contract"] == "ordered_task_queue_v1"
    assert second_metadata["input_path"] == "in/book.ks0000.nr.task-002.json"
    assert second_metadata["task_sequence"] == 2
    assert second_metadata["task_total"] == 2


def test_evaluate_knowledge_response_salvages_shell_wrapper_noise_after_json_object() -> None:
    payload, validation_errors, validation_metadata, proposal_status = (
        knowledge_module._evaluate_knowledge_response(  # noqa: SLF001
            shard=ShardManifestEntryV1(
                shard_id="book.ks0000.nr.task-001",
                owned_ids=("book.c0000.nr",),
                metadata={
                    "owned_block_indices": [4],
                    "ordered_chunk_ids": ["book.c0000.nr"],
                    "chunk_block_indices_by_id": {"book.c0000.nr": [4]},
                },
            ),
            response_text=(
                json.dumps(
                    _semantic_packet_output(
                        packet_id="book.ks0000.nr.task-001",
                        chunk_id="book.c0000.nr",
                        block_indices=[4],
                    ),
                    sort_keys=True,
                )
                + "\n$ exit 0\n"
            ),
        )
    )

    assert proposal_status == "validated"
    assert validation_errors == ()
    assert validation_metadata["response_shell_wrapper_noise_trimmed"] is True
    assert validation_metadata["response_shell_wrapper_noise_preview"] == "$ exit 0"
    assert payload is not None


def test_knowledge_recovery_governor_marks_poisoned_workers_and_skips_followups() -> None:
    governor = knowledge_module._KnowledgeRecoveryGovernor()  # noqa: SLF001

    assert governor.observe_main_failure(  # noqa: SLF001
        worker_id="worker-001",
        failure_signature="invalid_json",
    ) is None
    poisoned = governor.observe_main_failure(  # noqa: SLF001
        worker_id="worker-001",
        failure_signature="invalid_json",
    )

    assert poisoned == {
        "reason_code": "poisoned_worker_uniform_malformed_outputs",
        "reason_detail": "worker repeatedly produced malformed or schema-invalid packet outputs",
    }
    repair_decision = governor.allow_followup(  # noqa: SLF001
        kind="repair",
        worker_id="worker-001",
        failure_signature="invalid_json",
    )

    assert repair_decision.allowed is False
    assert repair_decision.reason_code == "repair_skipped_poisoned_worker"
    assert "malformed" in str(repair_decision.reason_detail)


def test_knowledge_recovery_governor_opens_repair_circuit_breaker_after_repeated_failures() -> None:
    governor = knowledge_module._KnowledgeRecoveryGovernor()  # noqa: SLF001

    for _ in range(3):
        governor.record_followup_outcome(  # noqa: SLF001
            kind="repair",
            failure_signature="coverage_mismatch",
            recovered=False,
        )

    decision = governor.allow_followup(  # noqa: SLF001
        kind="repair",
        worker_id="worker-001",
        failure_signature="coverage_mismatch",
        near_miss=True,
    )

    assert decision.allowed is False
    assert decision.reason_code == "repair_skipped_circuit_breaker"
    assert "bounded recovery circuit breaker opened" in str(decision.reason_detail)


def test_knowledge_recovery_governor_does_not_poison_snippet_copy_only_failures() -> None:
    governor = knowledge_module._KnowledgeRecoveryGovernor()  # noqa: SLF001

    assert governor.observe_main_failure(  # noqa: SLF001
        worker_id="worker-001",
        failure_signature="snippet_copy_only",
    ) is None
    assert governor.observe_main_failure(  # noqa: SLF001
        worker_id="worker-001",
        failure_signature="snippet_copy_only",
    ) is None

    repair_decision = governor.allow_followup(  # noqa: SLF001
        kind="repair",
        worker_id="worker-001",
        failure_signature="snippet_copy_only",
        near_miss=True,
    )

    assert repair_decision.allowed is True


def test_knowledge_orchestrator_writes_manifest_and_artifacts(tmp_path: Path) -> None:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_workspace_root": str(workspace_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
            "codex_farm_knowledge_context_blocks": 1,
            "codex_farm_failure_mode": "fail",
        }
    )

    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        nonRecipeBlocks=[
            {"index": 0, "text": "Preface"},
            {"index": 4, "text": "Technique: Whisk constantly."},
        ],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Preface"},
                        {"index": 1, "text": "Toast"},
                        {"index": 2, "text": "1 slice bread"},
                        {"index": 3, "text": "Toast the bread."},
                        {"index": 4, "text": "Technique: Whisk constantly."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    runner = FakeCodexExecRunner(
        output_builder=lambda payload: build_structural_pipeline_output(
            "recipe.knowledge.compact.v1",
            dict(payload or {}),
        )
    )
    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.other.0.1",
                    category="other",
                    block_start_index=0,
                    block_end_index=1,
                    block_indices=[0],
                    block_ids=["b0"],
                ),
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                ),
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            other_spans=[
                NonRecipeSpan(
                    span_id="nr.other.0.1",
                    category="other",
                    block_start_index=0,
                    block_end_index=1,
                    block_indices=[0],
                    block_ids=["b0"],
                )
            ],
            block_category_by_index={0: "other", 4: "knowledge"},
        ),
        recipe_spans=[
            RecipeSpan(
                span_id="recipe.0",
                start_block_index=1,
                end_block_index=4,
                block_indices=[1, 2, 3],
                source_block_ids=["b1", "b2", "b3"],
            )
        ],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert apply_result.llm_report["enabled"] is True
    assert "output_schema_path" in apply_result.llm_report
    assert "process_run" in apply_result.llm_report
    assert apply_result.llm_report["process_run"]["pipeline_id"] == "recipe.knowledge.compact.v1"
    assert apply_result.llm_report["process_run"]["runtime_mode"] == "direct_codex_exec_v1"
    assert apply_result.llm_report["process_run"]["telemetry"]["summary"]["call_count"] > 0
    assert apply_result.llm_report["phase_worker_runtime"]["shard_count"] > 0
    assert apply_result.llm_report["input_mode"] == "stage7_seed_nonrecipe_spans"
    assert apply_result.llm_report["review_summary"]["seed_nonrecipe_span_count"] == 2
    assert apply_result.llm_report["review_summary"]["reviewed_shard_count"] >= 1
    assert apply_result.llm_report["review_summary"]["reviewed_shards_with_useful_chunks"] >= 1
    assert apply_result.llm_report["review_status"] == "complete"
    assert apply_result.llm_report["review_summary"]["promoted_snippet_count"] >= 1
    assert apply_result.refined_stage_result.block_category_by_index[4] == "knowledge"
    assert apply_result.manifest_path.exists()
    manifest = json.loads(apply_result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["paths"]["seed_nonrecipe_spans_path"].endswith("08_nonrecipe_spans.json")
    assert manifest["paths"]["final_knowledge_outputs_path"].endswith("09_knowledge_outputs.json")
    assert manifest["counts"]["shards_written"] > 0
    assert manifest["counts"]["seed_nonrecipe_span_count"] == 2
    assert manifest["counts"]["chunks_built_before_pruning"] >= manifest["counts"]["chunks_written"]
    assert manifest["counts"]["chunks_written"] >= manifest["counts"]["shards_written"]
    assert manifest["stage_status"] == "completed"
    assert manifest["review_summary"]["promoted_snippet_count"] >= 1

    knowledge_dir = run_root / "knowledge" / "book"
    assert (knowledge_dir / "snippets.jsonl").exists()
    assert (knowledge_dir / "knowledge.md").exists()
    assert "Fake knowledge snippet." in (knowledge_dir / "snippets.jsonl").read_text(
        encoding="utf-8"
    )
    assert "Fake knowledge snippet." in (knowledge_dir / "knowledge.md").read_text(
        encoding="utf-8"
    )
    phase_dir = run_root / "raw" / "llm" / "book" / "knowledge"
    assert (phase_dir / "phase_manifest.json").exists()
    assert (phase_dir / "shard_manifest.jsonl").exists()
    assert (phase_dir / "task_manifest.jsonl").exists()
    assert (phase_dir / "worker_assignments.json").exists()
    task_manifest = [
        json.loads(line)
        for line in (phase_dir / "task_manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert task_manifest
    assert all(row["task_id"] == row["parent_shard_id"] for row in task_manifest)
    worker_root = phase_dir / "workers" / "worker-001"
    worker_prompt = (worker_root / "prompt.txt").read_text(encoding="utf-8")
    assert "worker_manifest.json" in worker_prompt
    assert "`CURRENT_TASK.md`" in worker_prompt
    assert "`current_task.json`" in worker_prompt
    assert "`CURRENT_TASK_FEEDBACK.md`" in worker_prompt
    assert "OUTPUT_CONTRACT.md" in worker_prompt
    assert "tools/knowledge_worker.py complete-current" in worker_prompt
    assert "tools/knowledge_worker.py check-current" in worker_prompt
    assert "tools/knowledge_worker.py install-current" in worker_prompt
    assert "tools/knowledge_worker.py explain-failure" in worker_prompt
    assert "`assigned_tasks.json`" in worker_prompt
    assert "authoritative current-task surface" in worker_prompt
    assert "`metadata.input_path`, `metadata.hint_path`, and `metadata.result_path`" in worker_prompt
    assert "A task is not finished until `check-current` prints `OK ...`." in worker_prompt
    assert "Workspace-local shell commands are allowed when they materially help" in worker_prompt
    assert "Stay inside this workspace" in worker_prompt
    assert "repo-written helper under `tools/`" in worker_prompt
    assert "Top level keys: `packet_id`, `chunk_results`." in worker_prompt
    assert (
        "Each result row uses `chunk_id`, `is_useful`, `block_decisions`, `snippets`, and optional `reason_code`."
        in worker_prompt
    )
    assert "`category` must be exactly one of `knowledge`, `other`." in worker_prompt
    assert (
        "`reviewer_category` may be omitted or must be one of `knowledge`, "
        "`chapter_taxonomy`, `decorative_heading`, `front_matter`, `toc_navigation`, "
        "`endorsement_or_marketing`, `memoir_or_scene_setting`, "
        "`reference_back_matter`, `other`."
        in worker_prompt
    )
    assert (
        "Never invent category labels such as `content`, `noise`, or `heading`"
        in worker_prompt
    )
    assert "short grounded extraction, not a whole-block dump, full-chunk echo" in worker_prompt
    assert "Good snippet pattern: body `Use low heat to prevent curdling.`" in worker_prompt
    assert "Bad snippet pattern: a body that restates nearly every sentence" in worker_prompt
    assert "The repo will write the final canonical `v` / `bid` / `r` packet artifact" in worker_prompt
    assert "Do not work ahead on later tasks" in worker_prompt
    assert "Do not invent your own batch scheduler" in worker_prompt
    assert "repo-written `check-current` loop" in worker_prompt
    assert "Assigned packet ids in required processing order:" not in worker_prompt
    worker_manifest = json.loads(
        (worker_root / "worker_manifest.json").read_text(encoding="utf-8")
    )
    assert worker_manifest["entry_files"] == [
        "worker_manifest.json",
        "current_task.json",
        "CURRENT_TASK.md",
        "CURRENT_TASK_FEEDBACK.md",
        "assigned_shards.json",
        "assigned_tasks.json",
    ]
    assert worker_manifest["hints_dir"] == "hints"
    assert worker_manifest["current_task_file"] == "current_task.json"
    assert worker_manifest["current_task_brief_file"] == "CURRENT_TASK.md"
    assert worker_manifest["current_task_feedback_file"] == "CURRENT_TASK_FEEDBACK.md"
    assert worker_manifest["output_contract_file"] == "OUTPUT_CONTRACT.md"
    assert worker_manifest["examples_dir"] == "examples"
    assert worker_manifest["tools_dir"] == "tools"
    assert worker_manifest["current_packet_file"] is None
    assert worker_manifest["current_hint_file"] is None
    assert worker_manifest["current_result_path_file"] is None
    assert worker_manifest["packet_lease_status_file"] is None
    assert worker_manifest["scratch_dir"] == "scratch"
    assert "valid_semantic_packet.json" in worker_manifest["mirrored_example_files"]
    assert "invalid_echo_packet.json" in worker_manifest["mirrored_example_files"]
    assert worker_manifest["mirrored_tool_files"] == ["knowledge_worker.py"]
    output_contract = (worker_root / "OUTPUT_CONTRACT.md").read_text(encoding="utf-8")
    assert "Knowledge Workspace Output Contract" in output_contract
    assert "Good snippet" in output_contract
    assert "Intentionally invalid echo example" in output_contract
    assert "A task is not finished until `check` passes." in output_contract
    assert (worker_root / "examples" / "valid_semantic_packet.json").exists()
    assert (worker_root / "examples" / "invalid_echo_packet.json").exists()
    assert (worker_root / "tools" / "knowledge_worker.py").exists()
    assert (worker_root / "hints").exists()
    assert (worker_root / "scratch").exists()
    assert (worker_root / "CURRENT_TASK.md").exists()
    assert (worker_root / "CURRENT_TASK_FEEDBACK.md").exists()
    assigned_tasks = json.loads((worker_root / "assigned_tasks.json").read_text(encoding="utf-8"))
    assert assigned_tasks
    assert "input_payload" not in assigned_tasks[0]
    assert not (worker_root / "current_task.json").exists()
    first_task_metadata = dict(assigned_tasks[0]["metadata"])
    assert first_task_metadata["input_path"].startswith("in/")
    assert first_task_metadata["hint_path"].startswith("hints/")
    assert first_task_metadata["result_path"].startswith("out/")
    assert first_task_metadata["workspace_processing_contract"] == "ordered_task_queue_v1"
    hint_text = (
        worker_root / first_task_metadata["hint_path"]
    ).read_text(encoding="utf-8")
    assert "Good snippet body: a shorter grounded claim." in hint_text
    assert "check-current" in hint_text
    valid_example_payload = json.loads(
        (worker_root / "examples" / "valid_semantic_packet.json").read_text(encoding="utf-8")
    )
    valid_example_row = valid_example_payload["chunk_results"][0]
    valid_example_snippet = valid_example_row["snippets"][0]
    assert valid_example_snippet["body"] != valid_example_snippet["evidence"][0]["quote"]
    invalid_example_payload = json.loads(
        (worker_root / "examples" / "invalid_echo_packet.json").read_text(encoding="utf-8")
    )
    invalid_example_row = invalid_example_payload["chunk_results"][0]
    invalid_surface = " ".join(
        evidence["quote"] for evidence in invalid_example_row["snippets"][0]["evidence"]
    )
    assert invalid_example_row["snippets"][0]["body"] == invalid_surface
    assert "No current task is active" in (worker_root / "CURRENT_TASK.md").read_text(encoding="utf-8")
    assert "queue is complete" in (
        worker_root / "CURRENT_TASK_FEEDBACK.md"
    ).read_text(encoding="utf-8").lower()


def test_knowledge_workspace_helper_cli_behaves_like_the_paved_road(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "codex_farm_cmd": "codex exec",
        }
    )
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: _semantic_packet_output(
            packet_id=str((payload or {}).get("bid") or ""),
            chunk_id=str(((payload or {}).get("c") or [{}])[0].get("cid") or ""),
            block_indices=[
                int(block.get("i"))
                for block in ((((payload or {}).get("c") or [{}])[0].get("b") or []))
                if isinstance(block, dict) and block.get("i") is not None
            ],
        )
    )

    run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=ConversionResult(
            recipes=[],
            tips=[],
            tipCandidates=[],
            topicCandidates=[],
            nonRecipeBlocks=[
                {"index": 0, "text": "Use low heat to keep the milk from curdling."},
                {"index": 1, "text": "Stir constantly so the sauce stays smooth and glossy."},
            ],
            rawArtifacts=[
                RawArtifact(
                    importer="text",
                    sourceHash="hash123",
                    locationId="full_text",
                    extension="json",
                    content={
                        "blocks": [
                            {
                                "index": 0,
                                "text": "Use low heat to keep the milk from curdling.",
                            },
                            {
                                "index": 1,
                                "text": "Stir constantly so the sauce stays smooth and glossy.",
                            },
                        ]
                    },
                    metadata={},
                )
            ],
            report=ConversionReport(),
            workbook="book",
            workbookPath=str(source),
        ),
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.2",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=2,
                    block_indices=[0, 1],
                    block_ids=["b0", "b1"],
                )
            ],
            seed_nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.2",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=2,
                    block_indices=[0, 1],
                    block_ids=["b0", "b1"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.2",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=2,
                    block_indices=[0, 1],
                    block_ids=["b0", "b1"],
                )
            ],
            other_spans=[],
            block_category_by_index={0: "knowledge", 1: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
        full_blocks=[
            {"index": 0, "id": "b0", "text": "Use low heat to keep the milk from curdling."},
            {"index": 1, "id": "b1", "text": "Stir constantly so the sauce stays smooth and glossy."},
        ],
    )

    worker_root = run_root / "raw" / "llm" / "book" / "knowledge" / "workers" / "worker-001"
    tool_path = worker_root / "tools" / "knowledge_worker.py"
    assigned_tasks = json.loads((worker_root / "assigned_tasks.json").read_text(encoding="utf-8"))
    task_id = assigned_tasks[0]["task_id"]
    result_path = worker_root / assigned_tasks[0]["metadata"]["result_path"]
    knowledge_module.write_current_task_sidecars(  # noqa: SLF001
        workspace_root=worker_root,
        task_row=assigned_tasks[0],
        current_draft_path=worker_root / "scratch" / "current_task.json",
    )
    if result_path.exists():
        result_path.unlink()

    overview = subprocess.run(
        [sys.executable, str(tool_path), "overview"],
        cwd=worker_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "current_task:" in overview.stdout
    assert task_id in overview.stdout

    current = subprocess.run(
        [sys.executable, str(tool_path), "current"],
        cwd=worker_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "# Current Knowledge Task" in current.stdout
    assert f"Task id: `{task_id}`" in current.stdout

    explain_failure = subprocess.run(
        [sys.executable, str(tool_path), "explain-failure"],
        cwd=worker_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "# Current Task Feedback" in explain_failure.stdout

    show = subprocess.run(
        [sys.executable, str(tool_path), "show", task_id],
        cwd=worker_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert f"task_id: {task_id}" in show.stdout
    assert "input_path:" in show.stdout

    scaffold_path = worker_root / "scratch" / "current_task.json"
    if scaffold_path.exists():
        scaffold_path.unlink()
    scaffold = subprocess.run(
        [
            sys.executable,
            str(tool_path),
            "complete-current",
        ],
        cwd=worker_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "wrote current scaffold" in scaffold.stdout
    scaffold_payload = json.loads(scaffold_path.read_text(encoding="utf-8"))
    assert scaffold_payload["packet_id"] == task_id
    assert scaffold_payload["chunk_results"]

    valid_check = subprocess.run(
        [
            sys.executable,
            str(tool_path),
            "check-current",
            "examples/valid_semantic_packet.json",
        ],
        cwd=worker_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert f"OK {task_id}" in valid_check.stdout

    invalid_check = subprocess.run(
        [
            sys.executable,
            str(tool_path),
            "check-current",
            "examples/invalid_echo_packet.json",
        ],
        cwd=worker_root,
        capture_output=True,
        text=True,
    )
    assert invalid_check.returncode == 1
    assert "semantic_snippet_echoes_full_chunk" in invalid_check.stderr
    assert "copied evidence" in invalid_check.stderr
    assert "Run `check` again" in invalid_check.stderr
    assert "Validation status: FAILED." in (
        worker_root / "CURRENT_TASK_FEEDBACK.md"
    ).read_text(encoding="utf-8")

    invalid_install = subprocess.run(
        [
            sys.executable,
            str(tool_path),
            "install-current",
            "examples/invalid_echo_packet.json",
        ],
        cwd=worker_root,
        capture_output=True,
        text=True,
    )
    assert invalid_install.returncode == 1
    assert "copied evidence" in invalid_install.stderr

    install = subprocess.run(
        [
            sys.executable,
            str(tool_path),
            "install-current",
            "examples/valid_semantic_packet.json",
        ],
        cwd=worker_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "installed valid_semantic_packet.json" in install.stdout
    installed_payload = json.loads(result_path.read_text(encoding="utf-8"))
    example_payload = json.loads(
        (worker_root / "examples" / "valid_semantic_packet.json").read_text(encoding="utf-8")
    )
    assert installed_payload == example_payload
    assert "Validation status: OK." in (
        worker_root / "CURRENT_TASK_FEEDBACK.md"
    ).read_text(encoding="utf-8")


def test_knowledge_orchestrator_writes_interrupt_status_before_reraising(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 1,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )

    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        nonRecipeBlocks=[{"index": 4, "text": "Technique: Whisk constantly."}],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={"blocks": [{"index": 4, "text": "Technique: Whisk constantly."}]},
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    def _interrupting_worker_run(**kwargs: object) -> tuple[object, list[object], dict[str, object]]:
        run_root = Path(str(kwargs["run_root"]))
        worker_root = run_root / "workers" / "worker-001"
        worker_root.mkdir(parents=True, exist_ok=True)
        (run_root / "worker_assignments.json").write_text("[]\n", encoding="utf-8")
        (worker_root / "live_status.json").write_text(
            json.dumps(
                {
                    "state": "watchdog_killed",
                    "reason_code": "watchdog_malformed_final_output",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        raise KeyboardInterrupt()

    monkeypatch.setattr(
        knowledge_module,
        "_run_direct_knowledge_workers_v1",
        _interrupting_worker_run,
    )

    with pytest.raises(KeyboardInterrupt):
        run_codex_farm_nonrecipe_knowledge_review(
            conversion_result=result,
            nonrecipe_stage_result=NonRecipeStageResult(
                nonrecipe_spans=[
                    NonRecipeSpan(
                        span_id="nr.knowledge.4.5",
                        category="knowledge",
                        block_start_index=4,
                        block_end_index=5,
                        block_indices=[4],
                        block_ids=["b4"],
                    )
                ],
                knowledge_spans=[
                    NonRecipeSpan(
                        span_id="nr.knowledge.4.5",
                        category="knowledge",
                        block_start_index=4,
                        block_end_index=5,
                        block_indices=[4],
                        block_ids=["b4"],
                    )
                ],
                other_spans=[],
                block_category_by_index={4: "knowledge"},
            ),
            recipe_spans=[],
            run_settings=settings,
            run_root=run_root,
            workbook_slug="book",
            runner=FakeCodexExecRunner(output_builder=lambda payload: dict(payload or {})),
        )

    stage_status_path = run_root / "raw" / "llm" / "book" / "knowledge" / "stage_status.json"
    stage_status = json.loads(stage_status_path.read_text(encoding="utf-8"))
    assert stage_status["stage_state"] == "interrupted"
    assert stage_status["termination_cause"] == "operator_interrupt"
    assert stage_status["finalization_completeness"] == "interrupted_before_finalization"
    assert stage_status["artifact_states"]["worker_assignments.json"] == "present"
    assert stage_status["artifact_states"]["phase_manifest.json"] == "skipped_due_to_interrupt"
    assert stage_status["artifact_states"]["proposals/*"] == "skipped_due_to_interrupt"
    assert stage_status["pre_kill_failure_counts"]["worker_terminal_states"] == {
        "watchdog_killed": 1
    }
    assert stage_status["pre_kill_failure_counts"]["worker_reason_codes"] == {
        "watchdog_malformed_final_output": 1
    }


def test_mark_running_knowledge_status_files_interrupted_cancels_followups_and_tasks(
    tmp_path: Path,
) -> None:
    stage_root = tmp_path / "knowledge"
    shard_root = stage_root / "workers" / "worker-001" / "shards" / "book.ks0000.nr"
    retry_root = shard_root / "watchdog_retry"
    for path in (
        stage_root / "workers" / "worker-001" / "live_status.json",
        retry_root / "live_status.json",
        shard_root / "repair_live_status.json",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"state": "running"}, sort_keys=True), encoding="utf-8")

    task_status_path = stage_root / "task_status.jsonl"
    rows_by_task_id = {
        "book.ks0000.nr.t000": {
            "schema_version": "knowledge_task_status.v1",
            "task_id": "book.ks0000.nr.t000",
            "state": "pending",
            "terminal": False,
            "active_attempt_type": "repair",
            "last_attempt_type": None,
            "attempt_state": "running",
            "metadata": {},
        },
        "book.ks0000.nr.t001": {
            "schema_version": "knowledge_task_status.v1",
            "task_id": "book.ks0000.nr.t001",
            "state": "validated",
            "terminal": True,
            "active_attempt_type": None,
            "last_attempt_type": "main_worker",
            "attempt_state": "completed",
            "metadata": {},
        },
    }
    knowledge_module._KnowledgeTaskStatusTracker(  # noqa: SLF001
        path=task_status_path,
        rows_by_task_id=rows_by_task_id,
    )

    knowledge_module._mark_running_knowledge_status_files_interrupted(stage_root)  # noqa: SLF001
    tracker = knowledge_module._KnowledgeTaskStatusTracker(  # noqa: SLF001
        path=task_status_path,
        rows_by_task_id=rows_by_task_id,
    )
    tracker.mark_interrupted()

    repair_status = json.loads((shard_root / "repair_status.json").read_text(encoding="utf-8"))
    retry_status = json.loads((retry_root / "status.json").read_text(encoding="utf-8"))
    task_rows = [
        json.loads(line)
        for line in task_status_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    task_rows_by_id = {row["task_id"]: row for row in task_rows}

    assert json.loads((shard_root / "repair_live_status.json").read_text(encoding="utf-8"))["state"] == (
        "cancelled_stage_interrupt"
    )
    assert json.loads((retry_root / "live_status.json").read_text(encoding="utf-8"))["state"] == (
        "cancelled_stage_interrupt"
    )
    assert repair_status["status"] == "cancelled_stage_interrupt"
    assert repair_status["state"] == "cancelled_stage_interrupt"
    assert repair_status["reason_code"] == "cancelled_stage_interrupt"
    assert retry_status["status"] == "cancelled_stage_interrupt"
    assert retry_status["state"] == "cancelled_stage_interrupt"
    assert retry_status["reason_code"] == "cancelled_stage_interrupt"
    assert task_rows_by_id["book.ks0000.nr.t000"]["state"] == "cancelled_due_to_interrupt"
    assert task_rows_by_id["book.ks0000.nr.t000"]["attempt_state"] == "cancelled"
    assert (
        task_rows_by_id["book.ks0000.nr.t000"]["terminal_reason_code"]
        == "cancelled_stage_interrupt"
    )
    assert task_rows_by_id["book.ks0000.nr.t001"]["state"] == "validated"


def test_run_direct_knowledge_workers_writes_partial_runtime_artifacts_before_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "knowledge"
    shard = ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("chunk-1",),
        input_payload={"shard_id": "book.ks0000.nr", "c": []},
        input_text='{"shard_id":"book.ks0000.nr","c":[]}',
        metadata={},
    )

    def _interrupting_assignment(**kwargs):
        worker_root = Path(kwargs["assignment"].workspace_root)
        (worker_root / "live_status.json").parent.mkdir(parents=True, exist_ok=True)
        (worker_root / "live_status.json").write_text(
            json.dumps({"state": "running", "reason_code": None}, sort_keys=True),
            encoding="utf-8",
        )
        raise KeyboardInterrupt()

    monkeypatch.setattr(
        knowledge_module,
        "_run_direct_knowledge_worker_assignment_v1",
        _interrupting_assignment,
    )

    with pytest.raises(KeyboardInterrupt):
        _run_direct_knowledge_workers_v1(
            phase_key="nonrecipe_knowledge_review",
            pipeline_id="recipe.knowledge.compact.v1",
            run_root=run_root,
            shards=[shard],
            runner=FakeCodexExecRunner(output_builder=lambda payload: dict(payload or {})),
            worker_count=1,
            env={},
            model=None,
            reasoning_effort=None,
            output_schema_path=None,
            settings={},
            runtime_metadata={},
        )

    assert (run_root / "phase_manifest.json").exists()
    assert (run_root / "promotion_report.json").exists()
    assert (run_root / "telemetry.json").exists()
    assert (run_root / "failures.json").exists()
    assert (run_root / "task_status.jsonl").exists()

    telemetry = json.loads((run_root / "telemetry.json").read_text(encoding="utf-8"))
    promotion_report = json.loads((run_root / "promotion_report.json").read_text(encoding="utf-8"))
    task_rows = [
        json.loads(line)
        for line in (run_root / "task_status.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert telemetry["worker_count"] == 1
    assert promotion_report["validated_shards"] == 0
    assert task_rows[0]["state"] == "cancelled_due_to_interrupt"


def test_knowledge_orchestrator_repairs_near_miss_invalid_shards_once(
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 1,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )

    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        nonRecipeBlocks=[
            {"index": 4, "text": "Technique: Whisk constantly."},
        ],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 4, "text": "Technique: Whisk constantly."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    runner = FakeCodexExecRunner(
        output_builder=lambda payload: (
            {
                "v": "2",
                "bid": payload["shard_id"],
                "r": [
                    {
                        "cid": chunk_id,
                        "u": True,
                        "d": [{"i": 4, "c": "knowledge"}],
                        "s": [
                            {
                                "b": "Technique note: whisk constantly to keep the mixture smooth.",
                                "e": [{"i": 4, "q": "Technique: Whisk constantly."}],
                            }
                        ],
                    }
                    for chunk_id in payload.get("owned_ids", [])
                ],
            }
            if payload and payload.get("repair_mode") == "knowledge"
            else {"v": "2", "bid": payload["bid"], "r": []}
        )
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            other_spans=[],
            block_category_by_index={4: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    process_summary = apply_result.llm_report["process_run"]["telemetry"]["summary"]
    assert process_summary["call_count"] == 2
    assert process_summary["repaired_shard_count"] == 1
    assert process_summary["invalid_output_shard_count"] == 0
    assert process_summary["workspace_worker_session_count"] == 1
    assert process_summary["structured_followup_call_count"] == 1
    assert process_summary["prompt_input_mode_counts"] == {
        "inline_repair": 1,
        "workspace_worker": 1,
    }
    assert runner.calls[0]["mode"] == "workspace_worker"
    assert runner.calls[1]["mode"] == "structured_prompt"

    proposals_dir = (
        run_root / "raw" / "llm" / "book" / "knowledge" / "proposals"
    )
    proposal = json.loads((proposals_dir / "book.ks0000.nr.json").read_text(encoding="utf-8"))
    assert proposal["repair_attempted"] is True
    assert proposal["repair_status"] == "repaired"
    assert proposal["validation_errors"] == []

    repair_status_path = (
        run_root
        / "raw"
        / "llm"
        / "book"
        / "knowledge"
        / "workers"
        / "worker-001"
        / "shards"
        / "book.ks0000.nr"
        / "repair_status.json"
    )
    repair_status = json.loads(repair_status_path.read_text(encoding="utf-8"))
    assert repair_status["status"] == "repaired"
    assert "Authoritative shard input:" in runner.calls[1]["prompt_text"]
    assert "Missing owned chunk ids: book.c0000.nr" in runner.calls[1]["prompt_text"]
    assert "<BEGIN_INPUT_JSON>" in runner.calls[1]["prompt_text"]


def test_knowledge_orchestrator_repairs_snippet_copy_outputs_before_poison_skip(
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 1,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    source_text = (
        "Keep the sauce at a gentle simmer and stir constantly so the emulsion stays glossy, "
        "smooth, and cohesive instead of tightening, scorching, or breaking around the edges "
        "while the heat keeps rising under the pan."
    )

    def _snippet_payload(payload: object, *, snippet_body: str) -> dict[str, object]:
        packet = dict(payload or {})
        authoritative_input = dict(packet.get("authoritative_input") or packet)
        chunk = dict(((authoritative_input.get("c") or [{}])[0]))
        chunk_id = str(chunk.get("cid") or "")
        block_indices = [
            int(block.get("i"))
            for block in (chunk.get("b") or [])
            if isinstance(block, dict) and block.get("i") is not None
        ]
        return _semantic_packet_output(
            packet_id=str(packet.get("bid") or packet.get("shard_id") or ""),
            chunk_id=chunk_id,
            block_indices=block_indices,
            snippet_body=snippet_body,
            evidence_quote=source_text,
        )

    runner = FakeCodexExecRunner(
        output_builder=lambda payload: (
            _snippet_payload(
                payload,
                snippet_body="Simmer gently and stir constantly to keep the sauce smooth.",
            )
            if payload and payload.get("repair_mode") == "knowledge_snippet_only"
            else _snippet_payload(payload, snippet_body=source_text)
        )
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=ConversionResult(
            recipes=[],
            tips=[],
            tipCandidates=[],
            topicCandidates=[],
            nonRecipeBlocks=[{"index": 4, "text": source_text}],
            rawArtifacts=[
                RawArtifact(
                    importer="text",
                    sourceHash="hash123",
                    locationId="full_text",
                    extension="json",
                    content={"blocks": [{"index": 4, "text": source_text}]},
                    metadata={},
                )
            ],
            report=ConversionReport(),
            workbook="book",
            workbookPath="book.txt",
        ),
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            other_spans=[],
            block_category_by_index={4: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    process_summary = apply_result.llm_report["process_run"]["telemetry"]["summary"]
    assert process_summary["call_count"] == 2
    assert process_summary["repaired_shard_count"] == 1
    assert process_summary["prompt_input_mode_counts"] == {
        "inline_snippet_repair": 1,
        "workspace_worker": 1,
    }
    assert runner.calls[0]["mode"] == "workspace_worker"
    assert runner.calls[1]["mode"] == "structured_prompt"
    assert runner.calls[1]["input_payload"]["repair_mode"] == "knowledge_snippet_only"
    assert "Rewrite only `snippets[*].body`." in runner.calls[1]["prompt_text"]

    proposal = json.loads(
        (
            run_root / "raw" / "llm" / "book" / "knowledge" / "proposals" / "book.ks0000.nr.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal["repair_attempted"] is True
    assert proposal["repair_status"] == "repaired"
    assert proposal["repair_mode"] == "snippet_only"
    assert proposal["validation_errors"] == []

    repair_status = json.loads(
        (
            run_root
            / "raw"
            / "llm"
            / "book"
            / "knowledge"
            / "workers"
            / "worker-001"
            / "shards"
            / "book.ks0000.nr"
            / "repair_status.json"
        ).read_text(encoding="utf-8")
    )
    assert repair_status["status"] == "repaired"
    assert repair_status["repair_mode"] == "snippet_only"


def test_knowledge_orchestrator_hard_fails_when_snippet_only_repair_still_copies_source(
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 1,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    source_text = (
        "All salt comes from the ocean, be it the Atlantic or a long-forgotten inland sea, "
        "and careful cooks use it in layers so seasoning develops depth instead of landing "
        "all at once at the very end of cooking."
    )

    def _always_invalid(payload: object) -> dict[str, object]:
        packet = dict(payload or {})
        authoritative_input = dict(packet.get("authoritative_input") or packet)
        chunk = dict(((authoritative_input.get("c") or [{}])[0]))
        chunk_id = str(chunk.get("cid") or "")
        block_indices = [
            int(block.get("i"))
            for block in (chunk.get("b") or [])
            if isinstance(block, dict) and block.get("i") is not None
        ]
        return _semantic_packet_output(
            packet_id=str(packet.get("bid") or packet.get("shard_id") or ""),
            chunk_id=chunk_id,
            block_indices=block_indices,
            snippet_body=source_text,
            evidence_quote=source_text,
        )

    runner = FakeCodexExecRunner(output_builder=_always_invalid)

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=ConversionResult(
            recipes=[],
            tips=[],
            tipCandidates=[],
            topicCandidates=[],
            nonRecipeBlocks=[{"index": 4, "text": source_text}],
            rawArtifacts=[
                RawArtifact(
                    importer="text",
                    sourceHash="hash123",
                    locationId="full_text",
                    extension="json",
                    content={"blocks": [{"index": 4, "text": source_text}]},
                    metadata={},
                )
            ],
            report=ConversionReport(),
            workbook="book",
            workbookPath="book.txt",
        ),
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            other_spans=[],
            block_category_by_index={4: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    process_summary = apply_result.llm_report["process_run"]["telemetry"]["summary"]
    assert process_summary["call_count"] == 2
    assert process_summary["invalid_output_shard_count"] == 1
    assert process_summary["prompt_input_mode_counts"] == {
        "inline_snippet_repair": 1,
        "workspace_worker": 1,
    }

    proposal = json.loads(
        (
            run_root / "raw" / "llm" / "book" / "knowledge" / "proposals" / "book.ks0000.nr.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal["repair_attempted"] is True
    assert proposal["repair_status"] == "failed"
    assert proposal["repair_mode"] == "snippet_only"
    assert proposal["validation_errors"] == ["missing_owned_chunk_results"]
    assert proposal["validation_metadata"]["repair_validation_errors"] == [
        "semantic_snippet_echoes_full_chunk"
    ]

    task_rows = [
        json.loads(line)
        for line in (
            run_root / "raw" / "llm" / "book" / "knowledge" / "task_status.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert task_rows[0]["state"] == "repair_failed"
    assert task_rows[0]["terminal_reason_code"] == "semantic_snippet_echoes_full_chunk"


def test_pathological_knowledge_response_text_detects_giant_whitespace_run() -> None:
    response_text = (
        '{"v":"2","bid":"book.ks0000.nr","r":[{"cid":"book.c0000.nr","u":false,'
        '"d":[],"s":[{"b":"ok"'
        + (" " * 5000)
        + ',"e":[{"i":4,"q":"quote"}]}]}]}'
    )

    assert _is_pathological_knowledge_response_text(
        response_text,
        owned_chunk_count=2,
        returned_chunk_count=1,
    ) is True


def test_preflight_knowledge_shard_rejects_missing_model_facing_chunks() -> None:
    shard = ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.c0000.nr",),
        input_payload={"v": "2", "bid": "book.ks0000.nr", "c": []},
    )

    assert _preflight_knowledge_shard(shard) == {
        "reason_code": "preflight_invalid_shard_payload",
        "reason_detail": "knowledge shard has no model-facing chunks",
    }


def test_knowledge_watchdog_retry_uses_bounded_timeout(tmp_path: Path) -> None:
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: {
            "v": "2",
            "bid": str((payload or {}).get("bid") or "book.ks0000.nr"),
            "r": [],
        }
    )
    worker_root = tmp_path / "worker-001"
    worker_root.mkdir(parents=True, exist_ok=True)
    (worker_root / "shards" / "book.ks0000.nr" / "watchdog_retry").mkdir(
        parents=True,
        exist_ok=True,
    )
    shard = ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.c0000.nr",),
        input_payload={
            "v": "2",
            "bid": "book.ks0000.nr",
            "c": [{"cid": "book.c0000.nr", "b": [{"i": 0, "t": "Whisk constantly."}]}],
        },
    )

    knowledge_module._run_knowledge_watchdog_retry_attempt(  # noqa: SLF001
        runner=runner,
        worker_root=worker_root,
        shard=shard,
        env={},
        output_schema_path=tmp_path / "schema.json",
        model="gpt-5.1-codex-mini",
        reasoning_effort="medium",
        reason_code="watchdog_command_execution_forbidden",
        reason_detail="workspace worker stage attempted tool use",
        successful_examples=(),
        live_status_path=tmp_path / "live_status.json",
    )

    retry_call = runner.calls[-1]
    assert retry_call["mode"] == "structured_prompt"
    assert (
        retry_call["timeout_seconds"]
        == knowledge_module._KNOWLEDGE_WATCHDOG_RETRY_TIMEOUT_SECONDS  # noqa: SLF001
    )
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert (
        live_status["silence_timeout_seconds"]
        == knowledge_module._KNOWLEDGE_WATCHDOG_RETRY_SILENCE_TIMEOUT_SECONDS  # noqa: SLF001
    )


def test_knowledge_orchestrator_marks_watchdog_killed_shards_in_summary(
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 1,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )

    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        nonRecipeBlocks=[
            {"index": 4, "text": "Technique: Whisk constantly."},
        ],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 4, "text": "Technique: Whisk constantly."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    class _WatchdogRunner(FakeCodexExecRunner):
        def run_structured_prompt(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_structured_prompt(*args, **kwargs)
            supervision_callback = kwargs.get("supervision_callback")
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
                        timeout_seconds=kwargs.get("timeout_seconds"),
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
                supervision_retryable=True,
            )

        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            from cookimport.llm.codex_exec_runner import CodexExecRunResult

            supervision_callback = kwargs.get("supervision_callback")
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
                        timeout_seconds=kwargs.get("timeout_seconds"),
                    )
                )
            working_dir = Path(kwargs.get("working_dir"))
            self.calls.append(
                {
                    "mode": "workspace_worker",
                    "prompt_text": str(kwargs.get("prompt_text") or ""),
                    "input_payload": None,
                    "working_dir": str(working_dir),
                    "execution_working_dir": str(working_dir),
                    "output_schema_path": None,
                }
            )
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=None,
                prompt_text=str(kwargs.get("prompt_text") or ""),
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
                stderr_text=None,
                stdout_text=None,
                source_working_dir=str(working_dir),
                execution_working_dir=str(working_dir),
                execution_agents_path=None,
                duration_ms=100,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:00Z",
                supervision_state="watchdog_killed",
                supervision_reason_code="watchdog_command_execution_forbidden",
                supervision_reason_detail="strict JSON stage attempted tool use",
                supervision_retryable=True,
            )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            other_spans=[],
            block_category_by_index={4: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=_WatchdogRunner(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.compact.v1",
                dict(payload or {}),
            )
        ),
    )

    process_summary = apply_result.llm_report["process_run"]["telemetry"]["summary"]
    assert process_summary["watchdog_killed_shard_count"] == 1
    assert process_summary["workspace_worker_session_count"] == 1
    assert process_summary["structured_followup_call_count"] == 1
    assert process_summary["prompt_input_mode_counts"] == {
        "inline_watchdog_retry": 1,
        "workspace_worker": 1,
    }
    assert "watchdog_kills_detected" in process_summary["pathological_flags"]
    assert "command_execution_detected" in process_summary["pathological_flags"]

    status_path = (
        run_root
        / "raw"
        / "llm"
        / "book"
        / "knowledge"
        / "workers"
        / "worker-001"
        / "shards"
        / "book.ks0000.nr"
        / "status.json"
    )
    status_payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert status_payload["status"] == "invalid"
    assert status_payload["state"] == "watchdog_killed"
    assert status_payload["reason_code"] == "watchdog_command_execution_forbidden"

    live_status_path = status_path.with_name("live_status.json")
    live_status_payload = json.loads(live_status_path.read_text(encoding="utf-8"))
    assert live_status_payload["state"] == "watchdog_killed"
    assert live_status_payload["reason_code"] == "watchdog_command_execution_forbidden"
    assert live_status_payload["retryable"] is True
    assert apply_result.llm_report["review_status"] == "unreviewed"
    assert apply_result.llm_report["counts"]["unreviewed_shard_count"] == 1
    assert apply_result.llm_report["counts"]["invalid_shards"] == 1
    assert apply_result.llm_report["counts"]["missing_output_shards"] == 0


def test_knowledge_orchestrator_retries_taskized_watchdog_failures_inside_large_parent_shards(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        lambda _sequence, overrides=None: [  # noqa: ARG005
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Chunk 0",
                text="A" * 4000,
                blockIds=[0],
            ),
            KnowledgeChunk(
                id="chunk-1",
                lane=ChunkLane.KNOWLEDGE,
                title="Chunk 1",
                text="B" * 4000,
                blockIds=[1],
            ),
        ],
    )

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 1,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "A" * 4000},
                        {"index": 1, "text": "B" * 4000},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    class _WatchdogKilledRunner(FakeCodexExecRunner):
        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            from cookimport.llm.codex_exec_runner import CodexExecRunResult

            working_dir = Path(kwargs.get("working_dir"))
            self.calls.append(
                {
                    "mode": "workspace_worker",
                    "prompt_text": str(kwargs.get("prompt_text") or ""),
                    "input_payload": None,
                    "working_dir": str(working_dir),
                    "execution_working_dir": str(working_dir),
                    "output_schema_path": None,
                }
            )
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=None,
                prompt_text=str(kwargs.get("prompt_text") or ""),
                response_text=None,
                turn_failed_message="workspace worker stage attempted tool use",
                events=(),
                usage={
                    "input_tokens": 7,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                },
                stderr_text=None,
                stdout_text=None,
                source_working_dir=str(working_dir),
                execution_working_dir=str(working_dir),
                execution_agents_path=None,
                duration_ms=100,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:00Z",
                supervision_state="watchdog_killed",
                supervision_reason_code="watchdog_command_execution_forbidden",
                supervision_reason_detail="workspace worker stage attempted tool use",
                supervision_retryable=True,
            )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.2",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=2,
                    block_indices=[0, 1],
                    block_ids=["b0", "b1"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.2",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=2,
                    block_indices=[0, 1],
                    block_ids=["b0", "b1"],
                )
            ],
            other_spans=[],
            block_category_by_index={0: "knowledge", 1: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=_WatchdogKilledRunner(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.compact.v1",
                dict(payload or {}),
            )
        ),
    )

    process_summary = apply_result.llm_report["process_run"]["telemetry"]["summary"]
    assert process_summary["workspace_worker_session_count"] == 1
    assert process_summary["structured_followup_call_count"] == 2
    proposal = json.loads(
        (
            run_root / "raw" / "llm" / "book" / "knowledge" / "proposals" / "book.ks0000.nr.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal["watchdog_retry_attempted"] is True
    assert proposal["watchdog_retry_status"] == "failed"
    assert proposal["watchdog_retry_skip_reason_code"] == "retry_skipped_poisoned_worker"
    assert proposal["repair_attempted"] is True
    assert proposal["repair_status"] == "failed"
    assert proposal["validation_metadata"]["task_aggregation"]["task_count"] == 2
    assert proposal["validation_metadata"]["task_aggregation"]["fallback_task_ids"] == [
        "book.ks0000.nr.task-001",
        "book.ks0000.nr.task-002",
    ]
    assert proposal["validation_metadata"]["task_watchdog_retry_skip_reason_by_task_id"] == {
        "book.ks0000.nr.task-002": "retry_skipped_poisoned_worker"
    }
    assert apply_result.llm_report["review_status"] == "unreviewed"


def test_knowledge_orchestrator_retries_cohort_outlier_watchdog_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 4,
            "knowledge_worker_count": 4,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_orchestrator._KNOWLEDGE_COHORT_WATCHDOG_MIN_ELAPSED_MS",
        10,
    )
    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_orchestrator._KNOWLEDGE_COHORT_WATCHDOG_MEDIAN_FACTOR",
        2.0,
    )

    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id=f"chunk-{index}",
                lane=ChunkLane.KNOWLEDGE,
                title=f"Topic {index}",
                text=(f"Knowledge chunk {index} " + ("X" * 8000)),
                blockIds=[index],
            )
            for index in range(4)
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        nonRecipeBlocks=[
            {"index": index, "text": (f"Knowledge chunk {index} " + ("X" * 8000))}
            for index in range(4)
        ],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {
                            "index": index,
                            "text": (f"Knowledge chunk {index} " + ("X" * 8000)),
                        }
                        for index in range(4)
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    def _valid_payload(payload: dict[str, object] | None) -> dict[str, object]:
        if payload is None:
            return {"v": "2", "bid": "missing", "r": []}
        bundle_id = str(payload.get("bid") or payload.get("shard_id") or "missing")
        chunk_rows: list[dict[str, object]] = []
        authoritative_input = payload.get("authoritative_input") or {}
        chunk_payloads = payload.get("c") or authoritative_input.get("c") or []
        for chunk in chunk_payloads:
            if not isinstance(chunk, dict):
                continue
            chunk_id = str(chunk.get("cid") or "").strip()
            if not chunk_id:
                continue
            blocks = chunk.get("b") or []
            first_block = blocks[0] if isinstance(blocks, list) and blocks else {}
            block_index = int((first_block or {}).get("i") or 0)
            block_text = str((first_block or {}).get("t") or "").strip()
            grounded_excerpt = block_text[:80].strip() or f"Knowledge chunk {block_index}"
            chunk_rows.append(
                {
                    "cid": chunk_id,
                    "u": True,
                    "d": [{"i": block_index, "c": "knowledge"}],
                    "s": [
                        {
                            "b": f"Technique note for {chunk_id}",
                            "e": [{"i": block_index, "q": grounded_excerpt}],
                        }
                    ],
                }
            )
        if not chunk_rows:
            for owned_id in payload.get("owned_ids", []) or []:
                chunk_id = str(owned_id or "").strip()
                if not chunk_id:
                    continue
                match = re.search(r"(\d+)", chunk_id)
                block_index = int(match.group(1)) if match is not None else 0
                chunk_rows.append(
                    {
                        "cid": chunk_id,
                        "u": True,
                        "d": [{"i": block_index, "c": "knowledge"}],
                        "s": [
                            {
                                "b": f"Technique note for {chunk_id}",
                                "e": [{"i": block_index, "q": f"Knowledge chunk {block_index}"}],
                            }
                        ],
                    }
                )
        return {
            "v": "2",
            "bid": bundle_id,
            "r": chunk_rows,
        }

    class _OutlierRetryRunner(FakeCodexExecRunner):
        def run_structured_prompt(self, *args, **kwargs):  # noqa: ANN002, ANN003
            payload = dict(kwargs.get("input_payload") or {})
            shard_id = str(payload.get("shard_id") or payload.get("bid") or "")
            if payload.get("retry_mode") == "knowledge_watchdog":
                return super().run_structured_prompt(*args, **kwargs)
            return super().run_structured_prompt(*args, **kwargs)

        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            working_dir = Path(kwargs.get("working_dir"))
            assigned_shards = json.loads(
                (working_dir / "assigned_shards.json").read_text(encoding="utf-8")
            )
            shard_id = ""
            if assigned_shards and isinstance(assigned_shards[0], dict):
                shard_id = str(assigned_shards[0].get("shard_id") or "")
            if shard_id.endswith("ks0003.nr"):
                supervision_callback = kwargs.get("supervision_callback")
                decision = None
                if supervision_callback is not None:
                    for _ in range(40):
                        time.sleep(0.05)
                        decision = supervision_callback(
                            CodexExecLiveSnapshot(
                                elapsed_seconds=0.2,
                                last_event_seconds_ago=0.05,
                                event_count=0,
                                command_execution_count=0,
                                reasoning_item_count=0,
                                last_command=None,
                                last_command_repeat_count=0,
                                has_final_agent_message=False,
                                timeout_seconds=kwargs.get("timeout_seconds"),
                            )
                        )
                        if decision is not None:
                            break
                assert decision is not None
                return self._build_result(
                    mode="workspace_worker",
                    prompt_text=str(kwargs.get("prompt_text") or ""),
                    working_dir=working_dir,
                    output_schema_path=None,
                    response_text=None,
                    usage={"input_tokens": 9, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0},
                    supervision_state="watchdog_killed",
                    supervision_reason_code=str(decision.reason_code),
                    supervision_reason_detail=str(decision.reason_detail),
                    supervision_retryable=bool(decision.retryable),
                )
            return super().run_workspace_worker(*args, **kwargs)

        def _build_result(
            self,
            *,
            mode: str,
            prompt_text: str,
            working_dir: Path,
            output_schema_path,
            response_text: str | None,
            usage: dict[str, int],
            supervision_state: str,
            supervision_reason_code: str | None,
            supervision_reason_detail: str | None,
            supervision_retryable: bool,
        ):
            from cookimport.llm.codex_exec_runner import CodexExecRunResult

            self.calls.append(
                {
                    "mode": mode,
                    "prompt_text": prompt_text,
                    "input_payload": {},
                    "working_dir": str(working_dir),
                    "output_schema_path": str(output_schema_path) if output_schema_path is not None else None,
                }
            )
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=str(output_schema_path) if output_schema_path is not None else None,
                prompt_text=prompt_text,
                response_text=response_text,
                turn_failed_message=supervision_reason_detail,
                events=(),
                usage=usage,
                source_working_dir=str(working_dir),
                execution_working_dir=str(working_dir),
                execution_agents_path=None,
                duration_ms=50,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:00Z",
                supervision_state=supervision_state,
                supervision_reason_code=supervision_reason_code,
                supervision_reason_detail=supervision_reason_detail,
                supervision_retryable=supervision_retryable,
            )

    runner = _OutlierRetryRunner(output_builder=_valid_payload)
    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.4",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=4,
                    block_indices=[0, 1, 2, 3],
                    block_ids=["b0", "b1", "b2", "b3"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.4",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=4,
                    block_indices=[0, 1, 2, 3],
                    block_ids=["b0", "b1", "b2", "b3"],
                )
            ],
            other_spans=[],
            block_category_by_index={0: "knowledge", 1: "knowledge", 2: "knowledge", 3: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    process_summary = apply_result.llm_report["process_run"]["telemetry"]["summary"]
    assert process_summary["watchdog_killed_shard_count"] == 1
    assert process_summary["call_count"] == 5
    assert process_summary["workspace_worker_session_count"] == 4
    assert process_summary["structured_followup_call_count"] == 1
    assert process_summary["prompt_input_mode_counts"] == {
        "inline_watchdog_retry": 1,
        "workspace_worker": 4,
    }

    proposals_dir = run_root / "raw" / "llm" / "book" / "knowledge" / "proposals"
    recovered_proposal = json.loads(
        (proposals_dir / "book.ks0003.nr.json").read_text(encoding="utf-8")
    )
    assert recovered_proposal["watchdog_retry_attempted"] is True
    assert recovered_proposal["watchdog_retry_status"] == "recovered"
    assert recovered_proposal["validation_errors"] == []

    retry_status_path = (
        run_root
        / "raw"
        / "llm"
        / "book"
        / "knowledge"
        / "workers"
        / "worker-004"
        / "shards"
        / "book.ks0003.nr"
        / "watchdog_retry"
        / "status.json"
    )
    retry_status = json.loads(retry_status_path.read_text(encoding="utf-8"))
    assert retry_status["status"] == "validated"
    assert retry_status["watchdog_retry_reason_code"] == "watchdog_cohort_runtime_outlier"

    retry_prompt = (
        retry_status_path.parent / "prompt.txt"
    ).read_text(encoding="utf-8")
    assert "Successful sibling examples:" in retry_prompt


def test_knowledge_orchestrator_taskization_eliminates_old_missing_rows_split_retry_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 1,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )

    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-a",
                lane=ChunkLane.KNOWLEDGE,
                text="Whisk constantly to emulsify sauces.",
                blockIds=[0],
            ),
            KnowledgeChunk(
                id="chunk-b",
                lane=ChunkLane.KNOWLEDGE,
                text="Use low heat to avoid curdling.",
                blockIds=[1],
            ),
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        nonRecipeBlocks=[
            {"index": 4, "text": "Whisk constantly to emulsify sauces."},
            {"index": 5, "text": "Use low heat to avoid curdling."},
        ],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 4, "text": "Whisk constantly to emulsify sauces."},
                        {"index": 5, "text": "Use low heat to avoid curdling."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    def _output_builder(payload: dict[str, object] | None) -> dict[str, object]:
        if payload is None:
            return {"v": "2", "bid": "missing", "r": []}
        bundle_id = str(payload.get("bid") or "")
        chunks = payload.get("c") or []
        chunk = chunks[0]
        blocks = list(chunk["b"])
        return {
            "v": "2",
            "bid": bundle_id,
            "r": [
                {
                    "cid": chunk["cid"],
                    "u": True,
                    "d": [
                        {"i": block["i"], "c": "knowledge", "rc": "knowledge"}
                        for block in blocks
                    ],
                    "s": [
                        {
                            "b": blocks[0]["t"],
                            "e": [{"i": blocks[0]["i"], "q": blocks[0]["t"]}],
                        }
                    ],
                }
            ],
        }

    runner = FakeCodexExecRunner(output_builder=_output_builder)

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.6",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=6,
                    block_indices=[4, 5],
                    block_ids=["b4", "b5"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.6",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=6,
                    block_indices=[4, 5],
                    block_ids=["b4", "b5"],
                )
            ],
            other_spans=[],
            block_category_by_index={4: "knowledge", 5: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    process_summary = apply_result.llm_report["process_run"]["telemetry"]["summary"]
    assert process_summary["call_count"] == 2
    assert process_summary["invalid_output_shard_count"] == 0
    assert process_summary["repaired_shard_count"] == 0
    assert process_summary["workspace_worker_session_count"] == 1
    assert process_summary["structured_followup_call_count"] == 0
    assert process_summary["prompt_input_mode_counts"] == {
        "workspace_worker": 2,
    }

    proposals_dir = run_root / "raw" / "llm" / "book" / "knowledge" / "proposals"
    proposal = json.loads((proposals_dir / "book.ks0000.nr.json").read_text(encoding="utf-8"))
    assert proposal["validation_errors"] == []
    assert proposal["retry_attempted"] is False
    assert proposal["retry_status"] == "not_attempted"
    assert proposal["repair_attempted"] is False
    assert proposal["payload"]["bid"] == "book.ks0000.nr"
    assert [row["cid"] for row in proposal["payload"]["r"]] == [
        "book.c0000.nr",
        "book.c0001.nr",
    ]
    assert proposal["validation_metadata"]["task_aggregation"]["task_count"] == 2


def test_knowledge_orchestrator_accepts_valid_workspace_outputs_without_final_message(
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 1,
            "knowledge_worker_count": 1,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )

    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        nonRecipeBlocks=[
            {"index": 4, "text": "Whisk constantly to emulsify sauces."},
            {"index": 5, "text": "Use low heat to avoid curdling."},
        ],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 4, "text": "Whisk constantly to emulsify sauces."},
                        {"index": 5, "text": "Use low heat to avoid curdling."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    def _output_builder(payload: dict[str, object] | None) -> dict[str, object]:
        if payload is None:
            return {"v": "2", "bid": "missing", "r": []}
        bundle_id = str(payload.get("bid") or "")
        chunks = payload.get("c") or []
        chunk = chunks[0]
        blocks = list(chunk["b"])
        return {
            "v": "2",
            "bid": bundle_id,
            "r": [
                {
                    "cid": chunk["cid"],
                    "u": True,
                    "d": [
                        {"i": block["i"], "c": "knowledge", "rc": "knowledge"}
                        for block in blocks
                    ],
                    "s": [
                        {
                            "b": blocks[0]["t"],
                            "e": [{"i": blocks[0]["i"], "q": blocks[0]["t"]}],
                        }
                    ],
                }
            ],
        }

    runner = _NoFinalWorkspaceMessageRunner(output_builder=_output_builder)

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.6",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=6,
                    block_indices=[4, 5],
                    block_ids=["b4", "b5"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.6",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=6,
                    block_indices=[4, 5],
                    block_ids=["b4", "b5"],
                )
            ],
            other_spans=[],
            block_category_by_index={4: "knowledge", 5: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    process_rows = [
        row
        for row in apply_result.llm_report["process_run"]["telemetry"]["rows"]
        if row.get("prompt_input_mode") == "workspace_worker"
    ]
    assert process_rows
    assert all(row["proposal_status"] == "validated" for row in process_rows)
    assert all(row["repair_attempted"] is False for row in process_rows)
    assert process_rows[0]["final_agent_message_state"] == "absent"
    assert process_rows[0]["final_agent_message_reason"] is None

    proposals_dir = run_root / "raw" / "llm" / "book" / "knowledge" / "proposals"
    proposal = json.loads((proposals_dir / "book.ks0000.nr.json").read_text(encoding="utf-8"))
    assert proposal["validation_errors"] == []
    assert proposal["repair_attempted"] is False
    assert proposal["payload"]["bid"] == "book.ks0000.nr"


def test_knowledge_orchestrator_noops_when_no_seed_nonrecipe_spans(tmp_path: Path) -> None:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[],
            knowledge_spans=[],
            other_spans=[],
            block_category_by_index={},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=FakeCodexExecRunner(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.compact.v1",
                dict(payload or {}),
            )
        ),
        full_blocks=[],
    )

    assert apply_result.llm_report["stage_status"] == "no_nonrecipe_spans"
    assert apply_result.llm_report["counts"]["shards_written"] == 0
    assert apply_result.llm_report["counts"]["shards_written"] == 0
    assert apply_result.llm_report["counts"]["chunks_written"] == 0
    assert apply_result.manifest_path.exists()


def test_knowledge_orchestrator_noops_when_all_chunks_are_skipped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-noise",
                lane=ChunkLane.NOISE,
                text="Advertisement copy.",
                blockIds=[0],
            )
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 4, "text": "Advertisement copy."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: build_structural_pipeline_output(
            "recipe.knowledge.compact.v1",
            dict(payload or {}),
        )
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            other_spans=[],
            block_category_by_index={4: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert len(runner.calls) == 1
    assert apply_result.llm_report["stage_status"] == "completed"
    assert apply_result.llm_report["counts"]["shards_written"] == 1
    assert apply_result.llm_report["counts"]["chunks_written"] == 1
    assert apply_result.llm_report["counts"]["skipped_chunk_count"] == 0
    assert apply_result.llm_report["skipped_lane_counts"] == {}


def test_knowledge_orchestrator_defaults_workers_to_shard_count_when_unspecified(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Sauce Basics",
                text="Always whisk constantly when adding butter.",
                blockIds=[0],
            ),
            KnowledgeChunk(
                id="chunk-1",
                lane=ChunkLane.KNOWLEDGE,
                title="Seasoning",
                text="Salt in layers for better control.",
                blockIds=[1],
            ),
            KnowledgeChunk(
                id="chunk-2",
                lane=ChunkLane.KNOWLEDGE,
                title="Storage",
                text="Cool leftovers quickly before refrigeration.",
                blockIds=[2],
            ),
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("COOKIMPORT_CODEX_FARM_CODEX_HOME", str(codex_home))

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 2,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_workspace_root": str(workspace_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
            "codex_farm_failure_mode": "fail",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Always whisk constantly when adding butter."},
                        {"index": 1, "text": "Salt in layers for better control."},
                        {"index": 2, "text": "Cool leftovers quickly before refrigeration."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.3",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=3,
                    block_indices=[0, 1, 2],
                    block_ids=["b0", "b1", "b2"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.3",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=3,
                    block_indices=[0, 1, 2],
                    block_ids=["b0", "b1", "b2"],
                )
            ],
            other_spans=[],
            block_category_by_index={0: "knowledge", 1: "knowledge", 2: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=FakeCodexExecRunner(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.compact.v1",
                dict(payload or {}),
            )
        ),
    )

    phase_runtime = apply_result.llm_report["phase_worker_runtime"]

    assert phase_runtime["shard_count"] == 2
    assert phase_runtime["worker_count"] == 2
    assert phase_runtime["bundle_policy"] == (
        "shard_round_robin_with_task_packets_v1"
    )
    assert phase_runtime["task_packet_total"] >= phase_runtime["shard_count"]
    assert sum(phase_runtime["worker_task_packet_counts"].values()) == phase_runtime[
        "task_packet_total"
    ]
    assert phase_runtime["max_task_packets_per_worker"] >= phase_runtime[
        "min_task_packets_per_worker"
    ]
    assert phase_runtime["min_task_packets_per_worker"] >= 1


def test_knowledge_orchestrator_uses_workspace_worker_for_multi_shard_assignment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Sauce Basics",
                text="Always whisk constantly when adding butter.",
                blockIds=[0],
            ),
            KnowledgeChunk(
                id="chunk-1",
                lane=ChunkLane.KNOWLEDGE,
                title="Seasoning",
                text="Salt in layers for better control.",
                blockIds=[1],
            ),
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 2,
            "knowledge_worker_count": 1,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Always whisk constantly when adding butter."},
                        {"index": 1, "text": "Salt in layers for better control."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: build_structural_pipeline_output(
            "recipe.knowledge.compact.v1",
            dict(payload or {}),
        )
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.2",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=2,
                    block_indices=[0, 1],
                    block_ids=["b0", "b1"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.2",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=2,
                    block_indices=[0, 1],
                    block_ids=["b0", "b1"],
                )
            ],
            other_spans=[],
            block_category_by_index={0: "knowledge", 1: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    knowledge_dir = run_root / "raw" / "llm" / "book" / "knowledge"
    worker_root = knowledge_dir / "workers" / "worker-001"
    status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))

    assert len(runner.calls) == 1
    assert runner.calls[0]["mode"] == "workspace_worker"
    assert (worker_root / "out" / "book.ks0000.nr.json").exists()
    assert (worker_root / "out" / "book.ks0001.nr.json").exists()
    assert apply_result.llm_report["stage_status"] == "completed"
    assert apply_result.llm_report["counts"]["validated_shards"] == 2
    assert status["runtime_mode_audit"]["output_schema_enforced"] is False
    assert status["runtime_mode_audit"]["tool_affordances_requested"] is True


def test_knowledge_orchestrator_taskizes_multi_chunk_shards_inside_workspace_assignment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Sauce Basics",
                text="Always whisk constantly when adding butter.",
                blockIds=[0],
            ),
            KnowledgeChunk(
                id="chunk-1",
                lane=ChunkLane.KNOWLEDGE,
                title="Seasoning",
                text="Salt in layers for better control.",
                blockIds=[1],
            ),
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 1,
            "knowledge_worker_count": 1,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Always whisk constantly when adding butter."},
                        {"index": 1, "text": "Salt in layers for better control."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: build_structural_pipeline_output(
            "recipe.knowledge.compact.v1",
            dict(payload or {}),
        )
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.2",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=2,
                    block_indices=[0, 1],
                    block_ids=["b0", "b1"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.2",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=2,
                    block_indices=[0, 1],
                    block_ids=["b0", "b1"],
                )
            ],
            other_spans=[],
            block_category_by_index={0: "knowledge", 1: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    phase_dir = run_root / "raw" / "llm" / "book" / "knowledge"
    task_manifest = [
        json.loads(line)
        for line in (phase_dir / "task_manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["task_id"] for row in task_manifest] == [
        "book.ks0000.nr.task-001",
        "book.ks0000.nr.task-002",
    ]
    assert [row["parent_shard_id"] for row in task_manifest] == [
        "book.ks0000.nr",
        "book.ks0000.nr",
    ]

    worker_root = phase_dir / "workers" / "worker-001"
    assert (worker_root / "out" / "book.ks0000.nr.task-001.json").exists()
    assert (worker_root / "out" / "book.ks0000.nr.task-002.json").exists()
    proposal = json.loads((phase_dir / "proposals" / "book.ks0000.nr.json").read_text(encoding="utf-8"))
    assert proposal["validation_errors"] == []
    assert proposal["validation_metadata"]["task_aggregation"]["task_count"] == 2
    assert proposal["validation_metadata"]["task_aggregation"]["accepted_task_ids"] == [
        "book.ks0000.nr.task-001",
        "book.ks0000.nr.task-002",
    ]
    assert apply_result.llm_report["counts"]["validated_shards"] == 1


def test_knowledge_orchestrator_partially_promotes_accepted_task_packets_from_invalid_parent_shard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Sauce Basics",
                text="Always whisk constantly when adding butter.",
                blockIds=[0],
            ),
            KnowledgeChunk(
                id="chunk-1",
                lane=ChunkLane.KNOWLEDGE,
                title="Serving",
                text="Serve the sauce immediately while it is still glossy.",
                blockIds=[1],
            ),
            KnowledgeChunk(
                id="chunk-2",
                lane=ChunkLane.KNOWLEDGE,
                title="Storage",
                text="Cool leftovers quickly before refrigeration.",
                blockIds=[2],
            ),
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 1,
            "knowledge_worker_count": 1,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Always whisk constantly when adding butter."},
                        {
                            "index": 1,
                            "text": "Serve the sauce immediately while it is still glossy.",
                        },
                        {"index": 2, "text": "Cool leftovers quickly before refrigeration."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    def _task_output(payload: dict[str, object]) -> dict[str, object]:
        task_id = str(payload["bid"])
        chunk = payload["c"][0]
        block = chunk["b"][0]
        if task_id.endswith("task-001"):
            return {
                "v": "2",
                "bid": task_id,
                "r": [
                    {
                        "cid": chunk["cid"],
                        "u": True,
                        "d": [{"i": block["i"], "c": "knowledge", "rc": "knowledge"}],
                        "s": [{"b": "Whisk constantly.", "e": [{"i": block["i"], "q": "Whisk constantly."}]}],
                    }
                ],
            }
        if task_id.endswith("task-002"):
            return {
                "v": "2",
                "bid": task_id,
                "r": [
                    {
                        "cid": chunk["cid"],
                        "u": True,
                        "d": [{"i": block["i"], "c": "knowledge", "rc": "knowledge"}],
                        "s": [
                            {
                                "b": "Serve immediately while the sauce is glossy.",
                                "e": [{"i": block["i"], "q": "Serve the sauce immediately while it is still glossy."}],
                            }
                        ],
                    }
                ],
            }
        return {
            "v": "2",
            "bid": task_id,
            "r": [
                {
                    "cid": chunk["cid"],
                    "u": True,
                    "d": [{"i": block["i"], "c": "knowledge", "rc": "knowledge"}],
                    "s": [{"b": "...", "e": [{"i": block["i"], "q": str(block["t"])}]}],
                }
            ],
        }

    runner = FakeCodexExecRunner(output_builder=_task_output)

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.3",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=3,
                    block_indices=[0, 1, 2],
                    block_ids=["b0", "b1", "b2"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.3",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=3,
                    block_indices=[0, 1, 2],
                    block_ids=["b0", "b1", "b2"],
                )
            ],
            other_spans=[],
            block_category_by_index={0: "knowledge", 1: "knowledge", 2: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    phase_dir = run_root / "raw" / "llm" / "book" / "knowledge"
    proposal = json.loads((phase_dir / "proposals" / "book.ks0000.nr.json").read_text(encoding="utf-8"))
    task_rows = [
        json.loads(line)
        for line in (phase_dir / "task_status.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert apply_result.refined_stage_result.block_category_by_index == {
        0: "knowledge",
        1: "knowledge",
        2: "knowledge",
    }
    assert proposal["validation_errors"] == ["missing_owned_chunk_results"]
    assert proposal["validation_metadata"]["task_aggregation"]["accepted_task_ids"] == [
        "book.ks0000.nr.task-001",
        "book.ks0000.nr.task-002",
    ]
    assert task_rows[1]["state"] == "validated"
    assert task_rows[2]["validation_errors"] == ["semantic_snippet_body_not_grounded_text"]
    assert apply_result.llm_report["stage_status"] == "completed_with_failures"
    assert apply_result.llm_report["review_status"] == "partial"
    assert apply_result.llm_report["counts"]["validated_shards"] == 0
    assert apply_result.llm_report["counts"]["invalid_shards"] == 1
    assert apply_result.llm_report["counts"]["partially_promoted_shards"] == 1
    assert apply_result.llm_report["counts"]["wholly_unpromoted_invalid_shards"] == 0
    assert apply_result.llm_report["counts"]["promoted_chunk_count"] == 2
    assert apply_result.llm_report["counts"]["outputs_parsed"] == 2
    assert apply_result.llm_report["counts"]["unreviewed_shard_count"] == 0
    assert apply_result.llm_report["counts"]["unreviewed_chunk_count"] == 1
    assert apply_result.llm_report["counts"]["chunks_missing"] == 1
    assert apply_result.llm_report["review_summary"]["reviewed_shard_count"] == 1
    assert apply_result.llm_report["review_summary"]["partially_promoted_shard_count"] == 1
    assert apply_result.llm_report["review_summary"]["unreviewed_shard_count"] == 0
    assert apply_result.llm_report["review_summary"]["reviewed_chunk_count"] == 2
    assert apply_result.llm_report["missing_chunk_ids"] == ["book.c0002.nr"]


def test_knowledge_orchestrator_can_promote_seed_other_block_to_final_knowledge(
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
            "codex_farm_failure_mode": "fail",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 8, "text": "Why this works: acid slows browning."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: {
            "v": "2",
            "bid": payload["bid"],
            "r": [
                {
                    "cid": payload["c"][0]["cid"],
                    "u": True,
                    "d": [{"i": 8, "c": "knowledge", "rc": "knowledge"}],
                    "s": [
                        {
                            "b": "Acid slows browning.",
                            "e": [{"i": 8, "q": "acid slows browning"}],
                        }
                    ],
                }
            ],
        }
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.other.8.9",
                    category="other",
                    block_start_index=8,
                    block_end_index=9,
                    block_indices=[8],
                    block_ids=["b8"],
                )
            ],
            knowledge_spans=[],
            other_spans=[
                NonRecipeSpan(
                    span_id="nr.other.8.9",
                    category="other",
                    block_start_index=8,
                    block_end_index=9,
                    block_indices=[8],
                    block_ids=["b8"],
                )
            ],
            block_category_by_index={8: "other"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert apply_result.refined_stage_result.seed_block_category_by_index == {8: "other"}
    assert apply_result.refined_stage_result.block_category_by_index == {8: "knowledge"}
    assert apply_result.refined_stage_result.refinement_report["changed_block_count"] == 1
    assert apply_result.refined_stage_result.refinement_report["reviewer_category_counts"] == {
        "knowledge": 1
    }
    assert apply_result.llm_report["authority_mode"] == "knowledge_refined_final"
    assert apply_result.llm_report["scored_effect"] == "final_authority"


def test_knowledge_orchestrator_maps_other_reviewer_category_to_final_other(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        lambda _sequence, overrides=None: [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Salt",
                text="SALT",
                blockIds=[0],
            )
        ],
    )
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={"blocks": [{"index": 4, "text": "SALT"}]},
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: {
            "v": "2",
            "bid": payload["bid"],
            "r": [
                {
                    "cid": payload["c"][0]["cid"],
                    "u": False,
                    "d": [{"i": 4, "c": "other", "rc": "chapter_taxonomy"}],
                    "s": [],
                }
            ],
        }
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            other_spans=[],
            block_category_by_index={4: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert apply_result.refined_stage_result.block_category_by_index == {4: "other"}
    assert apply_result.refined_stage_result.refinement_report["reviewer_category_counts"] == {
        "chapter_taxonomy": 1
    }


def test_knowledge_orchestrator_rejects_off_surface_worker_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        lambda _sequence, overrides=None: [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Sauce Basics",
                text="Whisk constantly.",
                blockIds=[0],
            )
        ],
    )
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 4, "text": "Whisk constantly."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: {
            "v": "2",
            "bid": payload["bid"],
            "r": [
                {
                    "cid": payload["c"][0]["cid"],
                    "u": True,
                    "d": [{"i": 99, "c": "knowledge"}],
                    "s": [
                        {
                            "b": "Invalid output.",
                            "e": [{"i": 99, "q": "bad"}],
                        }
                    ],
                }
            ],
        }
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            other_spans=[],
            block_category_by_index={4: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert apply_result.refined_stage_result.block_category_by_index == {4: "knowledge"}
    assert apply_result.llm_report["counts"]["outputs_parsed"] == 0
    assert apply_result.llm_report["counts"]["invalid_shards"] == 1
    assert apply_result.llm_report["counts"]["unreviewed_shard_count"] == 1
    assert apply_result.llm_report["counts"]["unreviewed_chunk_count"] == 1
    assert apply_result.llm_report["counts"]["chunks_missing"] == 1
    assert apply_result.llm_report["missing_chunk_ids"] == ["book.c0000.nr"]
    assert apply_result.llm_report["stage_status"] == "completed_with_failures"
    assert apply_result.llm_report["review_status"] == "unreviewed"
    assert apply_result.llm_report["authority_mode"] == "knowledge_unreviewed_seed_kept"
    assert apply_result.write_report is not None
    assert apply_result.write_report.snippets_written == 0


def test_knowledge_orchestrator_rejects_semantically_empty_strong_cue_shard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        lambda _sequence, overrides=None: [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="How Salt Affects Eggs",
                text="Salt tightens proteins in eggs and changes texture.",
                blockIds=[0],
            )
        ],
    )

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={"blocks": [{"index": 4, "text": "Salt tightens proteins in eggs."}]},
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: {
            "v": "2",
            "bid": payload["bid"],
            "r": [
                {
                    "cid": payload["c"][0]["cid"],
                    "u": False,
                    "d": [{"i": 4, "c": "other", "rc": "other"}],
                    "s": [],
                }
            ],
        }
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            other_spans=[],
            block_category_by_index={4: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert apply_result.refined_stage_result.block_category_by_index == {4: "knowledge"}
    assert apply_result.llm_report["stage_status"] == "completed_with_failures"
    assert apply_result.llm_report["review_status"] == "unreviewed"
    assert apply_result.llm_report["authority_mode"] == "knowledge_unreviewed_seed_kept"
    assert apply_result.llm_report["counts"]["semantic_rejection_shard_count"] == 1
    assert apply_result.llm_report["counts"]["all_false_empty_shard_count"] == 1
    assert apply_result.llm_report["counts"]["unreviewed_shard_count"] == 1
    assert apply_result.llm_report["counts"]["unreviewed_chunk_count"] == 1
    assert apply_result.llm_report["missing_chunk_ids"] == ["book.c0000.nr"]


def test_knowledge_orchestrator_counts_valid_and_invalid_shards_in_same_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Sauce Basics",
                text="Always whisk constantly when adding butter.",
                blockIds=[0],
            ),
            KnowledgeChunk(
                id="chunk-1",
                lane=ChunkLane.KNOWLEDGE,
                title="Seasoning",
                text="Salt in layers for better control.",
                blockIds=[1],
            ),
            KnowledgeChunk(
                id="chunk-2",
                lane=ChunkLane.KNOWLEDGE,
                title="Storage",
                text="Cool leftovers quickly before refrigeration.",
                blockIds=[2],
            ),
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_shard_target_chunks": 2,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Always whisk constantly when adding butter."},
                        {"index": 1, "text": "Salt in layers for better control."},
                        {"index": 2, "text": "Cool leftovers quickly before refrigeration."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: (
            {
                "v": "2",
                "bid": payload["bid"],
                "r": [
                    {
                        "cid": chunk["cid"],
                        "u": True,
                        "d": [{"i": block["i"], "c": "knowledge", "rc": "knowledge"}],
                        "s": [
                            {
                                "b": block["t"],
                                "e": [{"i": block["i"], "q": block["t"]}],
                            }
                        ],
                    }
                    for chunk in payload["c"]
                    for block in chunk["b"][:1]
                ],
            }
            if str(payload["bid"]).startswith("book.ks0000.nr")
            else {
                "v": "2",
                "bid": payload["bid"],
                "r": [],
            }
        )
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.3",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=3,
                    block_indices=[0, 1, 2],
                    block_ids=["b0", "b1", "b2"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.3",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=3,
                    block_indices=[0, 1, 2],
                    block_ids=["b0", "b1", "b2"],
                )
            ],
            other_spans=[],
            block_category_by_index={0: "knowledge", 1: "knowledge", 2: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert apply_result.llm_report["stage_status"] == "completed_with_failures"
    assert apply_result.llm_report["review_status"] == "partial"
    assert apply_result.llm_report["review_summary"]["planned_shard_count"] == 2
    assert apply_result.llm_report["review_summary"]["reviewed_shard_count"] == 1
    assert apply_result.llm_report["review_summary"]["validated_shard_count"] == 1
    assert apply_result.llm_report["review_summary"]["invalid_shard_count"] == 1
    assert apply_result.llm_report["review_summary"]["reviewed_shards_with_useful_chunks"] == 1
    assert apply_result.llm_report["review_summary"]["unreviewed_shard_count"] == 1
    assert apply_result.llm_report["counts"]["outputs_parsed"] == 2
    assert apply_result.llm_report["counts"]["invalid_shards"] == 1
    assert apply_result.llm_report["counts"]["unreviewed_chunk_count"] == 1
    assert apply_result.llm_report["counts"]["chunks_missing"] == 1
    assert apply_result.llm_report["missing_chunk_ids"] == ["book.c0002.nr"]


def test_knowledge_orchestrator_honors_direct_shard_override_and_records_warnings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id=f"chunk-{index}",
                lane=ChunkLane.KNOWLEDGE,
                title=f"Topic {index}",
                text="X" * 8000,
                blockIds=[index],
            )
            for index in range(10)
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 5,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
            "codex_farm_failure_mode": "fail",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": index, "text": f"Block {index} " + ("X" * 8000)}
                        for index in range(10)
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.10",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=10,
                    block_indices=list(range(10)),
                    block_ids=[f"b{index}" for index in range(10)],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.10",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=10,
                    block_indices=list(range(10)),
                    block_ids=[f"b{index}" for index in range(10)],
                )
            ],
            other_spans=[],
            block_category_by_index={index: "knowledge" for index in range(10)},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=FakeCodexExecRunner(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.compact.v1",
                dict(payload or {}),
            )
        ),
    )

    assert apply_result.llm_report["counts"]["shards_written"] == 5
    assert apply_result.llm_report["phase_worker_runtime"]["shard_count"] == 5
    assert apply_result.llm_report["review_summary"]["reviewed_shard_count"] == 5
    assert apply_result.llm_report["planning_warnings"]
    assert any(
        "forced shard count 5 produced 5 shard(s)" in warning
        for warning in apply_result.llm_report["planning_warnings"]
    )


def test_knowledge_orchestrator_falls_back_when_phase_runtime_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FailingRunner:
        def run_structured_prompt(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise CodexFarmRunnerError("boom")

        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise CodexFarmRunnerError("boom")

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        lambda _sequence, overrides=None: [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Sauce Basics",
                text="Whisk constantly.",
                blockIds=[0],
            )
        ],
    )

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={"blocks": [{"index": 4, "text": "Whisk constantly."}]},
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            other_spans=[],
            block_category_by_index={4: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=FailingRunner(),  # type: ignore[arg-type]
    )

    assert apply_result.refined_stage_result.block_category_by_index == {4: "knowledge"}
    assert apply_result.llm_report["stage_status"] == "runtime_failed"
    assert apply_result.llm_report["authority_mode"] == "knowledge_not_run_runtime_failed"
    assert apply_result.llm_report["counts"]["outputs_parsed"] == 0
    assert apply_result.llm_report["counts"]["missing_output_shards"] == 1
