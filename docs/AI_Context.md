---
summary: "AI Onboarding & Project Summary for the cookimport project."
read_when:
  - When an AI agent or new developer needs a technical overview of the architecture, tech stack, and data flow
  - When you need to understand how recipe ingestion and parsing works in this codebase
---

# AI Onboarding & Project Summary: Recipe Import Pipeline

This document provides a technical overview of the `cookimport` project. It is designed to help AI developers and AI chatbots (who may not have direct access to the codebase) understand the architecture, data flow, and key algorithms.

## 1. Project Purpose

The `cookimport` project is a **recipe ingestion and normalization pipeline** that transforms messy, real-world recipe sources into structured, high-fidelity data. It handles:

- **Legacy Excel spreadsheets** with varying layouts (wide, tall, template-based)
- **EPUB cookbooks** with unstructured text requiring segmentation
- **PDF documents** (including scanned images with OCR)
- **Proprietary app archives**: Paprika (.paprikarecipes) and RecipeSage (.zip/JSON)
- **Plain text/Word documents**

### Key Objectives

1. **Universal Ingestion**: Handle diverse formats and layouts through a plugin-based architecture where each source type has a dedicated importer.

2. **Two-Phase Pipeline**:
   - **Phase 1 (Ingestion)**: Extract raw content and normalize to an intermediate **schema.org Recipe JSON** format.
   - **Phase 2 (Transformation)**: Parse ingredients into structured fields, link ingredients to instruction steps, and produce the final **cookbook3** format (internal model name: `RecipeDraftV1`).

3. **100% Traceability**: Every output field is traceable back to its source via a `provenance` metadata system that records file hashes, block indices, and extraction methods.

4. **Knowledge Extraction**: Beyond recipe scraping, the system identifies and extracts standalone "Kitchen Tips" and topical content.

## 2. Tech Stack & Active Dependencies

The project is built with **Python 3.12**. Key libraries:

