---
summary: "CLI architecture/build/fix-attempt log used to avoid repeating failed paths."
read_when:
  - When troubleshooting CLI behavior and you think "we are going in circles on this"
  - When doing multi-turn fixes and you need prior architecture/build/fix attempts
---
# CLI Build and Fix Log

This file is the anti-loop log for CLI work. Read it before retrying approaches that may already have failed.

### 2026-03-06_00.30.31 single-profile benchmark terminal noise suppression

Preserved finding:
- Shared single-profile benchmark status was still getting polluted by nested codex decision banners and recoverable codex-farm warning logs, which made the PTY look corrupted even though the benchmark runner itself was still alive.

Current rule:
- `_print_codex_decision(...)` is suppressed when benchmark summary suppression is active.
- Recoverable codex-farm partial-output failures should surface as one short progress line through the shared callback path during interactive/shared-status runs, not as multiline warning logs directly into the terminal.

### 2026-03-03_23.30.00 single-profile selected-matched benchmark mode

Preserved finding:
- Interactive benchmark needed a middle path between one-book single-offline and all matched sets, where operators can pick only specific matched books.

Current rule:
- Interactive benchmark mode picker now includes `Single config, selected matched sets: Pick which matched books to run`.
- Selected-matched mode opens a toggle menu for matched books with `Run selected books (N)` and `Run all matched books`.
- The runner keeps single-profile semantics (one config per selected target, offline canonical-text eval, no all-method expansion).

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
- Superseded by `2026-03-02_23.01.36` (merged below): interactive dashboard generation no longer prompts to open browser and always calls `stats_dashboard(..., open_browser=False)`.

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

## 2026-03-02 docs/tasks merge ledger (interactive quality-first preset)

### 2026-03-02_00.24.23 quality-first winner stack preset in shared chooser

Source task file:
- `docs/tasks/2026-03-02_00.24.23-interactive-quality-first-run-settings-preset.md`

Problem captured:
- Interactive run-settings flow lacked a stable built-in quality-first preset option, forcing manual edits or dependency on saved profile artifacts.

Durable decisions:
- Add a chooser option in `choose_run_settings(...)` for `Run with quality-first winner stack (...)`.
- Apply deterministic built-in patch values:
  - `epub_extractor=unstructured`
  - `epub_unstructured_html_parser_version=v1`
  - `epub_unstructured_preprocess_mode=semantic_v1`
  - `epub_unstructured_skip_headers_footers=true`
- Keep this preset independent from saved winner/profile files so it is always available in interactive import and benchmark flows.

Evidence preserved:
- `. .venv/bin/activate && pytest tests/cli/test_c3imp_interactive_menu.py -q`

Anti-loop note:
- If preset menus drift between import and benchmark, patch the shared chooser path (`cookimport/cli_ui/run_settings_flow.py`) rather than mode-specific menu branches.

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

## 2026-03-02 migrated understanding ledger (common-core progress dashboard execution + stage parity)

Chronological migration from `docs/understandings`; source files are retired after this merge.

### 2026-03-02_01.05.35 common-core progress-dashboard migration

Source: `docs/understandings/2026-03-02_01.05.35-common-core-progress-dashboard-migration.md`

Problem captured:
- Stage/benchmark callback and worker rendering were duplicated across paths and ETA/rate logic was at risk of diverging.

Durable decisions:
- Route callback and worker lines through shared `ProgressCallbackAdapter` / `ProgressDashboardCore`.
- Preserve existing callback compatibility while unifying worker-line formatting and stage `Live(...)` rendering.

Anti-loop note:
- If live behavior diverges, diff `status` and `snapshot_text` output rather than only unit tests.

### 2026-03-02_09.37.48 review gaps in common-core progress migration

Source: `docs/understandings/2026-03-02_09.37.48-common-core-progress-dashboard-review-gaps.md`

Problem captured:
- `_run_with_progress_status(...)` used a broken worker-count expression, and stage parity tests were asserting monkeypatched entrypoints that no longer existed on module import.

Durable findings:
- `worker_snapshot` logic needed correction to match `snapshot_workers()` return type.
- Stage parity tests should patch through `cookimport.cli_worker` helper import surfaces (and merged split path helpers) instead of `cli` module attributes.

Anti-loop note:
- If stage tests fail after progress edits, confirm both test monkeypatch targets and worker snapshot arithmetic before rewriting the dashboard contract.

### 2026-03-02_09.48.15 current-state blocker during common-core migration review

Source: `docs/understandings/2026-03-02_09.48.15-common-core-progress-dashboard-review-current-state-gap.md`

Problem captured:
- `_run_with_progress_status(...)` live-path indentation made `cookimport.cli` fail import and prevented live progress behavior entirely in that working tree.

Durable decisions:
- Treat this as a non-contractual importability blocker to be fixed before relying on any migration completion checkboxes.

Anti-loop note:
- A live-mode import error always invalidates dashboard completion claims.

### 2026-03-02_09.52.00 common-core progress review fixes

Source: `docs/understandings/2026-03-02_09.52.00-common-core-progress-dashboard-review-fixes.md`

Problem captured:
- Live ticker and stage parity tests still failed because of incorrect worker-count handling and wrong patch targets.

Durable outcomes:
- Replaced broken worker count expression with direct worker count consumption from `snapshot_workers()`.
- Updated stage test monkeypatch paths to `cli_worker.stage_one_file` and split helpers.
- Added merge-phase snapshot assertions for stage parity.

Anti-loop note:
- If parity tests regress, check monkeypatch target names before changing run-loop behavior.

### 2026-03-02_10.12.00 OG plan parity review after migration

Source: `docs/understandings/2026-03-02_10.12.00-common-core-progress-dashboard-ogplan-parity-review.md`

Problem captured:
- OG acceptance criteria expected parity, but stage path still lacked an explicit adapter abstraction despite otherwise shared state logic.

Durable findings:
- `_run_with_progress_status(...)` migration was functionally in place, and ETA/rate contracts passed.
- Full parity gate still required for stage merge and adapter coverage.

Anti-loop note:
- Do not close architecture gates while stage parity tests are still known-failing.

### 2026-03-02_19.00.00 stage progress live/plain parity

Source: `docs/understandings/2026-03-02_19.00.00-stage-progress-live-plain-parity.md`

Problem captured:
- Stage path lacked consistent live/plain parity around shared core snapshots and backend-resolution metadata capture.

Durable outcomes:
- Stage now renders snapshot text through shared core in both live and plain modes; plain mode strips rich tags.
- `_run_jobs` uses `nonlocal` to preserve backend/merge-resolution metadata so post-run `stage_worker_resolution.json` is consistent.

