from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .codex_farm_knowledge_contracts import knowledge_input_packets
from .phase_worker_runtime import ShardManifestEntryV1
from .codex_farm_knowledge_models import (
    ALLOWED_KNOWLEDGE_REASON_CODES,
    KnowledgeBundleOutputV2,
    KnowledgePacketSemanticResultV1,
    serialize_canonical_knowledge_packet,
)

_KNOWLEDGE_SNIPPET_COPY_VALIDATION_ERRORS = frozenset(
    {
        "semantic_snippet_echoes_packet_surface",
        "semantic_snippet_copies_evidence_quote",
    }
)
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
    }
)
_GROUNDING_WORD_RE = re.compile(r"[A-Za-z]{3,}")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_knowledge_worker_payload(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload_dict = dict(payload)
    try:
        semantic_result = KnowledgePacketSemanticResultV1.model_validate(payload_dict)
    except Exception:
        parsed = KnowledgeBundleOutputV2.model_validate(payload_dict)
        return parsed.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
            exclude_defaults=True,
        ), {
            "worker_output_contract": "canonical_packet_result_v3",
            "allowed_reason_codes": list(ALLOWED_KNOWLEDGE_REASON_CODES),
        }
    return serialize_canonical_knowledge_packet(semantic_result), {
        "worker_output_contract": "semantic_packet_result_v2",
        "allowed_reason_codes": list(ALLOWED_KNOWLEDGE_REASON_CODES),
    }


