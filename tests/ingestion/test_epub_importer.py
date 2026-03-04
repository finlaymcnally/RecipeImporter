from __future__ import annotations

import sys
import time
import types
import pytest
from pathlib import Path
from cookimport.config.run_settings import RunSettings
from cookimport.core.blocks import Block
from cookimport.core.models import RecipeCandidate
from cookimport.parsing.atoms import Atom
from cookimport.parsing.tips import TopicContainer
from cookimport.parsing import signals
from cookimport.plugins.epub import EpubImporter, _resolve_unstructured_version
from tests.fixtures.make_epub import make_synthetic_epub
from tests.paths import FIXTURES_DIR as TESTS_FIXTURES_DIR

FIXTURES_DIR = TESTS_FIXTURES_DIR

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
    assert r1.recipe_likeness is not None
    assert r1.confidence == r1.recipe_likeness.score
    assert len(r1.ingredients) == 2
    assert "1 cup flour" in r1.ingredients
    assert "Mix contents." in r1.instructions
    
    r2 = result.recipes[1]
    assert r2.name == "Simple Salad"
    assert r2.recipe_likeness is not None
    assert r2.confidence == r2.recipe_likeness.score
    assert "Lettuce" in r2.ingredients


def test_convert_epub_emits_post_candidate_progress(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    source.write_bytes(b"dummy-epub")
    importer = EpubImporter()
    importer._extractor_diagnostics = {"beautifulsoup": [], "unstructured": [], "markdown": []}
    importer._extractor_meta = {"beautifulsoup": {}, "unstructured": {}, "markdown": {}}
    importer._unstructured_spine_xhtml = []
    importer._markitdown_markdown = None
    blocks = [
        Block(text="Skillet Bread"),
        Block(text="Ingredients"),
        Block(text="1 cup flour"),
        Block(text="Instructions"),
        Block(text="Mix ingredients."),
    ]
    for block in blocks:
        signals.enrich_block(block)

    monkeypatch.setenv("C3IMP_EPUB_EXTRACTOR", "beautifulsoup")
    monkeypatch.setattr(importer, "_extract_docpack", lambda *_args, **_kwargs: blocks)
    monkeypatch.setattr(
        importer,
        "_detect_candidates",
        lambda _blocks: [(0, len(blocks), 0.9)],
    )
    monkeypatch.setattr(
        importer,
        "_extract_fields",
        lambda _candidate_blocks: RecipeCandidate(
            name="Skillet Bread",
            ingredients=["1 cup flour"],
            instructions=["Mix ingredients."],
        ),
    )
    monkeypatch.setattr(
        importer,
        "_extract_standalone_tips",
        lambda *_args, **_kwargs: ([], [], 0, 0),
    )

    progress_messages: list[str] = []
    result = importer.convert(source, None, progress_callback=progress_messages.append)

    assert result.recipes
    assert any(msg.startswith("Extracting candidate 1/1") for msg in progress_messages)
    assert "Analyzing standalone knowledge blocks..." in progress_messages
    assert "Finalizing EPUB extraction results..." in progress_messages
    assert progress_messages[-1] == "EPUB conversion complete."


def test_convert_epub_emits_pattern_diagnostics_and_trim_actions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "pattern.epub"
    source.write_bytes(b"dummy-epub")
    importer = EpubImporter()
    importer._extractor_diagnostics = {"beautifulsoup": [], "unstructured": [], "markdown": []}
    importer._extractor_meta = {"beautifulsoup": {}, "unstructured": {}, "markdown": {}}
    importer._unstructured_spine_xhtml = []
    importer._markitdown_markdown = None
    blocks = [
        Block(text="Table of Contents"),
        Block(text="Soups .......... 7"),
        Block(text="Stews .......... 12"),
        Block(text="Desserts .......... 44"),
        Block(text="Herb Bread"),
        Block(text="A short intro sentence."),
        Block(text="Herb Bread"),
        Block(text="Ingredients"),
        Block(text="1 cup flour"),
        Block(text="Instructions"),
        Block(text="Bake."),
    ]
    for block in blocks:
        signals.enrich_block(block)

    monkeypatch.setenv("C3IMP_EPUB_EXTRACTOR", "beautifulsoup")
    monkeypatch.setattr(importer, "_extract_docpack", lambda *_args, **_kwargs: blocks)
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
    monkeypatch.setattr(
        importer,
        "_extract_standalone_tips",
        lambda *_args, **_kwargs: ([], [], 0, 0),
    )

    result = importer.convert(source, None)

    assert len(result.recipes) == 1
    location = result.recipes[0].provenance["location"]
    assert location["start_block"] == 6
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

    non_recipe_text = [row["text"] for row in result.non_recipe_blocks]
    assert "Table of Contents" in non_recipe_text
    assert "A short intro sentence." in non_recipe_text


def test_convert_epub_applies_multi_recipe_splitter_postprocessing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_bytes(b"dummy-epub")
    importer = EpubImporter()
    importer._extractor_diagnostics = {"beautifulsoup": [], "unstructured": [], "markdown": []}
    importer._extractor_meta = {"beautifulsoup": {}, "unstructured": {}, "markdown": {}}
    importer._unstructured_spine_xhtml = []
    importer._markitdown_markdown = None
    blocks = [
        Block(text="Recipe One"),
        Block(text="Ingredients"),
        Block(text="1 cup flour"),
        Block(text="Instructions"),
        Block(text="Bake."),
        Block(text="Recipe Two"),
        Block(text="Ingredients"),
        Block(text="2 eggs"),
        Block(text="Instructions"),
        Block(text="Whisk."),
    ]
    for block in blocks:
        signals.enrich_block(block)

    monkeypatch.setenv("C3IMP_EPUB_EXTRACTOR", "beautifulsoup")
    monkeypatch.setattr(importer, "_extract_docpack", lambda *_args, **_kwargs: blocks)
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
    monkeypatch.setattr(
        importer,
        "_extract_standalone_tips",
        lambda *_args, **_kwargs: ([], [], 0, 0),
    )

    result = importer.convert(
        source,
        None,
        run_settings=RunSettings(
            multi_recipe_splitter="rules_v1",
            multi_recipe_trace=True,
        ),
    )

    assert len(result.recipes) == 2
    assert result.recipes[0].provenance["multi_recipe"]["split_index"] == 0
    assert result.recipes[1].provenance["multi_recipe"]["split_index"] == 1
    assert any(
        artifact.location_id == "multi_recipe_split_trace"
        for artifact in result.raw_artifacts
    )


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


def test_extract_standalone_tips_parallel_progress_and_order(monkeypatch, tmp_path: Path) -> None:
    importer = EpubImporter()
    source = tmp_path / "book.epub"
    source.write_text("dummy", encoding="utf-8")
    blocks = [Block(text="late"), Block(text="fast")]
    containers = [
        TopicContainer(indices=[0], blocks=[(0, "late")], header=None),
        TopicContainer(indices=[1], blocks=[(1, "fast")], header=None),
    ]

    monkeypatch.setattr(
        "cookimport.plugins.epub.chunk_standalone_blocks",
        lambda *_args, **_kwargs: containers,
    )
    monkeypatch.setattr(
        "cookimport.plugins.epub.split_text_to_atoms",
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
        "cookimport.plugins.epub.contextualize_atoms",
        lambda atoms: atoms,
    )
    monkeypatch.setattr(
        "cookimport.plugins.epub.build_topic_candidate",
        lambda text, **_kwargs: {"topic": text},
    )

    def _fake_extract_tip_candidates(text: str, **_kwargs):
        if text == "late":
            time.sleep(0.03)
        return [{"tip": text}]

    monkeypatch.setattr(
        "cookimport.plugins.epub.extract_tip_candidates",
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


def test_extract_standalone_tips_filters_noise_and_tracks_split_diagnostics(
    monkeypatch,
    tmp_path: Path,
) -> None:
    importer = EpubImporter()
    source = tmp_path / "book.epub"
    source.write_text("dummy", encoding="utf-8")
    long_intro = (
        "I remember those early afternoons and I always thought this quiet routine "
        "was enough to teach me patience and curiosity in a way nothing else could. "
        "I remember those early afternoons and I always thought this quiet routine "
        "was enough to teach me patience and curiosity in a way nothing else could."
    )
    long_actionable = " ".join(
        [
            "Salt early for flavor.",
            "Keep the pan hot for browning.",
            "Let the meat rest before slicing.",
        ]
        * 12
    )
    blocks = [
        Block(text="Table of Contents"),
        Block(text="Simple Soup"),
        Block(text=long_intro),
        Block(text=long_actionable),
    ]

    captured_blocks: dict[str, list[tuple[int, str]]] = {}

    def _fake_chunk_standalone_blocks(raw_blocks, **_kwargs):
        rows = list(raw_blocks)
        captured_blocks["rows"] = rows
        return [
            TopicContainer(indices=[idx], blocks=[(idx, text)], header=None)
            for idx, text in rows
        ]

    monkeypatch.setattr(
        "cookimport.plugins.epub.chunk_standalone_blocks",
        _fake_chunk_standalone_blocks,
    )
    monkeypatch.setattr(
        "cookimport.plugins.epub.split_text_to_atoms",
        lambda text, block_index, **_kwargs: [
            Atom(
                text=text,
                kind="paragraph",
                source_block_index=block_index,
                sequence=0,
            )
        ],
    )
    monkeypatch.setattr("cookimport.plugins.epub.contextualize_atoms", lambda atoms: atoms)
    monkeypatch.setattr(
        "cookimport.plugins.epub.build_topic_candidate",
        lambda text, **_kwargs: {"topic": text},
    )
    monkeypatch.setattr(
        "cookimport.plugins.epub.extract_tip_candidates",
        lambda text, **_kwargs: [{"tip": text}],
    )
    monkeypatch.setenv("C3IMP_STANDALONE_ANALYSIS_WORKERS", "1")

    tips, topics, standalone_block_count, _topic_block_count = importer._extract_standalone_tips(
        blocks,
        [],
        source,
        "hash",
        accepted_recipe_titles=["Simple Soup"],
    )

    assert standalone_block_count == 4
    assert len(tips) == len(topics)
    assert len(captured_blocks["rows"]) > 1

    diagnostics = importer._standalone_filter_diagnostics
    assert diagnostics["candidate_standalone_block_count"] == 4
    assert diagnostics["analyzed_standalone_block_count"] == len(captured_blocks["rows"])
    assert diagnostics["filter_reason_counts"]["toc_noise"] == 1
    assert diagnostics["filter_reason_counts"]["duplicate_title_carryover"] == 1
    assert diagnostics["filter_reason_counts"]["intro_narrative"] == 1
    assert diagnostics["long_split_source_blocks"] == 1
    assert diagnostics["long_split_segments_added"] >= 1


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


def test_extract_fields_shared_backend_preserves_for_the_component_headers() -> None:
    importer = EpubImporter()
    importer._section_detector_backend = "shared_v1"
    importer._overrides = None
    blocks = [
        Block(text="Apple Tart", font_weight="bold"),
        Block(text="Ingredients"),
        Block(text="For the Frangipane"),
        Block(text="3/4 cup almonds"),
        Block(text="Instructions"),
        Block(text="For the Frangipane"),
        Block(text="Mix almonds and sugar."),
    ]
    for block in blocks:
        signals.enrich_block(block)

    candidate = importer._extract_fields(blocks)

    assert candidate.name == "Apple Tart"
    assert candidate.ingredients[:2] == ["For the Frangipane", "3/4 cup almonds"]
    assert candidate.instructions[:2] == ["For the Frangipane", "Mix almonds and sugar."]
