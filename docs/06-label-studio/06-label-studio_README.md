---
summary: "Code-verified Label Studio import/export/eval reference for current behavior, contracts, and known pitfalls."
read_when:
  - Working on any Label Studio import/export/evaluation flow
  - Debugging unexpected uploads, zero-match evals, or output-path confusion
  - Working on freeform golden-set workflows and legacy-scope migration behavior
---

# Label Studio: Technical Readme

This document merges all prior docs from `docs/06-label-studio/` and reconciles them with the current implementation in:

- `cookimport/labelstudio/`
- `cookimport/cli.py`

This document is the current source of truth for implemented Label Studio behavior.

Use `docs/06-label-studio/06-label-studio_log.md` for historical architecture versions, builds, and fix attempts when work starts looping.

## 1) Current Truth (Verified Against Code)

### 1.1 Scope and purpose

Label Studio integration is for creating/evaluating freeform golden sets for cookbook extraction/parsing.
Current workflow scope is `freeform-spans` only. Legacy `pipeline` and `canonical-blocks`
projects/manifests are treated as historical artifacts and rejected by current export flows.

Primary code paths:

- Import/upload: `cookimport/labelstudio/ingest.py`
- Export: `cookimport/labelstudio/export.py`
- Freeform eval: `cookimport/labelstudio/eval_freeform.py`
- CLI + interactive routing: `cookimport/cli.py`

Benchmark scoring update (current behavior):
- `cookimport labelstudio-benchmark` evaluates stage evidence manifests (`stage_block_predictions.json`) with selectable modes:
  - `stage-blocks` (default): block-index scoring vs freeform gold.
  - `canonical-text`: alignment scoring vs canonical gold text/line labels.
  - `--execution-mode legacy|pipelined|predict-only` chooses orchestration path (default `legacy`).
  - `--predictions-out <path>` writes a run-level prediction record JSONL.
  - `--predictions-in <path>` runs evaluate-only from a saved prediction record (no prediction generation/upload).
  - `--execution-mode predict-only` writes prediction artifacts and skips evaluation.
- Interactive benchmark modes (`single_offline` and `all_method`) run `labelstudio-benchmark` in `canonical-text` mode so extractor permutations can share one freeform gold export safely.
- `cookimport bench run` currently remains on stage-block scoring.
- `label_studio_tasks.jsonl` remains the upload/task artifact surface, but benchmark scoring does not depend on it.
  - default behavior still writes it for offline runs;
  - offline benchmark runs may intentionally skip it with `labelstudio-benchmark --no-upload --no-write-labelstudio-tasks` or `bench run --no-write-labelstudio-tasks`.

### 1.2 Commands and defaults

CLI commands:

- `cookimport labelstudio-import`
- `cookimport labelstudio-export`
- `cookimport labelstudio-eval`
- `cookimport labelstudio-benchmark`

Default output roots:

- `labelstudio-import --output-dir` defaults to `data/golden/sent-to-labelstudio`.
- `labelstudio-export --output-dir` defaults to `data/golden/pulled-from-labelstudio`.
- `labelstudio-benchmark --output-dir` defaults to `data/golden/benchmark-vs-golden`.
- Interactive menu (`cookimport` with no subcommand) still uses `cookimport.json.output_dir` for stage output, but routes Label Studio import/export/benchmark artifact roots to those same dedicated `data/golden/*` subfolders.
- Benchmark also writes stage-style processed cookbook outputs to `data/output` by default via `--processed-output-dir`.

### 1.3 Write safety and consent

Uploads are intentionally gated.

- Non-interactive:
  - `labelstudio-import` requires `--allow-labelstudio-write`.
  - `labelstudio-benchmark` requires `--allow-labelstudio-write` only in upload mode.
  - `labelstudio-benchmark --no-upload` is fully offline and skips credential resolution + upload.
  - Otherwise they fail fast.
- Interactive:
  - `labelstudio` import proceeds directly to upload (no separate upload confirmation prompt).
  - `labelstudio` import always uses overwrite semantics for resolved project names (`overwrite=True`, `resume=False`); there is no overwrite/resume chooser in this flow.
  - Interactive freeform import includes an AI prelabel mode picker (off, strict/allow-partial annotations, advanced predictions modes; strict is marked recommended), then a style picker (`actual freeform` span mode vs `legacy, block based` mode), prints total processing time in the import summary, and prints `prelabel_report.json` when prelabel is enabled.
  - Interactive freeform prelabel does not prompt for command selection; it resolves command from `COOKIMPORT_CODEX_CMD` or `codex exec -`, displays the resolved account email when available, then prompts for model and thinking effort (model-compatible subset of `none|low|medium|high|xhigh`; `minimal` hidden) using metadata/defaults from that command's Codex home cache (`CODEX_HOME` honored).
  - Token usage tracking is always enabled for AI labeling runs.
- non-interactive benchmark upload does not ask a second confirmation; passing upload flags is treated as explicit intent.
- interactive benchmark now has two offline-only menu modes, and asks mode before run-settings:
  - single offline mode (default first choice): one `labelstudio-benchmark --no-upload --eval-mode canonical-text` run (no Label Studio credentials, no upload),
  - all-method mode: offline multi-config benchmark sweep (no Label Studio upload), with scope selection:
    - `Single golden set` (manual one-pair flow),
    - `All golden sets with matching input files` (bulk matching flow).
- benchmark upload auto-recovers from project scope collisions when project name is auto-generated: if an existing project+manifest resolves to a different task scope, it creates a deduped project name instead of failing interactive flow.

Non-interactive overwrite/resume behavior is unchanged:
- `cookimport labelstudio-import` still exposes `--overwrite / --resume`.

Relevant code:

- `cookimport/cli.py` (`_require_labelstudio_write_consent`, benchmark/import flow)
- `cookimport/labelstudio/ingest.py` (`allow_labelstudio_write` guard)

### 1.4 Task generation and IDs

Resume/idempotence is based on deterministic freeform task IDs, not Label Studio internal IDs.

Freeform segment IDs:

- `urn:cookimport:segment:{source_hash}:{start_block_index}:{end_block_index}`

Resume behavior:

- prior manifests and/or prior `label_studio_tasks.jsonl` are scanned,
- already-seen IDs are skipped.
- resume metadata is only applied when the target Label Studio project already exists; if a new project is created for this run, stale local manifests are ignored.
- benchmark upload passes `auto_project_name_on_scope_mismatch=True`, so auto-named benchmark projects that collide with existing freeform/canonical scope names are auto-suffixed (`-1`, `-2`, ...).

### 1.5 Label configs (actual current sets)

Freeform labels (`cookimport/labelstudio/label_config_freeform.py`):

