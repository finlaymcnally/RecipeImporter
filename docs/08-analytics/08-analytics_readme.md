---
summary: "Comprehensive analytics reference: performance history, dashboard data model, benchmark metrics, and historical optimization context."
read_when:
  - When changing performance reporting, CSV history writes, or stats-dashboard behavior
  - When debugging missing or inconsistent analytics artifacts under data/output or data/golden
  - When deciding whether prior performance work was attempted already and what remains unresolved
---

# 08 Analytics README

This document consolidates the prior analytics docs in `docs/08-analytics/` and reconciles them with current code.

Scope: analytics/reporting only (what is emitted, where it is emitted, how it is consumed, and known quality gaps).

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
- Current schema version: `6` (adds explicit `run_config_hash` / `run_config_summary` fields on stage + benchmark records)
- Renderer: `cookimport/analytics/dashboard_render.py`
- `index.html` now embeds an inline copy of the same dashboard JSON so the dashboard still works when opened via `file://` in browsers that block local `fetch()`.

## 2) Where code lives

Primary analytics code:

- `cookimport/analytics/perf_report.py`
- `cookimport/analytics/dashboard_collect.py`
- `cookimport/analytics/dashboard_schema.py`
- `cookimport/analytics/dashboard_render.py`

Primary CLI integration:

- `cookimport/cli.py:1444` `stage(...)`
- `cookimport/cli.py:1996` `perf_report(...)`
- `cookimport/cli.py:2075` `stats_dashboard(...)`
- `cookimport/cli.py:2320+` benchmark eval flows appending benchmark rows to history CSV

Related producers of report content:

- `cookimport/cli_worker.py` (`stage_one_file`, `stage_pdf_job`, `stage_epub_job`)
- `cookimport/cli.py:1261` `_merge_split_jobs(...)` for merged PDF/EPUB split jobs
- `cookimport/staging/writer.py:671` `write_report(...)`
- `cookimport/core/timing.py` timing data structure/checkpoint helper
- `cookimport/core/models.py:506` `ConversionReport` schema

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

## 5) Historical timeline and prior attempts (preserved)

This section intentionally keeps prior context to avoid repeating cycles.

### 2026-02-01 performance strategy + implementation push

Sources merged here:
- prior `SPEED_UP.md` (ExecPlan + implementation log)
- prior `resource_usage_report.md` (resource bottleneck analysis + recommendations)

What was proposed:

1. Add runtime observability first (timing fields/checkpoints).
2. Add explicit OCR device control (`auto|cpu|cuda|mps`).
3. Add OCR batching (`--ocr-batch-size`).
4. Add warm-model path (`--warm-models`).
5. Add multi-process staging.
6. Add tests/docs around this.

What code now confirms as implemented:

- CLI options for OCR device, OCR batch size, warming, workers, and split-worker controls exist in `stage` command.
- Per-file `timing` and checkpoint data are written into conversion reports.
- Parallel processing and split-job merge flows are active.
- Stats dashboard + analytics tests exist (`tests/test_stats_dashboard.py`).

What to retain from old analysis even if wording is stale:

- RAM is still the limiting factor as worker count rises.
- OCR acceleration can shift bottlenecks from OCR to parsing/writing.
- Batch-size and worker-count tuning should be empirical per machine/input mix.

What became outdated in older docs:

- Claim that staging is sequential/single-threaded is no longer true.
- Claim that OCR device handling is entirely unmanaged is no longer true.

### 2026-02-12 metrics observability map

Source merged here:
- prior `2026-02-12_11.31.47-metrics-observability-map.md`

Status:

- The three-surface metrics map (per-run report, history CSV, Label Studio eval artifacts) is still accurate.
- Split merge timing note (`timing.checkpoints.merge_seconds`) is still accurate.

### 2026-02-15_22.07.37 analytics metrics flow and mismatch map

Merged source file:
- `2026-02-15_22.07.37-analytics-metrics-flow-and-mismatches.md` (formerly in `docs/understandings`)

Preserved findings:
- Stage writes per-file reports at `<run_root>/<slug>.excel_import_report.json`, then derives perf summary rows and appends history CSV.
- Stats dashboard primarily reads `data/output/.history/performance_history.csv`, then supplements/falls back to report JSON scan.
- That investigation identified two mismatches that were later fixed:
  - `perf_report.resolve_run_dir()` now accepts both hyphen-style legacy folders and underscore/dot stage folders.
  - Stage history append now targets `history_path(<actual_stage_output_root>)`, not `history_path(DEFAULT_OUTPUT)`.

### 2026-02-15_23.17.17 file:// dashboard data-loading fallback

Merged source file:
- `2026-02-15_23.17.17-stats-dashboard-file-scheme-fetch-fallback.md` (formerly in `docs/understandings`)

