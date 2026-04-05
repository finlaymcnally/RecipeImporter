"""Tests for the stats-dashboard feature: schema, collectors, renderer."""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from cookimport.analytics.benchmark_semantics import (
    ai_assistance_profile_for_record,
    benchmark_variant_for_record,
    is_official_golden_benchmark_record,
)
from cookimport.analytics.dashboard_schema import (
    BenchmarkLabelMetrics,
    BenchmarkRecord,
    DashboardData,
    DashboardSummary,
    RunCategory,
    StageRecord,
)
from cookimport.analytics.dashboard_collect import collect_dashboard_data
from cookimport.analytics.dashboard_render import render_dashboard
from cookimport.analytics.perf_report import (
    append_benchmark_csv,
    append_history_csv,
    backfill_benchmark_history_csv,
    history_path,
    _CSV_FIELDS,
)
from cookimport.paths import history_csv_for_output


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sample_csv_row(values: dict[str, str]) -> str:
    row = {field: "" for field in _CSV_FIELDS}
    row.update(values)
    return ",".join(str(row[field]) for field in _CSV_FIELDS)


SAMPLE_CSV_HEADER = ",".join(_CSV_FIELDS)

SAMPLE_CSV_ROW1 = _sample_csv_row(
    {
        "run_timestamp": "2026-02-10T10:00:00",
        "run_dir": "data/output/2026-02-10_10.00.00",
        "file_name": "cookbook_a.xlsx",
        "report_path": "data/output/2026-02-10_10.00.00/cookbook_a.excel_import_report.json",
        "total_seconds": "5.5",
        "parsing_seconds": "1.2",
        "writing_seconds": "3.8",
        "ocr_seconds": "0.0",
        "recipes": "20",
        "standalone_blocks": "5",
        "total_units": "30",
        "per_recipe_seconds": "0.275",
        "per_unit_seconds": "0.183",
        "output_files": "10",
        "output_bytes": "50000",
        "dominant_stage": "writing",
        "dominant_stage_seconds": "3.8",
        "dominant_checkpoint": "write_final_seconds",
        "dominant_checkpoint_seconds": "3.5",
        "run_category": "stage_import",
    }
)

SAMPLE_CSV_ROW2 = _sample_csv_row(
    {
        "run_timestamp": "2026-02-11T14:30:00",
        "run_dir": "data/output/2026-02-11_14.30.00",
        "file_name": "cookbook_b.epub",
        "report_path": "data/output/2026-02-11_14.30.00/cookbook_b.excel_import_report.json",
        "importer_name": "epub",
        "total_seconds": "12.3",
        "parsing_seconds": "4.5",
        "writing_seconds": "6.1",
        "ocr_seconds": "1.7",
        "recipes": "50",
        "standalone_blocks": "12",
        "total_units": "73",
        "per_recipe_seconds": "0.246",
        "per_unit_seconds": "0.168",
        "output_files": "25",
        "output_bytes": "120000",
        "dominant_stage": "writing",
        "dominant_stage_seconds": "6.1",
        "dominant_checkpoint": "write_final_seconds",
        "dominant_checkpoint_seconds": "5.8",
        "run_category": "stage_import",
    }
)

SAMPLE_CSV_BENCH_ROW = _sample_csv_row(
    {
        "run_timestamp": "2026-02-11T16:00:00",
        "run_dir": "data/golden/eval-vs-pipeline/2026-02-11_16.00.00",
        "file_name": "my_book.pdf",
        "run_category": "benchmark_eval",
        "eval_scope": "freeform-spans",
        "precision": "0.05",
        "recall": "0.25",
        "f1": "0.08333333333333333",
        "practical_precision": "0.70",
        "practical_recall": "0.85",
        "practical_f1": "0.767741935483871",
        "gold_total": "100",
        "gold_recipe_headers": "11",
        "gold_matched": "25",
        "pred_total": "500",
        "supported_precision": "0.08",
        "supported_recall": "0.55",
        "supported_practical_precision": "0.72",
        "supported_practical_recall": "0.88",
        "supported_practical_f1": "0.7919999999999999",
        "granularity_mismatch_likely": "1",
        "pred_width_p50": "28",
        "gold_width_p50": "1",
        "boundary_correct": "10",
        "boundary_over": "8",
        "boundary_under": "5",
        "boundary_partial": "2",
        "tokens_input": "1234",
        "tokens_cached_input": "234",
        "tokens_output": "345",
        "tokens_reasoning": "12",
        "tokens_total": "1591",
    }
)


SAMPLE_REPORT_JSON = {
    "runTimestamp": "2026-02-12T09:00:00",
    "sourceFile": "test_book.pdf",
    "importerName": "pdf",
    "totalRecipes": 15,
    "totalStandaloneBlocks": 4,
    "warnings": ["low confidence on sheet 2"],
    "errors": [],
    "timing": {
        "total_seconds": 8.0,
        "parsing_seconds": 3.0,
        "writing_seconds": 4.5,
        "ocr_seconds": 0.5,
        "checkpoints": {"write_final_seconds": 4.0},
    },
    "outputStats": {
        "files": {
            "total": {"count": 8, "bytes": 45000},
        },
    },
    "runConfig": {
        "epub_extractor": "beautifulsoup",
        "epub_extractor_requested": "beautifulsoup",
        "epub_extractor_effective": "beautifulsoup",
        "ocr_device": "auto",
        "ocr_batch_size": 1,
        "effective_workers": 10,
    },
    "runConfigHash": "abc123def456",
    "runConfigSummary": "epub_extractor=beautifulsoup",
}


SAMPLE_EVAL_REPORT = {
    "precision": 0.05,
    "recall": 0.25,
    "f1": 0.08333333333333333,
    "practical_precision": 0.7,
    "practical_recall": 0.85,
    "practical_f1": 0.767741935483871,
    "supported_practical_precision": 0.72,
    "supported_practical_recall": 0.88,
    "supported_practical_f1": 0.792,
    "span_width_stats": {
        "gold": {"min": 1, "p50": 1, "p90": 2, "max": 4, "avg": 1.2},
        "pred": {"min": 3, "p50": 28, "p90": 45, "max": 60, "avg": 24.5},
    },
    "granularity_mismatch": {
        "likely": True,
        "reason": "Strict IoU is near zero while practical overlap is high.",
        "ratio_p50_pred_to_gold": 28.0,
    },
    "counts": {
        "gold_total": 100,
        "gold_matched": 25,
        "gold_missed": 75,
        "pred_total": 500,
        "pred_matched": 25,
        "pred_false_positive": 475,
    },
    "recipe_counts": {
        "gold_recipe_headers": 11,
        "predicted_recipe_count": 14,
    },
    "per_label": {
        "RECIPE_TITLE": {
            "precision": 0.1,
            "recall": 0.4,
            "gold_total": 30,
            "pred_total": 120,
        },
        "INGREDIENT_LINE": {
            "precision": 0.03,
            "recall": 0.2,
            "gold_total": 70,
            "pred_total": 380,
        },
    },
    "boundary": {
        "correct": 10,
        "over": 8,
        "under": 5,
        "partial": 2,
    },
    "app_aligned": {
        "supported_labels_relaxed": {
            "precision": 0.08,
            "recall": 0.55,
        }
    },
}


def _write_csv(tmp_path: Path) -> Path:
    """Create a small performance_history.csv fixture."""
    history_dir = history_csv_for_output(tmp_path / "output").parent
    history_dir.mkdir(parents=True)
    csv_path = history_dir / "performance_history.csv"
    csv_path.write_text(
        SAMPLE_CSV_HEADER + "\n" + SAMPLE_CSV_ROW1 + "\n" + SAMPLE_CSV_ROW2 + "\n",
        encoding="utf-8",
    )
    return csv_path


def _write_report_json(tmp_path: Path) -> Path:
    """Create a conversion report JSON in a timestamp folder."""
    run_dir = tmp_path / "output" / "2026-02-12_09.00.00"
    run_dir.mkdir(parents=True)
    report_path = run_dir / "test_book.excel_import_report.json"
    report_path.write_text(json.dumps(SAMPLE_REPORT_JSON), encoding="utf-8")
    return report_path


def _write_eval_report(tmp_path: Path) -> Path:
    """Create a benchmark eval fixture."""
    eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-11_00.30.00"
    eval_dir.mkdir(parents=True)
    eval_path = eval_dir / "eval_report.json"
    eval_path.write_text(json.dumps(SAMPLE_EVAL_REPORT), encoding="utf-8")
    return eval_path


def _run_compare_control_behavior_harness(js_path: Path) -> dict[str, object]:
    """Run generated dashboard JS compare/control behavior checks in Node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for compare/control behavior harness")
    harness = r"""
const fs = require("fs");
const jsPath = process.argv[1];
    let js = fs.readFileSync(jsPath, "utf8");
