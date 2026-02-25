---
summary: "Label Studio architecture/build/fix-attempt log used to avoid repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on Label Studio behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need historical architecture versions, builds, and failed fix attempts before trying another change
---

# Label Studio Log: Architecture, Builds, and Fix Attempts

Read this file if work is going in multi-turn circles, or when someone says "we are going in circles on this."

This log preserves prior architecture versions, build decisions, and fix attempts so we do not repeat dead ends.

## Historical Timeline (What Changed, in Order)

This section preserves chronology from the original docs and git history to avoid repeating prior loops.

### 2026-01-31 baseline documentation refactor

- Label Studio docs consolidated around chunk-based benchmark workflow.

### 2026-02-02 canonical-block workflow introduced

- canonical block scope added as a parallel workflow (not replacement for pipeline scope),
- stable block IDs introduced,
- canonical export/eval scaffolding and tests added,
- task scope persistence added to prevent accidental cross-scope resume.

### 2026-02-10 freeform workflow introduced

- freeform span scope added (`freeform-spans`),
- segment-based task strategy adopted (`segment_blocks` + `segment_overlap`),
- offset-preserving text rendering adopted (`pre-wrap`),
- export contract for spans + segment manifest added,
- guided benchmark/gold discovery added,
- default project name dedupe behavior clarified (`stem`, `-1`, `-2`, ...).

### 2026-02-10 taxonomy and routing refinements

- freeform taxonomy moved to `TIP`/`NOTES`/`VARIANT` (+ structural labels and `OTHER`),
- scope-routing guardrails across import/export/eval were added/documented.

### 2026-02-11 hardening and observability wave

From 2026-02-11 discovery docs:

- explicit write-consent gate enforced,
- benchmark/import progress expanded to post-merge phases,
- split-job merge reindex fix added,
- benchmark writes processed outputs for upload/review,
- interactive benchmark gained eval-only fallback,
- freeform eval gained `app_aligned`, `classification_only`, and `force-source-match` options,
- interactive export menu + scope prompts polished,
- benchmark output defaults moved to golden-root patterns.

### 2026-02-15 interactive Label Studio UX simplification pass

Merged sources:
- `2026-02-15_21.35.47-interactive-labelstudio-overwrite-rule.md` (former understanding file)
- `2026-02-15_21.52.54-interactive-labelstudio-import-auto-upload.md` (former understanding file)
- `2026-02-15_22.00.23-interactive-labelstudio-export-project-picker.md` (former understanding file)
- `docs/tasks/2026-02-15_21.35.54 - interactive-labelstudio-import-auto-overwrite.md`
- `docs/tasks/2026-02-15_22.00.23 - interactive-labelstudio-export-project-picker.md`

Preserved decisions:
- Interactive import no longer asks for upload confirmation; it uploads immediately after scope/options + credential resolution.
- Interactive import no longer asks overwrite/resume; it always overwrites resolved project names and does not resume.
- Interactive export resolves credentials first, attempts remote project-title discovery, shows a picker, then asks for export scope.
- Interactive credential prompts are one-time by default because prompted URL/API key values persist in `cookimport.json` for later interactive runs.
- If project discovery fails or no projects are available, flow degrades to manual project-name entry instead of failing.

Task-spec evidence preserved (timestamp order):

- `2026-02-15_21.35.54` import auto-overwrite:
  - acceptance: no overwrite/resume prompt in interactive import; always `overwrite=True` and `resume=False`.
  - constraints: keep non-interactive `--overwrite/--resume` semantics unchanged.
  - regression test: `test_interactive_labelstudio_import_forces_overwrite_without_prompt` (`tests/test_labelstudio_benchmark_helpers.py`), with fail-before and pass-after recorded in the task file.
- `2026-02-15_22.00.23` export project picker:
  - acceptance: resolve credentials first, fetch project names for picker, keep manual-entry fallback, and preserve existing export routing.
  - constraints: preserve env-var credential behavior and back-navigation semantics (`BACK_ACTION`).
  - verification command recorded:
    - `. .venv/bin/activate && pytest -q tests/test_labelstudio_benchmark_helpers.py -k "interactive_labelstudio_export_routes_to_export_command or select_export_project_name"`
  - recorded result: `3 passed, 16 deselected`.

### 2026-02-15_22.27.19 -> 2026-02-15_23.20.35 interactive export prompt/type/scope refinement

Merged sources:
- `2026-02-15_22.27.19-interactive-export-prompt-order.md` (former understanding file)
- `2026-02-15_22.34.31-export-project-type-detection.md` (former understanding file)
- `2026-02-15_23.20.45-interactive-export-uses-detected-project-scope.md` (former understanding file)
- `docs/tasks/2026-02-15_22.27.19 - interactive-export-project-before-scope.md`
- `docs/tasks/2026-02-15_22.34.31 - export-picker-show-project-type.md`
- `docs/tasks/2026-02-15_23.20.35 - interactive-export-auto-scope-from-project-type.md`

Preserved sequence of decisions (timestamp order):

1. `2026-02-15_22.27.19` changed interactive export prompt order to match user intent:
- select/export project first,
- then ask `Export scope` only if still needed.
- Task constraint: keep credential resolution and manual-entry fallback semantics unchanged.
- Task verification focus:
  - fail-before on `interactive_labelstudio_export_selects_project_before_scope`
  - pass-after on export order + routing tests.

2. `2026-02-15_22.34.31` made project picker labels explicit:
- render entries as `<project> [type: <scope>]`.
- detection order chosen to maximize reliability:
  - local `manifest.json` `task_scope` first,
  - Label Studio payload/`label_config` heuristic fallback,
  - `unknown` when unresolved.
- Task verification command recorded:
  - `. .venv/bin/activate && pytest -q tests/test_labelstudio_benchmark_helpers.py -k 'select_export_project_name or interactive_labelstudio_export'`.

3. `2026-02-15_23.20.35` removed redundant scope prompt when type is known:
- project selection now returns both title and detected scope,
- interactive export auto-uses detected `pipeline` / `canonical-blocks` / `freeform-spans`,
- only prompts for scope when type is `unknown` or the user enters a manual project name.
- Recorded regression expectation:
  - `test_interactive_labelstudio_export_routes_to_export_command` asserts no scope prompt when scope is detected.
  - `test_interactive_labelstudio_export_selects_project_before_scope` still validates order in unknown/manual scope cases.

Anti-loop note from this chain:
- Do not reintroduce unconditional `Export scope` prompting after known-type project selection; this is explicitly the behavior users rejected.

### 2026-02-15_22.28.33 -> 2026-02-15_22.45.08 export destination root churn (short-lived, now settled)

