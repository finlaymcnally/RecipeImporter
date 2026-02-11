---
summary: "Why freeform eval now reports app-aligned diagnostics in addition to strict metrics."
read_when:
  - Interpreting low freeform benchmark precision/recall against real cookbook app behavior
  - Modifying freeform evaluation reporting or benchmark score presentation
---

# Freeform Eval App-Aligned Summary

- Strict freeform metrics remain the source-of-truth span benchmark (`IoU >= threshold` with full label taxonomy).
- They can look punitive when predictions contain duplicate block ranges and when gold labels include classes not currently emitted by pipeline predictions (`TIP`, `NOTES`, `VARIANT`).
- `eval_freeform.py` now adds `report.app_aligned` so reports also show:
  - strict metrics after deduping identical predicted ranges,
  - strict/relaxed metrics for app-supported labels (`RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `OTHER`),
  - same-label any-overlap coverage for core recipe labels.
