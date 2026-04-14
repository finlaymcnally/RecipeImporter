from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

_WHITESPACE_RE = re.compile(r"\s+")
_SPACED_FRACTION_RE = re.compile(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)")
_NOTE_PREFIX_RE = re.compile(r"^\s*note\s*:\s*", re.IGNORECASE)
_YIELD_PREFIX_RE = re.compile(
    r"^\s*(?:makes|serves?|servings|yields?)\b",
    re.IGNORECASE,
)
_NUMBERED_STEP_RE = re.compile(r"^\s*(?:step\s*)?\d{1,2}[.)]\s+", re.IGNORECASE)
_HOWTO_PREFIX_RE = re.compile(
    r"^\s*(?:to make|to serve|for serving|for garnish|for the)\b",
    re.IGNORECASE,
)
_BOUNDARY_NOTE_RE = re.compile(r"\bnote\s*:\s*", re.IGNORECASE)
_BOUNDARY_YIELD_RE = re.compile(
    r"\b(?:makes|serves?|servings|yields?)\b",
    re.IGNORECASE,
)
_BOUNDARY_HOWTO_RE = re.compile(
    r"\b(?:to make|to serve|for serving|for garnish|for the)\b",
    re.IGNORECASE,
)
_BOUNDARY_NUMBERED_RE = re.compile(r"(?<!\w)(?:step\s*)?\d{1,2}[.)]\s+", re.IGNORECASE)
_QUANTITY_START_RE = re.compile(
    r"(?<![\w/])(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?(?:\s*(?:to|-)\s*\d+(?:\.\d+)?)?)\s+(?=[A-Za-z])",
    re.IGNORECASE,
)
_QUANTITY_RANGE_START_RE = re.compile(
    r"^\s*\d+(?:\.\d+)?\s*(?:to|-)\s*\d+(?:\.\d+)?\s+",
    re.IGNORECASE,
)
_INGREDIENT_UNIT_HINT_RE = re.compile(
    r"\b(cups?|tbsp|tablespoons?|tsp|teaspoons?|oz|ounces?|lb|lbs|pounds?|"
    r"g|kg|ml|l|cloves?|sticks?|cans?|jars?|bunch(?:es)?|pinch)\b",
    re.IGNORECASE,
)
_TIME_METADATA_RE = re.compile(
    r"\b(?:\d+\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)|"
    r"prep time|cook time|total time|active time)\b",
    re.IGNORECASE,
)
_INSTRUCTION_VERB_RE = re.compile(
    r"^\s*(?:add|bake|beat|blend|boil|braise|bring|combine|cook|cool|cover|drain|"
    r"fold|grill|heat|mix|place|pour|reduce|remove|roast|season|serve|simmer|stir|"
    r"transfer|whisk)\b",
    re.IGNORECASE,
)
_INSTRUCTION_CUE_RE = re.compile(
    r"\b(?:add|bake|beat|blend|boil|braise|bring|combine|cook|cool|cover|drain|"
    r"fold|grill|heat|mix|place|pour|reduce|remove|roast|season|serve|simmer|stir|"
    r"transfer|whisk)\b",
    re.IGNORECASE,
)
_BROKEN_DUAL_UNIT_FRAGMENT_RE = re.compile(
    r"^\s*\d+(?:\.\d+)?\s+[A-Za-z][A-Za-z'/-]*/\s*$",
    re.IGNORECASE,
)
_SHORT_QUANTITY_INGREDIENT_RE = re.compile(
    r"^\s*(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s+[A-Za-z]",
    re.IGNORECASE,
)
_VARIANT_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'/-]*")
_TITLE_CASE_WORD_RE = re.compile(r"[A-Z][A-Za-z'/-]*")
_FIRST_PERSON_RE = re.compile(r"\b(?:i|i'm|i'd|i've|my|me|we|we're|our)\b", re.IGNORECASE)
_NOTE_PROSE_HINT_RE = re.compile(
    r"\b(?:you can|you may|if you like|if desired|optional|i like|i prefer|"
    r"make sure|the key is|don't|do not|tip|tips)\b",
    re.IGNORECASE,
)
_NON_RECIPE_PROSE_HINT_RE = re.compile(
    r"\b(?:preface|introduction|contents|acknowledg(?:ment|ments)|index)\b",
    re.IGNORECASE,
)
_RECIPE_CONTEXT_HINT_RE = re.compile(
    r"\b(?:egg|eggs|omelet|omelette|soup|chicken|stock|broth|sauce|gravy|"
    r"hollandaise|boil|fry|roast|braise|biscuits?|scones?|pancakes?|waffles?|"
    r"hash|onion|garlic|tomato|cheese|pasta|bean|mushroom|broccoli|potato|"
    r"parsley|bacon|ham|buttermilk|yolk|rice|noodles|gravy)\b",
    re.IGNORECASE,
)
_INGREDIENT_NOUN_HINTS = {
    "anchovy",
    "beef",
    "broth",
    "butter",
    "cheese",
    "chicken",
    "cream",
    "egg",
    "eggs",
    "flour",
    "garlic",
    "juice",
    "lemon",
    "milk",
    "oil",
    "onion",
    "pepper",
    "salt",
    "stock",
    "sugar",
    "vinegar",
    "water",
    "wine",
    "yolk",
    "yolks",
}
_YIELD_AMOUNT_HINTS = {
    "batch",
    "batches",
    "cookie",
    "cookies",
    "cup",
    "cups",
    "glass",
    "glasses",
    "jar",
    "jars",
    "loaf",
    "loaves",
    "piece",
    "pieces",
    "portion",
    "portions",
    "serving",
    "servings",
}
_YIELD_LEAD_QUALIFIERS = {
    "about",
    "approximately",
    "approx",
    "around",
    "almost",
    "nearly",
    "roughly",
}
_YIELD_LEAD_NUMBER_WORDS = {
    "a",
    "an",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
}

