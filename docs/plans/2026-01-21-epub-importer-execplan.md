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

- [ ] Initial ExecPlan drafted.

## Surprises & Discoveries

(To be filled during implementation.)

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

## Outcomes & Retrospective

(To be filled at completion.)

## Context and Orientation

The cookimport package already has an Excel importer at cookimport/plugins/excel.py. This plan adds an EPUB importer at cookimport/plugins/epub.py following the same Importer protocol. The importer must implement detect, inspect, and convert methods.

Key terms used in this plan:

A DocPack is an intermediate representation of an ebook consisting of book_meta.json (title, author, file hash), a spine/ folder with normalized XHTML files, and blocks.jsonl containing a stream of text blocks in reading order with metadata. A Block is a JSON object with fields like spine_idx, block_idx, type (heading, paragraph, list_item, table, image), heading_level, text, html, and computed features. A RecipeCandidate is a contiguous slice of blocks that likely represents one recipe, with start/end block indices and a confidence score. Features are cheap boolean or numeric signals computed per block, such as has_qty_unit_pattern, looks_like_ingredient_line, imperative_verb_score, and section_label.

The spine is the ordered list of content documents in an EPUB, defined in the OPF file. Reading order follows the spine. Chapters in cookbooks often contain multiple recipes, so recipe boundary detection must work within chapters, not just between them.

## Plan of Work

Milestone 1 establishes the EPUB extraction and DocPack generation. Create cookimport/plugins/epub.py with the Importer protocol. Implement detect to return high confidence for .epub files. Implement a private _extract_docpack method that unzips the EPUB, locates content.opf via META-INF/container.xml, reads the spine order, and loads XHTML files. Parse each XHTML file with BeautifulSoup or lxml, walking the DOM to emit Block objects. Compute features for each block during extraction. Write the DocPack to a work directory for debugging and resumption. If direct extraction fails (malformed EPUB), fall back to Calibre's ebook-convert to produce HTML first.

Milestone 2 implements recipe candidate detection on the block stream. Create a _detect_candidates method that scans blocks.jsonl and identifies recipe start/end boundaries. Use these signals for recipe start: heading block followed by ingredient-like lines within N blocks, explicit section labels like "Ingredients" or "Method", short all-caps lines followed by yield/ingredients. Use these signals for recipe end: next recipe start signal, new chapter heading without recipe signals, long narrative stretch without ingredient/instruction features. Compute a confidence score per candidate based on presence of title, ingredients region, instructions region, and yield/time markers. Store candidates with block index ranges and scores.

Milestone 3 implements field extraction from each candidate. For each candidate slice, extract: title (best heading near start), headnote (paragraphs between title and ingredients), ingredients (list items or ingredient-like paragraphs), instructions (ordered list or imperative paragraphs), and metadata (yield, times via regex). Detect ingredient subheaders like "For the sauce" and preserve them. Convert each extracted candidate to a RecipeCandidate model and then to RecipeSage JSON-LD.

Milestone 4 handles edge cases and LLM escalation. Detect recipes embedded as images (low text density with image blocks) and flag them for future OCR integration. Handle multi-recipe pages where short bold lines introduce mini-recipes. Implement optional LLM escalation for low-confidence candidates: send block text to an LLM with a constrained schema asking it to identify section boundaries, validate output with Pydantic, and merge results.

Milestone 5 adds tests, fixtures, and documentation. Create fixture EPUB files under tests/fixtures/epub/ covering: single-recipe-per-chapter, multiple-recipes-per-chapter, mixed content with narrative, and edge cases like image-heavy pages. Add golden outputs and pytest tests. Document usage in a short note in cookimport/plugins/README.md.

## Concrete Steps

Work from /home/mcnal/projects/recipeimport with the virtual environment activated.

Install additional dependencies for EPUB parsing:

    pip install beautifulsoup4 lxml ebooklib

Create the EPUB importer file:

    touch cookimport/plugins/epub.py

Register the importer in the plugin registry by adding it to cookimport/plugins/__init__.py.

Run tests after implementation:

    pytest tests/test_epub_importer.py

Run the CLI to verify:

    cookimport inspect tests/fixtures/epub/sample_cookbook.epub
    cookimport stage tests/fixtures/epub --out data/output/epub_test

## Validation and Acceptance

The change is accepted when: Running cookimport inspect on a fixture EPUB prints chapter/recipe counts, detected layout, and writes a mapping stub. Running cookimport stage on an EPUB folder produces JSON-LD files at staging/recipesage_jsonld/<book>/<recipe>.json and a report at staging/reports/<book>.epub_import_report.json. Each JSON-LD includes @id, name, recipeIngredient, recipeInstructions, and provenance with source file, chapter, and block range. The report lists recipe counts, low-confidence candidates, and skipped content. Pytest tests pass and verify block extraction, candidate detection, and field extraction against fixtures.

## Idempotence and Recovery

The stage command computes a stable @id as urn:recipeimport:epub:<file_hash>:<recipe_slug> so reruns overwrite the same outputs. The DocPack intermediate files in work/<book_id>/ allow resuming from block extraction without re-parsing the EPUB. If extraction fails for one file, the CLI continues to others and logs the error in the report.

## Artifacts and Notes

Example block in blocks.jsonl:

    {
      "spine_idx": 3,
      "block_idx": 42,
      "type": "heading",
      "heading_level": 2,
      "text": "Classic Tomato Soup",
      "html": "<h2>Classic Tomato Soup</h2>",
      "features": {
        "looks_like_recipe_title": true,
        "has_qty_unit_pattern": false
      }
    }

Example candidate detection output:

    {
      "candidate_id": "ch3-r1",
      "start_block_idx": 42,
      "end_block_idx": 67,
      "title_guess": "Classic Tomato Soup",
      "confidence": 0.85,
      "reasons": ["has_title_heading", "has_ingredient_section", "has_instruction_section"]
    }

## Interfaces and Dependencies

Dependencies: beautifulsoup4 for HTML/XHTML parsing, lxml as parser backend, ebooklib for EPUB metadata access (optional, can use direct unzip), calibre CLI as optional fallback for format conversion.

In cookimport/plugins/epub.py, implement:

    from pathlib import Path
    from cookimport.plugins.base import Importer
    from cookimport.core.models import WorkbookInspection, MappingConfig, ConversionResult

    class EpubImporter:
        name = "epub"

        def detect(self, path: Path) -> float:
            """Return 0.9 for .epub files, 0.0 otherwise."""
            ...

        def inspect(self, path: Path) -> WorkbookInspection:
            """Extract DocPack, detect candidates, return summary."""
            ...

        def convert(self, path: Path, mapping: MappingConfig | None) -> ConversionResult:
            """Full extraction, candidate detection, field extraction, JSON-LD emission."""
            ...

        def _extract_docpack(self, path: Path, work_dir: Path) -> Path:
            """Unzip EPUB, parse spine, emit blocks.jsonl to work_dir."""
            ...

        def _detect_candidates(self, blocks_path: Path) -> list[dict]:
            """Scan blocks.jsonl, return candidate slices with confidence."""
            ...

        def _extract_fields(self, blocks: list[dict], candidate: dict) -> RecipeCandidate:
            """Extract title, ingredients, instructions, metadata from block slice."""
            ...

The Block schema includes: spine_idx (int), block_idx (int), type (str: heading/paragraph/list_item/table/image), heading_level (int or None), text (str), html (str), features (dict of computed signals), source_path (str).

Feature computation functions should be in a separate module cookimport/parsing/block_features.py for reuse across PDF and text importers.
