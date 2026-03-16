from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from cookimport.core.blocks import Block
from cookimport.core.models import ParsingOverrides
from cookimport.parsing import signals
from cookimport.parsing.section_detector import detect_sections_from_lines

_MAIN_SECTION_KEYS = {"", "main", "notes"}
_YIELD_LINE_RE = re.compile(r"^\s*(serves|yield|yields|makes)\b", re.IGNORECASE)
_INSTRUCTION_LEAD_RE = re.compile(
    r"^\s*(preheat|heat|bring|make|mix|stir|whisk|crush|cook|bake|roast|fry|grill|"
    r"blanch|season|serve|add|melt|place|put|pour|combine|fold|return|remove|drain|"
    r"peel|chop|slice|cut|toss|leave|cool|refrigerate|strain|set|beat|whip|simmer|"
    r"boil|reduce|cover|unwrap|sear|saute)\b",
    re.IGNORECASE,
)
_NUMBERED_STEP_RE = re.compile(r"^\s*\d+[.)]\s+")
_BULLET_RE = re.compile(r"^\s*[-*•]\s+")
_MARKDOWN_TITLE_PREFIX_RE = re.compile(r"^\s*#{1,6}\s+")
_NUMBERED_TITLE_PREFIX_RE = re.compile(r"^\s*\d+[.)]\s+")


@dataclass(frozen=True)
class MultiRecipeSplitConfig:
    backend: str
    min_ingredient_lines: int
    min_instruction_lines: int
    enable_for_the_guardrail: bool
    trace: bool


@dataclass(frozen=True)
class CandidateSpan:
    start: int
    end: int
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class BoundaryDecision:
    index: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MultiRecipeSplitResult:
    spans: tuple[CandidateSpan, ...]
    boundaries: tuple[BoundaryDecision, ...] = ()
    trace: dict[str, Any] | None = None


@dataclass(frozen=True)
class _Unit:
    index: int
    text: str
    features: dict[str, Any]


def split_candidate_lines(
    lines: Sequence[str],
    *,
    config: MultiRecipeSplitConfig,
    overrides: ParsingOverrides | None = None,
) -> MultiRecipeSplitResult:
    units: list[_Unit] = []
    for idx, raw in enumerate(lines):
        text = str(raw).strip()
        features = signals.classify_block(text, overrides=overrides) if text else {}
        units.append(
            _Unit(
                index=idx,
                text=text,
                features=features,
            )
        )
    return _split_units(units, config=config, overrides=overrides)


def split_candidate_blocks(
    blocks: Sequence[Block],
    *,
    config: MultiRecipeSplitConfig,
    overrides: ParsingOverrides | None = None,
) -> MultiRecipeSplitResult:
    units: list[_Unit] = []
    for idx, block in enumerate(blocks):
        text = str(getattr(block, "text", "") or "").strip()
        features = (
            dict(block.features)
            if isinstance(getattr(block, "features", None), dict)
            else {}
        )
        if text and not features:
            features = signals.classify_block(text, overrides=overrides)
        units.append(_Unit(index=idx, text=text, features=features))
    return _split_units(units, config=config, overrides=overrides)