const bootNeedle = '  try {\n    const inlineData = loadInlineData();';
const initNeedle = '  function init() {';
const bootStart = js.indexOf(bootNeedle);
const initStart = js.indexOf(initNeedle);
if (bootStart < 0 || initStart < 0 || initStart <= bootStart) {
  throw new Error("Could not find dashboard bootstrap block in JS output");
}
js = js.slice(0, bootStart) + "  // boot disabled in node behavior harness\n\n" + js.slice(initStart);
js = js.replace(/\n\}\)\(\);\s*$/, `
  globalThis.__compareControlHarness = {
    buildCompareControlFieldCatalog,
    analyzeCompareControlCategoricalRaw,
  analyzeCompareControlCategoricalControlled,
  compareControlRecordsForState,
  applyCompareControlSelectionSubset,
  normalizeCompareControlState,
  resetCompareControlStateForHarness: function() {
    resetCompareControlState();
    const state = compareControlState;
    return {
      applied: true,
      state: JSON.parse(JSON.stringify(state || {})),
    };
  },
  setCompareControlStateForHarness: function(state) {
    compareControlState = normalizeCompareControlState(state);
  },
  setDataForHarness: function(benchmarkRecords) {
    DATA = {
      stage_records: [],
      benchmark_records: Array.isArray(benchmarkRecords) ? benchmarkRecords : [],
    };
  },
    clearColumnFiltersForHarness: function() {
      previousRunsColumnFilters = Object.create(null);
      previousRunsColumnFilterModes = Object.create(null);
    },
    getColumnFiltersForHarness: function() {
      return JSON.parse(JSON.stringify(previousRunsColumnFilters));
    },
    getColumnFilterModeForHarness: function(fieldName) {
      return previousRunsColumnFilterMode(fieldName);
    },
  };
})();
`);
eval(js);
    const hooks = globalThis.__compareControlHarness;
    if (!hooks) throw new Error("Compare/control harness exports were not attached");

    const records = [];
for (let i = 0; i < 1; i += 1) records.push({ strict_accuracy: 0.2, compare_group: "A", stratum: "S1" });
for (let i = 0; i < 9; i += 1) records.push({ strict_accuracy: 0.3, compare_group: "B", stratum: "S1" });
for (let i = 0; i < 9; i += 1) records.push({ strict_accuracy: 0.9, compare_group: "A", stratum: "S2" });
for (let i = 0; i < 1; i += 1) records.push({ strict_accuracy: 1.0, compare_group: "B", stratum: "S2" });

const raw = hooks.analyzeCompareControlCategoricalRaw(records, "strict_accuracy", "compare_group");
const controlled = hooks.analyzeCompareControlCategoricalControlled(
  records,
  "strict_accuracy",
  "compare_group",
  ["stratum"]
);
const secondaryRecords = [
  {
    strict_accuracy: 0.61,
    compare_group: "A",
    benchmark_total_seconds: 0.0,
    benchmark_prediction_seconds: 0.0,
    benchmark_evaluation_seconds: 0.0,
    tokens_input: 800,
    tokens_cached_input: 100,
    tokens_output: 80,
    tokens_total: 1100,
  },
  {
    strict_accuracy: 0.62,
    compare_group: "A",
    benchmark_total_seconds: 0.0,
    benchmark_prediction_seconds: 0.0,
    benchmark_evaluation_seconds: 0.0,
    tokens_input: 900,
    tokens_cached_input: 120,
    tokens_output: 90,
    tokens_total: 1200,
  },
  {
    strict_accuracy: 0.58,
    compare_group: "B",
    benchmark_total_seconds: 0.0,
    benchmark_prediction_seconds: 0.0,
    benchmark_evaluation_seconds: 0.0,
    tokens_input: 700,
    tokens_cached_input: 90,
    tokens_output: 70,
    tokens_total: 900,
  },
  {
    strict_accuracy: 0.57,
    compare_group: "B",
    benchmark_total_seconds: 0.0,
    benchmark_prediction_seconds: 0.0,
    benchmark_evaluation_seconds: 0.0,
    tokens_input: 650,
    tokens_cached_input: 80,
    tokens_output: 65,
    tokens_total: 800,
  },
];
const secondaryAnalysis = hooks.analyzeCompareControlCategoricalRaw(
  secondaryRecords,
  "strict_accuracy",
  "compare_group"
);

function toGroupMap(groups) {
  const out = Object.create(null);
  (Array.isArray(groups) ? groups : []).forEach(group => {
    if (!group || !group.key) return;
    out[String(group.key)] = group;
  });
  return out;
}

const rawByGroup = toGroupMap(raw.groups);
const controlledByGroup = toGroupMap(controlled.groups);
hooks.setDataForHarness(
  records.map((row, index) => ({
    ...row,
    run_category: "benchmark_eval",
    run_timestamp: "2026-03-04T10:" + String(index).padStart(2, "0") + ":00",
  }))
);

hooks.clearColumnFiltersForHarness();
hooks.setCompareControlStateForHarness({
  compare_field: "compare_group",
  selected_groups: ["A", "B"],
});
const subset = hooks.applyCompareControlSelectionSubset();
const filters = hooks.getColumnFiltersForHarness();
const filterClauses = Array.isArray(filters.compare_group) ? filters.compare_group : [];
const filterMode = hooks.getColumnFilterModeForHarness("compare_group");
const localSubsetRows = hooks.compareControlRecordsForState(
  records,
  hooks.normalizeCompareControlState({
    compare_field: "compare_group",
    selected_groups: ["A"],
  }),
  { by_field: { compare_group: { numeric: false } } }
);

