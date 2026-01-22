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

A .paprikarecipes file is a ZIP archive where each entry is a gzip-compressed JSON blob representing one recipe. The JSON schema includes fields like name, ingredients (text blob), directions (text blob), notes, servings, prep_time, cook_time, source, source_url, categories, and optionally photo data. A Paprika HTML Export is a folder containing per-recipe HTML files with embedded schema.org Recipe microdata/JSON-LD, plus an images/ subfolder. The HTML export often has cleaner structured ingredient lists (one per line in the HTML) compared to the raw text blob in .paprikarecipes.

Paprika is a commercial recipe manager app. Its export formats are designed for backup/restore, so they contain all recipe data. This makes Paprika imports the cleanest source type in the pipeline.

Example files are available at docs/template/examples/Broccoli Cheese Soup1.paprikarecipes and docs/template/examples/PaprikaApp Broccoli Cheese Soup.html.

## Plan of Work

Milestone 1 establishes .paprikarecipes extraction. Create cookimport/plugins/paprika.py with the Importer protocol. Implement detect to return high confidence (0.95) for .paprikarecipes files and for folders containing Paprika HTML exports (index.html with characteristic structure). Implement _extract_paprikarecipes that: opens the file as a ZIP, iterates entries, gunzips each entry, parses JSON, and yields raw recipe dicts. Write raw decompressed JSON to staging/raw/paprika/<recipe_id>.json for provenance.

Milestone 2 implements field mapping from Paprika JSON to RecipeCandidate. Create _paprika_to_candidate that maps: name to title, ingredients (text) split by newlines to ingredients list, directions (text) split by newlines or numbered patterns to instructions list, notes to description, servings to recipeYield, prep_time and cook_time to time fields, source and source_url to source fields, categories to tags. Generate a stable source_uid from Paprika's uid field if present, otherwise hash the JSON. Preserve the original Paprika JSON in provenance.

Milestone 3 implements HTML export parsing. Create _extract_html_export that: scans a folder for recipe HTML files (not index.html), parses each with BeautifulSoup, extracts embedded JSON-LD or schema.org microdata, and yields structured recipe dicts. HTML exports often have better ingredient structure (already split into lines) and image references. If an images/ folder exists, record image paths for optional asset copying.

Milestone 4 implements merge mode when both exports are present. Create _merge_exports that: matches recipes from .paprikarecipes and HTML export by source_url and fuzzy title match, prefers .paprikarecipes for text fields (notes, categories, ratings), prefers HTML for structured ingredients and image assets, logs merge decisions and confidence. Output is a single unified RecipeCandidate per recipe.

Milestone 5 converts to RecipeSage JSON-LD and emits output. Map RecipeCandidate to JSON-LD with standard @context, @type, @id. Include provenance with source_system: "paprika", original Paprika fields, and export type. Generate per-export report with recipe count, merge stats (if applicable), and any warnings.

Milestone 6 adds tests, fixtures, and documentation. Use the existing fixture at tests/fixtures (or copy from docs/template/examples) for .paprikarecipes. Create a mock HTML export folder. Add golden outputs and pytest tests verifying extraction, field mapping, and merge logic.

## Concrete Steps

Work from /home/mcnal/projects/recipeimport with the virtual environment activated.

BeautifulSoup should already be installed for the EPUB importer. If not:

    pip install beautifulsoup4 lxml

Create the Paprika importer:

    touch cookimport/plugins/paprika.py

Copy example files to test fixtures:

    mkdir -p tests/fixtures/paprika
    cp "docs/template/examples/Broccoli Cheese Soup1.paprikarecipes" tests/fixtures/paprika/
    cp "docs/template/examples/PaprikaApp Broccoli Cheese Soup.html" tests/fixtures/paprika/

Register in the plugin registry.

Run tests:

    pytest tests/test_paprika_importer.py

Verify with CLI:

    cookimport inspect "tests/fixtures/paprika/Broccoli Cheese Soup1.paprikarecipes"
    cookimport stage tests/fixtures/paprika --out data/output/paprika_test

## Validation and Acceptance

The change is accepted when: Running cookimport inspect on a .paprikarecipes file prints recipe count and field summary. Running cookimport stage produces JSON-LD files and a report. Each JSON-LD includes @id, name, recipeIngredient, recipeInstructions, and provenance with source_system: "paprika" and original Paprika fields. The report lists recipe count, source type (paprikarecipes/html/merged), and any missing fields. Pytest tests pass and verify ZIP/gzip extraction, field mapping, and HTML parsing.

## Idempotence and Recovery

