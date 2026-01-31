---
summary: "Ingredient parsing, instruction metadata extraction, and text normalization."
read_when:
  - Working on ingredient line parsing
  - Extracting time/temperature from instructions
  - Understanding text preprocessing pipeline
---

# Parsing Pipeline

The parsing phase transforms raw text into structured data.

## Ingredient Parsing

**Location:** `cookimport/parsing/ingredients.py`

**Library:** [ingredient-parser-nlp](https://ingredient-parser.readthedocs.io/) - NLP-based decomposition

### Input/Output Example

```python
parse_ingredient_line("3 stalks celery, sliced")
# Returns:
{
    "quantity_kind": "exact",      # exact | approximate | unquantified | section_header
    "input_qty": 3.0,              # Numeric quantity (float)
    "raw_unit_text": "stalks",     # Unit as written
    "raw_ingredient_text": "celery",  # Ingredient name
    "preparation": "sliced",       # Prep instructions
    "note": None,                  # Additional notes
    "is_optional": False,          # Detected from "(optional)"
    "confidence": 0.92,            # Parser confidence
    "raw_text": "3 stalks celery, sliced"  # Original input
}
```

### Quantity Kinds

| Kind | Description | Example |
|------|-------------|---------|
| `exact` | Numeric quantity present | "2 cups flour" |
| `approximate` | Vague quantity | "salt to taste", "oil for frying" |
| `unquantified` | No quantity detected | "fresh parsley" |
| `section_header` | Ingredient group label | "FOR THE SAUCE:", "Marinade" |

### Section Header Detection

Headers are identified by:
- ALL CAPS single words: "FILLING", "MARINADE"
- "For the X" pattern: "For the Filling"
- Known keywords: garnish, topping, sauce, dressing, crust, glaze, etc.
- No amounts parsed from text

### Range Handling

Ranges like "3-4 cups" → midpoint rounded up (4.0)

### Approximate Phrases

Detected patterns:
- "to taste", "as needed", "as desired"
- "for serving", "for garnish", "for frying"
- "for greasing", "for the pan"

---

## Instruction Metadata Extraction

**Location:** `cookimport/parsing/instruction_parser.py`

Extracts time and temperature from instruction text.

### Time Extraction

```python
parse_instruction("Bake for 25-30 minutes until golden.")
# Returns:
{
    "total_time_seconds": 1650,  # Midpoint of range (27.5 min)
    "temperature": None,
    "temperature_unit": None
}
```

Supported patterns:
- "X minutes", "X hours", "X-Y minutes"
- "1 hour 30 minutes", "1.5 hours"
- Accumulates multiple times in one step

### Temperature Extraction

```python
parse_instruction("Preheat oven to 375°F.")
# Returns:
{
    "total_time_seconds": None,
    "temperature": 375.0,
    "temperature_unit": "F"
}
```

Supported patterns:
- "350°F", "180°C", "350 degrees F"
- Unit conversion available (F↔C)

### Cook Time Aggregation

Total recipe cook time = sum of all step times (when not explicitly provided in source).

---

## Text Normalization

**Location:** `cookimport/parsing/cleaning.py`

### Unicode Normalization
- NFKC normalization (compatibility decomposition + canonical composition)
- Non-breaking spaces → regular spaces

### Mojibake Repair
Common encoding corruption fixes:
- `â€™` → `'` (smart quote)
- `â€"` → `—` (em dash)
- `Ã©` → `é` (accented characters)

### Whitespace Standardization
- Collapse multiple spaces to single space
- Collapse 3+ newlines to 2 newlines
- Strip leading/trailing whitespace

### Hyphenation Repair
Rejoins words split across lines:
- "ingre-\ndients" → "ingredients"
- Handles soft hyphens (U+00AD)

---

## Signal Detection

**Location:** `cookimport/parsing/signals.py`

Enriches `Block` objects with feature flags for downstream processing.

### Available Signals

| Signal | Description |
|--------|-------------|
| `is_heading` | Detected as heading element |
| `heading_level` | 1-6 for h1-h6 |
| `is_ingredient_header` | "Ingredients:", "For the Sauce:" |
| `is_instruction_header` | "Instructions:", "Method:", "Directions:" |
| `is_yield` | "Serves 4", "Makes 12 cookies" |
| `is_time` | "Prep: 15 min", "Cook: 30 min" |
| `starts_with_quantity` | Line starts with number/fraction |
| `has_unit` | Contains unit term (cup, tbsp, oz) |
| `is_ingredient_likely` | High probability ingredient line |
| `is_instruction_likely` | High probability instruction step |

### Override Support

Cookbook-specific overrides via `ParsingOverrides`:
- Custom ingredient headers
- Custom instruction headers
- Additional imperative verbs
- Custom unit terms
