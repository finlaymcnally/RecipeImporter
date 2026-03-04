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
- Default location for default output root (`data/output`): `.history/performance_history.csv`
- Producer paths:
  - stage/perf-report appenders (`append_history_csv`)
  - benchmark appenders (`append_benchmark_csv`)
  - one-off patch command (`benchmark-csv-backfill`)

3. Static dashboard site
- Default root: `.history/dashboard`
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
- `cookimport/analytics/compare_control_engine.py`
- `cookimport/analytics/benchmark_timing.py`
- `cookimport/paths.py` (history-root helpers used by analytics paths)
- `cookimport/cli.py` (`stats-dashboard`, history appenders, refresh helper wiring)

Primary CLI entry points:
- `cookimport stage`
- `cookimport perf-report`
- `cookimport benchmark-csv-backfill`
- `cookimport stats-dashboard`
- `cookimport compare-control run`
- `cookimport compare-control agent`
- `cookimport labelstudio-eval` (benchmark CSV append + refresh)
- `cookimport labelstudio-benchmark` (benchmark CSV append + refresh)

Regression anchors:
- `tests/analytics/test_perf_report.py`
- `tests/analytics/test_stats_dashboard.py`
- `tests/analytics/test_benchmark_csv_backfill_cli.py`
- `tests/analytics/test_compare_control_engine.py`
- `tests/analytics/test_compare_control_cli.py`
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
- Repo-local output roots (for example `data/output`) resolve to `<repo>/.history/performance_history.csv`.
- External output roots resolve to `output_root.parent / ".history" / "performance_history.csv"`.
- Example: output root `/tmp/out` writes history at `/tmp/.history/performance_history.csv`.
- Collector compatibility read path: if canonical history CSV is missing, collector also probes previous canonical `<output_root parent>/.history/performance_history.csv` and legacy `<output_root>/.history/performance_history.csv`.
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
- `bench gc` is read-only for `performance_history.csv`: it does not hydrate/rewrite/prune rows, and skips run-root pruning when durable benchmark retention cannot be confirmed from existing durable CSV rows.

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
  - when CSV benchmark rows exist, collector auto-supplements only missing **older** benchmark history from benchmark `eval_report.json` artifacts (pre-CSV migrations), then keeps CSV rows authoritative for overlapping artifacts
  - benchmark CSV rows persist Codex token usage (`tokens_*`) when benchmark prediction manifests include `llm_codex_farm` telemetry
  - CSV benchmark rows now backfill missing codex model/effort runtime from adjacent benchmark manifests (`manifest.json` / `prediction-run/manifest.json`) when available
  - collector hard-excludes benchmark artifacts tagged as test/gate noise (`/bench/`, pytest temp layouts, and timestamp-suffix tokens such as `_...-gated-...`, `_...-smoke-...`, `_...-test-...`)
  - optional recursive JSON scan only when `--scan-benchmark-reports` is enabled
  - scan fallback still activates when benchmark CSV rows are unavailable
  - scan mode merges JSON-discovered benchmark rows with benchmark CSV rows (dedupe key: normalized benchmark artifact dir path)
- Sorting is timestamp-parse-aware (mixed `YYYY-MM-DD_HH.MM.SS` and ISO timestamp text tolerated)

Benchmark scan details:
- Recurses nested eval reports including sweep layouts:
  - `all-method-benchmark/<source_slug>/config_*/eval_report.json`
  - `single-profile-benchmark/<source_slug>/eval_report.json`
- For suffixed run folders (for example `2026-02-28_02.03.18_manual-top5-...`), benchmark `run_timestamp` is normalized to the timestamp prefix (`2026-02-28_02.03.18`) so sweep rows aggregate correctly.
- Excludes `prediction-run` eval dirs plus benchmark artifact paths classified as test/gate noise
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
- `Diagnostics` now includes a latest-benchmark runtime card (model, thinking effort, pipeline mode) from benchmark run-config metadata when available, scoped to the latest benchmark run group.
- Diagnostics layout is fixed 2-up on desktop: `Benchmark Runtime` and `Boundary Classification` each occupy 50% width on the first row, with `Per-Label Breakdown` full-width below (mobile collapses to one column).
- Latest runtime diagnostics include only `Token use` (cached-adjusted discounted estimate, same formula as `All token use`) with compact `k`/`m` display for large values, summed across rows in the latest benchmark run group.
- Latest runtime diagnostics also include quality-efficiency rows: `Quality / 1M tokens`, `Delta quality vs vanilla`, `Delta quality / 1M extra tokens vs vanilla`, and peer-run `Quality/tokens vs peers` rank/median comparison.
- Per-label diagnostics keep latest-run `codexfarm` precision/recall as raw baseline columns. Comparison columns can be shown as signed deltas or raw point values via an in-card `Point value` checkbox; delta sign is `codexfarm baseline - comparison` (positive/green = codexfarm higher, negative/red = codexfarm lower).
- Per-label comparison cells now render `-` when the comparison variant metric is missing (instead of coercing to `0.0000` in point-value mode).
- Per-label diagnostics now include a run-group selector beside the title (`Default - most recent` + all available run timestamps) so the table can auto-follow latest runs or be pinned to a chosen timestamp.
- Per-label diagnostics expose a `Rolling N` selector; rolling codexfarm/vanilla comparison columns use that selected N and render under a shared dynamic `<N>-run Rolling <Mode>:` header with metric+variant subcolumns.
- If benchmark run-config leaves model/effort unset (default runtime), collector backfills from prediction-run manifest `llm_codex_farm` process telemetry when present.
- `Previous Runs` includes separate `AI Model` and `AI Effort` columns; `Source` uses source-file basename first, then artifact-path slug fallback when source-file metadata is missing.
  - `AI Model` shows only model-derived runtime values (plus `off`); pipeline profile IDs are not displayed in that column.
  - `AI Effort` shows only concrete effort values; placeholders (`<default>`, `default`) are treated as missing in the UI.
  - `All token use` and `Quality / 1M tokens` are part of the default `Previous Runs` columns.
  - `All token use` displays combined `total | input | output` with compact `k`/`m` formatting for large values.
  - `Quality / 1M tokens` computes preferred quality (`strict_accuracy`, then `macro_f1_excluding_other`, then `f1`) divided by discounted token total and scaled per 1,000,000 tokens (higher is better).
  - Sorting/filtering `All token use` uses the discounted numeric total (`all_token_use`), not raw `tokens_total`.
  - Detailed token columns (`Tokens In`, `Tokens Cached In`, `Tokens Out`, `Tokens Reasoning`, `Tokens Total`) remain available through the `+/-` column picker.
