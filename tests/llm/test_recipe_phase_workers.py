from __future__ import annotations

import json
from pathlib import Path

from cookimport.config.run_settings import RunSettings
from cookimport.core.progress_messages import parse_stage_progress
from cookimport.core.models import ConversionReport, ConversionResult, RawArtifact, RecipeCandidate
from cookimport.llm.codex_farm_orchestrator import run_codex_farm_recipe_pipeline
from cookimport.llm.codex_exec_runner import FakeCodexExecRunner


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
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
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


def _build_recipe_shard_output(payload: dict[str, object] | None) -> dict[str, object]:
    shard_payload = dict(payload or {})
    recipes = []
    for recipe_payload in shard_payload.get("r") or []:
        recipe_payload = dict(recipe_payload)
        recipe_hint = dict(recipe_payload.get("h") or {})
        recipes.append(
            {
                "bundle_version": "1",
                "recipe_id": recipe_payload["rid"],
                "repair_status": "repaired",
                "status_reason": None,
                "canonical_recipe": {
                    "title": recipe_hint.get("n"),
                    "ingredients": recipe_hint.get("i", []),
                    "steps": recipe_hint.get("s", []),
                    "description": None,
                    "recipeYield": None,
                },
                "ingredient_step_mapping": [],
                "ingredient_step_mapping_reason": "not_needed_single_step",
                "selected_tags": [],
                "warnings": [],
            }
        )
    return {
        "bundle_version": "1",
        "shard_id": shard_payload.get("sid"),
        "recipes": recipes,
    }


def test_recipe_phase_runtime_groups_multi_recipe_shards_and_promotes_outputs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(tmp_path / "pack"),
            "recipe_worker_count": 1,
            "recipe_shard_target_recipes": 2,
        }
    )
    for name in ("pipelines", "prompts", "schemas"):
        (tmp_path / "pack" / name).mkdir(parents=True, exist_ok=True)

    runner = FakeCodexExecRunner(output_builder=_build_recipe_shard_output)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=_build_multi_recipe_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    runtime_dir = apply_result.llm_raw_dir / "recipe_phase_runtime"
    manifest = json.loads(
        (apply_result.llm_raw_dir / "recipe_manifest.json").read_text(encoding="utf-8")
    )
    phase_manifest = json.loads((runtime_dir / "phase_manifest.json").read_text(encoding="utf-8"))
    worker_assignments = json.loads(
        (runtime_dir / "worker_assignments.json").read_text(encoding="utf-8")
    )
    shard_manifest = [
        json.loads(line)
        for line in (runtime_dir / "shard_manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert manifest["counts"]["recipe_shards_total"] == 2
    assert manifest["counts"]["recipe_workers_total"] == 1
    assert manifest["counts"]["recipe_correction_ok"] == 3
    assert manifest["counts"]["build_final_recipe_ok"] == 3
    assert manifest["process_runs"]["recipe_correction"]["runtime_mode"] == "direct_codex_exec_v1"

    assert phase_manifest["worker_count"] == 1
    assert phase_manifest["shard_count"] == 2
    assert phase_manifest["runtime_mode"] == "direct_codex_exec_v1"
    assert worker_assignments[0]["worker_id"] == "worker-001"
    assert len(worker_assignments[0]["shard_ids"]) == 2
    assert len(shard_manifest) == 2
    assert shard_manifest[0]["owned_ids"] == [
        "urn:recipe:test:toast",
        "urn:recipe:test:tea",
    ]
    assert shard_manifest[1]["owned_ids"] == ["urn:recipe:test:cereal"]

    phase_input_dir = apply_result.llm_raw_dir / "recipe_phase_runtime" / "inputs"
    assert len(list(phase_input_dir.glob("*.json"))) == 2
    assert not (apply_result.llm_raw_dir / "recipe_correction").exists()
    assert len(apply_result.intermediate_overrides_by_recipe_id) == 3
    assert len(apply_result.final_overrides_by_recipe_id) == 3


def test_recipe_phase_runtime_defaults_workers_to_shard_count_when_unspecified(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(tmp_path / "pack"),
            "recipe_shard_target_recipes": 2,
        }
    )
    for name in ("pipelines", "prompts", "schemas"):
        (tmp_path / "pack" / name).mkdir(parents=True, exist_ok=True)

    runner = FakeCodexExecRunner(output_builder=_build_recipe_shard_output)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=_build_multi_recipe_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    phase_manifest = json.loads(
        (
            apply_result.llm_raw_dir / "recipe_phase_runtime" / "phase_manifest.json"
        ).read_text(encoding="utf-8")
    )

    assert phase_manifest["shard_count"] == 2
    assert phase_manifest["worker_count"] == 2


def test_recipe_phase_runtime_forwards_structured_progress(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(tmp_path / "pack"),
            "recipe_worker_count": 2,
            "recipe_shard_target_recipes": 2,
        }
    )
    for name in ("pipelines", "prompts", "schemas"):
        (tmp_path / "pack" / name).mkdir(parents=True, exist_ok=True)

    progress_messages: list[str] = []
    runner = FakeCodexExecRunner(output_builder=_build_recipe_shard_output)

    run_codex_farm_recipe_pipeline(
        conversion_result=_build_multi_recipe_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
        progress_callback=progress_messages.append,
    )

    payloads = [
        payload
        for message in progress_messages
        for payload in [parse_stage_progress(message)]
        if payload is not None
    ]
    assert payloads
    assert payloads[0]["stage_label"] == "recipe pipeline"
    assert payloads[0]["task_total"] == 2
    assert int(payloads[0]["worker_total"] or 0) >= 1
    assert payloads[-1]["task_current"] == payloads[-1]["task_total"]
