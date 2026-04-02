from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from cookimport.core.models import ConversionResult, HowToStep, RecipeCandidate
from cookimport.labelstudio.archive import build_extracted_archive, normalize_display_text
from cookimport.parsing.sections import (
    extract_ingredient_sections,
    extract_instruction_sections,
)
from cookimport.parsing.tips import extract_recipe_specific_notes
from cookimport.staging.recipe_ownership import (
    RecipeOwnershipInvariantError,
    RecipeOwnershipResult,
)


_YIELD_KEYWORDS_RE = re.compile(r"\b(yield|serves?|servings?|makes?)\b", re.IGNORECASE)
_TIME_KEYWORDS_RE = re.compile(
    r"\b(prep|cook|total|active|rest|marinate|chill|time)\b",
    re.IGNORECASE,
)
_TIME_VALUE_RE = re.compile(
    r"(?:\b\d+\s*(?:h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\b|\b\d{1,2}:\d{2}\b)",
    re.IGNORECASE,
)
_VARIANT_HEADER_RE = re.compile(
    r"^\s*variations?\s*:?\s*$|^\s*variants?\s*:?\s*$",
    re.IGNORECASE,
)
_VARIANT_PREFIX_RE = re.compile(r"^\s*variations?\b|^\s*variants?\b", re.IGNORECASE)
_INSTRUCTION_PREFIX_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+")
_HOWTO_SENTENCE_END_RE = re.compile(r"[.!?]\s*$")
_HOWTO_WORD_RE = re.compile(r"[A-Za-z]+")
_HOWTO_ALL_CAPS_RE = re.compile(r"^[A-Z0-9][A-Z0-9 &/+-]*$")
_TITLE_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'/-]*")
_TITLE_PROSE_CUE_RE = re.compile(
    r"\b(?:i|my|me|we|our|chapter|preface|introduction)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ArchiveBlockView:
    index: int
    text: str
    location: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RecipeBlockEvidence:
    archive: list[ArchiveBlockView]
    block_count: int
    block_labels: dict[int, set[str]]
    notes: list[str]


def load_stage_prediction_archive(
    conversion_result: ConversionResult,
    archive_blocks: Iterable[dict[str, Any]] | None,
) -> list[ArchiveBlockView]:
    if archive_blocks is None:
        archive_payload = build_extracted_archive(
            conversion_result,
            conversion_result.raw_artifacts,
        )
        return sorted(
            [
                ArchiveBlockView(
                    index=int(block.index),
                    text=str(block.text or ""),
                    location=dict(block.location or {}),
                )
                for block in archive_payload
            ],
            key=lambda block: block.index,
        )

    blocks: list[ArchiveBlockView] = []
    for fallback_index, payload in enumerate(archive_blocks):
        if not isinstance(payload, dict):
            continue
        raw_index = payload.get("index")
        try:
            block_index = int(raw_index)
        except (TypeError, ValueError):
            block_index = fallback_index
        location = payload.get("location")
        if not isinstance(location, dict):
            location = {
                key: value
                for key, value in payload.items()
                if key not in {"index", "text"}
            }
        blocks.append(
            ArchiveBlockView(
                index=block_index,
                text=str(payload.get("text") or ""),
                location=dict(location),
            )
        )
    return sorted(blocks, key=lambda block: block.index)


def resolve_stage_prediction_source_file(conversion_result: ConversionResult) -> str:
    if conversion_result.workbook_path:
        return str(conversion_result.workbook_path)
    if conversion_result.source:
        return str(conversion_result.source)
    if conversion_result.workbook:
        return str(conversion_result.workbook)
    return ""


def resolve_stage_prediction_source_hash(conversion_result: ConversionResult) -> str:
    for artifact in conversion_result.raw_artifacts:
        if artifact.source_hash:
            return str(artifact.source_hash)
    for recipe in conversion_result.recipes:
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        source_hash = provenance.get("file_hash") or provenance.get("fileHash")
        if source_hash:
            return str(source_hash)
    return "unknown"


def build_recipe_block_evidence(
    conversion_result: ConversionResult,
    *,
    archive: list[ArchiveBlockView],
    recipe_ownership_result: RecipeOwnershipResult,
) -> RecipeBlockEvidence:
    notes: list[str] = []
    max_index = max((block.index for block in archive), default=-1)
    block_count = max_index + 1 if max_index >= 0 else 0
    block_labels: dict[int, set[str]] = {index: set() for index in range(block_count)}
    archive_by_index = {block.index: block for block in archive}
    for recipe in conversion_result.recipes:
        recipe_id = _require_recipe_id(recipe)
        ownership_entry = recipe_ownership_result.recipe_entry_by_recipe_id(recipe_id)
        if ownership_entry is None:
            raise RecipeOwnershipInvariantError(
                f"Recipe-local evidence could not be projected because '{recipe_id}' has no ownership entry."
            )
        _label_recipe_blocks(
            recipe,
            archive_by_index=archive_by_index,
            owned_block_indices=ownership_entry.owned_block_indices,
            block_labels=block_labels,
            notes=notes,
        )
    ownership_recipe_ids = {entry.recipe_id for entry in recipe_ownership_result.recipe_entries}
    result_recipe_ids = {_require_recipe_id(recipe) for recipe in conversion_result.recipes}
    extra_ownership_ids = sorted(ownership_recipe_ids - result_recipe_ids)
    if extra_ownership_ids:
        raise RecipeOwnershipInvariantError(
            "Recipe ownership referenced recipes that were not present in the conversion result: "
            f"{extra_ownership_ids}."
        )
    return RecipeBlockEvidence(
        archive=archive,
        block_count=block_count,
        block_labels=block_labels,
        notes=notes,
    )


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_recipe_range(
    recipe: RecipeCandidate,
    *,
    archive: list[ArchiveBlockView],
) -> tuple[int | None, int | None]:
    provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
    location = provenance.get("location") if isinstance(provenance, dict) else None
    if not isinstance(location, dict):
        location = {}

    start = _coerce_int(location.get("start_block"))
    end = _coerce_int(location.get("end_block"))
    if start is None and end is None:
        single = _coerce_int(location.get("block_index"))
        if single is not None:
            return single, single
        line_start = _coerce_int(location.get("start_line"))
        line_end = _coerce_int(location.get("end_line"))
        if line_start is None:
            line_start = _coerce_int(location.get("startLine"))
        if line_end is None:
            line_end = _coerce_int(location.get("endLine"))
        if line_start is None and line_end is None:
            line_single = _coerce_int(location.get("line_index"))
            if line_single is None:
                line_single = _coerce_int(location.get("lineIndex"))
            if line_single is None:
                line_single = _coerce_int(location.get("line"))
            if line_single is not None:
                line_start = line_single
                line_end = line_single
        if line_start is None and line_end is None:
            return None, None
        if line_start is None:
            line_start = line_end
        if line_end is None:
            line_end = line_start
        if line_start is None or line_end is None:
            return None, None
        if line_start > line_end:
            line_start, line_end = line_end, line_start
        line_index_matches = _match_archive_indices_for_line_range(
            archive,
            start_line=line_start,
            end_line=line_end,
        )
        if not line_index_matches:
            return None, None
        return min(line_index_matches), max(line_index_matches)
    if start is None:
        start = end
    if end is None:
        end = start
    if start is None or end is None:
        return None, None
    if start > end:
        start, end = end, start
    return start, end


def _label_recipe_blocks(
    recipe: RecipeCandidate,
    *,
    archive_by_index: dict[int, ArchiveBlockView],
    owned_block_indices: list[int],
    block_labels: dict[int, set[str]],
    notes: list[str],
) -> None:
    recipe_id = _require_recipe_id(recipe)
    if not owned_block_indices:
        notes.append(
            f"Recipe '{recipe.name}' ({recipe_id}) owns no blocks; skipped recipe-local labeling."
        )
        return
    candidate_blocks: list[ArchiveBlockView] = []
    missing_block_indices: list[int] = []
    for block_index in owned_block_indices:
        block = archive_by_index.get(int(block_index))
        if block is None:
            missing_block_indices.append(int(block_index))
            continue
        candidate_blocks.append(block)
    if missing_block_indices:
        raise RecipeOwnershipInvariantError(
            f"Recipe '{recipe_id}' owns missing archive blocks: {missing_block_indices}."
        )

    title_index = _find_title_block_index(recipe, candidate_blocks)
    if title_index is not None:
        _mark_label(block_labels, title_index, "RECIPE_TITLE")

    ingredient_indices = _match_texts_to_block_indices(
        _ingredient_texts(recipe),
        candidate_blocks,
        preferred_roles={"ingredient_line", "section_heading"},
    )
    for idx in ingredient_indices:
        _mark_label(block_labels, idx, "INGREDIENT_LINE")

    instruction_indices = _match_texts_to_block_indices(
        _instruction_texts(recipe),
        candidate_blocks,
        preferred_roles={"instruction_line", "section_heading"},
    )
    for idx in instruction_indices:
        _mark_label(block_labels, idx, "INSTRUCTION_LINE")

    ingredient_role_indices = {
        block.index for block in candidate_blocks if _block_role(block) == "ingredient_line"
    }
    instruction_role_indices = {
        block.index for block in candidate_blocks if _block_role(block) == "instruction_line"
    }
    howto_header_rows = _ingredient_section_header_texts(recipe)
    howto_header_rows.extend(_instruction_section_header_texts(recipe))
    howto_indices = _match_texts_to_block_indices(
        howto_header_rows,
        candidate_blocks,
        preferred_roles={"ingredient_line", "instruction_line", "section_heading"},
    )
    howto_indices = _filter_howto_section_indices(
        indices=howto_indices,
        candidate_blocks=candidate_blocks,
        structural_signal_indices=(
            ingredient_indices
            | instruction_indices
            | ingredient_role_indices
            | instruction_role_indices
        ),
    )
    for idx in howto_indices:
        _mark_label(block_labels, idx, "HOWTO_SECTION")

    for idx in _match_texts_to_block_indices(_note_texts(recipe), candidate_blocks):
        _mark_label(block_labels, idx, "RECIPE_NOTES")

    variant_texts = _variant_texts(recipe)
    variant_indices = _match_texts_to_block_indices(variant_texts, candidate_blocks)
    if not variant_indices and variant_texts:
        for block in candidate_blocks:
            if _is_variant_text(block.text):
                variant_indices.add(block.index)
    block_position_by_index = {
        block.index: position for position, block in enumerate(candidate_blocks)
    }
    block_by_index = {block.index: block for block in candidate_blocks}
    variant_indices = {
        index
        for index in variant_indices
        if (
            (block := block_by_index.get(index)) is not None
            and (position := block_position_by_index.get(index)) is not None
            and _is_valid_title_or_variant_candidate(
                block,
                candidate_blocks=candidate_blocks,
                candidate_position=position,
                kind="variant",
            )
        )
    }
    for idx in variant_indices:
        _mark_label(block_labels, idx, "RECIPE_VARIANT")

    for idx in _find_yield_block_indices(recipe, candidate_blocks):
        _mark_label(block_labels, idx, "YIELD_LINE")
    for idx in _find_time_block_indices(recipe, candidate_blocks):
        _mark_label(block_labels, idx, "TIME_LINE")

    if not ingredient_indices:
        for block in candidate_blocks:
            if _block_role(block) == "ingredient_line":
                _mark_label(block_labels, block.index, "INGREDIENT_LINE")
    if not instruction_indices:
        for block in candidate_blocks:
            if _block_role(block) == "instruction_line":
                _mark_label(block_labels, block.index, "INSTRUCTION_LINE")

    if title_index is not None:
        existing = block_labels.get(title_index)
        if existing is not None:
            existing.discard("INGREDIENT_LINE")
            existing.discard("INSTRUCTION_LINE")


def _mark_label(block_labels: dict[int, set[str]], block_index: int, label: str) -> None:
    if block_index < 0:
        return
    block_labels.setdefault(block_index, set()).add(label)


def _require_recipe_id(recipe: RecipeCandidate) -> str:
    recipe_id = str(getattr(recipe, "identifier", None) or "").strip()
    if recipe_id:
        return recipe_id
    provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
    for key in ("@id", "id"):
        raw_value = provenance.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
    raise RecipeOwnershipInvariantError(
        f"Recipe '{getattr(recipe, 'name', '')}' is missing an identifier."
    )


def _normalize_for_match(text: str) -> str:
    normalized = normalize_display_text(text).lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9 ]+", "", normalized)
    return normalized.strip()


