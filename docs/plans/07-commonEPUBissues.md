---
summary: "ExecPlan and implementation record for EPUB extraction quick wins (normalization, structural cleanup, and extraction health guardrails)."
read_when:
  - "When changing EPUB text normalization or post-extraction block cleanup"
  - "When debugging EPUB noise/line-boundary issues that break segmentation"
  - "When updating EPUB extraction health warning behavior"
---

# EPUB extraction quick wins: common bugs, guardrails, and fixes

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` were updated during implementation.

This document is maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

EPUB quality failures were mostly upstream text-shape problems (soft hyphens, BR-collapsed lists, bullet prefixes, TOC/nav noise, pagebreak noise). Downstream recipe segmentation and ingredient parsing then failed in noisy ways. This work adds extractor-agnostic EPUB cleanup plus extraction health checks so bad EPUB block streams are corrected early and suspicious runs are explicitly flagged.

User-visible outcomes after implementation:

- `legacy` and `unstructured` EPUB extraction now share postprocess cleanup (`cookimport/parsing/epub_postprocess.py`).
- EPUB text now uses dedicated normalization (`cleaning.normalize_epub_text`) for soft hyphens, zero-width chars, unicode fractions/punctuation.
- EPUB nav/TOC spine documents are skipped when detected by OPF properties or nav signatures.
- EPUB extraction now writes `epub_extraction_health.json` and appends `epub_*` warning keys into `ConversionReport.warnings`.
- New synthetic regression tests cover common bug classes across extractors.

## Progress

- [x] (2026-02-19_14.13.16) Added synthetic EPUB fixture builder enhancements in `tests/fixtures/make_epub.py` for nav-in-spine and custom chapter content.
- [x] (2026-02-19_14.13.16) Added EPUB-specific text normalization (`normalize_epub_text`) in `cookimport/parsing/cleaning.py`.
- [x] (2026-02-19_14.13.16) Added shared EPUB postprocess module `cookimport/parsing/epub_postprocess.py`.
- [x] (2026-02-19_14.13.16) Added EPUB extraction health module `cookimport/parsing/epub_health.py`.
- [x] (2026-02-19_14.13.16) Wired postprocess + health reporting into `cookimport/plugins/epub.py` for `legacy` and `unstructured`.
- [x] (2026-02-19_14.13.16) Added nav/TOC spine skipping and richer spine metadata (`EpubSpineItem`) in EPUB importer.
- [x] (2026-02-19_14.13.16) Updated legacy parser table-row handling and pagebreak filtering.
- [x] (2026-02-19_14.13.16) Added regression suite `tests/test_epub_extraction_quickwins.py` plus normalization unit tests `tests/test_cleaning_epub.py`.
- [x] (2026-02-19_14.13.16) Updated docs (`docs/03-ingestion/03-ingestion_readme.md`, `docs/04-parsing/04-parsing_readme.md`, `docs/IMPORTANT CONVENTIONS.md`, `cookimport/parsing/README.md`).

## Surprises & Discoveries

- Observation: Existing debug extract tooling in `cookimport/cli.py:debug_epub_extract` compared raw Unstructured outputs and did not include the new shared postprocess pass, causing parity drift.
  Evidence: importer path now applies `postprocess_epub_blocks(...)`; debug command needed the same call for comparable block counts and ingredient-line metrics.

- Observation: OPF spine metadata needed to carry `item_id` and `properties` to reliably skip nav docs in zip-fallback extraction.
  Evidence: old tuple shape `(path, media_type)` could not distinguish nav items from chapter XHTML in fallback mode.

## Decision Log

- Decision: Keep EPUB-specific cleanup in a single shared postprocess module and apply it only to HTML-based extractors (`legacy`, `unstructured`), not `markitdown`.
  Rationale: The failures targeted here come from HTML extraction shape; `markitdown` already emits line-oriented markdown blocks and should remain unchanged.
  Date/Author: 2026-02-19 / Codex

- Decision: Emit extraction health as both report warnings and raw JSON artifact.
  Rationale: warnings give quick triage visibility, and artifact metrics preserve full debugging context without opening code.
  Date/Author: 2026-02-19 / Codex

- Decision: Parse OPF manifest/spine into a typed `EpubSpineItem` contract.
  Rationale: nav-skipping correctness requires item properties and ids in both ebooklib and zip fallback paths.
  Date/Author: 2026-02-19 / Codex

## Outcomes & Retrospective

Quick-win goal achieved: EPUB block streams are now cleaner before segmentation, and suspicious extraction quality is surfaced automatically.

Implemented improvements:

- Text cleanup: soft hyphen/zero-width/NBSP/fraction/punctuation normalization.
- Structure cleanup: BR/table/list split improvements and bullet stripping.
- Noise cleanup: nav/TOC spine skips and pagebreak filtering.
- Guardrails: deterministic health metrics + `epub_*` warning keys + raw health artifact.
- Coverage: synthetic regression tests for the targeted failure classes.

Remaining limitations:

- Health thresholds are intentionally conservative and heuristic; they are warning-only, not hard failures.
- Unstructured diagnostics (`unstructured_elements.jsonl`) represent pre-postprocess element rows; final block-level state is in `full_text`.

## Context and Orientation

Primary implementation files:

- `cookimport/parsing/cleaning.py`
- `cookimport/parsing/epub_postprocess.py`
- `cookimport/parsing/epub_health.py`
- `cookimport/parsing/epub_html_normalize.py`
- `cookimport/parsing/unstructured_adapter.py`
- `cookimport/plugins/epub.py`
- `cookimport/cli.py` (`debug-epub-extract` parity path)

Primary regression coverage:

- `tests/test_epub_extraction_quickwins.py`
- `tests/test_cleaning_epub.py`
- `tests/fixtures/make_epub.py`

## Plan of Work (Implemented)

### Milestone 1: Synthetic repro harness

Extended synthetic EPUB fixture generation to build custom nav/spine/chapter combinations for targeted regression tests.

### Milestone 2: Shared EPUB text normalization

Implemented `normalize_epub_text` and switched Unstructured text mapping and legacy extraction to use EPUB-specific normalization behavior.

### Milestone 3: Structural EPUB quick wins

Added shared postprocess pass for BR-collapsed lines, bullet stripping, page-marker filtering, and table/list line normalization. Updated legacy table row extraction and nav/pagebreak handling.

### Milestone 4: Extraction health guardrails

Added health metric computation and warning keys; persisted health JSON artifact and warning keys in conversion reports.

## Concrete Steps

Run from repository root:

    source .venv/bin/activate
    pip install -e .[dev]
    pytest -q tests/test_cleaning_epub.py tests/test_epub_extraction_quickwins.py

Optional broader EPUB validation:

    source .venv/bin/activate
    pytest -q tests/test_epub_importer.py tests/test_epub_debug_cli.py tests/test_epub_debug_extract_cli.py

## Validation and Acceptance

Accepted behavior:

- BR-collapsed ingredient paragraphs produce per-line blocks.
- Bullet-prefixed ingredient lines lose leading bullet glyphs and preserve quantity detection.
- Nav/TOC spine docs are skipped when detected.
- Pagebreak markers do not leak into output block text.
- Legacy table rows emit ingredient-like row blocks.
- Conversion report includes `epub_*` health warning keys when thresholds trip.
- Raw artifact `epub_extraction_health.json` exists for EPUB conversions.

## Idempotence and Recovery

- All extraction behavior is deterministic for a fixed input EPUB and extractor mode.
- New health warnings are non-blocking; runs do not fail solely from health warning keys.
- Rollback is file-scoped: revert postprocess/health wiring and keep extractor internals unchanged.

## Artifacts and Notes

New artifact:

- `raw/epub/<source_hash>/epub_extraction_health.json`:
  - `metrics`
  - `warnings`
  - `top_repeated_lines`

Related existing artifacts remain unchanged:

- `full_text.json`
- `unstructured_elements.jsonl`
- `raw_spine_xhtml_*.xhtml`
- `norm_spine_xhtml_*.xhtml`

## Interfaces and Dependencies

New interfaces:

- `cookimport.parsing.cleaning.normalize_epub_text(text: str) -> str`
- `cookimport.parsing.epub_postprocess.postprocess_epub_blocks(blocks: list[Block]) -> list[Block]`
- `cookimport.parsing.epub_health.compute_epub_extraction_health(blocks: list[Block]) -> dict[str, object]`

Updated interface:

- `EpubImporter._read_epub_spine(...)` now returns `list[EpubSpineItem]` (path, media_type, item_id, properties).

No new third-party dependencies were added.

Revision note (2026-02-19_14.13.16): Replaced draft-only ExecPlan with implementation record, added required front matter/read hints, and documented shipped code/test/doc changes plus the new EPUB extraction health contract.
