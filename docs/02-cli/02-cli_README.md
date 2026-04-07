---
summary: "Detailed CLI and interactive-mode reference, including all commands, options, and environment variables."
read_when:
  - When changing command wiring, defaults, or interactive menu flows
  - When adding a new CLI command or command group
---

# CLI Section Reference

Public CLI entrypoint wiring still lives in `cookimport/cli.py`, and that file is now a plain Typer composition root. Shared helper state lives in the private package `cookimport/cli_support/`, and active command-family ownership lives in `cookimport/cli_commands/`.
`cookimport.cli` still re-exports the shared helper/direct-call surface once at import time, but it no longer wraps callbacks or syncs patched globals back into owner modules at runtime. Prefer patching `cookimport.cli_commands.<family>` or the specific helper owner under `cookimport.cli_support` when you are changing one domain deliberately.
Use this doc as the CLI reference and open `cookimport/cli_commands/<family>.py` before treating `cookimport/cli.py` as the implementation owner.
For beginner interactive usage, start with `README.md` in the project root.

Current package note:
- the first real private support homes are `cookimport/cli_support/interactive.py`, `cookimport/cli_support/settings.py`, `cookimport/cli_support/dashboard.py`, and `cookimport/cli_support/compare_control.py`
- `cookimport/cli_support/bench.py` now owns the benchmark-heavy private surface: single-book helpers, all-method planning/runtime/reporting, and Oracle/upload bundle support
- `cookimport/cli_support/progress.py` now owns shared live-status rendering, telemetry, and benchmark progress override helpers
- `cookimport/cli_support/settings_flow.py` now owns the interactive settings screen, and `cookimport/cli_support/interactive_flow.py` owns the main guided menu loop
- `cookimport/cli_support/stage.py` now owns the shared stage manifest/merge/report helpers that were previously buried at the end of the root support file
- `cookimport/cli_commands/stage.py`, `cookimport/cli_commands/bench.py`, and `cookimport/cli_commands/labelstudio.py` now use explicit `cli_support` imports instead of `from cookimport.cli_support import *`
- `cookimport/cli_support/__init__.py` is now the small internal export hub for shared CLI helpers, not the Typer composition root and not a runtime compatibility relay
- benchmark split modules should explicitly import cross-owner helpers they call (for example stage-owned importer checks) instead of assuming late-added `cli_support.__init__` exports are present in the bench facade snapshot

## Entry Points

`pyproject.toml` defines five CLI scripts:

- `cookimport` -> `cookimport.cli:app`
- `cf-debug` -> `cookimport.cf_debug_cli:app`
- `C3imp` -> `cookimport.c3imp_entrypoint:main`

Remember to do source .venv/bin/activate

Behavior differences:

- `cookimport` with no subcommand enters interactive mode.
- `cf-debug` is a non-interactive follow-up/debugging CLI for existing benchmark `upload_bundle_v1/` directories. Its high-level iterative workflow is:
  - `request-template`: create a manifest you can fill with the web AI's asks.
  - `build-followup`: answer that manifest into a new `followup_dataN/` folder that assumes the requester already has `upload_bundle_v1`.
  - lower-level commands (`select-cases`, `export-cases`, `audit-line-role`, `audit-prompt-links`, `audit-knowledge`, `export-page-context`, `export-uncertainty`, `pack`, `ablate`) remain available when you want manual control.
  - `preview-prompts`: rebuild zero-token recipe/knowledge/line-role prompt previews from an existing deterministic/`vanilla` processed run or benchmark root so you can estimate likely cost before spending tokens.
    Preview outputs are scratch analysis artifacts; `cf-debug` now refuses `--out` paths under `data/golden/benchmark-vs-golden/` so prompt previews do not masquerade as real benchmark runs.
  - `actual-costs`: resolve the finished-run postmortem cost artifact (`prompt_budget_summary.json`) from a completed run or benchmark root.
  - `preview-shard-sweep`: run several local worker/shard preview variants from one existing run root and compare them side by side. A tiny starter experiment file lives at `docs/examples/shard_sweep_examples.json`.
    Like `preview-prompts`, it must write outside `data/golden/benchmark-vs-golden/`.
  - knowledge follow-up uses a dedicated run-level path rather than the line-role prompt audit: `select-cases` now accepts `--include-knowledge-source-key` or `--include-knowledge-output-subdir`, and `audit-knowledge` / `pack` / `build-followup` can emit `knowledge_audit.jsonl` plus knowledge artifact references.
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
  +--> [H] Benchmark vs freeform gold -----> mode picker ------------------> (single book OR selected/all matched books) -> [C]
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

### Shared Progress Contract

Current spinner/status rule:
- shared CLI status rendering accepts either plain text or the serialized `stage_progress` payload from `cookimport/core/progress_messages.py`
- plain `task X/Y` updates are still valid and now infer `stage:` / `progress:` lines in the shared spinner even before a stage emits richer worker metadata
- generic messages shaped like `task X/Y | running N` now expand into `active workers: N` rows just like the older codex-farm-specific worker surface
- richer `stage_progress` payloads can now carry `work_unit_label`, typed worker-session counts (`worker_running`, `worker_completed`, `worker_failed`), typed repo-follow-up counts (`followup_*` + `followup_label`), compact `artifact_counts`, and `last_activity_at`
- recipe, knowledge, and canonical line-role taskfile stages now also use those same structured fields to surface repo-owned worker-health attention from `live_status.json`; active rows can pick up a short live activity snippet from visible Codex events plus compact suffixes such as `quiet 58s` or `final message, no output`, and `detail_lines` can add `attention:` / `stalled workers:` summaries before a shard finishes
- when those richer fields are present, the shared spinner should render worker-session state separately from repo-owned follow-up/finalization state instead of forcing stages to fake that truth through `active_tasks` labels
- when `last_activity_at` is present, the shared spinner now renders a visible `last activity: ... ago` row instead of silently retaining that timestamp off-screen
- worker panels no longer cap configured rows at eight when structured stage progress provides a larger `worker_total` or active-task list; a ten-worker knowledge stage should render ten worker lines instead of `10/8`
- structured worker panels should also stop at the reported slot count; a five-worker phase should not pad fake `worker 06` to `worker 08` idle rows
- stage-specific emitters for recipe shard work, line-role, non-recipe finalize, label-first authority building, and staged-output writing should prefer structured payloads so benchmark/import status panels keep the active-stage context visible
- recipe shard work should report outer worker-bucket truth from `phase_worker_runtime.py` (configured workers, queued shards, active worker buckets, current first shard), not pretend the CLI can see true inner per-shard Codex progress once one worker hands a whole bucket to a single classic `process` call
- `processing_timeseries*.jsonl` is the durable machine-readable history of those progress snapshots and should retain stage label, work-unit label, active tasks, typed worker/follow-up counts, artifact counts, and detail lines when present
- progress/timeseries writers must coerce nested `Path` values to strings before JSON serialization so benchmark and stage telemetry does not silently drop rows when payloads include filesystem paths
- ETA/rate sampling is stage-local, so a new structured `stage_label` must reset avg-per-task history instead of inheriting timings from the previous stage even when the next stage reuses the same `task X/Y` shape
- bootstrap ETA for structured parallel stages should use active/configured worker count to estimate remaining worker-waves, instead of treating all remaining tasks as fully serial work

### [C] Main Menu

Menu options:

- `Stage: Convert files from data/input into cookbook outputs`
- `Label Studio upload: Create labeling tasks (uploads)`
- `Label Studio export: Export completed labels into golden artifacts`
- `Evaluate vs freeform gold: Generate predictions and compare to your labels`
- `Dashboard: Build lifetime stats dashboard HTML`
- `Settings: Change saved interactive defaults`
- `Exit: Close the tool`

