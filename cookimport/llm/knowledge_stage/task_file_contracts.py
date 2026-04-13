from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping, Sequence

from ..codex_farm_knowledge_models import (
    ALLOWED_KNOWLEDGE_CLASSIFICATION_CATEGORIES,
    ALLOWED_KNOWLEDGE_FINAL_CATEGORIES,
    ALLOWED_KNOWLEDGE_PROPOSAL_DECISIONS,
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
KNOWLEDGE_GROUP_SAME_SESSION_BATCH_UNIT_ID = "knowledge-group-batch"


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
    row = _packet_context_row(packet, key=key, last=last)
    if row is None:
        return None
    cleaned = str(row.get("text") or "").strip()
    return cleaned or None


def _packet_context_row(
    packet: Mapping[str, Any],
    *,
    key: str,
    last: bool,
) -> dict[str, Any] | None:
    packet_context = _coerce_dict(packet.get("x"))
    rows = list(packet_context.get(key) or [])
    if not rows:
        return None
    row = rows[-1] if last else rows[0]
    if not isinstance(row, Mapping):
        return None
    cleaned = str(row.get("t") or "").strip()
    if not cleaned:
        return None
    return {
        "block_index": int(row.get("i") or row.get("block_index") or 0),
        "text": cleaned,
    }


def _blank_classification_answer() -> dict[str, Any]:
    return {"category": None}


def _canonical_other_classification_answer() -> dict[str, Any]:
    return {"category": "other"}


def _blank_grouping_answer() -> dict[str, Any]:
    return {
        "group_id": None,
        "topic_label": None,
        "grounding": empty_grounding_payload(),
        "why_no_existing_tag": None,
        "retrieval_query": None,
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


def _coerce_grouping_proposed_tag_rows(*values: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, Mapping):
            rows.append(dict(value))
            continue
        if isinstance(value, list):
            rows.extend(dict(row) for row in value if isinstance(row, Mapping))
    return rows


def _grouping_answer_proposed_tags(answer: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    payload = _coerce_dict(answer)
    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in _coerce_grouping_proposed_tag_rows(
        payload.get("proposed_tags"),
        payload.get("proposed_tag"),
    ):
        proposed_key = str(row.get("key") or "").strip()
        display_name = str(row.get("display_name") or "").strip()
        category_key = str(row.get("category_key") or "").strip()
        if not proposed_key or not display_name or not category_key:
            continue
        if proposed_key in seen_keys:
            continue
        seen_keys.add(proposed_key)
        deduped.append(
            {
                "key": proposed_key,
                "display_name": display_name,
                "category_key": category_key,
            }
        )
    return deduped


def _display_name_from_tag_key(value: str) -> str:
    cleaned = normalize_knowledge_tag_key(value)
    if not cleaned:
        return ""
    return " ".join(
        word.capitalize() for word in cleaned.replace("_", "-").split("-") if word
    )


def normalize_knowledge_grouping_group_shape(
    group_raw: Mapping[str, Any] | None,
) -> dict[str, Any]:
    group = _coerce_dict(group_raw)
    if not group:
        return {}
    grounding = _coerce_dict(group.get("grounding"))
    normalized_group = dict(group)
    if grounding:
        normalized_group["grounding"] = dict(grounding)

    if not str(normalized_group.get("group_id") or "").strip():
        nested_group_id = str(grounding.get("group_id") or "").strip()
        if nested_group_id:
            normalized_group["group_id"] = nested_group_id
    if not str(normalized_group.get("topic_label") or "").strip():
        nested_topic_label = str(grounding.get("topic_label") or "").strip()
        if nested_topic_label:
            normalized_group["topic_label"] = nested_topic_label

    proposed_rows = _coerce_grouping_proposed_tag_rows(
        grounding.get("proposed_tags") if grounding else None,
        grounding.get("proposed_tag") if grounding else None,
    )
    if not proposed_rows:
        proposed_rows = _coerce_grouping_proposed_tag_rows(
            group.get("proposed_tags"),
            group.get("proposed_tag"),
        )

    topic_label = str(normalized_group.get("topic_label") or "").strip()
    for proposed_tag in proposed_rows:
        display_name = str(
            proposed_tag.get("display_name")
            or proposed_tag.get("display")
            or proposed_tag.get("name")
            or ""
        ).strip()
        if not display_name and len(proposed_rows) == 1 and topic_label:
            display_name = topic_label
        if not display_name:
            display_name = _display_name_from_tag_key(str(proposed_tag.get("key") or ""))
        if display_name:
            proposed_tag["display_name"] = display_name

    if proposed_rows:
        normalized_grounding = dict(_coerce_dict(normalized_group.get("grounding")))
        normalized_grounding["proposed_tags"] = proposed_rows
        normalized_group["grounding"] = normalized_grounding

    why_no_existing_tag = str(normalized_group.get("why_no_existing_tag") or "").strip()
    retrieval_query = str(normalized_group.get("retrieval_query") or "").strip()
    if not why_no_existing_tag:
        why_no_existing_tag = str(grounding.get("why_no_existing_tag") or "").strip()
    if not retrieval_query:
        retrieval_query = str(grounding.get("retrieval_query") or "").strip()
    if (not why_no_existing_tag or not retrieval_query) and len(proposed_rows) == 1:
        proposed_tag = proposed_rows[0]
        if not why_no_existing_tag:
            why_no_existing_tag = str(
                proposed_tag.get("why_no_existing_tag")
                or proposed_tag.get("why_no_tag")
                or ""
            ).strip()
        if not retrieval_query:
            retrieval_query = str(proposed_tag.get("retrieval_query") or "").strip()
    if why_no_existing_tag:
        normalized_group["why_no_existing_tag"] = why_no_existing_tag
    if retrieval_query:
        normalized_group["retrieval_query"] = retrieval_query
    return normalized_group


def _validate_grouping_approved_proposed_tags(
    *,
    unit_id: str,
    proposed_tag_raw: Any,
    proposed_tags_raw: Any,
    why_no_existing_tag: str | None,
    retrieval_query: str | None,
    tag_keys: set[str],
    category_keys: set[str],
    tag_keys_by_normalized_display_name: Mapping[str, Sequence[str]],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    error_details: list[dict[str, Any]] = []
    proposed_rows = _coerce_grouping_proposed_tag_rows(proposed_tags_raw, proposed_tag_raw)
    invalid_shape = (
        proposed_tag_raw not in (None, "")
        and not isinstance(proposed_tag_raw, (Mapping, list))
    ) or (
        proposed_tags_raw not in (None, "")
        and not isinstance(proposed_tags_raw, (Mapping, list))
    )
    if invalid_shape or not proposed_rows:
        errors.append("approved_proposal_tag_required")
        error_details.append(
            {
                "path": f"/units/{unit_id}/answer/proposed_tags",
                "code": "approved_proposal_tag_required",
                "message": "approved proposal rows must include one or more proposed tag objects",
            }
        )
        return [], errors, error_details
    normalized_rows: list[dict[str, Any]] = []
    seen_proposed_keys: set[str] = set()
    for tag_index, proposed_tag in enumerate(proposed_rows):
        proposed_key = str(proposed_tag.get("key") or "").strip()
        normalized_proposed_key = normalize_knowledge_tag_key(proposed_key)
        display_name = str(proposed_tag.get("display_name") or "").strip()
        normalized_display_name = normalize_knowledge_tag_key(display_name)
        proposed_category_key = normalize_knowledge_tag_key(proposed_tag.get("category_key"))
        path_prefix = f"/units/{unit_id}/answer/proposed_tags/{tag_index}"
        row_failed = False
        if not proposed_key or proposed_key != normalized_proposed_key:
            errors.append("invalid_proposed_tag_key")
            error_details.append(
                {
                    "path": f"{path_prefix}/key",
                    "code": "invalid_proposed_tag_key",
                    "message": "proposed tag keys must already be normalized slug strings",
                }
            )
            row_failed = True
        elif normalized_proposed_key in tag_keys:
            errors.append("proposed_tag_key_conflicts_existing")
            error_details.append(
                {
                    "path": f"{path_prefix}/key",
                    "code": "proposed_tag_key_conflicts_existing",
                    "message": "proposed tag keys must not duplicate an existing tag key",
                }
            )
            row_failed = True
        elif normalized_proposed_key in seen_proposed_keys:
            continue
        if not display_name or len(display_name) > 64:
            errors.append("invalid_proposed_tag_display_name")
            error_details.append(
                {
                    "path": f"{path_prefix}/display_name",
                    "code": "invalid_proposed_tag_display_name",
                    "message": "proposed display_name must be a short non-empty string",
                }
            )
            row_failed = True
        elif tag_keys_by_normalized_display_name.get(normalized_display_name):
            errors.append("proposed_tag_display_name_conflicts_existing")
            error_details.append(
                {
                    "path": f"{path_prefix}/display_name",
                    "code": "proposed_tag_display_name_conflicts_existing",
                    "message": "proposed tag display_name matches an existing tag; use the existing tag instead",
                }
            )
            row_failed = True
        if not proposed_category_key or proposed_category_key not in category_keys:
            errors.append("unknown_grounding_category_key")
            error_details.append(
                {
                    "path": f"{path_prefix}/category_key",
                    "code": "unknown_grounding_category_key",
                    "message": "proposed tag category_key must be an existing category key",
                }
            )
            row_failed = True
        if row_failed:
            continue
        seen_proposed_keys.add(normalized_proposed_key)
        normalized_rows.append(
            {
                "key": normalized_proposed_key,
                "display_name": display_name,
                "category_key": proposed_category_key,
            }
        )
    if not normalized_rows:
        if "approved_proposal_tag_required" not in errors:
            errors.append("approved_proposal_tag_required")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/proposed_tags",
                    "code": "approved_proposal_tag_required",
                    "message": "approved proposal rows must include at least one valid proposed tag",
                }
            )
        return [], errors, error_details
    if not why_no_existing_tag:
        errors.append("proposal_justification_required")
        error_details.append(
            {
                "path": f"/units/{unit_id}/answer/why_no_existing_tag",
                "code": "proposal_justification_required",
                "message": "approved proposal rows must explain why no existing tag fits",
            }
        )
    if not retrieval_query:
        errors.append("proposal_retrieval_query_required")
        error_details.append(
            {
                "path": f"/units/{unit_id}/answer/retrieval_query",
                "code": "proposal_retrieval_query_required",
                "message": "approved proposal rows must include a plausible retrieval_query",
            }
        )
    if errors:
        return [], errors, error_details
    return normalized_rows, [], []


def _validate_group_grounding(
    *,
    unit_id: str,
    grounding_raw: Any,
    why_no_existing_tag: str | None,
    retrieval_query: str | None,
    catalog: Any,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    tag_keys = set(catalog.tag_by_key)
    category_keys = set(catalog.category_by_key)
    tag_keys_by_normalized_display_name = catalog.tag_keys_by_normalized_display_name
    grounding = _coerce_dict(grounding_raw)
    errors: list[str] = []
    error_details: list[dict[str, Any]] = []
    normalized_grounding = empty_grounding_payload()
    raw_tag_keys = grounding.get("tag_keys")
    raw_category_keys = grounding.get("category_keys")
    raw_proposed_tags = grounding.get("proposed_tags")
    if raw_tag_keys not in (None, "") and not isinstance(raw_tag_keys, list):
        errors.append("invalid_grounding_tag_keys")
        error_details.append(
            {
                "path": f"/units/{unit_id}/answer/grounding/tag_keys",
                "code": "invalid_grounding_tag_keys",
                "message": "grounding.tag_keys must be a list of existing tag keys",
            }
        )
    for tag_key in _normalized_string_list(raw_tag_keys):
        normalized_tag_key = normalize_knowledge_tag_key(tag_key)
        if normalized_tag_key not in tag_keys:
            errors.append("unknown_grounding_tag_key")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/grounding/tag_keys",
                    "code": "unknown_grounding_tag_key",
                    "message": f"unknown grounding tag key {tag_key!r}",
                }
            )
            continue
        normalized_grounding["tag_keys"].append(normalized_tag_key)
        normalized_grounding["category_keys"].append(
            catalog.tag_by_key[normalized_tag_key].category_key
        )
    if raw_category_keys not in (None, "") and not isinstance(raw_category_keys, list):
        errors.append("invalid_grounding_category_keys")
        error_details.append(
            {
                "path": f"/units/{unit_id}/answer/grounding/category_keys",
                "code": "invalid_grounding_category_keys",
                "message": "grounding.category_keys must be a list of existing category keys",
            }
        )
    for category_key in _normalized_string_list(raw_category_keys):
        normalized_category_key = normalize_knowledge_tag_key(category_key)
        if normalized_category_key not in category_keys:
            errors.append("unknown_grounding_category_key")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/grounding/category_keys",
                    "code": "unknown_grounding_category_key",
                    "message": f"unknown grounding category key {category_key!r}",
                }
            )
            continue
        normalized_grounding["category_keys"].append(normalized_category_key)
    if raw_proposed_tags not in (None, "") and not isinstance(raw_proposed_tags, list):
        errors.append("invalid_group_proposed_tags")
        error_details.append(
            {
                "path": f"/units/{unit_id}/answer/grounding/proposed_tags",
                "code": "invalid_group_proposed_tags",
                "message": "grounding.proposed_tags must be a list of proposed tag objects",
            }
        )
    normalized_proposed_tags: list[dict[str, Any]] = []
    if isinstance(raw_proposed_tags, list) and raw_proposed_tags:
        (
            normalized_proposed_tags,
            helper_errors,
            helper_error_details,
        ) = _validate_grouping_approved_proposed_tags(
            unit_id=unit_id,
            proposed_tag_raw=None,
            proposed_tags_raw=raw_proposed_tags,
            why_no_existing_tag=why_no_existing_tag,
            retrieval_query=retrieval_query,
            tag_keys=tag_keys,
            category_keys=category_keys,
            tag_keys_by_normalized_display_name=tag_keys_by_normalized_display_name,
        )
        errors.extend(helper_errors)
        error_details.extend(helper_error_details)
    elif why_no_existing_tag or retrieval_query:
        errors.append("group_proposal_justification_forbidden")
        error_details.append(
            {
                "path": f"/units/{unit_id}/answer",
                "code": "group_proposal_justification_forbidden",
                "message": "why_no_existing_tag and retrieval_query are only allowed when proposed_tags are present",
            }
        )
    if normalized_proposed_tags:
        normalized_grounding["proposed_tags"] = normalized_proposed_tags
        normalized_grounding["category_keys"].extend(
            str(proposed_tag.get("category_key") or "").strip()
            for proposed_tag in normalized_proposed_tags
            if str(proposed_tag.get("category_key") or "").strip()
        )
    normalized_grounding["category_keys"] = _normalized_string_list(
        normalized_grounding["category_keys"]
    )
    if not normalized_grounding["tag_keys"] and not normalized_grounding["proposed_tags"]:
        errors.append("group_grounding_required")
        error_details.append(
            {
                "path": f"/units/{unit_id}/answer/grounding",
                "code": "group_grounding_required",
                "message": "group grounding must include at least one existing tag or proposed tag",
            }
        )
    if errors:
        return empty_grounding_payload(), errors, error_details
    return normalized_grounding, [], []


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
        "required_keys": ["category"],
        "allowed_values": {"category": list(ALLOWED_KNOWLEDGE_CLASSIFICATION_CATEGORIES)},
        "example_answers": [
            {"category": "keep_for_review"},
            {"category": "other"},
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
            "Should this exact block survive into the second-pass knowledge grouping and tagging review?"
        ),
        "decision_policy": [
            "Read the owned block text first. That text is the primary evidence.",
            "Start by understanding short local runs of adjacent rows. Use nearby context to understand what role each row plays in that local run.",
            "Decide by local span, emit by row: neighboring rows can explain the current row without forcing all nearby rows into the same answer.",
            "Treat heading shape and packet position as weak hints only.",
            "A heading or bridge row can support nearby knowledge without itself being knowledge.",
            "A heading alone is not enough for knowledge; keep a heading only when it directly introduces or names reusable explanatory content in the owned packet.",
            "Return `keep_for_review` only when the row looks like reusable cooking knowledge worth carrying into the second-pass group review.",
            "Do not think about tags in this first pass. Tagging belongs entirely to the second pass.",
            "Short conceptual headings can still be knowledge when they introduce real explanatory content; shortness alone is not enough to drop a block.",
            "Keep a short action-key or strategy heading when it is the semantic key for the following owned explanatory row, even if the body text does not restate the heading words.",
        ],
        "anti_patterns": [
            "Do not invent a rule that classifies many rows at once from heading level, casing, length, or title shape.",
            "Do not treat the whole packet as one semantic unit just because the rows are adjacent.",
            "Do not keep memoir, praise, endorsement, foreword, thesis, manifesto, or broad inspiration-about-cooking prose as knowledge just because it contains true cooking claims.",
            "Do not invent a new tag in the first pass. That decision belongs to the second-pass grouping and tagging step.",
            "Navigation, decorative headings, book framing, memoir scene-setting, and true-but-low-utility filler belong in `other` even when you can imagine a plausible tag.",
            "If you feel tempted to batch or script the decision, stop and reread the actual owned block text instead.",
        ],
    }


