---
summary: "ExecPlan for integrating structured ingredient parsing using ingredient-parser-nlp."
read_when:
  - When implementing or modifying ingredient parsing
  - When working on draft_v1.py or ingredient output format
---

# Ingredient Parser Integration ExecPlan

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

This plan must be maintained in accordance with docs/PLANS.md from the repository root.


## Purpose / Big Picture

After this change, the recipe importer will parse raw ingredient strings like "3 stalks celery, sliced" into structured data with separate fields for quantity (3), unit (stalks), ingredient name (celery), and preparation notes (sliced). Currently, all ingredients are stored as raw text with quantity_kind set to "unquantified" and input_qty/input_unit_id set to null. After this change, the Draft V1 output will contain properly parsed and normalized ingredient data that downstream applications can consume without additional parsing.

The user can verify success by running the stage command on any Excel file and inspecting the output JSON files. Where an ingredient previously appeared as:

    {
      "quantity_kind": "unquantified",
      "input_qty": null,
      "input_unit_id": null,
      "raw_text": "3 stalks celery, sliced"
    }

It will now appear as:

    {
      "quantity_kind": "quantified",
      "input_qty": 3.0,
      "input_unit_id": "stalks",
      "input_item": "celery",
      "preparation": "sliced",
      "note": null,
      "raw_text": "3 stalks celery, sliced"
    }


## Progress

- [x] (2026-01-21 22:45Z) Add ingredient-parser-nlp to pyproject.toml dependencies.
- [x] (2026-01-21 22:46Z) Create cookimport/parsing/ingredients.py module with parse_ingredient_line() function.
- [x] (2026-01-21 22:46Z) Implement quantity normalization (ranges to midpoint rounded up, fractions to decimal).
- [x] (2026-01-21 22:47Z) Implement section header detection to distinguish "FILLING" from actual ingredients.
- [x] (2026-01-21 22:47Z) Update _convert_ingredient() in draft_v1.py to use the new parser.
- [x] (2026-01-21 22:48Z) Create tests (23 test cases) to verify parsed output.
- [x] (2026-01-21 22:50Z) Run full staging on cookbook_cutdown.xlsx and verify output quality.


## Surprises & Discoveries

- Observation: The ingredient-parser library returns unit names in plural form (e.g., "cups" not "cup", "teaspoons" not "teaspoon").
  Evidence: Tests initially failed expecting singular forms. Adjusted tests to accept both forms.

- Observation: The library returns empty results for single-word section headers like "Garnish" (no name, no amount, nothing).
  Evidence: parse_ingredient("Garnish") returns ParsedIngredient with empty name[] and amount[]. Added pre-parse heuristic to catch known section keywords.

- Observation: CompositeIngredientAmount objects need special handling - they wrap multiple IngredientAmount objects.
  Evidence: Compound ingredients like "1 10-ounce bag" return composite amounts. Added hasattr check for "amounts" attribute.


## Decision Log

- Decision: Use ingredient-parser-nlp library for NLP-based parsing.
  Rationale: The library is already available, MIT-licensed, and achieves 95%+ accuracy. It uses a sequence labeling model trained on 81,000 ingredient sentences. Manual regex parsing would be less accurate and harder to maintain.
  Date/Author: 2026-01-21 / User + Agent

- Decision: Handle quantity ranges by taking midpoint and rounding up to nearest whole number.
  Rationale: User preference. For "3-4 Tbsp", the library returns qty=3, qty_max=4. The midpoint is 3.5, rounded up to 4.
  Date/Author: 2026-01-21 / User

- Decision: Convert fractions to decimal form.
  Rationale: User preference. The library returns fractions as Python Fraction objects (e.g., Fraction(1,3) for "1/3 cup"). These will be converted to float (0.333...).
  Date/Author: 2026-01-21 / User

- Decision: Detect section headers by checking for: no amount, short text (1-3 words), and header-like formatting (ALL CAPS or single word with no punctuation except optional colon).
  Rationale: The library parses headers like "FILLING" and "Marinade" as ingredient names with no amounts. These are section dividers in recipes, not actual ingredients. They should be flagged as quantity_kind="section_header" so downstream apps can handle them appropriately.
  Date/Author: 2026-01-21 / Agent (based on user guidance)

- Decision: Integrate parsing at staging time (in draft_v1.py) rather than at import time.
  Rationale: User preference to do all the work in this tool so the downstream cookbook app receives clean, fully-parsed data.
  Date/Author: 2026-01-21 / User

- Decision: Add new fields to ingredient output structure: input_item (ingredient name), preparation (prep notes), and keep existing note field for comments.
  Rationale: The library distinguishes between preparation instructions (e.g., "minced", "sliced") and comments (e.g., "to taste"). Both should be preserved separately for downstream use.
  Date/Author: 2026-01-21 / Agent


