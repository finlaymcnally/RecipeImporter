---
summary: "CLI architecture/build/fix-attempt log used to avoid repeating failed paths."
read_when:
  - When troubleshooting CLI behavior and you think "we are going in circles on this"
  - When doing multi-turn fixes and you need prior architecture/build/fix attempts
---
# CLI Build and Fix Log

This file is the anti-loop log for CLI work. Read it before retrying approaches that may already have failed.

### 2026-02-28_09.26.29 codex-farm model discovery via CLI json contract

Source task file:
- `docs/tasks/2026-02-28_09.26.29-codex-farm-connection-contract-alignment.md`

Preserved finding:
- Shared run-settings Codex model picker was still sourcing models from local cache paths, which could drift from Codex Farm caller expectations.

Current rule:
- `choose_run_settings(...)` codex model picker now discovers models via `codex-farm models list --json` (best-effort; fallback options remain available).
- Model picker still preserves `keep current`, optional `pipeline default`, and `custom model id...` escape hatch.
- Pipeline-id and run-error contract enforcement is handled in LLM runner/orchestrator modules, not CLI menu code.

### 2026-02-28_04.14.07 codex-farm model picker in shared run-settings flow

Source task file:
- `docs/tasks/2026-02-28_04.14.07-codex-farm-model-picker-in-run-settings.md`

Preserved finding:
- Free-text codex model entry in interactive run setup was error-prone and inconsistent with existing model-picker UX.

Current rule:
- `choose_run_settings(...)` uses a picker for codex model override in both import and benchmark flows.
- Picker offers:
  - keep current value,
  - pipeline default (when an override exists),
  - discovered models from `codex-farm models list --json` (best-effort with fallback options),
  - custom model id fallback.
- Reasoning-effort prompt behavior remains unchanged.
- Cancel/back from model or reasoning prompts returns `None` and cleanly cancels run setup.

Task-spec evidence merged:
- Targeted verification subset:
  - `. .venv/bin/activate && COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1 pytest -o addopts='' tests/cli/test_c3imp_interactive_menu.py -vv -k "collects_codex_model_and_reasoning or model_cancel_returns_none or reasoning_back_returns_none or custom_codex_model_and_reasoning" --tb=short --show-capture=all --assert=rewrite`
- Broader chooser regression:
  - `. .venv/bin/activate && pytest tests/cli/test_c3imp_interactive_menu.py -q`

### 2026-02-28_04.05.00 codex-farm always-on interactive defaults and ungated normalizers

Source task file:
- `docs/tasks/2026-02-28_04.05.00-codex-farm-always-on-in-interactive-and-normalizers.md`

Preserved finding:
- Users wanted Codex Farm on now, visible everywhere in interactive setup, without env-gate friction.

Current rule:
- Recipe Codex Farm is no longer gated by `COOKIMPORT_ALLOW_CODEX_FARM` in run-settings/CLI/labelstudio normalizers.
- Interactive chooser prompt `Use Codex Farm recipe pipeline for this run?` defaults to `Yes`.
- Interactive all-method prompt `Include Codex Farm permutations?` defaults to `Yes`.
- Codex model and reasoning override prompts still appear when codex is enabled for the run.
- Supersedes older env-gate notes later in this file (`03:37-03:57` merged-understanding batch).

### 2026-02-28_03.59.43 benchmark split-conversion spinner harmonization

Source task file:
- `docs/tasks/2026-02-28_03.59.43-benchmark-split-spinner-harmonization.md`

Preserved finding:
- Benchmark import split conversion emitted phase-only start text plus `Completed split job X/Y`; spinner ETA/counter behavior was less consistent than other benchmark spinners.
- Split worker subprocesses also received report-only run-config keys, causing repeated `Ignoring unknown ... keys` warnings that interrupted spinner output.

Current rule:
- Split conversion progress callbacks should emit `Running split conversion... task X/Y` from `0/Y` onward, appending `(workers=N)` when parallel workers are active.
- Split worker subprocesses should receive RunSettings-only config payloads; report metadata-only keys stay in the persisted run config for output artifacts.

Task-spec evidence merged:
- Verification command: `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_ingest_parallel.py -q -k "split_workers_emit_worker_activity"`.
- Verification command: `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_ingest_parallel.py -q -k "run_labelstudio_import_emits_post_merge_progress or split_workers_emit_worker_activity"`.
- Implementation touchpoints:
  - `cookimport/labelstudio/ingest.py` split progress callback path
  - worker payload sanitization (`worker_run_config`) for split subprocesses
  - `tests/labelstudio/test_labelstudio_ingest_parallel.py` assertions for `task 0/3` and `task 3/3`

### 2026-02-28_03.51.54 per-run codex-farm prompt in interactive run-settings chooser

Source task file:
- `docs/tasks/2026-02-28_03.52.06-interactive-codex-farm-per-run-prompt.md`

Preserved finding:
- Operators wanted an explicit per-run codex-farm decision during interactive setup, not only hidden in run-settings editor/all-method prompts.

Current rule:
- `choose_run_settings(...)` now asks `Use Codex Farm recipe pipeline for this run?` after selecting profile/edit result for both import and benchmark interactive flows.
- Default answer is now `Yes` so Codex Farm is on by default in interactive run setup.
- When codex is enabled for the run, chooser immediately asks model override text + reasoning effort override so operators do not need to open the full settings editor.
- Policy lock removed: recipe Codex Farm options are no longer gated by `COOKIMPORT_ALLOW_CODEX_FARM`.

