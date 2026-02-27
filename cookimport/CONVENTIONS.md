# cookimport Conventions

Durable CLI/runtime conventions for top-level orchestration code (primarily `cookimport/cli.py` and entrypoints).

## CLI Discovery Rule

Interactive file discovery and direct staging intentionally differ:

- Interactive menu discovery (`cookimport` with no subcommand) scans only top-level files in `data/input`.
- Direct staging (`cookimport stage <folder>`) scans recursively under the folder.
- Interactive `labelstudio` import always recreates the resolved Label Studio project (`overwrite=True`, `resume=False`) and does not prompt for resume mode.
- Interactive `labelstudio` import is freeform-only and no longer asks for upload confirmation; once freeform/prelabel options are chosen, it proceeds directly to upload (after credential resolution).
- Interactive freeform `labelstudio` import prompts for AI prelabel mode (`off`, `strict`, `allow-partial`, plus advanced predictions modes) during the same prompt flow, then prompts for labeling style (`actual freeform` span mode vs `legacy, block based` mode); do not require leaving interactive mode for first-pass AI annotations.
- Interactive freeform `labelstudio` prelabel flow includes explicit Codex model selection followed by model-compatible thinking effort selection (`none|low|medium|high|xhigh` and filtered by selected model metadata); `minimal` must stay hidden for this workflow due Codex tool compatibility failures. Token-usage tracking is always enabled and should not be a prompt.
- Interactive and non-interactive `labelstudio` import must use the same status/progress callback wiring so long-running phases (especially AI prelabeling) show a live spinner/status update path.
- `labelstudio` resume semantics apply only when the target Label Studio project already exists; if a run creates a new project, do not reuse local manifest task IDs from older runs.
- Spinner/progress text for known-size worklists should include `<noun> X/Y` counters (for example `task`, `item`, `config`, `phase`) rather than phase-only text so operators can track throughput.
- Callback-driven CLI spinners (`labelstudio` import, benchmark import, bench run/sweep) should append elapsed seconds after prolonged unchanged phases (default threshold: 10s) so users can see that work is still running when a phase message is stale. When status text includes `<noun> X/Y`, the same spinner path should estimate ETA as average seconds-per-unit times remaining units. When worker telemetry is emitted, render per-worker activity lines under the main spinner status.
- Progress callback plumbing is telemetry-only: exceptions raised by UI/status callbacks must be logged and ignored (never allowed to abort extraction, task generation, or upload flows).
- Interactive `labelstudio` export resolves credentials first, then lists project titles from Label Studio for selection, with manual entry fallback when discovery is unavailable. Export is freeform-only and should reject legacy `pipeline` / `canonical-blocks` projects explicitly.
- Golden workflow roots are split by purpose:
  - Label Studio task-generation/import artifacts: `data/golden/sent-to-labelstudio/<timestamp>/...`
  - Label Studio export artifacts: `data/golden/pulled-from-labelstudio/<project_slug>/exports/...`
  - Benchmark/eval artifacts: `data/golden/benchmark-vs-golden/<timestamp>/...`
- Label Studio export (interactive and non-interactive) writes to a stable project root by default: `data/golden/pulled-from-labelstudio/<project_slug>/exports/...`; it uses prior manifests for project resolution and legacy-scope rejection, not for export destination. `--run-dir` still forces export into a specific run.
- Interactive main menu is persistent: successful `import`, `labelstudio`, `labelstudio_export`, and `labelstudio_benchmark` actions all return to the main menu. The session exits only when the user selects `Exit`.
- Interactive select menus should be wired through `_menu_select` so numbering, shortcuts, and Esc-go-back behavior remain consistent.
- Interactive typed prompts in CLI flows should use `_prompt_text`, `_prompt_confirm`, or `_prompt_password` so `Esc` consistently maps to one-level back/cancel behavior.
- Questionary `text/password/confirm` prompts expose merged key bindings (`_MergedKeyBindings`) at runtime; `Esc` overrides must be attached via `merge_key_bindings(...)` (not `.add(...)` on `application.key_bindings`).
- Freeform interactive segment sizing (`segment_blocks`, `segment_overlap`, `segment_focus_blocks`, `target_task_count`) should route through `_prompt_freeform_segment_settings(...)` so `Esc` walks back one field instead of dropping to main menu.
- Interactive Import and interactive benchmark single-offline mode go through a per-run settings chooser (`global defaults`, `last run settings`, `change run settings`) before execution.
- Interactive benchmark (`labelstudio_benchmark`) now has a mode submenu:
  - single offline mode (default first choice): one local evaluate run with `no_upload=True` (no Label Studio credential resolution, no upload),
  - all-method mode: offline permutation sweep (no Label Studio credential resolution, no upload).
