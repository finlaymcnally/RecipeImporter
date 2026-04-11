from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cookimport.labelstudio.label_config_freeform import normalize_freeform_label
from cookimport.llm.codex_exec_runner import (
    CodexExecRunResult,
    summarize_direct_telemetry_rows,
)
from cookimport.parsing.line_role_workspace_tools import validate_line_role_output_payload

from .contracts import (
    CANONICAL_LINE_ROLE_ALLOWED_LABELS,
    CanonicalLineRolePrediction,
)
from .planning import ShardManifestEntryV1
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate


def _coerce_shard_input_rows(
    shard: ShardManifestEntryV1,
) -> list[tuple[int, str]]:
    rows_payload = list((dict(shard.input_payload or {})).get("rows") or [])
    rows: list[tuple[int, str]] = []
    for row in rows_payload:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        try:
            atomic_index = int(row[0])
        except (TypeError, ValueError):
            continue
        text_value = row[2] if len(row) >= 3 else row[1]
        rows.append((atomic_index, str(text_value or "")))
    return rows


def _line_role_packet_row_id(index: int) -> str:
    return f"r{index + 1:02d}"


def _translate_line_role_packet_local_ordinal_rows(
    *,
    ordered_rows: Sequence[tuple[int, str]],
    rows_payload: Sequence[Any],
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    if not rows_payload:
        return None, None
    ordinal_values: list[int] = []
    normalized_rows: list[dict[str, Any]] = []
    for row in rows_payload:
        if not isinstance(row, Mapping):
            return None, None
        row_dict = dict(row)
        if str(row_dict.get("row_id") or "").strip():
            return None, None
        if row_dict.get("atomic_index") is None:
            return None, None
        try:
            ordinal_value = int(row_dict.get("atomic_index"))
        except (TypeError, ValueError):
            return None, None
        ordinal_values.append(ordinal_value)
        normalized_rows.append(row_dict)
    row_count = len(ordered_rows)
    returned_row_count = len(normalized_rows)
    if row_count == 0 or returned_row_count == 0 or returned_row_count > row_count + 1:
        return None, None
    ordinal_base: int | None = None
    if ordinal_values == list(range(returned_row_count)):
        ordinal_base = 0
    elif ordinal_values == list(range(1, returned_row_count + 1)):
        ordinal_base = 1
    if ordinal_base is None:
        return None, None
    trimmed_trailing_row_count = 0
    translated_source_rows = normalized_rows
    translated_ordinal_values = ordinal_values
    if returned_row_count == row_count + 1:
        expected_with_spill = list(range(ordinal_base, ordinal_base + returned_row_count))
        if ordinal_values != expected_with_spill:
            return None, None
        trimmed_trailing_row_count = 1
        translated_source_rows = normalized_rows[:row_count]
        translated_ordinal_values = ordinal_values[:row_count]
    translated_rows: list[dict[str, Any]] = []
    for row_dict, ordinal_value in zip(
        translated_source_rows,
        translated_ordinal_values,
        strict=False,
    ):
        ordered_index = ordinal_value - ordinal_base
        if ordered_index < 0 or ordered_index >= row_count:
            return None, None
        translated_rows.append(
            {
                **row_dict,
                "atomic_index": int(ordered_rows[ordered_index][0]),
            }
        )
    missing_row_ids = [
        _line_role_packet_row_id(index)
        for index in range(len(translated_rows), row_count)
    ]
    response_mode = "complete"
    if trimmed_trailing_row_count:
        response_mode = "trimmed_trailing_spill"
    elif len(translated_rows) < row_count:
        response_mode = "prefix"
    return translated_rows, {
        "atomic_index_alias_salvage": {
            "applied": True,
            "alias_kind": "packet_local_ordinal",
            "ordinal_base": ordinal_base,
            "salvaged_row_count": len(translated_rows),
            "returned_row_count": returned_row_count,
            "expected_row_count": row_count,
            "response_mode": response_mode,
            "trimmed_trailing_row_count": trimmed_trailing_row_count,
        },
        "returned_row_ids": [
            _line_role_packet_row_id(index) for index in range(len(translated_rows))
        ],
        "missing_row_ids": missing_row_ids,
        "duplicate_row_ids": [],
        "unknown_row_ids": [],
    }


def _translate_line_role_ordered_labels_to_atomic_indices(
    *,
    ordered_rows: Sequence[tuple[int, str]],
    labels_payload: Sequence[Any],
) -> tuple[dict[str, Any], tuple[str, ...], dict[str, Any]]:
    translated_rows: list[dict[str, Any]] = []
    for index, label_value in enumerate(labels_payload):
        row_payload: dict[str, Any] = {"label": label_value}
        if index < len(ordered_rows):
            row_payload["atomic_index"] = int(ordered_rows[index][0])
        translated_rows.append(row_payload)
    return (
        {"rows": translated_rows},
        (),
        {
            "ordered_label_vector": {
                "applied": True,
                "returned_label_count": len(labels_payload),
                "expected_row_count": len(ordered_rows),
            }
        },
    )


def _translate_line_role_output_to_atomic_indices(
    *,
    shard: ShardManifestEntryV1,
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...], dict[str, Any]]:
    ordered_rows = _coerce_shard_input_rows(shard)
    labels_payload = payload.get("labels")
    if isinstance(labels_payload, list) and not isinstance(payload.get("rows"), list):
        return _translate_line_role_ordered_labels_to_atomic_indices(
            ordered_rows=ordered_rows,
            labels_payload=labels_payload,
        )
    rows_payload = payload.get("rows")
    if not isinstance(rows_payload, list):
        return dict(payload), (), {}
    translated_ordinal_rows, ordinal_metadata = _translate_line_role_packet_local_ordinal_rows(
        ordered_rows=ordered_rows,
        rows_payload=rows_payload,
    )
    if translated_ordinal_rows is not None:
        return {
            **dict(payload),
            "rows": translated_ordinal_rows,
        }, (), dict(ordinal_metadata or {})
    atomic_index_by_row_id = {
        _line_role_packet_row_id(index): atomic_index
        for index, (atomic_index, _text) in enumerate(ordered_rows)
    }
    translated_rows: list[dict[str, Any]] = []
    seen_row_ids: set[str] = set()
    duplicate_row_ids: set[str] = set()
    unknown_row_ids: set[str] = set()
    used_row_ids: list[str] = []
    saw_row_id_mode = False
    for row in rows_payload:
        if not isinstance(row, Mapping):
            translated_rows.append(dict(row) if isinstance(row, dict) else {"value": row})
            continue
        row_dict = dict(row)
        if row_dict.get("atomic_index") is not None:
            translated_rows.append(row_dict)
            continue
        row_id = str(row_dict.get("row_id") or "").strip()
        if not row_id:
            translated_rows.append(row_dict)
            continue
        saw_row_id_mode = True
        if row_id in seen_row_ids:
            duplicate_row_ids.add(row_id)
            continue
        seen_row_ids.add(row_id)
        atomic_index = atomic_index_by_row_id.get(row_id)
        if atomic_index is None:
            unknown_row_ids.add(row_id)
            continue
        used_row_ids.append(row_id)
        translated_rows.append(
            {
                **row_dict,
                "atomic_index": atomic_index,
            }
        )
    if not saw_row_id_mode:
        return dict(payload), (), {}
    expected_row_ids = list(atomic_index_by_row_id.keys())
    missing_row_ids = [
        row_id for row_id in expected_row_ids if row_id not in set(used_row_ids)
    ]
    translation_errors: list[str] = []
    if missing_row_ids:
        translation_errors.append("missing_row_ids:" + ",".join(missing_row_ids))
    translation_errors.extend(
        f"duplicate_row_id:{row_id}" for row_id in sorted(duplicate_row_ids)
    )
    translation_errors.extend(
        f"unknown_row_id:{row_id}" for row_id in sorted(unknown_row_ids)
    )
    return (
        {
            **dict(payload),
            "rows": translated_rows,
        },
        tuple(translation_errors),
        {
            "returned_row_ids": used_row_ids,
            "missing_row_ids": missing_row_ids,
            "duplicate_row_ids": sorted(duplicate_row_ids),
            "unknown_row_ids": sorted(unknown_row_ids),
        },
    )


