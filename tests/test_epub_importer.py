from __future__ import annotations

import sys
import types
import pytest
from pathlib import Path
from cookimport.core.blocks import Block
from cookimport.parsing import signals
from cookimport.plugins.epub import EpubImporter, _resolve_unstructured_version
from tests.fixtures.make_epub import make_synthetic_epub

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


def test_convert_epub_markitdown_writes_markdown_artifact(monkeypatch, tmp_path: Path):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"dummy-epub")

    monkeypatch.setenv("C3IMP_EPUB_EXTRACTOR", "markitdown")
    monkeypatch.setattr(
        "cookimport.plugins.epub.convert_path_to_markdown",
        lambda _path: (
            "# Pancakes\n\n"
            "## Ingredients\n"
            "- 1 cup flour\n"
            "- 1 cup milk\n\n"
            "## Instructions\n"
            "1. Mix ingredients\n"
        ),
    )

    importer = EpubImporter()
    result = importer.convert(epub_path, None)

    assert result.report.epub_backend == "markitdown"
    markdown_artifact = next(
        artifact for artifact in result.raw_artifacts if artifact.location_id == "markitdown_markdown"
    )
    assert markdown_artifact.extension == "md"
    assert "Ingredients" in str(markdown_artifact.content)

    full_text_artifact = next(
        artifact for artifact in result.raw_artifacts if artifact.location_id == "full_text"
    )
    first_block = full_text_artifact.content["blocks"][0]
    assert first_block["features"]["extraction_backend"] == "markitdown"
    assert first_block["features"]["md_line_start"] == 1
    assert first_block["features"]["md_line_end"] == 1


def test_convert_epub_unstructured_writes_option_metadata_and_spine_html_artifacts(
    monkeypatch,
):
    epub_path = FIXTURES_DIR / "sample.epub"
    if not epub_path.exists():
        pytest.skip("sample.epub not found")

    monkeypatch.setenv("C3IMP_EPUB_EXTRACTOR", "unstructured")
    monkeypatch.setenv("C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION", "v2")
    monkeypatch.setenv("C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS", "true")
    monkeypatch.setenv("C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE", "br_split_v1")

    importer = EpubImporter()
    result = importer.convert(epub_path, None)

    diag_artifact = next(
        artifact
        for artifact in result.raw_artifacts
        if artifact.location_id == "unstructured_elements"
    )
    assert diag_artifact.metadata["unstructured_html_parser_version"] == "v2"
    assert diag_artifact.metadata["unstructured_skip_headers_footers"] is True
    assert diag_artifact.metadata["unstructured_preprocess_mode"] == "br_split_v1"

    raw_spine = [
        artifact
        for artifact in result.raw_artifacts
        if artifact.location_id.startswith("raw_spine_xhtml_")
    ]
    normalized_spine = [
        artifact
        for artifact in result.raw_artifacts
        if artifact.location_id.startswith("norm_spine_xhtml_")
    ]
    assert raw_spine
    assert normalized_spine
    assert len(raw_spine) == len(normalized_spine)


def test_convert_epub_markdown_writes_diagnostics_artifact(tmp_path: Path, monkeypatch) -> None:
    source = make_synthetic_epub(
        tmp_path / "markdown.epub",
        spine_documents=[
            (
                "chapter1.xhtml",
                """
                <h1>Skillet Bread</h1>
                <h2>Ingredients</h2>
                <ul><li>1 cup flour</li><li>1 egg</li></ul>
                <h2>Instructions</h2>
                <p>Mix ingredients.</p>
                """,
            ),
        ],
    )
    monkeypatch.setenv("C3IMP_EPUB_EXTRACTOR", "markdown")

    result = EpubImporter().convert(source, None)

    assert result.report.epub_backend == "markdown"
    markdown_artifact = next(
        artifact
        for artifact in result.raw_artifacts
        if artifact.location_id == "markdown_blocks"
    )
    assert markdown_artifact.extension == "jsonl"
    assert markdown_artifact.metadata["extractor"] == "markdown"
    assert markdown_artifact.metadata["element_count"] > 0