- `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `YIELD_LINE`, `TIME_LINE`, `RECIPE_NOTES`, `RECIPE_VARIANT`, `KNOWLEDGE`, `OTHER`
- explicitly preserves whitespace with `style="white-space: pre-wrap;"` for stable offsets.

### 1.6 Export contracts

Freeform export produces:

- `exports/labelstudio_export.json`
- `exports/freeform_span_labels.jsonl`
- `exports/freeform_segment_manifest.jsonl`
- `exports/canonical_text.txt`
- `exports/canonical_block_map.jsonl`
- `exports/canonical_span_labels.jsonl`
- `exports/canonical_span_label_errors.jsonl`
- `exports/canonical_manifest.json`
- `exports/summary.json`
  - `summary.recipe_counts.recipe_headers` stores deduped golden recipe count based on `RECIPE_TITLE` header spans (dedupe key: source + block range).

Legacy projects/manifests scoped as `pipeline` or `canonical-blocks` are rejected by export.

Freeform span rows include offsets, label, touched block mapping, annotator/timestamp, and deterministic `span_id`.

### 1.6.1 Freeform prelabel contracts

- `labelstudio-import --prelabel` can attach completed freeform annotations before upload.
- Prelabel supports two granularity modes (`--prelabel-granularity block|span`, interactive style picker):
  - `block` (legacy, block based): LLM output `{block_index, label}` -> full-block span.
  - `span` (actual freeform): LLM output quote-anchored spans (`{block_index, label, quote, occurrence?}`) and optional absolute spans (`{label, start, end}`) resolved deterministically to exact offsets.
  - no whitespace normalization is allowed in either mode.
- Import upload mode `--prelabel-upload-as`:
  - `annotations` (default): attempts inline completed annotations in import payload.
  - `predictions`: uploads model predictions instead of completed annotations.
- If inline `annotations` upload fails, import auto-falls back to:
  - upload plain tasks,
  - then create annotations per task through Label Studio API.
- Prelabel artifacts written in run root:
  - `prelabel_report.json`
  - `prelabel_errors.jsonl`
  - `prelabel_prompt_log.md` (human-readable Markdown, one section per `codex exec` prompt with full prompt text plus prompt-context description/metadata)
- Prelabel performs a single Codex model-access preflight probe before task labeling so invalid model/account combinations fail once up front instead of repeating task-level failures.
- Freeform prelabel task calls run with bounded concurrency (`--prelabel-workers`, default `15`; set `1` to force serial behavior).
- Freeform prelabel treats provider `HTTP 429`/rate-limit failures as a stop condition: once one task returns 429, no additional queued tasks should call the provider, remaining queued tasks are marked skipped, and progress emits an explicit 429 warning.
- Progress callbacks now report `Running freeform prelabeling... task X/Y` so CLI spinners show per-task progress while AI labels are generated; parallel mode appends `(workers=N)` on kickoff and completion updates, and emits worker-activity telemetry so the spinner can render one line per worker under the main status. Split conversion loops emit the same worker-activity telemetry (`job X/Y`) when split workers are active.
- Progress callbacks are best-effort telemetry: callback exceptions are logged and ignored so extraction/task generation/upload logic is not aborted by spinner/UI callback failures.
- CLI status wrappers now add a live elapsed suffix (for example `(17s)`) after ~10 seconds with no phase-message change, so long steps remain visibly active instead of appearing stuck.
- CLI import summaries now print an explicit red `PRELABEL ERRORS: X/Y ...` line (plus `prelabel_errors.jsonl` path) when prelabel failures occur, including allow-partial runs that still upload tasks.
- Codex CLI invocation for prelabel uses non-interactive `... exec -`; plain `codex`/`codex2` values auto-retry with `exec -` when stderr reports `stdin is not a terminal`.
- Default Codex command resolution is: `--codex-cmd` -> `COOKIMPORT_CODEX_CMD` -> `codex exec -`.
- Prelabel runs accept explicit model selection via `--codex-model`; when omitted they resolve model from `COOKIMPORT_CODEX_MODEL` then Codex config (`~/.codex/config.toml`, `~/.codex-alt/config.toml`).
- Prelabel runs accept explicit thinking effort selection via `--codex-thinking-effort` (alias `--codex-reasoning-effort`), mapping to Codex `model_reasoning_effort`; when omitted they use Codex config defaults.
- Prelabel model/config/cache discovery is command-aware: it resolves from the selected command's Codex home roots rather than assuming one global login.
- Provider errors reported via Codex JSON events (`turn.failed`) are treated as hard failures and recorded with their normalized provider detail (for example unsupported model/account messages) instead of generic "no labels" parse failures.
- Token usage tracking is always enabled for prelabel runs, using Codex JSON event parsing to record aggregate `input_tokens`, `cached_input_tokens`, `output_tokens`, and `reasoning_tokens` (when emitted by Codex; `0` when not present) in run reports (`prelabel_report.json` also records resolved command/account metadata).

#### 1.6.1.1 Prompt, parsing, and context management (code-verified)

AI prelabeling for `freeform-spans` is **one fresh prompt per task** (per segment) with **no cross-task conversation memory**.
The task’s AI context window is the prompt block stream (context-before blocks + focus blocks + context-after blocks).

Where it happens:

- Task segmentation: `cookimport/labelstudio/freeform_tasks.py` (`segment_blocks`, `segment_overlap`, `segment_focus_blocks`, `target_task_count` overlap tuning)
- Prompt + parsing + span construction: `cookimport/labelstudio/prelabel.py`
- End-to-end wiring (generate artifacts, then upload + fallback): `cookimport/labelstudio/ingest.py`

**Context management (your question):**

- Each segment task is labeled independently. There is no rolling chat history; every call is a brand new Codex CLI subprocess fed a single prompt string on stdin (`subprocess.run(..., input=prompt, ...)`). Tasks may run concurrently (`--prelabel-workers`), but each prompt remains task-local.
- The “chunking” is done before the LLM call: freeform tasks still use `segment_blocks` + `segment_overlap` (defaults `40` + `5`) to choose each task’s neighborhood and optional `target_task_count` to auto-tune effective overlap per file. For focus-mode prelabel runs, effective overlap is also clamped to at least `segment_blocks - segment_focus_blocks` so focus coverage can hand off cleanly between adjacent tasks.
- Label Studio payload is now focus-only: `data.segment_text` and `data.source_map.blocks` include only focus blocks (the rows that should be labeled). Neighboring context rows are stored separately in `data.source_map.context_before_blocks` / `data.source_map.context_after_blocks` and injected into prompts, so AI keeps boundary context while the UI shows only labelable text.
- Span prompts provide one block stream with explicit context-before/context-after markers plus `START/STOP` focus markers (instead of repeating focus block text separately), and prelabel output is filtered so only focus blocks can be labeled.
- There is no incremental “continue where you left off” prompting. It’s many small/fixed prompts, not one ever-growing prompt.
- A prompt/response cache can make reruns *look* stateful: `CodexCliProvider` stores `{prompt, response}` JSON files under `prelabel_cache/` keyed by a hash of `(codex_cmd, track_usage flag, prompt text)`. Delete the cache dir to force fresh completions.
- Run-level prompt logging is explicit: prelabel writes `prelabel_prompt_log.md` under the run root in `data/golden/sent-to-labelstudio/<timestamp>/labelstudio/<book_slug>/`, including the full prompt text and `included_with_prompt_description` + `included_with_prompt` metadata (labels, block/focus context, template, command/model/account fields).

**What the model is asked to do (the literal prompt template):**

Built in `cookimport/labelstudio/prelabel.py:_build_prompt(...)`. Prompt text is loaded from file-backed templates in `llm_pipelines/prompts/`:

- `freeform-prelabel-full.prompt.md`
- `freeform-prelabel-span.prompt.md`

This makes full-mode prompt iteration text-only: edit the file and rerun prelabel.
Runtime replaces placeholders such as `{{SEGMENT_ID}}`, `{{BLOCKS_JSON_LINES}}`, and span marker placeholders like `{{BLOCKS_WITH_FOCUS_MARKERS_COMPACT_LINES}}` (with legacy compatibility alias `{{BLOCKS_WITH_FOCUS_MARKERS_JSON_LINES}}`) per task.
If files are missing/empty, runtime falls back to built-in defaults.

```text
You are labeling cookbook text BLOCKS for a "freeform spans" golden set.
...
...
Segment id: {{SEGMENT_ID}}
Blocks:
{{BLOCKS_WITH_FOCUS_MARKERS_COMPACT_LINES}}
```

**Output parsing (tolerant, but prompt asks for strict JSON):**

- The parser extracts the first JSON array/object embedded anywhere in stdout (`extract_first_json_value(...)`), then accepts a few wrapper shapes (top-level list, or dict with keys like `selections` / `labels` / `items` / `blocks`).
- Block mode items require `block_index` + `label` (aliases like `tag`/`category` are accepted).
- Span mode items accept quote-anchored spans (`block_index`, `label`, `quote`, optional `occurrence`) and absolute spans (`label`, `start`, `end`).
- Labels are normalized (`TIME` -> `TIME_LINE`, `YIELD` -> `YIELD_LINE`, etc) and anything not in `FREEFORM_ALLOWED_LABELS` is dropped.

**Span generation (important nuance):**

- `block` mode keeps legacy behavior: each `{block_index, label}` becomes a span covering the entire block text range.
- `span` mode resolves partial spans deterministically:
  - quote-anchored spans are matched against the literal block substring inside `segment_text`.
  - repeated quotes require `occurrence` (1-based) to disambiguate.
  - unresolved/ambiguous items are dropped; valid items for the same task still upload.
- The annotation `result[].value.text` is always derived from `segment_text[start:end]` and must match exactly; this is why no whitespace normalization is allowed and the LS `<Text ... style="white-space: pre-wrap;">` config is required.

#### 1.6.1.2 Detailed mode behavior: `actual freeform` vs `legacy, block based` (code-verified)

Interactive style labels and runtime mode values are intentionally separate:

- Interactive choice `actual freeform - allow sub-block span highlights` (sometimes called `actual, freeform`) maps to `prelabel_granularity=span`.
- Interactive choice `legacy, block based - one label per block` maps to `prelabel_granularity=block`.
- CLI accepts `--prelabel-granularity block|span`; normalization also accepts aliases like `legacy` and `actual_freeform`.

`prelabel_granularity` only changes **how AI output is interpreted into spans**. It does not change segmentation (`segment_blocks`, `segment_overlap`), label config, or upload command shape.

**Option A: `actual freeform` (`span`)**

1. Prompt used:
   - Runtime loads `llm_pipelines/prompts/freeform-prelabel-span.prompt.md`.
   - Prompt uses one markerized block list (`<<<CONTEXT_BEFORE_LABELING_ONLY>>>`, `<<<START_LABELING_BLOCKS_HERE>>>`, `<<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>>`, `<<<CONTEXT_AFTER_LABELING_ONLY>>>`) plus a focus-index summary, so focus context is not duplicated as a second block payload list.
   - Prompt asks for selective span output (zero/one/many spans per block).
2. Accepted model output item shapes:
   - Quote-anchored (preferred): `{"block_index": <int>, "label": "<LABEL>", "quote": "<exact text>", "occurrence": <optional int>}`.
   - Absolute offsets (fallback): `{"label": "<LABEL>", "start": <int>, "end": <int>}` (segment-global offsets).
3. Parsing and normalization:
   - Parser tolerates prose-wrapped JSON by extracting first JSON value.
   - Wrapper keys `selections`, `labels`, `items`, `blocks` are accepted.
   - Label aliases are normalized (`TIME` -> `TIME_LINE`, `TIP` -> `KNOWLEDGE`, etc) and non-allowed labels are dropped.
4. Offset resolution behavior:
   - Quote mode resolves inside the selected block’s exact substring from `segment_text`.
   - Resolver tries exact `quote`, then stripped `quote` (leading/trailing whitespace only).
   - If the quote does not exist in the selected `block_index`, runtime runs a small repair pass that tries to re-anchor the quote in nearby focus blocks (and finally accepts a unique match across the focus window). Context-only blocks are never labeled.
   - If quote appears multiple times in that block, `occurrence` is required (1-based). Missing/invalid ambiguity resolution drops that selection.
   - Absolute mode validates `0 <= start < end <= len(segment_text)`; invalid bounds are dropped.
5. Emitted Label Studio results:
   - Multiple spans for the same block are allowed.
   - Duplicate spans (same normalized label + start + end) are deduped.
   - `value.text` is always recomputed from `segment_text[start:end]` to keep exact LS offset/text integrity.
6. Failure semantics:
   - Bad selections are dropped item-by-item.
   - Explicit empty output (`[]`) is treated as “no spans” (not an error).
   - Task prelabel fails only when the provider call raises or the provider returns non-empty suggestions but no valid spans survive.

**Option B: `legacy, block based` (`block`)**

1. Prompt used:
   - Runtime loads `llm_pipelines/prompts/freeform-prelabel-full.prompt.md`.
   - Prompt instructs model to assign one label per block and implies full-block coverage.
2. Accepted model output item shape:
   - `{"block_index": <int>, "label": "<LABEL>"}` (`tag`/`category` aliases accepted for label field).
3. Mapping behavior:
   - For each accepted record, runtime looks up the block’s `segment_start`/`segment_end` and emits one span covering the entire block.
   - This reproduces pre-span rollout behavior (one region per labeled block suggestion, full width of that block).
4. Enforcement nuance:
   - Prompt asks for exactly one label per block and ordered output, but runtime is tolerant.
   - Missing blocks are simply unlabeled.
   - If model returns multiple different labels for the same block, each distinct label can produce its own full-block span result.
5. Failure semantics:
   - Same as span mode: item-level drops are tolerated; task fails only if no valid spans remain or provider raises.

**Shared across both options**

- Same task construction and context boundaries (segment text + source map).
- Same provider path (`codex-cli`), model preflight check, cache behavior, and token tracking.
- Same prelabel artifacts (`prelabel_report.json`, `prelabel_errors.jsonl`).
- Same upload mode handling (`--prelabel-upload-as annotations|predictions`) and inline-annotation fallback path.

#### 1.6.1.3 Upload modes + fallback (mechanics)

When `--prelabel` is enabled:

1. `generate_pred_run_artifacts(...)` attaches `task["annotations"] = [annotation]` only when the prelabel result is non-empty (segments that return `[]` upload as plain tasks with no prelabels).
2. `run_labelstudio_import(...)` uploads tasks in batches:
   - `--prelabel-upload-as annotations` (default): try importing tasks with inline `annotations`.
   - If Label Studio rejects inline annotations, it automatically:
     - re-uploads the same tasks with annotations stripped,
     - then creates annotations per task via the Label Studio API by mapping deterministic `segment_id` to Label Studio’s internal `task.id`.
   - `--prelabel-upload-as predictions` (advanced): converts the first annotation into a Label Studio `predictions[]` entry (`model_version="cookimport-prelabel"`, `score=1.0`), which is useful for debugging/model comparison but won’t necessarily mark tasks “completed”.

#### 1.6.1.4 Operator FAQ: context window and prompt count

This is the most common point of confusion: both styles (`block` and `span`) use the same task segmentation and context boundaries.

**Q: Does the model see one block at a time?**

- No. It sees one **segment task** at a time.
- A segment task is still built from multiple nearby blocks (default `segment_blocks=40`), but Label Studio now receives only focus blocks in `segment_text`.
- Prompt context still includes the wider neighborhood: prelabel builds prompt lines from `source_map.context_before_blocks` + focus blocks (`source_map.blocks`) + `source_map.context_after_blocks`.
- Each task also carries a focus block list (`source_map.focus_block_indices`) plus precomputed scope summaries (`focus_scope_hint`, focus/context-before/context-after ranges) used by prelabel prompt instructions, parser-side filtering, and Label Studio headers.
- Both prelabel styles use this same task context.

**Q: Does it see surrounding context while labeling one block/span?**

- Yes, inside the current segment task.
- No, across tasks. There is no rolling conversation memory between tasks; each task is a fresh provider call.
- Overlap (`segment_overlap`, default `5`) repeats tail blocks into the next task so adjacent task windows share text. When `target_task_count` is set, manifest records both requested overlap and effective overlap selected for that file. Freeform prelabel runs also enforce a focus-coverage floor (`segment_overlap_effective >= segment_blocks - segment_focus_blocks`) to avoid unlabeled holes between task focus windows.

**Q: How many prompts are sent in a run?**

- Freeform prelabel runs do one model completion per sampled task (`provider.complete(prompt)` in the task loop), potentially in parallel depending on `--prelabel-workers`.
- There is also one preflight probe call before the loop (`preflight_codex_model_access(...)`) to fail fast on invalid model/account access.
- Practical formula:
  - model labeling prompts = number of sampled freeform tasks
  - plus one preflight probe call
- Note on cache: if a prompt hash already exists in prelabel cache, completion may be served from cache for that task.

Relevant code:

- segmentation/task windows: `cookimport/labelstudio/freeform_tasks.py`
- prompt build and per-task completion: `cookimport/labelstudio/prelabel.py`
- preflight + task loop wiring: `cookimport/labelstudio/ingest.py`

#### 1.6.1.5 Worked example: `saltfatacidheatcutdown` AIv1 vs AIv2

The pair below is a concrete example where users often ask why outputs differ:

- `data/golden/pulled-from-labelstudio/saltfatacidheatcutdown_aiv1_block_based`
- `data/golden/pulled-from-labelstudio/saltfatacidheatcutdown_aiv2_freeform_fr`

Shared mechanics (same in both):

- export scope: `freeform-spans`
- segment manifest rows: `42` tasks
- segment window size: mostly `40` blocks/task (min `36`, max `40`)
- segment start step: `35` blocks (indicates `segment_overlap=5`)

Contract difference:

- AIv1 (`block`): prompt asks for one label per block; runtime maps each `{block_index,label}` to full-block offsets.
- AIv2 (`span`): prompt asks for selective spans; runtime resolves quote/offset selections and drops ambiguous/unresolvable selections.

Observed output difference from this pair:

- total span rows:
  - AIv1 block-based: `1635`
  - AIv2 freeform-span: `1355`
- span geometry:
  - AIv1: `100%` full-block spans
  - AIv2: `92.2%` full-block spans, `7.8%` sub-block spans (`106` rows)
- coverage:
  - AIv1 touched `1440` unique source blocks
  - AIv2 touched `1201` unique source blocks

Why this is expected:

- `block` mode is effectively dense classification over the window (near one label per block).
- `span` mode is selective extraction (can return zero/one/many spans per block and leave unclear text unlabeled).
- Because of that, freeform-span runs usually produce fewer total labels and tighter offsets.

### 1.7 Evaluation behavior

Freeform eval (`labelstudio-eval`):

- compares predicted labeled ranges from the prediction run vs gold freeform spans (mapped by touched block indices).
- strict metrics remain canonical benchmark numbers.
- gold spans are deduped by default before scoring using `(source_hash, source_file, start_block_index, end_block_index)` keys.
- when deduped gold groups contain conflicting labels:
  - majority label wins (deterministic by count),
  - exact ties are dropped from scored gold and reported under `gold_dedupe.conflicts`.
- adds:
  - `app_aligned` diagnostics
  - `classification_only` diagnostics
- supports `--force-source-match` to bypass source identity checks.

Output artifacts:

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

Additional non-interactive execution modes:

- `--execution-mode legacy` (default): sequential predict then evaluate.
- `--execution-mode pipelined`: prediction stage and canonical eval prewarm overlap via a bounded stage queue.
- `--execution-mode predict-only`: generate prediction artifacts and optional `--predictions-out` JSONL, then skip evaluation.

Important:

- Upload mode imports/uploads prediction tasks (requires write consent).
- Offline mode is explicit via `--no-upload`.
- Eval-only mode against an existing prediction run is available via `labelstudio-eval` (interactive benchmark does not expose eval-only).
- Interactive benchmark single-offline mode runs one `labelstudio-benchmark --no-upload` flow per menu action and writes eval artifacts under `data/golden/benchmark-vs-golden/<timestamp>/`.
- Interactive all-method mode now starts with a scope chooser:
  - `Single golden set`: current one-pair flow.
  - `All golden sets with matching input files`: discover freeform exports and auto-match by source filename.
- All-matched source hint fallback order is:
  1. run `manifest.json` `source_file`,
  2. first non-empty `freeform_span_labels.jsonl` row `source_file`,
  3. first non-empty `freeform_segment_manifest.jsonl` row `source_file`.
- Interactive all-method mode runs offline `labelstudio-benchmark --no-upload` style executions across a fixed extractor/tuning permutation set, then writes per-source summary artifacts at:
  - `.../all-method-benchmark/<source_slug>/all_method_benchmark_report.json`
  - `.../all-method-benchmark/<source_slug>/all_method_benchmark_report.md`
  - each per-source report includes `scheduler` metrics (`heavy_slot_*`, wing backlog, idle gaps, and inflight/split/wing settings used).
- All-matched scope also writes one combined report at:
  - `.../all-method-benchmark/all_method_benchmark_multi_source_report.json`
  - `.../all-method-benchmark/all_method_benchmark_multi_source_report.md`
  - combined report includes `scheduler_summary` rollups across successful source sweeps.
- Interactive all-method mode also writes processed cookbook outputs under the interactive output root (`cookimport.json.output_dir`, default `data/output`) scoped by benchmark timestamp:
  - `<output_dir>/<benchmark_timestamp>/all-method-benchmark/<source_slug>/config_*/<prediction_timestamp>/...`
- Interactive all-method scheduler controls are read from `cookimport.json` keys:
  - `all_method_max_inflight_pipelines`
  - `all_method_max_split_phase_slots`
  - `all_method_wing_backlog_target`
  - `all_method_smart_scheduler`
  - `all_method_config_timeout_seconds`
  - `all_method_retry_failed_configs`
- Smart scheduler mode is phase-aware:
  - workers emit config phase telemetry (`prep`, `split_wait`, `split_active`, `post`, `evaluate`) to `<source_root>/.scheduler_events/config_###.jsonl`,
  - parent scheduler also writes `<source_root>/scheduler_timeseries.jsonl` with time-series snapshots (`scheduler heavy/wing/eval/active/pending`) plus host CPU utilization samples when `/proc/stat` is available,
  - parent queue admission targets `heavy + wing ~= split slots + wing backlog`,
  - effective inflight includes eval-tail headroom (`all_method_max_eval_tail_pipelines` override or CPU-aware auto default) so evaluate tails do not block new admissions,
  - spinner/dashboard task line shows live scheduler state: `scheduler heavy X/Y | wing Z | eval E | active A | pending P`,
  - scheduler polling cadence is `0.15s`; spinner snapshots emit on state-change, while `scheduler_timeseries.jsonl` also writes a heartbeat sample every `1.0s` when state is unchanged.
