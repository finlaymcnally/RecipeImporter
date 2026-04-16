from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from cookimport.core.models import AuthoritativeRecipeSemantics, ConversionResult, HowToStep, RecipeCandidate, RecipeComment
from cookimport.labelstudio.archive import build_extracted_archive, normalize_display_text
from cookimport.parsing.label_source_of_truth import AuthoritativeBlockLabel
from cookimport.parsing.canonical_line_roles.contracts import RECIPE_LOCAL_LINE_ROLE_LABELS
from cookimport.parsing.sections import (
    extract_ingredient_sections,
    extract_instruction_sections,
)
from cookimport.parsing.tips import extract_recipe_specific_notes
from cookimport.staging.recipe_authority_decisions import RecipeAuthorityDecision
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
class ArchiveRowView:
    index: int
    text: str
    location: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RecipeRowEvidence:
    archive_rows: list[ArchiveRowView]
    row_count: int
    row_labels: dict[int, set[str]]
    unresolved_recipe_owned_indices: list[int]
    unresolved_recipe_owned_recipe_id_by_index: dict[int, str]
    unresolved_exact_evidence: list[dict[str, Any]]
    notes: list[str]


def load_stage_prediction_archive_rows(
    conversion_result: ConversionResult,
    archive_blocks: Iterable[dict[str, Any]] | None,
) -> list[ArchiveRowView]:
    if archive_blocks is None:
        archive_payload = build_extracted_archive(
            conversion_result,
            conversion_result.raw_artifacts,
        )
        return sorted(
            [
                ArchiveRowView(
                    index=int(block.index),
                    text=str(block.text or ""),
                    location=dict(block.location or {}),
                )
                for block in archive_payload
            ],
            key=lambda block: block.index,
        )

    rows: list[ArchiveRowView] = []
    for fallback_index, payload in enumerate(archive_blocks):
        if not isinstance(payload, dict):
            continue
        raw_index = payload.get("index")
        try:
            row_index = int(raw_index)
        except (TypeError, ValueError):
            row_index = fallback_index
        location = payload.get("location")
        if not isinstance(location, dict):
            location = {
                key: value
                for key, value in payload.items()
                if key not in {"index", "text"}
            }
        rows.append(
            ArchiveRowView(
                index=row_index,
                text=str(payload.get("text") or ""),
                location=dict(location),
            )
        )
    return sorted(rows, key=lambda row: row.index)


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


