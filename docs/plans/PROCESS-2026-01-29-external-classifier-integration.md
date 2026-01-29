---
summary: "Integrate docTR for OCR and ingredient-instruction-classifier for text segmentation, simplifying tip extraction."
read_when:
  - When improving OCR support for scanned PDFs
  - When heuristic-based tip/instruction classification is unreliable
  - When considering external ML libraries for recipe parsing
---

# External Classifier Integration: OCR + Line Classification

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

The current cookimport pipeline "kind of works but is buggy." Specifically, tip extraction is unreliable because the ~1000 lines of heuristics in `cookimport/parsing/tips.py` try to do too much: detect what's an instruction, what's an ingredient, and what's a tip/narrative all at once.

After this change, users gain:

1. **OCR support for scanned PDFs** — Currently, scanned PDFs are detected but require external OCR. After this, the system will OCR them automatically using docTR, producing text with bounding boxes for provenance.

2. **Reliable text segmentation** — Instead of heuristics guessing whether a line is an ingredient, instruction, or "other," an external pre-trained classifier makes that decision. The "other" bucket becomes the tip/narrative candidate pool.

3. **Simpler tip extraction** — The tip extraction code no longer needs to distinguish ingredients from instructions. It only needs to classify the "other" bucket into general tips, recipe-specific notes, and narrative to discard.

To see it working: run `cookimport stage scanned-cookbook.pdf` on a scanned PDF and observe that (a) text is extracted via OCR, and (b) the output contains correctly segmented ingredients, instructions, and tips — without the current misclassification bugs.

## Progress

- [ ] Initial ExecPlan drafted.
- [ ] Milestone 1: Integrate docTR for OCR.
- [ ] Milestone 2: Integrate ingredient-instruction-classifier.
- [ ] Milestone 3: Simplify tip extraction to use "other" bucket.
- [ ] Milestone 4 (Optional): Add LayoutParser for complex layouts.

## Surprises & Discoveries

(To be filled during implementation.)

## Decision Log

- Decision: Use docTR instead of PaddleOCR.
  Rationale: docTR is pure Python, PyTorch-based, and has simpler installation. PaddleOCR requires the PaddlePaddle framework which adds complexity and potential dependency conflicts. For a solo builder prioritizing maintainability, docTR is the right choice. PaddleOCR can be revisited if docTR's accuracy proves insufficient on specific document types.
  Date/Author: 2026-01-29 / Agent

- Decision: Defer LayoutParser to an optional milestone.
  Rationale: LayoutParser requires detectron2 (heavy PyTorch dependency) and is primarily useful for complex multi-column cookbook layouts. Most recipe sources (EPUB, text PDFs, Excel) don't need layout detection — docTR's line-level bounding boxes are sufficient. Start simple; add LayoutParser only if complex scans become a priority.
  Date/Author: 2026-01-29 / Agent

- Decision: Keep ingredient-parser-nlp as the ingredient parsing library.
  Rationale: User reports this is "the best part" of the current pipeline. The ingredient-instruction-classifier only determines *which* lines are ingredients; the actual parsing of those lines into quantity/unit/name/prep continues to use ingredient-parser-nlp.
  Date/Author: 2026-01-29 / Agent

## Outcomes & Retrospective

(To be filled upon completion.)

## Context and Orientation

The cookimport project is a recipe import pipeline that ingests recipes from multiple formats (PDF, EPUB, Excel, text, app archives) and produces structured output in Draft V1 schema with parsed ingredients, instructions, and extracted tips.

Key files and modules involved in this plan:

**Existing code to modify:**

- `cookimport/plugins/pdf.py` — Current PDF importer using PyMuPDF (fitz). Detects "image-pdf" (scanned) vs "text-pdf" but has no OCR. This is where docTR integration goes.

- `cookimport/parsing/tips.py` (~1090 lines) — Heuristic-based tip extraction. Currently tries to detect instructions vs ingredients vs tips using regex/keywords. Will be simplified to only classify the "other" bucket from the classifier.

- `cookimport/core/models.py` — Pydantic models. May need new fields to store classifier confidence scores and OCR bounding boxes.

- `cookimport/parsing/signals.py` — Block classification signals. May be augmented or replaced by classifier output.

**New code to create:**

- `cookimport/parsing/classifier.py` — Wrapper around ingredient-instruction-classifier that handles loading the model and classifying text lines.

- `cookimport/ocr/doctr_engine.py` — Wrapper around docTR that handles OCR with bounding box extraction.

**External libraries to add:**

- `python-doctr[torch]` — OCR engine. Provides text detection + recognition with word/line bounding boxes.

