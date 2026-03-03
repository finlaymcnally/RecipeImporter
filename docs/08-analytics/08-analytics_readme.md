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
  - `all-method-benchmark/all-method-benchmark-run__<run_ts>.html`
  - `all-method-benchmark/all-method-benchmark__<run_ts>__<source_slug>.html`
- Data contract: `cookimport/analytics/dashboard_schema.py` (`SCHEMA_VERSION = "12"`)
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

Regression anchors:
- `tests/analytics/test_perf_report.py`
- `tests/analytics/test_stats_dashboard.py`
- `tests/analytics/test_benchmark_csv_backfill_cli.py`
- `tests/labelstudio/test_labelstudio_benchmark_helpers.py` (dashboard refresh/CSV wiring in benchmark flows)
- `tests/bench/test_bench.py` (bench command helper and artifact contracts)

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
- Collector also scans nested `<output_root>/**/.history/performance_history.csv` files for supplemental benchmark rows (used by nested benchmark processed-output layouts).

Stage/import rows (`run_category=stage_import` or `labelstudio_import`):
- Runtime fields: `total_seconds`, `parsing_seconds`, `writing_seconds`, `ocr_seconds`
- Workload/count fields: `recipes`, `tips`, `tip_candidates`, `topic_candidates`, `total_units`
- Derived fields: `per_recipe_seconds`, `per_unit_seconds`, knowledge/dominant-* fields
- Run-config context: `run_config_hash`, `run_config_summary`, `run_config_json`
- EPUB metadata: `epub_extractor_requested`, `epub_extractor_effective`

Benchmark rows (`run_category=benchmark_eval` or `benchmark_prediction`):
- Score fields: explicit `strict_accuracy`, `macro_f1_excluding_other` plus legacy compatibility fields (`precision`, `recall`, `f1`, `practical_*`), supported metrics
- Count/boundary fields: `gold_total`, `gold_matched`, `pred_total`, boundary columns
  - Canonical-text benchmark eval now emits `report.boundary` (computed from aligned canonical-line spans), so canonical benchmark rows can populate `boundary_*` columns without requiring separate freeform-eval runs.
- Per-label durability field: `per_label_json` (compact JSON list used by CSV-first dashboard collection when eval artifacts are no longer present).
- Recipe-level context: `recipes`, `gold_recipe_headers`
- Codex token-usage fields: `tokens_input`, `tokens_cached_input`, `tokens_output`, `tokens_reasoning`, `tokens_total`
- Benchmark timing fields: `benchmark_prediction_seconds`, `benchmark_evaluation_seconds`, `benchmark_artifact_write_seconds`, `benchmark_history_append_seconds`, `benchmark_total_seconds`, eval checkpoint timing columns
- Run-config context: `run_config_hash`, `run_config_summary`, `run_config_json`

Compatibility behavior:
- Appenders auto-expand older CSV headers to current schema before writing.
- CSV append operations use inter-process file locking to reduce concurrent write corruption.
- Benchmark readers collapse strict/practical aliases only when explicit benchmark metrics exist (`strict_accuracy`, `macro_f1_excluding_other`); legacy split precision/recall/practical fields are preserved when explicit metrics are absent.
- `bench gc` hydrates missing benchmark durability fields before deletion and skips run-root pruning when matching durable benchmark history rows cannot be confirmed.

### 3.3 Dashboard artifacts and data sources

`cookimport stats-dashboard` writes:
- `index.html`
- `assets/dashboard_data.json`
- `assets/dashboard_ui_state.json` (program-side Previous Runs UI state, used by `--serve`)
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
  - CSV-first by default
  - includes supplemental benchmark rows from nested benchmark history CSVs under `--output-root`
  - benchmark CSV rows persist Codex token usage (`tokens_*`) when benchmark prediction manifests include `llm_codex_farm` telemetry
  - CSV benchmark rows now backfill missing codex model/effort runtime from adjacent benchmark manifests (`manifest.json` / `prediction-run/manifest.json`) when available
  - optional recursive JSON scan only when `--scan-benchmark-reports` is enabled
  - scan fallback still activates when benchmark CSV rows are unavailable
  - scan mode merges JSON-discovered benchmark rows with benchmark CSV rows (dedupe key: normalized benchmark artifact dir path)
