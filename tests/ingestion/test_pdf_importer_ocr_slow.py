from __future__ import annotations

from cookimport.ocr.doctr_engine import ocr_available
from cookimport.plugins.pdf import PdfImporter
import pytest

from tests.paths import FIXTURES_DIR as TESTS_FIXTURES_DIR


def test_convert_scanned_pdf_with_ocr() -> None:
    """OCR integration coverage kept isolated from fast PDF importer tests."""
    if not ocr_available():
        pytest.skip("docTR not available")

    importer = PdfImporter()
    pdf_path = TESTS_FIXTURES_DIR / "scanned_recipe.pdf"
    if not pdf_path.exists():
        pytest.skip("scanned_recipe.pdf not found")

    result = importer.convert(pdf_path, None)
    raw_artifact = next(
        (artifact for artifact in result.raw_artifacts if artifact.location_id == "full_text"),
        None,
    )
    assert raw_artifact is not None
    assert raw_artifact.content.get("ocr_used") is True
    assert raw_artifact.content.get("block_count", 0) > 0

    blocks = raw_artifact.content.get("blocks", [])
    ocr_blocks = [block for block in blocks if block.get("ocr_source") == "doctr"]
    assert len(ocr_blocks) > 0
    all_text = " ".join(block.get("text", "") for block in blocks).lower()
    assert "banana" in all_text or "bread" in all_text
