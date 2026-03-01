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

## 2026-02-28 migrated understanding ledger

Chronological migration from `docs/understandings`; source files were removed after this merge.

### 2026-02-27_22.24.26 priority4 current state audit

Source: `docs/understandings/2026-02-27_22.24.26-priority4-current-state-audit.md`
Summary: Priority-4 current-state audit: ingredient parser remains legacy and options are not wired yet.

Details preserved:


# Priority-4 Current-State Audit

Audit date: 2026-02-28 (local run time).

Findings:

- `cookimport/parsing/ingredients.py` is still legacy-first and still defaults missing units to `medium`.
- `tests/parsing/test_ingredient_parser.py` still asserts `medium` fallback behavior.
- No Priority-4 run-settings knobs are present in `cookimport/config/run_settings.py`, CLI, or interactive run-settings flows.
- Priority-4 optional deps (`ftfy`, `quantulum3`, `pint`) are not present in `pyproject.toml` (only `ingredient-parser-nlp` is present for this area).
- `docs/04-parsing/04-parsing_readme.md` still documents the `medium` default and also notes duplicate `parse_ingredient_line` definitions in parser module.

Implication:

Priority-4 should still be treated as largely unimplemented; plan status should remain mostly pending with baseline behavior explicitly documented.

### 2026-02-27_22.24.37 priority6 current time temp yield state

Source: `docs/understandings/2026-02-27_22.24.37-priority6-current-time-temp-yield-state.md`
Summary: Priority-6 discovery: parser/staging are still baseline-only, with fragmented yield extraction and no Priority 6 run-setting surface.

Details preserved:


# Priority-6 Current Time/Temp/Yield State

Current Priority 6 status in code is mostly pre-implementation.

- `cookimport/parsing/instruction_parser.py` is single-backend regex only, with fixed behavior: it sums all extracted durations and returns only the first temperature match.
- `cookimport/staging/draft_v1.py` uses parser metadata per step (`time_seconds`, `temperature`, `temperature_unit`) and rolls summed step times into `recipe.cook_time_seconds` when `candidate.cook_time` is missing.
- `draft_v1` yield fields are currently baseline placeholders: `yield_units=1`, `yield_phrase=candidate.recipe_yield`, `yield_unit_name=None`, `yield_detail=None`.
- There is no staged recipe-level `max_oven_temp_f` field yet.
- Yield extraction/parsing is importer-local (`text`, `epub`, `pdf`, and structured-source passthrough) rather than centralized/scored.
- `RunSettings` has no Priority 6 (`p6_*`) knobs yet, and `pyproject.toml` has no `priority6`/`htmlschema` extras.
- Existing test coverage is strong for current parser behavior (`tests/parsing/test_instruction_parser.py`) but there is no dedicated Priority 6 staging/yield test suite yet.

Useful cross-check: tagging currently computes a derived max Fahrenheit temperature from staged steps (`cookimport/tagging/signals.py`), but that value is not written into draft recipe fields.

### 2026-02-27_22.27.26 priority5 current step segmentation status

Source: `docs/understandings/2026-02-27_22.27.26-priority5-current-step-segmentation-status.md`
Summary: Priority-5 discovery: instruction fallback segmentation is not implemented yet, and staging/bench wiring points that must change are now mapped.

Details preserved:


# Priority-5 Current State Discovery

Date: 2026-02-27_22.27.26

## What is true in code now

- There is no instruction fallback segmentation module yet (`rg` found no `instruction_step_segmentation` or `step_segmentation` runtime implementation).
- `cookimport/staging/draft_v1.py` currently uses raw instruction boundaries, then does variant extraction and section-header removal before `parse_instruction(...)`.
- `cookimport/staging/jsonld.py` currently uses raw instruction boundaries, then groups into `HowToSection` only if section headers are detected.
- `cookimport/staging/writer.py::write_section_outputs(...)` also reads raw `candidate.instructions`, so it will drift if fallback segmentation is added only in draft/jsonld.

## Wiring points that must be touched for a real implementation

