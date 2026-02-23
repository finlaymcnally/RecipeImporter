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

## Test Modularity Rule

- `pytest.ini` is the source of truth for low-noise defaults (`-q`, no traceback/capture/summary, plain asserts, strict markers).
- With pytest 9.x, `-q` alone still emits per-test progress rows; keep `console_output_style = classic` in `pytest.ini` and keep `pytest_report_teststatus(...)` in `tests/conftest.py` suppressing pass/skip glyphs to avoid dot-flood output.
- Keep `tests/conftest.py:pytest_configure(...)` enforcing compact mode (`no_header`, `no_summary`, warnings suppressed, `-v/-vv` clamped) so manual `-o addopts=''` invocations do not reintroduce noisy separator floods; opt out only with `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1`.
- Domain markers are assigned centrally in `tests/conftest.py`; keep per-file marker mapping there so targeted runs stay stable.
- `tests/test_*.py` files are grouped under domain folders (`tests/analytics`, `tests/bench`, `tests/cli`, `tests/core`, `tests/ingestion`, `tests/labelstudio`, `tests/llm`, `tests/parsing`, `tests/staging`, `tests/tagging`).
- Path-sensitive tests should resolve shared roots via `tests/paths.py` (fixtures/tagging gold/docs examples) instead of `Path(__file__).parent`.
- Keep expensive files in the shared `slow` set and a tiny sanity slice in `smoke` for low-token checks.
- Failed runs should print `docs/*_log.md` hints from `tests/conftest.py` so debugging details live in docs, not noisy test output.

## CLI Discovery Rule

Interactive file discovery and direct staging intentionally differ:

- Interactive menu discovery (`cookimport` with no subcommand) scans only top-level files in `data/input`.
- Direct staging (`cookimport stage <folder>`) scans recursively under the folder.
- Interactive `labelstudio` import always recreates the resolved Label Studio project (`overwrite=True`, `resume=False`) and does not prompt for resume mode.
- Interactive `labelstudio` import no longer asks for upload confirmation; once scope/options are chosen, it proceeds directly to upload (after credential resolution).
- Interactive freeform `labelstudio` import prompts for AI prelabel mode (`off`, `strict`, `allow-partial`, plus advanced predictions modes) during the same prompt flow, then prompts for labeling style (`actual freeform` span mode vs `legacy, block based` mode); do not require leaving interactive mode for first-pass AI annotations.
- Interactive freeform `labelstudio` prelabel flow includes explicit Codex model selection followed by thinking effort selection (`none|minimal|low|medium|high|xhigh`); token-usage tracking is always enabled and should not be a prompt.
- Interactive and non-interactive `labelstudio` import must use the same status/progress callback wiring so long-running phases (especially AI prelabeling) show a live spinner/status update path.
- `labelstudio` resume semantics apply only when the target Label Studio project already exists; if a run creates a new project, do not reuse local manifest task IDs from older runs.
- Spinner/progress text for known-size worklists should include `<noun> X/Y` counters (for example `task`, `item`, `config`, `phase`) rather than phase-only text so operators can track throughput.
- Callback-driven CLI spinners (`labelstudio` import, benchmark import, bench run/sweep) should append elapsed seconds after prolonged unchanged phases (default threshold: 10s) so users can see that work is still running when a phase message is stale. When status text includes `<noun> X/Y`, the same spinner path should estimate ETA as average seconds-per-unit times remaining units.
- Interactive `labelstudio` export resolves credentials first, then lists project titles from Label Studio for selection, with manual entry fallback when discovery is unavailable. If the selected project has a detected task type, export uses that scope automatically and skips the separate scope prompt.
- Label Studio export (interactive and non-interactive) writes to a stable project root by default: `data/golden/<project_slug>/exports/...`; it uses prior manifests for project/scope resolution, not for export destination. `--run-dir` still forces export into a specific run.
- Interactive main menu is persistent: successful `import`, `labelstudio`, `labelstudio_export`, and `labelstudio_benchmark` actions all return to the main menu. The session exits only when the user selects `Exit`.
- Interactive select menus should be wired through `_menu_select` so numbering, shortcuts, and Esc-go-back behavior remain consistent.
- Interactive typed prompts in CLI flows should use `_prompt_text`, `_prompt_confirm`, or `_prompt_password` so `Esc` consistently maps to one-level back/cancel behavior.
- Questionary `text/password/confirm` prompts expose merged key bindings (`_MergedKeyBindings`) at runtime; `Esc` overrides must be attached via `merge_key_bindings(...)` (not `.add(...)` on `application.key_bindings`).
- Freeform interactive segment sizing (`segment_blocks`, `segment_overlap`, `segment_focus_blocks`, `target_task_count`) should route through `_prompt_freeform_segment_settings(...)` so `Esc` walks back one field instead of dropping to main menu.
- Interactive benchmark (`labelstudio_benchmark`) only offers `eval-only` when both discovery sets are non-empty: at least one `**/exports/freeform_span_labels.jsonl` and one `**/label_studio_tasks.jsonl` under `data/golden` or `data/output`. If either set is missing, it falls back directly to upload mode.
- Interactive Import and interactive benchmark upload both go through a per-run settings chooser (`global defaults`, `last run settings`, `change run settings`) before execution.
- Interactive benchmark eval-only mode must not apply/save pipeline run settings and should emit `Eval-only mode: no pipeline run settings applied.`
- Interactive benchmark upload resolves Label Studio credentials through `_resolve_interactive_labelstudio_settings(settings)` (env -> saved config -> prompt) before calling `labelstudio_benchmark(...)`.
- Benchmark upload should pass `auto_project_name_on_scope_mismatch=True` into `run_labelstudio_import(...)` so auto-named benchmark projects recover by suffixing project titles instead of failing on prior freeform/canonical scope collisions.
- Typer command functions that are called directly from Python (interactive helpers/tests) must keep runtime defaults as plain Python values, typically via `Annotated[..., typer.Option(...)] = <default>`; avoid relying on `param: T = typer.Option(...)` defaults in those call paths.
- Interactive `generate_dashboard` asks whether to open the dashboard in a browser, then runs `stats_dashboard(output_root=<settings.output_dir>, out_dir=<output_root>/.history/dashboard)` and returns to the main menu.
- Interactive `epub_race` is a main-menu action shown only when top-level `data/input` includes at least one `.epub`; it prompts for output/candidates (default output root: `data/output/EPUBextractorRace/<book_stem>`), then runs `cookimport epub race` behavior and returns to the menu.
- EPUB debug tooling lives under `cookimport epub ...` (sub-CLI module `cookimport/epubdebug`), and block/candidate debug commands must reuse production EPUB importer internals (`_extract_docpack`, `_detect_candidates`) to preserve stage/debug parity.

