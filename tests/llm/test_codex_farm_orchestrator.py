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
    PASS1_PIPELINE_ID,
    PASS2_PIPELINE_ID,
    PASS3_PIPELINE_ID,
    _build_transport_audit,
    _RecipeState,
    run_codex_farm_recipe_pipeline,
)
from cookimport.llm.codex_farm_runner import (
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


def _build_run_settings(
    pack_root: Path,
    *,
    failure_mode: str = "fail",
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
        }
    )


def test_orchestrator_runs_three_passes_and_writes_manifest(tmp_path: Path) -> None:
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
                            "instruction": "Toast the bread.",
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

    assert runner.calls == [PASS1_PIPELINE_ID, PASS2_PIPELINE_ID, PASS3_PIPELINE_ID]
    assert apply_result.intermediate_overrides_by_recipe_id
    assert apply_result.final_overrides_by_recipe_id
    assert apply_result.llm_report["enabled"] is True
    assert apply_result.llm_report["output_schema_paths"] == {}
    manifest_path = apply_result.llm_raw_dir / "llm_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"]["pass1_ok"] == 1
    assert manifest["counts"]["pass2_degraded"] == 0
    assert manifest["counts"]["pass3_ok"] == 1
    assert manifest["counts"]["transport_audits"] == 1
    assert manifest["counts"]["transport_mismatches"] == 0
    assert manifest["counts"]["evidence_normalization_logs"] == 1
    assert manifest["output_schema_paths"] == {}
    assert manifest["codex_farm_recipe_mode"] == "extract"
    assert sorted(manifest["process_runs"].keys()) == ["pass1", "pass2", "pass3"]
    assert manifest["transport"]["mismatches"] == []
    assert apply_result.llm_report["process_runs"] == manifest["process_runs"]
    assert apply_result.llm_report["codex_farm_recipe_mode"] == "extract"
    assert apply_result.llm_report["transport"]["mismatch_recipes"] == 0


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
    assert "normalized_evidence_text" in pass2_input
    assert "1 cup sugar" in pass2_input["normalized_evidence_text"]
    assert "2 tbsp butter" in pass2_input["normalized_evidence_text"]
    assert pass2_input["normalization_stats"]["folded_page_markers"] == 1
    assert pass2_input["normalization_stats"]["split_quantity_lines"] == 1

    normalization_path = next((apply_result.llm_raw_dir / "evidence_normalization").glob("*.json"))
    normalization_payload = json.loads(normalization_path.read_text(encoding="utf-8"))
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
    assert apply_result.llm_report["counts"]["pass3_inputs"] == 0
    assert apply_result.llm_report["counts"]["pass3_fallback"] == 1

    recipe_id = result.recipes[0].identifier
    assert recipe_id is not None
    recipe_row = json.loads(
        (apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8")
    )["recipes"][recipe_id]
    assert recipe_row["pass2"] == "degraded"
    assert recipe_row["pass3"] == "fallback"
    assert "missing_instructions" in recipe_row["pass3_fallback_reason"]

    fallback_steps = apply_result.final_overrides_by_recipe_id[recipe_id]["steps"]
    assert any(step.get("instruction") == "Toast the bread." for step in fallback_steps)


def test_orchestrator_rejects_placeholder_only_pass3_steps(tmp_path: Path) -> None:
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
    assert manifest["recipes"][recipe_id]["pass3"] == "fallback"
    assert "placeholder-only" in manifest["recipes"][recipe_id]["pass3_fallback_reason"]


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


def test_pass1_pattern_hints_default_off_and_env_gated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = _build_run_settings(tmp_path / "pack")

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
        run_settings=settings,
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

    monkeypatch.setenv("COOKIMPORT_CODEX_FARM_PASS1_PATTERN_HINTS", "1")
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
        run_settings=settings,
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


def test_stage_one_file_skips_codex_farm_when_pipeline_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    out = tmp_path / "output"
    out.mkdir(parents=True, exist_ok=True)
    fake_result = _build_conversion_result(source)

    orchestrator_called = {"value": False}

    def _fake_orchestrator(**_kwargs):
        orchestrator_called["value"] = True
        raise AssertionError("orchestrator should not run when llm pipeline is off")

    def _fake_import(*_args, **_kwargs):
        return fake_result.model_copy(deep=True), TimingStats(), MappingConfig()

    monkeypatch.setattr("cookimport.cli_worker.run_codex_farm_recipe_pipeline", _fake_orchestrator)
    monkeypatch.setattr("cookimport.cli_worker._run_import", _fake_import)
    monkeypatch.setattr(
        "cookimport.cli_worker.registry.best_importer_for_path",
        lambda _path: (SimpleNamespace(name="text"), 1.0),
    )

    response = stage_one_file(
        source,
        out,
        MappingConfig(),
        None,
        dt.datetime.now(),
        run_config=RunSettings().to_run_config_dict(),
    )

    assert response["status"] == "success"
    assert orchestrator_called["value"] is False


def test_subprocess_runner_reports_missing_binary(tmp_path: Path) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")

    runner = SubprocessCodexFarmRunner(cmd="definitely-missing-codex-farm-binary")
    with pytest.raises(CodexFarmRunnerError):
        runner.run_pipeline("recipe.chunking.v1", in_dir, out_dir, {})


def test_subprocess_runner_passes_root_and_workspace_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    workspace_root = tmp_path / "workspace"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}
    calls: list[list[str]] = []

    def _fake_run(command, **kwargs):  # noqa: ANN001
        argv = list(command)
        calls.append(argv)
        captured["env"] = kwargs.get("env")
        if argv[1:3] == ["process", "--pipeline"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "run_id": "run-test-passes-root-and-workspace-flags",
                        "status": "completed",
                        "exit_code": 0,
                        "output_schema_path": str(schema_path),
                        "telemetry_report": {
                            "schema_version": 2,
                            "matched_rows": 0,
                            "insights": {},
                            "recommendations": {},
                            "tuning_playbook": {},
                        },
                    }
                ),
                stderr="",
            )
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "run-test-passes-root-and-workspace-flags",
                        "pipeline_id": "recipe.chunking.v1",
                        "flag_overrides": [],
                        "command_preview": "",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    run_result = runner.run_pipeline(
        "recipe.chunking.v1",
        in_dir,
        out_dir,
        {"EXTRA_ENV": "1"},
        root_dir=root_dir,
        workspace_root=workspace_root,
        model="gpt-test-model",
        reasoning_effort="low",
    )
    assert run_result.run_id == "run-test-passes-root-and-workspace-flags"
    assert run_result.process_exit_code == 0
    assert run_result.subprocess_exit_code == 0
    assert run_result.output_schema_path == str(schema_path)
    assert run_result.telemetry_report is not None
    assert run_result.telemetry_report["schema_version"] == 2
    assert run_result.autotune_report is not None
    assert run_result.autotune_report["schema_version"] == 1
    assert run_result.telemetry is not None
    assert run_result.telemetry.get("row_count") == 0

    command = calls[0]
    assert isinstance(command, list)
    assert "--root" in command
    assert str(root_dir) in command
    assert "--workspace-root" in command
    assert str(workspace_root) in command
    assert "--model" in command
    assert "gpt-test-model" in command
    assert "--reasoning-effort" in command
    assert "low" in command
    assert "--output-schema" in command
    assert str(schema_path) in command
    assert calls[1] == [
        "codex-farm",
        "run",
        "autotune",
        "--run-id",
        "run-test-passes-root-and-workspace-flags",
        "--json",
        "--pipeline",
        "recipe.chunking.v1",
    ]


