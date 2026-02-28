from __future__ import annotations

import json
from pathlib import Path

from cookimport.config.run_settings import RunSettings
from cookimport.plugins import registry
from cookimport.plugins import recipesage, webschema  # noqa: F401
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

    assert len(result.recipes) == 1
    recipe = result.recipes[0]
    assert recipe.name == "Sheet Pan Lemon Chicken"
    assert "1 lb chicken thighs" in recipe.ingredients
    assert recipe.recipe_likeness is not None
    assert recipe.confidence == recipe.recipe_likeness.score
    artifact_ids = {artifact.location_id for artifact in result.raw_artifacts}
    assert "schema_extracted" in artifact_ids
    assert "schema_accepted" in artifact_ids
    assert "source" in artifact_ids
    assert result.report.importer_name == "webschema"


def test_convert_fallback_lane_when_schema_missing() -> None:
    importer = WebSchemaImporter()
    source = FIXTURES_DIR / "webschema" / "html_without_schema.html"

    result = importer.convert(source, None)

    assert len(result.recipes) == 1
    recipe = result.recipes[0]
    assert recipe.name == "Skillet Zucchini"
    assert any("zucchini" in line.lower() for line in recipe.ingredients)
    assert result.report.importer_name == "webschema"
    artifact_ids = {artifact.location_id for artifact in result.raw_artifacts}
    assert "fallback_text" in artifact_ids
    assert "fallback_meta" in artifact_ids


def test_schema_only_policy_without_schema_returns_zero_with_warning() -> None:
    importer = WebSchemaImporter()
    source = FIXTURES_DIR / "webschema" / "html_without_schema.html"
    run_settings = RunSettings(web_schema_policy="schema_only")

    result = importer.convert(source, None, run_settings=run_settings)

    assert result.recipes == []
    assert any(
        "web_schema_policy=schema_only" in warning
        for warning in result.report.warnings
    )


def test_registry_prefers_recipesage_importer_for_recipesage_json(tmp_path: Path) -> None:
    source = _write_recipesage_export(tmp_path / "recipesage.json")

    importer, score = registry.best_importer_for_path(source)

    assert importer is not None
    assert importer.name == "recipesage"
    assert score > 0.9