- Benchmark CSV appends now persist `importer_name`; dashboard still infers importer from source-path/run-config for historical rows where CSV importer is blank.
- `Previous Runs` now supports per-column stacked filters via a compact `+/-` editor toggle in the first row beneath headers; each save appends a clause for that column (instead of replacing), active clauses can be removed individually via `×` in the popup, and each column stack has an `AND/OR` mode toggle. Active filter summaries in that row render one clause per line with a per-clause `X` remove button. Non-numeric popup value fields provide typeahead suggestions from that column, `Tab` accepts the top suggestion, and saving closes the popup while leaving a summary badge in-row. Header rows render in order: column names, filter row, then a blank spacer row before data. The same filtered dataset is applied to the score trend chart.
- Previous Runs table UI state is now browser-persistent (`localStorage`) for column visibility/order/width, column filters, quick-filter checkboxes, compare/control state (`outcome_field`, `compare_field`, `hold_constant_fields`, `split_field`, `view_mode`, `selected_groups`), sort order, and named view presets, so these customizations survive dashboard HTML rebuilds at the same dashboard path.
- `Isolate For X` was removed from `Previous Runs`; slicing is now done through Quick Filters and table column filters only.
- Older saved dashboard payloads/presets that still include isolate keys are tolerated on load; isolate keys are ignored and do not mutate current table filters.
- `Compare & Control` is now a sibling panel in `Previous Runs` with three modes:
  - `discover`: ranks likely driver fields from currently visible rows.
  - `raw`: direct categorical/numeric association metrics on visible rows; categorical output includes optional secondary means for runtime/token/cost-style numeric fields when available.
  - `controlled`: exact hold-constant strata metrics with explicit comparable-coverage reporting and weak-coverage warning text when comparable rows/strata are thin; categorical controlled means are stratum-standardized (shared stratum weights) to reduce confounded group-mix effects.
- Compare/control secondary metrics now skip constant-valued fields (including all-zero timing columns) so per-group summaries avoid misleading `0.000` side stats.
- `Previous Runs` now renders as two UI subsections:
  - `History Table & Trend` (primary trend chart + quick filters + table),
  - `Compare & Control Analysis` (compare/control panel + second trend-chart clone over the same filtered row set).
- `Compare & Control` also has a `Reset` action that restores default panel state without touching table filters.
- `Compare & Control` supports optional split-by segmentation (categorical buckets or equal-count numeric bins plus missing bucket).
- `Filter to subset` from `Compare & Control` writes selected categorical groups into existing table column filters (no separate filter engine).
- `Previous Runs` column filters now include a global `Across columns` combine mode (`AND` / `OR`) so cross-column OR is supported natively.
- `Quick Filters` now includes inline `View presets` controls (`Load`, `Save current view`, `Delete`) for reusable table setups (columns + filters + quick filters + sort + compare/control + column widths), without a separate presets popup.
- Diagnostic table resize now applies only to `Per-Label Breakdown`; `Boundary Classification` and `Benchmark Runtime` intentionally stay fixed-fit (no horizontal scroll/resize) for cleaner top-row readability.
- `Quick Filters` appears between trend chart and table with:
  - a primary default-on toggle for official single-offline benchmark rows (`benchmark-vs-golden` + `single-offline-benchmark`) with `vanilla`/`codexfarm` variants,
  - a secondary legacy toggle for excluding AI test/smoke rows that may still exist in older saved dashboard payloads.
  - a visible `Clear all filters` button that resets quick filters and table column filters together.
