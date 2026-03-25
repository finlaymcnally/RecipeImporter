from __future__ import annotations

import json
from pathlib import Path

from cookimport.plugins.recipesage import RecipeSageImporter


def _source_text(result) -> str:
    return "\n".join(block.text for block in result.source_blocks)


def _write_recipesage_export(path: Path) -> Path:
    payload = {
        "recipes": [
            {
                "@context": "http://schema.org",
                "@type": "Recipe",
                "name": "Slow Cooker Red Beans And Rice Recipe",
                "identifier": "recipesage-red-beans",
                "recipeIngredient": [
                    "1 pound dried red beans",
                    "1 cup chopped onion",
                    "2 cloves garlic",
                ],
                "recipeInstructions": [
                    "Soak beans overnight.",
                    "Combine all ingredients in slow cooker.",
                    "Cook on low until tender.",
                ],
            }
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_detect_recipesage(tmp_path):
    importer = RecipeSageImporter()
    path = _write_recipesage_export(
        tmp_path / "recipesage-1767631101507-d892343ecccd93.json"
    )
    assert importer.detect(path) > 0.9


def test_inspect_recipesage(tmp_path):
    importer = RecipeSageImporter()
    path = _write_recipesage_export(
        tmp_path / "recipesage-1767631101507-d892343ecccd93.json"
    )
    inspection = importer.inspect(path)
    assert len(inspection.sheets) == 1
    assert any("Detected 1 recipe(s)" in w for w in inspection.sheets[0].warnings)


def test_convert_recipesage(tmp_path):
    importer = RecipeSageImporter()
    path = _write_recipesage_export(
        tmp_path / "recipesage-1767631101507-d892343ecccd93.json"
    )
    result = importer.convert(path, None)

    assert result.recipes == []
    assert result.report.total_recipes == 0
    assert len(result.source_blocks) == 1
    assert len(result.source_support) == 1
    assert result.source_support[0].kind == "recipesage_recipe_object"
    assert "Slow Cooker Red Beans And Rice Recipe" in _source_text(result)
    assert "1 pound dried red beans" in _source_text(result)
    assert "Cook on low until tender." in _source_text(result)
