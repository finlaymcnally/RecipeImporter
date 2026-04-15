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

Ownership note:
- this root remains the CLI/orchestration surface for the cutdown package
- owner modules under `cookimport/bench/external_ai_cutdown/` now hold the
  reusable helper families
- the largest logic still intentionally left here is the late-stage reporting
  and packaging layer: scorecards, ablations, chapter/page breakdowns, top
  regression packets, and final package assembly in `main()`
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
from cookimport.bench.external_ai_cutdown.row_gold_sampling import (
    _build_correct_label_sample,
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
    _resolve_recipe_manifest_path as _resolve_recipe_manifest_path_impl,
)
from cookimport.bench.external_ai_cutdown.comparison_diagnostics import (
    _aggregate_confusion_deltas as _aggregate_confusion_deltas_impl,
    _aggregate_region_accuracy as _aggregate_region_accuracy_impl,
    _build_comparison_summary as _build_comparison_summary_impl,
    _build_pair_diagnostics as _build_pair_diagnostics_impl,
    _build_warning_and_trace_summary as _build_warning_and_trace_summary_impl,
    _select_targeted_prompt_cases as _select_targeted_prompt_cases_impl,
    _write_targeted_prompt_cases_markdown as _write_targeted_prompt_cases_markdown_impl,
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
from cookimport.bench.external_ai_cutdown.diagnostic_packets import (
    _build_preprocess_trace_failure_rows as _build_preprocess_trace_failure_rows_impl,
    _build_wrong_label_full_context_rows as _build_wrong_label_full_context_rows_impl,
    _load_extracted_archive_blocks as _load_extracted_archive_blocks_impl,
    _prompt_row_sort_key as _prompt_row_sort_key_impl,
    _select_prompt_rows_by_recipe as _select_prompt_rows_by_recipe_impl,
    _write_jsonl_gzip_deterministic as _write_jsonl_gzip_deterministic_impl,
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
from cookimport.bench.external_ai_cutdown.high_level_artifacts import (
    GROUP_UPLOAD_BUNDLE_MIN_ARTIFACT_BUDGET_BYTES,
    GROUP_UPLOAD_BUNDLE_ROOT_ARTIFACT_BUDGET_SHARE,
    GROUP_UPLOAD_BUNDLE_ROOT_PRIORITY_FILES,
    GROUP_UPLOAD_BUNDLE_RUN_CONTEXT_FILES,
    GROUP_UPLOAD_BUNDLE_RUN_PRIORITY_FILES,
    _json_dump_bytes_impl,
    _json_size_bytes_impl,
    _resolve_prompt_budget_summary_path,
    _upload_bundle_load_json_object,
    _upload_bundle_build_group_high_level_packet_impl,
    _upload_bundle_build_knowledge_summary_impl,
    _upload_bundle_category_impl,
    _upload_bundle_content_type_impl,
    _upload_bundle_derived_run_artifact_path_impl,
    _upload_bundle_high_level_final_reserve_bytes_impl,
    _upload_bundle_high_level_trim_priority_impl,
    _upload_bundle_load_csv_rows_impl,
    _upload_bundle_load_recipe_triage_rows_impl,
    _upload_bundle_optional_artifact_status_impl,
    _upload_bundle_parse_csv_text_impl,
    _upload_bundle_parse_jsonl_text_impl,
    _upload_bundle_payload_row_line_bytes_impl,
    _upload_bundle_relative_path_within_root_impl,
    _upload_bundle_select_high_level_artifact_paths,
    _upload_bundle_trim_high_level_payload_rows_impl,
)
from cookimport.bench.external_ai_cutdown.line_projection import (
    _build_line_prediction_view as _build_line_prediction_view_impl,
    _build_recipe_spans_from_full_prompt_rows as _build_recipe_spans_from_full_prompt_rows_impl,
    _normalize_recipe_spans_to_line_coordinates as _normalize_recipe_spans_to_line_coordinates_impl,
    _resolve_recipe_for_line as _resolve_recipe_for_line_impl,
    _span_contains_line as _span_contains_line_impl,
    _span_line_bounds as _span_line_bounds_impl,
    _span_line_indices as _span_line_indices_impl,
)
from cookimport.bench.external_ai_cutdown.prompt_diagnostics import (
    _coerce_str_list as _coerce_str_list_impl,
    _is_empty_mapping_value as _is_empty_mapping_value_impl,
    _normalize_warning_bucket_name as _normalize_warning_bucket_name_impl,
    _normalize_warning_bucket_reason as _normalize_warning_bucket_reason_impl,
    _normalize_whitespace as _normalize_whitespace_impl,
    _parse_json_like as _parse_json_like_impl,
    _prompt_warning_bucket as _prompt_warning_bucket_impl,
    _summarize_prompt_warning_aggregate as _summarize_prompt_warning_aggregate_impl,
    _upload_bundle_recipe_correction_input_block_count as _upload_bundle_recipe_correction_input_block_count_impl,
    _upload_bundle_recipe_correction_metrics as _upload_bundle_recipe_correction_metrics_impl,
    _upload_bundle_recipe_correction_output_for_recipe as _upload_bundle_recipe_correction_output_for_recipe_impl,
    _upload_bundle_recipe_correction_output_rows as _upload_bundle_recipe_correction_output_rows_impl,
)
from cookimport.bench.external_ai_cutdown.prompt_log_reconstruction import (
    _reconstruct_full_prompt_log as _reconstruct_full_prompt_log_impl,
)
from cookimport.bench.external_ai_cutdown.projection_trace import (
    _alignment_is_healthy as _alignment_is_healthy_impl,
    _build_projection_trace as _build_projection_trace_impl,
    _first_prompt_block_excerpt as _first_prompt_block_excerpt_impl,
    _line_context as _line_context_impl,
    _prompt_row_owned_recipe_ids as _prompt_row_owned_recipe_ids_impl,
    _prompt_row_recipe_id as _prompt_row_recipe_id_impl,
    _prompt_row_stage_key as _prompt_row_stage_key_impl,
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
from cookimport.bench.external_ai_cutdown.prompt_case_views import (
    _block_id_from_row as _block_id_from_row_impl,
    _blocks_from_request_payload as _blocks_from_request_payload_impl,
    _build_intermediate_selected_blocks as _build_intermediate_selected_blocks_impl,
    _correction_input_blocks as _correction_input_blocks_impl,
    _count_list_entries as _count_list_entries_impl,
    _final_recipe_step_count as _final_recipe_step_count_impl,
    _input_excerpt_for_prompt_row as _input_excerpt_for_prompt_row_impl,
    _mapping_count as _mapping_count_impl,
    _nearest_recipe_id_for_line_index as _nearest_recipe_id_for_line_index_impl,
    _output_excerpt_for_prompt_row as _output_excerpt_for_prompt_row_impl,
    _prompt_case_score as _prompt_case_score_impl,
    _prompt_row_identity_key as _prompt_row_identity_key_impl,
    _recipe_short_title as _recipe_short_title_impl,
    _to_json_excerpt as _to_json_excerpt_impl,
    _warning_buckets as _warning_buckets_impl,
)
from cookimport.bench.external_ai_cutdown.run_cutdown import (
    _build_run_cutdown as _build_run_cutdown_impl,
    _build_run_record_from_existing_run as _build_run_record_from_existing_run_impl,
)
from cookimport.bench.external_ai_cutdown.root_rendering import (
    _flatten_output as _flatten_output_impl,
    _write_readme as _write_readme_impl,
    _write_root_summary_markdown as _write_root_summary_markdown_impl,
    write_flattened_summary_for_existing_runs as write_flattened_summary_for_existing_runs_impl,
)
from cookimport.bench.external_ai_cutdown.starter_pack import (
    _bridge_anomaly_summary as _bridge_anomaly_summary_impl,
    _build_selected_recipe_packets as _build_selected_recipe_packets_impl,
    _group_changed_lines_by_recipe as _group_changed_lines_by_recipe_impl,
    _recipe_row_key as _recipe_row_key_impl,
    _render_starter_pack_casebook as _render_starter_pack_casebook_impl,
    _render_starter_pack_label_policy as _render_starter_pack_label_policy_impl,
    _select_starter_pack_recipe_cases as _select_starter_pack_recipe_cases_impl,
    _sort_recipe_rows_for_metric as _sort_recipe_rows_for_metric_impl,
    _warning_summary_for_recipe as _warning_summary_for_recipe_impl,
    _write_starter_pack_readme as _write_starter_pack_readme_impl,
)
from cookimport.bench.external_ai_cutdown.starter_pack_writer import (
    _write_starter_pack_v1 as _write_starter_pack_v1_impl,
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
ORACLE_REVIEW_PACKET_TARGET_BYTES = 820_000
ORACLE_REVIEW_PACKET_MAX_ROW_BYTES = 48 * 1024
ORACLE_REVIEW_PACKET_PROMPT_TOTAL_BYTES = 16 * 1024
ORACLE_REVIEW_PACKET_PROMPT_SECTION_BYTES = 3 * 1024
ORACLE_REVIEW_PACKET_PROMPT_SECTION_LIMIT = 4
ORACLE_REVIEW_PACKET_COMPACT_LIST_LIMIT = 8
ORACLE_REVIEW_PACKET_COMPACT_EXCERPT_LIMIT = 240
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
CHANGED_LINES_FILE_NAME = "changed_lines.benchmark_comparison.jsonl"
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
    return _write_jsonl_gzip_deterministic_impl(path, rows)


def _load_extracted_archive_blocks(path: Path) -> dict[int, dict[str, Any]]:
    return _load_extracted_archive_blocks_impl(
        path,
        coerce_int=_coerce_int,
    )


def _prompt_row_sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
    return _prompt_row_sort_key_impl(
        row,
        prompt_row_stage_key=_prompt_row_stage_key,
        llm_stage_map=LLM_STAGE_MAP,
        parse_json_like=_parse_json_like,
        coerce_str_list=_coerce_str_list,
    )


def _select_prompt_rows_by_recipe(
    full_prompt_rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    return _select_prompt_rows_by_recipe_impl(
        full_prompt_rows,
        prompt_row_sort_key=_prompt_row_sort_key,
        prompt_row_owned_recipe_ids=_prompt_row_owned_recipe_ids,
    )


def _build_wrong_label_full_context_rows(
    *,
    run_dir: Path,
    recipe_spans: list[dict[str, Any]],
    excerpt_limit: int,
) -> list[dict[str, Any]]:
    return _build_wrong_label_full_context_rows_impl(
        run_dir=run_dir,
        recipe_spans=recipe_spans,
        excerpt_limit=excerpt_limit,
        iter_jsonl=_iter_jsonl,
        load_json=_load_json,
        coerce_int=_coerce_int,
        source_file_name=_source_file_name,
        source_key=_source_key,
        build_line_prediction_view=_build_line_prediction_view,
        line_context=_line_context,
    )


def _build_preprocess_trace_failure_rows(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    full_prompt_rows: list[dict[str, Any]],
    excerpt_limit: int,
) -> tuple[list[dict[str, Any]], str]:
    return _build_preprocess_trace_failure_rows_impl(
        run_dir=run_dir,
        run_manifest=run_manifest,
        full_prompt_rows=full_prompt_rows,
        excerpt_limit=excerpt_limit,
        iter_jsonl=_iter_jsonl,
        coerce_int=_coerce_int,
        parse_json_like=_parse_json_like,
        coerce_str_list=_coerce_str_list,
        normalize_whitespace=_normalize_whitespace,
        prompt_warning_bucket=_prompt_warning_bucket,
        prompt_row_stage_key=_prompt_row_stage_key,
        source_file_name=_source_file_name,
        source_key=_source_key,
        excerpt=_excerpt,
        line_context=_line_context,
        first_prompt_block_excerpt=_first_prompt_block_excerpt,
        select_prompt_row_for_trace=select_prompt_row_for_trace,
        resolve_trace_status=resolve_trace_status,
        resolve_prediction_run_dir=_resolve_prediction_run_dir,
        resolve_extracted_archive_path=_resolve_extracted_archive_path,
        load_extracted_archive_blocks=_load_extracted_archive_blocks,
        select_prompt_rows_by_recipe=_select_prompt_rows_by_recipe,
        build_recipe_spans_from_full_prompt_rows=_build_recipe_spans_from_full_prompt_rows,
        build_line_prediction_view=_build_line_prediction_view,
    )


def _parse_json_like(value: Any) -> Any:
    return _parse_json_like_impl(value)


def _coerce_str_list(value: Any) -> list[str]:
    return _coerce_str_list_impl(value)


def _is_empty_mapping_value(value: Any) -> bool:
    return _is_empty_mapping_value_impl(value)


def _upload_bundle_recipe_correction_output_rows(value: Any) -> list[dict[str, Any]]:
    return _upload_bundle_recipe_correction_output_rows_impl(value)


def _upload_bundle_recipe_correction_output_for_recipe(
    value: Any,
    *,
    recipe_id: str,
) -> dict[str, Any]:
    return _upload_bundle_recipe_correction_output_for_recipe_impl(
        value,
        recipe_id=recipe_id,
    )


def _upload_bundle_recipe_correction_input_block_count(
    value: Any,
    *,
    recipe_id: str | None = None,
) -> int:
    return _upload_bundle_recipe_correction_input_block_count_impl(
        value,
        recipe_id=recipe_id,
    )


def _upload_bundle_recipe_correction_metrics(output_row: dict[str, Any]) -> dict[str, Any]:
    return _upload_bundle_recipe_correction_metrics_impl(
        output_row,
        mapping_count=_mapping_count,
    )


def _normalize_whitespace(text: str) -> str:
    return _normalize_whitespace_impl(text)


def _normalize_warning_bucket_name(bucket: str) -> str:
    return _normalize_warning_bucket_name_impl(bucket)


def _normalize_warning_bucket_reason(reason: str) -> str:
    return _normalize_warning_bucket_reason_impl(reason)


def _prompt_warning_bucket(message: str) -> str:
    return _prompt_warning_bucket_impl(message)


def _summarize_prompt_warning_aggregate(full_prompt_log_path: Path) -> dict[str, Any]:
    return _summarize_prompt_warning_aggregate_impl(
        full_prompt_log_path,
        prompt_row_stage_key=_prompt_row_stage_key,
        mapping_count=_mapping_count,
    )


def _build_recipe_spans_from_full_prompt_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _build_recipe_spans_from_full_prompt_rows_impl(
        rows=rows,
        prompt_row_stage_key=_prompt_row_stage_key,
        parse_json_like=_parse_json_like,
    )


def _normalize_recipe_spans_to_line_coordinates(
    *,
    run_dir: Path,
    recipe_spans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _normalize_recipe_spans_to_line_coordinates_impl(
        run_dir=run_dir,
        recipe_spans=recipe_spans,
    )


def _span_line_indices(span: dict[str, Any]) -> list[int] | None:
    return _span_line_indices_impl(span)


def _span_line_bounds(span: dict[str, Any]) -> tuple[int | None, int | None]:
    return _span_line_bounds_impl(span)


def _span_contains_line(*, span: dict[str, Any], line_index: int) -> bool:
    return _span_contains_line_impl(span=span, line_index=line_index)


def _resolve_recipe_for_line(
    *,
    line_index: int,
    recipe_spans: list[dict[str, Any]],
) -> tuple[str | None, str]:
    return _resolve_recipe_for_line_impl(
        line_index=line_index,
        recipe_spans=recipe_spans,
    )


def _build_line_prediction_view(
    *,
    run_dir: Path,
    recipe_spans: list[dict[str, Any]],
) -> LinePredictionView:
    return _build_line_prediction_view_impl(
        run_dir=run_dir,
        recipe_spans=recipe_spans,
        line_prediction_view_type=LinePredictionView,
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
    return _line_context_impl(
        line_text_by_index=line_text_by_index,
        line_index=line_index,
        excerpt_limit=excerpt_limit,
        excerpt=_excerpt,
    )


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
    recipe_manifest_path = _resolve_recipe_manifest_path_impl(
        run_dir=run_dir,
        run_manifest=run_manifest,
    )
    if recipe_manifest_path is not None:
        candidate_paths.append(recipe_manifest_path)

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


def _reconstruct_full_prompt_log(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    output_path: Path,
) -> int:
    return _reconstruct_full_prompt_log_impl(
        run_dir=run_dir,
        run_manifest=run_manifest,
        output_path=output_path,
        llm_stage_map=LLM_STAGE_MAP,
    )


def _alignment_is_healthy(alignment: dict[str, Any]) -> bool:
    return _alignment_is_healthy_impl(
        alignment,
        coerce_float=_coerce_float,
        coverage_min=ALIGNMENT_HEALTHY_COVERAGE_MIN,
        match_ratio_min=ALIGNMENT_HEALTHY_MATCH_RATIO_MIN,
    )


def _build_projection_trace(
    *,
    line_view: LinePredictionView,
    full_prompt_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return _build_projection_trace_impl(
        line_view=line_view,
        full_prompt_rows=full_prompt_rows,
        prompt_row_stage_key=_prompt_row_stage_key,
        parse_json_like=_parse_json_like,
        coerce_str_list=_coerce_str_list,
        upload_bundle_recipe_correction_output_rows=_upload_bundle_recipe_correction_output_rows,
        upload_bundle_recipe_correction_metrics=_upload_bundle_recipe_correction_metrics,
        is_empty_mapping_value=_is_empty_mapping_value,
        rate=_rate,
    )


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
    return _build_run_cutdown_impl(
        run_dir=run_dir,
        output_run_dir=output_run_dir,
        sample_limit=sample_limit,
        excerpt_limit=excerpt_limit,
        top_confusions_limit=top_confusions_limit,
        top_labels_limit=top_labels_limit,
        prompt_pairs_per_category=prompt_pairs_per_category,
        prompt_excerpt_limit=prompt_excerpt_limit,
        record_cls=RunRecord,
        load_json=_load_json,
        write_json=_write_json,
        write_jsonl_sample=_write_jsonl_sample,
        jsonl_row_count=_jsonl_row_count,
        iter_jsonl=_iter_jsonl,
        coerce_float=_coerce_float,
        coerce_int=_coerce_int,
        source_file_name=_source_file_name,
        source_key=_source_key,
        parse_run_timestamp=_parse_run_timestamp,
        config_snapshot=_config_snapshot,
        top_confusions=_top_confusions,
        compact_per_label=_compact_per_label,
        lowest_metric_labels=_lowest_metric_labels,
        alignment_is_healthy=_alignment_is_healthy,
        resolve_prompt_log_path=_resolve_prompt_log_path,
        resolve_full_prompt_log_path=_resolve_full_prompt_log_path,
        reconstruct_full_prompt_log=_reconstruct_full_prompt_log,
        build_recipe_spans_from_full_prompt_rows=_build_recipe_spans_from_full_prompt_rows,
        write_prompt_log_samples_from_full_prompt_log=_write_prompt_log_samples_from_full_prompt_log,
        write_prompt_log_samples=_write_prompt_log_samples,
        summarize_prompt_warning_aggregate=_summarize_prompt_warning_aggregate,
        build_line_prediction_view=_build_line_prediction_view,
        build_projection_trace=_build_projection_trace,
        build_wrong_label_full_context_rows=_build_wrong_label_full_context_rows,
        write_jsonl_gzip_deterministic=_write_jsonl_gzip_deterministic,
        build_preprocess_trace_failure_rows=_build_preprocess_trace_failure_rows,
        line_level_sampled_jsonl_inputs=LINE_LEVEL_SAMPLED_JSONL_INPUTS,
        unmatched_pred_blocks_input=UNMATCHED_PRED_BLOCKS_INPUT,
        alignment_sampled_jsonl_inputs=ALIGNMENT_SAMPLED_JSONL_INPUTS,
        full_prompt_log_file_name=FULL_PROMPT_LOG_FILE_NAME,
        prompt_log_file_name=PROMPT_LOG_FILE_NAME,
        prompt_warning_aggregate_file_name=PROMPT_WARNING_AGGREGATE_FILE_NAME,
        projection_trace_file_name=PROJECTION_TRACE_FILE_NAME,
        wrong_label_full_context_file_name=WRONG_LABEL_FULL_CONTEXT_FILE_NAME,
        preprocess_trace_failures_file_name=PREPROCESS_TRACE_FAILURES_FILE_NAME,
        alignment_healthy_coverage_min=ALIGNMENT_HEALTHY_COVERAGE_MIN,
        alignment_healthy_match_ratio_min=ALIGNMENT_HEALTHY_MATCH_RATIO_MIN,
    )


def _build_run_record_from_existing_run(
    *,
    run_dir: Path,
    top_confusions_limit: int = DEFAULT_TOP_CONFUSIONS,
) -> RunRecord:
    return _build_run_record_from_existing_run_impl(
        run_dir=run_dir,
        top_confusions_limit=top_confusions_limit,
        record_cls=RunRecord,
        load_json=_load_json,
        source_file_name=_source_file_name,
        source_key=_source_key,
        coerce_float=_coerce_float,
        coerce_int=_coerce_int,
        parse_run_timestamp=_parse_run_timestamp,
        config_snapshot=_config_snapshot,
        top_confusions=_top_confusions,
        resolve_full_prompt_log_path=_resolve_full_prompt_log_path,
        iter_jsonl=_iter_jsonl,
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
    return _first_prompt_block_excerpt_impl(
        row,
        excerpt_limit=excerpt_limit,
        parse_json_like=_parse_json_like,
        excerpt=_excerpt,
        normalize_whitespace=_normalize_whitespace,
    )


def _prompt_case_score(
    *,
    stage_key: str,
    warnings_count: int,
    empty_mapping: bool,
    changed_lines_for_recipe: int,
) -> int:
    return _prompt_case_score_impl(
        stage_key=stage_key,
        warnings_count=warnings_count,
        empty_mapping=empty_mapping,
        changed_lines_for_recipe=changed_lines_for_recipe,
    )


def _prompt_row_identity_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return _prompt_row_identity_key_impl(row)


def _prompt_row_stage_key(row: dict[str, Any]) -> str:
    return _prompt_row_stage_key_impl(row)


def _prompt_row_recipe_id(row: dict[str, Any]) -> str:
    return _prompt_row_recipe_id_impl(
        row,
        parse_json_like=_parse_json_like,
    )


def _prompt_row_owned_recipe_ids(row: dict[str, Any]) -> list[str]:
    return _prompt_row_owned_recipe_ids_impl(
        row,
        parse_json_like=_parse_json_like,
    )


def _warning_buckets(warnings: list[str]) -> list[str]:
    return _warning_buckets_impl(
        warnings,
        prompt_warning_bucket=_prompt_warning_bucket,
        normalize_whitespace=_normalize_whitespace,
    )


def _count_list_entries(value: Any) -> int:
    return _count_list_entries_impl(
        value,
        parse_json_like=_parse_json_like,
    )


def _blocks_from_request_payload(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return _blocks_from_request_payload_impl(payload, key)


def _block_id_from_row(block: dict[str, Any]) -> str | None:
    return _block_id_from_row_impl(
        block,
        coerce_int=_coerce_int,
    )


def _build_intermediate_selected_blocks(
    row: dict[str, Any],
) -> tuple[list[dict[str, Any]], int | None, int | None]:
    return _build_intermediate_selected_blocks_impl(
        row,
        parse_json_like=_parse_json_like,
        coerce_int=_coerce_int,
        coerce_str_list=_coerce_str_list,
    )


def _correction_input_blocks(row: dict[str, Any]) -> list[dict[str, Any]]:
    return _correction_input_blocks_impl(
        row,
        parse_json_like=_parse_json_like,
    )


def _final_recipe_step_count(parsed_response: dict[str, Any]) -> int:
    return _final_recipe_step_count_impl(
        parsed_response,
        parse_json_like=_parse_json_like,
    )


def _mapping_count(value: Any) -> int:
    return _mapping_count_impl(
        value,
        parse_json_like=_parse_json_like,
    )


def _to_json_excerpt(value: Any, *, excerpt_limit: int) -> str:
    return _to_json_excerpt_impl(
        value,
        excerpt_limit=excerpt_limit,
        excerpt=_excerpt,
        normalize_whitespace=_normalize_whitespace,
    )


def _input_excerpt_for_prompt_row(row: dict[str, Any], *, excerpt_limit: int) -> str:
    return _input_excerpt_for_prompt_row_impl(
        row,
        excerpt_limit=excerpt_limit,
        first_prompt_block_excerpt=_first_prompt_block_excerpt,
        parse_json_like=_parse_json_like,
        excerpt=_excerpt,
        normalize_whitespace=_normalize_whitespace,
    )


def _output_excerpt_for_prompt_row(row: dict[str, Any], *, excerpt_limit: int) -> str:
    return _output_excerpt_for_prompt_row_impl(
        row,
        excerpt_limit=excerpt_limit,
        parse_json_like=_parse_json_like,
        coerce_str_list=_coerce_str_list,
        prompt_row_stage_key=_prompt_row_stage_key,
        excerpt=_excerpt,
        normalize_whitespace=_normalize_whitespace,
    )


def _recipe_short_title(
    *,
    recipe_id: str,
    recipe_spans: list[dict[str, Any]],
    correction_row: dict[str, Any] | None,
) -> str:
    return _recipe_short_title_impl(
        recipe_id=recipe_id,
        recipe_spans=recipe_spans,
        correction_row=correction_row,
        parse_json_like=_parse_json_like,
    )


def _nearest_recipe_id_for_line_index(
    *,
    line_index: int,
    recipe_spans: list[dict[str, Any]],
) -> str | None:
    return _nearest_recipe_id_for_line_index_impl(
        line_index=line_index,
        recipe_spans=recipe_spans,
        span_line_bounds=_span_line_bounds,
    )


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
    return _build_pair_diagnostics_impl(
        source_key=source_key,
        source_file=source_file,
        codex_run=codex_run,
        baseline_run=baseline_run,
        excerpt_limit=excerpt_limit,
        targeted_case_limit=targeted_case_limit,
        pair_diagnostics_cls=PairDiagnostics,
        llm_stage_map=LLM_STAGE_MAP,
        load_full_prompt_rows_for_run=_load_full_prompt_rows_for_run,
        normalize_recipe_spans_to_line_coordinates=_normalize_recipe_spans_to_line_coordinates,
        build_recipe_spans_from_full_prompt_rows=_build_recipe_spans_from_full_prompt_rows,
        build_line_prediction_view=_build_line_prediction_view,
        line_context=_line_context,
        rate=_rate,
        delta=_delta,
        confusion_matrix_from_view=_confusion_matrix_from_view,
        delta_confusion_matrix=_delta_confusion_matrix,
        prompt_row_stage_key=_prompt_row_stage_key,
        parse_json_like=_parse_json_like,
        coerce_str_list=_coerce_str_list,
        upload_bundle_recipe_correction_output_rows=_upload_bundle_recipe_correction_output_rows,
        upload_bundle_recipe_correction_metrics=_upload_bundle_recipe_correction_metrics,
        is_empty_mapping_value=_is_empty_mapping_value,
        first_prompt_block_excerpt=_first_prompt_block_excerpt,
        prompt_case_score=_prompt_case_score,
        prompt_row_identity_key=_prompt_row_identity_key,
        prompt_row_owned_recipe_ids=_prompt_row_owned_recipe_ids,
        load_json=_load_json,
        load_llm_manifest_recipe_diagnostics=_load_llm_manifest_recipe_diagnostics,
        build_preprocess_trace_failure_rows=_build_preprocess_trace_failure_rows,
        coerce_int=_coerce_int,
        nearest_recipe_id_for_line_index=_nearest_recipe_id_for_line_index,
        build_intermediate_selected_blocks=_build_intermediate_selected_blocks,
        upload_bundle_recipe_stages_for_row=_upload_bundle_recipe_stages_for_row,
        upload_bundle_recipe_correction_output_for_recipe=_upload_bundle_recipe_correction_output_for_recipe,
        upload_bundle_recipe_correction_input_block_count=_upload_bundle_recipe_correction_input_block_count,
        warning_buckets=_warning_buckets,
        final_recipe_step_count=_final_recipe_step_count,
        mapping_count=_mapping_count,
        coerce_bool=_coerce_bool,
        coerce_float=_coerce_float,
        recipe_short_title=_recipe_short_title,
        input_excerpt_for_prompt_row=_input_excerpt_for_prompt_row,
        upload_bundle_call_inventory_stage_included=_upload_bundle_call_inventory_stage_included,
        upload_bundle_extract_call_runtime=_upload_bundle_extract_call_runtime,
        upload_bundle_estimate_call_cost_usd=_upload_bundle_estimate_call_cost_usd,
        upload_bundle_call_inventory_stage_rank=_upload_bundle_call_inventory_stage_rank,
        prompt_row_recipe_id=_prompt_row_recipe_id,
        output_excerpt_for_prompt_row=_output_excerpt_for_prompt_row,
        stage_label=stage_label,
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
    return _build_comparison_summary_impl(
        records=records,
        excerpt_limit=excerpt_limit,
        targeted_prompt_case_limit=targeted_prompt_case_limit,
        build_pair_diagnostics=_build_pair_diagnostics,
        nearest_baseline=_nearest_baseline,
        delta=_delta,
        config_differences=_config_differences,
    )


def _select_targeted_prompt_cases(
    *,
    rows: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    return _select_targeted_prompt_cases_impl(
        rows=rows,
        limit=limit,
    )


def _write_targeted_prompt_cases_markdown(
    *,
    output_path: Path,
    rows: list[dict[str, Any]],
) -> None:
    _write_targeted_prompt_cases_markdown_impl(
        output_path=output_path,
        rows=rows,
        excerpt=_excerpt,
    )


def _aggregate_region_accuracy(
    pair_breakdown_rows: list[dict[str, Any]],
) -> tuple[float | None, float | None, float | None]:
    return _aggregate_region_accuracy_impl(
        pair_breakdown_rows,
        coerce_int=_coerce_int,
        rate=_rate,
    )


def _aggregate_confusion_deltas(
    comparison_summary: dict[str, Any],
    *,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    return _aggregate_confusion_deltas_impl(
        comparison_summary,
        coerce_int=_coerce_int,
        top_k=top_k,
    )


def _build_warning_and_trace_summary(
    *,
    call_inventory_rows: list[dict[str, Any]],
    recipe_triage_rows: list[dict[str, Any]],
    outside_span_trace_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return _build_warning_and_trace_summary_impl(
        call_inventory_rows=call_inventory_rows,
        recipe_triage_rows=recipe_triage_rows,
        outside_span_trace_rows=outside_span_trace_rows,
        coerce_int=_coerce_int,
        coerce_str_list=_coerce_str_list,
        upload_bundle_status_is_problem=_upload_bundle_status_is_problem,
        counter_to_sorted_dict=_counter_to_sorted_dict,
    )


def _recipe_row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return _recipe_row_key_impl(row)


def _sort_recipe_rows_for_metric(
    rows: list[dict[str, Any]],
    *,
    metric_key: str,
) -> list[dict[str, Any]]:
    return _sort_recipe_rows_for_metric_impl(
        rows,
        metric_key=metric_key,
        coerce_int=_coerce_int,
        float_or_zero=_float_or_zero,
    )


def _select_starter_pack_recipe_cases(
    recipe_triage_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _select_starter_pack_recipe_cases_impl(
        recipe_triage_rows,
        coerce_int=_coerce_int,
        float_or_zero=_float_or_zero,
        selection_policy=STARTER_PACK_SELECTION_POLICY,
    )


def _group_changed_lines_by_recipe(
    changed_line_rows: list[dict[str, Any]],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    return _group_changed_lines_by_recipe_impl(
        changed_line_rows,
        coerce_int=_coerce_int,
    )


def _bridge_anomaly_summary(row: dict[str, Any]) -> str:
    return _bridge_anomaly_summary_impl(
        row,
        coerce_int=_coerce_int,
        serialize_bool=_serialize_bool,
    )


def _warning_summary_for_recipe(row: dict[str, Any]) -> str:
    return _warning_summary_for_recipe_impl(
        row,
        coerce_int=_coerce_int,
        serialize_pipe_list=_serialize_pipe_list,
        coerce_str_list=_coerce_str_list,
    )


def _build_selected_recipe_packets(
    *,
    selected_recipe_rows: list[dict[str, Any]],
    changed_line_rows: list[dict[str, Any]],
    default_recipe_stages: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    return _build_selected_recipe_packets_impl(
        selected_recipe_rows=selected_recipe_rows,
        changed_line_rows=changed_line_rows,
        default_recipe_stages=default_recipe_stages,
        coerce_int=_coerce_int,
        coerce_float=_coerce_float,
        coerce_str_list=_coerce_str_list,
        diagnostic_value_has_signal=_diagnostic_value_has_signal,
        bridge_anomaly_summary=_bridge_anomaly_summary,
        warning_summary_for_recipe=_warning_summary_for_recipe,
    )


def _render_starter_pack_casebook(packets: list[dict[str, Any]]) -> str:
    return _render_starter_pack_casebook_impl(
        packets,
        coerce_int=_coerce_int,
        excerpt=_excerpt,
    )


def _render_starter_pack_label_policy() -> str:
    return _render_starter_pack_label_policy_impl()


def _write_starter_pack_readme(
    *,
    output_path: Path,
    comparison_summary: dict[str, Any],
) -> None:
    _write_starter_pack_readme_impl(
        output_path=output_path,
        comparison_summary=comparison_summary,
        starter_pack_dir_name=STARTER_PACK_DIR_NAME,
        starter_pack_triage_file_name=STARTER_PACK_TRIAGE_FILE_NAME,
        starter_pack_triage_packet_file_name=STARTER_PACK_TRIAGE_PACKET_FILE_NAME,
        starter_pack_call_inventory_file_name=STARTER_PACK_CALL_INVENTORY_FILE_NAME,
        starter_pack_changed_lines_file_name=STARTER_PACK_CHANGED_LINES_FILE_NAME,
        starter_pack_warning_trace_summary_file_name=STARTER_PACK_WARNING_TRACE_SUMMARY_FILE_NAME,
        starter_pack_bridge_summary_file_name=STARTER_PACK_BRIDGE_SUMMARY_FILE_NAME,
        starter_pack_selected_packets_file_name=STARTER_PACK_SELECTED_PACKETS_FILE_NAME,
        starter_pack_casebook_file_name=STARTER_PACK_CASEBOOK_FILE_NAME,
        starter_pack_outside_trace_file_name=STARTER_PACK_OUTSIDE_TRACE_FILE_NAME,
        starter_pack_label_policy_file_name=STARTER_PACK_LABEL_POLICY_FILE_NAME,
        starter_pack_manifest_file_name=STARTER_PACK_MANIFEST_FILE_NAME,
        starter_pack_comparison_mirror_file_name=STARTER_PACK_COMPARISON_MIRROR_FILE_NAME,
        starter_pack_breakdown_mirror_file_name=STARTER_PACK_BREAKDOWN_MIRROR_FILE_NAME,
        starter_pack_net_error_blame_file_name=STARTER_PACK_NET_ERROR_BLAME_FILE_NAME,
        starter_pack_config_version_metadata_file_name=STARTER_PACK_CONFIG_VERSION_METADATA_FILE_NAME,
        starter_pack_explicit_escalation_changed_lines_file_name=STARTER_PACK_EXPLICIT_ESCALATION_CHANGED_LINES_FILE_NAME,
        starter_pack_baseline_trace_parity_file_name=STARTER_PACK_BASELINE_TRACE_PARITY_FILE_NAME,
        timestamp_now=_timestamp_now,
    )


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
    return _write_starter_pack_v1_impl(
        output_dir=output_dir,
        comparison_summary=comparison_summary,
        changed_line_rows=changed_line_rows,
        pair_breakdown_rows=pair_breakdown_rows,
        per_recipe_breakdown_payload=per_recipe_breakdown_payload,
        recipe_triage_rows=recipe_triage_rows,
        call_inventory_rows=call_inventory_rows,
        outside_span_trace_rows=outside_span_trace_rows,
        sample_limit=sample_limit,
        starter_pack_dir_name=STARTER_PACK_DIR_NAME,
        starter_pack_readme_file_name=STARTER_PACK_README_FILE_NAME,
        starter_pack_triage_file_name=STARTER_PACK_TRIAGE_FILE_NAME,
        starter_pack_triage_packet_file_name=STARTER_PACK_TRIAGE_PACKET_FILE_NAME,
        starter_pack_call_inventory_file_name=STARTER_PACK_CALL_INVENTORY_FILE_NAME,
        starter_pack_changed_lines_file_name=STARTER_PACK_CHANGED_LINES_FILE_NAME,
        starter_pack_warning_trace_summary_file_name=STARTER_PACK_WARNING_TRACE_SUMMARY_FILE_NAME,
        starter_pack_bridge_summary_file_name=STARTER_PACK_BRIDGE_SUMMARY_FILE_NAME,
        starter_pack_selected_packets_file_name=STARTER_PACK_SELECTED_PACKETS_FILE_NAME,
        starter_pack_casebook_file_name=STARTER_PACK_CASEBOOK_FILE_NAME,
        starter_pack_outside_trace_file_name=STARTER_PACK_OUTSIDE_TRACE_FILE_NAME,
        starter_pack_label_policy_file_name=STARTER_PACK_LABEL_POLICY_FILE_NAME,
        starter_pack_manifest_file_name=STARTER_PACK_MANIFEST_FILE_NAME,
        starter_pack_comparison_mirror_file_name=STARTER_PACK_COMPARISON_MIRROR_FILE_NAME,
        starter_pack_breakdown_mirror_file_name=STARTER_PACK_BREAKDOWN_MIRROR_FILE_NAME,
        starter_pack_net_error_blame_file_name=STARTER_PACK_NET_ERROR_BLAME_FILE_NAME,
        starter_pack_config_version_metadata_file_name=STARTER_PACK_CONFIG_VERSION_METADATA_FILE_NAME,
        starter_pack_explicit_escalation_changed_lines_file_name=STARTER_PACK_EXPLICIT_ESCALATION_CHANGED_LINES_FILE_NAME,
        starter_pack_baseline_trace_parity_file_name=STARTER_PACK_BASELINE_TRACE_PARITY_FILE_NAME,
        starter_pack_selection_policy=STARTER_PACK_SELECTION_POLICY,
        starter_pack_outside_wrong_line_threshold=STARTER_PACK_OUTSIDE_WRONG_LINE_THRESHOLD,
        starter_pack_outside_accuracy_gap_threshold=STARTER_PACK_OUTSIDE_ACCURACY_GAP_THRESHOLD,
        starter_pack_heavy_artifacts_omitted_by_default=list(
            STARTER_PACK_HEAVY_ARTIFACTS_OMITTED_BY_DEFAULT
        ),
        upload_bundle_triage_packet_schema_version=UPLOAD_BUNDLE_TRIAGE_PACKET_SCHEMA_VERSION,
        write_starter_pack_readme=_write_starter_pack_readme,
        write_json=_write_json,
        write_jsonl=_write_jsonl,
        starter_pack_serialize_recipe_triage_row=_starter_pack_serialize_recipe_triage_row,
        upload_bundle_build_triage_packet_rows=_upload_bundle_build_triage_packet_rows,
        build_warning_and_trace_summary=_build_warning_and_trace_summary,
        select_starter_pack_recipe_cases=_select_starter_pack_recipe_cases,
        upload_bundle_recipe_stages_for_row=_upload_bundle_recipe_stages_for_row,
        build_selected_recipe_packets=_build_selected_recipe_packets,
        render_starter_pack_casebook=_render_starter_pack_casebook,
        aggregate_region_accuracy=_aggregate_region_accuracy,
        aggregate_confusion_deltas=_aggregate_confusion_deltas,
        render_starter_pack_label_policy=_render_starter_pack_label_policy,
        starter_pack_collect_run_rows_from_pairs=_starter_pack_collect_run_rows_from_pairs,
        starter_pack_build_run_dir_by_id=_starter_pack_build_run_dir_by_id,
        build_recipe_pipeline_topology=build_recipe_pipeline_topology,
        upload_bundle_build_explicit_escalation_changed_lines_packet=_upload_bundle_build_explicit_escalation_changed_lines_packet,
        upload_bundle_build_net_error_blame_summary=_upload_bundle_build_net_error_blame_summary,
        upload_bundle_build_config_version_metadata=_upload_bundle_build_config_version_metadata,
        starter_pack_build_baseline_trace_parity_cues=_starter_pack_build_baseline_trace_parity_cues,
        coerce_int=_coerce_int,
        coerce_float=_coerce_float,
        coerce_str_list=_coerce_str_list,
        float_or_zero=_float_or_zero,
        average_float=_average_float,
        serialize_float=_serialize_float,
        sample_rows_evenly=_sample_rows_evenly,
        timestamp_now=_timestamp_now,
    )


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
    _write_readme_impl(
        output_dir=output_dir,
        input_dir=input_dir,
        records=records,
        sample_limit=sample_limit,
        excerpt_limit=excerpt_limit,
        prompt_pairs_per_category=prompt_pairs_per_category,
        project_context_digest_lines=project_context_digest_lines,
        flattened=flattened,
        timestamp_now=_timestamp_now,
        full_prompt_log_file_name=FULL_PROMPT_LOG_FILE_NAME,
        line_level_sampled_jsonl_inputs=LINE_LEVEL_SAMPLED_JSONL_INPUTS,
        wrong_label_full_context_file_name=WRONG_LABEL_FULL_CONTEXT_FILE_NAME,
        preprocess_trace_failures_file_name=PREPROCESS_TRACE_FAILURES_FILE_NAME,
        prompt_log_file_name=PROMPT_LOG_FILE_NAME,
        prompt_warning_aggregate_file_name=PROMPT_WARNING_AGGREGATE_FILE_NAME,
        projection_trace_file_name=PROJECTION_TRACE_FILE_NAME,
        changed_lines_file_name=CHANGED_LINES_FILE_NAME,
        per_recipe_breakdown_file_name=PER_RECIPE_BREAKDOWN_FILE_NAME,
        targeted_prompt_cases_file_name=TARGETED_PROMPT_CASES_FILE_NAME,
        label_policy_notes_file_name=LABEL_POLICY_NOTES_FILE_NAME,
        starter_pack_dir_name=STARTER_PACK_DIR_NAME,
    )


def _flatten_output(
    *,
    repo_root: Path,
    output_dir: Path,
    flatten_script: Path,
) -> Path:
    return _flatten_output_impl(
        repo_root=repo_root,
        output_dir=output_dir,
        flatten_script=flatten_script,
        root_metadata_files=ROOT_METADATA_FILES,
        starter_pack_dir_name=STARTER_PACK_DIR_NAME,
        aggregated_root_summary_md=AGGREGATED_ROOT_SUMMARY_MD,
        changed_lines_file_name=CHANGED_LINES_FILE_NAME,
        per_recipe_breakdown_file_name=PER_RECIPE_BREAKDOWN_FILE_NAME,
        targeted_prompt_cases_file_name=TARGETED_PROMPT_CASES_FILE_NAME,
        label_policy_notes_file_name=LABEL_POLICY_NOTES_FILE_NAME,
        load_json=_load_json,
        jsonl_row_count=_jsonl_row_count,
    )


def _write_root_summary_markdown(output_dir: Path) -> Path:
    return _write_root_summary_markdown_impl(
        output_dir,
        aggregated_root_summary_md=AGGREGATED_ROOT_SUMMARY_MD,
        changed_lines_file_name=CHANGED_LINES_FILE_NAME,
        per_recipe_breakdown_file_name=PER_RECIPE_BREAKDOWN_FILE_NAME,
        targeted_prompt_cases_file_name=TARGETED_PROMPT_CASES_FILE_NAME,
        label_policy_notes_file_name=LABEL_POLICY_NOTES_FILE_NAME,
        load_json=_load_json,
        jsonl_row_count=_jsonl_row_count,
    )


def _upload_bundle_content_type(path: Path) -> str:
    return _upload_bundle_content_type_impl(path)


def _upload_bundle_parse_jsonl_text(text: str) -> list[Any]:
    return _upload_bundle_parse_jsonl_text_impl(text)


def _upload_bundle_parse_csv_text(text: str) -> dict[str, Any]:
    return _upload_bundle_parse_csv_text_impl(text)


def _upload_bundle_category(
    relative_path: str,
    run_output_dirs: set[str],
) -> tuple[str, str | None]:
    return _upload_bundle_category_impl(
        relative_path,
        run_output_dirs,
        starter_pack_dir_name=STARTER_PACK_DIR_NAME,
    )


def _upload_bundle_load_csv_rows(path: Path) -> list[dict[str, Any]]:
    return _upload_bundle_load_csv_rows_impl(path)


def _upload_bundle_load_recipe_triage_rows(starter_pack_dir: Path) -> list[dict[str, Any]]:
    return _upload_bundle_load_recipe_triage_rows_impl(
        starter_pack_dir,
        starter_pack_triage_file_name=STARTER_PACK_TRIAGE_FILE_NAME,
        starter_pack_triage_legacy_csv_file_name=STARTER_PACK_TRIAGE_LEGACY_CSV_FILE_NAME,
    )


def _json_size_bytes(value: Any) -> int:
    return _json_size_bytes_impl(value)


def _json_dump_bytes(
    value: Any,
    *,
    indent: int | None = None,
    sort_keys: bool = False,
) -> bytes:
    return _json_dump_bytes_impl(value, indent=indent, sort_keys=sort_keys)


def _upload_bundle_payload_row_line_bytes(payload_row: dict[str, Any]) -> int:
    return _upload_bundle_payload_row_line_bytes_impl(payload_row)


def _upload_bundle_high_level_final_reserve_bytes(target_bundle_size_bytes: int) -> int:
    return _upload_bundle_high_level_final_reserve_bytes_impl(
        target_bundle_size_bytes,
        final_reserve_share=GROUP_UPLOAD_BUNDLE_FINAL_RESERVE_SHARE,
        final_reserve_min_bytes=GROUP_UPLOAD_BUNDLE_FINAL_RESERVE_MIN_BYTES,
    )


def _upload_bundle_high_level_trim_priority(path: str) -> tuple[int, str] | None:
    return _upload_bundle_high_level_trim_priority_impl(
        path,
        prompt_request_response_log_name=PROMPT_REQUEST_RESPONSE_LOG_NAME,
        targeted_prompt_cases_file_name=TARGETED_PROMPT_CASES_FILE_NAME,
        label_policy_notes_file_name=LABEL_POLICY_NOTES_FILE_NAME,
        starter_pack_casebook_file_name=STARTER_PACK_CASEBOOK_FILE_NAME,
        starter_pack_selected_packets_file_name=STARTER_PACK_SELECTED_PACKETS_FILE_NAME,
        starter_pack_bridge_summary_file_name=STARTER_PACK_BRIDGE_SUMMARY_FILE_NAME,
        starter_pack_explicit_escalation_changed_lines_file_name=(
            STARTER_PACK_EXPLICIT_ESCALATION_CHANGED_LINES_FILE_NAME
        ),
        starter_pack_baseline_trace_parity_file_name=(
            STARTER_PACK_BASELINE_TRACE_PARITY_FILE_NAME
        ),
        starter_pack_config_version_metadata_file_name=(
            STARTER_PACK_CONFIG_VERSION_METADATA_FILE_NAME
        ),
        starter_pack_net_error_blame_file_name=STARTER_PACK_NET_ERROR_BLAME_FILE_NAME,
        changed_lines_file_name=CHANGED_LINES_FILE_NAME,
        upload_bundle_derived_dir_name=UPLOAD_BUNDLE_DERIVED_DIR_NAME,
        starter_pack_dir_name=STARTER_PACK_DIR_NAME,
    )


def _upload_bundle_trim_high_level_payload_rows(
    *,
    payload_rows: list[dict[str, Any]],
    target_payload_bytes: int,
    preserve_paths: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return _upload_bundle_trim_high_level_payload_rows_impl(
        payload_rows=payload_rows,
        target_payload_bytes=target_payload_bytes,
        preserve_paths=preserve_paths,
        prompt_request_response_log_name=PROMPT_REQUEST_RESPONSE_LOG_NAME,
        targeted_prompt_cases_file_name=TARGETED_PROMPT_CASES_FILE_NAME,
        label_policy_notes_file_name=LABEL_POLICY_NOTES_FILE_NAME,
        starter_pack_casebook_file_name=STARTER_PACK_CASEBOOK_FILE_NAME,
        starter_pack_selected_packets_file_name=STARTER_PACK_SELECTED_PACKETS_FILE_NAME,
        starter_pack_bridge_summary_file_name=STARTER_PACK_BRIDGE_SUMMARY_FILE_NAME,
        starter_pack_explicit_escalation_changed_lines_file_name=(
            STARTER_PACK_EXPLICIT_ESCALATION_CHANGED_LINES_FILE_NAME
        ),
        starter_pack_baseline_trace_parity_file_name=(
            STARTER_PACK_BASELINE_TRACE_PARITY_FILE_NAME
        ),
        starter_pack_config_version_metadata_file_name=(
            STARTER_PACK_CONFIG_VERSION_METADATA_FILE_NAME
        ),
        starter_pack_net_error_blame_file_name=STARTER_PACK_NET_ERROR_BLAME_FILE_NAME,
        changed_lines_file_name=CHANGED_LINES_FILE_NAME,
        upload_bundle_derived_dir_name=UPLOAD_BUNDLE_DERIVED_DIR_NAME,
        starter_pack_dir_name=STARTER_PACK_DIR_NAME,
    )


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
    return _upload_bundle_build_group_high_level_packet_impl(
        source_root=source_root,
        discovered_run_dirs=discovered_run_dirs,
        run_rows=run_rows,
        run_diagnostics=run_diagnostics,
        target_bundle_size_bytes=target_bundle_size_bytes,
        payload_bytes_before_packet=payload_bytes_before_packet,
        artifact_selection=artifact_selection,
        group_upload_bundle_reserved_bytes=GROUP_UPLOAD_BUNDLE_RESERVED_BYTES,
        group_upload_bundle_min_wrong_line_samples_per_run=(
            GROUP_UPLOAD_BUNDLE_MIN_WRONG_LINE_SAMPLES_PER_RUN
        ),
        group_upload_bundle_max_wrong_line_samples_per_run=(
            GROUP_UPLOAD_BUNDLE_MAX_WRONG_LINE_SAMPLES_PER_RUN
        ),
        timestamp_now=_timestamp_now,
    )


def _upload_bundle_optional_artifact_status(*, path: Path | None, enabled: bool) -> str:
    return _upload_bundle_optional_artifact_status_impl(path=path, enabled=enabled)


def _upload_bundle_relative_path_within_root(
    *,
    source_root: Path,
    candidate: Path | None,
) -> str | None:
    return _upload_bundle_relative_path_within_root_impl(
        source_root=source_root,
        candidate=candidate,
    )


def _upload_bundle_derived_run_artifact_path(*, output_subdir: str, file_name: str) -> str:
    return _upload_bundle_derived_run_artifact_path_impl(
        output_subdir=output_subdir,
        file_name=file_name,
        upload_bundle_derived_dir_name=UPLOAD_BUNDLE_DERIVED_DIR_NAME,
    )


def _upload_bundle_build_knowledge_summary(
    *,
    source_root: Path,
    discovered_run_dirs: list[Path],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return _upload_bundle_build_knowledge_summary_impl(
        source_root=source_root,
        discovered_run_dirs=discovered_run_dirs,
        upload_bundle_derived_dir_name=UPLOAD_BUNDLE_DERIVED_DIR_NAME,
    )


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


from cookimport.bench.external_ai_cutdown.stage_reports import (
    _upload_bundle_blocks_from_evidence_rows as _upload_bundle_blocks_from_evidence_rows_impl,
    _upload_bundle_build_per_label_metrics as _upload_bundle_build_per_label_metrics_impl,
    _upload_bundle_collect_confusion_delta_counts as _upload_bundle_collect_confusion_delta_counts_impl,
    _upload_bundle_collect_stage_per_label_metrics as _upload_bundle_collect_stage_per_label_metrics_impl,
    _upload_bundle_collect_stage_reports_for_run as _upload_bundle_collect_stage_reports_for_run_impl,
    _upload_bundle_collect_text_matches as _upload_bundle_collect_text_matches_impl,
    _upload_bundle_extract_text_values as _upload_bundle_extract_text_values_impl,
    _upload_bundle_load_gold_line_labels_from_eval_report as _upload_bundle_load_gold_line_labels_from_eval_report_impl,
    _upload_bundle_load_run_per_label_metrics as _upload_bundle_load_run_per_label_metrics_impl,
    _upload_bundle_normalize_match_text as _upload_bundle_normalize_match_text_impl,
    _upload_bundle_pick_title_block as _upload_bundle_pick_title_block_impl,
    _upload_bundle_project_correction_recipe_labels as _upload_bundle_project_correction_recipe_labels_impl,
    _upload_bundle_project_final_recipe_labels as _upload_bundle_project_final_recipe_labels_impl,
    _upload_bundle_resolve_gold_spans_path as _upload_bundle_resolve_gold_spans_path_impl,
    _upload_bundle_resolve_manifest_path as _upload_bundle_resolve_manifest_path_impl,
)


def _upload_bundle_collect_confusion_delta_counts(*args, **kwargs):
    return _upload_bundle_collect_confusion_delta_counts_impl(*args, **kwargs)


def _upload_bundle_load_run_per_label_metrics(*args, **kwargs):
    return _upload_bundle_load_run_per_label_metrics_impl(*args, **kwargs)


def _upload_bundle_resolve_manifest_path(*args, **kwargs):
    return _upload_bundle_resolve_manifest_path_impl(*args, **kwargs)


def _upload_bundle_resolve_gold_spans_path(*args, **kwargs):
    return _upload_bundle_resolve_gold_spans_path_impl(*args, **kwargs)


def _upload_bundle_load_gold_line_labels_from_eval_report(*args, **kwargs):
    return _upload_bundle_load_gold_line_labels_from_eval_report_impl(*args, **kwargs)


def _upload_bundle_normalize_match_text(*args, **kwargs):
    return _upload_bundle_normalize_match_text_impl(*args, **kwargs)


def _upload_bundle_extract_text_values(*args, **kwargs):
    return _upload_bundle_extract_text_values_impl(*args, **kwargs)


def _upload_bundle_blocks_from_evidence_rows(*args, **kwargs):
    return _upload_bundle_blocks_from_evidence_rows_impl(*args, **kwargs)


def _upload_bundle_collect_text_matches(*args, **kwargs):
    return _upload_bundle_collect_text_matches_impl(*args, **kwargs)


def _upload_bundle_pick_title_block(*args, **kwargs):
    return _upload_bundle_pick_title_block_impl(*args, **kwargs)


def _upload_bundle_project_correction_recipe_labels(*args, **kwargs):
    return _upload_bundle_project_correction_recipe_labels_impl(*args, **kwargs)


def _upload_bundle_project_final_recipe_labels(*args, **kwargs):
    return _upload_bundle_project_final_recipe_labels_impl(*args, **kwargs)


def _upload_bundle_collect_stage_reports_for_run(*args, **kwargs):
    return _upload_bundle_collect_stage_reports_for_run_impl(*args, **kwargs)


def _upload_bundle_collect_stage_per_label_metrics(*args, **kwargs):
    return _upload_bundle_collect_stage_per_label_metrics_impl(*args, **kwargs)


def _upload_bundle_build_per_label_metrics(*args, **kwargs):
    return _upload_bundle_build_per_label_metrics_impl(*args, **kwargs)


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


from cookimport.bench.external_ai_cutdown.runtime_inventory import (
    _upload_bundle_build_call_runtime_inventory as _upload_bundle_build_call_runtime_inventory_impl,
    _upload_bundle_build_call_runtime_inventory_from_prediction_manifest as _upload_bundle_build_call_runtime_inventory_from_prediction_manifest_impl,
    _upload_bundle_build_line_role_escalation_summary as _upload_bundle_build_line_role_escalation_summary_impl,
    _upload_bundle_call_inventory_stage_included as _upload_bundle_call_inventory_stage_included_impl,
    _upload_bundle_call_inventory_stage_rank as _upload_bundle_call_inventory_stage_rank_impl,
    _upload_bundle_collect_call_runtime_map as _upload_bundle_collect_call_runtime_map_impl,
    _upload_bundle_estimate_call_cost_usd as _upload_bundle_estimate_call_cost_usd_impl,
    _upload_bundle_extract_call_runtime as _upload_bundle_extract_call_runtime_impl,
    _upload_bundle_iter_unique_run_dirs as _upload_bundle_iter_unique_run_dirs_impl,
    _upload_bundle_load_prompt_budget_summary as _upload_bundle_load_prompt_budget_summary_impl,
    _upload_bundle_merge_runtime_inventory_with_fallback as _upload_bundle_merge_runtime_inventory_with_fallback_impl,
    _upload_bundle_merge_runtime_stage_summary as _upload_bundle_merge_runtime_stage_summary_impl,
    _upload_bundle_nested_numeric as _upload_bundle_nested_numeric_impl,
    _upload_bundle_normalize_runtime_stage_key as _upload_bundle_normalize_runtime_stage_key_impl,
    _upload_bundle_quantile as _upload_bundle_quantile_impl,
    _upload_bundle_runtime_inventory_needs_fallback as _upload_bundle_runtime_inventory_needs_fallback_impl,
    _upload_bundle_stage_total_duration_ms as _upload_bundle_stage_total_duration_ms_impl,
    _upload_bundle_telemetry_call_count as _upload_bundle_telemetry_call_count_impl,
    _upload_bundle_token_share_fields as _upload_bundle_token_share_fields_impl,
)


def _upload_bundle_nested_numeric(*args, **kwargs):
    return _upload_bundle_nested_numeric_impl(*args, **kwargs)


def _upload_bundle_call_inventory_stage_included(*args, **kwargs):
    return _upload_bundle_call_inventory_stage_included_impl(*args, **kwargs)


def _upload_bundle_call_inventory_stage_rank(*args, **kwargs):
    return _upload_bundle_call_inventory_stage_rank_impl(*args, **kwargs)


def _upload_bundle_extract_call_runtime(*args, **kwargs):
    return _upload_bundle_extract_call_runtime_impl(*args, **kwargs)


def _upload_bundle_estimate_call_cost_usd(*args, **kwargs):
    return _upload_bundle_estimate_call_cost_usd_impl(*args, **kwargs)


def _upload_bundle_iter_unique_run_dirs(*args, **kwargs):
    return _upload_bundle_iter_unique_run_dirs_impl(*args, **kwargs)


def _upload_bundle_normalize_runtime_stage_key(*args, **kwargs):
    return _upload_bundle_normalize_runtime_stage_key_impl(*args, **kwargs)


def _upload_bundle_collect_call_runtime_map(*args, **kwargs):
    return _upload_bundle_collect_call_runtime_map_impl(*args, **kwargs)


def _upload_bundle_telemetry_call_count(*args, **kwargs):
    return _upload_bundle_telemetry_call_count_impl(*args, **kwargs)


def _upload_bundle_token_share_fields(*args, **kwargs):
    return _upload_bundle_token_share_fields_impl(*args, **kwargs)


def _upload_bundle_load_prompt_budget_summary(*args, **kwargs):
    return _upload_bundle_load_prompt_budget_summary_impl(*args, **kwargs)


def _upload_bundle_build_call_runtime_inventory_from_prediction_manifest(*args, **kwargs):
    return _upload_bundle_build_call_runtime_inventory_from_prediction_manifest_impl(*args, **kwargs)


def _upload_bundle_runtime_inventory_needs_fallback(*args, **kwargs):
    return _upload_bundle_runtime_inventory_needs_fallback_impl(*args, **kwargs)


def _upload_bundle_stage_total_duration_ms(*args, **kwargs):
    return _upload_bundle_stage_total_duration_ms_impl(*args, **kwargs)


def _upload_bundle_merge_runtime_stage_summary(*args, **kwargs):
    return _upload_bundle_merge_runtime_stage_summary_impl(*args, **kwargs)


def _upload_bundle_merge_runtime_inventory_with_fallback(*args, **kwargs):
    return _upload_bundle_merge_runtime_inventory_with_fallback_impl(*args, **kwargs)


def _upload_bundle_build_call_runtime_inventory(*args, **kwargs):
    return _upload_bundle_build_call_runtime_inventory_impl(*args, **kwargs)


def _upload_bundle_quantile(*args, **kwargs):
    return _upload_bundle_quantile_impl(*args, **kwargs)


def _upload_bundle_build_line_role_escalation_summary(*args, **kwargs):
    return _upload_bundle_build_line_role_escalation_summary_impl(*args, **kwargs)


from cookimport.bench.external_ai_cutdown.regression_sampling import (
    _upload_bundle_build_changed_line_stratified_sample as _upload_bundle_build_changed_line_stratified_sample_impl,
    _upload_bundle_build_regression_casebook as _upload_bundle_build_regression_casebook_impl,
    _upload_bundle_build_triage_packet_rows as _upload_bundle_build_triage_packet_rows_impl,
    _upload_bundle_changed_line_bucket as _upload_bundle_changed_line_bucket_impl,
    _upload_bundle_derive_run_diagnostic_statuses as _upload_bundle_derive_run_diagnostic_statuses_impl,
    _upload_bundle_matches_recipe_target as _upload_bundle_matches_recipe_target_impl,
    _upload_bundle_regression_casebook_signal_key as _upload_bundle_regression_casebook_signal_key_impl,
    _upload_bundle_safe_run_subdir as _upload_bundle_safe_run_subdir_impl,
    _upload_bundle_select_triage_packet_sample_rows as _upload_bundle_select_triage_packet_sample_rows_impl,
    _upload_bundle_sort_recipe_triage_rows as _upload_bundle_sort_recipe_triage_rows_impl,
    _upload_bundle_triage_packet_row_has_signal as _upload_bundle_triage_packet_row_has_signal_impl,
)


def _upload_bundle_safe_run_subdir(*args, **kwargs):
    return _upload_bundle_safe_run_subdir_impl(*args, **kwargs)


def _upload_bundle_derive_run_diagnostic_statuses(*args, **kwargs):
    return _upload_bundle_derive_run_diagnostic_statuses_impl(*args, **kwargs)


def _upload_bundle_matches_recipe_target(*args, **kwargs):
    return _upload_bundle_matches_recipe_target_impl(*args, **kwargs)


def _upload_bundle_regression_casebook_signal_key(*args, **kwargs):
    return _upload_bundle_regression_casebook_signal_key_impl(*args, **kwargs)


def _upload_bundle_build_regression_casebook(*args, **kwargs):
    return _upload_bundle_build_regression_casebook_impl(*args, **kwargs)


def _upload_bundle_changed_line_bucket(*args, **kwargs):
    return _upload_bundle_changed_line_bucket_impl(*args, **kwargs)


def _upload_bundle_build_changed_line_stratified_sample(*args, **kwargs):
    return _upload_bundle_build_changed_line_stratified_sample_impl(*args, **kwargs)


def _upload_bundle_sort_recipe_triage_rows(*args, **kwargs):
    return _upload_bundle_sort_recipe_triage_rows_impl(*args, **kwargs)


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


def _upload_bundle_build_triage_packet_rows(*args, **kwargs):
    return _upload_bundle_build_triage_packet_rows_impl(*args, **kwargs)


def _upload_bundle_triage_packet_row_has_signal(*args, **kwargs):
    return _upload_bundle_triage_packet_row_has_signal_impl(*args, **kwargs)


def _upload_bundle_select_triage_packet_sample_rows(*args, **kwargs):
    return _upload_bundle_select_triage_packet_sample_rows_impl(*args, **kwargs)


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
                    "benchmark_comparison.json",
                    "codex_vs_vanilla_comparison.json",
                    derived_root_paths["comparison_summary_json"],
                ),
                basenames=(
                    "comparison_summary.json",
                    "benchmark_comparison.json",
                    "codex_vs_vanilla_comparison.json",
                ),
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
                "benchmark_comparison.json",
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
    bundle_target = oracle_upload_contract.OracleBenchmarkBundleTarget(
        requested_path=output_root,
        source_root=source_root,
        bundle_dir=output_root,
        scope=oracle_upload_contract._infer_bundle_scope(source_root),
    )

    def _review_packet_dir(review_profile: str) -> Path:
        return output_root / review_profile

    def _compact_turn1_value(
        value: Any,
        *,
        item_limit: int = ORACLE_REVIEW_PACKET_COMPACT_LIST_LIMIT,
        excerpt_limit: int = ORACLE_REVIEW_PACKET_COMPACT_EXCERPT_LIMIT,
        max_depth: int = 5,
    ) -> Any:
        if max_depth <= 0:
            return "<clipped>"
        if isinstance(value, str):
            return _excerpt(value, max_len=excerpt_limit)
        if isinstance(value, list):
            clipped_items = [
                _compact_turn1_value(
                    item,
                    item_limit=item_limit,
                    excerpt_limit=excerpt_limit,
                    max_depth=max_depth - 1,
                )
                for item in value[:item_limit]
            ]
            if len(value) > item_limit:
                clipped_items.append(
                    f"<{len(value) - item_limit} additional items omitted>"
                )
            return clipped_items
        if isinstance(value, dict):
            clipped: dict[str, Any] = {}
            items = list(value.items())
            for key, item in items[:item_limit]:
                clipped[str(key)] = _compact_turn1_value(
                    item,
                    item_limit=item_limit,
                    excerpt_limit=excerpt_limit,
                    max_depth=max_depth - 1,
                )
            if len(items) > item_limit:
                clipped["_omitted_key_count"] = len(items) - item_limit
            return clipped
        return value

    def _take_lines_to_byte_limit(lines: list[str], *, max_bytes: int) -> tuple[list[str], bool]:
        selected: list[str] = []
        total_bytes = 0
        clipped = False
        for line in lines:
            line_bytes = len((line + "\n").encode("utf-8"))
            if selected and total_bytes + line_bytes > max_bytes:
                clipped = True
                break
            if not selected and line_bytes > max_bytes:
                selected.append(_excerpt(line, max_len=max_bytes))
                clipped = True
                total_bytes = max_bytes
                break
            selected.append(line)
            total_bytes += line_bytes
        return selected, clipped

    def _build_prompt_sample_digest(text: str) -> str:
        if not text.strip():
            return "# Prompt Digest\n\nPrompt samples were unavailable.\n"
        lines = text.splitlines()
        first_section_index = next(
            (index for index, line in enumerate(lines) if line.startswith("## ")),
            len(lines),
        )
        preamble_lines, preamble_clipped = _take_lines_to_byte_limit(
            lines[:first_section_index],
            max_bytes=ORACLE_REVIEW_PACKET_PROMPT_SECTION_BYTES,
        )
        section_chunks: list[tuple[str, list[str], bool]] = []
        current_heading = ""
        current_lines: list[str] = []
        for line in lines[first_section_index:]:
            if line.startswith("## "):
                if current_heading:
                    selected_lines, clipped = _take_lines_to_byte_limit(
                        current_lines,
                        max_bytes=ORACLE_REVIEW_PACKET_PROMPT_SECTION_BYTES,
                    )
                    section_chunks.append((current_heading, selected_lines, clipped))
                current_heading = line
                current_lines = []
                continue
            current_lines.append(line)
        if current_heading:
            selected_lines, clipped = _take_lines_to_byte_limit(
                current_lines,
                max_bytes=ORACLE_REVIEW_PACKET_PROMPT_SECTION_BYTES,
            )
            section_chunks.append((current_heading, selected_lines, clipped))

        digest_lines: list[str] = ["# Prompt Digest", ""]
        digest_lines.extend(preamble_lines)
        if preamble_lines and digest_lines[-1] != "":
            digest_lines.append("")
        if preamble_clipped:
            digest_lines.append("_Preamble clipped for Oracle turn 1._")
            digest_lines.append("")
        selected_sections = section_chunks[:ORACLE_REVIEW_PACKET_PROMPT_SECTION_LIMIT]
        for heading, section_lines, clipped in selected_sections:
            digest_lines.append(heading)
            digest_lines.append("")
            digest_lines.extend(section_lines)
            if section_lines and section_lines[-1] != "":
                digest_lines.append("")
            if clipped:
                digest_lines.append("_Section clipped for Oracle turn 1._")
                digest_lines.append("")
        if len(section_chunks) > ORACLE_REVIEW_PACKET_PROMPT_SECTION_LIMIT:
            omitted = len(section_chunks) - ORACLE_REVIEW_PACKET_PROMPT_SECTION_LIMIT
            digest_lines.extend(
                [
                    f"_Omitted {omitted} additional prompt sections for Oracle turn 1._",
                    "",
                ]
            )

        digest_text = "\n".join(digest_lines).strip() + "\n"
        if len(digest_text.encode("utf-8")) <= ORACLE_REVIEW_PACKET_PROMPT_TOTAL_BYTES:
            return digest_text
        return (
            _excerpt(digest_text, max_len=ORACLE_REVIEW_PACKET_PROMPT_TOTAL_BYTES)
            + "\n"
        )

    def _eval_report_top_per_label_rows(value: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if isinstance(value, dict):
            for label, payload in value.items():
                if not isinstance(payload, dict):
                    continue
                row = {"label": str(label)}
                row.update(payload)
                rows.append(row)
        elif isinstance(value, list):
            rows = [dict(item) for item in value if isinstance(item, dict)]
        rows.sort(
            key=lambda row: (
                _coerce_float(row.get("f1")) if _coerce_float(row.get("f1")) is not None else 1.0,
                _coerce_float(row.get("recall"))
                if _coerce_float(row.get("recall")) is not None
                else 1.0,
                -int(_coerce_int(row.get("gold_total")) or _coerce_int(row.get("line_total")) or 0),
                str(row.get("label") or ""),
            )
        )
        compact_rows: list[dict[str, Any]] = []
        for row in rows[:ORACLE_REVIEW_PACKET_COMPACT_LIST_LIMIT]:
            compact_rows.append(
                {
                    "label": str(row.get("label") or ""),
                    "f1": _coerce_float(row.get("f1")),
                    "precision": _coerce_float(row.get("precision")),
                    "recall": _coerce_float(row.get("recall")),
                    "gold_total": _coerce_int(row.get("gold_total") or row.get("line_total")),
                    "pred_total": _coerce_int(
                        row.get("pred_total") or row.get("predicted_total")
                    ),
                    "wrong_total": _coerce_int(
                        row.get("wrong_total") or row.get("wrong_count")
                    ),
                }
            )
        return compact_rows

    def _build_eval_report_digest(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "oracle_turn1_eval_report_digest.v1",
            "source_schema_version": str(payload.get("schema_version") or ""),
            "eval_mode": str(payload.get("eval_mode") or ""),
            "eval_type": str(payload.get("eval_type") or ""),
            "unit": str(payload.get("unit") or ""),
            "strict_accuracy": _coerce_float(payload.get("strict_accuracy")),
            "overall_line_accuracy": _coerce_float(payload.get("overall_line_accuracy")),
            "overall_block_accuracy": _coerce_float(payload.get("overall_block_accuracy")),
            "macro_f1_excluding_other": _coerce_float(
                payload.get("macro_f1_excluding_other")
            ),
            "worst_label_recall": _coerce_float(payload.get("worst_label_recall")),
            "counts": _compact_turn1_value(payload.get("counts")),
            "boundary": _compact_turn1_value(payload.get("boundary")),
            "authority_coverage": _compact_turn1_value(
                payload.get("authority_coverage")
            ),
            "top_per_label_rows": _eval_report_top_per_label_rows(
                payload.get("per_label")
            ),
            "confusion_excerpt": _compact_turn1_value(payload.get("confusion")),
        }

    def _compact_payload_jsonl_rows(rows: list[Any]) -> list[Any]:
        sample_rows = rows
        if len(rows) > ORACLE_REVIEW_PACKET_COMPACT_LIST_LIMIT:
            sample_rows = _sample_rows_evenly(
                [row for row in rows if isinstance(row, dict)],
                ORACLE_REVIEW_PACKET_COMPACT_LIST_LIMIT,
            )
            if not sample_rows:
                sample_rows = rows[:ORACLE_REVIEW_PACKET_COMPACT_LIST_LIMIT]
        compact_rows: list[Any] = []
        for row in sample_rows:
            if isinstance(row, dict):
                compact_rows.append(
                    _clip_large_text_fields(
                        _compact_turn1_value(row),
                        excerpt_limit=ORACLE_REVIEW_PACKET_COMPACT_EXCERPT_LIMIT,
                    )
                )
            else:
                compact_rows.append(
                    _compact_turn1_value(
                        row,
                        excerpt_limit=ORACLE_REVIEW_PACKET_COMPACT_EXCERPT_LIMIT,
                    )
                )
        return compact_rows

    def _compact_review_payload_row(row: dict[str, Any]) -> dict[str, Any]:
        row_copy = dict(row)
        logical_path = str(row_copy.get("path") or "")
        source_bytes = int(_coerce_int(row_copy.get("bytes")) or 0)
        summary_only = False
        policy = ""

        if logical_path.endswith("prompts/prompt_type_samples_from_full_prompt_log.md"):
            content_text = row_copy.get("content_text")
            if isinstance(content_text, str):
                row_copy["content_text"] = _build_prompt_sample_digest(content_text)
                summary_only = True
                policy = "prompt_digest"
        elif logical_path.endswith("eval_report.json"):
            content_json = row_copy.get("content_json")
            if isinstance(content_json, dict):
                row_copy["content_json"] = _build_eval_report_digest(content_json)
                summary_only = True
                policy = "eval_report_digest"

        rendered_bytes = _upload_bundle_payload_row_line_bytes(row_copy)
        if rendered_bytes > ORACLE_REVIEW_PACKET_MAX_ROW_BYTES:
            if isinstance(row_copy.get("content_jsonl_rows"), list):
                original_rows = list(row_copy.get("content_jsonl_rows") or [])
                row_copy["content_jsonl_rows"] = _compact_payload_jsonl_rows(original_rows)
                row_copy["oracle_turn1_source_row_count"] = len(original_rows)
                summary_only = True
                policy = policy or "sampled_jsonl"
            elif isinstance(row_copy.get("content_json"), (dict, list)):
                row_copy["content_json"] = _compact_turn1_value(row_copy.get("content_json"))
                summary_only = True
                policy = policy or "compact_json"
            elif isinstance(row_copy.get("content_text"), str):
                row_copy["content_text"] = _excerpt(
                    str(row_copy.get("content_text") or ""),
                    max_len=ORACLE_REVIEW_PACKET_PROMPT_TOTAL_BYTES,
                )
                summary_only = True
                policy = policy or "clipped_text"
            rendered_bytes = _upload_bundle_payload_row_line_bytes(row_copy)

        if summary_only:
            row_copy["oracle_turn1_summary_only"] = True
            row_copy["oracle_turn1_policy"] = policy
            row_copy["oracle_turn1_source_bytes"] = source_bytes
            row_copy["oracle_turn1_rendered_bytes"] = int(rendered_bytes)
        return row_copy

    def _compact_bucket_rows(value: Any) -> list[dict[str, Any]]:
        rows = value if isinstance(value, list) else []
        compact_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            compact_rows.append(
                {
                    "bucket": str(row.get("bucket") or ""),
                    "new_error_count": int(_coerce_int(row.get("new_error_count")) or 0),
                    "fixed_error_count": int(_coerce_int(row.get("fixed_error_count")) or 0),
                    "net_error_count": int(_coerce_int(row.get("net_error_count")) or 0),
                    "share_of_new_errors": _coerce_float(
                        row.get("share_of_new_errors")
                    ),
                    "share_of_fixed_errors": _coerce_float(
                        row.get("share_of_fixed_errors")
                    ),
                    "share_of_net_error": _coerce_float(row.get("share_of_net_error")),
                }
            )
        return compact_rows

    def _compact_triage_packet_summary(value: Any) -> dict[str, Any]:
        payload = value if isinstance(value, dict) else {}
        sample_rows = payload.get("sample_rows") if isinstance(payload.get("sample_rows"), list) else []
        return {
            "schema_version": str(payload.get("schema_version") or ""),
            "row_count": int(_coerce_int(payload.get("row_count")) or 0),
            "signal_row_count": int(_coerce_int(payload.get("signal_row_count")) or 0),
            "sample_rows_note": str(payload.get("sample_rows_note") or ""),
            "empty_packet_note": str(payload.get("empty_packet_note") or ""),
            "sample_rows": [
                _clip_large_text_fields(
                    _compact_turn1_value(row),
                    excerpt_limit=ORACLE_REVIEW_PACKET_COMPACT_EXCERPT_LIMIT,
                )
                for row in sample_rows[:ORACLE_REVIEW_PACKET_COMPACT_LIST_LIMIT]
                if isinstance(row, dict)
            ],
        }

    def _compact_config_version_metadata(value: Any) -> dict[str, Any]:
        payload = value if isinstance(value, dict) else {}
        compact_runs: list[dict[str, Any]] = []
        for row in payload.get("runs") if isinstance(payload.get("runs"), list) else []:
            if not isinstance(row, dict):
                continue
            compact_runs.append(
                {
                    "run_id": str(row.get("run_id") or ""),
                    "llm_recipe_pipeline": str(row.get("llm_recipe_pipeline") or ""),
                    "line_role_pipeline": str(row.get("line_role_pipeline") or ""),
                    "atomic_block_splitter": str(row.get("atomic_block_splitter") or ""),
                    "eval_mode": str(row.get("eval_mode") or ""),
                }
            )
        return {
            "schema_version": str(payload.get("schema_version") or ""),
            "pair_comparability": _compact_turn1_value(payload.get("pair_comparability")),
            "runs": compact_runs,
        }

    def _compact_structure_label_report(value: Any) -> dict[str, Any]:
        payload = value if isinstance(value, dict) else {}
        return {
            "schema_version": str(payload.get("schema_version") or ""),
            "boundary": _compact_turn1_value(payload.get("boundary")),
            "slices": _compact_turn1_value(payload.get("slices")),
        }

    def _compact_runtime_inventory(value: Any) -> dict[str, Any]:
        payload = value if isinstance(value, dict) else {}
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        by_stage = summary.get("by_stage") if isinstance(summary.get("by_stage"), dict) else {}
        compact_stages: list[dict[str, Any]] = []
        for stage_key, stage_payload in by_stage.items():
            if not isinstance(stage_payload, dict):
                continue
            compact_stages.append(
                {
                    "stage_key": str(stage_key),
                    "total_tokens": int(_coerce_int(stage_payload.get("total_tokens")) or 0),
                    "call_count": int(_coerce_int(stage_payload.get("call_count")) or 0),
                    "duration_total_ms": int(
                        _coerce_int(stage_payload.get("duration_total_ms")) or 0
                    ),
                    "token_share": _coerce_float(stage_payload.get("token_share")),
                    "runtime_share": _coerce_float(stage_payload.get("runtime_share")),
                }
            )
        compact_stages.sort(
            key=lambda row: (-int(row.get("total_tokens") or 0), str(row.get("stage_key") or ""))
        )
        compact_summary = dict(summary)
        compact_summary["by_stage"] = compact_stages[:ORACLE_REVIEW_PACKET_COMPACT_LIST_LIMIT]
        return {"summary": compact_summary}

    def _compact_line_role_escalation(value: Any) -> dict[str, Any]:
        payload = value if isinstance(value, dict) else {}
        return {
            "schema_version": str(payload.get("schema_version") or ""),
            "summary": _compact_turn1_value(payload.get("summary")),
            "selective_escalation_signal": _compact_turn1_value(
                payload.get("selective_escalation_signal")
            ),
        }

    def _compact_top_confusions(value: Any) -> list[dict[str, Any]]:
        rows = value if isinstance(value, list) else []
        compact_rows: list[dict[str, Any]] = []
        for row in rows[:ORACLE_REVIEW_PACKET_COMPACT_LIST_LIMIT]:
            if not isinstance(row, dict):
                continue
            compact_rows.append(
                {
                    "gold_label": str(row.get("gold_label") or ""),
                    "pred_label": str(row.get("pred_label") or ""),
                    "delta_count": int(_coerce_int(row.get("delta_count")) or 0),
                    "codex_count": int(_coerce_int(row.get("codex_count")) or 0),
                    "baseline_count": int(_coerce_int(row.get("baseline_count")) or 0),
                }
            )
        return compact_rows

    def _compact_prompt_budget_highlights() -> dict[str, Any]:
        prompt_budget_row = payload_row_by_path.get("codex-exec/prompt_budget_summary.json")
        prompt_budget_payload = (
            prompt_budget_row.get("content_json")
            if isinstance(prompt_budget_row, dict)
            and isinstance(prompt_budget_row.get("content_json"), dict)
            else {}
        )
        by_stage = (
            prompt_budget_payload.get("by_stage")
            if isinstance(prompt_budget_payload.get("by_stage"), dict)
            else {}
        )
        stage_rows: list[dict[str, Any]] = []
        for stage_key, stage_payload in by_stage.items():
            if not isinstance(stage_payload, dict):
                continue
            stage_rows.append(
                {
                    "stage_key": str(stage_key),
                    "tokens_total": int(_coerce_int(stage_payload.get("tokens_total")) or 0),
                    "call_count": int(_coerce_int(stage_payload.get("call_count")) or 0),
                    "wrapper_overhead_tokens": int(
                        _coerce_int(stage_payload.get("wrapper_overhead_tokens"))
                        or _coerce_int(stage_payload.get("protocol_overhead_tokens_total"))
                        or 0
                    ),
                    "protocol_overhead_share": _coerce_float(
                        stage_payload.get("protocol_overhead_share")
                    ),
                }
            )
        stage_rows.sort(
            key=lambda row: (-int(row.get("tokens_total") or 0), str(row.get("stage_key") or ""))
        )
        return {
            "schema_version": "oracle_turn1_prompt_budget_highlights.v1",
            "stage_rows": stage_rows[:ORACLE_REVIEW_PACKET_COMPACT_LIST_LIMIT],
        }

    def _selected_payload_row_summaries(
        selected_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for row in selected_rows:
            if not isinstance(row, dict):
                continue
            summaries.append(
                {
                    "path": str(row.get("path") or ""),
                    "payload_row": int(_coerce_int(row.get("payload_row")) or 0),
                    "content_type": str(row.get("content_type") or ""),
                    "category": str(row.get("category") or ""),
                    "source_bytes": int(_coerce_int(row.get("bytes")) or 0),
                    "summary_only": bool(row.get("oracle_turn1_summary_only")),
                    "turn1_policy": str(row.get("oracle_turn1_policy") or "literal"),
                    "rendered_bytes": int(
                        _coerce_int(row.get("oracle_turn1_rendered_bytes"))
                        or _upload_bundle_payload_row_line_bytes(row)
                    ),
                }
            )
        return summaries

    def _review_packet_analysis_payload(
        review_profile: oracle_upload_contract.OracleBenchmarkReviewProfile,
    ) -> dict[str, Any]:
        analysis_payload = (
            index_payload.get("analysis") if isinstance(index_payload.get("analysis"), dict) else {}
        )
        compact_analysis = {
            "turn1_summary": analysis_payload.get("turn1_summary") or {},
            "benchmark_pair_inventory": {
                "pair_count": int(
                    _coerce_int(
                        ((analysis_payload.get("benchmark_pair_inventory") or {}).get("pair_count"))
                    )
                    or 0
                ),
                "delta_summary": _compact_turn1_value(
                    ((analysis_payload.get("benchmark_pair_inventory") or {}).get("delta_summary"))
                ),
                "generalization_readiness": _compact_turn1_value(
                    (
                        (analysis_payload.get("benchmark_pair_inventory") or {}).get(
                            "generalization_readiness"
                        )
                    )
                ),
            },
            "active_recipe_span_breakout": analysis_payload.get("active_recipe_span_breakout")
            or {},
            "triage_packet": _compact_triage_packet_summary(
                analysis_payload.get("triage_packet")
            ),
            "net_error_blame_summary": {
                "new_error_lines": int(
                    _coerce_int(
                        (analysis_payload.get("net_error_blame_summary") or {}).get(
                            "new_error_lines"
                        )
                    )
                    or 0
                ),
                "fixed_error_lines": int(
                    _coerce_int(
                        (analysis_payload.get("net_error_blame_summary") or {}).get(
                            "fixed_error_lines"
                        )
                    )
                    or 0
                ),
                "net_error_delta_lines": int(
                    _coerce_int(
                        (analysis_payload.get("net_error_blame_summary") or {}).get(
                            "net_error_delta_lines"
                        )
                    )
                    or 0
                ),
                "share_semantics": _compact_turn1_value(
                    (analysis_payload.get("net_error_blame_summary") or {}).get(
                        "share_semantics"
                    )
                ),
                "bucket_rows": _compact_bucket_rows(
                    (analysis_payload.get("net_error_blame_summary") or {}).get(
                        "bucket_rows"
                    )
                ),
            },
            "config_version_metadata": _compact_config_version_metadata(
                analysis_payload.get("config_version_metadata")
            ),
            "recipe_pipeline_context": analysis_payload.get("recipe_pipeline_context") or {},
            "stage_observability_summary": analysis_payload.get("stage_observability_summary")
            or {},
            "structure_label_report": _compact_structure_label_report(
                analysis_payload.get("structure_label_report")
            ),
            "top_confusion_deltas": _compact_top_confusions(
                analysis_payload.get("top_confusion_deltas")
            ),
            "group_high_level": analysis_payload.get("group_high_level") or {},
            "call_inventory_runtime": _compact_runtime_inventory(
                analysis_payload.get("call_inventory_runtime")
            ),
            "line_role_escalation": _compact_line_role_escalation(
                analysis_payload.get("line_role_escalation")
            ),
        }
        if review_profile.profile_id == oracle_upload_contract.ORACLE_REVIEW_PROFILE_TOKEN:
            compact_analysis["prompt_budget_highlights"] = _compact_prompt_budget_highlights()
        return compact_analysis

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
            row_copy = _compact_review_payload_row(payload_row)
            row_copy["payload_row"] = int(artifact_row_lookup.get(logical_path) or 0)
            selected_rows.append(row_copy)
        return selected_rows, missing_paths

    def _review_packet_index_payload(
        review_profile: oracle_upload_contract.OracleBenchmarkReviewProfile,
        *,
        selected_rows: list[dict[str, Any]],
        missing_paths: list[str],
    ) -> dict[str, Any]:
        selected_row_summaries = _selected_payload_row_summaries(selected_rows)
        analysis_payload = _review_packet_analysis_payload(review_profile)
        recommended_read_order = (
            analysis_payload.get("turn1_summary", {}).get("recommended_read_order")
            if isinstance(analysis_payload.get("turn1_summary"), dict)
            else []
        )
        lane_index_payload = {
            "schema_version": "upload_bundle.review_index.v1",
            "bundle_version": str(index_payload.get("bundle_version") or "upload_bundle.v1"),
            "generated_at": str(index_payload.get("generated_at") or ""),
            "source_dir": str(source_root),
            "output_dir": str(output_root),
            "review_profile": review_profile.profile_id,
            "review_profile_display_name": review_profile.display_name,
            "bundle_scope": bundle_target.scope,
            "file_contract": {
                "overview_file": UPLOAD_BUNDLE_OVERVIEW_FILE_NAME,
                "artifact_index_file": UPLOAD_BUNDLE_INDEX_FILE_NAME,
                "payload_file": UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
            },
            "topline": _compact_turn1_value(index_payload.get("topline"), item_limit=24),
            "self_check": _compact_turn1_value(index_payload.get("self_check"), item_limit=24),
            "navigation": {
                "start_here": [
                    UPLOAD_BUNDLE_OVERVIEW_FILE_NAME,
                    UPLOAD_BUNDLE_INDEX_FILE_NAME,
                ],
                "recommended_read_order": (
                    list(recommended_read_order)
                    if isinstance(recommended_read_order, list)
                    else []
                ),
                "selected_payload_rows": selected_row_summaries,
                "full_payload_companion": UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
                "followup_policy": (
                    "Turn 1 is intentionally summary-first. Ask for narrow local follow-up "
                    "artifacts instead of requesting the full benchmark tree."
                ),
            },
            "analysis": analysis_payload,
        }
        lane_index_payload["review_packet"] = {
            "schema_version": "upload_bundle.review_packet.v1",
            "packet_policy": "compact_turn1_only",
            "byte_budget_target": ORACLE_REVIEW_PACKET_TARGET_BYTES,
            "review_profile": review_profile.profile_id,
            "review_profile_display_name": review_profile.display_name,
            "review_dir": review_profile.profile_id,
            "overview_file": UPLOAD_BUNDLE_OVERVIEW_FILE_NAME,
            "artifact_index_file": UPLOAD_BUNDLE_INDEX_FILE_NAME,
            "payload_file": UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
            "index_file": UPLOAD_BUNDLE_INDEX_FILE_NAME,
            "selected_paths": list(review_profile.payload_paths),
            "missing_paths": missing_paths,
            "row_count": len(selected_rows),
            "summary_only_row_count": sum(
                1 for row in selected_rows if bool(row.get("oracle_turn1_summary_only"))
            ),
            "full_root_artifact_count": len(payload_rows),
            "selected_payload_rows": selected_row_summaries,
        }
        return lane_index_payload

    def _review_packet_payload_json(
        review_profile: oracle_upload_contract.OracleBenchmarkReviewProfile,
        *,
        selected_rows: list[dict[str, Any]],
        missing_paths: list[str],
    ) -> dict[str, Any]:
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
            "row_count": len(selected_rows),
            "rows": selected_rows,
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
            payload_json = _review_packet_payload_json(
                review_profile,
                selected_rows=selected_rows,
                missing_paths=missing_paths,
            )
            _write_json(review_dir / UPLOAD_BUNDLE_PAYLOAD_FILE_NAME, payload_json)
            payload_size_bytes = int(
                (review_dir / UPLOAD_BUNDLE_PAYLOAD_FILE_NAME).stat().st_size
            )
            lane_index_payload["review_packet"]["payload_size_bytes"] = payload_size_bytes
            lane_index_payload["review_packet"]["estimated_bundle_size_bytes"] = (
                payload_size_bytes
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
            overview_size_bytes = int(
                (review_dir / UPLOAD_BUNDLE_OVERVIEW_FILE_NAME).stat().st_size
            )
            index_size_bytes = int((review_dir / UPLOAD_BUNDLE_INDEX_FILE_NAME).stat().st_size)
            lane_index_payload["review_packet"]["overview_size_bytes"] = overview_size_bytes
            lane_index_payload["review_packet"]["index_size_bytes"] = index_size_bytes
            lane_index_payload["review_packet"]["estimated_bundle_size_bytes"] = (
                payload_size_bytes + overview_size_bytes + index_size_bytes
            )
            _write_json(review_dir / UPLOAD_BUNDLE_INDEX_FILE_NAME, lane_index_payload)
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
    return write_flattened_summary_for_existing_runs_impl(
        output_dir=output_dir,
        timestamp_now=_timestamp_now,
        aggregated_root_summary_md=AGGREGATED_ROOT_SUMMARY_MD,
        starter_pack_dir_name=STARTER_PACK_DIR_NAME,
        starter_pack_readme_file_name=STARTER_PACK_README_FILE_NAME,
        starter_pack_manifest_file_name=STARTER_PACK_MANIFEST_FILE_NAME,
        starter_pack_comparison_mirror_file_name=STARTER_PACK_COMPARISON_MIRROR_FILE_NAME,
        starter_pack_breakdown_mirror_file_name=STARTER_PACK_BREAKDOWN_MIRROR_FILE_NAME,
        load_json=_load_json,
    )


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
