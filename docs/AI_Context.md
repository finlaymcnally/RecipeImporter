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
   - **Phase 1 (Ingestion)**: Extract raw content and normalize to an intermediate JSON-LD format based on schema.org Recipe.
   - **Phase 2 (Transformation)**: Parse ingredients into structured fields, link ingredients to instruction steps, and produce the final `RecipeDraftV1` format.

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
| `RecipeCandidate` | Intermediate format (schema.org JSON-LD compatible) with name, ingredients, instructions, metadata |
| `TipCandidate` | Extracted kitchen tip with scope (general, recipe_specific, not_tip) and taxonomy tags |
| `TopicCandidate` | Topical content block (sections about techniques, ingredient guides, etc.) |
| `ConversionResult` | Container for recipes, tips, topics, raw artifacts, and conversion report |
| `Block` | Low-level text block with type, HTML source, font weight, and feature flags |

### 3.3 Block & Signals Architecture

For unstructured sources (EPUB, PDF, text), the pipeline uses a **Block-based extraction model**:

1. **Block Extraction**: Source content is converted to a linear sequence of `Block` objects, each representing a paragraph, heading, or list item.

2. **Signal Enrichment** (`cookimport/parsing/signals.py`): Each block is analyzed for features:
   - `is_heading`, `heading_level` - Typography signals
   - `is_ingredient_header`, `is_instruction_header` - Section markers
   - `is_yield`, `is_time` - Metadata phrases
   - `starts_with_quantity`, `has_unit` - Ingredient signals
   - `is_instruction_likely`, `is_ingredient_likely` - Content classification

3. **Candidate Detection**: Blocks are segmented into recipe candidates using heuristics:
   - Backtracking from anchor points (yield phrases, ingredient headers)
   - Forward scanning with section boundary detection
   - Scoring based on ingredient/instruction density

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

## 5. Data Flow & Processing Stages

### Stage 1: Ingestion (`cookimport stage` command)
1. **Detection**: Plugins score confidence for handling the file
2. **Inspection**: Analyze internal structure (layout, headers, sections)
3. **Extraction**: Convert to `RecipeCandidate` objects with provenance
4. **Raw Artifacts**: Store extracted blocks as JSON for auditing

### Stage 2: Transformation
1. **Ingredient Parsing**: Lines parsed into structured components
2. **Instruction Parsing**: Extract time/temperature metadata
3. **Step Linking**: Assign ingredients to steps
4. **Tip Extraction**: Identify standalone tips and topics

### Stage 3: Output
- **Intermediate Drafts**: JSON-LD format in `{timestamp}/intermediate drafts/`
- **Final Drafts**: RecipeDraftV1 format in `{timestamp}/final drafts/`
- **Tips**: Extracted tips in `{timestamp}/tips/`
- **Reports**: Conversion summary with stats and warnings

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
├── staging/        # Output: Writers, JSON-LD, Draft V1
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
