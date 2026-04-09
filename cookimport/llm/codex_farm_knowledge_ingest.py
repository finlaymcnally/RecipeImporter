from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.core.models import KnowledgeChunk
from cookimport.parsing.chunks import summarize_chunk_utility_profile

from .codex_farm_knowledge_contracts import knowledge_input_packets
from .phase_worker_runtime import ShardManifestEntryV1
from .codex_farm_knowledge_models import (
    ALLOWED_KNOWLEDGE_REASON_CODES,
    KnowledgeBundleOutputV2,
    KnowledgePacketSemanticResultV1,
    serialize_canonical_knowledge_packet,
)
from .knowledge_tag_catalog import load_knowledge_tag_catalog, normalize_knowledge_tag_key

_KNOWLEDGE_SCHEMA_OR_SHAPE_VALIDATION_ERRORS = frozenset(
    {
        "response_json_invalid",
        "response_not_json_object",
        "schema_invalid",
    }
)
_KNOWLEDGE_COVERAGE_VALIDATION_ERRORS = frozenset(
    {
        "missing_owned_packet_results",
        "unexpected_packet_results",
        "duplicate_packet_results",
        "packet_result_validation_failed",
        "missing_owned_block_decisions",
        "unexpected_block_decisions",
        "block_decision_order_mismatch",
        "knowledge_block_missing_group",
        "knowledge_block_group_conflict",
        "group_contains_other_block",
        "unknown_grounding_tag_key",
        "unknown_grounding_category_key",
        "invalid_proposed_tag_key",
        "invalid_proposed_tag_display_name",
        "proposed_tag_key_conflicts_existing",
    }
)
_KNOWLEDGE_REPAIRABLE_NEAR_MISS_ERRORS = frozenset(
    {
        "missing_owned_packet_results",
        "unexpected_packet_results",
        "duplicate_packet_results",
        "response_json_invalid",
        "response_not_json_object",
        "schema_invalid",
        "missing_owned_block_decisions",
        "unexpected_block_decisions",
        "block_decision_order_mismatch",
        "knowledge_block_missing_group",
        "knowledge_block_group_conflict",
        "group_contains_other_block",
        "unknown_grounding_tag_key",
        "unknown_grounding_category_key",
        "invalid_proposed_tag_key",
        "invalid_proposed_tag_display_name",
        "proposed_tag_key_conflicts_existing",
    }
)


def normalize_knowledge_worker_payload(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload_dict = dict(payload)
    try:
        semantic_result = KnowledgePacketSemanticResultV1.model_validate(payload_dict)
    except Exception:
        parsed = KnowledgeBundleOutputV2.model_validate(payload_dict)
        normalized_payload = parsed.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
            exclude_defaults=True,
        )
        normalized_payload.pop("v", None)
        return normalized_payload, {
            "worker_output_contract": "canonical_packet_result_v3",
            "allowed_reason_codes": list(ALLOWED_KNOWLEDGE_REASON_CODES),
        }
    return serialize_canonical_knowledge_packet(semantic_result), {
        "worker_output_contract": "semantic_packet_result_v2",
        "allowed_reason_codes": list(ALLOWED_KNOWLEDGE_REASON_CODES),
    }


def _block_rows_by_index_for_shard(
    shard: ShardManifestEntryV1,
) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for packet in knowledge_input_packets(dict(shard.input_payload or {})):
        for block in (packet.get("b") or packet.get("blocks") or []):
            if not isinstance(block, Mapping):
                continue
            block_index = block.get("i")
            if block_index is None:
                block_index = block.get("block_index")
            try:
                normalized_block_index = int(block_index)
            except (TypeError, ValueError):
                continue
            rows[normalized_block_index] = dict(block)
    return rows


