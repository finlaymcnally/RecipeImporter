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
  +--> [H] Benchmark vs freeform gold -----> mode picker ------------------> (single offline OR selected/all matched single-profile) -> [C]
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

- `Stage: Convert files from data/input into cookbook outputs`
- `Label Studio upload: Create labeling tasks (uploads)`
- `Label Studio export: Export completed labels into golden artifacts`
- `Evaluate vs freeform gold: Generate predictions and compare to your labels`
- `Dashboard: Build lifetime stats dashboard HTML`
- `Settings: Change worker/OCR/output defaults`
- `Exit: Close the tool`

Availability rule:

- `Import` and `Label Studio task upload` only appear when at least one supported top-level file exists in `data/input`.
- `inspect` remains available as a direct command (`cookimport inspect <path>`), not as an interactive menu action.

Menu numbering and shortcuts:

- `_menu_select` now shows Questionary shortcut labels on all select-style menus (for example `1)`, `2)`, ...).
- Numeric shortcuts (`1-9`, `0`) select immediately in interactive menus; non-numeric shortcuts still move focus and can be confirmed with Enter.

### [J] Settings

`Settings` edits global defaults in `cookimport.json`.

Interactive `Import` and benchmark runs (single-offline + matched-sets) ask:
- `Use Codex Farm recipe pipeline for this run?`
  - default is inferred from global `llm_recipe_pipeline` (`codex-farm-3pass-v1` => `Yes`, otherwise `No`),
  - `COOKIMPORT_TOP_TIER_PROFILE=codexfarm|vanilla` can force either profile and bypass the prompt.
- when codex is selected, chooser then asks:
  - `Codex Farm model override (blank for pipeline default)`
  - `Codex Farm reasoning effort override` (`Pipeline default`, `none`, `minimal`, `low`, `medium`, `high`, `xhigh`)

Resolved profile families:
- `CodexFarm automatic top-tier`:
  - use saved `quality-suite winner` settings when available (`.history/qualitysuite_winner_run_settings.json` for default repo-local output),
  - otherwise use built-in codex top-tier baseline (`quality-first` EPUB stack + codex recipe/line-role/atomic enabled),
  - built-in codex fallback baseline pins `codex_farm_pass1_pattern_hints_enabled=false`,
  - built-in codex fallback baseline pins `codex_farm_pass3_skip_pass2_ok=true`,
  - then harmonize to codex top-tier pipeline knobs (`llm_recipe_pipeline=codex-farm-3pass-v1`, `line_role_pipeline=codex-line-role-v1`, `atomic_block_splitter=atomic-v1`).
  - winner-provided `codex_farm_pass1_pattern_hints_enabled` remains tunable and is not overwritten by codex harmonization.
  - winner-provided `codex_farm_pass3_skip_pass2_ok` remains tunable and is not overwritten by codex harmonization.
- `Vanilla automatic top-tier`:
  - built-in deterministic baseline with codex disabled (`llm_recipe_pipeline=off`, `llm_knowledge_pipeline=off`, `llm_tags_pipeline=off`),
  - deterministic line-role + atomic splitter enabled (`line_role_pipeline=deterministic-v1`, `atomic_block_splitter=atomic-v1`),
  - EPUB parsing baseline pinned to `unstructured + v1 + br_split_v1 + skip_headers=false`.
  - vanilla baseline explicitly pins `codex_farm_pass1_pattern_hints_enabled=false` (inert while `llm_recipe_pipeline=off`).
  - vanilla baseline explicitly pins `codex_farm_pass3_skip_pass2_ok=true` (inert while `llm_recipe_pipeline=off`).

Config keys and defaults:

- `workers` (default `7`)
- `pdf_split_workers` (default `7`)
- `epub_split_workers` (default `7`)
- `all_method_max_parallel_sources` (default is CPU-aware, up to `4`)
- `all_method_source_scheduling` (default `tail_pair`)
- `all_method_source_shard_threshold_seconds` (default `1200`)
- `all_method_source_shard_max_parts` (default `3`)
- `all_method_source_shard_min_variants` (default `6`)
- `all_method_scheduler_scope` (default `global`)
- `all_method_max_inflight_pipelines` (default `4`)
- `all_method_max_split_phase_slots` (default `4`)
- `all_method_max_eval_tail_pipelines` (default follows split slots)
- `all_method_config_timeout_seconds` (default `600`; `0` disables timeout)
- `all_method_retry_failed_configs` (default `1`; `0` disables retries)
- `all_method_wing_backlog_target` (default follows split slots)
- `all_method_smart_scheduler` (default `true`)
- `benchmark_sequence_matcher` (default `dmp`; canonical-text matcher for benchmark/eval runs)
- `epub_extractor` (default `unstructured`)
- `epub_unstructured_html_parser_version` (default `v1`)
- `epub_unstructured_skip_headers_footers` (default `true`)
- `epub_unstructured_preprocess_mode` (default `semantic_v1`)
- `table_extraction` (default `off`)
- `section_detector_backend` (default `legacy`)
- `multi_recipe_splitter` (default `legacy`)
- `multi_recipe_trace` (default `false`)
- `multi_recipe_min_ingredient_lines` (default `1`)
- `multi_recipe_min_instruction_lines` (default `1`)
- `multi_recipe_for_the_guardrail` (default `true`)
- `instruction_step_segmentation_policy` (default `auto`)
- `instruction_step_segmenter` (default `heuristic_v1`)
- `web_schema_extractor` (default `builtin_jsonld`)
- `web_schema_normalizer` (default `simple`)
- `web_html_text_extractor` (default `bs4`)
- `web_schema_policy` (default `prefer_schema`)
- `web_schema_min_confidence` (default `0.75`)
- `web_schema_min_ingredients` (default `2`)
- `web_schema_min_instruction_steps` (default `1`)
- `ingredient_text_fix_backend` (default `none`)
- `ingredient_pre_normalize_mode` (default `legacy`)
- `ingredient_packaging_mode` (default `off`)
- `ingredient_parser_backend` (default `ingredient_parser_nlp`)
- `ingredient_unit_canonicalizer` (default `legacy`)
- `ingredient_missing_unit_policy` (default `null`)
- `p6_time_backend` (default `regex_v1`)
- `p6_time_total_strategy` (default `sum_all_v1`)
- `p6_temperature_backend` (default `regex_v1`)
- `p6_temperature_unit_backend` (default `builtin_v1`)
- `p6_ovenlike_mode` (default `keywords_v1`)
- `p6_yield_mode` (default `legacy_v1`)
- `p6_emit_metadata_debug` (default `false`)
- `recipe_scorer_backend` (default `heuristic_v1`)
- `recipe_score_gold_min` (default `0.75`)
- `recipe_score_silver_min` (default `0.55`)
- `recipe_score_bronze_min` (default `0.35`)
- `recipe_score_min_ingredient_lines` (default `1`)
- `recipe_score_min_instruction_lines` (default `1`)
- `ocr_device` (default `auto`)
- `pdf_ocr_policy` (default `auto`)
- `ocr_batch_size` (default `1`)
- `pdf_column_gap_ratio` (default `0.12`)
- `output_dir` (default `data/output`)
- `label_studio_url` (default unset; populated after first interactive Label Studio prompt)
- `label_studio_api_key` (default unset; populated after first interactive Label Studio prompt)
- `pdf_pages_per_job` (default `50`)
- `epub_spine_items_per_job` (default `10`)
- `warm_models` (default `false`)
- `llm_recipe_pipeline` (default `codex-farm-3pass-v1`)
- `llm_knowledge_pipeline` (default `off`)
- `llm_tags_pipeline` (default `off`)
- `codex_farm_cmd` (default `codex-farm`)
- `codex_farm_root` (default unset; falls back to `<repo_root>/llm_pipelines`)
- `codex_farm_workspace_root` (default unset; pipeline `codex_cd_mode` decides Codex `--cd`)
- `codex_farm_pipeline_pass1` (default `recipe.chunking.v1`)
- `codex_farm_pass1_pattern_hints_enabled` (default `false`)
- `codex_farm_pipeline_pass2` (default `recipe.schemaorg.v1`)
- `codex_farm_pipeline_pass3` (default `recipe.final.v1`)
- `codex_farm_pass3_skip_pass2_ok` (default `true`)
- `codex_farm_pipeline_pass4_knowledge` (default `recipe.knowledge.v1`)
- `codex_farm_pipeline_pass5_tags` (default `recipe.tags.v1`)
- `codex_farm_context_blocks` (default `30`)
- `codex_farm_knowledge_context_blocks` (default `12`)
- `tag_catalog_json` (default `data/tagging/tag_catalog.json`)
- `codex_farm_failure_mode` (default `fail`)

What each setting affects:

- `workers`, split workers, page/spine split size: `stage` and benchmark import parallelism/sharding.
- `all_method_max_parallel_sources`: all-matched source-level concurrency cap (how many books run at once).
- `all_method_source_scheduling`: source job order strategy (`discovery` legacy FIFO or `tail_pair` heavy/light interleave).
- `all_method_source_shard_threshold_seconds`, `all_method_source_shard_max_parts`, `all_method_source_shard_min_variants`: heavy-source sharding controls for all-matched runs (split one source’s variant set into multiple schedulable jobs).
- `all_method_scheduler_scope`: all-method all-matched scheduler implementation (`global` uses one run-wide config queue + run-wide eval-signature dedupe; `legacy` keeps per-source config schedulers).
- `all_method_max_inflight_pipelines`, `all_method_max_split_phase_slots`, `all_method_max_eval_tail_pipelines`, `all_method_wing_backlog_target`, `all_method_smart_scheduler`: all-method config scheduler controls (inflight cap, split-heavy slots, evaluate-tail cap, prewarm runway, smart/fixed admission mode; in `global` scope these apply to one run-wide scheduler, while in `legacy` scope they apply per source).
- `all_method_config_timeout_seconds`, `all_method_retry_failed_configs`: all-method safety controls (per-config timeout and failed-config retry passes).
- all-method canonical alignment cache root is resolved per run and shared across timestamps (default under `data/golden/benchmark-vs-golden/.cache/canonical_alignment`; override via `COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT`).
- `benchmark_sequence_matcher`: canonical-text alignment matcher mode for benchmark/eval flows (`dmp` only; non-`dmp` values are invalid). Loading `cookimport.json` coerces unsupported legacy values back to `dmp`.
- `epub_extractor`: runtime extractor choice via `C3IMP_EPUB_EXTRACTOR` (default-enabled choices: `unstructured`, `beautifulsoup`; `markdown`/`markitdown` are policy-locked off unless `COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS=1`).
- `epub_unstructured_html_parser_version`: parser version (`v1` or `v2`) passed into Unstructured HTML partitioning.
- `epub_unstructured_skip_headers_footers`: enables Unstructured `skip_headers_and_footers` for EPUB HTML partitioning.
- `epub_unstructured_preprocess_mode`: HTML pre-normalization mode before Unstructured (`none`, `br_split_v1`, or `semantic_v1` alias).
- `table_extraction`: deterministic non-recipe table detection/export (`tables.jsonl`, `tables.md`) and table-aware chunking behavior.
- `section_detector_backend`: section detector selection (`legacy|shared_v1`) used by stage and benchmark prediction generation for Text/Excel/EPUB/PDF importer section extraction.
- `multi_recipe_splitter`, `multi_recipe_trace`, `multi_recipe_min_*`, `multi_recipe_for_the_guardrail`: shared deterministic multi-recipe split controls used by Text/EPUB/PDF importer conversion in stage and benchmark prediction generation (`legacy|off|rules_v1` backend selection plus optional split trace artifact and coverage/guardrail thresholds).
- `instruction_step_segmentation_policy`, `instruction_step_segmenter`: deterministic fallback instruction-step segmentation controls shared by stage and benchmark prediction generation (`off|auto|always`, `heuristic_v1|pysbd_v1`).
- `web_schema_extractor`, `web_schema_normalizer`, `web_html_text_extractor`, `web_schema_policy`, `web_schema_min_*`: deterministic local HTML/JSON schema ingestion controls for `webschema` importer (schema backend, normalization mode, fallback text extractor, schema-vs-fallback policy, and confidence/min-line thresholds).
- `ingredient_text_fix_backend`, `ingredient_pre_normalize_mode`, `ingredient_packaging_mode`, `ingredient_parser_backend`, `ingredient_unit_canonicalizer`, `ingredient_missing_unit_policy`: ingredient parser normalization/backend/unit-policy controls used by stage and benchmark prediction-generation imports.
- `p6_time_backend`, `p6_time_total_strategy`, `p6_temperature_backend`, `p6_temperature_unit_backend`, `p6_ovenlike_mode`, `p6_yield_mode`, `p6_emit_metadata_debug`: Priority 6 deterministic instruction/yield controls for stage and benchmark prediction generation (time extraction backend and rollup strategy, temperature extraction/unit conversion backend, oven-like classifier mode, yield parser mode, and optional p6 debug sidecar emission).
- `recipe_scorer_backend`, `recipe_score_*`: deterministic recipe-likeness scoring and tier gating thresholds/minimum line hints used by all importer families.
- `ocr_device`, `pdf_ocr_policy`, `ocr_batch_size`: OCR path/policy for PDFs.
- `pdf_column_gap_ratio`: PDF column-boundary sensitivity (`page_width * ratio` threshold).
- `output_dir`: interactive `stage` target output root.
- `label_studio_url`, `label_studio_api_key`: interactive Label Studio import/export credential defaults.
- `warm_models`: preloads SpaCy, ingredient parser, and OCR model before staging.
- `llm_recipe_pipeline`: recipe codex-farm parsing correction flow (`off` or `codex-farm-3pass-v1`).
- `llm_knowledge_pipeline`: optional knowledge-harvest flow (`off` or `codex-farm-knowledge-v1`) used by `stage` only.
- `llm_tags_pipeline`: optional tags pass (`off` or `codex-farm-tags-v1`) used by `stage` only.
- `tag_catalog_json`: required catalog snapshot path when `llm_tags_pipeline` is enabled.
- `codex_farm_*`: codex-farm command/root/workspace/pipeline-id/context/failure behavior used by `stage`.

