---
summary: "Current analytics reference: artifact contracts, command behavior, caveats, and maintenance checklist."
read_when:
  - When changing performance reporting, CSV history writes, or stats-dashboard behavior
  - When debugging missing or inconsistent analytics artifacts under data/output or data/golden
  - When updating current analytics behavior; read `08-analytics_log.md` for prior attempts/history
---

# 08 Analytics README

Current, code-verified analytics contract for this repo.

This README documents active behavior only. Historical notes that still matter for active code paths live in `docs/08-analytics/08-analytics_log.md`.

## 1) What analytics currently includes

1. Per-file conversion reports
- Artifact: `<run_dir>/<file_slug>.excel_import_report.json`
- Producers: stage file handlers plus split/merge flows
- Schema anchor: `cookimport/core/models.py` (`ConversionReport`)

2. Cross-run history CSV
- Artifact: `performance_history.csv`
- Default repo-local location: `.history/performance_history.csv`
- Written by stage/perf-report appenders, benchmark appenders, and `benchmark-csv-backfill`

3. Static dashboard site
- Default root: `.history/dashboard`
- Main page: `index.html`
- Supporting assets:
  - `assets/dashboard_data.json`
  - `assets/dashboard_ui_state.json`
  - `assets/dashboard.js`
  - `assets/style.css`
- Standalone all-method pages:
  - `all-method-benchmark/all-method-benchmark-run__<run_ts>.html`
  - `all-method-benchmark/all-method-benchmark__<run_ts>__<source_slug>.html`
- There is no standalone `all-method-benchmark/index.html` page

4. Compare/control backend utilities
- Terminal/agent entry points share the same benchmark-record model used by the dashboard
- Live dashboard state helpers can read/write `assets/dashboard_ui_state.json`

## 2) Code map

Primary modules:
- `cookimport/analytics/perf_report.py`
- `cookimport/analytics/dashboard_collect.py`
- `cookimport/analytics/dashboard_schema.py`
- `cookimport/analytics/dashboard_render.py`
- `cookimport/analytics/compare_control_engine.py`
- `cookimport/analytics/benchmark_timing.py`
- `cookimport/paths.py`
- `cookimport/cli.py`

Primary CLI entry points:
- `cookimport stage`
- `cookimport perf-report`
- `cookimport benchmark-csv-backfill`
- `cookimport stats-dashboard`
- `cookimport compare-control run`
- `cookimport compare-control agent`
- `cookimport compare-control dashboard-state`
- `cookimport compare-control discovery-preferences`
- `cookimport labelstudio-eval`
- `cookimport labelstudio-benchmark`

Regression anchors:
- `tests/analytics/test_perf_report.py`
- `tests/analytics/test_stats_dashboard.py`
- `tests/analytics/test_benchmark_csv_backfill_cli.py`
- `tests/analytics/test_compare_control_engine.py`
- `tests/analytics/test_compare_control_cli.py`
- `tests/labelstudio/test_labelstudio_benchmark_helpers_import_eval.py`
- `tests/labelstudio/test_labelstudio_benchmark_helpers_single_offline_run.py`
- `tests/bench/test_bench.py`

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

History-root rule:
- Resolve the canonical path from the output root with `history_csv_for_output(output_root)`.
- Repo-local outputs such as `data/output` write to `<repo>/.history/performance_history.csv`.
- External output roots write to `<output_root parent>/.history/performance_history.csv`.
- Collector also scans nested `<output_root>/**/.history/performance_history.csv` files for supplemental benchmark rows from nested benchmark layouts.

Stage/import rows (`run_category=stage_import` or `labelstudio_import`) keep:
- Timing fields: `total_seconds`, `parsing_seconds`, `writing_seconds`, `ocr_seconds`
- Count fields: `recipes`, `tips`, `tip_candidates`, `topic_candidates`, `total_units`
- Derived fields such as `per_recipe_seconds`, `per_unit_seconds`, knowledge share, and dominant-stage/checkpoint values
- Run-config context: `run_config_hash`, `run_config_summary`, `run_config_json`

Benchmark rows (`run_category=benchmark_eval` or `benchmark_prediction`) keep:
- Explicit benchmark metrics: `strict_accuracy`, `macro_f1_excluding_other`
- Legacy compatibility metrics when explicit metrics are absent: `precision`, `recall`, `f1`, `practical_*`
- Count and boundary fields: `gold_total`, `gold_matched`, `pred_total`, `boundary_*`
- Recipe context: `recipes`, `gold_recipe_headers`
- Per-label durability field: `per_label_json`
- Token usage fields: `tokens_input`, `tokens_cached_input`, `tokens_output`, `tokens_reasoning`, `tokens_total`
- Benchmark timing fields: `benchmark_prediction_seconds`, `benchmark_evaluation_seconds`, `benchmark_artifact_write_seconds`, `benchmark_history_append_seconds`, `benchmark_total_seconds`
- Run-config context: `run_config_hash`, `run_config_summary`, `run_config_json`