def _knowledge_grouping_answer_schema() -> dict[str, Any]:
    return {
        "editable_pointer_pattern": "/units/*/answer",
        "required_keys": [
            "group_id",
            "topic_label",
            "grounding",
            "why_no_existing_tag",
            "retrieval_query",
        ],
        "example_answers": [
            {
                "group_id": "g01",
                "topic_label": "Heat control",
                "grounding": {
                    "tag_keys": ["heat-control"],
                    "category_keys": ["techniques"],
                    "proposed_tags": [],
                },
                "why_no_existing_tag": None,
                "retrieval_query": None,
            },
            {
                "group_id": "g02",
                "topic_label": "Rendering fat",
                "grounding": {
                    "tag_keys": [],
                    "category_keys": ["techniques"],
                    "proposed_tags": [
                        {
                            "key": "rendering-fat",
                            "display_name": "Rendering fat",
                            "category_key": "techniques",
                        }
                    ],
                },
                "why_no_existing_tag": "The catalog has nearby heat tags but no direct tag for slowly melting solid fat into usable rendered fat.",
                "retrieval_query": "how to render chicken fat",
            }
        ],
    }


def _knowledge_same_session_grouping_answer_schema() -> dict[str, Any]:
    return {
        "editable_pointer_pattern": "/units/*/answer",
        "required_keys": ["groups"],
        "example_answers": [
            {
                "groups": [
                    {
                        "group_id": "g01",
                        "start_row_id": "r01",
                        "end_row_id": "r03",
                        "topic_label": "Heat control",
                        "grounding": {
                            "tag_keys": ["heat-control"],
                            "category_keys": ["techniques"],
                            "proposed_tags": [],
                        },
                        "why_no_existing_tag": None,
                        "retrieval_query": None,
                    },
                    {
                        "group_id": "g02",
                        "row_ids": ["r04"],
                        "topic_label": "Rendering fat",
                        "grounding": {
                            "tag_keys": [],
                            "category_keys": ["techniques"],
                            "proposed_tags": [
                                {
                                    "key": "rendering-fat",
                                    "display_name": "Rendering fat",
                                    "category_key": "techniques",
                                }
                            ],
                        },
                        "why_no_existing_tag": "The catalog has nearby heat tags but no direct tag for slowly rendering solid fat.",
                        "retrieval_query": "how to render chicken fat",
                    },
                ]
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
        category = str(answer.get("category") or "").strip()
        if category != "keep_for_review":
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
                    "context_before_block_index": evidence.get(
                        "context_before_block_index"
                    ),
                    "context_after": evidence.get("context_after"),
                    "context_after_block_index": evidence.get(
                        "context_after_block_index"
                    ),
                    "structure": dict(_coerce_dict(evidence.get("structure"))),
                },
                "classification": {
                    "category": category,
                },
                "answer": _blank_grouping_answer(),
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
    task_file["ontology"] = load_knowledge_tag_catalog().task_scope_payload()
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


def _knowledge_same_session_group_rows(
    *,
    units: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row_index, unit in enumerate(units, start=1):
        if not isinstance(unit, Mapping):
            continue
        unit_dict = dict(unit)
        evidence = _coerce_dict(unit_dict.get("evidence"))
        rows.append(
            {
                "row_id": f"r{row_index:02d}",
                "source_unit_id": str(unit_dict.get("unit_id") or "").strip(),
                "owned_id": str(unit_dict.get("owned_id") or "").strip(),
                "block_index": int(evidence.get("block_index") or 0),
                "block_id": str(
                    evidence.get("block_id")
                    or unit_dict.get("owned_id")
                    or unit_dict.get("unit_id")
                    or ""
                ).strip(),
                "text": str(evidence.get("text") or ""),
                "context_before": evidence.get("context_before"),
                "context_before_block_index": evidence.get(
                    "context_before_block_index"
                ),
                "context_after": evidence.get("context_after"),
                "context_after_block_index": evidence.get(
                    "context_after_block_index"
                ),
                "structure": dict(_coerce_dict(evidence.get("structure"))),
                "classification": dict(_coerce_dict(unit_dict.get("classification"))),
            }
        )
    return rows


def _build_knowledge_same_session_grouping_task_file_from_units(
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
    task_file = build_task_file(
        stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
        assignment_id=assignment_id,
        worker_id=worker_id,
        units=[
            {
                "unit_id": KNOWLEDGE_GROUP_SAME_SESSION_BATCH_UNIT_ID,
                "evidence": {
                    "rows": _knowledge_same_session_group_rows(units=units),
                },
                "answer": {
                    "groups": [],
                },
            }
        ],
        schema_version=KNOWLEDGE_GROUP_SCHEMA_VERSION,
        answer_schema=_knowledge_same_session_grouping_answer_schema(),
    )
    task_file["ontology"] = load_knowledge_tag_catalog().task_scope_payload()
    task_file["grouping_batch"] = _grouping_batch_metadata(
        batch_units=units,
        batch_index=batch_index,
        batch_count=batch_count,
        total_grouping_unit_count=total_grouping_unit_count,
        max_units_per_batch=max_units_per_batch,
        max_evidence_chars_per_batch=max_evidence_chars_per_batch,
    )
    return task_file


def _is_knowledge_same_session_grouping_task_file(
    task_file: Mapping[str, Any],
) -> bool:
    answer_schema = _coerce_dict(task_file.get("answer_schema"))
    required_keys = {
        str(key).strip()
        for key in (answer_schema.get("required_keys") or [])
        if str(key).strip()
    }
    if required_keys != {"groups"}:
        return False
    units = [
        dict(unit)
        for unit in (task_file.get("units") or [])
        if isinstance(unit, Mapping)
    ]
    if len(units) != 1:
        return False
    return isinstance(_coerce_dict(units[0].get("evidence")).get("rows"), list)


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
    total_grouping_unit_count = len(units)
    task_files = []
    batch_unit_ids: list[list[str]] = []
    if units:
        grouping_batches = _partition_knowledge_grouping_units(
            units,
            max_units_per_batch=max_units_per_batch,
            max_evidence_chars_per_batch=max_evidence_chars_per_batch,
        )
        task_files = [
            _build_knowledge_grouping_task_file_from_units(
                assignment_id=assignment_id,
                worker_id=worker_id,
                units=batch_units,
                batch_index=batch_index,
                batch_count=len(grouping_batches),
                total_grouping_unit_count=total_grouping_unit_count,
                max_units_per_batch=max_units_per_batch,
                max_evidence_chars_per_batch=max_evidence_chars_per_batch,
            )
            for batch_index, batch_units in enumerate(grouping_batches, start=1)
        ]
        batch_unit_ids = [
            [
                str(unit.get("unit_id") or "").strip()
                for unit in batch_units
                if str(unit.get("unit_id") or "").strip()
            ]
            for batch_units in grouping_batches
        ]
    return task_files, grouping_unit_to_shard_id, batch_unit_ids


def build_knowledge_classification_task_file(
    *,
    assignment: WorkerAssignmentV1,
    shards: Sequence[ShardManifestEntryV1],
    knowledge_group_task_max_units: int = KNOWLEDGE_GROUP_TASK_MAX_UNITS,
    knowledge_group_task_max_evidence_chars: int = KNOWLEDGE_GROUP_TASK_MAX_EVIDENCE_CHARS,
) -> tuple[dict[str, Any], dict[str, str]]:
    units: list[dict[str, Any]] = []
    unit_to_shard_id: dict[str, str] = {}
    for shard in shards:
        for packet in _knowledge_packet_payloads(shard.input_payload):
            context_before_row = _packet_context_row(packet, key="p", last=True)
            context_after_row = _packet_context_row(packet, key="n", last=False)
            context_before = (
                str(context_before_row.get("text") or "").strip()
                if context_before_row is not None
                else None
            )
            context_after = (
                str(context_after_row.get("text") or "").strip()
                if context_after_row is not None
                else None
            )
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
                        "context_before_block_index": (
                            int(context_before_row.get("block_index") or 0)
                            if context_before_row is not None
                            else None
                        ),
                        "context_after": context_after,
                        "context_after_block_index": (
                            int(context_after_row.get("block_index") or 0)
                            if context_after_row is not None
                            else None
                        ),
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
                    "answer": _blank_classification_answer(),
                }
                units.append(unit_payload)
    task_file = build_task_file(
        stage_key=KNOWLEDGE_CLASSIFY_STAGE_KEY,
        assignment_id=assignment.worker_id,
        worker_id=assignment.worker_id,
        units=units,
        schema_version=KNOWLEDGE_CLASSIFY_SCHEMA_VERSION,
        answer_schema=_knowledge_classification_answer_schema(),
    )
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
    missing_block_indices: list[int] = []
    validated_answers: dict[str, dict[str, Any]] = {}
    units_by_id = {
        str(unit.get("unit_id") or "").strip(): dict(unit)
        for unit in (original_task_file.get("units") or [])
        if isinstance(unit, Mapping) and str(unit.get("unit_id") or "").strip()
    }
    for unit_id, answer in answers_by_unit_id.items():
        unit = units_by_id.get(unit_id) or {}
        block_index = int(_coerce_dict(unit.get("evidence")).get("block_index") or 0)
        answer_keys = {str(key).strip() for key in answer.keys()}
        category = str(answer.get("category") or "").strip()
        unit_failed = False
        extra_keys = sorted(key for key in answer_keys if key and key != "category")
        if extra_keys:
            next_errors.append("classification_extra_answer_keys_forbidden")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer",
                    "code": "classification_extra_answer_keys_forbidden",
                    "message": "first-pass classification answers may only include `category`",
                }
            )
            unit_failed = True
        if not category:
            next_errors.append("knowledge_block_missing_decision")
            missing_block_indices.append(block_index)
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/category",
                    "code": "knowledge_block_missing_decision",
                    "message": "response did not return a classification decision for this block",
                }
            )
            unit_failed = True
        elif category not in ALLOWED_KNOWLEDGE_CLASSIFICATION_CATEGORIES:
            next_errors.append("invalid_category")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/category",
                    "code": "invalid_category",
                    "message": "category must be 'keep_for_review' or 'other'",
                }
            )
            unit_failed = True
        if unit_failed:
            failed_unit_ids.append(unit_id)
            unresolved_block_indices.append(block_index)
            continue
        validated_answers[unit_id] = {"category": category}
    next_metadata = {
        **dict(metadata),
        "error_details": error_details,
        "failed_unit_ids": failed_unit_ids,
        "unresolved_block_indices": sorted(set(unresolved_block_indices)),
        "missing_block_indices": sorted(set(missing_block_indices)),
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


def _validate_knowledge_same_session_grouping_task_file(
    *,
    original_task_file: Mapping[str, Any],
    edited_task_file: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]] | None, tuple[str, ...], dict[str, Any]]:
    catalog = load_knowledge_tag_catalog()
    answers_by_unit_id, errors, metadata = validate_edited_task_file(
        original_task_file=original_task_file,
        edited_task_file=edited_task_file,
        expected_schema_version=KNOWLEDGE_GROUP_SCHEMA_VERSION,
    )
    if answers_by_unit_id is None:
        return None, errors, metadata

    batch_units = [
        dict(unit)
        for unit in (original_task_file.get("units") or [])
        if isinstance(unit, Mapping)
    ]
    batch_unit = batch_units[0] if batch_units else {}
    batch_unit_id = (
        str(batch_unit.get("unit_id") or "").strip()
        or KNOWLEDGE_GROUP_SAME_SESSION_BATCH_UNIT_ID
    )
    batch_answer = _coerce_dict(answers_by_unit_id.get(batch_unit_id))
    next_errors = list(errors)
    error_details = list(metadata.get("error_details") or [])

    answer_keys = {str(key).strip() for key in batch_answer.keys()}
    extra_keys = sorted(key for key in answer_keys if key and key != "groups")
    if extra_keys:
        next_errors.append("grouping_extra_answer_keys_forbidden")
        error_details.append(
            {
                "path": f"/units/{batch_unit_id}/answer",
                "code": "grouping_extra_answer_keys_forbidden",
                "message": "same-session grouping answers may only include `groups`",
            }
        )

    groups = batch_answer.get("groups")
    if not isinstance(groups, list):
        next_errors.append("groups_missing_or_not_a_list")
        error_details.append(
            {
                "path": f"/units/{batch_unit_id}/answer/groups",
                "code": "groups_missing_or_not_a_list",
                "message": "grouping batches must answer with one `groups` list",
            }
        )
        return None, tuple(dict.fromkeys(next_errors)), {
            **dict(metadata),
            "error_details": error_details,
            "failed_unit_ids": [batch_unit_id],
            "validated_answers_by_unit_id": {},
        }

    rows = [
        dict(row)
        for row in (_coerce_dict(batch_unit.get("evidence")).get("rows") or [])
        if isinstance(row, Mapping)
    ]
    row_ids_in_order = [
        str(row.get("row_id") or "").strip()
        for row in rows
        if str(row.get("row_id") or "").strip()
    ]
    row_index_by_row_id = {
        row_id: index for index, row_id in enumerate(row_ids_in_order)
    }
    row_id_to_source_unit_id = {
        str(row.get("row_id") or "").strip(): str(row.get("source_unit_id") or "").strip()
        for row in rows
        if str(row.get("row_id") or "").strip() and str(row.get("source_unit_id") or "").strip()
    }
    row_id_to_block_index = {
        str(row.get("row_id") or "").strip(): int(row.get("block_index") or 0)
        for row in rows
        if str(row.get("row_id") or "").strip()
    }

    validated_answers: dict[str, dict[str, Any]] = {}
    missing_row_ids: list[str] = []
    unknown_row_ids: set[str] = set()
    duplicate_row_ids: set[str] = set()
    seen_row_ids: set[str] = set()

    for group_index, group in enumerate(groups):
        if not isinstance(group, Mapping):
            next_errors.append("group_not_a_json_object")
            error_details.append(
                {
                    "path": f"/units/{batch_unit_id}/answer/groups/{group_index}",
                    "code": "group_not_a_json_object",
                    "message": "each group must be a JSON object",
                }
            )
            continue
        group_dict = normalize_knowledge_grouping_group_shape(group)
        group_id = str(
            group_dict.get("group_id")
            or group_dict.get("group_key")
            or group_dict.get("group_index")
            or ""
        ).strip()
        topic_label = str(group_dict.get("topic_label") or "").strip()
        if not group_id:
            next_errors.append("knowledge_block_missing_group")
            error_details.append(
                {
                    "path": f"/units/{batch_unit_id}/answer/groups/{group_index}/group_id",
                    "code": "knowledge_block_missing_group",
                    "message": "group_id must be a non-empty string",
                }
            )
        if not topic_label:
            next_errors.append("knowledge_block_missing_group")
            error_details.append(
                {
                    "path": f"/units/{batch_unit_id}/answer/groups/{group_index}/topic_label",
                    "code": "knowledge_block_missing_group",
                    "message": "topic_label must be a non-empty string",
                }
            )

        explicit_row_ids_raw = group_dict.get("row_ids")
        if explicit_row_ids_raw not in (None, "") and not isinstance(explicit_row_ids_raw, list):
            next_errors.append("knowledge_group_noncontiguous_span")
            error_details.append(
                {
                    "path": f"/units/{batch_unit_id}/answer/groups/{group_index}/row_ids",
                    "code": "knowledge_group_noncontiguous_span",
                    "message": "row_ids must be a list when provided",
                }
            )
            continue
        explicit_row_ids = [
            str(value).strip()
            for value in (explicit_row_ids_raw or [])
            if str(value).strip()
        ]
        group_row_ids: list[str] = []
        if explicit_row_ids:
            unknown_in_group = [
                row_id for row_id in explicit_row_ids if row_id not in row_index_by_row_id
            ]
            if unknown_in_group:
                unknown_row_ids.update(unknown_in_group)
                continue
            explicit_positions = [row_index_by_row_id[row_id] for row_id in explicit_row_ids]
            expected_positions = list(range(min(explicit_positions), max(explicit_positions) + 1))
            if explicit_positions != expected_positions:
                next_errors.append("knowledge_group_noncontiguous_span")
                error_details.append(
                    {
                        "path": f"/units/{batch_unit_id}/answer/groups/{group_index}/row_ids",
                        "code": "knowledge_group_noncontiguous_span",
                        "message": "group row_ids must form one contiguous ordered run",
                    }
                )
                continue
            group_row_ids = list(explicit_row_ids)
        else:
            start_row_id = str(group_dict.get("start_row_id") or "").strip()
            end_row_id = str(group_dict.get("end_row_id") or "").strip()
            if not start_row_id or not end_row_id:
                next_errors.append("knowledge_group_missing_span")
                error_details.append(
                    {
                        "path": f"/units/{batch_unit_id}/answer/groups/{group_index}",
                        "code": "knowledge_group_missing_span",
                        "message": "each group must provide row_ids or both start_row_id and end_row_id",
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
                next_errors.append("knowledge_group_noncontiguous_span")
                error_details.append(
                    {
                        "path": f"/units/{batch_unit_id}/answer/groups/{group_index}",
                        "code": "knowledge_group_noncontiguous_span",
                        "message": "start_row_id must appear before or equal to end_row_id",
                    }
                )
                continue
            group_row_ids = row_ids_in_order[start_index : end_index + 1]

        why_no_existing_tag = _trimmed_text_or_none(group_dict.get("why_no_existing_tag"))
        retrieval_query = _trimmed_text_or_none(group_dict.get("retrieval_query"))
        grounding_raw = group_dict.get("grounding")
        if grounding_raw not in (None, "") and not isinstance(grounding_raw, Mapping):
            next_errors.append("group_grounding_not_object")
            error_details.append(
                {
                    "path": f"/units/{batch_unit_id}/answer/groups/{group_index}/grounding",
                    "code": "group_grounding_not_object",
                    "message": "grounding must be a JSON object",
                }
            )
            continue
        normalized_grounding, helper_errors, helper_error_details = _validate_group_grounding(
            unit_id=batch_unit_id,
            grounding_raw=grounding_raw,
            why_no_existing_tag=why_no_existing_tag,
            retrieval_query=retrieval_query,
            catalog=catalog,
        )
        if helper_errors:
            next_errors.extend(helper_errors)
            for detail in helper_error_details:
                path = str(detail.get("path") or "").strip()
                suffix = path.split("/answer", 1)[1] if "/answer" in path else ""
                error_details.append(
                    {
                        **dict(detail),
                        "path": (
                            f"/units/{batch_unit_id}/answer/groups/{group_index}{suffix}"
                            if suffix
                            else f"/units/{batch_unit_id}/answer/groups/{group_index}"
                        ),
                    }
                )
            continue

        group_answer = {
            "group_id": group_id,
            "topic_label": topic_label,
            "grounding": normalized_grounding,
            "why_no_existing_tag": why_no_existing_tag,
            "retrieval_query": retrieval_query,
        }
        for row_id in group_row_ids:
            if row_id in seen_row_ids:
                duplicate_row_ids.add(row_id)
                continue
            seen_row_ids.add(row_id)
            source_unit_id = row_id_to_source_unit_id.get(row_id)
            if not source_unit_id:
                unknown_row_ids.add(row_id)
                continue
            validated_answers[source_unit_id] = dict(group_answer)

    if unknown_row_ids:
        next_errors.append("knowledge_unknown_response_rows")
        error_details.append(
            {
                "path": f"/units/{batch_unit_id}/answer/groups",
                "code": "knowledge_unknown_response_rows",
                "message": f"unknown row ids: {', '.join(sorted(unknown_row_ids))}",
            }
        )
    if duplicate_row_ids:
        next_errors.append("knowledge_duplicate_response_rows")
        error_details.append(
            {
                "path": f"/units/{batch_unit_id}/answer/groups",
                "code": "knowledge_duplicate_response_rows",
                "message": f"duplicate row ids: {', '.join(sorted(duplicate_row_ids))}",
            }
        )

    missing_row_ids = [
        row_id
        for row_id in row_ids_in_order
        if row_id_to_source_unit_id.get(row_id)
        and row_id_to_source_unit_id[row_id] not in validated_answers
    ]
    unresolved_block_indices = sorted(
        {
            row_id_to_block_index[row_id]
            for row_id in set(missing_row_ids) | duplicate_row_ids | unknown_row_ids
            if row_id in row_id_to_block_index
        }
    )
    if missing_row_ids:
        next_errors.append("knowledge_block_missing_group")
        error_details.append(
            {
                "path": f"/units/{batch_unit_id}/answer/groups",
                "code": "knowledge_block_missing_group",
                "message": f"every kept row must appear in exactly one group; missing row ids: {', '.join(missing_row_ids)}",
            }
        )

    next_metadata = {
        **dict(metadata),
        "error_details": error_details,
        "failed_unit_ids": [batch_unit_id] if next_errors or error_details else [],
        "unresolved_block_indices": unresolved_block_indices,
        "validated_answers_by_unit_id": {} if next_errors else validated_answers,
        "same_session_group_missing_row_ids": missing_row_ids,
        "same_session_group_unknown_row_ids": sorted(unknown_row_ids),
        "same_session_group_duplicate_row_ids": sorted(duplicate_row_ids),
    }
    if next_errors:
        if unresolved_block_indices:
            next_metadata["knowledge_blocks_missing_group"] = unresolved_block_indices
        return None, tuple(dict.fromkeys(next_errors)), next_metadata
    return validated_answers, (), next_metadata


def validate_knowledge_grouping_task_file(
    *,
    original_task_file: Mapping[str, Any],
    edited_task_file: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]] | None, tuple[str, ...], dict[str, Any]]:
    if _is_knowledge_same_session_grouping_task_file(original_task_file):
        return _validate_knowledge_same_session_grouping_task_file(
            original_task_file=original_task_file,
            edited_task_file=edited_task_file,
        )
    catalog = load_knowledge_tag_catalog()
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
    canonical_story_by_group_id: dict[str, str] = {}
    unit_ids_by_group_id: dict[str, list[str]] = {}
    row_position_by_unit_id: dict[str, int] = {}
    units_by_id = {
        str(unit.get("unit_id") or "").strip(): dict(unit)
        for unit in (original_task_file.get("units") or [])
        if isinstance(unit, Mapping) and str(unit.get("unit_id") or "").strip()
    }
    for row_position, unit in enumerate(original_task_file.get("units") or []):
        if not isinstance(unit, Mapping):
            continue
        unit_id = str(unit.get("unit_id") or "").strip()
        if unit_id:
            row_position_by_unit_id[unit_id] = row_position
    for unit_id, answer in answers_by_unit_id.items():
        unit = units_by_id.get(unit_id) or {}
        block_index = int(_coerce_dict(unit.get("evidence")).get("block_index") or 0)
        classification = _coerce_dict(unit.get("classification"))
        classification_category = str(classification.get("category") or "").strip()
        answer_keys = {str(key).strip() for key in answer.keys()}
        group_id = str(answer.get("group_id") or "").strip()
        topic_label = str(answer.get("topic_label") or "").strip()
        grounding_raw = answer.get("grounding")
        why_no_existing_tag = _trimmed_text_or_none(answer.get("why_no_existing_tag"))
        retrieval_query = _trimmed_text_or_none(answer.get("retrieval_query"))
        unit_failed = False
        extra_keys = sorted(
            key
            for key in answer_keys
            if key
            not in {"group_id", "topic_label", "grounding", "why_no_existing_tag", "retrieval_query"}
        )
        if extra_keys:
            next_errors.append("grouping_extra_answer_keys_forbidden")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer",
                    "code": "grouping_extra_answer_keys_forbidden",
                    "message": "grouping answers may only include group_id, topic_label, grounding, why_no_existing_tag, and retrieval_query",
                }
            )
            unit_failed = True
        if not group_id:
            next_errors.append("knowledge_block_missing_group")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/group_id",
                    "code": "knowledge_block_missing_group",
                    "message": "group_id must be a non-empty string",
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
        if grounding_raw not in (None, "") and not isinstance(grounding_raw, Mapping):
            next_errors.append("group_grounding_not_object")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/grounding",
                    "code": "group_grounding_not_object",
                    "message": "grounding must be a JSON object",
                }
            )
            unit_failed = True
        if classification_category != "keep_for_review":
            next_errors.append("invalid_grouping_source_category")
            error_details.append(
                {
                    "path": f"/units/{unit_id}/classification/category",
                    "code": "invalid_grouping_source_category",
                    "message": "grouping units must originate from keep_for_review classification rows",
                }
            )
            unit_failed = True
        normalized_grounding = empty_grounding_payload()
        if not unit_failed:
            (
                normalized_grounding,
                helper_errors,
                helper_error_details,
            ) = _validate_group_grounding(
                unit_id=unit_id,
                grounding_raw=grounding_raw,
                why_no_existing_tag=why_no_existing_tag,
                retrieval_query=retrieval_query,
                catalog=catalog,
            )
            if helper_errors:
                next_errors.extend(helper_errors)
                error_details.extend(helper_error_details)
                unit_failed = True
        if unit_failed:
            failed_unit_ids.append(unit_id)
            unresolved_block_indices.append(block_index)
            continue
        canonical_story = json.dumps(
            {
                "topic_label": topic_label,
                "grounding": normalized_grounding,
                "why_no_existing_tag": why_no_existing_tag,
                "retrieval_query": retrieval_query,
            },
            sort_keys=True,
        )
        prior_story = canonical_story_by_group_id.get(group_id)
        unit_ids_by_group_id.setdefault(group_id, []).append(unit_id)
        if prior_story is None:
            canonical_story_by_group_id[group_id] = canonical_story
        elif prior_story != canonical_story:
            next_errors.append("knowledge_group_mixed_tag_story")
            for conflicted_unit_id in unit_ids_by_group_id[group_id]:
                if conflicted_unit_id not in failed_unit_ids:
                    failed_unit_ids.append(conflicted_unit_id)
            if unit_id not in failed_unit_ids:
                failed_unit_ids.append(unit_id)
            for conflicted_unit_id in unit_ids_by_group_id[group_id]:
                conflicted_block_index = int(
                    _coerce_dict(
                        _coerce_dict(units_by_id.get(conflicted_unit_id)).get("evidence")
                    ).get("block_index")
                    or 0
                )
                unresolved_block_indices.append(conflicted_block_index)
            unresolved_block_indices.append(block_index)
            error_details.append(
                {
                    "path": f"/units/{unit_id}/answer/group_id",
                    "code": "knowledge_group_mixed_tag_story",
                    "message": "rows sharing one group_id must also share the same topic label and grounding story",
                }
            )
            continue
        validated_answers[unit_id] = {
            "group_id": group_id,
            "topic_label": topic_label,
            "grounding": normalized_grounding,
            "why_no_existing_tag": why_no_existing_tag,
            "retrieval_query": retrieval_query,
        }
    noncontiguous_blocks: list[int] = []
    if not next_errors:
        for group_id, grouped_unit_ids in unit_ids_by_group_id.items():
            ordered_positions = sorted(
                row_position_by_unit_id[unit_id]
                for unit_id in grouped_unit_ids
                if unit_id in row_position_by_unit_id
            )
            if not ordered_positions:
                continue
            expected_positions = list(
                range(ordered_positions[0], ordered_positions[-1] + 1)
            )
            if ordered_positions == expected_positions:
                continue
            next_errors.append("knowledge_group_noncontiguous_span")
            for conflicted_unit_id in grouped_unit_ids:
                if conflicted_unit_id not in failed_unit_ids:
                    failed_unit_ids.append(conflicted_unit_id)
                conflicted_block_index = int(
                    _coerce_dict(
                        _coerce_dict(units_by_id.get(conflicted_unit_id)).get("evidence")
                    ).get("block_index")
                    or 0
                )
                unresolved_block_indices.append(conflicted_block_index)
                noncontiguous_blocks.append(conflicted_block_index)
            error_details.append(
                {
                    "path": f"/groups/{group_id}",
                    "code": "knowledge_group_noncontiguous_span",
                    "message": "rows sharing one group_id must form one contiguous run in packet order",
                }
            )
    next_metadata = {
        **dict(metadata),
        "error_details": error_details,
        "failed_unit_ids": failed_unit_ids,
        "unresolved_block_indices": sorted(set(unresolved_block_indices)),
        "validated_answers_by_unit_id": validated_answers,
    }
    if next_errors:
        next_metadata["knowledge_blocks_missing_group"] = sorted(set(unresolved_block_indices))
        if noncontiguous_blocks:
            next_metadata["knowledge_group_noncontiguous_blocks"] = sorted(
                set(noncontiguous_blocks)
            )
        return None, tuple(dict.fromkeys(next_errors)), next_metadata
    return validated_answers, (), next_metadata


