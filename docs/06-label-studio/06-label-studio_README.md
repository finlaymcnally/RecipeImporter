---
summary: "Comprehensive source-of-truth for Label Studio import/export/eval workflows, history, and known pitfalls."
read_when:
  - Working on any Label Studio import/export/evaluation flow
  - Debugging unexpected uploads, zero-match evals, or output-path confusion
  - Deciding between pipeline, canonical, and freeform golden-set workflows
---

# Label Studio: Consolidated Technical Readme

This document merges all prior docs from `docs/06-label-studio/` and reconciles them with the current implementation in:

- `cookimport/labelstudio/`
- `cookimport/cli.py`

The goal is to preserve historical context (including failed/abandoned paths), while clearly separating:

- what is implemented now,
- what changed over time,
- what is known-bad or still unresolved.

## 1) Current Truth (Verified Against Code)

### 1.1 Scope and purpose

Label Studio integration is for creating/evaluating golden sets for cookbook extraction/parsing. It currently supports three task scopes:

- `pipeline`: label pipeline-generated chunks.
- `canonical-blocks`: label every extracted block with one class.
- `freeform-spans`: highlight arbitrary spans in text segments with labels.

Primary code paths:

- Import/upload: `cookimport/labelstudio/ingest.py`
- Export: `cookimport/labelstudio/export.py`
- Canonical eval: `cookimport/labelstudio/eval_canonical.py`
- Freeform eval: `cookimport/labelstudio/eval_freeform.py`
- CLI + interactive routing: `cookimport/cli.py`

### 1.2 Commands and defaults

CLI commands:

- `cookimport labelstudio-import`
- `cookimport labelstudio-export`
- `cookimport labelstudio-eval`
- `cookimport labelstudio-benchmark`

Default output roots:

- Non-interactive Label Studio commands default `--output-dir` to `data/golden`.
- Interactive menu (`cookimport` with no subcommand) still uses `cookimport.json.output_dir` for stage output, but routes Label Studio import/export/benchmark artifact roots to `data/golden`.
- Benchmark also writes stage-style processed cookbook outputs to `data/output` by default via `--processed-output-dir`.

### 1.3 Write safety and consent

Uploads are intentionally gated.

- Non-interactive:
  - `labelstudio-import` and `labelstudio-benchmark` require `--allow-labelstudio-write`.
  - Otherwise they fail fast.
- Interactive:
  - `labelstudio` import proceeds directly to upload (no separate upload confirmation prompt).
  - `labelstudio` import always uses overwrite semantics for resolved project names (`overwrite=True`, `resume=False`); there is no overwrite/resume chooser in this flow.
  - benchmark upload path still has an explicit confirmation prompt.
  - benchmark supports eval-only fallback (no upload) in interactive flow only.

Non-interactive overwrite/resume behavior is unchanged:
- `cookimport labelstudio-import` still exposes `--overwrite / --resume`.

Relevant code:

- `cookimport/cli.py` (`_require_labelstudio_write_consent`, benchmark/import flow)
- `cookimport/labelstudio/ingest.py` (`allow_labelstudio_write` guard)

### 1.4 Task generation and IDs

Resume/idempotence is based on deterministic scope-specific task IDs, not Label Studio internal IDs.

- Pipeline key: `chunk_id`
- Canonical key: `block_id`
- Freeform key: `segment_id`

Canonical block IDs:

- `urn:cookimport:block:{source_hash}:{block_index}`

Freeform segment IDs:

- `urn:cookimport:segment:{source_hash}:{start_block_index}:{end_block_index}`

Resume behavior:

- prior manifests and/or prior `label_studio_tasks.jsonl` are scanned,
- already-seen IDs are skipped.

### 1.5 Label configs (actual current sets)

Pipeline labels (`cookimport/labelstudio/label_config.py`):

- Content type: `tip`, `recipe`, `step`, `ingredient`, `fluff`, `other`, `mixed`
- Value/usefulness: `useful`, `neutral`, `useless`, `unclear`
- Optional tags include: `servings`, `pairs_well_with`, etc.

Canonical labels (`cookimport/labelstudio/label_config_blocks.py`):

