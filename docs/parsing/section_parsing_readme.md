---
summary: "Comprehensive overview of parsing systems (ingredients, instructions, step linking, tips, chunking) and known issues."
read_when:
  - When working on parsing, step linking, or tip/chunk extraction
  - When debugging ingredient parsing, instruction metadata, or parsing signals
  - When tuning tip/knowledge extraction or section chunking
---

# Parsing: Section Overview

This document consolidates the parsing docs in `docs/parsing/` into a single reference. It is meant to be the one-stop context for anyone (human or AI) working on parsing, step linking, or tip/knowledge extraction.

If you only read one thing before touching parsing code, read this.

## Scope and Where It Lives

Parsing spans several cooperating modules under `cookimport/parsing/` and its users in importers and staging. The key pieces are:

- `cookimport/parsing/ingredients.py`: ingredient line parsing and ingredient section header detection
- `cookimport/parsing/instruction_parser.py`: time/temperature extraction from instruction steps
- `cookimport/parsing/cleaning.py`: text normalization (Unicode, mojibake, whitespace, hyphen repair)
- `cookimport/parsing/signals.py`: block/line signals used downstream (heading, ingredient/instruction likelihood, etc.)
- `cookimport/parsing/step_ingredients.py`: ingredient-to-step assignment (exact, semantic, fuzzy)
- `cookimport/parsing/tips.py`: tip mining (legacy “tip” extraction)
- `cookimport/parsing/tip_taxonomy.py`: tag taxonomy used for tips/highlights
- `cookimport/parsing/atoms.py`: atomization for tip mining (paragraph/list/header slicing)
- `cookimport/parsing/chunks.py`: non-recipe knowledge chunking (section-based chunking with lanes/highlights)

Parsing is used by:

- `cookimport/plugins/epub.py`: block segmentation + recipe boundary detection
- `cookimport/staging/draft_v1.py`: recipe candidate to draft conversion
- `cookimport/staging/writer.py`: outputs for tips and chunks

## Parsing Pipeline (High Level)

1. **Input text → normalized text** via `cleaning.py` (Unicode/whitespace/hyphen repair).
2. **Signals** computed via `signals.py` (heading detection, ingredient/instruction likelihood, etc.).
3. **Ingredient parsing** (`ingredients.py`) and **instruction parsing** (`instruction_parser.py`).
4. **Step linking** (`step_ingredients.py`) assigns ingredient lines to instruction steps.
5. **Tips / knowledge**: non-recipe text is mined for tips and/or chunked into larger knowledge chunks (`tips.py`, `chunks.py`).

## Ingredient Parsing

**Location:** `cookimport/parsing/ingredients.py`

Parsing relies on `ingredient-parser-nlp` to extract structured fields from raw ingredient lines. Key fields:

- `quantity_kind`: `exact`, `approximate`, `unquantified`, or `section_header`
- `input_qty`, `raw_unit_text`, `raw_ingredient_text`, `preparation`, `note`, `is_optional`, `confidence`, `raw_text`

### Quantity Kinds

- `exact`: “2 cups flour”
- `approximate`: “salt to taste”, “oil for frying”
- `unquantified`: “fresh parsley”
- `section_header`: “FOR THE SAUCE:”, “Marinade”

### Section Header Detection

Headers are detected via:

- ALL CAPS single words
- “For the X” pattern
- Known keywords like garnish/topping/sauce/dressing/etc.
- No parsed amounts

### Range and Approximate Handling

- Ranges (e.g., “3-4 cups”) convert to midpoint, rounded up
- Approximate phrases include “to taste”, “as needed”, “for serving”, etc.

## Instruction Metadata Extraction

**Location:** `cookimport/parsing/instruction_parser.py`

Extracts time and temperature for instruction steps:

- Time patterns: “X minutes”, “X-Y minutes”, “1 hour 30 minutes”, “1.5 hours”
- Temperature patterns: “350°F”, “180°C”, “350 degrees F”
- Cook time aggregation is sum of step times if not explicitly provided by source

## Text Normalization

**Location:** `cookimport/parsing/cleaning.py`

Normalization includes:

- Unicode NFKC normalization
- Non-breaking spaces → regular spaces
- Mojibake repairs (e.g., `â€™` → `'`, `â€"` → `—`, `Ã©` → `é`)
- Whitespace collapsing
- Hyphenation repair for split words (`ingre-\ndients` → `ingredients`)

## Signal Detection

**Location:** `cookimport/parsing/signals.py`

Signals enrich blocks and lines to drive later classification:

- Heading and heading level
- Ingredient and instruction headers
- Yield/time detection
- Ingredient likelihood and instruction likelihood
- Quantity/unit detection

`ParsingOverrides` supports cookbook-specific overrides:

- Custom ingredient/instruction headers
- Custom imperative verbs
- Custom unit terms

## Step Linking: Ingredient → Instruction Assignment

**Location:** `cookimport/parsing/step_ingredients.py`

### Matching Strategy (Current Behavior)

1. **Exact alias matching**: raw + cleaned aliases, including single-token head/tail aliases.
2. **Semantic fallback** (only if no exact matches):
   - Rule-based lemmatization (suffix stripping + overrides)
   - Curated synonym expansions (e.g., scallion ↔ green onion)
