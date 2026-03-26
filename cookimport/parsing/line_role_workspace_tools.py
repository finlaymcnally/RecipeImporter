from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.llm.canonical_line_role_prompt import build_line_role_label_code_by_label


_LABEL_CODE_BY_LABEL = build_line_role_label_code_by_label()
LINE_ROLE_LABEL_BY_CODE: dict[str, str] = {
    str(code): str(label)
    for label, code in _LABEL_CODE_BY_LABEL.items()
}
LINE_ROLE_ALLOWED_LABELS: tuple[str, ...] = tuple(
    label
    for label, _ in sorted(_LABEL_CODE_BY_LABEL.items(), key=lambda item: item[1])
)
LINE_ROLE_WORKER_TOOL_FILENAME = "line_role_worker.py"
LINE_ROLE_VALID_OUTPUT_EXAMPLE_FILENAME = "valid_line_role_output.json"
LINE_ROLE_VALID_OUTPUT_EXAMPLE_PAYLOAD = {
    "rows": [
        {"atomic_index": 123, "label": "INGREDIENT_LINE"},
        {
            "atomic_index": 124,
            "label": "OTHER",
            "review_exclusion_reason": "navigation",
        },
    ]
}
LINE_ROLE_OUTPUT_CONTRACT_MARKDOWN = """# Line-Role Ledger Contract

Use this contract for every `work/<shard_id>.json` ledger and every installed `out/<shard_id>.json`.

Required shape:

    {"rows":[{"atomic_index":123,"label":"INGREDIENT_LINE"}]}

Rules:

- The file must be one JSON object with exactly one top-level key: `rows`.
- `rows` must be a JSON array.
- Return exactly one row for every owned input row from `in/<shard_id>.json`.
- Keep output order identical to the input `rows` order.
- Each row object must use `atomic_index` and `label`, plus optional `review_exclusion_reason`.
- `atomic_index` must match the owned input row at the same position.
- `label` must be one of:
  `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`, `YIELD_LINE`, `TIME_LINE`, `RECIPE_NOTES`, `RECIPE_VARIANT`, `KNOWLEDGE`, `OTHER`
- `review_exclusion_reason`, when present, must be one of:
  `navigation`, `front_matter`, `publishing_metadata`, `copyright_legal`, `endorsement`, `page_furniture`
- Only use `review_exclusion_reason` on rows labeled `OTHER`, and only for overwhelmingly obvious non-recipe junk that should skip knowledge review.
- Do not add commentary, markdown, or extra JSON keys.
- There is no separate repo-owned repair model pass for line-role; the work ledger plus `check-phase` is the real repair loop.

Preferred loop:

    open CURRENT_PHASE.md
    open work/<shard_id>.json
    read hints/<shard_id>.md if helpful
    python3 tools/line_role_worker.py check-phase
    if CURRENT_PHASE_FEEDBACK.md names repair/<shard_id>.json, fix only the unresolved rows
    python3 tools/line_role_worker.py install-phase
"""

