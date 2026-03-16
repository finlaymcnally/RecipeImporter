# llm_pipelines

Local codex-farm pipeline-pack assets for `cookimport`.

`cookimport` defaults `codex_farm_root` to this folder when the LLM recipe pipeline is enabled.
This root must contain:

- `pipelines/`
- `prompts/`
- `schemas/`

## Codex-farm recipe defaults

Editable pipeline specs:

- `pipelines/recipe.correction.compact.v1.json`
- `pipelines/recipe.knowledge.compact.v1.json` (optional pass4 knowledge harvest)
- `pipelines/recipe.tags.v1.json` (optional pass5 tag suggestions)
- `pipelines/line-role.canonical.v1.json` (canonical line-role surface)
- `pipelines/prelabel.freeform.v1.json` (Label Studio freeform prelabel surface)

Editable prompt text:

- `prompts/recipe.correction.compact.v1.prompt.md`
- `prompts/recipe.knowledge.compact.v1.prompt.md`
- `prompts/recipe.tags.v1.prompt.md`

Output schemas:

- `schemas/recipe.correction.v1.output.schema.json`
- `schemas/recipe.knowledge.v1.output.schema.json`
- `schemas/recipe.tags.v1.output.schema.json`
- `schemas/line-role.canonical.v1.output.schema.json`
- `schemas/prelabel.freeform.v1.output.schema.json`

To tune pass behavior, edit prompt text files in `prompts/`. The recipe path now uses one compact correction asset, `recipe.correction.compact.v1`, plus the optional knowledge and tag packs.

Recipe correction schemas use native nested JSON objects for recipe payload fields (`canonical_recipe`) instead of JSON-string wrapper fields. `ingredient_step_mapping` is now a strict array of mapping-entry objects on the wire because Codex structured outputs rejected the old arbitrary-key object form; recipeimport still normalizes that back to an internal dictionary after validation.

Prompt input contract:
- `prompt_input_mode` is set to `"inline"` for recipe pipelines.
- Use `{{INPUT_TEXT}}` to inject the full JSON payload directly into the prompt.
- Do not rely on path-read instructions for recipe pipeline prompts.

Prompt convention note:
- `recipe.*.prompt.md` templates now explicitly enforce deterministic JSON behavior (no extra keys, strict field grounding, stable ordering, and "omit rather than guess" for uncertain fields).
- Recipe codex-farm packs (`recipe.correction.compact.v1`, `recipe.knowledge.compact.v1`, `recipe.tags.v1`) default to `codex_timeout_seconds: 600`.

## Label Studio freeform AI templates

Freeform prelabel (full mode) is file-backed and editable:

- `prompts/freeform-prelabel-full.prompt.md`
- `prompts/freeform-prelabel-span.prompt.md` (actual freeform span mode)

Span mode prompt should keep quote/offset JSON output shape while mirroring full-mode label heuristics and tie-break logic.
Span mode now uses one markerized block stream (`START/STOP` focus markers) so focus text is not duplicated in the same prompt payload.

Prelabel runtime now executes through CodexFarm pipeline `prelabel.freeform.v1` with prompt wrapper `prompts/prelabel.freeform.v1.prompt.md`.

Canonical line-role runtime now executes through CodexFarm pipeline `line-role.canonical.v1` with prompt wrapper `prompts/line-role.canonical.v1.prompt.md`.

For external packs, pass `--codex-farm-root <path>`.
