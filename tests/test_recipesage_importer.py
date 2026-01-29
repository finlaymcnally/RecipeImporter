from __future__ import annotations

from pathlib import Path
from cookimport.plugins.recipesage import RecipeSageImporter

EXAMPLES_DIR = Path(__file__).parent.parent / "docs" / "template" / "examples"

def test_detect_recipesage():
    importer = RecipeSageImporter()
    path = EXAMPLES_DIR / "recipesage-1767631101507-d892343ecccd93.json"
    assert importer.detect(path) > 0.9

def test_inspect_recipesage():
    importer = RecipeSageImporter()
    path = EXAMPLES_DIR / "recipesage-1767631101507-d892343ecccd93.json"
    inspection = importer.inspect(path)
    assert len(inspection.sheets) == 1
    assert any("Detected 1 recipe(s)" in w for w in inspection.sheets[0].warnings)

def test_convert_recipesage():
    importer = RecipeSageImporter()
    path = EXAMPLES_DIR / "recipesage-1767631101507-d892343ecccd93.json"
    result = importer.convert(path, None)
    
    assert len(result.recipes) == 1
    recipe = result.recipes[0]
    assert recipe.name == "Slow Cooker Red Beans And Rice Recipe"
    assert "1 pound dried red beans" in recipe.ingredients
    assert len(recipe.instructions) > 0
    assert recipe.provenance["source_system"] == "recipesage"