def _match_archive_indices_for_line_range(
    archive: list[ArchiveBlockView],
    *,
    start_line: int,
    end_line: int,
) -> set[int]:
    offsets = (0, -1, 1)
    for offset in offsets:
        low = start_line + offset
        high = end_line + offset
        if low > high:
            continue
        matches = {
            block.index
            for block in archive
            if (line_index := _coerce_int(block.location.get("line_index"))) is not None
            and low <= line_index <= high
        }
        if matches:
            return matches
    for offset in offsets:
        low = start_line + offset
        high = end_line + offset
        if low > high:
            continue
        matches = {block.index for block in archive if low <= block.index <= high}
        if matches:
            return matches
    return set()


def _ingredient_texts(recipe: RecipeCandidate) -> list[str]:
    return [str(value or "") for value in recipe.ingredients if str(value or "").strip()]


def _instruction_texts(recipe: RecipeCandidate) -> list[str]:
    texts: list[str] = []
    for item in recipe.instructions:
        text = item.text if isinstance(item, HowToStep) else str(item)
        text = text.strip()
        if text:
            texts.append(text)
    return texts


def _note_texts(recipe: RecipeCandidate) -> list[str]:
    rows: list[str] = []
    for comment in recipe.comments:
        text = (comment.text or comment.name or "").strip()
        if text:
            rows.append(text)
    rows.extend(extract_recipe_specific_notes(recipe))
    return _dedupe_text_rows(rows)


