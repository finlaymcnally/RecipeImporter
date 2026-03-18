from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from cookimport.config.run_settings import RunSettings
from cookimport.core.progress_messages import parse_stage_progress
from cookimport.core.models import ChunkLane, ConversionReport, ConversionResult, KnowledgeChunk, RawArtifact
from cookimport.llm.codex_farm_knowledge_orchestrator import run_codex_farm_knowledge_harvest
from cookimport.llm.codex_exec_runner import FakeCodexExecRunner
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.llm.fake_codex_farm_runner import build_structural_pipeline_output
from cookimport.parsing.label_source_of_truth import RecipeSpan
from cookimport.staging.nonrecipe_stage import NonRecipeSpan, NonRecipeStageResult


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
    apply_result = run_codex_farm_knowledge_harvest(
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
    assert apply_result.refined_stage_result.block_category_by_index[4] == "knowledge"
    assert apply_result.manifest_path.exists()
    manifest = json.loads(apply_result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"]["jobs_written"] > 0
    assert manifest["counts"]["shards_written"] == manifest["counts"]["jobs_written"]
    assert manifest["counts"]["chunks_written"] >= manifest["counts"]["jobs_written"]
    assert manifest["stage_status"] == "completed"

    knowledge_dir = run_root / "knowledge" / "book"
    assert (knowledge_dir / "snippets.jsonl").exists()
    assert (knowledge_dir / "knowledge.md").exists()
    phase_dir = run_root / "raw" / "llm" / "book" / "knowledge"
    assert (phase_dir / "phase_manifest.json").exists()
    assert (phase_dir / "shard_manifest.jsonl").exists()
    assert (phase_dir / "worker_assignments.json").exists()


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
    run_codex_farm_knowledge_harvest(
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
    assert payloads[0]["stage_label"] == "knowledge harvest"
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
        def run_structured_prompt(self, *args, **kwargs):  # noqa: ANN002, ANN003
            with lock:
                state["current"] += 1
                state["max"] = max(state["max"], state["current"])
            barrier.wait(timeout=1.0)
            time.sleep(0.05)
            try:
                return super().run_structured_prompt(*args, **kwargs)
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

    apply_result = run_codex_farm_knowledge_harvest(
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

    apply_result = run_codex_farm_knowledge_harvest(
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
    assert apply_result.llm_report["counts"]["jobs_written"] == 0
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
                blockIds=[4],
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

    apply_result = run_codex_farm_knowledge_harvest(
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

    assert runner.calls == []
    assert apply_result.llm_report["stage_status"] == "all_chunks_skipped"
    assert apply_result.llm_report["counts"]["jobs_written"] == 0
    assert apply_result.llm_report["counts"]["shards_written"] == 0
    assert apply_result.llm_report["counts"]["chunks_written"] == 0
    assert apply_result.llm_report["counts"]["jobs_skipped"] == 1
    assert apply_result.llm_report["skipped_lane_counts"] == {"noise": 1}


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

    apply_result = run_codex_farm_knowledge_harvest(
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
            "bid": payload["bundle_id"],
            "r": [
                {
                    "cid": payload["chunks"][0]["chunk_id"],
                    "u": True,
                    "d": [{"i": 8, "c": "knowledge"}],
                    "s": [
                        {
                            "t": "Acid and browning",
                            "b": "Acid slows browning.",
                            "g": ["science"],
                            "e": [{"i": 8, "q": "acid slows browning"}],
                        }
                    ],
                }
            ],
        }
    )

    apply_result = run_codex_farm_knowledge_harvest(
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
    assert apply_result.llm_report["authority_mode"] == "knowledge_refined_final"
    assert apply_result.llm_report["scored_effect"] == "final_authority"


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
            "bid": payload["bundle_id"],
            "r": [
                {
                    "cid": payload["chunks"][0]["chunk_id"],
                    "u": True,
                    "d": [{"i": 99, "c": "knowledge"}],
                    "s": [
                        {
                            "t": "Bad pointer",
                            "b": "Invalid output.",
                            "g": ["invalid"],
                            "e": [{"i": 99, "q": "bad"}],
                        }
                    ],
                }
            ],
        }
    )

    apply_result = run_codex_farm_knowledge_harvest(
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
    assert apply_result.llm_report["counts"]["chunks_missing"] == 1
    assert apply_result.llm_report["missing_chunk_ids"] == ["book.c0000.nr"]
    assert apply_result.llm_report["stage_status"] == "completed_with_failures"
    assert apply_result.write_report is not None
    assert apply_result.write_report.snippets_written == 0


def test_knowledge_orchestrator_falls_back_when_phase_runtime_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FailingRunner:
        def run_structured_prompt(self, *args, **kwargs):  # noqa: ANN002, ANN003
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

    apply_result = run_codex_farm_knowledge_harvest(
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