def _split_units(
    units: Sequence[_Unit],
    *,
    config: MultiRecipeSplitConfig,
    overrides: ParsingOverrides | None,
) -> MultiRecipeSplitResult:
    backend = _normalize_backend(config.backend)
    if not units:
        return MultiRecipeSplitResult(spans=())

    if backend == "off":
        return MultiRecipeSplitResult(
            spans=(CandidateSpan(start=0, end=len(units), reasons=(f"{backend}_passthrough",)),),
            trace=_trace_payload(
                config=config,
                units=units,
                boundaries=(),
                rejected=(),
                component_header_indices=(),
            ),
        )

    min_ingredient_lines = max(0, int(config.min_ingredient_lines))
    min_instruction_lines = max(0, int(config.min_instruction_lines))

    ingredient_flags = tuple(_is_ingredient_content_line(unit) for unit in units)
    instruction_flags = tuple(_is_instruction_content_line(unit) for unit in units)
    ingredient_signal_flags = tuple(_is_ingredient_signal_line(unit) for unit in units)
    instruction_signal_flags = tuple(_is_instruction_signal_line(unit) for unit in units)

    prefix_ingredients = _build_prefix_counts(ingredient_signal_flags)
    prefix_instructions = _build_prefix_counts(instruction_signal_flags)

    component_header_indices = _resolve_component_header_indices(
        units,
        overrides=overrides,
        enabled=config.enable_for_the_guardrail,
    )

    boundaries: list[BoundaryDecision] = []
    rejected: list[dict[str, Any]] = []
    last_boundary = 0
    total_units = len(units)

    for idx in range(1, total_units):
        unit = units[idx]
        reasons: list[str] = []
        rejection_reason: str | None = None
        if not _is_title_like(unit):
            rejection_reason = "not_title_like"
        elif idx in component_header_indices:
            rejection_reason = "component_header_guardrail"
        else:
            left_ingredient = _range_count(prefix_ingredients, 0, idx)
            left_instruction = _range_count(prefix_instructions, 0, idx)
            right_ingredient = _range_count(prefix_ingredients, idx, total_units)
            right_instruction = _range_count(prefix_instructions, idx, total_units)
            if (
                left_ingredient < min_ingredient_lines
                or left_instruction < min_instruction_lines
            ):
                rejection_reason = "left_section_coverage_below_threshold"
            elif (
                right_ingredient < min_ingredient_lines
                or right_instruction < min_instruction_lines
            ):
                rejection_reason = "right_section_coverage_below_threshold"
            elif idx - last_boundary < 2:
                rejection_reason = "boundary_too_close"
            elif not _has_local_recipe_signals(
                ingredient_signal_flags,
                instruction_signal_flags,
                start=idx,
                stop=min(total_units, idx + 24),
            ):
                rejection_reason = "insufficient_local_recipe_signals"
            else:
                reasons.extend(
                    (
                        "title_like_boundary",
                        "section_coverage_threshold_met",
                        "local_recipe_signals_present",
                    )
                )
                boundaries.append(BoundaryDecision(index=idx, reasons=tuple(reasons)))
                last_boundary = idx
                continue

        rejected.append(
            {
                "index": idx,
                "text": unit.text,
                "reason": rejection_reason,
            }
        )

    if not boundaries:
        return MultiRecipeSplitResult(
            spans=(CandidateSpan(start=0, end=total_units, reasons=("no_split",)),),
            boundaries=(),
            trace=_trace_payload(
                config=config,
                units=units,
                boundaries=(),
                rejected=rejected,
                component_header_indices=component_header_indices,
            ),
        )

    starts = [0] + [decision.index for decision in boundaries]
    spans: list[CandidateSpan] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else total_units
        if end <= start:
            continue
        if idx == 0:
            reasons = ("initial_span",)
        else:
            reasons = boundaries[idx - 1].reasons
        spans.append(CandidateSpan(start=start, end=end, reasons=tuple(reasons)))

    return MultiRecipeSplitResult(
        spans=tuple(spans),
        boundaries=tuple(boundaries),
        trace=_trace_payload(
            config=config,
            units=units,
            boundaries=boundaries,
            rejected=rejected,
            component_header_indices=component_header_indices,
        ),
    )


def _normalize_backend(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"off", "rules_v1"}:
        return normalized
    return "rules_v1"


def _build_prefix_counts(flags: Sequence[bool]) -> list[int]:
    counts = [0]
    for flag in flags:
        counts.append(counts[-1] + (1 if flag else 0))
    return counts


def _range_count(prefix: Sequence[int], start: int, end: int) -> int:
    return int(prefix[end] - prefix[start])


def _has_local_recipe_signals(
    ingredient_flags: Sequence[bool],
    instruction_flags: Sequence[bool],
    *,
    start: int,
    stop: int,
) -> bool:
    ingredient_seen = False
    instruction_seen = False
    for idx in range(start, stop):
        if idx >= len(ingredient_flags) or idx >= len(instruction_flags):
            break
        if ingredient_flags[idx]:
            ingredient_seen = True
        if instruction_flags[idx]:
            instruction_seen = True
        if ingredient_seen and instruction_seen:
            return True
    return False


