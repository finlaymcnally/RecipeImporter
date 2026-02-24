---
summary: "Analytics architecture and implementation history log: versions, experiments, reversals, fixes, and provenance to prevent repeated loops."
read_when:
  - When iterating on analytics/dashboard changes and you need to verify what was already tried
  - When a task is going in multi-turn circles, or the human says "we are going in circles on this"
  - When reconciling behavior differences across analytics/dashboard versions
---

# 08 Analytics Log

This is the analytics history/attempt log. Keep `08-analytics_readme.md` for current behavior docs, and use this file to avoid repeating prior implementation paths.
Section numbers below intentionally preserve the source README numbering for provenance.

## 5) Historical timeline and prior attempts (preserved)

This section intentionally keeps prior context to avoid repeating cycles.

### 2026-02-01 performance strategy + implementation push

Sources merged here:
- prior `SPEED_UP.md` (ExecPlan + implementation log)
- prior `resource_usage_report.md` (resource bottleneck analysis + recommendations)

What was proposed:

1. Add runtime observability first (timing fields/checkpoints).
2. Add explicit OCR device control (`auto|cpu|cuda|mps`).
3. Add OCR batching (`--ocr-batch-size`).
4. Add warm-model path (`--warm-models`).
5. Add multi-process staging.
6. Add tests/docs around this.

What code now confirms as implemented:

- CLI options for OCR device, OCR batch size, warming, workers, and split-worker controls exist in `stage` command.
- Per-file `timing` and checkpoint data are written into conversion reports.
- Parallel processing and split-job merge flows are active.
- Stats dashboard + analytics tests exist (`tests/test_stats_dashboard.py`).

What to retain from old analysis even if wording is stale:

- RAM is still the limiting factor as worker count rises.
- OCR acceleration can shift bottlenecks from OCR to parsing/writing.
- Batch-size and worker-count tuning should be empirical per machine/input mix.

What became outdated in older docs:

- Claim that staging is sequential/single-threaded is no longer true.
- Claim that OCR device handling is entirely unmanaged is no longer true.

### 2026-02-12 metrics observability map

Source merged here:
- prior `2026-02-12_11.31.47-metrics-observability-map.md`

Status:

- The three-surface metrics map (per-run report, history CSV, Label Studio eval artifacts) is still accurate.
- Split merge timing note (`timing.checkpoints.merge_seconds`) is still accurate.

### 2026-02-15_22.07.37 analytics metrics flow and mismatch map

Merged source file:
- `2026-02-15_22.07.37-analytics-metrics-flow-and-mismatches.md` (formerly in `docs/understandings`)

Preserved findings:
- Stage writes per-file reports at `<run_root>/<slug>.excel_import_report.json`, then derives perf summary rows and appends history CSV.
- Stats dashboard primarily reads `data/output/.history/performance_history.csv`, then supplements/falls back to report JSON scan.
- That investigation identified two mismatches that were later fixed:
  - `perf_report.resolve_run_dir()` now accepts both hyphen-style legacy folders and underscore/dot stage folders.
  - Stage history append now targets `history_path(<actual_stage_output_root>)`, not `history_path(DEFAULT_OUTPUT)`.

### 2026-02-15_23.17.17 file:// dashboard data-loading fallback

Merged source file:
- `2026-02-15_23.17.17-stats-dashboard-file-scheme-fetch-fallback.md` (formerly in `docs/understandings`)

Problem captured:
- Browser local-file mode (`file://`) can block JS `fetch("assets/dashboard_data.json")`, making dashboard appear broken even when artifacts were written correctly.

Decision captured:
- Keep writing `assets/dashboard_data.json` for normal hosting/inspection.
- Also embed the same JSON payload inline in `index.html`.
- Dashboard JS should read inline JSON first, then fall back to fetch only when inline payload is missing/invalid.

### 2026-02-15_23.36.55 benchmark metadata merge by artifact directory

