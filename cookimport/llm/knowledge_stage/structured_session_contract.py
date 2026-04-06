from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..knowledge_tag_catalog import empty_grounding_payload
from .task_file_contracts import (
    KNOWLEDGE_CLASSIFY_STAGE_KEY,
    KNOWLEDGE_GROUP_STAGE_KEY,
)


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def render_validation_reason_detail(
    *,
    prefix: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
) -> str:
    cleaned_errors = [
        str(error).strip() for error in validation_errors if str(error).strip()
    ]
    parse_error = str(validation_metadata.get("parse_error") or "").strip()
    unresolved_block_indices = [
        int(value)
        for value in (validation_metadata.get("unresolved_block_indices") or [])
        if value is not None
    ]
    missing_block_indices = [
        int(value)
        for value in (validation_metadata.get("missing_block_indices") or [])
        if value is not None
    ]
    unexpected_block_indices = [
        int(value)
        for value in (validation_metadata.get("unexpected_block_indices") or [])
        if value is not None
    ]
    duplicate_block_indices = [
        int(value)
        for value in (validation_metadata.get("duplicate_block_indices") or [])
        if value is not None
    ]
    missing_row_ids = [
        str(value).strip()
        for value in (validation_metadata.get("missing_row_ids") or [])
        if str(value).strip()
    ]
    unknown_row_ids = [
        str(value).strip()
        for value in (validation_metadata.get("unknown_row_ids") or [])
        if str(value).strip()
    ]
    duplicate_row_ids = [
        str(value).strip()
        for value in (validation_metadata.get("duplicate_row_ids") or [])
        if str(value).strip()
    ]
    detail_parts = [str(prefix).strip() or "validation blocked promotion"]
    if cleaned_errors:
        detail_parts.append("errors=" + ",".join(cleaned_errors))
    if unresolved_block_indices:
        detail_parts.append(
            "unresolved_block_indices="
            + ",".join(str(value) for value in unresolved_block_indices)
        )
    if missing_block_indices:
        detail_parts.append(
            "missing_block_indices="
            + ",".join(str(value) for value in missing_block_indices)
        )
    if unexpected_block_indices:
        detail_parts.append(
            "unexpected_block_indices="
            + ",".join(str(value) for value in unexpected_block_indices)
        )
    if duplicate_block_indices:
        detail_parts.append(
            "duplicate_block_indices="
            + ",".join(str(value) for value in duplicate_block_indices)
        )
    if missing_row_ids:
        detail_parts.append("missing_row_ids=" + ",".join(missing_row_ids))
    if unknown_row_ids:
        detail_parts.append("unknown_row_ids=" + ",".join(unknown_row_ids))
    if duplicate_row_ids:
        detail_parts.append("duplicate_row_ids=" + ",".join(duplicate_row_ids))
    if parse_error:
        detail_parts.append(f"parse_error={parse_error}")
    return "; ".join(part for part in detail_parts if part)


def write_knowledge_task_file_snapshot(
    *,
    worker_root: Path,
    step_name: str,
    suffix: str,
    payload: Mapping[str, Any],
) -> None:
    snapshot_path = worker_root / f"task_{step_name}.{suffix}.json"
    snapshot_path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def apply_knowledge_same_session_row_metadata(
    *,
    row: dict[str, Any],
    initial_task_file: Mapping[str, Any],
    state_payload: Mapping[str, Any],
) -> None:
    classification_validation_count = int(
        state_payload.get("classification_validation_count") or 0
    )
    grouping_validation_count = int(state_payload.get("grouping_validation_count") or 0)
    same_session_repair_rewrite_count = int(
        state_payload.get("same_session_repair_rewrite_count") or 0
    )
    row["knowledge_same_session"] = True
    row["knowledge_same_session_status"] = (
        str(state_payload.get("final_status") or "").strip() or None
    )
    row["same_session_transition_count"] = int(
        state_payload.get("same_session_transition_count") or 0
    )
    row["classification_validation_count"] = classification_validation_count
    row["grouping_validation_count"] = grouping_validation_count
    row["same_session_repair_rewrite_count"] = same_session_repair_rewrite_count
    row["grouping_transition_count"] = int(
        state_payload.get("grouping_transition_count") or 0
    )
    row["classification_step_count"] = 1 if classification_validation_count > 0 else 0
    row["grouping_step_count"] = grouping_validation_count
    row["workspace_packet_count"] = (
        classification_validation_count + grouping_validation_count
    )
    row["workspace_repair_packet_count"] = same_session_repair_rewrite_count
    row["owned_row_count"] = int(len(initial_task_file.get("units") or []))
    row["classification_owned_row_count"] = int(len(initial_task_file.get("units") or []))
    row["grouping_owned_row_count"] = int(state_payload.get("grouping_unit_count") or 0)
    row["final_output_shard_count"] = int(state_payload.get("final_output_shard_count") or 0)