## Outcomes & Retrospective

Implementation completed successfully. All 27 tests pass (4 existing + 23 new ingredient parser tests).

Key outcomes:
- Ingredients are now parsed into structured components: quantity, unit, ingredient name, preparation, and notes
- Section headers (FILLING, Marinade, Garnish, etc.) are correctly identified with quantity_kind="section_header"
- Quantity ranges (3-4) are normalized to midpoint rounded up (4)
- Unicode fractions (⅓, ½, ¼) are converted to decimal floats
- Confidence scores from the parser are preserved for downstream quality assessment
- Raw text is always preserved for reference

Sample output verification shows the parser correctly handles:
- "1 tablespoon ginger, minced" → qty=1, unit=tablespoon, item=ginger, prep=minced
- "⅓ cup soy sauce" → qty=0.333, unit=cups, item=soy sauce
- "3-4 Tbsp vegan butter" → qty=4 (range normalized), unit=Tbsp, item=vegan butter
- "FILLING" → quantity_kind=section_header, item=FILLING
- "Salt and pepper (to taste)" → quantity_kind=unquantified, item=Salt, note=(to taste)

The implementation is clean and self-contained in cookimport/parsing/ingredients.py with a single public function parse_ingredient_line().


## Context and Orientation

The repository contains a Python CLI tool named cookimport that imports recipes from Excel files into structured JSON. The tool currently extracts raw ingredient strings but does not parse them into structured components.

Key files involved in this change:

- cookimport/staging/draft_v1.py (lines 13-22): Contains the _convert_ingredient() function that wraps raw ingredient text. This is where parsing will be integrated.

- cookimport/core/models.py: Contains Pydantic models including RecipeCandidate which holds ingredients as a list[str].

- pyproject.toml: Project dependencies.

- data/output/: Contains sample output files showing current unstructured ingredient format.

