---
summary: "ExecPlan for the RecipeSage export file import engine."
read_when:
  - When implementing the RecipeSage import engine
---

# RecipeSage Export Importer ExecPlan

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

This plan must be maintained in accordance with docs/PLANS.md from the repository root.

## Purpose / Big Picture

After this change, a user can point the cookimport CLI at a folder containing RecipeSage export files (JSON with schema.org Recipe format) and have them "staged" for the final transformation.

**Critical Context:** The project's "intermediate staging format" **IS** RecipeSage JSON-LD. Therefore, this importer is unique: it does not convert *to* the staging format, it **validates and normalizes** existing files *into* the official staging layout. It acts as a "pass-through" or "gatekeeper" to ensure that data coming from RecipeSage backups is compliant with the expectations of Phase 2 (the Transformer).

Success is visible by the presence of `staging/recipesage_jsonld/<export_name>/<recipe_id>.json` files that are validated, normalized, and enriched with provenance, plus a report.

## Progress

- [ ] Initial ExecPlan drafted.

## Surprises & Discoveries

(To be filled during implementation.)

## Decision Log

- Decision: RecipeSage importer validates and normalizes incoming RecipeSage exports rather than blindly copying.
  Rationale: Exports may vary in field completeness, use different schema conventions, or lack provenance. Validation ensures downstream consistency for the Transformer.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: RecipeSage exports use a wrapper format with a "recipes" array containing schema.org Recipe objects.
  Rationale: Observed in example files. Each file contains `{"recipes": [...]}`.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: No LLM escalation for RecipeSage imports.
  Rationale: The format is already structured JSON-LD. Any issues are validation/normalization, not structure recovery.
  Date/Author: 2026-01-21 / Initial Plan

## Outcomes & Retrospective

(To be filled at completion.)

## Context and Orientation

The cookimport package has importers for Excel, EPUB, PDF, Text, and Paprika. This plan adds a RecipeSage importer at `cookimport/plugins/recipesage.py`.

Key terms:
*   **RecipeSage Export:** A JSON file `{"recipes": [...]}` where each item is a schema.org `Recipe`.
*   **Staging Format:** The same schema.org `Recipe` JSON-LD structure, but saved as individual files with standard filenames and added provenance.

## Plan of Work

### Phase 1: Ingest & Parse (Milestone 1)

**Goal:** Read the export file and extract the list of recipes.

1.  **Detect:** Return high confidence (0.95) for JSON files containing a `"recipes"` array of objects with `"@type": "Recipe"`.
2.  **Parse:** Load the JSON and extract the list.

### Phase 2: Validation & Normalization (Milestone 2)

**Goal:** Ensure the incoming data meets the strict expectations of the Phase 2 Transformer.

1.  **Validate:**
    *   Check for required fields: `name`.
    *   Check for at least one of: `recipeIngredient`, `recipeInstructions`.
2.  **Normalize:**
    *   **Context:** Ensure `@context` is valid (e.g., `http://schema.org`).
    *   **Lists:** Ensure `recipeIngredient` is a list of strings.
    *   **Instructions:** Ensure `recipeInstructions` is a list of `HowToStep` objects or strings (normalize to `HowToStep` preferred).
    *   **Times:** Normalize `prepTime`, `cookTime` to ISO 8601 durations (`PT15M`) if they aren't already.
    *   **Categories:** Ensure `recipeCategory` is a list.

### Phase 3: Provenance & Emission (Milestone 3)

**Goal:** Write the "Staged" files.

1.  **Provenance:** Add a `recipeimport:provenance` block to the JSON-LD object containing:
    *   `source_system`: "recipesage"
    *   `export_file`: Original filename.
    *   `source_uid`: The original `identifier` or a content hash.
2.  **Stable ID:** Ensure the `@id` field is set to `urn:recipeimport:recipesage:<uid>`.
3.  **Write:** Save to `staging/recipesage_jsonld/<export_slug>/<recipe_uid>.json`.
4.  **Report:** Generate `staging/reports/<export_slug>.recipesage_import_report.json` summarizing valid vs. invalid recipes.

## Concrete Steps

1.  **Create Plugin:** `touch cookimport/plugins/recipesage.py`.
2.  **Implement `RecipeSageImporter`:**
    *   `detect`, `inspect`, `convert`.
    *   `_validate_recipe`: Checks for mandatory fields.
    *   `_normalize_recipe`: Cleaning and formatting logic.
    *   `_add_provenance`: Injecting metadata.
3.  **Testing:**
    *   Use fixtures in `tests/fixtures/recipesage/`.
    *   Verify that "bad" data (missing name) is flagged in the report.
    *   Verify that "good" data is faithfully copied to the staging folder with added provenance.

## Validation and Acceptance

*   `cookimport stage` on a RecipeSage export file results in a folder of individual JSON files in the staging directory.
*   The output files are valid JSON-LD.
*   Provenance metadata is present in every output file.
*   The report accurately counts successful and failed recipes.

## Interfaces and Dependencies

*   **Libraries:** `json` (stdlib).
*   **Models:** Re-use `cookimport.core.models` validation logic where applicable.