def _validate_line_role_shard_proposal(
    shard: ShardManifestEntryV1,
    payload: dict[str, Any],
    *,
    frozen_rows_by_atomic_index: Mapping[int, Mapping[str, Any]]
    | Sequence[Mapping[str, Any]]
    | None = None,
) -> tuple[bool, Sequence[str], dict[str, Any] | None]:
    errors, metadata = validate_line_role_output_payload(
        {"input_payload": shard.input_payload},
        payload,
        frozen_rows_by_atomic_index=frozen_rows_by_atomic_index,
    )
    mapped_errors: list[str] = []
    row_errors_by_atomic_index = {
        int(key): list(value)
        for key, value in (metadata or {}).get("row_errors_by_atomic_index", {}).items()
        if str(key).strip()
    }
    for error in errors:
        cleaned = str(error).strip()
        if not cleaned:
            continue
        if cleaned == "payload_not_object":
            mapped_errors.append("proposal_not_a_json_object")
        elif cleaned == "rows_not_list":
            mapped_errors.append("rows_missing_or_not_a_list")
        elif cleaned == "invalid_atomic_index":
            mapped_errors.append("atomic_index_missing")
        elif cleaned == "row_not_object":
            mapped_errors.append("row_not_a_json_object")
        else:
            mapped_errors.append(cleaned)
    rows_payload = payload.get("rows") if isinstance(payload, Mapping) else []
    for atomic_index, row_errors in sorted(row_errors_by_atomic_index.items()):
        row_payload = next(
            (
                row
                for row in rows_payload
                if isinstance(row, Mapping)
                and row.get("atomic_index") is not None
                and str(row.get("atomic_index")).strip()
                and int(row.get("atomic_index")) == atomic_index
            ),
            {},
        )
        for row_error in row_errors:
            if row_error == "invalid_label":
                mapped_errors.append(
                    f"invalid_label:{atomic_index}:{str(row_payload.get('label') or '').strip()}"
                )
            elif row_error == "unowned_atomic_index":
                mapped_errors.append(f"unowned_atomic_index:{atomic_index}")
            elif row_error == "duplicate_atomic_index":
                mapped_errors.append(f"duplicate_atomic_index:{atomic_index}")
    missing_owned = [
        int(value)
        for value in (metadata or {}).get("expected_atomic_indices", [])
        if str(value).strip()
        and int(value)
        not in {
            int(index)
            for index in (metadata or {}).get("accepted_atomic_indices", [])
            if str(index).strip()
        }
        and int(value)
        not in {
            int(index)
            for index in (metadata or {}).get("invalid_row_atomic_indices", [])
            if str(index).strip()
        }
    ]
    if missing_owned:
        mapped_errors.append(
            "missing_owned_atomic_indices:" + ",".join(str(value) for value in missing_owned)
        )
    deduped_errors = tuple(dict.fromkeys(mapped_errors))
    runtime_metadata = dict(metadata or {})
    runtime_metadata["validated_row_count"] = len(
        runtime_metadata.get("accepted_atomic_indices") or []
    )
    return len(deduped_errors) == 0, deduped_errors, runtime_metadata


def _build_line_role_semantic_guard_candidates(
    *,
    shard: ShardManifestEntryV1,
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
) -> dict[int, AtomicLineCandidate]:
    candidates: dict[int, AtomicLineCandidate] = {}
    for atomic_index, text in _coerce_shard_input_rows(shard):
        baseline = deterministic_baseline_by_atomic_index.get(int(atomic_index))
        candidates[int(atomic_index)] = AtomicLineCandidate(
            recipe_id=baseline.recipe_id if baseline is not None else None,
            block_id=str(baseline.block_id) if baseline is not None else f"semantic-guard:{atomic_index}",
            block_index=(
                int(baseline.block_index)
                if baseline is not None and baseline.block_index is not None
                else int(atomic_index)
            ),
            atomic_index=int(atomic_index),
            text=str(text or ""),
            within_recipe_span=baseline.within_recipe_span if baseline is not None else None,
            rule_tags=list(baseline.reason_tags if baseline is not None else []),
        )
    return candidates


def _line_role_prediction_rows_by_atomic_index(
    payload: Mapping[str, Any] | None,
) -> dict[int, dict[str, Any]]:
    rows_payload = list((payload or {}).get("rows") or [])
    rows_by_atomic_index: dict[int, dict[str, Any]] = {}
    for row in rows_payload:
        if not isinstance(row, Mapping):
            continue
        try:
            atomic_index = int(row.get("atomic_index"))
        except (TypeError, ValueError):
            continue
        rows_by_atomic_index[atomic_index] = dict(row)
    return rows_by_atomic_index


