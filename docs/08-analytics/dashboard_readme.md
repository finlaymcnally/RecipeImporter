---
summary: "How the stats dashboard is built, what data it reads, and what files it writes."
read_when:
  - When you need to know how data/output/.history/dashboard/index.html is generated
  - When debugging missing stats in the dashboard
---

# Dashboard README

## What this generates

`cookimport stats-dashboard` builds a static dashboard rooted at `data/output/.history/dashboard/`.
Main entry point: `data/output/.history/dashboard/index.html`.

## How it works (collect -> render)

1. The CLI command in `cookimport/cli.py` calls `collect_dashboard_data(...)`.
2. The collector (`cookimport/analytics/dashboard_collect.py`) scans metrics from disk.
3. The renderer (`cookimport/analytics/dashboard_render.py`) writes HTML/CSS/JS and JSON assets.

## Where dashboard stats come from

### Primary source (stage + benchmark rows from CSV)

`<output_root>/.history/performance_history.csv` (default `<output_root>` is `data/output`)

This CSV is populated by:

- `cookimport stage` (auto-appends stage/import rows at the end of a run)
- `cookimport perf-report` when `--write-csv` is enabled (default)
- benchmark/eval commands that append benchmark rows:
  - `labelstudio-eval`
  - `labelstudio-benchmark`
  - `bench run`
- optional one-off repair command for older benchmark rows:
  - `benchmark-csv-backfill` (patches missing benchmark `recipes/report_path/file_name` from manifests)

### Stage-report fallback/supplement

`<output_root>/<YYYY-MM-DD_HH.MM.SS>/*.excel_import_report.json`

Used when the CSV is missing, and also used as a supplement when `--scan-reports` is passed.

### Benchmark JSON source

- `data/golden/eval-vs-pipeline/*/eval_report.json`
- `data/golden/eval-vs-pipeline/*/all-method-benchmark/*/config_*/eval_report.json`
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
  - benchmark `recipes` prefers `recipe_count`; collector backfills from `processed_report_path` (`totalRecipes`) when needed

## Where dashboard stats are saved

Default `--out-dir` is `data/output/.history/dashboard`.

The renderer writes:

- `data/output/.history/dashboard/index.html`
- `data/output/.history/dashboard/assets/dashboard_data.json`
- `data/output/.history/dashboard/assets/dashboard.js`
- `data/output/.history/dashboard/assets/style.css`
- `data/output/.history/dashboard/all-method-benchmark.html` (always generated)
- `data/output/.history/dashboard/all-method-benchmark__<run_timestamp>__<source_slug>.html` (one per all-method benchmark run, when present)

Notes:

- `index.html` embeds an inline copy of `dashboard_data.json`, so it still works via `file://` even when browser local fetches are restricted.
- Collectors are read-only. They do not modify the source metrics in `data/output` or `data/golden`.
- Benchmark rows pointing at pytest temp eval paths (for example `.../pytest-46/test_foo0/eval`) are ignored so local `pytest` runs do not appear in `Recent Benchmarks`.
- All-method standalone pages are built from benchmark CSV rows (`run_dir` / `artifact_dir`) grouped by paths containing `all-method-benchmark/<source_slug>/config_*` (CSV-first; no extra dashboard-only metric store). The dashboard root page for this view is always written, even when there are zero runs.

## Import speed organization in the dashboard

The throughput section is intentionally split into two complementary views:

- Run/date view:
  - `Run / Date Trend (sec/recipe)` chart across all visible stage/import rows.
  - `Recent Runs (Date / Run View)` table sorted by newest run timestamp.
  - Includes explicit EPUB visibility columns: `EPUB Req`, `EPUB Eff`, and `Auto Score`.
  - Includes `Importer` and `Run Config` columns for stage/import rows.
- File view:
  - `File Trend (Selected File)` selector + chart + table.
  - File-trend rows include `Importer`, `EPUB Req`, `EPUB Eff`, `Auto Score`, and `Run Config` summary columns.
  - Grouping key is `stage_records[*].file_name`, so you can track how one file's processing speed changes across runs.
  - Filters include category/date plus a dedicated `EPUB Extractor` checkbox group keyed by effective/requested extractor values.