### Core Frameworks
| Library | Purpose |
|---------|---------|
| **[Typer](https://typer.tiangolo.com/)** | Powers the CLI interface (`cookimport`, `C3imp`, `C3import` commands) |
| **[Pydantic V2](https://docs.pydantic.dev/)** | Strict data validation, schema enforcement, and JSON serialization for all models |
| **[Rich](https://rich.readthedocs.io/)** | Console output formatting, progress spinners, and status updates during processing |
| **[Questionary](https://questionary.readthedocs.io/)** | Interactive CLI prompts for guided workflows |

### Specialized Parsers (Production Use)
| Library | Purpose |
|---------|---------|
| **[Ingredient Parser](https://ingredient-parser.readthedocs.io/)** | NLP-based decomposition of ingredient strings into quantity, unit, item, preparation, and notes |
| **[PyMuPDF (fitz)](https://pymupdf.readthedocs.io/)** | High-performance PDF text and layout extraction |
| **[python-doctr](https://mindee.github.io/doctr/)** | Deep learning OCR for scanned PDFs (uses CRNN + ResNet architectures) |
| **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) + [lxml](https://lxml.de/)** | HTML parsing for EPUB content and app archive formats |
| **[EbookLib](https://github.com/aerkalov/ebooklib)** | EPUB container structure management with fallback to raw ZIP parsing |
| **[Openpyxl](https://openpyxl.readthedocs.io/)** | Excel file processing with complex layout detection |
| **[python-docx](https://python-docx.readthedocs.io/)** | Word document text and table extraction |

### Quality Assurance & Evaluation
| Library | Purpose |
|---------|---------|
| **[Label Studio SDK](https://labelstud.io/)** | Creating ground-truth datasets for benchmarking parser accuracy |

## 3. Architecture Overview

### 3.1 Plugin System

The project uses a **registry-based plugin architecture** where each source format has a dedicated importer class:

```
cookimport/plugins/
  ├── registry.py      # Plugin registry with best_importer_for_path()
  ├── epub.py          # EPUB cookbook importer
  ├── pdf.py           # PDF document importer
  ├── excel.py         # Excel spreadsheet importer
  ├── paprika.py       # Paprika app archive importer
  ├── recipesage.py    # RecipeSage JSON archive importer
  └── text.py          # Plain text / Word document importer
```

Each plugin implements:
- `detect(path) -> float`: Returns confidence score (0.0-1.0) that this plugin can handle the file
- `inspect(path) -> WorkbookInspection`: Quick analysis of file structure
- `convert(path, mapping, progress_callback) -> ConversionResult`: Full extraction

### 3.2 Core Data Models

The system uses Pydantic models for type-safe data flow (see `cookimport/core/models.py`):

| Model | Purpose |
|-------|---------|
| `RecipeCandidate` | Intermediate format (schema.org Recipe JSON-compatible) with name, ingredients, instructions, metadata |
| `TipCandidate` | Extracted kitchen tip with scope (general, recipe_specific, not_tip) and taxonomy tags |
| `TopicCandidate` | Topical content block (sections about techniques, ingredient guides, etc.) |
| `ConversionResult` | Container for recipes, tips, topics, raw artifacts, and conversion report |
| `Block` | Low-level text block with type, HTML source, font weight, and feature flags |

### 3.3 Block, Candidate, and Chunk Vocabulary

These three terms are easy to confuse, so this is the practical definition used in code:

- `Block` (`cookimport/core/blocks.py`):
  - The shared low-level text unit used during extraction from unstructured sources.
  - Typical fields: `text`, `type`, `page`, `bbox`, `font_size`, `font_weight`, `alignment`, `features`.
  - Think: one paragraph/list/header line plus layout/style metadata.

- `RecipeCandidate` (`cookimport/core/models.py`):
  - A segmented recipe record in schema-like form (`name`, `recipeIngredient`, `recipeInstructions`, `provenance`, etc.).
  - Produced by importers after they decide which block ranges are recipes.

- `KnowledgeChunk` (`cookimport/core/models.py`, created by `cookimport/parsing/chunks.py`):
  - A coherent non-recipe text region used for knowledge extraction.
  - Built from `nonRecipeBlocks` after recipe ranges are removed.
  - Contains lane (`knowledge`/`noise`), `sectionPath`, boundary reasons, highlights, and tags.

### 3.4 Block & Signals Architecture

For EPUB/PDF (and line-based text heuristics), extraction relies on a linear content stream + signal enrichment:

1. **Block extraction**
   - EPUB: HTML spine documents -> block tags (`h1..h6`, `p`, `li`, etc.) -> `Block`.
   - PDF: PyMuPDF line extraction (or docTR OCR) -> `Block` with page/bbox/style metadata.

2. **Signal enrichment** (`cookimport/parsing/signals.py`)
   - Each block is annotated with features used by segmentation/parsing:
   - `is_heading`, `heading_level`
   - `is_ingredient_header`, `is_instruction_header`
   - `is_yield`, `is_time`
   - `starts_with_quantity`, `has_unit`
   - `is_instruction_likely`, `is_ingredient_likely`

3. **Recipe segmentation**
   - Importers compute candidate ranges (`start_block`, `end_block`, `segmentation_score`) over the block stream.
   - Each range becomes one `RecipeCandidate` after field extraction.

## 4. Key Algorithms

### 4.1 Ingredient-Step Linking (Two-Phase Algorithm)

The step-ingredient linking algorithm (`cookimport/parsing/step_ingredients.py`) assigns each ingredient to the instruction step(s) where it's used:

**Phase 1: Candidate Collection**
- For each step, scan for mentions of each ingredient using multiple aliases (full text, cleaned text, head/tail tokens)
- Classify verb context: "use" verbs (add, mix, stir), "reference" verbs (cook, let rest), "split" signals (half, remaining)
- Score matches based on alias length, token overlap, and context

**Phase 2: Resolution**
- Default: Single best step wins (highest score)
- Exception: Multi-step assignment when split language detected ("add half the butter... add remaining butter")
- Fraction calculation for split ingredients (e.g., 0.5 each for "half/remaining" pattern)

This approach handles:
- Section headers grouping ingredients (e.g., "For the Sauce")
- "All ingredients" phrases that assign everything to a step
- Weak match filtering to avoid false positives

### 4.2 Ingredient Parsing

The ingredient parser (`cookimport/parsing/ingredients.py`) wraps the `ingredient-parser-nlp` library:

```python
"3 stalks celery, sliced" -> {
    "quantity_kind": "exact",
    "input_qty": 3.0,
    "raw_unit_text": "stalks",
    "raw_ingredient_text": "celery",
    "preparation": "sliced",
    "is_optional": False,
    "confidence": 0.92
}
```

Special handling for:
- Section headers (e.g., "MARINADE:", "For the Filling")
- Range quantities (e.g., "3-4 cups" -> midpoint rounded up)
- Approximate quantities ("to taste", "as needed")

### 4.3 Variant Extraction

Recipes may contain variant instructions. The system (`cookimport/staging/draft_v1.py`) extracts these:

- Detects "Variation:" or "Variant:" headers
- Separates variant content from main instructions
- Stores variants as a separate array in the recipe output

### 4.4 Tip Classification

Tips are classified by scope (`cookimport/parsing/tips.py`):
- **general**: Standalone kitchen wisdom (reusable across recipes)
- **recipe_specific**: Notes tied to a particular recipe
- **not_tip**: Content that looks like a tip but isn't (copyright notices, ads)

## 5. Data Flow & Processing Stages (Detailed)

### 5.1 End-to-end walkthrough: importing one EPUB

When you run `cookimport stage data/input/book.epub`, the concrete flow is:

1. **Importer selection**
   - `registry.best_importer_for_path()` picks `EpubImporter` based on `detect()` score.

2. **Inspect (optional)**
   - `EpubImporter.inspect()` reads spine metadata and returns `WorkbookInspection` + mapping stub.

3. **Convert**
   - `EpubImporter.convert()` computes file hash and extracts a linear block stream via `_extract_docpack(...)`.
   - Each block gets normalized text + signal features.
   - Raw artifact `full_text` is recorded as extracted blocks JSON.

4. **Recipe candidate segmentation**
   - `_detect_candidates(blocks)` returns candidate ranges over block indices.
   - For each range, `_extract_fields(...)` builds a `RecipeCandidate` and provenance.
   - Stable IDs are assigned if missing (based on source hash + chunk index semantics).

5. **Tip/topic candidate extraction**
   - Recipe-local tip candidates come from `extract_tip_candidates_from_candidate(...)`.
   - Standalone (non-recipe) text is atomized and mined for tip/topic candidates.

6. **Non-recipe block capture**
   - Blocks not covered by recipe ranges are collected as `nonRecipeBlocks`.
   - This is the main input to chunking later.

7. **Return unified conversion payload**
   - Importer returns one `ConversionResult` containing recipes, tip candidates, topic candidates, non-recipe blocks, raw artifacts, and report metrics.

8. **Shared post-import stage path (all formats)**
   - In `cli_worker.stage_one_file(...)`, chunking runs from `nonRecipeBlocks` when present.
   - Writers emit:
   - intermediate schema.org Recipe JSON (`intermediate drafts/<workbook>/r{index}.jsonld`)
   - final cookbook3 (`final drafts/<workbook>/r{index}.json`)
   - tips/topics/chunks/raw/report

### 5.2 What determines blocks, candidates, and chunks

- **Blocks** are determined by importer-specific extraction rules:
  - EPUB uses HTML structure.
  - PDF uses visual text lines (or OCR lines) plus layout reordering.
  - Text importer mostly works line/chunk-first and does not build the same persisted `nonRecipeBlocks` stream.

- **Recipe candidates** are determined by segmentation heuristics over ordered content:
  - Yield anchors, ingredient/instruction headers, title backtracking, and boundary checks.
  - Candidate quality is scored (`score_recipe_candidate`), and provenance captures location ranges.

- **Chunks** are determined after recipe segmentation:
  - Input: only non-recipe content (`nonRecipeBlocks`) or fallback topic candidates.
  - Engine: `cookimport/parsing/chunks.py`.
  - Boundary drivers: heading levels, callout starts (`TIP:`, `NOTE:`), format-mode changes (prose/list), max-char limits, and stop headings (index/credits/etc.).
  - Lane assignment: chunk lanes are classified and written as `knowledge` or `noise` behavior in outputs.
  - Highlights inside chunks are mined with tip extraction logic and stored with offsets/block IDs.

### 5.3 Where file-type behavior differs

Before convergence, importer behavior is format-specific:

- **EPUB (`plugins/epub.py`)**
  - Parses EPUB spine documents and HTML blocks.
  - Carries `spine_index` features for deterministic ordering and split-job merges.

- **PDF (`plugins/pdf.py`)**
  - Uses PyMuPDF text extraction and column ordering.
  - Falls back to docTR OCR for scanned pages.
  - Preserves `page`, `bbox`, and OCR confidence metadata in blocks/provenance.

- **Text/Markdown/Word (`plugins/text.py`)**
  - Splits by markdown headers, yield lines, or table layouts (DOCX tables).
  - Produces `RecipeCandidate` records directly from text chunks/rows.

- **Excel (`plugins/excel.py`)**
  - Layout detection (`wide-table`, `tall`, `template`) then row/cell normalization.
  - Provenance is row/sheet-centric, not block-centric.

- **Paprika/RecipeSage (`plugins/paprika.py`, `plugins/recipesage.py`)**
  - Parse structured exports (ZIP/GZIP JSON or JSON objects).
  - Less segmentation work because source is already near recipe schema.

### 5.4 Where all file types converge

Convergence happens in two major places:

1. **Common conversion contract**
   - Every importer returns the same `ConversionResult` model.
   - This lets stage orchestration and writers treat all importers uniformly.

2. **Common writer/transform path**
   - `write_intermediate_outputs(...)`: recipe candidates -> JSON-LD.
   - `write_draft_outputs(...)`: each `RecipeCandidate` -> `recipe_candidate_to_draft_v1(...)`.
   - During cookbook3 conversion, all sources go through the same:
   - ingredient parsing (`parse_ingredient_line`)
   - instruction metadata extraction (`parse_instruction`)
   - ingredient-step linking (`assign_ingredient_lines_to_steps`)
   - variant extraction and draft shaping

So: EPUB/PDF are very different early (block extraction + segmentation), but once they emit `RecipeCandidate`, they follow the same downstream transformation and output contracts as Excel/text/app exports.

### 5.5 Split-job behavior (PDF/EPUB only)

For large sources, PDF/EPUB can be split into page/spine jobs:

- workers convert ranges in parallel and emit mergeable results,
- main process merges candidates, rebases IDs/order, merges raw artifacts, then writes once,
- chunk generation happens after merge on the unified non-recipe stream.

This preserves one global coordinate space (`start_page`/`start_spine` + block ordering) across the final run outputs.

## 6. Label Studio Integration

The project includes deep integration with Label Studio for building ground-truth datasets:

### Chunking Strategies
- **Structural Chunks**: Recipe-level units for validating segmentation
- **Atomic Chunks**: Line-level units for validating ingredient parsing

### Workflow
1. `cookimport labelstudio-import`: Upload chunks to Label Studio project
2. Annotate in Label Studio UI
3. `cookimport labelstudio-export`: Export labeled data as JSONL golden set

## 7. Current Status

| Feature | Status | Notes |
|---------|--------|-------|
| Excel Ingestion | **Active** | Wide, Tall, and Template layouts |
| App Archives | **Active** | Paprika and RecipeSage support |
| EPUB/PDF/Text | **Active** | Heuristic segmentation with variant extraction |
| OCR (docTR) | **Active** | For scanned PDFs, uses CRNN + ResNet |
| Ingredient Parsing | **Active** | NLP-based with confidence scores |
| Step-Ingredient Linking | **Active** | Two-phase algorithm with split detection |
| Tip Extraction | **Active** | Taxonomy tagging and scope classification |
| Label Studio | **Active** | Benchmarking and dataset export |
| LLM Repair | **Mocked** | Structure exists, calls return mock data |

## 8. Directory Map

```
cookimport/
├── core/           # Engine: Models, Reporting, Registry, Scoring
├── plugins/        # Adapters: Source-specific extraction (Excel, EPUB, etc.)
├── parsing/        # Brains: Ingredient parsing, Tip taxonomy, Step linking
│   ├── ingredients.py      # Ingredient line parsing
│   ├── step_ingredients.py # Two-phase step linking
│   ├── signals.py          # Block feature enrichment
│   ├── tips.py             # Tip extraction and classification
│   └── atoms.py            # Atomic text unit handling
├── staging/        # Output: Writers, schema.org intermediate, cookbook3 final
├── labelstudio/    # Benchmarking: Chunking, client, export
├── llm/            # (Mocked) LLM integration layer
└── ocr/            # docTR OCR engine for scanned documents

data/
├── input/          # Place source files here
└── output/         # Generated outputs appear here

tests/              # Comprehensive test suite
```

## 9. CLI Commands

| Command | Purpose |
|---------|---------|
| `cookimport` | Interactive mode with guided prompts |
| `cookimport stage <path>` | Stage recipes from file/folder |
| `cookimport perf-report` | Summarize per-file timing and append to `data/output/.history/performance_history.csv` |
| `cookimport inspect <path>` | Preview file structure and layout |
| `cookimport labelstudio-import` | Upload to Label Studio |
| `cookimport labelstudio-export` | Export labeled data |

Environment variables:
- `C3IMP_LIMIT`: Limit recipes per file (for testing)
- `LABEL_STUDIO_URL`: Label Studio server URL
- `LABEL_STUDIO_API_KEY`: Label Studio API key
