---
summary: "CLI architecture/build/fix-attempt log used to avoid repeating failed paths."
read_when:
  - When troubleshooting CLI behavior and you think "we are going in circles on this"
  - When doing multi-turn fixes and you need prior architecture/build/fix attempts
---
# CLI Build and Fix Log

This file is the anti-loop log for CLI work. Read it before retrying approaches that may already have failed.

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

### 2026-02-20_13.20.47 interactive EPUB race routing contract

Merged source file:
- `docs/understandings/2026-02-20_13.20.47-interactive-epub-race-routing.md`

Preserved rules:
- Keep EPUB race as a main-menu action (not Settings).
- Show it only when top-level `data/input` discovery finds at least one `.epub`.
- Reuse existing command behavior (`race_epub_extractors(...)`) instead of cloning scoring/report code in interactive mode.
- Interactive prompt scope should remain menu concerns only (file/output/candidates/overwrite), then return to main menu regardless of success/failure.

Anti-loop note:
- If interactive race behavior drifts from `cookimport epub race`, route interactive branch back to the shared command function instead of patching two separate implementations.

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

### 2026-02-20_13.21.49 - interactive EPUB race menu

Source task file:
- `docs/tasks/2026-02-20_13.21.49 - interactive-epub-race-menu.md`

Problem captured:
- `cookimport epub race` existed, but interactive mode had no in-menu route to run it.

Behavior contract preserved:
- Add top-level interactive menu action for EPUB race when top-level `data/input` has `.epub` files.
- Prompt for file/output/candidates in interactive flow.
- Reuse shared `race_epub_extractors(...)` behavior instead of cloning logic.
- Return to main menu after execution.

Verification and evidence preserved:
- Recorded command:
  - `source .venv/bin/activate && pytest -q tests/test_labelstudio_benchmark_helpers.py tests/test_c3imp_interactive_menu.py`
- Recorded result: `37 passed`.

Constraints and anti-loop notes:
- Keep race visibility scoped to top-level EPUB discovery behavior used by interactive mode.
- Do not fork race scoring/report code inside interactive path.

Rollback path preserved:
- Remove `_interactive_epub_race(...)` and corresponding menu branch + tests/docs.

### 2026-02-22_10.14.15 - interactive EPUB race default output root

Source task file:
- `docs/tasks/2026-02-22_10.14.15 - epub-race-default-output-root.md`

Problem captured:
- Interactive race defaulted to `/tmp/epub-race/<book>`, which was easy to lose and hard to find.

Behavior contract preserved:
- Interactive race default output root moved to:
  - `data/output/EPUBextractorRace/<book_stem>`
- Prompt/custom output/candidate/overwrite behavior otherwise unchanged.

Verification and evidence preserved:
- Recorded command:
  - `source .venv/bin/activate && pytest -q tests/test_labelstudio_benchmark_helpers.py -k interactive_epub_race`
- Recorded result: `1 passed, 33 deselected`.

Constraint preserved:
- Scope change to interactive default only; direct `cookimport epub race --out` semantics unchanged.

Rollback path preserved:
- Restore previous interactive default root (`/tmp/epub-race/<book_stem>`) and revert related docs/test assertions.

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