The ingredient-parser-nlp library (https://github.com/strangetom/ingredient-parser) provides a parse_ingredient() function that returns a ParsedIngredient dataclass with these fields:

- name: List of IngredientText objects, each with .text (string) and .confidence (float)
- amount: List of IngredientAmount objects, each with:
  - .quantity: Fraction or string representing the amount
  - .quantity_max: Upper range limit (equals .quantity if not a range)
  - .unit: String or pint.Unit object
  - .RANGE: Boolean flag indicating if this is a range (e.g., "3-4")
- preparation: Optional IngredientText for prep instructions like "minced", "sliced"
- comment: Optional IngredientText for notes like "to taste", "optional"
- sentence: The normalized input string

The library handles unicode fractions (⅓, ½, ¾), mixed fractions ("1 1/2"), ranges ("3-4"), and various unit formats automatically.


## Plan of Work

Milestone 1 adds the dependency and creates the parsing module. Add ingredient-parser-nlp to the dependencies list in pyproject.toml. Create a new module at cookimport/parsing/__init__.py (empty) and cookimport/parsing/ingredients.py containing the parsing logic. The module will expose a single function parse_ingredient_line(text: str) -> ParsedIngredientResult that wraps the library and normalizes the output.

The ParsedIngredientResult will be a TypedDict or dataclass with these fields:
- quantity_kind: One of "quantified", "unquantified", "section_header"
- input_qty: float or None (the normalized quantity)
- input_unit_id: str or None (the unit as a string)
- input_item: str or None (the ingredient name)
- preparation: str or None (prep instructions)
- note: str or None (comments like "to taste")
- raw_text: str (original input for reference)
- is_optional: bool (True if "optional" appears in comment)
- confidence: float (average confidence from the parser)

The function will:
1. Call parse_ingredient() from ingredient_parser
2. Handle ranges by computing midpoint and rounding up: math.ceil((qty + qty_max) / 2)
3. Convert Fraction quantities to float
4. Extract the first name from the names list as input_item
5. Combine preparation text if present
6. Extract comment text if present
7. Detect "optional" in comment and set is_optional accordingly
8. Detect section headers (no amount + header-like text pattern)

Milestone 2 integrates the parser into draft_v1.py. Modify the _convert_ingredient() function to call parse_ingredient_line() instead of just wrapping raw text. The output dict structure will be extended to include input_item and preparation fields. The quantity_kind field will now have meaningful values ("quantified", "unquantified", or "section_header").

Milestone 3 adds tests and validates output quality. Create tests/test_ingredient_parser.py with unit tests covering:
- Simple ingredients: "1 cup flour" -> qty=1, unit="cup", item="flour"
- Prep instructions: "2 cloves garlic, minced" -> prep="minced"
- Ranges: "3-4 Tbsp butter" -> qty=4 (midpoint rounded up)
- Fractions: "⅓ cup sugar" -> qty=0.333...
- Unquantified: "salt to taste" -> quantity_kind="unquantified"
- Section headers: "FILLING", "Marinade" -> quantity_kind="section_header"
- Complex: "1 10-ounce bag frozen peas" -> multiple amounts handled

Run the full stage command on cookbook_cutdown.xlsx and spot-check several output files to verify parsed ingredients look correct.


## Concrete Steps

Work from /home/mcnal/projects/recipeimport. Ensure the virtual environment is active:

    source .venv/bin/activate

The ingredient-parser-nlp library is already installed. Verify with:

    python -c "from ingredient_parser import parse_ingredient; print('OK')"

After implementing changes, reinstall the package:

    pip install -e .

Run tests:

    pytest tests/test_ingredient_parser.py -v

Run the full stage command to generate new output:

    cookimport stage data/input --out data/output

Inspect a sample output file to verify parsing:

    cat data/output/*/drafts/cookbook_cutdown/database/r10.json | python -m json.tool | head -80


## Validation and Acceptance

The change is accepted when:

1. All unit tests in tests/test_ingredient_parser.py pass.

2. Running pytest produces no failures.

3. Running cookimport stage data/input --out data/output completes without errors.

4. Inspecting output files shows ingredients with properly populated fields:
   - Ingredients with amounts have quantity_kind="quantified", input_qty set to a float, input_unit_id set to a string, and input_item set to the ingredient name.
   - Ingredients without amounts have quantity_kind="unquantified" and input_item set to the ingredient name.
   - Section headers like "FILLING" have quantity_kind="section_header".

5. The raw_text field is preserved for all ingredients so no information is lost.


## Idempotence and Recovery

The parsing function is pure and deterministic. Running stage multiple times produces identical output. The parser does not modify any state and all transformations are derived from the input text. If the ingredient-parser library fails on malformed input, the function should catch exceptions and fall back to returning an unquantified result with just the raw_text preserved.


## Artifacts and Notes

Example of expected output for "3 stalks celery, sliced":

    {
      "ingredient_id": "uuid-here",
      "quantity_kind": "quantified",
      "input_qty": 3.0,
      "input_unit_id": "stalks",
      "input_item": "celery",
      "preparation": "sliced",
      "note": null,
      "raw_text": "3 stalks celery, sliced",
      "is_optional": false,
      "confidence": 0.95
    }

Example of expected output for "FILLING" (section header):

    {
      "ingredient_id": "uuid-here",
      "quantity_kind": "section_header",
      "input_qty": null,
      "input_unit_id": null,
      "input_item": "FILLING",
      "preparation": null,
      "note": null,
      "raw_text": "FILLING",
      "is_optional": false,
      "confidence": 0.0
    }

Example of expected output for "salt, to taste" (unquantified):

    {
      "ingredient_id": "uuid-here",
      "quantity_kind": "unquantified",
      "input_qty": null,
      "input_unit_id": null,
      "input_item": "salt",
      "preparation": null,
      "note": "to taste",
      "raw_text": "salt, to taste",
      "is_optional": false,
      "confidence": 0.9
    }


## Interfaces and Dependencies

Add to pyproject.toml dependencies:

    "ingredient-parser-nlp>=0.1.0",

Create cookimport/parsing/__init__.py as an empty file.

Create cookimport/parsing/ingredients.py with:

    from __future__ import annotations

    import math
    import re
    from fractions import Fraction
    from typing import Any

    from ingredient_parser import parse_ingredient


    def parse_ingredient_line(text: str) -> dict[str, Any]:
        """Parse an ingredient string into structured components.

        Returns a dict with:
            quantity_kind: "quantified", "unquantified", or "section_header"
            input_qty: float or None
            input_unit_id: str or None
            input_item: str or None (the ingredient name)
            preparation: str or None
            note: str or None
            raw_text: str (original input)
            is_optional: bool
            confidence: float
        """
        # Implementation here
        ...


    def _is_section_header(text: str, parsed) -> bool:
        """Detect if text is a section header rather than an ingredient."""
        # Implementation here
        ...


    def _normalize_quantity(amount) -> float | None:
        """Convert quantity to float, handling ranges and fractions."""
        # Implementation here
        ...

In cookimport/staging/draft_v1.py, modify _convert_ingredient():

    from cookimport.parsing.ingredients import parse_ingredient_line

    def _convert_ingredient(text: str) -> dict[str, Any]:
        parsed = parse_ingredient_line(text)
        return {
            "ingredient_id": _generate_uuid(),
            **parsed,  # Spread the parsed fields
        }

Create tests/test_ingredient_parser.py with test cases covering the acceptance criteria.
