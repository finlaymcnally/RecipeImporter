---
summary: "Comprehensive staging/output reference with chronology, code-verified behavior, contract rules, and known failure patterns."
read_when:
  - When changing output paths, filenames, IDs, or report artifacts
  - When modifying draft-v1 conversion or Cookbook staging contract invariants
  - When debugging split-job merge output ordering/raw artifacts
---

# 05 Staging: Consolidated Working Reference

This document consolidates all prior docs in `docs/05-staging/` and reconciles them against current code.

Scope: where staged artifacts are written, how they are shaped, what invariants are required for Cookbook staging import, what has failed before, and what tradeoffs/limitations still exist.

## Why this exists

Staging is the boundary between importer/parsing internals and persisted artifacts used by downstream tools (Cookbook staging import, Label Studio helpers, tagging, analytics). Small output-shape drift here causes expensive rework across the pipeline.

## Quick map: where staging logic lives

- `cookimport/staging/jsonld.py`
  - Intermediate conversion from `RecipeCandidate` to schema.org `Recipe` JSON-LD (+ `recipeimport:*` metadata).
- `cookimport/staging/draft_v1.py`
  - Final conversion to cookbook3 output shape (internal model label still `RecipeDraftV1`).
  - Applies staging safety normalization for ingredient lines.
- `cookimport/staging/writer.py`
  - Writes intermediate/final outputs, tips, topic candidates, chunks, raw artifacts, and report JSON.
  - Generates/stabilizes IDs where needed.
- `cookimport/staging/pdf_jobs.py`
  - Split-job helpers: range planning and post-merge recipe/tip ID reassignment by source order.
- `cookimport/cli_worker.py`
  - Main single-file stage flow uses writer functions.
- `cookimport/cli.py`
  - Multi-job merge flow for split PDF/EPUB runs; writes merged outputs and merges per-job raw artifacts.
- `cookimport/labelstudio/ingest.py`
  - Reuses same writer flow for processed output snapshots used in LS workflows.

## Canonical naming conventions (user-facing)

From prior task docs, still valid in current CLI/docs:

- `RecipeSage` is an importer/source label, not the canonical intermediate format name.
- Intermediate outputs are described as `schema.org Recipe JSON`.
- Final outputs are described as `cookbook3`.
- `RecipeDraftV1` is an internal model identifier and can appear in code/tests, but user-facing text should prefer `cookbook3`.

## Output layout and file names (current behavior)

Per run, output root:

- `data/output/<timestamp>/`

Per workbook (slugified file stem):

- `intermediate drafts/<workbook_slug>/r{index}.jsonld`
- `final drafts/<workbook_slug>/r{index}.json`
- `tips/<workbook_slug>/t{index}.json`
- `tips/<workbook_slug>/tips.md`
- `tips/<workbook_slug>/topic_candidates.json` (if any)
- `tips/<workbook_slug>/topic_candidates.md` (if any)
- `chunks/<workbook_slug>/c{index}.json` (if any)
- `chunks/<workbook_slug>/chunks.md` (if any)
- `raw/<importer>/<source_hash>/<location_id>.<ext>` (if any)
- `<workbook_slug>.excel_import_report.json` at run root

Code refs:

- `cookimport/cli.py:1515`
- `cookimport/cli_worker.py:198`
- `cookimport/staging/writer.py:275`
- `cookimport/staging/writer.py:308`
- `cookimport/staging/writer.py:331`
- `cookimport/staging/writer.py:396`
- `cookimport/staging/writer.py:611`
- `cookimport/staging/writer.py:668`
- `cookimport/staging/writer.py:686`

## ID and provenance behavior in staging

### Recipe IDs

- Intermediate writer ensures candidate IDs exist (`@id`) before JSON-LD write.
- Fallback stable pattern when unresolved: `urn:recipeimport:excel:{file_hash}:{sheet_slug}:r{row_index}`.
- If `candidate.identifier` exists, it is used.

Code refs:

- `cookimport/staging/writer.py:209`
- `cookimport/staging/writer.py:275`

