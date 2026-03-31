from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Mapping, Sequence

from ..codex_farm_knowledge_models import (
    ALLOWED_KNOWLEDGE_FINAL_CATEGORIES,
    ALLOWED_KNOWLEDGE_REVIEWER_CATEGORIES,
)
from ..editable_task_file import (
    build_repair_task_file,
    build_task_file,
    validate_edited_task_file,
)
from ..knowledge_tag_catalog import (
    empty_grounding_payload,
    load_knowledge_tag_catalog,
    normalize_knowledge_tag_key,
)
from ..phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1

KNOWLEDGE_CLASSIFY_STAGE_KEY = "nonrecipe_classify"
KNOWLEDGE_GROUP_STAGE_KEY = "knowledge_group"
KNOWLEDGE_CLASSIFY_SCHEMA_VERSION = "knowledge_block_classify.v1"
KNOWLEDGE_GROUP_SCHEMA_VERSION = "knowledge_group_only.v1"


@dataclass(frozen=True)
class KnowledgeTaskFileTransition:
    status: str
    current_stage_key: str
    next_stage_key: str | None = None
    next_task_file: dict[str, Any] | None = None
    final_outputs: dict[str, dict[str, Any]] | None = None
    validated_answers_by_unit_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    validation_errors: tuple[str, ...] = ()
    validation_metadata: dict[str, Any] = field(default_factory=dict)
    transition_metadata: dict[str, Any] = field(default_factory=dict)


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


def _blank_classification_answer() -> dict[str, Any]:
    return {
        "category": None,
        "reviewer_category": None,
        "retrieval_concept": None,
        "grounding": empty_grounding_payload(),
    }


