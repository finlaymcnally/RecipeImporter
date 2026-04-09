from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from cookimport.llm.codex_exec_runner import CodexExecRunResult, FakeCodexExecRunner
from cookimport.llm.editable_task_file import load_task_file, write_task_file
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
    make_runtime_recipe_ownership_result,
    make_runtime_settings,
)


def _run_runtime_phase(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    runner: FakeCodexExecRunner,
    settings=None,
    block_texts: list[str] | None = None,
    spans=None,
) -> dict[str, object]:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)
    pack_root, run_root = make_runtime_pack_and_run_dirs(tmp_path)
    if settings is None:
        settings = make_runtime_settings(
            pack_root=pack_root,
            worker_count=1,
            knowledge_prompt_target_count=2,
        )
    runtime_block_texts = (
        list(block_texts)
        if block_texts is not None
        else ["Knowledge zero.", "Recipe gap.", "Knowledge two."]
    )
    runtime_spans = list(spans) if spans is not None else [knowledge_span(0), knowledge_span(2)]
    apply_result = run_codex_farm_nonrecipe_finalize(
        conversion_result=make_runtime_conversion_result(runtime_block_texts),
        nonrecipe_stage_result=make_runtime_nonrecipe_stage_result(spans=runtime_spans),
        recipe_ownership_result=make_runtime_recipe_ownership_result(
            block_count=len(runtime_block_texts)
        ),
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

    class AssignmentRunner(FakeCodexExecRunner):
        def __init__(self) -> None:
            super().__init__(
                output_builder=lambda payload: build_structural_pipeline_output(
                    "recipe.knowledge.packet.v1",
                    dict(payload or {}),
                )
            )
            self.initial_assigned_shard_ids: list[str] = []
            self.saw_task_queue_surface = False
            self.saw_task_file_surface = False

        def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
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
            self.saw_task_file_surface = (working_dir / "task.json").exists()
            task_file = load_task_file(working_dir / "task.json")
            self.initial_assigned_shard_ids = sorted(
                {
                    str(unit.get("owned_id") or "").partition(":")[0]
                    for unit in task_file.get("units") or []
                    if isinstance(unit, dict)
                }
            )
            assert not (working_dir / "current_packet.json").exists()
            assert not (working_dir / "current_hint.md").exists()
            assert not (working_dir / "current_result_path.txt").exists()
            assert not (working_dir / "packet_lease_status.json").exists()
            assert not (working_dir / "current_phase.json").exists()
            assert not (working_dir / "CURRENT_PHASE.md").exists()
            assert not (working_dir / "CURRENT_PHASE_FEEDBACK.md").exists()
            return super().run_taskfile_worker(*args, **kwargs)

    return _run_runtime_phase(monkeypatch, tmp_path, runner=AssignmentRunner())


def test_knowledge_orchestrator_uses_fixed_assignment_surface_not_task_queue_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_runtime_phase_fixture(monkeypatch, tmp_path)
    runner = fixture["runner"]
    worker_root = fixture["worker_root"]

    assert isinstance(worker_root, Path)
    assert runner.saw_task_queue_surface is False
    assert runner.saw_task_file_surface is True
    assert not (worker_root / "assigned_tasks.json").exists()
    assert not (worker_root / "current_task.json").exists()
    assert not (worker_root / "CURRENT_TASK.md").exists()
    assert not (worker_root / "CURRENT_TASK_FEEDBACK.md").exists()
    assert (worker_root / "task.json").exists()
    assert runner.initial_assigned_shard_ids == ["book.ks0000.nr", "book.ks0001.nr"]
    assert not (worker_root / "current_packet.json").exists()
    assert not (worker_root / "current_hint.md").exists()
    assert not (worker_root / "current_result_path.txt").exists()
    assert not (worker_root / "packet_lease_status.json").exists()


def test_knowledge_orchestrator_writes_final_outputs_from_fixed_assignments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_runtime_phase_fixture(monkeypatch, tmp_path)
    worker_root = fixture["worker_root"]
    phase_dir = fixture["phase_dir"]
    task_file = load_task_file(worker_root / "task.json")
    classify_snapshot = json.loads(
        (worker_root / "task_classification.initial.json").read_text(encoding="utf-8")
    )

    first_output = json.loads(
        (worker_root / "out" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )
    second_output = json.loads(
        (worker_root / "out" / "book.ks0001.nr.json").read_text(encoding="utf-8")
    )
    assert not (worker_root / "current_packet.json").exists()
    assert not (worker_root / "current_hint.md").exists()
    assert not (worker_root / "current_result_path.txt").exists()
    assert classify_snapshot["stage_key"] == "nonrecipe_classify"
    assert classify_snapshot["answer_schema"]["editable_pointer_pattern"] == "/units/*/answer"
    assert classify_snapshot["ontology"]["catalog_version"] == "cookbook-tag-catalog-2026-03-30"
    assert "helper_commands" not in classify_snapshot
    assert classify_snapshot["answer_schema"]["example_answers"][0]["category"] == "knowledge"
    assert task_file["stage_key"] == "knowledge_group"
    assert "helper_commands" not in task_file
    assert task_file["answer_schema"]["editable_pointer_pattern"] == "/units/*/answer"
    assert task_file["answer_schema"]["example_answers"][0]["group_key"] == "heat-control"
    assert first_output["packet_id"] == "book.ks0000.nr"
    assert first_output["block_decisions"][0]["block_index"] == 0
    assert first_output["block_decisions"][0]["category"] == "knowledge"
    assert first_output["block_decisions"][0]["grounding"]["proposed_tags"]
    assert first_output["idea_groups"] == [
        {"group_id": "g01", "topic_label": "Fake knowledge group", "block_indices": [0]}
    ]
    assert second_output["packet_id"] == "book.ks0001.nr"
    assert second_output["block_decisions"][0]["block_index"] == 2
    assert second_output["block_decisions"][0]["category"] == "knowledge"
    assert second_output["block_decisions"][0]["grounding"]["proposed_tags"]
    phase_manifest = json.loads((phase_dir / "phase_manifest.json").read_text(encoding="utf-8"))
    telemetry = json.loads((phase_dir / "telemetry.json").read_text(encoding="utf-8"))
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))
    stage_summary = summarize_knowledge_stage_artifacts(phase_dir)
    assert telemetry["summary"]["packet_economics"]["packet_count_total"] >= 2
    assert telemetry["summary"]["packet_economics"]["repair_packet_count_total"] == 0
    assert telemetry["summary"]["packet_economics"]["owned_row_count_total"] == 2
    assert telemetry["summary"]["packet_economics"]["classification_step_count_total"] == 1
    assert telemetry["summary"]["packet_economics"]["grouping_step_count_total"] == 1
    assert telemetry["summary"]["packet_economics"]["classification_validation_count_total"] == 1
    assert telemetry["summary"]["packet_economics"]["grouping_validation_count_total"] == 1
    assert telemetry["summary"]["packet_economics"]["same_session_transition_count_total"] == 2
    assert telemetry["summary"]["packet_economics"]["grouping_transition_count_total"] == 1
    assert telemetry["rows"][0]["knowledge_same_session"] is True
    assert telemetry["summary"]["worker_session_guardrails"]["planned_happy_path_worker_cap"] == 2
    assert telemetry["summary"]["task_file_guardrails"]["assignment_count"] == 1
    assert (
        worker_status["repair_recovery_policy"]["worker_assignment"]["budgets"][
            "structured_repair_followup"
        ]["allowed_attempts"]
        == 2
    )
    assert (
        worker_status["repair_recovery_policy"]["worker_assignment"]["budgets"][
            "structured_repair_followup"
        ]["spent_attempts"]
        == 0
    )
    assert (
        phase_manifest["runtime_metadata"]["worker_session_guardrails"][
            "actual_happy_path_worker_sessions"
        ]
        == 1
    )
    assert stage_summary["pre_kill_failures_observed"] is False