Developer note:
- Per-run setting definitions live in `cookimport/config/run_settings.py`. Interactive top-tier chooser logic lives in `cookimport/cli_ui/run_settings_flow.py`; keep import and benchmark aligned there.
- `stage(...)` is called both by Typer CLI dispatch and direct Python callers (interactive helpers/entrypoints/tests); it must coerce any Typer `OptionInfo` default objects back to plain values before normalization/building run settings.
- `stats_dashboard(...)` is also called directly from interactive helpers; it must coerce Typer `OptionInfo` defaults (`--serve/--host/--port` and related flags) before branching into serve mode.
- Interactive import should pass the full selected run-settings surface into `stage(...)` (including knowledge/tags pipeline toggles, pass4/pass5 pipeline IDs, and related context/catalog settings), not a partial subset.
- `import` / `C3import` entrypoint shims should forward the expanded stage run-settings arguments so persisted settings can affect direct-entrypoint runs.

### [D] Import Flow

`Import` steps:

1. Prompt for `Import All` or one selected file from top-level `data/input`.
2. Select one automatic top-tier profile family (`CodexFarm` or `Vanilla`) and resolve its deterministic run-settings profile (no full profile chooser and no codex yes/no prompt in this flow).
3. Applies selected EPUB env vars:
   - `C3IMP_EPUB_EXTRACTOR`
   - `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`
   - `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`
   - `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`
4. Calls `stage(...)` using the full selected run settings payload (workers/OCR/extractor + section/ingredient parser controls + LLM/codex-farm knobs).
   - When Codex Farm recipe/knowledge/tag passes run, stage now also writes prompt-debug artifacts under `<run_folder>/codexfarm/`:
   - `prompt_request_response_log.txt`
   - `full_prompt_log.jsonl`
   - `prompt_type_samples_from_full_prompt_log.md`
5. Uses `limit` only if `C3IMP_LIMIT` was set before entering interactive mode.
6. Prints `Outputs written to: <run_folder>`.
7. Returns to the main menu after successful import.

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
   - It also writes status telemetry under `<output_dir>/.history/processing_timeseries/<timestamp>__labelstudio_import__<source>.jsonl`.
   - It writes run files under `data/golden/sent-to-labelstudio`:
   - `label_studio_tasks.jsonl`
   - `coverage.json`
   - `extracted_archive.json`
   - `extracted_text.txt`
   - `manifest.json`
   - If Codex Farm recipe pass is enabled, this flow also writes prompt-debug artifacts under the run folder:
   - `codexfarm/prompt_request_response_log.txt`
   - `codexfarm/full_prompt_log.jsonl`
   - `codexfarm/prompt_type_samples_from_full_prompt_log.md`
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
   - By default, export writes to: `data/golden/pulled-from-labelstudio/<source_slug_or_project_slug>/exports/`.
   - When one source file is detectable, export uses the source filename stem slug so repeat pulls overwrite the same folder even if project names gain suffixes like `-2`.
   - If `--run-dir` is supplied in non-interactive mode, export writes to that run directory.
6. Prints export summary path and returns to the main menu.

### [H] Benchmark vs Freeform Gold Flow

Interactive benchmark now has a mode submenu before execution:

1. Shows benchmark mode picker:
   - `Single offline eval: One local prediction + eval vs freeform gold` (default first choice)
   - `Single config, selected matched sets: Pick which matched books to run`
   - `Single config, all matched sets: Repeat one config for every matched golden set`
2. Single offline path:
   - resolves one selected automatic top-tier run profile family (same resolver used by interactive import),
   - uses the resolved `llm_recipe_pipeline` to decide variant planning,
   - when run settings resolve to `llm_recipe_pipeline=codex-farm-3pass-v1`, runs paired variants under one timestamp session:
     - `single-offline-benchmark/<source_slug>/vanilla` first (`llm_recipe_pipeline=off`),
     - `single-offline-benchmark/<source_slug>/codexfarm` second (`llm_recipe_pipeline=codex-farm-3pass-v1`),
   - when run settings resolve to `llm_recipe_pipeline=off`, runs one variant under `single-offline-benchmark/<source_slug>/vanilla`,
   - each variant run calls `labelstudio-benchmark` with `--no-upload --eval-mode canonical-text`,
   - source slug is derived from the selected source filename stem (slugified),
   - for paired codex+vanilla runs, split conversion is cached once and reused across variants (default cache root: `.../single-offline-benchmark/<source_slug>/.split-cache`),
   - cache controls are available on `labelstudio-benchmark`: `--single-offline-split-cache-mode`, `--single-offline-split-cache-dir`, `--single-offline-split-cache-force`,
   - for codex-enabled paired runs, writes comparison artifacts only when both variant runs succeed:
     - `single-offline-benchmark/<source_slug>/codex_vs_vanilla_comparison.json` (always)
     - comparison JSON metadata now includes `per_label_breakdown` aggregated across the latest paired evals (`label`, strict `precision`, strict `recall`, `gold_total`, `pred_total`)
     - also writes `single-offline-benchmark/<source_slug>/starter_pack_v1/` by running the benchmark cutdown starter-pack builder in-place against the paired variant run dirs
     - paired starter-pack generation also writes `single-offline-benchmark/<source_slug>/benchmark_summary.md` (flattened comparison + starter-pack summary)
     - also writes a dedicated 3-file upload folder: `single-offline-benchmark/<source_slug>/upload_bundle_v1/`:
       - `upload_bundle_overview.md`
       - `upload_bundle_index.json`
       - `upload_bundle_payload.jsonl`
   - when markdown writes are enabled, single-offline writes one consolidated top-level markdown file:
     - `single-offline-benchmark/<source_slug>/single_offline_summary.md`
   - if one variant fails, successful variant artifacts are preserved and comparison artifacts are skipped,
   - defaults to writing markdown summaries on and Label Studio task artifacts off in interactive mode
     (set `COOKIMPORT_BENCH_WRITE_MARKDOWN=0` to disable summaries, and `COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS=1` to keep task JSONL).
   - keeps spinner/status visible for both prediction generation and evaluation phases,
   - split conversion progress uses the shared counter format from the first update (`Running split conversion... task 0/N`), with `(workers=N)` suffix when split jobs run in parallel,
   - does not resolve Label Studio credentials,
   - writes eval artifacts under `data/golden/benchmark-vs-golden/<timestamp>/single-offline-benchmark/<source_slug>/<variant>/`.
3. Single-profile matched-sets path:
   - uses the same compact automatic top-tier profile selector as single-offline,
   - discovers freeform exports and matches source hints to top-level importable files in `data/input` by filename,
   - selected-matched mode lets you toggle specific books and run only that subset (or choose `Run all matched books`),
   - defaults to writing markdown summaries on and Label Studio task artifacts off in interactive mode
     (set `COOKIMPORT_BENCH_WRITE_MARKDOWN=0` to disable summaries, and `COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS=1` to keep task JSONL).
   - prints matched/skipped counts and asks final proceed confirmation (`Proceed with N benchmark runs across N matched golden sets?` or `... across N selected matched books?`, default `No`),
   - normalizes variants from the selected run settings:
     - when `llm_recipe_pipeline=off`, runs one `vanilla` variant per selected book under `single-profile-benchmark/<index_source_slug>/`,
     - when `llm_recipe_pipeline=codex-farm-3pass-v1`, runs paired variants per selected book:
       - `single-profile-benchmark/<index_source_slug>/vanilla` first (`llm_recipe_pipeline=off`, deterministic-only),
       - `single-profile-benchmark/<index_source_slug>/codexfarm` second (`llm_recipe_pipeline=codex-farm-3pass-v1`, `line_role_pipeline=codex-line-role-v1`, `atomic_block_splitter=atomic-v1`),
   - for paired codex+vanilla selected/all-matched runs, writes per-book comparison only when both variants succeed:
     - `single-profile-benchmark/<index_source_slug>/codex_vs_vanilla_comparison.json`,
   - runs `labelstudio-benchmark` with `--no-upload --eval-mode canonical-text` for each planned variant run (no all-method variant expansion),
   - when 2+ books are selected, runs up to three books concurrently (`parallel books=3`),
   - concurrent single-profile runs downscale per-book `workers`, `pdf_split_workers`, and `epub_split_workers` to 80% of the chosen run-settings values,
   - concurrent single-profile runs enforce one shared split conversion slot (`split conversion slots=1`) across the selected books,
   - concurrent single-profile runs request up to two live spinner panels (`COOKIMPORT_LIVE_STATUS_SLOTS=2` override for this path); extra concurrent runs fall back to plain status lines instead of failing with Rich live-display conflicts,
   - continues when an individual source fails and prints a failure summary at the end,
   - writes eval artifacts under `data/golden/benchmark-vs-golden/<timestamp>/single-profile-benchmark/<index_source_slug>/` (paired runs nest under `/vanilla` and `/codexfarm`),
   - writes a dedicated 3-file upload folder per target eval root:
     - `single-profile-benchmark/<index_source_slug>/upload_bundle_v1/upload_bundle_overview.md`
     - `single-profile-benchmark/<index_source_slug>/upload_bundle_v1/upload_bundle_index.json`
     - `single-profile-benchmark/<index_source_slug>/upload_bundle_v1/upload_bundle_payload.jsonl`
   - multi-book runs also write one shared 3-file group upload folder:
     - `single-profile-benchmark/upload_bundle_v1/upload_bundle_overview.md`
     - `single-profile-benchmark/upload_bundle_v1/upload_bundle_index.json`
     - `single-profile-benchmark/upload_bundle_v1/upload_bundle_payload.jsonl`
     - group mode targets ~40MB and automatically lowers per-book sampled detail as selected-book count increases.
   - writes processed cookbook outputs under `<interactive output_dir>/<benchmark_timestamp>/single-profile-benchmark/<index_source_slug>/...`.
4. Returns to the main menu on completion.

For re-scoring an existing prediction run directly, use `cookimport labelstudio-eval`. For offline single-run benchmarking, use non-interactive `cookimport labelstudio-benchmark --no-upload`.

