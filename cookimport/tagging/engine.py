"""Deterministic tagging engine: scores recipes against TAG_RULES and applies category policies."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from cookimport.tagging.catalog import TagCatalog
from cookimport.tagging.policies import get_policy
from cookimport.tagging.rules import TAG_RULES
from cookimport.tagging.signals import RecipeSignalPack, normalize_text_for_matching

logger = logging.getLogger(__name__)


@dataclass
class TagSuggestion:
    tag_key: str
    category_key: str
    confidence: float
    evidence: list[str] = field(default_factory=list)


# Precompile regex patterns once at import time
_COMPILED_RULES: dict[str, dict[str, Any]] = {}


def _clear_compiled_cache() -> None:
    """Clear the compiled rules cache (for testing after rule changes)."""
    _COMPILED_RULES.clear()


def _ensure_compiled() -> dict[str, dict[str, Any]]:
    """Lazily compile all regex patterns in TAG_RULES."""
    if _COMPILED_RULES:
        return _COMPILED_RULES
    for tag_key, rule in TAG_RULES.items():
        compiled: dict[str, Any] = {
            "min_score": rule.get("min_score", 0.6),
            "patterns": [],
            "exclude_patterns": [],
        }
        for p in rule.get("patterns", []):
            compiled["patterns"].append({
                "field": p["field"],
                "regex": re.compile(p["regex"], re.IGNORECASE),
                "weight": p["weight"],
                "evidence": p["evidence"],
            })
        for ep in rule.get("exclude_patterns", []):
            compiled["exclude_patterns"].append({
                "field": ep.get("field", "title"),
                "regex": re.compile(ep["regex"], re.IGNORECASE),
            })
        _COMPILED_RULES[tag_key] = compiled
    return _COMPILED_RULES


def _get_field_text(signals: RecipeSignalPack, field_name: str, normalized_cache: dict[str, str]) -> str:
    """Get normalized text for a given field, using cache."""
    if field_name in normalized_cache:
        return normalized_cache[field_name]

    raw = ""
    if field_name == "title":
        raw = signals.title
    elif field_name == "description":
        raw = signals.description
    elif field_name == "notes":
        raw = signals.notes
    elif field_name == "ingredients":
        raw = "\n".join(signals.ingredients)
    elif field_name == "instructions":
        raw = "\n".join(signals.instructions)

    text = normalize_text_for_matching(raw)
    normalized_cache[field_name] = text
    return text


def _apply_numeric_rules(signals: RecipeSignalPack) -> list[TagSuggestion]:
    """Generate suggestions based on numeric fields (time, levels)."""
    suggestions: list[TagSuggestion] = []

    # Quick: total_time <= 25 minutes
    total = signals.total_time_minutes
    if total is not None and 0 < total <= 25:
        suggestions.append(TagSuggestion(
            tag_key="quick",
            category_key="effort",
            confidence=0.8,
            evidence=[f"total_time_minutes={total} (<=25)"],
        ))

    # Hands-off from attention_level
    if signals.attention_level and signals.attention_level.lower() in ("set_and_forget", "set-and-forget"):
        suggestions.append(TagSuggestion(
            tag_key="hands-off-friendly",
            category_key="effort",
            confidence=0.8,
            evidence=["attention_level=set_and_forget"],
        ))

    return suggestions


def suggest_tags_deterministic(
    catalog: TagCatalog,
    signals: RecipeSignalPack,
) -> list[TagSuggestion]:
    """Run deterministic rules and return scored, policy-filtered suggestions."""
    compiled = _ensure_compiled()
    normalized_cache: dict[str, str] = {}

    raw_suggestions: list[TagSuggestion] = []

    for tag_key, rule in compiled.items():
        # Skip tags not in the catalog
        if tag_key not in catalog.tags_by_key:
            continue

        category_key = catalog.category_key_for_tag(tag_key)
        if category_key is None:
            continue

        # Check exclude patterns first
        excluded = False
        for ep in rule["exclude_patterns"]:
            field_text = _get_field_text(signals, ep["field"], normalized_cache)
            if ep["regex"].search(field_text):
                excluded = True
                break
        if excluded:
            continue

        # Score patterns
        raw_score = 0.0
        evidence: list[str] = []
        for p in rule["patterns"]:
            field_text = _get_field_text(signals, p["field"], normalized_cache)
            if p["regex"].search(field_text):
                raw_score += p["weight"]
                evidence.append(p["evidence"])

        confidence = min(1.0, max(0.0, raw_score))

        # Apply threshold
        policy = get_policy(category_key)
        threshold = max(rule["min_score"], policy.get("min_confidence", 0.6))
        if confidence >= threshold:
            raw_suggestions.append(TagSuggestion(
                tag_key=tag_key,
                category_key=category_key,
                confidence=confidence,
                evidence=evidence,
            ))

    # Add numeric-based suggestions
    for ns in _apply_numeric_rules(signals):
        if ns.tag_key in catalog.tags_by_key:
            # Merge with existing suggestion if present
            existing = next((s for s in raw_suggestions if s.tag_key == ns.tag_key), None)
            if existing:
                existing.confidence = min(1.0, existing.confidence + ns.confidence * 0.5)
                existing.evidence.extend(ns.evidence)
            else:
                raw_suggestions.append(ns)

    # Apply category policies
    return _apply_policies(catalog, raw_suggestions)


def _apply_policies(catalog: TagCatalog, suggestions: list[TagSuggestion]) -> list[TagSuggestion]:
    """Group suggestions by category and apply single/multi policies."""
    # Group by category
    by_category: dict[str, list[TagSuggestion]] = {}
    for s in suggestions:
        by_category.setdefault(s.category_key, []).append(s)

    result: list[TagSuggestion] = []
    for category_key, group in sorted(by_category.items()):
        policy = get_policy(category_key)
        mode = policy.get("mode", "multi")
        max_tags = policy.get("max_tags", 3)

        # Sort by confidence descending, then by catalog sort_order for tie-breaking
        group.sort(key=lambda s: (
            -s.confidence,
            catalog.tags_by_key.get(s.tag_key, None) and catalog.tags_by_key[s.tag_key].sort_order or 0,
        ))

        if mode == "single":
            if group:
                result.append(group[0])
        else:
            result.extend(group[:max_tags])

    # Sort final output by category then confidence
    result.sort(key=lambda s: (s.category_key, -s.confidence))
    return result
