---
summary: "Parsing architecture/build/fix-attempt log used to avoid repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on parsing behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need historical architecture versions, build attempts, and known failed paths before trying another change
---

# Parsing Log: Architecture, Builds, and Fix Attempts

Read this file when work starts looping across turns, or when someone says "we are going in circles on this."

This log is the anti-loop record for parsing: what changed, why, what worked, and what remains risky.

## Historical Timeline (What Changed, Why, Outcome)

### 2026-01-30 to 2026-01-31: step-linking duplication and split handling

Problem observed:

- Ingredients duplicated across multiple steps when only one assignment intended.

What was implemented:

- Two-phase global resolver.
- Earliest-use tiebreak among multiple use-verb steps.
- Strong split gating for true multi-step assignment.
- Split confidence penalty for review triage.

Outcome:

- Major duplicate reduction while preserving intentional split behavior.

Residual risk:

- Collective/fuzzy fallbacks can still create occasional false positives.

### 2026-02-10: lane taxonomy alignment

Problem observed:

- Freeform labeling no longer treated `NARRATIVE` as a user-facing lane.

What was implemented:

- Chunk lane routing changed toward `knowledge`/`noise`.
- Writer summary treats legacy `NARRATIVE` as noise.

Outcome:

- Better alignment between parsing outputs and benchmark/annotation taxonomy.

Residual risk:

- Historical artifacts may still contain `NARRATIVE`; reporting is compatible but mixed-lane legacy data can confuse manual comparisons.

### 2026-02-15: docs consolidation pass

What happened:

- Parsing docs were merged, then revalidated against code/tests.

Important note:

- Some prior docs described desired behavior that is now only partially true; the paired README reflects implemented behavior as of current code.

### 2026-02-15_22.07.14: Parsing flow and regression hotspot map

Preserved guidance:
- Parsing ownership is intentionally split across importer extraction, shared parsing modules, and draft-v1 shaping; regressions can first appear as staging/importer symptoms.
- Step-link assignment surprises most often come from post-resolution passes (`all ingredients`, section-group aliasing, collective-term fallback), not from the initial exact/semantic/fuzzy scorer.
- Chunk lanes are effectively binary (`knowledge` / `noise`) in current behavior, while legacy `NARRATIVE` compatibility remains for historical artifact/report interpretation.
- `tip_candidates` / `topic_candidates` are broader debugging/classification surfaces; exported standalone tips come from filtered `results.tips`.

### 2026-02-15_22.23.02: Unstructured runtime status check

Preserved verification snapshot:
- Dependency pin is `unstructured>=0.18.32,<0.19` (see `pyproject.toml`).
- EPUB extractor default resolution was verified end-to-end as `unstructured` (CLI defaults + importer fallback via `C3IMP_EPUB_EXTRACTOR`).
- E2E stage run produced expected unstructured-specific raw diagnostics (`unstructured_elements.jsonl`) and enriched block features.

Critical caveat preserved:
- Always store the Unstructured version in metadata as a plain string (for split import/benchmark pickle-safety). Use `_resolve_unstructured_version()` rather than serializing raw `__version__` objects.

### 2026-02-16: Unstructured EPUB tuning pass (BR splitting + explicit options)

What changed:

- Added explicit Unstructured HTML options through run settings/env:
  - `html_parser_version` (`v1|v2`)
  - `skip_headers_and_footers` (bool)
  - `preprocess_mode` (`none|br_split_v1|semantic_v1`)
- Added EPUB pre-normalization module `cookimport/parsing/epub_html_normalize.py`:
  - BR-separated lines in `p/div/li` are split into sibling block tags.
  - Normalization is deterministic and idempotent by test.
- Adapter improvements in `cookimport/parsing/unstructured_adapter.py`:
  - bold-detection heuristic from Unstructured emphasis metadata,
  - explicit list depth hint and category depth persistence,
  - defensive split of `ListItem` text containing newline-delimited items.

Important caveat:

- Unstructured HTML parser `v2` expects `body.Document`/`div.Page` style structure.
- Adapter now applies a compatibility shim for `v2` inputs by wrapping/marking body when needed before calling `partition_html`.

### 2026-02-27_19.50.31: parsing docs module/call-site coverage parity audit

Problem captured:
- `04-parsing_readme.md` had partial file-path coverage (core behavior was documented, but several active helper modules and cross-boundary call sites were implicit or missing).

Decision/outcome preserved:
- Expanded module inventory to include active helper modules that shape parsing behavior:
  - `cookimport/parsing/markitdown_adapter.py`
  - `cookimport/parsing/patterns.py`
  - `cookimport/parsing/spacy_support.py`
  - plus explicit top-level listing of `epub_html_normalize.py`, `unstructured_adapter.py`, `epub_postprocess.py`, `epub_health.py`.
- Expanded call-site inventory so parsing entrypoints are explicit in docs:
  - `cookimport/plugins/pdf.py`, `cookimport/plugins/text.py`, `cookimport/plugins/excel.py`
  - `cookimport/cli.py`, `cookimport/cli_worker.py`, `cookimport/labelstudio/ingest.py`
  - `cookimport/epubdebug/cli.py`, `cookimport/staging/jsonld.py`, `cookimport/core/scoring.py`
  - `cookimport/llm/codex_farm_knowledge_jobs.py`.
