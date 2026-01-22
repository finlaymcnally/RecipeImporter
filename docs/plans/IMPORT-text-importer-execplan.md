---
summary: "ExecPlan for the text file recipe import engine."
read_when:
  - When implementing the text file import engine
---

# Text File Recipe Importer ExecPlan

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

This plan must be maintained in accordance with docs/PLANS.md from the repository root.

## Purpose / Big Picture

After this change, a user can point the cookimport CLI at a folder containing text files (.txt, .md) with recipes and receive RecipeSage JSON-LD files plus a per-file report. The importer handles both single-recipe files and multi-recipe files, detecting recipe boundaries and extracting structured fields. Success is visible by staging/recipesage_jsonld/<file>/<recipe>.json files, staging/reports/<file>.text_import_report.json, and diagnostic artifacts showing split decisions and parse confidence.

## Progress

- [ ] Initial ExecPlan drafted.

## Surprises & Discoveries

(To be filled during implementation.)

## Decision Log

- Decision: Support both single-recipe and multi-recipe files with automatic detection.
  Rationale: User has a mix of saved notes (often one recipe) and compiled collections (multiple recipes). Auto-detection reduces manual configuration.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: Support an explicit recipe delimiter convention that users can adopt over time.
  Rationale: Reduces ambiguity for multi-recipe files. Recommended delimiter: a line containing only "=== RECIPE ===" or a Markdown H1 heading.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: Support YAML frontmatter in Markdown files for metadata extraction.
  Rationale: Many users already use frontmatter for personal notes. Extracting source, author, tags from frontmatter reduces parsing complexity.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: Use deterministic section detection with LLM escalation only for genuinely ambiguous cases.
  Rationale: Text files are often well-structured with clear section headers. LLM is reserved for interleaved or poorly formatted content.
  Date/Author: 2026-01-21 / Initial Plan

## Outcomes & Retrospective

(To be filled at completion.)

## Context and Orientation

The cookimport package has importers for Excel, EPUB, and PDF. This plan adds a text file importer at cookimport/plugins/text.py following the same Importer protocol.

Key terms used in this plan:

A NormalizedTextDocument is the cleaned, decoded text content of a file with metadata about encoding decisions and normalization applied. A SplitDecision records whether a file is treated as single-recipe or multi-recipe and the reasoning/confidence. A RecipeCandidate is a text chunk representing one recipe with start/end character offsets and provenance. Section Headers are lines like "Ingredients", "Directions", "Notes" that mark structural boundaries within a recipe.

Text files are the simplest source format but have high variability: some are carefully formatted with clear sections, others are copy-pasted from websites with minimal structure. The importer must handle both gracefully.

## Plan of Work

Milestone 1 establishes text file discovery and normalization. Create cookimport/plugins/text.py with the Importer protocol. Implement detect to return high confidence for .txt and .md files. Implement _normalize_text that: reads bytes and decodes with UTF-8 (fallback to CP1252/Latin-1 with warnings), normalizes line endings to \n, trims excessive whitespace (collapse 3+ blank lines to 2), and preserves original content in a raw artifact for debugging. Write staging/_raw_text/<file_id>.txt and staging/_normalized_text/<file_id>.txt.