def test_knowledge_orchestrator_can_skip_grouping_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)
    pack_root, _run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(
        pack_root=pack_root,
        worker_count=1,
        knowledge_prompt_target_count=1,
        knowledge_grouping_enabled=False,
    )
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: build_structural_pipeline_output(
            "recipe.knowledge.packet.v1",
            dict(payload or {}),
        )
    )

    fixture = _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=runner,
        settings=settings,
        block_texts=["Knowledge zero."],
        spans=[knowledge_span(0)],
    )
    phase_dir = Path(fixture["phase_dir"])
    worker_root = Path(fixture["worker_root"])
    output_payload = json.loads(
        (worker_root / "out" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )
    telemetry = json.loads((phase_dir / "telemetry.json").read_text(encoding="utf-8"))

    assert output_payload["idea_groups"] == []
    assert telemetry["summary"]["packet_economics"]["grouping_step_count_total"] == 0
    assert telemetry["summary"]["packet_economics"]["grouping_validation_count_total"] == 0


def test_knowledge_orchestrator_retries_one_fresh_session_after_preserved_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _FreshSessionKnowledgeRunner()
    fixture = _run_runtime_phase(monkeypatch, tmp_path, runner=runner)
    phase_dir = Path(fixture["phase_dir"])
    worker_root = Path(fixture["worker_root"])
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))
    phase_manifest = json.loads((phase_dir / "phase_manifest.json").read_text(encoding="utf-8"))

    assert runner.workspace_run_calls == 2
    assert worker_status["fresh_session_retry_count"] == 1
    assert worker_status["fresh_session_retry_status"] == "completed"
    assert worker_status["telemetry"]["summary"]["taskfile_session_count"] == 2
    assert (
        phase_manifest["runtime_metadata"]["worker_session_guardrails"][
            "actual_happy_path_worker_sessions"
        ]
        == 2
    )