const payload = {
  raw_A: rawByGroup.A ? rawByGroup.A.outcome_mean : null,
  raw_B: rawByGroup.B ? rawByGroup.B.outcome_mean : null,
  controlled_A: controlledByGroup.A ? controlledByGroup.A.outcome_mean : null,
  controlled_B: controlledByGroup.B ? controlledByGroup.B.outcome_mean : null,
  subset_applied: Boolean(subset && subset.applied),
  subset_message: String((subset && subset.message) || ""),
  subset_mode: filterMode,
  subset_clause_count: filterClauses.length,
  subset_clause_values: filterClauses.map(clause => String((clause && clause.value) || "")),
  subset_clause_operators: filterClauses.map(clause => String((clause && clause.operator) || "")),
  local_subset_rows: Array.isArray(localSubsetRows) ? localSubsetRows.length : 0,
  local_subset_groups: Array.from(new Set((Array.isArray(localSubsetRows) ? localSubsetRows : []).map(row => String((row && row.compare_group) || "")))),
  secondary_fields: Array.isArray(secondaryAnalysis.secondary_fields)
    ? secondaryAnalysis.secondary_fields.slice()
    : [],
};
hooks.setCompareControlStateForHarness({
  outcome_field: "strict_accuracy",
  compare_field: "compare_group",
  hold_constant_fields: ["stratum"],
  split_field: "stratum",
  view_mode: "controlled",
  selected_groups: ["A"],
});
const resetState = hooks.resetCompareControlStateForHarness();
payload.reset_state = resetState.state;
process.stdout.write(JSON.stringify(payload));
"""
    completed = subprocess.run(
      [node, "-e", harness, str(js_path)],
      capture_output=True,
      text=True,
      check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Compare/control behavior harness failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout.strip())


def _run_compare_control_chart_harness(js_path: Path) -> dict[str, object]:
    """Run generated dashboard JS compare/control chart-definition checks in Node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for compare/control chart harness")
    harness = r"""
const fs = require("fs");
const jsPath = process.argv[1];
let js = fs.readFileSync(jsPath, "utf8");
const bootNeedle = '  try {\n    const inlineData = loadInlineData();';
const initNeedle = '  function init() {';
const bootStart = js.indexOf(bootNeedle);
const initStart = js.indexOf(initNeedle);
if (bootStart < 0 || initStart < 0 || initStart <= bootStart) {
  throw new Error("Could not find dashboard bootstrap block in JS output");
}
js = js.slice(0, bootStart) + "  // boot disabled in node behavior harness\n\n" + js.slice(initStart);
js = js.replace(/\n\}\)\(\);\s*$/, `
  globalThis.__compareControlChartHarness = {
    buildCompareControlFieldCatalog,
    normalizeCompareControlStateForCatalog,
    compareControlRecordsForState,
    buildCompareControlChartDefinition,
    buildCombinedCompareControlChartDefinition,
    setCombinedAxisModeForHarness: function(mode) {
      compareControlCombinedAxisMode = normalizeCompareControlCombinedAxisMode(mode);
    },
  };
})();
`);
eval(js);
const hooks = globalThis.__compareControlChartHarness;
if (!hooks) throw new Error("Compare/control chart harness exports were not attached");

const records = [
  { run_timestamp: "2026-03-04T10:00:00", source_file: "/tmp/book_a.epub", importer_name: "epub", tokens_total: 1000, tokens_input: 1000, tokens_cached_input: 100, tokens_output: 80, strict_accuracy: 0.60 },
  { run_timestamp: "2026-03-04T10:01:00", source_file: "/tmp/book_a.epub", importer_name: "pdf", tokens_total: 1200, tokens_input: 1200, tokens_cached_input: 120, tokens_output: 90, strict_accuracy: 0.64 },
  { run_timestamp: "2026-03-04T10:02:00", source_file: "/tmp/book_a.epub", importer_name: "epub", tokens_total: 1400, tokens_input: 1400, tokens_cached_input: 140, tokens_output: 95, strict_accuracy: 0.66 },
  { run_timestamp: "2026-03-04T10:03:00", source_file: "/tmp/book_b.epub", importer_name: "epub", tokens_total: 1600, tokens_input: 1600, tokens_cached_input: 160, tokens_output: 100, strict_accuracy: 0.68 },
  { run_timestamp: "2026-03-04T10:04:00", source_file: "/tmp/book_b.epub", importer_name: "pdf", tokens_total: 1800, tokens_input: 1800, tokens_cached_input: 180, tokens_output: 110, strict_accuracy: 0.72 },
  { run_timestamp: "2026-03-04T10:05:00", source_file: "/tmp/book_b.epub", importer_name: "pdf", tokens_total: 2000, tokens_input: 2000, tokens_cached_input: 200, tokens_output: 120, strict_accuracy: 0.74 },
];
const catalog = hooks.buildCompareControlFieldCatalog(records);

const numericState = hooks.normalizeCompareControlStateForCatalog(
  {
    outcome_field: "strict_accuracy",
    compare_field: "all_token_use",
    split_field: "source_label",
    view_mode: "raw",
  },
  catalog
);
const numericChart = hooks.buildCompareControlChartDefinition({
  records,
  total_rows: records.length,
  state: numericState,
  catalog,
  compare_info: catalog.by_field[numericState.compare_field],
});
const numericSeries = Array.isArray(numericChart.series) ? numericChart.series : [];
const numericPointTotal = numericSeries.reduce(
  (total, series) => total + (Array.isArray(series.data) ? series.data.length : 0),
  0
);
const numericFirstPoint = (
  numericSeries.length &&
  Array.isArray(numericSeries[0].data) &&
  numericSeries[0].data.length
) ? numericSeries[0].data[0] : null;

const timeState = hooks.normalizeCompareControlStateForCatalog(
  {
    outcome_field: "all_token_use",
    compare_field: "run_timestamp",
    split_field: "source_label",
    view_mode: "raw",
  },
  catalog
);
const timeChart = hooks.buildCompareControlChartDefinition({
  records,
  total_rows: records.length,
  state: timeState,
  catalog,
  compare_info: catalog.by_field[timeState.compare_field],
});
const timeSeries = Array.isArray(timeChart.series) ? timeChart.series : [];
const timePointTotal = timeSeries.reduce(
  (total, series) => total + (Array.isArray(series.data) ? series.data.length : 0),
  0
);
const timeFirstPoint = (
  timeSeries.length &&
  Array.isArray(timeSeries[0].data) &&
  timeSeries[0].data.length
) ? timeSeries[0].data[0] : null;

const categoricalState = hooks.normalizeCompareControlStateForCatalog(
  {
    outcome_field: "strict_accuracy",
    compare_field: "importer_name",
    split_field: "source_label",
    view_mode: "raw",
  },
  catalog
);
const categoricalScopedRecords = hooks.compareControlRecordsForState(
  records,
  categoricalState,
  catalog
);
const categoricalChart = hooks.buildCompareControlChartDefinition({
  records: categoricalScopedRecords,
  total_rows: records.length,
  state: categoricalState,
  catalog,
  compare_info: catalog.by_field[categoricalState.compare_field],
});
const categoricalSeries = Array.isArray(categoricalChart.series) ? categoricalChart.series : [];
const categoricalPointTotal = categoricalSeries.reduce(
  (total, series) => total + (Array.isArray(series.data) ? series.data.length : 0),
  0
);
const categoricalFirstSeries = categoricalSeries.length ? categoricalSeries[0] : null;
const categoricalPointColors = (
  categoricalFirstSeries &&
  Array.isArray(categoricalFirstSeries.data)
)
  ? categoricalFirstSeries.data
      .filter(point => point && typeof point === "object")
      .map(point => String(point.color || ""))
      .filter(value => value.length > 0)
  : [];
function firstColorForCompareValue(chart, compareValue) {
  const target = String(compareValue || "");
  const seriesList = Array.isArray(chart && chart.series) ? chart.series : [];
  for (const series of seriesList) {
    const points = Array.isArray(series && series.data) ? series.data : [];
    for (const point of points) {
      if (!point || typeof point !== "object") continue;
      const custom = point.custom && typeof point.custom === "object"
        ? point.custom
        : {};
      if (String(custom.compareValue || "") !== target) continue;
      const color = String(point.color || "").trim();
      if (color) return color;
    }
  }
  return "";
}
const categoricalSubsetState = hooks.normalizeCompareControlStateForCatalog(
  {
    outcome_field: "strict_accuracy",
    compare_field: "importer_name",
    split_field: "source_label",
    view_mode: "raw",
    selected_groups: ["epub"],
  },
  catalog
);
const categoricalSubsetRecords = hooks.compareControlRecordsForState(
  records,
  categoricalSubsetState,
  catalog
);
const categoricalSubsetChart = hooks.buildCompareControlChartDefinition({
  records: categoricalSubsetRecords,
  total_rows: records.length,
  state: categoricalSubsetState,
  catalog,
  compare_info: catalog.by_field[categoricalSubsetState.compare_field],
});
const categoricalColorEpubAll = firstColorForCompareValue(categoricalChart, "epub");
const categoricalColorEpubSubset = firstColorForCompareValue(categoricalSubsetChart, "epub");

const reorderedRecords = [
  { run_timestamp: "2026-03-04T11:00:00", source_file: "/tmp/book_a.epub", importer_name: "pdf", strict_accuracy: 0.61 },
  { run_timestamp: "2026-03-04T11:01:00", source_file: "/tmp/book_a.epub", importer_name: "pdf", strict_accuracy: 0.62 },
  { run_timestamp: "2026-03-04T11:02:00", source_file: "/tmp/book_a.epub", importer_name: "pdf", strict_accuracy: 0.63 },
  { run_timestamp: "2026-03-04T11:03:00", source_file: "/tmp/book_b.epub", importer_name: "pdf", strict_accuracy: 0.64 },
  { run_timestamp: "2026-03-04T11:04:00", source_file: "/tmp/book_b.epub", importer_name: "epub", strict_accuracy: 0.65 },
];
const reorderedCatalog = hooks.buildCompareControlFieldCatalog(reorderedRecords);
const reorderedState = hooks.normalizeCompareControlStateForCatalog(
  {
    outcome_field: "strict_accuracy",
    compare_field: "importer_name",
    split_field: "",
    view_mode: "raw",
  },
  reorderedCatalog
);
const reorderedScopedRecords = hooks.compareControlRecordsForState(
  reorderedRecords,
  reorderedState,
  reorderedCatalog
);
const reorderedChart = hooks.buildCompareControlChartDefinition({
  records: reorderedScopedRecords,
  total_rows: reorderedRecords.length,
  state: reorderedState,
  catalog: reorderedCatalog,
  compare_info: reorderedCatalog.by_field[reorderedState.compare_field],
});
const categoricalColorEpubReordered = firstColorForCompareValue(reorderedChart, "epub");
const categoricalColorPdfAll = firstColorForCompareValue(categoricalChart, "pdf");
const categoricalColorPdfReordered = firstColorForCompareValue(reorderedChart, "pdf");

const discoverState = hooks.normalizeCompareControlStateForCatalog(
  {
    outcome_field: "strict_accuracy",
    compare_field: "",
    view_mode: "discover",
  },
  catalog
);
const discoverChart = hooks.buildCompareControlChartDefinition({
  records,
  total_rows: records.length,
  state: discoverState,
  catalog,
  compare_info: null,
});

const categoricalAltState = hooks.normalizeCompareControlStateForCatalog(
  {
    outcome_field: "strict_accuracy",
    compare_field: "source_label",
    split_field: "importer_name",
    view_mode: "raw",
  },
  catalog
);
const categoricalAltScopedRecords = hooks.compareControlRecordsForState(
  records,
  categoricalAltState,
  catalog
);
const categoricalAltChart = hooks.buildCompareControlChartDefinition({
  records: categoricalAltScopedRecords,
  total_rows: records.length,
  state: categoricalAltState,
  catalog,
  compare_info: catalog.by_field[categoricalAltState.compare_field],
});

hooks.setCombinedAxisModeForHarness("single");
const combinedSingleChart = hooks.buildCombinedCompareControlChartDefinition(
  categoricalChart,
  categoricalAltChart
);
hooks.setCombinedAxisModeForHarness("dual");
const combinedDualChart = hooks.buildCombinedCompareControlChartDefinition(
  categoricalChart,
  categoricalAltChart
);
const combinedMixedChart = hooks.buildCombinedCompareControlChartDefinition(
  numericChart,
  categoricalChart
);

const combinedSingleSeries = Array.isArray(combinedSingleChart.series) ? combinedSingleChart.series : [];
const combinedDualSeries = Array.isArray(combinedDualChart.series) ? combinedDualChart.series : [];
const combinedDualSecondarySeries = combinedDualSeries.filter(
  series => String((series && series.name) || "").startsWith("Set 2 - ")
);
const combinedSinglePointTotal = combinedSingleSeries.reduce(
  (total, series) => total + (
    Array.isArray(series.data)
      ? series.data.filter(point => point != null).length
      : 0
  ),
  0
);

const payload = {
  numeric_chart_type: String(numericChart.chart_type || ""),
  numeric_series_count: numericSeries.length,
  numeric_point_total: numericPointTotal,
  numeric_title: String(numericChart.chart_title || ""),
  numeric_subtitle: String(numericChart.chart_subtitle || ""),
  numeric_first_compare_value: numericFirstPoint ? Number(numericFirstPoint.x) : null,
  numeric_first_outcome_value: numericFirstPoint ? Number(numericFirstPoint.y) : null,
  numeric_first_split_label: (
    numericFirstPoint &&
    numericFirstPoint.custom &&
    String(numericFirstPoint.custom.splitLabel || "")
  ) || "",
  time_chart_type: String(timeChart.chart_type || ""),
  time_series_count: timeSeries.length,
  time_point_total: timePointTotal,
  time_title: String(timeChart.chart_title || ""),
  time_x_axis_type: String((timeChart.x_axis && timeChart.x_axis.type) || ""),
  time_first_compare_value: (
    timeFirstPoint &&
    timeFirstPoint.custom &&
    String(timeFirstPoint.custom.compareValue || "")
  ) || "",
  time_first_x_is_number: Boolean(timeFirstPoint && Number.isFinite(Number(timeFirstPoint.x))),
  time_first_outcome_value: timeFirstPoint ? Number(timeFirstPoint.y) : null,
  categorical_series_count: categoricalSeries.length,
  categorical_chart_type: String(categoricalChart.chart_type || ""),
  categorical_title: String(categoricalChart.chart_title || ""),
  categorical_subtitle: String(categoricalChart.chart_subtitle || ""),
  categorical_categories_count: (
    categoricalChart &&
    categoricalChart.x_axis &&
    Array.isArray(categoricalChart.x_axis.categories)
  ) ? categoricalChart.x_axis.categories.length : 0,
  categorical_point_total: categoricalPointTotal,
  categorical_first_series_unique_colors: Array.from(new Set(categoricalPointColors)).length,
  categorical_first_series_first_color: categoricalPointColors.length
    ? categoricalPointColors[0]
    : "",
  categorical_epub_color_all: categoricalColorEpubAll,
  categorical_epub_color_subset: categoricalColorEpubSubset,
  categorical_epub_color_reordered: categoricalColorEpubReordered,
  categorical_pdf_color_all: categoricalColorPdfAll,
  categorical_pdf_color_reordered: categoricalColorPdfReordered,
  categorical_first_compare_value: (
    categoricalSeries.length &&
    Array.isArray(categoricalSeries[0].data) &&
    categoricalSeries[0].data.length &&
    categoricalSeries[0].data[0] &&
    categoricalSeries[0].data[0].custom
      ? String(categoricalSeries[0].data[0].custom.compareValue || "")
      : ""
  ),
  discover_series_count: Array.isArray(discoverChart.series) ? discoverChart.series.length : 0,
  discover_empty_reason: String(discoverChart.empty_reason || ""),
  combined_single_chart_type: String(combinedSingleChart.chart_type || ""),
  combined_single_series_count: combinedSingleSeries.length,
  combined_single_point_total: combinedSinglePointTotal,
  combined_single_subtitle: String(combinedSingleChart.chart_subtitle || ""),
  combined_single_categories_count: (
    combinedSingleChart &&
    combinedSingleChart.x_axis &&
    Array.isArray(combinedSingleChart.x_axis.categories)
  ) ? combinedSingleChart.x_axis.categories.length : 0,
  combined_dual_y_axis_count: Array.isArray(combinedDualChart.y_axis)
    ? combinedDualChart.y_axis.length
    : 0,
  combined_dual_secondary_series_on_axis_1: combinedDualSecondarySeries.every(
    series => Number(series && series.yAxis) === 1
  ),
  combined_mixed_series_count: Array.isArray(combinedMixedChart.series)
    ? combinedMixedChart.series.length
    : 0,
  combined_mixed_empty_reason: String(combinedMixedChart.empty_reason || ""),
};
process.stdout.write(JSON.stringify(payload));
"""
    completed = subprocess.run(
        [node, "-e", harness, str(js_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Compare/control chart harness failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout.strip())


def _run_previous_runs_filter_edit_harness(js_path: Path) -> dict[str, object]:
    """Run generated dashboard JS and verify in-place editing of filter clauses."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for previous-runs filter edit harness")
    harness = r"""
const fs = require("fs");
const jsPath = process.argv[1];
let js = fs.readFileSync(jsPath, "utf8");
const bootNeedle = '  try {\n    const inlineData = loadInlineData();';
const initNeedle = '  function init() {';
const bootStart = js.indexOf(bootNeedle);
const initStart = js.indexOf(initNeedle);
if (bootStart < 0 || initStart < 0 || initStart <= bootStart) {
  throw new Error("Could not find dashboard bootstrap block in JS output");
}
js = js.slice(0, bootStart) + "  // boot disabled in node behavior harness\n\n" + js.slice(initStart);
js = js.replace(/\n\}\)\(\);\s*$/, `
  globalThis.__previousRunsFilterEditHarness = {
    setPreviousRunsColumnFilterClauses,
    previousRunsColumnFilterClauses,
    openPreviousRunsColumnFilterEditor,
    closePreviousRunsColumnFilterEditor,
    currentPreviousRunsColumnFilterDraft,
    updatePreviousRunsColumnFilterAt,
  };
})();
`);
eval(js);
const hooks = globalThis.__previousRunsFilterEditHarness;
if (!hooks) throw new Error("Previous-runs filter edit harness exports were not attached");

