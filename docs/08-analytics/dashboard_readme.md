---
summary: "How the stats dashboard is built, what data it reads, and what files it writes."
read_when:
  - When you need to know how data/.history/dashboard/index.html is generated
  - When debugging missing stats in the dashboard
---

# Dashboard README

## What this generates

`cookimport stats-dashboard` builds a static dashboard rooted at `data/.history/dashboard/`.
Main entry point: `data/.history/dashboard/index.html`.

## How it works (collect -> render)

1. The CLI command in `cookimport/cli.py` calls `collect_dashboard_data(...)`.
2. The collector (`cookimport/analytics/dashboard_collect.py`) scans metrics from disk.
3. The renderer (`cookimport/analytics/dashboard_render.py`) writes HTML/CSS/JS and JSON assets.

## Where dashboard stats come from

### Primary source (stage + benchmark rows from CSV)

`<output_root parent>/.history/performance_history.csv` (default `<output_root>` is `data/output`)

Collector compatibility fallback:
- If canonical history CSV is missing, collector also probes legacy `<output_root>/.history/performance_history.csv`.
- Benchmark rows can also be supplemented from nested benchmark history CSV files under `<output_root>/**/.history/performance_history.csv` (used by nested benchmark processed-output layouts).

This CSV is populated by:

- `cookimport stage` (auto-appends stage/import rows at the end of a run)
- `cookimport perf-report` when `--write-csv` is enabled (default)
- benchmark/eval commands that append benchmark rows:
  - `labelstudio-eval`
  - `labelstudio-benchmark`
- optional one-off repair command for older benchmark rows:
  - `benchmark-csv-backfill` (patches missing benchmark `recipes/report_path/file_name` from manifests)
- After successful CSV writes, these commands now auto-refresh dashboard artifacts under the same history root (`.history/dashboard`) in best-effort mode.
- All-method benchmark internals suppress per-config refreshes and refresh once per source batch to avoid concurrent dashboard rewrites.

### Stage-report fallback/supplement

`<output_root>/<YYYY-MM-DD_HH.MM.SS>/*.excel_import_report.json`

Used when the CSV is missing, and also used as a supplement when `--scan-reports` is passed.

### Benchmark JSON source

- `data/golden/benchmark-vs-golden/*/eval_report.json`
- `data/golden/benchmark-vs-golden/*/single-offline-benchmark/*/eval_report.json`
- `data/golden/benchmark-vs-golden/*/single-offline-benchmark/*/*/eval_report.json`
- `data/golden/benchmark-vs-golden/*/all-method-benchmark/*/config_*/eval_report.json`
- `data/golden/*/eval_report.json`

Collector mode:
- benchmark rows are CSV-first by default
- recursive benchmark JSON scan is opt-in via `--scan-benchmark-reports` (automatic fallback when no benchmark CSV rows are available)
- benchmark history rows remain dashboard-visible after `bench gc --apply` because GC now refuses to prune run roots without confirmed durable CSV metrics

Optional enrichment files in each eval directory:

- `coverage.json`
- `manifest.json`
- `prediction-run/coverage.json`
- `prediction-run/manifest.json`

Manifest enrichment now includes benchmark run context used by the dashboard:
- `importer_name`
- `run_config` (for example `epub_extractor`, `ocr_device`, worker knobs)
- `run_config_hash`
- `run_config_summary`
- `recipe_count` (extracted recipes in prediction run)
- `processed_report_path` when processed outputs were written during benchmark
  - benchmark `recipes` prefers `recipe_count`; collector backfills from `processed_report_path` (`totalRecipes`) when needed, then falls back to eval `recipe_counts.predicted_recipe_count`

## Where dashboard stats are saved

Default `--out-dir` is `data/.history/dashboard`.

The renderer writes:

- `data/.history/dashboard/index.html`
- `data/.history/dashboard/assets/dashboard_data.json`
- `data/.history/dashboard/assets/dashboard.js`
- `data/.history/dashboard/assets/style.css`
- `data/.history/dashboard/all-method-benchmark/all-method-benchmark-run__<run_timestamp>.html` (one run summary page per all-method sweep, when present)
- `data/.history/dashboard/all-method-benchmark/all-method-benchmark__<run_timestamp>__<source_slug>.html` (per-book config breakdown pages, when present)

Notes:

- `index.html` embeds an inline copy of `dashboard_data.json`, so it still works via `file://` even when browser local fetches are restricted.
- Collectors are read-only. They do not modify the source metrics in `data/output` or `data/golden`.
- Benchmark rows pointing at pytest temp eval paths (for example `.../pytest-46/test_foo0/eval`) are ignored so local `pytest` runs do not appear in `Previous Runs`.
- All-method standalone pages are built from benchmark CSV rows (`run_dir` / `artifact_dir`) grouped by benchmark sweep paths:
  - `all-method-benchmark/<source_slug>/config_*`
  - `single-profile-benchmark/<source_slug>`
  (CSV-first; no extra dashboard-only metric store). The hierarchy is run summary -> per-book detail, and all pages are written under `data/.history/dashboard/all-method-benchmark/`.