- Documented `cookimport/parsing/classifier.py` as parsing-adjacent/test-scoped (not default stage recipe-path runtime), so it is not mistaken for an active stage dependency.

Anti-loop note:
- When reconciling parsing docs coverage, compare:
  1) `cookimport/parsing/*.py` file inventory,
  2) repo-wide `from cookimport.parsing ...` import call sites,
  3) README module + call-site lists.
  This prevents repeated "docs look complete but missed helper module" loops.

## Things We Know Are Bad (Do Not Re-discover)

- Text-based ingredient identity can collide when identical ingredient strings appear multiple times intentionally.
- Collective-term fallback (`spices`, `herbs`, `seasonings`) is useful but can attach to wrong step in multi-component recipes.
- Instruction time summing is naive across overlapping/optional durations.
- Tip/chunk lane decisions are heuristic and unstable around narrative-advice hybrids.
- `ingredients.py` has duplicate function definition for `parse_ingredient_line` (early stub + final function).
- `chunks.md` output currently includes emoji lane markers; harmless but noisy for strictly ASCII consumers.

### 2026-02-19_14.22.11 - EPUB common issues quick wins

Problem captured:
- EPUB extraction quality regressed on common noise classes (soft hyphens, BR-collapsed lines, bullet prefixes, nav/pagebreak noise), causing downstream segmentation and parsing errors.

Behavior contract preserved:
- Add shared text normalization for Unicode/whitespace/fraction cleanup.
- Add shared EPUB postprocess pass reused by extractor paths.
- Suppress nav/TOC spine docs and obvious pagebreak noise.
- Compute and emit extraction health metrics and warning keys.
- Keep regression coverage for known quick-win bug classes.

Verification and evidence preserved:
- Recorded command set includes:
  - `pytest -q tests/parsing/test_cleaning_epub.py tests/ingestion/test_epub_extraction_quickwins.py tests/ingestion/test_epub_importer.py tests/cli/test_epub_debug_cli.py tests/cli/test_epub_debug_extract_cli.py`
  - `pytest -q tests/ingestion/test_unstructured_adapter.py tests/cli/test_cli_output_structure.py tests/ingestion/test_epub_job_merge.py`
- Recorded results:
  - targeted suite `33 passed`,
  - additional affected suites `34 passed`.

Key constraints and anti-loop notes:
- Shared cleanup intentionally limited to HTML-based extractor outputs; avoid forcing `markitdown` through this path without dedicated design.
- Spine metadata needed typed `item_id`/`properties` coverage so zip fallback and ebooklib paths apply consistent nav skipping.
- Debug extraction path must call shared postprocess for parity with importer behavior.

Rollback path preserved:
- Revert `cookimport/parsing/epub_postprocess.py` and `cookimport/parsing/epub_health.py` plus importer/debug wiring and associated tests.

### 2026-02-16 unstructured tuning implementation record

Problem captured:
- Unstructured HTML partitioning could collapse BR-based ingredient/instruction lines and hide critical structure.

Major decisions preserved:
- Normalize EPUB HTML before partitioning, then keep preprocessing mode configurable.
- Promote unstructured parser/preprocess options into explicit run settings and diagnostics metadata.
- Keep parser default at `v1`; parser `v2` stays opt-in behind compatibility wrapping.

Anti-loop note:
- Repeated downstream segmentation hacks are the wrong fix when upstream block boundaries are already degraded.

### 2026-02-19 EPUB quick-wins and health guardrails

Problem captured:
- Upstream text-shape noise (soft hyphen, nav/pagebreak noise, BR-collapsed lists) was cascading into parsing regressions.

Major decisions preserved:
- Centralize EPUB cleanup in shared postprocess and apply to HTML-based backends (`legacy`, `unstructured`, `markdown`), not `markitdown`.
- Emit extraction health as both report warning keys and raw JSON artifact.
- Type OPF spine records (`EpubSpineItem`) so nav-skipping behavior matches across ebooklib and zip fallback paths.

Serious failed-path summary:
- Debug extraction initially skipped shared postprocess, causing apparent importer-vs-debug drift; parity was restored by applying the same cleanup path.

## 2026-02-25 understanding merge batch (chunk consolidation + step-link section context)

### 2026-02-25_16.39.07 chunk consolidation absolute-range contract

Problem captured:
- Consolidation needed absolute adjacency checks for source ordering without breaking pass4's relative chunk index contract.

Decision/outcome preserved:
- Keep `KnowledgeChunk.block_ids` sequence-relative for pass4 job bundling.
- Introduce/use `provenance.absolute_block_range` for adjacency checks.
- Enforce table isolation: chunks with `provenance.table_ids` never merge in either `merge_small_chunks` or adjacent consolidation.

Anti-loop note:
- Converting `block_ids` to absolute indices is a regression path; use provenance absolute ranges instead.

### 2026-02-25_16.42.42 section-aware step-linking and duplicate identity safety

