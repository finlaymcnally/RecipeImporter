from __future__ import annotations

from cookimport.core.blocks import Block
from cookimport.parsing.block_roles import assign_block_roles
from cookimport.parsing.extraction_quality import score_blocks


def test_score_blocks_rewards_structured_content() -> None:
    blocks = [
        Block(text="Pancakes", font_weight="bold"),
        Block(text="Ingredients"),
        Block(text="1 cup flour"),
        Block(text="2 eggs"),
        Block(text="Instructions"),
        Block(text="Mix and cook."),
    ]
    blocks[0].add_feature("is_heading", True)
    blocks[0].add_feature("heading_level", 1)
    blocks[2].add_feature("is_list_item", True)
    blocks[3].add_feature("is_list_item", True)
    assign_block_roles(blocks)

    scored = score_blocks(blocks)

    assert scored.score > 0.4
    assert scored.stats["heading_blocks"] == 1
    assert scored.stats["list_item_blocks"] == 2


def test_score_blocks_penalizes_empty_content() -> None:
    scored = score_blocks([])

    assert scored.score == 0.0
    assert "no_blocks" in scored.reasons