Anti-loop note:
- If `stage_worker_resolution.json` misses backend/context fields, check helper-scope metadata wiring before changing spinner render code.

### 2026-03-02_22.00.00 common-core progress-dashboard fix completion

Source: `docs/understandings/2026-03-02_22.00.00-common-core-progress-dashboard-fix-completion.md`

Problem captured:
- Adapter surface and direct test coverage for shared progress core were incomplete.

Durable decisions:
- Added `ProgressCallbackAdapter.snapshot_text()` API.
- Added direct adapter rendering coverage in `tests/core/test_progress_dashboard.py`.
- Mapped `tests/core/test_progress_dashboard.py` to core marker grouping for suite organization.

Anti-loop note:
- If adapter contract changes, update tests in both core and CLI layers together.

### 2026-03-02_23.00.00 stage progress current-label adapter behavior

Source: `docs/understandings/2026-03-02_23.00.00-common-core-progress-dashboard-stage-adapter-current-label.md`

Problem captured:
- Snapshot `current:` context did not consistently reflect active stage files after shared core migration.

Durable decisions:
- Stage snapshots now pull `current:` from `_resolve_stage_current_file`.
- All callback strings pass through adapter ingestion before ETA/rate accounting updates.
- Stage parity assertions now include `current:` presence in live/plain snapshots and merge paths.

Anti-loop note:
- If no `current:` line appears in merged mode, validate `_resolve_stage_current_file` fallback order first.

### 2026-03-02_23.15.00 stage adapter parity updates

Source: `docs/understandings/2026-03-02_23.15.00-stage-progress-dashboard-adapter-parity.md`

Problem captured:
- Stage worker-file state was still split between local and shared paths, with parity assertions not exercising worker lines consistently.

Durable decisions:
- Added `_StageProgressAdapter` for stage worker/file state and routed stage snapshot reads/writes through it.
- Aligned merge-phase assertions to include shared snapshot shape and active lines.

Anti-loop note:
- If stage parity regresses, compare `StageProgressAdapter` vs callback adapter inputs before touching core state model.

### 2026-03-02_01.05.35 common-core-progress-dashboard migration

Source task file:
- `docs/tasks/2026-03-02_01.05.35-common-core-progress-dashboard.md`

Problem captured:
- Stage, single benchmark/import, and all-method flows had independent progress implementations and different worker/current labeling semantics, making behavior hard to compare and easy to regress.
- Callback worker activity parsing and ETA/plain-mode behavior were coupled to each path, increasing blast radius during refactors.

Decision summary from execution:
- Build a shared snapshot/renderer core (`ProgressDashboardCore`) and move status assembly into adapters, not each caller.
- Keep `_run_with_progress_status(...)` as the behavior owner for timing, dedupe, mode selection, and timeseries.
- Keep stage-specific worker semantics in a stage adapter rather than adding stage-only render branches in every path.
- Preserve callback compatibility and existing contract for `activity`/`reset` messages.

Outcomes:
- Shared core now underpins all three execution profiles.
- `tests/core/test_progress_dashboard.py` and `tests/cli/test_stage_progress_dashboard.py` lock in live/plain parity and merge-phase behavior.
- Stage merge/backend lines are now captured into durable artifacts and the core snapshot text in both live/plain transport modes.

Failure-history that should not be repeated:
- An early regression path around wrong worker-line indexing and stale monkeypatch targets was encountered; fix landed by standardizing on `snapshot_workers()` and canonicalizing stage adapter targets.

Anti-loop note:
- If progress text starts to drift, first inspect adapter payload mapping and callback ingestion, then touch spinner output formatting.


## 2026-03-03 migrated understandings ledger (docs/understandings consolidation)

This section preserves detailed CLI/interactive discoveries in timestamp order after removing standalone files from `docs/understandings/`.

### 2026-03-02_00.00.00-progress-spinner-ascii-panel

Source file: docs/understandings/2026-03-02_00.00.00-progress-spinner-ascii-panel.md
Summary: Make benchmark/import status spinners render as a bordered ASCII panel.


# Progress spinner should stay boxed and readable

- Stable status rendering is now done in `cookimport.cli._run_with_progress_status(...)` by wrapping each live snapshot in an ASCII border before passing it to `console.status`.
- The border is built from the same snapshot that already powers worker/task/ETA lines, so behavior stays in one rendering pipeline (ETA, counter parsing, worker summaries unchanged).
- This is intentionally limited to live spinner mode (`console.status`) so plain non-ANSI snapshots keep their previous compact one-line output behavior.
- In legacy/plain-mode runs, progress callbacks still stream one-line updates without border formatting.


### 2026-03-02_07.10.00-c3imp-spinner-default

Source file: docs/understandings/2026-03-02_07.10.00-c3imp-spinner-default.md
Summary: Why C3imp showed plain progress and where spinner mode is overridden.


# C3imp should keep the spinner by default

- Investigation confirmed C3imp menu flows use the shared progress callback stack (`_run_with_progress_status`), but plain updates were forced by agent-env defaults (`CODEX_CI`, `CODEX_THREAD_ID`, `CLAUDE_CODE_SSE_PORT`).
- `cookimport/c3imp_entrypoint.py` previously did not set `COOKIMPORT_PLAIN_PROGRESS`, so the shared spinner logic defaulted to plain mode in agent-like environments.
- The fix is to set `COOKIMPORT_PLAIN_PROGRESS=0` in `c3imp_entrypoint.py` via `os.environ.setdefault(...)`, which lets interactive menu runs keep animated spinner behavior.
- Also added a short README note in `cookimport/README.md` documenting C3imp’s spinner default and override behavior.


### 2026-03-02_13.24.00-interactive-run-settings-compact-menu

Source file: docs/understandings/2026-03-02_13.24.00-interactive-run-settings-compact-menu.md
Summary: Interactive run-settings picker switched from full settings dumps to compact hash labels.


# Interactive run-settings menu UX compacted

- `choose_run_settings(...)` in `cookimport/cli_ui/run_settings_flow.py` now supports a compact menu label mode for interactive selection.
- `C3imp` interactive `import` and `labelstudio_benchmark` flows now pass `show_summary=False`, so preset choices use short hash labels instead of full `key=value` dumps.
- Post-selection output in interactive import/benchmark flows was reduced to `Run settings hash: ...` while preserving behavior and run settings semantics.


### 2026-03-02_15-40-00-plain-progress-no-spam

Source file: docs/understandings/2026-03-02_15-40-00-plain-progress-no-spam.md
Summary: 2026-03-02_15.40.00: quiet plain progress output for benchmark runs

## 2026-03-02_15.40.00: quiet plain progress output for benchmark runs