Merged source file:
- `2026-02-15_23.36.55-benchmark-dashboard-metadata-flow.md` (formerly in `docs/understandings`)

Problem captured:
- Benchmark enrichment metadata (`manifest.json`, `coverage.json`) can live under `<eval_dir>/prediction-run/`, not only eval root.
- CSV and JSON benchmark rows can describe the same eval run with timestamp differences, creating duplicate rows when merged by timestamp.

Decision captured:
- Probe both eval root and `prediction-run/` for benchmark enrichment.
- Merge CSV + JSON benchmark rows by eval artifact directory and fill missing fields instead of appending duplicates.

### 2026-02-15_23.50.42 throughput view split into run/date + file-trend perspectives

Merged source:
- `docs/tasks/2026-02-15_23.50.42 - dashboard-throughput-run-and-file-views.md`

Problem captured:
- Existing throughput section made it hard to answer both run-over-run trend questions and per-file trend questions.

Decision captured:
- Keep run/date view (`Recent Runs` table + trend) and add a file-focused trend/table view for one selected file over time.
- Scope explicitly kept renderer-only (no collector/schema changes for this step).

Task verification/evidence preserved:
- `. .venv/bin/activate && pytest -q tests/test_stats_dashboard.py`
- recorded result: `24 passed`.

### 2026-02-15_23.51.02 throughput organization rule clarified

Merged source file:
- `2026-02-15_23.51.02-dashboard-throughput-run-vs-file-organization.md` (formerly in `docs/understandings`)

Durable rule:
- Throughput should continue exposing both views backed by the same stage records:
  - run/date timeline across all records (newest-first table sorting),
  - single-file trend over time grouped by `StageRecord.file_name` (chronological trend order).

### 2026-02-16_00.10.16 mixed timestamp sort fix

Merged source:
- `docs/tasks/2026-02-16_00.10.16 - fix-dashboard-benchmark-time-sort.md`
- `2026-02-16_00.10.16-dashboard-mixed-timestamp-sort-order.md` (formerly in `docs/understandings`)

Problem captured:
- Lexicographic sort broke ordering when datasets mixed `YYYY-MM-DDTHH:MM:SS` and `YYYY-MM-DD_HH.MM.SS`.

Decision captured:
- Use parsed timestamp ordering in both collector (latest timestamp selection + sort keys) and renderer JS (recent benchmark/run tables).
- Keep unparseable rows visible and place them last where possible.

Task verification/evidence preserved:
- `. .venv/bin/activate && pytest -q tests/test_stats_dashboard.py` with mixed-format timestamp regressions (task records `26 passed`).
- `cookimport stats-dashboard` run also recorded as successful artifact regeneration.

### 2026-02-16_00.13.03 per-file history lists experiment (later superseded)

Merged source:
- `docs/tasks/2026-02-16_00.13.03 - dashboard-per-file-import-history-lists.md`
- `2026-02-16_00.12.54-dashboard-throughput-per-file-history-lists.md` (formerly in `docs/understandings`)

What was tried:
- Replaced selected-file trend control with always-visible `Per-File History Lists` (one table per file).

Why this matters historically:
- This was a real implemented direction (with tests passing), but it was later judged too heavy and replaced.

Task verification/evidence preserved:
- task records `pytest -q tests/test_stats_dashboard.py` passing (`26 passed`).

### 2026-02-16_00.19.42 stage/import run-config context added to throughput tables

Merged source:
- `docs/tasks/2026-02-16_00.19.42 - dashboard-import-run-config-columns.md`
- `2026-02-16_00.19.42-stage-run-config-flow-into-dashboard.md` (formerly in `docs/understandings`)

Problem captured:
- Benchmark rows showed run-config summaries, stage/import rows did not.

Decision captured:
- Persist stage `runConfig` into CSV (`run_config_json`) during history writes.
- Collect into stage records and render `Importer` + `Run Config` columns in run/date and file-trend tables.
- Reuse benchmark-style summary key ordering/formatting for consistency.

