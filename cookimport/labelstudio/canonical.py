from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

BLOCK_LABELS = {
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "TIP",
    "NARRATIVE",
    "OTHER",
}

RECIPE_CONTENT_LABELS = {"INGREDIENT_LINE", "INSTRUCTION_LINE"}
RECIPE_TITLE_LABEL = "RECIPE_TITLE"
END_RUN_LABELS = {"TIP", "NARRATIVE", "OTHER"}


def derive_gold_spans(
    block_labels: Iterable[dict[str, Any]],
    *,
    k_end_run: int = 2,
    rule_version: str = "v1",
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in block_labels:
        if not isinstance(record, dict):
            continue
        label = record.get("label")
        if label not in BLOCK_LABELS:
            continue
        source_hash = record.get("source_hash")
        source_file = record.get("source_file")
        if not source_hash or not source_file:
            continue
        grouped[(str(source_hash), str(source_file))].append(record)

    spans: list[dict[str, Any]] = []
    for (source_hash, source_file), records in grouped.items():
        records.sort(key=lambda item: int(item.get("block_index", 0)))
        current_start: int | None = None
        title_index: int | None = None
        last_good: int | None = None
        gap_run = 0

        for record in records:
            label = record.get("label")
            block_index = int(record.get("block_index", 0))
            if label == RECIPE_TITLE_LABEL:
                if current_start is not None and last_good is not None:
                    spans.append(
                        _build_span(
                            source_hash,
                            source_file,
                            current_start,
                            last_good,
                            title_index or current_start,
                            k_end_run,
                            rule_version,
                        )
                    )
                current_start = block_index
                title_index = block_index
                last_good = block_index
                gap_run = 0
                continue

            if current_start is None:
                continue

            if label in RECIPE_CONTENT_LABELS:
                last_good = block_index
                gap_run = 0
                continue

            gap_run += 1
            if gap_run >= k_end_run:
                if last_good is not None:
                    spans.append(
                        _build_span(
                            source_hash,
                            source_file,
                            current_start,
                            last_good,
                            title_index or current_start,
                            k_end_run,
                            rule_version,
                        )
                    )
                current_start = None
                title_index = None
                last_good = None
                gap_run = 0

        if current_start is not None and last_good is not None:
            spans.append(
                _build_span(
                    source_hash,
                    source_file,
                    current_start,
                    last_good,
                    title_index or current_start,
                    k_end_run,
                    rule_version,
                )
            )

    return spans


def _build_span(
    source_hash: str,
    source_file: str,
    start: int,
    end: int,
    title_index: int,
    k_end_run: int,
    rule_version: str,
) -> dict[str, Any]:
    span_id = f"urn:cookimport:gold_recipe:{source_hash}:{start}:{end}"
    return {
        "span_id": span_id,
        "source_hash": source_hash,
        "source_file": source_file,
        "start_block_index": start,
        "end_block_index": end,
        "title_block_index": title_index,
        "notes": {"k_end_run": k_end_run, "rule_version": rule_version},
    }
