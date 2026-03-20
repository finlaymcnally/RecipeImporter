from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .phase_worker_runtime import ShardManifestEntryV1
from .codex_farm_knowledge_models import KnowledgeBundleOutputV2, KnowledgeChunkResultV2


def validate_knowledge_shard_output(
    shard: ShardManifestEntryV1,
    payload: dict[str, Any],
) -> tuple[bool, tuple[str, ...], dict[str, Any]]:
    errors: list[str] = []
    metadata: dict[str, Any] = {
        "owned_chunk_count": len(shard.owned_ids),
    }
    try:
        parsed = KnowledgeBundleOutputV2.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        return False, ("schema_invalid",), {"parse_error": str(exc)}

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

    knowledge_cue_chunk_ids = sorted(_knowledge_cue_chunk_ids(shard))
    metadata["knowledge_cue_chunk_ids"] = knowledge_cue_chunk_ids
    if (
        parsed.chunk_results
        and useful_chunk_count == 0
        and knowledge_decision_count == 0
        and snippet_count == 0
        and knowledge_cue_chunk_ids
    ):
        errors.append("semantic_all_false_empty_shard")
        metadata["semantic_rejection_reason"] = "all_false_empty_strong_cue_shard"

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


def read_validated_knowledge_outputs_from_proposals(
    proposals_dir: Path,
) -> tuple[dict[str, KnowledgeChunkResultV2], dict[str, dict[str, Any]]]:
    outputs: dict[str, KnowledgeChunkResultV2] = {}
    payloads_by_shard_id: dict[str, dict[str, Any]] = {}
    for proposal_path in sorted(proposals_dir.glob("*.json")):
        wrapper = json.loads(proposal_path.read_text(encoding="utf-8"))
        if not isinstance(wrapper, Mapping):
            raise ValueError(f"Invalid proposal wrapper {proposal_path}: expected object.")
        validation_errors = wrapper.get("validation_errors") or []
        if isinstance(validation_errors, list) and validation_errors:
            continue
        payload = wrapper.get("payload")
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid proposal wrapper {proposal_path}: missing payload object.")
        parsed = KnowledgeBundleOutputV2.model_validate(payload)
        payloads_by_shard_id[str(parsed.bundle_id)] = payload
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
