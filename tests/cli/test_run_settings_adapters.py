from __future__ import annotations

from pathlib import Path

from cookimport.config.run_settings import RunSettings
from cookimport.config.run_settings_adapters import (
    build_benchmark_call_kwargs_from_run_settings,
    build_stage_call_kwargs_from_run_settings,
)


def test_build_stage_call_kwargs_propagates_webschema_fields() -> None:
    settings = RunSettings(
        multi_recipe_splitter="rules_v1",
        multi_recipe_trace=True,
        multi_recipe_min_ingredient_lines=2,
        multi_recipe_min_instruction_lines=3,
        multi_recipe_for_the_guardrail=False,
        instruction_step_segmentation_policy="always",
        instruction_step_segmenter="heuristic_v1",
        web_schema_extractor="extruct",
        web_schema_normalizer="pyld",
        web_html_text_extractor="justext",
        web_schema_policy="schema_only",
        web_schema_min_confidence=0.82,
        web_schema_min_ingredients=3,
        web_schema_min_instruction_steps=2,
        p6_time_backend="hybrid_regex_quantulum3_v1",
        p6_time_total_strategy="selective_sum_v1",
        p6_temperature_backend="quantulum3_v1",
        p6_temperature_unit_backend="pint_v1",
        p6_ovenlike_mode="off",
        p6_yield_mode="scored_v1",
        p6_emit_metadata_debug=True,
        pdf_ocr_policy="always",
        pdf_column_gap_ratio=0.2,
    )

    kwargs = build_stage_call_kwargs_from_run_settings(
        settings,
        out=Path("/tmp/out"),
        mapping=None,
        overrides=None,
        limit=None,
        write_markdown=False,
    )

    assert kwargs["multi_recipe_splitter"] == "rules_v1"
    assert kwargs["multi_recipe_trace"] is True
    assert kwargs["multi_recipe_min_ingredient_lines"] == 2
    assert kwargs["multi_recipe_min_instruction_lines"] == 3
    assert kwargs["multi_recipe_for_the_guardrail"] is False
    assert kwargs["instruction_step_segmentation_policy"] == "always"
    assert kwargs["instruction_step_segmenter"] == "heuristic_v1"
    assert kwargs["web_schema_extractor"] == "extruct"
    assert kwargs["web_schema_normalizer"] == "pyld"
    assert kwargs["web_html_text_extractor"] == "justext"
    assert kwargs["web_schema_policy"] == "schema_only"
    assert kwargs["web_schema_min_confidence"] == 0.82
    assert kwargs["web_schema_min_ingredients"] == 3
    assert kwargs["web_schema_min_instruction_steps"] == 2
    assert kwargs["p6_time_backend"] == "hybrid_regex_quantulum3_v1"
    assert kwargs["p6_time_total_strategy"] == "selective_sum_v1"
    assert kwargs["p6_temperature_backend"] == "quantulum3_v1"
    assert kwargs["p6_temperature_unit_backend"] == "pint_v1"
    assert kwargs["p6_ovenlike_mode"] == "off"
    assert kwargs["p6_yield_mode"] == "scored_v1"
    assert kwargs["p6_emit_metadata_debug"] is True
    assert kwargs["pdf_ocr_policy"] == "always"
    assert kwargs["pdf_column_gap_ratio"] == 0.2


def test_build_benchmark_call_kwargs_propagates_webschema_fields() -> None:
    settings = RunSettings(
        multi_recipe_splitter="rules_v1",
        multi_recipe_trace=True,
        multi_recipe_min_ingredient_lines=2,
        multi_recipe_min_instruction_lines=2,
        multi_recipe_for_the_guardrail=True,
        instruction_step_segmentation_policy="off",
        instruction_step_segmenter="pysbd_v1",
        web_schema_extractor="recipe_scrapers",
        web_schema_normalizer="simple",
        web_html_text_extractor="boilerpy3",
        web_schema_policy="heuristic_only",
        web_schema_min_confidence=0.5,
        web_schema_min_ingredients=1,
        web_schema_min_instruction_steps=1,
        p6_time_backend="quantulum3_v1",
        p6_time_total_strategy="max_v1",
        p6_temperature_backend="hybrid_regex_quantulum3_v1",
        p6_temperature_unit_backend="builtin_v1",
        p6_ovenlike_mode="keywords_v1",
        p6_yield_mode="legacy_v1",
        p6_emit_metadata_debug=False,
        pdf_ocr_policy="off",
        pdf_column_gap_ratio=0.09,
        atomic_block_splitter="atomic-v1",
        line_role_pipeline="deterministic-v1",
        codex_farm_recipe_mode="benchmark",
        codex_farm_model="gpt-5.3-codex-spark",
        codex_farm_reasoning_effort="low",
    )

    kwargs = build_benchmark_call_kwargs_from_run_settings(
        settings,
        output_dir=Path("/tmp/output"),
        eval_output_dir=Path("/tmp/eval"),
        eval_mode="canonical-text",
        execution_mode="legacy",
        no_upload=True,
        write_markdown=True,
        write_label_studio_tasks=False,
    )

    assert kwargs["multi_recipe_splitter"] == "rules_v1"
    assert kwargs["multi_recipe_trace"] is True
    assert kwargs["multi_recipe_min_ingredient_lines"] == 2
    assert kwargs["multi_recipe_min_instruction_lines"] == 2
    assert kwargs["multi_recipe_for_the_guardrail"] is True
    assert kwargs["instruction_step_segmentation_policy"] == "off"
    assert kwargs["instruction_step_segmenter"] == "pysbd_v1"
    assert kwargs["web_schema_extractor"] == "recipe_scrapers"
    assert kwargs["web_schema_normalizer"] == "simple"
    assert kwargs["web_html_text_extractor"] == "boilerpy3"
    assert kwargs["web_schema_policy"] == "heuristic_only"
    assert kwargs["web_schema_min_confidence"] == 0.5
    assert kwargs["web_schema_min_ingredients"] == 1
    assert kwargs["web_schema_min_instruction_steps"] == 1
    assert kwargs["p6_time_backend"] == "quantulum3_v1"
    assert kwargs["p6_time_total_strategy"] == "max_v1"
    assert kwargs["p6_temperature_backend"] == "hybrid_regex_quantulum3_v1"
    assert kwargs["p6_temperature_unit_backend"] == "builtin_v1"
    assert kwargs["p6_ovenlike_mode"] == "keywords_v1"
    assert kwargs["p6_yield_mode"] == "legacy_v1"
    assert kwargs["p6_emit_metadata_debug"] is False
    assert kwargs["pdf_ocr_policy"] == "off"
    assert kwargs["pdf_column_gap_ratio"] == 0.09
    assert kwargs["atomic_block_splitter"] == "atomic-v1"
    assert kwargs["line_role_pipeline"] == "deterministic-v1"
    assert kwargs["codex_farm_recipe_mode"] == "benchmark"
    assert kwargs["codex_farm_model"] == "gpt-5.3-codex-spark"
    assert kwargs["codex_farm_reasoning_effort"] == "low"
