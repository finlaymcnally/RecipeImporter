from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from ..codex_farm_knowledge_models import (
    ALLOWED_KNOWLEDGE_FINAL_CATEGORIES,
    ALLOWED_KNOWLEDGE_REVIEWER_CATEGORIES,
)
from ..editable_task_file import build_task_file, validate_edited_task_file
from ..phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1

KNOWLEDGE_CLASSIFY_STAGE_KEY = "nonrecipe_classify"
KNOWLEDGE_GROUP_STAGE_KEY = "knowledge_group"
KNOWLEDGE_CLASSIFY_SCHEMA_VERSION = "knowledge_block_classify.v1"
KNOWLEDGE_GROUP_SCHEMA_VERSION = "knowledge_group_only.v1"


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _knowledge_packet_payloads(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    data = _coerce_dict(payload)
    packets = data.get("p")
    if isinstance(packets, list):
        return [dict(packet) for packet in packets if isinstance(packet, Mapping)]
    blocks = data.get("b")
    packet_id = str(data.get("bid") or data.get("packet_id") or "").strip()
    if packet_id and isinstance(blocks, list):
        packet_payload = {
            "bid": packet_id,
            "b": [dict(block) for block in blocks if isinstance(block, Mapping)],
        }
        if isinstance(data.get("x"), Mapping):
            packet_payload["x"] = dict(data["x"])
        if isinstance(data.get("g"), Mapping):
            packet_payload["g"] = dict(data["g"])
        if data.get("v") is not None:
            packet_payload["v"] = data.get("v")
        return [packet_payload]
    return []


def _packet_context_text(packet: Mapping[str, Any], *, key: str, last: bool) -> str | None:
    packet_context = _coerce_dict(packet.get("x"))
    rows = list(packet_context.get(key) or [])
    if not rows:
        return None
    row = rows[-1] if last else rows[0]
    if not isinstance(row, Mapping):
        return None
    cleaned = str(row.get("t") or "").strip()
    return cleaned or None


def _classification_sort_key(owned_id: str, block_index: int) -> tuple[str, int]:
    digest = hashlib.sha1(owned_id.encode("utf-8")).hexdigest()
    return digest, int(block_index)


def build_knowledge_classification_task_file(
    *,
    assignment: WorkerAssignmentV1,
    shards: Sequence[ShardManifestEntryV1],
) -> tuple[dict[str, Any], dict[str, str]]:
    indexed_units: list[tuple[tuple[str, int], dict[str, Any]]] = []
    unit_to_shard_id: dict[str, str] = {}
    for shard in shards:
        for packet in _knowledge_packet_payloads(shard.input_payload):
            context_before = _packet_context_text(packet, key="p", last=True)
            context_after = _packet_context_text(packet, key="n", last=False)
            for block in packet.get("b") or []:
                if not isinstance(block, Mapping):
                    continue
                block_index = int(block.get("i") or 0)
                block_id = str(
                    block.get("id") or block.get("block_id") or f"{shard.shard_id}:{block_index}"
                ).strip()
                unit_id = f"knowledge::{block_index}"
                unit_to_shard_id[unit_id] = shard.shard_id
                unit_payload = {
                    "unit_id": unit_id,
                    "owned_id": block_id,
                    "evidence": {
                        "block_index": block_index,
                        "block_id": block_id,
                        "text": str(block.get("t") or ""),
                        "context_before": context_before,
                        "context_after": context_after,
                        "structure": {
                            "heading_level": (
                                int(block.get("hl"))
                                if block.get("hl") is not None
                                else None
                            ),
                            "table_hint": (
                                dict(block.get("th"))
                                if isinstance(block.get("th"), Mapping)
                                else None
                            ),
                        },
                        "routing_hints": [],
                    },
                    "answer": {},
                }
                indexed_units.append(
                    (_classification_sort_key(block_id, block_index), unit_payload)
                )
    units = [payload for _sort_key, payload in sorted(indexed_units, key=lambda row: row[0])]
    return (
        build_task_file(
            stage_key=KNOWLEDGE_CLASSIFY_STAGE_KEY,
            assignment_id=assignment.worker_id,
            worker_id=assignment.worker_id,
            units=units,
            schema_version=KNOWLEDGE_CLASSIFY_SCHEMA_VERSION,
        ),
        unit_to_shard_id,
    )


def validate_knowledge_classification_task_file(
    *,
    original_task_file: Mapping[str, Any],
    edited_task_file: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]] | None, tuple[str, ...], dict[str, Any]]:
    answers_by_unit_id, errors, metadata = validate_edited_task_file(
        original_task_file=original_task_file,
        edited_task_file=edited_task_file,
        expected_schema_version=KNOWLEDGE_CLASSIFY_SCHEMA_VERSION,
    )
    if answers_by_unit_id is None:
        return None, errors, metadata
    next_errors = list(errors)
    error_details = list(metadata.get("error_details") or [])
    failed_unit_ids: list[str] = []
    unresolved_block_indices: list[int] = []
    validated_answers: dict[str, dict[str, Any]] = {}
    units_by_id = {
        str(unit.get("unit_id") or "").strip(): dict(unit)
        for unit in (original_task_file.get("units") or [])
        if isinstance(unit, Mapping) and str(unit.get("unit_id") or "").strip()
    }
    for unit_id, answer in answers_by_unit_id.items():
        unit = units_by_id.get(unit_id) or {}
        block_index = int(_coerce_dict(unit.get("evidence")).get("block_index") or 0)
        category = str(answer.get("category") or "").strip()
        reviewer_category = str(answer.get("reviewer_category") or "").strip()
        unit_failed = False
        if category not in ALLOWED_KNOWLEDGE_FINAL_CATEGORIES:
            next_errors.append("invalid_category")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/category",
                    "code": "invalid_category",
                    "message": "category must be 'knowledge' or 'other'",
                }
            )
            unit_failed = True
        if reviewer_category not in ALLOWED_KNOWLEDGE_REVIEWER_CATEGORIES:
            next_errors.append("invalid_reviewer_category")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/reviewer_category",
                    "code": "invalid_reviewer_category",
                    "message": "reviewer_category must be a supported enum value",
                }
            )
            unit_failed = True
        elif category == "knowledge" and reviewer_category != "knowledge":
            next_errors.append("knowledge_reviewer_category_mismatch")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/reviewer_category",
                    "code": "knowledge_reviewer_category_mismatch",
                    "message": "knowledge rows must use reviewer_category=knowledge",
                }
            )
            unit_failed = True
        elif category == "other" and reviewer_category == "knowledge":
            next_errors.append("other_reviewer_category_mismatch")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/reviewer_category",
                    "code": "other_reviewer_category_mismatch",
                    "message": "other rows must not use reviewer_category=knowledge",
                }
            )
            unit_failed = True
        if unit_failed:
            failed_unit_ids.append(unit_id)
            unresolved_block_indices.append(block_index)
            continue
        validated_answers[unit_id] = {
            "category": category,
            "reviewer_category": reviewer_category,
        }
    next_metadata = {
        **dict(metadata),
        "error_details": error_details,
        "failed_unit_ids": failed_unit_ids,
        "unresolved_block_indices": sorted(set(unresolved_block_indices)),
        "validated_answers_by_unit_id": validated_answers,
    }
    if next_errors:
        return None, tuple(dict.fromkeys(next_errors)), next_metadata
    return validated_answers, (), next_metadata


