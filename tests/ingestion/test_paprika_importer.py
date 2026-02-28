from __future__ import annotations

import gzip
import json
import zipfile
from pathlib import Path

from cookimport.plugins.paprika import PaprikaImporter


def _write_paprika_recipe(path: Path) -> Path:
    recipe_data = {
        "name": "Broccoli Cheese Soup",
        "ingredients": "1 tbsp butter\n1 head broccoli\n2 cups cheddar cheese",
        "directions": "Melt butter.\nAdd broccoli.\nStir in cheese and simmer.",
        "notes": "Use sharp cheddar for best flavor.",
        "uid": "broccoli-cheese-soup",
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "recipe.json",
            gzip.compress(json.dumps(recipe_data).encode("utf-8")),
        )
    return path


def test_detect_paprika_file(tmp_path):
    importer = PaprikaImporter()
    path = _write_paprika_recipe(tmp_path / "Broccoli Cheese Soup1.paprikarecipes")
    assert importer.detect(path) > 0.9


def test_detect_paprika_dir(tmp_path):
    importer = PaprikaImporter()
    (tmp_path / "index.html").touch()
    (tmp_path / "images").mkdir()
    assert importer.detect(tmp_path) > 0.7


def test_inspect_paprika(tmp_path):
    importer = PaprikaImporter()
    path = _write_paprika_recipe(tmp_path / "Broccoli Cheese Soup1.paprikarecipes")
    inspection = importer.inspect(path)
    assert len(inspection.sheets) == 1
    assert any("Detected 1 recipe candidate(s)" in w for w in inspection.sheets[0].warnings)


def test_convert_paprika_file(tmp_path):
    importer = PaprikaImporter()
    path = _write_paprika_recipe(tmp_path / "Broccoli Cheese Soup1.paprikarecipes")
    result = importer.convert(path, None)

    assert len(result.recipes) == 1
    recipe = result.recipes[0]
    assert recipe.name == "Broccoli Cheese Soup"
    assert recipe.recipe_likeness is not None
    assert recipe.confidence == recipe.recipe_likeness.score
    assert any("broccoli" in ing.lower() for ing in recipe.ingredients)
    assert len(recipe.instructions) > 0
    assert recipe.provenance["extraction_method"] == "paprikarecipes_zip"


def test_convert_paprika_html(tmp_path):
    importer = PaprikaImporter()
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "images").mkdir()
    (tmp_path / "recipe.html").write_text(
        """
        <html>
          <body>
            <script type="application/ld+json">
              {
                "@context": "http://schema.org",
                "@type": "Recipe",
                "name": "Paprika HTML Recipe",
                "recipeIngredient": ["1 cup flour", "1 egg"],
                "recipeInstructions": ["Mix", "Bake"]
              }
            </script>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    result = importer.convert(tmp_path, None)
    assert len(result.recipes) == 1
    recipe = result.recipes[0]
    assert recipe.name == "Paprika HTML Recipe"
    assert recipe.recipe_likeness is not None
    assert recipe.confidence == recipe.recipe_likeness.score


def test_normalize_duration():
    from cookimport.plugins.paprika import _normalize_duration
    assert _normalize_duration("5 mins") == "PT5M"
    assert _normalize_duration("1 hr 30 mins") == "PT1H30M"
    assert _normalize_duration("1 hour") == "PT1H"
    assert _normalize_duration("PT15M") == "PT15M"
    assert _normalize_duration("0") is None
    assert _normalize_duration("") is None