Task verification/evidence preserved:
- task records `pytest -q tests/test_stats_dashboard.py` passing (`27 passed`).

### 2026-02-16_00.25.07 selector-based file trend restored (reversal of 00.13.03)

Merged source:
- `docs/tasks/2026-02-16_00.25.07 - dashboard-file-trend-selector-restore.md`
- `2026-02-16_00.25.07-dashboard-file-trend-selector-preferred.md` (formerly in `docs/understandings`)

Reason for reversal:
- always-visible per-file list layout was considered visually heavy and slower to scan.

Final decision captured:
- Restore single dropdown-driven file trend UI.
- Keep run-config columns/summaries introduced at `00.19.42`.

Task verification/evidence preserved:
- task records `pytest -q tests/test_stats_dashboard.py` passing (`27 passed`).

Anti-loop note:
- Per-file card/list layout is a known attempted branch; do not reintroduce it without a clear UX reason.

### 2026-02-16_00.26.20 pytest temp benchmark artifact filtering

Merged source:
- `docs/tasks/2026-02-16_00.26.20 - dashboard-ignore-pytest-benchmark-artifacts.md`
- `2026-02-16_00.26.20-dashboard-ignore-pytest-benchmark-artifacts.md` (formerly in `docs/understandings`)

Problem captured:
- `Recent Benchmarks` could include local pytest temp rows (for example `pytest-46/test_.../eval`), polluting user-facing history.

Decision captured:
- Add narrow pytest-path detector in benchmark collectors and skip matching temp artifact rows in both CSV and JSON collection paths.

Task verification/evidence preserved:
- targeted filter test: `1 passed, 27 deselected`.
- full suite after change: `28 passed`.

### 2026-02-16_10.37.22 report-path run-config backfill for historical stage rows

Merged source:
- `docs/tasks/2026-02-16_10.37.22 - dashboard-stage-run-config-backfill-from-report-path.md`
- `2026-02-16_10.37.22-stage-run-config-csv-backfill-rule.md` (formerly in `docs/understandings`)

Problem captured:
- Older CSV rows often have empty `run_config_json`, leaving new Run Config columns blank.

Decision captured:
- Collector precedence:
  - use CSV `run_config_json` when present,
  - else best-effort read row `report_path` JSON and load `runConfig`.
- Keep fallback read-only and non-fatal when report files are missing.

Task verification/evidence preserved:
- task records `pytest -q tests/test_stats_dashboard.py` passing (`29 passed`).

### 2026-02-16_10.43.02 stale-row warning for missing report references

Merged source:
- `docs/tasks/2026-02-16_10.43.02 - dashboard-stale-run-config-warning.md`
- `2026-02-16_10.43.02-dashboard-stale-row-warning-rule.md` (formerly in `docs/understandings`)

Problem captured:
- Some rows had neither CSV config nor resolvable report path, and silently rendered as `-`.

Decision captured:
- Add `StageRecord.run_config_warning`.
- Mark rows as stale when `report_path` is referenced but missing.
- Keep stale rows visible and render explicit warning text in Run Config cell.

Task verification/evidence preserved:
- task records `pytest -q tests/test_stats_dashboard.py` passing (`31 passed`).

### 2026-02-16_10.51.07 consolidated rule: CSV-first run-config + report fallback + stale warning

Merged source:
- `docs/tasks/2026-02-16_10.51.07 - csv-robust-stage-run-config-and-stale-warning.md`
- `2026-02-16_10.51.07-stage-run-config-stale-warning-metadata.md` (formerly in `docs/understandings`)

Final durable rule from the `10.37 -> 10.43 -> 10.51` sequence:
1. Primary: use CSV `run_config_json`.
2. Fallback: parse `report_path` JSON `runConfig` when primary is empty and report still exists.
3. If both unavailable and report reference is stale: keep row and render warning (`[warn] missing report (stale row)`).

