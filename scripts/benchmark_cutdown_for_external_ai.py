#!/usr/bin/env python3
"""Build a compact benchmark package for external AI review.

Run with:
    python3 scripts/benchmark_cutdown_for_external_ai.py <input_dir> [--output-dir <dir>]

This script creates a deterministic, low-token benchmark package that preserves
the signals needed to answer:
1) how well the run performed, and
2) why the run performed that way.

It discovers benchmark run directories under an input root by looking for
folders that contain both `eval_report.json` and `run_manifest.json`.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import re
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SAMPLE_LIMIT = 80
DEFAULT_TOP_CONFUSIONS = 8
DEFAULT_TOP_LABELS = 6
DEFAULT_EXCERPT_LIMIT = 440
DEFAULT_PROMPT_EXCERPT_LIMIT = 2000
DEFAULT_PROMPT_PAIRS_PER_CATEGORY = 3
DEFAULT_TARGETED_PROMPT_CASES = 10
ALIGNMENT_HEALTHY_COVERAGE_MIN = 0.98
ALIGNMENT_HEALTHY_MATCH_RATIO_MIN = 0.98

# Keep this focused on settings that are likely to explain quality deltas.
RUN_CONFIG_KEYS_OF_INTEREST = (
    "llm_recipe_pipeline",
    "atomic_block_splitter",
    "line_role_pipeline",
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
PROJECT_CONTEXT_REL_PATH = Path("docs/AI_Context.md")
PROJECT_CONTEXT_FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
PROJECT_CONTEXT_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
PROJECT_CONTEXT_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")

ROOT_METADATA_FILES = (
    "README.md",
    "run_index.json",
    "comparison_summary.json",
    "process_manifest.json",
    "changed_lines.codex_vs_vanilla.jsonl",
    "per_recipe_or_per_span_breakdown.json",
    "targeted_prompt_cases.md",
    "label_policy_adjudication_notes.md",
)
AGGREGATED_ROOT_SUMMARY_MD = "benchmark_summary.md"
PROMPT_LOG_FILE_NAME = "codexfarm_prompt_log.dedup.txt"
FULL_PROMPT_LOG_FILE_NAME = "full_prompt_log.jsonl"
PROMPT_WARNING_AGGREGATE_FILE_NAME = "prompt_warning_aggregate.json"
PROJECTION_TRACE_FILE_NAME = "projection_trace.codex_to_benchmark.json"
CHANGED_LINES_FILE_NAME = "changed_lines.codex_vs_vanilla.jsonl"
PER_RECIPE_BREAKDOWN_FILE_NAME = "per_recipe_or_per_span_breakdown.json"
TARGETED_PROMPT_CASES_FILE_NAME = "targeted_prompt_cases.md"
LABEL_POLICY_NOTES_FILE_NAME = "label_policy_adjudication_notes.md"
WRONG_LABEL_FULL_CONTEXT_FILE_NAME = "wrong_label_lines.with_context.full.jsonl.gz"
PREPROCESS_TRACE_FAILURES_FILE_NAME = "preprocess_trace_failures.jsonl.gz"
PROMPT_REQUEST_RESPONSE_LOG_NAME = "prompt_request_response_log.txt"
PROMPT_LOG_MANIFEST_ARTIFACT_KEY = "codexfarm_prompt_request_response_txt"
FULL_PROMPT_LOG_MANIFEST_ARTIFACT_KEYS = (
    "full_prompt_log_path",
    "codexfarm_full_prompt_log_jsonl",
)
PROMPT_LOG_SEPARATOR = "--------------------------------------------------------------------------------"
PROMPT_SECTION_HEADER_RE = re.compile(
    r"^---\s+([0-9A-Za-z_-]+)\s+(INPUT|RESPONSE)\s+FILES\s+---$"
)
PROMPT_ENTRY_RE = re.compile(r"^(INPUT|OUTPUT)\s+([0-9A-Za-z_-]+)\s*=>\s*(.+)$")
PROMPT_CATEGORY_SORT_RE = re.compile(r"^([a-z]+)(\d+)(.*)$")
PASS_DIR_MAP = {
    "pass1": "pass1_chunking",
    "pass2": "pass2_schemaorg",
    "pass3": "pass3_final",
}
PASS_PIPELINE_MAP = {
    "pass1": "recipe.chunking.v1",
    "pass2": "recipe.schemaorg.v1",
    "pass3": "recipe.final.v1",
}

LINE_LEVEL_SAMPLED_JSONL_INPUTS = (
    ("wrong_label_lines.jsonl", "wrong_label_lines.sample.jsonl"),
    ("missed_gold_lines.jsonl", "missed_gold_lines.sample.jsonl"),
)

UNMATCHED_PRED_BLOCKS_INPUT = "unmatched_pred_blocks.jsonl"

ALIGNMENT_SAMPLED_JSONL_INPUTS = (
    ("unmatched_pred_blocks.jsonl", "unmatched_pred_blocks.sample.jsonl"),
    ("aligned_prediction_blocks.jsonl", "aligned_prediction_blocks.sample.jsonl"),
    ("alignment_gaps.jsonl", "alignment_gaps.sample.jsonl"),
)


@dataclass
class RunRecord:
    run_id: str
    source_key: str
    source_file: str | None
    source_hash: str | None
    llm_recipe_pipeline: str
    atomic_block_splitter: str
    line_role_pipeline: str
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
    run_dir: str
    full_prompt_log_status: str
    full_prompt_log_rows: int
    full_prompt_log_path: str | None


@dataclass
class LinePredictionView:
    line_text_by_index: dict[int, str]
    gold_label_by_index: dict[int, str]
    pred_label_by_index: dict[int, str]
    recipe_id_by_index: dict[int, str | None]
    recipe_span_by_index: dict[int, str]
    recipe_spans: list[dict[str, Any]]


@dataclass
class PairDiagnostics:
    changed_line_rows: list[dict[str, Any]]
    pair_breakdown: dict[str, Any]
    confusion_matrix_codex: dict[str, dict[str, int]]
    confusion_matrix_baseline: dict[str, dict[str, int]]
    confusion_delta_codex_minus_baseline: dict[str, dict[str, int]]
    targeted_prompt_case_rows: list[dict[str, Any]]


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
        "--excerpt-limit",
        type=int,
        default=DEFAULT_EXCERPT_LIMIT,
        help=f"Max chars kept in sampled text fields (default: {DEFAULT_EXCERPT_LIMIT}).",
    )
    parser.add_argument(
        "--prompt-excerpt-limit",
        type=int,
        default=DEFAULT_PROMPT_EXCERPT_LIMIT,
        help=(
            "Max chars kept per string when dumping sampled prompt request/response payloads "
            f"(default: {DEFAULT_PROMPT_EXCERPT_LIMIT})."
        ),
    )
    parser.add_argument(
        "--prompt-pairs-per-category",
        type=int,
        default=DEFAULT_PROMPT_PAIRS_PER_CATEGORY,
        help=(
            "Max full input/output pairs to keep per prompt category from the prompt log "
            f"(default: {DEFAULT_PROMPT_PAIRS_PER_CATEGORY}). Set to 0 to keep the full log."
        ),
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
        "--keep-cutdown",
        action="store_true",
        help=(
            "Keep the intermediate non-flattened <output_dir> folder. "
            "By default, the intermediate folder is removed."
        ),
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


def _excerpt(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3] + "..."


def _clip_strings_deep(value: Any, *, excerpt_limit: int, max_depth: int = 8) -> Any:
    if max_depth <= 0:
        return "<clipped: max depth>"
    if isinstance(value, str):
        return _excerpt(value, max_len=excerpt_limit)
    if isinstance(value, list):
        return [
            _clip_strings_deep(item, excerpt_limit=excerpt_limit, max_depth=max_depth - 1)
            for item in value
        ]
    if isinstance(value, dict):
        clipped: dict[str, Any] = {}
        for key, item in value.items():
            clipped[str(key)] = _clip_strings_deep(
                item,
                excerpt_limit=excerpt_limit,
                max_depth=max_depth - 1,
            )
        return clipped
    return value


def _clip_large_text_fields(row: dict[str, Any], *, excerpt_limit: int) -> dict[str, Any]:
    clipped = dict(row)
    for key in ("line_text_excerpt", "block_text_excerpt", "selected_text", "text"):
        value = clipped.get(key)
        if isinstance(value, str):
            clipped[key] = _excerpt(value, max_len=excerpt_limit)
    return clipped


def _sample_rows_evenly(rows: list[dict[str, Any]], sample_limit: int) -> list[dict[str, Any]]:
    selected_indices = _sample_indices_evenly(len(rows), sample_limit)
    return [rows[index] for index in selected_indices]


def _sample_indices_evenly(total_count: int, sample_limit: int) -> list[int]:
    if total_count <= 0 or sample_limit <= 0:
        return []
    if sample_limit >= total_count:
        return list(range(total_count))
    if sample_limit == 1:
        return [0]

    last_index = total_count - 1
    selected_indices = {
        int(round(position * last_index / (sample_limit - 1))) for position in range(sample_limit)
    }
    if len(selected_indices) < sample_limit:
        extras = [index for index in range(total_count) if index not in selected_indices][
            : sample_limit - len(selected_indices)
        ]
        selected_indices.update(extras)
    return sorted(selected_indices)[:sample_limit]


def _write_jsonl_sample(
    *,
    source_path: Path,
    output_path: Path,
    sample_limit: int,
    excerpt_limit: int,
) -> dict[str, int]:
    rows = _iter_jsonl(source_path)
    sampled_raw = _sample_rows_evenly(rows, sample_limit)
    sampled = [_clip_large_text_fields(row, excerpt_limit=excerpt_limit) for row in sampled_raw]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in sampled:
            handle.write(json.dumps(row))
            handle.write("\n")
    return {"total_rows": len(rows), "sample_rows": len(sampled)}


def _parse_prompt_log_sections(source_path: Path) -> dict[str, dict[str, list[dict[str, str]]]]:
    sections: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(
        lambda: {"input": [], "output": []}
    )

    current_category: str | None = None
    current_kind: str | None = None
    current_filename: str | None = None
    current_lines: list[str] = []
    current_body_started = False
    collecting = False

    def flush_current_entry() -> None:
        nonlocal collecting, current_category, current_kind, current_filename, current_lines
        nonlocal current_body_started
        if not collecting or current_category is None or current_kind is None:
            return
        if current_filename is None:
            return
        text = "\n".join(current_lines).rstrip()
        if text:
            sections[current_category][current_kind].append(
                {"filename": current_filename, "text": text}
            )
        collecting = False
        current_filename = None
        current_lines = []
        current_kind = None
        current_body_started = False

    for raw_line in source_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()

        section_match = PROMPT_SECTION_HEADER_RE.match(stripped)
        if section_match:
            flush_current_entry()
            current_category = section_match.group(1).lower()
            continue

        entry_match = PROMPT_ENTRY_RE.match(stripped)
        if entry_match:
            flush_current_entry()
            current_category = entry_match.group(2).lower()
            current_kind = "input" if entry_match.group(1).upper() == "INPUT" else "output"
            current_filename = entry_match.group(3).strip()
            current_lines = [raw_line]
            current_body_started = False
            collecting = True
            continue

        if collecting and stripped == PROMPT_LOG_SEPARATOR:
            current_lines.append(raw_line)
            if current_body_started:
                flush_current_entry()
            else:
                current_body_started = True
            continue

        if collecting and current_category is not None:
            current_lines.append(raw_line)

    flush_current_entry()
    return {
        category: payload
        for category, payload in sections.items()
        if payload["input"] or payload["output"]
    }


def _prompt_category_sort_key(category: str) -> tuple[int, str, int, str]:
    lower = category.lower()
    match = PROMPT_CATEGORY_SORT_RE.match(lower)
    if match:
        return (0, match.group(1), int(match.group(2)), match.group(3))
    return (1, lower, 0, "")


def _write_prompt_log_samples(
    *,
    source_path: Path,
    output_path: Path,
    max_pairs_per_category: int,
) -> dict[str, Any]:
    parsed = _parse_prompt_log_sections(source_path)
    if not parsed:
        output_path.write_text(
            (
                "No parseable prompt input/response sections were found in this log.\n"
            ),
            encoding="utf-8",
        )
        return {
            "status": "no_sections",
            "max_pairs_per_category": max_pairs_per_category,
            "categories": [],
            "sampled_pairs": 0,
        }

    lines: list[str] = [
        "# CodexFarm prompt input/output examples (sampled)",
        "",
        (
            "This file keeps a deterministic sample of whole prompt-input/output file "
            f"blocks from the full prompt log, at most {max_pairs_per_category} pairs "
            "per category."
        ),
        "",
        f"Source log: {source_path}",
        "",
    ]

    category_metadata: dict[str, dict[str, int]] = {}
    sampled_pairs = 0
    for category in sorted(parsed.keys(), key=_prompt_category_sort_key):
        input_blocks = parsed[category]["input"]
        output_blocks = parsed[category]["output"]
        pairable_count = min(len(input_blocks), len(output_blocks))
        sampled_pair_indices = _sample_indices_evenly(pairable_count, max_pairs_per_category)
        pair_count = len(sampled_pair_indices)

        category_metadata[category] = {
            "input_blocks": len(input_blocks),
            "output_blocks": len(output_blocks),
            "pairable_blocks": pairable_count,
            "sampled_pairs": pair_count,
            "sampled_pair_indices": sampled_pair_indices,
        }
        lines.append(
            (
                f"--- {category.upper()} INPUT/OUTPUT PAIRS (showing {pair_count} of "
                f"{pairable_count}) ---"
            )
        )
        if pair_count == 0:
            lines.append("No full input/output pair available for this category in this log.")
            lines.append("")
            continue

        for pair_no, pair_index in enumerate(sampled_pair_indices, start=1):
            input_block = input_blocks[pair_index]
            output_block = output_blocks[pair_index]
            lines.extend(
                [
                    (
                        f"[{category}] Pair {pair_no} (source index {pair_index + 1}) "
                        f"- INPUT file: {input_block['filename']}"
                    ),
                    input_block["text"],
                    PROMPT_LOG_SEPARATOR,
                    (
                        f"[{category}] Pair {pair_no} (source index {pair_index + 1}) "
                        f"- OUTPUT file: {output_block['filename']}"
                    ),
                    output_block["text"],
                    PROMPT_LOG_SEPARATOR,
                    "",
                ]
            )
            sampled_pairs += 1

    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "status": "sampled",
        "source_path": str(source_path),
        "max_pairs_per_category": max_pairs_per_category,
        "categories": sorted(parsed.keys(), key=_prompt_category_sort_key),
        "sampled_pairs": sampled_pairs,
        "category_metadata": category_metadata,
    }


def _write_prompt_log_samples_from_full_prompt_log(
    *,
    source_path: Path,
    output_path: Path,
    max_pairs_per_category: int,
    excerpt_limit: int,
) -> dict[str, Any]:
    rows = _iter_jsonl(source_path)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        pass_name = str(row.get("pass") or "").strip().lower()
        if not pass_name:
            pass_name = "unknown"
        grouped[pass_name].append(row)

    if not grouped:
        output_path.write_text(
            "No parseable rows were found in full_prompt_log.jsonl.\n",
            encoding="utf-8",
        )
        return {
            "status": "no_rows",
            "source_path": str(source_path),
            "max_pairs_per_category": max_pairs_per_category,
            "categories": [],
            "sampled_pairs": 0,
        }

    for pass_name in grouped:
        grouped[pass_name].sort(
            key=lambda row: (
                str(row.get("call_id") or ""),
                str(row.get("timestamp_utc") or ""),
            )
        )

    lines: list[str] = [
        "# CodexFarm prompt input/output examples (from full_prompt_log.jsonl)",
        "",
        (
            "This convenience file is derived from full_prompt_log.jsonl and keeps "
            "request/response payload content for sampled calls (with long strings clipped)."
            if max_pairs_per_category > 0
            else (
                "This convenience file is derived from full_prompt_log.jsonl and keeps all calls "
                "(with long strings clipped)."
            )
        ),
        "",
        f"Source log: {source_path}",
        f"String clip limit: {excerpt_limit} chars",
        "",
    ]

    category_metadata: dict[str, dict[str, Any]] = {}
    sampled_pairs = 0
    for category in sorted(grouped.keys(), key=_prompt_category_sort_key):
        category_rows = grouped[category]
        if max_pairs_per_category <= 0:
            sampled_indices = list(range(len(category_rows)))
        else:
            sampled_indices = _sample_indices_evenly(
                len(category_rows),
                max_pairs_per_category,
            )
        pair_count = len(sampled_indices)
        category_metadata[category] = {
            "total_calls": len(category_rows),
            "sampled_calls": pair_count,
            "sampled_call_indices": sampled_indices,
        }

        lines.append(
            f"--- {category.upper()} CALLS (showing {pair_count} of {len(category_rows)}) ---"
        )
        if pair_count == 0:
            lines.append("No calls available for this pass category.")
            lines.append("")
            continue

        for sample_no, source_index in enumerate(sampled_indices, start=1):
            row = category_rows[source_index]
            call_id = str(row.get("call_id") or "").strip()
            recipe_id = str(row.get("recipe_id") or "").strip()
            timestamp_utc = str(row.get("timestamp_utc") or "").strip()
            source_file = str(row.get("source_file") or "").strip()
            lines.extend(
                [
                    (
                        f"[{category}] Sample {sample_no} (source index {source_index + 1})"
                        f" call_id={call_id} recipe_id={recipe_id} timestamp_utc={timestamp_utc}"
                    ),
                    f"source_file={source_file}",
                    "",
                    "REQUEST_MESSAGES:",
                    json.dumps(
                        _clip_strings_deep(
                            row.get("request_messages"),
                            excerpt_limit=excerpt_limit,
                        ),
                        indent=2,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "",
                    "RAW_RESPONSE:",
                    json.dumps(
                        _clip_strings_deep(
                            row.get("raw_response"),
                            excerpt_limit=excerpt_limit,
                        ),
                        indent=2,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "",
                    "PARSED_RESPONSE:",
                    json.dumps(
                        _clip_strings_deep(
                            row.get("parsed_response"),
                            excerpt_limit=excerpt_limit,
                        ),
                        indent=2,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    PROMPT_LOG_SEPARATOR,
                    "",
                ]
            )
            sampled_pairs += 1

    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "status": "sampled_from_full_prompt_log",
        "source_path": str(source_path),
        "max_pairs_per_category": max_pairs_per_category,
        "excerpt_limit": excerpt_limit,
        "categories": sorted(grouped.keys(), key=_prompt_category_sort_key),
        "sampled_pairs": sampled_pairs,
        "category_metadata": category_metadata,
    }


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
    excerpt_limit: int,
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
            "line_text_excerpt": _excerpt(str(line.get("text") or ""), max_len=excerpt_limit),
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


def _jsonl_row_count(path: Path) -> int:
    if not path.is_file():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            if raw_line.strip():
                count += 1
    return count


def _write_jsonl_gzip_deterministic(path: Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("wb") as raw_handle:
        with gzip.GzipFile(fileobj=raw_handle, mode="wb", mtime=0) as gzip_handle:
            for row in rows:
                payload = json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                gzip_handle.write(payload)
                gzip_handle.write(b"\n")
                written += 1
    return written


def _load_extracted_archive_blocks(path: Path) -> dict[int, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}

    rows: list[dict[str, Any]]
    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
    elif isinstance(payload, dict):
        blocks = payload.get("blocks")
        rows = [row for row in blocks if isinstance(row, dict)] if isinstance(blocks, list) else []
    else:
        rows = []

    indexed: dict[int, dict[str, Any]] = {}
    for fallback_index, row in enumerate(rows):
        index = _coerce_int(row.get("index"))
        if index is None:
            index = _coerce_int(row.get("block_index"))
        location = row.get("location")
        if index is None and isinstance(location, dict):
            index = _coerce_int(location.get("block_index"))
        if index is None:
            index = fallback_index
        features = location.get("features") if isinstance(location, dict) else None
        indexed[int(index)] = {
            "text": str(row.get("text") or ""),
            "features": dict(features) if isinstance(features, dict) else {},
        }
    return indexed


def _prompt_row_sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
    pass_name = str(row.get("pass") or "").strip().lower()
    if pass_name == "pass3":
        pass_rank = 0
    elif pass_name == "pass2":
        pass_rank = 1
    elif pass_name == "pass1":
        pass_rank = 2
    else:
        pass_rank = 3

    parsed_response = _parse_json_like(row.get("parsed_response"))
    parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
    warning_count = len(_coerce_str_list(parsed_response.get("warnings")))
    call_id = str(row.get("call_id") or "")
    return (pass_rank, -warning_count, call_id)


def _select_prompt_rows_by_recipe(
    full_prompt_rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    if not full_prompt_rows:
        return {}, None
    sorted_rows = sorted(full_prompt_rows, key=_prompt_row_sort_key)
    by_recipe: dict[str, dict[str, Any]] = {}
    fallback: dict[str, Any] | None = sorted_rows[0]
    for row in sorted_rows:
        recipe_id = str(row.get("recipe_id") or "").strip()
        if not recipe_id:
            continue
        if recipe_id not in by_recipe:
            by_recipe[recipe_id] = row
    return by_recipe, fallback


def _build_wrong_label_full_context_rows(
    *,
    run_dir: Path,
    recipe_spans: list[dict[str, Any]],
    excerpt_limit: int,
) -> list[dict[str, Any]]:
    wrong_rows = _iter_jsonl(run_dir / "wrong_label_lines.jsonl")
    if not wrong_rows:
        return []

    run_manifest_path = run_dir / "run_manifest.json"
    run_manifest = _load_json(run_manifest_path) if run_manifest_path.is_file() else {}
    run_id = str(run_manifest.get("run_id") or run_dir.name)
    source = run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
    source_path = source.get("path") if isinstance(source, dict) else None
    source_hash = source.get("source_hash") if isinstance(source, dict) else None
    source_file = _source_file_name(source_path if isinstance(source_path, str) else None)
    source_key = _source_key(
        source_hash if isinstance(source_hash, str) else None,
        source_file,
    )

    line_view = _build_line_prediction_view(run_dir=run_dir, recipe_spans=recipe_spans)

    rows: list[dict[str, Any]] = []
    for wrong_row in wrong_rows:
        line_index = _coerce_int(wrong_row.get("line_index"))
        if line_index is None:
            continue
        recipe_id = line_view.recipe_id_by_index.get(line_index)
        span_region = line_view.recipe_span_by_index.get(line_index, "outside_active_recipe_span")
        gold_label = str(
            wrong_row.get("gold_label")
            or line_view.gold_label_by_index.get(line_index)
            or "OTHER"
        )
        pred_label = str(
            wrong_row.get("pred_label")
            or line_view.pred_label_by_index.get(line_index)
            or "OTHER"
        )
        rows.append(
            {
                "run_id": run_id,
                "line_index": line_index,
                "recipe_id": recipe_id,
                "span_region": span_region,
                "gold_label": gold_label,
                "pred_label": pred_label,
                "source_file": source_file,
                "source_hash": source_hash if isinstance(source_hash, str) else None,
                "source_key": source_key,
                **_line_context(
                    line_text_by_index=line_view.line_text_by_index,
                    line_index=line_index,
                    excerpt_limit=excerpt_limit,
                ),
            }
        )
    rows.sort(key=lambda row: int(row.get("line_index") or 0))
    return rows


def _build_preprocess_trace_failure_rows(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    full_prompt_rows: list[dict[str, Any]],
    excerpt_limit: int,
) -> tuple[list[dict[str, Any]], str]:
    wrong_rows = _iter_jsonl(run_dir / "wrong_label_lines.jsonl")
    if not wrong_rows:
        return [], "not_applicable"

    pred_run_dir = _resolve_prediction_run_dir(run_dir, run_manifest)
    if pred_run_dir is None:
        return [], "missing_prediction_run"

    extracted_archive_path = pred_run_dir / "extracted_archive.json"
    if not extracted_archive_path.is_file():
        return [], "missing_extracted_archive"

    if not full_prompt_rows:
        return [], "missing_full_prompt_log"

    archive_blocks = _load_extracted_archive_blocks(extracted_archive_path)
    prompt_rows_by_recipe, fallback_prompt_row = _select_prompt_rows_by_recipe(full_prompt_rows)
    recipe_spans = _build_recipe_spans_from_full_prompt_rows(full_prompt_rows)
    line_view = _build_line_prediction_view(run_dir=run_dir, recipe_spans=recipe_spans)

    run_id = str(run_manifest.get("run_id") or run_dir.name)
    source = run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
    source_path = source.get("path") if isinstance(source, dict) else None
    source_hash = source.get("source_hash") if isinstance(source, dict) else None
    source_file = _source_file_name(source_path if isinstance(source_path, str) else None)
    source_key = _source_key(
        source_hash if isinstance(source_hash, str) else None,
        source_file,
    )

    rows: list[dict[str, Any]] = []
    for wrong_row in wrong_rows:
        line_index = _coerce_int(wrong_row.get("line_index"))
        if line_index is None:
            continue

        recipe_id = line_view.recipe_id_by_index.get(line_index)
        recipe_key = str(recipe_id or "").strip()
        prompt_row = prompt_rows_by_recipe.get(recipe_key) or fallback_prompt_row
        pass_name = str(prompt_row.get("pass") or "").strip().lower() if prompt_row else None
        call_id = str(prompt_row.get("call_id") or "").strip() if prompt_row else None

        parsed_response = (
            _parse_json_like(prompt_row.get("parsed_response")) if isinstance(prompt_row, dict) else {}
        )
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
        warnings = _coerce_str_list(parsed_response.get("warnings"))
        warning_buckets = sorted(
            {
                _prompt_warning_bucket(_normalize_whitespace(warning))
                for warning in warnings
                if warning.strip()
            }
        )
        prompt_candidate_block_excerpt = (
            _first_prompt_block_excerpt(prompt_row, excerpt_limit=excerpt_limit)
            if isinstance(prompt_row, dict)
            else ""
        )

        archive_row = archive_blocks.get(line_index, {})
        raw_block_text = str(archive_row.get("text") or "")
        raw_block_excerpt = (
            _excerpt(_normalize_whitespace(raw_block_text), max_len=excerpt_limit)
            if raw_block_text
            else ""
        )
        features = archive_row.get("features")
        features = features if isinstance(features, dict) else {}
        if raw_block_excerpt and prompt_candidate_block_excerpt:
            trace_status = "joined_with_prompt_and_archive"
        elif raw_block_excerpt:
            trace_status = "joined_with_archive_only"
        elif prompt_candidate_block_excerpt:
            trace_status = "joined_with_prompt_only"
        else:
            trace_status = "missing_prompt_and_archive_context"

        rows.append(
            {
                "run_id": run_id,
                "line_index": line_index,
                "recipe_id": recipe_id,
                "span_region": line_view.recipe_span_by_index.get(
                    line_index,
                    "outside_active_recipe_span",
                ),
                "gold_label": str(
                    wrong_row.get("gold_label")
                    or line_view.gold_label_by_index.get(line_index)
                    or "OTHER"
                ),
                "pred_label": str(
                    wrong_row.get("pred_label")
                    or line_view.pred_label_by_index.get(line_index)
                    or "OTHER"
                ),
                "raw_block_excerpt": raw_block_excerpt,
                "raw_block_unstructured_preprocess_mode": features.get(
                    "unstructured_preprocess_mode"
                ),
                "raw_block_stable_key": features.get("unstructured_stable_key"),
                "prompt_candidate_block_excerpt": prompt_candidate_block_excerpt,
                "pass": pass_name,
                "call_id": call_id,
                "warning_buckets": warning_buckets,
                "trace_status": trace_status,
                "source_file": source_file,
                "source_hash": source_hash if isinstance(source_hash, str) else None,
                "source_key": source_key,
                **_line_context(
                    line_text_by_index=line_view.line_text_by_index,
                    line_index=line_index,
                    excerpt_limit=excerpt_limit,
                ),
            }
        )

    rows.sort(key=lambda row: int(row.get("line_index") or 0))
    if not rows:
        return [], "not_applicable"
    return rows, "ready"


def _parse_json_like(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _coerce_str_list(value: Any) -> list[str]:
    parsed = _parse_json_like(value)
    if isinstance(parsed, list):
        rows: list[str] = []
        for entry in parsed:
            if isinstance(entry, str):
                text = entry.strip()
                if text:
                    rows.append(text)
        return rows
    if isinstance(parsed, str):
        text = parsed.strip()
        if text:
            return [text]
    return []


def _is_empty_mapping_value(value: Any) -> bool:
    parsed = _parse_json_like(value)
    if isinstance(parsed, dict):
        return len(parsed) == 0
    if isinstance(parsed, str):
        return parsed.strip() in {"{}", "null", ""}
    return value is None


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _prompt_warning_bucket(message: str) -> str:
    lowered = message.lower()
    if "split" in lowered and "line" in lowered:
        return "split_line_boundary"
    if "serving" in lowered and "split" in lowered:
        return "serving_boundary_split"
    if "ingredient" in lowered and ("fragment" in lowered or "incomplete" in lowered):
        return "ingredient_fragment"
    if "no " in lowered and "instruction" in lowered:
        return "missing_instructions"
    if "page" in lowered or "ocr" in lowered or "artifact" in lowered:
        return "ocr_or_page_artifact"
    if "yield" in lowered:
        return "yield_detection"
    return "other"


def _summarize_prompt_warning_aggregate(full_prompt_log_path: Path) -> dict[str, Any]:
    rows = _iter_jsonl(full_prompt_log_path)
    by_pass_calls: Counter[str] = Counter()
    by_pass_calls_with_warnings: Counter[str] = Counter()
    warning_message_counts: Counter[str] = Counter()
    warning_bucket_counts: Counter[str] = Counter()
    pass3_empty_mapping_calls = 0
    pass3_empty_mapping_recipe_ids: Counter[str] = Counter()

    calls_with_warnings = 0
    warning_total = 0

    for row in rows:
        pass_name = str(row.get("pass") or "unknown").strip().lower() or "unknown"
        by_pass_calls[pass_name] += 1

        parsed_response = _parse_json_like(row.get("parsed_response"))
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
        warnings = _coerce_str_list(parsed_response.get("warnings"))
        if warnings:
            calls_with_warnings += 1
            by_pass_calls_with_warnings[pass_name] += 1
        for warning in warnings:
            normalized = _normalize_whitespace(warning)
            warning_message_counts[normalized] += 1
            warning_bucket_counts[_prompt_warning_bucket(normalized)] += 1
            warning_total += 1

        if pass_name == "pass3":
            ingredient_step_mapping = parsed_response.get("ingredient_step_mapping")
            if _is_empty_mapping_value(ingredient_step_mapping):
                pass3_empty_mapping_calls += 1
                recipe_id = str(row.get("recipe_id") or "").strip()
                if recipe_id:
                    pass3_empty_mapping_recipe_ids[recipe_id] += 1

    return {
        "source_full_prompt_log": str(full_prompt_log_path),
        "total_calls": len(rows),
        "calls_with_warnings": calls_with_warnings,
        "warnings_total": warning_total,
        "calls_by_pass": dict(sorted(by_pass_calls.items())),
        "calls_with_warnings_by_pass": dict(sorted(by_pass_calls_with_warnings.items())),
        "warning_buckets": dict(
            sorted(warning_bucket_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "top_warning_messages": [
            {"warning": message, "count": count}
            for message, count in warning_message_counts.most_common(20)
        ],
        "pass3_empty_ingredient_step_mapping_calls": pass3_empty_mapping_calls,
        "pass3_empty_ingredient_step_mapping_recipe_ids": [
            {"recipe_id": recipe_id, "count": count}
            for recipe_id, count in pass3_empty_mapping_recipe_ids.most_common()
        ],
    }


def _build_recipe_spans_from_full_prompt_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for row in rows:
        pass_name = str(row.get("pass") or "").strip().lower()
        if pass_name != "pass1":
            continue
        parsed_response = _parse_json_like(row.get("parsed_response"))
        if not isinstance(parsed_response, dict):
            continue
        is_recipe = parsed_response.get("is_recipe")
        if is_recipe is False:
            continue
        start = _coerce_int(parsed_response.get("start_block_index"))
        end = _coerce_int(parsed_response.get("end_block_index"))
        if start is None or end is None or end < start:
            continue
        recipe_id = str(parsed_response.get("recipe_id") or row.get("recipe_id") or "").strip()
        if not recipe_id:
            continue
        dedupe_key = (recipe_id, start, end)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        spans.append(
            {
                "recipe_id": recipe_id,
                "start_block_index": start,
                "end_block_index": end,
                "title": parsed_response.get("title"),
                "call_id": row.get("call_id"),
            }
        )
    spans.sort(
        key=lambda row: (
            int(row["start_block_index"]),
            int(row["end_block_index"]) - int(row["start_block_index"]),
            str(row["recipe_id"]),
        )
    )
    return spans


def _resolve_recipe_for_line(
    *,
    line_index: int,
    recipe_spans: list[dict[str, Any]],
) -> tuple[str | None, str]:
    matches: list[dict[str, Any]] = []
    for span in recipe_spans:
        start = int(span["start_block_index"])
        end = int(span["end_block_index"])
        if start <= line_index <= end:
            matches.append(span)
    if not matches:
        return None, "outside_active_recipe_span"
    best = sorted(
        matches,
        key=lambda span: (
            int(span["end_block_index"]) - int(span["start_block_index"]),
            int(span["start_block_index"]),
            str(span["recipe_id"]),
        ),
    )[0]
    return str(best["recipe_id"]), "inside_active_recipe_span"


def _build_line_prediction_view(
    *,
    run_dir: Path,
    recipe_spans: list[dict[str, Any]],
) -> LinePredictionView:
    eval_report_path = run_dir / "eval_report.json"
    eval_report = _load_json(eval_report_path) if eval_report_path.is_file() else {}
    canonical = eval_report.get("canonical")
    if not isinstance(canonical, dict):
        return LinePredictionView({}, {}, {}, {}, {}, recipe_spans)

    canonical_text_path_raw = canonical.get("canonical_text_path")
    canonical_spans_path_raw = canonical.get("canonical_span_labels_path")
    if not isinstance(canonical_text_path_raw, str) or not isinstance(canonical_spans_path_raw, str):
        return LinePredictionView({}, {}, {}, {}, {}, recipe_spans)

    canonical_text_path = Path(canonical_text_path_raw)
    canonical_spans_path = Path(canonical_spans_path_raw)
    if not canonical_text_path.is_file() or not canonical_spans_path.is_file():
        return LinePredictionView({}, {}, {}, {}, {}, recipe_spans)

    canonical_text = canonical_text_path.read_text(encoding="utf-8")
    lines = _build_canonical_lines(canonical_text)
    gold_spans = _load_gold_spans(canonical_spans_path)
    gold_labels_by_line = _line_gold_labels(lines=lines, spans=gold_spans)

    wrong_label_rows = _iter_jsonl(run_dir / "wrong_label_lines.jsonl")
    predicted_overrides: dict[int, str] = {}
    for row in wrong_label_rows:
        line_index = _coerce_int(row.get("line_index"))
        if line_index is None:
            continue
        pred_label = str(row.get("pred_label") or "").strip()
        if not pred_label:
            continue
        predicted_overrides[line_index] = pred_label

    line_text_by_index: dict[int, str] = {}
    gold_label_by_index: dict[int, str] = {}
    pred_label_by_index: dict[int, str] = {}
    recipe_id_by_index: dict[int, str | None] = {}
    recipe_span_by_index: dict[int, str] = {}

    for line in lines:
        line_index = int(line["line_index"])
        line_text = str(line.get("text") or "")
        gold_labels = gold_labels_by_line.get(line_index, ["OTHER"])
        gold_label = gold_labels[0] if gold_labels else "OTHER"
        pred_label = predicted_overrides.get(line_index, gold_label)
        recipe_id, span_region = _resolve_recipe_for_line(
            line_index=line_index,
            recipe_spans=recipe_spans,
        )

        line_text_by_index[line_index] = line_text
        gold_label_by_index[line_index] = gold_label
        pred_label_by_index[line_index] = pred_label
        recipe_id_by_index[line_index] = recipe_id
        recipe_span_by_index[line_index] = span_region

    return LinePredictionView(
        line_text_by_index=line_text_by_index,
        gold_label_by_index=gold_label_by_index,
        pred_label_by_index=pred_label_by_index,
        recipe_id_by_index=recipe_id_by_index,
        recipe_span_by_index=recipe_span_by_index,
        recipe_spans=recipe_spans,
    )


def _confusion_matrix_from_view(view: LinePredictionView) -> dict[str, dict[str, int]]:
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    for line_index in sorted(view.gold_label_by_index.keys()):
        gold = str(view.gold_label_by_index.get(line_index) or "OTHER")
        pred = str(view.pred_label_by_index.get(line_index) or "OTHER")
        matrix[gold][pred] += 1
    return {
        gold: dict(
            sorted(pred_counts.items(), key=lambda item: item[0])
        )
        for gold, pred_counts in sorted(matrix.items(), key=lambda item: item[0])
    }


def _delta_confusion_matrix(
    *,
    codex_confusion: dict[str, dict[str, int]],
    baseline_confusion: dict[str, dict[str, int]],
) -> dict[str, dict[str, int]]:
    gold_labels = sorted(set(codex_confusion) | set(baseline_confusion))
    delta: dict[str, dict[str, int]] = {}
    for gold in gold_labels:
        codex_row = codex_confusion.get(gold, {})
        baseline_row = baseline_confusion.get(gold, {})
        pred_labels = sorted(set(codex_row) | set(baseline_row))
        row_delta: dict[str, int] = {}
        for pred in pred_labels:
            value = int(codex_row.get(pred, 0)) - int(baseline_row.get(pred, 0))
            if value != 0:
                row_delta[pred] = value
        if row_delta:
            delta[gold] = row_delta
    return delta


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _line_context(
    *,
    line_text_by_index: dict[int, str],
    line_index: int,
    excerpt_limit: int,
) -> dict[str, str]:
    previous = line_text_by_index.get(line_index - 1, "")
    current = line_text_by_index.get(line_index, "")
    following = line_text_by_index.get(line_index + 1, "")
    return {
        "previous_line": _excerpt(previous, max_len=excerpt_limit),
        "current_line": _excerpt(current, max_len=excerpt_limit),
        "next_line": _excerpt(following, max_len=excerpt_limit),
    }


def _render_label_policy_notes() -> str:
    lines = [
        "# Label Policy / Adjudication Notes",
        "",
        "These notes summarize the active freeform labeling policy used by this benchmark surface.",
        "They are intended for resolving common edge-case disagreements in this cutdown.",
        "",
        "## RECIPE_TITLE vs RECIPE_VARIANT",
        "",
        "- `RECIPE_TITLE`: the canonical name/title line of a specific dish/recipe.",
        "- `RECIPE_VARIANT`: an explicit alternate version (for example, \"Variation:\" or \"For a vegan version...\").",
        "- If text is only a small tip and not a distinct alternate formulation, prefer `RECIPE_NOTES`.",
        "",
        "## RECIPE_NOTES vs KNOWLEDGE",
        "",
        "- Prefer `RECIPE_NOTES` for recipe-local notes/tips/warnings/substitutions inside an active recipe.",
        "- Use `KNOWLEDGE` for general technique/reference prose that is not tied to a specific current recipe.",
        "- If inside a recipe and uncertain, prefer `RECIPE_NOTES` unless clearly standalone general background.",
        "",
        "## Heading-Like Instruction Lines",
        "",
        "- Heading lines such as `FOR THE ...` or `TO MAKE ...` are typically `HOWTO_SECTION` at annotation time.",
        "- In canonical benchmark scoring, `HOWTO_SECTION` is structurally resolved to ingredient/instruction context.",
        "- Practical adjudication: keep true imperative action sentences as `INSTRUCTION_LINE`; keep pure section headers as `HOWTO_SECTION`.",
        "",
        "Source policy references:",
        "- `cookimport/labelstudio/prelabel.py` (label definitions and tie-break guidance)",
        "- `cookimport/labelstudio/CONVENTIONS.md` (canonical freeform label set and HOWTO scoring behavior)",
    ]
    return "\n".join(lines) + "\n"


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


def _normalized_setting_value(value: Any) -> str:
    if value is None:
        return "unset"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    return text if text else "unset"


def _format_setting_values(values: set[str]) -> str:
    normalized = sorted(value for value in values if value)
    if not normalized:
        return "`unset`"
    return ", ".join(f"`{value}`" for value in normalized)


def _record_setting_values(records: list[RunRecord], key: str) -> set[str]:
    return {_normalized_setting_value(record.config_snapshot.get(key)) for record in records}


def _extract_project_context_front_matter(text: str) -> dict[str, str]:
    match = PROJECT_CONTEXT_FRONT_MATTER_RE.match(text)
    if not match:
        return {}
    payload: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key_text = key.strip()
        value_text = value.strip().strip("'\"")
        if key_text and value_text:
            payload[key_text] = value_text
    return payload


def _extract_project_context_title(text: str, context_path: Path) -> str:
    heading_match = PROJECT_CONTEXT_HEADING_RE.search(text)
    if heading_match:
        heading = heading_match.group(1).strip()
        heading = re.sub(r"`[^`]+`", "", heading)
        heading = re.sub(r"\s*\(code-verified on [^)]+\)\s*$", "", heading, flags=re.IGNORECASE)
        if ":" in heading:
            heading = heading.split(":", 1)[0].strip()
        heading = " ".join(heading.split())
        if heading:
            return heading

    front_matter = _extract_project_context_front_matter(text)
    summary = front_matter.get("summary")
    if summary:
        return summary
    return context_path.stem


def _extract_project_context_version_or_date(text: str, context_path: Path) -> str:
    heading_match = PROJECT_CONTEXT_HEADING_RE.search(text)
    if heading_match:
        heading = heading_match.group(1)
        date_match = PROJECT_CONTEXT_DATE_RE.search(heading)
        if date_match:
            return date_match.group(1)

    front_matter = _extract_project_context_front_matter(text)
    for key in ("version", "date", "updated", "last_updated"):
        value = front_matter.get(key)
        if value:
            date_match = PROJECT_CONTEXT_DATE_RE.search(value)
            if date_match:
                return date_match.group(1)
            return value

    timestamp = datetime.fromtimestamp(context_path.stat().st_mtime, tz=timezone.utc)
    return timestamp.strftime("%Y-%m-%d")


def _project_context_metadata(repo_root: Path) -> dict[str, Any]:
    context_path = repo_root / PROJECT_CONTEXT_REL_PATH
    metadata = {
        "project_context_path": str(PROJECT_CONTEXT_REL_PATH).replace("\\", "/"),
        "project_context_title": "missing",
        "project_context_version_or_date": "missing",
        "project_context_hash": "missing",
    }
    if not context_path.is_file():
        return metadata

    raw_bytes = context_path.read_bytes()
    text = raw_bytes.decode("utf-8", errors="replace")
    metadata["project_context_title"] = _extract_project_context_title(text, context_path)
    metadata["project_context_version_or_date"] = _extract_project_context_version_or_date(
        text,
        context_path,
    )
    metadata["project_context_hash"] = hashlib.sha256(raw_bytes).hexdigest()
    return metadata


def _build_project_context_digest(
    *,
    records: list[RunRecord],
    comparison_summary: dict[str, Any],
    project_context_metadata: dict[str, Any],
    prompt_pairs_per_category: int,
) -> list[str]:
    codex_runs = [record for record in records if record.codex_enabled]
    baseline_runs = [record for record in records if not record.codex_enabled]
    pairs_raw = comparison_summary.get("pairs")
    pair_count = len(pairs_raw) if isinstance(pairs_raw, list) else 0
    changed_lines_total = _coerce_int(comparison_summary.get("changed_lines_total")) or 0

    llm_pipelines = {_normalized_setting_value(record.llm_recipe_pipeline) for record in records}
    line_role_values = {record.line_role_pipeline for record in records}
    atomic_splitter_values = {record.atomic_block_splitter for record in records}
    section_backends = _record_setting_values(records, "section_detector_backend")
    ingredient_parsers = _record_setting_values(records, "ingredient_parser_backend")
    ingredient_fix_backends = _record_setting_values(records, "ingredient_text_fix_backend")
    epub_preprocess_modes = _record_setting_values(records, "epub_unstructured_preprocess_mode")

    prompt_sampling_caveat = (
        "convenience prompt log keeps all calls when `--prompt-pairs-per-category 0`; "
        "`full_prompt_log.jsonl` remains the source of truth."
        if prompt_pairs_per_category <= 0
        else (
            "convenience prompt log samples at most "
            f"{prompt_pairs_per_category} calls per pass; `full_prompt_log.jsonl` remains complete."
        )
    )

    return [
        (
            "- context_pointer: "
            f"`{project_context_metadata['project_context_path']}` | "
            f"title=`{project_context_metadata['project_context_title']}` | "
            f"version_or_date=`{project_context_metadata['project_context_version_or_date']}` | "
            f"sha256=`{project_context_metadata['project_context_hash']}`"
        ),
        (
            "- system_summary: "
            f"runs={len(records)} (codex={len(codex_runs)}, baseline={len(baseline_runs)}), "
            f"paired_comparisons={pair_count}, changed_lines={changed_lines_total}."
        ),
        (
            "- benchmark_contract: canonical-text scoring compares predicted labels against "
            "canonical line-space gold labels (including structural labels such as "
            "`INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`)."
        ),
        (
            "- label_ontology_cheat_sheet: common canonical labels in this benchmark include "
            "`RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`, "
            "`RECIPE_NOTES`, and `OTHER`."
        ),
        (
            "- projection_bridge: codex pass1 prompt spans (`start_block_index`/`end_block_index`) "
            "are projected into canonical line diagnostics so changed-line rows can be split into "
            "`inside_active_recipe_span` vs `outside_active_recipe_span`."
        ),
        (
            "- active_pipeline_map: llm_recipe_pipeline="
            f"{_format_setting_values(llm_pipelines)}, "
            f"line_role_pipeline={_format_setting_values(line_role_values)}, "
            f"atomic_block_splitter={_format_setting_values(atomic_splitter_values)}; "
            "codex-vs-baseline pairing is by source_key with nearest timestamp baseline "
            "(baseline values: `off`/`none`/empty)."
        ),
        (
            "- backend_caveat: section_detector_backend="
            f"{_format_setting_values(section_backends)}, "
            f"ingredient_parser_backend={_format_setting_values(ingredient_parsers)}, "
            f"ingredient_text_fix_backend={_format_setting_values(ingredient_fix_backends)}, "
            f"epub_unstructured_preprocess_mode={_format_setting_values(epub_preprocess_modes)}."
        ),
        (
            "- artifact_legend: root diagnosis artifacts are `changed_lines.codex_vs_vanilla.jsonl`, "
            "`per_recipe_or_per_span_breakdown.json`, `targeted_prompt_cases.md`, and "
            "`label_policy_adjudication_notes.md`; run folders retain `need_to_know_summary.json` "
            "plus codex trace artifacts when available."
        ),
        (
            "- sampling_caveat: sampled line-level JSONL artifacts are bounded by `--sample-limit`; "
            "`unmatched_pred_blocks.jsonl` is counts-only unless alignment quality is weak "
            f"(coverage<{ALIGNMENT_HEALTHY_COVERAGE_MIN} or match_ratio<{ALIGNMENT_HEALTHY_MATCH_RATIO_MIN}); "
            f"{prompt_sampling_caveat}"
        ),
    ]


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


def _resolve_prompt_log_path(run_dir: Path, run_manifest: dict[str, Any]) -> Path | None:
    candidate_paths: list[Path] = []

    artifacts = run_manifest.get("artifacts")
    if isinstance(artifacts, dict):
        manifest_path_raw = artifacts.get(PROMPT_LOG_MANIFEST_ARTIFACT_KEY)
        if isinstance(manifest_path_raw, str) and manifest_path_raw.strip():
            manifest_path = Path(manifest_path_raw.strip())
            candidate_paths.append(
                manifest_path if manifest_path.is_absolute() else run_dir / manifest_path
            )

    candidate_paths.extend(
        [
            run_dir / PROMPT_LOG_FILE_NAME,
            run_dir / "codexfarm" / PROMPT_REQUEST_RESPONSE_LOG_NAME,
            run_dir / "codexfarm" / PROMPT_LOG_FILE_NAME,
            run_dir / PROMPT_REQUEST_RESPONSE_LOG_NAME,
        ]
    )

    seen: set[Path] = set()
    for candidate in candidate_paths:
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            return candidate
    return None


def _resolve_full_prompt_log_path(run_dir: Path, run_manifest: dict[str, Any]) -> Path | None:
    candidate_paths: list[Path] = []

    artifacts = run_manifest.get("artifacts")
    if isinstance(artifacts, dict):
        for key in FULL_PROMPT_LOG_MANIFEST_ARTIFACT_KEYS:
            manifest_path_raw = artifacts.get(key)
            if isinstance(manifest_path_raw, str) and manifest_path_raw.strip():
                manifest_path = Path(manifest_path_raw.strip())
                candidate_paths.append(
                    manifest_path if manifest_path.is_absolute() else run_dir / manifest_path
                )

    candidate_paths.extend(
        [
            run_dir / FULL_PROMPT_LOG_FILE_NAME,
            run_dir / "codexfarm" / FULL_PROMPT_LOG_FILE_NAME,
        ]
    )

    seen: set[Path] = set()
    for candidate in candidate_paths:
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            return candidate
    return None


def _resolve_prediction_run_dir(run_dir: Path, run_manifest: dict[str, Any]) -> Path | None:
    artifacts = run_manifest.get("artifacts")
    if isinstance(artifacts, dict):
        pred_run_raw = artifacts.get("pred_run_dir")
        if isinstance(pred_run_raw, str) and pred_run_raw.strip():
            pred_candidate = Path(pred_run_raw.strip())
            pred_path = pred_candidate if pred_candidate.is_absolute() else run_dir / pred_candidate
            if pred_path.exists() and pred_path.is_dir():
                return pred_path
    fallback = run_dir / "prediction-run"
    if fallback.exists() and fallback.is_dir():
        return fallback
    return None


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _parse_json_text(raw_text: str) -> Any | None:
    text = str(raw_text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _mtime_utc(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    try:
        stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_run_assets_payload(run_id: str) -> dict[str, Any]:
    if not run_id:
        return {}
    run_assets_dir = Path("var") / "run_assets" / run_id
    if not run_assets_dir.exists() or not run_assets_dir.is_dir():
        return {"run_id": run_id}

    def _safe_load_json_dict(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            return _load_json(path)
        except Exception:
            return None

    return {
        "run_id": run_id,
        "prompt_template_text": _safe_read_text(run_assets_dir / "prompt.template.txt"),
        "output_schema_payload": _safe_load_json_dict(run_assets_dir / "output.schema.json"),
        "effective_pipeline_payload": _safe_load_json_dict(
            run_assets_dir / "effective_pipeline.json"
        ),
        "manifest_payload": _safe_load_json_dict(run_assets_dir / "manifest.json"),
    }


def _render_prompt(template_text: str | None, input_text: str, input_file: Path) -> str:
    template = str(template_text or "")
    if not template.strip():
        return input_text
    rendered = template.replace("{{INPUT_TEXT}}", input_text)
    rendered = rendered.replace("{{ INPUT_TEXT }}", input_text)
    rendered = rendered.replace("{{INPUT_PATH}}", str(input_file))
    rendered = rendered.replace("{{ INPUT_PATH }}", str(input_file))
    return rendered


def _collect_context_blocks(parsed_input: Any) -> list[dict[str, Any]]:
    if not isinstance(parsed_input, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in ("blocks_before", "blocks_candidate", "blocks_after", "blocks"):
        blocks = parsed_input.get(key)
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            rows.append(
                {
                    "source_key": key,
                    "block_id": block.get("block_id"),
                    "index": block.get("index"),
                    "text": block.get("text"),
                }
            )
    return rows


def _reconstruct_full_prompt_log(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    output_path: Path,
) -> int:
    pred_run_dir = _resolve_prediction_run_dir(run_dir, run_manifest)
    if pred_run_dir is None:
        return 0
    raw_llm_dir = pred_run_dir / "raw" / "llm"
    if not raw_llm_dir.exists() or not raw_llm_dir.is_dir():
        return 0

    pred_manifest_path = pred_run_dir / "manifest.json"
    pred_manifest = _load_json(pred_manifest_path) if pred_manifest_path.is_file() else {}
    llm_payload = pred_manifest.get("llm_codex_farm") if isinstance(pred_manifest, dict) else {}
    process_runs = llm_payload.get("process_runs") if isinstance(llm_payload, dict) else {}
    source_payload = run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
    source_file = source_payload.get("path") if isinstance(source_payload, dict) else None
    source_file = str(source_file).strip() if isinstance(source_file, str) else None

    rows_written = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        run_dirs = sorted(path for path in raw_llm_dir.iterdir() if path.is_dir())
        for llm_run_dir in run_dirs:
            for pass_name, pass_dir in PASS_DIR_MAP.items():
                pass_in_dir = llm_run_dir / pass_dir / "in"
                pass_out_dir = llm_run_dir / pass_dir / "out"
                input_files = (
                    sorted(path for path in pass_in_dir.iterdir() if path.is_file())
                    if pass_in_dir.exists()
                    else []
                )
                output_files = (
                    sorted(path for path in pass_out_dir.iterdir() if path.is_file())
                    if pass_out_dir.exists()
                    else []
                )
                if not input_files and not output_files:
                    continue
                input_by_name = {path.name: path for path in input_files}
                output_by_name = {path.name: path for path in output_files}
                pass_process_payload = (
                    process_runs.get(pass_name) if isinstance(process_runs, dict) else None
                )
                pass_run_id = None
                if isinstance(pass_process_payload, dict):
                    pass_run_id = str(pass_process_payload.get("run_id") or "").strip() or None
                run_assets = _load_run_assets_payload(pass_run_id or "")
                prompt_template_text = (
                    run_assets.get("prompt_template_text")
                    if isinstance(run_assets, dict)
                    else None
                )
                output_schema_payload = (
                    run_assets.get("output_schema_payload")
                    if isinstance(run_assets, dict)
                    else None
                )
                effective_pipeline_payload = (
                    run_assets.get("effective_pipeline_payload")
                    if isinstance(run_assets, dict)
                    else None
                )
                model_value = None
                if isinstance(effective_pipeline_payload, dict):
                    model_raw = effective_pipeline_payload.get("codex_model")
                    if isinstance(model_raw, str) and model_raw.strip():
                        model_value = model_raw.strip()

                for file_name in sorted(set(input_by_name) | set(output_by_name)):
                    input_file = input_by_name.get(file_name)
                    output_file = output_by_name.get(file_name)
                    input_text = _safe_read_text(input_file) if input_file is not None else ""
                    output_text = _safe_read_text(output_file) if output_file is not None else ""
                    parsed_input = _parse_json_text(input_text)
                    parsed_output = _parse_json_text(output_text)
                    timestamp_utc = _mtime_utc(output_file) or _mtime_utc(input_file)
                    call_id = (
                        input_file.stem
                        if input_file is not None
                        else (output_file.stem if output_file is not None else Path(file_name).stem)
                    )
                    recipe_id = None
                    if isinstance(parsed_input, dict):
                        recipe_id = str(parsed_input.get("recipe_id") or "").strip() or None
                    if recipe_id is None and isinstance(parsed_output, dict):
                        recipe_id = str(parsed_output.get("recipe_id") or "").strip() or None
                    rendered_prompt = _render_prompt(
                        prompt_template_text,
                        input_text,
                        input_file or (pass_in_dir / file_name),
                    )
                    request_messages = [{"role": "user", "content": rendered_prompt}]
                    response_format = (
                        {
                            "type": "json_schema",
                            "json_schema": output_schema_payload,
                        }
                        if isinstance(output_schema_payload, dict)
                        else None
                    )
                    row = {
                        "run_id": str(run_manifest.get("run_id") or run_dir.name),
                        "pass": pass_name,
                        "call_id": call_id,
                        "timestamp_utc": timestamp_utc,
                        "recipe_id": recipe_id,
                        "source_file": source_file,
                        "pipeline_id": PASS_PIPELINE_MAP.get(pass_name),
                        "process_run_id": pass_run_id,
                        "model": model_value,
                        "request_messages": request_messages,
                        "system_prompt": None,
                        "developer_prompt": None,
                        "user_prompt": rendered_prompt,
                        "rendered_prompt_text": rendered_prompt,
                        "rendered_messages": request_messages,
                        "prompt_templates": {
                            "prompt_template_text": prompt_template_text,
                        },
                        "template_vars": {
                            "INPUT_PATH": str(input_file) if input_file is not None else None,
                            "INPUT_TEXT": input_text,
                        },
                        "inserted_context_blocks": _collect_context_blocks(parsed_input),
                        "request": {
                            "messages": request_messages,
                            "tools": [],
                            "response_format": response_format,
                            "model": model_value,
                            "temperature": None,
                            "top_p": None,
                            "max_output_tokens": None,
                            "seed": None,
                            "pipeline_id": PASS_PIPELINE_MAP.get(pass_name),
                        },
                        "raw_response": {
                            "output_text": output_text,
                            "output_file": str(output_file) if output_file is not None else None,
                        },
                        "parsed_response": parsed_output,
                        "request_input_payload": parsed_input,
                        "request_input_file": str(input_file) if input_file is not None else None,
                    }
                    handle.write(json.dumps(row, ensure_ascii=False))
                    handle.write("\n")
                    rows_written += 1

    if rows_written <= 0:
        output_path.unlink(missing_ok=True)
    return rows_written


def _alignment_is_healthy(alignment: dict[str, Any]) -> bool:
    canonical_coverage = _coerce_float(alignment.get("canonical_char_coverage"))
    prediction_match_ratio = _coerce_float(alignment.get("prediction_block_match_ratio"))
    if canonical_coverage is None or prediction_match_ratio is None:
        return False
    return (
        canonical_coverage >= ALIGNMENT_HEALTHY_COVERAGE_MIN
        and prediction_match_ratio >= ALIGNMENT_HEALTHY_MATCH_RATIO_MIN
    )


def _build_projection_trace(
    *,
    line_view: LinePredictionView,
    full_prompt_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    wrong_line_indices = [
        line_index
        for line_index, gold_label in line_view.gold_label_by_index.items()
        if line_view.pred_label_by_index.get(line_index, gold_label) != gold_label
    ]
    wrong_line_set = set(wrong_line_indices)

    pass_call_counts: Counter[str] = Counter()
    pass_warning_counts: Counter[str] = Counter()
    pass_recipe_ids: dict[str, set[str]] = defaultdict(set)
    pass3_empty_mapping_calls = 0
    pass3_empty_mapping_recipe_ids: Counter[str] = Counter()

    for row in full_prompt_rows:
        pass_name = str(row.get("pass") or "unknown").strip().lower() or "unknown"
        pass_call_counts[pass_name] += 1

        recipe_id = str(row.get("recipe_id") or "").strip()
        if recipe_id:
            pass_recipe_ids[pass_name].add(recipe_id)

        parsed_response = _parse_json_like(row.get("parsed_response"))
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
        warnings = _coerce_str_list(parsed_response.get("warnings"))
        if warnings:
            pass_warning_counts[pass_name] += len(warnings)

        if pass_name == "pass3" and _is_empty_mapping_value(
            parsed_response.get("ingredient_step_mapping")
        ):
            pass3_empty_mapping_calls += 1
            if recipe_id:
                pass3_empty_mapping_recipe_ids[recipe_id] += 1

    region_counts = {
        "inside_active_recipe_span": {"line_total": 0, "wrong_total": 0},
        "outside_active_recipe_span": {"line_total": 0, "wrong_total": 0},
    }
    recipe_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"line_total": 0, "wrong_total": 0}
    )
    for line_index in sorted(line_view.gold_label_by_index.keys()):
        recipe_id = line_view.recipe_id_by_index.get(line_index)
        region_key = "inside_active_recipe_span" if recipe_id else "outside_active_recipe_span"
        region_counts[region_key]["line_total"] += 1
        if line_index in wrong_line_set:
            region_counts[region_key]["wrong_total"] += 1

        if recipe_id:
            recipe_counts[recipe_id]["line_total"] += 1
            if line_index in wrong_line_set:
                recipe_counts[recipe_id]["wrong_total"] += 1

    return {
        "summary": {
            "canonical_line_total": len(line_view.gold_label_by_index),
            "wrong_line_total": len(wrong_line_indices),
            "pass_call_counts": dict(sorted(pass_call_counts.items())),
            "pass_warning_counts": dict(sorted(pass_warning_counts.items())),
            "pass3_empty_ingredient_step_mapping_calls": pass3_empty_mapping_calls,
        },
        "regions": {
            region: {
                **payload,
                "wrong_rate": _rate(payload["wrong_total"], payload["line_total"]),
            }
            for region, payload in region_counts.items()
        },
        "per_recipe": [
            {
                "recipe_id": recipe_id,
                "line_total": payload["line_total"],
                "wrong_total": payload["wrong_total"],
                "wrong_rate": _rate(payload["wrong_total"], payload["line_total"]),
            }
            for recipe_id, payload in sorted(
                recipe_counts.items(),
                key=lambda item: (
                    -item[1]["wrong_total"],
                    -item[1]["line_total"],
                    item[0],
                ),
            )
        ],
        "recipe_ids_seen_by_pass": {
            pass_name: sorted(recipe_ids)
            for pass_name, recipe_ids in sorted(pass_recipe_ids.items())
        },
        "pass3_empty_mapping_recipe_ids": [
            {"recipe_id": recipe_id, "count": count}
            for recipe_id, count in pass3_empty_mapping_recipe_ids.most_common()
        ],
        "bridge_note": (
            "Recipe span assignment for per-line diagnostics uses pass1 start/end block indices. "
            "Canonical line indices that do not fall inside an active pass1 span are treated as "
            "outside_active_recipe_span."
        ),
    }


def _build_run_cutdown(
    *,
    run_dir: Path,
    output_run_dir: Path,
    sample_limit: int,
    excerpt_limit: int,
    top_confusions_limit: int,
    top_labels_limit: int,
    prompt_pairs_per_category: int,
    prompt_excerpt_limit: int,
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
    atomic_block_splitter = str(run_config.get("atomic_block_splitter") or "off")
    line_role_pipeline = str(run_config.get("line_role_pipeline") or "off")
    codex_enabled = llm_recipe_pipeline not in {"off", "none", ""}

    counts = eval_report.get("counts")
    if not isinstance(counts, dict):
        counts = {}
    alignment = eval_report.get("alignment")
    if not isinstance(alignment, dict):
        alignment = {}
    worst_label_recall = eval_report.get("worst_label_recall")
    if not isinstance(worst_label_recall, dict):
        worst_label_recall = {}

    output_run_dir.mkdir(parents=True, exist_ok=True)

    eval_report_md_path = run_dir / "eval_report.md"
    if eval_report_md_path.is_file():
        shutil.copy2(eval_report_md_path, output_run_dir / "eval_report.md")

    sample_counts: dict[str, Any] = {}
    for source_name, output_name in LINE_LEVEL_SAMPLED_JSONL_INPUTS:
        source_path_jsonl = run_dir / source_name
        output_path_jsonl = output_run_dir / output_name
        counts = _write_jsonl_sample(
            source_path=source_path_jsonl,
            output_path=output_path_jsonl,
            sample_limit=sample_limit,
            excerpt_limit=excerpt_limit,
        )
        sample_counts[output_name] = counts

    unmatched_total_rows = _jsonl_row_count(run_dir / UNMATCHED_PRED_BLOCKS_INPUT)
    sample_counts[UNMATCHED_PRED_BLOCKS_INPUT] = {
        "total_rows": unmatched_total_rows,
        "sample_rows": 0,
        "mode": "counts_only_default",
    }

    alignment_total_counts = {
        source_name: _jsonl_row_count(run_dir / source_name)
        for source_name, _ in ALIGNMENT_SAMPLED_JSONL_INPUTS
    }
    alignment_healthy = _alignment_is_healthy(alignment)
    sample_counts["alignment_debug_sampling"] = {
        "mode": "counts_only_healthy_alignment"
        if alignment_healthy
        else "sampled_alignment_debug",
        "counts": alignment_total_counts,
        "thresholds": {
            "canonical_char_coverage_min": ALIGNMENT_HEALTHY_COVERAGE_MIN,
            "prediction_block_match_ratio_min": ALIGNMENT_HEALTHY_MATCH_RATIO_MIN,
        },
        "actual": {
            "canonical_char_coverage": _coerce_float(alignment.get("canonical_char_coverage")),
            "prediction_block_match_ratio": _coerce_float(
                alignment.get("prediction_block_match_ratio")
            ),
        },
    }
    if not alignment_healthy:
        for source_name, output_name in ALIGNMENT_SAMPLED_JSONL_INPUTS:
            source_path_jsonl = run_dir / source_name
            output_path_jsonl = output_run_dir / output_name
            counts = _write_jsonl_sample(
                source_path=source_path_jsonl,
                output_path=output_path_jsonl,
                sample_limit=sample_limit,
                excerpt_limit=excerpt_limit,
            )
            sample_counts[output_name] = counts

    codex_prompt_log = _resolve_prompt_log_path(run_dir, run_manifest)
    full_prompt_log_source = _resolve_full_prompt_log_path(run_dir, run_manifest)
    full_prompt_log_output = output_run_dir / FULL_PROMPT_LOG_FILE_NAME
    full_prompt_log_status = "not_applicable"
    full_prompt_log_rows = 0
    full_prompt_log_output_path: str | None = None
    full_prompt_rows: list[dict[str, Any]] = []
    if full_prompt_log_source is not None:
        shutil.copy2(full_prompt_log_source, full_prompt_log_output)
        full_prompt_rows = _iter_jsonl(full_prompt_log_output)
        full_prompt_log_rows = len(full_prompt_rows)
        full_prompt_log_status = "complete"
        full_prompt_log_output_path = FULL_PROMPT_LOG_FILE_NAME
    elif codex_enabled:
        reconstructed_rows = _reconstruct_full_prompt_log(
            run_dir=run_dir,
            run_manifest=run_manifest,
            output_path=full_prompt_log_output,
        )
        if reconstructed_rows > 0:
            full_prompt_log_status = "complete"
            full_prompt_log_rows = reconstructed_rows
            full_prompt_log_output_path = FULL_PROMPT_LOG_FILE_NAME
            full_prompt_rows = _iter_jsonl(full_prompt_log_output)
            if len(full_prompt_rows) != reconstructed_rows:
                full_prompt_log_rows = len(full_prompt_rows)
        else:
            full_prompt_log_status = "missing"

    sample_counts[FULL_PROMPT_LOG_FILE_NAME] = {
        "status": full_prompt_log_status,
        "rows": full_prompt_log_rows,
        "source_path": str(full_prompt_log_source) if full_prompt_log_source is not None else None,
    }
    recipe_spans = (
        _build_recipe_spans_from_full_prompt_rows(full_prompt_rows)
        if full_prompt_rows
        else []
    )

    prompt_log_output = output_run_dir / PROMPT_LOG_FILE_NAME
    if full_prompt_log_status == "complete" and full_prompt_log_output.is_file():
        sample_counts[PROMPT_LOG_FILE_NAME] = _write_prompt_log_samples_from_full_prompt_log(
            source_path=full_prompt_log_output,
            output_path=prompt_log_output,
            max_pairs_per_category=prompt_pairs_per_category,
            excerpt_limit=prompt_excerpt_limit,
        )
    elif codex_prompt_log is not None:
        if prompt_pairs_per_category <= 0:
            shutil.copy2(codex_prompt_log, prompt_log_output)
            sample_counts[PROMPT_LOG_FILE_NAME] = {
                "status": "full_copied",
                "source_path": str(codex_prompt_log),
            }
        else:
            sample_counts[PROMPT_LOG_FILE_NAME] = _write_prompt_log_samples(
                source_path=codex_prompt_log,
                output_path=prompt_log_output,
                max_pairs_per_category=prompt_pairs_per_category,
            )
    elif codex_enabled:
        sample_counts[PROMPT_LOG_FILE_NAME] = {
            "status": "missing",
            "source_path": None,
        }

    if codex_enabled and full_prompt_log_status == "complete" and full_prompt_log_output.is_file():
        prompt_warning_aggregate = _summarize_prompt_warning_aggregate(full_prompt_log_output)
        _write_json(output_run_dir / PROMPT_WARNING_AGGREGATE_FILE_NAME, prompt_warning_aggregate)
        sample_counts[PROMPT_WARNING_AGGREGATE_FILE_NAME] = {
            "status": "written",
            "total_calls": int(prompt_warning_aggregate.get("total_calls") or 0),
            "calls_with_warnings": int(prompt_warning_aggregate.get("calls_with_warnings") or 0),
            "warnings_total": int(prompt_warning_aggregate.get("warnings_total") or 0),
        }

        line_view = _build_line_prediction_view(run_dir=run_dir, recipe_spans=recipe_spans)
        projection_trace = _build_projection_trace(
            line_view=line_view,
            full_prompt_rows=full_prompt_rows,
        )
        projection_trace["recipe_span_count"] = len(recipe_spans)
        projection_trace["recipe_spans"] = recipe_spans
        _write_json(output_run_dir / PROJECTION_TRACE_FILE_NAME, projection_trace)
        sample_counts[PROJECTION_TRACE_FILE_NAME] = {
            "status": "written",
            "recipe_span_count": len(recipe_spans),
            "canonical_line_total": int(
                projection_trace.get("summary", {}).get("canonical_line_total") or 0
            ),
        }
    elif codex_enabled:
        sample_counts[PROMPT_WARNING_AGGREGATE_FILE_NAME] = {"status": "missing_full_prompt_log"}
        sample_counts[PROJECTION_TRACE_FILE_NAME] = {"status": "missing_full_prompt_log"}

    wrong_label_total_rows = _jsonl_row_count(run_dir / "wrong_label_lines.jsonl")
    if wrong_label_total_rows <= 0:
        sample_counts[WRONG_LABEL_FULL_CONTEXT_FILE_NAME] = {
            "status": "not_applicable",
            "rows": 0,
            "source_rows": 0,
        }
        sample_counts[PREPROCESS_TRACE_FAILURES_FILE_NAME] = {
            "status": "not_applicable",
            "rows": 0,
            "source_rows": 0,
        }
    else:
        wrong_label_full_rows = _build_wrong_label_full_context_rows(
            run_dir=run_dir,
            recipe_spans=recipe_spans,
            excerpt_limit=excerpt_limit,
        )
        wrong_label_full_output = output_run_dir / WRONG_LABEL_FULL_CONTEXT_FILE_NAME
        if wrong_label_full_rows:
            written_wrong_context_rows = _write_jsonl_gzip_deterministic(
                wrong_label_full_output,
                wrong_label_full_rows,
            )
            sample_counts[WRONG_LABEL_FULL_CONTEXT_FILE_NAME] = {
                "status": "written",
                "rows": written_wrong_context_rows,
                "source_rows": wrong_label_total_rows,
            }
        else:
            sample_counts[WRONG_LABEL_FULL_CONTEXT_FILE_NAME] = {
                "status": "not_applicable",
                "rows": 0,
                "source_rows": wrong_label_total_rows,
            }

        if not codex_enabled:
            sample_counts[PREPROCESS_TRACE_FAILURES_FILE_NAME] = {
                "status": "not_applicable",
                "rows": 0,
                "source_rows": wrong_label_total_rows,
            }
        else:
            preprocess_rows, preprocess_status = _build_preprocess_trace_failure_rows(
                run_dir=run_dir,
                run_manifest=run_manifest,
                full_prompt_rows=full_prompt_rows,
                excerpt_limit=excerpt_limit,
            )
            preprocess_output = output_run_dir / PREPROCESS_TRACE_FAILURES_FILE_NAME
            if preprocess_status == "ready" and preprocess_rows:
                written_preprocess_rows = _write_jsonl_gzip_deterministic(
                    preprocess_output,
                    preprocess_rows,
                )
                sample_counts[PREPROCESS_TRACE_FAILURES_FILE_NAME] = {
                    "status": "written",
                    "rows": written_preprocess_rows,
                    "source_rows": wrong_label_total_rows,
                }
            else:
                sample_counts[PREPROCESS_TRACE_FAILURES_FILE_NAME] = {
                    "status": (
                        preprocess_status
                        if preprocess_status != "ready"
                        else "not_applicable"
                    ),
                    "rows": 0,
                    "source_rows": wrong_label_total_rows,
                }

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
        "pipeline_knobs": {
            "llm_recipe_pipeline": llm_recipe_pipeline,
            "atomic_block_splitter": atomic_block_splitter,
            "line_role_pipeline": line_role_pipeline,
        },
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
        "per_label_metrics": compact_per_label,
        "lowest_recall_labels": low_recall_labels,
        "lowest_precision_labels": low_precision_labels,
        "sample_counts": sample_counts,
        "full_prompt_log_status": full_prompt_log_status,
        "full_prompt_log_rows": full_prompt_log_rows,
        "full_prompt_log_path": full_prompt_log_output_path,
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
        atomic_block_splitter=atomic_block_splitter,
        line_role_pipeline=line_role_pipeline,
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
        run_dir=str(run_dir),
        full_prompt_log_status=full_prompt_log_status,
        full_prompt_log_rows=full_prompt_log_rows,
        full_prompt_log_path=(
            f"{output_run_dir.name}/{FULL_PROMPT_LOG_FILE_NAME}"
            if full_prompt_log_output_path is not None
            else None
        ),
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


def _load_full_prompt_rows_for_run(record: RunRecord) -> list[dict[str, Any]]:
    run_dir = Path(record.run_dir)
    if not run_dir.is_dir():
        return []
    run_manifest_path = run_dir / "run_manifest.json"
    if not run_manifest_path.is_file():
        return []
    run_manifest = _load_json(run_manifest_path)
    full_prompt_log_path = _resolve_full_prompt_log_path(run_dir, run_manifest)
    if full_prompt_log_path is None or not full_prompt_log_path.is_file():
        return []
    return _iter_jsonl(full_prompt_log_path)


def _first_prompt_block_excerpt(row: dict[str, Any], *, excerpt_limit: int) -> str:
    request_input_payload = _parse_json_like(row.get("request_input_payload"))
    if not isinstance(request_input_payload, dict):
        return ""
    for key in ("blocks_candidate", "blocks_before", "blocks_after", "blocks"):
        blocks = request_input_payload.get(key)
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                return _excerpt(_normalize_whitespace(text), max_len=excerpt_limit)
    return ""


def _prompt_case_score(
    *,
    pass_name: str,
    warnings_count: int,
    empty_mapping: bool,
    changed_lines_for_recipe: int,
) -> int:
    pass_weights = {"pass3": 9, "pass2": 6, "pass1": 3}
    return (
        pass_weights.get(pass_name, 1)
        + warnings_count * 4
        + (8 if empty_mapping else 0)
        + changed_lines_for_recipe * 5
    )


def _build_pair_diagnostics(
    *,
    source_key: str,
    source_file: str | None,
    codex_run: RunRecord,
    baseline_run: RunRecord,
    excerpt_limit: int,
    targeted_case_limit: int,
) -> PairDiagnostics:
    codex_prompt_rows = _load_full_prompt_rows_for_run(codex_run)
    recipe_spans = _build_recipe_spans_from_full_prompt_rows(codex_prompt_rows)

    codex_view = _build_line_prediction_view(
        run_dir=Path(codex_run.run_dir),
        recipe_spans=recipe_spans,
    )
    baseline_view = _build_line_prediction_view(
        run_dir=Path(baseline_run.run_dir),
        recipe_spans=recipe_spans,
    )

    all_line_indices = sorted(
        set(codex_view.gold_label_by_index.keys()) | set(baseline_view.gold_label_by_index.keys())
    )
    line_text_by_index = (
        codex_view.line_text_by_index
        if codex_view.line_text_by_index
        else baseline_view.line_text_by_index
    )

    changed_line_rows: list[dict[str, Any]] = []
    recipe_flip_counts: Counter[str] = Counter()

    region_metrics: dict[str, dict[str, int]] = {
        "inside_active_recipe_span": {
            "line_total": 0,
            "codex_correct": 0,
            "baseline_correct": 0,
        },
        "outside_active_recipe_span": {
            "line_total": 0,
            "codex_correct": 0,
            "baseline_correct": 0,
        },
    }
    per_recipe_metrics: dict[str, dict[str, int]] = defaultdict(
        lambda: {"line_total": 0, "codex_correct": 0, "baseline_correct": 0}
    )

    for line_index in all_line_indices:
        gold_label = str(
            codex_view.gold_label_by_index.get(
                line_index,
                baseline_view.gold_label_by_index.get(line_index, "OTHER"),
            )
        )
        codex_pred = str(
            codex_view.pred_label_by_index.get(
                line_index,
                codex_view.gold_label_by_index.get(line_index, gold_label),
            )
        )
        baseline_pred = str(
            baseline_view.pred_label_by_index.get(
                line_index,
                baseline_view.gold_label_by_index.get(line_index, gold_label),
            )
        )

        recipe_id = codex_view.recipe_id_by_index.get(line_index)
        span_region = codex_view.recipe_span_by_index.get(
            line_index, "outside_active_recipe_span"
        )
        if span_region not in region_metrics:
            span_region = "outside_active_recipe_span"
        region_metrics[span_region]["line_total"] += 1
        if codex_pred == gold_label:
            region_metrics[span_region]["codex_correct"] += 1
        if baseline_pred == gold_label:
            region_metrics[span_region]["baseline_correct"] += 1

        if recipe_id:
            per_recipe_metrics[recipe_id]["line_total"] += 1
            if codex_pred == gold_label:
                per_recipe_metrics[recipe_id]["codex_correct"] += 1
            if baseline_pred == gold_label:
                per_recipe_metrics[recipe_id]["baseline_correct"] += 1

        if codex_pred == baseline_pred:
            continue

        if recipe_id:
            recipe_flip_counts[recipe_id] += 1

        changed_line_rows.append(
            {
                "source_key": source_key,
                "source_file": source_file,
                "codex_run_id": codex_run.run_id,
                "baseline_run_id": baseline_run.run_id,
                "line_index": line_index,
                "recipe_id": recipe_id,
                "span_region": span_region,
                "gold_label": gold_label,
                "vanilla_pred": baseline_pred,
                "codex_pred": codex_pred,
                **_line_context(
                    line_text_by_index=line_text_by_index,
                    line_index=line_index,
                    excerpt_limit=excerpt_limit,
                ),
            }
        )

    region_breakdown: list[dict[str, Any]] = []
    for region_name, payload in region_metrics.items():
        line_total = int(payload["line_total"])
        codex_accuracy = _rate(int(payload["codex_correct"]), line_total)
        baseline_accuracy = _rate(int(payload["baseline_correct"]), line_total)
        region_breakdown.append(
            {
                "region": region_name,
                "line_total": line_total,
                "codex_correct": int(payload["codex_correct"]),
                "baseline_correct": int(payload["baseline_correct"]),
                "codex_accuracy": codex_accuracy,
                "baseline_accuracy": baseline_accuracy,
                "delta_codex_minus_baseline": _delta(codex_accuracy, baseline_accuracy),
            }
        )

    per_recipe_breakdown = [
        {
            "recipe_id": recipe_id,
            "line_total": int(payload["line_total"]),
            "codex_correct": int(payload["codex_correct"]),
            "baseline_correct": int(payload["baseline_correct"]),
            "codex_accuracy": _rate(int(payload["codex_correct"]), int(payload["line_total"])),
            "baseline_accuracy": _rate(
                int(payload["baseline_correct"]), int(payload["line_total"])
            ),
            "delta_codex_minus_baseline": _delta(
                _rate(int(payload["codex_correct"]), int(payload["line_total"])),
                _rate(int(payload["baseline_correct"]), int(payload["line_total"])),
            ),
            "changed_lines_codex_vs_vanilla": int(recipe_flip_counts.get(recipe_id, 0)),
        }
        for recipe_id, payload in sorted(
            per_recipe_metrics.items(),
            key=lambda item: (
                -int(recipe_flip_counts.get(item[0], 0)),
                -int(item[1]["line_total"]),
                item[0],
            ),
        )
    ]

    codex_confusion = _confusion_matrix_from_view(codex_view)
    baseline_confusion = _confusion_matrix_from_view(baseline_view)
    confusion_delta = _delta_confusion_matrix(
        codex_confusion=codex_confusion,
        baseline_confusion=baseline_confusion,
    )

    targeted_prompt_candidates: list[dict[str, Any]] = []
    for row in codex_prompt_rows:
        pass_name = str(row.get("pass") or "unknown").strip().lower() or "unknown"
        parsed_response = _parse_json_like(row.get("parsed_response"))
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
        warnings = _coerce_str_list(parsed_response.get("warnings"))
        empty_mapping = (
            pass_name == "pass3"
            and _is_empty_mapping_value(parsed_response.get("ingredient_step_mapping"))
        )
        recipe_id = str(row.get("recipe_id") or "").strip()
        changed_lines_for_recipe = int(recipe_flip_counts.get(recipe_id, 0))
        if not warnings and not empty_mapping and changed_lines_for_recipe <= 0:
            continue

        call_id = str(row.get("call_id") or "").strip()
        targeted_prompt_candidates.append(
            {
                "source_key": source_key,
                "source_file": source_file,
                "codex_run_id": codex_run.run_id,
                "baseline_run_id": baseline_run.run_id,
                "pass": pass_name,
                "call_id": call_id,
                "recipe_id": recipe_id or None,
                "changed_lines_for_recipe": changed_lines_for_recipe,
                "warning_count": len(warnings),
                "warnings": warnings,
                "empty_ingredient_step_mapping": empty_mapping,
                "input_excerpt": _first_prompt_block_excerpt(
                    row,
                    excerpt_limit=excerpt_limit,
                ),
                "score": _prompt_case_score(
                    pass_name=pass_name,
                    warnings_count=len(warnings),
                    empty_mapping=empty_mapping,
                    changed_lines_for_recipe=changed_lines_for_recipe,
                ),
            }
        )

    targeted_prompt_candidates.sort(
        key=lambda row: (
            -int(row.get("score") or 0),
            -int(row.get("changed_lines_for_recipe") or 0),
            -int(row.get("warning_count") or 0),
            str(row.get("pass") or ""),
            str(row.get("call_id") or ""),
        )
    )

    targeted_prompt_case_rows: list[dict[str, Any]] = []
    seen_prompt_case_keys: set[tuple[str, str]] = set()
    for row in targeted_prompt_candidates:
        dedupe_key = (str(row.get("pass") or ""), str(row.get("call_id") or ""))
        if dedupe_key in seen_prompt_case_keys:
            continue
        seen_prompt_case_keys.add(dedupe_key)
        targeted_prompt_case_rows.append(
            {
                key: value
                for key, value in row.items()
                if key != "score"
            }
        )
        if len(targeted_prompt_case_rows) >= targeted_case_limit:
            break

    pair_breakdown = {
        "source_key": source_key,
        "source_file": source_file,
        "codex_run_id": codex_run.run_id,
        "baseline_run_id": baseline_run.run_id,
        "recipe_span_count": len(recipe_spans),
        "changed_lines_total": len(changed_line_rows),
        "region_breakdown": region_breakdown,
        "per_recipe_breakdown": per_recipe_breakdown,
    }

    return PairDiagnostics(
        changed_line_rows=changed_line_rows,
        pair_breakdown=pair_breakdown,
        confusion_matrix_codex=codex_confusion,
        confusion_matrix_baseline=baseline_confusion,
        confusion_delta_codex_minus_baseline=confusion_delta,
        targeted_prompt_case_rows=targeted_prompt_case_rows,
    )


def _build_comparison_summary(
    *,
    records: list[RunRecord],
    excerpt_limit: int,
    targeted_prompt_case_limit: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    by_source: dict[str, list[RunRecord]] = defaultdict(list)
    for record in records:
        by_source[record.source_key].append(record)

    pairs: list[dict[str, Any]] = []
    unpaired_codex: list[dict[str, Any]] = []
    unpaired_baseline: list[dict[str, Any]] = []
    changed_line_rows: list[dict[str, Any]] = []
    pair_breakdown_rows: list[dict[str, Any]] = []
    targeted_prompt_case_rows: list[dict[str, Any]] = []

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
                pair_diagnostics = _build_pair_diagnostics(
                    source_key=source_key,
                    source_file=codex_run.source_file or baseline.source_file,
                    codex_run=codex_run,
                    baseline_run=baseline,
                    excerpt_limit=excerpt_limit,
                    targeted_case_limit=targeted_prompt_case_limit,
                )
                changed_line_rows.extend(pair_diagnostics.changed_line_rows)
                pair_breakdown_rows.append(pair_diagnostics.pair_breakdown)
                targeted_prompt_case_rows.extend(pair_diagnostics.targeted_prompt_case_rows)
                pairs.append(
                    {
                        "source_key": source_key,
                        "source_file": codex_run.source_file or baseline.source_file,
                        "codex_run": {
                            "run_id": codex_run.run_id,
                            "output_subdir": codex_run.output_subdir,
                            "llm_recipe_pipeline": codex_run.llm_recipe_pipeline,
                            "atomic_block_splitter": codex_run.atomic_block_splitter,
                            "line_role_pipeline": codex_run.line_role_pipeline,
                            "overall_line_accuracy": codex_run.metric_overall_line_accuracy,
                            "macro_f1_excluding_other": codex_run.metric_macro_f1_excluding_other,
                            "practical_f1": codex_run.metric_practical_f1,
                            "worst_label_recall": codex_run.worst_label_recall,
                        },
                        "baseline_run": {
                            "run_id": baseline.run_id,
                            "output_subdir": baseline.output_subdir,
                            "llm_recipe_pipeline": baseline.llm_recipe_pipeline,
                            "atomic_block_splitter": baseline.atomic_block_splitter,
                            "line_role_pipeline": baseline.line_role_pipeline,
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
                        "changed_line_count": len(pair_diagnostics.changed_line_rows),
                        "confusion_matrix": {
                            "codex": pair_diagnostics.confusion_matrix_codex,
                            "baseline": pair_diagnostics.confusion_matrix_baseline,
                            "delta_codex_minus_baseline": pair_diagnostics.confusion_delta_codex_minus_baseline,
                        },
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
                        "atomic_block_splitter": codex_run.atomic_block_splitter,
                        "line_role_pipeline": codex_run.line_role_pipeline,
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
                        "atomic_block_splitter": baseline.atomic_block_splitter,
                        "line_role_pipeline": baseline.line_role_pipeline,
                    }
                )

    summary = {
        "pairing_rule": (
            "Within each source_key group, each codex-enabled run is paired with the "
            "nearest baseline (llm_recipe_pipeline=off/none/empty) by timestamp."
        ),
        "pairs": pairs,
        "unpaired_codex_runs": unpaired_codex,
        "unpaired_baseline_runs": unpaired_baseline,
    }
    return summary, changed_line_rows, pair_breakdown_rows, targeted_prompt_case_rows


def _select_targeted_prompt_cases(
    *,
    rows: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            -int(row.get("changed_lines_for_recipe") or 0),
            -int(row.get("warning_count") or 0),
            -int(bool(row.get("empty_ingredient_step_mapping"))),
            str(row.get("pass") or ""),
            str(row.get("call_id") or ""),
        ),
    )
    selected: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for row in sorted_rows:
        dedupe_key = (
            str(row.get("source_key") or ""),
            str(row.get("codex_run_id") or ""),
            str(row.get("pass") or ""),
            str(row.get("call_id") or ""),
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


def _write_targeted_prompt_cases_markdown(
    *,
    output_path: Path,
    rows: list[dict[str, Any]],
) -> None:
    lines = [
        "# Targeted Prompt Cases",
        "",
        "Deterministic high-signal prompt cases selected from codex runs.",
        "Selection preference: higher changed-line impact, then warning-heavy/empty-mapping cases.",
        "",
    ]
    if not rows:
        lines.append("No targeted prompt cases were selected.")
        lines.append("")
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return

    for index, row in enumerate(rows, start=1):
        warnings = row.get("warnings")
        warning_rows = warnings if isinstance(warnings, list) else []
        warning_summary = (
            "; ".join(_excerpt(str(item), max_len=220) for item in warning_rows[:3])
            if warning_rows
            else "none"
        )
        lines.extend(
            [
                f"## Case {index}",
                f"- source_key: `{row.get('source_key')}`",
                f"- codex_run_id: `{row.get('codex_run_id')}`",
                f"- baseline_run_id: `{row.get('baseline_run_id')}`",
                f"- pass/call: `{row.get('pass')}` / `{row.get('call_id')}`",
                f"- recipe_id: `{row.get('recipe_id')}`",
                f"- changed_lines_for_recipe: {row.get('changed_lines_for_recipe')}",
                f"- warning_count: {row.get('warning_count')}",
                (
                    "- empty_ingredient_step_mapping: true"
                    if bool(row.get("empty_ingredient_step_mapping"))
                    else "- empty_ingredient_step_mapping: false"
                ),
                f"- warning_summary: {warning_summary}",
                f"- input_excerpt: {_excerpt(str(row.get('input_excerpt') or ''), max_len=320)}",
                "",
            ]
        )

    output_path.write_text("\n".join(lines), encoding="utf-8")


def _write_readme(
    *,
    output_dir: Path,
    input_dir: Path,
    records: list[RunRecord],
    sample_limit: int,
    excerpt_limit: int,
    prompt_pairs_per_category: int,
    project_context_digest_lines: list[str],
    flattened: bool,
) -> None:
    lines: list[str] = []
    lines.append("# Benchmark Need-To-Know Package")
    lines.append("")
    lines.append(f"Generated: {_timestamp_now()}")
    lines.append(f"Source folder: `{input_dir}`")
    lines.append(f"Run count: {len(records)}")
    lines.append(f"Sample limit per JSONL artifact: {sample_limit}")
    lines.append(f"Excerpt char limit for sampled text fields: {excerpt_limit}")
    if prompt_pairs_per_category <= 0:
        lines.append(
            "CodexFarm sampled prompt log: convenience file keeps all calls from "
            "`full_prompt_log.jsonl` when available (legacy text-log copy fallback)."
        )
    else:
        lines.append(
            "CodexFarm sampled prompt log: convenience-only sampled calls per pass "
            f"(max {prompt_pairs_per_category}, sampled from full_prompt_log.jsonl when available)"
        )
    lines.append(
        "CodexFarm full prompt log: `full_prompt_log.jsonl` copied as complete machine-readable call rows (no sampling/truncation)."
    )
    lines.append("")
    lines.append("Each run folder includes:")
    lines.append("- `need_to_know_summary.json`")
    lines.append("- `eval_report.md` (if present in source run)")
    lines.append(f"- `{FULL_PROMPT_LOG_FILE_NAME}` (required for codex-enabled runs)")
    for _, output_name in LINE_LEVEL_SAMPLED_JSONL_INPUTS:
        lines.append(f"- `{output_name}`")
    lines.append(f"- `{WRONG_LABEL_FULL_CONTEXT_FILE_NAME}` (when wrong-label rows exist)")
    lines.append(
        f"- `{PREPROCESS_TRACE_FAILURES_FILE_NAME}` "
        "(codex runs with failures and available prediction/context artifacts)"
    )
    lines.append(f"- `{PROMPT_LOG_FILE_NAME}` (optional convenience-only)")
    lines.append(f"- `{PROMPT_WARNING_AGGREGATE_FILE_NAME}` (codex runs when full log is available)")
    lines.append(f"- `{PROJECTION_TRACE_FILE_NAME}` (codex runs when full log is available)")
    lines.append(
        "- `unmatched_pred_blocks.jsonl` is reported as counts-only by default; "
        "alignment debug samples are emitted only when alignment quality is weak."
    )
    lines.append("")
    lines.append("Root files:")
    lines.append("- `run_index.json`")
    lines.append("- `comparison_summary.json`")
    lines.append(f"- `{CHANGED_LINES_FILE_NAME}`")
    lines.append(f"- `{PER_RECIPE_BREAKDOWN_FILE_NAME}`")
    lines.append(f"- `{TARGETED_PROMPT_CASES_FILE_NAME}`")
    lines.append(f"- `{LABEL_POLICY_NOTES_FILE_NAME}`")
    lines.append("- `process_manifest.json`")
    if flattened:
        lines.append("")
        lines.append(
            "Flattened markdown output is written to sibling folder "
            f"`{output_dir.name}_md`."
        )
    lines.append("")
    lines.append("## Project Context Digest")
    lines.append("")
    lines.extend(project_context_digest_lines)
    lines.append("")
    lines.append("Run index:")
    for record in sorted(records, key=lambda row: row.run_id):
        lines.append(
            "- "
            f"`{record.output_subdir}` | source={record.source_file or 'unknown'} "
            f"| llm_recipe_pipeline={record.llm_recipe_pipeline} "
            f"| atomic_block_splitter={record.atomic_block_splitter} "
            f"| line_role_pipeline={record.line_role_pipeline} "
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

    _write_root_summary_markdown(md_output_dir)
    return md_output_dir


def _write_root_summary_markdown(output_dir: Path) -> Path:
    readme_path = output_dir / "README.md"
    run_index_path = output_dir / "run_index.json"
    comparison_summary_path = output_dir / "comparison_summary.json"
    changed_lines_path = output_dir / CHANGED_LINES_FILE_NAME
    per_recipe_breakdown_path = output_dir / PER_RECIPE_BREAKDOWN_FILE_NAME
    targeted_prompt_cases_path = output_dir / TARGETED_PROMPT_CASES_FILE_NAME
    label_policy_notes_path = output_dir / LABEL_POLICY_NOTES_FILE_NAME
    process_manifest_path = output_dir / "process_manifest.json"

    sections: list[str] = []
    sections.append("# Benchmark Need-To-Know Package (Flattened)")
    sections.append("")

    if readme_path.is_file():
        sections.append("## README")
        sections.append(readme_path.read_text(encoding="utf-8").rstrip())
        sections.append("")

    if run_index_path.is_file():
        sections.append("## run_index.json")
        sections.append("```json")
        sections.append(json.dumps(_load_json(run_index_path), indent=2, sort_keys=True))
        sections.append("```")
        sections.append("")

    if comparison_summary_path.is_file():
        sections.append("## comparison_summary.json")
        sections.append("```json")
        sections.append(
            json.dumps(_load_json(comparison_summary_path), indent=2, sort_keys=True)
        )
        sections.append("```")
        sections.append("")

    if changed_lines_path.is_file():
        sections.append(f"## {CHANGED_LINES_FILE_NAME}")
        sections.append(
            f"Rows: {_jsonl_row_count(changed_lines_path)} (see file for full details)."
        )
        sections.append("")

    if per_recipe_breakdown_path.is_file():
        sections.append(f"## {PER_RECIPE_BREAKDOWN_FILE_NAME}")
        sections.append("```json")
        sections.append(
            json.dumps(_load_json(per_recipe_breakdown_path), indent=2, sort_keys=True)
        )
        sections.append("```")
        sections.append("")

    if targeted_prompt_cases_path.is_file():
        sections.append(f"## {TARGETED_PROMPT_CASES_FILE_NAME}")
        sections.append(targeted_prompt_cases_path.read_text(encoding="utf-8").rstrip())
        sections.append("")

    if label_policy_notes_path.is_file():
        sections.append(f"## {LABEL_POLICY_NOTES_FILE_NAME}")
        sections.append(label_policy_notes_path.read_text(encoding="utf-8").rstrip())
        sections.append("")

    if process_manifest_path.is_file():
        sections.append("## process_manifest.json")
        sections.append("```json")
        sections.append(
            json.dumps(_load_json(process_manifest_path), indent=2, sort_keys=True)
        )
        sections.append("```")
        sections.append("")

    output_path = output_dir / AGGREGATED_ROOT_SUMMARY_MD
    output_path.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")

    for source_path in (readme_path, run_index_path, comparison_summary_path, process_manifest_path):
        if source_path.is_file():
            source_path.unlink()

    return output_path


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    input_dir = args.input_dir.resolve()
    if not input_dir.is_dir():
        print(f"error: input directory does not exist: {input_dir}", file=sys.stderr)
        return 1
    if args.sample_limit <= 0:
        print("error: --sample-limit must be > 0", file=sys.stderr)
        return 1
    if args.excerpt_limit <= 0:
        print("error: --excerpt-limit must be > 0", file=sys.stderr)
        return 1
    if args.prompt_excerpt_limit <= 0:
        print("error: --prompt-excerpt-limit must be > 0", file=sys.stderr)
        return 1
    if args.prompt_pairs_per_category < 0:
        print(
            "error: --prompt-pairs-per-category must be >= 0",
            file=sys.stderr,
        )
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
        output_dir_explicit = False
    else:
        output_dir = args.output_dir.resolve()
        output_dir_explicit = True

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
            excerpt_limit=args.excerpt_limit,
            top_confusions_limit=args.top_confusions,
            top_labels_limit=args.top_labels,
            prompt_pairs_per_category=args.prompt_pairs_per_category,
            prompt_excerpt_limit=args.prompt_excerpt_limit,
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
                "atomic_block_splitter": record.atomic_block_splitter,
                "line_role_pipeline": record.line_role_pipeline,
                "codex_enabled": record.codex_enabled,
                "overall_line_accuracy": record.metric_overall_line_accuracy,
                "macro_f1_excluding_other": record.metric_macro_f1_excluding_other,
                "practical_f1": record.metric_practical_f1,
                "full_prompt_log_status": record.full_prompt_log_status,
                "full_prompt_log_rows": record.full_prompt_log_rows,
                "full_prompt_log_path": record.full_prompt_log_path,
                "summary_path": record.summary_path,
            }
            for record in sorted(records, key=lambda row: row.run_id)
        ],
    }
    _write_json(output_dir / "run_index.json", run_index)

    (
        comparison_summary,
        changed_line_rows,
        pair_breakdown_rows,
        targeted_prompt_case_rows,
    ) = _build_comparison_summary(
        records=records,
        excerpt_limit=args.excerpt_limit,
        targeted_prompt_case_limit=DEFAULT_TARGETED_PROMPT_CASES,
    )
    changed_line_rows.sort(
        key=lambda row: (
            str(row.get("source_key") or ""),
            str(row.get("codex_run_id") or ""),
            int(row.get("line_index") or 0),
        )
    )
    _write_jsonl(output_dir / CHANGED_LINES_FILE_NAME, changed_line_rows)

    per_recipe_breakdown_payload = {
        "generated_at": _timestamp_now(),
        "pair_count": len(pair_breakdown_rows),
        "pairs": pair_breakdown_rows,
    }
    _write_json(output_dir / PER_RECIPE_BREAKDOWN_FILE_NAME, per_recipe_breakdown_payload)

    selected_targeted_prompt_cases = _select_targeted_prompt_cases(
        rows=targeted_prompt_case_rows,
        limit=DEFAULT_TARGETED_PROMPT_CASES,
    )
    _write_targeted_prompt_cases_markdown(
        output_path=output_dir / TARGETED_PROMPT_CASES_FILE_NAME,
        rows=selected_targeted_prompt_cases,
    )
    (output_dir / LABEL_POLICY_NOTES_FILE_NAME).write_text(
        _render_label_policy_notes(),
        encoding="utf-8",
    )

    project_context_metadata = _project_context_metadata(repo_root)
    project_context_pointer = {
        "project_context_path": project_context_metadata["project_context_path"],
        "project_context_title": project_context_metadata["project_context_title"],
        "project_context_version_or_date": project_context_metadata[
            "project_context_version_or_date"
        ],
        "project_context_hash": project_context_metadata["project_context_hash"],
    }

    comparison_summary["generated_at"] = _timestamp_now()
    comparison_summary["input_dir"] = str(input_dir)
    comparison_summary["output_dir"] = str(output_dir)
    comparison_summary["changed_lines_total"] = len(changed_line_rows)
    comparison_summary["changed_lines_file"] = CHANGED_LINES_FILE_NAME
    comparison_summary["per_recipe_or_per_span_breakdown_file"] = PER_RECIPE_BREAKDOWN_FILE_NAME
    comparison_summary["targeted_prompt_cases_file"] = TARGETED_PROMPT_CASES_FILE_NAME
    comparison_summary["label_policy_notes_file"] = LABEL_POLICY_NOTES_FILE_NAME
    comparison_summary["project_context"] = dict(project_context_pointer)

    project_context_digest_lines = _build_project_context_digest(
        records=records,
        comparison_summary=comparison_summary,
        project_context_metadata=project_context_metadata,
        prompt_pairs_per_category=args.prompt_pairs_per_category,
    )
    _write_json(output_dir / "comparison_summary.json", comparison_summary)

    codex_records = [record for record in records if record.codex_enabled]
    missing_codex_full_prompt_logs = [
        record
        for record in codex_records
        if record.full_prompt_log_status != "complete"
    ]
    if codex_records:
        package_full_prompt_status = (
            "complete" if not missing_codex_full_prompt_logs else "missing"
        )
    else:
        package_full_prompt_status = "not_applicable"
    process_manifest = {
        "generated_at": _timestamp_now(),
        "tool": "scripts/benchmark_cutdown_for_external_ai.py",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "sample_limit": args.sample_limit,
        "excerpt_limit": args.excerpt_limit,
        "top_confusions": args.top_confusions,
        "top_labels": args.top_labels,
        "prompt_pairs_per_category": args.prompt_pairs_per_category,
        "targeted_prompt_cases_limit": DEFAULT_TARGETED_PROMPT_CASES,
        "flatten_enabled": not args.no_flatten,
        "flatten_script": str(args.flatten_script),
        "changed_lines_total": len(changed_line_rows),
        "comparison_pair_breakdown_count": len(pair_breakdown_rows),
        "full_prompt_log_status": package_full_prompt_status,
        "full_prompt_log_rows": sum(record.full_prompt_log_rows for record in records),
        "full_prompt_log_path": (
            records[0].full_prompt_log_path if len(records) == 1 else None
        ),
        "project_context_path": project_context_pointer["project_context_path"],
        "project_context_title": project_context_pointer["project_context_title"],
        "project_context_version_or_date": project_context_pointer[
            "project_context_version_or_date"
        ],
        "project_context_hash": project_context_pointer["project_context_hash"],
        "project_context_digest_included": True,
        "full_prompt_log_runs": [
            {
                "run_id": record.run_id,
                "output_subdir": record.output_subdir,
                "status": record.full_prompt_log_status,
                "rows": record.full_prompt_log_rows,
                "path": record.full_prompt_log_path,
            }
            for record in sorted(records, key=lambda row: row.run_id)
        ],
    }

    _write_readme(
        output_dir=output_dir,
        input_dir=input_dir,
        records=records,
        sample_limit=args.sample_limit,
        excerpt_limit=args.excerpt_limit,
        prompt_pairs_per_category=args.prompt_pairs_per_category,
        project_context_digest_lines=project_context_digest_lines,
        flattened=not args.no_flatten,
    )
    included_files = {path.name for path in output_dir.iterdir() if path.is_file()}
    included_files.add("process_manifest.json")
    for record in records:
        if record.full_prompt_log_path:
            included_files.add(record.full_prompt_log_path)
        run_output_dir = output_dir / record.output_subdir
        for nested_file_name in (
            WRONG_LABEL_FULL_CONTEXT_FILE_NAME,
            PREPROCESS_TRACE_FAILURES_FILE_NAME,
        ):
            nested_path = run_output_dir / nested_file_name
            if nested_path.is_file():
                included_files.add(f"{record.output_subdir}/{nested_file_name}")
    process_manifest["included_files"] = sorted(included_files)
    _write_json(output_dir / "process_manifest.json", process_manifest)

    md_output_dir: Path | None = None
    if not args.no_flatten:
        md_output_dir = _flatten_output(
            repo_root=repo_root,
            output_dir=output_dir,
            flatten_script=args.flatten_script,
        )

        if not args.keep_cutdown and not output_dir_explicit:
            shutil.rmtree(output_dir)

    final_output_dir = md_output_dir if md_output_dir is not None else output_dir
    print(f"Built cutdown package: {final_output_dir}")
    if args.keep_cutdown and not args.no_flatten:
        print(f"Kept intermediate package: {output_dir}")
    if md_output_dir is not None and not args.no_flatten:
        print(f"Built flattened package: {md_output_dir}")
    print(f"Runs processed: {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
