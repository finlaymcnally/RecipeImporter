---
summary: "Analytics architecture and implementation history log: versions, experiments, reversals, fixes, and provenance to prevent repeated loops."
read_when:
  - When iterating on analytics/dashboard changes and you need to verify what was already tried
  - When a task is going in multi-turn circles, or the human says "we are going in circles on this"
  - When reconciling behavior differences across analytics/dashboard versions
---

# 08 Analytics Log

Historical log for analytics decisions that still map to active code paths.

This file was intentionally pruned. Removed dashboard branches, deleted UI experiments, and old task-by-task migration notes were cut so this log only keeps history that still explains current code.

Use `08-analytics_readme.md` for the current contract.

## 1) Timeline (active-relevance only)

### 2026-02-01 performance observability foundation

Still-relevant outcomes:
- Conversion reports made timing checkpoints first-class.
- Stage flows stabilized enough that report -> CSV -> dashboard became a testable contract.
- Parallel/split staging assumptions became part of the normal runtime model.

Anti-loop note:
- Do not reason from older sequential-only staging notes.

### 2026-02-15 `file://` dashboard fallback

Problem solved:
- Some browsers blocked `fetch("assets/dashboard_data.json")` when the dashboard was opened directly from disk.

Durable fix:
- `index.html` embeds inline dashboard JSON.
- Dashboard JS loads inline data first, then falls back to fetch.

### 2026-02-15 benchmark metadata merge by artifact directory

Problem solved:
- Benchmark metadata can live in both the eval directory and `prediction-run/`.
- Timestamp-only merge logic produced duplicates and incomplete rows.

Durable fix:
- Benchmark enrichment keys off benchmark artifact identity, not timestamp alone.
- Collector probes both eval-root and `prediction-run/` enrichment files.

### 2026-02-16 history-root, timestamp, and CSV durability contracts

Still-relevant outcomes:
- History CSV location is derived from the output root and normally lives at `<output_root parent>/.history/performance_history.csv`.
- Collector tolerates mixed timestamp formats and sorts by parsed time, not raw strings.
- Appenders expand older CSV headers before writing and use locking to reduce concurrent-write corruption.
- Run-config context became first-class in both stage and benchmark rows.

Anti-loop note:
- If history appears missing, check output-root resolution before changing collector scan logic.

### 2026-02-16 benchmark artifact hygiene

Still-relevant outcomes:
- Benchmark collector excludes pytest temp layouts and benchmark artifact paths classified as gate/test/smoke noise.
- Benchmark recipe counts became durable CSV data, with `benchmark-csv-backfill` retained for older rows.

### 2026-02-23 static/offline dashboard contract

Still-relevant outcomes:
- Dashboard generation is read-only against source metrics.
- Static/offline usage remains the default.
- Collector and renderer stay separate: gather data first, then emit files.

### 2026-02-24 all-method standalone page hierarchy

Still-relevant outcomes:
- All-method output moved under `all-method-benchmark/`.
- The durable hierarchy is run summary -> per-book detail.
- Run-level aggregation groups by stable run identity, preferring run-config hashes when available.

### 2026-02-24 history-write refresh wiring

Still-relevant outcomes:
- Stage/perf/benchmark history writes trigger best-effort dashboard refresh.
- Batch benchmark flows suppress per-subrun refreshes and refresh once per source/run batch.
- Refresh inference depends on the canonical history-root path shape.

Anti-loop note:
- If a custom non-canonical history path is used, explicit `cookimport stats-dashboard` rebuilds are expected.

### 2026-02-28 collector transition and diagnostics preference

Still-relevant outcomes:
- Collector keeps transition fallbacks for prior history-root layouts.
- Diagnostics prefer non-speed benchmark rows when both speed and non-speed rows exist.
- Path normalization is part of the diagnostics selection contract, so mixed slash styles do not change row classification.

### 2026-02-28 trend-chart baseline

Still-relevant outcomes:
- Main dashboard includes a benchmark trend chart above `Previous Runs`.
- Highcharts mouse-wheel zoom is disabled globally.
- Trend rendering keeps mixed-format timestamp parsing and fallback messaging.

### 2026-03-02 main-page navigation contraction

Still-relevant outcomes:
- Main `index.html` no longer renders a separate all-method run-index section.
- There is no generated `all-method-benchmark/index.html`.
- All-method navigation goes through `Previous Runs` timestamp links to run-summary pages.

Anti-loop note:
- If docs suggest a main-page all-method section, trust the renderer/tests, not the older docs.

### 2026-03-03 benchmark-history workspace maturation

Still-relevant outcomes:
- `Previous Runs` became the benchmark-history workspace: trend chart, quick filters, configurable table, and view presets.
- Table filtering gained stacked clauses, per-column `AND/OR`, and a global across-columns `AND/OR` mode.
- Per-label diagnostics gained run-group awareness and a rolling-window selector.

