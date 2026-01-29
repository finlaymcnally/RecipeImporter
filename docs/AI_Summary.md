---
summary: "AI Onboarding & Project Summary for the cookimport project."
read_when:
  - When an AI agent or new developer needs a technical overview of the architecture, tech stack, and data flow
---

# AI Onboarding & Project Summary: Recipe Import Pipeline

This document provides a technical overview of the `cookimport` project. It is designed to help AI developers understand the current architecture, data flow, and dependencies.

## 1. Project Purpose
The goal of the `cookimport` project is to autonomously ingest recipes from various "messy" real-world sources—legacy Excel spreadsheets, EPUB cookbooks, PDFs, and proprietary app archives (Paprika, RecipeSage)—and normalize them into a high-fidelity, structured format.

Key objectives include:
*   **Universal Ingestion:** Handling diverse layouts (e.g., "Wide" vs "Tall" spreadsheets) and unstructured text streams.
*   **Two-Phase Pipeline:**
    1.  **Ingestion:** Extracting raw content and normalizing it into a standard intermediate format (RecipeSage JSON-LD).
    2.  **Transformation:** Parsing ingredients, linking steps, and structuring metadata into a final `RecipeDraftV1` format.
*   **100% Traceability:** Every output field must be traceable back to its source file, row, and column via a robust `provenance` metadata system.
*   **Knowledge Extraction:** Going beyond simple recipe scraping to identify and extract standalone "Kitchen Tips" and technique knowledge.

## 2. Tech Stack & Active Dependencies

The project is built with **Python 3.12**. The following libraries are actively used in the current pipeline:

### Core Frameworks
*   **[Typer](https://typer.tiangolo.com/):** Powers the CLI interface (`cookimport/cli.py`).
*   **[Pydantic V2](https://docs.pydantic.dev/):** Used for strict data validation, schema enforcement, and JSON serialization (`cookimport/core/models.py`).
*   **[Questionary](https://questionary.readthedocs.io/):** Handles interactive CLI prompts.

### Specialized Parsers (Production Use)
*   **[Ingredient Parser](https://github.com/strangetom/ingredient-parser) ([Docs](https://ingredient-parser.readthedocs.io/en/latest/)):** Decomposes raw ingredient strings into structured components (`cookimport/parsing/ingredients.py`).
*   **[PyMuPDF (fitz)](https://pymupdf.readthedocs.io/):** High-performance PDF text and layout extraction (`cookimport/plugins/pdf.py`).
*   **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) & [lxml](https://lxml.de/):** HTML cleaning/traversal for EPUB and Paprika/RecipeSage content.
*   **[EbookLib](https://github.com/aerkalov/ebooklib):** Manages EPUB container structures (`cookimport/plugins/epub.py`).
*   **[Openpyxl](https://openpyxl.readthedocs.io/):** Primary engine for `.xlsx` ingestion, including complex layout detection (`cookimport/plugins/excel.py`).
*   **[python-docx](https://python-docx.readthedocs.io/):** Extracts text and tables from Word documents (`cookimport/plugins/text.py`).

### Quality Assurance & Evaluation
*   **[Label Studio SDK](https://labelstud.io/):** Used for creating and syncing ground-truth datasets for benchmarking parser accuracy (`cookimport/labelstudio/`).

## 3. Data Flow & Processing Stages

### Stage 1: Ingestion & Discovery (`cookimport stage`)
1.  **Detection:** Plugins (EPUB, PDF, Excel, Paprika, etc.) score their confidence in handling a file.
2.  **Inspection:** The chosen plugin analyzes the internal layout (e.g., detecting Excel "template" rows).
3.  **Extraction:** Raw text/rows are extracted as `RecipeCandidate` objects.
4.  **Provenance:** Every candidate is tagged with a hash and specific location metadata.
5.  **Intermediate Output:** Data is saved as JSON-LD in `data/output/.../intermediate drafts/`.

### Stage 2: Structural Normalization
Raw chunks are segmented into `name`, `description`, `ingredients`, and `instructions` using deterministic heuristics (regex for yield phrases, heading detection, block classification).

### Stage 3: Component Parsing
*   **Ingredients:** Lines are parsed into structured JSON fields (quantity, unit, item, etc.).
*   **Step Linking:** Ingredients are semantically linked to the instruction steps where they are used.
*   **Tips/Knowledge:** `cookimport/parsing/tips.py` uses a taxonomy and heuristics to identify standalone kitchen tips, classifying them as `general` or `recipe_specific`.

### Stage 4: Staging & Reporting
*   **Final Output:** Fully structured recipes are written to `final drafts/` (Draft V1 Schema).
*   **Reporting:** A `reports/` JSON file is generated for every run, summarizing performance and missing fields.

---

## 4. Current Status: Active vs. Planned

| Feature | Status | Notes |
| :--- | :--- | :--- |
| **Excel Ingestion** | **Active** | Supports Wide, Tall, and Template layouts. |
| **App Archives** | **Active** | Supports **Paprika** (.paprikarecipes) and **RecipeSage** (.zip/JSON) imports. |
| **EPUB/PDF/Text** | **Active** | Heuristic-based segmentation is functional. |
| **Ingredient Parsing** | **Active** | Powered by `Ingredient Parser`. |
| **Tip Extraction** | **Active** | Heuristic classification and taxonomy tagging. |
| **Label Studio** | **Active** | Integrated for benchmarking and dataset export. |
| **LLM Repair** | **Mocked** | `cookimport/llm/` structure exists; calls return mock data. |
| **Unstructured.io** | **Planned** | Mentioned in plans but not yet integrated. |
| **Amazon Textract** | **Planned** | For difficult OCR cases, not yet implemented. |

## 5. Directory Map
*   `cookimport/core/`: The Engine (Models, Reporting, Registry).
*   `cookimport/plugins/`: The Adapters (Source-specific extraction: Excel, EPUB, Paprika, etc.).
*   `cookimport/parsing/`: The Brains (Ingredient parsing, Tip taxonomy, Step linking).
*   `cookimport/staging/`: The Output (Writers, JSON-LD, Draft V1).
*   `cookimport/labelstudio/`: Benchmarking and Ground Truth dataset management.
*   `cookimport/llm/`: Mocked LLM integration layer.
*   `tests/`: Comprehensive test suite for all importers and parsers.
