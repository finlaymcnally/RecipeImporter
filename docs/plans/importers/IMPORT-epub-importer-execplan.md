---
summary: "ExecPlan for the EPUB and ebook cookbook import engine."
read_when:
  - When implementing the EPUB import engine
---

# EPUB and Ebook Cookbook Importer ExecPlan

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

This plan must be maintained in accordance with docs/PLANS.md from the repository root.

## Purpose / Big Picture

After this change, a user can point the cookimport CLI at a folder containing EPUB files (and optionally other ebook formats like MOBI, AZW3) and receive RecipeSage JSON-LD files plus a per-book report in the staging layout. The importer will extract text and structure from ebook files, detect recipe boundaries within chapters, and emit one JSON-LD file per detected recipe. Success is visible by the presence of staging/recipesage_jsonld/<book>/<recipe_slug>.json files, staging/reports/<book>.epub_import_report.json, and debug artifacts showing block extraction and candidate detection.

## Progress

- [x] Initial ExecPlan drafted.
- [x] Implemented `EpubImporter` in `cookimport/plugins/epub.py`.
- [x] Implemented DocPack extraction and Candidate segmentation.
- [x] Verified with `tests/test_epub_importer.py`.
- [x] Added zipfile-based spine fallback when ebooklib is unavailable or fails.
- [x] Added yield-based candidate splitting and heuristic ingredient/instruction extraction.

## Surprises & Discoveries

- Some EPUBs parse as valid ZIP files but still trigger ebooklib errors; parsing container.xml + OPF spine directly is more reliable for extraction.
- The ATK EPUB has frequent `serves` lines but no explicit instruction headers, so segmentation must leverage yields and numbered steps.

## Decision Log

- Decision: Use direct EPUB unzip as the primary extraction path, with Calibre as a fallback for non-EPUB formats or malformed EPUBs.
  Rationale: EPUB is a ZIP containing XHTML; parsing directly preserves structure better than conversion tools. Calibre handles edge cases and format conversion when needed.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: Create an intermediate DocPack representation (book_meta.json + blocks.jsonl) before recipe segmentation.
  Rationale: A uniform block stream allows the same downstream recipe detection logic regardless of the original format, and enables debugging/resumption.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: Use deterministic heuristics for recipe boundary detection before any LLM escalation.
  Rationale: Saves tokens and provides predictable, debuggable output. LLM is only needed for genuinely ambiguous layouts.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: Add a zipfile-based EPUB spine reader as a fallback when ebooklib is missing or fails to parse.
  Rationale: Keeps the importer resilient to EPUB variants and environments without ebooklib.
  Date/Author: 2026-01-23 / Implementation update

- Decision: Use yield-line anchors to split EPUB recipes when ingredient headers are sparse or absent.
  Rationale: Some cookbooks (like ATK) mark every recipe with "serves" but omit explicit section headers.
  Date/Author: 2026-01-23 / Implementation update

## Outcomes & Retrospective

- The EPUB importer now falls back to container.xml + OPF spine parsing when ebooklib is unavailable or fails, keeping extraction working in more environments.
- The EPUB importer now segments recipes on yield lines and extracts instructions using heuristic step detection when instruction headers are absent.

## Context and Orientation

The cookimport package already has an Excel importer at cookimport/plugins/excel.py. This plan adds an EPUB importer at cookimport/plugins/epub.py following the same Importer protocol. The importer must implement detect, inspect, and convert methods.

Key terms used in this plan:

A **DocPack** is an intermediate representation of an ebook consisting of:
*   `book_meta.json` (title, author, isbn, publisher, file hash)
*   `spine/` folder containing normalized XHTML files (representing the "real reading order")
*   `assets/images/` (extracted images)
*   `blocks.jsonl`: a linear stream of blocks in reading order.

A **Block** is a JSON object with fields like: `spine_idx`, `block_idx`, `type` (heading, paragraph, list_item, table, image), `heading_level`, `text`, `html`, `features`, and `source_path`.