- `_run_with_progress_status` now renders plain progress updates as a single in-place line when stdout is a TTY, instead of printing a new line for every tick/message. This keeps a stable summary visible during long codex-farm stages.
- `SubprocessCodexFarmRunner` now filters progress-event lines out of stderr warnings and only warns on non-progress stderr content, so normal codex-farm queue/run chatter is no longer emitted as terminal spam.
- `SubprocessCodexFarmRunner` now also parses legacy `run=<id> queued=... running=... done=...` progress lines and turns them into callback updates, plus previewing active `input_path` names from JSON progress events (`active ...`) so users can see what each worker slot is processing.


### 2026-03-02_19.48.22-benchmark-interactive-regression-fixes

Source file: docs/understandings/2026-03-02_19.48.22-benchmark-interactive-regression-fixes.md
Summary: Regression notes for interactive benchmark routing and codex-farm progress callback formatting.


# Benchmark interactive regression fixes (2026-03-02)

- `_interactive_single_offline_benchmark` must not hard-require gold/source resolution in non-interactive contexts. Prompting there causes `EOFError` in headless/test runs and prevents benchmark dispatch.
- Hidden `benchmark_mode="all_method"` still needs a routing branch in `_interactive_mode` even if not shown in menu choices; tests and automation rely on this direct value.
- Progress callback messages from codex-farm should keep stable `task X/Y` formatting without volatile active-task suffixes so duplicate status events collapse correctly.


### 2026-03-02_20.00.00-remove-all-method-benchmark-from-interactive-menu

Source file: docs/understandings/2026-03-02_20.00.00-remove-all-method-benchmark-from-interactive-menu.md
Summary: Remove all-method benchmark from interactive menu

# Remove all-method benchmark from interactive menu

- Interactive benchmark mode selection under `labelstudio_benchmark` now only offers:
  - single offline eval
  - single config against all matched sets
- The existing all-method benchmark runtime path (`_interactive_all_method_benchmark`) remains in code but is no longer reachable from the interactive menu.


### 2026-03-02_21.22.44-cli-live-status-with-indent-regression

Source file: docs/understandings/2026-03-02_21.22.44-cli-live-status-with-indent-regression.md
Summary: Fix a CLI import crash caused by mis-indented live-status `with console.status(...)` block.


# CLI live-status indentation regression

- `cookimport/cli.py` had `with console.status(...)` indented under `if not supports_live_status:` after an early `return`, so Python parsed a `with` statement at the wrong level and then hit `IndentationError` because its body was not nested beneath it.
- Fix was indentation-only: dedent the `with console.status(...)` line so it runs in the live-status path while keeping its existing body unchanged.


### 2026-03-02_21.55.02-codex-farm-busy-panel-work-summary

Source file: docs/understandings/2026-03-02_21.55.02-codex-farm-busy-panel-work-summary.md
Summary: 2026-03-02_21.55.02 spinner panel + busy worker summary

### 2026-03-02_21.55.02 spinner panel + busy worker summary

- I inspected `cookimport/cli.py::_run_with_progress_status(...)` and extended the live
  render path to add a bordered ASCII panel with a static title line and a worker summary
  section injected into the snapshot.
- The worker summary is derived from:
  - parsed `running N` values (used as slot count), and
  - parsed `active [...]` task lists when present.
- If `active [...]` is not available, the spinner now renders generic worker slot rows so operators
  can still see the active worker count and that all workers are considered busy.
- I updated `cookimport/llm/codex_farm_runner.py` so Codex-Farm stderr lines that are already
  surfaced through progress callbacks are logged at debug instead of warning to avoid noisy console
  spam during normal benchmark runs.


### 2026-03-03_00.00.00-codexfarm-progress-active-workers

Source file: docs/understandings/2026-03-03_00.00.00-codexfarm-progress-active-workers.md
Summary: Track why codex-farm benchmark progress now includes active worker task labels.


# Codex-farm active worker progress visibility

- Added parsing for `Created run <id> with <n> tasks` so run bootstrap lines are no longer emitted as generic stderr noise and can be surfaced as progress messages.
- Extended callback formatting to append `active [...]` labels when `__codex_farm_progress__` payloads include task metadata (`running_tasks`, `running_task_ids`, etc.).
- Kept counter-only fallback behavior when task metadata is not available.
- Updated tests/docs so this is now a stable one-line live summary behavior instead of per-task spinner/noise.

## 2026-03-03 docs/tasks consolidation batch (interactive wording + dashboard prompt removal)

### 2026-03-02_18.22.28 clarify interactive menu labels

Source task file:
- `docs/tasks/2026-03-02_18.22.28 - clarify interactive menu labels.md`

Problem captured:
- Interactive select labels mixed styles (`name - description`, longer phrases), reducing scanability.

Durable decisions/outcomes:
- Interactive select labels now follow `NAME: short description` consistently (numeric prefixes continue to come from Questionary shortcuts).
- Benchmark submenu wording now keeps mode options distinct at one glance without changing flow behavior.
- Docs and tests were aligned to runtime wording contract.

### 2026-03-02_23.01.36 remove interactive dashboard open-browser prompt

Source task file:
- `docs/tasks/2026-03-02_23.01.36 - remove-dashboard-open-browser-prompt.md`

Problem captured:
- Interactive dashboard flow asked `Open dashboard in your browser after generation?`, adding friction and unreliable behavior in some environments.

Durable decisions/outcomes:
- Interactive dashboard branch now always generates files with `open_browser=False`.
- Interactive flow no longer asks for open-browser confirmation.
- Non-interactive `cookimport stats-dashboard --open` behavior is unchanged.

Evidence preserved:
- Fail-before then pass-after on `tests/labelstudio/test_labelstudio_benchmark_helpers.py -k interactive_generate_dashboard_runs_without_browser_prompt`.


## 2026-03-03 migrated understanding ledger (spinner runtime behavior)


### 2026-03-03_12.18.43 benchmark-spinner-panel-width-clamp

Source:
- `docs/understandings/2026-03-03_12.18.43-benchmark-spinner-panel-width-clamp.md`

Summary:
- Benchmark/import live spinner panel width must clamp to terminal width to avoid long-task overflow.

Preserved notes:

```md
summary: "Benchmark/import live spinner panel width must clamp to terminal width to avoid long-task overflow."
read_when:
  - "When benchmark/import spinner panels look too wide or wrap awkwardly in live terminals"
  - "When changing `_run_with_progress_status` boxed-panel rendering in `cookimport/cli.py`"
---

`_run_with_progress_status` renders a boxed panel in live mode. Before this fix, `_format_boxed_progress(...)` sized the box from the longest status line (capped at 120 chars), so long worker task labels (for example codex-farm file IDs) could force an oversized panel.

Current contract:
- Cap panel content width to a terminal-aware limit (`min(92, console.width - 6)` when terminal width is known).
- Truncate title/body text with ASCII `...` before padding so borders and content stay aligned.
- Keep worker/task information visible, but never let one long line expand the panel past the compact target width.

```