def test_subprocess_runner_appends_benchmark_mode_flag_from_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    calls: list[list[str]] = []

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        calls.append(argv)
        if argv[1:3] == ["process", "--pipeline"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "run_id": "run-benchmark-mode-flag",
                        "status": "completed",
                        "exit_code": 0,
                        "output_schema_path": str(schema_path),
                    }
                ),
                stderr="",
            )
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "run-benchmark-mode-flag",
                        "pipeline_id": "recipe.chunking.v1",
                        "flag_overrides": [],
                        "command_preview": "",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    run_result = runner.run_pipeline(
        "recipe.chunking.v1",
        in_dir,
        out_dir,
        {"COOKIMPORT_CODEX_FARM_RECIPE_MODE": "benchmark"},
        root_dir=root_dir,
    )

    assert run_result.run_id == "run-benchmark-mode-flag"
    process_command = calls[0]
    assert "--benchmark-mode" in process_command
    mode_index = process_command.index("--benchmark-mode")
    assert process_command[mode_index + 1] == "benchmark"


def test_subprocess_runner_retries_extract_without_benchmark_mode_flag_when_unsupported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    process_calls: list[list[str]] = []
    process_attempt = {"count": 0}

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        if argv[1:3] == ["process", "--pipeline"]:
            process_calls.append(argv)
            process_attempt["count"] += 1
            if process_attempt["count"] == 1:
                return SimpleNamespace(
                    returncode=2,
                    stdout="",
                    stderr="error: unrecognized arguments: --benchmark-mode\n",
                )
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "run_id": "run-extract-fallback",
                        "status": "completed",
                        "exit_code": 0,
                        "output_schema_path": str(schema_path),
                    }
                ),
                stderr="",
            )
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "run-extract-fallback",
                        "pipeline_id": "recipe.chunking.v1",
                        "flag_overrides": [],
                        "command_preview": "",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    run_result = runner.run_pipeline(
        "recipe.chunking.v1",
        in_dir,
        out_dir,
        {"COOKIMPORT_CODEX_FARM_RECIPE_MODE": "extract"},
        root_dir=root_dir,
    )

    assert run_result.run_id == "run-extract-fallback"
    assert len(process_calls) == 2
    assert "--benchmark-mode" in process_calls[0]
    assert "--benchmark-mode" not in process_calls[1]


