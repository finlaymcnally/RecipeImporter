---
summary: "Analytics architecture and implementation history log: versions, experiments, reversals, fixes, and provenance to prevent repeated loops."
read_when:
  - When iterating on analytics/dashboard changes and you need to verify what was already tried
  - When a task is going in multi-turn circles, or the human says "we are going in circles on this"
  - When reconciling behavior differences across analytics/dashboard versions
---

# 08 Analytics Log

Historical log for analytics decisions that still map to active code paths.

This file was pruned to remove branches tied to retired dashboard surfaces.
Use `08-analytics_readme.md` for current behavior.

## 1) Timeline (active-relevance only)

### 2026-02-01 performance observability + parallel staging foundation

Still-relevant outcomes:
- Timing/checkpoint data became first-class in conversion reports.
- Stage flow gained worker/split controls and parallel processing defaults.
- Analytics surfaces (report -> CSV -> dashboard) became stable enough for regression testing.

Anti-loop note:
- Old notes assuming sequential staging are obsolete.

### 2026-02-15 file:// dashboard loading fallback

Problem solved:
- Browser local-file mode could block `fetch("assets/dashboard_data.json")`.

Durable fix:
- `index.html` embeds inline dashboard JSON.
- JS loads inline first, then falls back to fetch.

### 2026-02-15 benchmark metadata merge by artifact directory

Problem solved:
- Benchmark metadata can live in both eval root and `prediction-run/`.
- Timestamp-only merge caused duplicates.

Durable fix:
- Merge benchmark records by artifact path identity.
- Probe both eval root and `prediction-run/` for enrichment files.

### 2026-02-16 mixed timestamp sorting support

Problem solved:
- Datasets mixed folder-style timestamps and ISO strings.

Durable fix:
- Collector and renderer sort by parsed timestamps, not raw lexical order.
- Unparseable values remain visible and sort last where applicable.

### 2026-02-16 benchmark artifact hygiene + recipe-count reliability

Still-relevant decisions:
- Ignore pytest temp benchmark artifact paths in dashboard collection.
- Persist benchmark `recipes` across benchmark append paths.
- Provide `benchmark-csv-backfill` for historical rows missing `recipes` / `report_path` / `file_name`.

### 2026-02-16 run-config propagation into analytics surfaces

Still-relevant contract:
- Keep `run_config_hash`, `run_config_summary`, and `run_config_json` in CSV for stage and benchmark rows.
- Collector can fall back to report/manifest reads when CSV run-config context is missing.

### 2026-02-16 history-root alignment

Still-relevant contract:
- History CSV path is derived from output root via helper (`history_csv_for_output`).
- Effective location is `<output_root parent>/.history/performance_history.csv`.

### 2026-02-23 baseline static dashboard contract

Still-relevant decisions:
- Keep dashboard static/offline and collector read-only.
- Keep category separation to avoid accidental double-counting.
- Do not mutate run artifacts during dashboard generation.

### 2026-02-24 all-method standalone pages and hierarchy

Still-relevant outcomes:
- All-method pages moved under `all-method-benchmark/` subfolder.
- Hierarchy became explicit: run index -> run summary -> per-book detail.
- Run-level aggregation groups by `run_config_hash` when present (slug/name fallback for older rows).
- All-method run index is always generated even when run count is zero.

### 2026-02-24 all-method chart semantics

Still-relevant outcomes:
- Run/detail pages include summary tables, metric bars, and radar charts.
- Score metrics render on fixed `0..100%` axes.
- Recipes metric is normalized as `% identified` against `gold_recipe_headers`.

### 2026-02-24 dashboard refresh after history writes

Still-relevant outcomes:
- CSV appenders trigger best-effort dashboard refresh.
- All-method internal benchmark flows batch refresh to avoid excessive or conflicting writes.
- Refresh inference depends on canonical history CSV path shape.

### 2026-02-25 main dashboard index scope reduction

Still-relevant UI contract:
- Main dashboard index focuses on:
  - `All-Method Benchmark Runs`
  - `Diagnostics (Latest Benchmark)`
  - `Previous Runs`

Anti-loop note:
- Throughput/filter/KPI-era main-index documentation is historical only and not active UI behavior.

### 2026-02-27 processing telemetry plumbing boundaries

Still-relevant architecture note:
- Telemetry has two surfaces:
  - shared wrapper path (`_run_with_progress_status(...)`)
  - stage-local progress path in `stage(...)`

Anti-loop note:
- Wrapper-only telemetry changes do not automatically affect stage telemetry artifacts.

### 2026-02-27 benchmark timing telemetry foundations

Still-relevant outcome:
- Benchmark timing fields were added as additive CSV/report metadata.
- `collect_all_method_timing_summary(...)` exists as helper foundation.

### 2026-02-28 benchmark CSV append ownership + refresh wiring

Still-relevant outcomes:
- Benchmark CSV rows are appended by multiple CLI entrypoints (`labelstudio-eval`, `labelstudio-benchmark`, `bench run`), not only `perf-report`/`stage`.
- Best-effort dashboard refresh is centralized in `_refresh_dashboard_after_history_write(...)` and targets the same history-root dashboard folder when path inference is canonical.

Anti-loop note:
- If `performance_history.csv` is written at a non-canonical custom path, automatic refresh may be skipped by design; run `cookimport stats-dashboard` explicitly in that case.

### 2026-02-28 collector compatibility + all-method output hygiene

Still-relevant outcomes:
- Dashboard collector compatibility now includes a legacy history lookup fallback (`<output_root>/.history/performance_history.csv`) when canonical history path is absent.
- Renderer clears stale legacy all-method root pages before writing the current `all-method-benchmark/` hierarchy.

### 2026-02-27_19.34.01 docs-task retirement target mapping

Durable decision:
- Benchmark runtime/scheduler/matcher closeouts belong in `docs/07-bench`; cross-flow telemetry plumbing ownership belongs in `docs/08-analytics`.

### 2026-02-27_19.46.24 analytics doc prune active-vs-retired surfaces

Problem captured:
- Analytics docs still mixed active dashboard surface with retired throughput/filter/KPI branches.

Durable decisions:
- Keep tested main-index contract (`All-Method Benchmark Runs`, `Diagnostics`, `Previous Runs`).
- Keep retired main-index branches demoted to historical notes only.

### 2026-02-27_19.52.19 removed-feature prune map

Durable decision:
- Removed-feature chronology should be retained only where it prevents loops, not as active contract text.

### 2026-02-27_19.52.27 analytics docs code-surface gap audit

Problem captured:
- Analytics docs under-described CLI/paths ownership and history-write entrypoints.

Durable decisions:
- Keep command ownership mapping explicit for benchmark/history writes.
- Keep legacy history-path fallback and all-method output-hygiene behavior documented.

## 2026-02-28 migrated understanding ledger

Chronological migration from `docs/understandings`; source files were removed after this merge.

### 2026-02-27_20.24.21 dashboard per label latest run aggregation

Source: `docs/understandings/2026-02-27_20.24.21-dashboard-per-label-latest-run-aggregation.md`
Summary: Stats dashboard per-label card now aggregates per-label totals across all records in the latest all-method run timestamp (fallback to latest benchmark timestamp if no all-method rows exist).

Details preserved:


# Dashboard Per-Label Latest-Run Aggregation

- Previous behavior: `renderPerLabel()` selected a single latest benchmark record with per-label data and rendered that row set directly.
- Intermediate behavior: grouped by latest benchmark `run_timestamp` across all benchmark records, which could pick speed-suite/matcher-probe rows instead of all-method runs.
- Current behavior: prefers rows under `/all-method-benchmark/`, then groups by the latest timestamp in that subset and aggregates each label across that run. If no all-method rows exist, falls back to latest benchmark timestamp grouping.
- Aggregated precision/recall are recomputed from summed totals (gold/pred weighted), so the card reflects the whole latest run batch.


## 2026-02-28 migrated understanding ledger (03:42-04:02 analytics batch)

### 2026-02-28_03.42.13 single-profile dashboard sweep grouping gap

Source: `docs/understandings/2026-02-28_03.42.13-single-profile-dashboard-sweep-grouping-gap.md`

Problem captured:
- Single-profile all-matched benchmark outputs existed on disk but were missing from all-method dashboard index.

Durable decisions:
- Group collector rows from both classic all-method config paths and single-profile source paths.
- Treat single-profile rows as one run-profile unit (prefer `run_config_hash`) so cross-book run aggregation remains stable.

### 2026-02-28_03.52.45 suffixed timestamp per-label grouping gap

Source: `docs/understandings/2026-02-28_03.52.45-suffixed-run-timestamp-per-label-grouping-gap.md`

Problem captured:
- Suffixed run folders caused timestamp parse fallback to `config_*` dir names, fragmenting one run into many one-eval pseudo-runs.

Durable decisions:
- Normalize timestamp-prefixed folder names (with optional suffix) to bare `YYYY-MM-DD_HH.MM.SS` for grouping.
- Keep regression coverage in analytics dashboard tests for suffixed-folder behavior.

### 2026-02-28_03.58.19 speed-suite max-targets causes one-eval diagnostics

Source: `docs/understandings/2026-02-28_03.58.19-speed-suite-max-targets-causes-one-eval-per-label.md`

Findings preserved:
- Latest benchmark diagnostics can legitimately show one eval when the most recent speed run selected one target.
- This is a data-selection artifact, not necessarily collector/render failure.

Anti-loop note:
- Confirm `suite_resolved.json` target selection and `run_manifest.json` counts before changing per-label aggregation logic.

### 2026-02-28_04.02.14 diagnostics prefer non-speed benchmarks

Source: `docs/understandings/2026-02-28_04.02.14-dashboard-diagnostics-prefer-non-speed-benchmarks.md`

Problem captured:
- One-target speed-suite runs could override richer multi-book benchmark diagnostics due latest-timestamp-only selection.

Durable decisions:
- Diagnostics selector now prefers non-speed benchmark rows when available.
- Speed rows remain fallback path when no non-speed benchmark rows exist.

## 2026-02-28 migrated understanding ledger (04:08 diagnostics normalization red/green)

### 2026-02-28_04.08.22 dashboard diagnostics path normalization red/green