Availability rule:

- `Import` and `Label Studio task upload` only appear when at least one supported top-level file exists in `data/input`.
- `inspect` remains available as a direct command (`cookimport inspect <path>`), not as an interactive menu action.

Menu numbering and shortcuts:

- `_menu_select` now shows Questionary shortcut labels on all select-style menus (for example `1)`, `2)`, ...).
- Numeric shortcuts (`1-9`, `0`) select immediately in interactive menus; non-numeric shortcuts still move focus and can be confirmed with Enter.

### [J] Settings

`Settings` edits global defaults in `cookimport.json`.

Persistent `Settings` now covers the saved operator defaults used by interactive stage/benchmark flows:
- workers and all-method scheduler/sharding defaults
- EPUB extraction defaults plus `pdf_ocr_policy`
- webschema extractor/policy/min-threshold defaults
- saved recipe/knowledge defaults
- saved Codex command/path/model/reasoning/context defaults
- output root, split sizing, warm-models, and Label Studio credentials

Important split:
- the top-tier per-run chooser (`choose_run_settings(...)`) is still the refactor-aware place where each import/benchmark run picks Codex Exec vs vanilla and applies any flow-specific per-run Codex surface overrides
- the persistent `Settings` screen now provides the saved defaults that feed those interactive flows, but it still does not expose benchmark-lab/internal-only tuning seams such as parser internals, scoring internals, or hidden transition-only pipeline-id fields

Interactive `Import` and benchmark runs (`single_book` + matched-books) ask:
- `Workflow for this run?`
  - underlying values are `off` and `codex-recipe-shard-v1`, but the menu still renders only the workflow families `Vanilla / no Codex` and `Codex Exec`,
  - default is inferred from global `llm_recipe_pipeline`,
  - `COOKIMPORT_TOP_TIER_PROFILE=codex-exec|vanilla` can still force vanilla vs codex family and bypass the menu.
- if interactive setup chooses Codex Exec, it then asks:
  - one shared Codex step planner implemented as a single list with one row per available stage
  - each row owns both transport mode and shard count on the same screen
  - mode columns are `Off`, `JSON`, and `Taskfile`; recipe exposes only `Off` and `Taskfile`
  - up/down moves between rows while keeping the planner on one screen
  - left/right arrows and `Enter` cycle the current row's mode in place, and `+`, `-`, or direct digits edit shard count
  - `Continue` accepts the current per-row settings
- for interactive `Import`, that planner asks about:
  - recipe correction (`codex-recipe-shard-v1`)
  - non-recipe finalize (`codex-knowledge-candidate-v2`)
- for interactive benchmark modes (`single_book`, `selected_matched_books`, `all_matched_books`), that planner asks about:
  - block labelling (`codex-line-role-route-v2`)
  - recipe correction (`codex-recipe-shard-v1`)
  - non-recipe finalize (`codex-knowledge-candidate-v2`)
  - recipe `Taskfile`, line-role `JSON`, and knowledge `JSON` are the default per-step modes
  - recipe `Off` maps to `llm_recipe_pipeline=off`
  - block labelling `Off` maps to `line_role_pipeline=off` and `atomic_block_splitter=off`
  - block labelling `JSON` / `Taskfile` keep `line_role_pipeline=codex-line-role-route-v2` and persist the transport choice through `line_role_codex_exec_style`
  - non-recipe finalize `Off` maps to `llm_knowledge_pipeline=off`
  - non-recipe finalize `JSON` / `Taskfile` keep `llm_knowledge_pipeline=codex-knowledge-candidate-v2` and persist the transport choice through `knowledge_codex_exec_style`
  - import shows the selected source file above the planner; single-book benchmark now resolves the concrete gold/source pair first and shows that target above the planner before run settings continue
  - single-book benchmark now resolves a shared deterministic prep bundle for that selected source before opening the planner, so the row notes can show minimum-safe shard suggestions for line-role, recipe, and knowledge without throwing that prep work away
  - benchmark and all-method Codex rows stay in runtime stage order: block-labelling, then recipe correction, then non-recipe finalize
  - the header now gives a short deterministic prep summary (`blocks`, `lines`, `recipe guesses`, leftover `knowledge packets`) plus a one-line legend for the row note format
  - when target-specific planning data is available, the shard-count column remains the operator's launch request, `min` stays the advisory survivability recommendation, row notes stay compact, and any longer planner warnings render in a dedicated block below the table
  - row notes still use short plain-English labels for the main limiting factor (`prompt`, `output`, `session`, or `work`) plus average prompt size, average session size, and average owned work units per shard
  - live planning still fails closed later if the requested shard count is unsafe
  - the interactive chooser still caps each per-step prompt/shard count at `256`
  - the stage and benchmark adapter/CLI seams preserve those values into the live run config, so interactive shard choices survive through execution instead of silently falling back to saved defaults
  - `recipe_prompt_target_count`, `line_role_prompt_target_count`, and `knowledge_prompt_target_count` now all mean requested shard count on the live runtime path; worker count remains a separate concurrency override
  - for recipe correction specifically, recipe count may be larger than shard count because several contiguous recipe tasks can share one planned shard
- interactive all-method benchmark callers reuse that same Codex planner too, so any interactive benchmark flow that exposes Codex Exec now makes the operator pick concrete Codex processes instead of falling back to a separate generic `Include Codex Exec permutations?` prompt
- the owning seam for that shared per-surface chooser is `choose_interactive_codex_surfaces(...)` in `cookimport/cli_ui/run_settings_flow.py`; if a Codex surface toggle or per-step transport choice should exist in import, benchmark, and all-method flows, add it there instead of inventing a benchmark-only menu variant
- this difference is intentional:
  - import reuses the submenu with recipe + knowledge only because stage call adapters do not carry `line_role_pipeline` or `atomic_block_splitter`
  - benchmark modes expose block labelling because benchmark call builders do carry those fields
