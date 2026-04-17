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
        else [
            "Whisk constantly to build the emulsion.",
            "Recipe gap.",
            "Control pan heat so the food browns without burning.",
        ]
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
    assert runner.initial_assigned_shard_ids == ["book.ks0000.nr"]
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
    assert not (worker_root / "current_packet.json").exists()
    assert not (worker_root / "current_hint.md").exists()
    assert not (worker_root / "current_result_path.txt").exists()
    assert classify_snapshot["stage_key"] == "nonrecipe_classify"
    assert classify_snapshot["answer_schema"]["editable_pointer_pattern"] == "/units/*/answer"
    assert "helper_commands" not in classify_snapshot
    assert "ontology" not in classify_snapshot
    assert classify_snapshot["answer_schema"]["example_answers"][0]["category"] == (
        "keep_for_review"
    )
    assert task_file["stage_key"] == "knowledge_group"
    assert "helper_commands" not in task_file
    assert task_file["answer_schema"]["editable_pointer_pattern"] == "/units/*/answer"
    assert task_file["answer_schema"]["example_answers"][0]["groups"][0]["group_id"] == "g01"
    assert first_output["packet_id"] == "book.ks0000.nr"
    assert [row["row_index"] for row in first_output["row_decisions"]] == [0, 2]
    assert all(row["category"] == "knowledge" for row in first_output["row_decisions"])
    assert all(
        row["grounding"]["tag_keys"] or row["grounding"]["proposed_tags"]
        for row in first_output["row_decisions"]
    )
    first_grounding = first_output["row_decisions"][0]["grounding"]
    first_group = first_output["row_groups"][0]
    assert first_group["group_id"] == "g01"
    assert first_group["row_indices"] == [0, 2]
    assert first_group["grounding"] == {
        "tag_keys": first_grounding["tag_keys"],
        "category_keys": first_grounding["category_keys"],
        "proposed_tags": first_grounding["proposed_tags"],
    }
    assert first_group["topic_label"]
    if first_grounding["proposed_tags"]:
        assert first_group["why_no_existing_tag"]
        assert first_group["retrieval_query"]
    else:
        assert first_group["why_no_existing_tag"] is None
        assert first_group["retrieval_query"] is None
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
        == 1
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


