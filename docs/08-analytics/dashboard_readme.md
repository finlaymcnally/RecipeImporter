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
- `data/golden/benchmark-vs-golden/*/all-method-benchmark/*/config_*/eval_report.json`
- `data/golden/*/eval_report.json`

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
- `data/.history/dashboard/all-method-benchmark/index.html` (always generated run index)
- `data/.history/dashboard/all-method-benchmark/all-method-benchmark-run__<run_timestamp>.html` (one run summary page per all-method sweep, when present)
- `data/.history/dashboard/all-method-benchmark/all-method-benchmark__<run_timestamp>__<source_slug>.html` (per-book config breakdown pages, when present)

Notes:

- `index.html` embeds an inline copy of `dashboard_data.json`, so it still works via `file://` even when browser local fetches are restricted.
- Collectors are read-only. They do not modify the source metrics in `data/output` or `data/golden`.
- Benchmark rows pointing at pytest temp eval paths (for example `.../pytest-46/test_foo0/eval`) are ignored so local `pytest` runs do not appear in `Previous Runs`.
- All-method standalone pages are built from benchmark CSV rows (`run_dir` / `artifact_dir`) grouped by benchmark sweep paths:
  - `all-method-benchmark/<source_slug>/config_*`
  - `single-profile-benchmark/<source_slug>`
  (CSV-first; no extra dashboard-only metric store). The hierarchy is run index -> run summary -> per-book detail, and all pages are written under `data/.history/dashboard/all-method-benchmark/`. The run index page is always written, even when there are zero runs.
- Before writing all-method pages, renderer removes stale legacy root pages (`all-method-benchmark.html`, old top-level detail pages) so only the subfolder hierarchy remains.

## Index layout

`index.html` is intentionally minimal:

- `All-Method Benchmark Runs`: links to a standalone all-method run index page.
- `Diagnostics (Latest Benchmark)`: per-label + boundary breakdown for the most recent benchmark record that contains that data.
  - When both speed-suite benchmark rows (`.../bench/speed/runs/...`) and regular benchmark rows exist, diagnostics prefer the latest non-speed rows to avoid one-target speed samples overriding multi-book benchmark diagnostics.
  - Speed/non-speed and all-method detection normalizes `artifact_dir` path separators first, so Windows-style `\\` paths in history data are handled the same as `/`.
- `Previous Runs`: scrollable table (about ~5 visible rows) with key benchmark columns only.
  - Normal benchmark rows: timestamp links to `artifact_dir`.
  - All-method benchmark sweeps: collapsed to one row; `Source` shows `all-method benchmark run`, and the timestamp links to the generated run-summary HTML page under `all-method-benchmark/`.

Timestamp ordering note:
- The `Previous Runs` table sorts by parsed time (not raw string compare), so mixed timestamp formats like `YYYY-MM-DDTHH:MM:SS` and `YYYY-MM-DD_HH.MM.SS` still appear in true chronological order.
- Frontend timestamp parsing should use explicit component parsing for these two forms (with `Date` fallback for timezone-bearing ISO values) rather than relying only on `Date.parse`.
- Benchmark collector normalizes suffixed sweep folder names like `2026-02-28_02.03.18_manual-top5-...` to `2026-02-28_02.03.18` for dashboard run-grouping.

Benchmark recipes note:
- `Previous Runs` includes a `Recipes` column.
- Benchmark recipe counts are persisted in CSV `recipes` for benchmark entrypoints (`labelstudio-benchmark`, `labelstudio-eval`) whenever recipe context is available.
- Collector prefers manifest `recipe_count`, then falls back to `processed_report_path` -> report `totalRecipes` when needed.
- For historical rows created before CSV persistence was complete, run `cookimport benchmark-csv-backfill` once to patch missing values.

Benchmark metrics note:
- `Previous Runs` shows strict precision/recall plus both `Practical F1` and `Strict F1`.
- `Strict F1` is the IoU-threshold localization metric (`precision/recall/f1` fields from eval).
- `Practical F1` is the any-overlap content metric (`practical_*` eval fields).
- Main dashboard includes an `All-Method Benchmark Runs` section linking to a run index page.
- All-method run index rows link to run-summary pages that aggregate config metrics across all book jobs in the sweep (including single-profile all-matched sweeps).
- All-method pages prefer reading `all_method_benchmark_report.json` (when present) so the dashboard can list all configured variants even when evaluation results were reused and not every `config_*/eval_report.json` exists.
- Run-summary pages now include a compact stats table plus per-metric bar charts (one bar per aggregated configuration), per-config radar/web charts, and per-cookbook average bar/radar sections before the aggregate table/drilldown links.
  - Score metrics on those charts (`Strict Precision`, `Strict Recall`, `Strict F1`, `Practical F1`) are fixed to a 0-100% scale (`1.0 == 100%`).
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

## Known gotcha

`cookimport stats-dashboard` reads stage/import history primarily from `<output_root parent>/.history/performance_history.csv`.

If you stage into a non-default output root (for example `cookimport stage --out /tmp/out`), build the dashboard with the matching root (for example `cookimport stats-dashboard --output-root /tmp/out`) so the collector reads the same history CSV and report folders you just produced.
