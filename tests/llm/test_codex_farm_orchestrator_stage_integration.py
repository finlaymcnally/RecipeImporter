from __future__ import annotations

import tests.llm.test_codex_farm_orchestrator as _base

# Reuse shared imports/helpers from the base orchestrator test module.
globals().update({
    name: value
    for name, value in _base.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


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
    assert manifest["counts"]["pass2_degraded_soft"] == 0
    assert manifest["counts"]["pass2_degraded_hard"] == 0
    assert manifest["counts"]["pass3_ok"] == 1
    assert manifest["counts"]["pass3_execution_mode_llm"] == 1
    assert manifest["counts"]["pass3_execution_mode_deterministic"] == 0
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
    recipe_metrics = manifest["recipes"][result.recipes[0].identifier]["pass1_span_loss_metrics"]
    assert recipe_metrics["raw_span_count"] == 4
    assert recipe_metrics["clamped_span_count"] == 4
    assert recipe_metrics["clamped_block_loss_count"] == 0
    assert recipe_metrics["clamped_block_loss_ratio"] == 0.0
    assert recipe_metrics["boundaries_clamped"] is False
    recipe_row = manifest["recipes"][result.recipes[0].identifier]
    assert recipe_row["pass2_degradation_severity"] == "none"
    assert recipe_row["pass2_promotion_policy"] == "pass2_ok_llm_pass3"
    assert recipe_row["pass3_execution_mode"] == "llm"
    assert recipe_row["pass3_routing_reason"] == "pass2_ok_requires_llm"
    assert recipe_row["pass3_utility_signal"]["status"] == "pass2_ok"
    assert recipe_row["pass3_utility_signal"]["deterministic_low_risk"] is False
    assert manifest["counts"]["pass3_pass2_ok_utility_rows"] == 1
    assert manifest["counts"]["pass3_pass2_ok_skip_candidates"] == 0
    assert manifest["counts"]["pass3_pass2_ok_deterministic_skips"] == 0
    assert manifest["counts"]["pass3_pass2_ok_llm_calls"] == 1
    assert manifest["pass3_policy"]["pass2_ok_deterministic_skip_enabled"] is True


def test_orchestrator_accepts_full_text_lines_when_blocks_missing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    settings = _build_run_settings(tmp_path / "pack")
    result = _build_lines_only_conversion_result(source)
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
    manifest = json.loads((apply_result.llm_raw_dir / "llm_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["pass1_ok"] == 1
    assert manifest["counts"]["pass2_ok"] == 1
    assert manifest["counts"]["pass3_ok"] == 1


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
        run_config=RunSettings(llm_recipe_pipeline="off").to_run_config_dict(),
    )

    assert response["status"] == "success"
    assert orchestrator_called["value"] is False