Problem captured:
- Repeated ingredient names and multi-section recipes could map ingredients to wrong steps under text-only identity and global fallback passes.

Decision/outcome preserved:
- Keep global candidate scoring, but bias near ties toward same-section steps when section context is available.
- Apply section scope in `all ingredients` and collective-term fallback passes when recipes have multiple sections.
- Track ingredient identity by original line index internally during assignment/sorting; remove internal index before staged return shape.

Anti-loop note:
- Do not downgrade assignment identity to text-only matching; it reintroduces duplicate-line collisions.

## 2026-02-25 archival merge batch (parsing)

### 2026-02-25_16.24.52 knowledge-table extraction rollout

Problem captured:
- Cookbook knowledge tables were flattening into prose-like blocks, making deterministic export and pass4 extraction unreliable.

Major decisions preserved:
- Treat table support as deterministic extraction/export first, optional LLM summarization second.
- Keep block text verbatim for evidence and attach table structure as hints (`table_hint`) instead of rewriting text.
- Annotate existing non-recipe block dicts (`features.table_id`, `features.table_row_index`) rather than introducing a new block model.
- Always write `tables/<workbook_slug>/tables.jsonl` and `tables.md` when `table_extraction=on`, even when empty.

Shipped outcomes:
- Added `cookimport/parsing/tables.py` with row detection/grouping/header inference.
- Wired table artifacts into stage, split-merge, and processed-output snapshot paths.
- Made chunking table-aware (table rows stay atomic for splitting; table chunks stay in `knowledge` lane).
- Added pass4 `table_hint` wiring in knowledge bundle construction.

Validation evidence preserved:
- Targeted tests passed for tables/chunks/pass4/CLI/run-settings wiring.
- Fixture stage runs wrote table artifacts but detected zero tables in tested EPUB/PDF fixtures.

Remaining gap preserved:
- Positive in-repo sample with detectable row separators still needed for one end-to-end non-empty table validation case.

Anti-loop note:
- Empty table outputs under `table_extraction=on` can be a source-text-shape limitation (missing row separators), not necessarily a regression in extraction logic.

### 2026-02-25_16.39.01 adjacent same-topic chunk consolidation

Problem captured:
- Adjacent knowledge chunks under one topic were fragmented, reducing chunk review quality and increasing pass4 work on near-duplicate neighbors.

Major decisions preserved:
- Consolidate adjacent chunks only (never reorder and never merge non-adjacent clusters).
- Require true book adjacency via absolute block indices to avoid merges across removed recipe spans.
- Use conservative topic matching (heading context first; tag-overlap fallback only when heading context missing).
- Keep rollback/debug switch: `COOKIMPORT_CONSOLIDATE_ADJACENT_KNOWLEDGE_CHUNKS=0`.
- Enforce strict table isolation across all merge phases.

Validation evidence preserved:
- Focused chunk tests: `29 passed`.
- Pass4 bundle compatibility test: `1 passed`.
- Broader suite snapshot had unrelated failures outside this scope (`toggle_editor` expectations and missing paprika/recipesage fixtures).

Anti-loop notes:
- Do not reinterpret `KnowledgeChunk.block_ids` as absolute source indices to solve adjacency issues; preserve sequence-relative IDs and use provenance ranges.
- Do not allow table chunks into generic merge paths; that regresses table auditability.

### 2026-02-25_16.45.50 multi-component recipe sections + section-aware linking

Problem captured:
- Multi-component recipe headers (`For the meat`, `For the gravy`, etc.) needed structural handling for better step linking and auditable outputs.

Major decisions preserved:
- Keep cookbook3 draft schema stable; expose section structure through additive artifacts and intermediate JSON-LD only.
- Emit intermediate `HowToSection/HowToStep` only when multiple instruction sections are detected.
- Use index-based internal ingredient identity during assignment to prevent duplicate text collisions.

Shipped outcomes:
- Added deterministic section extraction module and tests.
- Integrated section context into step-link scoring and fallback passes.
- Added section output artifacts (`sections/<workbook_slug>/...`) and richer intermediate JSON-LD section metadata.
- Verified with end-to-end fixture run on `tests/fixtures/sectioned_components_recipe.txt`.

Anti-loop note:
- If repeated ingredient names collapse to one step in multi-section recipes, check index-based identity flow before retuning alias scoring heuristics.

### 2026-02-27_19.46.23 parsing docs stale-content retirement

Problem captured:
- Parsing docs mixed active runtime context with removed feature/task archive material.

Durable decisions:
- Keep chronology tied to still-active parser/runtime behavior.
- Retire removed race-backend history and dead source-doc links.
- Keep test-path references aligned to current domain test layout (`tests/parsing`, `tests/ingestion`, `tests/staging`, `tests/core`).

### 2026-02-27_19.50.31 provenance note

Source understanding merged:
- `docs/understandings/2026-02-27_19.50.31-parsing-doc-module-callsite-coverage-audit.md`

Current status:
- Runtime helper-module and callsite coverage findings are retained in this log and reflected in `04-parsing_readme.md`.
