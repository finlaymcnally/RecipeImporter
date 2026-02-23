---
summary: "Current analytics reference: artifact contracts, command behavior, caveats, and maintenance checklist."
read_when:
  - When changing performance reporting, CSV history writes, or stats-dashboard behavior
  - When debugging missing or inconsistent analytics artifacts under data/output or data/golden
  - When updating current analytics behavior; read `08-analytics_log.md` for prior attempts/history
---

# 08 Analytics README

This document consolidates the prior analytics docs in `docs/08-analytics/` and reconciles them with current code.

Scope: analytics/reporting only (what is emitted, where it is emitted, how it is consumed, and known quality gaps).

Historical versions, build/fix attempts, and anti-loop notes are tracked in `docs/08-analytics/08-analytics_log.md`.

## 1) What this section is

Analytics in this repo currently means three surfaces:

1. Per-file stage/import conversion reports
- Artifact: `<run_dir>/<workbook_slug>.excel_import_report.json`
- Producer: staging flows in `cookimport/cli_worker.py` and split-job merge in `cookimport/cli.py`
- Schema anchor: `cookimport/core/models.py` (`ConversionReport`)

2. Cross-run history CSV
- Artifact: `data/output/.history/performance_history.csv` (unless you explicitly call helpers with another root)
- Producer: `cookimport/analytics/perf_report.py` via:
  - auto-append at end of `cookimport stage`
  - manual `cookimport perf-report`
  - benchmark eval append paths (`append_benchmark_csv`)

3. Lifetime static dashboard
- Artifacts:
  - `data/output/.history/dashboard/index.html`
  - `data/output/.history/dashboard/assets/dashboard_data.json`
  - `data/output/.history/dashboard/assets/dashboard.js`
  - `data/output/.history/dashboard/assets/style.css`
- Producer: `cookimport stats-dashboard`
- Collector: `cookimport/analytics/dashboard_collect.py`
- Data contract: `cookimport/analytics/dashboard_schema.py`
- Current schema version: `7` (adds explicit EPUB extractor requested/effective/auto-score fields on stage records)
- Renderer: `cookimport/analytics/dashboard_render.py`
- `index.html` now embeds an inline copy of the same dashboard JSON so the dashboard still works when opened via `file://` in browsers that block local `fetch()`.

## 2) Where code lives

Primary analytics code:

- `cookimport/analytics/perf_report.py`
- `cookimport/analytics/dashboard_collect.py`
- `cookimport/analytics/dashboard_schema.py`
- `cookimport/analytics/dashboard_render.py`

Primary CLI integration:

- `cookimport/cli.py:stage` (`cookimport stage`)
- `cookimport/cli.py:perf_report` (`cookimport perf-report`)
- `cookimport/cli.py:stats_dashboard` (`cookimport stats-dashboard`)
- `cookimport/cli.py` benchmark/eval commands appending benchmark rows to history CSV

Related producers of report content:

- `cookimport/cli_worker.py` (`stage_one_file`, `stage_pdf_job`, `stage_epub_job`)
- `cookimport/cli.py:_merge_split_jobs` for merged PDF/EPUB split jobs
- `cookimport/staging/writer.py:write_report`
- `cookimport/core/timing.py` timing data structure/checkpoint helper
- `cookimport/core/models.py:ConversionReport` schema

## 3) Artifact map (current, code-verified)

### 3.1 Per-file run report (`*.excel_import_report.json`)

Core fields consumed by analytics:

- identity: `runTimestamp`, `sourceFile`, `importerName`
- counts: `totalRecipes`, `totalTips`, `totalTipCandidates`, `totalTopicCandidates`
- standalone topic coverage:
  - `totalStandaloneBlocks`
  - `totalStandaloneTopicBlocks`
  - `standaloneTopicCoverage`
- timing:
  - `timing.total_seconds`
  - `timing.parsing_seconds`
  - `timing.writing_seconds`
  - `timing.ocr_seconds`
  - `timing.checkpoints` (arbitrary named checkpoints)
- output footprint: `outputStats`
- quality metadata: `warnings`, `errors`
- run context:
  - `runConfig` (full structured settings snapshot)
  - `runConfigHash` (stable SHA-256 hash of canonicalized `runConfig`)
  - `runConfigSummary` (human-readable ordered summary)

Notes:
- Split-job merges write aggregated report timing where parsing/OCR are summed from child jobs and merge overhead is recorded in `timing.checkpoints.merge_seconds`.
- Writer location for this JSON is always run-root level: `write_report(report, out, file_path.stem)`.

### 3.2 Cross-run CSV (`performance_history.csv`)

CSV acts as the long-term unified event log for:

- stage/import rows (`run_category=stage_import`; collector may classify some as `labelstudio_import` based on run path)
- benchmark/eval rows (`run_category=benchmark_eval` or `benchmark_prediction`)

For stage rows, key analytics columns include:

