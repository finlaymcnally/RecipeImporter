# Recommended Implementation Order

This document outlines the recommended sequence for building the import engine components. The order prioritizes shared foundations to minimize code duplication, followed by importers in increasing order of complexity.

## Phase 1: Foundations (The Shared Toolkit)

Build these first. They define the "language" that all specific importers will speak.

1.  **Reporting & Provenance (`PROCESS-reporting-and-provenance.md`)**
    *   *Why:* Defines the `RecipeCandidate` output structure and the `urn:recipeimport:...` identity scheme. All importers need this to save their work.

2.  **Common Parsing & Normalization (`PROCESS-common-parsing-and-normalization.md`)**
    *   *Why:* Implements the text cleaning (fixing mojibake) and "signal detection" (identifying ingredients vs steps) used by Text, EPUB, and PDF.

3.  **LLM Repair Infrastructure (`PROCESS-llm-repair.md`)**
    *   *Why:* Sets up the API client and prompts for "surgical repair." Importers will need to call this when heuristics fail.

## Phase 2: Importers (Unstructured Data)

Build these to validate the toolkit.

4.  **Text Importer (`IMPORT-text-importer-execplan.md`)**
    *   *Why:* The simplest unstructured format. Perfect for testing your normalization and signal detection logic without the noise of HTML tags or PDF bounding boxes.

5.  **EPUB Importer (`IMPORT-epub-importer-execplan.md`)**
    *   *Why:* Adds the complexity of HTML structure (DOM walking) on top of the text logic.

6.  **PDF Importer (`IMPORT-pdf-importer-execplan.md`)**
    *   *Why:* The most complex. Requires layout analysis (columns, blocks) which feeds into the same signal detection logic used above.

## Phase 3: Structured Data & Refinement

7.  **Excel Importer (`IMPORT-excel-import-engine-execplan.md`)**
    *   *Note:* Largely independent of the unstructured stack. Can be built in parallel or effectively already in progress.

8.  **Ingredient Parser Integration (`PROCESS1-ingredient-parser-integration.md`)**
    *   *Why:* Adds structured detail (quantity/unit/food) to the raw strings extracted by the importers.

9.  **Ingredient-Step Linking (`PROCESS2-ingredient-step-linking-execplan.md`)**
    *   *Why:* Advanced semantic enrichment. Depends on reliable ingredient parsing.
