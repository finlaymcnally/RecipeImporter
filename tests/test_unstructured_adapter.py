"""Tests for the Unstructured HTML → Block adapter and block_role assignment."""

from __future__ import annotations

import json
import os
import pytest

from cookimport.core.blocks import Block, BlockType
from cookimport.parsing import signals
from cookimport.parsing.unstructured_adapter import partition_html_to_blocks
from cookimport.parsing.block_roles import assign_block_roles


# ---------------------------------------------------------------------------
# partition_html_to_blocks — Element → Block mapping
# ---------------------------------------------------------------------------

class TestPartitionHtmlToBlocks:
    """Unit tests for the Unstructured adapter."""

    SIMPLE_HTML = (
        "<html><body>"
        "<h1>Chapter One</h1>"
        "<h2>Pasta Recipe</h2>"
        "<p>A classic Italian dish with rich tomato sauce and fresh basil leaves.</p>"
        "<ul><li>1 cup flour</li><li>2 eggs</li></ul>"
        "<table><tr><td>Nutrition</td></tr></table>"
        "</body></html>"
    )

    def test_returns_blocks_and_diagnostics(self):
        blocks, diag = partition_html_to_blocks(
            self.SIMPLE_HTML, spine_index=0, source_location_id="test"
        )
        assert isinstance(blocks, list)
        assert isinstance(diag, list)
        assert len(blocks) > 0
        assert len(diag) > 0

    def test_title_mapped_to_heading(self):
        blocks, _ = partition_html_to_blocks(
            self.SIMPLE_HTML, spine_index=0, source_location_id="test"
        )
        heading_blocks = [b for b in blocks if b.features.get("is_heading")]
        assert len(heading_blocks) >= 1
        assert heading_blocks[0].font_weight == "bold"

    def test_heading_level_from_category_depth(self):
        blocks, _ = partition_html_to_blocks(
            self.SIMPLE_HTML, spine_index=0, source_location_id="test"
        )
        headings = [b for b in blocks if b.features.get("is_heading")]
        # First Title (h1) should have category_depth=0 → heading_level=1
        assert headings[0].features["heading_level"] == 1
        # Second Title (h2) should have category_depth=1 → heading_level=2
        if len(headings) >= 2:
            assert headings[1].features["heading_level"] == 2

    def test_list_item_flagged(self):
        blocks, _ = partition_html_to_blocks(
            self.SIMPLE_HTML, spine_index=0, source_location_id="test"
        )
        list_blocks = [b for b in blocks if b.features.get("is_list_item")]
        assert len(list_blocks) >= 2

    def test_table_block_type(self):
        blocks, _ = partition_html_to_blocks(
            self.SIMPLE_HTML, spine_index=0, source_location_id="test"
        )
        table_blocks = [b for b in blocks if b.type == BlockType.TABLE]
        assert len(table_blocks) >= 1

    def test_spine_index_preserved(self):
        blocks, _ = partition_html_to_blocks(
            self.SIMPLE_HTML, spine_index=7, source_location_id="test"
        )
        for b in blocks:
            assert b.features["spine_index"] == 7

    def test_element_id_captured(self):
        blocks, _ = partition_html_to_blocks(
            self.SIMPLE_HTML, spine_index=0, source_location_id="test"
        )
        for b in blocks:
            # element_id may be None in some edge cases but should be present
            assert "unstructured_element_id" in b.features

    def test_element_index_sequential(self):
        blocks, _ = partition_html_to_blocks(
            self.SIMPLE_HTML, spine_index=0, source_location_id="test"
        )
        indices = [b.features["unstructured_element_index"] for b in blocks]
        # Indices should be monotonically increasing (some may be skipped due to empty-text filtering)
        assert indices == sorted(indices)

    def test_stable_key_format(self):
        blocks, _ = partition_html_to_blocks(
            self.SIMPLE_HTML, spine_index=3, source_location_id="my-book"
        )
        for b in blocks:
            key = b.features["unstructured_stable_key"]
            assert key.startswith("my-book:spine3:e")
            # Should end with the element index
            idx = b.features["unstructured_element_index"]
            assert key == f"my-book:spine3:e{idx}"

    def test_empty_text_skipped(self):
        html = "<html><body><p></p><p>  </p><p>Real text.</p></body></html>"
        blocks, _ = partition_html_to_blocks(
            html, spine_index=0, source_location_id="test"
        )
        for b in blocks:
            assert b.text.strip()

    def test_unstructured_category_stored(self):
        blocks, _ = partition_html_to_blocks(
            self.SIMPLE_HTML, spine_index=0, source_location_id="test"
        )
        categories = {b.features["unstructured_category"] for b in blocks}
        assert "Title" in categories

    def test_diagnostics_row_structure(self):
        _, diag = partition_html_to_blocks(
            self.SIMPLE_HTML, spine_index=2, source_location_id="book"
        )
        required_keys = {
            "source_location_id", "spine_index", "element_index",
            "element_id", "stable_key", "category", "category_depth",
            "parent_id", "text",
        }
        for row in diag:
            assert required_keys.issubset(row.keys()), (
                f"Missing keys: {required_keys - row.keys()}"
            )
            assert row["spine_index"] == 2
            assert row["source_location_id"] == "book"

    def test_diagnostics_json_serializable(self):
        _, diag = partition_html_to_blocks(
            self.SIMPLE_HTML, spine_index=0, source_location_id="test"
        )
        for row in diag:
            json.dumps(row)  # Should not raise

    def test_ordering_preserved(self):
        """Block order must match HTML document order."""
        html = (
            "<html><body>"
            "<h1>First</h1><p>Second paragraph with enough text to be narrative.</p>"
            "<h2>Third</h2><p>Fourth paragraph with enough text to be considered substantial.</p>"
            "</body></html>"
        )
        blocks, _ = partition_html_to_blocks(
            html, spine_index=0, source_location_id="test"
        )
        texts = [b.text for b in blocks]
        assert texts[0] == "First"
        assert "Second" in texts[1]
        assert texts[2] == "Third"
        assert "Fourth" in texts[3]


