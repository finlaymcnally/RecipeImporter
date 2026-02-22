---
summary: "Code-verified Label Studio import/export/eval reference for current behavior, contracts, and known pitfalls."
read_when:
  - Working on any Label Studio import/export/evaluation flow
  - Debugging unexpected uploads, zero-match evals, or output-path confusion
  - Deciding between pipeline, canonical, and freeform golden-set workflows
---

# Label Studio: Technical Readme

This document merges all prior docs from `docs/06-label-studio/` and reconciles them with the current implementation in:

- `cookimport/labelstudio/`
- `cookimport/cli.py`

This document is the current source of truth for implemented Label Studio behavior.

Use `docs/06-label-studio/06-label-studio_log.md` for historical architecture versions, builds, and fix attempts when work starts looping.

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
- `cookimport labelstudio-decorate`
- `cookimport labelstudio-eval`
- `cookimport labelstudio-benchmark`

Default output roots:

- Non-interactive Label Studio commands default `--output-dir` to `data/golden`.
- Interactive menu (`cookimport` with no subcommand) still uses `cookimport.json.output_dir` for stage output, but routes Label Studio import/export/decorate/benchmark artifact roots to `data/golden`.
- Benchmark also writes stage-style processed cookbook outputs to `data/output` by default via `--processed-output-dir`.

### 1.3 Write safety and consent

Uploads are intentionally gated.

- Non-interactive:
  - `labelstudio-import` requires `--allow-labelstudio-write`.
  - `labelstudio-decorate` requires `--allow-labelstudio-write` unless `--no-write` dry-run mode is used.
  - `labelstudio-benchmark` requires `--allow-labelstudio-write` only in upload mode.
  - `labelstudio-benchmark --no-upload` is fully offline and skips credential resolution + upload.
  - Otherwise they fail fast.
- Interactive:
  - `labelstudio` import proceeds directly to upload (no separate upload confirmation prompt).
  - `labelstudio` import always uses overwrite semantics for resolved project names (`overwrite=True`, `resume=False`); there is no overwrite/resume chooser in this flow.
  - Interactive freeform import includes an AI prelabel mode picker (off, strict/allow-partial annotations, advanced predictions modes) and prints `prelabel_report.json` when prelabel is enabled.
  - Interactive freeform import also includes a Codex model picker (`use default`, `gpt-5.3-codex`, `custom`); token usage tracking is always enabled for AI labeling runs.
  - Interactive `labelstudio_decorate` defaults to dry-run and only writes annotations after explicit write confirmation.
  - benchmark upload does not ask a second confirmation; choosing upload mode is treated as explicit intent.
  - benchmark supports eval-only fallback (no upload) in interactive flow.

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