- `Previous Runs` table keeps horizontal scrolling with a fixed minimum table width, and the viewport stays at about 10 visible-row height (even when filtered result count is lower) before vertical scrolling.
- Clicking a `Previous Runs` table header now toggles sort direction for that column (`A→Z` / `Z→A`; numeric/date-aware where possible).
- Benchmark trend chart timestamps are rendered in browser-local time (`Highcharts time.useUTC=false`).
- Benchmark trend field selection is now checklist-based (`Trend fields` with `Select all` / `Clear`) and accepts any number of numeric benchmark fields.
- Benchmark trend score series are rendered as scatter points so only discrete run timestamps are shown (no connected interpolation line for raw points); each plotted series also gets a dashed linear trendline with a same-color `±1σ` deviation band.
- When paired single-offline variants are present, benchmark trend chart splits metric series by variant (`vanilla` vs `codexfarm`) so each pair is plotted separately.
- Paired variants now use one shared x-axis timestamp per benchmark run-group (artifact timestamp token preferred, row timestamp fallback), preventing same-run horizontal drift between `vanilla` and `codexfarm`.
- Benchmark trend tooltip is point-only: hovering a point shows that dot's own score plus source/book label, variant, and eval-row timestamp, without grouped run-level series values.
- Benchmark trend chart uses a fixed 800px render/container height to preserve stable layout and provide a taller score-history viewport.
- Dashboard HTML now loads Highcharts Stock with a secondary CDN fallback (`code.highcharts.com` primary, `cdn.jsdelivr.net` fallback) before dashboard JS initialization.
- `Previous Runs` table columns are configurable in-browser: use the `+/-` header-row button popup to check/uncheck fields, drag headers to reorder, and resize by dragging header edges.
- `Benchmark Score Trend` defaults to the `All` range selector window so initial render includes full available benchmark history.
- `Benchmark Score Trend` initializes x-axis bounds from the full filtered benchmark timestamp span, so chart timeline coverage matches `Previous Runs` dates even when older rows lack explicit score points.
- Main page is intentionally narrow in scope:
  - `Diagnostics (Latest Benchmark)`
  - `Previous Runs`

### `cookimport compare-control run` / `cookimport compare-control agent`

- Backend compare/control engine now lives in `cookimport/analytics/compare_control_engine.py` and mirrors dashboard semantics for:
  - derived fields (`source_label`, `ai_model`, `ai_effort`, `all_token_use`, `artifact_dir_basename`, `all_method_record`, `speed_suite_record`)
  - quick filters (`official_full_golden_only`, `exclude_ai_tests`)
  - column filter operators (`contains`, `not_contains`, `starts_with`, `ends_with`, `regex`, `gt`, `gte`, `lt`, `lte`, `eq`, `neq`, `is_empty`, `not_empty`)
  - compare/control analysis (`discover`, `raw`, `controlled`) and subset patch output (`eq` clauses + `or` mode).
- `run` is one-shot JSON output; `agent` is persistent JSONL over stdin/stdout.
- Agent mode keeps running after malformed request lines and returns structured error envelopes.
- New `insights` action auto-summarizes candidate rows (actionable drivers vs noisy high-cardinality fields, process-factor spreads, model-efficiency view, and suggested next compare-control queries).
- QualitySuite bench flows now auto-produce agent bridge bundles (`agent_compare_control/`) that precompute `insights` outputs per scope/outcome and provide ready JSONL follow-up requests for `compare-control agent`.
- Discovery-card ranking can now be tuned from backend/CLI:
  - one-shot via `compare-control run` discovery flags (`--discover-exclude-field`, `--discover-prefer-field`, `--discover-demote-pattern`, `--discover-max-cards`),
  - persisted dashboard behavior via `compare-control discovery-preferences` (writes to `assets/dashboard_ui_state.json`).

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
- Compatibility fallbacks for prior history locations (`<output_root parent>/.history/performance_history.csv`, `<output_root>/.history/performance_history.csv`) and stale all-method root-page cleanup are active renderer/collector hygiene rules.

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
- Trend series defaults are `strict_accuracy` and `macro_f1_excluding_other`, but users can now add/remove any numeric benchmark field from the trend field checklist.
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
- Trend points follow the selected numeric trend fields (defaulting to `strict_accuracy` + `macro_f1_excluding_other`), and chart x-axis bounds should still be initialized from the full filtered timestamp span so timeline coverage matches `Previous Runs`.
- Legacy benchmark rows with null explicit metrics are valid history rows and should remain visible in table/filter contexts.
- When dashboard history is intentionally culled to current artifact paradigms, remove stale benchmark CSV rows that point to legacy pytest/tmp/eval-vs-pipeline paths.
- CSV pruning alone is not enough if old benchmark run folders still exist on disk; collector behavior and artifact retention policy must stay aligned.


## 2026-03-03 merged understandings digest (dashboard/table/filter/runtime contracts)