Task verification/evidence preserved:
- task records `pytest -q tests/test_stats_dashboard.py` passing (`31 passed`).

### 2026-02-16_10.56.36 benchmark recipe counts vs span metrics

Merged source file:
- `2026-02-16_10.56.36-benchmark-dashboard-recipe-count-vs-span-metrics.md` (formerly in `docs/understandings`)

Problem captured:
- Users were reading `Gold`/`Matched` columns in `Recent Benchmarks` as recipe totals; those are span-eval counts.

Decision captured:
- Keep span metrics (`Gold`, `Matched`) as the scoring surface.
- Add benchmark `Recipes` column sourced from CSV `recipes` and backfilled from `processed_report_path` (`totalRecipes`) when needed.

Anti-loop note:
- Perfect span scores do not imply perfect recipe-level parity in staged cookbook outputs; these are related but different contracts.

### 2026-02-16_11.33.17 benchmark recipes blank due to CSV append-path gaps

Merged source file:
- `2026-02-16_11.33.17-benchmark-recipes-blank-csv-path-gaps.md` (formerly in `docs/understandings`)

Problem captured:
- `Recent Benchmarks` reads from benchmark `recipes`, but only one command path initially persisted recipe counts consistently.
- `labelstudio-eval` and `bench run` could leave `recipes` blank even for new rows.

Final rule:
- Persist benchmark `recipes` in CSV for every benchmark CLI entrypoint (`labelstudio-benchmark`, `labelstudio-eval`, `bench run`).
- Use prediction-run manifest `recipe_count` first.
- Fall back to `processed_report_path` -> `totalRecipes` when manifest recipe count is unavailable.

### 2026-02-16_11.41.26 benchmark CSV backfill manifest resolution details

Merged source file:
- `2026-02-16_11.41.26-benchmark-csv-backfill-manifest-resolution.md` (formerly in `docs/understandings`)

Preserved recovery precedence/details:
- Resolve benchmark artifacts from CSV row `run_dir`.
- For single eval runs, check `run_dir/prediction-run/manifest.json` first (and `run_dir/manifest.json` fallback).
- For bench-suite runs, recover totals by summing `run_dir/per_item/*/pred_run/manifest.json` `recipe_count`.
- `recipes` precedence:
  1. manifest `recipe_count`
  2. fallback `processed_report_path` -> report `totalRecipes`
- Backfill scope remains limited to missing `recipes`, `report_path`, and `file_name`.

### 2026-02-16_12.09.36 run-settings propagation into analytics/dashboard

Merged source file:
- `2026-02-16_12.09.36-run-settings-config-propagation.md` (formerly in `docs/understandings`)

Durable analytics contract:
- `run_config_hash`, `run_config_summary`, and `run_config_json` must be persisted to history CSV for stage and benchmark rows.
- Dashboard collector prefers CSV hash/summary/json and only falls back to report/manifest reads when CSV context is missing.
- Dashboard renderer should keep stale-row signaling when legacy report references are missing.
- Run-setting canonical source remains `cookimport/config/run_settings.py`, but analytics consumers must treat CSV as primary runtime history surface.

### 2026-02-16_12.30.45 history-root alignment and mixed timestamp run-dir resolution

Merged source file:
- `2026-02-16_12.30.45-run-manifest-semantics-and-history-root.md` (formerly in `docs/understandings`)

Analytics-relevant outcomes:
- Stage CSV appends to `<stage --out>/.history/performance_history.csv`.
- Benchmark CSV appends to `<processed_output_dir>/.history/performance_history.csv`.
- `perf_report.resolve_run_dir()` supports both timestamp folder styles:
  - `YYYY-MM-DD_HH.MM.SS`
  - `YYYY-MM-DD-HH-MM-SS`
- This preserves auto-latest behavior across mixed historical output folders.


