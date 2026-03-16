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

Label-first runtime seam used by benchmark/import flows:

- `cookimport/parsing/label_source_of_truth.py`
- `cookimport/parsing/recipe_span_grouping.py`
- `cookimport/staging/import_session.py`

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
- `cookimport labelstudio-benchmark compare --baseline ... --candidate ...`

### 1.3 Default roots

- Import output root: `data/golden/sent-to-labelstudio`
- Export output root: `data/golden/pulled-from-labelstudio`
- Benchmark scratch root: `data/golden/benchmark-vs-golden`
- Benchmark processed output root: `data/output`

## 2) Write Safety and Interactive Behavior

### 2.1 Upload consent

- `labelstudio-import` requires `--allow-labelstudio-write`.
- `labelstudio-import --prelabel` also requires `--allow-codex` even when recipe parsing stays deterministic, because freeform prelabel is CodexFarm-backed.
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
Scoring behavior:
- freeform eval and stage-block benchmark mode resolve `HOWTO_SECTION` into `INGREDIENT_LINE` or `INSTRUCTION_LINE` using nearby context.
- canonical-text benchmark mode keeps `HOWTO_SECTION` as an explicit scored label.

### 4.2 Upload behavior

`--prelabel-upload-as` supports:

- `annotations` (default)
- `predictions`

If inline annotation import fails, runtime falls back to:

1. task-only upload,
2. post-import annotation creation through API (segment-id to task-id mapping).

### 4.3 Reliability behaviors

- Prelabel is part of the Codex decision boundary and shows up as the `prelabel` Codex surface in manifests and plan previews.
- Preflight model-access check happens once before task loop.
- Prompt calls are one-task-per-prompt (no cross-task conversation memory).
- Prompt cache is deterministic and can make reruns appear stateful.
- Parallel prelabel workers are bounded (`--prelabel-workers`, default `15`).
- Default prelabel timeout is `600` seconds per call.
- First provider 429 sets a stop signal; remaining queued tasks are skipped and logged.
- Callback failures are non-fatal telemetry warnings.
- Prelabel runs use CodexFarm pipeline `prelabel.freeform.v1` (no direct local `codex exec` fallback path).

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
3. `COOKIMPORT_CODEX_FARM_CMD`
4. `codex-farm`

Model resolution order:

1. `--codex-model`
2. `COOKIMPORT_CODEX_FARM_MODEL`
3. `COOKIMPORT_CODEX_MODEL`
4. Codex config/defaults

Thinking effort uses `--codex-thinking-effort` (alias `--codex-reasoning-effort`) and maps to CodexFarm reasoning-effort overrides.

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
For metadata parity with benchmark/prediction manifests, `labelstudio-eval` now accepts optional
`--llm-recipe-pipeline`, `--atomic-block-splitter`, and `--line-role-pipeline` overrides; when omitted,
values are inferred from prediction-run metadata.

### 5.3 Benchmark behavior

`labelstudio-benchmark` supports:

- upload path (prediction import + eval)
- offline path (`--no-upload`)
- eval-only from prediction records (`--predictions-in`)
- prediction-record output (`--predictions-out`)
- compare action for benchmark runs (`labelstudio-benchmark compare`)
- line-role gating (`--line-role-gated`) for canonical Milestone-5 regression checks
- benchmark prediction-generation scratch stays inside the resolved `eval_output_dir` artifact root, so one benchmark session does not spill sibling timestamp roots under `data/golden/benchmark-vs-golden`
- when processed outputs are requested, benchmark/prediction runs reuse the stage-produced authoritative label artifacts (`label_det`, `label_llm_correct`, `group_recipe_spans`) and mirror the resulting `stage_block_predictions.json` into the prediction run root
- prediction generation no longer runs a second post-stage diagnostic `label_atomic_lines(...)` pass; freeform span projection reuses the authoritative labeled-line bundle from stage or builds the same bundle once in-memory for offline-only runs

Execution modes:

- `pipelined` (fixed)

### 5.4 Codex plan/approval boundary notes