### 2026-03-03_12.20.00 spinner-eta-weighted-window-bootstrap

Source:
- `docs/understandings/2026-03-03_12.20.00-spinner-eta-weighted-window-bootstrap.md`

Summary:
- Spinner ETA gaps came from first-seen counters lacking increment history; ETA now uses weighted last-5 steps with a bootstrap fallback.

Preserved notes:

```md
summary: "Spinner ETA gaps came from first-seen counters lacking increment history; ETA now uses weighted last-5 steps with a bootstrap fallback."
read_when:
  - "When spinner status shows `task X/Y` but ETA is missing early in a phase"
  - "When tuning `_run_with_progress_status` ETA smoothing weights/window in `cookimport/cli.py`"
---

- `_run_with_progress_status(...)` previously required at least one observed counter increment delta before ETA could be computed, so first-seen counters like `task 2/19` could show no ETA.
- ETA smoothing now uses a weighted moving average over the most recent five completed steps (newest-first weights: `30/20/20/20/10`).
- If increment history is still empty but progress already started (`X > 0`), ETA bootstraps from `run_elapsed / X` until step-history samples arrive.

```


## 2026-03-03 docs/understandings consolidation batch

The entries below were merged from `docs/understandings` in timestamp order before source-file cleanup.

### 2026-03-03_13.12.17-spinner-panel-truncation-preserves-eta-suffix

Source:
- `docs/understandings/2026-03-03_13.12.17-spinner-panel-truncation-preserves-eta-suffix.md`

Summary:
- Live benchmark spinner line truncation should preserve ETA/avg suffix visibility.

Preserved source note:

````md
---
summary: "Live benchmark spinner line truncation should preserve ETA/avg suffix visibility."
read_when:
  - "When spinner shows task counters but ETA is missing in boxed live mode"
  - "When editing `_run_with_progress_status` panel truncation behavior in `cookimport/cli.py`"
---

Root cause: `_format_boxed_progress(...)` previously truncated long lines from the right, so appended timing suffixes like `(eta ..., avg .../task)` were clipped off when codex-farm `active [...]` payloads made the line too long.

Current contract:
- Boxed panel truncation should preserve trailing timing parentheticals (`eta`/`avg`/elapsed) by clipping the middle of the line when needed.
- Long worker/task identifiers may still be shortened, but timing visibility on the main status line is prioritized.

````

### 2026-03-03_13.28.55-codex-spinner-stage-readable-pass-labels

Source:
- `docs/understandings/2026-03-03_13.28.55-codex-spinner-stage-readable-pass-labels.md`

Summary:
- Codex-farm spinner status should surface a readable pass label and explicit stage row.

Preserved source note:

````md
---
summary: "Codex-farm spinner status should surface a readable pass label and explicit stage row."
read_when:
  - "When benchmark spinner text is too opaque about current codex-farm phase"
  - "When editing codex-farm progress display in `_run_with_progress_status`"
---

Raw codex-farm callback lines (`codex-farm recipe.schemaorg.v1 task X/Y | running N | active [...]`) are accurate but not operator-friendly in the boxed panel.

Current contract:
- Live spinner rewrites codex-farm status to human pass labels (`pass1 chunking`, `pass2 schemaorg`, `pass3 final`, `pass4 knowledge`, `pass5 tags`) while retaining `task X/Y` and `running` counters for ETA.
- Panel also emits `stage: <pass label>` above worker lines so stage remains visible even when top line is width-truncated.
- Worker rows continue to show active task IDs; stage readability is separated from raw task identifier noise.

````

### 2026-03-03_17.34.31-spinner-active-tasks-left-counter-source

Source:
- `docs/understandings/2026-03-03_17.34.31-spinner-active-tasks-left-counter-source.md`

Summary:
- Codex benchmark spinner can surface remaining tasks from the parsed task X/Y counter in the worker summary row.

Preserved source note:

````md
---
summary: "Codex benchmark spinner can surface remaining tasks from the parsed task X/Y counter in the worker summary row."
read_when:
  - "When benchmark spinner no longer shows an explicit remaining-task count"
  - "When editing `_run_with_progress_status` worker summary rendering in `cookimport/cli.py`"
---

Discovery:
- The boxed spinner's top status line can truncate the middle when preserving trailing ETA/avg suffixes, which can hide the `task X/Y` segment.
- `_inject_worker_summary_lines(...)` already receives codex worker task payloads; adding `N left` from `latest_counter` to `active tasks (...)` keeps remaining work visible on a dedicated row.

````

### 2026-03-04 understandings consolidation (interactive top-tier setting source control)

Merged source notes:
- `docs/understandings/2026-03-04_00.33.51-single-profile-codex-line-role-setting-source.md`
- `docs/understandings/2026-03-04_00.44.22-interactive-top-tier-default-run-settings-source-of-truth.md`
- `docs/understandings/2026-03-04_00.49.14-interactive-winner-harmonization-for-codex-line-role.md`

Problem lineage preserved:
- A concrete regression run (`2026-03-03_23.27.32`) showed `llm_recipe_pipeline=codex-farm-3pass-v1` with `line_role_pipeline=off` and `atomic_block_splitter=off`.
- Root cause was settings reuse and partial toggling behavior (codex toggle changed only llm pipeline), not benchmark scorer drift.
- Saved quality-suite winner payloads can carry stale off/off/off knobs and bypass fallback defaults if not normalized.

Durable decisions captured:
- Interactive benchmark/import settings now resolve through one automatic top-tier profile flow.
- Post-resolution harmonization enforces the coupled codex trio regardless of source (saved winner or built-in fallback):
  - `llm_recipe_pipeline=codex-farm-3pass-v1`
  - `line_role_pipeline=codex-line-role-v1`
  - `atomic_block_splitter=atomic-v1`

Anti-loop reminders:
- When a run quality drop is observed, inspect resolved `RunSettings` payload/hash first.
- Do not assume codex pipeline implies line-role/atomic are enabled unless harmonization was applied.

### 2026-03-04 understandings consolidation (two top-tier profile families)

Merged source note:
- `docs/understandings/2026-03-04_01.20.00-interactive-two-top-tier-profiles-codex-vs-vanilla.md`

Problem captured:
- One forced codex-harmonized automatic profile removed stale-menu drift but also removed a deterministic baseline operating path.

