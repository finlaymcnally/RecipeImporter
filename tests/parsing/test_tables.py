from __future__ import annotations

from cookimport.parsing.tables import (
    annotate_non_recipe_blocks_with_tables,
    detect_tables_from_non_recipe_blocks,
)


def test_detect_markdown_table_and_annotate_blocks() -> None:
    non_recipe_blocks = [
        {"index": 7, "text": "Doneness Temperatures", "features": {"is_header_likely": True}},
        {"index": 8, "text": "| Protein | Temp |"},
        {"index": 9, "text": "| --- | --- |"},
        {"index": 10, "text": "| Chicken | 165F |"},
        {"index": 11, "text": "| Pork | 145F |"},
    ]

    tables = detect_tables_from_non_recipe_blocks(non_recipe_blocks, source_hash="abc123")
    assert len(tables) == 1

    table = tables[0]
    assert table.caption == "Doneness Temperatures"
    assert table.headers == ["Protein", "Temp"]
    assert table.rows == [["Chicken", "165F"], ["Pork", "145F"]]
    assert table.start_block_index == 8
    assert table.end_block_index == 11
    assert table.row_texts == ["Protein: Chicken | Temp: 165F", "Protein: Pork | Temp: 145F"]

    mutable_blocks = [dict(block) for block in non_recipe_blocks]
    annotate_non_recipe_blocks_with_tables(mutable_blocks, tables)

    for block in mutable_blocks:
        if block.get("index") in {10, 11}:
            assert block.get("table_id") == table.table_id
            assert isinstance(block.get("table_hint"), dict)
            assert block["table_hint"]["table_id"] == table.table_id


def test_detect_multispace_table() -> None:
    non_recipe_blocks = [
        {"index": 20, "text": "Unit  Grams"},
        {"index": 21, "text": "Cup  240"},
        {"index": 22, "text": "Tablespoon  15"},
    ]

    tables = detect_tables_from_non_recipe_blocks(non_recipe_blocks, source_hash="abc123")
    assert len(tables) == 1
    assert tables[0].rows == [["Cup", "240"], ["Tablespoon", "15"]]


def test_false_positive_guard_for_narrative_text() -> None:
    non_recipe_blocks = [
        {"index": 30, "text": "This section explains why salt matters."},
        {"index": 31, "text": "Use kosher salt for even seasoning."},
        {"index": 32, "text": "Taste and adjust toward the end."},
    ]

    tables = detect_tables_from_non_recipe_blocks(non_recipe_blocks, source_hash="abc123")
    assert tables == []