3. **Fuzzy fallback** (only if no exact matches):
   - RapidFuzz near-match rescue
   - Excludes generic tokens to avoid noisy matches

Candidates are tagged with `match_kind` (`exact`, `semantic`, `fuzzy`).

### Collective Term Matching (Category Fallback)

There is a **category-based fallback pass** that assigns otherwise-unmatched ingredients to steps if the step mentions collective terms like “spices”, “seasonings”, or “herbs”.

This was added to avoid dropping ingredients when instructions refer to a group rather than each ingredient by name.

### Known Issues / Tradeoffs

- **Collective term matching can misassign** if a later step references a category (“Cinnamon Cream”) but the category should have been applied earlier.
- Ingredients mentioned only via **highly abstract terms** (e.g., “dough”, “mixture”) can remain unassigned.
- Fuzzy matching is intentionally constrained but can still introduce **false positives** for typos and near-miss tokens.

## EPUB Recipe Segmentation Fixes

**Location:** `cookimport/plugins/epub.py`

The EPUB importer has special handling for subsection headers inside recipes. Common cookbook patterns like “For the Frangipane” or “For the Tart” are treated as **ingredient section headers** and **not** as new recipe titles.

The key behavior:

- `_find_recipe_end()` skips “For the X” style headers so the recipe isn’t split incorrectly.

This fix was added after encountering recipes where subsection headers were mistakenly treated as new recipe starts (leading to empty or split recipes).

## Tips and Knowledge Extraction

This area has two related, distinct outputs:

1. **Legacy tip extraction** (tips are the primary outputs)
2. **Knowledge chunking** (chunks are primary outputs; tips become highlights)

### Legacy Tip Extraction

**Locations:** `cookimport/parsing/tips.py`, `cookimport/parsing/atoms.py`, `cookimport/parsing/tip_taxonomy.py`

Tips are extracted from non-recipe text and certain recipe metadata. The pipeline:

- Atomizes text into paragraphs/list items/headers
- Extracts tip spans based on anchors (“TIP:”, “NOTE:”, advice verbs, etc.)
- Repairs clipped tips by merging with neighbor atoms
- Scores tipness and generality
- Tags tips using a dictionary-based taxonomy

Outputs are written to:

- `data/output/<timestamp>/tips/<workbook_stem>/t{index}.json`
- `data/output/<timestamp>/tips/<workbook_stem>/tips.md`

Known tradeoffs:

- High precision but **recall-limited** for longer explanations
- **Aphorisms** can be extracted without their supporting context

### Knowledge Chunking (Chunk-First Pipeline)

**Locations:** `cookimport/parsing/chunks.py`, `cookimport/staging/writer.py`

Chunking creates **coherent, section-aligned** knowledge blocks from non-recipe text. It is designed to avoid orphan tips and preserve context.

Current behavior (implemented):

- Deterministic, heading-driven chunking of non-recipe blocks
- Lane assignment: `knowledge`, `narrative`, `noise`
- Tip miner is reused to create **highlights** inside each chunk
- Chunk boundaries include hard/medium/soft types (headings, callouts, formatting shifts)
- Small chunks are merged to keep outputs coherent

Outputs are written to:

- `data/output/<timestamp>/chunks/<workbook_stem>/c{index}.json`
- `data/output/<timestamp>/chunks/<workbook_stem>/chunks.md`

### Known Issues / Future Options

- Optional chunk **distillation** via mocked LLM layer is not implemented unless explicitly enabled; chunk outputs remain deterministic.
- Lane assignment is heuristic-based; false positives/negatives are possible for borderline narrative vs knowledge content.

## Tests and Validation

Key tests live under `tests/`, notably:

- `tests/test_chunks.py` for chunking behavior and lane assignment
- Step-ingredient linking tests for matching and collective term behavior

Typical validation commands:

```bash
source .venv/bin/activate
pytest tests/ -v
```

### Manual Spot Checks

- Run `python -m cookimport.cli stage data/input/<cookbook>`
- Inspect `chunks.md` and `tips.md`
- Confirm known failure modes are mitigated (blurbs → noise, headings → coherent chunks, aphorisms demoted to highlights)

## Known Bad / Sharp Edges (Avoid Repeating)

- **Subsection headers** in EPUBs are common; do not regress `_find_recipe_end()` into treating “For the X” as a recipe boundary.
- **Collective ingredient terms** are common (“spices”, “seasonings”). Removing or weakening the category fallback will drop ingredients.
- **Tip extraction** alone is insufficient for coherent knowledge; chunking should remain the primary path for non-recipe text.
- **Lane assignment** is heuristics-first; if you add ML options, keep deterministic fallback as the default.

## Outputs and Where to Look

- Ingredient parsing: `cookimport/parsing/ingredients.py`
- Instruction parsing: `cookimport/parsing/instruction_parser.py`
- Step linking: `cookimport/parsing/step_ingredients.py`
- Tip outputs: `data/output/<timestamp>/tips/<workbook_stem>/`
- Chunk outputs: `data/output/<timestamp>/chunks/<workbook_stem>/`

## Quick “What Changed” Notes

- “For the X” subsection headers are treated as in-recipe section headers, not new recipes.
- Collective term matching assigns otherwise-unmatched ingredients to steps referencing category terms like “spices”.
- Knowledge chunking is the preferred output for non-recipe text; tips are reused as highlights.
