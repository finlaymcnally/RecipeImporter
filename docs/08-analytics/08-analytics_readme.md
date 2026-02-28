---
summary: "Current analytics reference: artifact contracts, command behavior, caveats, and maintenance checklist."
read_when:
  - When changing performance reporting, CSV history writes, or stats-dashboard behavior
  - When debugging missing or inconsistent analytics artifacts under data/output or data/golden
  - When updating current analytics behavior; read `08-analytics_log.md` for prior attempts/history
---

# 08 Analytics README

Current, code-verified analytics contract for this repo.

This README intentionally documents only active behavior. Historical implementation detail and prior branches are in `docs/08-analytics/08-analytics_log.md`.

## 1) What analytics currently includes

1. Per-file conversion reports
- Artifact: `<run_dir>/<file_slug>.excel_import_report.json`
- Producers: `stage_one_file`, `stage_pdf_job`, `stage_epub_job`, split-merge path
- Schema anchor: `cookimport/core/models.py` (`ConversionReport`)

2. Cross-run history CSV
- Artifact: `performance_history.csv`
- Default location for default output root (`data/output`): `data/.history/performance_history.csv`
- Producer paths:
  - stage/perf-report appenders (`append_history_csv`)
  - benchmark appenders (`append_benchmark_csv`)
  - one-off patch command (`benchmark-csv-backfill`)

3. Static dashboard site
- Default root: `data/.history/dashboard`
- Main page: `index.html`
- Standalone all-method pages:
  - `all-method-benchmark/index.html`
  - `all-method-benchmark/all-method-benchmark-run__<run_ts>.html`
  - `all-method-benchmark/all-method-benchmark__<run_ts>__<source_slug>.html`
- Data contract: `cookimport/analytics/dashboard_schema.py` (`SCHEMA_VERSION = "10"`)
- Collect/render path: `dashboard_collect.py` -> `dashboard_render.py`

## 2) Code map

Primary modules:
- `cookimport/analytics/perf_report.py`
- `cookimport/analytics/dashboard_collect.py`
- `cookimport/analytics/dashboard_schema.py`
- `cookimport/analytics/dashboard_render.py`
- `cookimport/analytics/benchmark_timing.py`
- `cookimport/paths.py` (history-root helpers used by analytics paths)
- `cookimport/cli.py` (`stats-dashboard`, history appenders, refresh helper wiring)

Primary CLI entry points:
- `cookimport stage`
- `cookimport perf-report`
- `cookimport benchmark-csv-backfill`
- `cookimport stats-dashboard`
- `cookimport labelstudio-eval` (benchmark CSV append + refresh)
- `cookimport labelstudio-benchmark` (benchmark CSV append + refresh)
- `cookimport bench run` (suite aggregate benchmark CSV append + refresh)

Regression anchors:
- `tests/analytics/test_perf_report.py`
- `tests/analytics/test_stats_dashboard.py`
- `tests/analytics/test_benchmark_csv_backfill_cli.py`
- `tests/labelstudio/test_labelstudio_benchmark_helpers.py` (dashboard refresh/CSV wiring in benchmark flows)
- `tests/bench/test_bench.py` (bench-run analytics append/refresh wiring)

## 3) Artifact contracts

### 3.1 Per-file report JSON

Analytics-critical fields:
- Identity: `runTimestamp`, `sourceFile`, `importerName`
- Counts: `totalRecipes`, `totalTips`, `totalTipCandidates`, `totalTopicCandidates`
- Standalone-topic coverage: `totalStandaloneBlocks`, `totalStandaloneTopicBlocks`, `standaloneTopicCoverage`
- Timing: `timing.total_seconds`, `timing.parsing_seconds`, `timing.writing_seconds`, `timing.ocr_seconds`, `timing.checkpoints`
- Run context: `runConfig`, `runConfigHash`, `runConfigSummary`

Split-merge note:
- Split flows aggregate child timing and record merge overhead in `timing.checkpoints.merge_seconds`.

### 3.2 History CSV (`performance_history.csv`)

History root rule (important):
- History is resolved from output root using `history_csv_for_output(output_root)`.
- Path is `output_root.parent / ".history" / "performance_history.csv"`.
- Example: output root `/tmp/out` writes history at `/tmp/.history/performance_history.csv`.
- Collector compatibility read path: if canonical history CSV is missing, collector also probes legacy `<output_root>/.history/performance_history.csv`.

