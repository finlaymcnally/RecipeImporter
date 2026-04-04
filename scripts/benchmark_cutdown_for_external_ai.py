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

from cookimport.bench.line_role_artifact_lookup import LineRoleArtifactLookup
from cookimport.bench import oracle_upload as oracle_upload_contract
from cookimport.bench.external_ai_cutdown.canonical_lines import (
    _build_canonical_lines,
    _build_correct_label_sample,
    _line_gold_labels,
    _load_gold_spans,
    _overlap_len,
)
from cookimport.bench.external_ai_cutdown.artifact_paths import (
    _iter_prompt_category_manifest_paths as _iter_prompt_category_manifest_paths_impl,
    _resolve_extracted_archive_path as _resolve_extracted_archive_path_impl,
    _resolve_full_prompt_log_path as _resolve_full_prompt_log_path_impl,
    _resolve_knowledge_manifest_path as _resolve_knowledge_manifest_path_impl,
    _resolve_knowledge_prompt_path as _resolve_knowledge_prompt_path_impl,
    _resolve_prediction_run_dir as _resolve_prediction_run_dir_impl,
    _resolve_processed_output_run_dir as _resolve_processed_output_run_dir_impl,
    _resolve_prompt_log_path as _resolve_prompt_log_path_impl,
    _resolve_prompt_type_samples_path as _resolve_prompt_type_samples_path_impl,
)
from cookimport.bench.external_ai_cutdown.discovery import (
    _default_output_dir_from_runs,
    _discover_run_dirs,
    _is_ignored_dir,
    _is_run_dir,
    _parse_run_timestamp,
    _read_run_id_for_dir,
    _timestamp_now,
)
from cookimport.bench.external_ai_cutdown.io import (
    _clip_large_text_fields,
    _clip_strings_deep,
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _excerpt,
    _iter_jsonl,
    _jsonl_row_count,
    _load_json,
    _sample_indices_evenly,
    _sample_rows_evenly,
    _write_json,
    _write_jsonl,
    _write_jsonl_sample,
)
from cookimport.bench.external_ai_cutdown.project_context import (
    _build_project_context_digest as _build_project_context_digest_impl,
    _project_context_metadata as _project_context_metadata_impl,
)
from cookimport.bench.external_ai_cutdown.prompt_logs import (
    _prompt_category_sort_key as _prompt_category_sort_key_impl,
    _write_prompt_log_samples as _write_prompt_log_samples_impl,
    _write_prompt_log_samples_from_full_prompt_log as _write_prompt_log_samples_from_full_prompt_log_impl,
)
from cookimport.bench.eval_stage_blocks import (
    compute_block_metrics,
    load_gold_block_labels,
)
from cookimport.bench.codex_bridge_projection_policy import (
    resolve_trace_status,
    select_prompt_row_for_trace,
)
from cookimport.bench.upload_bundle_v1_existing_output import (
    ExistingOutputAdapterHelpers,
    build_recipe_pipeline_topology,
    build_recipe_pipeline_topology_context,
    build_upload_bundle_source_model_from_existing_root,
)
from cookimport.bench.upload_bundle_v1_model import UploadBundleSourceModel
from cookimport.bench.upload_bundle_v1_render import (
    build_stage_separated_comparison as render_stage_separated_comparison,
    build_stage_separated_comparison_from_model,
    build_recipe_pipeline_context_from_model,
    write_upload_bundle_v1,
)
from cookimport.bench.structure_label_report import build_structure_label_report
from cookimport.runs.stage_observability import stage_artifact_stem, stage_label