def test_subprocess_runner_fails_when_benchmark_mode_flag_is_unsupported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    process_calls: list[list[str]] = []

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        if argv[1:3] == ["process", "--pipeline"]:
            process_calls.append(argv)
            return SimpleNamespace(
                returncode=2,
                stdout="",
                stderr="error: unrecognized arguments: --benchmark-mode\n",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    with pytest.raises(CodexFarmRunnerError, match="does not support --benchmark-mode"):
        runner.run_pipeline(
            "recipe.chunking.v1",
            in_dir,
            out_dir,
            {"COOKIMPORT_CODEX_FARM_RECIPE_MODE": "benchmark"},
            root_dir=root_dir,
        )
    assert len(process_calls) == 1


def test_subprocess_runner_emits_progress_callback_from_progress_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    popen_command: list[str] | None = None

    class _FakePopen:
        def __init__(self, command, **_kwargs):  # noqa: ANN001
            nonlocal popen_command
            popen_command = list(command)
            self.returncode = 0
            self.stdout = io.StringIO(
                json.dumps(
                    {
                        "run_id": "run-progress-events",
                        "status": "done",
                        "exit_code": 0,
                        "output_schema_path": str(schema_path),
                    }
                )
                + "\n"
            )
            self.stderr = io.StringIO(
                "\n".join(
                    [
                        "__codex_farm_progress__ "
                        + json.dumps(
                            {
                                "event": "run_started",
                                "status": "running",
                                "counts": {
                                    "queued": 1,
                                    "running": 1,
                                    "done": 0,
                                    "error": 0,
                                    "canceled": 0,
                                    "total": 2,
                                },
                                "progress": {"completed": 0},
                                "running_tasks": [
                                    {"input_path": str(in_dir / "r0000.json")},
                                ],
                            },
                            sort_keys=True,
                        ),
                        "__codex_farm_progress__ "
                        + json.dumps(
                            {
                                "event": "run_progress",
                                "status": "running",
                                "counts": {
                                    "queued": 1,
                                    "running": 1,
                                    "done": 0,
                                    "error": 0,
                                    "canceled": 0,
                                    "total": 2,
                                },
                                "progress": {"completed": 0},
                                "running_tasks": [
                                    {"input_path": str(in_dir / "r0001.json")},
                                ],
                            },
                            sort_keys=True,
                        ),
                        "__codex_farm_progress__ "
                        + json.dumps(
                            {
                                "event": "run_progress",
                                "status": "running",
                                "counts": {
                                    "queued": 0,
                                    "running": 1,
                                    "done": 1,
                                    "error": 0,
                                    "canceled": 0,
                                    "total": 2,
                                },
                                "progress": {"completed": 1},
                            },
                            sort_keys=True,
                        ),
                        "__codex_farm_progress__ "
                        + json.dumps(
                            {
                                "event": "run_finished",
                                "status": "done",
                                "counts": {
                                    "queued": 0,
                                    "running": 0,
                                    "done": 2,
                                    "error": 0,
                                    "canceled": 0,
                                    "total": 2,
                                },
                                "progress": {"completed": 2},
                            },
                            sort_keys=True,
                        ),
                    ]
                )
                + "\n"
            )

        def wait(self):  # noqa: D401
            return self.returncode

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "run-progress-events",
                        "pipeline_id": "recipe.chunking.v1",
                        "flag_overrides": [],
                        "command_preview": "",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.Popen", _FakePopen)
    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    progress_messages: list[str] = []
    runner = SubprocessCodexFarmRunner(
        cmd="codex-farm",
        progress_callback=progress_messages.append,
    )
    run_result = runner.run_pipeline(
        "recipe.chunking.v1",
        in_dir,
        out_dir,
        {},
        root_dir=root_dir,
    )

    assert run_result.run_id == "run-progress-events"
    assert popen_command is not None
    assert "--progress-events" in popen_command
    assert any("task 0/2" in message for message in progress_messages)
    assert any("task 1/2" in message for message in progress_messages)
    assert any("task 2/2" in message for message in progress_messages)
    assert sum(1 for message in progress_messages if "task 0/2" in message) >= 1
    assert any("active [r0000.json]" in message for message in progress_messages)
    assert any("active [r0001.json]" in message for message in progress_messages)


def test_subprocess_runner_retries_without_progress_events_when_flag_unsupported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    popen_command: list[str] | None = None
    run_calls: list[list[str]] = []

    class _UnsupportedProgressEventsPopen:
        def __init__(self, command, **_kwargs):  # noqa: ANN001
            nonlocal popen_command
            popen_command = list(command)
            self.returncode = 2
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("error: unrecognized arguments: --progress-events\n")

        def wait(self):  # noqa: D401
            return self.returncode

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        run_calls.append(argv)
        if argv[1:3] == ["process", "--pipeline"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "run_id": "run-progress-events-fallback",
                        "status": "done",
                        "exit_code": 0,
                        "output_schema_path": str(schema_path),
                    }
                ),
                stderr="",
            )
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "run-progress-events-fallback",
                        "pipeline_id": "recipe.chunking.v1",
                        "flag_overrides": [],
                        "command_preview": "",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_runner.subprocess.Popen",
        _UnsupportedProgressEventsPopen,
    )
    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    progress_messages: list[str] = []
    runner = SubprocessCodexFarmRunner(
        cmd="codex-farm",
        progress_callback=progress_messages.append,
    )
    run_result = runner.run_pipeline(
        "recipe.chunking.v1",
        in_dir,
        out_dir,
        {},
        root_dir=root_dir,
    )

    assert run_result.run_id == "run-progress-events-fallback"
    assert popen_command is not None
    assert "--progress-events" in popen_command
    assert run_calls
    assert "--progress-events" not in run_calls[0]
    assert any("--progress-events" in message for message in progress_messages)


