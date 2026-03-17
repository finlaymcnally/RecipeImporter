from __future__ import annotations

import pytest

from cookimport.analytics import compare_control_engine as engine


def _confounded_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for _ in range(1):
        records.append({"strict_accuracy": 0.2, "compare_group": "A", "stratum": "S1"})
    for _ in range(9):
        records.append({"strict_accuracy": 0.3, "compare_group": "B", "stratum": "S1"})
    for _ in range(9):
        records.append({"strict_accuracy": 0.9, "compare_group": "A", "stratum": "S2"})
    for _ in range(1):
        records.append({"strict_accuracy": 1.0, "compare_group": "B", "stratum": "S2"})
    return records


def _insight_records() -> list[dict[str, object]]:
    return [
        {
            "strict_accuracy": 0.82,
            "macro_f1_excluding_other": 0.70,
            "source_file": "/tmp/books/book-a.epub",
            "importer_name": "epub",
            "artifact_dir": "/tmp/golden/benchmark-vs-golden/2026-03-03_23.00.00/single-offline-benchmark/book-a/codexfarm",
            "processed_report_path": "/tmp/out/run-a/report-a.json",
            "run_config": {
                "llm_recipe_pipeline": "codex-recipe-shard-v1",
                "line_role_pipeline": "codex-line-role-shard-v1",
                "atomic_block_splitter": "atomic-v1",
                "codex_farm_model": "gpt-5",
                "codex_farm_reasoning_effort": "medium",
            },
            "tokens_input": 900000,
            "tokens_cached_input": 200000,
            "tokens_output": 100000,
            "tokens_total": 1000000,
        },
        {
            "strict_accuracy": 0.79,
            "macro_f1_excluding_other": 0.66,
            "source_file": "/tmp/books/book-b.epub",
            "importer_name": "epub",
            "artifact_dir": "/tmp/golden/benchmark-vs-golden/2026-03-03_23.00.00/single-offline-benchmark/book-b/codexfarm",
            "processed_report_path": "/tmp/out/run-b/report-b.json",
            "run_config": {
                "llm_recipe_pipeline": "codex-recipe-shard-v1",
                "line_role_pipeline": "codex-line-role-shard-v1",
                "atomic_block_splitter": "atomic-v1",
                "codex_farm_model": "gpt-5",
                "codex_farm_reasoning_effort": "low",
            },
            "tokens_input": 850000,
            "tokens_cached_input": 220000,
            "tokens_output": 90000,
            "tokens_total": 940000,
        },
        {
            "strict_accuracy": 0.58,
            "macro_f1_excluding_other": 0.48,
            "source_file": "/tmp/books/book-a.epub",
            "importer_name": "epub",
            "artifact_dir": "/tmp/golden/benchmark-vs-golden/2026-03-03_23.00.00/single-offline-benchmark/book-a/vanilla",
            "processed_report_path": "/tmp/out/run-c/report-c.json",
            "run_config": {
                "llm_recipe_pipeline": "off",
                "line_role_pipeline": "off",
                "atomic_block_splitter": "off",
            },
            "tokens_input": 0,
            "tokens_cached_input": 0,
            "tokens_output": 0,
            "tokens_total": 0,
        },
        {
            "strict_accuracy": 0.60,
            "macro_f1_excluding_other": 0.50,
            "source_file": "/tmp/books/book-b.epub",
            "importer_name": "epub",
            "artifact_dir": "/tmp/golden/benchmark-vs-golden/2026-03-03_23.00.00/single-offline-benchmark/book-b/vanilla",
            "processed_report_path": "/tmp/out/run-d/report-d.json",
            "run_config": {
                "llm_recipe_pipeline": "off",
                "line_role_pipeline": "off",
                "atomic_block_splitter": "off",
            },
            "tokens_input": 0,
            "tokens_cached_input": 0,
            "tokens_output": 0,
            "tokens_total": 0,
        },
    ]


def test_previous_runs_field_value_resolves_derived_fields() -> None:
    record = {
        "source_file": "/tmp/books/my-book.epub",
        "artifact_dir": (
            "/tmp/golden/benchmark-vs-golden/2026-03-03_23.00.00/"
            "single-offline-benchmark/my-book/codexfarm"
        ),
        "tokens_input": 1000,
        "tokens_cached_input": 200,
        "tokens_output": 300,
        "tokens_total": 1300,
        "recipes": 4,
        "run_config": {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_model": "gpt-5",
            "codex_farm_reasoning_effort": "medium",
            "single_offline_split_cache": {
                "conversion_seconds": 20,
            },
        },
    }

    assert engine.previous_runs_field_value(record, "source_label") == "my-book.epub"
    assert engine.previous_runs_field_value(record, "ai_model") == "gpt-5"
    assert engine.previous_runs_field_value(record, "ai_effort") == "medium"
    assert engine.previous_runs_field_value(record, "all_method_record") is False
    assert engine.previous_runs_field_value(record, "speed_suite_record") is False
    assert engine.previous_runs_field_value(record, "all_token_use") == pytest.approx(1120.0)
    assert engine.previous_runs_field_value(record, "conversion_seconds_per_recipe") == pytest.approx(
        5.0
    )
    assert engine.previous_runs_field_value(record, "all_token_use_per_recipe") == pytest.approx(
        280.0
    )