- Run settings model and summary/hash: `cookimport/config/run_settings.py`
- Stage and benchmark run-settings adapters: `cookimport/config/run_settings_adapters.py`
- CLI options and pass-through:
  - `cookimport/cli.py::stage(...)`
  - `cookimport/cli.py::labelstudio_benchmark(...)`
  - `cookimport/labelstudio/ingest.py::generate_pred_run_artifacts(...)`
  - `cookimport/bench/pred_run.py::build_pred_run_for_source(...)`
- Bench knob registry: `cookimport/bench/knobs.py`
- Writer/call-site pass-through: `cookimport/staging/writer.py`, `cookimport/cli_worker.py`, `cookimport/cli.py` split-merge path, and `cookimport/labelstudio/ingest.py` processed output writer path.

### 2026-02-27_22.37.08 priority6 rebuild validation audit

Source: `docs/understandings/2026-02-27_22.37.08-priority6-rebuild-validation-audit.md`
Summary: Priority-6 revalidation audit: parser/staging/yield/run-settings contracts remain baseline-only and justify the active ExecPlan scope.

Details preserved:


# Priority-6 Rebuild Validation Audit

Revalidated Priority 6 surfaces on 2026-02-27 before rebuilding the active ExecPlan.

- `cookimport/parsing/instruction_parser.py` is still the legacy regex parser: sum-all time strategy only, first temperature only, no backend/options surface.
- `cookimport/staging/draft_v1.py` still hardcodes yield placeholders (`yield_units=1`, passthrough `yield_phrase`, null unit/detail) and does not emit recipe-level `max_oven_temp_f`.
- Yield extraction remains importer-local (`plugins/text.py`, `plugins/epub.py`, `plugins/pdf.py`) with no centralized scored yield parser.
- `cookimport/config/run_settings.py` has no Priority-6 knobs (`p6_*`), so parser/yield/time strategy selection is not yet benchmark-configurable.
- Existing tests still validate the baseline parser and importer behavior; no dedicated Priority-6 staging/yield test module exists yet.

This confirms Priority 6 is still primarily a planning/implementation gap, not a landed runtime feature.

### 2026-02-27_22.38.32 priority5 wiring refresh audit

Source: `docs/understandings/2026-02-27_22.38.32-priority5-wiring-refresh-audit.md`
Summary: Priority-5 refresh audit: instruction fallback segmentation is still unimplemented, and the exact stage/run-settings/bench wiring points remain mapped.

Details preserved:


# Priority-5 Wiring Refresh Audit

Date: 2026-02-27_22.38.32

## What remains true

- No runtime instruction-step fallback segmentation module exists yet (`rg` still finds no `instruction_step_segmentation`/`step_segmentation` implementation under `cookimport/` and `tests/`).
- Draft, JSON-LD, and section artifacts still derive instruction boundaries from raw importer lines plus section-header extraction, so they will drift unless Priority-5 integration is applied to all three surfaces together.
- `RunSettings`, CLI `stage`, CLI `labelstudio-benchmark`, and run-settings adapters still have no instruction-step segmentation fields/options.
- Bench sweep knobs are still minimal (`segment_blocks`, `segment_overlap`, `workers`, `epub_extractor`), so Priority-5 knobs will be additive and must be validated explicitly.

## Why this matters

Priority 5 is still a clean additive feature. The safest implementation path is to introduce one deterministic segmentation helper, wire it through canonical run settings, and apply identical effective instruction shaping in `draft_v1`, `jsonld`, and `write_section_outputs` before benchmarking/tuning surfaces are expanded.

### 2026-02-27_22.41.18 priority2 shared backend header preservation and test double signature

Source: `docs/understandings/2026-02-27_22.41.18-priority2-shared-backend-header-preservation-and-test-double-signature.md`
Summary: Priority-2 implementation discovery: shared section backend must preserve standalone component headers, and ingest tests should accept additive importer kwargs.

Details preserved:


# Priority-2 Shared Backend Header Preservation And Test-Double Signature

Two implementation details were easy to miss:

