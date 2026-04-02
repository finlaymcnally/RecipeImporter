---
summary: "CLI architecture/build/fix-attempt log used to avoid repeating failed paths."
read_when:
  - When troubleshooting CLI behavior and you think "we are going in circles on this"
  - When doing multi-turn fixes and you need prior architecture/build/fix attempts
---
# CLI Build and Fix Log

This file is the anti-loop log for CLI work. It now keeps only notes for surfaces that still exist in the current CLI.

### 2026-03-21 shared progress ETA reset

Preserved finding:
- the shared spinner and saved benchmark sampler could inherit avg-per-task timing from the previous structured stage whenever the next stage reused the same `task X/Y` counter shape

Current rule:
- clear structured rate/ETA samples whenever `stage_label` changes
- do this in both the live spinner path and the single-profile dashboard sampler
- for structured parallel stages, bootstrap ETA should use active/configured worker-wave math instead of treating the remaining work as fully serial

Anti-loop note:
- if a new stage opens with a cartoonish `avg .../task` before it has produced any timing of its own, inspect sampler reset and stage labels before changing stage emitters

### 2026-03-20 prompt-target count preservation and runtime-stage ordering

Preserved finding:
- interactive Codex prompt-target choices were easy to misapply because benchmark prompts asked for counts in a non-runtime order and adapter plumbing could drop the selected values before the live run config was built

Current rule:
- interactive benchmark Codex counts are asked in runtime order: `line_role`, `recipe`
- stage/import and benchmark adapters must preserve `recipe_prompt_target_count` and `line_role_prompt_target_count` into live `RunSettings`
- `recipe_prompt_target_count` now means requested recipe shard count, not preferred worker-session count

Anti-loop note:
- if an operator-picked `10 / 5 / 5` run executes as `5 / 5 / 5`, fix the adapter/chooser seam before retuning stage planners

### 2026-03-16_15.07.07 interactive chooser versus persistent Settings gap

Preserved finding:
- the interactive CLI now has two different settings surfaces, and they are easy to conflate during refactor follow-through

Current rule:
- treat `choose_run_settings(...)` as the refactor-aware top-tier surface for import and benchmark flows
- treat the persistent `Settings` menu as a narrower global-default editor, not the full product settings surface
- if an operator setting seems "missing" interactively, first decide whether it belongs in the per-run chooser or the persistent Settings screen before adding a third place to edit it

Anti-loop note:
- do not assume that a setting appearing in `RunSettings` or top-tier chooser flows automatically means the persistent Settings screen should also expose it
- do not expose block-labelling toggles in interactive import; that would create a fake menu for fields the stage adapters do not carry

### 2026-03-16_16.45.16 and 2026-03-16_16.53.38 workflow-first Codex submenu

Preserved finding:
- interactive benchmark/import setup was drifting into separate prompt styles and fake surface symmetry

Current rule:
- ask one top-level workflow question first (`Vanilla / deterministic only` vs `CodexFarm`)
- if CodexFarm is chosen, reuse one explicit yes/no Codex submenu rather than separate checkbox/select hybrids
- keep the submenu flow-scoped:
  - benchmark exposes recipe correction, block labelling, and knowledge harvest
  - import exposes recipe correction and knowledge harvest only

Anti-loop note:
- if import and benchmark need different runtime fields, share the submenu mechanics but not the exact option list

### 2026-03-06_19.07.00 interactive top-tier chooser source of truth

Preserved finding:
- The interactive chooser is easy to misremember because older docs talked about separate saved profiles and editor-first flows.

Current rule:
- `choose_run_settings(...)` in `cookimport/cli_ui/run_settings_flow.py` is the source of truth.
- The chooser now resolves exactly two top-tier profile families:
  - `vanilla`: deterministic top-tier contract.
  - `codex-exec`: quality-suite winner settings when available, otherwise built-in codex top-tier.

### 2026-03-06_00.30.31 single-profile benchmark terminal noise suppression

Preserved finding:
- Shared single-profile benchmark status became unreadable when codex decision banners and recoverable warnings wrote directly into the PTY.

Current rule:
- `_print_codex_decision(...)` is suppressed when benchmark summary suppression is active.
- Recoverable codex-farm partial-output failures should collapse into one short shared progress update, not multiline warning spam.

### 2026-03-03_23.30.00 selected-matched benchmark mode

Preserved finding:
- Interactive benchmark needed a middle path between one-book single-book and all matched books.

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
- Interactive select menus should route through `_menu_select()` in `cookimport/cli_support/interactive.py`.
- That helper owns shortcut numbering, explicit shortcut labels, and the shared `Esc` contract.

### 2026-03-13_22.48.50 run-settings public/internal split

