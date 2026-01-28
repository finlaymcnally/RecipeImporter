---
summary: "AI Onboarding & Project Summary for the cookimport project."
read_when:
  - When an AI agent or new developer needs a technical overview of the architecture, tech stack, and data flow
---

# AI Onboarding & Project Summary: Recipe Import Pipeline

This document provides a technical overview of the `cookimport` project. It is designed to help AI developers understand the current architecture, data flow, and dependencies.

## 1. Project Purpose
The goal of this project is to autonomously ingest recipes from various "messy" real-world sources (Excel, EPUB, PDF, Text, etc.) and normalize them into a structured staging format (RecipeSage JSON-LD or custom Draft V1).

## 2. Tech Stack & Active Dependencies

The project is built with **Python 3.10+**. The following libraries are actively used in the current pipeline:

### Core Frameworks
*   **[Typer](https://typer.tiangolo.com/):** Powers the CLI interface (`cookimport/cli.py`).
*   **[Pydantic V2](https://docs.pydantic.dev/):** Used for data validation and schema enforcement (`cookimport/core/models.py`).
*   **[Questionary](https://questionary.readthedocs.io/):** Handles interactive CLI prompts in the `cookimport` interactive mode.

### Specialized Parsers (Production Use)
*   **[Ingredient Parser](https://github.com/strangetom/ingredient-parser) ([Docs](https://ingredient-parser.readthedocs.io/en/latest/)):** Decomposes raw ingredient strings into structured components (`cookimport/parsing/ingredients.py`).
*   **[PyMuPDF (fitz)](https://pymupdf.readthedocs.io/):** High-performance PDF text and layout extraction (`cookimport/plugins/pdf.py`).
*   **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) & [lxml](https://lxml.de/):** HTML cleaning and traversal for EPUB content.
*   **[EbookLib](https://github.com/aerkalov/ebooklib):** Manages EPUB container structures (`cookimport/plugins/epub.py`).
*   **[Openpyxl](https://openpyxl.readthedocs.io/):** Primary engine for `.xlsx` ingestion, including complex layout detection (`cookimport/plugins/excel.py`).
*   **[python-docx](https://python-docx.readthedocs.io/):** Extracts text and tables from Word documents (`cookimport/plugins/text.py`).

### Utilities
*   **[PyYAML](https://pyyaml.org/):** Parses recipe frontmatter and mapping configuration files.
*   **[Rich](https://rich.readthedocs.io/):** Installed as a dependency (via Typer) but primarily used for terminal formatting.

## 3. Data Flow & Processing Stages

### Stage 1: Ingestion & Discovery (`cookimport stage`)
1.  **Detection:** Plugins (EPUB, PDF, Excel, Text) score their confidence in handling a file.
2.  **Inspection:** The chosen plugin analyzes the internal layout (e.g., detecting if an Excel sheet is a "Wide Table", "Tall", or "Template").
3.  **Extraction:** Raw text or rows are extracted as "Recipe Candidates".
4.  **Provenance:** Every candidate is tagged with a hash and specific location metadata (row, line, or chunk) for 100% traceability.

### Stage 2: Structural Normalization
Raw chunks are segmented into `name`, `description`, `ingredients`, and `instructions` using deterministic heuristics (regex for yield phrases, heading detection, block classification).

### Stage 3: Component Parsing
*   **Ingredients:** Lines are parsed into structured JSON fields (quantity, unit, item, etc.).
*   **Tips/Knowledge:** `cookimport/parsing/tips.py` uses a taxonomy and heuristics to identify standalone kitchen tips, classifying them as `general` or `recipe_specific`.

### Stage 4: Staging & Reporting
*   **Output Formats:** Files are written to `intermediate drafts/` (JSON-LD) and `final drafts/` (Draft V1).
*   **Traceability:** A `reports/` JSON file is generated for every run, summarizing performance and missing fields.

---

## 4. Current Status: Active vs. Planned

| Feature | Status | Notes |
| :--- | :--- | :--- |
| **Excel Ingestion** | **Active** | Supports Wide, Tall, and Template layouts. |
| **EPUB/PDF/Text** | **Active** | Heuristic-based segmentation is functional. |
| **Ingredient Parsing** | **Active** | Powered by `Ingredient Parser`. |
| **Tip Extraction** | **Active** | Heuristic classification and taxonomy tagging. |
| **LLM Repair** | **Mocked** | `cookimport/llm/` exists but currently uses mock responses. |
| **Unstructured.io** | **Planned** | Mentioned in plans but not yet integrated. |
| **Amazon Textract** | **Planned** | For difficult OCR cases, not yet implemented. |

## 5. Directory Map
*   `cookimport/core/`: The Engine (Models, Reporting, Registry).
*   `cookimport/plugins/`: The Adapters (Source-specific extraction).
*   `cookimport/parsing/`: The Brains (Ingredient and Tip logic).
*   `cookimport/staging/`: The Output (Writers and formatting).
*   `cookimport/llm/`: Mocked LLM integration layer.
*   `tests/`: Comprehensive test suite for all importers and parsers.