- In shared EPUB/PDF extraction, applying wrapped-line merge after preserving `For the X` component headers can collapse the header into the next instruction line. Shared paths should keep component headers as standalone lines so section detection and section key mapping stay stable.
- `generate_pred_run_artifacts(...)` now passes `run_settings` to `importer.convert(...)`. Label Studio ingest tests that use fake importer doubles should accept `**_kwargs` to avoid brittle failures when converter kwargs expand.

Practical verification used during implementation:

- `tests/ingestion/test_epub_importer.py::test_extract_fields_shared_backend_preserves_for_the_component_headers`
- `tests/ingestion/test_pdf_importer.py::test_extract_fields_shared_backend_preserves_for_the_component_headers`
- `tests/labelstudio/test_labelstudio_ingest_parallel.py`

### 2026-02-27_23.05.12 priority6 latest tree gap revalidation

Source: `docs/understandings/2026-02-27_23.05.12-priority6-latest-tree-gap-revalidation.md`
Summary: Priority 6 latest-tree revalidation: parser, staging, and run settings still expose baseline behavior only.

Details preserved:


# Priority 6 Latest-Tree Gap Revalidation

Revalidation on 2026-02-27 found Priority 6 still in planning status.

- `cookimport/parsing/instruction_parser.py` remains baseline-only: regex extraction, sum-all time totals, first-temperature only, no options surface.
- `cookimport/staging/draft_v1.py` still hardcodes baseline yield outputs (`yield_units=1`, passthrough `yield_phrase`, null unit/detail) and does not emit recipe-level `max_oven_temp_f`.
- `cookimport/config/run_settings.py` has no Priority 6 selector fields, so parser/yield strategy selection is not yet wired through stage/benchmark configs.
- Repository search under `cookimport/` and `tests/` shows no `p6_*`, `yield_mode`, `time_total_strategy`, `InstructionParseOptions`, or `temperature_items` symbols.

Conclusion: `docs/plans/priority-6.md` remains valid as an unimplemented ExecPlan and should continue to be executed milestone-by-milestone.

### 2026-02-27_23.22.41 priority6 runtime wiring map

Source: `docs/understandings/2026-02-27_23.22.41-priority6-runtime-wiring-map.md`
Summary: Priority 6 wiring map: run settings flow into stage/pred-run via run_config, then draft_v1 consumes parser/yield options from that shared payload.

Details preserved:


# Priority 6 Runtime Wiring Map

Priority-6 parser/yield behavior should be wired through `RunSettings` and carried as `run_config` so both stage and benchmark prediction generation stay in parity.

- Stage path: `cookimport/cli.py` builds `RunSettings` via `build_run_settings(...)`, converts to `run_config`, then worker paths pass that payload into writer calls (`write_draft_outputs(..., ingredient_parser_options=run_config, instruction_step_options=run_config)`).
- Prediction-generation path: `cookimport/labelstudio/ingest.py::generate_pred_run_artifacts(...)` mirrors stage, builds `RunSettings`, derives `run_config`, then writes processed outputs through the same writer options.
- Interactive and speed/benchmark adapters already use `cookimport/config/run_settings_adapters.py` as the central mapping layer from `RunSettings` to CLI call kwargs.
- Current baseline parser/staging contracts remain legacy defaults (`parse_instruction` sum-all + first-temperature; draft yield placeholders), so Priority 6 can be added as new `p6_*` settings without changing default behavior.

### 2026-02-27_23.39.38 priority6 wiring and oven-like audit

Source: `docs/understandings/2026-02-27_23.39.38-priority6-wiring-and-ovenlike-audit.md`
Summary: Priority 6 wiring audit identified selector-forwarding gaps in benchmark manifests/ingest/pred-run paths and documented the oven-like local negative-hint fix.

Details preserved:


# Priority 6 Wiring and Oven-Like Audit

## What was checked

- `cookimport/cli.py` benchmark prediction/eval wiring (`labelstudio_benchmark`)
- `cookimport/labelstudio/ingest.py` signatures + `build_run_settings(...)` calls
- `cookimport/bench/pred_run.py` config forwarding into `generate_pred_run_artifacts(...)`
- `cookimport/parsing/instruction_parser.py` oven-like classification behavior