hooks.setPreviousRunsColumnFilterClauses("ai_model", [
  { operator: "contains", value: "gpt-5.1-codex-mini" },
  { operator: "contains", value: "medium" },
]);
hooks.openPreviousRunsColumnFilterEditor("ai_model", {
  operator: "contains",
  value: "gpt-5.1-codex-mini",
  edit_index: 0,
});
const editDraft = hooks.currentPreviousRunsColumnFilterDraft("ai_model");
const updateApplied = hooks.updatePreviousRunsColumnFilterAt(
  "ai_model",
  editDraft.edit_index,
  "starts_with",
  "gpt-5.1"
);
const clausesAfter = hooks.previousRunsColumnFilterClauses("ai_model");
hooks.openPreviousRunsColumnFilterEditor("ai_model", {
  operator: "contains",
  value: "ignored",
  edit_index: 99,
});
const invalidDraft = hooks.currentPreviousRunsColumnFilterDraft("ai_model");
hooks.closePreviousRunsColumnFilterEditor();

const payload = {
  edit_draft_editing: Boolean(editDraft && editDraft.editing),
  edit_draft_index: editDraft && Number.isInteger(editDraft.edit_index) ? Number(editDraft.edit_index) : null,
  edit_draft_operator: String((editDraft && editDraft.operator) || ""),
  edit_draft_value: String((editDraft && editDraft.value) || ""),
  update_applied: Boolean(updateApplied),
  clauses_after_count: Array.isArray(clausesAfter) ? clausesAfter.length : 0,
  clause_0_operator: clausesAfter[0] ? String(clausesAfter[0].operator || "") : "",
  clause_0_value: clausesAfter[0] ? String(clausesAfter[0].value || "") : "",
  clause_1_operator: clausesAfter[1] ? String(clausesAfter[1].operator || "") : "",
  clause_1_value: clausesAfter[1] ? String(clausesAfter[1].value || "") : "",
  invalid_draft_editing: Boolean(invalidDraft && invalidDraft.editing),
  invalid_draft_index: invalidDraft && Number.isInteger(invalidDraft.edit_index)
    ? Number(invalidDraft.edit_index)
    : null,
};
process.stdout.write(JSON.stringify(payload));
"""
    completed = subprocess.run(
        [node, "-e", harness, str(js_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Previous-runs filter edit behavior harness failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout.strip())


def _run_benchmark_trend_alignment_harness(
    js_path: Path,
    records: list[dict[str, object]],
    trend_fields: list[str] | None = None,
) -> dict[str, object]:
    """Run generated dashboard JS benchmark trend-series alignment checks in Node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for benchmark trend behavior harness")
    harness = r"""
const fs = require("fs");
const jsPath = process.argv[1];
let js = fs.readFileSync(jsPath, "utf8");
const bootNeedle = '  try {\n    const inlineData = loadInlineData();';
const initNeedle = '  function init() {';
const bootStart = js.indexOf(bootNeedle);
const initStart = js.indexOf(initNeedle);
if (bootStart < 0 || initStart < 0 || initStart <= bootStart) {
  throw new Error("Could not find dashboard bootstrap block in JS output");
}
js = js.slice(0, bootStart) + "  // boot disabled in node behavior harness\n\n" + js.slice(initStart);
js = js.replace(/\n\}\)\(\);\s*$/, `
  globalThis.__trendHarness = {
    benchmarkRunGroupInfo,
    buildBenchmarkTrendSeries,
    benchmarkTrendVariantForRecord,
    buildRollingTrend,
    setBenchmarkTrendSelectedFields,
  };
})();
`);
eval(js);
const hooks = globalThis.__trendHarness;
if (!hooks) throw new Error("Trend harness exports were not attached");

const records = __RECORDS_JSON__;
const trendFields = __TREND_FIELDS_JSON__;
if (Array.isArray(trendFields) && typeof hooks.setBenchmarkTrendSelectedFields === "function") {
  hooks.setBenchmarkTrendSelectedFields(trendFields, {
    allow_empty: true,
    available_fields: trendFields,
  });
}
const series = hooks.buildBenchmarkTrendSeries(records);

function findSeries(name) {
  return series.find(item => item && String(item.name || "") === name) || null;
}

function pointCustomForRunTimestamp(seriesItem, runTimestamp) {
  if (!seriesItem || !Array.isArray(seriesItem.data) || !runTimestamp) return {};
  const match = seriesItem.data.find(point => (
    point &&
    point.custom &&
    String(point.custom.runTimestamp || "") === String(runTimestamp)
  ));
  return (match && match.custom) || {};
}

function firstX(name) {
  const item = findSeries(name);
  if (!item || !Array.isArray(item.data) || !item.data.length) return null;
  const point = item.data[0];
  if (!point) return null;
  const x = Number(point.x);
  return Number.isFinite(x) ? x : null;
}

const vanillaSeries = findSeries("strict_accuracy (vanilla)");
const codexSeries = findSeries("strict_accuracy (codex-exec)");
const tokenVanillaSeries = findSeries("tokens_total (vanilla)");
const tokenCodexSeries = findSeries("tokens_total (codex-exec)");
const vanillaRecord = records.find(record => String((record && record.artifact_dir) || "").includes("/vanilla"));
const codexRecord = records.find(record => String((record && record.artifact_dir) || "").includes("/codex-exec"));
const deterministicRecord = records.find(record => (
  String((record && record.artifact_dir) || "").includes("/line_role_only") ||
  String((record && record.benchmark_variant) || "") === "deterministic"
));
const vanillaGroup = vanillaRecord ? hooks.benchmarkRunGroupInfo(vanillaRecord) : null;
const codexGroup = codexRecord ? hooks.benchmarkRunGroupInfo(codexRecord) : null;
const deterministicGroup = deterministicRecord ? hooks.benchmarkRunGroupInfo(deterministicRecord) : null;
const deterministicTrendVariant = deterministicRecord
  ? String(hooks.benchmarkTrendVariantForRecord(deterministicRecord) || "")
  : "";
const vanillaPointCustom = (
  vanillaSeries &&
  Array.isArray(vanillaSeries.data) &&
  vanillaSeries.data.length &&
  vanillaSeries.data[0] &&
  vanillaSeries.data[0].custom
) || {};
const codexPointCustom = (
  codexSeries &&
  Array.isArray(codexSeries.data) &&
  codexSeries.data.length &&
  codexSeries.data[0] &&
  codexSeries.data[0].custom
) || {};
const deterministicPointCustom = pointCustomForRunTimestamp(
  deterministicTrendVariant === "codex-exec" ? codexSeries : vanillaSeries,
  deterministicRecord && deterministicRecord.run_timestamp
);

const payload = {
  vanilla_x: firstX("strict_accuracy (vanilla)"),
  codex_x: firstX("strict_accuracy (codex-exec)"),
  vanilla_series_points: vanillaSeries && Array.isArray(vanillaSeries.data) ? vanillaSeries.data.length : 0,
  codex_series_points: codexSeries && Array.isArray(codexSeries.data) ? codexSeries.data.length : 0,
  token_vanilla_series_points: tokenVanillaSeries && Array.isArray(tokenVanillaSeries.data) ? tokenVanillaSeries.data.length : 0,
  token_codex_series_points: tokenCodexSeries && Array.isArray(tokenCodexSeries.data) ? tokenCodexSeries.data.length : 0,
  vanilla_run_group_key: vanillaGroup ? String(vanillaGroup.runGroupKey || "") : "",
  codex_run_group_key: codexGroup ? String(codexGroup.runGroupKey || "") : "",
  deterministic_run_group_key: deterministicGroup ? String(deterministicGroup.runGroupKey || "") : "",
  vanilla_point_source_label: String(vanillaPointCustom.sourceLabel || ""),
  codex_point_source_label: String(codexPointCustom.sourceLabel || ""),
  deterministic_point_source_label: String(deterministicPointCustom.sourceLabel || ""),
  vanilla_point_source_title: String(vanillaPointCustom.sourceTitle || ""),
  codex_point_source_title: String(codexPointCustom.sourceTitle || ""),
  deterministic_point_source_title: String(deterministicPointCustom.sourceTitle || ""),
  vanilla_point_variant: String(vanillaPointCustom.variant || ""),
  codex_point_variant: String(codexPointCustom.variant || ""),
  deterministic_trend_variant: deterministicTrendVariant,
  deterministic_point_variant: String(deterministicPointCustom.variant || ""),
  vanilla_point_run_timestamp: String(vanillaPointCustom.runTimestamp || ""),
  codex_point_run_timestamp: String(codexPointCustom.runTimestamp || ""),
  deterministic_point_run_timestamp: String(deterministicPointCustom.runTimestamp || ""),
  selected_fields: Array.isArray(trendFields) ? trendFields : [],
};
process.stdout.write(JSON.stringify(payload));
"""
    harness = harness.replace("__RECORDS_JSON__", json.dumps(records))
    harness = harness.replace("__TREND_FIELDS_JSON__", json.dumps(trend_fields))
    completed = subprocess.run(
      [node, "-e", harness, str(js_path)],
      capture_output=True,
      text=True,
      check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Benchmark trend behavior harness failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout.strip())