Source: `docs/understandings/2026-02-28_04.08.22-dashboard-diagnostics-path-normalization-red-green.md`

Problem captured:
- Diagnostics selectors could choose speed-suite benchmark rows when path separators differed from expected slash style.

Red phase preserved:
- Added regression assertions in `tests/analytics/test_stats_dashboard.py` requiring diagnostics selectors to use normalized benchmark-path helpers.
- Initial run failed (`2 failed`) before renderer updates.

Green phase preserved:
- Added JS helper functions in `dashboard_render.py`:
  - `benchmarkArtifactPath(record)`
  - `isSpeedBenchmarkRecord(record)`
  - `isAllMethodBenchmarkRecord(record)`
- Updated diagnostics selection logic to use these helpers.
- Tests passed after update and regenerated dashboard selected non-speed multi-book timestamp for diagnostics.

Anti-loop note:
- Path-normalization regressions should be fixed in helper functions first; avoid patching selector call-sites with one-off string checks.

## 2026-02-28 docs/tasks consolidation batch (dashboard chart interaction default)

### 2026-02-28_12.18.03 disable Highcharts mouse-wheel zoom

Source task file:
- `docs/tasks/2026-02-28_12.18.03-disable-dashboard-highcharts-wheel-zoom.md`

Problem captured:
- Dashboard trend-chart wheel zoom caused frequent accidental zoom while users were just scrolling page content.

Durable decisions/outcomes:
- Added a global dashboard default for Highcharts mouse-wheel zoom off.
- Kept a clear, single toggle (`HIGHCHARTS_MOUSE_WHEEL_ZOOM_ENABLED`) for future re-enable.
- Implemented via dashboard init `Highcharts.setOptions(...)` so behavior applies to all dashboard charts consistently.

Evidence preserved:
- `pytest tests/analytics/test_stats_dashboard.py -k benchmark_trend_chart_uses_fixed_height`
- `pytest tests/analytics/test_stats_dashboard.py`

Anti-loop note:
- If wheel zoom comes back unexpectedly, check global init default first before changing per-chart options.

## 2026-02-28 migrated understanding ledger (benchmark trend chart)

### 2026-02-28_12.11.07 dashboard benchmark trend chart structure

Source: `docs/understandings/2026-02-28_12.11.07-dashboard-benchmark-trend-chart-structure.md`

Problem captured:
- Operators needed a quick run-to-run benchmark trend view, but chart/offline failure behavior had to avoid blank-page confusion.

Durable decisions:
- Add `#benchmark-trend-chart` and fallback container in main dashboard page.
- Build time-series from benchmark rows for `precision`, `recall`, `f1`, `practical_f1`.
- Keep explicit mixed-format timestamp parsing support for historical data.
- Use fallback messaging for both no-data and Highcharts-load failure conditions.
- Keep chart scoring axis fixed at `0..1` for consistent interpretation.

Anti-loop note:
- If chart looks blank but table rows render, inspect fallback state and timestamp parsing first before changing collector behavior.



## 2026-03-03 migrated understandings ledger (docs/understandings consolidation)

This section preserves detailed analytics/dashboard discoveries in timestamp order after removing standalone files from `docs/understandings/`.

### 2026-03-02_22.26.36-dashboard-ai-runtime-and-source-fallback

Source file: docs/understandings/2026-03-02_22.26.36-dashboard-ai-runtime-and-source-fallback.md
Summary: Dashboard `Previous Runs` source labels should fall back to artifact-path slugs, and AI runtime should come from run-config metadata.


- Main dashboard `Previous Runs` previously used `basename(source_file)` only; rows missing `source_file` degraded to `-` or low-signal path tails.
- Better fallback comes from benchmark artifact path patterns already present in collected rows:
  - `all-method-benchmark/<source_slug>/config_*`
  - `single-profile-benchmark/<source_slug>/...`
  - `scenario_runs/<source_slug>/...`
  - `.../eval/<source_slug>/...`
- AI model/thinking context can stay CSV-first by resolving from benchmark `run_config` and `run_config_summary` (`codex_farm_model`, `codex_farm_reasoning_effort`, related aliases); no new collector-only JSON metric needed.


### 2026-03-02_22.29.43-dashboard-all-method-navigation-contract

Source file: docs/understandings/2026-03-02_22.29.43-dashboard-all-method-navigation-contract.md
Summary: All-method dashboard pages should be reached from main Previous Runs, not from a separate all-method index page.


## Discovery

- `dashboard_render.py` generated three all-method surfaces: a root run-index page plus run-summary and per-book detail pages.
- Main dashboard also rendered an `All-Method Benchmark Runs` section linking to that root index page.
- `Previous Runs` already computes run-summary links (`all-method-benchmark-run__<ts>.html`) for grouped all-method rows, so the root run-index page is redundant.

## Applied Contract

- Keep generating run-summary + per-book detail pages under `all-method-benchmark/`.
- Remove generation of `all-method-benchmark/index.html`.
- Route navigation through main `index.html#previous-runs-section`.


### 2026-03-02_22.30.04-dashboard-previous-runs-rules-filter-flow

Source file: docs/understandings/2026-03-02_22.30.04-dashboard-previous-runs-rules-filter-flow.md
Summary: Previous Runs rules filtering should be applied before all-method run bundling so filtered comparisons stay meaningful.


- `Previous Runs` all-method rows are derived by bundling raw benchmark records by run path; filtering must happen before that bundling step.
- Applying rules first preserves comparisons like "single book + all model/effort combos" while still letting all-method summaries render from the matching subset.
- The trend chart should consume the exact same filtered record set as the table to avoid visual/table mismatch.


### 2026-03-02_22.35.41-dashboard-all-method-timestamp-from-path

Source file: docs/understandings/2026-03-02_22.35.41-dashboard-all-method-timestamp-from-path.md
Summary: All-method Previous Runs timestamps must be extracted from timestamp-like path tokens, not the segment immediately before all-method-benchmark.


- Some all-method artifact paths contain `.../repeat_01/eval_output/all-method-benchmark/...`; using `idx - 1` for the timestamp picks `eval_output`.
- The fix is to scan backward from `all-method-benchmark` and take the nearest token that matches dashboard timestamp formats (`YYYY-MM-DD_HH.MM.SS` or `YYYY-MM-DDTHH:MM:SS`).
- This keeps grouped all-method timestamp links readable and chronologically sortable.


### 2026-03-02_22.37.34-dashboard-boundary-fallback-to-last-non-null

Source file: docs/understandings/2026-03-02_22.37.34-dashboard-boundary-fallback-to-last-non-null.md
Summary: Boundary Classification card can show an older timestamp when newer benchmark rows have null boundary metrics.


# Discovery

The dashboard files were freshly regenerated (`data/.history/dashboard/index.html` at `2026-03-02 22:31:44 -0500`), but the Boundary card still showed `2026-02-23T15:59:03`.

Root cause: frontend boundary rendering intentionally chooses the first benchmark record with any non-null boundary values:

- `const latest = preferredRecords.find(r => r.boundary_correct != null || ...)`
- source: `cookimport/analytics/dashboard_render.py` (`renderBoundary`)

In current data, recent benchmark rows (including `2026-03-02_21.25.24`) have `boundary_* = null`, so UI falls back to the last record that still has boundary values (currently `2026-02-23T15:59:03`).

Why recent rows are null: their eval reports (e.g. `data/golden/benchmark-vs-golden/2026-03-02_21.25.24/single-offline-benchmark/{vanilla,codexfarm}/eval_report.json`) no longer contain a `boundary` object.


### 2026-03-02_22.40.42-dashboard-codex-runtime-llm-codex-farm-fallback

Source file: docs/understandings/2026-03-02_22.40.42-dashboard-codex-runtime-llm-codex-farm-fallback.md
Summary: Dashboard benchmark runtime model/effort may need fallback from prediction-run `llm_codex_farm` telemetry when run-config leaves defaults unset.


- Some codex-farm benchmark rows persist `llm_recipe_pipeline=codex-farm-3pass-v1` but keep `run_config.codex_farm_model` and `run_config.codex_farm_reasoning_effort` as `null`.
- The needed runtime values still exist in `prediction-run/manifest.json -> llm_codex_farm`:
  - `process_runs.*.process_payload.codex_model`
  - `process_runs.*.process_payload.codex_reasoning_effort` (or telemetry `model_reasoning_breakdown[].reasoning_effort`, often `<default>`).
- Collector should backfill these into benchmark `run_config` only when missing, so existing frontend/runtime-card extraction can display useful model/effort without changing table contracts.


### 2026-03-02_22.41.32-dashboard-ai-off-fallback-vs-codex-manifest-runtime

Source file: docs/understandings/2026-03-02_22.41.32-dashboard-ai-off-fallback-vs-codex-manifest-runtime.md
Summary: Dashboard AI column/runtime can incorrectly show `off` unless codex runtime is backfilled from benchmark manifest llm_codex_farm payloads.


- Benchmark rows may have `llm_recipe_pipeline=codex-farm-3pass-v1` but no model/effort in `run_config` or `run_config_summary`.
- The codex model is often present only in benchmark manifest `llm_codex_farm.process_runs.*.process_payload.codex_model` (with reasoning fallback in telemetry model breakdown).
- Collector should merge that runtime data into benchmark `run_config` (`codex_farm_model`, `codex_farm_reasoning_effort`) so dashboard UI can render real AI runtime labels.
- Diagnostics latest-row selection should tie-break identical timestamps by preferring richer AI metadata (model/effort/pipeline-on), not whichever row appears first.


### 2026-03-02_22.48.48-benchmark-importer-missing-csv-root-cause

Source file: docs/understandings/2026-03-02_22.48.48-benchmark-importer-missing-csv-root-cause.md
Summary: Benchmark importer '-' rows were caused by blank importer_name in CSV writes, not table rendering loss.


- Recent benchmark rows with `-` importer traced to `data/.history/performance_history.csv` rows where `importer_name` was blank at write time.
- `append_benchmark_csv(...)` previously did not set CSV `importer_name`, so dashboard collector had nothing to display unless JSON manifests happened to contain importer metadata.
- Practical fix is two-layered:
  - persist importer in benchmark CSV writes going forward,
  - dashboard fallback infers importer from `source_file` extension/run-config for historical blank rows.