- `single-offline-benchmark/{vanilla,codexfarm}` eval directories are collected and shown in the regular benchmark tables/metrics (not grouped into all-method standalone pages).
- Before writing all-method pages, renderer removes stale legacy root pages (`all-method-benchmark.html`, old top-level detail pages) so only the subfolder hierarchy remains.

## Index layout

`index.html` is intentionally minimal:

- `Diagnostics (Latest Benchmark)`: runtime + per-label + boundary breakdown for the most recent benchmark record.
  - Runtime card surfaces best-effort AI context from benchmark run-config metadata (`model`, `thinking effort`, pipeline mode), preferring latest non-speed rows when both speed/non-speed exist.
  - When multiple latest rows share one timestamp (for example single-offline `codexfarm` + `vanilla`), diagnostics prefers the row with richer AI metadata (model/effort/pipeline-on) instead of defaulting to `off`.
  - If benchmark run-config is missing codex model/effort, collector backfills from benchmark manifest `llm_codex_farm.process_runs.*.process_payload` (and telemetry reasoning breakdown fallback) so codex rows do not show false `off` labels.
  - When run-config omits explicit model/effort (for example defaults), collector backfills from prediction-run manifest `llm_codex_farm` runtime payload when available.
  - When both speed-suite benchmark rows (`.../bench/speed/runs/...`) and regular benchmark rows exist, diagnostics prefer the latest non-speed rows to avoid one-target speed samples overriding multi-book benchmark diagnostics.
  - Speed/non-speed and all-method detection normalizes `artifact_dir` path separators first, so Windows-style `\\` paths in history data are handled the same as `/`.
  - Canonical-text benchmark reports now include `boundary` counts again, so boundary diagnostics can advance with current single-offline/all-method benchmark rows instead of falling back to older freeform-eval rows.
- `Previous Runs`: full-history table with key benchmark columns only.
  - Horizontal scrolling is enabled; table keeps a minimum width so wide benchmark columns stay readable instead of over-compressing.
  - Click any table header to toggle sort direction for that column (`A→Z` / `Z→A`), including timestamps.
  - Includes table column controls: drag headers to reorder, resize via header drag handles, and add/remove fields dynamically from discovered benchmark keys.
  - Normal benchmark rows: timestamp links to `artifact_dir`.
  - `AI Model + Effort` column uses run-config metadata (`run_config` / `run_config_summary`) with fallback aliases.
  - `Source` prefers `source_file` basename, then artifact-path source slug fallback (`all-method-benchmark`, `single-profile-benchmark`, `scenario_runs`, `eval/<slug>` patterns).
  - `Importer` uses CSV/importer metadata first, then source-path/run-config fallback (for older benchmark rows with blank CSV importer).
  - All-method benchmark sweeps collapse to one row with summarized `Source` text (`all-method: <top source> + N more`), and timestamp links to generated run-summary HTML under `all-method-benchmark/`.
  - Includes a rules filter builder: define row rules over any benchmark field (including nested keys like `run_config.*`) and combine them with a boolean expression (`AND` / `OR` / `NOT`, parentheses) using rule IDs (`R1`, `R2`, ...).
  - Rule field dropdown is grouped into `Most used (table columns)` first, then `All other fields`.
  - The `Benchmark Score Trend` Highcharts panel uses a fixed 400px chart/container height to avoid browser reflow loops that can cause gradual chart height growth.
  - Benchmark trend timestamps are rendered in the browser's local timezone (`useUTC: false`) so chart hover time aligns with local run expectations.
  - Score series are plotted as discrete scatter points (no continuous interpolation line between run timestamps).
  - When filtered rows include paired benchmark variants (`codexfarm`/`vanilla`), trend points split into separate series per metric+variant so paired runs are visually distinct.
  - Hovering any trend point shows one run-level tooltip card with local run timestamp and all visible series values for that run group (instead of per-point coordinate tooltips).
  - The `Benchmark Score Trend` range selector defaults to `All`, so older benchmark history is visible on first load instead of starting on a short recent window.
  - The trend chart x-axis is initialized from the full filtered `Previous Runs` timestamp span (including rows without explicit score points), so timeline dates stay aligned with the table.
  - Highcharts mouse-wheel zoom is disabled globally in dashboard JS (`HIGHCHARTS_MOUSE_WHEEL_ZOOM_ENABLED = false`) so page scrolling does not zoom charts by accident; toggle that constant to re-enable later.

