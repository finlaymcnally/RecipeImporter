# Ingredient Duplication Bug in Step-Ingredient Linking

**Date:** 2026-01-30
**Status:** Open
**File:** `cookimport/parsing/step_ingredients.py`

## The Bug

Ingredients are being assigned to **every step** that mentions them, rather than just the step where they're actually used/added.

### Example (r29.json - Grilled Artichokes)

The ingredient `6 medium artichokes (or 18 baby artichokes)` appears in **4 separate steps** because the word "artichokes" is mentioned in each step's directions:

- Step 2: "Remove the tough, dark outer leaves from the **artichokes**..."
- Step 3: "Cut the **artichokes** in half..."
- Step 4: "Place the **artichokes** in the water..."
- Step 5: "Drizzle the **artichokes** lightly with olive oil..."

The artichokes should only appear once - in step 2 where they're first prepared.

## Root Cause

`assign_ingredient_lines_to_steps()` (lines 96-154) processes each step **independently**:

```python
for step_text in step_texts:
    # ... finds matches in THIS step's text
    matches = _find_matches(step_tokens, alias_map)
    # ... adds matched ingredients to THIS step
    include_indices.update(match.index for match in strong_matches)
    include_indices.update(match.index for match in weak_matches)
```

There's no global tracking of which ingredients have already been assigned. Each step independently finds and adds any ingredient whose name appears in the text.

## Why This Happens

The matching logic uses `_build_aliases()` to create searchable tokens from ingredient names. For "artichokes", this creates a weak (single-word) match. Every step that contains the word "artichokes" will match it.

The `_WEAK_MATCH_CAP = 3` only limits weak matches **per step**, not globally.

## Design Intent vs. Reality

The exec plan (`docs/plans/PROCESS-ingredient-step-linking-execplan.md`) says:
> "Allow a single ingredient line to appear in multiple steps when the instruction text explicitly mentions it."

This was intended for cases like:
- "Add 1 cup flour now" (step 3)
- "Reserve remaining flour for dusting" (step 5)

But it's triggering on **any** mention, even just references like "cook the artichokes until tender."

## Potential Fixes

1. **First-match-wins**: Assign each ingredient only to the first step that mentions it
2. **Usage-based matching**: Only match when ingredient is being *added* (look for action verbs like "add", "combine", "pour")
3. **Explicit quantity splits**: Only duplicate when recipe explicitly splits quantity ("reserve 1/2 cup", "use remaining")
4. **Confidence-based**: Lower match confidence for subsequent matches of same ingredient

## Known Edge Cases to Preserve

- "Use 1 cup now, reserve 0.5 cup to garnish" - ingredient legitimately appears twice
- "Combine all ingredients" - all ingredients should appear
- Section headers like "For the sauce:" - group assignment should still work

## Reproduction

See: `data/output/2026-01-30-11-54-17/final drafts/saltfatacidheat/r29.json`