### 2026-03-02_23.11.05-dashboard-trend-range-selector-default

Source file: docs/understandings/2026-03-02_23.11.05-dashboard-trend-range-selector-default.md
Summary: Benchmark Score Trend looked shorter than Previous Runs because Highcharts Stock defaulted to a recent range selection.


- The chart data already included older points, but `rangeSelector.selected = 1` opened on a recent time window by default.
- The `Previous Runs` table lists filtered rows directly and is not clipped by that chart viewport, so the two sections appeared inconsistent.
- Setting explicit range buttons with default `All` keeps initial chart history aligned with table context while preserving quick-range controls.


### 2026-03-02_23.50.00-dashboard-previous-runs-dynamic-column-contract

Source file: docs/understandings/2026-03-02_23.50.00-dashboard-previous-runs-dynamic-column-contract.md
Summary: Previous Runs now renders columns dynamically from JS state across single + all-method row shapes.


## Discovery

`Previous Runs` is not a single record type: it renders both raw benchmark rows and grouped all-method summary rows. Dynamic columns therefore must resolve values from two row shapes.

## Practical Contract

- Column list comes from runtime JS state (`previousRunsVisibleColumns`), seeded from defaults + discovered benchmark fields.
- Headers are rendered at runtime (`renderPreviousRunsTableColumns`) and use `<colgroup>` widths so drag-resize persists during rerenders.
- Header cells are mouse-draggable for reordering (`dragstart`/`drop`), with `Left`/`Right` editor buttons as fallback controls.
- Cell values route through `previousRunsRowFieldValue(...)`:
  - single rows pull from raw benchmark record fields (including nested paths)
  - all-method rows expose only summarized keys (`strict_accuracy`, `macro_f1_excluding_other`, `source`, etc.); missing fields render `-`.


### 2026-03-02_23.58.40-benchmark-metric-fallback-explicit-vs-legacy

Source file: docs/understandings/2026-03-02_23.58.40-benchmark-metric-fallback-explicit-vs-legacy.md
Summary: Benchmark compatibility readers should only collapse aliases when explicit strict/macro metrics are present.


# Benchmark Metric Fallback: Explicit vs Legacy

- Problem: after alias removal in stage/canonical `eval_report.json`, compatibility readers started collapsing legacy reports too aggressively (`precision=recall=f1`, `practical_*` all equal), which broke dashboard CSV/collector expectations.
- Root cause: fallback helpers treated any available alias metric as equivalent to explicit benchmark metrics.
- Decision:
  - Collapse to strict/practical aliases only when explicit benchmark keys exist:
    - strict: `strict_accuracy` / `overall_line_accuracy` / `overall_block_accuracy` / `accuracy`
    - practical: `macro_f1_excluding_other`
  - When explicit keys are absent, preserve legacy split fields (`precision`, `recall`, `f1`, `practical_precision`, `practical_recall`, `practical_f1`).
  - For single-offline comparison display only, keep legacy strict fallback to strict precision so old comparison artifacts still populate `strict_accuracy`.
- Verification anchors:
  - `tests/analytics/test_stats_dashboard.py -k benchmark`
  - `tests/labelstudio/test_labelstudio_benchmark_helpers.py -k "single_offline_comparison or interactive_single_offline_codex_enabled_runs_vanilla_then_codex_and_writes_comparison"`


### 2026-03-02_23.59.30-dashboard-explicit-metric-rendering

Source file: docs/understandings/2026-03-02_23.59.30-dashboard-explicit-metric-rendering.md
Summary: Dashboard Previous Runs/trend should render explicit benchmark metric names while preserving legacy ingestion fallback.


# Dashboard Explicit Metric Rendering

- Problem: backend benchmark eval reports moved to explicit metrics (`strict_accuracy`, `macro_f1_excluding_other`) but dashboard UI still rendered legacy strict/practical aliases.
- Fix shape:
  - Add explicit metric fields to dashboard schema records.
  - Populate explicit fields in collectors from explicit eval keys first, with legacy alias fallback for historical rows/artifacts.
  - Render main `Previous Runs` and trend chart using explicit metric fields/names.
- Compatibility:
- Legacy fields are still ingested for old rows.
- CSV rows now persist explicit metric columns alongside legacy compatibility columns.

## 2026-03-03 docs/tasks consolidation batch (dashboard task-file merge)

### 2026-03-02_22.26.36 dashboard AI runtime/source fallback

Source task file:
- `docs/tasks/2026-03-02_22.26.36 - dashboard-ai-runtime-columns-and-source-fallback.md`

Durable decisions/outcomes:
- Added latest-benchmark runtime diagnostics card and `AI Model + Effort` column in `Previous Runs`.
- Source labels now use layered fallbacks when `source_file` is missing.
- Runtime enrichment remains CSV-first; manifest runtime backfill is fallback-only.

Evidence preserved:
- `tests/analytics/test_stats_dashboard.py` expanded from 48 to 51 passing tests after collector/runtime fallback updates.

### 2026-03-02_22.29.43 remove standalone all-method index page

Source task file:
- `docs/tasks/2026-03-02_22.29.43 - dashboard-remove-all-method-index-page.md`

Durable decisions/outcomes:
- Main index no longer renders `All-Method Benchmark Runs` section.
- Renderer no longer writes `all-method-benchmark/index.html`.
- Run-summary and per-book detail pages remain generated and linked from `Previous Runs`.

Failure history preserved:
- Full analytics module had an unrelated pre-existing collector expectation failure during this task (`TestCollectors::test_benchmark_collector` recall mismatch), so renderer-only verification was scoped to `TestRenderer`.

### 2026-03-02_22.30.04 rules filter builder and boolean-expression support

Source task files:
- `docs/tasks/2026-03-02_22.30.04 - previous-runs-rules-filter-builder.md`
- `docs/tasks/2026-03-02_22.30.04-dashboard-previous-runs-rules-filters.md`

Durable decisions/outcomes:
- `Previous Runs` now supports rule rows (`field/operator/value`) and expression parsing (`R1`, `R2`, `AND/OR/NOT`, parentheses).
- Filtering is applied before all-method row bundling.
- Trend chart consumes the same filtered record set as the table.
- Invalid expression handling is non-destructive: status error + unfiltered fallback.

ExecPlan evidence preserved:
- Targeted analytics tests passed (`6 passed` subset), full file passed (`50 passed`), and static dashboard regeneration confirmed UI wiring.

### 2026-03-02_22.35.08 Previous Runs horizontal scroll contract

Source task file:
- `docs/tasks/2026-03-02_22.35.08 - previous-runs-horizontal-scroll.md`

Durable decisions/outcomes:
- CSS-only contract: table-level minimum width with no-wrap cells and overflow scrolling so dense columns remain readable.
- No collector/data-shape changes were required.

### 2026-03-02_22.41.32 codex manifest runtime fallback (`off`-label fix)

Source task file:
- `docs/tasks/2026-03-02_22.41.32 - fix-dashboard-ai-off-fallback-from-codex-manifest-runtime.md`

Durable decisions/outcomes:
- Collector backfills `codex_farm_model` and `codex_farm_reasoning_effort` from `llm_codex_farm` manifest payload when run-config is blank.
- Diagnostics latest-row tie-break prefers richer AI metadata at same timestamp.
- Maintains CSV-first behavior; manifest usage stays fallback-only.

Evidence preserved:
- `tests/analytics/test_stats_dashboard.py` passed (`51 passed`), and regenerated `dashboard_data.json` showed codex row model values instead of false `off`.

### 2026-03-02_22.48.48 benchmark importer CSV persistence + fallback

Source task file:
- `docs/tasks/2026-03-02_22.48.48 - benchmark-importer-csv-and-dashboard-fallback.md`

Durable decisions/outcomes:
- `append_benchmark_csv` now persists `importer_name` on benchmark rows.
- Dashboard keeps importer inference fallback for historical blank rows (source extension/run-config derived).

### 2026-03-02_23.11.05 trend selector defaults to full-history `All`

Source task file:
- `docs/tasks/2026-03-02_23.11.05 - benchmark-score-trend-default-all-range.md`

Durable decisions/outcomes:
- Highcharts range selector now has explicit buttons and defaults to `All` so first render matches long table history.
- Filtering/table wiring remains unchanged.

### 2026-03-02_23.17.11 trend timeline bounds aligned with table timestamps

Source task file:
- `docs/tasks/2026-03-02_23.17.11 - benchmark-trend-timeline-align-with-table.md`

Problem captured:
- Older rows without explicit score points caused trend chart to appear newer than `Previous Runs`.

Durable decisions/outcomes:
- Chart x-axis min/max now initializes from full filtered benchmark timestamp span.
- Plot series still uses explicit score metrics only; no synthetic legacy points added.

### 2026-03-02_23.50.00 configurable Previous Runs columns

Source task files:
- `docs/tasks/2026-03-02_23.50.00 - previous-runs-column-controls.md`
- `docs/tasks/2026-03-02_23.50.00-dashboard-previous-runs-column-controls.md`

Durable decisions/outcomes:
- Added in-browser column editor with add/remove fields, header drag reorder, and resize handles.
- Column model is session-local JS state (no persistence).
- Field discovery reuses existing benchmark field-path collection so options track schema changes.
- Rendering must support mixed `single` rows and grouped `all_method` rows.

ExecPlan evidence preserved:
- Targeted contract tests passed (`7 passed`) and full analytics dashboard test file passed (`51 passed`).

## 2026-03-03 migrated understanding ledger (explicit-metric timeline + legacy-row cull)

### 2026-03-02_23.17.11 trend null explicit metrics gap

Source:
- `docs/understandings/2026-03-02_23.17.11-benchmark-trend-null-explicit-metrics-gap.md`

Problem captured:
- Some historical benchmark rows carry legacy metrics but null explicit strict/macro values, so plotted trend looked newer than table history.

Durable decision:
- Keep explicit-metric plotting only.
- Initialize chart timeline bounds from full filtered benchmark timestamp span so chart/date context matches table history.

### 2026-03-02_23.22.43 dashboard history cull of legacy benchmark rows

Source:
- `docs/understandings/2026-03-02_23.22.43-dashboard-history-cull-legacy-benchmark-rows.md`