def test_knowledge_orchestrator_runs_grouping_for_kept_knowledge_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)
    pack_root, _run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(
        pack_root=pack_root,
        worker_count=1,
        knowledge_prompt_target_count=1,
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
        block_texts=["Whisk constantly to build the emulsion."],
        spans=[knowledge_span(0)],
    )
    phase_dir = Path(fixture["phase_dir"])
    worker_root = Path(fixture["worker_root"])
    output_payload = json.loads(
        (worker_root / "out" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )
    telemetry = json.loads((phase_dir / "telemetry.json").read_text(encoding="utf-8"))

    idea_group = output_payload["row_groups"][0]
    assert idea_group["row_indices"] == [0]
    assert idea_group["group_id"] == "g01"
    assert idea_group["topic_label"]
    assert idea_group["grounding"] == output_payload["row_decisions"][0]["grounding"]
    if output_payload["row_decisions"][0]["grounding"]["proposed_tags"]:
        assert idea_group["why_no_existing_tag"]
        assert idea_group["retrieval_query"]
    else:
        assert idea_group["why_no_existing_tag"] is None
        assert idea_group["retrieval_query"] is None
    assert telemetry["summary"]["packet_economics"]["grouping_step_count_total"] == 1
    assert telemetry["summary"]["packet_economics"]["grouping_validation_count_total"] == 1


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


def test_knowledge_orchestrator_inline_json_style_persists_workspace_for_possible_repair_resume(
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

    assert len(runner.calls) == 2
    assert [call["mode"] for call in runner.calls].count("structured_prompt") == 2
    assert [call["mode"] for call in runner.calls].count("structured_prompt_resume") == 0
    assert [call["persist_session"] for call in runner.calls].count(True) == 2
    assert [call["resume_last"] for call in runner.calls].count(True) == 0
    assert len({call["execution_working_dir"] for call in runner.calls}) == 1
    assert lineage_payload["turn_count"] == 2
    assert lineage_payload["turns"][0]["turn_kind"] == "classification_initial"
    assert lineage_payload["turns"][1]["turn_kind"] == "grouping_1"
    assert worker_status["telemetry"]["summary"]["taskfile_session_count"] == 0
    assert worker_status["telemetry"]["summary"]["prompt_input_mode_counts"] == {
        "structured_session_classification_initial": 1,
        "structured_session_grouping": 1,
    }


def test_knowledge_orchestrator_inline_json_repairs_resume_by_default(
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

    _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=runner,
        settings=settings,
        block_texts=["Knowledge zero."],
        spans=[knowledge_span(0)],
    )

    assert [call["mode"] for call in runner.calls] == [
        "structured_prompt",
        "structured_prompt",
        "structured_prompt_resume",
        "structured_prompt_resume",
    ]
    assert [call["resume_last"] for call in runner.calls] == [False, False, True, True]
    assert [call["persist_session"] for call in runner.calls] == [True, True, True, True]


def test_knowledge_orchestrator_inline_json_repairs_can_be_forced_fresh(
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
        knowledge_inline_repair_transcript_mode="fresh",
    )
    runner = _MultiRepairGroupingInlineRunner()

    _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=runner,
        settings=settings,
        block_texts=["Knowledge zero."],
        spans=[knowledge_span(0)],
    )

    assert [call["mode"] for call in runner.calls] == [
        "structured_prompt",
        "structured_prompt",
        "structured_prompt",
        "structured_prompt",
    ]
    assert [call["resume_last"] for call in runner.calls] == [False, False, False, False]
    assert [call["persist_session"] for call in runner.calls] == [False, False, False, False]


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
        block_texts=["Whisk constantly to build the emulsion."],
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


def test_knowledge_orchestrator_classification_missing_rows_repair_only_targets_unresolved_tail_rows(
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
    runner = _TailOnlyClassificationRepairInlineRunner()

    fixture = _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=runner,
        settings=settings,
        block_texts=[
            "Whisk constantly to build the emulsion.",
            "Use gentle heat to keep the pan steady.",
            "Rest the dough before rolling.",
        ],
        spans=[knowledge_span(0), knowledge_span(1), knowledge_span(2)],
    )
    phase_dir = Path(fixture["phase_dir"])
    worker_root = Path(fixture["worker_root"])
    proposal = json.loads(
        (phase_dir / "proposals" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )
    repair_packet = json.loads(
        (
            worker_root
            / "shards"
            / "book.ks0000.nr"
            / "structured_session"
            / "classification_repair_packet_01.json"
        ).read_text(encoding="utf-8")
    )

    assert runner.classification_repair_call_count == 1
    assert proposal["payload"] is not None
    assert repair_packet["repair_validation_summary"]["validation_errors"] == [
        "knowledge_row_missing_decision",
        "knowledge_missing_response_rows",
    ]
    assert repair_packet["repair_validation_summary"]["missing_row_ids"] == ["r03"]
    assert repair_packet["rows"] == [
        "r01 | 2 | Rest the dough before rolling.",
    ]


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


def test_knowledge_orchestrator_grouping_repairs_only_missing_rows_without_schema_files(
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
    runner = _PartialGroupingRepairInlineRunner()

    fixture = _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=runner,
        settings=settings,
        block_texts=[
            "Whisk constantly to build the emulsion.",
            "Keep the pan moving so the emulsion stays stable.",
            "Control pan heat so the food browns without burning.",
        ],
        spans=[knowledge_span(0), knowledge_span(1), knowledge_span(2)],
    )
    phase_dir = Path(fixture["phase_dir"])
    worker_root = Path(fixture["worker_root"])
    proposal = json.loads(
        (phase_dir / "proposals" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )

    assert proposal["payload"] is not None
    assert proposal["validation_errors"] == []
    call_modes = [call["mode"] for call in runner.calls]
    assert call_modes[:2] == ["structured_prompt", "structured_prompt"]
    assert call_modes[2:] == ["structured_prompt_resume", "structured_prompt_resume"]
    assert [call["output_schema_path"] for call in runner.calls] == [None] * len(runner.calls)
    assert not list(
        (
            worker_root / "shards" / "book.ks0000.nr" / "structured_session"
        ).glob("output_schema_*.json")
    )

    repair_packet = json.loads(
        (
            worker_root
            / "shards"
            / "book.ks0000.nr"
            / "structured_session"
            / "grouping_repair_packet_01_01.json"
        ).read_text(encoding="utf-8")
    )
    assert repair_packet["repair_validation_summary"]["missing_row_ids"] == ["r03"]
    assert repair_packet["ordered_rows"][-1] == (
        "r03 | 2 | Control pan heat so the food browns without burning."
    )


def test_knowledge_orchestrator_grouping_repairs_preserve_first_root_cause_summary(
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
    runner = _RootCausePreservingGroupingInlineRunner()

    fixture = _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=runner,
        settings=settings,
        block_texts=["Fold the dough gently after resting."],
        spans=[knowledge_span(0)],
    )
    phase_dir = Path(fixture["phase_dir"])
    worker_root = Path(fixture["worker_root"])
    proposal = json.loads(
        (phase_dir / "proposals" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )
    first_repair_packet = json.loads(
        (
            worker_root
            / "shards"
            / "book.ks0000.nr"
            / "structured_session"
            / "grouping_repair_packet_01_01.json"
        ).read_text(encoding="utf-8")
    )
    second_repair_packet = json.loads(
        (
            worker_root
            / "shards"
            / "book.ks0000.nr"
            / "structured_session"
            / "grouping_repair_packet_01_02.json"
        ).read_text(encoding="utf-8")
    )

    assert proposal["payload"] is not None
    assert proposal["validation_errors"] == []
    assert "unknown_grounding_category_key" in first_repair_packet[
        "repair_root_cause_summary"
    ]["validation_errors"]
    assert "proposed tag category_key must be an existing category key" in str(
        first_repair_packet["repair_root_cause_summary"]["message"]
    )
    assert second_repair_packet["repair_validation_summary"]["validation_errors"] == [
        "knowledge_row_missing_group"
    ]
    assert "unknown_grounding_category_key" in second_repair_packet[
        "repair_root_cause_summary"
    ]["validation_errors"]
    assert second_repair_packet["previous_groups"] == [
        {
            "start_row_id": "r01",
            "end_row_id": "r01",
            "row_ids": ["r01"],
            "validation_errors": ["knowledge_row_missing_group"],
            "error_details": [
                {
                    "path": "/units/knowledge::0/answer/group_id",
                    "code": "knowledge_row_missing_group",
                    "message": "group_id must be a non-empty string",
                },
                {
                    "path": "/units/knowledge::0/answer/topic_label",
                    "code": "knowledge_row_missing_group",
                    "message": "topic_label must be a non-empty string",
                }
            ],
            "group_id": "g01",
            "grounding": {
                "tag_keys": ["saute"],
                "category_keys": ["cooking-method"],
                "proposed_tags": [],
            },
        }
    ]


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
        block_texts=["Whisk constantly to build the emulsion."],
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
                unit["answer"] = {"category": "keep_for_review"}
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


def _structured_packet_row_id(row: object) -> str:
    if not isinstance(row, str):
        return ""
    return str(row.split(" | ", 1)[0] or "").strip()


def _structured_grouping_row_ids(payload: dict[str, object]) -> list[str]:
    ordered_rows = payload.get("ordered_rows")
    if not isinstance(ordered_rows, list):
        return [
            row_id
            for row in (payload.get("rows") or [])
            if (row_id := _structured_packet_row_id(row))
        ]
    row_ids: list[str] = []
    for row in ordered_rows:
        row_id = _structured_packet_row_id(row)
        if not row_id or row_id.startswith("ctx"):
            continue
        row_ids.append(row_id)
    return row_ids


def _structured_grouping_repair_target_row_ids(payload: dict[str, object]) -> list[str]:
    repair_summary = payload.get("repair_validation_summary")
    if isinstance(repair_summary, dict):
        missing_row_ids = [
            str(row_id).strip()
            for row_id in (repair_summary.get("missing_row_ids") or [])
            if str(row_id).strip()
        ]
        if missing_row_ids:
            return missing_row_ids
    return _structured_grouping_row_ids(payload)


def _structured_packet_grouping_categories(
    payload: dict[str, object],
) -> dict[str, str]:
    categories_by_row_id: dict[str, str] = {}
    for row_fact in payload.get("row_facts") or []:
        if not isinstance(row_fact, str):
            continue
        parts = [part.strip() for part in row_fact.split(" | ") if part.strip()]
        if len(parts) < 2:
            continue
        row_id = str(parts[0] or "").strip()
        if not row_id:
            continue
        for part in parts[1:]:
            if not part.startswith("classification="):
                continue
            categories_by_row_id[row_id] = str(
                part.removeprefix("classification=") or ""
            ).strip()
            break
    return categories_by_row_id


def _structured_classification_rows(payload: dict[str, object]) -> list[dict[str, str]]:
    return [
        {
            "row_id": row_id,
            "category": "keep_for_review",
        }
        for row in (payload.get("rows") or [])
        if (row_id := _structured_packet_row_id(row))
    ]


def _structured_grouping_groups(
    payload: dict[str, object],
    *,
    topic_label: str,
) -> list[dict[str, object]]:
    row_ids = _structured_grouping_row_ids(payload)
    if not row_ids:
        return []
    return [
        {
            "group_id": "g01",
            "start_row_id": row_ids[0],
            "end_row_id": row_ids[-1],
            "topic_label": topic_label,
            "grounding": {
                "tag_keys": ["saute"],
                "category_keys": ["cooking-method"],
                "proposed_tags": [],
            },
            "why_no_existing_tag": None,
            "retrieval_query": None,
        }
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
                response_text='{"rows":[{"row_index":0,"category":"knowledge"',
            )
        if stage_key == "nonrecipe_classify" and packet_kind == "classification_repair":
            self.classification_repair_call_count += 1
            if self.classification_repair_call_count == 1:
                return _packet_result_from_base(
                    base_result,
                    response_text='{"rows":[{"row_index":0,"category":"knowledge"',
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
                    {"groups": _structured_grouping_groups(payload, topic_label="Heat control")},
                    indent=2,
                    sort_keys=True,
                ),
            )
        return base_result


class _TailOnlyClassificationRepairInlineRunner(FakeCodexExecRunner):
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
                response_text=json.dumps(
                    {
                        "rows": [
                            {"row_id": "r01", "category": "keep_for_review"},
                            {"row_id": "r02", "category": "keep_for_review"},
                        ]
                    },
                    indent=2,
                    sort_keys=True,
                ),
            )
        if stage_key == "nonrecipe_classify" and packet_kind == "classification_repair":
            self.classification_repair_call_count += 1
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
                    {"groups": _structured_grouping_groups(payload, topic_label="Heat control")},
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
                    {"groups": _structured_grouping_groups(payload, topic_label="")},
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
                        {"groups": _structured_grouping_groups(payload, topic_label="")},
                        indent=2,
                        sort_keys=True,
                    ),
                )
            return _packet_result_from_base(
                base_result,
                response_text=json.dumps(
                    {"groups": _structured_grouping_groups(payload, topic_label="Heat control")},
                    indent=2,
                    sort_keys=True,
                ),
            )
        return base_result


