---
summary: "ExecPlan for adjacent same-topic knowledge chunk consolidation, including table-aware no-merge guardrails."
read_when:
  - "When changing knowledge chunk consolidation behavior in cookimport/parsing/chunks.py"
---

# Consolidate adjacent knowledge chunks by shared topic tags

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `docs/PLANS.md` (repository root). Follow the formatting and workflow rules in that document when implementing or revising this plan.

## Purpose / Big Picture

When processing a block-first cookbook source (EPUB/PDF/Markdown/text), the pipeline currently produces “knowledge chunks” (files under `data/output/<ts>/chunks/<workbook_slug>/`) by chunking `non_recipe_blocks` (or a topic-candidate fallback). In many books, chunk boundaries are sometimes “too eager”: the chunker splits content under the same conceptual topic (same section header / same taxonomy tags) into multiple adjacent chunks. This creates fragmentation in `chunks.md` and causes downstream “knowledge harvesting” (pass4 codex-farm) to do extra work on near-duplicate adjacent chunks.

After this change, adjacent **knowledge** chunks that refer to the same topic/idea (as indicated by shared heading context and/or shared taxonomy tags) will be consolidated into one chunk, as long as doing so is safe and does not cross real book boundaries. A human can see it working by staging an input and comparing `chunks.md` before vs after: the output should show fewer “knowledge” chunks, with merged text where the topic is clearly continuous.

## Progress

- [x] (2026-02-25 10:00-05:00) Drafted initial ExecPlan describing consolidation behavior, algorithm, integration points, and acceptance criteria.
- [x] (2026-02-25 16:24-05:00) Implemented consolidation pass in `cookimport/parsing/chunks.py` and threaded it into `process_blocks_to_chunks`.
- [x] (2026-02-25 16:30-05:00) Added focused unit tests covering safe merges, adjacency conventions, and “do not merge” boundaries (including table chunks).
- [x] (2026-02-25 16:33-05:00) Updated parsing/LLM docs and conventions to reflect the new pipeline step, kill switch, and table exclusion rules.
- [x] (2026-02-25 16:37-05:00) Ran focused and broader test suites; captured evidence snippets and current unrelated failing tests in `Artifacts and Notes`.

## Surprises & Discoveries

- Observation: `KnowledgeChunk.block_ids` are relative to the local non-recipe sequence, not absolute source indices.
  Evidence: `tests/llm/test_knowledge_job_bundles.py` relies on mapping `chunk.block_ids` back through sequence order; implementation now stores `provenance.absolute_block_range` using `features.source_block_index` for safe adjacency checks without breaking that contract.

- Observation: Existing `merge_small_chunks` could merge table chunks into neighboring prose chunks, which violates the table isolation requirement.
  Evidence: Added `test_merge_small_chunks_does_not_absorb_table_chunks` and enforced table guards in both small-chunk merge and adjacent-topic consolidation.

## Decision Log

- Decision: Only consolidate **adjacent** chunks (never reorder, never merge non-adjacent clusters).
  Rationale: Adjacent-only is deterministic, preserves book order, and matches the user goal (“consolidate adjacent knowledge blocks”).
  Date/Author: 2026-02-25 / GPT-5.2 Pro

- Decision: Require “book adjacency” using absolute block indices (do not merge across gaps where recipe blocks were removed).
  Rationale: `non_recipe_blocks` can be adjacent in the filtered list even if recipe content existed between them in `full_text`. A contiguity check prevents accidental merges across recipe boundaries.
  Date/Author: 2026-02-25 / GPT-5.2 Pro

- Decision: Use a conservative topic-similarity rule: prefer “same heading context” (section tag) and use tag overlap as a secondary signal.
  Rationale: Headings are the most stable and human-auditable “topic tag” in block-first books; taxonomy tags can be sparse or noisy. This reduces incorrect merges.
  Date/Author: 2026-02-25 / GPT-5.2 Pro

- Decision: Add a disable switch (debug/rollback) without requiring CLI/plumbing changes in the first iteration.
  Rationale: Chunk boundaries are regression-sensitive. A kill switch allows fast isolation if a book regresses, while keeping default behavior improved for most runs.
  Date/Author: 2026-02-25 / GPT-5.2 Pro