- `2026-03-03_01.33.31` `dashboard-previous-runs-css-height-cap`: Previous Runs gaps came from nested benchmark CSV history plus a capped table viewport.
- `2026-03-03_09.11.03` `benchmark-trend-variant-series-split`: Benchmark Score Trend now separates paired codexfarm/vanilla runs into distinct series.
- `2026-03-03_09.39.48` `csv-benchmark-runtime-manifest-backfill-gap`: CSV-first benchmark rows could miss codex model metadata until collector backfilled from nearby manifests.
- `2026-03-03_10.02.32` `previous-runs-header-filter-row-contract`: Previous Runs filters are column-scoped with +/- popup editors; active summaries stay visible in the first row under headers.
- `2026-03-03_10.04.28` `benchmark-history-backfill-nested-csv-runtime-columns`: Some benchmark rows come from nested history CSVs; runtime backfill must update those files to affect Previous Runs model/effort columns.
- `2026-03-03_10.09.14` `dashboard-isolate-slice-filter-flow`: Dashboard isolate mode should run after existing column filters so Previous Runs and Benchmark Score Trend stay aligned.
- `2026-03-03_10.21.04` `benchmark-codexfarm-token-usage-history-backfill`: Benchmark CSV/dashboard now persist CodexFarm token usage fields and backfill them from manifests when available.
- `2026-03-03_10.25.59` `previous-runs-filter-row-spacer-order`: Previous Runs now renders filter controls immediately under headers, with a dedicated blank spacer row after filters.
- `2026-03-03_10.29.22` `dashboard-all-token-use-computed-column`: Previous Runs now has an `All token use` computed column that renders total/input/output while sorting/filtering on tokens_total.
- `2026-03-03_10.39.32` `dashboard-per-label-variant-rolling-aggregation`: Per-label diagnostics should aggregate latest run at timestamp, then split run + rolling metrics by codexfarm/vanilla variant without cross-mixing.
- `2026-03-03_10.39.46` `boundary-card-matched-only-context`: Discovery: Boundary Card Can Look Artificially Perfect
- `2026-03-03_10.39.48` `dashboard-ui-state-persistence-localstorage`: Dashboard Previous Runs customization state was in-memory only; persistence now uses browser localStorage.
- `2026-03-03_10.40.00` `dashboard-quick-filters-official-benchmark-scope`: Dashboard quick checkboxes should filter benchmark rows through currentPreviousRunsFilterResult so chart, table, and isolate stay aligned.
- `2026-03-03_10.41.56` `dashboard-previous-runs-sticky-header-overlap`: Previous Runs sticky header/filter rows can visually overlap body rows when table border-collapse stays collapsed.
- `2026-03-03_10.44.19` `boundary-table-unmatched-gold-row`: Discovery: Boundary Table Needed Gold-Denominator Context In-Table
- `2026-03-03_10.47.01` `dashboard-sticky-header-relative-override`: Previous Runs sticky rows break when '#previous-runs-table th' sets position: relative, because row top offsets then shift relative instead of sticky.
- `2026-03-03_10.48.38` `dashboard-table-column-resize-state-plumbing`: Dashboard column width persistence flows through localStorage UI state; Previous Runs had width plumbing while diagnostics tables needed shared resize wiring.
- `2026-03-03_10.52.42` `boundary-card-denominator-cleanup`: Discovery: Boundary Table Needed One Denominator
- `2026-03-03_11.00.46` `dashboard-highcharts-secondary-cdn-fallback`: Benchmark trend chart fallback text can appear from transient single-CDN Highcharts load failures; add a second CDN fallback in dashboard HTML.
- `2026-03-03_11.16.23` `dashboard-all-token-use-cached-discount`: `All token use` now discounts cached input tokens to 10% weight and sorts/filters on that discounted total.
- `2026-03-03_11.25.12` `top-diagnostics-fit-and-runtime-dedupe`: Discovery: Top Diagnostics Needed Fixed-Fit Tables
- `2026-03-03_11.26.00` `runtime-token-card-discounted-vs-raw`: Benchmark Runtime token row now mirrors `All token use` discounted math and also shows raw total tokens.
- `2026-03-03_11.29.35` `runtime-token-use-label-and-raw-row-prune`: Discovery: Runtime Token Display Should Match One Metric
- `2026-03-03_11.30.19` `dashboard-isolate-stacked-rules-flow`: Dashboard isolate mode now supports stacked rules with AND/OR combine logic while staying aligned with existing quick/column filters.
- `2026-03-03_11.33.58` `dashboard-previous-runs-view-presets-state-shape`: Previous Runs presets should reuse the same UI-state shape as live controls to keep save/load behavior stable.
- `2026-03-03_11.36.11` `dashboard-program-side-ui-state-persistence`: Dashboard UI state can only be written program-side through an HTTP endpoint; static file mode remains localStorage-only.
- `2026-03-03_11.38.01` `stats-dashboard-optioninfo-direct-call`: Direct Python calls to stats_dashboard can receive Typer OptionInfo defaults unless unwrapped first.
- `2026-03-03_11.40.07` `dashboard-quick-filters-primary-official-advanced-ai-tests`: Quick Filters now keep official-only as the primary toggle while rendering test/smoke exclusion as a second checkbox in the same group.
- `2026-03-03_11.41.44` `dashboard-isolate-vs-table-filter-last-edited-wins`: Previous Runs now uses last-edited-wins handoff between isolate rules and table column filters.
- `2026-03-03_11.43.35` `dashboard-diagnostics-run-group-vs-eval-timestamp`: Per-label and boundary diagnostics must group latest benchmark rows by run-group key, not exact eval timestamp, so twinned vanilla/codexfarm rows aggregate together.
- `2026-03-03_11.46.52` `dashboard-previous-runs-clear-all-filters-scope`: Previous Runs clear-all now resets quick filters, table column filters, and isolate rules together.
- `2026-03-03_11.47.44` `dashboard-filter-summary-per-clause-lines`: Previous Runs filter summary row is built in renderPreviousRunsTableColumns and can remove clauses directly without opening the popup.
- `2026-03-03_12.00.09` `dashboard-presets-popout-in-quick-filters`: Historical note: dashboard presets were temporarily moved to a Quick Filters popout before later returning to inline controls.
- `2026-03-03_12.04.48` `dashboard-quick-filters-inline-presets-controls`: Previous Runs preset controls now render inline inside Quick Filters instead of behind a presets popup.
- `2026-03-03_12.30.35` `dashboard-per-label-delta-baseline-flow`: Per-label diagnostics should keep latest-run codexfarm precision/recall as raw baseline columns and anchor other deltas to that same-label baseline.
- `2026-03-03_12.56.20` `dashboard-per-label-rolling-n-selector-state`: Per-label rolling N should be UI-state-backed and update rolling column headers plus aggregation windows in sync.
- `2026-03-03_12.56.51` `dashboard-ai-effort-suppression-reverted`: Removed hard-coded AI effort suppression for three SeaAndSmoke benchmark rows so CSV/runtime effort renders as-is.
- `2026-03-03_13.02.02` `dashboard-collector-hard-excludes-gate-test-runs`: Stats dashboard must drop gate/test benchmark artifacts at collector time so diagnostics never pick them as latest runs.
- `2026-03-03_15.40.00` `dashboard-previous-runs-column-popup-control`: Previous Runs column visibility is now controlled by a header-adjacent +/- popup checklist.
- `2026-03-03_16.12.00` `dashboard-known-backfilled-ai-effort-suppression`: Historical note: dashboard once suppressed AI effort for three SeaAndSmoke benchmark rows; behavior was later reverted.

