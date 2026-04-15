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

- `cookimport/labelstudio/ingest_flows/prediction_run.py` (offline prediction-run/task-generation owner)
- `cookimport/labelstudio/ingest_flows/upload.py` (live Label Studio upload owner)
- `cookimport/labelstudio/ingest_support.py` (shared helper surface consumed by the flow package)
- `cookimport/labelstudio/ingest_flows/` (offline prediction-run, upload, normalization, split-merge, and artifact ownership)
- `cookimport/labelstudio/export.py`
- `cookimport/labelstudio/row_gold.py`
- `cookimport/labelstudio/migrate_to_source_rows.py`
- `cookimport/labelstudio/eval_freeform.py`
- `cookimport/labelstudio/prelabel.py`
- `cookimport/labelstudio/freeform_tasks.py`
- `cookimport/labelstudio/archive.py`
- `cookimport/labelstudio/client.py`
- `cookimport/labelstudio/label_config_freeform.py`
- `cookimport/labelstudio/models.py`
- `cookimport/cli.py`

Nearby code used directly by Label Studio benchmark/eval flow:

- `cookimport/bench/eval_source_rows.py`
- `cookimport/bench/prediction_records.py`
- `cookimport/analytics/perf_report.py`

Label-first runtime seam used by benchmark/import flows:

- `cookimport/parsing/label_source_of_truth.py`
- `cookimport/parsing/recipe_span_grouping.py`
- `cookimport/staging/import_session.py` (honest top-level re-export for the shared session entrypoint/result types)
- `cookimport/staging/import_session_contracts.py` (shared public result dataclass/types for the session flows)
- `cookimport/staging/import_session_flows/` (shared stage-session runtime ownership)

## 1) Current Scope and Commands

### 1.1 Scope boundary

Active Label Studio runtime scope is `freeform-spans`.

- Import writes `task_scope: freeform-spans` manifests.
- Export accepts `freeform-spans` only and rejects any other project/manifest/payload scope.
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
- Interactive Label Studio import includes freeform prelabel mode selection, but labeling style is fixed to actual row spans.
- CLI import exposes `--upload-batch-size` (default `200`) and threads it directly into the upload loop; callers can shrink batches without editing repo code.
- Interactive export resolves credentials, fetches project titles, and shows detected type tags for operator context.
- Interactive benchmark is offline-only and offers:
  - single offline run,
  - all-method offline sweep.
- Interactive benchmark routes extractor-independent scoring to `labelstudio-benchmark --eval-mode source-rows`.
- The interactive gold-export picker shortens normal `.../<book>/exports/<file>` paths to the book slug for display, while keeping the older relative-path fallback for nonstandard layouts.
- Interactive gold-export discovery ignores archived `live_row_gold_backups/` exports so benchmark pickers and matched-book discovery stay focused on the canonical pulled export for each book.
- When a chosen gold export implies a matching source file, interactive benchmark uses that inferred source automatically; the manual source picker appears only when inference fails.
- Source inference must prefer `exports/canonical_manifest.json` over the parent export `run_manifest.json` because migrated row-gold exports can record `source.path=source_rows.jsonl` in the run manifest while the canonical manifest still carries the real original input filename.
- Row-native migrated exports may carry `source_rows.jsonl` in the freeform JSONL artifacts; interactive source inference should prefer `exports/canonical_manifest.json` when present so migrated gold still auto-resolves back to the original input file.
- The offline prediction-run seam behind `labelstudio-benchmark --no-upload` accepts the hidden `knowledge_inline_repair_transcript_mode` run-setting knob too, so helper-built benchmark kwargs can flow all the way into prediction generation without signature drift.

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
- `source_map.rows[*]` carries the authoritative row-native mapping for that focus text, including stable `row_id`, row ordinals, and offsets.
- New task generation writes only `source_map.rows[*]` plus `context_before_rows` / `context_after_rows`.
- Some legacy pulled exports and fixtures may still carry `blocks` / `context_*_blocks`; compatibility readers may accept them, but they are not part of the supported new-task contract.
- Import writes `coverage.json` from focus + context block coverage and fails when extracted text is empty.