Problem captured:
- Browser local-file mode (`file://`) can block JS `fetch("assets/dashboard_data.json")`, making dashboard appear broken even when artifacts were written correctly.

Decision captured:
- Keep writing `assets/dashboard_data.json` for normal hosting/inspection.
- Also embed the same JSON payload inline in `index.html`.
- Dashboard JS should read inline JSON first, then fall back to fetch only when inline payload is missing/invalid.

### 2026-02-15_23.36.55 benchmark metadata merge by artifact directory

Merged source file:
- `2026-02-15_23.36.55-benchmark-dashboard-metadata-flow.md` (formerly in `docs/understandings`)

Problem captured:
- Benchmark enrichment metadata (`manifest.json`, `coverage.json`) can live under `<eval_dir>/prediction-run/`, not only eval root.
- CSV and JSON benchmark rows can describe the same eval run with timestamp differences, creating duplicate rows when merged by timestamp.

Decision captured:
- Probe both eval root and `prediction-run/` for benchmark enrichment.
- Merge CSV + JSON benchmark rows by eval artifact directory and fill missing fields instead of appending duplicates.

### 2026-02-15_23.50.42 throughput view split into run/date + file-trend perspectives

Merged source:
- `docs/tasks/2026-02-15_23.50.42 - dashboard-throughput-run-and-file-views.md`

Problem captured:
- Existing throughput section made it hard to answer both run-over-run trend questions and per-file trend questions.

Decision captured:
- Keep run/date view (`Recent Runs` table + trend) and add a file-focused trend/table view for one selected file over time.
- Scope explicitly kept renderer-only (no collector/schema changes for this step).

Task verification/evidence preserved:
- `. .venv/bin/activate && pytest -q tests/test_stats_dashboard.py`
- recorded result: `24 passed`.

### 2026-02-15_23.51.02 throughput organization rule clarified

Merged source file:
- `2026-02-15_23.51.02-dashboard-throughput-run-vs-file-organization.md` (formerly in `docs/understandings`)

Durable rule:
- Throughput should continue exposing both views backed by the same stage records:
  - run/date timeline across all records (newest-first table sorting),
  - single-file trend over time grouped by `StageRecord.file_name` (chronological trend order).

### 2026-02-16_00.10.16 mixed timestamp sort fix

Merged source:
- `docs/tasks/2026-02-16_00.10.16 - fix-dashboard-benchmark-time-sort.md`
- `2026-02-16_00.10.16-dashboard-mixed-timestamp-sort-order.md` (formerly in `docs/understandings`)

Problem captured:
- Lexicographic sort broke ordering when datasets mixed `YYYY-MM-DDTHH:MM:SS` and `YYYY-MM-DD_HH.MM.SS`.

Decision captured:
- Use parsed timestamp ordering in both collector (latest timestamp selection + sort keys) and renderer JS (recent benchmark/run tables).
- Keep unparseable rows visible and place them last where possible.

Task verification/evidence preserved:
- `. .venv/bin/activate && pytest -q tests/test_stats_dashboard.py` with mixed-format timestamp regressions (task records `26 passed`).
- `cookimport stats-dashboard` run also recorded as successful artifact regeneration.

### 2026-02-16_00.13.03 per-file history lists experiment (later superseded)

Merged source:
- `docs/tasks/2026-02-16_00.13.03 - dashboard-per-file-import-history-lists.md`
- `2026-02-16_00.12.54-dashboard-throughput-per-file-history-lists.md` (formerly in `docs/understandings`)

What was tried:
- Replaced selected-file trend control with always-visible `Per-File History Lists` (one table per file).

Why this matters historically:
- This was a real implemented direction (with tests passing), but it was later judged too heavy and replaced.

Task verification/evidence preserved:
- task records `pytest -q tests/test_stats_dashboard.py` passing (`26 passed`).

### 2026-02-16_00.19.42 stage/import run-config context added to throughput tables

Merged source:
- `docs/tasks/2026-02-16_00.19.42 - dashboard-import-run-config-columns.md`
- `2026-02-16_00.19.42-stage-run-config-flow-into-dashboard.md` (formerly in `docs/understandings`)

Problem captured:
- Benchmark rows showed run-config summaries, stage/import rows did not.

Decision captured:
- Persist stage `runConfig` into CSV (`run_config_json`) during history writes.
- Collect into stage records and render `Importer` + `Run Config` columns in run/date and file-trend tables.
- Reuse benchmark-style summary key ordering/formatting for consistency.

Task verification/evidence preserved:
- task records `pytest -q tests/test_stats_dashboard.py` passing (`27 passed`).

### 2026-02-16_00.25.07 selector-based file trend restored (reversal of 00.13.03)