Problem captured:
- Old `performance_history.csv` benchmark rows from pytest tmp paths and legacy eval-vs-pipeline runs kept stale dates visible even after workflow changes.

Durable decision:
- Prune benchmark CSV rows to on-disk `data/golden` artifact paths when cleaning history.
- Preserve stage/import history rows.

Anti-loop note:
- If stale dates remain, check both CSV rows and retained artifact folders; either side can keep old timeline entries alive.

### 2026-03-03_09.53.52 benchmark trend chart fixed-height increase

Problem captured:
- The benchmark trend chart viewport was too short for dashboard review workflows.

Durable decisions/outcomes:
- Doubled fixed trend chart height from `400` to `800` in both CSS host sizing and Highcharts config.
- Kept fixed-height contract (instead of auto-height) to preserve prior reflow-loop protection.

### 2026-03-03_10.21.04 Codex token usage persisted in benchmark history

Problem captured:
- Benchmark dashboard rows needed CodexFarm token usage per run, but token fields were not part of the benchmark CSV/dashboard contract.

Durable decisions/outcomes:
- Added benchmark CSV columns: `tokens_input`, `tokens_cached_input`, `tokens_output`, `tokens_reasoning`, `tokens_total`.
- `labelstudio-eval` and `labelstudio-benchmark` now append token usage from prediction-run manifest `llm_codex_farm.process_runs.*.process_payload.telemetry`.
- `benchmark-csv-backfill` now fills missing `tokens_*` from nearby manifests and reports `Token rows filled`/`Token fields filled`.
- Dashboard schema bumped to `SCHEMA_VERSION = "12"` and `Previous Runs` can display token columns via column picker.


## 2026-03-03 migrated understanding ledger (dashboard/table/filter/runtime contracts)


### 2026-03-03_01.33.31 dashboard-previous-runs-css-height-cap

Source:
- `docs/understandings/2026-03-03_01.33.31-dashboard-previous-runs-css-height-cap.md`

Summary:
- Previous Runs gaps came from nested benchmark CSV history plus a capped table viewport.

Preserved notes:

```md
summary: "Previous Runs gaps came from nested benchmark CSV history plus a capped table viewport."
read_when:
  - "When dashboard Previous Runs appears to be missing older benchmark rows"
  - "When benchmark runs are written under nested processed-output directories"
  - "When adjusting dashboard table scrolling or row visibility"
---

# dashboard Previous Runs nested CSV + viewport cap

Discovery:
- Canonical dashboard history (`data/.history/performance_history.csv`) can miss benchmark rows from nested benchmark workflows (for example single-offline variants), because those rows are appended to nested CSVs like `data/output/<run>/.../.history/performance_history.csv`.
- Example: `2026-03-03_01.24.28` rows existed in nested benchmark history CSVs but not in the canonical CSV.
- The main dashboard table container (`.table-scroll`) enforced `max-height: 12.5rem` with vertical overflow, so only about five rows were visible without scrolling.
- Grouped all-method rows showed `-` for timestamp when artifact path tokens included timestamp suffixes (for example `..._manual-all-matched-...`), because frontend token matching required exact timestamp-only segments.
- Once suffix tokens were shown directly, table ordering looked incorrect because frontend date parsing still rejected suffixed timestamps and treated them as non-date strings.

Resolution:
- Collector now supplements benchmark rows from nested `<output_root>/**/.history/performance_history.csv` files while keeping CSV-first behavior.
- Remove the vertical height cap for `Previous Runs` so full filtered history is rendered in-view by default.
- Keep horizontal scrolling for wide column sets.
- Frontend all-method timestamp extraction now accepts suffixed timestamp tokens and falls back to `record.run_timestamp` when path token extraction fails.
- Frontend timestamp parsing now accepts suffixed tokens for sorting, and `Previous Runs` headers toggle sort order (`A→Z` / `Z→A`) on click.

```

### 2026-03-03_09.11.03 benchmark-trend-variant-series-split

Source:
- `docs/understandings/2026-03-03_09.11.03-benchmark-trend-variant-series-split.md`

Summary:
- Benchmark Score Trend now separates paired codexfarm/vanilla runs into distinct series.

Preserved notes:

```md
summary: "Benchmark Score Trend now separates paired codexfarm/vanilla runs into distinct series."
read_when:
  - "When Benchmark Score Trend appears to mix codexfarm and vanilla paired runs"
  - "When adjusting benchmark trend chart series grouping"
---

# Benchmark trend variant split

Discovery:
- The trend chart originally grouped all benchmark rows into only two series (`strict_accuracy`, `macro_f1_excluding_other`), so paired `codexfarm`/`vanilla` points were visually mixed.

Resolution:
- Add frontend variant classification for benchmark rows using artifact path and run-config fallbacks.
- Keep default two-series behavior when no paired variants are present.
- When paired variants exist, split into per-metric variant series (for example `strict_accuracy (vanilla)` and `strict_accuracy (codexfarm)`), with separate colors.
- Tooltip grouping now keys points by run-group token so hovering any one of the paired dots opens a single card listing all visible metric+variant values for that run.

```

### 2026-03-03_09.39.48 csv-benchmark-runtime-manifest-backfill-gap

Source:
- `docs/understandings/2026-03-03_09.39.48-csv-benchmark-runtime-manifest-backfill-gap.md`

Summary:
- CSV-first benchmark rows could miss codex model metadata until collector backfilled from nearby manifests.

Preserved notes:

```md
summary: "CSV-first benchmark rows could miss codex model metadata until collector backfilled from nearby manifests."
read_when:
  - "When `AI Model + Effort` shows `-` for codex benchmark rows that are known to use codex models"
  - "When debugging CSV-first benchmark metadata backfill behavior"
---

# CSV benchmark runtime backfill gap

Discovery:
- Benchmark row `2026-03-03T01:28:32` (`.../single-offline-benchmark/.../codexfarm`) had `llm_recipe_pipeline=codex-farm-3pass-v1` but no `codex_farm_model` in CSV `run_config_json`.
- `prediction-run/manifest.json` for the same benchmark run contained codex runtime details (`gpt-5.3-codex-spark`) inside `llm_codex_farm.process_runs.*.process_payload`.
- Collector only extracted that runtime during eval-report scan mode, not CSV-first mode.

Resolution:
- Add CSV benchmark post-collection manifest enrichment using nearby `manifest.json` / `run_manifest.json` and `prediction-run/*` counterparts.
- Merge missing codex runtime keys into `record.run_config` and recompute `run_config_hash`/`run_config_summary` after merge.

```

### 2026-03-03_10.02.32 previous-runs-header-filter-row-contract

Source:
- `docs/understandings/2026-03-03_10.02.32-previous-runs-header-filter-row-contract.md`

Summary:
- Previous Runs filters are column-scoped with +/- popup editors; active summaries stay visible in the first row under headers.

Preserved notes:

```md
summary: "Previous Runs filters are column-scoped with +/- popup editors; active summaries stay visible in the first row under headers."
read_when:
  - "When changing Previous Runs filter UX or filter state wiring in dashboard JS"
  - "When debugging why Benchmark Score Trend and Previous Runs row counts diverge under filters"
---

# Previous Runs header filter row contract

- Previous Runs filtering is driven by visible-table columns, not a separate rules-expression builder.
- Each visible column in the first row beneath headers has a small `+/-` toggle that opens/closes a popup filter editor.
- Popup editors stage operator/value changes and apply on `Save`; each save appends a clause for that column, with per-column `AND/OR` stack mode and per-clause `×` removal. Closing without save leaves current filter state untouched.
- The filter summary row includes a quick per-column `×` button that clears that column’s full filter stack without opening the popup.
- Non-numeric popup value inputs are typeahead-enabled: ranked candidate chips are derived from viable column values, top match is first, and `Tab` completes to that top suggestion.
- The first row beneath headers always shows compact active-filter summaries after save/close.
- Filtered benchmark rows feed both Previous Runs and Benchmark Score Trend from the same predicate path (`currentPreviousRunsFilterResult`).
- Filters must be applied before all-method run bundling so grouped rows still reflect filtered underlying benchmark records.

```

### 2026-03-03_10.04.28 benchmark-history-backfill-nested-csv-runtime-columns

Source:
- `docs/understandings/2026-03-03_10.04.28-benchmark-history-backfill-nested-csv-runtime-columns.md`

Summary:
- Some benchmark rows come from nested history CSVs; runtime backfill must update those files to affect Previous Runs model/effort columns.

Preserved notes:

```md
summary: "Some benchmark rows come from nested history CSVs; runtime backfill must update those files to affect Previous Runs model/effort columns."
read_when:
  - "When a benchmark row appears in dashboard data but is missing from data/.history/performance_history.csv"
  - "When backfilling AI model/effort metadata for historical benchmark rows"
---

# Nested benchmark CSV backfill and AI runtime columns

Discovery:
- `stats-dashboard` merges benchmark rows from `data/.history/performance_history.csv` and nested `data/output/**/.history/performance_history.csv` files.
- Some `single-offline-benchmark` rows (including codex/vanilla paired runs) exist only in nested CSVs, so backfilling only the top-level CSV leaves those rows unchanged in `Previous Runs`.

Resolution:
- `benchmark-csv-backfill` now also repairs benchmark runtime metadata (`run_config_json`, `run_config_hash`, `run_config_summary`) from manifest context, including codex model/effort when resolvable.
- Effort placeholders like `<default>` are treated as missing and replaced with model-default effort from local Codex `models_cache.json` when available.
- Dashboard `Previous Runs` now uses separate `AI Model` and `AI Effort` columns; historical correctness depends on backfilling whichever history CSV actually supplies each row.

```

### 2026-03-03_10.09.14 dashboard-isolate-slice-filter-flow

Source:
- `docs/understandings/2026-03-03_10.09.14-dashboard-isolate-slice-filter-flow.md`

Summary:
- Dashboard isolate mode should run after existing column filters so Previous Runs and Benchmark Score Trend stay aligned.

Preserved notes:

