from __future__ import annotations

import json
from pathlib import Path

from tests.paths import REPO_ROOT as TESTS_REPO_ROOT

REPO_ROOT = TESTS_REPO_ROOT
PACK_ROOT = REPO_ROOT / "llm_pipelines"
PIPELINES_DIR = PACK_ROOT / "pipelines"

EXPECTED_PIPELINES = {
    "recipe.chunking.v1": {
        "pipeline_file": "recipe.chunking.v1.json",
        "prompt_path": "prompts/recipe.chunking.v1.prompt.md",
        "schema_path": "schemas/recipe.chunking.v1.output.schema.json",
        "required_keys": {"bundle_version", "recipe_id"},
    },
    "recipe.schemaorg.compact.v1": {
        "pipeline_file": "recipe.schemaorg.compact.v1.json",
        "prompt_path": "prompts/recipe.schemaorg.compact.v1.prompt.md",
        "schema_path": "schemas/recipe.schemaorg.v1.output.schema.json",
        "required_keys": {"bundle_version", "recipe_id"},
    },
    "recipe.final.compact.v1": {
        "pipeline_file": "recipe.final.compact.v1.json",
        "prompt_path": "prompts/recipe.final.compact.v1.prompt.md",
        "schema_path": "schemas/recipe.final.v1.output.schema.json",
        "required_keys": {"bundle_version", "recipe_id"},
    },
    "recipe.knowledge.compact.v1": {
        "pipeline_file": "recipe.knowledge.compact.v1.json",
        "prompt_path": "prompts/recipe.knowledge.compact.v1.prompt.md",
        "schema_path": "schemas/recipe.knowledge.v1.output.schema.json",
        "required_keys": {"bundle_version", "chunk_id"},
    },
    "recipe.tags.v1": {
        "pipeline_file": "recipe.tags.v1.json",
        "prompt_path": "prompts/recipe.tags.v1.prompt.md",
        "schema_path": "schemas/recipe.tags.v1.output.schema.json",
        "required_keys": {"bundle_version", "recipe_id", "selected_tags"},
    },
}


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_default_codex_farm_pass_assets_exist_and_link() -> None:
    assert PACK_ROOT.exists()
    assert PIPELINES_DIR.exists()

    for pipeline_id, expected in EXPECTED_PIPELINES.items():
        pipeline_path = PIPELINES_DIR / str(expected["pipeline_file"])
        assert pipeline_path.exists(), f"Missing pipeline file: {pipeline_path}"

        payload = _load_json(pipeline_path)
        assert payload["pipeline_id"] == pipeline_id
        assert payload["prompt_template_path"] == expected["prompt_path"]
        assert payload["output_schema_path"] == expected["schema_path"]
        assert payload.get("prompt_input_mode") == "inline"

        prompt_path = PACK_ROOT / str(payload["prompt_template_path"])
        schema_path = PACK_ROOT / str(payload["output_schema_path"])
        assert prompt_path.exists(), f"Missing prompt template: {prompt_path}"
        assert schema_path.exists(), f"Missing schema file: {schema_path}"

        prompt_text = prompt_path.read_text(encoding="utf-8")
        assert "{{INPUT_TEXT}}" in prompt_text

        schema_payload = _load_json(schema_path)
        assert schema_payload["type"] == "object"
        assert schema_payload["additionalProperties"] is False
        required = set(schema_payload.get("required") or [])
        assert expected["required_keys"].issubset(required)


def test_output_schemas_require_all_top_level_properties() -> None:
    for schema_path in sorted((PACK_ROOT / "schemas").glob("*.json")):
        schema_payload = _load_json(schema_path)
        properties = schema_payload.get("properties")
        if not isinstance(properties, dict) or not properties:
            continue
        required = schema_payload.get("required")
        assert isinstance(required, list), f"{schema_path} is missing required list"
        missing = sorted(set(properties) - set(required))
        assert not missing, (
            f"{schema_path} must list every top-level property in required for "
            f"Codex structured outputs compatibility; missing: {missing}"
        )


def test_recipe_output_schemas_use_native_nested_objects_for_recipe_payloads() -> None:
    schemaorg_schema = _load_json(PACK_ROOT / "schemas/recipe.schemaorg.v1.output.schema.json")
    final_schema = _load_json(PACK_ROOT / "schemas/recipe.final.v1.output.schema.json")
    merged_schema = _load_json(PACK_ROOT / "schemas/recipe.merged-repair.v1.output.schema.json")

    schemaorg_properties = schemaorg_schema["properties"]
    assert schemaorg_properties["schemaorg_recipe"]["type"] == "object"
    assert schemaorg_properties["field_evidence"]["type"] == "object"

    final_properties = final_schema["properties"]
    assert final_properties["draft_v1"]["type"] == "object"
    assert final_properties["ingredient_step_mapping"]["type"] == "array"
    assert final_properties["ingredient_step_mapping"]["items"]["type"] == "object"

    merged_properties = merged_schema["properties"]
    assert merged_properties["canonical_recipe"]["type"] == "object"
    assert merged_properties["ingredient_step_mapping"]["type"] == "array"
    assert merged_properties["ingredient_step_mapping"]["items"]["type"] == "object"