def build_knowledge_grouping_task_file(
    *,
    assignment_id: str,
    worker_id: str,
    classification_task_file: Mapping[str, Any],
    classification_answers_by_unit_id: Mapping[str, Mapping[str, Any]],
    unit_to_shard_id: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    units: list[dict[str, Any]] = []
    grouping_unit_to_shard_id: dict[str, str] = {}
    for unit in classification_task_file.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_dict = dict(unit)
        unit_id = str(unit_dict.get("unit_id") or "").strip()
        answer = _coerce_dict(classification_answers_by_unit_id.get(unit_id))
        if str(answer.get("category") or "").strip() != "knowledge":
            continue
        evidence = _coerce_dict(unit_dict.get("evidence"))
        block_index = int(evidence.get("block_index") or 0)
        owned_id = str(unit_dict.get("owned_id") or evidence.get("block_id") or unit_id).strip()
        shard_id = str(unit_to_shard_id.get(unit_id) or "").strip()
        if not shard_id:
            continue
        grouping_unit_to_shard_id[unit_id] = shard_id
        units.append(
            {
                "unit_id": unit_id,
                "owned_id": owned_id,
                "evidence": {
                    "block_index": block_index,
                    "block_id": str(evidence.get("block_id") or owned_id),
                    "text": str(evidence.get("text") or ""),
                    "context_before": evidence.get("context_before"),
                    "context_after": evidence.get("context_after"),
                },
                "answer": {},
            }
        )
    return (
        build_task_file(
            stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
            assignment_id=assignment_id,
            worker_id=worker_id,
            units=units,
            schema_version=KNOWLEDGE_GROUP_SCHEMA_VERSION,
        ),
        grouping_unit_to_shard_id,
    )


def validate_knowledge_grouping_task_file(
    *,
    original_task_file: Mapping[str, Any],
    edited_task_file: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]] | None, tuple[str, ...], dict[str, Any]]:
    answers_by_unit_id, errors, metadata = validate_edited_task_file(
        original_task_file=original_task_file,
        edited_task_file=edited_task_file,
        expected_schema_version=KNOWLEDGE_GROUP_SCHEMA_VERSION,
    )
    if answers_by_unit_id is None:
        return None, errors, metadata
    next_errors = list(errors)
    error_details = list(metadata.get("error_details") or [])
    failed_unit_ids: list[str] = []
    unresolved_block_indices: list[int] = []
    validated_answers: dict[str, dict[str, Any]] = {}
    units_by_id = {
        str(unit.get("unit_id") or "").strip(): dict(unit)
        for unit in (original_task_file.get("units") or [])
        if isinstance(unit, Mapping) and str(unit.get("unit_id") or "").strip()
    }
    for unit_id, answer in answers_by_unit_id.items():
        unit = units_by_id.get(unit_id) or {}
        block_index = int(_coerce_dict(unit.get("evidence")).get("block_index") or 0)
        group_key = str(answer.get("group_key") or "").strip()
        topic_label = str(answer.get("topic_label") or "").strip()
        unit_failed = False
        if not group_key:
            next_errors.append("knowledge_block_missing_group")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/group_key",
                    "code": "knowledge_block_missing_group",
                    "message": "group_key must be a non-empty string",
                }
            )
            unit_failed = True
        if not topic_label:
            next_errors.append("knowledge_block_missing_group")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/topic_label",
                    "code": "knowledge_block_missing_group",
                    "message": "topic_label must be a non-empty string",
                }
            )
            unit_failed = True
        if unit_failed:
            failed_unit_ids.append(unit_id)
            unresolved_block_indices.append(block_index)
            continue
        validated_answers[unit_id] = {
            "group_key": group_key,
            "topic_label": topic_label,
        }
    next_metadata = {
        **dict(metadata),
        "error_details": error_details,
        "failed_unit_ids": failed_unit_ids,
        "unresolved_block_indices": sorted(set(unresolved_block_indices)),
        "validated_answers_by_unit_id": validated_answers,
    }
    if next_errors:
        next_metadata["knowledge_blocks_missing_group"] = sorted(set(unresolved_block_indices))
        return None, tuple(dict.fromkeys(next_errors)), next_metadata
    return validated_answers, (), next_metadata


