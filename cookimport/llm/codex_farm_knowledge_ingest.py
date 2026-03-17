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

    owned_chunk_ids = {str(chunk_id) for chunk_id in shard.owned_ids}
    result_chunk_ids = {result.chunk_id for result in parsed.chunk_results}
    missing_owned_chunk_ids = sorted(owned_chunk_ids - result_chunk_ids)
    unexpected_chunk_ids = sorted(result_chunk_ids - owned_chunk_ids)
    if missing_owned_chunk_ids:
        errors.append("missing_owned_chunk_results")
        metadata["missing_owned_chunk_ids"] = missing_owned_chunk_ids
    if unexpected_chunk_ids:
        errors.append("unexpected_chunk_results")
        metadata["unexpected_chunk_ids"] = unexpected_chunk_ids

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
