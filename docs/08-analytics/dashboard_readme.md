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
  - `benchmark-csv-backfill` (patches missing benchmark `recipes/report_path/file_name`, run-config runtime metadata, and `tokens_*` usage columns from manifests)
- After successful CSV writes, these commands now auto-refresh dashboard artifacts under the same history root (`.history/dashboard`) in best-effort mode.
- All-method benchmark internals suppress per-config refreshes and refresh once per source batch to avoid concurrent dashboard rewrites; deferred all-method refreshes now target `history_root_for_output(output_root)/dashboard` (usually `data/.history/dashboard`) instead of nested run-local dashboard snapshots.
- Interactive single-offline benchmark suppresses per-variant refreshes and refreshes once after the full variant batch completes, targeting the lifetime dashboard path (`history_root_for_output(output_root)/dashboard`, usually `data/.history/dashboard`).

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
- benchmark CSV writes now persist Codex token usage columns (`tokens_input`, `tokens_cached_input`, `tokens_output`, `tokens_reasoning`, `tokens_total`) when available from prediction manifests
- CSV benchmark rows also backfill missing codex model/effort from adjacent benchmark manifests (`manifest.json` / `prediction-run/manifest.json`) so `AI Model` / `AI Effort` columns stay populated without full report scanning
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
- Codex token totals from `llm_codex_farm.process_runs.*.process_payload.telemetry` (`tokens_*`)
- `processed_report_path` when processed outputs were written during benchmark
  - benchmark `recipes` prefers `recipe_count`; collector backfills from `processed_report_path` (`totalRecipes`) when needed, then falls back to eval `recipe_counts.predicted_recipe_count`

## Where dashboard stats are saved

Default `--out-dir` is `data/.history/dashboard`.

The renderer writes:

- `data/.history/dashboard/index.html`
- `data/.history/dashboard/assets/dashboard_data.json`
- `data/.history/dashboard/assets/dashboard_ui_state.json` (program-side Previous Runs UI state when served)
- `data/.history/dashboard/assets/dashboard.js`
- `data/.history/dashboard/assets/style.css`
- `data/.history/dashboard/all-method-benchmark/all-method-benchmark-run__<run_timestamp>.html` (one run summary page per all-method sweep, when present)
- `data/.history/dashboard/all-method-benchmark/all-method-benchmark__<run_timestamp>__<source_slug>.html` (per-book config breakdown pages, when present)

Notes:

- `index.html` embeds an inline copy of `dashboard_data.json`, so it still works via `file://` even when browser local fetches are restricted.
- Collectors are read-only. They do not modify the source metrics in `data/output` or `data/golden`.
- Benchmark rows classified as test/gate noise are ignored before rendering (`/bench/`, pytest temp eval paths, and timestamp-suffix tokens like `_...-gated-...` / `_...-smoke-...` / `_...-test-...`) so those runs never appear in `Previous Runs` or latest diagnostics.
- All-method standalone pages are built from benchmark CSV rows (`run_dir` / `artifact_dir`) grouped by benchmark sweep paths:
  - `all-method-benchmark/<source_slug>/config_*`
  - `single-profile-benchmark/<source_slug>`
  (CSV-first; no extra dashboard-only metric store). The hierarchy is run summary -> per-book detail, and all pages are written under `data/.history/dashboard/all-method-benchmark/`.
- `single-offline-benchmark/{vanilla,codexfarm}` eval directories are collected and shown in the regular benchmark tables/metrics (not grouped into all-method standalone pages).
- Before writing all-method pages, renderer removes stale legacy root pages (`all-method-benchmark.html`, old top-level detail pages) so only the subfolder hierarchy remains.

## Index layout

`index.html` is intentionally minimal:

