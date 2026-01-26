---
summary: "Standalone EPUB tip extraction scans every non-recipe block, so weak advice words can surface narrative prose."
read_when:
  - When tuning tip/knowledge extraction or investigating narrative tips
---

# Narrative tips leak through standalone blocks

- EPUB imports pass every non-recipe block through `extract_tip_candidates`, so any weak advice cue (for example “aim to” or “better”) can elevate story-like sentences into the general tip output.
- Filtering needs an explicit advice anchor (imperative start, strong tip header/prefix, diagnostic/benefit cue) to keep narrative prose out of the tips folder.