def test_subprocess_runner_collects_codex_exec_activity_telemetry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    data_dir = tmp_path / "farm-data"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    telemetry_csv = data_dir / "codex_exec_activity.csv"

    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    fieldnames = [
        "logged_at_utc",
        "started_at_utc",
        "finished_at_utc",
        "duration_ms",
        "status",
        "exit_code",
        "accepted_nonzero_exit",
        "output_payload_present",
        "output_bytes",
        "output_sha256",
        "output_preview",
        "output_preview_chars",
        "output_preview_truncated",
        "codex_event_count",
        "codex_event_types_json",
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_total",
        "prompt_sha256",
        "prompt_chars",
        "pipeline_id",
        "run_id",
        "task_id",
        "worker_id",
        "input_path",
        "output_path",
        "heads_up_applied",
        "heads_up_tip_count",
        "heads_up_input_signature",
        "heads_up_tip_ids_json",
        "heads_up_tip_texts_json",
        "heads_up_tip_scores_json",
        "attempt_index",
        "retry_context_applied",
        "retry_previous_error",
        "retry_previous_error_chars",
        "retry_previous_error_sha256",
        "failure_category",
        "rate_limit_suspected",
        "stderr_tail",
        "stdout_tail",
    ]
    with telemetry_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "logged_at_utc": "2026-02-28T09:00:00.000Z",
                "started_at_utc": "2026-02-28T08:59:58.000Z",
                "finished_at_utc": "2026-02-28T09:00:00.000Z",
                "duration_ms": "2000",
                "status": "ok",
                "exit_code": "0",
                "accepted_nonzero_exit": "false",
                "output_payload_present": "true",
                "output_bytes": "321",
                "output_sha256": "abc123",
                "output_preview": "{\"bundle_version\":\"1\"}",
                "output_preview_chars": "22",
                "output_preview_truncated": "false",
                "codex_event_count": "4",
                "codex_event_types_json": json.dumps(
                    ["thread.started", "turn.completed"],
                    sort_keys=True,
                ),
                "tokens_input": "100",
                "tokens_cached_input": "20",
                "tokens_output": "30",
                "tokens_total": "130",
                "prompt_sha256": "prompt-sha",
                "prompt_chars": "999",
                "pipeline_id": "recipe.chunking.v1",
                "run_id": "run-123",
                "task_id": "task-1",
                "worker_id": "worker-a",
                "input_path": "/tmp/in.json",
                "output_path": "/tmp/out.json",
                "heads_up_applied": "true",
                "heads_up_tip_count": "2",
                "heads_up_input_signature": "sig-1",
                "heads_up_tip_ids_json": json.dumps(["tip-a", "tip-b"], sort_keys=True),
                "heads_up_tip_texts_json": json.dumps(["Tip A", "Tip B"], sort_keys=True),
                "heads_up_tip_scores_json": json.dumps([0.9, 0.2], sort_keys=True),
                "attempt_index": "2",
                "retry_context_applied": "true",
                "retry_previous_error": "schema validation failed",
                "retry_previous_error_chars": "24",
                "retry_previous_error_sha256": "retry-sha",
                "failure_category": "accepted_nonzero_exit",
                "rate_limit_suspected": "false",
                "stderr_tail": "",
                "stdout_tail": "",
            }
        )

    calls: list[list[str]] = []

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        calls.append(argv)
        if "process" in argv and "--pipeline" in argv:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "run_id": "run-123",
                        "status": "completed",
                        "exit_code": 0,
                        "output_schema_path": str(schema_path),
                        "telemetry_report": {
                            "schema_version": 2,
                            "matched_rows": 1,
                            "insights": {
                                "pass_forward_effectiveness": {
                                    "retry_context": {"rows_applied": 1},
                                }
                            },
                            "recommendations": {},
                            "tuning_playbook": {},
                        },
                    }
                ),
                stderr="",
            )
        if "run" in argv and "autotune" in argv:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "run-123",
                        "pipeline_id": "recipe.chunking.v1",
                        "flag_overrides": [
                            {
                                "flag": "--workers",
                                "current": "8",
                                "suggested": "4",
                            }
                        ],
                        "command_preview": "codex-farm process ... --workers 4",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd=f"codex-farm --data-dir {data_dir}")
    run_result = runner.run_pipeline(
        "recipe.chunking.v1",
        in_dir,
        out_dir,
        {},
        root_dir=root_dir,
    )

    assert run_result.run_id == "run-123"
    assert run_result.telemetry_report is not None
    assert run_result.telemetry_report["schema_version"] == 2
    assert run_result.telemetry_report["matched_rows"] == 1
    assert run_result.autotune_report is not None
    assert run_result.autotune_report["schema_version"] == 1
    assert run_result.autotune_report["flag_overrides"][0]["flag"] == "--workers"
    assert run_result.telemetry is not None
    assert run_result.telemetry["row_count"] == 1
    assert run_result.telemetry["summary"]["attempt_index_counts"] == {"2": 1}
    assert run_result.telemetry["summary"]["failure_category_counts"] == {
        "accepted_nonzero_exit": 1
    }
    rows = run_result.telemetry["rows"]
    assert len(rows) == 1
    assert rows[0]["heads_up_tip_ids"] == ["tip-a", "tip-b"]
    assert rows[0]["retry_context_applied"] is True
    assert rows[0]["output_sha256"] == "abc123"
    assert rows[0]["codex_event_types"] == ["thread.started", "turn.completed"]
    assert calls[1] == [
        "codex-farm",
        "--data-dir",
        str(data_dir),
        "run",
        "autotune",
        "--run-id",
        "run-123",
        "--json",
        "--pipeline",
        "recipe.chunking.v1",
    ]