Durable decision:
- Interactive resolver exposes exactly two automatic top-tier profile families:
  - CodexFarm top-tier (winner-first + codex harmonization).
  - Vanilla top-tier (codex-off deterministic baseline with deterministic line-role/atomic + EPUB defaults).

Anti-loop reminder:
- Preserve two-profile deterministic choice; do not restore broad profile branches to recover codex-vs-vanilla comparison capability.

### 2026-03-04 docs/tasks consolidation (top-tier default run-settings resolver)

Merged source task file:
- `docs/tasks/2026-03-04_00.44.22-top-tier-default-run-settings.md`

Problem captured:
- Interactive import/benchmark still exposed multi-profile menu choice, allowing stale low-quality combinations (notably codex ON with line-role/atomic OFF).

Durable decisions/outcomes:
- Removed interactive chooser behavior from routine import/benchmark flow.
- Centralized deterministic resolution in `choose_run_settings(...)`.
- Resolver contract: winner-first, baseline fallback second, with codex+line-role+atomic preserved in baseline.

Verification evidence preserved from task:
- `. .venv/bin/activate && pytest tests/cli/test_c3imp_interactive_menu.py -q`
- Updated tests assert winner usage, fallback behavior, and absence of chooser/codex-prompt callbacks.

Anti-loop reminder:
- Reintroducing manual profile-picking should be treated as an explicit behavior change with new regression evidence, not an ad-hoc tweak.

### 2026-03-04_01.49.43 legacy EPUB extractor migration parity

- Interactive config load path in `cookimport/cli.py::_load_settings()` now treats stored `epub_extractor=legacy` as an explicit migration to `beautifulsoup` (warning: migration), matching `RunSettings.from_dict(...)` behavior.
- This removes misleading generic "stored value not supported" warnings for legacy configs and preserves backward compatibility semantics.
- Added regression coverage in `tests/cli/test_c3imp_interactive_menu.py::test_load_settings_migrates_legacy_epub_extractor`.

### 2026-03-04_01.56.50 EPUB extractor migration parity follow-up (`auto`)

- Extended interactive `cookimport.json` migration parity in `cookimport/cli.py::_load_settings()`:
  - `epub_extractor=legacy` => explicit migration warning + `beautifulsoup`.
  - `epub_extractor=auto` => explicit removal warning + `unstructured`.
- Keeps startup warning semantics aligned with `RunSettings.from_dict(...)` migration behavior.
- Added regression coverage in `tests/cli/test_c3imp_interactive_menu.py::test_load_settings_migrates_auto_epub_extractor_to_unstructured`.

### 2026-03-04 understandings merge ledger (interactive codex setup + run-settings cleanup)

Merged source notes (timestamp order):
- `docs/understandings/2026-03-04_01.19.12-interactive-codex-toggle-top-tier-resolution.md`
- `docs/understandings/2026-03-04_01.37.23-two-profile-run-settings-cleanup-seams.md`
- `docs/understandings/2026-03-04_01.49.43-cli-legacy-epub-extractor-migration-parity.md` (captured above)
- `docs/understandings/2026-03-04_01.55.47-single-profile-benchmark-codex-model-effort-prompt-boundary.md` (historical/superseded)
- `docs/understandings/2026-03-04_01.56.50-cli-epub-extractor-migration-parity-auto-followup.md` (captured above)
- `docs/understandings/2026-03-04_01.59.33-interactive-codex-ai-settings-coupled-prompts.md`
- `docs/understandings/2026-03-04_06.51.02-interactive-codex-model-menu-only.md`
- `docs/understandings/2026-03-04_06.55.46-interactive-codex-effort-model-copy-validation-gap.md`

#### 2026-03-04_01.19.12 interactive codex toggle -> top-tier profile resolution
- Replaced explicit codex/vanilla profile menu wording with codex intent prompt.
- Intent mapping remains deterministic and still resolves to the same two profile families.
- This keeps codex-vs-vanilla decision explicit without restoring broad profile-pick surfaces.

#### 2026-03-04_01.37.23 two-profile run-settings cleanup seams
- Removed dead legacy run-settings branches around persistence/editor/all-method routing that no longer had menu reachability.
- Preserved qualitysuite winner persistence path while retiring obsolete last/preferred settings APIs.

#### 2026-03-04_01.55.47 historical prompt boundary (superseded)
- Historical state: single-profile codex choice did not yet force immediate model/effort prompting.
- Superseded by `2026-03-04_01.59.33` where codex enablement and AI settings prompting were intentionally coupled in chooser flow.

#### 2026-03-04_01.59.33 coupled codex AI settings prompts
- When codex is enabled in shared chooser, model + reasoning effort prompts are now part of the same setup transaction.
- Prompt cancellation returns `None` so callers can exit cleanly without partial run-state mutation.

#### 2026-03-04_06.51.02 menu-only codex model selection
- Model override prompt is menu-only and sourced from discovered codex-farm models (+ deterministic fallback).
- Freeform model text entry branch was removed from shared chooser flow.

#### 2026-03-04_06.55.46 reasoning-effort validation gap fix
- `model_copy(update=...)` path left reasoning effort as raw string and triggered pydantic serializer warnings.
- Fix path reconstructs settings through validated `RunSettings.from_dict(...)`-style normalization to keep enum typing stable.

Anti-loop reminders:
- If codex setup prompt behavior regresses, verify chooser sequencing and cancellation semantics before touching benchmark command routes.
- If model/effort warnings return, inspect update/validation path first (not serializer config).

### 2026-03-04 docs/tasks merge ledger (interactive codex setup sequence)

Merged source task files (timestamp order):
- `docs/tasks/2026-03-04_01.22.04-interactive-codex-toggle-top-tier.md`
- `docs/tasks/2026-03-04_01.59.33-interactive-codex-ai-settings-always-prompt.md`
- `docs/tasks/2026-03-04_06.50.54-interactive-model-menu-only.md`
- `docs/tasks/2026-03-04_06.55.38-interactive-codex-effort-enum-warning.md`

#### 2026-03-04_01.22.04 codex on/off prompt replaces top-tier picker wording

Problem captured:
- Profile-family choice was expressed as a top-tier profile menu instead of codex intent.

Durable outcomes:
- `choose_run_settings(...)` uses codex intent prompt and maps to codex/vanilla top-tier families.
- `COOKIMPORT_TOP_TIER_PROFILE` override contract preserved.
- Single-offline codex-enabled behavior still runs vanilla baseline then codexfarm for comparison.

Verification evidence retained:
- `pytest tests/cli/test_c3imp_interactive_menu.py -k choose_run_settings`: `5 passed`.
- Targeted single-offline variant ordering tests: `2 passed`.

