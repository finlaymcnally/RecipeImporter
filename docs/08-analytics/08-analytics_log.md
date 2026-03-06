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

## 2026-03-04 to 2026-03-05 migrated understanding ledger (dashboard + compare/control)

Merged source notes (timestamp order):
- `docs/understandings/2026-03-04_19.28.54-dashboard-responsive-layout-notes.md`
- `docs/understandings/2026-03-04_19.38.38-dashboard-filter-clause-edit-flow.md`
- `docs/understandings/2026-03-04_19.40.07-dashboard-token-zero-vs-ai-model-metadata.md`
- `docs/understandings/2026-03-04_19.46.34-compare-control-dynamic-chart-seam.md`
- `docs/understandings/2026-03-04_19.53.42-compare-control-group-row-format.md`
- `docs/understandings/2026-03-04_19.54.47-compare-control-chart-activation-gate.md`
- `docs/understandings/2026-03-04_20.05.03-compare-control-group-table-rendering.md`
- `docs/understandings/2026-03-04_20.10.12-compare-control-auto-bar-chart-routing.md`
- `docs/understandings/2026-03-04_20.12.15-compare-control-table-header-label-cleanup.md`
- `docs/understandings/2026-03-04_20.12.22-dashboard-compare-control-harness-data-dependency.md`
- `docs/understandings/2026-03-04_20.14.21-dashboard-ai-model-system-error-label.md`
- `docs/understandings/2026-03-04_20.14.32-compare-control-chart-activation-auto-restore.md`
- `docs/understandings/2026-03-04_20.14.35-compare-control-table-number-format-threshold.md`
- `docs/understandings/2026-03-04_20.19.00-compare-control-bar-color-weight-seam.md`
- `docs/understandings/2026-03-04_20.19.15-compare-control-group-display-sort-order.md`
- `docs/understandings/2026-03-04_20.24.25-ai-effort-ai-off-vs-unknown-seam.md`
- `docs/understandings/2026-03-04_20.26.27-compare-control-categorical-color-stability.md`
- `docs/understandings/2026-03-04_20.31.27-ai-effort-vanilla-fallback.md`
- `docs/understandings/2026-03-04_20.40.02-ai-effort-runtime-error-no-ai.md`
- `docs/understandings/2026-03-04_20.31.52-dashboard-metric-tooltip-autotagging-seam.md`
- `docs/understandings/2026-03-04_20.44.54-single-profile-live-panel-wrapping-seam.md`
- `docs/understandings/2026-03-04_20.47.00-compare-control-dual-set-render-seams.md`
- `docs/understandings/2026-03-04_20.55.53-dashboard-per-label-remove-rolling-vanilla-columns.md`
- `docs/understandings/2026-03-04_22.55.00-compare-control-previous-runs-decoupling.md`
- `docs/understandings/2026-03-04_23.36.00-dashboard-metric-tooltip-seam.md`
- `docs/understandings/2026-03-05_22.25.45-benchmark-labeling-semantics-gap.md`
- `docs/understandings/2026-03-05_22.55.48-benchmark-review-findings.md`
- `docs/understandings/2026-03-05_23.05.00-benchmark-labeling-semantics-implementation.md`
- `docs/understandings/2026-03-05_23.17.34-compare-control-dual-column-layout.md`
- `docs/understandings/2026-03-05_23.18.21-compare-control-live-dashboard-state.md`

Problem cluster captured:
- Dashboard render semantics and compare/control behavior were changing quickly enough that raw task closeouts were starting to hide key seams: activation gates, chart routing, table formatting, label semantics, and live-state ownership.

Durable decisions and outcomes:
- Previous Runs token columns must treat blank telemetry as unknown, not numeric zero. `AI Model` / `AI Effort` come from run-config/manifest metadata and can be present even when token telemetry is absent.
- Fatal Codex runtime metadata is first-class analytics context. Dashboard labeling should surface `System error` rather than pretending a failed fallback run was a normal model-backed result.
- AI Effort semantics intentionally do not grow a separate runtime-error bucket. Runtime error rows collapse into `AI off`, while truly missing effort metadata remains `-`.
- Benchmark labeling is intentionally split:
  - `benchmark_variant` keeps official paired benchmark identity only when the authored benchmark contract actually matches,
  - `ai_assistance_profile` captures the real runtime assistance posture so hybrid runs do not get mislabeled as `vanilla` / `AI off`.
- Compare & Control is builder-driven from the filtered Previous Runs dataset. The durable seam is:
  - shared visible rows from Previous Runs,
  - normalized compare/control state,
  - field catalog metadata,
  - chart-definition builders per chart type.
- Chart activation is runtime-only and intentionally non-persistent. Blank-on-load remains the default, but valid restored non-`discover` selections should auto-activate so saved views reopen correctly.
- Categorical compare/control output moved from ad hoc strings to a dynamic table with:
  - display-name-only labels,
  - two-line wrap-safe headers,
  - threshold-based number formatting,
  - display-oriented row ordering,
  - stable per-category colors hashed from compare field + category key.
- Numeric vs categorical compare fields should route to different chart builders (`scatter` vs `bar`) instead of forcing scatter semantics onto grouped categorical data.
- Responsive/layout fixes that matter long-term:
  - avoid hard Previous Runs table floors that prevent shrink on narrow screens,
  - re-render charts on resize using measured host width,
  - keep single-profile live status panels wrap-safe instead of clamping meaningful status text away.
- Previous Runs and Compare & Control state ownership was intentionally decoupled from older isolate-style table mutations. Served dashboards read `assets/dashboard_ui_state.json`; updating that file with a fresher `saved_at` is enough to move the visible panel and chart.

Testing and anti-loop notes preserved:
- Node harness tests that call live-state compare/control helpers must seed `DATA.benchmark_records`; bootstrap-free harnesses otherwise fail for setup reasons, not analytics math reasons.
- If restored compare/control charts stay blank, inspect activation-gate logic before touching chart builders.
- If hybrid runs show up under `vanilla` paths or labels, inspect benchmark-variant classification and single-offline planner contracts together; dashboard relabeling alone is not enough.

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

## 2026-03-03 docs/tasks consolidation batch (dashboard benchmark filtering/runtime display)

### 2026-03-03_13.02.16 dashboard hard exclude gate/test runs

Source task file:
- `docs/tasks/2026-03-03_13.02.16-dashboard-hard-exclude-gate-test-runs.md`

Problem captured:
- UI quick filters alone could not stop gated/test artifacts from being selected as the latest diagnostics run.

Durable decisions/outcomes:
- Keep exclusion in collector input paths (`_collect_from_csv` + benchmark scan collection), not only in renderer filters.
- Keep exclusion deterministic and path-based (`/bench/`, pytest temp layouts, gated/smoke/test suffix tokens).
- Ensure exclusion applies before diagnostics and `Previous Runs` datasets are built.

Evidence preserved in task:
- `pytest tests/analytics/test_stats_dashboard.py -k "gated or pytest_temp_eval_artifacts"`
- `pytest tests/analytics/test_stats_dashboard.py`

### 2026-03-03_13.13.06 dashboard vanilla AI runtime suppression

Source task file:
- `docs/tasks/2026-03-03_13.13.06-dashboard-vanilla-ai-runtime-suppression.md`

Problem captured:
- Paired `single-offline-benchmark` vanilla rows could show codex model/effort values when historical metadata backfill left codex keys in row run-config.

Durable decisions/outcomes:
- Apply suppression in dashboard JS display helpers: when row variant resolves to `vanilla`, show `AI Model` and `AI Effort` as absent.
- Keep variant detection path/pipeline-first so trend/per-label aggregation and official benchmark filters remain consistent.
- Treat this as display-semantics repair; do not rewrite historical CSV/runtime metadata.

