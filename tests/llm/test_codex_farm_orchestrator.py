from __future__ import annotations

import csv
import datetime as dt
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cookimport.cli_worker import stage_one_file
from cookimport.config.run_settings import RunSettings
from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    MappingConfig,
    RawArtifact,
    RecipeCandidate,
)
from cookimport.core.timing import TimingStats
from cookimport.llm.codex_farm_orchestrator import (
    COMPACT_PASS2_PIPELINE_ID,
    COMPACT_PASS3_PIPELINE_ID,
    LEGACY_PASS2_PIPELINE_ID,
    LEGACY_PASS3_PIPELINE_ID,
    PASS1_PIPELINE_ID,
    PASS2_PIPELINE_ID,
    PASS3_PIPELINE_ID,
    _build_transport_audit,
    _RecipeState,
    run_codex_farm_recipe_pipeline,
)
from cookimport.llm.codex_farm_runner import (
    CodexFarmPipelineRunResult,
    CodexFarmRunnerError,
    SubprocessCodexFarmRunner,
    ensure_codex_farm_pipelines_exist,
    list_codex_farm_models,
)
from cookimport.llm.fake_codex_farm_runner import FakeCodexFarmRunner


def _build_conversion_result(source_path: Path) -> ConversionResult:
    return ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:recipe:test:toast",
                recipeIngredient=["1 slice bread"],
                recipeInstructions=["Toast the bread."],
                provenance={"location": {"start_block": 1, "end_block": 4}},
            )
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
                        {"index": 4, "text": "Serve warm."},
                    ],
                    "block_count": 5,
                },
                metadata={"artifact_type": "extracted_blocks"},
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
                name="Recipe A",
                identifier="urn:recipe:test:r0",
                recipeIngredient=["1 cup flour"],
                recipeInstructions=["Mix."],
                provenance={"location": {"start_block": 0, "end_block": 2}},
            ),
            RecipeCandidate(
                name="Recipe B",
                identifier="urn:recipe:test:r1",
                recipeIngredient=["2 eggs"],
                recipeInstructions=["Bake."],
                provenance={"location": {"start_block": 3, "end_block": 5}},
            ),
        ],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        nonRecipeBlocks=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash456",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Recipe A"},
                        {"index": 1, "text": "1 cup flour"},
                        {"index": 2, "text": "Mix."},
                        {"index": 3, "text": "Recipe B"},
                        {"index": 4, "text": "2 eggs"},
                        {"index": 5, "text": "Bake."},
                    ],
                    "block_count": 6,
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook=source_path.stem,
        workbookPath=str(source_path),
    )


def _build_lines_only_conversion_result(source_path: Path) -> ConversionResult:
    return ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:recipe:test:toast",
                recipeIngredient=["1 slice bread"],
                recipeInstructions=["Toast the bread."],
                provenance={"location": {"start_block": 1, "end_block": 4}},
            )
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
                    "lines": [
                        {"index": 0, "text": "Preface"},
                        {"index": 1, "text": "Toast"},
                        {"index": 2, "text": "1 slice bread"},
                        {"index": 3, "text": "Toast the bread."},
                        {"index": 4, "text": "Serve warm."},
                    ],
                    "text": "Preface\nToast\n1 slice bread\nToast the bread.\nServe warm.\n",
                },
                metadata={"artifact_type": "extracted_lines"},
            )
        ],
        report=ConversionReport(),
        workbook=source_path.stem,
        workbookPath=str(source_path),
    )


def _build_run_settings(
    pack_root: Path,
    *,
    failure_mode: str = "fail",
    pass3_skip_pass2_ok: bool = True,
    pass1_pattern_hints_enabled: bool = False,
    pass2_pipeline: str = PASS2_PIPELINE_ID,
    pass3_pipeline: str = PASS3_PIPELINE_ID,
    recipe_mode: str = "extract",
    benchmark_selective_retry_enabled: bool = True,
    benchmark_selective_retry_max_attempts: int = 1,
) -> RunSettings:
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)
    return RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-farm-3pass-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_context_blocks": 3,
            "codex_farm_failure_mode": failure_mode,
            "codex_farm_pass3_skip_pass2_ok": pass3_skip_pass2_ok,
            "codex_farm_pass1_pattern_hints_enabled": pass1_pattern_hints_enabled,
            "codex_farm_pipeline_pass2": pass2_pipeline,
            "codex_farm_pipeline_pass3": pass3_pipeline,
            "codex_farm_recipe_mode": recipe_mode,
            "codex_farm_benchmark_selective_retry_enabled": (
                benchmark_selective_retry_enabled
            ),
            "codex_farm_benchmark_selective_retry_max_attempts": (
                benchmark_selective_retry_max_attempts
            ),
        }
    )


def test_orchestrator_writes_compact_pass2_payload_and_reduces_bundle_size(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    result.raw_artifacts[0].content["blocks"] = [
        {"index": 0, "text": "Preface"},
        {"index": 1, "text": "TOAST"},
        {"index": 2, "text": "1 slice bread"},
        {"index": 3, "text": "1 tablespoon butter"},
        {"index": 4, "text": "Toast the bread until golden."},
        {"index": 5, "text": "Spread with butter and serve hot."},
    ]

    runner = FakeCodexFarmRunner(
        output_builders={
            LEGACY_PASS2_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "schemaorg_recipe": {"name": "Toast"},
                "extracted_ingredients": ["1 slice bread", "1 tablespoon butter"],
                "extracted_instructions": [
                    "Toast the bread until golden.",
                    "Spread with butter and serve hot.",
                ],
                "field_evidence": {},
                "warnings": [],
            },
            COMPACT_PASS2_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "schemaorg_recipe": {"name": "Toast"},
                "extracted_ingredients": ["1 slice bread", "1 tablespoon butter"],
                "extracted_instructions": [
                    "Toast the bread until golden.",
                    "Spread with butter and serve hot.",
                ],
                "field_evidence": {},
                "warnings": [],
            },
        }
    )

    legacy_apply = run_codex_farm_recipe_pipeline(
        conversion_result=result.model_copy(deep=True),
        run_settings=_build_run_settings(
            tmp_path / "legacy-pack",
            pass2_pipeline=LEGACY_PASS2_PIPELINE_ID,
        ),
        run_root=tmp_path / "legacy-run",
        workbook_slug="book",
        runner=runner,
    )
    compact_apply = run_codex_farm_recipe_pipeline(
        conversion_result=result.model_copy(deep=True),
        run_settings=_build_run_settings(
            tmp_path / "compact-pack",
            pass2_pipeline=COMPACT_PASS2_PIPELINE_ID,
        ),
        run_root=tmp_path / "compact-run",
        workbook_slug="book",
        runner=runner,
    )

    legacy_input_path = next((legacy_apply.llm_raw_dir / "pass2_schemaorg" / "in").glob("*.json"))
    compact_input_path = next((compact_apply.llm_raw_dir / "pass2_schemaorg" / "in").glob("*.json"))
    legacy_payload = json.loads(
        legacy_input_path.read_text(encoding="utf-8")
    )
    compact_payload = json.loads(
        compact_input_path.read_text(encoding="utf-8")
    )

    assert "canonical_text" in legacy_payload
    assert "normalized_evidence_text" in legacy_payload
    assert "evidence_rows" not in legacy_payload
    assert "evidence_rows" in compact_payload
    assert "canonical_text" not in compact_payload
    assert "normalized_evidence_text" not in compact_payload
    assert compact_payload["evidence_rows"][0] == [1, "TOAST"]
    legacy_bytes = len(json.dumps(legacy_payload, sort_keys=True).encode("utf-8"))
    compact_bytes = len(json.dumps(compact_payload, sort_keys=True).encode("utf-8"))
    assert compact_bytes < legacy_bytes * 0.65


