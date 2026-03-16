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
- `{{FOCUS_BLOCK_INDICES}}`
- `{{FOCUS_MARKER_RULES}}`
- `{{FOCUS_BLOCK_JSON_LINES}}` (legacy focus listing, still available)
- `{{BLOCKS_WITH_FOCUS_MARKERS_COMPACT_LINES}}` (span template single-pass block stream with context-before/context-after markers plus `START/STOP` focus markers, each block line as `<block_index><TAB><block_text>`)

For span mode, prefer `{{BLOCKS_WITH_FOCUS_MARKERS_COMPACT_LINES}}` to avoid duplicating block text payloads and reduce wrapper overhead.

Keep span-template quality guardrails in place:
- anti-whole-block rules for long blocks,
- explicit "context is for interpretation, not auto-labeling adjacent blocks" wording,
- mixed-block split examples (e.g., yield+time, notes+instruction, header+ingredient).

If a prompt template file is missing or empty, runtime falls back to a built-in default string in `cookimport/labelstudio/prelabel.py`.
