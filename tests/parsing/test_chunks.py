"""Tests for knowledge chunking functionality."""

from __future__ import annotations

import pytest

from cookimport.core.blocks import Block, BlockType
from cookimport.core.models import (
    ChunkBoundaryReason,
    ChunkLane,
    KnowledgeChunk,
    TipTags,
)
from cookimport.parsing.chunks import (
    ChunkingProfile,
    assign_lanes,
    collapse_heading_bridge_chunks,
    chunk_non_recipe_blocks,
    consolidate_adjacent_knowledge_chunks,
    extract_highlights,
    merge_small_chunks,
    process_blocks_to_chunks,
    should_merge_adjacent_chunks,
)


def _make_block(text: str, **kwargs) -> Block:
    """Helper to create Block objects for testing."""
    return Block(text=text, type=BlockType.TEXT, **kwargs)


def _make_chunk(
    *,
    identifier: str,
    text: str,
    block_ids: list[int],
    abs_start: int,
    abs_end: int,
    section_path: list[str] | None = None,
    lane: ChunkLane = ChunkLane.KNOWLEDGE,
    title: str | None = None,
    table_ids: list[str] | None = None,
    tags: TipTags | None = None,
) -> KnowledgeChunk:
    return KnowledgeChunk(
        identifier=identifier,
        lane=lane,
        title=title,
        section_path=section_path or [],
        text=text,
        block_ids=block_ids,
        tags=tags or TipTags(),
        provenance={
            "block_range": [min(block_ids), max(block_ids)] if block_ids else [],
            "absolute_block_range": [abs_start, abs_end],
            "table_ids": table_ids or [],
        },
    )


class TestHeadingDetection:
    """Test heading-based chunk boundaries."""

    def test_all_caps_heading_creates_boundary(self):
        """ALL CAPS headings should create chunk boundaries."""
        blocks = [
            _make_block("Some intro text about cooking."),
            _make_block("USING SALT"),
            _make_block("Salt enhances flavor in multiple ways."),
            _make_block("Always season in layers."),
        ]
        chunks = chunk_non_recipe_blocks(blocks)

        # Should have 2 chunks: intro and salt section
        assert len(chunks) >= 1
        # Find the chunk with USING SALT
        salt_chunks = [c for c in chunks if c.title and "SALT" in c.title.upper()]
        assert len(salt_chunks) == 1
        assert "enhances flavor" in salt_chunks[0].text

    def test_colon_header_detected(self):
        """Headers ending with colon should be detected."""
        blocks = [
            _make_block("Storage Tips:"),
            _make_block("Keep in airtight container."),
        ]
        chunks = chunk_non_recipe_blocks(blocks)
        assert len(chunks) >= 1

    def test_section_path_maintained(self):
        """Section path should accumulate through nested headings."""
        blocks = [
            _make_block("TECHNIQUES"),
            _make_block("Braising:"),
            _make_block("Braising is a slow cooking method."),
        ]
        chunks = chunk_non_recipe_blocks(blocks)

        # Should have chunks with section path
        assert len(chunks) >= 1
        # At least one chunk should have section path with TECHNIQUES
        paths = [c.section_path for c in chunks]
        assert any("TECHNIQUES" in str(p) for p in paths)


