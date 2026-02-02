---
summary: "Semantic fallback matching for ingredient-to-step assignment."
read_when:
  - When improving ingredient normalization or semantic matching in step linking
---

# Semantic Matching for Ingredient-to-Step Assignment

## Current behavior (implemented)

- Exact alias matching runs first (raw + cleaned aliases).
- If an ingredient has **no exact matches**, a lightweight **lemmatized** fallback runs.
- "Exact match" here includes head/tail single-token aliases, so semantic/fuzzy only run when **no alias tokens** hit a step.
- Lemmatization is **rule-based** (suffix stripping + a small override map) and adds **no external deps**.
- A **curated synonym map** expands semantic aliases (e.g., scallion ↔ green onion).
- If an ingredient is still unmatched, a **RapidFuzz** fallback runs for near-miss typos.
- Candidates are tagged as `match_kind="semantic"` or `match_kind="fuzzy"` and only considered when exact matches are absent for that ingredient.

## Why it helps

This rescues common morphology gaps without heavy models, e.g.:

- "floured" → "flour"
- "onions" → "onion"
- "chopped" → "chop"
- "scallions" → "green onion"
- "squah" (typo) → "squash" (via fuzzy rescue)

## Where it lives

- `cookimport/parsing/step_ingredients.py`
  - `_lemmatize_token` / `_lemmatize_tokens`
  - `_expand_synonym_variants` / `_add_alias_variants`
  - `_tokenize(..., lemmatize=True)`
  - semantic fallback in `assign_ingredient_lines_to_steps`
  - fuzzy fallback in `assign_ingredient_lines_to_steps`

## Guardrails and tuning knobs

- `_SYNONYM_GROUPS`: curated synonym phrase groups (lemmatized tokens).
- `_FUZZY_MIN_SCORE`: minimum RapidFuzz score for fuzzy candidates (default 85).
- `_GENERIC_FUZZY_TOKENS`: excludes very generic single-word ingredients from fuzzy rescue.

## Future options (not implemented)

- Real lemmatizers (spaCy, NLTK, LemmInflect)
- Embedding fallback for *unassigned* ingredients only, ideally on constrained spans