## 4) Freeform Prelabel Contracts

### 4.1 Modes

`--prelabel-granularity` is span-only.

- `span` (actual freeform): quote/offset span resolution for sub-block highlights

Span mode keeps deterministic normalization and offset integrity.

Freeform label set includes `HOWTO_SECTION` for in-recipe subsection headers (for example `TO SERVE` / `FOR THE SAUCE`).
Scoring behavior:
- freeform eval and stage-block benchmark mode resolve `HOWTO_SECTION` into `INGREDIENT_LINE` or `INSTRUCTION_LINE` using nearby context.
- source-row benchmark mode keeps `HOWTO_SECTION` as an explicit scored label.

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

When discovery/config has no concrete model, interactive prelabel keeps the honest default/custom choices instead of inventing a repo-pinned fallback id.

Thinking effort uses `--codex-thinking-effort` (alias `--codex-reasoning-effort`) and maps to CodexFarm reasoning-effort overrides.

## 5) Export, Eval, and Benchmark Contracts

### 5.1 Export artifacts

`labelstudio-export` writes:

- `exports/labelstudio_export.json`
- `exports/freeform_span_labels.jsonl`
- `exports/freeform_segment_manifest.jsonl`
- `exports/row_gold_labels.jsonl`
- `exports/row_gold_conflicts.jsonl`
- `exports/summary.json`
- `run_manifest.json` (run root)

`summary.json` includes deduped recipe-header diagnostics from normalized `RECIPE_TITLE` spans.

Row-authoritative benchmark note:
- `freeform_span_labels.jsonl` remains the raw archive of what the annotator drew in Label Studio.
- `row_gold_labels.jsonl` is the benchmark-authoritative gold. It is exhaustive for task focus rows: explicit annotated span labels win, and any focus row left unlabeled in Label Studio exports as `OTHER`. Benchmarks and row prediction diagnostics should trace one `row_id` end-to-end through scoring and mismatch reports.
- `data.source_map.rows` is the authoritative task mapping for new freeform tasks.
- New exports do not write `block_gold_labels.jsonl`.
- Older pulled exports can be batch-migrated in place with `python scripts/migrate_pulled_labelstudio_gold_to_source_rows.py`. That script writes `exports/source_rows.jsonl`, migrated row gold files, `exports/row_seed_tasks.jsonl`, and updates the export summary/manifest to point at the new row-native artifacts.
- Row-gold migration is now row-native only. `migrate_to_source_rows.py` trusts exact `touched_blocks[].row_id` plus row-local `segment_start` / `segment_end` spans and ignores touched entries that do not name a real row. Old block-wide reprojection is intentionally unsupported because it can smear later rows in the same source block backward onto earlier rows and create fake conflicts/ambiguous rows.
- When replacement row-gold projects already exist in Label Studio and may contain newer edits than the archived pulled export, run the migration script with `--prefer-live-row-gold`. It exports the current replacement project into `live_row_gold_backups/<timestamp>_project-<id>/`, then remigrates from that live freeform export so refreshed projects do not discard newer annotation work.
- To recreate those migrated sets as fresh editable Label Studio gold projects, run `python scripts/upload_row_gold_seed_projects_to_labelstudio.py`. That uploader reads `exports/row_seed_tasks.jsonl`, converts the seeded row results into real Label Studio `annotations`, rewrites seeded result ids into Label Studio-safe CSS-friendly ids so text highlights render correctly, and by default also mirrors the same rows into `predictions` plus enables interactive preannotation reveal because some Label Studio builds surface imported overlays more reliably through the prediction path. The migrated row-gold seed tasks now use non-overlapping 120-row focus windows so adjacent tasks do not duplicate labelable rows. The uploader now also exports the just-created project back from Label Studio and verifies that the stored annotation label counts still match the seed tasks; on mismatch it retries once with a clean recreate instead of silently leaving a corrupted project behind. It writes `exports/row_gold_labelstudio_project.json` plus a batch upload summary under `data/golden/pulled-from-labelstudio/`.

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
values are inferred from prediction-run metadata. Prediction-run line-role diagnostics now distinguish
route-layer and final-semantic views: prediction runs may write both
`line-role-pipeline/line_role_predictions.jsonl` (route-layer compatibility view) and
`line-role-pipeline/semantic_line_role_predictions.jsonl` (final nonrecipe-authority semantic view used
by benchmark joins when present).
New eval manifests should record the prediction-run root under `artifacts.artifact_root_dir`; `pred_run_dir` is only a stale historical alias and should not be reintroduced on new writes.

