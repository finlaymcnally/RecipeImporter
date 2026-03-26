from __future__ import annotations

import json
import subprocess
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

    class PhaseRunner(FakeCodexExecRunner):
        def __init__(self) -> None:
            super().__init__(
                output_builder=lambda payload: build_structural_pipeline_output(
                    "recipe.knowledge.packet.v1",
                    dict(payload or {}),
                )
            )
            self.initial_assigned_shard_ids: list[str] = []
            self.initial_pass1_ledgers: dict[str, dict[str, object]] = {}
            self.initial_phase_row: dict[str, object] | None = None
            self.initial_check_phase: subprocess.CompletedProcess[str] | None = None
            self.initial_phase_brief = ""
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
            self.initial_pass1_ledgers = {
                path.name: json.loads(path.read_text(encoding="utf-8"))
                for path in sorted((working_dir / "work").glob("*.pass1.json"))
            }
            self.initial_phase_row = json.loads(
                (working_dir / "current_phase.json").read_text(encoding="utf-8")
            )
            self.initial_phase_brief = (working_dir / "CURRENT_PHASE.md").read_text(
                encoding="utf-8"
            )
            self.initial_check_phase = subprocess.run(
                ["python3", "tools/knowledge_worker.py", "check-phase"],
                cwd=working_dir,
                text=True,
                capture_output=True,
                check=False,
            )
            return super().run_workspace_worker(*args, **kwargs)

    pack_root, run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(pack_root=pack_root, worker_count=1)
    runner = PhaseRunner()
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


def test_knowledge_orchestrator_uses_phase_surface_not_task_queue_surface(
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
    assert runner.initial_phase_row == {
        "status": "active",
        "phase": "pass1",
        "shard_id": "book.ks0000.nr",
        "input_path": "in/book.ks0000.nr.json",
        "work_path": "work/book.ks0000.nr.pass1.json",
        "repair_path": "repair/book.ks0000.nr.pass1.json",
        "result_path": "out/book.ks0000.nr.json",
        "hint_path": "hints/book.ks0000.nr.md",
    }
    assert "check-phase" in runner.initial_phase_brief


def test_knowledge_orchestrator_seeds_valid_pass1_ledgers_before_worker_edits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_runtime_phase_fixture(monkeypatch, tmp_path)
    runner = fixture["runner"]
    worker_root = fixture["worker_root"]

    assert runner.initial_check_phase is not None
    assert runner.initial_check_phase.returncode == 0, (
        runner.initial_check_phase.stderr or runner.initial_check_phase.stdout
    )
    assert runner.initial_pass1_ledgers == {
        "book.ks0000.nr.pass1.json": {
            "phase": "pass1",
            "rows": [{"block_index": 0, "category": "other"}],
        },
        "book.ks0001.nr.pass1.json": {
            "phase": "pass1",
            "rows": [{"block_index": 2, "category": "other"}],
        },
    }
