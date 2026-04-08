---
summary: "Current analytics reference: artifact contracts, command behavior, caveats, and maintenance checklist."
read_when:
  - When changing performance reporting, CSV history writes, or stats-dashboard behavior
  - When debugging missing or inconsistent analytics artifacts under data/output or data/golden
  - When updating current analytics behavior
---

# 08 Analytics README

Current, code-verified analytics contract for this repo.

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
- There is no standalone `all-method-benchmark/` page family anymore; all-method sweep summaries stay inside `index.html`

4. Compare/control backend utilities
- Terminal/agent entry points share the same benchmark-record model used by the dashboard
- Live dashboard state helpers can read/write `assets/dashboard_ui_state.json`
- Runtime ownership is split cleanly: `compare_control_engine.py` is the import-stable facade, `compare_control_fields.py` owns derived field normalization/catalog work, `compare_control_filters.py` owns filter normalization/evaluation, and `compare_control_analysis.py` owns statistics/discovery/insights.

## 2) Code map

Primary modules:
- `cookimport/analytics/perf_report.py`
- `cookimport/analytics/dashboard_collect.py`
- `cookimport/analytics/benchmark_manifest_runtime.py`
- `cookimport/analytics/dashboard_schema.py`
- `cookimport/analytics/dashboard_render.py` (public renderer entrypoint; writes `index.html` plus shared assets directly)
- `cookimport/analytics/dashboard_renderers/` (asset/page/template ownership)
  - `html_shell.py` owns the static page shell
  - `style_asset.py` owns the emitted dashboard CSS
  - `script_bootstrap.py` and `script_compare_control.py` own the Python-side JS fragments
  - `dashboard_renderers/assets/script_filters.js` and `dashboard_renderers/assets/script_tables.js` are the source-of-truth checked-in JS files loaded directly by `dashboard_render.py`
- `cookimport/analytics/compare_control_engine.py` (public facade)
- `cookimport/analytics/compare_control_fields.py` (derived field values and compare/control field catalog ownership)
- `cookimport/analytics/compare_control_filters.py` (quick-filter and column-filter normalization/evaluation)
- `cookimport/analytics/compare_control_analysis.py` (raw/controlled stats, discovery ranking, split summaries, and insights ownership)
- `cookimport/analytics/benchmark_timing.py`
- `cookimport/cli_commands/analytics.py`
- `cookimport/cli_commands/compare_control.py`
- `cookimport/cli_support/dashboard.py`
- `cookimport/paths.py`

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
- `tests/analytics/test_stats_dashboard_slow.py`
- `tests/analytics/test_dashboard_state_server.py`
- `tests/analytics/test_benchmark_csv_backfill_cli.py`
- `tests/analytics/test_compare_control_engine.py`
- `tests/analytics/test_compare_control_cli.py`
- `tests/labelstudio/test_labelstudio_benchmark_helpers_import_eval.py`
- `tests/labelstudio/test_labelstudio_benchmark_helpers_single_book_run.py`
- `tests/bench/test_bench.py`

## 3) Artifact contracts

### 3.1 Per-file report JSON

Analytics-critical fields:
- Identity: `runTimestamp`, `sourceFile`, `importerName`
- Counts: `totalRecipes`, `totalStandaloneBlocks`
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
- Tests and local fixture builders that mean "the primary history CSV for this output root" must write to that canonical parent `.history` location, not `output/.history`; nested benchmark `.history` files remain valid supplemental inputs only.

Stage/import rows (`run_category=stage_import` or `labelstudio_import`) keep:
- Timing fields: `total_seconds`, `parsing_seconds`, `writing_seconds`, `ocr_seconds`
- Count fields: `recipes`, `standalone_blocks`, `total_units`
- Derived fields such as `per_recipe_seconds`, `per_unit_seconds`, and dominant-stage/checkpoint values
- Run-config context: `run_config_hash`, `run_config_summary`, `run_config_json`

Benchmark rows (`run_category=benchmark_eval` or `benchmark_prediction`) keep:
- Explicit benchmark metrics: `strict_accuracy`, `macro_f1_excluding_other`
- Additional reporting metrics used by current dashboard and compare/control flows: `precision`, `recall`, `f1`, `practical_*`
- Count and boundary fields: `gold_total`, `gold_matched`, `pred_total`, `boundary_*`
- Recipe context: `recipes`, `gold_recipe_headers`
- Per-label durability field: `per_label_json`
- Token usage fields: `tokens_input`, `tokens_cached_input`, `tokens_output`, `tokens_reasoning`, `tokens_total`
  - benchmark token backfill/enrichment now treats those as whole-run actuals when the manifest carries recipe, knowledge, and line-role telemetry rather than only one `process_runs` slice
  - line-role totals may need recovery from nested telemetry summaries when the top-level benchmark copy only carries lightweight phase metadata; `prompt_budget_summary.json` is the preferred whole-run artifact when present
  - when a Codex taskfile stage has partial or missing usage for some worker runs, `prompt_budget_summary.json` now marks token usage as `complete`, `partial`, or `unavailable` and leaves the affected token totals blank instead of reporting a misleading literal spend
  - canonical line-role telemetry and manifest backfill now use the same fail-closed rule: when line-role usage is incomplete, token totals stay blank instead of silently reporting `0`
  - prompt-budget stage rollups should trust explicit stage telemetry when it is populated, but an empty top-level telemetry surface with zeroed summary must recover from nested worker summaries instead of falsely reporting zero spend
  - those prompt-budget summaries should also carry the status context needed to explain the blank totals: how many worker calls had usable usage and how many were missing it
  - knowledge prompt-budget rollups now also preserve packet terminal reasons from `knowledge_stage_summary.json`: `no_final_output_reason_code_counts` is the explicit failure breakdown, and `no_final_output_shard_count` is the coarse derived topline when analytics wants one “no final output” number
  - prompt-budget and stage-summary artifacts now also preserve direct-exec guardrail context from the live runtime: `worker_session_guardrails` for planned-versus-actual happy-path sessions plus repair/follow-up counts, and `task_file_guardrails` for deterministic `task.json` size pressure on the actual worker-visible file
