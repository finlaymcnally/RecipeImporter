from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence


KNOWLEDGE_VALID_PASS1_RESULT_EXAMPLE_FILENAME = "valid_pass1_packet_result.json"
KNOWLEDGE_VALID_PASS2_RESULT_EXAMPLE_FILENAME = "valid_pass2_packet_result.json"
KNOWLEDGE_OUTPUT_CONTRACT_FILENAME = "OUTPUT_CONTRACT.md"

KNOWLEDGE_VALID_PASS1_RESULT_EXAMPLE_PAYLOAD = {
    "v": "1",
    "task_id": "book.ks0000.nr.pass1",
    "packet_kind": "pass1",
    "shard_id": "book.ks0000.nr",
    "rows": [
        {"block_index": 10, "category": "knowledge"},
        {"block_index": 11, "category": "other"},
    ],
}

KNOWLEDGE_VALID_PASS2_RESULT_EXAMPLE_PAYLOAD = {
    "v": "1",
    "task_id": "book.ks0000.nr.pass2",
    "packet_kind": "pass2",
    "shard_id": "book.ks0000.nr",
    "rows": [
        {
            "block_index": 10,
            "group_key": "heat-control",
            "topic_label": "Heat control",
        }
    ],
}

KNOWLEDGE_PACKET_OUTPUT_CONTRACT_MARKDOWN = """# Knowledge Packet Result Contract

The live knowledge worker no longer edits repo-owned work ledgers or runs helper install loops.
The happy path is one leased packet at a time:

1. Open `current_packet.json`
2. Open `current_hint.md`
3. Read `current_result_path.txt`
4. Write exactly one JSON object to that result path
5. Re-open the current-packet files after the repo advances the lease

Pass 1 result shape:

    {"v":"1","task_id":"book.ks0000.nr.pass1","packet_kind":"pass1","shard_id":"book.ks0000.nr","rows":[{"block_index":10,"category":"knowledge"}]}

Pass 2 result shape:

    {"v":"1","task_id":"book.ks0000.nr.pass2","packet_kind":"pass2","shard_id":"book.ks0000.nr","rows":[{"block_index":10,"group_key":"heat-control","topic_label":"Heat control"}]}

Rules:

- The file must be one JSON object.
- `task_id`, `packet_kind`, and `shard_id` must echo the current packet exactly.
- Pass 1 rows must cover every required row exactly once and keep the same row order as `current_packet.json`.
- Pass 1 `category` must be `knowledge` or `other`.
- Pass 2 rows must cover every required row exactly once and keep the same row order as `current_packet.json`.
- Pass 2 `group_key` and `topic_label` must both be non-empty strings.
- Repair packets name only the unresolved rows. Do not resend already accepted rows unless the packet explicitly asks for them.
- Return JSON only. Do not add markdown, prose, or wrapper keys.
"""


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text), encoding="utf-8")


def _input_blocks(input_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(block)
        for block in (input_payload.get("b") or [])
        if isinstance(block, Mapping)
    ]


def _packet_rows(packet_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in (packet_payload.get("rows") or [])
        if isinstance(row, Mapping)
    ]


def _required_block_indices(packet_payload: Mapping[str, Any]) -> list[int]:
    required = []
    for row in _packet_rows(packet_payload):
        block_index = row.get("block_index")
        if block_index is None:
            continue
        required.append(int(block_index))
    return required


def _packet_repair_metadata(packet_payload: Mapping[str, Any]) -> dict[str, Any]:
    return _coerce_dict(packet_payload.get("repair"))


def _packet_context(packet_payload: Mapping[str, Any]) -> dict[str, Any]:
    return _coerce_dict(packet_payload.get("context"))