def canonicalize_knowledge_grouping_answer_ids(
    *,
    original_task_file: Mapping[str, Any],
    answers_by_unit_id: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    canonical_answers: dict[str, dict[str, Any]] = {}
    next_group_index = 1
    current_story_key: str | None = None
    current_group_id: str | None = None
    seen_unit_ids: set[str] = set()

    for unit in original_task_file.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_id = str(unit.get("unit_id") or "").strip()
        if not unit_id:
            continue
        seen_unit_ids.add(unit_id)
        answer = _coerce_dict(_coerce_dict(answers_by_unit_id).get(unit_id))
        if not answer:
            current_story_key = None
            current_group_id = None
            continue
        topic_label = str(answer.get("topic_label") or "").strip()
        group_id = str(answer.get("group_id") or "").strip()
        if not topic_label or not group_id:
            canonical_answers[unit_id] = dict(answer)
            current_story_key = None
            current_group_id = None
            continue
        grounding = _normalize_output_grounding(answer.get("grounding"))
        why_no_existing_tag = _trimmed_text_or_none(answer.get("why_no_existing_tag"))
        retrieval_query = _trimmed_text_or_none(answer.get("retrieval_query"))
        story_key = json.dumps(
            {
                "topic_label": topic_label,
                "grounding": grounding,
                "why_no_existing_tag": why_no_existing_tag,
                "retrieval_query": retrieval_query,
            },
            sort_keys=True,
        )
        if current_story_key != story_key or current_group_id is None:
            current_group_id = f"g{next_group_index:02d}"
            next_group_index += 1
            current_story_key = story_key
        canonical_answers[unit_id] = {
            "group_id": current_group_id,
            "topic_label": topic_label,
            "grounding": grounding,
            "why_no_existing_tag": why_no_existing_tag,
            "retrieval_query": retrieval_query,
        }

    for unit_id, answer in dict(answers_by_unit_id or {}).items():
        cleaned_unit_id = str(unit_id).strip()
        if (
            not cleaned_unit_id
            or cleaned_unit_id in seen_unit_ids
            or not isinstance(answer, Mapping)
        ):
            continue
        canonical_answers[cleaned_unit_id] = dict(answer)
    return canonical_answers


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
    grouping_answers = grouping_answers_by_unit_id or {}
    outputs: dict[str, dict[str, Any]] = {}
    grouped_rows_by_shard = _canonicalize_knowledge_groups_by_shard(
        shard_rows=shard_rows,
        grouping_answers=grouping_answers,
    )
    for shard_id, rows in shard_rows.items():
        ordered_rows = sorted(rows, key=lambda row: row[0])
        group_rows = grouped_rows_by_shard.get(shard_id, [])
        idea_groups = [
            {
                "group_id": str(group_row.get("group_id") or ""),
                "topic_label": str(group_row.get("topic_label") or ""),
                "block_indices": list(group_row.get("block_indices") or []),
                "grounding": dict(group_row.get("grounding") or empty_grounding_payload()),
                "why_no_existing_tag": group_row.get("why_no_existing_tag"),
                "retrieval_query": group_row.get("retrieval_query"),
            }
            for group_row in group_rows
        ]
        block_to_grounding = {
            int(block_index): dict(group_row.get("grounding") or empty_grounding_payload())
            for group_row in group_rows
            for block_index in (group_row.get("block_indices") or [])
            if block_index is not None
        }
        block_decisions: list[dict[str, Any]] = []
        for block_index, answer, _unit_id in ordered_rows:
            classification_category = str(answer.get("category") or "other").strip() or "other"
            final_category = "knowledge" if classification_category == "keep_for_review" else "other"
            block_decisions.append(
                {
                    "block_index": block_index,
                    "category": final_category,
                    "grounding": (
                        dict(block_to_grounding.get(block_index) or empty_grounding_payload())
                        if final_category == "knowledge"
                        else empty_grounding_payload()
                    ),
                }
            )
        outputs[shard_id] = {
            "packet_id": shard_id,
            "block_decisions": block_decisions,
            "idea_groups": idea_groups,
        }
    return outputs


def collect_knowledge_resolution_metadata_by_shard(
    *,
    classification_task_file: Mapping[str, Any],
    classification_answers_by_unit_id: Mapping[str, Mapping[str, Any]],
    grouping_answers_by_unit_id: Mapping[str, Mapping[str, Any]] | None,
    unit_to_shard_id: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    grouping_answers = grouping_answers_by_unit_id or {}
    shard_rows: dict[str, list[tuple[int, dict[str, Any], str]]] = {}
    metadata_by_shard: dict[str, dict[str, Any]] = {}
    for unit in classification_task_file.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_id = str(unit.get("unit_id") or "").strip()
        shard_id = str(unit_to_shard_id.get(unit_id) or "").strip()
        if not unit_id or not shard_id:
            continue
        evidence = _coerce_dict(unit.get("evidence"))
        block_index = int(evidence.get("block_index") or 0)
        classification_answer = _coerce_dict(classification_answers_by_unit_id.get(unit_id))
        classification_category = str(
            classification_answer.get("category") or "other"
        ).strip() or "other"
        shard_rows.setdefault(shard_id, []).append((block_index, classification_answer, unit_id))
        shard_row = metadata_by_shard.setdefault(
            shard_id,
            {
                "kept_for_review_block_count": 0,
                "knowledge_group_count": 0,
                "knowledge_group_split_count": 0,
                "knowledge_groups_using_existing_tags": 0,
                "knowledge_groups_using_proposed_tags": 0,
                "group_resolution_details": [],
                "_group_details_by_id": {},
            },
        )
        if classification_category != "keep_for_review":
            continue
        shard_row["kept_for_review_block_count"] += 1
    grouped_rows_by_shard = _canonicalize_knowledge_groups_by_shard(
        shard_rows=shard_rows,
        grouping_answers=grouping_answers,
    )
    for shard_id, shard_row in metadata_by_shard.items():
        shard_row.pop("_group_details_by_id")
        group_details = []
        for detail in grouped_rows_by_shard.get(shard_id, []):
            if not str(detail.get("group_id") or "").strip():
                continue
            group_details.append(
                {
                    "group_id": str(detail.get("group_id") or ""),
                    "topic_label": str(detail.get("topic_label") or ""),
                    "block_indices": list(detail.get("block_indices") or []),
                    "grounding": dict(detail.get("grounding") or empty_grounding_payload()),
                    "why_no_existing_tag": detail.get("why_no_existing_tag"),
                    "retrieval_query": detail.get("retrieval_query"),
                }
            )
        shard_row["knowledge_group_count"] = len(group_details)
        shard_row["knowledge_group_split_count"] = max(len(group_details) - 1, 0)
        shard_row["knowledge_groups_using_existing_tags"] = sum(
            1
            for detail in group_details
            if list(_coerce_dict(detail.get("grounding")).get("tag_keys") or [])
        )
        shard_row["knowledge_groups_using_proposed_tags"] = sum(
            1
            for detail in group_details
            if list(_coerce_dict(detail.get("grounding")).get("proposed_tags") or [])
        )
        shard_row["group_resolution_details"] = group_details
    return metadata_by_shard


def _canonicalize_knowledge_groups_by_shard(
    *,
    shard_rows: Mapping[str, Sequence[tuple[int, Mapping[str, Any], str]]],
    grouping_answers: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped_rows_by_shard: dict[str, list[dict[str, Any]]] = {}
    for shard_id, rows in shard_rows.items():
        canonical_groups: list[dict[str, Any]] = []
        current_group: dict[str, Any] | None = None
        current_story_key: str | None = None
        for block_index, answer, unit_id in sorted(rows, key=lambda row: row[0]):
            classification_category = str(answer.get("category") or "other").strip() or "other"
            if classification_category != "keep_for_review":
                continue
            grouping_answer = _coerce_dict(grouping_answers.get(unit_id))
            original_group_id = str(grouping_answer.get("group_id") or "").strip()
            topic_label = str(grouping_answer.get("topic_label") or "").strip()
            if not original_group_id or not topic_label:
                continue
            grounding = _normalize_output_grounding(grouping_answer.get("grounding"))
            why_no_existing_tag = _trimmed_text_or_none(
                grouping_answer.get("why_no_existing_tag")
            )
            retrieval_query = _trimmed_text_or_none(
                grouping_answer.get("retrieval_query")
            )
            story_key = json.dumps(
                {
                    "topic_label": topic_label,
                    "grounding": grounding,
                    "why_no_existing_tag": why_no_existing_tag,
                    "retrieval_query": retrieval_query,
                },
                sort_keys=True,
            )
            if current_story_key != story_key or current_group is None:
                current_group = {
                    "group_id": "",
                    "topic_label": topic_label,
                    "block_indices": [],
                    "grounding": grounding,
                    "why_no_existing_tag": why_no_existing_tag,
                    "retrieval_query": retrieval_query,
                }
                canonical_groups.append(current_group)
                current_story_key = story_key
            current_group["block_indices"].append(block_index)
        grouped_rows_by_shard[shard_id] = [
            {
                **group_row,
                "group_id": f"g{index:02d}",
                "block_indices": sorted(
                    {
                        int(block_index)
                        for block_index in (
                            group_row.get("block_indices") or []
                        )
                        if block_index is not None
                    }
                ),
            }
            for index, group_row in enumerate(canonical_groups, start=1)
        ]
    return grouped_rows_by_shard


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
    (
        grouping_task_files,
        _grouping_unit_to_shard_id,
        grouping_batch_unit_ids,
    ) = build_knowledge_grouping_task_files(
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
    if grouping_task_files:
        first_grouping_batch_unit_ids = grouping_batch_unit_ids[0] if grouping_batch_unit_ids else []
        first_grouping_units = [
            unit
            for unit in (grouping_task_files[0].get("units") or [])
            if isinstance(unit, Mapping)
            and str(unit.get("unit_id") or "").strip() in set(first_grouping_batch_unit_ids)
        ]
        grouping_task_file = _build_knowledge_same_session_grouping_task_file_from_units(
            assignment_id=str(original_task_file.get("assignment_id") or ""),
            worker_id=str(original_task_file.get("worker_id") or ""),
            units=first_grouping_units,
            batch_index=1,
            batch_count=len(grouping_task_files),
            total_grouping_unit_count=sum(
                len(batch_unit_ids) for batch_unit_ids in grouping_batch_unit_ids
            ),
            max_units_per_batch=int(
                grouping_limits.get("max_units_per_batch")
                or KNOWLEDGE_GROUP_TASK_MAX_UNITS
            ),
            max_evidence_chars_per_batch=int(
                grouping_limits.get("max_evidence_chars_per_batch")
                or KNOWLEDGE_GROUP_TASK_MAX_EVIDENCE_CHARS
            ),
        )
        total_grouping_unit_count = sum(len(batch_unit_ids) for batch_unit_ids in grouping_batch_unit_ids)
        grouping_batch_metadata = _coerce_dict(grouping_task_file.get("grouping_batch"))
        return KnowledgeTaskFileTransition(
            status="advance_to_grouping",
            current_stage_key=KNOWLEDGE_CLASSIFY_STAGE_KEY,
            next_stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
            next_task_file=grouping_task_file,
            validated_answers_by_unit_id=combined_answers_by_unit_id,
            validation_metadata=dict(validation_metadata),
            transition_metadata={
                "grouping_unit_count": total_grouping_unit_count,
                "grouping_batch_count": len(grouping_task_files),
                "current_grouping_batch_index": max(
                    int(grouping_batch_metadata.get("current_batch_index") or 0),
                    1,
                ),
                "current_grouping_batch_unit_count": int(
                    grouping_batch_metadata.get("unit_count") or 0
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
    grouping_limits = _coerce_dict(classification_task_file.get("grouping_limits"))
    (
        grouping_task_files,
        _grouping_unit_to_shard_id,
        grouping_batch_unit_ids,
    ) = build_knowledge_grouping_task_files(
        assignment_id=str(original_task_file.get("assignment_id") or ""),
        worker_id=str(original_task_file.get("worker_id") or ""),
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id=classification_answers_by_unit_id,
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
    unanswered_batch_indices = [
        batch_index
        for batch_index, batch_unit_ids in enumerate(grouping_batch_unit_ids)
        if any(unit_id not in combined_grouping_answers_by_unit_id for unit_id in batch_unit_ids)
    ]
    if unanswered_batch_indices:
        next_batch_index = unanswered_batch_indices[0]
        next_batch_unit_ids = grouping_batch_unit_ids[next_batch_index]
        next_grouping_units = [
            unit
            for unit in (grouping_task_files[next_batch_index].get("units") or [])
            if isinstance(unit, Mapping)
            and str(unit.get("unit_id") or "").strip() in set(next_batch_unit_ids)
        ]
        next_grouping_task_file = _build_knowledge_same_session_grouping_task_file_from_units(
            assignment_id=str(original_task_file.get("assignment_id") or ""),
            worker_id=str(original_task_file.get("worker_id") or ""),
            units=next_grouping_units,
            batch_index=next_batch_index + 1,
            batch_count=len(grouping_task_files),
            total_grouping_unit_count=sum(
                len(batch_unit_ids) for batch_unit_ids in grouping_batch_unit_ids
            ),
            max_units_per_batch=int(
                grouping_limits.get("max_units_per_batch")
                or KNOWLEDGE_GROUP_TASK_MAX_UNITS
            ),
            max_evidence_chars_per_batch=int(
                grouping_limits.get("max_evidence_chars_per_batch")
                or KNOWLEDGE_GROUP_TASK_MAX_EVIDENCE_CHARS
            ),
        )
        next_grouping_batch_metadata = _coerce_dict(
            next_grouping_task_file.get("grouping_batch")
        )
        pending_grouping_batches = [
            batch_unit_ids
            for batch_unit_ids in grouping_batch_unit_ids[next_batch_index + 1 :]
            if any(unit_id not in combined_grouping_answers_by_unit_id for unit_id in batch_unit_ids)
        ]
        return KnowledgeTaskFileTransition(
            status="advance_to_grouping",
            current_stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
            next_stage_key=KNOWLEDGE_GROUP_STAGE_KEY,
            next_task_file=next_grouping_task_file,
            validated_answers_by_unit_id=combined_grouping_answers_by_unit_id,
            validation_metadata=dict(validation_metadata),
            transition_metadata={
                "grouping_batch_count": len(grouping_task_files),
                "current_grouping_batch_index": max(
                    int(next_grouping_batch_metadata.get("current_batch_index") or 0),
                    1,
                ),
                "current_grouping_batch_unit_count": int(
                    next_grouping_batch_metadata.get("unit_count") or 0
                ),
                "pending_grouping_unit_batches": pending_grouping_batches,
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
