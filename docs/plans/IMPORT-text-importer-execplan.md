---
summary: "ExecPlan for the text file import engine."
read_when:
  - When implementing the text file import engine
---

# Text File Importer ExecPlan

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

This plan must be maintained in accordance with docs/PLANS.md from the repository root.

## Purpose / Big Picture

After this change, a user can point the cookimport CLI at a folder containing text files (TXT, MD, etc.) and receive RecipeSage JSON-LD files plus a report in the staging layout. The importer will normalize text content, intelligently split files containing multiple recipes, and parse structure (ingredients, instructions, metadata) into standardized candidates. Success is visible by the presence of staging/recipesage_jsonld/<file>/<recipe>.json files and staging/reports/<file>.text_import_report.json.

## Progress

- [x] Initial ExecPlan drafted.
- [x] Implemented `TextImporter` in `cookimport/plugins/text.py`.
- [x] Implemented `TextNormalizer` and `RecipeSplitter` logic.
- [x] Verified with `tests/test_text_importer.py`.

## Surprises & Discoveries

(To be filled during implementation.)

## Decision Log

- Decision: Normalize all input text formats (Markdown, RTF, etc.) into a "Normalized Text Document" before processing.
  Rationale: Removing encoding issues, line endings, and excessive whitespace early simplifies the downstream splitting and parsing logic.
  Date/Author: 2026-01-21 / Initial Plan

- Decision: Implement a "Split Decision" step to classify files as "Single Recipe" or "Multi-Recipe" before parsing.
  Rationale: Prevents trying to parse a whole cookbook file as one giant recipe, and allows for specialized splitting logic (e.g., Markdown headers vs. delimiters).
  Date/Author: 2026-01-21 / Initial Plan

- Decision: Support YAML frontmatter for metadata injection.
  Rationale: Allows users to easily add metadata (tags, servings, source) to their text notes in a standard way that the importer can pick up deterministically.
  Date/Author: 2026-01-21 / Initial Plan

## Outcomes & Retrospective

(To be filled at completion.)

## Context and Orientation

This plan adds a Text importer at cookimport/plugins/text.py. It follows the standard Importer protocol. The challenge with text files is lack of explicit structure; a file might be a quick note, a copy-paste from a blog, or an entire exported notebook.

Key terms:
*   **NormalizedText:** UTF-8 text with consistent line endings (\n) and trimmed whitespace.
*   **Split Mode:** A classification (`single` vs. `multi`) determining if the file should be sliced.
*   **RecipeCandidate:** A chunk of text identified as one recipe.
*   **Skeleton:** An internal intermediate object identifying the structural blocks (Title, Ingredients Block, Instructions Block) before field parsing.

## Plan of Work

### Phase 1: Ingest & Normalization (Milestone 1)

**Goal:** Turn any text file into a clean, normalized string.

1.  **File Discovery:** Accept `.txt`, `.md`, `.markdown`.
2.  **Normalization:**
    *   Use the shared **Text Normalization** module (see `docs/plans/PROCESS-common-parsing-and-normalization.md`).
    *   Decode bytes -> UTF-8.
    *   Apply standard cleaning (whitespace, line endings, mojibake).
    *   *Artifact:* `staging/_normalized_text/<file_id>.txt`.

### Phase 2: Recipe Splitting (Milestone 2)

**Goal:** Decide if a file is one recipe or many, and slice it accordingly.

1.  **Classification (Heuristics):**
    *   Use shared **Signal Detection** (see `docs/plans/PROCESS-common-parsing-and-normalization.md`) to count ingredients/headers.
    *   **Multi-Recipe Signals:** Multiple top-level Markdown headers (`#`), repeated "Ingredients" headers, clear delimiters (`---`, `***`, `===`).
    *   **Single-Recipe Signals:** Short length, only one "Ingredients" section.
2.  **Splitting Strategy (Order of Operations):**
    1.  **Explicit Delimiter:** If `\n=== RECIPE ===\n` or similar is found, split there.
    2.  **Markdown Heading:** Split on `^#\s+` (and optionally `^##\s+`).
    3.  **Repeated Patterns:** If "Ingredients" appears multiple times disjointly, split around them.
    4.  **Fallback:** Detect title-ish lines (short, Title Case, surrounded by blank lines).
3.  **Output:** List of `RecipeCandidate` chunks (text + line number range).

### Phase 3: Structure Recovery (Milestone 3)

**Goal:** Parse each candidate chunk into fields (Deterministic First).

1.  **Frontmatter:** If file/chunk starts with YAML frontmatter (`---`), parse it as metadata (tags, source, servings).
2.  **Section Detection:**
    *   Use shared **Signal Detection** (see `docs/plans/PROCESS-common-parsing-and-normalization.md`) for headers, ingredients, and instructions.
3.  **Field Extraction:**
    *   **Ingredients:** Lines within the ingredients block.
    *   **Instructions:** Lines within directions block.
    *   **Metadata:** Regex for "Yield:", "Prep time:", "Cook time:".
4.  **LLM Escalation:** 
    *   Trigger only if skeleton confidence is low.
    *   Use the shared **LLM Repair** strategy (see `docs/plans/PROCESS-llm-repair.md`).

### Phase 4: JSON-LD Emission (Milestone 4)

1.  **Emission:**
    *   Use the shared **Reporting and Provenance** standards (see `docs/plans/PROCESS-reporting-and-provenance.md`).
    *   Write `staging/recipesage_jsonld/<file_id>/<candidate_id>.jsonld` with stable IDs.
2.  **Reporting:**
    *   Write `manifest.json` using the standard `ReportBuilder`.

## Concrete Steps

1.  **Create Plugin:** `touch cookimport/plugins/text.py`.
2.  **Implement `TextImporter`:**
    *   `detect`: Check file extensions.
    *   `inspect`: Print split decision (single vs. multi) and detected sections for the first recipe.
    *   `convert`: Run full pipeline.
3.  **Implement `TextNormalizer`:** Encoding handling and whitespace cleanup.
4.  **Implement `RecipeSplitter`:** Logic for multi-recipe detection and slicing.
5.  **Implement `TextParser`:** Logic for identifying headers and extracting lists.

## Validation and Acceptance

*   `cookimport inspect` correctly identifies "multi-recipe" files and prints the count.
*   `cookimport stage` correctly splits a multi-recipe Markdown file into separate JSON-LD files.
*   YAML frontmatter is correctly parsed into metadata fields.
*   Provenance data includes accurate line number ranges for tracing back to the source file.

## Interfaces and Dependencies

*   **PyYAML:** For parsing optional frontmatter.
*   **Regex:** Heavy use for splitting and header detection.