Evidence preserved in task:
- `pytest tests/analytics/test_stats_dashboard.py -k "renders_previous_runs_table_and_links_timestamp_to_artifact"`
- `pytest tests/analytics/test_stats_dashboard.py`


## 2026-03-03 docs/understandings consolidation batch

The entries below were merged from `docs/understandings` in timestamp order before source-file cleanup.

### 2026-03-03_13.13.20-dashboard-vanilla-runtime-display-guard

Source:
- `docs/understandings/2026-03-03_13.13.20-dashboard-vanilla-runtime-display-guard.md`

Summary:
- Discovery: vanilla benchmark variants can inherit codex runtime metadata, so dashboard AI columns need variant-aware suppression.

Preserved source note:

````md
---
summary: "Discovery: vanilla benchmark variants can inherit codex runtime metadata, so dashboard AI columns need variant-aware suppression."
read_when:
  - "When debugging why `single-offline` vanilla rows show codex model/effort in Previous Runs"
---

# Discovery

Dashboard AI columns (`AI Model`, `AI Effort`) read model/effort from `run_config` fields. If a vanilla benchmark row carries stale/backfilled codex keys in `run_config`, the row can incorrectly display codex runtime in the table.

# Practical Rule

For `benchmarkVariantForRecord(record) === "vanilla"` (path/pipeline inferred), treat AI model/effort as absent in display helpers, regardless of run-config codex keys.

# Why this works

Variant inference is already used by trend/per-label logic and official single-offline filtering, so using the same signal keeps UI behavior consistent across dashboard surfaces.

````

### 2026-03-03_16.11.09-dashboard-per-label-comparison-mode-toggle

Source:
- `docs/understandings/2026-03-03_16.11.09-dashboard-per-label-comparison-mode-toggle.md`

Summary:
- Per-Label comparison cells should share one mode switch (delta vs point value) while preserving baseline-relative coloring.

Preserved source note:

````md
---
summary: "Per-Label comparison cells should share one mode switch (delta vs point value) while preserving baseline-relative coloring."
read_when:
  - "When editing Per-Label Breakdown comparison cell rendering"
  - "When extending per-label dashboard UI controls/state"
---

# Discovery

Per-Label Breakdown renders all six comparison columns through one shared cell formatter path, so comparison semantics are safest when centralized there with one shared UI-state field.

This keeps:
- one consistent switch across run-vanilla and rolling codexfarm/vanilla comparison columns,
- persisted mode in dashboard UI state,
- codex-oriented delta direction (`codexfarm baseline - comparison`) with baseline-anchored coloring.

````

### 2026-03-03_19.42.15-dashboard-trend-overlay-series-contract

Source:
- `docs/understandings/2026-03-03_19.42.15-dashboard-trend-overlay-series-contract.md`

Summary:
- Benchmark trend overlays should be layered from base scatter series and excluded from grouped tooltips.

Preserved source note:

````md
---
summary: "Benchmark trend overlays should be layered from base scatter series and excluded from grouped tooltips."
read_when:
  - "When adding or changing Benchmark Score Trend overlay series (trendline/bands)"
  - "When trend tooltip rows unexpectedly include synthetic overlay series"
---

# Dashboard trend overlay series contract

`buildBenchmarkTrendSeries(records)` is the seam for trend visualization composition:
- Build base score scatter series first.
- Derive overlay series from each base series (`withTrendOverlays`), so overlays always track whichever variant split is active.
- Mark overlay series with `custom.isTrendOverlay = true` and skip them in grouped tooltip row collection.

This keeps the tooltip tied to raw metric points while still drawing regression context on-chart.

````

### 2026-03-03_19.55.01-isolate-column-filter-global-or

Source:
- `docs/understandings/2026-03-03_19.55.01-isolate-column-filter-global-or.md`

Summary:
- Isolate-to-table unification requires a native cross-column OR combine mode in the Previous Runs column-filter evaluator.

Preserved source note:

````md
---
summary: "Isolate-to-table unification requires a native cross-column OR combine mode in the Previous Runs column-filter evaluator."
read_when:
  - "When changing Isolate For X behavior or table filter expression evaluation"
  - "When debugging why isolate any-rule and table filters diverge"
---

# Discovery

`Isolate For X` and table filters originally used separate filter paths, with table filters hard-coded to AND across columns.

To make isolate rules truly become table column filters, the table evaluator needed a first-class global combine mode (`AND`/`OR`) across field groups, not just per-column clause stack modes.

The implementation now maps isolate clauses into table `eq`/`neq` clauses and sets:
- per-column clause mode to match isolate combine mode,
- global column combine mode to `OR` for isolate `any`, `AND` for isolate `all`.

This preserves isolate semantics while keeping one shared filtering engine.

````

### 2026-03-03_19.59.39-dashboard-trend-paired-variant-xaxis-alignment

Source:
- `docs/understandings/2026-03-03_19.59.39-dashboard-trend-paired-variant-xaxis-alignment.md`

Summary:
- Benchmark trend paired variants drifted on X because each point used eval-row timestamp instead of run-group timestamp.

Preserved source note:

````md
---
summary: "Benchmark trend paired variants drifted on X because each point used eval-row timestamp instead of run-group timestamp."
read_when:
  - "When codexfarm/vanilla points from the same benchmark run do not align on the trend chart"
  - "When editing benchmark trend point construction in cookimport/analytics/dashboard_render.py"
---

# Dashboard trend paired-variant X-axis alignment

Root cause: `benchmarkSeriesFromRecords(...)` used `parseTs(record.run_timestamp)` for each point's `x`, so paired `vanilla`/`codexfarm` rows from one benchmark session could land a few seconds apart (different eval completion times).

Fix seam: resolve `x` from run-group timestamp first (`benchmarkRunGroupInfo` timestamp token from artifact path), then fall back to row timestamp only when no run-group timestamp is parseable.

Outcome: paired variants in the same run group share one X position while keeping separate series and grouped tooltip behavior.

````

### 2026-03-03_20.32.36-isolate-numeric-operator-contract

Source:
- `docs/understandings/2026-03-03_20.32.36-isolate-numeric-operator-contract.md`

Summary:
- Isolate numeric comparisons require field-typed operator sets and numeric-value normalization before syncing into table filters.

Preserved source note:

````md
---
summary: "Isolate numeric comparisons require field-typed operator sets and numeric-value normalization before syncing into table filters."
read_when:
  - "When changing Isolate For X operator behavior or value input controls"
  - "When isolate numeric rules do not match Previous Runs table filter results"
---

# Discovery

Adding `>`, `>=`, `<`, `<=` to `Isolate For X` is not just an operator-list change.

To keep isolate behavior identical to table filters, isolate rules must:
- choose operator options by field type (numeric vs categorical),
- validate/normalize numeric values before a clause is considered active,
- sync operator + value directly into table filter clauses (`gt/gte/lt/lte/eq/neq`),
- evaluate row matching with the same `evaluatePreviousRunsFilterOperator(...)` path used by table filters.

This keeps isolate and table filters as one semantics engine.

````

### 2026-03-03_21.50.00-isolateforxv2-plan-rebaseline-dashboard-seams

Source:
- `docs/understandings/2026-03-03_21.50.00-isolateforxv2-plan-rebaseline-dashboard-seams.md`

Summary:
- Discovery note: Compare/Isolate planning must target dashboard_render.py JS templates and existing table-filter/state seams.

Preserved source note:

````md
---
summary: "Discovery note: Compare/Isolate planning must target dashboard_render.py JS templates and existing table-filter/state seams."
read_when:
  - "When reworking Isolate For X or adding Compare & Control behavior in stats-dashboard."
  - "When an ExecPlan references dashboard files/tests that do not exist in this repo."