Preserved finding:
- CLI docs and summaries kept leaking internal settings back into the public operator surface.

Current rule:
- Public operator docs should focus on the smaller current run-settings contract.
- Internal parser/OCR/scoring knobs may still load from saved payloads and hidden flags, but they are not normal operator documentation.

### 2026-03-14_14.08.00 winner cache boundary

Preserved finding:
- Old quality-suite winner payloads created noisy warning dumps and tempted the CLI into acting like stale schemas were durable contracts.

Current rule:
- Quality-suite winner settings are a disposable cache.
- Interactive loading should harmonize only real `RunSettings` fields and ignore stale winner payloads with one concise warning.

### 2026-03-16_17.50.43 and 2026-03-16_18.26.12 shared CodexFarm submenu everywhere

Preserved finding:
- interactive CodexFarm process selection kept drifting into multiple prompt styles, especially for all-method benchmark flows

Current rule:
- use one shared single-screen submenu everywhere the interactive CLI exposes benchmark/import Codex choices
- the submenu owns recipe / line-role / knowledge surface selection, plus the shared model/reasoning override flow
- all-method benchmark should honor the exact selected Codex surfaces; the old "include codex permutations" wording is too vague because the builder already inherits the full benchmark Codex contract

Anti-loop note:
- if a benchmark path starts adding a separate yes/no Codex prompt again, it is probably bypassing the shared chooser instead of extending it

### 2026-03-16_18.12.18 benchmark-only menu seams

Preserved finding:
- benchmark gold/source picking is easy to confuse with the shared run-settings chooser

Current rule:
- shared workflow/Codex choices belong in `choose_run_settings(...)`
- benchmark-only source/gold selection belongs in the benchmark helpers under `cookimport/cli_support/`

Anti-loop note:
- if an interactive tweak should affect import and benchmark equally, it probably belongs in `run_settings_flow.py`, not in benchmark-only helpers

### 2026-03-16_18.14.37 concise book labels across benchmark pickers

Preserved finding:
- benchmark menus were showing the same book identity in different formats, which made selected-matched flows harder to scan

Current rule:
- reuse one concise book label style across interactive benchmark pickers
- keep picker-label cleanup scoped to operator-facing menus; do not mutate report payload fields or logging identity just to match menu wording

### 2026-03-17_16.18.00 shared per-surface Codex chooser seam

Preserved finding:
- import, benchmark, and all-method flows can drift apart if they each grow their own Codex surface picker behavior

Current rule:
- the shared seam is `choose_interactive_codex_surfaces(...)` in `cookimport/cli_ui/run_settings_flow.py`
- if a per-surface Codex toggle should exist everywhere, add it on that shared chooser boundary
- benchmark helpers should keep source/gold selection and other benchmark-only UI local, but they should not grow a second per-surface Codex menu contract

Anti-loop note:
- if a benchmark-only prompt seems to duplicate one of the shared recipe / line-role / knowledge toggles, it probably belongs in the shared chooser instead

### 2026-03-17 structured stage-progress payloads and generic running rows

Preserved finding:
- benchmark/import status panels were only as informative as the latest plain string, and line-role/knowledge worker activity could collapse back to one stale line.

Current rule:
- the shared CLI progress seam accepts the repo-owned serialized `stage_progress` payload in addition to plain strings
- plain `task X/Y` messages still work, but the spinner now infers `stage:` / `progress:` rows from them
- generic `task X/Y | running N` messages expand to `active workers: N` plus worker rows; this is no longer limited to one old codex-farm message shape
- recipe shard progress should stay honest about the seam it can observe: outer worker-bucket state is real, inner shard-by-shard Codex progress inside one classic worker assignment is not
- legacy codex-farm `run=... queued=... running=...` stderr snapshots are progress noise and should be dropped at the runner boundary instead of surfaced as ordinary stderr
- processing timeseries artifacts should preserve structured progress metadata when the emitter provides it

Anti-loop note:
- if a long-running stage still looks blank, fix the stage emitter to publish structured progress rather than adding another spinner-only special case

### 2026-03-18 interactive shard-count selection is split by surface on purpose

Preserved finding:
- the repo briefly moved toward "all prompt counts are literal hard overrides," but knowledge reliability proved that one shared policy was wrong

Current rule:
- the interactive chooser still asks for recipe / line-role / knowledge prompt targets in one place
- recipe and line-role honor those values as literal shard-count overrides
- knowledge records the operator request but may exceed it when hard chunk, char, locality, or table caps would otherwise be violated; the runtime should explain that mismatch in manifests/reports instead of silently pretending the request was met

Anti-loop note:
- if knowledge uses more shards than the interactive picker requested, do not start by debugging the chooser. Check whether the runtime is correctly obeying knowledge safety caps.
