from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence


KNOWLEDGE_WORKER_TOOL_FILENAME = "knowledge_worker.py"
KNOWLEDGE_VALID_OUTPUT_EXAMPLE_FILENAME = "valid_knowledge_output.json"
KNOWLEDGE_VALID_OUTPUT_EXAMPLE_PAYLOAD = {
    "packet_id": "book.ks0000.nr",
    "block_decisions": [
        {"block_index": 10, "category": "knowledge", "reviewer_category": "knowledge"},
        {"block_index": 11, "category": "other", "reviewer_category": "other"},
    ],
    "idea_groups": [
        {
            "group_id": "g01",
            "topic_label": "Heat control",
            "block_indices": [10],
        }
    ],
}
KNOWLEDGE_OUTPUT_CONTRACT_MARKDOWN = """# Knowledge Ledger Contract

Use this contract for every installed `out/<shard_id>.json`.

Required shape:

    {"packet_id":"book.ks0000.nr","block_decisions":[{"block_index":10,"category":"knowledge"}],"idea_groups":[{"group_id":"g01","topic_label":"Heat control","block_indices":[10]}]}

Rules:

- The file must be one JSON object.
- Top level keys: `packet_id`, `block_decisions`, `idea_groups`.
- `packet_id` must match the active shard id.
- `block_decisions` must cover every owned block exactly once and keep the same block order as `in/<shard_id>.json`.
- Each block decision must use `block_index` plus `category`, with optional `reviewer_category`.
- `category` must be `knowledge` or `other`.
- Each `knowledge` block must appear in exactly one idea group.
- `idea_groups` rows must use `group_id`, `topic_label`, and `block_indices`.
- Group ids may span more than one kept block, but one `group_id` must keep one `topic_label`.
- Do not add markdown, commentary, or extra JSON wrapper keys.
"""


def _coerce_metadata(shard_row: Mapping[str, Any]) -> dict[str, Any]:
    metadata = shard_row.get("metadata")
    if isinstance(metadata, Mapping):
        return dict(metadata)
    return {}


def _load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} did not contain a JSON object")
    return dict(payload)


def _save_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _workspace_relative_path(workspace_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(workspace_root))
    except ValueError:
        return str(path)


def _input_blocks(input_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    blocks = input_payload.get("b")
    if not isinstance(blocks, list):
        return []
    return [dict(block) for block in blocks if isinstance(block, Mapping)]


def build_knowledge_workspace_shard_metadata(
    *,
    shard_id: str,
    input_payload: Mapping[str, Any] | None,
    input_path: str,
    hint_path: str,
    result_path: str,
) -> dict[str, Any]:
    blocks = _input_blocks(dict(input_payload or {}))
    block_indices = [
        int(block.get("i"))
        for block in blocks
        if block.get("i") is not None
    ]
    return {
        "phase_key": "knowledge_pass_1",
        "shard_id": str(shard_id),
        "input_path": str(input_path),
        "hint_path": str(hint_path),
        "result_path": str(result_path),
        "owned_row_count": len(block_indices),
        "block_index_start": block_indices[0] if block_indices else None,
        "block_index_end": block_indices[-1] if block_indices else None,
    }


def build_knowledge_seed_output(
    input_payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "packet_id": str(input_payload.get("bid") or input_payload.get("packet_id") or ""),
        "block_decisions": [
            {
                "block_index": int(block.get("i")),
                "category": "other",
                "reviewer_category": "other",
            }
            for block in _input_blocks(input_payload)
            if block.get("i") is not None
        ],
        "idea_groups": [],
    }


def build_pass1_work_ledger(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "phase": "pass1",
        "rows": [
            {
                "block_index": int(block.get("i")),
                "category": "other",
            }
            for block in _input_blocks(input_payload)
            if block.get("i") is not None
        ],
    }


def migrate_legacy_pass1_work_ledger(
    *,
    input_payload: Mapping[str, Any],
    payload: Any,
) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    decisions = payload.get("block_decisions")
    if not isinstance(decisions, list):
        return None
    category_by_index: dict[int, str] = {}
    for decision in decisions:
        if not isinstance(decision, Mapping) or decision.get("block_index") is None:
            continue
        try:
            block_index = int(decision.get("block_index"))
        except (TypeError, ValueError):
            continue
        category = str(decision.get("category") or "").strip()
        category_by_index[block_index] = (
            category if category in {"knowledge", "other"} else "other"
        )
    return {
        "phase": "pass1",
        "rows": [
            {
                "block_index": int(block.get("i")),
                "category": category_by_index.get(int(block.get("i")), "other"),
            }
            for block in _input_blocks(input_payload)
            if block.get("i") is not None
        ],
    }


def build_pass2_input_ledger(
    *,
    input_payload: Mapping[str, Any],
    pass1_payload: Mapping[str, Any],
) -> dict[str, Any]:
    text_by_index = {
        int(block.get("i")): str(block.get("t") or "").strip()
        for block in _input_blocks(input_payload)
        if block.get("i") is not None
    }
    kept_indices = [
        int(row.get("block_index"))
        for row in (pass1_payload.get("rows") or [])
        if isinstance(row, Mapping) and str(row.get("category") or "").strip() == "knowledge"
    ]
    return {
        "phase": "pass2",
        "rows": [
            {
                "block_index": block_index,
                "text": text_by_index.get(block_index, ""),
            }
            for block_index in kept_indices
        ],
    }


def build_pass2_work_ledger(pass2_input_payload: Mapping[str, Any]) -> dict[str, Any]:
    rows = pass2_input_payload.get("rows")
    if not isinstance(rows, list):
        rows = []
    work_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping) or row.get("block_index") is None:
            continue
        work_rows.append(
            {
                "block_index": int(row.get("block_index")),
                "group_id": f"g{index:02d}",
                "topic_label": "",
            }
        )
    return {"phase": "pass2", "rows": work_rows}


def build_final_output(
    *,
    shard_id: str,
    pass1_payload: Mapping[str, Any],
    pass2_payload: Mapping[str, Any],
) -> dict[str, Any]:
    decisions = [
        {
            "block_index": int(row.get("block_index")),
            "category": str(row.get("category") or "").strip(),
            "reviewer_category": (
                "knowledge"
                if str(row.get("category") or "").strip() == "knowledge"
                else "other"
            ),
        }
        for row in (pass1_payload.get("rows") or [])
        if isinstance(row, Mapping) and row.get("block_index") is not None
    ]
    groups_by_id: dict[str, dict[str, Any]] = {}
    for row in (pass2_payload.get("rows") or []):
        if not isinstance(row, Mapping) or row.get("block_index") is None:
            continue
        group_id = str(row.get("group_id") or "").strip()
        topic_label = str(row.get("topic_label") or "").strip()
        if not group_id or not topic_label:
            continue
        group = groups_by_id.setdefault(
            group_id,
            {
                "group_id": group_id,
                "topic_label": topic_label,
                "block_indices": [],
            },
        )
        group["block_indices"].append(int(row.get("block_index")))
    ordered_groups = [
        {
            "group_id": group["group_id"],
            "topic_label": group["topic_label"],
            "block_indices": group["block_indices"],
        }
        for group in groups_by_id.values()
    ]
    return {
        "packet_id": shard_id,
        "block_decisions": decisions,
        "idea_groups": ordered_groups,
    }


