from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
from typing import Any

from cookimport.labelstudio.howto_section import (
    HOWTO_SECTION_LABEL,
    INSTRUCTION_LINE_LABEL,
    resolve_howto_label_for_range,
    resolve_howto_label_sets_by_index,
)
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_ALLOWED_LABELS,
    normalize_freeform_label as _normalize_config_freeform_label,
)


@dataclass(frozen=True)
class LabeledRange:
    span_id: str
    source_hash: str | None
    source_file: str
    label: str
    start_block_index: int
    end_block_index: int

    def normalized(self) -> "LabeledRange":
        start = self.start_block_index
        end = self.end_block_index
        if start > end:
            start, end = end, start
        return LabeledRange(
            span_id=self.span_id,
            source_hash=self.source_hash,
            source_file=self.source_file,
            label=self.label,
            start_block_index=start,
            end_block_index=end,
        )


@dataclass(frozen=True)
class LabeledMatch:
    gold: LabeledRange
    predicted: LabeledRange
    overlap: float
    classification: str


@dataclass(frozen=True)
class GoldConflict:
    source_hash: str | None
    source_file: str
    start_block_index: int
    end_block_index: int
    label_counts: dict[str, int]
    resolution: str
    selected_label: str | None
    span_ids: list[str]


_APP_SUPPORTED_LABELS = (
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "OTHER",
)
_APP_OVERLAP_LABELS = (
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
)
_APP_RELAXED_OVERLAP_THRESHOLD = 0.1
_NO_OVERLAP_LABEL = "__NO_OVERLAP__"
_GRANULARITY_MISMATCH_MIN_SUPPORTED_PRACTICAL_RECALL = 0.8
_GRANULARITY_MISMATCH_MAX_STRICT_F1 = 0.05
_GRANULARITY_MISMATCH_MIN_WIDTH_RATIO = 4.0
_RECIPE_HEADER_LABEL = "RECIPE_TITLE"


def load_gold_freeform_ranges(path: Path) -> list[LabeledRange]:
    spans: list[LabeledRange] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            continue
        label = payload.get("label")
        source_file = payload.get("source_file")
        if not label or source_file is None:
            continue
        normalized_label = _normalize_freeform_label(str(label))
        if normalized_label not in FREEFORM_ALLOWED_LABELS:
            raise ValueError(f"Invalid freeform label in {path}: {label!r}")
        touched_indices = _extract_block_indices(payload)
        if not touched_indices:
            continue
        span_id = payload.get("span_id") or f"gold:{len(spans)}"
        source_hash = payload.get("source_hash")
        spans.append(
            LabeledRange(
                span_id=str(span_id),
                source_hash=str(source_hash) if source_hash else None,
                source_file=str(source_file),
                label=normalized_label,
                start_block_index=min(touched_indices),
                end_block_index=max(touched_indices),
            ).normalized()
        )
    return spans


def _extract_block_indices(payload: dict[str, Any]) -> list[int]:
    values = payload.get("touched_block_indices")
    items: list[Any]
    if isinstance(values, list):
        items = values
    else:
        touched_blocks = payload.get("touched_blocks")
        if not isinstance(touched_blocks, list):
            return []
        items = [
            item.get("block_index")
            for item in touched_blocks
            if isinstance(item, dict) and item.get("block_index") is not None
        ]

    indices: list[int] = []
    for value in items:
        try:
            indices.append(int(value))
        except (TypeError, ValueError):
            continue
    return indices


def load_predicted_labeled_ranges(run_dir: Path) -> list[LabeledRange]:
    tasks_path = run_dir / "label_studio_tasks.jsonl"
    if not tasks_path.exists():
        raise FileNotFoundError(f"Missing label_studio_tasks.jsonl in {run_dir}")
    prefer_recipe_title = False
    with tasks_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                continue
            data = payload.get("data")
            if not isinstance(data, dict):
                continue
            if data.get("chunk_level") == "structural" and data.get("chunk_type") == "recipe_title":
                prefer_recipe_title = True
                break
    spans: list[LabeledRange] = []
    with tasks_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                continue
            data = payload.get("data")
            if not isinstance(data, dict):
                continue
            chunk_id = data.get("chunk_id")
            if not chunk_id:
                continue
            label = _map_chunk_to_label(data, prefer_recipe_title=prefer_recipe_title)
            if label is None:
                continue
            location = data.get("location")
            if not isinstance(location, dict):
                location = {}
            start, end = _location_to_range(location)
            if start is None or end is None:
                continue
            source_hash = data.get("source_hash")
            if source_hash is None:
                source_hash = _parse_chunk_id(chunk_id)
            source_file = data.get("source_file") or "unknown"
            spans.append(
                LabeledRange(
                    span_id=str(chunk_id),
                    source_hash=str(source_hash) if source_hash else None,
                    source_file=str(source_file),
                    label=label,
                    start_block_index=start,
                    end_block_index=end,
                ).normalized()
            )
    return spans


def _map_chunk_to_label(
    data: dict[str, Any], *, prefer_recipe_title: bool = False
) -> str | None:
    chunk_level = str(data.get("chunk_level") or "")
    chunk_type = str(data.get("chunk_type") or "")
    chunk_hint = str(data.get("chunk_type_hint") or "")

    if chunk_level == "structural":
        if chunk_type == "recipe_title" or chunk_hint == "recipe_title":
            return "RECIPE_TITLE"
        if chunk_type == "recipe_block" or chunk_hint == "recipe":
            if prefer_recipe_title:
                return None
            return "RECIPE_TITLE"
        return None

    if chunk_level != "atomic":
        return None

    if (
        chunk_type == "ingredient_line"
        or chunk_hint in {"ingredient", "ingredient_like"}
        or "ingredient" in chunk_type
    ):
        return "INGREDIENT_LINE"
    if (
        chunk_type == "step_line"
        or chunk_hint in {"step", "list_item"}
        or chunk_type.endswith("_step")
    ):
        return "INSTRUCTION_LINE"
    if chunk_type == "note" or chunk_hint == "note":
        return "RECIPE_NOTES"
    if (
        "variant" in chunk_type
        or "variant" in chunk_hint
    ):
        return "RECIPE_VARIANT"
    if (
        "tip" in chunk_type
        or "tip" in chunk_hint
        or "knowledge" in chunk_type
        or "knowledge" in chunk_hint
        or "advice" in chunk_type
        or "advice" in chunk_hint
    ):
        return "KNOWLEDGE"
    if (
        "yield" in chunk_type
        or "yield" in chunk_hint
        or "serving" in chunk_type
        or "serving" in chunk_hint
    ):
        return "YIELD_LINE"
    if (
        chunk_type in {"time_line", "prep_time", "cook_time", "total_time"}
        or chunk_hint in {"time_line", "prep_time", "cook_time", "total_time"}
        or (chunk_type.startswith("time") and "line" in chunk_type)
    ):
        return "TIME_LINE"
    if chunk_type in {"recipe_description"}:
        return "OTHER"
    if chunk_type.startswith("atom_"):
        atom_kind = chunk_type[5:]
        if atom_kind in {"ingredient_like"}:
            return "INGREDIENT_LINE"
        if atom_kind in {"step", "list_item"}:
            return "INSTRUCTION_LINE"
        if atom_kind in {"paragraph", "sentence"}:
            return "OTHER"
    return "OTHER"


