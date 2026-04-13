from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .task_file_contracts import (
    KNOWLEDGE_CLASSIFY_STAGE_KEY,
    KNOWLEDGE_GROUP_STAGE_KEY,
    collect_knowledge_resolution_metadata_by_shard,
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
    classification_repair_rewrite_count = 0
    grouping_repair_rewrite_count = 0
    for transition_row in state_payload.get("transition_history") or ():
        if not isinstance(transition_row, Mapping):
            continue
        if str(transition_row.get("status") or "").strip() != "repair_required":
            continue
        current_stage_key = str(transition_row.get("current_stage_key") or "").strip()
        if current_stage_key == "nonrecipe_classify":
            classification_repair_rewrite_count += 1
        elif current_stage_key == "knowledge_group":
            grouping_repair_rewrite_count += 1
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
    row["classification_same_session_repair_rewrite_count"] = (
        classification_repair_rewrite_count
    )
    row["grouping_same_session_repair_rewrite_count"] = grouping_repair_rewrite_count
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


def knowledge_same_session_resolution_metadata_by_shard(
    *,
    initial_task_file: Mapping[str, Any],
    state_payload: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    return collect_knowledge_resolution_metadata_by_shard(
        classification_task_file=initial_task_file,
        classification_answers_by_unit_id=dict(
            state_payload.get("classification_answers_by_unit_id") or {}
        ),
        grouping_answers_by_unit_id=dict(state_payload.get("grouping_answers_by_unit_id") or {}),
        unit_to_shard_id=dict(state_payload.get("unit_to_shard_id") or {}),
    )


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


def _compact_knowledge_packet_row(
    *,
    row_id: str,
    block_index: int,
    text: str,
) -> str:
    return f"{row_id} | {int(block_index)} | {str(text or '')}"


def _compact_knowledge_context_row(
    *,
    row_id: str,
    block_index: int | None,
    text: str,
) -> str:
    if block_index is None:
        return f"{row_id} | {str(text or '')}"
    return f"{row_id} | {int(block_index)} | {str(text or '')}"


def _compact_knowledge_row_facts(
    *,
    row_id: str,
    classification_category: str,
) -> str:
    parts = [f"{row_id} | classification={classification_category}"]
    return " | ".join(parts)


def _compact_repair_error_detail(detail: Mapping[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in ("code", "message", "path", "row_id", "block_index"):
        value = detail.get(key)
        if value in (None, "", [], {}):
            continue
        compact[str(key)] = value
    return compact


def _compact_repair_feedback_row(
    *,
    row_id: str,
    unit: Mapping[str, Any],
) -> dict[str, Any] | None:
    previous_answer = _coerce_dict(unit.get("previous_answer"))
    validation_feedback = _coerce_dict(unit.get("validation_feedback"))
    validation_errors = [
        str(error).strip()
        for error in (validation_feedback.get("validation_errors") or [])
        if str(error).strip()
    ]
    error_details = [
        _compact_repair_error_detail(detail)
        for detail in (validation_feedback.get("error_details") or [])
        if isinstance(detail, Mapping)
    ]
    error_details = [detail for detail in error_details if detail]
    if not previous_answer and not validation_errors and not error_details:
        return None
    payload: dict[str, Any] = {"row_id": row_id}
    if previous_answer:
        payload["previous_answer"] = previous_answer
    if validation_errors:
        payload["validation_errors"] = validation_errors
    if error_details:
        payload["error_details"] = error_details
    return payload


def _compact_repair_validation_summary(
    task_file_payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    validation_errors = [
        str(error).strip()
        for error in (task_file_payload.get("repair_validation_errors") or [])
        if str(error).strip()
    ]
    validation_metadata = _coerce_dict(task_file_payload.get("repair_validation_metadata"))
    summary: dict[str, Any] = {}
    if validation_errors:
        summary["validation_errors"] = validation_errors
    for key in (
        "expected_label_count",
        "returned_label_count",
        "unresolved_block_indices",
        "missing_block_indices",
        "missing_row_ids",
        "unknown_row_ids",
        "duplicate_row_ids",
        "knowledge_blocks_missing_group",
        "knowledge_group_grounding_mismatch_blocks",
    ):
        value = validation_metadata.get(key)
        if value in (None, "", [], {}):
            continue
        summary[str(key)] = value
    error_details = [
        _compact_repair_error_detail(detail)
        for detail in (validation_metadata.get("error_details") or [])
        if isinstance(detail, Mapping)
    ]
    error_details = [detail for detail in error_details if detail]
    if error_details:
        summary["error_details"] = error_details
    return summary or None


def knowledge_task_file_to_structured_packet(
    *,
    task_file_payload: Mapping[str, Any],
    packet_kind: str,
    validation_errors: Sequence[str] | None = None,
) -> dict[str, Any]:
    stage_key = str(task_file_payload.get("stage_key") or "").strip()
    repair_mode = str(task_file_payload.get("mode") or "").strip() == "repair"
    rows: list[str] = []
    context_before_rows: list[str] = []
    context_after_rows: list[str] = []
    row_facts: list[str] = []
    repair_feedback_rows: list[dict[str, Any]] = []
    for index, unit in enumerate(task_file_payload.get("units") or []):
        if not isinstance(unit, Mapping):
            continue
        evidence = _coerce_dict(unit.get("evidence"))
        row_id = _knowledge_local_row_id(index)
        row_text = str(evidence.get("text") or "")
        block_index = int(evidence.get("block_index") or 0)
        rows.append(
            _compact_knowledge_packet_row(
                row_id=row_id,
                block_index=block_index,
                text=row_text,
            )
        )
        context_before = str(evidence.get("context_before") or "").strip()
        if context_before:
            context_before_rows.append(
                _compact_knowledge_context_row(
                    row_id=row_id,
                    block_index=(
                        int(evidence.get("context_before_block_index"))
                        if evidence.get("context_before_block_index") is not None
                        else None
                    ),
                    text=context_before,
                )
            )
        context_after = str(evidence.get("context_after") or "").strip()
        if context_after:
            context_after_rows.append(
                _compact_knowledge_context_row(
                    row_id=row_id,
                    block_index=(
                        int(evidence.get("context_after_block_index"))
                        if evidence.get("context_after_block_index") is not None
                        else None
                    ),
                    text=context_after,
                )
            )
        if stage_key == KNOWLEDGE_GROUP_STAGE_KEY:
            classification = _coerce_dict(unit.get("classification"))
            classification_category = str(
                classification.get("category") or ""
            ).strip()
            if classification_category:
                row_facts.append(
                    _compact_knowledge_row_facts(
                        row_id=row_id,
                        classification_category=classification_category,
                    )
                )
        if repair_mode:
            repair_feedback_row = _compact_repair_feedback_row(
                row_id=row_id,
                unit=unit,
            )
            if repair_feedback_row is not None:
                repair_feedback_rows.append(repair_feedback_row)
    packet = {
        "schema_version": "knowledge_structured_packet.v2",
        "stage_key": stage_key,
        "packet_kind": str(packet_kind or "initial"),
        "assignment_id": str(task_file_payload.get("assignment_id") or ""),
        "worker_id": str(task_file_payload.get("worker_id") or ""),
        "bid": str(task_file_payload.get("assignment_id") or "knowledge-packet"),
        "rows": rows,
    }
    if context_before_rows:
        packet["context_before_rows"] = context_before_rows
    if context_after_rows:
        packet["context_after_rows"] = context_after_rows
    if row_facts:
        packet["row_facts"] = row_facts
    if isinstance(task_file_payload.get("ontology"), Mapping):
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
        tags = [
            {
                "key": str(tag.get("key") or "").strip(),
                "display_name": str(tag.get("display_name") or "").strip(),
                "category_key": str(tag.get("category_key") or "").strip(),
            }
            for tag in (task_file_payload.get("ontology") or {}).get("tags") or []
            if isinstance(tag, Mapping) and str(tag.get("key") or "").strip()
        ]
        if tags:
            packet["tags"] = tags
    if isinstance(task_file_payload.get("grouping_batch"), Mapping):
        packet["grouping_batch"] = dict(task_file_payload.get("grouping_batch") or {})
    if validation_errors:
        packet["validation_errors"] = [
            str(error).strip() for error in validation_errors if str(error).strip()
        ]
    if repair_feedback_rows:
        packet["repair_feedback_rows"] = repair_feedback_rows
    repair_validation_summary = _compact_repair_validation_summary(task_file_payload)
    if repair_validation_summary is not None:
        packet["repair_validation_summary"] = repair_validation_summary
    return packet


def build_knowledge_structured_prompt(
    *,
    task_file_payload: Mapping[str, Any],
    packet: Mapping[str, Any],
) -> str:
    stage_key = str(task_file_payload.get("stage_key") or "").strip()
    repair_mode = str(task_file_payload.get("mode") or "").strip() == "repair"
    row_count = len([row for row in (packet.get("rows") or []) if isinstance(row, str)])
    has_context = bool(packet.get("context_before_rows") or packet.get("context_after_rows"))
    if stage_key == KNOWLEDGE_GROUP_STAGE_KEY:
        response_shape = (
            '{"groups":[{"group_id":"g01","start_row_id":"r01","end_row_id":"r02","topic_label":"Heat control","grounding":{"tag_keys":["heat-control"],"category_keys":["techniques"],"proposed_tags":[]},"why_no_existing_tag":null,"retrieval_query":null}]}'
        )
        task_note = (
            "Review the ordered kept knowledge rows and partition them into contiguous reading-order groups.\n"
            "The packet `rows` array is ordered and authoritative; each row is rendered as `rXX | block_index | text`.\n"
            "This is a split-and-tag pass: choose the group boundaries with the tag story in mind.\n"
            "Every owned row in `rows` already survived the binary review and must belong to exactly one contiguous group.\n"
            "Return one `groups` array. Each group claims an inclusive span with `start_row_id` and `end_row_id`.\n"
            "The groups must cover every owned row exactly once, in order, with no gaps and no overlap.\n"
            "Each group must carry one `group_id`, one `topic_label`, and one shared `grounding` story for that whole span.\n"
            "If nearby rows need different tags, split them into different groups instead of mixing one vague story across them.\n"
            "When present, `row_facts` gives factual row metadata in compact `rXX | key=value` form.\n"
            "Use existing `tags` first whenever they fit cleanly.\n"
            "If no existing tag fits, you may use `grounding.proposed_tags`, but proposed tags must be strong standalone retrieval handles and must include both `why_no_existing_tag` and `retrieval_query`.\n"
            "When you propose a new tag, its `category_key` must be chosen from the packet `categories` list.\n"
            "Prefer concrete kitchen vocabulary rooted in the packet ontology, such as techniques, ingredients, storage, or equipment.\n"
            "Reject broad chapter-theme, editorial, or pedagogy-summary labels. If the only tag story that comes to mind is vague or bookish, split the rows differently or choose a better existing tag.\n"
            "Keep each proposed tag key as a normalized slug like `rendering-fat`, not prose.\n"
            "Do not answer this step with one row object per row. Return groups, not row-level grouping answers.\n"
        )
    else:
        response_shape = '{"labels":["keep_for_review","other"]}'
        task_note = (
            "Review the ordered knowledge rows and answer every `row_id` exactly once.\n"
            "The packet `rows` array is ordered and authoritative; each row is rendered as `rXX | block_index | text`.\n"
            "Reason about the packet holistically first: read short local runs of adjacent rows together before deciding any single row.\n"
            "Decide by local span, emit by row. Neighboring rows often explain what role a row plays, but you must still return one final answer per `row_id`.\n"
            "Return one ordered `labels` array with exactly one label per row.\n"
            "Classify each row only as `keep_for_review` or `other`.\n"
            "A heading, bridge line, or short setup row may help nearby rows count as knowledge without itself being `knowledge`.\n"
            "Do not think about tags during classification. Tagging happens only in the second pass.\n"
            "If the row looks like reusable cooking knowledge worth carrying forward, return `keep_for_review`; otherwise return `other`.\n"
            "Memoir, book framing, navigation, decorative headings, and true-but-low-utility prose belong in `other` even if they mention cooking.\n"
            "Treat category labels and heading shape as weak hints only, but do use row order and nearby rows to understand the local run.\n"
        )
    context_note = (
        "Use `context_before_rows` and `context_after_rows` when present so you can understand the local run, then make the final label for the owned row itself.\n"
        if has_context
        else ""
    )
    repair_note = (
        "This is a repair followup.\n"
        "When present, `repair_feedback_rows` shows the prior answer for each failing row and the exact validator complaints.\n"
        "When present, `repair_validation_summary` carries packet-level contract failures such as wrong row count.\n"
        "Fix those exact failures instead of inventing a new scheme.\n"
        if repair_mode
        else ""
    )
    return (
        "Return JSON only.\n\n"
        + task_note
        + context_note
        + repair_note
        + f"The `groups` spans together must cover exactly {row_count} owned row(s).\n"
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
    labels = parsed.get("labels")
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
    if isinstance(labels, list):
        if len(labels) != len(owned_row_ids):
            return None, ("label_count_mismatch",), {
                "expected_label_count": len(owned_row_ids),
                "returned_label_count": len(labels),
            }
        for index, row_id in enumerate(owned_row_ids):
            unit_id = unit_id_by_row_id.get(row_id)
            if not unit_id:
                continue
            answers_by_unit_id[unit_id] = {
                "category": str(labels[index] or "").strip(),
            }
    else:
        decision_rows = parsed.get("rows")
        if not isinstance(decision_rows, list):
            return None, ("rows_missing_or_not_a_list",), {}
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
    row_index_by_row_id = {
        row_id: index for index, row_id in enumerate(owned_row_ids)
    }
    error_details: list[dict[str, Any]] = []
    response_contract_errors: list[str] = []
    groups = parsed.get("groups")
    if isinstance(groups, list):
        for group_index, group in enumerate(groups):
            if not isinstance(group, Mapping):
                return None, ("group_not_a_json_object",), {}
            group_id = str(
                group.get("group_id") or group.get("group_key") or group.get("group_index") or ""
            ).strip()
            topic_label = str(group.get("topic_label") or "").strip()
            start_row_id = str(group.get("start_row_id") or "").strip()
            end_row_id = str(group.get("end_row_id") or "").strip()
            explicit_row_ids = [
                str(value).strip()
                for value in (group.get("row_ids") or [])
                if str(value).strip()
            ]
            group_row_ids: list[str] = []
            if explicit_row_ids:
                unknown_in_group = [
                    row_id
                    for row_id in explicit_row_ids
                    if row_id not in row_index_by_row_id
                ]
                if unknown_in_group:
                    unknown_row_ids.update(unknown_in_group)
                    continue
                explicit_positions = [row_index_by_row_id[row_id] for row_id in explicit_row_ids]
                expected_positions = list(
                    range(min(explicit_positions), max(explicit_positions) + 1)
                )
                if explicit_positions != expected_positions:
                    response_contract_errors.append("knowledge_group_noncontiguous_span")
                    error_details.append(
                        {
                            "path": f"/response/groups/{group_index}/row_ids",
                            "code": "knowledge_group_noncontiguous_span",
                            "message": "group row_ids must form one contiguous ordered run",
                        }
                    )
                    continue
                group_row_ids = list(explicit_row_ids)
            else:
                if not start_row_id or not end_row_id:
                    response_contract_errors.append("knowledge_group_missing_span")
                    error_details.append(
                        {
                            "path": f"/response/groups/{group_index}",
                            "code": "knowledge_group_missing_span",
                            "message": "each group must provide either row_ids or both start_row_id and end_row_id",
                        }
                    )
                    continue
                if start_row_id not in row_index_by_row_id:
                    unknown_row_ids.add(start_row_id)
                    continue
                if end_row_id not in row_index_by_row_id:
                    unknown_row_ids.add(end_row_id)
                    continue
                start_index = row_index_by_row_id[start_row_id]
                end_index = row_index_by_row_id[end_row_id]
                if start_index > end_index:
                    response_contract_errors.append("knowledge_group_noncontiguous_span")
                    error_details.append(
                        {
                            "path": f"/response/groups/{group_index}",
                            "code": "knowledge_group_noncontiguous_span",
                            "message": "group start_row_id must appear before or equal to end_row_id",
                        }
                    )
                    continue
                group_row_ids = owned_row_ids[start_index : end_index + 1]
            proposed_tags = [
                dict(tag)
                for tag in (
                    group.get("proposed_tags")
                    or ([group.get("proposed_tag")] if isinstance(group.get("proposed_tag"), Mapping) else [])
                )
                if isinstance(tag, Mapping)
            ]
            group_answer = {
                "group_id": group_id,
                "topic_label": topic_label,
                "grounding": (
                    dict(group.get("grounding"))
                    if isinstance(group.get("grounding"), Mapping)
                    else {
                        "tag_keys": [
                            str(value).strip()
                            for value in (group.get("tag_keys") or [])
                            if str(value).strip()
                        ],
                        "category_keys": [
                            str(value).strip()
                            for value in (group.get("category_keys") or [])
                            if str(value).strip()
                        ],
                        "proposed_tags": proposed_tags,
                    }
                ),
                "why_no_existing_tag": str(
                    group.get("why_no_existing_tag") or ""
                ).strip(),
                "retrieval_query": str(group.get("retrieval_query") or "").strip(),
            }
            for row_id in group_row_ids:
                if row_id in seen_row_ids:
                    duplicate_row_ids.add(row_id)
                    continue
                seen_row_ids.add(row_id)
                unit_id = unit_id_by_row_id.get(row_id)
                if not unit_id:
                    unknown_row_ids.add(row_id)
                    continue
                answers_by_unit_id[unit_id] = dict(group_answer)
    elif isinstance(rows, list):
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
            proposed_tags = [
                dict(tag)
                for tag in (
                    row.get("proposed_tags")
                    or ([row.get("proposed_tag")] if isinstance(row.get("proposed_tag"), Mapping) else [])
                )
                if isinstance(tag, Mapping)
            ]
            answers_by_unit_id[unit_id] = {
                "group_id": str(
                    row.get("group_id") or row.get("group_key") or row.get("group_index") or ""
                ).strip(),
                "topic_label": str(row.get("topic_label") or "").strip(),
                "grounding": (
                    dict(row.get("grounding"))
                    if isinstance(row.get("grounding"), Mapping)
                    else {
                        "tag_keys": [
                            str(value).strip()
                            for value in (row.get("tag_keys") or [])
                            if str(value).strip()
                        ],
                        "category_keys": [
                            str(value).strip()
                            for value in (row.get("category_keys") or [])
                            if str(value).strip()
                        ],
                        "proposed_tags": proposed_tags,
                    }
                ),
                "why_no_existing_tag": str(
                    row.get("why_no_existing_tag") or ""
                ).strip(),
                "retrieval_query": str(row.get("retrieval_query") or "").strip(),
            }
    else:
        return None, ("rows_missing_or_not_a_list",), {}
    missing_unit_ids = [
        unit_id_by_row_id[row_id]
        for row_id in owned_row_ids
        if row_id in unit_id_by_row_id and unit_id_by_row_id[row_id] not in answers_by_unit_id
    ]
    base_response_contract_errors, response_contract_metadata = _response_contract_metadata(
        original_task_file=original_task_file,
        missing_unit_ids=missing_unit_ids,
        unknown_row_ids=sorted(unknown_row_ids),
        duplicate_row_ids=sorted(duplicate_row_ids),
    )
    combined_response_contract_errors = list(base_response_contract_errors)
    if error_details:
        response_contract_metadata = {
            **dict(response_contract_metadata),
            "error_details": list(response_contract_metadata.get("error_details") or [])
            + error_details,
        }
    response_contract_errors = tuple(
        dict.fromkeys(combined_response_contract_errors + response_contract_errors)
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
