---
summary: "Standalone EPUB tip extraction scans every non-recipe block, so weak advice words can surface narrative prose."
read_when:
  - When tuning tip/knowledge extraction or investigating narrative tips
---

# Narrative tips leak through standalone blocks

- EPUB imports pass every non-recipe block through `extract_tip_candidates`, so any weak advice cue (for example “aim to” or “better”) can elevate story-like sentences into the general tip output.
- Filtering needs an explicit advice anchor (imperative start, strong tip header/prefix, diagnostic/benefit cue) plus a cooking anchor (ingredient/technique/tool keyword) to keep narrative prose out of the tips folder.
- Standalone narrative lines containing “never/always” were being treated as advice; removing those tokens from the strong advice regex prevented non-cooking prose from passing the explicit advice gate.
- Standalone blocks are now merged into topic chunks (header + anchor overlap) before tip extraction so related short tips are grouped into longer paragraphs.