def _normalize_frozen_rows_by_block_index(
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
            block_index = int(row.get("block_index"))
        except (TypeError, ValueError):
            continue
        normalized_row = {"block_index": block_index}
        if row.get("category") is not None:
            normalized_row["category"] = str(row.get("category") or "").strip()
        if row.get("group_id") is not None:
            normalized_row["group_id"] = str(row.get("group_id") or "").strip()
        if row.get("topic_label") is not None:
            normalized_row["topic_label"] = str(row.get("topic_label") or "").strip()
        normalized[block_index] = normalized_row
    return normalized


def _pass1_input_rows_by_block_index(
    input_payload: Mapping[str, Any],
) -> dict[int, dict[str, Any]]:
    return {
        int(block.get("i")): {
            "block_index": int(block.get("i")),
            "text": str(block.get("t") or "").strip(),
        }
        for block in _input_blocks(input_payload)
        if block.get("i") is not None
    }


def _pass2_input_rows_by_block_index(
    pass2_input_payload: Mapping[str, Any],
) -> dict[int, dict[str, Any]]:
    rows = pass2_input_payload.get("rows")
    if not isinstance(rows, list):
        rows = []
    return {
        int(row.get("block_index")): {
            "block_index": int(row.get("block_index")),
            "text": str(row.get("text") or "").strip(),
        }
        for row in rows
        if isinstance(row, Mapping) and row.get("block_index") is not None
    }


def _resolved_unresolved_block_indices(
    *,
    metadata: Mapping[str, Any],
) -> list[int]:
    unresolved = [
        int(value)
        for value in (metadata.get("unresolved_block_indices") or [])
        if str(value).strip()
    ]
    if unresolved:
        return unresolved
    return [
        int(value)
        for value in (metadata.get("expected_block_indices") or [])
        if str(value).strip()
    ]


def _merge_frozen_rows_by_block_index(
    *,
    frozen_rows_by_block_index: Mapping[int, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None = None,
    accepted_rows: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    merged = _normalize_frozen_rows_by_block_index(frozen_rows_by_block_index)
    for row in accepted_rows or ():
        if not isinstance(row, Mapping) or row.get("block_index") is None:
            continue
        block_index = int(row.get("block_index"))
        merged[block_index] = {
            key: value
            for key, value in dict(row).items()
            if key in {"block_index", "category", "group_id", "topic_label"}
        }
        merged[block_index]["block_index"] = block_index
    return [merged[block_index] for block_index in sorted(merged)]


def build_pass1_repair_request_payload(
    *,
    input_payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
    validation_errors: Sequence[str],
    frozen_rows_by_block_index: Mapping[int, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    unresolved_block_indices = _resolved_unresolved_block_indices(metadata=metadata)
    input_rows_by_block_index = _pass1_input_rows_by_block_index(input_payload)
    frozen_rows = _merge_frozen_rows_by_block_index(
        frozen_rows_by_block_index=frozen_rows_by_block_index,
        accepted_rows=[
            dict(row)
            for row in (metadata.get("accepted_rows") or [])
            if isinstance(row, Mapping)
        ],
    )
    return {
        "repair_mode": "knowledge_phase",
        "phase": "pass1",
        "accepted_block_indices": [int(row["block_index"]) for row in frozen_rows],
        "unresolved_block_indices": unresolved_block_indices,
        "validation_errors": [
            str(error).strip() for error in validation_errors if str(error).strip()
        ],
        "frozen_rows": frozen_rows,
        "rows": [
            input_rows_by_block_index[block_index]
            for block_index in unresolved_block_indices
            if block_index in input_rows_by_block_index
        ],
    }


def build_pass2_repair_request_payload(
    *,
    pass2_input_payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
    validation_errors: Sequence[str],
    frozen_rows_by_block_index: Mapping[int, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    unresolved_block_indices = _resolved_unresolved_block_indices(metadata=metadata)
    input_rows_by_block_index = _pass2_input_rows_by_block_index(pass2_input_payload)
    frozen_rows = _merge_frozen_rows_by_block_index(
        frozen_rows_by_block_index=frozen_rows_by_block_index,
        accepted_rows=[
            dict(row)
            for row in (metadata.get("accepted_rows") or [])
            if isinstance(row, Mapping)
        ],
    )
    return {
        "repair_mode": "knowledge_phase",
        "phase": "pass2",
        "accepted_block_indices": [int(row["block_index"]) for row in frozen_rows],
        "unresolved_block_indices": unresolved_block_indices,
        "validation_errors": [
            str(error).strip() for error in validation_errors if str(error).strip()
        ],
        "frozen_rows": frozen_rows,
        "rows": [
            input_rows_by_block_index[block_index]
            for block_index in unresolved_block_indices
            if block_index in input_rows_by_block_index
        ],
    }


def validate_pass1_work_ledger(
    *,
    input_payload: Mapping[str, Any],
    payload: Any,
    frozen_rows_by_block_index: Mapping[int, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None = None,
) -> tuple[tuple[str, ...], dict[str, Any]]:
    expected_block_indices = [
        int(block.get("i"))
        for block in _input_blocks(input_payload)
        if block.get("i") is not None
    ]
    metadata: dict[str, Any] = {
        "expected_block_indices": expected_block_indices,
        "owned_row_count": len(expected_block_indices),
    }
    if not isinstance(payload, Mapping):
        return ("payload_not_object",), metadata
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return ("rows_not_list",), metadata
    actual_indices: list[int] = []
    errors: list[str] = []
    invalid_block_indices: list[int] = []
    unresolved_block_indices: set[int] = set()
    row_error_map: dict[int, list[str]] = {}
    parsed_rows: list[dict[str, Any] | None] = []
    seen_block_indices: set[int] = set()
    duplicate_block_indices: set[int] = set()
    frozen_by_block_index = _normalize_frozen_rows_by_block_index(
        frozen_rows_by_block_index
    )
    for row in rows:
        if not isinstance(row, Mapping) or row.get("block_index") is None:
            errors.append("row_missing_block_index")
            parsed_rows.append(None)
            continue
        block_index = int(row.get("block_index"))
        actual_indices.append(block_index)
        row_errors: list[str] = []
        category = str(row.get("category") or "").strip()
        if category not in {"knowledge", "other"}:
            row_errors.append("invalid_block_category")
        if block_index in seen_block_indices:
            duplicate_block_indices.add(block_index)
            row_errors.append("duplicate_block_index")
        seen_block_indices.add(block_index)
        if row_errors:
            invalid_block_indices.append(block_index)
            unresolved_block_indices.add(block_index)
            row_error_map.setdefault(block_index, []).extend(row_errors)
        parsed_rows.append(
            {
                "block_index": block_index,
                "category": category,
            }
        )
    if actual_indices != expected_block_indices:
        missing = [idx for idx in expected_block_indices if idx not in actual_indices]
        unexpected = [idx for idx in actual_indices if idx not in expected_block_indices]
        if missing:
            errors.append("missing_owned_block_decisions")
            metadata["missing_owned_block_indices"] = missing
            unresolved_block_indices.update(missing)
        if unexpected:
            errors.append("unexpected_block_decisions")
            metadata["unexpected_block_indices"] = unexpected
            unresolved_block_indices.update(unexpected)
        if not missing and not unexpected:
            errors.append("block_decision_order_mismatch")
            unresolved_block_indices.update(expected_block_indices)
    if invalid_block_indices:
        errors.append("invalid_block_category")
        metadata["invalid_block_category_indices"] = invalid_block_indices
    accepted_rows: list[dict[str, Any]] = []
    accepted_block_indices: list[int] = []
    for position, expected_block_index in enumerate(expected_block_indices):
        parsed_row = parsed_rows[position] if position < len(parsed_rows) else None
        if parsed_row is None:
            unresolved_block_indices.add(expected_block_index)
            continue
        actual_block_index = int(parsed_row.get("block_index"))
        if actual_block_index != expected_block_index:
            unresolved_block_indices.add(expected_block_index)
            continue
        if actual_block_index in duplicate_block_indices:
            unresolved_block_indices.add(expected_block_index)
            continue
        if actual_block_index in row_error_map:
            unresolved_block_indices.add(expected_block_index)
            continue
        frozen_row = frozen_by_block_index.get(expected_block_index)
        if frozen_row is not None and dict(parsed_row) != frozen_row:
            errors.append(f"frozen_row_modified:{expected_block_index}")
            invalid_block_indices.append(expected_block_index)
            row_error_map.setdefault(expected_block_index, []).append(
                "frozen_row_modified"
            )
            unresolved_block_indices.add(expected_block_index)
            continue
        accepted_block_indices.append(expected_block_index)
        accepted_rows.append(dict(parsed_row))
    metadata["kept_block_indices"] = [
        int(row.get("block_index"))
        for row in rows
        if isinstance(row, Mapping) and str(row.get("category") or "").strip() == "knowledge"
    ]
    metadata["accepted_block_indices"] = accepted_block_indices
    metadata["accepted_rows"] = accepted_rows
    metadata["row_errors_by_block_index"] = {
        str(block_index): sorted(set(row_errors))
        for block_index, row_errors in sorted(row_error_map.items())
    }
    metadata["frozen_block_indices"] = sorted(frozen_by_block_index)
    metadata["unresolved_block_indices"] = [
        block_index
        for block_index in expected_block_indices
        if block_index in unresolved_block_indices
    ] or list(expected_block_indices if errors else [])
    return tuple(dict.fromkeys(errors)), metadata


def validate_pass2_work_ledger(
    *,
    pass2_input_payload: Mapping[str, Any],
    payload: Any,
    frozen_rows_by_block_index: Mapping[int, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None = None,
) -> tuple[tuple[str, ...], dict[str, Any]]:
    expected_block_indices = [
        int(row.get("block_index"))
        for row in (pass2_input_payload.get("rows") or [])
        if isinstance(row, Mapping) and row.get("block_index") is not None
    ]
    metadata: dict[str, Any] = {
        "expected_block_indices": expected_block_indices,
        "owned_row_count": len(expected_block_indices),
    }
    if not isinstance(payload, Mapping):
        return ("payload_not_object",), metadata
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return ("rows_not_list",), metadata
    actual_indices: list[int] = []
    errors: list[str] = []
    group_id_to_topic: dict[str, str] = {}
    invalid_block_indices: list[int] = []
    unresolved_block_indices: set[int] = set()
    row_error_map: dict[int, list[str]] = {}
    parsed_rows: list[dict[str, Any] | None] = []
    seen_block_indices: set[int] = set()
    duplicate_block_indices: set[int] = set()
    frozen_by_block_index = _normalize_frozen_rows_by_block_index(
        frozen_rows_by_block_index
    )
    for row in rows:
        if not isinstance(row, Mapping) or row.get("block_index") is None:
            errors.append("row_missing_block_index")
            parsed_rows.append(None)
            continue
        block_index = int(row.get("block_index"))
        actual_indices.append(block_index)
        row_errors: list[str] = []
        group_id = str(row.get("group_id") or "").strip()
        topic_label = str(row.get("topic_label") or "").strip()
        if not group_id or not topic_label:
            row_errors.append("knowledge_block_missing_group")
        previous_topic = group_id_to_topic.get(group_id)
        if group_id and previous_topic is None:
            group_id_to_topic[group_id] = topic_label
        elif group_id and previous_topic != topic_label:
            row_errors.append("knowledge_block_group_conflict")
            metadata.setdefault("group_id_topic_conflicts", []).append(group_id)
        if block_index in seen_block_indices:
            duplicate_block_indices.add(block_index)
            row_errors.append("duplicate_block_index")
        seen_block_indices.add(block_index)
        if row_errors:
            invalid_block_indices.append(block_index)
            unresolved_block_indices.add(block_index)
            row_error_map.setdefault(block_index, []).extend(row_errors)
        parsed_rows.append(
            {
                "block_index": block_index,
                "group_id": group_id,
                "topic_label": topic_label,
            }
        )
    if actual_indices != expected_block_indices:
        missing = [idx for idx in expected_block_indices if idx not in actual_indices]
        unexpected = [idx for idx in actual_indices if idx not in expected_block_indices]
        if missing:
            errors.append("knowledge_block_missing_group")
            metadata["knowledge_blocks_missing_group"] = missing
            unresolved_block_indices.update(missing)
        if unexpected:
            errors.append("group_contains_other_block")
            metadata["group_blocks_out_of_surface"] = unexpected
            unresolved_block_indices.update(unexpected)
        if not missing and not unexpected:
            errors.append("block_decision_order_mismatch")
            unresolved_block_indices.update(expected_block_indices)
    if invalid_block_indices:
        errors.append("knowledge_block_missing_group")
        metadata.setdefault("knowledge_blocks_missing_group", []).extend(invalid_block_indices)
    accepted_rows: list[dict[str, Any]] = []
    accepted_block_indices: list[int] = []
    for position, expected_block_index in enumerate(expected_block_indices):
        parsed_row = parsed_rows[position] if position < len(parsed_rows) else None
        if parsed_row is None:
            unresolved_block_indices.add(expected_block_index)
            continue
        actual_block_index = int(parsed_row.get("block_index"))
        if actual_block_index != expected_block_index:
            unresolved_block_indices.add(expected_block_index)
            continue
        if actual_block_index in duplicate_block_indices:
            unresolved_block_indices.add(expected_block_index)
            continue
        if actual_block_index in row_error_map:
            unresolved_block_indices.add(expected_block_index)
            continue
        frozen_row = frozen_by_block_index.get(expected_block_index)
        if frozen_row is not None and dict(parsed_row) != frozen_row:
            errors.append(f"frozen_row_modified:{expected_block_index}")
            invalid_block_indices.append(expected_block_index)
            row_error_map.setdefault(expected_block_index, []).append(
                "frozen_row_modified"
            )
            unresolved_block_indices.add(expected_block_index)
            continue
        accepted_block_indices.append(expected_block_index)
        accepted_rows.append(dict(parsed_row))
    metadata["group_ids"] = sorted(group_id_to_topic)
    metadata["accepted_block_indices"] = accepted_block_indices
    metadata["accepted_rows"] = accepted_rows
    metadata["row_errors_by_block_index"] = {
        str(block_index): sorted(set(row_errors))
        for block_index, row_errors in sorted(row_error_map.items())
    }
    metadata["frozen_block_indices"] = sorted(frozen_by_block_index)
    metadata["unresolved_block_indices"] = [
        block_index
        for block_index in expected_block_indices
        if block_index in unresolved_block_indices
    ] or list(expected_block_indices if errors else [])
    return tuple(dict.fromkeys(errors)), metadata


def render_knowledge_current_phase_brief(
    phase_row: Mapping[str, Any] | None,
) -> str:
    if phase_row is None:
        return "# Current Knowledge Phase\n\nNo active knowledge shard.\n"
    if str(phase_row.get("status") or "").strip() == "completed":
        return "# Current Knowledge Phase\n\nAll assigned knowledge shards are installed.\n"
    lines = [
        "# Current Knowledge Phase",
        "",
        f"Shard id: `{phase_row.get('shard_id') or '[unknown shard]'}`",
        f"Phase: `{phase_row.get('phase') or '[unknown phase]'}`",
        f"Input file: `{phase_row.get('input_path') or '?'}`",
        f"Work file: `{phase_row.get('work_path') or '?'}`",
        f"Repair file: `{phase_row.get('repair_path') or '?'}`",
        f"Result file: `{phase_row.get('result_path') or '?'}`",
        "",
    ]
    if str(phase_row.get("phase") or "").strip() == "pass1":
        lines.extend(
            [
                "Pass 1 contract: return one row per owned block with `knowledge` or `other`.",
                "Do not create topic labels or group ids in Pass 1.",
            ]
        )
    else:
        lines.extend(
            [
                "Pass 2 contract: return one row per kept knowledge block with `group_id` and `topic_label`.",
                "Use the same `group_id` on blocks that belong in the same knowledge group.",
            ]
        )
    lines.extend(
        [
            "",
            "Recommended loop:",
            "1. Open `CURRENT_PHASE.md`, then the named work file.",
            "2. Read the named input and hint files only when needed.",
            "3. Run `python3 tools/knowledge_worker.py check-phase`.",
            "4. If `CURRENT_PHASE_FEEDBACK.md` names a repair file, fix only those unresolved rows.",
            "5. Run `python3 tools/knowledge_worker.py install-phase` after the current work ledger validates cleanly.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_knowledge_current_phase_feedback(
    *,
    phase_row: Mapping[str, Any] | None,
    validation_errors: Sequence[str] = (),
    validation_metadata: Mapping[str, Any] | None = None,
    completed: bool = False,
) -> str:
    if completed:
        return "# Current Phase Feedback\n\nAll assigned knowledge shards are installed.\n"
    if phase_row is None:
        return "# Current Phase Feedback\n\nNo active knowledge shard.\n"
    if not validation_errors:
        return (
            "# Current Phase Feedback\n\n"
            "Current work ledger validates cleanly.\n"
            f"Install target: `{phase_row.get('result_path') or '<missing>'}`\n"
        )
    unresolved = []
    if isinstance(validation_metadata, Mapping):
        unresolved = [
            int(value)
            for value in (validation_metadata.get("unresolved_block_indices") or [])
            if str(value).strip()
        ]
    lines = [
        "# Current Phase Feedback",
        "",
        "Current work ledger is still unresolved.",
        "Validation errors:",
    ]
    lines.extend(f"- `{error}`" for error in validation_errors if str(error).strip())
    if phase_row.get("repair_path"):
        lines.append(f"Repair request: `{phase_row.get('repair_path')}`")
    if unresolved:
        lines.append(
            "Unresolved block indices: "
            f"`{', '.join(str(value) for value in unresolved)}`"
        )
    accepted = []
    if isinstance(validation_metadata, Mapping):
        accepted = [
            int(value)
            for value in (
                validation_metadata.get("frozen_block_indices")
                or validation_metadata.get("accepted_block_indices")
                or []
            )
            if str(value).strip()
        ]
    if accepted:
        lines.append(
            "Frozen accepted block indices: "
            f"`{', '.join(str(value) for value in accepted)}`"
        )
    return "\n".join(lines) + "\n"


def render_knowledge_worker_script() -> str:
    output_contract_markdown = json.dumps(KNOWLEDGE_OUTPUT_CONTRACT_MARKDOWN)
    valid_example_json = json.dumps(
        json.dumps(KNOWLEDGE_VALID_OUTPUT_EXAMPLE_PAYLOAD, indent=2, sort_keys=True) + "\n"
    )
    script = """#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

OUTPUT_CONTRACT_MARKDOWN = __OUTPUT_CONTRACT_MARKDOWN__
VALID_EXAMPLE_JSON = __VALID_EXAMPLE_JSON__


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")


def save_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def workspace_root() -> Path:
    return Path.cwd()


def assigned_shards():
    payload = load_json(workspace_root() / "assigned_shards.json")
    if not isinstance(payload, list):
        raise SystemExit("assigned_shards.json is not a list")
    return [row for row in payload if isinstance(row, dict)]


def current_phase():
    path = workspace_root() / "current_phase.json"
    if not path.exists():
        return None
    payload = load_json(path)
    return payload if isinstance(payload, dict) else None


def relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(workspace_root()))
    except ValueError:
        return str(path)


def load_phase_input(phase_row):
    return load_json(workspace_root() / str(phase_row.get("input_path") or ""))


def load_phase_work(phase_row):
    return load_json(workspace_root() / str(phase_row.get("work_path") or ""))


def input_blocks(input_payload):
    blocks = input_payload.get("b")
    if not isinstance(blocks, list):
        return []
    return [dict(block) for block in blocks if isinstance(block, dict)]


def build_pass1_seed(input_payload):
    return {{
        "phase": "pass1",
        "rows": [
            {{"block_index": int(block.get("i")), "category": "other"}}
            for block in input_blocks(input_payload)
            if block.get("i") is not None
        ],
    }}


def migrate_legacy_pass1_work(input_payload, payload):
    if not isinstance(payload, dict):
        return None
    decisions = payload.get("block_decisions")
    if not isinstance(decisions, list):
        return None
    category_by_index = {{}}
    for decision in decisions:
        if not isinstance(decision, dict) or decision.get("block_index") is None:
            continue
        try:
            block_index = int(decision.get("block_index"))
        except (TypeError, ValueError):
            continue
        category = str(decision.get("category") or "").strip()
        category_by_index[block_index] = (
            category if category in {{"knowledge", "other"}} else "other"
        )
    return {{
        "phase": "pass1",
        "rows": [
            {{
                "block_index": int(block.get("i")),
                "category": category_by_index.get(int(block.get("i")), "other"),
            }}
            for block in input_blocks(input_payload)
            if block.get("i") is not None
        ],
    }}


def build_pass2_input(input_payload, pass1_payload):
    text_by_index = {{
        int(block.get("i")): str(block.get("t") or "").strip()
        for block in input_blocks(input_payload)
        if block.get("i") is not None
    }}
    kept = [
        int(row.get("block_index"))
        for row in (pass1_payload.get("rows") or [])
        if isinstance(row, dict) and str(row.get("category") or "").strip() == "knowledge"
    ]
    return {{
        "phase": "pass2",
        "rows": [
            {{"block_index": block_index, "text": text_by_index.get(block_index, "")}}
            for block_index in kept
        ],
    }}


def build_pass2_seed(pass2_input_payload):
    rows = pass2_input_payload.get("rows")
    if not isinstance(rows, list):
        rows = []
    return {{
        "phase": "pass2",
        "rows": [
            {{
                "block_index": int(row.get("block_index")),
                "group_id": f"g{{index:02d}}",
                "topic_label": "",
            }}
            for index, row in enumerate(rows, start=1)
            if isinstance(row, dict) and row.get("block_index") is not None
        ],
    }}


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
            block_index = int(row.get("block_index"))
        except (TypeError, ValueError):
            continue
        normalized_row = {{"block_index": block_index}}
        if row.get("category") is not None:
            normalized_row["category"] = str(row.get("category") or "").strip()
        if row.get("group_id") is not None:
            normalized_row["group_id"] = str(row.get("group_id") or "").strip()
        if row.get("topic_label") is not None:
            normalized_row["topic_label"] = str(row.get("topic_label") or "").strip()
        normalized[block_index] = normalized_row
    return normalized


def merge_frozen_rows(frozen_rows, accepted_rows):
    merged = normalize_frozen_rows(frozen_rows)
    for row in accepted_rows or []:
        if not isinstance(row, dict) or row.get("block_index") is None:
            continue
        block_index = int(row.get("block_index"))
        normalized_row = {{"block_index": block_index}}
        if row.get("category") is not None:
            normalized_row["category"] = str(row.get("category") or "").strip()
        if row.get("group_id") is not None:
            normalized_row["group_id"] = str(row.get("group_id") or "").strip()
        if row.get("topic_label") is not None:
            normalized_row["topic_label"] = str(row.get("topic_label") or "").strip()
        merged[block_index] = normalized_row
    return [merged[block_index] for block_index in sorted(merged)]


def pass1_input_rows_by_block_index(input_payload):
    return {{
        int(block.get("i")): {{
            "block_index": int(block.get("i")),
            "text": str(block.get("t") or "").strip(),
        }}
        for block in input_blocks(input_payload)
        if block.get("i") is not None
    }}


def pass2_input_rows_by_block_index(pass2_input_payload):
    rows = pass2_input_payload.get("rows")
    if not isinstance(rows, list):
        rows = []
    return {{
        int(row.get("block_index")): {{
            "block_index": int(row.get("block_index")),
            "text": str(row.get("text") or "").strip(),
        }}
        for row in rows
        if isinstance(row, dict) and row.get("block_index") is not None
    }}


def resolved_unresolved_block_indices(metadata):
    unresolved = [
        int(value)
        for value in (metadata.get("unresolved_block_indices") or [])
        if str(value).strip()
    ]
    if unresolved:
        return unresolved
    return [
        int(value)
        for value in (metadata.get("expected_block_indices") or [])
        if str(value).strip()
    ]


def build_pass1_repair_payload(input_payload, metadata, validation_errors, *, frozen_rows=None):
    unresolved = resolved_unresolved_block_indices(metadata)
    input_rows_by_block_index = pass1_input_rows_by_block_index(input_payload)
    merged_frozen_rows = merge_frozen_rows(
        frozen_rows,
        [
            dict(row)
            for row in (metadata.get("accepted_rows") or [])
            if isinstance(row, dict)
        ],
    )
    return {{
        "repair_mode": "knowledge_phase",
        "phase": "pass1",
        "accepted_block_indices": [
            int(row.get("block_index"))
            for row in merged_frozen_rows
            if row.get("block_index") is not None
        ],
        "unresolved_block_indices": unresolved,
        "validation_errors": [
            str(error).strip()
            for error in validation_errors
            if str(error).strip()
        ],
        "frozen_rows": merged_frozen_rows,
        "rows": [
            input_rows_by_block_index[block_index]
            for block_index in unresolved
            if block_index in input_rows_by_block_index
        ],
    }}


def build_pass2_repair_payload(pass2_input_payload, metadata, validation_errors, *, frozen_rows=None):
    unresolved = resolved_unresolved_block_indices(metadata)
    input_rows_by_block_index = pass2_input_rows_by_block_index(pass2_input_payload)
    merged_frozen_rows = merge_frozen_rows(
        frozen_rows,
        [
            dict(row)
            for row in (metadata.get("accepted_rows") or [])
            if isinstance(row, dict)
        ],
    )
    return {{
        "repair_mode": "knowledge_phase",
        "phase": "pass2",
        "accepted_block_indices": [
            int(row.get("block_index"))
            for row in merged_frozen_rows
            if row.get("block_index") is not None
        ],
        "unresolved_block_indices": unresolved,
        "validation_errors": [
            str(error).strip()
            for error in validation_errors
            if str(error).strip()
        ],
        "frozen_rows": merged_frozen_rows,
        "rows": [
            input_rows_by_block_index[block_index]
            for block_index in unresolved
            if block_index in input_rows_by_block_index
        ],
    }}


def validate_pass1(input_payload, payload, *, frozen_rows_by_block_index=None):
    expected = [
        int(block.get("i"))
        for block in input_blocks(input_payload)
        if block.get("i") is not None
    ]
    metadata = {{"expected_block_indices": expected, "owned_row_count": len(expected)}}
    if not isinstance(payload, dict):
        return ["payload_not_object"], metadata
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return ["rows_not_list"], metadata
    actual = []
    errors = []
    invalid = []
    unresolved = set()
    row_error_map = {{}}
    parsed_rows = []
    seen = set()
    duplicates = set()
    frozen_by_block_index = normalize_frozen_rows(frozen_rows_by_block_index)
    for row in rows:
        if not isinstance(row, dict) or row.get("block_index") is None:
            errors.append("row_missing_block_index")
            parsed_rows.append(None)
            continue
        block_index = int(row.get("block_index"))
        actual.append(block_index)
        row_errors = []
        category = str(row.get("category") or "").strip()
        if category not in {{"knowledge", "other"}}:
            row_errors.append("invalid_block_category")
        if block_index in seen:
            duplicates.add(block_index)
            row_errors.append("duplicate_block_index")
        seen.add(block_index)
        if row_errors:
            invalid.append(block_index)
            unresolved.add(block_index)
            row_error_map.setdefault(block_index, []).extend(row_errors)
        parsed_rows.append({{"block_index": block_index, "category": category}})
    if actual != expected:
        missing = [idx for idx in expected if idx not in actual]
        unexpected = [idx for idx in actual if idx not in expected]
        if missing:
            errors.append("missing_owned_block_decisions")
            metadata["missing_owned_block_indices"] = missing
            unresolved.update(missing)
        if unexpected:
            errors.append("unexpected_block_decisions")
            metadata["unexpected_block_indices"] = unexpected
            unresolved.update(unexpected)
        if not missing and not unexpected:
            errors.append("block_decision_order_mismatch")
            unresolved.update(expected)
    if invalid:
        errors.append("invalid_block_category")
        metadata["invalid_block_category_indices"] = invalid
    accepted_rows = []
    accepted_block_indices = []
    for position, expected_block_index in enumerate(expected):
        parsed_row = parsed_rows[position] if position < len(parsed_rows) else None
        if parsed_row is None:
            unresolved.add(expected_block_index)
            continue
        actual_block_index = int(parsed_row.get("block_index"))
        if actual_block_index != expected_block_index:
            unresolved.add(expected_block_index)
            continue
        if actual_block_index in duplicates:
            unresolved.add(expected_block_index)
            continue
        if actual_block_index in row_error_map:
            unresolved.add(expected_block_index)
            continue
        frozen_row = frozen_by_block_index.get(expected_block_index)
        if frozen_row is not None and dict(parsed_row) != frozen_row:
            errors.append(f"frozen_row_modified:{{expected_block_index}}")
            invalid.append(expected_block_index)
            row_error_map.setdefault(expected_block_index, []).append("frozen_row_modified")
            unresolved.add(expected_block_index)
            continue
        accepted_block_indices.append(expected_block_index)
        accepted_rows.append(dict(parsed_row))
    metadata["kept_block_indices"] = [
        int(row.get("block_index"))
        for row in rows
        if isinstance(row, dict) and str(row.get("category") or "").strip() == "knowledge"
    ]
    metadata["accepted_block_indices"] = accepted_block_indices
    metadata["accepted_rows"] = accepted_rows
    metadata["row_errors_by_block_index"] = {{
        str(block_index): sorted(set(row_errors))
        for block_index, row_errors in sorted(row_error_map.items())
    }}
    metadata["frozen_block_indices"] = sorted(frozen_by_block_index)
    metadata["unresolved_block_indices"] = [
        block_index for block_index in expected if block_index in unresolved
    ] or list(expected if errors else [])
    return list(dict.fromkeys(errors)), metadata


def validate_pass2(pass2_input_payload, payload, *, frozen_rows_by_block_index=None):
    expected = [
        int(row.get("block_index"))
        for row in (pass2_input_payload.get("rows") or [])
        if isinstance(row, dict) and row.get("block_index") is not None
    ]
    metadata = {{"expected_block_indices": expected, "owned_row_count": len(expected)}}
    if not isinstance(payload, dict):
        return ["payload_not_object"], metadata
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return ["rows_not_list"], metadata
    actual = []
    group_id_to_topic = {{}}
    errors = []
    invalid = []
    unresolved = set()
    row_error_map = {{}}
    parsed_rows = []
    seen = set()
    duplicates = set()
    frozen_by_block_index = normalize_frozen_rows(frozen_rows_by_block_index)
    for row in rows:
        if not isinstance(row, dict) or row.get("block_index") is None:
            errors.append("row_missing_block_index")
            parsed_rows.append(None)
            continue
        block_index = int(row.get("block_index"))
        actual.append(block_index)
        row_errors = []
        group_id = str(row.get("group_id") or "").strip()
        topic_label = str(row.get("topic_label") or "").strip()
        if not group_id or not topic_label:
            row_errors.append("knowledge_block_missing_group")
        previous = group_id_to_topic.get(group_id)
        if group_id and previous is None:
            group_id_to_topic[group_id] = topic_label
        elif group_id and previous != topic_label:
            row_errors.append("knowledge_block_group_conflict")
            metadata.setdefault("group_id_topic_conflicts", []).append(group_id)
        if block_index in seen:
            duplicates.add(block_index)
            row_errors.append("duplicate_block_index")
        seen.add(block_index)
        if row_errors:
            invalid.append(block_index)
            unresolved.add(block_index)
            row_error_map.setdefault(block_index, []).extend(row_errors)
        parsed_rows.append(
            {{
                "block_index": block_index,
                "group_id": group_id,
                "topic_label": topic_label,
            }}
        )
    if actual != expected:
        missing = [idx for idx in expected if idx not in actual]
        unexpected = [idx for idx in actual if idx not in expected]
        if missing:
            errors.append("knowledge_block_missing_group")
            metadata["knowledge_blocks_missing_group"] = missing
            unresolved.update(missing)
        if unexpected:
            errors.append("group_contains_other_block")
            metadata["group_blocks_out_of_surface"] = unexpected
            unresolved.update(unexpected)
        if not missing and not unexpected:
            errors.append("block_decision_order_mismatch")
            unresolved.update(expected)
    if invalid:
        errors.append("knowledge_block_missing_group")
        metadata.setdefault("knowledge_blocks_missing_group", []).extend(invalid)
    accepted_rows = []
    accepted_block_indices = []
    for position, expected_block_index in enumerate(expected):
        parsed_row = parsed_rows[position] if position < len(parsed_rows) else None
        if parsed_row is None:
            unresolved.add(expected_block_index)
            continue
        actual_block_index = int(parsed_row.get("block_index"))
        if actual_block_index != expected_block_index:
            unresolved.add(expected_block_index)
            continue
        if actual_block_index in duplicates:
            unresolved.add(expected_block_index)
            continue
        if actual_block_index in row_error_map:
            unresolved.add(expected_block_index)
            continue
        frozen_row = frozen_by_block_index.get(expected_block_index)
        if frozen_row is not None and dict(parsed_row) != frozen_row:
            errors.append(f"frozen_row_modified:{{expected_block_index}}")
            invalid.append(expected_block_index)
            row_error_map.setdefault(expected_block_index, []).append("frozen_row_modified")
            unresolved.add(expected_block_index)
            continue
        accepted_block_indices.append(expected_block_index)
        accepted_rows.append(dict(parsed_row))
    metadata["accepted_block_indices"] = accepted_block_indices
    metadata["accepted_rows"] = accepted_rows
    metadata["row_errors_by_block_index"] = {{
        str(block_index): sorted(set(row_errors))
        for block_index, row_errors in sorted(row_error_map.items())
    }}
    metadata["frozen_block_indices"] = sorted(frozen_by_block_index)
    metadata["unresolved_block_indices"] = [
        block_index for block_index in expected if block_index in unresolved
    ] or list(expected if errors else [])
    return list(dict.fromkeys(errors)), metadata


def render_phase_brief(phase_row):
    if phase_row is None:
        return "# Current Knowledge Phase\\n\\nNo active knowledge shard.\\n"
    if str(phase_row.get("status") or "").strip() == "completed":
        return "# Current Knowledge Phase\\n\\nAll assigned knowledge shards are installed.\\n"
    lines = [
        "# Current Knowledge Phase",
        "",
        f"Shard id: `{{phase_row.get('shard_id') or '[unknown shard]'}}`",
        f"Phase: `{{phase_row.get('phase') or '[unknown phase]'}}`",
        f"Input file: `{{phase_row.get('input_path') or '?'}}`",
        f"Work file: `{{phase_row.get('work_path') or '?'}}`",
        f"Repair file: `{{phase_row.get('repair_path') or '?'}}`",
        f"Result file: `{{phase_row.get('result_path') or '?'}}`",
        "",
    ]
    if str(phase_row.get("phase") or "").strip() == "pass1":
        lines.extend([
            "Pass 1 contract: return one row per owned block with `knowledge` or `other`.",
            "Do not create topic labels or group ids in Pass 1.",
        ])
    else:
        lines.extend([
            "Pass 2 contract: return one row per kept knowledge block with `group_id` and `topic_label`.",
            "Use the same `group_id` on blocks that belong in the same knowledge group.",
        ])
    return "\\n".join(lines) + "\\n"


def render_phase_feedback(phase_row, validation_errors=(), validation_metadata=None, *, completed=False):
    if completed:
        return "# Current Phase Feedback\\n\\nAll assigned knowledge shards are installed.\\n"
    if phase_row is None:
        return "# Current Phase Feedback\\n\\nNo active knowledge shard.\\n"
    if not validation_errors:
        return (
            "# Current Phase Feedback\\n\\n"
            "Current work ledger validates cleanly.\\n"
            f"Install target: `{{phase_row.get('result_path') or '<missing>'}}`\\n"
        )
    unresolved = []
    if isinstance(validation_metadata, dict):
        unresolved = [
            int(value)
            for value in (validation_metadata.get("unresolved_block_indices") or [])
            if str(value).strip()
        ]
    lines = [
        "# Current Phase Feedback",
        "",
        "Current work ledger is still unresolved.",
        "Validation errors:",
    ]
    lines.extend(f"- `{{error}}`" for error in validation_errors if str(error).strip())
    if phase_row.get("repair_path"):
        lines.append(f"Repair request: `{{phase_row.get('repair_path')}}`")
    if unresolved:
        lines.append(
            "Unresolved block indices: "
            f"`{{', '.join(str(value) for value in unresolved)}}`"
        )
    accepted = []
    if isinstance(validation_metadata, dict):
        accepted = [
            int(value)
            for value in (
                validation_metadata.get("frozen_block_indices")
                or validation_metadata.get("accepted_block_indices")
                or []
            )
            if str(value).strip()
        ]
    if accepted:
        lines.append(
            "Frozen accepted block indices: "
            f"`{{', '.join(str(value) for value in accepted)}}`"
        )
    return "\\n".join(lines) + "\\n"


def write_phase_surface(
    phase_row,
    *,
    validation_errors=(),
    validation_metadata=None,
    completed=False,
    frozen_rows=None,
):
    phase_payload = dict(phase_row or {{}})
    if completed:
        phase_payload = {{
            "status": "completed",
            "phase": None,
            "shard_id": None,
        }}
    elif frozen_rows:
        phase_payload["frozen_rows"] = [
            dict(row)
            for row in frozen_rows
            if isinstance(row, dict) and row.get("block_index") is not None
        ]
    else:
        phase_payload.pop("frozen_rows", None)
    save_json(workspace_root() / "current_phase.json", phase_payload)
    save_text(workspace_root() / "CURRENT_PHASE.md", render_phase_brief(phase_payload))
    save_text(
        workspace_root() / "CURRENT_PHASE_FEEDBACK.md",
        render_phase_feedback(
            phase_payload,
            validation_errors=validation_errors,
            validation_metadata=validation_metadata,
            completed=completed,
        ),
    )


def ensure_pass1_work(phase_row):
    work_path = workspace_root() / str(phase_row.get("work_path") or "")
    if work_path.exists():
        try:
            existing_payload = load_json(work_path)
        except Exception:
            existing_payload = None
        if (
            isinstance(existing_payload, dict)
            and str(existing_payload.get("phase") or "").strip() == "pass1"
            and isinstance(existing_payload.get("rows"), list)
        ):
            return
        migrated = migrate_legacy_pass1_work(load_phase_input(phase_row), existing_payload)
        if migrated is not None:
            save_json(work_path, migrated)
            return
        return
    save_json(work_path, build_pass1_seed(load_phase_input(phase_row)))


def build_final_output(phase_row, pass1_payload, pass2_payload):
    shard_id = str(phase_row.get("shard_id") or "")
    decisions = [
        {{
            "block_index": int(row.get("block_index")),
            "category": str(row.get("category") or "").strip(),
            "reviewer_category": (
                "knowledge"
                if str(row.get("category") or "").strip() == "knowledge"
                else "other"
            ),
        }}
        for row in (pass1_payload.get("rows") or [])
        if isinstance(row, dict) and row.get("block_index") is not None
    ]
    groups_by_id = {{}}
    for row in (pass2_payload.get("rows") or []):
        if not isinstance(row, dict) or row.get("block_index") is None:
            continue
        group_id = str(row.get("group_id") or "").strip()
        topic_label = str(row.get("topic_label") or "").strip()
        if not group_id or not topic_label:
            continue
        group = groups_by_id.setdefault(
            group_id,
            {{"group_id": group_id, "topic_label": topic_label, "block_indices": []}},
        )
        group["block_indices"].append(int(row.get("block_index")))
    return {{
        "packet_id": shard_id,
        "block_decisions": decisions,
        "idea_groups": list(groups_by_id.values()),
    }}


def next_phase_row(current_phase_row):
    shard_rows = assigned_shards()
    shard_ids = [str(row.get("shard_id") or "").strip() for row in shard_rows]
    current_shard_id = str(current_phase_row.get("shard_id") or "").strip()
    if current_shard_id not in shard_ids:
        return {{"status": "completed", "phase": None, "shard_id": None}}
    current_index = shard_ids.index(current_shard_id)
    for next_row in shard_rows[current_index + 1 :]:
        shard_id = str(next_row.get("shard_id") or "").strip()
        if not shard_id:
            continue
        result_path = workspace_root() / "out" / f"{{shard_id}}.json"
        if result_path.exists():
            continue
        return {{
            "status": "active",
            "phase": "pass1",
            "shard_id": shard_id,
            "input_path": f"in/{{shard_id}}.json",
            "work_path": f"work/{{shard_id}}.pass1.json",
            "repair_path": f"repair/{{shard_id}}.pass1.json",
            "result_path": f"out/{{shard_id}}.json",
            "hint_path": f"hints/{{shard_id}}.md",
        }}
    return {{"status": "completed", "phase": None, "shard_id": None}}


def scaffold_current_phase():
    phase_row = current_phase()
    if not isinstance(phase_row, dict):
        raise SystemExit("current_phase.json is missing")
    if str(phase_row.get("status") or "").strip() == "completed":
        print("all assigned knowledge shards are installed")
        return 0
    if str(phase_row.get("phase") or "").strip() == "pass1":
        ensure_pass1_work(phase_row)
    else:
        work_path = workspace_root() / str(phase_row.get("work_path") or "")
        if not work_path.exists():
            save_json(work_path, build_pass2_seed(load_phase_input(phase_row)))
    print(str(phase_row.get("work_path") or ""))
    return 0


def check_current_phase():
    phase_row = current_phase()
    if not isinstance(phase_row, dict):
        raise SystemExit("current_phase.json is missing")
    if str(phase_row.get("status") or "").strip() == "completed":
        write_phase_surface(phase_row, completed=True)
        print("all assigned knowledge shards are installed")
        return 0
    if str(phase_row.get("phase") or "").strip() == "pass1":
        ensure_pass1_work(phase_row)
    work_payload = load_phase_work(phase_row)
    input_payload = load_phase_input(phase_row)
    frozen_rows = phase_row.get("frozen_rows")
    if str(phase_row.get("phase") or "").strip() == "pass1":
        errors, metadata = validate_pass1(
            input_payload,
            work_payload,
            frozen_rows_by_block_index=frozen_rows,
        )
    else:
        errors, metadata = validate_pass2(
            input_payload,
            work_payload,
            frozen_rows_by_block_index=frozen_rows,
        )
    merged_frozen_rows = merge_frozen_rows(
        frozen_rows,
        [
            dict(row)
            for row in (metadata.get("accepted_rows") or [])
            if isinstance(row, dict)
        ],
    )
    metadata = dict(metadata)
    metadata["frozen_block_indices"] = [
        int(row.get("block_index"))
        for row in merged_frozen_rows
        if row.get("block_index") is not None
    ]
    repair_path = workspace_root() / str(phase_row.get("repair_path") or "")
    if errors:
        if str(phase_row.get("phase") or "").strip() == "pass1":
            repair_payload = build_pass1_repair_payload(
                input_payload,
                metadata,
                errors,
                frozen_rows=frozen_rows,
            )
        else:
            repair_payload = build_pass2_repair_payload(
                input_payload,
                metadata,
                errors,
                frozen_rows=frozen_rows,
            )
        save_json(repair_path, repair_payload)
        write_phase_surface(
            phase_row,
            validation_errors=errors,
            validation_metadata=metadata,
            frozen_rows=merged_frozen_rows,
        )
        print("\\n".join(errors))
        return 1
    if repair_path.exists():
        repair_path.unlink()
    write_phase_surface(
        phase_row,
        validation_metadata=metadata,
        frozen_rows=merged_frozen_rows,
    )
    print("ok")
    return 0


def install_current_phase():
    phase_row = current_phase()
    if not isinstance(phase_row, dict):
        raise SystemExit("current_phase.json is missing")
    if check_current_phase() != 0:
        raise SystemExit("knowledge phase failed validation")
    phase_row = current_phase()
    work_payload = load_phase_work(phase_row)
    frozen_rows = phase_row.get("frozen_rows")
    if str(phase_row.get("phase") or "").strip() == "pass1":
        input_payload = load_phase_input(phase_row)
        errors, metadata = validate_pass1(
            input_payload,
            work_payload,
            frozen_rows_by_block_index=frozen_rows,
        )
        if errors:
            raise SystemExit("knowledge phase failed validation")
        pass2_input = build_pass2_input(input_payload, work_payload)
        pass2_input_path = workspace_root() / "in" / f"{{phase_row['shard_id']}}.pass2.json"
        save_json(pass2_input_path, pass2_input)
        next_row = dict(phase_row)
        next_row.pop("frozen_rows", None)
        next_row["phase"] = "pass2"
        next_row["input_path"] = relative_path(pass2_input_path)
        next_row["work_path"] = f"work/{{phase_row['shard_id']}}.pass2.json"
        next_row["repair_path"] = f"repair/{{phase_row['shard_id']}}.pass2.json"
        save_json(workspace_root() / next_row["work_path"], build_pass2_seed(pass2_input))
        write_phase_surface(next_row)
        print("advanced to pass2")
        return 0
    pass1_path = workspace_root() / "work" / f"{{phase_row['shard_id']}}.pass1.json"
    pass1_payload = load_json(pass1_path)
    errors, metadata = validate_pass2(
        load_phase_input(phase_row),
        work_payload,
        frozen_rows_by_block_index=frozen_rows,
    )
    if errors:
        raise SystemExit("knowledge phase failed validation")
    final_payload = build_final_output(phase_row, pass1_payload, work_payload)
    save_json(workspace_root() / str(phase_row.get("result_path") or ""), final_payload)
    next_row = next_phase_row(phase_row)
    if str(next_row.get("status") or "").strip() == "completed":
        write_phase_surface(next_row, completed=True)
        print("queue complete")
        return 0
    next_row.pop("frozen_rows", None)
    ensure_pass1_work(next_row)
    write_phase_surface(next_row)
    print(f"advanced to {{next_row['shard_id']}} pass1")
    return 0


def write_static_artifacts():
    save_text(workspace_root() / "OUTPUT_CONTRACT.md", OUTPUT_CONTRACT_MARKDOWN)
    examples_dir = workspace_root() / "examples"
    save_text(examples_dir / "valid_knowledge_output.json", VALID_EXAMPLE_JSON)
    return 0


def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("scaffold-phase")
    subparsers.add_parser("check-phase")
    subparsers.add_parser("install-phase")
    subparsers.add_parser("write-static")
    return parser


def main():
    args = build_parser().parse_args()
    if args.command == "scaffold-phase":
        return scaffold_current_phase()
    if args.command == "check-phase":
        return check_current_phase()
    if args.command == "install-phase":
        return install_current_phase()
    if args.command == "write-static":
        return write_static_artifacts()
    raise SystemExit(f"unknown command: {{args.command}}")


if __name__ == "__main__":
    raise SystemExit(main())
"""
    return (
        script.replace("__OUTPUT_CONTRACT_MARKDOWN__", output_contract_markdown)
        .replace("__VALID_EXAMPLE_JSON__", valid_example_json)
        .replace("{{", "{")
        .replace("}}", "}")
    )


def write_knowledge_worker_examples(*, worker_root: Path) -> None:
    examples_dir = worker_root / "examples"
    _save_text(
        examples_dir / KNOWLEDGE_VALID_OUTPUT_EXAMPLE_FILENAME,
        json.dumps(KNOWLEDGE_VALID_OUTPUT_EXAMPLE_PAYLOAD, indent=2, sort_keys=True) + "\n",
    )


def write_knowledge_output_contract(*, worker_root: Path) -> None:
    _save_text(worker_root / "OUTPUT_CONTRACT.md", KNOWLEDGE_OUTPUT_CONTRACT_MARKDOWN)


def write_knowledge_worker_tools(*, worker_root: Path) -> None:
    tools_dir = worker_root / "tools"
    tool_path = tools_dir / KNOWLEDGE_WORKER_TOOL_FILENAME
    _save_text(tool_path, render_knowledge_worker_script())
    tool_path.chmod(0o755)
