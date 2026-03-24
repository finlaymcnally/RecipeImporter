from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase_worker_runtime import ShardManifestEntryV1
from .codex_farm_knowledge_models import (
    KnowledgePacketSemanticResultV1,
    KnowledgeBundleOutputV2,
    ALLOWED_KNOWLEDGE_FINAL_CATEGORIES,
    ALLOWED_KNOWLEDGE_REASON_CODES,
    serialize_canonical_knowledge_packet,
)
_KNOWLEDGE_SNIPPET_COPY_VALIDATION_ERRORS = frozenset(
    {
        "semantic_snippet_echoes_full_chunk",
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
        "missing_owned_chunk_results",
        "unexpected_chunk_results",
        "chunk_result_order_mismatch",
    }
)
_KNOWLEDGE_REPAIRABLE_NEAR_MISS_ERRORS = frozenset(
    {
        "response_json_invalid",
        "response_not_json_object",
        "schema_invalid",
        "missing_owned_chunk_results",
        "unexpected_chunk_results",
        "chunk_result_order_mismatch",
    }
)


def normalize_knowledge_worker_payload(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        semantic_result = KnowledgePacketSemanticResultV1.model_validate(dict(payload))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            "worker output did not match the semantic packet result v1 contract: "
            f"{exc}"
        ) from exc
    return serialize_canonical_knowledge_packet(semantic_result), {
        "worker_output_contract": "semantic_packet_result_v1",
        **_knowledge_reason_metadata(semantic_result),
    }


def _knowledge_reason_metadata(
    semantic_result: KnowledgePacketSemanticResultV1,
) -> dict[str, Any]:
    reason_code_by_chunk_id: dict[str, str] = {}
    reason_code_counts: dict[str, int] = {}
    useful_reason_code_counts: dict[str, int] = {}
    other_reason_code_counts: dict[str, int] = {}
    for chunk_result in semantic_result.chunk_results:
        reason_code = str(chunk_result.reason_code or "").strip()
        if not reason_code:
            continue
        reason_code_by_chunk_id[chunk_result.chunk_id] = reason_code
        reason_code_counts[reason_code] = reason_code_counts.get(reason_code, 0) + 1
        target_counts = (
            useful_reason_code_counts if chunk_result.is_useful else other_reason_code_counts
        )
        target_counts[reason_code] = target_counts.get(reason_code, 0) + 1
    metadata = {
        "allowed_reason_codes": list(ALLOWED_KNOWLEDGE_REASON_CODES),
        "reason_code_by_chunk_id": dict(sorted(reason_code_by_chunk_id.items())),
        "reason_code_counts": dict(sorted(reason_code_counts.items())),
        "useful_reason_code_counts": dict(sorted(useful_reason_code_counts.items())),
        "other_reason_code_counts": dict(sorted(other_reason_code_counts.items())),
    }
    if other_reason_code_counts:
        metadata["all_other_reason_code_counts"] = dict(sorted(other_reason_code_counts.items()))
    return metadata