Task-spec evidence merged:
- Cancel (`None`) from codex confirm prompt cleanly cancels run setup.
- Verification commands:
  - `. .venv/bin/activate && pytest tests/cli/test_c3imp_interactive_menu.py -q -k "choose_run_settings"`
  - `. .venv/bin/activate && pytest tests/llm/test_run_settings.py -q -k "run_settings_ui_specs"`

### 2026-02-28_03.39.40 single-profile-all-matched interactive benchmark mode

Source task file:
- `docs/tasks/2026-02-28_03.32.49-single-profile-all-matched-interactive-benchmark.md`

Preserved finding:
- Operators needed a middle path between one-off single offline runs and full all-method permutations: run one selected profile across every matched freeform gold/source pair.

Current rule:
- Interactive benchmark mode picker now includes `Generate predictions + evaluate for all matched golden sets (single config each, offline)`.
- This mode reuses the standard benchmark run-settings chooser and runs `labelstudio-benchmark` once per matched target with canonical-text eval and no upload.
- No all-method variant expansion is applied; run count is one config per matched target.
- Per-source eval artifacts are written under `<benchmark_timestamp>/single-profile-benchmark/<index_source_slug>/`.

Update (2026-02-28_04.04):
- Run-settings editor now always shows `llm_recipe_pipeline=off|codex-farm-3pass-v1` (no env gate).

Task-spec evidence merged:
- Verification command: `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py -q`.
- Primary implementation path: `cookimport/cli.py:_interactive_single_profile_all_matched_benchmark(...)`.

### 2026-02-28_02.08.45 all-method process-worker preflight

Source task file:
- `docs/tasks/2026-02-28_02.08.45-all-method-process-worker-preflight.md`

Preserved finding:
- Restricted runtimes frequently failed process-pool startup and logged "falling back to serial mode," which looked like runtime breakage even when runs were healthy.

Current rule:
- All-method startup now probes process-worker availability before attempting parallel config scheduling.
- When workers are unavailable, runner chooses single-config execution directly instead of emitting old fallback wording.
- Defensive executor error handling remains for rare mid-run failures.

Task-spec evidence merged:
- Verification command: `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py -q`.
- Primary implementation path: `cookimport/cli.py` all-method scheduler startup helpers and status wording.

### 2026-02-28_03.04.14 dual saved run-settings profiles

Preserved finding:
- One saved preferred profile was not enough for operator workflow; they need both a personal baseline profile and a separate quality-suite winner profile available in interactive runs.

Current rule:
- `choose_run_settings(...)` now exposes both `Run with preferred format (...)` and `Run with quality-suite winner (...)`.
- Quality-suite winner settings are loaded from `<output_dir_parent>/.history/qualitysuite_winner_run_settings.json` when present.
- `bench quality-leaderboard` now saves winner settings into that file automatically.
- Winner extraction prefers `run_manifest.json -> run_config.prediction_run_config` when present, so the saved winner matches the scored variant dimensions.

### 2026-02-28_02.13.34 preferred-format run-settings option

Preserved finding:
- The interactive run-settings chooser needed one stable “go-to” profile for repeated import + benchmark runs without editing toggles each time.

Current rule:
- `choose_run_settings(...)` now includes `Run with preferred format (...)` for both import and benchmark interactive flows.
- Preferred settings are loaded from `<output_dir_parent>/.history/preferred_run_settings.json` when present.
- If no preferred file exists yet, the chooser falls back to built-in preferred defaults:
  - `epub_extractor=beautifulsoup`
  - `instruction_step_segmentation_policy=off`
- Interactive all-method benchmark now uses the same run-settings chooser (it no longer hard-wires global defaults only).

## Merged Discovery Provenance (Archived CLI understandings)

Some earlier CLI-specific understanding notes were merged into this log in timestamp order so CLI behavior + anti-loop notes live in one place.

Note: `docs/understandings/` still exists for cross-cutting discoveries; prefer adding new general-purpose findings there (and link back here only when it prevents CLI fix loops).

### 2026-02-22_22.30.58 interactive Esc back migration

Merged source file:
- `2026-02-22_22.30.58-interactive-esc-back-contract.md` (in `docs/understandings`)

Preserved finding:
- Back navigation was previously wired only on `_menu_select()` and used `Backspace`.
- Numeric/text prompts (`questionary.text` etc.) had no equivalent go-back binding.

Current rule:
- Interactive prompts now use `Esc` for one-level back/cancel.
- Menu prompts use `_menu_select()`; typed prompts use `_prompt_text/_prompt_confirm/_prompt_password`.
- Keybinding injection for typed prompts uses `merge_key_bindings(...)` because PromptSession prompts expose `_MergedKeyBindings` without `.add(...)`.

### 2026-02-22_23.09.47 freeform numeric prompt step-back

Merged source file:
- `2026-02-22_23.09.47-freeform-interactive-esc-step-back.md` (in `docs/understandings`)

Preserved finding:
- Inline freeform numeric prompts treated Esc as flow-level cancel (`continue`), which bounced users to main menu.

Current rule:
- Use `_prompt_freeform_segment_settings(...)` for freeform segment/focus/target prompts so Esc walks back one field.

### 2026-02-15_21.04.54 cli interactive flow map

