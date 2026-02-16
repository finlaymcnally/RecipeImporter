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

Notes:
- Split-job merges write aggregated report timing where parsing/OCR are summed from child jobs and merge overhead is recorded in `timing.checkpoints.merge_seconds`.
- Writer location for this JSON is always run-root level: `write_report(report, out, file_path.stem)`.

### 3.2 Cross-run CSV (`performance_history.csv`)

CSV acts as the long-term unified event log for:

- stage/import rows (`run_category` empty or stage categories)
- benchmark/eval rows (`run_category=benchmark_eval` or `benchmark_prediction`)

For stage rows, key analytics columns include:

- runtime: `total_seconds`, `parsing_seconds`, `writing_seconds`, `ocr_seconds`
- workload: `recipes`, `tips`, `tip_candidates`, `topic_candidates`, `total_units`
- normalized metrics: `per_recipe_seconds`, `per_unit_seconds`, etc.
- topic coverage fields: `standalone_*`
- output size: `output_files`, `output_bytes`
- derived descriptors: `knowledge_share`, `knowledge_heavy`, dominant stage/checkpoint fields
- run context: `run_config_json` (serialized `runConfig` from per-file reports when available)

For benchmark rows, key columns include:

- `precision`, `recall`, `f1`
- `gold_total`, `gold_matched`, `pred_total`
- `supported_precision`, `supported_recall`
- boundary columns: `boundary_correct`, `boundary_over`, `boundary_under`, `boundary_partial`
- `eval_scope`, `source_file` (stored in `file_name`)

Schema migration support exists: old CSV files missing newer columns are auto-expanded during append.

### 3.3 Dashboard artifacts

Dashboard collector reads:

1. `output_root/.history/performance_history.csv` (primary unless `--scan-reports`)
2. `output_root/<timestamp>/*.excel_import_report.json` (fallback/supplement)
3. `golden_root/eval-vs-pipeline/*/eval_report.json` and `golden_root/*/eval_report.json` (benchmark scans)

Collector enrichment:

- optional `coverage.json` adds `extracted_chars`, `chunked_chars`, `coverage_ratio`
- optional `manifest.json` adds `task_count`, `source_file`
- benchmark collector also checks `prediction-run/{coverage.json,manifest.json}` and can enrich `importer_name`, `run_config`, and `processed_report_path` when present

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

Merged source:
- `docs/understandings/2026-02-15_22.07.37-analytics-metrics-flow-and-mismatches.md`

Preserved findings:
- Stage writes per-file reports at `<run_root>/<slug>.excel_import_report.json`, then derives perf summary rows and appends history CSV.
- Stats dashboard primarily reads `data/output/.history/performance_history.csv`, then supplements/falls back to report JSON scan.
- Two mismatches remain important:
  - `perf_report.resolve_run_dir()` still expects hyphen-style timestamp folders while stage uses underscore/dot format.
  - End-of-stage auto history append writes to `history_path(DEFAULT_OUTPUT)` even when stage used a custom `--out`.

## 6) Known bad / sharp edges (important)

### A) `perf-report` latest-run auto-detect likely mismatches current run-folder naming

- `stage` writes run dirs as `YYYY-MM-DD_HH.MM.SS`.
- `resolve_run_dir` in `cookimport/analytics/perf_report.py` currently matches `YYYY-MM-DD-HH-MM-SS`.
- Effect: `cookimport perf-report` without `--run-dir` may fail to find the latest run under modern timestamped folders.

### B) `stage` history append currently targets `DEFAULT_OUTPUT` regardless of `--out`

- In `cookimport/cli.py`, end-of-stage append uses `history_path(DEFAULT_OUTPUT)`.
- Effect: running `cookimport stage --out <custom>` still appends history rows to default `data/output/.history/performance_history.csv`, not the custom output root.
- Dashboard generation with non-default roots can therefore look incomplete unless manually aligned.

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
- provide explicit `--run-dir data/output/<timestamp>`
- then check/fix timestamp matcher mismatch noted above

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