- Benchmark timing fields: `benchmark_prediction_seconds`, `benchmark_evaluation_seconds`, `benchmark_artifact_write_seconds`, `benchmark_history_append_seconds`, `benchmark_total_seconds`
- Run-config context: `run_config_hash`, `run_config_summary`, `run_config_json`
- Benchmark variant/profile semantics are current-only: dashboard and compare/control should use explicit benchmark/profile metadata or current pipeline-derived fields, not artifact-path names such as `vanilla/` or `codex-exec/`.

Important boundary:
- `precision`, `recall`, and `practical_f1` are still part of the live dashboard/compare-control product surface. Analytics cleanup should target fallback readers, old layout tolerance, and stale wording before it attempts any metric rename.

Current write behavior:
- CSV appends use file locking.
- CSV history is durable; `bench gc` does not rewrite or prune `performance_history.csv`.

### 3.3 Dashboard artifacts and collector behavior

Schema contract:
- `cookimport/analytics/dashboard_schema.py`
- `SCHEMA_VERSION = "14"`

Collector behavior (`collect_dashboard_data`):
- Stage data is CSV-first.
- `--scan-reports` supplements stage rows from `*.excel_import_report.json`.
- If no usable history CSV exists, stage data can fall back to report-only scanning.
- Benchmark data is CSV-first.
- Nested benchmark history CSVs under the output root are merged in as supplemental rows.
- `eval_report.json` scanning is opt-in via `--scan-benchmark-reports`, with automatic fallback only when benchmark CSV rows are unavailable.
- When CSV benchmark rows exist, they are authoritative. JSON benchmark scans happen only when `--scan-benchmark-reports` is explicitly requested or when no benchmark CSV rows exist.
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
- `run_timestamp` is treated as a time axis for compare/control numeric charts, so timestamp-vs-metric views plot one point per run instead of averaging timestamp buckets.
- Timestamp compare/control charts stay as datetime scatter plots; they do not connect runs with a continuous line.

Dashboard Compare & Control:
- Uses the active `Previous Runs` quick filters and column filters as its source subset before running compare/control analysis, so saved dashboard state can reopen one-book or otherwise filtered charts directly.
- When `Compare by = run_timestamp`, the chart can switch between `Date` (datetime scatter) and `Per run` (equal-spaced chronological run order) from the toggle below the chart; the selected mode persists in dashboard UI state.

`cookimport compare-control dashboard-state`:
- Reads or updates the live Compare & Control state stored in `assets/dashboard_ui_state.json`.
- Can target Set 1 or Set 2, plus dual-set layout options.

`cookimport compare-control discovery-preferences`:
- Reads or updates discover-card ranking preferences stored in `assets/dashboard_ui_state.json`.

Benchmark history appenders:
- `cookimport labelstudio-eval` appends benchmark rows and refreshes the dashboard.
- `cookimport labelstudio-benchmark` appends benchmark rows and refreshes the dashboard.
- Interactive single-book and all-method benchmark flows batch refreshes so they do not rewrite the dashboard after every sub-run.
- Dashboard refresh helpers now require an explicit `golden_root` from the caller; CLI edges own repo-default root resolution instead of lower-level benchmark helpers guessing it.
- Repo pytest runs now fail fast when a test reaches real dashboard refresh without explicit opt-in. Use `@pytest.mark.heavy_side_effects` plus `allow_heavy_test_side_effects` for the rare tests that intentionally exercise the real refresh path.

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
- Per-label aggregates across the selected run group, keeps latest-run `codex-exec` baseline columns, supports point-value vs delta display, and exposes a `Rolling N` selector plus run-group selector.

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
- `all_token_use` is an effective-token cost proxy, not a literal raw total; dashboard displays should keep cached input explicit so the discounted total is readable beside raw input/output counts.
- `AI Model` can render `System error` when manifest enrichment detects codex runtime failure metadata.
- `Effective token use` and `Quality / 1M tokens` are default columns.
- Missing token telemetry stays unknown (`-`) instead of becoming numeric zero.
- All-method benchmark sweeps collapse to one row whose timestamp jumps to the in-page `All-Method Sweeps` summary.

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

### 5.5 All-method sweeps

Grouping contract:
- `all-method-benchmark/<source_slug>/config_*`
- `single-profile-benchmark/<source_slug>`

Current page behavior:
- No standalone all-method HTML pages are generated
- `Previous Runs` keeps one collapsed row per all-method sweep run
- `All-Method Sweeps` on the main page shows a compact recent-sweeps summary table with the source set, best config, row counts, and topline metrics

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

6. Dashboard token cells are not the same thing as whole-run actual cost.
- `Effective token use` is a cached-discounted per-row dashboard proxy.
- raw CSV `tokens_total` is still just that one benchmark row's total.
- finished-run `prompt_budget_summary.json` is the multi-stage actual-cost artifact when recipe, knowledge, and line-role all contributed spend.
- prompt preview artifacts are forward-looking estimates, not retrospective billing truth.

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
8. `cookimport/cli_commands/analytics.py`
9. `cookimport/cli_commands/compare_control.py`
10. Refresh wiring in `cookimport/cli_support/dashboard.py`
11. Analytics tests under `tests/analytics/` plus related CLI/benchmark tests
12. This README plus the short notes under `cookimport/analytics/` when dashboard behavior changes
