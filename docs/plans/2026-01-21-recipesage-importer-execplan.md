---
summary: "ExecPlan for the RecipeSage export file import engine."
read_when:
  - When implementing the RecipeSage import engine
---

# RecipeSage Export Importer ExecPlan

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

This plan must be maintained in accordance with docs/PLANS.md from the repository root.

## Purpose / Big Picture

After this change, a user can point the cookimport CLI at a folder containing RecipeSage export files (JSON with schema.org Recipe format) and have them pass through the staging layer for normalization, provenance tracking, and eventual transformation to the final database format. Since RecipeSage JSON-LD is the target intermediate format, this importer is primarily a validation and enrichment pass. Success is visible by staging/recipesage_jsonld/<export>/<recipe>.json files that are validated, normalized, and enriched with provenance, plus a per-export report.

## Progress

- [ ] Initial ExecPlan drafted.

## Surprises & Discoveries

(To be filled during implementation.)

## Decision Log

- Decision: RecipeSage importer validates and normalizes incoming RecipeSage exports rather than blindly copying.
  Rationale: Exports may vary in field completeness, use different schema conventions, or lack provenance. Validation ensures downstream consistency.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: RecipeSage exports use a wrapper format with a "recipes" array containing schema.org Recipe objects.
  Rationale: Observed in example files at docs/template/examples/recipesage-*.json. Each file contains {"recipes": [...]}.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: No LLM escalation for RecipeSage imports; the format is already the target schema.
  Rationale: RecipeSage exports are machine-generated and follow schema.org conventions. Any issues are validation/normalization, not structure recovery.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: Preserve original RecipeSage fields in provenance and add any missing fields from our standard set.
  Rationale: RecipeSage exports may evolve. Preserving originals enables re-processing; adding defaults ensures consistency.
  Date/Author: 2026-01-21 / Initial Plan

## Outcomes & Retrospective

(To be filled at completion.)

## Context and Orientation

The cookimport package has importers for Excel, EPUB, PDF, text, and Paprika. This plan adds a RecipeSage importer at cookimport/plugins/recipesage.py. Since RecipeSage JSON-LD is the staging format, this importer is simpler than others: it validates, normalizes, and re-emits with added provenance.

Key terms used in this plan:

A RecipeSage Export File is a JSON file with structure {"recipes": [...]} where each recipe follows schema.org Recipe type with fields like @context, @type, identifier, name, recipeIngredient, recipeInstructions, prepTime, cookTime, totalTime, recipeYield, recipeCategory, image, etc. HowToStep is the schema.org type for instruction steps, with a text field. Comment is used for author notes in RecipeSage. AggregateRating contains ratingValue and ratingCount.

Example files are available at docs/template/examples/recipesage-1767633332725-b28c4512684ecf.json and docs/template/examples/recipesage-1767631101507-d892343ecccd93.json.

## Plan of Work

Milestone 1 establishes RecipeSage file detection and parsing. Create cookimport/plugins/recipesage.py with the Importer protocol. Implement detect to return high confidence (0.95) for JSON files that contain a "recipes" key with array value containing objects with @type: "Recipe". Implement _parse_export that loads JSON and extracts the recipes array.

Milestone 2 implements validation and normalization. Create _validate_recipe that checks each recipe for required fields (name, at least one of recipeIngredient or recipeInstructions). Report missing or malformed fields. Create _normalize_recipe that: ensures @context is present and valid, normalizes time fields to ISO 8601 if needed, ensures recipeIngredient is a list of strings, ensures recipeInstructions is a list of HowToStep objects or strings, normalizes recipeCategory and keywords to lists, and fills optional fields with null/empty defaults for consistency.

Milestone 3 implements RecipeCandidate conversion and provenance. Create _recipesage_to_candidate that maps validated/normalized recipe to RecipeCandidate model. Use identifier field as source_uid if present, otherwise generate from content hash. Add provenance with source_system: "recipesage", original export fields, and validation notes.

Milestone 4 re-emits to staging JSON-LD with enrichment. Convert RecipeCandidate back to JSON-LD (using existing jsonld.py), ensuring @id follows the urn:recipeimport:recipesage:<uid> pattern. Write to staging/recipesage_jsonld/<export>/<recipe>.json. Generate per-export report with recipe count, validation warnings, and normalization changes applied.

Milestone 5 handles edge cases and field variations. RecipeSage exports may include custom fields, varying instruction formats (array of strings vs array of HowToStep), and optional comment/rating structures. The normalizer should handle these gracefully, preserving unknown fields in a custom extension block.

Milestone 6 adds tests, fixtures, and documentation. Copy example files to tests/fixtures/recipesage/. Add golden outputs and pytest tests verifying parsing, validation, normalization, and output.

## Concrete Steps

Work from /home/mcnal/projects/recipeimport with the virtual environment activated.

Create the RecipeSage importer:

    touch cookimport/plugins/recipesage.py

Copy example files to test fixtures:

    mkdir -p tests/fixtures/recipesage
    cp docs/template/examples/recipesage-*.json tests/fixtures/recipesage/

Register in the plugin registry.

Run tests:

    pytest tests/test_recipesage_importer.py

Verify with CLI:

    cookimport inspect tests/fixtures/recipesage/recipesage-1767633332725-b28c4512684ecf.json
    cookimport stage tests/fixtures/recipesage --out data/output/recipesage_test

## Validation and Acceptance

The change is accepted when: Running cookimport inspect on a RecipeSage export file prints recipe count, validation summary, and any warnings. Running cookimport stage produces JSON-LD files and a report. Output JSON-LD is normalized and includes provenance with source_system: "recipesage". The report lists recipe count, validation status per recipe, and normalization changes. Pytest tests pass and verify parsing, validation, normalization, and round-trip stability.

