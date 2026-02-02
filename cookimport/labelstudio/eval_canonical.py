from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import json


@dataclass(frozen=True)
class Span:
    span_id: str
    source_hash: str | None
    source_file: str
    start_block_index: int
    end_block_index: int

    def normalized(self) -> "Span":
        start = self.start_block_index
        end = self.end_block_index
        if start > end:
            start, end = end, start
        return Span(
            span_id=self.span_id,
            source_hash=self.source_hash,
            source_file=self.source_file,
            start_block_index=start,
            end_block_index=end,
        )


@dataclass(frozen=True)
class Match:
    gold: Span
    predicted: Span
    overlap: float
    classification: str


def load_gold_spans(path: Path) -> list[Span]:
    spans: list[Span] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            continue
        span_id = payload.get("span_id") or ""
        source_hash = payload.get("source_hash")
        source_file = payload.get("source_file")
        start = payload.get("start_block_index")
        end = payload.get("end_block_index")
        if not span_id or source_file is None or start is None or end is None:
            continue
        spans.append(
            Span(
                span_id=str(span_id),
                source_hash=str(source_hash) if source_hash else None,
                source_file=str(source_file),
                start_block_index=int(start),
                end_block_index=int(end),
            ).normalized()
        )
    return spans


def load_predicted_spans(run_dir: Path) -> list[Span]:
    tasks_path = run_dir / "label_studio_tasks.jsonl"
    if not tasks_path.exists():
        raise FileNotFoundError(f"Missing label_studio_tasks.jsonl in {run_dir}")
    spans: list[Span] = []
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
        if data.get("chunk_level") != "structural":
            continue
        chunk_type = data.get("chunk_type")
        chunk_hint = data.get("chunk_type_hint")
        if chunk_type != "recipe_block" and chunk_hint != "recipe":
            continue
        location = data.get("location")
        if not isinstance(location, dict):
            location = {}
        start, end = _location_to_range(location)
        if start is None or end is None:
            continue
        span_id = data.get("chunk_id") or f"pred:{start}:{end}"
        source_hash = data.get("source_hash")
        if source_hash is None:
            parsed_hash = _parse_chunk_id(span_id)
            source_hash = parsed_hash
        source_file = data.get("source_file")
        if source_file is None:
            source_file = "unknown"
        spans.append(
            Span(
                span_id=str(span_id),
                source_hash=str(source_hash) if source_hash else None,
                source_file=str(source_file),
                start_block_index=int(start),
                end_block_index=int(end),
            ).normalized()
        )
    return spans


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


def _overlap_ratio(a: Span, b: Span) -> float:
    a = a.normalized()
    b = b.normalized()
    intersection = max(0, min(a.end_block_index, b.end_block_index) - max(a.start_block_index, b.start_block_index) + 1)
    if intersection == 0:
        return 0.0
    union = (a.end_block_index - a.start_block_index + 1) + (b.end_block_index - b.start_block_index + 1) - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _compatible_source(pred: Span, gold: Span) -> bool:
    if pred.source_hash and gold.source_hash:
        if pred.source_hash == gold.source_hash:
            return True
        if gold.source_hash.startswith(pred.source_hash) or pred.source_hash.startswith(
            gold.source_hash
        ):
            return True
        return False
    return pred.source_file == gold.source_file


def evaluate_structural_vs_gold(
    predicted: list[Span],
    gold: list[Span],
    *,
    overlap_threshold: float = 0.5,
) -> dict[str, Any]:
    matches: list[Match] = []
    missed_gold: list[Span] = []
    matched_pred_ids: set[str] = set()

    for gold_span in gold:
        best_match: Match | None = None
        for pred_span in predicted:
            if not _compatible_source(pred_span, gold_span):
                continue
            overlap = _overlap_ratio(pred_span, gold_span)
            if best_match is None or overlap > best_match.overlap:
                classification = _classify_boundary(pred_span, gold_span)
                best_match = Match(gold_span, pred_span, overlap, classification)
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


def _classify_boundary(pred: Span, gold: Span) -> str:
    pred = pred.normalized()
    gold = gold.normalized()
    if pred.start_block_index == gold.start_block_index and pred.end_block_index == gold.end_block_index:
        return "correct"
    if pred.start_block_index <= gold.start_block_index and pred.end_block_index >= gold.end_block_index:
        return "over"
    if pred.start_block_index >= gold.start_block_index and pred.end_block_index <= gold.end_block_index:
        return "under"
    return "partial"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def format_eval_report_md(report: dict[str, Any]) -> str:
    counts = report.get("counts", {})
    boundary = report.get("boundary", {})
    lines = [
        "# Canonical Block Evaluation Report",
        "",
        f"Canonical gold recipes: {counts.get('gold_total', 0)}",
        f"Pipeline predicted recipes: {counts.get('pred_total', 0)}",
        f"Recall (gold matched): {report.get('recall', 0):.3f} ({counts.get('gold_matched', 0)}/{counts.get('gold_total', 0)})",
        f"Precision (pred matched): {report.get('precision', 0):.3f} ({counts.get('pred_matched', 0)}/{counts.get('pred_total', 0)})",
        "",
        "Boundary diagnostics:",
        f"- correct: {boundary.get('correct', 0)}",
        f"- over: {boundary.get('over', 0)}",
        f"- under: {boundary.get('under', 0)}",
        f"- partial: {boundary.get('partial', 0)}",
        "",
        f"Overlap threshold: {report.get('overlap_threshold', 0)}",
        f"Missed gold spans: {counts.get('gold_missed', 0)}",
        f"False-positive predictions: {counts.get('pred_false_positive', 0)}",
        "",
    ]
    return "\n".join(lines)
