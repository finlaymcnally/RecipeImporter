---
summary: "Staging architecture/build/fix-attempt log used to avoid repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on staging behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need historical architecture versions, build attempts, and known failed paths before trying another change
---

# Staging Log: Architecture, Builds, and Fix Attempts

Read this file when work starts looping across turns, or when someone says "we are going in circles on this."

This log is the anti-loop record for staging: what changed, why, what worked, and what remains risky.

## Chronology: What Was Documented/Tried Before

### 2026-02-12_10.25.47 format naming conventions

Decision captured:

- Use `schema.org Recipe JSON` for intermediate and `cookbook3` for final in docs/help text.
- Do not describe intermediate format as `RecipeSage`.
- `RecipeDraftV1` remains internal term.

Status now: still correct and reflected in current stage CLI help text and stage command output layout docs.

### 2026-02-12_10.41.48 staging contract alignment

Problem captured:

- Final draft output drifted from Cookbook staging import invariants.
- Failures occurred even after resolver normalization.

Key decisions/actions captured:

- Normalize ingredient lines in `draft_v1.py` post-parse/post-assignment.
- Do not generate random UUIDs for unresolved ingredient IDs.
- Preserve lowercasing and step-linking behavior.

Recorded evidence at that time:

- `pytest -q tests/staging/test_draft_v1_lowercase.py tests/staging/test_draft_v1_variants.py tests/parsing/test_ingredient_parser.py tests/staging/test_draft_v1_staging_alignment.py`
- Result recorded: `35 passed`.
- Cross-repo schema validation cases recorded as passing for:
  - `salt, to taste`
  - `0`
  - `1 cup flour`

Status now: rules still present in current `draft_v1.py` and corresponding tests remain in repo.

### 2026-02-12_10.41.48 staging contract edge cases

Critical invariant note captured:

- Cookbook staging tolerates unresolved IDs if placeholders are non-empty and unresolved unit IDs are `null`.
- But quantity invariants are strict:
  - non-linked `exact`/`approximate` require `input_qty > 0`
- `unquantified` must have null/omitted quantity+unit

Status now: these edge-case rules are still actively normalized in `draft_v1.py`.

### 2026-02-15_22.10.59 staging output contract flow map

Preserved outcomes:
- Single-file stage flow (`cli_worker`) and split-job merge flow (`cli.py`) both converge on the same writer functions for intermediate/final/tips/topic/chunks/report outputs.
- Split jobs add one extra step: move raw artifacts from `.job_parts/<workbook>/job_<index>/raw/...` into run `raw/...`.
- Cookbook safety normalization remains in `draft_v1.py` (ingredient line shaping), not in writer functions.
- Historical staging failures were primarily quantity-kind/qty invariant violations, not unresolved ID placeholder handling.

### 2026-02-15_22.48.59 report metadata flow consistency

Preserved rule:
- Single-file report writes happen in `cli_worker.stage_one_file`.
- Split EPUB/PDF report writes happen in `cli._merge_split_jobs`.
- Metadata fields that downstream tooling depends on (notably `importerName` and `runConfig`) must be set in both paths or split runs will silently drift.

### 2026-02-15_22.59.48 split-merge bottleneck diagnosis from real run data

Preserved diagnosis:
- Long "idle" periods after worker completion can be real merge output work, not a deadlock.
- Example captured from `data/output/2026-02-15_22.47.11`: one EPUB merge spent about 172 seconds in `write_topic_candidates_seconds`.
- Root cause in that run shape was repeated `_resolve_file_hash(...)` fallback hashing for candidates missing `file_hash`.

Anti-loop note:
- Do not treat post-100%-progress hangs as automatic concurrency bugs until merge-phase timing fields are checked.
- Do not remove topic-candidate provenance to speed up writes; keep provenance and cache hash lookup instead.

### 2026-02-15_22.59.30 split-merge visibility and topic hash cache

Problem captured:
- Large split EPUB/PDF runs could look hung after workers completed because merge stayed under a generic MainProcess label while doing long post-merge writes.
- Topic-candidate writing repeatedly hashed the same source file, inflating merge-time write cost on knowledge-heavy inputs.

Decisions/actions captured:
- Add phase-level main-process status updates across merge/report/raw/topic-candidate write phases.
- Cache source hash resolution per source file during topic-candidate ID generation so `_hash_file` runs once per file version, not once per candidate.

