from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from cookimport.core.models import ConversionResult, HowToStep, RecipeCandidate
from cookimport.labelstudio.archive import build_extracted_archive, normalize_display_text

FREEFORM_LABELS: tuple[str, ...] = (
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "YIELD_LINE",
    "TIME_LINE",
    "RECIPE_NOTES",
    "RECIPE_VARIANT",
    "KNOWLEDGE",
    "OTHER",
)

_LABEL_RESOLUTION_PRIORITY: tuple[str, ...] = (
    "RECIPE_VARIANT",
    "RECIPE_TITLE",
    "YIELD_LINE",
    "TIME_LINE",
    "INGREDIENT_LINE",
    "RECIPE_NOTES",
    "INSTRUCTION_LINE",
    "KNOWLEDGE",
)

_RECIPE_LOCAL_LABELS: set[str] = {
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "YIELD_LINE",
    "TIME_LINE",
    "RECIPE_NOTES",
    "RECIPE_VARIANT",
}

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


class _ArchiveBlockView:
    __slots__ = ("index", "text", "location")

    def __init__(self, *, index: int, text: str, location: dict[str, Any]) -> None:
        self.index = index
        self.text = text
        self.location = location


def build_stage_block_predictions(
    conversion_result: ConversionResult,
    workbook_slug: str,
    *,
    source_file: str | None = None,
    source_hash: str | None = None,
    archive_blocks: Iterable[dict[str, Any]] | None = None,
    knowledge_snippets_path: Path | None = None,
) -> dict[str, Any]:
    """Build a deterministic per-block label manifest from staged outputs."""
    archive = _load_archive(conversion_result, archive_blocks)
    notes: list[str] = []

    max_index = max((block.index for block in archive), default=-1)
    block_count = max_index + 1 if max_index >= 0 else 0
    block_labels: dict[int, set[str]] = {index: set() for index in range(block_count)}
    for recipe in conversion_result.recipes:
        _label_recipe_blocks(
            recipe,
            archive=archive,
            block_labels=block_labels,
            notes=notes,
        )

    knowledge_indices = _load_knowledge_indices(knowledge_snippets_path)
    if knowledge_indices and block_count == 0:
        notes.append("Knowledge snippets were present but no extracted archive blocks were available.")
    for block_index in sorted(knowledge_indices):
        if block_index < 0 or block_index >= block_count:
            notes.append(
                f"Knowledge snippet referenced out-of-range block {block_index}; ignored."
            )
            continue
        block_labels.setdefault(block_index, set()).add("KNOWLEDGE")

    if not _contains_label(block_labels, "TIME_LINE"):
        notes.append("TIME_LINE was not detected in stage evidence.")
    if not _contains_label(block_labels, "YIELD_LINE"):
        notes.append("YIELD_LINE was not detected in stage evidence.")

    conflicts: list[dict[str, Any]] = []
    resolved: dict[int, str] = {}
    for block_index in range(block_count):
        labels = sorted(label for label in block_labels.get(block_index, set()) if label != "OTHER")
        if len(labels) > 1:
            conflicts.append(
                {
                    "block_index": block_index,
                    "labels": labels,
                }
            )
        resolved[block_index] = _resolve_block_label(labels)

    label_blocks: dict[str, list[int]] = {label: [] for label in FREEFORM_LABELS}
    for block_index in range(block_count):
        label = resolved.get(block_index, "OTHER")
        label_blocks.setdefault(label, []).append(block_index)

    normalized_source_file = source_file or _resolve_source_file(conversion_result)
    normalized_source_hash = source_hash or _resolve_source_hash(conversion_result)

    return {
        "schema_version": "stage_block_predictions.v1",
        "source_file": normalized_source_file,
        "source_hash": normalized_source_hash,
        "workbook_slug": workbook_slug,
        "block_count": block_count,
        "block_labels": {str(index): resolved.get(index, "OTHER") for index in range(block_count)},
        "label_blocks": {
            label: sorted(indices)
            for label, indices in label_blocks.items()
        },
        "conflicts": conflicts,
        "notes": sorted(set(note for note in notes if note)),
    }


