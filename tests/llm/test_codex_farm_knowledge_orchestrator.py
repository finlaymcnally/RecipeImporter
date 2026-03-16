from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import ChunkLane, ConversionReport, ConversionResult, KnowledgeChunk, RawArtifact
from cookimport.llm.codex_farm_knowledge_orchestrator import run_codex_farm_knowledge_harvest
from cookimport.llm.fake_codex_farm_runner import FakeCodexFarmRunner
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
            "llm_knowledge_pipeline": "codex-farm-knowledge-v1",
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

    runner = FakeCodexFarmRunner()
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
    assert "telemetry_report" in apply_result.llm_report["process_run"]
    assert "autotune_report" in apply_result.llm_report["process_run"]
    assert apply_result.llm_report["input_mode"] == "stage7_knowledge_spans"
    assert apply_result.manifest_path.exists()
    manifest = json.loads(apply_result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"]["jobs_written"] > 0

    knowledge_dir = run_root / "knowledge" / "book"
    assert (knowledge_dir / "snippets.jsonl").exists()
    assert (knowledge_dir / "knowledge.md").exists()


def test_knowledge_orchestrator_noops_when_no_stage7_knowledge_spans(tmp_path: Path) -> None:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-farm-knowledge-v1",
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
        runner=FakeCodexFarmRunner(),
        full_blocks=[],
    )

    assert apply_result.llm_report["stage_status"] == "no_knowledge_spans"
    assert apply_result.llm_report["counts"]["jobs_written"] == 0
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
            "llm_knowledge_pipeline": "codex-farm-knowledge-v1",
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
    runner = FakeCodexFarmRunner()

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
    assert apply_result.llm_report["counts"]["jobs_skipped"] == 1
    assert apply_result.llm_report["skipped_lane_counts"] == {"noise": 1}
