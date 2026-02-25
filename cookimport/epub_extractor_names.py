from __future__ import annotations

from typing import Final

EPUB_EXTRACTOR_DEFAULT: Final[str] = "unstructured"
EPUB_EXTRACTOR_CANONICAL_CHOICES: Final[tuple[str, ...]] = (
    "unstructured",
    "beautifulsoup",
    "markdown",
    "markitdown",
)
EPUB_EXTRACTOR_ACCEPTED_CHOICES: Final[tuple[str, ...]] = EPUB_EXTRACTOR_CANONICAL_CHOICES
EPUB_EXTRACTOR_CANONICAL_SET: Final[frozenset[str]] = frozenset(
    EPUB_EXTRACTOR_CANONICAL_CHOICES
)
EPUB_EXTRACTOR_ACCEPTED_SET: Final[frozenset[str]] = frozenset(
    EPUB_EXTRACTOR_ACCEPTED_CHOICES
)


def normalize_epub_extractor_name(value: str) -> str:
    return str(value).strip().lower()


def is_supported_epub_extractor_name(value: str) -> bool:
    normalized = normalize_epub_extractor_name(value)
    return normalized in EPUB_EXTRACTOR_CANONICAL_SET


def epub_extractor_choices_for_help() -> str:
    return "unstructured, beautifulsoup, markdown, markitdown"
