from __future__ import annotations

import pytest

from cookimport.config.run_settings import (
    BUCKET2_INTERNAL_ONLY_RUN_SETTING_NAMES,
    RunSettings,
    benchmark_lab_run_setting_names,
    build_run_settings,
    compute_effective_workers,
    internal_run_setting_names,
    ordinary_operator_run_setting_names,
    public_run_setting_names,
    run_settings_ui_specs,
    summarize_run_config_payload,
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
        "multi_recipe_splitter",
        "multi_recipe_min_ingredient_lines",
        "multi_recipe_min_instruction_lines",
        "multi_recipe_for_the_guardrail",
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
        "pdf_ocr_policy",
        "pdf_column_gap_ratio",
        "llm_recipe_pipeline",
        "atomic_block_splitter",
        "line_role_pipeline",
        "llm_knowledge_pipeline",
        "llm_tags_pipeline",
        "codex_farm_recipe_mode",
        "codex_farm_cmd",
        "codex_farm_context_blocks",
        "codex_farm_knowledge_context_blocks",
        "tag_catalog_json",
        "codex_farm_failure_mode",
    )
    assert "bucket1_fixed_behavior_version" in run_config
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


def test_run_settings_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="Unknown run settings keys: unknown_new_field"):
        RunSettings.from_dict({"workers": 3, "unknown_new_field": "x"})


def test_run_settings_accepts_recipe_codex_farm_pipeline() -> None:
    settings = RunSettings.from_dict({"llm_recipe_pipeline": "codex-farm-3pass-v1"})

    assert settings.llm_recipe_pipeline.value == "codex-farm-3pass-v1"


def test_run_settings_accepts_merged_recipe_codex_farm_pipeline() -> None:
    settings = RunSettings.from_dict({"llm_recipe_pipeline": "codex-farm-2stage-repair-v1"})

    assert settings.llm_recipe_pipeline.value == "codex-farm-2stage-repair-v1"


def test_run_settings_defaults_use_compact_codex_farm_pass_pipelines() -> None:
    settings = RunSettings()

    assert settings.codex_farm_pipeline_pass2 == "recipe.schemaorg.compact.v1"
    assert settings.codex_farm_pipeline_pass3 == "recipe.final.compact.v1"
    assert settings.codex_farm_pipeline_pass4_knowledge == "recipe.knowledge.compact.v1"


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
    expected = set(public_run_setting_names())
    assert by_name == expected
    assert set(BUCKET2_INTERNAL_ONLY_RUN_SETTING_NAMES).isdisjoint(by_name)
    llm_recipe_spec = next(spec for spec in specs if spec.name == "llm_recipe_pipeline")
    assert llm_recipe_spec.choices == (
        "off",
        "codex-farm-3pass-v1",
        "codex-farm-2stage-repair-v1",
    )
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
    web_policy_spec = next(spec for spec in specs if spec.name == "web_schema_policy")
    assert web_policy_spec.choices == (
        "prefer_schema",
        "schema_only",
        "heuristic_only",
    )
    assert "multi_recipe_splitter" not in by_name
    assert "p6_time_backend" not in by_name
    assert "ocr_device" not in by_name
def test_bucket2_run_settings_are_internal_only() -> None:
    public_names = set(public_run_setting_names())
    internal_names = set(internal_run_setting_names())

    assert set(BUCKET2_INTERNAL_ONLY_RUN_SETTING_NAMES).isdisjoint(public_names)
    assert set(BUCKET2_INTERNAL_ONLY_RUN_SETTING_NAMES).issubset(internal_names)


def test_run_settings_contract_helpers_split_public_surface() -> None:
    public_names = set(public_run_setting_names())
    operator_names = set(ordinary_operator_run_setting_names())
    benchmark_lab_names = set(benchmark_lab_run_setting_names())

    assert operator_names
    assert benchmark_lab_names
    assert operator_names.isdisjoint(benchmark_lab_names)
    assert operator_names | benchmark_lab_names == public_names
    assert {
        "atomic_block_splitter",
        "line_role_pipeline",
        "codex_farm_model",
        "codex_farm_reasoning_effort",
    }.issubset(benchmark_lab_names)
    assert {
        "workers",
        "epub_extractor",
        "pdf_ocr_policy",
        "llm_recipe_pipeline",
        "codex_farm_cmd",
    }.issubset(operator_names)


def test_run_settings_ui_specs_include_internal_bucket2_fields_when_requested(
    monkeypatch,
) -> None:
    monkeypatch.delenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", raising=False)
    specs = run_settings_ui_specs(include_internal=True)
    by_name = {spec.name for spec in specs}

    assert set(BUCKET2_INTERNAL_ONLY_RUN_SETTING_NAMES).issubset(by_name)

    multi_recipe_spec = next(spec for spec in specs if spec.name == "multi_recipe_splitter")
    assert multi_recipe_spec.choices == ("legacy", "off", "rules_v1")
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