- when any codex-backed surface is selected, chooser then asks:
  - `Codex Exec model override` (menu-only: `Pipeline default`, optional `Keep current override`, discovered models only; no repo-invented fallback model id)
  - `Codex Exec reasoning effort override` (`Pipeline default` plus the selected discovered model's supported efforts when metadata is available)

Resolved profile families:
- `Codex Exec automatic top-tier`:
  - use saved `quality-suite winner` settings when available (`.history/qualitysuite_winner_run_settings.json` for default repo-local output),
  - interactive loading reuses only real `RunSettings` model fields during harmonization, so persistence metadata such as `bucket1_fixed_behavior_version` should not replay warning dumps in the chooser,
  - stale winner caches are treated as disposable and ignored with one concise warning rather than being migrated forever,
  - otherwise use built-in codex top-tier baseline,
  - harmonize saved or built-in settings to the current codex top-tier contract, then apply the interactively selected recipe pipeline (`codex-recipe-shard-v1`):
    `llm_knowledge_pipeline=codex-knowledge-candidate-v2`,
    `line_role_pipeline=codex-line-role-route-v2`,
    `atomic_block_splitter=off`,
    `epub_extractor=unstructured`,
    `epub_unstructured_html_parser_version=v1`,
    `epub_unstructured_preprocess_mode=br_split_v1`,
    `epub_unstructured_skip_headers_footers=true`,
    `multi_recipe_splitter=rules_v1`,
    `pdf_ocr_policy=off`,
    plus fixed Bucket 1 parser behavior recorded as
    `bucket1_fixed_behavior_version=bucket1-fixed-v1`
    (shared section detection, always-on heuristic fallback segmentation,
    compact codex stage ids, pattern hints off, current skip-on-success policy on).
- `Vanilla automatic top-tier`:
  - built-in fully vanilla baseline with Codex disabled (`llm_recipe_pipeline=off`, `llm_knowledge_pipeline=off`, `line_role_pipeline=off`, `atomic_block_splitter=off`),
  - current top-tier parsing baseline pinned to `unstructured + v1 + br_split_v1 + skip_headers=true`,
  - deterministic parsing knobs pinned to `shared_v1 + rules_v1 + always + heuristic_v1 + pdf_ocr_policy=off`,
  - compact codex pass ids remain pinned even when recipe codex is off.

Config keys and defaults:

The post-Bucket-2 product contract now has two public layers:
- ordinary operator settings: the day-to-day knobs surfaced most directly by `stage`/interactive flows (`workers`, split sizing, `epub_extractor`, `pdf_ocr_policy`, and Codex enablement/path/context knobs),
- benchmark-lab settings: still-public persistence fields used for EPUB parser tuning, some web fallback tuning, and benchmark-only line-role/Codex override work, but no longer treated as the normal stage help story.

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
- `epub_extractor` (default `unstructured`)
- benchmark-lab: `epub_unstructured_html_parser_version` (default `v1`)
- benchmark-lab: `epub_unstructured_skip_headers_footers` (default `true`)
- benchmark-lab: `epub_unstructured_preprocess_mode` (default `br_split_v1`)
- `web_schema_extractor` (default `builtin_jsonld`)
- benchmark-lab: `web_schema_normalizer` (default `simple`)
- benchmark-lab: `web_html_text_extractor` (default `bs4`)
- `web_schema_policy` (default `prefer_schema`)
- benchmark-lab: `web_schema_min_confidence` (default `0.75`)
- benchmark-lab: `web_schema_min_ingredients` (default `2`)
- benchmark-lab: `web_schema_min_instruction_steps` (default `1`)
- `pdf_ocr_policy` (default `auto`)
- `output_dir` (default `data/output`)
- `label_studio_url` (default unset; populated after first interactive Label Studio prompt)
- `label_studio_api_key` (default unset; populated after first interactive Label Studio prompt)
- `pdf_pages_per_job` (default `50`)
- `epub_spine_items_per_job` (default `10`)
- `warm_models` (default `false`)
- `llm_recipe_pipeline` (default `off`)
- `llm_knowledge_pipeline` (default `off`)
- `labelstudio-import --prelabel` is also a Codex-backed path and now requires `--allow-codex` even if `llm_recipe_pipeline=off`
- `codex_farm_cmd` (default `codex-farm`)
- `codex_farm_root` (default unset; falls back to `<repo_root>/llm_pipelines`)
- `codex_farm_workspace_root` (default unset; pipeline `codex_cd_mode` decides Codex `--cd`)
- `codex_farm_context_blocks` (default `30`)
- `codex_farm_knowledge_context_blocks` (default `0`)

Internal-only settings still load from saved payloads, winner profiles, QualitySuite `run_settings_patch` payloads, and speed-suite settings files, but they are no longer part of the ordinary operator surface. That internal-only set includes the Bucket 2 parser/OCR/scoring knobs (`multi_recipe_*`, `ingredient_*`, `p6_*`, `recipe_score*`, `ocr_device`, `ocr_batch_size`, `pdf_column_gap_ratio`, `codex_farm_failure_mode`) plus transition-only keys like `benchmark_sequence_matcher`, `multi_recipe_trace`, `p6_emit_metadata_debug`, and hidden current-pack ids such as `codex_farm_pipeline_knowledge`.

Normal stage summaries now render the smaller operator contract first. Raw/full payloads still persist in manifests, reports, saved settings, and benchmark artifacts for reproducibility.

What each setting affects:

- `workers`, split workers, page/spine split size: `stage` and benchmark import parallelism/sharding.
- `all_method_max_parallel_sources`: all-matched source-level concurrency cap (how many books run at once).
- `all_method_source_scheduling`: source job order strategy (`discovery` source order or `tail_pair` heavy/light interleave).
- `all_method_source_shard_threshold_seconds`, `all_method_source_shard_max_parts`, `all_method_source_shard_min_variants`: heavy-source sharding controls for all-matched runs (split one source’s variant set into multiple schedulable jobs).
- `all_method_scheduler_scope`: all-method all-matched scheduler implementation (`global` is the only supported scheduler and uses one run-wide config queue + run-wide eval-signature dedupe).
- `all_method_max_inflight_pipelines`, `all_method_max_split_phase_slots`, `all_method_max_eval_tail_pipelines`, `all_method_wing_backlog_target`, `all_method_smart_scheduler`: all-method config scheduler controls for the run-wide global scheduler (inflight cap, split-heavy slots, evaluate-tail cap, prewarm runway, smart/fixed admission mode).
- `all_method_config_timeout_seconds`, `all_method_retry_failed_configs`: all-method safety controls (per-config timeout and failed-config retry passes).
- all-method canonical alignment cache root is resolved per run and shared across timestamps (default under `data/golden/benchmark-vs-golden/.cache/canonical_alignment`; override via `COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT`).
- `epub_extractor`: runtime extractor choice via `C3IMP_EPUB_EXTRACTOR` (default-enabled choices: `unstructured`, `beautifulsoup`; `markdown`/`markitdown` are policy-locked off unless `COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS=1`).
- `epub_unstructured_html_parser_version`: parser version (`v1` or `v2`) passed into Unstructured HTML partitioning.
- `epub_unstructured_skip_headers_footers`: enables Unstructured `skip_headers_and_footers` for EPUB HTML partitioning.
- `epub_unstructured_preprocess_mode`: HTML pre-normalization mode before Unstructured (`none` or `br_split_v1`).
- Tables are always extracted during stage and benchmark prediction generation.
- Bucket 1 fixed behavior is recorded as `bucket1_fixed_behavior_version` in new run configs. Old payloads may still carry older hidden keys such as `section_detector_backend`, `multi_recipe_trace`, or instruction-step fallback settings, but new runs do not expose them as operator choices.
- `web_schema_extractor`, `web_schema_normalizer`, `web_html_text_extractor`, `web_schema_policy`, `web_schema_min_*`: deterministic local HTML/JSON schema ingestion controls for `webschema` importer (schema backend, normalization mode, fallback text extractor, schema-vs-fallback policy, and confidence/min-line thresholds).
- `p6_emit_metadata_debug`: internal-only debug toggle for optional Priority 6 sidecar artifacts.
- Internal-only parser/OCR/scoring payload keys remain accepted for engineering experiments and benchmark reproducibility: `multi_recipe_*`, `ingredient_*`, `p6_*`, `recipe_score*`, `ocr_device`, `ocr_batch_size`, `pdf_column_gap_ratio`, and `codex_farm_failure_mode`.
- `pdf_ocr_policy`: public OCR policy for PDFs.
- `output_dir`: interactive `stage` target output root.
- `label_studio_url`, `label_studio_api_key`: interactive Label Studio import/export credential defaults.
- `warm_models`: preloads SpaCy, ingredient parser, and OCR model before staging.
- `llm_recipe_pipeline`: recipe codex-farm parsing correction flow (`off` or `codex-recipe-shard-v1`).
- `llm_knowledge_pipeline`: optional knowledge-harvest flow (`off` or `codex-knowledge-candidate-v2`) used by `stage` only.
- recipe correction also emits raw selected tags, which are normalized into `recipe.tags` and JSON-LD `keywords` during stage/import runs.
- `codex_farm_*`: codex-farm command/root/workspace/context behavior used by `stage`; pipeline-id/failure internals remain loadable from explicit settings payloads but are hidden from ordinary help/UI.

Developer note:
- Per-run setting definitions live in `cookimport/config/run_settings.py`. Interactive top-tier chooser logic lives in `cookimport/cli_ui/run_settings_flow.py`; keep import and benchmark aligned there.
- `stage(...)` is called both by Typer CLI dispatch and direct Python callers (interactive helpers/tests); it must coerce any Typer `OptionInfo` default objects back to plain values before normalization/building run settings.
- `stats_dashboard(...)` is also called directly from interactive helpers; it must coerce Typer `OptionInfo` defaults (`--serve/--host/--port` and related flags) before branching into serve mode.
- Interactive import should pass the full selected run-settings surface into `stage(...)` (including knowledge toggles, pipeline IDs, and related context settings), not a partial subset.

### [D] Import Flow

`Import` steps:

1. Prompt for `Import All` or one selected file from top-level `data/input`.
2. Select one automatic top-tier profile family (`Codex Exec` or `Vanilla`) and resolve its deterministic run-settings profile (no full profile chooser and no codex yes/no prompt in this flow).
3. Applies selected EPUB env vars:
   - `C3IMP_EPUB_EXTRACTOR`
   - `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`
   - `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`
   - `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`
4. Calls `stage(...)` using the full selected run settings payload (workers/OCR/extractor + section/ingredient parser controls + LLM/codex-farm knobs).
   - When Codex Exec recipe/knowledge/tag passes run, stage now also writes prompt-debug artifacts under `<run_folder>/codex-exec/`:
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
   - interactive mode uses the resolved Codex Exec command (`COOKIMPORT_CODEX_CMD`, `COOKIMPORT_CODEX_FARM_CMD`, or `codex-farm`), shows the resolved account when available, then prompts for model (`use default`, discovered models, or custom model id) and thinking effort (model-compatible subset of `none|low|medium|high|xhigh`; `minimal` is intentionally hidden for this workflow).
   - freeform prelabel task calls run in parallel by default (`15` workers).
5. Enter Label Studio URL and API key if needed.
   - If `LABEL_STUDIO_URL` and `LABEL_STUDIO_API_KEY` are set, prompts are skipped.
   - Otherwise, interactive mode uses saved `cookimport.json` values when present.
   - If still missing, you are prompted once and the entered values are saved to `cookimport.json` for future interactive runs.
6. The tool builds tasks on your machine.
   - It prepares freeform segment tasks (`freeform-spans`) from extracted source blocks.
   - Before per-task AI labeling starts, it runs a single Codex model-access preflight call and fails fast when the selected model/account combination is invalid.
   - A status spinner shows live phase updates with `task X/Y` progress for known-size loops (including freeform prelabeling when AI prelabel is enabled), adds ETA once enough `X/Y` progress is observed, and shows per-worker activity lines under the main status when worker telemetry is available.
   - Plain counter updates now also render inferred `stage:` and `progress:` summary lines, so long-running stages stay informative even before they have custom worker metadata.
   - It also writes status telemetry under `<output_dir>/.history/processing_timeseries/<timestamp>__labelstudio_import__<source>.jsonl`.
   - It writes run files under `data/golden/sent-to-labelstudio`:
   - `label_studio_tasks.jsonl`
   - `coverage.json`
   - `extracted_archive.json`
   - `extracted_text.txt`
   - `manifest.json`
   - If Codex Exec recipe pass is enabled, this flow also writes prompt-debug artifacts under the run folder:
   - `prompts/prompt_request_response_log.txt`
   - `prompts/full_prompt_log.jsonl`
   - `prompts/prompt_type_samples_from_full_prompt_log.md`
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
   - Export supports freeform projects only.
5. Calls `run_labelstudio_export(...)` with `output_dir=data/golden/pulled-from-labelstudio`.
   - By default, export writes to: `data/golden/pulled-from-labelstudio/<source_slug_or_project_slug>/exports/`.
   - When one source file is detectable, export uses the source filename stem slug so repeat pulls overwrite the same folder even if project names gain suffixes like `-2`.
   - If `--run-dir` is supplied in non-interactive mode, export writes to that run directory.
6. Prints export summary path and returns to the main menu.

### [H] Benchmark vs Freeform Gold Flow

Interactive benchmark now has a mode submenu before execution:

1. Shows benchmark mode picker:
   - `Single Book: One local prediction + eval vs freeform gold` (default first choice)
   - `Salt Fat Acid Heat preset: Fast Codex Exec single-book benchmark`
   - `Selected Matched Books: Pick which matched books to run`
   - `All Matched Books: Repeat one config for every matched golden set`
   - the Salt Fat Acid Heat preset skips the normal run-settings and gold-export pickers when a freeform export labeled `saltfatacidheatcutdown` is available, and instead runs single-book with block labelling + recipe correction + non-recipe finalize enabled, shard counts `5/5/5`, `codex_farm_model=gpt-5.3-codex-spark`, and `codex_farm_reasoning_effort=low`
2. Single book path:
   - resolves one selected automatic top-tier run profile family (same resolver used by interactive import),
   - benchmark setup can now independently choose recipe Codex, block-labelling Codex, and knowledge extraction before execution,
   - when prompting for a discovered freeform gold export, the menu label is shortened to just the book slug instead of the full pulled-from-labelstudio path,
   - when the selected gold export already identifies a source file, interactive benchmark auto-uses that inferred source instead of asking for a `Use inferred source file?` confirmation,
   - uses the resolved `llm_recipe_pipeline` to decide variant planning,
   - when run settings resolve to any non-`off` `llm_recipe_pipeline`, runs paired variants under one timestamp session:
     - `single-book-benchmark/<source_slug>/vanilla` first (`llm_recipe_pipeline=off`),
     - `single-book-benchmark/<source_slug>/codex-exec` second (preserving the selected recipe pipeline, for example `codex-recipe-shard-v1`),
     - both paired variants now share the same operator-selected `atomic_block_splitter` value instead of forcing `off` for `vanilla` and `atomic-v1` for `codex-exec`,
   - when run settings resolve to `llm_recipe_pipeline=off`, runs one variant under `single-book-benchmark/<source_slug>/vanilla`,
   - each variant run calls `labelstudio-benchmark` with `--no-upload --eval-mode canonical-text`,
   - prediction generation now inherits shared ingest defaults for canonical line-role codex inflight: non-split jobs default to `8`; split-gated jobs default to `4`; explicit `COOKIMPORT_LINE_ROLE_CODEX_MAX_INFLIGHT` overrides both,
   - source slug is derived from the selected source filename stem (slugified),
   - for paired codex+vanilla runs, split conversion is cached once and reused across variants (default cache root: `.../single-book-benchmark/<source_slug>/.split-cache`),
   - repeated interactive single-book reruns now also reuse finished prediction artifacts across sessions from `<interactive output_dir>/.prediction_reuse_cache/` by default (or `COOKIMPORT_ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT` when set), so a warm rerun can skip the full prediction stage and just materialize the prior variant outputs into the new timestamped session root,
   - single-book split-cache controls are available on `labelstudio-benchmark`: `--single-book-split-cache-mode`, `--single-book-split-cache-dir`, `--single-book-split-cache-force`,
   - for codex-enabled paired runs, writes comparison artifacts only when both variant runs succeed:
     - `single-book-benchmark/<source_slug>/codex_vs_vanilla_comparison.json` (always)
     - comparison JSON metadata now includes `per_label_breakdown` aggregated across the latest paired evals (`label`, strict `precision`, strict `recall`, `gold_total`, `pred_total`)
     - `single-book-benchmark/<source_slug>/single_book_summary.md` now shows per-label tables per variant; it does not embed the paired aggregate per-label table from comparison metadata
     - also writes `single-book-benchmark/<source_slug>/starter_pack_v1/` by running the benchmark cutdown starter-pack builder in-place against the paired variant run dirs
     - paired starter-pack generation also writes `single-book-benchmark/<source_slug>/benchmark_summary.md` (flattened comparison + starter-pack summary)
     - also writes a dedicated 3-file upload folder: `single-book-benchmark/<source_slug>/upload_bundle_v1/`:
       - `upload_bundle_overview.md`
     - `upload_bundle_index.json`
     - `upload_bundle_payload.jsonl`
3. Matched-set picker path:
   - matched-book selection rows reuse the same concise book label style as the single-book gold picker instead of mixing source filename plus bracketed gold label text.
     - after that bundle is written, interactive single-book mode starts Oracle automatically in the background instead of blocking benchmark wrap-up
     - Oracle now uses one auto browser launcher everywhere: it opens visible Chromium when a usable display exists and falls back to xvfb otherwise
     - the wrap-up prints the detached Oracle PID, the chosen browser-profile path, and one explicit `oracle_upload.log` response/log path under `upload_bundle_v1/.oracle_upload_runs/<timestamp>/`; full command/shard detail stays in the log/metadata files instead of spamming the terminal
   - when markdown writes are enabled, single-book writes one consolidated top-level markdown file:
     - `single-book-benchmark/<source_slug>/single_book_summary.md`
   - if one variant fails, successful variant artifacts are preserved and comparison artifacts are skipped,
   - defaults to writing markdown summaries on and Label Studio task artifacts off in interactive mode
     (set `COOKIMPORT_BENCH_WRITE_MARKDOWN=0` to disable summaries, and `COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS=1` to keep task JSONL).
   - keeps spinner/status visible for both prediction generation and evaluation phases,
   - benchmark status panels now treat generic phase messages shaped like `task X/Y | running N` the same way as codex-farm progress, so canonical line-role stages also render worker rows instead of only a single status line,
   - split conversion progress uses the shared counter format from the first update (`Running split conversion... task 0/N`), with `(workers=N)` suffix when split jobs run in parallel,
   - does not resolve Label Studio credentials,
   - writes eval artifacts under `data/golden/benchmark-vs-golden/<timestamp>/single-book-benchmark/<source_slug>/<variant>/`.
3. Single-profile matched-sets path:
   - uses the same compact automatic top-tier profile selector as single-book,
   - discovers freeform exports and matches source hints to top-level importable files in `data/input` by filename,
   - selected-matched mode lets you toggle specific books and run only that subset (or choose `Run all matched books`),
   - defaults to writing markdown summaries on and Label Studio task artifacts off in interactive mode
     (set `COOKIMPORT_BENCH_WRITE_MARKDOWN=0` to disable summaries, and `COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS=1` to keep task JSONL).
   - prints matched/skipped counts and asks final proceed confirmation (`Proceed with N benchmark runs across N matched golden sets?` or `... across N selected matched books?`, default `No`),
   - normalizes variants from the selected run settings:
     - when `llm_recipe_pipeline=off`, runs one `vanilla` variant per selected book under `single-profile-benchmark/<index_source_slug>/`,
     - when `llm_recipe_pipeline` is non-`off`, runs paired variants per selected book:
       - `single-profile-benchmark/<index_source_slug>/vanilla` first (`llm_recipe_pipeline=off`, deterministic-only),
       - `single-profile-benchmark/<index_source_slug>/codex-exec` second (preserving the selected non-`off` recipe pipeline while still forcing `line_role_pipeline=codex-line-role-route-v2`, and now sharing the selected `atomic_block_splitter` value with the paired `vanilla` run),
   - for paired codex+vanilla selected/all-matched runs, writes per-book comparison only when both variants succeed:
     - `single-profile-benchmark/<index_source_slug>/codex_vs_vanilla_comparison.json`,
   - runs `labelstudio-benchmark` with `--no-upload --eval-mode canonical-text` for each planned variant run (no all-method variant expansion),
   - when 2+ books are selected, runs up to three books concurrently (`parallel books=3`),
   - single-profile runs use the same shared ingest inflight defaults; because multi-book mode enables split-phase gating, canonical line-role codex inflight defaults to `4` there (single-book stays at `8` unless env override is set),
   - concurrent single-profile runs downscale per-book `workers`, `pdf_split_workers`, and `epub_split_workers` to 80% of the chosen run-settings values,
   - concurrent single-profile runs enforce one shared split conversion slot (`split conversion slots=1`) across the selected books,
   - concurrent single-profile runs now use one shared spinner dashboard for the whole batch; inner per-book benchmark runs suppress their own spinners and stream progress into shared per-book queue/task lines,
   - repeated interactive single-profile reruns now reuse finished per-book prediction artifacts from the same stable prediction-reuse cache used by single-book mode before launching a fresh prediction stage,
   - codex-farm subprocess failures that expose `stderr_summary=` are condensed before display in the interactive single-profile summary so precheck/auth/quota failures show the real precheck message instead of raw `out_dir=...` exception details,
   - continues when an individual source fails and prints a failure summary at the end,
   - writes eval artifacts under `data/golden/benchmark-vs-golden/<timestamp>/single-profile-benchmark/<index_source_slug>/` (paired runs nest under `/vanilla` and `/codex-exec`),
   - writes a dedicated 3-file upload folder per target eval root:
     - `single-profile-benchmark/<index_source_slug>/upload_bundle_v1/upload_bundle_overview.md`
     - `single-profile-benchmark/<index_source_slug>/upload_bundle_v1/upload_bundle_index.json`
     - `single-profile-benchmark/<index_source_slug>/upload_bundle_v1/upload_bundle_payload.jsonl`
   - multi-book runs also write one shared 3-file group upload folder:
     - `single-profile-benchmark/upload_bundle_v1/upload_bundle_overview.md`
     - `single-profile-benchmark/upload_bundle_v1/upload_bundle_index.json`
     - `single-profile-benchmark/upload_bundle_v1/upload_bundle_payload.jsonl`
     - group mode targets ~40MB and automatically lowers per-book sampled detail as selected-book count increases.
     - when that group bundle is written, interactive multi-book single-profile mode starts Oracle automatically in the background for that top-level bundle; per-book bundles are retained but not auto-uploaded
     - Oracle now uses that same auto browser launcher here too: visible Chromium when a usable display exists, xvfb otherwise
     - the wrap-up prints the detached Oracle PID, the chosen browser-profile path, and one explicit `oracle_upload.log` response/log path under `upload_bundle_v1/.oracle_upload_runs/<timestamp>/`; full command/shard detail stays in the log/metadata files instead of spamming the terminal
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
- `cookimport compare-control <run|agent|discovery-preferences|dashboard-state>`
- `cookimport bench <oracle-upload|oracle-followup|speed-discover|speed-run|speed-compare|gc|pin|unpin|quality-discover|quality-run|quality-leaderboard|quality-compare|eval-stage>`

`cookimport bench oracle-upload <session root or upload_bundle_v1>` reuses an existing benchmark bundle without rerunning the benchmark. It now launches both Oracle review lanes by default and accepts `--profile quality|token|all` for replay control. `--mode dry-run` is the low-cost validation path; when the payload file is too large for Oracle's inline dry-run, the command falls back to a local preview and tells you to use browser mode for the real upload.

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
When a Codex-backed stage summary reports guardrail pressure, that same quick summary and `run_summary.{json,md}` now include a `Codex guardrails` section with planned-versus-actual worker-session counts and any `task.json` size warnings; the CLI warns without silently changing shard or worker counts.
Codex-backed stage runs now have a single live execution mode.
For zero-token inspection, use prompt preview to inspect prompt text/costs or run the normal execute path through `scripts/fake-codex-farm.py` to rehearse file handoffs without model spend.

Arguments:

- `PATH` (required): file or folder to stage.

Options:

- `--out PATH` (default `data/output`): output root.
- `--mapping PATH`: explicit mapping config path.
- `--overrides PATH`: explicit parsing overrides path.
- `--limit, -n INTEGER>=1`: limit recipes per file.
- `--pdf-ocr-policy TEXT` (default `auto`): `off|auto|always` OCR policy for PDFs.
- `--ocr-device TEXT` (default `auto`): `auto|cpu|cuda|mps`.
- `--ocr-batch-size INTEGER>=1` (default `1`): pages per OCR model call.
- `--pdf-pages-per-job INTEGER>=1` (default `50`): page shard size for PDF splitting.
- `--epub-spine-items-per-job INTEGER>=1` (default `10`): spine-item shard size for EPUB splitting.
- `--warm-models` (default `false`): preload heavy models before processing.
- `--workers, -w INTEGER>=1` (default `7`): total process pool workers.
- `--require-process-workers / --allow-worker-fallback` (default allow fallback): fail fast when process workers are unavailable instead of falling back to subprocess/thread/serial.
- `--pdf-split-workers INTEGER>=1` (default `7`): max workers for one split PDF.
- `--epub-split-workers INTEGER>=1` (default `7`): max workers for one split EPUB.
- `--write-markdown / --no-write-markdown` (default write): write markdown sidecar artifacts (`sections.md`, `chunks.md`, `tables.md`).
- `--epub-extractor TEXT` (default `unstructured`): default-enabled values are `unstructured|beautifulsoup`; `markdown|markitdown` are rejected unless `COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS=1`. Exported to `C3IMP_EPUB_EXTRACTOR` for importer runtime.
- `--epub-unstructured-html-parser-version TEXT` (default `v1`): `v1|v2`; exported to `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`.
- `--epub-unstructured-skip-headers-footers / --no-epub-unstructured-skip-headers-footers` (default enabled): exported to `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`.
- `--epub-unstructured-preprocess-mode TEXT` (default `br_split_v1`): `none|br_split_v1`; exported to `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`.
- `--recipe-scorer-backend TEXT` (default `heuristic_v1`): recipe-likeness scorer backend.
- `--recipe-score-gold-min FLOAT` (default `0.75`): minimum score for `gold` tier.
- `--recipe-score-silver-min FLOAT` (default `0.55`): minimum score for `silver` tier.
- `--recipe-score-bronze-min FLOAT` (default `0.35`): minimum score for `bronze` tier.
- `--recipe-score-min-ingredient-lines INTEGER>=0` (default `1`): soft minimum ingredient line hint for scoring/gating.
- `--recipe-score-min-instruction-lines INTEGER>=0` (default `1`): soft minimum instruction line hint for scoring/gating.
- `--section-detector-backend TEXT` (default `shared_v1`): `shared_v1`; controls importer section extraction backend.
- `--multi-recipe-splitter TEXT` (default `rules_v1`): `off|rules_v1`; controls shared multi-recipe candidate split backend for Text/EPUB/PDF importers.
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
- `--llm-recipe-pipeline TEXT` (default `off`): `off|codex-recipe-shard-v1`.
- `--llm-knowledge-pipeline TEXT` (default `off`): `off|codex-knowledge-candidate-v2`.
- `--allow-codex / --no-allow-codex` (default disabled): required for execute-mode Codex-backed stage runs.
- `--codex-farm-cmd TEXT` (default `codex-farm`): subprocess command used to invoke codex-farm.
- `--codex-farm-root PATH` (default unset): optional codex-farm pipeline-pack root; defaults to `<repo_root>/llm_pipelines`.
- `--codex-farm-workspace-root PATH` (default unset): optional workspace root passed to codex-farm (`--workspace-root`).
- `--codex-farm-context-blocks INTEGER>=0` (default `30`): context blocks before/after candidate for recipe-correction bundles.
- `--codex-farm-knowledge-context-blocks INTEGER>=0` (default `0`): context blocks before/after each knowledge chunk for knowledge bundles.
- `--codex-farm-failure-mode TEXT` (default `fail`): `fail|fallback` behavior when codex-farm setup/invocation fails.
- Internal-only note: stage still accepts hidden codex-farm pipeline-id/debug overrides for experiments and old payload replay, but they are no longer advertised in `--help`.
- `markitdown` note: EPUB split jobs are disabled for this extractor because conversion is whole-book EPUB -> markdown (no spine-range mode).
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
- `cookimport epub blocks PATH --out OUTDIR [--extractor unstructured|beautifulsoup|markdown|markitdown] [--start-spine N] [--end-spine M] [--html-parser-version v1|v2] [--skip-headers-footers] [--preprocess-mode none|br_split_v1] [--force]`
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
- `--prelabel-provider TEXT` (default `codex-farm`): provider backend for prelabeling.
- `--codex-cmd TEXT`: override Codex Exec command (defaults to `COOKIMPORT_CODEX_CMD`, `COOKIMPORT_CODEX_FARM_CMD`, or `codex-farm`).
- `--codex-model TEXT`: explicit Codex model for prelabel calls (defaults to `COOKIMPORT_CODEX_FARM_MODEL`, `COOKIMPORT_CODEX_MODEL`, or local defaults).
- `--codex-thinking-effort`, `--codex-reasoning-effort` (alias flags): Codex reasoning-effort hint (`none|minimal|low|medium|high|xhigh`, normalized to model-supported values).
- `--prelabel-timeout-seconds INTEGER>=1` (default `600`): timeout per provider call.
- `--prelabel-cache-dir PATH`: optional prompt/response cache directory.
- `--prelabel-workers INTEGER>=1` (default `15`): concurrent freeform prelabel provider calls (`1` keeps serialized behavior).
- `--prelabel-upload-as TEXT` (default `annotations`): `annotations|predictions`.
- `--prelabel-granularity TEXT` (default `block`): `block|span` (`block` = block based; `span` = actual freeform).
- `--prelabel-allow-partial / --no-prelabel-allow-partial` (default disabled): continue upload when some prelabels fail.
- `--llm-recipe-pipeline TEXT` (default `off`): `off|codex-recipe-shard-v1`.
- `--codex-farm-cmd TEXT` (default `codex-farm`): subprocess command used when `--llm-recipe-pipeline` is enabled.
- `--codex-farm-root PATH` (default unset): optional codex-farm pipeline-pack root; defaults to `<repo_root>/llm_pipelines`.
- `--codex-farm-workspace-root PATH` (default unset): optional workspace root passed to codex-farm (`--workspace-root`).
- `--codex-farm-context-blocks INTEGER>=0` (default `30`): context blocks before/after candidate in pass-1 bundles.
- `--codex-farm-failure-mode TEXT` (default `fail`): `fail|fallback` behavior when codex-farm setup/invocation fails.

Prelabel behavior notes:
- `labelstudio-import` is freeform-only (`freeform-spans`), so `--prelabel` always applies to freeform tasks.
- `--prelabel-upload-as annotations` first tries inline annotation upload and falls back to task-only upload + per-task annotation create when needed.
- When prelabel failures occur (especially with `--prelabel-allow-partial`), the CLI prints an explicit red `PRELABEL ERRORS: X/Y ...` summary plus `prelabel_errors.jsonl` path at run completion.

Hard requirement:

- Upload is blocked unless `--allow-labelstudio-write` is set.
- Codex-backed import work still requires explicit `--allow-codex`.

### `cookimport labelstudio-export`

Exports completed labels to golden-set artifacts.

Options:

- `--project-name TEXT` (required): Label Studio project name.
- `--output-dir PATH` (default `data/golden/pulled-from-labelstudio`): output root.
- `--run-dir PATH`: export from a specific run directory.
- `--label-studio-url TEXT`: explicit Label Studio URL.
- `--label-studio-api-key TEXT`: explicit Label Studio API key.
- Export supports freeform projects only.

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
- `cookimport labelstudio-benchmark compare --baseline ... --candidate ...` compares either:
  - two all-method benchmark outputs (`all_method_benchmark_multi_source_report.json` roots), or
  - two single-run eval outputs (`eval_report.json` files/directories),
  and writes timestamped gate reports (`comparison.json`, `comparison.md`) under `--compare-out`.
- Offline prediction generation can skip non-scoring side artifacts via:
  - `--no-write-markdown` to skip markdown sidecars in processed stage outputs.
  - `--no-write-labelstudio-tasks` to skip `label_studio_tasks.jsonl` in offline pred-runs (stage-block scoring remains unchanged because it reads stage evidence + extracted archive).
- Eval mode is configurable via `--eval-mode stage-blocks|canonical-text` (default `stage-blocks`).
- Benchmark execution is fixed to `pipelined`.
- Codex-backed benchmark runs now have a single live execution mode.
  - For prompt/cost inspection, use prompt preview.
  - For zero-token handoff rehearsal, run the normal execute path with `--codex-farm-cmd scripts/fake-codex-farm.py`.
- Single-book split-cache controls:
  - `--single-book-split-cache-mode off|auto` toggles single-book split cache usage.
  - `--single-book-split-cache-dir PATH` overrides the single-book cache root.
  - `--single-book-split-cache-force` forces single-book cache rebuild for that run.
- Prediction-record roundtrip supports evaluate-only replays:
  - `--predictions-out` writes prediction-stage records to JSONL.
  - `--predictions-in` skips generation and evaluates from a prior record JSONL.
  - `--predictions-in` and `--predictions-out` are mutually exclusive.
- Re-scoring an old prediction run without regeneration is still done with `cookimport labelstudio-eval --pred-run ... --gold-spans ...`.
- Interactive mode (`cookimport` -> Benchmark) always runs offline benchmark generation/eval (`single book` or matched-books modes).
- Successful runs persist benchmark timing under `eval_report.json` `timing`, including prediction/evaluation/write/history subphase timings and checkpoints.
- Benchmark spinner telemetry is also persisted per phase:
  - `<eval_output_dir>/processing_timeseries_prediction.jsonl`
  - `<eval_output_dir>/processing_timeseries_evaluation.jsonl` (when evaluation runs)
- Those per-phase time-series rows now also persist stage-centric fields (`stage_label`, `work_unit_label`, `active_tasks`, typed worker/follow-up counts, `artifact_counts`, `detail_lines`, effective worker counts) when a stage emits structured progress snapshots, so line-role/knowledge/recipe debugging does not depend on terminal screenshots.
- Recipe phase workers, label-first authority building, and staged output writing now emit the same structured progress payload family too, so benchmark/import spinners stay rich outside the original line-role + knowledge stages.
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
  Interactive selection shows discovered exports as book-slug labels for readability.
- `--source-file PATH`: source file to re-import for predictions; if omitted, prompt/infer.
  Interactive benchmark auto-uses an inferred source file when available and only prompts for source selection when inference fails.
- `ACTION` positional (default `run`): `run|compare`.
- `--output-dir PATH` (default `data/golden/benchmark-vs-golden`): scratch root for prediction import artifacts.
- `--processed-output-dir PATH` (default `data/output`): root for staged cookbook outputs generated during benchmark.
- `--eval-output-dir PATH`: destination for benchmark report artifacts.
- `--overlap-threshold FLOAT 0..1` (default `0.5`): match threshold.
- `--force-source-match` (default `false`): ignore source identity checks while matching.
- `--eval-mode TEXT` (default `stage-blocks`): `stage-blocks|canonical-text`.
- Canonical-text benchmark matching is fixed to `dmp`.
- `--pdf-ocr-policy TEXT` (default `auto`): `off|auto|always` OCR policy for PDF prediction generation.
- `--pdf-column-gap-ratio FLOAT` (default `0.12`): PDF column-gap threshold ratio for column reconstruction.
- `--line-role-guardrail-mode TEXT` (default `enforce`): `off|preview|enforce`; controls whether line-role do-no-harm arbitration is disabled, reported-only, or mutating.
- `--single-book-split-cache-mode TEXT` (default `off`): `off|auto` split-cache mode for single-book benchmark prediction generation.
- `--single-book-split-cache-dir PATH`: optional root for single-book split-cache entries.
- `--single-book-split-cache-force / --no-single-book-split-cache-force` (default disabled): force split-cache rebuild for the current run.
- `--predictions-out PATH`: optional JSONL output for prediction-stage records (for later evaluate-only runs).
- `--predictions-in PATH`: optional JSONL input to run evaluate-only without generating predictions.
- `--baseline PATH`: compare action only; baseline all-method benchmark directory/report JSON or single-eval `eval_report.json` path/directory.
- `--candidate PATH`: compare action only; candidate all-method benchmark directory/report JSON or single-eval `eval_report.json` path/directory.
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
- `--epub-unstructured-preprocess-mode TEXT` (default `br_split_v1`): `none|br_split_v1`; exported to `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`.
- `--recipe-scorer-backend TEXT` (default `heuristic_v1`): recipe-likeness scorer backend.
- `--recipe-score-gold-min FLOAT` (default `0.75`): minimum score for `gold` tier.
- `--recipe-score-silver-min FLOAT` (default `0.55`): minimum score for `silver` tier.
- `--recipe-score-bronze-min FLOAT` (default `0.35`): minimum score for `bronze` tier.
- `--recipe-score-min-ingredient-lines INTEGER>=0` (default `1`): soft minimum ingredient line hint for scoring/gating.
- `--recipe-score-min-instruction-lines INTEGER>=0` (default `1`): soft minimum instruction line hint for scoring/gating.
- `--section-detector-backend TEXT` (default `shared_v1`): `shared_v1`; controls importer section extraction backend for prediction generation.
- `--multi-recipe-splitter TEXT` (default `rules_v1`): `off|rules_v1`; controls shared multi-recipe candidate split backend for Text/EPUB/PDF prediction imports.
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
- `--llm-recipe-pipeline TEXT` (default `off`): `off|codex-recipe-shard-v1`.
- `--codex-farm-recipe-mode TEXT` (default `extract`): `extract|benchmark`.
- `--codex-farm-cmd TEXT` (default `codex-farm`): subprocess command used to invoke codex-farm during prediction generation.
- `--codex-farm-root PATH` (default unset): optional codex-farm pipeline-pack root; defaults to `<repo_root>/llm_pipelines`.
- `--codex-farm-workspace-root PATH` (default unset): optional workspace root passed to codex-farm (`--workspace-root`).
- `--codex-farm-context-blocks INTEGER>=0` (default `30`): context blocks before/after candidate for recipe-correction bundles.
- `--codex-farm-failure-mode TEXT` (default `fail`): `fail|fallback` behavior when codex-farm setup/invocation fails.
- `--alignment-cache-dir PATH` (internal/hidden): optional canonical alignment cache directory override for benchmark runs.
- Internal-only note: hidden benchmark options still exist for pipeline-id and selective-retry experiments, but normal `labelstudio-benchmark --help` no longer advertises them.
- `markitdown` note: prediction EPUB split jobs are disabled for this extractor for the same reason as stage runs.
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
- `--scenarios TEXT` (default `stage_import,benchmark_canonical_pipelined`): comma-separated scenario list from `stage_import|benchmark_canonical_pipelined|benchmark_all_method_multi_source`.
- `--warmups INTEGER>=0` (default `1`): warmup samples per target+scenario (excluded from medians).
- `--repeats INTEGER>=1` (default `2`): measured samples per target+scenario.
- `--max-targets INTEGER>=1`: optional cap on number of targets from the suite.
- `--max-parallel-tasks INTEGER>=1`: optional fixed SpeedSuite task concurrency cap. When omitted, speed-run auto-selects `min(total_tasks, cpu_count, 4)`.
- `--require-process-workers / --allow-worker-fallback` (default allow fallback): fail fast when stage/all-method internals cannot use process workers.
- `--resume-run-dir PATH`: resume an existing speed run directory and skip tasks with completed sample snapshots.
- `--run-settings-file PATH`: optional JSON payload in `RunSettings` shape for deterministic speed-run settings.
- Canonical-text benchmark matching is fixed to `dmp` for normal runs; older saved payloads may still contain `benchmark_sequence_matcher` as a load-time transition key.
- `--include-codex-farm / --no-include-codex-farm` (default disabled): include Codex Exec recipe-pipeline permutations in all-method scenarios.
- `--speedsuite-codex-farm-confirmation TEXT`: required with `--include-codex-farm`; must be `I_HAVE_EXPLICIT_USER_CONFIRMATION`.
- `--codex-farm-model TEXT`: optional Codex Exec model override (blank keeps pipeline defaults).
- `--codex-farm-thinking-effort|--codex-farm-reasoning-effort TEXT`: optional Codex Exec reasoning-effort override (`none|minimal|low|medium|high|xhigh`) (blank keeps pipeline defaults).

`cookimport labelstudio-import` also exposes `--upload-batch-size INTEGER` (default `200`) so Label Studio task uploads can be chunked without changing `cookimport/labelstudio/ingest_flows/upload.py`.

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
- `--include-codex-farm / --no-include-codex-farm` (default disabled): include Codex Exec recipe-pipeline permutations in all-method runs.
- `--qualitysuite-codex-farm-confirmation TEXT`: required with `--include-codex-farm`; must be `I_HAVE_EXPLICIT_USER_CONFIRMATION`.
- `--codex-farm-model TEXT`: optional Codex Exec model override applied to all experiments.
- `--codex-farm-thinking-effort|--codex-farm-reasoning-effort TEXT`: optional Codex Exec reasoning-effort override (`none|minimal|low|medium|high|xhigh`) applied to all experiments.
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

## Environment Variables

CLI-relevant environment variables:

- `C3IMP_LIMIT`: used by interactive mode callback. If set to an integer, interactive import uses it as `stage --limit`.
- `COOKIMPORT_WORKER_UTILIZATION`: optional percentage or ratio for interactive per-run concurrency defaults in `C3imp` (defaults to `90`).
- `COOKIMPORT_IO_PACE_EVERY_WRITES` / `COOKIMPORT_IO_PACE_SLEEP_MS`: optional disk write pacing controls (default `16` and `8` in `C3imp`).
- `C3IMP_EPUB_EXTRACTOR`: EPUB extractor switch read at runtime by the EPUB importer (default-enabled: `unstructured`, `beautifulsoup`; `markdown`/`markitdown` require `COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS=1`).
- `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`: unstructured HTML parser version (`v1` or `v2`) for EPUB extraction.
- `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`: bool toggle for Unstructured `skip_headers_and_footers` on EPUB HTML.
- `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`: EPUB HTML preprocess mode before Unstructured (`none`, `br_split_v1`).
- `C3IMP_EPUBCHECK_JAR`: optional EPUBCheck jar path used by `cookimport epub validate` when `--jar` is omitted.
- `COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS`: unlocks `markdown`/`markitdown` EPUB extractors across stage/prediction/debug command paths when set truthy (`1|true|yes|on`).
- `COOKIMPORT_ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS`: include optional markdown-based extractors in all-method permutations when set to `1`.
- `COOKIMPORT_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS`: optional auto-mode ceiling for `bench quality-run` experiment concurrency (default follows detected CPU count; ignored when `--max-parallel-experiments` is set).
- `COOKIMPORT_QUALITY_EXPERIMENT_EXECUTOR_MODE`: quality-run experiment fanout backend (`auto` default, `thread`, or `subprocess`). `auto` picks subprocess fanout when process-pool probing fails.
- `JOBLIB_MULTIPROCESSING`: when unset, startup now auto-sets `JOBLIB_MULTIPROCESSING=0` in SemLock-restricted runtimes to avoid noisy `joblib ... will operate in serial mode` warnings.
- `COOKIMPORT_DISABLE_JOBLIB_SEMLOCK_GUARD`: disable the automatic `JOBLIB_MULTIPROCESSING` guard (`1|true|yes|on`).
- `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER`: canonical-text matcher selection (`dmp` only; non-`dmp` values are invalid).
- `COOKIMPORT_BENCHMARK_EVAL_PROFILE_MIN_SECONDS`: optional profiler threshold for benchmark evaluation stage (`>=0`; enables profile artifact capture when eval runtime meets threshold).
- `COOKIMPORT_BENCHMARK_EVAL_PROFILE_TOP_N`: optional `pstats` top-N row count for benchmark evaluation profiling output (default `40`).
- `COOKIMPORT_CODEX_CMD`: primary command override for prelabel Codex Exec flows when `--codex-cmd` is omitted.
- `COOKIMPORT_CODEX_FARM_CMD`: fallback command override for prelabel Codex Exec flows.
- `COOKIMPORT_CODEX_MODEL`: default Codex model used by prelabel flows when `--codex-model` is omitted.
- `LABEL_STUDIO_URL`: default Label Studio URL when `--label-studio-url` is omitted.
- `LABEL_STUDIO_API_KEY`: default Label Studio API key when `--label-studio-api-key` is omitted.
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
- For all-method codex variants: `--include-codex-farm` controls inclusion; `bench speed-run` requires `--speedsuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`; `bench quality-run` requires `--qualitysuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`.
- Benchmark sequence matcher is now fixed product behavior (`dmp`) rather than a user setting; manifests record `bucket1_fixed_behavior_version` instead of treating matcher choice as a normal knob.
## Interactive Seam Notes

- Shared interactive run-settings UX lives in `cookimport/cli_ui/run_settings_flow.py`:
  - top-tier workflow choice
  - the single-screen Codex Exec per-surface submenu
  - shared model / reasoning override prompts
- Benchmark-only gold/source selection lives in the benchmark helpers, primarily `_resolve_benchmark_gold_and_source(...)` in `cookimport/cli_support/bench_all_method.py`. Changes there affect benchmark picking flows only, not import/upload/export/dashboard menus.
- The Codex Exec submenu is intentionally one screen with aligned `[Yes]` / `[No]` columns:
  - up/down changes rows
  - left/right changes the active row in place
  - Enter can still flip the current row
  - `Continue` commits the whole selection set
- All interactive benchmark callers that expose Codex Exec should reuse that same shared submenu, including all-method benchmark flows.
- All-method benchmark Codex variants inherit the full benchmark Codex contract, so a generic `Include Codex Exec permutations?` prompt is misleading. The correct surface is explicit recipe / line-role / knowledge selection.
- Interactive benchmark pickers should reuse one concise book identity across flows. The matched-books picker should not drift back to `source filename + [gold label]` formatting noise.
- For prompt/cost inspection, use `cf-debug preview-prompts`.
- For runtime artifact rehearsal without live spend, use `scripts/fake-codex-farm.py`.
- Interactive prompt-count entry should be read as a surface request, not one universal planner law:
  - recipe and line-role use the chosen count as a literal shard-count override
  - knowledge still records the chosen count but may exceed it when hard bundle safety caps win


## Related Docs

- Import flow details: `docs/03-ingestion/03-ingestion_readme.md`
- Output/staging behavior: `docs/05-staging/05-staging_readme.md`
- Labeling and eval workflows: `docs/06-label-studio/06-label-studio_README.md`
- Offline bench suite: `docs/07-bench/07-bench_README.md`