Task-spec evidence preserved:
- Fail-before command recorded:
  - `. .venv/bin/activate && pytest -q tests/staging/test_tip_writer.py::test_write_topic_candidates_hashes_source_file_once tests/staging/test_split_merge_status.py::test_merge_split_jobs_reports_main_process_phases`
- Pass-after command recorded:
  - `. .venv/bin/activate && pytest -q tests/staging/test_tip_writer.py tests/staging/test_split_merge_status.py`
- Recorded pass-after result: `3 passed`.

Constraints that should remain:
- Keep split merge output contract unchanged (same files, IDs, and artifact structure).
- Merge progress/status callbacks must be best-effort and never allowed to fail the merge itself.

Rollback note captured in task:
- Removing callback plumbing and hash caching reverts to prior behavior where long merges appear stalled and topic-candidate writes can re-hash per candidate.

## Known Bad Patterns and Anti-Regression Notes

These are the loops we should avoid repeating.

1. Using random UUIDs for unresolved `ingredient_id`
- Why bad: bypasses resolver mapping semantics and can mask true unresolved state.
- Keep: unresolved placeholder should remain meaningful raw text fallback.

2. Letting `approximate`/`exact` lines through with missing/non-positive quantity
- Why bad: Cookbook staging contract rejects these combinations.
- Keep: downgrade to `unquantified` during staging conversion.

3. Emitting unresolved `input_unit_id` as non-null fake value
- Why bad: can violate staging import expectations and creates false precision.
- Keep: `input_unit_id = null` when unresolved; preserve `raw_unit_text`.

4. Leaking section headers into ingredient lines
- Why bad: section headers are structural and invalid as ingredient entries.
- Keep: remove `section_header` lines before final output.

5. Re-hashing the same source file for every topic candidate
- Why bad: adds avoidable merge-time write overhead, especially on knowledge-heavy split runs.
- Keep: source-hash cache behavior in topic-candidate write path.

6. Reporting only a generic merge status after worker completion
- Why bad: long post-merge phases can look like a hang and trigger false debugging loops.
- Keep: phase-level merge status callbacks for report/raw/topic-candidate stages.

### 2026-02-20_12.46.28 staging contract alignment edge cases

Preserved rules:
- Cookbook staging schema allows `source=null` but rejects empty-string source values; normalize blank source to `null`.
- Linked-recipe ingredient lines require stricter normalization:
  - blank `linked_recipe_id` must become `null`,
  - positive `input_qty` values are capped at `100` (missing/non-positive values normalize to `null`),
  - `input_unit_id` and `ingredient_id` should stay `null` for these rows.

Anti-loop note:
- "Looks valid locally" is not enough for staging alignment; enforce these normalizations in `draft_v1.py` before output writes to avoid downstream contract parser failures.

## 2026-02-27 understanding merge batch (staging)

### 2026-02-27_12.00.28 split-merge outputStats ordering and moved-file accounting

Merged source:
- `docs/understandings/2026-02-27_12.00.28-speed1-5-split-merge-outputstats-ordering.md`

Problem captured:
- In `_merge_split_jobs(...)`, writing report before `_merge_raw_artifacts(...)` can undercount moved raw files in `report.outputStats`.

Decision/outcome preserved:
- Keep report emission after raw-merge completion.
- Explicitly record:
  - merged `raw/.../full_text.json`,
  - every moved raw destination produced by `_merge_raw_artifacts(...)`.
- Preserve split-merge parity assertion against real filesystem ground truth.

Verification anchor preserved:
- `tests/staging/test_split_merge_status.py::test_merge_split_jobs_output_stats_match_fresh_directory_walk`

Anti-loop note:
- Avoid reordering report-before-raw-merge for convenience; it reintroduces silent stats drift that looks like analytics/dashboard bugs later.

### 2026-02-27_19.53.48 staging docs completeness audit (code-to-doc map refresh)

Problem captured:
- Staging docs covered core writers/merge flow but missed active runtime surfaces now relied on by tests/tooling:
  - `run_manifest.json` stage artifact contract,
  - explicit `cookimport/staging/stage_block_predictions.py` behavior,
  - split-merge block-index offset + merged `full_text.json` alignment details.