def _low_utility_reason_for_block(
    block_row: Mapping[str, Any] | None,
) -> tuple[str | None, dict[str, Any]]:
    row = _coerce_dict(block_row)
    text = str(row.get("t") or row.get("text") or "").strip()
    if not text:
        return "not_cooking_knowledge", {
            "text": "",
            "positive_cues": [],
            "negative_cues": [],
            "strong_negative_cue": False,
            "borderline": False,
        }
    utility_profile = summarize_chunk_utility_profile(KnowledgeChunk(text=text))
    positive_cues = [
        str(value).strip()
        for value in (utility_profile.get("positive_cues") or [])
        if str(value).strip()
    ]
    negative_cues = [
        str(value).strip()
        for value in (utility_profile.get("negative_cues") or [])
        if str(value).strip()
    ]
    strong_negative_cue = bool(utility_profile.get("strong_negative_cue"))
    borderline = bool(utility_profile.get("borderline"))
    reason_code: str | None = None

    if "book_framing_or_marketing" in negative_cues:
        reason_code = "book_framing_or_marketing"
    elif "navigation_or_taxonomy" in negative_cues:
        reason_code = "navigation_or_chapter_taxonomy"
    elif "rhetorical_heading" in negative_cues and not positive_cues:
        reason_code = "decorative_heading_only"
    elif "memoir_or_voice" in negative_cues and not positive_cues:
        reason_code = "memoir_or_scene_setting"
    elif "true_but_low_utility" in negative_cues and not strong_negative_cue:
        reason_code = "true_but_low_utility"

    return reason_code, {
        "text": text,
        "positive_cues": positive_cues,
        "negative_cues": negative_cues,
        "strong_negative_cue": strong_negative_cue,
        "borderline": borderline,
    }


