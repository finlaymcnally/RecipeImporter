from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping, Sequence

from ..codex_farm_knowledge_models import (
    ALLOWED_KNOWLEDGE_FINAL_CATEGORIES,
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
KNOWLEDGE_GROUP_TASK_MAX_UNITS = 40
KNOWLEDGE_GROUP_TASK_MAX_EVIDENCE_CHARS = 12000


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
        "grounding": empty_grounding_payload(),
    }


def _canonical_other_classification_answer() -> dict[str, Any]:
    return {
        "category": "other",
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
    normalized_validation_errors = [
        str(error).strip() for error in validation_errors if str(error).strip()
    ]
    feedback_by_unit_id: dict[str, dict[str, Any]] = {}
    for unit_id in failed_unit_ids:
        unit_path_prefix = f"/units/{unit_id}/"
        unit_path_exact = f"/units/{unit_id}"
        unit_details = [
            detail
            for detail in details
            if str(detail.get("path") or "").strip().startswith(unit_path_prefix)
            or str(detail.get("path") or "").strip() == unit_path_exact
        ]
        unit_codes = [
            str(detail.get("code") or "").strip()
            for detail in unit_details
            if str(detail.get("code") or "").strip()
        ]
        feedback_by_unit_id[unit_id] = {
            "validation_errors": unit_codes or normalized_validation_errors,
            "error_details": unit_details,
        }
    return feedback_by_unit_id

def _knowledge_classification_answer_schema() -> dict[str, Any]:
    return {
        "editable_pointer_pattern": "/units/*/answer",
        "required_keys": ["category", "grounding"],
        "allowed_values": {"category": list(ALLOWED_KNOWLEDGE_FINAL_CATEGORIES)},
        "example_answers": [
            {
                "category": "knowledge",
                "grounding": {
                    "tag_keys": [],
                    "category_keys": [],
                    "proposed_tags": [
                        {
                            "key": "heat-control",
                            "display_name": "Heat control",
                            "category_key": "techniques",
                        }
                    ],
                },
            },
            {
                "category": "other",
                "grounding": {
                    "tag_keys": [],
                    "category_keys": [],
                    "proposed_tags": [],
                },
            },
        ],
    }


def _knowledge_classification_review_contract() -> dict[str, Any]:
    return {
        "mode": "semantic_review",
        "worker_role": (
            "You are doing close semantic review of owned non-recipe blocks, not "
            "writing a classifier or bulk heuristic."
        ),
        "primary_question": (
            "Would this exact block be worth retrieving later as a standalone "
            "cooking concept?"
        ),
        "decision_policy": [
            "Read the owned block text first. That text is the primary evidence.",
            "Use nearby context only to disambiguate edge cases, not to force nearby rows into the same answer.",
            "Treat candidate tags, heading shape, and packet position as weak hints only.",
            "Short conceptual headings can still be knowledge when they introduce real explanatory content; shortness alone is not enough to drop a block.",
        ],
        "anti_patterns": [
            "Do not invent a rule that classifies many rows at once from heading level, casing, length, or title shape.",
            "Do not treat the whole packet as one semantic unit just because the rows are adjacent.",
            "Do not treat candidate tags as votes or proof that a block is knowledge.",
            "If you feel tempted to batch or script the decision, stop and reread the actual owned block text instead.",
        ],
    }


def _knowledge_grouping_answer_schema() -> dict[str, Any]:
    return {
        "editable_pointer_pattern": "/units/*/answer",
        "required_keys": ["group_key", "topic_label"],
        "example_answers": [
            {
                "group_key": "heat-control",
                "topic_label": "Heat control",
            }
        ],
    }


def _grouping_batch_metadata(
    *,
    batch_units: Sequence[Mapping[str, Any]],
    batch_index: int,
    batch_count: int,
    total_grouping_unit_count: int,
    max_units_per_batch: int,
    max_evidence_chars_per_batch: int,
) -> dict[str, Any]:
    shard_ids: list[str] = []
    seen_shard_ids: set[str] = set()
    evidence_chars = 0
    for unit in batch_units:
        if not isinstance(unit, Mapping):
            continue
        shard_id = str(unit.get("grouping_shard_id") or "").strip()
        if shard_id and shard_id not in seen_shard_ids:
            seen_shard_ids.add(shard_id)
            shard_ids.append(shard_id)
        evidence_chars += len(
            json.dumps(_coerce_dict(unit.get("evidence")), sort_keys=True, ensure_ascii=True)
        )
    return {
        "current_batch_index": max(1, int(batch_index)),
        "total_batches": max(1, int(batch_count)),
        "unit_count": len(batch_units),
        "total_grouping_unit_count": max(0, int(total_grouping_unit_count)),
        "remaining_batches_after_this": max(0, int(batch_count) - int(batch_index)),
        "estimated_evidence_chars": evidence_chars,
        "max_units_per_batch": max(1, int(max_units_per_batch)),
        "max_evidence_chars_per_batch": max(1, int(max_evidence_chars_per_batch)),
        "shard_ids": shard_ids,
    }


def _grouping_unit_budget(unit: Mapping[str, Any]) -> int:
    return len(
        json.dumps(_coerce_dict(unit.get("evidence")), sort_keys=True, ensure_ascii=True)
    )


def _collect_knowledge_grouping_units(
    *,
    classification_task_file: Mapping[str, Any],
    classification_answers_by_unit_id: Mapping[str, Mapping[str, Any]],
    unit_to_shard_id: Mapping[str, str],
    allowed_unit_ids: Sequence[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    units: list[dict[str, Any]] = []
    grouping_unit_to_shard_id: dict[str, str] = {}
    allowed_unit_id_set = (
        {
            str(unit_id).strip()
            for unit_id in (allowed_unit_ids or [])
            if str(unit_id).strip()
        }
        if allowed_unit_ids is not None
        else None
    )
    for unit in classification_task_file.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_dict = dict(unit)
        unit_id = str(unit_dict.get("unit_id") or "").strip()
        if allowed_unit_id_set is not None and unit_id not in allowed_unit_id_set:
            continue
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
                "grouping_shard_id": shard_id,
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
    return units, grouping_unit_to_shard_id


def _partition_knowledge_grouping_units(
    units: Sequence[Mapping[str, Any]],
    *,
    max_units_per_batch: int,
    max_evidence_chars_per_batch: int,
) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    current_batch: list[dict[str, Any]] = []
    current_budget = 0
    for unit in units:
        if not isinstance(unit, Mapping):
            continue
        unit_dict = dict(unit)
        unit_budget = _grouping_unit_budget(unit_dict)
        should_rotate = bool(current_batch) and (
            len(current_batch) >= max(1, int(max_units_per_batch))
            or current_budget + unit_budget > max(1, int(max_evidence_chars_per_batch))
        )
        if should_rotate:
            batches.append(current_batch)
            current_batch = []
            current_budget = 0
        current_batch.append(unit_dict)
        current_budget += unit_budget
    if current_batch:
        batches.append(current_batch)
    return batches


def _build_knowledge_grouping_task_file_from_units(
    *,
    assignment_id: str,
    worker_id: str,
    units: Sequence[Mapping[str, Any]],
    batch_index: int,
    batch_count: int,
    total_grouping_unit_count: int,
    max_units_per_batch: int,
    max_evidence_chars_per_batch: int,
) -> dict[str, Any]:
    task_units = [
        {
            key: value
            for key, value in dict(unit).items()
            if key != "grouping_shard_id"
        }
        for unit in units
        if isinstance(unit, Mapping)
    ]
    task_file = build_task_file(
        stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
        assignment_id=assignment_id,
        worker_id=worker_id,
        units=task_units,
        schema_version=KNOWLEDGE_GROUP_SCHEMA_VERSION,
        answer_schema=_knowledge_grouping_answer_schema(),
    )
    if task_units:
        task_file["grouping_batch"] = _grouping_batch_metadata(
            batch_units=units,
            batch_index=batch_index,
            batch_count=batch_count,
            total_grouping_unit_count=total_grouping_unit_count,
            max_units_per_batch=max_units_per_batch,
            max_evidence_chars_per_batch=max_evidence_chars_per_batch,
        )
    return task_file


def build_knowledge_grouping_task_files(
    *,
    assignment_id: str,
    worker_id: str,
    classification_task_file: Mapping[str, Any],
    classification_answers_by_unit_id: Mapping[str, Mapping[str, Any]],
    unit_to_shard_id: Mapping[str, str],
    max_units_per_batch: int = KNOWLEDGE_GROUP_TASK_MAX_UNITS,
    max_evidence_chars_per_batch: int = KNOWLEDGE_GROUP_TASK_MAX_EVIDENCE_CHARS,
) -> tuple[list[dict[str, Any]], dict[str, str], list[list[str]]]:
    units, grouping_unit_to_shard_id = _collect_knowledge_grouping_units(
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id=classification_answers_by_unit_id,
        unit_to_shard_id=unit_to_shard_id,
    )
    batches = _partition_knowledge_grouping_units(
        units,
        max_units_per_batch=max_units_per_batch,
        max_evidence_chars_per_batch=max_evidence_chars_per_batch,
    )
    total_grouping_unit_count = len(units)
    task_files = [
        _build_knowledge_grouping_task_file_from_units(
            assignment_id=assignment_id,
            worker_id=worker_id,
            units=batch_units,
            batch_index=index + 1,
            batch_count=len(batches),
            total_grouping_unit_count=total_grouping_unit_count,
            max_units_per_batch=max_units_per_batch,
            max_evidence_chars_per_batch=max_evidence_chars_per_batch,
        )
        for index, batch_units in enumerate(batches)
    ]
    batch_unit_ids = [
        [
            str(unit.get("unit_id") or "").strip()
            for unit in batch_units
            if str(unit.get("unit_id") or "").strip()
        ]
        for batch_units in batches
    ]
    return task_files, grouping_unit_to_shard_id, batch_unit_ids


def build_knowledge_classification_task_file(
    *,
    assignment: WorkerAssignmentV1,
    shards: Sequence[ShardManifestEntryV1],
    knowledge_group_task_max_units: int = KNOWLEDGE_GROUP_TASK_MAX_UNITS,
    knowledge_group_task_max_evidence_chars: int = KNOWLEDGE_GROUP_TASK_MAX_EVIDENCE_CHARS,
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
        answer_schema=_knowledge_classification_answer_schema(),
    )
    task_file["ontology"] = catalog.task_scope_payload()
    task_file["review_contract"] = _knowledge_classification_review_contract()
    task_file["grouping_limits"] = {
        "max_units_per_batch": max(1, int(knowledge_group_task_max_units)),
        "max_evidence_chars_per_batch": max(
            1, int(knowledge_group_task_max_evidence_chars)
        ),
    }
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
    grounding_gate_demotion_details: list[dict[str, Any]] = []
    grounding_drop_details: list[dict[str, Any]] = []
    units_by_id = {
        str(unit.get("unit_id") or "").strip(): dict(unit)
        for unit in (original_task_file.get("units") or [])
        if isinstance(unit, Mapping) and str(unit.get("unit_id") or "").strip()
    }
    for unit_id, answer in answers_by_unit_id.items():
        unit = units_by_id.get(unit_id) or {}
        block_index = int(_coerce_dict(unit.get("evidence")).get("block_index") or 0)
        category = str(answer.get("category") or "").strip()
        grounding = _coerce_dict(answer.get("grounding"))
        raw_tag_keys = grounding.get("tag_keys")
        raw_category_keys = grounding.get("category_keys")
        proposed_tags_raw = grounding.get("proposed_tags")
        normalized_grounding = empty_grounding_payload()
        unit_failed = False
        unit_grounding_drop_codes: list[str] = []
        unit_grounding_drop_details: list[dict[str, Any]] = []
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
                unit_grounding_drop_codes.append("unknown_grounding_tag_key")
                unit_grounding_drop_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/tag_keys",
                        "code": "unknown_grounding_tag_key",
                        "message": f"unknown grounding tag key {tag_key!r}",
                    }
                )
                continue
            normalized_grounding["tag_keys"].append(normalized_tag_key)
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
                unit_grounding_drop_codes.append("unknown_grounding_category_key")
                unit_grounding_drop_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/category_keys",
                        "code": "unknown_grounding_category_key",
                        "message": f"unknown grounding category key {category_key!r}",
                    }
                )
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
            proposed_drop_details: list[dict[str, Any]] = []
            if not proposed_key or proposed_key != normalized_proposed_key:
                proposed_drop_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/proposed_tags/{index}/key",
                        "code": "invalid_proposed_tag_key",
                        "message": "proposed tag keys must already be normalized slug strings",
                    }
                )
            if normalized_proposed_key in tag_keys:
                proposed_drop_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/proposed_tags/{index}/key",
                        "code": "proposed_tag_key_conflicts_existing",
                        "message": "proposed tag keys must not duplicate an existing tag key",
                    }
                )
            if normalized_proposed_key in proposed_keys_seen:
                proposed_drop_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/proposed_tags/{index}/key",
                        "code": "duplicate_proposed_tag_key",
                        "message": "proposed tag keys must be unique within one answer",
                    }
                )
            display_name = str(row.get("display_name") or "").strip()
            if not display_name or len(display_name) > 64:
                proposed_drop_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/proposed_tags/{index}/display_name",
                        "code": "invalid_proposed_tag_display_name",
                        "message": "proposed display_name must be a short non-empty string",
                    }
                )
            proposed_category_key = normalize_knowledge_tag_key(row.get("category_key"))
            if not proposed_category_key or proposed_category_key not in category_keys:
                proposed_drop_details.append(
                    {
                        "path": f"/units/{unit_id}/answer/grounding/proposed_tags/{index}/category_key",
                        "code": "unknown_grounding_category_key",
                        "message": "proposed tag category_key must be an existing category key",
                    }
                )
            if proposed_drop_details:
                unit_grounding_drop_codes.extend(
                    str(detail.get("code") or "").strip()
                    for detail in proposed_drop_details
                    if str(detail.get("code") or "").strip()
                )
                unit_grounding_drop_details.extend(proposed_drop_details)
                continue
            proposed_keys_seen.add(normalized_proposed_key)
            normalized_grounding["proposed_tags"].append(
                {
                    "key": normalized_proposed_key,
                    "display_name": display_name,
                    "category_key": proposed_category_key,
                }
            )
        if unit_grounding_drop_details:
            grounding_drop_details.extend(
                {
                    "unit_id": unit_id,
                    "block_index": block_index,
                    **dict(detail),
                }
                for detail in unit_grounding_drop_details
            )
        if category == "knowledge":
            if (
                not unit_failed
                and not normalized_grounding["tag_keys"]
                and not normalized_grounding["proposed_tags"]
            ):
                demotion_reason = "missing_grounding"
                if normalized_grounding["category_keys"]:
                    demotion_reason = "category_only_grounding"
                elif unit_grounding_drop_details:
                    demotion_reason = "invalid_grounding_dropped_to_empty"
                grounding_gate_demotion_details.append(
                    {
                        "unit_id": unit_id,
                        "block_index": block_index,
                        "reason": demotion_reason,
                        "retained_category_keys": list(normalized_grounding["category_keys"]),
                        "dropped_grounding_error_codes": sorted(
                            {
                                str(code).strip()
                                for code in unit_grounding_drop_codes
                                if str(code).strip()
                            }
                        ),
                    }
                )
                validated_answers[unit_id] = _canonical_other_classification_answer()
                continue
        elif category == "other":
            if (
                normalized_grounding["tag_keys"]
                or normalized_grounding["category_keys"]
                or normalized_grounding["proposed_tags"]
                or _normalized_string_list(raw_tag_keys)
                or _normalized_string_list(raw_category_keys)
                or list(proposed_tags_raw or [])
                or unit_grounding_drop_details
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
            "grounding": normalized_grounding,
        }
    next_metadata = {
        **dict(metadata),
        "error_details": error_details,
        "failed_unit_ids": failed_unit_ids,
        "unresolved_block_indices": sorted(set(unresolved_block_indices)),
        "validated_answers_by_unit_id": validated_answers,
        "grounding_gate_demotion_details": grounding_gate_demotion_details,
        "grounding_gate_demoted_unit_ids": [
            str(detail.get("unit_id") or "").strip()
            for detail in grounding_gate_demotion_details
            if str(detail.get("unit_id") or "").strip()
        ],
        "grounding_gate_demoted_block_indices": sorted(
            {
                int(detail.get("block_index"))
                for detail in grounding_gate_demotion_details
                if detail.get("block_index") is not None
            }
        ),
        "grounding_gate_demotion_reason_counts": {
            reason: sum(
                1
                for detail in grounding_gate_demotion_details
                if str(detail.get("reason") or "").strip() == reason
            )
            for reason in sorted(
                {
                    str(detail.get("reason") or "").strip()
                    for detail in grounding_gate_demotion_details
                    if str(detail.get("reason") or "").strip()
                }
            )
        },
        "grounding_gate_demoted_after_invalid_grounding_drop_unit_ids": [
            str(detail.get("unit_id") or "").strip()
            for detail in grounding_gate_demotion_details
            if str(detail.get("reason") or "").strip() == "invalid_grounding_dropped_to_empty"
            and str(detail.get("unit_id") or "").strip()
        ],
        "grounding_gate_demoted_for_category_only_unit_ids": [
            str(detail.get("unit_id") or "").strip()
            for detail in grounding_gate_demotion_details
            if str(detail.get("reason") or "").strip() == "category_only_grounding"
            and str(detail.get("unit_id") or "").strip()
        ],
        "grounding_drop_details": grounding_drop_details,
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
    max_units_per_batch: int = KNOWLEDGE_GROUP_TASK_MAX_UNITS,
    max_evidence_chars_per_batch: int = KNOWLEDGE_GROUP_TASK_MAX_EVIDENCE_CHARS,
) -> tuple[dict[str, Any], dict[str, str]]:
    task_files, grouping_unit_to_shard_id, _batch_unit_ids = build_knowledge_grouping_task_files(
        assignment_id=assignment_id,
        worker_id=worker_id,
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id=classification_answers_by_unit_id,
        unit_to_shard_id=unit_to_shard_id,
        max_units_per_batch=max_units_per_batch,
        max_evidence_chars_per_batch=max_evidence_chars_per_batch,
    )
    if task_files:
        return task_files[0], grouping_unit_to_shard_id
    return (
        _build_knowledge_grouping_task_file_from_units(
            assignment_id=assignment_id,
            worker_id=worker_id,
            units=(),
            batch_index=1,
            batch_count=1,
            total_grouping_unit_count=0,
            max_units_per_batch=max_units_per_batch,
            max_evidence_chars_per_batch=max_evidence_chars_per_batch,
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
            grounding = _normalize_output_grounding(answer.get("grounding"))
            block_decisions.append(
                {
                    "block_index": block_index,
                    "category": category,
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
    classification_task_file: Mapping[str, Any] | None = None,
    existing_classification_answers_by_unit_id: Mapping[str, Mapping[str, Any]] | None = None,
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
    combined_answers_by_unit_id = {
        str(unit_id): dict(answer)
        for unit_id, answer in dict(
            existing_classification_answers_by_unit_id or {}
        ).items()
        if str(unit_id).strip() and isinstance(answer, Mapping)
    }
    combined_answers_by_unit_id.update(validated_answers_by_unit_id)
    classification_source_task_file = (
        dict(classification_task_file)
        if isinstance(classification_task_file, Mapping)
        else dict(original_task_file)
    )
    no_edits_detected = (
        not validation_errors
        and not validation_metadata.get("error_details")
        and
        int(validation_metadata.get("changed_unit_count") or 0) <= 0
        and not combined_answers_by_unit_id
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
            validated_answers_by_unit_id=combined_answers_by_unit_id,
            validation_errors=tuple(validation_errors),
            validation_metadata=dict(validation_metadata),
            transition_metadata={
                "repair_unit_count": len(repair_task_file.get("units") or []),
                "repair_reason": "task_file_contract_violation"
                if not validation_metadata.get("failed_unit_ids")
                else "unit_validation_failure",
            },
        )
    grouping_limits = _coerce_dict(classification_source_task_file.get("grouping_limits"))
    grouping_task_files, _grouping_unit_to_shard_id, grouping_batch_unit_ids = (
        build_knowledge_grouping_task_files(
            assignment_id=str(original_task_file.get("assignment_id") or ""),
            worker_id=str(original_task_file.get("worker_id") or ""),
            classification_task_file=classification_source_task_file,
            classification_answers_by_unit_id=combined_answers_by_unit_id,
            unit_to_shard_id=unit_to_shard_id,
            max_units_per_batch=int(
                grouping_limits.get("max_units_per_batch")
                or KNOWLEDGE_GROUP_TASK_MAX_UNITS
            ),
            max_evidence_chars_per_batch=int(
                grouping_limits.get("max_evidence_chars_per_batch")
                or KNOWLEDGE_GROUP_TASK_MAX_EVIDENCE_CHARS
            ),
        )
    )
    if grouping_task_files:
        first_grouping_task_file = grouping_task_files[0]
        total_grouping_unit_count = sum(
            len(batch_unit_ids) for batch_unit_ids in grouping_batch_unit_ids
        )
        return KnowledgeTaskFileTransition(
            status="advance_to_grouping",
            current_stage_key=KNOWLEDGE_CLASSIFY_STAGE_KEY,
            next_stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
            next_task_file=first_grouping_task_file,
            validated_answers_by_unit_id=combined_answers_by_unit_id,
            validation_metadata=dict(validation_metadata),
            transition_metadata={
                "grouping_unit_count": total_grouping_unit_count,
                "grouping_batch_count": len(grouping_task_files),
                "current_grouping_batch_index": 1,
                "current_grouping_batch_unit_count": len(
                    first_grouping_task_file.get("units") or []
                ),
                "pending_grouping_unit_batches": grouping_batch_unit_ids[1:],
            },
        )
    return KnowledgeTaskFileTransition(
        status="completed_without_grouping",
        current_stage_key=KNOWLEDGE_CLASSIFY_STAGE_KEY,
        final_outputs=combine_knowledge_task_file_outputs(
            classification_task_file=classification_source_task_file,
            classification_answers_by_unit_id=combined_answers_by_unit_id,
            grouping_answers_by_unit_id=None,
            unit_to_shard_id=unit_to_shard_id,
        ),
        validated_answers_by_unit_id=combined_answers_by_unit_id,
        validation_metadata=dict(validation_metadata),
    )


def transition_knowledge_grouping_task_file(
    *,
    original_task_file: Mapping[str, Any],
    edited_task_file: Mapping[str, Any],
    classification_task_file: Mapping[str, Any],
    classification_answers_by_unit_id: Mapping[str, Mapping[str, Any]],
    grouping_answers_by_unit_id: Mapping[str, Mapping[str, Any]] | None,
    unit_to_shard_id: Mapping[str, str],
    pending_grouping_unit_batches: Sequence[Sequence[str]] | None = None,
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
    combined_grouping_answers_by_unit_id = {
        str(unit_id): dict(answer)
        for unit_id, answer in dict(grouping_answers_by_unit_id or {}).items()
        if str(unit_id).strip() and isinstance(answer, Mapping)
    }
    combined_grouping_answers_by_unit_id.update(validated_answers_by_unit_id)
    no_edits_detected = (
        not validation_errors
        and not validation_metadata.get("error_details")
        and
        int(validation_metadata.get("changed_unit_count") or 0) <= 0
        and not combined_grouping_answers_by_unit_id
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
            validated_answers_by_unit_id=combined_grouping_answers_by_unit_id,
            validation_errors=tuple(validation_errors),
            validation_metadata=dict(validation_metadata),
            transition_metadata={
                "repair_unit_count": len(repair_task_file.get("units") or []),
                "repair_reason": "task_file_contract_violation"
                if not validation_metadata.get("failed_unit_ids")
                else "unit_validation_failure",
            },
        )
    remaining_batch_unit_ids = [
        [
            str(unit_id).strip()
            for unit_id in batch_unit_ids
            if str(unit_id).strip()
        ]
        for batch_unit_ids in (pending_grouping_unit_batches or [])
        if batch_unit_ids
    ]
    if remaining_batch_unit_ids:
        next_batch_unit_ids = remaining_batch_unit_ids[0]
        later_batch_unit_ids = remaining_batch_unit_ids[1:]
        batch_metadata = _coerce_dict(original_task_file.get("grouping_batch"))
        total_batch_count = max(
            int(batch_metadata.get("total_batches") or 0),
            1 + len(remaining_batch_unit_ids),
        )
        current_batch_index = max(int(batch_metadata.get("current_batch_index") or 0), 1)
        max_units_per_batch = max(
            1,
            int(batch_metadata.get("max_units_per_batch") or KNOWLEDGE_GROUP_TASK_MAX_UNITS),
        )
        max_evidence_chars_per_batch = max(
            1,
            int(
                batch_metadata.get("max_evidence_chars_per_batch")
                or KNOWLEDGE_GROUP_TASK_MAX_EVIDENCE_CHARS
            ),
        )
        total_grouping_unit_count = max(
            int(batch_metadata.get("total_grouping_unit_count") or 0),
            len(combined_grouping_answers_by_unit_id) + sum(len(batch) for batch in later_batch_unit_ids),
        )
        next_batch_units, _next_mapping = _collect_knowledge_grouping_units(
            classification_task_file=classification_task_file,
            classification_answers_by_unit_id=classification_answers_by_unit_id,
            unit_to_shard_id=unit_to_shard_id,
            allowed_unit_ids=next_batch_unit_ids,
        )
        next_task_file = _build_knowledge_grouping_task_file_from_units(
            assignment_id=str(original_task_file.get("assignment_id") or ""),
            worker_id=str(original_task_file.get("worker_id") or ""),
            units=next_batch_units,
            batch_index=current_batch_index + 1,
            batch_count=total_batch_count,
            total_grouping_unit_count=total_grouping_unit_count,
            max_units_per_batch=max_units_per_batch,
            max_evidence_chars_per_batch=max_evidence_chars_per_batch,
        )
        return KnowledgeTaskFileTransition(
            status="advance_to_grouping",
            current_stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
            next_stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
            next_task_file=next_task_file,
            validated_answers_by_unit_id=combined_grouping_answers_by_unit_id,
            validation_metadata=dict(validation_metadata),
            transition_metadata={
                "grouping_unit_count": total_grouping_unit_count,
                "grouping_batch_count": total_batch_count,
                "current_grouping_batch_index": current_batch_index + 1,
                "current_grouping_batch_unit_count": len(next_task_file.get("units") or []),
                "pending_grouping_unit_batches": later_batch_unit_ids,
            },
        )
    return KnowledgeTaskFileTransition(
        status="completed_with_grouping",
        current_stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
        final_outputs=combine_knowledge_task_file_outputs(
            classification_task_file=classification_task_file,
            classification_answers_by_unit_id=classification_answers_by_unit_id,
            grouping_answers_by_unit_id=combined_grouping_answers_by_unit_id,
            unit_to_shard_id=unit_to_shard_id,
        ),
        validated_answers_by_unit_id=combined_grouping_answers_by_unit_id,
        validation_metadata=dict(validation_metadata),
        transition_metadata={
            "grouping_batch_count": max(
                int(_coerce_dict(original_task_file.get("grouping_batch")).get("total_batches") or 0),
                1,
            ),
            "current_grouping_batch_index": max(
                int(_coerce_dict(original_task_file.get("grouping_batch")).get("current_batch_index") or 0),
                1,
            ),
        },
    )
