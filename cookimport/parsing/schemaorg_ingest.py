from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any

from cookimport.core.models import RecipeCandidate

_SCHEMA_DURATION_RE = re.compile(r"^[Pp](?:\d+[YMWD])?(?:T[\dHMS]+)?$")
_DURATION_TOKEN_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|hr|h|minutes?|mins?|min|m|seconds?|secs?|sec|s)\b",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")

_HOWTO_SECTION_TYPES = {"howtosection"}
_HOWTO_STEP_TYPES = {"howtostep", "howtodirection"}


def collect_schemaorg_recipe_objects(data: object) -> list[dict[str, Any]]:
    """Collect schema.org Recipe objects from nested dict/list/@graph structures."""

    collected: list[dict[str, Any]] = []
    seen_signatures: set[str] = set()
    visited_nodes: set[int] = set()

    def _visit(node: object) -> None:
        node_id = id(node)
        if node_id in visited_nodes:
            return
        visited_nodes.add(node_id)

        if isinstance(node, dict):
            if _is_recipe_object(node):
                signature = _recipe_object_signature(node)
                if signature not in seen_signatures:
                    seen_signatures.add(signature)
                    collected.append(node)
            for value in node.values():
                _visit(value)
            return

        if isinstance(node, list):
            for item in node:
                _visit(item)

    _visit(data)
    return collected


def flatten_schema_recipe_instructions(recipe_obj: dict[str, Any]) -> list[str]:
    """Flatten recipeInstructions into deterministic plain-text steps."""

    raw = recipe_obj.get("recipeInstructions")
    steps: list[str] = []
    seen: set[str] = set()

    def _append(text: str | None) -> None:
        normalized = _normalize_text(text)
        if not normalized:
            return
        if normalized in seen:
            return
        seen.add(normalized)
        steps.append(normalized)

    def _visit(node: object) -> None:
        if node is None:
            return
        if isinstance(node, str):
            for line in node.splitlines():
                _append(line)
            return
        if isinstance(node, list):
            for item in node:
                _visit(item)
            return
        if not isinstance(node, dict):
            _append(str(node))
            return

        node_types = _type_tokens(node.get("@type"))
        if node_types & _HOWTO_SECTION_TYPES:
            _append(_coerce_text(node.get("name")) or _coerce_text(node.get("headline")))
            _visit(node.get("itemListElement"))
            _visit(node.get("steps"))
            _visit(node.get("recipeInstructions"))
            return

        if node_types & _HOWTO_STEP_TYPES:
            _append(
                _coerce_text(node.get("text"))
                or _coerce_text(node.get("name"))
                or _coerce_text(node.get("item"))
            )
            _visit(node.get("itemListElement"))
            return

        _append(_coerce_text(node.get("text")) or _coerce_text(node.get("name")))
        _visit(node.get("itemListElement"))
        _visit(node.get("steps"))
        _visit(node.get("recipeInstructions"))

    _visit(raw)
    return steps


def schema_recipe_confidence(
    recipe_obj: dict[str, Any],
    *,
    min_ingredients: int = 2,
    min_instruction_steps: int = 1,
) -> tuple[float, list[str]]:
    """Compute deterministic confidence for a schema object before importer gating."""

    threshold_ingredients = max(0, int(min_ingredients))
    threshold_steps = max(0, int(min_instruction_steps))

    score = 0.0
    reasons: list[str] = []

    name = _coerce_text(recipe_obj.get("name"))
    if name:
        score += 0.25
        reasons.append("has_name")
    else:
        reasons.append("missing_name")

    ingredient_lines = _coerce_str_list(recipe_obj.get("recipeIngredient"))
    if len(ingredient_lines) >= threshold_ingredients:
        score += 0.35
        reasons.append("ingredients_threshold_met")
    elif ingredient_lines:
        score += 0.18
        reasons.append("few_ingredients")
    else:
        reasons.append("missing_ingredients")

    instruction_steps = flatten_schema_recipe_instructions(recipe_obj)
    if len(instruction_steps) >= threshold_steps:
        score += 0.30
        reasons.append("instructions_threshold_met")
    elif instruction_steps:
        score += 0.15
        reasons.append("few_instruction_steps")
    else:
        reasons.append("missing_instructions")

    if _coerce_text(recipe_obj.get("description")):
        score += 0.05
        reasons.append("has_description")
    if _coerce_text(recipe_obj.get("recipeYield")):
        score += 0.02
    if _coerce_text(recipe_obj.get("prepTime")) or _coerce_text(recipe_obj.get("cookTime")):
        score += 0.02
    if _coerce_text(recipe_obj.get("url")):
        score += 0.01

    return (round(min(score, 1.0), 4), reasons)