def sanitize_knowledge_worker_payload_for_shard(
    shard: ShardManifestEntryV1,
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_payload, normalization_metadata = normalize_knowledge_worker_payload(payload)
    parsed = KnowledgeBundleOutputV2.model_validate(normalized_payload)
    block_rows_by_index = _block_rows_by_index_for_shard(shard)

    demoted_block_indices: set[int] = set()
    demotion_details: list[dict[str, Any]] = []
    serialized_decisions: list[dict[str, Any]] = []
    for decision in parsed.block_decisions:
        block_index = int(decision.block_index)
        category = str(decision.category)
        if category != "knowledge":
            serialized_decisions.append(
                {
                    "i": block_index,
                    "c": category,
                    "gr": _serialize_grounding_for_payload(decision.grounding),
                }
            )
            continue
        reason_code, utility_metadata = _low_utility_reason_for_block(
            block_rows_by_index.get(block_index)
        )
        if reason_code is not None:
            demoted_block_indices.add(block_index)
            demotion_details.append(
                {
                    "block_index": block_index,
                    "reason_code": reason_code,
                    "positive_cues": list(utility_metadata.get("positive_cues") or []),
                    "negative_cues": list(utility_metadata.get("negative_cues") or []),
                    "strong_negative_cue": bool(
                        utility_metadata.get("strong_negative_cue")
                    ),
                    "borderline": bool(utility_metadata.get("borderline")),
                    "text": str(utility_metadata.get("text") or ""),
                }
            )
            serialized_decisions.append(
                {
                    "i": block_index,
                    "c": "other",
                    "gr": {"tk": [], "ck": [], "pt": []},
                }
            )
            continue
        serialized_decisions.append(
            {
                "i": block_index,
                "c": category,
                "gr": _serialize_grounding_for_payload(decision.grounding),
            }
        )

    serialized_groups: list[dict[str, Any]] = []
    dropped_group_ids: list[str] = []
    for group in parsed.idea_groups:
        surviving_block_indices = [
            int(block_index)
            for block_index in group.block_indices
            if int(block_index) not in demoted_block_indices
        ]
        if not surviving_block_indices:
            dropped_group_ids.append(str(group.group_id))
            continue
        serialized_groups.append(
            {
                "gid": str(group.group_id),
                "l": str(group.topic_label),
                "bi": surviving_block_indices,
                "s": [
                    {
                        "b": str(snippet.body),
                        "e": [
                            {
                                "i": int(evidence.block_index),
                                "q": str(evidence.quote),
                            }
                            for evidence in snippet.evidence
                        ],
                    }
                    for snippet in group.snippets
                ],
            }
        )

    reason_counts: dict[str, int] = {}
    for detail in demotion_details:
        reason_code = str(detail.get("reason_code") or "").strip()
        if not reason_code:
            continue
        reason_counts[reason_code] = int(reason_counts.get(reason_code) or 0) + 1
    primary_reason_code = None
    if reason_counts:
        primary_reason_code = sorted(
            reason_counts.items(),
            key=lambda row: (-int(row[1]), str(row[0])),
        )[0][0]

    return {
        "v": "3",
        "bid": parsed.bundle_id,
        "d": serialized_decisions,
        "g": serialized_groups,
    }, {
        **dict(normalization_metadata),
        "deterministic_other_bypass_block_count": len(demotion_details),
        "deterministic_other_bypass_reason_counts": dict(sorted(reason_counts.items())),
        "deterministic_other_bypass_details": demotion_details,
        "dropped_idea_group_count_after_bypass": len(dropped_group_ids),
        "dropped_idea_group_ids_after_bypass": sorted(
            group_id for group_id in dropped_group_ids if group_id
        ),
        "deterministic_bypass_reason_code": primary_reason_code,
    }


def _serialize_grounding_for_payload(grounding: Any) -> dict[str, Any]:
    return {
        "tk": [
            str(value).strip()
            for value in (getattr(grounding, "tag_keys", ()) or ())
            if str(value).strip()
        ],
        "ck": [
            str(value).strip()
            for value in (getattr(grounding, "category_keys", ()) or ())
            if str(value).strip()
        ],
        "pt": [
            {
                "k": str(tag.key).strip(),
                "d": str(tag.display_name).strip(),
                "ck": str(tag.category_key).strip(),
            }
            for tag in (getattr(grounding, "proposed_tags", ()) or ())
            if str(getattr(tag, "key", "")).strip()
        ],
    }


def validate_knowledge_shard_output(
    shard: ShardManifestEntryV1,
    payload: dict[str, Any],
) -> tuple[bool, tuple[str, ...], dict[str, Any]]:
    sanitized_payload, sanitize_metadata = sanitize_knowledge_worker_payload_for_shard(
        shard,
        payload,
    )
    packet_surfaces = _packet_surfaces_for_shard(shard)
    metadata: dict[str, Any] = {
        "owned_packet_count": len(packet_surfaces),
        "owned_packet_ids": [surface["packet_id"] for surface in packet_surfaces],
        "owned_block_indices": [
            block_index
            for surface in packet_surfaces
            for block_index in surface["owned_block_indices"]
        ],
        "owned_block_count": sum(
            len(surface["owned_block_indices"]) for surface in packet_surfaces
        ),
        **dict(sanitize_metadata or {}),
    }
    packet_results = sanitized_payload.get("packet_results")
    if not isinstance(packet_results, list):
        packet_results = sanitized_payload.get("results")
    if not isinstance(packet_results, list):
        if len(packet_surfaces) > 1:
            return False, ("schema_invalid",), {
                **metadata,
                "parse_error": "multi-packet shard payload must use `packet_results`",
            }
        valid, errors, packet_metadata = _validate_single_packet_payload(
            packet_surface=packet_surfaces[0],
            payload=sanitized_payload,
        )
        return valid, errors, {
            **dict(metadata),
            **dict(packet_metadata or {}),
        }

    errors: list[str] = []
    seen_packet_ids: set[str] = set()
    unexpected_packet_ids: list[str] = []
    duplicate_packet_ids: list[str] = []
    invalid_packet_ids: list[str] = []
    missing_owned_block_indices: list[int] = []
    child_validation_errors_by_packet_id: dict[str, list[str]] = {}
    validated_packet_count = 0
    result_block_decision_count = 0
    idea_group_count = 0
    knowledge_decision_count = 0
    reviewed_all_other = True
    packet_surface_by_id = {
        surface["packet_id"]: surface for surface in packet_surfaces
    }
    for packet_result in packet_results:
        if not isinstance(packet_result, Mapping):
            errors.append("packet_result_not_json_object")
            continue
        packet_id = str(
            packet_result.get("packet_id") or packet_result.get("bid") or ""
        ).strip()
        if not packet_id:
            errors.append("packet_result_missing_packet_id")
            continue
        if packet_id in seen_packet_ids:
            duplicate_packet_ids.append(packet_id)
            continue
        seen_packet_ids.add(packet_id)
        packet_surface = packet_surface_by_id.get(packet_id)
        if packet_surface is None:
            unexpected_packet_ids.append(packet_id)
            continue
        valid, packet_errors, packet_metadata = _validate_single_packet_payload(
            packet_surface=packet_surface,
            payload=dict(packet_result),
        )
        if valid:
            validated_packet_count += 1
        else:
            invalid_packet_ids.append(packet_id)
            child_validation_errors_by_packet_id[packet_id] = list(packet_errors)
            missing_owned_block_indices.extend(packet_surface["owned_block_indices"])
        result_block_decision_count += int(
            packet_metadata.get("result_block_decision_count") or 0
        )
        idea_group_count += int(packet_metadata.get("idea_group_count") or 0)
        knowledge_decision_count += int(
            packet_metadata.get("knowledge_decision_count") or 0
        )
        reviewed_all_other = reviewed_all_other and bool(
            packet_metadata.get("reviewed_all_other")
        )
    missing_packet_ids = [
        packet_id
        for packet_id in packet_surface_by_id
        if packet_id not in seen_packet_ids
    ]
    if unexpected_packet_ids:
        errors.append("unexpected_packet_results")
        metadata["unexpected_packet_ids"] = sorted(set(unexpected_packet_ids))
    if duplicate_packet_ids:
        errors.append("duplicate_packet_results")
        metadata["duplicate_packet_ids"] = sorted(set(duplicate_packet_ids))
    if missing_packet_ids:
        errors.append("missing_owned_packet_results")
        metadata["missing_packet_ids"] = missing_packet_ids
        missing_owned_block_indices.extend(
            block_index
            for packet_id in missing_packet_ids
            for block_index in packet_surface_by_id[packet_id]["owned_block_indices"]
        )
    if invalid_packet_ids:
        errors.append("packet_result_validation_failed")
        metadata["invalid_packet_result_ids"] = sorted(set(invalid_packet_ids))
        metadata["packet_validation_errors_by_packet_id"] = dict(
            sorted(child_validation_errors_by_packet_id.items())
        )
    if missing_owned_block_indices:
        metadata["missing_owned_block_indices"] = sorted(set(missing_owned_block_indices))
    metadata["validated_packet_count"] = validated_packet_count
    metadata["result_block_decision_count"] = result_block_decision_count
    metadata["idea_group_count"] = idea_group_count
    metadata["knowledge_decision_count"] = knowledge_decision_count
    metadata["reviewed_all_other"] = (
        not errors
        and validated_packet_count == len(packet_surfaces)
        and reviewed_all_other
    )
    return not errors, tuple(errors), metadata


def classify_knowledge_validation_failure(
    *,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    errors = tuple(
        str(error).strip()
        for error in validation_errors
        if str(error).strip()
    )
    error_set = set(errors)
    has_schema_or_shape_error = bool(
        error_set.intersection(_KNOWLEDGE_SCHEMA_OR_SHAPE_VALIDATION_ERRORS)
    )
    has_coverage_error = bool(error_set.intersection(_KNOWLEDGE_COVERAGE_VALIDATION_ERRORS))
    repairable_near_miss = bool(error_set) and error_set.issubset(
        _KNOWLEDGE_REPAIRABLE_NEAR_MISS_ERRORS
    )
    classification = "other_invalid"
    reason_code = "validation_failed"
    reason_detail = ""

    if repairable_near_miss:
        classification = "repairable_near_miss"
        reason_code = "repairable_near_miss"
        reason_detail = (
            "The output is close to valid but still misses one narrow contract or coverage "
            "requirement."
        )
    elif has_schema_or_shape_error:
        classification = "schema_or_shape_invalid"
        reason_code = "schema_or_shape_invalid"
        reason_detail = "The output does not match the required JSON object shape."
    elif has_coverage_error:
        classification = "coverage_mismatch"
        reason_code = "coverage_mismatch"
        reason_detail = (
            "The output does not cover exactly the owned block surface or valid knowledge groups."
        )
    return {
        "classification": classification,
        "errors": list(errors),
        "reason_code": reason_code,
        "reason_detail": reason_detail,
        "has_schema_or_shape_error": has_schema_or_shape_error,
        "has_coverage_error": has_coverage_error,
        "repairable_near_miss": repairable_near_miss,
        "snippet_only_repair": False,
    }


def extract_promotable_knowledge_bundles(
    *,
    payload: Mapping[str, Any] | None,
    validation_errors: Sequence[str] = (),
    validation_metadata: Mapping[str, Any] | None = None,
) -> tuple[dict[str, KnowledgeBundleOutputV2], dict[str, Any]] | None:
    metadata = _coerce_dict(validation_metadata)
    normalized_errors = _normalize_validation_errors(validation_errors)
    payload_dict = _coerce_dict(payload)
    if not payload_dict:
        if normalized_errors:
            return None
        raise ValueError("Invalid proposal wrapper: missing payload object.")
    packet_results = payload_dict.get("packet_results")
    if not isinstance(packet_results, list):
        packet_results = payload_dict.get("results")
    if isinstance(packet_results, list):
        outputs: dict[str, KnowledgeBundleOutputV2] = {}
        for packet_result in packet_results:
            if not isinstance(packet_result, Mapping):
                continue
            try:
                normalized_payload, _ = normalize_knowledge_worker_payload(dict(packet_result))
                parsed = KnowledgeBundleOutputV2.model_validate(normalized_payload)
            except Exception:
                continue
            if parsed.bundle_id in outputs:
                return None
            outputs[parsed.bundle_id] = parsed
        if not outputs:
            return None
        promoted_packet_ids = sorted(outputs)
        missing_packet_ids = [
            str(packet_id).strip()
            for packet_id in (
                metadata.get("missing_packet_ids")
                or metadata.get("invalid_packet_result_ids")
                or []
            )
            if str(packet_id).strip()
        ]
        if not missing_packet_ids and normalized_errors:
            expected_packet_ids = [
                str(packet_id).strip()
                for packet_id in (metadata.get("owned_packet_ids") or [])
                if str(packet_id).strip()
            ]
            missing_packet_ids = sorted(set(expected_packet_ids) - set(promoted_packet_ids))
        return outputs, {
            "promotion_mode": "validated_wrapper",
            "partial": bool(normalized_errors) or bool(missing_packet_ids),
            "promoted_packet_ids": promoted_packet_ids,
            "promoted_packet_count": len(promoted_packet_ids),
            "missing_packet_ids": missing_packet_ids,
            "missing_owned_block_indices": list(
                metadata.get("missing_owned_block_indices") or []
            ),
        }
    if normalized_errors:
        return None
    normalized_payload, _ = normalize_knowledge_worker_payload(payload_dict)
    parsed = KnowledgeBundleOutputV2.model_validate(normalized_payload)
    return {parsed.bundle_id: parsed}, {
        "promotion_mode": "validated_wrapper",
        "partial": False,
        "promoted_packet_ids": [parsed.bundle_id],
        "promoted_packet_count": 1,
        "missing_packet_ids": [],
    }


def extract_promotable_knowledge_bundle(
    *,
    payload: Mapping[str, Any] | None,
    validation_errors: Sequence[str] = (),
    validation_metadata: Mapping[str, Any] | None = None,
) -> tuple[KnowledgeBundleOutputV2, dict[str, Any]] | None:
    promoted = extract_promotable_knowledge_bundles(
        payload=payload,
        validation_errors=validation_errors,
        validation_metadata=validation_metadata,
    )
    if promoted is None:
        return None
    outputs, promotion_metadata = promoted
    if len(outputs) != 1:
        return None
    bundle = next(iter(outputs.values()))
    return bundle, promotion_metadata


def read_validated_knowledge_outputs_from_proposals(
    proposals_dir: Path,
) -> tuple[dict[str, KnowledgeBundleOutputV2], dict[str, dict[str, Any]]]:
    outputs: dict[str, KnowledgeBundleOutputV2] = {}
    payloads_by_shard_id: dict[str, dict[str, Any]] = {}
    for proposal_path in sorted(proposals_dir.glob("*.json")):
        wrapper = json.loads(proposal_path.read_text(encoding="utf-8"))
        if not isinstance(wrapper, Mapping):
            raise ValueError(f"Invalid proposal wrapper {proposal_path}: expected object.")
        promoted_bundles = extract_promotable_knowledge_bundles(
            payload=wrapper.get("payload"),
            validation_errors=wrapper.get("validation_errors") or (),
            validation_metadata=(
                wrapper.get("validation_metadata")
                if isinstance(wrapper.get("validation_metadata"), Mapping)
                else wrapper.get("metadata")
            ),
        )
        if promoted_bundles is None:
            continue
        promoted_outputs, _ = promoted_bundles
        for packet_id, parsed in promoted_outputs.items():
            if packet_id in outputs:
                raise ValueError(
                    "Duplicate packet_id in validated knowledge proposals: "
                    f"{packet_id!r} (file={proposal_path.name})."
                )
            outputs[packet_id] = parsed
            payloads_by_shard_id[str(packet_id)] = parsed.model_dump(
                mode="json",
                by_alias=True,
            )
    return outputs, payloads_by_shard_id


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _normalize_validation_errors(validation_errors: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        str(error).strip()
        for error in validation_errors
        if str(error).strip()
    )


def _packet_surfaces_for_shard(shard: ShardManifestEntryV1) -> list[dict[str, Any]]:
    payload = dict(shard.input_payload or {})
    packet_surfaces: list[dict[str, Any]] = []
    for packet in knowledge_input_packets(payload):
        packet_id = str(packet.get("bid") or packet.get("packet_id") or "").strip()
        if not packet_id:
            continue
        owned_block_indices = [
            int(
                block.get("i")
                if block.get("i") is not None
                else block.get("block_index")
            )
            for block in (packet.get("b") or packet.get("blocks") or [])
            if isinstance(block, Mapping)
            and (block.get("i") is not None or block.get("block_index") is not None)
        ]
        packet_surfaces.append(
            {
                "packet_id": packet_id,
                "owned_block_indices": owned_block_indices,
            }
        )
    if packet_surfaces:
        return packet_surfaces
    owned_block_indices = [
        int(value)
        for value in (dict(shard.metadata or {}).get("owned_block_indices") or [])
        if value is not None
    ]
    return [
        {
            "packet_id": str(shard.shard_id).strip(),
            "owned_block_indices": owned_block_indices,
        }
    ]


def _validate_single_packet_payload(
    *,
    packet_surface: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> tuple[bool, tuple[str, ...], dict[str, Any]]:
    packet_id = str(packet_surface.get("packet_id") or "").strip()
    metadata: dict[str, Any] = {
        "bundle_id": packet_id,
        "owned_block_indices": list(packet_surface.get("owned_block_indices") or []),
        "owned_block_count": len(packet_surface.get("owned_block_indices") or []),
    }
    try:
        normalized_payload, normalization_metadata = normalize_knowledge_worker_payload(dict(payload))
        parsed = KnowledgeBundleOutputV2.model_validate(normalized_payload)
        metadata.update(normalization_metadata)
    except Exception as exc:
        return False, ("schema_invalid",), {
            **metadata,
            "parse_error": str(exc),
        }
    if parsed.bundle_id != packet_id:
        return False, ("unexpected_packet_results",), {
            **metadata,
            "returned_packet_id": parsed.bundle_id,
        }

    expected_block_indices = [int(value) for value in packet_surface.get("owned_block_indices") or []]
    actual_block_indices = [int(row.block_index) for row in parsed.block_decisions]
    metadata["result_block_decision_count"] = len(actual_block_indices)
    metadata["idea_group_count"] = len(parsed.idea_groups)
    metadata["knowledge_decision_count"] = sum(
        1
        for row in parsed.block_decisions
        if str(row.category) == "knowledge"
    )
    metadata["reviewed_all_other"] = (
        actual_block_indices == expected_block_indices
        and metadata["knowledge_decision_count"] == 0
        and not parsed.idea_groups
    )

    errors: list[str] = []
    catalog = load_knowledge_tag_catalog()
    unknown_grounding_tag_keys: set[str] = set()
    unknown_grounding_category_keys: set[str] = set()
    invalid_proposed_tag_keys: set[str] = set()
    invalid_proposed_tag_display_names: set[str] = set()
    proposed_tag_key_conflicts_existing: set[str] = set()
    for row in parsed.block_decisions:
        for tag_key in row.grounding.tag_keys:
            normalized_tag_key = normalize_knowledge_tag_key(tag_key)
            if normalized_tag_key not in catalog.tag_by_key:
                unknown_grounding_tag_keys.add(normalized_tag_key)
        for category_key in row.grounding.category_keys:
            normalized_category_key = normalize_knowledge_tag_key(category_key)
            if normalized_category_key not in catalog.category_by_key:
                unknown_grounding_category_keys.add(normalized_category_key)
        for proposed_tag in row.grounding.proposed_tags:
            normalized_proposed_key = normalize_knowledge_tag_key(proposed_tag.key)
            if proposed_tag.key != normalized_proposed_key or not normalized_proposed_key:
                invalid_proposed_tag_keys.add(str(proposed_tag.key))
            if normalized_proposed_key in catalog.tag_by_key:
                proposed_tag_key_conflicts_existing.add(normalized_proposed_key)
            normalized_category_key = normalize_knowledge_tag_key(proposed_tag.category_key)
            if normalized_category_key not in catalog.category_by_key:
                unknown_grounding_category_keys.add(normalized_category_key)
            if not str(proposed_tag.display_name).strip() or len(str(proposed_tag.display_name).strip()) > 64:
                invalid_proposed_tag_display_names.add(str(proposed_tag.display_name))
    if unknown_grounding_tag_keys:
        errors.append("unknown_grounding_tag_key")
        metadata["unknown_grounding_tag_keys"] = sorted(unknown_grounding_tag_keys)
    if unknown_grounding_category_keys:
        errors.append("unknown_grounding_category_key")
        metadata["unknown_grounding_category_keys"] = sorted(unknown_grounding_category_keys)
    if invalid_proposed_tag_keys:
        errors.append("invalid_proposed_tag_key")
        metadata["invalid_proposed_tag_keys"] = sorted(invalid_proposed_tag_keys)
    if invalid_proposed_tag_display_names:
        errors.append("invalid_proposed_tag_display_name")
        metadata["invalid_proposed_tag_display_names"] = sorted(
            invalid_proposed_tag_display_names
        )
    if proposed_tag_key_conflicts_existing:
        errors.append("proposed_tag_key_conflicts_existing")
        metadata["proposed_tag_key_conflicts_existing"] = sorted(
            proposed_tag_key_conflicts_existing
        )
    if actual_block_indices != expected_block_indices:
        missing = [idx for idx in expected_block_indices if idx not in actual_block_indices]
        unexpected = [idx for idx in actual_block_indices if idx not in expected_block_indices]
        if missing:
            errors.append("missing_owned_block_decisions")
            metadata["missing_owned_block_indices"] = missing
        if unexpected:
            errors.append("unexpected_block_decisions")
            metadata["unexpected_block_indices"] = unexpected
        if not missing and not unexpected:
            errors.append("block_decision_order_mismatch")

    category_by_block = {
        int(row.block_index): str(row.category)
        for row in parsed.block_decisions
    }
    grouped_blocks: dict[int, str] = {}
    group_labels_by_id: dict[str, str] = {}
    conflicting_blocks: set[int] = set()
    groups_on_other_blocks: set[int] = set()
    for group in parsed.idea_groups:
        normalized_group_id = str(group.group_id).strip()
        normalized_topic_label = str(group.topic_label).strip()
        previous_topic = group_labels_by_id.get(normalized_group_id)
        if previous_topic is None:
            group_labels_by_id[normalized_group_id] = normalized_topic_label
        elif previous_topic != normalized_topic_label:
            errors.append("knowledge_block_group_conflict")
            metadata.setdefault("group_id_topic_conflicts", []).append(normalized_group_id)
        for block_index in group.block_indices:
            normalized_block_index = int(block_index)
            if category_by_block.get(normalized_block_index) != "knowledge":
                groups_on_other_blocks.add(normalized_block_index)
                continue
            previous_group_id = grouped_blocks.get(normalized_block_index)
            if previous_group_id is None:
                grouped_blocks[normalized_block_index] = normalized_group_id
                continue
            if previous_group_id != normalized_group_id:
                conflicting_blocks.add(normalized_block_index)
    knowledge_blocks = [
        block_index
        for block_index in expected_block_indices
        if category_by_block.get(block_index) == "knowledge"
    ]
    missing_group_blocks = [
        block_index for block_index in knowledge_blocks if block_index not in grouped_blocks
    ]
    if missing_group_blocks:
        errors.append("knowledge_block_missing_group")
        metadata["knowledge_blocks_missing_group"] = missing_group_blocks
    if conflicting_blocks:
        errors.append("knowledge_block_group_conflict")
        metadata["knowledge_blocks_with_group_conflicts"] = sorted(conflicting_blocks)
    if groups_on_other_blocks:
        errors.append("group_contains_other_block")
        metadata["group_blocks_out_of_surface"] = sorted(groups_on_other_blocks)
    return not errors, tuple(dict.fromkeys(errors)), metadata