def test_orchestrator_writes_compact_pass3_payload_and_drops_duplicate_schema_lists(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    result = _build_conversion_result(source)
    result.raw_artifacts[0].content["blocks"] = [
        {"index": 0, "text": "Preface"},
        {"index": 1, "text": "TOAST"},
        {"index": 2, "text": "1 slice bread"},
        {"index": 3, "text": "1 tablespoon butter"},
        {"index": 4, "text": "Toast the bread until golden."},
        {"index": 5, "text": "Spread with butter and serve hot."},
    ]

    runner = FakeCodexFarmRunner(
        output_builders={
            PASS2_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "schemaorg_recipe": {
                    "@context": "http://schema.org",
                    "@type": "Recipe",
                    "name": "Toast",
                    "recipeYield": "2 servings",
                    "recipeIngredient": [
                        "1 slice bread",
                        "1 tablespoon butter",
                    ],
                    "recipeInstructions": [
                        "Toast the bread until golden.",
                        "Spread with butter and serve hot.",
                    ],
                },
                "extracted_ingredients": ["1 slice bread", "1 tablespoon butter"],
                "extracted_instructions": [
                    "Toast the bread until golden.",
                    "Spread with butter and serve hot.",
                ],
                "field_evidence": {},
                "warnings": [],
            },
            LEGACY_PASS3_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "draft_v1": {
                    "schema_v": 1,
                    "recipe": {"title": "Toast"},
                    "steps": [
                        {"instruction": "Toast the bread until golden.", "ingredient_lines": []}
                    ],
                },
                "ingredient_step_mapping": {},
                "warnings": [],
            },
            COMPACT_PASS3_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "draft_v1": {
                    "schema_v": 1,
                    "recipe": {"title": "Toast"},
                    "steps": [
                        {"instruction": "Toast the bread until golden.", "ingredient_lines": []}
                    ],
                },
                "ingredient_step_mapping": {},
                "warnings": [],
            },
        }
    )

    legacy_apply = run_codex_farm_recipe_pipeline(
        conversion_result=result.model_copy(deep=True),
        run_settings=_build_run_settings(
            tmp_path / "legacy-pass3-pack",
            pass3_skip_pass2_ok=False,
            pass3_pipeline=LEGACY_PASS3_PIPELINE_ID,
        ),
        run_root=tmp_path / "legacy-pass3-run",
        workbook_slug="book",
        runner=runner,
    )
    compact_apply = run_codex_farm_recipe_pipeline(
        conversion_result=result.model_copy(deep=True),
        run_settings=_build_run_settings(
            tmp_path / "compact-pass3-pack",
            pass3_skip_pass2_ok=False,
            pass3_pipeline=COMPACT_PASS3_PIPELINE_ID,
        ),
        run_root=tmp_path / "compact-pass3-run",
        workbook_slug="book",
        runner=runner,
    )

    legacy_input_path = next((legacy_apply.llm_raw_dir / "pass3_final" / "in").glob("*.json"))
    compact_input_path = next((compact_apply.llm_raw_dir / "pass3_final" / "in").glob("*.json"))
    legacy_payload = json.loads(
        legacy_input_path.read_text(encoding="utf-8")
    )
    compact_payload = json.loads(
        compact_input_path.read_text(encoding="utf-8")
    )

    assert "schemaorg_recipe" in legacy_payload
    assert "recipeIngredient" in legacy_payload["schemaorg_recipe"]
    assert "recipeInstructions" in legacy_payload["schemaorg_recipe"]
    assert "schemaorg_recipe" not in compact_payload
    assert "recipe_metadata" in compact_payload
    assert compact_payload["recipe_metadata"]["name"] == "Toast"
    assert "recipeIngredient" not in compact_payload["recipe_metadata"]
    assert "recipeInstructions" not in compact_payload["recipe_metadata"]
    legacy_bytes = len(json.dumps(legacy_payload, sort_keys=True).encode("utf-8"))
    compact_bytes = len(json.dumps(compact_payload, sort_keys=True).encode("utf-8"))
    assert compact_bytes < legacy_bytes * 0.85