def _line_role_semantic_guard_candidate_signals(
    *,
    candidate: AtomicLineCandidate,
    candidates_by_atomic_index: Mapping[int, AtomicLineCandidate],
) -> set[str]:
    from . import policy as policy_module

    signals: set[str] = set()
    if policy_module._looks_recipe_title_with_context(  # noqa: SLF001
        candidate,
        by_atomic_index=dict(candidates_by_atomic_index),
    ):
        signals.add("RECIPE_TITLE")
    if policy_module._looks_strict_yield_header(candidate.text):  # noqa: SLF001
        signals.add("YIELD_LINE")
    if policy_module._looks_obvious_ingredient(candidate):  # noqa: SLF001
        signals.add("INGREDIENT_LINE")
    if policy_module._howto_section_label_allowed(  # noqa: SLF001
        candidate,
        by_atomic_index=dict(candidates_by_atomic_index),
    ):
        signals.add("HOWTO_SECTION")
    if (
        policy_module._looks_note_text(candidate.text)  # noqa: SLF001
        or policy_module._looks_storage_or_serving_note(candidate.text)  # noqa: SLF001
        or policy_module._looks_recipe_note_prose(candidate.text)  # noqa: SLF001
    ):
        signals.add("RECIPE_NOTES")
    if (
        "RECIPE_TITLE" not in signals
        and "YIELD_LINE" not in signals
        and "INGREDIENT_LINE" not in signals
        and "RECIPE_NOTES" not in signals
        and (
            policy_module._looks_direct_instruction_start(candidate)  # noqa: SLF001
            or policy_module._looks_instructional_neighbor(candidate)  # noqa: SLF001
        )
    ):
        signals.add("INSTRUCTION_LINE")
    if (
        "RECIPE_TITLE" not in signals
        and "YIELD_LINE" not in signals
        and "INGREDIENT_LINE" not in signals
        and "HOWTO_SECTION" not in signals
        and "RECIPE_NOTES" not in signals
        and "INSTRUCTION_LINE" not in signals
        and (
            policy_module._variant_label_allowed(  # noqa: SLF001
                candidate,
                by_atomic_index=dict(candidates_by_atomic_index),
            )
            or policy_module._looks_variant_run_body_line(  # noqa: SLF001
                candidate,
                by_atomic_index=dict(candidates_by_atomic_index),
            )
        )
    ):
        signals.add("RECIPE_VARIANT")
    return signals


def _line_role_semantic_guard_neighbor_labels(
    *,
    atomic_index: int,
    predicted_rows_by_atomic_index: Mapping[int, Mapping[str, Any]],
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
    candidates_by_atomic_index: Mapping[int, AtomicLineCandidate],
    radius: int = 2,
) -> set[str]:
    labels: set[str] = set()
    for offset in range(1, max(1, int(radius)) + 1):
        for neighbor_index in (atomic_index - offset, atomic_index + offset):
            predicted_row = predicted_rows_by_atomic_index.get(neighbor_index)
            if isinstance(predicted_row, Mapping):
                rendered = str(predicted_row.get("label") or "").strip().upper()
                if rendered:
                    labels.add(rendered)
            baseline = deterministic_baseline_by_atomic_index.get(neighbor_index)
            if baseline is not None:
                rendered = str(baseline.label or "").strip().upper()
                if rendered:
                    labels.add(rendered)
            neighbor_candidate = candidates_by_atomic_index.get(neighbor_index)
            if neighbor_candidate is not None:
                labels.update(
                    _line_role_semantic_guard_candidate_signals(
                        candidate=neighbor_candidate,
                        candidates_by_atomic_index=candidates_by_atomic_index,
                    )
                )
    return labels


def _line_role_semantic_guard_has_recipe_anchor(
    *,
    atomic_index: int,
    predicted_rows_by_atomic_index: Mapping[int, Mapping[str, Any]],
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
    candidates_by_atomic_index: Mapping[int, AtomicLineCandidate],
    required_labels: Sequence[str] | None = None,
    radius: int = 2,
) -> bool:
    recipe_anchor_labels = {
        "RECIPE_TITLE",
        "YIELD_LINE",
        "INGREDIENT_LINE",
        "INSTRUCTION_LINE",
        "HOWTO_SECTION",
        "RECIPE_VARIANT",
        "RECIPE_NOTES",
    }
    neighbor_labels = _line_role_semantic_guard_neighbor_labels(
        atomic_index=atomic_index,
        predicted_rows_by_atomic_index=predicted_rows_by_atomic_index,
        deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
        candidates_by_atomic_index=candidates_by_atomic_index,
        radius=radius,
    )
    if required_labels:
        return bool(set(required_labels) & neighbor_labels)
    return bool(recipe_anchor_labels & neighbor_labels)


def _line_role_semantic_guard_context_text(
    *,
    atomic_index: int,
    candidates_by_atomic_index: Mapping[int, AtomicLineCandidate],
) -> str:
    context_parts: list[str] = []
    for neighbor_index in (atomic_index - 1, atomic_index + 1, atomic_index + 2):
        neighbor = candidates_by_atomic_index.get(neighbor_index)
        if neighbor is None:
            continue
        rendered = str(neighbor.text or "").strip()
        if not rendered:
            continue
        prefix = (
            "previous row"
            if neighbor_index == atomic_index - 1
            else "next row"
            if neighbor_index == atomic_index + 1
            else "next-next row"
        )
        context_parts.append(f"{prefix}: `{rendered}`")
    return "; ".join(context_parts)


def _line_role_semantic_guard_build_diagnostic(
    *,
    atomic_index: int,
    code: str,
    suggested_label: str,
    observed_label: str,
    candidate: AtomicLineCandidate,
    candidates_by_atomic_index: Mapping[int, AtomicLineCandidate],
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
    candidate_signals: Sequence[str] | None = None,
    neighbor_signals: Sequence[str] | None = None,
) -> dict[str, Any]:
    baseline = deterministic_baseline_by_atomic_index.get(int(atomic_index))
    row_text = str(candidate.text or "").strip()
    context_text = _line_role_semantic_guard_context_text(
        atomic_index=atomic_index,
        candidates_by_atomic_index=candidates_by_atomic_index,
    )
    if code == "recipe_title_reset":
        hint = (
            f"This line looks like a fresh recipe start. Re-check whether `{row_text}` should be "
            f"`RECIPE_TITLE` because nearby rows show recipe scaffolding ({context_text})."
        )
    elif code == "recipe_yield_anchor":
        hint = (
            f"This line looks like a strict yield/serving line. Re-check whether `{row_text}` should be "
            f"`YIELD_LINE` because it sits inside recipe-start context ({context_text})."
        )
    elif code == "recipe_ingredient_anchor":
        hint = (
            f"This line looks like an ingredient entry. Re-check whether `{row_text}` should be "
            f"`INGREDIENT_LINE` because nearby rows indicate an active recipe structure ({context_text})."
        )
    elif code == "recipe_instruction_anchor":
        hint = (
            f"This line looks like recipe method text. Re-check whether `{row_text}` should be "
            f"`INSTRUCTION_LINE` because nearby rows indicate an active recipe body ({context_text})."
        )
    elif code == "recipe_note_anchor":
        hint = (
            f"This line looks like recipe-local note text. Re-check whether `{row_text}` should be "
            f"`RECIPE_NOTES` because it follows active recipe context ({context_text})."
        )
    else:
        hint = (
            f"This line looks like recipe-local variant text. Re-check whether `{row_text}` should be "
            f"`RECIPE_VARIANT` because nearby rows indicate a variant run ({context_text})."
        )
    return {
        "atomic_index": int(atomic_index),
        "code": str(code),
        "observed_label": str(observed_label or "").strip().upper(),
        "suggested_label": str(suggested_label or "").strip().upper(),
        "baseline_label": str(baseline.label or "").strip().upper() if baseline is not None else None,
        "candidate_signals": sorted(
            str(value).strip().upper()
            for value in (candidate_signals or [])
            if str(value).strip()
        ),
        "neighbor_signals": sorted(
            str(value).strip().upper()
            for value in (neighbor_signals or [])
            if str(value).strip()
        ),
        "line_text": row_text,
        "hint": hint,
        "context_text": context_text,
    }


