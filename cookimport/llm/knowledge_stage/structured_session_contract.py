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
    detail_parts = [str(prefix).strip() or "validation blocked promotion"]
    if cleaned_errors:
        detail_parts.append("errors=" + ",".join(cleaned_errors))
    if unresolved_block_indices:
        detail_parts.append(
            "unresolved_block_indices="
            + ",".join(str(value) for value in unresolved_block_indices)
        )
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


def knowledge_task_file_to_structured_packet(
    *,
    task_file_payload: Mapping[str, Any],
    packet_kind: str,
    validation_errors: Sequence[str] | None = None,
) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    for unit in task_file_payload.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        evidence = _coerce_dict(unit.get("evidence"))
        block_index = int(evidence.get("block_index") or 0)
        block_payload: dict[str, Any] = {
            "i": block_index,
            "id": str(evidence.get("block_id") or unit.get("owned_id") or block_index),
            "t": str(evidence.get("text") or ""),
        }
        structure = _coerce_dict(evidence.get("structure"))
        if structure.get("heading_level") is not None:
            block_payload["hl"] = int(structure.get("heading_level"))
        if isinstance(structure.get("table_hint"), Mapping):
            block_payload["th"] = dict(structure.get("table_hint"))
        blocks.append(block_payload)
    packet = {
        "schema_version": "knowledge_structured_packet.v1",
        "stage_key": str(task_file_payload.get("stage_key") or ""),
        "packet_kind": str(packet_kind or "initial"),
        "assignment_id": str(task_file_payload.get("assignment_id") or ""),
        "worker_id": str(task_file_payload.get("worker_id") or ""),
        "bid": str(task_file_payload.get("assignment_id") or "knowledge-packet"),
        "b": blocks,
    }
    if isinstance(task_file_payload.get("ontology"), Mapping):
        packet["ontology"] = dict(task_file_payload.get("ontology") or {})
    if isinstance(task_file_payload.get("review_contract"), Mapping):
        packet["review_contract"] = dict(task_file_payload.get("review_contract") or {})
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
    if stage_key == KNOWLEDGE_GROUP_STAGE_KEY:
        response_shape = (
            '{"rows":[{"block_index":12,"group_key":"heat-control","topic_label":"Heat control"}]}'
        )
        task_note = (
            "Group every knowledge block in this packet. Cover each block exactly once.\n"
            "Blocks with the same idea should share the same `group_key` and `topic_label`.\n"
        )
    else:
        response_shape = (
            '{"rows":[{"block_index":12,"category":"knowledge","grounding":{"tag_keys":[],"category_keys":["techniques"],"proposed_tags":[{"key":"heat-control","display_name":"Heat control","category_key":"techniques"}]}}]}'
        )
        task_note = (
            "Classify each owned block as `knowledge` or `other` and include `grounding`.\n"
            "Cover every block in this packet exactly once.\n"
        )
    return (
        "Return JSON only.\n\n"
        + task_note
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
        decision_rows = parsed.get("block_decisions")
    if not isinstance(decision_rows, list):
        return None, ("rows_missing_or_not_a_list",), {}
    unit_id_by_block_index = {
        int(_coerce_dict(unit.get("evidence")).get("block_index") or 0): str(
            unit.get("unit_id") or ""
        ).strip()
        for unit in (original_task_file.get("units") or [])
        if isinstance(unit, Mapping)
    }
    answers_by_unit_id: dict[str, dict[str, Any]] = {}
    for row in decision_rows:
        if not isinstance(row, Mapping):
            return None, ("row_not_a_json_object",), {}
        if row.get("block_index") is None:
            return None, ("block_index_missing",), {}
        block_index = int(row.get("block_index"))
        unit_id = unit_id_by_block_index.get(block_index)
        if not unit_id:
            continue
        answers_by_unit_id[unit_id] = {
            "category": str(row.get("category") or "").strip(),
            "grounding": dict(row.get("grounding") or _blank_grounding_payload()),
        }
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
    return edited, (), {}


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
    answers_by_block_index: dict[int, dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                return None, ("row_not_a_json_object",), {}
            if row.get("block_index") is None:
                return None, ("block_index_missing",), {}
            answers_by_block_index[int(row.get("block_index"))] = {
                "group_key": str(row.get("group_key") or "").strip(),
                "topic_label": str(row.get("topic_label") or "").strip(),
            }
    elif isinstance(parsed.get("idea_groups"), list):
        for group in parsed.get("idea_groups") or []:
            if not isinstance(group, Mapping):
                continue
            group_key = str(group.get("group_id") or group.get("group_key") or "").strip()
            topic_label = str(group.get("topic_label") or "").strip()
            for block_index in group.get("block_indices") or []:
                try:
                    normalized_block_index = int(block_index)
                except (TypeError, ValueError):
                    continue
                answers_by_block_index[normalized_block_index] = {
                    "group_key": group_key,
                    "topic_label": topic_label,
                }
    else:
        return None, ("rows_missing_or_not_a_list",), {}
    edited = dict(original_task_file)
    edited["units"] = []
    for unit in original_task_file.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_dict = dict(unit)
        evidence = _coerce_dict(unit_dict.get("evidence"))
        block_index = int(evidence.get("block_index") or 0)
        if block_index in answers_by_block_index:
            unit_dict["answer"] = answers_by_block_index[block_index]
        edited["units"].append(unit_dict)
    return edited, (), {}


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
