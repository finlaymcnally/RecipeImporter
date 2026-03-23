from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import ConversionReport, ConversionResult, RawArtifact, RecipeCandidate
from cookimport.llm.codex_farm_knowledge_orchestrator import run_codex_farm_nonrecipe_knowledge_review
from cookimport.llm.codex_farm_orchestrator import run_codex_farm_recipe_pipeline
from cookimport.parsing.canonical_line_roles import label_atomic_lines
from cookimport.parsing.label_source_of_truth import RecipeSpan
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate
from cookimport.staging.nonrecipe_stage import NonRecipeSpan, NonRecipeStageResult


def _patch_direct_exec_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("cookimport.llm.codex_exec_runner.Path.home", lambda: tmp_path)
    monkeypatch.setattr(
        "cookimport.llm.codex_exec_runner._resolve_recipeimport_codex_home",
        lambda explicit_env=None: str(tmp_path / ".codex-recipe"),
    )


def _script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "fake-codex-farm.py"


def _build_lines_only_conversion_result(source_path: Path) -> ConversionResult:
    return ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:recipe:test:toast",
                recipeIngredient=["1 slice bread"],
                recipeInstructions=["Toast the bread."],
                provenance={"location": {"start_block": 1, "end_block": 3}},
            )
        ],
        nonRecipeBlocks=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "lines": [
                        {"index": 0, "text": "Preface"},
                        {"index": 1, "text": "Toast"},
                        {"index": 2, "text": "1 slice bread"},
                        {"index": 3, "text": "Toast the bread."},
                    ],
                },
                metadata={"artifact_type": "extracted_lines"},
            )
        ],
        report=ConversionReport(),
        workbook=source_path.stem,
        workbookPath=str(source_path),
    )


def _build_multi_recipe_conversion_result(source_path: Path) -> ConversionResult:
    return ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:recipe:test:toast",
                recipeIngredient=["1 slice bread"],
                recipeInstructions=["Toast the bread."],
                provenance={"location": {"start_block": 1, "end_block": 3}},
            ),
            RecipeCandidate(
                name="Tea",
                identifier="urn:recipe:test:tea",
                recipeIngredient=["1 cup water", "1 tea bag"],
                recipeInstructions=["Boil the water.", "Steep the tea bag."],
                provenance={"location": {"start_block": 5, "end_block": 8}},
            ),
            RecipeCandidate(
                name="Cereal",
                identifier="urn:recipe:test:cereal",
                recipeIngredient=["1 cup cereal", "1/2 cup milk"],
                recipeInstructions=["Pour cereal into a bowl.", "Add milk."],
                provenance={"location": {"start_block": 10, "end_block": 13}},
            ),
        ],
        nonRecipeBlocks=[],
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
                        {"index": 4, "text": "Separator"},
                        {"index": 5, "text": "Tea"},
                        {"index": 6, "text": "1 cup water"},
                        {"index": 7, "text": "1 tea bag"},
                        {"index": 8, "text": "Boil the water. Steep the tea bag."},
                        {"index": 9, "text": "Separator"},
                        {"index": 10, "text": "Cereal"},
                        {"index": 11, "text": "1 cup cereal"},
                        {"index": 12, "text": "1/2 cup milk"},
                        {"index": 13, "text": "Pour cereal into a bowl. Add milk."},
                    ],
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook=source_path.stem,
        workbookPath=str(source_path),
    )


def _knowledge_conversion_result(source_path: Path) -> ConversionResult:
    return ConversionResult(
        recipes=[],
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
        workbook=source_path.stem,
        workbookPath=str(source_path),
    )


