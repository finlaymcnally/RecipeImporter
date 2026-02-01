from __future__ import annotations

import pytest
from pathlib import Path
from cookimport.core.blocks import Block
from cookimport.parsing import signals
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
