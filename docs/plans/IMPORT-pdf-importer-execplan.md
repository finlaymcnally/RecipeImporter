---
summary: "ExecPlan for the PDF cookbook import engine (pre-OCR'd PDFs)."
read_when:
  - When implementing the PDF import engine
---

# PDF Cookbook Importer ExecPlan

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

This plan must be maintained in accordance with docs/PLANS.md from the repository root.

## Purpose / Big Picture

After this change, a user can point the cookimport CLI at a folder containing PDF cookbooks (already OCR'd or with selectable text) and receive RecipeSage JSON-LD files plus a per-book report. The importer extracts text blocks with coordinates from each page, reconstructs reading order across columns, detects recipe boundaries, and emits one JSON-LD file per recipe. Success is visible by staging/recipesage_jsonld/<book>/<recipe>.json files, staging/reports/<book>.pdf_import_report.json, and work/<book_id>/pages/*.blocks.json debug artifacts.

## Progress

- [ ] Initial ExecPlan drafted.

## Surprises & Discoveries

(To be filled during implementation.)

## Decision Log

- Decision: Use PyMuPDF (fitz) as the primary PDF extraction library.
  Rationale: PyMuPDF provides block-level extraction with bounding boxes, font info, and is faster than pdfplumber for large files. Coordinates enable column detection and reading order reconstruction.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: Implement custom reading order reconstruction using column detection heuristics before recipe detection.
  Rationale: PDF text extraction often interleaves columns. Cookbook PDFs frequently use two-column layouts; correct reading order is essential for coherent recipes.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: User is responsible for OCR before import; this importer assumes text is already extractable.
  Rationale: User stated they will OCR in advance. This keeps the importer focused and avoids bundling OCR dependencies.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: Use deterministic heuristics for recipe detection with LLM escalation only for ambiguous cases.
  Rationale: Consistent with the EPUB importer approach; saves tokens and provides predictable output.
  Date/Author: 2026-01-21 / Initial Plan

## Outcomes & Retrospective

(To be filled at completion.)

## Context and Orientation

The cookimport package has Excel and (after the EPUB plan) EPUB importers. This plan adds a PDF importer at cookimport/plugins/pdf.py following the same Importer protocol.

Key terms used in this plan:

A Block is a text region extracted from a PDF page with bounding box coordinates (x0, y0, x1, y1), text content, and style information (font size, bold-ish flag). Blocks are the atomic unit for reading order and recipe detection. Reading Order is the sequence of blocks as they should be read, accounting for multi-column layouts. Column Detection is the process of clustering blocks by their x-position to identify left/right columns, then ordering blocks top-to-bottom within each column, columns left-to-right. A RecipeCandidate is a contiguous sequence of blocks (possibly spanning pages) that likely represents one recipe.

PDFs present unique challenges: text blocks may be out of order, columns interleave, headers/footers repeat, and sidebars contain tips or variations. The importer must handle these deterministically before attempting recipe segmentation.

## Plan of Work

Milestone 1 establishes PDF extraction and block representation. Create cookimport/plugins/pdf.py with the Importer protocol. Implement detect to return high confidence for .pdf files. Implement _extract_pages that uses PyMuPDF to load each page and extract blocks with get_text("dict") or get_text("blocks"). For each block, capture: page number, block index, bounding box, text, font size median, bold-ish flag (based on font name or weight), and block kind (text/image). Write per-page block files to work/<book_id>/pages/0001.blocks.json for debugging.

Milestone 2 implements cleaning and normalization. Create _clean_blocks that: removes repeating headers/footers (text repeating at top/bottom bands across many pages), fixes hyphenation artifacts (choco-\nlate to chocolate), normalizes ligatures (fi, fl), collapses whitespace, and normalizes bullet characters. Merge adjacent blocks that appear to be the same paragraph (close vertically, same style). This produces fewer, larger, cleaner blocks.

Milestone 3 implements reading order reconstruction. Create _reconstruct_reading_order that: clusters blocks by x-position to detect 1-3 columns per page, sorts blocks top-to-bottom within each column, orders columns left-to-right, and handles sidebars (small-width, far-right blocks) by flagging them rather than discarding. Output is an ordered block stream per page with column and sidebar annotations.

Milestone 4 implements recipe candidate detection. Create _detect_candidates that scans the ordered block stream across all pages. Use title signals: font size jump vs page median, bold, centered, short length, followed by ingredient-ish patterns. Use ingredient signals: blocks with many quantity/unit patterns, short lines. Use instruction signals: numbered steps, imperative verbs. Build candidates as block ranges (start_page, start_block, end_page, end_block) with confidence scores. Allow candidates to span pages.

Milestone 5 implements field extraction. For each candidate, extract: title (highest-scored title block), headnote (blocks before ingredients), ingredients (ingredient-ish blocks, detecting subheaders), instructions (step-ish blocks), and metadata (yield/times via regex). Sidebar blocks within the candidate range become notes/variations. Convert to RecipeCandidate model and emit RecipeSage JSON-LD.

Milestone 6 handles LLM escalation and edge cases. For low-confidence candidates (interleaved ingredients/instructions, unclear boundaries), send block text to LLM with constrained schema for section labeling. Validate with Pydantic. Flag image-heavy pages for manual review or future OCR integration.

Milestone 7 adds tests, fixtures, and documentation. Create fixture PDFs under tests/fixtures/pdf/ covering: single-column layout, two-column layout, mixed content, header/footer heavy, and sidebar-heavy pages. Add golden outputs and pytest tests.

## Concrete Steps

Work from /home/mcnal/projects/recipeimport with the virtual environment activated.

Install PyMuPDF:

    pip install pymupdf

Create the PDF importer:

    touch cookimport/plugins/pdf.py

Register in the plugin registry.

Run tests:

    pytest tests/test_pdf_importer.py

Verify with CLI:

    cookimport inspect tests/fixtures/pdf/sample_cookbook.pdf
    cookimport stage tests/fixtures/pdf --out data/output/pdf_test

## Validation and Acceptance

The change is accepted when: Running cookimport inspect on a fixture PDF prints page count, detected recipe count, column layout summary, and writes a mapping stub. Running cookimport stage produces JSON-LD files and a report. Each JSON-LD includes @id, name, recipeIngredient, recipeInstructions, and provenance with source file, page range, and block indices. The report lists recipe counts, page coverage, low-confidence candidates, and skipped pages. Pytest tests pass and verify block extraction, reading order reconstruction, and candidate detection.

## Idempotence and Recovery

Stable @id as urn:recipeimport:pdf:<file_hash>:<recipe_slug>. Work directory artifacts (pages/*.blocks.json) enable resumption. Errors in one file do not stop processing of other files.

## Artifacts and Notes

Example block from pages/0012.blocks.json:

    {
      "page": 12,
      "block_idx": 7,
      "bbox": [72.0, 150.0, 280.0, 180.0],
      "text": "Classic Tomato Soup",
      "style": {
        "font_size_med": 18.0,
        "is_boldish": true
      },
      "column": 0,
      "is_sidebar": false
    }

Example reading order output showing cross-column ordering:

    Page 12: [block_7 (col0), block_8 (col0), block_9 (col0), block_3 (col1), block_4 (col1)]

## Interfaces and Dependencies

Dependencies: pymupdf (fitz) for PDF parsing and block extraction.

In cookimport/plugins/pdf.py:

    from pathlib import Path
    import fitz  # PyMuPDF
    from cookimport.plugins.base import Importer
    from cookimport.core.models import WorkbookInspection, MappingConfig, ConversionResult

    class PdfImporter:
        name = "pdf"

        def detect(self, path: Path) -> float:
            """Return 0.9 for .pdf files."""
            ...

        def inspect(self, path: Path) -> WorkbookInspection:
            """Extract blocks, detect layout, return summary."""
            ...

        def convert(self, path: Path, mapping: MappingConfig | None) -> ConversionResult:
            """Full extraction, candidate detection, field extraction."""
            ...

        def _extract_pages(self, path: Path, work_dir: Path) -> list[Path]:
            """Extract blocks from each page, write to work_dir/pages/."""
            ...

        def _clean_blocks(self, blocks: list[dict]) -> list[dict]:
            """Remove headers/footers, fix hyphenation, merge paragraphs."""
            ...

        def _detect_columns(self, blocks: list[dict]) -> list[dict]:
            """Cluster by x-position, assign column indices."""
            ...

        def _reconstruct_reading_order(self, blocks: list[dict]) -> list[dict]:
            """Order blocks by column then y-position."""
            ...

        def _detect_candidates(self, ordered_blocks: list[dict]) -> list[dict]:
            """Find recipe boundaries across pages."""
            ...

        def _extract_fields(self, blocks: list[dict], candidate: dict) -> RecipeCandidate:
            """Extract title, ingredients, instructions from block range."""
            ...

The Block schema for PDFs includes: page (int), block_idx (int), bbox (list of 4 floats), text (str), style (dict with font_size_med, is_boldish), column (int), is_sidebar (bool).

Column detection parameters (configurable via mapping): min_column_gap (pixels between columns), sidebar_max_width (max width for sidebar classification), header_footer_band_height (pixels from top/bottom to check for repeating content).