- `Diagnostics (Latest Benchmark)`: runtime + per-label + boundary breakdown for the most recent benchmark record.
  - Layout: on desktop, `Benchmark Runtime` and `Boundary Classification` each take one half-width column on the top row; `Per-Label Breakdown` renders below as a full-width card (mobile collapses to one column).
  - Runtime card surfaces best-effort AI context from benchmark run-config metadata (`model`, `thinking effort`, pipeline mode), preferring latest non-speed rows when both speed/non-speed exist.
  - Runtime card surfaces `Token use` using the same cached-adjusted discounted token formula as `All token use`, with compact `k`/`m` display for large values.
  - When multiple latest rows share one timestamp (for example single-offline `codexfarm` + `vanilla`), diagnostics prefers the row with richer AI metadata (model/effort/pipeline-on) instead of defaulting to `off`.
  - If benchmark run-config is missing codex model/effort, collector backfills from benchmark manifest `llm_codex_farm.process_runs.*.process_payload` (and telemetry reasoning breakdown fallback) so codex rows do not show false `off` labels.
  - When run-config omits explicit model/effort (for example defaults), collector backfills from prediction-run manifest `llm_codex_farm` runtime payload when available.
  - When both speed-suite benchmark rows (`.../bench/speed/runs/...`) and regular benchmark rows exist, diagnostics prefer the latest non-speed rows to avoid one-target speed samples overriding multi-book benchmark diagnostics.
  - Speed/non-speed and all-method detection normalizes `artifact_dir` path separators first, so Windows-style `\\` paths in history data are handled the same as `/`.
  - Canonical-text benchmark reports now include `boundary` counts again, so boundary diagnostics can advance with current single-offline/all-method benchmark rows instead of falling back to older freeform-eval rows.
  - Boundary diagnostics now aggregate all boundary-bearing rows at the latest preferred benchmark run-group key (artifact-path timestamp token fallback to record timestamp), so twinned `vanilla`/`codexfarm` evals are grouped even when eval completion timestamps differ.
  - Boundary diagnostics include matched-coverage context (`gold_matched/gold_total`, `gold_matched/pred_total`) so `100/0/0` splits are read as matched-boundary-only.
  - Boundary table shows `% of gold` only (clean denominator), plus `Matched (boundary unclassified)` and `Unmatched gold spans` rows so gaps are visible in one pass.
  - Per-label diagnostics keep latest-run `codexfarm` precision/recall as raw baseline columns, and show signed deltas for the other precision/recall columns against that same-label baseline (green = better, red = worse).
  - Per-label diagnostics include a small `Rolling N` selector in-card; rolling codexfarm/vanilla delta columns sit under one shared dynamic group header (`<N>-run Rolling Delta:`), with per-column labels reduced to metric + variant.
  - Per-label table column order starts with `Label`, `Gold`, `Pred`, then the precision/recall baseline + delta columns.
  - Latest-run aggregation uses the same benchmark run-group key as trend tooltips (`benchmarkRunGroupInfo`) so single-offline twinned runs count as one group.
  - Per-label metric headers are intentionally three-line (`group`, `metric`, `(variant)`) and left-aligned to keep diagnostic columns narrower on single-screen layouts.
  - Per-label table is content-sized (no forced full-card width) with compact fixed-width metric/count columns so numeric deltas stay dense; horizontal scroll remains available for overflow.
