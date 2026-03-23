"""Knowledge chunking module.

Implements structure-first chunking for non-recipe content blocks.
Chunks are formed based on headings and section boundaries rather than
punctuation or sentence boundaries.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from cookimport.core.blocks import Block, BlockType
from cookimport.core.models import (
    ChunkBoundaryReason,
    ChunkHighlight,
    ChunkLane,
    KnowledgeChunk,
    ParsingOverrides,
    TipTags,
)
from cookimport.parsing import signals
from cookimport.parsing import tips as tip_miner

# Heading detection patterns
_ALL_CAPS_RE = re.compile(r"^[A-Z][A-Z0-9\s\-—–&,:']+$")
_COLON_HEADER_RE = re.compile(r"^[A-Z][^.!?\n]{0,60}:\s*$")
_SHORT_TITLE_RE = re.compile(r"^[A-Z][A-Za-z0-9\s\-—–&,']{0,50}$")

# Callout prefixes that indicate sidebar/tip content
_CALLOUT_PREFIXES = frozenset({
    "tip", "tips", "note", "notes", "hint", "hints", "pro tip",
    "variation", "variations", "make ahead", "make-ahead",
    "storage", "leftovers", "substitution", "substitutions",
    "troubleshooting", "warning", "caution",
})

# Stop headings that typically indicate noise sections
_DEFAULT_STOP_HEADINGS = frozenset({
    "index", "acknowledgments", "acknowledgements", "about the author",
    "about the authors", "credits", "copyright", "bibliography",
    "sources", "resources", "metric conversions", "conversion chart",
    "glossary", "appendix",
})

# Format mode indicators
_BULLET_RE = re.compile(r"^\s*[-*•]\s+")
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+")
_TOPIC_TOKEN_RE = re.compile(r"[^a-z0-9]+")

_CONSOLIDATE_ADJACENT_KNOWLEDGE_CHUNKS_ENV = (
    "COOKIMPORT_CONSOLIDATE_ADJACENT_KNOWLEDGE_CHUNKS"
)

_TAG_FIELD_NAMES = (
    "recipes",
    "dishes",
    "meats",
    "vegetables",
    "herbs",
    "spices",
    "dairy",
    "grains",
    "legumes",
    "fruits",
    "sweeteners",
    "oils_fats",
    "techniques",
    "cooking_methods",
    "tools",
    "other",
)


@dataclass
class ChunkingProfile:
    """Configuration for chunk boundaries and behavior."""

    min_chars: int = 200
    max_chars: int = 6000
    major_heading_levels: tuple[int, ...] = (1, 2)
    minor_heading_levels: tuple[int, ...] = (3, 4, 5, 6)
    stop_headings: frozenset[str] = _DEFAULT_STOP_HEADINGS
    callout_prefixes: frozenset[str] = _CALLOUT_PREFIXES
    split_on_callouts: bool = True
    include_stop_sections: bool = False


@dataclass
class _ChunkBuilder:
    """Internal state for building a chunk."""

    blocks: list[Block] = field(default_factory=list)
    block_ids: list[int] = field(default_factory=list)
    section_path: list[str] = field(default_factory=list)
    title: str | None = None
    start_reason: ChunkBoundaryReason = ChunkBoundaryReason.START_OF_INPUT
    end_reason: ChunkBoundaryReason = ChunkBoundaryReason.END_OF_INPUT
    is_callout: bool = False

    @property
    def text(self) -> str:
        return "\n\n".join(b.text.strip() for b in self.blocks if b.text.strip())

    @property
    def char_count(self) -> int:
        return sum(len(b.text) for b in self.blocks)

    def is_empty(self) -> bool:
        return not self.blocks or not self.text.strip()


def _table_id_for_block(block: Block) -> str | None:
    features = block.features if isinstance(block.features, dict) else {}
    table_id = features.get("table_id")
    if not isinstance(table_id, str):
        return None
    normalized = table_id.strip()
    return normalized or None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _source_block_index_for_block(block: Block, *, fallback_index: int) -> int:
    features = block.features if isinstance(block.features, dict) else {}
    source_index = _coerce_int(features.get("source_block_index"))
    if source_index is not None:
        return source_index
    return fallback_index


def chunk_non_recipe_blocks(
    blocks: Sequence[Block],
    *,
    profile: ChunkingProfile | None = None,
) -> list[KnowledgeChunk]:
    """Chunk a sequence of non-recipe blocks into coherent knowledge chunks.

    Uses heading structure as the primary boundary signal. Falls back to
    format-mode changes and max-size limits when headings are sparse.

    Args:
        blocks: Sequence of Block objects to chunk.
        profile: Configuration for chunking behavior. Uses defaults if None.

    Returns:
        List of KnowledgeChunk objects with provenance and boundary reasons.
    """
    if profile is None:
        profile = ChunkingProfile()

    if not blocks:
        return []

    chunks: list[KnowledgeChunk] = []
    section_stack: list[tuple[int, str]] = []  # (level, heading_text)
    current = _ChunkBuilder()
    chunk_index = 0
    in_stop_section = False  # Track if we're in a stop section (INDEX, etc.)

    def get_section_path() -> list[str]:
        return [heading for _, heading in section_stack]

    def flush_chunk(end_reason: ChunkBoundaryReason) -> None:
        nonlocal chunk_index, current
        if current.is_empty():
            current = _ChunkBuilder(
                section_path=get_section_path(),
                start_reason=ChunkBoundaryReason.START_OF_INPUT,
            )
            return

        # Aggregate block_role counts for lane scoring
        role_counts: dict[str, int] = {}
        table_ids: list[str] = []
        absolute_block_ids: list[int] = []
        for b in current.blocks:
            role = b.features.get("block_role", "other")
            role_counts[role] = role_counts.get(role, 0) + 1
            table_id = _table_id_for_block(b)
            if table_id and table_id not in table_ids:
                table_ids.append(table_id)
        for block_id, block in zip(current.block_ids, current.blocks):
            absolute_block_ids.append(
                _source_block_index_for_block(block, fallback_index=block_id)
            )

        chunk = KnowledgeChunk(
            identifier=f"c{chunk_index}",
            lane=ChunkLane.KNOWLEDGE,  # Lane assigned later
            title=current.title,
            section_path=current.section_path,
            text=current.text,
            block_ids=current.block_ids,
            boundary_start_reason=current.start_reason,
            boundary_end_reason=end_reason,
            provenance={
                "chunk_index": chunk_index,
                "block_range": [min(current.block_ids), max(current.block_ids)]
                if current.block_ids
                else [],
                "absolute_block_range": [min(absolute_block_ids), max(absolute_block_ids)]
                if absolute_block_ids
                else [],
                "block_role_counts": role_counts,
                "table_ids": table_ids,
            },
        )
        chunks.append(chunk)
        chunk_index += 1
        current = _ChunkBuilder(
            section_path=get_section_path(),
            start_reason=end_reason,
        )

    for i, block in enumerate(blocks):
        text = block.text.strip()
        if not text:
            continue

        table_id = _table_id_for_block(block)
        previous_table_id = _table_id_for_block(current.blocks[-1]) if current.blocks else None
        in_same_table_run = bool(table_id and previous_table_id and table_id == previous_table_id)

        heading_level = _detect_heading_level(block, profile)

        # Check for callout prefix
        callout_match = _is_callout_start(text, profile)

        # Check for stop heading (INDEX, ACKNOWLEDGMENTS, etc.)
        if not in_same_table_run and heading_level and _is_stop_heading(text, profile):
            if current.block_ids:
                flush_chunk(ChunkBoundaryReason.NOISE_BREAK)
            if not profile.include_stop_sections:
                in_stop_section = True
                continue

        # If we're in a stop section, skip until next major heading
        if in_stop_section:
            if heading_level and heading_level in profile.major_heading_levels:
                # Exit stop section on next major heading
                in_stop_section = False
            else:
                # Skip this block
                continue

        # Major heading creates a hard boundary
        if not in_same_table_run and heading_level and heading_level in profile.major_heading_levels:
            if current.block_ids:
                flush_chunk(ChunkBoundaryReason.HEADING)
            # Update section stack
            while section_stack and section_stack[-1][0] >= heading_level:
                section_stack.pop()
            section_stack.append((heading_level, text))
            current.section_path = get_section_path()
            current.title = text
            current.start_reason = ChunkBoundaryReason.HEADING

        # Minor heading: include in current chunk but may update title
        elif (
            not in_same_table_run
            and heading_level
            and heading_level in profile.minor_heading_levels
        ):
            while section_stack and section_stack[-1][0] >= heading_level:
                section_stack.pop()
            section_stack.append((heading_level, text))
            current.section_path = get_section_path()
            if not current.title:
                current.title = text

        # Callout prefix creates a boundary if configured
        elif not in_same_table_run and callout_match and profile.split_on_callouts:
            if current.block_ids:
                flush_chunk(ChunkBoundaryReason.CALLOUT_SEED)
            current.title = text if len(text) < 80 else None
            current.is_callout = True
            current.start_reason = ChunkBoundaryReason.CALLOUT_SEED

        # Check for format mode change (prose -> bullets, etc.)
        elif (
            not in_same_table_run
            and current.block_ids
            and _is_format_mode_change(current.blocks[-1], block)
        ):
            # Only split if we have reasonable content
            if current.char_count >= profile.min_chars:
                flush_chunk(ChunkBoundaryReason.FORMAT_MODE_CHANGE)

        # Check max size
        if (
            not in_same_table_run
            and current.char_count + len(text) > profile.max_chars
            and current.block_ids
        ):
            flush_chunk(ChunkBoundaryReason.MAX_CHARS)

        # Add block to current chunk
        current.blocks.append(block)
        current.block_ids.append(i)

    # Flush final chunk
    if current.block_ids:
        flush_chunk(ChunkBoundaryReason.END_OF_INPUT)

    return chunks


def _detect_heading_level(block: Block, profile: ChunkingProfile) -> int | None:
    """Detect if a block is a heading and return its level.

    Returns:
        Heading level (1-6) or None if not a heading.
    """
    text = block.text.strip()
    if not text:
        return None

    # Check block features first
    features = block.features or {}
    if features.get("is_header_likely"):
        # Default to level 2 for detected headers
        return 2

    # Check for explicit heading indicators
    if block.font_weight == "bold" and len(text) < 100:
        # Bold text under 100 chars is likely a heading
        return 2 if block.font_size and block.font_size > 12 else 3

    # ALL CAPS heading pattern
    if _ALL_CAPS_RE.match(text) and len(text) < 80:
        return 1 if len(text.split()) <= 4 else 2

    # Colon-terminated header pattern
    if _COLON_HEADER_RE.match(text):
        return 3

    # Short title-case text
    if _SHORT_TITLE_RE.match(text) and text.istitle() and len(text.split()) <= 6:
        return 3

    return None


def _is_callout_start(text: str, profile: ChunkingProfile) -> bool:
    """Check if text starts with a callout prefix like TIP: or NOTE:."""
    lower = text.lower().strip()
    for prefix in profile.callout_prefixes:
        if lower.startswith(prefix + ":") or lower.startswith(prefix + " -"):
            return True
        if lower == prefix or lower == prefix + ":":
            return True
    return False


def _is_stop_heading(text: str, profile: ChunkingProfile) -> bool:
    """Check if heading text indicates a stop section (INDEX, etc.)."""
    normalized = text.lower().strip().rstrip(":")
    return normalized in profile.stop_headings


def _is_format_mode_change(prev_block: Block, curr_block: Block) -> bool:
    """Check if there's a format mode change between blocks."""
    prev_text = prev_block.text.strip()
    curr_text = curr_block.text.strip()

    prev_is_bullet = bool(_BULLET_RE.match(prev_text))
    curr_is_bullet = bool(_BULLET_RE.match(curr_text))

    prev_is_numbered = bool(_NUMBERED_RE.match(prev_text))
    curr_is_numbered = bool(_NUMBERED_RE.match(curr_text))

    # Transition from prose to list or vice versa
    prev_is_list = prev_is_bullet or prev_is_numbered
    curr_is_list = curr_is_bullet or curr_is_numbered

    if prev_is_list != curr_is_list:
        return True

    # Transition between bullet and numbered
    if prev_is_bullet and curr_is_numbered:
        return True
    if prev_is_numbered and curr_is_bullet:
        return True

    return False


