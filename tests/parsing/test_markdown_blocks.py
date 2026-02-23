from __future__ import annotations

from pathlib import Path

from cookimport.parsing.markdown_blocks import markdown_to_blocks


def test_markdown_to_blocks_parses_headings_and_lists_with_line_provenance() -> None:
    markdown = (
        "# Pancakes\n"
        "\n"
        "## Ingredients\n"
        "- 1 cup flour\n"
        "- 1 cup milk\n"
        "- 1 egg\n"
        "\n"
        "## Instructions\n"
        "1. Mix ingredients\n"
        "2. Cook on skillet\n"
    )

    blocks = markdown_to_blocks(
        markdown,
        source_path=Path("book.epub"),
        extraction_backend="markitdown",
    )

    assert [block.text for block in blocks] == [
        "Pancakes",
        "Ingredients",
        "1 cup flour",
        "1 cup milk",
        "1 egg",
        "Instructions",
        "Mix ingredients",
        "Cook on skillet",
    ]
    assert blocks[0].features["is_heading"] is True
    assert blocks[0].features["heading_level"] == 1
    assert blocks[0].features["md_line_start"] == 1
    assert blocks[0].features["md_line_end"] == 1

    assert blocks[2].features["is_list_item"] is True
    assert blocks[2].features["md_line_start"] == 4
    assert blocks[2].features["md_line_end"] == 4

    assert blocks[6].features["is_list_item"] is True
    assert blocks[6].features["md_line_start"] == 9
    assert blocks[6].features["md_line_end"] == 9

    for block in blocks:
        assert block.features["extraction_backend"] == "markitdown"
        assert block.features["source_location_id"] == "book"


def test_markdown_to_blocks_merges_paragraph_lines_until_blank() -> None:
    markdown = (
        "Intro line one\n"
        "continues line two\n"
        "\n"
        "Next paragraph\n"
    )

    blocks = markdown_to_blocks(
        markdown,
        source_path=Path("sample.epub"),
        extraction_backend="markitdown",
    )

    assert len(blocks) == 2
    assert blocks[0].text == "Intro line one continues line two"
    assert blocks[0].features["md_line_start"] == 1
    assert blocks[0].features["md_line_end"] == 2
    assert blocks[1].text == "Next paragraph"
    assert blocks[1].features["md_line_start"] == 4
    assert blocks[1].features["md_line_end"] == 4