def build_recipe_row_evidence(
    conversion_result: ConversionResult,
    *,
    archive_rows: list[ArchiveRowView],
    recipe_ownership_result: RecipeOwnershipResult,
    authoritative_payloads_by_recipe_id: Mapping[str, AuthoritativeRecipeSemantics | dict[str, Any]] | None = None,
    recipe_authority_decisions_by_recipe_id: Mapping[str, RecipeAuthorityDecision | Mapping[str, Any]] | None = None,
    boundary_labels: Iterable[AuthoritativeBlockLabel] | None = None,
) -> RecipeRowEvidence:
    notes: list[str] = []
    max_index = max((row.index for row in archive_rows), default=-1)
    row_count = max_index + 1 if max_index >= 0 else 0
    row_labels: dict[int, set[str]] = {index: set() for index in range(row_count)}
    archive_rows_by_index = {row.index: row for row in archive_rows}
    conversion_recipes_by_id = {
        _require_recipe_id(recipe): recipe for recipe in conversion_result.recipes
    }
    authoritative_payload_rows = {
        str(recipe_id).strip(): _coerce_authoritative_payload(payload)
        for recipe_id, payload in (authoritative_payloads_by_recipe_id or {}).items()
        if str(recipe_id).strip()
    }
    decision_rows = {
        str(recipe_id).strip(): _coerce_recipe_authority_decision(decision)
        for recipe_id, decision in (recipe_authority_decisions_by_recipe_id or {}).items()
        if str(recipe_id).strip()
    }
    boundary_labels_by_index = {
        int(row.source_block_index): str(row.final_label or "").strip()
        for row in (boundary_labels or [])
    }
    unresolved_recipe_owned_indices: set[int] = set()
    unresolved_recipe_owned_recipe_id_by_index: dict[int, str] = {}
    unresolved_exact_evidence: list[dict[str, Any]] = []

    for ownership_entry in recipe_ownership_result.recipe_entries:
        recipe_id = str(ownership_entry.recipe_id).strip()
        if not recipe_id or not ownership_entry.owned_row_indices:
            continue
        recipe_payload = authoritative_payload_rows.get(recipe_id)
        recipe = (
            _recipe_candidate_from_authoritative_payload(recipe_payload)
            if recipe_payload is not None
            else conversion_recipes_by_id.get(recipe_id)
        )
        if recipe is not None:
            _label_recipe_rows(
                recipe,
                archive_rows_by_index=archive_rows_by_index,
                owned_row_indices=ownership_entry.owned_row_indices,
                row_labels=row_labels,
                unresolved_exact_evidence=unresolved_exact_evidence,
                notes=notes,
            )
            continue
        labeled_from_boundary = _label_recipe_rows_from_boundary_labels(
            recipe_id=recipe_id,
            owned_row_indices=ownership_entry.owned_row_indices,
            boundary_labels_by_index=boundary_labels_by_index,
            row_labels=row_labels,
            notes=notes,
        )
        if labeled_from_boundary:
            continue
        decision = decision_rows.get(recipe_id)
        for row_index in ownership_entry.owned_row_indices:
            unresolved_recipe_owned_indices.add(int(row_index))
            unresolved_recipe_owned_recipe_id_by_index[int(row_index)] = recipe_id
        notes.append(
            "Recipe-owned rows remained withheld without recipe-local evidence: "
            f"{recipe_id} ({getattr(decision, 'publish_status', 'unknown') or 'unknown'})."
        )
    return RecipeRowEvidence(
        archive_rows=archive_rows,
        row_count=row_count,
        row_labels=row_labels,
        unresolved_recipe_owned_indices=sorted(unresolved_recipe_owned_indices),
        unresolved_recipe_owned_recipe_id_by_index=unresolved_recipe_owned_recipe_id_by_index,
        unresolved_exact_evidence=unresolved_exact_evidence,
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
    archive: list[ArchiveRowView],
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


def _label_recipe_rows(
    recipe: RecipeCandidate,
    *,
    archive_rows_by_index: dict[int, ArchiveRowView],
    owned_row_indices: list[int],
    row_labels: dict[int, set[str]],
    unresolved_exact_evidence: list[dict[str, Any]],
    notes: list[str],
) -> None:
    recipe_id = _require_recipe_id(recipe)
    if not owned_row_indices:
        notes.append(
            f"Recipe '{recipe.name}' ({recipe_id}) owns no rows; skipped recipe-local labeling."
        )
        return
    candidate_rows: list[ArchiveRowView] = []
    missing_row_indices: list[int] = []
    for row_index in owned_row_indices:
        row = archive_rows_by_index.get(int(row_index))
        if row is None:
            missing_row_indices.append(int(row_index))
            continue
        candidate_rows.append(row)
    if missing_row_indices:
        raise RecipeOwnershipInvariantError(
            f"Recipe '{recipe_id}' owns missing archive rows: {missing_row_indices}."
        )

    title_index = _find_title_row_index(recipe, candidate_rows)
    if title_index is not None:
        _mark_row_label(row_labels, title_index, "RECIPE_TITLE")
    elif str(recipe.name or "").strip():
        _record_unresolved_exact_evidence(
            unresolved_exact_evidence,
            recipe_id=recipe_id,
            label="RECIPE_TITLE",
            value=str(recipe.name or "").strip(),
        )

    ingredient_indices = _match_texts_to_row_indices(
        _ingredient_texts(recipe),
        candidate_rows,
        preferred_roles={"ingredient_line", "section_heading"},
    )
    for idx in ingredient_indices:
        _mark_row_label(row_labels, idx, "INGREDIENT_LINE")

    instruction_indices = _match_texts_to_row_indices(
        _instruction_texts(recipe),
        candidate_rows,
        preferred_roles={"instruction_line", "section_heading"},
    )
    for idx in instruction_indices:
        _mark_row_label(row_labels, idx, "INSTRUCTION_LINE")

    ingredient_role_indices = {
        row.index for row in candidate_rows if _block_role(row) == "ingredient_line"
    }
    instruction_role_indices = {
        row.index for row in candidate_rows if _block_role(row) == "instruction_line"
    }
    howto_header_rows = _ingredient_section_header_texts(recipe)
    howto_header_rows.extend(_instruction_section_header_texts(recipe))
    howto_indices = _match_texts_to_row_indices(
        howto_header_rows,
        candidate_rows,
        preferred_roles={"ingredient_line", "instruction_line", "section_heading"},
    )
    howto_indices = _filter_howto_section_indices(
        indices=howto_indices,
        candidate_rows=candidate_rows,
        structural_signal_indices=(
            ingredient_indices
            | instruction_indices
            | ingredient_role_indices
            | instruction_role_indices
        ),
    )
    for idx in howto_indices:
        _mark_row_label(row_labels, idx, "HOWTO_SECTION")

    for idx in _match_texts_to_row_indices(_note_texts(recipe), candidate_rows):
        _mark_row_label(row_labels, idx, "RECIPE_NOTES")

    variant_texts = _variant_texts(recipe)
    variant_indices = _match_texts_to_row_indices(variant_texts, candidate_rows)
    if not variant_indices and variant_texts:
        for row in candidate_rows:
            if _is_variant_text(row.text):
                variant_indices.add(row.index)
    row_position_by_index = {
        row.index: position for position, row in enumerate(candidate_rows)
    }
    row_by_index = {row.index: row for row in candidate_rows}
    variant_indices = {
        index
        for index in variant_indices
        if (
            (row := row_by_index.get(index)) is not None
            and (position := row_position_by_index.get(index)) is not None
            and _is_valid_title_or_variant_candidate(
                row,
                candidate_rows=candidate_rows,
                candidate_position=position,
                kind="variant",
            )
        )
    }
    for idx in variant_indices:
        _mark_row_label(row_labels, idx, "RECIPE_VARIANT")
    if variant_texts and not variant_indices:
        for text in _dedupe_text_rows(list(variant_texts)):
            _record_unresolved_exact_evidence(
                unresolved_exact_evidence,
                recipe_id=recipe_id,
                label="RECIPE_VARIANT",
                value=text,
            )

    yield_indices = _find_yield_row_indices(recipe, candidate_rows)
    for idx in yield_indices:
        _mark_row_label(row_labels, idx, "YIELD_LINE")
    if str(recipe.recipe_yield or "").strip() and not yield_indices:
        _record_unresolved_exact_evidence(
            unresolved_exact_evidence,
            recipe_id=recipe_id,
            label="YIELD_LINE",
            value=str(recipe.recipe_yield or "").strip(),
        )
    time_indices = _find_time_row_indices(recipe, candidate_rows)
    for idx in time_indices:
        _mark_row_label(row_labels, idx, "TIME_LINE")
    time_values = [
        str(value).strip()
        for value in (recipe.prep_time, recipe.cook_time, recipe.total_time)
        if value is not None and str(value).strip()
    ]
    if time_values and not time_indices:
        for value in _dedupe_text_rows(time_values):
            _record_unresolved_exact_evidence(
                unresolved_exact_evidence,
                recipe_id=recipe_id,
                label="TIME_LINE",
                value=value,
            )

    if not ingredient_indices:
        for row in candidate_rows:
            if _block_role(row) == "ingredient_line":
                _mark_row_label(row_labels, row.index, "INGREDIENT_LINE")
    if not instruction_indices:
        for row in candidate_rows:
            if _block_role(row) == "instruction_line":
                _mark_row_label(row_labels, row.index, "INSTRUCTION_LINE")

    if title_index is not None:
        existing = row_labels.get(title_index)
        if existing is not None:
            existing.discard("INGREDIENT_LINE")
            existing.discard("INSTRUCTION_LINE")


def _mark_row_label(row_labels: dict[int, set[str]], row_index: int, label: str) -> None:
    if row_index < 0:
        return
    row_labels.setdefault(row_index, set()).add(label)


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


def _coerce_authoritative_payload(
    payload: AuthoritativeRecipeSemantics | Mapping[str, Any],
) -> AuthoritativeRecipeSemantics:
    if isinstance(payload, AuthoritativeRecipeSemantics):
        return payload
    return AuthoritativeRecipeSemantics.model_validate(payload)


def _coerce_recipe_authority_decision(
    decision: RecipeAuthorityDecision | Mapping[str, Any],
) -> RecipeAuthorityDecision:
    if isinstance(decision, RecipeAuthorityDecision):
        return decision
    return RecipeAuthorityDecision(
        recipe_id=str(decision.get("recipe_id") or "").strip(),
        semantic_outcome=str(decision.get("semantic_outcome") or "").strip(),
        publish_status=str(decision.get("publish_status") or "").strip(),
        ownership_action=str(decision.get("ownership_action") or "").strip(),
        owned_block_indices=[int(value) for value in decision.get("owned_block_indices") or []],
        divested_block_indices=[int(value) for value in decision.get("divested_block_indices") or []],
        retained_block_indices=[int(value) for value in decision.get("retained_block_indices") or []],
        worker_repair_status=str(decision.get("worker_repair_status") or "").strip() or None,
        status_reason=str(decision.get("status_reason") or "").strip() or None,
        single_correction_status=str(decision.get("single_correction_status") or "").strip() or None,
        final_assembly_status=str(decision.get("final_assembly_status") or "").strip() or None,
        structural_status=str(decision.get("structural_status") or "").strip() or None,
        structural_reason_codes=[str(value).strip() for value in decision.get("structural_reason_codes") or [] if str(value).strip()],
        mapping_status=str(decision.get("mapping_status") or "").strip() or None,
        mapping_reason=str(decision.get("mapping_reason") or "").strip() or None,
        final_recipe_authority_status=str(decision.get("final_recipe_authority_status") or "").strip() or None,
        final_recipe_authority_reason=str(decision.get("final_recipe_authority_reason") or "").strip() or None,
    )


def _recipe_candidate_from_authoritative_payload(
    payload: AuthoritativeRecipeSemantics,
) -> RecipeCandidate:
    return RecipeCandidate(
        name=payload.title,
        identifier=payload.recipe_id,
        recipeIngredient=list(payload.ingredients),
        recipeInstructions=list(payload.instructions),
        description=payload.description,
        recipeYield=payload.recipe_yield,
        comment=[RecipeComment(text=text) for text in payload.notes],
        tags=list(payload.tags),
        provenance=dict(payload.provenance),
        source=payload.source,
    )


def _label_recipe_rows_from_boundary_labels(
    *,
    recipe_id: str,
    owned_row_indices: list[int],
    boundary_labels_by_index: Mapping[int, str],
    row_labels: dict[int, set[str]],
    notes: list[str],
) -> bool:
    labeled_indices: list[int] = []
    for row_index in owned_row_indices:
        label = str(boundary_labels_by_index.get(int(row_index)) or "").strip()
        if label not in RECIPE_LOCAL_LINE_ROLE_LABELS:
            continue
        _mark_row_label(row_labels, int(row_index), label)
        labeled_indices.append(int(row_index))
    if not labeled_indices:
        return False
    notes.append(
        "Recipe-local stage evidence fell back to boundary labels for withheld recipe "
        f"{recipe_id} ({len(labeled_indices)} rows)."
    )
    return True


def _normalize_for_match(text: str) -> str:
    normalized = normalize_display_text(text).lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9 ]+", "", normalized)
    return normalized.strip()