def test_resolve_unstructured_version_handles_module_value(monkeypatch):
    version_module = types.ModuleType("unstructured.__version__")
    version_module.__version__ = "9.9.9"

    package_module = types.ModuleType("unstructured")
    package_module.__version__ = version_module

    def _raise_missing(_dist_name: str) -> str:
        raise RuntimeError("not installed")

    monkeypatch.setattr("cookimport.plugins.epub.importlib_metadata.version", _raise_missing)
    monkeypatch.setitem(sys.modules, "unstructured", package_module)

    assert _resolve_unstructured_version() == "9.9.9"


def test_backtrack_for_title_prefers_earliest_title_block():
    importer = EpubImporter()
    blocks = [
        Block(text="Classic Rice Pilaf"),
        Block(text="classic rice pilaf", font_weight="bold"),
        Block(text="serves 2"),
    ]

    for block in blocks:
        signals.enrich_block(block)

    title_idx = importer._backtrack_for_title(blocks, anchor_idx=2, limit=4)
    assert title_idx == 0


def test_find_recipe_end_stops_on_all_caps_section_intro():
    importer = EpubImporter()
    blocks = [
        Block(text="Grill Artichokes", font_weight="bold"),
        Block(text="Ingredients"),
        Block(text="6 artichokes"),
        Block(text="Instructions"),
        Block(text="Cook the artichokes."),
        Block(
            text=(
                "STOCK AND SOUPS Stock With stock on hand, dinner is always within reach."
            )
        ),
        Block(text="Every time you roast a chicken, save the bones for stock."),
    ]

    for block in blocks:
        signals.enrich_block(block)

    end_idx = importer._find_recipe_end(blocks, start_idx=0, anchor_idx=1)
    assert end_idx == 5


def test_find_recipe_end_stops_on_single_word_all_caps_section_intro():
    importer = EpubImporter()
    blocks = [
        Block(text="Onion Salad", font_weight="bold"),
        Block(text="Ingredients"),
        Block(text="2 onions"),
        Block(text="Instructions"),
        Block(text="Slice onions."),
        Block(
            text=(
                "VEGETABLES Cooking Onions The longer you cook onions, the deeper their "
                "flavor will be."
            )
        ),
        Block(text="Cook all onions until they lose their crunch."),
    ]

    for block in blocks:
        signals.enrich_block(block)

    end_idx = importer._find_recipe_end(blocks, start_idx=0, anchor_idx=1)
    assert end_idx == 5


def test_find_recipe_end_stops_on_all_caps_heading_block():
    importer = EpubImporter()
    blocks = [
        Block(text="Peanut-Lime Dressing", font_weight="bold"),
        Block(text="Makes about 1 3/4 cups"),
        Block(text="1 cup peanut butter"),
        Block(text="Mix well."),
        Block(text="VEGETABLES", font_weight="bold"),
        Block(text="Cooking Onions", font_weight="bold"),
        Block(text="The longer you cook onions, the deeper their flavor will be."),
    ]

    for block in blocks:
        signals.enrich_block(block)
    blocks[4].add_feature("is_heading", True)
    blocks[4].add_feature("heading_level", 2)
    blocks[5].add_feature("is_heading", True)
    blocks[5].add_feature("heading_level", 3)

    end_idx = importer._find_recipe_end(blocks, start_idx=0, anchor_idx=1)
    assert end_idx == 4