def _build_line_role_semantic_diagnostics(
    *,
    shard: ShardManifestEntryV1,
    payload: Mapping[str, Any] | None,
    accepted_atomic_indices: Sequence[int],
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
) -> list[dict[str, Any]]:
    if not accepted_atomic_indices:
        return []
    candidates_by_atomic_index = _build_line_role_semantic_guard_candidates(
        shard=shard,
        deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
    )
    predicted_rows_by_atomic_index = _line_role_prediction_rows_by_atomic_index(payload)
    diagnostics: list[dict[str, Any]] = []
    accepted_set = {int(value) for value in accepted_atomic_indices}
    for atomic_index in [int(value) for value in shard.owned_ids]:
        if atomic_index not in accepted_set:
            continue
        candidate = candidates_by_atomic_index.get(atomic_index)
        predicted_row = predicted_rows_by_atomic_index.get(atomic_index)
        if candidate is None or not isinstance(predicted_row, Mapping):
            continue
        observed_label = str(predicted_row.get("label") or "").strip().upper()
        if not observed_label:
            continue
        candidate_signals = _line_role_semantic_guard_candidate_signals(
            candidate=candidate,
            candidates_by_atomic_index=candidates_by_atomic_index,
        )
        neighbor_signals = _line_role_semantic_guard_neighbor_labels(
            atomic_index=atomic_index,
            predicted_rows_by_atomic_index=predicted_rows_by_atomic_index,
            deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
            candidates_by_atomic_index=candidates_by_atomic_index,
        )
        diagnostic: dict[str, Any] | None = None
        if (
            "RECIPE_TITLE" in candidate_signals
            and observed_label != "RECIPE_TITLE"
            and _line_role_semantic_guard_has_recipe_anchor(
                atomic_index=atomic_index,
                predicted_rows_by_atomic_index=predicted_rows_by_atomic_index,
                deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
                candidates_by_atomic_index=candidates_by_atomic_index,
                required_labels=(
                    "YIELD_LINE",
                    "INGREDIENT_LINE",
                    "RECIPE_VARIANT",
                ),
            )
        ):
            diagnostic = _line_role_semantic_guard_build_diagnostic(
                atomic_index=atomic_index,
                code="recipe_title_reset",
                suggested_label="RECIPE_TITLE",
                observed_label=observed_label,
                candidate=candidate,
                candidates_by_atomic_index=candidates_by_atomic_index,
                deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
                candidate_signals=candidate_signals,
                neighbor_signals=neighbor_signals,
            )
        elif (
            "YIELD_LINE" in candidate_signals
            and observed_label != "YIELD_LINE"
            and _line_role_semantic_guard_has_recipe_anchor(
                atomic_index=atomic_index,
                predicted_rows_by_atomic_index=predicted_rows_by_atomic_index,
                deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
                candidates_by_atomic_index=candidates_by_atomic_index,
                required_labels=(
                    "RECIPE_TITLE",
                    "INGREDIENT_LINE",
                    "INSTRUCTION_LINE",
                    "HOWTO_SECTION",
                    "RECIPE_VARIANT",
                ),
            )
        ):
            diagnostic = _line_role_semantic_guard_build_diagnostic(
                atomic_index=atomic_index,
                code="recipe_yield_anchor",
                suggested_label="YIELD_LINE",
                observed_label=observed_label,
                candidate=candidate,
                candidates_by_atomic_index=candidates_by_atomic_index,
                deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
                candidate_signals=candidate_signals,
                neighbor_signals=neighbor_signals,
            )
        elif (
            "INGREDIENT_LINE" in candidate_signals
            and _line_role_semantic_guard_has_recipe_anchor(
                atomic_index=atomic_index,
                predicted_rows_by_atomic_index=predicted_rows_by_atomic_index,
                deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
                candidates_by_atomic_index=candidates_by_atomic_index,
                required_labels=(
                    "RECIPE_TITLE",
                    "YIELD_LINE",
                    "INGREDIENT_LINE",
                    "INSTRUCTION_LINE",
                    "HOWTO_SECTION",
                    "RECIPE_VARIANT",
                ),
            )
            and observed_label != "INGREDIENT_LINE"
        ):
            diagnostic = _line_role_semantic_guard_build_diagnostic(
                atomic_index=atomic_index,
                code="recipe_ingredient_anchor",
                suggested_label="INGREDIENT_LINE",
                observed_label=observed_label,
                candidate=candidate,
                candidates_by_atomic_index=candidates_by_atomic_index,
                deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
                candidate_signals=candidate_signals,
                neighbor_signals=neighbor_signals,
            )
        elif (
            "INSTRUCTION_LINE" in candidate_signals
            and (
                _line_role_semantic_guard_has_recipe_anchor(
                    atomic_index=atomic_index,
                    predicted_rows_by_atomic_index=predicted_rows_by_atomic_index,
                    deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
                    candidates_by_atomic_index=candidates_by_atomic_index,
                    required_labels=(
                        "YIELD_LINE",
                        "INGREDIENT_LINE",
                        "RECIPE_VARIANT",
                    ),
                )
                or (
                    candidate.within_recipe_span is True
                    and _line_role_semantic_guard_has_recipe_anchor(
                        atomic_index=atomic_index,
                        predicted_rows_by_atomic_index=predicted_rows_by_atomic_index,
                        deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
                        candidates_by_atomic_index=candidates_by_atomic_index,
                        required_labels=("RECIPE_TITLE",),
                    )
                )
            )
            and observed_label not in {"INSTRUCTION_LINE", "RECIPE_VARIANT"}
        ):
            diagnostic = _line_role_semantic_guard_build_diagnostic(
                atomic_index=atomic_index,
                code="recipe_instruction_anchor",
                suggested_label="INSTRUCTION_LINE",
                observed_label=observed_label,
                candidate=candidate,
                candidates_by_atomic_index=candidates_by_atomic_index,
                deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
                candidate_signals=candidate_signals,
                neighbor_signals=neighbor_signals,
            )
        elif (
            "RECIPE_NOTES" in candidate_signals
            and _line_role_semantic_guard_has_recipe_anchor(
                atomic_index=atomic_index,
                predicted_rows_by_atomic_index=predicted_rows_by_atomic_index,
                deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
                candidates_by_atomic_index=candidates_by_atomic_index,
                required_labels=(
                    "RECIPE_TITLE",
                    "YIELD_LINE",
                    "INGREDIENT_LINE",
                    "INSTRUCTION_LINE",
                    "HOWTO_SECTION",
                    "RECIPE_VARIANT",
                ),
            )
            and observed_label != "RECIPE_NOTES"
        ):
            diagnostic = _line_role_semantic_guard_build_diagnostic(
                atomic_index=atomic_index,
                code="recipe_note_anchor",
                suggested_label="RECIPE_NOTES",
                observed_label=observed_label,
                candidate=candidate,
                candidates_by_atomic_index=candidates_by_atomic_index,
                deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
                candidate_signals=candidate_signals,
                neighbor_signals=neighbor_signals,
            )
        elif (
            "RECIPE_VARIANT" in candidate_signals
            and _line_role_semantic_guard_has_recipe_anchor(
                atomic_index=atomic_index,
                predicted_rows_by_atomic_index=predicted_rows_by_atomic_index,
                deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
                candidates_by_atomic_index=candidates_by_atomic_index,
                required_labels=(
                    "RECIPE_TITLE",
                    "YIELD_LINE",
                    "INGREDIENT_LINE",
                    "INSTRUCTION_LINE",
                    "HOWTO_SECTION",
                    "RECIPE_VARIANT",
                ),
            )
            and observed_label not in {"RECIPE_VARIANT", "RECIPE_TITLE"}
        ):
            diagnostic = _line_role_semantic_guard_build_diagnostic(
                atomic_index=atomic_index,
                code="recipe_variant_anchor",
                suggested_label="RECIPE_VARIANT",
                observed_label=observed_label,
                candidate=candidate,
                candidates_by_atomic_index=candidates_by_atomic_index,
                deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
                candidate_signals=candidate_signals,
                neighbor_signals=neighbor_signals,
            )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
    return diagnostics