def test_knowledge_orchestrator_inline_json_style_reuses_workspace_without_resuming_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)
    pack_root, _run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(
        pack_root=pack_root,
        worker_count=1,
        knowledge_prompt_target_count=2,
    ).model_copy(
        update={
            "knowledge_codex_exec_style": "inline-json-v1",
        }
    )
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: build_structural_pipeline_output(
            "recipe.knowledge.packet.v1",
            dict(payload or {}),
        )
    )

    fixture = _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=runner,
        settings=settings,
    )
    worker_root = Path(fixture["worker_root"])
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))
    lineage_path = next(worker_root.rglob("session_lineage.json"))
    lineage_payload = json.loads(lineage_path.read_text(encoding="utf-8"))

    assert len(runner.calls) == 4
    assert [call["mode"] for call in runner.calls].count("structured_prompt") == 4
    assert [call["mode"] for call in runner.calls].count("structured_prompt_resume") == 0
    assert [call["persist_session"] for call in runner.calls].count(True) == 0
    assert [call["resume_last"] for call in runner.calls].count(True) == 0
    assert len({call["execution_working_dir"] for call in runner.calls}) == 2
    assert lineage_payload["turn_count"] == 2
    assert lineage_payload["turns"][0]["turn_kind"] == "classification_initial"
    assert lineage_payload["turns"][1]["turn_kind"] == "grouping_1"
    assert worker_status["telemetry"]["summary"]["taskfile_session_count"] == 0
    assert worker_status["telemetry"]["summary"]["prompt_input_mode_counts"] == {
        "structured_session_classification_initial": 2,
        "structured_session_grouping": 2,
    }


