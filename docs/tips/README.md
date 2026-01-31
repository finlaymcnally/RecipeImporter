---
summary: "Tip extraction, classification, taxonomy tagging, and evaluation."
read_when:
  - Working on tip/knowledge extraction
  - Tuning tip precision or recall
  - Building golden sets for tip evaluation
---

# Tip Extraction Pipeline

**Location:** `cookimport/parsing/tips.py`

The tip extraction system identifies standalone kitchen wisdom from cookbook content.

## Tip Classification

Tips are classified by scope:

| Scope | Description | Example |
|-------|-------------|---------|
| `general` | Reusable kitchen wisdom | "Toast spices in a dry pan to release oils." |
| `recipe_specific` | Notes tied to one recipe | "This soup freezes well for up to 3 months." |
| `not_tip` | False positive | Copyright notices, ads, narrative prose |

---

## Extraction Strategy

### From Recipes

Tips extracted from recipe content:
1. Scan description, notes, and instruction comments
2. Look for tip markers (see Advice Anchors below)
3. Classify scope based on generality signals

### From Standalone Blocks

Content not assigned to recipes:
1. Chunk into containers (by section headers)
2. Split containers into atoms (individual sentences/points)
3. Apply tip detection heuristics
4. Generate topic candidates for non-tip content

---

## Detection Heuristics

### Advice Anchors (Required)

Tips must contain explicit advice language:

**Modal verbs:** can, should, must, need to, ought to, have to
**Imperatives:** use, try, avoid, choose, store, keep, serve, add, make sure
**Conditionals:** if you, when you, for best results

### Cooking Anchors (Gate)

At least one cooking-related term must be present:
- Techniques: sauté, roast, simmer, marinate
- Equipment: pan, oven, pot, knife
- Ingredients: butter, salt, garlic, onion
- Outcomes: crispy, tender, golden, caramelized

### Narrative Rejection

Reject tip-like content that's actually narrative:
- Story-telling patterns ("I remember when...", "My grandmother used to...")
- Long flowing paragraphs without actionable advice
- Historical or biographical content

---

## Taxonomy Tagging

Tips are tagged with relevant anchors (`TipTags` model):

| Category | Examples |
|----------|----------|
| `recipes` | Recipe names mentioned |
| `dishes` | pasta, soup, salad, stew |
| `meats` | chicken, beef, pork, fish |
| `vegetables` | onion, garlic, tomato, carrot |
| `herbs` | basil, thyme, rosemary, cilantro |
| `spices` | cumin, paprika, cinnamon, pepper |
| `dairy` | butter, cream, cheese, milk |
| `grains` | rice, bread, flour, pasta |
| `techniques` | sauté, roast, braise, poach |
| `cooking_methods` | baking, grilling, frying, steaming |
| `tools` | pan, oven, knife, blender |

---

## Atom Chunking

**Location:** `cookimport/parsing/atoms.py`

Large blocks are split into atomic units for better precision:

```
Container: "COOKING TIPS" section
  └─ Atom 1: "Toast whole spices before grinding."
  └─ Atom 2: "Store herbs wrapped in damp paper towels."
  └─ Atom 3: "Let meat rest before slicing."
```

Each atom includes context:
- `context_prev`: Previous atom text (for context)
- `context_next`: Next atom text (for context)
- `container_header`: Section header if present

---

## Topic Candidates

Content that doesn't qualify as tips but may be valuable:
- Ingredient guides ("All About Olive Oil")
- Technique explanations ("How to Julienne Vegetables")
- Equipment recommendations ("Choosing the Right Pan")

Topic candidates are stored separately for potential future use.

---

## Tuning Guide

### Precision vs Recall

**To increase precision** (fewer false positives):
- Tighten advice anchor requirements
- Add more narrative rejection patterns
- Require more cooking anchors

**To increase recall** (catch more tips):
- Add advice anchor words
- Relax cooking anchor requirements
- Reduce minimum generality score

### Key Knobs

Located in `cookimport/parsing/tips.py`:

1. **Advice anchor patterns** - Regex patterns for tip-like language
2. **Cooking anchor terms** - Required domain vocabulary
3. **Narrative rejection patterns** - Story-telling indicators
4. **Generality threshold** - Score cutoff for general vs recipe-specific

### Override Support

Per-cookbook overrides via `ParsingOverrides`:
- `tip_headers`: Additional section headers to treat as tip containers
- `tip_prefixes`: Line prefixes that indicate tips ("TIP:", "NOTE:")

---

## Evaluation Harness

**Location:** `docs/tips/` (this doc) + Label Studio integration

### Building Golden Sets

1. Run tip extraction on test cookbook
2. Export tip candidates to Label Studio
3. Annotate: correct scope, correct/incorrect extraction
4. Export labeled data as golden set JSONL

### Scoring

```bash
# Run evaluation against golden set
python -m cookimport.evaluation.tips --golden golden_tips.jsonl --predicted predicted_tips.jsonl
```

Metrics:
- **Precision**: % of extracted tips that are correct
- **Recall**: % of actual tips that were extracted
- **Scope accuracy**: % of tips with correct scope classification

### A/B Testing Workflow

1. Establish baseline metrics on golden set
2. Modify heuristics
3. Re-run extraction
4. Compare metrics
5. Keep changes only if metrics improve