### [I] Generate Dashboard Flow

1. Runs `stats-dashboard` using the interactive `output_dir` setting as `--output-root`.
2. Uses `open_browser=False` in interactive mode (no browser auto-open prompt).
3. Writes dashboard files to `history_root_for_output(output_dir)/dashboard`.
4. Returns to the main menu on completion.

Note:
- History-writing commands (`stage`, `perf-report --write-csv`, `labelstudio-eval`, `labelstudio-benchmark`, and non-dry `benchmark-csv-backfill` with updates) now auto-run the same dashboard refresh process for their target history root.

### [Z] Exit Conditions

Interactive mode exits when:

- user selects `Exit` from the main menu.

## Command Surface

Top-level command groups:

- `cookimport stage`
- `cookimport debug-epub-extract`
- `cookimport epub <inspect|dump|unpack|blocks|candidates|validate>`
- `cookimport inspect`
- `cookimport labelstudio-import`
- `cookimport labelstudio-export`
- `cookimport labelstudio-eval`
- `cookimport labelstudio-benchmark`
- `cookimport perf-report`
- `cookimport benchmark-csv-backfill`
- `cookimport stats-dashboard`
- `cookimport bench <speed-discover|speed-run|speed-compare|quality-discover|quality-run|quality-leaderboard|quality-compare|eval-stage>`
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
Each stage run folder also includes `processing_timeseries.jsonl` (status snapshots + CPU utilization samples).
After stage history CSV append, the CLI also auto-refreshes dashboard artifacts under `history_root_for_output(<out>)/dashboard` (best effort).
Stage job worker fallback order is `process -> subprocess-backed workers -> thread -> serial`; if process workers are denied in sandboxed runtimes, stage emits a warning that it switched to subprocess-backed worker concurrency.
Use `--require-process-workers` to fail fast instead of using any fallback backend.
When thread fallback is active, `processing_timeseries.jsonl` worker labels include thread names so concurrent workers are visible (instead of collapsing to one `MainProcess` label).
Stage completion also prints a compact `Quick run summary` block (books, codex-farm on/off state, selected major settings, topline metrics) and always writes `<run_dir>/run_summary.json`.
When `--write-markdown` is enabled (default), stage also writes `<run_dir>/run_summary.md`; `--no-write-markdown` suppresses the markdown summary file.

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
- `--require-process-workers / --allow-worker-fallback` (default allow fallback): fail fast when process workers are unavailable instead of falling back to subprocess/thread/serial.
- `--pdf-split-workers INTEGER>=1` (default `7`): max workers for one split PDF.
- `--epub-split-workers INTEGER>=1` (default `7`): max workers for one split EPUB.
- `--write-markdown / --no-write-markdown` (default write): write markdown sidecar artifacts (`sections.md`, `tips.md`, `topic_candidates.md`, `chunks.md`, `tables.md`).
- `--epub-extractor TEXT` (default `unstructured`): default-enabled values are `unstructured|beautifulsoup`; `markdown|markitdown` are rejected unless `COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS=1`. Exported to `C3IMP_EPUB_EXTRACTOR` for importer runtime.
- `--epub-unstructured-html-parser-version TEXT` (default `v1`): `v1|v2`; exported to `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`.
- `--epub-unstructured-skip-headers-footers / --no-epub-unstructured-skip-headers-footers` (default enabled): exported to `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`.
- `--epub-unstructured-preprocess-mode TEXT` (default `semantic_v1`): `none|br_split_v1|semantic_v1`; exported to `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`.
- `--table-extraction TEXT` (default `off`): `off|on` deterministic table detection/export and table-aware chunking.
- `--recipe-scorer-backend TEXT` (default `heuristic_v1`): recipe-likeness scorer backend.
- `--recipe-score-gold-min FLOAT` (default `0.75`): minimum score for `gold` tier.
- `--recipe-score-silver-min FLOAT` (default `0.55`): minimum score for `silver` tier.
- `--recipe-score-bronze-min FLOAT` (default `0.35`): minimum score for `bronze` tier.
- `--recipe-score-min-ingredient-lines INTEGER>=0` (default `1`): soft minimum ingredient line hint for scoring/gating.
- `--recipe-score-min-instruction-lines INTEGER>=0` (default `1`): soft minimum instruction line hint for scoring/gating.
- `--section-detector-backend TEXT` (default `legacy`): `legacy|shared_v1`; controls importer section extraction backend.
- `--multi-recipe-splitter TEXT` (default `legacy`): `legacy|off|rules_v1`; controls shared multi-recipe candidate split backend for Text/EPUB/PDF importers.
- `--multi-recipe-trace / --no-multi-recipe-trace` (default disabled): write `multi_recipe_split_trace` raw artifact from shared splitter when enabled.
- `--multi-recipe-min-ingredient-lines INTEGER>=0` (default `1`): minimum ingredient-signal lines per side for `rules_v1` split acceptance.
- `--multi-recipe-min-instruction-lines INTEGER>=0` (default `1`): minimum instruction-signal lines per side for `rules_v1` split acceptance.
- `--multi-recipe-for-the-guardrail / --no-multi-recipe-for-the-guardrail` (default enabled): enable section-detector-backed `For the X` false-boundary guard in shared splitter.
- `--web-schema-extractor TEXT` (default `builtin_jsonld`): `builtin_jsonld|extruct|scrape_schema_recipe|recipe_scrapers|ensemble_v1`.
- `--web-schema-normalizer TEXT` (default `simple`): `simple|pyld`.
- `--web-html-text-extractor TEXT` (default `bs4`): `bs4|trafilatura|readability_lxml|justext|boilerpy3|ensemble_v1`.
- `--web-schema-policy TEXT` (default `prefer_schema`): `prefer_schema|schema_only|heuristic_only`.
- `--web-schema-min-confidence FLOAT` (default `0.75`): minimum schema confidence before schema candidate acceptance.
- `--web-schema-min-ingredients INTEGER>=0` (default `2`): minimum ingredient lines used in schema confidence scoring.
- `--web-schema-min-instruction-steps INTEGER>=0` (default `1`): minimum instruction lines used in schema confidence scoring.
- `--llm-recipe-pipeline TEXT` (default `codex-farm-3pass-v1`): `off|codex-farm-3pass-v1`.
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
- backfills missing benchmark runtime metadata (`run_config_json/hash/summary`, codex model/effort) from nearby manifests
- backfills missing benchmark token columns (`tokens_input`, `tokens_cached_input`, `tokens_output`, `tokens_reasoning`, `tokens_total`) from nearby prediction manifests when telemetry is present
- writes updates in-place to the CSV unless `--dry-run` is used
- when rows are written, auto-refreshes dashboard artifacts for that history root
- command output includes token backfill counters (`Token rows filled`, `Token fields filled`)

Options:

- `--out-dir PATH` (default `data/output`): used to resolve default CSV path (`.history/performance_history.csv` for repo-local outputs; `<out-dir parent>/.history/performance_history.csv` for external outputs).
- `--history-csv PATH`: explicit CSV path override.
- `--dry-run` (default `false`): report how many rows would be patched without writing.

### `cookimport stats-dashboard`

Builds static lifetime dashboard HTML from output/golden data.

Options:

- `--output-root PATH` (default `data/output`): staged import root.
- `--golden-root PATH` (default `data/golden`): benchmark/golden artifacts root.
- `--out-dir PATH` (default `.history/dashboard`): dashboard output directory.
- `--open` (default `false`): opens generated HTML in default browser.
- `--serve` (default `false`): serve dashboard over local HTTP and enable program-side UI-state sync (`assets/dashboard_ui_state.json`).
- `--host TEXT` (default `127.0.0.1`): host interface for `--serve`.
- `--port INTEGER` (default `8765`): port for `--serve` (`0` picks a free port).
- `--since-days INTEGER`: include only recent runs.
- `--scan-reports` (default `false`): force scanning per-file report JSON instead of cached summaries.
- `--scan-benchmark-reports` (default `false`): force recursive benchmark eval report scanning under `--golden-root`.

### `cookimport compare-control run`

Backend one-shot Compare & Control query command. This runs the same analytics domain as dashboard `Previous Runs -> Compare & Control`, but returns JSON in terminal output.

Usage patterns:

- Flag-driven query: set `--action` plus optional `--view`, `--outcome-field`, `--compare-field`, `--hold-constant-field`, `--split-field`, and `--filters-json`.
- Query-file driven: pass `--query-file` with either:
  - payload object only, or
  - `{ \"action\": \"...\", \"payload\": { ... } }`.
- Discovery tuning (for `discover` cards): optionally pass
  - `--discover-exclude-field FIELD` (repeatable),
  - `--discover-prefer-field FIELD` (repeatable),
  - `--discover-demote-pattern TEXT` (repeatable substring match),
  - `--discover-max-cards N`.

Actions:

- `analyze` (default)
- `discover`
- `fields`
- `suggest_hold_constants`
- `suggest_splits`
- `insights` (auto-profile rows + drivers + process-factor deltas + suggested follow-up queries)
- `subset_filter_patch`
- `ping`

Output contract:

- Always prints JSON.
- Top-level parse/input errors still exit non-zero (standard CLI behavior).
- Analysis-domain errors are structured JSON (`ok=false`, `error.code`, `error.message`, optional `error.details`).

### `cookimport compare-control agent`

Persistent JSONL session over stdin/stdout for tool/agent workflows.

Protocol:

- Input: one JSON object per line with `id`, `action`, `payload`.
- Output: one JSON object per line, preserving request `id` when provided.
- Malformed lines return structured errors and do not terminate the process.

Supported actions:

- `load`, `fields`, `discover`, `analyze`, `suggest_hold_constants`, `suggest_splits`, `insights`, `subset_filter_patch`, `reset`, `ping`

### `cookimport compare-control discovery-preferences`

Updates dashboard `Compare & Control -> discover` card preferences in `assets/dashboard_ui_state.json` so backend tools can influence what cards are surfaced/emphasized.

Common usage:

- Show current preferences:
  - `cookimport compare-control discovery-preferences --show-only`
- Exclude noisy path/hash fields and prefer actionable fields:
  - `cookimport compare-control discovery-preferences --exclude-field processed_report_path --exclude-field run_config_hash --prefer-field ai_model --prefer-field ai_effort`
- Reset to defaults:
  - `cookimport compare-control discovery-preferences --reset`

Options:

- `--output-root PATH` (default `data/output`): used to resolve default dashboard dir.
- `--dashboard-dir PATH`: explicit dashboard dir override.
- `--show-only`: print effective preferences without writing.
- `--reset`: restore defaults.
- `--exclude-field TEXT` (repeatable): hide these fields from discovery cards.
- `--prefer-field TEXT` (repeatable): boost these fields in discovery ranking.
- `--demote-pattern TEXT` (repeatable): demote discovery fields containing these substrings.
- `--max-cards INTEGER` (`1..40`): max discovery cards shown.

### `cookimport labelstudio-import PATH`

