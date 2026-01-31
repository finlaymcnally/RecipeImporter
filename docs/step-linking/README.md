---
summary: "Two-phase algorithm for linking ingredients to instruction steps."
read_when:
  - Working on step-ingredient assignment
  - Debugging ingredient duplication issues
  - Understanding split ingredient handling
---

# Step-Ingredient Linking

**Location:** `cookimport/parsing/step_ingredients.py`

This module assigns each ingredient to the instruction step(s) where it's used.

## Algorithm Overview

The **two-phase algorithm** solves the ingredient-step linking problem:

### Phase 1: Candidate Collection

For each (ingredient, step) pair:
1. Generate **aliases** for the ingredient (full text, cleaned text, head/tail tokens)
2. Scan step text for alias matches
3. Classify **verb context** around the match
4. Score the candidate based on match quality

### Phase 2: Global Resolution

For each ingredient:
1. Collect all step candidates
2. Apply assignment rules (usually: best step wins)
3. Handle exceptions (split ingredients, section groups)

---

## Alias Generation

Each ingredient generates multiple searchable aliases:

```python
"fresh sage leaves, chopped" →
  - ("fresh", "sage", "leaves", "chopped")  # full text
  - ("sage", "leaves")                       # cleaned (no prep)
  - ("sage",)                                # head token
  - ("leaves",)                              # tail token
```

Aliases are scored by:
1. Token count (more tokens = stronger match)
2. Character length
3. Source preference (raw_ingredient_text > raw_text)

---

## Verb Context Classification

The 1-3 tokens before an ingredient match reveal usage intent:

| Verb Type | Words | Score Adjustment |
|-----------|-------|------------------|
| **use** | add, mix, stir, fold, pour, whisk, combine, toss, season, drizzle, melt | +10 |
| **reference** | cook, let, rest, simmer, reduce, return | -5 |
| **split** | half, remaining, reserved, divided | +8 (enables multi-step) |
| **neutral** | (other) | 0 |

### Split Detection

Split signals trigger multi-step assignment:

```
Step 3: "Add half the butter and stir."
Step 7: "Add remaining butter and serve."
```

Both steps get the butter ingredient, with quantity fractions:
- Step 3: `input_qty * 0.5`
- Step 7: `input_qty * 0.5`

---

## Assignment Rules

### Default: Best Step Wins

Each ingredient goes to exactly one step (highest-scoring candidate).

**Tiebreaker:** When multiple steps have "use" verbs, prefer the **earliest step** (first introduction of ingredient).

### Exception: Multi-Step Assignment

Enabled only when:
1. Multiple candidates have "use" or "split" signals
2. At least one candidate has explicit split language

Maximum 3 steps per ingredient (prevents runaway assignments).

### Exception: Section Header Groups

Ingredients under a section header (e.g., "For the Sauce") are grouped:

```
For the Sauce:
  2 tbsp butter
  1 cup cream

Step: "Make the sauce by combining sauce ingredients..."
```

The phrase "sauce ingredients" matches the section, assigning all grouped ingredients.

### Exception: "All Ingredients" Phrases

Patterns like "combine all ingredients" assign every non-header ingredient to that step.

---

## Weak Match Filtering

Single-token matches (e.g., "oil") are **weak** and can cause false positives.

Filtering rule: If a weak match's token appears in a strong match in the same step, exclude the weak match.

Example:
- "olive oil" (strong match, 2 tokens)
- "oil" (weak match, 1 token)

If both match step 3, only "olive oil" is assigned (weak "oil" excluded).

---

## Debugging

Enable debug mode to trace assignments:

```python
results, debug_info = assign_ingredient_lines_to_steps(
    steps, ingredients, debug=True
)

# debug_info contains:
#   .candidates - all detected matches with scores
#   .assignments - final assignment decisions with reasons
#   .group_assignments - section header group matches
#   .all_ingredients_steps - steps with "all ingredients" phrase
```

---

## Key Discoveries

### Duplication Bug Fix (2026-01-30)

**Problem:** Ingredients appearing in multiple steps when only one assignment was intended.

**Root cause:** Greedy per-step matching without global resolution.

**Solution:** Two-phase algorithm with "earliest use verb wins" tiebreaker.

### Fraction Calculation

For split ingredients:
- "half" → 0.5
- "quarter" → 0.25
- "third" → 0.333
- "remaining" → complement of previously assigned fractions
