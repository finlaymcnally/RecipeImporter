from __future__ import annotations

import json
from pathlib import Path

from cookimport.config.run_settings import RunSettings
from cookimport.plugins import recipesage, registry, webschema  # noqa: F401
from cookimport.plugins.webschema import WebSchemaImporter
from tests.paths import FIXTURES_DIR


def _write_recipesage_export(path: Path) -> Path:
    payload = {
        "recipes": [
            {
                "@context": "http://schema.org",
                "@type": "Recipe",
                "name": "RecipeSage Example",
                "recipeIngredient": ["1 cup rice"],
                "recipeInstructions": ["Cook rice."],
            }
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_detect_html_jsonld_and_schema_json() -> None:
    importer = WebSchemaImporter()

    assert importer.detect(FIXTURES_DIR / "webschema" / "html_with_jsonld.html") > 0.8
    assert importer.detect(FIXTURES_DIR / "webschema" / "recipe_graph.jsonld") > 0.8
    assert importer.detect(FIXTURES_DIR / "webschema" / "schema_recipe.json") > 0.7


def test_detect_recipesage_export_json_returns_zero(tmp_path: Path) -> None:
    importer = WebSchemaImporter()
    recipesage_export = _write_recipesage_export(tmp_path / "recipesage.json")

    assert importer.detect(recipesage_export) == 0.0


def test_convert_schema_lane_html_with_jsonld() -> None:
    importer = WebSchemaImporter()
    source = FIXTURES_DIR / "webschema" / "html_with_jsonld.html"

    result = importer.convert(source, None)
    source_text = "\n".join(block.text for block in result.source_blocks)

    assert result.recipes == []
    assert "Sheet Pan Lemon Chicken" in source_text
    assert "schema-first extraction" in source_text
    assert len(result.source_support) == 1
    assert result.source_support[0].kind == "structured_recipe_object"
    artifact_ids = {artifact.location_id for artifact in result.raw_artifacts}
    assert "schema_extracted" in artifact_ids
    assert "source" in artifact_ids
    assert result.report.importer_name == "webschema"


def test_convert_fallback_lane_when_schema_missing() -> None:
    importer = WebSchemaImporter()
    source = FIXTURES_DIR / "webschema" / "html_without_schema.html"

    result = importer.convert(source, None)
    source_text = "\n".join(block.text for block in result.source_blocks)

    assert result.recipes == []
    assert "Skillet Zucchini" in source_text
    assert "2 zucchini, sliced" in source_text
    assert "Serve immediately." in source_text
    assert result.source_support == []
    assert result.report.importer_name == "webschema"
    artifact_ids = {artifact.location_id for artifact in result.raw_artifacts}
    assert "full_text" in artifact_ids
    assert "source_text_meta" in artifact_ids


def test_schema_only_policy_without_schema_returns_source_blocks_without_support() -> None:
    importer = WebSchemaImporter()
    source = FIXTURES_DIR / "webschema" / "html_without_schema.html"
    run_settings = RunSettings(web_schema_policy="schema_only")

    result = importer.convert(source, None, run_settings=run_settings)

    assert result.recipes == []
    assert result.source_blocks
    assert result.source_support == []


def test_registry_prefers_recipesage_importer_for_recipesage_json(tmp_path: Path) -> None:
    source = _write_recipesage_export(tmp_path / "recipesage.json")

    importer, score = registry.best_importer_for_path(source)

    assert importer is not None
    assert importer.name == "recipesage"
    assert score > 0.9