def validate_knowledge_shard_output(
    shard: ShardManifestEntryV1,
    payload: dict[str, Any],
) -> tuple[bool, tuple[str, ...], dict[str, Any]]:
    errors: list[str] = []
    metadata: dict[str, Any] = {
        "owned_chunk_count": len(shard.owned_ids),
    }
    try:
        normalized_payload, normalization_metadata = normalize_knowledge_worker_payload(payload)
        parsed = KnowledgeBundleOutputV2.model_validate(normalized_payload)
    except Exception as exc:  # noqa: BLE001
        return False, ("schema_invalid",), {"parse_error": str(exc)}
    metadata.update(normalization_metadata)

    metadata["bundle_id"] = parsed.bundle_id
    metadata["result_chunk_count"] = len(parsed.chunk_results)
    if parsed.bundle_id != shard.shard_id:
        errors.append("bundle_id_mismatch")

    ordered_chunk_ids = _ordered_chunk_ids(shard)
    owned_chunk_ids = set(ordered_chunk_ids)
    metadata["ordered_chunk_ids"] = list(ordered_chunk_ids)
    result_chunk_ids = {result.chunk_id for result in parsed.chunk_results}
    result_chunk_id_order = [result.chunk_id for result in parsed.chunk_results]
    missing_owned_chunk_ids = sorted(owned_chunk_ids - result_chunk_ids)
    unexpected_chunk_ids = sorted(result_chunk_ids - owned_chunk_ids)
    if missing_owned_chunk_ids:
        errors.append("missing_owned_chunk_results")
        metadata["missing_owned_chunk_ids"] = missing_owned_chunk_ids
    if unexpected_chunk_ids:
        errors.append("unexpected_chunk_results")
        metadata["unexpected_chunk_ids"] = unexpected_chunk_ids
    if (
        not missing_owned_chunk_ids
        and not unexpected_chunk_ids
        and result_chunk_id_order != ordered_chunk_ids
    ):
        errors.append("chunk_result_order_mismatch")
        metadata["result_chunk_id_order"] = list(result_chunk_id_order)

    allowed_block_indices = {
        int(value)
        for value in (shard.metadata.get("owned_block_indices") or [])
        if _coerce_int(value) is not None
    }
    if allowed_block_indices:
        metadata["owned_block_count"] = len(allowed_block_indices)
        out_of_surface_decisions: list[int] = []
        out_of_surface_evidence: list[int] = []
        for result in parsed.chunk_results:
            for decision in result.block_decisions:
                if int(decision.block_index) not in allowed_block_indices:
                    out_of_surface_decisions.append(int(decision.block_index))
            for snippet in result.snippets:
                for evidence in snippet.evidence:
                    if int(evidence.block_index) not in allowed_block_indices:
                        out_of_surface_evidence.append(int(evidence.block_index))
        if out_of_surface_decisions:
            errors.append("block_decision_out_of_surface")
            metadata["out_of_surface_decision_block_indices"] = sorted(
                set(out_of_surface_decisions)
            )
        if out_of_surface_evidence:
            errors.append("snippet_evidence_out_of_surface")
            metadata["out_of_surface_evidence_block_indices"] = sorted(
                set(out_of_surface_evidence)
            )

    chunk_block_indices_by_id = _chunk_block_indices_by_id(shard)
    if chunk_block_indices_by_id:
        metadata["chunk_block_count_by_id"] = {
            chunk_id: len(block_indices)
            for chunk_id, block_indices in sorted(chunk_block_indices_by_id.items())
        }
        chunk_coverage_mismatches: dict[str, dict[str, list[int]]] = {}
        cross_chunk_evidence: dict[str, list[int]] = {}
        for result in parsed.chunk_results:
            expected_block_indices = chunk_block_indices_by_id.get(result.chunk_id)
            if expected_block_indices is None:
                continue
            observed_block_indices = [
                int(decision.block_index) for decision in result.block_decisions
            ]
            if observed_block_indices != expected_block_indices:
                chunk_coverage_mismatches[result.chunk_id] = {
                    "expected": list(expected_block_indices),
                    "observed": list(observed_block_indices),
                }
            wrong_chunk_evidence = sorted(
                {
                    int(evidence.block_index)
                    for snippet in result.snippets
                    for evidence in snippet.evidence
                    if int(evidence.block_index) not in expected_block_indices
                }
            )
            if wrong_chunk_evidence:
                cross_chunk_evidence[result.chunk_id] = wrong_chunk_evidence
        if chunk_coverage_mismatches:
            errors.append("block_decision_coverage_mismatch")
            metadata["chunk_block_coverage_mismatches"] = chunk_coverage_mismatches
        if cross_chunk_evidence:
            errors.append("snippet_evidence_wrong_chunk_surface")
            metadata["cross_chunk_evidence_by_chunk_id"] = cross_chunk_evidence

    useful_chunk_count = sum(1 for result in parsed.chunk_results if bool(result.is_useful))
    knowledge_decision_count = sum(
        1
        for result in parsed.chunk_results
        for decision in result.block_decisions
        if decision.category == "knowledge"
    )
    snippet_count = sum(len(result.snippets) for result in parsed.chunk_results)
    metadata["useful_chunk_count"] = useful_chunk_count
    metadata["knowledge_decision_count"] = knowledge_decision_count
    metadata["snippet_count"] = snippet_count

    non_grounded_snippet_chunk_ids: list[str] = []
    echoed_full_chunk_ids: list[str] = []
    snippet_echo_reasons_by_chunk_id: dict[str, set[str]] = {}
    evidence_surface_echoes_by_chunk_id: dict[str, list[dict[str, Any]]] = {}
    aggregate_copied_surface_by_chunk_id: dict[str, dict[str, Any]] = {}
    chunk_source_text_by_id = _chunk_source_text_by_id(shard)
    chunk_block_texts_by_id = _chunk_block_texts_by_id(shard)
    for result in parsed.chunk_results:
        source_text = chunk_source_text_by_id.get(result.chunk_id)
        normalized_source_text = _normalize_semantic_comparison_text(source_text)
        expected_block_indices = chunk_block_indices_by_id.get(result.chunk_id) or []
        copied_block_indices: set[int] = set()
        copied_snippet_count = 0
        for snippet_index, snippet in enumerate(result.snippets):
            if not _contains_grounded_text(snippet.body):
                non_grounded_snippet_chunk_ids.append(result.chunk_id)
            normalized_body = _normalize_semantic_comparison_text(snippet.body)
            evidence_surface_text = " ".join(
                str(evidence.quote).strip()
                for evidence in snippet.evidence
                if str(evidence.quote).strip()
            ).strip()
            normalized_evidence_surface = _normalize_semantic_comparison_text(
                evidence_surface_text
            )
            snippet_block_indices = sorted(
                {
                    int(evidence.block_index)
                    for evidence in snippet.evidence
                }
            )
            if (
                normalized_source_text
                and len(normalized_source_text) >= 160
                and len(normalized_body) >= max(120, int(len(normalized_source_text) * 0.85))
                and snippet_block_indices == expected_block_indices
                and _looks_like_verbatim_surface_echo(
                    normalized_body,
                    normalized_source_text,
                    min_surface_chars=160,
                    min_body_chars=120,
                )
            ):
                echoed_full_chunk_ids.append(result.chunk_id)
                snippet_echo_reasons_by_chunk_id.setdefault(result.chunk_id, set()).add(
                    "full_chunk_surface"
                )
            if _looks_like_verbatim_surface_echo(
                normalized_body,
                normalized_evidence_surface,
                min_surface_chars=80,
                min_body_chars=80,
            ):
                echoed_full_chunk_ids.append(result.chunk_id)
                snippet_echo_reasons_by_chunk_id.setdefault(result.chunk_id, set()).add(
                    "evidence_surface"
                )
                copied_snippet_count += 1
                copied_block_indices.update(snippet_block_indices)
                evidence_surface_echoes_by_chunk_id.setdefault(result.chunk_id, []).append(
                    {
                        "snippet_index": snippet_index,
                        "block_indices": list(snippet_block_indices),
                        "body_char_count": len(normalized_body),
                        "evidence_surface_char_count": len(normalized_evidence_surface),
                    }
                )
        aggregate_copied_surface = _chunk_surface_for_block_indices(
            chunk_block_texts_by_id.get(result.chunk_id) or {},
            expected_block_indices=expected_block_indices,
            selected_block_indices=sorted(copied_block_indices),
        )
        normalized_aggregate_copied_surface = _normalize_semantic_comparison_text(
            aggregate_copied_surface
        )
        if (
            copied_snippet_count >= 2
            and _copied_surface_covers_most_of_chunk(
                copied_surface_text=normalized_aggregate_copied_surface,
                full_chunk_text=normalized_source_text,
            )
        ):
            echoed_full_chunk_ids.append(result.chunk_id)
            snippet_echo_reasons_by_chunk_id.setdefault(result.chunk_id, set()).add(
                "aggregate_copied_surface"
            )
            aggregate_copied_surface_by_chunk_id[result.chunk_id] = {
                "copied_block_indices": sorted(copied_block_indices),
                "copied_surface_char_count": len(normalized_aggregate_copied_surface),
                "full_chunk_char_count": len(normalized_source_text),
                "copied_snippet_count": copied_snippet_count,
            }
    if non_grounded_snippet_chunk_ids:
        errors.append("semantic_snippet_body_not_grounded_text")
        metadata["non_grounded_snippet_chunk_ids"] = sorted(set(non_grounded_snippet_chunk_ids))
    if echoed_full_chunk_ids:
        errors.append("semantic_snippet_echoes_full_chunk")
        metadata["echoed_full_chunk_ids"] = sorted(set(echoed_full_chunk_ids))
        metadata["snippet_echo_reasons_by_chunk_id"] = {
            chunk_id: sorted(reasons)
            for chunk_id, reasons in sorted(snippet_echo_reasons_by_chunk_id.items())
        }
    if evidence_surface_echoes_by_chunk_id:
        metadata["evidence_surface_echoes_by_chunk_id"] = {
            chunk_id: details
            for chunk_id, details in sorted(evidence_surface_echoes_by_chunk_id.items())
        }
    if aggregate_copied_surface_by_chunk_id:
        metadata["aggregate_copied_surface_by_chunk_id"] = {
            chunk_id: details
            for chunk_id, details in sorted(aggregate_copied_surface_by_chunk_id.items())
        }

    knowledge_cue_chunk_ids = sorted(_knowledge_cue_chunk_ids(shard))
    metadata["knowledge_cue_chunk_ids"] = knowledge_cue_chunk_ids
    metadata["useful_chunk_count"] = useful_chunk_count
    metadata["knowledge_decision_count"] = knowledge_decision_count
    metadata["snippet_count"] = snippet_count
    if (
        parsed.chunk_results
        and useful_chunk_count == 0
        and knowledge_decision_count == 0
        and snippet_count == 0
        and knowledge_cue_chunk_ids
    ):
        errors.append("semantic_all_false_empty_shard")
        metadata["semantic_rejection_reason"] = "all_false_empty_strong_cue_shard"
        metadata["strong_cue_empty_chunk_ids"] = knowledge_cue_chunk_ids
        metadata["strong_cue_empty_summary"] = {
            "knowledge_cue_chunk_ids": knowledge_cue_chunk_ids,
            "useful_chunk_count": useful_chunk_count,
            "knowledge_decision_count": knowledge_decision_count,
            "snippet_count": snippet_count,
        }

    metadata["reviewed_with_useful_chunks"] = useful_chunk_count > 0
    metadata["reviewed_all_other"] = (
        not errors
        and bool(parsed.chunk_results)
        and useful_chunk_count == 0
        and knowledge_decision_count == 0
        and snippet_count == 0
    )
    metadata["semantic_rejection"] = any(
        error == "semantic_all_false_empty_shard" for error in errors
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
    has_semantic_rejection = bool(metadata.get("semantic_rejection"))
    has_non_grounded_snippet = bool(metadata.get("non_grounded_snippet_chunk_ids"))
    repairable_near_miss = False
    classification = "other_invalid"
    reason_code = "validation_failed"
    reason_detail = ""

    if snippet_copy_only:
        classification = "snippet_copy_only"
        repairable_near_miss = True
        reason_code = "snippet_copy_only"
        reason_detail = (
            "At least one snippet body copies the cited evidence or the full owned chunk "
            "surface too closely."
        )
    elif (
        error_set
        and len(error_set) <= 2
        and error_set.issubset(_KNOWLEDGE_REPAIRABLE_NEAR_MISS_ERRORS)
        and not has_semantic_rejection
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
            "The output does not cover exactly the owned chunks or owned block surface."
        )
    elif has_snippet_copy_error or has_non_grounded_snippet or any(
        error.startswith("semantic_") for error in error_set
    ):
        classification = "semantic_invalid"
        reason_code = "semantic_invalid"
        reason_detail = "The output is structurally valid but semantically low trust."

    if "semantic_all_false_empty_shard" in error_set:
        cue_chunk_ids = [
            str(chunk_id).strip()
            for chunk_id in (metadata.get("knowledge_cue_chunk_ids") or [])
            if str(chunk_id).strip()
        ]
        reason_code = "semantic_all_false_empty_shard"
        reason_detail = (
            "Strong-cue chunk(s) "
            + ", ".join(f"`{chunk_id}`" for chunk_id in cue_chunk_ids)
            + " cannot be returned as fully empty all-`other` review with zero "
            "`knowledge` decisions and zero snippets."
            if cue_chunk_ids
            else "A strong-cue packet cannot be returned as fully empty all-`other` "
            "review with zero `knowledge` decisions and zero snippets."
        )

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


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _normalize_validation_errors(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(error).strip() for error in value if str(error).strip())


def extract_promotable_knowledge_bundle(
    *,
    payload: Mapping[str, Any] | None,
    validation_errors: Sequence[str] = (),
    validation_metadata: Mapping[str, Any] | None = None,
) -> tuple[KnowledgeBundleOutputV2, dict[str, Any]] | None:
    normalized_errors = _normalize_validation_errors(validation_errors)
    error_set = set(normalized_errors)
    if error_set and error_set != {"missing_owned_chunk_results"}:
        return None

    payload_dict = _coerce_dict(payload)
    if not payload_dict:
        if error_set:
            return None
        raise ValueError("Invalid proposal wrapper: missing payload object.")
    parsed = KnowledgeBundleOutputV2.model_validate(payload_dict)

    if not error_set:
        promoted_chunk_ids = [result.chunk_id for result in parsed.chunk_results]
        return parsed, {
            "promotion_mode": "validated_wrapper",
            "partial": False,
            "promoted_chunk_ids": promoted_chunk_ids,
            "promoted_chunk_count": len(promoted_chunk_ids),
        }

    metadata = _coerce_dict(validation_metadata)
    task_aggregation = _coerce_dict(metadata.get("task_aggregation"))
    accepted_task_ids = {
        str(task_id).strip()
        for task_id in (task_aggregation.get("accepted_task_ids") or [])
        if str(task_id).strip()
    }
    task_id_by_chunk_id_raw = task_aggregation.get("task_id_by_chunk_id")
    if not accepted_task_ids or not isinstance(task_id_by_chunk_id_raw, Mapping):
        return None

    task_id_by_chunk_id = {
        str(chunk_id).strip(): str(task_id).strip()
        for chunk_id, task_id in task_id_by_chunk_id_raw.items()
        if str(chunk_id).strip() and str(task_id).strip()
    }
    promoted_chunk_results = [
        result
        for result in parsed.chunk_results
        if task_id_by_chunk_id.get(result.chunk_id) in accepted_task_ids
    ]
    if not promoted_chunk_results:
        return None

    promoted_bundle = KnowledgeBundleOutputV2(
        v=parsed.bundle_version,
        bid=parsed.bundle_id,
        r=promoted_chunk_results,
    )
    promoted_chunk_ids = [result.chunk_id for result in promoted_chunk_results]
    return promoted_bundle, {
        "promotion_mode": "accepted_task_subset",
        "partial": True,
        "promoted_chunk_ids": promoted_chunk_ids,
        "promoted_chunk_count": len(promoted_chunk_ids),
        "accepted_task_ids": sorted(accepted_task_ids),
        "missing_chunk_ids": [
            str(chunk_id).strip()
            for chunk_id in (
                task_aggregation.get("missing_chunk_ids")
                or metadata.get("missing_owned_chunk_ids")
                or []
            )
            if str(chunk_id).strip()
        ],
    }


def read_validated_knowledge_outputs_from_proposals(
    proposals_dir: Path,
) -> tuple[dict[str, KnowledgeChunkResultV2], dict[str, dict[str, Any]]]:
    outputs: dict[str, KnowledgeChunkResultV2] = {}
    payloads_by_shard_id: dict[str, dict[str, Any]] = {}
    for proposal_path in sorted(proposals_dir.glob("*.json")):
        wrapper = json.loads(proposal_path.read_text(encoding="utf-8"))
        if not isinstance(wrapper, Mapping):
            raise ValueError(f"Invalid proposal wrapper {proposal_path}: expected object.")
        promoted_bundle = extract_promotable_knowledge_bundle(
            payload=wrapper.get("payload"),
            validation_errors=wrapper.get("validation_errors") or (),
            validation_metadata=(
                wrapper.get("validation_metadata")
                if isinstance(wrapper.get("validation_metadata"), Mapping)
                else wrapper.get("metadata")
            ),
        )
        if promoted_bundle is None:
            continue
        parsed, _promotion_metadata = promoted_bundle
        payloads_by_shard_id[str(parsed.bundle_id)] = parsed.model_dump(
            mode="json",
            by_alias=True,
        )
        for chunk_result in parsed.chunk_results:
            if chunk_result.chunk_id in outputs:
                raise ValueError(
                    "Duplicate chunk_id in validated knowledge proposals: "
                    f"{chunk_result.chunk_id!r} (file={proposal_path.name})."
                )
            outputs[chunk_result.chunk_id] = chunk_result
    return outputs, payloads_by_shard_id


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ordered_chunk_ids(shard: ShardManifestEntryV1) -> list[str]:
    ordered = [
        str(chunk_id).strip()
        for chunk_id in (shard.metadata.get("ordered_chunk_ids") or [])
        if str(chunk_id).strip()
    ]
    if ordered:
        return ordered
    return [str(chunk_id).strip() for chunk_id in shard.owned_ids if str(chunk_id).strip()]


def _chunk_block_indices_by_id(shard: ShardManifestEntryV1) -> dict[str, list[int]]:
    raw_mapping = shard.metadata.get("chunk_block_indices_by_id")
    resolved: dict[str, list[int]] = {}
    if isinstance(raw_mapping, Mapping):
        for chunk_id, values in raw_mapping.items():
            normalized_chunk_id = str(chunk_id).strip()
            if not normalized_chunk_id:
                continue
            indices = [
                value
                for value in (_coerce_int(item) for item in (values or []))
                if value is not None
            ]
            if indices:
                resolved[normalized_chunk_id] = indices
    if resolved:
        return resolved
    payload = dict(shard.input_payload) if isinstance(shard.input_payload, Mapping) else {}
    chunks = payload.get("c")
    if not isinstance(chunks, list):
        return {}
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            continue
        chunk_id = str(chunk.get("cid") or "").strip()
        if not chunk_id:
            continue
        indices = [
            value
            for value in (_coerce_int((block or {}).get("i")) for block in (chunk.get("b") or []))
            if value is not None
        ]
        if indices:
            resolved[chunk_id] = indices
    return resolved


def _knowledge_cue_chunk_ids(shard: ShardManifestEntryV1) -> set[str]:
    raw_mapping = shard.metadata.get("chunk_knowledge_cue_by_id")
    if not isinstance(raw_mapping, Mapping):
        return set()
    cue_chunk_ids: set[str] = set()
    for chunk_id, value in raw_mapping.items():
        normalized_chunk_id = str(chunk_id).strip()
        if normalized_chunk_id and bool(value):
            cue_chunk_ids.add(normalized_chunk_id)
    return cue_chunk_ids


def _chunk_source_text_by_id(shard: ShardManifestEntryV1) -> dict[str, str]:
    payload = dict(shard.input_payload) if isinstance(shard.input_payload, Mapping) else {}
    chunks = payload.get("c")
    if not isinstance(chunks, list):
        return {}
    source_text_by_id: dict[str, str] = {}
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            continue
        chunk_id = str(chunk.get("cid") or "").strip()
        if not chunk_id:
            continue
        block_text = " ".join(
            str((block or {}).get("t") or "").strip()
            for block in (chunk.get("b") or [])
            if isinstance(block, Mapping) and str((block or {}).get("t") or "").strip()
        ).strip()
        if block_text:
            source_text_by_id[chunk_id] = block_text
    return source_text_by_id


def _chunk_block_texts_by_id(shard: ShardManifestEntryV1) -> dict[str, dict[int, str]]:
    payload = dict(shard.input_payload) if isinstance(shard.input_payload, Mapping) else {}
    chunks = payload.get("c")
    if not isinstance(chunks, list):
        return {}
    block_texts_by_id: dict[str, dict[int, str]] = {}
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            continue
        chunk_id = str(chunk.get("cid") or "").strip()
        if not chunk_id:
            continue
        block_texts: dict[int, str] = {}
        for block in chunk.get("b") or []:
            if not isinstance(block, Mapping):
                continue
            block_index = _coerce_int(block.get("i"))
            block_text = str(block.get("t") or "").strip()
            if block_index is None or not block_text:
                continue
            block_texts[block_index] = block_text
        if block_texts:
            block_texts_by_id[chunk_id] = block_texts
    return block_texts_by_id


def _chunk_surface_for_block_indices(
    chunk_block_texts: Mapping[int, str],
    *,
    expected_block_indices: list[int],
    selected_block_indices: list[int],
) -> str:
    if not chunk_block_texts or not selected_block_indices:
        return ""
    selected = set(selected_block_indices)
    return " ".join(
        str(chunk_block_texts.get(block_index) or "").strip()
        for block_index in expected_block_indices
        if block_index in selected and str(chunk_block_texts.get(block_index) or "").strip()
    ).strip()


def _contains_grounded_text(value: object) -> bool:
    return bool(re.search(r"[A-Za-z]", str(value or "")))


def _normalize_semantic_comparison_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _looks_like_verbatim_surface_echo(
    normalized_body: str,
    normalized_surface: str,
    *,
    min_surface_chars: int,
    min_body_chars: int,
) -> bool:
    if not normalized_body or not normalized_surface:
        return False
    if len(normalized_surface) < min_surface_chars:
        return False
    if len(normalized_body) < max(min_body_chars, int(len(normalized_surface) * 0.85)):
        return False
    return (
        normalized_body == normalized_surface
        or normalized_body in normalized_surface
        or normalized_surface in normalized_body
    )


def _copied_surface_covers_most_of_chunk(
    *,
    copied_surface_text: str,
    full_chunk_text: str,
) -> bool:
    if not copied_surface_text or not full_chunk_text:
        return False
    if len(full_chunk_text) < 160:
        return False
    return len(copied_surface_text) >= max(120, int(len(full_chunk_text) * 0.85))
