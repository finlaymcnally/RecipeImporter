# llm_pipelines

Local codex-farm pipeline-pack assets for `cookimport`.

`cookimport` defaults `codex_farm_root` to this folder when the LLM recipe pipeline is enabled.
This root must contain:

- `pipelines/`
- `prompts/`
- `schemas/`

## Codex-farm recipe 3-pass defaults

Editable pipeline specs:

- `pipelines/recipe.chunking.v1.json`
- `pipelines/recipe.schemaorg.v1.json`
- `pipelines/recipe.final.v1.json`
- `pipelines/recipe.knowledge.v1.json` (optional pass4 knowledge harvest)
- `pipelines/recipe.tags.v1.json` (optional pass5 tag suggestions)

Editable prompt text:

- `prompts/recipe.chunking.v1.prompt.md`
- `prompts/recipe.schemaorg.v1.prompt.md`
- `prompts/recipe.final.v1.prompt.md`
- `prompts/recipe.knowledge.v1.prompt.md`
- `prompts/recipe.tags.v1.prompt.md`

Output schemas:

- `schemas/recipe.chunking.v1.output.schema.json`
- `schemas/recipe.schemaorg.v1.output.schema.json`
- `schemas/recipe.final.v1.output.schema.json`
- `schemas/recipe.knowledge.v1.output.schema.json`
- `schemas/recipe.tags.v1.output.schema.json`

To tune pass behavior, edit prompt text files in `prompts/`.

Prompt input contract:
- `prompt_input_mode` is set to `"inline"` for recipe pipelines.
- Use `{{INPUT_TEXT}}` to inject the full JSON payload directly into the prompt.
- Do not rely on path-read instructions for recipe pipeline prompts.

Prompt convention note:
- `recipe.*.prompt.md` templates now explicitly enforce deterministic JSON behavior (no extra keys, strict field grounding, stable ordering, and "omit rather than guess" for uncertain fields).

## Label Studio freeform AI templates

Freeform prelabel (full mode) is file-backed and editable:

- `prompts/freeform-prelabel-full.prompt.md`
- `prompts/freeform-prelabel-span.prompt.md` (actual freeform span mode)

Span mode prompt should keep quote/offset JSON output shape while mirroring full-mode label heuristics and tie-break logic.
Span mode now uses one markerized block stream (`START/STOP` focus markers) so focus text is not duplicated in the same prompt payload.

For external packs, pass `--codex-farm-root <path>`.