def knowledge_same_session_grounding_gate_metadata_by_shard(
    *,
    initial_task_file: Mapping[str, Any],
    state_payload: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    unit_to_shard_id = {
        str(unit_id): str(shard_id)
        for unit_id, shard_id in dict(state_payload.get("unit_to_shard_id") or {}).items()
        if str(unit_id).strip() and str(shard_id).strip()
    }
    unit_to_block_index = {
        str(unit.get("unit_id") or "").strip(): int(
            _coerce_dict(unit.get("evidence")).get("block_index") or 0
        )
        for unit in (initial_task_file.get("units") or [])
        if isinstance(unit, Mapping) and str(unit.get("unit_id") or "").strip()
    }
    shard_metadata: dict[str, dict[str, Any]] = {}
    for transition_row in state_payload.get("transition_history") or []:
        transition = _coerce_dict(transition_row)
        if (
            str(transition.get("current_stage_key") or "").strip()
            != KNOWLEDGE_CLASSIFY_STAGE_KEY
        ):
            continue
        validation_metadata = _coerce_dict(transition.get("validation_metadata"))
        for raw_detail in validation_metadata.get("grounding_gate_demotion_details") or []:
            detail = _coerce_dict(raw_detail)
            unit_id = str(detail.get("unit_id") or "").strip()
            shard_id = str(unit_to_shard_id.get(unit_id) or "").strip()
            if not unit_id or not shard_id:
                continue
            reason = str(detail.get("reason") or "").strip() or "missing_grounding"
            block_index = int(
                detail.get("block_index")
                if detail.get("block_index") is not None
                else unit_to_block_index.get(unit_id) or 0
            )
            shard_row = shard_metadata.setdefault(
                shard_id,
                {
                    "grounding_gate_demotion_details": [],
                    "grounding_gate_demoted_unit_ids": set(),
                    "grounding_gate_demoted_block_indices": set(),
                    "grounding_gate_demotion_reason_counts": {},
                },
            )
            shard_row["grounding_gate_demotion_details"].append(
                {
                    "unit_id": unit_id,
                    "block_index": block_index,
                    "reason": reason,
                }
            )
            shard_row["grounding_gate_demoted_unit_ids"].add(unit_id)
            shard_row["grounding_gate_demoted_block_indices"].add(block_index)
            shard_row["grounding_gate_demotion_reason_counts"][reason] = (
                int(shard_row["grounding_gate_demotion_reason_counts"].get(reason) or 0)
                + 1
            )
    finalized: dict[str, dict[str, Any]] = {}
    for shard_id, metadata in shard_metadata.items():
        reason_counts = dict(metadata.get("grounding_gate_demotion_reason_counts") or {})
        finalized[shard_id] = {
            "grounding_gate_demotion_details": list(
                metadata.get("grounding_gate_demotion_details") or []
            ),
            "grounding_gate_demoted_unit_ids": sorted(
                str(unit_id)
                for unit_id in (metadata.get("grounding_gate_demoted_unit_ids") or set())
            ),
            "grounding_gate_demoted_block_indices": sorted(
                int(block_index)
                for block_index in (
                    metadata.get("grounding_gate_demoted_block_indices") or set()
                )
            ),
            "grounding_gate_demotion_reason_counts": dict(sorted(reason_counts.items())),
            "grounding_gate_demoted_block_count": sum(reason_counts.values()),
            "grounding_gate_demoted_after_invalid_grounding_drop_count": int(
                reason_counts.get("invalid_grounding_dropped_to_empty") or 0
            ),
            "grounding_gate_demoted_for_category_only_count": int(
                reason_counts.get("category_only_grounding") or 0
            ),
        }
    return finalized


def _knowledge_local_row_id(index: int) -> str:
    return f"r{index + 1:02d}"


def _knowledge_local_row_maps(
    original_task_file: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, int], list[str]]:
    row_id_by_unit_id: dict[str, str] = {}
    unit_id_by_row_id: dict[str, str] = {}
    block_index_by_unit_id: dict[str, int] = {}
    ordered_row_ids: list[str] = []
    for index, unit in enumerate(original_task_file.get("units") or []):
        if not isinstance(unit, Mapping):
            continue
        unit_id = str(unit.get("unit_id") or "").strip()
        if not unit_id:
            continue
        row_id = _knowledge_local_row_id(index)
        row_id_by_unit_id[unit_id] = row_id
        unit_id_by_row_id[row_id] = unit_id
        block_index_by_unit_id[unit_id] = int(
            _coerce_dict(unit.get("evidence")).get("block_index") or 0
        )
        ordered_row_ids.append(row_id)
    return row_id_by_unit_id, unit_id_by_row_id, block_index_by_unit_id, ordered_row_ids


