from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from cookimport.parsing.epub_html_normalize import normalize_epub_html_for_unstructured
from tests.paths import FIXTURES_DIR as TESTS_FIXTURES_DIR


FIXTURES_DIR = TESTS_FIXTURES_DIR / "epub_html"


def _fixture_text(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def test_br_split_mode_splits_single_paragraph_into_multiple_blocks() -> None:
    html = _fixture_text("br_ingredients.xhtml")

    normalized = normalize_epub_html_for_unstructured(html, mode="br_split_v1")
    soup = BeautifulSoup(normalized, "lxml")
    ingredient_paragraphs = soup.select("p.ingredients")

    assert [p.get_text(strip=True) for p in ingredient_paragraphs] == [
        "1 cup flour",
        "2 eggs",
        "1 tbsp sugar",
    ]
    assert ingredient_paragraphs[0].get("id") == "ingredient-lines"
    assert ingredient_paragraphs[1].get("id") is None
    assert ingredient_paragraphs[2].get("id") is None


def test_none_mode_returns_input_html_unchanged() -> None:
    html = _fixture_text("br_ingredients.xhtml")
    normalized = normalize_epub_html_for_unstructured(html, mode="none")
    assert normalized == html


def test_br_split_mode_is_idempotent() -> None:
    html = _fixture_text("br_instructions.xhtml")

    normalized_once = normalize_epub_html_for_unstructured(html, mode="br_split_v1")
    normalized_twice = normalize_epub_html_for_unstructured(
        normalized_once,
        mode="br_split_v1",
    )

    soup_once = BeautifulSoup(normalized_once, "lxml")
    soup_twice = BeautifulSoup(normalized_twice, "lxml")
    assert [p.get_text(strip=True) for p in soup_once.select("p.steps")] == [
        p.get_text(strip=True) for p in soup_twice.select("p.steps")
    ]
    assert not soup_twice.find("br")


def test_semantic_v1_aliases_br_split_v1() -> None:
    html = _fixture_text("faux_heading.xhtml")

    br_split = normalize_epub_html_for_unstructured(html, mode="br_split_v1")
    semantic = normalize_epub_html_for_unstructured(html, mode="semantic_v1")

    assert BeautifulSoup(br_split, "lxml").get_text() == BeautifulSoup(semantic, "lxml").get_text()


def test_invalid_mode_raises_value_error() -> None:
    with pytest.raises(ValueError):
        normalize_epub_html_for_unstructured("<p>hello</p>", mode="invalid-mode")
