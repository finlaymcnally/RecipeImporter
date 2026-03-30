from __future__ import annotations

from typing import Any

from cookimport.config.run_settings import RECIPE_CODEX_FARM_PIPELINE_SHARD_V1


LABEL_DETERMINISTIC_STAGE_KEY = "label_deterministic"
LABEL_REFINE_STAGE_KEY = "label_refine"
RECIPE_BOUNDARY_STAGE_KEY = "recipe_boundary"
NONRECIPE_ROUTE_STAGE_KEY = "nonrecipe_route"
RECIPE_BUILD_INTERMEDIATE_STAGE_KEY = "recipe_build_intermediate"
RECIPE_REFINE_STAGE_KEY = "recipe_refine"
RECIPE_BUILD_FINAL_STAGE_KEY = "recipe_build_final"
NONRECIPE_FINALIZE_STAGE_KEY = "nonrecipe_finalize"
LINE_ROLE_STAGE_KEY = "line_role"
WRITE_OUTPUTS_STAGE_KEY = "write_outputs"


_STAGE_DEFINITIONS: dict[str, dict[str, Any]] = {
    LABEL_DETERMINISTIC_STAGE_KEY: {
        "label": "Label Deterministic",
        "artifact_stem": LABEL_DETERMINISTIC_STAGE_KEY,
        "family": "label_stage",
        "order": 5,
    },
    LABEL_REFINE_STAGE_KEY: {
        "label": "Label Refine",
        "artifact_stem": LABEL_REFINE_STAGE_KEY,
        "family": "label_stage",
        "order": 6,
    },
    RECIPE_BOUNDARY_STAGE_KEY: {
        "label": "Recipe Boundary",
        "artifact_stem": RECIPE_BOUNDARY_STAGE_KEY,
        "family": "label_stage",
        "order": 7,
    },
    NONRECIPE_ROUTE_STAGE_KEY: {
        "label": "Non-Recipe Route",
        "artifact_stem": NONRECIPE_ROUTE_STAGE_KEY,
        "family": "deterministic",
        "order": 8,
    },
    RECIPE_BUILD_INTERMEDIATE_STAGE_KEY: {
        "label": "Recipe Build Intermediate",
        "artifact_stem": RECIPE_BUILD_INTERMEDIATE_STAGE_KEY,
        "family": "recipe_deterministic",
        "order": 10,
    },
    RECIPE_REFINE_STAGE_KEY: {
        "label": "Recipe Refine",
        "artifact_stem": RECIPE_REFINE_STAGE_KEY,
        "family": "recipe_llm",
        "order": 20,
    },
    RECIPE_BUILD_FINAL_STAGE_KEY: {
        "label": "Recipe Build Final",
        "artifact_stem": RECIPE_BUILD_FINAL_STAGE_KEY,
        "family": "recipe_deterministic",
        "order": 30,
    },
    NONRECIPE_FINALIZE_STAGE_KEY: {
        "label": "Non-Recipe Finalize",
        "artifact_stem": NONRECIPE_FINALIZE_STAGE_KEY,
        "family": "knowledge_llm",
        "order": 40,
    },
    LINE_ROLE_STAGE_KEY: {
        "label": "Line Role",
        "artifact_stem": LINE_ROLE_STAGE_KEY,
        "family": "line_role_llm",
        "order": 35,
    },
    WRITE_OUTPUTS_STAGE_KEY: {
        "label": "Write Outputs",
        "artifact_stem": WRITE_OUTPUTS_STAGE_KEY,
        "family": "deterministic",
        "order": 90,
    },
}


def canonical_stage_key(stage_key: str) -> str:
    normalized = str(stage_key or "").strip()
    return normalized


def stage_label(stage_key: str) -> str:
    definition = _STAGE_DEFINITIONS.get(canonical_stage_key(stage_key), {})
    return str(definition.get("label") or str(stage_key).replace("_", " ").title())


def stage_artifact_stem(stage_key: str) -> str:
    definition = _STAGE_DEFINITIONS.get(canonical_stage_key(stage_key), {})
    return str(definition.get("artifact_stem") or canonical_stage_key(stage_key))


def stage_order(stage_key: str) -> int:
    definition = _STAGE_DEFINITIONS.get(canonical_stage_key(stage_key), {})
    try:
        return int(definition.get("order") or 999)
    except (TypeError, ValueError):
        return 999


def stage_family(stage_key: str) -> str:
    definition = _STAGE_DEFINITIONS.get(canonical_stage_key(stage_key), {})
    return str(definition.get("family") or "stage")


def recipe_stage_keys_for_pipeline(pipeline_id: str | None) -> tuple[str, ...]:
    normalized = str(pipeline_id or "").strip()
    if normalized == RECIPE_CODEX_FARM_PIPELINE_SHARD_V1:
        return (
            RECIPE_BUILD_INTERMEDIATE_STAGE_KEY,
            RECIPE_REFINE_STAGE_KEY,
            RECIPE_BUILD_FINAL_STAGE_KEY,
        )
    return ()
