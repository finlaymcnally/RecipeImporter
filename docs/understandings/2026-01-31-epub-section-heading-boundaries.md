---
summary: "EPUB exports may split chapter headers into separate heading blocks that need to terminate recipe ranges."
read_when:
  - When debugging EPUB recipes that bleed into chapter or technique prose
---

In Salt, Fat, Acid, Heat EPUB exports, section headers like "VEGETABLES" (h2) and
subheads like "Cooking Onions" (h3) appear as their own heading blocks. Recipe
segmentation must treat those heading blocks as hard boundaries; otherwise the
following narrative technique text gets merged into the prior recipe.
