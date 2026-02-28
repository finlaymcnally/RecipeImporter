from __future__ import annotations

import os
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
EPUB_EXTRACTOR_MARKDOWN_POLICY_LOCKED_CHOICES: Final[tuple[str, ...]] = (
    "markdown",
    "markitdown",
)
EPUB_EXTRACTOR_MARKDOWN_POLICY_LOCKED_SET: Final[frozenset[str]] = frozenset(
    EPUB_EXTRACTOR_MARKDOWN_POLICY_LOCKED_CHOICES
)
EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV: Final[str] = (
    "COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS"
)
_TRUTHY_ENV_VALUES: Final[frozenset[str]] = frozenset(
    {"1", "true", "yes", "on"}
)


def normalize_epub_extractor_name(value: str) -> str:
    return str(value).strip().lower()


def markdown_epub_extractors_enabled() -> bool:
    raw_value = os.environ.get(EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV, "")
    return raw_value.strip().lower() in _TRUTHY_ENV_VALUES


def is_policy_locked_epub_extractor_name(value: str) -> bool:
    normalized = normalize_epub_extractor_name(value)
    return (
        normalized in EPUB_EXTRACTOR_MARKDOWN_POLICY_LOCKED_SET
        and not markdown_epub_extractors_enabled()
    )


def epub_extractor_enabled_choices() -> tuple[str, ...]:
    if markdown_epub_extractors_enabled():
        return EPUB_EXTRACTOR_CANONICAL_CHOICES
    return tuple(
        choice
        for choice in EPUB_EXTRACTOR_CANONICAL_CHOICES
        if choice not in EPUB_EXTRACTOR_MARKDOWN_POLICY_LOCKED_SET
    )


def is_supported_epub_extractor_name(value: str) -> bool:
    normalized = normalize_epub_extractor_name(value)
    return normalized in EPUB_EXTRACTOR_CANONICAL_SET


def epub_extractor_choices_for_help() -> str:
    return ", ".join(epub_extractor_enabled_choices())