```md
summary: "Dashboard isolate mode should run after existing column filters so Previous Runs and Benchmark Score Trend stay aligned."
read_when:
  - "When adding a new dashboard filter mode on top of Previous Runs"
  - "When chart/table slices appear to disagree in the stats dashboard"
---

# Dashboard isolate slice filter flow

Discovery:
- The active `dashboard.js` in `data/.history/dashboard/assets` currently uses per-column filters (`previousRunsColumnFilters`), not the older rules-expression flow.
- `Benchmark Score Trend` and `Previous Runs` both consume `currentPreviousRunsFilterResult()`, so new filtering must be integrated there to keep both views consistent.

Applied approach:
- Isolate controls (`field`, `value`) are synced from filtered benchmark rows, then isolate filtering runs after existing column filters.
- Isolate insights compare isolated rows to the pre-isolate baseline row set from the same current view.
- Status text now reports both active column filters and active isolate slice.

```

### 2026-03-03_10.21.04 benchmark-codexfarm-token-usage-history-backfill

Source:
- `docs/understandings/2026-03-03_10.21.04-benchmark-codexfarm-token-usage-history-backfill.md`

Summary:
- Benchmark CSV/dashboard now persist CodexFarm token usage fields and backfill them from manifests when available.

Preserved notes:

```md
summary: "Benchmark CSV/dashboard now persist CodexFarm token usage fields and backfill them from manifests when available."
read_when:
  - "When adding benchmark runtime fields that must be CSV-first in Previous Runs"
  - "When CodexFarm token columns are blank for historical benchmark rows"
---

# CodexFarm benchmark token usage persistence + backfill

Discovery:
- CodexFarm token usage already exists in prediction telemetry (`llm_codex_farm.process_runs.*.process_payload.telemetry`) but benchmark CSV rows did not persist those values.
- Dashboard `Previous Runs` relies on CSV-first benchmark rows, so missing CSV token fields made per-run token visibility inconsistent.

Resolution:
- Extended benchmark CSV contract with `tokens_input`, `tokens_cached_input`, `tokens_output`, `tokens_reasoning`, `tokens_total`.
- Wired token extraction into benchmark append paths (`labelstudio-eval`, `labelstudio-benchmark`) and collector manifest enrichment fallback.
- Extended `benchmark-csv-backfill` to fill missing `tokens_*` fields and report token-specific counters.

Operational outcome from this run:
- Backfill was executed across all discovered `data/**/.history/performance_history.csv` files.
- Token fields were filled in three nested single-offline CSVs:
  - `data/output/2026-03-02_23.15.01/single-offline-benchmark/seaandsmokecutdown/.history/performance_history.csv`
  - `data/output/2026-03-02_23.33.49/single-offline-benchmark/seaandsmokecutdown/.history/performance_history.csv`
  - `data/output/2026-03-03_01.24.28/single-offline-benchmark/seaandsmokecutdown/.history/performance_history.csv`
- Most older rows remained unchanged because their manifests do not contain Codex token telemetry.

```

### 2026-03-03_10.25.59 previous-runs-filter-row-spacer-order

Source:
- `docs/understandings/2026-03-03_10.25.59-previous-runs-filter-row-spacer-order.md`

Summary:
- Previous Runs now renders filter controls immediately under headers, with a dedicated blank spacer row after filters.

Preserved notes:

```md
summary: "Previous Runs now renders filter controls immediately under headers, with a dedicated blank spacer row after filters."
read_when:
  - "When changing Previous Runs sticky header/filter row layout or row-order behavior"
  - "When debugging a blank row appearing above the filter +/- row in the dashboard"
---

# Previous Runs filter-row spacer order

- The table header now renders three rows in order: `previous-runs-header-row`, `previous-runs-active-filters-row`, then `previous-runs-filter-spacer-row`.
- Sticky offsets are set from measured row heights in `renderPreviousRunsTableColumns(...)`, not just static rem constants.
- This keeps the filter `+/-` row directly under column headers and leaves the blank separator row after filters.

```

### 2026-03-03_10.29.22 dashboard-all-token-use-computed-column

Source:
- `docs/understandings/2026-03-03_10.29.22-dashboard-all-token-use-computed-column.md`

Summary:
- Previous Runs now has an `All token use` computed column that renders total/input/output while sorting/filtering on tokens_total.

Preserved notes:

```md
summary: "Previous Runs now has an `All token use` computed column that renders total/input/output while sorting/filtering on tokens_total."
read_when:
  - "When changing benchmark token columns in Previous Runs"
  - "When users expect one token cell but numeric sort/filter behavior"
---

# Dashboard `All token use` computed column contract

Discovery:
- Users wanted one token cell per run (`total/input/output`) instead of switching between separate token columns.
- Sort/filter behavior still needs to be numeric and stable, so it must key off `tokens_total` rather than the combined display string.

Resolution:
- Added virtual field `all_token_use` in dashboard JS table logic.
- Cell text renders combined token stats as `total | input | output`.
- Sort/filter/suggestion value for that field is `tokens_total` numeric.
- Kept detailed token columns available via the existing `+/-` column picker.

```

### 2026-03-03_10.39.32 dashboard-per-label-variant-rolling-aggregation

Source:
- `docs/understandings/2026-03-03_10.39.32-dashboard-per-label-variant-rolling-aggregation.md`

Summary:
- Per-label diagnostics should aggregate latest run at timestamp, then split run + rolling metrics by codexfarm/vanilla variant without cross-mixing.

Preserved notes:

```md
summary: "Per-label diagnostics should aggregate latest run at timestamp, then split run + rolling metrics by codexfarm/vanilla variant without cross-mixing."
read_when:
  - "When changing Per-Label Breakdown columns/aggregation in dashboard_render.py"
  - "When users ask for codexfarm-vs-vanilla precision/recall comparisons in diagnostics"
---

# Dashboard per-label variant split + rolling average

Discovery:
- `Per-Label Breakdown` scope is timestamp-group based: use latest all-method timestamp when present, else latest benchmark timestamp with per-label rows.
- Variant detection should reuse `benchmarkVariantForRecord` (artifact-path + run-config/model fallbacks), not ad-hoc checks.
- Rolling averages must be computed per variant and per run timestamp (aggregate each run first, then average across latest `n` runs).

Implementation note:
- Keep `Gold`/`Pred` from the latest run aggregate (all latest rows).
- Render separate latest-run precision/recall columns for `codexfarm` and `vanilla`.
- Render separate rolling `n=10` precision/recall columns for `codexfarm` and `vanilla`.

```

### 2026-03-03_10.39.46 boundary-card-matched-only-context

Source:
- `docs/understandings/2026-03-03_10.39.46-boundary-card-matched-only-context.md`

Summary:
- Discovery: Boundary Card Can Look Artificially Perfect

Preserved notes:

```md
# Discovery: Boundary Card Can Look Artificially Perfect

- The dashboard boundary card previously picked one latest boundary-bearing record and showed percentages over only `boundary_{correct,over,under,partial}`.
- Latest single-offline canonical rows can have `boundary_correct > 0` and `boundary_over/under/partial = 0` while strict metrics are still low, because boundary percentages describe matched boundary pairs only.
- Renderer fix: aggregate boundary counts across all latest timestamp records (all-method preferred, non-speed preferred) and show matched-coverage context (`gold_matched/gold_total`, `gold_matched/pred_total`) next to the boundary table.

```

### 2026-03-03_10.39.48 dashboard-ui-state-persistence-localstorage

Source:
- `docs/understandings/2026-03-03_10.39.48-dashboard-ui-state-persistence-localstorage.md`

Summary:
- Dashboard Previous Runs customization state was in-memory only; persistence now uses browser localStorage.

Preserved notes:

```md
summary: "Dashboard Previous Runs customization state was in-memory only; persistence now uses browser localStorage."
read_when:
  - "When users report Previous Runs column/filter customizations resetting after dashboard rebuilds or page refreshes"
  - "When changing dashboard JS state wiring for Previous Runs filters/columns/sort/isolate controls"
---

# Dashboard UI state persistence

- `dashboard_render.py` previously kept Previous Runs controls entirely in runtime JS variables (`previousRunsVisibleColumns`, `previousRunsColumnFilters`, `previousRunsQuickFilters`, widths, sort, isolate), so settings were lost on reload/regenerated `index.html`.
- Persistence now saves/restores those controls via `localStorage` key `cookimport.stats_dashboard.ui_state.v1` with storage-availability guards.
- Restored values are still normalized through existing runtime guards (`ensurePreviousRunsColumns`, filter/operator validation), so stale fields/operators from older dashboards are safely pruned instead of breaking render.

```

### 2026-03-03_10.40.00 dashboard-quick-filters-official-benchmark-scope

Source:
- `docs/understandings/2026-03-03_10.40.00-dashboard-quick-filters-official-benchmark-scope.md`

Summary:
- Dashboard quick checkboxes should filter benchmark rows through currentPreviousRunsFilterResult so chart, table, and isolate stay aligned.

Preserved notes:

```md
summary: "Dashboard quick checkboxes should filter benchmark rows through currentPreviousRunsFilterResult so chart, table, and isolate stay aligned."
read_when:
  - "When adding or changing dashboard quick filters between Benchmark Score Trend and Previous Runs"
  - "When benchmark chart/table counts disagree after adding new filter controls"
---

# Dashboard quick filters: official benchmark scope

- Wire quick checkbox filters into `currentPreviousRunsFilterResult()` (not just one renderer) so `Benchmark Score Trend`, `Previous Runs`, and isolate panel all use the same filtered row set.
- Keep quick-filtered rows in `previousRunsRecordsMatchingOtherFilters(...)` too, otherwise column filter suggestions show values from rows users can no longer see.
- Useful default split:
  - AI test/smoke rows: benchmark artifact paths under `/bench/`, pytest-style temp segments, and timestamp-suffixed run folders like `<timestamp>_manual-...-smoke`.
  - Official benchmark rows: only `benchmark-vs-golden` rows under `single-offline-benchmark` with `vanilla`/`codexfarm` variants.
- Keep the two quick checkboxes independent: official-single-offline filtering should not implicitly apply AI-test filtering; users can combine both explicitly.
- Path-keyword caution: naive `smoke` substring matching can false-positive real source slugs like `seaandsmokecutdown`; prefer timestamp-suffix token checks for smoke/manual markers.

```

### 2026-03-03_10.41.56 dashboard-previous-runs-sticky-header-overlap