def _normalize_freeform_label(label: str) -> str:
    return _normalize_config_freeform_label(label)


def _parse_chunk_id(chunk_id: str) -> str | None:
    parts = chunk_id.split(":")
    if len(parts) < 6:
        return None
    if parts[0] != "urn" or parts[1] != "recipeimport" or parts[2] != "chunk":
        return None
    return parts[4]


def _location_to_range(location: dict[str, Any]) -> tuple[int | None, int | None]:
    for start_key, end_key in (
        ("start_block", "end_block"),
        ("start_line", "end_line"),
        ("block_index", "block_index"),
    ):
        start = location.get(start_key)
        end = location.get(end_key)
        if start is None or end is None:
            continue
        try:
            return int(start), int(end)
        except (TypeError, ValueError):
            continue
    return None, None


def _overlap_ratio(a: LabeledRange, b: LabeledRange) -> float:
    a = a.normalized()
    b = b.normalized()
    intersection = max(
        0,
        min(a.end_block_index, b.end_block_index)
        - max(a.start_block_index, b.start_block_index)
        + 1,
    )
    if intersection == 0:
        return 0.0
    union = (
        (a.end_block_index - a.start_block_index + 1)
        + (b.end_block_index - b.start_block_index + 1)
        - intersection
    )
    if union <= 0:
        return 0.0
    return intersection / union


def _ranges_overlap(a: LabeledRange, b: LabeledRange) -> bool:
    a = a.normalized()
    b = b.normalized()
    intersection = max(
        0,
        min(a.end_block_index, b.end_block_index)
        - max(a.start_block_index, b.start_block_index)
        + 1,
    )
    return intersection > 0


def _f1_score(precision: float, recall: float) -> float:
    if (precision + recall) <= 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _range_width(span: LabeledRange) -> int:
    normalized = span.normalized()
    return max(0, normalized.end_block_index - normalized.start_block_index + 1)


def _percentile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    rank = (len(values) - 1) * q
    lower_index = int(math.floor(rank))
    upper_index = int(math.ceil(rank))
    if lower_index == upper_index:
        return float(values[lower_index])
    lower = float(values[lower_index])
    upper = float(values[upper_index])
    weight = rank - lower_index
    return lower + (upper - lower) * weight


def _span_width_stats(spans: list[LabeledRange]) -> dict[str, float]:
    if not spans:
        return {
            "min": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "max": 0.0,
            "avg": 0.0,
        }
    widths = sorted(_range_width(span) for span in spans)
    return {
        "min": float(widths[0]),
        "p50": _percentile(widths, 0.50),
        "p90": _percentile(widths, 0.90),
        "max": float(widths[-1]),
        "avg": float(sum(widths) / len(widths)),
    }


def _compatible_source(
    pred: LabeledRange,
    gold: LabeledRange,
    *,
    force_source_match: bool = False,
) -> bool:
    if force_source_match:
        return True
    if pred.source_hash and gold.source_hash:
        if pred.source_hash == gold.source_hash:
            return True
        if gold.source_hash.startswith(pred.source_hash) or pred.source_hash.startswith(
            gold.source_hash
        ):
            return True
        return False
    return pred.source_file == gold.source_file


def _classify_boundary(pred: LabeledRange, gold: LabeledRange) -> str:
    pred = pred.normalized()
    gold = gold.normalized()
    if (
        pred.start_block_index == gold.start_block_index
        and pred.end_block_index == gold.end_block_index
    ):
        return "correct"
    if (
        pred.start_block_index <= gold.start_block_index
        and pred.end_block_index >= gold.end_block_index
    ):
        return "over"
    if (
        pred.start_block_index >= gold.start_block_index
        and pred.end_block_index <= gold.end_block_index
    ):
        return "under"
    return "partial"


def _evaluate_ranges(
    predicted: list[LabeledRange],
    gold: list[LabeledRange],
    *,
    overlap_threshold: float = 0.5,
    force_source_match: bool = False,
) -> dict[str, Any]:
    matches: list[LabeledMatch] = []
    missed_gold: list[LabeledRange] = []
    matched_pred_ids: set[str] = set()

    for gold_span in gold:
        best_match: LabeledMatch | None = None
        for pred_span in predicted:
            if pred_span.label != gold_span.label:
                continue
            if not _compatible_source(
                pred_span,
                gold_span,
                force_source_match=force_source_match,
            ):
                continue
            overlap = _overlap_ratio(pred_span, gold_span)
            if best_match is None or overlap > best_match.overlap:
                best_match = LabeledMatch(
                    gold=gold_span,
                    predicted=pred_span,
                    overlap=overlap,
                    classification=_classify_boundary(pred_span, gold_span),
                )
        if best_match is None or best_match.overlap < overlap_threshold:
            missed_gold.append(gold_span)
            continue
        matches.append(best_match)
        matched_pred_ids.add(best_match.predicted.span_id)

    false_positive_preds = [
        span for span in predicted if span.span_id not in matched_pred_ids
    ]

    boundary_counts = {"correct": 0, "over": 0, "under": 0, "partial": 0}
    for match in matches:
        if match.classification in boundary_counts:
            boundary_counts[match.classification] += 1
        else:
            boundary_counts["partial"] += 1

    labels = sorted({span.label for span in gold} | {span.label for span in predicted})
    per_label: dict[str, dict[str, Any]] = {}
    for label in labels:
        gold_total = sum(1 for span in gold if span.label == label)
        pred_total = sum(1 for span in predicted if span.label == label)
        matched_gold = sum(1 for match in matches if match.gold.label == label)
        matched_pred = len(
            {match.predicted.span_id for match in matches if match.predicted.label == label}
        )
        recall = (matched_gold / gold_total) if gold_total else 0.0
        precision = (matched_pred / pred_total) if pred_total else 0.0
        per_label[label] = {
            "gold_total": gold_total,
            "pred_total": pred_total,
            "gold_matched": matched_gold,
            "pred_matched": matched_pred,
            "recall": recall,
            "precision": precision,
        }

    recall = (len(matches) / len(gold)) if gold else 0.0
    precision = (len(matched_pred_ids) / len(predicted)) if predicted else 0.0

    report = {
        "counts": {
            "gold_total": len(gold),
            "pred_total": len(predicted),
            "gold_matched": len(matches),
            "pred_matched": len(matched_pred_ids),
            "gold_missed": len(missed_gold),
            "pred_false_positive": len(false_positive_preds),
        },
        "recall": recall,
        "precision": precision,
        "boundary": boundary_counts,
        "overlap_threshold": overlap_threshold,
        "per_label": per_label,
        "matches": [
            {
                "gold": asdict(match.gold),
                "predicted": asdict(match.predicted),
                "overlap": match.overlap,
                "classification": match.classification,
            }
            for match in matches
        ],
    }

    return {
        "report": report,
        "missed_gold": missed_gold,
        "false_positive_preds": false_positive_preds,
    }


