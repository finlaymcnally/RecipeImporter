Performance reporting utilities live here.

- Reads per-run conversion reports and prints one-line, per-file timing summaries.
- Appends run history to `data/output/.history/performance_history.csv` for easy trending.
- Invoked by `cookimport perf-report` and auto-runs after `cookimport stage`.
- Includes `cookimport benchmark-csv-backfill` to patch older benchmark rows from manifest/report artifacts.
- Includes standalone topic coverage (`totalStandaloneBlocks`, `totalStandaloneTopicBlocks`, `standaloneTopicCoverage`) when available.

Outliers are flagged across multiple metrics (total, parsing, writing, per-unit) and
per-recipe only when the run is recipe-heavy (to avoid knowledge-heavy false positives).

## Stats Dashboard

`cookimport stats-dashboard` generates a static HTML dashboard summarizing lifetime
import/stage throughput and golden-set benchmark trends.

Modules:
- `dashboard_schema.py` – Pydantic v2 models (`DashboardData`, `StageRecord`, `BenchmarkRecord`)
- `dashboard_collect.py` – Read-only collectors for CSV history + eval_report.json
- `dashboard_render.py` – Writes `index.html` + local JS/CSS/JSON assets

Data sources (read-only):
- `data/output/.history/performance_history.csv` (primary for stage records)
- `data/output/<timestamp>/*.excel_import_report.json` (fallback with `--scan-reports`)
- `data/golden/eval-vs-pipeline/*/eval_report.json` (benchmarks)
- benchmark enrichment from `manifest.json` / `coverage.json` at eval root or `prediction-run/`
  (includes source/importer/run-config context when available)

Output: `data/output/.history/dashboard/` (configurable via `--out-dir`)

Throughput dashboard organization:
- run/date view (`Run / Date Trend`, `Recent Runs`) for timeline-level comparisons
- stage/import tables include importer + run-config summary from stage report `runConfig` when available
- collector fallback fills stage run-config from `report_path` JSON when CSV `run_config_json` is missing
- stale stage rows with missing report references are flagged in Run Config as `[warn] missing report (stale row)`
- file view (`File Trend`) grouped by `stage_records[*].file_name` to track one file across runs
