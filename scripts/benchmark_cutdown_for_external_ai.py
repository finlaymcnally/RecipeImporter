#!/usr/bin/env python3
"""Build a compact benchmark package for external AI review.

This script creates a deterministic, low-token benchmark package that preserves
the signals needed to answer:
1) how well the run performed, and
2) why the run performed that way.

It discovers benchmark run directories under an input root by looking for
folders that contain both `eval_report.json` and `run_manifest.json`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SAMPLE_LIMIT = 80
DEFAULT_TOP_CONFUSIONS = 8
DEFAULT_TOP_LABELS = 6
EXCERPT_LIMIT = 240

# Keep this focused on settings that are likely to explain quality deltas.
RUN_CONFIG_KEYS_OF_INTEREST = (
    "llm_recipe_pipeline",
    "eval_mode",
    "execution_mode",
    "sequence_matcher",
    "section_detector_backend",
    "ingredient_parser_backend",
    "ingredient_text_fix_backend",
    "ingredient_pre_normalize_mode",
    "ingredient_unit_canonicalizer",
    "instruction_step_segmentation_policy",
    "instruction_step_segmenter",
    "multi_recipe_splitter",
    "multi_recipe_for_the_guardrail",
    "multi_recipe_min_ingredient_lines",
    "multi_recipe_min_instruction_lines",
    "epub_extractor",
    "epub_unstructured_preprocess_mode",
    "epub_unstructured_html_parser_version",
    "workers",
    "predict_only",
)

ROOT_METADATA_FILES = (
    "README.md",
    "run_index.json",
    "comparison_summary.json",
    "process_manifest.json",
)

SAMPLED_JSONL_INPUTS = (
    ("wrong_label_lines.jsonl", "wrong_label_lines.sample.jsonl"),
    ("missed_gold_lines.jsonl", "missed_gold_lines.sample.jsonl"),
    ("unmatched_pred_blocks.jsonl", "unmatched_pred_blocks.sample.jsonl"),
)


@dataclass
class RunRecord:
    run_id: str
    source_key: str
    source_file: str | None
    source_hash: str | None
    llm_recipe_pipeline: str
    codex_enabled: bool
    metric_overall_line_accuracy: float | None
    metric_macro_f1_excluding_other: float | None
    metric_practical_f1: float | None
    worst_label_recall: dict[str, Any]
    run_timestamp: datetime | None
    output_subdir: str
    config_snapshot: dict[str, Any]
    top_confusions: list[dict[str, Any]]
    summary_path: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a compact benchmark package for external AI review and "
            "flatten it into markdown files."
        )
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        help=(
            "Benchmark root to scan. Can be a single run folder or a parent "
            "folder containing multiple run folders."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Output folder for the cutdown package. Default: <input_dir>_cutdown "
            "(sibling)."
        ),
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=DEFAULT_SAMPLE_LIMIT,
        help=f"Max rows per sampled JSONL artifact (default: {DEFAULT_SAMPLE_LIMIT}).",
    )
    parser.add_argument(
        "--top-confusions",
        type=int,
        default=DEFAULT_TOP_CONFUSIONS,
        help=f"Number of top confusion pairs to keep (default: {DEFAULT_TOP_CONFUSIONS}).",
    )
    parser.add_argument(
        "--top-labels",
        type=int,
        default=DEFAULT_TOP_LABELS,
        help=f"Number of low-recall/precision labels to keep (default: {DEFAULT_TOP_LABELS}).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output directory if it already exists.",
    )
    parser.add_argument(
        "--no-flatten",
        action="store_true",
        help="Skip flattening output folder into <output_dir>_md.",
    )
    parser.add_argument(
        "--flatten-script",
        type=Path,
        default=Path("docs/flatten-folders.sh"),
        help="Path to flatten script (default: docs/flatten-folders.sh).",
    )
    return parser.parse_args()


def _timestamp_now() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H.%M.%S")


def _parse_run_timestamp(run_id: str) -> datetime | None:
    try:
        return datetime.strptime(run_id, "%Y-%m-%d_%H.%M.%S")
    except ValueError:
        return None


def _is_run_dir(path: Path) -> bool:
    return (path / "eval_report.json").is_file() and (path / "run_manifest.json").is_file()


def _is_ignored_dir(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    if ".cache" in parts:
        return True
    for part in parts:
        if part.endswith("_cutdown") or part.endswith("_md"):
            return True
    return False


def _discover_run_dirs(input_dir: Path) -> list[Path]:
    discovered: dict[Path, None] = {}
    if _is_run_dir(input_dir):
        discovered[input_dir] = None

    for report_path in input_dir.rglob("eval_report.json"):
        run_dir = report_path.parent
        if _is_ignored_dir(run_dir):
            continue
        if _is_run_dir(run_dir):
            discovered[run_dir] = None

    return sorted(discovered.keys())


def _read_run_id_for_dir(run_dir: Path) -> str:
    manifest_path = run_dir / "run_manifest.json"
    try:
        manifest = _load_json(manifest_path)
    except Exception:
        return run_dir.name
    run_id = manifest.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        return run_id.strip()
    return run_dir.name


def _default_output_dir_from_runs(input_dir: Path, run_dirs: list[Path]) -> Path:
    run_ids = sorted({_read_run_id_for_dir(run_dir) for run_dir in run_dirs})
    timestamp_ids = sorted(
        run_id for run_id in run_ids if _parse_run_timestamp(run_id) is not None
    )
    if len(timestamp_ids) == 1:
        base_name = timestamp_ids[0]
    elif len(timestamp_ids) > 1:
        base_name = f"{timestamp_ids[0]}__to__{timestamp_ids[-1]}"
    else:
        base_name = input_dir.name
    return input_dir.parent / f"{base_name}_cutdown"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _excerpt(text: str, max_len: int = EXCERPT_LIMIT) -> str:
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3] + "..."


def _clip_large_text_fields(row: dict[str, Any]) -> dict[str, Any]:
    clipped = dict(row)
    for key in ("line_text_excerpt", "block_text_excerpt", "selected_text", "text"):
        value = clipped.get(key)
        if isinstance(value, str):
            clipped[key] = _excerpt(value)
    return clipped


def _write_jsonl_sample(
    *,
    source_path: Path,
    output_path: Path,
    sample_limit: int,
) -> dict[str, int]:
    rows = _iter_jsonl(source_path)
    sampled = [_clip_large_text_fields(row) for row in rows[:sample_limit]]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in sampled:
            handle.write(json.dumps(row))
            handle.write("\n")
    return {"total_rows": len(rows), "sample_rows": len(sampled)}


def _build_canonical_lines(canonical_text: str) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    cursor = 0
    for raw_line in canonical_text.splitlines(keepends=True):
        line_start = cursor
        line_end = line_start + len(raw_line)
        text_end = line_end
        while text_end > line_start and canonical_text[text_end - 1] in {"\n", "\r"}:
            text_end -= 1
        if text_end > line_start:
            lines.append(
                {
                    "line_index": len(lines),
                    "start_char": line_start,
                    "end_char": text_end,
                    "text": canonical_text[line_start:text_end],
                }
            )
        cursor = line_end
    if not lines and canonical_text:
        lines.append(
            {
                "line_index": 0,
                "start_char": 0,
                "end_char": len(canonical_text),
                "text": canonical_text,
            }
        )
    return lines


def _load_gold_spans(canonical_spans_path: Path) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for row in _iter_jsonl(canonical_spans_path):
        start_char = _coerce_int(row.get("start_char"))
        end_char = _coerce_int(row.get("end_char"))
        label = str(row.get("label") or "").strip()
        if start_char is None or end_char is None or end_char <= start_char:
            continue
        if not label:
            continue
        spans.append(
            {
                "label": label,
                "start_char": start_char,
                "end_char": end_char,
            }
        )
    spans.sort(key=lambda span: (int(span["start_char"]), int(span["end_char"])))
    return spans


def _overlap_len(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def _line_gold_labels(
    *,
    lines: list[dict[str, Any]],
    spans: list[dict[str, Any]],
) -> dict[int, list[str]]:
    labels_by_line: dict[int, list[str]] = {}
    span_cursor = 0
    span_total = len(spans)

    for line in lines:
        line_index = int(line["line_index"])
        line_start = int(line["start_char"])
        line_end = int(line["end_char"])

        while span_cursor < span_total and int(spans[span_cursor]["end_char"]) <= line_start:
            span_cursor += 1

        overlap_by_label: dict[str, int] = defaultdict(int)
        scan_index = span_cursor
        while scan_index < span_total:
            span = spans[scan_index]
            span_start = int(span["start_char"])
            if span_start >= line_end:
                break
            span_end = int(span["end_char"])
            overlap = _overlap_len(line_start, line_end, span_start, span_end)
            if overlap > 0:
                overlap_by_label[str(span["label"])] += overlap
            scan_index += 1

        if not overlap_by_label:
            labels_by_line[line_index] = ["OTHER"]
            continue

        ordered = sorted(
            overlap_by_label.items(),
            key=lambda item: (-item[1], item[0]),
        )
        labels_by_line[line_index] = [label for label, _ in ordered]

    return labels_by_line


def _build_correct_label_sample(
    *,
    eval_report: dict[str, Any],
    wrong_label_rows: list[dict[str, Any]],
    sample_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    canonical = eval_report.get("canonical")
    if not isinstance(canonical, dict):
        return [], {"status": "skipped", "reason": "missing_canonical_block"}

    canonical_text_path_raw = canonical.get("canonical_text_path")
    canonical_span_path_raw = canonical.get("canonical_span_labels_path")
    if not isinstance(canonical_text_path_raw, str) or not isinstance(canonical_span_path_raw, str):
        return [], {"status": "skipped", "reason": "missing_canonical_paths"}

    canonical_text_path = Path(canonical_text_path_raw)
    canonical_span_path = Path(canonical_span_path_raw)
    if not canonical_text_path.is_file() or not canonical_span_path.is_file():
        return [], {
            "status": "skipped",
            "reason": "canonical_paths_not_found",
            "canonical_text_path": str(canonical_text_path),
            "canonical_span_labels_path": str(canonical_span_path),
        }

    canonical_text = canonical_text_path.read_text(encoding="utf-8")
    lines = _build_canonical_lines(canonical_text)
    spans = _load_gold_spans(canonical_span_path)
    labels_by_line = _line_gold_labels(lines=lines, spans=spans)

    wrong_line_indices = {
        idx
        for row in wrong_label_rows
        if (idx := _coerce_int(row.get("line_index"))) is not None
    }

    primary_pool: list[dict[str, Any]] = []
    fallback_pool: list[dict[str, Any]] = []

    for line in lines:
        line_index = int(line["line_index"])
        if line_index in wrong_line_indices:
            continue
        gold_labels = labels_by_line.get(line_index, ["OTHER"])
        gold_label = gold_labels[0] if gold_labels else "OTHER"
        row = {
            "line_index": line_index,
            "line_text_excerpt": _excerpt(str(line.get("text") or "")),
            "gold_label": gold_label,
            "gold_labels": gold_labels,
            "pred_label": gold_label,
            "correctness_basis": "line_index_absent_from_wrong_label_lines",
        }
        if gold_label == "OTHER":
            fallback_pool.append(row)
        else:
            primary_pool.append(row)

    combined = primary_pool + fallback_pool
    sample = combined[:sample_limit]
    metadata = {
        "status": "ok",
        "candidate_rows_total": len(combined),
        "sample_rows": len(sample),
        "non_other_candidates": len(primary_pool),
        "other_candidates": len(fallback_pool),
        "canonical_text_path": str(canonical_text_path),
        "canonical_span_labels_path": str(canonical_span_path),
    }
    return sample, metadata


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row))
            handle.write("\n")


def _top_confusions(confusion: Any, top_k: int) -> list[dict[str, Any]]:
    if not isinstance(confusion, dict):
        return []
    rows: list[dict[str, Any]] = []
    for gold_label, pred_counts_raw in confusion.items():
        if not isinstance(gold_label, str) or not isinstance(pred_counts_raw, dict):
            continue
        row_total = 0
        clean_counts: dict[str, int] = {}
        for pred_label, count_raw in pred_counts_raw.items():
            if not isinstance(pred_label, str):
                continue
            count = _coerce_int(count_raw)
            if count is None or count < 0:
                continue
            clean_counts[pred_label] = count
            row_total += count
        for pred_label, count in clean_counts.items():
            if pred_label == gold_label or count <= 0:
                continue
            rows.append(
                {
                    "gold_label": gold_label,
                    "pred_label": pred_label,
                    "count": count,
                    "gold_row_total": row_total,
                    "gold_row_share": (count / row_total) if row_total else None,
                }
            )
    rows.sort(
        key=lambda row: (
            -int(row.get("count") or 0),
            -float(row.get("gold_row_share") or 0.0),
            str(row.get("gold_label") or ""),
            str(row.get("pred_label") or ""),
        )
    )
    return rows[:top_k]


def _compact_per_label(per_label_raw: Any) -> list[dict[str, Any]]:
    if not isinstance(per_label_raw, dict):
        return []
    rows: list[dict[str, Any]] = []
    for label, payload in per_label_raw.items():
        if not isinstance(label, str) or not isinstance(payload, dict):
            continue
        rows.append(
            {
                "label": label,
                "gold_total": _coerce_int(payload.get("gold_total")),
                "gold_matched": _coerce_int(payload.get("gold_matched")),
                "pred_total": _coerce_int(payload.get("pred_total")),
                "pred_matched": _coerce_int(payload.get("pred_matched")),
                "tp": _coerce_int(payload.get("tp")),
                "fp": _coerce_int(payload.get("fp")),
                "fn": _coerce_int(payload.get("fn")),
                "precision": _coerce_float(payload.get("precision")),
                "recall": _coerce_float(payload.get("recall")),
                "f1": _coerce_float(payload.get("f1")),
            }
        )
    rows.sort(key=lambda row: str(row.get("label") or ""))
    return rows


def _lowest_metric_labels(
    *,
    per_label: list[dict[str, Any]],
    metric_key: str,
    total_key: str,
    limit: int,
) -> list[dict[str, Any]]:
    eligible = [
        row
        for row in per_label
        if isinstance(row.get(total_key), int)
        and int(row.get(total_key) or 0) > 0
        and isinstance(row.get(metric_key), (int, float))
    ]
    eligible.sort(
        key=lambda row: (
            float(row.get(metric_key) or 0.0),
            -int(row.get(total_key) or 0),
            str(row.get("label") or ""),
        )
    )
    return eligible[:limit]


def _config_snapshot(run_manifest: dict[str, Any]) -> dict[str, Any]:
    run_config = run_manifest.get("run_config")
    if not isinstance(run_config, dict):
        run_config = {}
    snapshot: dict[str, Any] = {}
    for key in RUN_CONFIG_KEYS_OF_INTEREST:
        snapshot[key] = run_config.get(key)
    snapshot["prediction_run_config_hash"] = run_config.get("prediction_run_config_hash")
    return snapshot


def _source_file_name(path_raw: str | None) -> str | None:
    if not isinstance(path_raw, str) or not path_raw.strip():
        return None
    return Path(path_raw).name


def _source_key(source_hash: str | None, source_file: str | None) -> str:
    if source_hash:
        return source_hash
    if source_file:
        return source_file.lower()
    return "unknown_source"


def _run_output_dir_name(run_id: str, seen: dict[str, int]) -> str:
    base = run_id if run_id else "run"
    seen[base] += 1
    suffix = seen[base]
    if suffix == 1:
        return base
    return f"{base}__{suffix}"


def _build_run_cutdown(
    *,
    run_dir: Path,
    output_run_dir: Path,
    sample_limit: int,
    top_confusions_limit: int,
    top_labels_limit: int,
) -> RunRecord:
    run_manifest = _load_json(run_dir / "run_manifest.json")
    eval_report = _load_json(run_dir / "eval_report.json")

    run_id = str(run_manifest.get("run_id") or run_dir.name)
    source = run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
    source_path = source.get("path") if isinstance(source, dict) else None
    source_hash = source.get("source_hash") if isinstance(source, dict) else None
    source_file = _source_file_name(source_path if isinstance(source_path, str) else None)

    run_config = run_manifest.get("run_config")
    if not isinstance(run_config, dict):
        run_config = {}
    llm_recipe_pipeline = str(run_config.get("llm_recipe_pipeline") or "unknown")
    codex_enabled = llm_recipe_pipeline not in {"off", "none", ""}

    output_run_dir.mkdir(parents=True, exist_ok=True)

    eval_report_md_path = run_dir / "eval_report.md"
    if eval_report_md_path.is_file():
        shutil.copy2(eval_report_md_path, output_run_dir / "eval_report.md")

    sample_counts: dict[str, dict[str, int]] = {}
    sampled_rows_by_name: dict[str, list[dict[str, Any]]] = {}
    for source_name, output_name in SAMPLED_JSONL_INPUTS:
        source_path_jsonl = run_dir / source_name
        output_path_jsonl = output_run_dir / output_name
        counts = _write_jsonl_sample(
            source_path=source_path_jsonl,
            output_path=output_path_jsonl,
            sample_limit=sample_limit,
        )
        sample_counts[output_name] = counts
        sampled_rows_by_name[source_name] = _iter_jsonl(output_path_jsonl)

    wrong_rows_for_correct = _iter_jsonl(run_dir / "wrong_label_lines.jsonl")
    correct_rows, correct_metadata = _build_correct_label_sample(
        eval_report=eval_report,
        wrong_label_rows=wrong_rows_for_correct,
        sample_limit=sample_limit,
    )
    correct_path = output_run_dir / "correct_label_lines.sample.jsonl"
    _write_jsonl(correct_path, correct_rows)
    sample_counts["correct_label_lines.sample.jsonl"] = {
        "total_rows": int(correct_metadata.get("candidate_rows_total") or 0),
        "sample_rows": len(correct_rows),
    }

    codex_prompt_log = run_dir / "codexfarm_prompt_log.dedup.txt"
    if codex_prompt_log.is_file():
        shutil.copy2(codex_prompt_log, output_run_dir / codex_prompt_log.name)

    top_confusions = _top_confusions(
        eval_report.get("confusion"),
        top_k=top_confusions_limit,
    )
    compact_per_label = _compact_per_label(eval_report.get("per_label"))
    low_recall_labels = _lowest_metric_labels(
        per_label=compact_per_label,
        metric_key="recall",
        total_key="gold_total",
        limit=top_labels_limit,
    )
    low_precision_labels = _lowest_metric_labels(
        per_label=compact_per_label,
        metric_key="precision",
        total_key="pred_total",
        limit=top_labels_limit,
    )

    counts = eval_report.get("counts")
    if not isinstance(counts, dict):
        counts = {}
    alignment = eval_report.get("alignment")
    if not isinstance(alignment, dict):
        alignment = {}
    worst_label_recall = eval_report.get("worst_label_recall")
    if not isinstance(worst_label_recall, dict):
        worst_label_recall = {}

    summary = {
        "run_id": run_id,
        "source": {
            "source_file": source_file,
            "source_path": source_path,
            "source_hash": source_hash,
            "source_key": _source_key(
                source_hash if isinstance(source_hash, str) else None,
                source_file,
            ),
        },
        "run_config_snapshot": _config_snapshot(run_manifest),
        "eval_mode": eval_report.get("eval_mode"),
        "eval_type": eval_report.get("eval_type"),
        "key_metrics": {
            "overall_line_accuracy": _coerce_float(eval_report.get("overall_line_accuracy")),
            "overall_block_accuracy": _coerce_float(eval_report.get("overall_block_accuracy")),
            "macro_f1_excluding_other": _coerce_float(eval_report.get("macro_f1_excluding_other")),
            "practical_precision": _coerce_float(eval_report.get("practical_precision")),
            "practical_recall": _coerce_float(eval_report.get("practical_recall")),
            "practical_f1": _coerce_float(eval_report.get("practical_f1")),
        },
        "counts": {
            "gold_total": _coerce_int(counts.get("gold_total")),
            "gold_matched": _coerce_int(counts.get("gold_matched")),
            "gold_missed": _coerce_int(counts.get("gold_missed")),
            "pred_total": _coerce_int(counts.get("pred_total")),
            "pred_matched": _coerce_int(counts.get("pred_matched")),
            "pred_false_positive": _coerce_int(counts.get("pred_false_positive")),
        },
        "alignment_summary": {
            "alignment_strategy": alignment.get("alignment_strategy"),
            "alignment_primary_strategy": alignment.get("alignment_primary_strategy"),
            "canonical_char_coverage": _coerce_float(alignment.get("canonical_char_coverage")),
            "prediction_char_coverage": _coerce_float(alignment.get("prediction_char_coverage")),
            "prediction_block_match_ratio": _coerce_float(
                alignment.get("prediction_block_match_ratio")
            ),
            "nonempty_prediction_block_match_ratio": _coerce_float(
                alignment.get("nonempty_prediction_block_match_ratio")
            ),
        },
        "worst_label_recall": {
            "label": worst_label_recall.get("label"),
            "recall": _coerce_float(worst_label_recall.get("recall")),
            "gold_total": _coerce_int(worst_label_recall.get("gold_total")),
        },
        "top_confusions": top_confusions,
        "lowest_recall_labels": low_recall_labels,
        "lowest_precision_labels": low_precision_labels,
        "sample_counts": sample_counts,
        "correct_sample_metadata": correct_metadata,
        "included_files": sorted(
            path.name for path in output_run_dir.iterdir() if path.is_file()
        ),
    }

    summary_path = output_run_dir / "need_to_know_summary.json"
    _write_json(summary_path, summary)

    return RunRecord(
        run_id=run_id,
        source_key=_source_key(
            source_hash if isinstance(source_hash, str) else None,
            source_file,
        ),
        source_file=source_file,
        source_hash=source_hash if isinstance(source_hash, str) else None,
        llm_recipe_pipeline=llm_recipe_pipeline,
        codex_enabled=codex_enabled,
        metric_overall_line_accuracy=_coerce_float(eval_report.get("overall_line_accuracy")),
        metric_macro_f1_excluding_other=_coerce_float(
            eval_report.get("macro_f1_excluding_other")
        ),
        metric_practical_f1=_coerce_float(eval_report.get("practical_f1")),
        worst_label_recall={
            "label": worst_label_recall.get("label"),
            "recall": _coerce_float(worst_label_recall.get("recall")),
            "gold_total": _coerce_int(worst_label_recall.get("gold_total")),
        },
        run_timestamp=_parse_run_timestamp(run_id),
        output_subdir=output_run_dir.name,
        config_snapshot=_config_snapshot(run_manifest),
        top_confusions=top_confusions,
        summary_path=str(summary_path),
    )


def _delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return a - b


def _nearest_baseline(codex_run: RunRecord, baselines: list[RunRecord]) -> RunRecord:
    if len(baselines) == 1:
        return baselines[0]

    def score(candidate: RunRecord) -> tuple[float, float, str]:
        if codex_run.run_timestamp and candidate.run_timestamp:
            distance = abs((codex_run.run_timestamp - candidate.run_timestamp).total_seconds())
            preference = 0.0 if candidate.run_timestamp <= codex_run.run_timestamp else 1.0
            return (distance, preference, candidate.run_id)
        return (float("inf"), 0.0, candidate.run_id)

    return sorted(baselines, key=score)[0]


def _config_differences(a: dict[str, Any], b: dict[str, Any]) -> dict[str, dict[str, Any]]:
    keys = sorted(set(a.keys()) | set(b.keys()))
    diffs: dict[str, dict[str, Any]] = {}
    for key in keys:
        left = a.get(key)
        right = b.get(key)
        if left != right:
            diffs[key] = {"codex": left, "baseline": right}
    return diffs


def _build_comparison_summary(records: list[RunRecord]) -> dict[str, Any]:
    by_source: dict[str, list[RunRecord]] = defaultdict(list)
    for record in records:
        by_source[record.source_key].append(record)

    pairs: list[dict[str, Any]] = []
    unpaired_codex: list[dict[str, Any]] = []
    unpaired_baseline: list[dict[str, Any]] = []

    for source_key in sorted(by_source.keys()):
        runs = by_source[source_key]
        codex_runs = [run for run in runs if run.codex_enabled]
        baseline_runs = [run for run in runs if not run.codex_enabled]

        if codex_runs and baseline_runs:
            for codex_run in sorted(
                codex_runs,
                key=lambda run: (run.run_timestamp or datetime.min, run.run_id),
                reverse=True,
            ):
                baseline = _nearest_baseline(codex_run, baseline_runs)
                pairs.append(
                    {
                        "source_key": source_key,
                        "source_file": codex_run.source_file or baseline.source_file,
                        "codex_run": {
                            "run_id": codex_run.run_id,
                            "output_subdir": codex_run.output_subdir,
                            "llm_recipe_pipeline": codex_run.llm_recipe_pipeline,
                            "overall_line_accuracy": codex_run.metric_overall_line_accuracy,
                            "macro_f1_excluding_other": codex_run.metric_macro_f1_excluding_other,
                            "practical_f1": codex_run.metric_practical_f1,
                            "worst_label_recall": codex_run.worst_label_recall,
                        },
                        "baseline_run": {
                            "run_id": baseline.run_id,
                            "output_subdir": baseline.output_subdir,
                            "llm_recipe_pipeline": baseline.llm_recipe_pipeline,
                            "overall_line_accuracy": baseline.metric_overall_line_accuracy,
                            "macro_f1_excluding_other": baseline.metric_macro_f1_excluding_other,
                            "practical_f1": baseline.metric_practical_f1,
                            "worst_label_recall": baseline.worst_label_recall,
                        },
                        "delta_codex_minus_baseline": {
                            "overall_line_accuracy": _delta(
                                codex_run.metric_overall_line_accuracy,
                                baseline.metric_overall_line_accuracy,
                            ),
                            "macro_f1_excluding_other": _delta(
                                codex_run.metric_macro_f1_excluding_other,
                                baseline.metric_macro_f1_excluding_other,
                            ),
                            "practical_f1": _delta(
                                codex_run.metric_practical_f1,
                                baseline.metric_practical_f1,
                            ),
                        },
                        "run_config_differences": _config_differences(
                            codex_run.config_snapshot,
                            baseline.config_snapshot,
                        ),
                    }
                )
            continue

        if codex_runs:
            for codex_run in codex_runs:
                unpaired_codex.append(
                    {
                        "source_key": source_key,
                        "source_file": codex_run.source_file,
                        "run_id": codex_run.run_id,
                        "output_subdir": codex_run.output_subdir,
                        "llm_recipe_pipeline": codex_run.llm_recipe_pipeline,
                    }
                )
        if baseline_runs:
            for baseline in baseline_runs:
                unpaired_baseline.append(
                    {
                        "source_key": source_key,
                        "source_file": baseline.source_file,
                        "run_id": baseline.run_id,
                        "output_subdir": baseline.output_subdir,
                        "llm_recipe_pipeline": baseline.llm_recipe_pipeline,
                    }
                )

    return {
        "pairing_rule": (
            "Within each source_key group, each codex-enabled run is paired with the "
            "nearest baseline (llm_recipe_pipeline=off/none/empty) by timestamp."
        ),
        "pairs": pairs,
        "unpaired_codex_runs": unpaired_codex,
        "unpaired_baseline_runs": unpaired_baseline,
    }


def _write_readme(
    *,
    output_dir: Path,
    input_dir: Path,
    records: list[RunRecord],
    sample_limit: int,
    flattened: bool,
) -> None:
    lines: list[str] = []
    lines.append("# Benchmark Need-To-Know Package")
    lines.append("")
    lines.append(f"Generated: {_timestamp_now()}")
    lines.append(f"Source folder: `{input_dir}`")
    lines.append(f"Run count: {len(records)}")
    lines.append(f"Sample limit per JSONL artifact: {sample_limit}")
    lines.append("")
    lines.append("Each run folder includes:")
    lines.append("- `need_to_know_summary.json`")
    lines.append("- `eval_report.md` (if present in source run)")
    lines.append("- `correct_label_lines.sample.jsonl`")
    lines.append("- `wrong_label_lines.sample.jsonl`")
    lines.append("- `missed_gold_lines.sample.jsonl`")
    lines.append("- `unmatched_pred_blocks.sample.jsonl`")
    lines.append("- `codexfarm_prompt_log.dedup.txt` (if present)")
    lines.append("")
    lines.append("Root files:")
    lines.append("- `run_index.json`")
    lines.append("- `comparison_summary.json`")
    lines.append("- `process_manifest.json`")
    if flattened:
        lines.append("")
        lines.append(
            "Flattened markdown output is written to sibling folder "
            f"`{output_dir.name}_md`."
        )
    lines.append("")
    lines.append("Run index:")
    for record in sorted(records, key=lambda row: row.run_id):
        lines.append(
            "- "
            f"`{record.output_subdir}` | source={record.source_file or 'unknown'} "
            f"| pipeline={record.llm_recipe_pipeline} "
            f"| overall_line_accuracy={record.metric_overall_line_accuracy}"
        )
    lines.append("")

    readme_path = output_dir / "README.md"
    readme_path.write_text("\n".join(lines), encoding="utf-8")


def _flatten_output(
    *,
    repo_root: Path,
    output_dir: Path,
    flatten_script: Path,
) -> Path:
    script_path = (repo_root / flatten_script).resolve() if not flatten_script.is_absolute() else flatten_script
    if not script_path.is_file():
        raise FileNotFoundError(f"Flatten script not found: {script_path}")

    subprocess.run(
        ["bash", str(script_path), str(output_dir)],
        cwd=repo_root,
        check=True,
    )

    md_output_dir = output_dir.parent / f"{output_dir.name}_md"
    md_output_dir.mkdir(parents=True, exist_ok=True)
    for file_name in ROOT_METADATA_FILES:
        source = output_dir / file_name
        if source.is_file():
            shutil.copy2(source, md_output_dir / file_name)
    return md_output_dir


def main() -> int:
    args = _parse_args()
    input_dir = args.input_dir.resolve()
    if not input_dir.is_dir():
        print(f"error: input directory does not exist: {input_dir}", file=sys.stderr)
        return 1
    if args.sample_limit <= 0:
        print("error: --sample-limit must be > 0", file=sys.stderr)
        return 1

    run_dirs = _discover_run_dirs(input_dir)
    if not run_dirs:
        print(
            "error: no benchmark run directories found (need both eval_report.json "
            "and run_manifest.json).",
            file=sys.stderr,
        )
        return 1

    if args.output_dir is None:
        output_dir = _default_output_dir_from_runs(input_dir, run_dirs)
    else:
        output_dir = args.output_dir.resolve()

    if output_dir.exists():
        if not args.overwrite:
            print(
                f"error: output directory already exists: {output_dir}\n"
                "       pass --overwrite to replace it.",
                file=sys.stderr,
            )
            return 1
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    seen_output_names: dict[str, int] = defaultdict(int)
    records: list[RunRecord] = []
    for run_dir in run_dirs:
        run_manifest = _load_json(run_dir / "run_manifest.json")
        run_id = str(run_manifest.get("run_id") or run_dir.name)
        output_subdir_name = _run_output_dir_name(run_id, seen_output_names)
        output_run_dir = output_dir / output_subdir_name
        record = _build_run_cutdown(
            run_dir=run_dir,
            output_run_dir=output_run_dir,
            sample_limit=args.sample_limit,
            top_confusions_limit=args.top_confusions,
            top_labels_limit=args.top_labels,
        )
        records.append(record)

    run_index = {
        "generated_at": _timestamp_now(),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "run_count": len(records),
        "runs": [
            {
                "run_id": record.run_id,
                "output_subdir": record.output_subdir,
                "source_key": record.source_key,
                "source_file": record.source_file,
                "source_hash": record.source_hash,
                "llm_recipe_pipeline": record.llm_recipe_pipeline,
                "codex_enabled": record.codex_enabled,
                "overall_line_accuracy": record.metric_overall_line_accuracy,
                "macro_f1_excluding_other": record.metric_macro_f1_excluding_other,
                "practical_f1": record.metric_practical_f1,
                "summary_path": record.summary_path,
            }
            for record in sorted(records, key=lambda row: row.run_id)
        ],
    }
    _write_json(output_dir / "run_index.json", run_index)

    comparison_summary = _build_comparison_summary(records)
    comparison_summary["generated_at"] = _timestamp_now()
    comparison_summary["input_dir"] = str(input_dir)
    comparison_summary["output_dir"] = str(output_dir)
    _write_json(output_dir / "comparison_summary.json", comparison_summary)

    process_manifest = {
        "generated_at": _timestamp_now(),
        "tool": "scripts/benchmark_cutdown_for_external_ai.py",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "sample_limit": args.sample_limit,
        "top_confusions": args.top_confusions,
        "top_labels": args.top_labels,
        "flatten_enabled": not args.no_flatten,
        "flatten_script": str(args.flatten_script),
    }
    _write_json(output_dir / "process_manifest.json", process_manifest)

    _write_readme(
        output_dir=output_dir,
        input_dir=input_dir,
        records=records,
        sample_limit=args.sample_limit,
        flattened=not args.no_flatten,
    )

    md_output_dir: Path | None = None
    if not args.no_flatten:
        repo_root = Path(__file__).resolve().parents[1]
        md_output_dir = _flatten_output(
            repo_root=repo_root,
            output_dir=output_dir,
            flatten_script=args.flatten_script,
        )

    print(f"Built cutdown package: {output_dir}")
    if md_output_dir is not None:
        print(f"Built flattened package: {md_output_dir}")
    print(f"Runs processed: {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