Stage/import rows (`run_category=stage_import` or `labelstudio_import`):
- Runtime fields: `total_seconds`, `parsing_seconds`, `writing_seconds`, `ocr_seconds`
- Workload/count fields: `recipes`, `tips`, `tip_candidates`, `topic_candidates`, `total_units`
- Derived fields: `per_recipe_seconds`, `per_unit_seconds`, knowledge/dominant-* fields
- Run-config context: `run_config_hash`, `run_config_summary`, `run_config_json`
- EPUB metadata: `epub_extractor_requested`, `epub_extractor_effective`

Benchmark rows (`run_category=benchmark_eval` or `benchmark_prediction`):
- Score fields: `precision`, `recall`, `f1`, `practical_*`, supported metrics
- Count/boundary fields: `gold_total`, `gold_matched`, `pred_total`, boundary columns
- Recipe-level context: `recipes`, `gold_recipe_headers`
- Benchmark timing fields: `benchmark_prediction_seconds`, `benchmark_evaluation_seconds`, `benchmark_artifact_write_seconds`, `benchmark_history_append_seconds`, `benchmark_total_seconds`, eval checkpoint timing columns
- Run-config context: `run_config_hash`, `run_config_summary`, `run_config_json`

Compatibility behavior:
- Appenders auto-expand older CSV headers to current schema before writing.
- CSV append operations use inter-process file locking to reduce concurrent write corruption.

### 3.3 Dashboard artifacts and data sources

`cookimport stats-dashboard` writes:
- `index.html`
- `assets/dashboard_data.json`
- `assets/dashboard.js`
- `assets/style.css`
- all-method pages under `all-method-benchmark/`

Collector behavior (`collect_dashboard_data`):
- Stage rows:
  - CSV-first when history exists and `--scan-reports` is off
  - CSV plus report-scan supplement when `--scan-reports` is on
  - report-only fallback when CSV is missing
  - run-config fallback from report JSON when stale CSV rows lack `run_config_json`
- Benchmark rows:
  - always scans benchmark JSON surfaces under `golden_root`
  - merges JSON-discovered benchmark rows with benchmark CSV rows (dedupe key: normalized benchmark artifact dir path)
- Sorting is timestamp-parse-aware (mixed `YYYY-MM-DD_HH.MM.SS` and ISO timestamp text tolerated)

Benchmark scan details:
- Recurses nested eval reports including all-method layouts (`all-method-benchmark/<source_slug>/config_*/eval_report.json`)
- Excludes `prediction-run` eval dirs and pytest temp artifacts
- Optional enrichment from `manifest.json` / `coverage.json` (eval dir and `prediction-run/`)

## 4) Command behavior (current)

### `cookimport stage`

- Writes timestamped run folders (`YYYY-MM-DD_HH.MM.SS`) under `--out` root.
- Appends stage rows to history CSV for that output root.
- Triggers best-effort dashboard refresh after history write.

### `cookimport perf-report`

- Summarizes one run (`--run-dir` explicit or latest resolved under `--out-dir`).
- `--write-csv` (default) appends rows to history CSV and triggers dashboard refresh.

### `cookimport benchmark-csv-backfill`

- Repairs missing benchmark CSV fields (`recipes`, `report_path`, `file_name`) for older rows.
- Uses benchmark manifests and processed report references as backfill sources.
- `--dry-run` reports potential changes without writing.
- Real writes trigger dashboard refresh for matching history root.

### `cookimport stats-dashboard`

- Builds static dashboard files from collected analytics data.
- Supports `--since-days` filtering and optional report scan (`--scan-reports`).
- Supports `--open` to launch the generated `index.html` in browser.
- Prints collector warnings (first 10) when malformed/partial inputs are detected.
- Main page is intentionally narrow in scope:
  - `All-Method Benchmark Runs`
  - `Diagnostics (Latest Benchmark)`
  - `Previous Runs`

### Benchmark CSV append entry points (`append_benchmark_csv`)

