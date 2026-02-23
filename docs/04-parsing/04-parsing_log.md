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
  - `pytest -q tests/test_cleaning_epub.py tests/test_epub_extraction_quickwins.py tests/test_epub_importer.py tests/test_epub_debug_cli.py tests/test_epub_debug_extract_cli.py`
  - `pytest -q tests/test_unstructured_adapter.py tests/test_cli_output_structure.py tests/test_epub_job_merge.py`
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