def _normalize_title_for_match(text: str) -> str:
    stripped = str(text or "").strip()
    lowered = stripped.lower()
    if lowered.startswith("title:"):
        stripped = stripped.split(":", 1)[1].strip()
    return _normalize_for_match(stripped)


def _match_archive_indices_for_line_range(
    archive: list[ArchiveRowView],
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


def _block_features(block: ArchiveRowView) -> dict[str, Any]:
    location = block.location if isinstance(block.location, dict) else {}
    features = location.get("features")
    return features if isinstance(features, dict) else {}


def _block_role(block: ArchiveRowView) -> str:
    features = _block_features(block)
    role = features.get("block_role")
    if role is None:
        role = block.location.get("block_role") if isinstance(block.location, dict) else None
    return str(role or "").strip().lower()


def _block_has_recipe_boundary_signal(block: ArchiveRowView) -> bool:
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
    candidate_rows: list[ArchiveRowView],
    kind: str,
) -> bool:
    upper = min(len(candidate_rows), candidate_position + (4 if kind == "title" else 3) + 1)
    for position in range(candidate_position + 1, upper):
        if _block_has_recipe_boundary_signal(candidate_rows[position]):
            return True
    if kind == "variant":
        lower = max(0, candidate_position - 2)
        for position in range(lower, candidate_position):
            if _block_has_recipe_boundary_signal(candidate_rows[position]):
                return True
    return False


