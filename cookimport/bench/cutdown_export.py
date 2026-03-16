from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any

from cookimport.labelstudio.label_config_freeform import normalize_freeform_label
from cookimport.staging.stage_block_predictions import FREEFORM_LABELS

_FREEFORM_LABEL_SET = set(FREEFORM_LABELS)
_WHITESPACE_RE = re.compile(r"\s+")


def build_line_role_joined_line_rows(
    *,
    report: dict[str, Any],
    eval_output_dir: Path,
    line_role_predictions_path: Path | None,
) -> list[dict[str, Any]]:
    canonical_payload = report.get("canonical")
    if not isinstance(canonical_payload, dict):
        return []

    canonical_text_path_raw = canonical_payload.get("canonical_text_path")
    canonical_spans_path_raw = canonical_payload.get("canonical_span_labels_path")
    if not isinstance(canonical_text_path_raw, str) or not isinstance(
        canonical_spans_path_raw, str
    ):
        return []

    canonical_text_path = Path(canonical_text_path_raw)
    canonical_spans_path = Path(canonical_spans_path_raw)
    if not canonical_text_path.exists() or not canonical_spans_path.exists():
        return []

    canonical_text = canonical_text_path.read_text(encoding="utf-8")
    canonical_lines = _build_canonical_lines(canonical_text)
    gold_spans = _load_gold_spans(canonical_spans_path)
    gold_labels_by_line = _line_gold_labels(lines=canonical_lines, spans=gold_spans)

    wrong_rows = _read_jsonl(eval_output_dir / "wrong_label_lines.jsonl")
    pred_overrides: dict[int, str] = {}
    for row in wrong_rows:
        line_index = _coerce_int(row.get("line_index"))
        if line_index is None:
            continue
        normalized = _normalize_label(row.get("pred_label"))
        pred_overrides[line_index] = normalized

    line_role_meta: dict[int, dict[str, Any]] = {}
    if line_role_predictions_path is not None and line_role_predictions_path.exists():
        line_role_meta = _build_line_role_meta_by_line_index(
            canonical_lines=canonical_lines,
            prediction_rows=_read_jsonl(line_role_predictions_path),
        )

    joined_rows: list[dict[str, Any]] = []
    for line in canonical_lines:
        line_index = int(line["line_index"])
        gold_label = gold_labels_by_line.get(line_index, "OTHER")
        pred_label = pred_overrides.get(line_index, gold_label)
        line_meta = line_role_meta.get(line_index, {})
        joined_rows.append(
            {
                "sample_id": f"line:{line_index:06d}",
                "line_index": line_index,
                "line_text": str(line.get("text") or ""),
                "gold_label": gold_label,
                "pred_label": pred_label,
                "is_wrong_label": pred_label != gold_label,
                "within_recipe_span": line_meta.get("within_recipe_span"),
                "decided_by": line_meta.get("decided_by"),
                "recipe_id": line_meta.get("recipe_id"),
                "escalation_reasons": line_meta.get("escalation_reasons"),
                "line_role_match_kind": str(line_meta.get("match_kind") or "unmatched"),
                "line_role_prediction_atomic_index": line_meta.get(
                    "prediction_atomic_index"
                ),
            }
        )
    joined_rows.sort(key=lambda row: int(row["line_index"]))
    return joined_rows