def test_orchestrator_runs_pass3_for_low_risk_pass2_ok_when_policy_disabled_in_run_settings(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack", pass3_skip_pass2_ok=False)
    result = _build_conversion_result(source)
    result.raw_artifacts[0].content["blocks"][3]["text"] = (
        "Toast slowly until deeply golden and crisp on both sides."
    )
    result.raw_artifacts[0].content["blocks"][4]["text"] = (
        "Serve immediately while the crust is still hot and crackling."
    )

    runner = FakeCodexFarmRunner(
        output_builders={
            PASS2_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "schemaorg_recipe": {
                    "@context": "http://schema.org",
                    "@type": "Recipe",
                    "name": "Toast",
                },
                "extracted_ingredients": ["1 slice bread"],
                "extracted_instructions": [
                    "Toast slowly until deeply golden and crisp on both sides.",
                    "Serve immediately while the crust is still hot and crackling.",
                ],
                "field_evidence": {},
                "warnings": [],
            },
            PASS3_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "draft_v1": {
                    "schema_v": 1,
                    "source": "book.txt",
                    "recipe": {"title": "Toast"},
                    "steps": [
                        {
                            "instruction": "Toast slowly until deeply golden and crisp on both sides.",
                            "ingredient_lines": [],
                        }
                    ],
                },
                "ingredient_step_mapping": {"0": [0]},
                "warnings": [],
            },
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert runner.calls == [PASS1_PIPELINE_ID, PASS2_PIPELINE_ID, PASS3_PIPELINE_ID]
    recipe_id = result.recipes[0].identifier
    assert recipe_id is not None
    manifest = json.loads((apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8"))
    recipe_row = manifest["recipes"][recipe_id]
    assert recipe_row["pass3_execution_mode"] == "llm"
    assert recipe_row["pass3_routing_reason"] == "pass2_ok"
    assert recipe_row["pass3_utility_signal"]["deterministic_low_risk"] is True
    assert manifest["counts"]["pass3_inputs"] == 1
    assert manifest["counts"]["pass3_pass2_ok_skip_candidates"] == 1
    assert manifest["counts"]["pass3_pass2_ok_deterministic_skips"] == 0
    assert manifest["counts"]["pass3_pass2_ok_llm_calls"] == 1
    assert manifest["pass3_policy"]["pass2_ok_deterministic_skip_enabled"] is False


def test_orchestrator_skips_pass3_for_low_risk_pass2_ok_when_policy_enabled_in_run_settings(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack", pass3_skip_pass2_ok=True)
    result = _build_conversion_result(source)
    result.raw_artifacts[0].content["blocks"][3]["text"] = (
        "Toast slowly until deeply golden and crisp on both sides."
    )
    result.raw_artifacts[0].content["blocks"][4]["text"] = (
        "Serve immediately while the crust is still hot and crackling."
    )

    runner = FakeCodexFarmRunner(
        output_builders={
            PASS2_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "schemaorg_recipe": {
                    "@context": "http://schema.org",
                    "@type": "Recipe",
                    "name": "Toast",
                },
                "extracted_ingredients": ["1 slice bread"],
                "extracted_instructions": [
                    "Toast slowly until deeply golden and crisp on both sides.",
                    "Serve immediately while the crust is still hot and crackling.",
                ],
                "field_evidence": {},
                "warnings": [],
            },
            PASS3_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "draft_v1": {
                    "schema_v": 1,
                    "source": "book.txt",
                    "recipe": {"title": "Should not run"},
                    "steps": [{"instruction": "Should not run", "ingredient_lines": []}],
                },
                "ingredient_step_mapping": {"0": [0]},
                "warnings": [],
            },
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert runner.calls == [PASS1_PIPELINE_ID, PASS2_PIPELINE_ID]
    recipe_id = result.recipes[0].identifier
    assert recipe_id is not None
    manifest = json.loads((apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8"))
    recipe_row = manifest["recipes"][recipe_id]
    assert recipe_row["pass3"] == "ok"
    assert recipe_row["pass3_execution_mode"] == "deterministic"
    assert recipe_row["pass3_routing_reason"] == "pass2_ok_high_confidence_deterministic"
    assert recipe_row["pass2_promotion_policy"] == "pass2_ok_deterministic_promotion"
    assert recipe_row["pass3_utility_signal"]["deterministic_low_risk"] is True
    assert manifest["counts"]["pass3_inputs"] == 0
    assert manifest["counts"]["pass3_pass2_ok_skip_candidates"] == 1
    assert manifest["counts"]["pass3_pass2_ok_deterministic_skips"] == 1
    assert manifest["counts"]["pass3_pass2_ok_llm_calls"] == 0
    assert manifest["pass3_policy"]["pass2_ok_deterministic_skip_enabled"] is True


def test_orchestrator_writes_recipe_guardrail_report_artifacts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack", pass3_skip_pass2_ok=True)
    result = _build_conversion_result(source)
    result.raw_artifacts[0].content["blocks"][3]["text"] = (
        "Toast slowly until deeply golden and crisp on both sides."
    )
    result.raw_artifacts[0].content["blocks"][4]["text"] = (
        "Serve immediately while the crust is still hot and crackling."
    )
    runner = FakeCodexFarmRunner(
        output_builders={
            PASS2_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "schemaorg_recipe": {
                    "@context": "http://schema.org",
                    "@type": "Recipe",
                    "name": "Toast",
                },
                "extracted_ingredients": ["1 slice bread"],
                "extracted_instructions": [
                    "Toast slowly until deeply golden and crisp on both sides.",
                    "Serve immediately while the crust is still hot and crackling.",
                ],
                "field_evidence": {},
                "warnings": [],
            },
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    guardrail_report = json.loads(
        (apply_result.llm_raw_dir / "guardrail_report.json").read_text(encoding="utf-8")
    )
    guardrail_rows = (
        apply_result.llm_raw_dir / "guardrail_rows.jsonl"
    ).read_text(encoding="utf-8")
    manifest = json.loads(
        (apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8")
    )

    assert guardrail_report["schema_version"] == "recipe_codex_guardrail_report.v1"
    assert guardrail_report["summary"]["pass3_routing_rows"] >= 1
    assert "pass2_ok_high_confidence_deterministic" in guardrail_rows
    assert manifest["paths"]["recipe_guardrail_report"].endswith("guardrail_report.json")
    assert manifest["paths"]["recipe_guardrail_rows"].endswith("guardrail_rows.jsonl")


def test_orchestrator_records_pass1_span_loss_metrics_when_midpoint_clamp_shrinks_span(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_multi_recipe_conversion_result(source)

    def _pass1_builder(payload: dict[str, object]) -> dict[str, object]:
        recipe_id = str(payload.get("recipe_id") or "")
        start = 0
        end = 4
        if recipe_id.endswith("r1"):
            start = 2
            end = 5
        return {
            "bundle_version": "1",
            "recipe_id": recipe_id,
            "is_recipe": True,
            "start_block_index": start,
            "end_block_index": end,
            "title": None,
            "reasoning_tags": ["overlap-test"],
            "excluded_block_ids": [],
        }

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=FakeCodexFarmRunner(output_builders={PASS1_PIPELINE_ID: _pass1_builder}),
    )

    manifest = json.loads(
        (apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8")
    )
    first_recipe_metrics = manifest["recipes"]["urn:recipe:test:r0"]["pass1_span_loss_metrics"]
    assert first_recipe_metrics["raw_start_block_index"] == 0
    assert first_recipe_metrics["raw_end_block_index"] == 4
    assert first_recipe_metrics["raw_span_count"] == 5
    assert first_recipe_metrics["clamped_start_block_index"] == 0
    assert first_recipe_metrics["clamped_end_block_index"] == 3
    assert first_recipe_metrics["clamped_span_count"] == 4
    assert first_recipe_metrics["clamped_block_loss_count"] == 1
    assert first_recipe_metrics["clamped_block_loss_ratio"] == 0.2
    assert first_recipe_metrics["boundaries_clamped"] is True


def test_orchestrator_pass1_eligibility_gate_drops_low_evidence_spans(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)
    result.raw_artifacts[0].content["blocks"][0]["text"] = (
        "This opening paragraph discusses kitchen history, writing style, and context, "
        "but it is not an actionable recipe span."
    )

    runner = FakeCodexFarmRunner(
        output_builders={
            PASS1_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "is_recipe": True,
                "start_block_index": 0,
                "end_block_index": 0,
                "title": None,
                "reasoning_tags": ["eligibility-drop"],
                "excluded_block_ids": [],
            }
        }
    )
    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert runner.calls == [PASS1_PIPELINE_ID]
    manifest = json.loads(
        (apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8")
    )
    recipe_id = "urn:recipe:test:toast"
    recipe_row = manifest["recipes"][recipe_id]
    assert recipe_row["eligibility_action"] == "drop"
    assert recipe_row["pass1"] == "dropped"
    assert manifest["counts"]["pass1_eligibility_drop"] == 1
    assert manifest["counts"]["pass2_inputs"] == 0
    assert result.recipes == []


def test_orchestrator_pass1_eligibility_gate_clamps_to_heuristic_bounds(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)
    result.raw_artifacts[0].content["blocks"][1]["text"] = "TOAST"

    runner = FakeCodexFarmRunner(
        output_builders={
            PASS1_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "is_recipe": True,
                "start_block_index": 1,
                "end_block_index": 1,
                "title": None,
                "reasoning_tags": ["eligibility-clamp"],
                "excluded_block_ids": [],
            }
        }
    )
    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert runner.calls == [PASS1_PIPELINE_ID, PASS2_PIPELINE_ID]
    recipe_id = "urn:recipe:test:toast"
    manifest = json.loads(
        (apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8")
    )
    recipe_row = manifest["recipes"][recipe_id]
    assert recipe_row["eligibility_action"] == "clamp"
    assert recipe_row["pass1"] == "ok"
    assert manifest["counts"]["pass1_eligibility_clamp"] == 1
    location = result.recipes[0].provenance.get("location")
    assert location["start_block"] == 1
    assert location["end_block"] == 4


def test_orchestrator_pass1_eligibility_uses_chapter_page_negative_metadata(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)
    blocks = result.raw_artifacts[0].content["blocks"]
    blocks[1]["text"] = "TOAST"
    blocks[1]["features"] = {"chapter_type": "chapter_intro"}
    blocks[2]["text"] = "Mix the bread."
    blocks[2]["features"] = {"page_type": "mixed_content_page"}

    runner = FakeCodexFarmRunner(
        output_builders={
            PASS1_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "is_recipe": True,
                "start_block_index": 1,
                "end_block_index": 2,
                "title": None,
                "reasoning_tags": ["eligibility-clamp"],
                "excluded_block_ids": [],
            }
        }
    )
    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert runner.calls == [PASS1_PIPELINE_ID, PASS2_PIPELINE_ID]
    recipe_id = "urn:recipe:test:toast"
    manifest = json.loads(
        (apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8")
    )
    recipe_row = manifest["recipes"][recipe_id]
    components = recipe_row["eligibility_score_components"]
    reasons = recipe_row["eligibility_reasons"]
    assert recipe_row["eligibility_action"] == "clamp"
    assert components["chapter_page_negative_evidence_high"] is True
    assert components["chapter_page_negative_score"] == -2
    assert "chapter_page_metadata_negative_evidence_high" in reasons


def test_orchestrator_pass1_eligibility_gate_records_proceed_action(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)
    runner = FakeCodexFarmRunner(
        output_builders={
            PASS2_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "schemaorg_recipe": {
                    "@context": "http://schema.org",
                    "@type": "Recipe",
                    "name": "Toast",
                },
                "extracted_ingredients": ["1 slice bread"],
                "extracted_instructions": ["Toast the bread."],
                "field_evidence": {},
                "warnings": [],
            }
        }
    )
    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    manifest = json.loads(
        (apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8")
    )
    recipe_row = manifest["recipes"]["urn:recipe:test:toast"]
    assert recipe_row["eligibility_action"] == "proceed"
    assert recipe_row["eligibility_score"] >= 3
    assert manifest["counts"]["pass1_eligibility_proceed"] == 1


def test_orchestrator_transport_mismatch_is_recipe_scoped_error(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)
    result.raw_artifacts[0].content["blocks"] = [
        {"index": 0, "text": "Preface"},
        {"index": 1, "text": "Toast"},
        # Missing index 2 on purpose; pass1 range still references it.
        {"index": 3, "text": "Toast the bread."},
        {"index": 4, "text": "Serve warm."},
    ]
    runner = FakeCodexFarmRunner()

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert runner.calls == [PASS1_PIPELINE_ID]
    manifest = json.loads((apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["transport_mismatches"] == 1
    assert manifest["counts"]["pass2_errors"] == 1
    assert manifest["counts"]["pass3_inputs"] == 0
    assert apply_result.llm_report["transport"]["mismatch_recipes"] == 1

    audit_path = next((apply_result.llm_raw_dir / "transport_audit").glob("*.json"))
    audit_payload = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit_payload["mismatch"] is True
    assert "effective_indices_vs_payload_indices" in audit_payload["mismatch_reasons"]


def test_build_transport_audit_detects_block_id_value_mismatch() -> None:
    recipe = RecipeCandidate(name="Toast")
    state = _RecipeState(
        recipe=recipe,
        recipe_id="urn:recipe:test:toast",
        bundle_name="urn-recipe-test-toast__r000.json",
        heuristic_start=1,
        heuristic_end=3,
        pass1_status="ok",
        start_block_index=1,
        end_block_index=3,
    )
    audit = _build_transport_audit(
        state=state,
        block_indices=[1, 2],
        effective_block_ids=["block-1", "block-2"],
        included_blocks=[
            {"index": 1, "block_id": "block-1"},
            {"index": 2, "block_id": "wrong-block-id"},
        ],
    )

    assert audit["mismatch"] is True
    assert "effective_block_ids_vs_payload_block_ids_values" in audit["mismatch_reasons"]
    assert "effective_count_vs_payload_count" not in audit["mismatch_reasons"]


def test_orchestrator_transport_mismatch_marks_recipe_fallback_in_fallback_mode(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack", failure_mode="fallback")
    result = _build_conversion_result(source)
    result.raw_artifacts[0].content["blocks"] = [
        {"index": 0, "text": "Preface"},
        {"index": 1, "text": "Toast"},
        # Missing index 2 on purpose; pass1 range still references it.
        {"index": 3, "text": "Toast the bread."},
        {"index": 4, "text": "Serve warm."},
    ]
    runner = FakeCodexFarmRunner()

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert runner.calls == [PASS1_PIPELINE_ID]
    manifest = json.loads((apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["transport_mismatches"] == 1
    assert manifest["counts"]["pass2_errors"] == 1
    assert manifest["counts"]["pass3_fallback"] == 1
    assert apply_result.llm_report["pass3_fallback_recipe_ids"] == [
        result.recipes[0].identifier
    ]
    assert apply_result.final_overrides_by_recipe_id
    recipe_row = manifest["recipes"][result.recipes[0].identifier]
    assert recipe_row["pass3"] == "fallback"
    assert recipe_row["pass3_fallback_reason"] == "transport_invariant_failed"


def test_orchestrator_writes_evidence_normalization_artifact(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)
    result.raw_artifacts[0].content["blocks"][2]["text"] = "Page 9 - 1 cup sugar 2 tbsp butter"

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=FakeCodexFarmRunner(),
    )

    pass2_input_path = next((apply_result.llm_raw_dir / "pass2_schemaorg" / "in").glob("*.json"))
    pass2_input = json.loads(pass2_input_path.read_text(encoding="utf-8"))
    assert "evidence_rows" in pass2_input
    assert "normalized_evidence_text" not in pass2_input

    normalization_path = next((apply_result.llm_raw_dir / "evidence_normalization").glob("*.json"))
    normalization_payload = json.loads(normalization_path.read_text(encoding="utf-8"))
    normalized_lines = [row["text"] for row in normalization_payload["line_rows"]]
    assert "Page 9" not in normalized_lines
    assert "1 cup sugar" in normalized_lines
    assert "2 tbsp butter" in normalized_lines
    assert normalization_payload["stats"]["folded_page_markers"] == 1
    assert normalization_payload["stats"]["split_quantity_lines"] == 1


def test_orchestrator_uses_deterministic_pass3_fallback_for_low_quality_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)

    runner = FakeCodexFarmRunner(
        output_builders={
            PASS2_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "schemaorg_recipe": {
                    "@context": "http://schema.org",
                    "@type": "Recipe",
                    "name": "Toast",
                    "description": "Serve warm with lemon.",
                },
                "extracted_ingredients": ["1 slice bread"],
                "extracted_instructions": ["Toast the bread."],
                "field_evidence": {},
                "warnings": [],
            },
            PASS3_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "draft_v1": {
                    "schema_v": 1,
                    "source": "book.txt",
                    "recipe": {"title": "Toast"},
                    "steps": [
                        {
                            "instruction": "Serve warm with lemon.",
                            "ingredient_lines": [],
                        }
                    ],
                },
                "ingredient_step_mapping": {},
                "warnings": [],
            },
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    recipe_id = result.recipes[0].identifier
    assert recipe_id is not None
    fallback_draft = apply_result.final_overrides_by_recipe_id[recipe_id]
    step_instructions = [step.get("instruction") for step in fallback_draft.get("steps", [])]
    assert "Serve warm with lemon." not in step_instructions
    assert "Toast the bread." in step_instructions

    manifest = json.loads((apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["pass3_fallback"] == 1
    recipe_row = manifest["recipes"][recipe_id]
    assert recipe_row["pass3"] == "fallback"
    assert "pass3 output rejected as low quality" in recipe_row["pass3_fallback_reason"]


def test_orchestrator_gates_pass3_when_pass2_degraded_missing_instruction_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=FakeCodexFarmRunner(),
    )

    assert apply_result.llm_report["counts"]["pass2_degraded"] == 1
    assert apply_result.llm_report["counts"]["pass2_degraded_hard"] == 1
    assert apply_result.llm_report["counts"]["pass2_degraded_soft"] == 0
    assert apply_result.llm_report["counts"]["pass3_inputs"] == 0
    assert apply_result.llm_report["counts"]["pass3_fallback"] == 1
    assert apply_result.llm_report["counts"]["pass3_execution_mode_deterministic"] == 1

    recipe_id = result.recipes[0].identifier
    assert recipe_id is not None
    recipe_row = json.loads(
        (apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8")
    )["recipes"][recipe_id]
    assert recipe_row["pass2"] == "degraded"
    assert recipe_row["pass3"] == "fallback"
    assert "missing_instructions" in recipe_row["pass3_fallback_reason"]
    assert recipe_row["pass2_degradation_severity"] == "hard"
    assert recipe_row["pass2_promotion_policy"] == "hard_fallback"
    assert recipe_row["pass3_execution_mode"] == "deterministic"
    assert recipe_row["pass3_routing_reason"] == "pass2_hard_degradation_forced_fallback"

    fallback_steps = apply_result.final_overrides_by_recipe_id[recipe_id]["steps"]
    assert any(step.get("instruction") == "Toast the bread." for step in fallback_steps)


def test_orchestrator_soft_degradation_uses_deterministic_promotion_without_pass3_call(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)

    runner = FakeCodexFarmRunner(
        output_builders={
            PASS2_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "schemaorg_recipe": {
                    "@context": "http://schema.org",
                    "@type": "Recipe",
                    "name": "Toast",
                },
                "extracted_ingredients": ["1 slice bread"],
                "extracted_instructions": ["Toast the bread."],
                "field_evidence": {},
                "warnings": ["Page marker artifact detected in scanned footer."],
            },
            PASS3_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "draft_v1": {
                    "schema_v": 1,
                    "source": "book.txt",
                    "recipe": {"title": "Should not run"},
                    "steps": [{"instruction": "Should not run", "ingredient_lines": []}],
                },
                "ingredient_step_mapping": {"0": [0]},
                "warnings": [],
            },
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert runner.calls == [PASS1_PIPELINE_ID, PASS2_PIPELINE_ID]
    assert apply_result.llm_report["counts"]["pass2_degraded"] == 1
    assert apply_result.llm_report["counts"]["pass2_degraded_soft"] == 1
    assert apply_result.llm_report["counts"]["pass2_degraded_hard"] == 0
    assert apply_result.llm_report["counts"]["pass3_inputs"] == 0
    assert apply_result.llm_report["counts"]["pass3_ok"] == 1
    assert apply_result.llm_report["counts"]["pass3_fallback"] == 0
    assert apply_result.llm_report["counts"]["pass3_execution_mode_deterministic"] == 1

    recipe_id = result.recipes[0].identifier
    assert recipe_id is not None
    manifest = json.loads((apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8"))
    recipe_row = manifest["recipes"][recipe_id]
    assert recipe_row["pass2"] == "degraded"
    assert recipe_row["pass2_degradation_severity"] == "soft"
    assert recipe_row["pass2_promotion_policy"] == "soft_degradation_deterministic_promotion"
    assert recipe_row["pass3"] == "ok"
    assert recipe_row["pass3_execution_mode"] == "deterministic"
    assert recipe_row["pass3_routing_reason"] == "pass2_soft_degradation_low_risk"
    assert "pass3_fallback_reason" not in recipe_row


def test_orchestrator_repairs_placeholder_only_pass3_steps_from_pass2_instructions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)

    runner = FakeCodexFarmRunner(
        output_builders={
            PASS2_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "schemaorg_recipe": {
                    "@context": "http://schema.org",
                    "@type": "Recipe",
                    "name": "Toast",
                },
                "extracted_ingredients": ["1 slice bread"],
                "extracted_instructions": ["Toast the bread."],
                "field_evidence": {},
                "warnings": [],
            },
            PASS3_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "draft_v1": {
                    "schema_v": 1,
                    "source": "book.txt",
                    "recipe": {"title": "Toast"},
                    "steps": [
                        {
                            "instruction": "See original recipe for details.",
                            "ingredient_lines": [],
                        }
                    ],
                },
                "ingredient_step_mapping": {"0": [0]},
                "warnings": [],
            },
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    manifest = json.loads((apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8"))
    recipe_id = result.recipes[0].identifier
    assert recipe_id is not None
    assert manifest["recipes"][recipe_id]["pass3"] == "ok"
    assert "pass3_fallback_reason" not in manifest["recipes"][recipe_id]
    warnings = manifest["recipes"][recipe_id]["warnings"]
    assert any("placeholder-only steps repaired" in warning for warning in warnings)
    final_draft = apply_result.final_overrides_by_recipe_id[recipe_id]
    steps = [str(step.get("instruction") or "") for step in final_draft.get("steps", [])]
    assert "See original recipe for details." not in steps
    assert "Toast the bread." in steps


def test_orchestrator_coerces_legacy_pass3_draft_shape_without_schema_v(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)

    runner = FakeCodexFarmRunner(
        output_builders={
            PASS2_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "schemaorg_recipe": {
                    "@context": "http://schema.org",
                    "@type": "Recipe",
                    "name": "Toast",
                },
                "extracted_ingredients": ["1 slice bread"],
                "extracted_instructions": ["Toast the bread."],
                "field_evidence": {},
                "warnings": [],
            },
            PASS3_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "draft_v1": {
                    "name": "Toast",
                    "ingredients": ["1 slice bread"],
                    "instructions": ["Toast the bread."],
                },
                "ingredient_step_mapping": {},
                "warnings": [],
            },
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    recipe_id = result.recipes[0].identifier
    assert recipe_id is not None
    manifest = json.loads((apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8"))
    assert manifest["recipes"][recipe_id]["pass3"] == "ok"

    final_draft = apply_result.final_overrides_by_recipe_id[recipe_id]
    assert final_draft["schema_v"] == 1
    assert final_draft["recipe"]["title"] == "Toast"
    assert final_draft["steps"][0]["instruction"] == "Toast the bread."


def test_orchestrator_coerces_pass2_like_pass3_draft_shape_to_draft_v1(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)

    runner = FakeCodexFarmRunner(
        output_builders={
            PASS2_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "schemaorg_recipe": {
                    "@context": "http://schema.org",
                    "@type": "Recipe",
                    "name": "Toast",
                    "recipeInstructions": [
                        {"@type": "HowToStep", "text": "Toast the bread."},
                    ],
                },
                "extracted_ingredients": ["1 slice bread"],
                "extracted_instructions": ["Toast the bread."],
                "field_evidence": {},
                "warnings": [],
            },
            PASS3_PIPELINE_ID: lambda payload: {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "draft_v1": {
                    "schemaorg_recipe": {
                        "@context": "http://schema.org",
                        "@type": "Recipe",
                        "name": "Toast",
                        "recipeInstructions": [
                            {"@type": "HowToStep", "text": "Toast the bread."},
                        ],
                    },
                    "extracted_instructions": ["Toast the bread."],
                },
                "ingredient_step_mapping": {},
                "warnings": [],
            },
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    recipe_id = result.recipes[0].identifier
    assert recipe_id is not None
    manifest = json.loads((apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8"))
    assert manifest["recipes"][recipe_id]["pass3"] == "ok"

    final_draft = apply_result.final_overrides_by_recipe_id[recipe_id]
    assert final_draft["schema_v"] == 1
    assert final_draft["recipe"]["title"] == "Toast"
    assert final_draft["steps"][0]["instruction"] == "Toast the bread."


def test_orchestrator_uses_configured_pipeline_ids_and_workspace_root(
    tmp_path: Path,
) -> None:
    class _RecordingRunner:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run_pipeline(
            self,
            pipeline_id: str,
            in_dir: Path,
            out_dir: Path,
            env: dict[str, str],
            *,
            root_dir: Path | None = None,
            workspace_root: Path | None = None,
            model: str | None = None,
            reasoning_effort: str | None = None,
        ) -> None:
            self.calls.append(
                {
                    "pipeline_id": pipeline_id,
                    "root_dir": root_dir,
                    "workspace_root": workspace_root,
                    "env_root": env.get("CODEX_FARM_ROOT"),
                    "env_recipe_mode": env.get("COOKIMPORT_CODEX_FARM_RECIPE_MODE"),
                    "model": model,
                    "reasoning_effort": reasoning_effort,
                }
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            for in_path in sorted(in_dir.glob("*.json")):
                payload = json.loads(in_path.read_text(encoding="utf-8"))
                if pipeline_id == "custom.pass1":
                    output = {
                        "bundle_version": "1",
                        "recipe_id": payload.get("recipe_id"),
                        "is_recipe": True,
                        "start_block_index": payload.get("heuristic_start_block_index"),
                        "end_block_index": payload.get("heuristic_end_block_index"),
                        "title": None,
                        "reasoning_tags": ["recording-runner"],
                        "excluded_block_ids": [],
                    }
                elif pipeline_id == "custom.pass2":
                    output = {
                        "bundle_version": "1",
                        "recipe_id": payload.get("recipe_id"),
                        "schemaorg_recipe": {
                            "@context": "http://schema.org",
                            "@type": "Recipe",
                            "name": "Custom Recipe",
                        },
                "extracted_ingredients": [],
                "extracted_instructions": ["Toast the bread."],
                "field_evidence": {},
                "warnings": [],
            }
                elif pipeline_id == "custom.pass3":
                    output = {
                        "bundle_version": "1",
                        "recipe_id": payload.get("recipe_id"),
                        "draft_v1": {
                            "schema_v": 1,
                            "source": None,
                            "recipe": {"title": "Custom Recipe"},
                            "steps": [
                                {
                                    "instruction": "See original recipe for details.",
                                    "ingredient_lines": [],
                                }
                            ],
                        },
                        "ingredient_step_mapping": {},
                        "warnings": [],
                    }
                else:
                    raise AssertionError(f"Unexpected pipeline id: {pipeline_id}")
                (out_dir / in_path.name).write_text(
                    json.dumps(output, indent=2, sort_keys=True),
                    encoding="utf-8",
                )

    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    pack_root = tmp_path / "pack"
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(pack_root)
    settings = settings.model_copy(
        update={
            "codex_farm_workspace_root": str(workspace_root),
            "codex_farm_pipeline_pass1": "custom.pass1",
            "codex_farm_pipeline_pass2": "custom.pass2",
            "codex_farm_pipeline_pass3": "custom.pass3",
            "codex_farm_model": "gpt-test-model",
            "codex_farm_reasoning_effort": "high",
        }
    )
    result = _build_conversion_result(source)
    runner = _RecordingRunner()

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert [call["pipeline_id"] for call in runner.calls] == [
        "custom.pass1",
        "custom.pass2",
        "custom.pass3",
    ]
    for call in runner.calls:
        assert call["root_dir"] == pack_root
        assert call["workspace_root"] == workspace_root
        assert call["env_root"] == str(pack_root)
        assert call["env_recipe_mode"] == "extract"
        assert call["model"] == "gpt-test-model"
        assert call["reasoning_effort"] == "high"

    manifest_path = apply_result.llm_raw_dir / "llm_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["pipelines"] == {
        "pass1": "custom.pass1",
        "pass2": "custom.pass2",
        "pass3": "custom.pass3",
    }
    assert apply_result.llm_report["pipelines"] == manifest["pipelines"]


def test_pass1_pattern_hints_follow_run_settings(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings_off = _build_run_settings(tmp_path / "pack-off")

    result_off = _build_conversion_result(source)
    result_off.recipes[0].provenance["location"]["pattern_flags"] = [
        "toc_like_cluster",
        "duplicate_title_intro",
    ]
    result_off.recipes[0].provenance["location"]["pattern_actions"] = [
        {
            "action": "trim_candidate_start",
            "original_start_block": 1,
            "trimmed_start_block": 2,
        }
    ]
    apply_off = run_codex_farm_recipe_pipeline(
        conversion_result=result_off,
        run_settings=settings_off,
        run_root=tmp_path / "run-off",
        workbook_slug="book",
        runner=FakeCodexFarmRunner(),
    )
    pass1_payload_off = json.loads(
        next((apply_off.llm_raw_dir / "pass1_chunking" / "in").glob("*.json")).read_text(
            encoding="utf-8"
        )
    )
    assert pass1_payload_off["pattern_hints"] == []
    assert apply_off.llm_report["pass1_pattern_hints_enabled"] is False

    settings_on = _build_run_settings(
        tmp_path / "pack-on",
        pass1_pattern_hints_enabled=True,
    )
    result_on = _build_conversion_result(source)
    result_on.recipes[0].provenance["location"]["pattern_flags"] = [
        "toc_like_cluster",
        "duplicate_title_intro",
    ]
    result_on.recipes[0].provenance["location"]["pattern_actions"] = [
        {
            "action": "trim_candidate_start",
            "original_start_block": 1,
            "trimmed_start_block": 2,
        }
    ]
    apply_on = run_codex_farm_recipe_pipeline(
        conversion_result=result_on,
        run_settings=settings_on,
        run_root=tmp_path / "run-on",
        workbook_slug="book",
        runner=FakeCodexFarmRunner(),
    )
    pass1_payload_on = json.loads(
        next((apply_on.llm_raw_dir / "pass1_chunking" / "in").glob("*.json")).read_text(
            encoding="utf-8"
        )
    )
    hint_types = {hint["hint_type"] for hint in pass1_payload_on["pattern_hints"]}
    assert "toc_like_cluster" in hint_types
    assert "duplicate_title_intro" in hint_types
    assert "trim_candidate_start" in hint_types
    assert apply_on.llm_report["pass1_pattern_hints_enabled"] is True


def test_orchestrator_recipe_level_failures_fallback_without_crashing(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_conversion_result(source)

    runner = FakeCodexFarmRunner(
        output_builders={
            PASS2_PIPELINE_ID: lambda _payload: {
                "bundle_version": "1",
                "recipe_id": "oops",
            }
        }
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert runner.calls == [PASS1_PIPELINE_ID, PASS2_PIPELINE_ID]
    assert apply_result.intermediate_overrides_by_recipe_id == {}
    assert apply_result.final_overrides_by_recipe_id == {}
    assert len(apply_result.updated_conversion_result.recipes) == 1
    assert apply_result.llm_report["counts"]["pass2_errors"] == 1


def test_orchestrator_keeps_other_recipes_when_one_pass2_bundle_is_missing(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack", pass3_skip_pass2_ok=False)
    result = _build_multi_recipe_conversion_result(source)

    class PartialPass2Runner(FakeCodexFarmRunner):
        def run_pipeline(  # type: ignore[override]
            self,
            pipeline_id: str,
            in_dir: Path,
            out_dir: Path,
            env: dict[str, str],
            *,
            root_dir: Path | None = None,
            workspace_root: Path | None = None,
            model: str | None = None,
            reasoning_effort: str | None = None,
        ) -> CodexFarmPipelineRunResult:
            if pipeline_id != PASS2_PIPELINE_ID:
                return super().run_pipeline(
                    pipeline_id,
                    in_dir,
                    out_dir,
                    env,
                    root_dir=root_dir,
                    workspace_root=workspace_root,
                    model=model,
                    reasoning_effort=reasoning_effort,
                )
            self.calls.append(pipeline_id)
            out_dir.mkdir(parents=True, exist_ok=True)
            first_input = sorted(in_dir.glob("*.json"))[0]
            payload = json.loads(first_input.read_text(encoding="utf-8"))
            canonical_text = str(payload.get("canonical_text") or "").strip()
            recipe_name = canonical_text.splitlines()[0].strip() if canonical_text else "Recipe"
            output = {
                "bundle_version": "1",
                "recipe_id": payload.get("recipe_id"),
                "schemaorg_recipe": json.dumps(
                    {
                        "@context": "http://schema.org",
                        "@type": "Recipe",
                        "name": recipe_name,
                    },
                    sort_keys=True,
                ),
                "extracted_ingredients": ["1 test ingredient"],
                "extracted_instructions": ["Do the test step."],
                "field_evidence": "{}",
                "warnings": [],
            }
            (out_dir / first_input.name).write_text(
                json.dumps(output, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            return CodexFarmPipelineRunResult(
                pipeline_id=pipeline_id,
                run_id="run-partial-pass2",
                subprocess_exit_code=1,
                process_exit_code=1,
                output_schema_path=None,
                process_payload={"run_id": "run-partial-pass2", "status": "failed", "exit_code": 1},
                telemetry_report=None,
                autotune_report=None,
                telemetry={
                    "row_count": 2,
                    "summary": {
                        "failure_category_counts": {
                            "nonzero_exit_no_payload": 1,
                            "timeout": 1,
                        }
                    },
                },
            )

    runner = PartialPass2Runner()
    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert runner.calls == [PASS1_PIPELINE_ID, PASS2_PIPELINE_ID, PASS3_PIPELINE_ID]
    assert len(apply_result.intermediate_overrides_by_recipe_id) == 1
    assert len(apply_result.final_overrides_by_recipe_id) == 1
    assert apply_result.llm_report["counts"]["pass2_errors"] == 1
    assert apply_result.llm_report["counts"]["pass3_ok"] == 1
    manifest = json.loads((apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8"))
    recipe_rows = list(manifest["recipes"].values())
    errored_rows = [row for row in recipe_rows if row.get("pass2") == "error"]
    ok_rows = [row for row in recipe_rows if row.get("pass3") == "ok"]
    assert len(errored_rows) == 1
    assert errored_rows[0]["errors"] == ["missing pass2 output bundle."]
    assert len(ok_rows) == 1
    assert manifest["selective_retries"] == {}
    assert not (apply_result.llm_raw_dir / "pass2_schemaorg" / "retry_attempt_01").exists()


def test_orchestrator_selective_retry_recovers_missing_pass2_bundle_in_benchmark_mode(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(
        tmp_path / "pack",
        recipe_mode="benchmark",
        pass3_skip_pass2_ok=False,
        benchmark_selective_retry_enabled=True,
        benchmark_selective_retry_max_attempts=2,
    )
    result = _build_multi_recipe_conversion_result(source)

    class RecoveringPass2Runner(FakeCodexFarmRunner):
        def __init__(self) -> None:
            super().__init__()
            self.pass2_input_batches: list[list[str]] = []
            self.pass2_attempt = 0

        def run_pipeline(  # type: ignore[override]
            self,
            pipeline_id: str,
            in_dir: Path,
            out_dir: Path,
            env: dict[str, str],
            *,
            root_dir: Path | None = None,
            workspace_root: Path | None = None,
            model: str | None = None,
            reasoning_effort: str | None = None,
        ) -> CodexFarmPipelineRunResult:
            if pipeline_id != PASS2_PIPELINE_ID:
                return super().run_pipeline(
                    pipeline_id,
                    in_dir,
                    out_dir,
                    env,
                    root_dir=root_dir,
                    workspace_root=workspace_root,
                    model=model,
                    reasoning_effort=reasoning_effort,
                )
            self.calls.append(pipeline_id)
            self.pass2_attempt += 1
            batch = [path.name for path in sorted(in_dir.glob("*.json"))]
            self.pass2_input_batches.append(batch)
            out_dir.mkdir(parents=True, exist_ok=True)
            if self.pass2_attempt == 1:
                first_input = sorted(in_dir.glob("*.json"))[0]
                payload = json.loads(first_input.read_text(encoding="utf-8"))
                (out_dir / first_input.name).write_text(
                    json.dumps(
                        {
                            "bundle_version": "1",
                            "recipe_id": payload.get("recipe_id"),
                            "schemaorg_recipe": {
                                "@context": "http://schema.org",
                                "@type": "Recipe",
                                "name": "Recovered pass2 primary",
                            },
                            "extracted_ingredients": ["1 test ingredient"],
                            "extracted_instructions": ["Do the test step."],
                            "field_evidence": {},
                            "warnings": [],
                        },
                        indent=2,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                return CodexFarmPipelineRunResult(
                    pipeline_id=pipeline_id,
                    run_id="run-pass2-partial",
                    subprocess_exit_code=1,
                    process_exit_code=1,
                    output_schema_path=None,
                    process_payload={
                        "run_id": "run-pass2-partial",
                        "status": "failed",
                        "exit_code": 1,
                    },
                    telemetry_report=None,
                    autotune_report=None,
                    telemetry={
                        "row_count": 2,
                        "summary": {
                            "failure_category_counts": {
                                "nonzero_exit_no_payload": 1,
                                "timeout": 1,
                            }
                        },
                    },
                )
            retry_input = next(in_dir.glob("*.json"))
            retry_payload = json.loads(retry_input.read_text(encoding="utf-8"))
            (out_dir / retry_input.name).write_text(
                json.dumps(
                    {
                        "bundle_version": "1",
                        "recipe_id": retry_payload.get("recipe_id"),
                        "schemaorg_recipe": {
                            "@context": "http://schema.org",
                            "@type": "Recipe",
                            "name": "Recovered on retry",
                        },
                        "extracted_ingredients": ["1 test ingredient"],
                        "extracted_instructions": ["Do the test step."],
                        "field_evidence": {},
                        "warnings": [],
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            return CodexFarmPipelineRunResult(
                pipeline_id=pipeline_id,
                run_id="run-pass2-retry",
                subprocess_exit_code=0,
                process_exit_code=0,
                output_schema_path=None,
                process_payload={
                    "run_id": "run-pass2-retry",
                    "status": "completed",
                    "exit_code": 0,
                },
                telemetry_report=None,
                autotune_report=None,
                telemetry=None,
            )

    runner = RecoveringPass2Runner()
    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert len(runner.pass2_input_batches) == 2
    assert len(runner.pass2_input_batches[0]) == 2
    assert len(runner.pass2_input_batches[1]) == 1
    assert runner.pass2_input_batches[1][0] in runner.pass2_input_batches[0]
    assert apply_result.llm_report["counts"]["selective_retry_pass2_attempts"] == 1
    assert apply_result.llm_report["counts"]["selective_retry_pass2_recovered"] == 1
    assert apply_result.llm_report["counts"]["pass2_errors"] == 0
    assert apply_result.llm_report["counts"]["pass3_ok"] == 2

    manifest = json.loads(
        (apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8")
    )
    retry_payload = manifest["selective_retries"]["pass2"]
    assert retry_payload["settings"]["codex_farm_recipe_mode"] == "benchmark"
    assert retry_payload["settings"]["codex_farm_benchmark_selective_retry_enabled"] is True
    assert retry_payload["settings"]["codex_farm_benchmark_selective_retry_max_attempts"] == 2
    assert retry_payload["original_missing_bundle_count"] == 1
    assert retry_payload["recovered_bundle_count"] == 1
    assert retry_payload["unrecovered_bundle_count"] == 0
    assert len(retry_payload["attempts"]) == 1
    assert retry_payload["attempts"][0]["attempted_bundle_filenames"] == runner.pass2_input_batches[1]
    assert retry_payload["attempts"][0]["copied_output_filenames"] == runner.pass2_input_batches[1]
    assert (apply_result.llm_raw_dir / "pass2_schemaorg" / "retry_attempt_01" / "in").exists()
    assert (apply_result.llm_raw_dir / "pass2_schemaorg" / "retry_attempt_01" / "out").exists()


def test_orchestrator_selective_retry_reports_unrecovered_pass2_bundle(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(
        tmp_path / "pack",
        recipe_mode="benchmark",
        pass3_skip_pass2_ok=False,
        benchmark_selective_retry_enabled=True,
        benchmark_selective_retry_max_attempts=1,
    )
    result = _build_multi_recipe_conversion_result(source)

    class UnrecoveredPass2Runner(FakeCodexFarmRunner):
        def __init__(self) -> None:
            super().__init__()
            self.pass2_input_batches: list[list[str]] = []
            self.pass2_attempt = 0

        def run_pipeline(  # type: ignore[override]
            self,
            pipeline_id: str,
            in_dir: Path,
            out_dir: Path,
            env: dict[str, str],
            *,
            root_dir: Path | None = None,
            workspace_root: Path | None = None,
            model: str | None = None,
            reasoning_effort: str | None = None,
        ) -> CodexFarmPipelineRunResult:
            if pipeline_id != PASS2_PIPELINE_ID:
                return super().run_pipeline(
                    pipeline_id,
                    in_dir,
                    out_dir,
                    env,
                    root_dir=root_dir,
                    workspace_root=workspace_root,
                    model=model,
                    reasoning_effort=reasoning_effort,
                )
            self.calls.append(pipeline_id)
            self.pass2_attempt += 1
            batch = [path.name for path in sorted(in_dir.glob("*.json"))]
            self.pass2_input_batches.append(batch)
            out_dir.mkdir(parents=True, exist_ok=True)
            if self.pass2_attempt == 1:
                first_input = sorted(in_dir.glob("*.json"))[0]
                payload = json.loads(first_input.read_text(encoding="utf-8"))
                (out_dir / first_input.name).write_text(
                    json.dumps(
                        {
                            "bundle_version": "1",
                            "recipe_id": payload.get("recipe_id"),
                            "schemaorg_recipe": {
                                "@context": "http://schema.org",
                                "@type": "Recipe",
                                "name": "Only first recipe recovered",
                            },
                            "extracted_ingredients": ["1 test ingredient"],
                            "extracted_instructions": ["Do the test step."],
                            "field_evidence": {},
                            "warnings": [],
                        },
                        indent=2,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
            return CodexFarmPipelineRunResult(
                pipeline_id=pipeline_id,
                run_id=f"run-pass2-attempt-{self.pass2_attempt}",
                subprocess_exit_code=1,
                process_exit_code=1,
                output_schema_path=None,
                process_payload={
                    "run_id": f"run-pass2-attempt-{self.pass2_attempt}",
                    "status": "failed",
                    "exit_code": 1,
                },
                telemetry_report=None,
                autotune_report=None,
                telemetry={
                    "row_count": len(batch),
                    "summary": {
                        "failure_category_counts": {
                            "nonzero_exit_no_payload": 1,
                            "timeout": 1,
                        }
                    },
                },
            )

    runner = UnrecoveredPass2Runner()
    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert len(runner.pass2_input_batches) == 2
    assert len(runner.pass2_input_batches[0]) == 2
    assert len(runner.pass2_input_batches[1]) == 1
    assert apply_result.llm_report["counts"]["selective_retry_pass2_attempts"] == 1
    assert apply_result.llm_report["counts"]["selective_retry_pass2_recovered"] == 0
    assert apply_result.llm_report["counts"]["pass2_errors"] == 1
    assert apply_result.llm_report["counts"]["pass3_ok"] == 1

    manifest = json.loads(
        (apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8")
    )
    retry_payload = manifest["selective_retries"]["pass2"]
    assert retry_payload["settings"]["codex_farm_recipe_mode"] == "benchmark"
    assert retry_payload["settings"]["codex_farm_benchmark_selective_retry_enabled"] is True
    assert retry_payload["settings"]["codex_farm_benchmark_selective_retry_max_attempts"] == 1
    assert retry_payload["original_missing_bundle_count"] == 1
    assert retry_payload["recovered_bundle_count"] == 0
    assert retry_payload["unrecovered_bundle_count"] == 1
    assert len(retry_payload["attempts"]) == 1
    errored_rows = [
        row for row in manifest["recipes"].values() if row.get("pass2") == "error"
    ]
    assert len(errored_rows) == 1


def test_orchestrator_selective_retry_recovers_missing_pass3_bundle_in_benchmark_mode(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(
        tmp_path / "pack",
        recipe_mode="benchmark",
        pass3_skip_pass2_ok=False,
        benchmark_selective_retry_enabled=True,
        benchmark_selective_retry_max_attempts=2,
    )
    result = _build_multi_recipe_conversion_result(source)

    class RecoveringPass3Runner(FakeCodexFarmRunner):
        def __init__(self) -> None:
            super().__init__(
                output_builders={
                    PASS2_PIPELINE_ID: lambda payload: {
                        "bundle_version": "1",
                        "recipe_id": payload.get("recipe_id"),
                        "schemaorg_recipe": {
                            "@context": "http://schema.org",
                            "@type": "Recipe",
                            "name": str(payload.get("recipe_id") or "Recipe"),
                        },
                        "extracted_ingredients": ["1 test ingredient"],
                        "extracted_instructions": ["Mix ingredients and cook."],
                        "field_evidence": {},
                        "warnings": [],
                    }
                }
            )
            self.pass3_input_batches: list[list[str]] = []
            self.pass3_attempt = 0

        def run_pipeline(  # type: ignore[override]
            self,
            pipeline_id: str,
            in_dir: Path,
            out_dir: Path,
            env: dict[str, str],
            *,
            root_dir: Path | None = None,
            workspace_root: Path | None = None,
            model: str | None = None,
            reasoning_effort: str | None = None,
        ) -> CodexFarmPipelineRunResult:
            if pipeline_id != PASS3_PIPELINE_ID:
                return super().run_pipeline(
                    pipeline_id,
                    in_dir,
                    out_dir,
                    env,
                    root_dir=root_dir,
                    workspace_root=workspace_root,
                    model=model,
                    reasoning_effort=reasoning_effort,
                )
            self.calls.append(pipeline_id)
            self.pass3_attempt += 1
            batch = [path.name for path in sorted(in_dir.glob("*.json"))]
            self.pass3_input_batches.append(batch)
            out_dir.mkdir(parents=True, exist_ok=True)

            def _write_pass3_output(input_path: Path, title: str) -> None:
                payload = json.loads(input_path.read_text(encoding="utf-8"))
                (out_dir / input_path.name).write_text(
                    json.dumps(
                        {
                            "bundle_version": "1",
                            "recipe_id": payload.get("recipe_id"),
                            "draft_v1": {
                                "schema_v": 1,
                                "source": "book.txt",
                                "recipe": {"title": title},
                                "steps": [
                                    {
                                        "instruction": "Mix ingredients and cook.",
                                        "ingredient_lines": ["1 test ingredient"],
                                    }
                                ],
                            },
                            "ingredient_step_mapping": {"0": [0]},
                            "warnings": [],
                        },
                        indent=2,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )

            if self.pass3_attempt == 1:
                first_input = sorted(in_dir.glob("*.json"))[0]
                _write_pass3_output(first_input, "Recovered pass3 primary")
                return CodexFarmPipelineRunResult(
                    pipeline_id=pipeline_id,
                    run_id="run-pass3-partial",
                    subprocess_exit_code=1,
                    process_exit_code=1,
                    output_schema_path=None,
                    process_payload={
                        "run_id": "run-pass3-partial",
                        "status": "failed",
                        "exit_code": 1,
                    },
                    telemetry_report=None,
                    autotune_report=None,
                    telemetry={
                        "row_count": 2,
                        "summary": {
                            "failure_category_counts": {
                                "nonzero_exit_no_payload": 1,
                                "timeout": 1,
                            }
                        },
                    },
                )

            retry_input = next(in_dir.glob("*.json"))
            _write_pass3_output(retry_input, "Recovered pass3 on retry")
            return CodexFarmPipelineRunResult(
                pipeline_id=pipeline_id,
                run_id="run-pass3-retry",
                subprocess_exit_code=0,
                process_exit_code=0,
                output_schema_path=None,
                process_payload={
                    "run_id": "run-pass3-retry",
                    "status": "completed",
                    "exit_code": 0,
                },
                telemetry_report=None,
                autotune_report=None,
                telemetry=None,
            )

    runner = RecoveringPass3Runner()
    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert len(runner.pass3_input_batches) == 2
    assert len(runner.pass3_input_batches[0]) == 2
    assert len(runner.pass3_input_batches[1]) == 1
    assert runner.pass3_input_batches[1][0] in runner.pass3_input_batches[0]
    assert apply_result.llm_report["counts"]["selective_retry_pass3_attempts"] == 1
    assert apply_result.llm_report["counts"]["selective_retry_pass3_recovered"] == 1
    assert apply_result.llm_report["counts"]["pass3_errors"] == 0
    assert len(apply_result.final_overrides_by_recipe_id) == 2

    manifest = json.loads(
        (apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8")
    )
    retry_payload = manifest["selective_retries"]["pass3"]
    assert retry_payload["settings"]["codex_farm_recipe_mode"] == "benchmark"
    assert retry_payload["settings"]["codex_farm_benchmark_selective_retry_enabled"] is True
    assert retry_payload["settings"]["codex_farm_benchmark_selective_retry_max_attempts"] == 2
    assert retry_payload["original_missing_bundle_count"] == 1
    assert retry_payload["recovered_bundle_count"] == 1
    assert retry_payload["unrecovered_bundle_count"] == 0
    assert len(retry_payload["attempts"]) == 1
    assert retry_payload["attempts"][0]["attempted_bundle_filenames"] == runner.pass3_input_batches[1]
    assert retry_payload["attempts"][0]["copied_output_filenames"] == runner.pass3_input_batches[1]
    assert (apply_result.llm_raw_dir / "pass3_final" / "retry_attempt_01" / "in").exists()
    assert (apply_result.llm_raw_dir / "pass3_final" / "retry_attempt_01" / "out").exists()


def test_orchestrator_selective_retry_reports_unrecovered_pass3_bundle(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(
        tmp_path / "pack",
        recipe_mode="benchmark",
        pass3_skip_pass2_ok=False,
        benchmark_selective_retry_enabled=True,
        benchmark_selective_retry_max_attempts=1,
    )
    result = _build_multi_recipe_conversion_result(source)

    class UnrecoveredPass3Runner(FakeCodexFarmRunner):
        def __init__(self) -> None:
            super().__init__(
                output_builders={
                    PASS2_PIPELINE_ID: lambda payload: {
                        "bundle_version": "1",
                        "recipe_id": payload.get("recipe_id"),
                        "schemaorg_recipe": {
                            "@context": "http://schema.org",
                            "@type": "Recipe",
                            "name": str(payload.get("recipe_id") or "Recipe"),
                        },
                        "extracted_ingredients": ["1 test ingredient"],
                        "extracted_instructions": ["Cook until done."],
                        "field_evidence": {},
                        "warnings": [],
                    }
                }
            )
            self.pass3_input_batches: list[list[str]] = []
            self.pass3_attempt = 0

        def run_pipeline(  # type: ignore[override]
            self,
            pipeline_id: str,
            in_dir: Path,
            out_dir: Path,
            env: dict[str, str],
            *,
            root_dir: Path | None = None,
            workspace_root: Path | None = None,
            model: str | None = None,
            reasoning_effort: str | None = None,
        ) -> CodexFarmPipelineRunResult:
            if pipeline_id != PASS3_PIPELINE_ID:
                return super().run_pipeline(
                    pipeline_id,
                    in_dir,
                    out_dir,
                    env,
                    root_dir=root_dir,
                    workspace_root=workspace_root,
                    model=model,
                    reasoning_effort=reasoning_effort,
                )
            self.calls.append(pipeline_id)
            self.pass3_attempt += 1
            batch = [path.name for path in sorted(in_dir.glob("*.json"))]
            self.pass3_input_batches.append(batch)
            out_dir.mkdir(parents=True, exist_ok=True)
            if self.pass3_attempt == 1:
                first_input = sorted(in_dir.glob("*.json"))[0]
                payload = json.loads(first_input.read_text(encoding="utf-8"))
                (out_dir / first_input.name).write_text(
                    json.dumps(
                        {
                            "bundle_version": "1",
                            "recipe_id": payload.get("recipe_id"),
                            "draft_v1": {
                                "schema_v": 1,
                                "source": "book.txt",
                                "recipe": {"title": "Only first pass3 recipe recovered"},
                                "steps": [
                                    {
                                        "instruction": "Cook until done.",
                                        "ingredient_lines": ["1 test ingredient"],
                                    }
                                ],
                            },
                            "ingredient_step_mapping": {"0": [0]},
                            "warnings": [],
                        },
                        indent=2,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
            return CodexFarmPipelineRunResult(
                pipeline_id=pipeline_id,
                run_id=f"run-pass3-attempt-{self.pass3_attempt}",
                subprocess_exit_code=1,
                process_exit_code=1,
                output_schema_path=None,
                process_payload={
                    "run_id": f"run-pass3-attempt-{self.pass3_attempt}",
                    "status": "failed",
                    "exit_code": 1,
                },
                telemetry_report=None,
                autotune_report=None,
                telemetry={
                    "row_count": len(batch),
                    "summary": {
                        "failure_category_counts": {
                            "nonzero_exit_no_payload": 1,
                            "timeout": 1,
                        }
                    },
                },
            )

    runner = UnrecoveredPass3Runner()
    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=result,
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    assert len(runner.pass3_input_batches) == 2
    assert len(runner.pass3_input_batches[0]) == 2
    assert len(runner.pass3_input_batches[1]) == 1
    assert apply_result.llm_report["counts"]["selective_retry_pass3_attempts"] == 1
    assert apply_result.llm_report["counts"]["selective_retry_pass3_recovered"] == 0
    assert apply_result.llm_report["counts"]["pass3_errors"] == 0
    assert len(apply_result.final_overrides_by_recipe_id) == 2

    manifest = json.loads(
        (apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8")
    )
    retry_payload = manifest["selective_retries"]["pass3"]
    assert retry_payload["settings"]["codex_farm_recipe_mode"] == "benchmark"
    assert retry_payload["settings"]["codex_farm_benchmark_selective_retry_enabled"] is True
    assert retry_payload["settings"]["codex_farm_benchmark_selective_retry_max_attempts"] == 1
    assert retry_payload["original_missing_bundle_count"] == 1
    assert retry_payload["recovered_bundle_count"] == 0
    assert retry_payload["unrecovered_bundle_count"] == 1
    assert len(retry_payload["attempts"]) == 1