def combine_knowledge_task_file_outputs(
    *,
    classification_task_file: Mapping[str, Any],
    classification_answers_by_unit_id: Mapping[str, Mapping[str, Any]],
    grouping_answers_by_unit_id: Mapping[str, Mapping[str, Any]] | None,
    unit_to_shard_id: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    shard_rows: dict[str, list[tuple[int, dict[str, Any], str]]] = {}
    for unit in classification_task_file.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_dict = dict(unit)
        unit_id = str(unit_dict.get("unit_id") or "").strip()
        shard_id = str(unit_to_shard_id.get(unit_id) or "").strip()
        if not shard_id:
            continue
        evidence = _coerce_dict(unit_dict.get("evidence"))
        block_index = int(evidence.get("block_index") or 0)
        answer = _coerce_dict(classification_answers_by_unit_id.get(unit_id))
        category = str(answer.get("category") or "other").strip() or "other"
        shard_rows.setdefault(shard_id, []).append((block_index, answer, unit_id))
    outputs: dict[str, dict[str, Any]] = {}
    grouping_answers = grouping_answers_by_unit_id or {}
    for shard_id, rows in shard_rows.items():
        ordered_rows = sorted(rows, key=lambda row: row[0])
        group_members: dict[tuple[str, str], list[int]] = {}
        block_decisions: list[dict[str, Any]] = []
        for block_index, answer, unit_id in ordered_rows:
            category = str(answer.get("category") or "other").strip() or "other"
            reviewer_category = str(
                answer.get("reviewer_category")
                or ("knowledge" if category == "knowledge" else "other")
            ).strip() or ("knowledge" if category == "knowledge" else "other")
            block_decisions.append(
                {
                    "block_index": block_index,
                    "category": category,
                    "reviewer_category": reviewer_category,
                }
            )
            if category != "knowledge":
                continue
            grouping_answer = _coerce_dict(grouping_answers.get(unit_id))
            group_key = str(grouping_answer.get("group_key") or "").strip()
            topic_label = str(grouping_answer.get("topic_label") or "").strip()
            if group_key and topic_label:
                group_members.setdefault((group_key, topic_label), []).append(block_index)
        idea_groups = [
            {
                "group_id": f"g{index + 1:02d}",
                "topic_label": topic_label,
                "block_indices": sorted(block_indices),
            }
            for index, ((_, topic_label), block_indices) in enumerate(
                sorted(group_members.items(), key=lambda row: (row[0][0], row[0][1]))
            )
        ]
        outputs[shard_id] = {
            "packet_id": shard_id,
            "block_decisions": block_decisions,
            "idea_groups": idea_groups,
        }
    return outputs
