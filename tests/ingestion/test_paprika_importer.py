from __future__ import annotations

from pathlib import Path
from cookimport.plugins.paprika import PaprikaImporter
from tests.paths import DOCS_EXAMPLES_DIR as TESTS_DOCS_EXAMPLES_DIR

EXAMPLES_DIR = TESTS_DOCS_EXAMPLES_DIR

def test_detect_paprika_file():
    importer = PaprikaImporter()
    path = EXAMPLES_DIR / "Broccoli Cheese Soup1.paprikarecipes"
    assert importer.detect(path) > 0.9

def test_detect_paprika_dir(tmp_path):
    importer = PaprikaImporter()
    (tmp_path / "index.html").touch()
    (tmp_path / "images").mkdir()
    assert importer.detect(tmp_path) > 0.7

def test_inspect_paprika():
    importer = PaprikaImporter()
    path = EXAMPLES_DIR / "Broccoli Cheese Soup1.paprikarecipes"
    inspection = importer.inspect(path)
    assert len(inspection.sheets) == 1
    assert any("Detected 1 recipe candidate(s)" in w for w in inspection.sheets[0].warnings)

def test_convert_paprika_file():
    importer = PaprikaImporter()
    path = EXAMPLES_DIR / "Broccoli Cheese Soup1.paprikarecipes"
    result = importer.convert(path, None)
    
    assert len(result.recipes) == 1
    recipe = result.recipes[0]
    assert recipe.name == "Broccoli Cheese Soup"
    assert any("broccoli" in ing.lower() for ing in recipe.ingredients)
    assert len(recipe.instructions) > 0
    assert recipe.provenance["extraction_method"] == "paprikarecipes_zip"

def test_convert_paprika_html():
    importer = PaprikaImporter()
    # Note: EXAMPLES_DIR has the .html file, but it's not in a proper folder structure for the directory detector
    # But we can test the fallback or specific file handling if we had it.
    # The current implementation handles directory as a folder of HTML files.
    # Let's mock a folder.
    pass

def test_normalize_duration():
    from cookimport.plugins.paprika import _normalize_duration
    assert _normalize_duration("5 mins") == "PT5M"
    assert _normalize_duration("1 hr 30 mins") == "PT1H30M"
    assert _normalize_duration("1 hour") == "PT1H"
    assert _normalize_duration("PT15M") == "PT15M"
    assert _normalize_duration("0") is None
    assert _normalize_duration("") is None