- Benchmark prediction manifests include run-config metadata (`run_config`, `run_config_hash`, `run_config_summary`) so analytics/dashboard rows can be grouped by configuration.
- Non-interactive benchmark knobs include worker/split controls, OCR/warmup flags, knowledge-harvest codex-farm controls, and a recipe codex-farm policy knob that is currently forced to `off` (`--ocr-device`, `--ocr-batch-size`, `--warm-models`, `--epub-extractor`, `--llm-recipe-pipeline`, `--codex-farm-cmd`, `--codex-farm-root`, `--codex-farm-workspace-root`, `--codex-farm-pipeline-pass1`, `--codex-farm-pipeline-pass2`, `--codex-farm-pipeline-pass3`, `--codex-farm-context-blocks`, `--codex-farm-failure-mode`).
- If recipe codex-farm correction is re-enabled in future, processed report payloads include `llmCodexFarm` and prediction-run artifacts include `llm_manifest.json` when produced.

### 1.9 Parallel split-job behavior and reindexing

For large EPUB/PDF prediction imports, split jobs can run in parallel.

- planners reused from stage path (`plan_pdf_page_ranges`, `plan_job_ranges`)
- merge step rebases block-index fields by cumulative offsets to restore global block coordinates

This reindexing is critical; without it, freeform eval can report near-zero matches despite good extraction.

