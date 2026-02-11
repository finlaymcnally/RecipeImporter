---
summary: "Freeform label taxonomy and eval normalization rules."
read_when:
  - Updating freeform span labels or evaluator mappings
---

# Freeform Label Taxonomy (Discovery)

- Freeform Label Studio config now uses `TIP`, `NOTES`, and `VARIANT` (plus structural recipe labels and `OTHER`; no `NARRATIVE` label in freeform mode).
- `TIP` is broad reusable guidance; `NOTES` is recipe-specific and intended for recipe JSON notes; `VARIANT` marks recipe/step alternatives.
- Freeform evaluator normalizes legacy aliases so older exports remain comparable: `KNOWLEDGE` -> `TIP`, `NOTE` -> `NOTES`, `NARRATIVE` -> `OTHER`.
- Pipeline chunk mapping in freeform eval maps `chunk_type=note` to `NOTES`.