DEFAULT_SAMPLE_LIMIT = 80
DEFAULT_TOP_CONFUSIONS = 8
DEFAULT_TOP_LABELS = 6
DEFAULT_EXCERPT_LIMIT = 440
DEFAULT_PROMPT_EXCERPT_LIMIT = 2000
DEFAULT_PROMPT_PAIRS_PER_CATEGORY = 3
DEFAULT_TARGETED_PROMPT_CASES = 10
ALIGNMENT_HEALTHY_COVERAGE_MIN = 0.98
ALIGNMENT_HEALTHY_MATCH_RATIO_MIN = 0.98
GROUP_UPLOAD_BUNDLE_TARGET_BYTES = 30 * 1024 * 1024
GROUP_UPLOAD_BUNDLE_RESERVED_BYTES = 3 * 1024 * 1024
GROUP_UPLOAD_BUNDLE_ROOT_ARTIFACT_BUDGET_SHARE = 0.8
GROUP_UPLOAD_BUNDLE_MIN_ARTIFACT_BUDGET_BYTES = 4 * 1024 * 1024
GROUP_UPLOAD_BUNDLE_GROUP_PACKET_FILE_NAME = "group_high_level_packet.json"
GROUP_UPLOAD_BUNDLE_MIN_WRONG_LINE_SAMPLES_PER_RUN = 1
GROUP_UPLOAD_BUNDLE_MAX_WRONG_LINE_SAMPLES_PER_RUN = 240
GROUP_UPLOAD_BUNDLE_FINAL_RESERVE_SHARE = 0.08
GROUP_UPLOAD_BUNDLE_FINAL_RESERVE_MIN_BYTES = 64 * 1024
UPLOAD_BUNDLE_MIN_PAIRS_FOR_GENERALIZATION = 2
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
PROJECT_CONTEXT_REL_PATH = Path("docs/AI_context.md")

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
    ("prediction-run/prompt_budget_summary.json", False),
)
GROUP_UPLOAD_BUNDLE_RUN_CONTEXT_FILES: tuple[str, ...] = (
    "prompts/prompt_request_response_log.txt",
    "prediction-run/extracted_archive.json",
    "prediction-run/line-role-pipeline/extracted_archive.json",
)
UPLOAD_BUNDLE_OVERVIEW_FILE_NAME = "overview.md"
UPLOAD_BUNDLE_INDEX_FILE_NAME = "index.json"
UPLOAD_BUNDLE_PAYLOAD_FILE_NAME = "payload.json"
UPLOAD_BUNDLE_FILE_NAMES = (
    UPLOAD_BUNDLE_OVERVIEW_FILE_NAME,
    UPLOAD_BUNDLE_INDEX_FILE_NAME,
    UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
)
UPLOAD_BUNDLE_REVIEW_PROFILE_DIR_NAMES = (
    oracle_upload_contract.ORACLE_REVIEW_PROFILE_QUALITY,
    oracle_upload_contract.ORACLE_REVIEW_PROFILE_TOKEN,
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
STARTER_PACK_EXPLICIT_ESCALATION_CHANGED_LINES_FILE_NAME = (
    "15_explicit_escalation_changed_lines.packet.jsonl"
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
UPLOAD_BUNDLE_EXPLICIT_ESCALATION_CHANGED_LINES_SCHEMA_VERSION = (
    "upload_bundle_explicit_escalation_changed_lines.v1"
)
STARTER_PACK_TRIAGE_HEADER = (
    "recipe_id",
    "short_title",
    "line_total",
    "changed_lines_codex_vs_baseline",
    "codex_accuracy",
    "baseline_accuracy",
    "delta_codex_minus_baseline",
    "correction_call_id",
    "correction_input_block_count",
    "correction_warning_count",
    "correction_warning_buckets",
    "correction_ingredient_count",
    "correction_step_count",
    "correction_mapping_count",
    "correction_empty_mapping",
    "build_intermediate_status",
    "correction_status",
    "build_final_status",
    "final_mapping_status",
    "final_mapping_reason",
    "structural_status",
    "structural_reason_codes",
    "recipe_warning_count",
    "recipe_error_count",
    "outside_span_wrong_line_count",
    "outside_span_trace_status_top",
)
AGGREGATED_ROOT_SUMMARY_MD = "benchmark_summary.md"
PROMPT_LOG_FILE_NAME = "codex_exec_prompt_log.dedup.txt"
FULL_PROMPT_LOG_FILE_NAME = "full_prompt_log.jsonl"
PROMPT_TYPE_SAMPLES_FILE_NAME = "prompt_type_samples_from_full_prompt_log.md"
KNOWLEDGE_PROMPT_FILE_NAME = "prompt_nonrecipe_finalize.txt"
KNOWLEDGE_MANIFEST_FILE_NAME = "knowledge_manifest.json"
PROMPT_WARNING_AGGREGATE_FILE_NAME = "prompt_warning_aggregate.json"
PROJECTION_TRACE_FILE_NAME = "projection_trace.codex_to_benchmark.json"
CHANGED_LINES_FILE_NAME = "changed_lines.codex_vs_vanilla.jsonl"
PER_RECIPE_BREAKDOWN_FILE_NAME = "per_recipe_or_per_span_breakdown.json"
TARGETED_PROMPT_CASES_FILE_NAME = "targeted_prompt_cases.md"
LABEL_POLICY_NOTES_FILE_NAME = "label_policy_adjudication_notes.md"
WRONG_LABEL_FULL_CONTEXT_FILE_NAME = "wrong_label_lines.with_context.full.jsonl.gz"
PREPROCESS_TRACE_FAILURES_FILE_NAME = "preprocess_trace_failures.jsonl.gz"
PROMPT_REQUEST_RESPONSE_LOG_NAME = "prompt_request_response_log.txt"
PROMPT_LOG_MANIFEST_ARTIFACT_KEY = "prompt_request_response_txt"
FULL_PROMPT_LOG_MANIFEST_ARTIFACT_KEYS = (
    "full_prompt_log_path",
    "full_prompt_log_jsonl",
)
PROMPT_TYPE_SAMPLES_MANIFEST_ARTIFACT_KEYS = (
    "prompt_type_samples_from_full_prompt_log_md",
)
LLM_STAGE_MAP = {
    "recipe_build_intermediate": {
        "artifact_stem": stage_artifact_stem("recipe_build_intermediate"),
        "pipeline_id": None,
        "sort_order": 0,
    },
    "recipe_refine": {
        "artifact_stem": stage_artifact_stem("recipe_refine"),
        "pipeline_id": "recipe.correction.compact.v1",
        "sort_order": 1,
    },
    "recipe_build_final": {
        "artifact_stem": stage_artifact_stem("recipe_build_final"),
        "pipeline_id": None,
        "sort_order": 2,
    },
    "nonrecipe_finalize": {
        "artifact_stem": stage_artifact_stem("nonrecipe_finalize"),
        "pipeline_id": "recipe.knowledge.compact.v1",
        "sort_order": 4,
    },
    "tags": {
        "artifact_stem": stage_artifact_stem("tags"),
        "pipeline_id": "recipe.tags.v1",
        "sort_order": 5,
    },
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


def _upload_bundle_recipe_stages_for_row(
    *,
    recipe_pipeline_id: Any,
    correction_call_id: Any,
) -> list[dict[str, str]]:
    correction_seen = 1 if str(correction_call_id or "").strip() else 0
    topology = build_recipe_pipeline_topology_context(
        codex_recipe_pipelines=[str(recipe_pipeline_id or "").strip()],
        observed_execution_modes=[],
        observed_routing_reasons=[],
        observed_correction_call_count=correction_seen,
        observed_final_recipe_build_count=correction_seen,
    )
    recipe_stages = topology.get("recipe_stages")
    return list(recipe_stages) if isinstance(recipe_stages, list) else []


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


def _write_prompt_log_samples(
    *,
    source_path: Path,
    output_path: Path,
    max_pairs_per_category: int,
) -> dict[str, Any]:
    return _write_prompt_log_samples_impl(
        source_path=source_path,
        output_path=output_path,
        max_pairs_per_category=max_pairs_per_category,
        llm_stage_map=LLM_STAGE_MAP,
    )


def _prompt_category_sort_key(category: str) -> tuple[int, str, int, str]:
    return _prompt_category_sort_key_impl(
        category,
        llm_stage_map=LLM_STAGE_MAP,
    )


def _write_prompt_log_samples_from_full_prompt_log(
    *,
    source_path: Path,
    output_path: Path,
    max_pairs_per_category: int,
    excerpt_limit: int,
) -> dict[str, Any]:
    return _write_prompt_log_samples_from_full_prompt_log_impl(
        source_path=source_path,
        output_path=output_path,
        max_pairs_per_category=max_pairs_per_category,
        excerpt_limit=excerpt_limit,
        llm_stage_map=LLM_STAGE_MAP,
        prompt_row_stage_key=_prompt_row_stage_key,
        clip_strings_deep=_clip_strings_deep,
    )


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
    stage_key = _prompt_row_stage_key(row)
    pass_rank = int(LLM_STAGE_MAP.get(stage_key, {}).get("sort_order") or 99)

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
        for recipe_id in _prompt_row_owned_recipe_ids(row):
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

    if not full_prompt_rows:
        return [], "missing_full_prompt_log"

    pred_run_dir = _resolve_prediction_run_dir(run_dir, run_manifest)
    extracted_archive_path = _resolve_extracted_archive_path(
        run_dir,
        run_manifest,
        pred_run_dir=pred_run_dir,
    )
    if extracted_archive_path is None:
        return [], "missing_prediction_run" if pred_run_dir is None else "missing_extracted_archive"

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
        prompt_stage_key = _prompt_row_stage_key(prompt_row) if isinstance(prompt_row, dict) else None
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
                "stage_key": prompt_stage_key,
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


def _upload_bundle_recipe_correction_output_rows(value: Any) -> list[dict[str, Any]]:
    parsed = _parse_json_like(value)
    if not isinstance(parsed, dict):
        return []

    candidates: list[dict[str, Any]] = []
    payload = parsed.get("payload")
    if isinstance(payload, dict):
        candidates.append(payload)
    candidates.append(parsed)

    for candidate in candidates:
        recipe_rows = candidate.get("r")
        if not isinstance(recipe_rows, list):
            continue
        normalized_rows: list[dict[str, Any]] = []
        for recipe_row in recipe_rows:
            if not isinstance(recipe_row, dict):
                continue
            compact_recipe = recipe_row.get("cr")
            compact_recipe = compact_recipe if isinstance(compact_recipe, dict) else {}
            normalized_rows.append(
                {
                    "recipe_id": str(recipe_row.get("rid") or "").strip(),
                    "repair_status": str(recipe_row.get("st") or "").strip(),
                    "status_reason": str(recipe_row.get("sr") or "").strip(),
                    "warnings": _coerce_str_list(recipe_row.get("w")),
                    "has_mapping_field": "m" in recipe_row,
                    "canonical_recipe": {
                        "title": str(compact_recipe.get("t") or "").strip(),
                        "ingredients": _coerce_str_list(compact_recipe.get("i")),
                        "steps": _coerce_str_list(compact_recipe.get("s")),
                        "description": str(compact_recipe.get("d") or "").strip(),
                        "recipe_yield": str(compact_recipe.get("y") or "").strip(),
                    },
                    "ingredient_step_mapping": recipe_row.get("m"),
                    "ingredient_step_mapping_reason": str(recipe_row.get("mr") or "").strip(),
                }
            )
        if normalized_rows:
            return normalized_rows

    if any(
        key in parsed
        for key in (
            "canonical_recipe",
            "ingredient_step_mapping",
            "ingredient_step_mapping_reason",
            "warnings",
        )
    ):
        canonical_recipe = (
            parsed.get("canonical_recipe") if isinstance(parsed.get("canonical_recipe"), dict) else {}
        )
        return [
            {
                "recipe_id": str(parsed.get("recipe_id") or "").strip(),
                "repair_status": str(parsed.get("repair_status") or "").strip(),
                "status_reason": str(parsed.get("status_reason") or "").strip(),
                "warnings": _coerce_str_list(parsed.get("warnings")),
                "has_mapping_field": "ingredient_step_mapping" in parsed,
                "canonical_recipe": {
                    "title": str(canonical_recipe.get("title") or "").strip(),
                    "ingredients": _coerce_str_list(canonical_recipe.get("ingredients")),
                    "steps": _coerce_str_list(canonical_recipe.get("steps")),
                    "description": str(canonical_recipe.get("description") or "").strip(),
                    "recipe_yield": str(canonical_recipe.get("recipe_yield") or "").strip(),
                },
                "ingredient_step_mapping": parsed.get("ingredient_step_mapping"),
                "ingredient_step_mapping_reason": str(
                    parsed.get("ingredient_step_mapping_reason") or ""
                ).strip(),
            }
        ]
    return []


def _upload_bundle_recipe_correction_output_for_recipe(
    value: Any,
    *,
    recipe_id: str,
) -> dict[str, Any]:
    normalized_recipe_id = str(recipe_id or "").strip()
    rows = _upload_bundle_recipe_correction_output_rows(value)
    if normalized_recipe_id:
        for row in rows:
            if str(row.get("recipe_id") or "").strip() == normalized_recipe_id:
                return row
    return rows[0] if len(rows) == 1 else {}


def _upload_bundle_recipe_correction_input_block_count(
    value: Any,
    *,
    recipe_id: str | None = None,
) -> int:
    parsed = _parse_json_like(value)
    if not isinstance(parsed, dict):
        return 0
    normalized_recipe_id = str(recipe_id or "").strip()
    if normalized_recipe_id:
        shard_recipe_rows = parsed.get("r")
        if isinstance(shard_recipe_rows, list):
            for recipe_row in shard_recipe_rows:
                if not isinstance(recipe_row, dict):
                    continue
                if str(recipe_row.get("rid") or "").strip() != normalized_recipe_id:
                    continue
                evidence_rows = recipe_row.get("ev")
                return len(evidence_rows) if isinstance(evidence_rows, list) else 0
    evidence_rows = parsed.get("evidence_rows")
    if isinstance(evidence_rows, list):
        return len(evidence_rows)
    shard_recipe_rows = parsed.get("r")
    if isinstance(shard_recipe_rows, list):
        return sum(
            len(recipe_row.get("ev") or [])
            for recipe_row in shard_recipe_rows
            if isinstance(recipe_row, dict) and isinstance(recipe_row.get("ev"), list)
        )
    return 0


def _upload_bundle_recipe_correction_metrics(output_row: dict[str, Any]) -> dict[str, Any]:
    canonical_recipe = (
        output_row.get("canonical_recipe")
        if isinstance(output_row.get("canonical_recipe"), dict)
        else {}
    )
    ingredients = _coerce_str_list(canonical_recipe.get("ingredients"))
    steps = _coerce_str_list(canonical_recipe.get("steps"))
    warnings = _coerce_str_list(output_row.get("warnings"))
    mapping_value = output_row.get("ingredient_step_mapping")
    mapping_count = _mapping_count(mapping_value)
    has_signal = bool(
        str(canonical_recipe.get("title") or "").strip()
        or str(canonical_recipe.get("description") or "").strip()
        or str(canonical_recipe.get("recipe_yield") or "").strip()
        or ingredients
        or steps
        or mapping_count > 0
        or warnings
        or str(output_row.get("repair_status") or "").strip()
        or str(output_row.get("status_reason") or "").strip()
    )
    return {
        "ingredient_count": len(ingredients),
        "step_count": len(steps),
        "mapping_count": mapping_count,
        "warnings": warnings,
        "empty_mapping": bool(output_row.get("has_mapping_field"))
        and _is_empty_mapping_value(mapping_value),
        "empty_output": not has_signal,
    }


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
    by_stage_calls: Counter[str] = Counter()
    by_stage_calls_with_warnings: Counter[str] = Counter()
    warning_message_counts: Counter[str] = Counter()
    warning_bucket_counts: Counter[str] = Counter()
    correction_empty_mapping_calls = 0
    correction_empty_mapping_recipe_ids: Counter[str] = Counter()

    calls_with_warnings = 0
    warning_total = 0

    for row in rows:
        stage_key = _prompt_row_stage_key(row) or "unknown"
        by_stage_calls[stage_key] += 1

        parsed_response = _parse_json_like(row.get("parsed_response"))
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
        warnings = _coerce_str_list(parsed_response.get("warnings"))
        correction_outputs = (
            _upload_bundle_recipe_correction_output_rows(parsed_response)
            if stage_key == "recipe_refine"
            else []
        )
        if correction_outputs:
            warnings = []
            for output_row in correction_outputs:
                warnings.extend(_upload_bundle_recipe_correction_metrics(output_row)["warnings"])
        if warnings:
            calls_with_warnings += 1
            by_stage_calls_with_warnings[stage_key] += 1
        for warning in warnings:
            normalized = _normalize_whitespace(warning)
            warning_message_counts[normalized] += 1
            warning_bucket_counts[_prompt_warning_bucket(normalized)] += 1
            warning_total += 1

        if correction_outputs:
            empty_mapping_recipe_ids: list[str] = []
            for output_row in correction_outputs:
                metrics = _upload_bundle_recipe_correction_metrics(output_row)
                if not metrics["empty_mapping"]:
                    continue
                recipe_id = str(output_row.get("recipe_id") or row.get("recipe_id") or "").strip()
                if recipe_id:
                    empty_mapping_recipe_ids.append(recipe_id)
            if empty_mapping_recipe_ids:
                correction_empty_mapping_calls += 1
                for recipe_id in empty_mapping_recipe_ids:
                    correction_empty_mapping_recipe_ids[recipe_id] += 1
        elif "ingredient_step_mapping" in parsed_response and _is_empty_mapping_value(
            parsed_response.get("ingredient_step_mapping")
        ):
            correction_empty_mapping_calls += 1
            recipe_id = str(row.get("recipe_id") or "").strip()
            if recipe_id:
                correction_empty_mapping_recipe_ids[recipe_id] += 1

    return {
        "source_full_prompt_log": str(full_prompt_log_path),
        "total_calls": len(rows),
        "calls_with_warnings": calls_with_warnings,
        "warnings_total": warning_total,
        "calls_by_stage": dict(sorted(by_stage_calls.items())),
        "calls_with_warnings_by_stage": dict(sorted(by_stage_calls_with_warnings.items())),
        "warning_buckets": dict(
            sorted(warning_bucket_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "top_warning_messages": [
            {"warning": message, "count": count}
            for message, count in warning_message_counts.most_common(20)
        ],
        "correction_empty_ingredient_step_mapping_calls": correction_empty_mapping_calls,
        "correction_empty_ingredient_step_mapping_recipe_ids": [
            {"recipe_id": recipe_id, "count": count}
            for recipe_id, count in correction_empty_mapping_recipe_ids.most_common()
        ],
    }


def _build_recipe_spans_from_full_prompt_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for row in rows:
        stage_key = _prompt_row_stage_key(row)
        if stage_key not in {"recipe_refine", "recipe_build_intermediate"}:
            continue
        request_input_payload = _parse_json_like(row.get("request_input_payload"))
        if not isinstance(request_input_payload, dict):
            continue
        parsed_response = _parse_json_like(row.get("parsed_response"))
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}

        shard_recipe_rows = request_input_payload.get("r")
        if isinstance(shard_recipe_rows, list) and shard_recipe_rows:
            for recipe_row in shard_recipe_rows:
                if not isinstance(recipe_row, dict):
                    continue
                recipe_id = str(recipe_row.get("rid") or "").strip()
                if not recipe_id:
                    continue
                evidence_rows = recipe_row.get("ev")
                evidence_rows = (
                    evidence_rows if isinstance(evidence_rows, list) else []
                )
                indices = [
                    int(index)
                    for index in (
                        _coerce_int(item[0])
                        for item in evidence_rows
                        if isinstance(item, (list, tuple)) and len(item) >= 2
                    )
                    if index is not None
                ]
                if not indices:
                    continue
                start = min(indices)
                end = max(indices)
                if start is None or end is None or end < start:
                    continue
                hints = recipe_row.get("h") if isinstance(recipe_row.get("h"), dict) else {}
                title = (
                    str(hints.get("n") or "").strip()
                    or str(recipe_row.get("txt") or "").strip()
                    or None
                )
                dedupe_key = (recipe_id, start, end)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                spans.append(
                    {
                        "recipe_id": recipe_id,
                        "start_block_index": start,
                        "end_block_index": end,
                        "title": title,
                        "call_id": row.get("call_id"),
                    }
                )
            continue

        evidence_rows = request_input_payload.get("evidence_rows")
        indices: list[int] = []
        if isinstance(evidence_rows, list) and evidence_rows:
            indices = [
                int(index)
                for index in (
                    _coerce_int(item[0])
                    for item in evidence_rows
                    if isinstance(item, (list, tuple)) and len(item) >= 2
                )
                if index is not None
            ]
        if not indices:
            start = _coerce_int(parsed_response.get("start_block_index"))
            end = _coerce_int(parsed_response.get("end_block_index"))
            if start is not None and end is not None and end >= start:
                indices = list(range(int(start), int(end) + 1))
        if not indices:
            continue
        start = min(indices)
        end = max(indices)
        if start is None or end is None or end < start:
            continue
        recipe_id = str(
            row.get("recipe_id") or request_input_payload.get("recipe_id") or ""
        ).strip()
        if not recipe_id:
            continue
        canonical_recipe = (
            parsed_response.get("canonical_recipe")
            if isinstance(parsed_response.get("canonical_recipe"), dict)
            else {}
        )
        dedupe_key = (recipe_id, start, end)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        spans.append(
            {
                "recipe_id": recipe_id,
                "start_block_index": start,
                "end_block_index": end,
                "title": canonical_recipe.get("title")
                or parsed_response.get("title")
                or ((request_input_payload.get("recipe_candidate_hint") or {}).get("name") if isinstance(request_input_payload.get("recipe_candidate_hint"), dict) else None),
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


def _normalize_recipe_spans_to_line_coordinates(
    *,
    run_dir: Path,
    recipe_spans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not recipe_spans:
        return []

    normalized = [dict(span) for span in recipe_spans if isinstance(span, dict)]
    needs_projection = False
    for span in normalized:
        start_line_index = _coerce_int(span.get("start_line_index"))
        end_line_index = _coerce_int(span.get("end_line_index"))
        if start_line_index is not None and end_line_index is not None:
            continue
        if "line_indices" in span:
            continue
        needs_projection = True

    if not needs_projection:
        return normalized

    projected_rows = _iter_jsonl(run_dir / "line-role-pipeline" / "projected_spans.jsonl")
    if not projected_rows:
        return normalized

    line_indices_by_block_index: dict[int, set[int]] = defaultdict(set)
    for row in projected_rows:
        block_index = _coerce_int(row.get("block_index"))
        line_index = _coerce_int(row.get("line_index"))
        if block_index is None or line_index is None:
            continue
        line_indices_by_block_index[int(block_index)].add(int(line_index))

    if not line_indices_by_block_index:
        return normalized

    for span in normalized:
        if "line_indices" in span:
            continue
        start_block_index = _coerce_int(span.get("start_block_index"))
        end_block_index = _coerce_int(span.get("end_block_index"))
        if start_block_index is None or end_block_index is None or end_block_index < start_block_index:
            continue
        projected_line_indices = sorted(
            line_index
            for block_index, line_indices in line_indices_by_block_index.items()
            if start_block_index <= block_index <= end_block_index
            for line_index in line_indices
        )
        span["line_indices"] = projected_line_indices
        if projected_line_indices:
            span["start_line_index"] = projected_line_indices[0]
            span["end_line_index"] = projected_line_indices[-1]
    return normalized


def _span_line_indices(span: dict[str, Any]) -> list[int] | None:
    if "line_indices" not in span:
        return None
    raw_values = span.get("line_indices")
    if not isinstance(raw_values, list):
        return []
    seen: set[int] = set()
    line_indices: list[int] = []
    for value in raw_values:
        parsed = _coerce_int(value)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        line_indices.append(int(parsed))
    line_indices.sort()
    return line_indices


def _span_line_bounds(span: dict[str, Any]) -> tuple[int | None, int | None]:
    line_indices = _span_line_indices(span)
    if line_indices is not None:
        if not line_indices:
            return None, None
        return line_indices[0], line_indices[-1]

    start_line_index = _coerce_int(span.get("start_line_index"))
    end_line_index = _coerce_int(span.get("end_line_index"))
    if start_line_index is not None and end_line_index is not None:
        return int(start_line_index), int(end_line_index)

    start_block_index = _coerce_int(span.get("start_block_index"))
    end_block_index = _coerce_int(span.get("end_block_index"))
    if start_block_index is None or end_block_index is None:
        return None, None
    return int(start_block_index), int(end_block_index)


def _span_contains_line(*, span: dict[str, Any], line_index: int) -> bool:
    line_indices = _span_line_indices(span)
    if line_indices is not None:
        return line_index in line_indices
    start, end = _span_line_bounds(span)
    if start is None or end is None:
        return False
    return start <= line_index <= end


def _resolve_recipe_for_line(
    *,
    line_index: int,
    recipe_spans: list[dict[str, Any]],
) -> tuple[str | None, str]:
    matches: list[dict[str, Any]] = []
    for span in recipe_spans:
        if _span_contains_line(span=span, line_index=line_index):
            matches.append(span)
    if not matches:
        return None, "outside_active_recipe_span"
    best = sorted(
        matches,
        key=lambda span: (
            int((_span_line_bounds(span)[1] or 0) - (_span_line_bounds(span)[0] or 0)),
            int(_span_line_bounds(span)[0] or 0),
            str(span["recipe_id"]),
        ),
    )[0]
    return str(best["recipe_id"]), "inside_active_recipe_span"


def _build_line_prediction_view(
    *,
    run_dir: Path,
    recipe_spans: list[dict[str, Any]],
) -> LinePredictionView:
    normalized_recipe_spans = _normalize_recipe_spans_to_line_coordinates(
        run_dir=run_dir,
        recipe_spans=recipe_spans,
    )
    eval_report_path = run_dir / "eval_report.json"
    eval_report = _load_json(eval_report_path) if eval_report_path.is_file() else {}
    canonical = eval_report.get("canonical")
    if not isinstance(canonical, dict):
        return LinePredictionView({}, {}, {}, {}, {}, normalized_recipe_spans)

    canonical_text_path_raw = canonical.get("canonical_text_path")
    canonical_spans_path_raw = canonical.get("canonical_span_labels_path")
    if not isinstance(canonical_text_path_raw, str) or not isinstance(canonical_spans_path_raw, str):
        return LinePredictionView({}, {}, {}, {}, {}, normalized_recipe_spans)

    canonical_text_path = Path(canonical_text_path_raw)
    canonical_spans_path = Path(canonical_spans_path_raw)
    if not canonical_text_path.is_file() or not canonical_spans_path.is_file():
        return LinePredictionView({}, {}, {}, {}, {}, normalized_recipe_spans)

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
            recipe_spans=normalized_recipe_spans,
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
        recipe_spans=normalized_recipe_spans,
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


def _project_context_metadata(repo_root: Path) -> dict[str, Any]:
    return _project_context_metadata_impl(
        repo_root=repo_root,
        project_context_rel_path=PROJECT_CONTEXT_REL_PATH,
    )


def _build_project_context_digest(
    *,
    records: list[RunRecord],
    comparison_summary: dict[str, Any],
    project_context_metadata: dict[str, Any],
    prompt_pairs_per_category: int,
) -> list[str]:
    return _build_project_context_digest_impl(
        records=records,
        comparison_summary=comparison_summary,
        project_context_metadata=project_context_metadata,
        prompt_pairs_per_category=prompt_pairs_per_category,
        alignment_healthy_coverage_min=ALIGNMENT_HEALTHY_COVERAGE_MIN,
        alignment_healthy_match_ratio_min=ALIGNMENT_HEALTHY_MATCH_RATIO_MIN,
        coerce_int=_coerce_int,
        normalized_setting_value=_normalized_setting_value,
        record_setting_values=_record_setting_values,
        format_setting_values=_format_setting_values,
    )


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
    return _resolve_prompt_log_path_impl(
        run_dir=run_dir,
        run_manifest=run_manifest,
        prompt_log_manifest_artifact_key=PROMPT_LOG_MANIFEST_ARTIFACT_KEY,
        prompt_log_file_name=PROMPT_LOG_FILE_NAME,
        prompt_request_response_log_name=PROMPT_REQUEST_RESPONSE_LOG_NAME,
    )

def _resolve_full_prompt_log_path(run_dir: Path, run_manifest: dict[str, Any]) -> Path | None:
    return _resolve_full_prompt_log_path_impl(
        run_dir=run_dir,
        run_manifest=run_manifest,
        full_prompt_log_manifest_artifact_keys=FULL_PROMPT_LOG_MANIFEST_ARTIFACT_KEYS,
        full_prompt_log_file_name=FULL_PROMPT_LOG_FILE_NAME,
    )

def _resolve_prompt_type_samples_path(run_dir: Path, run_manifest: dict[str, Any]) -> Path | None:
    return _resolve_prompt_type_samples_path_impl(
        run_dir=run_dir,
        run_manifest=run_manifest,
        prompt_type_samples_manifest_artifact_keys=PROMPT_TYPE_SAMPLES_MANIFEST_ARTIFACT_KEYS,
        prompt_type_samples_file_name=PROMPT_TYPE_SAMPLES_FILE_NAME,
    )

def _iter_prompt_category_manifest_paths(prompts_dir: Path) -> list[Path]:
    return _iter_prompt_category_manifest_paths_impl(prompts_dir)


def _resolve_knowledge_prompt_path(run_dir: Path) -> Path | None:
    return _resolve_knowledge_prompt_path_impl(
        run_dir=run_dir,
        knowledge_prompt_file_name=KNOWLEDGE_PROMPT_FILE_NAME,
    )


def _resolve_prediction_run_dir(run_dir: Path, run_manifest: dict[str, Any]) -> Path | None:
    return _resolve_prediction_run_dir_impl(run_dir, run_manifest)


def _resolve_processed_output_run_dir(run_dir: Path, run_manifest: dict[str, Any]) -> Path | None:
    return _resolve_processed_output_run_dir_impl(run_dir, run_manifest)


def _resolve_extracted_archive_path(
    run_dir: Path,
    run_manifest: dict[str, Any],
    *,
    pred_run_dir: Path | None = None,
) -> Path | None:
    return _resolve_extracted_archive_path_impl(
        run_dir=run_dir,
        run_manifest=run_manifest,
        pred_run_dir=pred_run_dir,
    )

def _resolve_knowledge_manifest_path(run_dir: Path, run_manifest: dict[str, Any]) -> Path | None:
    return _resolve_knowledge_manifest_path_impl(
        run_dir=run_dir,
        run_manifest=run_manifest,
        knowledge_manifest_file_name=KNOWLEDGE_MANIFEST_FILE_NAME,
    )


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
    candidate_paths: list[Path] = []
    artifacts = run_manifest.get("artifacts")
    if isinstance(artifacts, dict):
        recipe_manifest_raw = str(artifacts.get("recipe_manifest_json") or "").strip()
        if recipe_manifest_raw:
            recipe_manifest_path = Path(recipe_manifest_raw)
            candidate_paths.append(
                recipe_manifest_path
                if recipe_manifest_path.is_absolute()
                else run_dir / recipe_manifest_path
            )

    pred_run_dir = _resolve_prediction_run_dir(run_dir, run_manifest)
    processed_output_dir = _resolve_processed_output_run_dir(run_dir, run_manifest)
    raw_llm_dirs: list[Path] = []
    for stage_root in (pred_run_dir, processed_output_dir):
        if not isinstance(stage_root, Path):
            continue
        raw_llm_dir = stage_root / "raw" / "llm"
        if raw_llm_dir.is_dir():
            raw_llm_dirs.append(raw_llm_dir)
            candidate_paths.extend(sorted(raw_llm_dir.glob("*/recipe_manifest.json")))
            direct_raw_llm_manifest = raw_llm_dir / "recipe_manifest.json"
            if direct_raw_llm_manifest.is_file():
                candidate_paths.append(direct_raw_llm_manifest)

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

            extracted = {
                "build_intermediate_status": _manifest_pass_status(
                    recipe_payload.get("recipe_build_intermediate")
                ),
                "correction_status": _manifest_pass_status(
                    recipe_payload.get("recipe_refine")
                ),
                "build_final_status": _manifest_pass_status(
                    recipe_payload.get("recipe_build_final")
                ),
                "final_mapping_status": str(recipe_payload.get("mapping_status") or "").strip(),
                "final_mapping_reason": str(recipe_payload.get("mapping_reason") or "").strip(),
                "recipe_warning_count": len(_coerce_str_list(recipe_payload.get("warnings"))),
                "recipe_error_count": len(_coerce_str_list(recipe_payload.get("errors"))),
                "structural_status": str(recipe_payload.get("structural_status") or "").strip(),
                "structural_reason_codes": _coerce_str_list(
                    recipe_payload.get("structural_reason_codes")
                ),
                "build_intermediate_clamped_block_loss_count": 0,
                "build_intermediate_clamped_block_loss_ratio": None,
                "correction_degradation_reasons": [],
                "correction_degradation_severity": "",
                "correction_promotion_policy": "",
                "build_final_execution_mode": "",
                "build_final_routing_reason": "",
                "build_final_fallback_reason": "",
                "transport_mismatch": _coerce_bool(
                    ((recipe_payload.get("transport_audit") or {}).get("mismatch"))
                ),
                "transport_mismatch_reasons": _coerce_str_list(
                    ((recipe_payload.get("transport_audit") or {}).get("mismatch_reasons"))
                ),
                "transport_effective_to_payload_coverage_ratio": _coerce_float(
                    ((recipe_payload.get("transport_audit") or {}).get(
                        "effective_to_payload_coverage_ratio"
                    ))
                ),
                "evidence_split_quantity_lines": int(
                    _coerce_int(
                        (((recipe_payload.get("evidence_normalization") or {}).get("stats") or {}).get(
                            "split_quantity_lines"
                        ))
                    )
                    or 0
                ),
                "evidence_dropped_page_markers": int(
                    _coerce_int(
                        (((recipe_payload.get("evidence_normalization") or {}).get("stats") or {}).get(
                            "dropped_page_markers"
                        ))
                    )
                    or 0
                ),
                "evidence_folded_page_markers": int(
                    _coerce_int(
                        (((recipe_payload.get("evidence_normalization") or {}).get("stats") or {}).get(
                            "folded_page_markers"
                        ))
                    )
                    or 0
                ),
            }

            existing = diagnostics_by_recipe.get(recipe_id)
            if existing is None:
                diagnostics_by_recipe[recipe_id] = extracted
                continue

            for key, value in extracted.items():
                if _diagnostic_value_has_signal(value):
                    existing[key] = value

        manifest_paths = payload.get("paths") if isinstance(payload.get("paths"), dict) else {}
        correction_audit_dir_raw = str(
            manifest_paths.get("recipe_correction_audit_dir") or ""
        ).strip()
        if correction_audit_dir_raw:
            correction_audit_dir = Path(correction_audit_dir_raw)
            if not correction_audit_dir.is_absolute():
                correction_audit_dir = manifest_path.parent / correction_audit_dir
        else:
            correction_audit_dir = manifest_path.parent / "recipe_correction_audit"
        if correction_audit_dir.is_dir():
            for audit_path in sorted(correction_audit_dir.glob("*.json")):
                try:
                    audit_payload = _load_json(audit_path)
                except Exception:  # noqa: BLE001
                    continue
                recipe_id = str(audit_payload.get("recipe_id") or "").strip()
                if not recipe_id:
                    continue
                input_payload = (
                    audit_payload.get("input")
                    if isinstance(audit_payload.get("input"), dict)
                    else {}
                )
                output_payload = (
                    audit_payload.get("output")
                    if isinstance(audit_payload.get("output"), dict)
                    else {}
                )
                final_payload = (
                    audit_payload.get("deterministic_final_assembly")
                    if isinstance(audit_payload.get("deterministic_final_assembly"), dict)
                    else {}
                )
                mapping_payload = output_payload.get("ingredient_step_mapping")
                correction_mapping_count = _mapping_count(mapping_payload)
                extracted = {
                    "correction_input_block_count": int(
                        _coerce_int(input_payload.get("block_count")) or 0
                    ),
                    "correction_warning_count": int(
                        _coerce_int(output_payload.get("warning_count")) or 0
                    ),
                    "correction_ingredient_count": int(
                        _coerce_int(output_payload.get("ingredient_count")) or 0
                    ),
                    "correction_step_count": int(
                        _coerce_int(output_payload.get("step_count")) or 0
                    ),
                    "correction_mapping_count": int(correction_mapping_count or 0),
                    "correction_empty_mapping": _is_empty_mapping_value(mapping_payload),
                    "final_step_count": int(
                        _coerce_int(final_payload.get("final_step_count")) or 0
                    ),
                }
                existing = diagnostics_by_recipe.setdefault(recipe_id, {})
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
    evidence_rows = parsed_input.get("evidence_rows")
    if isinstance(evidence_rows, list):
        for fallback_index, row in enumerate(evidence_rows):
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            index = _coerce_int(row[0])
            if index is None:
                index = fallback_index
            rows.append(
                {
                    "source_key": "evidence_rows",
                    "block_id": None,
                    "index": int(index),
                    "text": str(row[1] or ""),
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
    knowledge_payload = llm_payload.get("knowledge") if isinstance(llm_payload, dict) else {}
    knowledge_payload = knowledge_payload if isinstance(knowledge_payload, dict) else {}
    source_payload = run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
    source_file = source_payload.get("path") if isinstance(source_payload, dict) else None
    source_file = str(source_file).strip() if isinstance(source_file, str) else None

    rows_written = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        run_dirs = sorted(path for path in raw_llm_dir.iterdir() if path.is_dir())
        for llm_run_dir in run_dirs:
            for stage_key, stage_meta in sorted(
                LLM_STAGE_MAP.items(),
                key=lambda item: (
                    int(item[1].get("sort_order") or 999),
                    str(item[0]),
                ),
            ):
                stage_dir = str(stage_meta.get("artifact_stem") or "").strip()
                if not stage_dir:
                    continue
                stage_in_dir = llm_run_dir / stage_dir / "in"
                stage_out_dir = llm_run_dir / stage_dir / "out"
                input_files = (
                    sorted(path for path in stage_in_dir.iterdir() if path.is_file())
                    if stage_in_dir.exists()
                    else []
                )
                output_files = (
                    sorted(path for path in stage_out_dir.iterdir() if path.is_file())
                    if stage_out_dir.exists()
                    else []
                )
                if not input_files and not output_files:
                    continue
                input_by_name = {path.name: path for path in input_files}
                output_by_name = {path.name: path for path in output_files}
                if stage_key == "nonrecipe_finalize":
                    pass_process_payload = (
                        knowledge_payload.get("process_run")
                        if isinstance(knowledge_payload.get("process_run"), dict)
                        else None
                    )
                elif stage_key == "recipe_refine":
                    pass_process_payload = (
                        process_runs.get("recipe_correction")
                        if isinstance(process_runs, dict)
                        else None
                    )
                else:
                    pass_process_payload = None
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
                    if recipe_id is None and stage_key == "nonrecipe_finalize":
                        chunk_id = None
                        if isinstance(parsed_input, dict):
                            chunk_id = str(parsed_input.get("chunk_id") or "").strip() or None
                        if chunk_id is None and isinstance(parsed_output, dict):
                            chunk_id = str(parsed_output.get("chunk_id") or "").strip() or None
                        recipe_id = chunk_id
                    rendered_prompt = _render_prompt(
                        prompt_template_text,
                        input_text,
                        input_file or (stage_in_dir / file_name),
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
                        "stage_key": stage_key,
                        "stage_label": stage_label(stage_key),
                        "stage_artifact_stem": stage_dir,
                        "call_id": call_id,
                        "timestamp_utc": timestamp_utc,
                        "recipe_id": recipe_id,
                        "source_file": source_file,
                        "pipeline_id": stage_meta.get("pipeline_id"),
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
                            "pipeline_id": stage_meta.get("pipeline_id"),
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

    stage_call_counts: Counter[str] = Counter()
    stage_warning_counts: Counter[str] = Counter()
    stage_recipe_ids: dict[str, set[str]] = defaultdict(set)
    correction_empty_mapping_calls = 0
    correction_empty_mapping_recipe_ids: Counter[str] = Counter()

    for row in full_prompt_rows:
        stage_key = _prompt_row_stage_key(row) or "unknown"
        stage_call_counts[stage_key] += 1

        recipe_id = str(row.get("recipe_id") or "").strip()
        if recipe_id:
            stage_recipe_ids[stage_key].add(recipe_id)

        parsed_response = _parse_json_like(row.get("parsed_response"))
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
        warnings = _coerce_str_list(parsed_response.get("warnings"))
        correction_outputs = (
            _upload_bundle_recipe_correction_output_rows(parsed_response)
            if stage_key == "recipe_refine"
            else []
        )
        if correction_outputs:
            warnings = []
            for output_row in correction_outputs:
                warnings.extend(_upload_bundle_recipe_correction_metrics(output_row)["warnings"])
        if warnings:
            stage_warning_counts[stage_key] += len(warnings)

        if correction_outputs:
            empty_mapping_recipe_ids: list[str] = []
            for output_row in correction_outputs:
                metrics = _upload_bundle_recipe_correction_metrics(output_row)
                if not metrics["empty_mapping"]:
                    continue
                output_recipe_id = str(output_row.get("recipe_id") or "").strip()
                if output_recipe_id:
                    empty_mapping_recipe_ids.append(output_recipe_id)
            if empty_mapping_recipe_ids:
                correction_empty_mapping_calls += 1
                for output_recipe_id in empty_mapping_recipe_ids:
                    correction_empty_mapping_recipe_ids[output_recipe_id] += 1
        elif "ingredient_step_mapping" in parsed_response and _is_empty_mapping_value(
            parsed_response.get("ingredient_step_mapping")
        ):
            correction_empty_mapping_calls += 1
            if recipe_id:
                correction_empty_mapping_recipe_ids[recipe_id] += 1

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
            "stage_call_counts": dict(sorted(stage_call_counts.items())),
            "stage_warning_counts": dict(sorted(stage_warning_counts.items())),
            "correction_empty_ingredient_step_mapping_calls": correction_empty_mapping_calls,
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
        "recipe_ids_seen_by_stage": {
            stage_key: sorted(recipe_ids)
            for stage_key, recipe_ids in sorted(stage_recipe_ids.items())
        },
        "correction_empty_mapping_recipe_ids": [
            {"recipe_id": recipe_id, "count": count}
            for recipe_id, count in correction_empty_mapping_recipe_ids.most_common()
        ],
        "bridge_note": (
            "Recipe span assignment for per-line diagnostics uses recipe-correction evidence rows. "
            "Canonical line indices that do not fall inside an active recipe span are treated as "
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
    evidence_rows = request_input_payload.get("evidence_rows")
    if isinstance(evidence_rows, list):
        for evidence_row in evidence_rows:
            if not isinstance(evidence_row, (list, tuple)) or len(evidence_row) < 2:
                continue
            text = str(evidence_row[1] or "").strip()
            if text:
                return _excerpt(_normalize_whitespace(text), max_len=excerpt_limit)
    return ""


def _prompt_case_score(
    *,
    stage_key: str,
    warnings_count: int,
    empty_mapping: bool,
    changed_lines_for_recipe: int,
) -> int:
    stage_weights = {
        "recipe_refine": 6,
        "nonrecipe_finalize": 3,
        "tags": 1,
    }
    return (
        stage_weights.get(stage_key, 1)
        + warnings_count * 4
        + (8 if empty_mapping else 0)
        + changed_lines_for_recipe * 5
    )


def _prompt_row_identity_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("timestamp_utc") or ""),
        str(row.get("call_id") or ""),
        str(row.get("stage_key") or row.get("stage_artifact_stem") or ""),
    )


def _prompt_row_stage_key(row: dict[str, Any]) -> str:
    return str(row.get("stage_key") or "").strip()


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


def _prompt_row_owned_recipe_ids(row: dict[str, Any]) -> list[str]:
    request_input_payload = _parse_json_like(row.get("request_input_payload"))
    request_input_payload = (
        request_input_payload if isinstance(request_input_payload, dict) else {}
    )

    owned_ids: list[str] = []
    shard_recipe_rows = request_input_payload.get("r")
    if isinstance(shard_recipe_rows, list):
        for recipe_row in shard_recipe_rows:
            if not isinstance(recipe_row, dict):
                continue
            recipe_id = str(recipe_row.get("rid") or "").strip()
            if recipe_id:
                owned_ids.append(recipe_id)

    if not owned_ids:
        for key in ("owned_ids", "ids"):
            values = request_input_payload.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                recipe_id = str(value or "").strip()
                if recipe_id:
                    owned_ids.append(recipe_id)

    if owned_ids:
        return list(dict.fromkeys(owned_ids))

    recipe_id = _prompt_row_recipe_id(row)
    return [recipe_id] if recipe_id else []


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


def _build_intermediate_selected_blocks(
    row: dict[str, Any],
) -> tuple[list[dict[str, Any]], int | None, int | None]:
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


def _correction_input_blocks(row: dict[str, Any]) -> list[dict[str, Any]]:
    request_payload = _parse_json_like(row.get("request_input_payload"))
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    return _blocks_from_request_payload(request_payload, "blocks")


def _final_recipe_step_count(parsed_response: dict[str, Any]) -> int:
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

    stage_key = _prompt_row_stage_key(row)
    if stage_key == "recipe_refine":
        canonical_recipe = (
            parsed_response.get("canonical_recipe")
            if isinstance(parsed_response.get("canonical_recipe"), dict)
            else {}
        )
        title = str(canonical_recipe.get("title") or "").strip()
        if title:
            return _excerpt(_normalize_whitespace(title), max_len=excerpt_limit)
        if canonical_recipe:
            return _to_json_excerpt(canonical_recipe, excerpt_limit=excerpt_limit)
    if parsed_response:
        return _to_json_excerpt(parsed_response, excerpt_limit=excerpt_limit)
    return ""


def _recipe_short_title(
    *,
    recipe_id: str,
    recipe_spans: list[dict[str, Any]],
    correction_row: dict[str, Any] | None,
) -> str:
    parsed_response = (
        _parse_json_like(correction_row.get("parsed_response"))
        if isinstance(correction_row, dict)
        else None
    )
    if isinstance(parsed_response, dict):
        canonical_recipe = (
            parsed_response.get("canonical_recipe")
            if isinstance(parsed_response.get("canonical_recipe"), dict)
            else {}
        )
        title = str(canonical_recipe.get("title") or "").strip()
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
        start, end = _span_line_bounds(span)
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
    recipe_spans = _normalize_recipe_spans_to_line_coordinates(
        run_dir=Path(codex_run.run_dir),
        recipe_spans=_build_recipe_spans_from_full_prompt_rows(codex_prompt_rows),
    )

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
        stage_key = _prompt_row_stage_key(row)
        if stage_key not in LLM_STAGE_MAP:
            continue
        parsed_response = _parse_json_like(row.get("parsed_response"))
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
        warnings = _coerce_str_list(parsed_response.get("warnings"))
        empty_mapping = False
        if stage_key == "recipe_refine":
            correction_outputs = _upload_bundle_recipe_correction_output_rows(parsed_response)
            if correction_outputs:
                warnings = []
                empty_mapping = False
                for output_row in correction_outputs:
                    metrics = _upload_bundle_recipe_correction_metrics(output_row)
                    warnings.extend(metrics["warnings"])
                    empty_mapping = empty_mapping or bool(metrics["empty_mapping"])
            else:
                empty_mapping = (
                    "ingredient_step_mapping" in parsed_response
                    and _is_empty_mapping_value(parsed_response.get("ingredient_step_mapping"))
                )
        else:
            empty_mapping = (
                "ingredient_step_mapping" in parsed_response
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
                "stage_key": stage_key,
                "stage_label": stage_label(stage_key),
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
                    stage_key=stage_key,
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
            str(row.get("stage_key") or ""),
            str(row.get("call_id") or ""),
        )
    )

    targeted_prompt_case_rows: list[dict[str, Any]] = []
    seen_prompt_case_keys: set[tuple[str, str]] = set()
    for row in targeted_prompt_candidates:
        dedupe_key = (str(row.get("stage_key") or ""), str(row.get("call_id") or ""))
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

    stage_rows_by_recipe: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in sorted(codex_prompt_rows, key=_prompt_row_identity_key):
        stage_key = _prompt_row_stage_key(row)
        if stage_key not in {
            "recipe_build_intermediate",
            "recipe_refine",
            "recipe_build_final",
        }:
            continue
        for recipe_id in _prompt_row_owned_recipe_ids(row):
            if stage_key not in stage_rows_by_recipe[recipe_id]:
                stage_rows_by_recipe[recipe_id][stage_key] = row

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
    recipe_ids.update(stage_rows_by_recipe.keys())
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

        build_intermediate_row = stage_rows_by_recipe.get(recipe_id, {}).get(
            "recipe_build_intermediate"
        )
        correction_row = stage_rows_by_recipe.get(recipe_id, {}).get(
            "recipe_refine"
        )
        build_final_row = stage_rows_by_recipe.get(recipe_id, {}).get(
            "recipe_build_final"
        )
        manifest_diagnostics = manifest_diagnostics_by_recipe.get(recipe_id, {})
        build_intermediate_blocks: list[dict[str, Any]] = []
        build_intermediate_start_block_index: int | None = None
        build_intermediate_end_block_index: int | None = None
        build_intermediate_selected_block_count = 0
        if isinstance(build_intermediate_row, dict):
            (
                build_intermediate_blocks,
                build_intermediate_start_block_index,
                build_intermediate_end_block_index,
            ) = _build_intermediate_selected_blocks(
                build_intermediate_row
            )
            build_intermediate_selected_block_count = len(build_intermediate_blocks)
        correction_call_id = (
            str(correction_row.get("call_id") or "") if isinstance(correction_row, dict) else ""
        )
        correction_input_payload = (
            _parse_json_like(correction_row.get("request_input_payload"))
            if isinstance(correction_row, dict)
            else None
        )
        correction_input_payload = (
            correction_input_payload
            if isinstance(correction_input_payload, dict)
            else {}
        )
        parsed_correction = (
            _upload_bundle_recipe_correction_output_for_recipe(
                correction_row.get("parsed_response"),
                recipe_id=recipe_id,
            )
            if isinstance(correction_row, dict)
            else {}
        )
        correction_input_block_count = int(
            _coerce_int(manifest_diagnostics.get("correction_input_block_count"))
            or _upload_bundle_recipe_correction_input_block_count(
                correction_input_payload,
                recipe_id=recipe_id,
            )
        )
        correction_metrics = _upload_bundle_recipe_correction_metrics(parsed_correction)
        correction_warnings = list(correction_metrics["warnings"])
        correction_warning_count = int(
            _coerce_int(manifest_diagnostics.get("correction_warning_count"))
            or len(correction_warnings)
        )
        correction_warning_buckets = _warning_buckets(correction_warnings)
        canonical_recipe = (
            parsed_correction.get("canonical_recipe")
            if isinstance(parsed_correction.get("canonical_recipe"), dict)
            else {}
        )
        correction_ingredient_count = int(
            _coerce_int(manifest_diagnostics.get("correction_ingredient_count"))
            or int(correction_metrics["ingredient_count"])
        )
        correction_step_count = int(
            _coerce_int(manifest_diagnostics.get("correction_step_count"))
            or int(correction_metrics["step_count"])
        )
        correction_mapping_value = parsed_correction.get("ingredient_step_mapping")
        correction_mapping_count = int(
            _coerce_int(manifest_diagnostics.get("correction_mapping_count"))
            or int(correction_metrics["mapping_count"])
            or 0
        )
        correction_empty_mapping = bool(
            manifest_diagnostics.get("correction_empty_mapping")
        ) or _is_empty_mapping_value(correction_mapping_value)
        correction_empty_output = bool(
            manifest_diagnostics.get("correction_empty_output")
        ) or bool(correction_metrics["empty_output"])
        build_final_parsed = (
            _parse_json_like(build_final_row.get("parsed_response"))
            if isinstance(build_final_row, dict)
            else None
        )
        build_final_parsed = (
            build_final_parsed if isinstance(build_final_parsed, dict) else {}
        )
        final_recipe_step_count = _final_recipe_step_count(build_final_parsed)
        final_recipe_mapping_count = _mapping_count(
            build_final_parsed.get("ingredient_step_mapping")
        )
        final_recipe_empty_mapping = bool(build_final_row) and _is_empty_mapping_value(
            build_final_parsed.get("ingredient_step_mapping")
        )
        final_recipe_warnings = _coerce_str_list(build_final_parsed.get("warnings"))
        final_recipe_warning_count = len(final_recipe_warnings)
        final_recipe_warning_buckets = _warning_buckets(final_recipe_warnings)

        outside_span_status_counter = outside_span_trace_statuses_by_recipe.get(recipe_id, Counter())
        outside_span_trace_status_top = ""
        if outside_span_status_counter:
            outside_span_trace_status_top = sorted(
                outside_span_status_counter.items(),
                key=lambda item: (-item[1], item[0]),
            )[0][0]

        recipe_pipeline_id = str(codex_run.llm_recipe_pipeline or "").strip()
        recipe_stages = _upload_bundle_recipe_stages_for_row(
            recipe_pipeline_id=recipe_pipeline_id,
            correction_call_id=correction_call_id,
        )
        build_intermediate_status = str(
            manifest_diagnostics.get("build_intermediate_status") or ""
        )
        correction_status = str(
            manifest_diagnostics.get("correction_status") or ""
        )
        build_final_status = str(
            manifest_diagnostics.get("build_final_status") or ""
        )
        final_mapping_status = str(
            manifest_diagnostics.get("final_mapping_status") or ""
        )
        final_mapping_reason = str(
            manifest_diagnostics.get("final_mapping_reason") or ""
        )
        structural_status = str(manifest_diagnostics.get("structural_status") or "")
        structural_reason_codes = _coerce_str_list(
            manifest_diagnostics.get("structural_reason_codes")
        )
        recipe_warning_count = int(
            _coerce_int(manifest_diagnostics.get("recipe_warning_count")) or 0
        )
        recipe_error_count = int(
            _coerce_int(manifest_diagnostics.get("recipe_error_count")) or 0
        )

        line_total_effective = (
            line_total
            if line_total > 0
            else (correction_input_block_count or build_intermediate_selected_block_count)
        )
        short_title = _recipe_short_title(
            recipe_id=recipe_id,
            recipe_spans=recipe_spans,
            correction_row=correction_row,
        )
        recipe_triage_rows.append(
            {
                "source_key": source_key,
                "source_file": source_file,
                "codex_run_id": codex_run.run_id,
                "baseline_run_id": baseline_run.run_id,
                "recipe_pipeline_id": recipe_pipeline_id,
                "recipe_stages": recipe_stages,
                "selection_hint_preprocess_status": preprocess_status,
                "recipe_id": recipe_id,
                "short_title": short_title,
                "line_total": line_total_effective,
                "changed_lines_codex_vs_baseline": int(recipe_flip_counts.get(recipe_id, 0)),
                "codex_accuracy": codex_accuracy,
                "baseline_accuracy": baseline_accuracy,
                "delta_codex_minus_baseline": delta_codex_minus_baseline,
                "correction_call_id": correction_call_id,
                "correction_input_block_count": correction_input_block_count,
                "correction_warning_count": correction_warning_count,
                "correction_warning_buckets": correction_warning_buckets,
                "correction_ingredient_count": correction_ingredient_count,
                "correction_step_count": correction_step_count,
                "correction_mapping_count": correction_mapping_count,
                "correction_empty_mapping": correction_empty_mapping,
                "correction_empty_output": correction_empty_output,
                "build_intermediate_status": build_intermediate_status,
                "correction_status": correction_status,
                "build_final_status": build_final_status,
                "final_mapping_status": final_mapping_status,
                "final_mapping_reason": final_mapping_reason,
                "structural_status": structural_status,
                "structural_reason_codes": structural_reason_codes,
                "recipe_warning_count": recipe_warning_count,
                "recipe_error_count": recipe_error_count,
                "build_intermediate_call_id": str(build_intermediate_row.get("call_id") or "")
                if isinstance(build_intermediate_row, dict)
                else "",
                "correction_call_id": correction_call_id,
                "build_final_call_id": str(build_final_row.get("call_id") or "")
                if isinstance(build_final_row, dict)
                else "",
                "build_intermediate_start_block_index": build_intermediate_start_block_index,
                "build_intermediate_end_block_index": build_intermediate_end_block_index,
                "build_intermediate_selected_block_count": build_intermediate_selected_block_count,
                "correction_input_block_count": correction_input_block_count,
                "build_intermediate_missing_block_count": 0,
                "build_intermediate_extra_block_count": 0,
                "final_recipe_step_count": final_recipe_step_count,
                "final_recipe_mapping_count": final_recipe_mapping_count,
                "final_recipe_empty_mapping": final_recipe_empty_mapping,
                "final_recipe_warning_count": final_recipe_warning_count,
                "final_recipe_warning_buckets": final_recipe_warning_buckets,
                "build_intermediate_clamped_block_loss_count": 0,
                "build_intermediate_clamped_block_loss_ratio": None,
                "correction_degradation_reasons": [],
                "correction_degradation_severity": "",
                "correction_promotion_policy": "",
                "build_final_execution_mode": "",
                "build_final_routing_reason": "",
                "build_final_fallback_reason": "",
                "transport_mismatch": _coerce_bool(
                    manifest_diagnostics.get("transport_mismatch")
                ),
                "transport_mismatch_reasons": _coerce_str_list(
                    manifest_diagnostics.get("transport_mismatch_reasons")
                ),
                "transport_effective_to_payload_coverage_ratio": _coerce_float(
                    manifest_diagnostics.get("transport_effective_to_payload_coverage_ratio")
                ),
                "evidence_split_quantity_lines": int(
                    _coerce_int(manifest_diagnostics.get("evidence_split_quantity_lines"))
                    or 0
                ),
                "evidence_dropped_page_markers": int(
                    _coerce_int(manifest_diagnostics.get("evidence_dropped_page_markers"))
                    or 0
                ),
                "evidence_folded_page_markers": int(
                    _coerce_int(manifest_diagnostics.get("evidence_folded_page_markers"))
                    or 0
                ),
                "outside_span_wrong_line_count": int(outside_span_wrong_counts.get(recipe_id, 0)),
                "outside_span_trace_status_top": outside_span_trace_status_top,
                "raw_block_window_excerpt": _input_excerpt_for_prompt_row(
                    correction_row,
                    excerpt_limit=excerpt_limit,
                )
                if isinstance(correction_row, dict)
                else "",
            }
        )

    call_inventory_rows: list[dict[str, Any]] = []
    for row in sorted(codex_prompt_rows, key=_prompt_row_identity_key):
        stage_key = _prompt_row_stage_key(row)
        if not _upload_bundle_call_inventory_stage_included(stage_key):
            continue
        parsed_response = _parse_json_like(row.get("parsed_response"))
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
        warnings = _coerce_str_list(parsed_response.get("warnings"))
        warning_buckets = _warning_buckets(warnings)

        input_block_count = 0
        extracted_ingredient_count = 0
        step_count = 0
        mapping_count = 0
        request_input_payload = _parse_json_like(row.get("request_input_payload"))
        request_input_payload = (
            request_input_payload if isinstance(request_input_payload, dict) else {}
        )
        if stage_key == "recipe_refine":
            correction_outputs = _upload_bundle_recipe_correction_output_rows(parsed_response)
            input_block_count = _upload_bundle_recipe_correction_input_block_count(
                request_input_payload
            )
            if correction_outputs:
                warnings = []
                extracted_ingredient_count = 0
                step_count = 0
                mapping_count = 0
                for output_row in correction_outputs:
                    metrics = _upload_bundle_recipe_correction_metrics(output_row)
                    warnings.extend(metrics["warnings"])
                    extracted_ingredient_count += int(metrics["ingredient_count"])
                    step_count += int(metrics["step_count"])
                    mapping_count += int(metrics["mapping_count"])
                warning_buckets = _warning_buckets(warnings)
            else:
                canonical_recipe = (
                    parsed_response.get("canonical_recipe")
                    if isinstance(parsed_response.get("canonical_recipe"), dict)
                    else {}
                )
                extracted_ingredient_count = len(canonical_recipe.get("ingredients") or [])
                step_count = len(canonical_recipe.get("steps") or [])
                mapping_count = _mapping_count(parsed_response.get("ingredient_step_mapping"))
        elif stage_key == "line_role":
            row_payload = request_input_payload.get("rows")
            input_block_count = len(row_payload) if isinstance(row_payload, list) else 0
        elif stage_key == "recipe_build_final":
            draft_payload = _parse_json_like(parsed_response.get("draft_v1"))
            draft_payload = draft_payload if isinstance(draft_payload, dict) else {}
            steps_payload = draft_payload.get("steps")
            step_count = len(steps_payload) if isinstance(steps_payload, list) else 0
            mapping_count = _mapping_count(parsed_response.get("ingredient_step_mapping"))

        runtime_payload = _upload_bundle_extract_call_runtime(row)
        observed_cost_usd = _coerce_float(runtime_payload.get("cost_usd"))
        estimated_cost_usd = (
            observed_cost_usd
            if observed_cost_usd is not None
            else _upload_bundle_estimate_call_cost_usd(
                tokens_input=_coerce_int(runtime_payload.get("tokens_input")),
                tokens_cached_input=_coerce_int(runtime_payload.get("tokens_cached_input")),
                tokens_output=_coerce_int(runtime_payload.get("tokens_output")),
            )
        )

        call_inventory_rows.append(
            {
                "run_id": codex_run.run_id,
                "source_key": source_key,
                "source_file": source_file,
                "recipe_id": _prompt_row_recipe_id(row),
                "stage_key": stage_key,
                "stage_label": stage_label(stage_key),
                "call_id": str(row.get("call_id") or ""),
                "timestamp_utc": str(row.get("timestamp_utc") or ""),
                "model": str(row.get("model") or ""),
                "input_block_count": input_block_count,
                "warning_count": len(warnings),
                "warning_buckets": warning_buckets,
                "extracted_ingredient_count": extracted_ingredient_count,
                "extracted_instruction_count": step_count,
                "step_count": step_count,
                "mapping_count": mapping_count,
                "input_excerpt": _input_excerpt_for_prompt_row(row, excerpt_limit=excerpt_limit),
                "output_excerpt": _output_excerpt_for_prompt_row(row, excerpt_limit=excerpt_limit),
                "duration_ms": _coerce_int(runtime_payload.get("duration_ms")),
                "tokens_input": _coerce_int(runtime_payload.get("tokens_input")),
                "tokens_cached_input": _coerce_int(
                    runtime_payload.get("tokens_cached_input")
                ),
                "tokens_output": _coerce_int(runtime_payload.get("tokens_output")),
                "tokens_reasoning": _coerce_int(runtime_payload.get("tokens_reasoning")),
                "tokens_total": _coerce_int(runtime_payload.get("tokens_total")),
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
                "retry_attempt": _coerce_int(runtime_payload.get("attempt_index")),
                "runtime_status": runtime_payload.get("status"),
                "_stage_rank": _upload_bundle_call_inventory_stage_rank(stage_key),
            }
        )
    call_inventory_rows.sort(
        key=lambda row: (
            str(row.get("recipe_id") or ""),
            int(row.get("_stage_rank") or 99),
            str(row.get("call_id") or ""),
            str(row.get("timestamp_utc") or ""),
        )
    )
    for row in call_inventory_rows:
        row.pop("_stage_rank", None)

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
            str(row.get("stage_key") or ""),
            str(row.get("call_id") or ""),
        ),
    )
    selected: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for row in sorted_rows:
        dedupe_key = (
            str(row.get("source_key") or ""),
            str(row.get("codex_run_id") or ""),
            str(row.get("stage_key") or ""),
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
                f"- stage/call: `{row.get('stage_key')}` / `{row.get('call_id')}`",
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
    warnings_by_stage: Counter[str] = Counter()
    warning_buckets: Counter[str] = Counter()
    for row in call_inventory_rows:
        stage_key = str(row.get("stage_key") or "")
        warning_count = int(_coerce_int(row.get("warning_count")) or 0)
        warnings_by_stage[stage_key] += warning_count
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

    correction_empty_mapping_count = sum(
        1 for row in recipe_triage_rows if bool(row.get("correction_empty_mapping"))
    )
    correction_empty_output_count = sum(
        1 for row in recipe_triage_rows if bool(row.get("correction_empty_output"))
    )
    correction_empty_mapping_with_nonempty_output_count = sum(
        1
        for row in recipe_triage_rows
        if bool(row.get("correction_empty_mapping")) and not bool(row.get("correction_empty_output"))
    )
    final_recipe_empty_mapping_count = sum(
        1 for row in recipe_triage_rows if bool(row.get("final_recipe_empty_mapping"))
    )
    recipe_warning_recipe_count = sum(
        1
        for row in recipe_triage_rows
        if int(_coerce_int(row.get("recipe_warning_count")) or 0) > 0
    )
    structural_problem_recipe_count = sum(
        1
        for row in recipe_triage_rows
        if str(row.get("structural_status") or "").strip().lower()
        not in {"", "ok", "none"}
    )
    transport_mismatch_recipe_count = sum(
        1 for row in recipe_triage_rows if bool(row.get("transport_mismatch"))
    )
    build_intermediate_clamped_loss_recipe_count = sum(
        1
        for row in recipe_triage_rows
        if int(_coerce_int(row.get("build_intermediate_clamped_block_loss_count")) or 0) > 0
    )
    correction_degraded_recipe_count = sum(
        1
        for row in recipe_triage_rows
        if _coerce_str_list(row.get("correction_degradation_reasons"))
        or _upload_bundle_status_is_problem(row.get("correction_status"))
    )
    build_final_fallback_recipe_count = sum(
        1
        for row in recipe_triage_rows
        if str(row.get("build_final_fallback_reason") or "").strip()
        or _upload_bundle_status_is_problem(row.get("build_final_status"))
    )

    build_intermediate_status_counts: Counter[str] = Counter()
    correction_status_counts: Counter[str] = Counter()
    build_final_status_counts: Counter[str] = Counter()
    final_mapping_status_counts: Counter[str] = Counter()
    structural_status_counts: Counter[str] = Counter()
    correction_degradation_severity_counts: Counter[str] = Counter()
    build_final_execution_mode_counts: Counter[str] = Counter()
    for row in recipe_triage_rows:
        build_intermediate_status = (
            str(row.get("build_intermediate_status") or "").strip()
            or "missing"
        )
        raw_correction_status = str(row.get("correction_status") or "").strip()
        if raw_correction_status:
            correction_status = raw_correction_status
        elif bool(row.get("correction_empty_output")) and (
            bool(row.get("correction_call_id"))
            or int(_coerce_int(row.get("correction_input_block_count")) or 0) > 0
        ):
            correction_status = "empty_output_without_manifest_status"
        elif (
            bool(row.get("correction_call_id"))
            or int(_coerce_int(row.get("correction_input_block_count")) or 0) > 0
            or int(_coerce_int(row.get("correction_ingredient_count")) or 0) > 0
            or int(_coerce_int(row.get("correction_step_count")) or 0) > 0
            or int(_coerce_int(row.get("correction_mapping_count")) or 0) > 0
        ):
            correction_status = "nonempty_output_without_manifest_status"
        else:
            correction_status = "missing"
        build_final_status = (
            str(row.get("build_final_status") or "").strip()
            or "missing"
        )
        final_mapping_status = (
            str(row.get("final_mapping_status") or "").strip() or "missing"
        )
        structural_status = str(row.get("structural_status") or "").strip() or "missing"
        build_intermediate_status_counts[build_intermediate_status] += 1
        correction_status_counts[correction_status] += 1
        build_final_status_counts[build_final_status] += 1
        final_mapping_status_counts[final_mapping_status] += 1
        structural_status_counts[structural_status] += 1

        correction_degradation_severity = str(
            row.get("correction_degradation_severity") or ""
        ).strip()
        if correction_degradation_severity:
            correction_degradation_severity_counts[correction_degradation_severity] += 1
        build_final_execution_mode = str(row.get("build_final_execution_mode") or "").strip()
        if build_final_execution_mode:
            build_final_execution_mode_counts[build_final_execution_mode] += 1

    return {
        "warnings_by_stage": _counter_to_sorted_dict(warnings_by_stage),
        "warning_buckets": _counter_to_sorted_dict(warning_buckets),
        "correction_empty_mapping_count": correction_empty_mapping_count,
        "correction_empty_mapping_note": (
            "Counts recipes where the correction mapping object was empty. "
            "This does not imply the correction payload itself was empty."
        ),
        "correction_empty_output_count": correction_empty_output_count,
        "correction_empty_mapping_with_nonempty_output_count": (
            correction_empty_mapping_with_nonempty_output_count
        ),
        "final_recipe_empty_mapping_count": final_recipe_empty_mapping_count,
        "recipe_warning_recipe_count": recipe_warning_recipe_count,
        "structural_problem_recipe_count": structural_problem_recipe_count,
        "transport_mismatch_recipe_count": transport_mismatch_recipe_count,
        "build_intermediate_clamped_loss_recipe_count": build_intermediate_clamped_loss_recipe_count,
        "correction_degraded_recipe_count": correction_degraded_recipe_count,
        "build_final_fallback_recipe_count": build_final_fallback_recipe_count,
        "recipe_stage_status_counts": {
            "recipe_build_intermediate": _counter_to_sorted_dict(
                build_intermediate_status_counts
            ),
            "recipe_refine": _counter_to_sorted_dict(
                correction_status_counts
            ),
            "recipe_build_final": _counter_to_sorted_dict(build_final_status_counts),
        },
        "correction_degradation_severity_counts": _counter_to_sorted_dict(
            correction_degradation_severity_counts
        ),
        "build_final_execution_mode_counts": _counter_to_sorted_dict(
            build_final_execution_mode_counts
        ),
        "final_mapping_status_counts": _counter_to_sorted_dict(
            final_mapping_status_counts
        ),
        "structural_status_counts": _counter_to_sorted_dict(
            structural_status_counts
        ),
        "outside_span_wrong_line_count": len(outside_span_trace_rows),
        "outside_span_trace_status_counts": _counter_to_sorted_dict(
            outside_span_trace_status_counts
        ),
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
    def _block_loss_count(row: dict[str, Any]) -> int:
        return int(
            _coerce_int(
                row.get("build_intermediate_missing_block_count")
                if row.get("build_intermediate_missing_block_count") is not None
                else row.get("build_intermediate_clamped_block_loss_count")
            )
            or 0
        )

    def _empty_mapping(row: dict[str, Any]) -> bool:
        return bool(
            row.get("final_recipe_empty_mapping") or row.get("correction_empty_mapping")
        )

    def _upstream_input_count(row: dict[str, Any]) -> int:
        return int(
            _coerce_int(
                row.get("build_intermediate_selected_block_count")
                if row.get("build_intermediate_selected_block_count") is not None
                else row.get("correction_input_block_count")
            )
            or 0
        )

    def _warning_count(row: dict[str, Any]) -> int:
        return int(_coerce_int(row.get("correction_warning_count")) or 0)

    def _instruction_count(row: dict[str, Any]) -> int:
        return int(_coerce_int(row.get("correction_step_count")) or 0)

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

    top_warning_burden = sorted(
        recipe_triage_rows,
        key=lambda row: (
            -_block_loss_count(row),
            -abs(_float_or_zero(row.get("delta_codex_minus_baseline"))),
            -int(_coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0),
            str(row.get("recipe_id") or ""),
        ),
    )
    top_warning_burden = [row for row in top_warning_burden if _block_loss_count(row) > 0]
    add_rows(
        top_warning_burden,
        limit=STARTER_PACK_SELECTION_POLICY["top_block_loss"],
        reason="top_block_loss",
    )

    empty_mapping_candidates = [
        row
        for row in recipe_triage_rows
        if _empty_mapping(row)
        and (
            _upstream_input_count(row) >= 8
            or _warning_count(row) >= 2
            or _instruction_count(row) == 0
        )
    ]
    empty_mapping_candidates.sort(
        key=lambda row: (
            -abs(_float_or_zero(row.get("delta_codex_minus_baseline"))),
            -int(_coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0),
            -_upstream_input_count(row),
            str(row.get("recipe_id") or ""),
        )
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
        if _warning_count(row) == 0
        and not _empty_mapping(row)
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
        "current_recipe_pipeline=single_correction",
        f"correction_warnings={int(_coerce_int(row.get('correction_warning_count')) or 0)}",
        f"correction_empty_mapping={_serialize_bool(bool(row.get('correction_empty_mapping')))}",
    ]
    final_mapping_status = str(row.get("final_mapping_status") or "").strip()
    if final_mapping_status:
        chunks.append(f"final_mapping_status={final_mapping_status}")
    if str(row.get("final_mapping_reason") or "").strip():
        chunks.append("final_mapping_reason=yes")
    structural_status = str(row.get("structural_status") or "").strip()
    if structural_status:
        chunks.append(f"structural_status={structural_status}")
    outside_count = int(_coerce_int(row.get("outside_span_wrong_line_count")) or 0)
    if outside_count > 0:
        chunks.append(f"outside_span_wrong_lines={outside_count}")
    return ", ".join(chunks)


def _warning_summary_for_recipe(row: dict[str, Any]) -> str:
    chunks: list[str] = []
    correction_warning_count = int(_coerce_int(row.get("correction_warning_count")) or 0)
    if correction_warning_count > 0:
        chunks.append(
            "recipe_refine"
            f"({correction_warning_count}): "
            f"{_serialize_pipe_list(_coerce_str_list(row.get('correction_warning_buckets')))}"
        )
    final_mapping_status = str(row.get("final_mapping_status") or "").strip()
    if final_mapping_status:
        chunks.append(f"recipe_build_final_mapping: {final_mapping_status}")
    structural_status = str(row.get("structural_status") or "").strip()
    if structural_status:
        chunks.append(f"structural_status: {structural_status}")
    return "; ".join(chunks) if chunks else "none"


def _build_selected_recipe_packets(
    *,
    selected_recipe_rows: list[dict[str, Any]],
    changed_line_rows: list[dict[str, Any]],
    default_recipe_stages: list[dict[str, str]] | None = None,
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

        intermediate_summary = {
            "call_id": str(row.get("build_intermediate_call_id") or ""),
            "status": str(row.get("build_intermediate_status") or ""),
            "input_block_count": int(
                _coerce_int(row.get("correction_input_block_count")) or 0
            ),
            "deterministic_stage": True,
            "clamped_block_loss_count": int(
                _coerce_int(row.get("build_intermediate_clamped_block_loss_count")) or 0
            ),
            "clamped_block_loss_ratio": _coerce_float(
                row.get("build_intermediate_clamped_block_loss_ratio")
            ),
        }
        correction_summary = {
            "call_id": str(row.get("correction_call_id") or ""),
            "status": str(row.get("correction_status") or ""),
            "input_block_count": int(
                _coerce_int(row.get("correction_input_block_count")) or 0
            ),
            "warning_count": int(_coerce_int(row.get("correction_warning_count")) or 0),
            "warning_buckets": _coerce_str_list(row.get("correction_warning_buckets")),
            "ingredient_count": int(
                _coerce_int(row.get("correction_ingredient_count")) or 0
            ),
            "step_count": int(_coerce_int(row.get("correction_step_count")) or 0),
            "mapping_count": int(_coerce_int(row.get("correction_mapping_count")) or 0),
            "empty_mapping": bool(row.get("correction_empty_mapping")),
            "degradation_reasons": _coerce_str_list(row.get("correction_degradation_reasons")),
            "degradation_severity": str(row.get("correction_degradation_severity") or ""),
            "promotion_policy": str(row.get("correction_promotion_policy") or ""),
        }
        final_summary = {
            "call_id": str(row.get("build_final_call_id") or ""),
            "status": str(row.get("build_final_status") or ""),
            "mapping_status": str(row.get("final_mapping_status") or ""),
            "mapping_reason": str(row.get("final_mapping_reason") or ""),
            "structural_status": str(row.get("structural_status") or ""),
            "structural_reason_codes": _coerce_str_list(
                row.get("structural_reason_codes")
            ),
            "execution_mode": str(row.get("build_final_execution_mode") or ""),
            "routing_reason": str(row.get("build_final_routing_reason") or ""),
            "fallback_reason": str(row.get("build_final_fallback_reason") or ""),
        }
        recipe_quality_summary = {
            "warning_count": int(_coerce_int(row.get("recipe_warning_count")) or 0),
            "error_count": int(_coerce_int(row.get("recipe_error_count")) or 0),
        }
        transport_summary: dict[str, Any] = {}
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
        if not any(
            _diagnostic_value_has_signal(value)
            for value in evidence_normalization_summary.values()
        ):
            evidence_normalization_summary = {}
        recipe_stages = row.get("recipe_stages")
        recipe_stages = recipe_stages if isinstance(recipe_stages, list) else []
        if not recipe_stages:
            recipe_stages = list(default_recipe_stages or [])
        recipe_stage_summaries: list[dict[str, Any]] = []
        for recipe_stage in recipe_stages:
            if not isinstance(recipe_stage, dict):
                continue
            stage_key = str(recipe_stage.get("stage_key") or "").strip()
            stage_label = str(recipe_stage.get("stage_label") or stage_key).strip()
            if stage_key == "recipe_build_intermediate":
                recipe_stage_summaries.append(
                    {
                        "stage_key": stage_key,
                        "stage_label": stage_label,
                        **intermediate_summary,
                    }
                )
                continue
            if stage_key == "recipe_refine":
                recipe_stage_summaries.append(
                    {
                        "stage_key": stage_key,
                        "stage_label": stage_label,
                        **correction_summary,
                    }
                )
                continue
            if stage_key == "recipe_build_final":
                recipe_stage_summaries.append(
                    {
                        "stage_key": stage_key,
                        "stage_label": stage_label,
                        **final_summary,
                    }
                )
                continue
        packets.append(
            {
                "selection_reason": str(row.get("selection_reason") or ""),
                "source_key": str(row.get("source_key") or ""),
                "codex_run_id": str(row.get("codex_run_id") or row.get("run_id") or ""),
                "baseline_run_id": str(row.get("baseline_run_id") or ""),
                "recipe_pipeline_id": str(row.get("recipe_pipeline_id") or ""),
                "recipe_stages": recipe_stage_summaries,
                "recipe_id": str(row.get("recipe_id") or ""),
                "short_title": str(row.get("short_title") or ""),
                "delta_codex_minus_baseline": _coerce_float(
                    row.get("delta_codex_minus_baseline")
                ),
                "changed_lines_codex_vs_baseline": int(
                    _coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0
                ),
                "bridge_anomaly_summary": _bridge_anomaly_summary(row),
                "warning_summary": _warning_summary_for_recipe(row),
                "build_intermediate_summary": intermediate_summary,
                "correction_summary": correction_summary,
                "build_final_summary": final_summary,
                "recipe_quality_summary": recipe_quality_summary,
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
        recipe_pipeline_id = str(packet.get("recipe_pipeline_id") or "").strip()
        recipe_stages = packet.get("recipe_stages")
        recipe_stages = recipe_stages if isinstance(recipe_stages, list) else []
        recipe_stage_labels = [
            str(stage.get("stage_label") or stage.get("stage_key") or "").strip()
            for stage in recipe_stages
            if isinstance(stage, dict)
        ]
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
                *(
                    [f"- recipe_pipeline_id: {recipe_pipeline_id}"]
                    if recipe_pipeline_id
                    else []
                ),
                *(
                    [f"- recipe_stages: {', '.join(recipe_stage_labels)}"]
                    if recipe_stage_labels
                    else []
                ),
                "",
                "### Stage Excerpts",
                (
                    "- recipe_build_intermediate: "
                    f"status={packet.get('build_intermediate_summary', {}).get('status')} "
                    "deterministic_stage=yes "
                    f"input_block_count={packet.get('build_intermediate_summary', {}).get('input_block_count')}"
                ),
                (
                    "- recipe_quality: "
                    f"warnings={packet.get('recipe_quality_summary', {}).get('warning_count')} "
                    f"errors={packet.get('recipe_quality_summary', {}).get('error_count')}"
                ),
                "",
            ]
        )
        for recipe_stage in recipe_stages:
            if not isinstance(recipe_stage, dict):
                continue
            stage_label = str(recipe_stage.get("stage_label") or recipe_stage.get("stage_key") or "")
            stage_key = str(recipe_stage.get("stage_key") or "")
            if stage_key == "recipe_build_intermediate":
                lines.extend(
                    [
                        (
                            f"- {stage_label}: "
                            f"status={recipe_stage.get('status')} "
                            "deterministic_stage=yes"
                        ),
                    ]
                )
                continue
            if stage_key == "recipe_refine":
                lines.extend(
                    [
                        (
                            f"- {stage_label}: "
                            f"call_id={recipe_stage.get('call_id')} "
                            f"status={recipe_stage.get('status')} "
                            f"input_block_count={recipe_stage.get('input_block_count')} "
                            f"warning_count={recipe_stage.get('warning_count')} "
                            f"ingredient_count={recipe_stage.get('ingredient_count')} "
                            f"step_count={recipe_stage.get('step_count')} "
                            f"mapping_count={recipe_stage.get('mapping_count')} "
                            f"empty_mapping={recipe_stage.get('empty_mapping')}"
                        ),
                    ]
                )
                continue
            lines.extend(
                [
                    (
                        f"- {stage_label}: "
                        f"status={recipe_stage.get('status')} "
                        f"mapping_status={recipe_stage.get('mapping_status')} "
                        f"structural_status={recipe_stage.get('structural_status')} "
                        "mapping_reason="
                        f"{'yes' if str(recipe_stage.get('mapping_reason') or '').strip() else 'no'}"
                    ),
                ]
            )
        lines.append("")
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
        f"- `{STARTER_PACK_EXPLICIT_ESCALATION_CHANGED_LINES_FILE_NAME}`",
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
            str(row.get("stage_key") or ""),
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
            "correction_call_id": str(row.get("correction_call_id") or ""),
            "correction_input_block_count": int(
                _coerce_int(row.get("correction_input_block_count")) or 0
            ),
            "correction_warning_count": int(
                _coerce_int(row.get("correction_warning_count")) or 0
            ),
            "correction_warning_buckets": _coerce_str_list(
                row.get("correction_warning_buckets")
            ),
            "correction_ingredient_count": int(
                _coerce_int(row.get("correction_ingredient_count")) or 0
            ),
            "correction_step_count": int(
                _coerce_int(row.get("correction_step_count")) or 0
            ),
            "correction_mapping_count": int(
                _coerce_int(row.get("correction_mapping_count")) or 0
            ),
            "correction_empty_mapping": bool(row.get("correction_empty_mapping")),
            "build_intermediate_status": str(row.get("build_intermediate_status") or ""),
            "correction_status": str(row.get("correction_status") or ""),
            "build_final_status": str(row.get("build_final_status") or ""),
            "final_mapping_status": str(row.get("final_mapping_status") or ""),
            "final_mapping_reason": str(row.get("final_mapping_reason") or ""),
            "structural_status": str(row.get("structural_status") or ""),
            "structural_reason_codes": _coerce_str_list(row.get("structural_reason_codes")),
            "recipe_warning_count": int(_coerce_int(row.get("recipe_warning_count")) or 0),
            "recipe_error_count": int(_coerce_int(row.get("recipe_error_count")) or 0),
            "outside_span_wrong_line_count": int(
                _coerce_int(row.get("outside_span_wrong_line_count")) or 0
            ),
            "outside_span_trace_status_top": str(row.get("outside_span_trace_status_top") or ""),
        }
        for row in sorted_recipe_triage_rows
    ]
    _write_jsonl(starter_pack_dir / STARTER_PACK_BRIDGE_SUMMARY_FILE_NAME, bridge_summary_rows)

    selected_recipe_rows = _select_starter_pack_recipe_cases(sorted_recipe_triage_rows)
    default_recipe_stages = _upload_bundle_recipe_stages_for_row(
        recipe_pipeline_id="codex-recipe-shard-v1",
        correction_call_id=None,
    )
    selected_packets = _build_selected_recipe_packets(
        selected_recipe_rows=selected_recipe_rows,
        changed_line_rows=changed_line_rows,
        default_recipe_stages=default_recipe_stages,
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
    warning_lines = warning_trace_summary["warnings_by_stage"]
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
            "- warning_counts_by_stage: "
            + ", ".join(f"{key}={value}" for key, value in warning_lines.items())
            if warning_lines
            else "- warning_counts_by_stage: none"
        ),
        (
            "- warning_bucket_counts: "
            + ", ".join(f"{key}={value}" for key, value in bucket_lines.items())
            if bucket_lines
            else "- warning_bucket_counts: none"
        ),
        (
            "- correction_empty_mapping_count: "
            f"{warning_trace_summary.get('correction_empty_mapping_count')}"
        ),
        (
            "- correction_empty_output_count: "
            f"{warning_trace_summary.get('correction_empty_output_count')}"
        ),
        (
            "- correction_empty_mapping_with_nonempty_output_count: "
            f"{warning_trace_summary.get('correction_empty_mapping_with_nonempty_output_count')}"
        ),
        (
            "- recipe_warning_recipe_count: "
            f"{warning_trace_summary.get('recipe_warning_recipe_count')}"
        ),
        (
            "- structural_problem_recipe_count: "
            f"{warning_trace_summary.get('structural_problem_recipe_count')}"
        ),
        (
            "- final_mapping_status_counts: "
            f"{json.dumps(warning_trace_summary.get('final_mapping_status_counts') or {}, sort_keys=True)}"
        ),
        (
            "- recipe_stage_status_counts: "
            f"{json.dumps(warning_trace_summary.get('recipe_stage_status_counts') or {}, sort_keys=True)}"
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
    recipe_pipeline_context = build_recipe_pipeline_topology(
        run_rows=starter_pack_run_rows,
        comparison_pairs=comparison_pairs,
        recipe_triage_rows=sorted_recipe_triage_rows,
    )
    (
        explicit_escalation_changed_lines_summary,
        explicit_escalation_changed_lines_rows,
    ) = _upload_bundle_build_explicit_escalation_changed_lines_packet(
        source_root=output_dir,
        run_dir_by_id=starter_pack_run_dir_by_id,
        changed_line_rows=changed_line_rows,
    )
    _write_jsonl(
        starter_pack_dir / STARTER_PACK_EXPLICIT_ESCALATION_CHANGED_LINES_FILE_NAME,
        explicit_escalation_changed_lines_rows,
    )
    net_error_blame_summary = _upload_bundle_build_net_error_blame_summary(
        changed_line_rows=changed_line_rows,
        recipe_triage_rows=sorted_recipe_triage_rows,
        comparison_pairs=comparison_pairs,
        recipe_pipeline_context=recipe_pipeline_context,
        explicit_escalation_rows=explicit_escalation_changed_lines_rows,
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
            "- explicit_escalation_changed_lines: "
            + str(
                int(
                    _coerce_int(
                        explicit_escalation_changed_lines_summary.get("row_count")
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
        "outside_span_trace_sample": outside_span_manifest,
        "triage_packet": {
            "schema_version": UPLOAD_BUNDLE_TRIAGE_PACKET_SCHEMA_VERSION,
            "row_count": len(triage_packet_rows),
        },
        "net_error_blame_summary_file": STARTER_PACK_NET_ERROR_BLAME_FILE_NAME,
        "config_version_metadata_file": STARTER_PACK_CONFIG_VERSION_METADATA_FILE_NAME,
        "explicit_escalation_changed_lines": {
            "summary": explicit_escalation_changed_lines_summary,
            "file": STARTER_PACK_EXPLICIT_ESCALATION_CHANGED_LINES_FILE_NAME,
            "row_count": len(explicit_escalation_changed_lines_rows),
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
            "Codex Exec sampled prompt log: convenience file keeps all calls from "
            "`full_prompt_log.jsonl` when available (legacy text-log copy fallback)."
        )
    else:
        lines.append(
            "Codex Exec sampled prompt log: convenience-only sampled calls per stage "
            f"(max {prompt_pairs_per_category}, sampled from full_prompt_log.jsonl when available)"
        )
    lines.append(
        "Codex Exec full prompt log: `full_prompt_log.jsonl` copied as complete machine-readable call rows (no sampling/truncation)."
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


def _json_dump_bytes(
    value: Any,
    *,
    indent: int | None = None,
    sort_keys: bool = False,
) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=indent,
        sort_keys=sort_keys,
    ).encode("utf-8")


def _upload_bundle_payload_row_line_bytes(payload_row: dict[str, Any]) -> int:
    return len(_json_dump_bytes(payload_row)) + 1


def _resolve_prompt_budget_summary_path(
    *,
    run_dir: Path,
    pred_run_dir: Path | None,
    pred_manifest: dict[str, Any],
) -> Path | None:
    candidates: list[Path] = []
    manifest_path = str(pred_manifest.get("prompt_budget_summary_path") or "").strip()
    if manifest_path:
        candidate = Path(manifest_path)
        if not candidate.is_absolute() and pred_run_dir is not None:
            candidate = pred_run_dir / candidate
        candidates.append(candidate)
    candidates.append(run_dir / "prompt_budget_summary.json")
    if pred_run_dir is not None:
        candidates.append(pred_run_dir / "prompt_budget_summary.json")
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved in seen or not candidate.is_file():
            continue
        seen.add(resolved)
        payload = _upload_bundle_load_json_object(candidate)
        if isinstance(payload.get("by_stage"), dict):
            return candidate
    return None


def _upload_bundle_high_level_final_reserve_bytes(target_bundle_size_bytes: int) -> int:
    target_bytes = max(int(target_bundle_size_bytes), 1)
    reserve_bytes = max(
        int(target_bytes * GROUP_UPLOAD_BUNDLE_FINAL_RESERVE_SHARE),
        GROUP_UPLOAD_BUNDLE_FINAL_RESERVE_MIN_BYTES,
    )
    return min(reserve_bytes, max(target_bytes - 1, 0))


def _upload_bundle_high_level_trim_priority(path: str) -> tuple[int, str] | None:
    normalized = str(path or "").strip().lower()
    if not normalized:
        return None
    direct_suffixes = (
        (
            (
                FULL_PROMPT_LOG_FILE_NAME,
                WRONG_LABEL_FULL_CONTEXT_FILE_NAME,
                PREPROCESS_TRACE_FAILURES_FILE_NAME,
                PROMPT_REQUEST_RESPONSE_LOG_NAME,
                "recipe_manifest.json",
            ),
            0,
        ),
        (
            (
                TARGETED_PROMPT_CASES_FILE_NAME,
                LABEL_POLICY_NOTES_FILE_NAME,
                STARTER_PACK_CASEBOOK_FILE_NAME,
                STARTER_PACK_SELECTED_PACKETS_FILE_NAME,
                STARTER_PACK_BRIDGE_SUMMARY_FILE_NAME,
            ),
            1,
        ),
        (
            (
                STARTER_PACK_EXPLICIT_ESCALATION_CHANGED_LINES_FILE_NAME,
                "explicit_escalation_changed_lines.packet.jsonl",
                STARTER_PACK_BASELINE_TRACE_PARITY_FILE_NAME,
                "baseline_trace_parity.json",
                STARTER_PACK_CONFIG_VERSION_METADATA_FILE_NAME,
                "config_version_metadata.json",
                STARTER_PACK_NET_ERROR_BLAME_FILE_NAME,
                "net_error_blame_summary.json",
                PROMPT_TYPE_SAMPLES_FILE_NAME,
                KNOWLEDGE_MANIFEST_FILE_NAME,
                CHANGED_LINES_FILE_NAME.rsplit("/", 1)[-1],
                "prediction-run/extracted_archive.json",
                "prediction-run/line-role-pipeline/extracted_archive.json",
                "extracted_archive.json",
            ),
            2,
        ),
        (
            (
                "need_to_know_summary.json",
                "eval_report.json",
                "prompt_budget_summary.json",
            ),
            3,
        ),
    )
    for suffixes, priority in direct_suffixes:
        if normalized.endswith(suffixes):
            return (priority, "final_size_trim")
    if f"/{UPLOAD_BUNDLE_DERIVED_DIR_NAME}/{STARTER_PACK_DIR_NAME}/" in normalized:
        return (1, "final_size_trim")
    if f"/{STARTER_PACK_DIR_NAME}/" in normalized:
        return (2, "final_size_trim")
    return None


def _upload_bundle_trim_high_level_payload_rows(
    *,
    payload_rows: list[dict[str, Any]],
    target_payload_bytes: int,
    preserve_paths: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    current_payload_bytes = sum(
        _upload_bundle_payload_row_line_bytes(row)
        for row in payload_rows
        if isinstance(row, dict)
    )
    omitted_rows: list[dict[str, Any]] = []
    if current_payload_bytes <= max(int(target_payload_bytes), 0):
        return payload_rows, {
            "target_payload_bytes": max(int(target_payload_bytes), 0),
            "final_payload_bytes": current_payload_bytes,
            "omitted_artifact_count": 0,
            "omitted_bytes_estimate": 0,
            "omitted_artifacts": [],
        }

    candidate_rows: list[tuple[int, str, int, int]] = []
    for index, row in enumerate(payload_rows):
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").strip()
        if not path or path in preserve_paths:
            continue
        priority = _upload_bundle_high_level_trim_priority(path)
        if priority is None:
            continue
        candidate_rows.append(
            (
                int(priority[0]),
                path,
                _upload_bundle_payload_row_line_bytes(row),
                index,
            )
        )

    candidate_rows.sort(
        key=lambda item: (
            int(item[0]),
            -int(item[2]),
            str(item[1]),
        )
    )

    dropped_paths: set[str] = set()
    omitted_bytes_estimate = 0
    for priority, path, estimated_payload_bytes, _index in candidate_rows:
        if current_payload_bytes <= target_payload_bytes:
            break
        dropped_paths.add(path)
        current_payload_bytes -= estimated_payload_bytes
        omitted_bytes_estimate += estimated_payload_bytes
        omitted_rows.append(
            {
                "path": path,
                "reason": "final_size_trim",
                "trim_priority": priority,
                "estimated_payload_bytes": estimated_payload_bytes,
            }
        )

    if not dropped_paths:
        return payload_rows, {
            "target_payload_bytes": max(int(target_payload_bytes), 0),
            "final_payload_bytes": current_payload_bytes,
            "omitted_artifact_count": 0,
            "omitted_bytes_estimate": 0,
            "omitted_artifacts": [],
        }

    trimmed_rows = [
        row
        for row in payload_rows
        if isinstance(row, dict) and str(row.get("path") or "").strip() not in dropped_paths
    ]
    return trimmed_rows, {
        "target_payload_bytes": max(int(target_payload_bytes), 0),
        "final_payload_bytes": sum(
            _upload_bundle_payload_row_line_bytes(row) for row in trimmed_rows
        ),
        "omitted_artifact_count": len(omitted_rows),
        "omitted_bytes_estimate": omitted_bytes_estimate,
        "omitted_artifacts": omitted_rows,
    }


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
    policy_omitted_artifacts: list[dict[str, Any]] = []

    def _record_policy_omission(path: Path, *, reason: str) -> None:
        try:
            relative_path = str(path.relative_to(source_root).as_posix())
        except ValueError:
            relative_path = str(path)
        policy_omitted_artifacts.append(
            {
                "path": relative_path,
                "reason": reason,
                "source_bytes": _path_size(path),
            }
        )

    for run_dir in discovered_run_dirs:
        run_rel = ""
        try:
            run_rel = str(run_dir.relative_to(source_root).as_posix())
        except ValueError:
            run_rel = run_dir.name
        included_files: list[str] = []
        omitted_files: list[dict[str, Any]] = []
        run_manifest_payload = _upload_bundle_load_json_object(run_dir / "run_manifest.json")
        for file_name, required in GROUP_UPLOAD_BUNDLE_RUN_PRIORITY_FILES:
            candidate = run_dir / file_name
            if _append_if_allowed(candidate, required=required):
                included_files.append(file_name)
            elif candidate.is_file():
                omitted_files.append(
                    {
                        "path": file_name,
                        "reason": "artifact_budget_exceeded",
                        "source_bytes": _path_size(candidate),
                    }
                )
        pred_run_dir = _resolve_prediction_run_dir(run_dir, run_manifest_payload)
        pred_manifest = (
            _upload_bundle_load_json_object(pred_run_dir / "manifest.json")
            if pred_run_dir is not None
            else {}
        )
        prompt_budget_summary_path = _resolve_prompt_budget_summary_path(
            run_dir=run_dir,
            pred_run_dir=pred_run_dir,
            pred_manifest=pred_manifest,
        )
        if prompt_budget_summary_path is not None:
            if _append_if_allowed(prompt_budget_summary_path, required=False):
                try:
                    included_files.append(
                        str(prompt_budget_summary_path.relative_to(run_dir).as_posix())
                    )
                except ValueError:
                    included_files.append(str(prompt_budget_summary_path))
            else:
                try:
                    omitted_path = str(prompt_budget_summary_path.relative_to(run_dir).as_posix())
                except ValueError:
                    omitted_path = str(prompt_budget_summary_path)
                omitted_files.append(
                    {
                        "path": omitted_path,
                        "reason": "artifact_budget_exceeded",
                        "source_bytes": _path_size(prompt_budget_summary_path),
                    }
                )
        prompt_type_samples_path = _resolve_prompt_type_samples_path(
            run_dir,
            run_manifest_payload,
        )
        if prompt_type_samples_path is not None:
            try:
                prompt_type_samples_path.relative_to(source_root)
            except ValueError:
                prompt_type_samples_path = None
        if prompt_type_samples_path is not None:
            if _append_if_allowed(prompt_type_samples_path, required=False):
                try:
                    included_files.append(
                        str(prompt_type_samples_path.relative_to(run_dir).as_posix())
                    )
                except ValueError:
                    included_files.append(str(prompt_type_samples_path))
            else:
                try:
                    omitted_path = str(prompt_type_samples_path.relative_to(run_dir).as_posix())
                except ValueError:
                    omitted_path = str(prompt_type_samples_path)
                omitted_files.append(
                    {
                        "path": omitted_path,
                        "reason": "artifact_budget_exceeded",
                        "source_bytes": _path_size(prompt_type_samples_path),
                    }
                )
        knowledge_manifest_path = _resolve_knowledge_manifest_path(
            run_dir,
            run_manifest_payload,
        )
        if knowledge_manifest_path is not None:
            try:
                knowledge_manifest_path.relative_to(source_root)
            except ValueError:
                knowledge_manifest_path = None
        if knowledge_manifest_path is not None:
            if _append_if_allowed(knowledge_manifest_path, required=False):
                try:
                    included_files.append(
                        str(knowledge_manifest_path.relative_to(run_dir).as_posix())
                    )
                except ValueError:
                    included_files.append(str(knowledge_manifest_path))
            else:
                try:
                    omitted_path = str(knowledge_manifest_path.relative_to(run_dir).as_posix())
                except ValueError:
                    omitted_path = str(knowledge_manifest_path)
                omitted_files.append(
                    {
                        "path": omitted_path,
                        "reason": "artifact_budget_exceeded",
                        "source_bytes": _path_size(knowledge_manifest_path),
                    }
                )
        for relative_path in GROUP_UPLOAD_BUNDLE_RUN_CONTEXT_FILES:
            candidate = run_dir / relative_path
            if _append_if_allowed(candidate, required=False):
                included_files.append(relative_path)
            elif candidate.is_file():
                omitted_files.append(
                    {
                        "path": relative_path,
                        "reason": "artifact_budget_exceeded",
                        "source_bytes": _path_size(candidate),
                    }
                )
        # Keep full prompt logs in high-level bundles (deprioritized in navigation).
        full_prompt_log_path = _resolve_full_prompt_log_path(run_dir, run_manifest_payload)
        if full_prompt_log_path is not None and full_prompt_log_path.is_file():
            try:
                full_prompt_log_path.relative_to(source_root)
            except ValueError:
                full_prompt_log_path = None
        if full_prompt_log_path is not None:
            try:
                omitted_path = str(full_prompt_log_path.relative_to(run_dir).as_posix())
            except ValueError:
                omitted_path = str(full_prompt_log_path)
            omitted_files.append(
                {
                    "path": omitted_path,
                    "reason": "followup_only_heavy_prompt_log",
                    "source_bytes": _path_size(full_prompt_log_path),
                }
            )
            _record_policy_omission(
                full_prompt_log_path,
                reason="followup_only_heavy_prompt_log",
            )
        knowledge_prompt_path = _resolve_knowledge_prompt_path(run_dir)
        if knowledge_prompt_path is not None and knowledge_prompt_path.is_file():
            try:
                omitted_path = str(knowledge_prompt_path.relative_to(run_dir).as_posix())
            except ValueError:
                omitted_path = str(knowledge_prompt_path)
            omitted_files.append(
                {
                    "path": omitted_path,
                    "reason": "followup_only_heavy_prompt_context",
                    "source_bytes": _path_size(knowledge_prompt_path),
                }
            )
            _record_policy_omission(
                knowledge_prompt_path,
                reason="followup_only_heavy_prompt_context",
            )
        for heavy_name, omission_reason in (
            (WRONG_LABEL_FULL_CONTEXT_FILE_NAME, "followup_only_full_context_trace"),
            (PREPROCESS_TRACE_FAILURES_FILE_NAME, "followup_only_full_context_trace"),
        ):
            heavy_path = run_dir / heavy_name
            if not heavy_path.is_file():
                continue
            omitted_files.append(
                {
                    "path": heavy_name,
                    "reason": omission_reason,
                    "source_bytes": _path_size(heavy_path),
                }
            )
            _record_policy_omission(heavy_path, reason=omission_reason)
        included_run_rows.append(
            {
                "run_dir": run_rel,
                "included_files": included_files,
                "omitted_files": omitted_files,
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
        "policy_omitted_artifacts": policy_omitted_artifacts,
        "policy_omitted_artifact_count": len(policy_omitted_artifacts),
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


def _upload_bundle_optional_artifact_status(*, path: Path | None, enabled: bool) -> str:
    if isinstance(path, Path) and path.is_file():
        return "written"
    return "missing" if enabled else "not_applicable"


def _upload_bundle_relative_path_within_root(
    *,
    source_root: Path,
    candidate: Path | None,
) -> str | None:
    if not isinstance(candidate, Path):
        return None
    try:
        return str(candidate.resolve().relative_to(source_root).as_posix())
    except Exception:  # noqa: BLE001
        return None


def _upload_bundle_derived_run_artifact_path(*, output_subdir: str, file_name: str) -> str:
    normalized_subdir = str(output_subdir or "").strip().strip("/")
    normalized_subdir = normalized_subdir or "unknown_run"
    return f"{UPLOAD_BUNDLE_DERIVED_DIR_NAME}/runs/{normalized_subdir}/{file_name}"


def _upload_bundle_build_knowledge_summary(
    *,
    source_root: Path,
    discovered_run_dirs: list[Path],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    locator_rows: list[dict[str, Any]] = []
    enabled_run_count = 0
    runs_with_prompt_samples = 0
    runs_with_knowledge_manifest = 0
    total_knowledge_call_count = 0
    shards_written_total = 0
    outputs_parsed_total = 0
    snippets_written_total = 0

    for run_dir in discovered_run_dirs:
        run_manifest = _upload_bundle_load_json_object(run_dir / "run_manifest.json")
        run_id = str(run_manifest.get("run_id") or run_dir.name).strip() or run_dir.name
        try:
            output_subdir = str(run_dir.resolve().relative_to(source_root).as_posix())
        except Exception:  # noqa: BLE001
            output_subdir = run_dir.name

        run_config = run_manifest.get("run_config")
        run_config = run_config if isinstance(run_config, dict) else {}
        prediction_run_config = run_config.get("prediction_run_config")
        prediction_run_config = (
            prediction_run_config if isinstance(prediction_run_config, dict) else {}
        )
        llm_knowledge_pipeline = str(
            prediction_run_config.get("llm_knowledge_pipeline")
            or run_config.get("llm_knowledge_pipeline")
            or ""
        ).strip()

        pred_run_dir = _resolve_prediction_run_dir(run_dir, run_manifest)
        pred_manifest = (
            _upload_bundle_load_json_object(pred_run_dir / "manifest.json")
            if pred_run_dir is not None
            else {}
        )
        processed_output_dir = _resolve_processed_output_run_dir(run_dir, run_manifest)
        knowledge_outputs: dict[str, Any] = {}
        if processed_output_dir is not None:
            for candidate in (
                processed_output_dir / "09_knowledge_outputs.json",
                processed_output_dir / "09_nonrecipe_finalize_status.json",
            ):
                if not candidate.is_file():
                    continue
                knowledge_outputs = _upload_bundle_load_json_object(candidate)
                break
        llm_payload = (
            pred_manifest.get("llm_codex_farm") if isinstance(pred_manifest, dict) else {}
        )
        llm_payload = llm_payload if isinstance(llm_payload, dict) else {}
        knowledge_payload = llm_payload.get("knowledge")
        knowledge_payload = knowledge_payload if isinstance(knowledge_payload, dict) else {}
        manifest_knowledge_counts = (
            knowledge_payload.get("counts")
            if isinstance(knowledge_payload.get("counts"), dict)
            else {}
        )
        outputs_knowledge_counts = (
            knowledge_outputs.get("counts")
            if isinstance(knowledge_outputs.get("counts"), dict)
            else {}
        )
        knowledge_counts = (
            manifest_knowledge_counts if manifest_knowledge_counts else outputs_knowledge_counts
        )

        prompt_budget_summary = _upload_bundle_load_prompt_budget_summary(
            run_dir=run_dir,
            pred_run_dir=pred_run_dir,
            pred_manifest=pred_manifest,
        )
        prompt_budget_by_stage = (
            prompt_budget_summary.get("by_stage")
            if isinstance(prompt_budget_summary, dict)
            else {}
        )
        prompt_budget_by_stage = (
            prompt_budget_by_stage if isinstance(prompt_budget_by_stage, dict) else {}
        )
        knowledge_budget = (
            prompt_budget_by_stage.get("knowledge")
            if isinstance(prompt_budget_by_stage.get("knowledge"), dict)
            else {}
        )
        knowledge_call_count = _coerce_int(knowledge_budget.get("call_count"))
        knowledge_token_total = _coerce_int(knowledge_budget.get("tokens_total"))

        prompt_samples_path = _resolve_prompt_type_samples_path(run_dir, run_manifest)
        knowledge_prompt_path = _resolve_knowledge_prompt_path(run_dir)
        knowledge_manifest_path = _resolve_knowledge_manifest_path(run_dir, run_manifest)
        prompt_budget_path = _resolve_prompt_budget_summary_path(
            run_dir=run_dir,
            pred_run_dir=pred_run_dir,
            pred_manifest=pred_manifest,
        )
        knowledge_manifest_locator_path = _upload_bundle_relative_path_within_root(
            source_root=source_root,
            candidate=knowledge_manifest_path,
        )
        knowledge_manifest_source_path: Path | None = None
        if knowledge_manifest_locator_path is None and isinstance(knowledge_manifest_path, Path):
            knowledge_manifest_locator_path = _upload_bundle_derived_run_artifact_path(
                output_subdir=output_subdir,
                file_name=KNOWLEDGE_MANIFEST_FILE_NAME,
            )
            knowledge_manifest_source_path = knowledge_manifest_path

        knowledge_enabled = bool(
            _coerce_bool(knowledge_payload.get("enabled"))
            or _coerce_bool(knowledge_outputs.get("enabled"))
        )
        enabled = bool(
            knowledge_enabled
            or (knowledge_call_count is not None and knowledge_call_count > 0)
            or isinstance(knowledge_manifest_path, Path)
            or llm_knowledge_pipeline not in {"", "off", "none"}
        )

        if enabled:
            enabled_run_count += 1
        if isinstance(prompt_samples_path, Path) and prompt_samples_path.is_file():
            runs_with_prompt_samples += 1
        if isinstance(knowledge_manifest_path, Path) and knowledge_manifest_path.is_file():
            runs_with_knowledge_manifest += 1
        total_knowledge_call_count += int(knowledge_call_count or 0)
        shards_written_total += int(_coerce_int(knowledge_counts.get("shards_written")) or 0)
        outputs_parsed_total += int(_coerce_int(knowledge_counts.get("outputs_parsed")) or 0)
        snippets_written_total += int(_coerce_int(knowledge_counts.get("snippets_written")) or 0)

        rows.append(
            {
                "run_id": run_id,
                "output_subdir": output_subdir,
                "enabled": enabled,
                "llm_knowledge_pipeline": llm_knowledge_pipeline or "off",
                "pipeline": str(knowledge_payload.get("pipeline") or "").strip(),
                "pipeline_id": str(knowledge_payload.get("pipeline_id") or "").strip(),
                "knowledge_call_count": int(knowledge_call_count or 0),
                "knowledge_token_total": int(knowledge_token_total or 0),
                "shards_written": int(_coerce_int(knowledge_counts.get("shards_written")) or 0),
                "outputs_parsed": int(_coerce_int(knowledge_counts.get("outputs_parsed")) or 0),
                "snippets_written": int(_coerce_int(knowledge_counts.get("snippets_written")) or 0),
                "prompt_samples_status": _upload_bundle_optional_artifact_status(
                    path=prompt_samples_path,
                    enabled=enabled,
                ),
                "prompt_knowledge_status": _upload_bundle_optional_artifact_status(
                    path=knowledge_prompt_path,
                    enabled=enabled,
                ),
                "knowledge_manifest_status": _upload_bundle_optional_artifact_status(
                    path=knowledge_manifest_path,
                    enabled=enabled,
                ),
                "prompt_budget_summary_status": _upload_bundle_optional_artifact_status(
                    path=prompt_budget_path,
                    enabled=enabled,
                ),
            }
        )
        locator_rows.append(
            {
                "run_id": run_id,
                "output_subdir": output_subdir,
                "prompt_samples_path": _upload_bundle_relative_path_within_root(
                    source_root=source_root,
                    candidate=prompt_samples_path,
                ),
                "prompt_knowledge_path": _upload_bundle_relative_path_within_root(
                    source_root=source_root,
                    candidate=knowledge_prompt_path,
                ),
                "prompt_budget_summary_path": _upload_bundle_relative_path_within_root(
                    source_root=source_root,
                    candidate=prompt_budget_path,
                ),
                "knowledge_manifest_path": knowledge_manifest_locator_path,
                "knowledge_manifest_source_path": knowledge_manifest_source_path,
            }
        )

    summary = {
        "schema_version": "upload_bundle_knowledge.v1",
        "run_count": len(rows),
        "enabled_run_count": enabled_run_count,
        "runs_with_prompt_samples": runs_with_prompt_samples,
        "runs_with_knowledge_manifest": runs_with_knowledge_manifest,
        "total_knowledge_call_count": total_knowledge_call_count,
        "shards_written_total": shards_written_total,
        "outputs_parsed_total": outputs_parsed_total,
        "snippets_written_total": snippets_written_total,
        "rows": rows,
    }
    return summary, locator_rows


def _upload_bundle_existing_output_adapter_helpers() -> ExistingOutputAdapterHelpers:
    return ExistingOutputAdapterHelpers(
        load_json_object=_upload_bundle_load_json_object,
        iter_jsonl=_iter_jsonl,
        load_recipe_triage_rows=_upload_bundle_load_recipe_triage_rows,
        discover_run_dirs=_discover_run_dirs,
        build_run_record_from_existing_run=lambda run_dir: _build_run_record_from_existing_run(
            run_dir=run_dir
        ),
        build_comparison_summary=_build_comparison_summary,
        coerce_int=_coerce_int,
        source_file_name=_source_file_name,
        source_key=_source_key,
        select_starter_pack_recipe_cases=_select_starter_pack_recipe_cases,
        build_selected_recipe_packets=_build_selected_recipe_packets,
    )


def _upload_bundle_build_source_model(*, source_root: Path) -> UploadBundleSourceModel:
    return build_upload_bundle_source_model_from_existing_root(
        source_root=source_root,
        helpers=_upload_bundle_existing_output_adapter_helpers(),
        default_excerpt_limit=DEFAULT_EXCERPT_LIMIT,
        default_targeted_prompt_cases=DEFAULT_TARGETED_PROMPT_CASES,
        per_recipe_breakdown_file_name=PER_RECIPE_BREAKDOWN_FILE_NAME,
        changed_lines_file_name=CHANGED_LINES_FILE_NAME,
        starter_pack_dir_name=STARTER_PACK_DIR_NAME,
        starter_call_inventory_file_name=STARTER_PACK_CALL_INVENTORY_FILE_NAME,
        starter_selected_packets_file_name=STARTER_PACK_SELECTED_PACKETS_FILE_NAME,
        starter_manifest_file_name=STARTER_PACK_MANIFEST_FILE_NAME,
    )


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


def _upload_bundle_blocks_from_evidence_rows(value: Any) -> tuple[dict[int, str], list[int]]:
    if not isinstance(value, list):
        return {}, []
    blocks_by_index: dict[int, str] = {}
    ordered_indices: list[int] = []
    for row in value:
        index: int | None = None
        text = ""
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            index = _coerce_int(row[0])
            text = str(row[1] or "")
        elif isinstance(row, dict):
            index = _coerce_int(row.get("index"))
            text = str(row.get("text") or "")
        if index is None or index < 0:
            continue
        blocks_by_index[int(index)] = text
        ordered_indices.append(int(index))
    return blocks_by_index, sorted(set(ordered_indices))


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


def _upload_bundle_project_correction_recipe_labels(
    *,
    correction_input: dict[str, Any],
    correction_output: dict[str, Any],
) -> dict[int, str]:
    blocks_by_index, ordered_indices = _upload_bundle_blocks_from_evidence_rows(
        correction_input.get("evidence_rows")
    )
    if not blocks_by_index:
        return {}
    canonical_recipe = correction_output.get("canonical_recipe")
    if not isinstance(canonical_recipe, dict):
        canonical_recipe = {}

    ingredient_indices = _upload_bundle_collect_text_matches(
        targets=_upload_bundle_extract_text_values(canonical_recipe.get("ingredients")),
        blocks_by_index=blocks_by_index,
    )
    instruction_indices = _upload_bundle_collect_text_matches(
        targets=_upload_bundle_extract_text_values(canonical_recipe.get("steps")),
        blocks_by_index=blocks_by_index,
    )
    notes_indices = _upload_bundle_collect_text_matches(
        targets=[
            str(canonical_recipe.get("description") or ""),
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
        title=str(canonical_recipe.get("title") or ""),
        candidate_indices=ordered_indices,
        blocks_by_index=blocks_by_index,
    )
    if title_index is not None:
        labels_by_index[int(title_index)] = "RECIPE_TITLE"

    yield_values = [
        str(canonical_recipe.get("recipe_yield") or ""),
    ]
    normalized_yields = [
        _upload_bundle_normalize_match_text(value)
        for value in yield_values
        if _upload_bundle_normalize_match_text(value)
    ]
    time_values: list[str] = []
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


def _upload_bundle_project_final_recipe_labels(
    *,
    correction_input: dict[str, Any],
    correction_output: dict[str, Any] | None,
    final_output: dict[str, Any] | None,
) -> dict[int, str]:
    blocks_by_index, ordered_indices = _upload_bundle_blocks_from_evidence_rows(
        correction_input.get("evidence_rows")
    )
    if not blocks_by_index:
        return {}

    labels_by_index: dict[int, str] = {}
    title_value = ""
    ingredient_targets: list[str] = []
    instruction_targets: list[str] = []

    if isinstance(final_output, dict):
        draft_payload = final_output.get("draft_v1")
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

    if not title_value and isinstance(correction_output, dict):
        canonical_recipe = correction_output.get("canonical_recipe")
        if isinstance(canonical_recipe, dict):
            title_value = str(canonical_recipe.get("title") or "")
        if not ingredient_targets:
            ingredient_targets = _upload_bundle_extract_text_values(
                canonical_recipe.get("ingredients") if isinstance(canonical_recipe, dict) else None
            )
        if not instruction_targets:
            instruction_targets = _upload_bundle_extract_text_values(
                canonical_recipe.get("steps") if isinstance(canonical_recipe, dict) else None
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


def _upload_bundle_collect_stage_reports_for_run(
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

    correction_inputs: dict[str, dict[str, Any]] = {}
    correction_outputs: dict[str, dict[str, Any]] = {}
    final_outputs: dict[str, dict[str, Any]] = {}
    for llm_run_dir in llm_run_dirs:
        correction_in_dir = (
            llm_run_dir / stage_artifact_stem("recipe_refine") / "in"
        )
        correction_out_dir = (
            llm_run_dir / stage_artifact_stem("recipe_refine") / "out"
        )
        final_out_dir = llm_run_dir / stage_artifact_stem("recipe_build_final") / "out"

        for path in sorted(correction_in_dir.glob("*.json")):
            payload = _upload_bundle_load_json_object(path)
            recipe_id = str(payload.get("recipe_id") or "").strip()
            if recipe_id:
                correction_inputs[recipe_id] = payload
        for path in sorted(correction_out_dir.glob("*.json")):
            payload = _upload_bundle_load_json_object(path)
            recipe_id = str(payload.get("recipe_id") or "").strip()
            if recipe_id:
                correction_outputs[recipe_id] = payload
        for path in sorted(final_out_dir.glob("*.json")):
            payload = _upload_bundle_load_json_object(path)
            recipe_id = str(payload.get("recipe_id") or "").strip()
            if recipe_id:
                final_outputs[recipe_id] = payload

    reports: dict[str, dict[str, Any]] = {}

    correction_prediction = dict(default_prediction)
    correction_label_hits = 0
    for recipe_id, correction_output in correction_outputs.items():
        correction_input = correction_inputs.get(recipe_id)
        if not isinstance(correction_input, dict):
            continue
        projected_labels = _upload_bundle_project_correction_recipe_labels(
            correction_input=correction_input,
            correction_output=correction_output,
        )
        if not projected_labels:
            continue
        for index, label in projected_labels.items():
            if index not in correction_prediction:
                continue
            correction_prediction[index] = str(label)
            if str(label) != "OTHER":
                correction_label_hits += 1
    if correction_label_hits > 0:
        try:
            reports["recipe_refine"] = compute_block_metrics(
                gold_labels,
                correction_prediction,
            )
        except Exception:  # noqa: BLE001
            reports["recipe_refine"] = {}

    final_prediction = dict(default_prediction)
    final_label_hits = 0
    recipe_ids = sorted(
        set(correction_inputs.keys()) | set(correction_outputs.keys()) | set(final_outputs.keys())
    )
    for recipe_id in recipe_ids:
        correction_input = correction_inputs.get(recipe_id)
        if not isinstance(correction_input, dict):
            continue
        projected_labels = _upload_bundle_project_final_recipe_labels(
            correction_input=correction_input,
            correction_output=correction_outputs.get(recipe_id),
            final_output=final_outputs.get(recipe_id),
        )
        if not projected_labels:
            continue
        for index, label in projected_labels.items():
            if index not in final_prediction:
                continue
            final_prediction[index] = str(label)
            if str(label) != "OTHER":
                final_label_hits += 1
    if final_label_hits > 0:
        try:
            reports["recipe_build_final"] = compute_block_metrics(
                gold_labels,
                final_prediction,
            )
        except Exception:  # noqa: BLE001
            reports["recipe_build_final"] = {}

    return reports


def _upload_bundle_collect_stage_per_label_metrics(
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
        reports_by_run[run_id] = _upload_bundle_collect_stage_reports_for_run(
            run_dir=run_dir,
            gold_cache=gold_cache,
        )

    output: dict[str, Any] = {}
    for stage_key in ("recipe_refine", "recipe_build_final"):
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
        stage_key = str(call_row.get("stage_key") or "").strip()
        if not recipe_id or stage_key not in {
            "recipe_build_intermediate",
            "recipe_refine",
            "recipe_build_final",
        }:
            continue
        retry_counts[(run_id, recipe_id, stage_key)] += 1

    rows: list[dict[str, Any]] = []
    for triage_row in recipe_triage_rows:
        recipe_id = str(triage_row.get("recipe_id") or "").strip()
        if not recipe_id:
            continue
        run_id = str(triage_row.get("codex_run_id") or triage_row.get("run_id") or "").strip()
        build_intermediate_status = str(
            triage_row.get("build_intermediate_status") or ""
        ).strip()
        correction_status = str(triage_row.get("correction_status") or "").strip()
        build_final_status = str(triage_row.get("build_final_status") or "").strip()
        final_mapping_reason = str(triage_row.get("final_mapping_reason") or "").strip()
        delta = _coerce_float(triage_row.get("delta_codex_minus_baseline"))
        build_intermediate_call_id = str(
            triage_row.get("build_intermediate_call_id") or ""
        ).strip()
        correction_call_id = str(triage_row.get("correction_call_id") or "").strip()
        build_final_call_id = str(triage_row.get("build_final_call_id") or "").strip()

        stage_rows = [
            {
                "stage_key": "recipe_build_intermediate",
                "call_id": build_intermediate_call_id,
                "status": build_intermediate_status or "ok",
                "reason": "",
                "warning_buckets": [],
                "fallback_target": None,
                "call_observed": bool(build_intermediate_call_id),
                "output_signal": bool(
                    int(
                        _coerce_int(
                            triage_row.get("build_intermediate_selected_block_count")
                        )
                        or 0
                    )
                    > 0
                ),
                "empty_output_signal": False,
            },
            {
                "stage_key": "recipe_refine",
                "call_id": correction_call_id,
                "status": correction_status or "unknown",
                "reason": "",
                "warning_buckets": _coerce_str_list(
                    triage_row.get("correction_warning_buckets")
                ),
                "fallback_target": None,
                "call_observed": bool(correction_call_id),
                "output_signal": bool(
                    int(_coerce_int(triage_row.get("correction_input_block_count")) or 0) > 0
                    or int(_coerce_int(triage_row.get("correction_ingredient_count")) or 0) > 0
                    or int(_coerce_int(triage_row.get("correction_step_count")) or 0) > 0
                    or int(_coerce_int(triage_row.get("correction_mapping_count")) or 0) > 0
                ),
                "empty_output_signal": bool(triage_row.get("correction_empty_output")),
            },
            {
                "stage_key": "recipe_build_final",
                "call_id": build_final_call_id,
                "status": build_final_status or "unknown",
                "reason": final_mapping_reason,
                "warning_buckets": [],
                "fallback_target": None,
                "call_observed": bool(build_final_call_id),
                "output_signal": bool(
                    int(_coerce_int(triage_row.get("final_recipe_step_count")) or 0) > 0
                    or int(_coerce_int(triage_row.get("final_recipe_mapping_count")) or 0) > 0
                ),
                "empty_output_signal": bool(triage_row.get("final_recipe_empty_mapping")),
            },
            {
                "stage_key": "final_result",
                "call_id": "",
                "status": (
                    "regressed"
                    if delta is not None and delta < 0
                    else ("ok" if delta is not None else "unknown")
                ),
                "reason": (
                    f"delta_codex_minus_baseline={_serialize_float(delta)}"
                    if delta is not None
                    else ""
                ),
                "warning_buckets": [],
                "fallback_target": None,
                "call_observed": bool(correction_call_id or build_final_call_id),
                "output_signal": bool(
                    int(_coerce_int(triage_row.get("final_recipe_step_count")) or 0) > 0
                    or int(_coerce_int(triage_row.get("final_recipe_mapping_count")) or 0) > 0
                    or int(_coerce_int(triage_row.get("correction_step_count")) or 0) > 0
                    or int(_coerce_int(triage_row.get("correction_mapping_count")) or 0) > 0
                ),
                "empty_output_signal": bool(
                    triage_row.get("final_recipe_empty_mapping")
                    or triage_row.get("correction_empty_output")
                ),
            },
        ]

        for stage_row in stage_rows:
            stage_key = str(stage_row["stage_key"])
            retry_attempted = (
                retry_counts[(run_id, recipe_id, stage_key)] > 1
                if stage_key in {
                    "recipe_build_intermediate",
                    "recipe_refine",
                    "recipe_build_final",
                }
                else False
            )
            parse_validation_error = _upload_bundle_parse_validation_error(
                str(stage_row["reason"] or "")
            )
            status_text = str(stage_row["status"] or "").strip()
            stage_semantics = "recorded_status"
            stage_semantics_explanation = (
                "Stage status came from recorded runtime/manifest diagnostics."
            )
            if stage_key == "final_result":
                if delta is not None:
                    stage_semantics = "scored_result"
                    stage_semantics_explanation = (
                        "Final benchmark delta was computed for this recipe."
                    )
                elif bool(stage_row["call_observed"]) or bool(stage_row["output_signal"]):
                    stage_semantics = "projection_or_scoring_gap"
                    stage_semantics_explanation = (
                        "Recipe-stage execution was observed, but the final benchmark result "
                        "could not be projected/scored."
                    )
                else:
                    stage_semantics = "runtime_missing_or_unobserved"
                    stage_semantics_explanation = (
                        "No recipe-stage execution or scored result was observed for this recipe."
                    )
            elif status_text.lower() in {"", "unknown"}:
                if bool(stage_row["empty_output_signal"]) and (
                    bool(stage_row["call_observed"]) or bool(stage_row["output_signal"])
                ):
                    if stage_key == "recipe_refine":
                        stage_semantics = "empty_output_without_manifest_status"
                        stage_semantics_explanation = (
                            "Recipe correction execution was observed, but the parsed correction "
                            "payload was empty and no manifest/runtime status was recorded."
                        )
                    else:
                        stage_semantics = "empty_output_signal"
                        stage_semantics_explanation = (
                            "Stage execution was observed, but the available output signal is empty."
                        )
                elif bool(stage_row["call_observed"]) or bool(stage_row["output_signal"]):
                    if stage_key == "recipe_refine":
                        stage_semantics = "nonempty_output_without_manifest_status"
                        stage_semantics_explanation = (
                            "Recipe correction execution was observed and the parsed correction "
                            "payload was non-empty, but no manifest/runtime status was recorded."
                        )
                    else:
                        stage_semantics = "projection_or_scoring_gap"
                        stage_semantics_explanation = (
                            "Stage execution was observed, but the bundle could not project/score "
                            "that stage into a concrete status."
                        )
                else:
                    stage_semantics = "runtime_missing_or_unobserved"
                    stage_semantics_explanation = (
                        "The bundle has no runtime evidence that this stage executed."
                    )
            elif bool(stage_row["empty_output_signal"]):
                stage_semantics = "recorded_status_with_empty_output_signal"
                stage_semantics_explanation = (
                    "Stage status was recorded, and the output signal is empty."
                )
            rows.append(
                {
                    "source_key": str(triage_row.get("source_key") or ""),
                    "source_file": str(triage_row.get("source_file") or ""),
                    "codex_run_id": run_id,
                    "baseline_run_id": str(triage_row.get("baseline_run_id") or ""),
                    "recipe_id": recipe_id,
                    "short_title": str(triage_row.get("short_title") or ""),
                    "stage_key": stage_key,
                    "call_id": str(stage_row["call_id"] or ""),
                    "status": str(stage_row["status"] or "unknown"),
                    "reason": str(stage_row["reason"] or ""),
                    "warning_buckets": list(stage_row["warning_buckets"] or []),
                    "retry_attempted": bool(retry_attempted),
                    "fallback_target": stage_row["fallback_target"],
                    "parse_validation_error": parse_validation_error,
                    "call_observed": bool(stage_row["call_observed"]),
                    "output_signal": bool(stage_row["output_signal"]),
                    "empty_output_signal": bool(stage_row["empty_output_signal"]),
                    "status_semantics": stage_semantics,
                    "status_semantics_explanation": stage_semantics_explanation,
                }
            )

    stage_status_counts: dict[str, Counter[str]] = defaultdict(Counter)
    stage_semantics_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        stage_status_counts[str(row["stage_key"])][str(row["status"])] += 1
        stage_semantics_counts[str(row["stage_key"])][
            str(row.get("status_semantics") or "")
        ] += 1
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
            "stage_status_counts": {
                stage_key: _counter_to_sorted_dict(counter)
                for stage_key, counter in sorted(stage_status_counts.items())
            },
            "stage_semantics_counts": {
                stage_key: _counter_to_sorted_dict(counter)
                for stage_key, counter in sorted(stage_semantics_counts.items())
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


def _upload_bundle_call_inventory_stage_included(stage_key: str | None) -> bool:
    normalized = str(stage_key or "").strip()
    return bool(normalized) and (
        normalized == "line_role" or normalized in LLM_STAGE_MAP
    )


def _upload_bundle_call_inventory_stage_rank(stage_key: str | None) -> int:
    normalized = str(stage_key or "").strip()
    if normalized == "line_role":
        return -1
    return int(LLM_STAGE_MAP.get(normalized, {}).get("sort_order") or 99)


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


def _upload_bundle_iter_unique_run_dirs(
    *,
    run_dirs: list[Path] | None = None,
    run_dir_by_id: dict[str, Path] | None = None,
) -> list[Path]:
    candidates: list[Path] = []
    if isinstance(run_dirs, list):
        candidates.extend([item for item in run_dirs if isinstance(item, Path)])
    if isinstance(run_dir_by_id, dict):
        candidates.extend([item for item in run_dir_by_id.values() if isinstance(item, Path)])
    unique: list[Path] = []
    seen: set[str] = set()
    for run_dir in candidates:
        key = str(run_dir.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(run_dir)
    return unique


def _upload_bundle_normalize_runtime_stage_key(stage_key: str | None) -> str:
    rendered = str(stage_key or "").strip()
    if rendered == "recipe_correction":
        return "recipe_refine"
    if rendered == "knowledge":
        return "nonrecipe_finalize"
    return rendered


def _upload_bundle_collect_call_runtime_map(
    *,
    run_dirs: list[Path] | None = None,
    run_dir_by_id: dict[str, Path] | None = None,
) -> dict[tuple[str, str, str, str, str], dict[str, Any]]:
    runtime_by_key: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for run_dir in _upload_bundle_iter_unique_run_dirs(
        run_dirs=run_dirs,
        run_dir_by_id=run_dir_by_id,
    ):
        run_manifest_path = run_dir / "run_manifest.json"
        if not run_manifest_path.is_file():
            continue
        run_manifest = _upload_bundle_load_json_object(run_manifest_path)
        manifest_run_id = str(run_manifest.get("run_id") or run_dir.name).strip() or run_dir.name
        source_payload = (
            run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
        )
        source_path = source_payload.get("path") if isinstance(source_payload, dict) else None
        source_hash = source_payload.get("source_hash") if isinstance(source_payload, dict) else None
        source_file = _source_file_name(source_path if isinstance(source_path, str) else None)
        source_key = _source_key(
            source_hash if isinstance(source_hash, str) else None,
            source_file,
        )
        full_prompt_path = _resolve_full_prompt_log_path(run_dir, run_manifest)
        if full_prompt_path is None or not full_prompt_path.is_file():
            continue
        for prompt_row in _iter_jsonl(full_prompt_path):
            stage_key = _prompt_row_stage_key(prompt_row)
            call_id = str(prompt_row.get("call_id") or "").strip()
            recipe_id = _prompt_row_recipe_id(prompt_row)
            if (
                not _upload_bundle_call_inventory_stage_included(stage_key)
                or not call_id
            ):
                continue
            row_run_id = str(prompt_row.get("run_id") or manifest_run_id).strip() or manifest_run_id
            key = (
                source_key,
                row_run_id,
                recipe_id,
                stage_key,
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
    by_stage: dict[str, dict[str, Any]],
    total_tokens: int | None,
) -> dict[str, float | None]:
    fields: dict[str, float | None] = {}
    for stage_key in sorted(by_stage, key=_prompt_category_sort_key):
        share_key = f"{stage_key}_token_share"
        stage_payload = by_stage.get(stage_key)
        stage_payload = stage_payload if isinstance(stage_payload, dict) else {}
        stage_tokens = _coerce_int(stage_payload.get("total_tokens"))
        if (
            total_tokens is None
            or total_tokens <= 0
            or stage_tokens is None
            or stage_tokens < 0
        ):
            fields[share_key] = None
            continue
        fields[share_key] = round(float(stage_tokens) / float(total_tokens), 4)
    return fields


def _upload_bundle_load_prompt_budget_summary(
    *,
    run_dir: Path,
    pred_run_dir: Path | None,
    pred_manifest: dict[str, Any],
) -> dict[str, Any] | None:
    candidate = _resolve_prompt_budget_summary_path(
        run_dir=run_dir,
        pred_run_dir=pred_run_dir,
        pred_manifest=pred_manifest,
    )
    if isinstance(candidate, Path):
        if not candidate.is_file():
            return None
        payload = _upload_bundle_load_json_object(candidate)
        if isinstance(payload.get("by_stage"), dict):
            return payload
    return None


def _upload_bundle_build_call_runtime_inventory_from_prediction_manifest(
    *,
    run_dirs: list[Path] | None = None,
    run_dir_by_id: dict[str, Path] | None = None,
) -> dict[str, Any] | None:
    aggregate_by_stage: dict[str, dict[str, Any]] = {}
    used_prompt_budget_summary = False
    for run_dir in _upload_bundle_iter_unique_run_dirs(
        run_dirs=run_dirs,
        run_dir_by_id=run_dir_by_id,
    ):
        run_manifest_path = run_dir / "run_manifest.json"
        if not run_manifest_path.is_file():
            continue
        run_manifest = _upload_bundle_load_json_object(run_manifest_path)
        pred_run_dir = _resolve_prediction_run_dir(run_dir, run_manifest)
        pred_manifest_path = pred_run_dir / "manifest.json" if pred_run_dir is not None else None
        pred_manifest = (
            _upload_bundle_load_json_object(pred_manifest_path)
            if isinstance(pred_manifest_path, Path) and pred_manifest_path.is_file()
            else {}
        )
        prompt_budget_summary = _upload_bundle_load_prompt_budget_summary(
            run_dir=run_dir,
            pred_run_dir=pred_run_dir,
            pred_manifest=pred_manifest,
        )
        if isinstance(prompt_budget_summary, dict):
            by_stage_payload = prompt_budget_summary.get("by_stage")
            if isinstance(by_stage_payload, dict) and by_stage_payload:
                used_prompt_budget_summary = True
                for pass_name, pass_payload in sorted(by_stage_payload.items()):
                    if not isinstance(pass_payload, dict):
                        continue
                    normalized_stage_key = _upload_bundle_normalize_runtime_stage_key(pass_name)
                    bucket = aggregate_by_stage.setdefault(
                        normalized_stage_key,
                        {
                            "call_count": 0,
                            "calls_known": False,
                            "duration_total_ms": 0,
                            "duration_known": False,
                            "tokens_total": 0,
                            "tokens_known": False,
                        },
                    )
                    call_count = _coerce_int(pass_payload.get("call_count"))
                    if call_count is not None:
                        bucket["call_count"] += max(int(call_count), 0)
                        bucket["calls_known"] = True
                    duration_total_ms = _coerce_int(pass_payload.get("duration_total_ms"))
                    if duration_total_ms is not None:
                        bucket["duration_total_ms"] += max(int(duration_total_ms), 0)
                        bucket["duration_known"] = True
                    tokens_total = _coerce_int(pass_payload.get("tokens_total"))
                    if tokens_total is not None:
                        bucket["tokens_total"] += max(int(tokens_total), 0)
                        bucket["tokens_known"] = True
                continue
        if pred_run_dir is None or not isinstance(pred_manifest_path, Path) or not pred_manifest_path.is_file():
            continue
        llm_payload = (
            pred_manifest.get("llm_codex_farm") if isinstance(pred_manifest, dict) else {}
        )
        llm_payload = llm_payload if isinstance(llm_payload, dict) else {}
        knowledge_payload = llm_payload.get("knowledge")
        knowledge_payload = knowledge_payload if isinstance(knowledge_payload, dict) else {}
        process_runs = llm_payload.get("process_runs")
        process_runs = process_runs if isinstance(process_runs, dict) else {}
        process_payload_by_stage = {
            "recipe_correction": (
                process_runs.get("recipe_correction")
                or process_runs.get("recipe_refine")
            ),
            "nonrecipe_finalize": (
                process_runs.get("nonrecipe_finalize")
                or (
                    knowledge_payload.get("process_run")
                    if isinstance(knowledge_payload.get("process_run"), dict)
                    else None
                )
            ),
        }
        for stage_key, pass_payload in process_payload_by_stage.items():
            pass_payload = pass_payload if isinstance(pass_payload, dict) else {}
            telemetry_report = pass_payload.get("telemetry_report")
            telemetry_report = telemetry_report if isinstance(telemetry_report, dict) else {}
            summary = telemetry_report.get("summary")
            if not isinstance(summary, dict):
                continue
            normalized_stage_key = _upload_bundle_normalize_runtime_stage_key(stage_key)
            bucket = aggregate_by_stage.setdefault(
                normalized_stage_key,
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

    if not aggregate_by_stage:
        return None

    by_stage: dict[str, dict[str, Any]] = {}
    for pass_name in sorted(aggregate_by_stage.keys()):
        bucket = aggregate_by_stage.get(pass_name)
        if not isinstance(bucket, dict):
            continue
        call_count = int(bucket.get("call_count") or 0)
        calls_known = bool(bucket.get("calls_known"))
        duration_known = bool(bucket.get("duration_known"))
        tokens_known = bool(bucket.get("tokens_known"))
        duration_total_ms = (
            int(bucket.get("duration_total_ms") or 0) if duration_known else None
        )
        by_stage[pass_name] = {
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

    total_calls = int(sum(int(payload.get("call_count") or 0) for payload in by_stage.values()))
    total_calls_with_runtime = int(
        sum(int(payload.get("calls_with_runtime") or 0) for payload in by_stage.values())
    )
    duration_totals = [
        int(bucket.get("duration_total_ms") or 0)
        for bucket in aggregate_by_stage.values()
        if bool(bucket.get("duration_known"))
    ]
    total_duration_ms = int(sum(duration_totals)) if duration_totals else None
    token_totals = [
        _coerce_int(payload.get("total_tokens"))
        for payload in by_stage.values()
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
                "No per-call token telemetry available; aggregate stage totals cannot be "
                "reliably cost-estimated per call."
            ),
        },
        "by_stage": by_stage,
        "runtime_source": (
            "prediction_run_prompt_budget_summary"
            if used_prompt_budget_summary
            else "prediction_run_manifest_telemetry"
        ),
    }
    summary.update(
        _upload_bundle_token_share_fields(by_stage=by_stage, total_tokens=total_tokens)
    )
    return {
        "summary": summary,
        "by_source": [],
        "top_slowest_calls": [],
        "top_token_calls": [],
        "top_cost_calls": [],
        "top_estimated_cost_calls": [],
    }


def _upload_bundle_runtime_inventory_needs_fallback(
    *,
    row_summary: dict[str, Any],
    fallback_summary: dict[str, Any],
) -> bool:
    row_calls_with_runtime = int(_coerce_int(row_summary.get("calls_with_runtime")) or 0)
    fallback_calls_with_runtime = int(
        _coerce_int(fallback_summary.get("calls_with_runtime")) or 0
    )
    if fallback_calls_with_runtime > row_calls_with_runtime:
        return True
    row_total_tokens = _coerce_int(row_summary.get("total_tokens"))
    fallback_total_tokens = _coerce_int(fallback_summary.get("total_tokens"))
    if row_total_tokens is None and fallback_total_tokens is not None:
        return True
    row_stage_count = len(row_summary.get("by_stage") or {})
    fallback_stage_count = len(fallback_summary.get("by_stage") or {})
    if fallback_stage_count > row_stage_count:
        return True
    row_call_count = int(_coerce_int(row_summary.get("call_count")) or 0)
    fallback_call_count = int(_coerce_int(fallback_summary.get("call_count")) or 0)
    if fallback_call_count > row_call_count and (
        fallback_total_tokens is not None or fallback_calls_with_runtime > 0
    ):
        return True
    row_by_stage = row_summary.get("by_stage")
    row_by_stage = row_by_stage if isinstance(row_by_stage, dict) else {}
    fallback_by_stage = fallback_summary.get("by_stage")
    fallback_by_stage = (
        fallback_by_stage if isinstance(fallback_by_stage, dict) else {}
    )
    for stage_key, fallback_stage in fallback_by_stage.items():
        if not isinstance(fallback_stage, dict):
            continue
        row_stage = row_by_stage.get(stage_key)
        row_stage = row_stage if isinstance(row_stage, dict) else {}
        row_stage_call_count = int(_coerce_int(row_stage.get("call_count")) or 0)
        fallback_stage_call_count = int(
            _coerce_int(fallback_stage.get("call_count")) or 0
        )
        row_stage_runtime = int(
            _coerce_int(row_stage.get("calls_with_runtime")) or 0
        )
        fallback_stage_runtime = int(
            _coerce_int(fallback_stage.get("calls_with_runtime")) or 0
        )
        row_stage_tokens = _coerce_int(row_stage.get("total_tokens"))
        fallback_stage_tokens = _coerce_int(fallback_stage.get("total_tokens"))
        if fallback_stage_runtime > row_stage_runtime:
            return True
        if row_stage_tokens is None and fallback_stage_tokens is not None:
            return True
        if (
            fallback_stage_tokens is not None
            and row_stage_tokens is not None
            and fallback_stage_tokens > row_stage_tokens
            and fallback_stage_call_count >= row_stage_call_count
        ):
            return True
    return False


def _upload_bundle_stage_total_duration_ms(stage_payload: dict[str, Any]) -> int | None:
    calls_with_runtime = int(_coerce_int(stage_payload.get("calls_with_runtime")) or 0)
    avg_duration_ms = _coerce_float(stage_payload.get("avg_duration_ms"))
    if calls_with_runtime <= 0 or avg_duration_ms is None:
        return None
    return int(round(avg_duration_ms * float(calls_with_runtime)))


def _upload_bundle_merge_runtime_stage_summary(
    *,
    row_stage: dict[str, Any],
    fallback_stage: dict[str, Any],
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    row_call_count = int(_coerce_int(row_stage.get("call_count")) or 0)
    fallback_call_count = int(_coerce_int(fallback_stage.get("call_count")) or 0)
    row_calls_with_runtime = int(
        _coerce_int(row_stage.get("calls_with_runtime")) or 0
    )
    fallback_calls_with_runtime = int(
        _coerce_int(fallback_stage.get("calls_with_runtime")) or 0
    )
    row_total_tokens = _coerce_int(row_stage.get("total_tokens"))
    fallback_total_tokens = _coerce_int(fallback_stage.get("total_tokens"))
    row_total_duration_ms = _upload_bundle_stage_total_duration_ms(row_stage)
    fallback_total_duration_ms = _upload_bundle_stage_total_duration_ms(fallback_stage)

    merged["call_count"] = max(row_call_count, fallback_call_count)
    merged["calls_with_runtime"] = max(
        row_calls_with_runtime,
        fallback_calls_with_runtime,
    )
    merged["calls_with_cost"] = int(_coerce_int(row_stage.get("calls_with_cost")) or 0)
    merged["calls_with_estimated_cost"] = int(
        _coerce_int(row_stage.get("calls_with_estimated_cost")) or 0
    )
    if fallback_total_tokens is not None and (
        row_total_tokens is None or fallback_total_tokens > row_total_tokens
    ):
        merged["total_tokens"] = fallback_total_tokens
    else:
        merged["total_tokens"] = row_total_tokens

    merged_total_duration_ms: int | None
    if fallback_total_duration_ms is not None and (
        row_total_duration_ms is None or fallback_total_duration_ms > row_total_duration_ms
    ):
        merged_total_duration_ms = fallback_total_duration_ms
    else:
        merged_total_duration_ms = row_total_duration_ms
    merged["avg_duration_ms"] = (
        round(float(merged_total_duration_ms) / float(merged["calls_with_runtime"]), 3)
        if merged_total_duration_ms is not None and merged["calls_with_runtime"] > 0
        else None
    )

    row_total_cost = _coerce_float(row_stage.get("total_cost_usd"))
    fallback_total_cost = _coerce_float(fallback_stage.get("total_cost_usd"))
    merged["total_cost_usd"] = (
        row_total_cost if row_total_cost is not None else fallback_total_cost
    )
    row_total_estimated_cost = _coerce_float(row_stage.get("total_estimated_cost_usd"))
    fallback_total_estimated_cost = _coerce_float(
        fallback_stage.get("total_estimated_cost_usd")
    )
    merged["total_estimated_cost_usd"] = (
        row_total_estimated_cost
        if row_total_estimated_cost is not None
        else fallback_total_estimated_cost
    )
    merged["cost_coverage_ratio"] = (
        round(merged["calls_with_cost"] / merged["call_count"], 6)
        if merged["call_count"] > 0
        else 0.0
    )
    merged["estimated_cost_coverage_ratio"] = (
        round(merged["calls_with_estimated_cost"] / merged["call_count"], 6)
        if merged["call_count"] > 0
        else 0.0
    )
    return merged


def _upload_bundle_merge_runtime_inventory_with_fallback(
    *,
    row_inventory: dict[str, Any],
    fallback_inventory: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(fallback_inventory)
    row_summary = row_inventory.get("summary")
    row_summary = row_summary if isinstance(row_summary, dict) else {}
    fallback_summary = fallback_inventory.get("summary")
    fallback_summary = fallback_summary if isinstance(fallback_summary, dict) else {}
    row_by_stage = row_summary.get("by_stage")
    row_by_stage = row_by_stage if isinstance(row_by_stage, dict) else {}
    fallback_by_stage = fallback_summary.get("by_stage")
    fallback_by_stage = fallback_by_stage if isinstance(fallback_by_stage, dict) else {}
    merged_by_stage: dict[str, dict[str, Any]] = {}
    stage_keys = (
        sorted(fallback_by_stage, key=_prompt_category_sort_key)
        if fallback_by_stage
        else sorted(row_by_stage, key=_prompt_category_sort_key)
    )
    for stage_key in stage_keys:
        row_stage = row_by_stage.get(stage_key)
        row_stage = row_stage if isinstance(row_stage, dict) else {}
        fallback_stage = fallback_by_stage.get(stage_key)
        fallback_stage = fallback_stage if isinstance(fallback_stage, dict) else {}
        merged_by_stage[stage_key] = _upload_bundle_merge_runtime_stage_summary(
            row_stage=row_stage,
            fallback_stage=fallback_stage,
        )
    merged_summary = dict(fallback_summary)
    merged_summary["by_stage"] = merged_by_stage
    merged_summary["call_count"] = int(
        sum(int(payload.get("call_count") or 0) for payload in merged_by_stage.values())
    )
    merged_summary["calls_with_runtime"] = int(
        sum(
            int(payload.get("calls_with_runtime") or 0)
            for payload in merged_by_stage.values()
        )
    )
    merged_summary["calls_with_cost"] = int(
        sum(int(payload.get("calls_with_cost") or 0) for payload in merged_by_stage.values())
    )
    merged_summary["calls_with_estimated_cost"] = int(
        sum(
            int(payload.get("calls_with_estimated_cost") or 0)
            for payload in merged_by_stage.values()
        )
    )
    duration_totals = [
        stage_total
        for payload in merged_by_stage.values()
        for stage_total in [_upload_bundle_stage_total_duration_ms(payload)]
        if stage_total is not None
    ]
    merged_summary["total_duration_ms"] = (
        int(sum(duration_totals)) if duration_totals else None
    )
    merged_summary["avg_duration_ms"] = (
        round(
            float(merged_summary["total_duration_ms"])
            / float(merged_summary["calls_with_runtime"]),
            3,
        )
        if merged_summary["total_duration_ms"] is not None
        and merged_summary["calls_with_runtime"] > 0
        else None
    )
    token_totals = [
        _coerce_int(payload.get("total_tokens"))
        for payload in merged_by_stage.values()
        if _coerce_int(payload.get("total_tokens")) is not None
    ]
    merged_summary["total_tokens"] = int(sum(token_totals)) if token_totals else None
    cost_totals = [
        _coerce_float(payload.get("total_cost_usd"))
        for payload in merged_by_stage.values()
        if _coerce_float(payload.get("total_cost_usd")) is not None
    ]
    merged_summary["total_cost_usd"] = (
        round(float(sum(cost_totals)), 8) if cost_totals else None
    )
    estimated_cost_totals = [
        _coerce_float(payload.get("total_estimated_cost_usd"))
        for payload in merged_by_stage.values()
        if _coerce_float(payload.get("total_estimated_cost_usd")) is not None
    ]
    merged_summary["total_estimated_cost_usd"] = (
        round(float(sum(estimated_cost_totals)), 8)
        if estimated_cost_totals
        else None
    )
    merged_summary["cost_coverage_ratio"] = (
        round(merged_summary["calls_with_cost"] / merged_summary["call_count"], 6)
        if merged_summary["call_count"] > 0
        else 0.0
    )
    merged_summary["estimated_cost_coverage_ratio"] = (
        round(
            merged_summary["calls_with_estimated_cost"] / merged_summary["call_count"],
            6,
        )
        if merged_summary["call_count"] > 0
        else 0.0
    )
    merged_summary["cost_signal"] = (
        dict(row_summary.get("cost_signal"))
        if isinstance(row_summary.get("cost_signal"), dict)
        else dict(fallback_summary.get("cost_signal") or {})
    )
    merged_summary["estimated_cost_signal"] = (
        dict(row_summary.get("estimated_cost_signal"))
        if isinstance(row_summary.get("estimated_cost_signal"), dict)
        else dict(fallback_summary.get("estimated_cost_signal") or {})
    )
    merged_summary["cost_signal"]["available"] = merged_summary["calls_with_cost"] > 0
    merged_summary["cost_signal"]["calls_with_cost"] = merged_summary["calls_with_cost"]
    merged_summary["cost_signal"]["coverage_ratio"] = merged_summary["cost_coverage_ratio"]
    if merged_summary["calls_with_cost"] > 0:
        merged_summary["cost_signal"]["unavailable_reason"] = ""
    merged_summary["estimated_cost_signal"]["available"] = (
        merged_summary["calls_with_estimated_cost"] > 0
    )
    merged_summary["estimated_cost_signal"]["calls_with_estimated_cost"] = (
        merged_summary["calls_with_estimated_cost"]
    )
    merged_summary["estimated_cost_signal"]["coverage_ratio"] = (
        merged_summary["estimated_cost_coverage_ratio"]
    )
    fallback_runtime_source = str(fallback_summary.get("runtime_source") or "").strip()
    merged_summary["runtime_source"] = (
        f"call_inventory_rows_plus_{fallback_runtime_source}"
        if fallback_runtime_source
        else "call_inventory_rows_plus_fallback"
    )
    merged_summary.update(
        _upload_bundle_token_share_fields(
            by_stage=merged_by_stage,
            total_tokens=_coerce_int(merged_summary.get("total_tokens")),
        )
    )
    merged["summary"] = merged_summary
    for key in (
        "top_slowest_calls",
        "top_token_calls",
        "top_cost_calls",
        "top_estimated_cost_calls",
    ):
        merged[key] = list(row_inventory.get(key) or [])
    row_by_source = row_inventory.get("by_source")
    if isinstance(row_by_source, list) and row_by_source:
        merged["by_source"] = row_by_source
    return merged


def _upload_bundle_build_call_runtime_inventory(
    *,
    call_inventory_rows: list[dict[str, Any]],
    run_dir_by_id: dict[str, Path],
    run_dirs: list[Path] | None = None,
) -> dict[str, Any]:
    runtime_by_key = _upload_bundle_collect_call_runtime_map(
        run_dirs=run_dirs,
        run_dir_by_id=run_dir_by_id,
    )
    telemetry_fallback = _upload_bundle_build_call_runtime_inventory_from_prediction_manifest(
        run_dirs=run_dirs,
        run_dir_by_id=run_dir_by_id,
    )
    enriched_rows: list[dict[str, Any]] = []
    for row in call_inventory_rows:
        source_key = str(row.get("source_key") or "").strip()
        run_id = str(row.get("run_id") or "").strip()
        recipe_id = str(row.get("recipe_id") or "").strip()
        stage_key = _prompt_row_stage_key(row)
        call_id = str(row.get("call_id") or "").strip()
        runtime = runtime_by_key.get((source_key, run_id, recipe_id, stage_key, call_id))
        if not isinstance(runtime, dict):
            runtime = runtime_by_key.get(("", run_id, recipe_id, stage_key, call_id))
        if not isinstance(runtime, dict):
            runtime = {}
            for runtime_key, runtime_payload in runtime_by_key.items():
                if (
                    not isinstance(runtime_key, tuple)
                    or len(runtime_key) != 5
                    or not isinstance(runtime_payload, dict)
                ):
                    continue
                (
                    _runtime_source_key,
                    runtime_run_id,
                    runtime_recipe_id,
                    runtime_stage_key,
                    runtime_call_id,
                ) = runtime_key
                if (
                    str(runtime_run_id) == run_id
                    and str(runtime_recipe_id) == recipe_id
                    and str(runtime_stage_key) == stage_key
                    and str(runtime_call_id) == call_id
                ):
                    runtime = runtime_payload
                    break

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

    if not enriched_rows and telemetry_fallback is not None:
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
    by_stage: dict[str, dict[str, Any]] = {}
    stage_keys = sorted(
        {
            _prompt_row_stage_key(row)
            for row in enriched_rows
            if _prompt_row_stage_key(row)
        },
        key=_prompt_category_sort_key,
    )
    for stage_key in stage_keys:
        stage_rows = [
            row
            for row in enriched_rows
            if _prompt_row_stage_key(row) == stage_key
        ]
        stage_duration = [
            _coerce_int(row.get("duration_ms"))
            for row in stage_rows
            if _coerce_int(row.get("duration_ms")) is not None
        ]
        stage_tokens = [
            _coerce_int(row.get("tokens_total"))
            for row in stage_rows
            if _coerce_int(row.get("tokens_total")) is not None
        ]
        stage_cost = [
            _coerce_float(row.get("cost_usd"))
            for row in stage_rows
            if _coerce_float(row.get("cost_usd")) is not None
        ]
        stage_estimated_cost = [
            _coerce_float(row.get("estimated_cost_usd"))
            for row in stage_rows
            if _coerce_float(row.get("estimated_cost_usd")) is not None
        ]
        stage_calls_with_cost = len(stage_cost)
        stage_calls_with_estimated_cost = len(stage_estimated_cost)
        by_stage[stage_key] = {
            "call_count": len(stage_rows),
            "calls_with_runtime": len(stage_duration),
            "calls_with_cost": stage_calls_with_cost,
            "calls_with_estimated_cost": stage_calls_with_estimated_cost,
            "avg_duration_ms": (
                round(sum(stage_duration) / len(stage_duration), 3)
                if stage_duration
                else None
            ),
            "total_tokens": int(sum(stage_tokens)) if stage_tokens else None,
            "total_cost_usd": (
                round(float(sum(stage_cost)), 8) if stage_cost else None
            ),
            "total_estimated_cost_usd": (
                round(float(sum(stage_estimated_cost)), 8)
                if stage_estimated_cost
                else None
            ),
            "cost_coverage_ratio": (
                round(stage_calls_with_cost / len(stage_rows), 6) if stage_rows else 0.0
            ),
            "estimated_cost_coverage_ratio": (
                round(stage_calls_with_estimated_cost / len(stage_rows), 6)
                if stage_rows
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
        "by_stage": by_stage,
        "runtime_source": "call_inventory_rows",
    }
    summary.update(
        _upload_bundle_token_share_fields(by_stage=by_stage, total_tokens=total_tokens)
    )

    by_source_buckets: dict[str, dict[str, Any]] = {}
    for row in enriched_rows:
        source_key = str(row.get("source_key") or "").strip()
        source_file = str(row.get("source_file") or "").strip()
        if not source_key:
            source_key = source_file.lower() if source_file else "unknown_source"
        bucket = by_source_buckets.setdefault(
            source_key,
            {
                "source_key": source_key,
                "source_file": source_file or None,
                "call_count": 0,
                "calls_with_runtime": 0,
                "calls_with_cost": 0,
                "calls_with_estimated_cost": 0,
                "duration_total_ms": 0,
                "duration_known": False,
                "tokens_total": 0,
                "tokens_known": False,
                "cost_total_usd": 0.0,
                "cost_known": False,
                "estimated_cost_total_usd": 0.0,
                "estimated_cost_known": False,
                "by_stage": defaultdict(
                    lambda: {
                        "call_count": 0,
                        "calls_with_runtime": 0,
                        "calls_with_cost": 0,
                        "calls_with_estimated_cost": 0,
                        "duration_total_ms": 0,
                        "duration_known": False,
                        "tokens_total": 0,
                        "tokens_known": False,
                        "cost_total_usd": 0.0,
                        "cost_known": False,
                        "estimated_cost_total_usd": 0.0,
                        "estimated_cost_known": False,
                    }
                ),
            },
        )
        bucket["call_count"] += 1
        stage_key = _prompt_row_stage_key(row) or "unknown"
        stage_bucket = bucket["by_stage"][stage_key]
        stage_bucket["call_count"] += 1

        duration_ms = _coerce_int(row.get("duration_ms"))
        if duration_ms is not None:
            bucket["calls_with_runtime"] += 1
            bucket["duration_total_ms"] += int(duration_ms)
            bucket["duration_known"] = True
            stage_bucket["calls_with_runtime"] += 1
            stage_bucket["duration_total_ms"] += int(duration_ms)
            stage_bucket["duration_known"] = True

        tokens_total_row = _coerce_int(row.get("tokens_total"))
        if tokens_total_row is not None:
            bucket["tokens_total"] += int(tokens_total_row)
            bucket["tokens_known"] = True
            stage_bucket["tokens_total"] += int(tokens_total_row)
            stage_bucket["tokens_known"] = True

        cost_usd = _coerce_float(row.get("cost_usd"))
        if cost_usd is not None:
            bucket["calls_with_cost"] += 1
            bucket["cost_total_usd"] += float(cost_usd)
            bucket["cost_known"] = True
            stage_bucket["calls_with_cost"] += 1
            stage_bucket["cost_total_usd"] += float(cost_usd)
            stage_bucket["cost_known"] = True

        estimated_cost_usd_row = _coerce_float(row.get("estimated_cost_usd"))
        if estimated_cost_usd_row is not None:
            bucket["calls_with_estimated_cost"] += 1
            bucket["estimated_cost_total_usd"] += float(estimated_cost_usd_row)
            bucket["estimated_cost_known"] = True
            stage_bucket["calls_with_estimated_cost"] += 1
            stage_bucket["estimated_cost_total_usd"] += float(estimated_cost_usd_row)
            stage_bucket["estimated_cost_known"] = True

    by_source_rows: list[dict[str, Any]] = []
    for source_key, bucket in by_source_buckets.items():
        call_count = int(bucket.get("call_count") or 0)
        calls_with_runtime = int(bucket.get("calls_with_runtime") or 0)
        calls_with_cost = int(bucket.get("calls_with_cost") or 0)
        calls_with_estimated_cost = int(bucket.get("calls_with_estimated_cost") or 0)
        stage_rows: dict[str, Any] = {}
        by_stage_payload = bucket.get("by_stage")
        if isinstance(by_stage_payload, dict):
            for stage_key in sorted(by_stage_payload.keys(), key=_prompt_category_sort_key):
                stage_bucket = by_stage_payload.get(stage_key)
                if not isinstance(stage_bucket, dict):
                    continue
                stage_call_count = int(stage_bucket.get("call_count") or 0)
                stage_calls_with_runtime = int(stage_bucket.get("calls_with_runtime") or 0)
                stage_rows[stage_key] = {
                    "call_count": stage_call_count,
                    "calls_with_runtime": stage_calls_with_runtime,
                    "calls_with_cost": int(stage_bucket.get("calls_with_cost") or 0),
                    "calls_with_estimated_cost": int(
                        stage_bucket.get("calls_with_estimated_cost") or 0
                    ),
                    "total_duration_ms": (
                        int(stage_bucket.get("duration_total_ms") or 0)
                        if bool(stage_bucket.get("duration_known"))
                        else None
                    ),
                    "avg_duration_ms": (
                        round(
                            float(int(stage_bucket.get("duration_total_ms") or 0))
                            / float(stage_calls_with_runtime),
                            3,
                        )
                        if bool(stage_bucket.get("duration_known"))
                        and stage_calls_with_runtime > 0
                        else None
                    ),
                    "total_tokens": (
                        int(stage_bucket.get("tokens_total") or 0)
                        if bool(stage_bucket.get("tokens_known"))
                        else None
                    ),
                    "total_cost_usd": (
                        round(float(stage_bucket.get("cost_total_usd") or 0.0), 8)
                        if bool(stage_bucket.get("cost_known"))
                        else None
                    ),
                    "total_estimated_cost_usd": (
                        round(float(stage_bucket.get("estimated_cost_total_usd") or 0.0), 8)
                        if bool(stage_bucket.get("estimated_cost_known"))
                        else None
                    ),
                }
        by_source_rows.append(
            {
                "source_key": source_key,
                "source_file": bucket.get("source_file"),
                "call_count": call_count,
                "calls_with_runtime": calls_with_runtime,
                "calls_with_cost": calls_with_cost,
                "calls_with_estimated_cost": calls_with_estimated_cost,
                "total_duration_ms": (
                    int(bucket.get("duration_total_ms") or 0)
                    if bool(bucket.get("duration_known"))
                    else None
                ),
                "avg_duration_ms": (
                    round(
                        float(int(bucket.get("duration_total_ms") or 0))
                        / float(calls_with_runtime),
                        3,
                    )
                    if bool(bucket.get("duration_known")) and calls_with_runtime > 0
                    else None
                ),
                "total_tokens": (
                    int(bucket.get("tokens_total") or 0)
                    if bool(bucket.get("tokens_known"))
                    else None
                ),
                "total_cost_usd": (
                    round(float(bucket.get("cost_total_usd") or 0.0), 8)
                    if bool(bucket.get("cost_known"))
                    else None
                ),
                "total_estimated_cost_usd": (
                    round(float(bucket.get("estimated_cost_total_usd") or 0.0), 8)
                    if bool(bucket.get("estimated_cost_known"))
                    else None
                ),
                "cost_coverage_ratio": (
                    round(calls_with_cost / call_count, 6) if call_count > 0 else 0.0
                ),
                "estimated_cost_coverage_ratio": (
                    round(calls_with_estimated_cost / call_count, 6)
                    if call_count > 0
                    else 0.0
                ),
                "by_stage": stage_rows,
            }
        )
    by_source_rows.sort(
        key=lambda row: (
            -_float_or_zero(row.get("total_estimated_cost_usd")),
            -_float_or_zero(row.get("total_cost_usd")),
            -int(_coerce_int(row.get("call_count")) or 0),
            str(row.get("source_key") or ""),
        )
    )

    row_inventory = {
        "summary": summary,
        "by_source": by_source_rows,
        "top_slowest_calls": top_slowest,
        "top_token_calls": top_token,
        "top_cost_calls": top_cost,
        "top_estimated_cost_calls": top_estimated_cost,
    }
    if telemetry_fallback is None:
        return row_inventory
    fallback_summary = (
        telemetry_fallback.get("summary")
        if isinstance(telemetry_fallback.get("summary"), dict)
        else {}
    )
    if _upload_bundle_runtime_inventory_needs_fallback(
        row_summary=summary,
        fallback_summary=fallback_summary,
    ):
        return _upload_bundle_merge_runtime_inventory_with_fallback(
            row_inventory=row_inventory,
            fallback_inventory=telemetry_fallback,
        )
    return row_inventory


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


def _upload_bundle_build_line_role_escalation_summary(
    *,
    source_root: Path,
    run_dir_by_id: dict[str, Path],
    run_dirs: list[Path] | None = None,
) -> dict[str, Any]:
    file_paths: list[Path] = []
    for run_dir in _upload_bundle_iter_unique_run_dirs(
        run_dirs=run_dirs,
        run_dir_by_id=run_dir_by_id,
    ):
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
    explicit_escalation_examples: list[dict[str, Any]] = []
    explicit_escalation_by_label: Counter[str] = Counter()
    explicit_escalation_by_decided_by: Counter[str] = Counter()
    explicit_escalation_reason_counts: Counter[str] = Counter()
    total_rows = 0

    for path in sorted(file_paths):
        for row in _iter_jsonl(path):
            total_rows += 1
            label = str(row.get("label") or "").strip().upper() or "OTHER"
            decided_by = str(row.get("decided_by") or "").strip().lower() or "unknown"
            escalation_reasons = _coerce_str_list(row.get("escalation_reasons"))
            label_counts[label] += 1
            decided_by_counts[decided_by] += 1
            for reason in escalation_reasons:
                explicit_escalation_reason_counts[reason] += 1
            if escalation_reasons:
                explicit_escalation_by_label[label] += 1
                explicit_escalation_by_decided_by[decided_by] += 1
                explicit_escalation_examples.append(
                    {
                        "run_id": str(row.get("run_id") or ""),
                        "recipe_id": str(row.get("recipe_id") or ""),
                        "line_index": _coerce_int(row.get("line_index")),
                        "atomic_index": _coerce_int(row.get("atomic_index")),
                        "label": label,
                        "decided_by": decided_by,
                        "escalation_reasons": escalation_reasons,
                        "text_excerpt": _excerpt(
                            str(row.get("text") or ""),
                            max_len=220,
                        ),
                    }
                )

    explicit_escalation_examples.sort(
        key=lambda row: (
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
        "selective_escalation_signal": {
            "explicit_escalation_row_count": int(sum(explicit_escalation_by_label.values())),
            "explicit_escalation_ratio": (
                round(sum(explicit_escalation_by_label.values()) / total_rows, 6)
                if total_rows > 0
                else 0.0
            ),
            "explicit_escalation_by_label": _counter_to_sorted_dict(
                explicit_escalation_by_label
            ),
            "explicit_escalation_by_decided_by": _counter_to_sorted_dict(
                explicit_escalation_by_decided_by
            ),
            "explicit_escalation_reasons": _counter_to_sorted_dict(
                explicit_escalation_reason_counts
            ),
        },
        "explicit_escalation_examples": explicit_escalation_examples[:24],
    }


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


def _upload_bundle_regression_casebook_signal_key(row: dict[str, Any]) -> tuple[int, int, int, int, str]:
    return (
        -int(_coerce_int(row.get("outside_span_wrong_line_count")) or 0),
        -int(_coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0),
        -int(_coerce_int(row.get("recipe_error_count")) or 0),
        -int(_coerce_int(row.get("recipe_warning_count")) or 0),
        str(row.get("recipe_id") or ""),
    )


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
    negative_delta_rows = [
        row
        for row in sorted_worst
        if (_coerce_float(row.get("delta_codex_minus_baseline")) or 0.0) < 0.0
    ]
    signal_rows = sorted(recipe_triage_rows, key=_upload_bundle_regression_casebook_signal_key)

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

    fill_source = negative_delta_rows
    fill_reason = "top_negative_delta_fill"
    suggested_target_source = "top_negative_delta_recipes"
    if not fill_source:
        fill_source = signal_rows
        fill_reason = "top_signal_fill"
        suggested_target_source = "top_signal_recipes"

    for row in fill_source:
        key = _recipe_row_key(row)
        if key in selected_keys:
            continue
        row_copy = dict(row)
        row_copy["selection_reason"] = fill_reason
        selected_rows.append(row_copy)
        selected_keys.add(key)
        if len(selected_rows) >= 10:
            break
    if len(selected_rows) < 10 and fill_reason != "top_signal_fill":
        for row in signal_rows:
            key = _recipe_row_key(row)
            if key in selected_keys:
                continue
            row_copy = dict(row)
            row_copy["selection_reason"] = "top_signal_fill"
            selected_rows.append(row_copy)
            selected_keys.add(key)
            if len(selected_rows) >= 10:
                break
    selected_rows = selected_rows[:10]

    packets = _build_selected_recipe_packets(
        selected_recipe_rows=selected_rows,
        changed_line_rows=changed_line_rows,
        default_recipe_stages=_upload_bundle_recipe_stages_for_row(
            recipe_pipeline_id="codex-recipe-shard-v1",
            correction_call_id=None,
        ),
    )
    found_targets = [
        str(row.get("recipe_id") or "")
        for row in selected_rows
        if any(
            _upload_bundle_matches_recipe_target(str(row.get("recipe_id") or ""), target)
            for target in requested_targets
        )
    ]
    missing_targets = [
        target
        for target in requested_targets
        if not any(
            _upload_bundle_matches_recipe_target(recipe_id, target)
            for recipe_id in found_targets
        )
    ]
    suggested_targets: list[str] = []
    suggested_rows = fill_source if fill_reason == "top_signal_fill" else negative_delta_rows
    if not suggested_rows:
        suggested_rows = signal_rows
        suggested_target_source = "top_signal_recipes"
    for row in suggested_rows:
        recipe_id = str(row.get("recipe_id") or "").strip()
        if not recipe_id or recipe_id in suggested_targets:
            continue
        suggested_targets.append(recipe_id)
        if len(suggested_targets) >= 4:
            break
    return {
        "requested_targets": requested_targets,
        "found_targets": found_targets,
        "missing_targets": missing_targets,
        "target_request_status": (
            "all_found"
            if requested_targets and not missing_targets
            else ("partial" if found_targets else "none_found")
        ),
        "suggested_targets": suggested_targets,
        "suggested_target_source": suggested_target_source,
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
    def _sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        changed_lines = int(_coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0)
        outside_span_wrong_line_count = int(
            _coerce_int(row.get("outside_span_wrong_line_count")) or 0
        )
        delta_abs = abs(_float_or_zero(row.get("delta_codex_minus_baseline")))
        warning_count = (
            int(_coerce_int(row.get("correction_warning_count")) or 0)
            + int(_coerce_int(row.get("recipe_warning_count")) or 0)
            + int(_coerce_int(row.get("final_recipe_warning_count")) or 0)
        )
        line_total = int(_coerce_int(row.get("line_total")) or 0)
        empty_mapping_only = (
            bool(row.get("final_recipe_empty_mapping") or row.get("correction_empty_mapping"))
            and changed_lines <= 0
            and outside_span_wrong_line_count <= 0
            and delta_abs <= 0.0
            and warning_count <= 0
        )
        has_turn1_signal = (
            changed_lines > 0
            or outside_span_wrong_line_count > 0
            or delta_abs > 0.0
            or warning_count > 0
        )
        return (
            -int(has_turn1_signal),
            int(empty_mapping_only),
            -changed_lines,
            -outside_span_wrong_line_count,
            -delta_abs,
            -warning_count,
            -line_total,
            str(row.get("recipe_id") or ""),
            str(row.get("source_key") or ""),
            str(row.get("codex_run_id") or ""),
        )

    return sorted(
        [row for row in recipe_triage_rows if isinstance(row, dict)],
        key=_sort_key,
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
        "correction_call_id": str(row.get("correction_call_id") or ""),
        "correction_input_block_count": int(
            _coerce_int(row.get("correction_input_block_count")) or 0
        ),
        "correction_warning_count": int(
            _coerce_int(row.get("correction_warning_count")) or 0
        ),
        "correction_warning_buckets": _coerce_str_list(
            row.get("correction_warning_buckets")
        ),
        "correction_ingredient_count": int(
            _coerce_int(row.get("correction_ingredient_count")) or 0
        ),
        "correction_step_count": int(
            _coerce_int(row.get("correction_step_count")) or 0
        ),
        "correction_mapping_count": int(
            _coerce_int(row.get("correction_mapping_count")) or 0
        ),
        "correction_empty_mapping": bool(row.get("correction_empty_mapping")),
        "build_intermediate_status": str(row.get("build_intermediate_status") or ""),
        "correction_status": str(row.get("correction_status") or ""),
        "build_final_status": str(row.get("build_final_status") or ""),
        "build_intermediate_clamped_block_loss_count": int(
            _coerce_int(row.get("build_intermediate_clamped_block_loss_count")) or 0
        ),
        "build_intermediate_clamped_block_loss_ratio": _coerce_float(
            row.get("build_intermediate_clamped_block_loss_ratio")
        ),
        "correction_degradation_reasons": _coerce_str_list(
            row.get("correction_degradation_reasons")
        ),
        "correction_degradation_severity": str(row.get("correction_degradation_severity") or ""),
        "correction_promotion_policy": str(row.get("correction_promotion_policy") or ""),
        "build_final_execution_mode": str(row.get("build_final_execution_mode") or ""),
        "build_final_routing_reason": str(row.get("build_final_routing_reason") or ""),
        "build_final_fallback_reason": str(row.get("build_final_fallback_reason") or ""),
        "final_mapping_status": str(row.get("final_mapping_status") or ""),
        "final_mapping_reason": str(row.get("final_mapping_reason") or ""),
        "structural_status": str(row.get("structural_status") or ""),
        "structural_reason_codes": _coerce_str_list(row.get("structural_reason_codes")),
        "recipe_warning_count": int(_coerce_int(row.get("recipe_warning_count")) or 0),
        "recipe_error_count": int(_coerce_int(row.get("recipe_error_count")) or 0),
        "transport_mismatch": bool(row.get("transport_mismatch")),
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
    run_diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    row_by_run_id = {
        str(row.get("run_id") or "").strip(): row
        for row in run_rows
        if isinstance(row, dict) and str(row.get("run_id") or "").strip()
    }
    diagnostic_by_run_id = {
        str(row.get("run_id") or "").strip(): row
        for row in (run_diagnostics or [])
        if isinstance(row, dict) and str(row.get("run_id") or "").strip()
    }
    artifact_names = (
        "need_to_know_summary.json",
        PROMPT_WARNING_AGGREGATE_FILE_NAME,
        PROJECTION_TRACE_FILE_NAME,
        WRONG_LABEL_FULL_CONTEXT_FILE_NAME,
        PREPROCESS_TRACE_FAILURES_FILE_NAME,
    )

    def _diagnostic_status_for_artifact(
        *,
        run_diagnostic: dict[str, Any] | None,
        artifact_name: str,
    ) -> str | None:
        if not isinstance(run_diagnostic, dict):
            return None
        field_by_artifact = {
            PROMPT_WARNING_AGGREGATE_FILE_NAME: "prompt_warning_aggregate_status",
            PROJECTION_TRACE_FILE_NAME: "projection_trace_status",
            WRONG_LABEL_FULL_CONTEXT_FILE_NAME: "wrong_label_full_context_status",
            PREPROCESS_TRACE_FAILURES_FILE_NAME: "preprocess_trace_failures_status",
        }
        field_name = field_by_artifact.get(artifact_name)
        if not field_name:
            return None
        status = str(run_diagnostic.get(field_name) or "").strip()
        if not status:
            return None
        if status == "written":
            return "present"
        return status

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
        codex_diag = diagnostic_by_run_id.get(codex_run_id)
        baseline_diag = diagnostic_by_run_id.get(baseline_run_id)
        codex_enabled = _upload_bundle_is_codex_pipeline_enabled(
            codex_row.get("llm_recipe_pipeline")
        )
        baseline_enabled = _upload_bundle_is_codex_pipeline_enabled(
            baseline_row.get("llm_recipe_pipeline")
        )
        codex_statuses: dict[str, str] = {}
        baseline_statuses: dict[str, str] = {}
        for artifact_name in artifact_names:
            codex_status = _diagnostic_status_for_artifact(
                run_diagnostic=codex_diag,
                artifact_name=artifact_name,
            )
            if codex_status is None:
                codex_status = (
                    _starter_pack_status_for_artifact(
                        run_dir=codex_dir,
                        artifact_name=artifact_name,
                        codex_enabled=codex_enabled,
                    )
                    if isinstance(codex_dir, Path)
                    else "missing"
                )
            codex_statuses[artifact_name] = codex_status

            baseline_status = _diagnostic_status_for_artifact(
                run_diagnostic=baseline_diag,
                artifact_name=artifact_name,
            )
            if baseline_status is None:
                baseline_status = (
                    _starter_pack_status_for_artifact(
                        run_dir=baseline_dir,
                        artifact_name=artifact_name,
                        codex_enabled=baseline_enabled,
                    )
                    if isinstance(baseline_dir, Path)
                    else "missing"
                )
            baseline_statuses[artifact_name] = baseline_status
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
                "build_intermediate_status": str(row.get("build_intermediate_status") or ""),
                "correction_status": str(row.get("correction_status") or ""),
                "build_final_status": str(row.get("build_final_status") or ""),
                "correction_warning_count": int(
                    _coerce_int(row.get("correction_warning_count")) or 0
                ),
                "final_recipe_warning_count": int(
                    _coerce_int(row.get("final_recipe_warning_count")) or 0
                ),
                "final_recipe_empty_mapping": bool(row.get("final_recipe_empty_mapping")),
                "build_final_execution_mode": str(row.get("build_final_execution_mode") or ""),
                "build_final_routing_reason": str(row.get("build_final_routing_reason") or ""),
                "build_final_fallback_reason": str(row.get("build_final_fallback_reason") or ""),
                "transport_mismatch": bool(row.get("transport_mismatch")),
            }
        )
    return rows


def _upload_bundle_triage_packet_row_has_signal(row: dict[str, Any]) -> bool:
    return bool(
        int(_coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0) > 0
        or int(_coerce_int(row.get("outside_span_wrong_line_count")) or 0) > 0
        or _coerce_float(row.get("delta_codex_minus_baseline")) is not None
        or int(_coerce_int(row.get("line_total")) or 0) > 0
        or int(_coerce_int(row.get("correction_warning_count")) or 0) > 0
        or int(_coerce_int(row.get("final_recipe_warning_count")) or 0) > 0
    )


def _upload_bundle_select_triage_packet_sample_rows(
    triage_packet_rows: list[dict[str, Any]],
    *,
    pair_count: int = 0,
    active_recipe_span_breakout: dict[str, Any] | None = None,
    limit: int = 40,
) -> tuple[list[dict[str, Any]], str]:
    signal_rows = [
        row
        for row in triage_packet_rows
        if isinstance(row, dict) and _upload_bundle_triage_packet_row_has_signal(row)
    ]
    if signal_rows:
        return signal_rows[:limit], ""
    active_recipe_span_breakout = (
        active_recipe_span_breakout
        if isinstance(active_recipe_span_breakout, dict)
        else {}
    )
    if int(pair_count) <= 0:
        recipe_span_count = int(
            _coerce_int(active_recipe_span_breakout.get("recipe_span_count")) or 0
        )
        if recipe_span_count > 0:
            return (
                [],
                (
                    "No comparison pair was available, so recipe-local triage rows were not "
                    "built. Recipe spans were discovered in the single run, so use "
                    "`analysis.active_recipe_span_breakout`, "
                    "`analysis.recipe_pipeline_context`, and "
                    "`analysis.stage_observability_summary` first."
                ),
            )
        return (
            [],
            (
                "No comparison pair was available, so recipe-local triage rows were not "
                "built. Use `analysis.recipe_pipeline_context`, "
                "`analysis.stage_observability_summary`, and per-run summaries first."
            ),
        )
    return (
        [],
        (
            "No triage rows had recipe-local signal. This usually means active recipe spans "
            "were not discovered, so use `analysis.turn1_summary`, "
            "`analysis.active_recipe_span_breakout`, `analysis.top_confusion_deltas`, and "
            "`analysis.changed_lines_stratified_sample` first."
        ),
    )


def _upload_bundle_single_run_recipe_span_fallback(
    run_dirs: list[Path] | None,
) -> dict[str, Any] | None:
    unique_run_dirs = _upload_bundle_iter_unique_run_dirs(run_dirs=run_dirs, run_dir_by_id=None)
    if len(unique_run_dirs) != 1:
        return None
    run_dir = unique_run_dirs[0]
    telemetry_path = run_dir / "line-role-pipeline" / "telemetry_summary.json"
    telemetry_payload = (
        _upload_bundle_load_json_object(telemetry_path)
        if telemetry_path.is_file()
        else {}
    )
    benchmark_manifest_path = run_dir / "manifest.json"
    benchmark_manifest_payload = (
        _upload_bundle_load_json_object(benchmark_manifest_path)
        if benchmark_manifest_path.is_file()
        else {}
    )
    projection_payload = (
        benchmark_manifest_payload.get("line_role_pipeline_recipe_projection")
        if isinstance(benchmark_manifest_payload.get("line_role_pipeline_recipe_projection"), dict)
        else {}
    )
    projection_payload = projection_payload if isinstance(projection_payload, dict) else {}

    recipe_span_count = _coerce_int(telemetry_payload.get("recipe_span_count"))
    signal_source = ""
    if recipe_span_count is not None:
        signal_source = "line_role_projection_telemetry"
    else:
        recipe_span_count = _coerce_int(projection_payload.get("recipes_applied"))
        if recipe_span_count is not None:
            signal_source = "benchmark_manifest_projection"

    labeled_line_count = _coerce_int(telemetry_payload.get("labeled_line_count"))
    if labeled_line_count is None:
        labeled_line_count = _coerce_int(projection_payload.get("span_count"))
    unresolved_candidate_line_count = _coerce_int(
        telemetry_payload.get("unresolved_candidate_line_count")
    )
    if unresolved_candidate_line_count is None:
        unresolved_candidate_line_count = _coerce_int(
            projection_payload.get("unresolved_candidate_line_count")
        )

    if (
        recipe_span_count is None
        and labeled_line_count is None
        and unresolved_candidate_line_count is None
    ):
        return None

    return {
        "schema_version": "upload_bundle_single_run_recipe_spans.v1",
        "run_dir": str(run_dir),
        "signal_source": signal_source or "single_run_manifest",
        "recipe_span_count": int(recipe_span_count or 0),
        "labeled_line_count": (
            int(labeled_line_count) if labeled_line_count is not None else None
        ),
        "unresolved_candidate_line_count": (
            int(unresolved_candidate_line_count)
            if unresolved_candidate_line_count is not None
            else None
        ),
    }


def _upload_bundle_build_active_recipe_span_breakout(
    pair_breakdown_rows: list[dict[str, Any]],
    *,
    run_dirs: list[Path] | None = None,
) -> dict[str, Any]:
    region_totals = {
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
    pair_count = 0
    total_recipe_span_count = 0
    pairs_with_zero_recipe_spans = 0
    for row in pair_breakdown_rows:
        if not isinstance(row, dict):
            continue
        pair_count += 1
        recipe_span_count = int(_coerce_int(row.get("recipe_span_count")) or 0)
        total_recipe_span_count += recipe_span_count
        if recipe_span_count <= 0:
            pairs_with_zero_recipe_spans += 1
        region_rows = row.get("region_breakdown")
        region_rows = region_rows if isinstance(region_rows, list) else []
        for region_row in region_rows:
            if not isinstance(region_row, dict):
                continue
            region_name = str(region_row.get("region") or "").strip()
            if region_name not in region_totals:
                continue
            region_totals[region_name]["line_total"] += int(
                _coerce_int(region_row.get("line_total")) or 0
            )
            region_totals[region_name]["codex_correct"] += int(
                _coerce_int(region_row.get("codex_correct")) or 0
            )
            region_totals[region_name]["baseline_correct"] += int(
                _coerce_int(region_row.get("baseline_correct")) or 0
            )

    inside_total = int(region_totals["inside_active_recipe_span"]["line_total"] or 0)
    outside_total = int(region_totals["outside_active_recipe_span"]["line_total"] or 0)
    total_scored_lines = inside_total + outside_total

    def _finalize(bucket: dict[str, int]) -> dict[str, Any]:
        line_total = int(bucket.get("line_total") or 0)
        codex_accuracy = _rate(int(bucket.get("codex_correct") or 0), line_total)
        baseline_accuracy = _rate(int(bucket.get("baseline_correct") or 0), line_total)
        return {
            "line_total": line_total,
            "codex_correct": int(bucket.get("codex_correct") or 0),
            "baseline_correct": int(bucket.get("baseline_correct") or 0),
            "codex_accuracy": codex_accuracy,
            "baseline_accuracy": baseline_accuracy,
            "delta_codex_minus_baseline": _delta(codex_accuracy, baseline_accuracy),
        }

    single_run_fallback = None
    if pair_count <= 0:
        single_run_fallback = _upload_bundle_single_run_recipe_span_fallback(run_dirs)
        if isinstance(single_run_fallback, dict):
            fallback_recipe_span_count = int(
                _coerce_int(single_run_fallback.get("recipe_span_count")) or 0
            )
            if fallback_recipe_span_count > 0:
                total_recipe_span_count = fallback_recipe_span_count

    all_scored_lines_outside = total_scored_lines > 0 and inside_total <= 0 and outside_total > 0
    if all_scored_lines_outside:
        turn1_note = "All scored comparison mass is outside active recipe spans."
    elif pairs_with_zero_recipe_spans > 0:
        turn1_note = "No active recipe spans were discovered for one or more compared pairs."
    elif pair_count <= 0 and isinstance(single_run_fallback, dict):
        turn1_note = (
            "No compared pairs were available. Recipe span count was derived from "
            "single-run line-role telemetry."
        )
    elif pair_count <= 0:
        turn1_note = (
            "No compared pairs were available, so pairwise span breakout is unavailable."
        )
    else:
        turn1_note = ""
    return {
        "schema_version": "upload_bundle_active_recipe_span_breakout.v1",
        "pair_count": pair_count,
        "recipe_span_count": total_recipe_span_count,
        "pairs_with_zero_recipe_spans": pairs_with_zero_recipe_spans,
        "total_scored_lines": total_scored_lines,
        "all_scored_lines_outside_active_recipe_spans": all_scored_lines_outside,
        "outside_share_of_scored_lines": (
            round(outside_total / total_scored_lines, 6) if total_scored_lines > 0 else None
        ),
        "dominant_region": (
            "outside_active_recipe_span"
            if outside_total > inside_total
            else (
                "inside_active_recipe_span"
                if inside_total > 0
                else "no_scored_lines"
            )
        ),
        "inside_active_recipe_span": _finalize(
            region_totals["inside_active_recipe_span"]
        ),
        "outside_active_recipe_span": _finalize(
            region_totals["outside_active_recipe_span"]
        ),
        "turn1_note": turn1_note,
        "single_run_fallback": single_run_fallback,
    }


def _upload_bundle_build_pair_delta_summary(
    pair_inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    def _minimum(metric_key: str) -> float | None:
        values = [
            _coerce_float(row.get(metric_key))
            for row in pair_inventory
            if _coerce_float(row.get(metric_key)) is not None
        ]
        if not values:
            return None
        return min(values)

    return {
        "worst_pair_delta_overall_line_accuracy": _minimum(
            "delta_overall_line_accuracy"
        ),
        "worst_pair_delta_macro_f1_excluding_other": _minimum(
            "delta_macro_f1_excluding_other"
        ),
        "worst_pair_delta_practical_f1": _minimum("delta_practical_f1"),
        "pairs_with_negative_overall_line_accuracy_delta": sum(
            1
            for row in pair_inventory
            if (_coerce_float(row.get("delta_overall_line_accuracy")) or 0.0) < 0.0
        ),
        "pairs_with_negative_macro_f1_delta": sum(
            1
            for row in pair_inventory
            if (_coerce_float(row.get("delta_macro_f1_excluding_other")) or 0.0) < 0.0
        ),
        "pairs_with_negative_practical_f1_delta": sum(
            1
            for row in pair_inventory
            if (_coerce_float(row.get("delta_practical_f1")) or 0.0) < 0.0
        ),
    }


def _upload_bundle_build_stage_observability_summary(
    failure_ledger: dict[str, Any],
) -> dict[str, Any]:
    rows = failure_ledger.get("rows")
    rows = rows if isinstance(rows, list) else []
    by_stage: dict[str, dict[str, Any]] = {}
    for stage_key in sorted(
        {
            str(row.get("stage_key") or "")
            for row in rows
            if isinstance(row, dict) and str(row.get("stage_key") or "")
        }
    ):
        stage_rows = [
            row
            for row in rows
            if isinstance(row, dict) and str(row.get("stage_key") or "") == stage_key
        ]
        status_semantics_counts: Counter[str] = Counter()
        status_unknown_count = 0
        for row in stage_rows:
            status_semantics_counts[str(row.get("status_semantics") or "")] += 1
            if str(row.get("status") or "").strip().lower() in {"", "unknown"}:
                status_unknown_count += 1
        by_stage[stage_key] = {
            "recipe_count": len(stage_rows),
            "status_unknown_count": status_unknown_count,
            "call_observed_count": sum(
                1 for row in stage_rows if bool(row.get("call_observed"))
            ),
            "output_signal_count": sum(
                1 for row in stage_rows if bool(row.get("output_signal"))
            ),
            "empty_output_signal_count": sum(
                1 for row in stage_rows if bool(row.get("empty_output_signal"))
            ),
            "status_semantics_counts": _counter_to_sorted_dict(status_semantics_counts),
        }
    return {
        "schema_version": "upload_bundle_stage_observability_summary.v1",
        "stage_count": len(by_stage),
        "by_stage": by_stage,
    }


def _upload_bundle_assert_recipe_correction_output_accounting(
    *,
    stage_observability_summary: dict[str, Any],
    correction_prompt_rows: list[dict[str, Any]] | None = None,
    call_inventory_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    stage_rows = (
        stage_observability_summary.get("by_stage")
        if isinstance(stage_observability_summary.get("by_stage"), dict)
        else {}
    )
    stage_payload = (
        stage_rows.get("recipe_refine")
        if isinstance(stage_rows, dict)
        else {}
    )
    stage_payload = stage_payload if isinstance(stage_payload, dict) else {}
    derived_recipe_count = int(_coerce_int(stage_payload.get("recipe_count")) or 0)
    derived_output_signal_count = int(_coerce_int(stage_payload.get("output_signal_count")) or 0)
    derived_empty_output_signal_count = int(
        _coerce_int(stage_payload.get("empty_output_signal_count")) or 0
    )

    prompt_rows = correction_prompt_rows if isinstance(correction_prompt_rows, list) else []
    observed_nonempty_recipe_output_count = 0
    observed_recipe_output_count = 0
    for prompt_row in prompt_rows:
        parsed_response = _parse_json_like(prompt_row.get("parsed_response"))
        for output_row in _upload_bundle_recipe_correction_output_rows(parsed_response):
            observed_recipe_output_count += 1
            metrics = _upload_bundle_recipe_correction_metrics(output_row)
            if not metrics["empty_output"]:
                observed_nonempty_recipe_output_count += 1

    correction_call_rows = [
        row
        for row in (call_inventory_rows or [])
        if isinstance(row, dict)
        and str(row.get("stage_key") or "").strip() == "recipe_refine"
    ]
    compact_nonempty_excerpt_re = re.compile(
        r'"cr"\s*:\s*\{.*?"(?:i|s)"\s*:\s*\[\s*"',
        re.DOTALL,
    )
    call_rows_with_nonempty_output = sum(
        1
        for row in correction_call_rows
        if (
            int(_coerce_int(row.get("extracted_ingredient_count")) or 0) > 0
            or int(_coerce_int(row.get("step_count")) or 0) > 0
            or int(_coerce_int(row.get("mapping_count")) or 0) > 0
        )
    )
    excerpt_rows_with_nonempty_compact_output = sum(
        1
        for row in correction_call_rows
        if compact_nonempty_excerpt_re.search(str(row.get("output_excerpt") or ""))
    )

    all_derived_empty = (
        derived_recipe_count > 0
        and derived_output_signal_count == 0
        and derived_empty_output_signal_count >= derived_recipe_count
    )
    contradiction = all_derived_empty and (
        observed_nonempty_recipe_output_count > 0
        or call_rows_with_nonempty_output > 0
        or excerpt_rows_with_nonempty_compact_output > 0
    )
    details = {
        "derived_recipe_count": derived_recipe_count,
        "derived_output_signal_count": derived_output_signal_count,
        "derived_empty_output_signal_count": derived_empty_output_signal_count,
        "observed_recipe_output_count": observed_recipe_output_count,
        "observed_nonempty_recipe_output_count": observed_nonempty_recipe_output_count,
        "call_rows_with_nonempty_output": call_rows_with_nonempty_output,
        "excerpt_rows_with_nonempty_compact_output": excerpt_rows_with_nonempty_compact_output,
    }
    if contradiction:
        raise ValueError(
            "recipe correction output accounting mismatch: non-empty correction outputs "
            "were observed while stage observability marked every correction output empty"
        )
    return details


def _upload_bundle_bundle_prompt_log_summary(
    *,
    process_manifest_payload: dict[str, Any],
    run_rows: list[dict[str, Any]],
    run_diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest_status = str(
        process_manifest_payload.get("full_prompt_log_status") or ""
    ).strip()
    codex_run_ids = {
        str(row.get("run_id") or "").strip()
        for row in run_rows
        if isinstance(row, dict)
        and _upload_bundle_is_codex_pipeline_enabled(row.get("llm_recipe_pipeline"))
    }
    diagnostic_by_run_id = {
        str(row.get("run_id") or "").strip(): row
        for row in run_diagnostics
        if isinstance(row, dict) and str(row.get("run_id") or "").strip()
    }
    codex_statuses = [
        str((diagnostic_by_run_id.get(run_id) or {}).get("full_prompt_log_status") or "").strip()
        for run_id in sorted(codex_run_ids)
    ]
    non_empty_codex_statuses = [status for status in codex_statuses if status]

    if manifest_status and manifest_status.lower() != "unknown":
        effective_status = manifest_status
        source = "process_manifest"
    elif not codex_run_ids:
        effective_status = "not_applicable"
        source = "derived_from_run_diagnostics"
    elif non_empty_codex_statuses and all(status == "complete" for status in non_empty_codex_statuses):
        effective_status = "complete"
        source = "derived_from_run_diagnostics"
    elif any(status == "complete" for status in non_empty_codex_statuses):
        effective_status = "partial"
        source = "derived_from_run_diagnostics"
    elif non_empty_codex_statuses:
        effective_status = "missing"
        source = "derived_from_run_diagnostics"
    else:
        effective_status = "unknown"
        source = "derived_from_run_diagnostics"

    full_prompt_log_rows = _coerce_int(process_manifest_payload.get("full_prompt_log_rows"))
    if full_prompt_log_rows is None:
        full_prompt_log_rows = sum(
            int(_coerce_int(row.get("full_prompt_log_rows")) or 0)
            for row in run_rows
            if isinstance(row, dict)
        )

    return {
        "status": effective_status,
        "status_source": source,
        "full_prompt_log_rows": int(full_prompt_log_rows or 0),
        "codex_run_count": len(codex_run_ids),
        "codex_runs_complete": sum(1 for status in codex_statuses if status == "complete"),
    }


def _upload_bundle_build_turn1_summary(
    *,
    pair_delta_summary: dict[str, Any],
    active_recipe_span_breakout: dict[str, Any],
    net_error_blame_summary: dict[str, Any],
    top_confusion_deltas: list[dict[str, Any]],
    triage_packet_rows: list[dict[str, Any]],
    triage_packet_sample_note: str,
    runtime_summary_payload: dict[str, Any],
    stage_observability_summary: dict[str, Any],
    regression_casebook: dict[str, Any],
) -> dict[str, Any]:
    bucket_rows = (
        net_error_blame_summary.get("bucket_rows")
        if isinstance(net_error_blame_summary.get("bucket_rows"), list)
        else []
    )
    ranked_buckets = [
        row
        for row in bucket_rows
        if isinstance(row, dict)
    ]
    ranked_buckets.sort(
        key=lambda row: (
            -int(_coerce_int(row.get("net_error_count")) or 0),
            -int(_coerce_int(row.get("new_error_count")) or 0),
            str(row.get("bucket") or ""),
        )
    )
    top_blame_buckets = ranked_buckets[:3]

    stage_rows = (
        stage_observability_summary.get("by_stage")
        if isinstance(stage_observability_summary.get("by_stage"), dict)
        else {}
    )
    stage_rows = stage_rows if isinstance(stage_rows, dict) else {}

    def _stage_gap_count(stage_key: str) -> int:
        payload = stage_rows.get(stage_key)
        payload = payload if isinstance(payload, dict) else {}
        semantics = payload.get("status_semantics_counts")
        semantics = semantics if isinstance(semantics, dict) else {}
        return int(_coerce_int(semantics.get("projection_or_scoring_gap")) or 0) + int(
            _coerce_int(semantics.get("nonempty_output_without_manifest_status")) or 0
        )

    diagnosis_flags: list[str] = []
    if bool(active_recipe_span_breakout.get("all_scored_lines_outside_active_recipe_spans")):
        diagnosis_flags.append("outside_span_contamination_dominant")
    if _stage_gap_count("recipe_refine") > 0 or _stage_gap_count(
        "recipe_build_final"
    ) > 0:
        diagnosis_flags.append("stage_projection_gap_present")
    if _coerce_float(pair_delta_summary.get("worst_pair_delta_overall_line_accuracy")) is not None:
        if (
            float(
                _coerce_float(pair_delta_summary.get("worst_pair_delta_overall_line_accuracy"))
                or 0.0
            )
            < 0.0
        ):
            diagnosis_flags.append("pair_level_regression_present")

    top_triage_rows = (
        []
        if str(triage_packet_sample_note or "").strip()
        else [
            {
                "recipe_id": str(row.get("recipe_id") or ""),
                "short_title": str(row.get("short_title") or ""),
                "changed_lines_codex_vs_baseline": int(
                    _coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0
                ),
                "delta_codex_minus_baseline": _coerce_float(
                    row.get("delta_codex_minus_baseline")
                ),
                "outside_span_wrong_line_count": int(
                    _coerce_int(row.get("outside_span_wrong_line_count")) or 0
                ),
                "final_recipe_empty_mapping": bool(row.get("final_recipe_empty_mapping")),
                "correction_warning_count": int(
                    _coerce_int(row.get("correction_warning_count")) or 0
                ),
            }
            for row in triage_packet_rows[:5]
            if isinstance(row, dict)
        ]
    )
    pair_count = int(_coerce_int(active_recipe_span_breakout.get("pair_count")) or 0)
    if pair_count > 0:
        recommended_read_order = [
            "analysis.benchmark_pair_inventory",
            "analysis.active_recipe_span_breakout",
            "analysis.net_error_blame_summary",
            "analysis.top_confusion_deltas",
            "analysis.changed_lines_stratified_sample",
            "analysis.triage_packet",
        ]
    else:
        recommended_read_order = [
            "analysis.active_recipe_span_breakout",
            "analysis.recipe_pipeline_context",
            "analysis.stage_observability_summary",
            "analysis.top_confusion_deltas",
            "analysis.call_inventory_runtime",
            "analysis.triage_packet",
        ]

    return {
        "schema_version": "upload_bundle_turn1_summary.v1",
        "diagnosis_flags": diagnosis_flags,
        "recommended_read_order": recommended_read_order,
        "severity": {
            "changed_lines_total_topline_context": int(
                _coerce_int(sum(
                    int(_coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0)
                    for row in triage_packet_rows
                    if isinstance(row, dict)
                ))
                or 0
            ),
            "worst_pair_delta_overall_line_accuracy": _coerce_float(
                pair_delta_summary.get("worst_pair_delta_overall_line_accuracy")
            ),
            "worst_pair_delta_macro_f1_excluding_other": _coerce_float(
                pair_delta_summary.get("worst_pair_delta_macro_f1_excluding_other")
            ),
            "worst_pair_delta_practical_f1": _coerce_float(
                pair_delta_summary.get("worst_pair_delta_practical_f1")
            ),
        },
        "active_recipe_span_breakout": {
            "recipe_span_count": int(
                _coerce_int(active_recipe_span_breakout.get("recipe_span_count")) or 0
            ),
            "pairs_with_zero_recipe_spans": int(
                _coerce_int(active_recipe_span_breakout.get("pairs_with_zero_recipe_spans"))
                or 0
            ),
            "all_scored_lines_outside_active_recipe_spans": bool(
                active_recipe_span_breakout.get("all_scored_lines_outside_active_recipe_spans")
            ),
            "outside_share_of_scored_lines": _coerce_float(
                active_recipe_span_breakout.get("outside_share_of_scored_lines")
            ),
            "turn1_note": str(active_recipe_span_breakout.get("turn1_note") or ""),
        },
        "top_blame_buckets": [
            {
                "bucket": str(row.get("bucket") or ""),
                "net_error_count": int(_coerce_int(row.get("net_error_count")) or 0),
                "share_of_net_error": _coerce_float(row.get("share_of_net_error")),
            }
            for row in top_blame_buckets
        ],
        "top_confusion_deltas": [
            {
                "gold_label": str(row.get("gold_label") or ""),
                "pred_label": str(row.get("pred_label") or ""),
                "delta_count": int(_coerce_int(row.get("delta_count")) or 0),
            }
            for row in top_confusion_deltas[:5]
            if isinstance(row, dict)
        ],
        "top_triage_rows_note": triage_packet_sample_note,
        "top_triage_rows": top_triage_rows,
        "runtime_snapshot": {
            "call_count": int(_coerce_int(runtime_summary_payload.get("call_count")) or 0),
            "calls_with_runtime": int(
                _coerce_int(runtime_summary_payload.get("calls_with_runtime")) or 0
            ),
            "calls_with_estimated_cost": int(
                _coerce_int(runtime_summary_payload.get("calls_with_estimated_cost")) or 0
            ),
            "total_duration_ms": _coerce_int(runtime_summary_payload.get("total_duration_ms")),
            "total_tokens": _coerce_int(runtime_summary_payload.get("total_tokens")),
            "estimated_cost_coverage_ratio": _coerce_float(
                runtime_summary_payload.get("estimated_cost_coverage_ratio")
            ),
        },
        "stage_observability": {
            stage_key: {
                "status_unknown_count": int(
                    _coerce_int((payload or {}).get("status_unknown_count")) or 0
                ),
                "call_observed_count": int(
                    _coerce_int((payload or {}).get("call_observed_count")) or 0
                ),
                "empty_output_signal_count": int(
                    _coerce_int((payload or {}).get("empty_output_signal_count")) or 0
                ),
                "status_semantics_counts": (
                    dict((payload or {}).get("status_semantics_counts"))
                    if isinstance((payload or {}).get("status_semantics_counts"), dict)
                    else {}
                ),
            }
            for stage_key, payload in sorted(stage_rows.items())
            if isinstance(payload, dict)
        },
        "targeted_regression_affordance": {
            "target_request_status": str(
                regression_casebook.get("target_request_status") or "unknown"
            ),
            "requested_targets": list(regression_casebook.get("requested_targets") or []),
            "found_targets": list(regression_casebook.get("found_targets") or []),
            "missing_targets": list(regression_casebook.get("missing_targets") or []),
            "suggested_targets": list(regression_casebook.get("suggested_targets") or []),
            "suggested_target_source": str(
                regression_casebook.get("suggested_target_source") or ""
            ),
        },
    }


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


def _upload_bundle_normalized_label(value: Any) -> str:
    return str(value or "").strip().upper()


def _upload_bundle_classify_explicit_escalation_issue(
    *,
    line_role_label: Any,
    codex_pred: Any,
    gold_label: Any,
) -> tuple[str | None, str | None]:
    route_label = _upload_bundle_normalized_label(line_role_label)
    final_label = _upload_bundle_normalized_label(codex_pred)
    gold = _upload_bundle_normalized_label(gold_label)
    if route_label == "NONRECIPE_EXCLUDE" and final_label == "KNOWLEDGE":
        return (
            "exclusion_leak_into_final_knowledge",
            "line-role excluded this row, but final authority still surfaced KNOWLEDGE.",
        )
    if (
        route_label == "NONRECIPE_CANDIDATE"
        and final_label == "KNOWLEDGE"
        and gold == "OTHER"
    ):
        return (
            "route_broadness_other_promoted_to_knowledge",
            "line-role routed this row into knowledge review and final authority kept KNOWLEDGE against OTHER gold.",
        )
    return None, None


def _upload_bundle_collect_line_role_prediction_rows(
    *,
    source_root: Path,
    run_dir_by_id: dict[str, Path],
    run_dirs: list[Path] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    relative_paths: list[str] = []
    for run_dir in _upload_bundle_iter_unique_run_dirs(
        run_dirs=run_dirs,
        run_dir_by_id=run_dir_by_id,
    ):
        path = run_dir / "line-role-pipeline" / "line_role_predictions.jsonl"
        if not path.is_file():
            continue
        run_manifest = _upload_bundle_load_json_object(run_dir / "run_manifest.json")
        run_id = str(run_manifest.get("run_id") or run_dir.name).strip() or run_dir.name
        source_payload = (
            run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
        )
        source_path = source_payload.get("path") if isinstance(source_payload, dict) else None
        source_hash = source_payload.get("source_hash") if isinstance(source_payload, dict) else None
        source_file = _source_file_name(source_path if isinstance(source_path, str) else None)
        source_key = _source_key(
            source_hash if isinstance(source_hash, str) else None,
            source_file,
        )
        try:
            output_subdir = str(run_dir.resolve().relative_to(source_root).as_posix())
        except Exception:  # noqa: BLE001
            output_subdir = run_dir.name
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
            row_payload["source_key"] = source_key
            row_payload["output_subdir"] = output_subdir
            row_payload["escalation_reasons"] = _coerce_str_list(
                row_payload.get("escalation_reasons")
            )
            rows.append(row_payload)
    return rows, sorted(set(relative_paths))


def _upload_bundle_collect_line_role_artifact_lookups(
    *,
    source_root: Path,
    run_dir_by_id: dict[str, Path],
    run_dirs: list[Path] | None = None,
) -> tuple[dict[tuple[str, str], LineRoleArtifactLookup], dict[str, LineRoleArtifactLookup]]:
    lookups_by_source_run: dict[tuple[str, str], LineRoleArtifactLookup] = {}
    lookups_by_run_id: dict[str, LineRoleArtifactLookup] = {}
    for run_dir in _upload_bundle_iter_unique_run_dirs(
        run_dirs=run_dirs,
        run_dir_by_id=run_dir_by_id,
    ):
        path = run_dir / "line-role-pipeline" / "line_role_predictions.jsonl"
        if not path.is_file():
            continue
        run_manifest = _upload_bundle_load_json_object(run_dir / "run_manifest.json")
        run_id = str(run_manifest.get("run_id") or run_dir.name).strip() or run_dir.name
        source_payload = (
            run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
        )
        source_path = source_payload.get("path") if isinstance(source_payload, dict) else None
        source_hash = source_payload.get("source_hash") if isinstance(source_payload, dict) else None
        source_file = _source_file_name(source_path if isinstance(source_path, str) else None)
        source_key = _source_key(
            source_hash if isinstance(source_hash, str) else None,
            source_file,
        )
        lookup = LineRoleArtifactLookup.from_run_dir(run_dir)
        lookups_by_source_run[(source_key, run_id)] = lookup
        lookups_by_run_id[run_id] = lookup
    return lookups_by_source_run, lookups_by_run_id


def _upload_bundle_build_explicit_escalation_changed_lines_packet(
    *,
    source_root: Path,
    run_dir_by_id: dict[str, Path],
    changed_line_rows: list[dict[str, Any]],
    run_dirs: list[Path] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    prediction_rows, prediction_files = _upload_bundle_collect_line_role_prediction_rows(
        source_root=source_root,
        run_dir_by_id=run_dir_by_id,
        run_dirs=run_dirs,
    )
    lookups_by_source_run, lookups_by_run_id = _upload_bundle_collect_line_role_artifact_lookups(
        source_root=source_root,
        run_dir_by_id=run_dir_by_id,
        run_dirs=run_dirs,
    )
    if not prediction_rows:
        return (
            {
                "schema_version": UPLOAD_BUNDLE_EXPLICIT_ESCALATION_CHANGED_LINES_SCHEMA_VERSION,
                "available": False,
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

    packet_rows: list[dict[str, Any]] = []
    issue_kind_counts: Counter[str] = Counter()
    attribution_bucket_counts: Counter[str] = Counter()
    for changed_row in changed_line_rows:
        if not isinstance(changed_row, dict):
            continue
        source_key = str(changed_row.get("source_key") or "").strip()
        codex_run_id = str(changed_row.get("codex_run_id") or "").strip()
        line_index = _coerce_int(changed_row.get("line_index"))
        if not codex_run_id or line_index is None:
            continue
        lookup = lookups_by_source_run.get((source_key, codex_run_id))
        if lookup is None:
            lookup = lookups_by_run_id.get(codex_run_id)
        if lookup is None:
            continue
        selected = lookup.resolve_prediction_row(
            line_index=int(line_index),
            line_text=changed_row.get("current_line"),
        )
        if not isinstance(selected, dict):
            continue
        escalation_reasons = _coerce_str_list(selected.get("escalation_reasons"))
        if not escalation_reasons:
            continue
        issue_kind, issue_note = _upload_bundle_classify_explicit_escalation_issue(
            line_role_label=selected.get("label"),
            codex_pred=changed_row.get("codex_pred"),
            gold_label=changed_row.get("gold_label"),
        )
        attribution_bucket_hint = (
            "nonrecipe_authority"
            if issue_kind == "exclusion_leak_into_final_knowledge"
            else "line_role"
        )
        if issue_kind:
            issue_kind_counts[issue_kind] += 1
        attribution_bucket_counts[attribution_bucket_hint] += 1
        packet_rows.append(
            {
                "source_key": str(changed_row.get("source_key") or ""),
                "codex_run_id": codex_run_id,
                "baseline_run_id": str(changed_row.get("baseline_run_id") or ""),
                "recipe_id": str(changed_row.get("recipe_id") or ""),
                "line_index": int(line_index),
                "atomic_index": _coerce_int(selected.get("atomic_index")),
                "escalation_reasons": escalation_reasons,
                "label": str(selected.get("label") or "OTHER"),
                "decided_by": str(selected.get("decided_by") or "unknown"),
                "issue_kind": issue_kind,
                "issue_note": issue_note,
                "attribution_bucket_hint": attribution_bucket_hint,
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
            str(row.get("recipe_id") or ""),
            int(_coerce_int(row.get("line_index")) or 0),
        )
    )

    return (
        {
            "schema_version": UPLOAD_BUNDLE_EXPLICIT_ESCALATION_CHANGED_LINES_SCHEMA_VERSION,
            "available": True,
            "prediction_files": prediction_files,
            "changed_line_rows_considered": len(changed_line_rows),
            "matched_prediction_rows": len(packet_rows),
            "row_count": len(packet_rows),
            "issue_kind_counts": _counter_to_sorted_dict(issue_kind_counts),
            "attribution_bucket_counts": _counter_to_sorted_dict(attribution_bucket_counts),
            "empty_packet_note": (
                ""
                if packet_rows
                else (
                    "No changed lines intersected explicit line-role escalation reasons."
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
    recipe_pipeline_context: dict[str, Any] | None = None,
    explicit_escalation_rows: list[dict[str, Any]] | None = None,
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

    explicit_issue_by_changed_line_key: dict[
        tuple[str, str, str, str, int], str
    ] = {}
    for row in explicit_escalation_rows or []:
        if not isinstance(row, dict):
            continue
        source_key = str(row.get("source_key") or "")
        codex_run_id = str(row.get("codex_run_id") or "")
        baseline_run_id = str(row.get("baseline_run_id") or "")
        recipe_id = str(row.get("recipe_id") or "")
        line_index = _coerce_int(row.get("line_index"))
        issue_kind = str(row.get("issue_kind") or "").strip()
        if not (source_key and codex_run_id and issue_kind and line_index is not None):
            continue
        explicit_issue_by_changed_line_key[
            (source_key, codex_run_id, baseline_run_id, recipe_id, int(line_index))
        ] = issue_kind

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
        explicit_issue = explicit_issue_by_changed_line_key.get(
            (
                str(changed_row.get("source_key") or ""),
                str(changed_row.get("codex_run_id") or ""),
                str(changed_row.get("baseline_run_id") or ""),
                str(changed_row.get("recipe_id") or ""),
                int(_coerce_int(changed_row.get("line_index")) or 0),
            )
        )
        if explicit_issue == "exclusion_leak_into_final_knowledge":
            return "nonrecipe_authority"
        blame_bucket = "line_role"
        if isinstance(triage_row, dict):
            transport_mismatch = bool(triage_row.get("transport_mismatch"))
            final_recipe_empty_mapping = bool(triage_row.get("final_recipe_empty_mapping"))
            final_recipe_warning_count = int(
                _coerce_int(triage_row.get("final_recipe_warning_count")) or 0
            )
            correction_warning_count = int(
                _coerce_int(triage_row.get("correction_warning_count")) or 0
            )
            correction_degradation = _coerce_str_list(
                triage_row.get("correction_degradation_reasons")
            )
            build_final_execution_mode = str(
                triage_row.get("build_final_execution_mode") or ""
            ).strip().lower()
            build_final_routing_reason = str(
                triage_row.get("build_final_routing_reason") or ""
            ).strip()
            build_final_fallback_reason = str(
                triage_row.get("build_final_fallback_reason") or ""
            ).strip()
            build_final_status_problem = _upload_bundle_status_is_problem(
                triage_row.get("build_final_status")
            )
            correction_status_problem = _upload_bundle_status_is_problem(
                triage_row.get("correction_status")
            )
            build_final_mode_implies_fallback = build_final_execution_mode in {
                "fallback",
                "fallback_or_partial",
                "projection_only",
                "route_to_baseline",
            }
            if (
                transport_mismatch
                or build_final_mode_implies_fallback
                or bool(build_final_routing_reason)
                or bool(build_final_fallback_reason)
            ):
                blame_bucket = "routing_or_fallback"
            elif (
                final_recipe_empty_mapping
                or final_recipe_warning_count > 0
                or build_final_status_problem
            ):
                blame_bucket = "final_recipe"
            elif (
                correction_warning_count > 0
                or bool(correction_degradation)
                or correction_status_problem
            ):
                blame_bucket = "recipe_correction"
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
        "nonrecipe_authority",
        "line_role",
        "recipe_correction",
        "final_recipe",
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
            "nonrecipe_authority": "Rows where line-role explicitly excluded the text but final authority still leaked it into KNOWLEDGE.",
            "line_role": "Rows where codex line-role decisions are most likely responsible.",
            "recipe_correction": "Rows with recipe-correction warnings or degradation signals suggesting correction-stage loss.",
            "final_recipe": "Rows with final-recipe empty-mapping, warnings, or failing final-stage status.",
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
    run_dir_by_output_subdir: dict[str, Path] | None = None,
) -> dict[str, Any]:
    settings_keys = list(RUN_CONFIG_KEYS_OF_INTEREST) + ["prediction_run_config_hash"]
    run_rows_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for row in run_rows:
        if not isinstance(row, dict):
            continue
        run_id = str(row.get("run_id") or "").strip()
        output_subdir = str(row.get("output_subdir") or "").strip()
        if not run_id and not output_subdir:
            continue
        identity = (run_id, output_subdir)
        run_rows_by_identity.setdefault(identity, row)

    run_settings_rows: list[dict[str, Any]] = []
    for run_id, output_subdir in sorted(run_rows_by_identity.keys()):
        row = run_rows_by_identity[(run_id, output_subdir)]
        run_dir = None
        if isinstance(run_dir_by_output_subdir, dict) and output_subdir:
            candidate = run_dir_by_output_subdir.get(output_subdir)
            if isinstance(candidate, Path):
                run_dir = candidate
        if run_dir is None:
            candidate = run_dir_by_id.get(run_id)
            run_dir = candidate if isinstance(candidate, Path) else None
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
                "output_subdir": output_subdir,
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

    return {
        "content_equivalent_groups": content_equivalent_groups,
    }


def _upload_bundle_build_stage_separated_comparison(
    *,
    recipe_triage_rows: list[dict[str, Any]],
    per_label_metrics: list[dict[str, Any]],
    comparison_pairs: list[dict[str, Any]],
    pass_stage_per_label_metrics: dict[str, Any],
    recipe_pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return render_stage_separated_comparison(
        recipe_triage_rows=recipe_triage_rows,
        per_label_metrics=per_label_metrics,
        comparison_pairs=comparison_pairs,
        pass_stage_per_label_metrics=pass_stage_per_label_metrics,
        recipe_pipeline_context=recipe_pipeline_context,
    )


def _upload_bundle_source_key_for_row(row: dict[str, Any]) -> str:
    source_key = str(row.get("source_key") or "").strip()
    if source_key:
        return source_key
    source_hash = str(row.get("source_hash") or "").strip()
    source_file = _source_file_name(str(row.get("source_file") or "").strip() or None)
    return _source_key(source_hash or None, source_file)


def _upload_bundle_source_metadata(
    *,
    run_rows: list[dict[str, Any]],
    comparison_pairs: list[dict[str, Any]],
    recipe_triage_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}

    def _register(source_key: str, source_file: Any) -> None:
        key = str(source_key or "").strip()
        if not key:
            return
        source_file_name = _source_file_name(str(source_file or "").strip() or None)
        entry = metadata.setdefault(
            key,
            {
                "source_key": key,
                "source_file": source_file_name,
            },
        )
        if not entry.get("source_file") and source_file_name:
            entry["source_file"] = source_file_name

    for row in run_rows:
        if not isinstance(row, dict):
            continue
        _register(_upload_bundle_source_key_for_row(row), row.get("source_file"))

    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        _register(str(pair.get("source_key") or ""), pair.get("source_file"))
        codex_run = pair.get("codex_run")
        if isinstance(codex_run, dict):
            _register(str(pair.get("source_key") or ""), codex_run.get("source_file"))
        baseline_run = pair.get("baseline_run")
        if isinstance(baseline_run, dict):
            _register(str(pair.get("source_key") or ""), baseline_run.get("source_file"))

    for row in recipe_triage_rows:
        if not isinstance(row, dict):
            continue
        _register(str(row.get("source_key") or ""), row.get("source_file"))

    return metadata


def _upload_bundle_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(sum(values)) / float(len(values)), 6)


def _upload_bundle_stringify_value(value: Any) -> str:
    if value is None:
        return "<none>"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _upload_bundle_build_book_scorecard(
    *,
    comparison_pairs: list[dict[str, Any]],
    source_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    metric_keys = (
        "overall_line_accuracy",
        "macro_f1_excluding_other",
        "practical_f1",
    )
    by_source: dict[str, dict[str, Any]] = {}
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        source_key = str(pair.get("source_key") or "").strip()
        if not source_key:
            continue
        bucket = by_source.setdefault(
            source_key,
            {
                "pair_count": 0,
                "changed_line_total": 0,
                "baseline_metrics": defaultdict(list),
                "codex_metrics": defaultdict(list),
                "delta_metrics": defaultdict(list),
                "wins": [],
                "regressions": [],
            },
        )
        bucket["pair_count"] += 1
        bucket["changed_line_total"] += int(_coerce_int(pair.get("changed_line_count")) or 0)

        codex_run = pair.get("codex_run")
        codex_run = codex_run if isinstance(codex_run, dict) else {}
        baseline_run = pair.get("baseline_run")
        baseline_run = baseline_run if isinstance(baseline_run, dict) else {}
        delta_payload = pair.get("delta_codex_minus_baseline")
        delta_payload = delta_payload if isinstance(delta_payload, dict) else {}
        codex_run_id = str(codex_run.get("run_id") or "")
        baseline_run_id = str(baseline_run.get("run_id") or "")

        for metric_key in metric_keys:
            baseline_value = _coerce_float(baseline_run.get(metric_key))
            codex_value = _coerce_float(codex_run.get(metric_key))
            delta_value = _coerce_float(delta_payload.get(metric_key))
            if delta_value is None and baseline_value is not None and codex_value is not None:
                delta_value = _delta(codex_value, baseline_value)

            if baseline_value is not None:
                bucket["baseline_metrics"][metric_key].append(float(baseline_value))
            if codex_value is not None:
                bucket["codex_metrics"][metric_key].append(float(codex_value))
            if delta_value is not None:
                delta_float = float(delta_value)
                bucket["delta_metrics"][metric_key].append(delta_float)
                metric_row = {
                    "metric": metric_key,
                    "delta": round(delta_float, 6),
                    "codex_run_id": codex_run_id,
                    "baseline_run_id": baseline_run_id,
                }
                if delta_float > 0:
                    bucket["wins"].append(metric_row)
                elif delta_float < 0:
                    bucket["regressions"].append(metric_row)

    rows: list[dict[str, Any]] = []
    for source_key in sorted(by_source.keys()):
        bucket = by_source.get(source_key)
        if not isinstance(bucket, dict):
            continue
        source_info = source_metadata.get(source_key, {})
        wins = sorted(
            bucket.get("wins") or [],
            key=lambda row: (
                -_float_or_zero(row.get("delta")),
                str(row.get("metric") or ""),
            ),
        )[:5]
        regressions = sorted(
            bucket.get("regressions") or [],
            key=lambda row: (
                _float_or_zero(row.get("delta")),
                str(row.get("metric") or ""),
            ),
        )[:5]
        row = {
            "source_key": source_key,
            "source_file": source_info.get("source_file"),
            "pair_count": int(bucket.get("pair_count") or 0),
            "changed_line_total": int(bucket.get("changed_line_total") or 0),
            "vanilla": {
                metric_key: _upload_bundle_mean(
                    [float(value) for value in (bucket.get("baseline_metrics", {}).get(metric_key) or [])]
                )
                for metric_key in metric_keys
            },
            "codex": {
                metric_key: _upload_bundle_mean(
                    [float(value) for value in (bucket.get("codex_metrics", {}).get(metric_key) or [])]
                )
                for metric_key in metric_keys
            },
            "delta": {
                metric_key: _upload_bundle_mean(
                    [float(value) for value in (bucket.get("delta_metrics", {}).get(metric_key) or [])]
                )
                for metric_key in metric_keys
            },
            "best_wins": wins,
            "worst_regressions": regressions,
            "best_wins_count": len(bucket.get("wins") or []),
            "worst_regressions_count": len(bucket.get("regressions") or []),
        }
        rows.append(row)

    rows.sort(
        key=lambda row: (
            _float_or_zero((row.get("delta") or {}).get("practical_f1")),
            _float_or_zero((row.get("delta") or {}).get("overall_line_accuracy")),
            -int(_coerce_int(row.get("changed_line_total")) or 0),
            str(row.get("source_key") or ""),
        )
    )
    return {
        "schema_version": "upload_bundle_book_scorecard.v1",
        "book_count": len(rows),
        "rows": rows,
    }


def _upload_bundle_build_ablation_summary(
    comparison_pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    by_key: dict[str, dict[str, Any]] = {}
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        delta_payload = pair.get("delta_codex_minus_baseline")
        delta_payload = delta_payload if isinstance(delta_payload, dict) else {}
        practical_delta = _coerce_float(delta_payload.get("practical_f1"))
        overall_delta = _coerce_float(delta_payload.get("overall_line_accuracy"))
        macro_delta = _coerce_float(delta_payload.get("macro_f1_excluding_other"))
        diff_payload = pair.get("run_config_differences")
        diff_payload = diff_payload if isinstance(diff_payload, dict) else {}
        diff_items = (
            list(diff_payload.items()) if diff_payload else [("__no_config_diff__", {})]
        )
        for diff_key, diff_row in diff_items:
            diff_bucket = by_key.setdefault(
                str(diff_key),
                {
                    "pair_count": 0,
                    "practical_deltas": [],
                    "overall_deltas": [],
                    "macro_deltas": [],
                    "improved_pairs": 0,
                    "regressed_pairs": 0,
                    "codex_values": Counter(),
                    "baseline_values": Counter(),
                },
            )
            diff_bucket["pair_count"] += 1
            if practical_delta is not None:
                diff_bucket["practical_deltas"].append(float(practical_delta))
                if float(practical_delta) > 0:
                    diff_bucket["improved_pairs"] += 1
                elif float(practical_delta) < 0:
                    diff_bucket["regressed_pairs"] += 1
            if overall_delta is not None:
                diff_bucket["overall_deltas"].append(float(overall_delta))
            if macro_delta is not None:
                diff_bucket["macro_deltas"].append(float(macro_delta))
            if isinstance(diff_row, dict):
                diff_bucket["codex_values"][
                    _upload_bundle_stringify_value(diff_row.get("codex"))
                ] += 1
                diff_bucket["baseline_values"][
                    _upload_bundle_stringify_value(diff_row.get("baseline"))
                ] += 1

    rows: list[dict[str, Any]] = []
    for diff_key in sorted(by_key.keys()):
        bucket = by_key.get(diff_key)
        if not isinstance(bucket, dict):
            continue
        rows.append(
            {
                "ablation_key": diff_key,
                "pair_count": int(bucket.get("pair_count") or 0),
                "avg_delta_practical_f1": _upload_bundle_mean(
                    [float(value) for value in (bucket.get("practical_deltas") or [])]
                ),
                "avg_delta_overall_line_accuracy": _upload_bundle_mean(
                    [float(value) for value in (bucket.get("overall_deltas") or [])]
                ),
                "avg_delta_macro_f1_excluding_other": _upload_bundle_mean(
                    [float(value) for value in (bucket.get("macro_deltas") or [])]
                ),
                "improved_pairs": int(bucket.get("improved_pairs") or 0),
                "regressed_pairs": int(bucket.get("regressed_pairs") or 0),
                "codex_values": [
                    {"value": value, "count": count}
                    for value, count in Counter(bucket.get("codex_values") or {}).most_common(5)
                ],
                "baseline_values": [
                    {"value": value, "count": count}
                    for value, count in Counter(bucket.get("baseline_values") or {}).most_common(5)
                ],
            }
        )
    rows.sort(
        key=lambda row: (
            -int(_coerce_int(row.get("pair_count")) or 0),
            _float_or_zero(row.get("avg_delta_practical_f1")),
            str(row.get("ablation_key") or ""),
        )
    )
    return {
        "schema_version": "upload_bundle_ablation_summary.v1",
        "row_count": len(rows),
        "rows": rows,
    }


def _upload_bundle_build_outside_span_summary_by_book(
    *,
    recipe_triage_rows: list[dict[str, Any]],
    comparison_pairs: list[dict[str, Any]],
    source_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    changed_line_totals: Counter[str] = Counter()
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        source_key = str(pair.get("source_key") or "").strip()
        if not source_key:
            continue
        changed_line_totals[source_key] += int(_coerce_int(pair.get("changed_line_count")) or 0)

    by_source: dict[str, dict[str, Any]] = {}
    for row in recipe_triage_rows:
        if not isinstance(row, dict):
            continue
        source_key = str(row.get("source_key") or "").strip()
        if not source_key:
            continue
        recipe_id = str(row.get("recipe_id") or "").strip()
        outside_count = int(_coerce_int(row.get("outside_span_wrong_line_count")) or 0)
        status_top = str(row.get("outside_span_trace_status_top") or "").strip() or "missing"
        bucket = by_source.setdefault(
            source_key,
            {
                "recipe_keys": set(),
                "recipes_with_outside": set(),
                "outside_span_wrong_line_total": 0,
                "trace_status_counts": Counter(),
                "dropped_page_markers": 0,
                "folded_page_markers": 0,
            },
        )
        recipe_key = (str(row.get("codex_run_id") or ""), recipe_id)
        if recipe_id:
            bucket["recipe_keys"].add(recipe_key)
        if outside_count > 0 and recipe_id:
            bucket["recipes_with_outside"].add(recipe_key)
        bucket["outside_span_wrong_line_total"] += outside_count
        bucket["trace_status_counts"][status_top] += 1
        bucket["dropped_page_markers"] += int(
            _coerce_int(row.get("evidence_dropped_page_markers")) or 0
        )
        bucket["folded_page_markers"] += int(
            _coerce_int(row.get("evidence_folded_page_markers")) or 0
        )

    rows: list[dict[str, Any]] = []
    for source_key in sorted(by_source.keys()):
        bucket = by_source.get(source_key)
        if not isinstance(bucket, dict):
            continue
        recipe_count = len(bucket.get("recipe_keys") or set())
        recipes_with_outside = len(bucket.get("recipes_with_outside") or set())
        outside_total = int(bucket.get("outside_span_wrong_line_total") or 0)
        changed_line_total = int(changed_line_totals.get(source_key) or 0)
        source_info = source_metadata.get(source_key, {})
        rows.append(
            {
                "source_key": source_key,
                "source_file": source_info.get("source_file"),
                "recipe_count": recipe_count,
                "recipes_with_outside_span": recipes_with_outside,
                "outside_span_wrong_line_total": outside_total,
                "outside_span_recipe_ratio": (
                    round(recipes_with_outside / recipe_count, 6) if recipe_count > 0 else 0.0
                ),
                "outside_span_vs_changed_line_ratio": (
                    round(outside_total / changed_line_total, 6)
                    if changed_line_total > 0
                    else None
                ),
                "changed_line_total": changed_line_total,
                "trace_status_counts": _counter_to_sorted_dict(
                    Counter(bucket.get("trace_status_counts") or {})
                ),
                "evidence_dropped_page_markers": int(
                    bucket.get("dropped_page_markers") or 0
                ),
                "evidence_folded_page_markers": int(
                    bucket.get("folded_page_markers") or 0
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            -int(_coerce_int(row.get("outside_span_wrong_line_total")) or 0),
            -int(_coerce_int(row.get("recipes_with_outside_span")) or 0),
            str(row.get("source_key") or ""),
        )
    )
    return {
        "schema_version": "upload_bundle_outside_span_by_book.v1",
        "row_count": len(rows),
        "rows": rows,
    }


def _upload_bundle_build_chapter_page_type_breakdown(
    *,
    source_root: Path,
    discovered_run_dirs: list[Path],
    run_rows: list[dict[str, Any]],
    changed_line_rows: list[dict[str, Any]],
    recipe_triage_rows: list[dict[str, Any]],
    source_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    chapter_fields = (
        "chapter",
        "chapter_title",
        "chapter_name",
        "section",
        "section_title",
    )
    page_type_fields = (
        "page_type",
        "page_kind",
        "page_label",
        "content_type",
    )

    run_source_by_subdir: dict[str, str] = {}
    for row in run_rows:
        if not isinstance(row, dict):
            continue
        output_subdir = str(row.get("output_subdir") or "").strip()
        source_key = _upload_bundle_source_key_for_row(row)
        if output_subdir and source_key:
            run_source_by_subdir.setdefault(output_subdir, source_key)

    by_source: dict[str, dict[str, Any]] = {}

    def _bucket_for_source(source_key: str) -> dict[str, Any]:
        source_info = source_metadata.get(source_key, {})
        return by_source.setdefault(
            source_key,
            {
                "source_key": source_key,
                "source_file": source_info.get("source_file"),
                "run_count": 0,
                "span_region_counts": Counter(),
                "page_type_counts": Counter(),
                "chapter_counts": Counter(),
                "evidence_dropped_page_markers": 0,
                "evidence_folded_page_markers": 0,
            },
        )

    for row in changed_line_rows:
        if not isinstance(row, dict):
            continue
        source_key = str(row.get("source_key") or "").strip()
        if not source_key:
            continue
        span_region = str(row.get("span_region") or "").strip() or "unknown"
        _bucket_for_source(source_key)["span_region_counts"][span_region] += 1

    for row in recipe_triage_rows:
        if not isinstance(row, dict):
            continue
        source_key = str(row.get("source_key") or "").strip()
        if not source_key:
            continue
        bucket = _bucket_for_source(source_key)
        bucket["evidence_dropped_page_markers"] += int(
            _coerce_int(row.get("evidence_dropped_page_markers")) or 0
        )
        bucket["evidence_folded_page_markers"] += int(
            _coerce_int(row.get("evidence_folded_page_markers")) or 0
        )

    global_chapter_counts: Counter[str] = Counter()
    global_page_type_counts: Counter[str] = Counter()
    for run_dir in discovered_run_dirs:
        if not isinstance(run_dir, Path):
            continue
        prediction_path = run_dir / "line-role-pipeline" / "line_role_predictions.jsonl"
        if not prediction_path.is_file():
            continue
        run_manifest = _upload_bundle_load_json_object(run_dir / "run_manifest.json")
        manifest_source = (
            run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
        )
        source_path = manifest_source.get("path") if isinstance(manifest_source, dict) else None
        source_hash = (
            manifest_source.get("source_hash") if isinstance(manifest_source, dict) else None
        )
        source_file = _source_file_name(source_path if isinstance(source_path, str) else None)
        source_key = _source_key(
            source_hash if isinstance(source_hash, str) else None,
            source_file,
        )
        try:
            run_subdir = str(run_dir.resolve().relative_to(source_root).as_posix())
        except Exception:  # noqa: BLE001
            run_subdir = run_dir.name
        source_key = run_source_by_subdir.get(run_subdir, source_key)
        if not source_key:
            continue
        bucket = _bucket_for_source(source_key)
        bucket["run_count"] = int(bucket.get("run_count") or 0) + 1
        for row in _iter_jsonl(prediction_path):
            if not isinstance(row, dict):
                continue
            page_type = ""
            for key in page_type_fields:
                value = str(row.get(key) or "").strip()
                if value:
                    page_type = value
                    break
            if not page_type:
                within_recipe_span = row.get("within_recipe_span")
                if isinstance(within_recipe_span, bool):
                    page_type = (
                        "inside_active_recipe_span"
                        if within_recipe_span
                        else "outside_active_recipe_span"
                    )
            if page_type:
                bucket["page_type_counts"][page_type] += 1
                global_page_type_counts[page_type] += 1

            chapter_value = ""
            for key in chapter_fields:
                value = str(row.get(key) or "").strip()
                if value:
                    chapter_value = value
                    break
            if chapter_value:
                bucket["chapter_counts"][chapter_value] += 1
                global_chapter_counts[chapter_value] += 1

    rows: list[dict[str, Any]] = []
    for source_key in sorted(by_source.keys()):
        bucket = by_source.get(source_key)
        if not isinstance(bucket, dict):
            continue
        chapter_counts = Counter(bucket.get("chapter_counts") or {})
        rows.append(
            {
                "source_key": source_key,
                "source_file": bucket.get("source_file"),
                "run_count": int(bucket.get("run_count") or 0),
                "span_region_counts": _counter_to_sorted_dict(
                    Counter(bucket.get("span_region_counts") or {})
                ),
                "page_type_counts": _counter_to_sorted_dict(
                    Counter(bucket.get("page_type_counts") or {})
                ),
                "chapter_counts_top": [
                    {"chapter": chapter, "count": count}
                    for chapter, count in chapter_counts.most_common(10)
                ],
                "evidence_page_markers": {
                    "dropped": int(bucket.get("evidence_dropped_page_markers") or 0),
                    "folded": int(bucket.get("evidence_folded_page_markers") or 0),
                },
            }
        )
    rows.sort(
        key=lambda row: (
            -sum(int(value) for value in (row.get("page_type_counts") or {}).values()),
            -sum(int(value) for value in (row.get("span_region_counts") or {}).values()),
            str(row.get("source_key") or ""),
        )
    )

    return {
        "schema_version": "upload_bundle_chapter_page_type_breakdown.v1",
        "book_count": len(rows),
        "chapter_available": bool(global_chapter_counts),
        "chapter_unavailable_reason": (
            ""
            if global_chapter_counts
            else (
                "No chapter-like fields were present in line_role_predictions.jsonl "
                "(checked: chapter/chapter_title/chapter_name/section/section_title)."
            )
        ),
        "page_type_available": bool(global_page_type_counts),
        "page_type_fields_checked": list(page_type_fields),
        "global_page_type_counts": _counter_to_sorted_dict(global_page_type_counts),
        "global_chapter_counts_top": [
            {"chapter": chapter, "count": count}
            for chapter, count in global_chapter_counts.most_common(20)
        ],
        "rows": rows,
    }


def _upload_bundle_build_top_regression_packets_with_decision_trace(
    *,
    regression_casebook: dict[str, Any],
    limit: int = 10,
) -> dict[str, Any]:
    packets_raw = regression_casebook.get("packets")
    packets_raw = packets_raw if isinstance(packets_raw, list) else []
    packets: list[dict[str, Any]] = []
    for packet in packets_raw:
        if not isinstance(packet, dict):
            continue
        packet_copy = dict(packet)
        packet_copy["decision_trace"] = {
            "selection_reason": str(packet.get("selection_reason") or ""),
            "build_intermediate_summary": packet.get("build_intermediate_summary"),
            "recipe_correction_summary": packet.get("correction_summary"),
            "recipe_build_final_summary": packet.get("build_final_summary"),
            "transport_summary": packet.get("transport_summary"),
            "evidence_normalization_summary": packet.get(
                "evidence_normalization_summary"
            ),
            "warning_summary": str(packet.get("warning_summary") or ""),
            "bridge_anomaly_summary": str(packet.get("bridge_anomaly_summary") or ""),
        }
        packets.append(packet_copy)

    packets.sort(
        key=lambda row: (
            _float_or_zero(row.get("delta_codex_minus_baseline")),
            -int(_coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0),
            str(row.get("recipe_id") or ""),
        )
    )
    packets = packets[: max(int(limit), 0)]
    return {
        "schema_version": "upload_bundle_top_regression_packets.v1",
        "packet_count": len(packets),
        "packets": packets,
    }


def _write_upload_bundle_three_files(
    *,
    output_dir: Path,
    source_dir: Path | None = None,
    high_level_only: bool = False,
    target_bundle_size_bytes: int | None = None,
    source_model: UploadBundleSourceModel | None = None,
) -> dict[str, Any]:
    source_root = source_dir.resolve() if isinstance(source_dir, Path) else output_dir.resolve()
    output_root = output_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    group_target_size_bytes = (
        max(int(target_bundle_size_bytes), 1)
        if high_level_only and target_bundle_size_bytes is not None
        else GROUP_UPLOAD_BUNDLE_TARGET_BYTES
    )
    effective_group_target_size_bytes = (
        max(group_target_size_bytes // len(UPLOAD_BUNDLE_REVIEW_PROFILE_DIR_NAMES), 1)
        if high_level_only and UPLOAD_BUNDLE_REVIEW_PROFILE_DIR_NAMES
        else group_target_size_bytes
    )

    model = source_model or _upload_bundle_build_source_model(source_root=source_root)
    run_index_payload = model.run_index_payload if isinstance(model.run_index_payload, dict) else {}
    comparison_summary_payload = (
        model.comparison_summary_payload
        if isinstance(model.comparison_summary_payload, dict)
        else {}
    )
    process_manifest_payload = (
        model.process_manifest_payload if isinstance(model.process_manifest_payload, dict) else {}
    )
    starter_manifest_payload = (
        model.starter_manifest_payload if isinstance(model.starter_manifest_payload, dict) else {}
    )

    run_rows = model.run_rows if isinstance(model.run_rows, list) else []
    comparison_pairs = model.comparison_pairs if isinstance(model.comparison_pairs, list) else []
    changed_line_rows = model.changed_line_rows if isinstance(model.changed_line_rows, list) else []
    pair_breakdown_rows = (
        model.pair_breakdown_rows if isinstance(model.pair_breakdown_rows, list) else []
    )
    recipe_triage_rows = (
        model.recipe_triage_rows if isinstance(model.recipe_triage_rows, list) else []
    )
    call_inventory_rows = (
        model.call_inventory_rows if isinstance(model.call_inventory_rows, list) else []
    )
    selected_packets = model.selected_packets if isinstance(model.selected_packets, list) else []
    run_dir_by_id = model.run_dir_by_id if isinstance(model.run_dir_by_id, dict) else {}
    run_dirs_by_id = model.run_dirs_by_id if isinstance(model.run_dirs_by_id, dict) else {}
    run_dir_by_output_subdir = (
        model.run_dir_by_output_subdir
        if isinstance(model.run_dir_by_output_subdir, dict)
        else {}
    )
    advertised_counts = (
        model.advertised_counts if isinstance(model.advertised_counts, dict) else {}
    )
    starter_pack_physical_present = bool(model.starter_pack_present)
    discovered_run_dirs = (
        model.discovered_run_dirs if isinstance(model.discovered_run_dirs, list) else []
    )
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
    run_dirs_for_analysis: list[Path] = [
        run_dir for run_dir in discovered_run_dirs if isinstance(run_dir, Path)
    ]
    if not run_dirs_for_analysis:
        for rows in run_dirs_by_id.values():
            if not isinstance(rows, list):
                continue
            for run_dir in rows:
                if isinstance(run_dir, Path):
                    run_dirs_for_analysis.append(run_dir)
    for run_dir in discovered_run_dirs:
        if not isinstance(run_dir, Path):
            continue
        try:
            relative_subdir = str(run_dir.resolve().relative_to(source_root).as_posix())
        except Exception:  # noqa: BLE001
            relative_subdir = str(run_dir.name)
        if relative_subdir:
            run_dir_by_output_subdir.setdefault(relative_subdir, run_dir)

    if high_level_only:
        selected_paths, selection_meta = _upload_bundle_select_high_level_artifact_paths(
            source_root=source_root,
            discovered_run_dirs=discovered_run_dirs,
            target_bundle_size_bytes=effective_group_target_size_bytes,
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
                relative_parts = path.relative_to(source_root).parts
                if relative_parts and relative_parts[0] in UPLOAD_BUNDLE_REVIEW_PROFILE_DIR_NAMES:
                    continue
            elif path.is_relative_to(output_root):
                # Avoid recursively bundling previously written bundle files when the
                # bundle output lives inside the source tree.
                continue
            relative_path = str(path.relative_to(source_root).as_posix())
            if relative_path in excluded:
                continue
            artifact_paths.append(path)

    payload_rows: list[dict[str, Any]] = []
    payload_paths_seen: set[str] = set()

    def _append_payload_row(payload_row: dict[str, Any]) -> None:
        relative_path = str(payload_row.get("path") or "").strip()
        if not relative_path or relative_path in payload_paths_seen:
            return
        payload_paths_seen.add(relative_path)
        payload_rows.append(payload_row)

    for artifact_path in artifact_paths:
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
                    payload_row["decompressed_text"] = gzip.decompress(raw_bytes).decode(
                        "utf-8"
                    )
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
        _append_payload_row(payload_row)

    artifact_index: list[dict[str, Any]] = []
    artifact_row_lookup: dict[str, int] = {}
    artifact_paths_by_basename: dict[str, list[str]] = defaultdict(list)

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
        if not relative_path or relative_path in payload_paths_seen:
            return
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
        _append_payload_row(payload_row)

    run_diagnostics: list[dict[str, Any]] = []
    for row in run_rows:
        if not isinstance(row, dict):
            continue
        run_id = str(row.get("run_id") or "")
        output_subdir = str(row.get("output_subdir") or "")
        if not output_subdir:
            continue
        run_dir_relative = output_subdir
        run_dir_candidate = run_dir_by_output_subdir.get(run_dir_relative)
        run_dir = run_dir_candidate if isinstance(run_dir_candidate, Path) else None
        if run_dir is None:
            run_dir_candidate = run_dir_by_id.get(run_id)
            run_dir = run_dir_candidate if isinstance(run_dir_candidate, Path) else None
            if run_dir is not None:
                try:
                    run_dir_relative = str(run_dir.resolve().relative_to(source_root).as_posix())
                except Exception:  # noqa: BLE001
                    run_dir_relative = output_subdir

        codex_enabled = _upload_bundle_is_codex_pipeline_enabled(
            row.get("llm_recipe_pipeline")
        )
        summary_path = source_root / run_dir_relative / "need_to_know_summary.json"
        summary_payload = _load_json(summary_path) if summary_path.is_file() else {}
        sample_counts = summary_payload.get("sample_counts")
        sample_counts = sample_counts if isinstance(sample_counts, dict) else {}
        derived_statuses: dict[str, str] = {}
        if run_dir is not None:
            derived_statuses = _upload_bundle_derive_run_diagnostic_statuses(
                run_dir=run_dir,
                run_id=run_id,
                output_subdir=run_dir_relative,
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
                "output_subdir": run_dir_relative,
                "source_key": row.get("source_key"),
                "source_file": row.get("source_file"),
                "overall_line_accuracy": _coerce_float(row.get("overall_line_accuracy")),
                "practical_f1": _coerce_float(row.get("practical_f1")),
                "full_prompt_log_status": str(row.get("full_prompt_log_status") or "unknown"),
                "need_to_know_summary_path": f"{run_dir_relative}/need_to_know_summary.json",
                "run_manifest_path": f"{run_dir_relative}/run_manifest.json",
                "eval_report_path": f"{run_dir_relative}/eval_report.json",
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
    recipe_pipeline_context = build_recipe_pipeline_context_from_model(model=model)
    pass_stage_per_label_metrics = _upload_bundle_collect_stage_per_label_metrics(
        comparison_pairs=comparison_pairs,
        run_dir_by_id=run_dir_by_id,
    )
    stage_separated_comparison = build_stage_separated_comparison_from_model(
        model=model,
        per_label_metrics=per_label_metrics,
        pass_stage_per_label_metrics=pass_stage_per_label_metrics,
    )
    failure_ledger = _upload_bundle_build_failure_ledger(
        recipe_triage_rows=recipe_triage_rows,
        call_inventory_rows=call_inventory_rows,
    )
    call_runtime_inventory = _upload_bundle_build_call_runtime_inventory(
        call_inventory_rows=call_inventory_rows,
        run_dir_by_id=run_dir_by_id,
        run_dirs=run_dirs_for_analysis,
    )
    (
        knowledge_summary,
        knowledge_locator_hints,
    ) = _upload_bundle_build_knowledge_summary(
        source_root=source_root,
        discovered_run_dirs=run_dirs_for_analysis,
    )
    for locator_hint in knowledge_locator_hints:
        if not isinstance(locator_hint, dict):
            continue
        logical_path = str(locator_hint.get("knowledge_manifest_path") or "").strip()
        source_path = locator_hint.get("knowledge_manifest_source_path")
        if (
            not logical_path
            or not logical_path.startswith(f"{UPLOAD_BUNDLE_DERIVED_DIR_NAME}/")
            or not isinstance(source_path, Path)
            or not source_path.is_file()
        ):
            continue
        _append_virtual_payload_row(
            path=logical_path,
            content_type="json",
            content_json=_upload_bundle_load_json_object(source_path),
        )
    line_role_signal_summary = _upload_bundle_build_line_role_escalation_summary(
        source_root=source_root,
        run_dir_by_id=run_dir_by_id,
        run_dirs=run_dirs_for_analysis,
    )
    regression_casebook = _upload_bundle_build_regression_casebook(
        recipe_triage_rows=recipe_triage_rows,
        changed_line_rows=changed_line_rows,
    )
    changed_line_stratified = _upload_bundle_build_changed_line_stratified_sample(
        changed_line_rows
    )
    triage_packet_rows = _upload_bundle_build_triage_packet_rows(recipe_triage_rows)
    (
        explicit_escalation_changed_lines_summary,
        explicit_escalation_changed_lines_rows,
    ) = _upload_bundle_build_explicit_escalation_changed_lines_packet(
        source_root=source_root,
        run_dir_by_id=run_dir_by_id,
        changed_line_rows=changed_line_rows,
        run_dirs=run_dirs_for_analysis,
    )
    net_error_blame_summary = _upload_bundle_build_net_error_blame_summary(
        changed_line_rows=changed_line_rows,
        recipe_triage_rows=recipe_triage_rows,
        comparison_pairs=comparison_pairs,
        recipe_pipeline_context=recipe_pipeline_context,
        explicit_escalation_rows=explicit_escalation_changed_lines_rows,
    )
    config_version_metadata = _upload_bundle_build_config_version_metadata(
        source_root=source_root,
        run_rows=run_rows,
        comparison_pairs=comparison_pairs,
        run_dir_by_id=run_dir_by_id,
        run_dir_by_output_subdir=run_dir_by_output_subdir,
    )
    baseline_trace_parity = _starter_pack_build_baseline_trace_parity_cues(
        comparison_pairs=comparison_pairs,
        run_rows=run_rows,
        run_dir_by_id=run_dir_by_id,
        run_diagnostics=run_diagnostics,
    )
    source_metadata = _upload_bundle_source_metadata(
        run_rows=[row for row in run_rows if isinstance(row, dict)],
        comparison_pairs=[row for row in comparison_pairs if isinstance(row, dict)],
        recipe_triage_rows=[row for row in recipe_triage_rows if isinstance(row, dict)],
    )
    source_keys = sorted(source_metadata.keys())
    multi_book_run_level = bool(high_level_only and len(source_keys) > 1)
    book_scorecard = _upload_bundle_build_book_scorecard(
        comparison_pairs=comparison_pairs,
        source_metadata=source_metadata,
    )
    ablation_summary = _upload_bundle_build_ablation_summary(comparison_pairs)
    outside_span_summary_by_book = _upload_bundle_build_outside_span_summary_by_book(
        recipe_triage_rows=recipe_triage_rows,
        comparison_pairs=comparison_pairs,
        source_metadata=source_metadata,
    )
    chapter_page_type_breakdown = _upload_bundle_build_chapter_page_type_breakdown(
        source_root=source_root,
        discovered_run_dirs=run_dirs_for_analysis,
        run_rows=[row for row in run_rows if isinstance(row, dict)],
        changed_line_rows=[row for row in changed_line_rows if isinstance(row, dict)],
        recipe_triage_rows=[row for row in recipe_triage_rows if isinstance(row, dict)],
        source_metadata=source_metadata,
    )
    runtime_by_book_summary = {
        "schema_version": "upload_bundle_runtime_by_book.v1",
        "book_count": len(
            call_runtime_inventory.get("by_source")
            if isinstance(call_runtime_inventory.get("by_source"), list)
            else []
        ),
        "rows": (
            call_runtime_inventory.get("by_source")
            if isinstance(call_runtime_inventory.get("by_source"), list)
            else []
        ),
        "summary": (
            call_runtime_inventory.get("summary")
            if isinstance(call_runtime_inventory.get("summary"), dict)
            else {}
        ),
    }
    top_regression_packets_full_trace = (
        _upload_bundle_build_top_regression_packets_with_decision_trace(
            regression_casebook=regression_casebook,
            limit=10,
        )
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
        "explicit_escalation_changed_lines_packet_jsonl": (
            f"{derived_root_prefix}/explicit_escalation_changed_lines.packet.jsonl"
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
        path=derived_root_paths["explicit_escalation_changed_lines_packet_jsonl"],
        content_type="jsonl",
        content_jsonl_rows=[dict(row) for row in explicit_escalation_changed_lines_rows],
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
        "final_payload_target_bytes": None,
        "final_payload_bytes": None,
        "final_bundle_bytes": None,
        "serialized_size_capped": None,
        "omitted_artifact_count": 0,
        "omitted_bytes_estimate": 0,
        "omitted_artifacts": [],
    }
    group_high_level_packet: dict[str, Any] | None = None
    if high_level_only:
        payload_bytes_before_group_packet = sum(
            _upload_bundle_payload_row_line_bytes(row) for row in payload_rows
        )
        group_high_level_packet = _upload_bundle_build_group_high_level_packet(
            source_root=source_root,
            discovered_run_dirs=discovered_run_dirs,
            run_rows=run_rows,
            run_diagnostics=run_diagnostics,
            target_bundle_size_bytes=effective_group_target_size_bytes,
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
            "target_bundle_size_bytes": int(group_target_size_bytes),
            "target_bundle_size_mb": round(group_target_size_bytes / (1024 * 1024), 3),
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

    if high_level_only:
        final_payload_target_bytes = max(
            effective_group_target_size_bytes
            - _upload_bundle_high_level_final_reserve_bytes(
                effective_group_target_size_bytes
            ),
            1,
        )
        payload_rows, trim_meta = _upload_bundle_trim_high_level_payload_rows(
            payload_rows=payload_rows,
            target_payload_bytes=final_payload_target_bytes,
            preserve_paths={
                "run_index.json",
                "comparison_summary.json",
                "process_manifest.json",
                derived_root_paths["run_index_json"],
                derived_root_paths["comparison_summary_json"],
                derived_root_paths["process_manifest_json"],
                derived_root_paths["group_high_level_packet_json"],
                *{
                    f"{str(row.get('output_subdir') or '').strip()}/prediction-run/prompt_budget_summary.json"
                    for row in run_rows
                    if isinstance(row, dict) and str(row.get("output_subdir") or "").strip()
                },
                *{
                    f"{str(row.get('output_subdir') or '').strip()}/prompt_budget_summary.json"
                    for row in run_rows
                    if isinstance(row, dict) and str(row.get("output_subdir") or "").strip()
                },
            },
        )
        payload_paths_seen = {
            str(row.get("path") or "").strip()
            for row in payload_rows
            if isinstance(row, dict)
        }
        group_artifact_selection["final_trim"] = trim_meta
        group_high_level_packet_summary["final_payload_target_bytes"] = int(
            trim_meta.get("target_payload_bytes") or final_payload_target_bytes
        )
        group_high_level_packet_summary["final_payload_bytes"] = int(
            trim_meta.get("final_payload_bytes") or 0
        )
        group_high_level_packet_summary["omitted_artifact_count"] = int(
            trim_meta.get("omitted_artifact_count") or 0
        )
        group_high_level_packet_summary["omitted_bytes_estimate"] = int(
            trim_meta.get("omitted_bytes_estimate") or 0
        )
        group_high_level_packet_summary["omitted_artifacts"] = list(
            trim_meta.get("omitted_artifacts") or []
        )
        if isinstance(group_high_level_packet, dict):
            group_high_level_packet["final_payload_target_bytes"] = int(
                trim_meta.get("target_payload_bytes") or final_payload_target_bytes
            )
            group_high_level_packet["final_payload_bytes"] = int(
                trim_meta.get("final_payload_bytes") or 0
            )
            group_high_level_packet["omitted_artifact_count"] = int(
                trim_meta.get("omitted_artifact_count") or 0
            )
            group_high_level_packet["omitted_bytes_estimate"] = int(
                trim_meta.get("omitted_bytes_estimate") or 0
            )
            group_high_level_packet["omitted_artifacts"] = list(
                trim_meta.get("omitted_artifacts") or []
            )

    artifact_index = []
    artifact_row_lookup = {}
    artifact_paths_by_basename = defaultdict(list)
    for payload_row_number, payload_row in enumerate(payload_rows, start=1):
        if not isinstance(payload_row, dict):
            continue
        relative_path = str(payload_row.get("path") or "").strip()
        if not relative_path:
            continue
        artifact_index.append(
            {
                "path": relative_path,
                "payload_row": payload_row_number,
                "content_type": str(payload_row.get("content_type") or ""),
                "category": payload_row.get("category"),
                "run_subdir": payload_row.get("run_subdir"),
                "bytes": int(_coerce_int(payload_row.get("bytes")) or 0),
                "sha256": str(payload_row.get("sha256") or ""),
                "parsed_mode": str(payload_row.get("parsed_mode") or ""),
            }
        )
        artifact_row_lookup[relative_path] = payload_row_number
        basename = relative_path.rsplit("/", 1)[-1]
        if basename:
            artifact_paths_by_basename[basename].append(relative_path)

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
        "recipe_manifest.json",
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
                    str(item.get("run_manifest_path") or ""),
                    str(item.get("eval_report_path") or ""),
                ),
            ),
        }
        for item in run_diagnostics
        if isinstance(item, dict) and str(item.get("need_to_know_summary_path") or "")
    ]
    knowledge_row_locators = [
        {
            "run_id": str(item.get("run_id") or ""),
            "output_subdir": str(item.get("output_subdir") or ""),
            "prompt_samples_md": _payload_locator(
                paths=tuple(
                    path
                    for path in (str(item.get("prompt_samples_path") or ""),)
                    if path
                ),
            ),
            "prompt_knowledge_txt": _payload_locator(
                paths=tuple(
                    path for path in (str(item.get("prompt_knowledge_path") or ""),) if path
                ),
            ),
            "knowledge_manifest_json": _payload_locator(
                paths=tuple(
                    path for path in (str(item.get("knowledge_manifest_path") or ""),) if path
                ),
            ),
            "prompt_budget_summary_json": _payload_locator(
                paths=tuple(
                    path
                    for path in (str(item.get("prompt_budget_summary_path") or ""),)
                    if path
                ),
            ),
        }
        for item in knowledge_locator_hints
        if isinstance(item, dict) and str(item.get("run_id") or "")
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
            "explicit_escalation_changed_lines_packet_jsonl": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_EXPLICIT_ESCALATION_CHANGED_LINES_FILE_NAME}",
                    derived_root_paths["explicit_escalation_changed_lines_packet_jsonl"],
                ),
                basenames=(
                    STARTER_PACK_EXPLICIT_ESCALATION_CHANGED_LINES_FILE_NAME,
                    "explicit_escalation_changed_lines.packet.jsonl",
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
            "explicit_escalation_changed_lines_packet_jsonl": _payload_locator(
                paths=(
                    f"{STARTER_PACK_DIR_NAME}/{STARTER_PACK_EXPLICIT_ESCALATION_CHANGED_LINES_FILE_NAME}",
                    derived_root_paths["explicit_escalation_changed_lines_packet_jsonl"],
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
        "knowledge_by_run": knowledge_row_locators,
        "deprioritized_heavy_artifacts": heavy_artifact_locators[:80],
    }

    knowledge_rows = (
        knowledge_summary.get("rows")
        if isinstance(knowledge_summary.get("rows"), list)
        else []
    )
    knowledge_locator_by_key = {
        (
            str(row.get("run_id") or ""),
            str(row.get("output_subdir") or ""),
        ): row
        for row in knowledge_row_locators
        if isinstance(row, dict)
    }
    for row in knowledge_rows:
        if not isinstance(row, dict):
            continue
        locator_row = knowledge_locator_by_key.get(
            (
                str(row.get("run_id") or ""),
                str(row.get("output_subdir") or ""),
            )
        )
        locator_row = locator_row if isinstance(locator_row, dict) else {}
        row["prompt_samples_in_bundle"] = isinstance(locator_row.get("prompt_samples_md"), dict)
        row["prompt_knowledge_in_bundle"] = isinstance(
            locator_row.get("prompt_knowledge_txt"),
            dict,
        )
        row["knowledge_manifest_in_bundle"] = isinstance(
            locator_row.get("knowledge_manifest_json"),
            dict,
        )
        row["prompt_budget_summary_in_bundle"] = isinstance(
            locator_row.get("prompt_budget_summary_json"),
            dict,
        )

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
    pair_delta_summary = _upload_bundle_build_pair_delta_summary(pair_inventory)
    active_recipe_span_breakout = _upload_bundle_build_active_recipe_span_breakout(
        pair_breakdown_rows,
        run_dirs=run_dirs_for_analysis,
    )
    (
        triage_packet_sample_rows,
        triage_packet_sample_note,
    ) = _upload_bundle_select_triage_packet_sample_rows(
        triage_packet_rows,
        pair_count=len(comparison_pairs),
        active_recipe_span_breakout=active_recipe_span_breakout,
    )
    triage_packet_summary = {
        "schema_version": UPLOAD_BUNDLE_TRIAGE_PACKET_SCHEMA_VERSION,
        "row_count": len(triage_packet_rows),
        "empty_packet_note": (
            ""
            if triage_packet_rows
            else (
                "No comparison pair was available, so recipe-local triage rows were not built."
                if len(comparison_pairs) <= 0
                else "No triage rows were available from source or derived comparison artifacts."
            )
        ),
        "signal_row_count": len(
            [
                row
                for row in triage_packet_rows
                if isinstance(row, dict) and _upload_bundle_triage_packet_row_has_signal(row)
            ]
        ),
        "sample_rows_note": triage_packet_sample_note,
        "sample_rows": triage_packet_sample_rows,
    }
    prompt_log_summary = _upload_bundle_bundle_prompt_log_summary(
        process_manifest_payload=process_manifest_payload,
        run_rows=run_rows,
        run_diagnostics=run_diagnostics,
    )
    runtime_summary_payload = (
        call_runtime_inventory.get("summary")
        if isinstance(call_runtime_inventory.get("summary"), dict)
        else {}
    )
    stage_observability_summary = _upload_bundle_build_stage_observability_summary(
        failure_ledger
    )
    recipe_correction_output_accounting = _upload_bundle_assert_recipe_correction_output_accounting(
        stage_observability_summary=stage_observability_summary,
        call_inventory_rows=call_inventory_rows,
    )
    self_check["recipe_correction_output_accounting_consistent"] = True
    verification_details = self_check.get("verification_details")
    verification_details = verification_details if isinstance(verification_details, dict) else {}
    verification_details["recipe_correction_output_accounting"] = (
        recipe_correction_output_accounting
    )
    self_check["verification_details"] = verification_details
    top_confusion_deltas = _aggregate_confusion_deltas(
        {"pairs": comparison_pairs},
        top_k=20,
    )
    turn1_summary = _upload_bundle_build_turn1_summary(
        pair_delta_summary=pair_delta_summary,
        active_recipe_span_breakout=active_recipe_span_breakout,
        net_error_blame_summary=net_error_blame_summary,
        top_confusion_deltas=top_confusion_deltas,
        triage_packet_rows=triage_packet_rows,
        triage_packet_sample_note=triage_packet_sample_note,
        runtime_summary_payload=runtime_summary_payload,
        stage_observability_summary=stage_observability_summary,
        regression_casebook=regression_casebook,
    )
    topline = {
        "run_count": run_count_verified,
        "pair_count": pair_count_verified_count,
        "changed_lines_total": changed_lines_verified_count,
        "full_prompt_log_status": str(prompt_log_summary.get("status") or "unknown"),
        "full_prompt_log_status_source": str(
            prompt_log_summary.get("status_source") or "unknown"
        ),
        "full_prompt_log_rows": int(prompt_log_summary.get("full_prompt_log_rows") or 0),
        "full_prompt_log_codex_run_count": int(
            prompt_log_summary.get("codex_run_count") or 0
        ),
        "full_prompt_log_complete_codex_run_count": int(
            prompt_log_summary.get("codex_runs_complete") or 0
        ),
        "largest_practical_f1_regressions": largest_regressions,
        "pair_count_sufficient_for_generalization": (
            pair_count_verified_count >= UPLOAD_BUNDLE_MIN_PAIRS_FOR_GENERALIZATION
        ),
        "additional_pairs_needed_for_generalization": max(
            UPLOAD_BUNDLE_MIN_PAIRS_FOR_GENERALIZATION - pair_count_verified_count,
            0,
        ),
        **pair_delta_summary,
        "active_recipe_span_breakout": active_recipe_span_breakout,
        "call_runtime_call_count": int(runtime_summary_payload.get("call_count") or 0),
        "call_runtime_coverage_ratio": round(
            (
                int(runtime_summary_payload.get("calls_with_runtime") or 0)
                / int(runtime_summary_payload.get("call_count") or 1)
            ),
            6,
        )
        if int(runtime_summary_payload.get("call_count") or 0) > 0
        else 0.0,
        "call_runtime_estimated_cost_coverage_ratio": _coerce_float(
            runtime_summary_payload.get("estimated_cost_coverage_ratio")
        ),
        "call_runtime_total_duration_ms": _coerce_int(
            runtime_summary_payload.get("total_duration_ms")
        ),
        "call_runtime_total_tokens": _coerce_int(runtime_summary_payload.get("total_tokens")),
    }
    structure_label_report = build_structure_label_report(
        per_label_metrics=per_label_metrics,
        pair_rows=pair_inventory,
        run_dir_by_id=run_dir_by_id,
    )

    if pair_count_verified_count > 0:
        default_initial_views = [
            "topline",
            "self_check",
            "analysis.turn1_summary",
            "analysis.benchmark_pair_inventory",
            "analysis.active_recipe_span_breakout",
            "analysis.net_error_blame_summary",
            "analysis.top_confusion_deltas",
            "analysis.changed_lines_stratified_sample",
            "analysis.triage_packet",
            "analysis.config_version_metadata",
            "analysis.recipe_pipeline_context",
            "analysis.stage_observability_summary",
            "analysis.structure_label_report",
            "analysis.knowledge",
            "analysis.per_label_metrics",
            "analysis.per_recipe_breakdown",
            "analysis.stage_separated_comparison",
            "analysis.failure_ledger",
            "analysis.regression_casebook",
            "analysis.explicit_escalation_changed_lines_packet",
            "analysis.call_inventory_runtime",
            "analysis.line_role_escalation",
        ]
    else:
        default_initial_views = [
            "topline",
            "self_check",
            "analysis.turn1_summary",
            "analysis.active_recipe_span_breakout",
            "analysis.recipe_pipeline_context",
            "analysis.stage_observability_summary",
            "analysis.net_error_blame_summary",
            "analysis.top_confusion_deltas",
            "analysis.changed_lines_stratified_sample",
            "analysis.triage_packet",
            "analysis.benchmark_pair_inventory",
            "analysis.config_version_metadata",
            "analysis.structure_label_report",
            "analysis.knowledge",
            "analysis.per_label_metrics",
            "analysis.per_recipe_breakdown",
            "analysis.stage_separated_comparison",
            "analysis.failure_ledger",
            "analysis.regression_casebook",
            "analysis.explicit_escalation_changed_lines_packet",
            "analysis.call_inventory_runtime",
            "analysis.line_role_escalation",
        ]
    if high_level_only:
        default_initial_views.insert(2, "analysis.group_high_level")
    if multi_book_run_level:
        insert_at = 3 if high_level_only else 2
        for view_name in reversed(
            [
                "analysis.book_scorecard",
                "analysis.ablation_summary",
                "analysis.outside_span_by_book",
                "analysis.chapter_page_type_breakdown",
                "analysis.runtime_by_book",
                "analysis.top_regression_packets_full_trace",
            ]
        ):
            default_initial_views.insert(insert_at, view_name)

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
                (
                    "High-level group bundles are intentionally curated first-pass packets: "
                    "heavy prompt/trace artifacts may be omitted and the omission list is "
                    "recorded in analysis.group_high_level."
                )
                if high_level_only
                else (
                    "Every source artifact is represented in payload with sha256/bytes and "
                    "full content (UTF-8 structured/text fields or base64 when binary/compressed)."
                )
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
                    f"{STARTER_PACK_EXPLICIT_ESCALATION_CHANGED_LINES_FILE_NAME}"
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
            "turn1_summary": turn1_summary,
            "benchmark_pair_inventory": {
                "pair_count": len(pair_inventory),
                "delta_summary": pair_delta_summary,
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
            "active_recipe_span_breakout": active_recipe_span_breakout,
            "triage_packet": triage_packet_summary,
            "net_error_blame_summary": net_error_blame_summary,
            "config_version_metadata": config_version_metadata,
            "recipe_pipeline_context": recipe_pipeline_context,
            "stage_observability_summary": stage_observability_summary,
            "structure_label_report": structure_label_report,
            "knowledge": knowledge_summary,
            "group_high_level": group_high_level_packet_summary,
            "per_label_metrics": per_label_metrics,
            "top_confusion_deltas": top_confusion_deltas,
            "per_recipe_breakdown": {
                "pair_breakdown_count": len(pair_breakdown_rows),
                "pairs": pair_breakdown_rows,
            },
            "stage_separated_comparison": stage_separated_comparison,
            "failure_ledger": failure_ledger,
            "regression_casebook": regression_casebook,
            "changed_lines_stratified_sample": changed_line_stratified,
            "explicit_escalation_changed_lines_packet": (
                explicit_escalation_changed_lines_summary
            ),
            "call_inventory_runtime": call_runtime_inventory,
            "line_role_escalation": line_role_signal_summary,
            "selected_recipe_packets": {
                "packet_count": len(selected_packets),
                "packets": selected_packets,
            },
            **(
                {
                    "book_scorecard": book_scorecard,
                    "ablation_summary": ablation_summary,
                    "outside_span_by_book": outside_span_summary_by_book,
                    "chapter_page_type_breakdown": chapter_page_type_breakdown,
                    "runtime_by_book": runtime_by_book_summary,
                    "top_regression_packets_full_trace": top_regression_packets_full_trace,
                }
                if multi_book_run_level
                else {}
            ),
        },
        "alias_metadata": alias_metadata,
        "artifact_count": len(artifact_index),
        "artifact_index": artifact_index,
    }
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
        (
            f"- `{UPLOAD_BUNDLE_PAYLOAD_FILE_NAME}`: curated payload rows for the first-pass group handoff."
            if high_level_only
            else f"- `{UPLOAD_BUNDLE_PAYLOAD_FILE_NAME}`: full artifact payload rows (lossless source data)."
        ),
        "",
        "## Quick Start",
        "",
        f"1. Read `topline` and `self_check` in `{UPLOAD_BUNDLE_INDEX_FILE_NAME}`.",
        "2. Read `analysis.turn1_summary` for the one-screen severity, span, blame, runtime, and targeted-regression summary.",
        (
            "3. Read `analysis.benchmark_pair_inventory` and `analysis.active_recipe_span_breakout` for the pair-delta and span story."
            if int(_coerce_int(topline.get("pair_count")) or 0) > 0
            else "3. Read `analysis.active_recipe_span_breakout`, `analysis.recipe_pipeline_context`, and `analysis.stage_observability_summary` for the single-run span and stage story."
        ),
        "4. Use `analysis.net_error_blame_summary`, `analysis.top_confusion_deltas`, and `analysis.changed_lines_stratified_sample` before drilling into recipe rows.",
        "5. Open `navigation.default_initial_views` in order for first-pass triage.",
        f"6. Use `navigation.row_locators` to jump into `{UPLOAD_BUNDLE_PAYLOAD_FILE_NAME}` rows.",
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
        (
            "- full_prompt_log_status_source: "
            f"{str(topline.get('full_prompt_log_status_source') or 'unknown')}"
        ),
        f"- full_prompt_log_rows: {topline['full_prompt_log_rows']}",
        (
            "- worst_pair_delta_overall_line_accuracy: "
            f"{_serialize_float(_coerce_float(topline.get('worst_pair_delta_overall_line_accuracy')))}"
        ),
        (
            "- worst_pair_delta_macro_f1_excluding_other: "
            f"{_serialize_float(_coerce_float(topline.get('worst_pair_delta_macro_f1_excluding_other')))}"
        ),
        (
            "- worst_pair_delta_practical_f1: "
            f"{_serialize_float(_coerce_float(topline.get('worst_pair_delta_practical_f1')))}"
        ),
        (
            "- recipe_span_count: "
            f"{int(_coerce_int(active_recipe_span_breakout.get('recipe_span_count')) or 0)}"
        ),
        (
            "- all_scored_lines_outside_active_recipe_spans: "
            f"{'true' if bool(active_recipe_span_breakout.get('all_scored_lines_outside_active_recipe_spans')) else 'false'}"
        ),
        (
            "- outside_active_recipe_span_line_total: "
            f"{int(_coerce_int(((active_recipe_span_breakout.get('outside_active_recipe_span') or {}).get('line_total'))) or 0)}"
        ),
        (
            "- inside_active_recipe_span_line_total: "
            f"{int(_coerce_int(((active_recipe_span_breakout.get('inside_active_recipe_span') or {}).get('line_total'))) or 0)}"
        ),
        (
            "- call_runtime_coverage_ratio: "
            f"{_serialize_float(_coerce_float(topline.get('call_runtime_coverage_ratio')))}"
        ),
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
    turn1_target_summary = (
        turn1_summary.get("targeted_regression_affordance")
        if isinstance(turn1_summary.get("targeted_regression_affordance"), dict)
        else {}
    )
    overview_lines.extend(
        [
            "## Turn-1 Summary",
            "",
            (
                "- diagnosis_flags: "
                + (
                    ", ".join(
                        f"`{str(flag)}`" for flag in turn1_summary.get("diagnosis_flags") or []
                    )
                    if isinstance(turn1_summary.get("diagnosis_flags"), list)
                    and (turn1_summary.get("diagnosis_flags") or [])
                    else "none"
                )
            ),
            (
                "- targeted_regression_status: "
                f"{str(turn1_target_summary.get('target_request_status') or 'unknown')}"
            ),
            (
                "- suggested_targets: "
                + (
                    ", ".join(
                        f"`{str(item)}`"
                        for item in turn1_target_summary.get("suggested_targets") or []
                    )
                    if isinstance(turn1_target_summary.get("suggested_targets"), list)
                    and (turn1_target_summary.get("suggested_targets") or [])
                    else "none"
                )
            ),
            "",
        ]
    )
    if str(turn1_summary.get("top_triage_rows_note") or "").strip():
        overview_lines.extend(
            [
                (
                    "- triage_row_note: "
                    f"{str(turn1_summary.get('top_triage_rows_note') or '').strip()}"
                ),
                "",
            ]
        )
    recipe_stage_rows = (
        recipe_pipeline_context.get("recipe_stages")
        if isinstance(recipe_pipeline_context.get("recipe_stages"), list)
        else []
    )
    recipe_stage_labels = [
        str(stage.get("stage_label") or stage.get("stage_key") or "").strip()
        for stage in recipe_stage_rows
        if isinstance(stage, dict)
    ]
    recipe_stage_display = " / ".join(recipe_stage_labels) if recipe_stage_labels else "recipe-stages"
    overview_lines.extend(
        [
            "## Recipe Pipeline Context",
            "",
            (
                "- codex_recipe_pipelines: "
                + (
                    ", ".join(
                        f"`{pipeline}`"
                        for pipeline in recipe_pipeline_context.get("codex_recipe_pipelines") or []
                    )
                    if isinstance(recipe_pipeline_context.get("codex_recipe_pipelines"), list)
                    and (recipe_pipeline_context.get("codex_recipe_pipelines") or [])
                    else "none"
                )
            ),
            (
                "- recipe_topology_key: "
                f"{str(recipe_pipeline_context.get('recipe_topology_key') or 'schemaorg_final')}"
            ),
            (
                "- recipe_stages: "
                f"{', '.join(recipe_stage_labels) if recipe_stage_labels else 'none'}"
            ),
            "",
        ]
    )
    overview_lines.extend(
        [
            "## Knowledge",
            "",
            (
                "- enabled_run_count: "
                f"{int(_coerce_int(knowledge_summary.get('enabled_run_count')) or 0)}"
            ),
            (
                "- runs_with_prompt_samples: "
                f"{int(_coerce_int(knowledge_summary.get('runs_with_prompt_samples')) or 0)}"
            ),
            (
                "- runs_with_knowledge_manifest: "
                f"{int(_coerce_int(knowledge_summary.get('runs_with_knowledge_manifest')) or 0)}"
            ),
            (
                "- total_knowledge_call_count: "
                f"{int(_coerce_int(knowledge_summary.get('total_knowledge_call_count')) or 0)}"
            ),
            (
                "- prompt navigation: "
                f"`{UPLOAD_BUNDLE_INDEX_FILE_NAME} -> analysis.knowledge` and "
                "`navigation.row_locators.knowledge_by_run`."
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
                (
                    "- final_payload_target_bytes: "
                    f"{int(_coerce_int(group_high_level_packet_summary.get('final_payload_target_bytes')) or 0)}"
                ),
                (
                    "- final_payload_bytes: "
                    f"{int(_coerce_int(group_high_level_packet_summary.get('final_payload_bytes')) or 0)}"
                ),
                (
                    "- omitted_artifact_count: "
                    f"{int(_coerce_int(group_high_level_packet_summary.get('omitted_artifact_count')) or 0)}"
                ),
                (
                    "- omitted_bytes_estimate: "
                    f"{int(_coerce_int(group_high_level_packet_summary.get('omitted_bytes_estimate')) or 0)}"
                ),
                "",
            ]
        )

    included_views = [
        "- turn-1 summary (severity, span breakout, blame, runtime, and targeted regression hints)",
        "- benchmark pair inventory (per-pair deltas + generalization readiness)",
        "- active recipe span breakout (inside vs outside active recipe spans)",
        "- triage packet (JSONL-first row navigation; CSV remains legacy-compatible)",
        (
            "- net-error blame summary "
            f"(line-role / {recipe_stage_display} / routing-fallback buckets)"
        ),
        "- top confusion deltas",
        "- config/version parity metadata",
        "- recipe pipeline context (active recipe pipeline ids + semantic recipe-stage labels)",
        "- stage observability summary (recorded status vs projection gap vs empty output)",
        "- per-label metrics + confusion deltas",
        "- per-recipe breakdown",
        (
            "- stage-separated comparison "
            f"(baseline / line-role / {recipe_stage_display} / final-fallback)"
        ),
        "- failure ledger (recipe x pass rows)",
        "- compact regression casebook",
        "- changed-lines stratified sample",
        "- explicit-escalation changed-lines packet",
        "- call inventory with latency/tokens/cost",
        "- line-role escalation reasons",
    ]
    if multi_book_run_level:
        included_views.extend(
            [
                "- per-book scorecard (vanilla/codex/delta with best wins + worst regressions)",
                "- ablation summary table",
                "- outside-span contamination summary by book",
                "- chapter/page-type breakdown by book",
                "- runtime by book (latency/tokens/cost)",
                "- top regression packets (decision trace first)",
            ]
        )
    overview_lines.extend(["## Included Views", "", *included_views, ""])

    if multi_book_run_level:
        book_score_rows = book_scorecard.get("rows")
        book_score_rows = book_score_rows if isinstance(book_score_rows, list) else []
        top_book_regressions = [
            row
            for row in book_score_rows
            if isinstance(row, dict)
        ][:3]
        overview_lines.extend(
            [
                "## Multi-Book Highlights",
                "",
                f"- book_count: {int(book_scorecard.get('book_count') or 0)}",
                f"- ablation_rows: {int(ablation_summary.get('row_count') or 0)}",
                (
                    "- outside_span_books_with_signal: "
                    f"{sum(1 for row in (outside_span_summary_by_book.get('rows') or []) if isinstance(row, dict) and int(_coerce_int(row.get('outside_span_wrong_line_total')) or 0) > 0)}"
                ),
                (
                    "- runtime_books: "
                    f"{int(runtime_by_book_summary.get('book_count') or 0)}"
                ),
                (
                    "- top_regression_packets_with_trace: "
                    f"{int(top_regression_packets_full_trace.get('packet_count') or 0)}"
                ),
                "",
            ]
        )
        if top_book_regressions:
            overview_lines.append("### Worst Book Deltas (Practical F1)")
            overview_lines.append("")
            for row in top_book_regressions:
                delta_payload = row.get("delta") if isinstance(row.get("delta"), dict) else {}
                overview_lines.append(
                    "- "
                    f"{str(row.get('source_key') or '')} "
                    f"(delta_practical_f1={_serialize_float(_coerce_float(delta_payload.get('practical_f1')))}, "
                    f"delta_overall_line_accuracy={_serialize_float(_coerce_float(delta_payload.get('overall_line_accuracy')))}, "
                    f"pair_count={int(_coerce_int(row.get('pair_count')) or 0)})"
                )
            overview_lines.append("")

    overview_lines.extend(
        [
            "## Active Recipe Span Breakout",
            "",
            (
                "- recipe_span_count: "
                f"{int(_coerce_int(active_recipe_span_breakout.get('recipe_span_count')) or 0)}"
            ),
            (
                "- pairs_with_zero_recipe_spans: "
                f"{int(_coerce_int(active_recipe_span_breakout.get('pairs_with_zero_recipe_spans')) or 0)}"
            ),
            (
                "- total_scored_lines: "
                f"{int(_coerce_int(active_recipe_span_breakout.get('total_scored_lines')) or 0)}"
            ),
            (
                "- outside_share_of_scored_lines: "
                f"{_serialize_float(_coerce_float(active_recipe_span_breakout.get('outside_share_of_scored_lines')))}"
            ),
            (
                "- dominant_region: "
                f"{str(active_recipe_span_breakout.get('dominant_region') or 'unknown')}"
            ),
            (
                "- turn1_note: "
                f"{str(active_recipe_span_breakout.get('turn1_note') or 'none')}"
            ),
            (
                "- inside_active_recipe_span: "
                f"line_total={int(_coerce_int(((active_recipe_span_breakout.get('inside_active_recipe_span') or {}).get('line_total'))) or 0)} "
                f"delta={_serialize_float(_coerce_float(((active_recipe_span_breakout.get('inside_active_recipe_span') or {}).get('delta_codex_minus_baseline'))))}"
            ),
            (
                "- outside_active_recipe_span: "
                f"line_total={int(_coerce_int(((active_recipe_span_breakout.get('outside_active_recipe_span') or {}).get('line_total'))) or 0)} "
                f"delta={_serialize_float(_coerce_float(((active_recipe_span_breakout.get('outside_active_recipe_span') or {}).get('delta_codex_minus_baseline'))))}"
            ),
            "",
        ]
    )

    runtime_summary_payload = (
        call_runtime_inventory.get("summary")
        if isinstance(call_runtime_inventory.get("summary"), dict)
        else {}
    )
    cost_signal = (
        runtime_summary_payload.get("cost_signal")
        if isinstance(runtime_summary_payload, dict)
        else {}
    )
    cost_signal = cost_signal if isinstance(cost_signal, dict) else {}
    estimated_cost_signal = (
        runtime_summary_payload.get("estimated_cost_signal")
        if isinstance(runtime_summary_payload, dict)
        else {}
    )
    estimated_cost_signal = (
        estimated_cost_signal if isinstance(estimated_cost_signal, dict) else {}
    )
    overview_lines.extend(
        [
            "## Runtime / Cost Snapshot",
            "",
            (
                "- call_count: "
                f"{int(_coerce_int(runtime_summary_payload.get('call_count')) or 0)}"
            ),
            (
                "- calls_with_runtime: "
                f"{int(_coerce_int(runtime_summary_payload.get('calls_with_runtime')) or 0)}"
            ),
            (
                "- runtime_coverage_ratio: "
                f"{_serialize_float(_coerce_float(topline.get('call_runtime_coverage_ratio')))}"
            ),
            (
                "- calls_with_estimated_cost: "
                f"{int(_coerce_int(runtime_summary_payload.get('calls_with_estimated_cost')) or 0)}"
            ),
            (
                "- estimated_cost_coverage_ratio: "
                f"{_serialize_float(_coerce_float(runtime_summary_payload.get('estimated_cost_coverage_ratio')))}"
            ),
            (
                "- total_duration_ms: "
                f"{int(_coerce_int(runtime_summary_payload.get('total_duration_ms')) or 0)}"
            ),
            (
                "- total_tokens: "
                f"{int(_coerce_int(runtime_summary_payload.get('total_tokens')) or 0)}"
            ),
            "",
        ]
    )
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
                "- total_duration_ms: "
                f"{int(_coerce_int(runtime_summary_payload.get('total_duration_ms')) or 0)}"
            ),
            (
                "- total_tokens: "
                f"{int(_coerce_int(runtime_summary_payload.get('total_tokens')) or 0)}"
            ),
            (
                "- total_observed_cost_usd: "
                f"{_serialize_float(_coerce_float(runtime_summary_payload.get('total_cost_usd')))}"
            ),
            (
                "- total_estimated_cost_usd: "
                f"{_serialize_float(_coerce_float(runtime_summary_payload.get('total_estimated_cost_usd')))}"
            ),
            (
                "- triage_packet_rows: "
                f"{int(triage_packet_summary.get('row_count') or 0)}"
            ),
            (
                "- explicit_escalation_changed_lines_rows: "
                f"{int(explicit_escalation_changed_lines_summary.get('row_count') or 0)}"
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

    top_confusion_rows = index_payload["analysis"].get("top_confusion_deltas")
    top_confusion_rows = top_confusion_rows if isinstance(top_confusion_rows, list) else []
    if top_confusion_rows:
        overview_lines.extend(
            [
                "## Top Confusion Deltas",
                "",
            ]
        )
        for row in top_confusion_rows[:5]:
            if not isinstance(row, dict):
                continue
            overview_lines.append(
                "- "
                f"{str(row.get('gold_label') or '')} -> {str(row.get('pred_label') or '')}: "
                f"delta_count={int(_coerce_int(row.get('delta_count')) or 0)}"
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

    stage_observability_by_stage = (
        stage_observability_summary.get("by_stage")
        if isinstance(stage_observability_summary.get("by_stage"), dict)
        else {}
    )
    overview_lines.extend(
        [
            "## Stage Observability",
            "",
            "This separates recorded runtime status from projection/scoring gaps and empty-output signals.",
            "",
        ]
    )
    for stage_key in (
        "recipe_build_intermediate",
        "recipe_refine",
        "recipe_build_final",
        "final_result",
    ):
        stage_payload = (
            stage_observability_by_stage.get(stage_key)
            if isinstance(stage_observability_by_stage, dict)
            else {}
        )
        stage_payload = stage_payload if isinstance(stage_payload, dict) else {}
        semantics_counts = (
            stage_payload.get("status_semantics_counts")
            if isinstance(stage_payload.get("status_semantics_counts"), dict)
            else {}
        )
        semantics_text = (
            ", ".join(
                f"{key}={int(_coerce_int(value) or 0)}"
                for key, value in sorted(semantics_counts.items())
                if key
            )
            if semantics_counts
            else "none"
        )
        overview_lines.append(
            "- "
            f"{stage_key}: "
            f"recipes={int(_coerce_int(stage_payload.get('recipe_count')) or 0)} "
            f"unknown={int(_coerce_int(stage_payload.get('status_unknown_count')) or 0)} "
            f"call_observed={int(_coerce_int(stage_payload.get('call_observed_count')) or 0)} "
            f"empty_output_signal={int(_coerce_int(stage_payload.get('empty_output_signal_count')) or 0)} "
            f"semantics={semantics_text}"
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
        missing_targets = regression_casebook.get("missing_targets")
        missing_targets = missing_targets if isinstance(missing_targets, list) else []
        suggested_targets = regression_casebook.get("suggested_targets")
        suggested_targets = (
            suggested_targets if isinstance(suggested_targets, list) else []
        )
        overview_lines.append(
            "- found: "
            + (
                ", ".join(f"`{str(item)}`" for item in found_targets)
                if found_targets
                else "none"
            )
        )
        overview_lines.append(
            "- status: "
            + str(regression_casebook.get("target_request_status") or "unknown")
        )
        overview_lines.append(
            "- missing: "
            + (
                ", ".join(f"`{str(item)}`" for item in missing_targets)
                if missing_targets
                else "none"
            )
        )
        overview_lines.append(
            "- suggested_available_targets: "
            + (
                ", ".join(f"`{str(item)}`" for item in suggested_targets)
                if suggested_targets
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
            )
            if not high_level_only
            else (
                "Each retained artifact row still carries `sha256` and `bytes`, but this high-level "
                "bundle is curated rather than lossless. Omitted heavy rows are listed in "
                "`analysis.group_high_level.omitted_artifacts`."
            ),
            (
                "Heavy artifacts (full prompt logs, raw manifests, transport traces, split-cache blobs) "
                "are retained in payload but deprioritized in default navigation."
            )
            if not high_level_only
            else (
                "Heavy prompt and full-context trace artifacts are reserved for follow-up packets so "
                "the first-pass group bundle stays small enough to move around."
            ),
            "",
        ]
    )

    def _render_group_final_size_lines() -> list[str]:
        if not high_level_only:
            return []
        return [
            "## Final Bundle Size",
            "",
            (
                "- final_payload_target_bytes: "
                f"{int(_coerce_int(group_high_level_packet_summary.get('final_payload_target_bytes')) or 0)}"
            ),
            (
                "- final_payload_bytes: "
                f"{int(_coerce_int(group_high_level_packet_summary.get('final_payload_bytes')) or 0)}"
            ),
            (
                "- final_bundle_bytes: "
                f"{int(_coerce_int(group_high_level_packet_summary.get('final_bundle_bytes')) or 0)}"
            ),
            (
                "- serialized_size_capped: "
                f"{'true' if bool(group_high_level_packet_summary.get('serialized_size_capped')) else 'false'}"
            ),
            (
                "- omitted_artifact_count: "
                f"{int(_coerce_int(group_high_level_packet_summary.get('omitted_artifact_count')) or 0)}"
            ),
            (
                "- omitted_bytes_estimate: "
                f"{int(_coerce_int(group_high_level_packet_summary.get('omitted_bytes_estimate')) or 0)}"
            ),
            "",
        ]

    def _render_overview_text() -> str:
        if not high_level_only:
            return "\n".join(overview_lines)
        return "\n".join(overview_lines).rstrip() + "\n\n" + "\n".join(
            _render_group_final_size_lines()
        )

    payload_row_by_path = {
        str(row.get("path") or ""): row
        for row in payload_rows
        if isinstance(row, dict) and str(row.get("path") or "").strip()
    }
    payload_rows_with_locators = [
        {
            **dict(row),
            "payload_row": int(artifact_row_lookup.get(str(row.get("path") or "")) or 0),
        }
        for row in payload_rows
        if isinstance(row, dict)
    ]
    bundle_target = oracle_upload_contract.OracleBenchmarkBundleTarget(
        requested_path=output_root,
        source_root=source_root,
        bundle_dir=output_root,
        scope=oracle_upload_contract._infer_bundle_scope(source_root),
    )

    def _review_packet_dir(review_profile: str) -> Path:
        return output_root / review_profile

    def _selected_review_payload_rows(
        review_profile: oracle_upload_contract.OracleBenchmarkReviewProfile,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        selected_rows: list[dict[str, Any]] = []
        missing_paths: list[str] = []
        for logical_path in review_profile.payload_paths:
            payload_row = payload_row_by_path.get(logical_path)
            if not isinstance(payload_row, dict):
                missing_paths.append(logical_path)
                continue
            row_copy = dict(payload_row)
            row_copy["payload_row"] = int(artifact_row_lookup.get(logical_path) or 0)
            selected_rows.append(row_copy)
        return selected_rows, missing_paths

    def _review_packet_index_payload(
        review_profile: oracle_upload_contract.OracleBenchmarkReviewProfile,
        *,
        selected_rows: list[dict[str, Any]],
        missing_paths: list[str],
    ) -> dict[str, Any]:
        lane_index_payload = json.loads(
            json.dumps(index_payload, ensure_ascii=False)
        )
        lane_index_payload["review_profile"] = review_profile.profile_id
        lane_index_payload["review_profile_display_name"] = review_profile.display_name
        lane_index_payload["file_contract"] = {
            "overview_file": UPLOAD_BUNDLE_OVERVIEW_FILE_NAME,
            "artifact_index_file": UPLOAD_BUNDLE_INDEX_FILE_NAME,
            "payload_file": UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
        }
        navigation_payload = (
            lane_index_payload.get("navigation")
            if isinstance(lane_index_payload.get("navigation"), dict)
            else {}
        )
        navigation_payload["start_here"] = [
            UPLOAD_BUNDLE_OVERVIEW_FILE_NAME,
            UPLOAD_BUNDLE_INDEX_FILE_NAME,
        ]
        navigation_payload["full_payload_companion"] = UPLOAD_BUNDLE_PAYLOAD_FILE_NAME
        lane_index_payload["navigation"] = navigation_payload
        lane_index_payload["review_packet"] = {
            "schema_version": "upload_bundle.review_packet.v1",
            "review_profile": review_profile.profile_id,
            "review_profile_display_name": review_profile.display_name,
            "review_dir": review_profile.profile_id,
            "overview_file": UPLOAD_BUNDLE_OVERVIEW_FILE_NAME,
            "index_file": UPLOAD_BUNDLE_INDEX_FILE_NAME,
            "payload_file": UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
            "selected_paths": list(review_profile.payload_paths),
            "missing_paths": missing_paths,
            "row_count": len(selected_rows),
        }
        return lane_index_payload

    def _review_packet_payload_json(
        review_profile: oracle_upload_contract.OracleBenchmarkReviewProfile,
        *,
        selected_rows: list[dict[str, Any]],
        missing_paths: list[str],
    ) -> dict[str, Any]:
        packet_rows = selected_rows if high_level_only else payload_rows_with_locators
        return {
            "schema_version": "upload_bundle.review_payload.v1",
            "review_profile": review_profile.profile_id,
            "review_profile_display_name": review_profile.display_name,
            "generated_at": str(index_payload.get("generated_at") or ""),
            "benchmark_root": str(source_root),
            "bundle_root": str(output_root),
            "selected_paths": list(review_profile.payload_paths),
            "missing_paths": list(missing_paths),
            "selected_row_count": len(selected_rows),
            "row_count": len(packet_rows),
            "rows": packet_rows,
        }

    def _write_review_packets() -> list[str]:
        written_files: list[str] = []
        for review_profile in oracle_upload_contract.ORACLE_BENCHMARK_REVIEW_PROFILES:
            review_dir = _review_packet_dir(review_profile.profile_id)
            review_dir.mkdir(parents=True, exist_ok=True)
            selected_rows, missing_paths = _selected_review_payload_rows(review_profile)
            lane_index_payload = _review_packet_index_payload(
                review_profile,
                selected_rows=selected_rows,
                missing_paths=missing_paths,
            )
            _write_json(review_dir / UPLOAD_BUNDLE_INDEX_FILE_NAME, lane_index_payload)
            lane_focus_text = oracle_upload_contract._build_review_lane_brief(
                target=bundle_target,
                profile=review_profile,
                missing_paths=missing_paths,
            ).strip()
            combined_overview = (
                lane_focus_text
                + "\n\n## Shared Benchmark Overview\n\n"
                + overview_text.strip()
                + "\n"
            )
            (review_dir / UPLOAD_BUNDLE_OVERVIEW_FILE_NAME).write_text(
                combined_overview,
                encoding="utf-8",
            )
            _write_json(
                review_dir / UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
                _review_packet_payload_json(
                    review_profile,
                    selected_rows=selected_rows,
                    missing_paths=missing_paths,
                ),
            )
            written_files.extend(
                [
                    f"{review_profile.profile_id}/{UPLOAD_BUNDLE_OVERVIEW_FILE_NAME}",
                    f"{review_profile.profile_id}/{UPLOAD_BUNDLE_INDEX_FILE_NAME}",
                    f"{review_profile.profile_id}/{UPLOAD_BUNDLE_PAYLOAD_FILE_NAME}",
                ]
            )
        return written_files

    def _bundle_output_size_bytes() -> int:
        return sum(
            int(candidate.stat().st_size)
            for candidate in output_root.rglob("*")
            if candidate.is_file()
            and candidate.parent.name in UPLOAD_BUNDLE_REVIEW_PROFILE_DIR_NAMES
            and candidate.name in UPLOAD_BUNDLE_FILE_NAMES
        )

    payload_serialized_bytes = sum(
        _upload_bundle_payload_row_line_bytes(row)
        for row in payload_rows
        if isinstance(row, dict)
    )
    group_high_level_packet_summary["final_payload_bytes"] = int(payload_serialized_bytes)
    if isinstance(group_high_level_packet, dict):
        group_high_level_packet["final_payload_bytes"] = int(payload_serialized_bytes)

    overview_text = "\n".join(overview_lines)
    if high_level_only:
        index_serialized_bytes = len(_json_dump_bytes(index_payload, indent=2, sort_keys=False)) + 1
        provisional_bundle_bytes = (
            payload_serialized_bytes
            + index_serialized_bytes
            + len(overview_text.encode("utf-8"))
        )
        group_high_level_packet_summary["final_bundle_bytes"] = int(provisional_bundle_bytes)
        group_high_level_packet_summary["serialized_size_capped"] = (
            provisional_bundle_bytes <= group_target_size_bytes
        )
        if isinstance(group_high_level_packet, dict):
            group_high_level_packet["final_bundle_bytes"] = int(provisional_bundle_bytes)
            group_high_level_packet["serialized_size_capped"] = (
                provisional_bundle_bytes <= group_target_size_bytes
            )
        overview_text = overview_text.rstrip() + "\n\n" + "\n".join(
            _render_group_final_size_lines()
        )
        index_serialized_bytes = len(_json_dump_bytes(index_payload, indent=2, sort_keys=False)) + 1
        final_bundle_bytes = (
            payload_serialized_bytes
            + index_serialized_bytes
            + len(overview_text.encode("utf-8"))
        )
        group_high_level_packet_summary["final_bundle_bytes"] = int(final_bundle_bytes)
        group_high_level_packet_summary["serialized_size_capped"] = (
            final_bundle_bytes <= group_target_size_bytes
        )
        if isinstance(group_high_level_packet, dict):
            group_high_level_packet["final_bundle_bytes"] = int(final_bundle_bytes)
            group_high_level_packet["serialized_size_capped"] = (
                final_bundle_bytes <= group_target_size_bytes
            )
        overview_text = _render_overview_text()

    written_files: list[str] = []
    for _ in range(2 if high_level_only else 1):
        written_files = _write_review_packets()
        if not high_level_only:
            break
        actual_bundle_bytes = _bundle_output_size_bytes()
        if actual_bundle_bytes == int(
            _coerce_int(group_high_level_packet_summary.get("final_bundle_bytes")) or 0
        ):
            break
        group_high_level_packet_summary["final_bundle_bytes"] = int(actual_bundle_bytes)
        group_high_level_packet_summary["serialized_size_capped"] = (
            actual_bundle_bytes <= group_target_size_bytes
        )
        if isinstance(group_high_level_packet, dict):
            group_high_level_packet["final_bundle_bytes"] = int(actual_bundle_bytes)
            group_high_level_packet["serialized_size_capped"] = (
                actual_bundle_bytes <= group_target_size_bytes
            )
        overview_text = _render_overview_text()

    return {
        "file_names": written_files,
        "artifact_count": len(artifact_index),
        "payload_rows": len(artifact_index),
        "topline": topline,
        "self_check": self_check,
        "final_bundle_bytes": (
            int(_coerce_int(group_high_level_packet_summary.get("final_bundle_bytes")) or 0)
            if high_level_only
            else _bundle_output_size_bytes()
        ),
    }


def _prune_output_to_upload_bundle_files(*, output_dir: Path) -> None:
    keep_dirs = set(UPLOAD_BUNDLE_REVIEW_PROFILE_DIR_NAMES)
    for path in output_dir.iterdir():
        if path.is_dir() and path.name in keep_dirs:
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
    """Build lane-local upload packets from an existing artifact tree.

    When `output_dir` is omitted, files are written alongside the source tree.
    When `prune_output_dir` is true and output equals source, only the lane
    upload packet folders are retained in that folder. Set
    `high_level_only=True` to emit a size-budgeted group bundle (target bytes controlled by
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

    source_model = _upload_bundle_build_source_model(source_root=source_root)
    bundle_metadata = write_upload_bundle_v1(
        model=source_model,
        output_dir=output_root,
        source_root=source_root,
        write_impl=_write_upload_bundle_three_files,
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
    """Write a flattened benchmark summary for in-place single-book sessions."""

    output_root = output_dir.resolve()
    comparison_json_path = output_root / "codex_vs_vanilla_comparison.json"
    starter_pack_dir = output_root / STARTER_PACK_DIR_NAME
    starter_readme_path = starter_pack_dir / STARTER_PACK_README_FILE_NAME
    starter_manifest_path = starter_pack_dir / STARTER_PACK_MANIFEST_FILE_NAME
    starter_comparison_path = starter_pack_dir / STARTER_PACK_COMPARISON_MIRROR_FILE_NAME
    starter_breakdown_path = starter_pack_dir / STARTER_PACK_BREAKDOWN_MIRROR_FILE_NAME
    single_book_summary_path = output_root / "single_book_summary.md"

    sections: list[str] = [
        "# Benchmark Need-To-Know Package (Flattened)",
        "",
        f"- Generated at: `{_timestamp_now()}`",
        f"- Session root: `{output_root}`",
        "",
    ]

    if single_book_summary_path.is_file():
        sections.append("## single_book_summary.md")
        sections.append(single_book_summary_path.read_text(encoding="utf-8").rstrip())
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

    This helper is used by interactive single-book benchmark flows to emit
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
        "upload_3_files_contract": (
            {
                review_dir: list(UPLOAD_BUNDLE_FILE_NAMES)
                for review_dir in UPLOAD_BUNDLE_REVIEW_PROFILE_DIR_NAMES
            }
            if args.upload_3_files
            else {}
        ),
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
        for review_dir in UPLOAD_BUNDLE_REVIEW_PROFILE_DIR_NAMES:
            for file_name in UPLOAD_BUNDLE_FILE_NAMES:
                included_files.add(f"{review_dir}/{file_name}")
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