### Tip/topic IDs

- Tip fallback ID pattern: `urn:recipeimport:tip:{file_hash}:{sheet_slug}:t{row_index}:{tip_index}`.
- Topic fallback ID pattern: `urn:recipeimport:topic:{file_hash}:{sheet_slug}:tc{row_index}:{topic_index}`.

Code refs:

- `cookimport/staging/writer.py:227`
- `cookimport/staging/writer.py:247`

### Row index fallback rule (important for non-tabular sources)

Row index resolution checks provenance keys in this order:

1. `row_index` / `rowIndex` / `row`
2. `location.row_index` / `location.rowIndex` / `location.row`
3. `location.chunk_index` / `location.chunkIndex` / `location.chunk`

This fallback is what keeps stable-ish IDs for text/PDF/EPUB when row semantics do not exist.

Code ref:

- `cookimport/staging/writer.py:180`

## Draft-v1 (cookbook3) contract shaping

`recipe_candidate_to_draft_v1()` is where staging contract safety is enforced.

### Ingredient line normalization rules

Current enforced behavior:

- `section_header` lines are dropped from output lines.
- Allowed output `quantity_kind`: `exact`, `approximate`, `unquantified`.
- `exact`/`approximate` lines require positive `input_qty`; otherwise they are downgraded to `unquantified`.
- `unquantified` lines must have `input_qty = null` and `input_unit_id = null`.
- For unresolved units, `input_unit_id` is always set to `null` (raw unit text retained in `raw_unit_text`).
- For unresolved ingredients, `ingredient_id` must be non-empty string; fallback uses `raw_ingredient_text`, then `raw_text`, then sentinel `__missing_ingredient__`.

Code refs:

- `cookimport/staging/draft_v1.py:39`
- `cookimport/staging/draft_v1.py:79`
- `cookimport/staging/draft_v1.py:94`
- `cookimport/staging/draft_v1.py:108`

### Additional draft-v1 behaviors that affect downstream consumers

- Ingredient text fields are lowercased in final draft output:
  - `raw_text`, `raw_ingredient_text`, `raw_unit_text`, `preparation`, `note`
- Variant extraction removes instruction lines that are variation headers/prefixes and stores them under `recipe.variants`.
- If no instructions remain, fallback step is injected: `See original recipe for details.`
- Unassigned ingredients create prep step at beginning: `Gather and prepare ingredients.`
- Step time metadata from instruction parser is rolled up to `cook_time_seconds` when recipe cook time is missing.

Code refs:

- `cookimport/staging/draft_v1.py:15`
- `cookimport/staging/draft_v1.py:118`
- `cookimport/staging/draft_v1.py:129`
- `cookimport/staging/draft_v1.py:166`

## Split-job merge behavior (PDF/EPUB)

When PDFs/EPUBs are split into jobs, merge flow:

1. Collects all job results.
2. Sorts jobs by start range.
3. Reassigns recipe IDs in source order (`start_spine` first, then `start_page`, then `start_block`).
4. Updates tip references (`source_recipe_id`, provenance IDs) via remap.
5. Writes merged outputs through standard writer functions.
6. Moves raw artifacts from temporary `.job_parts/<workbook_slug>/job_{i}/raw/...` into final `raw/...` path.

Code refs:

- `cookimport/cli.py:1260`
- `cookimport/cli.py:1203`
- `cookimport/staging/pdf_jobs.py:38`
- `cookimport/staging/pdf_jobs.py:76`

## Chronology: what was documented/tried before (do not lose)

This section preserves the historical task notes that were previously split across files.

### Baseline staging section doc (non-timestamped, prior summary)

Contained initial map of:

- code locations,
- output surfaces,
- links to contract/naming notes.

Status now: superseded by this doc, but key map retained and expanded.

### 2026-02-12_10.25.47 format naming conventions

Decision captured:

- Use `schema.org Recipe JSON` for intermediate and `cookbook3` for final in docs/help text.
- Do not describe intermediate format as `RecipeSage`.
- `RecipeDraftV1` remains internal term.