Merged source:
- `docs/tasks/2026-02-16_00.25.07 - dashboard-file-trend-selector-restore.md`
- `2026-02-16_00.25.07-dashboard-file-trend-selector-preferred.md` (formerly in `docs/understandings`)

Reason for reversal:
- always-visible per-file list layout was considered visually heavy and slower to scan.

Final decision captured:
- Restore single dropdown-driven file trend UI.
- Keep run-config columns/summaries introduced at `00.19.42`.

Task verification/evidence preserved:
- task records `pytest -q tests/test_stats_dashboard.py` passing (`27 passed`).

Anti-loop note:
- Per-file card/list layout is a known attempted branch; do not reintroduce it without a clear UX reason.

### 2026-02-16_00.26.20 pytest temp benchmark artifact filtering

Merged source:
- `docs/tasks/2026-02-16_00.26.20 - dashboard-ignore-pytest-benchmark-artifacts.md`
- `2026-02-16_00.26.20-dashboard-ignore-pytest-benchmark-artifacts.md` (formerly in `docs/understandings`)

Problem captured:
- `Recent Benchmarks` could include local pytest temp rows (for example `pytest-46/test_.../eval`), polluting user-facing history.

Decision captured:
- Add narrow pytest-path detector in benchmark collectors and skip matching temp artifact rows in both CSV and JSON collection paths.

Task verification/evidence preserved:
- targeted filter test: `1 passed, 27 deselected`.
- full suite after change: `28 passed`.

### 2026-02-16_10.37.22 report-path run-config backfill for historical stage rows

Merged source:
- `docs/tasks/2026-02-16_10.37.22 - dashboard-stage-run-config-backfill-from-report-path.md`
- `2026-02-16_10.37.22-stage-run-config-csv-backfill-rule.md` (formerly in `docs/understandings`)

Problem captured:
- Older CSV rows often have empty `run_config_json`, leaving new Run Config columns blank.

Decision captured:
- Collector precedence:
  - use CSV `run_config_json` when present,
  - else best-effort read row `report_path` JSON and load `runConfig`.
- Keep fallback read-only and non-fatal when report files are missing.

Task verification/evidence preserved:
- task records `pytest -q tests/test_stats_dashboard.py` passing (`29 passed`).

### 2026-02-16_10.43.02 stale-row warning for missing report references

Merged source:
- `docs/tasks/2026-02-16_10.43.02 - dashboard-stale-run-config-warning.md`
- `2026-02-16_10.43.02-dashboard-stale-row-warning-rule.md` (formerly in `docs/understandings`)

Problem captured:
- Some rows had neither CSV config nor resolvable report path, and silently rendered as `-`.

Decision captured:
- Add `StageRecord.run_config_warning`.
- Mark rows as stale when `report_path` is referenced but missing.
- Keep stale rows visible and render explicit warning text in Run Config cell.

Task verification/evidence preserved:
- task records `pytest -q tests/test_stats_dashboard.py` passing (`31 passed`).

### 2026-02-16_10.51.07 consolidated rule: CSV-first run-config + report fallback + stale warning

Merged source:
- `docs/tasks/2026-02-16_10.51.07 - csv-robust-stage-run-config-and-stale-warning.md`
- `2026-02-16_10.51.07-stage-run-config-stale-warning-metadata.md` (formerly in `docs/understandings`)

Final durable rule from the `10.37 -> 10.43 -> 10.51` sequence:
1. Primary: use CSV `run_config_json`.
2. Fallback: parse `report_path` JSON `runConfig` when primary is empty and report still exists.
3. If both unavailable and report reference is stale: keep row and render warning (`[warn] missing report (stale row)`).

Task verification/evidence preserved:
- task records `pytest -q tests/test_stats_dashboard.py` passing (`31 passed`).

### 2026-02-16_10.56.36 benchmark recipe counts vs span metrics

Merged source file:
- `2026-02-16_10.56.36-benchmark-dashboard-recipe-count-vs-span-metrics.md` (formerly in `docs/understandings`)

Problem captured:
- Users were reading `Gold`/`Matched` columns in `Recent Benchmarks` as recipe totals; those are span-eval counts.

Decision captured:
- Keep span metrics (`Gold`, `Matched`) as the scoring surface.
- Add benchmark `Recipes` column sourced from CSV `recipes` and backfilled from `processed_report_path` (`totalRecipes`) when needed.

Anti-loop note:
- Perfect span scores do not imply perfect recipe-level parity in staged cookbook outputs; these are related but different contracts.

### 2026-02-16_11.33.17 benchmark recipes blank due to CSV append-path gaps

Merged source file:
- `2026-02-16_11.33.17-benchmark-recipes-blank-csv-path-gaps.md` (formerly in `docs/understandings`)