def test_bucket2_public_projection_and_summary_omit_internal_fields() -> None:
    payload = {
        "epub_extractor": "beautifulsoup",
        "workers": 3,
        "multi_recipe_splitter": "rules_v1",
        "ocr_device": "auto",
        "recipe_score_silver_min": 0.6,
    }

    settings = RunSettings.from_dict(payload, warn_context="bucket2 projection")

    full_payload = settings.to_run_config_dict()
    public_payload = settings.to_public_run_config_dict()

    assert full_payload["multi_recipe_splitter"] == "rules_v1"
    assert full_payload["ocr_device"] == "auto"
    assert full_payload["recipe_score_silver_min"] == 0.6
    assert "multi_recipe_splitter" not in public_payload
    assert "ocr_device" not in public_payload
    assert "recipe_score_silver_min" not in public_payload
    assert public_payload["epub_extractor"] == "beautifulsoup"

    summary = settings.summary()
    assert "epub_extractor=beautifulsoup" in summary
    assert "multi_recipe_splitter=" not in summary
    assert "ocr_device=" not in summary
    assert "recipe_score_silver_min=" not in summary

    internal_summary = summarize_run_config_payload(full_payload, include_internal=True)
    assert "multi_recipe_splitter=rules_v1" in internal_summary
    assert "ocr_device=auto" in internal_summary


def test_operator_and_benchmark_lab_projections_split_public_surface() -> None:
    payload = {
        "workers": 3,
        "epub_extractor": "beautifulsoup",
        "llm_recipe_pipeline": "codex-farm-3pass-v1",
        "atomic_block_splitter": "atomic-v1",
        "line_role_pipeline": "deterministic-v1",
        "codex_farm_model": "gpt-5.3-codex-spark",
        "multi_recipe_splitter": "rules_v1",
    }

    settings = RunSettings.from_dict(payload, warn_context="contract projection")

    operator_payload = settings.to_operator_run_config_dict()
    benchmark_lab_payload = settings.to_benchmark_lab_run_config_dict()

    assert operator_payload["workers"] == 3
    assert operator_payload["epub_extractor"] == "beautifulsoup"
    assert "atomic_block_splitter" not in operator_payload
    assert "line_role_pipeline" not in operator_payload
    assert "codex_farm_model" not in operator_payload
    assert "multi_recipe_splitter" not in operator_payload

    assert benchmark_lab_payload["atomic_block_splitter"] == "atomic-v1"
    assert benchmark_lab_payload["line_role_pipeline"] == "deterministic-v1"
    assert benchmark_lab_payload["codex_farm_model"] == "gpt-5.3-codex-spark"
    assert "workers" not in benchmark_lab_payload
    assert "multi_recipe_splitter" not in benchmark_lab_payload

    operator_summary = settings.summary(contract="operator")
    assert "workers=3" in operator_summary
    assert "epub_extractor=beautifulsoup" in operator_summary
    assert "atomic_block_splitter=" not in operator_summary
    assert "codex_farm_model=" not in operator_summary

    product_summary = settings.summary(contract="product")
    assert "atomic_block_splitter=atomic-v1" in product_summary
    assert "codex_farm_model=gpt-5.3-codex-spark" in product_summary
    assert "multi_recipe_splitter=" not in product_summary


def test_run_settings_rejects_stale_removed_setting_keys() -> None:
    with pytest.raises(ValueError, match="Unknown test retired setting keys: table_extraction"):
        RunSettings.from_dict(
            {"table_extraction": "off", "workers": 3},
            warn_context="test retired setting",
        )


def test_run_settings_ui_specs_include_recipe_codex_farm_without_env_gate() -> None:
    specs = run_settings_ui_specs()
    llm_recipe_spec = next(spec for spec in specs if spec.name == "llm_recipe_pipeline")

    assert llm_recipe_spec.choices == (
        "off",
        "codex-farm-3pass-v1",
        "codex-farm-2stage-repair-v1",
    )


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


def test_run_settings_rejects_removed_auto_extractor() -> None:
    with pytest.raises(Exception):
        RunSettings.from_dict({"epub_extractor": "auto"}, warn_context="test")


def test_run_settings_rejects_removed_legacy_extractor() -> None:
    with pytest.raises(Exception):
        RunSettings.from_dict({"epub_extractor": "legacy"}, warn_context="test")


def test_run_settings_forces_markdown_extractors_off_by_default() -> None:
    settings = RunSettings.from_dict({"epub_extractor": "markdown"}, warn_context="test")

    assert settings.epub_extractor.value == "unstructured"


def test_run_settings_allows_markdown_extractors_when_policy_enabled(monkeypatch) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    settings = RunSettings.from_dict({"epub_extractor": "markitdown"}, warn_context="test")

    assert settings.epub_extractor.value == "markitdown"