Source:
- `docs/understandings/2026-03-03_10.41.56-dashboard-previous-runs-sticky-header-overlap.md`

Summary:
- Previous Runs sticky header/filter rows can visually overlap body rows when table border-collapse stays collapsed.

Preserved notes:

```md
summary: "Previous Runs sticky header/filter rows can visually overlap body rows when table border-collapse stays collapsed."
read_when:
  - "When Previous Runs header/filter rows look duplicated or body text bleeds into sticky header rows"
  - "When changing sticky table CSS in cookimport/analytics/dashboard_render.py"
---

# Dashboard Previous Runs sticky-row overlap

- `Previous Runs` uses three sticky header rows (column header, filter summary row, spacer row).
- With `border-collapse: collapse`, Chromium can paint multi-row sticky table headers with row-boundary bleed/overlap artifacts.
- Setting `#previous-runs-table` to `border-collapse: separate; border-spacing: 0;` stabilizes sticky row painting while preserving layout.
- Keep this CSS pair in place when touching sticky offsets/row ordering.

```

### 2026-03-03_10.44.19 boundary-table-unmatched-gold-row

Source:
- `docs/understandings/2026-03-03_10.44.19-boundary-table-unmatched-gold-row.md`

Summary:
- Discovery: Boundary Table Needed Gold-Denominator Context In-Table

Preserved notes:

```md
# Discovery: Boundary Table Needed Gold-Denominator Context In-Table

- Even with latest-run aggregation, boundary buckets can remain `correct=100%` because those percentages are over matched boundary pairs, not all gold spans.
- To make this explicit in the table (not just helper text), boundary rendering now includes `% of matched`, `% of gold`, and an `Unmatched gold spans` row.
- This keeps boundary localization signal while preventing the card from reading as end-to-end perfection when strict accuracy/recall are lower.

```

### 2026-03-03_10.47.01 dashboard-sticky-header-relative-override

Source:
- `docs/understandings/2026-03-03_10.47.01-dashboard-sticky-header-relative-override.md`

Summary:
- Previous Runs sticky rows break when '#previous-runs-table th' sets position: relative, because row top offsets then shift relative instead of sticky.

Preserved notes:

```md
summary: "Previous Runs sticky rows break when '#previous-runs-table th' sets position: relative, because row top offsets then shift relative instead of sticky."
read_when:
  - "When Previous Runs header/filter rows appear duplicated, offset, or over body rows"
  - "When editing table header CSS for column resize handles in dashboard_render.py"
---

# Dashboard sticky header override pitfall

- Sticky behavior is declared on `.table-scroll thead th { position: sticky; }`.
- If a later, more specific selector sets `#previous-runs-table th { position: relative; }`, sticky is overridden.
- With sticky overridden, `top` offsets on header/filter/spacer rows become relative shifts and visually stack rows over body content.
- Keep `#previous-runs-table th` free of explicit `position` overrides; sticky cells still work as positioning context for resize handles.

```

### 2026-03-03_10.48.38 dashboard-table-column-resize-state-plumbing

Source:
- `docs/understandings/2026-03-03_10.48.38-dashboard-table-column-resize-state-plumbing.md`

Summary:
- Dashboard column width persistence flows through localStorage UI state; Previous Runs had width plumbing while diagnostics tables needed shared resize wiring.

Preserved notes:

```md
summary: "Dashboard column width persistence flows through localStorage UI state; Previous Runs had width plumbing while diagnostics tables needed shared resize wiring."
read_when:
  - "When changing dashboard table column resizing in cookimport/analytics/dashboard_render.py"
  - "When debugging why column widths do or do not survive stats-dashboard regeneration"
---

# Dashboard table column resize state plumbing

- Existing UI-state persistence already stored Previous Runs width state at `previous_runs.column_widths` under `cookimport.stats_dashboard.ui_state.v1` in browser `localStorage`.
- Previous Runs width updates happen during drag (`mousedown` + `mousemove`) and are flushed on mouseup via `persistDashboardUiState()`.
- Other dashboard tables (Per-Label, Boundary, Runtime) had no shared resize wiring, so they did not participate in persistent width state.
- Added a shared table-width map (`table_column_widths`) in the same UI-state payload and connected shared drag handles for diagnostics tables.
- Previous Runs width state now syncs to both legacy `previous_runs.column_widths` and shared `table_column_widths["previous-runs-table"]` for backward compatibility.

```

### 2026-03-03_10.52.42 boundary-card-denominator-cleanup

Source:
- `docs/understandings/2026-03-03_10.52.42-boundary-card-denominator-cleanup.md`

Summary:
- Discovery: Boundary Table Needed One Denominator

Preserved notes:

```md
# Discovery: Boundary Table Needed One Denominator

- Showing `% of matched` and `% of gold` together made the boundary card harder to scan and amplified confusion when `Correct=100% of matched` but overall coverage was low.
- Cleaner contract: keep one percentage denominator (`% of gold`) and make the remainder explicit with two rows:
  - `Matched (boundary unclassified)`
  - `Unmatched gold spans`
- This keeps the boundary breakdown mathematically complete against gold totals without duplicate explanatory text.

```

### 2026-03-03_11.00.46 dashboard-highcharts-secondary-cdn-fallback

Source:
- `docs/understandings/2026-03-03_11.00.46-dashboard-highcharts-secondary-cdn-fallback.md`

Summary:
- Benchmark trend chart fallback text can appear from transient single-CDN Highcharts load failures; add a second CDN fallback in dashboard HTML.

Preserved notes:

```md
summary: "Benchmark trend chart fallback text can appear from transient single-CDN Highcharts load failures; add a second CDN fallback in dashboard HTML."
read_when:
  - "When Benchmark Score Trend intermittently says Highcharts did not load"
  - "When changing dashboard script loading order in dashboard_render.py"
---

- `index.html` previously depended on one Highcharts Stock CDN script (`code.highcharts.com`) before loading `assets/dashboard.js`.
- When that request failed (network/CDN hiccup), dashboard JS initialized without `window.Highcharts` and rendered the fallback message permanently for that page load.
- A parser-time fallback script now injects `https://cdn.jsdelivr.net/npm/highcharts/highstock.js` when `window.Highcharts.stockChart` is missing, reducing random chart-unavailable sessions without changing dashboard JS rendering logic.

```

### 2026-03-03_11.16.23 dashboard-all-token-use-cached-discount

Source:
- `docs/understandings/2026-03-03_11.16.23-dashboard-all-token-use-cached-discount.md`

Summary:
- `All token use` now discounts cached input tokens to 10% weight and sorts/filters on that discounted total.

Preserved notes:

```md
summary: "`All token use` now discounts cached input tokens to 10% weight and sorts/filters on that discounted total."
read_when:
  - "When adjusting benchmark token cost approximation in Previous Runs"
  - "When `All token use` sort/filter behavior appears inconsistent with displayed token parts"
---

# Cached-input discount for `All token use`

Discovery:
- Raw token totals overstate cost-like usage when cached input is present.
- Operators need `All token use` to approximate Codex window/cost usage better while keeping one-cell readability.

Resolution:
- `All token use` now computes discounted total as:
  - `(input - cached_input) + 0.1 * cached_input + output`
- If input/output/cached fields are absent, fallback remains raw `tokens_total`.
- Table sort/filter value for `All token use` uses this discounted numeric total.
- Cell display remains compact (`discounted_total | input | output`) and tooltip includes raw total plus cached component.

```

### 2026-03-03_11.25.12 top-diagnostics-fit-and-runtime-dedupe

Source:
- `docs/understandings/2026-03-03_11.25.12-top-diagnostics-fit-and-runtime-dedupe.md`

Summary:
- Discovery: Top Diagnostics Needed Fixed-Fit Tables

Preserved notes:

```md
# Discovery: Top Diagnostics Needed Fixed-Fit Tables

- Runtime/boundary cards were inheriting the same resizable-table contract as wide tables, which can preserve oversized widths via UI state and force horizontal scrolling in top cards.
- Fix: keep resize/scroll behavior only for `Per-Label` (wide table), and force runtime/boundary tables to fixed-fit width inside 50/50 cards.
- Runtime card also dropped redundant `AI Runtime` row because it duplicated the `Model` value while `Thinking Effort` already carries the extra runtime context.

```

### 2026-03-03_11.26.00 runtime-token-card-discounted-vs-raw

Source:
- `docs/understandings/2026-03-03_11.26.00-runtime-token-card-discounted-vs-raw.md`

Summary:
- Benchmark Runtime token row now mirrors `All token use` discounted math and also shows raw total tokens.

Preserved notes:

```md
summary: "Benchmark Runtime token row now mirrors `All token use` discounted math and also shows raw total tokens."
read_when:
  - "When runtime card token values differ from Previous Runs `All token use`"
  - "When updating token cost approximation in dashboard runtime diagnostics"
---

# Runtime token card alignment

Discovery:
- Runtime diagnostics still displayed raw `tokens_total` while `Previous Runs` used discounted cached-token math.
- This made the latest runtime card look inconsistent with the table and overstate effective token usage.

Resolution:
- Runtime card now computes `Token use (cached 0.1x)` via the same helper as `All token use`.
- Card also keeps `Raw total tokens` as a separate line for traceability.

```

### 2026-03-03_11.29.35 runtime-token-use-label-and-raw-row-prune

Source:
- `docs/understandings/2026-03-03_11.29.35-runtime-token-use-label-and-raw-row-prune.md`

Summary:
- Discovery: Runtime Token Display Should Match One Metric

Preserved notes:

```md
# Discovery: Runtime Token Display Should Match One Metric

- Runtime card was showing both `Token use (cached 0.1x)` and `Raw total tokens`, which made the card noisier than requested.
- UI contract now shows a single runtime token row labeled `Token use`, backed by the same cached-adjusted discounted calculation already used in `All token use`.
- Raw token total remains in underlying benchmark fields for sorting/filtering elsewhere; it is just not shown in runtime diagnostics.

```

### 2026-03-03_11.30.19 dashboard-isolate-stacked-rules-flow

Source:
- `docs/understandings/2026-03-03_11.30.19-dashboard-isolate-stacked-rules-flow.md`

Summary:
- Dashboard isolate mode now supports stacked rules with AND/OR combine logic while staying aligned with existing quick/column filters.

Preserved notes:

```md
summary: "Dashboard isolate mode now supports stacked rules with AND/OR combine logic while staying aligned with existing quick/column filters."
read_when:
  - "When changing Isolate For X behavior in stats dashboard"
  - "When chart/table counts diverge after isolate rule changes"