- `ingredient-instruction-classifier` — TensorFlow-based classifier that labels text as ingredient/instruction/other. GitHub: julianpoy/ingredient-instruction-classifier.

**Existing libraries to keep:**

- `ingredient-parser-nlp` — Parses ingredient lines into structured data (quantity, unit, name, prep). This is already working well and is not replaced.

- `pymupdf` — Still used for text-based PDFs and as fallback; docTR is only invoked for scanned PDFs.

## Plan of Work

### Milestone 1: Integrate docTR for OCR

**Goal:** When a PDF is detected as scanned (no extractable text), automatically run OCR using docTR and return text with bounding boxes for provenance.

**What exists after this milestone:** Scanned PDFs produce the same `RecipeCandidate` output as text PDFs, with provenance fields containing OCR bounding box coordinates.

**Edits:**

1. Add `python-doctr[torch]` to `pyproject.toml` dependencies.

2. Create `cookimport/ocr/__init__.py` (empty, makes it a package).

3. Create `cookimport/ocr/doctr_engine.py` with:
   - Function `ocr_pdf(path: Path) -> list[OcrPage]` that runs docTR on each page.
   - `OcrPage` dataclass with `page_num`, `lines: list[OcrLine]`.
   - `OcrLine` dataclass with `text`, `confidence`, `bbox: tuple[float, float, float, float]` (x0, y0, x1, y1 in relative coords).
   - Lazy model loading (only load on first call) to avoid startup cost.

4. Modify `cookimport/plugins/pdf.py`:
   - In `convert()`, after detecting "image-pdf", call `ocr_pdf()` instead of returning empty blocks.
   - Map OCR lines to the existing block structure with provenance including bounding boxes.
   - Add `ocr_engine: Literal["doctr", "none"]` field to the inspection report.

5. Update `cookimport/core/models.py`:
   - Add optional `bbox` field to provenance dict schema (or document it as an allowed key).

**Validation:** Run `cookimport stage tests/fixtures/scanned-recipe.pdf` (create a fixture if none exists) and verify:
   - The output JSON contains extracted text.
   - Provenance includes `bbox` coordinates.
   - Text extraction is reasonably accurate (spot-check manually).

### Milestone 2: Integrate ingredient-instruction-classifier

**Goal:** Classify each text line/block as ingredient, instruction, or other before tip extraction runs.

**What exists after this milestone:** Every `RecipeCandidate` has its blocks annotated with classifier labels and confidence scores. The parsing pipeline uses these labels instead of (or in addition to) heuristic signals.

**Background on the classifier:**

The `ingredient-instruction-classifier` (GitHub: julianpoy/ingredient-instruction-classifier) is a TensorFlow model that classifies text into three categories:
- `ingredient` — Lines that are ingredients (e.g., "2 cups flour")
- `instruction` — Lines that are cooking instructions (e.g., "Preheat oven to 350°F")
- `other` — Everything else (tips, headnotes, narrative, titles, etc.)

The model is designed for recipe text and handles messy/informal language well.

**Edits:**

1. Add `ingredient-instruction-classifier` to `pyproject.toml` dependencies. If not on PyPI, add as git dependency: `ingredient-instruction-classifier @ git+https://github.com/julianpoy/ingredient-instruction-classifier.git`.

2. Create `cookimport/parsing/classifier.py` with:
   - Function `classify_lines(lines: list[str]) -> list[ClassificationResult]`.
   - `ClassificationResult` dataclass with `label: Literal["ingredient", "instruction", "other"]`, `confidence: float`, `text: str`.
   - Lazy model loading to avoid startup cost.
   - Batch classification for efficiency (classify all lines at once).

3. Modify `cookimport/plugins/base.py`:
   - Add optional `classification` field to block/line data structures that stores the classifier result.

4. Modify each importer (`pdf.py`, `epub.py`, `text.py`, `excel.py`):
   - After extracting text blocks/lines, call `classify_lines()` on them.
   - Store classification results alongside the text.
   - This is a "classify early" approach — classification happens during ingestion, not during tip extraction.

5. Modify `cookimport/parsing/tips.py`:
   - Change `extract_tip_candidates()` to use classifier labels:
     - Lines labeled `ingredient` or `instruction` are not tip candidates.
     - Lines labeled `other` are passed to the existing tip classification logic (general vs recipe-specific vs narrative).
   - This dramatically simplifies the tip extraction — it no longer needs to detect ingredients/instructions.

**Validation:** Run `cookimport stage tests/fixtures/mixed-content.epub` and verify:
   - Blocks are correctly labeled as ingredient/instruction/other.
   - Tip candidates come only from "other" blocks.
   - Ingredients and instructions are no longer misclassified as tips.

