from __future__ import annotations

from typing import Any, Mapping, Sequence

from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate


def serialize_line_role_file_row(
    *,
    candidate: AtomicLineCandidate,
    deterministic_label: str,
    escalation_reasons: Sequence[str],
) -> dict[str, Any]:
    return {
        "atomic_index": int(candidate.atomic_index),
        "block_index": int(candidate.block_index),
        "block_id": str(candidate.block_id),
        "recipe_id": candidate.recipe_id,
        "within_recipe_span": candidate.within_recipe_span,
        "deterministic_label": str(deterministic_label or "OTHER"),
        "rule_tags": list(candidate.rule_tags),
        "escalation_reasons": list(escalation_reasons),
        "current_line": str(candidate.text),
    }


def serialize_line_role_debug_context_row(
    *,
    candidate: AtomicLineCandidate,
) -> dict[str, Any]:
    return {
        "atomic_index": int(candidate.atomic_index),
        "current_line": str(candidate.text),
    }


def serialize_line_role_debug_context_row_from_mapping(
    row: Mapping[str, Any],
) -> dict[str, Any] | None:
    try:
        atomic_index = int(row.get("atomic_index"))
    except (AttributeError, TypeError, ValueError):
        return None
    return {
        "atomic_index": atomic_index,
        "current_line": str(row.get("current_line") or ""),
    }


def serialize_line_role_model_context_row(
    *,
    candidate: AtomicLineCandidate,
) -> list[Any]:
    return [
        int(candidate.atomic_index),
        str(candidate.text),
    ]
