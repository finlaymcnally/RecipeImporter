---
summary: "ExecPlan for the Image (OCR) import engine."
read_when:
  - When implementing the Image import engine
---

# Image Importer ExecPlan

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

This plan must be maintained in accordance with docs/PLANS.md from the repository root.

## Purpose / Big Picture

After this change, a user can point the cookimport CLI at a folder containing image files (PNG, JPG, JPEG) and receive RecipeSage JSON-LD files plus a report. The importer will use Optical Character Recognition (OCR) to extract text, reconstruct layout (reading order, columns), and detect recipe structures. Success is visible by the presence of staging/recipesage_jsonld/<image_file>/<recipe>.json files and staging/reports/<image_file>.image_import_report.json.

This system is designed to support pluggable OCR backends, prioritizing offline capabilities (PaddleOCR, EasyOCR, Tesseract) while allowing for future cloud integrations.

## Progress

- [ ] Initial ExecPlan drafted.
- [ ] Implemented `ImageImporter` in `cookimport/plugins/image.py`.
- [ ] Implemented Pluggable OCR Interface and Local Adapters.
- [ ] Implemented Layout Analysis (reusing PDF logic where possible).
- [ ] Verified with `tests/test_image_importer.py`.

## Surprises & Discoveries

(To be filled during implementation.)

## Decision Log

- Decision: Use a pluggable `OCREngine` interface.
  Rationale: Different images (clean scans vs. phone photos) require different strengths. We want to support PaddleOCR (robust for photos), EasyOCR (easy setup), and Tesseract (lightweight) without locking the core logic to one vendor.
  Date/Author: 2026-01-22 / Initial Plan

- Decision: Reuse the PDF Layout Analysis logic.
  Rationale: Once OCR provides bounding boxes and text, the problem is identical to PDF parsing: we have a bag of positioned text blocks that need to be ordered into columns and sections.
  Date/Author: 2026-01-22 / Initial Plan

## Outcomes & Retrospective

(To be filled at completion.)

## Context and Orientation

This plan adds an Image importer at `cookimport/plugins/image.py`. It bridges the gap between raw pixels and the structured text processing used by the PDF importer.

Key terms:
*   **OCR Block:** A unit of text returned by the OCR engine, containing text, a bounding box (x0, y0, x1, y1), and a confidence score.
*   **Engine:** A specific OCR implementation (e.g., `PaddleAdapter`, `TesseractAdapter`).
*   **Layout Reconstruction:** The process of turning spatial OCR blocks into a linear `PageTextStream`.

## Plan of Work

### Phase 1: Ingest & OCR Abstraction (Milestone 1)

**Goal:** Turn an image file into a standardized list of text blocks using a configurable engine.

1.  **Ingest:** Accept `.png`, `.jpg`, `.jpeg`.
2.  **OCR Interface:** Define a protocol `OCREngine` with a method `extract_text(image_path) -> List[Block]`.
3.  **Implement Adapters:**
    *   **PaddleOCR (Option A):** Best for phone photos/complex layouts. Run via Python API or CLI.
    *   **EasyOCR (Option B):** robust Python-native option.
    *   **Tesseract (Option C):** Lightweight, good for clean scans. Use `pytesseract` or CLI wrapper.
    *   *(Note: Cloud options like Google Cloud Vision or Azure Vision are out of scope for Milestone 1 but the interface must support them).*
4.  **CLI Configuration:** Allow user to select engine via config or flag (defaulting to a "best available" heuristic).

### Phase 2: Layout & Reading Order (Milestone 2)

**Goal:** Turn the "bag of blocks" from OCR into a readable text stream.

1.  **Normalization:** Convert engine-specific bbox formats to a standard `(x0, y0, x1, y1)` normalized to 0-1000 scale (consistent with PDF importer).
2.  **Reconstruction:**
    *   Reuse the **Layout Analysis** logic from the PDF Importer (`cookimport.plugins.pdf`).
    *   Cluster blocks into columns.
    *   Sort vertically within columns.
    *   Detect sidebars/notes based on spatial isolation.
3.  **Output:** `PageTextStream` (ordered blocks).

### Phase 3: Recipe Parsing (Milestone 3)

**Goal:** Identify and parse recipes from the text stream.

1.  **Candidate Detection:**
    *   Use shared **Signal Detection** (ingredients, steps).
    *   Identify titles based on font size (if available from OCR) or isolation/capitalization.
2.  **Segmentation:**
    *   Split stream into Headnote, Ingredients, Instructions, Notes.
    *   Handle multi-recipe images (e.g., a magazine page with two recipes) using the **Recipe Segmenter** logic.
3.  **LLM Repair:**
    *   Trigger if OCR confidence is low or layout is ambiguous.
    *   Pass the OCR text to the shared **LLM Repair** module.

### Phase 4: Reporting & Provenance (Milestone 4)

**Goal:** Emit structured JSON-LD and a report.

1.  **Emission:** Write `staging/recipesage_jsonld/...`.
2.  **Provenance:**
    *   Link parsed fields back to the original image bounding box.
    *   Report the OCR engine used and average confidence score.
3.  **Comparison Mode (Optional):**
    *   Allow running multiple engines on the same image and logging the diffs/confidence scores to helping the user choose the best one.

## Concrete Steps

1.  **Dependencies:** `pip install paddlepaddle paddleocr easyocr pytesseract` (add as optional dependencies or "extras").
2.  **Create Plugin:** `touch cookimport/plugins/image.py`.
3.  **Define Interface:** Create `cookimport/core/ocr.py` (or inside plugin) for the `OCREngine` base class.
4.  **Implement `ImageImporter`:**
    *   `detect`: Check image extensions.
    *   `inspect`: Run configured OCR on the image, print raw text and detected layout.
    *   `convert`: Full pipeline.
5.  **Implement Adapters:**
    *   `PaddleEngine`: Wraps PaddleOCR.
    *   `EasyOCREngine`: Wraps EasyOCR.
    *   `TesseractEngine`: Wraps Tesseract.

## Validation and Acceptance

*   `cookimport inspect --engine=paddle` prints readable text from a sample photo.
*   `cookimport stage` produces valid JSON-LD for a standard recipe image.
*   The system gracefully handles missing OCR dependencies (warns user and suggests installation).
*   Layout analysis correctly orders a 2-column recipe image.

## Interfaces and Dependencies

*   **PaddleOCR:** Primary recommendation for robustness.
*   **EasyOCR / Tesseract:** Secondary options.
*   **Pillow (PIL):** For basic image handling.
*   **Shared Layout Logic:** Must be importable from `cookimport.plugins.pdf` or refactored into `cookimport.core.layout`.
