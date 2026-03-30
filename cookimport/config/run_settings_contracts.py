from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

RUN_SETTING_SURFACE_PUBLIC = "public"
RUN_SETTING_SURFACE_INTERNAL = "internal"
RUN_SETTING_CONTRACT_FULL = "full"
RUN_SETTING_CONTRACT_PRODUCT = "product"
RUN_SETTING_CONTRACT_OPERATOR = "operator"
RUN_SETTING_CONTRACT_BENCHMARK_LAB = "benchmark_lab"
RUN_SETTING_CONTRACT_INTERNAL = "internal"

BENCHMARK_LAB_RUN_SETTING_NAMES = (
    "epub_unstructured_html_parser_version",
    "epub_unstructured_skip_headers_footers",
    "epub_unstructured_preprocess_mode",
    "web_schema_normalizer",
    "web_html_text_extractor",
    "web_schema_min_confidence",
    "web_schema_min_ingredients",
    "web_schema_min_instruction_steps",
    "atomic_block_splitter",
    "line_role_pipeline",
    "codex_farm_recipe_mode",
    "codex_farm_model",
    "codex_farm_reasoning_effort",
)

_SUMMARY_ORDER = (
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
    "recipe_scorer_backend",
    "recipe_score_gold_min",
    "recipe_score_silver_min",
    "recipe_score_bronze_min",
    "recipe_score_min_ingredient_lines",
    "recipe_score_min_instruction_lines",
    "pdf_column_gap_ratio",
    "pdf_ocr_policy",
    "ocr_device",
    "ocr_batch_size",
    "workers",
    "effective_workers",
    "pdf_split_workers",
    "epub_split_workers",
    "pdf_pages_per_job",
    "epub_spine_items_per_job",
    "warm_models",
    "llm_recipe_pipeline",
    "recipe_prompt_target_count",
    "llm_knowledge_pipeline",
    "knowledge_prompt_target_count",
    "knowledge_packet_input_char_budget",
    "knowledge_packet_output_char_budget",
    "line_role_pipeline",
    "line_role_prompt_target_count",
    "codex_farm_cmd",
    "codex_farm_model",
    "codex_farm_reasoning_effort",
    "codex_farm_root",
    "codex_farm_workspace_root",
    "codex_farm_context_blocks",
    "codex_farm_knowledge_context_blocks",
    "codex_farm_recipe_mode",
    "codex_farm_failure_mode",
)

_CONFIGURED_RUN_SETTING_NAMES: tuple[str, ...] = ()
_CONFIGURED_RUN_SETTING_SURFACES: dict[str, str] = {}


def configure_run_setting_contracts(
    *,
    ordered_field_names: tuple[str, ...],
    surface_by_field_name: Mapping[str, str],
) -> None:
    global _CONFIGURED_RUN_SETTING_NAMES, _CONFIGURED_RUN_SETTING_SURFACES

    _CONFIGURED_RUN_SETTING_NAMES = tuple(ordered_field_names)
    _CONFIGURED_RUN_SETTING_SURFACES = {
        str(name): str(surface).strip().lower() or RUN_SETTING_SURFACE_PUBLIC
        for name, surface in surface_by_field_name.items()
    }


def _require_configured_run_setting_names() -> tuple[str, ...]:
    if not _CONFIGURED_RUN_SETTING_NAMES:
        raise RuntimeError(
            "Run-setting contracts are not configured. "
            "Import cookimport.config.run_settings before using this module."
        )
    return _CONFIGURED_RUN_SETTING_NAMES


def run_setting_surface(field_name: str) -> str:
    _require_configured_run_setting_names()
    surface = str(
        _CONFIGURED_RUN_SETTING_SURFACES.get(field_name, RUN_SETTING_SURFACE_PUBLIC)
    ).strip().lower()
    if surface == RUN_SETTING_SURFACE_INTERNAL:
        return RUN_SETTING_SURFACE_INTERNAL
    return RUN_SETTING_SURFACE_PUBLIC


def public_run_setting_names() -> tuple[str, ...]:
    return tuple(
        name
        for name in _require_configured_run_setting_names()
        if run_setting_surface(name) == RUN_SETTING_SURFACE_PUBLIC
    )


def internal_run_setting_names() -> tuple[str, ...]:
    return tuple(
        name
        for name in _require_configured_run_setting_names()
        if run_setting_surface(name) == RUN_SETTING_SURFACE_INTERNAL
    )


def product_run_setting_names() -> tuple[str, ...]:
    return public_run_setting_names()


def benchmark_lab_run_setting_names() -> tuple[str, ...]:
    public_names = set(public_run_setting_names())
    return tuple(
        name for name in BENCHMARK_LAB_RUN_SETTING_NAMES if name in public_names
    )


def ordinary_operator_run_setting_names() -> tuple[str, ...]:
    benchmark_lab_names = set(benchmark_lab_run_setting_names())
    return tuple(
        name for name in public_run_setting_names() if name not in benchmark_lab_names
    )


def normalize_run_setting_contract(
    *,
    include_internal: bool | None,
    contract: str | None,
) -> str:
    if contract is None:
        return (
            RUN_SETTING_CONTRACT_FULL
            if include_internal
            else RUN_SETTING_CONTRACT_PRODUCT
        )
    normalized = str(contract).strip().lower()
    allowed = {
        RUN_SETTING_CONTRACT_FULL,
        RUN_SETTING_CONTRACT_PRODUCT,
        RUN_SETTING_CONTRACT_OPERATOR,
        RUN_SETTING_CONTRACT_BENCHMARK_LAB,
        RUN_SETTING_CONTRACT_INTERNAL,
    }
    if normalized not in allowed:
        allowed_list = ", ".join(sorted(allowed))
        raise ValueError(
            f"Unknown run-setting contract {contract!r}. Expected one of: {allowed_list}."
        )
    return normalized


def run_setting_names_for_contract(contract: str) -> tuple[str, ...]:
    if contract == RUN_SETTING_CONTRACT_FULL:
        return _require_configured_run_setting_names()
    if contract == RUN_SETTING_CONTRACT_PRODUCT:
        return product_run_setting_names()
    if contract == RUN_SETTING_CONTRACT_OPERATOR:
        return ordinary_operator_run_setting_names()
    if contract == RUN_SETTING_CONTRACT_BENCHMARK_LAB:
        return benchmark_lab_run_setting_names()
    if contract == RUN_SETTING_CONTRACT_INTERNAL:
        return internal_run_setting_names()
    raise ValueError(f"Unhandled run-setting contract: {contract}")


def project_run_config_payload(
    payload: Mapping[str, Any] | None,
    *,
    include_internal: bool | None = True,
    contract: str | None = None,
) -> dict[str, Any]:
    if payload is None:
        return {}
    normalized_contract = normalize_run_setting_contract(
        include_internal=include_internal,
        contract=contract,
    )
    allowed_names = set(run_setting_names_for_contract(normalized_contract))
    return {
        name: payload[name]
        for name in _require_configured_run_setting_names()
        if name in allowed_names and name in payload
    }


def summarize_run_config_payload(
    payload: Mapping[str, Any] | None,
    *,
    include_internal: bool = False,
    contract: str | None = None,
) -> str:
    projected = project_run_config_payload(
        payload,
        include_internal=include_internal,
        contract=contract,
    )
    ordered_names = [name for name in _SUMMARY_ORDER if name in projected]
    remaining_names = [name for name in projected if name not in ordered_names]
    parts: list[str] = []
    for key in (*ordered_names, *remaining_names):
        value = projected[key]
        if key.endswith("_path"):
            value = Path(str(value)).name
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return " | ".join(parts)