- Sorting is timestamp-parse-aware (mixed `YYYY-MM-DD_HH.MM.SS` and ISO timestamp text tolerated)

Benchmark scan details:
- Recurses nested eval reports including sweep layouts:
  - `all-method-benchmark/<source_slug>/config_*/eval_report.json`
  - `single-profile-benchmark/<source_slug>/eval_report.json`
- For suffixed run folders (for example `2026-02-28_02.03.18_manual-top5-...`), benchmark `run_timestamp` is normalized to the timestamp prefix (`2026-02-28_02.03.18`) so sweep rows aggregate correctly.
- Excludes `prediction-run` eval dirs and pytest temp artifacts
- Optional enrichment from `manifest.json` / `coverage.json` (eval dir and `prediction-run/`)
  - Manifest enrichment also backfills codex runtime context into benchmark `run_config` when needed:
    - `codex_farm_model`
    - `codex_farm_reasoning_effort`
    using `llm_codex_farm.process_runs.*.process_payload` with telemetry reasoning fallback.

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
- Also backfills benchmark `run_config_json`/`run_config_hash`/`run_config_summary` runtime metadata from nearby manifests, including codex model/effort when resolvable.
- Also backfills missing benchmark token columns (`tokens_input`, `tokens_cached_input`, `tokens_output`, `tokens_reasoning`, `tokens_total`) from nearby prediction-run manifests when telemetry is available.
- Uses benchmark manifests and processed report references as backfill sources.
- `--dry-run` reports potential changes without writing.
- Real writes trigger dashboard refresh for matching history root.

### `cookimport stats-dashboard`

- Builds static dashboard files from collected analytics data.
- Supports `--since-days` filtering, optional stage report scan (`--scan-reports`), and optional benchmark eval scan (`--scan-benchmark-reports`).
- Supports `--open` to launch the generated `index.html` in browser.
- Supports `--serve` (`--host`, `--port`) to run a local HTTP server for the generated dashboard and enable program-side UI-state sync to `assets/dashboard_ui_state.json`.
  - In `--serve` mode, dashboard JS polls program-side UI-state and applies newer state live, so cross-browser dashboard settings converge automatically.
- Prints collector warnings (first 10) when malformed/partial inputs are detected.
- `Per-Label Breakdown` aggregates per-label totals across the latest preferred benchmark run-group key (all-method preferred, non-speed preferred), where the group key comes from benchmark artifact-path timestamp token and falls back to record timestamp when needed.
- `Boundary Classification` aggregates boundary counts across all boundary-bearing rows at that same latest preferred benchmark run-group key, and surfaces matched-coverage context (`gold_matched/gold_total`, `gold_matched/pred_total`) so boundary percentages are interpreted as matched-boundary-only.
- Boundary table now uses `% of gold` as the only percentage denominator, and adds `Matched (boundary unclassified)` + `Unmatched gold spans` rows so coverage gaps are explicit in-table.
- `Diagnostics` now includes a latest-benchmark runtime card (model, thinking effort, pipeline mode) from benchmark run-config metadata when available.
- Diagnostics layout is fixed 2-up on desktop: `Benchmark Runtime` and `Boundary Classification` each occupy 50% width on the first row, with `Per-Label Breakdown` full-width below (mobile collapses to one column).
- Latest runtime diagnostics include only `Token use` (cached-adjusted discounted estimate, same formula as `All token use`) with compact `k`/`m` display for large values.
- Per-label diagnostics keep latest-run `codexfarm` precision/recall as raw baseline columns, and render signed deltas for the other precision/recall columns against that same-label baseline (green = better, red = worse), while rolling `n=10` windows remain variant-specific (no cross-variant averaging).
- If benchmark run-config leaves model/effort unset (default runtime), collector backfills from prediction-run manifest `llm_codex_farm` process telemetry when present.
- `Previous Runs` includes separate `AI Model` and `AI Effort` columns; `Source` uses source-file basename first, then artifact-path slug fallback when source-file metadata is missing.
  - `AI Model` shows only model-derived runtime values (plus `off`); pipeline profile IDs are not displayed in that column.
  - `AI Effort` shows only concrete effort values; placeholders (`<default>`, `default`) are treated as missing in the UI.
  - Known SeaAndSmoke historical rows at `2026-03-03T01:28:32`, `2026-03-02T23:37:21`, and `2026-03-02T23:20:13` have `AI Effort` intentionally suppressed to avoid displaying incorrect inferred backfill values.
  - `All token use` is part of the default `Previous Runs` columns and displays combined `total | input | output` with compact `k`/`m` formatting for large values.
  - Sorting/filtering `All token use` uses the numeric `tokens_total` value.
  - Detailed token columns (`Tokens In`, `Tokens Cached In`, `Tokens Out`, `Tokens Reasoning`, `Tokens Total`) remain available through the `+/-` column picker.
