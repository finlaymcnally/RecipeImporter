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
import base64
import csv
import gzip
import hashlib
import io
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

from cookimport.bench.eval_stage_blocks import (
    compute_block_metrics,
    load_gold_block_labels,
)
from cookimport.bench.codex_bridge_projection_policy import (
    resolve_trace_status,
    select_prompt_row_for_trace,
)


DEFAULT_SAMPLE_LIMIT = 80
DEFAULT_TOP_CONFUSIONS = 8
DEFAULT_TOP_LABELS = 6
DEFAULT_EXCERPT_LIMIT = 440
DEFAULT_PROMPT_EXCERPT_LIMIT = 2000
DEFAULT_PROMPT_PAIRS_PER_CATEGORY = 3
DEFAULT_TARGETED_PROMPT_CASES = 10
ALIGNMENT_HEALTHY_COVERAGE_MIN = 0.98
ALIGNMENT_HEALTHY_MATCH_RATIO_MIN = 0.98
GROUP_UPLOAD_BUNDLE_TARGET_BYTES = 40 * 1024 * 1024
GROUP_UPLOAD_BUNDLE_RESERVED_BYTES = 3 * 1024 * 1024
GROUP_UPLOAD_BUNDLE_ROOT_ARTIFACT_BUDGET_SHARE = 0.8
GROUP_UPLOAD_BUNDLE_MIN_ARTIFACT_BUDGET_BYTES = 4 * 1024 * 1024
GROUP_UPLOAD_BUNDLE_GROUP_PACKET_FILE_NAME = "group_high_level_packet.json"
GROUP_UPLOAD_BUNDLE_MIN_WRONG_LINE_SAMPLES_PER_RUN = 1
GROUP_UPLOAD_BUNDLE_MAX_WRONG_LINE_SAMPLES_PER_RUN = 240
UPLOAD_BUNDLE_MIN_PAIRS_FOR_GENERALIZATION = 2
UPLOAD_BUNDLE_LOW_CONFIDENCE_THRESHOLD = 0.90
UPLOAD_BUNDLE_ESTIMATED_COST_DEFAULT_PRICING = {
    "input_per_1m": 3.0,
    "cached_input_per_1m": 0.0,
    "output_per_1m": 15.0,
}

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
GROUP_UPLOAD_BUNDLE_ROOT_PRIORITY_FILES = (
    "run_index.json",
    "comparison_summary.json",
    "process_manifest.json",
    "README.md",
    "changed_lines.codex_vs_vanilla.jsonl",
    "per_recipe_or_per_span_breakdown.json",
    "targeted_prompt_cases.md",
    "label_policy_adjudication_notes.md",
)
GROUP_UPLOAD_BUNDLE_RUN_PRIORITY_FILES: tuple[tuple[str, bool], ...] = (
    ("run_manifest.json", True),
    ("eval_report.json", False),
    ("need_to_know_summary.json", False),
)
UPLOAD_BUNDLE_OVERVIEW_FILE_NAME = "upload_bundle_overview.md"
UPLOAD_BUNDLE_INDEX_FILE_NAME = "upload_bundle_index.json"
UPLOAD_BUNDLE_PAYLOAD_FILE_NAME = "upload_bundle_payload.jsonl"
UPLOAD_BUNDLE_FILE_NAMES = (
    UPLOAD_BUNDLE_OVERVIEW_FILE_NAME,
    UPLOAD_BUNDLE_INDEX_FILE_NAME,
    UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
)
UPLOAD_BUNDLE_DERIVED_DIR_NAME = "_upload_bundle_derived"
STARTER_PACK_DIR_NAME = "starter_pack_v1"
STARTER_PACK_README_FILE_NAME = "README.md"
STARTER_PACK_TRIAGE_FILE_NAME = "01_recipe_triage.jsonl"
STARTER_PACK_TRIAGE_LEGACY_CSV_FILE_NAME = "01_recipe_triage.csv"
STARTER_PACK_TRIAGE_PACKET_FILE_NAME = "01_recipe_triage.packet.jsonl"
STARTER_PACK_CALL_INVENTORY_FILE_NAME = "02_call_inventory.jsonl"
STARTER_PACK_CHANGED_LINES_FILE_NAME = "03_changed_lines.codex_vs_baseline.jsonl"
STARTER_PACK_WARNING_TRACE_SUMMARY_FILE_NAME = "04_warning_and_trace_summary.json"
STARTER_PACK_BRIDGE_SUMMARY_FILE_NAME = "05_bridge_summary.jsonl"
STARTER_PACK_SELECTED_PACKETS_FILE_NAME = "06_selected_recipe_packets.jsonl"
STARTER_PACK_CASEBOOK_FILE_NAME = "07_casebook.md"
STARTER_PACK_OUTSIDE_TRACE_FILE_NAME = "08_outside_span_trace.sample.jsonl"
STARTER_PACK_LABEL_POLICY_FILE_NAME = "09_label_policy.md"
STARTER_PACK_MANIFEST_FILE_NAME = "10_process_manifest.json"
STARTER_PACK_COMPARISON_MIRROR_FILE_NAME = "11_comparison_summary.json"
STARTER_PACK_BREAKDOWN_MIRROR_FILE_NAME = "12_per_recipe_or_per_span_breakdown.json"
STARTER_PACK_NET_ERROR_BLAME_FILE_NAME = "13_net_error_blame_summary.json"
STARTER_PACK_CONFIG_VERSION_METADATA_FILE_NAME = "14_config_version_metadata.json"
STARTER_PACK_LOW_CONFIDENCE_CHANGED_LINES_FILE_NAME = (
    "15_low_confidence_changed_lines.packet.jsonl"
)
STARTER_PACK_BASELINE_TRACE_PARITY_FILE_NAME = "16_baseline_trace_parity.json"
STARTER_PACK_SELECTION_POLICY = {
    "top_changed_lines": 3,
    "top_block_loss": 2,
    "top_empty_mapping": 2,
    "outside_span_case": 1,
    "healthy_control": 1,
}
STARTER_PACK_OUTSIDE_WRONG_LINE_THRESHOLD = 10
STARTER_PACK_OUTSIDE_ACCURACY_GAP_THRESHOLD = 0.05
STARTER_PACK_HEAVY_ARTIFACTS_OMITTED_BY_DEFAULT = [
    "full_prompt_log.jsonl",
    "wrong_label_lines.with_context.full.jsonl.gz",
    "preprocess_trace_failures.jsonl.gz",
    "flattened_run_markdown_summaries",
]
UPLOAD_BUNDLE_TRIAGE_PACKET_SCHEMA_VERSION = "upload_bundle_triage_packet.v1"
UPLOAD_BUNDLE_NET_ERROR_BLAME_SCHEMA_VERSION = "upload_bundle_net_error_blame.v1"
UPLOAD_BUNDLE_CONFIG_VERSION_METADATA_SCHEMA_VERSION = (
    "upload_bundle_config_version_metadata.v1"
)
UPLOAD_BUNDLE_LOW_CONFIDENCE_CHANGED_LINES_SCHEMA_VERSION = (
    "upload_bundle_low_confidence_changed_lines.v1"
)
STARTER_PACK_TRIAGE_HEADER = (
    "recipe_id",
    "short_title",
    "line_total",
    "changed_lines_codex_vs_baseline",
    "codex_accuracy",
    "baseline_accuracy",
    "delta_codex_minus_baseline",
    "pass1_call_id",
    "pass2_call_id",
    "pass3_call_id",
    "pass1_start_block_index",
    "pass1_end_block_index",
    "pass1_selected_block_count",
    "pass2_input_block_count",
    "pass1_vs_pass2_missing_block_count",
    "pass1_vs_pass2_extra_block_count",
    "pass2_warning_count",
    "pass2_warning_buckets",
    "pass2_extracted_ingredient_count",
    "pass2_extracted_instruction_count",
    "pass3_step_count",
    "pass3_mapping_count",
    "pass3_empty_mapping",
    "pass3_warning_count",
    "pass3_warning_buckets",
    "pass1_status",
    "pass2_status",
    "pass3_status",
    "pass1_clamped_block_loss_count",
    "pass1_clamped_block_loss_ratio",
    "pass2_degradation_reasons",
    "pass2_degradation_severity",
    "pass2_promotion_policy",
    "pass3_execution_mode",
    "pass3_routing_reason",
    "pass3_fallback_reason",
    "transport_mismatch",
    "transport_mismatch_reasons",
    "transport_effective_to_payload_coverage_ratio",
    "evidence_split_quantity_lines",
    "evidence_dropped_page_markers",
    "evidence_folded_page_markers",
    "outside_span_wrong_line_count",
    "outside_span_trace_status_top",
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
_UPLOAD_BUNDLE_YIELD_LINE_RE = re.compile(
    r"\b(yield|serves?|servings?|makes?)\b",
    re.IGNORECASE,
)
_UPLOAD_BUNDLE_TIME_LINE_RE = re.compile(
    r"\b(prep|cook|total|active|rest|marinate|chill|time)\b",
    re.IGNORECASE,
)
_UPLOAD_BUNDLE_TIME_VALUE_RE = re.compile(
    r"(?:\b\d+\s*(?:h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\b|\b\d{1,2}:\d{2}\b)",
    re.IGNORECASE,
)

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
    recipe_triage_rows: list[dict[str, Any]]
    call_inventory_rows: list[dict[str, Any]]
    outside_span_trace_rows: list[dict[str, Any]]


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
    parser.add_argument(
        "--upload-3-files",
        action="store_true",
        help=(
            "Write a consolidated 3-file upload bundle at the output root "
            "(overview markdown + artifact index JSON + full payload JSONL)."
        ),
    )
    parser.add_argument(
        "--upload-3-files-only",
        action="store_true",
        help=(
            "After writing the 3-file upload bundle, prune all other files/directories "
            "from the output folder. Requires --upload-3-files and --no-flatten."
        ),
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


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in {0, 1}:
            return bool(value)
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no"}:
            return False
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
        span_region = line_view.recipe_span_by_index.get(
            line_index,
            "outside_active_recipe_span",
        )
        recipe_key = str(recipe_id or "").strip()
        prompt_row = select_prompt_row_for_trace(
            recipe_key=recipe_key,
            span_region=span_region,
            prompt_rows_by_recipe=prompt_rows_by_recipe,
            fallback_prompt_row=fallback_prompt_row,
        )
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
        trace_status = resolve_trace_status(
            span_region=span_region,
            has_prompt_excerpt=bool(prompt_candidate_block_excerpt),
            has_archive_excerpt=bool(raw_block_excerpt),
        )

        rows.append(
            {
                "run_id": run_id,
                "line_index": line_index,
                "recipe_id": recipe_id,
                "span_region": span_region,
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


def _normalize_warning_bucket_name(bucket: str) -> str:
    cleaned = str(bucket or "").strip().lower()
    if cleaned in {"ocr_or_page_artifact", "page_or_layout_artifact"}:
        return "page_or_layout_artifact"
    return cleaned


def _normalize_warning_bucket_reason(reason: str) -> str:
    cleaned = str(reason or "").strip()
    normalized_bare = _normalize_warning_bucket_name(cleaned)
    if normalized_bare and normalized_bare != cleaned:
        return normalized_bare
    prefix = "warning_bucket:"
    if not cleaned.startswith(prefix):
        return cleaned
    bucket = _normalize_warning_bucket_name(cleaned[len(prefix) :])
    if not bucket:
        return cleaned
    return f"{prefix}{bucket}"


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
        return "page_or_layout_artifact"
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
            "`label_policy_adjudication_notes.md`; blended starter-pack artifacts live under "
            "`starter_pack_v1/`; run folders retain `need_to_know_summary.json` plus codex trace "
            "artifacts when available."
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


def _manifest_pass_status(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        status_raw = value.get("status")
        if isinstance(status_raw, str):
            return status_raw.strip()
    return ""


def _diagnostic_value_has_signal(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _load_llm_manifest_recipe_diagnostics(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    pred_run_dir = _resolve_prediction_run_dir(run_dir, run_manifest)
    if pred_run_dir is None:
        return {}

    candidate_paths: list[Path] = []
    raw_llm_dir = pred_run_dir / "raw" / "llm"
    if raw_llm_dir.is_dir():
        candidate_paths.extend(sorted(raw_llm_dir.glob("*/llm_manifest.json")))
        direct_raw_llm_manifest = raw_llm_dir / "llm_manifest.json"
        if direct_raw_llm_manifest.is_file():
            candidate_paths.append(direct_raw_llm_manifest)
    direct_pred_manifest = pred_run_dir / "llm_manifest.json"
    if direct_pred_manifest.is_file():
        candidate_paths.append(direct_pred_manifest)

    diagnostics_by_recipe: dict[str, dict[str, Any]] = {}
    seen_paths: set[Path] = set()
    for manifest_path in candidate_paths:
        resolved = manifest_path.resolve(strict=False)
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)

        try:
            payload = _load_json(manifest_path)
        except Exception:  # noqa: BLE001
            continue
        recipes = payload.get("recipes") if isinstance(payload, dict) else None
        if not isinstance(recipes, dict):
            continue

        for recipe_id_raw, recipe_payload in recipes.items():
            recipe_id = str(recipe_id_raw or "").strip()
            if not recipe_id or not isinstance(recipe_payload, dict):
                continue

            span_loss = (
                recipe_payload.get("pass1_span_loss_metrics")
                if isinstance(recipe_payload.get("pass1_span_loss_metrics"), dict)
                else {}
            )
            transport_audit = (
                recipe_payload.get("transport_audit")
                if isinstance(recipe_payload.get("transport_audit"), dict)
                else {}
            )
            evidence_normalization = (
                recipe_payload.get("evidence_normalization")
                if isinstance(recipe_payload.get("evidence_normalization"), dict)
                else {}
            )
            evidence_stats = (
                evidence_normalization.get("stats")
                if isinstance(evidence_normalization.get("stats"), dict)
                else {}
            )

            extracted = {
                "pass1_status": _manifest_pass_status(recipe_payload.get("pass1")),
                "pass2_status": _manifest_pass_status(recipe_payload.get("pass2")),
                "pass3_status": _manifest_pass_status(recipe_payload.get("pass3")),
                "pass1_clamped_block_loss_count": int(
                    _coerce_int(span_loss.get("clamped_block_loss_count")) or 0
                ),
                "pass1_clamped_block_loss_ratio": _coerce_float(
                    span_loss.get("clamped_block_loss_ratio")
                ),
                "pass2_degradation_reasons": _coerce_str_list(
                    recipe_payload.get("pass2_degradation_reasons")
                ),
                "pass2_degradation_severity": str(
                    recipe_payload.get("pass2_degradation_severity") or ""
                ).strip(),
                "pass2_promotion_policy": str(
                    recipe_payload.get("pass2_promotion_policy") or ""
                ).strip(),
                "pass3_execution_mode": str(
                    recipe_payload.get("pass3_execution_mode") or ""
                ).strip(),
                "pass3_routing_reason": str(
                    recipe_payload.get("pass3_routing_reason") or ""
                ).strip(),
                "pass3_fallback_reason": str(recipe_payload.get("pass3_fallback_reason") or "").strip(),
                "transport_mismatch": _coerce_bool(transport_audit.get("mismatch")),
                "transport_mismatch_reasons": _coerce_str_list(
                    transport_audit.get("mismatch_reasons")
                ),
                "transport_effective_to_payload_coverage_ratio": _coerce_float(
                    transport_audit.get("effective_to_payload_coverage_ratio")
                ),
                "evidence_split_quantity_lines": int(
                    _coerce_int(evidence_stats.get("split_quantity_lines")) or 0
                ),
                "evidence_dropped_page_markers": int(
                    _coerce_int(evidence_stats.get("dropped_page_markers")) or 0
                ),
                "evidence_folded_page_markers": int(
                    _coerce_int(evidence_stats.get("folded_page_markers")) or 0
                ),
            }

            existing = diagnostics_by_recipe.get(recipe_id)
            if existing is None:
                diagnostics_by_recipe[recipe_id] = extracted
                continue

            for key, value in extracted.items():
                if _diagnostic_value_has_signal(value):
                    existing[key] = value

    return diagnostics_by_recipe


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


def _build_run_record_from_existing_run(
    *,
    run_dir: Path,
    top_confusions_limit: int = DEFAULT_TOP_CONFUSIONS,
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

    worst_label_recall = eval_report.get("worst_label_recall")
    if not isinstance(worst_label_recall, dict):
        worst_label_recall = {}

    full_prompt_log_source = _resolve_full_prompt_log_path(run_dir, run_manifest)
    full_prompt_log_status = "not_applicable"
    full_prompt_log_rows = 0
    full_prompt_log_path: str | None = None
    if full_prompt_log_source is not None and full_prompt_log_source.is_file():
        full_prompt_log_rows = len(_iter_jsonl(full_prompt_log_source))
        full_prompt_log_status = "complete"
        try:
            full_prompt_log_path = str(full_prompt_log_source.relative_to(run_dir))
        except ValueError:
            full_prompt_log_path = str(full_prompt_log_source)
    elif codex_enabled:
        full_prompt_log_status = "missing"

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
        output_subdir=run_dir.name,
        config_snapshot=_config_snapshot(run_manifest),
        top_confusions=_top_confusions(
            eval_report.get("confusion"),
            top_k=top_confusions_limit,
        ),
        summary_path=str(run_dir / "need_to_know_summary.json"),
        run_dir=str(run_dir),
        full_prompt_log_status=full_prompt_log_status,
        full_prompt_log_rows=full_prompt_log_rows,
        full_prompt_log_path=full_prompt_log_path,
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


def _prompt_row_identity_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("timestamp_utc") or ""),
        str(row.get("call_id") or ""),
        str(row.get("pass") or ""),
    )


def _prompt_row_pass_name(row: dict[str, Any]) -> str:
    return str(row.get("pass") or "").strip().lower()


def _prompt_row_recipe_id(row: dict[str, Any]) -> str:
    direct = str(row.get("recipe_id") or "").strip()
    if direct:
        return direct
    parsed_response = _parse_json_like(row.get("parsed_response"))
    if isinstance(parsed_response, dict):
        parsed_recipe_id = str(parsed_response.get("recipe_id") or "").strip()
        if parsed_recipe_id:
            return parsed_recipe_id
    return ""


def _warning_buckets(warnings: list[str]) -> list[str]:
    buckets = {
        _prompt_warning_bucket(_normalize_whitespace(message))
        for message in warnings
        if message.strip()
    }
    return sorted(buckets)


def _count_list_entries(value: Any) -> int:
    parsed = _parse_json_like(value)
    if isinstance(parsed, list):
        return len(parsed)
    return 0


def _blocks_from_request_payload(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _block_id_from_row(block: dict[str, Any]) -> str | None:
    for key in ("block_id", "stable_key"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    index_value = _coerce_int(block.get("index"))
    if index_value is not None:
        return f"index:{index_value}"
    return None


def _pass1_selected_blocks(row: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None, int | None]:
    request_payload = _parse_json_like(row.get("request_input_payload"))
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    parsed_response = _parse_json_like(row.get("parsed_response"))
    parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
    blocks_candidate = _blocks_from_request_payload(request_payload, "blocks_candidate")
    if not blocks_candidate:
        return [], None, None

    start = _coerce_int(parsed_response.get("start_block_index"))
    end = _coerce_int(parsed_response.get("end_block_index"))
    excluded_ids = {
        str(value).strip()
        for value in _coerce_str_list(parsed_response.get("excluded_block_ids"))
        if str(value).strip()
    }

    selected: list[dict[str, Any]] = []
    for fallback_index, block in enumerate(blocks_candidate):
        block_index = _coerce_int(block.get("index"))
        if block_index is None:
            block_index = fallback_index
        if start is not None and end is not None and not (start <= block_index <= end):
            continue
        block_id = _block_id_from_row(block)
        if block_id and block_id in excluded_ids:
            continue
        selected.append(block)

    if start is not None and end is not None and end >= start and not selected:
        selected_count = end - start + 1
    else:
        selected_count = len(selected)
    return selected, start, end


def _pass2_input_blocks(row: dict[str, Any]) -> list[dict[str, Any]]:
    request_payload = _parse_json_like(row.get("request_input_payload"))
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    return _blocks_from_request_payload(request_payload, "blocks")


def _pass3_step_count(parsed_response: dict[str, Any]) -> int:
    draft_payload = _parse_json_like(parsed_response.get("draft_v1"))
    if isinstance(draft_payload, dict):
        steps = draft_payload.get("steps")
        if isinstance(steps, list):
            return len(steps)
    steps = parsed_response.get("steps")
    if isinstance(steps, list):
        return len(steps)
    return 0


def _mapping_count(value: Any) -> int:
    parsed = _parse_json_like(value)
    if isinstance(parsed, dict):
        return len(parsed)
    if isinstance(parsed, list):
        return len(parsed)
    return 0


def _to_json_excerpt(value: Any, *, excerpt_limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _excerpt(_normalize_whitespace(value), max_len=excerpt_limit)
    return _excerpt(
        _normalize_whitespace(json.dumps(value, ensure_ascii=False, sort_keys=True)),
        max_len=excerpt_limit,
    )


def _input_excerpt_for_prompt_row(row: dict[str, Any], *, excerpt_limit: int) -> str:
    primary = _first_prompt_block_excerpt(row, excerpt_limit=excerpt_limit)
    if primary:
        return primary
    request_payload = _parse_json_like(row.get("request_input_payload"))
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    canonical_text = request_payload.get("canonical_text")
    if isinstance(canonical_text, str) and canonical_text.strip():
        return _excerpt(_normalize_whitespace(canonical_text), max_len=excerpt_limit)
    for key in ("extracted_instructions", "extracted_ingredients"):
        rows = request_payload.get(key)
        if not isinstance(rows, list):
            continue
        if rows and isinstance(rows[0], dict):
            text = str(rows[0].get("text") or rows[0].get("name") or "").strip()
            if text:
                return _excerpt(_normalize_whitespace(text), max_len=excerpt_limit)
        if rows and isinstance(rows[0], str):
            return _excerpt(_normalize_whitespace(str(rows[0])), max_len=excerpt_limit)
    return ""


def _output_excerpt_for_prompt_row(row: dict[str, Any], *, excerpt_limit: int) -> str:
    parsed_response = _parse_json_like(row.get("parsed_response"))
    parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
    warnings = _coerce_str_list(parsed_response.get("warnings"))
    if warnings:
        return _excerpt(_normalize_whitespace(warnings[0]), max_len=excerpt_limit)

    pass_name = _prompt_row_pass_name(row)
    if pass_name == "pass1":
        title = str(parsed_response.get("title") or "").strip()
        if title:
            return _excerpt(_normalize_whitespace(title), max_len=excerpt_limit)
    if pass_name == "pass2":
        schemaorg_recipe = parsed_response.get("schemaorg_recipe")
        if schemaorg_recipe is not None:
            return _to_json_excerpt(schemaorg_recipe, excerpt_limit=excerpt_limit)
    if pass_name == "pass3":
        draft_payload = _parse_json_like(parsed_response.get("draft_v1"))
        if isinstance(draft_payload, dict):
            recipe_payload = draft_payload.get("recipe")
            title = (
                str(recipe_payload.get("title") or "").strip()
                if isinstance(recipe_payload, dict)
                else ""
            )
            steps = draft_payload.get("steps")
            if title:
                return _excerpt(
                    _normalize_whitespace(f"{title} | steps={len(steps) if isinstance(steps, list) else 0}"),
                    max_len=excerpt_limit,
                )
            return _to_json_excerpt(draft_payload, excerpt_limit=excerpt_limit)
    if parsed_response:
        return _to_json_excerpt(parsed_response, excerpt_limit=excerpt_limit)
    return ""


def _recipe_short_title(
    *,
    recipe_id: str,
    recipe_spans: list[dict[str, Any]],
    pass1_row: dict[str, Any] | None,
) -> str:
    parsed_response = (
        _parse_json_like(pass1_row.get("parsed_response"))
        if isinstance(pass1_row, dict)
        else None
    )
    if isinstance(parsed_response, dict):
        title = str(parsed_response.get("title") or "").strip()
        if title:
            return title
    for span in recipe_spans:
        if str(span.get("recipe_id") or "") != recipe_id:
            continue
        title = str(span.get("title") or "").strip()
        if title:
            return title
    if ":" in recipe_id:
        return recipe_id.rsplit(":", 1)[-1]
    return recipe_id


def _nearest_recipe_id_for_line_index(
    *,
    line_index: int,
    recipe_spans: list[dict[str, Any]],
) -> str | None:
    if not recipe_spans:
        return None
    ranked: list[tuple[int, int, int, str]] = []
    for span in recipe_spans:
        recipe_id = str(span.get("recipe_id") or "").strip()
        if not recipe_id:
            continue
        start = _coerce_int(span.get("start_block_index"))
        end = _coerce_int(span.get("end_block_index"))
        if start is None or end is None:
            continue
        if start <= line_index <= end:
            distance = 0
        else:
            distance = min(abs(line_index - start), abs(line_index - end))
        ranked.append((distance, start, recipe_id.count(":"), recipe_id))
    if not ranked:
        return None
    ranked.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    return ranked[0][3]


def _counter_to_sorted_dict(counter: Counter[str]) -> dict[str, int]:
    return {
        key: count
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    }


def _float_or_zero(value: Any) -> float:
    parsed = _coerce_float(value)
    if parsed is None:
        return 0.0
    return parsed


def _average_float(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _serialize_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def _serialize_bool(value: bool) -> str:
    return "true" if value else "false"


def _serialize_pipe_list(values: list[str]) -> str:
    return "|".join(sorted({value for value in values if value}))


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

    pass_rows_by_recipe: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in sorted(codex_prompt_rows, key=_prompt_row_identity_key):
        pass_name = _prompt_row_pass_name(row)
        if pass_name not in {"pass1", "pass2", "pass3"}:
            continue
        recipe_id = _prompt_row_recipe_id(row)
        if not recipe_id:
            continue
        if pass_name not in pass_rows_by_recipe[recipe_id]:
            pass_rows_by_recipe[recipe_id][pass_name] = row

    run_manifest_path = Path(codex_run.run_dir) / "run_manifest.json"
    run_manifest = _load_json(run_manifest_path) if run_manifest_path.is_file() else {}
    manifest_diagnostics_by_recipe = _load_llm_manifest_recipe_diagnostics(
        run_dir=Path(codex_run.run_dir),
        run_manifest=run_manifest,
    )
    preprocess_rows, preprocess_status = _build_preprocess_trace_failure_rows(
        run_dir=Path(codex_run.run_dir),
        run_manifest=run_manifest,
        full_prompt_rows=codex_prompt_rows,
        excerpt_limit=excerpt_limit,
    )
    outside_span_trace_rows: list[dict[str, Any]] = []
    outside_span_wrong_counts: Counter[str] = Counter()
    outside_span_trace_statuses_by_recipe: dict[str, Counter[str]] = defaultdict(Counter)
    for row in preprocess_rows:
        if str(row.get("span_region") or "") != "outside_active_recipe_span":
            continue
        line_index = _coerce_int(row.get("line_index"))
        if line_index is None:
            continue
        recipe_id = str(row.get("recipe_id") or "").strip()
        if not recipe_id:
            inferred_recipe_id = _nearest_recipe_id_for_line_index(
                line_index=line_index,
                recipe_spans=recipe_spans,
            )
            recipe_id = inferred_recipe_id or "unknown_recipe"
        trace_status = str(row.get("trace_status") or "")
        warning_buckets = _coerce_str_list(row.get("warning_buckets"))
        outside_span_trace_rows.append(
            {
                "source_key": source_key,
                "source_file": source_file,
                "codex_run_id": codex_run.run_id,
                "baseline_run_id": baseline_run.run_id,
                "call_id": row.get("call_id"),
                "recipe_id": recipe_id,
                "line_index": line_index,
                "gold_label": row.get("gold_label"),
                "pred_label": row.get("pred_label"),
                "trace_status": trace_status,
                "warning_buckets": warning_buckets,
                "raw_block_stable_key": row.get("raw_block_stable_key"),
                "raw_block_excerpt": row.get("raw_block_excerpt"),
                "prompt_candidate_block_excerpt": row.get("prompt_candidate_block_excerpt"),
            }
        )
        outside_span_wrong_counts[recipe_id] += 1
        if trace_status:
            outside_span_trace_statuses_by_recipe[recipe_id][trace_status] += 1

    recipe_ids: set[str] = set(per_recipe_metrics.keys())
    recipe_ids.update(pass_rows_by_recipe.keys())
    recipe_ids.update(str(span.get("recipe_id") or "") for span in recipe_spans if span.get("recipe_id"))
    recipe_ids.update(outside_span_wrong_counts.keys())
    recipe_ids.update(manifest_diagnostics_by_recipe.keys())
    recipe_ids.discard("")
    recipe_triage_rows: list[dict[str, Any]] = []
    for recipe_id in sorted(recipe_ids):
        metrics = per_recipe_metrics.get(
            recipe_id,
            {"line_total": 0, "codex_correct": 0, "baseline_correct": 0},
        )
        line_total = int(metrics.get("line_total") or 0)
        codex_correct = int(metrics.get("codex_correct") or 0)
        baseline_correct = int(metrics.get("baseline_correct") or 0)
        codex_accuracy = _rate(codex_correct, line_total)
        baseline_accuracy = _rate(baseline_correct, line_total)
        delta_codex_minus_baseline = _delta(codex_accuracy, baseline_accuracy)

        pass1_row = pass_rows_by_recipe.get(recipe_id, {}).get("pass1")
        pass2_row = pass_rows_by_recipe.get(recipe_id, {}).get("pass2")
        pass3_row = pass_rows_by_recipe.get(recipe_id, {}).get("pass3")
        manifest_diagnostics = manifest_diagnostics_by_recipe.get(recipe_id, {})

        pass1_blocks: list[dict[str, Any]] = []
        pass1_start_block_index: int | None = None
        pass1_end_block_index: int | None = None
        pass1_selected_block_count = 0
        if isinstance(pass1_row, dict):
            pass1_blocks, pass1_start_block_index, pass1_end_block_index = _pass1_selected_blocks(
                pass1_row
            )
            pass1_selected_block_count = len(pass1_blocks)
            if (
                pass1_selected_block_count <= 0
                and pass1_start_block_index is not None
                and pass1_end_block_index is not None
                and pass1_end_block_index >= pass1_start_block_index
            ):
                pass1_selected_block_count = pass1_end_block_index - pass1_start_block_index + 1
        pass1_block_ids = {
            block_id
            for block_id in (_block_id_from_row(block) for block in pass1_blocks)
            if block_id
        }

        pass2_blocks: list[dict[str, Any]] = []
        pass2_warning_count = 0
        pass2_warning_buckets: list[str] = []
        pass2_extracted_ingredient_count = 0
        pass2_extracted_instruction_count = 0
        pass2_input_block_count = 0
        if isinstance(pass2_row, dict):
            pass2_blocks = _pass2_input_blocks(pass2_row)
            pass2_input_block_count = len(pass2_blocks)
            parsed_pass2 = _parse_json_like(pass2_row.get("parsed_response"))
            parsed_pass2 = parsed_pass2 if isinstance(parsed_pass2, dict) else {}
            pass2_warnings = _coerce_str_list(parsed_pass2.get("warnings"))
            pass2_warning_count = len(pass2_warnings)
            pass2_warning_buckets = _warning_buckets(pass2_warnings)
            pass2_extracted_ingredient_count = _count_list_entries(
                parsed_pass2.get("extracted_ingredients")
            )
            pass2_extracted_instruction_count = _count_list_entries(
                parsed_pass2.get("extracted_instructions")
            )
        pass2_block_ids = {
            block_id
            for block_id in (_block_id_from_row(block) for block in pass2_blocks)
            if block_id
        }
        if pass1_block_ids and pass2_block_ids:
            pass1_vs_pass2_missing_block_count = len(pass1_block_ids - pass2_block_ids)
            pass1_vs_pass2_extra_block_count = len(pass2_block_ids - pass1_block_ids)
        else:
            pass1_vs_pass2_missing_block_count = max(
                pass1_selected_block_count - pass2_input_block_count,
                0,
            )
            pass1_vs_pass2_extra_block_count = max(
                pass2_input_block_count - pass1_selected_block_count,
                0,
            )

        pass3_step_count = 0
        pass3_mapping_count = 0
        pass3_empty_mapping = False
        pass3_warning_count = 0
        pass3_warning_buckets: list[str] = []
        if isinstance(pass3_row, dict):
            parsed_pass3 = _parse_json_like(pass3_row.get("parsed_response"))
            parsed_pass3 = parsed_pass3 if isinstance(parsed_pass3, dict) else {}
            pass3_step_count = _pass3_step_count(parsed_pass3)
            pass3_mapping_count = _mapping_count(parsed_pass3.get("ingredient_step_mapping"))
            pass3_empty_mapping = _is_empty_mapping_value(parsed_pass3.get("ingredient_step_mapping"))
            pass3_warnings = _coerce_str_list(parsed_pass3.get("warnings"))
            pass3_warning_count = len(pass3_warnings)
            pass3_warning_buckets = _warning_buckets(pass3_warnings)

        outside_span_status_counter = outside_span_trace_statuses_by_recipe.get(recipe_id, Counter())
        outside_span_trace_status_top = ""
        if outside_span_status_counter:
            outside_span_trace_status_top = sorted(
                outside_span_status_counter.items(),
                key=lambda item: (-item[1], item[0]),
            )[0][0]

        pass1_status = str(manifest_diagnostics.get("pass1_status") or "")
        pass2_status = str(manifest_diagnostics.get("pass2_status") or "")
        pass3_status = str(manifest_diagnostics.get("pass3_status") or "")
        pass1_clamped_block_loss_count = int(
            _coerce_int(manifest_diagnostics.get("pass1_clamped_block_loss_count")) or 0
        )
        pass1_clamped_block_loss_ratio = _coerce_float(
            manifest_diagnostics.get("pass1_clamped_block_loss_ratio")
        )
        pass2_degradation_reasons = [
            _normalize_warning_bucket_reason(reason)
            for reason in _coerce_str_list(manifest_diagnostics.get("pass2_degradation_reasons"))
        ]
        pass2_degradation_severity = str(
            manifest_diagnostics.get("pass2_degradation_severity") or ""
        ).strip()
        pass2_promotion_policy = str(
            manifest_diagnostics.get("pass2_promotion_policy") or ""
        ).strip()
        pass3_execution_mode = str(
            manifest_diagnostics.get("pass3_execution_mode") or ""
        ).strip()
        pass3_routing_reason = str(
            manifest_diagnostics.get("pass3_routing_reason") or ""
        ).strip()
        pass3_fallback_reason = str(manifest_diagnostics.get("pass3_fallback_reason") or "")
        transport_mismatch = _coerce_bool(manifest_diagnostics.get("transport_mismatch"))
        transport_mismatch_reasons = _coerce_str_list(
            manifest_diagnostics.get("transport_mismatch_reasons")
        )
        transport_effective_to_payload_coverage_ratio = _coerce_float(
            manifest_diagnostics.get("transport_effective_to_payload_coverage_ratio")
        )
        evidence_split_quantity_lines = int(
            _coerce_int(manifest_diagnostics.get("evidence_split_quantity_lines")) or 0
        )
        evidence_dropped_page_markers = int(
            _coerce_int(manifest_diagnostics.get("evidence_dropped_page_markers")) or 0
        )
        evidence_folded_page_markers = int(
            _coerce_int(manifest_diagnostics.get("evidence_folded_page_markers")) or 0
        )

        line_total_effective = line_total if line_total > 0 else pass1_selected_block_count
        short_title = _recipe_short_title(
            recipe_id=recipe_id,
            recipe_spans=recipe_spans,
            pass1_row=pass1_row,
        )
        recipe_triage_rows.append(
            {
                "source_key": source_key,
                "source_file": source_file,
                "codex_run_id": codex_run.run_id,
                "baseline_run_id": baseline_run.run_id,
                "selection_hint_preprocess_status": preprocess_status,
                "recipe_id": recipe_id,
                "short_title": short_title,
                "line_total": line_total_effective,
                "changed_lines_codex_vs_baseline": int(recipe_flip_counts.get(recipe_id, 0)),
                "codex_accuracy": codex_accuracy,
                "baseline_accuracy": baseline_accuracy,
                "delta_codex_minus_baseline": delta_codex_minus_baseline,
                "pass1_call_id": str(pass1_row.get("call_id") or "") if isinstance(pass1_row, dict) else "",
                "pass2_call_id": str(pass2_row.get("call_id") or "") if isinstance(pass2_row, dict) else "",
                "pass3_call_id": str(pass3_row.get("call_id") or "") if isinstance(pass3_row, dict) else "",
                "pass1_start_block_index": pass1_start_block_index,
                "pass1_end_block_index": pass1_end_block_index,
                "pass1_selected_block_count": pass1_selected_block_count,
                "pass2_input_block_count": pass2_input_block_count,
                "pass1_vs_pass2_missing_block_count": pass1_vs_pass2_missing_block_count,
                "pass1_vs_pass2_extra_block_count": pass1_vs_pass2_extra_block_count,
                "pass2_warning_count": pass2_warning_count,
                "pass2_warning_buckets": pass2_warning_buckets,
                "pass2_extracted_ingredient_count": pass2_extracted_ingredient_count,
                "pass2_extracted_instruction_count": pass2_extracted_instruction_count,
                "pass3_step_count": pass3_step_count,
                "pass3_mapping_count": pass3_mapping_count,
                "pass3_empty_mapping": pass3_empty_mapping,
                "pass3_warning_count": pass3_warning_count,
                "pass3_warning_buckets": pass3_warning_buckets,
                "pass1_status": pass1_status,
                "pass2_status": pass2_status,
                "pass3_status": pass3_status,
                "pass1_clamped_block_loss_count": pass1_clamped_block_loss_count,
                "pass1_clamped_block_loss_ratio": pass1_clamped_block_loss_ratio,
                "pass2_degradation_reasons": pass2_degradation_reasons,
                "pass2_degradation_severity": pass2_degradation_severity,
                "pass2_promotion_policy": pass2_promotion_policy,
                "pass3_execution_mode": pass3_execution_mode,
                "pass3_routing_reason": pass3_routing_reason,
                "pass3_fallback_reason": pass3_fallback_reason,
                "transport_mismatch": transport_mismatch,
                "transport_mismatch_reasons": transport_mismatch_reasons,
                "transport_effective_to_payload_coverage_ratio": (
                    transport_effective_to_payload_coverage_ratio
                ),
                "evidence_split_quantity_lines": evidence_split_quantity_lines,
                "evidence_dropped_page_markers": evidence_dropped_page_markers,
                "evidence_folded_page_markers": evidence_folded_page_markers,
                "outside_span_wrong_line_count": int(outside_span_wrong_counts.get(recipe_id, 0)),
                "outside_span_trace_status_top": outside_span_trace_status_top,
                "raw_block_window_excerpt": _input_excerpt_for_prompt_row(
                    pass1_row,
                    excerpt_limit=excerpt_limit,
                )
                if isinstance(pass1_row, dict)
                else "",
            }
        )

    call_inventory_rows: list[dict[str, Any]] = []
    pass_rank = {"pass1": 1, "pass2": 2, "pass3": 3}
    for row in sorted(codex_prompt_rows, key=_prompt_row_identity_key):
        pass_name = _prompt_row_pass_name(row)
        if pass_name not in {"pass1", "pass2", "pass3"}:
            continue
        parsed_response = _parse_json_like(row.get("parsed_response"))
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
        warnings = _coerce_str_list(parsed_response.get("warnings"))
        warning_buckets = _warning_buckets(warnings)

        input_block_count = 0
        extracted_ingredient_count = 0
        extracted_instruction_count = 0
        step_count = 0
        mapping_count = 0
        if pass_name == "pass1":
            pass1_blocks, start_block_index, end_block_index = _pass1_selected_blocks(row)
            input_block_count = len(pass1_blocks)
            if (
                input_block_count <= 0
                and start_block_index is not None
                and end_block_index is not None
                and end_block_index >= start_block_index
            ):
                input_block_count = end_block_index - start_block_index + 1
        elif pass_name == "pass2":
            input_block_count = len(_pass2_input_blocks(row))
            extracted_ingredient_count = _count_list_entries(parsed_response.get("extracted_ingredients"))
            extracted_instruction_count = _count_list_entries(
                parsed_response.get("extracted_instructions")
            )
        elif pass_name == "pass3":
            step_count = _pass3_step_count(parsed_response)
            mapping_count = _mapping_count(parsed_response.get("ingredient_step_mapping"))

        call_inventory_rows.append(
            {
                "run_id": codex_run.run_id,
                "source_key": source_key,
                "recipe_id": _prompt_row_recipe_id(row),
                "pass": pass_name,
                "call_id": str(row.get("call_id") or ""),
                "timestamp_utc": str(row.get("timestamp_utc") or ""),
                "model": str(row.get("model") or ""),
                "input_block_count": input_block_count,
                "warning_count": len(warnings),
                "warning_buckets": warning_buckets,
                "extracted_ingredient_count": extracted_ingredient_count,
                "extracted_instruction_count": extracted_instruction_count,
                "step_count": step_count,
                "mapping_count": mapping_count,
                "input_excerpt": _input_excerpt_for_prompt_row(row, excerpt_limit=excerpt_limit),
                "output_excerpt": _output_excerpt_for_prompt_row(row, excerpt_limit=excerpt_limit),
                "_pass_rank": pass_rank.get(pass_name, 99),
            }
        )
    call_inventory_rows.sort(
        key=lambda row: (
            str(row.get("recipe_id") or ""),
            int(row.get("_pass_rank") or 99),
            str(row.get("call_id") or ""),
            str(row.get("timestamp_utc") or ""),
        )
    )
    for row in call_inventory_rows:
        row.pop("_pass_rank", None)

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
        recipe_triage_rows=recipe_triage_rows,
        call_inventory_rows=call_inventory_rows,
        outside_span_trace_rows=outside_span_trace_rows,
    )


def _build_comparison_summary(
    *,
    records: list[RunRecord],
    excerpt_limit: int,
    targeted_prompt_case_limit: int,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    by_source: dict[str, list[RunRecord]] = defaultdict(list)
    for record in records:
        by_source[record.source_key].append(record)

    pairs: list[dict[str, Any]] = []
    unpaired_codex: list[dict[str, Any]] = []
    unpaired_baseline: list[dict[str, Any]] = []
    changed_line_rows: list[dict[str, Any]] = []
    pair_breakdown_rows: list[dict[str, Any]] = []
    targeted_prompt_case_rows: list[dict[str, Any]] = []
    recipe_triage_rows: list[dict[str, Any]] = []
    call_inventory_rows: list[dict[str, Any]] = []
    outside_span_trace_rows: list[dict[str, Any]] = []

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
                recipe_triage_rows.extend(pair_diagnostics.recipe_triage_rows)
                call_inventory_rows.extend(pair_diagnostics.call_inventory_rows)
                outside_span_trace_rows.extend(pair_diagnostics.outside_span_trace_rows)
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
    return (
        summary,
        changed_line_rows,
        pair_breakdown_rows,
        targeted_prompt_case_rows,
        recipe_triage_rows,
        call_inventory_rows,
        outside_span_trace_rows,
    )


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


def _aggregate_region_accuracy(
    pair_breakdown_rows: list[dict[str, Any]],
) -> tuple[float | None, float | None, float | None]:
    totals: dict[str, dict[str, int]] = {
        "inside_active_recipe_span": {"line_total": 0, "codex_correct": 0},
        "outside_active_recipe_span": {"line_total": 0, "codex_correct": 0},
    }
    for pair_row in pair_breakdown_rows:
        region_rows = pair_row.get("region_breakdown")
        if not isinstance(region_rows, list):
            continue
        for region_row in region_rows:
            if not isinstance(region_row, dict):
                continue
            region = str(region_row.get("region") or "")
            if region not in totals:
                continue
            totals[region]["line_total"] += int(_coerce_int(region_row.get("line_total")) or 0)
            totals[region]["codex_correct"] += int(_coerce_int(region_row.get("codex_correct")) or 0)

    inside_accuracy = _rate(
        totals["inside_active_recipe_span"]["codex_correct"],
        totals["inside_active_recipe_span"]["line_total"],
    )
    outside_accuracy = _rate(
        totals["outside_active_recipe_span"]["codex_correct"],
        totals["outside_active_recipe_span"]["line_total"],
    )
    if inside_accuracy is None or outside_accuracy is None:
        gap = None
    else:
        gap = inside_accuracy - outside_accuracy
    return inside_accuracy, outside_accuracy, gap


def _aggregate_confusion_deltas(
    comparison_summary: dict[str, Any],
    *,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    pairs = comparison_summary.get("pairs")
    if not isinstance(pairs, list):
        return []
    counter: Counter[tuple[str, str]] = Counter()
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        confusion = pair.get("confusion_matrix")
        if not isinstance(confusion, dict):
            continue
        delta_matrix = confusion.get("delta_codex_minus_baseline")
        if not isinstance(delta_matrix, dict):
            continue
        for gold_label, pred_counts in delta_matrix.items():
            if not isinstance(gold_label, str) or not isinstance(pred_counts, dict):
                continue
            for pred_label, count_raw in pred_counts.items():
                if not isinstance(pred_label, str):
                    continue
                count = _coerce_int(count_raw)
                if count is None or count == 0:
                    continue
                counter[(gold_label, pred_label)] += count
    rows = [
        {"gold_label": gold_label, "pred_label": pred_label, "delta_count": count}
        for (gold_label, pred_label), count in counter.items()
    ]
    rows.sort(
        key=lambda row: (
            -abs(int(row.get("delta_count") or 0)),
            str(row.get("gold_label") or ""),
            str(row.get("pred_label") or ""),
        )
    )
    return rows[:top_k]


def _build_warning_and_trace_summary(
    *,
    call_inventory_rows: list[dict[str, Any]],
    recipe_triage_rows: list[dict[str, Any]],
    outside_span_trace_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    warnings_by_pass: Counter[str] = Counter()
    warning_buckets: Counter[str] = Counter()
    for row in call_inventory_rows:
        pass_name = str(row.get("pass") or "")
        warnings_by_pass[pass_name] += int(_coerce_int(row.get("warning_count")) or 0)
        for bucket in _coerce_str_list(row.get("warning_buckets")):
            warning_buckets[bucket] += 1

    outside_span_trace_status_counts: Counter[str] = Counter()
    outside_span_warning_bucket_counts: Counter[str] = Counter()
    for row in outside_span_trace_rows:
        trace_status = str(row.get("trace_status") or "")
        if trace_status:
            outside_span_trace_status_counts[trace_status] += 1
        for bucket in _coerce_str_list(row.get("warning_buckets")):
            outside_span_warning_bucket_counts[bucket] += 1

    pass3_empty_mapping_count = sum(
        1 for row in recipe_triage_rows if bool(row.get("pass3_empty_mapping"))
    )
    pass2_degraded_recipe_count = sum(
        1 for row in recipe_triage_rows if _coerce_str_list(row.get("pass2_degradation_reasons"))
    )
    pass3_fallback_recipe_count = sum(
        1
        for row in recipe_triage_rows
        if str(row.get("pass3_fallback_reason") or "").strip()
    )
    transport_mismatch_recipe_count = sum(
        1 for row in recipe_triage_rows if _coerce_bool(row.get("transport_mismatch")) is True
    )
    pass1_clamped_loss_recipe_count = sum(
        1
        for row in recipe_triage_rows
        if int(_coerce_int(row.get("pass1_clamped_block_loss_count")) or 0) > 0
    )
    pass1_status_counts: Counter[str] = Counter()
    pass2_status_counts: Counter[str] = Counter()
    pass3_status_counts: Counter[str] = Counter()
    pass2_severity_counts: Counter[str] = Counter()
    pass3_execution_mode_counts: Counter[str] = Counter()
    for row in recipe_triage_rows:
        pass1_status = str(row.get("pass1_status") or "").strip() or "missing"
        pass2_status = str(row.get("pass2_status") or "").strip() or "missing"
        pass3_status = str(row.get("pass3_status") or "").strip() or "missing"
        pass2_severity = str(row.get("pass2_degradation_severity") or "").strip() or "missing"
        pass3_execution_mode = str(row.get("pass3_execution_mode") or "").strip() or "missing"
        pass1_status_counts[pass1_status] += 1
        pass2_status_counts[pass2_status] += 1
        pass3_status_counts[pass3_status] += 1
        pass2_severity_counts[pass2_severity] += 1
        pass3_execution_mode_counts[pass3_execution_mode] += 1
    return {
        "warnings_by_pass": _counter_to_sorted_dict(warnings_by_pass),
        "warning_buckets": _counter_to_sorted_dict(warning_buckets),
        "pass3_empty_mapping_count": pass3_empty_mapping_count,
        "pass2_degraded_recipe_count": pass2_degraded_recipe_count,
        "pass3_fallback_recipe_count": pass3_fallback_recipe_count,
        "transport_mismatch_recipe_count": transport_mismatch_recipe_count,
        "pass1_clamped_loss_recipe_count": pass1_clamped_loss_recipe_count,
        "pass_status_counts": {
            "pass1": _counter_to_sorted_dict(pass1_status_counts),
            "pass2": _counter_to_sorted_dict(pass2_status_counts),
            "pass3": _counter_to_sorted_dict(pass3_status_counts),
        },
        "pass2_degradation_severity_counts": _counter_to_sorted_dict(pass2_severity_counts),
        "pass3_execution_mode_counts": _counter_to_sorted_dict(
            pass3_execution_mode_counts
        ),
        "outside_span_wrong_line_count": len(outside_span_trace_rows),
        "outside_span_trace_status_counts": _counter_to_sorted_dict(outside_span_trace_status_counts),
        "outside_span_warning_bucket_counts": _counter_to_sorted_dict(
            outside_span_warning_bucket_counts
        ),
    }


def _recipe_row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("source_key") or ""),
        str(row.get("codex_run_id") or ""),
        str(row.get("recipe_id") or ""),
    )


def _sort_recipe_rows_for_metric(
    rows: list[dict[str, Any]],
    *,
    metric_key: str,
) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -int(_coerce_int(row.get(metric_key)) or 0),
            -abs(_float_or_zero(row.get("delta_codex_minus_baseline"))),
            str(row.get("recipe_id") or ""),
        ),
    )


def _select_starter_pack_recipe_cases(
    recipe_triage_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    ordered_keys: list[tuple[str, str, str]] = []

    def reason_count(reason: str) -> int:
        return sum(
            1
            for entry in ordered_keys
            if reason in str(selected_by_key[entry].get("selection_reason") or "")
        )

    def add_rows(rows: list[dict[str, Any]], *, limit: int, reason: str) -> None:
        for row in rows:
            key = _recipe_row_key(row)
            if key not in selected_by_key:
                selected_by_key[key] = dict(row)
                selected_by_key[key]["selection_reason"] = reason
                ordered_keys.append(key)
            else:
                existing = str(selected_by_key[key].get("selection_reason") or "")
                if reason not in existing.split(", "):
                    selected_by_key[key]["selection_reason"] = (
                        f"{existing}, {reason}" if existing else reason
                    )
            if len(ordered_keys) >= 10:
                return
            if reason_count(reason) >= limit:
                return

    top_changed = _sort_recipe_rows_for_metric(
        recipe_triage_rows,
        metric_key="changed_lines_codex_vs_baseline",
    )
    add_rows(
        top_changed,
        limit=STARTER_PACK_SELECTION_POLICY["top_changed_lines"],
        reason="top_changed_lines",
    )

    top_block_loss = _sort_recipe_rows_for_metric(
        recipe_triage_rows,
        metric_key="pass1_vs_pass2_missing_block_count",
    )
    add_rows(
        top_block_loss,
        limit=STARTER_PACK_SELECTION_POLICY["top_block_loss"],
        reason="top_block_loss",
    )

    empty_mapping_candidates = [
        row
        for row in recipe_triage_rows
        if bool(row.get("pass3_empty_mapping"))
        and (
            int(_coerce_int(row.get("pass1_selected_block_count")) or 0) >= 8
            or int(_coerce_int(row.get("pass2_warning_count")) or 0) >= 2
            or int(_coerce_int(row.get("pass2_extracted_instruction_count")) or 0) == 0
        )
    ]
    empty_mapping_candidates = _sort_recipe_rows_for_metric(
        empty_mapping_candidates,
        metric_key="pass3_empty_mapping",
    )
    add_rows(
        empty_mapping_candidates,
        limit=STARTER_PACK_SELECTION_POLICY["top_empty_mapping"],
        reason="top_empty_mapping_upstream_evidence",
    )

    outside_candidates = _sort_recipe_rows_for_metric(
        recipe_triage_rows,
        metric_key="outside_span_wrong_line_count",
    )
    outside_candidates = [
        row for row in outside_candidates if int(_coerce_int(row.get("outside_span_wrong_line_count")) or 0) > 0
    ]
    add_rows(
        outside_candidates,
        limit=STARTER_PACK_SELECTION_POLICY["outside_span_case"],
        reason="outside_span_contamination",
    )

    healthy_controls = [
        row
        for row in recipe_triage_rows
        if int(_coerce_int(row.get("pass1_vs_pass2_missing_block_count")) or 0) == 0
        and not bool(row.get("pass3_empty_mapping"))
    ]
    healthy_controls.sort(
        key=lambda row: (
            -_float_or_zero(row.get("codex_accuracy")),
            str(row.get("recipe_id") or ""),
        )
    )
    add_rows(
        healthy_controls,
        limit=STARTER_PACK_SELECTION_POLICY["healthy_control"],
        reason="healthy_control",
    )

    if len(ordered_keys) < 6:
        for row in top_changed:
            key = _recipe_row_key(row)
            if key in selected_by_key:
                continue
            selected_by_key[key] = dict(row)
            selected_by_key[key]["selection_reason"] = "highest_remaining_signal"
            ordered_keys.append(key)
            if len(ordered_keys) >= min(10, len(recipe_triage_rows)):
                break
            if len(ordered_keys) >= 6:
                break

    return [selected_by_key[key] for key in ordered_keys[:10]]


def _group_changed_lines_by_recipe(
    changed_line_rows: list[dict[str, Any]],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in changed_line_rows:
        recipe_id = str(row.get("recipe_id") or "").strip()
        if not recipe_id:
            continue
        key = (
            str(row.get("source_key") or ""),
            str(row.get("codex_run_id") or ""),
            recipe_id,
        )
        grouped[key].append(row)
    for key in grouped:
        grouped[key].sort(
            key=lambda row: (
                int(_coerce_int(row.get("line_index")) or 0),
                str(row.get("gold_label") or ""),
            )
        )
    return grouped


def _bridge_anomaly_summary(row: dict[str, Any]) -> str:
    chunks = [
        f"missing_blocks={int(_coerce_int(row.get('pass1_vs_pass2_missing_block_count')) or 0)}",
        f"extra_blocks={int(_coerce_int(row.get('pass1_vs_pass2_extra_block_count')) or 0)}",
        f"pass2_warnings={int(_coerce_int(row.get('pass2_warning_count')) or 0)}",
        f"pass3_empty_mapping={_serialize_bool(bool(row.get('pass3_empty_mapping')))}",
    ]
    clamped_loss = int(_coerce_int(row.get("pass1_clamped_block_loss_count")) or 0)
    if clamped_loss > 0:
        chunks.append(f"pass1_clamped_block_loss={clamped_loss}")
    degradation_reasons = _serialize_pipe_list(_coerce_str_list(row.get("pass2_degradation_reasons")))
    if degradation_reasons:
        chunks.append(f"pass2_degradation_reasons={degradation_reasons}")
    pass2_severity = str(row.get("pass2_degradation_severity") or "").strip()
    if pass2_severity:
        chunks.append(f"pass2_severity={pass2_severity}")
    pass2_policy = str(row.get("pass2_promotion_policy") or "").strip()
    if pass2_policy:
        chunks.append(f"pass2_policy={pass2_policy}")
    pass3_execution_mode = str(row.get("pass3_execution_mode") or "").strip()
    if pass3_execution_mode:
        chunks.append(f"pass3_mode={pass3_execution_mode}")
    if str(row.get("pass3_fallback_reason") or "").strip():
        chunks.append("pass3_fallback=true")
    if _coerce_bool(row.get("transport_mismatch")) is True:
        mismatch_reasons = _serialize_pipe_list(_coerce_str_list(row.get("transport_mismatch_reasons")))
        if mismatch_reasons:
            chunks.append(f"transport_mismatch={mismatch_reasons}")
        else:
            chunks.append("transport_mismatch=true")
    outside_count = int(_coerce_int(row.get("outside_span_wrong_line_count")) or 0)
    if outside_count > 0:
        chunks.append(f"outside_span_wrong_lines={outside_count}")
    return ", ".join(chunks)


def _warning_summary_for_recipe(row: dict[str, Any]) -> str:
    chunks: list[str] = []
    pass2_warning_count = int(_coerce_int(row.get("pass2_warning_count")) or 0)
    if pass2_warning_count > 0:
        chunks.append(
            f"pass2({pass2_warning_count}): {_serialize_pipe_list(_coerce_str_list(row.get('pass2_warning_buckets')))}"
        )
    pass2_degradation_reasons = _serialize_pipe_list(_coerce_str_list(row.get("pass2_degradation_reasons")))
    if pass2_degradation_reasons:
        chunks.append(f"pass2_degradation: {pass2_degradation_reasons}")
    pass2_severity = str(row.get("pass2_degradation_severity") or "").strip()
    if pass2_severity:
        chunks.append(f"pass2_severity: {pass2_severity}")
    pass2_policy = str(row.get("pass2_promotion_policy") or "").strip()
    if pass2_policy:
        chunks.append(f"pass2_policy: {pass2_policy}")
    pass3_warning_count = int(_coerce_int(row.get("pass3_warning_count")) or 0)
    if pass3_warning_count > 0:
        chunks.append(
            f"pass3({pass3_warning_count}): {_serialize_pipe_list(_coerce_str_list(row.get('pass3_warning_buckets')))}"
        )
    pass3_execution_mode = str(row.get("pass3_execution_mode") or "").strip()
    if pass3_execution_mode:
        chunks.append(f"pass3_mode: {pass3_execution_mode}")
    if str(row.get("pass3_fallback_reason") or "").strip():
        chunks.append("pass3_fallback: yes")
    return "; ".join(chunks) if chunks else "none"


def _build_selected_recipe_packets(
    *,
    selected_recipe_rows: list[dict[str, Any]],
    changed_line_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped_changed_lines = _group_changed_lines_by_recipe(changed_line_rows)
    packets: list[dict[str, Any]] = []
    for row in selected_recipe_rows:
        key = _recipe_row_key(row)
        changed_rows = grouped_changed_lines.get(key, [])
        changed_examples = []
        for changed_row in changed_rows[:8]:
            changed_examples.append(
                {
                    "line_index": int(_coerce_int(changed_row.get("line_index")) or 0),
                    "gold_label": str(changed_row.get("gold_label") or ""),
                    "baseline_pred": str(changed_row.get("vanilla_pred") or ""),
                    "codex_pred": str(changed_row.get("codex_pred") or ""),
                    "current_line": str(changed_row.get("current_line") or ""),
                    "previous_line": str(changed_row.get("previous_line") or ""),
                    "next_line": str(changed_row.get("next_line") or ""),
                }
            )

        pass1_summary = {
            "call_id": str(row.get("pass1_call_id") or ""),
            "start_block_index": _coerce_int(row.get("pass1_start_block_index")),
            "end_block_index": _coerce_int(row.get("pass1_end_block_index")),
            "selected_block_count": int(_coerce_int(row.get("pass1_selected_block_count")) or 0),
            "status": str(row.get("pass1_status") or ""),
            "clamped_block_loss_count": int(
                _coerce_int(row.get("pass1_clamped_block_loss_count")) or 0
            ),
            "clamped_block_loss_ratio": _coerce_float(row.get("pass1_clamped_block_loss_ratio")),
            "missing_block_count_vs_pass2": int(
                _coerce_int(row.get("pass1_vs_pass2_missing_block_count")) or 0
            ),
            "extra_block_count_vs_pass2": int(
                _coerce_int(row.get("pass1_vs_pass2_extra_block_count")) or 0
            ),
        }
        pass2_summary = {
            "call_id": str(row.get("pass2_call_id") or ""),
            "status": str(row.get("pass2_status") or ""),
            "input_block_count": int(_coerce_int(row.get("pass2_input_block_count")) or 0),
            "warning_count": int(_coerce_int(row.get("pass2_warning_count")) or 0),
            "warning_buckets": _coerce_str_list(row.get("pass2_warning_buckets")),
            "degradation_reasons": _coerce_str_list(row.get("pass2_degradation_reasons")),
            "degradation_severity": str(row.get("pass2_degradation_severity") or ""),
            "promotion_policy": str(row.get("pass2_promotion_policy") or ""),
            "extracted_ingredient_count": int(
                _coerce_int(row.get("pass2_extracted_ingredient_count")) or 0
            ),
            "extracted_instruction_count": int(
                _coerce_int(row.get("pass2_extracted_instruction_count")) or 0
            ),
        }
        pass3_summary = {
            "call_id": str(row.get("pass3_call_id") or ""),
            "status": str(row.get("pass3_status") or ""),
            "step_count": int(_coerce_int(row.get("pass3_step_count")) or 0),
            "mapping_count": int(_coerce_int(row.get("pass3_mapping_count")) or 0),
            "empty_mapping": bool(row.get("pass3_empty_mapping")),
            "warning_count": int(_coerce_int(row.get("pass3_warning_count")) or 0),
            "warning_buckets": _coerce_str_list(row.get("pass3_warning_buckets")),
            "execution_mode": str(row.get("pass3_execution_mode") or ""),
            "routing_reason": str(row.get("pass3_routing_reason") or ""),
            "fallback_reason": str(row.get("pass3_fallback_reason") or ""),
        }
        transport_summary = {
            "mismatch": _coerce_bool(row.get("transport_mismatch")),
            "mismatch_reasons": _coerce_str_list(row.get("transport_mismatch_reasons")),
            "effective_to_payload_coverage_ratio": _coerce_float(
                row.get("transport_effective_to_payload_coverage_ratio")
            ),
        }
        evidence_normalization_summary = {
            "split_quantity_lines": int(
                _coerce_int(row.get("evidence_split_quantity_lines")) or 0
            ),
            "dropped_page_markers": int(
                _coerce_int(row.get("evidence_dropped_page_markers")) or 0
            ),
            "folded_page_markers": int(
                _coerce_int(row.get("evidence_folded_page_markers")) or 0
            ),
        }

        packets.append(
            {
                "selection_reason": str(row.get("selection_reason") or ""),
                "recipe_id": str(row.get("recipe_id") or ""),
                "short_title": str(row.get("short_title") or ""),
                "changed_lines_codex_vs_baseline": int(
                    _coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0
                ),
                "bridge_anomaly_summary": _bridge_anomaly_summary(row),
                "warning_summary": _warning_summary_for_recipe(row),
                "pass1_summary": pass1_summary,
                "pass2_summary": pass2_summary,
                "pass3_summary": pass3_summary,
                "transport_summary": transport_summary,
                "evidence_normalization_summary": evidence_normalization_summary,
                "changed_line_examples": changed_examples,
                "raw_block_window_excerpt": str(row.get("raw_block_window_excerpt") or ""),
            }
        )
    return packets


def _render_starter_pack_casebook(packets: list[dict[str, Any]]) -> str:
    lines = [
        "# Starter Pack Casebook",
        "",
        "Deterministic selected cases for first-pass benchmark and bridge diagnosis.",
        "",
    ]
    if not packets:
        lines.append("No recipe cases were selected.")
        lines.append("")
        return "\n".join(lines)

    for index, packet in enumerate(packets, start=1):
        lines.extend(
            [
                f"## Case {index}: {packet.get('recipe_id')}",
                f"- selection_reason: {packet.get('selection_reason')}",
                f"- short_title: {packet.get('short_title')}",
                (
                    "- changed_lines_codex_vs_baseline: "
                    f"{packet.get('changed_lines_codex_vs_baseline')}"
                ),
                f"- bridge_anomaly_summary: {packet.get('bridge_anomaly_summary')}",
                f"- warning_summary: {packet.get('warning_summary')}",
                "",
                "### Pass Excerpts",
                (
                    "- pass1: "
                    f"call_id={packet.get('pass1_summary', {}).get('call_id')} "
                    f"status={packet.get('pass1_summary', {}).get('status')} "
                    f"selected_block_count={packet.get('pass1_summary', {}).get('selected_block_count')} "
                    f"clamped_block_loss={packet.get('pass1_summary', {}).get('clamped_block_loss_count')}"
                ),
                (
                    "- pass2: "
                    f"call_id={packet.get('pass2_summary', {}).get('call_id')} "
                    f"status={packet.get('pass2_summary', {}).get('status')} "
                    f"input_block_count={packet.get('pass2_summary', {}).get('input_block_count')} "
                    f"warning_count={packet.get('pass2_summary', {}).get('warning_count')} "
                    f"severity={packet.get('pass2_summary', {}).get('degradation_severity')} "
                    f"policy={packet.get('pass2_summary', {}).get('promotion_policy')} "
                    "degradation_reasons="
                    f"{_serialize_pipe_list(packet.get('pass2_summary', {}).get('degradation_reasons') or []) or 'none'}"
                ),
                (
                    "- pass3: "
                    f"call_id={packet.get('pass3_summary', {}).get('call_id')} "
                    f"status={packet.get('pass3_summary', {}).get('status')} "
                    f"mode={packet.get('pass3_summary', {}).get('execution_mode')} "
                    f"route={packet.get('pass3_summary', {}).get('routing_reason')} "
                    f"mapping_count={packet.get('pass3_summary', {}).get('mapping_count')} "
                    f"empty_mapping={packet.get('pass3_summary', {}).get('empty_mapping')} "
                    "fallback="
                    f"{'yes' if str(packet.get('pass3_summary', {}).get('fallback_reason') or '').strip() else 'no'}"
                ),
                (
                    "- transport: "
                    f"mismatch={packet.get('transport_summary', {}).get('mismatch')} "
                    "reasons="
                    f"{_serialize_pipe_list(packet.get('transport_summary', {}).get('mismatch_reasons') or []) or 'none'} "
                    "coverage_ratio="
                    f"{_serialize_float(_coerce_float(packet.get('transport_summary', {}).get('effective_to_payload_coverage_ratio')))}"
                ),
                "",
            ]
        )
        raw_excerpt = str(packet.get("raw_block_window_excerpt") or "").strip()
        if raw_excerpt:
            lines.extend(
                [
                    "### Raw Block Window Excerpt",
                    "",
                    raw_excerpt,
                    "",
                ]
            )

        changed_examples = packet.get("changed_line_examples")
        changed_rows = changed_examples if isinstance(changed_examples, list) else []
        lines.append("### Changed Canonical Lines")
        lines.append("")
        if not changed_rows:
            lines.append("No changed canonical lines recorded for this recipe in this pair.")
            lines.append("")
            continue
        for changed_row in changed_rows[:8]:
            if not isinstance(changed_row, dict):
                continue
            lines.append(
                (
                    f"- line {int(_coerce_int(changed_row.get('line_index')) or 0)} | "
                    f"gold={changed_row.get('gold_label')} | "
                    f"baseline={changed_row.get('baseline_pred')} | "
                    f"codex={changed_row.get('codex_pred')} | "
                    f"text={_excerpt(str(changed_row.get('current_line') or ''), max_len=260)}"
                )
            )
        lines.append("")
    return "\n".join(lines)


def _render_starter_pack_label_policy() -> str:
    lines = [
        "# Label Policy",
        "",
        "## Policy Notes",
        "",
        "- Treat labels as canonical line-space classes from benchmark evaluation artifacts.",
        "- Prefer recipe-local interpretations (`RECIPE_NOTES`) over broad `KNOWLEDGE` when context is inside an active recipe.",
        "- Keep benchmark adjudication deterministic: compare codex vs baseline using the same canonical text and line indices.",
        "",
        "## Known Structural Label Conventions",
        "",
        "- `RECIPE_TITLE`: canonical recipe name line.",
        "- `RECIPE_VARIANT`: explicit variant/alternative version wording.",
        "- `INGREDIENT_LINE`: ingredient inventory line.",
        "- `INSTRUCTION_LINE`: imperative cooking action line.",
        "- `HOWTO_SECTION`: section header-style line that introduces grouped instructions or ingredients.",
        "",
        "## How to Read False Positives/False Negatives",
        "",
        "- False positive: prediction label is present but does not match the gold line label.",
        "- False negative: gold label line was not predicted as that label.",
        "- Use changed-line context (`previous_line`, `current_line`, `next_line`) before escalating to full prompt/archive artifacts.",
        "",
    ]
    return "\n".join(lines)


def _write_starter_pack_readme(
    *,
    output_path: Path,
    comparison_summary: dict[str, Any],
) -> None:
    pair_count = len(comparison_summary.get("pairs") or [])
    lines = [
        "# Starter Pack v1",
        "",
        "## Source and Pairing",
        "",
        (
            "Codex runs are paired against nearest-timestamp baseline runs within each source key. "
            f"Pair count: {pair_count}."
        ),
        "",
        "## Benchmark Contract",
        "",
        "Canonical line-space scoring compares codex and baseline labels against the same gold canonical lines.",
        "",
        "## Label Ontology Cheat Sheet",
        "",
        "Common labels: `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`, `RECIPE_NOTES`, `OTHER`.",
        "",
        "## Starter Pack Inventory",
        "",
        "- `00_run_overview.md`",
        f"- `{STARTER_PACK_TRIAGE_FILE_NAME}`",
        f"- `{STARTER_PACK_TRIAGE_PACKET_FILE_NAME}`",
        f"- `{STARTER_PACK_CALL_INVENTORY_FILE_NAME}`",
        f"- `{STARTER_PACK_CHANGED_LINES_FILE_NAME}`",
        f"- `{STARTER_PACK_WARNING_TRACE_SUMMARY_FILE_NAME}`",
        f"- `{STARTER_PACK_BRIDGE_SUMMARY_FILE_NAME}`",
        f"- `{STARTER_PACK_SELECTED_PACKETS_FILE_NAME}`",
        f"- `{STARTER_PACK_CASEBOOK_FILE_NAME}`",
        f"- `{STARTER_PACK_OUTSIDE_TRACE_FILE_NAME}` (conditional)",
        f"- `{STARTER_PACK_LABEL_POLICY_FILE_NAME}`",
        f"- `{STARTER_PACK_MANIFEST_FILE_NAME}`",
        f"- `{STARTER_PACK_COMPARISON_MIRROR_FILE_NAME}`",
        f"- `{STARTER_PACK_BREAKDOWN_MIRROR_FILE_NAME}`",
        f"- `{STARTER_PACK_NET_ERROR_BLAME_FILE_NAME}`",
        f"- `{STARTER_PACK_CONFIG_VERSION_METADATA_FILE_NAME}`",
        f"- `{STARTER_PACK_LOW_CONFIDENCE_CHANGED_LINES_FILE_NAME}`",
        f"- `{STARTER_PACK_BASELINE_TRACE_PARITY_FILE_NAME}`",
        "",
        "## Follow-up Packet Rules",
        "",
        "Use this starter pack for first-pass triage. Request heavy artifacts only for selected cases.",
        "",
        "## Generated At",
        "",
        _timestamp_now(),
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _write_starter_pack_v1(
    *,
    output_dir: Path,
    comparison_summary: dict[str, Any],
    changed_line_rows: list[dict[str, Any]],
    pair_breakdown_rows: list[dict[str, Any]],
    per_recipe_breakdown_payload: dict[str, Any],
    recipe_triage_rows: list[dict[str, Any]],
    call_inventory_rows: list[dict[str, Any]],
    outside_span_trace_rows: list[dict[str, Any]],
    sample_limit: int,
) -> dict[str, Any]:
    starter_pack_dir = output_dir / STARTER_PACK_DIR_NAME
    starter_pack_dir.mkdir(parents=True, exist_ok=True)

    _write_starter_pack_readme(
        output_path=starter_pack_dir / STARTER_PACK_README_FILE_NAME,
        comparison_summary=comparison_summary,
    )

    sorted_recipe_triage_rows = sorted(
        recipe_triage_rows,
        key=lambda row: (
            -int(_coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0),
            -abs(_float_or_zero(row.get("delta_codex_minus_baseline"))),
            str(row.get("recipe_id") or ""),
            str(row.get("source_key") or ""),
            str(row.get("codex_run_id") or ""),
        ),
    )
    serialized_triage_rows = [
        _starter_pack_serialize_recipe_triage_row(row)
        for row in sorted_recipe_triage_rows
    ]
    _write_jsonl(starter_pack_dir / STARTER_PACK_TRIAGE_FILE_NAME, serialized_triage_rows)
    triage_packet_rows = _upload_bundle_build_triage_packet_rows(sorted_recipe_triage_rows)
    _write_jsonl(starter_pack_dir / STARTER_PACK_TRIAGE_PACKET_FILE_NAME, triage_packet_rows)

    sorted_call_inventory_rows = sorted(
        call_inventory_rows,
        key=lambda row: (
            str(row.get("run_id") or ""),
            str(row.get("recipe_id") or ""),
            str(row.get("pass") or ""),
            str(row.get("call_id") or ""),
        ),
    )
    _write_jsonl(starter_pack_dir / STARTER_PACK_CALL_INVENTORY_FILE_NAME, sorted_call_inventory_rows)

    starter_changed_rows: list[dict[str, Any]] = []
    for row in changed_line_rows:
        starter_changed_rows.append(
            {
                "recipe_id": str(row.get("recipe_id") or ""),
                "span_region": str(row.get("span_region") or ""),
                "line_index": int(_coerce_int(row.get("line_index")) or 0),
                "gold_label": str(row.get("gold_label") or ""),
                "baseline_pred": str(row.get("vanilla_pred") or ""),
                "codex_pred": str(row.get("codex_pred") or ""),
                "previous_line": str(row.get("previous_line") or ""),
                "current_line": str(row.get("current_line") or ""),
                "next_line": str(row.get("next_line") or ""),
            }
        )
    _write_jsonl(starter_pack_dir / STARTER_PACK_CHANGED_LINES_FILE_NAME, starter_changed_rows)

    warning_trace_summary = _build_warning_and_trace_summary(
        call_inventory_rows=sorted_call_inventory_rows,
        recipe_triage_rows=sorted_recipe_triage_rows,
        outside_span_trace_rows=outside_span_trace_rows,
    )
    _write_json(starter_pack_dir / STARTER_PACK_WARNING_TRACE_SUMMARY_FILE_NAME, warning_trace_summary)

    bridge_summary_rows = [
        {
            "source_key": str(row.get("source_key") or ""),
            "source_file": str(row.get("source_file") or ""),
            "codex_run_id": str(row.get("codex_run_id") or ""),
            "baseline_run_id": str(row.get("baseline_run_id") or ""),
            "recipe_id": str(row.get("recipe_id") or ""),
            "pass1_call_id": str(row.get("pass1_call_id") or ""),
            "pass2_call_id": str(row.get("pass2_call_id") or ""),
            "pass3_call_id": str(row.get("pass3_call_id") or ""),
            "pass1_start_block_index": _coerce_int(row.get("pass1_start_block_index")),
            "pass1_end_block_index": _coerce_int(row.get("pass1_end_block_index")),
            "pass1_selected_block_count": int(_coerce_int(row.get("pass1_selected_block_count")) or 0),
            "pass2_input_block_count": int(_coerce_int(row.get("pass2_input_block_count")) or 0),
            "pass1_vs_pass2_missing_block_count": int(
                _coerce_int(row.get("pass1_vs_pass2_missing_block_count")) or 0
            ),
            "pass1_vs_pass2_extra_block_count": int(
                _coerce_int(row.get("pass1_vs_pass2_extra_block_count")) or 0
            ),
            "pass2_warning_count": int(_coerce_int(row.get("pass2_warning_count")) or 0),
            "pass2_warning_buckets": _coerce_str_list(row.get("pass2_warning_buckets")),
            "pass2_extracted_ingredient_count": int(
                _coerce_int(row.get("pass2_extracted_ingredient_count")) or 0
            ),
            "pass2_extracted_instruction_count": int(
                _coerce_int(row.get("pass2_extracted_instruction_count")) or 0
            ),
            "pass3_step_count": int(_coerce_int(row.get("pass3_step_count")) or 0),
            "pass3_mapping_count": int(_coerce_int(row.get("pass3_mapping_count")) or 0),
            "pass3_empty_mapping": bool(row.get("pass3_empty_mapping")),
            "pass3_warning_count": int(_coerce_int(row.get("pass3_warning_count")) or 0),
            "pass3_warning_buckets": _coerce_str_list(row.get("pass3_warning_buckets")),
            "pass1_status": str(row.get("pass1_status") or ""),
            "pass2_status": str(row.get("pass2_status") or ""),
            "pass3_status": str(row.get("pass3_status") or ""),
            "pass1_clamped_block_loss_count": int(
                _coerce_int(row.get("pass1_clamped_block_loss_count")) or 0
            ),
            "pass1_clamped_block_loss_ratio": _coerce_float(
                row.get("pass1_clamped_block_loss_ratio")
            ),
            "pass2_degradation_reasons": _coerce_str_list(row.get("pass2_degradation_reasons")),
            "pass2_degradation_severity": str(row.get("pass2_degradation_severity") or ""),
            "pass2_promotion_policy": str(row.get("pass2_promotion_policy") or ""),
            "pass3_execution_mode": str(row.get("pass3_execution_mode") or ""),
            "pass3_routing_reason": str(row.get("pass3_routing_reason") or ""),
            "pass3_fallback_reason": str(row.get("pass3_fallback_reason") or ""),
            "transport_mismatch": _coerce_bool(row.get("transport_mismatch")),
            "transport_mismatch_reasons": _coerce_str_list(
                row.get("transport_mismatch_reasons")
            ),
            "transport_effective_to_payload_coverage_ratio": _coerce_float(
                row.get("transport_effective_to_payload_coverage_ratio")
            ),
            "evidence_split_quantity_lines": int(
                _coerce_int(row.get("evidence_split_quantity_lines")) or 0
            ),
            "evidence_dropped_page_markers": int(
                _coerce_int(row.get("evidence_dropped_page_markers")) or 0
            ),
            "evidence_folded_page_markers": int(
                _coerce_int(row.get("evidence_folded_page_markers")) or 0
            ),
            "outside_span_wrong_line_count": int(
                _coerce_int(row.get("outside_span_wrong_line_count")) or 0
            ),
            "outside_span_trace_status_top": str(row.get("outside_span_trace_status_top") or ""),
        }
        for row in sorted_recipe_triage_rows
    ]
    _write_jsonl(starter_pack_dir / STARTER_PACK_BRIDGE_SUMMARY_FILE_NAME, bridge_summary_rows)

    selected_recipe_rows = _select_starter_pack_recipe_cases(sorted_recipe_triage_rows)
    selected_packets = _build_selected_recipe_packets(
        selected_recipe_rows=selected_recipe_rows,
        changed_line_rows=changed_line_rows,
    )
    _write_jsonl(starter_pack_dir / STARTER_PACK_SELECTED_PACKETS_FILE_NAME, selected_packets)
    (starter_pack_dir / STARTER_PACK_CASEBOOK_FILE_NAME).write_text(
        _render_starter_pack_casebook(selected_packets),
        encoding="utf-8",
    )

    inside_accuracy, outside_accuracy, outside_span_accuracy_gap = _aggregate_region_accuracy(
        pair_breakdown_rows
    )
    outside_span_wrong_line_count = len(outside_span_trace_rows)
    include_outside_span_trace = (
        outside_span_wrong_line_count >= STARTER_PACK_OUTSIDE_WRONG_LINE_THRESHOLD
        or (
            outside_span_accuracy_gap is not None
            and outside_span_accuracy_gap >= STARTER_PACK_OUTSIDE_ACCURACY_GAP_THRESHOLD
        )
    )
    outside_span_manifest: dict[str, Any]
    if include_outside_span_trace:
        sorted_outside_rows = sorted(
            outside_span_trace_rows,
            key=lambda row: (
                str(row.get("recipe_id") or ""),
                int(_coerce_int(row.get("line_index")) or 0),
                str(row.get("call_id") or ""),
            ),
        )
        sampled_outside_rows = (
            _sample_rows_evenly(sorted_outside_rows, sample_limit)
            if sample_limit > 0
            else sorted_outside_rows
        )
        outside_rows_out = [
            {
                "call_id": str(row.get("call_id") or ""),
                "recipe_id": str(row.get("recipe_id") or ""),
                "line_index": int(_coerce_int(row.get("line_index")) or 0),
                "gold_label": str(row.get("gold_label") or ""),
                "pred_label": str(row.get("pred_label") or ""),
                "trace_status": str(row.get("trace_status") or ""),
                "warning_buckets": _coerce_str_list(row.get("warning_buckets")),
                "raw_block_stable_key": row.get("raw_block_stable_key"),
                "raw_block_excerpt": str(row.get("raw_block_excerpt") or ""),
                "prompt_candidate_block_excerpt": str(
                    row.get("prompt_candidate_block_excerpt") or ""
                ),
            }
            for row in sampled_outside_rows
        ]
        _write_jsonl(starter_pack_dir / STARTER_PACK_OUTSIDE_TRACE_FILE_NAME, outside_rows_out)
        outside_span_manifest = {
            "included": True,
            "path": f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_OUTSIDE_TRACE_FILE_NAME}",
            "rows": len(outside_rows_out),
            "source_rows": outside_span_wrong_line_count,
        }
    else:
        outside_span_manifest = {
            "included": False,
            "path": None,
            "rows": 0,
            "source_rows": outside_span_wrong_line_count,
            "omitted_reason": (
                "outside_span thresholds not met: "
                f"outside_span_wrong_line_count={outside_span_wrong_line_count} "
                f"(threshold={STARTER_PACK_OUTSIDE_WRONG_LINE_THRESHOLD}), "
                f"outside_span_accuracy_gap="
                f"{_serialize_float(outside_span_accuracy_gap) if outside_span_accuracy_gap is not None else 'n/a'} "
                f"(threshold={STARTER_PACK_OUTSIDE_ACCURACY_GAP_THRESHOLD:.2f})."
            ),
        }

    top_confusion_deltas = _aggregate_confusion_deltas(comparison_summary)
    warning_lines = warning_trace_summary["warnings_by_pass"]
    bucket_lines = warning_trace_summary["warning_buckets"]
    pairs = [
        pair
        for pair in (comparison_summary.get("pairs") or [])
        if isinstance(pair, dict)
    ]
    codex_overall_accuracy_avg = _average_float(
        [
            _coerce_float(pair.get("codex_run", {}).get("overall_line_accuracy"))
            for pair in pairs
            if isinstance(pair.get("codex_run"), dict)
        ]
    )
    codex_macro_f1_avg = _average_float(
        [
            _coerce_float(pair.get("codex_run", {}).get("macro_f1_excluding_other"))
            for pair in pairs
            if isinstance(pair.get("codex_run"), dict)
        ]
    )
    run_overview_lines = [
        "# Starter Pack Run Overview",
        "",
        f"- pair_count: {len(pairs)}",
        f"- codex_overall_line_accuracy_avg: {_serialize_float(codex_overall_accuracy_avg)}",
        f"- codex_macro_f1_excluding_other_avg: {_serialize_float(codex_macro_f1_avg)}",
        f"- inside_span_accuracy: {_serialize_float(inside_accuracy)}",
        f"- outside_span_accuracy: {_serialize_float(outside_accuracy)}",
        f"- inside_vs_outside_accuracy_gap: {_serialize_float(outside_span_accuracy_gap)}",
        (
            "- warning_counts_by_pass: "
            + ", ".join(f"{key}={value}" for key, value in warning_lines.items())
            if warning_lines
            else "- warning_counts_by_pass: none"
        ),
        (
            "- warning_bucket_counts: "
            + ", ".join(f"{key}={value}" for key, value in bucket_lines.items())
            if bucket_lines
            else "- warning_bucket_counts: none"
        ),
        (
            "- pass3_empty_mapping_count: "
            f"{warning_trace_summary.get('pass3_empty_mapping_count')}"
        ),
        (
            "- pass2_degraded_recipe_count: "
            f"{warning_trace_summary.get('pass2_degraded_recipe_count')}"
        ),
        (
            "- pass3_fallback_recipe_count: "
            f"{warning_trace_summary.get('pass3_fallback_recipe_count')}"
        ),
        (
            "- transport_mismatch_recipe_count: "
            f"{warning_trace_summary.get('transport_mismatch_recipe_count')}"
        ),
        (
            "- pass1_clamped_loss_recipe_count: "
            f"{warning_trace_summary.get('pass1_clamped_loss_recipe_count')}"
        ),
        (
            "- pass_status_counts: "
            f"{json.dumps(warning_trace_summary.get('pass_status_counts') or {}, sort_keys=True)}"
        ),
        (
            "- top_confusion_deltas: "
            + (
                ", ".join(
                    f"{row['gold_label']}->{row['pred_label']} ({row['delta_count']:+d})"
                    for row in top_confusion_deltas
                )
                if top_confusion_deltas
                else "none"
            )
        ),
        "",
    ]
    (starter_pack_dir / STARTER_PACK_LABEL_POLICY_FILE_NAME).write_text(
        _render_starter_pack_label_policy(),
        encoding="utf-8",
    )

    _write_json(starter_pack_dir / STARTER_PACK_COMPARISON_MIRROR_FILE_NAME, comparison_summary)
    _write_json(
        starter_pack_dir / STARTER_PACK_BREAKDOWN_MIRROR_FILE_NAME,
        per_recipe_breakdown_payload,
    )
    comparison_pairs = [
        pair
        for pair in (comparison_summary.get("pairs") or [])
        if isinstance(pair, dict)
    ]
    starter_pack_run_rows = _starter_pack_collect_run_rows_from_pairs(comparison_pairs)
    starter_pack_run_dir_by_id = _starter_pack_build_run_dir_by_id(
        output_dir=output_dir,
        run_rows=starter_pack_run_rows,
    )
    net_error_blame_summary = _upload_bundle_build_net_error_blame_summary(
        changed_line_rows=changed_line_rows,
        recipe_triage_rows=sorted_recipe_triage_rows,
        comparison_pairs=comparison_pairs,
    )
    _write_json(
        starter_pack_dir / STARTER_PACK_NET_ERROR_BLAME_FILE_NAME,
        net_error_blame_summary,
    )
    config_version_metadata = _upload_bundle_build_config_version_metadata(
        source_root=output_dir,
        run_rows=starter_pack_run_rows,
        comparison_pairs=comparison_pairs,
        run_dir_by_id=starter_pack_run_dir_by_id,
    )
    _write_json(
        starter_pack_dir / STARTER_PACK_CONFIG_VERSION_METADATA_FILE_NAME,
        config_version_metadata,
    )
    (
        low_confidence_changed_lines_summary,
        low_confidence_changed_lines_rows,
    ) = _upload_bundle_build_low_confidence_changed_lines_packet(
        source_root=output_dir,
        run_dir_by_id=starter_pack_run_dir_by_id,
        changed_line_rows=changed_line_rows,
    )
    _write_jsonl(
        starter_pack_dir / STARTER_PACK_LOW_CONFIDENCE_CHANGED_LINES_FILE_NAME,
        low_confidence_changed_lines_rows,
    )
    baseline_trace_parity = _starter_pack_build_baseline_trace_parity_cues(
        comparison_pairs=comparison_pairs,
        run_rows=starter_pack_run_rows,
        run_dir_by_id=starter_pack_run_dir_by_id,
    )
    _write_json(
        starter_pack_dir / STARTER_PACK_BASELINE_TRACE_PARITY_FILE_NAME,
        baseline_trace_parity,
    )
    pair_comparability = config_version_metadata.get("pair_comparability")
    pair_comparability = (
        pair_comparability if isinstance(pair_comparability, dict) else {}
    )
    run_overview_lines.extend(
        [
            "- config_compatible_pair_ratio: "
            + _serialize_float(
                _coerce_float(pair_comparability.get("config_compatible_pair_ratio"))
            ),
            "- net_error_delta_lines: "
            + str(int(_coerce_int(net_error_blame_summary.get("net_error_delta_lines")) or 0)),
            "- low_confidence_changed_lines: "
            + str(
                int(
                    _coerce_int(
                        low_confidence_changed_lines_summary.get("row_count")
                    )
                    or 0
                )
            ),
            "- baseline_trace_fully_ready_pairs: "
            + str(int(_coerce_int(baseline_trace_parity.get("fully_ready_pairs")) or 0)),
            "",
        ]
    )
    (starter_pack_dir / "00_run_overview.md").write_text(
        "\n".join(run_overview_lines),
        encoding="utf-8",
    )

    legacy_to_starter_mapping = {
        "comparison_summary.json": f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_COMPARISON_MIRROR_FILE_NAME}",
        "per_recipe_or_per_span_breakdown.json": (
            f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_BREAKDOWN_MIRROR_FILE_NAME}"
        ),
        "changed_lines.codex_vs_vanilla.jsonl": (
            f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_CHANGED_LINES_FILE_NAME}"
        ),
        "label_policy_adjudication_notes.md": (
            f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_LABEL_POLICY_FILE_NAME}"
        ),
        "process_manifest.json": f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_MANIFEST_FILE_NAME}",
        STARTER_PACK_TRIAGE_LEGACY_CSV_FILE_NAME: (
            f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_TRIAGE_FILE_NAME}"
        ),
    }
    starter_pack_manifest = {
        "starter_pack_version": "v1",
        "selection_policy": dict(STARTER_PACK_SELECTION_POLICY),
        "outside_span_inclusion_policy": {
            "wrong_line_count_threshold": STARTER_PACK_OUTSIDE_WRONG_LINE_THRESHOLD,
            "accuracy_gap_threshold": STARTER_PACK_OUTSIDE_ACCURACY_GAP_THRESHOLD,
        },
        "heavy_artifacts_omitted_by_default": list(
            STARTER_PACK_HEAVY_ARTIFACTS_OMITTED_BY_DEFAULT
        ),
        "legacy_to_starter_mapping": legacy_to_starter_mapping,
        "outside_span_trace_sample": outside_span_manifest,
        "triage_packet": {
            "schema_version": UPLOAD_BUNDLE_TRIAGE_PACKET_SCHEMA_VERSION,
            "row_count": len(triage_packet_rows),
        },
        "net_error_blame_summary_file": STARTER_PACK_NET_ERROR_BLAME_FILE_NAME,
        "config_version_metadata_file": STARTER_PACK_CONFIG_VERSION_METADATA_FILE_NAME,
        "low_confidence_changed_lines": {
            "summary": low_confidence_changed_lines_summary,
            "file": STARTER_PACK_LOW_CONFIDENCE_CHANGED_LINES_FILE_NAME,
            "row_count": len(low_confidence_changed_lines_rows),
        },
        "baseline_trace_parity_file": STARTER_PACK_BASELINE_TRACE_PARITY_FILE_NAME,
        "generated_at": _timestamp_now(),
    }
    _write_json(starter_pack_dir / STARTER_PACK_MANIFEST_FILE_NAME, starter_pack_manifest)

    included_files = sorted(
        f"{STARTER_PACK_DIR_NAME}/{path.name}"
        for path in starter_pack_dir.iterdir()
        if path.is_file()
    )
    return {
        "path": STARTER_PACK_DIR_NAME,
        "included_files": included_files,
        "manifest": starter_pack_manifest,
    }


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
    lines.append(f"- `{STARTER_PACK_DIR_NAME}/` (deterministic blended first-look starter pack)")
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
    starter_pack_source = output_dir / STARTER_PACK_DIR_NAME
    if starter_pack_source.is_dir():
        shutil.copytree(
            starter_pack_source,
            md_output_dir / STARTER_PACK_DIR_NAME,
            dirs_exist_ok=True,
        )

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


def _upload_bundle_content_type(path: Path) -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name.endswith(".jsonl.gz"):
        return "jsonl_gzip"
    if suffix == ".json":
        return "json"
    if suffix == ".jsonl":
        return "jsonl"
    if suffix == ".md":
        return "markdown"
    if suffix == ".txt":
        return "text"
    if suffix == ".csv":
        return "csv"
    if suffix == ".gz":
        return "gzip"
    return "binary"


def _upload_bundle_parse_jsonl_text(text: str) -> list[Any]:
    rows: list[Any] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append(
                {
                    "_parse_error": "invalid_json",
                    "_line_number": line_number,
                    "_raw_line": raw_line,
                }
            )
    return rows


def _upload_bundle_parse_csv_text(text: str) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(row) for row in reader]
    return {
        "fieldnames": list(reader.fieldnames or []),
        "rows": rows,
    }


def _upload_bundle_category(
    relative_path: str,
    run_output_dirs: set[str],
) -> tuple[str, str | None]:
    parts = relative_path.split("/")
    if not parts:
        return ("other", None)
    first = parts[0]
    if first == STARTER_PACK_DIR_NAME:
        return ("starter_pack", None)
    if first in run_output_dirs:
        return ("run_artifact", first)
    if len(parts) == 1:
        return ("root_artifact", None)
    return ("other", None)


def _upload_bundle_load_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            if isinstance(row, dict):
                rows.append(dict(row))
    except csv.Error:
        return []
    return rows


def _upload_bundle_load_recipe_triage_rows(starter_pack_dir: Path) -> list[dict[str, Any]]:
    jsonl_rows = _iter_jsonl(starter_pack_dir / STARTER_PACK_TRIAGE_FILE_NAME)
    if jsonl_rows:
        return [row for row in jsonl_rows if isinstance(row, dict)]
    return _upload_bundle_load_csv_rows(
        starter_pack_dir / STARTER_PACK_TRIAGE_LEGACY_CSV_FILE_NAME
    )


def _upload_bundle_load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return _load_json(path)
    except Exception:  # noqa: BLE001
        return {}


def _json_size_bytes(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    except Exception:  # noqa: BLE001
        return 0


def _upload_bundle_select_high_level_artifact_paths(
    *,
    source_root: Path,
    discovered_run_dirs: list[Path],
    target_bundle_size_bytes: int,
) -> tuple[list[Path], dict[str, Any]]:
    target_bytes = max(int(target_bundle_size_bytes), 1)
    minimum_budget_bytes = min(GROUP_UPLOAD_BUNDLE_MIN_ARTIFACT_BUDGET_BYTES, target_bytes)
    artifact_budget_bytes = max(
        int(target_bytes * GROUP_UPLOAD_BUNDLE_ROOT_ARTIFACT_BUDGET_SHARE),
        minimum_budget_bytes,
    )
    artifact_budget_bytes = min(artifact_budget_bytes, target_bytes)
    selected: list[Path] = []
    selected_set: set[Path] = set()
    selected_bytes = 0

    def _path_size(path: Path) -> int:
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0

    def _append_if_allowed(path: Path, *, required: bool) -> bool:
        nonlocal selected_bytes
        if path in selected_set or not path.is_file():
            return False
        path_bytes = _path_size(path)
        if not required and selected_bytes + path_bytes > artifact_budget_bytes:
            return False
        selected.append(path)
        selected_set.add(path)
        selected_bytes += path_bytes
        return True

    for relative_path in GROUP_UPLOAD_BUNDLE_ROOT_PRIORITY_FILES:
        _append_if_allowed(source_root / relative_path, required=False)

    included_run_rows: list[dict[str, Any]] = []
    for run_dir in discovered_run_dirs:
        run_rel = ""
        try:
            run_rel = str(run_dir.relative_to(source_root).as_posix())
        except ValueError:
            run_rel = run_dir.name
        included_files: list[str] = []
        for file_name, required in GROUP_UPLOAD_BUNDLE_RUN_PRIORITY_FILES:
            candidate = run_dir / file_name
            if _append_if_allowed(candidate, required=required):
                included_files.append(file_name)
        included_run_rows.append(
            {
                "run_dir": run_rel,
                "included_files": included_files,
            }
        )

    metadata = {
        "mode": "high_level_only",
        "target_bundle_size_bytes": target_bytes,
        "artifact_budget_bytes": artifact_budget_bytes,
        "selected_artifact_count": len(selected),
        "selected_artifact_bytes": selected_bytes,
        "discovered_run_count": len(discovered_run_dirs),
        "per_run_included_files": included_run_rows,
    }
    return selected, metadata


def _upload_bundle_build_group_high_level_packet(
    *,
    source_root: Path,
    discovered_run_dirs: list[Path],
    run_rows: list[dict[str, Any]],
    run_diagnostics: list[dict[str, Any]],
    target_bundle_size_bytes: int,
    payload_bytes_before_packet: int,
    artifact_selection: dict[str, Any],
) -> dict[str, Any]:
    run_row_by_id: dict[str, dict[str, Any]] = {}
    run_row_by_subdir: dict[str, dict[str, Any]] = {}
    for row in run_rows:
        if not isinstance(row, dict):
            continue
        run_id = str(row.get("run_id") or "").strip()
        if run_id:
            run_row_by_id.setdefault(run_id, row)
        output_subdir = str(row.get("output_subdir") or "").strip()
        if output_subdir:
            run_row_by_subdir.setdefault(output_subdir, row)

    run_diag_by_id: dict[str, dict[str, Any]] = {}
    run_diag_by_subdir: dict[str, dict[str, Any]] = {}
    for row in run_diagnostics:
        if not isinstance(row, dict):
            continue
        run_id = str(row.get("run_id") or "").strip()
        if run_id:
            run_diag_by_id.setdefault(run_id, row)
        output_subdir = str(row.get("output_subdir") or "").strip()
        if output_subdir:
            run_diag_by_subdir.setdefault(output_subdir, row)

    run_payloads: list[dict[str, Any]] = []
    run_count = len(discovered_run_dirs)
    target_bytes = max(int(target_bundle_size_bytes), 1)
    reserved_bytes = min(
        max(GROUP_UPLOAD_BUNDLE_RESERVED_BYTES, target_bytes // 8),
        max(target_bytes // 2, 1),
    )
    budget_for_samples = max(target_bytes - int(payload_bytes_before_packet) - reserved_bytes, 0)
    per_run_sample_budget_bytes = (
        max(budget_for_samples // run_count, 0) if run_count > 0 else 0
    )

    sampled_wrong_line_rows_total = 0
    sampled_wrong_line_bytes_total = 0
    runs_with_sampled_rows = 0

    for run_dir in discovered_run_dirs:
        run_manifest = _upload_bundle_load_json_object(run_dir / "run_manifest.json")
        eval_report = _upload_bundle_load_json_object(run_dir / "eval_report.json")
        run_id = str(run_manifest.get("run_id") or run_dir.name).strip() or run_dir.name
        try:
            output_subdir = str(run_dir.relative_to(source_root).as_posix())
        except ValueError:
            output_subdir = run_dir.name

        run_row = run_row_by_id.get(run_id) or run_row_by_subdir.get(output_subdir) or {}
        run_diag = run_diag_by_id.get(run_id) or run_diag_by_subdir.get(output_subdir) or {}
        source_payload = (
            run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
        )
        source_path = source_payload.get("path") if isinstance(source_payload, dict) else None
        source_file = source_path if isinstance(source_path, str) else None

        wrong_line_candidates: list[dict[str, Any]] = []
        wrong_line_rows = _iter_jsonl(run_dir / "wrong_label_lines.jsonl")
        for row in wrong_line_rows:
            if not isinstance(row, dict):
                continue
            line_index = _coerce_int(row.get("line_index"))
            if line_index is None:
                continue
            text_value = ""
            for key in ("current_line", "line_text", "text"):
                candidate_text = row.get(key)
                if isinstance(candidate_text, str) and candidate_text.strip():
                    text_value = candidate_text.strip()
                    break
            wrong_line_candidates.append(
                {
                    "line_index": int(line_index),
                    "recipe_id": str(row.get("recipe_id") or ""),
                    "gold_label": str(row.get("gold_label") or ""),
                    "pred_label": str(row.get("pred_label") or ""),
                    "line_excerpt": _excerpt(text_value, max_len=160),
                }
            )

        wrong_line_samples: list[dict[str, Any]] = []
        if wrong_line_candidates and per_run_sample_budget_bytes > 0:
            probe_rows = wrong_line_candidates[: min(12, len(wrong_line_candidates))]
            average_row_bytes = max(
                int(sum(_json_size_bytes(item) for item in probe_rows) / max(len(probe_rows), 1)),
                1,
            )
            max_rows_by_budget = max(per_run_sample_budget_bytes // average_row_bytes, 0)
            max_rows = min(
                len(wrong_line_candidates),
                GROUP_UPLOAD_BUNDLE_MAX_WRONG_LINE_SAMPLES_PER_RUN,
            )
            if max_rows_by_budget > 0:
                max_rows = min(max_rows, int(max_rows_by_budget))
            if max_rows <= 0:
                max_rows = min(
                    GROUP_UPLOAD_BUNDLE_MIN_WRONG_LINE_SAMPLES_PER_RUN,
                    len(wrong_line_candidates),
                )
            wrong_line_samples = _sample_rows_evenly(wrong_line_candidates, max_rows)
            while (
                len(wrong_line_samples) > 1
                and _json_size_bytes(wrong_line_samples) > per_run_sample_budget_bytes
            ):
                wrong_line_samples = wrong_line_samples[:-1]

        sampled_wrong_line_rows_total += len(wrong_line_samples)
        sampled_wrong_line_bytes_total += _json_size_bytes(wrong_line_samples)
        if wrong_line_samples:
            runs_with_sampled_rows += 1

        run_payloads.append(
            {
                "run_id": run_id,
                "output_subdir": output_subdir,
                "source_file": _source_file_name(source_file),
                "llm_recipe_pipeline": str(
                    run_row.get("llm_recipe_pipeline")
                    or ((run_manifest.get("run_config") or {}).get("llm_recipe_pipeline"))
                    or "unknown"
                ),
                "line_role_pipeline": str(
                    run_row.get("line_role_pipeline")
                    or ((run_manifest.get("run_config") or {}).get("line_role_pipeline"))
                    or "off"
                ),
                "overall_line_accuracy": _coerce_float(
                    run_row.get("overall_line_accuracy")
                    if isinstance(run_row, dict)
                    else eval_report.get("overall_line_accuracy")
                ),
                "macro_f1_excluding_other": _coerce_float(
                    run_row.get("macro_f1_excluding_other")
                    if isinstance(run_row, dict)
                    else eval_report.get("macro_f1_excluding_other")
                ),
                "practical_f1": _coerce_float(
                    run_row.get("practical_f1")
                    if isinstance(run_row, dict)
                    else eval_report.get("practical_f1")
                ),
                "full_prompt_log_status": str(
                    run_diag.get("full_prompt_log_status")
                    if isinstance(run_diag, dict)
                    else run_row.get("full_prompt_log_status")
                    or "unknown"
                ),
                "wrong_line_total": len(wrong_line_rows),
                "sampled_wrong_line_count": len(wrong_line_samples),
                "sampled_wrong_lines": wrong_line_samples,
            }
        )

    return {
        "schema_version": "upload_bundle_group_high_level.v1",
        "generated_at": _timestamp_now(),
        "source_root": str(source_root),
        "run_count": run_count,
        "target_bundle_size_bytes": target_bytes,
        "target_bundle_size_mb": round(target_bytes / (1024 * 1024), 3),
        "payload_bytes_before_group_packet": int(payload_bytes_before_packet),
        "reserved_bytes_for_index_overview": reserved_bytes,
        "budget_for_group_samples_bytes": budget_for_samples,
        "per_run_sample_budget_bytes": per_run_sample_budget_bytes,
        "artifact_selection": artifact_selection,
        "runs_with_sampled_rows": runs_with_sampled_rows,
        "sampled_wrong_line_rows_total": sampled_wrong_line_rows_total,
        "sampled_wrong_line_bytes_total": sampled_wrong_line_bytes_total,
        "runs": run_payloads,
    }


def _upload_bundle_build_context(*, source_root: Path) -> dict[str, Any]:
    run_index_payload = _upload_bundle_load_json_object(source_root / "run_index.json")
    comparison_summary_payload = _upload_bundle_load_json_object(
        source_root / "comparison_summary.json"
    )
    process_manifest_payload = _upload_bundle_load_json_object(source_root / "process_manifest.json")
    per_recipe_payload = _upload_bundle_load_json_object(source_root / PER_RECIPE_BREAKDOWN_FILE_NAME)

    run_rows_from_root_raw = run_index_payload.get("runs")
    has_run_rows_from_root = isinstance(run_rows_from_root_raw, list)
    run_rows_from_root = run_rows_from_root_raw if has_run_rows_from_root else []
    comparison_pairs_from_root_raw = comparison_summary_payload.get("pairs")
    has_pairs_from_root = isinstance(comparison_pairs_from_root_raw, list)
    comparison_pairs_from_root = (
        comparison_pairs_from_root_raw if has_pairs_from_root else []
    )
    pair_breakdown_from_root = per_recipe_payload.get("pairs")
    pair_breakdown_from_root = (
        pair_breakdown_from_root if isinstance(pair_breakdown_from_root, list) else []
    )
    changed_lines_from_root = _iter_jsonl(source_root / CHANGED_LINES_FILE_NAME)

    starter_pack_dir = source_root / STARTER_PACK_DIR_NAME
    starter_pack_present = starter_pack_dir.is_dir()
    starter_recipe_triage_rows = _upload_bundle_load_recipe_triage_rows(starter_pack_dir)
    starter_call_inventory_rows = _iter_jsonl(
        starter_pack_dir / STARTER_PACK_CALL_INVENTORY_FILE_NAME
    )
    starter_selected_packets = _iter_jsonl(
        starter_pack_dir / STARTER_PACK_SELECTED_PACKETS_FILE_NAME
    )
    starter_manifest_payload = _upload_bundle_load_json_object(
        starter_pack_dir / STARTER_PACK_MANIFEST_FILE_NAME
    )

    discovered_run_dirs = _discover_run_dirs(source_root)
    derived_run_records: list[RunRecord] = []
    for run_dir in discovered_run_dirs:
        try:
            derived_run_records.append(
                _build_run_record_from_existing_run(run_dir=run_dir)
            )
        except Exception:  # noqa: BLE001
            continue
    run_dir_by_id: dict[str, Path] = {}
    for record in derived_run_records:
        run_id = str(record.run_id or "").strip()
        if not run_id:
            continue
        run_dir_by_id.setdefault(run_id, Path(record.run_dir))
    derived_run_rows = [
        {
            "run_id": record.run_id,
            "output_subdir": record.output_subdir,
            "source_file": record.source_file,
            "overall_line_accuracy": record.metric_overall_line_accuracy,
            "practical_f1": record.metric_practical_f1,
            "full_prompt_log_status": record.full_prompt_log_status,
            "full_prompt_log_rows": record.full_prompt_log_rows,
            "line_role_pipeline": record.line_role_pipeline,
            "llm_recipe_pipeline": record.llm_recipe_pipeline,
        }
        for record in sorted(
            derived_run_records,
            key=lambda record: (
                record.run_timestamp or datetime.min,
                str(record.run_id or ""),
            ),
        )
    ]

    derived_pairs: list[dict[str, Any]] = []
    derived_changed_lines: list[dict[str, Any]] = []
    derived_pair_breakdown: list[dict[str, Any]] = []
    derived_recipe_triage: list[dict[str, Any]] = []
    derived_call_inventory: list[dict[str, Any]] = []
    if derived_run_records:
        try:
            (
                derived_comparison_summary,
                derived_changed_lines,
                derived_pair_breakdown,
                _derived_targeted_prompt_rows,
                derived_recipe_triage,
                derived_call_inventory,
                _derived_outside_span_rows,
            ) = _build_comparison_summary(
                records=derived_run_records,
                excerpt_limit=DEFAULT_EXCERPT_LIMIT,
                targeted_prompt_case_limit=DEFAULT_TARGETED_PROMPT_CASES,
            )
            derived_pairs = (
                derived_comparison_summary.get("pairs")
                if isinstance(derived_comparison_summary.get("pairs"), list)
                else []
            )
        except Exception:  # noqa: BLE001
            derived_pairs = []
            derived_changed_lines = []
            derived_pair_breakdown = []
            derived_recipe_triage = []
            derived_call_inventory = []

    effective_run_rows = run_rows_from_root if run_rows_from_root else derived_run_rows
    effective_pairs = comparison_pairs_from_root if comparison_pairs_from_root else derived_pairs
    effective_changed_lines = (
        changed_lines_from_root if changed_lines_from_root else derived_changed_lines
    )
    effective_pair_breakdown = (
        pair_breakdown_from_root if pair_breakdown_from_root else derived_pair_breakdown
    )
    effective_recipe_triage = (
        derived_recipe_triage if derived_recipe_triage else starter_recipe_triage_rows
    )
    effective_call_inventory = (
        derived_call_inventory if derived_call_inventory else starter_call_inventory_rows
    )

    effective_selected_packets = list(starter_selected_packets)
    if not effective_selected_packets and effective_recipe_triage and effective_changed_lines:
        try:
            selected_rows = _select_starter_pack_recipe_cases(effective_recipe_triage)
            effective_selected_packets = _build_selected_recipe_packets(
                selected_recipe_rows=selected_rows,
                changed_line_rows=effective_changed_lines,
            )
        except Exception:  # noqa: BLE001
            effective_selected_packets = []

    return {
        "run_index_payload": run_index_payload,
        "comparison_summary_payload": comparison_summary_payload,
        "process_manifest_payload": process_manifest_payload,
        "per_recipe_payload": per_recipe_payload,
        "starter_manifest_payload": starter_manifest_payload,
        "starter_pack_present": starter_pack_present,
        "run_rows": effective_run_rows,
        "comparison_pairs": effective_pairs,
        "changed_line_rows": effective_changed_lines,
        "pair_breakdown_rows": effective_pair_breakdown,
        "recipe_triage_rows": effective_recipe_triage,
        "call_inventory_rows": effective_call_inventory,
        "selected_packets": effective_selected_packets,
        "run_dir_by_id": run_dir_by_id,
        "discovered_run_dirs": discovered_run_dirs,
        "advertised_counts": {
            "run_count": len(run_rows_from_root) if has_run_rows_from_root else None,
            "pair_count": len(comparison_pairs_from_root) if has_pairs_from_root else None,
            "changed_lines_total": _coerce_int(
                comparison_summary_payload.get("changed_lines_total")
            ),
        },
    }


def _upload_bundle_collect_confusion_delta_counts(
    comparison_pairs: list[dict[str, Any]],
) -> Counter[tuple[str, str]]:
    counter: Counter[tuple[str, str]] = Counter()
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        confusion_payload = pair.get("confusion_matrix")
        if not isinstance(confusion_payload, dict):
            continue
        delta_matrix = confusion_payload.get("delta_codex_minus_baseline")
        if not isinstance(delta_matrix, dict):
            continue
        for gold_label, pred_counts in delta_matrix.items():
            if not isinstance(gold_label, str) or not isinstance(pred_counts, dict):
                continue
            for pred_label, count_raw in pred_counts.items():
                if not isinstance(pred_label, str):
                    continue
                count = _coerce_int(count_raw)
                if count is None or count == 0:
                    continue
                counter[(gold_label, pred_label)] += count
    return counter


def _upload_bundle_load_run_per_label_metrics(run_dir: Path) -> dict[str, dict[str, Any]]:
    eval_report_path = run_dir / "eval_report.json"
    if not eval_report_path.is_file():
        return {}
    try:
        eval_report = _load_json(eval_report_path)
    except Exception:  # noqa: BLE001
        return {}
    per_label = eval_report.get("per_label")
    if not isinstance(per_label, dict):
        return {}
    output: dict[str, dict[str, Any]] = {}
    for label, row in per_label.items():
        if not isinstance(label, str) or not isinstance(row, dict):
            continue
        output[label] = {
            "precision": _coerce_float(row.get("precision")),
            "recall": _coerce_float(row.get("recall")),
            "f1": _coerce_float(row.get("f1")),
            "gold_total": _coerce_int(row.get("gold_total")),
            "pred_total": _coerce_int(row.get("pred_total")),
        }
    return output


def _upload_bundle_resolve_manifest_path(
    *,
    run_dir: Path,
    value: Any,
) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value.strip())
    resolved = candidate if candidate.is_absolute() else run_dir / candidate
    if resolved.exists() and resolved.is_file():
        return resolved
    return None


def _upload_bundle_resolve_gold_spans_path(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
) -> Path | None:
    artifacts = run_manifest.get("artifacts")
    if isinstance(artifacts, dict):
        from_artifacts = _upload_bundle_resolve_manifest_path(
            run_dir=run_dir,
            value=artifacts.get("gold_spans_jsonl"),
        )
        if from_artifacts is not None:
            return from_artifacts
    run_config = run_manifest.get("run_config")
    if isinstance(run_config, dict):
        from_run_config = _upload_bundle_resolve_manifest_path(
            run_dir=run_dir,
            value=run_config.get("gold_spans"),
        )
        if from_run_config is not None:
            return from_run_config
    eval_report_path = run_dir / "eval_report.json"
    if eval_report_path.is_file():
        eval_report = _upload_bundle_load_json_object(eval_report_path)
        canonical = eval_report.get("canonical") if isinstance(eval_report, dict) else None
        if isinstance(canonical, dict):
            from_eval_report = _upload_bundle_resolve_manifest_path(
                run_dir=run_dir,
                value=canonical.get("canonical_span_labels_path"),
            )
            if from_eval_report is not None:
                return from_eval_report
        from_eval_report = _upload_bundle_resolve_manifest_path(
            run_dir=run_dir,
            value=eval_report.get("gold_spans_path") if isinstance(eval_report, dict) else None,
        )
        if from_eval_report is not None:
            return from_eval_report
    return None


def _upload_bundle_load_gold_line_labels_from_eval_report(
    run_dir: Path,
) -> dict[int, set[str]]:
    eval_report_path = run_dir / "eval_report.json"
    if not eval_report_path.is_file():
        return {}
    eval_report = _upload_bundle_load_json_object(eval_report_path)
    canonical = eval_report.get("canonical") if isinstance(eval_report, dict) else None
    if not isinstance(canonical, dict):
        return {}

    canonical_text_path_raw = canonical.get("canonical_text_path")
    canonical_spans_path_raw = canonical.get("canonical_span_labels_path")
    if not isinstance(canonical_text_path_raw, str) or not isinstance(canonical_spans_path_raw, str):
        return {}

    canonical_text_path = Path(canonical_text_path_raw)
    canonical_spans_path = Path(canonical_spans_path_raw)
    if not canonical_text_path.is_file() or not canonical_spans_path.is_file():
        return {}

    try:
        canonical_text = canonical_text_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    lines = _build_canonical_lines(canonical_text)
    spans = _load_gold_spans(canonical_spans_path)
    labels_by_line = _line_gold_labels(lines=lines, spans=spans)
    output: dict[int, set[str]] = {}
    for raw_index, labels in labels_by_line.items():
        index = _coerce_int(raw_index)
        if index is None:
            continue
        if isinstance(labels, (list, tuple, set)):
            resolved_labels = {
                str(label).strip()
                for label in labels
                if str(label).strip()
            }
        else:
            resolved_labels = {str(labels).strip()} if str(labels).strip() else set()
        if not resolved_labels:
            resolved_labels = {"OTHER"}
        output[int(index)] = resolved_labels
    return output


def _upload_bundle_normalize_match_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _upload_bundle_extract_text_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                rows.append(text)
            continue
        if not isinstance(item, dict):
            continue
        for key in ("text", "name", "value", "raw", "label"):
            text = str(item.get(key) or "").strip()
            if text:
                rows.append(text)
                break
    return rows


def _upload_bundle_collect_text_matches(
    *,
    targets: list[str],
    blocks_by_index: dict[int, str],
) -> set[int]:
    normalized_targets = [
        _upload_bundle_normalize_match_text(value)
        for value in targets
        if _upload_bundle_normalize_match_text(value)
    ]
    if not normalized_targets:
        return set()
    matched: set[int] = set()
    for index, block_text in blocks_by_index.items():
        normalized_block = _upload_bundle_normalize_match_text(block_text)
        if not normalized_block:
            continue
        for target in normalized_targets:
            if len(target) < 4:
                continue
            if target in normalized_block or (
                len(normalized_block) >= 20 and normalized_block in target
            ):
                matched.add(int(index))
                break
    return matched


def _upload_bundle_pick_title_block(
    *,
    title: str,
    candidate_indices: list[int],
    blocks_by_index: dict[int, str],
) -> int | None:
    normalized_title = _upload_bundle_normalize_match_text(title)
    if not normalized_title:
        return candidate_indices[0] if candidate_indices else None
    for index in candidate_indices:
        normalized_block = _upload_bundle_normalize_match_text(blocks_by_index.get(index))
        if not normalized_block:
            continue
        if normalized_title in normalized_block or normalized_block in normalized_title:
            return int(index)
    return candidate_indices[0] if candidate_indices else None


def _upload_bundle_project_pass2_recipe_labels(
    *,
    pass2_input: dict[str, Any],
    pass2_output: dict[str, Any],
) -> dict[int, str]:
    blocks_payload = pass2_input.get("blocks")
    if not isinstance(blocks_payload, list):
        return {}
    blocks_by_index: dict[int, str] = {}
    ordered_indices: list[int] = []
    for row in blocks_payload:
        if not isinstance(row, dict):
            continue
        index = _coerce_int(row.get("index"))
        if index is None or index < 0:
            continue
        blocks_by_index[int(index)] = str(row.get("text") or "")
        ordered_indices.append(int(index))
    if not blocks_by_index:
        return {}
    ordered_indices = sorted(set(ordered_indices))

    schemaorg_payload = pass2_output.get("schemaorg_recipe")
    if not isinstance(schemaorg_payload, dict):
        schemaorg_payload = {}

    ingredient_indices = _upload_bundle_collect_text_matches(
        targets=_upload_bundle_extract_text_values(pass2_output.get("extracted_ingredients")),
        blocks_by_index=blocks_by_index,
    )
    instruction_indices = _upload_bundle_collect_text_matches(
        targets=_upload_bundle_extract_text_values(pass2_output.get("extracted_instructions")),
        blocks_by_index=blocks_by_index,
    )
    notes_indices = _upload_bundle_collect_text_matches(
        targets=[
            str(schemaorg_payload.get("description") or ""),
            str(schemaorg_payload.get("comment") or ""),
        ],
        blocks_by_index=blocks_by_index,
    )

    labels_by_index: dict[int, str] = {}
    for index in ingredient_indices:
        labels_by_index[int(index)] = "INGREDIENT_LINE"
    for index in instruction_indices:
        labels_by_index[int(index)] = "INSTRUCTION_LINE"
    for index in notes_indices:
        labels_by_index.setdefault(int(index), "RECIPE_NOTES")

    title_index = _upload_bundle_pick_title_block(
        title=str(schemaorg_payload.get("name") or ""),
        candidate_indices=ordered_indices,
        blocks_by_index=blocks_by_index,
    )
    if title_index is not None:
        labels_by_index[int(title_index)] = "RECIPE_TITLE"

    yield_values = [
        str(schemaorg_payload.get("recipeYield") or ""),
        str(schemaorg_payload.get("yield") or ""),
        str(schemaorg_payload.get("yields") or ""),
    ]
    normalized_yields = [
        _upload_bundle_normalize_match_text(value)
        for value in yield_values
        if _upload_bundle_normalize_match_text(value)
    ]
    time_values = [
        str(schemaorg_payload.get("prepTime") or ""),
        str(schemaorg_payload.get("cookTime") or ""),
        str(schemaorg_payload.get("totalTime") or ""),
    ]
    normalized_times = [
        _upload_bundle_normalize_match_text(value)
        for value in time_values
        if _upload_bundle_normalize_match_text(value)
    ]
    for index in ordered_indices:
        block_text = blocks_by_index.get(index, "")
        normalized_block = _upload_bundle_normalize_match_text(block_text)
        if not normalized_block:
            continue
        if (
            _UPLOAD_BUNDLE_YIELD_LINE_RE.search(block_text)
            and (
                not normalized_yields
                or any(value in normalized_block for value in normalized_yields)
            )
        ):
            labels_by_index[index] = "YIELD_LINE"
            continue
        if _UPLOAD_BUNDLE_TIME_LINE_RE.search(block_text) or _UPLOAD_BUNDLE_TIME_VALUE_RE.search(
            block_text
        ):
            if not normalized_times or any(value in normalized_block for value in normalized_times):
                labels_by_index.setdefault(index, "TIME_LINE")

    return labels_by_index


def _upload_bundle_project_pass3_recipe_labels(
    *,
    pass2_input: dict[str, Any],
    pass2_output: dict[str, Any] | None,
    pass3_output: dict[str, Any] | None,
) -> dict[int, str]:
    blocks_payload = pass2_input.get("blocks")
    if not isinstance(blocks_payload, list):
        return {}
    blocks_by_index: dict[int, str] = {}
    ordered_indices: list[int] = []
    for row in blocks_payload:
        if not isinstance(row, dict):
            continue
        index = _coerce_int(row.get("index"))
        if index is None or index < 0:
            continue
        blocks_by_index[int(index)] = str(row.get("text") or "")
        ordered_indices.append(int(index))
    if not blocks_by_index:
        return {}
    ordered_indices = sorted(set(ordered_indices))

    labels_by_index: dict[int, str] = {}
    title_value = ""
    ingredient_targets: list[str] = []
    instruction_targets: list[str] = []

    if isinstance(pass3_output, dict):
        draft_payload = pass3_output.get("draft_v1")
        if isinstance(draft_payload, dict):
            recipe_payload = draft_payload.get("recipe")
            if isinstance(recipe_payload, dict):
                title_value = str(recipe_payload.get("title") or "")
            steps_payload = draft_payload.get("steps")
            if isinstance(steps_payload, list):
                for step_row in steps_payload:
                    if not isinstance(step_row, dict):
                        continue
                    instruction_text = str(step_row.get("instruction") or "").strip()
                    if instruction_text:
                        instruction_targets.append(instruction_text)
                    ingredient_lines = step_row.get("ingredient_lines")
                    ingredient_targets.extend(
                        _upload_bundle_extract_text_values(ingredient_lines)
                    )

    if not title_value and isinstance(pass2_output, dict):
        schemaorg_payload = pass2_output.get("schemaorg_recipe")
        if isinstance(schemaorg_payload, dict):
            title_value = str(schemaorg_payload.get("name") or "")
        if not ingredient_targets:
            ingredient_targets = _upload_bundle_extract_text_values(
                pass2_output.get("extracted_ingredients")
            )
        if not instruction_targets:
            instruction_targets = _upload_bundle_extract_text_values(
                pass2_output.get("extracted_instructions")
            )

    for index in _upload_bundle_collect_text_matches(
        targets=ingredient_targets,
        blocks_by_index=blocks_by_index,
    ):
        labels_by_index[int(index)] = "INGREDIENT_LINE"
    for index in _upload_bundle_collect_text_matches(
        targets=instruction_targets,
        blocks_by_index=blocks_by_index,
    ):
        labels_by_index[int(index)] = "INSTRUCTION_LINE"

    title_index = _upload_bundle_pick_title_block(
        title=title_value,
        candidate_indices=ordered_indices,
        blocks_by_index=blocks_by_index,
    )
    if title_index is not None:
        labels_by_index[int(title_index)] = "RECIPE_TITLE"

    return labels_by_index


def _upload_bundle_collect_stage_pass_reports_for_run(
    *,
    run_dir: Path,
    gold_cache: dict[Path, dict[int, set[str]]],
) -> dict[str, dict[str, Any]]:
    run_manifest_path = run_dir / "run_manifest.json"
    if not run_manifest_path.is_file():
        return {}
    run_manifest = _upload_bundle_load_json_object(run_manifest_path)
    if not run_manifest:
        return {}
    pred_run_dir = _resolve_prediction_run_dir(run_dir, run_manifest)
    if pred_run_dir is None:
        return {}
    gold_spans_path = _upload_bundle_resolve_gold_spans_path(
        run_dir=run_dir,
        run_manifest=run_manifest,
    )
    if gold_spans_path is None:
        return {}
    gold_labels = gold_cache.get(gold_spans_path)
    if gold_labels is None:
        try:
            gold_labels = load_gold_block_labels(
                gold_spans_path,
                require_exhaustive=False,
            )
        except Exception:  # noqa: BLE001
            gold_labels = _upload_bundle_load_gold_line_labels_from_eval_report(run_dir)
            if not gold_labels:
                return {}
        gold_cache[gold_spans_path] = gold_labels
    if not gold_labels:
        return {}
    gold_indices = sorted(int(index) for index in gold_labels.keys())
    default_prediction = {index: "OTHER" for index in gold_indices}

    raw_llm_dir = pred_run_dir / "raw" / "llm"
    llm_run_dirs = sorted(path for path in raw_llm_dir.glob("*") if path.is_dir())
    if not llm_run_dirs and raw_llm_dir.is_dir():
        llm_run_dirs = [raw_llm_dir]
    if not llm_run_dirs:
        return {}

    pass2_inputs: dict[str, dict[str, Any]] = {}
    pass2_outputs: dict[str, dict[str, Any]] = {}
    pass3_outputs: dict[str, dict[str, Any]] = {}
    for llm_run_dir in llm_run_dirs:
        pass2_in_dir = llm_run_dir / "pass2_schemaorg" / "in"
        pass2_out_dir = llm_run_dir / "pass2_schemaorg" / "out"
        pass3_out_dir = llm_run_dir / "pass3_final" / "out"

        for path in sorted(pass2_in_dir.glob("*.json")):
            payload = _upload_bundle_load_json_object(path)
            recipe_id = str(payload.get("recipe_id") or "").strip()
            if recipe_id:
                pass2_inputs[recipe_id] = payload
        for path in sorted(pass2_out_dir.glob("*.json")):
            payload = _upload_bundle_load_json_object(path)
            recipe_id = str(payload.get("recipe_id") or "").strip()
            if recipe_id:
                pass2_outputs[recipe_id] = payload
        for path in sorted(pass3_out_dir.glob("*.json")):
            payload = _upload_bundle_load_json_object(path)
            recipe_id = str(payload.get("recipe_id") or "").strip()
            if recipe_id:
                pass3_outputs[recipe_id] = payload

    reports: dict[str, dict[str, Any]] = {}

    pass2_prediction = dict(default_prediction)
    pass2_label_hits = 0
    for recipe_id, pass2_output in pass2_outputs.items():
        pass2_input = pass2_inputs.get(recipe_id)
        if not isinstance(pass2_input, dict):
            continue
        projected_labels = _upload_bundle_project_pass2_recipe_labels(
            pass2_input=pass2_input,
            pass2_output=pass2_output,
        )
        if not projected_labels:
            continue
        for index, label in projected_labels.items():
            if index not in pass2_prediction:
                continue
            pass2_prediction[index] = str(label)
            if str(label) != "OTHER":
                pass2_label_hits += 1
    if pass2_label_hits > 0:
        try:
            reports["pass2"] = compute_block_metrics(gold_labels, pass2_prediction)
        except Exception:  # noqa: BLE001
            reports["pass2"] = {}

    pass3_prediction = dict(default_prediction)
    pass3_label_hits = 0
    recipe_ids = sorted(set(pass2_inputs.keys()) | set(pass2_outputs.keys()) | set(pass3_outputs.keys()))
    for recipe_id in recipe_ids:
        pass2_input = pass2_inputs.get(recipe_id)
        if not isinstance(pass2_input, dict):
            continue
        projected_labels = _upload_bundle_project_pass3_recipe_labels(
            pass2_input=pass2_input,
            pass2_output=pass2_outputs.get(recipe_id),
            pass3_output=pass3_outputs.get(recipe_id),
        )
        if not projected_labels:
            continue
        for index, label in projected_labels.items():
            if index not in pass3_prediction:
                continue
            pass3_prediction[index] = str(label)
            if str(label) != "OTHER":
                pass3_label_hits += 1
    if pass3_label_hits > 0:
        try:
            reports["pass3"] = compute_block_metrics(gold_labels, pass3_prediction)
        except Exception:  # noqa: BLE001
            reports["pass3"] = {}

    return reports


def _upload_bundle_collect_pass_stage_per_label_metrics(
    *,
    comparison_pairs: list[dict[str, Any]],
    run_dir_by_id: dict[str, Path],
) -> dict[str, Any]:
    codex_run_ids: set[str] = set()
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        codex_run = pair.get("codex_run")
        if not isinstance(codex_run, dict):
            continue
        run_id = str(codex_run.get("run_id") or "").strip()
        if run_id:
            codex_run_ids.add(run_id)

    gold_cache: dict[Path, dict[int, set[str]]] = {}
    reports_by_run: dict[str, dict[str, dict[str, Any]]] = {}
    for run_id in sorted(codex_run_ids):
        run_dir = run_dir_by_id.get(run_id)
        if run_dir is None:
            reports_by_run[run_id] = {}
            continue
        reports_by_run[run_id] = _upload_bundle_collect_stage_pass_reports_for_run(
            run_dir=run_dir,
            gold_cache=gold_cache,
        )

    output: dict[str, Any] = {}
    for stage_key in ("pass2", "pass3"):
        labels_agg: dict[str, dict[str, Any]] = {}
        runs_scored = 0
        for run_id in sorted(codex_run_ids):
            report = (reports_by_run.get(run_id) or {}).get(stage_key)
            if not isinstance(report, dict):
                continue
            per_label = report.get("per_label")
            if not isinstance(per_label, dict):
                continue
            runs_scored += 1
            for label, row in per_label.items():
                if not isinstance(label, str) or not isinstance(row, dict):
                    continue
                agg_row = labels_agg.setdefault(
                    label,
                    {
                        "label": label,
                        "_precision": [],
                        "_recall": [],
                        "_f1": [],
                        "gold_total_sum": 0,
                        "pred_total_sum": 0,
                    },
                )
                agg_row["_precision"].append(_coerce_float(row.get("precision")))
                agg_row["_recall"].append(_coerce_float(row.get("recall")))
                agg_row["_f1"].append(_coerce_float(row.get("f1")))
                agg_row["gold_total_sum"] = int(agg_row["gold_total_sum"]) + int(
                    _coerce_int(row.get("gold_total")) or 0
                )
                agg_row["pred_total_sum"] = int(agg_row["pred_total_sum"]) + int(
                    _coerce_int(row.get("pred_total")) or 0
                )

        labels_rows: dict[str, dict[str, Any]] = {}
        for label, row in labels_agg.items():
            labels_rows[label] = {
                "label": label,
                "precision_avg": _average_float(row["_precision"]),
                "recall_avg": _average_float(row["_recall"]),
                "f1_avg": _average_float(row["_f1"]),
                "gold_total_sum": int(row["gold_total_sum"]),
                "pred_total_sum": int(row["pred_total_sum"]),
                "runs_scored": int(runs_scored),
            }
        output[stage_key] = {
            "available": runs_scored > 0,
            "runs_scored": int(runs_scored),
            "labels": labels_rows,
            "unavailable_reason": (
                ""
                if runs_scored > 0
                else (
                    f"{stage_key} stage outputs could not be projected/scored from discovered "
                    "prediction-run codex artifacts"
                )
            ),
        }
    return output


def _upload_bundle_build_per_label_metrics(
    *,
    comparison_pairs: list[dict[str, Any]],
    run_dir_by_id: dict[str, Path],
) -> list[dict[str, Any]]:
    confusion_counter = _upload_bundle_collect_confusion_delta_counts(comparison_pairs)
    per_run_cache: dict[str, dict[str, dict[str, Any]]] = {}

    def _metrics_for_run(run_id: str) -> dict[str, dict[str, Any]]:
        if run_id in per_run_cache:
            return per_run_cache[run_id]
        run_dir = run_dir_by_id.get(run_id)
        if run_dir is None:
            per_run_cache[run_id] = {}
            return {}
        metrics = _upload_bundle_load_run_per_label_metrics(run_dir)
        per_run_cache[run_id] = metrics
        return metrics

    aggregated: dict[str, dict[str, Any]] = {}
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        codex_run = pair.get("codex_run")
        baseline_run = pair.get("baseline_run")
        codex_run_id = (
            str(codex_run.get("run_id") or "")
            if isinstance(codex_run, dict)
            else ""
        )
        baseline_run_id = (
            str(baseline_run.get("run_id") or "")
            if isinstance(baseline_run, dict)
            else ""
        )
        codex_metrics = _metrics_for_run(codex_run_id)
        baseline_metrics = _metrics_for_run(baseline_run_id)
        labels = sorted(set(codex_metrics.keys()) | set(baseline_metrics.keys()))
        for label in labels:
            row = aggregated.setdefault(
                label,
                {
                    "label": label,
                    "pair_count_with_metrics": 0,
                    "_codex_precision": [],
                    "_baseline_precision": [],
                    "_delta_precision": [],
                    "_codex_recall": [],
                    "_baseline_recall": [],
                    "_delta_recall": [],
                    "_codex_f1": [],
                    "_baseline_f1": [],
                    "_delta_f1": [],
                    "gold_total_sum": 0,
                    "pred_total_sum": 0,
                },
            )
            codex_row = codex_metrics.get(label, {})
            baseline_row = baseline_metrics.get(label, {})

            codex_precision = _coerce_float(codex_row.get("precision"))
            baseline_precision = _coerce_float(baseline_row.get("precision"))
            codex_recall = _coerce_float(codex_row.get("recall"))
            baseline_recall = _coerce_float(baseline_row.get("recall"))
            codex_f1 = _coerce_float(codex_row.get("f1"))
            baseline_f1 = _coerce_float(baseline_row.get("f1"))
            if (
                codex_precision is not None
                or baseline_precision is not None
                or codex_recall is not None
                or baseline_recall is not None
                or codex_f1 is not None
                or baseline_f1 is not None
            ):
                row["pair_count_with_metrics"] = int(row["pair_count_with_metrics"]) + 1

            row["_codex_precision"].append(codex_precision)
            row["_baseline_precision"].append(baseline_precision)
            row["_delta_precision"].append(_delta(codex_precision, baseline_precision))
            row["_codex_recall"].append(codex_recall)
            row["_baseline_recall"].append(baseline_recall)
            row["_delta_recall"].append(_delta(codex_recall, baseline_recall))
            row["_codex_f1"].append(codex_f1)
            row["_baseline_f1"].append(baseline_f1)
            row["_delta_f1"].append(_delta(codex_f1, baseline_f1))
            row["gold_total_sum"] = int(row["gold_total_sum"]) + int(
                _coerce_int(codex_row.get("gold_total"))
                or _coerce_int(baseline_row.get("gold_total"))
                or 0
            )
            row["pred_total_sum"] = int(row["pred_total_sum"]) + int(
                _coerce_int(codex_row.get("pred_total"))
                or _coerce_int(baseline_row.get("pred_total"))
                or 0
            )

    output_rows: list[dict[str, Any]] = []
    labels_all = sorted(set(aggregated.keys()))
    for label in labels_all:
        row = aggregated[label]
        outbound = [
            {"pred_label": pred_label, "delta_count": count}
            for (gold_label, pred_label), count in confusion_counter.items()
            if gold_label == label
        ]
        inbound = [
            {"gold_label": gold_label, "delta_count": count}
            for (gold_label, pred_label), count in confusion_counter.items()
            if pred_label == label
        ]
        outbound.sort(
            key=lambda item: (
                -abs(int(item["delta_count"])),
                str(item["pred_label"]),
            )
        )
        inbound.sort(
            key=lambda item: (
                -abs(int(item["delta_count"])),
                str(item["gold_label"]),
            )
        )
        output_rows.append(
            {
                "label": label,
                "pair_count_with_metrics": int(row["pair_count_with_metrics"]),
                "gold_total_sum": int(row["gold_total_sum"]),
                "pred_total_sum": int(row["pred_total_sum"]),
                "codex_precision_avg": _average_float(row["_codex_precision"]),
                "baseline_precision_avg": _average_float(row["_baseline_precision"]),
                "delta_precision_avg": _average_float(row["_delta_precision"]),
                "codex_recall_avg": _average_float(row["_codex_recall"]),
                "baseline_recall_avg": _average_float(row["_baseline_recall"]),
                "delta_recall_avg": _average_float(row["_delta_recall"]),
                "codex_f1_avg": _average_float(row["_codex_f1"]),
                "baseline_f1_avg": _average_float(row["_baseline_f1"]),
                "delta_f1_avg": _average_float(row["_delta_f1"]),
                "confusion_delta_outbound_total": sum(
                    int(item["delta_count"]) for item in outbound
                ),
                "confusion_delta_inbound_total": sum(
                    int(item["delta_count"]) for item in inbound
                ),
                "top_confusion_outbound": outbound[:5],
                "top_confusion_inbound": inbound[:5],
            }
        )
    output_rows.sort(
        key=lambda row: (
            -abs(_float_or_zero(row.get("delta_f1_avg"))),
            -abs(_float_or_zero(row.get("delta_recall_avg"))),
            str(row.get("label") or ""),
        )
    )
    return output_rows


def _upload_bundle_parse_validation_error(reason: str) -> str | None:
    text = str(reason or "").strip()
    if not text:
        return None
    lowered = text.lower()
    keywords = (
        "parse",
        "schema",
        "validation",
        "invalid json",
        "reject",
        "missing schema_v",
    )
    if any(keyword in lowered for keyword in keywords):
        return text
    return None


def _upload_bundle_build_failure_ledger(
    *,
    recipe_triage_rows: list[dict[str, Any]],
    call_inventory_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    retry_counts: Counter[tuple[str, str, str]] = Counter()
    for call_row in call_inventory_rows:
        run_id = str(call_row.get("run_id") or "").strip()
        recipe_id = str(call_row.get("recipe_id") or "").strip()
        pass_name = str(call_row.get("pass") or "").strip().lower()
        if not recipe_id or pass_name not in {"pass1", "pass2", "pass3"}:
            continue
        retry_counts[(run_id, recipe_id, pass_name)] += 1

    rows: list[dict[str, Any]] = []
    for triage_row in recipe_triage_rows:
        recipe_id = str(triage_row.get("recipe_id") or "").strip()
        if not recipe_id:
            continue
        run_id = str(triage_row.get("codex_run_id") or triage_row.get("run_id") or "").strip()
        pass1_status = str(triage_row.get("pass1_status") or "").strip()
        pass2_status = str(triage_row.get("pass2_status") or "").strip()
        pass3_status = str(triage_row.get("pass3_status") or "").strip()
        pass2_reasons = _coerce_str_list(triage_row.get("pass2_degradation_reasons"))
        pass3_fallback_reason = str(triage_row.get("pass3_fallback_reason") or "").strip()
        pass1_clamped_loss = int(
            _coerce_int(triage_row.get("pass1_clamped_block_loss_count")) or 0
        )
        delta = _coerce_float(triage_row.get("delta_codex_minus_baseline"))

        pass_rows = [
            {
                "pass": "pass1",
                "call_id": str(triage_row.get("pass1_call_id") or ""),
                "status": pass1_status or ("degraded" if pass1_clamped_loss > 0 else "ok"),
                "reason": (
                    f"pass1_clamped_block_loss_count={pass1_clamped_loss}"
                    if pass1_clamped_loss > 0
                    else ""
                ),
                "warning_buckets": [],
                "fallback_target": None,
            },
            {
                "pass": "pass2",
                "call_id": str(triage_row.get("pass2_call_id") or ""),
                "status": pass2_status or ("degraded" if pass2_reasons else "ok"),
                "reason": "|".join(pass2_reasons),
                "warning_buckets": _coerce_str_list(
                    triage_row.get("pass2_warning_buckets")
                ),
                "fallback_target": None,
            },
            {
                "pass": "pass3",
                "call_id": str(triage_row.get("pass3_call_id") or ""),
                "status": pass3_status or ("fallback" if pass3_fallback_reason else "ok"),
                "reason": pass3_fallback_reason,
                "warning_buckets": _coerce_str_list(
                    triage_row.get("pass3_warning_buckets")
                ),
                "fallback_target": (
                    "baseline_or_safe_finalizer" if pass3_fallback_reason else None
                ),
            },
            {
                "pass": "final",
                "call_id": "",
                "status": (
                    "fallback"
                    if pass3_fallback_reason
                    else (
                        "regressed"
                        if delta is not None and delta < 0
                        else ("ok" if delta is not None else "unknown")
                    )
                ),
                "reason": (
                    pass3_fallback_reason
                    if pass3_fallback_reason
                    else (
                        f"delta_codex_minus_baseline={_serialize_float(delta)}"
                        if delta is not None
                        else ""
                    )
                ),
                "warning_buckets": [],
                "fallback_target": (
                    "baseline_or_safe_finalizer" if pass3_fallback_reason else None
                ),
            },
        ]

        for pass_row in pass_rows:
            pass_name = str(pass_row["pass"])
            retry_attempted = (
                retry_counts[(run_id, recipe_id, pass_name)] > 1
                if pass_name in {"pass1", "pass2", "pass3"}
                else False
            )
            parse_validation_error = _upload_bundle_parse_validation_error(
                str(pass_row["reason"] or "")
            )
            rows.append(
                {
                    "source_key": str(triage_row.get("source_key") or ""),
                    "source_file": str(triage_row.get("source_file") or ""),
                    "codex_run_id": run_id,
                    "baseline_run_id": str(triage_row.get("baseline_run_id") or ""),
                    "recipe_id": recipe_id,
                    "short_title": str(triage_row.get("short_title") or ""),
                    "pass": pass_name,
                    "call_id": str(pass_row["call_id"] or ""),
                    "status": str(pass_row["status"] or "unknown"),
                    "reason": str(pass_row["reason"] or ""),
                    "warning_buckets": list(pass_row["warning_buckets"] or []),
                    "retry_attempted": bool(retry_attempted),
                    "fallback_target": pass_row["fallback_target"],
                    "parse_validation_error": parse_validation_error,
                }
            )

    pass_status_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        pass_status_counts[str(row["pass"])][str(row["status"])] += 1
    return {
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "recipe_count": len(
                {
                    (str(row.get("codex_run_id") or ""), str(row.get("recipe_id") or ""))
                    for row in rows
                    if str(row.get("recipe_id") or "")
                }
            ),
            "pass_status_counts": {
                pass_name: _counter_to_sorted_dict(counter)
                for pass_name, counter in sorted(pass_status_counts.items())
            },
        },
    }


def _upload_bundle_nested_numeric(
    payload: Any,
    paths: tuple[tuple[str, ...], ...],
    *,
    integer: bool = False,
) -> int | float | None:
    for path in paths:
        current: Any = payload
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if integer:
            value = _coerce_int(current)
            if value is not None:
                return value
        else:
            value = _coerce_float(current)
            if value is not None:
                return value
    return None


def _upload_bundle_extract_call_runtime(row: dict[str, Any]) -> dict[str, Any]:
    request_telemetry = row.get("request_telemetry")
    request_telemetry = request_telemetry if isinstance(request_telemetry, dict) else {}
    usage_payload = request_telemetry.get("usage_json")
    usage_payload = usage_payload if isinstance(usage_payload, dict) else {}

    duration_ms = _upload_bundle_nested_numeric(
        request_telemetry,
        (
            ("duration_ms",),
            ("duration",),
        ),
        integer=True,
    )
    tokens_input = _upload_bundle_nested_numeric(
        request_telemetry,
        (("tokens_input",),),
        integer=True,
    )
    if tokens_input is None:
        tokens_input = _upload_bundle_nested_numeric(
            usage_payload,
            (("input_tokens",), ("prompt_tokens",), ("tokens_input",)),
            integer=True,
        )
    tokens_cached_input = _upload_bundle_nested_numeric(
        request_telemetry,
        (("tokens_cached_input",),),
        integer=True,
    )
    if tokens_cached_input is None:
        tokens_cached_input = _upload_bundle_nested_numeric(
            usage_payload,
            (("cached_input_tokens",),),
            integer=True,
        )
    tokens_output = _upload_bundle_nested_numeric(
        request_telemetry,
        (("tokens_output",),),
        integer=True,
    )
    if tokens_output is None:
        tokens_output = _upload_bundle_nested_numeric(
            usage_payload,
            (("output_tokens",), ("completion_tokens",), ("tokens_output",)),
            integer=True,
        )
    tokens_reasoning = _upload_bundle_nested_numeric(
        request_telemetry,
        (("tokens_reasoning",),),
        integer=True,
    )
    if tokens_reasoning is None:
        tokens_reasoning = _upload_bundle_nested_numeric(
            usage_payload,
            (
                ("output_tokens_reasoning",),
                ("output_tokens_details", "reasoning_tokens"),
                ("completion_tokens_details", "reasoning_tokens"),
            ),
            integer=True,
        )
    tokens_total = _upload_bundle_nested_numeric(
        request_telemetry,
        (("tokens_total",),),
        integer=True,
    )
    if tokens_total is None:
        tokens_total = _upload_bundle_nested_numeric(
            usage_payload,
            (
                ("total_tokens",),
                ("tokens_total",),
            ),
            integer=True,
        )
    if tokens_total is None and (tokens_input is not None or tokens_output is not None):
        tokens_total = int(tokens_input or 0) + int(tokens_output or 0)

    cost_usd = _upload_bundle_nested_numeric(
        usage_payload,
        (
            ("cost_usd",),
            ("total_cost_usd",),
            ("estimated_cost_usd",),
            ("estimated_cost",),
            ("cost", "total_usd"),
            ("cost", "usd"),
        ),
    )
    if cost_usd is None:
        cost_usd = _upload_bundle_nested_numeric(
            request_telemetry,
            (
                ("cost_usd",),
                ("total_cost_usd",),
                ("estimated_cost_usd",),
                ("estimated_cost",),
                ("cost",),
            ),
        )

    return {
        "duration_ms": duration_ms,
        "tokens_input": tokens_input,
        "tokens_cached_input": tokens_cached_input,
        "tokens_output": tokens_output,
        "tokens_reasoning": tokens_reasoning,
        "tokens_total": tokens_total,
        "cost_usd": cost_usd,
        "attempt_index": _coerce_int(request_telemetry.get("attempt_index")),
        "status": str(request_telemetry.get("status") or "").strip() or None,
    }


def _upload_bundle_estimate_call_cost_usd(
    *,
    tokens_input: int | None,
    tokens_cached_input: int | None,
    tokens_output: int | None,
) -> float | None:
    if tokens_input is None and tokens_output is None:
        return None
    input_tokens = int(tokens_input or 0)
    cached_tokens = int(tokens_cached_input or 0)
    if cached_tokens < 0:
        cached_tokens = 0
    if cached_tokens > input_tokens:
        cached_tokens = input_tokens
    uncached_tokens = max(input_tokens - cached_tokens, 0)
    output_tokens = int(tokens_output or 0)
    pricing = UPLOAD_BUNDLE_ESTIMATED_COST_DEFAULT_PRICING
    total_cost = (
        (uncached_tokens / 1_000_000.0) * float(pricing["input_per_1m"])
        + (cached_tokens / 1_000_000.0) * float(pricing["cached_input_per_1m"])
        + (output_tokens / 1_000_000.0) * float(pricing["output_per_1m"])
    )
    return round(total_cost, 8)


def _upload_bundle_collect_call_runtime_map(
    *,
    run_dir_by_id: dict[str, Path],
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    runtime_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for run_id, run_dir in sorted(run_dir_by_id.items()):
        run_manifest_path = run_dir / "run_manifest.json"
        if not run_manifest_path.is_file():
            continue
        run_manifest = _upload_bundle_load_json_object(run_manifest_path)
        full_prompt_path = _resolve_full_prompt_log_path(run_dir, run_manifest)
        if full_prompt_path is None or not full_prompt_path.is_file():
            continue
        for prompt_row in _iter_jsonl(full_prompt_path):
            pass_name = str(prompt_row.get("pass") or "").strip().lower()
            call_id = str(prompt_row.get("call_id") or "").strip()
            recipe_id = str(prompt_row.get("recipe_id") or "").strip()
            if pass_name not in {"pass1", "pass2", "pass3"} or not call_id:
                continue
            key = (
                str(prompt_row.get("run_id") or run_id).strip() or run_id,
                recipe_id,
                pass_name,
                call_id,
            )
            runtime_payload = _upload_bundle_extract_call_runtime(prompt_row)
            existing = runtime_by_key.get(key)
            if existing is None:
                runtime_by_key[key] = runtime_payload
                continue
            existing_attempt = _coerce_int(existing.get("attempt_index")) or -1
            next_attempt = _coerce_int(runtime_payload.get("attempt_index")) or -1
            if next_attempt >= existing_attempt:
                runtime_by_key[key] = runtime_payload
    return runtime_by_key


def _upload_bundle_telemetry_call_count(summary: dict[str, Any]) -> int | None:
    call_count = _coerce_int(summary.get("call_count"))
    if call_count is not None:
        return max(int(call_count), 0)
    status_counts = summary.get("status_counts")
    if isinstance(status_counts, dict):
        raw_values = [_coerce_int(value) for value in status_counts.values()]
        if any(value is not None for value in raw_values):
            return int(sum(int(value or 0) for value in raw_values))
    matched_rows = _coerce_int(summary.get("matched_rows"))
    if matched_rows is not None:
        return max(int(matched_rows), 0)
    return None


def _upload_bundle_token_share_fields(
    *,
    by_pass: dict[str, dict[str, Any]],
    total_tokens: int | None,
) -> dict[str, float | None]:
    fields: dict[str, float | None] = {}
    for pass_name in ("pass1", "pass2", "pass3"):
        share_key = f"{pass_name}_token_share"
        pass_payload = by_pass.get(pass_name)
        pass_payload = pass_payload if isinstance(pass_payload, dict) else {}
        pass_tokens = _coerce_int(pass_payload.get("total_tokens"))
        if (
            total_tokens is None
            or total_tokens <= 0
            or pass_tokens is None
            or pass_tokens < 0
        ):
            fields[share_key] = None
            continue
        fields[share_key] = round(float(pass_tokens) / float(total_tokens), 4)
    return fields


def _upload_bundle_build_call_runtime_inventory_from_prediction_manifest(
    *,
    run_dir_by_id: dict[str, Path],
) -> dict[str, Any] | None:
    aggregate_by_pass: dict[str, dict[str, Any]] = {}
    for run_id, run_dir in sorted(run_dir_by_id.items()):
        run_manifest_path = run_dir / "run_manifest.json"
        if not run_manifest_path.is_file():
            continue
        run_manifest = _upload_bundle_load_json_object(run_manifest_path)
        pred_run_dir = _resolve_prediction_run_dir(run_dir, run_manifest)
        if pred_run_dir is None:
            continue
        pred_manifest_path = pred_run_dir / "manifest.json"
        if not pred_manifest_path.is_file():
            continue
        pred_manifest = _upload_bundle_load_json_object(pred_manifest_path)
        llm_payload = (
            pred_manifest.get("llm_codex_farm") if isinstance(pred_manifest, dict) else {}
        )
        llm_payload = llm_payload if isinstance(llm_payload, dict) else {}
        process_runs = llm_payload.get("process_runs")
        process_runs = process_runs if isinstance(process_runs, dict) else {}
        for pass_name in ("pass1", "pass2", "pass3"):
            pass_payload = process_runs.get(pass_name)
            pass_payload = pass_payload if isinstance(pass_payload, dict) else {}
            telemetry_report = pass_payload.get("telemetry_report")
            telemetry_report = telemetry_report if isinstance(telemetry_report, dict) else {}
            summary = telemetry_report.get("summary")
            if not isinstance(summary, dict):
                continue
            bucket = aggregate_by_pass.setdefault(
                pass_name,
                {
                    "call_count": 0,
                    "calls_known": False,
                    "duration_total_ms": 0,
                    "duration_known": False,
                    "tokens_total": 0,
                    "tokens_known": False,
                },
            )
            call_count = _upload_bundle_telemetry_call_count(summary)
            if call_count is not None:
                bucket["call_count"] += max(int(call_count), 0)
                bucket["calls_known"] = True
            duration_total_ms = _coerce_int(summary.get("duration_total_ms"))
            if duration_total_ms is None:
                duration_avg_ms = _coerce_float(summary.get("duration_avg_ms"))
                if (
                    duration_avg_ms is not None
                    and call_count is not None
                    and int(call_count) > 0
                ):
                    duration_total_ms = int(round(float(duration_avg_ms) * int(call_count)))
            if duration_total_ms is not None:
                bucket["duration_total_ms"] += max(int(duration_total_ms), 0)
                bucket["duration_known"] = True
            tokens_total = _coerce_int(summary.get("tokens_total"))
            if tokens_total is not None:
                bucket["tokens_total"] += max(int(tokens_total), 0)
                bucket["tokens_known"] = True

    if not aggregate_by_pass:
        return None

    by_pass: dict[str, dict[str, Any]] = {}
    for pass_name in sorted(aggregate_by_pass.keys()):
        bucket = aggregate_by_pass.get(pass_name)
        if not isinstance(bucket, dict):
            continue
        call_count = int(bucket.get("call_count") or 0)
        calls_known = bool(bucket.get("calls_known"))
        duration_known = bool(bucket.get("duration_known"))
        tokens_known = bool(bucket.get("tokens_known"))
        duration_total_ms = (
            int(bucket.get("duration_total_ms") or 0) if duration_known else None
        )
        by_pass[pass_name] = {
            "call_count": call_count if calls_known else 0,
            "calls_with_runtime": call_count if calls_known and duration_known else 0,
            "calls_with_cost": 0,
            "calls_with_estimated_cost": 0,
            "avg_duration_ms": (
                round(float(duration_total_ms) / float(call_count), 3)
                if duration_total_ms is not None and calls_known and call_count > 0
                else None
            ),
            "total_tokens": int(bucket.get("tokens_total") or 0) if tokens_known else None,
            "total_cost_usd": None,
            "total_estimated_cost_usd": None,
            "cost_coverage_ratio": 0.0,
            "estimated_cost_coverage_ratio": 0.0,
        }

    total_calls = int(sum(int(payload.get("call_count") or 0) for payload in by_pass.values()))
    total_calls_with_runtime = int(
        sum(int(payload.get("calls_with_runtime") or 0) for payload in by_pass.values())
    )
    duration_totals = [
        int(bucket.get("duration_total_ms") or 0)
        for bucket in aggregate_by_pass.values()
        if bool(bucket.get("duration_known"))
    ]
    total_duration_ms = int(sum(duration_totals)) if duration_totals else None
    token_totals = [
        _coerce_int(payload.get("total_tokens"))
        for payload in by_pass.values()
        if _coerce_int(payload.get("total_tokens")) is not None
    ]
    total_tokens = int(sum(token_totals)) if token_totals else None
    summary = {
        "call_count": total_calls,
        "calls_with_runtime": total_calls_with_runtime,
        "calls_with_cost": 0,
        "calls_with_estimated_cost": 0,
        "total_duration_ms": total_duration_ms,
        "avg_duration_ms": (
            round(float(total_duration_ms) / float(total_calls_with_runtime), 3)
            if total_duration_ms is not None and total_calls_with_runtime > 0
            else None
        ),
        "total_tokens": total_tokens,
        "total_cost_usd": None,
        "total_estimated_cost_usd": None,
        "cost_coverage_ratio": 0.0,
        "estimated_cost_coverage_ratio": 0.0,
        "cost_signal": {
            "available": False,
            "calls_with_cost": 0,
            "coverage_ratio": 0.0,
            "unavailable_reason": (
                "prediction-run telemetry summaries do not expose per-call observed cost fields"
            ),
        },
        "estimated_cost_signal": {
            "available": False,
            "calls_with_estimated_cost": 0,
            "coverage_ratio": 0.0,
            "method": "",
            "pricing_used": dict(UPLOAD_BUNDLE_ESTIMATED_COST_DEFAULT_PRICING),
            "note": (
                "No per-call token telemetry available; aggregate pass totals cannot be "
                "reliably cost-estimated per call."
            ),
        },
        "by_pass": by_pass,
        "runtime_source": "prediction_run_manifest_telemetry",
    }
    summary.update(
        _upload_bundle_token_share_fields(by_pass=by_pass, total_tokens=total_tokens)
    )
    return {
        "summary": summary,
        "top_slowest_calls": [],
        "top_token_calls": [],
        "top_cost_calls": [],
        "top_estimated_cost_calls": [],
    }


def _upload_bundle_build_call_runtime_inventory(
    *,
    call_inventory_rows: list[dict[str, Any]],
    run_dir_by_id: dict[str, Path],
) -> dict[str, Any]:
    runtime_by_key = _upload_bundle_collect_call_runtime_map(run_dir_by_id=run_dir_by_id)
    enriched_rows: list[dict[str, Any]] = []
    for row in call_inventory_rows:
        run_id = str(row.get("run_id") or "").strip()
        recipe_id = str(row.get("recipe_id") or "").strip()
        pass_name = str(row.get("pass") or "").strip().lower()
        call_id = str(row.get("call_id") or "").strip()
        runtime = runtime_by_key.get((run_id, recipe_id, pass_name, call_id), {})
        observed_cost_usd = _coerce_float(runtime.get("cost_usd"))
        estimated_cost_usd = (
            observed_cost_usd
            if observed_cost_usd is not None
            else _upload_bundle_estimate_call_cost_usd(
                tokens_input=_coerce_int(runtime.get("tokens_input")),
                tokens_cached_input=_coerce_int(runtime.get("tokens_cached_input")),
                tokens_output=_coerce_int(runtime.get("tokens_output")),
            )
        )
        enriched_rows.append(
            {
                **row,
                "duration_ms": _coerce_int(runtime.get("duration_ms")),
                "tokens_input": _coerce_int(runtime.get("tokens_input")),
                "tokens_cached_input": _coerce_int(runtime.get("tokens_cached_input")),
                "tokens_output": _coerce_int(runtime.get("tokens_output")),
                "tokens_reasoning": _coerce_int(runtime.get("tokens_reasoning")),
                "tokens_total": _coerce_int(runtime.get("tokens_total")),
                "cost_usd": observed_cost_usd,
                "estimated_cost_usd": estimated_cost_usd,
                "cost_source": (
                    "observed_telemetry"
                    if observed_cost_usd is not None
                    else (
                        "estimated_from_tokens_default_pricing"
                        if estimated_cost_usd is not None
                        else None
                    )
                ),
                "retry_attempt": _coerce_int(runtime.get("attempt_index")),
                "runtime_status": runtime.get("status"),
            }
        )

    if not enriched_rows:
        telemetry_fallback = _upload_bundle_build_call_runtime_inventory_from_prediction_manifest(
            run_dir_by_id=run_dir_by_id
        )
        if telemetry_fallback is not None:
            return telemetry_fallback

    duration_values = [
        _coerce_int(row.get("duration_ms"))
        for row in enriched_rows
        if _coerce_int(row.get("duration_ms")) is not None
    ]
    token_totals = [
        _coerce_int(row.get("tokens_total"))
        for row in enriched_rows
        if _coerce_int(row.get("tokens_total")) is not None
    ]
    cost_values = [
        _coerce_float(row.get("cost_usd"))
        for row in enriched_rows
        if _coerce_float(row.get("cost_usd")) is not None
    ]
    estimated_cost_values = [
        _coerce_float(row.get("estimated_cost_usd"))
        for row in enriched_rows
        if _coerce_float(row.get("estimated_cost_usd")) is not None
    ]
    calls_with_cost = len(cost_values)
    cost_coverage_ratio = (
        round(calls_with_cost / len(enriched_rows), 6) if enriched_rows else 0.0
    )
    calls_with_estimated_cost = len(estimated_cost_values)
    estimated_cost_coverage_ratio = (
        round(calls_with_estimated_cost / len(enriched_rows), 6)
        if enriched_rows
        else 0.0
    )
    by_pass: dict[str, dict[str, Any]] = {}
    pass_names = sorted(
        {
            str(row.get("pass") or "").strip().lower()
            for row in enriched_rows
            if str(row.get("pass") or "").strip()
        }
    )
    for pass_name in pass_names:
        pass_rows = [
            row
            for row in enriched_rows
            if str(row.get("pass") or "").strip().lower() == pass_name
        ]
        pass_duration = [
            _coerce_int(row.get("duration_ms"))
            for row in pass_rows
            if _coerce_int(row.get("duration_ms")) is not None
        ]
        pass_tokens = [
            _coerce_int(row.get("tokens_total"))
            for row in pass_rows
            if _coerce_int(row.get("tokens_total")) is not None
        ]
        pass_cost = [
            _coerce_float(row.get("cost_usd"))
            for row in pass_rows
            if _coerce_float(row.get("cost_usd")) is not None
        ]
        pass_estimated_cost = [
            _coerce_float(row.get("estimated_cost_usd"))
            for row in pass_rows
            if _coerce_float(row.get("estimated_cost_usd")) is not None
        ]
        pass_calls_with_cost = len(pass_cost)
        pass_calls_with_estimated_cost = len(pass_estimated_cost)
        by_pass[pass_name] = {
            "call_count": len(pass_rows),
            "calls_with_runtime": len(pass_duration),
            "calls_with_cost": pass_calls_with_cost,
            "calls_with_estimated_cost": pass_calls_with_estimated_cost,
            "avg_duration_ms": (
                round(sum(pass_duration) / len(pass_duration), 3)
                if pass_duration
                else None
            ),
            "total_tokens": int(sum(pass_tokens)) if pass_tokens else None,
            "total_cost_usd": (
                round(float(sum(pass_cost)), 8) if pass_cost else None
            ),
            "total_estimated_cost_usd": (
                round(float(sum(pass_estimated_cost)), 8)
                if pass_estimated_cost
                else None
            ),
            "cost_coverage_ratio": (
                round(pass_calls_with_cost / len(pass_rows), 6) if pass_rows else 0.0
            ),
            "estimated_cost_coverage_ratio": (
                round(pass_calls_with_estimated_cost / len(pass_rows), 6)
                if pass_rows
                else 0.0
            ),
        }

    top_slowest = sorted(
        [row for row in enriched_rows if _coerce_int(row.get("duration_ms")) is not None],
        key=lambda row: (
            -int(_coerce_int(row.get("duration_ms")) or 0),
            str(row.get("run_id") or ""),
            str(row.get("call_id") or ""),
        ),
    )[:12]
    top_token = sorted(
        [row for row in enriched_rows if _coerce_int(row.get("tokens_total")) is not None],
        key=lambda row: (
            -int(_coerce_int(row.get("tokens_total")) or 0),
            str(row.get("run_id") or ""),
            str(row.get("call_id") or ""),
        ),
    )[:12]
    top_cost = sorted(
        [row for row in enriched_rows if _coerce_float(row.get("cost_usd")) is not None],
        key=lambda row: (
            -float(_coerce_float(row.get("cost_usd")) or 0.0),
            str(row.get("run_id") or ""),
            str(row.get("call_id") or ""),
        ),
    )[:12]
    top_estimated_cost = sorted(
        [
            row
            for row in enriched_rows
            if _coerce_float(row.get("estimated_cost_usd")) is not None
        ],
        key=lambda row: (
            -float(_coerce_float(row.get("estimated_cost_usd")) or 0.0),
            str(row.get("run_id") or ""),
            str(row.get("call_id") or ""),
        ),
    )[:12]

    total_tokens = int(sum(token_totals)) if token_totals else None
    summary = {
        "call_count": len(enriched_rows),
        "calls_with_runtime": len(duration_values),
        "calls_with_cost": calls_with_cost,
        "calls_with_estimated_cost": calls_with_estimated_cost,
        "total_duration_ms": int(sum(duration_values)) if duration_values else None,
        "avg_duration_ms": (
            round(sum(duration_values) / len(duration_values), 3)
            if duration_values
            else None
        ),
        "total_tokens": total_tokens,
        "total_cost_usd": (
            round(float(sum(cost_values)), 8) if cost_values else None
        ),
        "total_estimated_cost_usd": (
            round(float(sum(estimated_cost_values)), 8)
            if estimated_cost_values
            else None
        ),
        "cost_coverage_ratio": cost_coverage_ratio,
        "estimated_cost_coverage_ratio": estimated_cost_coverage_ratio,
        "cost_signal": {
            "available": calls_with_cost > 0,
            "calls_with_cost": calls_with_cost,
            "coverage_ratio": cost_coverage_ratio,
            "unavailable_reason": (
                ""
                if calls_with_cost > 0
                else (
                    "request telemetry does not include recognized cost fields "
                    "(cost_usd/total_cost_usd/estimated_cost_usd)"
                )
            ),
        },
        "estimated_cost_signal": {
            "available": calls_with_estimated_cost > 0,
            "calls_with_estimated_cost": calls_with_estimated_cost,
            "coverage_ratio": estimated_cost_coverage_ratio,
            "method": (
                "observed_or_default_token_pricing_estimate"
                if calls_with_estimated_cost > 0
                else ""
            ),
            "pricing_used": dict(UPLOAD_BUNDLE_ESTIMATED_COST_DEFAULT_PRICING),
            "note": (
                "Estimated costs use default token pricing and are not billing truth."
                if calls_with_estimated_cost > 0
                else "No token-based estimate available because token telemetry is missing."
            ),
        },
        "by_pass": by_pass,
        "runtime_source": "call_inventory_rows",
    }
    summary.update(
        _upload_bundle_token_share_fields(by_pass=by_pass, total_tokens=total_tokens)
    )

    return {
        "summary": summary,
        "top_slowest_calls": top_slowest,
        "top_token_calls": top_token,
        "top_cost_calls": top_cost,
        "top_estimated_cost_calls": top_estimated_cost,
    }


def _upload_bundle_quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if q <= 0:
        return float(values[0])
    if q >= 1:
        return float(values[-1])
    position = (len(values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return float(values[lower] * (1.0 - weight) + values[upper] * weight)


def _upload_bundle_build_line_role_confidence_summary(
    *,
    source_root: Path,
    run_dir_by_id: dict[str, Path],
) -> dict[str, Any]:
    file_paths: list[Path] = []
    for run_dir in run_dir_by_id.values():
        candidate = run_dir / "line-role-pipeline" / "line_role_predictions.jsonl"
        if candidate.is_file():
            file_paths.append(candidate)
    if not file_paths:
        return {
            "available": False,
            "line_role_prediction_files": [],
            "reason": "line-role-pipeline/line_role_predictions.jsonl not found in discovered run roots",
        }

    decided_by_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    confidence_values: list[float] = []
    low_confidence_examples: list[dict[str, Any]] = []
    low_confidence_by_label: Counter[str] = Counter()
    low_confidence_by_decided_by: Counter[str] = Counter()
    candidate_label_rows = 0
    candidate_label_counts: Counter[str] = Counter()
    total_rows = 0

    for path in sorted(file_paths):
        for row in _iter_jsonl(path):
            total_rows += 1
            label = str(row.get("label") or "").strip().upper() or "OTHER"
            decided_by = str(row.get("decided_by") or "").strip().lower() or "unknown"
            confidence = _coerce_float(row.get("confidence"))
            label_counts[label] += 1
            decided_by_counts[decided_by] += 1
            if confidence is not None:
                confidence_values.append(float(confidence))
            candidate_labels = _upload_bundle_extract_candidate_labels(row)
            if candidate_labels:
                candidate_label_rows += 1
                for candidate in candidate_labels:
                    candidate_label_counts[candidate] += 1
            if (
                confidence is not None
                and confidence < UPLOAD_BUNDLE_LOW_CONFIDENCE_THRESHOLD
            ):
                low_confidence_by_label[label] += 1
                low_confidence_by_decided_by[decided_by] += 1
                low_confidence_examples.append(
                    {
                        "run_id": str(row.get("run_id") or ""),
                        "recipe_id": str(row.get("recipe_id") or ""),
                        "line_index": _coerce_int(row.get("line_index")),
                        "atomic_index": _coerce_int(row.get("atomic_index")),
                        "label": label,
                        "decided_by": decided_by,
                        "confidence": float(confidence),
                        "text_excerpt": _excerpt(
                            str(row.get("text") or ""),
                            max_len=220,
                        ),
                    }
                )

    confidence_values.sort()
    low_confidence_examples.sort(
        key=lambda row: (
            _float_or_zero(row.get("confidence")),
            str(row.get("recipe_id") or ""),
            int(_coerce_int(row.get("line_index")) or 0),
        )
    )
    relative_paths = [
        str(path.relative_to(source_root).as_posix())
        for path in sorted(file_paths)
        if path.is_relative_to(source_root)
    ]
    return {
        "available": True,
        "line_role_prediction_files": relative_paths,
        "row_count": total_rows,
        "decided_by_counts": _counter_to_sorted_dict(decided_by_counts),
        "label_counts": _counter_to_sorted_dict(label_counts),
        "confidence_stats": {
            "min": confidence_values[0] if confidence_values else None,
            "p25": _upload_bundle_quantile(confidence_values, 0.25),
            "p50": _upload_bundle_quantile(confidence_values, 0.50),
            "p75": _upload_bundle_quantile(confidence_values, 0.75),
            "max": confidence_values[-1] if confidence_values else None,
            "avg": (
                round(sum(confidence_values) / len(confidence_values), 6)
                if confidence_values
                else None
            ),
        },
        "candidate_label_signal": {
            "available": candidate_label_rows > 0,
            "rows_with_candidate_labels": candidate_label_rows,
            "top_candidate_labels": [
                {"label": label, "count": count}
                for label, count in candidate_label_counts.most_common(12)
            ],
            "unavailable_reason": (
                ""
                if candidate_label_rows > 0
                else (
                    "line-role predictions do not include recognized candidate-label fields "
                    "(candidate_labels/label_candidates/candidates/label_scores)"
                )
            ),
        },
        "selective_escalation_signal": {
            "low_confidence_threshold": UPLOAD_BUNDLE_LOW_CONFIDENCE_THRESHOLD,
            "low_confidence_row_count": int(sum(low_confidence_by_label.values())),
            "low_confidence_ratio": (
                round(sum(low_confidence_by_label.values()) / total_rows, 6)
                if total_rows > 0
                else 0.0
            ),
            "low_confidence_by_label": _counter_to_sorted_dict(low_confidence_by_label),
            "low_confidence_by_decided_by": _counter_to_sorted_dict(
                low_confidence_by_decided_by
            ),
        },
        "low_confidence_examples": low_confidence_examples[:24],
    }


def _upload_bundle_extract_candidate_labels(row: dict[str, Any]) -> list[str]:
    def _normalize_candidate(value: Any) -> str | None:
        if isinstance(value, str):
            text = value.strip().upper()
            return text or None
        if isinstance(value, dict):
            for key in ("label", "name", "pred_label", "candidate"):
                text = str(value.get(key) or "").strip().upper()
                if text:
                    return text
        return None

    labels: list[str] = []
    for field_name in (
        "candidate_labels",
        "label_candidates",
        "candidates",
        "top_candidates",
    ):
        payload = row.get(field_name)
        if isinstance(payload, list):
            for item in payload:
                normalized = _normalize_candidate(item)
                if normalized:
                    labels.append(normalized)
    for field_name in ("candidate_label_scores", "label_scores", "candidate_distribution"):
        payload = row.get(field_name)
        if isinstance(payload, dict):
            for label in payload.keys():
                normalized = _normalize_candidate(label)
                if normalized:
                    labels.append(normalized)
    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        if label in seen:
            continue
        seen.add(label)
        deduped.append(label)
    return deduped


def _upload_bundle_safe_run_subdir(value: str) -> str:
    rendered = re.sub(r"[^0-9A-Za-z._-]+", "_", str(value or "").strip())
    return rendered or "run"


def _upload_bundle_derive_run_diagnostic_statuses(
    *,
    run_dir: Path,
    run_id: str,
    output_subdir: str,
    append_virtual_payload_row: Any,
) -> dict[str, str]:
    statuses: dict[str, str] = {}
    if not run_dir.is_dir():
        return statuses

    run_manifest_path = run_dir / "run_manifest.json"
    if not run_manifest_path.is_file():
        return statuses

    try:
        run_manifest = _load_json(run_manifest_path)
    except Exception:  # noqa: BLE001
        return statuses

    run_config = run_manifest.get("run_config")
    run_config = run_config if isinstance(run_config, dict) else {}
    llm_recipe_pipeline = str(run_config.get("llm_recipe_pipeline") or "").strip().lower()
    codex_enabled = llm_recipe_pipeline not in {"", "off", "none"}

    full_prompt_rows: list[dict[str, Any]] = []
    recipe_spans: list[dict[str, Any]] = []
    full_prompt_log_path = _resolve_full_prompt_log_path(run_dir, run_manifest)
    if full_prompt_log_path is not None and full_prompt_log_path.is_file():
        full_prompt_rows = _iter_jsonl(full_prompt_log_path)
        if full_prompt_rows:
            recipe_spans = _build_recipe_spans_from_full_prompt_rows(full_prompt_rows)

    derived_dir = (
        f"{UPLOAD_BUNDLE_DERIVED_DIR_NAME}/runs/"
        f"{_upload_bundle_safe_run_subdir(output_subdir or run_id)}"
    )
    wrong_context_name = WRONG_LABEL_FULL_CONTEXT_FILE_NAME.replace(".gz", "")
    preprocess_name = PREPROCESS_TRACE_FAILURES_FILE_NAME.replace(".gz", "")

    if codex_enabled:
        if full_prompt_log_path is not None and full_prompt_log_path.is_file():
            try:
                prompt_warning_aggregate = _summarize_prompt_warning_aggregate(full_prompt_log_path)
                append_virtual_payload_row(
                    path=f"{derived_dir}/{PROMPT_WARNING_AGGREGATE_FILE_NAME}",
                    content_type="json",
                    content_json=prompt_warning_aggregate,
                )
                statuses[PROMPT_WARNING_AGGREGATE_FILE_NAME] = "written"
            except Exception:  # noqa: BLE001
                statuses[PROMPT_WARNING_AGGREGATE_FILE_NAME] = "derivation_error"

            try:
                line_view = _build_line_prediction_view(run_dir=run_dir, recipe_spans=recipe_spans)
                projection_trace = _build_projection_trace(
                    line_view=line_view,
                    full_prompt_rows=full_prompt_rows,
                )
                projection_trace["recipe_span_count"] = len(recipe_spans)
                projection_trace["recipe_spans"] = recipe_spans
                append_virtual_payload_row(
                    path=f"{derived_dir}/{PROJECTION_TRACE_FILE_NAME}",
                    content_type="json",
                    content_json=projection_trace,
                )
                statuses[PROJECTION_TRACE_FILE_NAME] = "written"
            except Exception:  # noqa: BLE001
                statuses[PROJECTION_TRACE_FILE_NAME] = "derivation_error"
        else:
            statuses[PROMPT_WARNING_AGGREGATE_FILE_NAME] = "missing_full_prompt_log"
            statuses[PROJECTION_TRACE_FILE_NAME] = "missing_full_prompt_log"

    wrong_label_total_rows = _jsonl_row_count(run_dir / "wrong_label_lines.jsonl")
    if wrong_label_total_rows <= 0:
        statuses[WRONG_LABEL_FULL_CONTEXT_FILE_NAME] = "not_applicable"
        statuses[PREPROCESS_TRACE_FAILURES_FILE_NAME] = "not_applicable"
        return statuses

    try:
        wrong_label_rows = _build_wrong_label_full_context_rows(
            run_dir=run_dir,
            recipe_spans=recipe_spans,
            excerpt_limit=DEFAULT_EXCERPT_LIMIT,
        )
    except Exception:  # noqa: BLE001
        wrong_label_rows = []

    if wrong_label_rows:
        append_virtual_payload_row(
            path=f"{derived_dir}/{wrong_context_name}",
            content_type="jsonl",
            content_jsonl_rows=wrong_label_rows,
        )
        statuses[WRONG_LABEL_FULL_CONTEXT_FILE_NAME] = "written"
    else:
        statuses[WRONG_LABEL_FULL_CONTEXT_FILE_NAME] = "not_applicable"

    if not codex_enabled:
        statuses[PREPROCESS_TRACE_FAILURES_FILE_NAME] = "not_applicable"
        return statuses

    try:
        preprocess_rows, preprocess_status = _build_preprocess_trace_failure_rows(
            run_dir=run_dir,
            run_manifest=run_manifest,
            full_prompt_rows=full_prompt_rows,
            excerpt_limit=DEFAULT_EXCERPT_LIMIT,
        )
    except Exception:  # noqa: BLE001
        preprocess_rows = []
        preprocess_status = "derivation_error"

    if preprocess_status == "ready" and preprocess_rows:
        append_virtual_payload_row(
            path=f"{derived_dir}/{preprocess_name}",
            content_type="jsonl",
            content_jsonl_rows=preprocess_rows,
        )
        statuses[PREPROCESS_TRACE_FAILURES_FILE_NAME] = "written"
    else:
        statuses[PREPROCESS_TRACE_FAILURES_FILE_NAME] = (
            preprocess_status if preprocess_status != "ready" else "not_applicable"
        )
    return statuses


def _upload_bundle_matches_recipe_target(recipe_id: str, target: str) -> bool:
    recipe_text = recipe_id.strip().lower()
    target_text = target.strip().lower()
    if not recipe_text or not target_text:
        return False
    if recipe_text == target_text:
        return True
    if recipe_text.endswith(f":{target_text}"):
        return True
    return recipe_text.endswith(target_text)


def _upload_bundle_build_regression_casebook(
    *,
    recipe_triage_rows: list[dict[str, Any]],
    changed_line_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    requested_targets = ["c6", "c9", "c12", "c3"]
    selected_rows: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str, str]] = set()

    sorted_worst = sorted(
        recipe_triage_rows,
        key=lambda row: (
            _float_or_zero(row.get("delta_codex_minus_baseline")),
            -int(_coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0),
            str(row.get("recipe_id") or ""),
        ),
    )

    for target in requested_targets:
        for row in sorted_worst:
            recipe_id = str(row.get("recipe_id") or "")
            if not _upload_bundle_matches_recipe_target(recipe_id, target):
                continue
            key = _recipe_row_key(row)
            if key in selected_keys:
                continue
            row_copy = dict(row)
            row_copy["selection_reason"] = f"targeted_regression_id:{target}"
            selected_rows.append(row_copy)
            selected_keys.add(key)
            break

    for row in sorted_worst:
        key = _recipe_row_key(row)
        if key in selected_keys:
            continue
        row_copy = dict(row)
        row_copy["selection_reason"] = "top_negative_delta_fill"
        selected_rows.append(row_copy)
        selected_keys.add(key)
        if len(selected_rows) >= 10:
            break
    selected_rows = selected_rows[:10]

    packets = _build_selected_recipe_packets(
        selected_recipe_rows=selected_rows,
        changed_line_rows=changed_line_rows,
    )
    return {
        "requested_targets": requested_targets,
        "found_targets": [
            str(row.get("recipe_id") or "")
            for row in selected_rows
            if any(
                _upload_bundle_matches_recipe_target(str(row.get("recipe_id") or ""), target)
                for target in requested_targets
            )
        ],
        "packet_count": len(packets),
        "packets": packets,
    }


def _upload_bundle_changed_line_bucket(row: dict[str, Any]) -> str:
    gold_label = str(row.get("gold_label") or "")
    baseline_label = str(row.get("vanilla_pred") or row.get("baseline_pred") or "")
    codex_label = str(row.get("codex_pred") or "")
    baseline_correct = bool(gold_label) and baseline_label == gold_label
    codex_correct = bool(gold_label) and codex_label == gold_label
    if baseline_correct and not codex_correct:
        return "new_error"
    if not baseline_correct and codex_correct:
        return "fixed_error"
    if not baseline_correct and not codex_correct:
        return "both_wrong_shift"
    return "other_changed"


def _upload_bundle_build_changed_line_stratified_sample(
    changed_line_rows: list[dict[str, Any]],
    *,
    per_bucket_limit: int = 40,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    confusion_counts: Counter[str] = Counter()
    for row in changed_line_rows:
        bucket = _upload_bundle_changed_line_bucket(row)
        grouped[bucket].append(row)
        gold_label = str(row.get("gold_label") or "")
        codex_label = str(row.get("codex_pred") or "")
        confusion_counts[f"{gold_label}->{codex_label}"] += 1

    samples: dict[str, list[dict[str, Any]]] = {}
    counts_by_bucket: dict[str, int] = {}
    for bucket_name in sorted(grouped):
        rows = sorted(
            grouped[bucket_name],
            key=lambda row: (
                str(row.get("recipe_id") or ""),
                int(_coerce_int(row.get("line_index")) or 0),
                str(row.get("gold_label") or ""),
            ),
        )
        counts_by_bucket[bucket_name] = len(rows)
        sampled_rows: list[dict[str, Any]] = []
        for row in rows[: max(per_bucket_limit, 0)]:
            sampled_rows.append(
                {
                    "source_key": str(row.get("source_key") or ""),
                    "codex_run_id": str(row.get("codex_run_id") or ""),
                    "baseline_run_id": str(row.get("baseline_run_id") or ""),
                    "recipe_id": str(row.get("recipe_id") or ""),
                    "line_index": int(_coerce_int(row.get("line_index")) or 0),
                    "span_region": str(row.get("span_region") or ""),
                    "gold_label": str(row.get("gold_label") or ""),
                    "baseline_pred": str(
                        row.get("vanilla_pred") or row.get("baseline_pred") or ""
                    ),
                    "codex_pred": str(row.get("codex_pred") or ""),
                    "current_line": str(row.get("current_line") or ""),
                    "previous_line": str(row.get("previous_line") or ""),
                    "next_line": str(row.get("next_line") or ""),
                }
            )
        samples[bucket_name] = sampled_rows
    return {
        "total_rows": len(changed_line_rows),
        "counts_by_bucket": counts_by_bucket,
        "top_error_buckets": [
            {"bucket": bucket, "count": count}
            for bucket, count in confusion_counts.most_common(20)
        ],
        "samples_by_bucket": samples,
    }


def _upload_bundle_sort_recipe_triage_rows(
    recipe_triage_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        [row for row in recipe_triage_rows if isinstance(row, dict)],
        key=lambda row: (
            -int(_coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0),
            -abs(_float_or_zero(row.get("delta_codex_minus_baseline"))),
            str(row.get("recipe_id") or ""),
            str(row.get("source_key") or ""),
            str(row.get("codex_run_id") or ""),
        ),
    )


def _starter_pack_serialize_recipe_triage_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_key": str(row.get("source_key") or ""),
        "codex_run_id": str(row.get("codex_run_id") or row.get("run_id") or ""),
        "baseline_run_id": str(row.get("baseline_run_id") or ""),
        "recipe_id": str(row.get("recipe_id") or ""),
        "short_title": str(row.get("short_title") or ""),
        "line_total": int(_coerce_int(row.get("line_total")) or 0),
        "changed_lines_codex_vs_baseline": int(
            _coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0
        ),
        "codex_accuracy": _coerce_float(row.get("codex_accuracy")),
        "baseline_accuracy": _coerce_float(row.get("baseline_accuracy")),
        "delta_codex_minus_baseline": _coerce_float(row.get("delta_codex_minus_baseline")),
        "pass1_call_id": str(row.get("pass1_call_id") or ""),
        "pass2_call_id": str(row.get("pass2_call_id") or ""),
        "pass3_call_id": str(row.get("pass3_call_id") or ""),
        "pass1_start_block_index": _coerce_int(row.get("pass1_start_block_index")),
        "pass1_end_block_index": _coerce_int(row.get("pass1_end_block_index")),
        "pass1_selected_block_count": int(
            _coerce_int(row.get("pass1_selected_block_count")) or 0
        ),
        "pass2_input_block_count": int(_coerce_int(row.get("pass2_input_block_count")) or 0),
        "pass1_vs_pass2_missing_block_count": int(
            _coerce_int(row.get("pass1_vs_pass2_missing_block_count")) or 0
        ),
        "pass1_vs_pass2_extra_block_count": int(
            _coerce_int(row.get("pass1_vs_pass2_extra_block_count")) or 0
        ),
        "pass2_warning_count": int(_coerce_int(row.get("pass2_warning_count")) or 0),
        "pass2_warning_buckets": _coerce_str_list(row.get("pass2_warning_buckets")),
        "pass2_extracted_ingredient_count": int(
            _coerce_int(row.get("pass2_extracted_ingredient_count")) or 0
        ),
        "pass2_extracted_instruction_count": int(
            _coerce_int(row.get("pass2_extracted_instruction_count")) or 0
        ),
        "pass3_step_count": int(_coerce_int(row.get("pass3_step_count")) or 0),
        "pass3_mapping_count": int(_coerce_int(row.get("pass3_mapping_count")) or 0),
        "pass3_empty_mapping": bool(row.get("pass3_empty_mapping")),
        "pass3_warning_count": int(_coerce_int(row.get("pass3_warning_count")) or 0),
        "pass3_warning_buckets": _coerce_str_list(row.get("pass3_warning_buckets")),
        "pass1_status": str(row.get("pass1_status") or ""),
        "pass2_status": str(row.get("pass2_status") or ""),
        "pass3_status": str(row.get("pass3_status") or ""),
        "pass1_clamped_block_loss_count": int(
            _coerce_int(row.get("pass1_clamped_block_loss_count")) or 0
        ),
        "pass1_clamped_block_loss_ratio": _coerce_float(
            row.get("pass1_clamped_block_loss_ratio")
        ),
        "pass2_degradation_reasons": _coerce_str_list(row.get("pass2_degradation_reasons")),
        "pass2_degradation_severity": str(row.get("pass2_degradation_severity") or ""),
        "pass2_promotion_policy": str(row.get("pass2_promotion_policy") or ""),
        "pass3_execution_mode": str(row.get("pass3_execution_mode") or ""),
        "pass3_routing_reason": str(row.get("pass3_routing_reason") or ""),
        "pass3_fallback_reason": str(row.get("pass3_fallback_reason") or ""),
        "transport_mismatch": _coerce_bool(row.get("transport_mismatch")),
        "transport_mismatch_reasons": _coerce_str_list(
            row.get("transport_mismatch_reasons")
        ),
        "transport_effective_to_payload_coverage_ratio": _coerce_float(
            row.get("transport_effective_to_payload_coverage_ratio")
        ),
        "evidence_split_quantity_lines": int(
            _coerce_int(row.get("evidence_split_quantity_lines")) or 0
        ),
        "evidence_dropped_page_markers": int(
            _coerce_int(row.get("evidence_dropped_page_markers")) or 0
        ),
        "evidence_folded_page_markers": int(
            _coerce_int(row.get("evidence_folded_page_markers")) or 0
        ),
        "outside_span_wrong_line_count": int(
            _coerce_int(row.get("outside_span_wrong_line_count")) or 0
        ),
        "outside_span_trace_status_top": str(row.get("outside_span_trace_status_top") or ""),
    }


def _starter_pack_collect_run_rows_from_pairs(
    comparison_pairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_id: dict[str, dict[str, Any]] = {}
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        for key in ("codex_run", "baseline_run"):
            run_payload = pair.get(key)
            if not isinstance(run_payload, dict):
                continue
            run_id = str(run_payload.get("run_id") or "").strip()
            if not run_id:
                continue
            rows_by_id.setdefault(
                run_id,
                {
                    "run_id": run_id,
                    "output_subdir": str(run_payload.get("output_subdir") or run_id),
                    "source_file": run_payload.get("source_file"),
                    "llm_recipe_pipeline": run_payload.get("llm_recipe_pipeline"),
                    "line_role_pipeline": run_payload.get("line_role_pipeline"),
                    "atomic_block_splitter": run_payload.get("atomic_block_splitter"),
                    "prediction_run_config_hash": run_payload.get(
                        "prediction_run_config_hash"
                    ),
                },
            )
    return [rows_by_id[key] for key in sorted(rows_by_id)]


def _starter_pack_build_run_dir_by_id(
    *,
    output_dir: Path,
    run_rows: list[dict[str, Any]],
) -> dict[str, Path]:
    run_dir_by_id: dict[str, Path] = {}
    for row in run_rows:
        if not isinstance(row, dict):
            continue
        run_id = str(row.get("run_id") or "").strip()
        output_subdir = str(row.get("output_subdir") or "").strip()
        if not run_id or not output_subdir:
            continue
        run_dir = output_dir / output_subdir
        if run_dir.is_dir():
            run_dir_by_id[run_id] = run_dir
    return run_dir_by_id


def _starter_pack_status_for_artifact(
    *,
    run_dir: Path,
    artifact_name: str,
    codex_enabled: bool,
) -> str:
    codex_only = {
        PROMPT_WARNING_AGGREGATE_FILE_NAME,
        PROJECTION_TRACE_FILE_NAME,
        PREPROCESS_TRACE_FAILURES_FILE_NAME,
    }
    if artifact_name in codex_only and not codex_enabled:
        return "not_applicable"
    primary_path = run_dir / artifact_name
    if primary_path.is_file():
        return "present"
    if artifact_name.endswith(".gz"):
        decompressed_path = run_dir / artifact_name.removesuffix(".gz")
        if decompressed_path.is_file():
            return "present"
    return "missing"


def _starter_pack_build_baseline_trace_parity_cues(
    *,
    comparison_pairs: list[dict[str, Any]],
    run_rows: list[dict[str, Any]],
    run_dir_by_id: dict[str, Path],
) -> dict[str, Any]:
    row_by_run_id = {
        str(row.get("run_id") or "").strip(): row
        for row in run_rows
        if isinstance(row, dict) and str(row.get("run_id") or "").strip()
    }
    artifact_names = (
        "need_to_know_summary.json",
        PROMPT_WARNING_AGGREGATE_FILE_NAME,
        PROJECTION_TRACE_FILE_NAME,
        WRONG_LABEL_FULL_CONTEXT_FILE_NAME,
        PREPROCESS_TRACE_FAILURES_FILE_NAME,
    )
    pair_rows: list[dict[str, Any]] = []
    parity_counter: Counter[str] = Counter()
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        codex_payload = pair.get("codex_run")
        baseline_payload = pair.get("baseline_run")
        if not isinstance(codex_payload, dict) or not isinstance(baseline_payload, dict):
            continue
        codex_run_id = str(codex_payload.get("run_id") or "").strip()
        baseline_run_id = str(baseline_payload.get("run_id") or "").strip()
        codex_row = row_by_run_id.get(codex_run_id, {})
        baseline_row = row_by_run_id.get(baseline_run_id, {})
        codex_dir = run_dir_by_id.get(codex_run_id)
        baseline_dir = run_dir_by_id.get(baseline_run_id)
        codex_enabled = _upload_bundle_is_codex_pipeline_enabled(
            codex_row.get("llm_recipe_pipeline")
        )
        baseline_enabled = _upload_bundle_is_codex_pipeline_enabled(
            baseline_row.get("llm_recipe_pipeline")
        )
        codex_statuses: dict[str, str] = {}
        baseline_statuses: dict[str, str] = {}
        for artifact_name in artifact_names:
            codex_statuses[artifact_name] = (
                _starter_pack_status_for_artifact(
                    run_dir=codex_dir,
                    artifact_name=artifact_name,
                    codex_enabled=codex_enabled,
                )
                if isinstance(codex_dir, Path)
                else "missing"
            )
            baseline_statuses[artifact_name] = (
                _starter_pack_status_for_artifact(
                    run_dir=baseline_dir,
                    artifact_name=artifact_name,
                    codex_enabled=baseline_enabled,
                )
                if isinstance(baseline_dir, Path)
                else "missing"
            )
        parity_flags = {
            "need_to_know_summary_parity": (
                codex_statuses.get("need_to_know_summary.json")
                == baseline_statuses.get("need_to_know_summary.json")
            ),
            "wrong_label_context_parity": (
                codex_statuses.get(WRONG_LABEL_FULL_CONTEXT_FILE_NAME)
                == baseline_statuses.get(WRONG_LABEL_FULL_CONTEXT_FILE_NAME)
            ),
            "codex_only_trace_fields_expected": True,
            "codex_only_trace_fields_present_for_codex": all(
                codex_statuses.get(name) == "present"
                for name in (
                    PROMPT_WARNING_AGGREGATE_FILE_NAME,
                    PROJECTION_TRACE_FILE_NAME,
                    PREPROCESS_TRACE_FAILURES_FILE_NAME,
                )
            ),
            "codex_only_trace_fields_not_applicable_for_baseline": all(
                baseline_statuses.get(name) == "not_applicable"
                for name in (
                    PROMPT_WARNING_AGGREGATE_FILE_NAME,
                    PROJECTION_TRACE_FILE_NAME,
                    PREPROCESS_TRACE_FAILURES_FILE_NAME,
                )
            ),
        }
        parity_counter["pair_rows"] += 1
        if all(bool(value) for value in parity_flags.values()):
            parity_counter["fully_ready_pairs"] += 1
        pair_rows.append(
            {
                "source_key": str(pair.get("source_key") or ""),
                "codex_run_id": codex_run_id,
                "baseline_run_id": baseline_run_id,
                "codex_statuses": codex_statuses,
                "baseline_statuses": baseline_statuses,
                "parity_flags": parity_flags,
            }
        )

    return {
        "schema_version": "starter_pack_baseline_trace_parity.v1",
        "artifact_names": list(artifact_names),
        "pair_count": len(pair_rows),
        "fully_ready_pairs": int(parity_counter.get("fully_ready_pairs") or 0),
        "pair_rows": pair_rows,
    }


def _upload_bundle_build_triage_packet_rows(
    recipe_triage_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, row in enumerate(
        _upload_bundle_sort_recipe_triage_rows(recipe_triage_rows),
        start=1,
    ):
        rows.append(
            {
                "schema_version": UPLOAD_BUNDLE_TRIAGE_PACKET_SCHEMA_VERSION,
                "triage_rank": rank,
                "source_key": str(row.get("source_key") or ""),
                "codex_run_id": str(row.get("codex_run_id") or row.get("run_id") or ""),
                "baseline_run_id": str(row.get("baseline_run_id") or ""),
                "recipe_id": str(row.get("recipe_id") or ""),
                "short_title": str(row.get("short_title") or ""),
                "line_total": int(_coerce_int(row.get("line_total")) or 0),
                "changed_lines_codex_vs_baseline": int(
                    _coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0
                ),
                "baseline_accuracy": _coerce_float(row.get("baseline_accuracy")),
                "codex_accuracy": _coerce_float(row.get("codex_accuracy")),
                "delta_codex_minus_baseline": _coerce_float(
                    row.get("delta_codex_minus_baseline")
                ),
                "pass1_status": str(row.get("pass1_status") or ""),
                "pass2_status": str(row.get("pass2_status") or ""),
                "pass3_status": str(row.get("pass3_status") or ""),
                "pass2_warning_count": int(_coerce_int(row.get("pass2_warning_count")) or 0),
                "pass3_warning_count": int(_coerce_int(row.get("pass3_warning_count")) or 0),
                "pass3_empty_mapping": bool(row.get("pass3_empty_mapping")),
                "pass3_execution_mode": str(row.get("pass3_execution_mode") or ""),
                "pass3_routing_reason": str(row.get("pass3_routing_reason") or ""),
                "pass3_fallback_reason": str(row.get("pass3_fallback_reason") or ""),
                "transport_mismatch": bool(row.get("transport_mismatch")),
            }
        )
    return rows


def _upload_bundle_status_is_problem(value: Any) -> bool:
    status = str(value or "").strip().lower()
    if not status:
        return False
    non_problem = {
        "ok",
        "success",
        "successful",
        "complete",
        "completed",
        "ready",
        "written",
        "available",
        "not_applicable",
        "unknown",
    }
    return status not in non_problem


def _upload_bundle_recipe_ids_equivalent(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    if left_text == right_text:
        return True
    return _upload_bundle_matches_recipe_target(
        recipe_id=left_text,
        target=right_text,
    ) or _upload_bundle_matches_recipe_target(
        recipe_id=right_text,
        target=left_text,
    )


def _upload_bundle_collect_line_role_prediction_rows(
    *,
    source_root: Path,
    run_dir_by_id: dict[str, Path],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    relative_paths: list[str] = []
    for run_id, run_dir_value in sorted(run_dir_by_id.items(), key=lambda item: item[0]):
        run_dir = run_dir_value if isinstance(run_dir_value, Path) else None
        if run_dir is None:
            continue
        path = run_dir / "line-role-pipeline" / "line_role_predictions.jsonl"
        if not path.is_file():
            continue
        try:
            relative_paths.append(str(path.relative_to(source_root).as_posix()))
        except ValueError:
            relative_paths.append(str(path))
        for row in _iter_jsonl(path):
            if not isinstance(row, dict):
                continue
            row_payload = dict(row)
            row_payload["run_id"] = str(row_payload.get("run_id") or run_id)
            row_payload["recipe_id"] = str(row_payload.get("recipe_id") or "")
            row_payload["line_index"] = _coerce_int(row_payload.get("line_index"))
            row_payload["atomic_index"] = _coerce_int(row_payload.get("atomic_index"))
            row_payload["label"] = str(row_payload.get("label") or "OTHER").strip().upper() or "OTHER"
            row_payload["decided_by"] = (
                str(row_payload.get("decided_by") or "").strip().lower() or "unknown"
            )
            row_payload["confidence"] = _coerce_float(row_payload.get("confidence"))
            row_payload["candidate_labels"] = _upload_bundle_extract_candidate_labels(row_payload)
            rows.append(row_payload)
    return rows, sorted(set(relative_paths))


def _upload_bundle_build_low_confidence_changed_lines_packet(
    *,
    source_root: Path,
    run_dir_by_id: dict[str, Path],
    changed_line_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    prediction_rows, prediction_files = _upload_bundle_collect_line_role_prediction_rows(
        source_root=source_root,
        run_dir_by_id=run_dir_by_id,
    )
    if not prediction_rows:
        return (
            {
                "schema_version": UPLOAD_BUNDLE_LOW_CONFIDENCE_CHANGED_LINES_SCHEMA_VERSION,
                "available": False,
                "low_confidence_threshold": UPLOAD_BUNDLE_LOW_CONFIDENCE_THRESHOLD,
                "prediction_files": prediction_files,
                "changed_line_rows_considered": len(changed_line_rows),
                "row_count": 0,
                "sample_rows": [],
                "unavailable_reason": (
                    "line-role-pipeline/line_role_predictions.jsonl not found in discovered run roots"
                ),
            },
            [],
        )

    predictions_by_run_line: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in prediction_rows:
        run_id = str(row.get("run_id") or "")
        line_index = _coerce_int(row.get("line_index"))
        if not run_id or line_index is None:
            continue
        predictions_by_run_line[(run_id, int(line_index))].append(row)

    def _pick_prediction_row(
        *,
        candidates: list[dict[str, Any]],
        recipe_id: str,
    ) -> dict[str, Any] | None:
        if not candidates:
            return None
        recipe_text = str(recipe_id or "").strip()
        if recipe_text:
            for candidate in candidates:
                candidate_recipe = str(candidate.get("recipe_id") or "").strip()
                if _upload_bundle_recipe_ids_equivalent(candidate_recipe, recipe_text):
                    return candidate
        for candidate in candidates:
            if not str(candidate.get("recipe_id") or "").strip():
                return candidate
        return candidates[0]

    packet_rows: list[dict[str, Any]] = []
    for changed_row in changed_line_rows:
        if not isinstance(changed_row, dict):
            continue
        codex_run_id = str(changed_row.get("codex_run_id") or "").strip()
        line_index = _coerce_int(changed_row.get("line_index"))
        if not codex_run_id or line_index is None:
            continue
        candidates = predictions_by_run_line.get((codex_run_id, int(line_index)), [])
        if not candidates:
            continue
        selected = _pick_prediction_row(
            candidates=candidates,
            recipe_id=str(changed_row.get("recipe_id") or ""),
        )
        if not isinstance(selected, dict):
            continue
        confidence = _coerce_float(selected.get("confidence"))
        if confidence is None or confidence >= UPLOAD_BUNDLE_LOW_CONFIDENCE_THRESHOLD:
            continue
        packet_rows.append(
            {
                "source_key": str(changed_row.get("source_key") or ""),
                "codex_run_id": codex_run_id,
                "baseline_run_id": str(changed_row.get("baseline_run_id") or ""),
                "recipe_id": str(changed_row.get("recipe_id") or ""),
                "line_index": int(line_index),
                "atomic_index": _coerce_int(selected.get("atomic_index")),
                "confidence": float(confidence),
                "label": str(selected.get("label") or "OTHER"),
                "decided_by": str(selected.get("decided_by") or "unknown"),
                "candidate_labels": _coerce_str_list(selected.get("candidate_labels")),
                "gold_label": str(changed_row.get("gold_label") or ""),
                "baseline_pred": str(
                    changed_row.get("vanilla_pred") or changed_row.get("baseline_pred") or ""
                ),
                "codex_pred": str(changed_row.get("codex_pred") or ""),
                "changed_line_bucket": _upload_bundle_changed_line_bucket(changed_row),
                "text_excerpt": _excerpt(
                    str(selected.get("text") or changed_row.get("current_line") or ""),
                    max_len=220,
                ),
                "current_line": str(changed_row.get("current_line") or ""),
                "previous_line": str(changed_row.get("previous_line") or ""),
                "next_line": str(changed_row.get("next_line") or ""),
            }
        )
    packet_rows.sort(
        key=lambda row: (
            _float_or_zero(row.get("confidence")),
            str(row.get("recipe_id") or ""),
            int(_coerce_int(row.get("line_index")) or 0),
        )
    )

    return (
        {
            "schema_version": UPLOAD_BUNDLE_LOW_CONFIDENCE_CHANGED_LINES_SCHEMA_VERSION,
            "available": True,
            "low_confidence_threshold": UPLOAD_BUNDLE_LOW_CONFIDENCE_THRESHOLD,
            "prediction_files": prediction_files,
            "changed_line_rows_considered": len(changed_line_rows),
            "matched_prediction_rows": len(packet_rows),
            "row_count": len(packet_rows),
            "empty_packet_note": (
                ""
                if packet_rows
                else (
                    "No changed lines intersected low-confidence line-role predictions below "
                    f"{UPLOAD_BUNDLE_LOW_CONFIDENCE_THRESHOLD:.2f}."
                )
            ),
            "sample_rows": packet_rows[:40],
        },
        packet_rows,
    )


def _upload_bundle_build_net_error_blame_summary(
    *,
    changed_line_rows: list[dict[str, Any]],
    recipe_triage_rows: list[dict[str, Any]],
    comparison_pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    line_role_pipeline_by_run_id: dict[str, str] = {}
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        codex_run = pair.get("codex_run")
        if not isinstance(codex_run, dict):
            continue
        run_id = str(codex_run.get("run_id") or "").strip()
        if not run_id:
            continue
        line_role_pipeline_by_run_id[run_id] = str(
            codex_run.get("line_role_pipeline") or "off"
        ).strip()

    triage_by_full_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    triage_by_partial_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in recipe_triage_rows:
        if not isinstance(row, dict):
            continue
        source_key = str(row.get("source_key") or "")
        codex_run_id = str(row.get("codex_run_id") or row.get("run_id") or "")
        baseline_run_id = str(row.get("baseline_run_id") or "")
        recipe_id = str(row.get("recipe_id") or "")
        if source_key and codex_run_id and recipe_id:
            triage_by_partial_key.setdefault((source_key, codex_run_id, recipe_id), row)
            triage_by_full_key.setdefault(
                (source_key, codex_run_id, baseline_run_id, recipe_id),
                row,
            )

    def _triage_row_for_changed_line(row: dict[str, Any]) -> dict[str, Any] | None:
        source_key = str(row.get("source_key") or "")
        codex_run_id = str(row.get("codex_run_id") or "")
        baseline_run_id = str(row.get("baseline_run_id") or "")
        recipe_id = str(row.get("recipe_id") or "")
        key_full = (source_key, codex_run_id, baseline_run_id, recipe_id)
        if key_full in triage_by_full_key:
            return triage_by_full_key[key_full]
        key_partial = (source_key, codex_run_id, recipe_id)
        if key_partial in triage_by_partial_key:
            return triage_by_partial_key[key_partial]
        return None

    def _blame_bucket_for_row(
        *,
        changed_row: dict[str, Any],
        triage_row: dict[str, Any] | None,
    ) -> str:
        blame_bucket = "line_role"
        if isinstance(triage_row, dict):
            transport_mismatch = bool(triage_row.get("transport_mismatch"))
            pass3_empty_mapping = bool(triage_row.get("pass3_empty_mapping"))
            pass3_warning_count = int(_coerce_int(triage_row.get("pass3_warning_count")) or 0)
            pass2_warning_count = int(_coerce_int(triage_row.get("pass2_warning_count")) or 0)
            pass2_degradation = _coerce_str_list(triage_row.get("pass2_degradation_reasons"))
            pass3_execution_mode = str(triage_row.get("pass3_execution_mode") or "").strip().lower()
            pass3_routing_reason = str(triage_row.get("pass3_routing_reason") or "").strip()
            pass3_fallback_reason = str(triage_row.get("pass3_fallback_reason") or "").strip()
            pass3_status_problem = _upload_bundle_status_is_problem(triage_row.get("pass3_status"))
            pass2_status_problem = _upload_bundle_status_is_problem(triage_row.get("pass2_status"))
            pass3_mode_implies_fallback = pass3_execution_mode in {
                "fallback",
                "fallback_or_partial",
                "projection_only",
                "route_to_baseline",
            }
            if (
                transport_mismatch
                or pass3_mode_implies_fallback
                or bool(pass3_routing_reason)
                or bool(pass3_fallback_reason)
            ):
                blame_bucket = "routing_or_fallback"
            elif pass3_empty_mapping or pass3_warning_count > 0 or pass3_status_problem:
                blame_bucket = "pass3_mapping"
            elif pass2_warning_count > 0 or bool(pass2_degradation) or pass2_status_problem:
                blame_bucket = "pass2_extraction"
            else:
                codex_run_id = str(changed_row.get("codex_run_id") or "")
                line_role_pipeline = (
                    str(line_role_pipeline_by_run_id.get(codex_run_id) or "off").strip().lower()
                )
                if line_role_pipeline in {"", "off", "none"}:
                    blame_bucket = "routing_or_fallback"
                else:
                    blame_bucket = "line_role"
        return blame_bucket

    new_bucket_counts: Counter[str] = Counter()
    fixed_bucket_counts: Counter[str] = Counter()
    bucket_samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    new_error_rows = 0
    fixed_error_rows = 0

    for row in changed_line_rows:
        if not isinstance(row, dict):
            continue
        bucket = _upload_bundle_changed_line_bucket(row)
        if bucket not in {"new_error", "fixed_error"}:
            continue
        triage_row = _triage_row_for_changed_line(row)
        blame_bucket = _blame_bucket_for_row(changed_row=row, triage_row=triage_row)
        if bucket == "fixed_error":
            fixed_error_rows += 1
            fixed_bucket_counts[blame_bucket] += 1
            continue
        new_error_rows += 1
        new_bucket_counts[blame_bucket] += 1
        if len(bucket_samples[blame_bucket]) < 12:
            bucket_samples[blame_bucket].append(
                {
                    "source_key": str(row.get("source_key") or ""),
                    "codex_run_id": str(row.get("codex_run_id") or ""),
                    "baseline_run_id": str(row.get("baseline_run_id") or ""),
                    "recipe_id": str(row.get("recipe_id") or ""),
                    "line_index": int(_coerce_int(row.get("line_index")) or 0),
                    "gold_label": str(row.get("gold_label") or ""),
                    "baseline_pred": str(
                        row.get("vanilla_pred") or row.get("baseline_pred") or ""
                    ),
                    "codex_pred": str(row.get("codex_pred") or ""),
                }
            )

    ordered_buckets = [
        "line_role",
        "pass2_extraction",
        "pass3_mapping",
        "routing_or_fallback",
    ]
    net_error_delta_lines = int(new_error_rows - fixed_error_rows)
    new_error_denominator = new_error_rows if new_error_rows > 0 else 1
    fixed_error_denominator = fixed_error_rows if fixed_error_rows > 0 else 1
    bucket_rows: list[dict[str, Any]] = []
    for bucket_name in ordered_buckets:
        new_count = int(new_bucket_counts.get(bucket_name) or 0)
        fixed_count = int(fixed_bucket_counts.get(bucket_name) or 0)
        net_count = int(new_count - fixed_count)
        bucket_rows.append(
            {
                "bucket": bucket_name,
                "count": new_count,
                "new_error_count": new_count,
                "fixed_error_count": fixed_count,
                "net_error_count": net_count,
                "share_of_new_errors": round(new_count / new_error_denominator, 6),
                "share_of_fixed_errors": round(fixed_count / fixed_error_denominator, 6),
                "share_of_net_error": (
                    round(net_count / net_error_delta_lines, 6)
                    if net_error_delta_lines != 0
                    else None
                ),
                "sample_rows": bucket_samples.get(bucket_name, []),
            }
        )

    return {
        "schema_version": UPLOAD_BUNDLE_NET_ERROR_BLAME_SCHEMA_VERSION,
        "bucket_definitions": {
            "line_role": "Rows where codex line-role decisions are most likely responsible.",
            "pass2_extraction": "Rows with pass2 warnings/degradation signals suggesting extraction-stage loss.",
            "pass3_mapping": "Rows with pass3 empty-mapping/warning/status signals indicating mapping-stage loss.",
            "routing_or_fallback": "Rows with transport mismatch or explicit fallback/routing signals.",
        },
        "share_semantics": {
            "share_of_new_errors": "bucket.new_error_count / new_error_lines",
            "share_of_fixed_errors": "bucket.fixed_error_count / fixed_error_lines",
            "share_of_net_error": (
                "bucket.net_error_count / net_error_delta_lines (null when net_error_delta_lines=0)"
            ),
        },
        "new_error_lines": new_error_rows,
        "fixed_error_lines": fixed_error_rows,
        "net_error_delta_lines": net_error_delta_lines,
        "bucket_rows": bucket_rows,
    }


def _upload_bundle_is_codex_pipeline_enabled(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized not in {"", "off", "none", "false", "0"}


def _upload_bundle_build_config_version_metadata(
    *,
    source_root: Path,
    run_rows: list[dict[str, Any]],
    comparison_pairs: list[dict[str, Any]],
    run_dir_by_id: dict[str, Path],
) -> dict[str, Any]:
    settings_keys = list(RUN_CONFIG_KEYS_OF_INTEREST) + ["prediction_run_config_hash"]
    run_rows_by_id: dict[str, dict[str, Any]] = {}
    for row in run_rows:
        if not isinstance(row, dict):
            continue
        run_id = str(row.get("run_id") or "").strip()
        if not run_id:
            continue
        run_rows_by_id.setdefault(run_id, row)

    run_settings_rows: list[dict[str, Any]] = []
    for run_id in sorted(run_rows_by_id.keys()):
        row = run_rows_by_id[run_id]
        run_dir = run_dir_by_id.get(run_id)
        run_manifest: dict[str, Any] = {}
        eval_report: dict[str, Any] = {}
        if isinstance(run_dir, Path):
            run_manifest = _upload_bundle_load_json_object(run_dir / "run_manifest.json")
            eval_report = _upload_bundle_load_json_object(run_dir / "eval_report.json")
        run_config = run_manifest.get("run_config")
        run_config = run_config if isinstance(run_config, dict) else {}

        settings: dict[str, Any] = {}
        for key in settings_keys:
            if key in run_config:
                settings[key] = run_config.get(key)
            elif key in row:
                settings[key] = row.get(key)
            else:
                settings[key] = None

        run_settings_rows.append(
            {
                "run_id": run_id,
                "output_subdir": str(row.get("output_subdir") or ""),
                "source_file": row.get("source_file"),
                "llm_recipe_pipeline": settings.get("llm_recipe_pipeline"),
                "line_role_pipeline": settings.get("line_role_pipeline"),
                "atomic_block_splitter": settings.get("atomic_block_splitter"),
                "prediction_run_config_hash": settings.get("prediction_run_config_hash"),
                "run_manifest_schema_version": run_manifest.get("schema_version"),
                "eval_report_schema_version": eval_report.get("schema_version"),
                "settings": settings,
            }
        )

    allowed_pair_setting_differences = {
        "llm_recipe_pipeline",
        "line_role_pipeline",
        "atomic_block_splitter",
        "prediction_run_config_hash",
    }
    pair_delta_rows: list[dict[str, Any]] = []
    non_comparable_key_counts: Counter[str] = Counter()
    comparable_pair_count = 0
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        run_config_differences = pair.get("run_config_differences")
        run_config_differences = (
            run_config_differences if isinstance(run_config_differences, dict) else {}
        )
        differing_keys = sorted(run_config_differences.keys())
        non_comparable_keys = [
            key for key in differing_keys if key not in allowed_pair_setting_differences
        ]
        for key in non_comparable_keys:
            non_comparable_key_counts[key] += 1
        is_comparable = len(non_comparable_keys) == 0
        if is_comparable:
            comparable_pair_count += 1
        pair_delta_rows.append(
            {
                "source_key": str(pair.get("source_key") or ""),
                "codex_run_id": str(
                    ((pair.get("codex_run") or {}).get("run_id"))
                    if isinstance(pair.get("codex_run"), dict)
                    else ""
                ),
                "baseline_run_id": str(
                    ((pair.get("baseline_run") or {}).get("run_id"))
                    if isinstance(pair.get("baseline_run"), dict)
                    else ""
                ),
                "is_config_comparable": is_comparable,
                "differing_keys": differing_keys,
                "non_comparable_keys": non_comparable_keys,
                "run_config_differences": run_config_differences,
            }
        )

    return {
        "schema_version": UPLOAD_BUNDLE_CONFIG_VERSION_METADATA_SCHEMA_VERSION,
        "generator": {
            "script": "scripts/benchmark_cutdown_for_external_ai.py",
            "bundle_version": "upload_bundle.v1",
            "generated_at": _timestamp_now(),
            "source_root": str(source_root),
        },
        "settings_keys_of_interest": settings_keys,
        "settings_compatibility_policy": {
            "allowed_pair_setting_differences": sorted(allowed_pair_setting_differences),
            "rule": (
                "Pairs are config-comparable when differences are limited to intentional "
                "codex-vs-baseline toggles (llm/line-role/splitter/config-hash)."
            ),
        },
        "runs": run_settings_rows,
        "pair_comparability": {
            "pair_count": len(pair_delta_rows),
            "config_compatible_pair_count": comparable_pair_count,
            "config_compatible_pair_ratio": (
                round(comparable_pair_count / len(pair_delta_rows), 6)
                if pair_delta_rows
                else 1.0
            ),
            "non_comparable_key_counts": _counter_to_sorted_dict(non_comparable_key_counts),
        },
        "pair_setting_deltas": pair_delta_rows,
    }


def _upload_bundle_build_alias_metadata(
    *,
    artifact_index: list[dict[str, Any]],
    starter_manifest_payload: dict[str, Any],
) -> dict[str, Any]:
    sha_groups: dict[str, list[str]] = defaultdict(list)
    for row in artifact_index:
        path = str(row.get("path") or "")
        sha256 = str(row.get("sha256") or "")
        if not path or not sha256:
            continue
        sha_groups[sha256].append(path)
    content_equivalent_groups: list[dict[str, Any]] = []
    for sha256, paths in sha_groups.items():
        if len(paths) < 2:
            continue
        ordered_paths = sorted(paths, key=lambda value: (value.count("/"), len(value), value))
        canonical = ordered_paths[0]
        aliases = ordered_paths[1:]
        content_equivalent_groups.append(
            {
                "sha256": sha256,
                "canonical_path": canonical,
                "alias_paths": aliases,
                "alias_count": len(aliases),
                "reason": "same_sha256",
            }
        )
    content_equivalent_groups.sort(
        key=lambda row: (
            -int(row.get("alias_count") or 0),
            str(row.get("canonical_path") or ""),
        )
    )

    legacy_aliases: list[dict[str, Any]] = []
    legacy_mapping = starter_manifest_payload.get("legacy_to_starter_mapping")
    if isinstance(legacy_mapping, dict):
        for legacy_path, canonical_path in sorted(legacy_mapping.items()):
            if not isinstance(legacy_path, str) or not isinstance(canonical_path, str):
                continue
            legacy_aliases.append(
                {
                    "legacy_path": legacy_path,
                    "canonical_path": canonical_path,
                }
            )
    return {
        "content_equivalent_groups": content_equivalent_groups,
        "legacy_aliases": legacy_aliases,
    }


def _upload_bundle_build_stage_separated_comparison(
    *,
    recipe_triage_rows: list[dict[str, Any]],
    per_label_metrics: list[dict[str, Any]],
    comparison_pairs: list[dict[str, Any]],
    pass_stage_per_label_metrics: dict[str, Any],
) -> dict[str, Any]:
    line_role_pipeline_by_run_id: dict[str, str] = {}
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        codex_run = pair.get("codex_run")
        if not isinstance(codex_run, dict):
            continue
        run_id = str(codex_run.get("run_id") or "").strip()
        if not run_id:
            continue
        line_role_pipeline_by_run_id[run_id] = str(
            codex_run.get("line_role_pipeline") or "off"
        )

    per_recipe_rows: list[dict[str, Any]] = []
    for row in recipe_triage_rows:
        run_id = str(row.get("codex_run_id") or row.get("run_id") or "").strip()
        line_role_pipeline = line_role_pipeline_by_run_id.get(run_id, "unknown")
        pass3_fallback_reason = str(row.get("pass3_fallback_reason") or "").strip()
        per_recipe_rows.append(
            {
                "source_key": str(row.get("source_key") or ""),
                "codex_run_id": run_id,
                "baseline_run_id": str(row.get("baseline_run_id") or ""),
                "recipe_id": str(row.get("recipe_id") or ""),
                "short_title": str(row.get("short_title") or ""),
                "baseline_stage": {
                    "line_accuracy": _coerce_float(row.get("baseline_accuracy")),
                },
                "line_role_pipeline_stage": {
                    "pipeline": line_role_pipeline,
                    "line_accuracy": _coerce_float(row.get("codex_accuracy")),
                    "delta_vs_baseline": _coerce_float(
                        row.get("delta_codex_minus_baseline")
                    ),
                },
                "pass2_stage": {
                    "status": str(row.get("pass2_status") or ""),
                    "degradation_severity": str(
                        row.get("pass2_degradation_severity") or ""
                    ),
                    "promotion_policy": str(row.get("pass2_promotion_policy") or ""),
                    "warning_count": int(_coerce_int(row.get("pass2_warning_count")) or 0),
                    "warning_buckets": _coerce_str_list(
                        row.get("pass2_warning_buckets")
                    ),
                    "degradation_reasons": _coerce_str_list(
                        row.get("pass2_degradation_reasons")
                    ),
                    "extracted_instruction_count": int(
                        _coerce_int(row.get("pass2_extracted_instruction_count")) or 0
                    ),
                },
                "pass3_stage": {
                    "status": str(row.get("pass3_status") or ""),
                    "execution_mode": str(row.get("pass3_execution_mode") or ""),
                    "routing_reason": str(row.get("pass3_routing_reason") or ""),
                    "empty_mapping": bool(row.get("pass3_empty_mapping")),
                    "warning_count": int(_coerce_int(row.get("pass3_warning_count")) or 0),
                    "warning_buckets": _coerce_str_list(
                        row.get("pass3_warning_buckets")
                    ),
                    "fallback_reason": pass3_fallback_reason,
                },
                "final_or_fallback_stage": {
                    "status": (
                        "fallback"
                        if pass3_fallback_reason
                        else "final"
                    ),
                    "fallback_reason": pass3_fallback_reason or None,
                    "pass1_status": str(row.get("pass1_status") or ""),
                    "pass2_status": str(row.get("pass2_status") or ""),
                    "pass3_status": str(row.get("pass3_status") or ""),
                    "pass2_degradation_severity": str(
                        row.get("pass2_degradation_severity") or ""
                    ),
                    "pass2_promotion_policy": str(
                        row.get("pass2_promotion_policy") or ""
                    ),
                    "pass3_execution_mode": str(row.get("pass3_execution_mode") or ""),
                    "pass3_routing_reason": str(row.get("pass3_routing_reason") or ""),
                },
            }
        )
    per_recipe_rows.sort(
        key=lambda row: (
            _float_or_zero(
                ((row.get("line_role_pipeline_stage") or {}).get("delta_vs_baseline"))
            ),
            -int(
                _coerce_int(
                    ((row.get("pass2_stage") or {}).get("warning_count"))
                )
                or 0
            ),
            str(row.get("recipe_id") or ""),
        )
    )

    def _build_pass_stage_row(stage_key: str, label: str) -> dict[str, Any]:
        stage_payload = pass_stage_per_label_metrics.get(stage_key)
        stage_payload = stage_payload if isinstance(stage_payload, dict) else {}
        stage_labels = stage_payload.get("labels")
        stage_labels = stage_labels if isinstance(stage_labels, dict) else {}
        label_row = stage_labels.get(label)
        if isinstance(label_row, dict):
            return {
                "label_scored": True,
                "precision_avg": _coerce_float(label_row.get("precision_avg")),
                "recall_avg": _coerce_float(label_row.get("recall_avg")),
                "f1_avg": _coerce_float(label_row.get("f1_avg")),
                "gold_total_sum": int(_coerce_int(label_row.get("gold_total_sum")) or 0),
                "pred_total_sum": int(_coerce_int(label_row.get("pred_total_sum")) or 0),
                "runs_scored": int(_coerce_int(label_row.get("runs_scored")) or 0),
            }
        reason = str(stage_payload.get("unavailable_reason") or "").strip()
        if not reason and stage_payload.get("available"):
            reason = f"{stage_key} stage label metrics unavailable for label={label}"
        if not reason:
            reason = (
                f"{stage_key} stage outputs could not be projected/scored from discovered "
                "prediction-run codex artifacts"
            )
        return {
            "label_scored": False,
            "unavailable_reason": reason,
            "runs_scored": int(_coerce_int(stage_payload.get("runs_scored")) or 0),
        }

    per_label_rows: list[dict[str, Any]] = []
    for row in per_label_metrics:
        label = str(row.get("label") or "")
        per_label_rows.append(
            {
                "label": label,
                "baseline_stage": {
                    "recall_avg": _coerce_float(row.get("baseline_recall_avg")),
                    "f1_avg": _coerce_float(row.get("baseline_f1_avg")),
                },
                "line_role_pipeline_stage": {
                    "recall_avg": _coerce_float(row.get("codex_recall_avg")),
                    "f1_avg": _coerce_float(row.get("codex_f1_avg")),
                    "delta_recall_avg": _coerce_float(row.get("delta_recall_avg")),
                    "delta_f1_avg": _coerce_float(row.get("delta_f1_avg")),
                },
                "pass2_stage": _build_pass_stage_row("pass2", label),
                "pass3_stage": _build_pass_stage_row("pass3", label),
                "final_or_fallback_stage": {
                    "confusion_delta_outbound_total": int(
                        _coerce_int(row.get("confusion_delta_outbound_total")) or 0
                    ),
                    "confusion_delta_inbound_total": int(
                        _coerce_int(row.get("confusion_delta_inbound_total")) or 0
                    ),
                    "top_confusion_outbound": row.get("top_confusion_outbound"),
                    "top_confusion_inbound": row.get("top_confusion_inbound"),
                },
            }
        )
    return {
        "schema_version": "upload_bundle_stage_comparison.v1",
        "pair_count": len(comparison_pairs),
        "per_recipe": per_recipe_rows,
        "per_label": per_label_rows,
    }


def _write_upload_bundle_three_files(
    *,
    output_dir: Path,
    source_dir: Path | None = None,
    high_level_only: bool = False,
    target_bundle_size_bytes: int | None = None,
) -> dict[str, Any]:
    source_root = source_dir.resolve() if isinstance(source_dir, Path) else output_dir.resolve()
    output_root = output_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    group_target_size_bytes = (
        max(int(target_bundle_size_bytes), 1)
        if high_level_only and target_bundle_size_bytes is not None
        else GROUP_UPLOAD_BUNDLE_TARGET_BYTES
    )

    context = _upload_bundle_build_context(source_root=source_root)
    run_index_payload = context.get("run_index_payload", {})
    comparison_summary_payload = context.get("comparison_summary_payload", {})
    process_manifest_payload = context.get("process_manifest_payload", {})
    starter_manifest_payload = context.get("starter_manifest_payload", {})

    run_rows = context.get("run_rows")
    run_rows = run_rows if isinstance(run_rows, list) else []
    comparison_pairs = context.get("comparison_pairs")
    comparison_pairs = comparison_pairs if isinstance(comparison_pairs, list) else []
    changed_line_rows = context.get("changed_line_rows")
    changed_line_rows = changed_line_rows if isinstance(changed_line_rows, list) else []
    pair_breakdown_rows = context.get("pair_breakdown_rows")
    pair_breakdown_rows = pair_breakdown_rows if isinstance(pair_breakdown_rows, list) else []
    recipe_triage_rows = context.get("recipe_triage_rows")
    recipe_triage_rows = recipe_triage_rows if isinstance(recipe_triage_rows, list) else []
    call_inventory_rows = context.get("call_inventory_rows")
    call_inventory_rows = call_inventory_rows if isinstance(call_inventory_rows, list) else []
    selected_packets = context.get("selected_packets")
    selected_packets = selected_packets if isinstance(selected_packets, list) else []
    run_dir_by_id = context.get("run_dir_by_id")
    run_dir_by_id = run_dir_by_id if isinstance(run_dir_by_id, dict) else {}
    advertised_counts = context.get("advertised_counts")
    advertised_counts = advertised_counts if isinstance(advertised_counts, dict) else {}
    starter_pack_physical_present = bool(context.get("starter_pack_present"))
    discovered_run_dirs = context.get("discovered_run_dirs")
    discovered_run_dirs = discovered_run_dirs if isinstance(discovered_run_dirs, list) else []
    group_artifact_selection: dict[str, Any] = {
        "mode": "full",
        "target_bundle_size_bytes": None,
        "artifact_budget_bytes": None,
        "selected_artifact_count": None,
        "selected_artifact_bytes": None,
        "discovered_run_count": len(discovered_run_dirs),
        "per_run_included_files": [],
    }

    run_output_dirs = {
        str(row.get("output_subdir") or "")
        for row in run_rows
        if isinstance(row, dict) and str(row.get("output_subdir") or "")
    }

    if high_level_only:
        selected_paths, selection_meta = _upload_bundle_select_high_level_artifact_paths(
            source_root=source_root,
            discovered_run_dirs=discovered_run_dirs,
            target_bundle_size_bytes=group_target_size_bytes,
        )
        artifact_paths = list(selected_paths)
        group_artifact_selection = dict(selection_meta)
    else:
        artifact_paths = []
        excluded = set(UPLOAD_BUNDLE_FILE_NAMES)
        for path in sorted(source_root.rglob("*")):
            if not path.is_file():
                continue
            if source_root == output_root:
                if path.parent == output_root and path.name in excluded:
                    continue
            elif path.is_relative_to(output_root):
                # Avoid recursively bundling previously written bundle files when the
                # bundle output lives inside the source tree.
                continue
            relative_path = str(path.relative_to(source_root).as_posix())
            if relative_path in excluded:
                continue
            artifact_paths.append(path)

    payload_path = output_root / UPLOAD_BUNDLE_PAYLOAD_FILE_NAME
    artifact_index: list[dict[str, Any]] = []
    with payload_path.open("w", encoding="utf-8") as handle:
        for payload_row_number, artifact_path in enumerate(artifact_paths, start=1):
            relative_path = str(artifact_path.relative_to(source_root).as_posix())
            raw_bytes = artifact_path.read_bytes()
            content_type = _upload_bundle_content_type(artifact_path)
            category, run_subdir = _upload_bundle_category(relative_path, run_output_dirs)
            sha256 = hashlib.sha256(raw_bytes).hexdigest()

            payload_row: dict[str, Any] = {
                "path": relative_path,
                "content_type": content_type,
                "category": category,
                "run_subdir": run_subdir,
                "bytes": len(raw_bytes),
                "sha256": sha256,
            }
            parsed_mode = "base64"
            try:
                if content_type == "json":
                    text = raw_bytes.decode("utf-8")
                    payload_row["content_json"] = json.loads(text)
                    parsed_mode = "json"
                elif content_type == "jsonl":
                    text = raw_bytes.decode("utf-8")
                    payload_row["content_jsonl_rows"] = _upload_bundle_parse_jsonl_text(text)
                    parsed_mode = "jsonl"
                elif content_type in {"markdown", "text"}:
                    payload_row["content_text"] = raw_bytes.decode("utf-8")
                    parsed_mode = "utf8_text"
                elif content_type == "csv":
                    text = raw_bytes.decode("utf-8")
                    payload_row["content_text"] = text
                    payload_row["content_csv"] = _upload_bundle_parse_csv_text(text)
                    parsed_mode = "csv_plus_text"
                elif content_type == "jsonl_gzip":
                    payload_row["raw_gzip_base64"] = base64.b64encode(raw_bytes).decode("ascii")
                    decompressed_text = gzip.decompress(raw_bytes).decode("utf-8")
                    payload_row["content_jsonl_rows"] = _upload_bundle_parse_jsonl_text(
                        decompressed_text
                    )
                    parsed_mode = "gzip_plus_jsonl"
                elif content_type == "gzip":
                    payload_row["raw_gzip_base64"] = base64.b64encode(raw_bytes).decode("ascii")
                    try:
                        payload_row["decompressed_text"] = gzip.decompress(raw_bytes).decode("utf-8")
                        parsed_mode = "gzip_plus_text"
                    except (OSError, UnicodeDecodeError):
                        parsed_mode = "gzip_base64"
                else:
                    payload_row["content_base64"] = base64.b64encode(raw_bytes).decode("ascii")
                    parsed_mode = "base64"
            except (UnicodeDecodeError, json.JSONDecodeError, csv.Error, OSError) as exc:
                payload_row["parse_error"] = f"{exc.__class__.__name__}: {exc}"
                payload_row["content_base64"] = base64.b64encode(raw_bytes).decode("ascii")
                parsed_mode = "base64_fallback"

            payload_row["parsed_mode"] = parsed_mode
            handle.write(json.dumps(payload_row, ensure_ascii=False))
            handle.write("\n")

            artifact_index.append(
                {
                    "path": relative_path,
                    "payload_row": payload_row_number,
                    "content_type": content_type,
                    "category": category,
                    "run_subdir": run_subdir,
                    "bytes": len(raw_bytes),
                    "sha256": sha256,
                    "parsed_mode": parsed_mode,
                }
            )

    artifact_row_lookup = {
        str(row.get("path") or ""): int(row.get("payload_row") or 0)
        for row in artifact_index
        if isinstance(row, dict)
        and str(row.get("path") or "")
        and _coerce_int(row.get("payload_row")) is not None
    }
    artifact_paths_by_basename: dict[str, list[str]] = defaultdict(list)
    for artifact_path in artifact_row_lookup:
        basename = artifact_path.rsplit("/", 1)[-1]
        if basename:
            artifact_paths_by_basename[basename].append(artifact_path)

    def _best_locator_path(paths: list[str]) -> str | None:
        if not paths:
            return None
        ranked = sorted(
            paths,
            key=lambda value: (
                value.count("/"),
                len(value),
                value,
            ),
        )
        return ranked[0]

    def _rows_to_csv_text(
        rows: list[dict[str, Any]],
        *,
        preferred_fieldnames: tuple[str, ...] = (),
    ) -> str:
        fieldnames: list[str] = []
        seen: set[str] = set()
        for name in preferred_fieldnames:
            key = str(name or "")
            if key and key not in seen:
                seen.add(key)
                fieldnames.append(key)
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in row.keys():
                key_text = str(key or "")
                if key_text and key_text not in seen:
                    seen.add(key_text)
                    fieldnames.append(key_text)

        if not fieldnames:
            return ""

        def _csv_value(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return str(value)

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            if not isinstance(row, dict):
                continue
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})
        return buffer.getvalue()

    def _append_virtual_payload_row(
        *,
        path: str,
        content_type: str,
        content_json: dict[str, Any] | None = None,
        content_jsonl_rows: list[dict[str, Any]] | None = None,
        content_text: str | None = None,
    ) -> None:
        relative_path = str(path or "").strip()
        if not relative_path or relative_path in artifact_row_lookup:
            return

        payload_row_number = len(artifact_index) + 1
        payload_row: dict[str, Any] = {
            "path": relative_path,
            "content_type": content_type,
            "category": "derived_artifact",
            "run_subdir": None,
        }
        parsed_mode = "base64"
        raw_bytes = b""

        if content_type == "json":
            json_payload = content_json if isinstance(content_json, dict) else {}
            raw_text = json.dumps(json_payload, ensure_ascii=False, sort_keys=True)
            raw_bytes = raw_text.encode("utf-8")
            payload_row["content_json"] = json_payload
            parsed_mode = "json"
        elif content_type == "jsonl":
            rows_payload = (
                [row for row in content_jsonl_rows if isinstance(row, dict)]
                if isinstance(content_jsonl_rows, list)
                else []
            )
            raw_text = "".join(
                f"{json.dumps(row, ensure_ascii=False, sort_keys=True)}\n"
                for row in rows_payload
            )
            raw_bytes = raw_text.encode("utf-8")
            payload_row["content_jsonl_rows"] = rows_payload
            parsed_mode = "jsonl"
        elif content_type == "csv":
            text_payload = str(content_text or "")
            raw_bytes = text_payload.encode("utf-8")
            payload_row["content_text"] = text_payload
            payload_row["content_csv"] = _upload_bundle_parse_csv_text(text_payload)
            parsed_mode = "csv_plus_text"
        elif content_type in {"markdown", "text"}:
            text_payload = str(content_text or "")
            raw_bytes = text_payload.encode("utf-8")
            payload_row["content_text"] = text_payload
            parsed_mode = "utf8_text"
        else:
            base64_payload = base64.b64encode(str(content_text or "").encode("utf-8")).decode(
                "ascii"
            )
            raw_bytes = base64.b64decode(base64_payload.encode("ascii"))
            payload_row["content_base64"] = base64_payload
            parsed_mode = "base64"

        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        payload_row["bytes"] = len(raw_bytes)
        payload_row["sha256"] = sha256
        payload_row["parsed_mode"] = parsed_mode

        with payload_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload_row, ensure_ascii=False))
            handle.write("\n")

        artifact_index.append(
            {
                "path": relative_path,
                "payload_row": payload_row_number,
                "content_type": content_type,
                "category": "derived_artifact",
                "run_subdir": None,
                "bytes": len(raw_bytes),
                "sha256": sha256,
                "parsed_mode": parsed_mode,
            }
        )
        artifact_row_lookup[relative_path] = payload_row_number
        basename = relative_path.rsplit("/", 1)[-1]
        if basename:
            artifact_paths_by_basename[basename].append(relative_path)

    run_diagnostics: list[dict[str, Any]] = []
    for row in run_rows:
        if not isinstance(row, dict):
            continue
        run_id = str(row.get("run_id") or "")
        output_subdir = str(row.get("output_subdir") or "")
        if not output_subdir:
            continue
        codex_enabled = _upload_bundle_is_codex_pipeline_enabled(
            row.get("llm_recipe_pipeline")
        )
        summary_path = source_root / output_subdir / "need_to_know_summary.json"
        summary_payload = _load_json(summary_path) if summary_path.is_file() else {}
        sample_counts = summary_payload.get("sample_counts")
        sample_counts = sample_counts if isinstance(sample_counts, dict) else {}
        run_dir_candidate = run_dir_by_id.get(run_id)
        run_dir = run_dir_candidate if isinstance(run_dir_candidate, Path) else None
        derived_statuses: dict[str, str] = {}
        if run_dir is not None:
            derived_statuses = _upload_bundle_derive_run_diagnostic_statuses(
                run_dir=run_dir,
                run_id=run_id,
                output_subdir=output_subdir,
                append_virtual_payload_row=_append_virtual_payload_row,
            )

        def _sample_status(name: str) -> str:
            sample_payload = sample_counts.get(name)
            if isinstance(sample_payload, dict):
                return str(sample_payload.get("status") or "unknown")
            return "missing"

        def _resolved_status(name: str) -> str:
            sample_status = _sample_status(name)
            if sample_status != "missing":
                return sample_status
            derived_status = str(derived_statuses.get(name) or "").strip()
            if derived_status:
                return derived_status
            if (
                not codex_enabled
                and name
                in {
                    PROMPT_WARNING_AGGREGATE_FILE_NAME,
                    PROJECTION_TRACE_FILE_NAME,
                    PREPROCESS_TRACE_FAILURES_FILE_NAME,
                }
            ):
                return "not_applicable"
            return sample_status

        run_diagnostics.append(
            {
                "run_id": run_id,
                "output_subdir": output_subdir,
                "source_file": row.get("source_file"),
                "overall_line_accuracy": _coerce_float(row.get("overall_line_accuracy")),
                "practical_f1": _coerce_float(row.get("practical_f1")),
                "full_prompt_log_status": str(row.get("full_prompt_log_status") or "unknown"),
                "need_to_know_summary_path": f"{output_subdir}/need_to_know_summary.json",
                "prompt_warning_aggregate_status": _resolved_status(
                    PROMPT_WARNING_AGGREGATE_FILE_NAME
                ),
                "projection_trace_status": _resolved_status(PROJECTION_TRACE_FILE_NAME),
                "wrong_label_full_context_status": _resolved_status(
                    WRONG_LABEL_FULL_CONTEXT_FILE_NAME
                ),
                "preprocess_trace_failures_status": _resolved_status(
                    PREPROCESS_TRACE_FAILURES_FILE_NAME
                ),
            }
        )

    largest_regressions: list[dict[str, Any]] = []
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        delta_payload = pair.get("delta_codex_minus_baseline")
        delta_payload = delta_payload if isinstance(delta_payload, dict) else {}
        practical_delta = _coerce_float(delta_payload.get("practical_f1"))
        if practical_delta is None:
            continue
        largest_regressions.append(
            {
                "source_key": str(pair.get("source_key") or ""),
                "codex_run_id": str(
                    (pair.get("codex_run") or {}).get("run_id")
                    if isinstance(pair.get("codex_run"), dict)
                    else ""
                ),
                "baseline_run_id": str(
                    (pair.get("baseline_run") or {}).get("run_id")
                    if isinstance(pair.get("baseline_run"), dict)
                    else ""
                ),
                "delta_practical_f1": practical_delta,
                "delta_overall_line_accuracy": _coerce_float(
                    delta_payload.get("overall_line_accuracy")
                ),
                "changed_line_count": int(_coerce_int(pair.get("changed_line_count")) or 0),
            }
        )
    largest_regressions.sort(
        key=lambda row: (
            float(row.get("delta_practical_f1") or 0.0),
            float(row.get("delta_overall_line_accuracy") or 0.0),
            -int(row.get("changed_line_count") or 0),
            str(row.get("source_key") or ""),
        )
    )
    largest_regressions = largest_regressions[:5]

    per_label_metrics = _upload_bundle_build_per_label_metrics(
        comparison_pairs=comparison_pairs,
        run_dir_by_id=run_dir_by_id,
    )
    pass_stage_per_label_metrics = _upload_bundle_collect_pass_stage_per_label_metrics(
        comparison_pairs=comparison_pairs,
        run_dir_by_id=run_dir_by_id,
    )
    stage_separated_comparison = _upload_bundle_build_stage_separated_comparison(
        recipe_triage_rows=recipe_triage_rows,
        per_label_metrics=per_label_metrics,
        comparison_pairs=comparison_pairs,
        pass_stage_per_label_metrics=pass_stage_per_label_metrics,
    )
    failure_ledger = _upload_bundle_build_failure_ledger(
        recipe_triage_rows=recipe_triage_rows,
        call_inventory_rows=call_inventory_rows,
    )
    call_runtime_inventory = _upload_bundle_build_call_runtime_inventory(
        call_inventory_rows=call_inventory_rows,
        run_dir_by_id=run_dir_by_id,
    )
    line_role_signal_summary = _upload_bundle_build_line_role_confidence_summary(
        source_root=source_root,
        run_dir_by_id=run_dir_by_id,
    )
    regression_casebook = _upload_bundle_build_regression_casebook(
        recipe_triage_rows=recipe_triage_rows,
        changed_line_rows=changed_line_rows,
    )
    changed_line_stratified = _upload_bundle_build_changed_line_stratified_sample(
        changed_line_rows
    )
    triage_packet_rows = _upload_bundle_build_triage_packet_rows(recipe_triage_rows)
    triage_packet_summary = {
        "schema_version": UPLOAD_BUNDLE_TRIAGE_PACKET_SCHEMA_VERSION,
        "row_count": len(triage_packet_rows),
        "empty_packet_note": (
            ""
            if triage_packet_rows
            else "No triage rows were available from source or derived comparison artifacts."
        ),
        "sample_rows": triage_packet_rows[:40],
    }
    net_error_blame_summary = _upload_bundle_build_net_error_blame_summary(
        changed_line_rows=changed_line_rows,
        recipe_triage_rows=recipe_triage_rows,
        comparison_pairs=comparison_pairs,
    )
    config_version_metadata = _upload_bundle_build_config_version_metadata(
        source_root=source_root,
        run_rows=run_rows,
        comparison_pairs=comparison_pairs,
        run_dir_by_id=run_dir_by_id,
    )
    baseline_trace_parity = _starter_pack_build_baseline_trace_parity_cues(
        comparison_pairs=comparison_pairs,
        run_rows=run_rows,
        run_dir_by_id=run_dir_by_id,
    )
    (
        low_confidence_changed_lines_summary,
        low_confidence_changed_lines_rows,
    ) = _upload_bundle_build_low_confidence_changed_lines_packet(
        source_root=source_root,
        run_dir_by_id=run_dir_by_id,
        changed_line_rows=changed_line_rows,
    )
    derived_root_prefix = f"{UPLOAD_BUNDLE_DERIVED_DIR_NAME}/root"
    derived_starter_prefix = f"{UPLOAD_BUNDLE_DERIVED_DIR_NAME}/{STARTER_PACK_DIR_NAME}"
    derived_root_paths = {
        "run_index_json": f"{derived_root_prefix}/run_index.json",
        "comparison_summary_json": f"{derived_root_prefix}/comparison_summary.json",
        "process_manifest_json": f"{derived_root_prefix}/process_manifest.json",
        "group_high_level_packet_json": (
            f"{derived_root_prefix}/{GROUP_UPLOAD_BUNDLE_GROUP_PACKET_FILE_NAME}"
        ),
        "changed_lines_jsonl": f"{derived_root_prefix}/{CHANGED_LINES_FILE_NAME}",
        "per_recipe_breakdown_json": f"{derived_root_prefix}/{PER_RECIPE_BREAKDOWN_FILE_NAME}",
        "targeted_prompt_cases_md": f"{derived_root_prefix}/{TARGETED_PROMPT_CASES_FILE_NAME}",
        "label_policy_notes_md": f"{derived_root_prefix}/{LABEL_POLICY_NOTES_FILE_NAME}",
        "triage_packet_jsonl": f"{derived_root_prefix}/{STARTER_PACK_TRIAGE_PACKET_FILE_NAME}",
        "net_error_blame_summary_json": f"{derived_root_prefix}/net_error_blame_summary.json",
        "config_version_metadata_json": f"{derived_root_prefix}/config_version_metadata.json",
        "baseline_trace_parity_json": (
            f"{derived_root_prefix}/{STARTER_PACK_BASELINE_TRACE_PARITY_FILE_NAME}"
        ),
        "low_confidence_changed_lines_packet_jsonl": (
            f"{derived_root_prefix}/low_confidence_changed_lines.packet.jsonl"
        ),
    }
    derived_starter_paths = {
        "triage_jsonl": f"{derived_starter_prefix}/{STARTER_PACK_TRIAGE_FILE_NAME}",
        "triage_packet_jsonl": f"{derived_starter_prefix}/{STARTER_PACK_TRIAGE_PACKET_FILE_NAME}",
        "call_inventory_jsonl": f"{derived_starter_prefix}/{STARTER_PACK_CALL_INVENTORY_FILE_NAME}",
        "changed_lines_jsonl": f"{derived_starter_prefix}/{STARTER_PACK_CHANGED_LINES_FILE_NAME}",
        "warning_trace_summary_json": (
            f"{derived_starter_prefix}/{STARTER_PACK_WARNING_TRACE_SUMMARY_FILE_NAME}"
        ),
        "bridge_summary_jsonl": f"{derived_starter_prefix}/{STARTER_PACK_BRIDGE_SUMMARY_FILE_NAME}",
        "selected_packets_jsonl": f"{derived_starter_prefix}/{STARTER_PACK_SELECTED_PACKETS_FILE_NAME}",
        "casebook_md": f"{derived_starter_prefix}/{STARTER_PACK_CASEBOOK_FILE_NAME}",
        "manifest_json": f"{derived_starter_prefix}/{STARTER_PACK_MANIFEST_FILE_NAME}",
    }

    sorted_recipe_triage_rows = _upload_bundle_sort_recipe_triage_rows(recipe_triage_rows)
    serialized_sorted_recipe_triage_rows = [
        _starter_pack_serialize_recipe_triage_row(row)
        for row in sorted_recipe_triage_rows
    ]
    derived_warning_trace_summary = _build_warning_and_trace_summary(
        call_inventory_rows=call_inventory_rows,
        recipe_triage_rows=recipe_triage_rows,
        outside_span_trace_rows=[],
    )
    derived_bridge_summary_rows = [dict(row) for row in sorted_recipe_triage_rows]
    derived_starter_manifest = (
        dict(starter_manifest_payload)
        if isinstance(starter_manifest_payload, dict) and starter_manifest_payload
        else {
            "schema_version": "starter_pack_manifest.derived.v1",
            "generated_at": _timestamp_now(),
            "source_dir": str(source_root),
            "derived_from_upload_bundle": True,
            "row_counts": {
                "recipe_triage_rows": len(sorted_recipe_triage_rows),
                "call_inventory_rows": len(call_inventory_rows),
                "changed_lines_rows": len(changed_line_rows),
                "selected_packets": len(selected_packets),
            },
        }
    )

    _append_virtual_payload_row(
        path=derived_root_paths["run_index_json"],
        content_type="json",
        content_json={
            "schema_version": "upload_bundle_derived_run_index.v1",
            "runs": [dict(row) for row in run_rows if isinstance(row, dict)],
        },
    )
    _append_virtual_payload_row(
        path=derived_root_paths["comparison_summary_json"],
        content_type="json",
        content_json={
            "schema_version": "upload_bundle_derived_comparison_summary.v1",
            "pairs": [dict(row) for row in comparison_pairs if isinstance(row, dict)],
            "changed_lines_total": len(changed_line_rows),
        },
    )
    _append_virtual_payload_row(
        path=derived_root_paths["process_manifest_json"],
        content_type="json",
        content_json=(
            dict(process_manifest_payload)
            if isinstance(process_manifest_payload, dict) and process_manifest_payload
            else {
                "schema_version": "upload_bundle_derived_process_manifest.v1",
                "generated_at": _timestamp_now(),
                "source_dir": str(source_root),
                "upload_bundle_context_only": True,
            }
        ),
    )
    _append_virtual_payload_row(
        path=derived_root_paths["changed_lines_jsonl"],
        content_type="jsonl",
        content_jsonl_rows=[row for row in changed_line_rows if isinstance(row, dict)],
    )
    _append_virtual_payload_row(
        path=derived_root_paths["per_recipe_breakdown_json"],
        content_type="json",
        content_json={
            "schema_version": "upload_bundle_derived_per_recipe_breakdown.v1",
            "pair_breakdown_count": len(pair_breakdown_rows),
            "pairs": [dict(row) for row in pair_breakdown_rows if isinstance(row, dict)],
        },
    )
    _append_virtual_payload_row(
        path=derived_root_paths["targeted_prompt_cases_md"],
        content_type="markdown",
        content_text=_render_starter_pack_casebook(regression_casebook.get("packets") or []),
    )
    _append_virtual_payload_row(
        path=derived_root_paths["label_policy_notes_md"],
        content_type="markdown",
        content_text=_render_starter_pack_label_policy(),
    )
    _append_virtual_payload_row(
        path=derived_root_paths["triage_packet_jsonl"],
        content_type="jsonl",
        content_jsonl_rows=[dict(row) for row in triage_packet_rows],
    )
    _append_virtual_payload_row(
        path=derived_root_paths["net_error_blame_summary_json"],
        content_type="json",
        content_json=net_error_blame_summary,
    )
    _append_virtual_payload_row(
        path=derived_root_paths["config_version_metadata_json"],
        content_type="json",
        content_json=config_version_metadata,
    )
    _append_virtual_payload_row(
        path=derived_root_paths["baseline_trace_parity_json"],
        content_type="json",
        content_json=baseline_trace_parity,
    )
    _append_virtual_payload_row(
        path=derived_root_paths["low_confidence_changed_lines_packet_jsonl"],
        content_type="jsonl",
        content_jsonl_rows=[dict(row) for row in low_confidence_changed_lines_rows],
    )
    _append_virtual_payload_row(
        path=derived_starter_paths["triage_jsonl"],
        content_type="jsonl",
        content_jsonl_rows=serialized_sorted_recipe_triage_rows,
    )
    _append_virtual_payload_row(
        path=derived_starter_paths["triage_packet_jsonl"],
        content_type="jsonl",
        content_jsonl_rows=[dict(row) for row in triage_packet_rows],
    )
    _append_virtual_payload_row(
        path=derived_starter_paths["call_inventory_jsonl"],
        content_type="jsonl",
        content_jsonl_rows=[row for row in call_inventory_rows if isinstance(row, dict)],
    )
    _append_virtual_payload_row(
        path=derived_starter_paths["changed_lines_jsonl"],
        content_type="jsonl",
        content_jsonl_rows=[row for row in changed_line_rows if isinstance(row, dict)],
    )
    _append_virtual_payload_row(
        path=derived_starter_paths["warning_trace_summary_json"],
        content_type="json",
        content_json=derived_warning_trace_summary,
    )
    _append_virtual_payload_row(
        path=derived_starter_paths["bridge_summary_jsonl"],
        content_type="jsonl",
        content_jsonl_rows=derived_bridge_summary_rows,
    )
    _append_virtual_payload_row(
        path=derived_starter_paths["selected_packets_jsonl"],
        content_type="jsonl",
        content_jsonl_rows=[row for row in selected_packets if isinstance(row, dict)],
    )
    _append_virtual_payload_row(
        path=derived_starter_paths["casebook_md"],
        content_type="markdown",
        content_text=_render_starter_pack_casebook(selected_packets),
    )
    _append_virtual_payload_row(
        path=derived_starter_paths["manifest_json"],
        content_type="json",
        content_json=derived_starter_manifest,
    )

    group_high_level_packet_summary: dict[str, Any] = {
        "enabled": bool(high_level_only),
        "target_bundle_size_bytes": (
            int(group_target_size_bytes) if high_level_only else None
        ),
        "target_bundle_size_mb": (
            round(group_target_size_bytes / (1024 * 1024), 3)
            if high_level_only
            else None
        ),
        "artifact_selection": group_artifact_selection,
        "run_count": len(discovered_run_dirs),
        "runs_with_sampled_rows": 0,
        "sampled_wrong_line_rows_total": 0,
        "sampled_wrong_line_bytes_total": 0,
    }
    if high_level_only:
        payload_bytes_before_group_packet = 0
        try:
            payload_bytes_before_group_packet = int(payload_path.stat().st_size)
        except OSError:
            payload_bytes_before_group_packet = 0
        group_high_level_packet = _upload_bundle_build_group_high_level_packet(
            source_root=source_root,
            discovered_run_dirs=discovered_run_dirs,
            run_rows=run_rows,
            run_diagnostics=run_diagnostics,
            target_bundle_size_bytes=group_target_size_bytes,
            payload_bytes_before_packet=payload_bytes_before_group_packet,
            artifact_selection=group_artifact_selection,
        )
        _append_virtual_payload_row(
            path=derived_root_paths["group_high_level_packet_json"],
            content_type="json",
            content_json=group_high_level_packet,
        )
        group_high_level_packet_summary = {
            "enabled": True,
            "target_bundle_size_bytes": int(
                group_high_level_packet.get("target_bundle_size_bytes")
                or group_target_size_bytes
            ),
            "target_bundle_size_mb": _coerce_float(
                group_high_level_packet.get("target_bundle_size_mb")
            ),
            "payload_bytes_before_group_packet": int(
                _coerce_int(group_high_level_packet.get("payload_bytes_before_group_packet"))
                or payload_bytes_before_group_packet
            ),
            "reserved_bytes_for_index_overview": int(
                _coerce_int(group_high_level_packet.get("reserved_bytes_for_index_overview"))
                or 0
            ),
            "budget_for_group_samples_bytes": int(
                _coerce_int(group_high_level_packet.get("budget_for_group_samples_bytes"))
                or 0
            ),
            "per_run_sample_budget_bytes": int(
                _coerce_int(group_high_level_packet.get("per_run_sample_budget_bytes"))
                or 0
            ),
            "artifact_selection": group_artifact_selection,
            "run_count": int(_coerce_int(group_high_level_packet.get("run_count")) or 0),
            "runs_with_sampled_rows": int(
                _coerce_int(group_high_level_packet.get("runs_with_sampled_rows")) or 0
            ),
            "sampled_wrong_line_rows_total": int(
                _coerce_int(group_high_level_packet.get("sampled_wrong_line_rows_total")) or 0
            ),
            "sampled_wrong_line_bytes_total": int(
                _coerce_int(group_high_level_packet.get("sampled_wrong_line_bytes_total")) or 0
            ),
        }
    else:
        _append_virtual_payload_row(
            path=derived_root_paths["group_high_level_packet_json"],
            content_type="json",
            content_json={
                "schema_version": "upload_bundle_group_high_level.v1",
                "generated_at": _timestamp_now(),
                "enabled": False,
                "reason": "group_high_level_mode_disabled",
                "target_bundle_size_bytes": None,
                "run_count": len(discovered_run_dirs),
            },
        )

    alias_metadata = _upload_bundle_build_alias_metadata(
        artifact_index=artifact_index,
        starter_manifest_payload=starter_manifest_payload,
    )
    alias_to_canonical: dict[str, str] = {}
    content_equivalent_groups = alias_metadata.get("content_equivalent_groups")
    if isinstance(content_equivalent_groups, list):
        for group in content_equivalent_groups:
            if not isinstance(group, dict):
                continue
            canonical_path = str(group.get("canonical_path") or "").strip()
            if not canonical_path:
                continue
            alias_paths = group.get("alias_paths")
            alias_paths = alias_paths if isinstance(alias_paths, list) else []
            for alias_path in alias_paths:
                alias_text = str(alias_path or "").strip()
                if alias_text:
                    alias_to_canonical[alias_text] = canonical_path

    run_count_verified = len(run_rows)
    if run_count_verified <= 0:
        run_count_verified = len(discovered_run_dirs)
    pair_count_verified_count = len(comparison_pairs)
    changed_lines_verified_count = len(changed_line_rows)

    advertised_run_count = _coerce_int(advertised_counts.get("run_count"))
    advertised_pair_count = _coerce_int(advertised_counts.get("pair_count"))
    advertised_changed_lines = _coerce_int(advertised_counts.get("changed_lines_total"))
    if advertised_changed_lines is None:
        advertised_changed_lines = _coerce_int(
            comparison_summary_payload.get("changed_lines_total")
        )

    run_count_match = (
        advertised_run_count == run_count_verified
        if advertised_run_count is not None
        else True
    )
    pair_count_match = (
        advertised_pair_count == pair_count_verified_count
        if advertised_pair_count is not None
        else True
    )
    changed_lines_match = (
        advertised_changed_lines == changed_lines_verified_count
        if advertised_changed_lines is not None
        else True
    )
    topline_consistent = bool(run_count_match and pair_count_match and changed_lines_match)

    full_prompt_log_rows = _coerce_int(process_manifest_payload.get("full_prompt_log_rows"))
    if full_prompt_log_rows is None:
        full_prompt_log_rows = len(
            [
                row
                for row in run_diagnostics
                if str(row.get("full_prompt_log_status") or "").strip() == "complete"
            ]
        )

    topline = {
        "run_count": run_count_verified,
        "pair_count": pair_count_verified_count,
        "changed_lines_total": changed_lines_verified_count,
        "full_prompt_log_status": str(
            process_manifest_payload.get("full_prompt_log_status") or "unknown"
        ),
        "full_prompt_log_rows": int(full_prompt_log_rows or 0),
        "largest_practical_f1_regressions": largest_regressions,
        "pair_count_sufficient_for_generalization": (
            pair_count_verified_count >= UPLOAD_BUNDLE_MIN_PAIRS_FOR_GENERALIZATION
        ),
        "additional_pairs_needed_for_generalization": max(
            UPLOAD_BUNDLE_MIN_PAIRS_FOR_GENERALIZATION - pair_count_verified_count,
            0,
        ),
    }

    self_check = {
        "starter_pack_present": starter_pack_physical_present,
        "starter_pack_physical_dir_present": starter_pack_physical_present,
        "run_count_verified": run_count_match,
        "pair_count_verified": pair_count_match,
        "changed_lines_verified": changed_lines_match,
        "topline_consistent": topline_consistent,
        "verification_details": {
            "run_count": {
                "advertised": advertised_run_count,
                "recomputed": run_count_verified,
            },
            "pair_count": {
                "advertised": advertised_pair_count,
                "recomputed": pair_count_verified_count,
            },
            "changed_lines_total": {
                "advertised": advertised_changed_lines,
                "recomputed": changed_lines_verified_count,
            },
        },
    }

    heavy_markers = (
        "full_prompt_log.jsonl",
        "prompt_request_response_log.txt",
        "llm_manifest.json",
        ".split-cache",
        "codex_exec_activity.csv",
        "wrong_label_lines.with_context.full.jsonl.gz",
        "preprocess_trace_failures.jsonl.gz",
    )

    def _is_heavy_artifact(path: str) -> bool:
        lowered = path.lower()
        return any(marker in lowered for marker in heavy_markers)

    locator_alias_rewrites = 0

    def _canonical_locator(path: str, payload_row: int) -> dict[str, Any]:
        nonlocal locator_alias_rewrites
        canonical_path = alias_to_canonical.get(path)
        if canonical_path:
            canonical_payload_row = artifact_row_lookup.get(canonical_path)
            if canonical_payload_row is not None:
                locator_alias_rewrites += 1
                return {
                    "path": canonical_path,
                    "payload_row": int(canonical_payload_row),
                    "alias_path": path,
                }
        return {"path": path, "payload_row": int(payload_row)}

    def _payload_locator(
        *,
        paths: tuple[str, ...] = (),
        basenames: tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        for path in paths:
            payload_row = artifact_row_lookup.get(path)
            if payload_row is not None:
                return _canonical_locator(path, int(payload_row))
        for basename in basenames:
            candidate_paths = artifact_paths_by_basename.get(basename, [])
            best_path = _best_locator_path(candidate_paths)
            if best_path is None:
                continue
            payload_row = artifact_row_lookup.get(best_path)
            if payload_row is not None:
                return _canonical_locator(best_path, int(payload_row))
        return None

    heavy_artifact_locators = [
        {
            "path": str(row.get("path") or ""),
            "payload_row": int(row.get("payload_row") or 0),
            "category": row.get("category"),
            "reason": "deprioritized_in_default_reading",
        }
        for row in artifact_index
        if isinstance(row, dict)
        and _is_heavy_artifact(str(row.get("path") or ""))
        and _coerce_int(row.get("payload_row")) is not None
    ]
    heavy_artifact_locators.sort(
        key=lambda row: (
            str(row.get("path") or ""),
            int(row.get("payload_row") or 0),
        )
    )

    per_run_summary_locators = [
        {
            "run_id": str(item.get("run_id") or ""),
            "summary": _payload_locator(
                paths=(
                    str(item.get("need_to_know_summary_path") or ""),
                    (
                        f"{str(item.get('output_subdir') or '').strip()}/run_manifest.json"
                        if str(item.get("output_subdir") or "").strip()
                        else ""
                    ),
                    (
                        f"{str(item.get('output_subdir') or '').strip()}/eval_report.json"
                        if str(item.get("output_subdir") or "").strip()
                        else ""
                    ),
                ),
            ),
        }
        for item in run_diagnostics
        if isinstance(item, dict) and str(item.get("need_to_know_summary_path") or "")
    ]

    row_locators = {
        "root_files": {
            "run_index_json": _payload_locator(
                paths=("run_index.json", derived_root_paths["run_index_json"]),
                basenames=("run_index.json",),
            ),
            "comparison_summary_json": _payload_locator(
                paths=(
                    "comparison_summary.json",
                    "codex_vs_vanilla_comparison.json",
                    derived_root_paths["comparison_summary_json"],
                ),
                basenames=("comparison_summary.json", "codex_vs_vanilla_comparison.json"),
            ),
            "process_manifest_json": _payload_locator(
                paths=("process_manifest.json", derived_root_paths["process_manifest_json"]),
                basenames=("process_manifest.json",),
            ),
            "group_high_level_packet_json": _payload_locator(
                paths=(derived_root_paths["group_high_level_packet_json"],),
                basenames=(GROUP_UPLOAD_BUNDLE_GROUP_PACKET_FILE_NAME,),
            ),
            "changed_lines_jsonl": _payload_locator(
                paths=(
                    CHANGED_LINES_FILE_NAME,
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_CHANGED_LINES_FILE_NAME}",
                    derived_root_paths["changed_lines_jsonl"],
                    derived_starter_paths["changed_lines_jsonl"],
                ),
                basenames=(
                    CHANGED_LINES_FILE_NAME.rsplit("/", 1)[-1],
                    STARTER_PACK_CHANGED_LINES_FILE_NAME,
                ),
            ),
            "per_recipe_breakdown_json": _payload_locator(
                paths=(
                    PER_RECIPE_BREAKDOWN_FILE_NAME,
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_BREAKDOWN_MIRROR_FILE_NAME}",
                    derived_root_paths["per_recipe_breakdown_json"],
                ),
                basenames=(
                    PER_RECIPE_BREAKDOWN_FILE_NAME.rsplit("/", 1)[-1],
                    STARTER_PACK_BREAKDOWN_MIRROR_FILE_NAME,
                ),
            ),
            "targeted_prompt_cases_md": _payload_locator(
                paths=(
                    TARGETED_PROMPT_CASES_FILE_NAME,
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_CASEBOOK_FILE_NAME}",
                    derived_root_paths["targeted_prompt_cases_md"],
                    derived_starter_paths["casebook_md"],
                ),
                basenames=(
                    TARGETED_PROMPT_CASES_FILE_NAME.rsplit("/", 1)[-1],
                    STARTER_PACK_CASEBOOK_FILE_NAME,
                ),
            ),
            "label_policy_notes_md": _payload_locator(
                paths=(
                    LABEL_POLICY_NOTES_FILE_NAME,
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_LABEL_POLICY_FILE_NAME}",
                    derived_root_paths["label_policy_notes_md"],
                ),
                basenames=(
                    LABEL_POLICY_NOTES_FILE_NAME.rsplit("/", 1)[-1],
                    STARTER_PACK_LABEL_POLICY_FILE_NAME,
                ),
            ),
            "triage_packet_jsonl": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_TRIAGE_PACKET_FILE_NAME}",
                    derived_starter_paths["triage_packet_jsonl"],
                    derived_root_paths["triage_packet_jsonl"],
                ),
                basenames=(STARTER_PACK_TRIAGE_PACKET_FILE_NAME,),
            ),
            "net_error_blame_summary_json": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_NET_ERROR_BLAME_FILE_NAME}",
                    derived_root_paths["net_error_blame_summary_json"],
                ),
                basenames=(
                    STARTER_PACK_NET_ERROR_BLAME_FILE_NAME,
                    "net_error_blame_summary.json",
                ),
            ),
            "config_version_metadata_json": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_CONFIG_VERSION_METADATA_FILE_NAME}",
                    derived_root_paths["config_version_metadata_json"],
                ),
                basenames=(
                    STARTER_PACK_CONFIG_VERSION_METADATA_FILE_NAME,
                    "config_version_metadata.json",
                ),
            ),
            "low_confidence_changed_lines_packet_jsonl": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_LOW_CONFIDENCE_CHANGED_LINES_FILE_NAME}",
                    derived_root_paths["low_confidence_changed_lines_packet_jsonl"],
                ),
                basenames=(
                    STARTER_PACK_LOW_CONFIDENCE_CHANGED_LINES_FILE_NAME,
                    "low_confidence_changed_lines.packet.jsonl",
                ),
            ),
        },
        "starter_pack": {
            "triage_packet_jsonl": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_TRIAGE_PACKET_FILE_NAME}",
                    derived_starter_paths["triage_packet_jsonl"],
                    derived_root_paths["triage_packet_jsonl"],
                )
            ),
            "triage_jsonl": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_TRIAGE_FILE_NAME}",
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_TRIAGE_LEGACY_CSV_FILE_NAME}",
                    derived_starter_paths["triage_jsonl"],
                ),
                basenames=(
                    STARTER_PACK_TRIAGE_FILE_NAME,
                    STARTER_PACK_TRIAGE_LEGACY_CSV_FILE_NAME,
                ),
            ),
            "call_inventory_jsonl": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_CALL_INVENTORY_FILE_NAME}",
                    derived_starter_paths["call_inventory_jsonl"],
                )
            ),
            "changed_lines_jsonl": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_CHANGED_LINES_FILE_NAME}",
                    derived_starter_paths["changed_lines_jsonl"],
                )
            ),
            "warning_trace_summary_json": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_WARNING_TRACE_SUMMARY_FILE_NAME}",
                    derived_starter_paths["warning_trace_summary_json"],
                )
            ),
            "bridge_summary_jsonl": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_BRIDGE_SUMMARY_FILE_NAME}",
                    derived_starter_paths["bridge_summary_jsonl"],
                )
            ),
            "selected_packets_jsonl": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_SELECTED_PACKETS_FILE_NAME}",
                    derived_starter_paths["selected_packets_jsonl"],
                )
            ),
            "casebook_md": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_CASEBOOK_FILE_NAME}",
                    derived_starter_paths["casebook_md"],
                )
            ),
            "manifest_json": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_MANIFEST_FILE_NAME}",
                    derived_starter_paths["manifest_json"],
                )
            ),
            "net_error_blame_summary_json": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_NET_ERROR_BLAME_FILE_NAME}",
                    derived_root_paths["net_error_blame_summary_json"],
                )
            ),
            "config_version_metadata_json": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_CONFIG_VERSION_METADATA_FILE_NAME}",
                    derived_root_paths["config_version_metadata_json"],
                )
            ),
            "low_confidence_changed_lines_packet_jsonl": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_LOW_CONFIDENCE_CHANGED_LINES_FILE_NAME}",
                    derived_root_paths["low_confidence_changed_lines_packet_jsonl"],
                )
            ),
            "baseline_trace_parity_json": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_BASELINE_TRACE_PARITY_FILE_NAME}",
                    derived_root_paths["baseline_trace_parity_json"],
                )
            ),
        },
        "per_run_summaries": per_run_summary_locators,
        "deprioritized_heavy_artifacts": heavy_artifact_locators[:80],
    }

    starter_pack_locators = row_locators.get("starter_pack")
    starter_pack_locators = (
        starter_pack_locators if isinstance(starter_pack_locators, dict) else {}
    )
    starter_pack_effective_present = any(
        isinstance(value, dict) for value in starter_pack_locators.values()
    )
    self_check["starter_pack_present"] = starter_pack_effective_present

    critical_root_locators = row_locators.get("root_files")
    critical_root_locators = (
        critical_root_locators if isinstance(critical_root_locators, dict) else {}
    )
    critical_locator_values: list[Any] = list(critical_root_locators.values())
    per_run_locator_rows = row_locators.get("per_run_summaries")
    if isinstance(per_run_locator_rows, list):
        for row in per_run_locator_rows:
            if not isinstance(row, dict):
                continue
            critical_locator_values.append(row.get("summary"))
    critical_row_locator_total = len(critical_locator_values)
    critical_row_locator_populated = sum(
        1 for value in critical_locator_values if isinstance(value, dict)
    )
    self_check["critical_row_locators_populated"] = critical_row_locator_populated
    self_check["critical_row_locators_total"] = critical_row_locator_total
    self_check["critical_row_locators_coverage_ratio"] = (
        round(critical_row_locator_populated / critical_row_locator_total, 6)
        if critical_row_locator_total > 0
        else 0.0
    )

    pair_inventory = []
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        codex_run = pair.get("codex_run")
        baseline_run = pair.get("baseline_run")
        codex_payload = codex_run if isinstance(codex_run, dict) else {}
        baseline_payload = baseline_run if isinstance(baseline_run, dict) else {}
        delta_payload = (
            pair.get("delta_codex_minus_baseline")
            if isinstance(pair.get("delta_codex_minus_baseline"), dict)
            else {}
        )
        pair_inventory.append(
            {
                "source_key": str(pair.get("source_key") or ""),
                "codex_run_id": str(codex_payload.get("run_id") or ""),
                "baseline_run_id": str(baseline_payload.get("run_id") or ""),
                "changed_line_count": int(_coerce_int(pair.get("changed_line_count")) or 0),
                "delta_overall_line_accuracy": _coerce_float(
                    delta_payload.get("overall_line_accuracy")
                ),
                "delta_macro_f1_excluding_other": _coerce_float(
                    delta_payload.get("macro_f1_excluding_other")
                ),
                "delta_practical_f1": _coerce_float(delta_payload.get("practical_f1")),
            }
        )
    pair_inventory.sort(
        key=lambda row: (
            _float_or_zero(row.get("delta_practical_f1")),
            _float_or_zero(row.get("delta_overall_line_accuracy")),
            -int(row.get("changed_line_count") or 0),
            str(row.get("source_key") or ""),
        )
    )

    default_initial_views = [
        "topline",
        "self_check",
        "analysis.triage_packet",
        "analysis.net_error_blame_summary",
        "analysis.config_version_metadata",
        "analysis.per_label_metrics",
        "analysis.per_recipe_breakdown",
        "analysis.stage_separated_comparison",
        "analysis.failure_ledger",
        "analysis.regression_casebook",
        "analysis.changed_lines_stratified_sample",
        "analysis.low_confidence_changed_lines_packet",
        "analysis.call_inventory_runtime",
        "analysis.line_role_confidence_or_candidates",
    ]
    if high_level_only:
        default_initial_views.insert(2, "analysis.group_high_level")

    index_payload = {
        "bundle_version": "upload_bundle.v1",
        "generated_at": _timestamp_now(),
        "source_dir": str(source_root),
        "output_dir": str(output_root),
        "file_contract": {
            "overview_file": UPLOAD_BUNDLE_OVERVIEW_FILE_NAME,
            "artifact_index_file": UPLOAD_BUNDLE_INDEX_FILE_NAME,
            "payload_file": UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
        },
        "payload_contract": {
            "one_json_object_per_line": True,
            "join_key": "path",
            "row_locator_field": "payload_row",
            "lossless_guarantee": (
                "Every source artifact is represented in payload with sha256/bytes and "
                "full content (UTF-8 structured/text fields or base64 when binary/compressed)."
            ),
        },
        "topline": topline,
        "self_check": self_check,
        "run_diagnostics": run_diagnostics,
        "navigation": {
            "start_here": [
                UPLOAD_BUNDLE_OVERVIEW_FILE_NAME,
                UPLOAD_BUNDLE_INDEX_FILE_NAME,
            ],
            "default_initial_views": default_initial_views,
            "root_paths": [
                "README.md",
                "run_index.json",
                "comparison_summary.json",
                "codex_vs_vanilla_comparison.json",
                "process_manifest.json",
                derived_root_paths["group_high_level_packet_json"],
                CHANGED_LINES_FILE_NAME,
                PER_RECIPE_BREAKDOWN_FILE_NAME,
                TARGETED_PROMPT_CASES_FILE_NAME,
                LABEL_POLICY_NOTES_FILE_NAME,
                f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_TRIAGE_FILE_NAME}",
                f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_TRIAGE_PACKET_FILE_NAME}",
                f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_NET_ERROR_BLAME_FILE_NAME}",
                f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_CONFIG_VERSION_METADATA_FILE_NAME}",
                (
                    f"{STARTER_PACK_DIR_NAME}/"
                    f"{STARTER_PACK_LOW_CONFIDENCE_CHANGED_LINES_FILE_NAME}"
                ),
                f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_BASELINE_TRACE_PARITY_FILE_NAME}",
            ],
            "starter_pack_root": STARTER_PACK_DIR_NAME,
            "per_run_summary_paths": [
                item["need_to_know_summary_path"] for item in run_diagnostics
            ],
            "row_locators": row_locators,
            "alias_dedupe": {
                "content_equivalent_group_count": len(
                    alias_metadata.get("content_equivalent_groups")
                    if isinstance(alias_metadata.get("content_equivalent_groups"), list)
                    else []
                ),
                "locator_alias_rewrites": locator_alias_rewrites,
            },
            "deprioritized_patterns": list(heavy_markers),
            "full_payload_companion": UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
        },
        "analysis": {
            "benchmark_pair_inventory": {
                "pair_count": len(pair_inventory),
                "generalization_readiness": {
                    "minimum_pairs_for_generalization": (
                        UPLOAD_BUNDLE_MIN_PAIRS_FOR_GENERALIZATION
                    ),
                    "pair_count_sufficient_for_generalization": (
                        pair_count_verified_count
                        >= UPLOAD_BUNDLE_MIN_PAIRS_FOR_GENERALIZATION
                    ),
                    "additional_pairs_needed_for_generalization": max(
                        UPLOAD_BUNDLE_MIN_PAIRS_FOR_GENERALIZATION
                        - pair_count_verified_count,
                        0,
                    ),
                },
                "pairs": pair_inventory,
            },
            "triage_packet": triage_packet_summary,
            "net_error_blame_summary": net_error_blame_summary,
            "config_version_metadata": config_version_metadata,
            "group_high_level": group_high_level_packet_summary,
            "per_label_metrics": per_label_metrics,
            "top_confusion_deltas": _aggregate_confusion_deltas(
                {"pairs": comparison_pairs},
                top_k=20,
            ),
            "per_recipe_breakdown": {
                "pair_breakdown_count": len(pair_breakdown_rows),
                "pairs": pair_breakdown_rows,
            },
            "stage_separated_comparison": stage_separated_comparison,
            "failure_ledger": failure_ledger,
            "regression_casebook": regression_casebook,
            "changed_lines_stratified_sample": changed_line_stratified,
            "low_confidence_changed_lines_packet": low_confidence_changed_lines_summary,
            "call_inventory_runtime": call_runtime_inventory,
            "line_role_confidence_or_candidates": line_role_signal_summary,
            "selected_recipe_packets": {
                "packet_count": len(selected_packets),
                "packets": selected_packets,
            },
        },
        "alias_metadata": alias_metadata,
        "artifact_count": len(artifact_index),
        "artifact_index": artifact_index,
    }
    _write_json(output_root / UPLOAD_BUNDLE_INDEX_FILE_NAME, index_payload)

    overview_lines = [
        "# External AI Upload Bundle (3 files)",
        "",
        f"- Generated at: `{index_payload['generated_at']}`",
        f"- Source folder: `{source_root}`",
        f"- Bundle folder: `{output_root}`",
        "",
        "## Files",
        "",
        f"- `{UPLOAD_BUNDLE_OVERVIEW_FILE_NAME}`: human quick-start + topline diagnostics.",
        f"- `{UPLOAD_BUNDLE_INDEX_FILE_NAME}`: navigation index, topline metrics, artifact lookup.",
        f"- `{UPLOAD_BUNDLE_PAYLOAD_FILE_NAME}`: full artifact payload rows (lossless source data).",
        "",
        "## Quick Start",
        "",
        "1. Read `topline` and `self_check` in `upload_bundle_index.json`.",
        "2. Start with `analysis.triage_packet` (JSONL-first triage rows).",
        "3. Open `navigation.default_initial_views` in order for first-pass triage.",
        "4. Use `navigation.row_locators` to jump into `upload_bundle_payload.jsonl` rows.",
        "",
        "## Topline",
        "",
        f"- run_count: {topline['run_count']}",
        f"- pair_count: {topline['pair_count']}",
        f"- changed_lines_total: {topline['changed_lines_total']}",
        (
            "- pair_count_sufficient_for_generalization: "
            f"{'true' if topline['pair_count_sufficient_for_generalization'] else 'false'}"
        ),
        (
            "- additional_pairs_needed_for_generalization: "
            f"{int(topline['additional_pairs_needed_for_generalization'])}"
        ),
        f"- full_prompt_log_status: {topline['full_prompt_log_status']}",
        f"- full_prompt_log_rows: {topline['full_prompt_log_rows']}",
        "",
    ]
    overview_lines.extend(
        [
            "## Self-Check",
            "",
            (
                "- starter_pack_present: "
                f"{'true' if self_check['starter_pack_present'] else 'false'}"
            ),
            (
                "- starter_pack_physical_dir_present: "
                f"{'true' if self_check['starter_pack_physical_dir_present'] else 'false'}"
            ),
            (
                "- pair_count_verified: "
                f"{'true' if self_check['pair_count_verified'] else 'false'}"
            ),
            (
                "- changed_lines_verified: "
                f"{'true' if self_check['changed_lines_verified'] else 'false'}"
            ),
            (
                "- topline_consistent: "
                f"{'true' if self_check['topline_consistent'] else 'false'}"
            ),
            "",
        ]
    )
    if high_level_only:
        overview_lines.extend(
            [
                "## Group High-Level Budget",
                "",
                (
                    "- target_bundle_size_mb: "
                    f"{_serialize_float(_coerce_float(group_high_level_packet_summary.get('target_bundle_size_mb')))}"
                ),
                (
                    "- target_bundle_size_bytes: "
                    f"{int(_coerce_int(group_high_level_packet_summary.get('target_bundle_size_bytes')) or 0)}"
                ),
                (
                    "- payload_bytes_before_group_packet: "
                    f"{int(_coerce_int(group_high_level_packet_summary.get('payload_bytes_before_group_packet')) or 0)}"
                ),
                (
                    "- budget_for_group_samples_bytes: "
                    f"{int(_coerce_int(group_high_level_packet_summary.get('budget_for_group_samples_bytes')) or 0)}"
                ),
                (
                    "- per_run_sample_budget_bytes: "
                    f"{int(_coerce_int(group_high_level_packet_summary.get('per_run_sample_budget_bytes')) or 0)}"
                ),
                (
                    "- runs_with_sampled_rows: "
                    f"{int(_coerce_int(group_high_level_packet_summary.get('runs_with_sampled_rows')) or 0)}"
                ),
                (
                    "- sampled_wrong_line_rows_total: "
                    f"{int(_coerce_int(group_high_level_packet_summary.get('sampled_wrong_line_rows_total')) or 0)}"
                ),
                (
                    "- sampled_wrong_line_bytes_total: "
                    f"{int(_coerce_int(group_high_level_packet_summary.get('sampled_wrong_line_bytes_total')) or 0)}"
                ),
                "",
            ]
        )

    overview_lines.extend(
        [
            "## Included Views",
            "",
            "- triage packet (JSONL-first row navigation; CSV remains legacy-compatible)",
            "- net-error blame summary (line-role / pass2 / pass3 / routing-fallback buckets)",
            "- config/version parity metadata",
            "- per-label metrics + confusion deltas",
            "- per-recipe breakdown",
            "- stage-separated comparison (baseline / line-role / pass2 / pass3 / final-fallback)",
            "- failure ledger (recipe x pass rows)",
            "- compact regression casebook",
            "- changed-lines stratified sample",
            "- low-confidence changed-lines packet",
            "- call inventory with latency/tokens/cost",
            "- line-role confidence (and candidate-label signal when present)",
            "",
        ]
    )

    cost_signal = (
        call_runtime_inventory.get("summary")
        if isinstance(call_runtime_inventory.get("summary"), dict)
        else {}
    )
    cost_signal = cost_signal.get("cost_signal") if isinstance(cost_signal, dict) else {}
    cost_signal = cost_signal if isinstance(cost_signal, dict) else {}
    estimated_cost_signal = (
        call_runtime_inventory.get("summary")
        if isinstance(call_runtime_inventory.get("summary"), dict)
        else {}
    )
    estimated_cost_signal = (
        estimated_cost_signal.get("estimated_cost_signal")
        if isinstance(estimated_cost_signal, dict)
        else {}
    )
    estimated_cost_signal = (
        estimated_cost_signal if isinstance(estimated_cost_signal, dict) else {}
    )
    candidate_signal = (
        line_role_signal_summary.get("candidate_label_signal")
        if isinstance(line_role_signal_summary, dict)
        else {}
    )
    candidate_signal = candidate_signal if isinstance(candidate_signal, dict) else {}
    overview_lines.extend(
        [
            "## Availability Notes",
            "",
            (
                "- call_cost_available: "
                f"{'true' if bool(cost_signal.get('available')) else 'false'}"
            ),
            (
                "- call_cost_coverage_ratio: "
                f"{_serialize_float(_coerce_float(cost_signal.get('coverage_ratio')))}"
            ),
            (
                "- call_cost_estimated_available: "
                f"{'true' if bool(estimated_cost_signal.get('available')) else 'false'}"
            ),
            (
                "- call_cost_estimated_coverage_ratio: "
                f"{_serialize_float(_coerce_float(estimated_cost_signal.get('coverage_ratio')))}"
            ),
            (
                "- line_role_candidate_labels_available: "
                f"{'true' if bool(candidate_signal.get('available')) else 'false'}"
            ),
            (
                "- triage_packet_rows: "
                f"{int(triage_packet_summary.get('row_count') or 0)}"
            ),
            (
                "- low_confidence_changed_lines_rows: "
                f"{int(low_confidence_changed_lines_summary.get('row_count') or 0)}"
            ),
            (
                "- critical_row_locator_coverage_ratio: "
                f"{_serialize_float(_coerce_float(self_check.get('critical_row_locators_coverage_ratio')))}"
            ),
            "",
        ]
    )

    blame_bucket_rows = net_error_blame_summary.get("bucket_rows")
    blame_bucket_rows = blame_bucket_rows if isinstance(blame_bucket_rows, list) else []
    if blame_bucket_rows:
        overview_lines.extend(
            [
                "## Net-Error Blame Summary",
                "",
                f"- new_error_lines: {int(_coerce_int(net_error_blame_summary.get('new_error_lines')) or 0)}",
                f"- fixed_error_lines: {int(_coerce_int(net_error_blame_summary.get('fixed_error_lines')) or 0)}",
                (
                    "- net_error_delta_lines: "
                    f"{int(_coerce_int(net_error_blame_summary.get('net_error_delta_lines')) or 0)}"
                ),
            ]
        )
        for row in blame_bucket_rows:
            if not isinstance(row, dict):
                continue
            overview_lines.append(
                "- "
                f"{str(row.get('bucket') or '')}: "
                f"new={int(_coerce_int(row.get('new_error_count')) or _coerce_int(row.get('count')) or 0)} "
                f"fixed={int(_coerce_int(row.get('fixed_error_count')) or 0)} "
                f"net={int(_coerce_int(row.get('net_error_count')) or 0)} "
                f"(share_of_net_error={_serialize_float(_coerce_float(row.get('share_of_net_error')))})"
            )
        overview_lines.append("")

    pair_comparability = config_version_metadata.get("pair_comparability")
    pair_comparability = pair_comparability if isinstance(pair_comparability, dict) else {}
    non_comparable_key_counts = pair_comparability.get("non_comparable_key_counts")
    non_comparable_key_counts = (
        non_comparable_key_counts if isinstance(non_comparable_key_counts, dict) else {}
    )
    overview_lines.extend(
        [
            "## Config / Version Parity",
            "",
            (
                "- config_compatible_pair_count: "
                f"{int(_coerce_int(pair_comparability.get('config_compatible_pair_count')) or 0)}"
            ),
            f"- pair_count: {int(_coerce_int(pair_comparability.get('pair_count')) or 0)}",
            (
                "- config_compatible_pair_ratio: "
                f"{_serialize_float(_coerce_float(pair_comparability.get('config_compatible_pair_ratio')))}"
            ),
            (
                "- non_comparable_keys: "
                + (
                    ", ".join(
                        f"{str(key)}={int(_coerce_int(value) or 0)}"
                        for key, value in sorted(non_comparable_key_counts.items())
                    )
                    if non_comparable_key_counts
                    else "none"
                )
            ),
            "",
        ]
    )

    if largest_regressions:
        overview_lines.append("### Largest Practical-F1 Regressions")
        overview_lines.append("")
        for row in largest_regressions:
            overview_lines.append(
                "- "
                f"{row['source_key']} | codex={row['codex_run_id']} vs baseline={row['baseline_run_id']} "
                f"| delta_practical_f1={_serialize_float(_coerce_float(row['delta_practical_f1']))} "
                f"| delta_overall_line_accuracy={_serialize_float(_coerce_float(row['delta_overall_line_accuracy']))} "
                f"| changed_line_count={int(row['changed_line_count'])}"
            )
        overview_lines.append("")

    requested_target_ids = regression_casebook.get("requested_targets")
    requested_target_ids = (
        requested_target_ids if isinstance(requested_target_ids, list) else []
    )
    if requested_target_ids:
        overview_lines.append("### Targeted Regression IDs")
        overview_lines.append("")
        overview_lines.append(
            "- requested: "
            + ", ".join(f"`{str(item)}`" for item in requested_target_ids)
        )
        found_targets = regression_casebook.get("found_targets")
        found_targets = found_targets if isinstance(found_targets, list) else []
        overview_lines.append(
            "- found: "
            + (
                ", ".join(f"`{str(item)}`" for item in found_targets)
                if found_targets
                else "none"
            )
        )
        overview_lines.append("")

    if run_diagnostics:
        overview_lines.extend(
            [
                "## Run Diagnostics",
                "",
                "| run_id | prompt_log | prompt_warning | projection_trace | wrong_context | preprocess_trace |",
                "|---|---|---|---|---|---|",
            ]
        )
        for row in run_diagnostics:
            overview_lines.append(
                "| "
                f"{row['run_id']} | "
                f"{row['full_prompt_log_status']} | "
                f"{row['prompt_warning_aggregate_status']} | "
                f"{row['projection_trace_status']} | "
                f"{row['wrong_label_full_context_status']} | "
                f"{row['preprocess_trace_failures_status']} |"
            )
        overview_lines.append("")

    overview_lines.extend(
        [
            "## Data Integrity",
            "",
            (
                "Each artifact row carries `sha256` and `bytes`. Text/structured files are embedded "
                "directly for easy browsing, while compressed/binary payloads are embedded as base64."
            ),
            (
                "Heavy artifacts (full prompt logs, raw manifests, transport traces, split-cache blobs) "
                "are retained in payload but deprioritized in default navigation."
            ),
            "",
        ]
    )
    (output_root / UPLOAD_BUNDLE_OVERVIEW_FILE_NAME).write_text(
        "\n".join(overview_lines),
        encoding="utf-8",
    )

    return {
        "file_names": list(UPLOAD_BUNDLE_FILE_NAMES),
        "artifact_count": len(artifact_index),
        "payload_rows": len(artifact_index),
        "topline": topline,
        "self_check": self_check,
    }