Status now: still correct and reflected in current CLI help text (`cookimport/cli.py:322`, `cookimport/cli.py:1515`).

### 2026-02-12_10.41.48 staging contract alignment

Problem captured:

- Final draft output drifted from Cookbook staging import invariants.
- Failures occurred even after resolver normalization.

Key decisions/actions captured:

- Normalize ingredient lines in `draft_v1.py` post-parse/post-assignment.
- Do not generate random UUIDs for unresolved ingredient IDs.
- Preserve lowercasing and step-linking behavior.

Recorded evidence at that time:

- `pytest -q tests/test_draft_v1_lowercase.py tests/test_draft_v1_variants.py tests/test_ingredient_parser.py tests/test_draft_v1_staging_alignment.py`
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
  - `exact`/`approximate` require `input_qty > 0`
- `unquantified` must have null/omitted quantity+unit

Status now: these edge-case rules are still actively normalized in `draft_v1.py`.

### 2026-02-15_22.10.59 staging output contract flow map

Merged source:
- `docs/understandings/2026-02-15_22.10.59-staging-output-contract-flow.md`

Preserved outcomes:
- Single-file stage flow (`cli_worker`) and split-job merge flow (`cli.py`) both converge on the same writer functions for intermediate/final/tips/topic/chunks/report outputs.
- Split jobs add one extra step: move raw artifacts from `.job_parts/<workbook>/job_<index>/raw/...` into run `raw/...`.
- Cookbook safety normalization remains in `draft_v1.py` (ingredient line shaping), not in writer functions.
- Historical staging failures were primarily quantity-kind/qty invariant violations, not unresolved ID placeholder handling.

## Known bad patterns and anti-regression notes

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

## Current limitations / things we know are not great yet

1. Duplicate ingredient text can be undercounted in unassigned detection
- `recipe_candidate_to_draft_v1()` tracks assigned ingredients by `raw_ingredient_text` set membership.
- If duplicate lines share same text, one assignment can make another appear assigned.
- Code ref: `cookimport/staging/draft_v1.py:236`.

2. Lowercasing is lossy by design
- Improves normalization but may remove intentional capitalization in ingredient text fields.
- This is currently tested behavior, not an accidental bug.

3. Split-job raw artifact filename collisions are auto-prefixed
- Merge may rename colliding files with `job_{index}_...` prefixes.
- Good for loss avoidance, but file names can differ run-to-run when collisions happen.
- Code ref: `cookimport/cli.py:1230`.

4. Timestamp output folder granularity is seconds
- Two invocations in the same second could collide on output directory name.
- Current behavior uses `%Y-%m-%d_%H.%M.%S`.
- Code ref: `cookimport/cli.py:1538`.

## Test coverage tied to staging contracts

Core tests to keep green when touching staging:

- `tests/test_cli_output_structure.py`
- `tests/test_draft_v1_staging_alignment.py`
- `tests/test_draft_v1_lowercase.py`
- `tests/test_draft_v1_variants.py`
- `tests/test_tip_writer.py`
- `tests/test_source_field.py`
- `tests/test_pdf_job_merge.py`
- `tests/test_epub_job_merge.py`

## Practical “change checklist” for future work

When editing staging behavior, confirm:

1. Path layout and naming in CLI help/docs still match writes.
2. Draft ingredient-line invariants remain staging-safe.
3. Unresolved ID handling remains placeholder/null pattern.
4. Split-job merge still preserves deterministic order and tip references.
5. Tips/topic candidates/chunks/raw/report outputs still land in expected paths.
6. Output stats reporting remains attached to report (`outputStats`) when files are written.

## Related docs

- Ingestion details feeding staging: `docs/03-ingestion/03-ingestion_README.md`
- Parsing behavior feeding staging normalization: `docs/04-parsing/04-parsing_README.md`
- Metrics and report surfaces consuming staging outputs: `docs/08-analytics/08-analytics_README.md`