Timestamp ordering note:
- Recent-run and benchmark tables sort by parsed time (not raw string compare), so mixed timestamp formats like `YYYY-MM-DDTHH:MM:SS` and `YYYY-MM-DD_HH.MM.SS` still appear in true chronological order.
- Frontend timestamp parsing should use explicit component parsing for these two forms (with `Date` fallback for timezone-bearing ISO values) rather than relying only on `Date.parse`.

Run config note:
- Stage/import `Run Config` values primarily come from CSV `run_config_summary` and `run_config_hash` (with `run_config_json` kept for full details/tooltips).
- If `run_config_json` is empty on older history rows, the collector attempts to backfill from each row's `report_path` (`runConfig` in `*.excel_import_report.json`) when available.
- If neither CSV nor report data is available and a report path reference exists, dashboard tables show `[warn] missing report (stale row)`.
- Dashboard run-config cells show the summary and append a short hash suffix (`[abcdef1234]`) when `run_config_hash` is available; tooltip includes full hash and JSON/details.

Benchmark recipes note:
- `Recent Benchmarks` includes a `Recipes` column.
- Benchmark recipe counts are persisted in CSV `recipes` for benchmark entrypoints (`labelstudio-benchmark`, `labelstudio-eval`, `bench run`) whenever recipe context is available.
- Collector prefers manifest `recipe_count`, then falls back to `processed_report_path` -> report `totalRecipes` when needed.
- For historical rows created before CSV persistence was complete, run `cookimport benchmark-csv-backfill` once to patch missing values.

Benchmark metrics note:
- `Recent Benchmarks` shows both `Practical F1` and `Strict F1`.
- `Strict F1` is the IoU-threshold localization metric (`precision/recall/f1` fields from eval).
- `Practical F1` is the any-overlap content metric (`practical_*` eval fields).
- Rows with likely granularity mismatch display a small `mismatch` tag beside strict score so low strict/high practical runs are interpreted correctly.
- Main dashboard now includes an `All-Method Benchmark Runs` section linking to standalone pages with ranked per-config stats for each sweep.
- All-method detail pages now start with a compact `Run Summary` table (stats-only, no per-config labels) and metric-category bar charts (one bar per run/config) before the full ranked table.
- Ranked all-method tables now include explicit dimension columns (`Extractor`, `Parser`, `Skip HF`, `Preprocess`) so config differences are readable without decoding slug strings.

## Historical decisions worth preserving

Timeline notes merged from former `docs/understandings` files:

- `2026-02-15_23.17.17`: local `file://` dashboard failures were fixed by embedding inline JSON in `index.html`; keep inline-first + fetch-fallback behavior.
- `2026-02-15_23.51.02` -> `2026-02-16_00.25.07`: throughput UI intentionally keeps both run/date trend and single selected-file trend; full per-file list/cards were tried (`00.12.54`) and rejected as too heavy.
- `2026-02-16_10.37.22` -> `2026-02-16_10.51.07`: stage run-config display must stay CSV-first, report-path fallback second, with explicit stale-row warning text when report references are missing.
- `2026-02-16_10.56.36`: benchmark `Gold`/`Matched` are span-eval metrics; `Recipes` is separate and should not be interpreted as score denominator.
- `2026-02-16_11.33.17`: benchmark `recipes` must be persisted across all benchmark CSV append paths (`labelstudio-benchmark`, `labelstudio-eval`, `bench run`) to avoid blank `Recipes` rows.
- `2026-02-23_12.29.05`: keep JS template escaping explicit for `\\n` in run-config tooltip assembly (`runConfigCell`) so generated `dashboard.js` stays parseable when opened directly in browsers.

## Regenerate

`cookimport stats-dashboard`

Useful options:

- `--output-root <path>`: source root for staged output metrics
- `--golden-root <path>`: source root for benchmark metrics
- `--out-dir <path>`: where dashboard files are written
- `--since-days N`: include only recent runs
- `--scan-reports`: force scan of `*.excel_import_report.json` in addition to CSV

## Known gotcha

`cookimport stats-dashboard` reads stage/import history primarily from `<output_root>/.history/performance_history.csv`.

If you stage into a non-default output root (for example `cookimport stage --out /tmp/out`), build the dashboard with the matching root (for example `cookimport stats-dashboard --output-root /tmp/out`) so the collector reads the same history CSV and report folders you just produced.