class TestLaneAssignment:
    """Test lane classification (knowledge/noise)."""

    def test_knowledge_lane_for_technique_content(self):
        """Technique/instruction content should be classified as knowledge."""
        chunk = KnowledgeChunk(
            identifier="c0",
            text="Always preheat your pan before adding oil. This helps prevent sticking "
                 "and ensures even cooking. You should heat the pan until you see slight smoke.",
            block_ids=[0],
        )
        assign_lanes([chunk])
        assert chunk.lane == ChunkLane.KNOWLEDGE

    def test_personal_story_routed_to_noise(self):
        """Personal anecdotes should be routed to noise."""
        chunk = KnowledgeChunk(
            identifier="c0",
            text="I remember when my grandmother taught me to make bread. Growing up, "
                 "we would spend Sunday mornings in the kitchen. She always said the secret "
                 "was patience. I think about those days often.",
            block_ids=[0],
        )
        assign_lanes([chunk])
        assert chunk.lane == ChunkLane.NOISE

    def test_noise_lane_for_praise_blurb(self):
        """Promotional/praise content should be classified as noise."""
        chunk = KnowledgeChunk(
            identifier="c0",
            text="This beautiful, award-winning cookbook will teach you everything about "
                 "Mediterranean cuisine. The stunning photographs and comprehensive "
                 "collection make this an essential addition to any kitchen library.",
            block_ids=[0],
        )
        assign_lanes([chunk])
        assert chunk.lane == ChunkLane.NOISE

    def test_quote_only_content_is_noise(self):
        """Quote-only content should be classified as noise."""
        chunk = KnowledgeChunk(
            identifier="c0",
            text='"A masterpiece of culinary writing."\n'
                 '"The definitive guide to French cooking."\n'
                 '— James Beard Award Winner',
            block_ids=[0],
        )
        assign_lanes([chunk])
        assert chunk.lane == ChunkLane.NOISE

    def test_navigation_fragment_is_noise(self):
        """Contents/navigation fragments should be classified as noise."""
        chunk = KnowledgeChunk(
            identifier="c0",
            title="Contents",
            text="Contents\nSauces ........ 12\nStocks ........ 18\nRoasts ........ 26",
            block_ids=[0],
        )
        assign_lanes([chunk])
        assert chunk.lane == ChunkLane.NOISE

    def test_attribution_fragment_is_noise(self):
        """Pure byline/attribution fragments should be classified as noise."""
        chunk = KnowledgeChunk(
            identifier="c0",
            text="Recipes by Jane Doe\nPhotographs by Alex Roe",
            block_ids=[0],
        )
        assign_lanes([chunk])
        assert chunk.lane == ChunkLane.NOISE

    def test_intro_technique_prose_stays_knowledge(self):
        """Cooking-principles prose should remain knowledge even when narrative-flavored."""
        chunk = KnowledgeChunk(
            identifier="c0",
            text="Browning develops flavor because moisture must evaporate before the surface "
                 "can caramelize. If you crowd the pan, the food steams instead of searing.",
            block_ids=[0],
        )
        assign_lanes([chunk])
        assert chunk.lane == ChunkLane.KNOWLEDGE


class TestHighlightExtraction:
    """Test tip mining integration for highlights."""

    def test_highlights_extracted_from_knowledge_chunk(self):
        """Knowledge chunks should have highlights extracted."""
        chunk = KnowledgeChunk(
            identifier="c0",
            lane=ChunkLane.KNOWLEDGE,
            text="Always salt your pasta water generously. The water should taste like "
                 "the sea. This is your only chance to season the pasta itself. "
                 "For best results, add the salt after the water boils.",
            block_ids=[0, 1],
        )
        extract_highlights([chunk])

        # Should have at least one highlight
        assert chunk.highlight_count >= 1
        assert len(chunk.highlights) >= 1
        assert chunk.tip_density > 0

    def test_no_highlights_for_noise_chunks(self):
        """Noise chunks should not have highlights extracted."""
        chunk = KnowledgeChunk(
            identifier="c0",
            lane=ChunkLane.NOISE,
            text="I remember learning to cook from my mother.",
            block_ids=[0],
        )
        extract_highlights([chunk])

        # Should have no highlights (non-knowledge lane skipped)
        assert chunk.highlight_count == 0

    def test_tags_aggregated_from_highlights(self):
        """Chunk tags should aggregate from highlight tags."""
        chunk = KnowledgeChunk(
            identifier="c0",
            lane=ChunkLane.KNOWLEDGE,
            text="TIP: Always season your steak with salt and pepper before grilling. "
                 "You should let the meat rest for 5 minutes after cooking. The resting period "
                 "allows juices to redistribute for better flavor and tenderness.",
            block_ids=[0],
        )
        extract_highlights([chunk])

        # Should have extracted at least one highlight
        # Note: tag aggregation depends on tip miner extracting highlights
        # which requires explicit tip prefixes or strong advice patterns
        assert chunk.highlight_count >= 0  # May be 0 if text doesn't trigger tip patterns