def build_knowledge_workspace_shard_metadata(
    *,
    shard_id: str,
    input_payload: Mapping[str, Any] | None,
    input_path: str,
    hint_path: str,
    result_path: str,
) -> dict[str, Any]:
    blocks = _input_blocks(_coerce_dict(input_payload))
    block_indices = [
        int(block.get("i"))
        for block in blocks
        if block.get("i") is not None
    ]
    return {
        "workspace_processing_contract": "knowledge_packet_lease_v1",
        "shard_id": str(shard_id),
        "input_path": str(input_path),
        "hint_path": str(hint_path),
        "result_path": str(result_path),
        "owned_row_count": len(block_indices),
        "owned_block_indices": block_indices,
        "block_index_start": block_indices[0] if block_indices else None,
        "block_index_end": block_indices[-1] if block_indices else None,
    }


def build_pass1_packet(
    *,
    shard_id: str,
    task_id: str,
    input_payload: Mapping[str, Any],
    repair: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for block in _input_blocks(input_payload):
        block_index = block.get("i")
        if block_index is None:
            continue
        row = {
            "block_index": int(block_index),
            "text": str(block.get("t") or "").strip(),
        }
        if block.get("hl") is not None:
            row["heading_level"] = int(block.get("hl"))
        if isinstance(block.get("th"), Mapping):
            row["table_hint"] = dict(block["th"])
        rows.append(row)
    payload: dict[str, Any] = {
        "v": "1",
        "task_id": str(task_id),
        "packet_kind": "pass1",
        "shard_id": str(shard_id),
        "rows": rows,
    }
    context_payload = {
        key: value
        for key, value in (
            ("guardrails", _coerce_dict(input_payload.get("g"))),
            ("context", _coerce_dict(input_payload.get("x"))),
        )
        if value
    }
    if context_payload:
        payload["context"] = context_payload
    repair_payload = _coerce_dict(repair)
    if repair_payload:
        payload["repair"] = repair_payload
    return payload


def build_pass2_packet(
    *,
    shard_id: str,
    task_id: str,
    input_payload: Mapping[str, Any],
    pass1_rows: Sequence[Mapping[str, Any]],
    repair: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    kept_by_index = {
        int(row.get("block_index")): dict(row)
        for row in pass1_rows
        if isinstance(row, Mapping)
        and row.get("block_index") is not None
        and str(row.get("category") or "").strip() == "knowledge"
    }
    rows: list[dict[str, Any]] = []
    for block in _input_blocks(input_payload):
        block_index = block.get("i")
        if block_index is None:
            continue
        normalized_index = int(block_index)
        if normalized_index not in kept_by_index:
            continue
        row = {
            "block_index": normalized_index,
            "text": str(block.get("t") or "").strip(),
        }
        if block.get("hl") is not None:
            row["heading_level"] = int(block.get("hl"))
        if isinstance(block.get("th"), Mapping):
            row["table_hint"] = dict(block["th"])
        rows.append(row)
    payload: dict[str, Any] = {
        "v": "1",
        "task_id": str(task_id),
        "packet_kind": "pass2",
        "shard_id": str(shard_id),
        "rows": rows,
    }
    repair_payload = _coerce_dict(repair)
    if repair_payload:
        payload["repair"] = repair_payload
    return payload


def validate_pass1_packet_result(
    *,
    packet_payload: Mapping[str, Any],
    result_payload: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any]]:
    packet = _coerce_dict(packet_payload)
    payload = _coerce_dict(result_payload)
    errors: list[str] = []
    metadata: dict[str, Any] = {
        "packet_kind": "pass1",
        "task_id": str(packet.get("task_id") or "").strip() or None,
        "shard_id": str(packet.get("shard_id") or "").strip() or None,
    }
    if str(payload.get("task_id") or "").strip() != str(packet.get("task_id") or "").strip():
        errors.append("packet_task_id_mismatch")
    if str(payload.get("packet_kind") or "").strip() != "pass1":
        errors.append("packet_kind_mismatch")
    if str(payload.get("shard_id") or "").strip() != str(packet.get("shard_id") or "").strip():
        errors.append("packet_shard_id_mismatch")

    rows = payload.get("rows")
    if not isinstance(rows, list):
        return None, tuple(errors or ["schema_invalid"]), metadata

    required_indices = _required_block_indices(packet)
    result_rows: list[dict[str, Any]] = []
    result_indices: list[int] = []
    unexpected_indices: list[int] = []
    invalid_category_indices: list[int] = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("block_index") is None:
            errors.append("schema_invalid")
            continue
        block_index = int(row.get("block_index"))
        category = str(row.get("category") or "").strip()
        if category not in {"knowledge", "other"}:
            invalid_category_indices.append(block_index)
        result_rows.append({"block_index": block_index, "category": category})
        result_indices.append(block_index)
        if block_index not in required_indices:
            unexpected_indices.append(block_index)
    if invalid_category_indices:
        errors.append("schema_invalid")
        metadata["invalid_category_block_indices"] = sorted(set(invalid_category_indices))
    if unexpected_indices:
        errors.append("unexpected_block_decisions")
        metadata["unexpected_block_indices"] = sorted(set(unexpected_indices))
    if result_indices != required_indices:
        missing_indices = [
            block_index for block_index in required_indices if block_index not in result_indices
        ]
        if missing_indices:
            errors.append("missing_owned_block_decisions")
            metadata["missing_owned_block_indices"] = missing_indices
        ordered_required = [
            block_index for block_index in result_indices if block_index in required_indices
        ]
        if not missing_indices and ordered_required != required_indices:
            errors.append("block_decision_order_mismatch")
            metadata["expected_block_indices"] = required_indices
            metadata["returned_block_indices"] = result_indices
    if errors:
        metadata["unresolved_block_indices"] = metadata.get(
            "missing_owned_block_indices",
            required_indices,
        )
        return None, tuple(dict.fromkeys(errors)), metadata
    metadata["accepted_block_indices"] = required_indices
    return {
        "task_id": str(packet.get("task_id")),
        "packet_kind": "pass1",
        "shard_id": str(packet.get("shard_id")),
        "rows": result_rows,
    }, (), metadata


def validate_pass2_packet_result(
    *,
    packet_payload: Mapping[str, Any],
    result_payload: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any]]:
    packet = _coerce_dict(packet_payload)
    payload = _coerce_dict(result_payload)
    errors: list[str] = []
    metadata: dict[str, Any] = {
        "packet_kind": "pass2",
        "task_id": str(packet.get("task_id") or "").strip() or None,
        "shard_id": str(packet.get("shard_id") or "").strip() or None,
    }
    if str(payload.get("task_id") or "").strip() != str(packet.get("task_id") or "").strip():
        errors.append("packet_task_id_mismatch")
    if str(payload.get("packet_kind") or "").strip() != "pass2":
        errors.append("packet_kind_mismatch")
    if str(payload.get("shard_id") or "").strip() != str(packet.get("shard_id") or "").strip():
        errors.append("packet_shard_id_mismatch")

    rows = payload.get("rows")
    if not isinstance(rows, list):
        return None, tuple(errors or ["schema_invalid"]), metadata

    required_indices = _required_block_indices(packet)
    result_rows: list[dict[str, Any]] = []
    result_indices: list[int] = []
    missing_group_indices: list[int] = []
    unexpected_indices: list[int] = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("block_index") is None:
            errors.append("schema_invalid")
            continue
        block_index = int(row.get("block_index"))
        group_key = str(row.get("group_key") or "").strip()
        topic_label = str(row.get("topic_label") or "").strip()
        if not group_key or not topic_label:
            missing_group_indices.append(block_index)
        result_rows.append(
            {
                "block_index": block_index,
                "group_key": group_key,
                "topic_label": topic_label,
            }
        )
        result_indices.append(block_index)
        if block_index not in required_indices:
            unexpected_indices.append(block_index)
    if missing_group_indices:
        errors.append("knowledge_block_missing_group")
        metadata["knowledge_blocks_missing_group"] = sorted(set(missing_group_indices))
    if unexpected_indices:
        errors.append("unexpected_block_decisions")
        metadata["unexpected_block_indices"] = sorted(set(unexpected_indices))
    if result_indices != required_indices:
        missing_indices = [
            block_index for block_index in required_indices if block_index not in result_indices
        ]
        if missing_indices:
            errors.append("missing_owned_block_decisions")
            metadata["missing_owned_block_indices"] = missing_indices
        ordered_required = [
            block_index for block_index in result_indices if block_index in required_indices
        ]
        if not missing_indices and ordered_required != required_indices:
            errors.append("block_decision_order_mismatch")
            metadata["expected_block_indices"] = required_indices
            metadata["returned_block_indices"] = result_indices
    if errors:
        metadata["unresolved_block_indices"] = metadata.get(
            "missing_owned_block_indices",
            required_indices,
        )
        return None, tuple(dict.fromkeys(errors)), metadata
    metadata["accepted_block_indices"] = required_indices
    return {
        "task_id": str(packet.get("task_id")),
        "packet_kind": "pass2",
        "shard_id": str(packet.get("shard_id")),
        "rows": result_rows,
    }, (), metadata


