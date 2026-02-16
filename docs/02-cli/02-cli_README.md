---
summary: "Detailed CLI and interactive-mode reference, including all commands, options, and environment variables."
read_when:
  - When changing command wiring, defaults, or interactive menu flows
  - When adding a new CLI command or command group
---

# CLI Section Reference

Primary command wiring lives in `cookimport/cli.py`.

## Entry Points

`pyproject.toml` defines four CLI scripts:

- `cookimport` -> `cookimport.cli:app`
- `import` -> `cookimport.entrypoint:main`
- `C3import` -> `cookimport.entrypoint:main`
- `C3imp` -> `cookimport.c3imp_entrypoint:main`

Remember to do source .venv/bin/activate

Behavior differences:

- `cookimport` with no subcommand enters interactive mode.
- `import` / `C3import`:
  - no args: runs `stage(path=data/input)` immediately (non-interactive)
  - one positive integer arg: treated as `--limit` and runs `stage(path=data/input, limit=N)`
  - anything else: falls back to normal Typer command parsing (`app()`)
- `C3imp`:
  - one positive integer arg: sets `C3IMP_LIMIT=N`, clears args, then enters interactive mode
  - otherwise: falls back to normal Typer command parsing (`app()`)

## Interactive Mode Walkthrough

```text
Legend:
  [X] = matching labeled section below
  ~~> = one-level Backspace navigation (only on _menu_select prompts)

[A] Enter interactive mode (`cookimport` with no subcommand)
  |
  v
[B] Startup (load settings + scan top-level data/input files)
  |
  v
[C] Main Menu
  +--> [D] Import -------------------------> stage(...) ------------------> [C]
  |
  +--> [E] Label Studio import
  |       `--> [E] Unified prompt + artifact generation + upload flow -> run_labelstudio_import(...) -> [C]
  |
  +--> [F] Label Studio export ------------> run_labelstudio_export(...) -> [C]
  |
  +--> [G] Benchmark vs freeform gold
  |       +--> [G1] Eval-only -------------> labelstudio-eval -----------> [C]
  |       `--> [G2] Upload ----------------> labelstudio-benchmark ------> [C]
  |
  +--> [H] Generate dashboard -------------> stats-dashboard -------------> [C]
  |
  +--> [I] Settings -----------------------> save `cookimport.json` ------> [C]
  |
  `--> [Z] Exit (user selects Exit)
