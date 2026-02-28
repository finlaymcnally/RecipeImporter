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
