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
- Artifact: `data/.history/performance_history.csv` (unless you explicitly call helpers with another root)
- Producer: `cookimport/analytics/perf_report.py` via:
  - auto-append at end of `cookimport stage`
  - manual `cookimport perf-report`
  - benchmark eval append paths (`append_benchmark_csv`)

3. Lifetime static dashboard
- Artifacts:
  - `data/.history/dashboard/index.html`
  - `data/.history/dashboard/assets/dashboard_data.json`
  - `data/.history/dashboard/assets/dashboard.js`
  - `data/.history/dashboard/assets/style.css`
  - `data/.history/dashboard/all-method-benchmark/index.html` (always generated run index)
  - `data/.history/dashboard/all-method-benchmark/all-method-benchmark-run__<run_timestamp>.html` (one run summary page per all-method sweep)
  - `data/.history/dashboard/all-method-benchmark/all-method-benchmark__<run_timestamp>__<source_slug>.html` (one per grouped per-book all-method sweep)
- Producer: `cookimport stats-dashboard`
- Collector: `cookimport/analytics/dashboard_collect.py`
- Data contract: `cookimport/analytics/dashboard_schema.py`
- Current schema version: `9` (adds benchmark `gold_recipe_headers` enrichment for recipe-coverage chart scaling)
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
- `recipes` (from pred-run manifest `recipe_count` when available; fallback from processed report when available; fallback to eval `recipe_counts.predicted_recipe_count` when manifest/report paths are absent)
- `gold_recipe_headers` (from eval `recipe_counts.gold_recipe_headers`, with per-label `RECIPE_TITLE` fallback when needed)
- `supported_precision`, `supported_recall`
- boundary columns: `boundary_correct`, `boundary_over`, `boundary_under`, `boundary_partial`
- `eval_scope`, `source_file` (stored in `file_name`)
- run context columns: `run_config_hash`, `run_config_summary`, `run_config_json`
- benchmark runtime columns:
  - stage-aligned: `total_seconds`, `parsing_seconds`, `writing_seconds`, `ocr_seconds`
  - benchmark-specific: `benchmark_prediction_seconds`, `benchmark_evaluation_seconds`, `benchmark_artifact_write_seconds`, `benchmark_history_append_seconds`, `benchmark_total_seconds`
  - eval checkpoints: `benchmark_prediction_load_seconds`, `benchmark_gold_load_seconds`, `benchmark_evaluate_seconds`

Benchmark timing precedence for CSV append (`append_benchmark_csv`) is:
1. explicit `timing=...` argument (from benchmark orchestration),
2. `processed_report_path` report `timing` payload fallback,
3. blank timing fields.

Schema migration support exists: old CSV files missing newer columns are auto-expanded during append.
CSV append writes (`append_history_csv`, `append_benchmark_csv`) now hold an inter-process file lock across schema/header/row writes so parallel benchmark configs cannot corrupt shared history files.

### 3.3 Dashboard artifacts

Dashboard collector reads:

1. `output_root/.history/performance_history.csv` (primary unless `--scan-reports`)
2. `output_root/<timestamp>/*.excel_import_report.json` (fallback/supplement)
3. `golden_root/benchmark-vs-golden/*/eval_report.json` and `golden_root/*/eval_report.json` (benchmark scans)
   - includes nested all-method config eval reports under paths like
     `golden_root/benchmark-vs-golden/<run_ts>/all-method-benchmark/<source_slug>/config_*/eval_report.json`

Collector enrichment:

- optional `coverage.json` adds `extracted_chars`, `chunked_chars`, `coverage_ratio`
- optional `manifest.json` adds `task_count`, `source_file`, `recipe_count`
- benchmark collector also checks `prediction-run/{coverage.json,manifest.json}` and can enrich `importer_name`, `run_config`, `run_config_hash`, `run_config_summary`, and `processed_report_path` when present
  - benchmark `recipes` prefers manifest `recipe_count`; if missing, collector can backfill from `processed_report_path` -> report `totalRecipes`; final fallback is eval `recipe_counts.predicted_recipe_count`

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
  - auto-refreshes dashboard artifacts at `<out parent>/.history/dashboard` (best effort)

### `cookimport perf-report`

- Summarizes one run (`--run-dir` or auto-detect latest under `--out-dir`).
- Optionally appends to CSV (`--write-csv/--no-csv`).
- When CSV append runs, dashboard refresh is triggered for the same history root.

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
- When rows are written (`--dry-run` off + updates found), dashboard refresh is triggered for that history root.

### `cookimport stats-dashboard`