def test_ai_model_label_system_error_for_runtime_failure() -> None:
    record = {
        "artifact_dir": (
            "/tmp/golden/benchmark-vs-golden/2026-03-03_23.00.00/"
            "single-offline-benchmark/my-book/codexfarm"
        ),
        "run_config": {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_model": "gpt-5",
            "codex_farm_runtime_error": (
                "codex-farm failed for recipe.schemaorg.v1 (subprocess_exit=124)"
            ),
        },
    }
    assert engine.ai_model_label_for_record(record) == "System error"
    assert engine.previous_runs_field_value(record, "ai_model") == "System error"


def test_benchmark_semantics_distinguish_official_and_hybrid_rows() -> None:
    deterministic_official = {
        "artifact_dir": (
            "/tmp/golden/benchmark-vs-golden/2026-03-03_23.00.00/"
            "single-offline-benchmark/my-book/vanilla"
        ),
        "run_config": {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
        },
    }
    full_stack_official = {
        "artifact_dir": (
            "/tmp/golden/benchmark-vs-golden/2026-03-03_23.00.00/"
            "single-offline-benchmark/my-book/codexfarm"
        ),
        "run_config": {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "codex-line-role-shard-v1",
        },
    }
    line_role_only = {
        "artifact_dir": "/tmp/qualitysuite/my-book/eval",
        "run_config": {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "codex-line-role-shard-v1",
        },
    }
    deterministic_line_role = {
        "artifact_dir": "/tmp/qualitysuite/my-book/eval",
        "run_config": {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "deterministic-v1",
        },
    }
    recipe_only = {
        "artifact_dir": "/tmp/qualitysuite/my-book/eval",
        "run_config": {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "off",
        },
    }
    unknown = {
        "artifact_dir": "/tmp/qualitysuite/my-book/eval",
        "run_config": {},
    }
    runtime_error_record = {
        "artifact_dir": (
            "/tmp/golden/benchmark-vs-golden/2026-03-03_23.00.00/"
            "single-offline-benchmark/my-book/codexfarm"
        ),
        "run_config": {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "off",
            "codex_farm_runtime_error": "codex auth failed",
        },
    }

    assert engine.benchmark_variant_for_record(deterministic_official) == "vanilla"
    assert engine.ai_assistance_profile_for_record(deterministic_official) == "deterministic"
    assert engine.ai_effort_label_for_record(deterministic_official) == "AI off"
    assert engine.previous_runs_field_value(deterministic_official, "ai_effort") == "AI off"

    assert engine.benchmark_variant_for_record(full_stack_official) == "codexfarm"
    assert engine.ai_assistance_profile_for_record(full_stack_official) == "full_stack"
    assert engine.previous_runs_field_value(full_stack_official, "ai_assistance_profile") == (
        "Full-stack AI"
    )

    assert engine.benchmark_variant_for_record(line_role_only) == "line_role_only"
    assert engine.ai_assistance_profile_for_record(line_role_only) == "line_role_only"
    assert engine.ai_effort_label_for_record(line_role_only) == "Line-role only"
    assert engine.ai_model_label_for_record(line_role_only) == "-"

    assert engine.benchmark_variant_for_record(deterministic_line_role) == "deterministic"
    assert engine.ai_assistance_profile_for_record(deterministic_line_role) == "deterministic"
    assert engine.ai_effort_label_for_record(deterministic_line_role) == "AI off"

    assert engine.benchmark_variant_for_record(recipe_only) == "recipe_only"
    assert engine.ai_assistance_profile_for_record(recipe_only) == "recipe_only"
    assert engine.ai_effort_label_for_record(recipe_only) == "Recipe only"

    assert engine.benchmark_variant_for_record(unknown) == "other"
    assert engine.ai_assistance_profile_for_record(unknown) == "other"
    assert engine.ai_effort_label_for_record(unknown) == "Unknown"

    assert engine.ai_model_label_for_record(runtime_error_record) == "System error"
    assert engine.ai_effort_label_for_record(runtime_error_record) == "Recipe only"


def test_controlled_categorical_standardizes_strata() -> None:
    records = _confounded_records()
    field_options = engine.collect_benchmark_field_paths(records)

    raw = engine.analyze_compare_control_categorical_raw(
        records,
        "strict_accuracy",
        "compare_group",
        field_options,
    )
    controlled = engine.analyze_compare_control_categorical_controlled(
        records,
        "strict_accuracy",
        "compare_group",
        ["stratum"],
        field_options,
    )

    raw_by_group = {group["key"]: group for group in raw["groups"]}
    controlled_by_group = {group["key"]: group for group in controlled["groups"]}

    assert raw_by_group["A"]["outcome_mean"] > raw_by_group["B"]["outcome_mean"]
    assert controlled_by_group["B"]["outcome_mean"] > controlled_by_group["A"]["outcome_mean"]
    assert controlled["used_strata"] == 2
    assert controlled["total_strata"] == 2


