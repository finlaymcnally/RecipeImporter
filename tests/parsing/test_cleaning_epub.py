from __future__ import annotations

from cookimport.parsing.cleaning import normalize_epub_text


def test_normalize_epub_text_removes_soft_hyphen_and_zero_width_chars() -> None:
    raw = "but\u00adter\u200b and\u00a0milk"
    assert normalize_epub_text(raw) == "butter and milk"


def test_normalize_epub_text_normalizes_fractions_and_punctuation() -> None:
    raw = "“Use ½ cup” — it’s fine."
    assert normalize_epub_text(raw) == '"Use 1/2 cup" - it\'s fine.'