Creates Label Studio tasks from one source file.
The prediction run directory now includes `run_manifest.json`.
Split conversion worker fallback order during prediction generation is `process -> thread -> serial`; serial fallback warning appears only when thread worker startup also fails.

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
- `--codex-model TEXT`: explicit Codex model for prelabel calls (defaults to `COOKIMPORT_CODEX_MODEL` or your Codex CLI default model).
- `--codex-thinking-effort`, `--codex-reasoning-effort` (alias flags): Codex reasoning-effort hint (`none|minimal|low|medium|high|xhigh`, normalized per model compatibility).
- `--prelabel-timeout-seconds INTEGER>=1` (default `600`): timeout per provider call.
- `--prelabel-cache-dir PATH`: optional prompt/response cache directory.
- `--prelabel-workers INTEGER>=1` (default `15`): concurrent freeform prelabel provider calls (`1` keeps serialized behavior).
- `--prelabel-upload-as TEXT` (default `annotations`): `annotations|predictions`.
- `--prelabel-granularity TEXT` (default `block`): `block|span` (`block` = block based; `span` = actual freeform).
- `--prelabel-allow-partial / --no-prelabel-allow-partial` (default disabled): continue upload when some prelabels fail.
- `--llm-recipe-pipeline TEXT` (default `off`): `off|codex-farm-3pass-v1`.
- `--codex-farm-cmd TEXT` (default `codex-farm`): subprocess command used when `--llm-recipe-pipeline` is enabled.
- `--codex-farm-root PATH` (default unset): optional codex-farm pipeline-pack root; defaults to `<repo_root>/llm_pipelines`.
- `--codex-farm-workspace-root PATH` (default unset): optional workspace root passed to codex-farm (`--workspace-root`).
- `--codex-farm-pipeline-pass1 TEXT` (default `recipe.chunking.v1`): pass-1 pipeline id.
- `--codex-farm-pipeline-pass2 TEXT` (default `recipe.schemaorg.v1`): pass-2 pipeline id.
- `--codex-farm-pipeline-pass3 TEXT` (default `recipe.final.v1`): pass-3 pipeline id.
- `--codex-farm-context-blocks INTEGER>=0` (default `30`): context blocks before/after candidate in pass-1 bundles.
- `--codex-farm-failure-mode TEXT` (default `fail`): `fail|fallback` behavior when codex-farm setup/invocation fails.

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
- `--llm-recipe-pipeline TEXT` (optional): eval-manifest metadata override; defaults to prediction-run run-config value (fallback `off`).
- `--atomic-block-splitter TEXT` (optional): eval-manifest metadata override; defaults to prediction-run run-config value (fallback `off`).
- `--line-role-pipeline TEXT` (optional): eval-manifest metadata override; defaults to prediction-run run-config value (fallback `off`).
- On successful benchmark CSV append, auto-refreshes dashboard artifacts for that history root.

### `cookimport labelstudio-benchmark`

Prediction+eval flow against freeform gold spans (upload or offline).
Also supports an explicit compare action for baseline-vs-candidate all-method report gating.

Behavior note:

- Non-interactive upload path: generates predictions, uploads to Label Studio, then evaluates.
- Non-interactive offline path: `--no-upload` generates predictions locally and evaluates with no Label Studio credentials/API calls.
- `cookimport labelstudio-benchmark compare --baseline ... --candidate ...` compares two all-method benchmark outputs and writes timestamped gate reports (`comparison.json`, `comparison.md`) under `--compare-out`.
- Offline prediction generation can skip non-scoring side artifacts via:
  - `--no-write-markdown` to skip markdown sidecars in processed stage outputs.
  - `--no-write-labelstudio-tasks` to skip `label_studio_tasks.jsonl` in offline pred-runs (stage-block scoring remains unchanged because it reads stage evidence + extracted archive).
- Eval mode is configurable via `--eval-mode stage-blocks|canonical-text` (default `stage-blocks`).
- Execution mode is configurable via `--execution-mode legacy|pipelined|predict-only` (default `legacy`).
- Single-offline split-cache controls:
  - `--single-offline-split-cache-mode off|auto` toggles split cache usage.
  - `--single-offline-split-cache-dir PATH` overrides cache root.
  - `--single-offline-split-cache-force` forces cache rebuild for that run.
- Prediction-record roundtrip supports evaluate-only replays:
  - `--predictions-out` writes prediction-stage records to JSONL.
  - `--predictions-in` skips generation and evaluates from a prior record JSONL.
  - `--predictions-in` and `--predictions-out` are mutually exclusive.
- Re-scoring an old prediction run without regeneration is still done with `cookimport labelstudio-eval --pred-run ... --gold-spans ...`.
- Interactive mode (`cookimport` -> Benchmark) always runs offline benchmark generation/eval (`single offline` or single-profile matched-set modes).
- Successful runs persist benchmark timing under `eval_report.json` `timing`, including prediction/evaluation/write/history subphase timings and checkpoints.
- Benchmark spinner telemetry is also persisted per phase:
  - `<eval_output_dir>/processing_timeseries_prediction.jsonl`
  - `<eval_output_dir>/processing_timeseries_evaluation.jsonl` (when evaluation runs)
- Benchmark CSV append now receives that timing payload and records benchmark runtime columns in `performance_history.csv`.
- Single benchmark runs auto-refresh dashboard artifacts after CSV append.
- All-method benchmark internals suppress per-config refresh and refresh once per source batch.
- All-method evaluate-only replay failures now preserve the underlying `_fail(...)` message in report rows instead of opaque `error: "1"` exit-code strings.
- Non-interactive benchmark runs now also emit a dedicated 3-file upload folder under each eval root:
  - `<eval_output_dir>/upload_bundle_v1/upload_bundle_overview.md`
  - `<eval_output_dir>/upload_bundle_v1/upload_bundle_index.json`
  - `<eval_output_dir>/upload_bundle_v1/upload_bundle_payload.jsonl`

Options:

- `--gold-spans PATH`: freeform gold file; if omitted, prompt from discovered exports.
- `--source-file PATH`: source file to re-import for predictions; if omitted, prompt/infer.
- `ACTION` positional (default `run`): `run|compare`.
- `--output-dir PATH` (default `data/golden/benchmark-vs-golden`): scratch root for prediction import artifacts.
- `--processed-output-dir PATH` (default `data/output`): root for staged cookbook outputs generated during benchmark.
- `--eval-output-dir PATH`: destination for benchmark report artifacts.
- `--overlap-threshold FLOAT 0..1` (default `0.5`): match threshold.
- `--force-source-match` (default `false`): ignore source identity checks while matching.
- `--eval-mode TEXT` (default `stage-blocks`): `stage-blocks|canonical-text`.
- `--sequence-matcher TEXT` (default `dmp`): canonical-text matcher mode (`dmp` only).
- `--pdf-ocr-policy TEXT` (default `auto`): `off|auto|always` OCR policy for PDF prediction generation.
- `--pdf-column-gap-ratio FLOAT` (default `0.12`): PDF column-gap threshold ratio for column reconstruction.
- `--execution-mode TEXT` (default `legacy`): `legacy|pipelined|predict-only`.
- `--single-offline-split-cache-mode TEXT` (default `off`): `off|auto` split-cache mode for offline benchmark prediction generation.
- `--single-offline-split-cache-dir PATH`: optional root for single-offline split-cache entries.
- `--single-offline-split-cache-force / --no-single-offline-split-cache-force` (default disabled): force split-cache rebuild for the current run.
- `--predictions-out PATH`: optional JSONL output for prediction-stage records (for later evaluate-only runs).
- `--predictions-in PATH`: optional JSONL input to run evaluate-only without generating predictions.
- `--baseline PATH`: compare action only; baseline all-method benchmark directory or report JSON path.
- `--candidate PATH`: compare action only; candidate all-method benchmark directory or report JSON path.
- `--compare-out PATH` (default `data/golden/benchmark-vs-golden/comparisons`): compare action output root for timestamped reports.
- `--fail-on-regression / --no-fail-on-regression` (default disabled): compare action exits non-zero when verdict is FAIL.
- `--pipeline TEXT` (default `auto`): importer selection.
- `--project-name TEXT`: explicit prediction project name.
- `--allow-labelstudio-write / --no-allow-labelstudio-write` (default disabled): required gate for upload mode.
- `--no-upload` (default `false`): force offline benchmark (no upload, no credential resolution).
- `--write-markdown / --no-write-markdown` (default write): write markdown sidecar artifacts for processed outputs generated during benchmark prediction runs.
- `--write-labelstudio-tasks / --no-write-labelstudio-tasks` (default write): write `label_studio_tasks.jsonl` in offline pred-runs (`--no-upload` only).
- `--overwrite / --resume` (default `--resume`): recreate prediction project or resume.
- `--label-studio-url TEXT`: explicit Label Studio URL.
- `--label-studio-api-key TEXT`: explicit Label Studio API key.
- `--workers INTEGER>=1` (default `7`): prediction import process workers.
- `--pdf-split-workers INTEGER>=1` (default `7`): PDF split workers for prediction import.
- `--epub-split-workers INTEGER>=1` (default `7`): EPUB split workers for prediction import.
- `--pdf-pages-per-job INTEGER>=1` (default `50`): PDF shard size.
- `--epub-spine-items-per-job INTEGER>=1` (default `10`): EPUB shard size.
- `--epub-extractor TEXT` (default `unstructured`): default-enabled values are `unstructured|beautifulsoup`; `markdown|markitdown` are rejected unless `COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS=1`. Exported to `C3IMP_EPUB_EXTRACTOR` for prediction import runtime.
- `--epub-unstructured-html-parser-version TEXT` (default `v1`): `v1|v2`; exported to `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`.
- `--epub-unstructured-skip-headers-footers / --no-epub-unstructured-skip-headers-footers` (default enabled): exported to `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`.
- `--epub-unstructured-preprocess-mode TEXT` (default `semantic_v1`): `none|br_split_v1|semantic_v1`; exported to `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`.
- `--recipe-scorer-backend TEXT` (default `heuristic_v1`): recipe-likeness scorer backend.
- `--recipe-score-gold-min FLOAT` (default `0.75`): minimum score for `gold` tier.
- `--recipe-score-silver-min FLOAT` (default `0.55`): minimum score for `silver` tier.
- `--recipe-score-bronze-min FLOAT` (default `0.35`): minimum score for `bronze` tier.
- `--recipe-score-min-ingredient-lines INTEGER>=0` (default `1`): soft minimum ingredient line hint for scoring/gating.
- `--recipe-score-min-instruction-lines INTEGER>=0` (default `1`): soft minimum instruction line hint for scoring/gating.
- `--section-detector-backend TEXT` (default `legacy`): `legacy|shared_v1`; controls importer section extraction backend for prediction generation.
- `--multi-recipe-splitter TEXT` (default `legacy`): `legacy|off|rules_v1`; controls shared multi-recipe candidate split backend for Text/EPUB/PDF prediction imports.
- `--multi-recipe-trace / --no-multi-recipe-trace` (default disabled): write `multi_recipe_split_trace` raw artifact from shared splitter when enabled.
- `--multi-recipe-min-ingredient-lines INTEGER>=0` (default `1`): minimum ingredient-signal lines per side for `rules_v1` split acceptance.
- `--multi-recipe-min-instruction-lines INTEGER>=0` (default `1`): minimum instruction-signal lines per side for `rules_v1` split acceptance.
- `--multi-recipe-for-the-guardrail / --no-multi-recipe-for-the-guardrail` (default enabled): enable section-detector-backed `For the X` false-boundary guard in shared splitter.
- `--web-schema-extractor TEXT` (default `builtin_jsonld`): `builtin_jsonld|extruct|scrape_schema_recipe|recipe_scrapers|ensemble_v1`.
- `--web-schema-normalizer TEXT` (default `simple`): `simple|pyld`.
- `--web-html-text-extractor TEXT` (default `bs4`): `bs4|trafilatura|readability_lxml|justext|boilerpy3|ensemble_v1`.
- `--web-schema-policy TEXT` (default `prefer_schema`): `prefer_schema|schema_only|heuristic_only`.
- `--web-schema-min-confidence FLOAT` (default `0.75`): minimum schema confidence before schema candidate acceptance.
- `--web-schema-min-ingredients INTEGER>=0` (default `2`): minimum ingredient lines used in schema confidence scoring.
- `--web-schema-min-instruction-steps INTEGER>=0` (default `1`): minimum instruction lines used in schema confidence scoring.
- `--llm-recipe-pipeline TEXT` (default `codex-farm-3pass-v1`): `off|codex-farm-3pass-v1`.
- `--codex-farm-recipe-mode TEXT` (default `extract`): `extract|benchmark`.
- `--codex-farm-cmd TEXT` (default `codex-farm`): subprocess command used to invoke codex-farm during prediction generation.
- `--codex-farm-root PATH` (default unset): optional codex-farm pipeline-pack root; defaults to `<repo_root>/llm_pipelines`.
- `--codex-farm-workspace-root PATH` (default unset): optional workspace root passed to codex-farm (`--workspace-root`).
- `--codex-farm-pipeline-pass1 TEXT` (default `recipe.chunking.v1`): pass-1 pipeline id (recipe chunking/boundary).
- `--codex-farm-pipeline-pass2 TEXT` (default `recipe.schemaorg.v1`): pass-2 pipeline id (schema.org extraction).
- `--codex-farm-pipeline-pass3 TEXT` (default `recipe.final.v1`): pass-3 pipeline id (final draft generation).
- `--codex-farm-context-blocks INTEGER>=0` (default `30`): context blocks before/after candidate for pass1 bundles.
- `--codex-farm-failure-mode TEXT` (default `fail`): `fail|fallback` behavior when codex-farm setup/invocation fails.
- `--alignment-cache-dir PATH` (internal/hidden): optional canonical alignment cache directory override for benchmark runs.
- `markitdown` note: prediction EPUB split jobs are disabled for this extractor for the same reason as stage runs.
- explicit-choice note: prediction generation no longer supports `--epub-extractor auto`; requested/effective extractor values are the selected concrete backend.
- `--ocr-device TEXT` (default `auto`): `auto|cpu|cuda|mps`.
- `--ocr-batch-size INTEGER>=1` (default `1`): pages per OCR model call.
- `--warm-models` (default `false`): preload OCR/parsing models before prediction import.