## 2026-03-03 docs/tasks merge digest (dashboard gate/test exclusion + vanilla AI suppression)

Merged source task files (timestamp/file order):
- `docs/tasks/2026-03-03_13.02.16-dashboard-hard-exclude-gate-test-runs.md`
- `docs/tasks/2026-03-03_13.13.06-dashboard-vanilla-ai-runtime-suppression.md`

Current contract additions/reminders:
- Gate/test/smoke benchmark artifacts are excluded at collector input time (CSV and report-scan paths), not only in JS quick filters, so diagnostics and `Previous Runs` share the same exclusion policy.
- Exclusion policy remains deterministic/path-token based (`/bench/`, pytest temp layouts, gated/smoke/test timestamp suffix markers).
- `Previous Runs` AI runtime display is variant-aware: rows classified as `vanilla` suppress `AI Model` and `AI Effort` display even if stale/backfilled codex keys exist in `run_config`.
- Vanilla suppression is display-layer only; historical CSV/manifests are not rewritten.


## 2026-03-03 merged understandings digest (docs/understandings cleanup)

This section consolidates notes that were previously in `docs/understandings`.
Detailed chronology and preserved deep notes are in `08-analytics_log.md`.

Merged source notes (chronological):
- `2026-03-03_13.13.20-dashboard-vanilla-runtime-display-guard.md`: Discovery: vanilla benchmark variants can inherit codex runtime metadata, so dashboard AI columns need variant-aware suppression.
- `2026-03-03_16.11.09-dashboard-per-label-comparison-mode-toggle.md`: Per-Label comparison cells should share one mode switch (delta vs point value) while preserving baseline-relative coloring.
- `2026-03-03_19.42.15-dashboard-trend-overlay-series-contract.md`: Benchmark trend overlays should be layered from base scatter series and excluded from grouped tooltips.
- `2026-03-03_19.55.01-isolate-column-filter-global-or.md`: Isolate-to-table unification requires a native cross-column OR combine mode in the Previous Runs column-filter evaluator.
- `2026-03-03_19.59.39-dashboard-trend-paired-variant-xaxis-alignment.md`: Benchmark trend paired variants drifted on X because each point used eval-row timestamp instead of run-group timestamp.
- `2026-03-03_20.32.36-isolate-numeric-operator-contract.md`: Isolate numeric comparisons require field-typed operator sets and numeric-value normalization before syncing into table filters.

### 2026-03-03_21.50.00 isolateforxv2 dashboard seam reminder

- `stats-dashboard` UI behavior is generated from `cookimport/analytics/dashboard_render.py` (`_HTML`, `_CSS`, `_JS`) rather than a separate frontend source tree.
- `Isolate For X` already syncs into table filters via `applyIsolateRulesToTableFilters` and uses the same evaluator path (`recordMatchesPreviousRunsFilterGroups` + `evaluatePreviousRunsFilterOperator`).
- Previous Runs/preset persistence remains anchored in `buildDashboardUiStatePayload` / `applyDashboardUiStatePayload`.
- Compare/Control planning should extend these seams and use `tests/analytics/test_stats_dashboard.py` as the contract test anchor.

## 2026-03-03 docs/tasks consolidation batch (Per-Label mode, trend overlays, isolate/table unification)

Merged source task files (timestamp/file order):
- `docs/tasks/2026-03-03_16.11.20-per-label-point-value-toggle.md`
- `docs/tasks/2026-03-03_19.42.12-dashboard-trendline-std-band.md`
- `docs/tasks/2026-03-03_19.56.30-isolate-table-filter-unification.md`
- `docs/tasks/2026-03-03_19.59.52-dashboard-paired-variant-xaxis-alignment.md`
- `docs/tasks/2026-03-03_20.33.20-isolate-numeric-boolean-logic.md`

