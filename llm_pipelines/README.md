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
- `pipelines/recipe.knowledge.compact.v1.json` (legacy compact knowledge contract)
- `pipelines/recipe.knowledge.packet.v1.json` (live packet-based knowledge contract)
- `pipelines/line-role.canonical.v1.json` (canonical line-role surface)
- `pipelines/prelabel.freeform.v1.json` (Label Studio freeform prelabel surface)

Editable prompt text:

- `prompts/recipe.correction.compact.v1.prompt.md`
- `prompts/recipe.knowledge.compact.v1.prompt.md`
- `prompts/recipe.knowledge.packet.v1.prompt.md`
- `prompts/benchmark.oracle-upload.prompt.md` (post-benchmark Oracle review prompt for `cookimport bench oracle-upload` and benchmark auto-upload; keep `{{HELPER_BANNER}}`, `{{BUNDLE_SCOPE}}`, and `{{BENCHMARK_ROOT}}` intact)
- `prompts/benchmark.oracle-followup.prompt.md` (turn-2 Oracle follow-up prompt for `cookimport bench oracle-followup`)

Output schemas:

- `schemas/recipe.correction.v1.output.schema.json`
- `schemas/recipe.knowledge.v1.output.schema.json`
- `schemas/recipe.knowledge.packet.v1.output.schema.json`
- `schemas/line-role.canonical.v1.output.schema.json`
- `schemas/prelabel.freeform.v1.output.schema.json`

Structured-output schema rule:
- At every object level, every key listed in `properties` must also appear in `required`; model optionality with nullable types instead of omitting keys.

To tune pass behavior, edit prompt text files in `prompts/`. The recipe path now uses one compact correction asset, `recipe.correction.compact.v1`, plus the optional knowledge pack.

Recipe correction schemas use native nested JSON objects for recipe payload fields (`canonical_recipe`) instead of JSON-string wrapper fields. `ingredient_step_mapping` is now a strict array of mapping-entry objects on the wire because Codex structured outputs rejected the old arbitrary-key object form; recipeimport still normalizes that back to an internal dictionary after validation.

Prompt input contract:
- Recipe still uses `prompt_input_mode: "path"` through CodexFarm `process`.
- The knowledge and line-role live runtimes no longer use prompt-pack path handoff. They keep using the schemas in this folder, but they send inline prompt bodies directly to `codex exec` from repo-owned runtime code instead of asking Codex to read `{{INPUT_PATH}}`.

Prompt convention note:
- `recipe.*.prompt.md` templates now explicitly enforce deterministic JSON behavior (no extra keys, strict field grounding, stable ordering, and "omit rather than guess" for uncertain fields).
- `recipe.knowledge.packet.v1.prompt.md` is the live knowledge prompt. It asks for packet-level `block_decisions` plus model-authored related `idea_groups` instead of one deterministic chunk result row.
- Recipe codex-farm packs (`recipe.correction.compact.v1`, `recipe.knowledge.packet.v1`) default to `codex_timeout_seconds: 600`.

## Label Studio freeform AI templates

Freeform prelabel is span-only now and remains file-backed/editable through:

- `prompts/freeform-prelabel-span.prompt.md`

The span prompt should keep quote/offset JSON output shape while preserving the active label heuristics and tie-break logic.
Span mode now uses one markerized block stream (`START/STOP` focus markers) so focus text is not duplicated in the same prompt payload.

Prelabel runtime now executes through CodexFarm pipeline `prelabel.freeform.v1` with prompt wrapper `prompts/prelabel.freeform.v1.prompt.md`.

Canonical line-role runtime no longer uses the live CodexFarm prompt wrapper. The schema file remains authoritative for structured output, and the pipeline asset stays in this folder for pack compatibility, preview/tooling references, and tests that still inventory the pack.

For external packs, pass `--codex-farm-root <path>`.