When debugging "file missing from menu" reports, check whether the file is nested inside `data/input`.

## Run Settings Source of Truth

- `cookimport/config/run_settings.py` is the canonical definition of per-run knobs (`RunSettings`), UI metadata, summary rendering, and stable hash generation.
- When a run-setting value changes split capability (for example `epub_extractor=markitdown`), update both split planners (`cookimport/cli.py:_plan_jobs`, `cookimport/labelstudio/ingest.py:_plan_parallel_convert_jobs`) and `compute_effective_workers(...)` together.
- EPUB unstructured tuning knobs (`epub_unstructured_html_parser_version`, `epub_unstructured_skip_headers_footers`, `epub_unstructured_preprocess_mode`) are part of canonical run settings and must propagate in both stage and benchmark prediction paths; do not wire them only in one flow.
- When `epub_extractor=auto` is supported, resolve it once in the parent orchestration layer (stage/benchmark prediction) and persist both `epub_extractor_requested` and `epub_extractor_effective` in run config/report surfaces.
- Auto-selection probing calls `EpubImporter._extract_docpack(...)` directly (without `convert(...)`), so any importer runtime state used by `_extract_docpack` must be initialized in `EpubImporter.__init__` or guarded with safe defaults.
- EPUB auto-selection metadata contract is explicit: stage/processed reports should persist `epubAutoSelection` + `epubAutoSelectedScore`, and analytics CSV should persist `epub_extractor_requested` + `epub_extractor_effective` + `epub_auto_selected_score` (dashboard reads these directly, CSV-first).
- Runtime env overrides for EPUB extraction options in prediction/stage helper flows must be scoped and restored after conversion; do not leak `C3IMP_EPUB_*` values across runs/tests.
- `stage(...)` should pass per-file effective extractor choices explicitly to workers (`stage_one_file` / `stage_epub_job`) instead of depending on persistent process-wide `C3IMP_EPUB_EXTRACTOR`.
- `cookimport/cli_ui/run_settings_flow.py` and `cookimport/cli_ui/toggle_editor.py` must derive editor rows/options from `RunSettings` metadata; do not maintain a separate hard-coded field list.
- `cookimport/cli_ui/toggle_editor.py` must keep the selected row in view for long lists (cursor-tracked viewport scrolling), so benchmark/LLM-heavy settings menus remain navigable in small terminals.
- Last-run snapshots are stored in `<output_dir>/.history/last_run_settings_{import|benchmark}.json` via `cookimport/config/last_run_store.py`.
- Schema evolution contract for stored run settings: missing keys default, unknown keys are ignored (warn once), and corrupt payloads degrade to `None` (treated as no saved run settings).
- codex-farm knobs (`llm_recipe_pipeline`, `llm_knowledge_pipeline`, `codex_farm_cmd`, `codex_farm_root`, `codex_farm_workspace_root`, `codex_farm_pipeline_pass1`, `codex_farm_pipeline_pass2`, `codex_farm_pipeline_pass3`, `codex_farm_pipeline_pass4_knowledge`, `codex_farm_context_blocks`, `codex_farm_knowledge_context_blocks`, `codex_farm_failure_mode`) must be wired through stage and benchmark prediction-generation paths, and persisted in run-config surfaces (manifest/report/history).
- `llm_recipe_pipeline` must default to `off`; codex-farm subprocess calls are opt-in only and should never run in default pipeline mode.
- codex-farm orchestration should pass explicit `--root`/`--workspace-root` when those run settings are provided, and `llm_manifest.json` should record the effective pass pipeline ids.
- Default local codex-farm recipe pass prompts live in `llm_pipelines/prompts/recipe.{chunking,schemaorg,final}.v1.prompt.md`; text-only tuning should happen there without touching orchestration code.
- For local codex-farm packs, pipeline JSON `prompt_template_path` / `output_schema_path` entries are the source of truth; avoid keeping duplicate filename schemes in `llm_pipelines/prompts/` that are not referenced by those pipeline specs.
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