- Interactive benchmark modes (`single_offline` and `all_method`) should run `labelstudio-benchmark` in `canonical-text` eval mode so one freeform gold export can compare extractor/config permutations without block-index parity.
- Interactive benchmark asks for mode first; only single-offline mode shows the benchmark run-settings chooser.
- Interactive all-method benchmark must use global benchmark defaults directly, and should not overwrite `last_run_settings_benchmark` snapshots.
- Interactive all-method benchmark must ask scope (`Single golden set` vs `All golden sets with matching input files`), print planned run counts before execution, default Codex Farm inclusion prompt to `No`, and require explicit proceed confirmation before running N configs.
- Interactive all-method benchmark scheduler defaults are bounded (`inflight pipelines=4`, `split-phase slots=4`), and scheduler controls are configurable via `cookimport.json` keys:
  - `all_method_max_parallel_sources`
  - `all_method_max_inflight_pipelines`
  - `all_method_max_split_phase_slots`
  - `all_method_wing_backlog_target`
  - `all_method_smart_scheduler`
  - `all_method_config_timeout_seconds`
  - `all_method_retry_failed_configs`
- Interactive all-method benchmark should print resolved scheduler mode/limits before final confirmation, including source parallelism configured/effective, configured/effective inflight, split slots, wing backlog target, smart tail buffer, timeout, and retry settings.
- Interactive all-method benchmark should render one persistent spinner dashboard (book queue + overall source/config counters + current task) and suppress per-config `labelstudio-benchmark` completion dumps while the sweep is running.
- Interactive all-method spinner/dashboard task output should include a scheduler snapshot line: `scheduler heavy X/Y | wing Z | active A | pending P`.
- All-method spinner `current config` should track active config slots in parallel mode; when multiple configs are active, render a range (`current configs A-B/N`) instead of a stale last-submitted slug.
- For multi-active `current configs` states, render per-config worker detail lines (`config NN: <phase> | <slug>`) so active slot activity remains visible.
- All-matched all-method spinner queue should support multiple simultaneously running sources (`[>]` rows), with summary line `active sources: N`.
- All-method dashboard snapshots (`overall source ... | config ...` + `queue:`) are already fully-rendered spinner payloads; upstream wrappers must not nest them into `task:` text. When an inbound snapshot is stale/partial, wrappers should rerender from shared dashboard state before emitting.
- Split-slot acquire/wait/release telemetry in all-method worker configs should stay callback-driven; subprocess configs must not emit raw stdout `print(...)` slot lines while the outer spinner is active.
- For multi-line spinner payloads (all-method dashboard snapshots), ETA/elapsed suffix decoration belongs on the first summary line, not the trailing `task:` line.
- All-method scheduler phase telemetry should be persisted per config under `<source_root>/.scheduler_events/config_###.jsonl` so parent scheduling and post-run metrics can infer `prep`, `split_wait`, `split_active`, and `post` occupancy.
- All-matched all-method source hint order is: run `manifest.json` `source_file` -> first non-empty `freeform_span_labels.jsonl` row `source_file` -> first non-empty `freeform_segment_manifest.jsonl` row `source_file`.
- All-matched all-method runs must persist one combined summary report at `<benchmark_eval_output>/all-method-benchmark/all_method_benchmark_multi_source_report.{json,md}` in addition to per-source reports.
- Freeform benchmark/reporting contract now exposes two metric tracks everywhere (eval JSON/MD, bench reports, CSV history, dashboard): Practical/content-overlap (`practical_*`) and Strict/localization IoU (`precision/recall/f1`), with strict semantics unchanged.
- Benchmark upload should pass `auto_project_name_on_scope_mismatch=True` into `run_labelstudio_import(...)` so auto-named benchmark projects recover by suffixing project titles instead of failing on prior freeform/canonical scope collisions.
- Typer command functions that are called directly from Python (interactive helpers/tests) must keep runtime defaults as plain Python values, typically via `Annotated[..., typer.Option(...)] = <default>`; avoid relying on `param: T = typer.Option(...)` defaults in those call paths.
- If a command still uses `param: T = typer.Option(...)` defaults (legacy signatures), unwrap `OptionInfo` values to plain defaults at function entry before validation/normalization.
- Interactive `generate_dashboard` asks whether to open the dashboard in a browser, then runs `stats_dashboard(output_root=<settings.output_dir>, out_dir=<output_root_parent>/.history/dashboard)` and returns to the main menu.
- EPUB debug tooling lives under `cookimport epub ...` (sub-CLI module `cookimport/epubdebug`), and block/candidate debug commands must reuse production EPUB importer internals (`_extract_docpack`, `_detect_candidates`) to preserve stage/debug parity.

When debugging "file missing from menu" reports, check whether the file is nested inside `data/input`.


## Dependency Resolution Rule

- When checking package availability with `pip index versions`, remember it is stable-only by default; for pre-release-only packages use `--pre` before concluding a dependency is unavailable.
- For optional debug/tooling dependencies that are pre-release-only (for example `epub-utils==0.1.0a1`), keep them in optional extras and maintain a no-extra fallback path.