---

# Dashboard isolate stacked-rules flow

Discovery:
- `Isolate For X` now persists and evaluates a list of isolate clauses (`field`, `operator`, `value`) plus a combine mode (`all` = AND, `any` = OR), replacing the prior single-clause isolate state.
- Backward compatibility is kept by migrating legacy saved isolate state (`field` + `value`) into a single clause on load.

Contract:
- Isolate evaluation still runs after quick filters + column filters inside `computePreviousRunsFilterResult()`, so Previous Runs and Benchmark Score Trend remain aligned.
- Isolate insights compare the isolated slice to the same pre-isolate baseline row set currently visible after non-isolate filters.

```

### 2026-03-03_11.33.58 dashboard-previous-runs-view-presets-state-shape

Source:
- `docs/understandings/2026-03-03_11.33.58-dashboard-previous-runs-view-presets-state-shape.md`

Summary:
- Previous Runs presets should reuse the same UI-state shape as live controls to keep save/load behavior stable.

Preserved notes:

```md
summary: "Previous Runs presets should reuse the same UI-state shape as live controls to keep save/load behavior stable."
read_when:
  - "When changing dashboard Previous Runs view presets or localStorage state wiring"
  - "When save/load preset behavior drifts from current table/filter UI state"
---

# Dashboard Previous Runs view preset state shape

- Presets are safest when they serialize the same normalized fields already used by live UI state (`visible_columns`, `column_filters`, `quick_filters`, `column_widths`, `sort`, `isolate`).
- Reusing existing normalizers (`normalizePreviousRunsColumnFilterList`, isolate normalizers, width sanitizers) avoids adding a second schema path that can drift and break load behavior after future UI changes.
- Applying a preset should push state back through existing render/update paths (`setupPreviousRunsQuickFilters`, `renderAll`) so table, chart, and diagnostics stay aligned.

```

### 2026-03-03_11.36.11 dashboard-program-side-ui-state-persistence

Source:
- `docs/understandings/2026-03-03_11.36.11-dashboard-program-side-ui-state-persistence.md`

Summary:
- Dashboard UI state can only be written program-side through an HTTP endpoint; static file mode remains localStorage-only.

Preserved notes:

```md
summary: "Dashboard UI state can only be written program-side through an HTTP endpoint; static file mode remains localStorage-only."
read_when:
  - "When adding cross-browser persistence for Previous Runs settings"
  - "When changing stats-dashboard serve/open behavior or dashboard UI-state sync"
---

# Dashboard program-side UI state persistence

- `index.html` is static HTML/JS; direct `file://` usage cannot write disk files from browser JS, so `localStorage` was the only writable store.
- Cross-browser persistence needs a process-side write path; implemented as `assets/dashboard_ui_state.json` via a local HTTP endpoint when running `cookimport stats-dashboard --serve`.
- Frontend state now dual-writes: browser `localStorage` plus best-effort PUT to `assets/dashboard_ui_state.json`; load path reads local storage first, then merges server state by `saved_at` recency.
- In `--serve` mode the page also polls program-side state every few seconds for newer `saved_at` values and applies them live; remote-apply renders suppress re-persist to avoid cross-browser sync loops.

```

### 2026-03-03_11.38.01 stats-dashboard-optioninfo-direct-call

Source:
- `docs/understandings/2026-03-03_11.38.01-stats-dashboard-optioninfo-direct-call.md`

Summary:
- Direct Python calls to stats_dashboard can receive Typer OptionInfo defaults unless unwrapped first.

Preserved notes:

```md
summary: "Direct Python calls to stats_dashboard can receive Typer OptionInfo defaults unless unwrapped first."
read_when:
  - "When stats_dashboard crashes with OptionInfo type errors in interactive mode or helper-triggered calls"
  - "When adding CLI commands that are called both via Typer dispatch and direct Python calls"
---

`stats_dashboard(...)` is invoked from interactive mode as a plain Python function call.
When optional args are omitted in that path, Typer-injected defaults remain as `OptionInfo` objects.
Without early unwrapping, `if serve:` becomes truthy and `int(port)` crashes because `port` is `OptionInfo`.

Fix pattern: mirror `stage(...)` and unwrap every Typer option at function entry via `_unwrap_typer_option_default(...)` before any branching or type coercion.

```

### 2026-03-03_11.40.07 dashboard-quick-filters-primary-official-advanced-ai-tests

Source:
- `docs/understandings/2026-03-03_11.40.07-dashboard-quick-filters-primary-official-advanced-ai-tests.md`

Summary:
- Quick Filters now keep official-only as the primary toggle while rendering test/smoke exclusion as a second checkbox in the same group.

Preserved notes:

```md
summary: "Quick Filters now keep official-only as the primary toggle while rendering test/smoke exclusion as a second checkbox in the same group."
read_when:
  - "When adjusting Quick Filters UI layout or defaults in stats dashboard"
  - "When quick-filter row counts or column-suggestion values drift from visible rows"
---

# Dashboard quick filters: grouped primary + secondary toggles

- `currentPreviousRunsFilterResult()` and `previousRunsRecordsMatchingOtherFilters(...)` both call `applyPreviousRunsQuickFilters(...)`; this keeps chart, table, isolate, and filter-suggestion values aligned.
- Keeping `exclude_ai_tests` as a secondary checkbox in the same quick-filter group still preserves state compatibility because the key remains unchanged (`exclude_ai_tests`) across presets/localStorage/program-state payloads.
- Default `exclude_ai_tests=false` avoids hidden filtering surprises while `official_full_golden_only=true` remains the visible headline default.

```

### 2026-03-03_11.41.44 dashboard-isolate-vs-table-filter-last-edited-wins

Source:
- `docs/understandings/2026-03-03_11.41.44-dashboard-isolate-vs-table-filter-last-edited-wins.md`

Summary:
- Previous Runs now uses last-edited-wins handoff between isolate rules and table column filters.

Preserved notes:

```md
summary: "Previous Runs now uses last-edited-wins handoff between isolate rules and table column filters."
read_when:
  - "When changing Previous Runs isolate and column-filter interaction behavior"
  - "When users report isolate/table filter precedence confusion"
---

# Dashboard isolate/table precedence handoff

Discovery:
- Applying isolate and column filters simultaneously made intent ambiguous when both were active.
- The dashboard now tracks a control source (`table` or `isolate`) and applies only that source's filter set after quick filters.

Contract:
- Editing isolate controls sets control to `isolate`; isolate rules override table column filters.
- Editing table column filters sets control to `table`; isolate rules are paused until isolate is edited again.
- Control source persists in dashboard UI state (`previous_runs.filter_control_source`) and in saved view presets.

```

### 2026-03-03_11.43.35 dashboard-diagnostics-run-group-vs-eval-timestamp

Source:
- `docs/understandings/2026-03-03_11.43.35-dashboard-diagnostics-run-group-vs-eval-timestamp.md`

Summary:
- Per-label and boundary diagnostics must group latest benchmark rows by run-group key, not exact eval timestamp, so twinned vanilla/codexfarm rows aggregate together.

Preserved notes:

```md
summary: "Per-label and boundary diagnostics must group latest benchmark rows by run-group key, not exact eval timestamp, so twinned vanilla/codexfarm rows aggregate together."
read_when:
  - "When Per-Label Breakdown or Boundary Classification says 1 eval for a twinned single-offline run"
  - "When changing diagnostics latest-run grouping logic in dashboard_render.py"
---

# Dashboard diagnostics run-group vs eval timestamp

Discovery:
- A single-offline twinned run can produce different `run_timestamp` values for `vanilla` and `codexfarm` because one eval finishes later.
- Diagnostics cards (`Per-Label Breakdown`, `Boundary Classification`) were selecting latest rows by exact `run_timestamp`, so the later variant could show as `1 eval` even when both variants existed.

Implementation:
- Reused `benchmarkRunGroupInfo` in diagnostics selection.
- Latest diagnostics now select records by latest run-group key (artifact-path timestamp token, fallback to `run_timestamp`) before counting/aggregating evals.

Result:
- Twinned runs are aggregated consistently in diagnostics headers and totals even when eval completion timestamps differ.

```

### 2026-03-03_11.46.52 dashboard-previous-runs-clear-all-filters-scope

Source:
- `docs/understandings/2026-03-03_11.46.52-dashboard-previous-runs-clear-all-filters-scope.md`

Summary:
- Previous Runs clear-all now resets quick filters, table column filters, and isolate rules together.

Preserved notes:

```md
summary: "Previous Runs clear-all now resets quick filters, table column filters, and isolate rules together."
read_when:
  - "When changing Previous Runs filter-reset behavior in dashboard_render.py"
  - "When users report that Clear all filters does not fully reset the table"
---

# Dashboard Previous Runs clear-all filter scope

Discovery:
- The existing `Clear all filters` control lived inside the `+/-` popup and only cleared stacked table column filters.
- Quick filters and isolate rules remained active, so users could still see filtered table rows after clicking that button.

Contract:
- `Quick Filters` now includes a visible `Clear all filters` button.
- This action resets:
  - quick filters (`official benchmarks only`, `exclude AI tests/smoke`)
  - stacked table column filters (`+/-` filter editors)
  - isolate rules and isolate combine mode (`all`)
- The popup action remains available as `Clear column filters` for column-only clearing.

```

### 2026-03-03_11.47.44 dashboard-filter-summary-per-clause-lines

Source:
- `docs/understandings/2026-03-03_11.47.44-dashboard-filter-summary-per-clause-lines.md`

Summary:
- Previous Runs filter summary row is built in renderPreviousRunsTableColumns and can remove clauses directly without opening the popup.

Preserved notes:

```md
summary: "Previous Runs filter summary row is built in renderPreviousRunsTableColumns and can remove clauses directly without opening the popup."
read_when:
  - "When changing how active column filters are displayed in the Previous Runs sticky filter row"
  - "When debugging per-clause remove buttons or filter row height offsets"
---

# Dashboard filter summary per-clause lines

