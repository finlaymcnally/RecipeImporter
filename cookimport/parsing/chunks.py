"""Knowledge chunking module.

Implements structure-first chunking for non-recipe content blocks.
Chunks are formed based on headings and section boundaries rather than
punctuation or sentence boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from cookimport.core.blocks import Block, BlockType
from cookimport.core.models import (
    ChunkBoundaryReason,
    ChunkHighlight,
    ChunkLane,
    KnowledgeChunk,
    ParsingOverrides,
    TipTags,
    TopicCandidate,
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

        heading_level = _detect_heading_level(block, profile)

        # Check for callout prefix
        callout_match = _is_callout_start(text, profile)

        # Check for stop heading (INDEX, ACKNOWLEDGMENTS, etc.)
        if heading_level and _is_stop_heading(text, profile):
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
        if heading_level and heading_level in profile.major_heading_levels:
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
        elif heading_level and heading_level in profile.minor_heading_levels:
            while section_stack and section_stack[-1][0] >= heading_level:
                section_stack.pop()
            section_stack.append((heading_level, text))
            current.section_path = get_section_path()
            if not current.title:
                current.title = text

        # Callout prefix creates a boundary if configured
        elif callout_match and profile.split_on_callouts:
            if current.block_ids:
                flush_chunk(ChunkBoundaryReason.CALLOUT_SEED)
            current.title = text if len(text) < 80 else None
            current.is_callout = True
            current.start_reason = ChunkBoundaryReason.CALLOUT_SEED

        # Check for format mode change (prose -> bullets, etc.)
        elif current.block_ids and _is_format_mode_change(current.blocks[-1], block):
            # Only split if we have reasonable content
            if current.char_count >= profile.min_chars:
                flush_chunk(ChunkBoundaryReason.FORMAT_MODE_CHANGE)

        # Check max size
        if current.char_count + len(text) > profile.max_chars and current.block_ids:
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
            if len(chunk.text) < min_chars:
                pending = chunk
            else:
                result.append(chunk)
        else:
            # Check if we should merge
            shared_path = _shared_section_prefix(pending.section_path, chunk.section_path)
            if shared_path or len(pending.text) < min_chars // 2:
                # Merge pending into current
                merged = KnowledgeChunk(
                    identifier=pending.identifier,
                    lane=pending.lane,
                    title=pending.title or chunk.title,
                    section_path=pending.section_path or chunk.section_path,
                    text=pending.text + "\n\n" + chunk.text,
                    block_ids=pending.block_ids + chunk.block_ids,
                    boundary_start_reason=pending.boundary_start_reason,
                    boundary_end_reason=chunk.boundary_end_reason,
                    provenance={
                        **pending.provenance,
                        "merged_from": [pending.identifier, chunk.identifier],
                    },
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

    # Renumber identifiers
    for i, chunk in enumerate(result):
        chunk.identifier = f"c{i}"
        chunk.provenance["chunk_index"] = i

    return result


def _shared_section_prefix(path1: list[str], path2: list[str]) -> list[str]:
    """Return the shared prefix of two section paths."""
    shared = []
    for a, b in zip(path1, path2):
        if a == b:
            shared.append(a)
        else:
            break
    return shared


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
_NOISE_INTRO_PHRASES = frozenset({
    "introduction", "foreword", "preface", "about this book",
    "how to use this book", "a note from the author",
})


def assign_lanes(chunks: list[KnowledgeChunk]) -> list[KnowledgeChunk]:
    """Assign lane (knowledge/narrative/noise) to each chunk.

    Modifies chunks in place and returns the same list.
    """
    for chunk in chunks:
        chunk.lane = _score_lane(chunk)
    return chunks


def _score_lane(chunk: KnowledgeChunk) -> ChunkLane:
    """Score a chunk and determine its lane."""
    text = chunk.text
    title = (chunk.title or "").lower().strip().rstrip(":")

    # Check for noise indicators first
    noise_score = _noise_score(text, title)
    if noise_score >= 0.6:
        return ChunkLane.NOISE

    # Check for narrative indicators
    narrative_score = _narrative_score(text)

    # Check for knowledge indicators
    knowledge_score = _knowledge_score(text)

    # Decision logic
    if knowledge_score >= 0.5 and knowledge_score > narrative_score:
        return ChunkLane.KNOWLEDGE
    elif narrative_score >= 0.4 and narrative_score > knowledge_score:
        return ChunkLane.NARRATIVE
    elif knowledge_score >= 0.3:
        return ChunkLane.KNOWLEDGE
    elif narrative_score >= 0.2:
        return ChunkLane.NARRATIVE
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

    # Check title for intro/noise sections
    if title in _NOISE_INTRO_PHRASES:
        score += 0.3

    # Praise adjectives
    praise_matches = len(_NOISE_PRAISE_RE.findall(text))
    score += min(0.3, praise_matches * 0.1)

    # Book/marketing language
    book_matches = len(_NOISE_BOOK_RE.findall(text))
    score += min(0.3, book_matches * 0.1)

    # Quote-only content
    lines = [l.strip() for l in text.split("\n") if l.strip()]
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
    # Step 1: Create initial chunks from block structure
    chunks = chunk_non_recipe_blocks(blocks, profile=profile)

    # Step 2: Merge small chunks
    chunks = merge_small_chunks(chunks, min_chars=min_merge_chars)

    # Step 3: Assign lanes (knowledge/narrative/noise)
    chunks = assign_lanes(chunks)

    # Step 4: Extract highlights from knowledge chunks
    chunks = extract_highlights(chunks, overrides=overrides)

    return chunks


def chunks_from_topic_candidates(
    topic_candidates: Sequence[TopicCandidate],
    *,
    profile: ChunkingProfile | None = None,
    overrides: ParsingOverrides | None = None,
) -> list[KnowledgeChunk]:
    """Convert topic candidates to knowledge chunks.

    This bridges the existing topic candidate extraction with the new
    chunking system. Topic candidates are converted to blocks, then
    processed through the full chunking pipeline.

    Note: Prefer using chunks_from_non_recipe_blocks() when raw blocks
    are available, as it preserves document structure better.

    Args:
        topic_candidates: List of TopicCandidate objects from conversion.
        profile: Chunking configuration.
        overrides: Parsing overrides for tip extraction.

    Returns:
        List of fully processed KnowledgeChunk objects.
    """
    if not topic_candidates:
        return []

    # Convert topic candidates to blocks
    blocks: list[Block] = []
    for i, tc in enumerate(topic_candidates):
        block = Block(
            text=tc.text,
            type=BlockType.TEXT,
            features={
                "source_topic_id": tc.identifier,
                "topic_header": tc.header,
            },
        )
        # Add header information if available
        if tc.header:
            block.features["is_header_likely"] = _looks_like_header(tc.header)
        blocks.append(block)

    return process_blocks_to_chunks(blocks, profile=profile, overrides=overrides)


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
        block = Block(
            text=block_dict.get("text", ""),
            type=BlockType.TEXT,
            features=features if isinstance(features, dict) else {},
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