Decisions/actions captured:
- Promote `run_manifest.json` to first-class staging output contract (with code pointers to `_write_stage_run_manifest` + `runs/manifest.py`).
- Document stage-block label resolution behavior (text matching + structural fallback + deterministic conflict priority).
- Expand split-merge flow notes to include block-offset normalization and archive-aware stage-block prediction write.
- Add `tests/staging/test_run_manifest_parity.py` to staging guardrail list.

Anti-loop note:
- If a staging-output change modifies artifact paths or per-run metadata, update both docs and run-manifest parity tests in the same change to avoid silent drift between stage and benchmark/pred-run tooling.

### 2026-02-27_19.47.49 staging docs prune current contracts

Problem captured:
- Staging docs had stale test paths and outdated behavioral wording.

Durable decisions:
- Keep split-merge status/raw-artifact merge chronology and active invariants.
- Retire stale path/line references after test modularization.
- Keep docs wording aligned to actual `_sanitize_staging_line()` behavior for linked recipe quantity fields.

### 2026-02-27_19.53.48 provenance note

Source understanding merged:
- `docs/understandings/2026-02-27_19.53.48-staging-doc-code-coverage-refresh.md`

Current status:
- Run manifest, stage-block builder semantics, and split-merge block-offset coverage are retained in this log and `05-staging_readme.md`.

## 2026-02-28 migrated understanding ledger

Chronological migration from `docs/understandings`; source files were removed after this merge.

### 2026-02-27_20.39.35 recipe notes label intent vs stage comments source

Source: `docs/understandings/2026-02-27_20.39.35-recipe-notes-label-intent-vs-stage-comments-source.md`
Summary: RECIPE_NOTES is intended for recipe-local tips/notes, but stage block predictions currently source it only from recipe.comment fields.

Details preserved:


# RECIPE_NOTES Intent vs Stage Source

Intent (prompt/docs):

- `RECIPE_NOTES` means recipe-specific guidance attached to the current recipe (tips, storage, make-ahead, serving suggestions, cautions, ingredient-specific notes).
- If text is clearly in recipe context, prefer `RECIPE_NOTES` over `KNOWLEDGE`.
- Use `RECIPE_VARIANT` only for distinct alternate versions, not small tips.

Current benchmark stage evidence path:

- `cookimport/staging/stage_block_predictions.py` labels `RECIPE_NOTES` from `_note_texts(recipe)`.
- `_note_texts(recipe)` reads only `recipe.comments` (`comment` in schema.org payload).
- In runs where recipe-local note text lives in `description` and comments are empty, stage block predictions emit zero `RECIPE_NOTES`.

Related observation:

- The draft-v1 conversion path already extracts recipe-specific notes from `candidate.description` into `recipe.notes`, but stage block prediction labeling does not currently read that same source.

### 2026-02-27_20.44.19 stage block recipe notes description source enabled

Source: `docs/understandings/2026-02-27_20.44.19-stage-block-recipe-notes-description-source-enabled.md`
Summary: Stage block prediction now sources RECIPE_NOTES from both schema comments and description-derived recipe-specific notes.

Details preserved:


# Stage Block RECIPE_NOTES Source Expansion

Discovery and fix:

- `cookimport/staging/stage_block_predictions.py` previously built `RECIPE_NOTES` only from `recipe.comments`.
- Many parsed recipes carry note guidance in `description`, extracted elsewhere via `extract_recipe_specific_notes(...)`, so note blocks could be missed.
- `_note_texts(recipe)` now merges:
  - `recipe.comments` text/name
  - deterministic `extract_recipe_specific_notes(recipe)` output from description
- Note rows are normalized/deduped before block matching.

Regression proof:

- Added `test_build_stage_block_predictions_marks_notes_from_description_only` to ensure description-only notes label as `RECIPE_NOTES`.

### 2026-02-27_22.43.10 priority4 ingredient options wiring path

Source: `docs/understandings/2026-02-27_22.43.10-priority4-ingredient-options-wiring-path.md`
Summary: Priority-4 discovery: ingredient parser settings must be threaded at draft-write time, not importer convert time.

Details preserved:


# Priority-4 Wiring Discovery

Ingredient parser behavior is applied in `cookimport/staging/draft_v1.py` (`recipe_candidate_to_draft_v1`), not during importer `convert(...)` extraction.