- Collects stage + benchmark analytics and writes static dashboard files.
- `--scan-reports` can force direct JSON report scanning in addition to CSV path.
- Benchmark-row appenders (`labelstudio-eval`, `labelstudio-benchmark`, `bench run`) now auto-run this refresh flow after successful CSV writes; all-method internals batch refresh to once per source.
- Always writes an in-site all-method benchmark run index page at `data/.history/dashboard/all-method-benchmark/index.html` and, when grouped rows exist, writes run summary pages plus per-book detail pages from benchmark CSV rows whose `run_dir`/`artifact_dir` path includes `all-method-benchmark/<source_slug>/config_*`.
- Run summary pages aggregate config metrics across all book jobs in one run folder, and now include a compact stats summary + per-metric bar charts (one bar per aggregated config), per-config radar/web charts, plus per-cookbook average bar/radar sections (book metrics averaged across all configs for that source) before the ranked aggregate table and per-book drilldown links.
- All-method run-summary/detail pages now include sticky quick-nav links plus collapsible section grouping so long chart/table pages are easier to scan.
- All-method detail pages include a compact stats-only summary table, per-metric bar charts (one bar per run/config), and per-config radar/web charts ahead of the ranked config table.
- All-method standalone chart scaling contract: score metrics (`strict_precision`, `strict_recall`, `strict_f1`, `practical_f1`) render on fixed 0-100% axes (`1.0 == 100%`), and `recipes` now renders as `% identified` against golden recipe headers (`recipe_counts.gold_recipe_headers`) with the same fixed 0-100% axis.
- Ranked all-method detail tables expose explicit dimension columns (`Extractor`, `Parser`, `Skip HF`, `Preprocess`) sourced from run config with config-name fallback.
- Dashboard landing view now leads with a KPI card strip derived from filtered data (`Stage rows`, `Median sec/recipe`, `Mean strict/practical`, `Latest run`).
- Throughput view is organized in two ways:
  - run/date trend + recent-runs table across all stage/import rows
  - file trend selector/table (grouped by file name) to track one file's processing speed over time
  - stage/import tables include importer and run-config summary columns
- Throughput run/date chart supports outlier-aware display controls (`Clamp p95` default, plus `Raw` and `Log` modes).
- Benchmark trend chart now renders strict precision and strict recall on one shared-axis SVG line chart (with legend) instead of stacked charts.
- Dashboard run-list tables now use preview-collapse semantics (`Show all` / `Show fewer`) rather than hiding every row in collapsed state.

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

### E) `dashboard.js` template escaping can blank the whole dashboard

- `cookimport/analytics/dashboard_render.py` builds JS from Python template strings.
- In run-config tooltip assembly (`runConfigCell` path), `\\n` must stay double-escaped in Python so generated JS contains a literal `\n`, not a raw newline inside a quoted string.
- If this regresses, browsers fail to execute `dashboard.js` and the dashboard appears empty even though data artifacts exist.

## 6) Practical debugging runbook

1. Confirm per-run report exists:
- `<output_root>/<timestamp>/<slug>.excel_import_report.json` (default `<output_root>` is `data/output`)

2. Confirm history append happened:
- `<output_root parent>/.history/performance_history.csv`

3. If dashboard seems empty:
- run `cookimport stats-dashboard --scan-reports`
- inspect warnings printed by collector
- verify benchmark eval files exist under `data/golden/benchmark-vs-golden/*/eval_report.json`

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

## 11) Merged Understandings Batch (2026-02-24 cleanup)

### 11.1 All-method dashboard grouping + page hierarchy contract

Merged sources:
- `docs/understandings/2026-02-23_16.13.59-dashboard-all-method-page-grouping.md`
- `docs/understandings/2026-02-23_22.06.13-dashboard-all-method-root-page-contract.md`
- `docs/understandings/2026-02-24_00.40.56-all-method-run-level-dashboard-hierarchy.md`

Durable dashboard contract:
- Grouping remains CSV-first and keyed by benchmark artifact paths containing `all-method-benchmark/<source_slug>/config_*`.
- Dashboard always writes `all-method-benchmark/index.html` under the dashboard root, even when grouped rows are absent.
- Hierarchy is now explicit:
  - root all-method index: `all-method-benchmark/index.html` (run rows),
  - run summary pages: `all-method-benchmark/all-method-benchmark-run__<run_timestamp>.html`,
  - per-book detail pages: `all-method-benchmark/all-method-benchmark__<run_timestamp>__<source_slug>.html`.
- Run-level config aggregation key is `run_config_hash` when available, with config-slug fallback for historical rows.

### 11.2 Recursive benchmark eval discovery contract

Merged source:
- `docs/understandings/2026-02-23_22.15.18-dashboard-benchmark-recursive-eval-scan.md`