Preserved points:
- `cookimport` enters interactive mode only when no subcommand is invoked.
- `import` / `C3import` wrappers are batch-first shortcuts (no-arg path runs `stage(data/input)` immediately).
- Interactive import `limit` comes from `C3IMP_LIMIT` (for example via `C3imp <N>`), not a separate interactive prompt.
- Non-interactive Label Studio write paths remain explicitly gated by `--allow-labelstudio-write`.
- Interactive Label Studio import and interactive benchmark upload do not ask extra upload-confirmation questions; once flow/mode is chosen, upload proceeds after credential resolution.

### 2026-02-15_22.44.43 interactive menu loop after jobs

Merged source file:
- `2026-02-15_22.44.43-interactive-menu-loop-after-jobs.md` (formerly in `docs/understandings`)

Preserved finding:
- Successful interactive `import`, `labelstudio`, `labelstudio_export`, and `labelstudio_benchmark` branches previously used `break`, which exited the whole session after one job.

Current rule:
- These branches must `continue` back to main menu.
- Interactive mode exits only when main-menu action is `exit` (or `None`).

### 2026-02-15_23.03.59 interactive menu numbering source

Merged source file:
- `2026-02-15_23.03.59-interactive-menu-numbering-source.md` (formerly in `docs/understandings`)

Preserved finding:
- Interactive select prompts should route through `_menu_select()` in `cookimport/cli.py`.

Why this matters:
- `_menu_select()` is the one control point for numbering, shortcut handling, and Backspace navigation.
- Bypassing `_menu_select()` causes menu UX drift and inconsistent keyboard behavior.

### 2026-02-15_23.11.30 interactive generate-dashboard feedback

Merged source file:
- `2026-02-15_23.11.30-interactive-generate-dashboard-feedback.md` (formerly in `docs/understandings`)

Preserved finding:
- `generate_dashboard` already worked, but immediate menu redraw looked like a no-op.

Current rule:
- Interactive dashboard generation prompts whether to open the produced dashboard.
- `open_browser` response is forwarded into `stats_dashboard(...)` call.

### 2026-02-16_12.09.36 run-settings config propagation

Merged source file:
- `2026-02-16_12.09.36-run-settings-config-propagation.md` (formerly in `docs/understandings`)

Preserved map:
- Canonical run-setting definition + summary/hash source is `cookimport/config/run_settings.py`.
- Interactive chooser/editor path is `cookimport/cli_ui/run_settings_flow.py` + `cookimport/cli_ui/toggle_editor.py`.
- Last-run snapshots persist via `cookimport/config/last_run_store.py` under `<output_dir>/.history/last_run_settings_{import|benchmark}.json`.
- Stage/report writes in `cookimport/cli.py` + `cookimport/cli_worker.py` must carry `runConfig`, `runConfigHash`, `runConfigSummary`.
- Benchmark prediction manifests written via `cookimport/labelstudio/ingest.py` must carry `run_config`, `run_config_hash`, `run_config_summary`.
- CSV history (`cookimport/analytics/perf_report.py`) and dashboard collector/renderer must preserve and display run-config hash/summary/json consistently.

Anti-loop note:
- If a new run-setting is visible in interactive stage but missing in benchmark/dashboard history, the feature wiring is incomplete.

### 2026-02-16_14.30.00 epub debug CLI integration contract

Merged source file:
- `2026-02-16_14.30.00-epub-debug-cli-integration-contract.md` (formerly in `docs/understandings`)

Durable rules:
- Keep `cookimport epub blocks|candidates` behavior coupled to `EpubImporter` internals to avoid stage/debug drift.
- Preserve unstructured-option env parity with stage for debug extraction.
- Keep `--out` safety behavior (`--force` required for non-empty destinations).
- Keep `epub-utils` optional and pre-release aware (`0.1.0a1` currently; install via `.[epubdebug]` or `pip install --pre epub-utils`).

### Undated durable rule: pipeline option edit map

Merged source file:
- `IMPORTANT-INSTRUCTION-pipeline-option-edit-map.md` (formerly in `docs/understandings`)

Required checklist when adding a new processing-pipeline option:

1. Define/selectable option:
- `cookimport/config/run_settings.py` (`RunSettings`, UI metadata, summary ordering, canonical builder).
- `cookimport/cli_ui/run_settings_flow.py` + `cookimport/cli_ui/toggle_editor.py` for interactive selection.
- Update `compute_effective_workers(...)` if the option changes split capability or real parallelism.

2. Pass option through run-producing CLI paths:
- `cookimport/cli.py` validation/normalization, stage wiring, benchmark wiring, and split planning where relevant.
- `cookimport/labelstudio/ingest.py` prediction generation path (`generate_pred_run_artifacts(...)`) and split planner parity.

3. Persist run-config context for analytics:
- `cookimport/core/models.py` (`ConversionReport` run-config fields).
- `cookimport/cli_worker.py` and `cookimport/labelstudio/ingest.py` report/manifest writes.
- `cookimport/analytics/perf_report.py` CSV columns and append paths.
- `cookimport/analytics/dashboard_collect.py` + `cookimport/analytics/dashboard_render.py` display logic.

4. Apply option in both required execution lanes:
- Import path (`cookimport stage ...` via `stage(...)` and worker flow).
- Prediction/eval generation path (`cookimport labelstudio-benchmark ...` via prediction artifact generation and benchmark CSV append path).
- `labelstudio-eval` eval-only mode scores existing prediction runs and does not rerun the pipeline.