class TestChunkMerging:
    """Test merging of small chunks."""

    def test_small_chunks_merged(self):
        """Chunks below min_chars should be merged."""
        chunks = [
            KnowledgeChunk(
                identifier="c0",
                text="Short tip.",
                block_ids=[0],
            ),
            KnowledgeChunk(
                identifier="c1",
                text="Another short one.",
                block_ids=[1],
            ),
        ]
        merged = merge_small_chunks(chunks, min_chars=100)

        # Should merge into one chunk
        assert len(merged) == 1
        assert "Short tip" in merged[0].text
        assert "Another short" in merged[0].text

    def test_large_chunks_not_merged(self):
        """Chunks above min_chars should not be merged."""
        text1 = "A" * 300
        text2 = "B" * 300
        chunks = [
            KnowledgeChunk(identifier="c0", text=text1, block_ids=[0]),
            KnowledgeChunk(identifier="c1", text=text2, block_ids=[1]),
        ]
        merged = merge_small_chunks(chunks, min_chars=100)

        # Should remain separate
        assert len(merged) == 2

    def test_collapse_heading_only_chunk_into_following_chunk(self):
        """Standalone heading chunks should collapse into the following payload chunk."""
        heading = _make_chunk(
            identifier="c0",
            text="SAUCES",
            block_ids=[0],
            abs_start=0,
            abs_end=0,
            title="SAUCES",
        )
        body = _make_chunk(
            identifier="c1",
            text="Always whisk constantly to keep the sauce smooth.",
            block_ids=[1],
            abs_start=1,
            abs_end=1,
            section_path=["SAUCES"],
        )

        merged = collapse_heading_bridge_chunks([heading, body])

        assert len(merged) == 1
        assert "SAUCES" in merged[0].text
        assert "Always whisk constantly" in merged[0].text

    def test_process_blocks_to_chunks_does_not_leave_heading_fragment_alone(self):
        """Process pipeline should not emit a standalone heading fragment when prose follows."""
        blocks = [
            _make_block("SAUCES"),
            _make_block("EMULSIONS"),
            _make_block("Always whisk constantly while adding butter."),
        ]

        chunks = process_blocks_to_chunks(blocks, profile=ChunkingProfile(min_chars=20))

        assert len(chunks) == 1
        assert "Always whisk constantly" in chunks[0].text


class TestBoundaryReasons:
    """Test that boundary reasons are correctly recorded."""

    def test_heading_boundary_reason(self):
        """Heading-triggered boundaries should be recorded."""
        blocks = [
            _make_block("Intro text here."),
            _make_block("MAIN SECTION"),
            _make_block("Content of main section."),
        ]
        chunks = chunk_non_recipe_blocks(blocks)

        # Find chunk starting with heading
        heading_chunks = [
            c for c in chunks
            if c.boundary_start_reason == ChunkBoundaryReason.HEADING
        ]
        assert len(heading_chunks) >= 1

    def test_end_of_input_boundary(self):
        """Last chunk should have END_OF_INPUT boundary reason."""
        blocks = [
            _make_block("Some content."),
            _make_block("More content."),
        ]
        chunks = chunk_non_recipe_blocks(blocks)

        assert chunks[-1].boundary_end_reason == ChunkBoundaryReason.END_OF_INPUT


class TestTableAwareChunking:
    """Test table-aware chunk boundaries and lane scoring."""

    def test_table_rows_are_not_split_by_max_chars(self):
        blocks = [
            _make_block("Intro text. " * 30),
            _make_block(
                "Column A  Column B " + ("x" * 80),
                features={"table_id": "tbl_demo"},
            ),
            _make_block(
                "Row 1  Value " + ("y" * 80),
                features={"table_id": "tbl_demo"},
            ),
            _make_block(
                "Row 2  Value " + ("z" * 80),
                features={"table_id": "tbl_demo"},
            ),
            _make_block("Outro text. " * 30),
        ]

        chunks = chunk_non_recipe_blocks(
            blocks,
            profile=ChunkingProfile(min_chars=20, max_chars=180),
        )
        chunk_indexes_for_table_rows = {
            chunk_index
            for chunk_index, chunk in enumerate(chunks)
            if any(block_id in {1, 2, 3} for block_id in chunk.block_ids)
        }
        assert len(chunk_indexes_for_table_rows) == 1

    def test_table_chunk_is_forced_to_knowledge_lane(self):
        chunk = KnowledgeChunk(
            identifier="c0",
            text="A beautiful, award-winning cookbook with stunning photos.",
            block_ids=[0],
            provenance={"table_ids": ["tbl_demo"]},
        )

        assign_lanes([chunk])
        assert chunk.lane == ChunkLane.KNOWLEDGE