Timestamp ordering note:
- The `Previous Runs` table sorts by parsed time (not raw string compare), so mixed timestamp formats like `YYYY-MM-DDTHH:MM:SS` and `YYYY-MM-DD_HH.MM.SS` still appear in true chronological order.
- Frontend timestamp parsing should use explicit component parsing for these two forms (with `Date` fallback for timezone-bearing ISO values) rather than relying only on `Date.parse`.
- Benchmark collector normalizes suffixed sweep folder names like `2026-02-28_02.03.18_manual-top5-...` to `2026-02-28_02.03.18` for dashboard run-grouping.
- For grouped all-method rows, frontend timestamp extraction now scans backward in `artifact_dir` for the nearest timestamp token, so paths containing segments like `.../repeat_01/eval_output/all-method-benchmark/...` do not show `eval_output` as the timestamp label.
- Grouped all-method timestamp extraction accepts timestamp tokens with suffixes (for example `2026-02-28_00.42.13_manual-all-matched-global-smoke`) and falls back to benchmark `run_timestamp` when no path token is found.

Benchmark recipes note:
- `Previous Runs` includes a `Recipes` column.
- Benchmark recipe counts are persisted in CSV `recipes` for benchmark entrypoints (`labelstudio-benchmark`, `labelstudio-eval`) whenever recipe context is available.
- Collector prefers manifest `recipe_count`, then falls back to `processed_report_path` -> report `totalRecipes` when needed.
- For historical rows created before CSV persistence was complete, run `cookimport benchmark-csv-backfill` once to patch missing values.

Benchmark metrics note:
- `Previous Runs` and benchmark trend chart use explicit metric names: `strict_accuracy` and `macro_f1_excluding_other`.
- Dashboard collector populates explicit metrics from new eval-report keys directly and falls back to legacy alias fields for historical artifacts.
- Main dashboard does not include an all-method run-index section; all-method access is through `Previous Runs` timestamp links to run-summary pages.
- All-method pages prefer reading `all_method_benchmark_report.json` (when present) so the dashboard can list all configured variants even when evaluation results were reused and not every `config_*/eval_report.json` exists.
- Run-summary pages now include a compact stats table plus per-metric bar charts (one bar per aggregated configuration), per-config radar/web charts, and per-cookbook average bar/radar sections before the aggregate table/drilldown links.
  - Score metrics on those charts are fixed to a 0-100% scale (`1.0 == 100%`).
  - `Recipes` now charts `% identified` against golden recipe headers for each book (from eval `recipe_counts.gold_recipe_headers`) on the same fixed 0-100% scale.
- Run-summary pages link to per-book detail pages for existing single-source config drilldown.
- All-method run-summary/detail pages include a sticky quick-nav (Summary / Charts / Ranked Table / Drilldown) and use native collapsible section groups (`details`) to shorten default scan length without hiding metrics.
- All-method detail pages now start with a compact `Run Summary` table (stats-only, no per-config labels), metric-category bar charts (one bar per run/config), and per-config radar/web charts before the full ranked table.
- Ranked all-method tables now include explicit dimension columns (`Extractor`, `Parser`, `Skip HF`, `Preprocess`) so config differences are readable without decoding slug strings.

## Historical decisions worth preserving

Timeline notes merged from former `docs/understandings` files:

- `2026-02-15_23.17.17`: local `file://` dashboard failures were fixed by embedding inline JSON in `index.html`; keep inline-first + fetch-fallback behavior.
- `2026-02-16_10.56.36`: benchmark `Gold`/`Matched` are span-eval metrics; `Recipes` is separate and should not be interpreted as score denominator.
- `2026-02-16_11.33.17`: benchmark `recipes` must be persisted across benchmark CSV append paths (`labelstudio-benchmark`, `labelstudio-eval`) to avoid blank `Recipes` rows.
- `2026-02-25`: main dashboard index was trimmed to focus on all-method links, latest-benchmark diagnostics, and a scrollable benchmark history table (no throughput/speed views).

## Regenerate

`cookimport stats-dashboard`

Useful options:

- `--output-root <path>`: source root for staged output metrics
- `--golden-root <path>`: source root for benchmark metrics
- `--out-dir <path>`: where dashboard files are written
- `--open`: open generated dashboard in browser
- `--since-days N`: include only recent runs
- `--scan-reports`: force scan of `*.excel_import_report.json` in addition to CSV
- `--scan-benchmark-reports`: force recursive benchmark `eval_report.json` scan and merge with CSV rows

## Known gotcha

`cookimport stats-dashboard` reads stage/import history primarily from `<output_root parent>/.history/performance_history.csv`.

If you stage into a non-default output root (for example `cookimport stage --out /tmp/out`), build the dashboard with the matching root (for example `cookimport stats-dashboard --output-root /tmp/out`) so the collector reads the same history CSV and report folders you just produced.
