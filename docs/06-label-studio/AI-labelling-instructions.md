---
summary: "How to edit the runtime freeform prelabel prompt template quickly."
read_when:
  - "When iterating on AI prompt text for Label Studio prelabel"
  - "When updating placeholders used by cookimport/labelstudio/prelabel.py"
---

# AI labeling prompt templates

Runtime reads prompt text directly from this file:

- `llm_pipelines/prompts/freeform-prelabel-full.prompt.md`
- `llm_pipelines/prompts/freeform-prelabel-span.prompt.md` (actual freeform span mode)

Edit the `.prompt.md` file to iterate quickly. No Python edits are required for text-only changes.

## Placeholder tokens

Keep these tokens in templates so runtime can inject task data:

- `{{ALLOWED_LABELS}}`
- `{{UNCERTAINTY_HINT}}` (full/block template only)
- `{{SEGMENT_ID}}`
- `{{BLOCKS_JSON_LINES}}`
- `{{FOCUS_CONSTRAINTS}}`
- `{{FOCUS_BLOCK_JSON_LINES}}` (legacy focus listing, still available)
- `{{BLOCKS_WITH_FOCUS_MARKERS_JSON_LINES}}` (span template single-pass block stream with `START/STOP` focus markers)

For span mode, prefer `{{BLOCKS_WITH_FOCUS_MARKERS_JSON_LINES}}` to avoid duplicating block text payloads.

If a prompt template file is missing or empty, runtime falls back to a built-in default string in `cookimport/labelstudio/prelabel.py`.