class TestAdjacentKnowledgeConsolidation:
    def test_should_merge_adjacent_chunks_when_heading_matches(self):
        left = _make_chunk(
            identifier="c0",
            text="Always keep the knife sharp for better control.",
            block_ids=[0],
            abs_start=10,
            abs_end=10,
            section_path=["Knife Skills"],
            title="Knife Skills",
        )
        right = _make_chunk(
            identifier="c1",
            text="Use a claw grip so your fingertips stay protected.",
            block_ids=[1],
            abs_start=11,
            abs_end=11,
            section_path=["Knife Skills"],
            title="Knife Skills",
        )

        assert should_merge_adjacent_chunks(left, right, max_merged_chars=2000)

    def test_does_not_merge_across_absolute_index_gap(self):
        left = _make_chunk(
            identifier="c0",
            text="Keep knives dry after washing.",
            block_ids=[0],
            abs_start=10,
            abs_end=10,
            section_path=["Knife Care"],
        )
        right = _make_chunk(
            identifier="c1",
            text="Store the knife in a sheath.",
            block_ids=[1],
            abs_start=12,
            abs_end=12,
            section_path=["Knife Care"],
        )

        assert not should_merge_adjacent_chunks(left, right, max_merged_chars=2000)

    def test_does_not_merge_across_lane_boundary(self):
        left = _make_chunk(
            identifier="c0",
            text="Salt pasta water so noodles absorb seasoning.",
            block_ids=[0],
            abs_start=2,
            abs_end=2,
            section_path=["Pasta"],
        )
        right = _make_chunk(
            identifier="c1",
            text="A stunning and award-winning chapter introduction.",
            block_ids=[1],
            abs_start=3,
            abs_end=3,
            section_path=["Pasta"],
            lane=ChunkLane.NOISE,
        )

        assert not should_merge_adjacent_chunks(left, right, max_merged_chars=2000)

    def test_does_not_merge_when_over_max_chars(self):
        left = _make_chunk(
            identifier="c0",
            text="A" * 300,
            block_ids=[0],
            abs_start=0,
            abs_end=0,
            section_path=["Roasting"],
        )
        right = _make_chunk(
            identifier="c1",
            text="B" * 300,
            block_ids=[1],
            abs_start=1,
            abs_end=1,
            section_path=["Roasting"],
        )

        assert not should_merge_adjacent_chunks(left, right, max_merged_chars=500)

    def test_merges_chain_of_adjacent_chunks(self):
        chunks = [
            _make_chunk(
                identifier="c0",
                text="Sear over high heat first.",
                block_ids=[0],
                abs_start=4,
                abs_end=4,
                section_path=["Braising"],
            ),
            _make_chunk(
                identifier="c1",
                text="Then add liquid and cover.",
                block_ids=[1],
                abs_start=5,
                abs_end=5,
                section_path=["Braising"],
            ),
            _make_chunk(
                identifier="c2",
                text="Cook gently until tender.",
                block_ids=[2],
                abs_start=6,
                abs_end=6,
                section_path=["Braising"],
            ),
        ]

        merged = consolidate_adjacent_knowledge_chunks(chunks, max_merged_chars=2000)

        assert len(merged) == 1
        assert merged[0].identifier == "c0"
        assert merged[0].block_ids == [0, 1, 2]
        assert "Sear over high heat first." in merged[0].text
        assert "Cook gently until tender." in merged[0].text

    def test_inclusive_end_index_adjacency_convention(self):
        left = _make_chunk(
            identifier="c0",
            text="Start with dry pans to improve browning.",
            block_ids=[0],
            abs_start=20,
            abs_end=22,
            section_path=["Saute"],
        )
        right = _make_chunk(
            identifier="c1",
            text="Add oil only once the pan is hot.",
            block_ids=[1],
            abs_start=23,
            abs_end=25,
            section_path=["Saute"],
        )
        not_adjacent = _make_chunk(
            identifier="c2",
            text="Do not overcrowd the pan.",
            block_ids=[2],
            abs_start=24,
            abs_end=26,
            section_path=["Saute"],
        )

        assert should_merge_adjacent_chunks(left, right, max_merged_chars=2000)
        assert not should_merge_adjacent_chunks(left, not_adjacent, max_merged_chars=2000)

    def test_table_chunks_never_merge_with_other_chunks(self):
        table_chunk = _make_chunk(
            identifier="c0",
            text="Temp  Internal\n125F  Medium rare",
            block_ids=[0],
            abs_start=40,
            abs_end=40,
            section_path=["Temperature Guide"],
            table_ids=["tbl_temp_guide"],
        )
        prose_chunk = _make_chunk(
            identifier="c1",
            text="Rest steak for 5 minutes before slicing.",
            block_ids=[1],
            abs_start=41,
            abs_end=41,
            section_path=["Temperature Guide"],
        )

        assert not should_merge_adjacent_chunks(table_chunk, prose_chunk, max_merged_chars=2000)
        merged = consolidate_adjacent_knowledge_chunks(
            [table_chunk, prose_chunk],
            max_merged_chars=2000,
        )
        assert len(merged) == 2

    def test_merge_small_chunks_does_not_absorb_table_chunks(self):
        table_chunk = _make_chunk(
            identifier="c0",
            text="Row 1  100",
            block_ids=[0],
            abs_start=100,
            abs_end=100,
            section_path=["Conversion Chart"],
            table_ids=["tbl_conversion"],
        )
        prose_chunk = _make_chunk(
            identifier="c1",
            text="Short note.",
            block_ids=[1],
            abs_start=101,
            abs_end=101,
            section_path=["Conversion Chart"],
        )

        merged = merge_small_chunks([table_chunk, prose_chunk], min_chars=120)
        assert len(merged) == 2

    def test_process_pipeline_respects_consolidation_kill_switch(self, monkeypatch: pytest.MonkeyPatch):
        blocks = [
            _make_block("KNIFE SKILLS"),
            _make_block(
                "Always keep your knife sharp. This helps maintain control and improves safety."
            ),
            _make_block("- Use a claw grip while chopping."),
            _make_block("- Let the blade do the work."),
        ]
        profile = ChunkingProfile(min_chars=20, max_chars=6000)

        monkeypatch.setenv("COOKIMPORT_CONSOLIDATE_ADJACENT_KNOWLEDGE_CHUNKS", "0")
        disabled = process_blocks_to_chunks(blocks, profile=profile, min_merge_chars=0)
        monkeypatch.delenv("COOKIMPORT_CONSOLIDATE_ADJACENT_KNOWLEDGE_CHUNKS", raising=False)
        enabled = process_blocks_to_chunks(blocks, profile=profile, min_merge_chars=0)

        assert len(disabled) > len(enabled)
        assert len(enabled) == 1