def merge_small_chunks(
    chunks: list[KnowledgeChunk],
    *,
    min_chars: int = 200,
) -> list[KnowledgeChunk]:
    """Merge chunks that are too small with their neighbors.

    Small chunks are merged with the following chunk if they share
    the same section path prefix.
    """
    if not chunks:
        return []

    result: list[KnowledgeChunk] = []
    pending: KnowledgeChunk | None = None

    for chunk in chunks:
        if pending is None:
            if _chunk_has_table_content(chunk):
                result.append(chunk)
            elif len(chunk.text) < min_chars:
                pending = chunk
            else:
                result.append(chunk)
        else:
            if _chunk_has_table_content(pending) or _chunk_has_table_content(chunk):
                result.append(pending)
                if _chunk_has_table_content(chunk):
                    result.append(chunk)
                    pending = None
                elif len(chunk.text) < min_chars:
                    pending = chunk
                else:
                    result.append(chunk)
                    pending = None
                continue

            # Check if we should merge
            shared_path = _shared_section_prefix(pending.section_path, chunk.section_path)
            if shared_path or len(pending.text) < min_chars // 2:
                # Merge pending into current
                merged_block_ids = pending.block_ids + chunk.block_ids
                merged = KnowledgeChunk(
                    identifier=pending.identifier,
                    lane=pending.lane,
                    title=pending.title or chunk.title,
                    section_path=pending.section_path or chunk.section_path,
                    text=pending.text + "\n\n" + chunk.text,
                    block_ids=merged_block_ids,
                    boundary_start_reason=pending.boundary_start_reason,
                    boundary_end_reason=chunk.boundary_end_reason,
                    provenance=_merge_chunk_provenance(
                        pending,
                        chunk,
                        merged_block_ids=merged_block_ids,
                    ),
                )
                if len(merged.text) < min_chars:
                    pending = merged
                else:
                    result.append(merged)
                    pending = None
            else:
                result.append(pending)
                if len(chunk.text) < min_chars:
                    pending = chunk
                else:
                    result.append(chunk)
                    pending = None

    if pending:
        result.append(pending)

    _renumber_chunk_ids(result)
    return result