## Findings

- Benchmark runtime execution already forwarded `p6_*` selectors into prediction generation, but benchmark manifest dictionaries (`predict_only_run_config`, `benchmark_run_config`) initially omitted them.
- `labelstudio_benchmark` passed `p6_*` kwargs into `run_labelstudio_import(...)`, but ingest signatures had not yet been extended, causing a latent runtime mismatch on upload-enabled paths.
- `bench/pred_run.py` forwarded only a subset of parsing knobs and initially dropped `p6_*` selectors from helper-driven offline prediction runs.
- Oven-like classification used a broad negative-hint window; distant `internal` text could suppress nearby preheat/bake temperatures, making `max_oven_temp_f` unexpectedly null.

## Resolution pattern

- Add `p6_*` parameters and forwarding in ingest + bench helper signatures.
- Include `p6_*` selectors in benchmark run-manifest run-config payloads for reproducibility.
- Keep oven-like positive context broad, but evaluate negative hints in a tighter local window around the matched temperature.

## 2026-02-27 tasks consolidation ledger (migrated from `docs/tasks`)

The following task files were merged into this section and then removed from `docs/tasks`:
- `priority-4.md` (mtime `2026-02-27 22:44:14`)
- `priority-5.md` (mtime `2026-02-27 23:21:48`)
- `priority-6.md` (mtime `2026-02-27 23:40:38`)

### 2026-02-27_22.44.14: Priority 4 ingredient parser hardening and medium-default removal

Problems captured:
- Hidden missing-unit default (`medium`) created semantic drift.
- Parser rollout needed to preserve deterministic baseline while enabling stricter policy modes.
- One-word section headers (for example `Garnish`) regressed when parser-name output was empty.

Durable decisions:
- Keep `ingredient-parser-nlp` baseline and layer selectable options on top.
- Make missing-unit behavior explicit and selectable: `null`, `each`, `legacy_medium`.
- Flip default to `ingredient_missing_unit_policy=null` only after wiring/tests/docs alignment.
- Keep optional backends/normalizers soft-failable when optional deps are absent.

Outcome preserved:
- Priority 4 implementation is complete with explicit unit policy defaults and reproducible legacy mode.
- Packaging hoist (`regex_v1`) keeps container-unit semantics and records package details in notes.
- Run-config parser options are threaded through stage + benchmark prediction-generation surfaces.

Anti-loop notes:
- If section headers disappear after parser changes, inspect `_is_section_header_heuristic(...)` before retuning full parse logic.
- If stage and benchmark parse outputs differ, verify writer callsites receive `ingredient_parser_options=run_config`.

### 2026-02-27_23.21.48: Priority 5 fallback instruction step segmentation

Problems captured:
- Raw importer instruction blobs produced cross-artifact step-boundary drift.
- Initial auto fallback thresholds were too conservative and missed medium-length multi-sentence lines.
- Tiny-fragment merge logic initially attached numbered step markers (`2.`, `3.`) to prior sentences.

Durable decisions:
- Implement as staging safety net (not importer-specific extraction rewrite).
- Keep deterministic policy surface: `off|auto|always`; required backend `heuristic_v1`, optional backend `pysbd_v1`.
- Apply one instruction-shaping flow to draft-v1, intermediate JSON-LD, and section outputs.
- Keep run-settings/adapter wiring canonical to avoid stage-vs-benchmark drift.

Outcome preserved:
- Priority 5 is completed and wired across run settings, CLI, pred-run, and bench knob surfaces.
- JSON-LD compatibility is preserved in no-segmentation paths while segmented runs emit segmented step strings.

Anti-loop notes:
- Diagnose fallback-trigger thresholds and numbered-fragment handling before changing sentence regex primitives.
- If only one output surface drifts (draft vs JSON-LD vs sections), investigate shared writer-level shaping path first.

### 2026-02-27_23.40.38: Priority 6 time/temperature/yield upgrade lane

