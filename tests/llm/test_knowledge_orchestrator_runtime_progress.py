from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from cookimport.core.progress_messages import parse_stage_progress
from cookimport.llm.knowledge_stage import runtime as knowledge_module
from cookimport.llm.taskfile_progress import summarize_taskfile_health
from cookimport.llm.codex_exec_runner import (
    FakeCodexExecRunner,
)
from cookimport.llm.codex_farm_knowledge_orchestrator import (
    run_codex_farm_nonrecipe_finalize,
)
from cookimport.llm.fake_codex_farm_runner import build_structural_pipeline_output
from tests.llm.knowledge_packet_test_support import (
    configure_runtime_codex_home,
    knowledge_span,
    make_runtime_conversion_result,
    make_runtime_nonrecipe_stage_result,
    make_runtime_pack_and_run_dirs,
    make_runtime_recipe_ownership_result,
    make_runtime_settings,
)


def _run_live_shard_progress_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> list[dict[str, object]]:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)

    pack_root, run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(pack_root=pack_root, worker_count=1)
    progress_messages: list[str] = []
    run_codex_farm_nonrecipe_finalize(
        conversion_result=make_runtime_conversion_result(
            ["Knowledge zero.", "Recipe gap.", "Knowledge two."]
        ),
        nonrecipe_stage_result=make_runtime_nonrecipe_stage_result(
            spans=[knowledge_span(0), knowledge_span(2)]
        ),
        recipe_ownership_result=make_runtime_recipe_ownership_result(block_count=3),
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=FakeCodexExecRunner(
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


def test_knowledge_orchestrator_reports_live_shard_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payloads = _run_live_shard_progress_fixture(monkeypatch, tmp_path)

    assert payloads
    assert payloads[0]["task_current"] == 0
    assert payloads[0]["task_total"] == 2
    live_payloads = [
        payload
        for payload in payloads
        if int((payload.get("artifact_counts") or {}).get("shards_completed") or 0) == 1
    ]
    assert live_payloads
    assert payloads[-1]["task_current"] == 2
    assert payloads[-1]["task_total"] == 2


def test_knowledge_orchestrator_fails_closed_before_worker_launch_when_survivability_is_unsafe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)

    pack_root, run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(pack_root=pack_root, worker_count=1)
    runner = FakeCodexExecRunner(
        output_builder=lambda _payload: pytest.fail("worker should not start for unsafe shard plans")
    )
    unsafe_report = lambda **_kwargs: {
        "stage_label": "Nonrecipe Finalize",
        "requested_shard_count": 1,
        "minimum_safe_shard_count": 3,
        "binding_limit": "output",
        "survivability_verdict": "unsafe",
        "worst_shard": {"shard_id": "book.ks0000.nr"},
    }
    monkeypatch.setattr(
        knowledge_module,
        "_build_knowledge_shard_survivability_report",
        unsafe_report,
    )
    monkeypatch.setattr(
        "cookimport.llm.knowledge_stage._shared._build_knowledge_shard_survivability_report",
        unsafe_report,
    )
    monkeypatch.setitem(
        run_codex_farm_nonrecipe_finalize.__globals__,
        "_build_knowledge_shard_survivability_report",
        unsafe_report,
    )

    with pytest.raises(RuntimeError, match="minimum safe count is 3"):
        run_codex_farm_nonrecipe_finalize(
            conversion_result=make_runtime_conversion_result(
                ["Knowledge zero.", "Recipe gap.", "Knowledge two."]
            ),
            nonrecipe_stage_result=make_runtime_nonrecipe_stage_result(
                spans=[knowledge_span(0), knowledge_span(2)]
            ),
            recipe_ownership_result=make_runtime_recipe_ownership_result(block_count=3),
            run_settings=settings,
            run_root=run_root,
            workbook_slug="book",
            runner=runner,
        )

    assert runner.calls == []


def test_knowledge_orchestrator_progress_detail_lines_track_live_shards(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payloads = _run_live_shard_progress_fixture(monkeypatch, tmp_path)
    live_payloads = [
        payload
        for payload in payloads
        if int((payload.get("artifact_counts") or {}).get("shards_completed") or 0) == 1
    ]

    assert any(
        "book.ks0001.nr (2/2 shards)" in (payload.get("active_tasks") or [])
        for payload in live_payloads
    )
    assert any(
        "completed shards: 1/2" in (payload.get("detail_lines") or [])
        for payload in live_payloads
    )


def test_filtered_knowledge_planning_warnings_defer_budget_native_noise_when_safe() -> None:
    assert knowledge_module._filtered_knowledge_planning_warnings(
        planning_warnings=[
            (
                "knowledge_prompt_target_count is using the requested final shard count "
                "of 15; packet-budget planning would have split the queue into 37 shards."
            ),
            "another warning",
        ],
        requested_shard_count=15,
        survivability_report={"minimum_safe_shard_count": 5},
    ) == ["another warning"]


def test_filtered_knowledge_planning_warnings_keep_budget_native_warning_when_unsafe() -> None:
    assert knowledge_module._filtered_knowledge_planning_warnings(
        planning_warnings=[
            (
                "knowledge_prompt_target_count is using the requested final shard count "
                "of 5; packet-budget planning would have split the queue into 24 shards."
            )
        ],
        requested_shard_count=5,
        survivability_report={"minimum_safe_shard_count": 6},
    ) == [
        "knowledge_prompt_target_count is using the requested final shard count "
        "of 5; packet-budget planning would have split the queue into 24 shards."
    ]


def test_knowledge_orchestrator_surfaces_worker_attention_in_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)

    class WarningRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            supervision_callback = kwargs.get("supervision_callback")
            if callable(supervision_callback):
                supervision_callback(
                    knowledge_module.CodexExecLiveSnapshot(
                        elapsed_seconds=80.0,
                        last_event_seconds_ago=55.0,
                        event_count=9,
                        command_execution_count=301,
                        reasoning_item_count=0,
                        last_command="python3 helper.py",
                        last_command_repeat_count=21,
                        has_final_agent_message=False,
                        timeout_seconds=None,
                        live_activity_summary=(
                            "Reasoning summary: comparing heading context before final classification"
                        ),
                    )
                )
                time.sleep(1.2)
            return super().run_taskfile_worker(*args, **kwargs)

    pack_root, run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(pack_root=pack_root, worker_count=1)
    progress_messages: list[str] = []
    run_codex_farm_nonrecipe_finalize(
        conversion_result=make_runtime_conversion_result(
            ["Knowledge zero.", "Recipe gap.", "Knowledge two."]
        ),
        nonrecipe_stage_result=make_runtime_nonrecipe_stage_result(
            spans=[knowledge_span(0), knowledge_span(2)]
        ),
        recipe_ownership_result=make_runtime_recipe_ownership_result(block_count=3),
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=WarningRunner(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.packet.v1",
                dict(payload or {}),
            )
        ),
        progress_callback=progress_messages.append,
    )

    payloads = [
        payload
        for message in progress_messages
        for payload in [parse_stage_progress(message)]
        if payload is not None
    ]
    assert any(
        "watchdog warnings: 1" in (payload.get("detail_lines") or [])
        for payload in payloads
    )
    assert any(
        "stalled workers: 1" in (payload.get("detail_lines") or [])
        for payload in payloads
    )
    assert any(
        any(
            marker in str(task)
            for task in (payload.get("active_tasks") or [])
            for marker in ("[command loop]", "[shell drift]")
        )
        for payload in payloads
    )
    assert any(
        any(
            "Reasoning summary: comparing heading context before final classification"
            in str(task)
            for task in (payload.get("active_tasks") or [])
        )
        for payload in payloads
    )
    assert any(payload.get("last_activity_at") for payload in payloads)


