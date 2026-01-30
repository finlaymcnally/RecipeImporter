---
summary: "Extract time and temperature metadata from instruction text using patterns inspired by sharp-recipe-parser"
read_when:
  - When working on instruction parsing or step metadata
  - When adding time/temperature extraction to recipes
  - When considering schema.org HowToStep extensions
---

# Instruction Metadata Extraction: Time & Temperature

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

The cookimport pipeline currently extracts instruction text but doesn't parse structured metadata from it. The `sharp-recipe-parser` (JS/npm) demonstrates that instruction text like "Bake at 400F for 30 minutes" can yield:

- **Temperature**: 400°F (with Celsius conversion)
- **Time**: 30 minutes (1800 seconds)

After this change, users gain:

1. **Structured time/temp per step** — Each instruction step can have extracted `timeInSeconds`, `temperature`, and `temperatureUnit` metadata.

2. **Computed total cook time** — When recipe-level `cookTime` is missing, sum step times to estimate it.

3. **Better recipe search/filtering** — Downstream systems can filter recipes by cooking temperature or total time.

To see it working: run `cookimport stage some-recipe.pdf` and observe that instruction steps include extracted time and temperature where present.

## Progress

- [x] Initial ExecPlan drafted.
- [x] Milestone 1: Create instruction parser module.
- [x] Milestone 2: Extend HowToStep model with metadata fields.
- [x] Milestone 3: Integrate into pipeline and compute aggregates.
- [x] Milestone 4 (Optional): Add unit conversions (F↔C).

## Surprises & Discoveries

- The regex patterns for time/temp extraction were simpler than expected. Using `(?!\w)` word boundary for temperature prevents false positives on things like "2 cups".
- Time ranges (e.g., "12-15 minutes") use midpoint calculation, which feels more accurate than min/max.
- The existing `draft_v1.py` was a natural integration point since it already processes instructions step-by-step.

## Decision Log

- Decision: Port logic to Python rather than calling Node.js subprocess.
  Rationale: The project already took this approach with the classifier (see `classifier.py`). Heuristic Python code is more maintainable, has no external runtime dependency, and is easier to debug. The sharp-recipe-parser patterns are simple enough to port.
  Date/Author: 2026-01-29 / Agent

- Decision: Use optional metadata fields on HowToStep rather than a new model.
  Rationale: Keep compatibility with schema.org Recipe. The HowToStep spec doesn't have time/temp fields, but we can add them as extensions in our internal model and strip them when outputting standard JSON-LD.
  Date/Author: 2026-01-29 / Agent

- Decision: Keep ingredient parsing as-is (ingredient-parser-nlp).
  Rationale: User confirmed ingredient parsing is "the best part" of the current pipeline. sharp-recipe-parser has ingredient parsing too, but we don't need to replace what works.
  Date/Author: 2026-01-29 / Agent

## Outcomes & Retrospective

**Implemented 2026-01-29:**

1. Created `cookimport/parsing/instruction_parser.py` with:
   - `TimeItem` and `InstructionMetadata` dataclasses
   - `parse_instruction(text)` for single instruction parsing
   - `parse_instructions(steps)` for batch parsing
   - `fahrenheit_to_celsius()` and `celsius_to_fahrenheit()` conversions

2. Extended `HowToStep` model with optional fields:
   - `time_seconds: int | None`
   - `temperature: float | None`
   - `temperature_unit: str | None`

3. Integrated into `draft_v1.py`:
   - Each step gets `time_seconds`, `temperature`, `temperature_unit` when extracted
   - Recipe gets `cook_time_seconds` computed from step times when missing

4. 30 unit tests covering time, temperature, combined extraction, and edge cases.

**Files created/modified:**
- `cookimport/parsing/instruction_parser.py` (new)
- `cookimport/parsing/__init__.py` (updated exports)
- `cookimport/core/models.py` (HowToStep extended)
- `cookimport/staging/draft_v1.py` (integration)
- `tests/test_instruction_parser.py` (new)

## Context and Orientation

