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
12. `docs/12-plans`
13. `docs/13-tasks`
14. `docs/14-understandings`

When adding new top-level docs sections, use the same `NN-name` convention and update `docs/README.md`.

## CLI Discovery Rule

Interactive file discovery and direct staging intentionally differ:

- Interactive menu discovery (`cookimport` with no subcommand) scans only top-level files in `data/input`.
- Direct staging (`cookimport stage <folder>`) scans recursively under the folder.
- Interactive `labelstudio` import always recreates the resolved Label Studio project (`overwrite=True`, `resume=False`) and does not prompt for resume mode.
- Interactive `labelstudio` import no longer asks for upload confirmation; once scope/options are chosen, it proceeds directly to upload (after credential resolution).
- Interactive `labelstudio` export resolves credentials first, then lists project titles from Label Studio for selection, with manual entry fallback when discovery is unavailable. If the selected project has a detected task type, export uses that scope automatically and skips the separate scope prompt.
- Label Studio export (interactive and non-interactive) creates a fresh timestamped run folder by default: `data/golden/<timestamp>/labelstudio/<project_slug>/exports/...`; it uses prior manifests for project/scope resolution, not for export destination. `--run-dir` still forces export into a specific run.
- Interactive main menu is persistent: successful `import`, `labelstudio`, `labelstudio_export`, and `labelstudio_benchmark` actions all return to the main menu. The session exits only when the user selects `Exit`.
- Interactive select menus should be wired through `_menu_select` so numbering, shortcuts, and Backspace-go-back behavior remain consistent.
- Interactive benchmark (`labelstudio_benchmark`) only offers `eval-only` when both discovery sets are non-empty: at least one `**/exports/freeform_span_labels.jsonl` and one `**/label_studio_tasks.jsonl` under `data/golden` or `data/output`. If either set is missing, it falls back directly to upload mode.
- Interactive benchmark upload prompts for EPUB extractor (`unstructured` or `legacy`) before credential resolution and passes that choice into `labelstudio_benchmark(...)`.
- Interactive benchmark upload resolves Label Studio credentials through `_resolve_interactive_labelstudio_settings(settings)` (env -> saved config -> prompt) before calling `labelstudio_benchmark(...)`.
- Typer command functions that are called directly from Python (interactive helpers/tests) must keep runtime defaults as plain Python values, typically via `Annotated[..., typer.Option(...)] = <default>`; avoid relying on `param: T = typer.Option(...)` defaults in those call paths.
- Interactive `generate_dashboard` asks whether to open the dashboard in a browser, then runs `stats_dashboard(output_root=<settings.output_dir>, out_dir=<output_root>/.history/dashboard)` and returns to the main menu.

When debugging "file missing from menu" reports, check whether the file is nested inside `data/input`.

## Report Output Convention

- The canonical stage report output path is set by `cookimport/staging/writer.py`:
  - `<run_root>/<workbook_slug>.excel_import_report.json`
- `cookimport/core/reporting.py` includes a legacy `ReportBuilder` that writes under `reports/`; treat it as legacy unless explicitly wired into active runtime flows.
- When updating docs about report locations, verify `stage()` and split-merge paths in `cookimport/cli.py` before documenting.
- Report metadata fields that must be consistent across normal and split runs (for example `importerName`, `runConfig`) must be set in both:
  - `cookimport/cli_worker.py` (single-file writer path)
  - `cookimport/cli.py:_merge_split_jobs` (split merge writer path)

## Ingestion Split/Merge Rule

- Split PDF/EPUB workers write raw artifacts to `.job_parts/<workbook>/job_<index>/raw`, then the main process merges IDs/outputs and moves raw artifacts into run `raw/`.
- `.job_parts` should be removed after successful merge; if it remains, treat it as evidence of merge failure/interruption.
- `stage` builds and passes a base `MappingConfig` to workers, so worker conversion typically skips importer `inspect()` unless planning/split metadata requires it.
- Topic/Tip writer paths may call file-hash resolution many times; when provenance lacks `file_hash`, hashing must be cached by source file metadata to avoid repeated whole-file reads in high-cardinality merge runs.
- Any payload returned from split workers (especially `ConversionResult.raw_artifacts[*].metadata`) must stay process-pickle-safe primitives; module objects in metadata will fail split benchmark/stage merges with `cannot pickle 'module' object`.

## Benchmark Contract Rule

- Freeform benchmark scoring (`labelstudio-benchmark`, interactive eval-only, and `bench run`) evaluates prediction task artifacts (`label_studio_tasks.jsonl`) against freeform gold spans (`freeform_span_labels.jsonl`), not staged cookbook outputs; optional processed outputs written during benchmark are review artifacts only.

## Analytics Caveats

- Stage run folders are timestamped as `YYYY-MM-DD_HH.MM.SS`, but `perf_report.resolve_run_dir()` currently matches `YYYY-MM-DD-HH-MM-SS`; auto-latest selection for `cookimport perf-report` may miss normal stage folders unless `--run-dir` is supplied.
- End-of-stage history append currently writes to `history_path(DEFAULT_OUTPUT)` even when `cookimport stage` uses a custom `--out`; analytics CSV/dashboard reviews should verify whether rows landed in `data/output/.history/performance_history.csv` or expected custom roots.
- Dashboard `index.html` embeds dashboard JSON inline (in addition to `assets/dashboard_data.json`) so opening via `file://` works even when browser local `fetch()` is blocked.
- Dashboard timestamp ordering (recent runs/benchmarks and latest benchmark picks) must parse timestamps before sorting because history mixes `YYYY-MM-DDTHH:MM:SS` and `YYYY-MM-DD_HH.MM.SS` formats.
- Dashboard frontend timestamp parsing should explicitly parse timestamp components for those two canonical formats; avoid relying only on `Date.parse(...)` for local `file://` dashboards.
- Throughput dashboard should keep two complementary views: run/date history and file-over-time trend; file trend grouping key is `StageRecord.file_name`.
- Benchmark dashboard enrichment should read `manifest.json` and `coverage.json` from either eval root or `prediction-run/`; `labelstudio-benchmark` co-locates prediction artifacts under `prediction-run/`.
- When combining benchmark rows from JSON + CSV, dedupe by eval artifact directory and merge fields; CSV timestamps can differ from eval-folder timestamps for the same run.
- Dashboard benchmark collection should ignore pytest temp eval artifact paths (`.../pytest-<n>/test_*/eval`) so local Python test runs do not pollute benchmark history.