def test_knowledge_orchestrator_inline_json_retries_classification_more_than_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)
    pack_root, _run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(
        pack_root=pack_root,
        worker_count=1,
        knowledge_prompt_target_count=1,
        knowledge_codex_exec_style="inline-json-v1",
    )
    runner = _MultiRepairClassificationInlineRunner()

    fixture = _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=runner,
        settings=settings,
        block_texts=["Knowledge zero."],
        spans=[knowledge_span(0)],
    )
    phase_dir = Path(fixture["phase_dir"])
    worker_root = Path(fixture["worker_root"])
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))
    proposal = json.loads(
        (phase_dir / "proposals" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )

    assert runner.classification_repair_call_count == 2
    assert proposal["payload"] is not None
    assert proposal["validation_errors"] == []
    assert worker_status["telemetry"]["summary"]["prompt_input_mode_counts"] == {
        "structured_session_classification_initial": 1,
        "structured_session_classification_repair": 2,
        "structured_session_grouping": 1,
    }
    assert worker_status["telemetry"]["summary"]["structured_repair_followup_call_count"] == 2


def test_knowledge_orchestrator_inline_json_retries_grouping_more_than_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)
    pack_root, _run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(
        pack_root=pack_root,
        worker_count=1,
        knowledge_prompt_target_count=1,
        knowledge_codex_exec_style="inline-json-v1",
    )
    runner = _MultiRepairGroupingInlineRunner()

    fixture = _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=runner,
        settings=settings,
        block_texts=["Knowledge zero."],
        spans=[knowledge_span(0)],
    )
    phase_dir = Path(fixture["phase_dir"])
    worker_root = Path(fixture["worker_root"])
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))
    proposal = json.loads(
        (phase_dir / "proposals" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )

    assert runner.grouping_repair_call_count == 2
    assert proposal["payload"] is not None
    assert proposal["validation_errors"] == []
    assert worker_status["telemetry"]["summary"]["prompt_input_mode_counts"] == {
        "structured_session_classification_initial": 1,
        "structured_session_grouping": 1,
        "structured_session_grouping_repair": 2,
    }


def test_knowledge_orchestrator_inline_json_populates_top_level_telemetry_and_survivability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)
    pack_root, _run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(
        pack_root=pack_root,
        worker_count=1,
        knowledge_prompt_target_count=2,
        knowledge_codex_exec_style="inline-json-v1",
    )
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: build_structural_pipeline_output(
            "recipe.knowledge.packet.v1",
            dict(payload or {}),
        )
    )

    fixture = _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=runner,
        settings=settings,
    )
    phase_dir = Path(fixture["phase_dir"])
    telemetry = json.loads((phase_dir / "telemetry.json").read_text(encoding="utf-8"))
    survivability_report = json.loads(
        (phase_dir / "shard_survivability_report.json").read_text(encoding="utf-8")
    )

    assert telemetry["rows"]
    assert telemetry["summary"]["call_count"] == len(telemetry["rows"])
    assert telemetry["summary"]["tokens_total"] > 0
    assert all(row["task_id"].startswith("book.ks000") for row in telemetry["rows"])
    assert (
        survivability_report["shards"][0]["observed"]["token_usage_status"] == "complete"
    )
    assert survivability_report["shards"][0]["observed"]["total_billed_tokens"] > 0