_VALID_REVIEW_EXCLUSION_REASONS = {
    "navigation",
    "front_matter",
    "publishing_metadata",
    "copyright_legal",
    "endorsement",
    "page_furniture",
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
    metadata = _coerce_metadata(shard_row)
    input_path = str(metadata.get("input_path") or "").strip()
    if not input_path:
        return {}
    try:
        payload = json.loads((workspace_root / input_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(payload, Mapping):
        return dict(payload)
    return {}


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
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        normalized.append([row[0], row[1], row[2]])
    return normalized


def build_line_role_workspace_shard_metadata(
    *,
    shard_id: str,
    input_payload: Mapping[str, Any] | None,
    input_path: str,
    hint_path: str,
    work_path: str,
    result_path: str,
    repair_path: str,
) -> dict[str, Any]:
    rows = []
    if isinstance(input_payload, Mapping):
        candidate_rows = input_payload.get("rows")
        if isinstance(candidate_rows, list):
            rows = candidate_rows
    owned_atomic_indices: list[int] = []
    deterministic_label_counts: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        try:
            atomic_index = int(row[0])
        except (TypeError, ValueError):
            continue
        owned_atomic_indices.append(atomic_index)
        deterministic_label = LINE_ROLE_LABEL_BY_CODE.get(str(row[1]).strip(), "OTHER")
        deterministic_label_counts[deterministic_label] += 1
    return {
        "phase_key": "label_rows",
        "shard_id": str(shard_id),
        "input_path": str(input_path),
        "hint_path": str(hint_path),
        "work_path": str(work_path),
        "result_path": str(result_path),
        "repair_path": str(repair_path),
        "owned_row_count": len(owned_atomic_indices),
        "atomic_index_start": owned_atomic_indices[0] if owned_atomic_indices else None,
        "atomic_index_end": owned_atomic_indices[-1] if owned_atomic_indices else None,
        "deterministic_label_counts": dict(sorted(deterministic_label_counts.items())),
    }


def build_line_role_seed_output(shard_row: Mapping[str, Any]) -> dict[str, Any]:
    rows_payload: list[dict[str, Any]] = []
    unknown_codes: list[str] = []
    for row in _coerce_input_rows(shard_row):
        try:
            atomic_index = int(row[0])
        except (TypeError, ValueError) as exc:
            raise ValueError("input row is missing a valid atomic_index") from exc
        label_code = str(row[1]).strip()
        label = LINE_ROLE_LABEL_BY_CODE.get(label_code)
        if label is None:
            unknown_codes.append(label_code or "<blank>")
            label = "OTHER"
        rows_payload.append({"atomic_index": atomic_index, "label": label})
    if unknown_codes:
        rendered = ", ".join(sorted(set(unknown_codes)))
        raise ValueError(f"unknown line-role label code(s): {rendered}")
    return {"rows": rows_payload}


def build_line_role_seed_output_for_workspace(
    workspace_root: Path,
    shard_row: Mapping[str, Any],
) -> dict[str, Any]:
    rows_payload: list[dict[str, Any]] = []
    unknown_codes: list[str] = []
    for row in _coerce_input_rows(shard_row, workspace_root=workspace_root):
        try:
            atomic_index = int(row[0])
        except (TypeError, ValueError) as exc:
            raise ValueError("input row is missing a valid atomic_index") from exc
        label_code = str(row[1]).strip()
        label = LINE_ROLE_LABEL_BY_CODE.get(label_code)
        if label is None:
            unknown_codes.append(label_code or "<blank>")
            label = "OTHER"
        rows_payload.append({"atomic_index": atomic_index, "label": label})
    if unknown_codes:
        rendered = ", ".join(sorted(set(unknown_codes)))
        raise ValueError(f"unknown line-role label code(s): {rendered}")
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
        review_exclusion_reason = str(
            row.get("review_exclusion_reason") or ""
        ).strip()
        if review_exclusion_reason:
            normalized_row["review_exclusion_reason"] = review_exclusion_reason
        normalized[atomic_index] = normalized_row
    return normalized


def _input_rows_by_atomic_index(
    shard_row: Mapping[str, Any],
    *,
    workspace_root: Path | None = None,
) -> dict[int, list[Any]]:
    rows_by_atomic_index: dict[int, list[Any]] = {}
    for row in _coerce_input_rows(shard_row, workspace_root=workspace_root):
        try:
            atomic_index = int(row[0])
        except (TypeError, ValueError):
            continue
        rows_by_atomic_index[atomic_index] = [atomic_index, str(row[1]), str(row[2])]
    return rows_by_atomic_index


def validate_line_role_output_payload(
    shard_row: Mapping[str, Any],
    payload: Any,
    *,
    frozen_rows_by_atomic_index: Mapping[int, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None = None,
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
    extra_top_level_keys = sorted(key for key in payload.keys() if str(key) != "rows")
    if extra_top_level_keys:
        errors.append("extra_top_level_keys")
        metadata["extra_top_level_keys"] = extra_top_level_keys
    rows_payload = payload.get("rows")
    if not isinstance(rows_payload, list):
        errors.append("rows_not_list")
        return tuple(sorted(set(errors))), metadata
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
            if str(key) not in {"atomic_index", "label", "review_exclusion_reason"}
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
        review_exclusion_reason = str(row_payload.get("review_exclusion_reason") or "").strip()
        if review_exclusion_reason:
            if label != "OTHER":
                row_errors.append("review_exclusion_reason_requires_other")
            if review_exclusion_reason not in _VALID_REVIEW_EXCLUSION_REASONS:
                row_errors.append("invalid_review_exclusion_reason")
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
        if review_exclusion_reason:
            normalized_row["review_exclusion_reason"] = review_exclusion_reason
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


def build_line_role_repair_request_payload(
    *,
    shard_row: Mapping[str, Any],
    metadata: Mapping[str, Any],
    validation_errors: Sequence[str],
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    unresolved_atomic_indices = [
        int(value)
        for value in metadata.get("unresolved_atomic_indices", [])
        if str(value).strip()
    ]
    if not unresolved_atomic_indices:
        unresolved_atomic_indices = [
            int(value)
            for value in metadata.get("invalid_row_atomic_indices", [])
            if str(value).strip()
        ]
    input_row_by_atomic_index = _input_rows_by_atomic_index(
        shard_row,
        workspace_root=workspace_root,
    )
    frozen_rows = [
        dict(row)
        for row in metadata.get("accepted_rows", [])
        if isinstance(row, Mapping)
    ]
    return {
        "repair_mode": "line_role",
        "shard_id": str(shard_row.get("shard_id") or ""),
        "accepted_atomic_indices": [
            int(value)
            for value in metadata.get("accepted_atomic_indices", [])
            if str(value).strip()
        ],
        "unresolved_atomic_indices": unresolved_atomic_indices,
        "validation_errors": [str(error) for error in validation_errors if str(error).strip()],
        "frozen_rows": frozen_rows,
        "rows": [
            input_row_by_atomic_index[index]
            for index in unresolved_atomic_indices
            if index in input_row_by_atomic_index
        ],
    }


def render_line_role_shard_overview(
    *,
    shard_rows: Sequence[Mapping[str, Any]],
    current_shard_id: str | None,
) -> str:
    lines = ["Line-role shard queue:"]
    for index, shard_row in enumerate(shard_rows, start=1):
        shard_id = str(shard_row.get("shard_id") or "").strip() or f"shard-{index:03d}"
        metadata = _coerce_metadata(shard_row)
        counts = metadata.get("deterministic_label_counts")
        rendered_counts = (
            ", ".join(f"{label}={count}" for label, count in dict(counts).items())
            if isinstance(counts, Mapping) and counts
            else "unknown"
        )
        current_marker = " current" if shard_id == str(current_shard_id or "").strip() else ""
        lines.append(
            f"- {shard_id}{current_marker}: rows={metadata.get('owned_row_count')}, "
            f"atomic={metadata.get('atomic_index_start')}..{metadata.get('atomic_index_end')}, "
            f"labels={rendered_counts}, work={metadata.get('work_path') or 'unknown'}"
        )
    return "\n".join(lines) + "\n"


def render_line_role_shard_show(shard_row: Mapping[str, Any]) -> str:
    shard_id = str(shard_row.get("shard_id") or "").strip() or "<unknown>"
    metadata = _coerce_metadata(shard_row)
    lines = [
        f"shard_id: {shard_id}",
        f"input_path: {metadata.get('input_path') or '<missing>'}",
        f"hint_path: {metadata.get('hint_path') or '<missing>'}",
        f"work_path: {metadata.get('work_path') or '<missing>'}",
        f"result_path: {metadata.get('result_path') or '<missing>'}",
        f"repair_path: {metadata.get('repair_path') or '<missing>'}",
        f"owned_row_count: {metadata.get('owned_row_count')}",
        f"atomic_index_start: {metadata.get('atomic_index_start')}",
        f"atomic_index_end: {metadata.get('atomic_index_end')}",
    ]
    counts = metadata.get("deterministic_label_counts")
    if isinstance(counts, Mapping) and counts:
        lines.append(
            "deterministic_label_counts: "
            + ", ".join(f"{label}={count}" for label, count in dict(counts).items())
        )
    else:
        lines.append("deterministic_label_counts: none")
    return "\n".join(lines) + "\n"


def render_line_role_current_phase_brief(phase_row: Mapping[str, Any]) -> str:
    shard_id = str(phase_row.get("shard_id") or "").strip() or "<unknown>"
    metadata = _coerce_metadata(phase_row)
    counts = metadata.get("deterministic_label_counts")
    rendered_counts = (
        ", ".join(f"{label}={count}" for label, count in dict(counts).items())
        if isinstance(counts, Mapping) and counts
        else "unknown"
    )
    return "\n".join(
        [
            "# Current Line-Role Phase",
            "",
            "Phase: `label_rows`",
            f"Shard id: `{shard_id}`",
            f"Owned rows: `{metadata.get('owned_row_count')}`",
            f"Atomic span: `{metadata.get('atomic_index_start')}..{metadata.get('atomic_index_end')}`",
            f"Deterministic labels: {rendered_counts}",
            "",
            "Read order:",
            f"1. Work ledger: `{metadata.get('work_path') or '<missing>'}`",
            f"2. Hint: `{metadata.get('hint_path') or '<missing>'}`",
            f"3. Input ledger: `{metadata.get('input_path') or '<missing>'}`",
            "4. Run `python3 tools/line_role_worker.py check-phase`.",
            "5. If feedback names a repair file, fix only the unresolved rows.",
            f"6. Install to: `{metadata.get('result_path') or '<missing>'}`",
            "",
            "`assigned_shards.json` is queue/ownership context only.",
        ]
    ) + "\n"


def render_line_role_current_phase_feedback(
    *,
    phase_row: Mapping[str, Any] | None,
    validation_errors: Sequence[str] = (),
    validation_metadata: Mapping[str, Any] | None = None,
    repair_written: bool = False,
    completed: bool = False,
) -> str:
    if completed:
        return "# Current Phase Feedback\n\nAll assigned line-role shards are installed.\n"
    if phase_row is None:
        return "# Current Phase Feedback\n\nNo active line-role shard.\n"
    metadata = _coerce_metadata(phase_row)
    if not validation_errors:
        return "\n".join(
            [
                "# Current Phase Feedback",
                "",
                "Current work ledger validates cleanly.",
                f"Install target: `{metadata.get('result_path') or '<missing>'}`",
            ]
        ) + "\n"
    lines = [
        "# Current Phase Feedback",
        "",
        "Current work ledger is still unresolved.",
        "Validation errors:",
    ]
    lines.extend(f"- `{error}`" for error in validation_errors if str(error).strip())
    if repair_written:
        lines.append(f"Repair request: `{metadata.get('repair_path') or '<missing>'}`")
    invalid_rows = []
    accepted_rows = []
    if isinstance(validation_metadata, Mapping):
        invalid_rows = [
            int(value)
            for value in validation_metadata.get("unresolved_atomic_indices", [])
            if str(value).strip()
        ]
        accepted_rows = [
            int(value)
            for value in validation_metadata.get("accepted_atomic_indices", [])
            if str(value).strip()
        ]
    if accepted_rows:
        rendered = ", ".join(str(value) for value in accepted_rows)
        lines.append(f"Frozen accepted atomic indices: `{rendered}`")
    if invalid_rows:
        rendered = ", ".join(str(value) for value in invalid_rows)
        lines.append(f"Unresolved atomic indices: `{rendered}`")
    return "\n".join(lines) + "\n"


def render_line_role_worker_script() -> str:
    allowed_labels_json = json.dumps(list(LINE_ROLE_ALLOWED_LABELS), sort_keys=True)
    label_by_code_json = json.dumps(LINE_ROLE_LABEL_BY_CODE, sort_keys=True)
    valid_reasons_json = json.dumps(sorted(_VALID_REVIEW_EXCLUSION_REASONS))
    script = """#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ALLOWED_LABELS = __ALLOWED_LABELS_JSON__
LABEL_BY_CODE = __LABEL_BY_CODE_JSON__
VALID_REVIEW_EXCLUSION_REASONS = __VALID_REASONS_JSON__


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")


def save_text(path: Path, text: str):
    path.write_text(text, encoding="utf-8")


def workspace_relative_path(workspace_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(workspace_root))
    except ValueError:
        return str(path)


def coerce_metadata(shard_row):
    metadata = shard_row.get("metadata")
    if isinstance(metadata, dict):
        return dict(metadata)
    return {{}}


def read_assigned_shards(workspace_root: Path):
    path = workspace_root / "assigned_shards.json"
    payload = load_json(path)
    if not isinstance(payload, list):
        raise SystemExit("assigned_shards.json is not a list")
    return [row for row in payload if isinstance(row, dict)]


def read_current_phase(workspace_root: Path):
    path = workspace_root / "current_phase.json"
    if not path.exists():
        return None
    payload = load_json(path)
    if isinstance(payload, dict):
        return payload
    return None


def resolve_shard_row(workspace_root: Path, shard_id: str | None = None):
    assigned_shards = read_assigned_shards(workspace_root)
    wanted = str(shard_id or "").strip()
    if wanted:
        for row in assigned_shards:
            if str(row.get("shard_id") or "").strip() == wanted:
                return row
        raise SystemExit(f"unknown shard_id: {{wanted}}")
    current_phase = read_current_phase(workspace_root)
    if isinstance(current_phase, dict):
        current_shard_id = str(current_phase.get("shard_id") or "").strip()
        if current_shard_id:
            for row in assigned_shards:
                if str(row.get("shard_id") or "").strip() == current_shard_id:
                    return row
    if len(assigned_shards) == 1:
        return assigned_shards[0]
    raise SystemExit("shard_id is required when current_phase.json is absent")


def load_input_payload(workspace_root: Path, shard_row):
    input_payload = shard_row.get("input_payload")
    if isinstance(input_payload, dict):
        return input_payload
    metadata = coerce_metadata(shard_row)
    input_path = str(metadata.get("input_path") or "").strip()
    if not input_path:
        return {{}}
    candidate_path = (workspace_root / input_path).resolve()
    if not candidate_path.exists():
        return {{}}
    payload = load_json(candidate_path)
    return payload if isinstance(payload, dict) else {{}}


def coerce_input_rows(workspace_root: Path, shard_row):
    rows = load_input_payload(workspace_root, shard_row).get("rows")
    if not isinstance(rows, list):
        return []
    normalized = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        normalized.append([row[0], row[1], row[2]])
    return normalized


def build_seed_output(workspace_root: Path, shard_row):
    rows_payload = []
    unknown_codes = []
    for row in coerce_input_rows(workspace_root, shard_row):
        try:
            atomic_index = int(row[0])
        except (TypeError, ValueError):
            raise SystemExit("input row is missing a valid atomic_index")
        code = str(row[1]).strip()
        label = LABEL_BY_CODE.get(code)
        if label is None:
            unknown_codes.append(code or "<blank>")
            label = "OTHER"
        rows_payload.append({{"atomic_index": atomic_index, "label": label}})
    if unknown_codes:
        rendered = ", ".join(sorted(set(unknown_codes)))
        raise SystemExit(f"unknown line-role label code(s): {{rendered}}")
    return {{"rows": rows_payload}}


def normalize_frozen_rows(frozen_rows):
    normalized = {{}}
    if isinstance(frozen_rows, dict):
        values = frozen_rows.values()
    elif isinstance(frozen_rows, list):
        values = frozen_rows
    else:
        values = []
    for row in values:
        if not isinstance(row, dict):
            continue
        try:
            atomic_index = int(row.get("atomic_index"))
        except (TypeError, ValueError):
            continue
        normalized_row = {{
            "atomic_index": atomic_index,
            "label": str(row.get("label") or "").strip().upper(),
        }}
        review_exclusion_reason = str(row.get("review_exclusion_reason") or "").strip()
        if review_exclusion_reason:
            normalized_row["review_exclusion_reason"] = review_exclusion_reason
        normalized[atomic_index] = normalized_row
    return normalized


def load_existing_repair_request(workspace_root: Path, shard_row):
    metadata = coerce_metadata(shard_row)
    repair_path = str(metadata.get("repair_path") or "").strip()
    if not repair_path:
        return None
    candidate = (workspace_root / repair_path).resolve()
    if not candidate.exists():
        return None
    payload = load_json(candidate)
    return payload if isinstance(payload, dict) else None


def validate_payload(workspace_root: Path, shard_row, payload, *, frozen_rows_by_atomic_index=None):
    expected_rows = coerce_input_rows(workspace_root, shard_row)
    expected_atomic_indices = []
    for row in expected_rows:
        try:
            expected_atomic_indices.append(int(row[0]))
        except (TypeError, ValueError):
            return ["invalid_input_atomic_index"], {{}}
    metadata = {{"owned_row_count": len(expected_atomic_indices)}}
    if not isinstance(payload, dict):
        return ["payload_not_object"], metadata
    extra_top_level_keys = sorted(key for key in payload.keys() if str(key) != "rows")
    if extra_top_level_keys:
        metadata["extra_top_level_keys"] = extra_top_level_keys
    rows_payload = payload.get("rows")
    if not isinstance(rows_payload, list):
        return sorted(set(["rows_not_list"] + (["extra_top_level_keys"] if extra_top_level_keys else []))), metadata
    errors = []
    if extra_top_level_keys:
        errors.append("extra_top_level_keys")
    metadata["returned_row_count"] = len(rows_payload)
    if len(rows_payload) != len(expected_atomic_indices):
        errors.append("wrong_row_count")
    returned_atomic_indices = []
    invalid_row_atomic_indices = []
    unresolved_atomic_indices = set()
    row_error_map = {{}}
    parsed_rows = []
    seen_atomic_indices = set()
    duplicate_atomic_indices = set()
    frozen_by_atomic_index = normalize_frozen_rows(frozen_rows_by_atomic_index)
    for row_payload in rows_payload:
        if not isinstance(row_payload, dict):
            errors.append("row_not_object")
            parsed_rows.append(None)
            continue
        row_errors = []
        extra_row_keys = sorted(
            key
            for key in row_payload.keys()
            if str(key) not in {{"atomic_index", "label", "review_exclusion_reason"}}
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
        if label not in ALLOWED_LABELS:
            row_errors.append("invalid_label")
        review_exclusion_reason = str(row_payload.get("review_exclusion_reason") or "").strip()
        if review_exclusion_reason:
            if label != "OTHER":
                row_errors.append("review_exclusion_reason_requires_other")
            if review_exclusion_reason not in VALID_REVIEW_EXCLUSION_REASONS:
                row_errors.append("invalid_review_exclusion_reason")
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
        normalized_row = {{
            "atomic_index": atomic_index,
            "label": label,
        }}
        if review_exclusion_reason:
            normalized_row["review_exclusion_reason"] = review_exclusion_reason
        parsed_rows.append(normalized_row)
    if returned_atomic_indices != expected_atomic_indices:
        if len(returned_atomic_indices) == len(expected_atomic_indices):
            errors.append("row_order_mismatch")
        else:
            errors.append("atomic_index_mismatch")
    accepted_rows = []
    accepted_atomic_indices = []
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
            errors.append(f"frozen_row_modified:{{expected_atomic_index}}")
            invalid_row_atomic_indices.append(expected_atomic_index)
            row_error_map.setdefault(expected_atomic_index, []).append("frozen_row_modified")
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
    metadata["row_errors_by_atomic_index"] = {{
        str(atomic_index): sorted(set(row_errors))
        for atomic_index, row_errors in sorted(row_error_map.items())
    }}
    metadata["frozen_atomic_indices"] = sorted(frozen_by_atomic_index)
    return sorted(set(errors)), metadata


def render_feedback(shard_row, errors, metadata, repair_written=False, completed=False):
    if completed:
        return "# Current Phase Feedback\\n\\nAll assigned line-role shards are installed.\\n"
    if shard_row is None:
        return "# Current Phase Feedback\\n\\nNo active line-role shard.\\n"
    shard_id = str(shard_row.get("shard_id") or "").strip() or "<unknown>"
    row_metadata = coerce_metadata(shard_row)
    if not errors:
        return (
            "# Current Phase Feedback\\n\\n"
            "Current work ledger validates cleanly.\\n"
            f"Shard id: `{{shard_id}}`\\n"
            f"Install target: `{{row_metadata.get('result_path') or '<missing>'}}`\\n"
        )
    lines = [
        "# Current Phase Feedback",
        "",
        f"Shard id: `{{shard_id}}`",
        "Current work ledger is still unresolved.",
        "Validation errors:",
    ]
    lines.extend(f"- `{{error}}`" for error in errors if str(error).strip())
    if repair_written:
        lines.append(f"Repair request: `{{row_metadata.get('repair_path') or '<missing>'}}`")
    invalid_rows = [
        int(value)
        for value in metadata.get("unresolved_atomic_indices", [])
        if str(value).strip()
    ]
    accepted_rows = [
        int(value)
        for value in metadata.get("accepted_atomic_indices", [])
        if str(value).strip()
    ]
    if accepted_rows:
        lines.append(
            "Frozen accepted atomic indices: `"
            + ", ".join(str(value) for value in accepted_rows)
            + "`"
        )
    if invalid_rows:
        lines.append(
            "Unresolved atomic indices: `"
            + ", ".join(str(value) for value in invalid_rows)
            + "`"
        )
    return "\\n".join(lines) + "\\n"


def write_current_phase_files(workspace_root: Path, shard_row, *, completed=False, feedback_text=None):
    current_phase_path = workspace_root / "current_phase.json"
    current_phase_brief_path = workspace_root / "CURRENT_PHASE.md"
    current_phase_feedback_path = workspace_root / "CURRENT_PHASE_FEEDBACK.md"
    if completed:
        save_json(current_phase_path, {{"phase_key": "label_rows", "status": "completed", "shard_id": None}})
        save_text(current_phase_brief_path, "# Current Line-Role Phase\\n\\nAll assigned line-role shards are installed.\\n")
        save_text(
            current_phase_feedback_path,
            feedback_text or "# Current Phase Feedback\\n\\nAll assigned line-role shards are installed.\\n",
        )
        return
    if shard_row is None:
        return
    payload = {{"phase_key": "label_rows", "status": "active", **shard_row}}
    save_json(current_phase_path, payload)
    metadata = coerce_metadata(shard_row)
    counts = metadata.get("deterministic_label_counts")
    rendered_counts = (
        ", ".join(f"{{label}}={{count}}" for label, count in counts.items())
        if isinstance(counts, dict) and counts
        else "unknown"
    )
    save_text(
        current_phase_brief_path,
        "\\n".join(
            [
                "# Current Line-Role Phase",
                "",
                "Phase: `label_rows`",
                f"Shard id: `{{shard_row.get('shard_id') or '<unknown>'}}`",
                f"Owned rows: `{{metadata.get('owned_row_count')}}`",
                f"Atomic span: `{{metadata.get('atomic_index_start')}}..{{metadata.get('atomic_index_end')}}`",
                f"Deterministic labels: {{rendered_counts}}",
                "",
                "Read order:",
                f"1. Work ledger: `{{metadata.get('work_path') or '<missing>'}}`",
                f"2. Hint: `{{metadata.get('hint_path') or '<missing>'}}`",
                f"3. Input ledger: `{{metadata.get('input_path') or '<missing>'}}`",
                "4. Run `python3 tools/line_role_worker.py check-phase`.",
                "5. If feedback names a repair file, fix only the unresolved rows.",
                f"6. Install to: `{{metadata.get('result_path') or '<missing>'}}`",
                "",
                "`assigned_shards.json` is queue/ownership context only.",
                "",
            ]
        ),
    )
    save_text(
        current_phase_feedback_path,
        feedback_text
        or (
            "# Current Phase Feedback\\n\\n"
            "Edit the current work ledger, run `python3 tools/line_role_worker.py check-phase`, then install once clean.\\n"
        ),
    )


def next_pending_shard(workspace_root: Path, current_shard_id: str | None):
    assigned_shards = read_assigned_shards(workspace_root)
    if not assigned_shards:
        return None
    start_index = 0
    current = str(current_shard_id or "").strip()
    if current:
        for index, row in enumerate(assigned_shards):
            if str(row.get("shard_id") or "").strip() == current:
                start_index = index + 1
                break
    ordered = assigned_shards[start_index:] + assigned_shards[:start_index]
    for shard_row in ordered:
        metadata = coerce_metadata(shard_row)
        result_path = str(metadata.get("result_path") or "").strip()
        if not result_path:
            return shard_row
        if not (workspace_root / result_path).exists():
            return shard_row
    return None


def cmd_overview(workspace_root: Path):
    assigned_shards = read_assigned_shards(workspace_root)
    current_phase = read_current_phase(workspace_root)
    current_shard_id = str((current_phase or {{}}).get("shard_id") or "").strip()
    print("Line-role shard queue:")
    for index, shard_row in enumerate(assigned_shards, start=1):
        shard_id = str(shard_row.get("shard_id") or "").strip() or f"shard-{{index:03d}}"
        metadata = coerce_metadata(shard_row)
        counts = metadata.get("deterministic_label_counts")
        rendered_counts = (
            ", ".join(f"{{label}}={{count}}" for label, count in counts.items())
            if isinstance(counts, dict) and counts
            else "unknown"
        )
        current_marker = " current" if shard_id == current_shard_id else ""
        print(
            f"- {{shard_id}}{{current_marker}}: rows={{metadata.get('owned_row_count')}}, "
            f"atomic={{metadata.get('atomic_index_start')}}..{{metadata.get('atomic_index_end')}}, "
            f"labels={{rendered_counts}}, work={{metadata.get('work_path') or 'unknown'}}"
        )


def cmd_show(workspace_root: Path, shard_id: str | None):
    shard_row = resolve_shard_row(workspace_root, shard_id)
    metadata = coerce_metadata(shard_row)
    print(f"shard_id: {{shard_row.get('shard_id')}}")
    print(f"input_path: {{metadata.get('input_path') or '<missing>'}}")
    print(f"hint_path: {{metadata.get('hint_path') or '<missing>'}}")
    print(f"work_path: {{metadata.get('work_path') or '<missing>'}}")
    print(f"result_path: {{metadata.get('result_path') or '<missing>'}}")
    print(f"repair_path: {{metadata.get('repair_path') or '<missing>'}}")
    print(f"owned_row_count: {{metadata.get('owned_row_count')}}")
    print(f"atomic_index_start: {{metadata.get('atomic_index_start')}}")
    print(f"atomic_index_end: {{metadata.get('atomic_index_end')}}")
    counts = metadata.get("deterministic_label_counts")
    if isinstance(counts, dict) and counts:
        rendered_counts = ", ".join(f"{{label}}={{count}}" for label, count in counts.items())
    else:
        rendered_counts = "none"
    print(f"deterministic_label_counts: {{rendered_counts}}")


def cmd_scaffold(workspace_root: Path, shard_id: str | None, dest: str | None):
    shard_row = resolve_shard_row(workspace_root, shard_id)
    payload = build_seed_output(workspace_root, shard_row)
    if dest:
        save_json((workspace_root / dest).resolve(), payload)
        print(dest)
        return
    print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_check_phase(workspace_root: Path, shard_id: str | None):
    shard_row = resolve_shard_row(workspace_root, shard_id)
    metadata = coerce_metadata(shard_row)
    work_path = str(metadata.get("work_path") or "").strip()
    if not work_path:
        raise SystemExit("missing work_path")
    resolved_work_path = (workspace_root / work_path).resolve()
    payload = load_json(resolved_work_path)
    existing_repair_request = load_existing_repair_request(workspace_root, shard_row)
    frozen_rows = (
        existing_repair_request.get("frozen_rows")
        if isinstance(existing_repair_request, dict)
        else None
    )
    errors, validation_metadata = validate_payload(
        workspace_root,
        shard_row,
        payload,
        frozen_rows_by_atomic_index=frozen_rows,
    )
    repair_written = False
    repair_path = str(metadata.get("repair_path") or "").strip()
    if errors and repair_path:
        input_row_by_atomic_index = {{
            int(row[0]): [int(row[0]), str(row[1]), str(row[2])]
            for row in coerce_input_rows(workspace_root, shard_row)
            if len(row) >= 3
        }}
        unresolved_atomic_indices = [
            int(value)
            for value in (
                validation_metadata.get("unresolved_atomic_indices")
                or validation_metadata.get("invalid_row_atomic_indices")
                or validation_metadata.get("expected_atomic_indices")
                or []
            )
            if str(value).strip()
        ]
        repair_payload = {{
            "repair_mode": "line_role",
            "shard_id": str(shard_row.get("shard_id") or ""),
            "accepted_atomic_indices": [
                int(value)
                for value in validation_metadata.get("accepted_atomic_indices", [])
                if str(value).strip()
            ],
            "unresolved_atomic_indices": unresolved_atomic_indices,
            "validation_errors": errors,
            "frozen_rows": [
                dict(row)
                for row in validation_metadata.get("accepted_rows", [])
                if isinstance(row, dict)
            ],
            "rows": [
                input_row_by_atomic_index[index]
                for index in unresolved_atomic_indices
                if index in input_row_by_atomic_index
            ],
        }}
        save_json((workspace_root / repair_path).resolve(), repair_payload)
        repair_written = True
    elif repair_path:
        candidate = (workspace_root / repair_path).resolve()
        if candidate.exists():
            candidate.unlink()
    feedback_text = render_feedback(
        shard_row,
        errors,
        validation_metadata,
        repair_written=repair_written,
    )
    save_text(workspace_root / "CURRENT_PHASE_FEEDBACK.md", feedback_text)
    if errors:
        print(json.dumps({{"status": "invalid", "errors": errors, "metadata": validation_metadata}}, indent=2, sort_keys=True))
        raise SystemExit(1)
    print(f"OK {{str(shard_row.get('shard_id') or '').strip()}}")


def cmd_install_phase(workspace_root: Path, shard_id: str | None):
    shard_row = resolve_shard_row(workspace_root, shard_id)
    metadata = coerce_metadata(shard_row)
    work_path = str(metadata.get("work_path") or "").strip()
    result_path = str(metadata.get("result_path") or "").strip()
    if not work_path or not result_path:
        raise SystemExit("current phase is missing work_path or result_path")
    resolved_work_path = (workspace_root / work_path).resolve()
    payload = load_json(resolved_work_path)
    existing_repair_request = load_existing_repair_request(workspace_root, shard_row)
    frozen_rows = (
        existing_repair_request.get("frozen_rows")
        if isinstance(existing_repair_request, dict)
        else None
    )
    errors, validation_metadata = validate_payload(
        workspace_root,
        shard_row,
        payload,
        frozen_rows_by_atomic_index=frozen_rows,
    )
    if errors:
        feedback_text = render_feedback(
            shard_row,
            errors,
            validation_metadata,
            repair_written=bool(str(metadata.get("repair_path") or "").strip()),
        )
        save_text(workspace_root / "CURRENT_PHASE_FEEDBACK.md", feedback_text)
        print(json.dumps({{"status": "invalid", "errors": errors, "metadata": validation_metadata}}, indent=2, sort_keys=True))
        raise SystemExit(1)
    destination = (workspace_root / result_path).resolve()
    save_json(destination, payload)
    next_shard = next_pending_shard(
        workspace_root,
        str(shard_row.get("shard_id") or "").strip(),
    )
    if next_shard is None:
        write_current_phase_files(
            workspace_root,
            None,
            completed=True,
            feedback_text="# Current Phase Feedback\\n\\nAll assigned line-role shards are installed.\\n",
        )
    else:
        write_current_phase_files(workspace_root, next_shard)
    print(workspace_relative_path(workspace_root, destination))


def build_parser():
    parser = argparse.ArgumentParser(prog="line_role_worker.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("overview")

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("shard_id", nargs="?")

    scaffold_parser = subparsers.add_parser("scaffold")
    scaffold_parser.add_argument("shard_id", nargs="?")
    scaffold_parser.add_argument("--dest")

    check_phase_parser = subparsers.add_parser("check-phase")
    check_phase_parser.add_argument("--shard-id")

    install_phase_parser = subparsers.add_parser("install-phase")
    install_phase_parser.add_argument("--shard-id")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    workspace_root = Path.cwd()
    if args.command == "overview":
        cmd_overview(workspace_root)
    elif args.command == "show":
        cmd_show(workspace_root, args.shard_id)
    elif args.command == "scaffold":
        cmd_scaffold(workspace_root, args.shard_id, args.dest)
    elif args.command == "check-phase":
        cmd_check_phase(workspace_root, args.shard_id)
    elif args.command == "install-phase":
        cmd_install_phase(workspace_root, args.shard_id)
    else:
        raise SystemExit(f"unknown command: {{args.command}}")


if __name__ == "__main__":
    main()
"""
    return (
        script.replace("__ALLOWED_LABELS_JSON__", allowed_labels_json)
        .replace("__LABEL_BY_CODE_JSON__", label_by_code_json)
        .replace("__VALID_REASONS_JSON__", valid_reasons_json)
        .replace("{{", "{")
        .replace("}}", "}")
    )
