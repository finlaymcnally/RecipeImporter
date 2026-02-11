---
summary: "How freeform eval now reports boundary-insensitive classification alignment."
read_when:
  - Prioritizing label agreement over span-boundary strictness in benchmark interpretation
  - Changing freeform evaluation summaries or markdown reporting
---

# Freeform Eval Classification-Only View

- Strict and app-aligned sections remain unchanged and still report boundary-sensitive outcomes.
- `report.classification_only` is added for label-focused interpretation:
  - dedupes predicted ranges by `(source_hash, source_file, label, start_block_index, end_block_index)`,
  - counts same-label any-overlap coverage across gold spans,
  - counts best-overlap label matches (regardless strict IoU threshold),
  - exposes `confusion_by_gold_label` with `__NO_OVERLAP__` buckets.
- This gives a more stable signal when span chopping/granularity differs but high-level class intent is similar.
