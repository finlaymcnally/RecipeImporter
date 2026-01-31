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