def _run_benchmark_trend_overlay_tail_harness(
    js_path: Path,
    points: list[dict[str, object]],
) -> dict[str, object]:
    """Run generated dashboard JS and inspect rolling-trend tail behavior."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for benchmark trend behavior harness")
    harness = r"""
const fs = require("fs");
const jsPath = process.argv[1];
let js = fs.readFileSync(jsPath, "utf8");
const bootNeedle = '  try {\n    const inlineData = loadInlineData();';
const initNeedle = '  function init() {';
const bootStart = js.indexOf(bootNeedle);
const initStart = js.indexOf(initNeedle);
if (bootStart < 0 || initStart < 0 || initStart <= bootStart) {
  throw new Error("Could not find dashboard bootstrap block in JS output");
}
js = js.slice(0, bootStart) + "  // boot disabled in node behavior harness\n\n" + js.slice(initStart);
js = js.replace(/\n\}\)\(\);\s*$/, `
  globalThis.__trendOverlayHarness = {
    buildRollingTrend,
  };
})();
`);
eval(js);
const hooks = globalThis.__trendOverlayHarness;
if (!hooks || typeof hooks.buildRollingTrend !== "function") {
  throw new Error("Trend overlay harness exports were not attached");
}

const points = __POINTS_JSON__;
const result = hooks.buildRollingTrend(points);
const trendPoints = result && Array.isArray(result.trendPoints) ? result.trendPoints : [];
const tail = trendPoints.slice(-2).map(point => ({
  x: Number(point && point.x),
  y: Number(point && point.y),
}));
process.stdout.write(JSON.stringify({
  window_size: result ? Number(result.windowSize || 0) : 0,
  trend_point_count: trendPoints.length,
  tail,
}));
"""
    harness = harness.replace("__POINTS_JSON__", json.dumps(points))
    completed = subprocess.run(
        [node, "-e", harness, str(js_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Benchmark trend overlay harness failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout.strip())


def _run_latest_runtime_summary_harness(
    js_path: Path,
    records: list[dict[str, object]],
) -> dict[str, object]:
    """Run generated dashboard JS and verify latest runtime run-group aggregation."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for runtime summary harness")
    harness = r"""
const fs = require("fs");
const jsPath = process.argv[1];
let js = fs.readFileSync(jsPath, "utf8");
const bootNeedle = '  try {\n    const inlineData = loadInlineData();';
const initNeedle = '  function init() {';
const bootStart = js.indexOf(bootNeedle);
const initStart = js.indexOf(initNeedle);
if (bootStart < 0 || initStart < 0 || initStart <= bootStart) {
  throw new Error("Could not find dashboard bootstrap block in JS output");
}
js = js.slice(0, bootStart) + "  // boot disabled in node behavior harness\n\n" + js.slice(initStart);
js = js.replace(/\n\}\)\(\);\s*$/, `
  globalThis.__runtimeHarness = {
    latestRuntimeSummaryForRecords,
  };
})();
`);
eval(js);
const hooks = globalThis.__runtimeHarness;
if (!hooks || typeof hooks.latestRuntimeSummaryForRecords !== "function") {
  throw new Error("Runtime harness exports were not attached");
}

const records = __RECORDS_JSON__;
const summary = hooks.latestRuntimeSummaryForRecords(records);
const payload = summary
  ? {
      run_group_label: String(summary.runGroupLabel || ""),
      run_group_record_count: Number(summary.runGroupRecordCount || 0),
      token_use_value:
        summary.tokenUseValue == null ? null : Number(summary.tokenUseValue),
      token_use_display: String(summary.tokenUseDisplay || ""),
      context_model: String(summary.model || ""),
      context_effort: String(summary.effort || ""),
      context_pipeline: String(summary.pipelineMode || ""),
      quality_metric_key: String(summary.qualityMetricKey || ""),
      quality_per_million_tokens:
        summary.qualityPerMillionTokens == null
          ? null
          : Number(summary.qualityPerMillionTokens),
      quality_delta_vs_vanilla:
        summary.qualityDeltaVsVanilla == null
          ? null
          : Number(summary.qualityDeltaVsVanilla),
      quality_delta_per_million_extra_tokens_vs_vanilla:
        summary.qualityDeltaPerMillionExtraTokensVsVanilla == null
          ? null
          : Number(summary.qualityDeltaPerMillionExtraTokensVsVanilla),
      peer_rank:
        summary.peerQualityStats && summary.peerQualityStats.rank != null
          ? Number(summary.peerQualityStats.rank)
          : null,
      peer_total:
        summary.peerQualityStats && summary.peerQualityStats.total != null
          ? Number(summary.peerQualityStats.total)
          : null,
      peer_ratio_to_median:
        summary.peerQualityStats &&
        summary.peerQualityStats.ratioToMedian != null
          ? Number(summary.peerQualityStats.ratioToMedian)
          : null,
    }
  : {};
process.stdout.write(JSON.stringify(payload));
"""
    harness = harness.replace("__RECORDS_JSON__", json.dumps(records))
    completed = subprocess.run(
        [node, "-e", harness, str(js_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Latest runtime summary behavior harness failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout.strip())


def _run_previous_runs_quality_tokens_harness(
    js_path: Path,
) -> dict[str, object]:
    """Run generated dashboard JS and verify quality/tokens derived fields."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for quality/tokens harness")
    harness = r"""
const fs = require("fs");
const jsPath = process.argv[1];
let js = fs.readFileSync(jsPath, "utf8");
const bootNeedle = '  try {\n    const inlineData = loadInlineData();';
const initNeedle = '  function init() {';
const bootStart = js.indexOf(bootNeedle);
const initStart = js.indexOf(initNeedle);
if (bootStart < 0 || initStart < 0 || initStart <= bootStart) {
  throw new Error("Could not find dashboard bootstrap block in JS output");
}
js = js.slice(0, bootStart) + "  // boot disabled in node behavior harness\n\n" + js.slice(initStart);
js = js.replace(/\n\}\)\(\);\s*$/, `
  globalThis.__qualityTokensHarness = {
    aiAssistanceProfileLabelForRecord,
    aiAssistanceProfileForRecord,
    aiModelLabelForRecord,
    aiEffortLabelForRecord,
    benchmarkVariantForRecord,
    isOfficialGoldenBenchmarkRecord,
    previousRunsAllTokenUseDisplay,
    previousRunsFieldValue,
    previousRunsRowFieldValue,
  };
})();
`);
eval(js);
const hooks = globalThis.__qualityTokensHarness;
if (!hooks) throw new Error("Quality/tokens harness exports were not attached");