def test_subprocess_runner_fails_before_process_when_output_schema_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/missing.schema.json",
            }
        ),
        encoding="utf-8",
    )

    called = {"value": False}

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        called["value"] = True
        raise AssertionError(f"subprocess.run should not be called: {command}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    with pytest.raises(CodexFarmRunnerError) as exc_info:
        runner.run_pipeline(
            "recipe.chunking.v1",
            in_dir,
            out_dir,
            {},
            root_dir=root_dir,
        )

    assert "Expected file path does not exist" in str(exc_info.value)
    assert called["value"] is False


def test_subprocess_runner_rejects_process_payload_missing_output_schema_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    root_dir = tmp_path / "pack"
    schema_path = root_dir / "schemas" / "recipe.chunking.v1.output.schema.json"
    pipeline_path = root_dir / "pipelines" / "recipe.chunking.v1.json"
    in_dir.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.chunking.v1",
                "prompt_template_path": "prompts/recipe.chunking.v1.prompt.md",
                "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    def _fake_run(_command, **_kwargs):  # noqa: ANN001
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "run_id": "run-123",
                    "status": "completed",
                    "exit_code": 0,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    with pytest.raises(CodexFarmRunnerError) as exc_info:
        runner.run_pipeline(
            "recipe.chunking.v1",
            in_dir,
            out_dir,
            {},
            root_dir=root_dir,
        )
    assert "missing output_schema_path" in str(exc_info.value)


def test_list_codex_farm_models_uses_json_cli_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_run(command, **kwargs):  # noqa: ANN001
        captured["command"] = list(command)
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "slug": "gpt-5.3-codex",
                        "display_name": "GPT-5.3",
                        "description": "frontier",
                        "supported_reasoning_efforts": ["low", "medium"],
                    }
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    rows = list_codex_farm_models(cmd="/tmp/codex-farm")

    assert rows == [
        {
            "slug": "gpt-5.3-codex",
            "display_name": "GPT-5.3",
            "description": "frontier",
            "supported_reasoning_efforts": ["low", "medium"],
        }
    ]
    command = captured.get("command")
    assert isinstance(command, list)
    assert command == ["/tmp/codex-farm", "models", "list", "--json"]
    kwargs = captured.get("kwargs")
    assert isinstance(kwargs, dict)
    assert kwargs.get("text") is True
    assert kwargs.get("capture_output") is True
    assert kwargs.get("check") is False


