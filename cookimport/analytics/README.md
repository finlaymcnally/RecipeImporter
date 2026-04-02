Performance reporting utilities live here.
Durable analytics caveats/contracts live in `cookimport/analytics/CONVENTIONS.md`.

- Reads per-run conversion reports and prints one-line, per-file timing summaries.
- Appends run history to canonical history root (`history_csv_for_output(...)`; default `.history/performance_history.csv` for repo-local outputs) for easy trending.
- Invoked by `cookimport perf-report` and auto-runs after `cookimport stage`.
- Includes `cookimport benchmark-csv-backfill` to patch older benchmark rows from manifest/report artifacts.
- CSV-writing CLI flows now also auto-refresh dashboard artifacts under the same `.history/dashboard` root (best effort).
- Includes standalone topic coverage (`totalStandaloneBlocks`, `totalStandaloneTopicBlocks`, `standaloneTopicCoverage`) when available.
- Benchmark rows now include stage-block metric columns (`benchmark_overall_accuracy`, `benchmark_macro_f1_excluding_other`, `benchmark_worst_label`, `benchmark_worst_label_recall`).

Outliers are flagged across multiple metrics (total, parsing, writing, per-unit) and
per-recipe only when the run is recipe-heavy (to avoid knowledge-heavy false positives).

## Stats Dashboard

`cookimport stats-dashboard` generates a static HTML dashboard summarizing lifetime
import/stage throughput and golden-set benchmark trends.

Modules:
- `dashboard_schema.py` – Pydantic v2 models (`DashboardData`, `StageRecord`, `BenchmarkRecord`)
- `dashboard_collect.py` – Read-only collectors for CSV history + eval_report.json
- `dashboard_render.py` – Thin public facade exposing `render_dashboard(...)`
- `compare_control_engine.py` – Thin public compare/control facade
- `compare_control_fields.py` – Derived benchmark field values plus compare/control field catalog ownership
- `compare_control_filters.py` – Quick-filter and column-filter normalization/evaluation
- `compare_control_analysis.py` – Compare/control statistics, discovery cards, and insights ownership
- `dashboard_renderers/` – Asset writing, shared formatting, all-method page generation, and static templates

Dashboard UX rule:
- Any new metric shown in the dashboard should come with a plain-English description (tooltips and/or an on-page help/glossary). See `cookimport/analytics/CONVENTIONS.md`.

Data sources (read-only):
- `.history/performance_history.csv` (primary for repo-local stage records)
- `data/output/<timestamp>/*.excel_import_report.json` (fallback with `--scan-reports`)
- `data/golden/benchmark-vs-golden/*/eval_report.json` (benchmarks)
- benchmark enrichment from `manifest.json` / `coverage.json` at eval root or `prediction-run/`
  (includes source/importer/run-config context when available)

Output: `.history/dashboard/` for repo-local outputs (configurable via `--out-dir`)
- Main `index.html` diagnostics now includes a latest benchmark runtime card (model/thinking/pipeline when available).
- Main `index.html` diagnostics runtime `Token use` now uses compact `k`/`m` display for large token values and sums discounted token totals across the latest benchmark run group (not a single book row).
- Main `index.html` diagnostics runtime now also includes quality-efficiency rows (`Quality / 1M tokens`, vanilla delta efficiency, and peer rank).
- Main `index.html` `Previous Runs` now includes `AI Model + Effort` and source-slug fallbacks when `source_file` is missing.
- Main `index.html` `Previous Runs` `All token use` cell now uses compact `k`/`m` display for large token values.
- Main `index.html` `Previous Runs` includes derived `Quality / 1M tokens` for token-efficiency sorting/filtering across runs.
- Main `index.html` trend hover cards now show point-level context only (dot score + book/source label + variant + eval-row timestamp), without run-group/overall series summaries.
- Main `index.html` rolling trend overlays now shrink their edge windows near the start/end of a series so tail segments reflect the latest runs instead of flattening from a repeated final full-window slice.
- Benchmark CSV appends now write `importer_name`; dashboard importer display also has source-path/run-config fallback for historical blank rows.
- Codex model/effort is backfilled from benchmark manifest `llm_codex_farm` runtime payloads when run-config omits those fields.
- Benchmark runtime model/effort now falls back to prediction-run manifest `llm_codex_farm` telemetry when run-config values are unset/default.
- For grouped all-method runs, writes run-level summary pages under `all-method-benchmark/`:
  - `.history/dashboard/all-method-benchmark/all-method-benchmark-run__<run_timestamp>.html` (repo-local default)
- Per-book detail pages live in the same all-method subfolder:
  - `.history/dashboard/all-method-benchmark/all-method-benchmark__<run_timestamp>__<source_slug>.html` (repo-local default)
- No standalone `all-method-benchmark/index.html` page is generated; entry is via main-page `Previous Runs` timestamp links.
- Grouping key remains benchmark artifact paths matching `all-method-benchmark/<source_slug>/config_*`; run-level pages aggregate those per-book groups by run folder.
- Run-summary pages include config-level charts plus per-cookbook average bar/radar sections (averaged across all configs per source) before config and per-book tables.

Throughput dashboard organization:
- run/date view (`Run / Date Trend`, `Recent Runs`) for timeline-level comparisons
- stage/import tables include importer + run-config summary from stage report `runConfig` when available
- collector fallback fills stage run-config from `report_path` JSON when CSV `run_config_json` is missing
- stale stage rows with missing report references are flagged in Run Config as `[warn] missing report (stale row)`
- file view (`File Trend`) grouped by `stage_records[*].file_name` to track one file across runs