def _load_archive(
    conversion_result: ConversionResult,
    archive_blocks: Iterable[dict[str, Any]] | None,
) -> list[_ArchiveBlockView]:
    if archive_blocks is None:
        archive_payload = build_extracted_archive(
            conversion_result,
            conversion_result.raw_artifacts,
        )
        blocks: list[_ArchiveBlockView] = []
        for block in archive_payload:
            blocks.append(
                _ArchiveBlockView(
                    index=int(block.index),
                    text=str(block.text or ""),
                    location=dict(block.location or {}),
                )
            )
        return sorted(blocks, key=lambda block: block.index)

    blocks = []
    for fallback_index, payload in enumerate(archive_blocks):
        if not isinstance(payload, dict):
            continue
        raw_index = payload.get("index")
        try:
            block_index = int(raw_index)
        except (TypeError, ValueError):
            block_index = fallback_index
        text = str(payload.get("text") or "")
        location = payload.get("location")
        if not isinstance(location, dict):
            location = {
                key: value
                for key, value in payload.items()
                if key not in {"index", "text"}
            }
        blocks.append(
            _ArchiveBlockView(
                index=block_index,
                text=text,
                location=dict(location),
            )
        )
    return sorted(blocks, key=lambda block: block.index)


def _resolve_source_file(conversion_result: ConversionResult) -> str:
    if conversion_result.workbook_path:
        return str(conversion_result.workbook_path)
    if conversion_result.source:
        return str(conversion_result.source)
    if conversion_result.workbook:
        return str(conversion_result.workbook)
    return ""


def _resolve_source_hash(conversion_result: ConversionResult) -> str:
    for artifact in conversion_result.raw_artifacts:
        if artifact.source_hash:
            return str(artifact.source_hash)
    for recipe in conversion_result.recipes:
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        source_hash = provenance.get("file_hash") or provenance.get("fileHash")
        if source_hash:
            return str(source_hash)
    return "unknown"


def _contains_label(block_labels: dict[int, set[str]], target_label: str) -> bool:
    for labels in block_labels.values():
        if target_label in labels:
            return True
    return False


def _resolve_recipe_range(recipe: RecipeCandidate) -> tuple[int | None, int | None]:
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
        return None, None
    if start is None:
        start = end
    if end is None:
        end = start
    if start is None or end is None:
        return None, None
    if start > end:
        start, end = end, start
    return start, end


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _label_recipe_blocks(
    recipe: RecipeCandidate,
    *,
    archive: list[_ArchiveBlockView],
    block_labels: dict[int, set[str]],
    notes: list[str],
) -> None:
    start, end = _resolve_recipe_range(recipe)
    if start is None or end is None:
        notes.append(
            f"Recipe '{recipe.name}' lacked block-range provenance; skipped recipe-local labeling."
        )
        return

    candidate_blocks = [
        block for block in archive if start <= block.index <= end
    ]
    if not candidate_blocks:
        notes.append(
            f"Recipe '{recipe.name}' range {start}-{end} had no archive blocks."
        )
        return

    title_index = _find_title_block_index(recipe, candidate_blocks)
    if title_index is not None:
        _mark_label(block_labels, title_index, "RECIPE_TITLE")

    ingredient_indices = _match_texts_to_block_indices(
        _ingredient_texts(recipe),
        candidate_blocks,
    )
    for idx in ingredient_indices:
        _mark_label(block_labels, idx, "INGREDIENT_LINE")

    instruction_indices = _match_texts_to_block_indices(
        _instruction_texts(recipe),
        candidate_blocks,
    )
    for idx in instruction_indices:
        _mark_label(block_labels, idx, "INSTRUCTION_LINE")

    note_indices = _match_texts_to_block_indices(
        _note_texts(recipe),
        candidate_blocks,
    )
    for idx in note_indices:
        _mark_label(block_labels, idx, "RECIPE_NOTES")

    variant_texts = _variant_texts(recipe)
    variant_indices = _match_texts_to_block_indices(
        variant_texts,
        candidate_blocks,
    )
    if not variant_indices and variant_texts:
        for block in candidate_blocks:
            if _is_variant_text(block.text):
                variant_indices.add(block.index)
    for idx in variant_indices:
        _mark_label(block_labels, idx, "RECIPE_VARIANT")

    yield_indices = _find_yield_block_indices(recipe, candidate_blocks)
    for idx in yield_indices:
        _mark_label(block_labels, idx, "YIELD_LINE")

    time_indices = _find_time_block_indices(recipe, candidate_blocks)
    for idx in time_indices:
        _mark_label(block_labels, idx, "TIME_LINE")

    # Fill in structural ingredient/instruction hints if explicit text matching failed.
    if not ingredient_indices:
        for block in candidate_blocks:
            role = _block_role(block)
            if role == "ingredient_line":
                _mark_label(block_labels, block.index, "INGREDIENT_LINE")
    if not instruction_indices:
        for block in candidate_blocks:
            role = _block_role(block)
            if role == "instruction_line":
                _mark_label(block_labels, block.index, "INSTRUCTION_LINE")

    # Avoid classifying title line as instruction/ingredient by mistake.
    if title_index is not None:
        existing = block_labels.get(title_index)
        if existing is not None:
            existing.discard("INGREDIENT_LINE")
            existing.discard("INSTRUCTION_LINE")