## Label Studio Prelabel Rule

- Freeform prelabeling must derive final span offsets from task-local `segment_text` + `data.source_map.blocks[*].segment_start/end`; `block` mode uses block bounds directly and `span` mode resolves quotes against block text (with strict validation for optional absolute `start`/`end` fallbacks).
- Freeform prelabel flows must preserve `data.segment_text` exactly (no whitespace normalization) so exported offsets remain stable.
- Prompt text for freeform prelabel lives in `llm_pipelines/prompts/freeform-prelabel-full.prompt.md`; iterate prompt wording there and keep required placeholder tokens (`{{SEGMENT_ID}}`, `{{BLOCKS_JSON_LINES}}`, etc.) intact.
- Freeform prelabel granularity contract: `block` mode is legacy, block based full-block spans; `span` mode is actual freeform quote-anchored spans (`block_index` + `quote` + optional `occurrence`) with optional validated absolute fallback (`start`/`end`).
- Freeform context-vs-focus contract: `segment_blocks` controls context visibility, `segment_focus_blocks` controls which blocks may receive labels, focus windows should be centered inside each segment when possible (so context appears before and after), and prelabel runtime must enforce focus filtering parser-side (including absolute spans that cross non-focus blocks).
- Freeform target-task contract: when `target_task_count` is provided, resolve and persist both `segment_overlap_requested` and `segment_overlap_effective` in manifests; `segment_overlap` should reflect the effective runtime overlap.
- Freeform prelabel overlap floor: effective overlap must satisfy `segment_overlap_effective >= segment_blocks - segment_focus_blocks` so focus windows remain contiguous across tasks and do not leave uncovered block gaps.
- Freeform prelabel concurrency contract: task-level provider calls are bounded by `prelabel_workers` (default `4`), progress should still report `task X/Y` completions, and prompt logs/reports must remain deterministic per task id.
- Prompt text for actual freeform mode lives in `llm_pipelines/prompts/freeform-prelabel-span.prompt.md`; keep placeholder tokens intact.
- Actual freeform (`span`) prompts should provide block text once via `{{BLOCKS_WITH_FOCUS_MARKERS_JSON_LINES}}` with explicit context-before/context-after markers plus `<<<START_LABELING_BLOCKS_HERE>>>` / `<<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>>` focus boundaries; avoid duplicating focus blocks as a second full text payload list.
- Freeform canonical label names are `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `YIELD_LINE`, `TIME_LINE`, `RECIPE_NOTES`, `RECIPE_VARIANT`, `KNOWLEDGE`, `OTHER`; normalize legacy `TIP`/`NOTES`/`VARIANT` labels to those names.
- Codex prelabel invocations must use non-interactive CLI mode (`codex exec -`); plain `codex` is interactive and fails in pipeline subprocess calls without a TTY.
- Codex command resolution for prelabel is: explicit `--codex-cmd` -> `COOKIMPORT_CODEX_CMD` -> `codex exec -`.
- Interactive freeform prelabel should use that resolved command directly (no command chooser prompt) and display the resolved account email when available.
- Codex model resolution order for prelabel is: explicit `--codex-model` -> `COOKIMPORT_CODEX_MODEL` -> Codex config `model` (`~/.codex/config.toml`, `~/.codex-alt/config.toml`).
- Codex thinking effort for prelabel resolves from explicit command/CLI override first (`--codex-thinking-effort` / `--codex-reasoning-effort`, mapped to `model_reasoning_effort`), then Codex config `model_reasoning_effort`.
- Interactive prelabel model choices should be sourced from the selected command's Codex home cache metadata (`models_cache.json`) when available, with custom-id fallback.
- Prelabel runs should perform one model-access preflight probe before task loops; account/model mismatches should fail once up front with provider detail.
- Codex JSON `turn.failed` errors must be surfaced as provider failures (not collapsed into generic "no labels produced" parse misses).
- Token usage accounting for prelabel is always on and should be persisted as aggregate totals in `prelabel_report.json` (including resolved command/account metadata) without changing annotation semantics.
- Prelabel runs must persist `prelabel_prompt_log.md` in the run root (`data/golden/<timestamp>/labelstudio/<book_slug>/`) with one section per prompt containing full prompt text and prompt-context metadata/description for auditing.

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
- EPUB/PDF standalone knowledge-block analysis should emit `task X/Y` progress updates and uses bounded container-level parallelism controlled by `C3IMP_STANDALONE_ANALYSIS_WORKERS` (default `4`).
- Unstructured HTML parser `v2` requires `body.Document`/`div.Page`-style inputs; adapter-level compatibility wrapping is required before `partition_html(..., html_parser_version=\"v2\")` on generic EPUB XHTML.
- `.job_parts` should be removed after successful merge; if it remains, treat it as evidence of merge failure/interruption.
- Split-merge paths that run codex-farm must rebuild merged `raw/<importer>/<source_hash>/full_text.json` and rebase block indices before pass1 bundle generation.
- `stage` builds and passes a base `MappingConfig` to workers, so worker conversion typically skips importer `inspect()` unless planning/split metadata requires it.
- Topic/Tip writer paths may call file-hash resolution many times; when provenance lacks `file_hash`, hashing must be cached by source file metadata to avoid repeated whole-file reads in high-cardinality merge runs.
- Any payload returned from split workers (especially `ConversionResult.raw_artifacts[*].metadata`) must stay process-pickle-safe primitives; module objects in metadata will fail split benchmark/stage merges with `cannot pickle 'module' object`.

## Benchmark Contract Rule

- Freeform benchmark scoring (`labelstudio-benchmark`, interactive eval-only, and `bench run`) evaluates prediction task artifacts (`label_studio_tasks.jsonl`) against freeform gold spans (`freeform_span_labels.jsonl`), not staged cookbook outputs; optional processed outputs written during benchmark are review artifacts only.
- Freeform eval dedupes overlapping gold spans by default before scoring using `(source_hash, source_file, start_block_index, end_block_index)` keys. If duplicate groups disagree on label, use majority-vote label resolution; if label counts tie, drop that gold group from scoring and report it in `eval_report.json` `gold_dedupe.conflicts`.
- Non-interactive `labelstudio-benchmark` supports an explicit offline path via `--no-upload`; this mode must skip Label Studio credential resolution and never call upload APIs.
- Run-producing flows must emit `run_manifest.json` so source identity (`path` + `source_hash`), effective config, and key artifacts are inspectable without reading code.
- When codex-farm is enabled for stage/pred-run, report + manifest payloads should expose `llmCodexFarm`/`llm_codex_farm` metadata, and deterministic fallback semantics must be explicit (`codex_farm_failure_mode=fail|fallback`).

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
