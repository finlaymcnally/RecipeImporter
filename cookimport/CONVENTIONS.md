# cookimport Conventions

Durable CLI/runtime conventions for top-level orchestration code (primarily `cookimport/cli.py` and entrypoints).

## CLI Discovery Rule

Interactive file discovery and direct staging intentionally differ:

- Interactive menu discovery (`cookimport` with no subcommand) scans only top-level files in `data/input`.
- Direct staging (`cookimport stage <folder>`) scans recursively under the folder.
- Interactive `labelstudio` import always recreates the resolved Label Studio project (`overwrite=True`, `resume=False`) and does not prompt for resume mode.
- Interactive `labelstudio` import is freeform-only and no longer asks for upload confirmation; once freeform/prelabel options are chosen, it proceeds directly to upload (after credential resolution).
- Interactive freeform `labelstudio` import prompts for AI prelabel mode (`off`, `strict`, `allow-partial`, plus advanced predictions modes) during the same prompt flow, then prompts for labeling style (`actual freeform` span mode vs `block-based` mode); do not require leaving interactive mode for first-pass AI annotations.
- Interactive freeform `labelstudio` prelabel flow includes explicit Codex model selection followed by model-supported thinking effort selection (`none|low|medium|high|xhigh` and filtered by selected model metadata); `minimal` must stay hidden for this workflow due tool failures. Token-usage tracking is always enabled and should not be a prompt.
- Interactive and non-interactive `labelstudio` import must use the same status/progress callback wiring so long-running phases (especially AI prelabeling) show a live spinner/status update path.
- `labelstudio` resume semantics apply only when the target Label Studio project already exists; if a run creates a new project, do not reuse local manifest task IDs from older runs.
- Spinner/progress text for known-size worklists should include `<noun> X/Y` counters (for example `task`, `item`, `config`, `phase`) rather than phase-only text so operators can track throughput.
- Callback-driven CLI spinners (`labelstudio` import, benchmark import, bench speed-run/quality-run) should append elapsed seconds after prolonged unchanged phases (default threshold: 10s) so users can see that work is still running when a phase message is stale. When status text includes `<noun> X/Y`, the same spinner path should estimate ETA as average seconds-per-unit times remaining units. When worker telemetry is emitted, render per-worker activity lines under the main spinner status.
- Progress callback plumbing is telemetry-only: exceptions raised by UI/status callbacks must be logged and ignored (never allowed to abort extraction, task generation, or upload flows).
- Interactive `labelstudio` export resolves credentials first, then lists project titles from Label Studio for selection, with manual entry fallback when discovery is unavailable. Export is freeform-only and should reject older `pipeline` / `canonical-blocks` projects explicitly.
- Golden workflow roots are split by purpose:
  - Label Studio task-generation/import artifacts: `data/golden/sent-to-labelstudio/<timestamp>/...`
  - Label Studio export artifacts: `data/golden/pulled-from-labelstudio/<source_slug_or_project_slug>/exports/...`
  - Benchmark/eval artifacts: `data/golden/benchmark-vs-golden/<timestamp>/...`
- Label Studio export (interactive and non-interactive) writes to a stable source-aware root by default: `data/golden/pulled-from-labelstudio/<source_slug_or_project_slug>/exports/...`; when a single source file is detectable, its filename stem defines the slug so repeated pulls overwrite the same folder even if project titles are suffixed (for example `-2`). It still uses prior manifests for project resolution and non-freeform scope rejection. `--run-dir` still forces export into a specific run.
- Interactive main menu is persistent: successful `import`, `labelstudio`, `labelstudio_export`, and `labelstudio_benchmark` actions all return to the main menu. The session exits only when the user selects `Exit`.
- Interactive select menus should be wired through `_menu_select` so numbering, shortcuts, and Esc-go-back behavior remain consistent.
- Interactive typed prompts in CLI flows should use `_prompt_text`, `_prompt_confirm`, or `_prompt_password` so `Esc` consistently maps to one-level back/cancel behavior.
- Questionary `text/password/confirm` prompts expose merged key bindings (`_MergedKeyBindings`) at runtime; `Esc` overrides must be attached via `merge_key_bindings(...)` (not `.add(...)` on `application.key_bindings`).
- Freeform interactive segment sizing (`segment_blocks`, `segment_overlap`, `segment_focus_blocks`, `target_task_count`) should route through `_prompt_freeform_segment_settings(...)` so `Esc` walks back one field instead of dropping to main menu.
- Interactive Import and interactive benchmark modes go through one shared two-profile chooser (`CodexFarm automatic top-tier` / `Vanilla automatic top-tier`) before execution.
- Interactive benchmark (`labelstudio_benchmark`) has three offline modes only:
  - `single_book`
  - `selected_matched_books`
  - `all_matched_books`
- Interactive benchmark modes always run local canonical-text evaluation (`no_upload=True`), without Label Studio credential resolution/upload.
- All-method benchmarking remains available only as a non-interactive CLI path; interactive menu flow should not route to `_interactive_all_method_benchmark`.
- Benchmark eval report contracts should use explicit metrics: strict accuracy (`strict_accuracy`, plus `overall_block_accuracy`/`overall_line_accuracy`) and `macro_f1_excluding_other`. Analytics/history consumers may still derive older strict/practical aliases when reading archived artifacts.
- Benchmark upload should pass `auto_project_name_on_scope_mismatch=True` into `run_labelstudio_import(...)` so auto-named benchmark projects recover by suffixing project titles instead of failing on prior freeform/canonical scope collisions.
- Typer command functions that are called directly from Python (interactive helpers/tests) must keep runtime defaults as plain Python values, typically via `Annotated[..., typer.Option(...)] = <default>`; avoid relying on `param: T = typer.Option(...)` defaults in those call paths.
- If a command still uses `param: T = typer.Option(...)` defaults (older signature style), unwrap `OptionInfo` values to plain defaults at function entry before validation/normalization.
- Interactive `generate_dashboard` asks whether to open the dashboard in a browser, then runs `stats_dashboard(output_root=<settings.output_dir>, out_dir=history_root_for_output(<settings.output_dir>)/dashboard)` and returns to the main menu.
- EPUB debug tooling lives under `cookimport epub ...` (sub-CLI module `cookimport/epubdebug`), and block/candidate debug commands must reuse production EPUB importer internals (`_extract_docpack`, `_detect_candidates`) to preserve stage/debug parity.

When debugging "file missing from menu" reports, check whether the file is nested inside `data/input`.


## Dependency Resolution Rule

- When checking package availability with `pip index versions`, remember it is stable-only by default; for pre-release-only packages use `--pre` before concluding a dependency is unavailable.
- For optional debug/tooling dependencies that are pre-release-only (for example `epub-utils==0.1.0a1`), keep them in optional extras and maintain a no-extra fallback path.
