---
summary: "Code-verified Label Studio import/export/eval reference for current behavior, contracts, and known pitfalls."
read_when:
  - Working on any Label Studio import/export/evaluation flow
  - Debugging unexpected uploads, zero-match evals, or output-path confusion
  - Working on freeform golden-set workflows
---

# Label Studio: Technical Readme

This document is the current source of truth for implemented Label Studio behavior.

Code surfaces (primary):

- `cookimport/labelstudio/ingest.py`
- `cookimport/labelstudio/export.py`
- `cookimport/labelstudio/eval_freeform.py`
- `cookimport/labelstudio/prelabel.py`
- `cookimport/labelstudio/freeform_tasks.py`
- `cookimport/labelstudio/archive.py`
- `cookimport/labelstudio/canonical_gold.py`
- `cookimport/labelstudio/client.py`
- `cookimport/labelstudio/label_config_freeform.py`
- `cookimport/labelstudio/models.py`
- `cookimport/cli.py`

Nearby code used directly by Label Studio benchmark/eval flow:

- `cookimport/bench/eval_stage_blocks.py`
- `cookimport/bench/eval_canonical_text.py`
- `cookimport/bench/prediction_records.py`
- `cookimport/bench/sequence_matcher_select.py`
- `cookimport/bench/canonical_alignment_cache.py`
- `cookimport/analytics/perf_report.py`

Use `docs/06-label-studio/06-label-studio_log.md` only for compact historical context when a fix starts looping.

## 1) Current Scope and Commands

### 1.1 Scope boundary

Active Label Studio runtime scope is `freeform-spans`.

- Import writes `task_scope: freeform-spans` manifests.
- Export rejects legacy-scoped (`pipeline`, `canonical-blocks`) projects/manifests/payloads.
- Eval and benchmark flows are freeform-gold driven.

### 1.2 CLI commands

- `cookimport labelstudio-import`
- `cookimport labelstudio-export`
- `cookimport labelstudio-eval`
- `cookimport labelstudio-benchmark`

### 1.3 Default roots

- Import output root: `data/golden/sent-to-labelstudio`
- Export output root: `data/golden/pulled-from-labelstudio`
- Benchmark scratch root: `data/golden/benchmark-vs-golden`
- Benchmark processed output root: `data/output`

## 2) Write Safety and Interactive Behavior

### 2.1 Upload consent

- `labelstudio-import` requires `--allow-labelstudio-write`.
- `labelstudio-benchmark` requires `--allow-labelstudio-write` only when upload is enabled.
- `labelstudio-benchmark --no-upload` is offline and skips Label Studio writes.

### 2.2 Interactive flow contracts

- Interactive Label Studio import uploads directly (no second upload confirmation prompt).
- Interactive Label Studio import uses overwrite semantics (`overwrite=True`, `resume=False`).
- Interactive Label Studio import includes freeform prelabel mode + style selection (`span` vs `block`).
- Interactive export resolves credentials, fetches project titles, and shows detected type tags for operator context.
- Interactive benchmark is offline-only and offers:
  - single offline run,
  - all-method offline sweep.
- Interactive benchmark routes both modes to `labelstudio-benchmark` with `eval-mode canonical-text`.

## 3) Task Generation, Resume, and IDs

### 3.1 Deterministic task IDs

Freeform task IDs use deterministic segment URNs:

- `urn:cookimport:segment:{source_hash}:{start_block_index}:{end_block_index}`

Resume/idempotence is based on these IDs, not Label Studio internal task IDs.

### 3.2 Resume behavior

- Resume metadata is applied only when the target project already exists.
- Existing IDs come from prior manifests and/or prior `label_studio_tasks.jsonl`.
- Benchmark upload can auto-dedupe project names (`-1`, `-2`, ...) when old project scope metadata collides.

### 3.3 Task payload contract

- `segment_text` contains the labelable focus window for one task.
- `source_map.blocks[*]` carries offset-authoritative block spans (`segment_start`, `segment_end`) for that focus text.
- `source_map.context_before_blocks` and `source_map.context_after_blocks` carry prompt-only context rows (not label targets).
- Import writes `coverage.json` from focus + context block coverage and fails when extracted text is empty.

## 4) Freeform Prelabel Contracts

### 4.1 Modes

`--prelabel-granularity` supports:

- `block` (legacy block-based mapping): `{block_index, label}` -> full-block span
- `span` (actual freeform): quote/offset span resolution for sub-block highlights

Both modes keep deterministic normalization and offset integrity.

Freeform label set includes `HOWTO_SECTION` for in-recipe subsection headers (for example `TO SERVE` / `FOR THE SAUCE`).
Eval/benchmark scoring resolves `HOWTO_SECTION` into `INGREDIENT_LINE` or `INSTRUCTION_LINE` using nearby context.