### 1.10 Artifact layout and run folders

Import run artifacts:

- `<output_dir>/<timestamp>/labelstudio/<book_slug>/...` (default `output_dir`: `data/golden/sent-to-labelstudio`)
- interactive/non-interactive import spinner telemetry:
  - `<output_dir>/.history/processing_timeseries/<timestamp>__labelstudio_import__<source>.jsonl`
- Export run artifacts (default):
  - `<output_dir>/<project_slug>/exports/...` (default `output_dir`: `data/golden/pulled-from-labelstudio`)
  - `--run-dir` overrides this and writes into the specified run directory.
  - Existing manifests are still used to resolve `project_id` and validate task-scope alignment.

Benchmark eval artifacts:

- `<eval_output_dir>/...` (often under `data/golden/benchmark-vs-golden/<timestamp>/`)
- prediction artifacts moved to `<eval_output_dir>/prediction-run/`
- benchmark spinner telemetry:
  - `<eval_output_dir>/processing_timeseries_prediction.jsonl`
  - `<eval_output_dir>/processing_timeseries_evaluation.jsonl` (when evaluation runs)
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
- Interactive `labelstudio` export resolves credentials first, then fetches project titles for a picker UI (showing a detected type tag beside each project when available). The detected type is informational; export itself is freeform-only and rejects legacy scopes.
- Interactive Label Studio import/export credential resolution order is: CLI/env values first, then saved `cookimport.json` values, then one-time prompt (which persists back to `cookimport.json`).
- Interactive freeform `labelstudio` import now prompts for context blocks, overlap, focus blocks, and optional target task count in one sequence, then uses an AI prelabel mode selector before upload, prints summary processing time, and writes `prelabel_report.json` when prelabel is enabled.
- Interactive benchmark uses the same per-run settings chooser as interactive Import (`global defaults` / `last benchmark` / `change run settings`) and writes successful selections to `<output_dir_parent>/.history/last_run_settings_benchmark.json`.
- Interactive benchmark mode picker (`single offline` vs `all method`) appears before run-settings selection.
- Interactive benchmark no longer has an upload mode; both interactive paths are offline and do not resolve Label Studio credentials.
- Interactive benchmark always uses `canonical-text` eval mode in both offline paths.

## 2) Known-Bad / High-Risk / Common Confusion

