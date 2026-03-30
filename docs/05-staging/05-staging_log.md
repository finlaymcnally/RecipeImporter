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
- Single-file stage flow and split-job merge flow still converge on the same staging/session output contract for intermediate/final drafts, non-recipe artifacts, sections, chunks, raw artifacts, and reports.
- Split jobs add one extra step: move raw artifacts from `.job_parts/<workbook>/job_<index>/raw/...` into run `raw/...`.
- Cookbook safety normalization remains in `draft_v1.py` (ingredient line shaping), not in writer functions.
- Historical staging failures were primarily quantity-kind/qty invariant violations, not unresolved ID placeholder handling.

### 2026-02-15_22.48.59 report metadata flow consistency

Preserved rule:
- Single-file and split EPUB/PDF paths both construct report metadata independently before final report write.
- Metadata fields that downstream tooling depends on (notably `importerName` and `runConfig`) must be set in both paths or split runs will silently drift.

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

5. Reporting only a generic merge status after worker completion
- Why bad: long post-merge phases can look like a hang and trigger false debugging loops.
- Keep: phase-level merge status callbacks for authoritative-output, raw-merge, and report stages.

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
- In `_merge_source_jobs(...)`, writing report before `_merge_raw_artifacts(...)` undercounted moved raw files in `report.outputStats`.

Durable decisions:
- Keep report emission after raw-merge completion.
- Record merged `raw/.../full_text.json` and every moved raw destination as output stats are produced.
- Keep parity coverage in `tests/staging/test_split_merge_status.py::test_merge_source_jobs_output_stats_match_fresh_directory_walk`.

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

### 2026-03-22 Non-Recipe Route and Finalization stopped pretending review routing was final semantic authority

Problem captured:
- Non-Recipe Route and Finalization was still collapsing every outside-recipe block to deterministic `knowledge|other` even when the optional knowledge stage had not reviewed that row yet.
- That let downstream scoring and Label Studio projection overwrite correct raw line-role lesson headings with seed `OTHER`, which looked like a model-quality bug even when the overlap was architectural.

Durable decisions:
- Non-Recipe Route and Finalization is routing plus bookkeeping, not the semantic owner for candidate outside-recipe prose.
- `08_nonrecipe_route.json`, `09_nonrecipe_authority.json`, and `09_nonrecipe_finalize_status.json` now keep these seams distinct across routing, final authority, and unresolved-candidate bookkeeping.
- `stage_block_predictions.json` and Label Studio projection must read only explicit final authority, not the whole fallback category map.
- excluded obvious-junk rows still remain immediately authoritative final `other`; the ambiguity applies only to candidate rows.

Anti-loop note:
- if a future fix proposal wants to make Non-Recipe Route and Finalization "smart enough" to finalize candidate outside-recipe `KNOWLEDGE` again, re-check the March 22 authority-overlap failure first.

### 2026-03-22 nonrecipe staging diagnostics shifted from fake semantic totals to explicit exclusion ledgers

Problem captured:
- once Non-Recipe Route and Finalization became routing-first, older diagnostics that implied line-role or Non-Recipe Route and Finalization already "owned" outside-recipe semantic knowledge became misleading.
- obvious-junk pruning needed a row-level explanation surface so operators could tell whether knowledge input was shrinking for the right reason.

Durable decisions:
- keep `08_nonrecipe_exclusions.jsonl` as the row-level ledger for upstream excluded junk, with stable review-exclusion reasons and representative examples.
- when knowledge-stage input feels bloated or mysteriously small, inspect the exclusion ledger and Non-Recipe Route and Finalization routing counts before changing scorer logic, bundle topology, or knowledge prompts.
- retain the stable external `knowledge|other` output contract, but treat exclusion ledgers and refinement reports as the real explanation layer for how rows moved through Non-Recipe Route and Finalization.

Anti-loop note:
- do not use older line-role `KNOWLEDGE` budget counts as the primary diagnostic for this seam; after the routing-only cutover, exclusion ledgers and explicit final-authority maps tell the truthful story.

Anti-loop note:
- If a section header becomes the final recipe title, trace `canonical_line_roles.py -> apply_line_role_spans_to_recipes(...)` before changing stage-block heuristics.

### 2026-03-16_20.01.25 report totals mismatch is usually importer-vs-stage authority drift

Problem captured:
- `*.report_totals_mismatch_diagnostics.json` looked like an arithmetic-bug detector, but processed-output runs were mostly firing because stage sessions inherited importer-era `ConversionReport` totals and then compared them against final stage-owned counts

Durable decisions:
- treat this mismatch artifact as an authority-seam warning first, not proof that the final stage counts are wrong
- `execute_stage_import_session_from_result(...)` and `enrich_report_with_stats(...)` should not pretend inherited importer totals and final stage totals are the same contract
- the clean long-term fix is to start stage-owned totals from a fresh `ConversionReport`, or to keep inherited importer counts under a separate legacy/debug namespace so `finalize_report_totals(...)` compares authoritative-with-authoritative

Anti-loop note:
- if report totals mismatch appears mainly on processed-output reruns, inspect inherited `result.report` usage before debugging the final counting math
