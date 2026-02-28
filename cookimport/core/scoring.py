from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Any, Literal, Sequence

from cookimport.core.models import (
    RecipeCandidate,
    RecipeLikenessResult,
    RecipeLikenessTier,
)
from cookimport.parsing import signals

if TYPE_CHECKING:
    from cookimport.config.run_settings import RunSettings


RecipeGateAction = Literal["keep_full", "keep_partial", "reject"]

_DEFAULT_RECIPE_SCORER_BACKEND = "heuristic_v1"
_DEFAULT_RECIPE_LIKENESS_VERSION = "2026-02-28"
_DEFAULT_GOLD_MIN = 0.75
_DEFAULT_SILVER_MIN = 0.55
_DEFAULT_BRONZE_MIN = 0.35
_DEFAULT_MIN_INGREDIENT_LINES = 1
_DEFAULT_MIN_INSTRUCTION_LINES = 1
_PATTERN_TOC_LIKE_PENALTY = 0.18
_PATTERN_DUPLICATE_TITLE_PENALTY = 0.09
_PATTERN_OVERLAP_DUPLICATE_PENALTY = 0.26

_GENERIC_TITLES = {"recipe", "untitled recipe", "untitled", "new recipe"}
_FILENAME_TITLE_RE = re.compile(r"\.\w{2,5}$")
_INSTRUCTION_LEAD_RE = re.compile(
    r"^\s*(preheat|heat|bring|make|mix|stir|whisk|cook|bake|roast|fry|grill|"
    r"season|serve|add|melt|place|put|pour|combine|fold|remove|drain|peel|chop|"
    r"slice|cut|toss|cool|refrigerate|strain|beat|whip|simmer|boil|reduce|cover)\b",
    re.IGNORECASE,
)
_NOISE_SYMBOL_RE = re.compile(r"[`~^|]{2,}|[<>{}\\]{2,}|[_=*#]{6,}")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _coerce_int_feature(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_float_setting(value: Any, fallback: float) -> float:
    try:
        return _clamp(float(value))
    except (TypeError, ValueError):
        return fallback


def _coerce_int_setting(value: Any, fallback: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return fallback


def _setting_value(settings: RunSettings | None, key: str, fallback: Any) -> Any:
    if settings is None:
        return fallback
    return getattr(settings, key, fallback)


def _instruction_text(value: Any) -> str:
    text = getattr(value, "text", value)
    return str(text).strip()


def _pattern_flags_from_location(location: Any) -> set[str]:
    if not isinstance(location, dict):
        return set()
    flags: set[str] = set()
    raw_flags = location.get("pattern_flags")
    if isinstance(raw_flags, str):
        parts = [part.strip() for part in raw_flags.split(",")]
        flags.update(part for part in parts if part)
    elif isinstance(raw_flags, list):
        for raw_flag in raw_flags:
            normalized = str(raw_flag).strip()
            if normalized:
                flags.add(normalized)

    raw_actions = location.get("pattern_actions")
    if isinstance(raw_actions, list):
        for action in raw_actions:
            if not isinstance(action, dict):
                continue
            action_name = str(action.get("action") or "").strip().lower()
            if action_name == "reject_overlap_duplicate_candidate":
                flags.add("overlap_duplicate_candidate")
            elif action_name == "trim_candidate_start":
                flags.add("duplicate_title_intro")

    return flags


def _normalized_thresholds(
    settings: RunSettings | None,
) -> tuple[float, float, float]:
    gold_raw = _coerce_float_setting(
        _setting_value(settings, "recipe_score_gold_min", _DEFAULT_GOLD_MIN),
        _DEFAULT_GOLD_MIN,
    )
    silver_raw = _coerce_float_setting(
        _setting_value(settings, "recipe_score_silver_min", _DEFAULT_SILVER_MIN),
        _DEFAULT_SILVER_MIN,
    )
    bronze_raw = _coerce_float_setting(
        _setting_value(settings, "recipe_score_bronze_min", _DEFAULT_BRONZE_MIN),
        _DEFAULT_BRONZE_MIN,
    )
    gold = max(gold_raw, silver_raw, bronze_raw)
    silver = min(gold, max(silver_raw, bronze_raw))
    bronze = min(silver, bronze_raw)
    return gold, silver, bronze


def _title_quality(name: str) -> float:
    stripped = name.strip()
    if not stripped:
        return 0.0
    lowered = stripped.lower()
    if lowered in _GENERIC_TITLES:
        return 0.25
    if _FILENAME_TITLE_RE.search(lowered):
        return 0.4
    if len(stripped) < 4:
        return 0.35
    if len(stripped) > 90:
        return 0.55
    return 1.0


def _ingredient_quality(lines: list[str]) -> float:
    if not lines:
        return 0.0
    check_limit = min(len(lines), 8)
    quality_points = 0.0
    for line in lines[:check_limit]:
        feats = signals.classify_block(line)
        if feats.get("is_ingredient_likely"):
            quality_points += 1.0
            continue
        if feats.get("starts_with_quantity") and not feats.get("is_instruction_likely"):
            quality_points += 0.85
            continue
        if feats.get("has_unit") and not feats.get("is_instruction_likely"):
            quality_points += 0.75
            continue
        if re.match(r"^\s*[-*•]\s+", line):
            quality_points += 0.6
            continue
        if len(line.split()) <= 6:
            quality_points += 0.5
    ratio = quality_points / max(1, check_limit)
    count_boost = min(1.0, len(lines) / 6.0)
    return _clamp((ratio * 0.65) + (count_boost * 0.35))


def _instruction_quality(lines: list[str]) -> float:
    if not lines:
        return 0.0
    check_limit = min(len(lines), 8)
    quality_points = 0.0
    for line in lines[:check_limit]:
        feats = signals.classify_block(line)
        if feats.get("is_instruction_likely"):
            quality_points += 1.0
            continue
        if _INSTRUCTION_LEAD_RE.match(line):
            quality_points += 0.8
            continue
        if re.match(r"^\s*(\d+[.)]|[-*•])\s+", line):
            quality_points += 0.7
            continue
        if len(line.split()) >= 8:
            quality_points += 0.4
            continue
        if len(line.split()) >= 2:
            quality_points += 0.5
    ratio = quality_points / max(1, check_limit)
    count_boost = min(1.0, len(lines) / 5.0)
    return _clamp((ratio * 0.7) + (count_boost * 0.3))


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    clipped = _clamp(fraction)
    position = clipped * (len(values) - 1)
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    lower_value = values[lower_index]
    upper_value = values[upper_index]
    if lower_index == upper_index:
        return lower_value
    weight = position - lower_index
    return lower_value + ((upper_value - lower_value) * weight)


def score_recipe_likeness(
    candidate: RecipeCandidate,
    *,
    settings: RunSettings | None = None,
) -> RecipeLikenessResult:
    backend = str(
        _setting_value(
            settings,
            "recipe_scorer_backend",
            _DEFAULT_RECIPE_SCORER_BACKEND,
        )
        or _DEFAULT_RECIPE_SCORER_BACKEND
    ).strip()
    if not backend:
        backend = _DEFAULT_RECIPE_SCORER_BACKEND

    title = (candidate.name or "").strip()
    ingredient_lines = [line.strip() for line in candidate.ingredients if str(line).strip()]
    instruction_lines = [
        _instruction_text(line)
        for line in candidate.instructions
        if _instruction_text(line)
    ]

    description = (candidate.description or "").strip()
    total_text = "\n".join(
        [title] + ingredient_lines + instruction_lines + ([description] if description else [])
    ).strip()
    text_length = len(total_text)
    word_count = len(total_text.split())

    ingredient_count = len(ingredient_lines)
    instruction_count = len(instruction_lines)
    combined_line_count = ingredient_count + instruction_count

    title_quality = _title_quality(title)
    ingredient_quality = _ingredient_quality(ingredient_lines)
    instruction_quality = _instruction_quality(instruction_lines)

    metadata_quality = 0.0
    if candidate.recipe_yield:
        metadata_quality += 0.35
    if description:
        metadata_quality += 0.35
    if candidate.source_url or candidate.source:
        metadata_quality += 0.3
    metadata_quality = _clamp(metadata_quality)

    ingredient_density = ingredient_count / max(1, combined_line_count)
    instruction_density = instruction_count / max(1, combined_line_count)
    density_score = _clamp(
        min(1.0, ingredient_density / 0.6) * 0.5
        + min(1.0, instruction_density / 0.6) * 0.5
    )

    provenance = candidate.provenance if isinstance(candidate.provenance, dict) else {}
    location = provenance.get("location", {}) if isinstance(provenance, dict) else {}
    has_heading_anchor_hint = bool(
        isinstance(location, dict)
        and (
            location.get("start_block") is not None
            or location.get("start_page") is not None
            or location.get("start_spine") is not None
            or location.get("start_line") is not None
        )
    )
    heading_anchor_score = 1.0 if has_heading_anchor_hint else 0.0

    symbol_noise_count = len(_NOISE_SYMBOL_RE.findall(total_text))
    symbol_noise_ratio = symbol_noise_count / max(1, text_length)
    noise_penalty = 0.0
    if symbol_noise_ratio > 0.02:
        noise_penalty = min(0.14, (symbol_noise_ratio - 0.02) * 2.5)

    short_penalty = 0.0
    long_penalty = 0.0
    if text_length < 80:
        short_penalty = min(0.1, ((80 - text_length) / 80) * 0.1)
    if text_length > 12000:
        long_penalty = min(0.16, ((text_length - 12000) / 12000) * 0.16)

    min_ingredient_lines = _coerce_int_setting(
        _setting_value(
            settings,
            "recipe_score_min_ingredient_lines",
            _DEFAULT_MIN_INGREDIENT_LINES,
        ),
        _DEFAULT_MIN_INGREDIENT_LINES,
    )
    min_instruction_lines = _coerce_int_setting(
        _setting_value(
            settings,
            "recipe_score_min_instruction_lines",
            _DEFAULT_MIN_INSTRUCTION_LINES,
        ),
        _DEFAULT_MIN_INSTRUCTION_LINES,
    )
    minimum_line_penalty = 0.0
    if ingredient_count < min_ingredient_lines:
        gap = min_ingredient_lines - ingredient_count
        minimum_line_penalty += min(0.15, gap * 0.03)
    if instruction_count < min_instruction_lines:
        gap = min_instruction_lines - instruction_count
        minimum_line_penalty += min(0.15, gap * 0.04)

    pattern_flags = _pattern_flags_from_location(location)
    toc_like_penalty = (
        _PATTERN_TOC_LIKE_PENALTY if "toc_like_cluster" in pattern_flags else 0.0
    )
    duplicate_title_penalty = (
        _PATTERN_DUPLICATE_TITLE_PENALTY
        if "duplicate_title_intro" in pattern_flags
        else 0.0
    )
    overlap_duplicate_penalty = (
        _PATTERN_OVERLAP_DUPLICATE_PENALTY
        if "overlap_duplicate_candidate" in pattern_flags
        else 0.0
    )
    pattern_penalty_total = (
        toc_like_penalty + duplicate_title_penalty + overlap_duplicate_penalty
    )

    base_score = (
        (title_quality * 0.2)
        + (ingredient_quality * 0.31)
        + (instruction_quality * 0.31)
        + (metadata_quality * 0.08)
        + (density_score * 0.06)
        + (heading_anchor_score * 0.04)
    )
    score = _clamp(
        base_score
        - short_penalty
        - long_penalty
        - noise_penalty
        - minimum_line_penalty
        - pattern_penalty_total
    )

    gold_min, silver_min, bronze_min = _normalized_thresholds(settings)
    if score >= gold_min:
        tier = RecipeLikenessTier.gold
    elif score >= silver_min:
        tier = RecipeLikenessTier.silver
    elif score >= bronze_min:
        tier = RecipeLikenessTier.bronze
    else:
        tier = RecipeLikenessTier.reject

    reasons: list[str] = []
    if title_quality < 0.5:
        reasons.append("generic_or_low_quality_title")
    if ingredient_count == 0:
        reasons.append("missing_ingredients")
    elif ingredient_count < min_ingredient_lines:
        reasons.append("few_ingredient_lines")
    if instruction_count == 0:
        reasons.append("missing_instructions")
    elif instruction_count < min_instruction_lines:
        reasons.append("few_instruction_lines")
    if short_penalty > 0:
        reasons.append("content_too_short")
    if long_penalty > 0:
        reasons.append("content_too_long")
    if noise_penalty >= 0.08:
        reasons.append("high_symbol_noise")
    if toc_like_penalty > 0:
        reasons.append("pattern_toc_like_penalty")
    if duplicate_title_penalty > 0:
        reasons.append("pattern_duplicate_title_penalty")
    if overlap_duplicate_penalty > 0:
        reasons.append("pattern_overlap_duplicate_penalty")
    if tier is RecipeLikenessTier.reject:
        reasons.append("below_reject_threshold")

    features: dict[str, Any] = {
        "title_quality": round(title_quality, 4),
        "ingredient_quality": round(ingredient_quality, 4),
        "instruction_quality": round(instruction_quality, 4),
        "metadata_quality": round(metadata_quality, 4),
        "density_score": round(density_score, 4),
        "ingredient_count": ingredient_count,
        "instruction_count": instruction_count,
        "combined_line_count": combined_line_count,
        "ingredient_density": round(ingredient_density, 4),
        "instruction_density": round(instruction_density, 4),
        "has_heading_anchor_hint": has_heading_anchor_hint,
        "text_length_chars": text_length,
        "word_count": word_count,
        "noise_penalty": round(noise_penalty, 4),
        "short_penalty": round(short_penalty, 4),
        "long_penalty": round(long_penalty, 4),
        "minimum_line_penalty": round(minimum_line_penalty, 4),
        "pattern_toc_like_penalty": round(toc_like_penalty, 4),
        "pattern_duplicate_title_penalty": round(duplicate_title_penalty, 4),
        "pattern_overlap_duplicate_penalty": round(overlap_duplicate_penalty, 4),
        "pattern_penalty_total": round(pattern_penalty_total, 4),
        "pattern_flag_toc_like_cluster": bool("toc_like_cluster" in pattern_flags),
        "pattern_flag_duplicate_title_intro": bool("duplicate_title_intro" in pattern_flags),
        "pattern_flag_overlap_duplicate_candidate": bool(
            "overlap_duplicate_candidate" in pattern_flags
        ),
    }

    return RecipeLikenessResult(
        score=round(score, 4),
        tier=tier,
        backend=backend,
        version=_DEFAULT_RECIPE_LIKENESS_VERSION,
        features=features,
        reasons=reasons,
    )


def score_recipe_candidate(candidate: RecipeCandidate) -> float:
    """
    Backward-compatible numeric confidence score used by legacy callers.
    """
    return score_recipe_likeness(candidate).score


def recipe_gate_action(
    result: RecipeLikenessResult,
    *,
    settings: RunSettings | None = None,
) -> RecipeGateAction:
    if result.tier is RecipeLikenessTier.reject:
        return "reject"

    min_ingredient_lines = _coerce_int_setting(
        _setting_value(
            settings,
            "recipe_score_min_ingredient_lines",
            _DEFAULT_MIN_INGREDIENT_LINES,
        ),
        _DEFAULT_MIN_INGREDIENT_LINES,
    )
    min_instruction_lines = _coerce_int_setting(
        _setting_value(
            settings,
            "recipe_score_min_instruction_lines",
            _DEFAULT_MIN_INSTRUCTION_LINES,
        ),
        _DEFAULT_MIN_INSTRUCTION_LINES,
    )
    ingredient_count = _coerce_int_feature(result.features.get("ingredient_count"))
    instruction_count = _coerce_int_feature(result.features.get("instruction_count"))

    if result.tier is RecipeLikenessTier.bronze:
        return "keep_partial"
    if ingredient_count < min_ingredient_lines or instruction_count < min_instruction_lines:
        return "keep_partial"
    return "keep_full"


def summarize_recipe_likeness(
    results: Sequence[RecipeLikenessResult],
    rejected_count: int,
    *,
    settings: RunSettings | None = None,
) -> dict[str, Any]:
    gold_min, silver_min, bronze_min = _normalized_thresholds(settings)
    counts = {
        RecipeLikenessTier.gold.value: 0,
        RecipeLikenessTier.silver.value: 0,
        RecipeLikenessTier.bronze.value: 0,
        RecipeLikenessTier.reject.value: 0,
    }
    scores: list[float] = []
    backend = str(
        _setting_value(
            settings,
            "recipe_scorer_backend",
            _DEFAULT_RECIPE_SCORER_BACKEND,
        )
    )
    version = _DEFAULT_RECIPE_LIKENESS_VERSION

    for result in results:
        counts[result.tier.value] = counts.get(result.tier.value, 0) + 1
        scores.append(float(result.score))
        if result.backend:
            backend = result.backend
        if result.version:
            version = result.version

    scores.sort()
    if scores:
        score_stats: dict[str, float | None] = {
            "min": round(scores[0], 4),
            "p50": round(_percentile(scores, 0.5), 4),
            "p90": round(_percentile(scores, 0.9), 4),
            "max": round(scores[-1], 4),
        }
    else:
        score_stats = {
            "min": None,
            "p50": None,
            "p90": None,
            "max": None,
        }

    return {
        "backend": backend,
        "version": version,
        "thresholds": {
            "gold": round(gold_min, 4),
            "silver": round(silver_min, 4),
            "bronze": round(bronze_min, 4),
        },
        "counts": counts,
        "scoreStats": score_stats,
        "rejectedCandidateCount": int(max(0, rejected_count)),
        "totalCandidates": len(results),
    }


def build_recipe_scoring_debug_row(
    *,
    candidate: RecipeCandidate,
    result: RecipeLikenessResult,
    gate_action: RecipeGateAction,
    candidate_index: int,
    location: dict[str, Any] | None = None,
    importer: str | None = None,
    source_hash: str | None = None,
) -> dict[str, Any]:
    provenance = candidate.provenance if isinstance(candidate.provenance, dict) else {}
    location_payload = location
    if location_payload is None and isinstance(provenance.get("location"), dict):
        location_payload = dict(provenance["location"])
    if location_payload is None:
        location_payload = {}

    candidate_id = (
        candidate.identifier
        or str(provenance.get("@id") or "")
        or f"candidate_{candidate_index}"
    )
    row: dict[str, Any] = {
        "candidate_id": candidate_id,
        "candidate_name": candidate.name,
        "candidate_index": candidate_index,
        "gate_action": gate_action,
        "location": location_payload,
        "result": result.model_dump(mode="json", by_alias=True, exclude_none=True),
    }
    if importer:
        row["importer"] = importer
    if source_hash:
        row["source_hash"] = source_hash
    return row