Compatibility behavior:
- Appenders expand older CSV headers before writing.
- CSV appends use file locking.
- CSV history is durable; `bench gc` does not rewrite or prune `performance_history.csv`.

### 3.3 Dashboard artifacts and collector behavior

Schema contract:
- `cookimport/analytics/dashboard_schema.py`
- `SCHEMA_VERSION = "13"`

Collector behavior (`collect_dashboard_data`):
- Stage data is CSV-first.
- `--scan-reports` supplements stage rows from `*.excel_import_report.json`.
- If no usable history CSV exists, stage data can fall back to report-only scanning.
- Benchmark data is CSV-first.
- Nested benchmark history CSVs under the output root are merged in as supplemental rows.
- `eval_report.json` scanning is opt-in via `--scan-benchmark-reports`, with automatic fallback only when benchmark CSV rows are unavailable.
- When CSV rows exist, older benchmark artifacts can still supplement missing historical rows, but CSV stays authoritative for overlapping artifact directories.
- Manifest enrichment backfills importer/runtime context, codex model/effort, recipe counts, and token usage when available.
- Benchmark artifact paths classified as test/gate noise are excluded before rendering.
- Timestamp sorting is parse-aware and tolerates both `YYYY-MM-DD_HH.MM.SS` folder-style timestamps and ISO timestamps.

## 4) Command behavior

### `cookimport stage`

- Writes timestamped run folders using `YYYY-MM-DD_HH.MM.SS`.
- Appends stage rows to the resolved history CSV.
- Triggers best-effort dashboard refresh after the history write.

### `cookimport perf-report`

- Summarizes one run, either explicit `--run-dir` or latest under `--out-dir`.
- `--write-csv` is on by default and appends to history CSV plus best-effort dashboard refresh.

### `cookimport benchmark-csv-backfill`

- Repairs older benchmark CSV rows that are missing key fields such as `recipes`, `report_path`, or `file_name`.
- Backfills benchmark runtime metadata from nearby manifests.
- Backfills missing token fields from nearby prediction manifests when telemetry exists.
- `--dry-run` reports potential edits without writing.
- Real writes trigger dashboard refresh for the matching history root.

### `cookimport stats-dashboard`

- Builds a static dashboard from collected analytics data.
- Supports `--since-days`, `--scan-reports`, and `--scan-benchmark-reports`.
- Supports `--open`.
- Supports `--serve` with `--host` and `--port`.
- In `--serve` mode, browser state can sync through `assets/dashboard_ui_state.json`, and newer program-side state is applied live while the page stays open.
- Prints collector warnings when malformed or partial inputs are detected.

### Compare/control CLI surfaces

`cookimport compare-control run` and `cookimport compare-control agent`:
- Use the same benchmark-record model and field catalog as dashboard compare/control analysis.
- Support `discover`, `raw`, `controlled`, field catalog, subset-patch, and insights-style workflows.

`cookimport compare-control dashboard-state`:
- Reads or updates the live Compare & Control state stored in `assets/dashboard_ui_state.json`.
- Can target Set 1 or Set 2, plus dual-set layout options.

`cookimport compare-control discovery-preferences`:
- Reads or updates discover-card ranking preferences stored in `assets/dashboard_ui_state.json`.

Benchmark history appenders:
- `cookimport labelstudio-eval` appends benchmark rows and refreshes the dashboard.
- `cookimport labelstudio-benchmark` appends benchmark rows and refreshes the dashboard.
- Interactive single-offline and all-method benchmark flows batch refreshes so they do not rewrite the dashboard after every sub-run.

## 5) Dashboard surface (current)

### 5.1 Main page scope

The main dashboard page is intentionally narrow:
- `Diagnostics (Latest Benchmark)`
- `Previous Runs`

It does not render a separate `All-Method Benchmark Runs` section.

### 5.2 Diagnostics

Latest-benchmark diagnostics are selected from the preferred benchmark run group:
- all-method rows are preferred over other benchmark families when relevant
- non-speed rows are preferred over speed rows
- grouping uses artifact-path timestamp tokens when present, then falls back to record timestamps

Current diagnostics cards:
- `Benchmark Runtime`
- `Boundary Classification`
- `Per-Label Breakdown`