---

# Discovery

For stats-dashboard, frontend behavior is emitted from `cookimport/analytics/dashboard_render.py` (`_HTML`, `_CSS`, `_JS`), not from a separate JS source tree. Isolate already writes into table filters (`applyIsolateRulesToTableFilters`) and shares the same evaluator (`recordMatchesPreviousRunsFilterGroups` + `evaluatePreviousRunsFilterOperator`). UI persistence for Previous Runs and presets is centralized in `buildDashboardUiStatePayload` / `applyDashboardUiStatePayload`.

Practical planning implication: Compare & Control should be added as a sibling panel that reuses these seams, and regression tests should extend `tests/analytics/test_stats_dashboard.py` (current dashboard contract anchor) instead of referencing non-existent dashboard test modules.
````

## 2026-03-03 docs/tasks consolidation batch (dashboard comparison mode, trend overlays, isolate/filter contracts)

### 2026-03-03_16.11.20 per-label comparison mode toggle

Source task:
- `docs/tasks/2026-03-03_16.11.20-per-label-point-value-toggle.md`

Problem captured:
- Per-label comparison columns were fixed to baseline delta display and lacked a quick raw point-value view.

Decision/outcome preserved:
- Added one persisted dashboard mode (`per_label_comparison_mode`) that flips all comparison columns between `delta` and `point value` without changing collector/CSV contracts.
- Delta sign convention remains codex-baseline oriented (`codexfarm baseline - comparison`).

Evidence preserved:
- `pytest tests/analytics/test_stats_dashboard.py` -> `61 passed`.

### 2026-03-03_19.42.12 trendline + ±1σ overlays

Source task:
- `docs/tasks/2026-03-03_19.42.12-dashboard-trendline-std-band.md`

Problem captured:
- Benchmark trend chart showed raw points only and lacked quick visual trajectory/spread context.

Decision/outcome preserved:
- Added per-series linear trendline + `±1σ` shaded band overlays in dashboard JS generation while keeping base scatter points and tooltip focus on raw metrics.
- Added Highcharts secondary module fallback (`highcharts-more`) for `arearange` rendering.

Evidence preserved:
- Targeted pre/post checks in task:
  - fail-before assertions: `2 failed`.
  - pass-after targeted: `2 passed`.
  - full analytics module: `61 passed`.

### 2026-03-03_19.56.30 isolate/table filter unification with native cross-column OR

Source task:
- `docs/tasks/2026-03-03_19.56.30-isolate-table-filter-unification.md`

Problem captured:
- Isolate rules and table filters used separate evaluation paths; table engine lacked native top-level OR across columns.

Decision/outcome preserved:
- Added global filter combine mode (`column_filter_global_mode=AND|OR`) and mapped isolate edits directly into table filter clauses.
- Kept compatibility state fields while unifying semantics into one evaluator.

Evidence preserved:
- `. .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py -q` passed.

### 2026-03-03_19.59.52 paired-variant trend X-axis alignment

Source task:
- `docs/tasks/2026-03-03_19.59.52-dashboard-paired-variant-xaxis-alignment.md`

Problem captured:
- Same-run codexfarm/vanilla points were horizontally offset because row timestamp seconds differed.

Decision/outcome preserved:
- Trend point `x` now resolves from run-group timestamp first, with row timestamp fallback only when run-group timestamp is unavailable.

Evidence preserved:
- `pytest tests/analytics/test_stats_dashboard.py -k benchmark_trend_chart_uses_fixed_height` -> `1 passed`.
- Full dashboard module run in task: `62 passed`.

### 2026-03-03_20.33.20 isolate numeric operators and typed value controls

Source task:
- `docs/tasks/2026-03-03_20.33.20-isolate-numeric-boolean-logic.md`

Problem captured:
- Isolate controls could not express numeric thresholds with stable table-filter parity.

Decision/outcome preserved:
- Added numeric operator sets for numeric fields and numeric input normalization before clause activation.
- Isolate matching reuses table operator evaluation (`eq/neq/gt/gte/lt/lte`) for semantics parity.

Evidence preserved:
- `. .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py -q` passed.

## 2026-03-03 docs/tasks consolidation batch (IsolateForXv2 -> isolate removal -> backend compare-control)

Merged source task files (timestamp/file order):
- `docs/tasks/IsolateForXv2.md`
- `docs/tasks/2026-03-03_22.54.59-remove-isolate-for-x-dashboard.md`
- `docs/tasks/2026-03-03_23.05.29-compare-control-agent-cli.md`

### 2026-03-03_22.00.24 IsolateForXv2 implementation baseline

Source task:
- `docs/tasks/IsolateForXv2.md`

Problem captured:
- Previous Runs had deterministic slicing (`Isolate For X`) but no local attribution workspace for "what drives metric movement" with confounder control.

Decision/outcome preserved:
- Added `Compare & Control` as a sibling panel to isolate in `cookimport/analytics/dashboard_render.py` with persisted state under `previous_runs.compare_control`.
- Implemented deterministic browser-side analysis for:
  - categorical/raw,
  - numeric/raw,
  - categorical/controlled (exact strata weighting),
  - numeric/controlled (within-strata centering),
  - discovery ranking when compare field is unset.
- `Filter to subset` intentionally wrote through existing table filter helpers, not a parallel filtering engine.

Evidence preserved:
- `. .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py -q` passed.
- `. .venv/bin/activate && cookimport stats-dashboard` completed.

### 2026-03-03_22.54.59 remove isolate from dashboard

Source task:
- `docs/tasks/2026-03-03_22.54.59-remove-isolate-for-x-dashboard.md`

Problem captured:
- Once Compare/Control was available, isolate + compare dual-panel UX created overlapping slice surfaces and confusing status/state messaging.

Decision/outcome preserved:
- Removed Isolate For X end-to-end (rendering, state/control-source plumbing, and isolate-specific status text) while keeping Compare/Control and table-filter behavior intact.
- Kept backward compatibility for legacy saved UI/preset payloads that still contain isolate keys.

Evidence preserved:
- `. .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py -q` passed.
- `. .venv/bin/activate && cookimport stats-dashboard` completed.

Anti-loop note:
- Do not revert to hiding isolate UI only; previous task explicitly chose full removal to avoid stale state/control complexity.

### 2026-03-03_23.05.29 backend compare-control CLI/agent parity

Source task:
- `docs/tasks/2026-03-03_23.05.29-compare-control-agent-cli.md`

Problem captured:
- Compare/Control analysis was JS-only in generated dashboard pages, so terminal/agent tooling could not query it deterministically.

Decision/outcome preserved:
- Added parity-safe backend engine in `cookimport/analytics/compare_control_engine.py` mirroring dashboard derived fields/filter semantics.
- Added CLI surfaces:
  - `cookimport compare-control run`
  - `cookimport compare-control agent` (JSONL request/response loop with stable error envelope)
- Added `insights` action (auto-profile + actionable driver filtering + follow-up query suggestions).
- Added QualitySuite bridge handoff artifacts (`agent_compare_control/`) in `quality-run` and `quality-compare` outputs.

Key parity details preserved:
- `all_token_use` discounted formula: `(input - cached_input) + 0.1 * cached_input + output`.
- Controlled categorical parity fixture intentionally demonstrates direction flip (`raw A > raw B` but `controlled B > controlled A`).
- Subset patch remains table-filter contract (`eq` clauses + `or` mode for selected groups).

Evidence preserved:
- Engine + CLI parity tests added and passing:
  - `tests/analytics/test_compare_control_engine.py`
  - `tests/analytics/test_compare_control_cli.py`