### 4.2 Upload behavior

`--prelabel-upload-as` supports:

- `annotations` (default)
- `predictions`

If inline annotation import fails, runtime falls back to:

1. task-only upload,
2. post-import annotation creation through API (segment-id to task-id mapping).

### 4.3 Reliability behaviors

- Preflight model-access check happens once before task loop.
- Prompt calls are one-task-per-prompt (no cross-task conversation memory).
- Prompt cache is deterministic and can make reruns appear stateful.
- Parallel prelabel workers are bounded (`--prelabel-workers`, default `15`).
- Default prelabel timeout is `300` seconds per call.
- First provider 429 sets a stop signal; remaining queued tasks are skipped and logged.
- Callback failures are non-fatal telemetry warnings.
- Plain `codex` command fallback to `codex exec -` is handled for TTY-style stdin failures.

### 4.4 Artifacts

Prelabel-enabled runs write:

- `prelabel_report.json`
- `prelabel_errors.jsonl`
- `prelabel_prompt_log.md`

Usage tracking in reports includes token totals (`input`, `cached_input`, `output`, `reasoning` when present).

### 4.5 Command/model/effort resolution

Command resolution order:

1. `--codex-cmd`
2. `COOKIMPORT_CODEX_CMD`
3. `codex exec -`

Model resolution order:

1. `--codex-model`
2. `COOKIMPORT_CODEX_MODEL`
3. Codex config/defaults

Thinking effort uses `--codex-thinking-effort` (alias `--codex-reasoning-effort`) and maps to `model_reasoning_effort`.

## 5) Export, Eval, and Benchmark Contracts

### 5.1 Export artifacts

`labelstudio-export` writes:

- `exports/labelstudio_export.json`
- `exports/freeform_span_labels.jsonl`
- `exports/freeform_segment_manifest.jsonl`
- `exports/canonical_text.txt`
- `exports/canonical_block_map.jsonl`
- `exports/canonical_span_labels.jsonl`
- `exports/canonical_span_label_errors.jsonl`
- `exports/canonical_manifest.json`
- `exports/summary.json`
- `run_manifest.json` (run root)

`summary.json` includes deduped recipe-header diagnostics from normalized `RECIPE_TITLE` spans.

### 5.2 Eval artifacts

`labelstudio-eval` writes:

- `eval_report.json`
- `eval_report.md`
- `missed_gold_spans.jsonl`
- `false_positive_preds.jsonl`
- `run_manifest.json`

`--force-source-match` bypasses strict source identity checks when intentionally comparing renamed/cutdown variants.
`labelstudio-eval` also appends benchmark-style history CSV rows and refreshes dashboard artifacts.

### 5.3 Benchmark behavior

`labelstudio-benchmark` supports:

- upload path (prediction import + eval)
- offline path (`--no-upload`)
- eval-only from prediction records (`--predictions-in`)
- prediction-record output (`--predictions-out`)
- prediction-only artifact generation (`--execution-mode predict-only`)

Execution modes:

- `legacy` (default)
- `pipelined`
- `predict-only`

Eval modes:

- `stage-blocks` (default)
- `canonical-text`

Evaluation implementation:

- `stage-blocks` path uses `cookimport/bench/eval_stage_blocks.py`.
- `canonical-text` path uses `cookimport/bench/eval_canonical_text.py`.
- Canonical mode ensures canonical gold artifacts from export payloads via `cookimport/labelstudio/canonical_gold.py` when needed.

Benchmark eval artifacts include:

- `eval_report.json`
- `eval_report.md`
- `missed_gold_blocks.jsonl`
- `wrong_label_blocks.jsonl`
- `missed_gold_spans.jsonl` (legacy alias)
- `false_positive_preds.jsonl` (legacy alias)
- `run_manifest.json`

Canonical-text mode also writes line/alignment diagnostics:

- `missed_gold_lines.jsonl`
- `wrong_label_lines.jsonl`
- `aligned_prediction_blocks.jsonl`
- `unmatched_pred_blocks.jsonl`
- `alignment_gaps.jsonl`

Prediction/eval telemetry files are written under eval output roots, and benchmark appends history CSV/dashboard artifacts.

## 6) Artifact Layout

### 6.1 Import

- `<import_output_root>/<timestamp>/labelstudio/<book_slug>/...`
- Timestamp format: `%Y-%m-%d_%H.%M.%S`
- Core artifacts include `manifest.json`, `run_manifest.json`, `coverage.json`, `extracted_archive.json`, `extracted_text.txt`, and (when enabled) prelabel artifacts.

