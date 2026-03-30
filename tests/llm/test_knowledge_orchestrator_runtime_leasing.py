from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.llm.codex_exec_runner import FakeCodexExecRunner
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


def _run_runtime_phase_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)

    class LeaseRunner(FakeCodexExecRunner):
        def __init__(self) -> None:
            super().__init__(
                output_builder=lambda payload: build_structural_pipeline_output(
                    "recipe.knowledge.packet.v1",
                    dict(payload or {}),
                )
            )
            self.initial_assigned_shard_ids: list[str] = []
            self.initial_packet: dict[str, object] | None = None
            self.initial_hint = ""
            self.initial_result_path = ""
            self.initial_lease_status: dict[str, object] | None = None
            self.saw_task_queue_surface = False

        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            working_dir = Path(kwargs.get("working_dir"))
            self.saw_task_queue_surface = any(
                (working_dir / name).exists()
                for name in (
                    "assigned_tasks.json",
                    "current_task.json",
                    "CURRENT_TASK.md",
                    "CURRENT_TASK_FEEDBACK.md",
                )
            )
            assigned_shards = json.loads(
                (working_dir / "assigned_shards.json").read_text(encoding="utf-8")
            )
            self.initial_assigned_shard_ids = [
                str(row.get("shard_id") or "").strip()
                for row in assigned_shards
                if isinstance(row, dict)
            ]
            self.initial_packet = json.loads(
                (working_dir / "current_packet.json").read_text(encoding="utf-8")
            )
            self.initial_hint = (working_dir / "current_hint.md").read_text(encoding="utf-8")
            self.initial_result_path = (working_dir / "current_result_path.txt").read_text(
                encoding="utf-8"
            ).strip()
            self.initial_lease_status = json.loads(
                (working_dir / "packet_lease_status.json").read_text(encoding="utf-8")
            )
            assert not (working_dir / "current_phase.json").exists()
            assert not (working_dir / "CURRENT_PHASE.md").exists()
            assert not (working_dir / "CURRENT_PHASE_FEEDBACK.md").exists()
            return super().run_workspace_worker(*args, **kwargs)

    pack_root, run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(
        pack_root=pack_root,
        worker_count=1,
        knowledge_prompt_target_count=2,
    )
    runner = LeaseRunner()
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
    return {
        "runner": runner,
        "worker_root": worker_root,
        "apply_result": apply_result,
    }


def test_knowledge_orchestrator_uses_packet_lease_surface_not_task_queue_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_runtime_phase_fixture(monkeypatch, tmp_path)
    runner = fixture["runner"]
    worker_root = fixture["worker_root"]

    assert isinstance(worker_root, Path)
    assert runner.saw_task_queue_surface is False
    assert not (worker_root / "assigned_tasks.json").exists()
    assert not (worker_root / "current_task.json").exists()
    assert not (worker_root / "CURRENT_TASK.md").exists()
    assert not (worker_root / "CURRENT_TASK_FEEDBACK.md").exists()
    assert runner.initial_assigned_shard_ids == ["book.ks0000.nr", "book.ks0001.nr"]
    assert runner.initial_packet == {
        "v": "1",
        "task_id": "book.ks0000.nr.pass1",
        "packet_kind": "pass1",
        "shard_id": "book.ks0000.nr",
        "rows": [{"block_index": 0, "text": "Knowledge zero."}],
    }
    assert "Result path: `scratch/book.ks0000.nr.pass1.json`" in runner.initial_hint
    assert runner.initial_result_path == "scratch/book.ks0000.nr.pass1.json"
    assert runner.initial_lease_status == {
        "worker_state": "leased_current_packet",
        "current_task_id": "book.ks0000.nr.pass1",
        "current_shard_id": "book.ks0000.nr",
        "packet_kind": "pass1",
        "packet_count_total": 1,
        "repair_packet_count": 0,
        "completed_shard_count": 0,
        "failed_shard_count": 0,
        "queue_total_shard_count": 2,
    }


def test_knowledge_orchestrator_advances_packet_leases_and_assembles_final_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_runtime_phase_fixture(monkeypatch, tmp_path)
    worker_root = fixture["worker_root"]

    packet_history = [
        json.loads(line)
        for line in (worker_root / "packet_history.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    queue_status = json.loads(
        (worker_root / "packet_lease_status.json").read_text(encoding="utf-8")
    )
    first_output = json.loads(
        (worker_root / "out" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )
    second_output = json.loads(
        (worker_root / "out" / "book.ks0001.nr.json").read_text(encoding="utf-8")
    )
    assert queue_status == {
        "worker_state": "queue_completed",
        "completed_shard_count": 2,
        "failed_shard_count": 0,
        "queue_total_shard_count": 2,
    }
    assert not (worker_root / "current_packet.json").exists()
    assert not (worker_root / "current_hint.md").exists()
    assert not (worker_root / "current_result_path.txt").exists()
    assert [event["event"] for event in packet_history] == [
        "lease_started",
        "lease_started",
        "shard_validated",
        "lease_started",
        "lease_started",
        "shard_validated",
    ]
    assert [event.get("task_id") for event in packet_history if event["event"] == "lease_started"] == [
        "book.ks0000.nr.pass1",
        "book.ks0000.nr.pass2",
        "book.ks0001.nr.pass1",
        "book.ks0001.nr.pass2",
    ]
    assert first_output["packet_id"] == "book.ks0000.nr"
    assert first_output["block_decisions"] == [
        {"block_index": 0, "category": "knowledge", "reviewer_category": "knowledge"}
    ]
    assert first_output["idea_groups"] == [
        {"group_id": "g01", "topic_label": "Fake knowledge group", "block_indices": [0]}
    ]
    assert second_output["packet_id"] == "book.ks0001.nr"
    assert second_output["block_decisions"] == [
        {"block_index": 2, "category": "knowledge", "reviewer_category": "knowledge"}
    ]