Upload requirement:

- Upload mode is blocked unless `--allow-labelstudio-write` is set.

### `cookimport bench speed-discover`

Builds a speed-suite manifest by matching pulled freeform gold exports to importable source files.

Options:

- `--gold-root PATH` (default `data/golden/pulled-from-labelstudio`): root containing pulled gold export folders.
- `--input-root PATH` (default `data/input`): root containing source files for import runs.
- `--out PATH` (default `data/golden/bench/speed/suites/pulled_from_labelstudio.json`): destination for generated speed-suite JSON.

### `cookimport bench speed-run`

Runs deterministic speed scenarios for a speed suite and writes timestamped run artifacts (`summary.json`, `report.md`, `samples.jsonl`, `run_manifest.json`).

Status behavior:

- Spinner updates include `task X/Y` counters per target/scenario/sample phase.
- Spinner telemetry is persisted under `<out_dir>/.history/processing_timeseries/<timestamp>__bench_speed_run__<suite>.jsonl`.

Options:

- `--suite PATH` (required): path to speed suite JSON (typically from `bench speed-discover`).
- `--out-dir PATH` (default `data/golden/bench/speed/runs`): output root for timestamped speed runs.
- `--scenarios TEXT` (default `stage_import,benchmark_canonical_legacy`): comma-separated scenario list from `stage_import|benchmark_canonical_legacy|benchmark_canonical_pipelined|benchmark_all_method_multi_source`.
- `--warmups INTEGER>=0` (default `1`): warmup samples per target+scenario (excluded from medians).
- `--repeats INTEGER>=1` (default `2`): measured samples per target+scenario.
- `--max-targets INTEGER>=1`: optional cap on number of targets from the suite.
- `--max-parallel-tasks INTEGER>=1`: optional fixed SpeedSuite task concurrency cap. When omitted, speed-run auto-selects `min(total_tasks, cpu_count, 4)`.
- `--require-process-workers / --allow-worker-fallback` (default allow fallback): fail fast when stage/all-method internals cannot use process workers.
- `--resume-run-dir PATH`: resume an existing speed run directory and skip tasks with completed sample snapshots.
- `--run-settings-file PATH`: optional JSON payload in `RunSettings` shape for deterministic speed-run settings.
- `--sequence-matcher TEXT`: optional canonical-text matcher override for benchmark scenarios (when omitted, uses `benchmark_sequence_matcher` from effective run settings).
- `--include-codex-farm / --no-include-codex-farm` (default disabled): include Codex Farm recipe-pipeline permutations in all-method scenarios.
- `--speedsuite-codex-farm-confirmation TEXT`: required with `--include-codex-farm`; must be `I_HAVE_EXPLICIT_USER_CONFIRMATION`.
- `--codex-farm-model TEXT`: optional Codex Farm model override (blank keeps pipeline defaults).
- `--codex-farm-thinking-effort|--codex-farm-reasoning-effort TEXT`: optional Codex Farm reasoning-effort override (`none|minimal|low|medium|high|xhigh`) (blank keeps pipeline defaults).

### `cookimport bench speed-compare`

Compares baseline and candidate speed runs and emits a timestamped comparison report.

Options:

- `--baseline PATH` (required): baseline speed run directory (`summary.json` required).
- `--candidate PATH` (required): candidate speed run directory (`summary.json` required).
- `--out-dir PATH` (default `data/golden/bench/speed/comparisons`): output root for comparison reports.
- `--regression-pct FLOAT>=0` (default `5.0`): percent threshold for regression detection (used with absolute floor).
- `--absolute-seconds-floor FLOAT>=0` (default `0.5`): minimum absolute seconds increase required to mark regression.
- `--fail-on-regression / --no-fail-on-regression` (default disabled): exit non-zero when verdict is `FAIL`.
- `--allow-settings-mismatch / --no-allow-settings-mismatch` (default disabled): allow timing verdicts when baseline/candidate `run_settings_hash` differ.

### `cookimport bench quality-discover`

Builds a deterministic quality-suite manifest by matching pulled freeform gold exports to source files in `data/input`. Discovery now prefers this curated target-id order when matched: `saltfatacidheatcutdown`, `thefoodlabcutdown`, `seaandsmokecutdown`, `dinnerfor2cutdown`, `roastchickenandotherstoriescutdown`; otherwise it falls back to representative stratified selection. If importer-scored discovery returns zero files, it retries against non-hidden filenames in `--input-root`. Selection metadata now includes per-format counts (`format_counts`, `selected_format_counts`) and per-target `source_extension`.

Options:

- `--gold-root PATH` (default `data/golden/pulled-from-labelstudio`): root containing pulled gold export folders.
- `--input-root PATH` (default `data/input`): root containing source files for import runs.
- `--out PATH` (default `data/golden/bench/quality/suites/pulled_representative.json`): destination for generated quality-suite JSON.
- `--max-targets INTEGER>=1`: optional cap for selected targets (curated focus when available, representative fallback otherwise).
- `--seed INTEGER` (default `42`): deterministic selection seed stored in suite metadata.
- `--formats TEXT`: optional comma-separated extension filter (for example `.pdf,.epub`) applied before suite selection.
- `--prefer-curated/--no-prefer-curated` (default prefer curated): opt out of curated CUTDOWN-first selection behavior.

### `cookimport bench quality-run`

Runs all-method quality experiments for one quality suite and writes timestamped run artifacts (`suite_resolved.json`, `experiments_resolved.json`, `summary.json`, `report.md`). While running, it also writes crash-safe incremental artifacts (`checkpoint.json`, `summary.partial.json`, `report.partial.md`, and per-experiment `quality_experiment_result.json`) so interrupted runs can be resumed with `--resume-run-dir`. Experiment-level execution is CPU-aware by default (auto cap + adaptive worker target based on host load; default auto ceiling follows detected CPU count, override with `COOKIMPORT_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS`); override with `--max-parallel-experiments` to force a fixed cap. When process-pool probing fails in auto mode (common in `/dev/shm`-restricted runtimes), quality-run switches experiment fanout to subprocess workers to avoid thread/GIL bottlenecks; override with `COOKIMPORT_QUALITY_EXPERIMENT_EXECUTOR_MODE=thread|subprocess|auto`. By default, quality-run now also writes an AI-agent bridge bundle at `<run_dir>/agent_compare_control/` containing Compare & Control insights plus ready JSONL requests.

Status behavior:

- Spinner updates include `task X/Y` counters per experiment.
- Spinner telemetry is persisted under `<out_dir>/.history/processing_timeseries/<timestamp>__bench_quality_run__<suite>.jsonl`.

Options:

- `--suite PATH` (required): path to quality suite JSON (typically from `bench quality-discover`).
- `--experiments-file PATH` (required): JSON experiment definitions (schema v1 explicit experiments, or schema v2 with `levers` + optional `all_method_runtime_patch`).
- `--out-dir PATH` (default `data/golden/bench/quality/runs`): output root for timestamped quality runs.
- `--resume-run-dir PATH`: resume an existing quality-run directory and skip completed experiments from checkpoint snapshots.
- `--base-run-settings-file PATH`: optional base `RunSettings` JSON payload used by all experiments. When omitted, uses `experiments.base_run_settings_file` or `cookimport.json`.
- `--max-parallel-experiments INTEGER>=1` (optional): fixed experiment-level concurrency cap for quality-run. When omitted, quality-run auto-selects a CPU-aware adaptive cap.
- `--require-process-workers / --allow-worker-fallback` (default allow fallback): fail fast when per-experiment all-method config workers cannot use process pools.
- `--include-deterministic-sweeps / --no-include-deterministic-sweeps` (default disabled): expand each experiment’s all-method grid with deterministic Priority 2–6 sweep variants (section detector, multi-recipe splitter, ingredient missing-unit policy, instruction segmentation, time/temp/yield knobs).
- `--include-codex-farm / --no-include-codex-farm` (default disabled): include Codex Farm recipe-pipeline permutations in all-method runs.
- `--qualitysuite-codex-farm-confirmation TEXT`: required with `--include-codex-farm`; must be `I_HAVE_EXPLICIT_USER_CONFIRMATION`.
- `--codex-farm-model TEXT`: optional Codex Farm model override applied to all experiments.
- `--codex-farm-thinking-effort|--codex-farm-reasoning-effort TEXT`: optional Codex Farm reasoning-effort override (`none|minimal|low|medium|high|xhigh`) applied to all experiments.
- `--qualitysuite-agent-bridge / --no-qualitysuite-agent-bridge` (default enabled): write `<run_dir>/agent_compare_control/` with compare-control insight JSON + `agent_requests.jsonl`.
- `--qualitysuite-agent-bridge-since-days INTEGER` (optional): bound compare-control history scan when building bridge artifacts.
- `--qualitysuite-agent-bridge-output-root PATH` (default `data/output`): compare-control output root used for bridge generation.
- `--qualitysuite-agent-bridge-golden-root PATH` (default `data/golden`): compare-control golden root used for bridge generation.

AI-agent handoff flow (default bridge on):

1. Read `<run_dir>/agent_compare_control/qualitysuite_compare_control_index.json`.
2. Open one scope insight file (for example `experiment_baseline__strict_accuracy.json`).
3. Run `<run_dir>/agent_compare_control/agent_requests.jsonl` through `cookimport compare-control agent`.

Quick tuning guide for `--max-parallel-experiments`:

| Experiment count | Suggested setting |
| --- | --- |
| 1-2 | omit flag (auto) or `2` |
| 3-6 | omit flag (auto) or `3-4` |
| 7-12 | omit flag (auto) or `5-8` |
| 13+ | omit flag (auto) or `8-32` (watch thermals/background load) |

### `cookimport bench quality-leaderboard`

Aggregates one quality-run experiment into a global cross-source leaderboard and Pareto frontier. Optional per-format leaderboard artifacts can be emitted to inspect winners inside each source extension bucket.

Options:

- `--experiment-id TEXT` (default `baseline`): experiment id under `<run-dir>/experiments`.
- `--run-dir PATH`: explicit quality run directory (defaults to latest under `--runs-root`).
- `--runs-root PATH` (default `data/golden/bench/quality/runs`): root used when `--run-dir` is omitted.
- `--out-dir PATH`: output directory for artifacts (defaults to `<run-dir>/leaderboards/<experiment-id>/<timestamp>`).
- `--allow-partial-coverage/--require-full-coverage` (default require full coverage): include partial-coverage configs when full coverage is available.
- `--by-source-extension/--no-by-source-extension` (default disabled): also write `leaderboard_by_source_extension.json/csv`.
- `--top-n INTEGER>=1` (default `10`): number of top configs printed to stdout.

### `cookimport bench quality-compare`

