from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable

from cookimport.parsing.sections import is_instruction_section_header_line

DEFAULT_INSTRUCTION_STEP_SEGMENTATION_POLICY = "auto"
DEFAULT_INSTRUCTION_STEP_SEGMENTER = "heuristic_v1"

_ALLOWED_POLICIES = {
    "off",
    "auto",
    "always",
}
_ALLOWED_SEGMENTERS = {
    "heuristic_v1",
    "pysbd_v1",
}

_WHITESPACE_RE = re.compile(r"[ \t]+")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_INLINE_NUMBERED_STEP_RE = re.compile(
    r"(?<!\w)(?:step\s*)?\d{1,2}[.)](?=\s)",
    re.IGNORECASE,
)
_INLINE_BULLET_RE = re.compile(r"\s+[•●▪◦]\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


def normalize_instruction_step_segmentation_policy(value: str | None) -> str:
    normalized = str(value or DEFAULT_INSTRUCTION_STEP_SEGMENTATION_POLICY).strip().lower()
    normalized = normalized.replace("-", "_")
    if normalized in _ALLOWED_POLICIES:
        return normalized
    raise ValueError(
        "Invalid instruction step segmentation policy: "
        f"{value!r}. Expected one of: off, auto, always."
    )


def normalize_instruction_step_segmenter(value: str | None) -> str:
    normalized = str(value or DEFAULT_INSTRUCTION_STEP_SEGMENTER).strip().lower()
    normalized = normalized.replace("-", "_")
    if normalized in _ALLOWED_SEGMENTERS:
        return normalized
    raise ValueError(
        "Invalid instruction step segmenter: "
        f"{value!r}. Expected one of: heuristic_v1, pysbd_v1."
    )


def should_fallback_segment(instructions: list[str]) -> bool:
    normalized = _normalize_instructions(instructions)
    if not normalized:
        return False

    non_header_lines = [
        line for line in normalized if not is_instruction_section_header_line(line)
    ]
    if not non_header_lines:
        return False

    if any(_has_inline_markers(line) for line in non_header_lines):
        return True

    if len(non_header_lines) == 1:
        line = non_header_lines[0]
        if _estimated_sentence_count(line) >= 3 and _word_count(line) >= 16:
            return True

    long_lines = [
        line
        for line in non_header_lines
        if len(line) >= 200 or _word_count(line) >= 35
    ]
    if not long_lines:
        return False

    sentence_breaks = sum(_estimated_sentence_count(line) - 1 for line in long_lines)
    if sentence_breaks >= 2 and len(non_header_lines) <= 2:
        return True

    if (
        len(non_header_lines) == 1
        and (_word_count(non_header_lines[0]) >= 28 or len(non_header_lines[0]) >= 140)
        and _estimated_sentence_count(non_header_lines[0]) >= 3
    ):
        return True

    total_words = sum(_word_count(line) for line in non_header_lines)
    return len(non_header_lines) <= 3 and total_words >= 70


def segment_instruction_steps(
    instructions: list[str],
    *,
    policy: str = DEFAULT_INSTRUCTION_STEP_SEGMENTATION_POLICY,
    backend: str = DEFAULT_INSTRUCTION_STEP_SEGMENTER,
) -> list[str]:
    normalized = _normalize_instructions(instructions)
    if not normalized:
        return []

    selected_policy = normalize_instruction_step_segmentation_policy(policy)
    selected_backend = normalize_instruction_step_segmenter(backend)

    if selected_policy == "off":
        return normalized
    if selected_policy == "auto" and not should_fallback_segment(normalized):
        return normalized

    segmented = _segment_with_backend(normalized, backend=selected_backend)
    if not segmented:
        return normalized
    if len(segmented) > 80:
        return normalized
    return segmented


def _normalize_instructions(instructions: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for line in instructions:
        cleaned = _normalize_text(str(line))
        if cleaned:
            normalized.append(cleaned)
    return normalized


def _normalize_text(text: str) -> str:
    cleaned = text.replace("\u00a0", " ")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _has_inline_markers(text: str) -> bool:
    if len(_INLINE_NUMBERED_STEP_RE.findall(text)) >= 2:
        return True
    return len(_INLINE_BULLET_RE.findall(text)) >= 2


def _estimated_sentence_count(text: str) -> int:
    heuristic_split = _SENTENCE_SPLIT_RE.split(text)
    if len(heuristic_split) <= 1 and ";" in text:
        heuristic_split = [part for part in text.split(";") if part.strip()]
    return max(1, len([part for part in heuristic_split if part.strip()]))


def _segment_with_backend(instructions: list[str], *, backend: str) -> list[str]:
    segments: list[str] = []
    for instruction in instructions:
        segments.extend(_split_line_with_markers(instruction))

    split_sentences: list[str] = []
    for segment in segments:
        if is_instruction_section_header_line(segment):
            split_sentences.append(segment)
            continue
        sentence_parts = _split_sentences(segment, backend=backend)
        if sentence_parts:
            split_sentences.extend(sentence_parts)
        else:
            split_sentences.append(segment)

    merged = _merge_tiny_fragments(split_sentences)
    return _normalize_instructions(merged)


def _split_line_with_markers(text: str) -> list[str]:
    parts: list[str] = []
    for line in text.splitlines():
        cleaned = _normalize_text(line)
        if not cleaned:
            continue
        if is_instruction_section_header_line(cleaned):
            parts.append(cleaned)
            continue
        numbered = _split_inline_numbered_steps(cleaned)
        for item in numbered:
            if is_instruction_section_header_line(item):
                parts.append(item)
                continue
            bullet_split = _split_inline_bullets(item)
            if bullet_split:
                parts.extend(bullet_split)
            else:
                parts.append(item)
    return parts


def _split_inline_numbered_steps(text: str) -> list[str]:
    matches = list(_INLINE_NUMBERED_STEP_RE.finditer(text))
    if len(matches) < 2:
        return [text]

    chunks: list[str] = []
    prefix = text[: matches[0].start()].strip(" ,;:-")
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = text[start:end].strip(" ,;")
        if chunk:
            chunks.append(chunk)

    if prefix:
        if chunks:
            separator = " " if prefix.endswith((".", "!", "?", ":", ";")) else ". "
            chunks[0] = f"{prefix}{separator}{chunks[0]}".strip()
        else:
            chunks.append(prefix)
    return chunks or [text]


def _split_inline_bullets(text: str) -> list[str]:
    if len(_INLINE_BULLET_RE.findall(text)) < 2:
        return []
    chunks = [part.strip(" ,;") for part in _INLINE_BULLET_RE.split(text)]
    return [chunk for chunk in chunks if chunk]


def _split_sentences(text: str, *, backend: str) -> list[str]:
    if backend == "pysbd_v1":
        return _split_sentences_pysbd(text)
    return _split_sentences_heuristic(text)


def _split_sentences_heuristic(text: str) -> list[str]:
    if re.match(r"^\d{1,2}[.)]\s+", text):
        return [text]

    sentence_delimiter_count = len(re.findall(r"[.!?]", text))
    if sentence_delimiter_count <= 1 and len(text) < 70 and _word_count(text) < 14:
        return [text]

    parts = [part.strip(" ,;") for part in _SENTENCE_SPLIT_RE.split(text)]
    parts = [part for part in parts if part]
    if len(parts) > 1:
        return parts

    if ";" in text and len(text) >= 120:
        semicolon_parts = [part.strip(" ,;") for part in text.split(";")]
        semicolon_parts = [part for part in semicolon_parts if part]
        if len(semicolon_parts) > 1:
            return semicolon_parts

    return [text]


@lru_cache(maxsize=1)
def _build_pysbd_segmenter() -> object:
    try:
        import pysbd
    except ImportError as exc:  # pragma: no cover - exercised through call path.
        raise ValueError(
            "instruction_step_segmenter=pysbd_v1 requires optional dependency `pysbd`. "
            "Install with `pip install pysbd` or use heuristic_v1."
        ) from exc

    return pysbd.Segmenter(language="en", clean=False)


def _split_sentences_pysbd(text: str) -> list[str]:
    segmenter = _build_pysbd_segmenter()
    try:
        raw_parts = segmenter.segment(text)
    except Exception as exc:  # pragma: no cover - defensive path.
        raise ValueError(
            "Failed to segment instructions with instruction_step_segmenter=pysbd_v1: "
            f"{exc}"
        ) from exc
    parts = [_normalize_text(str(part)) for part in raw_parts]
    return [part for part in parts if part]


def _merge_tiny_fragments(fragments: list[str]) -> list[str]:
    merged: list[str] = []
    pending_prefix: str | None = None

    for fragment in fragments:
        text = _normalize_text(fragment)
        if not text:
            continue
        if is_instruction_section_header_line(text):
            if pending_prefix:
                if merged and not is_instruction_section_header_line(merged[-1]):
                    merged[-1] = _normalize_text(f"{merged[-1]} {pending_prefix}")
                else:
                    merged.append(pending_prefix)
                pending_prefix = None
            merged.append(text)
            continue

        if _is_tiny_fragment(text):
            if merged and not is_instruction_section_header_line(merged[-1]):
                merged[-1] = _normalize_text(f"{merged[-1]} {text}")
            elif pending_prefix:
                pending_prefix = _normalize_text(f"{pending_prefix} {text}")
            else:
                pending_prefix = text
            continue

        if pending_prefix:
            text = _normalize_text(f"{pending_prefix} {text}")
            pending_prefix = None
        merged.append(text)

    if pending_prefix:
        if merged and not is_instruction_section_header_line(merged[-1]):
            merged[-1] = _normalize_text(f"{merged[-1]} {pending_prefix}")
        else:
            merged.append(pending_prefix)
    return merged


def _is_tiny_fragment(text: str) -> bool:
    return _word_count(text) <= 2 or len(text) <= 14


__all__ = [
    "DEFAULT_INSTRUCTION_STEP_SEGMENTATION_POLICY",
    "DEFAULT_INSTRUCTION_STEP_SEGMENTER",
    "normalize_instruction_step_segmentation_policy",
    "normalize_instruction_step_segmenter",
    "segment_instruction_steps",
    "should_fallback_segment",
]