const record = {
  strict_accuracy: 0.5,
  tokens_input: 1000,
  tokens_cached_input: 200,
  tokens_output: 100,
  tokens_total: 1100,
  recipes: 4,
  run_config: {
    single_book_split_cache: {
      conversion_seconds: 20,
    },
  },
};
const allMethodRow = {
  type: "all_method",
  strict_accuracy: 0.25,
  tokens_input: 2000,
  tokens_cached_input: 0,
  tokens_output: 0,
  tokens_total: 2000,
};
const missingTelemetryRecord = {
  strict_accuracy: 0.54,
  run_config: {
    llm_recipe_pipeline: "codex-recipe-shard-v1",
    codex_farm_model: "gpt-5.1-codex-mini",
  },
};
const explicitZeroTelemetryRecord = {
  strict_accuracy: 0.54,
  run_config: {
    llm_recipe_pipeline: "codex-recipe-shard-v1",
    codex_farm_model: "gpt-5.1-codex-mini",
  },
  tokens_input: 0,
  tokens_cached_input: 0,
  tokens_output: 0,
  tokens_total: 0,
};
const runtimeErrorRecord = {
  strict_accuracy: 0.54,
  run_config: {
    llm_recipe_pipeline: "codex-recipe-shard-v1",
    line_role_pipeline: "off",
    codex_farm_model: "gpt-5.1-codex-mini",
    codex_farm_runtime_error: "codex-farm failed for recipe.schemaorg.v1 (subprocess_exit=124)",
  },
};
const aiOffEffortRecord = {
  strict_accuracy: 0.54,
  run_config: {
    llm_recipe_pipeline: "off",
    line_role_pipeline: "off",
  },
};
const vanillaPathAiOffEffortRecord = {
  strict_accuracy: 0.54,
  artifact_dir: "/tmp/golden/benchmark-vs-golden/2026-03-03_23.00.00/single-book-benchmark/my-book/vanilla",
  run_config: {
    llm_recipe_pipeline: "off",
    line_role_pipeline: "off",
  },
};
const lineRoleOnlyEffortRecord = {
  strict_accuracy: 0.54,
  run_config: {
    llm_recipe_pipeline: "off",
    line_role_pipeline: "codex-line-role-route-v2",
  },
};
const legacyCodexfarmRecord = {
  strict_accuracy: 0.54,
  artifact_dir: "/tmp/golden/benchmark-vs-golden/2026-03-03_13.00.00/single-book-benchmark/my-book/codex-exec",
  run_config: {
    llm_recipe_pipeline: "codex-recipe-shard-v1",
    codex_farm_model: "gpt-5.1-codex-mini",
  },
};
const legacyVanillaRecord = {
  strict_accuracy: 0.54,
  artifact_dir: "/tmp/golden/benchmark-vs-golden/2026-03-03_13.00.00/single-book-benchmark/my-book/vanilla",
  run_config: {},
};
const legacyRunDirCodexfarmRecord = {
  strict_accuracy: 0.54,
  run_dir: "/tmp/golden/benchmark-vs-golden/2026-03-03_13.00.00/single-book-benchmark/my-book/codex-exec",
  report_path: "/tmp/output/2026-03-03_13.00.00/single-book-benchmark/my-book/codex-exec/2026-03-03_13.08.47/report.json",
  run_config: {
    llm_recipe_pipeline: "codex-recipe-shard-v1",
    line_role_pipeline: "off",
  },
};
const legacyRunDirVanillaRecord = {
  strict_accuracy: 0.54,
  run_dir: "/tmp/golden/benchmark-vs-golden/2026-03-03_13.00.00/single-book-benchmark/my-book/vanilla",
  report_path: "/tmp/output/2026-03-03_13.00.00/single-book-benchmark/my-book/vanilla/2026-03-03_13.07.43/report.json",
  run_config: {},
};
const unknownEffortRecord = {
  strict_accuracy: 0.54,
  run_config: {},
};
const payload = {
  record_quality_per_million_tokens: Number(
    hooks.previousRunsFieldValue(record, "quality_per_million_tokens")
  ),
  record_conversion_seconds_per_recipe: Number(
    hooks.previousRunsFieldValue(record, "conversion_seconds_per_recipe")
  ),
  record_all_token_use_per_recipe: Number(
    hooks.previousRunsFieldValue(record, "all_token_use_per_recipe")
  ),
  all_method_quality_per_million_tokens: Number(
    hooks.previousRunsRowFieldValue(allMethodRow, "quality_per_million_tokens")
  ),
  missing_telemetry_ai_model: String(hooks.aiModelLabelForRecord(missingTelemetryRecord) || ""),
  missing_telemetry_token_display: String(
    hooks.previousRunsAllTokenUseDisplay({ record: missingTelemetryRecord }) || ""
  ),
  missing_telemetry_all_token_use: hooks.previousRunsFieldValue(
    missingTelemetryRecord,
    "all_token_use"
  ),
  explicit_zero_telemetry_token_display: String(
    hooks.previousRunsAllTokenUseDisplay({ record: explicitZeroTelemetryRecord }) || ""
  ),
  explicit_zero_telemetry_all_token_use: hooks.previousRunsFieldValue(
    explicitZeroTelemetryRecord,
    "all_token_use"
  ),
  runtime_error_ai_model: String(hooks.aiModelLabelForRecord(runtimeErrorRecord) || ""),
  runtime_error_effort_label: String(hooks.aiEffortLabelForRecord(runtimeErrorRecord) || ""),
  ai_off_effort_label: String(hooks.aiEffortLabelForRecord(aiOffEffortRecord) || ""),
  vanilla_path_ai_off_effort_label: String(
    hooks.aiEffortLabelForRecord(vanillaPathAiOffEffortRecord) || ""
  ),
  line_role_only_effort_label: String(hooks.aiEffortLabelForRecord(lineRoleOnlyEffortRecord) || ""),
  line_role_only_profile_label: String(
    hooks.aiAssistanceProfileLabelForRecord(lineRoleOnlyEffortRecord) || ""
  ),
  legacy_codex_exec_profile: String(hooks.aiAssistanceProfileForRecord(legacyCodexfarmRecord) || ""),
  legacy_codex_exec_variant: String(hooks.benchmarkVariantForRecord(legacyCodexfarmRecord) || ""),
  legacy_codex_exec_official: Boolean(hooks.isOfficialGoldenBenchmarkRecord(legacyCodexfarmRecord)),
  legacy_vanilla_profile: String(hooks.aiAssistanceProfileForRecord(legacyVanillaRecord) || ""),
  legacy_vanilla_variant: String(hooks.benchmarkVariantForRecord(legacyVanillaRecord) || ""),
  legacy_vanilla_official: Boolean(hooks.isOfficialGoldenBenchmarkRecord(legacyVanillaRecord)),
  legacy_rundir_codex_exec_profile: String(hooks.aiAssistanceProfileForRecord(legacyRunDirCodexfarmRecord) || ""),
  legacy_rundir_codex_exec_variant: String(hooks.benchmarkVariantForRecord(legacyRunDirCodexfarmRecord) || ""),
  legacy_rundir_codex_exec_official: Boolean(hooks.isOfficialGoldenBenchmarkRecord(legacyRunDirCodexfarmRecord)),
  legacy_rundir_vanilla_profile: String(hooks.aiAssistanceProfileForRecord(legacyRunDirVanillaRecord) || ""),
  legacy_rundir_vanilla_variant: String(hooks.benchmarkVariantForRecord(legacyRunDirVanillaRecord) || ""),
  legacy_rundir_vanilla_official: Boolean(hooks.isOfficialGoldenBenchmarkRecord(legacyRunDirVanillaRecord)),
  unknown_effort_label: String(hooks.aiEffortLabelForRecord(unknownEffortRecord) || ""),
};
process.stdout.write(JSON.stringify(payload));
"""
    completed = subprocess.run(
        [node, "-e", harness, str(js_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Quality/tokens behavior harness failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout.strip())


def _run_per_label_variant_fallback_harness(js_path: Path) -> dict[str, object]:
    """Run generated dashboard JS and verify per-label variant fallback behavior."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for per-label variant fallback harness")
    harness = r"""
const fs = require("fs");
const jsPath = process.argv[1];
let js = fs.readFileSync(jsPath, "utf8");
const bootNeedle = '  try {\n    const inlineData = loadInlineData();';
const initNeedle = '  function init() {';
const bootStart = js.indexOf(bootNeedle);
const initStart = js.indexOf(initNeedle);
if (bootStart < 0 || initStart < 0 || initStart <= bootStart) {
  throw new Error("Could not find dashboard bootstrap block in JS");
}
js = js.slice(0, bootStart) + "  // boot disabled in node behavior harness\n\n" + js.slice(initStart);
js = js.replace(/\n\}\)\(\);\s*$/, `
  globalThis.__perLabelVariantHarness = {
    mapBenchmarkVariantForPerLabel,
    aggregatePerLabelRows,
    perLabelRowsByLabel,
    benchmarkVariantForRecord,
    rollingPerLabelByVariant,
  };
})();
`);
eval(js);

const hooks = globalThis.__perLabelVariantHarness;
if (!hooks) {
  throw new Error("Per-label harness exports were not attached");
}

const singleProfileRecord = {
  run_timestamp: "2026-03-06T00.45.00",
  artifact_dir: "/tmp/golden/benchmark-vs-golden/2026-03-06_00.44.16/single-profile-benchmark/mybook/2026-03-06_00.45.00",
  run_config: {
    llm_recipe_pipeline: "codex-recipe-shard-v1",
    line_role_pipeline: "codex-line-role-route-v2",
    codex_farm_model: "gpt-5.3-codex-spark",
  },
  per_label: [
    {
      label: "INGREDIENT_LINE",
      precision: 0.35,
      recall: 0.40,
      gold_total: 10,
      pred_total: 20,
    },
  ],
};
const olderSingleProfileRecord = {
  run_timestamp: "2026-03-06T00.44.00",
  artifact_dir: "/tmp/golden/benchmark-vs-golden/2026-03-06_00.44.16/single-profile-benchmark/mybook/2026-03-06_00.44.00",
  run_config: {
    llm_recipe_pipeline: "codex-recipe-shard-v1",
    line_role_pipeline: "codex-line-role-route-v2",
    codex_farm_model: "gpt-5.3-codex-spark",
  },
  per_label: [
    {
      label: "INGREDIENT_LINE",
      precision: 0.15,
      recall: 0.20,
      gold_total: 8,
      pred_total: 16,
    },
  ],
};
const explicitVanillaRecord = {
  run_timestamp: "2026-03-06T00.40.00",
  artifact_dir: "/tmp/golden/benchmark-vs-golden/2026-03-06_00.40.00/single-profile-benchmark/mybook/2026-03-06_00.40.00/vanilla",
  run_config: {
    llm_recipe_pipeline: "off",
    line_role_pipeline: "off",
  },
  per_label: [
    {
      label: "INGREDIENT_LINE",
      precision: 0.05,
      recall: 0.10,
      gold_total: 8,
      pred_total: 16,
    },
  ],
};

const noOfficialRecords = [singleProfileRecord, olderSingleProfileRecord];
const noOfficialHasCodexOrVanilla = noOfficialRecords.some(record => {
  const variant = hooks.benchmarkVariantForRecord(record);
  return variant === "codex-exec" || variant === "vanilla";
});
const withOfficialRecords = [singleProfileRecord, explicitVanillaRecord];
const withOfficialHasCodexOrVanilla = withOfficialRecords.some(record => {
  const variant = hooks.benchmarkVariantForRecord(record);
  return variant === "codex-exec" || variant === "vanilla";
});
const mappedNoFallback = hooks.mapBenchmarkVariantForPerLabel(singleProfileRecord, false);
const mappedWithoutOfficial = hooks.mapBenchmarkVariantForPerLabel(
  singleProfileRecord,
  !noOfficialHasCodexOrVanilla
);

const noOfficialCodexRows = hooks.aggregatePerLabelRows(
  noOfficialRecords.filter(record => hooks.mapBenchmarkVariantForPerLabel(record, true) === "codex-exec")
);
const noOfficialCodexByLabel = hooks.perLabelRowsByLabel(noOfficialCodexRows);
const noOfficialCodexRow = noOfficialCodexByLabel["INGREDIENT_LINE"] || {};
const withOfficialCodexRows = hooks.aggregatePerLabelRows(
  withOfficialRecords.filter(record => hooks.mapBenchmarkVariantForPerLabel(record, false) === "codex-exec")
);
const withOfficialCodexByLabel = hooks.perLabelRowsByLabel(withOfficialCodexRows);
const withOfficialCodexRow = withOfficialCodexByLabel["INGREDIENT_LINE"] || {};
const noOfficialVanillaRows = hooks.aggregatePerLabelRows(
  noOfficialRecords.filter(record => hooks.benchmarkVariantForRecord(record) === "vanilla")
);
const noOfficialVanillaByLabel = hooks.perLabelRowsByLabel(noOfficialVanillaRows);
const noOfficialVanillaRow = noOfficialVanillaByLabel["INGREDIENT_LINE"] || {};
const rollingCodex = hooks.rollingPerLabelByVariant(
  noOfficialRecords,
  "codex-exec",
  2,
  record => hooks.mapBenchmarkVariantForPerLabel(record, !noOfficialHasCodexOrVanilla),
);
const rollingRow = rollingCodex["INGREDIENT_LINE"] || {};

const payload = {
  noOfficialHasCodexOrVanilla: Boolean(noOfficialHasCodexOrVanilla),
  singleProfileVariant: String(hooks.benchmarkVariantForRecord(singleProfileRecord) || ""),
  singleProfileMappedWithoutOfficial: String(mappedWithoutOfficial || ""),
  singleProfileMappedNoFallback: String(mappedNoFallback || ""),
  baseline_no_official_codex_precision: Number(noOfficialCodexRow.precision),
  baseline_no_official_codex_recall: Number(noOfficialCodexRow.recall),
  baseline_with_official_codex_precision: Number(withOfficialCodexRow.precision),
  baseline_vanilla_precision_no_official: Number(noOfficialVanillaRow.precision),
  rolling_no_official_codex_precision: Number(rollingRow.precision),
  rolling_no_official_codex_recall: Number(rollingRow.recall),
  withOfficialHasCodexOrVanilla: Boolean(withOfficialHasCodexOrVanilla),
};
process.stdout.write(JSON.stringify(payload));
"""
    completed = subprocess.run(
        [node, "-e", harness, str(js_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Per-label variant fallback harness failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout.strip())


def _run_benchmark_trend_host_rerender_harness(js_path: Path) -> dict[str, object]:
    """Run generated dashboard JS and verify trend host render behavior across re-renders."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for benchmark trend host rerender harness")
    harness = r"""
const fs = require("fs");
const jsPath = process.argv[1];
let js = fs.readFileSync(jsPath, "utf8");
const bootNeedle = '  try {\n    const inlineData = loadInlineData();';
const initNeedle = '  function init() {';
const bootStart = js.indexOf(bootNeedle);
const initStart = js.indexOf(initNeedle);
if (bootStart < 0 || initStart < 0 || initStart <= bootStart) {
  throw new Error("Could not find dashboard bootstrap block in JS output");
}
js = js.slice(0, bootStart) + "  // boot disabled in node behavior harness\n\n" + js.slice(initStart);
js = js.replace(/\n\}\)\(\);\s*$/, `
  globalThis.__trendHostHarness = {
    renderBenchmarkTrendChartHost,
  };
})();
`);
eval(js);
const hooks = globalThis.__trendHostHarness;
if (!hooks) throw new Error("Trend host harness exports were not attached");