## Merged Task Specs (`docs/tasks`)

Task-spec files were previously kept under `docs/tasks/` and are now merged here so interactive CLI behavior changes, constraints, and verification evidence stay in one place.

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

### 2026-02-16_14.31.00 - EPUB debug CLI

Source task file:
- `docs/tasks/2026-02-16_14.31.00 - epub-debug-cli.md`

Problem captured:
- EPUB debugging required ad hoc ZIP/manual inspection with no first-class CLI for spine inspection, extraction diagnostics, or candidate segmentation checks.

Behavior contract preserved:
- Add `cookimport epub` subcommands: `inspect`, `dump`, `unpack`, `blocks`, `candidates`, `validate`.
- Keep `blocks` and `candidates` behavior tied to production importer extraction/segmentation logic to avoid debug-vs-stage drift.
- Keep deterministic artifact outputs for inspect/blocks/candidates/validate workflows.

Verification and evidence preserved:
- Recorded test command:
  - `source .venv/bin/activate && pytest -q tests/test_epub_debug_cli.py tests/test_epub_debug_extract_cli.py tests/test_epub_importer.py`
- Recorded result: `19 passed`.
- Recorded artifact outputs:
  - `inspect_report.json`
  - `blocks.jsonl`, `blocks_preview.md`, `blocks_stats.json`
  - `candidates.json`, `candidates_preview.md`

Constraints and anti-loop notes:
- Direct `_extract_docpack(...)` usage requires importer `_overrides` to be initialized.
- `epub-utils` remains optional and pre-release aware; keep ZIP/OPF fallback path.
- EPUBCheck strictness remains opt-in (`--strict`).

Rollback path preserved:
- Remove `cookimport/epubdebug/` module + root CLI wiring and associated tests/docs if debug CLI must be fully reverted.

## 2026-02-23 docs/tasks archival merge batch (CLI)

### 2026-02-16 run-settings selector and persistence (`docs/tasks/01-PerRunSettingsSelector.md`)

Problem captured:
- Global defaults alone were too coarse for iteration and did not preserve per-run config provenance across import and benchmark loops.

Major decisions preserved:
- One canonical typed settings model (`RunSettings`) drives UI rows, run-time config, and analytics metadata.
- Last-run settings are persisted separately for `import` and `benchmark` modes and never overwrite global defaults.
- CSV keeps compact run config identifiers (`run_config_hash`, `run_config_summary`) while full JSON lives in reports/manifests.
- Interactive benchmark eval-only path skips run-settings persistence by design.

Important discoveries:
- Run-config propagation requires coordinated updates across report writers, CSV appenders, collector schema, and dashboard renderer; partial wiring creates silent analytics drift.
- Backward-compatible loading for last-run files must accept both wrapped and legacy-flat payload shapes.

Anti-loop note:
- If run settings show in CLI but not in benchmark/dashboard artifacts, fix propagation end-to-end before changing UI again.

### 2026-02-22_13.02.21 second-pass spinner counters (`docs/tasks/2026-02-22_13.02.21-spinner-progress-counters-second-pass.md`)

Problem captured:
- Status text looked stalled in bench and split-merge flows because many loops had known totals but emitted no counters.

Major decisions preserved:
- Generate counters in runtime loops that know totals; do not synthesize them in UI/render-only layers.
- Share formatter helpers for `task/item/config/phase` text to prevent cross-command drift.
- Keep merge-phase totals deterministic when optional chunk-writing is enabled or disabled.

Evidence preserved:
- Targeted tests added/updated for formatter output, bench progress forwarding, and split-merge status sequencing.

### 2026-02-22_19.12.59 run-settings editor scroll repair (`docs/tasks/2026-02-22_19.12.59 - benchmark-run-settings-editor-scroll.md`)

Problem captured:
- Long run-settings lists in full-screen editor stopped scrolling because the selected row had no exposed cursor mapping.

Decision preserved:
- Keep current text-rendering model; add prompt_toolkit cursor-position callback mapped to selected row and focus body window for native viewport tracking.

Rollback path preserved:
- Revert `cookimport/cli_ui/toggle_editor.py` and related toggle-editor tests if viewport tracking regresses.

## 2026-02-23 archival merge batch from `docs/understandings` (CLI)

### 2026-02-22_19.12.59 run-settings editor scroll contract

Merged source:
- `docs/understandings/2026-02-22_19.12.59-run-settings-editor-scroll-contract.md`

Preserved detail:
- Scroll behavior in long settings lists depends on selected-row cursor mapping (`get_cursor_position`) in the formatted-text body control plus keeping focus on the body window.

### 2026-02-22_22.30.58 interactive Esc back contract

Merged source:
- `docs/understandings/2026-02-22_22.30.58-interactive-esc-back-contract.md`

Preserved detail:
- Typed prompt Esc binding must be injected with `merge_key_bindings(...)` (PromptSession merged key bindings), not `.add(...)` on `application.key_bindings`.

### 2026-02-22_23.09.47 freeform Esc step-back contract

Merged source:
- `docs/understandings/2026-02-22_23.09.47-freeform-interactive-esc-step-back.md`

Preserved detail:
- Freeform numeric prompt flow should route through `_prompt_freeform_segment_settings(...)` so Esc is one-field-back behavior, not flow abort.