def _is_valid_title_or_variant_candidate(
    block: ArchiveRowView,
    *,
    candidate_rows: list[ArchiveRowView],
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
        candidate_rows=candidate_rows,
        kind=kind,
    )


def _find_title_row_index(
    recipe: RecipeCandidate,
    candidate_rows: list[ArchiveRowView],
) -> int | None:
    recipe_name = (recipe.name or "").strip()
    target = _normalize_title_for_match(recipe_name) if recipe_name else ""
    if target:
        for position, block in enumerate(candidate_rows[:60]):
            if _normalize_title_for_match(block.text) == target and _is_valid_title_or_variant_candidate(
                block,
                candidate_rows=candidate_rows,
                candidate_position=position,
                kind="title",
            ):
                return block.index
    role_matches = [
        block.index
        for position, block in enumerate(candidate_rows[:20])
        if _block_role(block) == "recipe_title"
        and _is_valid_title_or_variant_candidate(
            block,
            candidate_rows=candidate_rows,
            candidate_position=position,
            kind="title",
        )
    ]
    if len(role_matches) == 1:
        return role_matches[0]
    return None


def _find_yield_row_indices(
    recipe: RecipeCandidate,
    candidate_rows: list[ArchiveRowView],
) -> set[int]:
    matches: set[int] = set()
    recipe_yield = (recipe.recipe_yield or "").strip()
    if recipe_yield:
        target = _normalize_for_match(recipe_yield)
        for block in candidate_rows[:30]:
            block_norm = _normalize_for_match(block.text)
            if block_norm and target and (target in block_norm or block_norm in target):
                matches.add(block.index)
    if matches:
        return matches
    role_matches = {
        block.index for block in candidate_rows[:30] if _block_role(block) == "yield_line"
    }
    if role_matches:
        return role_matches
    keyword_matches = {
        block.index
        for block in candidate_rows[:30]
        if (text := (block.text or "").strip())
        and _YIELD_KEYWORDS_RE.search(text)
        and _block_role(block) != "instruction_line"
    }
    if len(keyword_matches) == 1:
        return keyword_matches
    return set()