A **RecipeCandidate** is a contiguous slice of blocks that likely represents one recipe, with start/end block indices and a confidence score.

**Features** are cheap boolean or numeric signals computed per block, such as `has_qty_unit_pattern`, `looks_like_ingredient_line`, `imperative_verb_score`, and `section_label`.

## Plan of Work

### Phase 1: Ingest & DocPack Generation (Milestone 1)

**Goal:** Convert any ebook format into a standardized `DocPack`.

1.  **Standardize Formats:**
    *   Use Calibre's `ebook-convert` as the "workhorse" for anything that isn't a clean EPUB (MOBI, AZW3, FB2). Convert them to EPUB first.
2.  **Extract EPUB:**
    *   **Primary Path (Direct Unzip):** Unzip the EPUB. Locate `content.opf` via `META-INF/container.xml`. Read the spine order. Load the XHTML files.
    *   **Fallback Path:** If parsing fails or the spine is garbage, use Calibre to convert to HTMLZ (zipped HTML).
3.  **Parse to Blocks:**
    *   **HTML Cleanup:** Deterministically strip nav/TOC boilerplate, drop page numbers, normalize whitespace, and merge hyphenation artifacts (e.g., `in-
ingredient`).
    *   **DOM Walk:** Walk the DOM and emit blocks (`h1-h6` -> heading, `li` -> list_item, `p` -> paragraph, `table` -> table block with cell grid).
    *   **Feature Computation:** For each block, compute cheap features using the shared **Signal Detection** module (see `docs/plans/PROCESS-common-parsing-and-normalization.md`):
        *   `has_qty_unit_pattern` (e.g., `^\s*\d+(\.\d+)?\s*(cup|tsp|tbsp|g|oz|ml|lb)\b`)
        *   `looks_like_ingredient_line` (qty + food word)
        *   `imperative_verb_score` (starts with "Mix", "Bake", "Heat")
        *   `section_label` ("Ingredients", "Directions", "Method")

### Phase 2: Recipe Segmentation (Milestone 2)

**Goal:** Turn the block stream into `RecipeCandidate` slices.

1.  **Candidate Start Signals:** Don't start a candidate unless you see two of the following:
    *   Title-ish heading (`h1`/`h2`/`h3` or short all-caps line).
    *   Ingredients-ish region within next N blocks.
    *   Instructions-ish region within next M blocks.
    *   Yield/Time markers ("Serves 4", "Prep time: 10m").
    *   *Special Case:* Multi-recipe pages (chapter contains many tiny recipes). Allow start signals on short bold lines if followed immediately by ingredients.
2.  **Candidate End Signals:**
    *   Next recipe start signal.
    *   New chapter heading that isn't recipe-like.
    *   Long narrative stretch with no ingredient/instruction features.
3.  **Confidence Scoring:**
    *   +3: Has ingredient section.
    *   +3: Has instruction section.
    *   +2: Title plausibility.
    *   +1: Yield/time found.
    *   -2: Candidate too short or too long.

### Phase 3: Field Extraction (Milestone 3)

**Goal:** Assign fields within a candidate slice (Deterministic First).

1.  **Title:** Best heading near start, or fallback to first "title-ish" paragraph.
2.  **Headnote:** Paragraphs between title and ingredients section.
3.  **Ingredients:**
    *   *Priority 1:* List items (`li`) under an "Ingredients" header.
    *   *Priority 2:* Table rows looking like ingredient grids.
    *   *Priority 3:* Consecutive ingredient-like paragraphs.
    *   *Subheaders:* Detect and preserve "For the sauce", "For the crust".
4.  **Instructions:**
    *   *Priority 1:* Ordered lists (`ol` > `li`).
    *   *Priority 2:* Paragraphs after "Directions"/"Method".
    *   *Priority 3:* Paragraphs with high imperative verb density.
5.  **Metadata:** Regex extraction for yield/servings, prep/cook times, temps.