Merged source files (former understandings):
- `2026-02-15_22.28.33-labelstudio-export-run-root-reuse.md`
- `2026-02-15_22.33.22-labelstudio-export-timestamped-project-root.md`
- `2026-02-15_22.45.08-labelstudio-export-project-root.md`

Preserved sequence (do not lose this context):
1. Before `22.33.22`, export defaulted to reusing the latest matching manifest run root for the selected project.
- Result: exports were refreshed in-place under older run timestamps.
- Concrete captured example: `SFAHpipe1` export wrote under `data/golden/2026-02-14_01.58.47/.../exports/summary.json` with newer file write-times than the manifest.
2. At `22.33.22`, default changed to always create timestamped project roots (`<output_dir>/<timestamp>/labelstudio/<project_slug>/exports/...`) when `--run-dir` was not supplied.
3. At `22.45.08`, default was simplified again to stable project-slug roots (`<output_dir>/<project_slug>/exports/...`) for both interactive and non-interactive export when `--run-dir` is absent.

Stable current rule:
- `--run-dir` always wins when supplied.
- Without `--run-dir`, default export root is project-slug-based (not reused run root and not fresh timestamp root).
- Manifest lookup still resolves `project_id` and enforces task-scope alignment.

### Abandoned/deferred branch: PDF page box annotation

- rectangle-on-page-images workflow was explored as a do-later idea,
- not part of current code.


## Consolidation Findings (Preserved)

- `labelstudio-benchmark` (CLI) supports both upload and offline `--no-upload` generation paths; true re-score-only of existing prediction runs remains `labelstudio-eval` (and interactive eval-only mode).
- Resume/idempotence is keyed by deterministic task IDs (`chunk_id`/`block_id`/`segment_id`), not Label Studio task IDs.
- Split EPUB/PDF job merges must rebase block indices globally before chunk/task generation; otherwise eval can produce false zero-match results.
- Freeform eval has three layers now: strict metrics, `app_aligned` diagnostics, and `classification_only` diagnostics.
- Current timestamp folders in code use dot-separated time (`%Y-%m-%d_%H.%M.%S`), which previously drifted from some docs.

### 2026-02-20_12.59.26 interactive Label Studio AI flow map

Merged source:
- `docs/understandings/2026-02-20_12.59.26-interactive-labelstudio-ai-flow.md`

Preserved outcomes:
- Interactive main menu now covers both freeform AI entrypoints:
  - prelabel during import,
- Freeform import prompt flow includes segmentation + AI mode selection in one pass.
- Completion summaries should include `prelabel_report.json` when prelabeling is enabled.

Anti-loop note:
- Do not reintroduce "leave interactive mode and run separate command" guidance for normal AI labeling workflows.

### 2026-02-20_13.05.00 prelabel upload fallback wiring map

Merged source:
- `docs/understandings/2026-02-20_13.05.00-labelstudio-prelabel-upload-fallback-map.md`

Preserved rules:
- Prelabel spans are generated during `generate_pred_run_artifacts(...)` before task JSONL write.
- Offset mapping is deterministic from `source_map.blocks[*].segment_start/end` + exact `segment_text`.
- Default upload mode (`annotations`) should auto-fallback to task upload + per-task annotation create when inline annotations are rejected.
- Fallback mapping key is deterministic `segment_id` -> Label Studio `task.id`.

### 2026-02-22_11.50.45 interactive prelabel mode mapping

Merged source:
- `docs/understandings/2026-02-22_11.50.45-interactive-prelabel-mode-mapping.md`

Preserved rule:
- One interactive prelabel mode selector maps directly to `prelabel`, `prelabel_upload_as`, and `prelabel_allow_partial`.
- Keep this mapping aligned with non-interactive CLI flags to avoid mode drift.

### 2026-02-22_12.26.42 Codex stdin/TTY compatibility fix

Merged source:
- `docs/understandings/2026-02-22_12.26.42-prelabel-codex-stdin-tty.md`

Preserved rule:
- Non-interactive prelabel subprocesses must default to `codex exec -`.
- `stdin is not a terminal` in `prelabel_errors.jsonl` usually means interactive `codex` was invoked in a non-TTY subprocess.
- Keep fallback retry (`codex` -> `codex exec -`) for backward compatibility with stale env/config overrides.

### 2026-02-22_12.36.11 interactive progress-callback wiring

Merged source:
- `docs/understandings/2026-02-22_12.36.11-interactive-labelstudio-import-progress-callback.md`

Preserved rule:
- Interactive Label Studio import should pass `progress_callback` through the same helper path as non-interactive flows so long-running prelabel phases surface spinner updates consistently.

### 2026-02-22_12.55.48 spinner task-counter ownership

Merged source:
- `docs/understandings/2026-02-22_12.55.48-spinner-task-counter-wiring.md`

Preserved rule:
- Task counters (`task X/Y`) belong in ingest runtime loops (where totals are known), not CLI wrapper-only logic.
- CLI should render callback messages; ingest owns message content.

### 2026-02-22_13.15.12 Codex model + token-usage propagation

Merged source:
- `docs/understandings/2026-02-22_13.15.12-prelabel-codex-model-and-token-usage.md`

Preserved outcomes:
- Model selection must propagate through prelabel runtime provider construction, not only prompt/UI layers.
- Effective command (`codex exec -` plus optional `--model`) should be resolved centrally and reported in run artifacts.
- Token usage remains provider-level aggregation (`usage_summary`) and is always enabled for prelabel runs.

### 2026-02-22_13.50.20 freeform prelabel prompt/context mechanics

Merged source:
- `docs/understandings/2026-02-22_13.50.20-freeform-prelabel-prompt-and-context.md`

Preserved map:
- Prompt template source is `_build_prompt(...)` in `cookimport/labelstudio/prelabel.py`.
- One subprocess call labels one segment task; no cross-task conversation context.
- Segment context window is controlled by `segment_blocks` + `segment_overlap`.
- Apparent statefulness usually comes from prompt cache keys, not in-process model memory.

### 2026-02-22_13.56.33 freeform taxonomy wiring

Merged source:
- `docs/understandings/2026-02-22_13.56.33-freeform-label-taxonomy-wiring.md`

Preserved rule:
- Canonical label names and alias normalization are centralized in `label_config_freeform.py`.
- Prelabel, export/eval label normalization, and interactive project-type inference should all reuse that shared normalization logic.

### 2026-02-20_21.45.00 - freeform prelabel baseline