_PROSE_KEEP_MAX_CHARS = 220
_PROSE_FORCE_SPLIT_MAX_CHARS = 320
_PROSE_REPAIR_FRAGMENT_MAX_CHARS = 70
_PROSE_COMFORTABLE_MIN_CHARS = 120
_PROSE_MAX_SENTENCES = 2
_PROSE_FORCE_SPLIT_SENTENCES = 3
_ABSURDLY_LONG_ROW_CHARS = 450
_SENTENCE_END_CHARS = ".?!"
_CLOSING_SENTENCE_CHARS = "\"')]}”’"
_MID_SENTENCE_SPLIT_CHARS = ",:"


class SourceRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    row_id: str
    source_hash: str
    row_index: int
    row_ordinal: int
    block_id: str
    block_index: int
    start_char_in_block: int
    end_char_in_block: int
    text: str
    rule_tags: list[str] = Field(default_factory=list)


def build_source_rows(
    source_blocks: Sequence[Any],
    *,
    source_hash: str,
) -> list[SourceRow]:
    normalized_hash = str(source_hash or "unknown").strip() or "unknown"
    rows: list[SourceRow] = []
    row_index = 0
    for position, block in enumerate(source_blocks):
        block_text, block_index, block_id = _coerce_block(block, fallback_index=position)
        if not block_text:
            continue
        segments = _split_block_text(block_text)
        if not segments:
            continue
        offsets = _resolve_segment_offsets(block_text, segments)
        for row_ordinal, (segment_text, (start_char, end_char)) in enumerate(
            zip(segments, offsets, strict=False)
        ):
            rows.append(
                SourceRow(
                    row_id=_build_row_id(
                        source_hash=normalized_hash,
                        block_index=block_index,
                        row_ordinal=row_ordinal,
                    ),
                    source_hash=normalized_hash,
                    row_index=row_index,
                    row_ordinal=row_ordinal,
                    block_id=block_id,
                    block_index=block_index,
                    start_char_in_block=start_char,
                    end_char_in_block=end_char,
                    text=segment_text,
                    rule_tags=_infer_rule_tags(segment_text, within_recipe_span=None),
                )
            )
            row_index += 1
    return rows