def test_subprocess_runner_uses_run_errors_followup_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    (in_dir / "r0000.json").write_text("{}", encoding="utf-8")

    calls: list[list[str]] = []

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        argv = list(command)
        calls.append(argv)
        if argv[1:3] == ["process", "--pipeline"]:
            return SimpleNamespace(
                returncode=1,
                stdout=json.dumps(
                    {
                        "run_id": "run-123",
                        "status": "failed",
                        "exit_code": 1,
                        "output_schema_path": "schemas/recipe.chunking.v1.output.schema.json",
                    }
                ),
                stderr="pipeline failed",
            )
        if argv[1:3] == ["run", "errors"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "errors": [
                            {"message": "simulated worker error"},
                        ]
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    runner = SubprocessCodexFarmRunner(cmd="codex-farm")
    with pytest.raises(CodexFarmRunnerError) as exc_info:
        runner.run_pipeline("recipe.chunking.v1", in_dir, out_dir, {})

    assert "run-123" in str(exc_info.value)
    assert "simulated worker error" in str(exc_info.value)
    assert len(calls) == 2
    assert calls[1] == ["codex-farm", "run", "errors", "--run-id", "run-123", "--json"]


def test_ensure_codex_farm_pipelines_exist_queries_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "pack"
    pack_root.mkdir(parents=True, exist_ok=True)
    captured: dict[str, object] = {}

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        captured["command"] = list(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {"pipeline_id": "recipe.chunking.v1"},
                    {"pipeline_id": "recipe.schemaorg.v1"},
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    ensure_codex_farm_pipelines_exist(
        cmd="codex-farm",
        root_dir=pack_root,
        pipeline_ids=("recipe.chunking.v1",),
    )

    command = captured.get("command")
    assert isinstance(command, list)
    assert command == [
        "codex-farm",
        "pipelines",
        "list",
        "--root",
        str(pack_root),
        "--json",
    ]


def test_ensure_codex_farm_pipelines_exist_raises_for_missing_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "pack"
    pack_root.mkdir(parents=True, exist_ok=True)

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps([{"pipeline_id": "recipe.chunking.v1"}]),
            stderr="",
        )

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    with pytest.raises(CodexFarmRunnerError) as exc_info:
        ensure_codex_farm_pipelines_exist(
            cmd="codex-farm",
            root_dir=pack_root,
            pipeline_ids=("recipe.final.v1",),
        )
    assert "recipe.final.v1" in str(exc_info.value)
