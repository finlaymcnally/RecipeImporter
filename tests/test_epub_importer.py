from __future__ import annotations

import pytest
from pathlib import Path
from cookimport.plugins.epub import EpubImporter

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def test_detect_epub():
    importer = EpubImporter()
    assert importer.detect(Path("book.epub")) > 0.9
    assert importer.detect(Path("book.txt")) == 0.0

def test_inspect_epub():
    importer = EpubImporter()
    epub_path = FIXTURES_DIR / "sample.epub"
    if not epub_path.exists():
        pytest.skip("sample.epub not found")
        
    inspection = importer.inspect(epub_path)
    assert len(inspection.sheets) == 1
    assert "Sample Cookbook" in inspection.sheets[0].name
    assert inspection.sheets[0].layout == "epub-book"

def test_convert_epub():
    importer = EpubImporter()
    epub_path = FIXTURES_DIR / "sample.epub"
    if not epub_path.exists():
        pytest.skip("sample.epub not found")

    result = importer.convert(epub_path, None)
    
    # We expect 2 recipes: Best Pancakes and Simple Salad
    assert len(result.recipes) == 2
    
    r1 = result.recipes[0]
    assert r1.name == "Best Pancakes"
    assert len(r1.ingredients) == 2
    assert "1 cup flour" in r1.ingredients
    assert "Mix contents." in r1.instructions
    
    r2 = result.recipes[1]
    assert r2.name == "Simple Salad"
    assert "Lettuce" in r2.ingredients
