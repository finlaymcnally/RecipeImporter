from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from cookimport.core.progress_messages import parse_stage_progress
from cookimport.llm.codex_exec_runner import (
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


def _run_live_shard_progress_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> list[dict[str, object]]:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)

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
        "book.ks0001.nr (2/2 tasks)" in (payload.get("active_tasks") or [])
        for payload in live_payloads
    )
    assert any(
        "completed shards: 1/2" in (payload.get("detail_lines") or [])
        for payload in live_payloads
    )


def test_knowledge_orchestrator_runs_shard_workers_concurrently(
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
