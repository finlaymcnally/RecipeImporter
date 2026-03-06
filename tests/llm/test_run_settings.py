from __future__ import annotations

from cookimport.config.run_settings import (
    RunSettings,
    build_run_settings,
    compute_effective_workers,
    run_settings_ui_specs,
)


def _serialized(value):
    return getattr(value, "value", value)


def test_run_settings_default_serialization_matches_current_field_values() -> None:
    settings = RunSettings()
    run_config = settings.to_run_config_dict()

    assert settings.stable_hash() == settings.stable_hash()
    assert settings.short_hash() == settings.stable_hash()[:12]

    representative_fields = (
        "epub_extractor",
        "epub_unstructured_html_parser_version",
        "epub_unstructured_skip_headers_footers",
        "epub_unstructured_preprocess_mode",
        "table_extraction",
        "section_detector_backend",
        "multi_recipe_splitter",
        "multi_recipe_trace",
        "multi_recipe_min_ingredient_lines",
        "multi_recipe_min_instruction_lines",
        "multi_recipe_for_the_guardrail",
        "instruction_step_segmentation_policy",
        "instruction_step_segmenter",
        "web_schema_extractor",
        "web_schema_normalizer",
        "web_html_text_extractor",
        "web_schema_policy",
        "web_schema_min_confidence",
        "web_schema_min_ingredients",
        "web_schema_min_instruction_steps",
        "ingredient_text_fix_backend",
        "ingredient_pre_normalize_mode",
        "ingredient_packaging_mode",
        "ingredient_parser_backend",
        "ingredient_unit_canonicalizer",
        "ingredient_missing_unit_policy",
        "p6_time_backend",
        "p6_time_total_strategy",
        "p6_temperature_backend",
        "p6_temperature_unit_backend",
        "p6_ovenlike_mode",
        "p6_yield_mode",
        "p6_emit_metadata_debug",
        "pdf_ocr_policy",
        "pdf_column_gap_ratio",
        "llm_recipe_pipeline",
        "atomic_block_splitter",
        "line_role_pipeline",
        "llm_knowledge_pipeline",
        "llm_tags_pipeline",
        "codex_farm_recipe_mode",
        "codex_farm_cmd",
        "codex_farm_pass1_pattern_hints_enabled",
        "codex_farm_pipeline_pass1",
        "codex_farm_pipeline_pass2",
        "codex_farm_pipeline_pass3",
        "codex_farm_pass3_skip_pass2_ok",
        "codex_farm_benchmark_selective_retry_enabled",
        "codex_farm_benchmark_selective_retry_max_attempts",
        "codex_farm_pipeline_pass4_knowledge",
        "codex_farm_pipeline_pass5_tags",
        "codex_farm_context_blocks",
        "codex_farm_knowledge_context_blocks",
        "tag_catalog_json",
        "codex_farm_failure_mode",
    )
    for field_name in representative_fields:
        assert run_config[field_name] == _serialized(getattr(settings, field_name))

    assert "codex_farm_workspace_root" not in run_config

    summary = settings.summary()
    assert f"workers={settings.workers}" in summary
    assert (
        f"llm_recipe_pipeline={_serialized(settings.llm_recipe_pipeline)}" in summary
    )
    assert (
        f"line_role_pipeline={_serialized(settings.line_role_pipeline)}" in summary
    )


def test_run_settings_schema_evolution_ignores_unknown_keys() -> None:
    settings = RunSettings.from_dict({"workers": 3, "unknown_new_field": "x"})

    assert settings.workers == 3
    assert settings.pdf_split_workers == 7
    assert "unknown_new_field" not in settings.to_run_config_dict()


def test_run_settings_accepts_recipe_codex_farm_pipeline() -> None:
    settings = RunSettings.from_dict({"llm_recipe_pipeline": "codex-farm-3pass-v1"})

    assert settings.llm_recipe_pipeline.value == "codex-farm-3pass-v1"


def test_run_settings_defaults_use_compact_codex_farm_pass_pipelines() -> None:
    settings = RunSettings()

    assert settings.codex_farm_pipeline_pass2 == "recipe.schemaorg.compact.v1"
    assert settings.codex_farm_pipeline_pass3 == "recipe.final.compact.v1"


def test_build_run_settings_defaults_match_safe_run_settings_defaults() -> None:
    settings = build_run_settings(
        workers=2,
        pdf_split_workers=2,
        epub_split_workers=2,
        pdf_pages_per_job=10,
        epub_spine_items_per_job=5,
        epub_extractor="unstructured",
        ocr_device="auto",
        ocr_batch_size=1,
        warm_models=False,
    )

    assert settings.llm_recipe_pipeline.value == "off"
    assert settings.atomic_block_splitter.value == "off"
    assert settings.line_role_pipeline.value == "off"


def test_run_settings_accepts_codex_farm_recipe_mode_aliases() -> None:
    assert (
        RunSettings.from_dict({"codex_farm_recipe_mode": "line-label"}).codex_farm_recipe_mode
        == "benchmark"
    )
    assert (
        RunSettings.from_dict({"codex_farm_recipe_mode": "line-labels"}).codex_farm_recipe_mode
        == "benchmark"
    )
    assert (
        RunSettings.from_dict({"codex_farm_recipe_mode": "default"}).codex_farm_recipe_mode
        == "extract"
    )


