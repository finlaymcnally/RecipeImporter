from __future__ import annotations

import importlib
import json
import re
from itertools import product
from pathlib import Path
from typing import Any, Iterable

from cookimport.cli_support import (
    ALL_METHOD_EPUB_EXTRACTORS_DEFAULT,
    ALL_METHOD_EPUB_EXTRACTORS_MARKDOWN_OPTIONAL,
    ALL_METHOD_UNSTRUCTURED_HTML_PARSER_VERSIONS,
    ALL_METHOD_UNSTRUCTURED_PREPROCESS_MODES,
    ALL_METHOD_UNSTRUCTURED_SKIP_HEADERS_FOOTERS,
    ALL_METHOD_WEBSCHEMA_POLICIES,
)
from cookimport.config.codex_decision import (
    apply_benchmark_baseline_contract,
    apply_benchmark_codex_contract_from_baseline,
)
from cookimport.config.run_settings import RunSettings
from cookimport.config.run_settings_types import (
    KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2,
    LINE_ROLE_PIPELINE_ROUTE_V2,
    RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
)
from cookimport.parsing.schemaorg_ingest import collect_schemaorg_recipe_objects
from .bench_all_method_types import AllMethodTarget, AllMethodVariant


def _bench_all_method_module():
    return importlib.import_module("cookimport.cli_support.bench_all_method")


def _all_method_variant_token(value: str | bool) -> str:
    if isinstance(value, bool):
        raw_value = "true" if value else "false"
    else:
        raw_value = str(value).strip().lower()
    token = raw_value.replace("-", "_")
    token = re.sub(r"[^a-z0-9_]+", "_", token)
    token = token.strip("_")
    return token or "na"


def _all_method_is_schema_like_json_source(source_file: Path) -> bool:
    try:
        if not source_file.exists() or not source_file.is_file():
            return False
        with source_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return False

    if isinstance(payload, dict):
        recipes = payload.get("recipes")
        if isinstance(recipes, list) and recipes:
            recipe_like = 0
            for item in recipes:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("@type") or "").lower()
                if "recipe" in item_type:
                    recipe_like += 1
            if recipe_like > 0:
                return False

    return bool(collect_schemaorg_recipe_objects(payload))


def _all_method_optional_module_available(module_name: str) -> bool:
    try:
        import importlib

        importlib.import_module(module_name)
        return True
    except Exception:  # noqa: BLE001
        return False


def _build_all_method_sweep_payloads(
    *,
    base_payload: dict[str, Any],
    include_deterministic_sweeps: bool,
) -> list[tuple[str, dict[str, Any]]]:
    """Return (sweep_tag, payload) rows for all-method benchmark runs.

    Strategy: baseline + one-at-a-time sweeps + one combined "all_upgrades" payload.
    This exercises new deterministic knobs without a factorial explosion.
    """

    bench_all_method = _bench_all_method_module()

    def _normalized(value: Any, default: str) -> str:
        cleaned = str(value if value is not None else default).strip().lower()
        return cleaned or default

    rows: list[tuple[str, dict[str, Any]]] = [("base", dict(base_payload))]
    if not include_deterministic_sweeps:
        return rows

    quantulum_ok = bench_all_method._all_method_optional_module_available("quantulum3")
    pint_ok = bench_all_method._all_method_optional_module_available("pint")

    def add_one_at_a_time(
        *,
        key: str,
        values: Iterable[str],
        default: str,
        require: bool = True,
    ) -> None:
        if not require:
            return
        base_value = _normalized(base_payload.get(key), default)
        for value in values:
            normalized = _normalized(value, default)
            if normalized == base_value:
                continue
            payload = dict(base_payload)
            payload[key] = normalized
            rows.append((f"{key}={normalized}", payload))

    add_one_at_a_time(
        key="multi_recipe_splitter",
        values=("off", "rules_v1"),
        default="rules_v1",
    )
    add_one_at_a_time(
        key="ingredient_missing_unit_policy",
        values=("null", "medium", "each"),
        default="null",
    )
    add_one_at_a_time(
        key="p6_yield_mode",
        values=("scored_v1",),
        default="scored_v1",
    )
    add_one_at_a_time(
        key="p6_time_backend",
        values=("regex_v1", "quantulum3_v1", "hybrid_regex_quantulum3_v1"),
        default="regex_v1",
        require=quantulum_ok,
    )
    add_one_at_a_time(
        key="p6_temperature_backend",
        values=("regex_v1", "quantulum3_v1", "hybrid_regex_quantulum3_v1"),
        default="regex_v1",
        require=quantulum_ok,
    )
    add_one_at_a_time(
        key="p6_temperature_unit_backend",
        values=("builtin_v1", "pint_v1"),
        default="builtin_v1",
        require=pint_ok,
    )

    upgrades: dict[str, str] = {
        "multi_recipe_splitter": "rules_v1",
        "ingredient_missing_unit_policy": "each",
        "p6_yield_mode": "scored_v1",
    }
    if quantulum_ok:
        upgrades["p6_time_backend"] = "hybrid_regex_quantulum3_v1"
        upgrades["p6_temperature_backend"] = "hybrid_regex_quantulum3_v1"
    if pint_ok:
        upgrades["p6_temperature_unit_backend"] = "pint_v1"

    combined = dict(base_payload)
    combined.update(upgrades)
    if combined != base_payload:
        rows.append(("all_upgrades", combined))

    return rows