- Existing dashboard compare/control tests remained green in `tests/analytics/test_stats_dashboard.py`.

Anti-loop reminders:
- If dashboard and backend outputs diverge, validate field resolution/filter semantics first (`previousRunsFieldValue` parity), not chart/UI rendering.
- Keep analysis local/deterministic; this path intentionally excludes LLM-in-the-loop behavior.

## 2026-03-04 docs/understandings consolidation batch (Compare/Control + isolate removal chronology)

Merged source notes below are preserved in timestamp order to keep implementation/audit context intact.
### 2026-03-03_22.00.24-compare-control-dashboard-seams

Source:
- `docs/understandings/2026-03-03_22.00.24-compare-control-dashboard-seams.md`

Summary:
- Compare & Control implementation discovery: reuse Previous Runs filtered-row output and table-filter writer seams to avoid parallel filtering logic.

Preserved source note:

````md
---
summary: "Compare & Control implementation discovery: reuse Previous Runs filtered-row output and table-filter writer seams to avoid parallel filtering logic."
read_when:
  - "When extending Compare & Control behavior in stats-dashboard."
  - "When debugging Filter to subset interactions with Previous Runs table filters."
---

# Discovery

`Compare & Control` should run on `computePreviousRunsFilterResult().records` (already quick-filter + table-filter constrained) and only write subsets through existing table filter helpers.

# Evidence

- `computePreviousRunsFilterResult()` is the shared source for table rows and trend points.
- `setPreviousRunsColumnFilterClauses(...)` + `setPreviousRunsColumnFilterMode(...)` already provide deterministic clause writes for one field.
- Reusing those helpers keeps `Filter to subset` aligned with existing status text, persistence, preset behavior, and chart/table synchronization.
````

### 2026-03-03_22.22.36-compare-control-gap-closure

Source:
- `docs/understandings/2026-03-03_22.22.36-compare-control-gap-closure.md`

Summary:
- Gap-closure design for Compare & Control: secondary categorical metrics, weak coverage warnings, and legacy state compatibility checks.

Preserved source note:

````md
---
summary: "Gap-closure design for Compare & Control: secondary categorical metrics, weak coverage warnings, and legacy state compatibility checks."
read_when:
  - "When extending Compare & Control categorical outputs or controlled-coverage messaging."
  - "When validating dashboard UI-state backward compatibility for missing compare_control keys."
---

- Raw categorical compare can add useful context without changing filter semantics by computing optional per-group means for a short list of runtime/token/cost numeric fields.
- Controlled mode already had coverage counts; adding explicit warning text in results is the missing UX contract so low-coverage controlled estimates are not treated as definitive.
- Legacy payload compatibility is already implemented in JS (`hasOwnProperty('compare_control')` fallback); adding explicit test assertions prevents regressions when UI-state schema evolves.
````

### 2026-03-03_22.31.58-isolateforxv2-og-vs-implementation-audit

Source:
- `docs/understandings/2026-03-03_22.31.58-isolateforxv2-og-vs-implementation-audit.md`

Summary:
- Audit result: IsolateForXv2 OG milestones are implemented; remaining gap is mostly behavioral test depth for compare/control math and filter handoff.

Preserved source note:

````md
---
summary: "Audit result: IsolateForXv2 OG milestones are implemented; remaining gap is mostly behavioral test depth for compare/control math and filter handoff."
read_when:
  - "When validating docs/plans/OGplan/IsolateForXv2.md against current dashboard code."
  - "When deciding whether Compare & Control needs stronger behavior-level tests beyond JS string-contract assertions."
---

- Verified against code: OG milestones for Compare & Control shell/state, raw and controlled analysis, split-by support, and Filter-to-subset table-filter handoff are implemented in `cookimport/analytics/dashboard_render.py`.
- Verified against docs/tests: analytics docs describe the shipped behavior and `tests/analytics/test_stats_dashboard.py` includes markup/JS/state-contract assertions for compare_control persistence compatibility.
- Residual gap: acceptance-level behavior (for example, controlled-vs-raw divergence on confounded data and concrete Filter-to-subset result assertions) is not covered by dedicated behavior-driven test fixtures yet.
````

### 2026-03-03_22.38.48-compare-control-categorical-controlled-weighting-fix

Source:
- `docs/understandings/2026-03-03_22.38.48-compare-control-categorical-controlled-weighting-fix.md`

Summary:
- Compare & Control categorical controlled mode now uses stratum-standardized weighting; added Node harness tests for confounding reversal and Filter-to-subset clause writes.

Preserved source note:

````md
---
summary: "Compare & Control categorical controlled mode now uses stratum-standardized weighting; added Node harness tests for confounding reversal and Filter-to-subset clause writes."
read_when:
  - "When debugging Compare & Control controlled categorical metrics in stats-dashboard."
  - "When updating behavior tests that execute generated dashboard.js compare/control logic."
---

- Discovery: the prior controlled categorical aggregation used per-group row counts as weights, which preserves group-mix confounding and can make controlled means equal raw means even when hold-constant strata are present.
- Fix: controlled categorical now applies shared stratum weights (`stratum total rows`) to each group's within-stratum mean, so groups are compared on the same stratum mix.
- Test coverage: `tests/analytics/test_stats_dashboard.py` now runs generated dashboard JS in a Node harness (bootstrap disabled) and verifies:
  - confounded fixture reversal (`raw` favors A while `controlled` favors B),
  - `Filter to subset` writes `eq` clauses + `or` mode into existing table column filters.
````

### 2026-03-03_22.45.05-compare-control-vs-isolate-intent

Source:
- `docs/understandings/2026-03-03_22.45.05-compare-control-vs-isolate-intent.md`

Summary:
- Dashboard intent check: Compare & Control complements Isolate For X; it was not intended to replace it.

Preserved source note:

````md
---
summary: "Dashboard intent check: Compare & Control complements Isolate For X; it was not intended to replace it."
read_when:
  - "When deciding whether to remove or rename Isolate For X in stats-dashboard."
  - "When adjusting Previous Runs analysis/filter UX boundaries."
---

- Source intent in `docs/tasks/IsolateForXv2.md` defines two distinct workflows: Isolate remains the deterministic row-slicing/filtering surface, while Compare & Control adds attribution/confounding analysis on visible rows.
- Current dashboard markup in `cookimport/analytics/dashboard_render.py` still renders both panels side-by-side under `Previous Runs`.
- Compare & Control and Isolate both write through the same table-filter engine, but for different user goals (`Isolate`: explicit rule-based slicing; `Compare & Control`: analysis + optional subset handoff).
````

### 2026-03-03_22.54.37-dashboard-isolate-removal-seams

Source:
- `docs/understandings/2026-03-03_22.54.37-dashboard-isolate-removal-seams.md`

Summary:
- Isolate For X removal seam map: delete isolate UI/logic, keep compare/control and table filter pipeline as the single slice path.

Preserved source note:

````md
---
summary: "Isolate For X removal seam map: delete isolate UI/logic, keep compare/control and table filter pipeline as the single slice path."
read_when:
  - "When removing or re-introducing Previous Runs isolate-style slicing behavior."
  - "When debugging compare/control after changes to Previous Runs filtering state/preset payloads."
---

- `Previous Runs` filtering now has one slice path: quick filters + table column filters (`computePreviousRunsFilterResult`), then compare/control reads those matched rows.
- Safe isolate removal required deleting isolate-specific HTML/CSS and removing isolate keys from preset/UI-state write paths while tolerating legacy payload keys on load.
- Status text and table-filter editor actions should no longer mention filter-control-source handoff; they only report active filters and global AND/OR mode.
````