- In-row filter summaries are rendered inside `renderPreviousRunsTableColumns(...)` (`cookimport/analytics/dashboard_render.py`) under `.previous-runs-column-filter-summary`.
- The row height used for sticky offsets comes from measured `previous-runs-active-filters-row` height, so multi-line summaries are safe and should not use hard-coded offsets.
- Clause removal in-row should call `removePreviousRunsColumnFilterAt(fieldName, clauseIndex)` and then `renderAll()` so table, chart, and filter chips stay synchronized.

```

### 2026-03-03_12.00.09 dashboard-presets-popout-in-quick-filters

Source:
- `docs/understandings/2026-03-03_12.00.09-dashboard-presets-popout-in-quick-filters.md`

Summary:
- Historical note: dashboard presets were temporarily moved to a Quick Filters popout before later returning to inline controls.

Preserved notes:

```md
summary: "Historical note: dashboard presets were temporarily moved to a Quick Filters popout before later returning to inline controls."
read_when:
  - "When auditing historical Previous Runs preset UI layout decisions"
  - "When debugging preset load/save behavior after UI layout changes"
---

# Dashboard presets popout in Quick Filters (historical)

- Superseded by `docs/understandings/2026-03-03_12.04.48-dashboard-quick-filters-inline-presets-controls.md`.

- Keeping preset IDs and state functions unchanged (`renderPreviousRunsPresetEditor`, `saveCurrentPreviousRunsViewPreset`, `applyPreviousRunsPresetByName`) makes UI relocation low-risk.
- The separate `Presets` popout in Quick Filters should own its own open/close state and outside-click handling, but must synchronize with the existing `+/-` popout so both do not stay open together.
- This keeps preset behavior stable while matching UX expectations: columns remain in `+/-`, presets live in Quick Filters.

```

### 2026-03-03_12.04.48 dashboard-quick-filters-inline-presets-controls

Source:
- `docs/understandings/2026-03-03_12.04.48-dashboard-quick-filters-inline-presets-controls.md`

Summary:
- Previous Runs preset controls now render inline inside Quick Filters instead of behind a presets popup.

Preserved notes:

```md
summary: "Previous Runs preset controls now render inline inside Quick Filters instead of behind a presets popup."
read_when:
  - "When changing Quick Filters layout for Previous Runs presets in dashboard_render.py"
  - "When debugging preset load/save/delete controls after dashboard UI layout edits"
---

# Dashboard Quick Filters inline presets controls

- Preset actions (`Load`, `Save current view`, `Delete`) should stay visible in the Quick Filters panel so users can apply them without opening a secondary presets popup.
- Keeping the preset element IDs and existing preset state functions unchanged (`renderPreviousRunsPresetEditor`, `saveCurrentPreviousRunsViewPreset`, `applyPreviousRunsPresetByName`) makes this layout change low-risk for localStorage/program-state compatibility.
- Popup-only JS state (`previousRunsPresetsPopupOpen`, outside-click handlers, toggle sync) can be removed once presets are inline; only the `+/-` column popup still needs open/close state wiring.

```

### 2026-03-03_12.30.35 dashboard-per-label-delta-baseline-flow

Source:
- `docs/understandings/2026-03-03_12.30.35-dashboard-per-label-delta-baseline-flow.md`

Summary:
- Per-label diagnostics should keep latest-run codexfarm precision/recall as raw baseline columns and anchor other deltas to that same-label baseline.

Preserved notes:

```md
summary: "Per-label diagnostics should keep latest-run codexfarm precision/recall as raw baseline columns and anchor other deltas to that same-label baseline."
read_when:
  - "When changing the top diagnostics Per-Label Breakdown table"
  - "When debugging why per-label values differ from raw run metrics"
---

`renderPerLabel()` builds the latest benchmark run-group first, then computes label metrics separately for latest `codexfarm`, latest `vanilla`, and rolling `n=10` windows per variant.

For delta display, the stable comparison anchor is the latest-run `codexfarm` value for the same label and metric (`precision` or `recall`).
Keep latest-run `codexfarm` precision/recall columns as raw scores; only other run/rolling columns should subtract that same baseline per label.

```

### 2026-03-03_12.56.20 dashboard-per-label-rolling-n-selector-state

Source:
- `docs/understandings/2026-03-03_12.56.20-dashboard-per-label-rolling-n-selector-state.md`

Summary:
- Per-label rolling N should be UI-state-backed and update rolling column headers plus aggregation windows in sync.

Preserved notes:

```md
summary: "Per-label rolling N should be UI-state-backed and update rolling column headers plus aggregation windows in sync."
read_when:
  - "When changing Per-Label Breakdown rolling window behavior"
  - "When dashboard rolling header text and rolling values disagree"
---

`renderPerLabel()` now reads `perLabelRollingWindowSize` (sanitized to 1..50) instead of a hardcoded `10`.

The in-card control `#per-label-rolling-window-size` updates this value, persists through dashboard UI state (`previous_runs.per_label_rolling_window_size`), and updates all rolling header labels via `.per-label-rolling-window-value` so `Rolling n=<N>` matches the actual aggregation window.

```

### 2026-03-03_12.56.51 dashboard-ai-effort-suppression-reverted

Source:
- `docs/understandings/2026-03-03_12.56.51-dashboard-ai-effort-suppression-reverted.md`

Summary:
- Removed hard-coded AI effort suppression for three SeaAndSmoke benchmark rows so CSV/runtime effort renders as-is.

Preserved notes:

```md
summary: "Removed hard-coded AI effort suppression for three SeaAndSmoke benchmark rows so CSV/runtime effort renders as-is."
read_when:
  - "When Previous Runs AI effort appears blank for specific historical benchmark timestamps."
  - "When reviewing collector-side exceptions that alter benchmark runtime metadata."
---

# Dashboard AI effort suppression reverted

Discovery:
- `cookimport/analytics/dashboard_collect.py` had a timestamp-specific override that removed effort keys from three SeaAndSmoke rows (`2026-03-03T01:28:32`, `2026-03-02T23:37:21`, `2026-03-02T23:20:13`).

Resolution:
- Removed the suppression hook so benchmark rows keep collector/backfilled `codex_farm_reasoning_effort` values.
- Updated the collector test to assert effort is preserved (`high`) for the known row.

```

### 2026-03-03_13.02.02 dashboard-collector-hard-excludes-gate-test-runs

Source:
- `docs/understandings/2026-03-03_13.02.02-dashboard-collector-hard-excludes-gate-test-runs.md`

Summary:
- Stats dashboard must drop gate/test benchmark artifacts at collector time so diagnostics never pick them as latest runs.

Preserved notes:

```md
summary: "Stats dashboard must drop gate/test benchmark artifacts at collector time so diagnostics never pick them as latest runs."
read_when:
  - "When benchmark gate/test runs still appear in Per-Label Breakdown or Boundary Classification"
  - "When changing benchmark artifact filtering in cookimport/analytics/dashboard_collect.py"
---

# Dashboard collector gate/test exclusion seam

- The quick-filter path in `dashboard_render.py` only affects table/chart views after records are already collected; it cannot prevent diagnostics (`Per-Label Breakdown`, `Boundary Classification`) from choosing a gated run as latest.
- To guarantee test/gate artifacts never surface anywhere in the dashboard, filtering must happen in `collect_dashboard_data` input paths (`_collect_from_csv` and `_collect_benchmarks`).
- Current exclusion tokens are aligned with existing test-noise heuristics and extended for gate runs: `/bench/`, pytest temp layouts, and timestamp-suffix segments containing `gate`/`gated` plus test/smoke keywords.

```

### 2026-03-03_15.40.00 dashboard-previous-runs-column-popup-control

Source:
- `docs/understandings/2026-03-03_15.40.00-dashboard-previous-runs-column-popup-control.md`

Summary:
- Previous Runs column visibility is now controlled by a header-adjacent +/- popup checklist.

Preserved notes:

```md
summary: "Previous Runs column visibility is now controlled by a header-adjacent +/- popup checklist."
read_when:
  - "When changing Previous Runs column-picker UI in dashboard_render.py"
  - "When debugging show/hide column state, popup open/close behavior, or default-column reset"
---

# Dashboard Previous Runs column popup control

- Column visibility state is still `previousRunsVisibleColumns`, but controls are now rendered as a checkbox list inside `#previous-runs-columns-popup`.
- Popup state is managed by `previousRunsColumnsPopupOpen` + `setPreviousRunsColumnsPopupOpen(...)`, with outside-click and `Escape` close behavior wired once in `setupPreviousRunsColumnsControls()`.
- Header drag reorder + resize remain the mechanism for column ordering and widths; the popup only toggles inclusion/exclusion and reset-to-default columns.

```

### 2026-03-03_16.12.00 dashboard-known-backfilled-ai-effort-suppression

Source:
- `docs/understandings/2026-03-03_16.12.00-dashboard-known-backfilled-ai-effort-suppression.md`

Summary:
- Historical note: dashboard once suppressed AI effort for three SeaAndSmoke benchmark rows; behavior was later reverted.

Preserved notes:

```md
summary: "Historical note: dashboard once suppressed AI effort for three SeaAndSmoke benchmark rows; behavior was later reverted."
read_when:
  - "When auditing why older dashboard builds showed blank AI effort for three SeaAndSmoke rows."
  - "When tracing collector-side benchmark runtime exceptions over time."
---

# Known backfilled AI effort suppression

Historical discovery:
- Three SeaAndSmoke benchmark rows in `Previous Runs` showed `AI Effort=high` from historical backfill, but those values are not trusted for that run set.
- A targeted collector-side suppression is safer than changing global runtime-effort parsing behavior.

Historical resolution (superseded):
- `dashboard_collect` now strips effort fields for benchmark rows with timestamps:
  - `2026-03-03T01:28:32`
  - `2026-03-02T23:37:21`
  - `2026-03-02T23:20:13`
- Suppression clears both `run_config` effort keys and any summary-string effort entry so `AI Effort` renders as blank (`-`) in the dashboard table.

Current state:
- This suppression was removed on `2026-03-03` so these rows now keep collector/backfilled effort values.
- See `docs/understandings/2026-03-03_12.56.51-dashboard-ai-effort-suppression-reverted.md`.

```
