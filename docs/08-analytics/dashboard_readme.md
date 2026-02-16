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

`data/output/.history/performance_history.csv`

This CSV is populated by:

- `cookimport stage` (auto-appends stage/import rows at the end of a run)
- `cookimport perf-report` when `--write-csv` is enabled (default)
- benchmark/eval commands that append benchmark rows:
  - `labelstudio-eval`
  - `labelstudio-benchmark`
  - `bench run`

### Stage-report fallback/supplement

`data/output/<YYYY-MM-DD_HH.MM.SS>/*.excel_import_report.json`

Used when the CSV is missing, and also used as a supplement when `--scan-reports` is passed.

### Benchmark JSON source

- `data/golden/eval-vs-pipeline/*/eval_report.json`
- `data/golden/*/eval_report.json`

Optional enrichment files in each eval directory:

- `coverage.json`
- `manifest.json`
- `prediction-run/coverage.json`
- `prediction-run/manifest.json`

Manifest enrichment now includes benchmark run context used by the dashboard:
- `importer_name`
- `run_config` (for example `epub_extractor`, `ocr_device`, worker knobs)
- `processed_report_path` when processed outputs were written during benchmark

## Where dashboard stats are saved

Default `--out-dir` is `data/output/.history/dashboard`.

The renderer writes:

- `data/output/.history/dashboard/index.html`
- `data/output/.history/dashboard/assets/dashboard_data.json`
- `data/output/.history/dashboard/assets/dashboard.js`
- `data/output/.history/dashboard/assets/style.css`

Notes:

- `index.html` embeds an inline copy of `dashboard_data.json`, so it still works via `file://` even when browser local fetches are restricted.
- Collectors are read-only. They do not modify the source metrics in `data/output` or `data/golden`.
- Benchmark rows pointing at pytest temp eval paths (for example `.../pytest-46/test_foo0/eval`) are ignored so local `pytest` runs do not appear in `Recent Benchmarks`.

## Import speed organization in the dashboard

The throughput section is intentionally split into two complementary views:

- Run/date view:
  - `Run / Date Trend (sec/recipe)` chart across all visible stage/import rows.
  - `Recent Runs (Date / Run View)` table sorted by newest run timestamp.
  - Includes `Importer` and `Run Config` columns for stage/import rows.
- File view:
  - `File Trend (Selected File)` selector + chart + table.
  - File-trend rows include `Importer` and `Run Config` summary columns.
  - Grouping key is `stage_records[*].file_name`, so you can track how one file's processing speed changes across runs.

Timestamp ordering note:
- Recent-run and benchmark tables sort by parsed time (not raw string compare), so mixed timestamp formats like `YYYY-MM-DDTHH:MM:SS` and `YYYY-MM-DD_HH.MM.SS` still appear in true chronological order.
- Frontend timestamp parsing should use explicit component parsing for these two forms (with `Date` fallback for timezone-bearing ISO values) rather than relying only on `Date.parse`.

## Regenerate

`cookimport stats-dashboard`

Useful options:

- `--output-root <path>`: source root for staged output metrics
- `--golden-root <path>`: source root for benchmark metrics
- `--out-dir <path>`: where dashboard files are written
- `--since-days N`: include only recent runs
- `--scan-reports`: force scan of `*.excel_import_report.json` in addition to CSV

## Known gotcha

In current code, `cookimport stage --out <custom>` still appends history rows to `data/output/.history/performance_history.csv` (default root). If you build a dashboard with a non-default `--output-root`, CSV-backed stage history may look incomplete unless those paths are aligned.
