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

From `GoldenSetTake2.md` + `2026-02-02-labelstudio-canonical-workflow.md`:

- canonical block scope added as a parallel workflow (not replacement for pipeline scope),
- stable block IDs introduced,
- canonical export/eval scaffolding and tests added,
- task scope persistence added to prevent accidental cross-scope resume.

### 2026-02-10 freeform workflow introduced

From `freeform.md` and related 2026-02-10 discovery docs:

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

From `PDF-freeform-DO-LATER.md`:

- rectangle-on-page-images workflow investigated and documented,
- left explicitly as do-later planning, not part of current code.


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
  - decorate existing freeform projects.
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
- Non-interactive prelabel/decorate subprocesses must default to `codex exec -`.
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
- Model selection must propagate through import/decorate runtime provider construction, not only prompt/UI layers.
- Effective command (`codex exec -` plus optional `--model`) should be resolved centrally and reported in run artifacts.
- Token usage remains provider-level aggregation (`usage_summary`) and is always enabled for prelabel/decorate runs.

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
- Prelabel, decorate, export/eval label normalization, and interactive project-type inference should all reuse that shared normalization logic.
