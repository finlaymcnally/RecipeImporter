from __future__ import annotations

import json
import re
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
    run_codex_farm_nonrecipe_knowledge_review,
)
from cookimport.llm.codex_exec_runner import CodexExecLiveSnapshot, FakeCodexExecRunner
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.llm.fake_codex_farm_runner import build_structural_pipeline_output
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1
from cookimport.parsing.label_source_of_truth import RecipeSpan
from cookimport.staging.nonrecipe_stage import NonRecipeSpan, NonRecipeStageResult


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
    assert live_status["last_command_policy"] == "tolerated_workspace_helper_command"
    assert live_status["last_command_policy_allowed"] is True


def test_knowledge_orchestrator_writes_manifest_and_artifacts(tmp_path: Path) -> None:
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
    phase_dir = run_root / "raw" / "llm" / "book" / "knowledge"
    assert (phase_dir / "phase_manifest.json").exists()
    assert (phase_dir / "shard_manifest.jsonl").exists()
    assert (phase_dir / "worker_assignments.json").exists()
    worker_root = phase_dir / "workers" / "worker-001"
    worker_prompt = (worker_root / "prompt.txt").read_text(encoding="utf-8")
    assert "worker_manifest.json" in worker_prompt
    assert "If you need a helper command, keep it narrow and workspace-local" in worker_prompt
    assert "Do not use exploration commands such as `find`, `tree`" in worker_prompt
    worker_manifest = json.loads(
        (worker_root / "worker_manifest.json").read_text(encoding="utf-8")
    )
    assert worker_manifest["entry_files"] == ["worker_manifest.json", "assigned_shards.json"]


def test_knowledge_orchestrator_repairs_near_miss_invalid_shards_once(
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
    assert process_summary["invalid_output_shard_count"] == 1
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


def test_knowledge_orchestrator_marks_watchdog_killed_shards_in_summary(
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
    assert status_payload["status"] == "missing_output"
    assert status_payload["state"] == "watchdog_killed"
    assert status_payload["reason_code"] == "watchdog_command_execution_forbidden"

    live_status_path = status_path.with_name("live_status.json")
    live_status_payload = json.loads(live_status_path.read_text(encoding="utf-8"))
    assert live_status_payload["state"] == "watchdog_killed"
    assert live_status_payload["reason_code"] == "watchdog_command_execution_forbidden"
    assert live_status_payload["retryable"] is True
    assert apply_result.llm_report["review_status"] == "unreviewed"
    assert apply_result.llm_report["counts"]["unreviewed_shard_count"] == 1
    assert apply_result.llm_report["counts"]["missing_output_shards"] == 1


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
            chunk_rows.append(
                {
                    "cid": chunk_id,
                    "u": True,
                    "d": [{"i": block_index, "c": "knowledge"}],
                    "s": [
                        {
                            "b": f"Knowledge note: {block_text}",
                            "e": [{"i": block_index, "q": block_text}],
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
                                "b": f"Knowledge note for {chunk_id}",
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


def test_knowledge_orchestrator_retries_missing_rows_with_single_chunk_retry_shards(
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
        if ".retry" not in bundle_id:
            first_chunk = chunks[0]
            first_block = first_chunk["b"][0]
            return {
                "v": "2",
                "bid": bundle_id,
                "r": [
                    {
                        "cid": first_chunk["cid"],
                        "u": False,
                        "d": [{"i": first_block["i"], "c": "other", "rc": "other"}],
                        "s": [],
                    }
                ],
            }
        chunk = chunks[0]
        block = chunk["b"][0]
        return {
            "v": "2",
            "bid": bundle_id,
            "r": [
                {
                    "cid": chunk["cid"],
                    "u": True,
                    "d": [{"i": block["i"], "c": "knowledge", "rc": "knowledge"}],
                    "s": [{"b": block["t"], "e": [{"i": block["i"], "q": block["t"]}]}],
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
    assert process_summary["call_count"] == 3
    assert process_summary["invalid_output_shard_count"] == 1
    assert process_summary["repaired_shard_count"] == 0
    assert process_summary["workspace_worker_session_count"] == 1
    assert process_summary["structured_followup_call_count"] == 2
    assert process_summary["prompt_input_mode_counts"] == {
        "inline_retry": 2,
        "workspace_worker": 1,
    }

    proposals_dir = run_root / "raw" / "llm" / "book" / "knowledge" / "proposals"
    proposal = json.loads((proposals_dir / "book.ks0000.nr.json").read_text(encoding="utf-8"))
    assert proposal["validation_errors"] == []
    assert proposal["retry_attempted"] is True
    assert proposal["retry_status"] == "recovered"
    assert proposal["repair_attempted"] is False
    assert proposal["payload"]["bid"] == "book.ks0000.nr"
    assert [row["cid"] for row in proposal["payload"]["r"]] == [
        "book.c0000.nr",
        "book.c0001.nr",
    ]


def test_knowledge_orchestrator_emits_structured_progress_snapshots(tmp_path: Path) -> None:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 2,
            "knowledge_worker_count": 4,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
            "codex_farm_knowledge_context_blocks": 1,
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

    progress_messages: list[str] = []
    run_codex_farm_nonrecipe_knowledge_review(
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
        runner=FakeCodexExecRunner(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.compact.v1",
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
    assert payloads
    assert payloads[0]["stage_label"] == "non-recipe knowledge review"
    assert payloads[0]["task_current"] == 0
    assert payloads[0]["task_total"] >= 1
    assert int(payloads[0]["worker_total"] or 0) >= 1
    assert any(
        any(line.startswith("configured workers: ") for line in (payload.get("detail_lines") or []))
        for payload in payloads
    )
    assert payloads[-1]["task_current"] == payloads[-1]["task_total"]


def test_knowledge_orchestrator_runs_worker_assignments_concurrently(
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
            KnowledgeChunk(
                id="chunk-3",
                lane=ChunkLane.KNOWLEDGE,
                title="Heat",
                text="Control the pan temperature carefully.",
                blockIds=[3],
            ),
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    barrier = threading.Barrier(2)
    lock = threading.Lock()
    state = {"current": 0, "max": 0}

    class _ConcurrentRunner(FakeCodexExecRunner):
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

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 2,
            "knowledge_worker_count": 2,
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
                        {"index": 3, "text": "Control the pan temperature carefully."},
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
        runner=_ConcurrentRunner(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.compact.v1",
                dict(payload or {}),
            )
        ),
    )

    assert apply_result.llm_report["phase_worker_runtime"]["shard_count"] == 2
    assert apply_result.llm_report["phase_worker_runtime"]["worker_count"] == 2
    assert state["max"] >= 2


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

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 2,
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

    assert apply_result.llm_report["phase_worker_runtime"]["shard_count"] == 2
    assert apply_result.llm_report["phase_worker_runtime"]["worker_count"] == 2


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
            if payload["bid"] == "book.ks0000.nr"
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