def _prune_output_to_upload_bundle_files(*, output_dir: Path) -> None:
    keep = set(UPLOAD_BUNDLE_FILE_NAMES)
    for path in output_dir.iterdir():
        if path.name in keep and path.is_file():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def build_upload_bundle_for_existing_output(
    *,
    source_dir: Path,
    output_dir: Path | None = None,
    overwrite: bool = True,
    prune_output_dir: bool = False,
    high_level_only: bool = False,
    target_bundle_size_bytes: int | None = None,
) -> dict[str, Any]:
    """Build a 3-file external-AI upload bundle from an existing artifact tree.

    When `output_dir` is omitted, files are written alongside the source tree.
    When `prune_output_dir` is true and output equals source, only the 3 upload
    files are retained in that folder. Set `high_level_only=True` to emit a
    size-budgeted group bundle (target bytes controlled by
    `target_bundle_size_bytes`).
    """

    source_root = source_dir.resolve()
    if not source_root.is_dir():
        raise ValueError(f"source directory does not exist: {source_root}")

    output_root = output_dir.resolve() if output_dir is not None else source_root
    if output_root.exists():
        if not overwrite:
            raise FileExistsError(f"output directory already exists: {output_root}")
        if output_root != source_root:
            shutil.rmtree(output_root)
            output_root.mkdir(parents=True, exist_ok=True)
    else:
        output_root.mkdir(parents=True, exist_ok=True)

    bundle_metadata = _write_upload_bundle_three_files(
        output_dir=output_root,
        source_dir=source_root,
        high_level_only=high_level_only,
        target_bundle_size_bytes=target_bundle_size_bytes,
    )
    if prune_output_dir and output_root == source_root:
        _prune_output_to_upload_bundle_files(output_dir=output_root)

    bundle_metadata["source_dir"] = str(source_root)
    bundle_metadata["output_dir"] = str(output_root)
    bundle_metadata["high_level_only"] = bool(high_level_only)
    bundle_metadata["target_bundle_size_bytes"] = (
        int(target_bundle_size_bytes)
        if target_bundle_size_bytes is not None
        else None
    )
    return bundle_metadata