def test_secondary_metrics_skip_constant_fields() -> None:
    records = [
        {
            "strict_accuracy": 0.60,
            "compare_group": "A",
            "benchmark_total_seconds": 0.0,
            "benchmark_prediction_seconds": 0.0,
            "benchmark_evaluation_seconds": 0.0,
            "tokens_total": 1000,
        },
        {
            "strict_accuracy": 0.62,
            "compare_group": "A",
            "benchmark_total_seconds": 0.0,
            "benchmark_prediction_seconds": 0.0,
            "benchmark_evaluation_seconds": 0.0,
            "tokens_total": 1200,
        },
        {
            "strict_accuracy": 0.58,
            "compare_group": "B",
            "benchmark_total_seconds": 0.0,
            "benchmark_prediction_seconds": 0.0,
            "benchmark_evaluation_seconds": 0.0,
            "tokens_total": 800,
        },
        {
            "strict_accuracy": 0.57,
            "compare_group": "B",
            "benchmark_total_seconds": 0.0,
            "benchmark_prediction_seconds": 0.0,
            "benchmark_evaluation_seconds": 0.0,
            "tokens_total": 900,
        },
    ]
    field_options = engine.collect_benchmark_field_paths(records)
    raw = engine.analyze_compare_control_categorical_raw(
        records,
        "strict_accuracy",
        "compare_group",
        field_options,
    )
    secondary_fields = set(raw["secondary_fields"])
    assert "benchmark_total_seconds" not in secondary_fields
    assert "benchmark_prediction_seconds" not in secondary_fields
    assert "benchmark_evaluation_seconds" not in secondary_fields
    assert "all_token_use" in secondary_fields
    assert "tokens_total" in secondary_fields


def test_apply_filters_invalid_regex_returns_structured_error() -> None:
    records = [{"strict_accuracy": 0.5, "compare_group": "codexfarm"}]
    with pytest.raises(engine.CompareControlError) as exc_info:
        engine.apply_filters(
            records,
            {
                "quick_filters": {
                    "official_full_golden_only": False,
                    "exclude_ai_tests": False,
                },
                "column_filters": {
                    "compare_group": {
                        "mode": "or",
                        "clauses": [{"operator": "regex", "value": "("}],
                    }
                },
            },
        )

    err = exc_info.value
    assert err.code == "invalid_filter_regex"
    assert err.details["field"] == "compare_group"


def test_build_subset_filter_patch_uses_eq_or_contract() -> None:
    patch = engine.build_subset_filter_patch(
        "ai_model",
        ["gpt-5", "gpt-5-mini"],
    )

    assert patch["compare_field"] == "ai_model"
    assert patch["column_filter_mode"] == "or"
    assert patch["clauses"] == [
        {"operator": "eq", "value": "gpt-5"},
        {"operator": "eq", "value": "gpt-5-mini"},
    ]


def test_generate_insights_returns_actionable_profile() -> None:
    insights = engine.generate_insights(
        _insight_records(),
        {
            "outcome_field": "strict_accuracy",
            "filters": {
                "quick_filters": {
                    "official_full_golden_only": False,
                    "exclude_ai_tests": False,
                }
            },
        },
    )

    assert insights["candidate_rows"] == 4
    assert insights["compare_field"] == "ai_model"
    assert insights["comparisons"]["raw"]["type"] == "categorical"
    assert insights["model_efficiency"]["groups"]
    assert insights["suggested_queries"]
    assert any(
        item.get("field") == "ai_model"
        for item in insights["drivers"]["actionable_top"]
    )
    assert any(
        item.get("field") == "processed_report_path"
        for item in insights["drivers"]["ignored_high_cardinality"]
    )


def test_generate_insights_surfaces_controlled_coverage_warning() -> None:
    insights = engine.generate_insights(
        _insight_records(),
        {
            "outcome_field": "strict_accuracy",
            "compare_field": "ai_model",
            "hold_constant_fields": ["processed_report_path"],
            "filters": {
                "quick_filters": {
                    "official_full_golden_only": False,
                    "exclude_ai_tests": False,
                }
            },
        },
    )

    warnings = insights["comparisons"]["controlled_warnings"]
    assert warnings
    assert "No comparable rows remained" in warnings[0]


def test_analyze_discover_respects_discovery_preferences() -> None:
    result = engine.analyze(
        _insight_records(),
        {
            "view_mode": "discover",
            "outcome_field": "strict_accuracy",
            "discovery_preferences": {
                "exclude_fields": ["processed_report_path"],
                "prefer_fields": ["ai_model"],
                "demote_patterns": ["run_config."],
                "max_cards": 3,
            },
            "filters": {
                "quick_filters": {
                    "official_full_golden_only": False,
                    "exclude_ai_tests": False,
                }
            },
        },
    )

    assert result["view_mode"] == "discover"
    assert result["discovery_preferences"]["max_cards"] == 3
    items = result["analysis"]["items"]
    assert len(items) <= 3
    fields = [str(item.get("field") or "") for item in items]
    assert "processed_report_path" not in fields
    assert "ai_model" in fields