def _find_time_row_indices(
    recipe: RecipeCandidate,
    candidate_rows: list[ArchiveRowView],
) -> set[int]:
    matches: set[int] = set()
    normalized_values = [
        _normalize_for_match(str(value).strip())
        for value in (recipe.prep_time, recipe.cook_time, recipe.total_time)
        if value
    ]
    for block in candidate_rows[:40]:
        text = (block.text or "").strip()
        if not text:
            continue
        block_norm = _normalize_for_match(text)
        if any(value and value in block_norm for value in normalized_values):
            matches.add(block.index)
            continue
    if matches:
        return matches
    role_matches = {
        block.index for block in candidate_rows[:40] if _block_role(block) == "time_line"
    }
    if role_matches:
        return role_matches
    keyword_matches = {
        block.index
        for block in candidate_rows[:40]
        if (text := (block.text or "").strip())
        and _TIME_KEYWORDS_RE.search(text)
        and _TIME_VALUE_RE.search(text)
        and _block_role(block) != "instruction_line"
    }
    if len(keyword_matches) == 1:
        return keyword_matches
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
    candidate_rows: list[ArchiveRowView],
    structural_signal_indices: set[int],
) -> set[int]:
    if not indices:
        return set()
    block_by_index = {block.index: block for block in candidate_rows}
    accepted: set[int] = set()
    for index in sorted(indices):
        block = block_by_index.get(index)
        if block is None or not is_howto_section_text(block.text):
            continue
        if not _has_nearby_structural_signal(index, structural_signal_indices, max_distance=3):
            continue
        accepted.add(index)
    return accepted


def _match_texts_to_row_indices(
    rows: list[str],
    candidate_rows: list[ArchiveRowView],
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
    for block in candidate_rows:
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
    return matched


def _record_unresolved_exact_evidence(
    unresolved_exact_evidence: list[dict[str, Any]],
    *,
    recipe_id: str,
    label: str,
    value: str,
) -> None:
    rendered_value = str(value or "").strip()
    if not rendered_value:
        return
    unresolved_exact_evidence.append(
        {
            "recipe_id": str(recipe_id).strip(),
            "label": str(label).strip(),
            "value": rendered_value,
        }
    )


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