Stable @id as urn:recipeimport:paprika:<source_uid> where source_uid is Paprika's uid field or a content hash. Raw JSON artifacts enable re-transformation without re-extraction. Duplicate detection by source_uid prevents duplicate output when processing overlapping exports.

## Artifacts and Notes

Example Paprika JSON structure (after gunzip, based on observed format):

    {
      "uid": "DA870225-2DB1-47DF-8714-744C1DFCE8AD",
      "name": "Broccoli Cheese Soup",
      "ingredients": "1 1/2 pounds broccoli\n2 tablespoons vegetable oil\n...",
      "directions": "Separate broccoli into florets...\nHeat oil in a large Dutch oven...",
      "notes": "",
      "servings": "6 servings",
      "prep_time": "5 mins",
      "cook_time": "50 mins",
      "source": "Seriouseats.com",
      "source_url": "https://www.seriouseats.com/broccoli-cheddar-cheese-soup-food-lab-recipe",
      "categories": ["Soup", "Vegetarian"],
      "rating": 0,
      "photo_data": "base64..."
    }

Mapped to RecipeSage JSON-LD:

    {
      "@context": ["https://schema.org", {"recipeimport": "..."}],
      "@type": "Recipe",
      "@id": "urn:recipeimport:paprika:DA870225-2DB1-47DF-8714-744C1DFCE8AD",
      "name": "Broccoli Cheese Soup",
      "recipeIngredient": [
        "1 1/2 pounds broccoli",
        "2 tablespoons vegetable oil",
        ...
      ],
      "recipeInstructions": [
        {"@type": "HowToStep", "text": "Separate broccoli into florets..."},
        {"@type": "HowToStep", "text": "Heat oil in a large Dutch oven..."}
      ],
      "prepTime": "PT5M",
      "cookTime": "PT50M",
      "recipeYield": "6 servings",
      "author": "Seriouseats.com",
      "isBasedOn": "https://www.seriouseats.com/broccoli-cheddar-cheese-soup-food-lab-recipe",
      "recipeCategory": ["Soup", "Vegetarian"],
      "recipeimport:provenance": {
        "source_system": "paprika",
        "source_uid": "DA870225-2DB1-47DF-8714-744C1DFCE8AD",
        "export_type": "paprikarecipes",
        "original_paprika": { ... }
      }
    }

## Interfaces and Dependencies

Dependencies: gzip (stdlib), zipfile (stdlib), beautifulsoup4 for HTML parsing.

In cookimport/plugins/paprika.py:

    from pathlib import Path
    import gzip
    import zipfile
    import json
    from cookimport.plugins.base import Importer
    from cookimport.core.models import WorkbookInspection, MappingConfig, ConversionResult

    class PaprikaImporter:
        name = "paprika"

        def detect(self, path: Path) -> float:
            """Return 0.95 for .paprikarecipes, 0.8 for Paprika HTML folders."""
            ...

        def inspect(self, path: Path) -> WorkbookInspection:
            """Extract and summarize without full conversion."""
            ...

        def convert(self, path: Path, mapping: MappingConfig | None) -> ConversionResult:
            """Full extraction and JSON-LD emission."""
            ...

        def _extract_paprikarecipes(self, path: Path) -> list[dict]:
            """Open ZIP, gunzip each entry, parse JSON, return list of raw dicts."""
            with zipfile.ZipFile(path, 'r') as zf:
                for name in zf.namelist():
                    with zf.open(name) as f:
                        decompressed = gzip.decompress(f.read())
                        yield json.loads(decompressed.decode('utf-8'))

        def _extract_html_export(self, folder: Path) -> list[dict]:
            """Parse HTML files, extract embedded schema.org data."""
            ...

        def _paprika_to_candidate(self, raw: dict, export_type: str) -> RecipeCandidate:
            """Map Paprika fields to RecipeCandidate."""
            ...

        def _merge_exports(self, paprika_recipes: list, html_recipes: list) -> list[RecipeCandidate]:
            """Match and merge recipes from both export types."""
            ...

Time field normalization: Paprika uses strings like "5 mins", "1 hr 30 mins". Convert to ISO 8601 duration (PT5M, PT1H30M) for RecipeSage compatibility. Implement a _parse_duration helper.

Paprika field mapping reference:
- name -> name
- ingredients -> recipeIngredient (split by \n)
- directions -> recipeInstructions (split by \n or numbered patterns)
- notes -> comment or description
- servings -> recipeYield
- prep_time -> prepTime (normalized to ISO 8601)
- cook_time -> cookTime (normalized to ISO 8601)
- total_time -> totalTime
- source -> author or creditText
- source_url -> isBasedOn
- categories -> recipeCategory
- rating -> aggregateRating (if > 0)
- photo_data -> image (base64 decode if needed, or reference)