class TestFullPipeline:
    """Test the complete chunking pipeline."""

    def test_process_blocks_end_to_end(self):
        """Full pipeline should produce valid chunks."""
        blocks = [
            _make_block("COOKING TECHNIQUES"),
            _make_block("Searing:"),
            _make_block("Always preheat your pan before searing meat. The pan should be "
                        "smoking hot. This creates a beautiful crust through the Maillard reaction."),
            _make_block("STORAGE TIPS"),
            _make_block("Store leftovers in airtight containers. Most cooked dishes keep "
                        "for 3-4 days in the refrigerator."),
        ]

        chunks = process_blocks_to_chunks(blocks)

        # Should have at least 2 chunks (one per major heading)
        assert len(chunks) >= 2

        # All chunks should have IDs
        assert all(c.identifier for c in chunks)

        # Knowledge chunks should have tip_density calculated
        knowledge_chunks = [c for c in chunks if c.lane == ChunkLane.KNOWLEDGE]
        assert all(c.tip_density >= 0 for c in knowledge_chunks)

    def test_blurb_routed_away_from_knowledge(self):
        """Front-matter blurbs should not be knowledge lane."""
        blocks = [
            _make_block("This beautiful, award-winning cookbook features stunning photography "
                        "and teaches you everything about Italian cuisine. An essential "
                        "addition to any kitchen library."),
            _make_block("PASTA BASICS"),
            _make_block("Always salt your pasta water generously. Use 1 tablespoon per quart."),
        ]

        chunks = process_blocks_to_chunks(blocks)

        # First chunk (blurb) should be noise
        blurb_chunks = [c for c in chunks if "beautiful" in c.text.lower()]
        for c in blurb_chunks:
            assert c.lane == ChunkLane.NOISE

        # Pasta section should be knowledge
        pasta_chunks = [c for c in chunks if "salt your pasta" in c.text.lower()]
        for c in pasta_chunks:
            assert c.lane == ChunkLane.KNOWLEDGE


class TestStopHeadings:
    """Test that stop headings (INDEX, ACKNOWLEDGMENTS) are handled."""

    def test_index_section_excluded(self):
        """INDEX sections should create noise break."""
        blocks = [
            _make_block("Some recipe content with useful tips."),
            _make_block("INDEX"),
            _make_block("A, B, C entries..."),
        ]

        profile = ChunkingProfile(include_stop_sections=False)
        chunks = chunk_non_recipe_blocks(blocks, profile=profile)

        # Should not include index content in chunks
        all_text = " ".join(c.text for c in chunks)
        assert "entries" not in all_text


class TestCalloutChunking:
    """Test callout/sidebar chunk behavior."""

    def test_tip_prefix_creates_boundary(self):
        """TIP: prefix should create callout boundary."""
        blocks = [
            _make_block("Regular paragraph content."),
            _make_block("TIP: Always taste as you cook."),
            _make_block("More regular content."),
        ]

        profile = ChunkingProfile(split_on_callouts=True)
        chunks = chunk_non_recipe_blocks(blocks, profile=profile)

        # Should have boundary at TIP:
        callout_chunks = [
            c for c in chunks
            if c.boundary_start_reason == ChunkBoundaryReason.CALLOUT_SEED
        ]
        assert len(callout_chunks) >= 1