### Phase 4: JSON-LD Emission & Edge Cases (Milestone 4)

1.  **Emit Artifacts:**
    *   Use the shared **Reporting and Provenance** standards (see `docs/plans/PROCESS-reporting-and-provenance.md`).
    *   `candidates/<book_id>/<candidate_id>.json` (Candidate schema with provenance).
    *   `recipesage_jsonld/<book_id>/<candidate_id>.jsonld` (Valid RecipeSage format).
    *   *Optional:* `debug/<candidate_id>.html` for human review.
2.  **Handle Image Recipes:** If a candidate has low text density but many images, extract images and flag for OCR (future expansion).
3.  **LLM Escalation (Surgical):** Only use LLM if confidence is low.
    *   Use the shared **LLM Repair** strategy (see `docs/plans/PROCESS-llm-repair.md`).
    *   *Trigger:* Interleaved ingredients/instructions, ambiguous structure.
    *   *Constraint:* Input ordered blocks; Output strict JSON schema validation.

## Concrete Steps

Work from `/home/mcnal/projects/recipeimport` with the virtual environment activated.

1.  **Install Dependencies:**
    `pip install beautifulsoup4 lxml ebooklib`

2.  **Create Importer:**
    `touch cookimport/plugins/epub.py`

3.  **Implement `EpubImporter` Class:**
    *   Implement `detect`, `inspect`, `convert`.
    *   Implement `_extract_docpack` (Unzip -> HTML Cleanup -> Block Stream).
    *   Implement `_detect_candidates` (Scanning blocks.jsonl).
    *   Implement `_extract_fields` (Assigning Title, Ingredients, Instructions).

4.  **Register Plugin:**
    Add to `cookimport/plugins/__init__.py`.

5.  **Testing:**
    *   Create fixtures in `tests/fixtures/epub/`.
    *   `pytest tests/test_epub_importer.py`
    *   `cookimport inspect tests/fixtures/epub/sample.epub`
    *   `cookimport stage tests/fixtures/epub --out data/output/epub_test`

## Validation and Acceptance

*   `cookimport inspect` prints chapter/recipe counts and layout info.
*   `cookimport stage` produces:
    *   `staging/recipesage_jsonld/...` (Valid JSON-LD).
    *   `staging/reports/...` (Import report).
*   Report lists recipe counts, low-confidence candidates, and skipped content.
*   Provenance includes source file, chapter, and block range.

## Interfaces and Dependencies

*   **Libraries:** `beautifulsoup4`, `lxml`, `ebooklib`, `calibre` (CLI, optional).
*   **Block Schema:** `spine_idx`, `block_idx`, `type`, `heading_level`, `text`, `html`, `features`, `source_path`.

## Alternative: Unstructured.io Integration (from Improving_Recipe_Import_Pipeline2.md)

The Unstructured library offers a potential simplification path for EPUB processing:

**What Unstructured Provides:**
- `partition_epub()`: EPUB → HTML (via Pandoc) → typed elements (Title, NarrativeText, ListItem, Table)
- Elements include metadata: page number, hierarchy, coordinates, section/chapter info
- Uniform block abstraction across formats (EPUB/PDF/HTML share same element schema)

**When to Consider:**
- If current ebooklib/BeautifulSoup approach struggles with specific EPUB variants
- When Pandoc's HTML output preserves headings/sections well enough
- Testing recommended on ~5 representative cookbooks before adoption

**Practical Integration Pattern:**
```python
from unstructured.partition.epub import partition_epub
elements = partition_epub(filename="cookbook.epub")
# Elements are typed blocks with metadata (type/text/element_id/metadata)
```

**Caveat:** Requires Pandoc installed. Test that `partition_epub` preserves structure adequately for your cookbooks; if it flattens too much, keep the current Calibre/unzip approach and optionally run `partition_html` on extracted HTML for consistent element schema.

**Privacy Note:** Use only local OSS/self-hosted Unstructured. Their hosted API collects documents for training.