- Decision: Table chunks must never be merged with other chunks in any merge phase.
  Rationale: Table rows are structured facts; merging with prose reduces table auditability and risks blending unrelated context after the new table-extraction feature.
  Date/Author: 2026-02-25 / GPT-5 Codex

## Outcomes & Retrospective

- Implemented consolidation in `cookimport/parsing/chunks.py` with deterministic left-to-right merging, topic-key matching, absolute-range adjacency checks, and a kill switch env var.
- Added table-preservation guardrails in both `merge_small_chunks` and `consolidate_adjacent_knowledge_chunks` so table chunks stay isolated.
- Added focused regression tests in `tests/parsing/test_chunks.py` (29 passing) and validated a pass4-bundle compatibility test (`tests/llm/test_knowledge_job_bundles.py`).
- Broader `pytest` currently reports 7 failures outside this scope (toggle-editor expectation drift and missing paprika/recipesage fixture files). No failures were observed in chunking/knowledge-bundle tests touched by this work.

## Context and Orientation

This repository is a deterministic recipe-import pipeline (`cookimport`) that processes inputs (PDF/EPUB/text/etc.) into:

- recipe drafts (intermediate JSON-LD + final cookbook3 JSON),
- tips/topic candidates,
- and **knowledge chunks** (non-recipe text chunks) written under `data/output/<timestamp>/chunks/<workbook_slug>/`.

Key definitions (plain English):

- **Block**: one extracted piece of text (a paragraph, heading, list line, or table row) plus metadata about where it came from in the source. EPUB/PDF importers emit an ordered list of blocks (`full_text`).
- **non_recipe_blocks**: blocks that are not part of any detected recipe. These are used as the primary source for knowledge chunking.
- **Knowledge chunk**: an output record produced by `cookimport/parsing/chunks.py` that groups adjacent blocks into a larger “knowledge unit”. The chunker assigns each chunk a **lane**:
  - `knowledge` (intended to be reusable cooking knowledge),
  - `noise` (index pages, acknowledgments, etc; or low-value narrative).
- **Topic tag / idea tag**: in this plan, “topic” is inferred from:
  1) the chunk’s current heading context (the most recent heading(s) governing those blocks), and
  2) any taxonomy tags/merged tags already produced by highlight extraction.
- **Adjacent**: consecutive chunks in the chunk list *and* contiguous in the original book’s absolute block indices (no gap).

Where the relevant code lives:

- Knowledge chunking pipeline: `cookimport/parsing/chunks.py`
  - `process_blocks_to_chunks` currently runs:
    1. `chunk_non_recipe_blocks`
    2. `merge_small_chunks`
    3. `assign_lanes`
    4. `extract_highlights`
    5. `consolidate_adjacent_knowledge_chunks` (unless disabled via env var)
- Chunk creation call sites:
  - `cookimport/cli_worker.py` (`stage_one_file`) builds chunks from `non_recipe_blocks` (or topic fallback).
  - `cookimport/cli.py` (`_merge_split_jobs`) rebuilds chunks once after merging split jobs.
- Output writers:
  - `cookimport/staging/writer.py` writes chunk JSON files and `chunks.md`.

Why this change matters:

- Fragmented adjacent chunks under the same topic make `chunks.md` harder to review.
- Optional pass4 knowledge harvesting (`docs/10-llm/knowledge_harvest.md`) uses these chunks as inputs; fragmentation increases job count and reduces per-chunk context.

## Plan of Work

### Milestone 1: Add a consolidation pass to knowledge chunking

At the end of knowledge chunking, add a new step that merges adjacent *knowledge* chunks when:
1) they are truly adjacent in the book (contiguous absolute block indices), and
2) they represent the same topic (same heading context and/or strong tag overlap), and
3) the merged chunk stays within a safe size bound, and
4) neither side is table-derived (`provenance.table_ids` present).

This milestone should be self-contained: after it lands, running the existing chunking tests should pass, and a small crafted input should show reduced chunk count when appropriate.

Implementation details (concrete and prescriptive):