def knowledge_task_file_to_structured_packet(
    *,
    task_file_payload: Mapping[str, Any],
    packet_kind: str,
    validation_errors: Sequence[str] | None = None,
) -> dict[str, Any]:
    stage_key = str(task_file_payload.get("stage_key") or "").strip()
    rows: list[dict[str, Any]] = []
    for index, unit in enumerate(task_file_payload.get("units") or []):
        if not isinstance(unit, Mapping):
            continue
        evidence = _coerce_dict(unit.get("evidence"))
        row_payload: dict[str, Any] = {
            "row_id": _knowledge_local_row_id(index),
            "text": str(evidence.get("text") or ""),
        }
        structure = _coerce_dict(evidence.get("structure"))
        if structure.get("heading_level") is not None:
            row_payload["heading_level"] = int(structure.get("heading_level"))
        if isinstance(structure.get("table_hint"), Mapping) and structure.get("table_hint"):
            row_payload["table_hint"] = dict(structure.get("table_hint"))
        context_before = str(evidence.get("context_before") or "").strip()
        if context_before:
            row_payload["context_before"] = context_before
        context_after = str(evidence.get("context_after") or "").strip()
        if context_after:
            row_payload["context_after"] = context_after
        candidate_tag_keys = [
            str(value).strip()
            for value in (evidence.get("candidate_tag_keys") or [])
            if str(value).strip()
        ][:4]
        if candidate_tag_keys:
            row_payload["candidate_tag_keys"] = candidate_tag_keys
        rows.append(row_payload)
    packet = {
        "schema_version": "knowledge_structured_packet.v1",
        "stage_key": stage_key,
        "packet_kind": str(packet_kind or "initial"),
        "assignment_id": str(task_file_payload.get("assignment_id") or ""),
        "worker_id": str(task_file_payload.get("worker_id") or ""),
        "bid": str(task_file_payload.get("assignment_id") or "knowledge-packet"),
        "rows": rows,
    }
    if stage_key == KNOWLEDGE_CLASSIFY_STAGE_KEY and isinstance(
        task_file_payload.get("ontology"), Mapping
    ):
        categories = [
            {
                "key": str(category.get("key") or "").strip(),
                "display_name": str(category.get("display_name") or "").strip(),
            }
            for category in (task_file_payload.get("ontology") or {}).get("categories") or []
            if isinstance(category, Mapping) and str(category.get("key") or "").strip()
        ]
        if categories:
            packet["categories"] = categories
    if isinstance(task_file_payload.get("grouping_batch"), Mapping):
        packet["grouping_batch"] = dict(task_file_payload.get("grouping_batch") or {})
    if validation_errors:
        packet["validation_errors"] = [
            str(error).strip() for error in validation_errors if str(error).strip()
        ]
    return packet