- Benchmark CSV appends now persist `importer_name`; dashboard still infers importer from source-path/run-config for historical rows where CSV importer is blank.
- `Previous Runs` now supports per-column stacked filters via a compact `+/-` editor toggle in the first row beneath headers; each save appends a clause for that column (instead of replacing), active clauses can be removed individually via `×` in the popup, and each column stack has an `AND/OR` mode toggle. Active filter summaries in that row render one clause per line with a per-clause `X` remove button. Non-numeric popup value fields provide typeahead suggestions from that column, `Tab` accepts the top suggestion, and saving closes the popup while leaving a summary badge in-row. Header rows render in order: column names, filter row, then a blank spacer row before data. The same filtered dataset is applied to the score trend chart.
- Previous Runs table UI state is now browser-persistent (`localStorage`) for column visibility/order/width, column filters, quick-filter checkboxes, isolate combine mode + stacked isolate rules, sort order, and named view presets, so these customizations survive dashboard HTML rebuilds at the same dashboard path.
- Previous Runs filter control between Isolate For X and table column filters now follows `last edited wins`: isolate edits override table filters, table-filter edits pause isolate until isolate is edited again.
- `Quick Filters` now includes inline `View presets` controls (`Load`, `Save current view`, `Delete`) for reusable table setups (columns + filters + quick filters + sort + isolate + column widths), without a separate presets popup.
- Diagnostic table resize now applies only to `Per-Label Breakdown`; `Boundary Classification` and `Benchmark Runtime` intentionally stay fixed-fit (no horizontal scroll/resize) for cleaner top-row readability.
- `Quick Filters` appears between trend chart and table with:
  - a primary default-on toggle for official single-offline benchmark rows (`benchmark-vs-golden` + `single-offline-benchmark`) with `vanilla`/`codexfarm` variants,
  - a secondary toggle for excluding AI test/smoke benchmark runs (`/bench/`, pytest-temp style paths, and `<timestamp>_manual-...-smoke` style run folders).
  - a visible `Clear all filters` button that resets quick filters, table column filters, and isolate rules together.
- `Previous Runs` table keeps horizontal scrolling with a fixed minimum table width, and the viewport stays at about 10 visible-row height (even when filtered result count is lower) before vertical scrolling.
- Clicking a `Previous Runs` table header now toggles sort direction for that column (`A→Z` / `Z→A`; numeric/date-aware where possible).
- Benchmark trend chart timestamps are rendered in browser-local time (`Highcharts time.useUTC=false`).
- Benchmark trend score series are rendered as scatter points so only discrete run timestamps are shown (no connected interpolation line).
- When paired single-offline variants are present, benchmark trend chart splits metric series by variant (`vanilla` vs `codexfarm`) so each pair is plotted separately.
- Benchmark trend tooltip is run-grouped: hovering any point shows one local-time card with all visible series values for that run (no raw coordinate-style x/y labels).
- Benchmark trend chart uses a fixed 800px render/container height to preserve stable layout and provide a taller score-history viewport.
- Dashboard HTML now loads Highcharts Stock with a secondary CDN fallback (`code.highcharts.com` primary, `cdn.jsdelivr.net` fallback) before dashboard JS initialization.
- `Previous Runs` table columns are configurable in-browser: use the `+/-` header-row button popup to check/uncheck fields, drag headers to reorder, and resize by dragging header edges.
- `Benchmark Score Trend` defaults to the `All` range selector window so initial render includes full available benchmark history.
- `Benchmark Score Trend` initializes x-axis bounds from the full filtered benchmark timestamp span, so chart timeline coverage matches `Previous Runs` dates even when older rows lack explicit score points.
- Main page is intentionally narrow in scope:
  - `Diagnostics (Latest Benchmark)`
  - `Previous Runs`

### Benchmark CSV append entry points (`append_benchmark_csv`)

