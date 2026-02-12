"""LLM second-pass scaffolding (disabled by default).

When enabled (--llm flag + provider configured), this module:
1. Identifies categories the deterministic tagger left empty or low-confidence.
2. Builds a candidate shortlist per category via fuzzy matching.
3. Calls the LLM with a structured prompt and validates output strictly.
"""

from __future__ import annotations

import logging
from typing import Any

from cookimport.tagging.catalog import TagCatalog
from cookimport.tagging.engine import TagSuggestion
from cookimport.tagging.signals import RecipeSignalPack, normalize_text_for_matching

logger = logging.getLogger(__name__)

# Expected LLM response schema (for documentation / future validation):
# {
#   "suggestions": [
#     {"category": "cuisine", "tag_key": "mexican", "confidence": 0.72, "why": "mentions tortillas + salsa + cumin"},
#     ...
#   ]
# }

_LLM_WARNING_SHOWN = False


def _check_provider_configured() -> bool:
    """Check if an LLM provider is configured. Returns False if not."""
    # Stub: no real provider wired yet.
    return False


def _build_candidate_shortlist(
    catalog: TagCatalog,
    signals: RecipeSignalPack,
    category_key: str,
    max_candidates: int = 10,
) -> list[str]:
    """Build a shortlist of candidate tag key_norms for a category via token overlap."""
    cat = catalog.categories_by_key.get(category_key)
    if cat is None:
        return []

    tags_in_category = catalog.tags_by_category_id.get(cat.id, [])
    if not tags_in_category:
        return []

    # Combined recipe text for matching
    combined = normalize_text_for_matching(
        " ".join([signals.title, signals.description, signals.notes]
                 + signals.ingredients + signals.instructions)
    )
    combined_tokens = set(combined.split())

    scored: list[tuple[str, float]] = []
    for tag in tags_in_category:
        tag_tokens = set(normalize_text_for_matching(tag.display_name).split())
        if not tag_tokens:
            continue
        overlap = len(tag_tokens & combined_tokens)
        score = overlap / len(tag_tokens)
        if score > 0:
            scored.append((tag.key_norm, score))

    scored.sort(key=lambda x: -x[1])
    return [key for key, _ in scored[:max_candidates]]


def suggest_tags_with_llm(
    signals: RecipeSignalPack,
    catalog: TagCatalog,
    missing_categories: list[str],
    deterministic: list[TagSuggestion],
) -> list[TagSuggestion]:
    """Run LLM second pass for missing categories. Returns additional suggestions.

    If no provider is configured, warns once and returns empty list.
    If the provider errors or times out, warns and returns empty list.
    """
    global _LLM_WARNING_SHOWN

    if not _check_provider_configured():
        if not _LLM_WARNING_SHOWN:
            logger.warning("LLM second pass requested but no provider configured. Using deterministic only.")
            _LLM_WARNING_SHOWN = True
        return []

    # Build candidate shortlists
    candidates_by_cat: dict[str, list[str]] = {}
    for cat_key in missing_categories:
        shortlist = _build_candidate_shortlist(catalog, signals, cat_key)
        if shortlist:
            candidates_by_cat[cat_key] = shortlist

    if not candidates_by_cat:
        return []

    # --- LLM call would go here ---
    # For now, return empty (mock implementation preserves the code path).
    logger.info("LLM second pass: would query %d categories with candidates", len(candidates_by_cat))
    return _mock_llm_call(signals, catalog, candidates_by_cat)


def _mock_llm_call(
    signals: RecipeSignalPack,
    catalog: TagCatalog,
    candidates_by_cat: dict[str, list[str]],
) -> list[TagSuggestion]:
    """Mock implementation that returns empty list. Keeps tests deterministic."""
    return []


def _validate_llm_response(
    raw: dict[str, Any],
    catalog: TagCatalog,
    candidates_by_cat: dict[str, list[str]],
) -> list[TagSuggestion]:
    """Validate and parse LLM response strictly.

    Rules:
    - tag_key must exist in catalog
    - category must match the tag's actual category
    - confidence must be 0..1
    - tag_key must be in the candidate shortlist for that category
    """
    suggestions: list[TagSuggestion] = []
    for item in raw.get("suggestions", []):
        tag_key = item.get("tag_key", "")
        category = item.get("category", "")
        confidence = item.get("confidence", 0)
        why = item.get("why", "")

        # Validate
        if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 1):
            logger.warning("LLM response: invalid confidence %s for %s", confidence, tag_key)
            continue
        if tag_key not in catalog.tags_by_key:
            logger.warning("LLM response: unknown tag_key %s", tag_key)
            continue
        actual_cat = catalog.category_key_for_tag(tag_key)
        if actual_cat != category:
            logger.warning("LLM response: tag %s has category %s, not %s", tag_key, actual_cat, category)
            continue
        allowed = candidates_by_cat.get(category, [])
        if tag_key not in allowed:
            logger.warning("LLM response: tag %s not in candidate shortlist for %s", tag_key, category)
            continue

        suggestions.append(TagSuggestion(
            tag_key=tag_key,
            category_key=category,
            confidence=float(confidence),
            evidence=[f"LLM: {why}"] if why else ["LLM suggestion"],
        ))
    return suggestions