def test_knowledge_orchestrator_inline_json_updates_task_status_and_stage_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)
    pack_root, _run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(
        pack_root=pack_root,
        worker_count=1,
        knowledge_prompt_target_count=1,
        knowledge_codex_exec_style="inline-json-v1",
    )
    runner = FakeCodexExecRunner(
        output_builder=lambda payload: build_structural_pipeline_output(
            "recipe.knowledge.packet.v1",
            dict(payload or {}),
        )
    )

    fixture = _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=runner,
        settings=settings,
        block_texts=["Knowledge zero."],
        spans=[knowledge_span(0)],
    )
    phase_dir = Path(fixture["phase_dir"])
    task_status_rows = [
        json.loads(line)
        for line in (phase_dir / "task_status.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    telemetry = json.loads((phase_dir / "telemetry.json").read_text(encoding="utf-8"))
    stage_status = json.loads((phase_dir / "stage_status.json").read_text(encoding="utf-8"))
    summary = summarize_knowledge_stage_artifacts(phase_dir)

    assert len(task_status_rows) == 1
    assert task_status_rows[0]["state"] == "validated"
    assert task_status_rows[0]["terminal"] is True
    assert task_status_rows[0]["proposal_status"] == "validated"
    assert telemetry["summary"]["packet_economics"]["packet_count_total"] == 2
    assert telemetry["summary"]["packet_economics"]["owned_row_count_total"] == 1
    assert telemetry["summary"]["packet_economics"]["classification_step_count_total"] == 1
    assert telemetry["summary"]["packet_economics"]["grouping_step_count_total"] == 1
    assert (
        telemetry["summary"]["packet_economics"]["classification_validation_count_total"]
        == 1
    )
    assert (
        telemetry["summary"]["packet_economics"]["grouping_validation_count_total"] == 1
    )
    assert stage_status["pre_kill_failure_counts"]["task_terminal_states"] == {}
    assert summary["pre_kill_failures_observed"] is False
    assert summary["packets"]["state_counts"] == {"validated": 1}
    assert summary["packets"]["topline"]["validated"] == 1
    assert summary["attention_summary"]["context_counts"]["validated_packet_count"] == 1
    assert summary["attention_summary"]["context_counts"]["owned_row_count_total"] == 1


def test_knowledge_orchestrator_replaces_hard_boundary_failure_with_fresh_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _FreshSessionKnowledgeRunner(hard_boundary=True)
    fixture = _run_runtime_phase(monkeypatch, tmp_path, runner=runner)
    worker_root = Path(fixture["worker_root"])
    phase_dir = Path(fixture["phase_dir"])
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))
    phase_manifest = json.loads((phase_dir / "phase_manifest.json").read_text(encoding="utf-8"))

    assert runner.workspace_run_calls == 2
    assert worker_status["fresh_worker_replacement_count"] == 1
    assert worker_status["fresh_worker_replacement_status"] == "recovered"
    assert worker_status["fresh_session_retry_count"] == 0
    assert worker_status["telemetry"]["summary"]["taskfile_session_count"] == 2
    assert (
        phase_manifest["runtime_metadata"]["worker_session_guardrails"][
            "actual_happy_path_worker_sessions"
        ]
        == 2
    )


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

    def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
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
            workspace_mode="taskfile",
            supervision_state=self._supervision_state,
            supervision_reason_code=self._supervision_reason_code,
        )


class _FreshSessionKnowledgeRunner(FakeCodexExecRunner):
    def __init__(self, *, hard_boundary: bool = False) -> None:
        super().__init__(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.packet.v1",
                dict(payload or {}),
            )
        )
        self.workspace_run_calls = 0
        self.hard_boundary = hard_boundary

    def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.workspace_run_calls += 1
        working_dir = Path(kwargs.get("working_dir"))
        if self.workspace_run_calls == 1:
            task_file = load_task_file(working_dir / "task.json")
            edited = deepcopy(task_file)
            for unit in edited["units"]:
                unit["answer"] = {
                    "category": "knowledge",
                    "grounding": {
                        "tag_keys": [],
                        "category_keys": [],
                        "proposed_tags": [
                            {
                                "key": "recovered-concept",
                                "display_name": "Recovered concept",
                                "category_key": "techniques",
                            }
                        ],
                    },
                }
            write_task_file(path=working_dir / "task.json", payload=edited)
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=None,
                prompt_text=str(kwargs.get("prompt_text") or ""),
                response_text='{"status":"session_exhausted"}',
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
                workspace_mode="taskfile",
                supervision_state="watchdog_killed" if self.hard_boundary else "completed",
                supervision_reason_code=(
                    "watchdog_command_execution_forbidden" if self.hard_boundary else None
                ),
            )
        return super().run_taskfile_worker(*args, **kwargs)


