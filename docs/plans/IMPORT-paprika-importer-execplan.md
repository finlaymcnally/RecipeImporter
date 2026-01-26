---
summary: "ExecPlan for the Paprika Recipe Manager import engine."
read_when:
  - When implementing the Paprika import engine
---

# Paprika Recipe Manager Importer ExecPlan

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

This plan must be maintained in accordance with docs/PLANS.md from the repository root.

## Purpose / Big Picture

After this change, a user can point the cookimport CLI at a folder containing Paprika export files (.paprikarecipes) and/or Paprika HTML export folders, and receive RecipeSage JSON-LD files plus a per-export report. Paprika exports are already structured, so this importer is largely a format translation with minimal heuristics. Success is visible by staging/recipesage_jsonld/<export>/<recipe>.json files, staging/reports/<export>.paprika_import_report.json, and raw decompressed JSON artifacts for provenance.

## Progress

- [ ] Initial ExecPlan drafted.

## Surprises & Discoveries

(To be filled during implementation.)

## Decision Log

- Decision: Support both .paprikarecipes files and Paprika HTML export folders.
  Rationale: Users may have either or both export types. The .paprikarecipes format is more complete; HTML exports provide cleaner ingredient arrays and images.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: The .paprikarecipes format is a ZIP containing individually gzipped JSON files per recipe.
  Rationale: Paprika's official documentation describes this format. Each entry is gzip-compressed JSON, not plain JSON.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: No LLM escalation for Paprika imports; the format is structured enough.
  Rationale: Paprika exports are already machine-readable with clear field mappings. LLM would add cost without benefit.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: When both .paprikarecipes and HTML export exist for the same recipes, prefer .paprikarecipes for text fields and HTML for structured ingredient arrays and images.
  Rationale: Best-of-both-worlds merge. Match recipes by source_url + title fuzzy matching.
  Date/Author: 2026-01-21 / Initial Plan

## Outcomes & Retrospective

(To be filled at completion.)

## Context and Orientation

The cookimport package has importers for Excel, EPUB, PDF, and text. This plan adds a Paprika importer at cookimport/plugins/paprika.py following the same Importer protocol.

Key terms used in this plan:

A **.paprikarecipes file** is a ZIP archive where each entry is a gzip-compressed JSON blob representing one recipe. The JSON schema includes fields like `name`, `ingredients` (text blob), `directions` (text blob), `notes`, `servings`, `prep_time`, `cook_time`, `source`, `source_url`, `categories`, and optionally `photo_data`.

A **Paprika HTML Export** is a folder containing per-recipe HTML files with embedded schema.org Recipe microdata/JSON-LD, plus an `images/` subfolder. The HTML export often has cleaner structured ingredient lists (one per line in the HTML) compared to the raw text blob in .paprikarecipes.

Paprika is a commercial recipe manager app. Its export formats are designed for backup/restore, so they contain all recipe data. This makes Paprika imports the cleanest source type in the pipeline.

Example files are available at `docs/template/examples/Broccoli Cheese Soup1.paprikarecipes` and `docs/template/examples/PaprikaApp Broccoli Cheese Soup.html`.

## Plan of Work

### Phase 1: Ingest & Extraction (Milestone 1)

**Goal:** Extract raw recipe data from both supported export formats.

1.  **Detect:**
    *   Return 0.95 confidence for `.paprikarecipes` files.
    *   Return 0.8 confidence for folders containing Paprika HTML exports (look for `index.html` and recipe `.html` files with specific signatures).
2.  **Extract .paprikarecipes:**
    *   Open as ZIP.
    *   Iterate entries: Gunzip -> UTF-8 Text -> JSON Parse.
    *   *Artifact:* Write raw decompressed JSON to `staging/raw/paprika/<recipe_uid>.json`.
3.  **Extract HTML Export:**
    *   Scan folder for recipe `.html` files (exclude `index.html`).
    *   Parse each file with BeautifulSoup.
    *   Extract embedded JSON-LD (preferred) or microdata.
    *   *Artifact:* Record image paths from the `images/` subfolder if present.

### Phase 2: Normalization (Milestone 2)

**Goal:** Convert raw extracted data into an internal `RecipeCandidate`.

1.  **Normalize from JSON (.paprikarecipes):**
    *   `name` -> `title`
    *   `ingredients` (text blob) -> `ingredients_raw` (keep raw here, split by `\n` downstream)
    *   `directions` (text blob) -> `directions_raw`
    *   `notes` -> `description`/`notes`
    *   `servings` -> `recipeYield`
    *   `prep_time`/`cook_time` -> Normalized to ISO 8601 Duration (e.g., `PT5M`).
    *   `uid` -> `source_uid` (stable ID).
2.  **Normalize from HTML:**
    *   Use schema.org fields directly where possible.
    *   Benefit: Ingredients are often already structured lists.
    *   Benefit: Times/Yields often already normalized.

### Phase 3: Merge Mode (Milestone 3)

**Goal:** Create a single best-record when both exports exist.

1.  **Matching:** Match recipes by `source_url` + fuzzy title match, or `uid` if present in both.
2.  **Precedence:**
    *   **Prefer .paprikarecipes** for: Notes, categories, ratings, internal fields, canonical text.
    *   **Prefer HTML Export** for: Structured ingredient arrays, time/yield normalization, photos/assets.
3.  **Audit:** Keep both originals in `raw/` so mismatches can be audited.

### Phase 4: Output & Reporting (Milestone 4)

1.  **Emission:**
    *   Write `staging/recipesage_jsonld/<stable_id>.jsonld`.
    *   **Stable ID:** `urn:recipeimport:paprika:<source_uid>`.
    *   **Provenance:** Include `source_system: "paprika"`, `export_type`, and the original fields in a `recipeimport:provenance` block.
2.  **Assets:** If HTML export images exist, copy them to `staging/assets/paprika/<id>/...`.
3.  **Reporting:**
    *   Write `reports/paprika_import_report.json` with counts, duplicates, and missing fields.
4.  **Shared updates:** Emit raw artifacts via `ConversionResult.rawArtifacts` and honor any `parsingOverrides` (tip headers/prefixes, units, etc.) to match the shared importer standards.

## Concrete Steps

1.  **Dependencies:** `pip install beautifulsoup4 lxml` (already present).
2.  **Create Plugin:** `touch cookimport/plugins/paprika.py`.
3.  **Implement `PaprikaImporter`:**
    *   `detect`, `inspect`, `convert` methods.
    *   `_extract_paprikarecipes`: ZIP/Gzip handling.
    *   `_extract_html`: BeautifulSoup parsing.
    *   `_merge_exports`: Logic for combining data sources.
    *   `_normalize_time`: Duration parsing helper.

## Validation and Acceptance

*   `cookimport inspect` on a `.paprikarecipes` file prints recipe count and field summary.
*   `cookimport stage` produces valid JSON-LD files with populated fields.
*   **Provenance:** Standard `recipeimport:provenance` block is present and links back to the source export.
*   **Idempotence:** Re-running the import on the same `.paprikarecipes` file produces identical recipe URNs and output filenames.
*   **Audit:** `staging/raw/paprika/` contains the raw decompressed JSON/HTML fragments.
*   Merged output (if applicable) correctly prioritizes structured data from HTML while keeping notes from JSON.

## Interfaces and Dependencies

*   **Libraries:** `gzip`, `zipfile`, `beautifulsoup4`.
*   **Time Normalization:** Strings like "5 mins", "1 hr 30 mins" must be converted to `PT5M`, `PT1H30M`.