def _mark_label(block_labels: dict[int, set[str]], block_index: int, label: str) -> None:
    if label not in FREEFORM_LABELS:
        return
    if block_index < 0:
        return
    labels = block_labels.setdefault(block_index, set())
    labels.add(label)


def _normalize_for_match(text: str) -> str:
    normalized = normalize_display_text(text)
    normalized = normalized.lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9 ]+", "", normalized)
    return normalized.strip()


def _ingredient_texts(recipe: RecipeCandidate) -> list[str]:
    return [str(value or "") for value in recipe.ingredients if str(value or "").strip()]


def _instruction_texts(recipe: RecipeCandidate) -> list[str]:
    texts: list[str] = []
    for item in recipe.instructions:
        if isinstance(item, HowToStep):
            text = item.text
        else:
            text = str(item)
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
    return rows


def _variant_texts(recipe: RecipeCandidate) -> list[str]:
    variants: list[str] = []
    for text in _instruction_texts(recipe):
        if _is_variant_text(text):
            variants.append(text)
    return variants


def _is_variant_text(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    return bool(_VARIANT_HEADER_RE.match(stripped) or _VARIANT_PREFIX_RE.match(stripped))


def _find_title_block_index(
    recipe: RecipeCandidate,
    candidate_blocks: list[_ArchiveBlockView],
) -> int | None:
    recipe_name = (recipe.name or "").strip()
    if not recipe_name:
        return candidate_blocks[0].index if candidate_blocks else None

    target = _normalize_for_match(recipe_name)
    if target:
        for block in candidate_blocks[:60]:
            if _normalize_for_match(block.text) == target:
                return block.index
        for block in candidate_blocks[:60]:
            block_norm = _normalize_for_match(block.text)
            if not block_norm:
                continue
            if target in block_norm or block_norm in target:
                return block.index

    best: tuple[int, int] | None = None
    start_index = candidate_blocks[0].index
    for block in candidate_blocks[:20]:
        text = (block.text or "").strip()
        if not text or len(text) > 140:
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
    if best is not None and best[0] > 0:
        return best[1]
    return candidate_blocks[0].index if candidate_blocks else None


def _find_yield_block_indices(
    recipe: RecipeCandidate,
    candidate_blocks: list[_ArchiveBlockView],
) -> set[int]:
    matches: set[int] = set()
    recipe_yield = (recipe.recipe_yield or "").strip()
    if recipe_yield:
        target = _normalize_for_match(recipe_yield)
        for block in candidate_blocks[:30]:
            block_norm = _normalize_for_match(block.text)
            if not block_norm:
                continue
            if target and (target in block_norm or block_norm in target):
                matches.add(block.index)

    if matches:
        return matches

    for block in candidate_blocks[:30]:
        text = (block.text or "").strip()
        if not text:
            continue
        if _YIELD_KEYWORDS_RE.search(text):
            role = _block_role(block)
            if role != "instruction_line":
                matches.add(block.index)
    return matches


def _find_time_block_indices(
    recipe: RecipeCandidate,
    candidate_blocks: list[_ArchiveBlockView],
) -> set[int]:
    matches: set[int] = set()
    candidate_time_values = [
        str(value).strip()
        for value in (recipe.prep_time, recipe.cook_time, recipe.total_time)
        if value
    ]
    normalized_values = [_normalize_for_match(value) for value in candidate_time_values]

    for block in candidate_blocks[:40]:
        text = (block.text or "").strip()
        if not text:
            continue
        block_norm = _normalize_for_match(text)
        if any(value and value in block_norm for value in normalized_values):
            matches.add(block.index)
            continue
        if _TIME_KEYWORDS_RE.search(text) and _TIME_VALUE_RE.search(text):
            role = _block_role(block)
            if role != "instruction_line":
                matches.add(block.index)

    return matches


def _block_features(block: _ArchiveBlockView) -> dict[str, Any]:
    location = block.location if isinstance(block.location, dict) else {}
    features = location.get("features")
    if isinstance(features, dict):
        return features
    return {}


def _block_role(block: _ArchiveBlockView) -> str:
    features = _block_features(block)
    role = features.get("block_role")
    if role is None:
        role = block.location.get("block_role") if isinstance(block.location, dict) else None
    return str(role or "").strip().lower()


def _match_texts_to_block_indices(
    rows: list[str],
    candidate_blocks: list[_ArchiveBlockView],
) -> set[int]:
    if not rows:
        return set()

    normalized_rows = [_normalize_for_match(row) for row in rows if row and row.strip()]
    normalized_rows = [row for row in normalized_rows if row]
    if not normalized_rows:
        return set()

    exact_index_by_text: dict[str, list[int]] = {}
    for block in candidate_blocks:
        block_norm = _normalize_for_match(block.text)
        if not block_norm:
            continue
        exact_index_by_text.setdefault(block_norm, []).append(block.index)

    used_indices: set[int] = set()
    matched: set[int] = set()

    for row in normalized_rows:
        exact_indices = exact_index_by_text.get(row, [])
        chosen_exact = _pick_first_unmatched(exact_indices, used_indices)
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
        chosen_fuzzy = _pick_first_unmatched(fuzzy_candidates, used_indices)
        if chosen_fuzzy is not None:
            used_indices.add(chosen_fuzzy)
            matched.add(chosen_fuzzy)

    return matched


def _pick_first_unmatched(candidates: Iterable[int], used: set[int]) -> int | None:
    for idx in candidates:
        if idx in used:
            continue
        return idx
    return None


def _resolve_block_label(labels: list[str]) -> str:
    if not labels:
        return "OTHER"

    label_set = set(labels)
    if "KNOWLEDGE" in label_set and any(
        recipe_label in label_set for recipe_label in _RECIPE_LOCAL_LABELS
    ):
        label_set.remove("KNOWLEDGE")

    for label in _LABEL_RESOLUTION_PRIORITY:
        if label in label_set:
            return label
    return "OTHER"


def _load_knowledge_indices(snippets_path: Path | None) -> set[int]:
    if snippets_path is None:
        return set()
    if not snippets_path.exists() or not snippets_path.is_file():
        return set()

    indices: set[int] = set()
    for line in snippets_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        provenance = payload.get("provenance")
        if not isinstance(provenance, dict):
            continue
        raw_indices = provenance.get("block_indices")
        if not isinstance(raw_indices, list):
            continue
        for value in raw_indices:
            coerced = _coerce_int(value)
            if coerced is None:
                continue
            indices.add(coerced)
    return indices
