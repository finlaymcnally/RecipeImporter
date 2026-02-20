---
summary: "Cross-cutting project conventions and hidden rules that must stay aligned with implementation."
read_when:
  - "When changing cross-cutting CLI/data/docs contracts"
  - "When adding new architectural rules discovered during implementation"
---

# Important Conventions

## Documentation IA

`docs/` subfolders are intentionally prefixed with two-digit numbers to express rough onboarding/implementation order.

Current order:
1. `docs/01-architecture`
2. `docs/02-cli`
3. `docs/03-ingestion`
4. `docs/04-parsing`
5. `docs/05-staging`
6. `docs/06-label-studio`
7. `docs/07-bench`
8. `docs/08-analytics`
9. `docs/09-tagging`
10. `docs/10-llm`
11. `docs/11-reference`
12. `docs/plans`
13. `docs/tasks`
14. `docs/understandings`

When adding new top-level docs sections, use the same `NN-name` convention and update `docs/README.md`.

## CLI Discovery Rule

Interactive file discovery and direct staging intentionally differ:

- Interactive menu discovery (`cookimport` with no subcommand) scans only top-level files in `data/input`.
- Direct staging (`cookimport stage <folder>`) scans recursively under the folder.
- Interactive `labelstudio` import always recreates the resolved Label Studio project (`overwrite=True`, `resume=False`) and does not prompt for resume mode.
- Interactive `labelstudio` import no longer asks for upload confirmation; once scope/options are chosen, it proceeds directly to upload (after credential resolution).
- Interactive `labelstudio` export resolves credentials first, then lists project titles from Label Studio for selection, with manual entry fallback when discovery is unavailable. If the selected project has a detected task type, export uses that scope automatically and skips the separate scope prompt.
- Label Studio export (interactive and non-interactive) writes to a stable project root by default: `data/golden/<project_slug>/exports/...`; it uses prior manifests for project/scope resolution, not for export destination. `--run-dir` still forces export into a specific run.
- Interactive main menu is persistent: successful `import`, `labelstudio`, `labelstudio_export`, and `labelstudio_benchmark` actions all return to the main menu. The session exits only when the user selects `Exit`.
- Interactive select menus should be wired through `_menu_select` so numbering, shortcuts, and Backspace-go-back behavior remain consistent.
- Interactive benchmark (`labelstudio_benchmark`) only offers `eval-only` when both discovery sets are non-empty: at least one `**/exports/freeform_span_labels.jsonl` and one `**/label_studio_tasks.jsonl` under `data/golden` or `data/output`. If either set is missing, it falls back directly to upload mode.
- Interactive Import and interactive benchmark upload both go through a per-run settings chooser (`global defaults`, `last run settings`, `change run settings`) before execution.
- Interactive benchmark eval-only mode must not apply/save pipeline run settings and should emit `Eval-only mode: no pipeline run settings applied.`
- Interactive benchmark upload resolves Label Studio credentials through `_resolve_interactive_labelstudio_settings(settings)` (env -> saved config -> prompt) before calling `labelstudio_benchmark(...)`.
- Typer command functions that are called directly from Python (interactive helpers/tests) must keep runtime defaults as plain Python values, typically via `Annotated[..., typer.Option(...)] = <default>`; avoid relying on `param: T = typer.Option(...)` defaults in those call paths.
- Interactive `generate_dashboard` asks whether to open the dashboard in a browser, then runs `stats_dashboard(output_root=<settings.output_dir>, out_dir=<output_root>/.history/dashboard)` and returns to the main menu.
- EPUB debug tooling lives under `cookimport epub ...` (sub-CLI module `cookimport/epubdebug`), and block/candidate debug commands must reuse production EPUB importer internals (`_extract_docpack`, `_detect_candidates`) to preserve stage/debug parity.

When debugging "file missing from menu" reports, check whether the file is nested inside `data/input`.

## Run Settings Source of Truth

