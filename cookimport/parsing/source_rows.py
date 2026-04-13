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
    return final_rows


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
    quantity_matches = list(_QUANTITY_START_RE.finditer(segment))
    if len(quantity_matches) < 2:
        return [segment]

    first_ingredient_start = quantity_matches[1].start()
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
    return bool(_YIELD_PREFIX_RE.match(text))


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
    if any(mark in heading_text for mark in ",;()"):
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