const elements = {
  "benchmark-trend-chart": {
    innerHTML: "",
    textContent: "",
    hidden: false,
  },
  "benchmark-trend-fallback": {
    innerHTML: "",
    textContent: "",
    hidden: true,
  },
};
globalThis.document = {
  getElementById: (id) => Object.prototype.hasOwnProperty.call(elements, id) ? elements[id] : null,
};
const stockChartCalls = [];
globalThis.window = {
  Highcharts: {
    stockChart: (hostId, options) => {
      const host = elements[hostId];
      const beforeInnerHTML = String(host.innerHTML || "");
      stockChartCalls.push({
        host_id: String(hostId || ""),
        before_is_empty: beforeInnerHTML.length === 0,
        title: options && options.title ? String(options.title.text || "") : "",
      });
      host.innerHTML = beforeInnerHTML + "<div class='mock-highcharts-host'></div>";
      return {
        destroy: () => {
          host.innerHTML = "";
        },
      };
    },
    dateFormat: () => "",
  },
};

const trendSeries = [
  {
    name: "strict_accuracy",
    data: [
      {
        x: Date.parse("2026-03-01T10:00:00Z"),
        y: 0.9,
        custom: { runGroupKey: "2026-03-01_10.00.00", runGroupLabel: "2026-03-01_10.00.00" },
      },
    ],
  },
];
const config = {
  hostId: "benchmark-trend-chart",
  fallbackId: "benchmark-trend-fallback",
  records: [],
  trendSeries,
  totalRows: 1,
  chartTitle: "Harness Trend",
};
hooks.renderBenchmarkTrendChartHost(config);
hooks.renderBenchmarkTrendChartHost(config);

