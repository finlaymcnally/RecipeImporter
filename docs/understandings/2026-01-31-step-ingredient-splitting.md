---
summary: "Notes on step-ingredient assignment, split gating, and confidence penalties."
read_when:
  - When adjusting step-ingredient matching or split behavior
---

Step-ingredient linking (`cookimport/parsing/step_ingredients.py`) uses a two-phase match: candidate collection per step via alias matching, then a global resolution that assigns each ingredient to a single best step unless a strong split signal (fraction/remaining/reserved) appears in multiple steps. Multi-step assignments now apply a small confidence penalty on the split ingredient lines to flag them for review.
