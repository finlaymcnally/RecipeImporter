"""Pydantic v2 models for the stats dashboard.

These models define the shape of ``dashboard_data.json`` consumed by the
static HTML dashboard.  The collectors in ``dashboard_collect.py`` populate
instances of :class:`DashboardData`; the renderer in ``dashboard_render.py``
serialises them to JSON.

Schema version history:
    1 – initial release
    2 – benchmark metadata enrichment (importer/run config)
    3 – stage/import run_config support in stage records
    4 – stage/import run_config warning metadata for stale rows
    5 – benchmark recipe count support (CSV + processed report enrichment)
    6 – explicit run_config_hash/run_config_summary support in CSV + manifests
    7 – explicit EPUB extractor requested/effective/auto-score fields on stage records
    8 – practical benchmark metrics + granularity mismatch fields
    9 – benchmark golden recipe-header count (`gold_recipe_headers`) for recipe-coverage charts
    10 – removed retired EPUB auto-score field from stage records
    11 – explicit benchmark metric fields (`strict_accuracy`, `macro_f1_excluding_other`)
    12 – CodexFarm benchmark token usage fields (`tokens_*`)
    13 – benchmark semantics fields (`benchmark_variant`, `ai_assistance_profile`)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


SCHEMA_VERSION = "13"


class RunCategory(str, Enum):
    stage_import = "stage_import"
    labelstudio_import = "labelstudio_import"
    benchmark_eval = "benchmark_eval"
    benchmark_prediction = "benchmark_prediction"


class StageRecord(BaseModel):
    """One imported source file – corresponds to one CSV row or one
    ``*.excel_import_report.json``."""

    run_timestamp: str | None = None
    run_dir: str | None = None
    file_name: str
    report_path: str | None = None
    artifact_dir: str | None = None
    importer_name: str | None = None
    run_config: dict[str, Any] | None = None
    run_config_hash: str | None = None
    run_config_summary: str | None = None
    run_config_warning: str | None = None
    epub_extractor_requested: str | None = None
    epub_extractor_effective: str | None = None
    run_category: RunCategory = RunCategory.stage_import

    # timing
    total_seconds: float | None = None
    parsing_seconds: float | None = None
    writing_seconds: float | None = None
    ocr_seconds: float | None = None

    # counts
    recipes: int | None = None
    tips: int | None = None
    tip_candidates: int | None = None
    topic_candidates: int | None = None

    # derived (computed only when safe)
    total_units: int | None = None
    per_recipe_seconds: float | None = None
    per_unit_seconds: float | None = None

    # output footprint
    output_files: int | None = None
    output_bytes: int | None = None

    # health
    warnings_count: int | None = None
    errors_count: int | None = None


class BenchmarkLabelMetrics(BaseModel):
    """Per-label precision/recall from an eval_report.json."""

    label: str
    precision: float | None = None
    recall: float | None = None
    gold_total: int | None = None
    pred_total: int | None = None


class BenchmarkRecord(BaseModel):
    """One Label Studio evaluation run, populated from ``eval_report.json``
    (and optionally ``coverage.json`` / ``manifest.json``)."""

    run_timestamp: str | None = None
    artifact_dir: str | None = None
    report_path: str | None = None
    run_category: RunCategory = RunCategory.benchmark_eval

    # Canonical benchmark metrics (explicit contract)
    strict_accuracy: float | None = None
    macro_f1_excluding_other: float | None = None

    # Additional benchmark metrics used by current reporting surfaces.
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    practical_precision: float | None = None
    practical_recall: float | None = None
    practical_f1: float | None = None
    gold_total: int | None = None
    gold_recipe_headers: int | None = None
    pred_total: int | None = None
    gold_matched: int | None = None
    recipes: int | None = None
    tokens_input: int | None = None
    tokens_cached_input: int | None = None
    tokens_output: int | None = None
    tokens_reasoning: int | None = None
    tokens_total: int | None = None

    # supported-labels focused metrics (relaxed overlap)
    supported_precision: float | None = None
    supported_recall: float | None = None
    supported_practical_precision: float | None = None
    supported_practical_recall: float | None = None
    supported_practical_f1: float | None = None
    granularity_mismatch_likely: bool | None = None
    pred_width_p50: float | None = None
    gold_width_p50: float | None = None

    # per-label breakdown
    per_label: list[BenchmarkLabelMetrics] = Field(default_factory=list)

    # boundary classification
    boundary_correct: int | None = None
    boundary_over: int | None = None
    boundary_under: int | None = None
    boundary_partial: int | None = None

    # optional enrichment from coverage.json
    coverage_ratio: float | None = None
    extracted_chars: int | None = None
    chunked_chars: int | None = None

    # optional enrichment from manifest.json
    task_count: int | None = None
    source_file: str | None = None
    importer_name: str | None = None
    run_config: dict[str, Any] | None = None
    run_config_hash: str | None = None
    run_config_summary: str | None = None
    processed_report_path: str | None = None
    benchmark_variant: str | None = None
    ai_assistance_profile: str | None = None


class DashboardSummary(BaseModel):
    """Pre-aggregated totals for the dashboard header."""

    total_stage_records: int = 0
    total_benchmark_records: int = 0
    total_recipes: int = 0
    total_tips: int = 0
    total_runtime_seconds: float | None = None
    latest_stage_timestamp: str | None = None
    latest_benchmark_timestamp: str | None = None


class DashboardData(BaseModel):
    """Top-level container written to ``dashboard_data.json``."""

    schema_version: str = SCHEMA_VERSION
    generated_at: str = ""
    output_root: str = "data/output"
    golden_root: str = "data/golden"
    stage_records: list[StageRecord] = Field(default_factory=list)
    benchmark_records: list[BenchmarkRecord] = Field(default_factory=list)
    summary: DashboardSummary = Field(default_factory=DashboardSummary)
    collector_warnings: list[str] = Field(default_factory=list)
