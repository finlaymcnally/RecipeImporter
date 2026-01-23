---
summary: "ATK EPUBs use 'serves' lines as reliable recipe anchors and omit instruction headers."
read_when:
  - When debugging EPUB imports from America's Test Kitchen books
---

# ATK EPUB structure notes

- Many recipes use a short title line followed by a `serves` line and ingredient list without explicit "Instructions" headers.
- Yield lines are frequent and are a reliable anchor for splitting recipes.
- Ingredient subheaders like "filling" appear in place of a global "Ingredients" header.