def write_flattened_summary_for_existing_runs(*, output_dir: Path) -> Path:
    """Write a flattened benchmark summary for in-place single-offline sessions."""

    output_root = output_dir.resolve()
    comparison_json_path = output_root / "codex_vs_vanilla_comparison.json"
    starter_pack_dir = output_root / STARTER_PACK_DIR_NAME
    starter_readme_path = starter_pack_dir / STARTER_PACK_README_FILE_NAME
    starter_manifest_path = starter_pack_dir / STARTER_PACK_MANIFEST_FILE_NAME
    starter_comparison_path = starter_pack_dir / STARTER_PACK_COMPARISON_MIRROR_FILE_NAME
    starter_breakdown_path = starter_pack_dir / STARTER_PACK_BREAKDOWN_MIRROR_FILE_NAME
    single_offline_summary_path = output_root / "single_offline_summary.md"

    sections: list[str] = [
        "# Benchmark Need-To-Know Package (Flattened)",
        "",
        f"- Generated at: `{_timestamp_now()}`",
        f"- Session root: `{output_root}`",
        "",
    ]

    if single_offline_summary_path.is_file():
        sections.append("## single_offline_summary.md")
        sections.append(single_offline_summary_path.read_text(encoding="utf-8").rstrip())
        sections.append("")

    if comparison_json_path.is_file():
        sections.append("## codex_vs_vanilla_comparison.json")
        sections.append("```json")
        sections.append(
            json.dumps(_load_json(comparison_json_path), indent=2, sort_keys=True)
        )
        sections.append("```")
        sections.append("")

    if starter_readme_path.is_file():
        sections.append(f"## {STARTER_PACK_DIR_NAME}/{STARTER_PACK_README_FILE_NAME}")
        sections.append(starter_readme_path.read_text(encoding="utf-8").rstrip())
        sections.append("")

    if starter_manifest_path.is_file():
        sections.append(f"## {STARTER_PACK_DIR_NAME}/{STARTER_PACK_MANIFEST_FILE_NAME}")
        sections.append("```json")
        sections.append(
            json.dumps(_load_json(starter_manifest_path), indent=2, sort_keys=True)
        )
        sections.append("```")
        sections.append("")

    if starter_comparison_path.is_file():
        sections.append(
            f"## {STARTER_PACK_DIR_NAME}/{STARTER_PACK_COMPARISON_MIRROR_FILE_NAME}"
        )
        sections.append("```json")
        sections.append(
            json.dumps(_load_json(starter_comparison_path), indent=2, sort_keys=True)
        )
        sections.append("```")
        sections.append("")

    if starter_breakdown_path.is_file():
        sections.append(
            f"## {STARTER_PACK_DIR_NAME}/{STARTER_PACK_BREAKDOWN_MIRROR_FILE_NAME}"
        )
        sections.append("```json")
        sections.append(
            json.dumps(_load_json(starter_breakdown_path), indent=2, sort_keys=True)
        )
        sections.append("```")
        sections.append("")

    output_path = output_root / AGGREGATED_ROOT_SUMMARY_MD
    output_path.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")
    return output_path