def _apply_line_role_semantic_guard(
    *,
    shard: ShardManifestEntryV1,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
    proposal_status: str,
    payload: Mapping[str, Any] | None,
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
) -> tuple[tuple[str, ...], dict[str, Any], str]:
    metadata = dict(validation_metadata or {})
    accepted_atomic_indices = [
        int(value)
        for value in (metadata.get("accepted_atomic_indices") or [])
        if str(value).strip()
    ]
    semantic_diagnostics = _build_line_role_semantic_diagnostics(
        shard=shard,
        payload=payload,
        accepted_atomic_indices=accepted_atomic_indices,
        deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
    )
    if not semantic_diagnostics:
        return tuple(validation_errors), metadata, proposal_status

    rejected_atomic_indices = [
        int(diagnostic["atomic_index"])
        for diagnostic in semantic_diagnostics
        if str(diagnostic.get("atomic_index")).strip()
    ]
    rejected_atomic_index_set = set(rejected_atomic_indices)
    accepted_rows = [
        dict(row)
        for row in (metadata.get("accepted_rows") or [])
        if isinstance(row, Mapping)
        and row.get("atomic_index") is not None
        and int(row.get("atomic_index")) not in rejected_atomic_index_set
    ]
    ordered_atomic_indices = [int(value) for value in shard.owned_ids]
    accepted_atomic_indices = [
        int(row["atomic_index"])
        for row in accepted_rows
        if row.get("atomic_index") is not None and str(row.get("atomic_index")).strip()
    ]
    accepted_atomic_index_set = set(accepted_atomic_indices)
    unresolved_atomic_indices = [
        atomic_index
        for atomic_index in ordered_atomic_indices
        if atomic_index not in accepted_atomic_index_set
    ]
    row_errors_by_atomic_index = {
        str(key): list(value)
        for key, value in (metadata.get("row_errors_by_atomic_index") or {}).items()
        if str(key).strip()
    }
    invalid_row_atomic_indices = {
        int(value)
        for value in (metadata.get("invalid_row_atomic_indices") or [])
        if str(value).strip()
    }
    semantic_repair_hints_by_atomic_index = {
        str(diagnostic["atomic_index"]): str(diagnostic.get("hint") or "").strip()
        for diagnostic in semantic_diagnostics
        if str(diagnostic.get("atomic_index")).strip()
        and str(diagnostic.get("hint") or "").strip()
    }
    semantic_errors: list[str] = []
    for diagnostic in semantic_diagnostics:
        atomic_index = int(diagnostic["atomic_index"])
        code = str(diagnostic.get("code") or "semantic_invariant_violation").strip()
        semantic_errors.append(f"semantic_invariant_violation:{code}:{atomic_index}")
        invalid_row_atomic_indices.add(atomic_index)
        existing_errors = list(row_errors_by_atomic_index.get(str(atomic_index)) or [])
        existing_errors.append("semantic_invariant_violation")
        row_errors_by_atomic_index[str(atomic_index)] = sorted(set(existing_errors))
    merged_errors = tuple(
        dict.fromkeys(
            [
                *[str(error).strip() for error in validation_errors if str(error).strip()],
                *semantic_errors,
            ]
        )
    )
    metadata = {
        **metadata,
        "accepted_rows": accepted_rows,
        "accepted_atomic_indices": accepted_atomic_indices,
        "validated_row_count": len(accepted_atomic_indices),
        "unresolved_atomic_indices": unresolved_atomic_indices,
        "invalid_row_atomic_indices": sorted(invalid_row_atomic_indices),
        "row_errors_by_atomic_index": row_errors_by_atomic_index,
        "semantic_diagnostics": semantic_diagnostics,
        "semantic_rejected_atomic_indices": rejected_atomic_indices,
        "semantic_repair_hints_by_atomic_index": semantic_repair_hints_by_atomic_index,
    }
    return merged_errors, metadata, "invalid"