Durable collector rule:
- Benchmark collector must recurse for `eval_report.json` under golden roots so nested all-method config reports are discovered.
- Recursive scan keeps exclusions for `prediction-run` and pytest temp paths to avoid duplicate/non-user rows.
- Nested config eval rows should map to nearest timestamped parent folder as `run_timestamp` for stable sorting/grouping.

### 11.3 Detail-page content contract (quick-scan before deep table)

Merged sources:
- `docs/understandings/2026-02-23_22.21.16-all-method-detail-summary-bars.md`
- `docs/understandings/2026-02-23_22.26.07-all-method-dimension-columns.md`

Durable rendering rules:
- Each all-method detail page starts with compact stats (`N`, `Min`, `Median`, `Mean`, `Max`) and per-metric run bars before ranked table.
- Ranked rows expose explicit config-dimension columns (`Extractor`, `Parser`, `Skip HF`, `Preprocess`).
- Dimension values come from run-config fields first, with config-slug parsing fallback for historical rows.
- For non-unstructured extractors, parser/skip/preprocess columns should render `-` to avoid implying inactive knobs.

## 12) Merged Task Specs (2026-02-24 docs/tasks archival batch)

### 12.1 2026-02-24_00.36.38 run-level all-method dashboard aggregation

Task source:
- `docs/tasks/2026-02-24_00.36.38-all-method-run-level-dashboard-aggregation.md`

Current analytics contract clarified by task implementation:
- Dashboard hierarchy is run-first, then per-book drilldown:
  - `all-method-benchmark/index.html` (run index),
  - `all-method-benchmark/all-method-benchmark-run__<run_timestamp>.html` (run summary),
  - `all-method-benchmark/all-method-benchmark__<run_timestamp>__<source_slug>.html` (per-book detail).
- Run-level config aggregation groups by `run_config_hash` when available, with config-name fallback for older rows.
- Run-level ranking prioritizes breadth + quality:
  1. books covered,
  2. practical mean,
  3. strict mean,
  4. win count,
  5. strict precision/recall tie-breakers.

### 12.2 2026-02-24_08.30.36 benchmark timing telemetry foundations

Task source:
- `docs/tasks/2026-02-24_08.30.36-benchmark-timing-telemetry-and-runtime-analyzer-foundation.md`

Current telemetry contract clarified by task implementation:
- Benchmark timing is additive across existing artifacts:
  - prediction `manifest.json`,
  - benchmark `run_manifest.json`,
  - `eval_report.json`,
  - all-method per-source and multi-source reports,
  - benchmark rows in `performance_history.csv`.
- CSV timing precedence remains:
  1. explicit timing passed to `append_benchmark_csv(...)`,
  2. processed report `timing` fallback,
  3. blank timing fields.
- New benchmark-specific CSV timing fields include:
  - `benchmark_prediction_seconds`,
  - `benchmark_evaluation_seconds`,
  - `benchmark_artifact_write_seconds`,
  - `benchmark_history_append_seconds`,
  - `benchmark_total_seconds`,
  - plus eval checkpoint columns (`benchmark_prediction_load_seconds`, `benchmark_gold_load_seconds`, `benchmark_evaluate_seconds`).
- Foundation helper exists for future coarse analysis:
  - `cookimport/analytics/benchmark_timing.py:collect_all_method_timing_summary(...)`.
- Important scope boundary: no analyzer CLI command ships in this task; only stable telemetry data surfaces and helper APIs were added.

## 13) Merged Understandings Batch (2026-02-24 dashboard + all-method refresh)

### 13.1 All-method page placement and link contract

Merged discoveries (chronological):
- `2026-02-24_14.20.21-dashboard-all-method-subfolder-output`

Durable rules:
- All-method page location is renderer-owned (`_render_all_method_pages(...)`), not collector/schema-owned.
- If page roots change, update all three together:
  1. renderer write targets,
  2. main index links into all-method pages,
  3. relative nav/style links inside generated all-method pages.

### 13.2 All-method charting contract (run summary + detail)

Merged discoveries (chronological):
- `2026-02-24_14.21.59-all-method-run-summary-charts`
- `2026-02-24_14.31.37-all-method-radar-web-charts`
- `2026-02-24_14.36.55-all-method-score-metrics-fixed-percent-scale`
- `2026-02-24_14.49.43-all-method-recipes-gold-normalization`
- `2026-02-24_20.49.47-all-method-run-summary-cookbook-average-charts`

