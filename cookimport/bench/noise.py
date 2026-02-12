"""Noise reduction primitives for prediction output."""

from __future__ import annotations

from typing import Any


def dedupe_predictions(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse identical/equivalent predicted spans.

    Two predictions are equivalent if they share the same
    source_hash + source_file + label + start_block_index + end_block_index.
    """
    seen: set[tuple[str, str, str, int, int]] = set()
    deduped: list[dict[str, Any]] = []
    for pred in predictions:
        key = (
            str(pred.get("source_hash") or ""),
            str(pred.get("source_file") or ""),
            str(pred.get("label") or ""),
            int(pred.get("start_block_index", 0)),
            int(pred.get("end_block_index", 0)),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(pred)
    return deduped


def consolidate_predictions(
    predictions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prefer minimal overlapping spans of the same label.

    When two predictions of the same label overlap, keep the one
    with the smaller span (more precise).
    """
    by_label: dict[str, list[dict[str, Any]]] = {}
    for pred in predictions:
        label = str(pred.get("label") or "OTHER")
        by_label.setdefault(label, []).append(pred)

    consolidated: list[dict[str, Any]] = []
    for label, preds in by_label.items():
        sorted_preds = sorted(
            preds,
            key=lambda p: (
                int(p.get("start_block_index", 0)),
                int(p.get("end_block_index", 0)),
            ),
        )
        kept: list[dict[str, Any]] = []
        for pred in sorted_preds:
            start = int(pred.get("start_block_index", 0))
            end = int(pred.get("end_block_index", 0))
            overlaps_existing = False
            for existing in kept:
                ex_start = int(existing.get("start_block_index", 0))
                ex_end = int(existing.get("end_block_index", 0))
                if start <= ex_end and end >= ex_start:
                    overlaps_existing = True
                    # Keep the smaller span
                    ex_size = ex_end - ex_start
                    pred_size = end - start
                    if pred_size < ex_size:
                        kept.remove(existing)
                        kept.append(pred)
                    break
            if not overlaps_existing:
                kept.append(pred)
        consolidated.extend(kept)
    return consolidated


_PROSE_LABELS = {"OTHER", "NARRATIVE"}


def gate_noise(
    predictions: list[dict[str, Any]],
    *,
    gate_labels: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter narrative prose from actionable predictions.

    Removes predictions whose label is in the gate set (defaults to
    OTHER and NARRATIVE).
    """
    blocked = gate_labels if gate_labels is not None else _PROSE_LABELS
    return [p for p in predictions if str(p.get("label") or "") not in blocked]