- `cookimport labelstudio-eval` appends freeform-eval benchmark rows and refreshes dashboard.
- `cookimport labelstudio-benchmark` appends benchmark rows (with timing + run-config metadata) and refreshes dashboard.
- Interactive `single_offline` wraps per-variant benchmark runs with deferred dashboard refresh and triggers one batch refresh after all planned variants finish.

## 5) All-method dashboard contract

Grouping and hierarchy:
- All-method grouping is derived from benchmark artifact paths containing either:
  - `all-method-benchmark/<source_slug>/config_*`
  - `single-profile-benchmark/<source_slug>`
- Renderer writes all-method run-summary and per-book detail pages under `all-method-benchmark/`; no standalone `all-method-benchmark/index.html` page is emitted.
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

E) Static/offline default plus optional local state server
- Opening `index.html` directly still works offline and uses browser-local `localStorage`.
- Program-side UI-state persistence across browsers requires `cookimport stats-dashboard --serve`.

## 7) Debugging checklist

1. Confirm run report files exist in the expected run folder.
2. Confirm history CSV path resolved from your chosen output root.
3. Regenerate dashboard with explicit roots when in doubt:
- `cookimport stats-dashboard --output-root <out_root> --golden-root <gold_root>`
4. If stage rows appear missing, rerun with `--scan-reports` to supplement CSV.
5. If benchmark rows look wrong, rerun with `--scan-benchmark-reports` and inspect `eval_report.json` + related manifests under the benchmark artifact directory.

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
- Analytics ownership covers telemetry artifact persistence and dashboard collector/renderer behavior, including command-side history appenders in `labelstudio-eval` and `labelstudio-benchmark`.
- Main dashboard index contract remains intentionally reduced to `Diagnostics (Latest Benchmark)` and `Previous Runs`.
- Legacy throughput/filter/KPI main-index branches are retired behavior and should stay historical-only.
- Compatibility fallback for legacy history path lookup (`<output_root>/.history/performance_history.csv`) and stale all-method root-page cleanup are active renderer/collector hygiene rules.

Anti-loop rule:
- If analytics docs and UI disagree, verify tests (`tests/analytics/test_stats_dashboard.py`) and current collector/render code before restoring retired UI branches.

## 2026-02-28 migrated understandings digest

This section consolidates discoveries migrated from `docs/understandings` into this domain folder.

### 2026-02-27_20.24.21 dashboard per label latest run aggregation
- Source: `docs/understandings/2026-02-27_20.24.21-dashboard-per-label-latest-run-aggregation.md`
- Summary: Stats dashboard per-label card aggregates across all records in the latest selected benchmark run group (artifact-path timestamp token fallback to record timestamp), avoiding split twin-run eval timestamps.

## 2026-02-28 migrated understandings batch (03:42-04:02)

The items below were merged from `docs/understandings` in timestamp order and folded into analytics current-state guidance.

### 2026-02-28_03.42.13 single-profile benchmark rows in all-method index grouping
- Collector/render grouping must support both path families:
  - `all-method-benchmark/<source_slug>/config_*`
  - `single-profile-benchmark/<source_slug>`
- Single-profile rows should be grouped at run level using `run_config_hash` when present.

### 2026-02-28_03.52.45 suffixed run folder timestamp normalization
- Benchmark folder names can include suffixes after timestamp (for example `_manual-top5-...`).
- Collector should normalize `run_timestamp` to prefix `YYYY-MM-DD_HH.MM.SS` so all configs from one run aggregate together.

### 2026-02-28_03.58.19 low-eval diagnostics from speed-suite sampling
- Latest diagnostics can be tiny when latest benchmark rows came from speed-suite runs with aggressive sampling (`max_targets=1`).
- Diagnose by checking speed run manifests before treating this as collector corruption.

### 2026-02-28_04.02.14 diagnostics source preference
- Diagnostics rendering should prefer non-speed benchmark rows when both speed and non-speed rows exist.
- Speed rows remain valid fallback when they are the only benchmark rows.

## 2026-02-28 migrated understandings batch (04:08 diagnostics path normalization)