- `labelstudio-import --task-scope freeform-spans --prelabel` can generate/upload completed annotations.
- Inline annotation rejection must trigger fallback to task upload followed by per-task annotation creation.
- Offset correctness is tied to exact `segment_text` and `source_map.blocks` positions.
- Codex output parsing must handle JSON wrapped in prose.
- Note: an additive “decorate/augment existing projects” mode was prototyped briefly and then removed on 2026-02-22; ignore old references to `labelstudio-decorate`.

### 2026-02-22_11.51.30 - interactive prelabel mode selector (including allow-partial)

Source task file:
- `docs/tasks/2026-02-22_11.51.30 - interactive-prelabel-mode-partial.md`

Problem captured:
- Interactive freeform import exposed only yes/no prelabel, hiding partial-failure upload mode.

Behavior contract preserved:
- Interactive freeform import uses a select menu with at least:
  - no prelabel,
  - strict annotation prelabel,
  - allow-partial annotation prelabel.
- Mode selection must route to `run_labelstudio_import(...)` via `prelabel`, `prelabel_upload_as`, and `prelabel_allow_partial`.

Verification and evidence preserved:
- Recorded tests assert interactive flow forwards:
  - `prelabel=True`
  - `prelabel_upload_as='annotations'`
  - `prelabel_allow_partial=True`
- Recorded command anchors:
  - `pytest -q tests/test_labelstudio_benchmark_helpers.py -k interactive_labelstudio_freeform_scope_routes_to_freeform_import`
  - `pytest -q tests/test_labelstudio_benchmark_helpers.py -k interactive_labelstudio_import_forces_overwrite_without_prompt`

Constraint preserved:
- Keep `_menu_select` usage so numeric shortcut/back navigation behavior remains consistent.

Rollback path preserved:
- Revert interactive prelabel prompt block and related tests/docs.

### 2026-02-22_12.25.10 - non-interactive Codex default for prelabel

Source task file:
- `docs/tasks/2026-02-22_12.25.10 - prelabel-codex-exec-default.md`

Problem captured:
- Prelabel runs could produce `success_count=0` due to plain `codex` in subprocess mode (`stdin is not a terminal`).

Behavior contract preserved:
- Default command resolves to `codex exec -`.
- Plain `codex` overrides auto-retry to `codex exec -` only when TTY error is detected.
- Override surfaces remain available (`--codex-cmd`, `COOKIMPORT_CODEX_CMD`).

Verification and evidence preserved:
- Recorded test anchors:
  - `pytest -q tests/test_labelstudio_prelabel.py -k codex`
  - `pytest -q tests/test_labelstudio_prelabel.py -k prelabel_freeform_task_uses_block_offsets_and_exact_text`
- Recorded assertions include default command value and retry path behavior.

Constraint preserved:
- Fallback rewrite is intentionally limited to plain-`codex` commands; do not rewrite arbitrary custom command lines.

Rollback path preserved:
- Revert fallback/default command changes in `cookimport/labelstudio/prelabel.py` and matching tests/docs.

### 2026-02-22_12.36.08 - interactive Label Studio spinner/progress callback wiring

Source task file:
- `docs/tasks/2026-02-22_12.36.08 - interactive-labelstudio-prelabel-spinner.md`

Problem captured:
- Interactive import called `run_labelstudio_import(...)` without progress callback, so long AI prelabel runs showed no live indicator.

Behavior contract preserved:
- Interactive import must pass a callable `progress_callback`.
- Spinner rendering should reuse shared callback/status helper path used by non-interactive `labelstudio-import`.

Verification and evidence preserved:
- Recorded command anchors:
  - `pytest -q tests/test_labelstudio_benchmark_helpers.py -k interactive_labelstudio_import`
  - `pytest -q tests/test_labelstudio_benchmark_helpers.py -k interactive_labelstudio_freeform_scope_routes_to_freeform_import`
- Recorded assertions ensure `progress_callback` is callable in interactive paths.

Constraint preserved:
- Keep status wording style aligned with existing `Label Studio import (...)` spinner text.

Rollback path preserved:
- Revert shared helper usage in `cookimport/cli.py` and callback assertions in tests.

### 2026-02-22_12.55.46 - spinner task X/Y counters for AI labeling

Source task file:
- `docs/tasks/2026-02-22_12.55.46 - spinner-task-progress-counters.md`

Problem captured:
- AI prelabel spinner text showed phase-only status and hid per-task throughput.

Behavior contract preserved:
- Prelabel loop emits `task X/Y` counters.
- Counter shape is normalized as `task X/Y`.

Verification and evidence preserved:
- Recorded command anchors:
  - `pytest -q tests/test_labelstudio_ingest_parallel.py -k prelabel_task_progress`
  - `pytest -q tests/test_labelstudio_benchmark_helpers.py -k interactive_labelstudio_import`
- Recorded evidence includes examples from `task 0/N` through `task N/N`.

Constraints and anti-loop notes:
- Keep callback-driven spinner flow; do not add second indicator systems.
- Counter ownership remains in ingest/runtime loops where totals are known.

Rollback path preserved:
- Revert ingest progress message changes and related tests/docs/conventions updates.

### 2026-02-22_13.56.20 - freeform label taxonomy refresh

Source task file:
- `docs/tasks/2026-02-22_13.56.20 - freeform-label-taxonomy-refresh.md`

Problem captured:
- Older freeform labels (`TIP` / `NOTES` / `VARIANT`) were ambiguous and mismatched desired golden-set taxonomy.