def collapse_heading_bridge_chunks(
    chunks: list[KnowledgeChunk],
    *,
    max_bridge_chars: int = 120,
) -> list[KnowledgeChunk]:
    """Merge tiny heading/bridge chunks into adjacent neighbors.

    This reduces prompt fragmentation from standalone headings, short
    transitional fragments, and similar decorative chunk seams.
    """
    if not chunks:
        return []

    collapsed: list[KnowledgeChunk] = []
    pending = chunks[0]
    for chunk in chunks[1:]:
        if _should_merge_into_next_chunk(pending, chunk, max_bridge_chars=max_bridge_chars):
            pending = _merge_adjacent_chunk_pair(pending, chunk)
            continue
        collapsed.append(pending)
        pending = chunk
    collapsed.append(pending)
    _renumber_chunk_ids(collapsed)
    return collapsed


def _should_merge_into_next_chunk(
    left: KnowledgeChunk,
    right: KnowledgeChunk,
    *,
    max_bridge_chars: int,
) -> bool:
    if _chunk_has_table_content(left) or _chunk_has_table_content(right):
        return False
    left_range = chunk_abs_range(left)
    right_range = chunk_abs_range(right)
    if left_range is None or right_range is None:
        return False
    if left_range[1] + 1 != right_range[0]:
        return False
    if _looks_standalone_heading_chunk(left):
        return True
    if _looks_tiny_bridge_chunk(left, max_bridge_chars=max_bridge_chars):
        return True
    return False


def _looks_standalone_heading_chunk(chunk: KnowledgeChunk) -> bool:
    text = chunk.text.strip()
    if not text:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        return False
    line = lines[0]
    if len(line) > 80:
        return False
    if len(line.split()) > 8:
        return False
    if line.endswith((".", "!", "?")):
        return False
    return bool(_detect_heading_level(Block(text=line, type=BlockType.TEXT), ChunkingProfile()))


def _looks_tiny_bridge_chunk(chunk: KnowledgeChunk, *, max_bridge_chars: int) -> bool:
    text = chunk.text.strip()
    if not text or len(text) > max_bridge_chars:
        return False
    if len(chunk.block_ids) > 2:
        return False
    if _KNOWLEDGE_TEMP_TIME_RE.search(text):
        return False
    if _KNOWLEDGE_IMPERATIVE_RE.search(text) and len(text) > 80:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return len(lines) <= 2


def _shared_section_prefix(path1: list[str], path2: list[str]) -> list[str]:
    """Return the shared prefix of two section paths."""
    shared = []
    for a, b in zip(path1, path2):
        if a == b:
            shared.append(a)
        else:
            break
    return shared


def _chunk_has_table_content(chunk: KnowledgeChunk) -> bool:
    provenance = chunk.provenance if isinstance(chunk.provenance, dict) else {}
    table_ids = provenance.get("table_ids")
    if not isinstance(table_ids, list):
        return False
    return any(isinstance(table_id, str) and table_id.strip() for table_id in table_ids)


def _chunk_identifier_for_merge(chunk: KnowledgeChunk) -> str:
    if isinstance(chunk.identifier, str) and chunk.identifier.strip():
        return chunk.identifier
    return "unknown"


def _merged_identifier_lineage(left: KnowledgeChunk, right: KnowledgeChunk) -> list[str]:
    lineage: list[str] = []
    for chunk in (left, right):
        provenance = chunk.provenance if isinstance(chunk.provenance, dict) else {}
        merged_from = provenance.get("merged_from")
        if isinstance(merged_from, list):
            for identifier in merged_from:
                if isinstance(identifier, str) and identifier and identifier not in lineage:
                    lineage.append(identifier)
        chunk_identifier = _chunk_identifier_for_merge(chunk)
        if chunk_identifier not in lineage:
            lineage.append(chunk_identifier)
    return lineage


def _merged_role_counts(
    left: KnowledgeChunk,
    right: KnowledgeChunk,
) -> dict[str, int]:
    merged: dict[str, int] = {}
    for chunk in (left, right):
        provenance = chunk.provenance if isinstance(chunk.provenance, dict) else {}
        role_counts = provenance.get("block_role_counts")
        if not isinstance(role_counts, dict):
            continue
        for key, value in role_counts.items():
            normalized = str(key)
            count = _coerce_int(value)
            if count is None:
                continue
            merged[normalized] = merged.get(normalized, 0) + count
    return merged


def _merged_table_ids(
    left: KnowledgeChunk,
    right: KnowledgeChunk,
) -> list[str]:
    merged: list[str] = []
    for chunk in (left, right):
        provenance = chunk.provenance if isinstance(chunk.provenance, dict) else {}
        table_ids = provenance.get("table_ids")
        if not isinstance(table_ids, list):
            continue
        for table_id in table_ids:
            if not isinstance(table_id, str):
                continue
            normalized = table_id.strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
    return merged