- `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `TIP`, `NARRATIVE`, `OTHER`

Freeform labels (`cookimport/labelstudio/label_config_freeform.py`):

- `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `TIP`, `NOTES`, `VARIANT`, `YIELD_LINE`, `TIME_LINE`, `OTHER`
- explicitly preserves whitespace with `style="white-space: pre-wrap;"` for stable offsets.

### 1.6 Export contracts

Pipeline export produces:

- `exports/labelstudio_export.json` (raw payload)
- `exports/labeled_chunks.jsonl`
- `exports/golden_set_tip_eval.jsonl`
- optional `exports/skipped.jsonl`
- `exports/summary.json`

Canonical export produces:

- `exports/labelstudio_export.json`
- `exports/canonical_block_labels.jsonl`
- `exports/canonical_gold_spans.jsonl` (derived)
- `exports/summary.json`

Freeform export produces:

- `exports/labelstudio_export.json`
- `exports/freeform_span_labels.jsonl`
- `exports/freeform_segment_manifest.jsonl`
- `exports/summary.json`

Freeform span rows include offsets, label, touched block mapping, annotator/timestamp, and deterministic `span_id`.

### 1.7 Evaluation behavior

Canonical eval (`labelstudio-eval canonical-blocks`):

- compares predicted structural recipe spans from `label_studio_tasks.jsonl` vs `canonical_gold_spans.jsonl`.
- Jaccard overlap threshold default `0.5`.
- supports prefix-compatible source hash matching for older IDs.

Freeform eval (`labelstudio-eval freeform-spans`):

- compares predicted labeled ranges (mapped from pipeline chunks) vs gold freeform spans (mapped by touched block indices).
- strict metrics remain canonical benchmark numbers.
- adds:
  - `app_aligned` diagnostics
  - `classification_only` diagnostics
- supports `--force-source-match` to bypass source identity checks.

Output artifacts for both eval scopes:

- `eval_report.json`
- `eval_report.md`
- `missed_gold_spans.jsonl`
- `false_positive_preds.jsonl`

### 1.8 Benchmark command behavior

`labelstudio-benchmark` currently does:

1. select/find a freeform gold export,
2. infer/select source file,
3. run a pipeline `run_labelstudio_import(...)` prediction import,
4. co-locate prediction run under `<eval_output_dir>/prediction-run`,
5. run freeform eval and write report artifacts.

Important:

- CLI `labelstudio-benchmark` always imports/uploads prediction tasks (requires write consent).
- Eval-only mode exists in interactive flow (`cookimport` menu), not as a standalone non-interactive flag.

### 1.9 Parallel split-job behavior and reindexing

For large EPUB/PDF prediction imports, split jobs can run in parallel.

- planners reused from stage path (`plan_pdf_page_ranges`, `plan_job_ranges`)
- merge step rebases block-index fields by cumulative offsets to restore global block coordinates

This reindexing is critical; without it, freeform/canonical eval can report near-zero matches despite good extraction.

### 1.10 Artifact layout and run folders

Import run artifacts:

- `<output_dir>/<timestamp>/labelstudio/<book_slug>/...`
- Export run artifacts (default):
  - `<output_dir>/<project_slug>/exports/...`
  - `--run-dir` overrides this and writes into the specified run directory.
  - Existing manifests are still used to resolve `project_id` and validate task-scope alignment.

Benchmark eval artifacts:

- `<eval_output_dir>/...` (often under `data/golden/eval-vs-pipeline/<timestamp>/`)
- prediction artifacts moved to `<eval_output_dir>/prediction-run/`

Manifest includes:

- project metadata, task scope settings, uploaded count, IDs, source file, URL, and coverage.

### 1.11 Additional operational conventions