### 5.3 Benchmark behavior

`labelstudio-benchmark` supports:

Canonical line-role projection note:
- prediction-run `line_role_predictions.jsonl` is still the route-label artifact. Outside recipe, it should show `NONRECIPE_CANDIDATE` / `NONRECIPE_EXCLUDE`, not final `KNOWLEDGE` / `OTHER`.
- when `semantic_line_role_predictions.jsonl` exists, benchmark eval prefers that final-semantic view for joined reviewer diagnostics and materializes it as the local benchmark `line_role_predictions.jsonl`.
- row-level `NONRECIPE_EXCLUDE` now survives that semantic projection too: when one source block mixes an excluded setup row with neighboring candidate rows that finalize as `knowledge`, the benchmark projection/scorer must keep the excluded row as final `OTHER` instead of letting block-level authority stamp the whole block `KNOWLEDGE`.
- `line-role-pipeline/stage_block_predictions.json` is the scored benchmark view. It stays in dense canonical `line_index` coordinates for scoring, while `projected_spans.jsonl` / `extracted_archive.json` preserve source block provenance, and it records unresolved outside-recipe candidates explicitly under `unresolved_candidate_*` metadata.
- In other words, an unresolved outside-recipe candidate may still appear as provisional `OTHER` in projected scoring artifacts, but benchmark scoring excludes that row via the unresolved-candidate metadata until explicit final non-recipe authority exists.

- upload path (prediction import + eval)
- offline path (`--no-upload`)
- eval-only from prediction records (`--predictions-in`)
- prediction-record output (`--predictions-out`)
- compare action for benchmark runs (`labelstudio-benchmark compare`)
- line-role gating (`--line-role-gated`) for row-based Milestone-5 regression checks
- benchmark prediction-generation scratch stays inside the resolved `eval_output_dir` artifact root, so one benchmark session does not spill sibling timestamp roots under `data/golden/benchmark-vs-golden`
- when processed outputs are requested, benchmark/prediction runs reuse the stage-produced authoritative label artifacts (`label_deterministic`, `label_refine`, `recipe_boundary`) and mirror the resulting `stage_block_predictions.json` into the prediction run root
- those processed outputs now also include `recipe_authority/<workbook_slug>/recipe_block_ownership.json`, and prediction-run scoring inherits the same ownership invariant: recipe-local evidence may not overlap final outside-recipe `KNOWLEDGE`
- prediction generation no longer runs a second post-stage diagnostic `label_atomic_lines(...)` pass; freeform span projection reuses the authoritative labeled-line bundle from stage or builds the same bundle once in-memory for offline-only runs
- source-row benchmark scoring follows the prediction manifest pointer pair; when authoritative line labels are projected, outside-recipe `KNOWLEDGE` versus `OTHER` still comes from the final non-recipe authority after knowledge refinement, and telemetry reports `mode=final_authority_projection`
- source-row benchmark eval reports now also serialize structural segmentation metrics beside the older overlap-style `boundary` counts, so paired benchmark comparisons can tell whether a gain came from line classification, boundary structure, or both
- interactive offline benchmark auto-publication of `upload_bundle_v1/` is Codex-only; fully vanilla single-book and matched-book runs stay local and skip Oracle bundle/upload startup