Current analytics contracts added/confirmed:
- `Per-Label Breakdown` comparison columns share one persisted mode switch (`delta` vs `point value`) through `per_label_comparison_mode`; codex baseline columns remain raw anchors.
- Benchmark trend chart overlays are derived from base scatter series and include dashed linear trendline + `±1σ` `arearange` bands, with overlay series excluded from grouped tooltip rows.
- Trend points for paired codexfarm/vanilla rows align on run-group timestamps (artifact-path-derived when available), then row timestamp fallback.
- `Previous Runs` filtering is table-filter-only (plus quick filters), and cross-column `OR` remains a first-class global mode (`column_filter_global_mode`).

Anti-loop reminders from this task batch:
- If table filter results diverge from trend/table row counts, verify global combine mode + quick-filter application order before changing row-match helpers.
- If paired trend points drift horizontally, inspect run-group timestamp extraction logic before changing chart series split behavior.
- If trend overlays render blank, confirm `highcharts-more.js` fallback is loaded for `arearange` support.

## 2026-03-03 docs/tasks merge digest (Compare/Control evolution and isolate removal)

Merged source task files (timestamp/file order):
- `docs/tasks/IsolateForXv2.md`
- `docs/tasks/2026-03-03_22.54.59-remove-isolate-for-x-dashboard.md`
- `docs/tasks/2026-03-03_23.05.29-compare-control-agent-cli.md`

Current analytics contracts to keep:
- Compare/Control started as a sibling panel to Isolate in Previous Runs, sharing the same filtered row pool (`computePreviousRunsFilterResult`) and the same table-filter write path for `Filter to subset`.
- Isolate was then intentionally removed end-to-end (HTML/CSS/JS/state/status text) to keep one slicing path (quick filters + table filters) and one analysis path (Compare/Control), while preserving backward compatibility for old saved UI payloads that still contain isolate keys.
- Compare/Control semantics that must remain stable:
  - views: `discover`, `raw`, `controlled`
  - controlled categorical mode uses stratum-standardized weighting with explicit coverage diagnostics (`used_rows`, `candidate_rows`, `used_strata`, `total_strata`)
  - subset action writes deterministic table clauses (`eq` + `or` mode for selected groups)
- Backend parity now exists via `cookimport compare-control`:
  - deterministic Python engine: `cookimport/analytics/compare_control_engine.py`
  - one-shot mode: `cookimport compare-control run`
  - JSONL agent loop: `cookimport compare-control agent`
  - agent actions include `discover`, `analyze`, `insights`, `subset_filter_patch`, `suggest_hold_constants`, `suggest_splits`.
- QualitySuite handoff contract now includes `agent_compare_control/` bridge bundles (index + insights + `agent_requests.jsonl` + README) so agent workflows can move directly from quality verdicts to compare/control drill-down without rediscovery.

Anti-loop reminders from this batch:
- Do not re-introduce a parallel isolate evaluator path; compare/control + table filters should stay on one semantics engine.
- If dashboard and backend compare/control disagree, validate derived field semantics (`source_label`, `ai_model`, `ai_effort`, `all_token_use`, `artifact_dir_basename`) before changing metric formulas.
- If old presets look odd after isolate removal, fix payload migration/sanitization first rather than adding isolate UI back.

## 2026-03-04 docs/understandings merge digest (Compare/Control completion wave)

Merged source notes (timestamp order):
- `2026-03-03_22.00.24-compare-control-dashboard-seams.md`: Compare & Control implementation discovery: reuse Previous Runs filtered-row output and table-filter writer seams to avoid parallel filtering logic.
- `2026-03-03_22.22.36-compare-control-gap-closure.md`: Gap-closure design for Compare & Control: secondary categorical metrics, weak coverage warnings, and legacy state compatibility checks.
- `2026-03-03_22.31.58-isolateforxv2-og-vs-implementation-audit.md`: Audit result: IsolateForXv2 OG milestones are implemented; remaining gap is mostly behavioral test depth for compare/control math and filter handoff.
- `2026-03-03_22.38.48-compare-control-categorical-controlled-weighting-fix.md`: Compare & Control categorical controlled mode now uses stratum-standardized weighting; added Node harness tests for confounding reversal and Filter-to-subset clause writes.
- `2026-03-03_22.45.05-compare-control-vs-isolate-intent.md`: Dashboard intent check: Compare & Control complements Isolate For X; it was not intended to replace it.
- `2026-03-03_22.54.37-dashboard-isolate-removal-seams.md`: Isolate For X removal seam map: delete isolate UI/logic, keep compare/control and table filter pipeline as the single slice path.
- `2026-03-03_22.58.03-compare-control-view-mode-discover-raw-controlled.md`: Compare & Control view semantics: `discover` is field-finding mode; `raw` and `controlled` are analysis modes.
- `2026-03-03_23.04.55-dashboard-previous-runs-metrics-sources.md`: Source map for where Previous Runs metrics and derived fields come from.
- `2026-03-03_23.05.29-compare-control-backend-cli-seams.md`: Seam map for adding a backend Compare & Control CLI without diverging from dashboard behavior.
- `2026-03-03_23.17.54-compare-control-agent-cli-plan-hardening.md`: Hardening notes for backend Compare & Control CLI plan: JS seam map, test anchors, and Typer integration points.
- `2026-03-03_23.38.21-compare-control-cli-usage-playbook.md`: Practical usage playbook for compare-control run/agent based on real local-output trials.
- `2026-03-03_23.40.00-compare-control-backend-engine-parity-implementation.md`: Backend Compare & Control engine implementation note: JS parity seams mirrored in Python and exposed via run/agent CLI surfaces.
- `2026-03-03_23.48.14-compare-control-insights-action-implementation.md`: Compare-control insights action: auto-profile + actionable driver filtering + process-factor deltas.
- `2026-03-03_23.57.39-per-label-run-selector-seam.md`: Per-label diagnostics run selector seam map in dashboard_render.js template.
- `2026-03-04_00.08.03-compare-control-discovery-preferences-cli-bridge.md`: Compare & Control discovery cards can now be tuned from backend/CLI via shared discovery-preferences state.

