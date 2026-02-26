---
summary: "Detailed CLI and interactive-mode reference, including all commands, options, and environment variables."
read_when:
  - When changing command wiring, defaults, or interactive menu flows
  - When adding a new CLI command or command group
---

# CLI Section Reference

Primary command wiring lives in `cookimport/cli.py`.
Use this file as the source-of-truth CLI reference for coding/agent context.
For beginner interactive usage, start with `README.md` in the project root.

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
  ~~> = one-level Esc navigation

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
  +--> [H] Benchmark vs freeform gold -----> mode picker ------------------> (single offline run OR all-method offline sweep) -> [C]
  |
  +--> [I] Generate dashboard -------------> stats-dashboard -------------> [C]
  |
  +--> [J] Settings -----------------------> save `cookimport.json` ------> [C]
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
5. Uses `Esc` as one-level "go back" in `_menu_select`; typed prompts use `_prompt_*` wrappers, and caller flows decide whether that means step-back (for example freeform segment sizing) or cancel.

Important divergence to remember:
- interactive file selection is top-level only, but `cookimport stage <folder>` is recursive when a folder path is passed directly.

### [C] Main Menu

Menu options:

- `Stage files from data/input - produce cookbook outputs`
- `Label Studio: create labeling tasks (uploads)`
- `Label Studio: export completed labels to golden artifacts`
- `Generate predictions + evaluate vs freeform gold`
- `Generate dashboard - build lifetime stats dashboard HTML`
- `Settings - tune worker/OCR/output defaults`
- `Exit - close the tool`

Availability rule:

- `Import` and `Label Studio task upload` only appear when at least one supported top-level file exists in `data/input`.
- `inspect` remains available as a direct command (`cookimport inspect <path>`), not as an interactive menu action.

Menu numbering and shortcuts:

- `_menu_select` now shows Questionary shortcut labels on all select-style menus (for example `1)`, `2)`, ...).
- Numeric shortcuts (`1-9`, `0`) select immediately in interactive menus; non-numeric shortcuts still move focus and can be confirmed with Enter.

### [J] Settings

`Settings` edits global defaults in `cookimport.json`.

Interactive `Import` and single-offline benchmark runs include a per-run chooser (`global defaults` / `last run` / `change run settings`) so experiments do not mutate these global defaults. Interactive all-method benchmark skips the chooser and uses current global benchmark defaults.

Config keys and defaults:

- `workers` (default `7`)
- `pdf_split_workers` (default `7`)
- `epub_split_workers` (default `7`)
- `all_method_max_parallel_sources` (default `2`)
- `all_method_max_inflight_pipelines` (default `4`)
- `all_method_max_split_phase_slots` (default `4`)
- `all_method_config_timeout_seconds` (default `900`; `0` disables timeout)
- `all_method_retry_failed_configs` (default `1`; `0` disables retries)
- `all_method_wing_backlog_target` (default follows split slots)
- `all_method_smart_scheduler` (default `true`)
- `epub_extractor` (default `unstructured`)
- `epub_unstructured_html_parser_version` (default `v1`)
- `epub_unstructured_skip_headers_footers` (default `false`)
- `epub_unstructured_preprocess_mode` (default `br_split_v1`)
- `table_extraction` (default `off`)
- `ocr_device` (default `auto`)
- `ocr_batch_size` (default `1`)
- `output_dir` (default `data/output`)
- `label_studio_url` (default unset; populated after first interactive Label Studio prompt)
- `label_studio_api_key` (default unset; populated after first interactive Label Studio prompt)
- `pdf_pages_per_job` (default `50`)
- `epub_spine_items_per_job` (default `10`)
- `warm_models` (default `false`)
- `llm_recipe_pipeline` (default `off`)
- `llm_knowledge_pipeline` (default `off`)
- `llm_tags_pipeline` (default `off`)
- `codex_farm_cmd` (default `codex-farm`)
- `codex_farm_root` (default unset; falls back to `<repo_root>/llm_pipelines`)
- `codex_farm_workspace_root` (default unset; pipeline `codex_cd_mode` decides Codex `--cd`)
- `codex_farm_pipeline_pass1` (default `recipe.chunking.v1`)
- `codex_farm_pipeline_pass2` (default `recipe.schemaorg.v1`)
- `codex_farm_pipeline_pass3` (default `recipe.final.v1`)
- `codex_farm_pipeline_pass4_knowledge` (default `recipe.knowledge.v1`)
- `codex_farm_pipeline_pass5_tags` (default `recipe.tags.v1`)
- `codex_farm_context_blocks` (default `30`)
- `codex_farm_knowledge_context_blocks` (default `12`)
- `tag_catalog_json` (default `data/tagging/tag_catalog.json`)
- `codex_farm_failure_mode` (default `fail`)

What each setting affects:

- `workers`, split workers, page/spine split size: `stage` and benchmark import parallelism/sharding.
- `all_method_max_parallel_sources`: all-matched source-level concurrency cap (how many books run at once).
- `all_method_max_inflight_pipelines`, `all_method_max_split_phase_slots`, `all_method_wing_backlog_target`, `all_method_smart_scheduler`: per-source config scheduler controls (inflight cap, split-heavy slots, prewarm runway, smart/fixed admission mode; smart mode also adds a tail buffer equal to split slots so post-stage work does not block prewarming).
- `all_method_config_timeout_seconds`, `all_method_retry_failed_configs`: all-method safety controls (per-config timeout and failed-config retry passes).
- `epub_extractor`: runtime extractor choice (`unstructured`, `beautifulsoup`, `markdown`, or `markitdown`) via `C3IMP_EPUB_EXTRACTOR`.
- `epub_unstructured_html_parser_version`: parser version (`v1` or `v2`) passed into Unstructured HTML partitioning.
- `epub_unstructured_skip_headers_footers`: enables Unstructured `skip_headers_and_footers` for EPUB HTML partitioning.
- `epub_unstructured_preprocess_mode`: HTML pre-normalization mode before Unstructured (`none`, `br_split_v1`, or `semantic_v1` alias).
- `table_extraction`: deterministic non-recipe table detection/export (`tables.jsonl`, `tables.md`) and table-aware chunking behavior.
- `ocr_device`, `ocr_batch_size`: OCR path for PDFs.
- `output_dir`: interactive `stage` target output root.
- `label_studio_url`, `label_studio_api_key`: interactive Label Studio import/export credential defaults.
- `warm_models`: preloads SpaCy, ingredient parser, and OCR model before staging.
- `llm_recipe_pipeline`: recipe codex-farm parsing correction flow. Policy-locked `off` for now (non-`off` values are rejected).
- `llm_knowledge_pipeline`: optional knowledge-harvest flow (`off` or `codex-farm-knowledge-v1`) used by `stage` only.
- `llm_tags_pipeline`: optional tags pass (`off` or `codex-farm-tags-v1`) used by `stage` only.
- `tag_catalog_json`: required catalog snapshot path when `llm_tags_pipeline` is enabled.
- `codex_farm_*`: codex-farm command/root/workspace/pipeline-id/context/failure behavior used by `stage`; recipe-pass subset remains wired for benchmark prediction generation but is inactive while `llm_recipe_pipeline` is policy-locked to `off`.