### 6.2 Export

- Default: `<export_output_root>/<source_slug_or_project_slug>/exports/...`
- If export payload/source metadata resolves to one source file, its filename stem is used as slug so repeated pulls overwrite the same folder even when project names are deduped with suffixes (`-2`, `-3`, ...).
- `--run-dir` overrides destination.
- Run root also carries `run_manifest.json`.

### 6.3 Benchmark

- Eval root: `data/golden/benchmark-vs-golden/<timestamp>/...`
- Prediction run is co-located under eval root (`prediction-run/`).
- Benchmark also records processed cookbook outputs under configured processed output root.
- Typical eval-root extras: `processing_timeseries_prediction.jsonl`, `processing_timeseries_evaluation.jsonl`, optional `eval_profile.pstats`/`eval_profile_top.txt`, and `run_manifest.json`.

## 7) Troubleshooting Checklist

1. Confirm the run is freeform (`freeform-spans`) and not a legacy-scope project.
2. Confirm write consent and upload mode (`--allow-labelstudio-write`, `--no-upload`).
3. Confirm you are checking `data/golden/*` paths (not only `data/output/*`).
4. If overlap looks zero, test with `--force-source-match` to rule out source identity mismatch.
5. For split EPUB/PDF paths, verify merged block indices were rebased globally.
6. If process workers are denied during split conversion, confirm logs show thread fallback (`Process-based worker concurrency unavailable ... using thread-based worker concurrency.`); serial fallback should appear only if thread startup also fails.
7. For prelabel failures, read `prelabel_errors.jsonl` and `prelabel_report.json` first.

## 8) Explicitly Retired Features

These are intentionally not active runtime features:

- Label Studio task-scope execution branches for `pipeline` and `canonical-blocks`.
- Legacy `labelstudio-decorate` branch.
- Interactive benchmark upload mode (interactive benchmark is offline-only).

## 2026-02-27 Merged Understandings: Label Studio Doc Scope and Coverage

Merged source notes:
- `docs/understandings/2026-02-27_19.44.58-labelstudio-doc-prune-scope-map.md`
- `docs/understandings/2026-02-27_19.50.37-labelstudio-doc-code-coverage-audit.md`

Current-contract additions:
- Runtime import/export/eval path is freeform-only (`freeform-spans`); legacy scope behavior remains only for explicit rejection/compat messaging.
- Prelabel `block` and `span` granularities are both active contracts and must stay documented.
- Module ownership docs must include `archive.py`, `canonical_gold.py`, `client.py`, `label_config_freeform.py`, `models.py`, plus benchmark evaluator dependencies.
- Benchmark docs must include prediction-record contracts (`--predictions-in`, `--predictions-out`) and mode-specific artifact differences.
- `labelstudio-eval` and `labelstudio-benchmark` both emit manifest/history side effects and should be documented together with those outputs.

## 2026-02-28 migrated understandings digest

This section consolidates discoveries migrated from `docs/understandings` into this domain folder.

### 2026-02-27_20.13.08 labelstudio unlabeled text fallback
- Source: `docs/understandings/2026-02-27_20.13.08-labelstudio-unlabeled-text-fallback.md`
- Summary: Pulled Label Studio freeform exports only contain explicit spans; unlabeled regions are treated as OTHER during benchmark evaluation.

### 2026-02-27_20.15.35 labelstudio overlap multilabel behavior
- Source: `docs/understandings/2026-02-27_20.15.35-labelstudio-overlap-multilabel-behavior.md`
- Summary: Overlapping Label Studio spans are preserved in export; stage/canonical eval treat overlapping coverage as multi-label gold sets.

### 2026-02-28_00.16.13 howtosection label scoring paths
- Source: `docs/understandings/2026-02-28_00.16.13-howto-section-label-scoring-paths.md`
- Summary: `HOWTO_SECTION` is UI-visible/exported, then resolved at scoring time to ingredient vs instruction via nearby structural context.

### 2026-02-28_00.50.48 labelstudio export root source identity
- Source: `docs/understandings/2026-02-28_00.50.48-labelstudio-export-root-source-identity.md`
- Summary: Export destination selection is source-aware so repeated pulls reuse one folder even when project titles are deduped/suffixed.

Current-contract additions from the HOWTO section audit:
- Label additions are multi-surface changes, not UI-only changes:
  - UI/export labels: `cookimport/labelstudio/label_config_freeform.py`
  - freeform eval labels: `cookimport/labelstudio/eval_freeform.py`
  - benchmark allowed labels: `cookimport/staging/stage_block_predictions.py:FREEFORM_LABELS`
  - benchmark scorers: `cookimport/bench/eval_stage_blocks.py`, `cookimport/bench/eval_canonical_text.py`