### 2026-03-03_22.58.03-compare-control-view-mode-discover-raw-controlled

Source:
- `docs/understandings/2026-03-03_22.58.03-compare-control-view-mode-discover-raw-controlled.md`

Summary:
- Compare & Control view semantics: `discover` is field-finding mode; `raw` and `controlled` are analysis modes.

Preserved source note:

````md
---
summary: "Compare & Control view semantics: `discover` is field-finding mode; `raw` and `controlled` are analysis modes."
read_when:
  - "When editing Compare & Control docs and `View` mode wording."
  - "When UI behavior seems inconsistent between `discover` and `raw`/`controlled`."
---

# Discovery

`View` intentionally has three values:
- `discover`: show ranked candidate compare fields (exploration mode).
- `raw`: run direct comparison analysis.
- `controlled`: run hold-constant-strata analysis.

The how-to wording can feel contradictory because one step uses `View=discover` for field selection, while the later "how careful" section describes only the two analysis modes (`raw`, `controlled`).

# Evidence

- UI dropdown includes all three options in one control.
- Rendering logic enters discovery when compare field is empty **or** view is `discover`.
- Clicking a discovery card sets `compare_field` and switches `view_mode` to `raw`.
````

### 2026-03-03_23.04.55-dashboard-previous-runs-metrics-sources

Source:
- `docs/understandings/2026-03-03_23.04.55-dashboard-previous-runs-metrics-sources.md`

Summary:
- Source map for where Previous Runs metrics and derived fields come from.

Preserved source note:

````md
---
summary: "Source map for where Previous Runs metrics and derived fields come from."
read_when:
  - "When tracing metric origins in dashboard Previous Runs."
  - "When adding backend analytics that must match Previous Runs field semantics."
---

# Dashboard "Previous Runs" metrics: where they come from

- The "Previous Runs" table is driven by `DashboardData.benchmark_records` (schema: `cookimport/analytics/dashboard_schema.py::BenchmarkRecord`). Field options come from `collectBenchmarkFieldPaths()` in `cookimport/analytics/dashboard_render.py`, which flattens every key in the benchmark record objects and also adds a few derived convenience columns (ex: `source_label`, `source_file_basename`, `ai_model`, `ai_effort`, `artifact_dir_basename`, `all_method_record`, `speed_suite_record`, `all_token_use`).

- Benchmark records are collected primarily from `data/.history/performance_history.csv` (CSV-first contract), with best-effort enrichment from artifacts like `eval_report.json` plus optional `coverage.json` and `manifest.json` (collector: `cookimport/analytics/dashboard_collect.py::_collect_benchmarks`).

- Strict vs practical vs supported metrics originate from the Label Studio evaluation logic (`cookimport/labelstudio/eval_freeform.py`). "Practical" metrics use more forgiving overlap-based matching; "supported_*" metrics restrict scoring to the app-supported label set.

- Boundary classification counts (`boundary_correct/over/under/partial`) are computed per matched span via `_classify_boundary()` in `cookimport/labelstudio/eval_freeform.py`: exact boundary match => `correct`; prediction contains gold => `over`; prediction inside gold => `under`; otherwise => `partial`.

- The `all_token_use` column in the dashboard is a derived "discounted" token total computed in `cookimport/analytics/dashboard_render.py::previousRunsDiscountedTokenTotal()`: roughly `(input - cached_input) + 0.1 * cached_input + output` (falls back to `tokens_total` if parts are missing).
````

### 2026-03-03_23.05.29-compare-control-backend-cli-seams

Source:
- `docs/understandings/2026-03-03_23.05.29-compare-control-backend-cli-seams.md`

Summary:
- Seam map for adding a backend Compare & Control CLI without diverging from dashboard behavior.

Preserved source note:

````md
---
summary: "Seam map for adding a backend Compare & Control CLI without diverging from dashboard behavior."
read_when:
  - "When implementing a backend/agent CLI for Compare & Control."
  - "When trying to keep CLI analysis parity with dashboard Compare & Control results."
---

# Discovery

`Compare & Control` analytics currently live only in generated dashboard JavaScript (`cookimport/analytics/dashboard_render.py`) and are not available as reusable Python functions.

# Evidence

- Analysis helpers are JS-only (`analyzeCompareControlCategoricalRaw`, `analyzeCompareControlNumericRaw`, `analyzeCompareControlCategoricalControlled`, `analyzeCompareControlNumericControlled`).
- The panel runs on already-filtered rows from `computePreviousRunsFilterResult()` (quick filters + column filters).
- `Filter to subset` uses existing table-filter writers (`setPreviousRunsColumnFilterClauses`, `setPreviousRunsColumnFilterMode`) instead of a separate filter engine.
- Important derived fields (`source_label`, `ai_model`, `ai_effort`, `all_token_use`) are resolved through `previousRunsFieldValue(...)`, not directly from raw benchmark record keys.

# Implication

A backend/agent CLI should extract or recreate these semantics in Python first (filters, derived fields, and compare/control math), then have dashboard JS and CLI share that logic contract to avoid split-brain analytics.
````

### 2026-03-03_23.17.54-compare-control-agent-cli-plan-hardening

Source:
- `docs/understandings/2026-03-03_23.17.54-compare-control-agent-cli-plan-hardening.md`

Summary:
- Hardening notes for backend Compare & Control CLI plan: JS seam map, test anchors, and Typer integration points.

Preserved source note:

````md
---
summary: "Hardening notes for backend Compare & Control CLI plan: JS seam map, test anchors, and Typer integration points."
read_when:
  - "When implementing docs/plans/2026-03-03_23.05.29-compare-control-agent-cli.md."
  - "When validating backend compare/control parity against dashboard behavior."
---

# Discovery

Backend compare/control should be implemented as a Python engine plus CLI adapter, not as ad-hoc CLI logic, because the dashboard semantics are spread across JS helper seams that must stay consistent (derived fields, filter operators, controlled weighting, and subset patch writes).

# Evidence

- Compare/control analysis functions exist only in dashboard JS emitted by `cookimport/analytics/dashboard_render.py` (`analyzeCompareControlCategoricalRaw`, `analyzeCompareControlNumericRaw`, `analyzeCompareControlCategoricalControlled`, `analyzeCompareControlNumericControlled`, `analyzeCompareControlDiscovery`).
- Row selection context comes from `computePreviousRunsFilterResult()` (quick filters + column filters) and not directly from raw benchmark rows.
- Derived field parity depends on `previousRunsFieldValue(...)`, especially `source_label`, `ai_model`, `ai_effort`, `all_token_use`, `artifact_dir_basename`, `all_method_record`, and `speed_suite_record`.
- Subset patch behavior contract is encoded in `syncCompareControlSelectionToTableFilters()` and writes `eq` clauses with `or` mode.
- Existing behavior tests in `tests/analytics/test_stats_dashboard.py` already validate controlled categorical weighting and subset patch output.
- CLI integration should follow existing Typer subgroup pattern in `cookimport/cli.py` (`app.add_typer(...)` pattern used by `bench` and `epub`).

# Implication

Implementation should prioritize one deterministic backend engine module that mirrors JS semantics, then expose it through a Typer `compare-control` subgroup with `run` and `agent` commands. The safest parity validation path is to add backend engine/CLI tests while continuing to run existing dashboard compare/control tests.
````

### 2026-03-03_23.38.21-compare-control-cli-usage-playbook

Source:
- `docs/understandings/2026-03-03_23.38.21-compare-control-cli-usage-playbook.md`

Summary:
- Practical usage playbook for compare-control run/agent based on real local-output trials.

Preserved source note:

