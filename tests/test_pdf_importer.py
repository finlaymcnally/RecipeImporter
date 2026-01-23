from __future__ import annotations

import pytest
from pathlib import Path
from cookimport.plugins.pdf import PdfImporter

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def test_detect_pdf():
    importer = PdfImporter()
    assert importer.detect(Path("book.pdf")) > 0.9
    assert importer.detect(Path("book.txt")) == 0.0

def test_inspect_pdf():
    importer = PdfImporter()
    pdf_path = FIXTURES_DIR / "sample.pdf"
    if not pdf_path.exists():
        pytest.skip("sample.pdf not found")
        
    inspection = importer.inspect(pdf_path)
    assert len(inspection.sheets) == 1
    assert inspection.sheets[0].layout == "text-pdf"

def test_convert_pdf():
    importer = PdfImporter()
    pdf_path = FIXTURES_DIR / "sample.pdf"
    if not pdf_path.exists():
        pytest.skip("sample.pdf not found")

    result = importer.convert(pdf_path, None)
    
    assert len(result.recipes) == 1
    recipe = result.recipes[0]
    
    assert recipe.name == "PDF Pancakes"
    assert "1 cup flour" in recipe.ingredients
    assert "Mix it all." in recipe.instructions