def load_source_rows(path: Path) -> list[SourceRow]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[SourceRow] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(SourceRow.model_validate(payload))
    rows.sort(key=lambda row: int(row.row_index))
    return rows


def write_source_rows(path: Path, rows: Sequence[SourceRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(
        "\n".join(
            json.dumps(row.model_dump(mode="json"), sort_keys=True) for row in rows
        )
        + "\n",
        encoding="utf-8",
    )


def source_rows_to_payload(rows: Sequence[SourceRow]) -> list[dict[str, Any]]:
    return [row.model_dump(mode="json") for row in rows]


def _build_row_id(*, source_hash: str, block_index: int, row_ordinal: int) -> str:
    return f"urn:cookimport:row:{source_hash}:{block_index}:{row_ordinal}"


def _coerce_block(block: Any, *, fallback_index: int) -> tuple[str, int, str]:
    if isinstance(block, Mapping):
        text = _normalize_text(str(block.get("text") or ""))
        raw_index = block.get("block_index", block.get("order_index", block.get("index", fallback_index)))
        block_index = _coerce_int(raw_index, fallback=fallback_index)
        block_id = str(
            block.get("block_id")
            or block.get("id")
            or f"block:{block_index}"
        )
        return text, block_index, block_id

    text = _normalize_text(str(getattr(block, "text", "") or ""))
    raw_index = getattr(
        block,
        "block_index",
        getattr(block, "order_index", getattr(block, "index", fallback_index)),
    )
    block_index = _coerce_int(raw_index, fallback=fallback_index)
    block_id = str(getattr(block, "block_id", f"block:{block_index}") or f"block:{block_index}")
    return text, block_index, block_id


def _coerce_int(value: Any, *, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _normalize_text(text: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", text.replace("\r", " ").replace("\n", " ")).strip()
    return _SPACED_FRACTION_RE.sub(r"\1/\2", normalized)


def _resolve_segment_offsets(
    block_text: str,
    segments: Sequence[str],
) -> list[tuple[int, int]]:
    offsets: list[tuple[int, int]] = []
    cursor = 0
    normalized = str(block_text or "")
    for segment in segments:
        start, end = _find_segment_offset(normalized, segment, cursor=cursor)
        offsets.append((start, end))
        cursor = max(cursor, end)
    return offsets


def _find_segment_offset(
    block_text: str,
    segment: str,
    *,
    cursor: int,
) -> tuple[int, int]:
    candidates = [segment]
    if segment and segment[-1:] not in {".", ",", ";", ":"}:
        candidates.extend(
            [f"{segment}.", f"{segment},", f"{segment};", f"{segment}:"]
        )
    for candidate in candidates:
        start = block_text.find(candidate, cursor)
        if start >= 0:
            return start, start + len(candidate)
    start = block_text.find(segment)
    if start >= 0:
        return start, start + len(segment)
    return cursor, cursor + len(segment)


def _split_block_text(text: str) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []

    segments = [normalized]
    for pattern in (
        _BOUNDARY_NOTE_RE,
        _BOUNDARY_YIELD_RE,
        _BOUNDARY_HOWTO_RE,
        _BOUNDARY_NUMBERED_RE,
    ):
        next_segments: list[str] = []
        for segment in segments:
            next_segments.extend(_split_before_pattern(segment, pattern))
        segments = next_segments

    output: list[str] = []
    for segment in segments:
        output.extend(_split_segment(segment))

    final_rows: list[str] = []
    for segment in output:
        cleaned = _normalize_text(segment.strip(" ,;"))
        if not cleaned:
            continue
        final_rows.append(cleaned.rstrip(".") if _looks_like_heading(cleaned) else cleaned)
    return _repair_prose_rows(final_rows)


def _split_segment(segment: str) -> list[str]:
    if ";" in segment:
        semicolon_rows = [_normalize_text(part) for part in segment.split(";")]
        rows: list[str] = []
        for item in semicolon_rows:
            if not item:
                continue
            rows.extend(_split_segment(item))
        return rows

    if _is_yield_line(segment):
        return _split_yield_segment(segment)

    return _split_quantity_runs(segment)


def _split_yield_segment(segment: str) -> list[str]:
    yield_match = _YIELD_PREFIX_RE.match(segment)
    search_start = yield_match.end() if yield_match else 0
    quantity_matches = list(_QUANTITY_START_RE.finditer(segment, pos=search_start))
    if len(quantity_matches) < 2:
        return [segment]

    first_match = quantity_matches[0]
    second_match = quantity_matches[1]
    first_fragment = _normalize_text(segment[first_match.start():second_match.start()])
    if _looks_like_yield_amount_fragment(first_fragment):
        first_ingredient_start = second_match.start()
    else:
        first_ingredient_start = first_match.start()
    yield_text = _normalize_text(segment[:first_ingredient_start])
    remainder = _normalize_text(segment[first_ingredient_start:])
    rows: list[str] = []
    if yield_text:
        rows.append(yield_text)
    if remainder:
        rows.extend(_split_quantity_runs(remainder))
    return rows or [segment]


def _split_quantity_runs(segment: str) -> list[str]:
    if _is_control_line(segment):
        return [segment]

    starts = sorted({match.start() for match in _QUANTITY_START_RE.finditer(segment)})
    if len(starts) <= 1:
        return [segment]
    prefix = _normalize_text(segment[: starts[0]].strip(" ,;"))
    if _should_keep_quantity_segment_whole(segment, prefix=prefix):
        return [segment]

    rows: list[str] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(segment)
        chunk = _normalize_text(segment[start:end].strip(" ,;"))
        if not chunk:
            continue
        if _looks_quantity_fragment_artifact(chunk):
            return [segment]
        rows.append(chunk)

    if prefix:
        rows.insert(0, prefix)
    return rows or [segment]


def _split_before_pattern(text: str, pattern: re.Pattern[str]) -> list[str]:
    starts = sorted(
        {
            match.start()
            for match in pattern.finditer(text)
            if not (
                pattern is _BOUNDARY_YIELD_RE
                and text[max(0, match.start() - 3): match.start()].lower() == "to "
            )
            if not (
                pattern is _BOUNDARY_YIELD_RE
                and not _looks_like_yield_line(text[match.start():])
            )
            if not (
                pattern is _BOUNDARY_HOWTO_RE
                and not _looks_like_structural_howto_boundary(text, match.start())
            )
            if match.start() > 0 and not text[max(0, match.start() - 1)].isalnum()
        }
    )
    if not starts:
        return [text]

    rows: list[str] = []
    cursor = 0
    for start in starts:
        chunk = _normalize_text(text[cursor:start].strip(" ,;"))
        if chunk:
            rows.append(chunk)
        cursor = start
    tail = _normalize_text(text[cursor:].strip(" ,;"))
    if tail:
        rows.append(tail)
    return rows or [text]


def _is_control_line(text: str) -> bool:
    return (
        _is_note_line(text)
        or _is_yield_line(text)
        or _is_howto_heading(text)
        or _is_numbered_instruction(text)
    )


def _repair_prose_rows(rows: Sequence[str]) -> list[str]:
    repaired: list[str] = []
    index = 0
    while index < len(rows):
        group = [rows[index]]
        while index + 1 < len(rows) and _should_join_prose_cleanup_rows(group[-1], rows[index + 1]):
            index += 1
            group.append(rows[index])

        if len(group) == 1:
            repaired.extend(_split_oversized_prose_row(group[0]))
        else:
            repaired.extend(_split_oversized_prose_row(_normalize_text(" ".join(group))))
        index += 1
    return repaired


def _should_join_prose_cleanup_rows(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if _is_structural_row_for_prose_cleanup(left) or _is_structural_row_for_prose_cleanup(right):
        return False
    if _ends_with_sentence_boundary(left):
        return False
    return _starts_with_lowercase_token(right)


def _split_oversized_prose_row(text: str) -> list[str]:
    stripped = _normalize_text(text)
    if not stripped:
        return []
    if _is_structural_row_for_prose_cleanup(stripped):
        return [stripped]
    if not _row_needs_prose_cleanup(stripped):
        return [stripped]

    sentence_spans = _sentence_spans(stripped)
    if len(sentence_spans) <= 1:
        return _split_absurdly_long_row(stripped)

    merged_spans = _merge_small_sentence_spans(stripped, sentence_spans)
    rows = [_normalize_text(stripped[start:end]) for start, end in merged_spans]
    final_rows: list[str] = []
    for row in rows:
        if _row_needs_prose_cleanup(row) and len(_sentence_spans(row)) <= 1:
            final_rows.extend(_split_absurdly_long_row(row))
            continue
        final_rows.append(row)
    return final_rows or [stripped]


def _row_needs_prose_cleanup(text: str) -> bool:
    sentence_count = _sentence_count(text)
    if len(text) > _PROSE_FORCE_SPLIT_MAX_CHARS:
        return True
    if sentence_count >= _PROSE_FORCE_SPLIT_SENTENCES:
        return True
    return len(text) > _PROSE_KEEP_MAX_CHARS and sentence_count >= 2


def _sentence_count(text: str) -> int:
    return len(_sentence_spans(text))


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    stripped = str(text or "").strip()
    if not stripped:
        return []

    spans: list[tuple[int, int]] = []
    start = 0
    index = 0
    while index < len(stripped):
        if stripped[index] not in _SENTENCE_END_CHARS:
            index += 1
            continue
        if _is_decimal_point(stripped, index):
            index += 1
            continue

        boundary_end = index + 1
        while boundary_end < len(stripped) and stripped[boundary_end] in _CLOSING_SENTENCE_CHARS:
            boundary_end += 1
        if not _looks_like_sentence_boundary(stripped, boundary_end):
            index += 1
            continue

        spans.append((start, boundary_end))
        start = _skip_whitespace(stripped, boundary_end)
        index = start

    if start < len(stripped):
        spans.append((start, len(stripped)))
    return spans


def _is_decimal_point(text: str, index: int) -> bool:
    if text[index] != ".":
        return False
    return (
        index > 0
        and text[index - 1].isdigit()
        and index + 1 < len(text)
        and text[index + 1].isdigit()
    )


def _looks_like_sentence_boundary(text: str, boundary_end: int) -> bool:
    next_index = _skip_whitespace(text, boundary_end)
    if next_index >= len(text):
        return True

    while next_index < len(text) and text[next_index] in "\"'([{“‘":
        next_index += 1
    if next_index >= len(text):
        return True
    next_char = text[next_index]
    return next_char.isupper() or next_char.isdigit()


def _skip_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _merge_small_sentence_spans(
    text: str,
    spans: Sequence[tuple[int, int]],
) -> list[tuple[int, int]]:
    if not spans:
        return []

    merged: list[tuple[int, int]] = []
    current_start, current_end = spans[0]
    current_count = 1
    for next_start, next_end in spans[1:]:
        current_text = text[current_start:current_end].strip()
        next_text = text[next_start:next_end].strip()
        merged_text = text[current_start:next_end].strip()
        if (
            current_count < _PROSE_MAX_SENTENCES
            and len(merged_text) <= _PROSE_KEEP_MAX_CHARS
            and len(current_text) < _PROSE_COMFORTABLE_MIN_CHARS
            and len(next_text) < _PROSE_COMFORTABLE_MIN_CHARS
            and (
                len(current_text) <= _PROSE_REPAIR_FRAGMENT_MAX_CHARS
                or len(next_text) <= _PROSE_REPAIR_FRAGMENT_MAX_CHARS
            )
        ):
            current_end = next_end
            current_count += 1
            continue

        merged.append((current_start, current_end))
        current_start, current_end = next_start, next_end
        current_count = 1
    merged.append((current_start, current_end))
    return merged


def _split_absurdly_long_row(text: str) -> list[str]:
    stripped = _normalize_text(text)
    if len(stripped) <= _ABSURDLY_LONG_ROW_CHARS:
        return [stripped]

    split_at = _best_mid_sentence_split_index(stripped)
    if split_at is None:
        return [stripped]
    left = _normalize_text(stripped[:split_at].rstrip())
    right = _normalize_text(stripped[split_at:].lstrip())
    if not left or not right:
        return [stripped]
    rows: list[str] = []
    rows.extend(_split_absurdly_long_row(left))
    rows.extend(_split_absurdly_long_row(right))
    return rows


def _best_mid_sentence_split_index(text: str) -> int | None:
    midpoint = len(text) / 2
    candidates: list[tuple[float, int]] = []
    for index, char in enumerate(text):
        if char not in _MID_SENTENCE_SPLIT_CHARS:
            continue
        split_at = index + 1
        left = text[:split_at].strip()
        right = text[split_at:].strip()
        if len(left) < 80 or len(right) < 80:
            continue
        candidates.append((abs(split_at - midpoint), split_at))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _is_structural_row_for_prose_cleanup(text: str) -> bool:
    return (
        _is_cleanup_control_row(text)
        or _is_variant_heading(text)
        or _is_recipe_title_like(text)
        or _is_ingredient_line(text)
    )


def _is_cleanup_control_row(text: str) -> bool:
    return (
        _is_note_line(text)
        or _looks_like_cleanup_yield_row(text)
        or _is_howto_heading(text)
        or _is_numbered_instruction(text)
    )


def _looks_like_cleanup_yield_row(text: str) -> bool:
    return _looks_like_yield_line(text)


def _ends_with_sentence_boundary(text: str) -> bool:
    stripped = str(text or "").rstrip()
    if not stripped:
        return False
    return stripped[-1] in _SENTENCE_END_CHARS


def _starts_with_lowercase_token(text: str) -> bool:
    stripped = str(text or "").lstrip()
    if not stripped:
        return False
    for char in stripped:
        if char.isalpha():
            return char.islower()
        if char.isdigit():
            return False
    return False


def _looks_like_structural_howto_boundary(text: str, start: int) -> bool:
    candidate = text[start:].strip()
    if not _looks_compact_howto_heading(candidate):
        return False
    if start <= 0:
        return True
    previous_index = start - 1
    while previous_index >= 0 and text[previous_index].isspace():
        previous_index -= 1
    if previous_index < 0:
        return True
    return text[previous_index] in ".!?:"


def _looks_like_yield_amount_fragment(text: str) -> bool:
    stripped = str(text or "").strip().lower()
    if not stripped or len(stripped) > 24:
        return False
    if any(mark in stripped for mark in ",;.!?"):
        return False
    words = _VARIANT_WORD_RE.findall(stripped)
    if len(words) > 2:
        return False
    if not words:
        return False
    return words[-1] in _YIELD_AMOUNT_HINTS or words[-1] in {
        "cup",
        "cups",
    }


def _looks_like_yield_line(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    match = _YIELD_PREFIX_RE.match(stripped)
    if not match:
        return False
    remainder = stripped[match.end():].lstrip(" :")
    if not remainder:
        return False
    lowered = remainder.lower()
    if lowered.startswith("enough for "):
        remainder = remainder[len("enough for ") :].lstrip()
        lowered = remainder.lower()
        if not remainder:
            return False
    for qualifier in sorted(_YIELD_LEAD_QUALIFIERS, key=len, reverse=True):
        prefix = f"{qualifier} "
        if lowered.startswith(prefix):
            remainder = remainder[len(prefix) :].lstrip()
            lowered = remainder.lower()
            break
    if not remainder:
        return False
    if remainder[0].isdigit():
        return True
    words = _VARIANT_WORD_RE.findall(lowered)
    if not words:
        return False
    first_word = words[0]
    prefix_word = match.group(0).strip().split()[0].lower()
    if prefix_word.startswith("serv"):
        return first_word in _YIELD_LEAD_NUMBER_WORDS
    if first_word not in _YIELD_LEAD_NUMBER_WORDS:
        return False
    return len(words) >= 2 and words[1] in _YIELD_AMOUNT_HINTS


def _infer_rule_tags(
    text: str,
    *,
    within_recipe_span: bool | None,
) -> list[str]:
    if _is_note_line(text):
        return ["note_prefix"]
    if _is_yield_line(text):
        return ["yield_prefix"]
    if _is_howto_heading(text):
        return ["howto_heading"]
    if _is_variant_heading(text):
        return ["variant_heading"]
    if _is_recipe_title_like(text):
        if within_recipe_span is True:
            return ["title_like"]
        if within_recipe_span is False:
            return ["title_like", "outside_recipe_span"]
        return ["title_like"]
    if _is_ingredient_line(text):
        return ["ingredient_like"]
    if _looks_note_prose(text):
        return ["note_like_prose"]
    if _is_numbered_instruction(text) or _is_instruction_sentence(text):
        if _is_time_metadata(text):
            return ["instruction_with_time"]
        return ["instruction_like"]
    if _is_time_metadata(text):
        return ["time_metadata"]
    if within_recipe_span is True:
        rule_tags = ["recipe_span_fallback"]
        if _looks_explicit_prose(text):
            rule_tags.append("explicit_prose")
        return rule_tags
    if within_recipe_span is False:
        rule_tags = ["outside_recipe_span"]
        if _looks_explicit_prose(text):
            rule_tags.append("explicit_prose")
        return rule_tags
    rule_tags: list[str] = []
    if _looks_explicit_prose(text):
        rule_tags.append("explicit_prose")
    return rule_tags


def _is_note_line(text: str) -> bool:
    return bool(_NOTE_PREFIX_RE.match(text))


def _is_yield_line(text: str) -> bool:
    return _looks_like_yield_line(text)


def _is_numbered_instruction(text: str) -> bool:
    return bool(_NUMBERED_STEP_RE.match(text))


def _has_howto_prefix(text: str) -> bool:
    return bool(_HOWTO_PREFIX_RE.match(text))


def _looks_compact_howto_heading(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or not _has_howto_prefix(stripped):
        return False
    if stripped[-1:] in {".", "!", "?"}:
        return False
    heading_text = stripped[:-1].rstrip() if stripped.endswith(":") else stripped
    if not heading_text:
        return False
    if any(mark in heading_text for mark in ".,;()"):
        return False
    words = _VARIANT_WORD_RE.findall(heading_text)
    if not (2 <= len(words) <= 8):
        return False
    if len(heading_text) > 72:
        return False
    return True


def _is_howto_heading(text: str) -> bool:
    return _looks_compact_howto_heading(text)


def _looks_like_heading(text: str) -> bool:
    words = _VARIANT_WORD_RE.findall(text)
    if not words:
        return False
    if len(words) > 12:
        return False
    uppercase_chars = sum(1 for ch in text if ch.isupper())
    alpha_chars = sum(1 for ch in text if ch.isalpha())
    if alpha_chars <= 0:
        return False
    uppercase_ratio = uppercase_chars / alpha_chars
    return uppercase_ratio >= 0.72 and text[-1:] not in {".", "!", "?"}


def _is_variant_heading(text: str) -> bool:
    words = _VARIANT_WORD_RE.findall(text)
    if len(words) < 4:
        return False
    if _is_howto_heading(text) or _is_numbered_instruction(text) or _is_yield_line(text):
        return False

    all_caps = all(word.upper() == word for word in words)
    if all_caps and "-" in text:
        return True

    title_case_words = _TITLE_CASE_WORD_RE.findall(text)
    if len(title_case_words) >= max(3, len(words) - 2) and "-" in text:
        return True
    return False


def _is_ingredient_line(text: str) -> bool:
    normalized = text.lower().strip()
    if not normalized:
        return False
    if _is_control_line(text):
        return False
    if _looks_quantity_fragment_artifact(text):
        return False
    if _looks_instructional_quantity_fragment(text):
        return False
    if _QUANTITY_RANGE_START_RE.match(text):
        return True
    if _QUANTITY_START_RE.match(text):
        if _INGREDIENT_UNIT_HINT_RE.search(text):
            return True
        if any(hint in normalized for hint in _INGREDIENT_NOUN_HINTS):
            return True
        if _is_short_quantity_led_ingredient_shape(text):
            return True
    word_count = len(_VARIANT_WORD_RE.findall(text))
    if 1 <= word_count <= 4 and any(hint in normalized for hint in _INGREDIENT_NOUN_HINTS):
        return True
    return False


def _is_instruction_sentence(text: str) -> bool:
    if _looks_note_prose(text):
        return False
    if _INSTRUCTION_VERB_RE.match(text):
        return True
    if (
        "." in text
        and len(_VARIANT_WORD_RE.findall(text)) >= 8
        and _INSTRUCTION_CUE_RE.search(text)
    ):
        return True
    return False


def _is_time_metadata(text: str) -> bool:
    return bool(_TIME_METADATA_RE.search(text))


def _looks_explicit_prose(text: str) -> bool:
    words = _VARIANT_WORD_RE.findall(text)
    if len(words) < 10:
        return False
    punctuation_hits = sum(ch in {".", ",", ";", ":"} for ch in text)
    return punctuation_hits >= 1


def _is_recipe_title_like(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _is_note_line(stripped) or _is_yield_line(stripped) or _is_howto_heading(stripped):
        return False
    if _is_numbered_instruction(stripped) or _is_time_metadata(stripped):
        return False
    if _QUANTITY_START_RE.match(stripped) or _INSTRUCTION_VERB_RE.match(stripped):
        return False
    if stripped[-1:] in {".", "!", "?"}:
        return False
    words = _VARIANT_WORD_RE.findall(stripped)
    if len(words) < 2 or len(words) > 12:
        return False
    if _looks_like_heading(stripped):
        return True
    title_case_words = _TITLE_CASE_WORD_RE.findall(stripped)
    return len(title_case_words) >= max(2, len(words) - 1)


def _looks_note_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _is_note_line(stripped):
        return True
    if (
        _is_yield_line(stripped)
        or _is_howto_heading(stripped)
        or _is_numbered_instruction(stripped)
    ):
        return False
    if _QUANTITY_START_RE.match(stripped):
        return False
    words = _VARIANT_WORD_RE.findall(stripped)
    if len(words) < 9:
        return False
    if _NON_RECIPE_PROSE_HINT_RE.search(stripped):
        return False
    if _NOTE_PROSE_HINT_RE.search(stripped):
        return True
    if _FIRST_PERSON_RE.search(stripped) and _RECIPE_CONTEXT_HINT_RE.search(stripped):
        return True
    return False


def _should_keep_quantity_segment_whole(segment: str, *, prefix: str) -> bool:
    if prefix and not prefix.endswith(":"):
        return True
    if _looks_instructional_quantity_fragment(segment):
        return True
    return False


def _looks_instructional_quantity_fragment(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        return True
    words = _VARIANT_WORD_RE.findall(stripped)
    if len(words) < 8:
        return False
    if "." in stripped and _INSTRUCTION_CUE_RE.search(stripped):
        return True
    if "," in stripped and _INSTRUCTION_CUE_RE.search(stripped):
        return True
    return False


def _looks_quantity_fragment_artifact(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _BROKEN_DUAL_UNIT_FRAGMENT_RE.match(stripped):
        return True
    if stripped.endswith("/") and _QUANTITY_START_RE.match(stripped):
        return True
    return False


def _is_short_quantity_led_ingredient_shape(text: str) -> bool:
    stripped = str(text or "").strip()
    if not _SHORT_QUANTITY_INGREDIENT_RE.match(stripped):
        return False
    if any(ch in stripped for ch in ".;!?"):
        return False
    if _TIME_METADATA_RE.search(stripped):
        return False
    if _INSTRUCTION_CUE_RE.search(stripped):
        return False
    words = _VARIANT_WORD_RE.findall(stripped)
    return 2 <= len(words) <= 10
