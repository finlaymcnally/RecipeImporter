---
summary: "ExecPlan for shared text parsing, normalization, and signal detection logic."
read_when:
  - When implementing parsing logic for any importer (Text, PDF, EPUB, etc.)
---

# Common Parsing and Normalization ExecPlan

This ExecPlan defines the shared logic for text normalization, feature extraction, and signal detection. Instead of each importer re-inventing how to spot an ingredient line or clean up mojibake, they will use this central library.

## Purpose / Big Picture

To provide a single, robust source of truth for "what looks like a recipe" and "how to clean text". This ensures that improvements to ingredient detection or text cleanup benefit all importers (PDF, EPUB, Text, etc.) simultaneously.

## Core Modules

### 1. Text Normalization (`cookimport.parsing.cleaning`)

**Goal:** Turn messy raw strings into clean, predictable Unicode.

*   **Unicode Normalization:** Convert all text to NFKC (or NFC) to handle composed characters consistently.
*   **Mojibake Repair:** Fix common encoding errors (e.g., `â€™` -> `'`) using `ftfy` or similar heuristics.
*   **Whitespace Standardization:**
    *   Collapse multiple spaces/tabs to single spaces.
    *   Normalize all line endings to `
`.
    *   Strip non-breaking spaces (`\xa0`) and other invisible control characters.
*   **Hyphenation Repair:** (Critical for PDF/EPUB) Rejoin words split across lines (e.g., `ingre-

dient` -> `ingredient`) based on dictionary lookups or heuristics.

### 2. Feature/Signal Detection (`cookimport.parsing.signals`)

**Goal:** Detect semantic meaning in text blocks without full parsing. Returns confidence scores or boolean flags.

*   **Ingredient Signals:**
    *   `starts_with_quantity`: Regex for leading numbers, fractions (`1/2`, `½`), and ranges (`1-2`).
    *   `has_unit`: Regex for common units (cup, g, oz, tbsp, etc.) immediately following a quantity.
    *   `is_ingredient_likely`: Combination of quantity + unit + food-word lookup (optional).
*   **Instruction Signals:**
    *   `starts_with_number`: Regex for `1.`, `Step 1:`, `A)`.
    *   `imperative_verb_score`: Checks if the sentence starts with a strong cooking verb (Mix, Bake, Stir, Whisk).
*   **Structure Signals:**
    *   `is_header_likely`: Checks for short length, lack of terminal punctuation, title case, or specific keywords ("Ingredients", "Method").
    *   `is_yield_pattern`: Regex for "Serves X", "Yield: ...".
    *   `is_time_pattern`: Regex for "Prep time:", "Cook:", "Total:".

### 3. Block & Stream Model (`cookimport.core.blocks`)

**Goal:** A shared intermediate representation for documents that aren't yet recipes.

*   **Block Object:**
    *   `text`: The normalized content.
    *   `type`: inferred type (Text, Image, Table).
    *   `layout`: (Optional) Bounding box, page number, indentation level.
    *   `style`: (Optional) Font size, weight, alignment.
    *   `features`: Cached dictionary of signals (e.g., `{"is_ingredient": 0.9}`).

## Implementation Strategy

1.  **Centralize Regex:** Move all specific regex patterns (units, times, headers) into `cookimport/parsing/patterns.py` so they are not hardcoded in plugins.
2.  **Shared "Detector" Class:** Create a class that takes a string (or Block) and returns a `FeatureVector`.
3.  **Progressive Enhancement:** Start with simple regexes. If those fail, add dictionary lookups or lightweight NLP (spacy/nltk) later without breaking the API.

## Integration Point

*   **Importers (PDF, EPUB, Text)** will import these functions to classify blocks *before* deciding where a recipe starts or ends.
*   **LLM Escalation** will use the normalized text, preventing token waste on garbage characters.

## Context from "Thoughts"

*   "Text normalization layer before features/heuristics."
*   "Feature/signal logic is duplicated... centralize this."
*   "Keep extraction deterministic first."

## Future Enhancements (from Improving_Recipe_Import_Pipeline.md)

**SpaCy NLP Integration:**
- Rule-based Matcher for phrase patterns (e.g., "if you don't have X" for substitution notes)
- Part-of-speech tagging to differentiate instructions (imperative verbs) from statements
- Entity ruler for custom cooking terms/ingredients
- TextCategorizer component for trainable tip vs non-tip classification

**Cookbook-Specific Overrides:**
- Allow per-cookbook parsing rules when consistent signals are discovered
- Example: some books use italicized paragraphs for tips—capture italic markers if available
- Hardcoded tweaks for specific book series are acceptable for personal use

**Testing and Validation:**
- Maintain "golden set" of pages with tricky formatting
- Log all paragraphs classified as tips with decision reasons
- Compare results cookbook-by-cookbook to spot systematic issues

## Implementation Status

*   **2026-01-22:** Implemented Core Modules.
    *   `cookimport.core.blocks`: Implemented `Block` model and `BlockType` enum.
    *   `cookimport.parsing.cleaning`: Implemented `normalize_text`, `fix_mojibake`, `standardize_whitespace`, `repair_hyphenation`. Added extra French mojibake cases.
    *   `cookimport.parsing.patterns`: Centralized regex for quantities, units, headers, times, etc.
    *   `cookimport.parsing.signals`: Implemented `classify_block` using patterns.
    *   Verified via manual test script `tests/test_phase1_manual.py`.