### Milestone 3: Simplify tip extraction

**Goal:** Refactor tip extraction to focus only on classifying the "other" bucket, removing ~500+ lines of ingredient/instruction detection heuristics.

**What exists after this milestone:** `cookimport/parsing/tips.py` is significantly smaller and cleaner. It assumes input has already been filtered to "other" (non-ingredient, non-instruction) text and only needs to:
   - Distinguish general tips from recipe-specific notes
   - Filter out pure narrative (biographical, introductory text)
   - Apply taxonomy tagging

**Edits:**

1. In `cookimport/parsing/tips.py`:
   - Remove or deprecate heuristics that detect ingredient-like or instruction-like patterns (these are now handled by the classifier).
   - Keep heuristics that distinguish:
     - General tips (cooking advice applicable to many recipes)
     - Recipe-specific notes (advice specific to the current recipe)
     - Narrative to discard (biographical info, story-telling, introductions)
   - The function signature remains the same but the implementation is simpler.

2. Create `cookimport/parsing/tip_classifier.py` (optional, if warranted):
   - If the remaining tip logic is small, keep it in `tips.py`.
   - If it's cleaner to separate, create a focused module for tip-vs-narrative classification.

3. Update tests in `tests/test_tip_extraction.py`:
   - Adjust tests to reflect the new assumption that input is pre-filtered to "other" lines.
   - Add tests for the general/recipe-specific/narrative classification.

**Validation:** Run the full test suite and verify:
   - All existing tip extraction tests pass (possibly with adjusted expectations).
   - Tip extraction runs faster (fewer heuristics to evaluate).
   - Manual spot-check: process a cookbook and verify tips are cleaner.

### Milestone 4 (Optional): Add LayoutParser for complex layouts

**Goal:** For scanned cookbooks with complex layouts (multi-column, sidebars, boxed tips), use LayoutParser to detect document regions before OCR.

**What exists after this milestone:** The pipeline can handle scanned cookbook pages with columns, sidebars, and boxed sections, grouping text correctly before classification.

**Why this is optional:** Most recipe sources don't have complex layouts. Single-column PDFs, EPUBs, and text files work fine with line-by-line processing. This milestone is only needed if complex cookbook scans become a priority.

**Edits (if implemented):**

1. Add `layoutparser[torch]` or `layoutparser[detectron2]` to `pyproject.toml`.

2. Create `cookimport/ocr/layout_engine.py` with:
   - Function `detect_layout(image: np.ndarray) -> list[LayoutRegion]`.
   - `LayoutRegion` dataclass with `type: str` (text, title, list, figure, table), `bbox`, `confidence`.
   - Use a pre-trained model (e.g., PubLayNet or a cookbook-specific one if available).

3. Modify `cookimport/ocr/doctr_engine.py`:
   - Add option to run layout detection first, then OCR within each region.
   - Preserve region type in output (e.g., "sidebar" or "main text").

4. Modify `cookimport/plugins/pdf.py`:
   - Add config option `use_layout_parser: bool = False`.
   - When enabled, run layout detection before OCR.

**Validation:** Process a complex multi-column cookbook scan and verify:
   - Regions are correctly detected.
   - Text from different columns is not interleaved.
   - Sidebars/boxed tips are grouped separately.

## Concrete Steps

### Milestone 1: docTR Integration

Working directory: `/home/mcnal/projects/recipeimport`

    # 1. Add dependency
    # Edit pyproject.toml to add: "python-doctr[torch]>=0.9"

    # 2. Create OCR module
    mkdir -p cookimport/ocr
    touch cookimport/ocr/__init__.py
    # Create cookimport/ocr/doctr_engine.py (see Plan of Work)

    # 3. Create test fixture (if needed)
    # Place a scanned PDF at: tests/fixtures/scanned-recipe.pdf

    # 4. Run tests
    source .venv/bin/activate
    pip install -e .[dev]
    pytest tests/test_pdf_importer.py -v

    # 5. Manual validation
    cookimport stage tests/fixtures/scanned-recipe.pdf --output-dir data/output/ocr-test
    # Inspect output JSON for extracted text and bbox provenance

### Milestone 2: Classifier Integration

Working directory: `/home/mcnal/projects/recipeimport`

    # 1. Investigate the classifier library
    # Clone and explore: git clone https://github.com/julianpoy/ingredient-instruction-classifier.git /tmp/classifier
    # Check if it's pip-installable or needs vendoring

    # 2. Add dependency (adjust based on investigation)
    # Edit pyproject.toml to add the classifier

    # 3. Create classifier wrapper
    # Create cookimport/parsing/classifier.py (see Plan of Work)

    # 4. Modify importers to classify during ingestion
    # Update pdf.py, epub.py, text.py, excel.py

    # 5. Run tests
    pytest tests/ -v

    # 6. Manual validation
    cookimport stage data/input/some-cookbook.epub --output-dir data/output/classifier-test
    # Inspect output for classification labels