1) In `cookimport/parsing/chunks.py`, identify the chunk model/type used by this module (likely a dataclass or Pydantic model).
   - Find where chunk objects store:
     - lane (`knowledge` vs `noise`)
     - text content (often `text` or `content`)
     - block provenance indices (absolute start/end or per-block indices)
     - heading context (if present)
     - tags (if present), or highlights from which tags can be derived

2) Implement a new helper function (names are suggestions; keep naming consistent with the module):

   - `consolidate_adjacent_knowledge_chunks(chunks: list[Chunk], *, max_merged_chars: int, require_contiguous_blocks: bool) -> list[Chunk]`

   It should:
   - scan left-to-right, greedily merging runs of mergeable adjacent chunks;
   - preserve deterministic ordering;
   - never merge `noise` lane chunks into `knowledge` (and never merge knowledge into noise);
   - update merged chunk provenance so consumers still see correct block ranges.

3) Define mergeability in a dedicated helper:

   - `should_merge_adjacent_chunks(a: Chunk, b: Chunk, *, max_merged_chars: int) -> bool`

   with rules:

   A) Lane rule:
   - Only consider merging if `a.lane == knowledge` and `b.lane == knowledge`.

   B) “Book adjacency” rule:
   - Only merge if the absolute block index ranges are contiguous.
   - Implement a helper to compute `abs_start, abs_end` for a chunk:
     - Prefer explicit chunk-level fields if they exist (e.g., `block_start_index`, `block_end_index`).
     - Otherwise compute from per-block provenance (e.g., `chunk.blocks[*].block_index`).
   - Then require contiguity:
     - If indices are inclusive end: `a_end + 1 == b_start`
     - If indices are exclusive end: `a_end == b_start`
   - The implementation MUST include a unit test that would fail if you got the inclusive/exclusive convention wrong.

   C) Topic similarity rule (conservative):
   - Compute a `topic_key` for each chunk:
     1. If the chunk stores a heading context field (examples: `heading`, `heading_path`, `section_header`), normalize it (lowercase, strip punctuation/whitespace) and use that as the topic key.
     2. Else, if the chunk stores tags (examples: `tags`, `merged_tags`), use a stable representation:
        - `tuple(sorted(tags))` if tags are a set-like list, or
        - a “primary tag” if tags are weighted/counted (prefer the most common).
     3. Else, use `None`.

   - Merge when:
     - `topic_key(a) is not None` AND `topic_key(a) == topic_key(b)`.

   - Optional secondary merge (only when heading context is absent on both chunks):
     - If both have non-empty tag sets, compute Jaccard similarity:
       `|A ∩ B| / |A ∪ B|`
     - Merge if similarity >= `0.7`.
     - Keep this threshold conservative; the goal is “obviously same topic”.

   D) Size rule:
   - Only merge if `len(a.text) + len(b.text) + separator_overhead <= max_merged_chars`.
   - Default `max_merged_chars` should be tied to existing chunking max-char behavior if present (do not invent a new unrelated limit). If this module already has `MAX_CHUNK_CHARS` or similar, reuse it.
   - If the module has no such constant, introduce one with a conservative default and document why.

4) How to build the merged chunk object:

   - Text:
     - `merged_text = a.text.rstrip() + "\n\n" + b.text.lstrip()`
     - Keep a blank line separator to preserve readability and avoid gluing sentences.

   - Provenance / block ids:
     - Merge underlying block references in order: `a.blocks + b.blocks` (or equivalent).
     - Update any chunk-level start/end indices accordingly.
     - If the chunk model stores both relative and absolute indices, ensure both remain internally consistent.

   - Heading context:
     - If headings match, keep that heading context.
     - If you merged using tag overlap without headings, preserve `a`’s heading context if present, but add a debug note (see below) so it’s auditable.

   - Highlights / tags:
     - Prefer not to re-run expensive highlight extraction if it would double compute cost for big books.
     - Instead:
       - If chunk already has highlight objects, concatenate and deduplicate by a stable key (prefer an explicit id; else use normalized highlight text).
       - Recompute any derived fields (`merged_tags`, `tip_density`) using the same internal helper that `extract_highlights` uses, if available.
     - If the module structure makes this hard, accept a first iteration that simply unions tags and concatenates highlights, and then follow up with a second milestone to recompute precisely. This plan prefers correctness but not at the cost of a risky refactor.

