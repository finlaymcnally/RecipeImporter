---
summary: "Notes on where non-instruction text lives in current importers (useful for tip extraction)."
read_when:
  - When adding tip/knowledge extraction to PDF/EPUB/Text importers
---

# Tip Extraction Context (Importer Notes)

- PDF and EPUB importers build a linear list of `Block` objects with signal features, then segment that list into recipe candidate ranges. Anything outside those ranges is currently ignored.
- Within a recipe range, `_extract_fields` splits content into `description`, `ingredients`, and `instructions`; the `description` list collects non-ingredient/non-instruction lines (headnotes, notes, etc.).
- The text importer builds `description_lines` from lines that are not classified as ingredient or instruction lines (or that appear before the ingredient run) and stores them in `RecipeCandidate.description`.
- Excel/docx-table parsing merges any `Notes/Tips` sections into the `description` field rather than emitting a dedicated structure.

These are the most obvious hooks for tip extraction: scan `description` for tip-like sentences, and scan block ranges outside recipes for standalone tips.