def build_pass1_repair_packet(
    *,
    packet_payload: Mapping[str, Any],
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
    accepted_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    packet = _coerce_dict(packet_payload)
    metadata = _coerce_dict(validation_metadata)
    unresolved = {
        int(value)
        for value in (metadata.get("unresolved_block_indices") or metadata.get("missing_owned_block_indices") or _required_block_indices(packet))
        if value is not None
    }
    rows = [
        dict(row)
        for row in _packet_rows(packet)
        if row.get("block_index") is not None
        and int(row.get("block_index")) in unresolved
    ]
    return build_pass1_packet(
        shard_id=str(packet.get("shard_id") or ""),
        task_id=str(packet.get("task_id") or "") + ".repair",
        input_payload={"b": [{"i": row["block_index"], "t": row.get("text") or ""} for row in rows]},
        repair={
            "validation_errors": [
                str(error).strip() for error in validation_errors if str(error).strip()
            ],
            "required_block_indices": [int(row["block_index"]) for row in rows],
            "accepted_rows": [
                {
                    "block_index": int(row.get("block_index")),
                    "category": str(row.get("category") or "").strip(),
                }
                for row in accepted_rows
                if isinstance(row, Mapping) and row.get("block_index") is not None
            ],
        },
    )


def build_pass2_repair_packet(
    *,
    packet_payload: Mapping[str, Any],
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
    accepted_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    packet = _coerce_dict(packet_payload)
    metadata = _coerce_dict(validation_metadata)
    unresolved = {
        int(value)
        for value in (metadata.get("unresolved_block_indices") or metadata.get("missing_owned_block_indices") or _required_block_indices(packet))
        if value is not None
    }
    rows = [
        dict(row)
        for row in _packet_rows(packet)
        if row.get("block_index") is not None
        and int(row.get("block_index")) in unresolved
    ]
    return {
        "v": "1",
        "task_id": str(packet.get("task_id") or "") + ".repair",
        "packet_kind": "pass2",
        "shard_id": str(packet.get("shard_id") or ""),
        "rows": rows,
        "repair": {
            "validation_errors": [
                str(error).strip() for error in validation_errors if str(error).strip()
            ],
            "required_block_indices": [int(row["block_index"]) for row in rows],
            "accepted_rows": [
                {
                    "block_index": int(row.get("block_index")),
                    "group_key": str(row.get("group_key") or "").strip(),
                    "topic_label": str(row.get("topic_label") or "").strip(),
                }
                for row in accepted_rows
                if isinstance(row, Mapping) and row.get("block_index") is not None
            ],
        },
    }


def assemble_final_output(
    *,
    shard_id: str,
    pass1_result: Mapping[str, Any],
    pass2_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    pass1_rows = [
        dict(row)
        for row in (_coerce_dict(pass1_result).get("rows") or [])
        if isinstance(row, Mapping) and row.get("block_index") is not None
    ]
    pass2_rows = [
        dict(row)
        for row in (_coerce_dict(pass2_result).get("rows") or [])
        if isinstance(row, Mapping) and row.get("block_index") is not None
    ]
    pass2_by_block_index = {
        int(row["block_index"]): row for row in pass2_rows
    }
    block_decisions: list[dict[str, Any]] = []
    groups_by_key: dict[tuple[str, str], list[int]] = {}
    group_order: list[tuple[str, str]] = []
    for row in pass1_rows:
        block_index = int(row["block_index"])
        category = str(row.get("category") or "").strip()
        reviewer_category = "knowledge" if category == "knowledge" else "other"
        block_decisions.append(
            {
                "block_index": block_index,
                "category": category,
                "reviewer_category": reviewer_category,
            }
        )
        if category != "knowledge":
            continue
        group_row = pass2_by_block_index.get(block_index) or {}
        key = (
            str(group_row.get("group_key") or "").strip(),
            str(group_row.get("topic_label") or "").strip(),
        )
        if not key[0] or not key[1]:
            continue
        if key not in groups_by_key:
            groups_by_key[key] = []
            group_order.append(key)
        groups_by_key[key].append(block_index)
    idea_groups: list[dict[str, Any]] = []
    for position, key in enumerate(group_order, start=1):
        group_key, topic_label = key
        idea_groups.append(
            {
                "group_id": f"g{position:02d}",
                "topic_label": topic_label,
                "block_indices": groups_by_key[key],
            }
        )
    return {
        "packet_id": str(shard_id),
        "block_decisions": block_decisions,
        "idea_groups": idea_groups,
    }


def render_knowledge_packet_hint(
    *,
    packet_payload: Mapping[str, Any],
    shard_hint_text: str | None = None,
    result_path: str,
) -> str:
    packet = _coerce_dict(packet_payload)
    packet_kind = str(packet.get("packet_kind") or "").strip()
    rows = _packet_rows(packet)
    header_lines = [
        "# Current Knowledge Packet",
        "",
        f"Packet kind: `{packet_kind or '[unknown]'}`",
        f"Task id: `{packet.get('task_id') or '[unknown]'}`",
        f"Shard id: `{packet.get('shard_id') or '[unknown]'}`",
        f"Result path: `{result_path}`",
        f"Required row count: `{len(rows)}`",
        "",
        "Happy path:",
        "1. Open `current_packet.json`.",
        "2. Read only the required rows for this leased packet.",
        "3. Write exactly one JSON object to the result path named above.",
        "4. Re-open `current_packet.json`, `current_hint.md`, and `current_result_path.txt` after the repo advances the lease.",
    ]
    repair_payload = _packet_repair_metadata(packet)
    if repair_payload:
        header_lines.extend(
            [
                "",
                "Repair rules:",
                "- This is a structural repair packet only.",
                "- Fix only the required rows named in this packet.",
                "- Do not resend already accepted rows unless the packet explicitly asks for them.",
                (
                    "Validator errors: `"
                    + ", ".join(
                        str(error)
                        for error in (repair_payload.get("validation_errors") or [])
                        if str(error).strip()
                    )
                    + "`"
                ),
            ]
        )
    if shard_hint_text and str(shard_hint_text).strip():
        return "\n".join(header_lines) + "\n\n---\n\n" + str(shard_hint_text).strip() + "\n"
    return "\n".join(header_lines) + "\n"


def write_knowledge_output_contract(worker_root: Path) -> None:
    _write_text(
        worker_root / KNOWLEDGE_OUTPUT_CONTRACT_FILENAME,
        KNOWLEDGE_PACKET_OUTPUT_CONTRACT_MARKDOWN,
    )


def write_knowledge_worker_examples(worker_root: Path) -> None:
    examples_dir = worker_root / "examples"
    _write_json(
        examples_dir / KNOWLEDGE_VALID_PASS1_RESULT_EXAMPLE_FILENAME,
        KNOWLEDGE_VALID_PASS1_RESULT_EXAMPLE_PAYLOAD,
    )
    _write_json(
        examples_dir / KNOWLEDGE_VALID_PASS2_RESULT_EXAMPLE_FILENAME,
        KNOWLEDGE_VALID_PASS2_RESULT_EXAMPLE_PAYLOAD,
    )


def build_pass1_work_ledger(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for block in _input_blocks(input_payload):
        block_index = block.get("i")
        if block_index is None:
            continue
        rows.append(
            {
                "block_index": int(block_index),
                "text": str(block.get("t") or "").strip(),
                "category": "",
            }
        )
    return {"phase": "pass1", "rows": rows}


def build_pass2_input_ledger(
    *,
    input_payload: Mapping[str, Any],
    pass1_payload: Mapping[str, Any],
) -> dict[str, Any]:
    kept_indices = {
        int(row.get("block_index"))
        for row in _packet_rows(pass1_payload)
        if row.get("block_index") is not None
        and str(row.get("category") or "").strip() == "knowledge"
    }
    rows: list[dict[str, Any]] = []
    for block in _input_blocks(input_payload):
        block_index = block.get("i")
        if block_index is None:
            continue
        normalized_index = int(block_index)
        if normalized_index not in kept_indices:
            continue
        rows.append(
            {
                "block_index": normalized_index,
                "category": "knowledge",
                "text": str(block.get("t") or "").strip(),
            }
        )
    return {"phase": "pass2", "rows": rows}


def build_pass2_work_ledger(pass2_input_payload: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row in _packet_rows(pass2_input_payload):
        if row.get("block_index") is None:
            continue
        rows.append(
            {
                "block_index": int(row.get("block_index")),
                "category": str(row.get("category") or "knowledge").strip() or "knowledge",
                "text": str(row.get("text") or "").strip(),
                "group_key": "",
                "topic_label": "",
            }
        )
    return {"phase": "pass2", "rows": rows}


def validate_pass1_work_ledger(
    *,
    input_payload: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> tuple[tuple[str, ...], dict[str, Any]]:
    packet_payload = build_pass1_packet(
        shard_id=str(input_payload.get("bid") or input_payload.get("packet_id") or ""),
        task_id=str(input_payload.get("bid") or input_payload.get("packet_id") or "") + ".pass1",
        input_payload=input_payload,
    )
    normalized_payload = {
        "task_id": packet_payload["task_id"],
        "packet_kind": "pass1",
        "shard_id": packet_payload["shard_id"],
        "rows": [
            {
                "block_index": int(row.get("block_index")),
                "category": str(row.get("category") or "").strip(),
            }
            for row in _packet_rows(payload)
            if row.get("block_index") is not None
        ],
    }
    _result, errors, metadata = validate_pass1_packet_result(
        packet_payload=packet_payload,
        result_payload=normalized_payload,
    )
    return errors, metadata


def validate_pass2_work_ledger(
    *,
    pass2_input_payload: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> tuple[tuple[str, ...], dict[str, Any]]:
    packet_payload = {
        "task_id": str(pass2_input_payload.get("task_id") or "") or "pass2",
        "packet_kind": "pass2",
        "shard_id": str(pass2_input_payload.get("shard_id") or "") or "packet",
        "rows": [
            {
                "block_index": int(row.get("block_index")),
                "text": str(row.get("text") or "").strip(),
            }
            for row in _packet_rows(pass2_input_payload)
            if row.get("block_index") is not None
        ],
    }
    normalized_payload = {
        "task_id": packet_payload["task_id"],
        "packet_kind": "pass2",
        "shard_id": packet_payload["shard_id"],
        "rows": [
            {
                "block_index": int(row.get("block_index")),
                "group_key": str(row.get("group_key") or row.get("group_id") or "").strip(),
                "topic_label": str(row.get("topic_label") or "").strip(),
            }
            for row in _packet_rows(payload)
            if row.get("block_index") is not None
        ],
    }
    _result, errors, metadata = validate_pass2_packet_result(
        packet_payload=packet_payload,
        result_payload=normalized_payload,
    )
    return errors, metadata


def build_final_output(
    *,
    shard_id: str,
    pass1_payload: Mapping[str, Any],
    pass2_payload: Mapping[str, Any],
) -> dict[str, Any]:
    return assemble_final_output(
        shard_id=shard_id,
        pass1_result=pass1_payload,
        pass2_result=pass2_payload,
    )


def render_knowledge_current_phase_brief(phase_row: Mapping[str, Any]) -> str:
    phase = str(phase_row.get("phase") or "pass1").strip() or "pass1"
    work_path = str(phase_row.get("work_path") or "work/current.json")
    hint_path = str(phase_row.get("hint_path") or "hints/current.md")
    input_path = str(phase_row.get("input_path") or "in/current.json")
    return (
        "# Current Knowledge Phase\n\n"
        "This is a first-authority semantic judgment loop.\n"
        f"Phase: `{phase}`\n"
        f"Active work ledger: `{work_path}`\n\n"
        "Preferred loop\n"
        f"1. Open `{hint_path}` before `{input_path}`.\n"
        f"2. Open `{input_path}` only if the phase brief, feedback, hint, and work ledger are still insufficient.\n"
        f"3. Edit only `{work_path}`.\n"
        "4. The repo does not know the `knowledge` versus `other` answer ahead of time.\n"
        "5. Run `python3 tools/knowledge_worker.py check-phase`.\n"
    )


def render_knowledge_current_phase_feedback(
    *,
    phase_row: Mapping[str, Any],
    validation_errors: Sequence[str] = (),
    validation_metadata: Mapping[str, Any] | None = None,
    completed: bool = False,
) -> str:
    if completed:
        return "# Current Knowledge Phase Feedback\n\nAll assigned knowledge shards are installed.\n"
    work_path = str(phase_row.get("work_path") or "work/current.json")
    repair_path = str(phase_row.get("repair_path") or "repair/current.json")
    lines = [
        "# Current Knowledge Phase Feedback",
        "",
        f"Edit only `{work_path}`.",
    ]
    if validation_errors:
        lines.append("Current work ledger is still unresolved.")
        lines.append(f"Repair request: `{repair_path}`")
        lines.append("Next command after fixes: `python3 tools/knowledge_worker.py check-phase`.")
    else:
        lines.append("Next command: `python3 tools/knowledge_worker.py install-phase`.")
        lines.append("Install target: write the validated result and advance the phase.")
    return "\n".join(lines) + "\n"


def render_knowledge_worker_script() -> str:
    return """#!/usr/bin/env python3
\"\"\"Minimal knowledge worker helper surface.\"\"\"

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    phase_path = Path(\"current_phase.json\")
    if phase_path.exists():
        payload = json.loads(phase_path.read_text(encoding=\"utf-8\"))
        if str(payload.get(\"status\") or \"\").strip() == \"completed\":
            print(\"queue complete\")
            return 0
    print(\"Use CURRENT_PHASE.md, CURRENT_PHASE_FEEDBACK.md, and current_phase.json.\")
    print(\"Run check-phase before install-phase.\")
    print(\"Final outputs still install into packet_id/block_decisions/idea_groups JSON.\")
    return 0


if __name__ == \"__main__\":
    raise SystemExit(main())
"""


def write_knowledge_worker_tools(worker_root: Path) -> None:
    tool_path = worker_root / "tools" / "knowledge_worker.py"
    _write_text(tool_path, render_knowledge_worker_script())
    tool_path.chmod(0o755)