def test_fake_codex_farm_lists_repo_pipelines() -> None:
    root = Path(__file__).resolve().parents[2] / "llm_pipelines"
    completed = subprocess.run(
        [
            sys.executable,
            str(_script_path()),
            "pipelines",
            "list",
            "--root",
            str(root),
            "--json",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    pipeline_ids = {row["pipeline_id"] for row in payload}
    assert "recipe.correction.compact.v1" in pipeline_ids
    assert "recipe.knowledge.compact.v1" in pipeline_ids
    assert "line-role.canonical.v1" in pipeline_ids


def test_fake_codex_farm_process_writes_recipe_outputs(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2] / "llm_pipelines"
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()
    payload = {
        "shard_id": "recipe-shard-0000",
        "recipes": [
            {
                "recipe_id": "r0001",
                "canonical_text": "Skillet Eggs\n2 eggs",
                "evidence_rows": [[0, "Skillet Eggs"], [1, "2 eggs"]],
                "recipe_candidate_hint": {},
            }
        ],
    }
    (in_dir / "recipe-shard-0000.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(_script_path()),
            "process",
            "--pipeline",
            "recipe.correction.compact.v1",
            "--in",
            str(in_dir),
            "--out",
            str(out_dir),
            "--root",
            str(root),
            "--json",
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    process_payload = json.loads(completed.stdout)
    output_payload = json.loads(
        (out_dir / "recipe-shard-0000.json").read_text(encoding="utf-8")
    )
    assert process_payload["status"] == "completed"
    assert process_payload["output_schema_path"].endswith(
        "schemas/recipe.correction.v1.output.schema.json"
    )
    assert output_payload["sid"] == "recipe-shard-0000"
    assert output_payload["r"][0]["rid"] == "r0001"
    assert output_payload["r"][0]["cr"]["t"] == "Skillet Eggs"


def test_fake_codex_farm_process_handles_text_prompt_inputs(tmp_path: Path) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()
    (in_dir / "line-role-shard-0001.json").write_text(
        '\n'.join(
            [
                '{"atomic_index": 7, "text": "2 eggs"}',
                '{"atomic_index": 8, "text": "Beat well"}',
            ]
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            str(_script_path()),
            "process",
            "--pipeline",
            "line-role.canonical.v1",
            "--in",
            str(in_dir),
            "--out",
            str(out_dir),
            "--json",
            "--progress-events",
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    output_payload = json.loads(
        (out_dir / "line-role-shard-0001.json").read_text(encoding="utf-8")
    )
    assert output_payload == {
        "rows": [
            {"atomic_index": 7, "label": "OTHER"},
            {"atomic_index": 8, "label": "OTHER"},
        ]
    }


def test_recipe_orchestrator_can_run_through_fake_codex_farm_subprocess(
    tmp_path: Path,
) -> None:
    source = tmp_path / "toast.txt"
    source.write_text("toast", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_cmd": str(_script_path()),
            "codex_farm_root": str(Path(__file__).resolve().parents[2] / "llm_pipelines"),
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=_build_lines_only_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="toast-book",
    )

    llm_root = apply_result.llm_raw_dir
    manifest = json.loads((llm_root / "recipe_manifest.json").read_text(encoding="utf-8"))
    phase_manifest = json.loads(
        (llm_root / "recipe_phase_runtime" / "phase_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    proposal_files = sorted(
        path.name
        for path in (llm_root / "recipe_phase_runtime" / "proposals").glob("*.json")
    )

    assert manifest["counts"]["recipe_shards_total"] == 1
    assert manifest["counts"]["recipe_correction_ok"] == 1
    assert phase_manifest["pipeline_id"] == "recipe.correction.compact.v1"
    assert proposal_files == ["recipe-shard-0000-r0000-r0000.json"]


def test_recipe_workspace_worker_can_run_through_fake_codex_farm_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_direct_exec_home(monkeypatch, tmp_path)
    source = tmp_path / "book.txt"
    source.write_text("book", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "recipe_worker_count": 1,
            "recipe_shard_target_recipes": 2,
            "codex_farm_cmd": str(_script_path()),
            "codex_farm_root": str(Path(__file__).resolve().parents[2] / "llm_pipelines"),
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=_build_multi_recipe_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
    )

    runtime_dir = apply_result.llm_raw_dir / "recipe_phase_runtime"
    worker_root = runtime_dir / "workers" / "worker-001"
    status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))

    assert status["runtime_mode_audit"]["output_schema_enforced"] is False
    assert status["runtime_mode_audit"]["tool_affordances_requested"] is True
    assert sorted(path.name for path in (worker_root / "out").glob("*.json")) == [
        "recipe-shard-0000-r0000-r0001.task-001.json",
        "recipe-shard-0000-r0000-r0001.task-002.json",
        "recipe-shard-0001-r0002-r0002.json",
    ]


def test_knowledge_orchestrator_can_run_through_fake_codex_farm_subprocess(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("book", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "codex_farm_cmd": str(_script_path()),
            "codex_farm_root": str(Path(__file__).resolve().parents[2] / "llm_pipelines"),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
            "codex_farm_knowledge_context_blocks": 1,
        }
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=_knowledge_conversion_result(source),
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
        run_root=tmp_path / "run",
        workbook_slug="book",
    )

    manifest = json.loads(apply_result.manifest_path.read_text(encoding="utf-8"))
    phase_dir = apply_result.llm_raw_dir / "knowledge"
    proposals = sorted(path.name for path in (phase_dir / "proposals").glob("*.json"))

    assert manifest["stage_status"] == "completed"
    assert manifest["counts"]["shards_written"] >= 1
    assert manifest["counts"]["validated_shards"] >= 1
    assert proposals
    assert (phase_dir / "phase_manifest.json").exists()
    assert (phase_dir / "worker_assignments.json").exists()
    assert (tmp_path / "run" / "knowledge" / "book" / "snippets.jsonl").exists()


def test_knowledge_workspace_worker_can_run_through_fake_codex_farm_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_direct_exec_home(monkeypatch, tmp_path)
    source = tmp_path / "book.txt"
    source.write_text("book", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 2,
            "knowledge_worker_count": 1,
            "codex_farm_cmd": str(_script_path()),
            "codex_farm_root": str(Path(__file__).resolve().parents[2] / "llm_pipelines"),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
            "codex_farm_knowledge_context_blocks": 1,
        }
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=_knowledge_conversion_result(source),
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
        run_root=tmp_path / "run",
        workbook_slug="book",
    )

    phase_dir = apply_result.llm_raw_dir / "knowledge"
    worker_root = phase_dir / "workers" / "worker-001"
    status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))

    assert status["runtime_mode_audit"]["output_schema_enforced"] is False
    assert status["runtime_mode_audit"]["tool_affordances_requested"] is True
    assert sorted(path.name for path in (worker_root / "out").glob("*.json"))


def test_line_role_runtime_can_run_through_fake_codex_farm_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_direct_exec_home(monkeypatch, tmp_path)
    settings = RunSettings.model_validate(
        {
            "line_role_pipeline": "codex-line-role-shard-v1",
            "line_role_worker_count": 1,
            "line_role_prompt_target_count": None,
            "codex_farm_cmd": str(_script_path()),
            "codex_farm_root": str(Path(__file__).resolve().parents[2] / "llm_pipelines"),
        }
    )
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:{atomic_index}",
            block_index=atomic_index,
            atomic_index=atomic_index,
            text=f"Ambiguous line {atomic_index}",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
        for atomic_index in range(3)
    ]

    predictions = label_atomic_lines(
        candidates,
        settings,
        artifact_root=tmp_path,
        codex_batch_size=1,
        live_llm_allowed=True,
    )

    runtime_root = tmp_path / "line-role-pipeline" / "runtime" / "line_role"
    phase_manifest = json.loads((runtime_root / "phase_manifest.json").read_text(encoding="utf-8"))
    proposals = sorted(path.name for path in (runtime_root / "proposals").glob("*.json"))

    assert [row.atomic_index for row in predictions] == [0, 1, 2]
    assert all(row.decided_by == "codex" for row in predictions)
    assert phase_manifest["pipeline_id"] == "line-role.canonical.v1"
    assert proposals == [
        "line-role-canonical-0001-a000000-a000000.json",
        "line-role-canonical-0002-a000001-a000001.json",
        "line-role-canonical-0003-a000002-a000002.json",
    ]