- `labelstudio-benchmark --codex-execution-policy plan` belongs at the benchmark command boundary:
  - writes `codex_execution_plan.json` plus manifests,
  - runs deterministic extraction/planning first so the plan artifact can list the pending recipe-pass work and codex line-role batches,
  - requires `--no-upload`,
  - stops before task generation, benchmark evaluation, upload, and live Codex work.
- `labelstudio-import --codex-execution-policy plan` now offers the same zero-token preview shape for direct import runs:
  - writes pred-run manifests plus `codex_execution_plan.json`,
  - includes concrete planned work rows derived from deterministic extraction,
  - skips task generation, upload, prelabel execution, and other live Codex work,
  - does not require `--allow-codex`.
- `labelstudio-import --prelabel` is a separate Codex-backed surface from recipe/line-role benchmark settings.
  - Do not assume recipe/line-role decision metadata or approval checks automatically cover prelabel behavior.
  - If operator-intent policy changes, review prelabel command wiring separately.

Codex preview mode:

- `--codex-execution-policy execute|plan` is available on `labelstudio-benchmark`.
- `execute` now has a stricter live-benchmark gate for non-interactive runs: `--allow-codex` is still required when Codex-backed surfaces are enabled, `labelstudio-benchmark` also requires `--benchmark-codex-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`, and agent-run environments are blocked from that non-interactive live path. Interactive CLI benchmark runs are treated as human-confirmed and may proceed directly.
- `plan` is offline-only (`--no-upload`), skips task generation/upload/benchmark eval/live Codex work, and writes a prediction-run `codex_execution_plan.json` plus benchmark/pred-run manifests so a later execute-mode rerun can be inspected before spending tokens.
- plan mode still performs deterministic extraction so the preview includes concrete pending line-role and recipe-pass work instead of only the requested Codex surfaces.
- `labelstudio-import` also accepts `--codex-execution-policy execute|plan`; its `plan` mode writes the same pred-run plan artifact and exits before task upload or prelabel execution.

Eval modes:

- `stage-blocks` (default)
- `canonical-text`

Evaluation implementation:

- `stage-blocks` path uses `cookimport/bench/eval_stage_blocks.py`.
- `canonical-text` path uses `cookimport/bench/eval_canonical_text.py`.
- Canonical mode ensures canonical gold artifacts from export payloads via `cookimport/labelstudio/canonical_gold.py` when needed.
- Benchmark prediction generation now writes one authoritative stage run under `data/output/<timestamp>/...` and mirrors benchmark artifacts into the eval root.
- Scoring reads only one canonical prediction-run pointer pair from `manifest.json`: `stage_block_predictions_path` and `extracted_archive_path`.
- When line-role projection is enabled, those canonical pointers are set to the projection outputs during generation (no scorer-side source switching).

Benchmark eval artifacts include:

- `eval_report.json`
- `eval_report.md` (only when markdown writes are enabled)
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
Compare runs write:
- `comparison.json`
- `comparison.md`