Implication: adding new `RunSettings` fields is not enough; the selected `run_config` must reach `write_draft_outputs(...)` so draft conversion can pass `ingredient_*` options into `parse_ingredient_line(...)`.

Practical wiring points that must stay aligned:

- `cookimport/cli_worker.py` stage single-file write path
- `cookimport/cli.py` split-merge write path
- `cookimport/labelstudio/ingest.py` processed-output write path

Without this plumbing, stage and benchmark run manifests can show new parser settings while final draft ingredient lines still use parser defaults.

### 2026-02-27_23.17.42 priority5 shared instruction shaping path

Source: `docs/understandings/2026-02-27_23.17.42-priority5-shared-instruction-shaping-path.md`
Summary: Priority-5 implementation note: stage draft/jsonld/sections must all consume one shared effective instruction-shaping path, wired from RunSettings through stage + pred-run flows.

Details preserved:


# Priority-5 Shared Instruction Shaping Path

- `recipe_candidate_to_draft_v1(...)`, `recipe_candidate_to_jsonld(...)`, and `write_section_outputs(...)` had independent instruction handling, so Priority-5 needed one shared segmentation contract passed into all three.
- The safest threading point is existing `run_config` propagation:
  - stage single-file path: `cli_worker.stage_one_file(...)`
  - stage split-merge path: `cli._merge_split_jobs(...)`
  - benchmark/Label Studio pred-run path: `labelstudio.ingest._write_processed_outputs(...)`
- New run-settings knobs (`instruction_step_segmentation_policy`, `instruction_step_segmenter`) must be forwarded through:
  - `RunSettings` + `build_run_settings(...)`
  - CLI `stage` and `labelstudio-benchmark` options
  - `run_settings_adapters` and bench `pred_run`/knob config mapping
  so run manifests and benchmark artifacts record the same effective segmentation behavior used by staged outputs.

### 2026-02-28_00.42.17 howto section auto-emission gap audit

Source: `docs/understandings/2026-02-28_00.42.17-howto-section-auto-emission-gap-audit.md`
Summary: Audited where `HOWTO_SECTION` is handled and identified remaining gap for automatic importer-side emission.

Details preserved:

# HOWTO_SECTION Auto-Emission Gap Audit

Discovery:

- Section headers are already detected deterministically in parsing/staging:
  - `cookimport/parsing/sections.py` (`extract_ingredient_sections`, `extract_instruction_sections`)
  - `cookimport/staging/jsonld.py` (`HowToSection` for instructions, `recipeimport:ingredientSections` metadata)
- `HOWTO_SECTION` exists in freeform label taxonomy and normalization:
  - `cookimport/labelstudio/label_config_freeform.py`
- Freeform eval remaps `HOWTO_SECTION` to ingredient/instruction context:
  - `cookimport/labelstudio/eval_freeform.py`
- Stage/canonical benchmark gold loaders remap `HOWTO_SECTION` in gold paths.

Remaining gap (at time of this note):

- Automatic prediction emission still did not output `HOWTO_SECTION` from imported books.
- `cookimport/staging/stage_block_predictions.py` labeled recipe blocks as title/ingredient/instruction/etc., but did not derive a dedicated section-header label from section-detection outputs.
- Stage/canonical benchmark predicted-label paths needed parity remapping for `HOWTO_SECTION` once prediction emission started using that label.

Implication:

Without importer-side prediction emission, users could label `HOWTO_SECTION` manually in Label Studio and score it, but auto-generated prediction evidence from imports would continue to flatten those headers into ingredient/instruction labels.

### 2026-02-28_00.54.00 stage block howto emission range and remap notes

Source: `docs/understandings/2026-02-28_00.54.00-stage-block-howto-emission-range-and-remap-notes.md`
Summary: HOWTO_SECTION auto-emission required line-range provenance fallback and prediction-side scorer remap parity.

Details preserved:

# Stage HOWTO Emission: Range + Scoring Discovery