Current analytics contracts reinforced by this batch:
- Compare/Control and Previous Runs table filters must continue sharing one row-selection engine; avoid introducing parallel filtering/evaluation paths.
- Controlled categorical analysis uses stratum-standardized weighting and should keep explicit weak-coverage messaging.
- Backend compare-control parity (`run`/`agent`/`insights`) is part of the maintained contract, not an optional side tool.
- Discovery/analysis modes remain distinct (`discover` for field finding, `raw`/`controlled` for inference) and this wording should stay explicit in UI/docs.
- Per-label and compare-control run selectors should remain state-backed and deterministic across reload/preset restores.

## 2026-03-04 merged understandings digest (trend controls, history roots, layout/rerender stability)

Merged source notes (timestamp order):
- `2026-03-04_00.14.17-per-label-missing-variant-zero-coercion.md`
- `2026-03-04_00.17.57-benchmark-trend-run-group-token-selection.md`
- `2026-03-04_00.21.08-compare-control-secondary-constant-zero.md`
- `2026-03-04_00.38.37-codexfarm-pass3-token-trend-query.md`
- `2026-03-04_00.41.49-previous-runs-two-section-two-chart-layout.md`
- `2026-03-04_00.44.24-dashboard-trend-field-selection-contract.md`
- `2026-03-04_00.48.32-history-root-repo-local-vs-external.md`
- `2026-03-04_00.50.58-previous-runs-grid-min-content-width-leak.md`
- `2026-03-04_00.58.21-benchmark-trend-host-rerender-cleanup.md`

Current analytics contracts reinforced:
- Missing comparison-variant per-label values must render as `-`, not coerced `0.0000` values.
- Trend run-group extraction must prefer the shared benchmark run token after `benchmark-vs-golden` to keep paired variant x-axis alignment stable.
- Compare/control secondary metric selection must require numeric variation so constant side-metrics are suppressed.
- Trend UI now supports state-backed arbitrary numeric field selection (`Trend fields` checklist, `trend_fields` persisted in UI state).
- Previous Runs layout uses two subsection cards with two chart hosts sharing one filtered-row pool (`benchmark-trend-chart`, `compare-control-trend-chart`).
- Trend host redraws must destroy/clear existing chart instances before re-render to avoid cumulative markup/width growth.
- Trend host redraws now also pin Highcharts `chart.width` to measured host width so timed rerenders cannot slowly widen host internals.
- History root behavior is repo-aware: repo-local outputs use `<repo>/.history`, external outputs keep sibling `.history`; compatibility reads of older locations remain required.

Operator query contract preserved:
- Pass-level codex token trend checks should read `llmCodexFarm.process_runs.pass{1,2,3}.telemetry.rows[*].tokens_total` from report JSON artifacts and compare over run timestamps.

Anti-loop reminders:
- If paired trend points drift, inspect run-group token extraction before touching chart plotting logic.
- If trend panels grow/duplicate after repeated filter changes, inspect host-destroy/host-clear sequencing first.
- If dashboard history appears missing after output-root changes, verify history-root resolution and fallback-read probes before changing collector logic.

## 2026-03-04 merged understandings digest (pixel overflow containment seam)

Merged source note:
- `2026-03-04_01.06.35-previous-runs-pixel-overflow-source.md`

Current analytics/UI containment contract reinforced:
- Previous Runs page-level horizontal growth can come from long unwrapped Compare & Control tokens, not only chart/table widths.
- Section-level containment must keep overflow local:
  - hide horizontal overflow at previous-runs section/subsection containers,
  - enable aggressive wrapping in compare/control result text (`overflow-wrap: anywhere`, `word-break: break-word`).
- Local table scrolling remains the approved path for wide tabular content.

Anti-loop reminder:
- If rightward growth recurs, check page-level `scrollWidth - clientWidth` and long-token wrapping behavior before altering trend chart sizing.

## 2026-03-04 docs/tasks merge digest (trend-field controls + overflow/rerender containment)

Merged source task files (timestamp order):
- `docs/tasks/2026-03-04_00.44.24-dashboard-trend-arbitrary-fields.md`
- `docs/tasks/2026-03-04_00.50.57-previous-runs-rightward-growth-containment.md`
- `docs/tasks/2026-03-04_00.58.20-benchmark-trend-host-rerender-cleanup.md`
- `docs/tasks/2026-03-04_01.06.34-previous-runs-pixel-overflow-guard.md`