### 2026-02-22_23.13.34 spinner X/Y ETA flow

Merged source:
- `docs/understandings/2026-02-22_23.13.34-spinner-xy-eta-flow.md`

Preserved detail:
- Shared spinner ETA logic belongs in `_run_with_progress_status(...)` and should compute remaining time from right-most `X/Y` counter increments, while preserving stale-phase elapsed-seconds liveness text.

### 2026-02-23_00.17.44 spinner worker-activity telemetry contract

Merged source:
- `docs/understandings/2026-02-23_00.17.44-spinner-worker-activity-telemetry.md`

Preserved detail:
- Worker activity stays a serialized side-channel parsed by shared spinner rendering so per-worker lines can be shown under the main phase/task status without breaking counter parsing.

## 2026-02-22_23 to 2026-02-23_00 docs/tasks merge batch (CLI spinner)

### 2026-02-22_23.13.39 - spinner X/Y ETA (`docs/tasks/2026-02-22_23.13.39 - spinner-xy-eta.md`)

Problem captured:
- Callback-driven spinner status showed phase text but no remaining-time estimate for known-size loops.

Decision preserved:
- Keep ETA in shared spinner wrapper (`_run_with_progress_status(...)`), derived from observed throughput on right-most `X/Y` counter.
- Preserve stale-phase elapsed-seconds fallback for phases with no counters.

Evidence preserved from task:
- Added ETA formatting/runtime assertions in `tests/labelstudio/test_labelstudio_benchmark_helpers.py`.
- Recorded verification runs:
  - `. .venv/bin/activate && pip install -e .[dev] && pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py` -> `45 passed, 2 warnings in 3.34s`.
  - `. .venv/bin/activate && pytest tests/bench/test_progress_messages.py` -> `2 passed in 0.01s`.

Anti-loop notes:
- Do not move ETA math into ingest/importer code; keep one renderer implementation.
- Do not derive ETA before first observed progress increment.

### 2026-02-23_00.17.44 - spinner worker summary list (`docs/tasks/2026-02-23_00.17.44 - spinner-worker-summary-list.md`)

Problem captured:
- Aggregate spinner line hid which worker was doing what during parallel phases.

Decision preserved:
- Keep worker activity as a serialized side-channel (`format_worker_activity`, `format_worker_activity_reset`, `parse_worker_activity`) so per-worker lines render below the primary status line.
- Keep primary line untouched so task-counter and ETA parsing remain stable.

Evidence preserved from task:
- Runtime changes were in `cookimport/cli.py` + `cookimport/core/progress_messages.py` with Label Studio emitters in `cookimport/labelstudio/ingest.py`.
- Recorded verification run:
  - `. .venv/bin/activate && PYTHONDONTWRITEBYTECODE=1 COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1 pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py tests/labelstudio/test_labelstudio_ingest_parallel.py` -> `60 passed, 2 warnings in 3.46s`.

Anti-loop notes:
- Do not replace the main status line with worker lines.
- Always emit reset telemetry after worker phases so stale worker rows do not linger.

### 2026-02-23_12.35.19 stage `OptionInfo` default leak on direct Python call paths

Merged source:
- `docs/understandings/2026-02-23_12.35.19-stage-optioninfo-default-leak.md`

Problem captured:
- `cookimport.cli.stage(...)` serves both Typer dispatch and direct Python callers (`_interactive_mode`, `entrypoint.main`, tests).
- When direct callers omit kwargs, Typer-declared defaults can remain as `OptionInfo` objects and break normalizers expecting plain strings/ints (for example `.strip()` calls).

Decision preserved:
- `stage(...)` must explicitly unwrap `OptionInfo` values to plain defaults before normalization/run-settings assembly.
- Interactive import should forward the full selected run-settings payload into `stage(...)`, including knowledge-pipeline knobs.
- `import`/`C3import` entrypoint wrappers should pass the expanded stage argument surface so saved settings can influence direct-entrypoint runs.

Anti-loop note:
- If a stage normalizer crashes with type/attribute errors from `OptionInfo`, audit direct caller argument forwarding and default unwrapping before touching parsing/staging logic.

## 2026-02-27_19.51.12 CLI README command-surface reconciliation

Problem captured:
- `docs/02-cli/02-cli_README.md` had drift against current command signatures in `cookimport/cli.py` + `cookimport/tagging/cli.py`, especially around benchmark speed tooling and newer option flags.

Code-verified findings:
- Missing command-reference coverage: `bench speed-discover`, `bench speed-run`, `bench speed-compare`, `bench eval-stage`.
- Missing option coverage on existing commands: `labelstudio-import` (`--codex-model`, reasoning-effort aliases, codex-farm flags), `labelstudio-benchmark` (`--execution-mode`, `--predictions-{in,out}`), and `bench run` write-toggle overrides.
- Tagging command option drift: `tag-recipes suggest` and `tag-recipes apply` codex-farm options were not listed.
- Command-surface list omission: `cookimport debug-epub-extract` absent from top-level command bullets.
- Stale option in docs: `labelstudio-benchmark --chunk-level` no longer exists.
- Environment variable list missed active CLI envs (`C3IMP_EPUBCHECK_JAR`, `COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS`, `COOKIMPORT_ALLOW_CODEX_FARM`, `COOKIMPORT_ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS`, benchmark eval profile env vars, and Codex model/cmd env vars).