def _trimmed_text_or_none(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    deduped: list[str] = []
    seen: set[str] = set()
    for row in value:
        cleaned = str(row or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def _normalize_output_grounding(value: Any) -> dict[str, Any]:
    grounding = _coerce_dict(value)
    return {
        "tag_keys": _normalized_string_list(grounding.get("tag_keys")),
        "category_keys": _normalized_string_list(grounding.get("category_keys")),
        "proposed_tags": [
            {
                "key": str(row.get("key") or "").strip(),
                "display_name": str(row.get("display_name") or "").strip(),
                "category_key": str(row.get("category_key") or "").strip(),
            }
            for row in (grounding.get("proposed_tags") or [])
            if isinstance(row, Mapping)
            and str(row.get("key") or "").strip()
            and str(row.get("display_name") or "").strip()
            and str(row.get("category_key") or "").strip()
        ],
    }


def build_task_file_answer_feedback(
    *,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    failed_unit_ids = {
        str(unit_id).strip()
        for unit_id in (validation_metadata.get("failed_unit_ids") or [])
        if str(unit_id).strip()
    }
    if not failed_unit_ids:
        return {}
    details = [dict(detail) for detail in (validation_metadata.get("error_details") or [])]
    feedback = {
        "validation_errors": [
            str(error).strip() for error in validation_errors if str(error).strip()
        ],
        "error_details": details,
    }
    return {unit_id: dict(feedback) for unit_id in failed_unit_ids}


def build_knowledge_classification_task_file(
    *,
    assignment: WorkerAssignmentV1,
    shards: Sequence[ShardManifestEntryV1],
) -> tuple[dict[str, Any], dict[str, str]]:
    catalog = load_knowledge_tag_catalog()
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
                        "candidate_tag_keys": catalog.candidate_tag_keys_for_text(
                            block.get("t"),
                        ),
                        "routing_hints": [],
                    },
                    "answer": _blank_classification_answer(),
                }
                indexed_units.append(
                    (_classification_sort_key(block_id, block_index), unit_payload)
                )
    units = [payload for _sort_key, payload in sorted(indexed_units, key=lambda row: row[0])]
    task_file = build_task_file(
        stage_key=KNOWLEDGE_CLASSIFY_STAGE_KEY,
        assignment_id=assignment.worker_id,
        worker_id=assignment.worker_id,
        units=units,
        schema_version=KNOWLEDGE_CLASSIFY_SCHEMA_VERSION,
    )
    task_file["ontology"] = catalog.task_scope_payload()
    return (task_file, unit_to_shard_id)


def validate_knowledge_classification_task_file(
    *,
    original_task_file: Mapping[str, Any],
    edited_task_file: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]] | None, tuple[str, ...], dict[str, Any]]:
    catalog = load_knowledge_tag_catalog()
    category_keys = set(catalog.category_by_key)
    tag_keys = set(catalog.tag_by_key)
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
        retrieval_concept = _trimmed_text_or_none(answer.get("retrieval_concept"))
        grounding = _coerce_dict(answer.get("grounding"))
        proposed_tags_raw = grounding.get("proposed_tags")
        normalized_grounding = empty_grounding_payload()
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
        raw_tag_keys = grounding.get("tag_keys")
        if raw_tag_keys not in (None, "") and not isinstance(raw_tag_keys, list):
            next_errors.append("invalid_grounding_tag_keys")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/grounding/tag_keys",
                    "code": "invalid_grounding_tag_keys",
                    "message": "grounding.tag_keys must be a list of existing tag keys",
                }
            )
            unit_failed = True
        for tag_key in _normalized_string_list(raw_tag_keys):
            normalized_tag_key = normalize_knowledge_tag_key(tag_key)
            if normalized_tag_key not in tag_keys:
                next_errors.append("unknown_grounding_tag_key")
                error_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/tag_keys",
                        "code": "unknown_grounding_tag_key",
                        "message": f"unknown grounding tag key {tag_key!r}",
                    }
                )
                unit_failed = True
                continue
            normalized_grounding["tag_keys"].append(normalized_tag_key)
        raw_category_keys = grounding.get("category_keys")
        if raw_category_keys not in (None, "") and not isinstance(raw_category_keys, list):
            next_errors.append("invalid_grounding_category_keys")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/grounding/category_keys",
                    "code": "invalid_grounding_category_keys",
                    "message": "grounding.category_keys must be a list of existing category keys",
                }
            )
            unit_failed = True
        for category_key in _normalized_string_list(raw_category_keys):
            normalized_category_key = normalize_knowledge_tag_key(category_key)
            if normalized_category_key not in category_keys:
                next_errors.append("unknown_grounding_category_key")
                error_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/category_keys",
                        "code": "unknown_grounding_category_key",
                        "message": f"unknown grounding category key {category_key!r}",
                    }
                )
                unit_failed = True
                continue
            normalized_grounding["category_keys"].append(normalized_category_key)
        if proposed_tags_raw not in (None, "") and not isinstance(proposed_tags_raw, list):
            next_errors.append("invalid_grounding_proposed_tags")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/grounding/proposed_tags",
                    "code": "invalid_grounding_proposed_tags",
                    "message": "grounding.proposed_tags must be a list of proposed tag objects",
                }
            )
            unit_failed = True
        proposed_keys_seen: set[str] = set()
        for index, row in enumerate(proposed_tags_raw or []):
            if not isinstance(row, Mapping):
                next_errors.append("invalid_grounding_proposed_tags")
                error_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/proposed_tags/{index}",
                        "code": "invalid_grounding_proposed_tags",
                        "message": "each proposed tag must be a JSON object",
                    }
                )
                unit_failed = True
                continue
            proposed_key = str(row.get("key") or "").strip()
            normalized_proposed_key = normalize_knowledge_tag_key(proposed_key)
            if not proposed_key or proposed_key != normalized_proposed_key:
                next_errors.append("invalid_proposed_tag_key")
                error_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/proposed_tags/{index}/key",
                        "code": "invalid_proposed_tag_key",
                        "message": "proposed tag keys must already be normalized slug strings",
                    }
                )
                unit_failed = True
            if normalized_proposed_key in tag_keys:
                next_errors.append("proposed_tag_key_conflicts_existing")
                error_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/proposed_tags/{index}/key",
                        "code": "proposed_tag_key_conflicts_existing",
                        "message": "proposed tag keys must not duplicate an existing tag key",
                    }
                )
                unit_failed = True
            if normalized_proposed_key in proposed_keys_seen:
                next_errors.append("duplicate_proposed_tag_key")
                error_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/proposed_tags/{index}/key",
                        "code": "duplicate_proposed_tag_key",
                        "message": "proposed tag keys must be unique within one answer",
                    }
                )
                unit_failed = True
            proposed_keys_seen.add(normalized_proposed_key)
            display_name = str(row.get("display_name") or "").strip()
            if not display_name or len(display_name) > 64:
                next_errors.append("invalid_proposed_tag_display_name")
                error_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/proposed_tags/{index}/display_name",
                        "code": "invalid_proposed_tag_display_name",
                        "message": "proposed display_name must be a short non-empty string",
                    }
                )
                unit_failed = True
            proposed_category_key = normalize_knowledge_tag_key(row.get("category_key"))
            if not proposed_category_key or proposed_category_key not in category_keys:
                next_errors.append("unknown_grounding_category_key")
                error_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/proposed_tags/{index}/category_key",
                        "code": "unknown_grounding_category_key",
                        "message": "proposed tag category_key must be an existing category key",
                    }
                )
                unit_failed = True
            normalized_grounding["proposed_tags"].append(
                {
                    "key": normalized_proposed_key,
                    "display_name": display_name,
                    "category_key": proposed_category_key,
                }
            )
        if category == "knowledge":
            if retrieval_concept is None:
                next_errors.append("knowledge_missing_retrieval_concept")
                error_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/retrieval_concept",
                        "code": "knowledge_missing_retrieval_concept",
                        "message": "knowledge rows must provide a non-empty retrieval_concept",
                    }
                )
                unit_failed = True
            if not normalized_grounding["tag_keys"] and not normalized_grounding["proposed_tags"]:
                next_errors.append("knowledge_missing_grounding")
                error_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding",
                        "code": "knowledge_missing_grounding",
                        "message": "knowledge rows must ground to an existing tag or a proposed tag",
                    }
                )
                unit_failed = True
        elif category == "other":
            if retrieval_concept is not None:
                next_errors.append("other_retrieval_concept_forbidden")
                error_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/retrieval_concept",
                        "code": "other_retrieval_concept_forbidden",
                        "message": "other rows must leave retrieval_concept null",
                    }
                )
                unit_failed = True
            if (
                normalized_grounding["tag_keys"]
                or normalized_grounding["category_keys"]
                or normalized_grounding["proposed_tags"]
            ):
                next_errors.append("other_grounding_forbidden")
                error_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding",
                        "code": "other_grounding_forbidden",
                        "message": "other rows must not carry grounding metadata",
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
            "retrieval_concept": retrieval_concept,
            "grounding": normalized_grounding,
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
            retrieval_concept = _trimmed_text_or_none(answer.get("retrieval_concept"))
            grounding = _normalize_output_grounding(answer.get("grounding"))
            block_decisions.append(
                {
                    "block_index": block_index,
                    "category": category,
                    "reviewer_category": reviewer_category,
                    "retrieval_concept": retrieval_concept,
                    "grounding": grounding,
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


def transition_knowledge_classification_task_file(
    *,
    original_task_file: Mapping[str, Any],
    edited_task_file: Mapping[str, Any],
    unit_to_shard_id: Mapping[str, str],
) -> KnowledgeTaskFileTransition:
    answers_by_unit_id, validation_errors, validation_metadata = (
        validate_knowledge_classification_task_file(
            original_task_file=original_task_file,
            edited_task_file=edited_task_file,
        )
    )
    validated_answers_by_unit_id = dict(
        validation_metadata.get("validated_answers_by_unit_id") or {}
    )
    if answers_by_unit_id is not None:
        validated_answers_by_unit_id.update(dict(answers_by_unit_id))
    no_edits_detected = (
        not validation_errors
        and not validation_metadata.get("error_details")
        and
        int(validation_metadata.get("changed_unit_count") or 0) <= 0
        and not validated_answers_by_unit_id
    )
    if no_edits_detected:
        return KnowledgeTaskFileTransition(
            status="no_edits_detected",
            current_stage_key=KNOWLEDGE_CLASSIFY_STAGE_KEY,
            validation_metadata={
                **dict(validation_metadata),
                "no_edits_detected": True,
            },
        )
    if validation_errors or validation_metadata.get("error_details"):
        failed_unit_ids = [
            str(unit_id).strip()
            for unit_id in (validation_metadata.get("failed_unit_ids") or [])
            if str(unit_id).strip()
        ]
        if not failed_unit_ids:
            failed_unit_ids = [
                str(unit.get("unit_id") or "").strip()
                for unit in (original_task_file.get("units") or [])
                if isinstance(unit, Mapping) and str(unit.get("unit_id") or "").strip()
            ]
        repair_task_file = build_repair_task_file(
            original_task_file=original_task_file,
            failed_unit_ids=failed_unit_ids,
            previous_answers_by_unit_id={
                str(unit.get("unit_id") or "").strip(): (
                    dict(unit.get("answer") or {})
                    if isinstance(unit, Mapping)
                    else {}
                )
                for unit in (edited_task_file.get("units") or [])
                if isinstance(unit, Mapping) and str(unit.get("unit_id") or "").strip()
            },
            validation_feedback_by_unit_id=build_task_file_answer_feedback(
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
            ),
        )
        return KnowledgeTaskFileTransition(
            status="repair_required",
            current_stage_key=KNOWLEDGE_CLASSIFY_STAGE_KEY,
            next_stage_key=KNOWLEDGE_CLASSIFY_STAGE_KEY,
            next_task_file=repair_task_file,
            validated_answers_by_unit_id=validated_answers_by_unit_id,
            validation_errors=tuple(validation_errors),
            validation_metadata=dict(validation_metadata),
            transition_metadata={
                "repair_unit_count": len(repair_task_file.get("units") or []),
                "repair_reason": "task_file_contract_violation"
                if not validation_metadata.get("failed_unit_ids")
                else "unit_validation_failure",
            },
        )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id=str(original_task_file.get("assignment_id") or ""),
        worker_id=str(original_task_file.get("worker_id") or ""),
        classification_task_file=original_task_file,
        classification_answers_by_unit_id=validated_answers_by_unit_id,
        unit_to_shard_id=unit_to_shard_id,
    )
    if grouping_task_file.get("units"):
        return KnowledgeTaskFileTransition(
            status="advance_to_grouping",
            current_stage_key=KNOWLEDGE_CLASSIFY_STAGE_KEY,
            next_stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
            next_task_file=grouping_task_file,
            validated_answers_by_unit_id=validated_answers_by_unit_id,
            validation_metadata=dict(validation_metadata),
            transition_metadata={
                "grouping_unit_count": len(grouping_task_file.get("units") or []),
            },
        )
    return KnowledgeTaskFileTransition(
        status="completed_without_grouping",
        current_stage_key=KNOWLEDGE_CLASSIFY_STAGE_KEY,
        final_outputs=combine_knowledge_task_file_outputs(
            classification_task_file=original_task_file,
            classification_answers_by_unit_id=validated_answers_by_unit_id,
            grouping_answers_by_unit_id=None,
            unit_to_shard_id=unit_to_shard_id,
        ),
        validated_answers_by_unit_id=validated_answers_by_unit_id,
        validation_metadata=dict(validation_metadata),
    )


def transition_knowledge_grouping_task_file(
    *,
    original_task_file: Mapping[str, Any],
    edited_task_file: Mapping[str, Any],
    classification_task_file: Mapping[str, Any],
    classification_answers_by_unit_id: Mapping[str, Mapping[str, Any]],
    unit_to_shard_id: Mapping[str, str],
) -> KnowledgeTaskFileTransition:
    answers_by_unit_id, validation_errors, validation_metadata = (
        validate_knowledge_grouping_task_file(
            original_task_file=original_task_file,
            edited_task_file=edited_task_file,
        )
    )
    validated_answers_by_unit_id = dict(
        validation_metadata.get("validated_answers_by_unit_id") or {}
    )
    if answers_by_unit_id is not None:
        validated_answers_by_unit_id.update(dict(answers_by_unit_id))
    no_edits_detected = (
        not validation_errors
        and not validation_metadata.get("error_details")
        and
        int(validation_metadata.get("changed_unit_count") or 0) <= 0
        and not validated_answers_by_unit_id
    )
    if no_edits_detected:
        return KnowledgeTaskFileTransition(
            status="no_edits_detected",
            current_stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
            validation_metadata={
                **dict(validation_metadata),
                "no_edits_detected": True,
            },
        )
    if validation_errors or validation_metadata.get("error_details"):
        failed_unit_ids = [
            str(unit_id).strip()
            for unit_id in (validation_metadata.get("failed_unit_ids") or [])
            if str(unit_id).strip()
        ]
        if not failed_unit_ids:
            failed_unit_ids = [
                str(unit.get("unit_id") or "").strip()
                for unit in (original_task_file.get("units") or [])
                if isinstance(unit, Mapping) and str(unit.get("unit_id") or "").strip()
            ]
        repair_task_file = build_repair_task_file(
            original_task_file=original_task_file,
            failed_unit_ids=failed_unit_ids,
            previous_answers_by_unit_id={
                str(unit.get("unit_id") or "").strip(): (
                    dict(unit.get("answer") or {})
                    if isinstance(unit, Mapping)
                    else {}
                )
                for unit in (edited_task_file.get("units") or [])
                if isinstance(unit, Mapping) and str(unit.get("unit_id") or "").strip()
            },
            validation_feedback_by_unit_id=build_task_file_answer_feedback(
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
            ),
        )
        return KnowledgeTaskFileTransition(
            status="repair_required",
            current_stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
            next_stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
            next_task_file=repair_task_file,
            validated_answers_by_unit_id=validated_answers_by_unit_id,
            validation_errors=tuple(validation_errors),
            validation_metadata=dict(validation_metadata),
            transition_metadata={
                "repair_unit_count": len(repair_task_file.get("units") or []),
                "repair_reason": "task_file_contract_violation"
                if not validation_metadata.get("failed_unit_ids")
                else "unit_validation_failure",
            },
        )
    return KnowledgeTaskFileTransition(
        status="completed_with_grouping",
        current_stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
        final_outputs=combine_knowledge_task_file_outputs(
            classification_task_file=classification_task_file,
            classification_answers_by_unit_id=classification_answers_by_unit_id,
            grouping_answers_by_unit_id=validated_answers_by_unit_id,
            unit_to_shard_id=unit_to_shard_id,
        ),
        validated_answers_by_unit_id=validated_answers_by_unit_id,
        validation_metadata=dict(validation_metadata),
    )