def validate_knowledge_shard_output(
    shard: ShardManifestEntryV1,
    payload: dict[str, Any],
) -> tuple[bool, tuple[str, ...], dict[str, Any]]:
    packet_surfaces = _packet_surfaces_for_shard(shard)
    metadata: dict[str, Any] = {
        "owned_packet_count": len(packet_surfaces),
        "owned_packet_ids": [surface["packet_id"] for surface in packet_surfaces],
        "owned_block_indices": [
            block_index
            for surface in packet_surfaces
            for block_index in surface["owned_block_indices"]
        ],
        "owned_block_count": sum(len(surface["owned_block_indices"]) for surface in packet_surfaces),
    }
    packet_results = payload.get("packet_results")
    if not isinstance(packet_results, list):
        packet_results = payload.get("results")
    if not isinstance(packet_results, list):
        if len(packet_surfaces) > 1:
            return False, ("schema_invalid",), {
                **metadata,
                "parse_error": "multi-packet shard payload must use `packet_results`",
            }
        return _validate_single_packet_payload(
            packet_surface=packet_surfaces[0],
            payload=payload,
        )

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
    snippet_count = 0
    reviewed_with_useful_packets = False
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
            missing_owned_block_indices.extend(
                packet_surface["owned_block_indices"]
            )
        result_block_decision_count += int(packet_metadata.get("result_block_decision_count") or 0)
        idea_group_count += int(packet_metadata.get("idea_group_count") or 0)
        knowledge_decision_count += int(packet_metadata.get("knowledge_decision_count") or 0)
        snippet_count += int(packet_metadata.get("snippet_count") or 0)
        reviewed_with_useful_packets = reviewed_with_useful_packets or bool(
            packet_metadata.get("reviewed_with_useful_chunks")
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
    metadata["snippet_count"] = snippet_count
    metadata["reviewed_with_useful_chunks"] = reviewed_with_useful_packets
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
    metadata = dict(validation_metadata or {})
    error_set = set(errors)
    has_snippet_copy_error = bool(
        error_set.intersection(_KNOWLEDGE_SNIPPET_COPY_VALIDATION_ERRORS)
    )
    snippet_copy_only = bool(error_set) and error_set.issubset(
        _KNOWLEDGE_SNIPPET_COPY_VALIDATION_ERRORS
    )
    has_schema_or_shape_error = bool(
        error_set.intersection(_KNOWLEDGE_SCHEMA_OR_SHAPE_VALIDATION_ERRORS)
    )
    has_coverage_error = bool(error_set.intersection(_KNOWLEDGE_COVERAGE_VALIDATION_ERRORS))
    has_non_grounded_snippet = bool(metadata.get("non_grounded_idea_group_ids"))
    repairable_near_miss = False
    classification = "other_invalid"
    reason_code = "validation_failed"
    reason_detail = ""

    if snippet_copy_only:
        classification = "snippet_copy_only"
        repairable_near_miss = True
        reason_code = "snippet_copy_only"
        reason_detail = (
            "At least one snippet body copies the cited evidence or the full owned packet "
            "surface too closely."
        )
    elif (
        error_set
        and len(error_set) <= 2
        and error_set.issubset(_KNOWLEDGE_REPAIRABLE_NEAR_MISS_ERRORS)
        and not has_non_grounded_snippet
        and not has_snippet_copy_error
    ):
        classification = "repairable_near_miss"
        repairable_near_miss = True
        reason_code = "repairable_near_miss"
        reason_detail = (
            "The output is close to valid but still misses one narrow contract or shape "
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
    elif has_snippet_copy_error or has_non_grounded_snippet or any(
        error.startswith("semantic_") for error in error_set
    ):
        classification = "semantic_invalid"
        reason_code = "semantic_invalid"
        reason_detail = "The output is structurally valid but semantically low trust."

    return {
        "classification": classification,
        "errors": list(errors),
        "reason_code": reason_code,
        "reason_detail": reason_detail,
        "snippet_copy_only": snippet_copy_only,
        "has_snippet_copy_error": has_snippet_copy_error,
        "has_schema_or_shape_error": has_schema_or_shape_error,
        "has_coverage_error": has_coverage_error,
        "repairable_near_miss": repairable_near_miss,
        "snippet_only_repair": snippet_copy_only,
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
                normalized_payload, _normalization_metadata = normalize_knowledge_worker_payload(
                    dict(packet_result)
                )
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
            "missing_owned_block_indices": list(metadata.get("missing_owned_block_indices") or []),
        }
    if normalized_errors:
        return None
    parsed = KnowledgeBundleOutputV2.model_validate(payload_dict)
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
        promoted_outputs, _promotion_metadata = promoted_bundles
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


def _normalize_validation_errors(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(error).strip() for error in value if str(error).strip())


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _owned_block_indices(shard: ShardManifestEntryV1) -> list[int]:
    indices = [
        value
        for value in (
            _coerce_int(item) for item in (shard.metadata.get("owned_block_indices") or [])
        )
        if value is not None
    ]
    if indices:
        return indices
    payload = dict(shard.input_payload) if isinstance(shard.input_payload, Mapping) else {}
    return [
        value
        for packet in knowledge_input_packets(payload)
        for value in (_coerce_int((block or {}).get("i")) for block in (packet.get("b") or []))
        if value is not None
    ]


def _owned_block_text_by_index(shard: ShardManifestEntryV1) -> dict[int, str]:
    payload = dict(shard.input_payload) if isinstance(shard.input_payload, Mapping) else {}
    owned_text: dict[int, str] = {}
    for packet in knowledge_input_packets(payload):
        for block in packet.get("b") or []:
            if not isinstance(block, Mapping):
                continue
            block_index = _coerce_int(block.get("i"))
            if block_index is None:
                continue
            owned_text[block_index] = str(block.get("t") or "").strip()
    return owned_text


def _packet_surfaces_for_shard(shard: ShardManifestEntryV1) -> list[dict[str, Any]]:
    payload = _coerce_dict(shard.input_payload)
    packet_payloads = knowledge_input_packets(payload)
    if not packet_payloads:
        return [
            {
                "packet_id": str(shard.shard_id).strip(),
                "owned_block_indices": _owned_block_indices(shard),
                "owned_block_text_by_index": _owned_block_text_by_index(shard),
            }
        ]
    surfaces: list[dict[str, Any]] = []
    for packet in packet_payloads:
        packet_id = str(packet.get("bid") or packet.get("packet_id") or "").strip()
        block_indices = [
            value
            for value in (_coerce_int((block or {}).get("i")) for block in (packet.get("b") or []))
            if value is not None
        ]
        block_text_by_index = {
            int(block_index): str(block.get("t") or "").strip()
            for block in (packet.get("b") or [])
            if isinstance(block, Mapping)
            for block_index in [_coerce_int(block.get("i"))]
            if block_index is not None
        }
        surfaces.append(
            {
                "packet_id": packet_id,
                "owned_block_indices": block_indices,
                "owned_block_text_by_index": block_text_by_index,
            }
        )
    return surfaces


def _validate_single_packet_payload(
    *,
    packet_surface: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> tuple[bool, tuple[str, ...], dict[str, Any]]:
    errors: list[str] = []
    metadata: dict[str, Any] = {
        "owned_packet_count": 1,
    }
    try:
        normalized_payload, normalization_metadata = normalize_knowledge_worker_payload(payload)
        parsed = KnowledgeBundleOutputV2.model_validate(normalized_payload)
    except Exception as exc:  # noqa: BLE001
        return False, ("schema_invalid",), {"parse_error": str(exc)}
    metadata.update(normalization_metadata)
    metadata["bundle_id"] = parsed.bundle_id
    expected_packet_id = str(packet_surface.get("packet_id") or "").strip()
    if expected_packet_id and parsed.bundle_id != expected_packet_id:
        errors.append("bundle_id_mismatch")

    owned_block_indices = [
        int(value)
        for value in (packet_surface.get("owned_block_indices") or [])
        if value is not None
    ]
    metadata["owned_block_indices"] = list(owned_block_indices)
    metadata["owned_block_count"] = len(owned_block_indices)
    decision_block_indices = [int(decision.block_index) for decision in parsed.block_decisions]
    metadata["result_block_decision_count"] = len(decision_block_indices)
    metadata["idea_group_count"] = len(parsed.idea_groups)

    decision_block_set = set(decision_block_indices)
    owned_block_set = set(owned_block_indices)
    missing_block_indices = [index for index in owned_block_indices if index not in decision_block_set]
    unexpected_block_indices = sorted(decision_block_set - owned_block_set)
    if missing_block_indices:
        errors.append("missing_owned_block_decisions")
        metadata["missing_owned_block_indices"] = missing_block_indices
    if unexpected_block_indices:
        errors.append("unexpected_block_decisions")
        metadata["unexpected_block_indices"] = unexpected_block_indices
    if not missing_block_indices and not unexpected_block_indices and decision_block_indices != owned_block_indices:
        errors.append("block_decision_order_mismatch")
        metadata["result_block_index_order"] = list(decision_block_indices)

    out_of_surface_evidence: list[int] = []
    decision_category_by_block = {
        int(decision.block_index): str(decision.category)
        for decision in parsed.block_decisions
    }
    knowledge_block_indices = [
        block_index
        for block_index in owned_block_indices
        if decision_category_by_block.get(block_index) == "knowledge"
    ]
    knowledge_group_count_by_block: dict[int, int] = {}
    group_contains_other_blocks: dict[str, list[int]] = {}
    group_out_of_surface_blocks: dict[str, list[int]] = {}
    for group in parsed.idea_groups:
        wrong_group_blocks: list[int] = []
        out_of_surface_group_blocks: list[int] = []
        for block_index in group.block_indices:
            if block_index not in owned_block_set:
                out_of_surface_group_blocks.append(int(block_index))
                continue
            if decision_category_by_block.get(int(block_index)) != "knowledge":
                wrong_group_blocks.append(int(block_index))
                continue
            knowledge_group_count_by_block[int(block_index)] = (
                knowledge_group_count_by_block.get(int(block_index), 0) + 1
            )
        if wrong_group_blocks:
            group_contains_other_blocks[group.group_id] = sorted(set(wrong_group_blocks))
        if out_of_surface_group_blocks:
            group_out_of_surface_blocks[group.group_id] = sorted(set(out_of_surface_group_blocks))
        for snippet in group.snippets:
            for evidence in snippet.evidence:
                if int(evidence.block_index) not in owned_block_set:
                    out_of_surface_evidence.append(int(evidence.block_index))
    if group_contains_other_blocks:
        errors.append("group_contains_other_block")
        metadata["group_contains_other_blocks"] = group_contains_other_blocks
    if group_out_of_surface_blocks:
        errors.append("idea_group_out_of_surface")
        metadata["idea_group_out_of_surface"] = group_out_of_surface_blocks
    if out_of_surface_evidence:
        errors.append("snippet_evidence_out_of_surface")
        metadata["out_of_surface_evidence_block_indices"] = sorted(set(out_of_surface_evidence))

    missing_group_blocks = [
        block_index
        for block_index in knowledge_block_indices
        if knowledge_group_count_by_block.get(block_index, 0) == 0
    ]
    duplicate_group_blocks = [
        block_index
        for block_index, count in sorted(knowledge_group_count_by_block.items())
        if count > 1
    ]
    if missing_group_blocks:
        errors.append("knowledge_block_missing_group")
        metadata["knowledge_blocks_missing_group"] = missing_group_blocks
    if duplicate_group_blocks:
        errors.append("knowledge_block_group_conflict")
        metadata["knowledge_blocks_with_multiple_groups"] = duplicate_group_blocks

    owned_block_text_by_index = {
        int(block_index): str(text).strip()
        for block_index, text in dict(packet_surface.get("owned_block_text_by_index") or {}).items()
    }
    snippet_count = 0
    non_grounded_groups: list[str] = []
    echoed_groups: list[str] = []
    copied_quote_groups: list[str] = []
    for group in parsed.idea_groups:
        group_surface = " ".join(
            owned_block_text_by_index.get(block_index, "")
            for block_index in group.block_indices
        ).strip()
        normalized_group_surface = _normalize_semantic_comparison_text(group_surface)
        for snippet in group.snippets:
            snippet_count += 1
            if not _contains_grounded_text(snippet.body):
                non_grounded_groups.append(group.group_id)
            normalized_body = _normalize_semantic_comparison_text(snippet.body)
            evidence_surface = " ".join(
                str(evidence.quote).strip()
                for evidence in snippet.evidence
                if str(evidence.quote).strip()
            ).strip()
            normalized_evidence_surface = _normalize_semantic_comparison_text(evidence_surface)
            if _looks_like_verbatim_surface_echo(
                normalized_body,
                normalized_evidence_surface,
                min_surface_chars=80,
                min_body_chars=80,
            ):
                copied_quote_groups.append(group.group_id)
            if _looks_like_verbatim_surface_echo(
                normalized_body,
                normalized_group_surface,
                min_surface_chars=160,
                min_body_chars=120,
            ):
                echoed_groups.append(group.group_id)
    if non_grounded_groups:
        errors.append("semantic_snippet_body_not_grounded_text")
        metadata["non_grounded_idea_group_ids"] = sorted(set(non_grounded_groups))
    if copied_quote_groups:
        errors.append("semantic_snippet_copies_evidence_quote")
        metadata["copied_quote_idea_group_ids"] = sorted(set(copied_quote_groups))
    if echoed_groups:
        errors.append("semantic_snippet_echoes_packet_surface")
        metadata["echoed_idea_group_ids"] = sorted(set(echoed_groups))

    metadata["knowledge_decision_count"] = len(knowledge_block_indices)
    metadata["snippet_count"] = snippet_count
    metadata["reviewed_with_useful_chunks"] = bool(parsed.idea_groups)
    metadata["reviewed_all_other"] = (
        not errors
        and not parsed.idea_groups
        and bool(parsed.block_decisions)
        and not knowledge_block_indices
    )
    return not errors, tuple(errors), metadata


def _normalize_semantic_comparison_text(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text)


def _contains_grounded_text(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(_GROUNDING_WORD_RE.search(text))


def _looks_like_verbatim_surface_echo(
    candidate_text: str,
    source_text: str,
    *,
    min_surface_chars: int,
    min_body_chars: int,
) -> bool:
    if not candidate_text or not source_text:
        return False
    if len(source_text) < min_surface_chars or len(candidate_text) < min_body_chars:
        return False
    return candidate_text in source_text or source_text in candidate_text