#### 2026-03-04_01.59.33 codex AI settings always prompted on codex-on runs

Problem captured:
- Codex could be enabled in interactive flows without asking model/effort overrides in shared chooser path.

Durable outcomes:
- Import + benchmark interactive paths now pass through codex AI settings prompt phase when codex is selected.
- Cancel/back from model/effort prompts returns `None` and cancels run setup.

Verification evidence retained:
- `-k choose_run_settings` suite and targeted single-profile helper tests remained green.

#### 2026-03-04_06.50.54 model menu-only chooser

Problem captured:
- Shared chooser still allowed freeform model typing branch.

Durable outcomes:
- Model selection moved to menu-only contract with discovered models, pipeline default, and deterministic fallback.
- Signature stability preserved for existing callers.

Verification evidence retained:
- `pytest tests/cli/test_c3imp_interactive_menu.py -k "choose_run_settings_codex" -q` (exit `0`).

#### 2026-03-04_06.55.38 reasoning-effort enum warning fix

Problem captured:
- `model_copy(update=...)` bypassed validation, leaving `codex_farm_reasoning_effort` as raw string and triggering serializer warnings.

Durable outcomes:
- Chooser updates now reconstruct validated `RunSettings` so effort values normalize to enum type.
- Prompt UX unchanged.

Verification evidence retained:
- Codex chooser tests green after fix (`pytest_exit=0`).

Anti-loop reminders:
- If codex prompt sequence regresses, inspect chooser sequencing/cancel-return semantics before changing benchmark command routing.
- If pydantic warnings reappear, check settings update validation path before serializer/output code.

## 2026-03-04 docs/tasks consolidation batch (interactive run-settings + spinner ETA)

### 2026-03-04_01.24.38 two-profile run-settings cleanup

Source task:
- `docs/tasks/2026-03-04_01.24.38-two-profile-run-settings-cleanup.md`

Problem captured:
- Interactive flows still carried dead/stale run-settings surfaces (`global/last/edit`, preferred/last persistence, toggle editor, and unreachable interactive all-method branch).

Durable outcomes:
- Kept interactive setup centered on two automatic profile families only.
- Removed stale persistence/editor APIs while preserving `qualitysuite_winner_run_settings` persistence.
- Removed dead interactive all-method branch while keeping non-interactive all-method command surface intact.
- Aligned tests/docs to current chooser behavior.