Execution modes:

- `pipelined` (fixed)

### 5.4 Codex approval and zero-token checks

- `labelstudio-benchmark` and `labelstudio-import` now only expose live execute mode for Codex-backed surfaces.
- Use the normal execute path with `--codex-farm-cmd scripts/fake-codex-farm.py` when you need a zero-token rehearsal of worker directories, file handoffs, validation, and promotion wiring.
- `labelstudio-import --prelabel` is a separate Codex-backed surface from recipe/line-role benchmark settings.
  - Do not assume recipe/line-role decision metadata or approval checks automatically cover prelabel behavior.
  - If operator-intent policy changes, review prelabel command wiring separately.

Codex execution notes:

- Non-interactive live benchmark runs still require `--allow-codex` when Codex-backed surfaces are enabled.
- `labelstudio-benchmark` also requires `--benchmark-codex-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION` for that non-interactive live path, and agent-run environments are blocked from that live benchmark path.

Eval modes:

- `source-rows`

Evaluation implementation:

- `source-rows` path uses `cookimport/bench/eval_source_rows.py`.
- Benchmark prediction generation now writes one authoritative stage run under `data/output/<timestamp>/...` and mirrors benchmark artifacts into the eval root.
- Scoring reads only one prediction-run pointer pair from `manifest.json`: `stage_block_predictions_path` and `extracted_archive_path`.
- When line-role projection is enabled, those pointers are set to the projection outputs during generation (no scorer-side source switching).

Benchmark eval artifacts include:

- `eval_report.json`
- `eval_report.md` (only when markdown writes are enabled)
- `missed_gold_blocks.jsonl`
- `wrong_label_blocks.jsonl`
- `run_manifest.json`
- interrupted benchmark runs now also write `benchmark_status.json` plus `partial_benchmark_summary.json`; when prediction-manifest telemetry is already present, they also try to write `prompt_budget_summary.json` before returning control
  - the command-layer recovery/finalization helpers now live in `cookimport/cli_support/labelstudio_benchmark_recovery.py`, while transient eval-output pruning lives in `cookimport/cli_support/labelstudio_benchmark_artifacts.py`

Source-row mode also writes row/line diagnostics:

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
Prediction-generation now reuses authoritative recipe-local line-role outputs from the stage-backed label bundle when available. `projected_spans.jsonl` and `extracted_archive.json` stay line-level reviewer artifacts, while `stage_block_predictions.json` is rebuilt as block-level scoring evidence from those projected rows. Outside-recipe `KNOWLEDGE` versus `OTHER` comes from the final non-recipe authority that import produced after any enabled refinement step.
`line_role_predictions.jsonl` is intentionally earlier in the contract than those scored artifacts: recipe-local labels stay semantic there, but outside-recipe labels stay route-first until knowledge finalization resolves them.
Those authoritative and projected line-role rows now carry `decided_by`, `reason_tags`, and `escalation_reasons`; scalar trust/confidence fields are gone from this seam.
Final non-recipe authority is still only a binary outside-recipe seam. It may arbitrate rows already labeled `OTHER` or `KNOWLEDGE`, but it must not collapse clear outside-recipe structural labels such as recipe-tail `RECIPE_NOTES` back into `OTHER`.
Stage-backed `recipe_boundary/<workbook_slug>/span_decisions.json` is the recipe-level reviewer/debug companion for the same reason-based escalation contract.
Canonical line-role codex inflight is now resolved inside `canonical_line_roles.py`; `COOKIMPORT_LINE_ROLE_CODEX_MAX_INFLIGHT` remains the explicit override.
`atomic_block_splitter=off` keeps one line-role candidate per extracted block; `atomic_block_splitter=atomic-v1` enables deterministic boundary splitting before line-role labeling.
When source-row benchmark eval runs with `line_role_pipeline != off`, eval roots also write diagnostics under `line-role-pipeline/`:
- `line-role-pipeline/joined_line_table.jsonl`
- `line-role-pipeline/line_role_flips_vs_reference.jsonl` (`line_role_flips_vs_baseline.jsonl` is the legacy filename for older runs)
- `line-role-pipeline/slice_metrics.json`
- `line-role-pipeline/routing_summary.json`
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
- Row-gold replacement projects ending in `source_rows_gold` are a special case: export should route back to the original project/book slug from the project title instead of writing into a generic `source_rows/` folder.
- `--run-dir` overrides destination.
- Run root also carries `run_manifest.json`.

