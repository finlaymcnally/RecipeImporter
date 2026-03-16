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

## 2026-02-27 onward: current durable staging history

### 2026-02-27_12.00.28 split-merge outputStats ordering and moved-file accounting

Problem captured:
- In `_merge_split_jobs(...)`, writing report before `_merge_raw_artifacts(...)` undercounted moved raw files in `report.outputStats`.

Durable decisions:
- Keep report emission after raw-merge completion.
- Record merged `raw/.../full_text.json` and every moved raw destination as output stats are produced.
- Keep parity coverage in `tests/staging/test_split_merge_status.py::test_merge_split_jobs_output_stats_match_fresh_directory_walk`.

Anti-loop note:
- If analytics or dashboard counts drift on split runs, check merge ordering before changing report aggregation.

### 2026-02-27_20.44.19 recipe notes and parser-option staging wiring

Problems captured:
- Stage-block prediction missed `RECIPE_NOTES` when recipe-local note text existed only in `description`.
- Ingredient parser options could appear in run config while final drafts still used parser defaults if the settings were not threaded to draft writing.

Durable decisions:
- `stage_block_predictions.py` must source `RECIPE_NOTES` from both schema comments and deterministic description-derived notes.
- Ingredient parser behavior remains a draft-write concern in `recipe_candidate_to_draft_v1(...)`, so new `ingredient_*` settings must be wired through stage single-file, split-merge, and Label Studio processed-output paths.
- Keep regression coverage for description-only notes and draft-v1 staging alignment tests.

Anti-loop note:
- If note labeling or ingredient parsing drifts, inspect staging write-time plumbing before changing importer extraction.

### 2026-02-27_23.17.42 shared instruction shaping path

Problem captured:
- Draft, JSON-LD, and section outputs diverged when instruction segmentation behavior was not driven by one shared run-config path.

Durable decisions:
- `recipe_candidate_to_draft_v1(...)`, `recipe_candidate_to_jsonld(...)`, and `write_section_outputs(...)` must consume the same effective instruction segmentation contract.
- New instruction-shaping settings belong on the run-config path that reaches stage, split-merge, and Label Studio pred-run/processed-output writes.

Anti-loop note:
- If staged sections and final drafts disagree on step boundaries, verify shared run-config propagation before adjusting segmentation heuristics.

### 2026-02-28_00.54.00 deterministic `HOWTO_SECTION` auto-emission

Problem captured:
- Importer-side stage predictions flattened section headers into structural labels and lost recipe-local coverage for text imports that only had line-range provenance.

Durable decisions:
- Emit `HOWTO_SECTION` once in shared stage prediction generation, not in importer-specific code.
- Preserve line-range fallback in `_resolve_recipe_range(...)` so text imports can map `start_line`/`end_line` provenance back to archive blocks.
- Keep benchmark parity by remapping predicted `HOWTO_SECTION` labels before structural scoring.

Verification anchors:
- `tests/staging/test_stage_block_predictions.py`
- `tests/bench/test_eval_stage_blocks.py`

Anti-loop note:
- If `HOWTO_SECTION` disappears again, check provenance remap and scorer remap before changing section detection.

### 2026-02-28_15.00.57 stage worker fallback hardening

Problem captured:
- Restricted hosts denied process-pool startup and made stage runs look serial or badly degraded.

Durable decisions:
- Fallback order is `process -> subprocess-backed workers -> thread -> serial`.
- Subprocess workers are launched through `python -m cookimport.cli_worker --stage-worker-request ...` and support `single`, `pdf_split`, and `epub_split`.
- Thread fallback worker labels must include non-main thread names so `processing_timeseries.jsonl` does not collapse concurrent workers into one key.

Verification anchors:
- `tests/ingestion/test_performance_features.py`

Anti-loop note:
- If stage appears serial on a restricted host, inspect fallback mode, worker labels, and `.stage_worker_requests` artifacts before changing merge/write code.

### 2026-03-02_20.39.37 run summary artifacts and markdown gating

Problem captured:
- Stage runs had enough metadata for quick inspection, but only in verbose reports/manifests, and `run_summary.md` initially risked bypassing markdown gating.

Durable decisions:
- Stage runs always emit `run_summary.json`.
- `run_summary.md` is optional and must obey `--no-write-markdown`.
- `run_manifest.json` should index whichever summary artifacts actually exist.

Anti-loop note:
- Treat summary markdown suppression as part of the staging output contract, not as a special-case UI tweak.

### 2026-03-04_01.54.06 stage live-status slot fallback

Problem captured:
- Stage could collide with other Rich live renderers when it bypassed shared slot gating.

Durable decisions:
- Stage live rendering participates in shared slot gating.
- `COOKIMPORT_LIVE_STATUS_SLOTS` remains the shared capacity control.
- When no live slot is available, plain status output is the expected fallback.

Anti-loop note:
- Plain status under slot contention is normal; do not treat it as a stage-progress regression by default.

### 2026-03-13_23.07.29 title-promotion ownership boundary

Problem captured:
- Wrong-title bugs were easy to misplace because block evidence, canonical line-role ownership, and final draft title overwrite live in different modules.

Durable findings:
- `stage_block_predictions.py` controls deterministic evidence labels only.
- Final `recipe.name` overwrite decisions happen in `draft_v1.py` inside `apply_line_role_spans_to_recipes(...)`.
- Strong syntax-heavy disagreement vetoes belong in `canonical_line_roles.py`, not in the writer path.

Anti-loop note:
- If a section header becomes the final recipe title, trace `canonical_line_roles.py -> apply_line_role_spans_to_recipes(...)` before changing stage-block heuristics.
