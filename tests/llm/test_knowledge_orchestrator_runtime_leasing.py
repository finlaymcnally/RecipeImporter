from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

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


def _run_runtime_task_leasing_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)

    class LeasingRunner(FakeCodexExecRunner):
        def __init__(self) -> None:
            super().__init__(
                output_builder=lambda payload: build_structural_pipeline_output(
                    "recipe.knowledge.packet.v1",
                    dict(payload or {}),
                )
            )
            self.seen_task_ids: list[str] = []
            self.seen_result_paths: list[str] = []
            self.seen_hint_prefixes: list[str] = []

        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            working_dir = Path(kwargs.get("working_dir"))
            out_dir = working_dir / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            supervision_callback = kwargs.get("supervision_callback")
            current_task_path = working_dir / "current_task.json"

            while True:
                if not current_task_path.exists():
                    break
                current_task = json.loads(current_task_path.read_text(encoding="utf-8"))
                task_metadata = dict(current_task.get("metadata") or {})
                task_id = str(current_task.get("task_id") or "").strip()
                hint_path = working_dir / str(task_metadata.get("hint_path") or "").strip()
                current_hint = hint_path.read_text(encoding="utf-8")
                result_path_text = str(task_metadata.get("result_path") or "").strip()
                result_path = working_dir / result_path_text
                input_path = working_dir / str(task_metadata.get("input_path") or "").strip()
                input_payload = json.loads(input_path.read_text(encoding="utf-8"))

                self.seen_task_ids.append(task_id)
                self.seen_result_paths.append(result_path_text)
                self.seen_hint_prefixes.append(current_hint.splitlines()[0].strip())

                result_path.write_text(
                    json.dumps(
                        build_structural_pipeline_output(
                            "recipe.knowledge.packet.v1",
                            dict(input_payload or {}),
                        ),
                        indent=2,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                if supervision_callback is not None:
                    supervision_callback(
                        CodexExecLiveSnapshot(
                            elapsed_seconds=max(0.1, len(self.seen_task_ids) * 0.1),
                            last_event_seconds_ago=0.0,
                            event_count=len(self.seen_task_ids),
                            command_execution_count=len(self.seen_task_ids),
                            reasoning_item_count=0,
                            last_command="/bin/bash -lc 'cat current_task.json'",
                            last_command_repeat_count=1,
                            has_final_agent_message=False,
                            timeout_seconds=kwargs.get("timeout_seconds"),
                        )
                    )
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    if not current_task_path.exists():
                        break
                    refreshed_task = json.loads(current_task_path.read_text(encoding="utf-8"))
                    refreshed_task_id = str(refreshed_task.get("task_id") or "").strip()
                    if refreshed_task_id != task_id:
                        break
                    time.sleep(0.05)

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
                usage={"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 10, "reasoning_tokens": 0},
                duration_ms=250,
                started_at_utc="2026-03-20T22:45:20Z",
                finished_at_utc="2026-03-20T22:45:21Z",
                supervision_state="completed",
            )

    pack_root, run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(pack_root=pack_root, worker_count=1)
    runner = LeasingRunner()
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
        runner=runner,
    )

    phase_dir = run_root / "raw" / "llm" / "book" / "knowledge"
    worker_root = phase_dir / "workers" / "worker-001"
    task_status_rows = [
        json.loads(line)
        for line in (phase_dir / "task_status.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    proposal = json.loads((phase_dir / "proposals" / "book.kp0000.nr.json").read_text(encoding="utf-8"))
    return {
        "runner": runner,
        "worker_root": worker_root,
        "task_status_rows": task_status_rows,
        "proposal": proposal,
        "apply_result": apply_result,
    }


def test_knowledge_orchestrator_leases_packet_tasks_one_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_runtime_task_leasing_fixture(monkeypatch, tmp_path)
    runner = fixture["runner"]
    worker_root = fixture["worker_root"]

    assert isinstance(runner, FakeCodexExecRunner)
    assert isinstance(worker_root, Path)
    assert runner.seen_task_ids == ["book.kp0000.nr", "book.kp0001.nr"]
    assert runner.seen_result_paths == ["out/book.kp0000.nr.json", "out/book.kp0001.nr.json"]
    assert all("Knowledge review hints" in prefix for prefix in runner.seen_hint_prefixes)
    assert not (worker_root / "current_task.json").exists()
    assert "No current task is active" in (worker_root / "CURRENT_TASK.md").read_text(
        encoding="utf-8"
    )
    assert "queue is complete" in (
        worker_root / "CURRENT_TASK_FEEDBACK.md"
    ).read_text(encoding="utf-8").lower()


def test_knowledge_orchestrator_records_validated_packet_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_runtime_task_leasing_fixture(monkeypatch, tmp_path)
    task_status_rows = fixture["task_status_rows"]
    proposal = fixture["proposal"]
    apply_result = fixture["apply_result"]

    assert [row["state"] for row in task_status_rows] == ["validated", "validated"]
    assert proposal["validation_metadata"]["task_aggregation"]["accepted_task_ids"] == [
        "book.kp0000.nr"
    ]
    assert apply_result.llm_report["counts"]["validated_shards"] == 2
    assert apply_result.llm_report["process_run"]["pipeline_id"] == "recipe.knowledge.packet.v1"
