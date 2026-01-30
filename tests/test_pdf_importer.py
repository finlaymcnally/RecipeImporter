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


def test_inspect_scanned_pdf():
    """Test that scanned PDFs are detected as needing OCR."""
    importer = PdfImporter()
    pdf_path = FIXTURES_DIR / "scanned_recipe.pdf"
    if not pdf_path.exists():
        pytest.skip("scanned_recipe.pdf not found")

    inspection = importer.inspect(pdf_path)
    assert len(inspection.sheets) == 1
    assert inspection.sheets[0].layout == "image-pdf"
    # Should have warning about OCR
    warnings = inspection.sheets[0].warnings
    assert any("OCR" in w for w in warnings)


def test_convert_scanned_pdf_with_ocr():
    """Test OCR processing of a scanned PDF."""
    from cookimport.ocr.doctr_engine import ocr_available

    if not ocr_available():
        pytest.skip("docTR not available")

    importer = PdfImporter()
    pdf_path = FIXTURES_DIR / "scanned_recipe.pdf"
    if not pdf_path.exists():
        pytest.skip("scanned_recipe.pdf not found")

    result = importer.convert(pdf_path, None)

    # Should have extracted text via OCR
    raw_artifact = next(
        (a for a in result.raw_artifacts if a.location_id == "full_text"), None
    )
    assert raw_artifact is not None
    assert raw_artifact.content.get("ocr_used") is True
    assert raw_artifact.content.get("block_count", 0) > 0

    # Check that OCR confidence is present in blocks
    blocks = raw_artifact.content.get("blocks", [])
    ocr_blocks = [b for b in blocks if b.get("ocr_source") == "doctr"]
    assert len(ocr_blocks) > 0

    # Should recognize recipe content
    all_text = " ".join(b.get("text", "") for b in blocks).lower()
    assert "banana" in all_text or "bread" in all_text