- `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `YIELD_LINE`, `TIME_LINE`, `RECIPE_NOTES`, `RECIPE_VARIANT`, `KNOWLEDGE`, `OTHER`
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

### 1.6.1 Freeform prelabel/decorate contracts

- `labelstudio-import --task-scope freeform-spans --prelabel` can attach completed freeform annotations before upload.
- Prelabel offset generation is block-index based and deterministic:
  - LLM output -> `{block_index, label}`
  - block index -> char offsets from `data.source_map.blocks[*].segment_start/end`
  - no whitespace normalization is allowed in this path.
- Import upload mode `--prelabel-upload-as`:
  - `annotations` (default): attempts inline completed annotations in import payload.
  - `predictions`: uploads model predictions instead of completed annotations.
- If inline `annotations` upload fails, import auto-falls back to:
  - upload plain tasks,
  - then create annotations per task through Label Studio API.
- Prelabel artifacts written in run root:
  - `prelabel_report.json`
  - `prelabel_errors.jsonl`
- Progress callbacks now report `Running freeform prelabeling... task X/Y` so CLI spinners show per-task progress while AI labels are generated.
- CLI status wrappers now add a live elapsed suffix (for example `(17s)`) after ~8 seconds with no phase-message change, so long steps remain visibly active instead of appearing stuck.
- Codex CLI invocation for prelabel/decorate defaults to non-interactive `codex exec -`; plain `codex` values auto-retry with `exec -` when stderr reports `stdin is not a terminal`.
- Prelabel/decorate runs accept explicit model selection via `--codex-model`; when omitted they resolve model from `COOKIMPORT_CODEX_MODEL` then Codex config (`~/.codex-alt/config.toml`, `~/.codex/config.toml`).
- Token usage tracking is always enabled for prelabel/decorate runs, using Codex JSON event parsing to record aggregate `input_tokens`, `cached_input_tokens`, and `output_tokens` in run reports.
- `labelstudio-decorate`:
  - fetches existing tasks/annotations from a freeform project,
  - requests additive labels only (for `--add-labels`),
  - creates a new merged annotation (base spans preserved, new spans added),
  - writes local report artifacts:
    - `decorate_report.json`
    - `decorate_errors.jsonl`
  - supports dry-run mode via `--no-write`.
  - progress callbacks report `Decorating freeform tasks... task X/Y` while scanning tasks.

#### 1.6.1.1 Prompt, parsing, and context management (code-verified)

AI prelabeling for `freeform-spans` is **one fresh prompt per task** (per segment) with **no cross-task conversation memory**.
The only “context window” is the task’s segment text (a chunk of consecutive extracted blocks).

Where it happens:

- Task segmentation: `cookimport/labelstudio/freeform_tasks.py` (`segment_blocks`, `segment_overlap`)
- Prompt + parsing + span construction: `cookimport/labelstudio/prelabel.py`
- End-to-end wiring (generate artifacts, then upload + fallback): `cookimport/labelstudio/ingest.py`

**Context management (your question):**

- Each segment task is labeled independently. There is no rolling chat history; every call is a brand new Codex CLI subprocess fed a single prompt string on stdin (`subprocess.run(..., input=prompt, ...)`).
- The “chunking” is done before the LLM call: freeform tasks are built by concatenating `segment_blocks` extracted blocks (default 40) with a separator (`\\n\\n`), and `segment_overlap` repeats the last N blocks into the next task (default 5). Overlap repeats text *across tasks*, but the model never sees prior prompts unless that text is repeated inside the current prompt.
- There is no incremental “continue where you left off” prompting. It’s many small/fixed prompts, not one ever-growing prompt.
- A prompt/response cache can make reruns *look* stateful: `CodexCliProvider` stores `{prompt, response}` JSON files under `prelabel_cache/` keyed by a hash of `(codex_cmd, track_usage flag, prompt text)`. Delete the cache dir to force fresh completions.

**What the model is asked to do (the literal prompt template):**

Built in `cookimport/labelstudio/prelabel.py:_build_prompt(...)`. The prompt is plain text and contains one JSON object per block (with `block_index` and the block’s exact text slice).

```text
You label cookbook text blocks.
Return STRICT JSON only.
Output format: [{"block_index": <int>, "label": "<LABEL>"}].
Allowed labels: RECIPE_TITLE, INGREDIENT_LINE, INSTRUCTION_LINE, YIELD_LINE, TIME_LINE, RECIPE_NOTES, RECIPE_VARIANT, KNOWLEDGE, OTHER.
Segment id: urn:cookimport:segment:<source_hash>:<start_block_index>:<end_block_index>
Blocks:
{"block_index": 12, "text": "…exact block text…"}
{"block_index": 13, "text": "…exact block text…"}
...
```

Decorate (“augment”) mode adds extra instructions + current labels per block to the same one-shot prompt:

```text
Mode: augment existing annotations.
Only add labels from: KNOWLEDGE, RECIPE_NOTES.
Existing labels per block:
- block_index=12: ['INGREDIENT_LINE']
- block_index=13: ['INSTRUCTION_LINE']
```

**Output parsing (tolerant, but prompt asks for strict JSON):**

- The parser extracts the first JSON array/object embedded anywhere in stdout (`extract_first_json_value(...)`), then accepts a few wrapper shapes (top-level list, or dict with keys like `selections` / `labels` / `items` / `blocks`).
- Each item must include `block_index` and `label` (aliases like `tag`/`category` are also accepted). Labels are normalized (`TIME` -> `TIME_LINE`, `YIELD` -> `YIELD_LINE`, etc) and anything not in `FREEFORM_ALLOWED_LABELS` is dropped.

**Span generation (important nuance):**

- Although the Label Studio project is a “freeform span highlight” UI, the AI prelabeler currently generates **block-level spans**: each `{block_index, label}` becomes a span covering the *entire* extracted block text range inside the segment (`start/end` come directly from `data.source_map.blocks[*].segment_start/segment_end`).
- The annotation `result[].value.text` is taken from `segment_text[start:end]` and must match exactly; this is why no whitespace normalization is allowed and the LS `<Text ... style="white-space: pre-wrap;">` config is required.

#### 1.6.1.2 Upload modes + fallback (mechanics)

When `--prelabel` is enabled:

1. `generate_pred_run_artifacts(...)` attaches `task["annotations"] = [annotation]` for each successfully prelabelled segment task.
2. `run_labelstudio_import(...)` uploads tasks in batches:
   - `--prelabel-upload-as annotations` (default): try importing tasks with inline `annotations`.
   - If Label Studio rejects inline annotations, it automatically:
     - re-uploads the same tasks with annotations stripped,
     - then creates annotations per task via the Label Studio API by mapping deterministic `segment_id` to Label Studio’s internal `task.id`.
   - `--prelabel-upload-as predictions` (advanced): converts the first annotation into a Label Studio `predictions[]` entry (`model_version="cookimport-prelabel"`, `score=1.0`), which is useful for debugging/model comparison but won’t necessarily mark tasks “completed”.

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

`labelstudio-benchmark` currently supports two non-interactive paths:

1. select/find a freeform gold export,
2. infer/select source file,
3. generate prediction artifacts:
   - upload mode: `run_labelstudio_import(...)`
   - offline mode: `generate_pred_run_artifacts(...)` with `--no-upload`
4. co-locate prediction run under `<eval_output_dir>/prediction-run`,
5. run freeform eval and write report artifacts.

Important:

- Upload mode imports/uploads prediction tasks (requires write consent).
- Offline mode is explicit via `--no-upload`.
- Eval-only mode against an existing prediction run is available via `labelstudio-eval` and interactive benchmark eval-only.
- Benchmark prediction manifests include run-config metadata (`run_config`, `run_config_hash`, `run_config_summary`) so analytics/dashboard rows can be grouped by configuration.
- Non-interactive benchmark knobs include worker/split controls plus OCR and warmup flags (`--ocr-device`, `--ocr-batch-size`, `--warm-models`, `--epub-extractor`).

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
- run roots now include `run_manifest.json` for import/export/eval/benchmark traceability.

Manifest includes:

- project metadata, task scope settings, uploaded count, IDs, source file, URL, and coverage.
- prediction run settings and traceability fields: `run_config`, `run_config_hash`, `run_config_summary`.
- processed-output linkage fields when available: `processed_run_root`, `processed_report_path`, `recipe_count`.
- run identity fields used across flows: `run_kind`, `run_id`, and source identity (`path`, `source_hash`).

### 1.11 Additional operational conventions

- Freeform source matching is strict by default (source identity must align). Use `--force-source-match` only when intentionally comparing renamed/cutdown variants.
- Benchmark gold discovery checks both `data/output/**/exports/freeform_span_labels.jsonl` and `data/golden/**/exports/freeform_span_labels.jsonl`.
- Split-job `labelstudio-import` and `labelstudio-benchmark` support the same PDF/EPUB split controls as stage imports (`workers`, split workers, pages/spine per job).
- Progress callbacks include post-merge phases (archive/hash, processed-output writes, chunk/task generation, upload batching) so long runs continue surfacing advancing status.
- Interactive `labelstudio` export resolves credentials first, then fetches project titles for a picker UI (showing a detected type tag beside each project when available). It now auto-uses the selected project's detected type as export scope and only prompts for scope when detection is `unknown` (or when the project name is typed manually).
- Interactive Label Studio import/export credential resolution order is: CLI/env values first, then saved `cookimport.json` values, then one-time prompt (which persists back to `cookimport.json`).
- Interactive freeform `labelstudio` import uses an AI prelabel mode selector before upload and writes `prelabel_report.json` when prelabel is enabled.
- Interactive `labelstudio_decorate` is available as a dedicated main-menu action and supports dry-run preview before write mode.
- Interactive benchmark upload uses the same per-run settings chooser as interactive Import (`global defaults` / `last benchmark` / `change run settings`) and writes successful selections to `<output_dir>/.history/last_run_settings_benchmark.json`.
- Interactive benchmark upload follows the same env -> saved settings -> one-time prompt credential resolution path before invoking `labelstudio-benchmark`.

## 2) Known-Bad / High-Risk / Common Confusion

### 2.1 Timestamp format mismatch in prior docs

Current code uses timestamp format with dots in time:

- `%Y-%m-%d_%H.%M.%S`

Several previous docs claimed a colon-separated time format. That claim was incorrect for current code.

### 2.2 Benchmark side-effect misunderstanding

Users often expected benchmark to be “offline scoring only.”

Current reality:

- non-interactive benchmark can be upload mode (default) or explicit offline mode (`--no-upload`).
- eval-only against an existing pred run is a separate command (`labelstudio-eval`) and interactive branch.

### 2.3 Source mismatch leading to zero overlap

Freeform eval can collapse to zero due to source hash/name mismatch even if ranges are aligned.

Mitigation:

- use `--force-source-match` when intentionally comparing renamed/cutdown variants.

### 2.4 Freeform taxonomy drift

Historical freeform exports used `TIP` / `NOTES` / `VARIANT` before the
`KNOWLEDGE` / `RECIPE_NOTES` / `RECIPE_VARIANT` rename.

Eval normalizes legacy exports:

- `TIP -> KNOWLEDGE`
- `NOTES -> RECIPE_NOTES`
- `NOTE -> RECIPE_NOTES`
- `VARIANT -> RECIPE_VARIANT`
- `NARRATIVE -> OTHER`
- `YIELD -> YIELD_LINE`
- `TIME -> TIME_LINE`

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

## 3) Where Things Live

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

## 4) Practical Runbook

### 4.1 Setup

- Start Label Studio.
- Set `LABEL_STUDIO_URL` and `LABEL_STUDIO_API_KEY`.

### 4.2 Import examples

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

### 4.3 Export examples

```bash
cookimport labelstudio-export --project-name "Project" --export-scope pipeline
cookimport labelstudio-export --project-name "Project" --export-scope canonical-blocks
cookimport labelstudio-export --project-name "Project" --export-scope freeform-spans
```

### 4.4 Eval examples

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

### 4.5 Benchmark example

```bash
cookimport labelstudio-benchmark --allow-labelstudio-write
```

Offline (no upload/API calls):

```bash
cookimport labelstudio-benchmark --no-upload
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