### 2.1 Timestamp format mismatch in prior docs

Current code uses timestamp format with dots in time:

- `%Y-%m-%d_%H.%M.%S`

Several previous docs claimed a colon-separated time format. That claim was incorrect for current code.

### 2.2 Benchmark side-effect misunderstanding

Users often expected benchmark to be “offline scoring only.”

Current reality:

- non-interactive benchmark can be upload mode (default) or explicit offline mode (`--no-upload`).
- eval-only against an existing pred run is a separate command (`labelstudio-eval`), not an interactive benchmark branch.
- interactive benchmark includes an offline all-method sweep branch that evaluates many run-setting permutations and writes a ranked summary report.

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

A “draw boxes on page images” workflow (PDF page box annotation) is not implemented in the current Label Studio integration.

Do not assume this path exists when debugging current flows.

## 3) Where Things Live

Core package:

- `cookimport/labelstudio/client.py`: API client wrapper
- `cookimport/labelstudio/ingest.py`: import flow, task generation dispatch, resume/upload, artifacts
- `cookimport/labelstudio/export.py`: export + JSONL shaping
- `cookimport/labelstudio/archive.py`: extracted-archive builders/normalization shared by Label Studio and stage-block prediction flows
- `cookimport/labelstudio/freeform_tasks.py`: freeform task builder + offset/block mapping
- `cookimport/labelstudio/prelabel.py`: optional Codex-CLI prelabel integration
- `cookimport/labelstudio/eval_freeform.py`: freeform metrics/report
- `cookimport/labelstudio/label_config_freeform.py`: freeform Label Studio XML config + label normalization

CLI surfaces:

- `cookimport/cli.py`

Tests:

- `tests/labelstudio/test_labelstudio_freeform.py`
- `tests/labelstudio/test_labelstudio_export.py`
- `tests/labelstudio/test_labelstudio_benchmark_helpers.py`
- `tests/labelstudio/test_labelstudio_ingest_parallel.py`
- `tests/staging/test_run_manifest_parity.py`

## 4) Practical Runbook

### 4.1 Setup

- Start Label Studio.
- Set `LABEL_STUDIO_URL` and `LABEL_STUDIO_API_KEY`.

### 4.2 Import examples

```bash
cookimport labelstudio-import data/input/book.epub \
  --segment-blocks 40 \
  --segment-overlap 5 \
  --segment-focus-blocks 28 \
  --target-task-count 55 \
  --allow-labelstudio-write
```

### 4.3 Export examples

```bash
cookimport labelstudio-export --project-name "Project"
```

### 4.4 Eval examples

```bash
cookimport labelstudio-eval \
  --pred-run data/golden/sent-to-labelstudio/<ts>/labelstudio/<book_slug> \
  --gold-spans data/golden/pulled-from-labelstudio/<...>/exports/freeform_span_labels.jsonl \
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

- Keep one explicit workflow contract: freeform spans (`freeform-spans`).
- Keep deterministic URN-based task identifiers (`segment_id`, `span_id`).
- Keep freeform offsets tied to exact uploaded text and source map.
- Keep benchmark artifacts co-located with eval outputs for reproducibility.
- Keep write consent explicit to avoid accidental Label Studio side effects.
- Keep split-job global block index rebasing; removing it reintroduces zero-match false negatives.

## 6) What To Check First When Things Break

1. Is this project/run a freeform (`freeform-spans`) workflow and not a legacy scope?
2. Did upload actually happen (write consent on, not cancelled)?
3. Are you looking under `data/golden` (not only `data/output`)?
4. Did source identity mismatch collapse freeform overlap? Try `--force-source-match`.
5. For split PDF/EPUB jobs, confirm merged block indices are globally rebased.
6. Confirm project naming did not silently dedupe to `-1`, `-2` and send you to a different project than expected.

## 7) Open Gaps / Future Work

- Add stronger live-manual validation transcripts for freeform import/export/eval after config changes.
- If a new workflow scope is introduced later, document it as a separate contract and keep migration rules explicit.

## 8) Merged Understandings Addendum (2026-02-20 to 2026-02-22)

### 8.1 Interactive freeform AI flow and prelabel mode mapping

- Interactive Label Studio import supports full freeform AI prelabel flow without leaving the main menu.
- Prelabel mode picker maps directly to backend controls:
  - `prelabel`
  - `prelabel_upload_as` (`annotations` or `predictions`)
  - `prelabel_granularity` (`block` or `span`)
  - `prelabel_allow_partial`
- This keeps interactive behavior aligned with non-interactive flags:
  - `--prelabel`
  - `--prelabel-upload-as`
  - `--prelabel-granularity`
  - `--prelabel-allow-partial`

### 8.2 Prelabel upload fallback

- Freeform prelabel generation happens in `generate_pred_run_artifacts(...)` after tasks are sampled and before `label_studio_tasks.jsonl` is written.
- Default upload behavior tries inline completed `annotations` first.
- If inline annotations are rejected by Label Studio, flow falls back to:
  - upload tasks without annotations,
  - fetch Label Studio task IDs,
  - map deterministic `segment_id` to Label Studio `task.id`,
  - create annotations per task via API.

### 8.3 Codex command, model, and token-usage propagation

- Prelabel default command should be non-interactive `codex exec -`.
- Keep compatibility fallback from legacy `codex` commands when stderr indicates `stdin is not a terminal`.
- Effective command/model resolution belongs in provider construction (`_build_prelabel_provider(...)`), not only in interactive prompt plumbing.
- Token usage tracking is provider-level and always-on for prelabel runs; aggregate totals flow into `prelabel_report.json` and include `reasoning_tokens` when the Codex CLI usage payload exposes them.

### 8.4 Progress callback ownership and spinner counters

- `run_labelstudio_import(...)` emits phase/status messages through `progress_callback`.
- Interactive and non-interactive wrappers should share this callback path rather than maintain separate spinner logic.
- Task-level counters (`task X/Y`) must be emitted where totals exist (ingest runtime loops), not inferred in CLI wrappers.

### 8.5 Prompt/context mechanics and taxonomy enforcement

- Prelabeling is one-shot per segment task (fresh subprocess call per prompt); there is no cross-task in-memory conversation history.
- Context size is controlled by segmentation settings (`segment_blocks`, `segment_overlap`), not persistent chat state.
- Apparent rerun statefulness is typically prompt cache reuse (`prelabel_cache/`), not model memory.
- Canonical freeform label taxonomy and normalization are centralized in `label_config_freeform.py`; prelabel, export/eval normalization, and project-type inference should reuse that source.

## 9) Merged Task Specs (2026-02-20 to 2026-02-22)

### 9.1 2026-02-20_21.45.00 freeform prelabel baseline

Durable contracts from the initial AI-labeling rollout:

- `labelstudio-import --prelabel` can generate AI labels and upload them as completed annotations.
- Inline annotation upload remains best-effort; if rejected by Label Studio, fallback path uploads tasks first and creates annotations after import.
- Note: `labelstudio-decorate` was removed from runtime on 2026-02-22.

Guardrails:

- Offset integrity depends on exact `segment_text` plus `source_map.blocks` positions.
- Provider output parsing must tolerate prose-wrapped JSON by extracting the first valid JSON payload.

### 9.2 2026-02-22_11.51.30 interactive prelabel mode selector

Interactive freeform import contract:

- Replace binary prelabel prompt with a mode picker that includes:
  - no prelabel,
  - strict annotation prelabel,
  - allow-partial annotation prelabel,
  - advanced predictions modes.
- Selected mode maps directly to runtime flags:
  - `prelabel`
  - `prelabel_upload_as`
  - `prelabel_allow_partial`

### 9.3 2026-02-22_12.25.10 Codex non-interactive default and TTY fallback

Codex provider execution contract:

- Default command for prelabel is non-interactive `codex exec -`.
- If user config/env still points to plain `codex`, provider auto-retries with `codex exec -` when stderr reports `stdin is not a terminal`.
- Existing override surfaces remain unchanged (`--codex-cmd`, `COOKIMPORT_CODEX_CMD`).

### 9.4 2026-02-22_12.36.08 interactive import spinner wiring

Interactive and non-interactive import behavior must share callback plumbing:

- Interactive Label Studio import passes a callable `progress_callback` into `run_labelstudio_import(...)`.
- Spinner/status rendering should stay in one shared helper path to avoid drift.

### 9.5 2026-02-22_12.55.46 task X/Y counters for AI labeling

Progress message contract where totals are known:

- Freeform prelabel loop emits `Running freeform prelabeling... task X/Y`.
- Counter text ownership stays in runtime loops (`ingest.py` / provider calls), not UI wrappers.

### 9.6 2026-02-22_13.56.20 freeform label taxonomy refresh

Canonical freeform labels and ordering:

- `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `YIELD_LINE`, `TIME_LINE`, `RECIPE_NOTES`, `RECIPE_VARIANT`, `KNOWLEDGE`, `OTHER`

