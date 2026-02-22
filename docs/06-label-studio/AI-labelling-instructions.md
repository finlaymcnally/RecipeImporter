---
summary: "How to edit the runtime freeform prelabel/decorate prompt templates quickly."
read_when:
  - "When iterating on AI prompt text for Label Studio prelabel/decorate"
  - "When updating placeholders used by cookimport/labelstudio/prelabel.py"
---

# AI labeling prompt templates

Runtime reads prompt text directly from these files:

- `llm_pipelines/prompts/freeform-prelabel-full.prompt.md`
- `llm_pipelines/prompts/freeform-prelabel-augment.prompt.md`

Edit those `.prompt.md` files to iterate quickly. No Python edits are required for text-only changes.

## Placeholder tokens

Keep these tokens in templates so runtime can inject task data:

- `{{ALLOWED_LABELS}}`
- `{{UNCERTAINTY_HINT}}` (full template)
- `{{ADD_LABELS}}` (augment template)
- `{{SEGMENT_ID}}`
- `{{EXISTING_LABELS_PER_BLOCK}}` (augment template)
- `{{BLOCKS_JSON_LINES}}`

If a prompt template file is missing or empty, runtime falls back to a built-in default string in `cookimport/labelstudio/prelabel.py`.