### 2026-02-28_04.08.22 dashboard diagnostics path normalization red/green
- Source: `docs/understandings/2026-02-28_04.08.22-dashboard-diagnostics-path-normalization-red-green.md`
- Diagnostics selectors now classify speed/all-method rows by normalized artifact paths instead of raw string fragments.
- Renderer helper contract in `cookimport/analytics/dashboard_render.py`:
  - `benchmarkArtifactPath(record)`
  - `isSpeedBenchmarkRecord(record)`
  - `isAllMethodBenchmarkRecord(record)`
- Per-label and boundary diagnostics selection now uses those helpers, which handles mixed slash styles (`/` and `\\`) correctly.

Anti-loop note:
- If diagnostics unexpectedly pick speed rows, test normalized-path helper behavior before changing collector grouping rules.

## 2026-02-28 task consolidation (`docs/tasks` dashboard wheel-zoom safeguard)

Merged task file:
- `2026-02-28_12.18.03-disable-dashboard-highcharts-wheel-zoom.md`

Current dashboard interaction contract:
- Highcharts mouse-wheel zoom is disabled globally for generated dashboard pages to prevent accidental chart zoom while scrolling.
- Toggle point is explicit and centralized in dashboard JS init via `HIGHCHARTS_MOUSE_WHEEL_ZOOM_ENABLED`.
- Re-enable path is intentionally one-line: set that constant to `true`.
- This is a global default (`Highcharts.setOptions(...)`) so newly-added dashboard charts inherit the same behavior unless explicitly overridden.

## 2026-02-28 merged understandings (benchmark trend chart contract)

### 2026-02-28_12.11.07 dashboard benchmark trend chart structure
- Source: `docs/understandings/2026-02-28_12.11.07-dashboard-benchmark-trend-chart-structure.md`
- Main stats dashboard now includes an interactive benchmark trend chart above Previous Runs with explicit fallback behavior:
  - no-data fallback text when rows have no trend points,
  - offline/CDN failure fallback text when Highcharts is unavailable,
  - table rendering remains usable regardless of chart state.
- Trend series contract currently includes: `strict_accuracy`, `macro_f1_excluding_other`.
- Timestamp parsing must continue to accept both `YYYY-MM-DD_HH.MM.SS` and ISO-style strings so historical rows sort correctly.
- Y-axis score bounds are intentionally fixed to `0..1` for comparability across runs.


## 2026-03-03 merged understandings digest

This batch consolidates dashboard/history discoveries that were previously in `docs/understandings/`.

Key analytics contracts to keep:
- `Previous Runs` should compute/filter on raw records before all-method bundling to avoid misleading grouped rows.
- Benchmark source/runtime display must use layered fallback logic (CSV -> run config -> manifest telemetry/path slug) so historical/partial rows stay informative.
- Boundary diagnostics may legitimately lag when fresh rows are missing boundary fields; preserve "last non-null" semantics and surface why.
- Trend/chart defaults should align with table context (`All` range default) to prevent false "missing history" confusion.
- Dynamic column rendering in Previous Runs is state-driven and must handle single + all-method row shapes consistently.
- Explicit benchmark metric names are preferred; legacy metric ingestion remains a compatibility path.

Chronological merged source notes:
- 2026-03-02_22.26.36-dashboard-ai-runtime-and-source-fallback: Dashboard `Previous Runs` source labels should fall back to artifact-path slugs, and AI runtime should come from run-config metadata.
- 2026-03-02_22.29.43-dashboard-all-method-navigation-contract: All-method dashboard pages should be reached from main Previous Runs, not from a separate all-method index page.
- 2026-03-02_22.30.04-dashboard-previous-runs-rules-filter-flow: Previous Runs filtering should be applied before all-method run bundling so filtered comparisons stay meaningful.
- 2026-03-02_22.35.41-dashboard-all-method-timestamp-from-path: All-method Previous Runs timestamps must be extracted from timestamp-like path tokens, not the segment immediately before all-method-benchmark.
- 2026-03-02_22.37.34-dashboard-boundary-fallback-to-last-non-null: Boundary Classification card can show an older timestamp when newer benchmark rows have null boundary metrics.
- 2026-03-02_22.40.42-dashboard-codex-runtime-llm-codex-farm-fallback: Dashboard benchmark runtime model/effort may need fallback from prediction-run `llm_codex_farm` telemetry when run-config leaves defaults unset.
- 2026-03-02_22.41.32-dashboard-ai-off-fallback-vs-codex-manifest-runtime: Dashboard AI column/runtime can incorrectly show `off` unless codex runtime is backfilled from benchmark manifest llm_codex_farm payloads.
- 2026-03-02_22.48.48-benchmark-importer-missing-csv-root-cause: Benchmark importer '-' rows were caused by blank importer_name in CSV writes, not table rendering loss.
- 2026-03-02_23.11.05-dashboard-trend-range-selector-default: Benchmark Score Trend looked shorter than Previous Runs because Highcharts Stock defaulted to a recent range selection.
- 2026-03-02_23.50.00-dashboard-previous-runs-dynamic-column-contract: Previous Runs now renders columns dynamically from JS state across single + all-method row shapes.
- 2026-03-02_23.58.40-benchmark-metric-fallback-explicit-vs-legacy: Benchmark compatibility readers should only collapse aliases when explicit strict/macro metrics are present.
- 2026-03-02_23.59.30-dashboard-explicit-metric-rendering: Dashboard Previous Runs/trend should render explicit benchmark metric names while preserving legacy ingestion fallback.