## 10) Consolidation provenance

This README replaced and merged:

- `docs/08-analytics/08-analytics_README.md`
- `docs/08-analytics/2026-02-12_11.31.47-metrics-observability-map.md`
- `docs/08-analytics/SPEED_UP.md`
- `docs/08-analytics/resource_usage_report.md`

Intentional preservation policy used during merge:
- Keep implementation history and failed/stale assumptions in “Historical timeline” and “Known bad”.
- Prefer code-verified current behavior when old docs conflict.

### 2026-02-20_14.40.00 EPUB auto report/analytics wiring map

Merged source file:
- `docs/understandings/2026-02-20_14.40.00-epub-auto-report-analytics-wiring.md`

Preserved cross-layer contract:
1. Stage orchestration resolves `auto` and forwards effective extractor metadata into worker/split-merge write paths.
2. Report writers must emit `epubAutoSelection` and `epubAutoSelectedScore`.
3. CSV history must persist `epub_extractor_requested`, `epub_extractor_effective`, and `epub_auto_selected_score`.
4. Dashboard schema/collector/render should map and display those explicit fields directly.

Anti-loop note:
- Writing auto metadata only to raw artifacts is incomplete; if one of these layers is skipped, users see extractor state in some analytics surfaces but not others.

## 2026-02-23 docs/tasks archival merge batch (analytics)

### 2026-02-12 lifetime stats dashboard baseline (`docs/tasks/I1.1-STATS-DASH.md`)

Problem captured:
- Throughput and benchmark trends were scattered across raw files, making regressions hard to inspect quickly.

Major decisions preserved:
- Build a static offline dashboard with zero runtime network dependencies.
- Keep collectors read-only and focused on compact metric surfaces (CSV + eval/report JSON), not full output rescans by default.
- Separate run categories to avoid inflated counts from mixed stage/labelstudio/benchmark artifact roots.

Anti-loop note:
- Dashboard generation should not mutate run artifacts; if a proposed change writes outside `--out-dir`, treat it as contract drift.

### 2026-02-23_12.29.17 dashboard JS newline escaping regression

Merged source:
- `docs/understandings/2026-02-23_12.29.17-dashboard-js-newline-escape.md`

Problem captured:
- `dashboard_render.py` JS template strings can accidentally emit a raw newline inside a quoted JS string when Python uses `"\n"` instead of `"\\n"`.
- Symptom is severe but non-obvious: generated dashboard opens but renders blank because `dashboard.js` fails to parse.

Decision preserved:
- Keep explicit double escaping for run-config tooltip newline joins in `runConfigCell`.
- Treat this as a renderer-template correctness issue, not a data-collection issue.

Anti-loop note:
- If dashboard content is blank, inspect generated `dashboard.js` parse validity before reworking collector/schema code.

## 2026-02-24 archival merge batch from `docs/understandings` (analytics)

### 2026-02-23_16.13.59 all-method page grouping discovery

Merged source:
- `docs/understandings/2026-02-23_16.13.59-dashboard-all-method-page-grouping.md`

Preserved findings:
- Grouping can stay CSV-first by clustering benchmark rows with artifact paths containing `all-method-benchmark/<source_slug>/config_*`.
- Stable detail page naming uses `<run_timestamp>__<source_slug>`.
- Root all-method page should exist in the same static site root as `index.html`.

### 2026-02-23_22.06.13 all-method root page always-generated contract

Merged source:
- `docs/understandings/2026-02-23_22.06.13-dashboard-all-method-root-page-contract.md`

Preserved rule:
- `all-method-benchmark.html` must always be generated, even when grouped runs are currently empty.
- Detail pages remain sibling files at dashboard root, not hidden in subfolders.

### 2026-02-23_22.15.18 recursive eval report scan requirement

Merged source:
- `docs/understandings/2026-02-23_22.15.18-dashboard-benchmark-recursive-eval-scan.md`

