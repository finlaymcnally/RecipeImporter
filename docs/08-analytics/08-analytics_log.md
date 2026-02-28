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