def build_starter_pack_for_existing_runs(
    *,
    input_dir: Path,
    output_dir: Path | None = None,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    excerpt_limit: int = DEFAULT_EXCERPT_LIMIT,
    top_confusions_limit: int = DEFAULT_TOP_CONFUSIONS,
    write_flattened_summary: bool = False,
) -> dict[str, Any]:
    """Build starter-pack artifacts from existing benchmark run dirs.

    This helper is used by interactive single-offline benchmark flows to emit
    `starter_pack_v1/` directly into the session folder without building a full
    cutdown package.
    """

    input_root = input_dir.resolve()
    if not input_root.is_dir():
        raise ValueError(f"input directory does not exist: {input_root}")
    if sample_limit <= 0:
        raise ValueError("sample_limit must be > 0")
    if excerpt_limit <= 0:
        raise ValueError("excerpt_limit must be > 0")

    run_dirs = _discover_run_dirs(input_root)
    if not run_dirs:
        raise ValueError(
            "no benchmark run directories found (need both eval_report.json and run_manifest.json)"
        )

    output_root = output_dir.resolve() if output_dir is not None else input_root
    output_root.mkdir(parents=True, exist_ok=True)

    records = [
        _build_run_record_from_existing_run(
            run_dir=run_dir,
            top_confusions_limit=top_confusions_limit,
        )
        for run_dir in run_dirs
    ]

    (
        comparison_summary,
        changed_line_rows,
        pair_breakdown_rows,
        _targeted_prompt_case_rows,
        recipe_triage_rows,
        call_inventory_rows,
        outside_span_trace_rows,
    ) = _build_comparison_summary(
        records=records,
        excerpt_limit=excerpt_limit,
        targeted_prompt_case_limit=DEFAULT_TARGETED_PROMPT_CASES,
    )
    changed_line_rows.sort(
        key=lambda row: (
            str(row.get("source_key") or ""),
            str(row.get("codex_run_id") or ""),
            int(row.get("line_index") or 0),
        )
    )

    per_recipe_breakdown_payload = {
        "generated_at": _timestamp_now(),
        "pair_count": len(pair_breakdown_rows),
        "pairs": pair_breakdown_rows,
    }

    comparison_summary["generated_at"] = _timestamp_now()
    comparison_summary["input_dir"] = str(input_root)
    comparison_summary["output_dir"] = str(output_root)
    comparison_summary["changed_lines_total"] = len(changed_line_rows)
    comparison_summary["changed_lines_file"] = CHANGED_LINES_FILE_NAME
    comparison_summary["per_recipe_or_per_span_breakdown_file"] = PER_RECIPE_BREAKDOWN_FILE_NAME
    comparison_summary["targeted_prompt_cases_file"] = TARGETED_PROMPT_CASES_FILE_NAME
    comparison_summary["label_policy_notes_file"] = LABEL_POLICY_NOTES_FILE_NAME
    comparison_summary["starter_pack_v1_dir"] = STARTER_PACK_DIR_NAME
    comparison_summary["starter_pack_v1_manifest_file"] = (
        f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_MANIFEST_FILE_NAME}"
    )

    starter_pack_metadata = _write_starter_pack_v1(
        output_dir=output_root,
        comparison_summary=comparison_summary,
        changed_line_rows=changed_line_rows,
        pair_breakdown_rows=pair_breakdown_rows,
        per_recipe_breakdown_payload=per_recipe_breakdown_payload,
        recipe_triage_rows=recipe_triage_rows,
        call_inventory_rows=call_inventory_rows,
        outside_span_trace_rows=outside_span_trace_rows,
        sample_limit=sample_limit,
    )

    flattened_summary_path: Path | None = None
    if write_flattened_summary:
        flattened_summary_path = write_flattened_summary_for_existing_runs(
            output_dir=output_root
        )

    relative_flattened_summary = (
        str(flattened_summary_path.relative_to(output_root))
        if isinstance(flattened_summary_path, Path)
        else None
    )

    return {
        "generated_at": _timestamp_now(),
        "input_dir": str(input_root),
        "output_dir": str(output_root),
        "run_count": len(records),
        "pair_count": len(comparison_summary.get("pairs") or []),
        "starter_pack": starter_pack_metadata,
        "flattened_summary_path": relative_flattened_summary,
    }


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
    if args.upload_3_files_only and not args.upload_3_files:
        print(
            "error: --upload-3-files-only requires --upload-3-files",
            file=sys.stderr,
        )
        return 1
    if args.upload_3_files and not args.no_flatten:
        print(
            "error: --upload-3-files requires --no-flatten (bundle is built from the "
            "non-flattened package).",
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
        recipe_triage_rows,
        call_inventory_rows,
        outside_span_trace_rows,
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
    comparison_summary["starter_pack_v1_dir"] = STARTER_PACK_DIR_NAME
    comparison_summary["starter_pack_v1_manifest_file"] = (
        f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_MANIFEST_FILE_NAME}"
    )
    comparison_summary["project_context"] = dict(project_context_pointer)

    project_context_digest_lines = _build_project_context_digest(
        records=records,
        comparison_summary=comparison_summary,
        project_context_metadata=project_context_metadata,
        prompt_pairs_per_category=args.prompt_pairs_per_category,
    )
    _write_json(output_dir / "comparison_summary.json", comparison_summary)
    starter_pack_metadata = _write_starter_pack_v1(
        output_dir=output_dir,
        comparison_summary=comparison_summary,
        changed_line_rows=changed_line_rows,
        pair_breakdown_rows=pair_breakdown_rows,
        per_recipe_breakdown_payload=per_recipe_breakdown_payload,
        recipe_triage_rows=recipe_triage_rows,
        call_inventory_rows=call_inventory_rows,
        outside_span_trace_rows=outside_span_trace_rows,
        sample_limit=args.sample_limit,
    )
    starter_pack_manifest = starter_pack_metadata.get("manifest")
    starter_pack_manifest = starter_pack_manifest if isinstance(starter_pack_manifest, dict) else {}

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
        "upload_3_files_enabled": bool(args.upload_3_files),
        "upload_3_files_only": bool(args.upload_3_files_only),
        "upload_3_files_contract": list(UPLOAD_BUNDLE_FILE_NAMES)
        if args.upload_3_files
        else [],
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
        "starter_pack_v1_path": STARTER_PACK_DIR_NAME,
        "starter_pack_v1_manifest_file": f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_MANIFEST_FILE_NAME}",
        "starter_pack_v1_heavy_artifacts_omitted_by_default": starter_pack_manifest.get(
            "heavy_artifacts_omitted_by_default",
            list(STARTER_PACK_HEAVY_ARTIFACTS_OMITTED_BY_DEFAULT),
        ),
        "starter_pack_v1_legacy_to_starter_mapping": starter_pack_manifest.get(
            "legacy_to_starter_mapping",
            {},
        ),
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
    for relative_path in starter_pack_metadata.get("included_files", []):
        if isinstance(relative_path, str) and relative_path:
            included_files.add(relative_path)
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
    if args.upload_3_files:
        included_files.update(UPLOAD_BUNDLE_FILE_NAMES)
    process_manifest["included_files"] = sorted(included_files)
    _write_json(output_dir / "process_manifest.json", process_manifest)

    upload_bundle_meta: dict[str, Any] | None = None
    if args.upload_3_files:
        upload_bundle_meta = _write_upload_bundle_three_files(output_dir=output_dir)
        if args.upload_3_files_only:
            _prune_output_to_upload_bundle_files(output_dir=output_dir)

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
    if upload_bundle_meta is not None:
        print(
            "Built 3-file upload bundle: "
            f"{', '.join(upload_bundle_meta.get('file_names') or [])}"
        )
        if args.upload_3_files_only:
            print("Pruned output to upload bundle files only.")
    print(f"Runs processed: {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