def _ingredient_section_header_texts(recipe: RecipeCandidate) -> list[str]:
    sectioned = extract_ingredient_sections(recipe.ingredients)
    return [str(hit.raw_line).strip() for hit in sectioned.header_hits if str(hit.raw_line).strip()]


def _instruction_section_header_texts(recipe: RecipeCandidate) -> list[str]:
    sectioned = extract_instruction_sections(_instruction_texts(recipe))
    return [str(hit.raw_line).strip() for hit in sectioned.header_hits if str(hit.raw_line).strip()]


def _dedupe_text_rows(rows: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for row in rows:
        text = str(row or "").strip()
        if not text:
            continue
        normalized = _normalize_for_match(text) or text.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(text)
    return deduped


def _variant_texts(recipe: RecipeCandidate) -> list[str]:
    return [text for text in _instruction_texts(recipe) if _is_variant_text(text)]


def _is_variant_text(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    return bool(_VARIANT_HEADER_RE.match(stripped) or _VARIANT_PREFIX_RE.match(stripped))


def _looks_title_boundary_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    words = _TITLE_WORD_RE.findall(stripped)
    if len(words) >= 10 and any(ch in stripped for ch in ",.;:"):
        return True
    if _TITLE_PROSE_CUE_RE.search(stripped) and len(words) >= 6:
        return True
    return False


def _block_features(block: ArchiveBlockView) -> dict[str, Any]:
    location = block.location if isinstance(block.location, dict) else {}
    features = location.get("features")
    return features if isinstance(features, dict) else {}


def _block_role(block: ArchiveBlockView) -> str:
    features = _block_features(block)
    role = features.get("block_role")
    if role is None:
        role = block.location.get("block_role") if isinstance(block.location, dict) else None
    return str(role or "").strip().lower()


def _block_has_recipe_boundary_signal(block: ArchiveBlockView) -> bool:
    text = (block.text or "").strip()
    role = _block_role(block)
    if role in {"ingredient_line", "instruction_line"}:
        return True
    if _YIELD_KEYWORDS_RE.search(text):
        return True
    if _TIME_KEYWORDS_RE.search(text) and _TIME_VALUE_RE.search(text):
        return True
    if _INSTRUCTION_PREFIX_RE.match(text):
        return True
    return False


def _has_title_boundary_evidence(
    *,
    candidate_position: int,
    candidate_blocks: list[ArchiveBlockView],
    kind: str,
) -> bool:
    upper = min(len(candidate_blocks), candidate_position + (4 if kind == "title" else 3) + 1)
    for position in range(candidate_position + 1, upper):
        if _block_has_recipe_boundary_signal(candidate_blocks[position]):
            return True
    if kind == "variant":
        lower = max(0, candidate_position - 2)
        for position in range(lower, candidate_position):
            if _block_has_recipe_boundary_signal(candidate_blocks[position]):
                return True
    return False


def _is_valid_title_or_variant_candidate(
    block: ArchiveBlockView,
    *,
    candidate_blocks: list[ArchiveBlockView],
    candidate_position: int,
    kind: str,
) -> bool:
    text = (block.text or "").strip()
    if not text or len(text) > 140:
        return False
    if kind == "variant" and not _is_variant_text(text):
        return False
    if kind == "title" and text[-1:] in {".", "!", "?"}:
        return False
    if kind == "title" and (
        _YIELD_KEYWORDS_RE.search(text)
        or (_TIME_KEYWORDS_RE.search(text) and _TIME_VALUE_RE.search(text))
        or _INSTRUCTION_PREFIX_RE.match(text)
        or _looks_title_boundary_prose(text)
    ):
        return False
    return _has_title_boundary_evidence(
        candidate_position=candidate_position,
        candidate_blocks=candidate_blocks,
        kind=kind,
    )


def _find_title_block_index(
    recipe: RecipeCandidate,
    candidate_blocks: list[ArchiveBlockView],
) -> int | None:
    recipe_name = (recipe.name or "").strip()
    target = _normalize_for_match(recipe_name) if recipe_name else ""
    if target:
        for position, block in enumerate(candidate_blocks[:60]):
            if _normalize_for_match(block.text) == target and _is_valid_title_or_variant_candidate(
                block,
                candidate_blocks=candidate_blocks,
                candidate_position=position,
                kind="title",
            ):
                return block.index
        for position, block in enumerate(candidate_blocks[:60]):
            block_norm = _normalize_for_match(block.text)
            if not block_norm:
                continue
            if (target in block_norm or block_norm in target) and _is_valid_title_or_variant_candidate(
                block,
                candidate_blocks=candidate_blocks,
                candidate_position=position,
                kind="title",
            ):
                return block.index

    best: tuple[int, int] | None = None
    start_index = candidate_blocks[0].index
    for position, block in enumerate(candidate_blocks[:20]):
        text = (block.text or "").strip()
        if not text or len(text) > 140:
            continue
        if not _is_valid_title_or_variant_candidate(
            block,
            candidate_blocks=candidate_blocks,
            candidate_position=position,
            kind="title",
        ):
            continue
        score = 0
        features = _block_features(block)
        if features.get("is_heading") or features.get("is_header_likely"):
            score += 10
        if features.get("block_role") in {"recipe_title", "section_heading"}:
            score += 4
        if _YIELD_KEYWORDS_RE.search(text) or _TIME_KEYWORDS_RE.search(text):
            score -= 8
        if _INSTRUCTION_PREFIX_RE.match(text):
            score -= 6
        score -= max(0, block.index - start_index)
        if best is None or score > best[0]:
            best = (score, block.index)
    return best[1] if best is not None and best[0] > 0 else None


def _find_yield_block_indices(
    recipe: RecipeCandidate,
    candidate_blocks: list[ArchiveBlockView],
) -> set[int]:
    matches: set[int] = set()
    recipe_yield = (recipe.recipe_yield or "").strip()
    if recipe_yield:
        target = _normalize_for_match(recipe_yield)
        for block in candidate_blocks[:30]:
            block_norm = _normalize_for_match(block.text)
            if block_norm and target and (target in block_norm or block_norm in target):
                matches.add(block.index)
    if matches:
        return matches
    for block in candidate_blocks[:30]:
        text = (block.text or "").strip()
        if text and _YIELD_KEYWORDS_RE.search(text) and _block_role(block) != "instruction_line":
            matches.add(block.index)
    return matches


def _find_time_block_indices(
    recipe: RecipeCandidate,
    candidate_blocks: list[ArchiveBlockView],
) -> set[int]:
    matches: set[int] = set()
    normalized_values = [
        _normalize_for_match(str(value).strip())
        for value in (recipe.prep_time, recipe.cook_time, recipe.total_time)
        if value
    ]
    for block in candidate_blocks[:40]:
        text = (block.text or "").strip()
        if not text:
            continue
        block_norm = _normalize_for_match(text)
        if any(value and value in block_norm for value in normalized_values):
            matches.add(block.index)
            continue
        if _TIME_KEYWORDS_RE.search(text) and _TIME_VALUE_RE.search(text):
            if _block_role(block) != "instruction_line":
                matches.add(block.index)
    return matches


def is_howto_section_text(text: str) -> bool:
    stripped = str(text or "").strip().strip(":").strip()
    if not stripped or len(stripped) > 90:
        return False
    if _INSTRUCTION_PREFIX_RE.match(stripped) or _HOWTO_SENTENCE_END_RE.search(stripped):
        return False
    lowered = stripped.lower()
    if lowered.startswith(("for ", "to ")):
        return True
    if _YIELD_KEYWORDS_RE.search(stripped) or _TIME_KEYWORDS_RE.search(stripped):
        return False
    words = _HOWTO_WORD_RE.findall(stripped)
    if not words or len(words) > 8:
        return False
    if len(words) == 1 and _HOWTO_ALL_CAPS_RE.fullmatch(stripped):
        return False
    return True


def _has_nearby_structural_signal(
    block_index: int,
    structural_signal_indices: set[int],
    *,
    max_distance: int,
) -> bool:
    return any(
        candidate_index != block_index and abs(candidate_index - block_index) <= max_distance
        for candidate_index in structural_signal_indices
    )


def _filter_howto_section_indices(
    *,
    indices: set[int],
    candidate_blocks: list[ArchiveBlockView],
    structural_signal_indices: set[int],
) -> set[int]:
    if not indices:
        return set()
    block_by_index = {block.index: block for block in candidate_blocks}
    accepted: set[int] = set()
    for index in sorted(indices):
        block = block_by_index.get(index)
        if block is None or not is_howto_section_text(block.text):
            continue
        if not _has_nearby_structural_signal(index, structural_signal_indices, max_distance=3):
            continue
        accepted.add(index)
    return accepted


def _match_texts_to_block_indices(
    rows: list[str],
    candidate_blocks: list[ArchiveBlockView],
    *,
    preferred_roles: set[str] | None = None,
) -> set[int]:
    if not rows:
        return set()
    normalized_rows = [_normalize_for_match(row) for row in rows if row and row.strip()]
    normalized_rows = [row for row in normalized_rows if row]
    if not normalized_rows:
        return set()

    exact_index_by_text: dict[str, list[int]] = {}
    normalized_preferred_roles = {
        str(role or "").strip().lower()
        for role in (preferred_roles or set())
        if str(role or "").strip()
    }
    role_by_index: dict[int, str] = {}
    for block in candidate_blocks:
        block_norm = _normalize_for_match(block.text)
        if not block_norm:
            continue
        exact_index_by_text.setdefault(block_norm, []).append(block.index)
        if normalized_preferred_roles:
            role_by_index[block.index] = _block_role(block)

    used_indices: set[int] = set()
    matched: set[int] = set()
    for row in normalized_rows:
        exact_indices = exact_index_by_text.get(row, [])
        chosen_exact = _pick_first_unmatched(
            exact_indices,
            used_indices,
            preferred_roles=normalized_preferred_roles if normalized_preferred_roles else None,
            role_by_index=role_by_index if normalized_preferred_roles else None,
        )
        if chosen_exact is not None:
            used_indices.add(chosen_exact)
            matched.add(chosen_exact)
            continue
        fuzzy_candidates: list[int] = []
        for block in candidate_blocks:
            block_norm = _normalize_for_match(block.text)
            if not block_norm:
                continue
            if len(row) >= 12 and row in block_norm:
                fuzzy_candidates.append(block.index)
                continue
            if len(block_norm) >= 12 and block_norm in row:
                fuzzy_candidates.append(block.index)
        chosen_fuzzy = _pick_first_unmatched(
            fuzzy_candidates,
            used_indices,
            preferred_roles=normalized_preferred_roles if normalized_preferred_roles else None,
            role_by_index=role_by_index if normalized_preferred_roles else None,
        )
        if chosen_fuzzy is not None:
            used_indices.add(chosen_fuzzy)
            matched.add(chosen_fuzzy)
    return matched


def _pick_first_unmatched(
    candidates: Iterable[int],
    used: set[int],
    *,
    preferred_roles: set[str] | None = None,
    role_by_index: dict[int, str] | None = None,
) -> int | None:
    fallback: int | None = None
    for idx in candidates:
        if idx in used:
            continue
        if fallback is None:
            fallback = idx
        if not preferred_roles or role_by_index is None:
            continue
        if role_by_index.get(idx, "") in preferred_roles:
            return idx
    return fallback