def _evaluate_line_role_response_with_pathology_guard(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
    validator: Callable[
        [ShardManifestEntryV1, dict[str, Any]],
        tuple[bool, Sequence[str], dict[str, Any] | None],
    ],
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    del deterministic_baseline_by_atomic_index
    return _evaluate_line_role_response(
        shard=shard,
        response_text=response_text,
        validator=validator,
    )


def _evaluate_line_role_workspace_response_with_pathology_guard(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
    frozen_rows_by_atomic_index: Mapping[int, Mapping[str, Any]]
    | Sequence[Mapping[str, Any]]
    | None = None,
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    del deterministic_baseline_by_atomic_index
    return _evaluate_line_role_response(
        shard=shard,
        response_text=response_text,
        validator=lambda proposal_shard, proposal_payload: _validate_line_role_shard_proposal(
            proposal_shard,
            proposal_payload,
            frozen_rows_by_atomic_index=frozen_rows_by_atomic_index,
        ),
    )

def _build_line_role_row_resolution(
    *,
    shard: ShardManifestEntryV1,
    validation_metadata: Mapping[str, Any] | None,
 ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    ordered_atomic_indices = [int(value) for value in shard.owned_ids]
    accepted_rows = []
    accepted_rows = [
        dict(row)
        for row in (validation_metadata or {}).get("accepted_rows", [])
        if isinstance(row, Mapping)
    ]
    accepted_by_atomic_index = {
        int(row["atomic_index"]): dict(row)
        for row in accepted_rows
        if row.get("atomic_index") is not None and str(row.get("atomic_index")).strip()
    }
    final_rows: list[dict[str, Any]] = []
    accepted_atomic_indices: list[int] = []
    for atomic_index in ordered_atomic_indices:
        accepted_row = accepted_by_atomic_index.get(atomic_index)
        if accepted_row is not None:
            final_rows.append(dict(accepted_row))
            accepted_atomic_indices.append(atomic_index)
    unresolved_atomic_indices = [
        atomic_index
        for atomic_index in ordered_atomic_indices
        if atomic_index not in set(accepted_atomic_indices)
    ]
    all_rows_resolved = not unresolved_atomic_indices
    resolution_metadata = {
        "accepted_atomic_indices": accepted_atomic_indices,
        "unresolved_atomic_indices": unresolved_atomic_indices,
        "accepted_row_count": len(accepted_atomic_indices),
        "unresolved_row_count": len(unresolved_atomic_indices),
        "all_rows_resolved": all_rows_resolved,
    }
    return (
        {"rows": final_rows} if all_rows_resolved else None,
        resolution_metadata,
    )

def _build_line_role_shard_status_row(
    *,
    shard: ShardManifestEntryV1,
    worker_id: str,
    state: str,
    last_attempt_type: str,
    output_path: Path | None,
    repair_path: Path | None,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
    row_resolution_metadata: Mapping[str, Any] | None,
    repair_attempted: bool,
    repair_status: str,
    resumed_from_existing_output: bool,
    fresh_session_recovery_metadata: Mapping[str, Any] | None = None,
    transport: str | None = None,
) -> dict[str, Any]:
    owned_row_count = len(tuple(shard.owned_ids))
    llm_authoritative_row_count = int(
        (row_resolution_metadata or {}).get("accepted_row_count") or 0
    )
    unresolved_row_count = int(
        (row_resolution_metadata or {}).get("unresolved_row_count") or 0
    )
    semantic_diagnostics = [
        dict(row)
        for row in (validation_metadata or {}).get("semantic_diagnostics", [])
        if isinstance(row, Mapping)
    ]
    semantic_row_count = len(
        {
            int(row.get("atomic_index"))
            for row in semantic_diagnostics
            if row.get("atomic_index") is not None and str(row.get("atomic_index")).strip()
        }
    )
    metadata = {
        "repair_attempted": bool(repair_attempted),
        "repair_status": str(repair_status or "not_attempted"),
        "output_path": str(output_path) if output_path is not None else None,
        "repair_path": str(repair_path) if repair_path is not None else None,
        "owned_row_count": owned_row_count,
        "llm_authoritative_row_count": llm_authoritative_row_count,
        "unresolved_row_count": unresolved_row_count,
        "suspicious_row_count": max(unresolved_row_count, semantic_row_count),
        "suspicious_shard": bool(unresolved_row_count or semantic_row_count),
        "semantic_diagnostics": semantic_diagnostics,
        "resumed_from_existing_output": bool(resumed_from_existing_output),
        "transport": str(transport or "").strip() or None,
        "validation_errors": [
            str(error).strip() for error in validation_errors if str(error).strip()
        ],
    }
    if validation_metadata:
        metadata["validation_metadata"] = dict(validation_metadata)
    if row_resolution_metadata:
        metadata["row_resolution"] = dict(row_resolution_metadata)
    if fresh_session_recovery_metadata:
        metadata["fresh_session_recovery"] = dict(fresh_session_recovery_metadata)
    return {
        "shard_id": shard.shard_id,
        "worker_id": worker_id,
        "owned_ids": [str(value).strip() for value in shard.owned_ids if str(value).strip()],
        "state": state,
        "terminal_outcome": state,
        "last_attempt_type": last_attempt_type,
        "metadata": metadata,
    }

def _summarize_direct_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return summarize_direct_telemetry_rows(rows)


def _render_codex_events_jsonl(events: Sequence[dict[str, Any]]) -> str:
    if not events:
        return ""
    return "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)


def _coerce_mapping_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _evaluate_line_role_response(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
    validator: Callable[[ShardManifestEntryV1, dict[str, Any]], tuple[bool, Sequence[str], dict[str, Any] | None]],
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    payload: dict[str, Any] | None = None
    validation_errors: tuple[str, ...] = ()
    validation_metadata: dict[str, Any] = {}
    proposal_status = "validated"
    cleaned_response_text = str(response_text or "").strip()
    if not cleaned_response_text:
        return None, ("missing_output_file",), {}, "missing_output"
    try:
        parsed_payload = json.loads(cleaned_response_text)
    except json.JSONDecodeError as exc:
        return None, ("response_json_invalid",), {"parse_error": str(exc)}, "invalid"
    if not isinstance(parsed_payload, dict):
        return (
            None,
            ("response_not_json_object",),
            {"response_type": type(parsed_payload).__name__},
            "invalid",
        )
    translated_payload, translation_errors, translation_metadata = (
        _translate_line_role_output_to_atomic_indices(
            shard=shard,
            payload=parsed_payload,
        )
    )
    payload = translated_payload
    valid, validation_errors, validation_metadata = validator(
        shard,
        translated_payload,
    )
    merged_errors = tuple(
        dict.fromkeys(
            [
                *[str(error).strip() for error in translation_errors if str(error).strip()],
                *[str(error).strip() for error in validation_errors if str(error).strip()],
            ]
        )
    )
    proposal_status = "validated" if valid and not translation_errors else "invalid"
    return payload, merged_errors, {**dict(validation_metadata or {}), **dict(translation_metadata or {})}, proposal_status


def _line_role_resume_reason_fields(*, resumed_from_existing_outputs: bool) -> tuple[str, str]:
    if resumed_from_existing_outputs:
        return "resumed_from_existing_outputs", "validated existing workspace outputs"
    return "completed", "validated worker output"


def _normalize_line_role_shard_outcome(
    *,
    run_result: CodexExecRunResult | None,
    proposal_status: str,
    watchdog_retry_status: str,
    repair_status: str,
    resumed_from_existing_outputs: bool,
    row_resolution_metadata: Mapping[str, Any] | None = None,
    fresh_session_recovery_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    def _with_fresh_session_recovery(result: dict[str, Any]) -> dict[str, Any]:
        if not fresh_session_recovery_metadata:
            return result
        return {
            **result,
            **{
                key: value
                for key, value in dict(fresh_session_recovery_metadata).items()
                if key
                in {
                    "fresh_session_recovery_attempted",
                    "fresh_session_recovery_status",
                    "fresh_session_recovery_count",
                    "fresh_session_recovery_skipped_reason",
                    "shared_retry_budget_spent",
                    "prior_session_reason_code",
                    "diagnosis_code",
                    "recommended_command",
                    "resume_summary",
                    "assessment_path",
                }
            },
        }

    raw_supervision_state = (
        str(run_result.supervision_state or "").strip() or None
        if run_result is not None
        else None
    )
    raw_supervision_reason_code = (
        str(run_result.supervision_reason_code or "").strip() or None
        if run_result is not None
        else None
    )
    raw_supervision_reason_detail = (
        str(run_result.supervision_reason_detail or "").strip() or None
        if run_result is not None
        else None
    )
    raw_supervision_retryable = (
        bool(run_result.supervision_retryable)
        if run_result is not None
        else False
    )
    recovery_status = str(
        (fresh_session_recovery_metadata or {}).get("fresh_session_recovery_status") or ""
    ).strip()
    prior_session_reason_code = str(
        (fresh_session_recovery_metadata or {}).get("prior_session_reason_code") or ""
    ).strip()
    unresolved_row_count = int(
        ((row_resolution_metadata or {}).get("unresolved_row_count") or 0)
    )
    unresolved_atomic_indices = [
        int(value)
        for value in ((row_resolution_metadata or {}).get("unresolved_atomic_indices") or [])
        if str(value).strip()
    ]
    unresolved_suffix = ""
    if unresolved_atomic_indices:
        unresolved_suffix = " Unresolved atomic indices: " + ", ".join(
            str(value) for value in unresolved_atomic_indices
        ) + "."

    if proposal_status == "validated":
        if str(repair_status).strip() == "repaired":
            detail = "line-role shard validated after a repair attempt corrected the final shard ledger."
            if raw_supervision_reason_code:
                detail += f" Original workspace reason: {raw_supervision_reason_code}."
            return _with_fresh_session_recovery({
                "state": "completed",
                "reason_code": "repair_recovered",
                "reason_detail": detail,
                "retryable": False,
                "finalization_path": "repair_recovered",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            })
        if str(watchdog_retry_status).strip() == "recovered":
            detail = (
                "line-role shard validated after a watchdog retry recovered a missing shard ledger."
            )
            if raw_supervision_reason_code:
                detail += f" Original workspace reason: {raw_supervision_reason_code}."
            return _with_fresh_session_recovery({
                "state": "completed",
                "reason_code": "watchdog_retry_recovered",
                "reason_detail": detail,
                "retryable": False,
                "finalization_path": "watchdog_retry_recovered",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            })
        if recovery_status == "recovered":
            detail = (
                "line-role shard validated after one fresh-session recovery resumed the preserved workspace."
            )
            if prior_session_reason_code:
                detail += f" Prior workspace reason: {prior_session_reason_code}."
            return _with_fresh_session_recovery({
                "state": "completed",
                "reason_code": "fresh_session_recovery_recovered",
                "reason_detail": detail,
                "retryable": False,
                "finalization_path": "fresh_session_recovery_recovered",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            })
        if run_result is None:
            reason_code, reason_detail = _line_role_resume_reason_fields(
                resumed_from_existing_outputs=resumed_from_existing_outputs
            )
            return _with_fresh_session_recovery({
                "state": "completed",
                "reason_code": reason_code,
                "reason_detail": reason_detail,
                "retryable": False,
                "finalization_path": reason_code,
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            })
        if str(raw_supervision_state or "").lower() == "watchdog_killed":
            detail = (
                "line-role shard validated using a durable shard ledger even though the main "
                "taskfile worker was killed before it terminated cleanly."
            )
            if raw_supervision_reason_code:
                detail += f" Original workspace reason: {raw_supervision_reason_code}."
            return _with_fresh_session_recovery({
                "state": "completed",
                "reason_code": "validated_after_watchdog_kill",
                "reason_detail": detail,
                "retryable": False,
                "finalization_path": "validated_after_watchdog_kill",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            })
        return _with_fresh_session_recovery({
            "state": str(raw_supervision_state or "completed"),
            "reason_code": raw_supervision_reason_code,
            "reason_detail": raw_supervision_reason_detail,
            "retryable": False,
            "finalization_path": "session_completed",
            "raw_supervision_state": raw_supervision_state,
            "raw_supervision_reason_code": raw_supervision_reason_code,
            "raw_supervision_reason_detail": raw_supervision_reason_detail,
            "raw_supervision_retryable": raw_supervision_retryable,
        })

    if run_result is None:
        if unresolved_row_count > 0:
            return _with_fresh_session_recovery({
                "state": "repair_failed" if str(repair_status).strip() == "failed" else "invalid_output",
                "reason_code": (
                    "same_session_repair_failed"
                    if str(repair_status).strip() == "failed"
                    else "line_role_install_required"
                ),
                "reason_detail": (
                    "line-role shard stopped without a clean installed ledger."
                    " The active worker repair loop must install a fully valid `out/<shard_id>.json` ledger"
                    " before the shard can succeed."
                    f"{unresolved_suffix}"
                ),
                "retryable": False,
                "finalization_path": "fail_closed_missing_install",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            })
        reason_code, reason_detail = _line_role_resume_reason_fields(
            resumed_from_existing_outputs=resumed_from_existing_outputs
        )
        return _with_fresh_session_recovery({
            "state": "completed",
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "retryable": False,
            "finalization_path": reason_code,
            "raw_supervision_state": raw_supervision_state,
            "raw_supervision_reason_code": raw_supervision_reason_code,
            "raw_supervision_reason_detail": raw_supervision_reason_detail,
            "raw_supervision_retryable": raw_supervision_retryable,
        })

    if unresolved_row_count > 0:
        detail = (
            "line-role shard stopped without a clean installed ledger."
            " The active worker repair loop must install a fully valid `out/<shard_id>.json` ledger"
            " before the shard can succeed."
            f"{unresolved_suffix}"
        )
        if raw_supervision_reason_detail:
            detail += f" Workspace detail: {raw_supervision_reason_detail}"
        return _with_fresh_session_recovery({
            "state": (
                "repair_failed"
                if str(repair_status).strip() == "failed"
                else (
                    str(raw_supervision_state)
                    if str(raw_supervision_state or "").strip()
                    and str(raw_supervision_state or "").strip() != "completed"
                    else "invalid_output"
                )
            ),
            "reason_code": (
                "same_session_repair_failed"
                if str(repair_status).strip() == "failed"
                else str(raw_supervision_reason_code or "line_role_install_required")
            ),
            "reason_detail": detail,
            "retryable": raw_supervision_retryable,
            "finalization_path": "fail_closed_missing_install",
            "raw_supervision_state": raw_supervision_state,
            "raw_supervision_reason_code": raw_supervision_reason_code,
            "raw_supervision_reason_detail": raw_supervision_reason_detail,
            "raw_supervision_retryable": raw_supervision_retryable,
        })

    return _with_fresh_session_recovery({
        "state": str(raw_supervision_state or "completed"),
        "reason_code": raw_supervision_reason_code,
        "reason_detail": raw_supervision_reason_detail,
        "retryable": raw_supervision_retryable,
        "finalization_path": "session_result",
        "raw_supervision_state": raw_supervision_state,
        "raw_supervision_reason_code": raw_supervision_reason_code,
        "raw_supervision_reason_detail": raw_supervision_reason_detail,
        "raw_supervision_retryable": raw_supervision_retryable,
    })


def _annotate_line_role_final_outcome_row(
    row: dict[str, Any],
    *,
    normalized_outcome: Mapping[str, Any],
    repair_attempted: bool | None = None,
    repair_status: str | None = None,
) -> None:
    row["final_supervision_state"] = normalized_outcome.get("state")
    row["final_supervision_reason_code"] = normalized_outcome.get("reason_code")
    row["final_supervision_reason_detail"] = normalized_outcome.get("reason_detail")
    row["final_supervision_retryable"] = normalized_outcome.get("retryable")
    row["finalization_path"] = normalized_outcome.get("finalization_path")
    row["raw_supervision_state"] = normalized_outcome.get("raw_supervision_state")
    row["raw_supervision_reason_code"] = normalized_outcome.get(
        "raw_supervision_reason_code"
    )
    row["raw_supervision_reason_detail"] = normalized_outcome.get(
        "raw_supervision_reason_detail"
    )
    row["raw_supervision_retryable"] = normalized_outcome.get(
        "raw_supervision_retryable"
    )
    for key in (
        "fresh_session_recovery_attempted",
        "fresh_session_recovery_status",
        "fresh_session_recovery_count",
        "fresh_session_recovery_skipped_reason",
        "shared_retry_budget_spent",
        "prior_session_reason_code",
        "diagnosis_code",
        "recommended_command",
        "resume_summary",
        "assessment_path",
    ):
        if key in normalized_outcome:
            row[key] = normalized_outcome.get(key)
    if repair_attempted is not None:
        row["repair_attempted"] = bool(repair_attempted)
    if repair_status is not None:
        row["repair_status"] = str(repair_status or "not_attempted")


def _annotate_line_role_final_proposal_status(
    row: dict[str, Any],
    *,
    final_proposal_status: str,
) -> None:
    raw_proposal_status = str(row.get("proposal_status") or "").strip()
    row["raw_proposal_status"] = raw_proposal_status or None
    row["final_proposal_status"] = str(final_proposal_status or "").strip() or None


def _apply_line_role_final_outcome_to_runner_payload(
    payload: dict[str, Any],
    *,
    shard_id: str,
    normalized_outcome: Mapping[str, Any],
    repair_attempted: bool | None = None,
    repair_status: str | None = None,
) -> None:
    telemetry = payload.get("telemetry")
    row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
    changed = False
    if isinstance(row_payloads, list):
        for row_payload in row_payloads:
            if not isinstance(row_payload, dict):
                continue
            if str(row_payload.get("task_id") or "").strip() != str(shard_id).strip():
                continue
            if str(row_payload.get("prompt_input_mode") or "").strip() != "taskfile":
                continue
            _annotate_line_role_final_outcome_row(
                row_payload,
                normalized_outcome=normalized_outcome,
                repair_attempted=repair_attempted,
                repair_status=repair_status,
            )
            changed = True
        if changed:
            telemetry["summary"] = _summarize_direct_rows(row_payloads)


def _safe_int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sum_runtime_usage(rows: Sequence[dict[str, Any]]) -> dict[str, int | None]:
    totals: dict[str, int | None] = {
        "tokens_input": None,
        "tokens_cached_input": None,
        "tokens_output": None,
        "tokens_reasoning": None,
        "tokens_total": None,
        "visible_input_tokens": None,
        "visible_output_tokens": None,
        "wrapper_overhead_tokens": None,
        "request_input_file_bytes_total": None,
    }
    for row in rows:
        tokens_input = _safe_int_value(row.get("tokens_input"))
        tokens_cached_input = _safe_int_value(row.get("tokens_cached_input"))
        tokens_output = _safe_int_value(row.get("tokens_output"))
        tokens_reasoning = _safe_int_value(row.get("tokens_reasoning"))
        values = {
            "tokens_input": tokens_input,
            "tokens_cached_input": tokens_cached_input,
            "tokens_output": tokens_output,
            "tokens_reasoning": tokens_reasoning,
            "tokens_total": _safe_int_value(row.get("tokens_total"))
            or (
                tokens_input + tokens_cached_input + tokens_output + tokens_reasoning
                if all(
                    value is not None
                    for value in (
                        tokens_input,
                        tokens_cached_input,
                        tokens_output,
                        tokens_reasoning,
                    )
                )
                else None
            ),
            "visible_input_tokens": _safe_int_value(row.get("visible_input_tokens")),
            "visible_output_tokens": _safe_int_value(row.get("visible_output_tokens")),
            "wrapper_overhead_tokens": _safe_int_value(row.get("wrapper_overhead_tokens")),
            "request_input_file_bytes_total": _safe_int_value(
                row.get("request_input_file_bytes")
            ),
        }
        for key, value in values.items():
            if value is None:
                continue
            current = totals.get(key)
            totals[key] = value if current is None else current + value
    return totals


def _line_role_usage_present(payload: Mapping[str, Any] | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    return any(
        _safe_int_value(payload.get(key)) is not None
        for key in (
            "tokens_input",
            "tokens_cached_input",
            "tokens_output",
            "tokens_reasoning",
            "tokens_total",
        )
    )

def _parse_codex_line_role_response(
    raw_response: str,
    *,
    requested: Sequence[AtomicLineCandidate],
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        return [], f"invalid_json:{exc.msg}"
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            payload = rows
    if not isinstance(payload, list):
        return [], "payload_not_list"

    requested_indices = [int(candidate.atomic_index) for candidate in requested]
    requested_by_index = {
        int(candidate.atomic_index): candidate for candidate in requested
    }
    seen: set[int] = set()
    parsed: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            return [], "row_not_object"
        raw_index = row.get("atomic_index")
        try:
            atomic_index = int(raw_index)
        except (TypeError, ValueError):
            return [], "missing_or_invalid_atomic_index"
        if atomic_index in seen:
            return [], "duplicate_atomic_index"
        if atomic_index not in requested_indices:
            return [], "unexpected_atomic_index"
        normalized_label = normalize_freeform_label(str(row.get("label") or ""))
        if normalized_label not in CANONICAL_LINE_ROLE_ALLOWED_LABELS:
            return [], f"unknown_label:{normalized_label}"
        seen.add(atomic_index)
        parsed.append(
            {
                "atomic_index": atomic_index,
                "label": normalized_label,
            }
        )

    if seen != set(requested_indices):
        return [], "missing_atomic_index_rows"
    ordered_parsed = sorted(parsed, key=lambda row: requested_indices.index(row["atomic_index"]))
    return ordered_parsed, None