Key behaviors:
- Runtime surfaces model, effort, pipeline mode, token use, and token-efficiency metrics when metadata exists.
- Boundary aggregates all boundary-bearing rows in the selected run group and shows matched-coverage context.
- Per-label aggregates across the selected run group, keeps latest-run `codexfarm` baseline columns, supports point-value vs delta display, and exposes a `Rolling N` selector plus run-group selector.

### 5.3 Previous Runs

`Previous Runs` is the benchmark-history workspace:
- benchmark trend chart
- quick filters
- configurable history table
- `Compare & Control Analysis`

Current table/trend behavior:
- Table columns can be shown/hidden, reordered, and resized.
- Column filters support stacked clauses, per-column `AND/OR`, and a global `Across columns` `AND/OR` mode.
- View presets persist table/filter/sort/compare-control state.
- Trend points are plotted as discrete scatter points with dashed rolling trend overlays.
- Trend timestamps render in browser-local time.
- Trend range selector defaults to `All`.
- Highcharts mouse-wheel zoom is disabled.

Current row semantics:
- `AI Model`, `AI Effort`, and derived `AI Profile` are first-class fields.
- `AI Model` can render `System error` when manifest enrichment detects codex runtime failure metadata.
- `All token use` and `Quality / 1M tokens` are default columns.
- Missing token telemetry stays unknown (`-`) instead of becoming numeric zero.
- All-method benchmark sweeps collapse to one row whose timestamp links to the generated run-summary page.

State behavior:
- Browser state persists in `localStorage`.
- In `--serve` mode, the same state can sync through `assets/dashboard_ui_state.json`.
- On served dashboards, program-side UI state is authoritative on initial load.

### 5.4 Compare & Control Analysis

Current compare/control contract:
- Separate subsection under `Previous Runs`
- Modes: `discover`, `raw`, `controlled`
- Dynamic chart routing by compare-field type
- Optional split-by segmentation
- Optional `Set 2` with `stacked`, `side_by_side`, or `combined` chart layouts
- Local selected-group subsets stay inside compare/control and do not mutate the table filters

Important scope rule:
- Compare/control analyzes benchmark history independently from the `Previous Runs` table filters.

### 5.5 All-method pages

Renderer output:
- `all-method-benchmark/all-method-benchmark-run__<run_timestamp>.html`
- `all-method-benchmark/all-method-benchmark__<run_timestamp>__<source_slug>.html`

Grouping contract:
- `all-method-benchmark/<source_slug>/config_*`
- `single-profile-benchmark/<source_slug>`

Current page behavior:
- No standalone all-method root index page
- Run-summary pages link to per-book detail pages
- Run and detail pages include summary tables, metric charts, radar/web charts, and ranked tables
- Score metrics use fixed `0..100%` axes
- Recipes are shown as percent identified against `gold_recipe_headers`

## 6) Known caveats

1. History root is above the output root.
- Do not assume `<out>/.history/...`; canonical history is `<out parent>/.history/...`.

2. Dashboard refresh inference is path-sensitive.
- Automatic refresh expects the canonical history CSV path shape.
- Non-canonical custom history paths may skip refresh.

3. Static/offline is still the default.
- Opening `index.html` directly works.
- Cross-browser live state sync requires `cookimport stats-dashboard --serve`.

4. Dashboard JS is emitted from Python string templates.
- Escaping mistakes in `dashboard_render.py` can break the generated page.

5. Compare/control and table filters are intentionally different scopes.
- If they disagree, check whether you are looking at table filters versus compare/control-local analysis before changing collector logic.

## 7) Debugging checklist

1. Confirm the expected report files or benchmark artifacts actually exist.
2. Confirm the history CSV path resolved from your chosen output root.
3. Rebuild with explicit roots when in doubt:
- `cookimport stats-dashboard --output-root <out_root> --golden-root <gold_root>`
4. If stage rows look incomplete, rerun with `--scan-reports`.
5. If benchmark rows or runtime metadata look incomplete, rerun with `--scan-benchmark-reports` and inspect nearby `manifest.json` / `prediction-run/manifest.json`.
6. If the main page scope looks wrong, verify against `tests/analytics/test_stats_dashboard.py` before restoring older dashboard sections.

## 8) If you change analytics, update together

1. `cookimport/core/models.py`
2. `cookimport/analytics/perf_report.py`
3. `cookimport/analytics/dashboard_schema.py`
4. `cookimport/analytics/dashboard_collect.py`
5. `cookimport/analytics/dashboard_render.py`
6. `cookimport/analytics/compare_control_engine.py`
7. `cookimport/paths.py`
8. Refresh wiring in `cookimport/cli.py`
9. Analytics tests under `tests/analytics/` plus related CLI/benchmark tests
10. This README plus `08-analytics_log.md` and `dashboard_readme.md` when dashboard behavior changes