Evidence retained from task:
- `. .venv/bin/activate && pytest tests/cli/test_c3imp_interactive_menu.py -q`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_single_profile.py -q`
- `. .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler.py -q`
- `. .venv/bin/activate && pytest tests/llm/test_run_settings.py -q`

Anti-loop reminders:
- Do not restore legacy run-settings branches to patch benchmark/profile regressions; debug chooser resolution and harmonization first.
- If interactive benchmark behavior drifts, confirm menu reachability before touching all-method internals.

### 2026-03-04_08.30.36 spinner ETA recent-bias update

Source task:
- `docs/tasks/2026-03-04_08.30.36-spinner-eta-recent-bias.md`

Problem captured:
- Spinner ETA smoothing lagged behind sudden throughput changes, making estimates stale.

Durable outcomes:
- `_recent_rate_average_seconds_per_task` now blends newest step duration with weighted window average (deterministic 50/50 blend).
- ETA responsiveness improvement is shared across callback/status spinner flows that use `_run_with_progress_status(...)`.

Evidence retained from task:
- `source .venv/bin/activate && pytest -q tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py -k "recent_rate_average_seconds_per_task or shows_eta_for_xy_progress or shows_eta_for_canonical_line_role_progress"`

Rollback note from task:
- If needed, revert to weighted-only ETA helper output and prior test expectations.

## 2026-03-04 docs/understandings consolidation batch (spinner state carryover + ETA blend)

### 2026-03-04_08.10.42 spinner line-role ETA worker-state cleanup

Source note:
- `docs/understandings/2026-03-04_08.10.42-spinner-line-role-eta-worker-state.md`

Problem captured:
- Codex worker/task overlay state leaked across phase transitions, causing misleading `active workers: 0` rows after codex-to-non-codex status changes.

Durable outcomes:
- `_update_progress_common` now clears codex worker/stage fields on non-codex, non-worker callback messages.
- Canonical line-role task-count messages were wired through ingest->parser callback path so spinner ETA logic can run on that phase.

Anti-loop reminder:
- If worker rows look stale, inspect state-reset logic in `_update_progress_common` before changing spinner render formatting.

### 2026-03-04_08.30.36 spinner ETA recent-blend

Source note:
- `docs/understandings/2026-03-04_08.30.36-spinner-eta-recent-blend.md`

Problem captured:
- Weighted-window-only ETA lagged during sharp throughput changes.

Durable outcomes:
- `_recent_rate_average_seconds_per_task(...)` now blends latest per-step duration with weighted recent history (50/50).
- ETA strings in shared spinner paths react faster while retaining stability.

Anti-loop reminder:
- If ETA feels stale again, check blend math and step-sample updates before widening callback frequency.

## 2026-03-06 migrated understanding ledger (top-tier source, chooser validation, and pass4 follow-up)

### 2026-03-06_14.22.47 and 2026-03-06_14.47.31 top-tier contract source-of-truth

Merged source notes:
- `docs/understandings/2026-03-06_14.22.47-top-tier-contract-vs-benchmark-normalization.md`
- `docs/understandings/2026-03-06_14.47.31-top-tier-codex-profile-source-of-truth.md`

Problem captured:
- Interactive top-tier behavior was easy to “fix” in menu code even though the actual defaults and benchmark harmonization lived deeper in the shared Codex decision layer.

Durable findings:
- `apply_top_tier_profile_contract(...)` in `cookimport/config/codex_decision.py` is the authoritative source for CodexFarm top-tier defaults.
- Shared chooser flows load or build a `RunSettings` payload, then harmonize it through that contract.
- The benchmark-normalization path and the interactive top-tier chooser therefore need to stay aligned through the same shared patch set, not through duplicated menu-local overrides.

Anti-loop note:
- If interactive top-tier and benchmark normalization drift, audit `codex_decision.py` first and only then adjust UI docs/tests.

### 2026-03-06_19.07.00 benchmark menu codex-effort validation boundary

Source:
- `docs/understandings/2026-03-06_19.07.00-benchmark-menu-codex-effort-validation-gap.md`

Problem captured:
- A fixed effort-choice list could offer unsupported model / reasoning-effort pairs if chooser code stopped honoring discovered `supported_reasoning_efforts`.

Durable findings:
- The real validation seam belongs in the shared chooser path, not in one benchmark menu wrapper.
- Current intended behavior is:
  - discover models,
  - derive supported effort choices from model metadata,
  - rebuild `RunSettings` through validated parsing.

Anti-loop note:
- If a bad model / effort pair shows up again, inspect `build_codex_farm_reasoning_effort_choices(...)` and chooser wiring before touching benchmark command flags.

### 2026-03-06_20.30.00 and 2026-03-06_21.20.00 pass4 follow-up seam and line-index join caveats

Merged source notes:
- `docs/understandings/2026-03-06_20.30.00-followup-cli-pass4-gap.md`
- `docs/understandings/2026-03-06_21.20.00-followup-attribution-and-line-role-join-caveats.md`

Problem captured:
- Follow-up tooling originally centered on line-role and recipe-pass evidence, while pass4 needed a run-level seam. At the same time, some line-role follow-up views were using direct index joins that could misalign canonical changed-line rows with atomic line-role rows.

Durable findings:
- Pass4 review needs dedicated selector/output shapes instead of being forced through line-role prompt-link audit semantics.
- Current `cf-debug` direction is:
  - pass4 selectors at the run level,
  - dedicated pass4 audit output,
  - pass4 artifact locators preserved separately from recipe pass1 / pass2 / pass3 artifacts.
- For structural title / header regressions, stage / draft title-labeling code paths are often more trustworthy than follow-up packet line-index joins.

Anti-loop note:
- If a follow-up packet shows the “wrong text,” suspect canonical-vs-atomic join mismatch before blaming the model or the benchmark scorer.

## 2026-03-13 migrated understanding ledger (docs-list entrypoint + run-settings surface cleanup)

### 2026-03-13_22.29.27 docs list invocation confusion

Source:
- `docs/understandings/2026-03-13_22.29.27-docs-list-invocation-confusion.md`

Problem captured:
- Agent-facing instructions were easy to misread as “run `docs:list` in the shell,” even though that name was only an npm script alias and not a standalone command path.

Durable decision:
- Keep onboarding/docs phrased as `npm run docs:list` or `./bin/docs-list`.

Anti-loop note:
- If an agent reports that the docs list command is missing, check whether they tried the bare npm script name before changing repo tooling.

### 2026-03-13_22.48.50 and 2026-03-13_23.09.32 run-settings surface audit to public/internal/retired split

Merged sources:
- `docs/understandings/2026-03-13_22.48.50-run-settings-surface-audit.md`
- `docs/understandings/2026-03-13_23.09.32-run-settings-public-surface-contract.md`

Problem captured:
- The raw `RunSettings` schema had grown into a much larger visible surface than the actual product/operator surface, which encouraged config drift, noisy manifests, and “configuration theater.”

Historical audit findings preserved:
- At audit time, `RunSettings` exposed 78 fields total, with 75 visible and only 3 hidden.
- That raw count overstated the real product surface because:
  - interactive flows already collapsed many decisions into top-tier profile families,
  - benchmark flows normalized settings through baseline/variant contracts,
  - several fields were effectively single-choice implementation seams, debug flags, or compatibility leftovers.

Shipped contract outcome:
- `cookimport/config/run_settings.py` now records field-level surface metadata plus retired-key compatibility handling.
- Public helpers and summaries default to the curated public surface.
- Internal-only controls remain persistable for benchmarking/debugging without advertising them as normal operator choices.
- `table_extraction` left the live schema entirely and is now compatibility-loaded as a retired key.

Anti-loop note:
- If someone wants to “just make one more internal knob visible,” require a concrete repeated operator use case first; do not use CLI help as an archaeology dump of implementation seams.

### 2026-03-13_23.26.13, 2026-03-13_23.26.22, and 2026-03-13_23.27.36 remaining run-settings leak points after first cleanup tranche

Merged sources:
- `docs/understandings/2026-03-13_23.26.13-bucket1-hardcode-remaining-surface-map.md`
- `docs/understandings/2026-03-13_23.26.22-run-settings-bucket2-remaining-surface-map.md`
- `docs/understandings/2026-03-13_23.27.36-run-settings-leak-points.md`

Problem captured:
- The first March 13 run-settings cleanup removed `table_extraction` and introduced public/internal metadata, but a large amount of the old surface still leaked through direct CLI flags, helper signatures, docs, summaries, and prediction-identity wiring.

Durable findings:
- Bucket 1 is incomplete:
  - several “should really be fixed behavior” settings are still live CLI/config/runtime inputs,
  - `benchmark_sequence_matcher` is especially split because it is internal in `RunSettings` while benchmark CLI/docs still expose the concept directly.
- Bucket 2 is also incomplete:
  - all 27 settings from that audit bucket were still public at the time of the late-night follow-up notes,
  - cleanup requires touching more than `run_settings.py` because Typer signatures, analytics summary code, helper APIs, and adapters all leak the same fields.
- Reproducibility constraints that should not be forgotten:
  - old payloads still need to load through `RunSettings.from_dict(...)`,
  - benchmark settings files and `run_settings_patch` paths still depend on broad persistence,
  - prediction identity and QualitySuite dimension logic still rely on some of these fields even if operators should stop seeing them.
- The right architecture direction is layered, not destructive:
  - keep `RunSettings` as the persistence/compatibility schema,
  - add a much smaller explicit operator-facing contract on top of it,
  - let `codex_decision.py` and benchmark contracts own frozen winner/default behavior instead of scattering more defaults through CLI code.

Anti-loop note:
- If a setting disappears from one menu but still shows up in `stage --help`, analytics summaries, or helper signatures, the cleanup is not done yet; treat that as contract leakage, not as a docs-only issue.

### 2026-03-14_13.55.00 and 2026-03-14_14.08.00 QualitySuite winner boundary cleanup and run-settings compat-shim removal

Problem captured:
- Interactive codex profile selection could dump compatibility warnings just by loading an old QualitySuite winner cache, because raw winner payloads and persistence-only metadata were being re-parsed through normal `RunSettings` validation.
- At the same time, `RunSettings.from_dict(...)` was still carrying stale-key and removed-value migration behavior that kept dead configuration interfaces alive longer than their value justified.

Durable decisions:
- Interactive harmonization should only revalidate real `RunSettings` model fields. Persistence metadata such as `bucket1_fixed_behavior_version` is not a live setting and should not be treated like one in the chooser.
- QualitySuite winner files can remain archaeology-friendly, but stale winner caches are disposable. The live loader should ignore stale/invalid caches with one concise warning rather than migrating them forever.
- `RunSettings.from_dict(...)` now represents the live schema only. Call sites that pass mixed `cookimport.json` payloads must filter to `RunSettings.model_fields` first.
- Historical analytics and dashboard continuity is preserved by persisted `run_config_*` artifacts, not by keeping live compatibility shims for old config payloads.

Same-day design correction preserved:
- The earlier cleanup direction was “sanitize old winner payloads forward.” The final rule is stricter and simpler: project to real model fields where needed, and ignore stale winner caches instead of carrying indefinite migration code for them.

Anti-loop note:
- If interactive warning dumps return, inspect `last_run_store.py`, `run_settings_flow.py`, and payload projection boundaries before weakening `RunSettings.from_dict(...)` again.

### 2026-03-13_23.57.23 Bucket 1 fixed-behavior runtime bundle

Source:
- `docs/understandings/2026-03-13_23.57.23-bucket1-fixed-behavior-runtime-bundle.md`

Problem captured:
- Bucket 1 fixed-behavior cleanup had removed some fake settings from the visible surface, but runtime still risked depending on them as if they were live `RunSettings` choices.

Durable decisions:
- Remaining fake settings were removed from live `RunSettings` fields.
- New runs derive those values from `cookimport/config/codex_decision.py:bucket1_fixed_behavior()`.
- New manifests and run-config payloads persist `bucket1_fixed_behavior_version` as metadata rather than pretending matcher/pass-policy seams are operator choices.
- Compatibility remains at the runtime boundary:
  - read-only `RunSettings` properties still expose the effective values,
  - adapter kwargs still let downstream stage/import/benchmark/orchestrator code read the same effective behavior without restoring the old settings surface.
- Normal CLI help for `stage`, `labelstudio-benchmark`, `labelstudio-import`, and `bench speed-run` should stay free of Bucket 1 knobs; old payload keys are retired/ignored rather than revived.

Anti-loop note:
- Do not re-add fixed-behavior fields to the live schema just because some downstream code still wants to read the effective value. Keep that compatibility at the runtime adapter/property layer.

### 2026-03-14_07.34.29, 2026-03-14_07.37.14, 2026-03-14_07.39.01, and 2026-03-14_07.57.44 surface ownership, chooser seams, and post-bucket projections

Sources:
- `docs/understandings/2026-03-14_07.34.29-bucket2-surface-ownership.md`
- `docs/understandings/2026-03-14_07.37.14-interactive-recipe-pipeline-choice-boundary.md`
- `docs/understandings/2026-03-14_07.39.01-run-settings-plan-boundaries-after-buckets.md`
- `docs/understandings/2026-03-14_07.57.44-run-settings-product-contract-surfaces.md`

Problem captured:
- The March 14 follow-on cleanup made it easy to confuse “hidden in `RunSettings` UI metadata” with “fully internalized,” and the interactive recipe-pipeline flow still had multiple places where selected settings could be rewritten back to defaults.

Durable decisions:
- Bucket 2 ownership is split across three surfaces:
  - `cookimport/config/run_settings.py` surface metadata,
  - handwritten CLI/help/interactive menu code in `cookimport/cli.py`,
  - analytics/dashboard summary fallbacks that must reuse `summarize_run_config_payload(...)` instead of rolling their own public story.
- Interactive recipe-pipeline choice has two seams that both have to preserve the selected value:
  - top-tier chooser harmonization in `cookimport/cli_ui/run_settings_flow.py`,
  - paired single-offline benchmark planning in `cookimport/cli.py:_interactive_single_offline_variants`.
- Post-Bucket-2 run-settings cleanup is intentionally three-projection, not one “public” dump:
  - `operator` for ordinary day-to-day summaries,
  - `benchmark_lab` for benchmark-visible tuning/model override surfaces,
  - `raw/full` for persistence and reproducibility artifacts.
- March 13 plan ownership stayed split on purpose:
  - Bucket 1 owns retired/fixed-behavior work,
  - Bucket 2 owns internalization,
  - the product-contract plan starts only after those buckets land and focuses on presentation/help/docs/manifests/analytics.
- Remaining leak worth remembering:
  - some helper signatures in `cookimport/labelstudio/ingest.py` still accept long settings-shaped argument lists for compatibility, so not every surface had yet converged onto the smaller projections.

Anti-loop note:
- If a field disappears from `run_settings_ui_specs()` but still shows up in CLI help, dashboard summaries, or paired benchmark behavior, treat that as unfinished contract cleanup, not as a documentation nit.

### 2026-03-14_13.49.43 and 2026-03-14_14.08.00 interactive winner-warning dump and strict live-schema boundary

Sources:
- `docs/understandings/2026-03-14_13.49.43-interactive-pipeline-warning-dump-source.md`
- `docs/understandings/2026-03-14_14.08.00-run-settings-compat-boundaries.md`

Problem captured:
- Interactive `Recipe pipeline for this run?` noise looked like a chooser/menu bug, and compatibility cleanup risked blurring live settings ingestion with persisted analytics/history reading.

Durable decisions:
- The warning dump came from compatibility logging while loading and re-harmonizing saved QualitySuite winner settings, not from the menu renderer itself.
- The active fix landed in two parts:
  - chooser-time revalidation now projects back to real model fields so `bucket1_fixed_behavior_version` does not leak into warnings,
  - stale winner caches are treated as disposable and ignored instead of being migrated forever.
- `RunSettings.from_dict(...)` is now the live-schema loader only.
- Call sites that pass mixed app settings into `RunSettings.from_dict(...)` must filter to `RunSettings.model_fields` first.
- Analytics/dashboard continuity is preserved by persisted `run_config_json`, `run_config_hash`, and `run_config_summary` artifacts, which means old charts can survive even if stale live config files stop loading.

Anti-loop note:
- If warning dumps or unknown-key tolerance pressure return, inspect mixed-payload filtering and winner-cache boundaries first. Do not weaken `RunSettings.from_dict(...)` just to keep stale caches alive.

### 2026-03-15_15.44.51 CLI prompt-export dead-code removal

Source:
- `docs/understandings/2026-03-15_15.44.51-cli-prompt-export-dead-code-removal.md`

Problem captured:
- `cookimport/cli.py` still carried legacy prompt-export compatibility wrappers even though real execution had already returned immediately into `cookimport/llm/prompt_artifacts.py`.

Durable decisions:
- Remove the dead CLI helper body and compatibility wrapper rather than maintaining a second false editing target.
- Call `llm_prompt_artifacts.build_codex_farm_prompt_response_log(...)` directly from CLI callsites.
- When tests need prompt-export coverage, point them at `cookimport/llm/prompt_artifacts.py` instead of resurrecting CLI-private helpers.

Anti-loop note:
- If prompt artifact behavior drifts, inspect `cookimport/llm/prompt_artifacts.py` first. Do not reintroduce CLI wrapper layers just to make the call graph look familiar.