def schema_recipe_to_candidate(
    recipe_obj: dict[str, Any],
    *,
    source: str | None = None,
    source_url_hint: str | None = None,
    confidence: float | None = None,
    provenance: dict[str, Any] | None = None,
) -> RecipeCandidate:
    """Map a schema.org recipe object to RecipeCandidate."""

    source_url = _coerce_text(recipe_obj.get("url")) or _coerce_text(source_url_hint)
    payload_provenance = dict(provenance or {})
    if confidence is not None:
        payload_provenance.setdefault("confidence_score", float(confidence))

    return RecipeCandidate(
        name=_coerce_text(recipe_obj.get("name")) or "Untitled Recipe",
        identifier=(
            _coerce_text(recipe_obj.get("identifier"))
            or _coerce_text(recipe_obj.get("@id"))
            or source_url
        ),
        description=_coerce_text(recipe_obj.get("description")),
        recipeIngredient=_coerce_str_list(recipe_obj.get("recipeIngredient")),
        recipeInstructions=flatten_schema_recipe_instructions(recipe_obj),
        recipeYield=_coerce_text(recipe_obj.get("recipeYield")),
        prepTime=parse_schema_duration(recipe_obj.get("prepTime")),
        cookTime=parse_schema_duration(recipe_obj.get("cookTime")),
        totalTime=parse_schema_duration(recipe_obj.get("totalTime")),
        tags=_collect_keyword_tags(recipe_obj.get("keywords")),
        image=_coerce_image_list(recipe_obj.get("image")),
        recipeCategory=_coerce_str_list(recipe_obj.get("recipeCategory")),
        recipeCuisine=_coerce_str_list(recipe_obj.get("recipeCuisine")),
        cookingMethod=_coerce_str_list(recipe_obj.get("cookingMethod")),
        suitableForDiet=_coerce_str_list(recipe_obj.get("suitableForDiet")),
        author=_person_or_org_name(recipe_obj.get("author")),
        publisher=_person_or_org_name(recipe_obj.get("publisher")),
        sourceUrl=source_url,
        isBasedOn=_coerce_text(recipe_obj.get("isBasedOn")),
        comment=_normalize_comments(recipe_obj.get("comment")),
        source=source,
        provenance=payload_provenance,
        confidence=confidence,
    )


def parse_schema_duration(value: Any) -> str | None:
    text = _coerce_text(value)
    if not text:
        return None
    if _SCHEMA_DURATION_RE.match(text):
        return text.upper()

    isodate_seconds = _parse_duration_with_isodate(text)
    if isodate_seconds is not None and isodate_seconds > 0:
        return _seconds_to_iso_duration(isodate_seconds)

    fallback_seconds = _parse_duration_fallback_seconds(text)
    if fallback_seconds is None or fallback_seconds <= 0:
        return None
    return _seconds_to_iso_duration(fallback_seconds)


def _is_recipe_object(node: dict[str, Any]) -> bool:
    return "recipe" in _type_tokens(node.get("@type"))


def _type_tokens(raw_type: object) -> set[str]:
    tokens: set[str] = set()
    if raw_type is None:
        return tokens
    values: list[object]
    if isinstance(raw_type, list):
        values = list(raw_type)
    else:
        values = [raw_type]
    for value in values:
        text = _coerce_text(value)
        if not text:
            continue
        tail = text.rsplit("/", 1)[-1]
        tail = tail.rsplit("#", 1)[-1]
        tokens.add(tail.strip().lower())
    return tokens