- `cookimport/config/run_settings.py` is the canonical definition of per-run knobs (`RunSettings`), UI metadata, summary rendering, and stable hash generation.
- When a run-setting value changes split capability (for example `epub_extractor=markitdown`), update both split planners (`cookimport/cli.py:_plan_jobs`, `cookimport/labelstudio/ingest.py:_plan_parallel_convert_jobs`) and `compute_effective_workers(...)` together.
- EPUB unstructured tuning knobs (`epub_unstructured_html_parser_version`, `epub_unstructured_skip_headers_footers`, `epub_unstructured_preprocess_mode`) are part of canonical run settings and must propagate in both stage and benchmark prediction paths; do not wire them only in one flow.
- When `epub_extractor=auto` is supported, resolve it once in the parent orchestration layer (stage/benchmark prediction) and persist both `epub_extractor_requested` and `epub_extractor_effective` in run config/report surfaces.
- EPUB auto-selection metadata contract is explicit: stage/processed reports should persist `epubAutoSelection` + `epubAutoSelectedScore`, and analytics CSV should persist `epub_extractor_requested` + `epub_extractor_effective` + `epub_auto_selected_score` (dashboard reads these directly, CSV-first).
- Runtime env overrides for EPUB extraction options in prediction/stage helper flows must be scoped and restored after conversion; do not leak `C3IMP_EPUB_*` values across runs/tests.
- `stage(...)` should pass per-file effective extractor choices explicitly to workers (`stage_one_file` / `stage_epub_job`) instead of depending on persistent process-wide `C3IMP_EPUB_EXTRACTOR`.
- `cookimport/cli_ui/run_settings_flow.py` and `cookimport/cli_ui/toggle_editor.py` must derive editor rows/options from `RunSettings` metadata; do not maintain a separate hard-coded field list.
- Last-run snapshots are stored in `<output_dir>/.history/last_run_settings_{import|benchmark}.json` via `cookimport/config/last_run_store.py`.
- Schema evolution contract for stored run settings: missing keys default, unknown keys are ignored (warn once), and corrupt payloads degrade to `None` (treated as no saved run settings).
- New processing-option contract (do all, or the feature is incomplete):
  - add option to `RunSettings` + interactive selectors,
  - pass it through both run-producing command paths (`stage` and benchmark prediction generation),
  - persist it in report/manifest + history CSV run-config fields,
  - expose it in dashboard collector/renderer surfaces.
- Pipeline option edit-map references:
  - `cookimport/config/run_settings.py`
  - `cookimport/cli.py`
  - `cookimport/labelstudio/ingest.py`
  - `cookimport/core/models.py`
  - `cookimport/analytics/perf_report.py`
  - `cookimport/analytics/dashboard_collect.py`
  - `cookimport/analytics/dashboard_render.py`

## Dependency Resolution Rule

- When checking package availability with `pip index versions`, remember it is stable-only by default; for pre-release-only packages use `--pre` before concluding a dependency is unavailable.
- For optional debug/tooling dependencies that are pre-release-only (for example `epub-utils==0.1.0a1`), keep them in optional extras and maintain a no-extra fallback path.

## Report Output Convention

- The canonical stage report output path is set by `cookimport/staging/writer.py`:
  - `<run_root>/<workbook_slug>.excel_import_report.json`
- `cookimport/core/reporting.py` includes a legacy `ReportBuilder` that writes under `reports/`; treat it as legacy unless explicitly wired into active runtime flows.
- When updating docs about report locations, verify `stage()` and split-merge paths in `cookimport/cli.py` before documenting.
- Report metadata fields that must be consistent across normal and split runs (for example `importerName`, `runConfig`, `runConfigHash`, `runConfigSummary`) must be set in both:
  - `cookimport/cli_worker.py` (single-file writer path)
  - `cookimport/cli.py:_merge_split_jobs` (split merge writer path)

## Ingestion Split/Merge Rule