def _build_all_method_variants(
    *,
    base_settings: RunSettings,
    source_file: Path,
    include_codex_farm: bool,
    codex_variant_settings: RunSettings | None = None,
    include_markdown_extractors: bool = False,
    include_deterministic_sweeps: bool = False,
) -> list[AllMethodVariant]:
    bench_all_method = _bench_all_method_module()
    base_payload = bench_all_method._all_method_apply_baseline_contract(
        base_settings.to_run_config_dict()
    )
    variants: list[AllMethodVariant] = []
    source_ext = source_file.suffix.lower()

    webschema_source = source_ext in {".html", ".htm", ".jsonld"} or (
        source_ext == ".json"
        and bench_all_method._all_method_is_schema_like_json_source(source_file)
    )

    sweep_payloads = bench_all_method._build_all_method_sweep_payloads(
        base_payload=dict(base_payload),
        include_deterministic_sweeps=include_deterministic_sweeps,
    )
    dedupe_hashes: set[str] = set()

    def add_variant(
        *,
        slug: str,
        payload: dict[str, Any],
        dimensions: dict[str, Any],
        sweep_tag: str,
        apply_baseline_contract: bool = False,
    ) -> None:
        normalized_payload = (
            bench_all_method._all_method_apply_baseline_contract(payload)
            if apply_baseline_contract
            else dict(payload)
        )
        run_settings_payload = {
            key: value
            for key, value in normalized_payload.items()
            if key in RunSettings.model_fields
        }
        run_settings = RunSettings.from_dict(
            run_settings_payload,
            warn_context="all-method variant",
        )
        stable_hash = run_settings.stable_hash()
        if stable_hash in dedupe_hashes:
            return
        dedupe_hashes.add(stable_hash)
        if sweep_tag != "base":
            dimensions = dict(dimensions)
            dimensions["deterministic_sweep"] = sweep_tag
        variants.append(
            AllMethodVariant(
                slug=slug,
                run_settings=run_settings,
                dimensions=dimensions,
            )
        )
        if include_codex_farm:
            current_llm = str(
                normalized_payload.get("llm_recipe_pipeline") or "off"
            ).strip().lower()
            if current_llm == "off":
                if codex_variant_settings is None:
                    codex_payload = (
                        bench_all_method._all_method_apply_codex_contract_from_baseline(
                            normalized_payload
                        )
                    )
                    codex_slug_parts = [
                        "llm_recipe_"
                        + bench_all_method._all_method_variant_token(
                            RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
                        )
                    ]
                    codex_dimensions = dict(dimensions)
                    codex_dimensions["llm_recipe_pipeline"] = (
                        RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
                    )
                    codex_dimensions["line_role_pipeline"] = LINE_ROLE_PIPELINE_ROUTE_V2
                    codex_dimensions["llm_knowledge_pipeline"] = (
                        KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2
                    )
                    codex_dimensions["atomic_block_splitter"] = str(
                        codex_payload.get("atomic_block_splitter") or "off"
                    )
                else:
                    codex_slug_parts = bench_all_method._all_method_codex_surface_slug_parts(
                        codex_variant_settings
                    )
                    if not codex_slug_parts:
                        return
                    codex_payload = (
                        bench_all_method._all_method_apply_selected_codex_contract_from_baseline(
                            normalized_payload,
                            codex_variant_settings=codex_variant_settings,
                        )
                    )
                    codex_dimensions = dict(dimensions)
                    if codex_variant_settings.llm_recipe_pipeline.value != "off":
                        codex_dimensions["llm_recipe_pipeline"] = (
                            codex_variant_settings.llm_recipe_pipeline.value
                        )
                    if (
                        codex_variant_settings.line_role_pipeline.value
                        == LINE_ROLE_PIPELINE_ROUTE_V2
                    ):
                        codex_dimensions["line_role_pipeline"] = (
                            codex_variant_settings.line_role_pipeline.value
                        )
                    if codex_variant_settings.llm_knowledge_pipeline.value != "off":
                        codex_dimensions["llm_knowledge_pipeline"] = (
                            codex_variant_settings.llm_knowledge_pipeline.value
                        )
                    codex_dimensions["atomic_block_splitter"] = (
                        codex_variant_settings.atomic_block_splitter.value
                    )
                add_variant(
                    slug=f"{slug}__{'__'.join(codex_slug_parts)}",
                    payload=codex_payload,
                    dimensions=codex_dimensions,
                    sweep_tag=sweep_tag,
                    apply_baseline_contract=False,
                )

    def base_dimensions(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "multi_recipe_splitter": str(
                payload.get("multi_recipe_splitter", "rules_v1")
            ),
            "ingredient_missing_unit_policy": str(
                payload.get("ingredient_missing_unit_policy", "null")
            ),
            "p6_time_backend": str(payload.get("p6_time_backend", "regex_v1")),
            "p6_temperature_backend": str(
                payload.get("p6_temperature_backend", "regex_v1")
            ),
            "p6_temperature_unit_backend": str(
                payload.get("p6_temperature_unit_backend", "builtin_v1")
            ),
            "p6_yield_mode": str(payload.get("p6_yield_mode", "scored_v1")),
            "pdf_ocr_policy": str(payload.get("pdf_ocr_policy", "auto")),
            "pdf_column_gap_ratio": float(payload.get("pdf_column_gap_ratio", 0.12)),
        }

    if source_ext != ".epub" and not webschema_source:
        for sweep_tag, payload in sweep_payloads:
            suffix = (
                ""
                if sweep_tag == "base"
                else f"__det_{bench_all_method._all_method_variant_token(sweep_tag)}"
            )
            multi_recipe = (
                str(payload.get("multi_recipe_splitter") or "rules_v1").strip().lower()
            )
            multi_recipe_suffix = (
                ""
                if multi_recipe in {"", "rules_v1"}
                else f"__multi_recipe_{bench_all_method._all_method_variant_token(multi_recipe)}"
            )
            add_variant(
                slug=(
                    f"source_{bench_all_method._all_method_variant_token(source_ext.lstrip('.') or 'unknown')}"
                    f"{multi_recipe_suffix}"
                    f"{suffix}"
                ),
                payload=payload,
                sweep_tag=sweep_tag,
                dimensions={
                    "source_extension": source_ext or "none",
                    **base_dimensions(payload),
                },
            )
        return variants

    if webschema_source:
        for sweep_tag, payload in sweep_payloads:
            suffix = (
                ""
                if sweep_tag == "base"
                else f"__det_{bench_all_method._all_method_variant_token(sweep_tag)}"
            )
            for schema_policy in ALL_METHOD_WEBSCHEMA_POLICIES:
                next_payload = dict(payload)
                next_payload["web_schema_policy"] = schema_policy
                add_variant(
                    slug=(
                        f"source_{bench_all_method._all_method_variant_token(source_ext.lstrip('.') or 'unknown')}"
                        f"__webschema_policy_{bench_all_method._all_method_variant_token(schema_policy)}"
                        f"{suffix}"
                    ),
                    payload=next_payload,
                    sweep_tag=sweep_tag,
                    dimensions={
                        "source_extension": source_ext or "none",
                        "web_schema_policy": schema_policy,
                        **base_dimensions(next_payload),
                    },
                )
        return variants

    extractors = ALL_METHOD_EPUB_EXTRACTORS_DEFAULT
    if include_markdown_extractors:
        extractors = (
            *ALL_METHOD_EPUB_EXTRACTORS_DEFAULT,
            *ALL_METHOD_EPUB_EXTRACTORS_MARKDOWN_OPTIONAL,
        )

    for sweep_tag, payload in sweep_payloads:
        suffix = (
            ""
            if sweep_tag == "base"
            else f"__det_{bench_all_method._all_method_variant_token(sweep_tag)}"
        )
        for extractor in extractors:
            if extractor == "unstructured":
                for parser_version, skip_headers_footers, preprocess_mode in product(
                    ALL_METHOD_UNSTRUCTURED_HTML_PARSER_VERSIONS,
                    ALL_METHOD_UNSTRUCTURED_SKIP_HEADERS_FOOTERS,
                    ALL_METHOD_UNSTRUCTURED_PREPROCESS_MODES,
                ):
                    next_payload = dict(payload)
                    next_payload.update(
                        {
                            "epub_extractor": extractor,
                            "epub_unstructured_html_parser_version": parser_version,
                            "epub_unstructured_skip_headers_footers": skip_headers_footers,
                            "epub_unstructured_preprocess_mode": preprocess_mode,
                        }
                    )
                    add_variant(
                        slug=(
                            f"extractor_{bench_all_method._all_method_variant_token(extractor)}"
                            f"__parser_{bench_all_method._all_method_variant_token(parser_version)}"
                            f"__skiphf_{bench_all_method._all_method_variant_token(skip_headers_footers)}"
                            f"__pre_{bench_all_method._all_method_variant_token(preprocess_mode)}"
                            f"{suffix}"
                        ),
                        payload=next_payload,
                        sweep_tag=sweep_tag,
                        dimensions={
                            "epub_extractor": extractor,
                            "epub_unstructured_html_parser_version": parser_version,
                            "epub_unstructured_skip_headers_footers": skip_headers_footers,
                            "epub_unstructured_preprocess_mode": preprocess_mode,
                            **base_dimensions(next_payload),
                        },
                    )
                continue

            next_payload = dict(payload)
            next_payload["epub_extractor"] = extractor
            add_variant(
                slug=f"extractor_{bench_all_method._all_method_variant_token(extractor)}{suffix}",
                payload=next_payload,
                sweep_tag=sweep_tag,
                dimensions={
                    "epub_extractor": extractor,
                    **base_dimensions(next_payload),
                },
            )

    return variants