### Milestone 3: Tip Extraction Simplification

Working directory: `/home/mcnal/projects/recipeimport`

    # 1. Identify heuristics to remove
    # Read through tips.py and mark sections that detect ingredients/instructions

    # 2. Refactor tips.py
    # Remove ingredient/instruction detection, keep tip classification

    # 3. Update tests
    # Adjust test_tip_extraction.py expectations

    # 4. Run tests
    pytest tests/test_tip_extraction.py -v

    # 5. Full test suite
    pytest tests/ -v

    # 6. Manual validation
    # Process the same cookbook as before, compare tip quality

## Validation and Acceptance

**Milestone 1 acceptance:** Run `cookimport stage` on a scanned PDF. Expect:
   - Output JSON contains extracted recipe text (not empty).
   - Provenance fields include `bbox` with coordinates.
   - Recipe name, ingredients, and instructions are populated.

**Milestone 2 acceptance:** Run `cookimport stage` on any supported file. Expect:
   - Each block/line has a `classification` field with `label` and `confidence`.
   - Labels are `ingredient`, `instruction`, or `other`.
   - Ingredients are correctly identified (compare to current output).

**Milestone 3 acceptance:** Run the full test suite. Expect:
   - All tests pass.
   - `tips.py` is significantly smaller (aim for <600 lines, down from ~1090).
   - Tip extraction is faster (fewer regexes to evaluate).
   - Manual review: tips from a cookbook are cleaner than before.

**Overall acceptance:** Import a cookbook (PDF or EPUB) end-to-end. Expect:
   - Scanned pages are OCR'd automatically.
   - Ingredients, instructions, and tips are correctly segmented.
   - No more instructions misclassified as tips (or vice versa).
   - Provenance traces back to source with bounding boxes (for OCR'd content).

## Idempotence and Recovery

All steps are idempotent:
   - Dependency installation is idempotent (pip reinstalls are safe).
   - File creation is idempotent (overwrite existing).
   - Running `cookimport stage` multiple times produces the same output.

If a step fails partway:
   - Milestone 1: If docTR fails, the PDF importer falls back to reporting "image-pdf, no text" (current behavior).
   - Milestone 2: If the classifier fails to load, importers should gracefully degrade to no classification (log a warning).
   - Milestone 3: Refactoring is incremental; tests catch regressions.

## Artifacts and Notes

**Expected dependency additions to pyproject.toml:**

    dependencies = [
        # ... existing deps ...
        "python-doctr[torch]>=0.9",
        # classifier TBD based on investigation
    ]

**Example classifier wrapper usage:**

    from cookimport.parsing.classifier import classify_lines

    lines = ["2 cups flour", "Preheat oven to 350°F", "This recipe comes from my grandmother."]
    results = classify_lines(lines)
    # results[0].label == "ingredient", confidence ~0.95
    # results[1].label == "instruction", confidence ~0.92
    # results[2].label == "other", confidence ~0.88

**Example docTR OCR usage:**

    from cookimport.ocr.doctr_engine import ocr_pdf

    pages = ocr_pdf(Path("scanned-cookbook.pdf"))
    for page in pages:
        for line in page.lines:
            print(f"{line.text} @ {line.bbox} (conf: {line.confidence:.2f})")

## Interfaces and Dependencies

**New interfaces to create:**

In `cookimport/ocr/doctr_engine.py`:

    @dataclass
    class OcrLine:
        text: str
        confidence: float
        bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 (relative 0-1)

    @dataclass
    class OcrPage:
        page_num: int
        lines: list[OcrLine]

    def ocr_pdf(path: Path) -> list[OcrPage]:
        """Run OCR on a PDF file, returning text with bounding boxes."""
        ...

In `cookimport/parsing/classifier.py`:

    @dataclass
    class ClassificationResult:
        text: str
        label: Literal["ingredient", "instruction", "other"]
        confidence: float

    def classify_lines(lines: list[str]) -> list[ClassificationResult]:
        """Classify text lines as ingredient, instruction, or other."""
        ...

**External dependencies:**

- `python-doctr[torch]>=0.9` — PyPI package for OCR
- `ingredient-instruction-classifier` — GitHub repo, installation method TBD

**Internal dependencies preserved:**

- `ingredient-parser-nlp` — Still used for parsing ingredient lines into structured data
- `pymupdf` — Still used for text-based PDF extraction
