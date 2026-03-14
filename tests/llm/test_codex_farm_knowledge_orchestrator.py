from __future__ import annotations

import json
from pathlib import Path

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import ConversionReport, ConversionResult, RawArtifact
from cookimport.llm.codex_farm_knowledge_orchestrator import run_codex_farm_knowledge_harvest
from cookimport.llm.fake_codex_farm_runner import FakeCodexFarmRunner


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
            "codex_farm_pipeline_pass4_knowledge": "recipe.knowledge.compact.v1",
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
    assert apply_result.manifest_path.exists()
    manifest = json.loads(apply_result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"]["jobs_written"] > 0

    knowledge_dir = run_root / "knowledge" / "book"
    assert (knowledge_dir / "snippets.jsonl").exists()
    assert (knowledge_dir / "knowledge.md").exists()
