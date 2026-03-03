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