def build_knowledge_structured_prompt(
    *,
    task_file_payload: Mapping[str, Any],
    packet: Mapping[str, Any],
) -> str:
    stage_key = str(task_file_payload.get("stage_key") or "").strip()
    packet_rows = [
        dict(row) for row in (packet.get("rows") or []) if isinstance(row, Mapping)
    ]
    has_context = any(
        str(row.get("context_before") or "").strip()
        or str(row.get("context_after") or "").strip()
        for row in packet_rows
    )
    if stage_key == KNOWLEDGE_GROUP_STAGE_KEY:
        response_shape = (
            '{"rows":[{"row_id":"r01","group_key":"heat-control","topic_label":"Heat control"}]}'
        )
        task_note = (
            "Review the ordered knowledge rows and answer every `row_id` exactly once.\n"
            "Rows about the same idea should share the same `group_key` and `topic_label`.\n"
        )
    else:
        response_shape = (
            '{"rows":[{"row_id":"r01","category":"knowledge","grounding":{"tag_keys":[],"category_keys":["techniques"],"proposed_tags":[{"key":"heat-control","display_name":"Heat control","category_key":"techniques"}]}}]}'
        )
        task_note = (
            "Review the ordered knowledge rows and answer every `row_id` exactly once.\n"
            "Classify each row as `knowledge` or `other` and include `grounding`.\n"
            "If `category` is `knowledge`, grounding must include at least one existing `tag_key` or one proposed tag.\n"
            "`category_keys` may support that grounding, but category-only grounding is invalid and will be returned for repair.\n"
            "If you cannot name a real existing tag fit or a concrete proposed tag, return `other` with empty grounding.\n"
            "Treat candidate tags, candidate categories, heading hints, and row order as weak hints only.\n"
        )
    context_note = (
        "Use nearby context only when the row includes `context_before` or `context_after`, and only to disambiguate that row.\n"
        if has_context
        else ""
    )
    return (
        "Return JSON only.\n\n"
        + task_note
        + context_note
        + "Do not include commentary, markdown, or extra keys.\n"
        + "Response shape:\n"
        + response_shape
        + "\n\nPacket JSON:\n"
        + json.dumps(dict(packet), indent=2, sort_keys=True)
        + "\n"
    )


def _blank_grounding_payload() -> dict[str, Any]:
    return {
        "tag_keys": [],
        "category_keys": [],
        "proposed_tags": [],
    }


def _knowledge_unit_maps(
    original_task_file: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, int], list[str]]:
    return _knowledge_local_row_maps(original_task_file)


def _response_contract_metadata(
    *,
    original_task_file: Mapping[str, Any],
    missing_unit_ids: Sequence[str],
    unknown_row_ids: Sequence[str],
    duplicate_row_ids: Sequence[str],
) -> tuple[tuple[str, ...], dict[str, Any]]:
    (
        row_id_by_unit_id,
        unit_id_by_row_id,
        block_index_by_unit_id,
        owned_row_ids,
    ) = _knowledge_unit_maps(original_task_file)
    missing_unit_id_set = {
        str(unit_id).strip()
        for unit_id in missing_unit_ids
        if str(unit_id).strip()
    }
    missing_row_ids = [
        row_id_by_unit_id[unit_id]
        for unit_id in sorted(missing_unit_id_set)
        if unit_id in row_id_by_unit_id
    ]
    missing_block_indices = [
        int(block_index_by_unit_id[unit_id])
        for unit_id in sorted(missing_unit_id_set)
        if unit_id in block_index_by_unit_id
    ]
    duplicate_row_id_list = sorted(
        {str(value).strip() for value in duplicate_row_ids if str(value).strip()}
    )
    duplicate_unit_ids = sorted(
        {
            str(unit_id_by_row_id.get(row_id) or "").strip()
            for row_id in duplicate_row_id_list
            if str(unit_id_by_row_id.get(row_id) or "").strip()
        }
    )
    duplicate_block_indices = [
        int(block_index_by_unit_id[unit_id])
        for unit_id in duplicate_unit_ids
        if unit_id in block_index_by_unit_id
    ]
    unknown_row_id_list = sorted(
        {str(value).strip() for value in unknown_row_ids if str(value).strip()}
    )
    response_contract_errors: list[str] = []
    error_details: list[dict[str, Any]] = []
    failed_unit_ids = sorted(missing_unit_id_set | set(duplicate_unit_ids))
    if missing_row_ids:
        response_contract_errors.append("knowledge_missing_response_rows")
        for unit_id in sorted(missing_unit_id_set):
            row_id = row_id_by_unit_id.get(unit_id)
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer",
                    "code": "knowledge_missing_response_row",
                    "message": "response did not return a row for this owned row_id",
                    "row_id": row_id,
                    "block_index": block_index_by_unit_id.get(unit_id),
                }
            )
    if duplicate_row_id_list:
        response_contract_errors.append("knowledge_duplicate_row_ids")
        for row_id in duplicate_row_id_list:
            unit_id = str(unit_id_by_row_id.get(row_id) or "").strip()
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer" if unit_id else "/response/rows/*/row_id",
                    "code": "knowledge_duplicate_row_id",
                    "message": "response returned more than one row for this row_id",
                    "row_id": row_id,
                    "block_index": block_index_by_unit_id.get(unit_id),
                }
            )
    if unknown_row_id_list:
        response_contract_errors.append("knowledge_unknown_row_ids")
        if not failed_unit_ids:
            failed_unit_ids = [
                unit_id_by_row_id[row_id]
                for row_id in owned_row_ids
                if row_id in unit_id_by_row_id
            ]
        for row_id in unknown_row_id_list:
            error_details.append(
                {
                    "path": "/response/rows/*/row_id",
                    "code": "knowledge_unknown_row_id",
                    "message": "response referenced a row_id that is not owned by this packet",
                    "row_id": row_id,
                }
            )
    if not response_contract_errors:
        return (), {}
    return (
        tuple(response_contract_errors),
        {
            "failed_unit_ids": failed_unit_ids,
            "unresolved_block_indices": sorted(
                set(missing_block_indices) | set(duplicate_block_indices)
            ),
            "missing_block_indices": missing_block_indices,
            "missing_row_ids": missing_row_ids,
            "unknown_row_ids": unknown_row_id_list,
            "duplicate_row_ids": duplicate_row_id_list,
            "error_details": error_details,
        },
    )