Compares selected baseline and candidate experiments from two quality runs and emits a timestamped comparison report. By default, quality-compare also writes an AI-agent bridge bundle at `<comparison_dir>/agent_compare_control/` with baseline/candidate Compare & Control insights and ready JSONL requests.

Options:

- `--baseline PATH` (required): baseline quality run directory (`summary.json` required).
- `--candidate PATH` (required): candidate quality run directory (`summary.json` required).
- `--out-dir PATH` (default `data/golden/bench/quality/comparisons`): output root for comparison reports.
- `--baseline-experiment-id TEXT`: optional baseline experiment selector (default resolver: `baseline` id, else exactly one successful experiment).
- `--candidate-experiment-id TEXT`: optional candidate experiment selector (default resolver: `candidate` id, else exactly one successful experiment).
- `--strict-f1-drop-max FLOAT>=0` (default `0.005`): max strict F1 drop before verdict FAIL.
- `--practical-f1-drop-max FLOAT>=0` (default `0.005`): max practical F1 drop before verdict FAIL.
- `--source-success-rate-drop-max FLOAT>=0` (default `0.0`): max source success-rate drop before verdict FAIL.
- `--fail-on-regression / --no-fail-on-regression` (default disabled): exit non-zero when verdict is `FAIL`.
- `--allow-settings-mismatch / --no-allow-settings-mismatch` (default disabled): allow quality verdicts when baseline/candidate `run_settings_hash` differ.
- `--qualitysuite-agent-bridge / --no-qualitysuite-agent-bridge` (default enabled): write `<comparison_dir>/agent_compare_control/` bundle.
- `--qualitysuite-agent-bridge-since-days INTEGER` (optional): bound compare-control history scan when building bridge artifacts.
- `--qualitysuite-agent-bridge-output-root PATH` (default `data/output`): compare-control output root used for bridge generation.
- `--qualitysuite-agent-bridge-golden-root PATH` (default `data/golden`): compare-control golden root used for bridge generation.

AI-agent handoff flow (default bridge on):

1. Read `<comparison_dir>/agent_compare_control/qualitysuite_compare_control_index.json`.
2. Compare `baseline__*.json` vs `candidate__*.json` insight files.
3. Run `<comparison_dir>/agent_compare_control/agent_requests.jsonl` through `cookimport compare-control agent` for deeper drill-down.

### `cookimport bench eval-stage`

Evaluates an existing stage run (no prediction generation) against a freeform gold export.

Options:

- `--gold-spans PATH` (required): exported `freeform_span_labels.jsonl` gold file.
- `--stage-run PATH` (required): stage run directory containing `.bench/*/stage_block_predictions.json`.
- `--workbook-slug TEXT`: workbook folder under `.bench` (required when multiple workbooks exist).
- `--extracted-archive PATH`: explicit extracted archive JSON path (otherwise auto-resolves unique `raw/**/full_text.json`).
- `--out-dir PATH`: output directory for eval artifacts (defaults to `data/golden/benchmark-vs-golden/<timestamp>`).
- `--label-projection TEXT` (default `core_structural_v1`): segmentation label projection for boundary diagnostics.
- `--boundary-tolerance-blocks INTEGER>=0` (default `0`): tolerance window used when matching gold/pred boundaries.
- `--segmentation-metrics TEXT` (default `boundary_f1`): comma-separated segmentation metrics (`boundary_f1`, optional `pk`, `windowdiff`, `boundary_similarity` when `segeval` is installed).

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
- `--codex-farm-cmd TEXT` (default `codex-farm`): codex-farm executable used when `--llm` is enabled.
- `--codex-farm-root PATH`: optional codex-farm pipeline-pack root.
- `--codex-farm-workspace-root PATH`: optional codex-farm workspace root.
- `--codex-farm-pipeline-pass5-tags TEXT` (default `recipe.tags.v1`): pass-5 tags pipeline id for LLM second pass.
- `--codex-farm-failure-mode TEXT` (default `fallback`): `fail|fallback` behavior when codex-farm setup/invocation fails.

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
- `--codex-farm-cmd TEXT` (default `codex-farm`): codex-farm executable used when `--llm` is enabled.
- `--codex-farm-root PATH`: optional codex-farm pipeline-pack root.
- `--codex-farm-workspace-root PATH`: optional codex-farm workspace root.
- `--codex-farm-pipeline-pass5-tags TEXT` (default `recipe.tags.v1`): pass-5 tags pipeline id for LLM second pass.
- `--codex-farm-failure-mode TEXT` (default `fallback`): `fail|fallback` behavior when codex-farm setup/invocation fails.
- `--import-batch-id TEXT`: batch filter for DB selection.
- `--source TEXT`: source filter for DB selection.
- `--limit INTEGER`: max recipes in batch mode (defaults to `100` internally when omitted).

## Environment Variables

CLI-relevant environment variables:

- `C3IMP_LIMIT`: used by interactive mode callback. If set to an integer, interactive import uses it as `stage --limit`.
- `COOKIMPORT_WORKER_UTILIZATION`: optional percentage or ratio for interactive per-run concurrency defaults in `C3imp` (defaults to `90`).
- `COOKIMPORT_IO_PACE_EVERY_WRITES` / `COOKIMPORT_IO_PACE_SLEEP_MS`: optional disk write pacing controls (default `16` and `8` in `C3imp`).
- `C3IMP_EPUB_EXTRACTOR`: EPUB extractor switch read at runtime by the EPUB importer (default-enabled: `unstructured`, `beautifulsoup`; `markdown`/`markitdown` require `COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS=1`).
- `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`: unstructured HTML parser version (`v1` or `v2`) for EPUB extraction.
- `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`: bool toggle for Unstructured `skip_headers_and_footers` on EPUB HTML.
- `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`: EPUB HTML preprocess mode before Unstructured (`none`, `br_split_v1`, `semantic_v1`).
- `C3IMP_EPUBCHECK_JAR`: optional EPUBCheck jar path used by `cookimport epub validate` when `--jar` is omitted.
- `C3IMP_STANDALONE_ANALYSIS_WORKERS`: worker count for EPUB/PDF standalone knowledge-block analysis (`>=1`, default `4`).
- `COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS`: unlocks `markdown`/`markitdown` EPUB extractors across stage/prediction/debug command paths when set truthy (`1|true|yes|on`).
- `COOKIMPORT_ALLOW_CODEX_FARM`: legacy no-op compatibility env var (recipe codex-farm options are no longer gated by this variable).
- `COOKIMPORT_ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS`: include optional markdown-based extractors in all-method permutations when set to `1`.
- `COOKIMPORT_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS`: optional auto-mode ceiling for `bench quality-run` experiment concurrency (default follows detected CPU count; ignored when `--max-parallel-experiments` is set).
- `COOKIMPORT_QUALITY_EXPERIMENT_EXECUTOR_MODE`: quality-run experiment fanout backend (`auto` default, `thread`, or `subprocess`). `auto` picks subprocess fanout when process-pool probing fails.
- `JOBLIB_MULTIPROCESSING`: when unset, startup now auto-sets `JOBLIB_MULTIPROCESSING=0` in SemLock-restricted runtimes to avoid noisy `joblib ... will operate in serial mode` warnings.
- `COOKIMPORT_DISABLE_JOBLIB_SEMLOCK_GUARD`: disable the automatic `JOBLIB_MULTIPROCESSING` guard (`1|true|yes|on`).
- `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER`: canonical-text matcher selection (`dmp` only; non-`dmp` values are invalid).
- `COOKIMPORT_BENCHMARK_EVAL_PROFILE_MIN_SECONDS`: optional profiler threshold for benchmark evaluation stage (`>=0`; enables profile artifact capture when eval runtime meets threshold).
- `COOKIMPORT_BENCHMARK_EVAL_PROFILE_TOP_N`: optional `pstats` top-N row count for benchmark evaluation profiling output (default `40`).
- `COOKIMPORT_CODEX_CMD`: default Codex CLI command used by prelabel flows when `--codex-cmd` is omitted.
- `COOKIMPORT_CODEX_MODEL`: default Codex model used by prelabel flows when `--codex-model` is omitted.
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
- For prelabel Codex settings: `--codex-cmd`/`--codex-model`/`--codex-thinking-effort` win for that run; env vars are defaults.
- For EPUB extractor/options: explicit stage/benchmark flags or interactive per-run Run Settings selection write `C3IMP_EPUB_EXTRACTOR` plus `C3IMP_EPUB_UNSTRUCTURED_*` vars for that run; markdown extractors still require `COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS=1`.
- For all-method markdown extractors: `COOKIMPORT_ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS=1` gates optional markdown variants.
- For all-method codex variants: `--include-codex-farm` controls inclusion; `bench speed-run` requires `--speedsuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`; `bench quality-run` requires `--qualitysuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`; `COOKIMPORT_ALLOW_CODEX_FARM` remains legacy no-op.
- For benchmark sequence matcher: `--sequence-matcher` (or interactive `benchmark_sequence_matcher`) wins for that run and temporarily sets `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER` around evaluation.
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
- Ensure interactive selector surface (`cookimport/cli_ui/run_settings_flow.py`) exposes it when relevant to top-tier profile resolution.
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
- Reminder: `labelstudio-eval` is eval-only and does not rerun pipeline options; pipeline flags on eval only affect run-manifest metadata parity.

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
- Interactive two-profile top-tier chooser: `cookimport/cli_ui/run_settings_flow.py`.
- Quality-suite winner snapshot persistence: `cookimport/config/last_run_store.py`.

Durable behavior:
- Interactive Import and interactive Benchmark flows always route through a top-tier profile choice before launching conversion.
- Every run-producing path persists structured `runConfig` plus `runConfigHash` and `runConfigSummary` into report/history surfaces.
- Eval-only benchmark mode intentionally bypasses run-settings selection because no extraction pipeline runs.

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

Historical note:
- The old full-screen toggle editor path was retired when interactive run selection simplified to the two automatic top-tier profiles.

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

Historical note:
- The viewport contract applied to the retired `toggle_editor` path and is kept only for context on earlier interactive UX iterations.

### Spinner ETA and worker telemetry contract

Merged sources:
- `docs/understandings/2026-02-22_23.13.34-spinner-xy-eta-flow.md`
- `docs/understandings/2026-02-23_00.17.44-spinner-worker-activity-telemetry.md`
- `docs/understandings/2026-03-03_12.20.00-spinner-eta-weighted-window-bootstrap.md`

Durable rules:
- Callback spinner ETA is derived from the active `X/Y` counter and should prioritize recent throughput via a weighted last-5-step average (`30/20/20/20/10`, newest first). For all-method dashboard snapshots, use top-line `overall ... | config X/Y`.
- `task/item/config/phase` loops should emit counters from runtime loop boundaries; CLI renderer should format and decorate them, not invent totals.
- Worker telemetry stays a side-channel payload parsed/rendered by shared spinner code so per-worker status lines do not overwrite the primary phase/task line.
- For multi-line dashboard snapshots, ETA/elapsed suffixes decorate the top summary line (`overall ...`) instead of the trailing `task:` line.
- Live spinner snapshots are rendered as a compact ASCII border panel so operators can see a stable, block-style status block while counts and worker lines refresh in place.
- The bordered spinner panel is generated once from the same shared snapshot state and used for benchmark/label-studio/import progress paths so the view stays consistent across workflows.
- When live panel width clamps a long status line, truncation keeps the trailing timing parenthetical (`eta`/`avg`/elapsed) visible via middle-ellipsis clipping.
- Codex-farm live status lines are summarized to human-readable pass labels (for example `pass2 schemaorg`) and emit a dedicated `stage:` line so current pass remains visible even with long worker IDs.

## Merged Task Specs (2026-02-22_23 to 2026-02-23_00)

### 2026-02-22_23.13.39 spinner `X/Y` ETA contract

Current CLI spinner contract for callback-driven phases:

- Parse the active `X/Y` counter in status text (all-method dashboard snapshots use top-line `overall ... | config X/Y`; other flows use right-most).
- Compute average seconds per completed unit from recent observed `X` increments using the weighted last-5 step window.
- If the first observed counter already starts above `1`, bootstrap ETA from run-elapsed/current until increment history is available; keep stale-phase elapsed-seconds ticker behavior unchanged.
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