Durable rule:
- For CLI doc updates, validate command/option coverage against Typer registration (`app` + mounted sub-typers) before finalizing README edits; avoid relying on historical option lists.

### 2026-02-27_19.45.20 CLI docs stale-feature prune

Problem captured:
- CLI docs retained removed EPUB race content and had stale benchmark command summaries.

Durable decisions:
- Keep retired EPUB race material removed from active CLI docs.
- Keep bench subcommand list and option coverage refreshed from `cookimport/cli.py` signatures.

Anti-loop note:
- If docs and CLI behavior diverge, audit option-level signature drift first.

### 2026-02-27_19.51.12 provenance note

Source understanding merged:
- `docs/understandings/2026-02-27_19.51.12-cli-readme-command-surface-reconciliation.md`

Current status:
- Its findings are retained in this log and reflected in `02-cli_README.md`; source file is retired from `docs/understandings`.

## 2026-02-28 migrated understanding ledger

Chronological migration from `docs/understandings`; source files were removed after this merge.

### 2026-02-27_20.38.15 load settings sequence matcher coercion

Source: `docs/understandings/2026-02-27_20.38.15-load-settings-sequence-matcher-coercion.md`
Summary: "Legacy cookimport.json matcher values are now rejected at load time; benchmark sequence matcher must be dmp."

Details preserved:

Read when:
- When interactive startup fails due invalid `cookimport.json benchmark_sequence_matcher`
- When migrating old `cookimport.json` files after matcher-mode contract changes

# Load Settings Sequence Matcher Validation

Discovery:

- Runtime defaults are `dmp`, and `_load_settings()` now validates merged `cookimport.json` values before returning settings.
- Old configs with archived values (for example `fallback`) fail fast with a clear `benchmark_sequence_matcher` error instead of being silently coerced.

Implication:

- Interactive/import/speed entrypoints now share one strict matcher contract: `dmp` only.
- Any stale `cookimport.json` matcher value must be updated explicitly by the user to continue.

### 2026-02-28_00.50.18 bench run/sweep removal surface map

Source: `docs/understandings/2026-02-28_00.50.18-bench-run-sweep-removal-surface-map.md`
Summary: Mapped active surfaces after removing deprecated bench validate/run/sweep/knobs commands.

Details preserved:

Deprecated bench-suite commands are now removed from `cookimport/cli.py` (`validate`, `run`, `sweep`, `knobs`) and old suite modules were deleted.

Active bench command surface is now:
- `bench speed-discover`
- `bench speed-run`
- `bench speed-compare`
- `bench quality-discover`
- `bench quality-run`
- `bench quality-compare`
- `bench eval-stage`

Docs that needed synchronized updates were:
- `docs/02-cli/02-cli_README.md`
- `docs/07-bench/07-bench_README.md`
- `docs/07-bench/runbook.md`
- `cookimport/CONVENTIONS.md`
- `cookimport/bench/README.md`
- `cookimport/bench/CONVENTIONS.md`
- analytics/architecture context docs that listed benchmark CSV appenders or bench command surfaces.

### 2026-02-28_01.00.09 all-method 79 run count breakdown

Source: `docs/understandings/2026-02-28_01.00.09-all-method-79-run-count-breakdown.md`
Summary: Why interactive all-method reports 79 configs for current 7 matched targets.

Details preserved:

Observed interactive output:
- `Matched golden sets: 7`
- `All method benchmark will run 79 configurations across 7 matched golden sets`

Current count logic comes from `_build_all_method_variants(...)` in `cookimport/cli.py`:
- Non-EPUB, non-webschema sources: exactly 1 variant.
- EPUB sources:
  - Extractors default to `unstructured` + `beautifulsoup`.
  - `unstructured` expands to `2 parser versions * 2 skip_headers choices * 3 preprocess modes = 12`.
  - `beautifulsoup` contributes 1.
  - Total per EPUB source: 13.

Current matched sources in this repo:
- 6 EPUB targets (`6 * 13 = 78`)
- 1 DOCX target (`1 * 1 = 1`)
- Total: `79`

Important non-expanding knobs:
- `section_detector_backend` and `multi_recipe_splitter` are recorded in dimensions when non-legacy, but they do not auto-expand the all-method matrix.
- `instruction_step_segmentation_policy`, `instruction_step_segmenter`, `ingredient_missing_unit_policy`, and `p6_yield_mode` are forwarded in run settings but not auto-expanded in all-method.

Update (2026-02-28):
- Interactive all-method benchmark now offers a wizard toggle to include deterministic option sweeps (Priority 2–6) and defaults it to enabled.
- With sweeps enabled, the run count will be higher than 79 for the same 7 targets.

Other relevant constraints:
- Codex Farm permutations are currently policy-locked off, so enabling that prompt does not increase count.
- Markdown/markitdown extractor variants are excluded unless both unlock env vars are set.

`Ignoring unknown interactive benchmark global settings keys: ...` is expected in interactive mode because `RunSettings.from_dict(...)` receives the whole `cookimport.json` payload and ignores non-RunSettings keys (scheduler/UI/global keys).

## 2026-02-28 migrated understandings batch (CLI)

### 2026-02-28_02.25.24 interactive run-settings preferred option wiring

Source: `docs/understandings/2026-02-28_02.25.24-interactive-run-settings-preferred-option-wiring.md`