# ---------------------------------------------------------------------------
# Split-spine merge ordering
# ---------------------------------------------------------------------------

class TestSplitSpineMerge:
    """Test that blocks from different spine ranges merge deterministically."""

    def test_spine_index_increases_across_spines(self):
        html_a = "<html><body><h1>Chapter A</h1><p>Content A text long enough to be narrative.</p></body></html>"
        html_b = "<html><body><h1>Chapter B</h1><p>Content B text long enough to be narrative.</p></body></html>"

        blocks_a, _ = partition_html_to_blocks(html_a, spine_index=0, source_location_id="test")
        blocks_b, _ = partition_html_to_blocks(html_b, spine_index=1, source_location_id="test")

        merged = blocks_a + blocks_b
        spine_indices = [b.features["spine_index"] for b in merged]
        # spine_index should be non-decreasing after merge
        for i in range(1, len(spine_indices)):
            assert spine_indices[i] >= spine_indices[i - 1]

    def test_split_job_produces_disjoint_spine_ranges(self):
        """Simulates two workers: worker 0 gets spines [0,1), worker 1 gets [1,2)."""
        html_0 = "<html><body><h1>Spine 0</h1></body></html>"
        html_1 = "<html><body><h1>Spine 1</h1></body></html>"

        # Worker 0
        blocks_0, diag_0 = partition_html_to_blocks(html_0, spine_index=0, source_location_id="test")
        # Worker 1
        blocks_1, diag_1 = partition_html_to_blocks(html_1, spine_index=1, source_location_id="test")

        all_blocks = blocks_0 + blocks_1
        all_diag = diag_0 + diag_1

        # Spine indices are disjoint per worker
        spines_0 = {b.features["spine_index"] for b in blocks_0}
        spines_1 = {b.features["spine_index"] for b in blocks_1}
        assert spines_0.isdisjoint(spines_1)

        # Stable keys are globally unique
        keys = [b.features["unstructured_stable_key"] for b in all_blocks]
        assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# block_roles — deterministic role assignment
# ---------------------------------------------------------------------------

class TestBlockRoles:
    """Test assign_block_roles heuristics."""

    def _make_block(self, text: str, **features) -> Block:
        b = Block(text=text)
        signals.enrich_block(b)
        for k, v in features.items():
            b.add_feature(k, v)
        return b

    def test_ingredient_line_by_quantity(self):
        b = self._make_block("1 cup flour")
        assign_block_roles([b])
        assert b.features["block_role"] == "ingredient_line"

    def test_instruction_line_by_verb(self):
        b = self._make_block("Preheat the oven to 350 degrees.")
        assign_block_roles([b])
        assert b.features["block_role"] == "instruction_line"

    def test_metadata_yield(self):
        b = self._make_block("Serves 4")
        assign_block_roles([b])
        assert b.features["block_role"] == "metadata"

    def test_metadata_time(self):
        b = self._make_block("Prep time: 20 minutes")
        assign_block_roles([b])
        assert b.features["block_role"] == "metadata"

    def test_section_heading(self):
        b = self._make_block("Chapter One", is_heading=True, heading_level=1)
        assign_block_roles([b])
        assert b.features["block_role"] == "section_heading"

    def test_recipe_title_heading(self):
        b = self._make_block("Grandma's Famous Cookies", is_heading=True, heading_level=3)
        assign_block_roles([b])
        assert b.features["block_role"] == "recipe_title"

    def test_tip_like(self):
        b = self._make_block("Tip: Use cold butter for a flakier crust.")
        assign_block_roles([b])
        assert b.features["block_role"] == "tip_like"

    def test_narrative_long_text(self):
        b = self._make_block(
            "This chapter explores the fundamental techniques of French pastry, "
            "including lamination, choux, and the science behind gluten development "
            "in enriched doughs."
        )
        assign_block_roles([b])
        assert b.features["block_role"] == "narrative"

    def test_other_short_text(self):
        b = self._make_block("pg 42")
        assign_block_roles([b])
        assert b.features["block_role"] == "other"

    def test_all_blocks_get_role(self):
        blocks = [
            self._make_block("Recipe Title", is_heading=True, heading_level=3),
            self._make_block("1 cup sugar"),
            self._make_block("Mix well and bake for 30 minutes."),
            self._make_block("Serves 6"),
            self._make_block("Note: can be frozen."),
        ]
        assign_block_roles(blocks)
        for b in blocks:
            assert "block_role" in b.features