## 5) Design Decisions Worth Preserving

- Keep three workflows as separate project contracts (pipeline/canonical/freeform), not one overloaded project.
- Keep deterministic URN-based task identifiers per scope.
- Keep freeform offsets tied to exact uploaded text and source map.
- Keep benchmark artifacts co-located with eval outputs for reproducibility.
- Keep write consent explicit to avoid accidental Label Studio side effects.
- Keep split-job global block index rebasing; removing it reintroduces zero-match false negatives.

## 6) What To Check First When Things Break

1. Is `task_scope`/`export_scope`/`eval scope` aligned for the same project/run?
2. Did upload actually happen (write consent on, not cancelled)?
3. Are you looking under `data/golden` (not only `data/output`)?
4. Did source identity mismatch collapse freeform overlap? Try `--force-source-match`.
5. For split PDF/EPUB jobs, confirm merged block indices are globally rebased.
6. Confirm project naming did not silently dedupe to `-1`, `-2` and send you to a different project than expected.

## 7) Open Gaps / Future Work

- Add stronger live-manual validation transcripts for each scope after config changes.
- If PDF page box workflow is revived, treat as a separate task scope and keep this doc explicit about status.

## 8) Merged Understandings Addendum (2026-02-20 to 2026-02-22)

### 8.1 Interactive freeform AI flow and prelabel mode mapping