### 2026-03-04 compare/control and served-state expansion

Still-relevant outcomes:
- `Compare & Control Analysis` became the dedicated analysis panel under `Previous Runs`.
- Compare/control chart generation became builder-driven and type-aware.
- Optional Set 2 introduced dual-set layouts and combined-axis modes.
- Served dashboards gained file-backed live state through `assets/dashboard_ui_state.json`.
- Width containment and rerender guards became part of the dashboard stability contract.

Anti-loop note:
- Compare/control has its own scope and local subsets; it is not just a second view of the table filters.

### 2026-03-05 benchmark semantics split

Still-relevant outcomes:
- `benchmark_variant` remains narrow and reserved for official paired benchmark semantics.
- `ai_assistance_profile` carries the broader runtime assistance posture.
- `AI Model` and `AI Effort` labeling uses run-config/manifest runtime context, with `System error` reserved for codex runtime failures.

### 2026-03-06 served-state precedence and trend-tail cleanup

Still-relevant outcomes:
- On served dashboards, program-side UI state is authoritative on first load.
- Trend overlays use rolling behavior that shrinks at the series edges instead of reusing the same tail window.
- `Official benchmarks only` remains intentionally narrow; hybrid rows can still appear elsewhere in diagnostics/history.

### 2026-03-16 metrics are current product fields, not just compatibility baggage

Still-relevant outcomes:
- dashboard renderers, CLI summaries, and analytics normalization still use `precision`, `recall`, and `practical_f1` as current metrics
- the real legacy seams in analytics are fallback readers and old artifact-layout tolerance, not the metric fields themselves

Anti-loop note:
- do not delete the precision/recall/practical metrics during a "legacy purge" unless the product has first adopted a replacement analytics vocabulary

### 2026-03-17 primary-history fixture drift

Still-relevant outcomes:
- the collector's canonical primary-history rule was not the bug; stale tests were still writing their main `performance_history.csv` under `output/.history`
- the fix for that class of analytics failure is to update the fixture or test setup to use `history_csv_for_output(output_root)`
- nested benchmark `.history` folders under the output root remain legitimate supplemental collector inputs and should not be "fixed" away

Anti-loop note:
- if dashboard collection finds no primary history rows, verify where the fixture wrote the CSV before changing collector search paths

### 2026-03-17 whole-run benchmark token recovery

Still-relevant outcomes:
- benchmark token enrichment should recover whole-run actuals from repo-owned artifacts first: recipe and knowledge manifest telemetry plus nested line-role telemetry when the top-level summary is sparse
- `prompt_budget_summary.json` is part of the durable actual-cost surface and should include recovered line-role stage totals when those are derivable
- dashboard `All token use` remains a cached-discounted row-level proxy, not a whole-run actual-cost answer; large differences between the dashboard cell and `prompt_budget_summary.json` can be expected on multi-stage Codex runs

Anti-loop note:
- if a dashboard token cell looks too small, inspect manifest plus `prompt_budget_summary.json` before assuming the live run used fewer tokens

### 2026-03-22 partial workspace-worker token usage must blank totals instead of faking completeness

Still-relevant outcomes:
- if a workspace-worker stage shows real command/duration activity but one or more worker calls wrote no usage, stage totals are partial or unavailable rather than literal spend
- `prompt_budget_summary.json` should carry explicit token-usage status plus available/missing call counts so downstream readers can tell why totals are blank
- this is a durable benchmark-analytics contract, not a one-off Label Studio helper quirk

Anti-loop note:
- if prompt-budget totals suddenly go blank after a run, inspect missing worker usage before adding fallback token math

## 2) Current anti-loop notes

- Main dashboard scope is only `Diagnostics (Latest Benchmark)` plus `Previous Runs`.
- Compare/control analyzes benchmark history independently from table filters.
- All-method access is through timestamp links in `Previous Runs`, not a dedicated index page.
- Benchmark collection is CSV-first; recursive JSON scans are fallback/opt-in paths, not the primary source of truth.
- Benchmark runtime/token/importer enrichment usually comes from nearby manifests when CSV rows are incomplete.
- If renderer/docs disagree, verify `tests/analytics/test_stats_dashboard.py` before restoring older UI surfaces.

## 3) Intentionally deleted history

The following categories were deliberately removed from this log because they no longer describe active features:
- task-by-task migration dumps from old `docs/understandings`
- chronology for removed dashboard panels and filters
- retired main-page branches that no longer render
- implementation notes whose only purpose was to explain deleted UI

If one of those branches ever truly needs to be resurrected, use git history, not this trimmed log, as the source material.