Problem captured:
- Interactive benchmark all-method path had drifted from import/single-offline benchmark by bypassing the shared run-settings chooser and defaulting to global settings.

Durable decisions:
- Keep `cookimport/cli_ui/run_settings_flow.py::choose_run_settings(...)` as the single chooser entrypoint for interactive import and both benchmark modes.
- Keep preferred-profile persistence in `data/.history/preferred_run_settings.json` rather than embedding profile-only keys into `cookimport.json`.
- Preserve mode-specific last-run snapshots in `cookimport/config/last_run_store.py`.

Outcome preserved:
- One preferred profile can now be selected across import, benchmark single-offline, and benchmark all-method without re-editing toggles.
- All interactive benchmark launch paths now share the same chooser/summary semantics and run-settings normalization path.

Anti-loop note:
- If benchmark menu options diverge again between single-offline and all-method, audit `_interactive_mode(...)` benchmark branch wiring first before changing chooser internals.

## 2026-02-28 migrated understanding ledger (03:37-03:57 CLI codex setup batch)

### 2026-02-28_03.37.41 interactive llm recipe pipeline UI gate

Source: `docs/understandings/2026-02-28_03.37.41-interactive-llm-recipe-pipeline-ui-gate.md`

Problem captured:
- Runtime parser accepted codex recipe pipeline under env unlock, but interactive editor hid that option.

Durable decision:
- `run_settings_ui_specs()` now conditionally exposes `codex-farm-3pass-v1` for `llm_recipe_pipeline` only when `COOKIMPORT_ALLOW_CODEX_FARM=1`.

Anti-loop note:
- If interactive users cannot select codex pipeline, check UI enum generation before changing run-settings normalization.

### 2026-02-28_03.44.53 single-profile benchmark codex menu behavior

Source: `docs/understandings/2026-02-28_03.44.53-single-profile-benchmark-codex-menu-behavior.md`

Findings preserved:
- Single-profile all-matched benchmark intentionally does not use all-method codex permutation prompt.
- In single-profile flow, codex on/off comes from run-settings chooser payload and env gate.

### 2026-02-28_03.52.23 shared run-settings chooser as codex prompt hook

Source: `docs/understandings/2026-02-28_03.52.23-shared-run-settings-chooser-is-codex-prompt-hook.md`

Findings preserved:
- `choose_run_settings(...)` is a shared choke point for import and benchmark interactive setup.
- Placing codex prompts there guarantees consistent per-run behavior across interactive entrypoints.

### 2026-02-28_03.57.17 codex toggle needs model/reasoning follow-up

Source: `docs/understandings/2026-02-28_03.57.17-codex-toggle-needs-model-reasoning-followup.md`

Problem captured:
- Per-run codex enable prompt without immediate model/reasoning prompts forced users into extra menu hops.

Durable decision:
- When codex is enabled in chooser flow, immediately prompt for model override and reasoning effort override.
- Preserve env gate behavior: if `COOKIMPORT_ALLOW_CODEX_FARM` is not enabled, recipe pipeline remains `off` and follow-up prompts are skipped.

Anti-loop note:
- Missing model/reasoning prompts after codex enablement is chooser-flow regression, not benchmark-mode-specific behavior.

## 2026-02-28 migrated understanding ledger (04:09-04:15 CLI Codex prompt surfaces)

### 2026-02-28_04.09.18 c3imp codex-farm interactive prompt paths

Source: `docs/understandings/2026-02-28_04.09.18-c3imp-codex-farm-interactive-prompt-paths.md`

Findings preserved:
- Interactive import and interactive benchmark both route through `choose_run_settings(...)`.
- Chooser-level Codex prompt defaults to enabled (`Yes`).
- Model/reasoning prompts are conditional on resolved recipe pipeline value, not simply on benchmark mode.
- `single_offline_all_matched` intentionally inherits chooser result and does not expose all-method Codex permutation prompt.

Durable decision:
- Keep Codex prompt sequencing anchored in shared chooser flow to avoid mode-specific drift.

### 2026-02-28_04.15.12 codex-farm run-settings model picker surface

Source: `docs/understandings/2026-02-28_04.15.12-codex-farm-run-settings-model-picker-surface.md`

Problem captured:
- Free-text-first model overrides created inconsistent UX and avoidable typo/error loops.

Durable decisions:
- Use menu-first model picker with explicit `custom model id...` fallback.
- Preserve cancel contract (`None`/`BACK_ACTION`) for model and reasoning prompts.

Anti-loop note:
- Treat missing model/reasoning follow-up as chooser-state regression first; do not patch benchmark menus before validating `choose_run_settings(...)` output.

## 2026-02-28 migrated understanding ledger (joblib startup warning guard)

### 2026-02-28_14.46.38 joblib SemLock warning is startup noise, not new regression

Source: `docs/understandings/2026-02-28_14.46.38-joblib-semlock-warning-is-startup-noise-not-new-regression.md`

Problem captured:
- Restricted hosts emitted repeated joblib serial-mode warnings during startup/import, creating false regression signals and noisy CLI output.

Durable decisions:
- Add early SemLock probe and set `JOBLIB_MULTIPROCESSING=0` when restriction is detected.
- Keep explicit user-provided `JOBLIB_MULTIPROCESSING` value authoritative.
- Provide guard disable env (`COOKIMPORT_DISABLE_JOBLIB_SEMLOCK_GUARD`) for controlled troubleshooting.