- `Previous Runs`: full-history table with key benchmark columns only.
  - The table viewport is fixed to roughly 10 data rows of height (even when current filters show fewer rows), then scrolls vertically.
  - Horizontal scrolling is enabled; table keeps a minimum width so wide benchmark columns stay readable instead of over-compressing.
  - Click any table header to toggle sort direction for that column (`A→Z` / `Z→A`), including timestamps.
  - Includes a `+/-` button beside the table header row that opens a small checkbox menu for show/hide column selection; drag headers to reorder and drag header edges to resize.
  - `Quick Filters` includes inline `View presets` controls (`Load`, `Save current view`, `Delete`) so preset actions are available without opening a second popup.
  - Previous Runs UI preferences persist in browser local storage (`localStorage`): column visibility/order/widths, column filters, quick-filter toggles, isolate combine mode + stacked isolate rules, current sort, and named view presets are restored across page reloads and dashboard regenerations at the same dashboard URL/path.
  - When opened via `cookimport stats-dashboard --serve`, the same UI state is also synced to `assets/dashboard_ui_state.json` so settings carry across browsers on the same machine.
  - While the page stays open, program-side state is polled every few seconds and newer remote state is applied live without a page refresh.
  - Diagnostic table resize is limited to `Per-Label Breakdown`; `Boundary Classification` and `Benchmark Runtime` are fixed-fit cards (no horizontal scroll/resize) to keep the top row stable.
  - Normal benchmark rows: timestamp links to `artifact_dir`.
  - `AI Model` and `AI Effort` are separate columns and only show model/effort-derived runtime values; pipeline profile names are not used as fallback (`AI Model=off` still displays as `off`).
  - Placeholder effort values like `<default>`/`default` are treated as unknown effort; CSV backfill resolves model-default effort where available.
  - For `single-offline-benchmark/.../vanilla` rows (or `llm_recipe_pipeline=off` rows), AI model/effort cells are intentionally suppressed even if stale run-config metadata still carries codex model/effort keys.
  - `All token use` is shown by default and displays `discounted_total | input | output` in one cell, abbreviated with `k`/`m` where large (for example `854k`, `2.27m`).
  - Discounted total applies cached-input tokens at `0.1x` weight (`(input - cached_input) + 0.1*cached_input + output`).
  - Sorting and filtering `All token use` uses that discounted numeric total (not raw `tokens_total`).
  - Other token columns (`Tokens In`, `Tokens Cached In`, `Tokens Out`, `Tokens Reasoning`, `Tokens Total`) can be enabled from the same `+/-` column picker.
  - `Source` prefers `source_file` basename, then artifact-path source slug fallback (`all-method-benchmark`, `single-profile-benchmark`, `scenario_runs`, `eval/<slug>` patterns).
  - `Importer` uses CSV/importer metadata first, then source-path/run-config fallback (for older benchmark rows with blank CSV importer).
  - All-method benchmark sweeps collapse to one row with summarized `Source` text (`all-method: <top source> + N more`), and timestamp links to generated run-summary HTML under `all-method-benchmark/`.
  - Includes per-column header-adjacent stacked filters: use the `+/-` toggle in the first row under headers to open a small popup editor. Saving appends a new clause for that column, active clauses can be removed via `×`, and each column stack supports an `AND/OR` mode toggle. Active summaries in the filter row now render one clause per line with its own `X` remove button. Save/close keeps compact active-filter summaries visible in-row. Non-numeric value inputs are typeahead fields with ranked candidate chips from that column, and `Tab` accepts the top suggestion.
  - Previous Runs header row order is: column names, filter summary/editor row, then one blank spacer row before data rows.
  - Multi-row sticky headers rely on `#previous-runs-table { border-collapse: separate; border-spacing: 0; }` to avoid browser overlap/bleed artifacts.
  - Do not set `position: relative` on `#previous-runs-table th`; that overrides sticky header positioning and causes row-offset overlap artifacts.
  - Includes an `Isolate For X` panel beside the trend chart (left on desktop, stacked on small screens): add one or more field + logic (`is` / `is not`) + value rules, choose `all rules (AND)` vs `any rule (OR)`, and auto-filter both chart/table with slice-vs-baseline metric deltas (quality, runtime/token fields when present).
  - Isolate vs table column filters use `last edited wins`: editing isolate controls makes isolate override table filters; editing table column filters pauses isolate until isolate is edited again.
  - The `Benchmark Score Trend` Highcharts panel uses a fixed 800px chart/container height to avoid browser reflow loops that can cause gradual chart height growth.
  - A `Quick Filters` section sits between the trend chart and table:
    - `Official benchmarks only (single-offline vanilla/codexfarm)` keeps the chart/table focused on paired single-offline benchmark mode used for headline comparisons.
    - `Exclude AI test/smoke benchmark runs` remains available mainly as a legacy cleanup toggle for older saved dashboard payloads.
    - `Clear all filters` resets quick filters, per-column table filters, and isolate rules in one click.
  - Benchmark trend timestamps are rendered in the browser's local timezone (`useUTC: false`) so chart hover time aligns with local run expectations.
  - Score series are plotted as discrete scatter points (no continuous interpolation line between run timestamps).
  - When filtered rows include paired benchmark variants (`codexfarm`/`vanilla`), trend points split into separate series per metric+variant so paired runs are visually distinct.
  - Hovering any trend point shows one run-level tooltip card with local run timestamp and all visible series values for that run group (instead of per-point coordinate tooltips).
  - The `Benchmark Score Trend` range selector defaults to `All`, so older benchmark history is visible on first load instead of starting on a short recent window.
  - The trend chart x-axis is initialized from the full filtered `Previous Runs` timestamp span (including rows without explicit score points), so timeline dates stay aligned with the table.
  - Highcharts Stock now loads with a secondary CDN fallback (`code.highcharts.com` -> `cdn.jsdelivr.net`) before `assets/dashboard.js`, reducing random single-CDN load failures.
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

Benchmark token note:
- Codex benchmark rows can persist `tokens_input`, `tokens_cached_input`, `tokens_output`, `tokens_reasoning`, and `tokens_total` in benchmark CSV history.
- Backfill can patch missing `tokens_*` columns from nearby prediction manifests when telemetry rows exist.

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
- `--serve`: serve dashboard over HTTP and enable program-side UI-state sync (`assets/dashboard_ui_state.json`)
- `--host <host>`: host interface for `--serve`
- `--port <port>`: port for `--serve` (`0` picks a free port)
- `--since-days N`: include only recent runs
- `--scan-reports`: force scan of `*.excel_import_report.json` in addition to CSV
- `--scan-benchmark-reports`: force recursive benchmark `eval_report.json` scan and merge with CSV rows

## Known gotcha

`cookimport stats-dashboard` reads stage/import history primarily from `<output_root parent>/.history/performance_history.csv`.

`dashboard_render.py` embeds JS/CSS as Python string templates; regex escapes in JS literals must stay double-escaped in Python (for example `\\s`) to avoid `SyntaxWarning` and preserve valid emitted JS.

If you stage into a non-default output root (for example `cookimport stage --out /tmp/out`), build the dashboard with the matching root (for example `cookimport stats-dashboard --output-root /tmp/out`) so the collector reads the same history CSV and report folders you just produced.