Back-compat normalization rules to preserve:

- `TIP -> KNOWLEDGE`
- `NOTES` / `NOTE -> RECIPE_NOTES`
- `VARIANT -> RECIPE_VARIANT`
- `NARRATIVE -> OTHER`
- `YIELD -> YIELD_LINE`
- `TIME -> TIME_LINE`

Project-type inference, prelabel normalization, and freeform eval/export mapping should continue using shared freeform label-config normalization logic.

## Merged Understanding Notes (2026-02-22 batch)

### Prompt template loading contract

Sources merged:
- `docs/understandings/2026-02-22_15.10.37-llm-pipelines-prompt-template-loader.md`
- `docs/understandings/2026-02-22_14.49.45-freeform-prelabel-full-vs-augment-prompt-contract.md`

Durable notes:
- Prelabel prompt text is file-backed from `llm_pipelines/prompts/` (`freeform-prelabel-full.prompt.md` and `freeform-prelabel-span.prompt.md`) with placeholder replacement per task.
- Template loader behavior is mtime-aware so edits are picked up without code changes.
- Missing/empty template files fall back to in-code defaults in `cookimport/labelstudio/prelabel.py`.
- Historical context: augment/decorate runtime mode was removed (2026-02-22); do not reuse legacy "label every block" full-mode instructions when implementing sparse/additive semantics in future features.

### Codex model/account resolution and preflight contract

Sources merged:
- `docs/understandings/2026-02-22_16.13.47-codex-model-cache-vs-runtime-access.md`
- `docs/understandings/2026-02-22_16.38.41-codex-command-vs-account-resolution.md`
- `docs/understandings/2026-02-22_17.07.31-freeform-prelabel-codex-home-override.md`
- `docs/understandings/2026-02-22_19.00.30-codex-prelabel-thinking-effort-injection.md`

Durable notes:
- Cached model menus (`models_cache.json`) can include entries that fail at runtime for the active login/account mode.
- Prelabel should keep one up-front provider probe so unsupported model/account combinations fail once before task loops.
- Command-aware resolution must be used for model/cache/account discovery (`--codex-cmd` -> `COOKIMPORT_CODEX_CMD` -> `codex exec -`) and must honor `CODEX_HOME`.
- Home precedence defaults to `~/.codex` before `~/.codex-alt`; explicit `CODEX_HOME=...` wrappers are the stable override when account choice matters.
- Reasoning effort should be injected via Codex config override (`-c model_reasoning_effort=\"...\"`) only after command resolution, and only if command text does not already set it.
- Interactive prelabel prompt order should remain: style -> account display -> model -> thinking effort.
- Prelabel reports should include resolved reasoning effort metadata for auditability alongside command/model/account.
- JSON event `turn.failed` provider detail should be surfaced in reports/errors directly, not collapsed into generic parse failures.

### Span quote resolution and legacy block-mode boundary

Sources merged:
- `docs/understandings/2026-02-22_17.27.33-freeform-span-quote-resolution-contract.md`
- `docs/understandings/2026-02-22_18.55.39-freeform-vs-legacy-prelabel-runtime-contract.md`

Durable notes:
- `span` mode is quote-anchored first; absolute offsets are accepted only after strict bounds checks.
- Repeated quote text in one block requires explicit `occurrence` (1-based); ambiguous matches are dropped.
- `value.text` must always be recomputed from `segment_text[start:end]` for Label Studio offset integrity.
- `block` mode remains full-block span mapping from `{block_index, label}` with tolerant coverage semantics.
- Task-level failures occur only when no valid spans remain (or provider call fails); item-level parsing/resolution failures are dropped.

### Resume gating for new projects

Source merged:
- `docs/understandings/2026-02-22_17.36.48-labelstudio-resume-gate-for-new-projects.md`

Durable notes:
- Resume metadata checks should apply only when the target Label Studio project existed before the current run.
- For benchmark auto-named projects, scope mismatch during resume checks should trigger deduped project-name retry (`-1`, `-2`, ...) instead of immediate failure.

## 10) Merged Task Specs (2026-02-22 docs/tasks import batch)

### 10.1 Prompt refresh and file-backed template workflow

Merged task sources:
- `docs/tasks/2026-02-22_14.49.14 - refresh-freeform-prelabel-prompt.md`
- `docs/tasks/2026-02-22_15.10.22 - llm-pipelines-prompt-templates.md`

Current-state contracts:
- Full-mode freeform prelabel prompt content follows `docs/06-label-studio/AI-labelling-instructions.md`.
- Prompt text is file-backed in `llm_pipelines/prompts/` and loaded at runtime with placeholder substitution.
- Missing/empty template files intentionally fall back to in-code defaults so imports still run.
- Prompt wording iteration should stay text-only in template files; keep placeholder tokens stable unless runtime parser logic is updated in the same change.

### 10.2 Command/account-aware interactive prelabel model selection

Merged task source:
- `docs/tasks/2026-02-22_16.38.50 - interactive-prelabel-codex2-account-selection.md`

Current-state contracts:
- Interactive freeform prelabel does not ask users to choose command alias.
- Command resolution remains `--codex-cmd` -> `COOKIMPORT_CODEX_CMD` -> `codex exec -`, with `CODEX_HOME` honored for model/account cache lookup.
- Resolved account identity should be displayed before model selection when discoverable.
- `codex2` command naming must still receive non-TTY `exec -` fallback behavior.

### 10.3 Span granularity mode alongside legacy block mode

Merged task source:
- `docs/tasks/2026-02-22_17.27.33 - freeform-span-granularity-mode.md`

Current-state contracts:
- `labelstudio-import` supports `--prelabel-granularity block|span` (default `block`).
- Interactive freeform flow keeps explicit style labels:
  - `actual freeform` (span-mode)
  - `legacy, block based` (block-mode)
- Span mode supports multiple sub-block highlights via quote-anchored resolution and strict offset/text integrity checks.
- Block mode behavior remains unchanged for backward compatibility.

### 10.4 Resume-scope mismatch handling in benchmark upload flows

Merged task source:
- `docs/tasks/2026-02-22_17.37.19 - benchmark-resume-scope-mismatch.md`

Current-state contracts:
- Resume metadata checks only run when the target project pre-existed before current upload.
- New-project uploads ignore stale local manifest `task_scope` values.
- Benchmark auto-named projects resolve scope collisions by creating a deduped project title (`-1`, `-2`, ...) instead of hard-failing.

### 10.5 Processing-time summary output for imports

Merged task source:
- `docs/tasks/2026-02-22_18.11.44 - labelstudio-import-processing-time-summary.md`

Current-state contracts:
- Interactive and non-interactive Label Studio import summaries include `Processing time: ...`.
- Duration format remains human-readable (`Xs`, `Ym Zs`, `Xh Ym Zs`) via shared formatter logic.

### 10.6 Codex thinking-effort picker and CLI aliasing

Merged task source:
- `docs/tasks/2026-02-22_19.00.14 - prelabel-codex-thinking-effort-picker.md`