## 2026-02-27 Merged Understandings: CLI Docs Drift and Prune Rules

Merged source notes:
- `docs/understandings/2026-02-27_19.45.20-cli-docs-stale-feature-prune.md`
- `docs/understandings/2026-02-27_19.51.12-cli-readme-command-surface-reconciliation.md`

Current-contract additions:
- Top-level command drift has been low; the higher-risk drift is option-level coverage inside existing commands.
- Keep benchmark docs synchronized with active `bench` options/subcommands (`speed-discover`, `speed-run`, `speed-compare`, `quality-discover`, `quality-run`, `quality-leaderboard`, `quality-compare`, `eval-stage`) and `labelstudio-benchmark` prediction/eval split options.
- Keep tagging CLI option docs synchronized for codex-farm pass5 paths (`tag-recipes suggest|apply --llm ...`).

Known stale surfaces that should stay retired:
- `cookimport epub race` command family.
- `labelstudio-benchmark --chunk-level` option.

Anti-loop rule:
- Validate CLI docs by command signatures and options (Typer registration), not by command-name list alone.

## 2026-02-28 migrated understandings digest

This section consolidates discoveries migrated from `docs/understandings` into this domain folder.

### 2026-02-27_20.38.15 load settings sequence matcher coercion
- Source: `docs/understandings/2026-02-27_20.38.15-load-settings-sequence-matcher-coercion.md`
- Summary: "Legacy cookimport.json matcher values are now rejected at load time; benchmark sequence matcher must be dmp."

### 2026-02-28_00.50.18 bench run/sweep removal surface map
- Source: `docs/understandings/2026-02-28_00.50.18-bench-run-sweep-removal-surface-map.md`
- Summary: Mapped remaining active `bench` command surface after removing deprecated `bench validate/run/sweep/knobs` commands and noted doc surfaces that needed sync.

### 2026-02-28_01.00.09 all-method 79 run count breakdown
- Source: `docs/understandings/2026-02-28_01.00.09-all-method-79-run-count-breakdown.md`
- Summary: Explained how the interactive all-method wizard derives the base configuration count (pre-sweep) from target variants (notably EPUB extractor variant expansion).

## 2026-02-28 migrated understandings digest (interactive run-settings chooser)

### 2026-02-28_02.25.24 interactive run-settings preferred option wiring
- Source: `docs/understandings/2026-02-28_02.25.24-interactive-run-settings-preferred-option-wiring.md`
- `choose_run_settings(...)` in `cookimport/cli_ui/run_settings_flow.py` is the single interactive top-tier chooser for import and benchmark flows.
- Interactive chooser surface is now exactly two families: `CodexFarm automatic top-tier` and `Vanilla automatic top-tier`.
- Quality-suite winner persistence remains in `.history/qualitysuite_winner_run_settings.json` for codex profile resolution.

## 2026-02-28 migrated understandings batch (03:37-03:57)

The items below were merged from `docs/understandings` in timestamp order and folded into CLI current-state guidance.

### 2026-02-28_03.37.41 interactive run-settings codex option gating
- Interactive codex behavior is controlled by the two-profile top-tier chooser.
- `CodexFarm automatic top-tier` always resolves to codex-enabled recipe/line-role/atomic settings without env gating.

### 2026-02-28_03.44.53 single-profile benchmark codex prompt expectations
- Single-profile benchmark flow does not show the all-method-only `Include Codex Farm permutations?` prompt.
- In this mode, codex behavior is controlled by the shared run-settings chooser and current `llm_recipe_pipeline` value.

### 2026-02-28_03.52.23 shared chooser is the common codex hook
- Both interactive import and interactive benchmark run through `choose_run_settings(...)`.
- Shared codex prompts belong there for consistent behavior across import and interactive benchmark single-profile modes.

### 2026-02-28_03.57.17 codex toggle must include model/reasoning follow-up
- Current chooser intentionally keeps this compact: one codex/vanilla profile selection without extra model/effort prompts.
- Model/effort overrides stay available through settings/CLI flags instead of interactive chooser follow-up.

## 2026-02-28 merged task specs (`docs/tasks` batch)

### 2026-02-28_02.08.45 all-method process-worker preflight
- Source task: `docs/tasks/2026-02-28_02.08.45-all-method-process-worker-preflight.md`
- All-method scheduling preflights process-worker availability before trying process-pool startup.
- When workers are unavailable, CLI now falls back to thread-based config concurrency (single-config execution remains a last-resort fallback).
- This keeps correctness unchanged while making restricted-runtime behavior clearer for operators.

### 2026-02-28_03.32.49 single-profile all-matched interactive benchmark
- Source task: `docs/tasks/2026-02-28_03.32.49-single-profile-all-matched-interactive-benchmark.md`
- Interactive benchmark mode picker includes single-profile all-matched mode.
- Mode runs one offline `labelstudio-benchmark` per matched target (no all-method expansion), preserving canonical-text scoring.
- Outputs write under `<benchmark_timestamp>/single-profile-benchmark/<index_source_slug>/...`.

### 2026-02-28_03.52.06 interactive codex-farm per-run prompt
- Source task: `docs/tasks/2026-02-28_03.52.06-interactive-codex-farm-per-run-prompt.md`
- `choose_run_settings(...)` is the shared codex hook for interactive import and benchmark flows.
- Prompt sequence for codex-enabled runs is:
  1. `Use Codex Farm recipe pipeline for this run?` (default `Yes`)
  2. optional model override
  3. optional reasoning effort override
- `None`/cancel from these prompts cancels run setup cleanly.

### 2026-02-28_03.59.43 benchmark split spinner harmonization
- Source task: `docs/tasks/2026-02-28_03.59.43-benchmark-split-spinner-harmonization.md`
- Split conversion now emits shared counter text from the first update (`Running split conversion... task 0/N`) and includes `(workers=N)` when parallel.
- Split worker payloads are sanitized to RunSettings-only keys so worker logs avoid repeated unknown-key warnings.

### 2026-02-28_04.14.07 codex-farm model picker in shared run-settings chooser
- Source task: `docs/tasks/2026-02-28_04.14.07-codex-farm-model-picker-in-run-settings.md`
- `choose_run_settings(...)` now uses a menu picker for codex model override instead of direct free-text prompt.
- Picker contract:
  - keep current value,
  - pipeline default (shown when an override exists),
  - discovered models from `codex-farm models list --json` (best-effort, with fallback options),
  - custom model id fallback.
- Reasoning-effort prompt behavior is unchanged and still follows model selection when codex is enabled.
- Cancel/back from model or reasoning prompts cancels run setup cleanly for both import and benchmark interactive flows.

## 2026-02-28 migrated understandings batch (04:09-04:15 Codex prompt surfaces)

### 2026-02-28_04.09.18 c3imp codex-farm interactive prompt paths
- Source: `docs/understandings/2026-02-28_04.09.18-c3imp-codex-farm-interactive-prompt-paths.md`
- Both interactive import and interactive benchmark flows call the same chooser entrypoint: `choose_run_settings(...)` in `cookimport/cli_ui/run_settings_flow.py`.
- Chooser prompt `Use Codex Farm recipe pipeline for this run?` defaults to `Yes`.
- Model and reasoning override prompts appear only when the resolved run settings keep `llm_recipe_pipeline=codex-farm-3pass-v1`.
- `single_offline_all_matched` has no separate Codex include prompt; it inherits chooser output.

### 2026-02-28_04.15.12 codex-farm run-settings model picker surface
- Source: `docs/understandings/2026-02-28_04.15.12-codex-farm-run-settings-model-picker-surface.md`
- Codex model override uses menu-first selection (`keep current`, optional `pipeline default`, discovered models, `custom model id...`) instead of free-text-first input.
- Typing is only used for the explicit `custom model id...` branch.
- `None`/`BACK_ACTION` from model or reasoning prompts cancels setup for both interactive import and benchmark paths.

Anti-loop note:
- If Codex enable prompts appear but model/reasoning prompts do not, confirm the resolved chooser payload still has `llm_recipe_pipeline=codex-farm-3pass-v1` before editing benchmark-mode menus.

## 2026-02-28 merged understandings (joblib SemLock startup warning guard)

### 2026-02-28_14.46.38 joblib SemLock warning is startup noise in restricted runtimes
- Source: `docs/understandings/2026-02-28_14.46.38-joblib-semlock-warning-is-startup-noise-not-new-regression.md`
- Repeated `joblib ... will operate in serial mode` output can be import-time SemLock probe noise rather than a newly introduced runtime regression.
- Startup guard behavior:
  - probe SemLock early,
  - set `JOBLIB_MULTIPROCESSING=0` before joblib import when host is restricted,
  - preserve explicit `JOBLIB_MULTIPROCESSING` env overrides as authoritative.
- Escape hatch: `COOKIMPORT_DISABLE_JOBLIB_SEMLOCK_GUARD` disables the guard for debugging.

## 2026-03-01 docs/tasks merge (CLI SemLock guard)

### 2026-02-28_14.46.37 joblib SemLock warning guard task merged
- Source task was merged into this section and then removed from `docs/tasks`:
  - `2026-02-28_14.46.37-joblib-semlock-warning-guard.md`
- Problem context retained:
  - Repeated startup warning spam (`joblib ... will operate in serial mode`) on SemLock-restricted hosts obscured real regression signals and polluted CLI output.
- Current contract retained:
  - Startup probes SemLock before downstream imports.
  - `JOBLIB_MULTIPROCESSING=0` is set only when host restriction is detected and the variable is otherwise unset.
  - Explicit operator values for `JOBLIB_MULTIPROCESSING` always win.
  - Guard can be disabled with `COOKIMPORT_DISABLE_JOBLIB_SEMLOCK_GUARD`.
- Validation evidence retained:
  - `. .venv/bin/activate && pytest tests/core/test_joblib_runtime.py -q`
  - `. .venv/bin/activate && python - <<'PY'` import smoke for `cookimport.cli`
- Anti-loop note:
  - Treat this warning as startup-environment noise first; only treat it as runtime regression evidence when executor-resolution telemetry also regresses.

## 2026-03-02 docs/tasks merge (interactive quality-first preset)

### 2026-03-02_00.24.23 quality-first winner stack chooser option
- Source task: `docs/tasks/2026-03-02_00.24.23-interactive-quality-first-run-settings-preset.md`
- Shared chooser (`choose_run_settings(...)`) now exposes a built-in `quality-first winner stack` option for both interactive import and benchmark flows.
- The preset applies a deterministic parser stack:
  - `epub_extractor=unstructured`
  - `epub_unstructured_html_parser_version=v1`
  - `epub_unstructured_preprocess_mode=semantic_v1`
  - `epub_unstructured_skip_headers_footers=true`
- This option is intentionally independent from saved profile files (`preferred`, `quality-suite winner`, `last run`) so it remains available on first run and in clean environments.

## 2026-03-02 merged understandings digest (interactive presets and progress core)

Merged sources (chronological):
- `docs/understandings/2026-03-02_00.25.21-interactive-run-settings-quality-first-preset-path.md`
- `docs/understandings/2026-03-02_01.02.17-codex-farm-progress-active-suffix-dedup.md`
- `docs/understandings/2026-03-02_01.06.21-cli-progress-systems-current-state.md`
- `docs/understandings/2026-03-02_01.12.49-c3imp-interactive-throttle-and-io-pacing.md`
- `docs/understandings/2026-03-02_08.59.03-common-core-progress-dashboard-plan-gap-audit.md`

Current-contract additions:
- `choose_run_settings(...)` in `cookimport/cli_ui/run_settings_flow.py` is the shared interactive run-settings entrypoint for Import and interactive Benchmark paths. Add/remove built-in profiles there to keep both flows synchronized.
- The quality-first preset should keep using the same chooser patch pattern (derive from global defaults, apply patch, then build `RunSettings`) so behavior stays consistent with other preset choices.
- `C3imp` interactive sessions default runtime pressure controls through env defaults:
  - `COOKIMPORT_WORKER_UTILIZATION=90`
  - `COOKIMPORT_IO_PACE_EVERY_WRITES=16`
  - `COOKIMPORT_IO_PACE_SLEEP_MS=8`
  These remain overrideable by explicit env values.
