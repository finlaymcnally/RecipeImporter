from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.llm.codex_exec_runner import CodexExecRunResult, FakeCodexExecRunner
from cookimport.llm.codex_farm_knowledge_orchestrator import (
    run_codex_farm_nonrecipe_finalize,
)
from cookimport.llm.fake_codex_farm_runner import build_structural_pipeline_output
from cookimport.runs.stage_observability import summarize_knowledge_stage_artifacts
from tests.llm.knowledge_packet_test_support import (
    configure_runtime_codex_home,
    knowledge_span,
    make_runtime_conversion_result,
    make_runtime_nonrecipe_stage_result,
    make_runtime_pack_and_run_dirs,
    make_runtime_settings,
)


def _run_runtime_phase(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    runner: FakeCodexExecRunner,
) -> dict[str, object]:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)
    pack_root, run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(
        pack_root=pack_root,
        worker_count=1,
        knowledge_prompt_target_count=2,
    )
    apply_result = run_codex_farm_nonrecipe_finalize(
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

    phase_dir = run_root / "raw" / "llm" / "book" / "nonrecipe_finalize"
    worker_root = phase_dir / "workers" / "worker-001"
    return {
        "runner": runner,
        "worker_root": worker_root,
        "phase_dir": phase_dir,
        "apply_result": apply_result,
    }


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

    return _run_runtime_phase(monkeypatch, tmp_path, runner=LeaseRunner())


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
    assert runner.initial_lease_status is not None
    assert runner.initial_lease_status["schema_version"] == "knowledge_packet_lease_status.v1"
    assert runner.initial_lease_status["worker_state"] == "leased_current_packet"
    assert runner.initial_lease_status["current_task_id"] == "book.ks0000.nr.pass1"
    assert runner.initial_lease_status["current_shard_id"] == "book.ks0000.nr"
    assert runner.initial_lease_status["packet_kind"] == "pass1"
    assert runner.initial_lease_status["current_packet_state"] == "leased"
    assert runner.initial_lease_status["current_result_relpath"] == "scratch/book.ks0000.nr.pass1.json"
    assert runner.initial_lease_status["packet_count_total"] == 1
    assert runner.initial_lease_status["repair_packet_count"] == 0
    assert runner.initial_lease_status["completed_shard_count"] == 0
    assert runner.initial_lease_status["failed_shard_count"] == 0
    assert runner.initial_lease_status["queue_total_shard_count"] == 2


def test_knowledge_orchestrator_advances_packet_leases_and_assembles_final_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_runtime_phase_fixture(monkeypatch, tmp_path)
    worker_root = fixture["worker_root"]
    phase_dir = fixture["phase_dir"]

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
    assert queue_status["schema_version"] == "knowledge_packet_lease_status.v1"
    assert queue_status["worker_state"] == "queue_completed"
    assert queue_status["last_runtime_action"] == "queue_completed"
    assert queue_status["completed_shard_count"] == 2
    assert queue_status["failed_shard_count"] == 0
    assert queue_status["queue_total_shard_count"] == 2
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
    telemetry = json.loads((phase_dir / "telemetry.json").read_text(encoding="utf-8"))
    assert telemetry["summary"]["packet_economics"]["packet_count_total"] == 4
    assert telemetry["summary"]["packet_economics"]["repair_packet_count_total"] == 0
    assert telemetry["summary"]["packet_economics"]["owned_row_count_total"] == 2


class _NoOutputLeaseRunner(FakeCodexExecRunner):
    def __init__(
        self,
        *,
        supervision_state: str = "completed",
        supervision_reason_code: str | None = None,
    ) -> None:
        super().__init__(output_builder=lambda payload: dict(payload or {}))
        self._supervision_state = supervision_state
        self._supervision_reason_code = supervision_reason_code

    def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
        working_dir = Path(kwargs.get("working_dir"))
        return CodexExecRunResult(
            command=["codex", "exec"],
            subprocess_exit_code=0,
            output_schema_path=None,
            prompt_text=str(kwargs.get("prompt_text") or ""),
            response_text='{"status":"worker_completed"}',
            turn_failed_message=None,
            usage={
                "input_tokens": 1,
                "cached_input_tokens": 0,
                "output_tokens": 1,
                "reasoning_tokens": 0,
            },
            source_working_dir=str(working_dir),
            execution_working_dir=str(working_dir),
            execution_agents_path=None,
            duration_ms=1,
            started_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:00Z",
            workspace_mode="workspace_worker",
            supervision_state=self._supervision_state,
            supervision_reason_code=self._supervision_reason_code,
        )


def _load_task_status_rows(path: Path) -> dict[str, dict[str, object]]:
    return {
        payload["task_id"]: payload
        for payload in (
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


def test_knowledge_orchestrator_classifies_clean_exit_with_packet_still_leased(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=_NoOutputLeaseRunner(),
    )
    phase_dir = Path(fixture["phase_dir"])
    worker_root = Path(fixture["worker_root"])

    task_rows = _load_task_status_rows(phase_dir / "task_status.jsonl")
    proposal = json.loads(
        (phase_dir / "proposals" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )
    summary = summarize_knowledge_stage_artifacts(phase_dir)
    lease_status = json.loads(
        (worker_root / "packet_lease_status.json").read_text(encoding="utf-8")
    )

    assert task_rows["book.ks0000.nr"]["state"] == "worker_exited_with_packet_still_leased"
    assert (
        task_rows["book.ks0000.nr"]["terminal_reason_code"]
        == "worker_exited_with_packet_still_leased"
    )
    assert proposal["validation_metadata"]["terminal_reason_code"] == (
        "worker_exited_with_packet_still_leased"
    )
    assert summary["packets"]["no_final_output_reason_code_counts"] == {
        "process_exited_without_final_packet_state": 1,
        "worker_exited_with_packet_still_leased": 1,
    }
    assert summary["attention_summary"]["zero_target_counts"]["no_final_output_shard_count"] == 2
    assert lease_status["worker_state"] == "leased_current_packet"
    assert lease_status["current_packet_state"] == "leased"


def test_knowledge_orchestrator_classifies_repair_packet_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=FakeCodexExecRunner(
            output_builder=lambda payload: {
                "task_id": str((payload or {}).get("task_id") or ""),
                "packet_kind": str((payload or {}).get("packet_kind") or ""),
                "shard_id": str((payload or {}).get("shard_id") or ""),
                "rows": [],
            }
        ),
    )
    phase_dir = Path(fixture["phase_dir"])
    worker_root = Path(fixture["worker_root"])

    task_rows = _load_task_status_rows(phase_dir / "task_status.jsonl")
    summary = summarize_knowledge_stage_artifacts(phase_dir)
    lease_status = json.loads(
        (worker_root / "packet_lease_status.json").read_text(encoding="utf-8")
    )

    assert task_rows["book.ks0000.nr"]["state"] == "repair_packet_exhausted"
    assert task_rows["book.ks0000.nr"]["terminal_reason_code"] == "repair_packet_exhausted"
    assert "repair packet was exhausted" in str(
        task_rows["book.ks0000.nr"]["terminal_reason_detail"]
    )
    assert summary["packets"]["no_final_output_reason_code_counts"] == {
        "repair_packet_exhausted": 2
    }
    assert summary["attention_summary"]["zero_target_counts"]["no_final_output_shard_count"] == 2
    assert lease_status["shard_statuses"]["book.ks0000.nr"]["terminal_reason_code"] == (
        "repair_packet_exhausted"
    )
    assert lease_status["shard_statuses"]["book.ks0000.nr"]["repair_attempted"] is True


def test_knowledge_orchestrator_preserves_watchdog_reason_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=_NoOutputLeaseRunner(
            supervision_state="watchdog_killed",
            supervision_reason_code="watchdog_command_execution_forbidden",
        ),
    )
    phase_dir = Path(fixture["phase_dir"])

    task_rows = _load_task_status_rows(phase_dir / "task_status.jsonl")
    summary = summarize_knowledge_stage_artifacts(phase_dir)

    assert task_rows["book.ks0000.nr"]["state"] == "watchdog_killed"
    assert (
        task_rows["book.ks0000.nr"]["terminal_reason_code"]
        == "watchdog_command_execution_forbidden"
    )
    assert summary["packets"]["no_final_output_reason_code_counts"] == {
        "watchdog_command_execution_forbidden": 2
    }