- runtime: `total_seconds`, `parsing_seconds`, `writing_seconds`, `ocr_seconds`
- workload: `recipes`, `tips`, `tip_candidates`, `topic_candidates`, `total_units`
- normalized metrics: `per_recipe_seconds`, `per_unit_seconds`, etc.
- topic coverage fields: `standalone_*`
- output size: `output_files`, `output_bytes`
- derived descriptors: `knowledge_share`, `knowledge_heavy`, dominant stage/checkpoint fields
- run context:
  - `run_config_hash` (grouping/filter key)
  - `run_config_summary` (table/display string)
  - `run_config_json` (serialized `runConfig` for full fidelity/tooltips/fallbacks)
  - explicit EPUB visibility columns:
    - `epub_extractor_requested`
    - `epub_extractor_effective`
    - `epub_auto_selected_score`
  - dashboard collector fallback: when `run_config_json` is empty, collector tries `report_path` JSON `runConfig`
  - stale-row signal: when a `report_path` reference is present but missing on disk, dashboard can emit a run-config warning

For benchmark rows, key columns include:

- `precision`, `recall`, `f1`
- `gold_total`, `gold_matched`, `pred_total`
- `recipes` (from pred-run manifest `recipe_count` when available; fallback from processed report when available)
- `supported_precision`, `supported_recall`
- boundary columns: `boundary_correct`, `boundary_over`, `boundary_under`, `boundary_partial`
- `eval_scope`, `source_file` (stored in `file_name`)
- run context columns: `run_config_hash`, `run_config_summary`, `run_config_json`

Schema migration support exists: old CSV files missing newer columns are auto-expanded during append.

### 3.3 Dashboard artifacts

Dashboard collector reads:

1. `output_root/.history/performance_history.csv` (primary unless `--scan-reports`)
2. `output_root/<timestamp>/*.excel_import_report.json` (fallback/supplement)
3. `golden_root/eval-vs-pipeline/*/eval_report.json` and `golden_root/*/eval_report.json` (benchmark scans)

Collector enrichment:

- optional `coverage.json` adds `extracted_chars`, `chunked_chars`, `coverage_ratio`
- optional `manifest.json` adds `task_count`, `source_file`, `recipe_count`
- benchmark collector also checks `prediction-run/{coverage.json,manifest.json}` and can enrich `importer_name`, `run_config`, `run_config_hash`, `run_config_summary`, and `processed_report_path` when present
  - benchmark `recipes` prefers manifest `recipe_count`; if missing, collector can backfill from `processed_report_path` -> report `totalRecipes`

Collector exclusions/filters:

- skips hidden output directories (including `.history`, `.job_parts`)
- skips `prediction-run` eval directories in JSON benchmark scan
- skips benchmark artifacts that match pytest temp eval paths (for example `.../pytest-46/test_foo0/eval`) so local Python test runs do not pollute dashboard benchmark history
- optional `--since-days` date cutoff

## 4) Command behavior (current)

### `cookimport stage`

- Creates run folder with timestamp format: `YYYY-MM-DD_HH.MM.SS`.
- Processes files in parallel by default (`--workers` default is `7`, not `1`).
- Supports split-job planning and merge for large PDF/EPUB.
- At end of run:
  - prints formatted per-file perf summaries/outlier hints
  - appends rows to history CSV

### `cookimport perf-report`

- Summarizes one run (`--run-dir` or auto-detect latest under `--out-dir`).
- Optionally appends to CSV (`--write-csv/--no-csv`).

### `cookimport benchmark-csv-backfill`

- One-off repair command for historical benchmark CSV rows.
- Reads `performance_history.csv` and patches benchmark rows missing `recipes` / `report_path` / `file_name`.
- Resolves benchmark artifact roots from each row `run_dir`.
- Backfill source order:
  - existing CSV `report_path` -> report `totalRecipes` (for missing `recipes`)
  - benchmark manifests (`prediction-run/manifest.json`, `run_dir/manifest.json`, `per_item/*/pred_run/manifest.json`)
  - manifest `recipe_count` first, then manifest `processed_report_path` -> report `totalRecipes`
- For bench-suite `run_dir/per_item/*/pred_run/manifest.json` cases, recovered `recipes` is sum of per-item `recipe_count` values.
- Repair is additive: only missing CSV fields are filled, existing values are not overwritten.
- Writes changes in place (or preview only with `--dry-run`).

### `cookimport stats-dashboard`

- Collects stage + benchmark analytics and writes static dashboard files.
- `--scan-reports` can force direct JSON report scanning in addition to CSV path.
- Throughput view is organized in two ways:
  - run/date trend + recent-runs table across all stage/import rows
  - file trend selector/table (grouped by file name) to track one file's processing speed over time
  - stage/import tables include importer and run-config summary columns

## 5) Known caveats / sharp edges (important)

### A) `perf-report` timestamp auto-detect now supports both folder styles