- Interactive Label Studio import supports full freeform AI prelabel flow without leaving the main menu.
- Prelabel mode picker maps directly to backend controls:
  - `prelabel`
  - `prelabel_upload_as` (`annotations` or `predictions`)
  - `prelabel_allow_partial`
- This keeps interactive behavior aligned with non-interactive flags:
  - `--prelabel`
  - `--prelabel-upload-as`
  - `--prelabel-allow-partial`

### 8.2 Prelabel upload fallback and decorate additivity

- Freeform prelabel generation happens in `generate_pred_run_artifacts(...)` after tasks are sampled and before `label_studio_tasks.jsonl` is written.
- Default upload behavior tries inline completed `annotations` first.
- If inline annotations are rejected by Label Studio, flow falls back to:
  - upload tasks without annotations,
  - fetch Label Studio task IDs,
  - map deterministic `segment_id` to Label Studio `task.id`,
  - create annotations per task via API.
- `labelstudio-decorate` remains additive:
  - base annotation preserved,
  - new merged annotation created,
  - metadata tags include `meta.cookimport_prelabel=true`, `mode=augment`, `added_labels`.

### 8.3 Codex command, model, and token-usage propagation

- Prelabel/decorate default command should be non-interactive `codex exec -`.
- Keep compatibility fallback from legacy `codex` commands when stderr indicates `stdin is not a terminal`.
- Effective command/model resolution belongs in provider construction (`_build_prelabel_provider(...)`), not only in interactive prompt plumbing.
- Token usage tracking is provider-level and always-on for prelabel/decorate runs; aggregate totals flow into `prelabel_report.json` / `decorate_report.json`.

### 8.4 Progress callback ownership and spinner counters

- `run_labelstudio_import(...)` emits phase/status messages through `progress_callback`.
- Interactive and non-interactive wrappers should share this callback path rather than maintain separate spinner logic.
- Task-level counters (`task X/Y`) must be emitted where totals exist (ingest runtime loops), not inferred in CLI wrappers.

### 8.5 Prompt/context mechanics and taxonomy enforcement

- Prelabeling is one-shot per segment task (fresh subprocess call per prompt); there is no cross-task in-memory conversation history.
- Context size is controlled by segmentation settings (`segment_blocks`, `segment_overlap`), not persistent chat state.
- Apparent rerun statefulness is typically prompt cache reuse (`prelabel_cache/`), not model memory.
- Canonical freeform label taxonomy and normalization are centralized in `label_config_freeform.py`; prelabel, decorate, export/eval normalization, and project-type inference should reuse that source.