const payload = {
  stockchart_calls: stockChartCalls.length,
  first_before_empty: stockChartCalls.length > 0 ? Boolean(stockChartCalls[0].before_is_empty) : null,
  second_before_empty: stockChartCalls.length > 1 ? Boolean(stockChartCalls[1].before_is_empty) : null,
  final_host_markup_length: String(elements["benchmark-trend-chart"].innerHTML || "").length,
};
process.stdout.write(JSON.stringify(payload));
"""
    completed = subprocess.run(
        [node, "-e", harness, str(js_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Benchmark trend host rerender harness failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout.strip())


def _run_previous_runs_pixel_overflow_harness(html_path: Path) -> dict[str, object]:
    """Measure Previous Runs horizontal overflow in real browser pixels across rerenders."""
    playwright_sync_api = pytest.importorskip("playwright.sync_api")
    with playwright_sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover - environment-specific browser install issues
            pytest.skip(f"chromium launch unavailable for pixel harness: {exc}")
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.add_init_script(
            """
            (() => {
              const originalSetInterval = window.setInterval.bind(window);
              const originalSetTimeout = window.setTimeout.bind(window);
              window.setInterval = (handler, timeout, ...args) =>
                originalSetInterval(handler, Math.min(Number(timeout) || 0, 80), ...args);
              window.setTimeout = (handler, timeout, ...args) =>
                originalSetTimeout(handler, Math.min(Number(timeout) || 0, 80), ...args);
            })();
            """
        )

        highcharts_stub = (
            "window.Highcharts = window.Highcharts || {};\n"
            "window.Highcharts.stockChart = window.Highcharts.stockChart || function(){"
            "  return { destroy: function(){} };"
            "};\n"
            "window.Highcharts.chart = window.Highcharts.chart || function(){"
            "  return { destroy: function(){} };"
            "};\n"
            "window.Highcharts.setOptions = window.Highcharts.setOptions || function(){};\n"
            "window.Highcharts.dateFormat = window.Highcharts.dateFormat || function(){ return ''; };\n"
            "window.Highcharts.seriesTypes = window.Highcharts.seriesTypes || {};\n"
            "window.Highcharts.seriesTypes.arearange = window.Highcharts.seriesTypes.arearange || function(){};\n"
        )

        def _fulfill_highcharts(route) -> None:
            route.fulfill(
                status=200,
                content_type="application/javascript",
                body=highcharts_stub,
            )

        page.route("**/*highstock.js*", _fulfill_highcharts)
        page.route("**/*highcharts-more.js*", _fulfill_highcharts)

        page.goto(html_path.as_uri(), wait_until="networkidle", timeout=120000)
        page.wait_for_timeout(120)

        page.select_option("#compare-control-view-mode", "raw")
        page.wait_for_timeout(80)

        compare_candidates = page.evaluate(
            """() => Array.from(
                document.querySelectorAll("#compare-control-compare-field option")
            ).map(opt => String(opt.value || "").trim()).filter(Boolean)"""
        )
        preferred = [
            "source_file",
            "source_label",
            "artifact_dir",
            "run_config.scenario_key",
            "run_config_hash",
        ]
        selected = [field for field in preferred if field in compare_candidates]
        if len(selected) < 2:
            browser.close()
            pytest.skip("pixel harness could not find two categorical compare fields")

        def _sample(tag: str) -> dict[str, int | str]:
            return page.evaluate(
                """(tag) => {
                    const section = document.getElementById("previous-runs-section");
                    const root = document.documentElement;
                    return {
                      tag,
                      doc_client: Number(root.clientWidth || 0),
                      doc_scroll: Number(root.scrollWidth || 0),
                      section_client: Number(section ? section.clientWidth : 0),
                      section_scroll: Number(section ? section.scrollWidth : 0),
                    };
                }""",
                tag,
            )

        samples = [_sample("initial")]
        for index in range(8):
            page.select_option("#compare-control-compare-field", selected[index % 2])
            page.wait_for_timeout(40)
            samples.append(_sample(f"cycle_{index}"))

        browser.close()

    doc_overflows = [max(0, row["doc_scroll"] - row["doc_client"]) for row in samples]
    section_overflows = [
        max(0, row["section_scroll"] - row["section_client"])
        for row in samples
    ]
    doc_scroll_values = [row["doc_scroll"] for row in samples]
    return {
        "samples": samples,
        "max_doc_overflow_px": max(doc_overflows) if doc_overflows else 0,
        "max_section_overflow_px": max(section_overflows) if section_overflows else 0,
        "max_doc_scroll_delta_px": (
            max(doc_scroll_values) - min(doc_scroll_values)
            if doc_scroll_values
            else 0
        ),
    }


def _run_benchmark_trend_host_width_drift_harness(
    html_path: Path,
) -> dict[str, object]:
    """Measure benchmark trend host horizontal drift across timed rerenders."""
    dashboard_state_server = pytest.importorskip("cookimport.analytics.dashboard_state_server")
    playwright_sync_api = pytest.importorskip("playwright.sync_api")

    start_dashboard_server = dashboard_state_server.start_dashboard_server
    server, url = start_dashboard_server(
        dashboard_dir=html_path.parent,
        host="127.0.0.1",
        port=0,
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    state_request_counter = {"count": 0}
    try:
        with playwright_sync_api.sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:  # pragma: no cover - environment-specific browser install issues
                pytest.skip(f"chromium launch unavailable for trend host drift harness: {exc}")
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.add_init_script(
                """
                (() => {
                  const originalSetInterval = window.setInterval.bind(window);
                  const originalSetTimeout = window.setTimeout.bind(window);
                  window.setInterval = (handler, timeout, ...args) =>
                    originalSetInterval(handler, Math.min(Number(timeout) || 0, 80), ...args);
                  window.setTimeout = (handler, timeout, ...args) =>
                    originalSetTimeout(handler, Math.min(Number(timeout) || 0, 80), ...args);
                })();
                """
            )

            highcharts_stub = (
                "window.Highcharts = window.Highcharts || {};\n"
                "window.Highcharts.__renderCount = window.Highcharts.__renderCount || 0;\n"
                "window.Highcharts.stockChart = function(hostId, config){\n"
                "  window.Highcharts.__renderCount += 1;\n"
                "  var host = document.getElementById(hostId);\n"
                "  if (host) {\n"
                "    var configured = Number(config && config.chart && config.chart.width);\n"
                "    var width = (Number.isFinite(configured) && configured > 0)\n"
                "      ? configured\n"
                "      : (900 + (window.Highcharts.__renderCount * 120));\n"
                "    host.innerHTML = '<div class=\"highcharts-container\" style=\"width:' + width + 'px\">'\n"
                "      + '<svg width=\"' + width + '\" height=\"760\" style=\"display:block;width:' + width + 'px;height:760px\"></svg>'\n"
                "      + '</div>';\n"
                "  }\n"
                "  return { destroy: function(){} };\n"
                "};\n"
                "window.Highcharts.chart = function(hostId, config){\n"
                "  return window.Highcharts.stockChart(hostId, config);\n"
                "};\n"
                "window.Highcharts.setOptions = window.Highcharts.setOptions || function(){};\n"
                "window.Highcharts.dateFormat = window.Highcharts.dateFormat || function(){ return ''; };\n"
                "window.Highcharts.seriesTypes = window.Highcharts.seriesTypes || {};\n"
                "window.Highcharts.seriesTypes.arearange = window.Highcharts.seriesTypes.arearange || function(){};\n"
            )

            def _fulfill_highcharts(route) -> None:
                route.fulfill(
                    status=200,
                    content_type="application/javascript",
                    body=highcharts_stub,
                )

            def _fulfill_ui_state(route) -> None:
                state_request_counter["count"] += 1
                saved_at = (
                    dt.datetime(2099, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
                    + dt.timedelta(seconds=state_request_counter["count"])
                ).isoformat().replace("+00:00", "Z")
                payload = {
                    "version": 1,
                    "saved_at": saved_at,
                    "previous_runs": {
                        "quick_filters": {
                            "exclude_ai_tests": False,
                            "official_full_golden_only": False,
                        }
                    },
                }
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(payload),
                )

            page.route("**/*highstock.js*", _fulfill_highcharts)
            page.route("**/*highcharts-more.js*", _fulfill_highcharts)
            page.route("**/assets/dashboard_ui_state.json", _fulfill_ui_state)

            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_function(
                "() => Number(window.Highcharts && window.Highcharts.__renderCount || 0) >= 1",
                timeout=10000,
            )

            samples = []
            for index in range(5):
                sample = page.evaluate(
                    """(index) => {
                        const trend = document.getElementById("benchmark-trend-chart");
                        const compareControl = document.getElementById("compare-control-trend-chart");
                        return {
                          index,
                          render_count: Number(
                            window.Highcharts && window.Highcharts.__renderCount
                              ? window.Highcharts.__renderCount
                              : 0
                          ),
                          trend_client: Number(trend ? trend.clientWidth : 0),
                          trend_scroll: Number(trend ? trend.scrollWidth : 0),
                          compare_client: Number(compareControl ? compareControl.clientWidth : 0),
                          compare_scroll: Number(compareControl ? compareControl.scrollWidth : 0),
                        };
                    }""",
                    index,
                )
                samples.append(sample)
                if index < 4:
                    expected_render_count = int(sample.get("render_count", 0)) + 1
                    page.wait_for_function(
                        """
                        (expectedCount) => Number(
                            window.Highcharts && window.Highcharts.__renderCount
                              ? window.Highcharts.__renderCount
                              : 0
                        ) >= Number(expectedCount)
                        """,
                        arg=expected_render_count,
                        timeout=10000,
                    )

            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    trend_overflows = [
        max(0, sample["trend_scroll"] - sample["trend_client"])
        for sample in samples
    ]
    compare_overflows = [
        max(0, sample["compare_scroll"] - sample["compare_client"])
        for sample in samples
    ]
    trend_scroll_values = [sample["trend_scroll"] for sample in samples]
    compare_scroll_values = [sample["compare_scroll"] for sample in samples]
    render_counts = [sample["render_count"] for sample in samples]
    return {
        "samples": samples,
        "state_request_count": state_request_counter["count"],
        "highcharts_render_count": max(render_counts) if render_counts else 0,
        "max_trend_host_overflow_px": max(trend_overflows) if trend_overflows else 0,
        "max_compare_control_host_overflow_px": (
            max(compare_overflows) if compare_overflows else 0
        ),
        "trend_host_scroll_delta_px": (
            max(trend_scroll_values) - min(trend_scroll_values)
            if trend_scroll_values
            else 0
        ),
        "compare_control_host_scroll_delta_px": (
            max(compare_scroll_values) - min(compare_scroll_values)
            if compare_scroll_values
            else 0
        ),
    }