class _RootCausePreservingGroupingInlineRunner(FakeCodexExecRunner):
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
            row_ids = _structured_grouping_row_ids(payload)
            return _packet_result_from_base(
                base_result,
                response_text=json.dumps(
                    {
                        "groups": [
                            {
                                "group_id": "g01",
                                "start_row_id": row_ids[0],
                                "end_row_id": row_ids[-1],
                                "topic_label": "Dough resting",
                                "grounding": {
                                    "tag_keys": [],
                                    "category_keys": ["techniques"],
                                    "proposed_tags": [
                                        {
                                            "key": "dough-resting",
                                            "display_name": "Dough resting",
                                            "category_key": "not-a-real-category",
                                        }
                                    ],
                                },
                                "why_no_existing_tag": (
                                    "No existing tag covers the rest-before-folding concept."
                                ),
                                "retrieval_query": "rest dough before folding",
                            }
                        ]
                    },
                    indent=2,
                    sort_keys=True,
                ),
            )
        if stage_key == "knowledge_group" and packet_kind == "grouping_1_repair":
            self.grouping_repair_call_count += 1
            row_ids = _structured_grouping_repair_target_row_ids(payload)
            if self.grouping_repair_call_count == 1:
                return _packet_result_from_base(
                    base_result,
                    response_text=json.dumps(
                        {
                            "groups": [
                                {
                                    "group_id": "g01",
                                    "start_row_id": row_ids[0],
                                    "end_row_id": row_ids[-1],
                                    "topic_label": "",
                                    "grounding": {
                                        "tag_keys": ["saute"],
                                        "category_keys": ["cooking-method"],
                                        "proposed_tags": [],
                                    },
                                    "why_no_existing_tag": None,
                                    "retrieval_query": None,
                                }
                            ]
                        },
                        indent=2,
                        sort_keys=True,
                    ),
                )
            return _packet_result_from_base(
                base_result,
                response_text=json.dumps(
                    {
                        "groups": [
                            {
                                "group_id": "g01",
                                "start_row_id": row_ids[0],
                                "end_row_id": row_ids[-1],
                                "topic_label": "Dough resting",
                                "grounding": {
                                    "tag_keys": [],
                                    "category_keys": ["techniques"],
                                    "proposed_tags": [
                                        {
                                            "key": "dough-resting",
                                            "display_name": "Dough resting",
                                            "category_key": "techniques",
                                        }
                                    ],
                                },
                                "why_no_existing_tag": (
                                    "No existing tag covers the rest-before-folding concept."
                                ),
                                "retrieval_query": "rest dough before folding",
                            }
                        ]
                    },
                    indent=2,
                    sort_keys=True,
                ),
            )
        return base_result