def build_knowledge_edited_task_file_from_classification_response(
    *,
    original_task_file: Mapping[str, Any],
    response_text: str | None,
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any]]:
    cleaned = str(response_text or "").strip()
    if not cleaned:
        return None, ("missing_output_file",), {}
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, ("response_json_invalid",), {"parse_error": str(exc)}
    if not isinstance(parsed, Mapping):
        return None, ("response_not_json_object",), {"response_type": type(parsed).__name__}
    decision_rows = parsed.get("rows")
    if not isinstance(decision_rows, list):
        return None, ("rows_missing_or_not_a_list",), {}
    (
        _row_id_by_unit_id,
        unit_id_by_row_id,
        _block_index_by_unit_id,
        owned_row_ids,
    ) = _knowledge_unit_maps(original_task_file)
    answers_by_unit_id: dict[str, dict[str, Any]] = {}
    seen_row_ids: set[str] = set()
    duplicate_row_ids: set[str] = set()
    unknown_row_ids: set[str] = set()
    for row in decision_rows:
        if not isinstance(row, Mapping):
            return None, ("row_not_a_json_object",), {}
        row_id = str(row.get("row_id") or "").strip()
        if not row_id:
            return None, ("row_id_missing",), {}
        if row_id in seen_row_ids:
            duplicate_row_ids.add(row_id)
            continue
        seen_row_ids.add(row_id)
        unit_id = unit_id_by_row_id.get(row_id)
        if not unit_id:
            unknown_row_ids.add(row_id)
            continue
        answers_by_unit_id[unit_id] = {
            "category": str(row.get("category") or "").strip(),
            "grounding": dict(row.get("grounding") or _blank_grounding_payload()),
        }
    missing_unit_ids = [
        unit_id_by_row_id[row_id]
        for row_id in owned_row_ids
        if row_id in unit_id_by_row_id and unit_id_by_row_id[row_id] not in answers_by_unit_id
    ]
    response_contract_errors, response_contract_metadata = _response_contract_metadata(
        original_task_file=original_task_file,
        missing_unit_ids=missing_unit_ids,
        unknown_row_ids=sorted(unknown_row_ids),
        duplicate_row_ids=sorted(duplicate_row_ids),
    )
    edited = dict(original_task_file)
    edited["units"] = []
    for unit in original_task_file.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_dict = dict(unit)
        unit_id = str(unit_dict.get("unit_id") or "").strip()
        if unit_id in answers_by_unit_id:
            unit_dict["answer"] = answers_by_unit_id[unit_id]
        edited["units"].append(unit_dict)
    return edited, response_contract_errors, response_contract_metadata


