from __future__ import annotations

import json
from pathlib import Path

from tests.paths import REPO_ROOT as TESTS_REPO_ROOT

REPO_ROOT = TESTS_REPO_ROOT
PACK_ROOT = REPO_ROOT / "llm_pipelines"
PIPELINES_DIR = PACK_ROOT / "pipelines"

EXPECTED_PIPELINES = {
    "recipe.correction.compact.v1": {
        "pipeline_file": "recipe.correction.compact.v1.json",
        "prompt_path": "prompts/recipe.correction.compact.v1.prompt.md",
        "schema_path": "schemas/recipe.correction.v1.output.schema.json",
        "prompt_input_mode": "inline",
        "prompt_contains": "{{INPUT_TEXT}}",
        "required_keys": {"v", "sid", "r"},
    },
    "recipe.knowledge.compact.v1": {
        "pipeline_file": "recipe.knowledge.compact.v1.json",
        "prompt_path": "prompts/recipe.knowledge.compact.v1.prompt.md",
        "schema_path": "schemas/recipe.knowledge.v1.output.schema.json",
        "prompt_input_mode": "path",
        "prompt_contains": "Review non-recipe cookbook text",
        "required_keys": {"v", "bid", "r"},
    },
    "recipe.knowledge.packet.v1": {
        "pipeline_file": "recipe.knowledge.packet.v1.json",
        "prompt_path": "prompts/recipe.knowledge.packet.v1.prompt.md",
        "schema_path": "schemas/recipe.knowledge.packet.v1.output.schema.json",
        "prompt_input_mode": "path",
        "prompt_contains": "Process one ordered packet of candidate non-recipe cookbook text",
        "required_keys": {"v", "bid", "d", "g"},
    },
}


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_object_schema_required_gaps(
    schema: object,
    *,
    path: str = "$",
):
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict) and properties:
            required = schema.get("required")
            if not isinstance(required, list):
                yield path, sorted(properties), "missing required list"
            else:
                missing = sorted(set(properties) - set(required))
                if missing:
                    yield path, missing, "missing required properties"
            for key, value in properties.items():
                yield from _iter_object_schema_required_gaps(value, path=f"{path}.properties.{key}")
        items = schema.get("items")
        if items is not None:
            yield from _iter_object_schema_required_gaps(items, path=f"{path}.items")
    elif isinstance(schema, list):
        for index, item in enumerate(schema):
            yield from _iter_object_schema_required_gaps(item, path=f"{path}[{index}]")


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
        assert payload.get("prompt_input_mode") == expected["prompt_input_mode"]

        prompt_path = PACK_ROOT / str(payload["prompt_template_path"])
        schema_path = PACK_ROOT / str(payload["output_schema_path"])
        assert prompt_path.exists(), f"Missing prompt template: {prompt_path}"
        assert schema_path.exists(), f"Missing schema file: {schema_path}"

        prompt_text = prompt_path.read_text(encoding="utf-8")
        assert expected["prompt_contains"] in prompt_text

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
            f"Codex structured outputs contract; missing: {missing}"
        )


def test_output_schemas_require_all_nested_object_properties() -> None:
    for schema_path in sorted((PACK_ROOT / "schemas").glob("*.json")):
        schema_payload = _load_json(schema_path)
        gaps = list(_iter_object_schema_required_gaps(schema_payload))
        assert not gaps, (
            f"{schema_path} must list every nested object property in required for "
            f"Codex structured outputs contract; gaps: {gaps}"
        )


def test_recipe_output_schemas_use_native_nested_objects_for_recipe_payloads() -> None:
    correction_schema = _load_json(PACK_ROOT / "schemas/recipe.correction.v1.output.schema.json")

    correction_properties = correction_schema["properties"]
    assert correction_properties["r"]["type"] == "array"
    recipe_item_properties = correction_properties["r"]["items"]["properties"]
    assert set(recipe_item_properties["cr"]["type"]) == {"object", "null"}
    assert recipe_item_properties["st"]["type"] == "string"
    assert recipe_item_properties["sr"]["type"] == ["string", "null"]
    assert recipe_item_properties["m"]["type"] == "array"
    assert recipe_item_properties["m"]["items"]["type"] == "object"
    assert recipe_item_properties["g"]["type"] == "array"