- Split PDF/EPUB workers write raw artifacts to `.job_parts/<workbook>/job_<index>/raw`, then the main process merges IDs/outputs and moves raw artifacts into run `raw/`.
- `epub_extractor=markitdown` is intentionally whole-book only: do not split EPUB by spine ranges for this extractor.
- `epub_extractor=markdown` is spine-range capable and should stay split-compatible; `markitdown` remains the legacy whole-book markdown path.
- Unstructured EPUB diagnostics now include both raw and normalized spine XHTML artifacts (`raw_spine_xhtml_*.xhtml`, `norm_spine_xhtml_*.xhtml`) in `raw/epub/<source_hash>/`; keep both when changing EPUB diagnostics.
- EPUB HTML extractors (`legacy` + `unstructured`) must run through shared `cookimport/parsing/epub_postprocess.py` cleanup before segmentation/signals so BR/table splitting, bullet stripping, and noise filtering remain consistent.
- EPUB extraction reports should always emit raw artifact `epub_extraction_health.json` plus stable warning keys (`epub_*`) in `ConversionReport.warnings` when thresholds trip.
- Unstructured HTML parser `v2` requires `body.Document`/`div.Page`-style inputs; adapter-level compatibility wrapping is required before `partition_html(..., html_parser_version=\"v2\")` on generic EPUB XHTML.
- `.job_parts` should be removed after successful merge; if it remains, treat it as evidence of merge failure/interruption.
- `stage` builds and passes a base `MappingConfig` to workers, so worker conversion typically skips importer `inspect()` unless planning/split metadata requires it.
- Topic/Tip writer paths may call file-hash resolution many times; when provenance lacks `file_hash`, hashing must be cached by source file metadata to avoid repeated whole-file reads in high-cardinality merge runs.
- Any payload returned from split workers (especially `ConversionResult.raw_artifacts[*].metadata`) must stay process-pickle-safe primitives; module objects in metadata will fail split benchmark/stage merges with `cannot pickle 'module' object`.

## Benchmark Contract Rule

- Freeform benchmark scoring (`labelstudio-benchmark`, interactive eval-only, and `bench run`) evaluates prediction task artifacts (`label_studio_tasks.jsonl`) against freeform gold spans (`freeform_span_labels.jsonl`), not staged cookbook outputs; optional processed outputs written during benchmark are review artifacts only.
- Non-interactive `labelstudio-benchmark` supports an explicit offline path via `--no-upload`; this mode must skip Label Studio credential resolution and never call upload APIs.
- Run-producing flows must emit `run_manifest.json` so source identity (`path` + `source_hash`), effective config, and key artifacts are inspectable without reading code.

## Analytics Caveats

- `perf_report.resolve_run_dir()` must accept both timestamp folder styles (`YYYY-MM-DD_HH.MM.SS` and legacy `YYYY-MM-DD-HH-MM-SS`) and choose the latest parsed run directory.
- Stage history append must target the actual chosen stage root (`<stage --out>/.history/performance_history.csv`), not a hard-coded default output folder.
- Dashboard `index.html` embeds dashboard JSON inline (in addition to `assets/dashboard_data.json`) so opening via `file://` works even when browser local `fetch()` is blocked.
- Dashboard timestamp ordering (recent runs/benchmarks and latest benchmark picks) must parse timestamps before sorting because history mixes `YYYY-MM-DDTHH:MM:SS` and `YYYY-MM-DD_HH.MM.SS` formats.
- Dashboard frontend timestamp parsing should explicitly parse timestamp components for those two canonical formats; avoid relying only on `Date.parse(...)` for local `file://` dashboards.
- Throughput dashboard should keep two complementary views: run/date history and file-over-time trend; file trend grouping key is `StageRecord.file_name`.
- Benchmark dashboard enrichment should read `manifest.json` and `coverage.json` from either eval root or `prediction-run/`; `labelstudio-benchmark` co-locates prediction artifacts under `prediction-run/`.
- When combining benchmark rows from JSON + CSV, dedupe by eval artifact directory and merge fields; CSV timestamps can differ from eval-folder timestamps for the same run.
- Dashboard benchmark collection should ignore pytest temp eval artifact paths (`.../pytest-<n>/test_*/eval`) so local Python test runs do not pollute benchmark history.
- Dashboard `Recent Benchmarks` `Gold`/`Matched` columns are freeform span-eval counts (`gold_total`/`gold_matched`), not recipe totals; benchmark `recipes` is stored in CSV when available and can be backfilled from `processed_report_path`.
- Dashboard metrics contract is CSV-first: every stat shown in `stats-dashboard` must be written to `performance_history.csv`; JSON report scans are fallback/backfill only.
- Run-config metrics contract is `run_config_hash` + `run_config_summary` + `run_config_json` in CSV. Dashboard UI should display summary/hash first and use JSON/report fallback only when CSV context is incomplete.
- Benchmark CSV `recipes` should be populated for all benchmark entrypoints (`labelstudio-benchmark`, `labelstudio-eval`, `bench run`) using pred-run manifest `recipe_count` first, then `processed_report_path` fallback.
- If historical benchmark rows predate that persistence path, use `cookimport benchmark-csv-backfill` to patch CSV `recipes/report_path/file_name` from benchmark manifests before regenerating the dashboard.
