from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from cookimport.core.progress_messages import parse_stage_progress
from cookimport.llm.codex_exec_runner import (
    CodexExecLiveSnapshot,
    CodexExecRunResult,
    FakeCodexExecRunner,
)
from cookimport.llm.codex_farm_knowledge_orchestrator import (
    run_codex_farm_nonrecipe_knowledge_review,
)
from cookimport.llm.fake_codex_farm_runner import build_structural_pipeline_output
from tests.llm.knowledge_packet_test_support import (
    configure_runtime_codex_home,
    knowledge_span,
    make_runtime_conversion_result,
    make_runtime_nonrecipe_stage_result,
    make_runtime_pack_and_run_dirs,
    make_runtime_settings,
)


def _run_live_task_packet_progress_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> list[dict[str, object]]:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)

    class LiveProgressRunner(FakeCodexExecRunner):
        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            working_dir = Path(kwargs.get("working_dir"))
            out_dir = working_dir / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            supervision_callback = kwargs.get("supervision_callback")
            assigned_tasks = json.loads(
                (working_dir / "assigned_tasks.json").read_text(encoding="utf-8")
            )
            for index, task_row in enumerate(assigned_tasks, start=1):
                task_id = str(task_row.get("task_id") or "").strip()
                if not task_id:
                    continue
                input_payload = json.loads(
                    (working_dir / "in" / f"{task_id}.json").read_text(encoding="utf-8")
                )
                output_payload = build_structural_pipeline_output(
                    "recipe.knowledge.packet.v1",
                    dict(input_payload or {}),
                )
                (out_dir / f"{task_id}.json").write_text(
                    json.dumps(output_payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                if supervision_callback is not None and index < len(assigned_tasks):
                    supervision_callback(
                        CodexExecLiveSnapshot(
                            elapsed_seconds=index * 0.1,
                            last_event_seconds_ago=0.0,
                            event_count=index,
                            command_execution_count=index,
                            reasoning_item_count=0,
                            last_command=f"/bin/bash -lc cat out/{task_id}.json",
                            last_command_repeat_count=1,
                            has_final_agent_message=False,
                            timeout_seconds=kwargs.get("timeout_seconds"),
                        )
                    )
            response_text = json.dumps({"status": "worker_completed"}, sort_keys=True)
            events = (
                {"type": "thread.started"},
                {"type": "item.completed", "item": {"type": "agent_message", "text": response_text}},
            )
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=None,
                prompt_text=str(kwargs.get("prompt_text") or ""),
                response_text=response_text,
                turn_failed_message=None,
                events=events,
                usage={"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 4, "reasoning_tokens": 0},
                stderr_text=None,
                stdout_text="\n".join(json.dumps(event) for event in events) + "\n",
                source_working_dir=str(working_dir),
                execution_working_dir=str(working_dir),
                execution_agents_path=None,
                duration_ms=25,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:01Z",
                supervision_state="completed",
            )

    pack_root, run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(pack_root=pack_root, worker_count=1)
    progress_messages: list[str] = []
    run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=make_runtime_conversion_result(
            ["Knowledge zero.", "Recipe gap.", "Knowledge two."]
        ),
        nonrecipe_stage_result=make_runtime_nonrecipe_stage_result(
            spans=[knowledge_span(0), knowledge_span(2)]
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=LiveProgressRunner(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.packet.v1",
                dict(payload or {}),
            )
        ),
        progress_callback=progress_messages.append,
    )
    return [
        payload
        for message in progress_messages
        for payload in [parse_stage_progress(message)]
        if payload is not None
    ]


def test_knowledge_orchestrator_reports_live_packet_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payloads = _run_live_task_packet_progress_fixture(monkeypatch, tmp_path)

    assert payloads
    assert payloads[0]["task_current"] == 0
    assert payloads[0]["task_total"] == 2
    live_payloads = [
        payload
        for payload in payloads
        if 0 < int(payload.get("task_current") or 0) < int(payload.get("task_total") or 0)
    ]
    assert live_payloads
    assert {int(payload["task_current"]) for payload in live_payloads} == {1}
    assert payloads[-1]["task_current"] == 2
    assert payloads[-1]["task_total"] == 2


def test_knowledge_orchestrator_progress_detail_lines_track_live_packets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payloads = _run_live_task_packet_progress_fixture(monkeypatch, tmp_path)
    live_payloads = [
        payload
        for payload in payloads
        if 0 < int(payload.get("task_current") or 0) < int(payload.get("task_total") or 0)
    ]

    assert any(
        "book.kp0000.nr +1 more (1/2 tasks)" in (payload.get("active_tasks") or [])
        for payload in live_payloads
    )
    assert any(
        "completed shards: 0/2" in (payload.get("detail_lines") or [])
        for payload in live_payloads
    )


def test_knowledge_orchestrator_runs_packet_workers_concurrently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    state = {"current": 0, "max": 0}

    class ConcurrentRunner(FakeCodexExecRunner):
        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            with lock:
                state["current"] += 1
                state["max"] = max(state["max"], state["current"])
            barrier.wait(timeout=1.0)
            time.sleep(0.05)
            try:
                return super().run_workspace_worker(*args, **kwargs)
            finally:
                with lock:
                    state["current"] -= 1

    pack_root, run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(pack_root=pack_root, worker_count=2)
    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=make_runtime_conversion_result(
            ["Knowledge zero.", "Recipe gap.", "Knowledge two."]
        ),
        nonrecipe_stage_result=make_runtime_nonrecipe_stage_result(
            spans=[knowledge_span(0), knowledge_span(2)]
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=ConcurrentRunner(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.packet.v1",
                dict(payload or {}),
            )
        ),
    )

    process_summary = apply_result.llm_report["process_run"]["telemetry"]["summary"]
    assert apply_result.llm_report["phase_worker_runtime"]["shard_count"] == 2
    assert apply_result.llm_report["phase_worker_runtime"]["worker_count"] == 2
    assert process_summary["workspace_worker_row_count"] == 2
    assert process_summary["workspace_worker_session_count"] == 2
    assert process_summary["prompt_input_mode_counts"]["workspace_worker"] == 2
    assert state["max"] >= 2