- Stage prediction labeling previously skipped recipe-local labels for text imports when provenance had only `start_line`/`end_line` (no `start_block`/`end_block`), producing all-`OTHER` block outputs.
- Fix shape: allow `_resolve_recipe_range(...)` to map provenance line ranges back to archive block indices (line-index aware, with deterministic offset fallback).
- Auto-emission now labels section headers as `HOWTO_SECTION` from deterministic section header hits in ingredients/instructions, with a conservative nearby-structure guardrail.
- Benchmark parity fix requires prediction-side `HOWTO_SECTION` remap (not just gold-side): stage-block loader and canonical line projection both resolve `HOWTO_SECTION` to ingredient/instruction before scoring.

## 2026-02-28 task consolidation (migrated from `docs/tasks`)

### 2026-02-28_00.42.17 importer-side `HOWTO_SECTION` emission implementation

Source task file:
- `docs/tasks/2026-02-28_00.42.17-howto-section-importer-auto-emission.md`

Problem captured:
- `HOWTO_SECTION` existed in staging/Label Studio schema surfaces, but importer-side stage predictions flattened headers into structural labels and never emitted `HOWTO_SECTION`.

Durable decisions/actions:
- Implement emission once in shared stage prediction generation (`cookimport/staging/stage_block_predictions.py`) instead of importer-specific patches.
- Keep implementation deterministic/rule-based only (no LLM parsing path).
- Add recipe-range fallback from provenance lines when block-range provenance is absent.
- Keep benchmark comparability by resolving predicted `HOWTO_SECTION` to structural classes before metrics (`eval_stage_blocks` + `eval_canonical_text`).

Evidence preserved:
- `pytest tests/staging/test_stage_block_predictions.py -q`
- `pytest tests/bench/test_eval_stage_blocks.py -q`
- `pytest tests/labelstudio/test_labelstudio_freeform.py tests/labelstudio/test_labelstudio_benchmark_helpers.py -q`
- Smoke run produced `HOWTO_SECTION` hits in:
  - `/tmp/howto-section-stage/output/2026-02-28_00.56.04/.bench/sectioned/stage_block_predictions.json`

Anti-loop note:
- If section labels disappear again on text imports, verify provenance-range fallback in `_resolve_recipe_range(...)` before changing section extraction heuristics.

## 2026-02-28 docs/tasks consolidation batch (stage sandbox fallback behavior)

### 2026-02-28_12.20.59 process-worker-denied fallback: stage `process -> thread -> serial`

Source task file (historical; removed during later docs consolidation):
- `docs/tasks/2026-02-28_12.20.59-sandbox-parallel-fallbacks-stage-and-labelstudio.md`

Problem captured:
- In sandboxed hosts where process pools fail (`PermissionError`/`SemLock` style startup failures), stage paths fell directly to serial loops and looked like throughput regressions.

Durable decisions/outcomes:
- Added shared fallback helper (`cookimport/core/executor_fallback.py`) and switched stage fallback order to `process -> thread -> serial`.
- Kept serial fallback only as terminal safety behavior.
- Added regression tests for process-denied fallback messaging and behavior.
- Hardened one stage assertion to normalize whitespace because wrapped warning text produced false-negative contiguous-string checks.

Evidence preserved:
- Speed-suite baseline/candidate compare PASS:
  - baseline run `data/golden/bench/speed/runs/2026-02-28_14.35.15`
  - candidate run `data/golden/bench/speed/runs/2026-02-28_14.35.52`
  - compare `data/golden/bench/speed/comparisons/2026-02-28_14.36.36/comparison.json`

Anti-loop note:
- If stage appears serial again, confirm fallback-mode message and executor-resolution telemetry before touching merge/write code paths.

### 2026-02-28_15.00.57 process-worker-denied fallback: stage `process -> subprocess-backed -> thread -> serial`

Source task file was merged into this log during docs consolidation and then removed from `docs/tasks`:
- `2026-02-28_15.00.57-stage-subprocess-worker-fallback-for-shm-restricted-hosts.md`

Problem captured:
- On this host, process pools fail with `PermissionError: [Errno 13] Permission denied` due SemLock restrictions.
- Previous stage fallback improved to threads, but CPU-heavy paths could still degrade and appear near-serial.

Durable decisions/outcomes:
- Added subprocess-backed stage execution path in `cookimport/cli.py` that activates when process workers are denied and stage worker subprocess probe passes.
- Added internal worker entrypoint in `cookimport/cli_worker.py`:
  - `--stage-worker-self-test`
  - `--stage-worker-request <request_json>`