When line-role prediction is enabled in prediction generation, prediction runs also write:
- `line-role-pipeline/line_role_predictions.jsonl`
- `line-role-pipeline/projected_spans.jsonl`
- `line-role-pipeline/stage_block_predictions.json`
- `line-role-pipeline/extracted_archive.json`
- `line-role-pipeline/guardrail_report.json`
- `raw/llm/<workbook_slug>/guardrail_report.json`
- `raw/llm/<workbook_slug>/guardrail_rows.jsonl`
- `line-role-pipeline/guardrail_changed_rows.jsonl`
- `line-role-pipeline/do_no_harm_diagnostics.json`
- `line-role-pipeline/do_no_harm_changed_rows.jsonl`
Prediction-generation now reuses authoritative line-role outputs from the stage-backed label bundle when available, and outside-recipe `KNOWLEDGE` evidence comes from Stage 7 non-recipe artifacts instead of a pass4 merge step.
Canonical line-role codex inflight is now resolved inside `canonical_line_roles.py`; `COOKIMPORT_LINE_ROLE_CODEX_MAX_INFLIGHT` remains the explicit override.
`atomic_block_splitter=off` keeps one line-role candidate per extracted block; `atomic_block_splitter=atomic-v1` enables deterministic boundary splitting before line-role labeling.
When canonical benchmark eval runs with `line_role_pipeline != off`, eval roots also write diagnostics under `line-role-pipeline/`:
- `line-role-pipeline/joined_line_table.jsonl`
- `line-role-pipeline/line_role_flips_vs_baseline.jsonl`
- `line-role-pipeline/slice_metrics.json`
- `line-role-pipeline/knowledge_budget.json`
- `line-role-pipeline/prompt_eval_alignment.md`
- stable sampled cutdowns keyed from one joined `sample_id` table

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
- Benchmark artifacts are rooted directly at the eval root.
- Benchmark also records processed cookbook outputs under configured processed output root.
- Typical eval-root extras: `processing_timeseries_prediction.jsonl`, `processing_timeseries_evaluation.jsonl`, optional `eval_profile.pstats`/`eval_profile_top.txt`, and `run_manifest.json`.
- If `line_role_pipeline != off`, benchmark manifests include line-role diagnostics pointers and an optional `line_role_pipeline_recipe_projection` summary.
- Manifest/return payloads no longer expose separate line-role stage/extracted scorer pointers; canonical scorer pointers are always `stage_block_predictions_path` and `extracted_archive_path`.
- New-format benchmark/prediction runs do not write or consume `pass4_merge_report.json`; Stage 7 ownership is already baked into the reused stage artifacts.
- Line-role manifests now also surface do-no-harm pointers:
  - `line_role_pipeline_do_no_harm_diagnostics_json`
  - `line_role_pipeline_do_no_harm_changed_rows_jsonl`
- Line-role manifests also surface explicit guardrail pointers:
  - `line_role_pipeline_guardrail_report_json`
  - `recipe_codex_guardrail_report_json`
  - `recipe_codex_guardrail_rows_jsonl`
  - `line_role_pipeline_guardrail_changed_rows_jsonl`

## 7) Current Gotchas

- `labelstudio-export` writes only explicit spans; unlabeled text is implicit and benchmarks treat missing gold coverage as `OTHER`.
- Overlapping exported spans are preserved. Stage-block and canonical-text scoring treat touched blocks/lines as multi-label gold, so macro/per-label metrics can lag overall accuracy.
- Adding a freeform label is a multi-surface change: update `cookimport/labelstudio/label_config_freeform.py`, `cookimport/labelstudio/eval_freeform.py`, `cookimport/staging/stage_block_predictions.py`, `cookimport/bench/eval_stage_blocks.py`, and `cookimport/bench/eval_canonical_text.py`.
- Reusing an older Label Studio project can leave stale `label_config`; if code labels and UI labels disagree, recreate or patch the project before changing scorers.
- `labelstudio-benchmark compare` accepts either all-method benchmark report roots/files or single `eval_report.json` inputs.

## 8) Troubleshooting Checklist

1. Confirm the run is freeform (`freeform-spans`) and not a legacy-scope project.
2. Confirm write consent and upload mode (`--allow-labelstudio-write`, `--no-upload`).
3. Confirm you are checking `data/golden/*` paths (not only `data/output/*`).
4. If overlap looks zero, test with `--force-source-match` to rule out source identity mismatch.
5. For split EPUB/PDF paths, verify merged block indices were rebased globally.
6. If process workers are denied during split conversion, confirm logs show thread fallback (`Process-based worker concurrency unavailable ... using thread-based worker concurrency.`); serial fallback should appear only if thread startup also fails.
7. For prelabel failures, read `prelabel_errors.jsonl` and `prelabel_report.json` first.

## 9) Explicitly Retired Features

These are intentionally not active runtime features:

- Label Studio task-scope execution branches for `pipeline` and `canonical-blocks`.
- Legacy `labelstudio-decorate` branch.
- Interactive benchmark upload mode (interactive benchmark is offline-only).