````md
---
summary: "Practical usage playbook for compare-control run/agent based on real local-output trials."
read_when:
  - "When using cookimport compare-control from terminal and results feel noisy or hard to act on."
  - "When deciding between one-shot run mode and persistent agent mode."
---

- Discovery context: validated `cookimport compare-control run` and `cookimport compare-control agent` against current local benchmark history (`data/output`, `data/golden`) and inspected response contracts.

- Best operational path:
  - Use `agent` for iterative analysis (load once, send many JSON lines).
  - First call `fields` to inspect available fields, cardinality, and active quick-filter context.
  - Then call `analyze` directly with explicit `compare_field` and `outcome_field`; do not rely on unfiltered `discover` as the only field picker.

- Why `discover` can be noisy:
  - High-cardinality identity fields (for example artifact/report paths and run-config hashes) can dominate top scores.
  - This is expected from current scoring because those fields strongly partition outcomes, even when they are not decision-friendly knobs.

- Suggestion caveat (important):
  - `suggest_hold_constants` and `suggest_splits` can rank outcome-adjacent metrics (for example `f1`, `precision`, `recall`) at the top.
  - For practical compare/control use, treat those as leakage-style signals and prefer operational controls (for example `source_label`, importer/config knobs) instead.

- Coverage behavior to trust:
  - Controlled mode emits warnings when comparability collapses (example observed: holding constant on `processed_report_path` produced `used_rows=0` and warning text).
  - Use `used_rows/candidate_rows` and `used_strata/total_strata` as the go/no-go signal for controlled conclusions.

- Filter contract confirmed:
  - Quick filters default to `official_full_golden_only=true`, `exclude_ai_tests=false`.
  - Column filters payload supports grouped clauses with per-field `mode` plus top-level `column_filter_global_mode`.
  - `subset_filter_patch` returns dashboard-compatible `{compare_field, column_filter_mode:\"or\", clauses:[{operator:\"eq\",value:...}]}`.

- CLI ergonomics note:
  - `run` always returns a large payload (includes catalog/filter context), so use `jq` projections for terminal readability.
  - `agent` is the better fit for Codex/tool loops because responses are line-delimited JSON and malformed lines return structured errors without killing the process.
````

### 2026-03-03_23.40.00-compare-control-backend-engine-parity-implementation

Source:
- `docs/understandings/2026-03-03_23.40.00-compare-control-backend-engine-parity-implementation.md`

Summary:
- Backend Compare & Control engine implementation note: JS parity seams mirrored in Python and exposed via run/agent CLI surfaces.

Preserved source note:

````md
---
summary: "Backend Compare & Control engine implementation note: JS parity seams mirrored in Python and exposed via run/agent CLI surfaces."
read_when:
  - "When debugging differences between dashboard Compare & Control results and cookimport compare-control CLI output."
  - "When extending compare-control agent actions or filter payload shapes."
---

- Discovery: dashboard compare/control behavior depends on a combined seam (`previousRunsFieldValue` + quick filters + column filter operators + analysis functions), so backend parity required reproducing all of them together instead of porting only analysis math.
- Implementation: `cookimport/analytics/compare_control_engine.py` now centralizes derived field resolution, filter evaluation, discover/raw/controlled analysis, suggestions, and subset filter patch generation.
- CLI wiring: `cookimport compare-control run` and `cookimport compare-control agent` both dispatch through the same engine action router in `cookimport/cli.py`, with structured success/error envelopes.
- Test anchors: `tests/analytics/test_compare_control_engine.py` covers derived fields/filter errors/controlled-math contract; `tests/analytics/test_compare_control_cli.py` covers one-shot JSON + persistent JSONL agent behavior.
````

### 2026-03-03_23.48.14-compare-control-insights-action-implementation

Source:
- `docs/understandings/2026-03-03_23.48.14-compare-control-insights-action-implementation.md`

Summary:
- Compare-control insights action: auto-profile + actionable driver filtering + process-factor deltas.

Preserved source note:

````md
---
summary: "Compare-control insights action: auto-profile + actionable driver filtering + process-factor deltas."
read_when:
  - "When extending compare-control beyond manual discover/raw/controlled workflows."
  - "When interpreting why insights hides some discovery fields as high-cardinality noise."
---

- Problem observed during local runs: unfiltered `discover` often surfaced path/hash identifiers first (`processed_report_path`, config hashes), which is technically predictive but weak for operator decision-making.

- Implementation added: new backend action `insights` in `cookimport/analytics/compare_control_engine.py`, wired through both `cookimport compare-control run` and `cookimport compare-control agent`.

- `insights` output now includes:
  - row/profile snapshot (`candidate_rows`, top source/importer/model categories),
  - actionable vs noisy discovery split (noise identified by path/hash/report-style field naming),
  - automatic raw + controlled compare payloads (default compare preference starts at `ai_model`),
  - controlled coverage warnings reused from existing compare/control warning contract,
  - process-factor delta summaries across key run-config fields,
  - suggested next query payloads for iterative terminal/agent loops.

- Contract note: this feature stays deterministic and local-data only (no LLM/tooling beyond existing compare-control math/filter contracts).

- Practical usage:
  - one-shot: `cookimport compare-control run --action insights --outcome-field strict_accuracy`
  - persistent loop: send JSONL `{ "action": "insights", "payload": { ... } }` to `cookimport compare-control agent`.
````

### 2026-03-03_23.57.39-per-label-run-selector-seam

Source:
- `docs/understandings/2026-03-03_23.57.39-per-label-run-selector-seam.md`

Summary:
- Per-label diagnostics run selector seam map in dashboard_render.js template.

Preserved source note:

````md
---
summary: "Per-label diagnostics run selector seam map in dashboard_render.js template."
read_when:
  - "When changing which benchmark run timestamp Per-Label Breakdown renders."
  - "When debugging persisted Per-Label run selection in dashboard UI state."
---

# Per-label run selector seam

- `renderPerLabel()` already computes `candidateRecords` (non-speed preferred, all-method preferred), so run-picker options should derive from that exact set to keep table semantics unchanged.
- `benchmarkRunGroupInfo()` is the canonical grouping key/label source; reuse it for dropdown options so timestamp grouping matches boundary/trend behavior.
- UI persistence belongs in `previous_runs` dashboard state next to other per-label controls (`per_label_rolling_window_size`, `per_label_comparison_mode`), now with `per_label_run_group_key`.
- The `Default - most recent` option should resolve at render-time (not load-time), so it auto-follows new latest runs while explicit selections stay pinned.
````

### 2026-03-04_00.08.03-compare-control-discovery-preferences-cli-bridge

Source:
- `docs/understandings/2026-03-04_00.08.03-compare-control-discovery-preferences-cli-bridge.md`

Summary:
- Compare & Control discovery cards can now be tuned from backend/CLI via shared discovery-preferences state.

Preserved source note:

````md
---
summary: "Compare & Control discovery cards can now be tuned from backend/CLI via shared discovery-preferences state."
read_when:
  - "When discovery cards are dominated by path/hash/config identifier fields."
  - "When adding or debugging compare-control discovery ranking controls in CLI or dashboard."
---

- Discovery seam: dashboard `discover` cards and backend compare-control discovery both compute a heuristic score per field; adding one shared `discovery_preferences` shape keeps behavior aligned across browser and CLI.

- Implemented preference shape:
  - `exclude_fields` (hard remove),
  - `prefer_fields` (score boost),
  - `demote_patterns` (substring score demotion),
  - `max_cards` (result cap).

- Backend surfaces:
  - `cookimport compare-control run` accepts one-shot discovery tuning flags.
  - `cookimport compare-control discovery-preferences` persists defaults into `assets/dashboard_ui_state.json` so dashboard discover cards follow backend-set preferences.