5) Integrate the new step into the pipeline:

   In `cookimport/parsing/chunks.py`, in `process_blocks_to_chunks`, insert:

   - after `extract_highlights`, call `consolidate_adjacent_knowledge_chunks(...)` and return the consolidated list.

   Do not change call sites in `cli_worker.py` or merge flows unless required; they should get the new behavior automatically through `process_blocks_to_chunks`.

6) Add a kill switch (debug/rollback):

   - Add an environment variable read in `cookimport/parsing/chunks.py`, for example:
     - `COOKIMPORT_CONSOLIDATE_ADJACENT_KNOWLEDGE_CHUNKS` (default truthy)
   - If the env var is set to `0` / `false`, skip consolidation and return the pre-merge chunk list.

   Document this env var in `docs/04-parsing/04-parsing_readme.md`.

### Milestone 2: Tests that prove consolidation is correct and safe

Add unit tests that cover:

- merges two adjacent knowledge chunks with the same heading context;
- does not merge if block indices are not contiguous (gap exists);
- does not merge across lane boundaries (knowledge vs noise);
- does not merge if combined size exceeds `max_merged_chars`;
- merges a chain of 3+ adjacent chunks into one when all are mergeable, preserving order;
- inclusive vs exclusive end-index convention is correct (explicit test).

Tests should be placed alongside existing chunking tests, typically `tests/parsing/test_chunks.py`.

### Milestone 3: Docs update

Update `docs/04-parsing/04-parsing_readme.md`:

- In the “Knowledge Chunking” pipeline list, add the new step:
  - `consolidate_adjacent_knowledge_chunks` (after highlights)
- Briefly describe:
  - what counts as adjacent,
  - what “same topic” means,
  - how to disable with the env var for debugging.

Optionally update `docs/10-llm/knowledge_harvest.md` with a one-paragraph note that pass4 inputs come from these consolidated knowledge chunks, so job counts may change.

## Concrete Steps

All commands are from the repository root.

1) Read and orient:

    sed -n '1,220p' docs/04-parsing/04-parsing_readme.md
    sed -n '1,220p' docs/10-llm/knowledge_harvest.md
    rg -n "def process_blocks_to_chunks|chunk_non_recipe_blocks|merge_small_chunks|assign_lanes|extract_highlights" cookimport/parsing/chunks.py

2) Implement consolidation in `cookimport/parsing/chunks.py`:

    rg -n "class .*Chunk|ChunkLane|lane" cookimport/parsing/chunks.py

   Add the new functions near existing merge helpers (next to `merge_small_chunks` is usually the right neighborhood).

3) Add tests:

    rg -n "test_chunks|process_blocks_to_chunks" tests/parsing/test_chunks.py

   Add new tests in the same file (or `tests/parsing/test_chunks.py` if that’s how the repo is structured).

4) Run focused tests:

    source .venv/bin/activate
    pytest tests/parsing/test_chunks.py

   Expected: all tests pass. Your new tests should fail if you temporarily comment out the consolidation call, then pass when enabled.

5) Optional manual spot-check (only if you can produce a visible before/after locally):

   Create a tiny Markdown input intended to produce adjacent chunks under one heading (the exact content may need tuning based on current chunking thresholds).

    mkdir -p data/input
    cat > data/input/adjacent_knowledge_demo.md <<'EOF'
    # Knife Skills

    Keep your knife sharp. A sharp knife is safer and more precise.
    Keep the cutting board stable with a damp towel underneath.

    - Use a claw grip to protect your fingertips.
    - Let the knife do the work; do not force it through the food.
    - Reset your grip often.

    After chopping, scrape food with the spine of the knife, not the edge.
    EOF

   Then stage it:

    cookimport stage data/input/adjacent_knowledge_demo.md

   Inspect the newest run folder:

    ls -1 data/output | tail -n 3
    # pick the latest <ts> folder
    sed -n '1,200p' data/output/<ts>/chunks/adjacent_knowledge_demo/chunks.md

   Acceptance signal: if the chunker previously produced separate adjacent chunks for the prose vs list sections under the same heading, you should now see them merged into one chunk.

