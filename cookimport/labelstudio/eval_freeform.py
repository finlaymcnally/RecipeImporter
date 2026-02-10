from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


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
    spans: list[LabeledRange] = []
    for line in tasks_path.read_text(encoding="utf-8").splitlines():
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
        label = _map_chunk_to_label(data)
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


def _map_chunk_to_label(data: dict[str, Any]) -> str | None:
    chunk_level = str(data.get("chunk_level") or "")
    chunk_type = str(data.get("chunk_type") or "")
    chunk_hint = str(data.get("chunk_type_hint") or "")

    if chunk_level == "structural":
        if chunk_type == "recipe_block" or chunk_hint == "recipe":
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
        return "NOTES"
    if (
        "variant" in chunk_type
        or "variant" in chunk_hint
    ):
        return "VARIANT"
    if (
        "tip" in chunk_type
        or "tip" in chunk_hint
        or "knowledge" in chunk_type
        or "knowledge" in chunk_hint
        or "advice" in chunk_type
        or "advice" in chunk_hint
    ):
        return "TIP"
    if chunk_type in {"recipe_description"}:
        return "NARRATIVE"
    if chunk_type.startswith("atom_"):
        atom_kind = chunk_type[5:]
        if atom_kind in {"ingredient_like"}:
            return "INGREDIENT_LINE"
        if atom_kind in {"step", "list_item"}:
            return "INSTRUCTION_LINE"
        if atom_kind in {"paragraph", "sentence"}:
            return "NARRATIVE"
    return "OTHER"


def _normalize_freeform_label(label: str) -> str:
    normalized = label.strip().upper()
    if normalized == "KNOWLEDGE":
        return "TIP"
    if normalized == "NOTE":
        return "NOTES"
    return normalized


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


def _compatible_source(pred: LabeledRange, gold: LabeledRange) -> bool:
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


def evaluate_predicted_vs_freeform(
    predicted: list[LabeledRange],
    gold: list[LabeledRange],
    *,
    overlap_threshold: float = 0.5,
) -> dict[str, Any]:
    matches: list[LabeledMatch] = []
    missed_gold: list[LabeledRange] = []
    matched_pred_ids: set[str] = set()

    for gold_span in gold:
        best_match: LabeledMatch | None = None
        for pred_span in predicted:
            if pred_span.label != gold_span.label:
                continue
            if not _compatible_source(pred_span, gold_span):
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
        "missed_gold": [asdict(span) for span in missed_gold],
        "false_positive_preds": [asdict(span) for span in false_positive_preds],
    }


def format_freeform_eval_report_md(report: dict[str, Any]) -> str:
    counts = report.get("counts", {})
    boundary = report.get("boundary", {})
    per_label = report.get("per_label", {})
    lines = [
        "# Freeform Span Evaluation Report",
        "",
        f"Gold spans: {counts.get('gold_total', 0)}",
        f"Predicted spans: {counts.get('pred_total', 0)}",
        f"Recall (gold matched): {report.get('recall', 0):.3f} ({counts.get('gold_matched', 0)}/{counts.get('gold_total', 0)})",
        f"Precision (pred matched): {report.get('precision', 0):.3f} ({counts.get('pred_matched', 0)}/{counts.get('pred_total', 0)})",
        "",
        "Boundary diagnostics:",
        f"- correct: {boundary.get('correct', 0)}",
        f"- over: {boundary.get('over', 0)}",
        f"- under: {boundary.get('under', 0)}",
        f"- partial: {boundary.get('partial', 0)}",
        "",
        "Per-label metrics:",
    ]
    for label in sorted(per_label):
        row = per_label[label]
        lines.append(
            "- "
            + f"{label}: recall={row.get('recall', 0):.3f} "
            + f"({row.get('gold_matched', 0)}/{row.get('gold_total', 0)}), "
            + f"precision={row.get('precision', 0):.3f} "
            + f"({row.get('pred_matched', 0)}/{row.get('pred_total', 0)})"
        )
    lines.extend(
        [
            "",
            f"Overlap threshold: {report.get('overlap_threshold', 0)}",
            f"Missed gold spans: {counts.get('gold_missed', 0)}",
            f"False-positive predictions: {counts.get('pred_false_positive', 0)}",
            "",
        ]
    )
    return "\n".join(lines)