```

### [A] Enter Interactive Mode

Interactive mode is entered when `cookimport` is run without a subcommand.

### [B] Startup

Startup behavior:

1. Loads settings from `cookimport.json` (or defaults if missing/invalid).
2. Sets `input_folder = data/input`.
3. Scans only top-level files in `data/input` for importer support (not recursive).
4. Builds the main menu choices.
5. Uses Backspace as one-level "go back" in prompts wired through `_menu_select`.

Important divergence to remember:
- interactive file selection is top-level only, but `cookimport stage <folder>` is recursive when a folder path is passed directly.

### [C] Main Menu

Menu options:

- `Import files from data/input - convert to schema.org + cookbook3 outputs`
- `Label Studio benchmark import - create labeling tasks from one source`
- `Label Studio export - pull finished labels into golden artifacts`
- `Benchmark against labeled freeform export - re-score existing runs or generate new predictions`
- `Generate dashboard - build lifetime stats dashboard HTML`
- `Settings - tune worker/OCR/output defaults`
- `Exit - close the tool`

Availability rule:

- `Import` and `Label Studio benchmark import` only appear when at least one supported top-level file exists in `data/input`.
- `inspect` remains available as a direct command (`cookimport inspect <path>`), not as an interactive menu action.

Menu numbering and shortcuts:

- `_menu_select` now shows Questionary shortcut labels on all select-style menus (for example `1)`, `2)`, ...).
- Numeric shortcuts (`1-9`, `0`) select immediately in interactive menus; non-numeric shortcuts still move focus and can be confirmed with Enter.

### [I] Settings

`Settings` opens a loop and writes each accepted change back to `cookimport.json` immediately.

Config keys and defaults:

- `workers` (default `7`)
- `pdf_split_workers` (default `7`)
- `epub_split_workers` (default `7`)
- `epub_extractor` (default `unstructured`)
- `ocr_device` (default `auto`)
- `ocr_batch_size` (default `1`)
- `output_dir` (default `data/output`)
- `label_studio_url` (default unset; populated after first interactive Label Studio prompt)
- `label_studio_api_key` (default unset; populated after first interactive Label Studio prompt)
- `pdf_pages_per_job` (default `50`)
- `epub_spine_items_per_job` (default `10`)
- `warm_models` (default `false`)

What each setting affects:

- `workers`, split workers, page/spine split size: `stage` and benchmark import parallelism/sharding.
- `epub_extractor`: runtime extractor choice (`unstructured` vs `legacy`) via `C3IMP_EPUB_EXTRACTOR`.
- `ocr_device`, `ocr_batch_size`: OCR path for PDFs.
- `output_dir`: interactive `stage` target output root.
- `label_studio_url`, `label_studio_api_key`: interactive Label Studio import/export credential defaults.
- `warm_models`: preloads SpaCy, ingredient parser, and OCR model before staging.

### [D] Import Flow

`Import` steps:

1. Prompt for `Import All` or one selected file from top-level `data/input`.
2. Applies `C3IMP_EPUB_EXTRACTOR=<settings.epub_extractor>`.
3. Calls `stage(...)` using settings values for workers/OCR/split/warm-models.
4. Uses `limit` only if `C3IMP_LIMIT` was set before entering interactive mode.
5. Prints `Outputs written to: <run_folder>`.
6. Returns to the main menu after successful import.

### [E] Label Studio Import Flow

1. Choose a source file.
   - The menu shows supported files from `data/input`.
   - Pick the file you want to create labeling tasks from.
2. Enter a project name (or leave it blank).
   - If blank, the tool uses a name based on the file name.
   - If a project with that final name already exists, this flow replaces it.
3. Choose task type (`task_scope`).
   - You are choosing what kind of labeling jobs the program will create.
   - There are 5 practical choices:
   - `pipeline` + `structural`:
   - Creates bigger recipe-section tasks.
   - Use this when you want a faster, higher-level labeling pass.
   - `pipeline` + `atomic`:
   - Creates smaller, line-like tasks.
   - Use this when you want detailed labels on fine-grained chunks.
   - `pipeline` + `both`:
   - Creates both structural and atomic tasks in one run.
   - Use this when you want broad coverage and can label more tasks.
   - `canonical-blocks`:
   - Creates one task per extracted text block, with one label per block.
   - Asks for `context_window` (number `>= 0`), which controls how much nearby text is shown for context.
   - Use this when you want complete block-by-block classification.
   - `freeform-spans`:
   - Creates segment tasks where you highlight exact text ranges (spans).
   - Asks for `segment_blocks` (number `>= 1`) and `segment_overlap` (number `>= 0`) to control segment size and overlap.
   - Use this when you need precise span annotations for downstream freeform export/eval.
   - In all 5 cases, the output is a set of Label Studio tasks that gets uploaded and later exported/evaluated with the matching scope.
4. Enter Label Studio URL and API key if needed.
   - If `LABEL_STUDIO_URL` and `LABEL_STUDIO_API_KEY` are set, prompts are skipped.
   - Otherwise, interactive mode uses saved `cookimport.json` values when present.
   - If still missing, you are prompted once and the entered values are saved to `cookimport.json` for future interactive runs.
5. The tool builds tasks on your machine.
   - It prepares text/chunk or block/segment tasks based on your scope choice.
   - It writes run files under `data/golden`:
   - `label_studio_tasks.jsonl`
   - `coverage.json`
   - `extracted_archive.json`
   - `extracted_text.txt`
   - `manifest.json`
6. The tool uploads tasks to Label Studio automatically.
   - No extra "are you sure?" prompt in this interactive flow.
   - Upload is batched in groups of 200 tasks.
   - `manifest.json` is updated with project ID, upload count, and project URL.
7. Review the summary shown in terminal.
   - You get a quick recap of project/tasks/run location.
8. Interactive mode returns to the main menu after the flow completes.

### [F] Label Studio Export Flow

`Label Studio export` steps:

1. Uses `LABEL_STUDIO_URL` / `LABEL_STUDIO_API_KEY` env vars when present; otherwise prompts for them.
   - If env vars are unset, interactive mode reuses saved `cookimport.json` values before prompting.
   - Newly prompted values are saved to `cookimport.json`.
2. Fetches Label Studio projects and shows a project picker.
   - In plain English: choose an existing project title instead of typing it.
   - The picker shows each project with a detected type tag (for example `pipeline`, `canonical-blocks`, `freeform-spans`) when available.
   - Includes a manual-entry option when needed.
3. Falls back to manual project-name entry when project discovery fails (or no projects exist).
4. Uses the selected project's detected type as `export_scope` when available.
   - If the selected project type is `unknown` (or project name is typed manually), interactive mode prompts for `export_scope` (`pipeline`, `canonical-blocks`, `freeform-spans`).
5. Calls `run_labelstudio_export(...)` with `output_dir=data/golden`.
   - By default, export writes to a fresh timestamped folder: `data/golden/<timestamp>/labelstudio/<project_slug>/exports/`.
   - If `--run-dir` is supplied in non-interactive mode, export writes to that run directory.
6. Prints export summary path and returns to the main menu.

### [G] Benchmark vs Freeform Gold Flow

`Benchmark against labeled freeform export` supports two paths:

- `eval-only` when both gold exports and prediction runs exist.
- `upload` mode (default/fallback) for generating fresh predictions.
- If either artifact set is missing, interactive mode skips the mode picker and goes straight to upload mode.

Why both paths exist:

1. Benchmark always needs two inputs:
- labeled `gold` spans (`freeform_span_labels.jsonl`)
- pipeline `predictions` (`label_studio_tasks.jsonl` run directory)
2. `eval-only` is the "re-score" path:
- no new upload
- no new prediction generation
- fastest way to compare an existing prediction run against updated gold labels or updated eval settings.
3. `upload` is the "make predictions first" path:
- creates a fresh prediction run
- uploads tasks to Label Studio
- then evaluates those fresh predictions against gold.

Typical reasons to use `eval-only` again on an old run:

- You corrected or expanded freeform gold labels and want updated scores.
- You changed eval settings (`overlap_threshold` or `force_source_match`) and want a fresh report on the same predictions.
- You changed evaluator/report formatting and want regenerated artifacts without creating new predictions.

### [G1] Eval-Only Branch

1. Select freeform gold export (`**/exports/freeform_span_labels.jsonl`).
2. Select prediction run (`**/label_studio_tasks.jsonl` run directory).
3. Runs `labelstudio-eval scope=freeform-spans` into `data/golden/eval-vs-pipeline/<timestamp>`.
4. Returns to the main menu.

### [G2] Upload Branch

1. Resolves Label Studio credentials from env (`LABEL_STUDIO_URL` / `LABEL_STUDIO_API_KEY`) or saved interactive settings; if still missing, prompts and saves values to `cookimport.json`.
2. Calls `labelstudio-benchmark(...)` with settings-driven parallelism/splitting values.
3. Returns to the main menu on completion.

### [H] Generate Dashboard Flow

1. Prompts `Open dashboard in your browser after generation?`.
2. Runs `stats-dashboard` using the interactive `output_dir` setting as `--output-root`.
3. Writes dashboard files to `<output_dir>/.history/dashboard`.
4. Opens `index.html` automatically when you answer `Yes`.
5. Returns to the main menu on completion.

### [Z] Exit Conditions

Interactive mode exits when:

- user selects `Exit` from the main menu.

## Command Surface

Top-level command groups:

- `cookimport stage`
- `cookimport inspect`
- `cookimport labelstudio-import`
- `cookimport labelstudio-export`
- `cookimport labelstudio-eval`
- `cookimport labelstudio-benchmark`
- `cookimport perf-report`
- `cookimport stats-dashboard`
- `cookimport bench <validate|run|sweep|knobs>`
- `cookimport tag-catalog export`
- `cookimport tag-recipes <debug-signals|suggest|apply>`

Every command supports `--help`.

## Command Reference

### `cookimport stage PATH`

Stages one file or all files under a folder (recursive for folder input). Always creates a timestamped run folder under `--out` using format `YYYY-MM-DD_HH.MM.SS`.

Arguments:

- `PATH` (required): file or folder to stage.

Options:

- `--out PATH` (default `data/output`): output root.
- `--mapping PATH`: explicit mapping config path.
- `--overrides PATH`: explicit parsing overrides path.
- `--limit, -n INTEGER>=1`: limit recipes/tips per file.
- `--ocr-device TEXT` (default `auto`): `auto|cpu|cuda|mps`.
- `--ocr-batch-size INTEGER>=1` (default `1`): pages per OCR model call.
- `--pdf-pages-per-job INTEGER>=1` (default `50`): page shard size for PDF splitting.
- `--epub-spine-items-per-job INTEGER>=1` (default `10`): spine-item shard size for EPUB splitting.
- `--warm-models` (default `false`): preload heavy models before processing.
- `--workers, -w INTEGER>=1` (default `7`): total process pool workers.
- `--pdf-split-workers INTEGER>=1` (default `7`): max workers for one split PDF.
- `--epub-split-workers INTEGER>=1` (default `7`): max workers for one split EPUB.
- `--epub-extractor TEXT` (default `unstructured`): `unstructured|legacy`; exported to `C3IMP_EPUB_EXTRACTOR` for importer runtime.

Split-merge progress detail:
- After split workers finish, the worker dashboard `MainProcess` row now advances through merge phases (payload merge, ID reassignment, output writes, raw merge) instead of staying on a single static `Merging ...` label.

### `cookimport inspect PATH`

Inspects importer layout guesses for one file.

Arguments:

- `PATH` (required): file to inspect.

Options:

- `--out PATH` (default `data/output`): where mapping stubs are written if enabled.
- `--write-mapping` (default `false`): writes `mappings/<stem>.mapping.yaml`.

### `cookimport perf-report`

Builds a per-file timing summary from conversion reports.

Options:

- `--run-dir PATH`: specific run folder to summarize (defaults to latest under `--out-dir`).
- `--out-dir PATH` (default `data/output`): output root used for discovery and history CSV location.
- `--write-csv / --no-csv` (default `--write-csv`): append summary rows to history CSV or skip.

### `cookimport stats-dashboard`

Builds static lifetime dashboard HTML from output/golden data.

Options:

- `--output-root PATH` (default `data/output`): staged import root.
- `--golden-root PATH` (default `data/golden`): benchmark/golden artifacts root.
- `--out-dir PATH` (default `data/output/.history/dashboard`): dashboard output directory.
- `--open` (default `false`): opens generated HTML in default browser.
- `--since-days INTEGER`: include only recent runs.
- `--scan-reports` (default `false`): force scanning per-file report JSON instead of cached summaries.

### `cookimport labelstudio-import PATH`

Creates Label Studio tasks from one source file.

Arguments:

- `PATH` (required): source file to import.

Options:

- `--output-dir PATH` (default `data/golden`): artifact root.
- `--pipeline TEXT` (default `auto`): importer selection.
- `--project-name TEXT`: explicit Label Studio project name.
- `--chunk-level TEXT` (default `both`): `structural|atomic|both`.
- `--task-scope TEXT` (default `pipeline`): `pipeline|canonical-blocks|freeform-spans`.
- `--context-window INTEGER>=0` (default `1`): canonical scope context window.
- `--segment-blocks INTEGER>=1` (default `40`): freeform segment size.
- `--segment-overlap INTEGER>=0` (default `5`): freeform overlap.
- `--overwrite / --resume` (default `--resume`): recreate or resume project.
- `--label-studio-url TEXT`: explicit Label Studio URL.
- `--label-studio-api-key TEXT`: explicit Label Studio API key.
- `--allow-labelstudio-write / --no-allow-labelstudio-write` (default disabled): required gate for upload.
- `--limit, -n INTEGER>=1`: cap chunks generated.
- `--sample INTEGER>=1`: randomly sample chunks.

Hard requirement:

- Upload is blocked unless `--allow-labelstudio-write` is set.

### `cookimport labelstudio-export`

Exports completed labels to golden-set artifacts.

Options:

- `--project-name TEXT` (required): Label Studio project name.
- `--output-dir PATH` (default `data/golden`): output root.
- `--run-dir PATH`: export from a specific run directory.
- `--export-scope TEXT` (default `pipeline`): `pipeline|canonical-blocks|freeform-spans`.
- `--label-studio-url TEXT`: explicit Label Studio URL.
- `--label-studio-api-key TEXT`: explicit Label Studio API key.

### `cookimport labelstudio-eval SCOPE`

Scores prediction spans against canonical/freeform gold labels.

Arguments:

- `SCOPE` (required): `canonical-blocks` or `freeform-spans`.

Options:

- `--pred-run PATH` (required): prediction run directory (must contain `label_studio_tasks.jsonl`).
- `--gold-spans PATH` (required): gold JSONL file.
- `--output-dir PATH` (required): eval artifact directory.
- `--overlap-threshold FLOAT 0..1` (default `0.5`): Jaccard match threshold.
- `--force-source-match` (default `false`): ignore source identity checks while matching spans.

### `cookimport labelstudio-benchmark`

One-shot prediction+eval flow against freeform gold spans.

Behavior note:

- Non-interactive `cookimport labelstudio-benchmark` is upload-first: it generates a fresh prediction run, uploads, then evaluates.
- Re-scoring an old prediction run without upload is done with `cookimport labelstudio-eval --pred-run ... --gold-spans ...`.
- Interactive mode (`cookimport` -> Benchmark) can expose an `eval-only` branch that wraps this re-score workflow when both artifacts are discoverable.

Options:

- `--gold-spans PATH`: freeform gold file; if omitted, prompt from discovered exports.
- `--source-file PATH`: source file to re-import for predictions; if omitted, prompt/infer.
- `--output-dir PATH` (default `data/golden`): scratch root for prediction import artifacts.
- `--processed-output-dir PATH` (default `data/output`): root for staged cookbook outputs generated during benchmark.
- `--eval-output-dir PATH`: destination for benchmark report artifacts.
- `--overlap-threshold FLOAT 0..1` (default `0.5`): match threshold.
- `--force-source-match` (default `false`): ignore source identity checks while matching.
- `--pipeline TEXT` (default `auto`): importer selection.
- `--chunk-level TEXT` (default `both`): `structural|atomic|both`.
- `--project-name TEXT`: explicit prediction project name.
- `--allow-labelstudio-write / --no-allow-labelstudio-write` (default disabled): required gate for upload.
- `--overwrite / --resume` (default `--resume`): recreate prediction project or resume.
- `--label-studio-url TEXT`: explicit Label Studio URL.
- `--label-studio-api-key TEXT`: explicit Label Studio API key.
- `--workers INTEGER>=1` (default `7`): prediction import process workers.
- `--pdf-split-workers INTEGER>=1` (default `7`): PDF split workers for prediction import.
- `--epub-split-workers INTEGER>=1` (default `7`): EPUB split workers for prediction import.
- `--pdf-pages-per-job INTEGER>=1` (default `50`): PDF shard size.
- `--epub-spine-items-per-job INTEGER>=1` (default `10`): EPUB shard size.

Hard requirement:

- Upload is blocked unless `--allow-labelstudio-write` is set.

### `cookimport bench validate`

Validates a bench suite manifest.

Options:

- `--suite PATH` (required): suite JSON path.

### `cookimport bench run`

Runs offline benchmark suite and writes report/metrics/iteration packet.

Options:

- `--suite PATH` (required): suite JSON path.
- `--out-dir PATH` (default `data/golden/bench/runs`): run output root.
- `--baseline PATH`: prior run directory for deltas.
- `--config PATH`: knob config JSON file.

### `cookimport bench sweep`

Runs random/configured sweep over suite knobs.

Options:

- `--suite PATH` (required): suite JSON path.
- `--out-dir PATH` (default `data/golden/bench/runs`): sweep output root.
- `--budget INTEGER>=1` (default `25`): max configurations to evaluate.
- `--seed INTEGER` (default `42`): RNG seed.
- `--objective TEXT` (default `coverage`): objective name (`coverage` or `precision`).

### `cookimport bench knobs`

Lists currently registered tunable knobs and defaults.

Options:

- no command-specific options.

### `cookimport tag-catalog export`

Exports DB-backed tag catalog to JSON.

Options:

- `--db-url TEXT` (or `COOKIMPORT_DATABASE_URL`): Postgres connection string.
- `--out PATH` (required): output JSON path.

### `cookimport tag-recipes debug-signals`

Prints the signal pack used by tagging logic.

Options:

- `--draft PATH`: staged draft JSON input.
- `--db-url TEXT` (or `COOKIMPORT_DATABASE_URL`): Postgres connection string.
- `--recipe-id TEXT`: recipe UUID for DB fetch.

Runtime rule:

- Must provide `--draft` OR (`--db-url` and `--recipe-id`).

### `cookimport tag-recipes suggest`

Runs deterministic tagging and optional LLM second pass on draft files.

Options:

- `--draft PATH`: single draft JSON.
- `--draft-dir PATH`: directory of draft JSON files (recursive).
- `--catalog-json PATH` (required): tag catalog JSON.
- `--out-dir PATH`: where to write per-recipe `*.tags.json`.
- `--explain` (default `false`): include evidence text in output.
- `--limit INTEGER`: cap number of recipes processed.
- `--llm` (default `false`): enable LLM second pass for missing categories.

Runtime rule:

- Must provide `--draft` or `--draft-dir`.

### `cookimport tag-recipes apply`

Applies suggested tags to DB records (dry-run by default).

Options:

- `--db-url TEXT` (or `COOKIMPORT_DATABASE_URL`): Postgres connection string.
- `--recipe-id TEXT`: single recipe UUID.
- `--catalog-json PATH` (required): tag catalog JSON.
- `--apply` (default `false`): actually write tag assignments.
- `--yes, -y` (default `false`): skip per-recipe confirmation prompts.
- `--explain` (default `false`): show evidence.
- `--min-confidence FLOAT`: filter suggestions below threshold.
- `--llm` (default `false`): enable LLM second pass.
- `--import-batch-id TEXT`: batch filter for DB selection.
- `--source TEXT`: source filter for DB selection.
- `--limit INTEGER`: max recipes in batch mode (defaults to `100` internally when omitted).

## Environment Variables

CLI-relevant environment variables:

- `C3IMP_LIMIT`: used by interactive mode callback. If set to an integer, interactive import uses it as `stage --limit`.
- `C3IMP_EPUB_EXTRACTOR`: EPUB extractor switch (`unstructured` or `legacy`) read at runtime by the EPUB importer.
- `LABEL_STUDIO_URL`: default Label Studio URL when `--label-studio-url` is omitted.
- `LABEL_STUDIO_API_KEY`: default Label Studio API key when `--label-studio-api-key` is omitted.
- `COOKIMPORT_DATABASE_URL`: DB URL fallback for `tag-catalog export`, `tag-recipes debug-signals`, and `tag-recipes apply`.
- `COOKIMPORT_SPACY`: optional parser signal toggle (`1|true|yes`) when parsing overrides do not explicitly set SpaCy behavior.
- `COOKIMPORT_CACHE_DIR`: preferred cache root for OCR model/artifact caches.
- `XDG_CACHE_HOME`: fallback cache root when `COOKIMPORT_CACHE_DIR` is unset.
- `DOCTR_MULTIPROCESSING_DISABLE`: can force docTR multiprocessing off; may also be set automatically when shared-memory constraints are detected.

Precedence notes:

- For Label Studio creds: CLI flags win over environment variables.
- For interactive Label Studio import/export creds: environment variables win over saved `cookimport.json` credentials.
- For EPUB extractor: explicit `stage --epub-extractor` or interactive setting writes `C3IMP_EPUB_EXTRACTOR` for that run.
- For tag DB URL: `--db-url` wins; env var is fallback.

## Merged Discovery Provenance (`docs/understandings`)

Merged source:
- `2026-02-15_21.04.54-cli-interactive-flow-map.md`

Preserved points:
- `cookimport` enters interactive mode only when no subcommand is invoked.
- `import` / `C3import` wrappers are batch-first shortcuts (no-arg path runs `stage(data/input)` immediately).
- Interactive import `limit` comes from `C3IMP_LIMIT` (for example via `C3imp <N>`), not a separate interactive prompt.
- Non-interactive Label Studio write paths remain explicitly gated by `--allow-labelstudio-write`.
- Interactive Label Studio import and interactive benchmark upload do not ask extra upload-confirmation questions; once the flow/mode is chosen, upload proceeds after credential resolution.

## Merged Task Specs (`docs/tasks`)

Task-spec files were previously kept under `docs/tasks/` and are now merged here so interactive CLI behavior changes, constraints, and verification evidence stay in one place.

### 2026-02-15_21.28.04 - remove-interactive-inspect-menu

Source task file:
- `docs/tasks/2026-02-15_21.28.04 - remove-interactive-inspect-menu.md`

Problem captured:
- Interactive main menu offered `Inspect`, but this path was not useful for the cleanup pass and created docs/menu drift.

Behavior contract preserved:
- Interactive main menu no longer includes `inspect`.
- Direct command `cookimport inspect PATH` remains available.
- CLI docs reflect the menu removal (and no standalone interactive inspect flow).

Verification and evidence preserved:
- Regression test: `test_interactive_main_menu_does_not_offer_inspect` in `tests/test_labelstudio_benchmark_helpers.py`.
- Task record states fail-before (menu still included `inspect`) and pass-after once the interactive inspect branch was removed from `cookimport/cli.py`.

Constraints and rollback notes:
- Keep non-interactive inspect tooling intact.
- Rollback path was to restore the interactive inspect branch and update docs/tests in the same change.

### 2026-02-15_21.35.54 - interactive-labelstudio-import-auto-overwrite

Source task file:
- `docs/tasks/2026-02-15_21.35.54 - interactive-labelstudio-import-auto-overwrite.md`

Problem captured:
- Interactive Label Studio import prompted overwrite/resume each run, which led to accidental resume paths and confusing exits.

Behavior contract preserved:
- Interactive `labelstudio` import no longer prompts `Overwrite existing project if it exists?`.
- Interactive path always calls import with `overwrite=True` and `resume=False`.
- Non-interactive `cookimport labelstudio-import` flags (`--overwrite/--resume`) remain unchanged.

Verification and evidence preserved:
- Regression test: `test_interactive_labelstudio_import_forces_overwrite_without_prompt`.
- Full helper test module run was also required by the task record.
- Task record preserves fail-before (prompt appeared) and pass-after once interactive flow forced overwrite mode.

Constraints and rollback notes:
- Auto-overwrite applies only inside the interactive `action == "labelstudio"` flow.
- Rollback path was to reintroduce prompt-driven overwrite/resume selection in interactive mode.

### 2026-02-15_22.00.23 - interactive-labelstudio-export-project-picker

Source task file:
- `docs/tasks/2026-02-15_22.00.23 - interactive-labelstudio-export-project-picker.md`

Problem captured:
- Interactive export required manual project-name typing, which was slow/error-prone when many similarly named projects existed.

Behavior contract preserved:
- Interactive export resolves Label Studio credentials first.
- It then attempts project-title discovery and shows a picker UI.
- Manual-entry fallback remains available.
- If discovery fails or returns no projects, flow falls back to manual entry.
- Export-scope selection and `run_labelstudio_export(...)` routing remain unchanged.

Verification and evidence preserved:
- Tests in `tests/test_labelstudio_benchmark_helpers.py` cover export routing + picker helper + fallback behavior.
- Task record includes command:
  - `. .venv/bin/activate && pytest -q tests/test_labelstudio_benchmark_helpers.py -k "interactive_labelstudio_export_routes_to_export_command or select_export_project_name"`
- Task record result: `3 passed, 16 deselected`.

Constraints and rollback notes:
- Keep env-var credential behavior unchanged.
- Preserve back-navigation semantics (`BACK_ACTION`).
- Rollback path was restoring manual-only project-name prompt in interactive export.

## Related Docs

- Import flow details: `docs/03-ingestion/README.md`
- Output/staging behavior: `docs/05-staging/README.md`
- Labeling and eval workflows: `docs/06-label-studio/README.md`
- Offline bench suite: `docs/07-bench/README.md`
- Tagging workflows: `docs/09-tagging/README.md`