def test_taskfile_progress_does_not_treat_inflight_final_message_as_missing_output(
    tmp_path: Path,
) -> None:
    worker_root = tmp_path / "worker-001"
    worker_root.mkdir(parents=True, exist_ok=True)
    (worker_root / "live_status.json").write_text(
        json.dumps(
            {
                "state": "running",
                "has_final_agent_message": True,
                "workspace_output_complete": False,
                "final_message_missing_output_deadline_reached": False,
                "last_event_seconds_ago": 2.0,
                "warning_codes": [],
                "warning_count": 0,
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_taskfile_health(
        worker_roots_by_id={"worker-001": worker_root}
    )

    assert summary.attention_suffix_by_worker_id == {}
    assert summary.attention_lines == ()


def test_taskfile_progress_surfaces_live_activity_summary(
    tmp_path: Path,
) -> None:
    worker_root = tmp_path / "worker-001"
    worker_root.mkdir(parents=True, exist_ok=True)
    (worker_root / "live_status.json").write_text(
        json.dumps(
            {
                "state": "running",
                "has_final_agent_message": False,
                "live_activity_summary": (
                    "Running `python3 -m cookimport.llm.editable_task_file --summary`"
                ),
                "last_event_seconds_ago": 2.0,
                "warning_codes": [],
                "warning_count": 0,
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_taskfile_health(
        worker_roots_by_id={"worker-001": worker_root}
    )

    assert summary.live_activity_summary_by_worker_id == {
        "worker-001": "Running `python3 -m cookimport.llm.editable_task_file --summary`"
    }


@pytest.mark.parametrize("state", ["completed", "completed_with_warnings"])
def test_taskfile_progress_requires_explicit_missing_output_failure_evidence(
    tmp_path: Path,
    state: str,
) -> None:
    worker_root = tmp_path / "worker-001"
    worker_root.mkdir(parents=True, exist_ok=True)
    (worker_root / "live_status.json").write_text(
        json.dumps(
            {
                "state": state,
                "has_final_agent_message": True,
                "workspace_output_complete": False,
                "final_message_missing_output_deadline_reached": False,
                "last_event_seconds_ago": 2.0,
                "warning_codes": [],
                "warning_count": 0,
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_taskfile_health(
        worker_roots_by_id={"worker-001": worker_root}
    )

    assert summary.attention_suffix_by_worker_id == {}
    assert summary.attention_lines == ()


def test_knowledge_orchestrator_runs_shard_workers_concurrently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    state = {"current": 0, "max": 0}

    class ConcurrentRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            with lock:
                state["current"] += 1
                state["max"] = max(state["max"], state["current"])
            barrier.wait(timeout=1.0)
            time.sleep(0.05)
            try:
                return super().run_taskfile_worker(*args, **kwargs)
            finally:
                with lock:
                    state["current"] -= 1

    pack_root, run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(pack_root=pack_root, worker_count=2)
    apply_result = run_codex_farm_nonrecipe_finalize(
        conversion_result=make_runtime_conversion_result(
            ["Knowledge zero.", "Recipe gap.", "Knowledge two."]
        ),
        nonrecipe_stage_result=make_runtime_nonrecipe_stage_result(
            spans=[knowledge_span(0), knowledge_span(2)]
        ),
        recipe_ownership_result=make_runtime_recipe_ownership_result(block_count=3),
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
    assert process_summary["taskfile_row_count"] == 2
    assert process_summary["taskfile_session_count"] == 2
    assert process_summary["prompt_input_mode_counts"]["taskfile"] == 2
    assert state["max"] >= 2


def test_knowledge_orchestrator_marks_invalid_post_validation_category_runtime_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)
    pack_root, run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(pack_root=pack_root, worker_count=1)

    def invalid_category_updates(**_kwargs):  # noqa: ANN003
        return ({0: "maybe"}, {}, [], [])

    monkeypatch.setattr(knowledge_module, "_collect_block_category_updates", invalid_category_updates)
    monkeypatch.setitem(
        run_codex_farm_nonrecipe_finalize.__globals__,
        "_collect_block_category_updates",
        invalid_category_updates,
    )

    apply_result = run_codex_farm_nonrecipe_finalize(
        conversion_result=make_runtime_conversion_result(["Knowledge zero."]),
        nonrecipe_stage_result=make_runtime_nonrecipe_stage_result(
            spans=[knowledge_span(0)]
        ),
        recipe_ownership_result=make_runtime_recipe_ownership_result(block_count=1),
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=FakeCodexExecRunner(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.packet.v1",
                dict(payload or {}),
            )
        ),
    )

    assert apply_result.llm_report["stage_status"] == "runtime_failed"
    assert "post_validation_finalize_failed" in str(apply_result.llm_report["error"])
    phase_dir = apply_result.llm_raw_dir / "nonrecipe_finalize"
    stage_status = json.loads((phase_dir / "stage_status.json").read_text(encoding="utf-8"))
    assert stage_status["stage_state"] == "runtime_failed"
    assert stage_status["termination_cause"] == "post_validation_finalize_error"
