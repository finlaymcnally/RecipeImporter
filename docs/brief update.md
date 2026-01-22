# Brief Update: Current System Status vs. Overall Plan

## Executive Summary
The current implementation of the `cookimport` CLI deviates from the original architectural plan. While the system successfully processes Excel files and outputs structured data, it combines two distinct phases into a single execution step, skipping the intermediate file generation that was originally specified.

## Original Plan vs. Current Reality

### Original Plan (Architectural Goal)
The system was designed to operate as a two-phase pipeline:
1.  **Ingestion Phase:** 
    *   **Input:** Source files (e.g., Excel, PDF, EPUB).
    *   **Action:** Extract raw content and normalize it.
    *   **Output:** **Intermediate RecipeSage JSON-LD files** saved to disk.
2.  **Transformation Phase:**
    *   **Input:** Intermediate RecipeSage JSON-LD files.
    *   **Action:** Apply detailed parsing, validation, and schema conversion.
    *   **Output:** **Final Database Format (DraftV1)**.

### Current Implementation (How it Works Now)
The system currently performs a "direct-to-final" conversion in a single pass:
1.  **Combined Execution:**
    *   **Input:** Excel file.
    *   **Action:** 
        1.  Extracts raw data into an in-memory object (`RecipeCandidate`).
        2.  Immediately applies NLP parsing and structure conversion.
        3.  Converts directly to the final schema (`RecipeDraftV1`).
    *   **Output:** Final DraftV1 JSON files saved to `staging/drafts/`.

**Critique:** The "RecipeSage JSON-LD" data model (`RecipeCandidate`) exists only transiently in memory. It is never serialized to disk as an intermediate artifact, meaning Phase 2 (Transformation) cannot be run independently or on data from other sources.

## Detailed Data Flow Analysis

The current single-pass process consists of 5 internal stages:

1.  **Inspection (Layout Detection)**
    *   **Input:** `.xlsx` File.
    *   **Action:** Scans sheets to determine if the layout is "Wide Table", "Template", or "Tall Table".
    *   **Output:** A mapping configuration (internal).

2.  **Extraction (Raw Data)**
    *   **Input:** Mapping Config.
    *   **Action:** Reads cell values and splits text blobs (e.g., splitting ingredient lists into lines).
    *   **Output:** `RecipeCandidate` object (In-Memory). *Note: This object matches the RecipeSage structure but is not saved.*

3.  **NLP Parsing (Structuring)**
    *   **Input:** Raw strings from the `RecipeCandidate`.
    *   **Action:** Uses `ingredient-parser-nlp` to extract Quantity, Unit, and Name from strings like "1 cup flour".
    *   **Output:** Structured ingredient objects (Internal).

4.  **Step Linking (Context)**
    *   **Input:** Instructions and Ingredients.
    *   **Action:** Uses heuristics and token matching to link specific ingredients to the instruction steps where they are used.
    *   **Output:** Instructions with attached ingredient references (Internal).

5.  **Draft Generation (Final Output)**
    *   **Input:** Fully structured and linked data.
    *   **Action:** Assembles the final JSON according to `RecipeDraftV1` schema.
    *   **Output:** Final `.json` file in `staging/drafts/`.

## Key Discrepancy
*   **The Missing Artifact:** There is no persistence of the intermediate `RecipeSage JSON-LD` format.
*   **Impact:** The "Transformer" logic is currently tightly coupled to the Excel importer. To add a new source (e.g., PDF), you would currently have to implement the full extraction-to-draft pipeline, rather than just extraction-to-intermediate.

## Code Reference
In `cookimport/cli.py`, the deviation is visible in the `stage` command:
```python
# Phase 1 extraction happens here
result = importer.convert(file_path, mapping_config) 

# Phase 2 transformation happens immediately inside this function call
# skipping the intermediate disk write/read
write_draft_outputs(result, out) 
```