- Practical outcome: operators/agents can suppress noisy IDs (for example `processed_report_path`, hash fields) and prioritize actionable drivers (`ai_model`, `ai_effort`) without editing frontend code.
````

Anti-loop reminders from this consolidation:
- If Compare/Control and table outputs diverge, debug shared filter/value seams first (`previousRunsFieldValue`, compiled column filters, quick-filter handoff).
- If someone suggests reintroducing isolate behavior, check the isolate-removal seam/audit notes first; this path was intentionally removed to reduce split-brain UX/state.
- If controlled categorical output looks counterintuitive, inspect strata coverage and weighting assumptions before changing formulas.


### 2026-03-04 understandings consolidation (trend field controls, run-group alignment, host stability)

Merged source notes:
- `docs/understandings/2026-03-04_00.14.17-per-label-missing-variant-zero-coercion.md`
- `docs/understandings/2026-03-04_00.17.57-benchmark-trend-run-group-token-selection.md`
- `docs/understandings/2026-03-04_00.21.08-compare-control-secondary-constant-zero.md`
- `docs/understandings/2026-03-04_00.38.37-codexfarm-pass3-token-trend-query.md`
- `docs/understandings/2026-03-04_00.41.49-previous-runs-two-section-two-chart-layout.md`
- `docs/understandings/2026-03-04_00.44.24-dashboard-trend-field-selection-contract.md`
- `docs/understandings/2026-03-04_00.48.32-history-root-repo-local-vs-external.md`
- `docs/understandings/2026-03-04_00.50.58-previous-runs-grid-min-content-width-leak.md`
- `docs/understandings/2026-03-04_00.58.21-benchmark-trend-host-rerender-cleanup.md`

Problem lineage preserved:
- Per-label comparison point-value mode could coerce missing variant values to zero because empty strings parsed as `0`.
- Trend run-group extraction fallback could select variant-local timestamps and split paired points horizontally.
- Compare/control secondary means could include constant all-zero timing fields, creating misleading `0.000` summaries.
- Previous Runs layout evolution required two chart hosts over one filtered row pool; single-host render path was insufficient.
- Trend chart rerenders could accumulate host markup if previous chart instances were not explicitly destroyed/cleared.
- History roots required a repo-local policy shift to keep `.history` trackable while preserving external-output behavior.

Durable decisions/outcomes:
- Missing comparison variant metrics now render as `-` (no zero coercion).
- Run-group timestamp extraction now prefers first timestamp token after `benchmark-vs-golden`; fallback order is `artifact_dir` -> `run_dir` -> `report_path` -> row timestamp.
- Compare/control secondary field selection now requires measurable variation (`max-min > 1e-12`).
- Trend rendering is host-aware (`renderBenchmarkTrendChartHost(config)`) and reused for both trend chart hosts.
- Trend series selection is now state-backed and arbitrary-field capable via `trend_fields` persistence.
- Trend host rendering now does scoped destroy/clear before redraw and fallback transitions.
- History root resolution now distinguishes repo-local outputs from external outputs and keeps compatibility reads for prior locations.

Operational query preserved:
- For codex pass-token investigations, sum `llmCodexFarm.process_runs.pass*.telemetry.rows[*].tokens_total` per pass from `*.excel_import_report.json` and compare by run timestamp.

Anti-loop reminders:
- For paired-series x-axis drift, inspect run-group extraction before series or Highcharts config changes.
- For chart growth/duplicate artifacts, inspect host cleanup lifecycle before CSS layout adjustments.
- For missing history rows after output-root changes, inspect `history_root_for_output` and fallback-read probes before collector rewrites.

### 2026-03-04 understandings consolidation (pixel overflow source and containment)

Merged source note:
- `docs/understandings/2026-03-04_01.06.35-previous-runs-pixel-overflow-source.md`

Problem captured:
- Previous Runs rightward growth reproduced as page-level horizontal overflow (`document.scrollWidth - clientWidth`), with long unwrapped compare/control token values as a primary contributor.

Durable decisions/outcomes:
- Keep overflow containment at section boundaries for Previous Runs containers.
- Keep compare/control output text wrapping aggressive enough to prevent long token spillover.
- Preserve local table scrollers for intentionally wide table content.

Anti-loop reminder:
- Use pixel overflow probes first when diagnosing rightward growth; do not assume chart rerendering is the sole source.

### 2026-03-04 docs/tasks consolidation (trend arbitrary fields + rightward-growth hardening)

Merged source task files:
- `docs/tasks/2026-03-04_00.44.24-dashboard-trend-arbitrary-fields.md`
- `docs/tasks/2026-03-04_00.50.57-previous-runs-rightward-growth-containment.md`
- `docs/tasks/2026-03-04_00.58.20-benchmark-trend-host-rerender-cleanup.md`
- `docs/tasks/2026-03-04_01.06.34-previous-runs-pixel-overflow-guard.md`

Problem lineage preserved:
- Trend charts were hardcoded to two metrics and could not be operator-configured.
- Previous Runs could grow rightward due to grid min-content pressure and later due to page-level overflow from long compare/control tokens.
- Trend host rerenders did not guarantee clean host state before redraw, allowing cumulative markup/width symptoms.

Durable decisions/outcomes:
- Added state-backed arbitrary trend-field selection controls and persisted `trend_fields` in dashboard UI state.
- Kept shared trend-series builder semantics across both chart hosts while preserving paired-variant and run-group contracts.
- Applied section/grid containment (`minmax(0, 1fr)`, `min-width: 0`, local overflow boundaries) rather than shrinking intentional table min-width contracts.
- Added host-scoped chart-instance cleanup in rerender path (destroy + clear before redraw/fallback).
- Added page-level overflow hardening for compare/control outputs (`overflow-wrap: anywhere`, `word-break: break-word`) and container overflow constraints.

Verification evidence preserved from tasks:
- Trend arbitrary fields task: `pytest tests/analytics/test_stats_dashboard.py` -> `69 passed in 8.62s`.
- Rightward-growth containment task:
  - targeted css test: `2 passed, 67 deselected in 0.85s`.
  - full file: `69 passed in 9.38s`.
- Host rerender cleanup task:
  - red before fix: `1 failed, 69 deselected` (`second_before_empty=False`).
  - green targeted: `1 passed, 69 deselected in 0.42s`.
  - green subset/full: `3 passed, 67 deselected in 1.06s`; `70 passed in 8.96s`.
- Pixel overflow guard task:
  - red before fix: `1 failed, 70 deselected` (`max_doc_overflow_px=2195`).
  - green targeted/subset/full: `1 passed, 70 deselected in 5.13s`; `3 passed, 68 deselected in 5.74s`; `71 passed in 14.14s`.

Anti-loop reminders:
- Keep red/green harnesses for rerender cleanliness and pixel overflow; these caught regressions invisible to static CSS checks.
- Do not “fix” rightward growth by removing table readability min-width; containment belongs in wrapper/grid policy.
- For two-host trend issues, debug host-id-scoped lifecycle and shared-series pipeline together.

### 2026-03-04_01.18.36 Previous Runs column-width state clamp

Source:
- `docs/understandings/2026-03-04_01.18.36-previous-runs-column-width-state-clamp.md`

Problem captured:
- Persisted Previous Runs column widths can carry oversized values across sessions and cause recurring layout growth even after content-level overflow fixes.

Durable outcomes:
- Column-width normalization clamps persisted values to `72..1200px`.
- Clamp is applied consistently at sanitize/load, drag-resize updates, and state persistence boundaries.

Anti-loop note:
- If Previous Runs keeps widening across sessions, inspect persisted-width clamp paths before changing table/container CSS.

### 2026-03-04_01.45.33 trend host width drift vs page overflow

