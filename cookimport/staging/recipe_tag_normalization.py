from __future__ import annotations

import re
from typing import Any

from cookimport.core.models import ConversionResult

_WHITESPACE_RE = re.compile(r"\s+")
_SEPARATOR_RE = re.compile(r"[_/+-]+")
_PUNCT_RE = re.compile(r"[^a-z0-9& ]+")


def normalize_tag_label(raw: str) -> str:
    cleaned = str(raw or "").strip().casefold()
    if not cleaned:
        return ""
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = cleaned.replace("’", "'").replace("`", "'")
    cleaned = cleaned.replace("&", " and ")
    cleaned = cleaned.replace("'", "")
    cleaned = _SEPARATOR_RE.sub(" ", cleaned)
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    return cleaned.strip()


def normalize_recipe_tags(raw_tags: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    normalized: list[str] = []
    alias_map: dict[str, list[str]] = {}
    seen: set[str] = set()
    alias_key_to_display: dict[str, str] = {}
    for raw in raw_tags:
        raw_text = str(raw or "").strip()
        if not raw_text:
            continue
        rendered = normalize_tag_label(raw_text)
        if not rendered:
            continue
        alias_key = rendered.replace(" ", "")
        display = alias_key_to_display.setdefault(alias_key, rendered)
        alias_map.setdefault(display, [])
        if raw_text not in alias_map[display]:
            alias_map[display].append(raw_text)
        if alias_key in seen:
            continue
        seen.add(alias_key)
        normalized.append(display)
    return normalized, alias_map


def normalize_conversion_result_recipe_tags(result: ConversionResult) -> dict[str, Any]:
    recipes = getattr(result, "recipes", None)
    if not isinstance(recipes, list):
        return {
            "recipes_seen": 0,
            "recipes_with_tags": 0,
            "normalized_tag_total": 0,
            "variant_groups": {},
        }

    variant_groups: dict[str, list[str]] = {}
    recipes_with_tags = 0
    normalized_total = 0
    for recipe in recipes:
        raw_tags = list(getattr(recipe, "tags", []) or [])
        normalized_tags, alias_map = normalize_recipe_tags(raw_tags)
        recipe.tags = normalized_tags
        if normalized_tags:
            recipes_with_tags += 1
            normalized_total += len(normalized_tags)
        for canonical, variants in alias_map.items():
            if len(variants) <= 1:
                continue
            variant_groups.setdefault(canonical, [])
            for variant in variants:
                if variant not in variant_groups[canonical]:
                    variant_groups[canonical].append(variant)

    return {
        "recipes_seen": len(recipes),
        "recipes_with_tags": recipes_with_tags,
        "normalized_tag_total": normalized_total,
        "variant_groups": dict(sorted(variant_groups.items())),
    }