Developer note:
- Per-run toggle definitions live in `cookimport/config/run_settings.py`. Add new fields there with `ui_*` metadata so the interactive editor picks them up automatically.
- The full-screen run-settings editor auto-scrolls to keep the selected row visible when the settings list exceeds terminal height.
- `stage(...)` is called both by Typer CLI dispatch and direct Python callers (interactive helpers/entrypoints/tests); it must coerce any Typer `OptionInfo` default objects back to plain values before normalization/building run settings.
- Interactive import should pass the full selected run-settings surface into `stage(...)` (including knowledge/tags pipeline toggles, pass4/pass5 pipeline IDs, and related context/catalog settings), not a partial subset.
- `import` / `C3import` entrypoint shims should forward the expanded stage run-settings arguments so persisted settings can affect direct-entrypoint runs.

### [D] Import Flow

`Import` steps:

1. Prompt for `Import All` or one selected file from top-level `data/input`.
2. Show `Run settings` mode picker:
   - `Run with global defaults (...)`
   - `Run with last import settings (...)` when available
   - `Change run settings...` (full-screen arrow-key editor)
3. Applies selected EPUB env vars:
   - `C3IMP_EPUB_EXTRACTOR`
   - `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`
   - `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`
   - `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`
4. Calls `stage(...)` using the full selected run settings payload (workers/OCR/extractor + LLM/codex-farm knobs).
5. Saves selected settings to `<output_dir_parent>/.history/last_run_settings_import.json` after a successful run.
6. Uses `limit` only if `C3IMP_LIMIT` was set before entering interactive mode.
7. Prints `Outputs written to: <run_folder>`.
8. Returns to the main menu after successful import.

### [E] Label Studio Import Flow

1. Choose a source file.
   - The menu shows supported files from `data/input`.
   - Pick the file you want to create labeling tasks from.
2. Enter a project name (or leave it blank).
   - If blank, the tool uses a name based on the file name.
   - If a project with that final name already exists, this flow replaces it.
3. Configure freeform task generation:
   - enter `segment_blocks` (context blocks per task, integer `>= 1`),
   - enter `segment_overlap` (integer `>= 0`),
   - enter `segment_focus_blocks` (blocks to actively label per task, integer `>= 1` and `<= segment_blocks`),
   - optional `target_task_count` (blank disables auto-tuning).