Preserved rule:
- Benchmark collector must recurse under golden roots for nested `config_*/eval_report.json` outputs.
- Exclusions for `prediction-run` and pytest temp artifact paths remain necessary to keep history clean.

### 2026-02-23_22.21.16 detail summary stats + bar charts

Merged source:
- `docs/understandings/2026-02-23_22.21.16-all-method-detail-summary-bars.md`

Preserved rendering rule:
- Detail pages should show quick-scan summary stats and per-metric run bars before the ranked config table.

### 2026-02-23_22.26.07 explicit configuration-dimension columns

Merged source:
- `docs/understandings/2026-02-23_22.26.07-all-method-dimension-columns.md`

Preserved rendering rule:
- Ranked detail rows keep explicit columns for extractor/parser/skiphf/preprocess values.
- Source for values is run config first, config-slug parsing fallback second.

### 2026-02-24_00.40.56 run-level all-method hierarchy layer

Merged source:
- `docs/understandings/2026-02-24_00.40.56-all-method-run-level-dashboard-hierarchy.md`

Preserved contract:
- Dashboard now has run-level summary pages above per-book detail pages.
- Run summary aggregation key is `run_config_hash` with slug fallback for older rows.

Anti-loop note for this batch:
- If all-method pages disappear, check collector recursion + path grouping + always-write root-page behavior before changing renderer layout.

## 2026-02-24 docs/tasks archival merge batch (analytics ExecPlans)

### 2026-02-24_00.36.38 run-level all-method dashboard aggregation

Merged source:
- `docs/tasks/2026-02-24_00.36.38-all-method-run-level-dashboard-aggregation.md`

Problem captured:
- Per-book all-method rows made mega-run interpretation noisy; operators needed one run-level view of config winners across books.

Decisions preserved:
- Keep existing per-book detail pages intact and add a run-detail layer above them.
- Aggregate config rows by `run_config_hash` when present (config-name fallback for legacy rows).
- Rank run-level configs by breadth first (`books`), then practical/strict means, wins, and strict tie-break metrics.

Implementation boundary preserved:
- Change was renderer-only over existing CSV-backed benchmark records; no dashboard schema/collector rewrite required.

Evidence preserved:
- Task records:
  - `pytest tests/analytics/test_stats_dashboard.py -k all_method` -> `3 passed, 37 deselected, 2 warnings`,
  - full dashboard suite -> `40 passed, 2 warnings`.

### 2026-02-24_08.30.36 benchmark timing telemetry + analyzer foundations

Merged source:
- `docs/tasks/2026-02-24_08.30.36-benchmark-timing-telemetry-and-runtime-analyzer-foundation.md`

Problem captured:
- Quality metrics were available, but benchmark runtime attribution was weak (blank timing columns and missing report timing in benchmark-produced artifacts).

Decisions preserved:
- Ship timing as additive fields in existing artifacts/CSV instead of a new telemetry store.
- Keep benchmark ranking semantics unchanged; timing is observational metadata only.
- Reuse stage timing columns for compatibility and add benchmark-specific timing columns for eval/orchestration phases.
- Add helper foundations for future analysis (`collect_all_method_timing_summary(...)`) but defer new analyzer CLI command.
- Treat processed report timing update as best-effort/non-fatal to avoid benchmark hard failures.

Important discovery preserved:
- Fast/mocked runs can under-report `total_seconds` unless totals are floored against known subphase sums; tests now guard this.

Evidence preserved:
- Task records targeted suite:
  - `pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py tests/analytics/test_perf_report.py tests/analytics/test_stats_dashboard.py` -> `111 passed`.
- Task records smoke suite:
  - `pytest -m smoke` -> `36 passed`.

Anti-loop note for this batch:
- If timing columns are blank, verify prediction/report timing propagation before changing CSV schema; append precedence already handles explicit timing first and processed-report fallback second.