Problems captured:
- Active/archived Priority 6 plans were stale and referenced missing source docs.
- Run-manifest payloads initially dropped `p6_*` selector evidence.
- CLI started passing `p6_*` into ingest calls before ingest signatures accepted those kwargs.
- Oven-like negative hints initially suppressed valid bake/preheat temperatures.

Durable decisions:
- Rebuild plan from current code and keep it synchronized as a living contract.
- Land deterministic regex-first upgrades before optional dependency backends.
- Centralize yield extraction/parsing in parsing/staging instead of importer-local primary extraction.
- Preserve compatibility temperature fields while adding richer `temperature_items`.
- Keep Priority 6 debug payloads as opt-in sidecar artifacts, not embedded in final draft JSON.

Outcome preserved:
- Priority 6 is implemented with legacy-safe defaults and full selector wiring across stage/benchmark/prediction-generation.
- Parser exposes richer time/temperature metadata; staging now emits `max_oven_temp_f` when derivable and centralized yield fields.
- Optional dependency extras were formalized (`priority6`, plus requested alias coverage) with actionable fail-fast guidance when missing.

Open gap captured:
- Validation in this task was focused on Priority 6 surfaces; full suite execution was not part of this pass.

Anti-loop notes:
- If P6 knobs appear set but benchmark/stage manifests lack them, inspect CLI->ingest run-config threading first.
- If oven-like max temperature unexpectedly drops to null, inspect local negative-hint scope before changing global temperature extraction.

## 2026-02-28 docs/tasks consolidation batch (pattern flags + scoring penalties)

### 2026-02-28_12.19.18 deterministic pattern detector rollout and penalty guardrails

Source task file:
- `docs/tasks/2026-02-28_12.19.18-deterministic-pattern-detector-and-codex-hints.md`

Problem captured:
- Pattern suppression logic for TOC noise and duplicate recipe-intro structures needed one shared deterministic implementation and transparent diagnostics across EPUB/PDF and scoring surfaces.

Durable decisions/outcomes:
- Centralized pattern detection/action logic in `cookimport/parsing/pattern_flags.py` and reused it across importer/scoring boundaries.
- Kept rollout deterministic and policy-aligned (no AI parsing/cleanup in ingestion).
- Preserved scoring-penalty behavior with explicit constants (`toc=0.18`, `duplicate_title=0.09`, `overlap_duplicate=0.26`) after targeted tests passed.
- Added/retained advisory-only pass1 `pattern_hints` contract wiring behind explicit env gate.

Evidence preserved:
- Targeted ingestion/core suites and follow-up gap-closure assertions for PDF diagnostics/trim and direct scoring penalties (recorded as passing in task).

Anti-loop note:
- If candidate suppression appears over-aggressive, inspect `pattern_diagnostics.json` and penalty reasons before changing constants blindly.

## 2026-02-28 migrated understanding ledger (pattern-detector closure status)

### 2026-02-28_12.16.27 pattern detectors and heads-up integration points

Source: `docs/understandings/2026-02-28_12.16.27-pattern-detectors-and-heads-up-integration-points.md`

Problem captured:
- Needed deterministic TOC/duplicate suppression insertion guidance plus future-proof hook points for codex heads-up data.

Durable findings:
- Candidate gating path already supports non-destructive penalties/rejections.
- Best deterministic insertion point is after extraction and before candidate detection in EPUB/PDF importers.
- Heads-up telemetry persistence path already exists in codex runner/process-run artifacts.

### 2026-02-28_12.44.31 pattern-detector plan/docs lag discovery

Source: `docs/understandings/2026-02-28_12.44.31-pattern-detector-plan-doc-lag-discovery.md`

Problem captured:
- ExecPlan/docs checklist implied pending implementation even though runtime/tests already contained shipped detector/hints behavior.

Durable decisions:
- Treat this feature set as implemented baseline.
- Keep `pattern_hints` default-off behind explicit env gate.
- Update plans/docs before proposing new detector rewrites to avoid duplicate implementation loops.

Anti-loop note:
- If a checklist says detector milestone missing, validate current code/tests first; do not re-implement blindly.