- `cookimport labelstudio-eval` appends freeform-eval benchmark rows and refreshes dashboard.
- `cookimport labelstudio-benchmark` appends benchmark rows (with timing + run-config metadata) and refreshes dashboard.
- `cookimport bench run` appends suite aggregate benchmark rows and refreshes dashboard.

## 5) All-method dashboard contract

Grouping and hierarchy:
- All-method grouping is derived from benchmark artifact paths containing `all-method-benchmark/<source_slug>/config_*`.
- Renderer always writes all-method run index page (`all-method-benchmark/index.html`) even when there are zero all-method runs.
- Renderer removes stale legacy all-method root pages before writing the current subfolder hierarchy.

Standalone page behavior:
- Run pages and detail pages include quick-nav and collapsed sections for scanability.
- Both run and detail pages include:
  - summary stats table
  - metric bar charts
  - radar/web charts
  - ranked tables
- Score/radar/bar scaling uses fixed `0..100%` axes (`1.0 == 100%` for score metrics).
- Recipes metric is `% identified` against `gold_recipe_headers`.

## 6) Known caveats

A) Mixed timestamp formats exist historically
- `resolve_run_dir` and dashboard timestamp sorting tolerate both current folder timestamps and legacy forms.

B) History root is above output root
- Do not assume `<out>/.history/...`; history is `<out parent>/.history/...`.

C) Dashboard JS template correctness still matters
- `dashboard_render.py` emits JS via Python string templates. Bad escaping can break generated JS and blank the page.

D) Auto-refresh output-root inference is path-sensitive
- Automatic refresh inference expects a canonical CSV path shape (`.../.history/performance_history.csv`).
- Non-canonical custom CSV paths may skip refresh with a warning.

E) Static/offline design is intentional
- No server-side persistence, no auth, no multi-user semantics.

## 7) Debugging checklist

1. Confirm run report files exist in the expected run folder.
2. Confirm history CSV path resolved from your chosen output root.
3. Regenerate dashboard with explicit roots when in doubt:
- `cookimport stats-dashboard --output-root <out_root> --golden-root <gold_root>`
4. If stage rows appear missing, rerun with `--scan-reports` to supplement CSV.
5. If benchmark rows look wrong, inspect `eval_report.json` + related manifests under the benchmark artifact directory.

## 8) If you change analytics, update together

1. `cookimport/core/models.py` (report schema)
2. `cookimport/analytics/perf_report.py` (CSV extraction/schema)
3. `cookimport/analytics/dashboard_schema.py` (dashboard contract)
4. `cookimport/analytics/dashboard_collect.py` (collector mapping/merge)
5. `cookimport/analytics/dashboard_render.py` (UI rendering)
6. `cookimport/paths.py` (history-root resolution contract)
7. refresh wiring in `cookimport/cli.py` (`_refresh_dashboard_after_history_write` + benchmark/stage append callers)
8. analytics tests under `tests/analytics/` plus nearby CLI integration tests
9. this README and `08-analytics_log.md`

## 2026-02-27 Merged Understandings: Analytics Ownership and Retired Surfaces

Merged source notes:
- `docs/understandings/2026-02-27_19.34.01-docs-task-retirement-target-mapping.md`
- `docs/understandings/2026-02-27_19.46.24-analytics-doc-prune-active-vs-retired-surfaces.md`
- `docs/understandings/2026-02-27_19.52.19-docs-removed-feature-prune-map.md`
- `docs/understandings/2026-02-27_19.52.27-analytics-docs-code-surface-gap-audit.md`

Current-contract additions:
- Analytics ownership covers telemetry artifact persistence and dashboard collector/renderer behavior, including command-side history appenders in `labelstudio-eval`, `labelstudio-benchmark`, and `bench run`.
- Main dashboard index contract remains intentionally reduced to `All-Method Benchmark Runs`, `Diagnostics (Latest Benchmark)`, and `Previous Runs`.
- Legacy throughput/filter/KPI main-index branches are retired behavior and should stay historical-only.
- Compatibility fallback for legacy history path lookup (`<output_root>/.history/performance_history.csv`) and stale all-method root-page cleanup are active renderer/collector hygiene rules.

Anti-loop rule:
- If analytics docs and UI disagree, verify tests (`tests/analytics/test_stats_dashboard.py`) and current collector/render code before restoring retired UI branches.