Milestone 2 implements single vs multi-recipe detection. Create _detect_split_mode that analyzes normalized text and returns (mode, confidence, reasons). Use these multi-recipe signals: multiple top-level headings (Markdown # or underlined), repeated section headers (Ingredients/Directions appearing more than once), explicit delimiters (---, ***, ====, === RECIPE ===), very long file (> 3000 words) without clear single-recipe structure. Default to single-recipe if signals are weak. Support explicit delimiter convention that users can adopt.

Milestone 3 implements recipe splitting for multi-recipe files. Create _split_into_candidates that applies splitting strategies in order: explicit delimiter split (trust user convention), Markdown heading split (split on ^# ), repeated section-pattern split (find multiple disjoint Ingredients/Directions pairs), title-ish line split (short lines in Title Case surrounded by blank lines). Each candidate chunk includes source_file, start_offset, end_offset, raw_text. If deterministic split is uncertain and file is clearly multi-recipe, flag for optional LLM boundary detection.

Milestone 4 implements structure recovery for each candidate. Create _parse_candidate that extracts fields from a text chunk. For title: first non-empty line if short, or first Markdown heading. For section detection: identify lines matching known headers (Ingredients, Directions, Method, Instructions, Notes) that are short and either match header words or end with colon. Assign subsequent lines to sections. For ingredients: lines within ingredient section, preserving as-is (no quantity parsing at this stage). For instructions: lines within directions section, split on numbered lists or paragraphs. For metadata: regex extraction of yield (Serves, Makes, Yield), times (Prep, Cook, Total), and other common patterns.

Milestone 5 handles frontmatter and LLM escalation. If a file starts with YAML frontmatter (--- block), parse it and merge fields (source, author, tags, servings) into the recipe metadata. For low-confidence parses (no ingredient section found but ingredient-like lines exist, or interleaved content), send to LLM with constrained schema. Validate output with Pydantic.

Milestone 6 converts parsed candidates to RecipeSage JSON-LD and emits output. Each recipe gets a stable @id, includes provenance (file, offsets, parse decisions), and is written to the staging layout. Generate a per-file report with split decision, recipe count, parse confidence per recipe, and warnings.

Milestone 7 adds tests, fixtures, and documentation. Create fixture text files under tests/fixtures/text/ covering: single-recipe .txt, single-recipe .md with frontmatter, multi-recipe .md with headings, multi-recipe with explicit delimiters, poorly formatted copy-paste. Add golden outputs and pytest tests.

## Concrete Steps

Work from /home/mcnal/projects/recipeimport with the virtual environment activated.

Install PyYAML if not already present (for frontmatter parsing):

    pip install pyyaml

Create the text importer:

    touch cookimport/plugins/text.py

Register in the plugin registry.

Run tests:

    pytest tests/test_text_importer.py

Verify with CLI:

    cookimport inspect tests/fixtures/text/single_recipe.md
    cookimport stage tests/fixtures/text --out data/output/text_test

## Validation and Acceptance

The change is accepted when: Running cookimport inspect on a fixture text file prints split mode decision, detected recipe count, and section detection summary. Running cookimport stage produces JSON-LD files and a report. Each JSON-LD includes @id, name, recipeIngredient, recipeInstructions, and provenance with source file and character offsets. The report lists split decision, recipe count, parse confidence, and any warnings. Pytest tests pass and verify normalization, split detection, and field extraction.

## Idempotence and Recovery

Stable @id as urn:recipeimport:text:<file_hash>:<candidate_idx>. Intermediate artifacts (_raw_text, _normalized_text, _candidates) enable debugging and resumption. Errors in one file do not stop processing of others.

## Artifacts and Notes

Example frontmatter handling:

    ---
    source: "Grandma's Recipe Box"
    author: "Grandma"
    tags: ["dessert", "holiday"]
    servings: 12
    ---

    # Pumpkin Pie

    ## Ingredients
    - 1 can pumpkin puree
    ...

Becomes:

    {
      "@id": "urn:recipeimport:text:abc123:0",
      "name": "Pumpkin Pie",
      "author": "Grandma",
      "keywords": ["dessert", "holiday"],
      "recipeYield": "12",
      "recipeIngredient": ["1 can pumpkin puree", ...],
      "recipeimport:provenance": {
        "file_path": "...",
        "source_meta": {"source": "Grandma's Recipe Box"},
        "start_offset": 95,
        "end_offset": 1523
      }
    }

Example split decision diagnostic:

    {
      "file": "family_recipes.txt",
      "split_mode": "multi_recipe",
      "confidence": 0.9,
      "reasons": [
        "found_repeated_section_headers",
        "file_length_exceeds_threshold"
      ],
      "candidate_count": 5
    }

## Interfaces and Dependencies

Dependencies: pyyaml for frontmatter parsing (already in project for mapping files).

In cookimport/plugins/text.py:

    from pathlib import Path
    from cookimport.plugins.base import Importer
    from cookimport.core.models import WorkbookInspection, MappingConfig, ConversionResult

    class TextImporter:
        name = "text"

        def detect(self, path: Path) -> float:
            """Return 0.85 for .txt/.md files."""
            ...

        def inspect(self, path: Path) -> WorkbookInspection:
            """Normalize, detect split mode, return summary."""
            ...

        def convert(self, path: Path, mapping: MappingConfig | None) -> ConversionResult:
            """Full normalization, splitting, parsing, JSON-LD emission."""
            ...

        def _normalize_text(self, path: Path) -> tuple[str, dict]:
            """Read, decode, normalize. Return (text, metadata)."""
            ...

        def _detect_split_mode(self, text: str) -> tuple[str, float, list[str]]:
            """Return (mode, confidence, reasons). mode is 'single' or 'multi'."""
            ...

        def _split_into_candidates(self, text: str, mode: str) -> list[dict]:
            """Split text into candidate chunks with offsets."""
            ...

        def _parse_candidate(self, chunk: str, offset: int) -> RecipeCandidate:
            """Extract title, ingredients, instructions, metadata from chunk."""
            ...

        def _parse_frontmatter(self, text: str) -> tuple[dict, str]:
            """Extract YAML frontmatter if present, return (metadata, remaining_text)."""
            ...

Section header aliases for detection:

    INGREDIENT_HEADERS = {"ingredients", "ingredient list", "you'll need", "what you need"}
    INSTRUCTION_HEADERS = {"directions", "instructions", "method", "steps", "preparation", "how to make"}
    NOTE_HEADERS = {"notes", "tips", "variations", "headnote", "description"}

MappingConfig extensions for text files: explicit_delimiter (string to use for splitting), assume_single_recipe (bool to skip split detection), section_header_overrides (dict to add custom header aliases).