Durable rules:
- Run-summary pages should reuse the same metric bar component family as per-book detail pages for visual parity.
- Run-summary can render config-level bars/radar directly from aggregated config means; no collector/schema changes needed.
- Score metrics are fixed-scale ratios (`1.0 == 100%`) in bar and radar charts; do not rescale to local max.
- Recipes metric is `% identified` against golden recipe headers (`recipe_counts.gold_recipe_headers`), not span totals.
- Per-cookbook run-summary charts use per-book averages across all configs, not winner-only rows.

### 13.3 Dashboard refresh and collapse ownership contract

Merged discoveries (chronological):
- `2026-02-24_14.25.28-all-method-dashboard-refresh-batching`
- `2026-02-24_14.28.22-dashboard-table-collapse-flow`
- `2026-02-24_21.16.27-dashboard-renderer-ux-refresh-template-contract`

Durable rules:
- All-method benchmark refresh should be batched per source (or once at multi-source completion in parallel source mode), not once per config.
- Run-list collapse behavior lives in renderer JS template helpers (`renderRowsWithCollapse`/`renderTableCollapseControl`), not static HTML shells.
- Global collapse controls belong outside rerendered table regions and should trigger one `renderAll()` after state update.
- UX refreshes should stay renderer-template-first and preserve existing section IDs used by JS hooks.

### 13.4 Readability and metric interpretation guardrails

Merged discoveries (chronological):
- `2026-02-24_20.57.19-dashboard-ux-readability-baseline`
- `2026-02-24_21.48.23-per-label-recipe-title-zero-strict-vs-overlap`
- `2026-02-24_22.29.33-dashboard-metrics-cheatsheet`

Durable rules:
- Dashboard snapshot cards are filter-scoped summaries and should remain the first high-signal entrypoint.
- Throughput `sec/recipe` and benchmark strict/practical metrics answer different questions and should stay explicitly separated.
- Strict per-label zeros (for example `RECIPE_TITLE`) can coexist with high practical overlap when predicted ranges are much wider than gold; treat this as granularity localization mismatch unless other diagnostics disagree.

## 14) 2026-02-24_22.44.09 docs/tasks archival merge batch (analytics)

### 14.1 Archived source tasks merged into this section

- `docs/tasks/2026-02-24_14.20.21-dashboard-all-method-pages-subfolder.md`
- `docs/tasks/2026-02-24_14.22.37-all-method-run-summary-graphs.md`
- `docs/tasks/2026-02-24_14.28.22-dashboard-collapsible-run-lists.md`
- `docs/tasks/2026-02-24_14.28.44-all-method-web-radar-charts.md`
- `docs/tasks/2026-02-24_14.28.56-auto-dashboard-refresh-on-history-writes.md`
- `docs/tasks/2026-02-24_14.36.31-all-method-score-axis-100pct.md`
- `docs/tasks/2026-02-24_14.49.43-all-method-recipes-vs-gold-percent.md`
- `docs/tasks/2026-02-24_15.17.13-all-method-run-summary-per-cookbook-graphs.md`
- `docs/tasks/2026-02-24_20.57.19-dashboard-readability-information-density-refresh.md`

### 14.2 Current all-method page structure and chart contracts

Durable rules preserved from the merged task set:

- All-method pages are generated under `data/.history/dashboard/all-method-benchmark/`.
- The root dashboard links into `all-method-benchmark/index.html`; legacy flat root files are not emitted.
- Run-summary pages include per-config bar charts, per-config radar charts, and per-cookbook average bar/radar sections.
- Chart scaling semantics are mixed by metric type:
  - score metrics (`strict precision`, `strict recall`, `strict f1`, `practical f1`) are fixed to `0..100%` (`1.0 == 100%`),
  - recipes are percent identified against golden recipe-header totals (`recipe_counts.gold_recipe_headers`), clamped to 100%.
- Renderer reuse is intentional: run-summary and detail charts share the same metric chart component/CSS family.

### 14.3 Dashboard refresh and table-behavior ownership

- CSV writers that append benchmark/stage/perf rows are expected to trigger best-effort dashboard regeneration.
- Refresh scope is intentionally batched where parallel all-method writes occur (not per config) to avoid dashboard writer contention.
- Run-table collapse UX is JS-template-owned (`assets/dashboard.js`), with centralized preview-row defaults and global show/collapse controls.

### 14.4 Readability redesign boundaries (implemented)

From the readability/info-density ExecPlan merge:

- The redesign remained renderer-first and static; no server or SPA migration.
- CSV/schema contracts remained unchanged (`performance_history.csv` stays source-of-truth).
- Main dashboard now emphasizes quick-scan hierarchy (KPI cards, clearer control grouping, outlier-aware throughput views, progressive disclosure in run tables).
- All-method standalone pages use navigation/compression patterns (`quick-nav`, section grouping/collapse) without adding new dashboard runtime dependencies.
