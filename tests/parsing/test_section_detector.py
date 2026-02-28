from __future__ import annotations

from cookimport.core.blocks import Block
from cookimport.parsing import signals
from cookimport.parsing.section_detector import (
    SectionKind,
    detect_sections_from_blocks,
    detect_sections_from_lines,
    extract_structured_sections_from_lines,
)


def test_detect_sections_from_lines_preserves_component_header_context() -> None:
    lines = [
        "For the sauce:",
        "Mix, stir, and bake:",
        "Cook until thick.",
    ]
    detected = detect_sections_from_lines(
        lines,
        preferred_kind=SectionKind.INSTRUCTIONS,
    )

    spans = [span for span in detected.spans if span.end_index > span.start_index]
    assert len(spans) == 1
    assert spans[0].kind == SectionKind.INSTRUCTIONS
    assert spans[0].key == "sauce"
    assert spans[0].header_index == 0
    assert spans[0].start_index == 1
    assert spans[0].end_index == 3


def test_extract_structured_sections_from_lines_keeps_for_the_component_headers() -> None:
    lines = [
        "Ingredients",
        "For the sauce:",
        "2 tbsp butter",
        "Instructions",
        "For the sauce:",
        "Melt the butter.",
    ]
    sections, found = extract_structured_sections_from_lines(lines)

    assert found is True
    assert sections["ingredients"] == ["For the sauce", "2 tbsp butter"]
    assert sections["instructions"] == ["For the sauce", "Melt the butter."]
    assert sections["notes"] == []


def test_detect_sections_from_blocks_recognizes_for_the_component_groups() -> None:
    blocks = [
        Block(text="For the Frangipane"),
        Block(text="3/4 cup almonds"),
        Block(text="3 tbsp sugar"),
        Block(text="For the Tart"),
        Block(text="1 recipe tart dough"),
    ]
    for block in blocks:
        signals.enrich_block(block)

    detected = detect_sections_from_blocks(
        blocks,
        preferred_kind=SectionKind.INGREDIENTS,
    )
    keyed_spans = [span for span in detected.spans if span.end_index > span.start_index]
    assert len(keyed_spans) == 2
    assert keyed_spans[0].kind == SectionKind.INGREDIENTS
    assert keyed_spans[0].key == "frangipane"
    assert keyed_spans[1].kind == SectionKind.INGREDIENTS
    assert keyed_spans[1].key == "tart"


def test_detect_sections_from_lines_ignores_instructional_for_phrase() -> None:
    lines = ["For best results, use fresh ingredients."]
    detected = detect_sections_from_lines(
        lines,
        preferred_kind=SectionKind.INSTRUCTIONS,
    )

    assert detected.spans
    assert all(span.header_index is None for span in detected.spans)