def _build_all_method_target_variants(
    *,
    targets: list[AllMethodTarget],
    base_settings: RunSettings,
    include_codex_farm: bool,
    codex_variant_settings: RunSettings | None = None,
    include_markdown_extractors: bool = False,
    include_deterministic_sweeps: bool = False,
) -> list[tuple[AllMethodTarget, list[AllMethodVariant]]]:
    bench_all_method = _bench_all_method_module()
    return [
        (
            target,
            bench_all_method._build_all_method_variants(
                base_settings=base_settings,
                source_file=target.source_file,
                include_codex_farm=include_codex_farm,
                codex_variant_settings=codex_variant_settings,
                include_markdown_extractors=include_markdown_extractors,
                include_deterministic_sweeps=include_deterministic_sweeps,
            ),
        )
        for target in targets
    ]


def _resolve_all_method_codex_choice(include_codex_farm: bool) -> tuple[bool, str | None]:
    if not include_codex_farm:
        return False, None
    return True, None


def _all_method_apply_baseline_contract(
    payload: dict[str, Any],
) -> dict[str, Any]:
    return apply_benchmark_baseline_contract(payload)


def _all_method_apply_codex_contract_from_baseline(
    baseline_payload: dict[str, Any],
) -> dict[str, Any]:
    return apply_benchmark_codex_contract_from_baseline(baseline_payload)


