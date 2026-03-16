---
summary: "CLI architecture/build/fix-attempt log used to avoid repeating failed paths."
read_when:
  - When troubleshooting CLI behavior and you think "we are going in circles on this"
  - When doing multi-turn fixes and you need prior architecture/build/fix attempts
---
# CLI Build and Fix Log

This file is the anti-loop log for CLI work. It now keeps only notes for surfaces that still exist in the current CLI.

### 2026-03-16_15.07.07 interactive chooser versus persistent Settings gap

Preserved finding:
- the interactive CLI now has two different settings surfaces, and they are easy to conflate during refactor follow-through

Current rule:
- treat `choose_run_settings(...)` as the refactor-aware top-tier surface for import and benchmark flows
- treat the persistent `Settings` menu as a narrower global-default editor, not the full product settings surface
- if an operator setting seems "missing" interactively, first decide whether it belongs in the per-run chooser or the persistent Settings screen before adding a third place to edit it

Known current gap:
- the persistent Settings screen still does not expose several ordinary operator settings now documented elsewhere, including `pdf_ocr_policy`, `llm_tags_pipeline`, `tag_catalog_json`, and Codex path/context defaults

Anti-loop note:
- do not assume that a setting appearing in `RunSettings` or top-tier chooser flows automatically means the persistent Settings screen already edits it

### 2026-03-15_23.20.00 retained surface only

Cleanup rule:
- Keep anti-loop notes only for features that still exist in `cookimport/cli.py` or `cookimport/cli_ui/run_settings_flow.py`.
- Delete merged task/spec history for removed chooser variants, removed command surfaces, and dead helper layers instead of archiving them forever here.

### 2026-03-06_19.07.00 interactive top-tier chooser source of truth

Preserved finding:
- The interactive chooser is easy to misremember because older docs talked about separate saved profiles and editor-first flows.

Current rule:
- `choose_run_settings(...)` in `cookimport/cli_ui/run_settings_flow.py` is the source of truth.
- The chooser now resolves exactly two top-tier profile families:
  - `vanilla`: deterministic top-tier contract.
  - `codexfarm`: quality-suite winner settings when available, otherwise built-in codex top-tier.
- The old `preferred format` profile is gone and should not be re-documented.

### 2026-03-06_00.30.31 single-profile benchmark terminal noise suppression

Preserved finding:
- Shared single-profile benchmark status became unreadable when codex decision banners and recoverable warnings wrote directly into the PTY.

Current rule:
- `_print_codex_decision(...)` is suppressed when benchmark summary suppression is active.
- Recoverable codex-farm partial-output failures should collapse into one short shared progress update, not multiline warning spam.

### 2026-03-03_23.30.00 selected-matched benchmark mode

Preserved finding:
- Interactive benchmark needed a middle path between one-book single-offline and all matched books.

Current rule:
- The benchmark menu includes `Single config, selected matched sets: Pick which matched books to run`.
- That path stays single-profile only: one config per selected target, canonical-text eval, no all-method expansion.

### 2026-03-02_23.01.36 dashboard generation returns to menu

Preserved finding:
- Interactive dashboard generation felt broken because it completed and immediately redrew the menu.

Current rule:
- Interactive dashboard generation always calls `stats_dashboard(..., open_browser=False)` and then returns to the main menu.
- There is no interactive browser-open prompt anymore.

### 2026-02-28_09.26.29 codex model picker contract

Preserved finding:
- Free-text model entry drifted from Codex Farm's real model surface.

Current rule:
- Shared chooser model discovery comes from `codex-farm models list --json`.
- The picker still supports `Pipeline default`, `Keep current override`, discovered models, and a custom fallback path.
- Reasoning-effort choices should stay aligned to the selected model's supported efforts when that metadata exists.

### 2026-02-28_03.59.43 split conversion progress contract

Preserved finding:
- Benchmark split conversion used inconsistent counter wording and leaked non-RunSettings payload keys into subprocess workers.

Current rule:
- Split progress starts at `Running split conversion... task 0/N` and keeps `task X/Y` wording throughout.
- Split worker subprocesses get RunSettings-only payloads; report metadata stays in persisted artifacts, not worker config blobs.

### 2026-02-28_02.08.45 all-method worker preflight

Preserved finding:
- Restricted runtimes made all-method startup look broken when process-pool creation failed and noisy fallback wording followed.

Current rule:
- All-method startup probes worker availability first.
- When process workers are unavailable, the runner chooses the supported execution path directly instead of pretending something degraded mid-run.

### 2026-02-22_22.30.58 interactive back-navigation contract

Preserved finding:
- Back navigation drifted whenever flows bypassed shared prompt helpers.

Current rule:
- Menu prompts go through `_menu_select()` and use `Esc` for one-level back.
- Typed prompts go through `_prompt_text`, `_prompt_confirm`, or `_prompt_password`, which merge an `Esc` binding into Questionary's prompt session.
- Freeform segment sizing uses `_prompt_freeform_segment_settings(...)` so `Esc` walks back field-by-field instead of dumping the user to the main menu.

### 2026-02-15_22.44.43 interactive main-menu loop contract

Preserved finding:
- Successful interactive branches used to exit the whole session by accident.

Current rule:
- Completed interactive flows must `continue` back to the main menu.
- Interactive mode exits only from explicit main-menu exit or a top-level cancel path.

### 2026-02-15_23.03.59 menu numbering source

Preserved finding:
- Shortcut numbering and keyboard behavior drift whenever a select prompt bypasses the shared menu helper.

Current rule:
- Interactive select menus should route through `_menu_select()` in `cookimport/cli.py`.
- That helper owns shortcut numbering, explicit shortcut labels, and the shared `Esc` contract.

### 2026-03-13_22.48.50 run-settings public/internal/retired split

Preserved finding:
- CLI docs and summaries kept leaking retired or internal settings back into the public operator surface.

Current rule:
- Public operator docs should focus on the smaller current run-settings contract.
- Internal parser/OCR/scoring knobs may still load from saved payloads and hidden flags, but they are not normal operator documentation.
- `table_extraction` is retired; new runs always extract tables, and docs should not advertise `--table-extraction` as a live feature.

### 2026-03-14_14.08.00 winner cache boundary

Preserved finding:
- Old quality-suite winner payloads created noisy warning dumps and tempted the CLI into acting like stale schemas were durable contracts.

Current rule:
- Quality-suite winner settings are a disposable cache.
- Interactive loading should harmonize only real `RunSettings` fields and ignore stale winner payloads with one concise warning.

### 2026-03-15_15.44.51 removed surface stays removed

Preserved finding:
- Historical docs kept trying to preserve dead CLI seams after the owning feature was deleted.

Current rule:
- If a CLI surface has been removed from the current code, delete its README/log notes instead of archiving them forever in this file.