def build_knowledge_edited_task_file_from_grouping_response(
    *,
    original_task_file: Mapping[str, Any],
    response_text: str | None,
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any]]:
    cleaned = str(response_text or "").strip()
    if not cleaned:
        return None, ("missing_output_file",), {}
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, ("response_json_invalid",), {"parse_error": str(exc)}
    if not isinstance(parsed, Mapping):
        return None, ("response_not_json_object",), {"response_type": type(parsed).__name__}
    rows = parsed.get("rows")
    (
        _row_id_by_unit_id,
        unit_id_by_row_id,
        _block_index_by_unit_id,
        owned_row_ids,
    ) = _knowledge_unit_maps(original_task_file)
    answers_by_unit_id: dict[str, dict[str, Any]] = {}
    seen_row_ids: set[str] = set()
    duplicate_row_ids: set[str] = set()
    unknown_row_ids: set[str] = set()
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                return None, ("row_not_a_json_object",), {}
            row_id = str(row.get("row_id") or "").strip()
            if not row_id:
                return None, ("row_id_missing",), {}
            if row_id in seen_row_ids:
                duplicate_row_ids.add(row_id)
                continue
            seen_row_ids.add(row_id)
            unit_id = unit_id_by_row_id.get(row_id)
            if not unit_id:
                unknown_row_ids.add(row_id)
                continue
            answers_by_unit_id[unit_id] = {
                "group_key": str(
                    row.get("group_key") or row.get("group_index") or ""
                ).strip(),
                "topic_label": str(row.get("topic_label") or "").strip(),
            }
    else:
        return None, ("rows_missing_or_not_a_list",), {}
    missing_unit_ids = [
        unit_id_by_row_id[row_id]
        for row_id in owned_row_ids
        if row_id in unit_id_by_row_id and unit_id_by_row_id[row_id] not in answers_by_unit_id
    ]
    response_contract_errors, response_contract_metadata = _response_contract_metadata(
        original_task_file=original_task_file,
        missing_unit_ids=missing_unit_ids,
        unknown_row_ids=sorted(unknown_row_ids),
        duplicate_row_ids=sorted(duplicate_row_ids),
    )
    edited = dict(original_task_file)
    edited["units"] = []
    for unit in original_task_file.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_dict = dict(unit)
        unit_id = str(unit_dict.get("unit_id") or "").strip()
        if unit_id in answers_by_unit_id:
            unit_dict["answer"] = answers_by_unit_id[unit_id]
        edited["units"].append(unit_dict)
    return edited, response_contract_errors, response_contract_metadata


def knowledge_failed_unit_ids(
    *,
    task_file_payload: Mapping[str, Any],
    validation_metadata: Mapping[str, Any],
) -> list[str]:
    failed_unit_ids = [
        str(unit_id).strip()
        for unit_id in (validation_metadata.get("failed_unit_ids") or [])
        if str(unit_id).strip()
    ]
    if failed_unit_ids:
        return failed_unit_ids
    return [
        str(unit.get("unit_id") or "").strip()
        for unit in (task_file_payload.get("units") or [])
        if isinstance(unit, Mapping) and str(unit.get("unit_id") or "").strip()
    ]


def knowledge_merge_answers(
    existing: Mapping[str, Mapping[str, Any]] | None,
    new_answers: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    merged = {
        str(unit_id): dict(answer)
        for unit_id, answer in dict(existing or {}).items()
        if str(unit_id).strip() and isinstance(answer, Mapping)
    }
    for unit_id, answer in dict(new_answers or {}).items():
        if not str(unit_id).strip() or not isinstance(answer, Mapping):
            continue
        merged[str(unit_id)] = dict(answer)
    return merged


def apply_answers_to_task_file(
    *,
    original_task_file: Mapping[str, Any],
    answers_by_unit_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    edited = dict(original_task_file)
    edited["units"] = []
    for unit in original_task_file.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_dict = dict(unit)
        unit_id = str(unit_dict.get("unit_id") or "").strip()
        if unit_id in answers_by_unit_id:
            unit_dict["answer"] = dict(answers_by_unit_id[unit_id])
        edited["units"].append(unit_dict)
    return edited