Current-state contracts:
- Interactive freeform prelabel asks for thinking effort immediately after model selection.
- Accepted values: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`.
- CLI supports `--codex-thinking-effort` with alias `--codex-reasoning-effort`.
- Runtime injection remains additive via Codex config override (`model_reasoning_effort`) and should not overwrite command text that already sets this key.
- Prelabel summary/report must include resolved effort metadata for reproducible reruns.

### 10.7 Known-bad loops to avoid (from these merged tasks)

- Do not reintroduce interactive command-picker UI for freeform prelabel account switching; use command-aware home/account resolution instead.
- Do not apply stale local resume manifests to newly created projects.
- Do not collapse span mode back to one-label-per-block behavior; keep quote-anchored sub-block semantics intact.
- Do not fork prompt text back into Python string literals when file-backed templates are available.

## 11) Merged Understandings Batch (2026-02-23 cleanup)

### 11.1 Block vs span prelabel outputs are intentionally different

Merged source:
- `docs/understandings/2026-02-22_19.03.31-freeform-block-vs-span-export-differences.md`

Durable interpretation rule:
- If two freeform runs used different `prelabel_granularity` values, changed label distribution and block coverage are expected.
- `block` mode pushes one-label-per-block full-block coverage.
- `span` mode is selective and drops ambiguous/unresolvable selections.

Observed paired-run anchor (kept to avoid re-debug loops):
- Same segmentation input in both runs (`42` segments, `1471` unique source blocks in manifests).
- Exported span rows: `1635` (`block`) vs `1355` (`span`).
- Unique touched blocks: `1440` (`block`) vs `1201` (`span`).
- Sub-block span share: `0%` (`block`) vs `7.8%` (`span`).

### 11.2 Focus/context + task-count overlap contracts

Merged sources:
- `docs/understandings/2026-02-22_19.35.04-freeform-context-focus-task-count-math.md`
- `docs/understandings/2026-02-22_19.48.08-freeform-focus-overlap-resolution-and-prompt-gating.md`
- `docs/understandings/2026-02-22_22.53.30-freeform-focus-overlap-gap-floor.md`
- `docs/understandings/2026-02-22_23.31.40-freeform-centered-focus-context-boundaries.md`

Durable rules:
- Task-count tuning happens by solving effective overlap (`segment_overlap_effective`) against requested `target_task_count`.
- Prompt instructions are not enough; runtime parsing/filtering is the hard guardrail for focus-only labeling.
- Focus coverage floor is mandatory:
  - `segment_overlap_effective >= segment_blocks - segment_focus_blocks`
- Focus windows should remain centered when possible so prompt streams show stable `context-before` and `context-after`.

### 11.3 Prompt payload and prelabel observability contracts

Merged sources:
- `docs/understandings/2026-02-22_19.50.52-prelabel-prompt-log-contract.md`
- `docs/understandings/2026-02-22_23.01.05-freeform-span-prompt-focus-markers.md`

Durable rules:
- Run roots must keep `prelabel_prompt_log.md` and manifest/report pointers to it.
- Span prompts should use one markerized block stream (`BLOCKS_WITH_FOCUS_MARKERS_COMPACT_LINES`; legacy alias `BLOCKS_WITH_FOCUS_MARKERS_JSON_LINES`) and avoid duplicate focus text payloads.

### 11.4 Parallel prelabel + progress/failure visibility contracts

Merged sources:
- `docs/understandings/2026-02-22_23.15.57-freeform-prelabel-parallelism-contract.md`
- `docs/understandings/2026-02-22_23.54.29-prelabel-worker-banner-task-counter.md`
- `docs/understandings/2026-02-23_00.01.05-freeform-prelabel-workers-visible-on-progress.md`
- `docs/understandings/2026-02-23_00.10.26-prelabel-timeout-and-partial-failure-visibility.md`
- `docs/understandings/2026-02-23_00.22.44-labelstudio-progress-callbacks-must-be-best-effort.md`

Durable rules:
- Freeform prelabel task calls are independent and safely parallelizable at task level; maintain deterministic task indexing in logs/reports.
- Keep `task X/Y` counters visible through kickoff and completion updates in parallel mode (with worker metadata).
- Default prelabel timeout is `300` seconds per provider call.
- Any `failure_count > 0` must surface explicit completion summary text and `prelabel_errors.jsonl` path.
- Progress callbacks are telemetry-only and must not abort convert/task/upload paths if UI code throws.

### 11.5 Codex effort and reasoning-usage shape contract

Merged sources:
- `docs/understandings/2026-02-22_19.06.24-codex-prelabel-thinking-effort-injection.md`
- `docs/understandings/2026-02-23_10.25.11-codex-prelabel-reasoning-usage-shape.md`

Durable rules:
- Thinking effort is injected as `model_reasoning_effort` only after command resolution and only when command text does not already set it.
- Interactive prompt order remains `style -> account -> model -> thinking effort`.
- Codex usage payloads may omit reasoning fields; parsing must remain shape-tolerant and default reasoning totals to `0` when absent.

### 11.6 Span prompt anti-whole-block guardrails

Merged source:
- `docs/understandings/2026-02-23_10.45.43-span-prompt-whole-block-collapse-guardrails.md`

Durable prompt-design guidance:
- Span mode can still collapse to mostly full-block selections if prompt text implies block-propagation behavior.
- Keep explicit anti-whole-block rules for long blocks (for example `>160` chars unless nearly uniform label).
- Keep context guidance phrased as interpretation-only; do not imply adjacent-block auto-labeling.
- Preserve concrete mixed-block examples in prompt instructions so the model sees expected split-label output shape.

### 11.7 2026-02-23 freeform payload/throughput hardening batch

Merged sources:
- `docs/understandings/2026-02-23_11.18.25-span-prompt-compact-block-stream.md`
- `docs/understandings/2026-02-23_11.54.43-prelabel-rate-limit-stop.md`
- `docs/understandings/2026-02-23_12.12.00-freeform-focus-only-task-text.md`

Durable rules:
- Span prompts should keep compact markerized block payload lines as `<block_index><TAB><block_text>` via `BLOCKS_WITH_FOCUS_MARKERS_COMPACT_LINES` (legacy alias `BLOCKS_WITH_FOCUS_MARKERS_JSON_LINES` remains supported).
- On the first provider `HTTP 429`/rate-limit failure, set one shared stop signal so queued tasks skip provider calls, record skipped/error state in `prelabel_errors.jsonl`, and emit an explicit `429` warning.
- Freeform task payload split stays strict:
  - `segment_text` + `source_map.blocks` are offset-authoritative focus rows only (what annotators label),
  - `source_map.context_before_blocks` + `source_map.context_after_blocks` are prompt-only context rows for AI prelabeling,
  - prompt builder may fallback to legacy `source_map.blocks`-only payloads when context arrays are absent.

## 12) Merged Task Specs (2026-02-22_23 to 2026-02-23_10)

### 12.1 2026-02-22_23.16.06 bounded parallel freeform prelabel workers

Task source:
- `docs/tasks/2026-02-22_23.16.06 - parallel-freeform-prelabel-workers.md`

Current contract:
- Freeform prelabel task calls run with bounded concurrency (`--prelabel-workers`, default `15`; set `1` for serial behavior).
- Runtime keeps deterministic downstream artifacts by sorting completed task results by task index before report/log writes.
- Provider usage aggregation remains thread-safe when one provider instance is reused.

### 12.2 2026-02-22_23.31.26 centered focus/context markers

Task source:
- `docs/tasks/2026-02-22_23.31.26 - freeform-focus-context-markers.md`

Current contract:
- Focus windows are centered when possible within each segment.
- Markerized prompt streams keep explicit context-before/context-after boundaries around focus start/stop markers.
- Label Studio tasks expose focus/context range hints (`focus_scope_hint` and related range fields).
- Overlap floor remains mandatory to avoid unlabeled holes:
  - `segment_overlap_effective >= segment_blocks - segment_focus_blocks`.

### 12.3 2026-02-22_23.55.11 kickoff counters with workers metadata

Task source:
- `docs/tasks/2026-02-22_23.55.11 - keep-prelabel-worker-banner-task-counter.md`

Current contract:
- Parallel kickoff message keeps `task 0/Y` and appends worker suffix (`(workers=N)`), instead of switching to worker-only banner text.

### 12.4 2026-02-23_00.01.05 workers visible on completion updates

Task source:
- `docs/tasks/2026-02-23_00.01.05 - keep-prelabel-workers-visible-during-progress.md`

Current contract:
- Parallel prelabel progress keeps `(workers=N)` on completion updates (`task 1/Y`, `task 2/Y`, ...), not kickoff-only.
- Serial mode keeps plain `task X/Y` output without worker suffix.

### 12.5 2026-02-23_00.10.13 timeout + explicit partial-failure summary

Task source:
- `docs/tasks/2026-02-23_00.10.13 - prelabel-timeout-and-error-summary.md`

Current contract:
- Default prelabel timeout is `300` seconds per provider call.
- Completion output always shows explicit prelabel-failure summary when failures exist (including allow-partial runs), with `prelabel_errors.jsonl` path guidance.

### 12.6 2026-02-23_00.22.43 progress callback failures are non-fatal

Task source:
- `docs/tasks/2026-02-23_00.22.43 - protect-ingest-from-progress-callback-failures.md`

Current contract:
- Progress callback forwarding in ingest is best-effort telemetry.
- Callback exceptions are logged and ignored so convert/task/upload behavior continues.
- Single-job artifact generation also routes through the same safe notifier wrapper.

### 12.7 2026-02-23_10.25.11 reasoning-token usage accounting

Task source:
- `docs/tasks/2026-02-23_10.25.11 - prelabel-reasoning-token-usage.md`

Current contract:
- Prelabel usage summaries include `reasoning_tokens` in both run artifacts and CLI summary text.
- Parsing remains backward-compatible when Codex payloads omit reasoning fields (defaults to `0`).
- Parser is shape-tolerant for nested/alias reasoning-token fields while preserving existing usage keys.

## 13) Archived Task Merge (2026-02-23_13.35.17)

### 13.1 Source task docs consolidated and retired from `docs/tasks`

- `docs/tasks/000-AI-labelling-golden.md`
- `docs/tasks/000-AI-span-freeform-fr.md`
- `docs/tasks/2026-02-22_19.35.04-freeform-focus-task-count.md`
- `docs/tasks/2026-02-23_12.11.30-freeform-focus-only-labelstudio-text.md`
- These records are now preserved in this README plus `docs/06-label-studio/06-label-studio_log.md`.

### 13.2 Freeform prelabel baseline preserved from 2026-02-20

- The canonical workflow remains `labelstudio-import --prelabel` with completed `annotations` as default and `predictions` only as an advanced/debug mode.
- Inline-annotation rejection remains a known Label Studio compatibility case; the fallback contract stays: import tasks first, then create per-task annotations by deterministic `segment_id` mapping.
- Offset safety remains strict: span offsets are always derived against the exact uploaded `segment_text` and validated against substring/text integrity.
- Run audit artifacts from this batch remain required: `prelabel_report.json` and `prelabel_errors.jsonl`.

### 13.3 Preserved span/focus decisions from retired task plans

- Keep `block` mode as backward-compatible default and `span` mode as explicit operator choice.
- In `span` mode, quote-anchored selections remain primary; repeated quotes require `occurrence` or they are dropped.
- Focus-only labeling remains parser-enforced (not prompt-only); out-of-focus selections are dropped deterministically.
- Task-count tuning remains deterministic with overlap tie-breaking that leans toward operator intent (more overlap for higher target task counts, less overlap for lower targets).

### 13.4 Preserved payload split contract from 2026-02-23 focus-only shift

- `data.segment_text` and `data.source_map.blocks` remain focus-only and offset-authoritative.
- Prompt-only context rows remain separate in `data.source_map.context_before_blocks` and `data.source_map.context_after_blocks`.
- Prelabel prompt construction must continue supporting both new split payloads and legacy payloads lacking context arrays.
- Coverage accounting must include focus blocks plus context arrays so warnings do not under-report source coverage after the split.

## 14) Merged Understanding (2026-02-24 cleanup)

### 14.1 2026-02-23_15.55.42 golden recipe-header count flow

Merged source:
- `docs/understandings/2026-02-23_15.55.42-golden-recipe-header-count-flow.md`

Durable freeform export/eval contract:
- `labelstudio-export` persists recipe-header counts in `exports/summary.json` under:
  - `counts.recipe_headers`,
  - `recipe_counts.recipe_headers` (deduped),
  - `recipe_counts.recipe_headers_raw` (raw).
- Header count source is normalized `RECIPE_TITLE` spans, deduped by source identity + block range.
- Benchmark/eval reports should surface `recipe_counts` diagnostics with predicted-vs-golden deltas so operators can compare recipe totals separately from span metrics.

## 15) Merged Understandings Batch (2026-02-24 prelabel reliability cleanup)

### 15.1 Interactive prelabel effort compatibility filtering

Merged discovery:
- `2026-02-24_21.34.27-prelabel-effort-compatibility-filtering`

Durable rules:
- Interactive effort choices must be filtered by selected-model metadata (`supported_reasoning_levels`) and known Codex tool-compatibility constraints.
- If configured default effort is incompatible with selected model/tool constraints, hide "use default" and force explicit valid choice.
- Keep invalid values (for example `minimal` under incompatible toolset/model combinations) out of menus up front instead of relying on provider-error retries.

### 15.2 Span prelabel quote-repair + empty-output semantics

Merged discovery:
- `2026-02-24_22.03.07-freeform-prelabel-repair-pass`

Durable rules:
- Empty `[]` model output is valid "no spans" and should not be treated as a provider failure.
- For quote-anchored span rows where `quote` is valid but `block_index` is wrong, run repair pass:
  - try nearby focus blocks first,
  - then accept a unique match across focus window.
- Only attach `task["annotations"]` when repaired/final result is non-empty.

## 16) 2026-02-24_22.44.09 docs/tasks archival merge batch (prelabel effort filtering)

### 16.1 Archived source task merged into this section

- `docs/tasks/2026-02-24_21.34.27-prelabel-invalid-effort-choices.md`

### 16.2 Current interactive effort-menu contract (durable)

- Interactive freeform prelabel effort menus must not expose known-invalid choices that fail immediately at provider preflight/runtime.
- `minimal` remains excluded in this workflow due known incompatibilities with current tool-enabled paths.
- Effort choices are filtered against selected-model metadata when available (`supported_reasoning_levels`-style constraints).
- If configured/default effort is incompatible with selected model + workflow constraints, the "use default" option is hidden and operator must pick a valid effort explicitly.

### 16.3 Validation evidence preserved from task

- `tests/labelstudio/test_labelstudio_prelabel.py -k 'list_codex_models'` passed in task session.
- `tests/labelstudio/test_labelstudio_benchmark_helpers.py -k 'interactive_labelstudio_freeform_scope_routes_to_freeform_import or interactive_labelstudio_filters_incompatible_effort_choices'` passed in task session.

## 17) Merged Understanding (2026-02-25 freeform-only migration)

### 17.1 2026-02-25_18.33.47 freeform-only scope behavior + shared archive helpers

Merged source:
- `docs/understandings/2026-02-25_18.33.47-labelstudio-freeform-only-migration.md`

Durable Label Studio contract:
- Keep scope detection only for UX and explicit rejection messaging.
- Do not keep scope-specific execution branches in import/export/eval command paths.
- Shared extracted-archive helper code used by stage-block predictions belongs in `cookimport/labelstudio/archive.py`, not legacy-named scope modules.

Anti-loop note:
- If stage-block prediction artifact generation fails after scope cleanup, check shared archive helper imports first before reintroducing legacy scope modules.

## 18) Merged Task Spec (2026-02-25 docs/tasks archival batch)

### 18.1 2026-02-25_17.45.03 remove-labelstudio-legacy-scopes

Merged source:
- `docs/tasks/2026-02-25_17.45.03-remove-labelstudio-legacy-scopes.md`

Durable Label Studio contract:
- Runtime import/export/eval command paths are freeform-only (`freeform-spans`).
- Legacy scope selection surfaces (`pipeline`, `canonical-blocks`) stay removed from:
  - `cookimport labelstudio-import`,
  - `cookimport labelstudio-export`,
  - `cookimport labelstudio-eval`,
  - interactive Label Studio import/export/eval menu flows.
- Legacy manifests/projects can still be discovered for UX but export must reject them with explicit unsupported-scope errors.

Key implementation boundary from task:
- Shared extracted-archive and display-text normalization helpers needed by stage-block prediction generation were moved to scope-neutral `cookimport/labelstudio/archive.py`.
- Scope inference helpers may remain for picker labeling/rejection messaging, but not for execution branch selection.

Task-level verification evidence (preserved):
- `pytest tests/labelstudio/test_labelstudio_ingest_parallel.py tests/labelstudio/test_labelstudio_freeform.py tests/labelstudio/test_labelstudio_benchmark_helpers.py tests/labelstudio/test_labelstudio_export.py tests/staging/test_run_manifest_parity.py`
  - `125 passed, 2 warnings`
- `pytest -m "labelstudio or bench or staging"`
  - `238 passed, 382 deselected, 7 warnings`

Anti-loop note:
- If a fix proposal reintroduces scope flags/options for compatibility, treat that as contract-breaking unless the product direction explicitly changes.