Behavior contract preserved:
- Canonical labels are now:
  - `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `YIELD_LINE`, `TIME_LINE`, `RECIPE_NOTES`, `RECIPE_VARIANT`, `KNOWLEDGE`, `OTHER`
- Label config order must match canonical list.
- Legacy aliases normalize to new names (`TIP`, `NOTES`/`NOTE`, `VARIANT`, `YIELD`, `TIME`, `NARRATIVE`).
- Eval chunk mapping and CLI scope inference must continue to recognize both new and legacy forms.

Verification and evidence preserved:
- Recorded commands:
  - `pip install -e .[dev]`
  - `pytest -q tests/test_labelstudio_freeform.py tests/test_labelstudio_prelabel.py tests/test_labelstudio_benchmark_helpers.py`
- Recorded result: `56 passed, 2 warnings in 1.99s`.

Constraints and anti-loop notes:
- Preserve back-compat through alias normalization instead of dropping legacy labels.
- Keep app-aligned metrics contracts unchanged (structural labels + `OTHER` subset semantics remain).

Rollback path preserved:
- Revert taxonomy mapping changes in freeform label config/eval/CLI and associated test/docs updates.

## 2026-02-22 understanding merge batch (chronological)

### 2026-02-22_14.49.45 freeform prelabel full vs augment prompt contract

Merged source:
- `docs/understandings/2026-02-22_14.49.45-freeform-prelabel-full-vs-augment-prompt-contract.md`

Preserved context:
- Full-mode "label every block" prompting was never compatible with sparse additive behavior.
- Runtime augment/decorate was later removed (2026-02-22), but this remains relevant when evaluating old docs/tests or future additive feature proposals.

### 2026-02-22_15.10.37 file-backed prelabel prompt template loader

Merged source:
- `docs/understandings/2026-02-22_15.10.37-llm-pipelines-prompt-template-loader.md`

Preserved rules:
- Prompt templates are loaded from `llm_pipelines/prompts/*.prompt.md` with placeholder token replacement.
- Loader is mtime-aware; template edits should apply on next render.
- Missing templates intentionally fall back to built-in prompt defaults.

### 2026-02-22_16.13.47 codex model cache vs runtime access

Merged source:
- `docs/understandings/2026-02-22_16.13.47-codex-model-cache-vs-runtime-access.md`

Preserved findings:
- Cached model lists can drift from provider-authorized runtime models for the active account.
- One preflight provider probe before labeling loops reduces repeated task-level failures.
- `turn.failed` provider detail should be preserved in surfaced error output.

### 2026-02-22_16.38.41 codex command vs account resolution

Merged source:
- `docs/understandings/2026-02-22_16.38.41-codex-command-vs-account-resolution.md`

Preserved rules:
- Interactive prelabel should resolve command/home/account without requiring a separate interactive command picker.
- `codex2`-style command names should still receive plain-command `exec -` fallback behavior.
- Showing resolved account identity before expensive prelabel loops is an explicit guardrail.

### 2026-02-22_17.07.31 freeform prelabel CODEX_HOME precedence

Merged source:
- `docs/understandings/2026-02-22_17.07.31-freeform-prelabel-codex-home-override.md`

Preserved rule:
- Default home fallback precedence is `~/.codex` then `~/.codex-alt`; explicit `CODEX_HOME` command wrappers remain the deterministic override path.

### 2026-02-22_17.27.33 freeform span quote resolution contract

Merged source:
- `docs/understandings/2026-02-22_17.27.33-freeform-span-quote-resolution-contract.md`

Preserved rules:
- Span mode uses quote-anchored selections as primary contract.
- Repeated quote strings require `occurrence`; unresolved ambiguity is dropped item-by-item.
- `value.text` remains derived from resolved offsets, never copied from model output.

### 2026-02-22_17.36.48 resume gate for new projects

Merged source:
- `docs/understandings/2026-02-22_17.36.48-labelstudio-resume-gate-for-new-projects.md`

Preserved rules:
- Resume metadata checks only apply to projects that existed before this run.
- Benchmark auto project naming should auto-dedupe on scope mismatch rather than fail immediately.
- Patch anchor for this rule remains `cookimport/labelstudio/ingest.py` with benchmark wiring from `cookimport/cli.py`.

### 2026-02-22_18.55.39 freeform span vs legacy block runtime contract

Merged source:
- `docs/understandings/2026-02-22_18.55.39-freeform-vs-legacy-prelabel-runtime-contract.md`

Preserved differences:
- `span` mode supports partial/multiple highlights per block through quote/offset resolution.
- `block` mode maps block labels to full-block spans and remains intentionally more tolerant.
- Both modes keep strict label normalization, dedupe identical `(label,start,end)` outputs, and task-level fail only when no valid spans survive.

### 2026-02-22_19.00.30 codex prelabel thinking effort injection

Merged source:
- `docs/understandings/2026-02-22_19.00.30-codex-prelabel-thinking-effort-injection.md`

Preserved rules:
- Reasoning effort is a Codex config override (`-c model_reasoning_effort=\"...\"`), not a dedicated top-level CLI flag.
- Injection should be command-aware and additive: resolve command first, then add effort override only when it is not already present.
- Preferred interactive prompt order for freeform prelabel remains:
  - style
  - account display
  - model
  - thinking effort
- Prelabel reporting should include resolved reasoning-effort metadata with command/model/account for reproducibility.

## 2026-02-22 merged task-spec batch from `docs/tasks` (chronological)

### 2026-02-22_14.49.14 refresh freeform prelabel prompt template

Source task file:
- `docs/tasks/2026-02-22_14.49.14 - refresh-freeform-prelabel-prompt.md`

Problem captured:
- Full-mode freeform prelabel instructions needed alignment with `AI-labelling-instructions.md` for better block-level consistency.

Decisions/actions captured:
- Updated `_build_prompt(...)` full-mode template content in `cookimport/labelstudio/prelabel.py`.
- Added tests that assert key full-mode instruction sections.

Verification/evidence preserved:
- Recorded run: `pytest -q tests/test_labelstudio_prelabel.py`
- Recorded result: `12 passed, 2 warnings in 1.35s`.

Rollback path preserved:
- Revert prompt-template branch changes in `cookimport/labelstudio/prelabel.py` and related assertions if quality regresses.

### 2026-02-22_15.10.22 llm_pipelines prompt templates for Label Studio prelabel

Source task file:
- `docs/tasks/2026-02-22_15.10.22 - llm-pipelines-prompt-templates.md`

Problem captured:
- Prompt wording iteration required code edits because text lived inside Python literals.

Decisions/actions captured:
- Moved freeform prelabel prompt text to files under `llm_pipelines/prompts/`.
- Kept runtime placeholder substitution for segment ID, allowed labels, and block payload.
- Added fallback path to built-in templates for missing/empty files.

Verification/evidence preserved:
- Recorded run: `pytest -q tests/test_labelstudio_prelabel.py`
- Recorded result: `13 passed, 2 warnings in 1.42s`.
- Coverage anchor recorded: `test_prelabel_prompt_uses_file_templates`.

### 2026-02-22_16.38.50 interactive prelabel Codex account selection

Source task file:
- `docs/tasks/2026-02-22_16.38.50 - interactive-prelabel-codex2-account-selection.md`

Problem captured:
- Model cache could come from one account while provider runtime used another account/command context.

Decisions/actions captured:
- Removed interactive command-selection prompt; resolve command via config/env defaults.
- Made model/cache/config/account discovery command-aware and `CODEX_HOME` aware.
- Show resolved account email before model selection when available.
- Added `codex2` compatibility for model injection and non-TTY fallback behavior.

Verification/evidence preserved:
- Recorded run:
  - `pytest tests/test_labelstudio_prelabel.py tests/test_labelstudio_benchmark_helpers.py tests/test_labelstudio_ingest_parallel.py -q`
- Recorded result: `62 passed, 2 warnings in 3.38s`.

### 2026-02-22_17.27.33 freeform span granularity mode

Source task file:
- `docs/tasks/2026-02-22_17.27.33 - freeform-span-granularity-mode.md`

Problem captured:
- Legacy block-only prelabels could not represent partial/multiple highlights within a block.

Decisions/actions captured:
- Added `--prelabel-granularity block|span` (default `block`) and interactive style picker text with explicit legacy wording.
- Implemented quote-anchored span-mode parser that supports repeated quotes via `occurrence`.
- Kept block-mode behavior unchanged for backward compatibility.

Verification/evidence preserved:
- Recorded runs:
  - `pytest -q tests/test_labelstudio_prelabel.py tests/test_labelstudio_ingest_parallel.py tests/test_labelstudio_benchmark_helpers.py`
  - `pytest -q tests/test_cli_llm_flags.py`
- Task recorded added/updated files across `prelabel.py`, `ingest.py`, `cli.py`, and associated tests.

Rollback path preserved:
- Runtime toggle back to legacy behavior via `--prelabel-granularity block`.

### 2026-02-22_17.37.19 benchmark resume scope mismatch

Source task file:
- `docs/tasks/2026-02-22_17.37.19 - benchmark-resume-scope-mismatch.md`

Problem captured:
- New benchmark uploads could fail because stale local manifests were checked during resume logic even when a new Label Studio project was created.

Decisions/actions captured:
- Gated resume metadata loading behind `had_existing_project`.
- Added benchmark auto-naming scope-collision fallback (`-1`, `-2`, ...) instead of immediate failure.
- Added regression coverage for new-project + stale-manifest scope mismatch.

Verification/evidence preserved:
- Recorded run:
  - `pytest -q tests/test_labelstudio_ingest_parallel.py tests/test_labelstudio_benchmark_helpers.py`
- Recorded result: `49 passed, 2 warnings in 3.30s`.

### 2026-02-22_18.11.44 labelstudio import processing-time summary

Source task file:
- `docs/tasks/2026-02-22_18.11.44 - labelstudio-import-processing-time-summary.md`

Problem captured:
- Import summaries lacked elapsed runtime, making run auditing harder.

Decisions/actions captured:
- Added elapsed-time measurement around `_run_labelstudio_import_with_status`.
- Printed `Processing time: ...` in interactive and non-interactive summary paths.
- Added one shared duration formatter for consistent output text.

Verification/evidence preserved:
- Recorded run: `pytest -q tests/test_labelstudio_benchmark_helpers.py`
- Recorded result: `39 passed, 2 warnings`.

### 2026-02-22_19.00.14 prelabel Codex thinking-effort picker

Source task file:
- `docs/tasks/2026-02-22_19.00.14 - prelabel-codex-thinking-effort-picker.md`

Problem captured:
- Interactive prelabel model selection had no thinking/reasoning-effort selection, and non-interactive parity flagging was missing.

Decisions/actions captured:
- Added interactive effort picker after model selection with values:
  - `none`
  - `minimal`
  - `low`
  - `medium`
  - `high`
  - `xhigh`
- Added non-interactive flags `--codex-thinking-effort` and alias `--codex-reasoning-effort`.
- Wired effort into provider command construction as additive `model_reasoning_effort` override.
- Ensured prelabel report fields include resolved effort metadata.

Verification/evidence preserved:
- Recorded run:
  - `pytest tests/test_labelstudio_prelabel.py tests/test_labelstudio_benchmark_helpers.py tests/test_labelstudio_ingest_parallel.py -q`
- Recorded result: `73 passed, 2 warnings`.

Constraints and rollback preserved:
- Keep command-aware resolution (`COOKIMPORT_CODEX_CMD` / `CODEX_HOME`) and avoid duplicate override injection.
- Rollback path is revert in `prelabel.py`, `ingest.py`, `cli.py`, and associated tests/docs.

## 2026-02-23 archival merge batch from `docs/understandings` (Label Studio)

### 2026-02-22_19.03.31 freeform block-vs-span export differences

Merged source:
- `docs/understandings/2026-02-22_19.03.31-freeform-block-vs-span-export-differences.md`

Preserved finding:
- Divergent export distributions between two freeform runs are expected when `prelabel_granularity` differs (`block` vs `span`), even with identical segmentation settings.

Preserved evidence:
- Compared pair had equal segmentation shape (`42` segments; `1471` unique source blocks in manifests).
- Span-row counts differed (`1635` block-mode vs `1355` span-mode), as did unique touched blocks (`1440` vs `1201`).
- Span-mode introduced sub-block coverage (`7.8%`), block-mode remained full-block only.

Anti-loop note:
- Do not treat this pattern as an export-pipeline bug without first checking prelabel granularity.

### 2026-02-22_19.06.24 Codex prelabel thinking-effort injection

Merged source:
- `docs/understandings/2026-02-22_19.06.24-codex-prelabel-thinking-effort-injection.md`

Preserved rule:
- Thinking effort is a command/config override (`model_reasoning_effort`) and should be injected only after command resolution, only when command text does not already set it.

### 2026-02-22_19.35.04 freeform context/focus task-count math

Merged source:
- `docs/understandings/2026-02-22_19.35.04-freeform-context-focus-task-count-math.md`

Preserved finding:
- Task count tuning is overlap math, not parser variance: `step = segment_blocks - segment_overlap`.
- Context-vs-focus requires parser/runtime filtering as the enforcement layer, not prompt wording alone.

### 2026-02-22_19.48.08 overlap resolution and prompt gating

Merged source:
- `docs/understandings/2026-02-22_19.48.08-freeform-focus-overlap-resolution-and-prompt-gating.md`

Preserved rule:
- Keep requested overlap and effective overlap distinct and persisted; focus filtering applies in block parsing, quote parsing, and absolute-span validation.

### 2026-02-22_19.50.52 prelabel prompt-log artifact contract

Merged source:
- `docs/understandings/2026-02-22_19.50.52-prelabel-prompt-log-contract.md`

Preserved rule:
- Run-level `prelabel_prompt_log.md` must be emitted and discoverable via `prelabel_report.json`, run `manifest.json`, and `run_manifest.json`.

### 2026-02-22_22.53.30 focus-overlap gap floor

Merged source:
- `docs/understandings/2026-02-22_22.53.30-freeform-focus-overlap-gap-floor.md`

Preserved rule:
- Focus windows can leave deterministic unlabeled gaps unless overlap floor is enforced:
  - `segment_overlap_effective >= segment_blocks - segment_focus_blocks`

### 2026-02-22_23.01.05 span prompt focus markers

Merged source:
- `docs/understandings/2026-02-22_23.01.05-freeform-span-prompt-focus-markers.md`

Preserved rule:
- Default span prompt should use one markerized block stream and avoid duplicated focus/context payload text.

### 2026-02-22_23.15.57 freeform prelabel parallelism contract

Merged source:
- `docs/understandings/2026-02-22_23.15.57-freeform-prelabel-parallelism-contract.md`

Preserved rule:
- Task-level provider calls are safe to parallelize; keep deterministic task indexing and thread-safe usage aggregation.

### 2026-02-22_23.31.40 centered focus boundaries

Merged source:
- `docs/understandings/2026-02-22_23.31.40-freeform-centered-focus-context-boundaries.md`

Preserved rule:
- Focus windows should remain centered when possible, and markerized context-before/context-after boundaries should remain explicit in prompt payloads.

### 2026-02-22_23.54.29 worker-banner task counters

Merged source:
- `docs/understandings/2026-02-22_23.54.29-prelabel-worker-banner-task-counter.md`

Preserved rule:
- Parallel kickoff status must preserve `task X/Y` shape (plus worker metadata) so ETA/counter parsing does not disappear mid-run.

### 2026-02-23_00.01.05 workers visible on all progress lines

Merged source:
- `docs/understandings/2026-02-23_00.01.05-freeform-prelabel-workers-visible-on-progress.md`

Preserved rule:
- Keep `(workers=N)` on completion updates, not kickoff-only, so long runs do not appear serial.

### 2026-02-23_00.10.26 timeout and partial-failure visibility

Merged source:
- `docs/understandings/2026-02-23_00.10.26-prelabel-timeout-and-partial-failure-visibility.md`

Preserved rules:
- Default prelabel timeout is `300` seconds per provider call.
- Completion output must surface explicit `PRELABEL ERRORS: X/Y` summary and `prelabel_errors.jsonl` path whenever failures exist (including allow-partial runs).

### 2026-02-23_00.22.44 progress callbacks are best-effort telemetry

Merged source:
- `docs/understandings/2026-02-23_00.22.44-labelstudio-progress-callbacks-must-be-best-effort.md`

Preserved rule:
- Label Studio ingest must wrap callback forwarding so spinner/UI exceptions are logged and ignored instead of aborting conversion/import.

### 2026-02-23_10.25.11 Codex reasoning-usage payload shape tolerance

Merged source:
- `docs/understandings/2026-02-23_10.25.11-codex-prelabel-reasoning-usage-shape.md`

Preserved rule:
- Codex usage payloads may omit reasoning fields; parsing remains best-effort with `reasoning_tokens` defaulting to `0` when unavailable.

### 2026-02-23_10.45.43 span prompt whole-block collapse guardrails

Merged source:
- `docs/understandings/2026-02-23_10.45.43-span-prompt-whole-block-collapse-guardrails.md`

Problem captured:
- Actual-freeform span runs could still over-select whole blocks even in span mode.

Preserved prompt-level guardrails:
- Keep explicit anti-whole-block rule for long blocks unless the block is nearly one label.
- Keep context guidance phrased as interpretation-only and forbid adjacent-block auto-propagation.
- Keep concrete mixed-block JSON examples in prompt text so selective sub-block behavior remains the demonstrated default.

### 2026-02-23_11.18.25 span prompt compact markerized block stream

Merged source:
- `docs/understandings/2026-02-23_11.18.25-span-prompt-compact-block-stream.md`

Problem captured:
- Span prompt wrapper overhead (JSON-like framing + marker lines) consumed avoidable input tokens in larger freeform prelabel runs.

Decision preserved:
- Keep span marker payload lines compact as `<block_index><TAB><block_text>` and use `{{BLOCKS_WITH_FOCUS_MARKERS_COMPACT_LINES}}`.
- Preserve legacy placeholder alias `{{BLOCKS_WITH_FOCUS_MARKERS_JSON_LINES}}` for backward-compatible custom prompt templates.
- Keep full/block payload placeholder behavior (`{{BLOCKS_JSON_LINES}}`) unchanged.

Anti-loop note:
- Do not re-expand compact span payload back to verbose wrapper formats unless segment sizing and token budget assumptions are revisited together.

### 2026-02-23_11.54.43 prelabel 429 stop-signal contract

Merged source:
- `docs/understandings/2026-02-23_11.54.43-prelabel-rate-limit-stop.md`

Problem captured:
- With queued parallel tasks, one provider 429 could still be followed by additional queued calls, amplifying throttling and noise.

Decision preserved:
- Detect provider rate-limit failures from normalized error text (`HTTP 429`).
- Set one shared stop event on first 429; queued tasks check this flag before provider calls and skip instead of sending new requests.
- Record skipped/error rows in `prelabel_errors.jsonl` and emit explicit `429` warning text in progress/summary output.

Anti-loop note:
- Retrying all queued tasks after first 429 is a known bad path for this flow; prefer explicit early stop + operator rerun.

### 2026-02-23_12.12.00 focus-only Label Studio text with prompt-only context rows

Merged source:
- `docs/understandings/2026-02-23_12.12.00-freeform-focus-only-task-text.md`

Problem captured:
- `segment_text` previously carried both focus and context rows, coupling offset-mapped labeling text to prompt-context transport.

Decision preserved:
- Keep `segment_text` and `source_map.blocks` focused on labelable rows only for offset-authoritative UI/export behavior.
- Keep neighboring prompt context in `source_map.context_before_blocks` and `source_map.context_after_blocks`.
- Prompt builder composes `context_before + focus + context_after`, with compatibility fallback for legacy payloads lacking context arrays.

Anti-loop note:
- Do not duplicate context rows back into `segment_text`; that reintroduces dedupe noise and offset drift risk for span labels.

## 2026-02-22_23 to 2026-02-23_10 docs/tasks merge batch (Label Studio freeform prelabel)

### 2026-02-22_23.16.06 - parallel freeform prelabel workers (`docs/tasks/2026-02-22_23.16.06 - parallel-freeform-prelabel-workers.md`)

Problem captured:
- Freeform prelabel was serial despite task independence, making long imports appear stalled.

Decision preserved:
- Use bounded `ThreadPoolExecutor` task-level concurrency with `--prelabel-workers` (task recorded default `4`; current runtime default is `15`).
- Keep deterministic post-processing by sorting completed task results by task index before writing logs/errors.
- Keep strict vs allow-partial failure semantics unchanged.

Evidence preserved from task:
- Recorded verification run:
  - `source .venv/bin/activate && pip install -e .[dev] && pytest -q tests/labelstudio/test_labelstudio_ingest_parallel.py tests/labelstudio/test_labelstudio_prelabel.py tests/labelstudio/test_labelstudio_benchmark_helpers.py` -> `86 passed`.

Anti-loop notes:
- Do not mutate shared usage counters without thread-safe guards.
- Preserve deterministic prompt-log/report ordering even when tasks finish out of order.

### 2026-02-22_23.31.26 - centered focus/context markers (`docs/tasks/2026-02-22_23.31.26 - freeform-focus-context-markers.md`)

Problem captured:
- Focus blocks were front-loaded, so context appeared mostly after focus and scope boundaries were unclear in UI/prompts.

Decision preserved:
- Center focus windows when possible.
- Use explicit context-before/context-after markers around focus boundaries in prompts.
- Surface scope hints/ranges in Label Studio tasks.

Evidence preserved from task:
- Recorded verification run:
  - `source .venv/bin/activate && pip install -e .[dev] && pytest -q tests/labelstudio/test_labelstudio_freeform.py tests/labelstudio/test_labelstudio_prelabel.py tests/labelstudio/test_labelstudio_ingest_parallel.py tests/labelstudio/test_labelstudio_benchmark_helpers.py` -> pass.

Constraint preserved:
- Enforce overlap floor `segment_overlap_effective >= segment_blocks - segment_focus_blocks`.

### 2026-02-22_23.55.11 - keep kickoff `task 0/Y` with workers suffix (`docs/tasks/2026-02-22_23.55.11 - keep-prelabel-worker-banner-task-counter.md`)

Problem captured:
- Parallel kickoff message dropped `task X/Y`, making spinner look stalled until first completion.

Decision preserved:
- Keep kickoff format as `Running freeform prelabeling... task 0/Y (workers=N)`.

Evidence preserved from task:
- Regression assertion added in `tests/labelstudio/test_labelstudio_ingest_parallel.py` for `task 0/2` with workers metadata.
- Recorded run: `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1 pytest tests/labelstudio/test_labelstudio_ingest_parallel.py tests/labelstudio/test_labelstudio_prelabel.py tests/labelstudio/test_labelstudio_benchmark_helpers.py` -> `87 passed, 2 warnings in 3.28s`.

### 2026-02-23_00.01.05 - keep worker suffix on completion updates (`docs/tasks/2026-02-23_00.01.05 - keep-prelabel-workers-visible-during-progress.md`)

Problem captured:
- Worker metadata appeared only at kickoff; completion updates looked serial.

Decision preserved:
- Route status formatting through one helper that conditionally appends `(workers=N)` for parallel runs on both kickoff and completion updates.

Evidence preserved from task:
- Regression assertions added for `(workers=2)` on `task 1/2` and `task 2/2` updates.
- Recorded run: `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1 pytest tests/labelstudio/test_labelstudio_ingest_parallel.py`.

### 2026-02-23_00.10.13 - timeout raise + explicit error summary (`docs/tasks/2026-02-23_00.10.13 - prelabel-timeout-and-error-summary.md`)

Problem captured:
- Per-task timeout was too low and allow-partial completions could hide serious prelabel failure counts.

Decisions preserved:
- Raise default timeout from `120s` to `300s`.
- Print explicit red completion summary (`PRELABEL ERRORS: X/Y`) and `prelabel_errors.jsonl` guidance whenever failures exist.
- Keep allow-partial behavior operator-controlled; improve visibility only.

Evidence preserved from task:
- Added assertions for default timeout propagation and completion summary behavior in benchmark helper / ingest parallel tests.

### 2026-02-23_00.22.43 - protect ingest from callback exceptions (`docs/tasks/2026-02-23_00.22.43 - protect-ingest-from-progress-callback-failures.md`)

Problem captured:
- Spinner/UI callback exceptions could abort ingest conversion even when extraction logic was healthy.

Decision preserved:
- Wrap callback forwarding in `_notify_progress_callback(...)` and treat failures as non-fatal warning-only telemetry.
- Use same safe notifier in `generate_pred_run_artifacts(...)` and `run_labelstudio_import(...)` paths.

Evidence preserved from task:
- Added `test_generate_pred_run_artifacts_ignores_progress_callback_errors`.
- Recorded verification runs include targeted and full `tests/labelstudio/test_labelstudio_ingest_parallel.py` plus spinner helper test.

### 2026-02-23_10.25.11 - reasoning-token usage in summaries (`docs/tasks/2026-02-23_10.25.11 - prelabel-reasoning-token-usage.md`)

Problem captured:
- Usage summaries omitted reasoning tokens.

Decision preserved:
- Add aggregate `reasoning_tokens` to provider usage summary, `prelabel_report.json`, and CLI summary line.
- Keep parsing backward-compatible (`0` when reasoning fields are absent) and shape-tolerant for nested payload variants.

Evidence preserved from task:
- Added provider tests for no-reasoning and nested reasoning payload shapes.
- Added summary-format assertion in benchmark-helper CLI output tests.
- Recorded verification run:
  - `source .venv/bin/activate && pytest tests/labelstudio/test_labelstudio_prelabel.py::test_codex_provider_tracks_usage_from_json_events tests/labelstudio/test_labelstudio_prelabel.py::test_codex_provider_tracks_reasoning_tokens_from_nested_usage tests/labelstudio/test_labelstudio_benchmark_helpers.py::test_labelstudio_import_prints_prelabel_token_usage_with_reasoning`.

Anti-loop notes across this batch:
- Keep `task X/Y` text intact in parallel progress messages; ETA parsing depends on that shape.
- Keep callback failure handling as telemetry-only; do not rewire it into hard-failure control flow.
- Do not assume reasoning fields are always emitted by Codex usage payloads.

## 2026-02-23_13.35.17 docs/tasks retirement merge (Label Studio freeform batch)

### 2026-02-20_21.40.00 freeform prelabel baseline record (`docs/tasks/000-AI-labelling-golden.md`, retired)

Problem captured:
- Golden-set setup for freeform spans was too slow when every segment required manual first-pass highlighting.

Decisions/actions preserved:
- Added offline prelabel generation with deterministic block/offset conversion and strict label validation.
- Kept upload default as completed `annotations` and retained `predictions` as a debug compatibility path.
- Preserved fallback upload contract for inline-annotation rejection: task import first, then per-task annotation create.
- Preserved robust JSON extraction requirement for Codex CLI responses that include non-JSON wrapper text.

Historical branch note preserved:
- `labelstudio-decorate` additive mode existed briefly and was later removed (2026-02-22); treat old decorate references as retired branch history unless explicitly reviving the feature.

Evidence preserved from task:
- `tests/test_labelstudio_prelabel.py::test_parse_block_label_output_extracts_embedded_json`
- `tests/test_labelstudio_prelabel.py::test_prelabel_freeform_task_uses_block_offsets_and_exact_text`
- `tests/test_labelstudio_ingest_parallel.py::test_run_labelstudio_import_falls_back_to_post_import_annotations`

### 2026-02-22_17.36.00 span-vs-block granularity record (`docs/tasks/000-AI-span-freeform-fr.md`, retired)

Problem captured:
- Legacy one-label-per-block prelabeling could not produce true sub-block highlights for freeform annotation.

Decisions/actions preserved:
- Added dual granularity contract (`block` vs `span`) and interactive naming (`actual freeform` vs `legacy, block based`).
- Kept quote-anchored span schema as primary (`block_index`, `label`, `quote`, optional `occurrence`) with validated absolute-offset fallback.
- Preserved ambiguity rule: repeated quote text in one block must include `occurrence`; unresolved ambiguous rows are dropped.

Evidence preserved from task:
- `tests/test_labelstudio_prelabel.py::test_span_resolution_requires_occurrence_for_ambiguous_quote`
- `tests/test_labelstudio_prelabel.py::test_prelabel_freeform_task_span_mode_creates_partial_block_spans`

### 2026-02-22_19.48.00 context/focus + target-task tuning record (`docs/tasks/2026-02-22_19.35.04-freeform-focus-task-count.md`, retired)

Problem captured:
- Operators needed to keep larger context windows while labeling a smaller focus subset and tuning approximate task count without hand-solving overlap.

Decisions/actions preserved:
- Added `segment_focus_blocks` and `target_task_count` while keeping backward-compatible defaults.
- Added deterministic overlap solver + manifest recording of requested vs effective overlap.
- Enforced focus scope in parser logic so prompt drift cannot bypass focus-only labeling constraints.
- Preserved direct-call CLI pitfall: Typer options used by helper/tests must keep plain Python defaults (`Annotated[..., typer.Option(...)] = ...`) to avoid `OptionInfo` runtime errors.

Evidence preserved from task:
- Focused verification run recorded in task: `93 passed` across freeform/prelabel/ingest/benchmark helper suites.

### 2026-02-23_12.12.00 focus-only Label Studio text record (`docs/tasks/2026-02-23_12.11.30-freeform-focus-only-labelstudio-text.md`, retired)

Problem captured:
- Mixed focus+context `segment_text` made Label Studio task text noisier and complicated downstream dedupe while prelabel still required neighborhood context.

Decisions/actions preserved:
- Made `segment_text` + `source_map.blocks` focus-only and offset-authoritative.
- Split prompt-only context into `source_map.context_before_blocks` and `source_map.context_after_blocks`.
- Kept prompt-builder fallback for legacy payloads that do not include the new context arrays.
- Updated coverage accounting to include context arrays so warnings remain accurate after focus-only split.

Anti-loop carry-forward for this retirement merge:
- Do not reintroduce decorate-mode assumptions into current runtime docs without explicit product decision.
- Do not relax focus constraints to prompt-only wording; parser enforcement is the contract.
- Do not collapse context arrays back into `segment_text`; that reintroduces dedupe noise and offset ambiguity.

## 2026-02-24 archival merge batch from `docs/understandings` (Label Studio)

### 2026-02-23_15.55.42 freeform export recipe-header count persistence

Merged source:
- `docs/understandings/2026-02-23_15.55.42-golden-recipe-header-count-flow.md`

Problem captured:
- Freeform exports had enough information to derive recipe totals, but recipe-header diagnostics were not persisted consistently for benchmark/eval interpretation.

Preserved decisions:
- Persist recipe-header counts in freeform export `summary.json` (`counts.recipe_headers`, `recipe_counts.recipe_headers`, `recipe_counts.recipe_headers_raw`).
- Derive golden recipe totals from normalized `RECIPE_TITLE` spans deduped by source+block-range.
- Surface predicted-vs-golden recipe count diagnostics in freeform benchmark/eval reports.

Anti-loop note:
- Keep recipe-count diagnostics distinct from span matching metrics; high span quality and recipe-count mismatch can coexist.

## 2026-02-24_21.34.27 to 2026-02-24_22.03.07 archival merge batch from `docs/understandings` (Label Studio)

### 2026-02-24_21.34.27 prelabel effort compatibility filtering

Preserved findings:
- Interactive freeform prelabel effort menus can present invalid options if they do not respect selected-model metadata + tool constraints.
- Captured incompatibilities included:
  - `minimal` rejected under active tool combinations,
  - model-specific invalid effort values (for example `none` for models whose metadata does not allow it).

Durable rule:
- Build interactive effort menu from model metadata and known tool compatibility constraints, and force explicit valid selection when configured defaults are incompatible.

### 2026-02-24_22.03.07 quote repair pass for block-index mismatches

Preserved findings:
- Empty list (`[]`) output is a legitimate "no spans found" result and should not be logged as a model/parsing failure.
- A recurring failure mode was valid quote text paired with off-by-one or otherwise incorrect `block_index`, producing false "no valid labels."

Durable rule:
- Keep quote repair pass in span-mode parsing:
  1. retry quote anchoring in nearby focus blocks,
  2. then accept unique focus-window match if available.
- Only attach annotation payloads when the final span result is non-empty.

Anti-loop note for this batch:
- Do not classify empty `[]` prelabel outputs as automatic provider failures; inspect mismatch-repair and segment signal quality first.

## 2026-02-24_22.44.09 archival merge batch from `docs/tasks` (Label Studio)

### 2026-02-24_21.34.27 prelabel invalid-effort menu filtering

Merged source:
- `docs/tasks/2026-02-24_21.34.27-prelabel-invalid-effort-choices.md`

Problem captured:
- Interactive prelabel effort picker surfaced values that can fail immediately at preflight/runtime (`minimal` with tool-enabled path, model-incompatible efforts like `none` on unsupported models).

Decision/outcome preserved:
- Exclude `minimal` in interactive freeform prelabel effort menus.
- Filter effort options by selected model metadata (`supported_reasoning_levels`) when available.
- Hide incompatible "use Codex default (...)" effort option when default conflicts with selected model/workflow.

Evidence preserved:
- `pytest -q tests/labelstudio/test_labelstudio_prelabel.py -k 'list_codex_models'` passed.
- `pytest -q tests/labelstudio/test_labelstudio_benchmark_helpers.py -k 'interactive_labelstudio_freeform_scope_routes_to_freeform_import or interactive_labelstudio_filters_incompatible_effort_choices'` passed.

Anti-loop note:
- For immediate provider-effort failures, inspect interactive menu filtering/model metadata compatibility first before changing prelabel prompt text or retry strategy.