def _parse_range(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    start = _coerce_int(value[0])
    end = _coerce_int(value[1])
    if start is None or end is None:
        return None
    if end < start:
        return (end, start)
    return (start, end)


def _relative_chunk_range(chunk: KnowledgeChunk) -> tuple[int, int] | None:
    if not chunk.block_ids:
        return None
    return (min(chunk.block_ids), max(chunk.block_ids))


def _renumber_chunk_ids(chunks: list[KnowledgeChunk]) -> None:
    for i, chunk in enumerate(chunks):
        chunk.identifier = f"c{i}"
        provenance = chunk.provenance if isinstance(chunk.provenance, dict) else {}
        provenance["chunk_index"] = i
        chunk.provenance = provenance


def _merge_chunk_provenance(
    left: KnowledgeChunk,
    right: KnowledgeChunk,
    *,
    merged_block_ids: list[int],
) -> dict[str, Any]:
    left_provenance = left.provenance if isinstance(left.provenance, dict) else {}
    merged: dict[str, Any] = dict(left_provenance)

    relative_range: list[int] = []
    if merged_block_ids:
        relative_range = [min(merged_block_ids), max(merged_block_ids)]
    merged["block_range"] = relative_range

    left_abs = chunk_abs_range(left)
    right_abs = chunk_abs_range(right)
    if left_abs and right_abs:
        merged["absolute_block_range"] = [
            min(left_abs[0], right_abs[0]),
            max(left_abs[1], right_abs[1]),
        ]
    elif left_abs:
        merged["absolute_block_range"] = [left_abs[0], left_abs[1]]
    elif right_abs:
        merged["absolute_block_range"] = [right_abs[0], right_abs[1]]

    merged_role_counts = _merged_role_counts(left, right)
    if merged_role_counts:
        merged["block_role_counts"] = merged_role_counts

    merged_table_ids = _merged_table_ids(left, right)
    if merged_table_ids:
        merged["table_ids"] = merged_table_ids

    merged["merged_from"] = _merged_identifier_lineage(left, right)
    return merged


# --------------------------------------------------------------------------
# Lane Assignment
# --------------------------------------------------------------------------

# Patterns for knowledge content
_KNOWLEDGE_IMPERATIVE_RE = re.compile(
    r"\b(use|add|keep|avoid|don'?t|do not|never|always|make sure|be sure|"
    r"remember|let|allow|stir|whisk|mix|cook|bake|roast|season|salt|sear|rest|"
    r"preheat|chill|heat|simmer|reduce|wash|dry|store|cut|slice|dice|chop)\b",
    re.IGNORECASE,
)
_KNOWLEDGE_MODAL_RE = re.compile(
    r"\b(should|must|need to|needs to|will|can|could|helps?|prevents?)\b",
    re.IGNORECASE,
)
_KNOWLEDGE_MECHANISM_RE = re.compile(
    r"\b(because|so that|therefore|in order to|which means|as a result|"
    r"this (helps|prevents|allows|ensures)|the reason)\b",
    re.IGNORECASE,
)
_KNOWLEDGE_DIAGNOSTIC_RE = re.compile(
    r"\b(you'?ll know|you will know|ready when|done when|look for|"
    r"should (be|look|feel|smell)|until)\b",
    re.IGNORECASE,
)
_KNOWLEDGE_TEMP_TIME_RE = re.compile(
    r"\b(\d+\s*(degrees?|°|f|c|fahrenheit|celsius|minutes?|mins?|hours?|hrs?|seconds?|secs?))\b",
    re.IGNORECASE,
)

# Patterns for narrative content
_NARRATIVE_FIRST_PERSON_RE = re.compile(
    r"\b(i|i'm|i am|i've|i'd|we|we're|we are|we've|my|our|me|us)\b",
    re.IGNORECASE,
)
_NARRATIVE_ANECDOTE_RE = re.compile(
    r"\b(i remember|when i was|years ago|growing up|my (mother|father|grandmother|"
    r"grandfather|mom|dad|grandma|aunt|uncle)|one time|once|"
    r"the first time|back in|in my childhood)\b",
    re.IGNORECASE,
)
_NARRATIVE_OPINION_RE = re.compile(
    r"\b(i think|i believe|i feel|in my opinion|to me|for me|i prefer|"
    r"i love|i like|i always|personally)\b",
    re.IGNORECASE,
)

# Patterns for noise/blurb content
_NOISE_PRAISE_RE = re.compile(
    r"\b(beautiful|gorgeous|stunning|magnificent|wonderful|extraordinary|"
    r"acclaimed|award-winning|best-selling|bestselling|definitive|"
    r"comprehensive|essential|must-have|indispensable)\b",
    re.IGNORECASE,
)
_NOISE_BOOK_RE = re.compile(
    r"\b(this book|the book|in (this|the) (book|volume|cookbook)|"
    r"teaches you|will teach|you'?ll learn|will learn|"
    r"pages|chapters?|featuring|includes)\b",
    re.IGNORECASE,
)
_NOISE_QUOTE_RE = re.compile(r'^["\u201c\u201d].*["\u201c\u201d]$')
_NOISE_ENDORSEMENT_RE = re.compile(
    r"\b(—|--|by\s+[A-Z][a-z]+\s+[A-Z][a-z]+|"
    r"author of|editor of|founder of|chef at|from the)\b",
)
_NOISE_NAVIGATION_RE = re.compile(
    r"\b(table of contents|contents|chapter\s+\d+|part\s+\d+|page\s+\d+|see also)\b",
    re.IGNORECASE,
)
_NOISE_MARKETING_RE = re.compile(
    r"\b(sign up|newsletter|follow us|visit (our|the)|website|order now|buy now|"
    r"available wherever books are sold|download|e-?book|subscribe)\b",
    re.IGNORECASE,
)
_NOISE_AD_COPY_RE = re.compile(
    r"\b(advertisement|advertising|ad copy|promotional copy|sponsored)\b",
    re.IGNORECASE,
)
_NOISE_ATTRIBUTION_LINE_RE = re.compile(
    r"^(by|photographs? by|photography by|illustrations? by|recipes? by|"
    r"adapted from|text by)\b",
    re.IGNORECASE,
)
_NOISE_INTRO_PHRASES = frozenset({
    "introduction", "foreword", "preface", "about this book",
    "how to use this book", "a note from the author",
})
_NOISE_NAVIGATION_TITLES = frozenset({
    "contents", "table of contents", "about the author", "about the authors",
    "copyright", "credits", "acknowledgments", "acknowledgements",
    "dedication", "author's note", "authors' note",
})
_UTILITY_SUBSTITUTION_RE = re.compile(
    r"\b(substitut(?:e|ion|ions)|swap|replace|instead of|in place of)\b",
    re.IGNORECASE,
)
_UTILITY_STORAGE_SAFETY_RE = re.compile(
    r"\b(store|storage|storing|refrigerat(?:e|ed|ion)|freeze|frozen|keep refrigerated|"
    r"food safety|safe(?:ly)?|danger zone|perishable|shelf life)\b",
    re.IGNORECASE,
)
_UTILITY_REFERENCE_RE = re.compile(
    r"\b(chart|table|guide|ratio|conversion|glossary|definition|means|refers to|"
    r"smoke point|temperature|doneness)\b",
    re.IGNORECASE,
)
_UTILITY_FAILURE_RE = re.compile(
    r"\b(prevent|avoid|fix|rescue|troubleshoot|curdle|split|seize|overcook|undercook|"
    r"burn|sticking|grainy)\b",
    re.IGNORECASE,
)
_UTILITY_LOW_VALUE_TRUTH_RE = re.compile(
    r"\b(is a|are a|is an|are an|is one of|are one of|comes from|is made from|"
    r"is used in|is popular|has a flavor|can be used)\b",
    re.IGNORECASE,
)


def assign_lanes(chunks: list[KnowledgeChunk]) -> list[KnowledgeChunk]:
    """Assign lane (knowledge/noise) to each chunk.

    Modifies chunks in place and returns the same list.
    """
    for chunk in chunks:
        chunk.lane = _score_lane(chunk)
    return chunks


def _score_lane(chunk: KnowledgeChunk) -> ChunkLane:
    """Score a chunk and determine its lane.

    Uses both text heuristics and block_role signals (from
    ``block_roles.assign_block_roles``) when available.
    """
    text = chunk.text
    title = (chunk.title or "").lower().strip().rstrip(":")
    table_ids = (chunk.provenance or {}).get("table_ids") or []
    if any(isinstance(table_id, str) and table_id.strip() for table_id in table_ids):
        return ChunkLane.KNOWLEDGE

    # Check for noise indicators first
    noise_score = _noise_score(text, title)
    if noise_score >= 0.6:
        return ChunkLane.NOISE

    # Check for narrative indicators
    narrative_score = _narrative_score(text)

    # Check for knowledge indicators
    knowledge_score = _knowledge_score(text)

    # Adjust scores using block_role counts when available
    role_counts = (chunk.provenance or {}).get("block_role_counts") or {}
    if role_counts:
        total_blocks = max(sum(role_counts.values()), 1)
        # Recipe-structural roles strongly indicate knowledge
        recipe_roles = (
            role_counts.get("ingredient_line", 0)
            + role_counts.get("instruction_line", 0)
            + role_counts.get("recipe_title", 0)
            + role_counts.get("metadata", 0)
        )
        recipe_ratio = recipe_roles / total_blocks
        # Tip-like roles are knowledge (technique/advice)
        tip_count = role_counts.get("tip_like", 0)
        # Narrative and other roles weakly suggest noise
        other_count = role_counts.get("other", 0)

        knowledge_score += recipe_ratio * 0.25
        knowledge_score += min(0.1, tip_count / total_blocks * 0.15)
        narrative_score += (other_count / total_blocks) * 0.1
        knowledge_score = min(1.0, knowledge_score)
        narrative_score = min(1.0, narrative_score)

    # Decision logic
    if knowledge_score >= 0.5 and knowledge_score > narrative_score:
        return ChunkLane.KNOWLEDGE
    elif narrative_score >= 0.4 and narrative_score > knowledge_score:
        return ChunkLane.NOISE
    elif knowledge_score >= 0.3:
        return ChunkLane.KNOWLEDGE
    elif narrative_score >= 0.2:
        return ChunkLane.NOISE
    else:
        # Default to knowledge if no strong signal
        return ChunkLane.KNOWLEDGE


def _knowledge_score(text: str) -> float:
    """Score text for knowledge content indicators."""
    score = 0.0
    char_count = max(len(text), 1)

    # Count matches normalized by length
    imperative_matches = len(_KNOWLEDGE_IMPERATIVE_RE.findall(text))
    modal_matches = len(_KNOWLEDGE_MODAL_RE.findall(text))
    mechanism_matches = len(_KNOWLEDGE_MECHANISM_RE.findall(text))
    diagnostic_matches = len(_KNOWLEDGE_DIAGNOSTIC_RE.findall(text))
    temp_time_matches = len(_KNOWLEDGE_TEMP_TIME_RE.findall(text))

    # Normalize by text length (per 500 chars)
    norm = 500 / char_count

    score += min(0.3, imperative_matches * 0.05 * norm)
    score += min(0.2, modal_matches * 0.04 * norm)
    score += min(0.3, mechanism_matches * 0.1 * norm)
    score += min(0.2, diagnostic_matches * 0.1 * norm)
    score += min(0.15, temp_time_matches * 0.05 * norm)

    # Penalize for narrative content
    if _NARRATIVE_FIRST_PERSON_RE.search(text):
        score -= 0.1
    if _NARRATIVE_ANECDOTE_RE.search(text):
        score -= 0.15

    return max(0.0, min(1.0, score))


def _narrative_score(text: str) -> float:
    """Score text for narrative content indicators."""
    score = 0.0
    char_count = max(len(text), 1)
    norm = 500 / char_count

    # First person usage
    first_person_matches = len(_NARRATIVE_FIRST_PERSON_RE.findall(text))
    score += min(0.3, first_person_matches * 0.03 * norm)

    # Anecdote patterns
    if _NARRATIVE_ANECDOTE_RE.search(text):
        score += 0.3

    # Opinion patterns
    opinion_matches = len(_NARRATIVE_OPINION_RE.findall(text))
    score += min(0.2, opinion_matches * 0.1 * norm)

    # Penalize if also has strong knowledge signals
    if _KNOWLEDGE_MECHANISM_RE.search(text):
        score -= 0.15
    if _KNOWLEDGE_DIAGNOSTIC_RE.search(text):
        score -= 0.1

    return max(0.0, min(1.0, score))


def _noise_score(text: str, title: str) -> float:
    """Score text for noise/blurb content indicators."""
    score = 0.0
    normalized_text = text.strip()
    lines = [line.strip() for line in normalized_text.split("\n") if line.strip()]

    # Check title for intro/noise sections
    if title in _NOISE_INTRO_PHRASES:
        score += 0.3
    if title in _NOISE_NAVIGATION_TITLES:
        score += 0.4

    # Praise adjectives
    praise_matches = len(_NOISE_PRAISE_RE.findall(text))
    score += min(0.3, praise_matches * 0.1)

    # Book/marketing language
    book_matches = len(_NOISE_BOOK_RE.findall(text))
    score += min(0.3, book_matches * 0.1)
    if _NOISE_MARKETING_RE.search(text):
        score += 0.45
    if _NOISE_AD_COPY_RE.search(text):
        score += 0.6

    if _looks_navigation_fragment(lines, title):
        score += 0.45

    if _looks_attribution_fragment(lines):
        score += 0.65

    if _looks_dedication_fragment(lines, title):
        score += 0.35

    # Quote-only content
    quote_lines = sum(1 for l in lines if _NOISE_QUOTE_RE.match(l))
    if lines and quote_lines / len(lines) > 0.5:
        score += 0.3

    # Endorsement patterns
    if _NOISE_ENDORSEMENT_RE.search(text):
        score += 0.2

    # Short chunks with praise but no actionable content
    if len(text) < 300 and praise_matches > 0 and not _KNOWLEDGE_IMPERATIVE_RE.search(text):
        score += 0.2

    return max(0.0, min(1.0, score))


def _looks_navigation_fragment(lines: Sequence[str], title: str) -> bool:
    if title in _NOISE_NAVIGATION_TITLES:
        return True
    if not lines:
        return False
    if any(_NOISE_NAVIGATION_RE.search(line) for line in lines):
        return True
    short_lines = [line for line in lines if len(line.split()) <= 6]
    numbered_or_dotted = [
        line for line in short_lines
        if re.search(r"\.{2,}\s*\d+$", line) or re.match(r"^\d+\.?\s+[A-Z]", line)
    ]
    return len(lines) >= 3 and len(numbered_or_dotted) >= max(2, len(lines) // 2)


def summarize_chunk_utility_profile(chunk: KnowledgeChunk) -> dict[str, Any]:
    text = str(chunk.text or "").strip()
    title = str(chunk.title or "").strip()
    normalized_title = title.lower().rstrip(":")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    positive_cues: list[str] = []
    negative_cues: list[str] = []

    if _chunk_has_table_content(chunk):
        positive_cues.append("reference_table_shape")
    if _KNOWLEDGE_MECHANISM_RE.search(text):
        positive_cues.append("cause_effect")
    if _KNOWLEDGE_DIAGNOSTIC_RE.search(text):
        positive_cues.append("diagnostic_or_sensory")
    if _UTILITY_SUBSTITUTION_RE.search(text):
        positive_cues.append("substitution")
    if _UTILITY_STORAGE_SAFETY_RE.search(text):
        positive_cues.append("storage_or_safety")
    if _UTILITY_REFERENCE_RE.search(text) and (
        _chunk_has_table_content(chunk) or len(lines) <= 6 or _looks_standalone_heading_chunk(chunk)
    ):
        positive_cues.append("reference_or_definition")
    if _UTILITY_FAILURE_RE.search(text):
        positive_cues.append("failure_prevention")
    if _KNOWLEDGE_IMPERATIVE_RE.search(text) and _KNOWLEDGE_MODAL_RE.search(text):
        positive_cues.append("actionable_technique")

    if _NARRATIVE_ANECDOTE_RE.search(text) or _NARRATIVE_FIRST_PERSON_RE.search(text):
        negative_cues.append("memoir_or_voice")
    if _NOISE_BOOK_RE.search(text) or _NOISE_MARKETING_RE.search(text) or _NOISE_PRAISE_RE.search(text):
        negative_cues.append("book_framing_or_marketing")
    if _looks_navigation_fragment(lines, normalized_title):
        negative_cues.append("navigation_or_taxonomy")
    if _looks_standalone_heading_chunk(chunk):
        negative_cues.append("rhetorical_heading")
    if (
        _UTILITY_LOW_VALUE_TRUTH_RE.search(text)
        and not positive_cues
        and len(lines) <= 3
        and len(text) <= 220
    ):
        negative_cues.append("true_but_low_utility")

    deduped_positive = list(dict.fromkeys(positive_cues))
    deduped_negative = list(dict.fromkeys(negative_cues))
    strong_positive = bool(
        {
            "reference_table_shape",
            "cause_effect",
            "diagnostic_or_sensory",
            "storage_or_safety",
            "failure_prevention",
        }.intersection(deduped_positive)
    )
    strong_negative = (
        bool(
            {
                "book_framing_or_marketing",
                "navigation_or_taxonomy",
                "memoir_or_voice",
            }.intersection(deduped_negative)
        )
        and not deduped_positive
    ) or ("rhetorical_heading" in deduped_negative and not deduped_positive)
    borderline = bool(deduped_positive and deduped_negative) or (
        "true_but_low_utility" in deduped_negative and not strong_negative
    )
    return {
        "positive_cues": deduped_positive,
        "negative_cues": deduped_negative,
        "strong_positive_cue": strong_positive,
        "strong_negative_cue": strong_negative,
        "borderline": borderline,
    }


def _looks_attribution_fragment(lines: Sequence[str]) -> bool:
    if not lines:
        return False
    combined = " ".join(lines)
    if len(combined) > 180:
        return False
    return all(_NOISE_ATTRIBUTION_LINE_RE.match(line) for line in lines)


def _looks_dedication_fragment(lines: Sequence[str], title: str) -> bool:
    if title == "dedication":
        return True
    if not lines:
        return False
    combined = " ".join(lines).strip()
    if len(combined) > 140:
        return False
    word_count = len(combined.split())
    if word_count == 0 or word_count > 18:
        return False
    lower = combined.lower()
    return lower.startswith(("for ", "to ")) and not _KNOWLEDGE_IMPERATIVE_RE.search(combined)


# --------------------------------------------------------------------------
# Highlight Extraction (Tip Mining Integration)
# --------------------------------------------------------------------------

# Minimum length for standalone tip promotion
_MIN_STANDALONE_CHARS = 60

# Contrastive markers that require expansion context
_CONTRASTIVE_RE = re.compile(
    r"\b(but|however|except|unless|instead|not necessarily|inverse|"
    r"on the other hand|contrary|although|though|while)\b",
    re.IGNORECASE,
)


def extract_highlights(
    chunks: list[KnowledgeChunk],
    *,
    overrides: ParsingOverrides | None = None,
) -> list[KnowledgeChunk]:
    """Extract highlights from each knowledge chunk using the existing tip miner.

    Modifies chunks in place, populating highlights, highlight_count, tip_density,
    and aggregated tags.

    Only processes chunks with lane=KNOWLEDGE.
    """
    for chunk in chunks:
        if chunk.lane != ChunkLane.KNOWLEDGE:
            continue

        # Use existing tip extraction on chunk text
        tips = tip_miner.extract_tip_candidates(
            chunk.text,
            provenance={"chunk_id": chunk.identifier},
            source_section="chunk",
            overrides=overrides,
        )

        highlights: list[ChunkHighlight] = []
        all_tags = TipTags()

        for tip in tips:
            # Skip non-tips
            if tip.scope == "not_tip":
                continue

            # Check if highlight is self-contained
            self_contained = _is_self_contained(tip.text)

            # Check for contrastive markers - these need context
            if _CONTRASTIVE_RE.search(tip.text) and len(tip.text) < _MIN_STANDALONE_CHARS:
                self_contained = False

            highlight = ChunkHighlight(
                text=tip.text,
                source_block_ids=chunk.block_ids,
                self_contained=self_contained,
                tags=tip.tags,
            )
            highlights.append(highlight)

            # Aggregate tags
            _merge_tags(all_tags, tip.tags)

        # Update chunk
        chunk.highlights = highlights
        chunk.highlight_count = len(highlights)
        chunk.tags = all_tags

        # Calculate tip density (highlights per 1000 chars)
        char_count = max(len(chunk.text), 1)
        chunk.tip_density = len(highlights) / (char_count / 1000)

    return chunks


def _is_self_contained(text: str) -> bool:
    """Check if a highlight is self-contained (complete thought)."""
    stripped = text.strip()
    if not stripped:
        return False

    # Too short
    if len(stripped) < _MIN_STANDALONE_CHARS:
        return False

    # Starts with dependent word
    dependent_starts = (
        "and ", "but ", "so ", "then ", "also ", "however ", "therefore ",
        "which ", "that ", "this ", "these ", "those ", "it ", "they ",
    )
    lower = stripped.lower()
    if any(lower.startswith(dep) for dep in dependent_starts):
        return False

    # Ends without terminal punctuation
    if not stripped.endswith((".", "!", "?", ":")):
        return False

    return True


def _merge_tags(target: TipTags, source: TipTags) -> None:
    """Merge source tags into target, avoiding duplicates."""
    for attr in (
        "recipes", "dishes", "meats", "vegetables", "herbs", "spices",
        "dairy", "grains", "legumes", "fruits", "sweeteners", "oils_fats",
        "techniques", "cooking_methods", "tools", "other",
    ):
        target_list = getattr(target, attr)
        source_list = getattr(source, attr)
        for item in source_list:
            if item not in target_list:
                target_list.append(item)


# --------------------------------------------------------------------------
# Adjacent Knowledge Consolidation
# --------------------------------------------------------------------------


def chunk_abs_range(chunk: KnowledgeChunk) -> tuple[int, int] | None:
    """Return a chunk's absolute [start, end] block range (inclusive)."""
    provenance = chunk.provenance if isinstance(chunk.provenance, dict) else {}

    absolute_range = _parse_range(provenance.get("absolute_block_range"))
    if absolute_range is not None:
        return absolute_range

    explicit_range = _parse_range(provenance.get("block_range"))
    if explicit_range is not None:
        return explicit_range

    return _relative_chunk_range(chunk)


def _normalize_topic_token(value: str) -> str:
    return _TOPIC_TOKEN_RE.sub(" ", value.lower()).strip()


def _chunk_heading_topic_key(chunk: KnowledgeChunk) -> str | None:
    normalized_section = [
        _normalize_topic_token(str(part))
        for part in chunk.section_path
        if _normalize_topic_token(str(part))
    ]
    if normalized_section:
        return " > ".join(normalized_section)

    if isinstance(chunk.title, str):
        normalized_title = _normalize_topic_token(chunk.title)
        if normalized_title:
            return normalized_title
    return None


def _chunk_tag_set(chunk: KnowledgeChunk) -> set[str]:
    tags = chunk.tags if isinstance(chunk.tags, TipTags) else TipTags()
    tag_values: set[str] = set()
    for field_name in _TAG_FIELD_NAMES:
        values = getattr(tags, field_name, [])
        if not isinstance(values, list):
            continue
        for value in values:
            normalized = _normalize_topic_token(str(value))
            if normalized:
                tag_values.add(normalized)
    return tag_values


def topic_key(chunk: KnowledgeChunk) -> str | tuple[str, ...] | None:
    """Return a stable topic key from heading context or chunk tags."""
    heading_key = _chunk_heading_topic_key(chunk)
    if heading_key is not None:
        return heading_key

    tag_values = sorted(_chunk_tag_set(chunk))
    if tag_values:
        return tuple(tag_values)
    return None


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _is_knowledge_chunk(chunk: KnowledgeChunk) -> bool:
    if isinstance(chunk.lane, ChunkLane):
        return chunk.lane == ChunkLane.KNOWLEDGE
    return str(chunk.lane).strip().lower() == ChunkLane.KNOWLEDGE.value


def should_merge_adjacent_chunks(
    left: KnowledgeChunk,
    right: KnowledgeChunk,
    *,
    max_merged_chars: int,
    require_contiguous_blocks: bool = True,
) -> bool:
    """Return True when two adjacent chunks are safe to merge."""
    if not _is_knowledge_chunk(left) or not _is_knowledge_chunk(right):
        return False

    if _chunk_has_table_content(left) or _chunk_has_table_content(right):
        return False

    if require_contiguous_blocks:
        left_range = chunk_abs_range(left)
        right_range = chunk_abs_range(right)
        if left_range is None or right_range is None:
            return False
        # Ranges are inclusive, so right.start must be left.end + 1.
        if left_range[1] + 1 != right_range[0]:
            return False

    merged_size = len(left.text.rstrip()) + 2 + len(right.text.lstrip())
    if merged_size > max_merged_chars:
        return False

    left_key = topic_key(left)
    right_key = topic_key(right)
    if left_key is not None and left_key == right_key:
        return True

    left_heading = _chunk_heading_topic_key(left)
    right_heading = _chunk_heading_topic_key(right)
    if left_heading is None and right_heading is None:
        left_tags = _chunk_tag_set(left)
        right_tags = _chunk_tag_set(right)
        if left_tags and right_tags and _jaccard_similarity(left_tags, right_tags) >= 0.7:
            return True

    return False


def _merge_int_lists(left: list[int], right: list[int]) -> list[int]:
    merged: list[int] = []
    for value in left + right:
        parsed = _coerce_int(value)
        if parsed is None or parsed in merged:
            continue
        merged.append(parsed)
    return merged


def _dedupe_chunk_highlights(highlights: list[ChunkHighlight]) -> list[ChunkHighlight]:
    deduped: list[ChunkHighlight] = []
    seen: set[tuple[str, tuple[int, ...]]] = set()
    for highlight in highlights:
        source_ids = []
        for source_id in highlight.source_block_ids:
            parsed = _coerce_int(source_id)
            if parsed is not None:
                source_ids.append(parsed)
        normalized_text = _normalize_topic_token(highlight.text) or highlight.text.strip().lower()
        key = (normalized_text, tuple(sorted(set(source_ids))))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(highlight)
    return deduped


def _merge_adjacent_chunk_pair(left: KnowledgeChunk, right: KnowledgeChunk) -> KnowledgeChunk:
    merged_text = left.text.rstrip() + "\n\n" + right.text.lstrip()
    merged_block_ids = left.block_ids + right.block_ids
    merged_highlights = _dedupe_chunk_highlights(list(left.highlights) + list(right.highlights))
    merged_tags = TipTags()
    _merge_tags(merged_tags, left.tags)
    _merge_tags(merged_tags, right.tags)

    merged_section_path = left.section_path or right.section_path
    left_heading = _chunk_heading_topic_key(left)
    right_heading = _chunk_heading_topic_key(right)
    if (
        left_heading is not None
        and right_heading is not None
        and left_heading == right_heading
        and right.section_path
        and len(right.section_path) > len(merged_section_path)
    ):
        merged_section_path = right.section_path

    merged = KnowledgeChunk(
        identifier=left.identifier,
        lane=left.lane,
        title=left.title or right.title,
        section_path=merged_section_path,
        text=merged_text,
        block_ids=merged_block_ids,
        aside_block_ids=_merge_int_lists(left.aside_block_ids, right.aside_block_ids),
        excluded_block_ids=_merge_int_lists(left.excluded_block_ids, right.excluded_block_ids),
        distill_text=left.distill_text or right.distill_text,
        boundary_start_reason=left.boundary_start_reason,
        boundary_end_reason=right.boundary_end_reason,
        tags=merged_tags,
        highlight_count=len(merged_highlights),
        highlights=merged_highlights,
        source=left.source or right.source,
        provenance=_merge_chunk_provenance(
            left,
            right,
            merged_block_ids=merged_block_ids,
        ),
    )
    merged.tip_density = len(merged_highlights) / (max(len(merged.text), 1) / 1000)
    return merged


def consolidate_adjacent_knowledge_chunks(
    chunks: list[KnowledgeChunk],
    *,
    max_merged_chars: int,
    require_contiguous_blocks: bool = True,
) -> list[KnowledgeChunk]:
    """Merge adjacent knowledge chunks that represent the same topic."""
    if not chunks:
        return []

    consolidated: list[KnowledgeChunk] = []
    pending = chunks[0]
    for chunk in chunks[1:]:
        if should_merge_adjacent_chunks(
            pending,
            chunk,
            max_merged_chars=max_merged_chars,
            require_contiguous_blocks=require_contiguous_blocks,
        ):
            pending = _merge_adjacent_chunk_pair(pending, chunk)
        else:
            consolidated.append(pending)
            pending = chunk
    consolidated.append(pending)

    _renumber_chunk_ids(consolidated)
    return consolidated


def _consolidate_adjacent_knowledge_chunks_enabled() -> bool:
    raw_value = os.getenv(_CONSOLIDATE_ADJACENT_KNOWLEDGE_CHUNKS_ENV)
    if raw_value is None:
        return True
    normalized = str(raw_value).strip().lower()
    if normalized in {"0", "false", "no", "off"}:
        return False
    return True


# --------------------------------------------------------------------------
# Full Pipeline
# --------------------------------------------------------------------------


def process_blocks_to_chunks(
    blocks: Sequence[Block],
    *,
    profile: ChunkingProfile | None = None,
    overrides: ParsingOverrides | None = None,
    min_merge_chars: int = 200,
) -> list[KnowledgeChunk]:
    """Full pipeline: chunk blocks, assign lanes, extract highlights.

    This is the main entry point for knowledge chunking.

    Args:
        blocks: Sequence of Block objects (non-recipe content).
        profile: Chunking configuration.
        overrides: Parsing overrides for tip extraction.
        min_merge_chars: Minimum chunk size before merging.

    Returns:
        List of fully processed KnowledgeChunk objects.
    """
    effective_profile = profile or ChunkingProfile()

    # Step 1: Create initial chunks from block structure
    chunks = chunk_non_recipe_blocks(blocks, profile=effective_profile)

    # Step 2: Merge small chunks
    chunks = merge_small_chunks(chunks, min_chars=min_merge_chars)

    # Step 3: Collapse heading-only and tiny bridge chunks into neighbors.
    chunks = collapse_heading_bridge_chunks(chunks)

    # Step 4: Assign lanes (knowledge/noise)
    chunks = assign_lanes(chunks)

    # Step 5: Extract highlights from knowledge chunks
    chunks = extract_highlights(chunks, overrides=overrides)

    # Step 6: Consolidate adjacent same-topic knowledge chunks (can be disabled).
    if _consolidate_adjacent_knowledge_chunks_enabled():
        chunks = consolidate_adjacent_knowledge_chunks(
            chunks,
            max_merged_chars=effective_profile.max_chars,
            require_contiguous_blocks=True,
        )

    return chunks

def chunks_from_non_recipe_blocks(
    non_recipe_blocks: Sequence[dict],
    *,
    profile: ChunkingProfile | None = None,
    overrides: ParsingOverrides | None = None,
) -> list[KnowledgeChunk]:
    """Convert non-recipe block dicts to knowledge chunks.

    This is the preferred method when raw blocks are available from
    the plugin. It preserves the original document structure and
    produces larger, more coherent chunks.

    Args:
        non_recipe_blocks: List of block dicts with 'index', 'text', 'features'.
        profile: Chunking configuration.
        overrides: Parsing overrides for tip extraction.

    Returns:
        List of fully processed KnowledgeChunk objects.
    """
    if not non_recipe_blocks:
        return []

    # Convert block dicts to Block objects
    blocks: list[Block] = []
    for block_dict in non_recipe_blocks:
        features = block_dict.get("features", {})
        normalized_features = dict(features) if isinstance(features, dict) else {}
        source_block_index = _coerce_int(block_dict.get("index"))
        if source_block_index is not None:
            normalized_features.setdefault("source_block_index", source_block_index)
        table_id = block_dict.get("table_id")
        if isinstance(table_id, str) and table_id.strip():
            normalized_features.setdefault("table_id", table_id.strip())
        table_row_index = block_dict.get("table_row_index")
        try:
            if table_row_index is not None:
                normalized_features.setdefault("table_row_index", int(table_row_index))
        except (TypeError, ValueError):
            pass
        block = Block(
            text=block_dict.get("text", ""),
            type=BlockType.TEXT,
            features=normalized_features,
        )
        blocks.append(block)

    return process_blocks_to_chunks(blocks, profile=profile, overrides=overrides)


def _looks_like_header(text: str) -> bool:
    """Check if text looks like a section header."""
    text = text.strip()
    if not text:
        return False
    # All caps
    if text.isupper() and len(text) < 80:
        return True
    # Ends with colon
    if text.endswith(":") and len(text) < 60:
        return True
    # Short title case
    if text.istitle() and len(text.split()) <= 6:
        return True
    return False