class _PartialGroupingRepairInlineRunner(FakeCodexExecRunner):
    def __init__(self) -> None:
        super().__init__(output_builder=lambda payload: {})

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
            grouping_groups = _structured_grouping_groups(payload, topic_label="Heat control")
            return _packet_result_from_base(
                base_result,
                response_text=json.dumps(
                    {"groups": [] if not grouping_groups else [{
                        **grouping_groups[0],
                        "end_row_id": "r02",
                    }]},
                    indent=2,
                    sort_keys=True,
                ),
            )
        if stage_key == "knowledge_group" and packet_kind == "grouping_1_repair":
            return _packet_result_from_base(
                base_result,
                response_text=json.dumps(
                    {
                        "groups": _structured_grouping_groups(
                            {
                                **payload,
                                "ordered_rows": [
                                    row
                                    for row in (payload.get("ordered_rows") or [])
                                    if _structured_packet_row_id(row)
                                    in _structured_grouping_repair_target_row_ids(payload)
                                ],
                            },
                            topic_label="Heat control",
                        )
                    },
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
        "same_session_handoff_incomplete": 1,
    }
    assert summary["attention_summary"]["zero_target_counts"]["no_final_output_shard_count"] == 1
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
        "same_session_handoff_incomplete": 1
    }
    assert summary["attention_summary"]["zero_target_counts"]["no_final_output_shard_count"] == 1
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
        "watchdog_command_execution_forbidden": 1
    }