def _resolve_component_header_indices(
    units: Sequence[_Unit],
    *,
    overrides: ParsingOverrides | None,
    enabled: bool,
) -> tuple[int, ...]:
    if not enabled:
        return ()
    lines = [unit.text for unit in units]
    detected = detect_sections_from_lines(lines, overrides=overrides)
    blocked: set[int] = set()
    for span in detected.spans:
        if span.header_index is None:
            continue
        key = str(span.key or "").strip().lower()
        if key in _MAIN_SECTION_KEYS:
            continue
        blocked.add(span.header_index)
    return tuple(sorted(blocked))


def _is_ingredient_signal_line(unit: _Unit) -> bool:
    if bool(unit.features.get("is_ingredient_header")):
        return True
    return _is_ingredient_content_line(unit)


def _is_instruction_signal_line(unit: _Unit) -> bool:
    if bool(unit.features.get("is_instruction_header")):
        return True
    return _is_instruction_content_line(unit)


def _is_ingredient_content_line(unit: _Unit) -> bool:
    if bool(unit.features.get("is_ingredient_header")):
        return False
    if bool(unit.features.get("is_ingredient_likely")) and not bool(
        unit.features.get("is_instruction_likely")
    ):
        return True
    if bool(unit.features.get("starts_with_quantity")) and not bool(
        unit.features.get("is_instruction_likely")
    ):
        return True
    if bool(unit.features.get("has_unit")) and not bool(
        unit.features.get("is_instruction_likely")
    ):
        return True
    if _BULLET_RE.match(unit.text):
        return True
    return False


def _is_instruction_content_line(unit: _Unit) -> bool:
    if bool(unit.features.get("is_instruction_header")):
        return False
    if bool(unit.features.get("is_instruction_likely")) and not bool(
        unit.features.get("is_ingredient_likely")
    ):
        return True
    if _INSTRUCTION_LEAD_RE.match(unit.text):
        return True
    if _NUMBERED_STEP_RE.match(unit.text):
        return True
    return False


def _is_title_like(unit: _Unit) -> bool:
    text = unit.text.strip()
    normalized_text = _MARKDOWN_TITLE_PREFIX_RE.sub("", text)
    normalized_text = _NUMBERED_TITLE_PREFIX_RE.sub("", normalized_text).strip()
    if not normalized_text:
        return False
    if not text:
        return False
    if len(normalized_text) > 90:
        return False
    if normalized_text.endswith("."):
        return False
    if bool(unit.features.get("is_ingredient_header")) or bool(
        unit.features.get("is_instruction_header")
    ):
        return False
    if bool(unit.features.get("is_yield")) or _YIELD_LINE_RE.match(normalized_text):
        return False
    if _is_ingredient_content_line(unit) or _is_instruction_content_line(unit):
        return False
    words = normalized_text.split()
    if len(words) > 12:
        return False
    first_char = normalized_text[0]
    if not first_char.isalpha():
        return False
    if not (first_char.isupper() or normalized_text.isupper()):
        return False
    return True


def _trace_payload(
    *,
    config: MultiRecipeSplitConfig,
    units: Sequence[_Unit],
    boundaries: Sequence[BoundaryDecision],
    rejected: Sequence[dict[str, Any]],
    component_header_indices: Sequence[int],
) -> dict[str, Any] | None:
    if not config.trace:
        return None
    return {
        "backend": _normalize_backend(config.backend),
        "unit_count": len(units),
        "candidate_indices": [
            {
                "index": idx,
                "text": unit.text,
            }
            for idx, unit in enumerate(units)
        ],
        "component_header_indices": list(component_header_indices),
        "accepted_boundaries": [
            {"index": boundary.index, "reasons": list(boundary.reasons)}
            for boundary in boundaries
        ],
        "rejected_boundaries": list(rejected),
    }


__all__ = [
    "BoundaryDecision",
    "CandidateSpan",
    "MultiRecipeSplitConfig",
    "MultiRecipeSplitResult",
    "split_candidate_blocks",
    "split_candidate_lines",
]