## Idempotence and Recovery

Stable @id as urn:recipeimport:recipesage:<identifier> where identifier is the RecipeSage identifier field or a content hash. Re-importing the same export produces identical output. No intermediate work files needed since parsing is straightforward.

## Artifacts and Notes

Example RecipeSage export structure (from observed files):

    {
      "recipes": [
        {
          "@context": "http://schema.org",
          "@type": "Recipe",
          "identifier": "35b00969-7c88-462a-9aae-89bd277a8a17",
          "datePublished": "2026-01-05T16:37:20.033Z",
          "name": "Slow Cooker Red Beans And Rice Recipe",
          "description": "Description",
          "image": ["https://..."],
          "prepTime": "PT15M",
          "cookTime": null,
          "totalTime": "PT7H",
          "recipeYield": "Makes 10",
          "recipeIngredient": [
            "1 pound dried red beans",
            "3/4 pound smoked turkey sausage, thinly sliced",
            ...
          ],
          "recipeInstructions": [
            {"@type": "HowToStep", "text": "Combine first 8 ingredients..."},
            {"@type": "HowToStep", "text": "Serve red bean mixture..."}
          ],
          "recipeCategory": ["label example", "label"],
          "creditText": "Source name",
          "isBasedOn": "https://www.southernliving.com/...",
          "comment": [
            {"@type": "Comment", "name": "Author Notes", "text": "notes notes"}
          ],
          "aggregateRating": {
            "@type": "AggregateRating",
            "ratingValue": "3",
            "ratingCount": "5"
          }
        }
      ]
    }

After normalization and provenance addition:

    {
      "@context": ["https://schema.org", {"recipeimport": "..."}],
      "@type": "Recipe",
      "@id": "urn:recipeimport:recipesage:35b00969-7c88-462a-9aae-89bd277a8a17",
      "identifier": "35b00969-7c88-462a-9aae-89bd277a8a17",
      "name": "Slow Cooker Red Beans And Rice Recipe",
      ... (all original fields preserved),
      "recipeimport:provenance": {
        "source_system": "recipesage",
        "source_uid": "35b00969-7c88-462a-9aae-89bd277a8a17",
        "export_file": "recipesage-1767633332725-b28c4512684ecf.json",
        "validation_notes": [],
        "normalization_applied": ["ensured_context_array"]
      }
    }

## Interfaces and Dependencies

Dependencies: json (stdlib), pydantic for validation (already in project).

In cookimport/plugins/recipesage.py:

    from pathlib import Path
    import json
    from cookimport.plugins.base import Importer
    from cookimport.core.models import WorkbookInspection, MappingConfig, ConversionResult, RecipeCandidate

    class RecipeSageImporter:
        name = "recipesage"

        def detect(self, path: Path) -> float:
            """Return 0.95 for JSON files with recipes array of @type Recipe objects."""
            if path.suffix.lower() != '.json':
                return 0.0
            try:
                data = json.loads(path.read_text())
                if isinstance(data.get('recipes'), list):
                    if any(r.get('@type') == 'Recipe' for r in data['recipes']):
                        return 0.95
            except:
                pass
            return 0.0

        def inspect(self, path: Path) -> WorkbookInspection:
            """Parse and summarize without full emission."""
            ...

        def convert(self, path: Path, mapping: MappingConfig | None) -> ConversionResult:
            """Parse, validate, normalize, emit."""
            ...

        def _parse_export(self, path: Path) -> list[dict]:
            """Load JSON and return recipes array."""
            data = json.loads(path.read_text())
            return data.get('recipes', [])

        def _validate_recipe(self, raw: dict) -> tuple[bool, list[str]]:
            """Check required fields, return (is_valid, warnings)."""
            warnings = []
            if not raw.get('name'):
                warnings.append('missing_name')
            if not raw.get('recipeIngredient') and not raw.get('recipeInstructions'):
                warnings.append('missing_ingredients_and_instructions')
            return len(warnings) == 0, warnings

        def _normalize_recipe(self, raw: dict) -> tuple[dict, list[str]]:
            """Normalize fields, return (normalized, changes_applied)."""
            changes = []
            normalized = dict(raw)

            # Ensure @context is array format
            ctx = normalized.get('@context')
            if isinstance(ctx, str):
                normalized['@context'] = [ctx, {"recipeimport": "https://recipeimport.local/ns#"}]
                changes.append('ensured_context_array')

            # Ensure recipeIngredient is list
            ing = normalized.get('recipeIngredient')
            if ing is None:
                normalized['recipeIngredient'] = []
            elif isinstance(ing, str):
                normalized['recipeIngredient'] = [ing]
                changes.append('converted_ingredients_to_list')

            # Ensure recipeInstructions is list
            inst = normalized.get('recipeInstructions')
            if inst is None:
                normalized['recipeInstructions'] = []
            elif isinstance(inst, str):
                normalized['recipeInstructions'] = [{"@type": "HowToStep", "text": inst}]
                changes.append('converted_instructions_to_list')

            return normalized, changes

        def _recipesage_to_candidate(self, raw: dict, export_file: str) -> RecipeCandidate:
            """Map validated/normalized recipe to RecipeCandidate."""
            ...

RecipeSage field reference (for validation):
- Required: name
- Semi-required: recipeIngredient OR recipeInstructions (at least one)
- Optional: description, image, prepTime, cookTime, totalTime, recipeYield, recipeCategory, keywords, author, creditText, isBasedOn, comment, aggregateRating, datePublished, identifier

Time format validation: RecipeSage uses ISO 8601 durations (PT15M, PT1H30M). Validate format; warn if malformed.

Instruction format normalization: Accept both string arrays and HowToStep arrays. Normalize to HowToStep format for consistency.