def _recipe_object_signature(recipe_obj: dict[str, Any]) -> str:
    try:
        return json.dumps(recipe_obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    except TypeError:
        return str(id(recipe_obj))


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    normalized = _WHITESPACE_RE.sub(" ", str(value)).strip()
    return normalized


def _coerce_text(value: Any) -> str | None:
    normalized = _normalize_text(value)
    return normalized or None


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = re.split(r"[\n\r]+", value)
    elif isinstance(value, list):
        items = list(value)
    else:
        items = [value]
    normalized: list[str] = []
    for item in items:
        text = _coerce_text(item)
        if text:
            normalized.append(text)
    return normalized


def _coerce_image_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = [value]
    images: list[str] = []
    for item in items:
        if isinstance(item, dict):
            text = _coerce_text(item.get("url") or item.get("@id"))
        else:
            text = _coerce_text(item)
        if text:
            images.append(text)
    return images


def _collect_keyword_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_values = [str(item) for item in value if _coerce_text(item)]
    else:
        raw_values = [str(value)]
    tags: list[str] = []
    for raw in raw_values:
        for token in re.split(r"[,;\n]", raw):
            normalized = _coerce_text(token)
            if normalized:
                tags.append(normalized)
    return tags


def _person_or_org_name(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _coerce_text(value)
    if isinstance(value, dict):
        return _coerce_text(value.get("name") or value.get("@id"))
    if isinstance(value, list):
        for item in value:
            resolved = _person_or_org_name(item)
            if resolved:
                return resolved
    return _coerce_text(value)


def _normalize_comments(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    comments: list[dict[str, str]] = []
    for item in values:
        if isinstance(item, dict):
            text = _coerce_text(item.get("text") or item.get("name"))
            name = _coerce_text(item.get("name"))
            payload: dict[str, str] = {}
            if name:
                payload["name"] = name
            if text:
                payload["text"] = text
            if payload:
                comments.append(payload)
            continue
        text = _coerce_text(item)
        if text:
            comments.append({"text": text})
    return comments


def _parse_duration_with_isodate(text: str) -> int | None:
    try:
        import isodate  # type: ignore[import-untyped]
    except Exception:
        return None
    try:
        parsed = isodate.parse_duration(text)
    except Exception:
        return None
    if isinstance(parsed, timedelta):
        return max(0, int(parsed.total_seconds()))
    tdelta = getattr(parsed, "tdelta", None)
    if isinstance(tdelta, timedelta):
        return max(0, int(tdelta.total_seconds()))
    to_timedelta = getattr(parsed, "totimedelta", None)
    if callable(to_timedelta):
        try:
            td = to_timedelta(start=None, end=None)
        except Exception:
            return None
        if isinstance(td, timedelta):
            return max(0, int(td.total_seconds()))
    return None


def _parse_duration_fallback_seconds(text: str) -> int | None:
    normalized = text.strip().lower()
    if not normalized:
        return None

    total_seconds = 0.0
    matched = False
    for number_text, unit_text in _DURATION_TOKEN_RE.findall(normalized):
        matched = True
        try:
            number = float(number_text)
        except ValueError:
            continue
        if unit_text.startswith(("hour", "hr", "h")):
            total_seconds += number * 3600.0
        elif unit_text.startswith(("minute", "min", "m")):
            total_seconds += number * 60.0
        else:
            total_seconds += number

    if matched:
        return max(0, int(round(total_seconds)))

    try:
        minutes_only = float(normalized)
    except ValueError:
        return None
    return max(0, int(round(minutes_only * 60.0)))


def _seconds_to_iso_duration(seconds: int) -> str:
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts = "P"
    if days:
        parts += f"{days}D"
    if hours or minutes or secs or not days:
        parts += "T"
        if hours:
            parts += f"{hours}H"
        if minutes:
            parts += f"{minutes}M"
        if secs or (not hours and not minutes):
            parts += f"{secs}S"
    return parts