- Codex-farm callback progress dedupe keys on full emitted status text; volatile `active <file>` suffixes should stay out of steady-state progress strings so duplicate suppression works in plain-progress mode.
- CLI progress rendering for stage, single benchmark, and all-method flows now uses a shared snapshot contract via `ProgressDashboardCore`; live and plain rendering share the same dashboard model with mode-appropriate output transport.
- `_run_with_progress_status(...)` is not render-only: it also owns ETA/rate sampling, worker-sidechannel decoding, mode selection, and timeseries writes. Any progress-core extraction must preserve these behaviors.
- Stage progress parity is now exercised by `tests/cli/test_stage_progress_dashboard.py`, including merge-phase worker updates and shared snapshot shape behavior.

## 2026-03-02 merged understanding digest (common-core progress-dashboard stabilization)

Merged sources (chronological):
- `docs/understandings/2026-03-02_01.05.35-common-core-progress-dashboard-migration.md`
- `docs/understandings/2026-03-02_09.37.48-common-core-progress-dashboard-review-gaps.md`
- `docs/understandings/2026-03-02_09.48.15-common-core-progress-dashboard-review-current-state-gap.md`
- `docs/understandings/2026-03-02_09.52.00-common-core-progress-dashboard-review-fixes.md`
- `docs/understandings/2026-03-02_10.12.00-common-core-progress-dashboard-ogplan-parity-review.md`
- `docs/understandings/2026-03-02_19.00.00-stage-progress-live-plain-parity.md`
- `docs/understandings/2026-03-02_22.00.00-common-core-progress-dashboard-fix-completion.md`
- `docs/understandings/2026-03-02_23.00.00-common-core-progress-dashboard-stage-adapter-current-label.md`
- `docs/understandings/2026-03-02_23.15.00-stage-progress-dashboard-adapter-parity.md`

Current-contract additions:
- Stage and benchmark callback progress now shares one rendering data model (`ProgressDashboardCore`) with callback state updates routed through `ProgressCallbackAdapter`; `_run_with_progress_status(...)` continues to own ETA/rate behavior and worker-sidechannel parsing.
- Stage execution uses local `_StageProgressAdapter` ownership for worker rows/current-file lines, and both live and plain modes print the same snapshot content through the shared transport (`status.update(...)` for live).
- Stage snapshots now include a meaningful `current:` line based on `_resolve_stage_current_file`, with merge-phase worker and backend-resolution messaging captured for durable post-run metadata (`stage_worker_resolution.json`).
- `tests/cli/test_stage_progress_dashboard.py` and `tests/core/test_progress_dashboard.py` now guard live/plain parity for merge-phase updates, `snapshot_text()`, and stable callback rendering.
- A prior live-path blocker (`len(worker_dashboard_adapter.snapshot_workers()[0])`, indentation drift in `_run_with_progress_status`) and stale monkeypatch targets were identified, then corrected before this ledger was finalized; if those failings reappear, treat it as a regression of the current shared-contract path, not a missing test.

## 2026-03-02 docs/tasks merge (CLI progress dashboard core consolidation)

### 2026-03-02_01.05.35-common-core-progress-dashboard.md

Why this exists: one operator-visible progress contract for all long-running CLI flows (single benchmark/import spinner, all-method benchmarking, and stage worker runs) was missing, with three separate tracker implementations diverging over time.

What it is now:
- Shared `ProgressDashboardCore` lives in `cookimport/core/progress_dashboard.py` and owns the canonical progress snapshot fields (overall counters, current label, queue rows, task line, worker lines).
- CLI callback flow is wrapped by `ProgressCallbackAdapter` in `cookimport/cli.py` so `_run_with_progress_status(...)` keeps ETA/rate sampling, dedupe, live/plain transport switching, and timeseries behavior while rendering from the shared model.
- Stage flow now uses `_StageProgressAdapter` and passes worker/backend resolution messages through the same snapshot model, so live and plain modes stay visually consistent.
- New/updated test anchors: `tests/core/test_progress_dashboard.py`, `tests/cli/test_stage_progress_dashboard.py`, `tests/labelstudio/test_labelstudio_benchmark_helpers.py` for callback/dashboard parity.

Known tradeoffs/limitations to remember:
- Stage/all-method adapters are adapter-boundary sensitive; parser or timing regressions usually come from adapter payload shape changes before core rendering.
- Merge-phase worker messaging should be guarded because it is the first place to drift into stale or duplicated worker rows in plain mode.

Where to find the current behavior:
- Runtime wiring: `cookimport/cli.py`.
- Adapter contracts: `ProgressDashboardCore`, `ProgressCallbackAdapter`, `_StageProgressAdapter`.
- Current accepted command/path behavior documented in previous `2026-03-01` and `2026-03-02` merged entries in this file and `docs/02-cli/02-cli_log.md`.


## 2026-03-03 merged understandings digest

This batch consolidates CLI/interactive benchmark notes that were previously scattered in `docs/understandings/`.

Key CLI contracts to keep:
- Spinner rendering is intentionally a compact boxed panel for worker-heavy runs; plain progress is environment-aware and should stay low-noise.
- Interactive benchmark keeps the mode picker, but run-settings profile selection is now automatic top-tier resolution (no per-run settings picker).
- All-method benchmark was intentionally removed from the interactive top-level benchmark menu in this cycle.
- Keep codex-farm progress summaries human-readable (`active` worker labels + concise status updates) without flooding the terminal.
- `_run_with_progress_status(...)` indentation/control-flow is regression-sensitive; one bad indent can crash imports immediately.

Chronological merged source notes:
- 2026-03-02_00.00.00-progress-spinner-ascii-panel: Make benchmark/import status spinners render as a bordered ASCII panel.
- 2026-03-02_07.10.00-c3imp-spinner-default: Why C3imp showed plain progress and where spinner mode is overridden.
- 2026-03-02_13.24.00-interactive-run-settings-compact-menu: Interactive run-settings picker switched from full settings dumps to compact hash labels.
- 2026-03-02_15-40-00-plain-progress-no-spam: 2026-03-02_15.40.00: quiet plain progress output for benchmark runs
- 2026-03-02_19.48.22-benchmark-interactive-regression-fixes: Regression notes for interactive benchmark routing and codex-farm progress callback formatting.
- 2026-03-02_20.00.00-remove-all-method-benchmark-from-interactive-menu: Remove all-method benchmark from interactive menu
- 2026-03-02_21.22.44-cli-live-status-with-indent-regression: Fix a CLI import crash caused by mis-indented live-status `with console.status(...)` block.
- 2026-03-02_21.55.02-codex-farm-busy-panel-work-summary: 2026-03-02_21.55.02 spinner panel + busy worker summary
- 2026-03-03_00.00.00-codexfarm-progress-active-workers: Track why codex-farm benchmark progress now includes active worker task labels.

## 2026-03-03 docs/tasks merge digest (interactive menu wording + dashboard flow)

Merged source task files:
- `docs/tasks/2026-03-02_18.22.28 - clarify interactive menu labels.md`
- `docs/tasks/2026-03-02_23.01.36 - remove-dashboard-open-browser-prompt.md`

Current contract additions:
- Interactive select menus should keep the `NAME: short description` label pattern so options remain scannable and consistent across flows.
- Interactive dashboard generation should not ask open-browser confirmation; it always calls `stats_dashboard(..., open_browser=False)` and returns to main menu.
- Browser open behavior remains explicitly opt-in for non-interactive CLI usage via `cookimport stats-dashboard --open`.


## 2026-03-03 merged understandings digest (spinner runtime behavior)

- `2026-03-03_12.18.43` `benchmark-spinner-panel-width-clamp`: Benchmark/import live spinner panel width must clamp to terminal width to avoid long-task overflow.
- `2026-03-03_12.20.00` `spinner-eta-weighted-window-bootstrap`: Spinner ETA gaps came from first-seen counters lacking increment history; ETA now uses weighted last-5 steps with a bootstrap fallback.


## 2026-03-03 merged understandings digest (docs/understandings cleanup)

This section consolidates notes that were previously in `docs/understandings`.
Detailed chronology and preserved deep notes are in `02-cli_log.md`.

Merged source notes (chronological):
- `2026-03-03_13.12.17-spinner-panel-truncation-preserves-eta-suffix.md`: Live benchmark spinner line truncation should preserve ETA/avg suffix visibility.
- `2026-03-03_13.28.55-codex-spinner-stage-readable-pass-labels.md`: Codex-farm spinner status should surface a readable pass label and explicit stage row.
- `2026-03-03_17.34.31-spinner-active-tasks-left-counter-source.md`: Codex benchmark spinner can surface remaining tasks from the parsed task X/Y counter in the worker summary row.

## 2026-03-04 merged understandings digest (interactive top-tier defaults)

- `2026-03-04_00.44.22` `interactive-top-tier-default-run-settings-source-of-truth`: single-profile resolver milestone that removed the old global/preferred/last/edit chooser.
- `2026-03-04_01.20.00` `interactive-two-top-tier-profiles-codex-vs-vanilla`: interactive import/benchmark now expose exactly two automatic top-tier profile families (`CodexFarm`, `Vanilla`) with deterministic harmonization per profile.

## 2026-03-04 merged understandings digest (stale benchmark settings + winner harmonization)

Merged source notes (timestamp order):
- `2026-03-04_00.33.51-single-profile-codex-line-role-setting-source.md`
- `2026-03-04_00.44.22-interactive-top-tier-default-run-settings-source-of-truth.md`
- `2026-03-04_00.49.14-interactive-winner-harmonization-for-codex-line-role.md`

Current CLI contracts reinforced by this batch:
- Interactive run-settings resolution is deterministic and top-tier-first; avoid reintroducing broad profile pickers that can silently reuse stale low-quality profiles.
- Codex-vs-vanilla intent is captured by the top-level `Use Codex Farm recipe pipeline for this run?` prompt (with env override support), and codex-enabled runs immediately collect model/effort overrides in the same chooser flow.
- `llm_recipe_pipeline` must not be treated as an implicit proxy for `line_role_pipeline` / `atomic_block_splitter`; harmonization must explicitly set all three knobs together.
- Saved quality-suite winner settings can remain stale in history files, so post-resolution harmonization is required even when winner settings are loaded.

Anti-loop reminders:
- If a benchmark/import run shows codex ON with line-role or atomic OFF, debug `choose_run_settings(...)` harmonization first.
- If quality appears regressed in single-profile mode, verify resolved settings/hash before changing parsing/scoring logic.

## 2026-03-04 merged understandings digest (two automatic top-tier profiles)

Merged source note:
- `2026-03-04_01.20.00-interactive-two-top-tier-profiles-codex-vs-vanilla.md`

Current CLI contract reinforced:
- Interactive run-settings selection stays compact and deterministic while preserving codex-vs-vanilla intent through a single codex on/off prompt that maps to two automatic profile families:
  - CodexFarm automatic top-tier.
  - Vanilla automatic top-tier.
- This keeps the old wide profile picker removed while restoring an explicit apples-to-apples baseline path.

Anti-loop reminder:
- Avoid adding back broad manual profile menus to solve codex-vs-vanilla choice; keep that choice in the two-profile automatic selector.

## 2026-03-04 docs/tasks merge digest (interactive top-tier resolver)

Merged source task file:
- `docs/tasks/2026-03-04_00.44.22-top-tier-default-run-settings.md`

Current CLI contract reinforced:
- Interactive import/benchmark flows should not show a run-settings profile picker for routine execution.
- `choose_run_settings(...)` acts as a deterministic resolver:
  - prefer saved quality-suite winner settings when present,
  - otherwise use built-in top-tier baseline.
- Deterministic baseline keeps codex recipe + codex line-role + atomic splitter enabled.

Anti-loop reminder:
- If stale low-quality setting combos reappear, verify chooser removal and resolver path usage before changing benchmark/scoring logic.
