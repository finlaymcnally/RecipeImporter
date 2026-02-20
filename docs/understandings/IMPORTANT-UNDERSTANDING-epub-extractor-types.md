---
summary: "What each EPUB extractor mode does (`unstructured`, `legacy`, `markdown`, `auto`, `markitdown`) and when to use each."
read_when:
  - "When choosing an EPUB extractor for a run"
  - "When debugging extractor-specific output differences or auto-selection"
---

# EPUB Extractor Types

`cookimport` supports five extractor values via `epub_extractor` (`--epub-extractor` / `C3IMP_EPUB_EXTRACTOR`):

- `unstructured` (default)
- `legacy`
- `markdown`
- `auto`
- `markitdown` (legacy compatibility path)

## Architecture Clarification

Extractor selection is a single mutually exclusive choice per run:

- `EPUB -> one extractor backend -> Block stream -> shared segmentation/extraction`

It is not a toggle stack where multiple extractors run in sequence.

## `unstructured`

What it does:
- Normalizes spine XHTML and partitions with Unstructured via `partition_html_to_blocks(...)`.
- Emits semantic traceability fields and diagnostics (`unstructured_elements.jsonl`).
- Captures raw + normalized spine XHTML debug artifacts.

Split support:
- Yes (spine-range jobs supported).

## `legacy`

What it does:
- Parses XHTML with BeautifulSoup block-tag traversal.
- Emits deterministic block rows with `legacy_*` diagnostics keys.
- Uses shared EPUB postprocess and signal enrichment after extraction.

Split support:
- Yes (spine-range jobs supported).

## `markdown`

What it does:
- Converts each spine HTML document to markdown.
- Uses Pandoc when available; falls back to `markdownify` deterministically.
- Parses markdown lines into heading/list/paragraph blocks (`markdown_to_blocks`).
- Emits diagnostics artifact `markdown_blocks.jsonl` with line-level provenance.

Split support:
- Yes (spine-range jobs supported).

## `auto`

What it does:
- Samples deterministic spine indices and evaluates candidate backends (`unstructured`, `markdown`, `legacy`) with `score_blocks(...)`.
- Picks highest average score (ties broken by configured candidate order).
- Writes rationale artifact: `raw/epub/<source_hash>/epub_extractor_auto.json`.
- Persists both requested and effective extractor in run config/report fields.

Split support:
- Resolved before workers launch; workers use the resolved concrete backend.

## `markitdown` (compatibility path)

What it does:
- Converts entire EPUB to markdown through the legacy whole-book MarkItDown adapter path.
- Parses markdown blocks with line provenance and emits `markitdown_markdown.md`.

Split support:
- No. This mode is whole-book only.

## Shared Downstream Path

After block extraction, all EPUB modes share:
- shared EPUB postprocess (for HTML-based backends),
- `signals.enrich_block(...)`,
- `assign_block_roles(...)`,
- candidate detection (`_detect_candidates`) and field extraction.

Extractor differences mainly change block boundaries and metadata, not downstream recipe logic.

## Quick Selection Guidance

- Start with `unstructured` for general-purpose extraction.
- Use `legacy` for simple tag-driven behavior.
- Use `markdown` when per-spine HTML-to-markdown conversion improves structure.
- Use `auto` when you want deterministic backend scoring and auditable selection.
- Use `markitdown` only when you explicitly want whole-book legacy markdown conversion.