def test_find_recipe_end_includes_variation_section():
    """Test that Variation headers and their content stay with the recipe."""
    importer = EpubImporter()
    blocks = [
        Block(text="Red Wine Vinaigrette", font_weight="bold"),
        Block(text="Makes 1 cup"),
        Block(text="1/4 cup red wine vinegar"),
        Block(text="3/4 cup olive oil"),
        Block(text="Whisk together."),
        Block(text="Variation", font_weight="bold"),  # Should stay with recipe
        Block(text="• To make Honey-Mustard Vinaigrette, add honey and mustard."),
        Block(text="Balsamic Vinaigrette", font_weight="bold"),  # Next recipe title
        Block(text="Ingredients"),
    ]

    for block in blocks:
        signals.enrich_block(block)
    blocks[5].add_feature("is_heading", True)
    blocks[5].add_feature("heading_level", 5)
    blocks[7].add_feature("is_heading", True)
    blocks[7].add_feature("heading_level", 3)

    end_idx = importer._find_recipe_end(blocks, start_idx=0, anchor_idx=1)
    # Should include up through block 6 (the variation content), stopping at block 7 (next recipe title)
    # The next recipe detection happens at block 8 (Ingredients header), backtracking to title at block 7
    assert end_idx == 7


def test_is_variation_header():
    """Test that variation headers are correctly identified."""
    importer = EpubImporter()

    variation_texts = ["Variation", "Variations", "Variant", "Variants", "variation:", "VARIATION"]
    for text in variation_texts:
        block = Block(text=text)
        assert importer._is_variation_header(block), f"Should identify '{text}' as variation header"

    non_variation_texts = ["Variation: add herbs", "My Variation", "Instructions", "Ingredients"]
    for text in non_variation_texts:
        block = Block(text=text)
        assert not importer._is_variation_header(block), f"Should NOT identify '{text}' as variation header"


def test_is_subsection_header():
    """Test that sub-section headers like 'For the Frangipane' are correctly identified."""
    importer = EpubImporter()

    # Should be identified as subsection headers
    subsection_texts = [
        "For the Frangipane",
        "For the Tart",
        "For the Sauce",
        "For the Crust",
        "For Filling",
        "FOR THE GLAZE",
    ]
    for text in subsection_texts:
        block = Block(text=text)
        assert importer._is_subsection_header(block), f"Should identify '{text}' as subsection header"

    # Should NOT be identified as subsection headers
    non_subsection_texts = [
        "Apple and Frangipane Tart",  # Recipe title
        "For best results, use fresh ingredients.",  # Instruction with "For"
        "Ingredients",  # Standard header
        "Instructions",
        "For this recipe you will need a mixer.",  # Too long / instruction-like
    ]
    for text in non_subsection_texts:
        block = Block(text=text)
        assert not importer._is_subsection_header(block), f"Should NOT identify '{text}' as subsection header"


def test_find_recipe_end_includes_subsection_headers():
    """Test that 'For the X' subsection headers stay with the recipe instead of starting a new one."""
    importer = EpubImporter()
    blocks = [
        Block(text="Apple and Frangipane Tart", font_weight="bold"),
        Block(text="Makes one 14-inch tart"),
        Block(text="For the Frangipane", font_weight="bold"),  # Should stay with recipe
        Block(text="3/4 cup almonds"),
        Block(text="3 tablespoons sugar"),
        Block(text="For the Tart", font_weight="bold"),  # Should stay with recipe
        Block(text="1 recipe Tart Dough"),
        Block(text="Flour for rolling"),
        Block(text="Place almonds in food processor."),
        Block(text="Banana Bread", font_weight="bold"),  # Next recipe title
        Block(text="Ingredients"),  # Ingredient header to trigger detection
        Block(text="3 ripe bananas"),
    ]

    for block in blocks:
        signals.enrich_block(block)
    # Mark headings
    blocks[2].add_feature("is_heading", True)
    blocks[2].add_feature("heading_level", 3)
    blocks[5].add_feature("is_heading", True)
    blocks[5].add_feature("heading_level", 3)
    blocks[9].add_feature("is_heading", True)
    blocks[9].add_feature("heading_level", 2)
    # Block 10 is ingredient header which will trigger recipe detection

    end_idx = importer._find_recipe_end(blocks, start_idx=0, anchor_idx=1)
    # Should include all blocks through the instructions (block 8), stopping at block 9 (next recipe title)
    # The ingredient header at block 10 triggers backtracking to title at block 9
    assert end_idx == 9, f"Expected end at block 9, got {end_idx}"