def _packet_result_from_base(
    base_result: CodexExecRunResult,
    *,
    response_text: str,
) -> CodexExecRunResult:
    usage = {
        "input_tokens": max(1, len(base_result.prompt_text) // 4),
        "cached_input_tokens": 0,
        "output_tokens": max(1, len(response_text) // 4),
        "reasoning_tokens": 0,
    }
    events = (
        {"type": "thread.started"},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": response_text},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": usage["input_tokens"],
                "cached_input_tokens": usage["cached_input_tokens"],
                "output_tokens": usage["output_tokens"],
                "reasoning_tokens": usage["reasoning_tokens"],
            },
        },
    )
    return CodexExecRunResult(
        command=base_result.command,
        subprocess_exit_code=base_result.subprocess_exit_code,
        output_schema_path=base_result.output_schema_path,
        prompt_text=base_result.prompt_text,
        response_text=response_text,
        turn_failed_message=None,
        events=events,
        usage=usage,
        stdout_text="\n".join(json.dumps(event) for event in events) + "\n",
        stderr_text=base_result.stderr_text,
        source_working_dir=base_result.source_working_dir,
        execution_working_dir=base_result.execution_working_dir,
        execution_agents_path=base_result.execution_agents_path,
        duration_ms=base_result.duration_ms,
        started_at_utc=base_result.started_at_utc,
        finished_at_utc=base_result.finished_at_utc,
        workspace_mode=base_result.workspace_mode,
        supervision_state=base_result.supervision_state,
        supervision_reason_code=base_result.supervision_reason_code,
        supervision_reason_detail=base_result.supervision_reason_detail,
        supervision_retryable=base_result.supervision_retryable,
    )


def _structured_classification_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    return [
        {
            "row_id": str(block.get("row_id") or ""),
            "category": "knowledge",
            "grounding": {
                "tag_keys": [],
                "category_keys": ["techniques"],
                "proposed_tags": [
                    {
                        "key": "heat-control",
                        "display_name": "Heat control",
                        "category_key": "techniques",
                    }
                ],
            },
        }
        for block in (payload.get("rows") or [])
        if isinstance(block, dict)
    ]


def _structured_grouping_rows(
    payload: dict[str, object],
    *,
    topic_label: str,
) -> list[dict[str, object]]:
    return [
        {
            "row_id": str(block.get("row_id") or ""),
            "group_key": "heat-control",
            "topic_label": topic_label,
        }
        for block in (payload.get("rows") or [])
        if isinstance(block, dict)
    ]


class _MultiRepairClassificationInlineRunner(FakeCodexExecRunner):
    def __init__(self) -> None:
        super().__init__(output_builder=lambda payload: {})
        self.classification_repair_call_count = 0

    def run_packet_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
        base_result = super().run_packet_worker(*args, **kwargs)
        payload = dict(kwargs.get("input_payload") or {})
        packet_kind = str(payload.get("packet_kind") or "").strip()
        stage_key = str(payload.get("stage_key") or "").strip()
        if stage_key == "nonrecipe_classify" and packet_kind == "classification_initial":
            return _packet_result_from_base(
                base_result,
                response_text='{"rows":[{"block_index":0,"category":"knowledge"',
            )
        if stage_key == "nonrecipe_classify" and packet_kind == "classification_repair":
            self.classification_repair_call_count += 1
            if self.classification_repair_call_count == 1:
                return _packet_result_from_base(
                    base_result,
                    response_text='{"rows":[{"block_index":0,"category":"knowledge"',
                )
            return _packet_result_from_base(
                base_result,
                response_text=json.dumps(
                    {"rows": _structured_classification_rows(payload)},
                    indent=2,
                    sort_keys=True,
                ),
            )
        if stage_key == "knowledge_group":
            return _packet_result_from_base(
                base_result,
                response_text=json.dumps(
                    {"rows": _structured_grouping_rows(payload, topic_label="Heat control")},
                    indent=2,
                    sort_keys=True,
                ),
            )
        return base_result