Problem captured:
- `Recent Benchmarks` reads from benchmark `recipes`, but only one command path initially persisted recipe counts consistently.
- `labelstudio-eval` and `bench run` could leave `recipes` blank even for new rows.

Final rule:
- Persist benchmark `recipes` in CSV for every benchmark CLI entrypoint (`labelstudio-benchmark`, `labelstudio-eval`, `bench run`).
- Use prediction-run manifest `recipe_count` first.
- Fall back to `processed_report_path` -> `totalRecipes` when manifest recipe count is unavailable.

### 2026-02-16_11.41.26 benchmark CSV backfill manifest resolution details

Merged source file:
- `2026-02-16_11.41.26-benchmark-csv-backfill-manifest-resolution.md` (formerly in `docs/understandings`)

Preserved recovery precedence/details:
- Resolve benchmark artifacts from CSV row `run_dir`.
- For single eval runs, check `run_dir/prediction-run/manifest.json` first (and `run_dir/manifest.json` fallback).
- For bench-suite runs, recover totals by summing `run_dir/per_item/*/pred_run/manifest.json` `recipe_count`.
- `recipes` precedence:
  1. manifest `recipe_count`
  2. fallback `processed_report_path` -> report `totalRecipes`
- Backfill scope remains limited to missing `recipes`, `report_path`, and `file_name`.

### 2026-02-16_12.09.36 run-settings propagation into analytics/dashboard

Merged source file:
- `2026-02-16_12.09.36-run-settings-config-propagation.md` (formerly in `docs/understandings`)

Durable analytics contract:
- `run_config_hash`, `run_config_summary`, and `run_config_json` must be persisted to history CSV for stage and benchmark rows.
- Dashboard collector prefers CSV hash/summary/json and only falls back to report/manifest reads when CSV context is missing.
- Dashboard renderer should keep stale-row signaling when legacy report references are missing.
- Run-setting canonical source remains `cookimport/config/run_settings.py`, but analytics consumers must treat CSV as primary runtime history surface.

### 2026-02-16_12.30.45 history-root alignment and mixed timestamp run-dir resolution

Merged source file:
- `2026-02-16_12.30.45-run-manifest-semantics-and-history-root.md` (formerly in `docs/understandings`)

Analytics-relevant outcomes:
- Stage CSV appends to `<stage --out>/.history/performance_history.csv`.
- Benchmark CSV appends to `<processed_output_dir>/.history/performance_history.csv`.
- `perf_report.resolve_run_dir()` supports both timestamp folder styles:
  - `YYYY-MM-DD_HH.MM.SS`
  - `YYYY-MM-DD-HH-MM-SS`
- This preserves auto-latest behavior across mixed historical output folders.

## 6) Known caveats / sharp edges (important)

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

## 7) Practical debugging runbook

1. Confirm per-run report exists:
- `data/output/<timestamp>/<slug>.excel_import_report.json`

2. Confirm history append happened:
- `data/output/.history/performance_history.csv`

3. If dashboard seems empty:
- run `cookimport stats-dashboard --scan-reports`
- inspect warnings printed by collector
- verify benchmark eval files exist under `data/golden/eval-vs-pipeline/*/eval_report.json`

4. If `perf-report` cannot auto-find a run:
- provide explicit `--run-dir <output_root>/<timestamp>`
- verify folder names match one of the supported timestamp formats above

## 8) Why this design exists

- JSON per-run report preserves detailed per-file telemetry next to artifacts.
- CSV history gives cheap append-only longitudinal tracking and easy tooling compatibility.
- Static dashboard keeps dependencies low, local/offline friendly, and deterministic.
- Unified CSV for stage + benchmark gives one place for trend analysis across ingestion quality and throughput.

## 9) If changing analytics, update these places together

1. `cookimport/core/models.py` (`ConversionReport` fields/aliases)
2. `cookimport/analytics/perf_report.py` (row extraction + CSV schema)
3. `cookimport/analytics/dashboard_schema.py` (dashboard contract)
4. `cookimport/analytics/dashboard_collect.py` (collector logic)
5. `cookimport/analytics/dashboard_render.py` (UI fields)
6. `tests/test_stats_dashboard.py` (coverage for schema/collector/renderer/CSV compatibility)
7. this README

## 10) Consolidation provenance

This README replaced and merged:

- `docs/08-analytics/08-analytics_README.md`
- `docs/08-analytics/2026-02-12_11.31.47-metrics-observability-map.md`
- `docs/08-analytics/SPEED_UP.md`
- `docs/08-analytics/resource_usage_report.md`

Intentional preservation policy used during merge:
- Keep implementation history and failed/stale assumptions in “Historical timeline” and “Known bad”.
- Prefer code-verified current behavior when old docs conflict.
