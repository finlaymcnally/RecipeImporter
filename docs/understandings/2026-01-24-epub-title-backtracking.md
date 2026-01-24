---
summary: "Yield-anchored EPUB segmentation can leave duplicate title lines in the previous recipe when titles are split into multiple blocks."
read_when:
  - When debugging EPUB recipes that include trailing title lines in instructions
---

# EPUB title backtracking

- ATK EPUBs sometimes emit two consecutive title-like blocks before a yield line (for example, a title-case heading plus a bold lowercase repeat).
- The previous recipe can absorb the earlier title block if backtracking stops at the closest title-like line.
- Backtracking should walk to the earliest consecutive title-like block before the yield anchor to keep titles with their own recipe.