Anti-loop note:
- Differentiate startup warning noise from actual executor-resolution regressions before changing benchmark/stage fallback logic.

## 2026-03-01 docs/tasks merge ledger (CLI)

### 2026-02-28_14.46.37 joblib SemLock warning guard

Source task was merged into this log and removed from `docs/tasks`:
- `2026-02-28_14.46.37-joblib-semlock-warning-guard.md`

Problem captured:
- Import-time joblib SemLock probes emitted repeated serial-mode warnings on restricted hosts, creating noisy startup output across CLI workflows.

Durable decisions:
- Add guarded early SemLock probe before heavy module imports.
- Force `JOBLIB_MULTIPROCESSING=0` only when restriction is detected and no explicit value is set.
- Keep `JOBLIB_MULTIPROCESSING` operator overrides authoritative.
- Provide opt-out env for debugging (`COOKIMPORT_DISABLE_JOBLIB_SEMLOCK_GUARD`).

Evidence preserved:
- `. .venv/bin/activate && pytest tests/core/test_joblib_runtime.py -q`
- `. .venv/bin/activate && python - <<'PY'` smoke import for `cookimport.cli`

Anti-loop note:
- Startup warning suppression is not a throughput fix; confirm executor fallback telemetry before changing stage/bench concurrency paths.

## 2026-03-02 migrated understanding ledger (interactive presets + progress architecture)

Chronological migration from `docs/understandings`; source files are retired after this merge.

### 2026-03-02_00.25.21 interactive quality-first preset shared chooser path

Source: `docs/understandings/2026-03-02_00.25.21-interactive-run-settings-quality-first-preset-path.md`

Findings preserved:
- Interactive import and interactive benchmark both route through `choose_run_settings(...)` in `cookimport/cli_ui/run_settings_flow.py`.
- The lowest-risk implementation path for profile additions is to add profile options in this shared chooser, not in mode-specific menu branches.
- Preferred/quality-style profile wiring should follow existing pattern: patch `global_defaults` and construct `RunSettings` from the patched payload.

Anti-loop note:
- If import and benchmark preset menus drift, audit chooser wiring first before patching individual interactive branches.

### 2026-03-02_01.02.17 codex-farm progress active suffix dedupe

Source: `docs/understandings/2026-03-02_01.02.17-codex-farm-progress-active-suffix-dedup.md`

Problem captured:
- Plain-progress logs were noisy because codex-farm progress messages included volatile `active <filename>` tails, defeating exact-string dedupe.

Durable decision:
- Keep codex-farm steady-state callback messages anchored to stable counters (`task X/Y`, running/error counts).
- Avoid per-file active suffix text in the message key path used by dedupe.

Anti-loop note:
- If progress spam returns, inspect runner-side emitted message text before changing spinner render code.

### 2026-03-02_01.06.21 CLI progress systems current state

Source: `docs/understandings/2026-03-02_01.06.21-cli-progress-systems-current-state.md`

Findings preserved:
- CLI currently has three parallel progress systems:
  1. `_AllMethodProgressDashboard` for all-method queue snapshots.
  2. `_run_with_progress_status(...)` for generic callback-driven rendering.
  3. Stage `Live` worker panel (`WorkerDashboard`) path.
- These systems represent similar state but are implemented separately.
- All-method dashboard shape is the best current extraction seed for a shared progress core.

Anti-loop note:
- If unification work starts, capture state model parity first; do not start by rewriting renderer formatting only.

### 2026-03-02_01.12.49 C3imp interactive throttle and I/O pacing defaults

Source: `docs/understandings/2026-03-02_01.12.49-c3imp-interactive-throttle-and-io-pacing.md`

Problem captured:
- Interactive sessions needed safer default resource pressure without forcing users to hand-set shell env vars each run.

Durable decisions:
- Centralize interactive run-setting normalization through chooser flow.
- Seed conservative default envs in `C3imp` entrypoint:
  - `COOKIMPORT_WORKER_UTILIZATION=90`
  - `COOKIMPORT_IO_PACE_EVERY_WRITES=16`
  - `COOKIMPORT_IO_PACE_SLEEP_MS=8`
- Preserve explicit user env overrides as authoritative.

Anti-loop note:
- If throughput/pacing behavior differs from expectation, check effective env values and chooser output before tuning split scheduler internals.

### 2026-03-02_08.59.03 common-core progress dashboard plan gap audit

Source: `docs/understandings/2026-03-02_08.59.03-common-core-progress-dashboard-plan-gap-audit.md`

Problem captured:
- Shared progress-core migration plans under-scoped non-render runtime responsibilities and stage parity requirements.

Durable findings:
- `_run_with_progress_status(...)` includes runtime control responsibilities (ETA/rate sampling, worker sidechannel parse, mode selection, timeseries writes), not just text formatting.
- Stage path writes timeseries from a different state source and includes merge-phase worker updates; parity cannot be inferred from all-method path alone.
- Existing test coverage is stronger for all-method and generic callback paths than for stage shared-shape parity.

Durable requirement:
- Any shared-core migration must include dedicated stage parity tests for snapshot shape and worker reset/dedupe behavior in both plain/live modes.

Anti-loop note:
- If shared-core refactor appears complete but stage telemetry regresses, review stage-specific parity checklist before adjusting queue/admission logic.