**Reference implementation:** [jlucaspains/sharp-recipe-parser](https://github.com/jlucaspains/sharp-recipe-parser) - a JS library that parses:
- Ingredients: quantity, unit, ingredient name, prep notes
- Instructions: time durations, temperatures

We're only interested in the **instruction parsing** part:
- Extract time: "30 minutes", "1 hour", "2-3 hours" → seconds
- Extract temperature: "400F", "180°C", "350 degrees" → value + unit

**Existing code to modify:**

- `cookimport/core/models.py` — Add optional fields to `HowToStep` for time/temp metadata.

- `cookimport/parsing/` — New module `instruction_parser.py` for extraction logic.

- `cookimport/staging/draft_v1.py` or `jsonld.py` — May need to handle new metadata when outputting.

**What sharp-recipe-parser returns for instructions:**

```javascript
{
  totalTimeInSeconds: number,       // Sum of all time items
  timeItems: [{
    timeInSeconds: number,
    timeUnitText: string,           // "minutes", "hours"
    timeText: string                // "30", "1-2"
  }],
  temperature: number,              // 400
  temperatureText: string,          // "400"
  temperatureUnit: string,          // "fahrenheit" or "celsius"
  temperatureUnitText: string,      // "F", "°C"
  alternativeTemperatures: [...]    // Conversions
}
```

## Plan of Work

### Milestone 1: Create Instruction Parser Module

**Goal:** A Python module that extracts time and temperature from instruction text using pattern matching.

**What exists after this milestone:** `cookimport/parsing/instruction_parser.py` with functions to parse a single instruction string and return structured data.

**Edits:**

1. Create `cookimport/parsing/instruction_parser.py` with:
   - `@dataclass InstructionMetadata` with fields:
     - `total_time_seconds: int | None`
     - `time_items: list[TimeItem]`
     - `temperature: float | None`
     - `temperature_unit: Literal["fahrenheit", "celsius"] | None`
   - `@dataclass TimeItem` with `seconds: int`, `original_text: str`
   - Function `parse_instruction(text: str) -> InstructionMetadata`
   - Pattern matching for:
     - Time: `\d+\s*(minutes?|mins?|hours?|hrs?|seconds?|secs?|days?)`
     - Temperature: `\d+\s*°?\s*(F|C|fahrenheit|celsius|degrees?\s*(F|C))`

2. Add comprehensive tests in `tests/test_instruction_parser.py`:
   - "Bake at 400F for 30 minutes" → temp=400, unit=fahrenheit, time=1800s
   - "Simmer for 1-2 hours" → time range handling
   - "Cook until golden" → no time extracted
   - "Preheat oven to 180°C" → temp=180, unit=celsius

**Validation:** Run `pytest tests/test_instruction_parser.py -v` and verify all test cases pass.

### Milestone 2: Extend HowToStep Model

**Goal:** Add optional metadata fields to the HowToStep model for storing extracted data.

**What exists after this milestone:** `HowToStep` has optional `time_seconds`, `temperature`, `temperature_unit` fields that can be populated during parsing.

**Edits:**

1. Modify `cookimport/core/models.py`:
   - Add to `HowToStep`:
     ```python
     time_seconds: int | None = Field(default=None, alias="timeSeconds")
     temperature: float | None = None
     temperature_unit: str | None = Field(default=None, alias="temperatureUnit")
     ```
   - These are extension fields not in schema.org, but useful for our pipeline.

2. Ensure JSON serialization works:
   - When outputting to schema.org JSON-LD, these fields should be included (they'll be ignored by strict consumers but useful for our downstream processing).

**Validation:** Create a HowToStep with metadata, serialize to JSON, verify fields appear.

### Milestone 3: Pipeline Integration

**Goal:** Automatically extract instruction metadata during recipe processing and compute aggregate times.

**What exists after this milestone:** All instruction steps have metadata extracted. Recipe-level `cookTime` is computed from step times when not already present.

**Edits:**

1. Create helper function in `instruction_parser.py`:
   - `parse_instructions(steps: list[str]) -> list[tuple[str, InstructionMetadata]]`
   - Process all steps, return text with metadata.

2. Modify importers or a central processing step:
   - After instructions are extracted but before final `RecipeCandidate` creation, run `parse_instruction()` on each step.
   - If the recipe has no `cook_time` but steps have times, compute and set it.
   - Identify steps with temperatures for potential `cookingMethod` hints (baking = oven temp, etc.).

3. Update relevant importers (`pdf.py`, `epub.py`, `text.py`, etc.) or the staging layer to call the parser.

**Validation:**
- Run `cookimport stage` on a real recipe file.
- Verify instruction steps have `timeSeconds` and `temperature` populated where applicable.
- Verify `cookTime` is computed when missing.

### Milestone 4 (Optional): Unit Conversions

**Goal:** Provide temperature conversions (F↔C) in the metadata.

**What exists after this milestone:** Each extracted temperature includes its alternative unit conversion.

**Edits:**

1. Add conversion functions to `instruction_parser.py`:
   - `fahrenheit_to_celsius(f: float) -> float`
   - `celsius_to_fahrenheit(c: float) -> float`

2. Add `alternative_temperature` field to metadata:
   - If temp is in F, also provide C equivalent
   - Round to sensible precision (whole numbers for temps)

**Validation:** "Bake at 400F" returns temp=400 F with alternative=204 C.

## Concrete Steps

### Milestone 1: Instruction Parser

Working directory: `/home/mcnal/projects/recipeimport`

```bash
# 1. Create the parser module
# Create cookimport/parsing/instruction_parser.py (see Plan of Work)

# 2. Create tests
# Create tests/test_instruction_parser.py

# 3. Run tests
source .venv/bin/activate
pytest tests/test_instruction_parser.py -v
```

### Milestone 2: Model Extension

```bash
# 1. Modify cookimport/core/models.py
# Add optional fields to HowToStep

# 2. Verify serialization
python -c "from cookimport.core.models import HowToStep; print(HowToStep(text='Test', time_seconds=60).model_dump_json())"
```

### Milestone 3: Pipeline Integration

```bash
# 1. Integrate parser into recipe processing
# Modify staging/draft_v1.py or relevant importers

# 2. Test with real files
cookimport stage data/input/some-cookbook.pdf --output-dir data/output/instruction-test

# 3. Inspect output
cat data/output/instruction-test/recipes.json | jq '.[] | .instructions'
```

## Validation and Acceptance

**Milestone 1 acceptance:** Unit tests pass for:
- Simple time extraction: "for 30 minutes" → 1800 seconds
- Temperature extraction: "at 400F" → 400, fahrenheit
- Combined: "Bake at 350°F for 45 minutes" → both extracted
- Edge cases: "until done", "over medium heat" → no false positives

**Milestone 2 acceptance:** HowToStep model accepts and serializes metadata fields.

**Milestone 3 acceptance:** Run `cookimport stage` on a recipe with instructions like "Bake at 400F for 30 minutes." Verify:
- The instruction step has `timeSeconds: 1800`
- The instruction step has `temperature: 400` and `temperatureUnit: "fahrenheit"`
- If recipe had no `cookTime`, it's now populated with summed step times

**Overall acceptance:** The extraction is reasonably accurate on typical recipe instructions without false positives on non-time/temp text.

## Interfaces and Dependencies

**New interfaces:**

```python
# cookimport/parsing/instruction_parser.py

@dataclass
class TimeItem:
    seconds: int
    original_text: str

@dataclass
class InstructionMetadata:
    total_time_seconds: int | None
    time_items: list[TimeItem]
    temperature: float | None
    temperature_unit: Literal["fahrenheit", "celsius"] | None
    temperature_text: str | None

def parse_instruction(text: str) -> InstructionMetadata:
    """Extract time and temperature from an instruction string."""
    ...
```

**Model extensions:**

```python
# In HowToStep
time_seconds: int | None = Field(default=None, alias="timeSeconds")
temperature: float | None = None
temperature_unit: str | None = Field(default=None, alias="temperatureUnit")
```

**No external dependencies added.** This is pure Python pattern matching.

## Patterns to Port from sharp-recipe-parser

The JS library uses tokenization + unit lookup. Key patterns to implement:

**Time patterns:**
- `\d+` followed by time unit token (minutes, hours, seconds, days)
- Handle ranges: "1-2 hours" → take midpoint or min
- Unit multipliers: minute=60, hour=3600, day=86400

**Temperature patterns:**
- `\d+` followed by temp unit token (F, C, °F, °C, fahrenheit, celsius)
- Also: "degrees F", "degrees fahrenheit"
- Common temps: 350, 375, 400, 425, 450 (F) or 180, 200, 220 (C)

**What NOT to extract (avoid false positives):**
- "Step 1", "serves 4" — numbers not followed by time/temp units
- "medium heat", "high heat" — qualitative, not quantitative
