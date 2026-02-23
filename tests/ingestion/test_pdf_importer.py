from __future__ import annotations

import pytest
import time
from pathlib import Path
from cookimport.core.blocks import Block
from cookimport.core.models import RecipeCandidate
from cookimport.parsing.atoms import Atom
from cookimport.parsing.tips import TopicContainer
from cookimport.parsing import signals
from cookimport.plugins.pdf import PdfImporter
from tests.paths import FIXTURES_DIR as TESTS_FIXTURES_DIR

FIXTURES_DIR = TESTS_FIXTURES_DIR


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


def test_convert_pdf_emits_post_candidate_progress(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF-1.4 dummy")
    importer = PdfImporter()
    blocks = [
        Block(text="PDF Pancakes", page=0),
        Block(text="Ingredients", page=0),
        Block(text="1 cup flour", page=0),
        Block(text="Instructions", page=0),
        Block(text="Mix it all.", page=0),
    ]
    for block in blocks:
        signals.enrich_block(block)

    monkeypatch.setattr(
        importer,
        "_extract_blocks_from_page",
        lambda _page, _abs_page: list(blocks),
    )
    monkeypatch.setattr(importer, "_needs_ocr", lambda _doc: False)
    monkeypatch.setattr(importer, "_detect_candidates", lambda _blocks: [(0, len(blocks), 0.9)])
    monkeypatch.setattr(
        importer,
        "_extract_fields",
        lambda _candidate_blocks: RecipeCandidate(
            name="PDF Pancakes",
            ingredients=["1 cup flour"],
            instructions=["Mix it all."],
        ),
    )
    monkeypatch.setattr(
        importer,
        "_extract_standalone_tips",
        lambda *_args, **_kwargs: ([], [], 0, 0),
    )

    class _FakeDoc:
        def __init__(self) -> None:
            self._closed = False

        def __len__(self) -> int:
            return 1

        def __getitem__(self, _index: int) -> object:
            return object()

        def close(self) -> None:
            self._closed = True

    monkeypatch.setattr("cookimport.plugins.pdf.fitz.open", lambda _path: _FakeDoc())

    progress_messages: list[str] = []
    result = importer.convert(source, None, progress_callback=progress_messages.append)

    assert result.recipes
    assert any(msg.startswith("Extracting candidate 1/1") for msg in progress_messages)
    assert "Analyzing standalone knowledge blocks..." in progress_messages
    assert "Finalizing PDF extraction results..." in progress_messages
    assert progress_messages[-1] == "PDF conversion complete."


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


def test_extract_standalone_tips_parallel_progress_and_order(monkeypatch, tmp_path: Path) -> None:
    importer = PdfImporter()
    monkeypatch.setattr(importer, "_overrides", None, raising=False)
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF-1.4 dummy")
    blocks = [
        Block(text="late", page=0),
        Block(text="fast", page=0),
    ]
    containers = [
        TopicContainer(indices=[0], blocks=[(0, "late")], header=None),
        TopicContainer(indices=[1], blocks=[(1, "fast")], header=None),
    ]

    monkeypatch.setattr(
        "cookimport.plugins.pdf.chunk_standalone_blocks",
        lambda *_args, **_kwargs: containers,
    )
    monkeypatch.setattr(
        "cookimport.plugins.pdf.split_text_to_atoms",
        lambda text, block_index, **_kwargs: [
            Atom(
                text=text,
                kind="paragraph",
                source_block_index=block_index,
                sequence=0,
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.plugins.pdf.contextualize_atoms",
        lambda atoms: atoms,
    )
    monkeypatch.setattr(
        "cookimport.plugins.pdf.build_topic_candidate",
        lambda text, **_kwargs: {"topic": text},
    )

    def _fake_extract_tip_candidates(text: str, **_kwargs):
        if text == "late":
            time.sleep(0.03)
        return [{"tip": text}]

    monkeypatch.setattr(
        "cookimport.plugins.pdf.extract_tip_candidates",
        _fake_extract_tip_candidates,
    )
    monkeypatch.setenv("C3IMP_STANDALONE_ANALYSIS_WORKERS", "2")

    progress_messages: list[str] = []
    tips, topics, standalone_block_count, topic_block_count = importer._extract_standalone_tips(
        blocks,
        [],
        source,
        "hash",
        progress_callback=progress_messages.append,
    )

    assert standalone_block_count == 2
    assert topic_block_count == 2
    assert [tip["tip"] for tip in tips] == ["late", "fast"]
    assert [topic["topic"] for topic in topics] == ["late", "fast"]
    assert any(
        "Analyzing standalone knowledge blocks... task 0/2" in msg
        for msg in progress_messages
    )
    assert any(
        "Analyzing standalone knowledge blocks... task 2/2" in msg
        for msg in progress_messages
    )