Current analytics contracts reinforced:
- Trend chart series are no longer fixed to two metrics; users can add/remove any number of numeric trend fields via state-backed controls.
- Trend behavior must preserve paired variant split, shared run-group x-axis alignment, and overlay rendering regardless of selected fields.
- Previous Runs layout containment is a section-level contract (`minmax(0, 1fr)` grid constraints + `min-width: 0` guards + overflow containment), while wide tables remain locally scrollable.
- Trend host rerenders must clear/destroy prior host-specific chart instances before redraw/fallback transitions.
- Trend drift regressions may hide at host level (`host.scrollWidth` growth) even when page-level `document.scrollWidth` remains stable; include host-level drift probes.
- Pixel-level overflow checks are valid regression anchors for page-growth issues; compare/control long-token wrapping is required to prevent page-level horizontal expansion.

Anti-loop reminders:
- If trend series regress after UI tweaks, check selected-field normalization/state persistence first.
- If rightward growth returns, inspect both host cleanup lifecycle and long-token wrapping before altering table min-width contracts.

## 2026-03-04 merged understandings digest (Previous Runs width persistence + trend host drift)

Merged source notes (timestamp order):
- `docs/understandings/2026-03-04_01.18.36-previous-runs-column-width-state-clamp.md`
- `docs/understandings/2026-03-04_01.45.33-trend-host-width-drift-vs-page-overflow.md`

Current analytics contracts reinforced:
- Persisted Previous Runs column widths must be normalized and clamped at load/save/resize boundaries (`72..1200px`) so stale local state cannot force unbounded layout growth.
- Trend drift diagnosis must include host-level overflow probes (`host.scrollWidth - host.clientWidth`) because page-level overflow checks can stay flat while chart hosts still widen internally.
- Trend chart rerenders should keep host-width pinning and host-local cleanup to prevent cumulative width creep across repeated redraws.

Anti-loop reminder:
- If the page width looks stable but trend cards still visually stretch, inspect host-level drift metrics before changing global container CSS.

## 2026-03-04 docs/tasks merge digest (pixel overflow + trend-host drift guards)

Merged source task files (timestamp order):
- `docs/tasks/2026-03-04_01.20.21-previous-runs-real-pixel-overflow-guard.md`
- `docs/tasks/2026-03-04_01.45.22-trend-host-width-drift-guard.md`

Current analytics contracts reinforced:
- Use browser-level pixel probes for rightward-growth regressions; static CSS/string checks are not sufficient for live rerender behavior.
- Keep Previous Runs containment at section/wrapper boundaries and preserve local table scroll contracts.
- Ensure long Compare/Control tokens wrap aggressively to prevent document-level horizontal overflow.
- Guard trend host drift with host-level metrics over timed rerenders and pin chart width to measured host width.
- Keep CDN-independent harness behavior in tests (chart scripts stubbed/controlled) for deterministic regression detection.

Known failure patterns retained:
- Page-level overflow can look stable while host-level chart width still drifts.
- Removing table min-widths can mask symptoms while degrading readability; containment belongs in wrapper/grid policy.

## 2026-03-04 docs/tasks consolidation (runtime-card run-group metrics + trend tooltip contracts)

Merged source task files (timestamp order):
- `docs/tasks/2026-03-04_08.27.09 - runtime-card-run-group-token-totals.md`
- `docs/tasks/2026-03-04_08.46.21 - dashboard-quality-per-token-metric.md`
- `docs/tasks/2026-03-04_08.49.13 - benchmark-trend-tooltip-point-details.md`
- `docs/tasks/2026-03-04_09.02.37 - benchmark-trend-tooltip-book-only.md`

Current analytics contracts reinforced:
- `Benchmark Runtime` token totals aggregate across the latest preferred benchmark run-group (not a single row), and runtime title/context indicate grouped scope.
- Runtime diagnostics and Previous Runs now expose quality efficiency using deterministic quality selection priority (`strict_accuracy`, then `macro_f1_excluding_other`, then `f1`) normalized per 1,000,000 discounted tokens.
- `Previous Runs` keeps numeric `quality_per_million_tokens` for sorting/filtering/compare.
- Trend tooltip metadata pipeline now includes point-level source/variant/timestamp payload and is intentionally point/book-only in rendered hover cards.
- Run-group summary rows were intentionally removed from trend tooltip cards after point-level metadata landed.

Regression anchors from merged tasks:
- `tests/analytics/test_stats_dashboard.py`
- specifically task-linked selectors around runtime-summary aggregation, quality-per-token derivation, and trend tooltip metadata/content assertions.

## 2026-03-04 docs/understandings consolidation (CSV migration supplement + runtime/tooltip metric seams)

Merged source notes (timestamp order):
- `docs/understandings/2026-03-04_08.19.19-dashboard-migration-benchmark-history-gap.md`
- `docs/understandings/2026-03-04_08.27.09-runtime-card-latest-run-group-token-sum.md`
- `docs/understandings/2026-03-04_08.46.21-quality-token-metric-runtime-and-table.md`
- `docs/understandings/2026-03-04_08.49.13-trend-tooltip-point-metadata.md`

Current analytics contracts reinforced:
- Benchmark collection is CSV-first, but migrated workspaces may need automatic supplementation of older pre-CSV `eval_report.json` rows.
- Runtime token diagnostics aggregate across latest preferred run-group, not one row.
- `all_token_use` discounted token math is shared between runtime diagnostics and Previous Runs derived metrics.
- `quality_per_million_tokens` uses deterministic quality-key fallback and discounted token denominator.
- Trend tooltip point metadata contract (`sourceLabel/sourceTitle/variant/runTimestamp`) remains required for per-point hover context.