def _evaluate_practical_ranges(
    predicted: list[LabeledRange],
    gold: list[LabeledRange],
    *,
    force_source_match: bool = False,
) -> dict[str, Any]:
    matched_gold_span_ids: set[str] = set()
    matched_pred_span_ids: set[str] = set()
    missed_gold: list[LabeledRange] = []
    false_positive_preds: list[LabeledRange] = []

    for gold_span in gold:
        found_overlap = False
        for pred_span in predicted:
            if pred_span.label != gold_span.label:
                continue
            if not _compatible_source(
                pred_span,
                gold_span,
                force_source_match=force_source_match,
            ):
                continue
            if _ranges_overlap(pred_span, gold_span):
                found_overlap = True
                matched_gold_span_ids.add(gold_span.span_id)
                break
        if not found_overlap:
            missed_gold.append(gold_span)

    for pred_span in predicted:
        found_overlap = False
        for gold_span in gold:
            if pred_span.label != gold_span.label:
                continue
            if not _compatible_source(
                pred_span,
                gold_span,
                force_source_match=force_source_match,
            ):
                continue
            if _ranges_overlap(pred_span, gold_span):
                found_overlap = True
                matched_pred_span_ids.add(pred_span.span_id)
                break
        if not found_overlap:
            false_positive_preds.append(pred_span)

    precision = (len(matched_pred_span_ids) / len(predicted)) if predicted else 0.0
    recall = (len(matched_gold_span_ids) / len(gold)) if gold else 0.0
    labels = sorted({span.label for span in gold} | {span.label for span in predicted})
    per_label: dict[str, dict[str, Any]] = {}
    for label in labels:
        label_gold = [span for span in gold if span.label == label]
        label_pred = [span for span in predicted if span.label == label]
        label_gold_matched = 0
        for gold_span in label_gold:
            if any(
                _compatible_source(pred_span, gold_span, force_source_match=force_source_match)
                and _ranges_overlap(pred_span, gold_span)
                for pred_span in label_pred
            ):
                label_gold_matched += 1
        label_pred_matched = 0
        for pred_span in label_pred:
            if any(
                _compatible_source(pred_span, gold_span, force_source_match=force_source_match)
                and _ranges_overlap(pred_span, gold_span)
                for gold_span in label_gold
            ):
                label_pred_matched += 1
        per_label[label] = {
            "gold_total": len(label_gold),
            "pred_total": len(label_pred),
            "gold_matched": label_gold_matched,
            "pred_matched": label_pred_matched,
            "recall": (label_gold_matched / len(label_gold)) if label_gold else 0.0,
            "precision": (label_pred_matched / len(label_pred)) if label_pred else 0.0,
        }

    return {
        "counts": {
            "gold_total": len(gold),
            "pred_total": len(predicted),
            "gold_matched": len(matched_gold_span_ids),
            "pred_matched": len(matched_pred_span_ids),
            "gold_missed": len(missed_gold),
            "pred_false_positive": len(false_positive_preds),
        },
        "precision": precision,
        "recall": recall,
        "f1": _f1_score(precision, recall),
        "per_label": per_label,
        "matched_gold_span_ids": sorted(matched_gold_span_ids),
        "matched_pred_span_ids": sorted(matched_pred_span_ids),
    }


def _detect_granularity_mismatch(
    *,
    strict_f1: float,
    supported_practical_recall: float,
    span_width_stats: dict[str, dict[str, float]],
) -> dict[str, Any]:
    gold_p50 = float((span_width_stats.get("gold") or {}).get("p50") or 0.0)
    pred_p50 = float((span_width_stats.get("pred") or {}).get("p50") or 0.0)
    ratio = (pred_p50 / gold_p50) if gold_p50 > 0 else 0.0
    likely = (
        supported_practical_recall
        >= _GRANULARITY_MISMATCH_MIN_SUPPORTED_PRACTICAL_RECALL
        and strict_f1 <= _GRANULARITY_MISMATCH_MAX_STRICT_F1
        and ratio >= _GRANULARITY_MISMATCH_MIN_WIDTH_RATIO
    )
    reason = (
        "Strict IoU is near zero while supported-label practical overlap is high, and "
        "prediction ranges are much wider than gold spans."
        if likely
        else (
            "Mismatch conditions not met "
            f"(strict_f1={strict_f1:.3f}, "
            f"supported_practical_recall={supported_practical_recall:.3f}, "
            f"p50_ratio={ratio:.2f})."
        )
    )
    return {
        "likely": likely,
        "reason": reason,
        "ratio_p50_pred_to_gold": ratio,
    }