def _all_method_apply_selected_codex_contract_from_baseline(
    baseline_payload: dict[str, Any],
    *,
    codex_variant_settings: RunSettings,
) -> dict[str, Any]:
    codex_payload = dict(baseline_payload)
    codex_config = codex_variant_settings.to_run_config_dict()
    for key in (
        "llm_recipe_pipeline",
        "llm_knowledge_pipeline",
        "line_role_pipeline",
        "atomic_block_splitter",
        "codex_farm_model",
        "codex_farm_reasoning_effort",
    ):
        if key in codex_config:
            codex_payload[key] = codex_config[key]
    return codex_payload


def _all_method_codex_surface_slug_parts(
    codex_variant_settings: RunSettings,
) -> list[str]:
    bench_all_method = _bench_all_method_module()
    parts: list[str] = []
    recipe_pipeline = codex_variant_settings.llm_recipe_pipeline.value
    if recipe_pipeline != "off":
        parts.append(
            f"llm_recipe_{bench_all_method._all_method_variant_token(recipe_pipeline)}"
        )
    if codex_variant_settings.line_role_pipeline.value == LINE_ROLE_PIPELINE_ROUTE_V2:
        parts.append(
            "line_role_"
            f"{bench_all_method._all_method_variant_token(codex_variant_settings.line_role_pipeline.value)}"
        )
    knowledge_pipeline = codex_variant_settings.llm_knowledge_pipeline.value
    if knowledge_pipeline != "off":
        parts.append(
            "llm_knowledge_"
            f"{bench_all_method._all_method_variant_token(knowledge_pipeline)}"
        )
    return parts


def _all_method_settings_enable_any_codex(
    codex_variant_settings: RunSettings | None,
) -> bool:
    if codex_variant_settings is None:
        return False
    return any(
        (
            codex_variant_settings.llm_recipe_pipeline.value != "off",
            codex_variant_settings.line_role_pipeline.value == LINE_ROLE_PIPELINE_ROUTE_V2,
            codex_variant_settings.llm_knowledge_pipeline.value != "off",
        )
    )
