---
summary: "ExecPlan for the PDF cookbook import engine."
read_when:
  - When implementing the PDF import engine
---

# PDF Cookbook Importer ExecPlan

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

This plan must be maintained in accordance with docs/PLANS.md from the repository root.

## Purpose / Big Picture

After this change, a user can point the cookimport CLI at a folder containing PDF files (primarily OCR'd or text-based) and receive RecipeSage JSON-LD files plus a per-book report. The importer will extract text with layout awareness, reconstruct reading order (columns, sidebars), detect recipe boundaries, and emit structured recipe candidates. Success is visible by the presence of staging/recipesage_jsonld/<book>/<recipe>.json files and staging/reports/<book>.pdf_import_report.json.

## Progress

- [x] Initial ExecPlan drafted.
- [x] Implemented `PdfImporter` in `cookimport/plugins/pdf.py`.
- [x] Implemented Layout Analysis and Candidate Detection.
- [x] Verified with `tests/test_pdf_importer.py`.
- [x] (2026-01-23 19:20Z) Switched PDF extraction to line-level dict spans for font size/alignment signals.
- [x] (2026-01-23 19:35Z) Added column clustering (x0 gap) and per-column ordering to avoid tiled page interleaving.
- [x] (2026-01-23 19:50Z) Tightened OCR heuristics (ingredient anchors, yield capture, wrapped instruction merge).
- [x] (2026-01-23 20:05Z) Ensured staging `@id` respects `RecipeCandidate.identifier` for non-Excel importers.

## Surprises & Discoveries

- Observation: PyMuPDF `get_text("blocks", sort=True)` interleaves left/right columns on tiled pages.
  Evidence: Hix1.pdf page 4 shows alternating x0 ~55 and x0 ~288 blocks, mixing two recipes.
- Observation: OCR frequently misreads "1" as "l", so ingredient anchors must treat `l tbsp` as quantity-like.
  Evidence: Hix1.pdf dressing recipes show `l tbsp ...` lines without digits, but still valid ingredients.

## Decision Log

- Decision: Use PyMuPDF (fitz) for local, layout-aware block extraction.
  Rationale: It provides bounding boxes (bbox) and font metadata, which are essential for reconstructing reading order in multi-column layouts, unlike simple text extraction.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: Implement a "page stream" abstraction that orders blocks before recipe detection.
  Rationale: Cookbooks often have complex layouts (sidebars, 2-3 columns). Solving "reading order" first simplifies the downstream logic to just "scanning a stream of blocks" for recipe signals.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: Use deterministic heuristics for candidate detection (title signals, ingredient patterns) before any LLM use.
  Rationale: LLMs are slow and expensive for scanning entire books. Fast heuristics can identify likely recipe regions ("candidates") which can then be parsed more intensively if needed.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: Extract line-level blocks via `page.get_text("dict")` and derive font size/alignment from spans.
  Rationale: OCR PDFs expose headings via font size/bold spans; line-level blocks reduce cross-column mixing.
  Date/Author: 2026-01-23 / Codex

- Decision: Detect columns by x0 gap clustering and order by (page, column, y).
  Rationale: Tiled pages interleave blocks when sorted by y/x; column grouping preserves recipe boundaries.
  Date/Author: 2026-01-23 / Codex

- Decision: Treat `l`/`I` + unit as quantity-like for ingredient anchors in OCR PDFs.
  Rationale: OCR often substitutes "1" with letter "l"; this preserves ingredient detection without LLM fallback.
  Date/Author: 2026-01-23 / Codex

## Outcomes & Retrospective

(To be filled at completion.)

## Context and Orientation

This plan adds a PDF importer at cookimport/plugins/pdf.py. It follows the standard Importer protocol. Unlike Excel or EPUB, PDFs lack semantic structure (no "cells" or "tags"), so the core challenge is **Geometric Layout Analysis**: turning a bag of positioned words into a coherent stream of text blocks.

Key terms:
*   **Block:** A unit of text with a bounding box (x0, y0, x1, y1), font info, and text content.
*   **Page Stream:** A linear sequence of blocks for a page, sorted by reading order (e.g., Column 1 Top-to-Bottom -> Column 2 Top-to-Bottom).
*   **Candidate:** A span of blocks (potentially crossing page boundaries) identified as a single recipe.

## Plan of Work

### Phase 1: Ingest & Layout Extraction (Milestone 1)

**Goal:** Turn a PDF into a standardized "Working Folder" with block data.

1.  **Ingest + Identify:**
    *   Input: `some_cookbook.pdf`
    *   Output: `work/<book_id>/` folder with `meta.json` (hash, title guess) and `pages/` (JSON block data).
2.  **Layout-Aware Extraction (PyMuPDF):**
    *   Extract line-level spans from `page.get_text("dict")` to retain font size and bold hints.
    *   Normalize into `Block` objects: `{ page, bbox, text, style: { size, is_bold, alignment }, kind }`.
    *   *Why:* Downstream steps need to know "this block is in the left column" or "this is a margin sidebar".
3.  **Cleaning (Deterministic):**
    *   **Header/Footer Removal:** Detect repeating text near top/bottom bands (e.g., y < 60px) and drop them.
    *   **Artifact Fixes:** Fix hyphenation (`choco-\nlate`), ligatures (`ﬁ`->`fi`), and whitespace.
    *   **Merge Fragments:** Merge adjacent blocks that share style and are vertically close.

### Phase 2: Reading Order Reconstruction (Milestone 2)

**Goal:** Turn "soup of blocks" into a reliable reading sequence.

1.  **Column Detection:** Cluster blocks by x-position into 1-3 columns (using x0 distribution gaps).
2.  **Order Within Columns:** Sort blocks by y0 (top to bottom) within each column, then order columns left-to-right.
3.  **Sidebars/Callouts:** Identify blocks with distinct properties (narrow width, far-right margin, different font) as `sidebar=true`. Do not discard; keeps them available for notes/variations.
4.  **Output:** `PageTextStream` (ordered blocks with metadata).

### Phase 3: Recipe Candidate Detection (Milestone 3)

**Goal:** Detect start/end boundaries of recipes in the stream.

1.  **Start Signals (Heuristics):**
    *   **Title:** Font size jump vs. median, bold/all-caps, centered, short length (< 80 chars).
    *   **Followed by:** "Serves", "Yield", or Ingredient patterns (using shared **Signal Detection** from `docs/plans/PROCESS-common-parsing-and-normalization.md`).
2.  **Content Signals:**
    *   Use shared **Signal Detection** to identify ingredient lines and instruction steps.
    *   **Ingredients:** Blocks with many short lines, numbers/fractions (`1/2`, `½`), units (`cup`, `g`, `oz`).
    *   **Steps:** Numbered lists (`1.`, `Step 1`) or imperative verbs (`Mix`, `Bake`).
3.  **Candidate Spans:**
    *   Start at a likely Title.
    *   Continue until the next strong Title signal.
    *   Allow crossing page boundaries.
    *   Store `start_page`, `end_page`, `block_ids`, `confidence`.

### Phase 4: Section Splitting & JSON-LD (Milestone 4)

**Goal:** Parse candidates into fields and emit JSON-LD.

1.  **Deterministic Splitting:**
    *   **Headnote:** Everything before first ingredient region.
    *   **Ingredients:** Ingredient-ish region until step-ish region. Detect subheaders ("For the sauce") to create groups.
    *   **Instructions:** Step-ish region until end.
    *   **Notes:** Sidebar blocks near the candidate.
    *   **OCR Quirk:** Treat `l`/`I` as quantity-like when followed by a unit (`l tbsp`).
2.  **LLM Escalation (Surgical):**
    *   Use the shared **LLM Repair** strategy (see `docs/plans/PROCESS-llm-repair.md`).
    *   *Trigger:* Interleaved ingredients/instructions, multi-column ordering confusion, no clear boundaries.
    *   *Constraint:* Input ordered blocks; Output JSON identifying block ranges for sections.
3.  **Emission:**
    *   Use the shared **Reporting and Provenance** standards (see `docs/plans/PROCESS-reporting-and-provenance.md`).
    *   Write `staging/recipesage_jsonld/<book_id>/<slug>.jsonld`.
    *   Include provenance: source file, page range, raw extracted text.
    *   Write `manifest.json` using the standard `ReportBuilder`.

## Concrete Steps

1.  **Dependencies:** `pip install pymupdf` (and `numpy`/`scikit-learn` if needed for clustering).
2.  **Create Plugin:** `touch cookimport/plugins/pdf.py`.
3.  **Implement `PdfImporter`:**
    *   `detect`: Check for `.pdf` header.
    *   `inspect`: Run extraction on first 10 pages, print layout guess (1-col vs 2-col).
    *   `convert`: Full pipeline execution.
4.  **Implement `LayoutAnalyzer`:** Logic for column clustering and sorting.
5.  **Implement `RecipeSegmenter`:** Logic for scanning the block stream for titles/ingredients.

## Validation and Acceptance

*   `cookimport inspect` accurately identifies column layout on test PDFs.
*   `cookimport stage` produces valid JSON-LD files for standard layouts (1-col and 2-col).
*   Provenance data accurately links back to specific page numbers and bounding boxes.
*   Review HTML (optional) shows the PDF page with bounding boxes overlaying the detected recipe.

## Interfaces and Dependencies

*   **PyMuPDF (fitz):** Primary extraction engine.
*   **Block Model:** Shared with EPUB importer (see `cookimport.core.models` or equivalent).
*   **Clustering:** Simple 1D clustering for column detection (can be custom heuristic or `sklearn.cluster.KMeans` if deps allow).

Change Note (2026-01-23): Updated this plan to reflect line-level extraction, column gap clustering, and OCR-aware ingredient anchors added during Hix1.pdf debugging; also recorded the non-Excel `@id` behavior so the plan matches current staging output. This keeps the plan self-contained with the new implementation details.

## Alternative: Unstructured.io Integration (from Improving_Recipe_Import_Pipeline2.md)

The Unstructured library may simplify PDF processing, especially for OCR/scans:

**What Unstructured Provides:**
- `partition()` or `partition_pdf()`: PDF → typed elements with bounding boxes
- Layout/OCR strategy controls: `fast`, `hi_res`, `ocr_only`, `auto`
- Multi-column ordering and table extraction behavior options
- Element types: Title, NarrativeText, ListItem, Table, PageBreak

**When to Consider:**
- For PDFs/scans where DIY layout/OCR pipelines get painful
- When PyMuPDF struggles with specific PDF layouts
- As a "staging-layer accelerator" to produce clean blocks, not as a recipe parser

**Practical Integration Pattern:**
```python
from unstructured.partition.auto import partition
elements = partition(filename="cookbook.pdf", strategy="hi_res")
# Use element metadata (type, bbox, parent_id) for recipe boundary detection
```

**Note:** Unstructured won't identify recipes or parse ingredients—that's still your logic/LLM. It just produces clean, labeled chunks with metadata.

**Privacy Note:** Use only local OSS/self-hosted Unstructured. Their hosted API collects documents for training.