Source:
- `docs/understandings/2026-03-04_01.45.33-trend-host-width-drift-vs-page-overflow.md`

Problem captured:
- Page-level overflow checks can remain stable while trend hosts still accumulate internal horizontal overflow over rerenders.

Durable outcomes:
- Added host-level drift checks (`host.scrollWidth - host.clientWidth`) sampled over time.
- Pinned trend chart width to measured host width each render to stop rerender-time width creep.

Anti-loop note:
- A passing page-overflow probe does not clear trend-host drift; verify host-level metrics before closing drift incidents.

### 2026-03-04 docs/tasks merge ledger (pixel overflow + host drift)

Merged source task files (timestamp order):
- `docs/tasks/2026-03-04_01.20.21-previous-runs-real-pixel-overflow-guard.md`
- `docs/tasks/2026-03-04_01.45.22-trend-host-width-drift-guard.md`

#### 2026-03-04_01.20.21 Previous Runs real pixel overflow guard

Problem captured:
- Previous Runs kept growing rightward under live rerenders; prior checks missed real overflow states.

Durable outcomes:
- Added browser-level pixel harness measuring document and section overflow over repeated rerenders.
- Hardened runtime containment via long-token wrapping and persisted-column-width normalization (`72..1200px`).

Verification evidence retained:
- Red before fix: `max_doc_overflow_px=2195`.
- Green targeted: `4 passed, 68 deselected`.
- Green full dashboard: `72 passed`.

#### 2026-03-04_01.45.22 trend-host width drift guard

Problem captured:
- Trend hosts could widen internally over time while page-level overflow checks stayed flat.

Durable outcomes:
- Added timed host-drift Playwright harness (5 samples, 5s interval).
- Pinned Highcharts width to measured host width per rerender.
- Kept rerender forcing deterministic in harness via UI-state churn and chart stubbing.

Verification evidence retained:
- Red before fix: host overflow drift up to `1396/1516px`.
- Green targeted/new slow: passing drift guard.
- Combined dashboard suites remained green after fix.

Anti-loop reminders:
- If rightward growth returns, run host-level drift + document-level overflow probes together.
- Treat wrapper containment and explicit host-width pinning as the primary guardrails, not table-width shrinkage.

## 2026-03-04 docs/tasks consolidation batch (runtime-card token aggregation + quality efficiency + trend tooltips)

### 2026-03-04_08.27.09 runtime-card run-group token totals

Source task:
- `docs/tasks/2026-03-04_08.27.09 - runtime-card-run-group-token-totals.md`

Problem captured:
- Latest runtime token usage came from one row and under-reported multi-book benchmark runs.

Durable outcomes:
- Runtime summary token use now sums across latest preferred benchmark run-group.
- Runtime context/model/effort selection stays representative but prefers richer rows in that run-group.

Evidence retained from task:
- `source .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py -k "runtime_summary_aggregates_tokens_across_latest_run_group or test_js_renders_previous_runs_table_and_links_timestamp_to_artifact"`

### 2026-03-04_08.46.21 dashboard quality-per-token metric

Source task:
- `docs/tasks/2026-03-04_08.46.21 - dashboard-quality-per-token-metric.md`

Problem captured:
- Dashboard exposed token totals but not quality gained per token, making efficiency tradeoffs hard to evaluate.

Durable outcomes:
- Added runtime card quality-efficiency rows for latest run-group.
- Added `quality_per_million_tokens` derived numeric field in Previous Runs.
- Added variant comparison context (including delta-vs-vanilla framing when paired variants exist).

Evidence retained from task:
- `source .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py -k "test_js_renders_previous_runs_table_and_links_timestamp_to_artifact or test_js_supports_previous_runs_column_header_filters or test_runtime_summary_aggregates_tokens_across_latest_run_group or test_previous_runs_quality_per_million_tokens_calculation"`
- `source .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py`

### 2026-03-04_08.49.13 benchmark trend tooltip point details

Source task:
- `docs/tasks/2026-03-04_08.49.13 - benchmark-trend-tooltip-point-details.md`

Problem captured:
- Trend hover cards emphasized run-group aggregates and did not clearly identify hovered dot source/score context.

Durable outcomes:
- Trend point `custom` payload now carries source/variant/timestamp metadata.
- Tooltip formatter shows hovered-point specifics first.
- Temporary run-group context remained available at this stage.

Evidence retained from task:
- `source .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py -k points_include_source_metadata_for_tooltips`
- `source .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py`

### 2026-03-04_09.02.37 benchmark trend tooltip book-only follow-up

Source task:
- `docs/tasks/2026-03-04_09.02.37 - benchmark-trend-tooltip-book-only.md`

Problem captured:
- After point metadata landed, tooltip still included run-group summary rows, which conflicted with requested per-point/book-only behavior.

Durable outcomes:
- Removed run-group summary block from tooltip renderer.
- Tooltip now keeps only hovered-point score, source/book context, variant, and eval-row timestamp.

Evidence retained from task:
- `source .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py -k benchmark_trend_chart_uses_fixed_height`
- `source .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py`

Anti-loop reminders:
- If tooltip cards look aggregated again, check tooltip formatter block before changing trend grouping logic.
- Point-only tooltip behavior depends on point `custom` metadata population; verify renderer payloads first.

## 2026-03-04 docs/understandings consolidation batch (history supplement + runtime/quality-token + tooltip point metadata)

### 2026-03-04_08.19.19 dashboard migration benchmark-history gap

Source note:
- `docs/understandings/2026-03-04_08.19.19-dashboard-migration-benchmark-history-gap.md`

Problem captured:
- CSV-first benchmark collection can appear to “chop” historical trend data when canonical CSV starts later than existing eval-report artifacts.

Durable outcomes:
- Keep CSV authoritative.
- Auto-supplement only rows older than earliest benchmark CSV from eval reports.
- Reserve full recursive benchmark JSON merge for explicit `--scan-benchmark-reports` runs.

### 2026-03-04_08.27.09 runtime-card latest run-group token sum

Source note:
- `docs/understandings/2026-03-04_08.27.09-runtime-card-latest-run-group-token-sum.md`

Problem captured:
- Runtime card token display under-reported multi-book runs by reading one latest row.

Durable outcomes:
- Runtime card now aggregates discounted token totals across `latestRunGroupRecords`.
- Runtime context row selection prefers richer metadata rows inside that run-group.

### 2026-03-04_08.46.21 quality-token metric runtime and table

Source note:
- `docs/understandings/2026-03-04_08.46.21-quality-token-metric-runtime-and-table.md`

Problem captured:
- Quality-efficiency values could drift if runtime and table paths used different token math/quality keys.

Durable outcomes:
- Unified discounted token formula for runtime + Previous Runs.
- Preserved deterministic quality key fallback chain.
- Preserved latest-run-group delta-vs-vanilla efficiency calculation contract.
- Preserved peer run-group rank semantics using same metric key.

### 2026-03-04_08.49.13 trend tooltip point metadata

Source note:
- `docs/understandings/2026-03-04_08.49.13-trend-tooltip-point-metadata.md`

Problem captured:
- Trend hover cards looked aggregated when point payload lacked per-dot source metadata.

Durable outcomes:
- Trend series points now carry per-point source/title/variant/timestamp metadata in `custom` payload.
- Tooltip formatter consumes hovered point metadata first, enabling per-book point context.

Anti-loop reminders:
- If trends look chopped after migration, validate CSV earliest timestamp and supplement path before enabling full scan-by-default.
- If runtime/token or quality-per-token numbers disagree across cards/tables, debug shared `all_token_use` and quality-key selection first.
- If tooltip context regresses to run-group-only, inspect trend point `custom` payload population before chart config changes.