- `HOWTO_SECTION` remains an explicit task/export label for annotator visibility.
- Scoring should remap `HOWTO_SECTION` to `INGREDIENT_LINE` or `INSTRUCTION_LINE` using nearby context before metric computation.
- Anti-loop guard:
  - if a new label appears in Label Studio but not in benchmark/eval results, check scorer label maps before changing task generation.

## 2026-02-28 task consolidation (`docs/tasks` split-convert fallback hardening)

Merged task file:
- `2026-02-28_12.20.59-sandbox-parallel-fallbacks-stage-and-labelstudio.md`

Current Label Studio split-convert fallback contract:
- Split conversion fallback order now mirrors stage/all-method behavior: `process -> thread -> serial`.
- Process-worker denial should produce thread-fallback warning text first; serial fallback should only appear if thread startup also fails.
- Shared resolver plumbing is centralized in `cookimport/core/executor_fallback.py` to keep fallback behavior aligned across stage and Label Studio surfaces.

## 2026-02-28 merged understandings (split-convert fallback closure and test robustness)

### 2026-02-28_13.19.45 stage and Label Studio fallback plan closure
- Source: `docs/understandings/2026-02-28_13.19.45-stage-and-labelstudio-fallback-plan-closure-and-test-wrap.md`
- Shared fallback resolver rollout for stage + Label Studio split conversion is complete in runtime code (`cookimport/core/executor_fallback.py` + call sites).
- Split-convert fallback behavior is validated by targeted tests; remaining confusion tended to be assertion fragility, not missing fallback runtime wiring.
- Test-contract reminder: warning text can wrap under rich/terminal output; normalize whitespace before matching fallback phrases in assertions.

## 2026-03-02 merged understandings digest (labelstudio benchmark compare mode + gate hardening)

### 2026-03-02_11.34.28 labelstudio benchmark compare CLI gate table
- Source: `docs/understandings/2026-03-02_11.34.28-labelstudio-benchmark-compare-cli-gate-table.md`
- `labelstudio_benchmark_compare` now prints pass/fail gate summary in terminal output immediately after verdict, while preserving `comparison.json` and `comparison.md` artifacts.
- Active contract location: `cookimport/cli.py` compare handler.

### 2026-03-02_11.39.21 benchmark alias normalization and prediction-manifest fallback
- Source: `docs/understandings/2026-03-02_11.39.21-run-settings-alias-and-manifest-path-notes.md`
- `RunSettings.from_dict` now normalizes `codex_farm_recipe_mode` aliases (`line-label`, `line-labels`, `default`, blank) to canonical `benchmark`/`extract`.
- Labelstudio benchmark compare debug artifact lookup now prefers `artifacts.pred_run_dir` from winner `run_manifest` and falls back to `eval_dir/prediction-run` only when missing.

### 2026-03-02_12.00.00 labelstudio benchmark compare mode resolution
- Source: `docs/understandings/2026-03-02_12.00.00-labelstudio-benchmark-compare-mode-resolution.md`
- Compare mode now resolves `codex_farm_mode_source` from either explicit metadata (`codex_farm_recipe_mode`) or raw llm evidence (`raw/llm` prompt/eval artifacts).
- Missing intent now yields `inferred`/`unknown` states with explicit warning emission instead of silently treating unverified runs as benchmark mode.

### 2026-03-02_20.44.30 labelstudio compare gates and debug artifact requirements
- Source: `docs/understandings/2026-03-02_20.44.30-labelstudio-benchmark-compare-mode-and-debug-gates.md`
- Verdict gating now keys on manifest-derived codex intent:
  - required gates when `codex_farm_recipe_mode=benchmark` + `llm_recipe_pipeline=codex-farm-3pass-v1`,
  - `aligned_prediction_blocks.jsonl`, `llm_manifest_json`, and pass-level manifests become mandatory for those paths.
- Missing required evidence flips corresponding `*_debug_artifacts_present` gates and can drive overall verdict fail when strict compare mode is active.

### 2026-03-02_23.40.00 labelstudio benchmark gate hardening
- Source: `docs/understandings/2026-03-02_23.40.00-labelstudio-benchmark-compare-gate-hardening.md`
- Missing explicit benchmark intent metadata is now an explicit hard-fail signal for strict debug-gate mode instead of a silent pass path.
- Raw prompt manifest payloads (`prompt_inputs_manifest_txt` and `prompt_outputs_manifest_txt`) are now treated as required source files for pass-level debug checks.
- Missing llm manifest metadata is surfaced in warning + gate output to prevent false confidence in incomplete candidate evaluations.