4. Configure optional AI prelabeling:
   - choose prelabel mode (`off`, strict/allow-partial annotations, or advanced predictions mode variants).
   - if enabled, choose labeling style (`actual freeform` span mode vs `block based` mode).
   - interactive mode uses the resolved Codex command (`COOKIMPORT_CODEX_CMD` or `codex exec -`), shows the resolved account email when available, then prompts for model (`use default`, discovered models from that command's Codex home / `CODEX_HOME`, or custom model id) and thinking effort (model-compatible subset of `none|low|medium|high|xhigh`; `minimal` is intentionally hidden for this workflow), mapped to Codex `model_reasoning_effort`.
   - freeform prelabel task calls run in parallel by default (`15` workers).
5. Enter Label Studio URL and API key if needed.
   - If `LABEL_STUDIO_URL` and `LABEL_STUDIO_API_KEY` are set, prompts are skipped.
   - Otherwise, interactive mode uses saved `cookimport.json` values when present.
   - If still missing, you are prompted once and the entered values are saved to `cookimport.json` for future interactive runs.
6. The tool builds tasks on your machine.
   - It prepares freeform segment tasks (`freeform-spans`) from extracted source blocks.
   - Before per-task AI labeling starts, it runs a single Codex model-access preflight call and fails fast when the selected model/account combination is invalid.
   - A status spinner shows live phase updates with `task X/Y` progress for known-size loops (including freeform prelabeling when AI prelabel is enabled), adds ETA once enough `X/Y` progress is observed, and shows per-worker activity lines under the main status when worker telemetry is available.
   - It writes run files under `data/golden/sent-to-labelstudio`:
   - `label_studio_tasks.jsonl`
   - `coverage.json`
   - `extracted_archive.json`
   - `extracted_text.txt`
   - `manifest.json`
7. The tool uploads tasks to Label Studio automatically.
   - No extra "are you sure?" prompt in this interactive flow.
   - Upload is batched in groups of 200 tasks.
   - `manifest.json` is updated with project ID, upload count, and project URL.
8. Review the summary shown in terminal.
   - You get a quick recap of project/tasks/run location, including total processing time.
   - If AI prelabel was enabled for `freeform-spans`, the summary also prints `prelabel_report.json`.
9. Interactive mode returns to the main menu after the flow completes.

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
4. Calls export directly (no scope prompt).
   - Detected type is informational only.
   - Export supports freeform projects only; legacy scopes are rejected with an explicit error.
5. Calls `run_labelstudio_export(...)` with `output_dir=data/golden/pulled-from-labelstudio`.
   - By default, export writes to: `data/golden/pulled-from-labelstudio/<project_slug>/exports/`.
   - If `--run-dir` is supplied in non-interactive mode, export writes to that run directory.
6. Prints export summary path and returns to the main menu.

### [H] Benchmark vs Freeform Gold Flow

Interactive benchmark now has a mode submenu before execution:

1. Shows benchmark mode picker:
   - `Generate predictions + evaluate (offline, no upload)` (default first choice)
   - `All method benchmark (offline, no upload)`
2. Single offline path:
   - shows benchmark `Run settings` mode picker (`global` / `last benchmark` / `change`), using the same editor flow as Import,
   - calls `labelstudio-benchmark` once with `--no-upload`,
   - does not resolve Label Studio credentials,
   - writes eval artifacts under `data/golden/benchmark-vs-golden/<timestamp>/`.
3. All method path:
   - uses global benchmark defaults directly (no run-settings chooser),
   - prompts for all-method scope:
     - `Single golden set`: prompts for one gold export and source file.
     - `All golden sets with matching input files`: discovers freeform exports and matches source hints to top-level importable files in `data/input` by filename.
   - source hint fallback order is: run `manifest.json` `source_file`, then first non-empty `freeform_span_labels.jsonl` row `source_file`, then first non-empty `freeform_segment_manifest.jsonl` row `source_file`,
   - all-matched mode prints matched/skipped counts, planned permutation count, and sample skipped reasons before execution,
  - asks whether to include Codex Farm permutations (default `No`; currently remains disabled by policy lock),
  - prints scheduler limits before confirmation, including mode and resolved values:
    - source parallelism (configured/effective),
    - configured/effective inflight,
    - split-phase slots,
    - wing backlog target,
    - smart tail buffer (equals split slots when smart mode is on),
    - per-config timeout and failed-config retry limit,
    sourced from `cookimport.json` keys `all_method_max_parallel_sources`, `all_method_max_inflight_pipelines`, `all_method_max_split_phase_slots`, `all_method_wing_backlog_target`, `all_method_smart_scheduler`, `all_method_config_timeout_seconds`, and `all_method_retry_failed_configs`,
   - asks final proceed confirmation (`Proceed with N benchmark runs?` for single or `Proceed with N benchmark runs across M matched golden sets?` for all-matched, default `No`),
  - execution uses one persistent all-method spinner dashboard (book queue + overall source/config counters + current task line), including a scheduler snapshot line:
    - `scheduler heavy X/Y | wing Z | active A | pending P`,
    - `current config` reflects active config slots in parallel mode (`current configs A-B/N`) rather than a stale last-submitted slug,
    - when no config is actively running but source work remains, the line shows `<queued>`,
    - outer multi-source progress should rerender from shared dashboard state when an inbound nested snapshot is stale/partial so queue rows stay stable,
    - all-matched mode can show multiple `[>]` source rows simultaneously (`active sources: N`),
  - executes configs through a bounded queue:
    - fixed mode: submit up to inflight capacity and refill on completion,
    - smart mode: phase-aware admission keeps `heavy + wing` near `split slots + wing backlog target` and auto-raises effective inflight with an additional split-slot tail buffer so long post phases do not starve preheating,
    - timeout watchdog (`all_method_config_timeout_seconds`) marks timed-out configs failed and recycles worker pool so one hung config cannot block source completion,
    - failed-only retry passes (`all_method_retry_failed_configs`) rerun only failed config indices, not successful ones,
    - startup fallback to serial mode remains when process workers are unavailable,
   - split-worker-heavy conversion is gate-limited to at most `4` simultaneous configs (slot telemetry updates spinner task/progress output instead of printing standalone worker lines),
   - runs each config offline (`--no-upload`) and writes per-source eval artifacts plus:
     - `<source_slug>/all_method_benchmark_report.json`
     - `<source_slug>/all_method_benchmark_report.md`
     - each per-source report now includes `timing_summary` and per-config `timing` rows
   - all-matched mode also writes a combined summary report:
     - `all_method_benchmark_multi_source_report.json`
     - `all_method_benchmark_multi_source_report.md`
     - combined report now includes run-level `timing_summary` (run/source/config totals + slowest source/config),
     - combined report includes source-parallel metadata (`source_parallelism_configured`, `source_parallelism_effective`),
     - dashboard refresh is batched once at multi-source completion when source parallelism is enabled (per-source refresh remains for serial source mode),
   - writes per-config processed cookbook outputs under:
     - `<interactive output_dir>/<benchmark_timestamp>/all-method-benchmark/<source_slug>/config_*/<prediction_timestamp>/...`
   - prints `All method processed outputs: ...` with that root path.
4. Saves selected settings to `<output_dir_parent>/.history/last_run_settings_benchmark.json` after successful single-offline runs.
5. Returns to the main menu on completion.

For re-scoring an existing prediction run directly, use `cookimport labelstudio-eval`. For offline single-run benchmarking, use non-interactive `cookimport labelstudio-benchmark --no-upload`.

### [I] Generate Dashboard Flow

1. Prompts `Open dashboard in your browser after generation?`.
2. Runs `stats-dashboard` using the interactive `output_dir` setting as `--output-root`.
3. Writes dashboard files to `<output_dir_parent>/.history/dashboard`.
4. Opens `index.html` automatically when you answer `Yes`.
5. Returns to the main menu on completion.

Note:
- History-writing commands (`stage`, `perf-report --write-csv`, `labelstudio-eval`, `labelstudio-benchmark`, `bench run`, and non-dry `benchmark-csv-backfill` with updates) now auto-run the same dashboard refresh process for their target history root.

### [Z] Exit Conditions

Interactive mode exits when:

- user selects `Exit` from the main menu.

## Command Surface

Top-level command groups:

- `cookimport stage`
- `cookimport epub <inspect|dump|unpack|blocks|candidates|validate>`
- `cookimport inspect`
- `cookimport labelstudio-import`
- `cookimport labelstudio-export`
- `cookimport labelstudio-eval`
- `cookimport labelstudio-benchmark`
- `cookimport perf-report`
- `cookimport benchmark-csv-backfill`
- `cookimport stats-dashboard`
- `cookimport bench <validate|run|sweep|knobs>`
- `cookimport tag-catalog export`
- `cookimport tag-recipes <debug-signals|suggest|apply>`

Every command supports `--help`.

### CLI Help Shortcuts

Use these to inspect current help text from the installed version:

```bash
cookimport --help
cookimport stage --help
cookimport perf-report --help
cookimport inspect --help
cookimport labelstudio-import --help
cookimport labelstudio-export --help
cookimport labelstudio-eval --help
cookimport labelstudio-benchmark --help
```

## Command Reference

### `cookimport stage PATH`

Stages one file or all files under a folder (recursive for folder input). Always creates a timestamped run folder under `--out` using format `YYYY-MM-DD_HH.MM.SS`.
Each stage run folder includes `run_manifest.json` for source/config/artifact traceability.
After stage history CSV append, the CLI also auto-refreshes dashboard artifacts under `<out parent>/.history/dashboard` (best effort).

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
- `--epub-extractor TEXT` (default `unstructured`): `unstructured|beautifulsoup|markdown|markitdown`; exported to `C3IMP_EPUB_EXTRACTOR` for importer runtime.
- `--epub-unstructured-html-parser-version TEXT` (default `v1`): `v1|v2`; exported to `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`.
- `--epub-unstructured-skip-headers-footers / --no-epub-unstructured-skip-headers-footers` (default disabled): exported to `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`.
- `--epub-unstructured-preprocess-mode TEXT` (default `br_split_v1`): `none|br_split_v1|semantic_v1`; exported to `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`.
- `--table-extraction TEXT` (default `off`): `off|on` deterministic table detection/export and table-aware chunking.
- `--llm-recipe-pipeline TEXT` (default `off`): policy-locked `off` (recipe codex-farm parsing correction is currently disabled).
- `--llm-knowledge-pipeline TEXT` (default `off`): `off|codex-farm-knowledge-v1`.
- `--llm-tags-pipeline TEXT` (default `off`): `off|codex-farm-tags-v1`.
- `--codex-farm-cmd TEXT` (default `codex-farm`): subprocess command used to invoke codex-farm.
- `--codex-farm-root PATH` (default unset): optional codex-farm pipeline-pack root; defaults to `<repo_root>/llm_pipelines`.
- `--codex-farm-workspace-root PATH` (default unset): optional workspace root passed to codex-farm (`--workspace-root`).
- `--codex-farm-pipeline-pass1 TEXT` (default `recipe.chunking.v1`): pass-1 pipeline id (recipe chunking/boundary).
- `--codex-farm-pipeline-pass2 TEXT` (default `recipe.schemaorg.v1`): pass-2 pipeline id (schema.org extraction).
- `--codex-farm-pipeline-pass3 TEXT` (default `recipe.final.v1`): pass-3 pipeline id (final draft generation).
- `--codex-farm-pipeline-pass4-knowledge TEXT` (default `recipe.knowledge.v1`): pass-4 pipeline id (non-recipe knowledge harvesting).
- `--codex-farm-pipeline-pass5-tags TEXT` (default `recipe.tags.v1`): pass-5 pipeline id (tag suggestions).
- `--codex-farm-context-blocks INTEGER>=0` (default `30`): context blocks before/after candidate for pass1 bundles.
- `--codex-farm-knowledge-context-blocks INTEGER>=0` (default `12`): context blocks before/after each knowledge chunk for pass4 bundles.
- `--tag-catalog-json PATH` (default `data/tagging/tag_catalog.json`): tag catalog snapshot path required when pass5 tags is enabled.
- `--codex-farm-failure-mode TEXT` (default `fail`): `fail|fallback` behavior when codex-farm setup/invocation fails.
- `markitdown` note: EPUB split jobs are disabled for this extractor because conversion is whole-book EPUB -> markdown (no spine-range mode).
- explicit-choice note: stage no longer supports `--epub-extractor auto`; choose a concrete backend (`unstructured|beautifulsoup|markdown|markitdown`).

Split-merge progress detail:
- After split workers finish, the worker dashboard `MainProcess` row now advances with explicit `merge phase X/Y: ...` status messages (payload merge, ID reassignment, output writes, raw merge) instead of staying on a single static `Merging ...` label.

### `cookimport debug-epub-extract PATH`

Runs unstructured extraction diagnostics for one EPUB spine and writes variant artifacts.

Behavior:

- Reads one spine XHTML entry from the EPUB container.
- Writes `raw_spine.xhtml` plus per-variant outputs:
  - `normalized_spine.xhtml`
  - `blocks.jsonl`
  - `unstructured_elements.jsonl`
  - `summary.json` (metrics per variant)
- `--variants` runs parser/preprocess grid:
  - parser `v1` + preprocess `none`
  - parser `v2` + preprocess `none`
  - parser `v1` + preprocess `br_split_v1`
  - parser `v2` + preprocess `br_split_v1`

Options:

- `--out PATH` (default `data/output/epub-debug`): output root.
- `--spine INTEGER>=0` (default `0`): spine index to inspect.
- `--variants` (default disabled): run full variant grid.
- `--html-parser-version TEXT` (default `v1`): single-run parser version when not using `--variants`.
- `--preprocess-mode TEXT` (default `none`): single-run preprocess mode when not using `--variants`.
- `--skip-headers-footers / --no-skip-headers-footers` (default disabled): pass Unstructured header/footer skip flag.

### `cookimport epub ...`

EPUB-specific inspection/debug command group mounted as a sub-CLI.
These commands are read-only on the source EPUB and write artifacts only to `--out` directories.
Optional pre-release helper dependency for richer structure inspection:

- `source .venv/bin/activate && python -m pip install -e '.[epubdebug]'`
- `epub-utils` is currently pre-release-only (`0.1.0a1`), so if installing directly use:
- `python -m pip install --pre epub-utils` or `python -m pip install 'epub-utils==0.1.0a1'`

Subcommands:

- `cookimport epub inspect PATH [--out OUTDIR] [--json] [--force]`
- `cookimport epub dump PATH --spine-index N [--format xhtml|plain] --out OUTDIR [--open] [--force]`
- `cookimport epub unpack PATH --out OUTDIR [--only-spine] [--force]`
- `cookimport epub blocks PATH --out OUTDIR [--extractor unstructured|beautifulsoup|markdown|markitdown] [--start-spine N] [--end-spine M] [--html-parser-version v1|v2] [--skip-headers-footers] [--preprocess-mode none|br_split_v1|semantic_v1] [--force]`
- `cookimport epub candidates PATH --out OUTDIR [--extractor ...] [--start-spine N] [--end-spine M] [--html-parser-version ...] [--skip-headers-footers] [--preprocess-mode ...] [--force]`
- `cookimport epub validate PATH [--jar PATH] [--out OUTDIR] [--strict] [--force]`

High-value outputs:

- `inspect_report.json`
- `blocks.jsonl`, `blocks_preview.md`, `blocks_stats.json`
- `candidates.json`, `candidates_preview.md`
- `epubcheck.txt`, `epubcheck.json` (when validator jar is found)

Integration contract (stage/debug parity, preserve this):

- `epub blocks` and `epub candidates` should continue to reuse production importer internals:
  - `cookimport/plugins/epub.py:_extract_docpack(...)`
  - `cookimport/plugins/epub.py:_detect_candidates(...)`
  - `cookimport/plugins/epub.py:_extract_title(...)` (candidate title guesses)
- Direct `_extract_docpack(...)` use in debug commands must initialize importer state expected by signal enrichment (`importer._overrides = None`), which is normally initialized on full `convert(...)` path.
- Debug commands should set the same EPUB unstructured env vars as stage so extractor output stays comparable:
  - `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`
  - `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`
  - `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`
- Output safety rules: reject non-empty `--out` unless `--force`, and never modify source EPUB files.
- Structural inspection should keep zip/OPF parsing as baseline; optional `epub_utils` support is best-effort enrichment only.

### `cookimport inspect PATH`

Inspects importer layout guesses for one file.

Arguments:

- `PATH` (required): file to inspect.

Options:

- `--out PATH` (default `data/output`): where mapping stubs are written if enabled.
- `--write-mapping` (default `false`): writes `mappings/<stem>.mapping.yaml`.

### `cookimport perf-report`

Builds a per-file timing summary from conversion reports.
When `--write-csv` is enabled, the same run also auto-refreshes dashboard artifacts for that history root.

Options:

- `--run-dir PATH`: specific run folder to summarize (defaults to latest under `--out-dir`).
- `--out-dir PATH` (default `data/output`): output root used for discovery and history CSV location.
- `--write-csv / --no-csv` (default `--write-csv`): append summary rows to history CSV or skip.

### `cookimport benchmark-csv-backfill`

One-off patch command for historical benchmark rows in `performance_history.csv`.

What it does:

- scans benchmark rows (`run_category=benchmark_eval|benchmark_prediction`)
- fills missing `recipes` from benchmark manifests (`recipe_count`) with fallback to `processed_report_path -> totalRecipes`
- fills missing `report_path` and `file_name` from benchmark manifests when available
- writes updates in-place to the CSV unless `--dry-run` is used
- when rows are written, auto-refreshes dashboard artifacts for that history root

Options:

- `--out-dir PATH` (default `data/output`): used to resolve default CSV path (`<out-dir parent>/.history/performance_history.csv`).
- `--history-csv PATH`: explicit CSV path override.
- `--dry-run` (default `false`): report how many rows would be patched without writing.

### `cookimport stats-dashboard`

Builds static lifetime dashboard HTML from output/golden data.

Options:

- `--output-root PATH` (default `data/output`): staged import root.
- `--golden-root PATH` (default `data/golden`): benchmark/golden artifacts root.
- `--out-dir PATH` (default `data/.history/dashboard`): dashboard output directory.
- `--open` (default `false`): opens generated HTML in default browser.
- `--since-days INTEGER`: include only recent runs.
- `--scan-reports` (default `false`): force scanning per-file report JSON instead of cached summaries.

### `cookimport labelstudio-import PATH`

Creates Label Studio tasks from one source file.
The prediction run directory now includes `run_manifest.json`.

Arguments:

- `PATH` (required): source file to import.

Options:

- `--output-dir PATH` (default `data/golden/sent-to-labelstudio`): artifact root.
- `--pipeline TEXT` (default `auto`): importer selection.
- `--project-name TEXT`: explicit Label Studio project name.
- `--segment-blocks INTEGER>=1` (default `40`): freeform segment size.
- `--segment-overlap INTEGER>=0` (default `5`): freeform overlap.
- `--segment-focus-blocks INTEGER>=1` (default unset): freeform blocks per task that should receive labels; when omitted, focus equals `segment_blocks`.
- `--target-task-count INTEGER>=1` (default unset): optional freeform task-count target; runtime auto-tunes effective overlap per file to land as close as possible.
- `--overwrite / --resume` (default `--resume`): recreate or resume project.
- `--label-studio-url TEXT`: explicit Label Studio URL.
- `--label-studio-api-key TEXT`: explicit Label Studio API key.
- `--allow-labelstudio-write / --no-allow-labelstudio-write` (default disabled): required gate for upload.
- `--limit, -n INTEGER>=1`: cap chunks generated.
- `--sample INTEGER>=1`: randomly sample chunks.
- `--prelabel / --no-prelabel` (default disabled): freeform-only first-pass LLM labeling.
- `--prelabel-provider TEXT` (default `codex-cli`): provider backend for prelabeling.
- `--codex-cmd TEXT`: override Codex CLI command (defaults to `COOKIMPORT_CODEX_CMD` or `codex exec -`).
- `--prelabel-timeout-seconds INTEGER>=1` (default `300`): timeout per provider call.
- `--prelabel-cache-dir PATH`: optional prompt/response cache directory.
- `--prelabel-workers INTEGER>=1` (default `15`): concurrent freeform prelabel provider calls (`1` keeps serialized behavior).
- `--prelabel-upload-as TEXT` (default `annotations`): `annotations|predictions`.
- `--prelabel-granularity TEXT` (default `block`): `block|span` (`block` = block based; `span` = actual freeform).
- `--prelabel-allow-partial / --no-prelabel-allow-partial` (default disabled): continue upload when some prelabels fail.

Prelabel behavior notes:
- `labelstudio-import` is freeform-only (`freeform-spans`), so `--prelabel` always applies to freeform tasks.
- `--prelabel-upload-as annotations` first tries inline annotation upload and falls back to task-only upload + per-task annotation create when needed.
- When prelabel failures occur (especially with `--prelabel-allow-partial`), the CLI prints an explicit red `PRELABEL ERRORS: X/Y ...` summary plus `prelabel_errors.jsonl` path at run completion.

Hard requirement:

- Upload is blocked unless `--allow-labelstudio-write` is set.

### `cookimport labelstudio-export`

Exports completed labels to golden-set artifacts.

Options:

- `--project-name TEXT` (required): Label Studio project name.
- `--output-dir PATH` (default `data/golden/pulled-from-labelstudio`): output root.
- `--run-dir PATH`: export from a specific run directory.
- `--label-studio-url TEXT`: explicit Label Studio URL.
- `--label-studio-api-key TEXT`: explicit Label Studio API key.
- Legacy project scopes (`pipeline`, `canonical-blocks`) are rejected; export supports freeform projects only.

### `cookimport labelstudio-eval`

Scores freeform prediction spans against freeform gold labels.
The eval output directory now includes `run_manifest.json`.

Options:

- `--pred-run PATH` (required): prediction run directory (must contain `label_studio_tasks.jsonl`).
- `--gold-spans PATH` (required): gold JSONL file.
- `--output-dir PATH` (required): eval artifact directory.
- `--overlap-threshold FLOAT 0..1` (default `0.5`): Jaccard match threshold.
- `--force-source-match` (default `false`): ignore source identity checks while matching spans.
- On successful benchmark CSV append, auto-refreshes dashboard artifacts for that history root.

### `cookimport labelstudio-benchmark`

Prediction+eval flow against freeform gold spans (upload or offline).

Behavior note:

- Non-interactive upload path: generates predictions, uploads to Label Studio, then evaluates.
- Non-interactive offline path: `--no-upload` generates predictions locally and evaluates with no Label Studio credentials/API calls.
- Re-scoring an old prediction run without regeneration is still done with `cookimport labelstudio-eval --pred-run ... --gold-spans ...`.
- Interactive mode (`cookimport` -> Benchmark) always runs offline benchmark generation/eval (`single offline` or `all method`).
- Successful runs persist benchmark timing under `eval_report.json` `timing`, including prediction/evaluation/write/history subphase timings and checkpoints.
- Benchmark CSV append now receives that timing payload and records benchmark runtime columns in `performance_history.csv`.
- Single benchmark runs auto-refresh dashboard artifacts after CSV append.
- All-method benchmark internals suppress per-config refresh and refresh once per source batch.

Options:

- `--gold-spans PATH`: freeform gold file; if omitted, prompt from discovered exports.
- `--source-file PATH`: source file to re-import for predictions; if omitted, prompt/infer.
- `--output-dir PATH` (default `data/golden/benchmark-vs-golden`): scratch root for prediction import artifacts.
- `--processed-output-dir PATH` (default `data/output`): root for staged cookbook outputs generated during benchmark.
- `--eval-output-dir PATH`: destination for benchmark report artifacts.
- `--overlap-threshold FLOAT 0..1` (default `0.5`): match threshold.
- `--force-source-match` (default `false`): ignore source identity checks while matching.
- `--pipeline TEXT` (default `auto`): importer selection.
- `--chunk-level TEXT` (default `both`): `structural|atomic|both`.
- `--project-name TEXT`: explicit prediction project name.
- `--allow-labelstudio-write / --no-allow-labelstudio-write` (default disabled): required gate for upload mode.
- `--no-upload` (default `false`): force offline benchmark (no upload, no credential resolution).
- `--overwrite / --resume` (default `--resume`): recreate prediction project or resume.
- `--label-studio-url TEXT`: explicit Label Studio URL.
- `--label-studio-api-key TEXT`: explicit Label Studio API key.
- `--workers INTEGER>=1` (default `7`): prediction import process workers.
- `--pdf-split-workers INTEGER>=1` (default `7`): PDF split workers for prediction import.
- `--epub-split-workers INTEGER>=1` (default `7`): EPUB split workers for prediction import.
- `--pdf-pages-per-job INTEGER>=1` (default `50`): PDF shard size.
- `--epub-spine-items-per-job INTEGER>=1` (default `10`): EPUB shard size.
- `--epub-extractor TEXT` (default `unstructured`): `unstructured|beautifulsoup|markdown|markitdown`; exported to `C3IMP_EPUB_EXTRACTOR` for prediction import runtime.
- `--epub-unstructured-html-parser-version TEXT` (default `v1`): `v1|v2`; exported to `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`.
- `--epub-unstructured-skip-headers-footers / --no-epub-unstructured-skip-headers-footers` (default disabled): exported to `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`.
- `--epub-unstructured-preprocess-mode TEXT` (default `br_split_v1`): `none|br_split_v1|semantic_v1`; exported to `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`.
- `--llm-recipe-pipeline TEXT` (default `off`): policy-locked `off` (recipe codex-farm parsing correction is currently disabled).
- `--codex-farm-cmd TEXT` (default `codex-farm`): subprocess command used to invoke codex-farm during prediction generation.
- `--codex-farm-root PATH` (default unset): optional codex-farm pipeline-pack root; defaults to `<repo_root>/llm_pipelines`.
- `--codex-farm-workspace-root PATH` (default unset): optional workspace root passed to codex-farm (`--workspace-root`).
- `--codex-farm-pipeline-pass1 TEXT` (default `recipe.chunking.v1`): pass-1 pipeline id (recipe chunking/boundary).
- `--codex-farm-pipeline-pass2 TEXT` (default `recipe.schemaorg.v1`): pass-2 pipeline id (schema.org extraction).
- `--codex-farm-pipeline-pass3 TEXT` (default `recipe.final.v1`): pass-3 pipeline id (final draft generation).
- `--codex-farm-context-blocks INTEGER>=0` (default `30`): context blocks before/after candidate for pass1 bundles.
- `--codex-farm-failure-mode TEXT` (default `fail`): `fail|fallback` behavior when codex-farm setup/invocation fails.
- `markitdown` note: prediction EPUB split jobs are disabled for this extractor for the same reason as stage runs.
- explicit-choice note: prediction generation no longer supports `--epub-extractor auto`; requested/effective extractor values are the selected concrete backend.
- `--ocr-device TEXT` (default `auto`): `auto|cpu|cuda|mps`.
- `--ocr-batch-size INTEGER>=1` (default `1`): pages per OCR model call.
- `--warm-models` (default `false`): preload OCR/parsing models before prediction import.

Upload requirement:

- Upload mode is blocked unless `--allow-labelstudio-write` is set.

### `cookimport bench validate`

Validates a bench suite manifest.

Options:

- `--suite PATH` (required): suite JSON path.

### `cookimport bench run`

Runs offline benchmark suite and writes report/metrics/iteration packet.

Status behavior:

- Spinner updates include `item X/Y` counters for per-suite-item work, with item id prefixes in nested prediction/eval messages.
- After benchmark CSV append, auto-refreshes dashboard artifacts for the benchmark history root.

Options:

- `--suite PATH` (required): suite JSON path.
- `--out-dir PATH` (default `data/golden/bench/runs`): run output root.
- `--baseline PATH`: prior run directory for deltas.
- `--config PATH`: knob config JSON file.

### `cookimport bench sweep`

Runs random/configured sweep over suite knobs.

Status behavior:

- Spinner updates include `config X/Y` counters.
- Nested suite updates are forwarded as `config X/Y | item X/Y [item_id] ...` so both loop levels are visible.

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
- `C3IMP_EPUB_EXTRACTOR`: EPUB extractor switch (`unstructured`, `beautifulsoup`, `markdown`, or `markitdown`) read at runtime by the EPUB importer.
- `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`: unstructured HTML parser version (`v1` or `v2`) for EPUB extraction.
- `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`: bool toggle for Unstructured `skip_headers_and_footers` on EPUB HTML.
- `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`: EPUB HTML preprocess mode before Unstructured (`none`, `br_split_v1`, `semantic_v1`).
- `C3IMP_STANDALONE_ANALYSIS_WORKERS`: worker count for EPUB/PDF standalone knowledge-block analysis (`>=1`, default `4`).
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
- For EPUB extractor/options: explicit stage/benchmark flags or interactive per-run Run Settings selection write `C3IMP_EPUB_EXTRACTOR` plus `C3IMP_EPUB_UNSTRUCTURED_*` vars for that run.
- For tag DB URL: `--db-url` wins; env var is fallback.


## CLI History Log

Historical architecture/build/fix-attempt notes were moved to `docs/02-cli/02-cli_log.md`.
Use that file to check prior attempts before retrying a fix path.

## Related Docs

- Import flow details: `docs/03-ingestion/03-ingestion_readme.md`
- Output/staging behavior: `docs/05-staging/05-staging_readme.md`
- Labeling and eval workflows: `docs/06-label-studio/06-label-studio_README.md`
- Offline bench suite: `docs/07-bench/07-bench_README.md`
- Tagging workflows: `docs/09-tagging/09-tagging_README.md`

## Merged Understandings (2026-02-20 and durable checklist)

### New pipeline-option wiring checklist (IMPORTANT-INSTRUCTION-pipeline-option-edit-map)

When introducing a new processing option, complete all four surfaces together:

1. Definition + selection:
- Add it to `RunSettings` in `cookimport/config/run_settings.py` (metadata, canonical builder, summary order when needed).
- Ensure interactive selector/editor surfaces (`cookimport/cli_ui/run_settings_flow.py`, `cookimport/cli_ui/toggle_editor.py`) expose it.
- Update `compute_effective_workers(...)` when the option changes split capability or effective parallelism.

2. Runtime propagation:
- Wire option handling through `cookimport/cli.py` stage and benchmark command paths.
- Keep split-planner parity between `cookimport/cli.py:_plan_jobs(...)` and `cookimport/labelstudio/ingest.py:_plan_parallel_convert_jobs(...)`.
- Propagate through prediction artifact generation in `cookimport/labelstudio/ingest.py:generate_pred_run_artifacts(...)`.

3. Analytics persistence:
- Preserve run-config/report fields (`runConfig`, `runConfigHash`, `runConfigSummary`) in stage/benchmark artifacts.
- Keep CSV + dashboard visibility aligned (`cookimport/analytics/perf_report.py`, `dashboard_collect.py`, `dashboard_render.py`).

4. Both execution lanes:
- Import lane (`cookimport stage`).
- Prediction-generation lane for benchmark/freeform eval (`labelstudio-benchmark` prediction run creation).
- Reminder: `labelstudio-eval` is eval-only and does not rerun pipeline options.

## Merged Task Specs (2026-02-16 to 2026-02-22)

### 2026-02-16_14.31.00 EPUB debug CLI (`cookimport epub ...`)

Durable behavior added for debug workflows:

- Subcommands: `inspect`, `dump`, `unpack`, `blocks`, `candidates`, `validate`.
- `blocks` and `candidates` must stay pipeline-faithful by reusing production EPUB extraction/segmentation logic.
- Deterministic debug artifacts are part of the command contract:
  - `inspect_report.json`
  - `blocks.jsonl`, `blocks_preview.md`, `blocks_stats.json`
  - `candidates.json`, `candidates_preview.md`

Important implementation constraints:

- Direct calls to `EpubImporter._extract_docpack(...)` require `_overrides` initialized (current rule: default `None` in importer init).
- `epub-utils` is optional and may require pre-release install handling (`epub-utils==0.1.0a1`); ZIP/OPF fallback must remain available.
- EPUBCheck support stays optional; strict failure is opt-in with `--strict`.

## Merged Task Specs (2026-02-23 docs/tasks archival batch)

### 2026-02-16 per-run run settings selector and persistence (`docs/tasks/01-PerRunSettingsSelector.md`)

What shipped and where to look:
- Canonical settings model and summary/hash source of truth: `cookimport/config/run_settings.py`.
- Interactive run-settings mode picker (global defaults / last run / edit): `cookimport/cli_ui/run_settings_flow.py`.
- Full-screen toggle-table editor: `cookimport/cli_ui/toggle_editor.py`.
- Last-run snapshots per operation (`import` vs `benchmark`): `cookimport/config/last_run_store.py`.

Durable behavior:
- Interactive Import and interactive Benchmark upload always route through a run-settings choice before launching conversion.
- Every run-producing path persists structured `runConfig` plus `runConfigHash` and `runConfigSummary` into report/history surfaces.
- Eval-only benchmark mode intentionally bypasses run-settings persistence because no extraction pipeline runs.

Anti-loop notes:
- If a new knob appears in the editor but not in report/CSV/dashboard metadata, wiring is incomplete.
- Add new pipeline knobs in one place (`RunSettings`) and propagate through stage + prediction-generation paths in the same change.

### 2026-02-22 spinner progress counters second pass (`docs/tasks/2026-02-22_13.02.21-spinner-progress-counters-second-pass.md`)

Durable CLI UX contract:
- Known-size loops should emit explicit counters (`item X/Y`, `config X/Y`, `merge phase X/Y`) instead of static phase text.
- Counter formatting should be shared through `cookimport/core/progress_messages.py` to avoid message drift.
- Split-merge phase totals must include optional phases only when they will actually run, so `X/Y` remains honest.

Operational examples to preserve:
- `item 3/12 [item_id] ...`
- `config 2/10 | item 4/12 ...`
- `merge phase 5/9: <label>`

### 2026-02-22 benchmark run-settings editor scroll fix (`docs/tasks/2026-02-22_19.12.59 - benchmark-run-settings-editor-scroll.md`)

Durable editor behavior:
- The full-screen toggle editor must expose a cursor position tied to the selected row so prompt_toolkit can auto-scroll.
- Focus should stay on the body window while navigating rows.
- Existing keybindings (`Up/Down/Left/Right`, save/cancel) are preserved.

Regression anchors:
- `tests/test_toggle_editor.py`
- `tests/test_run_settings.py`
- `tests/test_c3imp_interactive_menu.py`

## Merged Understandings Batch (2026-02-23 cleanup)

### Prompt/keybinding back-navigation contract

Merged sources:
- `docs/understandings/2026-02-22_22.30.58-interactive-esc-back-contract.md`
- `docs/understandings/2026-02-22_23.09.47-freeform-interactive-esc-step-back.md`

Durable rules:
- `_menu_select(...)` remains the select-menu control point for Esc/back semantics.
- Typed prompts in interactive flows should go through `_prompt_text`, `_prompt_confirm`, or `_prompt_password` so Esc maps to one-level back/cancel.
- Freeform segment settings must use `_prompt_freeform_segment_settings(...)` so Esc steps back one field instead of dropping to the main menu.

### Run-settings editor viewport contract

Merged source:
- `docs/understandings/2026-02-22_19.12.59-run-settings-editor-scroll-contract.md`

Durable rules:
- `toggle_editor` body control must expose selected-row cursor mapping (`get_cursor_position`) and keep body focus so prompt_toolkit viewport scrolling follows row movement.

### Spinner ETA and worker telemetry contract

Merged sources:
- `docs/understandings/2026-02-22_23.13.34-spinner-xy-eta-flow.md`
- `docs/understandings/2026-02-23_00.17.44-spinner-worker-activity-telemetry.md`

Durable rules:
- Callback spinner ETA is derived from the active `X/Y` counter and should only accumulate timing over real counter increments (`X` increase). For all-method dashboard snapshots, use top-line `overall ... | config X/Y`.
- `task/item/config/phase` loops should emit counters from runtime loop boundaries; CLI renderer should format and decorate them, not invent totals.
- Worker telemetry stays a side-channel payload parsed/rendered by shared spinner code so per-worker status lines do not overwrite the primary phase/task line.
- For multi-line dashboard snapshots, ETA/elapsed suffixes decorate the top summary line (`overall ...`) instead of the trailing `task:` line.

## Merged Task Specs (2026-02-22_23 to 2026-02-23_00)

### 2026-02-22_23.13.39 spinner `X/Y` ETA contract

Current CLI spinner contract for callback-driven phases:

- Parse the active `X/Y` counter in status text (all-method dashboard snapshots use top-line `overall ... | config X/Y`; other flows use right-most).
- Compute average seconds per completed unit from observed `X` increments.
- Render ETA only after at least one increment; keep stale-phase elapsed-seconds ticker behavior unchanged.
- Keep this logic centralized in `_run_with_progress_status(...)` so import/benchmark/Label Studio wrappers stay consistent.

Durable gotcha:
- Nested counters can appear (`config`, `item`, `task`); all-method dashboard snapshots are the exception where top-line overall config is the active unit.

### 2026-02-23_00.17.44 worker summary lines under spinner status

Current CLI spinner worker-telemetry contract:

- Worker activity is a side-channel payload parsed by shared progress helpers.
- Spinner keeps one primary status line, then renders one worker summary line per active worker below it.
- Worker summary state must be reset explicitly when a worker phase ends.
- Counter/ETA parsing must continue to read the primary status line unchanged.

Where this is used today:
- Label Studio freeform prelabel worker loops (`task X/Y` + segment ranges).
- Label Studio split-conversion worker loops (`job X/Y`).