- Freeform source matching is strict by default (source identity must align). Use `--force-source-match` only when intentionally comparing renamed/cutdown variants.
- Benchmark gold discovery checks both:
- `data/output/**/exports/freeform_span_labels.jsonl`
- `data/golden/**/exports/freeform_span_labels.jsonl`
- Split-job `labelstudio-import` and `labelstudio-benchmark` support the same PDF/EPUB split controls as stage imports (`workers`, split workers, pages/spine per job).
- Progress callbacks include post-merge phases (archive/hash, processed-output writes, chunk/task generation, upload batching) so long runs continue surfacing advancing status.
- Interactive `labelstudio` export resolves credentials first, then fetches project titles for a picker UI (showing a detected type tag beside each project when available). It now auto-uses the selected project's detected type as export scope and only prompts for scope when detection is `unknown` (or when the project name is typed manually).
- Interactive Label Studio import/export credential resolution order is: CLI/env values first, then saved `cookimport.json` values, then one-time prompt (which persists back to `cookimport.json`).

## 2) Known-Bad / High-Risk / Common Confusion

### 2.1 Timestamp format mismatch in prior docs

Current code uses timestamp format with dots in time:

- `%Y-%m-%d_%H.%M.%S`

Several previous docs claimed a colon-separated time format. That claim was incorrect for current code.

### 2.2 Benchmark side-effect misunderstanding

Users often expected benchmark to be “offline scoring only.”

Current reality:

- non-interactive benchmark always performs a prediction import upload before scoring,
- unless using interactive eval-only path.

### 2.3 Source mismatch leading to zero overlap

Freeform eval can collapse to zero due to source hash/name mismatch even if ranges are aligned.

Mitigation:

- use `--force-source-match` when intentionally comparing renamed/cutdown variants.

### 2.4 Freeform taxonomy drift

Historical docs/labels used `NARRATIVE` and/or `KNOWLEDGE` in freeform contexts.

Current freeform config does not include those labels. Eval normalizes legacy exports:

- `KNOWLEDGE -> TIP`
- `NOTE -> NOTES`
- `NARRATIVE -> OTHER`

### 2.5 Incomplete live validation risk

Plan docs repeatedly note that full live manual LS transcript coverage was not comprehensively recorded during implementation phases.

Mitigation:

- rely on deterministic unit tests for regressions,
- perform manual live smoke checks when modifying config/task payload shapes.

### 2.6 PDF box-annotation workflow is not implemented

`PDF-freeform-DO-LATER.md` described a future “draw boxes on page images” workflow.

Current status:

- planning only,
- not implemented in current Label Studio integration.

Do not assume this path exists when debugging current flows.

## 3) Historical Timeline (What Changed, in Order)

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
- `docs/understandings/2026-02-15_21.35.47-interactive-labelstudio-overwrite-rule.md`
- `docs/understandings/2026-02-15_21.52.54-interactive-labelstudio-import-auto-upload.md`
- `docs/understandings/2026-02-15_22.00.23-interactive-labelstudio-export-project-picker.md`
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

### Abandoned/deferred branch: PDF page box annotation

From `PDF-freeform-DO-LATER.md`:

- rectangle-on-page-images workflow investigated and documented,
- left explicitly as do-later planning, not part of current code.

## 4) Where Things Live

Core package:

- `cookimport/labelstudio/client.py`: API client wrapper
- `cookimport/labelstudio/ingest.py`: import flow, task generation dispatch, resume/upload, artifacts
- `cookimport/labelstudio/export.py`: export + JSONL shaping
- `cookimport/labelstudio/chunking.py`: pipeline chunk generation helpers
- `cookimport/labelstudio/block_tasks.py`: canonical task builder
- `cookimport/labelstudio/freeform_tasks.py`: freeform task builder + offset/block mapping
- `cookimport/labelstudio/canonical.py`: canonical derived span rules
- `cookimport/labelstudio/eval_canonical.py`: canonical metrics/report
- `cookimport/labelstudio/eval_freeform.py`: freeform metrics/report
- `cookimport/labelstudio/label_config*.py`: Label Studio XML configs

CLI surfaces:

- `cookimport/cli.py`

Tests:

- `tests/test_labelstudio_canonical.py`
- `tests/test_labelstudio_freeform.py`
- `tests/test_labelstudio_export.py`
- `tests/test_labelstudio_import_naming.py`
- `tests/test_labelstudio_benchmark_helpers.py`
- `tests/test_labelstudio_ingest_parallel.py`
- `tests/test_labelstudio_chunking.py`