def write_line_role_stable_samples(
    *,
    output_dir: Path,
    joined_line_rows: list[dict[str, Any]],
    flips_rows: list[dict[str, Any]],
    sample_limit: int = 80,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    sampled_indices = _sample_indices_evenly(len(joined_line_rows), sample_limit)
    sampled_all = [joined_line_rows[index] for index in sampled_indices]
    sampled_by_id = {str(row.get("sample_id")): row for row in sampled_all}

    wrong_rows = [row for row in sampled_all if bool(row.get("is_wrong_label"))]
    correct_rows = [row for row in sampled_all if not bool(row.get("is_wrong_label"))]
    aligned_rows = sampled_all
    flip_rows = [
        row
        for row in flips_rows
        if str(row.get("sample_id") or "") in sampled_by_id
    ]

    wrong_path = output_dir / "wrong_label_lines.sample.jsonl"
    correct_path = output_dir / "correct_label_lines.sample.jsonl"
    aligned_path = output_dir / "aligned_prediction_blocks.sample.jsonl"
    flips_path = output_dir / "line_role_flips_vs_baseline.sample.jsonl"
    _write_jsonl(wrong_path, wrong_rows)
    _write_jsonl(correct_path, correct_rows)
    _write_jsonl(aligned_path, aligned_rows)
    _write_jsonl(flips_path, flip_rows)
    return {
        "sample_limit": int(sample_limit),
        "joined_line_rows_total": len(joined_line_rows),
        "sampled_rows_total": len(sampled_all),
        "wrong_sample_rows": len(wrong_rows),
        "correct_sample_rows": len(correct_rows),
        "aligned_sample_rows": len(aligned_rows),
        "flip_sample_rows": len(flip_rows),
        "wrong_label_lines_sample_jsonl": str(wrong_path),
        "correct_label_lines_sample_jsonl": str(correct_path),
        "aligned_prediction_blocks_sample_jsonl": str(aligned_path),
        "line_role_flips_vs_baseline_sample_jsonl": str(flips_path),
    }


def write_prompt_eval_alignment_doc(
    *,
    output_path: Path,
    llm_recipe_pipeline: str,
    line_role_pipeline: str,
    atomic_block_splitter: str,
) -> None:
    lines = [
        "# Prompt ↔ Eval Alignment",
        "",
        "This run uses canonical line-label scoring.",
        "",
        "## Prompt Families",
        "",
        (
            f"- Recipe-object extraction pipeline: `{llm_recipe_pipeline}` "
            "(legacy recipe span/schema prompts)."
        ),
        (
            f"- Atomic block splitter: `{atomic_block_splitter}` "
            "(deterministic block-to-line atomization)."
        ),
        (
            f"- Canonical line-role pipeline: `{line_role_pipeline}` "
            "(direct one-label-per-line predictions)."
        ),
        "",
        "## Artifact Families",
        "",
        "- `eval_report.json` + `eval_report.md`: canonical benchmark metrics.",
        "- `wrong_label_lines.jsonl` + `aligned_prediction_blocks.jsonl`: evaluator diagnostics.",
        "- `line-role-pipeline/line_role_predictions.jsonl`: direct canonical line-role outputs.",
        "- `line-role-pipeline/line_role_flips_vs_baseline.jsonl`: inferred baseline-vs-candidate deltas.",
        "- `line-role-pipeline/slice_metrics.json`: slice-level quality signals.",
        "- `line-role-pipeline/knowledge_budget.json`: `KNOWLEDGE` usage inside vs outside recipe spans.",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return float(number)


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return None


def _normalize_label(value: Any) -> str:
    normalized = normalize_freeform_label(str(value or "OTHER"))
    if normalized not in _FREEFORM_LABEL_SET:
        return "OTHER"
    return normalized


def _build_line_role_meta_by_line_index(
    *,
    canonical_lines: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    meta_by_line_index: dict[int, dict[str, Any]] = {}
    matched_prediction_positions: set[int] = set()
    canonical_text_by_index = {
        int(row["line_index"]): _normalize_line_text(row.get("text"))
        for row in canonical_lines
    }

    for position, row in enumerate(prediction_rows):
        atomic_index = _coerce_int(row.get("atomic_index"))
        if atomic_index is None:
            continue
        canonical_text = canonical_text_by_index.get(atomic_index)
        prediction_text = _normalize_line_text(row.get("text"))
        if not canonical_text or not prediction_text or canonical_text != prediction_text:
            continue
        meta_by_line_index[atomic_index] = _line_role_meta_payload(
            row,
            match_kind="atomic_index_exact_text",
        )
        matched_prediction_positions.add(position)

    remaining_canonical: list[tuple[int, str]] = []
    for row in canonical_lines:
        line_index = int(row["line_index"])
        if line_index in meta_by_line_index:
            continue
        remaining_canonical.append(
            (
                line_index,
                _normalize_line_text(row.get("text")),
            )
        )

    remaining_predictions: list[tuple[int, dict[str, Any], str]] = []
    for position, row in enumerate(prediction_rows):
        if position in matched_prediction_positions:
            continue
        remaining_predictions.append(
            (
                position,
                row,
                _normalize_line_text(row.get("text")),
            )
        )

    canonical_texts = [text for _, text in remaining_canonical]
    prediction_texts = [text for _, _, text in remaining_predictions]
    matcher = difflib.SequenceMatcher(
        a=canonical_texts,
        b=prediction_texts,
        autojunk=False,
    )
    for tag, canon_start, canon_end, pred_start, pred_end in matcher.get_opcodes():
        if tag != "equal":
            continue
        for offset in range(canon_end - canon_start):
            line_index, normalized_text = remaining_canonical[canon_start + offset]
            _, row, prediction_text = remaining_predictions[pred_start + offset]
            if not normalized_text or normalized_text != prediction_text:
                continue
            meta_by_line_index[line_index] = _line_role_meta_payload(
                row,
                match_kind="exact_text_occurrence",
            )

    return meta_by_line_index


def _line_role_meta_payload(
    row: dict[str, Any],
    *,
    match_kind: str,
) -> dict[str, Any]:
    return {
        "decided_by": str(row.get("decided_by") or "").strip().lower() or None,
        "within_recipe_span": _coerce_bool(row.get("within_recipe_span")),
        "recipe_id": str(row.get("recipe_id") or "").strip() or None,
        "escalation_reasons": row.get("escalation_reasons") or [],
        "match_kind": str(match_kind),
        "prediction_atomic_index": _coerce_int(row.get("atomic_index")),
    }


def _normalize_line_text(value: Any) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "").strip())


def _build_canonical_lines(canonical_text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = 0
    text_length = len(canonical_text)
    while cursor < text_length:
        line_end = canonical_text.find("\n", cursor)
        if line_end == -1:
            line_end = text_length
        if line_end > cursor:
            rows.append(
                {
                    "line_index": len(rows),
                    "start_char": cursor,
                    "end_char": line_end,
                    "text": canonical_text[cursor:line_end],
                }
            )
        cursor = line_end + 1
    if not rows and canonical_text:
        rows.append(
            {
                "line_index": 0,
                "start_char": 0,
                "end_char": len(canonical_text),
                "text": canonical_text,
            }
        )
    return rows


def _load_gold_spans(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _read_jsonl(path):
        start_char = _coerce_int(row.get("start_char"))
        end_char = _coerce_int(row.get("end_char"))
        if start_char is None or end_char is None or end_char <= start_char:
            continue
        label = _normalize_label(row.get("label"))
        rows.append(
            {
                "label": label,
                "start_char": start_char,
                "end_char": end_char,
            }
        )
    rows.sort(key=lambda row: (int(row["start_char"]), int(row["end_char"])))
    return rows


def _line_gold_labels(
    *,
    lines: list[dict[str, Any]],
    spans: list[dict[str, Any]],
) -> dict[int, str]:
    labels_by_line: dict[int, str] = {}
    span_cursor = 0
    span_total = len(spans)
    for line in lines:
        line_index = int(line["line_index"])
        line_start = int(line["start_char"])
        line_end = int(line["end_char"])
        while span_cursor < span_total and int(spans[span_cursor]["end_char"]) <= line_start:
            span_cursor += 1
        overlap_by_label: dict[str, int] = {}
        scan_index = span_cursor
        while scan_index < span_total:
            span = spans[scan_index]
            span_start = int(span["start_char"])
            if span_start >= line_end:
                break
            span_end = int(span["end_char"])
            overlap = _overlap_len(line_start, line_end, span_start, span_end)
            if overlap > 0:
                label = str(span["label"])
                overlap_by_label[label] = overlap_by_label.get(label, 0) + overlap
            scan_index += 1
        if not overlap_by_label:
            labels_by_line[line_index] = "OTHER"
            continue
        labels_by_line[line_index] = sorted(
            overlap_by_label.items(), key=lambda item: (-item[1], item[0])
        )[0][0]
    return labels_by_line


def _overlap_len(
    left_start: int,
    left_end: int,
    right_start: int,
    right_end: int,
) -> int:
    return max(0, min(left_end, right_end) - max(left_start, right_start))


def _sample_indices_evenly(total_count: int, sample_limit: int) -> list[int]:
    if total_count <= 0 or sample_limit <= 0:
        return []
    if sample_limit >= total_count:
        return list(range(total_count))
    if sample_limit == 1:
        return [0]
    last_index = total_count - 1
    selected = {
        int(round(position * last_index / (sample_limit - 1)))
        for position in range(sample_limit)
    }
    if len(selected) < sample_limit:
        for index in range(total_count):
            if index in selected:
                continue
            selected.add(index)
            if len(selected) >= sample_limit:
                break
    return sorted(selected)[:sample_limit]
