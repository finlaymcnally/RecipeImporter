from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any

from cookimport.bench.pairwise_flips import (
    PRIMARY_LINE_ROLE_FLIPS_JSONL_FILE_NAME,
    PRIMARY_LINE_ROLE_FLIPS_SAMPLE_JSONL_FILE_NAME,
)
from cookimport.bench.row_gold_lines import (
    load_row_gold_line_labels,
    resolve_row_gold_path_from_eval_report,
)
from cookimport.labelstudio.label_config_freeform import normalize_freeform_label
from cookimport.staging.stage_block_predictions import FREEFORM_LABELS

_FREEFORM_LABEL_SET = set(FREEFORM_LABELS)
_WHITESPACE_RE = re.compile(r"\s+")
_TITLE_STRUCTURE_SUPPORT_LABELS = {
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "HOWTO_SECTION",
    "YIELD_LINE",
    "TIME_LINE",
}
_TITLE_STRUCTURE_LOOKAHEAD_LINES = 8


def build_line_role_joined_line_rows(
    *,
    report: dict[str, Any],
    eval_output_dir: Path,
    line_role_predictions_path: Path | None,
) -> list[dict[str, Any]]:
    canonical_lines, gold_label_sets_by_line = _load_eval_gold_lines(report)
    if not canonical_lines:
        return []

    wrong_rows = _read_jsonl(eval_output_dir / "wrong_label_lines.jsonl")
    pred_overrides: dict[int, str] = {}
    gold_overrides: dict[int, str] = {}
    for row in wrong_rows:
        line_index = _coerce_int(row.get("line_index"))
        if line_index is None:
            continue
        gold_normalized = _normalize_label(row.get("gold_label"))
        gold_overrides[line_index] = gold_normalized
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
        gold_labels = sorted(gold_label_sets_by_line.get(line_index) or {"OTHER"})
        projected_gold_label = _project_gold_label_for_joined_line_rows(
            line_index=line_index,
            gold_labels=gold_labels,
            gold_label_sets_by_line=gold_label_sets_by_line,
        )
        gold_label = gold_overrides.get(line_index, projected_gold_label)
        pred_label = pred_overrides.get(line_index, gold_label)
        line_meta = line_role_meta.get(line_index, {})
        joined_rows.append(
            {
                "sample_id": f"line:{line_index:06d}",
                "line_index": line_index,
                "line_text": str(line.get("text") or ""),
                "gold_label": gold_label,
                "gold_labels": gold_labels,
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


def _load_eval_gold_lines(
    report: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[int, set[str]]]:
    row_gold_path = resolve_row_gold_path_from_eval_report(report)
    if row_gold_path is None:
        return [], {}
    lines, raw_labels_by_line = load_row_gold_line_labels(
        row_gold_path,
        strict_empty_to_other=True,
    )
    return lines, {
        int(line_index): set(labels)
        for line_index, labels in raw_labels_by_line.items()
    }


def _project_gold_label_for_joined_line_rows(
    *,
    line_index: int,
    gold_labels: list[str],
    gold_label_sets_by_line: dict[int, set[str]],
) -> str:
    if not gold_labels:
        return "OTHER"
    if "OTHER" in gold_labels:
        return "OTHER"
    if "RECIPE_TITLE" not in gold_labels:
        return gold_labels[0]
    support = _find_title_support_context(
        line_index=line_index,
        labels_by_line=gold_label_sets_by_line,
    )
    if str(support.get("status") or "missing") == "supported":
        return gold_labels[0]
    return "OTHER"


def _find_title_support_context(
    *,
    line_index: int,
    labels_by_line: dict[int, set[str]],
) -> dict[str, Any]:
    for offset in range(1, _TITLE_STRUCTURE_LOOKAHEAD_LINES + 1):
        neighbor_labels = set(labels_by_line.get(line_index + offset) or set())
        non_other_labels = neighbor_labels - {"OTHER"}
        if not non_other_labels:
            continue
        if non_other_labels & _TITLE_STRUCTURE_SUPPORT_LABELS:
            return {
                "status": "supported",
                "support_line_index": line_index + offset,
                "support_labels": sorted(non_other_labels & _TITLE_STRUCTURE_SUPPORT_LABELS),
            }
        if "RECIPE_TITLE" in non_other_labels:
            return {
                "status": "later_title_before_structure",
                "later_title_line_index": line_index + offset,
                "later_title_labels": sorted(non_other_labels),
            }
    return {"status": "missing"}


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
    flips_path = output_dir / PRIMARY_LINE_ROLE_FLIPS_SAMPLE_JSONL_FILE_NAME
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
        "line_role_flips_vs_reference_sample_jsonl": str(flips_path),
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
        "This run uses source-row line-label scoring.",
        "The scorer reads the prediction manifest pointer pair directly instead of inferring legacy canonical artifacts.",
        "",
        "## Prompt Families",
        "",
        (
            f"- Recipe-object extraction pipeline: `{llm_recipe_pipeline}` "
            "(prior recipe span/schema prompts)."
        ),
        (
            f"- Legacy atomic block splitter flag: `{atomic_block_splitter}` "
            "(compatibility-only row candidate shaping when enabled)."
        ),
        (
            f"- Row line-role pipeline: `{line_role_pipeline}` "
            "(the requested prediction surface, not necessarily the final scored artifact mode)."
        ),
        "",
        "## Artifact Families",
        "",
        "- `eval_report.json` + `eval_report.md`: canonical benchmark metrics.",
        "- `wrong_label_lines.jsonl` + `aligned_prediction_blocks.jsonl`: evaluator diagnostics.",
        "- `line-role-pipeline/line_role_predictions.jsonl`: canonical line-role rows reused for reviewer diagnostics; benchmark eval prefers final-semantic rows when that artifact exists.",
        (
            f"- `line-role-pipeline/{PRIMARY_LINE_ROLE_FLIPS_JSONL_FILE_NAME}`: "
            "inferred reference-vs-candidate deltas."
        ),
        "- `line-role-pipeline/slice_metrics.json`: slice-level quality signals.",
        "- `line-role-pipeline/routing_summary.json`: excluded versus candidate outside-recipe routing plus recipe-local structure counts.",
        "- `line-role-pipeline/telemetry_summary.json`: the authoritative scoring-mode summary for projected line-role artifacts.",
        "- `manifest.json`: the authoritative source of `semantic_row_predictions_path` and `extracted_archive_path` used by the evaluator.",
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