- Subprocess worker path supports single-file, PDF split, and EPUB split jobs and returns pickled result payloads.
- Thread fallback remains as secondary path when subprocess worker launch/probe is unavailable; serial remains terminal safety fallback.

Evidence preserved:
- `. .venv/bin/activate && pytest tests/ingestion/test_performance_features.py -k "process_pool_permission_error_falls_back_to_thread or stage_worker or worker_label" -q`
- `. .venv/bin/activate && cookimport stage /tmp/stage_subprocess_probe/in --out /tmp/stage_subprocess_probe/out --workers 2 --limit 1`
  - Runtime warning now reports subprocess-backed fallback, not serial fallback.
  - Worker panel shows `SubprocessWorker-1`, `SubprocessWorker-2`.

Anti-loop note:
- This does not restore host process-pool capability itself; `/dev/shm`/SemLock policy is still restricted.
- If subprocess fallback regresses, check `--stage-worker-self-test` availability and request/result payload creation under `<out>/.stage_worker_requests` before touching parser/importer logic.

## 2026-02-28 migrated understanding ledger (stage fallback telemetry and subprocess path)

### 2026-02-28_14.42.43 stage thread-fallback worker label collision

Source: `docs/understandings/2026-02-28_14.42.43-stage-thread-fallback-worker-label-collision.md`

Problem captured:
- ThreadPool workers shared one process label key, collapsing worker-status maps and making telemetry appear serial.

Durable decision:
- Include thread names in non-main thread worker labels while keeping main-thread labels stable.

### 2026-02-28_15.00.58 stage subprocess workers bypass process-pool denial

Source: `docs/understandings/2026-02-28_15.00.58-stage-subprocess-workers-bypass-processpool-denial.md`

Problem captured:
- ProcessPool startup failures under SemLock restrictions reduced stage fanout effectiveness.

Durable decision:
- Use subprocess-backed stage workers (with explicit worker labels and telemetry) as recovery path when process pools are denied.

Anti-loop note:
- If stage looks serial in restricted environments, check fallback mode + worker labels before changing merge/write logic.

## 2026-03-01 docs/tasks merge ledger (stage fallback telemetry + subprocess path)

### 2026-02-28_14.42.42 thread-fallback worker label telemetry

Source task was merged into this log and removed from `docs/tasks`:
- `2026-02-28_14.42.42-speedsuite-thread-fallback-worker-label-telemetry.md`

Problem captured:
- In thread fallback mode, process-only worker labels collapsed multiple workers into one key (`MainProcess (pid)`), making stage processing timeseries appear serial.

Durable decisions:
- Worker labels append thread name for non-main threads.
- Main-thread/process-worker labels remain unchanged for compatibility.

Evidence preserved:
- `pytest tests/ingestion/test_performance_features.py -k "worker_label" -q`
- Added tests:
  - `test_worker_label_includes_thread_name_for_thread_fallback`
  - `test_worker_label_keeps_process_only_for_main_thread`

Anti-loop note:
- If `active_workers` appears stuck at `1`, inspect worker-label cardinality before retuning executors.

### 2026-02-28_15.00.57 subprocess-backed worker fallback for SemLock-restricted hosts

Source task was merged into this log and removed from `docs/tasks`:
- `2026-02-28_15.00.57-stage-subprocess-worker-fallback-for-shm-restricted-hosts.md`

Problem captured:
- Process pools failed with permission errors on restricted hosts; thread-only fallback still degraded throughput on CPU-heavy stage work.

Durable decisions:
- Fallback order promoted to `process -> subprocess-backed workers -> thread -> serial`.
- Added stage worker subprocess entrypoint with:
  - `--stage-worker-self-test`
  - `--stage-worker-request`
- Subprocess request/result artifacts are stored under `<out>/.stage_worker_requests`.
- Subprocess workers support `single`, `pdf_split`, and `epub_split` jobs.

Evidence preserved:
- `. .venv/bin/activate && pytest tests/ingestion/test_performance_features.py -k "process_pool_permission_error_falls_back_to_thread or stage_worker or worker_label" -q`
- `. .venv/bin/activate && cookimport stage /tmp/stage_subprocess_probe/in --out /tmp/stage_subprocess_probe/out --workers 2 --limit 1`

Anti-loop note:
- This path is a concurrency workaround under host restrictions, not a fix for host SemLock policy.