def test_run_settings_ui_specs_cover_all_editable_fields(monkeypatch) -> None:
    monkeypatch.delenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", raising=False)
    specs = run_settings_ui_specs()
    by_name = {spec.name for spec in specs}
    expected = {
        name
        for name, field in RunSettings.model_fields.items()
        if not dict(field.json_schema_extra or {}).get("ui_hidden")
    }
    assert by_name == expected
    llm_recipe_spec = next(spec for spec in specs if spec.name == "llm_recipe_pipeline")
    assert llm_recipe_spec.choices == ("off", "codex-farm-3pass-v1")
    atomic_block_splitter_spec = next(
        spec for spec in specs if spec.name == "atomic_block_splitter"
    )
    assert atomic_block_splitter_spec.choices == ("off", "atomic-v1")
    line_role_pipeline_spec = next(
        spec for spec in specs if spec.name == "line_role_pipeline"
    )
    assert line_role_pipeline_spec.choices == (
        "off",
        "deterministic-v1",
        "codex-line-role-v1",
    )
    codex_farm_recipe_mode_spec = next(
        spec for spec in specs if spec.name == "codex_farm_recipe_mode"
    )
    assert codex_farm_recipe_mode_spec.choices == ("extract", "benchmark")
    llm_tags_spec = next(spec for spec in specs if spec.name == "llm_tags_pipeline")
    assert llm_tags_spec.choices == ("off", "codex-farm-tags-v1")
    epub_extractor_spec = next(spec for spec in specs if spec.name == "epub_extractor")
    assert epub_extractor_spec.choices == ("unstructured", "beautifulsoup")
    section_backend_spec = next(
        spec for spec in specs if spec.name == "section_detector_backend"
    )
    assert section_backend_spec.choices == ("legacy", "shared_v1")
    multi_recipe_spec = next(spec for spec in specs if spec.name == "multi_recipe_splitter")
    assert multi_recipe_spec.choices == ("legacy", "off", "rules_v1")
    segmentation_policy_spec = next(
        spec for spec in specs if spec.name == "instruction_step_segmentation_policy"
    )
    assert segmentation_policy_spec.choices == ("off", "auto", "always")
    segmenter_spec = next(
        spec for spec in specs if spec.name == "instruction_step_segmenter"
    )
    assert segmenter_spec.choices == ("heuristic_v1", "pysbd_v1")
    web_policy_spec = next(spec for spec in specs if spec.name == "web_schema_policy")
    assert web_policy_spec.choices == (
        "prefer_schema",
        "schema_only",
        "heuristic_only",
    )
    p6_time_backend_spec = next(spec for spec in specs if spec.name == "p6_time_backend")
    assert p6_time_backend_spec.choices == (
        "regex_v1",
        "quantulum3_v1",
        "hybrid_regex_quantulum3_v1",
    )
    p6_time_strategy_spec = next(
        spec for spec in specs if spec.name == "p6_time_total_strategy"
    )
    assert p6_time_strategy_spec.choices == (
        "sum_all_v1",
        "max_v1",
        "selective_sum_v1",
    )
    p6_yield_mode_spec = next(spec for spec in specs if spec.name == "p6_yield_mode")
    assert p6_yield_mode_spec.choices == ("legacy_v1", "scored_v1")


def test_run_settings_ui_specs_include_recipe_codex_farm_without_env_gate() -> None:
    specs = run_settings_ui_specs()
    llm_recipe_spec = next(spec for spec in specs if spec.name == "llm_recipe_pipeline")

    assert llm_recipe_spec.choices == ("off", "codex-farm-3pass-v1")


def test_compute_effective_workers_does_not_promote_markitdown_epub_splits() -> None:
    effective = compute_effective_workers(
        workers=4,
        epub_split_workers=12,
        epub_extractor="markitdown",
        all_epub=True,
    )

    assert effective == 4


def test_compute_effective_workers_promotes_unstructured_epub_splits() -> None:
    effective = compute_effective_workers(
        workers=4,
        epub_split_workers=12,
        epub_extractor="unstructured",
        all_epub=True,
    )

    assert effective == 12


def test_run_settings_migrates_auto_extractor_to_unstructured() -> None:
    settings = RunSettings.from_dict({"epub_extractor": "auto"}, warn_context="test")

    assert settings.epub_extractor.value == "unstructured"


def test_run_settings_migrates_legacy_extractor_to_beautifulsoup() -> None:
    settings = RunSettings.from_dict({"epub_extractor": "legacy"}, warn_context="test")

    assert settings.epub_extractor.value == "beautifulsoup"


def test_run_settings_forces_markdown_extractors_off_by_default() -> None:
    settings = RunSettings.from_dict({"epub_extractor": "markdown"}, warn_context="test")

    assert settings.epub_extractor.value == "unstructured"


def test_run_settings_allows_markdown_extractors_when_policy_enabled(monkeypatch) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    settings = RunSettings.from_dict({"epub_extractor": "markitdown"}, warn_context="test")

    assert settings.epub_extractor.value == "markitdown"