## 5) Practical Runbook

### 5.1 Setup

- Start Label Studio.
- Set `LABEL_STUDIO_URL` and `LABEL_STUDIO_API_KEY`.

### 5.2 Import examples

Pipeline:

```bash
cookimport labelstudio-import data/input/book.epub \
  --task-scope pipeline \
  --chunk-level both \
  --allow-labelstudio-write
```

Canonical:

```bash
cookimport labelstudio-import data/input/book.epub \
  --task-scope canonical-blocks \
  --context-window 1 \
  --allow-labelstudio-write
```

Freeform:

```bash
cookimport labelstudio-import data/input/book.epub \
  --task-scope freeform-spans \
  --segment-blocks 40 \
  --segment-overlap 5 \
  --allow-labelstudio-write
```

### 5.3 Export examples

```bash
cookimport labelstudio-export --project-name "Project" --export-scope pipeline
cookimport labelstudio-export --project-name "Project" --export-scope canonical-blocks
cookimport labelstudio-export --project-name "Project" --export-scope freeform-spans
```

### 5.4 Eval examples

```bash
cookimport labelstudio-eval canonical-blocks \
  --pred-run data/golden/<ts>/labelstudio/<book_slug> \
  --gold-spans data/golden/<...>/exports/canonical_gold_spans.jsonl \
  --output-dir data/golden/<...>/eval-canonical
```

```bash
cookimport labelstudio-eval freeform-spans \
  --pred-run data/golden/<ts>/labelstudio/<book_slug> \
  --gold-spans data/golden/<...>/exports/freeform_span_labels.jsonl \
  --output-dir data/golden/<...>/eval-freeform \
  --force-source-match
```

### 5.5 Benchmark example

```bash
cookimport labelstudio-benchmark --allow-labelstudio-write
```

Optional tuning:

- `--workers`
- `--pdf-split-workers`
- `--epub-split-workers`
- `--pdf-pages-per-job`
- `--epub-spine-items-per-job`
- `--processed-output-dir`
- `--overlap-threshold`
- `--force-source-match`

## 6) Design Decisions Worth Preserving

- Keep three workflows as separate project contracts (pipeline/canonical/freeform), not one overloaded project.
- Keep deterministic URN-based task identifiers per scope.
- Keep freeform offsets tied to exact uploaded text and source map.
- Keep benchmark artifacts co-located with eval outputs for reproducibility.
- Keep write consent explicit to avoid accidental Label Studio side effects.
- Keep split-job global block index rebasing; removing it reintroduces zero-match false negatives.

## 7) What To Check First When Things Break

1. Is `task_scope`/`export_scope`/`eval scope` aligned for the same project/run?
2. Did upload actually happen (write consent on, not cancelled)?
3. Are you looking under `data/golden` (not only `data/output`)?
4. Did source identity mismatch collapse freeform overlap? Try `--force-source-match`.
5. For split PDF/EPUB jobs, confirm merged block indices are globally rebased.
6. Confirm project naming did not silently dedupe to `-1`, `-2` and send you to a different project than expected.

## 8) Open Gaps / Future Work

- Add explicit non-interactive eval-only benchmark path (currently interactive-only).
- Add stronger live-manual validation transcripts for each scope after config changes.
- If PDF page box workflow is revived, treat as a separate task scope and keep this doc explicit about status.

## 9) Consolidation Findings (Preserved)

- `labelstudio-benchmark` (CLI) is upload-first by design and always calls `run_labelstudio_import(...)`; true eval-only exists only in interactive menu mode.
- Resume/idempotence is keyed by deterministic task IDs (`chunk_id`/`block_id`/`segment_id`), not Label Studio task IDs.
- Split EPUB/PDF job merges must rebase block indices globally before chunk/task generation; otherwise eval can produce false zero-match results.
- Freeform eval has three layers now: strict metrics, `app_aligned` diagnostics, and `classification_only` diagnostics.
- Current timestamp folders in code use dot-separated time (`%Y-%m-%d_%H.%M.%S`), which previously drifted from some docs.