class _MultiRepairGroupingInlineRunner(FakeCodexExecRunner):
    def __init__(self) -> None:
        super().__init__(output_builder=lambda payload: {})
        self.grouping_repair_call_count = 0

    def run_packet_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
        base_result = super().run_packet_worker(*args, **kwargs)
        payload = dict(kwargs.get("input_payload") or {})
        packet_kind = str(payload.get("packet_kind") or "").strip()
        stage_key = str(payload.get("stage_key") or "").strip()
        if stage_key == "nonrecipe_classify":
            return _packet_result_from_base(
                base_result,
                response_text=json.dumps(
                    {"rows": _structured_classification_rows(payload)},
                    indent=2,
                    sort_keys=True,
                ),
            )
        if stage_key == "knowledge_group" and packet_kind == "grouping_1":
            return _packet_result_from_base(
                base_result,
                response_text=json.dumps(
                    {"rows": _structured_grouping_rows(payload, topic_label="")},
                    indent=2,
                    sort_keys=True,
                ),
            )
        if stage_key == "knowledge_group" and packet_kind == "grouping_1_repair":
            self.grouping_repair_call_count += 1
            if self.grouping_repair_call_count == 1:
                return _packet_result_from_base(
                    base_result,
                    response_text=json.dumps(
                        {"rows": _structured_grouping_rows(payload, topic_label="")},
                        indent=2,
                        sort_keys=True,
                    ),
                )
            return _packet_result_from_base(
                base_result,
                response_text=json.dumps(
                    {"rows": _structured_grouping_rows(payload, topic_label="Heat control")},
                    indent=2,
                    sort_keys=True,
                ),
            )
        return base_result


def _load_task_status_rows(path: Path) -> dict[str, dict[str, object]]:
    return {
        payload["task_id"]: payload
        for payload in (
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


def test_knowledge_orchestrator_classifies_clean_exit_without_assignment_output(
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
    live_status = json.loads((worker_root / "live_status.json").read_text(encoding="utf-8"))

    assert task_rows["book.ks0000.nr"]["state"] == "no_final_output"
    assert (
        task_rows["book.ks0000.nr"]["terminal_reason_code"]
        == "same_session_handoff_incomplete"
    )
    assert proposal["validation_metadata"]["terminal_reason_code"] == (
        "same_session_handoff_incomplete"
    )
    assert summary["packets"]["no_final_output_reason_code_counts"] == {
        "same_session_handoff_incomplete": 2,
    }
    assert summary["attention_summary"]["zero_target_counts"]["no_final_output_shard_count"] == 2
    assert not (worker_root / "packet_lease_status.json").exists()
    assert live_status["state"] == "completed"
    assert live_status["reason_code"] == "process_exited_without_watchdog_intervention"


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
    handoff_state = json.loads(
        (worker_root / "_repo_control" / "knowledge_same_session_state.json").read_text(
            encoding="utf-8"
        )
    )

    assert task_rows["book.ks0000.nr"]["state"] == "no_final_output"
    assert task_rows["book.ks0000.nr"]["terminal_reason_code"] == "same_session_handoff_incomplete"
    assert "same-session knowledge handoff" in str(
        task_rows["book.ks0000.nr"]["terminal_reason_detail"]
    )
    assert summary["packets"]["no_final_output_reason_code_counts"] == {
        "same_session_handoff_incomplete": 2
    }
    assert summary["attention_summary"]["zero_target_counts"]["no_final_output_shard_count"] == 2
    assert handoff_state["same_session_repair_rewrite_count"] == 1
    assert handoff_state["current_stage_key"] == "nonrecipe_classify"
    assert json.loads((worker_root / "task.json").read_text(encoding="utf-8"))["stage_key"] == (
        "nonrecipe_classify"
    )


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