## 2026-03-03 docs/tasks merge digest (dashboard Previous Runs contracts)

Merged source task files (chronological):
- `docs/tasks/2026-03-02_22.26.36 - dashboard-ai-runtime-columns-and-source-fallback.md`
- `docs/tasks/2026-03-02_22.29.43 - dashboard-remove-all-method-index-page.md`
- `docs/tasks/2026-03-02_22.30.04 - previous-runs-rules-filter-builder.md`
- `docs/tasks/2026-03-02_22.30.04-dashboard-previous-runs-rules-filters.md`
- `docs/tasks/2026-03-02_22.35.08 - previous-runs-horizontal-scroll.md`
- `docs/tasks/2026-03-02_22.41.32 - fix-dashboard-ai-off-fallback-from-codex-manifest-runtime.md`
- `docs/tasks/2026-03-02_22.48.48 - benchmark-importer-csv-and-dashboard-fallback.md`
- `docs/tasks/2026-03-02_23.11.05 - benchmark-score-trend-default-all-range.md`
- `docs/tasks/2026-03-02_23.17.11 - benchmark-trend-timeline-align-with-table.md`
- `docs/tasks/2026-03-02_23.50.00 - previous-runs-column-controls.md`
- `docs/tasks/2026-03-02_23.50.00-dashboard-previous-runs-column-controls.md`

Current contract additions:
- Main index no longer includes a separate all-method run index section/page; all-method deep links are reached from `Previous Runs`.
- `Previous Runs` column filters are edited via per-column `+/-` popup controls, with active filter summaries shown in the first header-adjacent row.
- Table overflow contract requires horizontal scrolling + minimum table width so dense benchmark rows remain legible.
- Diagnostics/latest-runtime and `Previous Runs` AI runtime columns (`AI Model`, `AI Effort`) should prefer richer codex runtime metadata, with fallback backfill from benchmark manifests when run-config fields are blank.
- Benchmark CSV writes should persist `importer_name`; dashboard still needs runtime fallback inference for historical blank rows.
- Trend chart default window is `All` and x-axis bounds should align with filtered table timestamp span even when some older rows have no explicit score points.
- Column controls remain session-local and must support checkbox show/hide, drag reorder, resize handles, and mixed row-shape rendering (`single` + grouped `all_method`).

## 2026-03-03 merged understandings digest (trend/table alignment + history culling)

Merged source notes:
- `docs/understandings/2026-03-02_23.17.11-benchmark-trend-null-explicit-metrics-gap.md`
- `docs/understandings/2026-03-02_23.22.43-dashboard-history-cull-legacy-benchmark-rows.md`

Current analytics contracts to keep:
- Trend points use explicit benchmark metrics (`strict_accuracy`, `macro_f1_excluding_other`) only, but chart x-axis bounds should still be initialized from the full filtered timestamp span so timeline coverage matches `Previous Runs`.
- Legacy benchmark rows with null explicit metrics are valid history rows and should remain visible in table/filter contexts.
- When dashboard history is intentionally culled to current artifact paradigms, remove stale benchmark CSV rows that point to legacy pytest/tmp/eval-vs-pipeline paths.
- CSV pruning alone is not enough if old benchmark run folders still exist on disk; collector behavior and artifact retention policy must stay aligned.
