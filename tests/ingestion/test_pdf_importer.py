from __future__ import annotations

import pytest
from pathlib import Path
from cookimport.config.run_settings import RunSettings
from cookimport.core.blocks import Block
from cookimport.core.models import RecipeCandidate
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

    assert result.recipes == []
    assert any("PDF Pancakes" in block.text for block in result.source_blocks)
    assert any("1 cup flour" in block.text for block in result.source_blocks)
    assert any(
        support.kind == "candidate_recipe_region" for support in result.source_support
    )


def test_convert_pdf_pdf_ocr_policy_off_skips_ocr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "policy-off.pdf"
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
    monkeypatch.setattr(
        importer,
        "_extract_blocks_via_ocr",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("OCR should be disabled when pdf_ocr_policy=off.")
        ),
    )
    monkeypatch.setattr(importer, "_needs_ocr", lambda _doc: True)
    monkeypatch.setattr("cookimport.plugins.pdf._ocr_available", lambda: True)
    monkeypatch.setattr(
        importer,
        "_detect_candidates",
        lambda _blocks: [(0, len(blocks), 0.9)],
    )
    monkeypatch.setattr(
        importer,
        "_extract_fields",
        lambda _candidate_blocks: RecipeCandidate(
            name="PDF Pancakes",
            ingredients=["1 cup flour"],
            instructions=["Mix it all."],
        ),
    )
    class _FakeDoc:
        def __len__(self) -> int:
            return 1

        def __getitem__(self, _index: int) -> object:
            return object()

        def close(self) -> None:
            return

    monkeypatch.setattr("cookimport.plugins.pdf.fitz.open", lambda _path: _FakeDoc())

    result = importer.convert(
        source,
        None,
        run_settings=RunSettings(pdf_ocr_policy="off"),
    )

    full_text = next(artifact for artifact in result.raw_artifacts if artifact.location_id == "full_text")
    assert full_text.content["ocr_used"] is False


def test_convert_pdf_pdf_ocr_policy_always_forces_ocr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "policy-always.pdf"
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
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Text extraction should be bypassed when pdf_ocr_policy=always.")
        ),
    )
    monkeypatch.setattr(
        importer,
        "_extract_blocks_via_ocr",
        lambda *_args, **_kwargs: list(blocks),
    )
    monkeypatch.setattr(importer, "_needs_ocr", lambda _doc: False)
    monkeypatch.setattr("cookimport.plugins.pdf._ocr_available", lambda: True)
    monkeypatch.setattr(
        importer,
        "_detect_candidates",
        lambda _blocks: [(0, len(blocks), 0.9)],
    )
    monkeypatch.setattr(
        importer,
        "_extract_fields",
        lambda _candidate_blocks: RecipeCandidate(
            name="PDF Pancakes",
            ingredients=["1 cup flour"],
            instructions=["Mix it all."],
        ),
    )
    class _FakeDoc:
        def __len__(self) -> int:
            return 1

        def __getitem__(self, _index: int) -> object:
            return object()

        def close(self) -> None:
            return

    monkeypatch.setattr("cookimport.plugins.pdf.fitz.open", lambda _path: _FakeDoc())

    result = importer.convert(
        source,
        None,
        run_settings=RunSettings(pdf_ocr_policy="always"),
    )

    full_text = next(artifact for artifact in result.raw_artifacts if artifact.location_id == "full_text")
    assert full_text.content["ocr_used"] is True


def test_derive_column_boundaries_respects_pdf_column_gap_ratio() -> None:
    importer = PdfImporter()
    blocks = [
        Block(text="A", bbox=[100.0, 0.0, 160.0, 10.0]),
        Block(text="B", bbox=[190.0, 0.0, 250.0, 10.0]),
        Block(text="C", bbox=[280.0, 0.0, 340.0, 10.0]),
        Block(text="D", bbox=[370.0, 0.0, 430.0, 10.0]),
    ]

    importer._pdf_column_gap_ratio = 0.12
    assert importer._derive_column_boundaries(blocks, page_width=1000.0) == []

    importer._pdf_column_gap_ratio = 0.08
    boundaries = importer._derive_column_boundaries(blocks, page_width=1000.0)
    assert boundaries == [145.0, 235.0, 325.0]


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

    assert result.recipes == []
    assert any(msg.startswith("Segmenting 5 blocks") for msg in progress_messages)
    assert "Finalizing PDF extraction results..." in progress_messages
    assert progress_messages[-1] == "PDF conversion complete."


