---
summary: "ExecPlan for shared reporting, provenance, and idempotence logic."
read_when:
  - When implementing output generation and status reporting for any importer
---

# Reporting and Provenance ExecPlan

This ExecPlan defines the standard output format, provenance structure, and identity management for the project. Consistency here is vital for the "Transformer" stage (which reads these outputs) and for user trust.

## Purpose / Big Picture

To ensure that every importer, regardless of source (PDF, Excel, Web), produces artifacts that look the same, trace back to their origin in the same way, and report their success/failure using a shared vocabulary.

## Core Standards

### 1. Stable Identity (Idempotence)

**Goal:** Re-running an import on the same file should produce the exact same output filenames and IDs.

*   **Strategy:**
    *   `source_hash`: SHA256 of the input file.
    *   `location_id`: Unique locator within the file (e.g., `page_12`, `row_5`, `section_3`).
    *   **Recipe ID (`@id`):** `urn:recipeimport:<source_type>:<source_hash>:<location_id>`
*   **Output Paths:**
    *   `staging/recipesage_jsonld/<source_filename_slug>/<location_id>.json`
    *   (Avoids random UUIDs).

### 2. Provenance Object (`recipeimport:provenance`)

**Goal:** Every emitted recipe must carry its "birth certificate".

*   **Structure (embedded in JSON-LD):**
    ```json
    "recipeimport:provenance": {
      "source_file": "My Cookbook.pdf",
      "source_hash": "a1b2...",
      "importer_version": "0.1.0",
      "extraction_method": "heuristic" | "llm_repair",
      "confidence_score": 0.85,
      "location": {
        "page": 42,
        "bbox": [100, 200, 300, 400],
        "original_text_fragment": "..."
      },
      "processing_log": ["Normalized text", "Detected header", "Repaired via LLM"]
    }
    ```

### 3. The Import Report (`Manifest`)

**Goal:** A human-readable and machine-parseable summary of what happened.

*   **File:** `staging/reports/<source_filename>.report.json`
*   **Structure:**
    *   `summary`: Total candidates, success count, low_confidence count, error count.
    *   `candidates`: List of detected recipes with their IDs, confidence scores, and status ("valid", "needs_review").
    *   `errors`: List of fatal errors or skipped blocks.
    *   `llm_usage`: Token counts and costs (if applicable).

### 4. Implementation (`cookimport.core.reporting`)

*   **`ReportBuilder` Class:** A context manager that accumulates events during the import process and writes the JSON report on exit.
*   **`ProvenanceBuilder` Class:** Helper to construct the standardized provenance dictionary.

## Integration Point

*   **All Importers:** Must instantiate a `ReportBuilder` at the start of `convert()`.
*   **All Importers:** Must attach provenance to every `RecipeCandidate` before emitting.
*   **CLI:** The `inspect` command should use the standard provenance/report logic to preview what *would* happen.

## Context from "Thoughts"

*   "Output/report/idempotence patterns are repeated."
*   "Treat 'confidence + reasons' as a first-class output."
*   "Idempotence + provenance everywhere: stable IDs..."

## Implementation Status

*   **2026-01-22:** Implemented `cookimport.core.reporting`.
    *   `ProvenanceBuilder`: Created and verifying standard provenance dictionary.
    *   `ReportBuilder`: Context manager implemented, producing JSON reports with summary, candidates, errors, and LLM usage.
    *   `generate_recipe_id`: Implemented stable URN generation.
    *   Verified via manual test script `tests/test_phase1_manual.py`.
