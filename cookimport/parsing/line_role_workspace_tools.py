from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

LINE_ROLE_ALLOWED_LABELS: tuple[str, ...] = (
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "HOWTO_SECTION",
    "YIELD_LINE",
    "TIME_LINE",
    "RECIPE_NOTES",
    "RECIPE_VARIANT",
    "NONRECIPE_CANDIDATE",
    "NONRECIPE_EXCLUDE",
)

_VALID_EXCLUSION_REASONS = {
}


def _coerce_metadata(shard_row: Mapping[str, Any]) -> dict[str, Any]:
    metadata = shard_row.get("metadata")
    if isinstance(metadata, Mapping):
        return dict(metadata)
    return {}


def _load_shard_input_payload(
    shard_row: Mapping[str, Any],
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    input_payload = shard_row.get("input_payload")
    if isinstance(input_payload, Mapping):
        return dict(input_payload)
    if workspace_root is None:
        return {}
    input_path = str(_coerce_metadata(shard_row).get("input_path") or "").strip()
    if not input_path:
        return {}
    try:
        payload = json.loads((workspace_root / input_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _coerce_input_rows(
    shard_row: Mapping[str, Any],
    *,
    workspace_root: Path | None = None,
) -> list[list[Any]]:
    rows = _load_shard_input_payload(shard_row, workspace_root=workspace_root).get("rows")
    if not isinstance(rows, list):
        return []
    normalized: list[list[Any]] = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            normalized.append(list(row))
    return normalized


def build_line_role_workspace_shard_metadata(
    *,
    shard_id: str,
    input_payload: Mapping[str, Any] | None,
    input_path: str,
    hint_path: str,
    result_path: str,
    work_path: str | None = None,
    repair_path: str | None = None,
) -> dict[str, Any]:
    rows = list(input_payload.get("rows") or []) if isinstance(input_payload, Mapping) else []
    owned_atomic_indices: list[int] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or not row:
            continue
        try:
            owned_atomic_indices.append(int(row[0]))
        except (TypeError, ValueError):
            continue
    payload = {
        "phase_key": "label_rows",
        "shard_id": str(shard_id),
        "input_path": str(input_path),
        "hint_path": str(hint_path),
        "result_path": str(result_path),
        "owned_row_count": len(owned_atomic_indices),
        "atomic_index_start": owned_atomic_indices[0] if owned_atomic_indices else None,
        "atomic_index_end": owned_atomic_indices[-1] if owned_atomic_indices else None,
    }
    if work_path:
        payload["work_path"] = str(work_path)
    if repair_path:
        payload["repair_path"] = str(repair_path)
    return payload


def build_line_role_workspace_scaffold(shard_row: Mapping[str, Any]) -> dict[str, Any]:
    rows_payload: list[dict[str, Any]] = []
    for row in _coerce_input_rows(shard_row):
        try:
            atomic_index = int(row[0])
        except (TypeError, ValueError) as exc:
            raise ValueError("input row is missing a valid atomic_index") from exc
        rows_payload.append({"atomic_index": atomic_index})
    return {"rows": rows_payload}


def build_line_role_workspace_scaffold_for_workspace(
    workspace_root: Path,
    shard_row: Mapping[str, Any],
) -> dict[str, Any]:
    rows_payload: list[dict[str, Any]] = []
    for row in _coerce_input_rows(shard_row, workspace_root=workspace_root):
        try:
            atomic_index = int(row[0])
        except (TypeError, ValueError) as exc:
            raise ValueError("input row is missing a valid atomic_index") from exc
        rows_payload.append({"atomic_index": atomic_index})
    return {"rows": rows_payload}


def _normalize_frozen_rows_by_atomic_index(
    frozen_rows: Mapping[int, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None,
) -> dict[int, dict[str, Any]]:
    normalized: dict[int, dict[str, Any]] = {}
    if isinstance(frozen_rows, Mapping):
        values = frozen_rows.values()
    elif isinstance(frozen_rows, Sequence):
        values = frozen_rows
    else:
        values = ()
    for row in values:
        if not isinstance(row, Mapping):
            continue
        try:
            atomic_index = int(row.get("atomic_index"))
        except (TypeError, ValueError):
            continue
        normalized_row = {
            "atomic_index": atomic_index,
            "label": str(row.get("label") or "").strip().upper(),
        }
        normalized[atomic_index] = normalized_row
    return normalized


def validate_line_role_output_payload(
    shard_row: Mapping[str, Any],
    payload: Any,
    *,
    frozen_rows_by_atomic_index: Mapping[int, Mapping[str, Any]]
    | Sequence[Mapping[str, Any]]
    | None = None,
) -> tuple[tuple[str, ...], dict[str, Any]]:
    errors: list[str] = []
    metadata: dict[str, Any] = {}
    expected_rows = _coerce_input_rows(shard_row)
    expected_atomic_indices: list[int] = []
    for row in expected_rows:
        try:
            expected_atomic_indices.append(int(row[0]))
        except (TypeError, ValueError):
            errors.append("invalid_input_atomic_index")
            return tuple(sorted(set(errors))), metadata
    metadata["owned_row_count"] = len(expected_atomic_indices)
    if not isinstance(payload, Mapping):
        return ("payload_not_object",), metadata
    payload_dict = dict(payload)
    rows_payload = payload_dict.get("rows")
    labels_payload = payload_dict.get("labels")
    if not isinstance(rows_payload, list) and isinstance(labels_payload, list):
        translated_rows: list[dict[str, Any]] = []
        for index, label_value in enumerate(labels_payload):
            row_payload: dict[str, Any] = {"label": label_value}
            if index < len(expected_atomic_indices):
                row_payload["atomic_index"] = expected_atomic_indices[index]
            translated_rows.append(row_payload)
        payload_dict = {"rows": translated_rows}
        rows_payload = translated_rows
        metadata["ordered_label_vector"] = {
            "applied": True,
            "returned_label_count": len(labels_payload),
            "expected_row_count": len(expected_atomic_indices),
        }
    extra_top_level_keys = sorted(key for key in payload_dict.keys() if str(key) != "rows")
    if extra_top_level_keys:
        errors.append("extra_top_level_keys")
        metadata["extra_top_level_keys"] = extra_top_level_keys
    if not isinstance(rows_payload, list):
        errors.append("rows_not_list")
        return tuple(sorted(set(errors))), metadata
    if len(rows_payload) == len(expected_atomic_indices) + 1:
        obvious_trailing_spill = True
        for position, expected_atomic_index in enumerate(expected_atomic_indices):
            row_payload = rows_payload[position]
            if not isinstance(row_payload, Mapping):
                obvious_trailing_spill = False
                break
            try:
                actual_atomic_index = int(row_payload.get("atomic_index"))
            except (TypeError, ValueError):
                obvious_trailing_spill = False
                break
            if actual_atomic_index != expected_atomic_index:
                obvious_trailing_spill = False
                break
        if obvious_trailing_spill:
            metadata["trimmed_trailing_row_spill"] = {
                "applied": True,
                "trimmed_row_count": 1,
                "returned_row_count_before_trim": len(rows_payload),
                "expected_row_count": len(expected_atomic_indices),
            }
            rows_payload = rows_payload[: len(expected_atomic_indices)]
    metadata["returned_row_count"] = len(rows_payload)
    if len(rows_payload) != len(expected_atomic_indices):
        errors.append("wrong_row_count")
    returned_atomic_indices: list[int] = []
    invalid_row_atomic_indices: list[int] = []
    unresolved_atomic_indices: set[int] = set()
    row_error_map: dict[int, list[str]] = {}
    parsed_rows: list[dict[str, Any] | None] = []
    seen_atomic_indices: set[int] = set()
    duplicate_atomic_indices: set[int] = set()
    frozen_by_atomic_index = _normalize_frozen_rows_by_atomic_index(
        frozen_rows_by_atomic_index
    )
    for row_payload in rows_payload:
        if not isinstance(row_payload, Mapping):
            errors.append("row_not_object")
            parsed_rows.append(None)
            continue
        row_errors: list[str] = []
        extra_row_keys = sorted(
            key
            for key in row_payload.keys()
            if str(key) not in {"atomic_index", "label"}
        )
        if extra_row_keys:
            row_errors.append("extra_row_keys")
        try:
            atomic_index = int(row_payload.get("atomic_index"))
            returned_atomic_indices.append(atomic_index)
        except (TypeError, ValueError):
            errors.append("invalid_atomic_index")
            parsed_rows.append(None)
            continue
        label = str(row_payload.get("label") or "").strip().upper()
        if label not in LINE_ROLE_ALLOWED_LABELS:
            row_errors.append("invalid_label")
        if atomic_index not in expected_atomic_indices:
            row_errors.append("unowned_atomic_index")
        if atomic_index in seen_atomic_indices:
            duplicate_atomic_indices.add(atomic_index)
            row_errors.append("duplicate_atomic_index")
        seen_atomic_indices.add(atomic_index)
        if row_errors:
            invalid_row_atomic_indices.append(atomic_index)
            unresolved_atomic_indices.add(atomic_index)
            row_error_map.setdefault(atomic_index, []).extend(row_errors)
        normalized_row = {
            "atomic_index": atomic_index,
            "label": label,
        }
        parsed_rows.append(normalized_row)
    if returned_atomic_indices != expected_atomic_indices:
        if len(returned_atomic_indices) == len(expected_atomic_indices):
            errors.append("row_order_mismatch")
        else:
            errors.append("atomic_index_mismatch")
    accepted_rows: list[dict[str, Any]] = []
    accepted_atomic_indices: list[int] = []
    for position, expected_atomic_index in enumerate(expected_atomic_indices):
        parsed_row = parsed_rows[position] if position < len(parsed_rows) else None
        if parsed_row is None:
            unresolved_atomic_indices.add(expected_atomic_index)
            continue
        actual_atomic_index = int(parsed_row.get("atomic_index"))
        if actual_atomic_index != expected_atomic_index:
            unresolved_atomic_indices.add(expected_atomic_index)
            continue
        if actual_atomic_index in duplicate_atomic_indices:
            unresolved_atomic_indices.add(expected_atomic_index)
            continue
        if actual_atomic_index in row_error_map:
            unresolved_atomic_indices.add(expected_atomic_index)
            continue
        frozen_row = frozen_by_atomic_index.get(expected_atomic_index)
        if frozen_row is not None and dict(parsed_row) != frozen_row:
            errors.append(f"frozen_row_modified:{expected_atomic_index}")
            invalid_row_atomic_indices.append(expected_atomic_index)
            row_error_map.setdefault(expected_atomic_index, []).append(
                "frozen_row_modified"
            )
            unresolved_atomic_indices.add(expected_atomic_index)
            continue
        accepted_atomic_indices.append(expected_atomic_index)
        accepted_rows.append(dict(parsed_row))
    missing_atomic_indices = [
        atomic_index
        for atomic_index in expected_atomic_indices
        if atomic_index not in set(returned_atomic_indices)
    ]
    for atomic_index in missing_atomic_indices:
        unresolved_atomic_indices.add(atomic_index)
    metadata["expected_atomic_indices"] = expected_atomic_indices
    metadata["returned_atomic_indices"] = returned_atomic_indices
    metadata["invalid_row_atomic_indices"] = sorted(set(invalid_row_atomic_indices))
    metadata["accepted_atomic_indices"] = accepted_atomic_indices
    metadata["accepted_rows"] = accepted_rows
    metadata["unresolved_atomic_indices"] = [
        atomic_index
        for atomic_index in expected_atomic_indices
        if atomic_index in unresolved_atomic_indices
    ]
    metadata["row_errors_by_atomic_index"] = {
        str(atomic_index): sorted(set(row_errors))
        for atomic_index, row_errors in sorted(row_error_map.items())
    }
    metadata["frozen_atomic_indices"] = sorted(frozen_by_atomic_index)
    return tuple(sorted(set(errors))), metadata


__all__ = (
    "LINE_ROLE_ALLOWED_LABELS",
    "build_line_role_workspace_scaffold",
    "build_line_role_workspace_scaffold_for_workspace",
    "build_line_role_workspace_shard_metadata",
    "validate_line_role_output_payload",
)