def test_convert_pdf_emits_pattern_diagnostics_and_trim_actions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "pattern.pdf"
    source.write_bytes(b"%PDF-1.4 dummy")
    importer = PdfImporter()
    blocks = [
        Block(text="Table of Contents", page=0),
        Block(text="Soups .......... 7", page=0),
        Block(text="Stews .......... 12", page=0),
        Block(text="Desserts .......... 44", page=0),
        Block(text="Herb Bread", page=0),
        Block(text="A short intro sentence.", page=0),
        Block(text="Herb Bread", page=0),
        Block(text="Ingredients", page=0),
        Block(text="1 cup flour", page=0),
        Block(text="Instructions", page=0),
        Block(text="Bake.", page=0),
    ]
    for block in blocks:
        signals.enrich_block(block)

    monkeypatch.setattr(
        importer,
        "_extract_blocks_from_page",
        lambda _page, _abs_page: list(blocks),
    )
    monkeypatch.setattr(importer, "_needs_ocr", lambda _doc: False)
    monkeypatch.setattr(
        importer,
        "_detect_candidates",
        lambda _blocks: [(0, len(blocks), 0.95)],
    )
    monkeypatch.setattr(
        importer,
        "_extract_fields",
        lambda candidate_blocks: RecipeCandidate(
            name=str(candidate_blocks[0].text),
            recipeIngredient=["1 cup flour"],
            recipeInstructions=["Bake."],
        ),
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

    result = importer.convert(source, None)

    assert result.recipes == []
    proposal = next(
        support for support in result.source_support if support.kind == "candidate_recipe_region"
    )
    assert proposal.payload["start_block"] == 6
    assert proposal.payload["pattern_actions"]
    assert proposal.referenced_block_ids[0] == "b6"
    assert any(
        warning.startswith("pattern_toc_like_cluster_detected:")
        for warning in result.report.warnings
    )
    assert any(
        warning.startswith("pattern_duplicate_title_flow_detected:")
        for warning in result.report.warnings
    )

    diagnostics_artifact = next(
        artifact for artifact in result.raw_artifacts if artifact.location_id == "pattern_diagnostics"
    )
    assert diagnostics_artifact.content["pre_candidate_excluded_indices"] == [0, 1, 2, 3]
    assert diagnostics_artifact.content["candidate_start_trim_actions"]

    source_texts = [block.text for block in result.source_blocks]
    assert "Table of Contents" in source_texts
    assert "A short intro sentence." in source_texts


def test_convert_pdf_applies_multi_recipe_splitter_postprocessing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF-1.4 dummy")
    importer = PdfImporter()
    blocks = [
        Block(text="Recipe One", page=0),
        Block(text="Ingredients", page=0),
        Block(text="1 cup flour", page=0),
        Block(text="Instructions", page=0),
        Block(text="Bake.", page=0),
        Block(text="Recipe Two", page=0),
        Block(text="Ingredients", page=0),
        Block(text="2 eggs", page=0),
        Block(text="Instructions", page=0),
        Block(text="Whisk.", page=0),
    ]
    for block in blocks:
        signals.enrich_block(block)

    monkeypatch.setattr(importer, "_extract_blocks_from_page", lambda _page, _abs_page: list(blocks))
    monkeypatch.setattr(importer, "_needs_ocr", lambda _doc: False)
    monkeypatch.setattr(importer, "_detect_candidates", lambda _blocks: [(0, len(blocks), 0.9)])
    monkeypatch.setattr(
        importer,
        "_apply_multi_recipe_splitter",
        lambda _blocks, _candidates, run_settings=None: (
            [(0, 5, 0.9), (5, len(blocks), 0.9)],
            [
                {
                    "backend": "rules_v1",
                    "split_parent": "c0",
                    "split_index": 0,
                    "split_count": 2,
                    "split_reason": ["title_like_boundary"],
                },
                {
                    "backend": "rules_v1",
                    "split_parent": "c0",
                    "split_index": 1,
                    "split_count": 2,
                    "split_reason": ["title_like_boundary"],
                },
            ],
            {"backend": "rules_v1", "candidates": []},
        ),
    )
    monkeypatch.setattr(
        importer,
        "_extract_fields",
        lambda candidate_blocks: RecipeCandidate(
            name=str(candidate_blocks[0].text),
            ingredients=["1 item"],
            instructions=["1 step"],
        ),
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

    result = importer.convert(
        source,
        None,
        run_settings=RunSettings(
            multi_recipe_splitter="rules_v1",
            multi_recipe_trace=True,
        ),
    )

    proposals = [
        support for support in result.source_support if support.kind == "candidate_recipe_region"
    ]
    assert len(proposals) == 2
    assert proposals[0].payload["multi_recipe"]["split_index"] == 0
    assert proposals[1].payload["multi_recipe"]["split_index"] == 1
    assert any(
        artifact.location_id == "multi_recipe_split_trace"
        for artifact in result.raw_artifacts
    )


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

def test_extract_fields_shared_backend_preserves_for_the_component_headers() -> None:
    importer = PdfImporter()
    importer._section_detector_backend = "shared_v1"
    importer._overrides = None
    blocks = [
        Block(text="Skillet Pie", font_weight="bold"),
        Block(text="Ingredients"),
        Block(text="For the filling"),
        Block(text="2 apples"),
        Block(text="Instructions"),
        Block(text="For the filling"),
        Block(text="Cook apples until soft."),
    ]
    for block in blocks:
        signals.enrich_block(block)

    candidate = importer._extract_fields(blocks)

    assert candidate.name == "Skillet Pie"
    assert candidate.ingredients[:2] == ["For the filling", "2 apples"]
    assert candidate.instructions[:2] == ["For the filling", "Cook apples until soft."]