- `resolve_run_dir` in `cookimport/analytics/perf_report.py` now accepts both:
  - `YYYY-MM-DD_HH.MM.SS` (current stage format)
  - `YYYY-MM-DD-HH-MM-SS` (legacy format)
- The latest run is chosen by parsed datetime, not string sort.
- Regression anchors:
  - `tests/test_perf_report.py::test_resolve_run_dir_detects_stage_timestamp_format`
  - `tests/test_perf_report.py::test_resolve_run_dir_accepts_legacy_timestamp_format`

### B) Stage history append now follows actual stage output root

- `cookimport stage --out <custom_root>` now appends to `<custom_root>/.history/performance_history.csv`.
- This keeps `perf-report` and `stats-dashboard --output-root <custom_root>` aligned with the run artifacts users just produced.
- Regression anchor:
  - `tests/test_cli_output_structure.py::test_stage_writes_to_custom_output`

### C) CSV and JSON collector date handling is tolerant but not fully normalized

- Collector supports both ISO timestamps and folder-style timestamps.
- Mixed/malformed timestamps are included with warnings rather than hard failure.
- Good for resilience, but can produce confusing order/filter behavior in edge datasets.

### D) Dashboard is static + local only

- No server-side persistence, no auth/multi-user semantics, no remote aggregation.
- This is intentional for this project, but important when considering future growth.

## 6) Practical debugging runbook

1. Confirm per-run report exists:
- `<output_root>/<timestamp>/<slug>.excel_import_report.json` (default `<output_root>` is `data/output`)

2. Confirm history append happened:
- `<output_root>/.history/performance_history.csv`

3. If dashboard seems empty:
- run `cookimport stats-dashboard --scan-reports`
- inspect warnings printed by collector
- verify benchmark eval files exist under `data/golden/eval-vs-pipeline/*/eval_report.json`

4. If `perf-report` cannot auto-find a run:
- provide explicit `--run-dir <output_root>/<timestamp>`
- verify folder names match one of the supported timestamp formats above

## 7) Why this design exists

- JSON per-run report preserves detailed per-file telemetry next to artifacts.
- CSV history gives cheap append-only longitudinal tracking and easy tooling compatibility.
- Static dashboard keeps dependencies low, local/offline friendly, and deterministic.
- Unified CSV for stage + benchmark gives one place for trend analysis across ingestion quality and throughput.

## 8) If changing analytics, update these places together

1. `cookimport/core/models.py` (`ConversionReport` fields/aliases)
2. `cookimport/analytics/perf_report.py` (row extraction + CSV schema)
3. `cookimport/analytics/dashboard_schema.py` (dashboard contract)
4. `cookimport/analytics/dashboard_collect.py` (collector logic)
5. `cookimport/analytics/dashboard_render.py` (UI fields)
6. `tests/test_stats_dashboard.py` (coverage for schema/collector/renderer/CSV compatibility)
7. this README

## 9) EPUB auto metadata propagation contract (Merged 2026-02-20_14.40.00)

Extractor auto metadata is only reliable when all four layers are wired together:

1. Stage orchestration (`cookimport/cli.py`)
- Resolve `auto` once per file.
- Persist per-file rationale payload.
- Pass effective extractor metadata through worker/split-merge write paths.

2. Report writers
- `cookimport/cli_worker.py`, `cookimport/cli.py:_merge_split_jobs`, and `cookimport/labelstudio/ingest.py:_write_processed_outputs` should populate:
  - `epubAutoSelection`
  - `epubAutoSelectedScore`

3. History CSV (`cookimport/analytics/perf_report.py`)
- Persist explicit columns:
  - `epub_extractor_requested`
  - `epub_extractor_effective`
  - `epub_auto_selected_score`

4. Dashboard schema/collector/rendering
- Map these fields directly into stage records and UI filters/tables.
- Do not rely on inference from nested run-config blobs.

If one layer is skipped, extractor visibility drifts across stage report JSON, CSV history, and dashboard tables.

## 10) Merged Task Spec (2026-02-23 docs/tasks archival batch)

### 10.1 2026-02-12 lifetime stats dashboard implementation record (`docs/tasks/I1.1-STATS-DASH.md`)

Durable dashboard contract:
- `cookimport stats-dashboard` is read-only over existing metric surfaces and writes static artifacts only under `--out-dir`.
- Architecture remains collect -> schema -> render (`dashboard_collect.py`, `dashboard_schema.py`, `dashboard_render.py`).
- Preferred data source is compact metrics surfaces (CSV + eval JSON), with report scanning as fallback.

Data-shape rules that should stay explicit:
- Missing numeric values remain `None` (not zero).
- Category separation (`stage_import`, `labelstudio_import`, `benchmark_eval`, `benchmark_prediction`) prevents double counting.
- Static output keeps inline JSON fallback for `file://` browser compatibility.

Known footguns preserved:
- Mixed timestamp formats exist in historical artifacts; collector must remain tolerant.
- `.job_parts` and `prediction-run` eval dirs should stay excluded from benchmark-history surfaces unless explicitly requested.