### 6.3 Benchmark

- Eval root: `data/golden/benchmark-vs-golden/<timestamp>/...`
- Benchmark artifacts are rooted directly at the eval root.
- Benchmark also records processed cookbook outputs under configured processed output root.
- Typical eval-root extras: `processing_timeseries_prediction.jsonl`, `processing_timeseries_evaluation.jsonl`, optional `eval_profile.pstats`/`eval_profile_top.txt`, and `run_manifest.json`.
- interrupted eval roots now keep the same root shape and add `benchmark_status.json` plus `partial_benchmark_summary.json` so a killed run still leaves one top-level status/pointer package instead of only raw worker trees
- If `line_role_pipeline != off`, benchmark manifests include line-role diagnostics pointers and an optional `line_role_pipeline_recipe_projection` summary.
- Manifest/return payloads no longer expose separate line-role stage/extracted scorer pointers; canonical scorer pointers are always `stage_block_predictions_path` and `extracted_archive_path`.
- Eval/benchmark manifests should resolve the prediction-run directory from `artifacts.artifact_root_dir`; do not add new readers that prefer eval-root-relative fallbacks when the prediction artifacts live elsewhere.
- New-format benchmark/prediction runs do not write or consume the old knowledge-stage merge report; non-recipe route/finalize ownership is already baked into the reused stage artifacts.

## 7) Current Gotchas

- `labelstudio-export` writes only explicit spans; unlabeled text is implicit and benchmarks treat missing gold coverage as `OTHER`.
- Overlapping exported spans are preserved. Stage-block and source-row scoring treat touched blocks/lines as multi-label gold, so macro/per-label metrics can lag overall accuracy.
- Adding a freeform label is a multi-surface change: update `cookimport/labelstudio/label_config_freeform.py`, `cookimport/labelstudio/eval_freeform.py`, `cookimport/staging/stage_block_predictions.py`, and `cookimport/bench/eval_source_rows.py`.
- Reusing an older Label Studio project can leave stale `label_config`; if code labels and UI labels disagree, recreate or patch the project before changing scorers.
- `labelstudio-benchmark compare` accepts either all-method benchmark report roots/files or single `eval_report.json` inputs.
- If recipe-tail storage/use notes are scoring as `OTHER`, check both seams:
  - deterministic line-role note recovery in `canonical_line_roles.py`
  - final non-recipe authority projection in `labelstudio/ingest_flows/artifacts.py`

## 8) Troubleshooting Checklist

1. Confirm the run is freeform (`freeform-spans`) and not an older-scope project.
2. Confirm write consent and upload mode (`--allow-labelstudio-write`, `--no-upload`).
3. Confirm you are checking `data/golden/*` paths (not only `data/output/*`).
4. If overlap looks zero, test with `--force-source-match` to rule out source identity mismatch.
5. For split EPUB/PDF paths, verify merged block indices were rebased globally.
6. If process workers are denied during split conversion, confirm logs show thread fallback (`Process-based worker concurrency unavailable ... using thread-based worker concurrency.`); serial fallback should appear only if thread startup also fails.
7. For prelabel failures, read `prelabel_errors.jsonl` and `prelabel_report.json` first.

## 9) Explicitly Retired Features

These are intentionally not active runtime features:

- Label Studio task-scope execution branches for `pipeline` and `canonical-blocks`.
- Removed `labelstudio-decorate` branch.
- Interactive benchmark upload mode (interactive benchmark is offline-only).
