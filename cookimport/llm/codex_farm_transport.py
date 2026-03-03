from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class Pass2TransportSelection:
    """Authoritative pass1->pass2 block selection with transport audit."""

    effective_indices: list[int]
    effective_block_ids: list[str]
    included_blocks: list[dict[str, Any]]
    audit: dict[str, Any]


def build_pass2_transport_selection(
    *,
    recipe_id: str,
    bundle_name: str,
    pass1_status: str,
    start_block_index: int | None,
    end_block_index: int | None,
    excluded_block_ids: Sequence[str],
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
) -> Pass2TransportSelection:
    """Select pass2 blocks using an inclusive end index contract.

    The inclusive contract is explicit because pass1 spans and bridge diagnostics
    use `start <= index <= end` semantics.
    """

    start = _coerce_int(start_block_index)
    end = _coerce_int(end_block_index)
    if start is not None and end is not None and start > end:
        start, end = end, start

    excluded = {
        str(block_id).strip()
        for block_id in excluded_block_ids
        if isinstance(block_id, str) and str(block_id).strip()
    }

    effective_indices: list[int] = []
    effective_block_ids: list[str] = []
    included_blocks: list[dict[str, Any]] = []

    if start is not None and end is not None:
        for index in range(start, end + 1):
            block = full_blocks_by_index.get(index)
            block_id = _resolve_block_id(block, fallback_index=index)
            if block_id in excluded:
                continue
            effective_indices.append(index)
            effective_block_ids.append(block_id)
            if isinstance(block, Mapping):
                included_blocks.append(dict(block))

    payload_indices = [int(block.get("index")) for block in included_blocks]
    payload_block_ids = [
        _resolve_block_id(block, fallback_index=int(block.get("index") or 0))
        for block in included_blocks
    ]
    payload_index_set = set(payload_indices)
    effective_index_set = set(effective_indices)

    missing_effective_indices = [
        index for index in effective_indices if index not in payload_index_set
    ]
    unexpected_payload_indices = [
        index for index in payload_indices if index not in effective_index_set
    ]

    mismatch_reasons: list[str] = []
    if start is None or end is None:
        mismatch_reasons.append("missing_pass1_span_bounds")
    if payload_indices != effective_indices:
        mismatch_reasons.append("effective_indices_vs_payload_indices")
    if payload_block_ids != effective_block_ids:
        mismatch_reasons.append("effective_block_ids_vs_payload_block_ids_values")
    if len(payload_indices) != len(effective_indices):
        mismatch_reasons.append("effective_count_vs_payload_count")
    if len(payload_block_ids) != len(effective_block_ids):
        mismatch_reasons.append("effective_block_ids_vs_payload_block_ids")
    if missing_effective_indices:
        mismatch_reasons.append("missing_effective_indices_in_payload")
    if unexpected_payload_indices:
        mismatch_reasons.append("unexpected_payload_indices")

    requested_span_count = 0
    if start is not None and end is not None:
        requested_span_count = max(0, (end - start) + 1)
    coverage_ratio = 1.0
    if effective_indices:
        coverage_ratio = len(payload_indices) / len(effective_indices)

    audit = {
        "recipe_id": recipe_id,
        "bundle_name": bundle_name,
        "pass1_status": pass1_status,
        "start_block_index": start,
        "end_block_index": end,
        "start_block_index_inclusive": start,
        "end_block_index_inclusive": end,
        "end_index_semantics": "inclusive",
        "excluded_block_ids": sorted(excluded),
        "requested_span_count_inclusive": requested_span_count,
        "effective_indices": list(effective_indices),
        "effective_block_ids": list(effective_block_ids),
        "payload_indices": payload_indices,
        "payload_block_ids": payload_block_ids,
        "effective_count": len(effective_indices),
        "payload_count": len(payload_indices),
        "missing_effective_indices": missing_effective_indices,
        "unexpected_payload_indices": unexpected_payload_indices,
        "effective_to_payload_coverage_ratio": round(float(coverage_ratio), 6),
        "mismatch": bool(mismatch_reasons),
        "mismatch_reasons": mismatch_reasons,
    }

    return Pass2TransportSelection(
        effective_indices=effective_indices,
        effective_block_ids=effective_block_ids,
        included_blocks=included_blocks,
        audit=audit,
    )


def _resolve_block_id(block: Mapping[str, Any] | None, *, fallback_index: int) -> str:
    value: Any = None
    if isinstance(block, Mapping):
        value = block.get("block_id") or block.get("id")
    if isinstance(value, str):
        rendered = value.strip()
        if rendered:
            return rendered
    return f"b{fallback_index}"


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