## Validation and Acceptance

This change is accepted when:

1) Automated tests:
- Running:

    source .venv/bin/activate
    pytest tests/parsing/test_chunks.py

  passes, and includes at least one new test demonstrating:
  - two chunks that were separate before are now merged when they share the same topic key and are contiguous.

2) Behavior verification (human-observable):
- Staging at least one input that previously produced fragmented adjacent knowledge chunks results in:
  - fewer `c*.json` files under `data/output/<ts>/chunks/<workbook_slug>/`, and
  - a `chunks.md` that shows the merged text content.

3) Safety properties:
- There is at least one test proving “no merge across a gap in absolute block indices”.
- There is at least one test proving “no merge across knowledge/noise boundary”.
- There is at least one test proving table chunks do not merge with non-table chunks.
- There is a documented kill switch env var that disables consolidation.

## Idempotence and Recovery

- The consolidation pass must be deterministic: given identical extracted blocks, it produces the same chunk list every run.
- The kill switch env var allows quickly bisecting regressions:
  - Set `COOKIMPORT_CONSOLIDATE_ADJACENT_KNOWLEDGE_CHUNKS=0` and rerun to confirm whether a behavior change is due to consolidation.
- No destructive operations are required. Rerunning `cookimport stage` is safe; it creates a new timestamped run directory.

## Artifacts and Notes

- Focused chunking tests:

    source .venv/bin/activate
    pytest tests/parsing/test_chunks.py
    29 passed, 2 warnings in 2.02s

- Related pass4 bundle test (guards relative `block_ids` contract):

    source .venv/bin/activate
    pytest tests/llm/test_knowledge_job_bundles.py
    1 passed, 2 warnings in 1.33s

- Broader suite snapshot (current workspace baseline includes unrelated failures):

    source .venv/bin/activate
    pytest
    7 failed, 608 passed, 19 warnings in 33.67s
    failing tests:
      tests/cli/test_toggle_editor.py::{test_enum_rows_show_all_options_with_selected_boxed,test_selected_row_uses_highlight_style_on_selected_option}
      tests/ingestion/test_paprika_importer.py::{test_inspect_paprika,test_convert_paprika_file}
      tests/ingestion/test_recipesage_importer.py::{test_detect_recipesage,test_inspect_recipesage,test_convert_recipesage}

## Interfaces and Dependencies

### New/changed interfaces (in-repo)

In `cookimport/parsing/chunks.py`, define:

- `def consolidate_adjacent_knowledge_chunks(chunks: list[Chunk], *, max_merged_chars: int, require_contiguous_blocks: bool = True) -> list[Chunk]:`
  - Merges adjacent knowledge-lane chunks that share topic signals and are contiguous in absolute block indices.

- `def should_merge_adjacent_chunks(a: Chunk, b: Chunk, *, max_merged_chars: int, require_contiguous_blocks: bool = True) -> bool:`
  - Encapsulates merge rules to keep the algorithm testable.

- `def topic_key(chunk: Chunk) -> str | tuple | None:`
  - Stable topic signature derived from heading context and/or tags.

- `def chunk_abs_range(chunk: Chunk) -> tuple[int, int] | None:`
  - Returns (abs_start, abs_end) in the book’s absolute block index space.
  - Document whether end is inclusive or exclusive.

### Configuration knobs (minimal)

- Environment variable:
  - `COOKIMPORT_CONSOLIDATE_ADJACENT_KNOWLEDGE_CHUNKS`
    - default: enabled
    - set to `0` / `false` to disable consolidation

Avoid introducing new third-party dependencies. Use only standard library modules (`os`, `re`, `dataclasses`, `collections`) and existing repo utilities.

---

Plan change notes (append-only):

- (2026-02-25) Initial plan drafted. No implementation work has been performed yet.
- (2026-02-25) Implemented plan in `cookimport/parsing/chunks.py` with tests/docs updates; added explicit table no-merge rule and absolute-range adjacency provenance to align with new table-extraction behavior.