def _dedupe_predicted_ranges(predicted: list[LabeledRange]) -> list[LabeledRange]:
    deduped: list[LabeledRange] = []
    seen: set[tuple[str, str, str, int, int]] = set()
    for span in predicted:
        key = (
            str(span.source_hash or ""),
            span.source_file,
            span.label,
            span.start_block_index,
            span.end_block_index,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(span)
    return deduped


def _gold_dedupe_key(span: LabeledRange) -> tuple[str, str, int, int]:
    return (
        str(span.source_hash or ""),
        span.source_file,
        span.start_block_index,
        span.end_block_index,
    )


def _resolve_howto_section_ranges(
    spans: list[LabeledRange],
    *,
    default_label: str = INSTRUCTION_LINE_LABEL,
) -> list[LabeledRange]:
    grouped: dict[tuple[str, str], list[LabeledRange]] = {}
    for span in spans:
        key = (str(span.source_hash or ""), span.source_file)
        grouped.setdefault(key, []).append(span)

    resolved_ranges: list[LabeledRange] = []
    for group_spans in grouped.values():
        labels_by_index: dict[int, set[str]] = {}
        for span in group_spans:
            for index in range(span.start_block_index, span.end_block_index + 1):
                labels_by_index.setdefault(index, set()).add(span.label)
        resolved_labels_by_index = resolve_howto_label_sets_by_index(
            labels_by_index,
            default_label=default_label,
        )

        for span in group_spans:
            if span.label != HOWTO_SECTION_LABEL:
                resolved_ranges.append(span)
                continue
            resolved_label = resolve_howto_label_for_range(
                start_index=span.start_block_index,
                end_index=span.end_block_index,
                label_sets_by_index=resolved_labels_by_index,
                default_label=default_label,
            )
            resolved_ranges.append(replace(span, label=resolved_label))

    return resolved_ranges


def _dedupe_gold_ranges(gold: list[LabeledRange]) -> tuple[list[LabeledRange], dict[str, Any]]:
    grouped: dict[tuple[str, str, int, int], list[LabeledRange]] = {}
    for span in gold:
        grouped.setdefault(_gold_dedupe_key(span), []).append(span)

    deduped: list[LabeledRange] = []
    conflicts: list[GoldConflict] = []
    duplicate_groups = 0
    conflict_groups = 0
    resolved_conflicts = 0
    dropped_tie_groups = 0
    dropped_tie_rows = 0

    for spans in grouped.values():
        if len(spans) == 1:
            deduped.append(spans[0])
            continue

        duplicate_groups += 1
        label_counts = Counter(span.label for span in spans)
        if len(label_counts) == 1:
            deduped.append(spans[0])
            continue

        conflict_groups += 1
        highest = max(label_counts.values())
        winning_labels = sorted(
            label for label, count in label_counts.items() if count == highest
        )
        exemplar = spans[0]
        if len(winning_labels) == 1:
            winning_label = winning_labels[0]
            selected = next(span for span in spans if span.label == winning_label)
            deduped.append(selected)
            resolved_conflicts += 1
            conflicts.append(
                GoldConflict(
                    source_hash=exemplar.source_hash,
                    source_file=exemplar.source_file,
                    start_block_index=exemplar.start_block_index,
                    end_block_index=exemplar.end_block_index,
                    label_counts=dict(label_counts),
                    resolution="majority_vote",
                    selected_label=winning_label,
                    span_ids=[span.span_id for span in spans],
                )
            )
            continue

        dropped_tie_groups += 1
        dropped_tie_rows += len(spans)
        conflicts.append(
            GoldConflict(
                source_hash=exemplar.source_hash,
                source_file=exemplar.source_file,
                start_block_index=exemplar.start_block_index,
                end_block_index=exemplar.end_block_index,
                label_counts=dict(label_counts),
                resolution="dropped_tie",
                selected_label=None,
                span_ids=[span.span_id for span in spans],
            )
        )

    input_total = len(gold)
    deduped_total = len(deduped)
    rows_removed = input_total - deduped_total
    conflict_rows_total = sum(sum(item.label_counts.values()) for item in conflicts)

    return deduped, {
        "enabled": True,
        "key": "source_hash+source_file+start_block_index+end_block_index",
        "input_gold_total": input_total,
        "deduped_gold_total": deduped_total,
        "rows_removed": rows_removed,
        "duplicate_groups": duplicate_groups,
        "conflict_groups": conflict_groups,
        "conflict_groups_resolved_majority": resolved_conflicts,
        "conflict_groups_dropped_tie": dropped_tie_groups,
        "conflict_rows_total": conflict_rows_total,
        "conflict_rows_dropped_tie": dropped_tie_rows,
        "conflicts": [asdict(item) for item in conflicts],
    }


def _count_gold_any_overlap(
    predicted: list[LabeledRange],
    gold: list[LabeledRange],
    *,
    label: str,
    force_source_match: bool = False,
) -> dict[str, Any]:
    label_gold = [span for span in gold if span.label == label]
    label_pred = [span for span in predicted if span.label == label]
    gold_with_overlap = 0
    for gold_span in label_gold:
        found = False
        for pred_span in label_pred:
            if not _compatible_source(
                pred_span,
                gold_span,
                force_source_match=force_source_match,
            ):
                continue
            if _overlap_ratio(pred_span, gold_span) > 0:
                found = True
                break
        if found:
            gold_with_overlap += 1
    gold_total = len(label_gold)
    coverage = (gold_with_overlap / gold_total) if gold_total else 0.0
    return {
        "gold_total": gold_total,
        "gold_with_any_overlap": gold_with_overlap,
        "coverage": coverage,
    }


def _best_overlap_match(
    gold_span: LabeledRange,
    predicted: list[LabeledRange],
    *,
    force_source_match: bool = False,
) -> tuple[LabeledRange | None, float]:
    best_span: LabeledRange | None = None
    best_overlap = 0.0
    for pred_span in predicted:
        if not _compatible_source(
            pred_span,
            gold_span,
            force_source_match=force_source_match,
        ):
            continue
        overlap = _overlap_ratio(pred_span, gold_span)
        if overlap <= 0:
            continue
        if overlap > best_overlap:
            best_span = pred_span
            best_overlap = overlap
    return best_span, best_overlap


def _build_classification_only_report(
    predicted: list[LabeledRange],
    gold: list[LabeledRange],
    *,
    force_source_match: bool = False,
) -> dict[str, Any]:
    deduped_pred = _dedupe_predicted_ranges(predicted)
    label_set = sorted({span.label for span in gold} | {span.label for span in deduped_pred})

    per_label_counts: dict[str, dict[str, int]] = {
        label: {
            "gold_total": 0,
            "gold_with_any_overlap": 0,
            "gold_with_same_label_any_overlap": 0,
            "gold_best_label_match": 0,
        }
        for label in label_set
    }
    confusion: dict[str, dict[str, int]] = {
        label: {pred_label: 0 for pred_label in (*label_set, _NO_OVERLAP_LABEL)}
        for label in label_set
    }

    gold_with_any_overlap = 0
    gold_with_same_label_any_overlap = 0
    gold_best_label_match = 0

    for gold_span in gold:
        if gold_span.label not in per_label_counts:
            per_label_counts[gold_span.label] = {
                "gold_total": 0,
                "gold_with_any_overlap": 0,
                "gold_with_same_label_any_overlap": 0,
                "gold_best_label_match": 0,
            }
            confusion[gold_span.label] = {
                pred_label: 0 for pred_label in (*label_set, _NO_OVERLAP_LABEL)
            }
        per_label_counts[gold_span.label]["gold_total"] += 1

        best_pred, _best_overlap = _best_overlap_match(
            gold_span,
            deduped_pred,
            force_source_match=force_source_match,
        )
        if best_pred is None:
            confusion[gold_span.label][_NO_OVERLAP_LABEL] += 1
            continue

        gold_with_any_overlap += 1
        per_label_counts[gold_span.label]["gold_with_any_overlap"] += 1

        any_same_label_overlap = False
        for pred_span in deduped_pred:
            if pred_span.label != gold_span.label:
                continue
            if not _compatible_source(
                pred_span,
                gold_span,
                force_source_match=force_source_match,
            ):
                continue
            if _overlap_ratio(pred_span, gold_span) > 0:
                any_same_label_overlap = True
                break
        if any_same_label_overlap:
            gold_with_same_label_any_overlap += 1
            per_label_counts[gold_span.label]["gold_with_same_label_any_overlap"] += 1

        confusion_row = confusion[gold_span.label]
        confusion_row.setdefault(best_pred.label, 0)
        confusion_row[best_pred.label] += 1
        if best_pred.label == gold_span.label:
            gold_best_label_match += 1
            per_label_counts[gold_span.label]["gold_best_label_match"] += 1

    gold_total = len(gold)
    same_label_any_overlap_rate = (
        gold_with_same_label_any_overlap / gold_total if gold_total else 0.0
    )
    best_label_match_rate = (gold_best_label_match / gold_total) if gold_total else 0.0
    any_overlap_rate = (gold_with_any_overlap / gold_total) if gold_total else 0.0

    per_label: dict[str, dict[str, Any]] = {}
    for label, counts in per_label_counts.items():
        label_total = counts["gold_total"]
        per_label[label] = {
            **counts,
            "any_overlap_rate": (
                counts["gold_with_any_overlap"] / label_total if label_total else 0.0
            ),
            "same_label_any_overlap_rate": (
                counts["gold_with_same_label_any_overlap"] / label_total
                if label_total
                else 0.0
            ),
            "best_label_match_rate": (
                counts["gold_best_label_match"] / label_total if label_total else 0.0
            ),
        }

    supported_gold_total = sum(
        counts["gold_total"]
        for label, counts in per_label_counts.items()
        if label in _APP_SUPPORTED_LABELS
    )
    supported_same_label_any_overlap = sum(
        counts["gold_with_same_label_any_overlap"]
        for label, counts in per_label_counts.items()
        if label in _APP_SUPPORTED_LABELS
    )
    supported_same_label_any_overlap_rate = (
        supported_same_label_any_overlap / supported_gold_total
        if supported_gold_total
        else 0.0
    )

    return {
        "deduped_pred_total": len(deduped_pred),
        "gold_total": gold_total,
        "gold_with_any_overlap": gold_with_any_overlap,
        "gold_with_same_label_any_overlap": gold_with_same_label_any_overlap,
        "gold_best_label_match": gold_best_label_match,
        "any_overlap_rate": any_overlap_rate,
        "same_label_any_overlap_rate": same_label_any_overlap_rate,
        "best_label_match_rate": best_label_match_rate,
        "supported_labels": list(_APP_SUPPORTED_LABELS),
        "supported_gold_total": supported_gold_total,
        "supported_gold_with_same_label_any_overlap": supported_same_label_any_overlap,
        "supported_same_label_any_overlap_rate": supported_same_label_any_overlap_rate,
        "per_label": per_label,
        "confusion_by_gold_label": confusion,
        "dedupe_key": "source_hash+source_file+label+start_block_index+end_block_index",
    }


def _build_app_aligned_report(
    predicted: list[LabeledRange],
    gold: list[LabeledRange],
    *,
    overlap_threshold: float,
    force_source_match: bool = False,
) -> dict[str, Any]:
    deduped_pred = _dedupe_predicted_ranges(predicted)

    deduped_strict = _evaluate_ranges(
        deduped_pred,
        gold,
        overlap_threshold=overlap_threshold,
        force_source_match=force_source_match,
    )["report"]

    supported_gold = [
        span for span in gold if span.label in _APP_SUPPORTED_LABELS
    ]
    supported_pred = [
        span for span in deduped_pred if span.label in _APP_SUPPORTED_LABELS
    ]

    supported_strict = _evaluate_ranges(
        supported_pred,
        supported_gold,
        overlap_threshold=overlap_threshold,
        force_source_match=force_source_match,
    )["report"]

    supported_relaxed = _evaluate_ranges(
        supported_pred,
        supported_gold,
        overlap_threshold=_APP_RELAXED_OVERLAP_THRESHOLD,
        force_source_match=force_source_match,
    )["report"]

    any_overlap_coverage = {
        label: _count_gold_any_overlap(
            supported_pred,
            supported_gold,
            label=label,
            force_source_match=force_source_match,
        )
        for label in _APP_OVERLAP_LABELS
    }

    return {
        "supported_labels": list(_APP_SUPPORTED_LABELS),
        "deduped_predictions": {
            "overlap_threshold": overlap_threshold,
            "counts": deduped_strict["counts"],
            "recall": deduped_strict["recall"],
            "precision": deduped_strict["precision"],
        },
        "supported_labels_strict": {
            "overlap_threshold": overlap_threshold,
            "counts": supported_strict["counts"],
            "recall": supported_strict["recall"],
            "precision": supported_strict["precision"],
        },
        "supported_labels_relaxed": {
            "overlap_threshold": _APP_RELAXED_OVERLAP_THRESHOLD,
            "counts": supported_relaxed["counts"],
            "recall": supported_relaxed["recall"],
            "precision": supported_relaxed["precision"],
        },
        "any_overlap_coverage": any_overlap_coverage,
    }


def evaluate_predicted_vs_freeform(
    predicted: list[LabeledRange],
    gold: list[LabeledRange],
    *,
    overlap_threshold: float = 0.5,
    force_source_match: bool = False,
) -> dict[str, Any]:
    predicted_resolved = _resolve_howto_section_ranges(predicted)
    gold_resolved = _resolve_howto_section_ranges(gold)

    gold_deduped, gold_dedupe = _dedupe_gold_ranges(gold_resolved)
    strict = _evaluate_ranges(
        predicted_resolved,
        gold_deduped,
        overlap_threshold=overlap_threshold,
        force_source_match=force_source_match,
    )
    strict_precision = float(strict["report"].get("precision", 0.0))
    strict_recall = float(strict["report"].get("recall", 0.0))
    strict_f1 = _f1_score(strict_precision, strict_recall)
    strict["report"]["f1"] = strict_f1

    practical = _evaluate_practical_ranges(
        predicted_resolved,
        gold_deduped,
        force_source_match=force_source_match,
    )
    deduped_pred = _dedupe_predicted_ranges(predicted_resolved)
    supported_gold = [span for span in gold_deduped if span.label in _APP_SUPPORTED_LABELS]
    supported_pred = [span for span in deduped_pred if span.label in _APP_SUPPORTED_LABELS]
    supported_practical = _evaluate_practical_ranges(
        supported_pred,
        supported_gold,
        force_source_match=force_source_match,
    )
    span_width_stats = {
        "gold": _span_width_stats(gold_deduped),
        "pred": _span_width_stats(predicted_resolved),
    }
    granularity_mismatch = _detect_granularity_mismatch(
        strict_f1=strict_f1,
        supported_practical_recall=float(supported_practical.get("recall", 0.0)),
        span_width_stats=span_width_stats,
    )

    app_aligned = _build_app_aligned_report(
        predicted_resolved,
        gold_deduped,
        overlap_threshold=overlap_threshold,
        force_source_match=force_source_match,
    )
    supported_relaxed = app_aligned.get("supported_labels_relaxed", {})
    strict["report"]["app_aligned"] = app_aligned
    strict["report"]["supported_precision"] = float(supported_relaxed.get("precision", 0.0))
    strict["report"]["supported_recall"] = float(supported_relaxed.get("recall", 0.0))
    strict["report"]["practical_precision"] = float(practical.get("precision", 0.0))
    strict["report"]["practical_recall"] = float(practical.get("recall", 0.0))
    strict["report"]["practical_f1"] = float(practical.get("f1", 0.0))
    strict["report"]["practical_counts"] = practical.get("counts", {})
    strict["report"]["practical_per_label"] = practical.get("per_label", {})
    strict["report"]["practical_matching"] = {
        "matched_gold_span_ids": practical.get("matched_gold_span_ids", []),
        "matched_pred_span_ids": practical.get("matched_pred_span_ids", []),
    }
    strict["report"]["supported_practical_precision"] = float(
        supported_practical.get("precision", 0.0)
    )
    strict["report"]["supported_practical_recall"] = float(
        supported_practical.get("recall", 0.0)
    )
    strict["report"]["supported_practical_f1"] = float(supported_practical.get("f1", 0.0))
    strict["report"]["supported_practical_counts"] = supported_practical.get("counts", {})
    strict["report"]["supported_practical_matching"] = {
        "matched_gold_span_ids": supported_practical.get("matched_gold_span_ids", []),
        "matched_pred_span_ids": supported_practical.get("matched_pred_span_ids", []),
    }
    strict["report"]["span_width_stats"] = span_width_stats
    strict["report"]["granularity_mismatch"] = granularity_mismatch
    strict["report"]["source_matching_mode"] = (
        "forced" if force_source_match else "strict"
    )
    strict["report"]["gold_dedupe"] = gold_dedupe
    strict["report"]["classification_only"] = _build_classification_only_report(
        predicted_resolved,
        gold_deduped,
        force_source_match=force_source_match,
    )
    attach_recipe_count_diagnostics(strict["report"])
    return {
        "report": strict["report"],
        "missed_gold": [asdict(span) for span in strict["missed_gold"]],
        "false_positive_preds": [asdict(span) for span in strict["false_positive_preds"]],
    }


def attach_recipe_count_diagnostics(
    report: dict[str, Any],
    *,
    gold_recipe_headers: int | None = None,
    gold_recipe_headers_source: str | None = None,
    predicted_recipe_count: int | None = None,
    predicted_recipe_count_source: str | None = None,
) -> dict[str, Any]:
    """Attach recipe-count diagnostics to a freeform eval report."""
    per_label = report.get("per_label")
    recipe_row = (
        per_label.get(_RECIPE_HEADER_LABEL)
        if isinstance(per_label, dict)
        else None
    )
    if not isinstance(recipe_row, dict):
        recipe_row = {}

    recipe_counts = report.get("recipe_counts")
    if not isinstance(recipe_counts, dict):
        recipe_counts = {}

    computed_gold_headers = _safe_int(recipe_row.get("gold_total"))
    computed_pred_headers = _safe_int(recipe_row.get("pred_total"))

    existing_gold_headers = _safe_int(recipe_counts.get("gold_recipe_headers"))
    existing_pred_headers = _safe_int(recipe_counts.get("pred_recipe_headers"))
    existing_pred_recipe_count = _safe_int(recipe_counts.get("predicted_recipe_count"))

    final_gold_headers = (
        _safe_int(gold_recipe_headers)
        if gold_recipe_headers is not None
        else (
            existing_gold_headers
            if existing_gold_headers is not None
            else computed_gold_headers
        )
    )
    final_pred_headers = (
        existing_pred_headers
        if existing_pred_headers is not None
        else computed_pred_headers
    )
    final_pred_recipe_count = (
        _safe_int(predicted_recipe_count)
        if predicted_recipe_count is not None
        else existing_pred_recipe_count
    )

    recipe_counts["gold_recipe_headers"] = final_gold_headers
    recipe_counts["pred_recipe_headers"] = final_pred_headers
    recipe_counts["predicted_recipe_count"] = final_pred_recipe_count

    if gold_recipe_headers_source:
        recipe_counts["gold_recipe_headers_source"] = str(gold_recipe_headers_source)
    elif (
        recipe_counts.get("gold_recipe_headers_source") is None
        and final_gold_headers is not None
    ):
        recipe_counts["gold_recipe_headers_source"] = "eval_per_label.RECIPE_TITLE"

    if predicted_recipe_count_source:
        recipe_counts["predicted_recipe_count_source"] = str(predicted_recipe_count_source)

    if final_gold_headers is not None and final_pred_recipe_count is not None:
        recipe_counts["predicted_minus_gold"] = final_pred_recipe_count - final_gold_headers
        recipe_counts["predicted_to_gold_ratio"] = (
            (final_pred_recipe_count / final_gold_headers) if final_gold_headers > 0 else None
        )
    else:
        recipe_counts["predicted_minus_gold"] = None
        recipe_counts["predicted_to_gold_ratio"] = None

    report["recipe_counts"] = recipe_counts
    return report


def format_freeform_eval_report_md(report: dict[str, Any]) -> str:
    counts = report.get("counts", {})
    practical_counts = report.get("practical_counts", {})
    boundary = report.get("boundary", {})
    per_label = report.get("per_label", {})
    strict_precision = float(report.get("precision", 0.0))
    strict_recall = float(report.get("recall", 0.0))
    strict_f1 = float(report.get("f1", _f1_score(strict_precision, strict_recall)))
    practical_precision = float(report.get("practical_precision", 0.0))
    practical_recall = float(report.get("practical_recall", 0.0))
    practical_f1 = float(
        report.get("practical_f1", _f1_score(practical_precision, practical_recall))
    )
    overlap_threshold = float(report.get("overlap_threshold", 0.0))
    supported_practical_precision = float(report.get("supported_practical_precision", 0.0))
    supported_practical_recall = float(report.get("supported_practical_recall", 0.0))
    supported_practical_f1 = float(report.get("supported_practical_f1", 0.0))
    span_width_stats = report.get("span_width_stats", {})
    granularity_mismatch = report.get("granularity_mismatch", {})
    supported_practical_counts = report.get("supported_practical_counts", {})
    recipe_counts = report.get("recipe_counts", {})
    lines = [
        "# Freeform Span Evaluation Report",
        "",
        "Practical / Content overlap (any-overlap):",
        (
            f"- Recall: {practical_recall:.3f} "
            f"({practical_counts.get('gold_matched', 0)}/{practical_counts.get('gold_total', 0)})"
        ),
        (
            f"- Precision: {practical_precision:.3f} "
            f"({practical_counts.get('pred_matched', 0)}/{practical_counts.get('pred_total', 0)})"
        ),
        f"- F1: {practical_f1:.3f}",
        (
            f"- Supported labels: recall={supported_practical_recall:.3f} "
            f"({supported_practical_counts.get('gold_matched', 0)}/"
            f"{supported_practical_counts.get('gold_total', 0)}), "
            f"precision={supported_practical_precision:.3f} "
            f"({supported_practical_counts.get('pred_matched', 0)}/"
            f"{supported_practical_counts.get('pred_total', 0)}), "
            f"f1={supported_practical_f1:.3f}"
        ),
        "",
        f"Strict / Localization (IoU>={overlap_threshold:g}):",
        (
            f"- Recall: {strict_recall:.3f} "
            f"({counts.get('gold_matched', 0)}/{counts.get('gold_total', 0)})"
        ),
        (
            f"- Precision: {strict_precision:.3f} "
            f"({counts.get('pred_matched', 0)}/{counts.get('pred_total', 0)})"
        ),
        f"- F1: {strict_f1:.3f}",
        "",
        f"Gold spans: {counts.get('gold_total', 0)}",
        f"Predicted spans: {counts.get('pred_total', 0)}",
        f"Recall (gold matched): {report.get('recall', 0):.3f} ({counts.get('gold_matched', 0)}/{counts.get('gold_total', 0)})",
        f"Precision (pred matched): {report.get('precision', 0):.3f} ({counts.get('pred_matched', 0)}/{counts.get('pred_total', 0)})",
        "",
    ]
    if isinstance(recipe_counts, dict):
        gold_recipe_headers = _safe_int(recipe_counts.get("gold_recipe_headers"))
        pred_recipe_headers = _safe_int(recipe_counts.get("pred_recipe_headers"))
        predicted_recipe_count = _safe_int(recipe_counts.get("predicted_recipe_count"))
        predicted_minus_gold = _safe_int(recipe_counts.get("predicted_minus_gold"))
        predicted_to_gold_ratio = recipe_counts.get("predicted_to_gold_ratio")
        try:
            ratio_value = (
                float(predicted_to_gold_ratio)
                if predicted_to_gold_ratio is not None
                else None
            )
        except (TypeError, ValueError):
            ratio_value = None

        if (
            gold_recipe_headers is not None
            or pred_recipe_headers is not None
            or predicted_recipe_count is not None
        ):
            lines.append("Recipe count diagnostics:")
            if gold_recipe_headers is not None:
                lines.append(
                    f"- Golden recipes (RECIPE_TITLE headers): {gold_recipe_headers}"
                )
            if predicted_recipe_count is not None:
                lines.append(
                    f"- Predicted recipes from import: {predicted_recipe_count}"
                )
            if pred_recipe_headers is not None:
                lines.append(
                    f"- Predicted RECIPE_TITLE spans (eval surface): {pred_recipe_headers}"
                )
            if (
                gold_recipe_headers is not None
                and predicted_recipe_count is not None
                and predicted_minus_gold is not None
            ):
                if ratio_value is not None:
                    lines.append(
                        "- Predicted vs gold recipes: "
                        + f"{predicted_recipe_count}/{gold_recipe_headers} "
                        + f"(delta {predicted_minus_gold:+d}, ratio {ratio_value:.3f}x)"
                    )
                else:
                    lines.append(
                        "- Predicted vs gold recipes: "
                        + f"{predicted_recipe_count}/{gold_recipe_headers} "
                        + f"(delta {predicted_minus_gold:+d})"
                    )
            lines.append("")
    if isinstance(granularity_mismatch, dict) and bool(granularity_mismatch.get("likely")):
        ratio = float(granularity_mismatch.get("ratio_p50_pred_to_gold") or 0.0)
        reason = str(granularity_mismatch.get("reason") or "").strip()
        lines.extend(
            [
                "Granularity mismatch likely:",
                f"- {reason or 'Strict localization is low while practical overlap is high.'}",
                f"- Width p50 ratio (pred/gold): {ratio:.2f}",
                (
                    "- Interpretation: content overlap is strong, but strict IoU stays low "
                    "because prediction ranges are much coarser than gold spans."
                ),
                "",
            ]
        )
    if isinstance(span_width_stats, dict):
        gold_width = span_width_stats.get("gold", {})
        pred_width = span_width_stats.get("pred", {})
        lines.extend(
            [
                "Span width stats (inclusive block width):",
                (
                    "- Gold: "
                    + f"min={float(gold_width.get('min', 0.0)):.1f}, "
                    + f"p50={float(gold_width.get('p50', 0.0)):.1f}, "
                    + f"p90={float(gold_width.get('p90', 0.0)):.1f}, "
                    + f"max={float(gold_width.get('max', 0.0)):.1f}, "
                    + f"avg={float(gold_width.get('avg', 0.0)):.1f}"
                ),
                (
                    "- Pred: "
                    + f"min={float(pred_width.get('min', 0.0)):.1f}, "
                    + f"p50={float(pred_width.get('p50', 0.0)):.1f}, "
                    + f"p90={float(pred_width.get('p90', 0.0)):.1f}, "
                    + f"max={float(pred_width.get('max', 0.0)):.1f}, "
                    + f"avg={float(pred_width.get('avg', 0.0)):.1f}"
                ),
                "",
            ]
        )
    gold_dedupe = report.get("gold_dedupe")
    if isinstance(gold_dedupe, dict):
        lines.extend(
            [
                "Gold dedupe:",
                "- Default dedupe: enabled",
                (
                    "- Input -> deduped gold: "
                    + f"{gold_dedupe.get('input_gold_total', 0)} -> "
                    + f"{gold_dedupe.get('deduped_gold_total', 0)} "
                    + f"(removed {gold_dedupe.get('rows_removed', 0)} rows)"
                ),
                (
                    "- Conflict groups: "
                    + f"{gold_dedupe.get('conflict_groups', 0)} "
                    + f"(majority resolved {gold_dedupe.get('conflict_groups_resolved_majority', 0)}, "
                    + f"tie dropped {gold_dedupe.get('conflict_groups_dropped_tie', 0)})"
                ),
            ]
        )
        rows_removed = int(gold_dedupe.get("rows_removed", 0))
        if rows_removed > 0:
            lines.append(
                "- Why counts can shrink: export rows are spans, eval units are block ranges; "
                "multiple spans that map to the same block range are deduped."
            )
        conflict_rows_dropped_tie = int(gold_dedupe.get("conflict_rows_dropped_tie", 0))
        if conflict_rows_dropped_tie > 0:
            lines.append(
                f"- Dropped rows from tie conflicts: {conflict_rows_dropped_tie}"
            )
        lines.append("")
    lines.extend(
        [
            "Boundary diagnostics:",
            f"- correct: {boundary.get('correct', 0)}",
            f"- over: {boundary.get('over', 0)}",
            f"- under: {boundary.get('under', 0)}",
            f"- partial: {boundary.get('partial', 0)}",
            "",
            "Per-label metrics:",
        ]
    )
    for label in sorted(per_label):
        row = per_label[label]
        lines.append(
            "- "
            + f"{label}: recall={row.get('recall', 0):.3f} "
            + f"({row.get('gold_matched', 0)}/{row.get('gold_total', 0)}), "
            + f"precision={row.get('precision', 0):.3f} "
            + f"({row.get('pred_matched', 0)}/{row.get('pred_total', 0)})"
        )
    app_aligned = report.get("app_aligned")
    if isinstance(app_aligned, dict):
        deduped = app_aligned.get("deduped_predictions", {})
        supported_strict = app_aligned.get("supported_labels_strict", {})
        supported_relaxed = app_aligned.get("supported_labels_relaxed", {})
        supported_labels = app_aligned.get("supported_labels", [])
        labels_text = ", ".join(str(label) for label in supported_labels)
        dedup_counts = deduped.get("counts", {})
        strict_counts = supported_strict.get("counts", {})
        relaxed_counts = supported_relaxed.get("counts", {})
        lines.extend(
            [
                "",
                "App-aligned diagnostics:",
                (
                    "- Deduped predictions (strict): "
                    + f"recall={deduped.get('recall', 0):.3f} "
                    + f"({dedup_counts.get('gold_matched', 0)}/{dedup_counts.get('gold_total', 0)}), "
                    + f"precision={deduped.get('precision', 0):.3f} "
                    + f"({dedup_counts.get('pred_matched', 0)}/{dedup_counts.get('pred_total', 0)}), "
                    + f"overlap>={deduped.get('overlap_threshold', 0)}"
                ),
                (
                    "- Supported labels only (strict): "
                    + f"recall={supported_strict.get('recall', 0):.3f} "
                    + f"({strict_counts.get('gold_matched', 0)}/{strict_counts.get('gold_total', 0)}), "
                    + f"precision={supported_strict.get('precision', 0):.3f} "
                    + f"({strict_counts.get('pred_matched', 0)}/{strict_counts.get('pred_total', 0)}), "
                    + f"overlap>={supported_strict.get('overlap_threshold', 0)}, labels=[{labels_text}]"
                ),
                (
                    "- Supported labels only (relaxed): "
                    + f"recall={supported_relaxed.get('recall', 0):.3f} "
                    + f"({relaxed_counts.get('gold_matched', 0)}/{relaxed_counts.get('gold_total', 0)}), "
                    + f"precision={supported_relaxed.get('precision', 0):.3f} "
                    + f"({relaxed_counts.get('pred_matched', 0)}/{relaxed_counts.get('pred_total', 0)}), "
                    + f"overlap>={supported_relaxed.get('overlap_threshold', 0)}"
                ),
                "- Any-overlap coverage (same label, IoU>0):",
            ]
        )
        any_overlap = app_aligned.get("any_overlap_coverage", {})
        for label in _APP_OVERLAP_LABELS:
            row = any_overlap.get(label, {})
            lines.append(
                f"  {label}: coverage={row.get('coverage', 0):.3f} "
                f"({row.get('gold_with_any_overlap', 0)}/{row.get('gold_total', 0)})"
            )
    classification_only = report.get("classification_only")
    if isinstance(classification_only, dict):
        supported_labels = classification_only.get("supported_labels", [])
        labels_text = ", ".join(str(label) for label in supported_labels)
        lines.extend(
            [
                "",
                "Classification-only diagnostics (boundary-insensitive):",
                (
                    "- Same-label any-overlap: "
                    + f"rate={classification_only.get('same_label_any_overlap_rate', 0):.3f} "
                    + f"({classification_only.get('gold_with_same_label_any_overlap', 0)}/"
                    + f"{classification_only.get('gold_total', 0)})"
                ),
                (
                    "- Best-overlap label match: "
                    + f"rate={classification_only.get('best_label_match_rate', 0):.3f} "
                    + f"({classification_only.get('gold_best_label_match', 0)}/"
                    + f"{classification_only.get('gold_total', 0)})"
                ),
                (
                    "- Any-overlap coverage (label-agnostic): "
                    + f"rate={classification_only.get('any_overlap_rate', 0):.3f} "
                    + f"({classification_only.get('gold_with_any_overlap', 0)}/"
                    + f"{classification_only.get('gold_total', 0)}), "
                    + f"deduped_pred_total={classification_only.get('deduped_pred_total', 0)}"
                ),
                (
                    "- Supported-label same-label any-overlap: "
                    + f"rate={classification_only.get('supported_same_label_any_overlap_rate', 0):.3f} "
                    + f"({classification_only.get('supported_gold_with_same_label_any_overlap', 0)}/"
                    + f"{classification_only.get('supported_gold_total', 0)}), "
                    + f"labels=[{labels_text}]"
                ),
                "- Per-label same-label any-overlap:",
            ]
        )
        per_label = classification_only.get("per_label", {})
        for label in sorted(per_label):
            row = per_label[label]
            lines.append(
                f"  {label}: rate={row.get('same_label_any_overlap_rate', 0):.3f} "
                f"({row.get('gold_with_same_label_any_overlap', 0)}/{row.get('gold_total', 0)})"
            )
    lines.extend(
        [
            "",
            f"Source matching mode: {report.get('source_matching_mode', 'strict')}",
            f"Overlap threshold: {report.get('overlap_threshold', 0)}",
            f"Missed gold spans: {counts.get('gold_missed', 0)}",
            f"False-positive predictions: {counts.get('pred_false_positive', 0)}",
            "",
        ]
    )
    return "\n".join(lines)
