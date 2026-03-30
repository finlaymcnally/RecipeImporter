---
summary: "Reference artifacts and snapshots for draft-v1 schemas, model mirrors, and field inventories."
read_when:
  - When validating output contracts or aligning with external data models
  - When you need the reference schema/type files in this folder
  - When auditing draft-v1 contract coverage between docs and runtime code
---

# Reference Section

This folder holds static contract references and inventory snapshots used to reason about pipeline outputs.
For versions/build/fix-attempt history and anti-loop notes, read `docs/11-reference/11-reference_log.md`.

## Artifact Inventory

1. `docs/11-reference/2026-02-10_recipe-database-field-inventory.md`
- Dated snapshot of recipe-related DB fields and constraints from the public schema as of `2026-02-10`.
- This file is a reference snapshot only; runtime code does not import it directly.

2. `docs/11-reference/2026-03-30_13.47.43_cookbook-tag-catalog-snapshot.md`
- Dated snapshot of the Cookbook app's seeded tag catalog copied from `~/projects/cookbook/supabase/seeds/catalog.sql`.
- Useful when designing `KNOWLEDGE` vs `OTHER` heuristics around whether text can ground to a stored tag or tag-category concept.

3. `docs/11-reference/recipeDraftV1.schema.json`
- JSON Schema mirror for the cookbook3 draft-v1 payload contract.
- Useful for external validators and cross-repo contract checks, but it currently tracks the strict core subset rather than every runtime-emitted field.

4. `docs/11-reference/recipeDraftV1.ts`
- Zod mirror of the draft-v1 contract (`RecipeDraftV1Schema`) plus helpers (`parseRecipeDraftV1`, `formatZodError`).
- Useful when TypeScript tooling needs strict draft-v1 validation behavior, but it currently lags some runtime-only draft fields.

## Runtime Code Map (Draft-v1 Contract)

1. `cookimport/staging/draft_v1.py`
- Primary deterministic converter from `RecipeCandidate` to draft-v1 payload.
- Enforces staging-specific shaping rules (quantity normalization, fallback IDs, variant extraction, source normalization, prep-step insertion for unassigned ingredients).

2. `cookimport/staging/writer.py`
- `write_draft_outputs(...)` writes final draft JSON payloads under `r{index}.json`.
- Primarily projects from `authoritative_payloads_by_recipe_id`; the explicit `draft_overrides_by_recipe_id` / `schemaorg_overrides_by_recipe_id` parameters remain only as narrow helper/test seams.
- `write_intermediate_outputs(...)` writes schema.org intermediates and shares the same canonical-payload-first behavior.

3. `cookimport/core/models.py`
- Defines internal `RecipeDraftV1`, `RecipeDraftRecipeMeta`, and `RecipeDraftStep` models used by runtime validation and type boundaries.

4. `cookimport/llm/codex_farm_contracts.py`
- Defines the live merged-repair LLM contract envelopes (`MergedRecipeRepairInput` / `MergedRecipeRepairOutput`) used by the recipe correction stage.

5. `cookimport/llm/codex_farm_orchestrator.py`
- Thin public facade for the recipe correction stage.
- Live normalization, validation, and `AuthoritativeRecipeSemantics` promotion now live behind this facade in `cookimport/llm/recipe_stage/` and `cookimport/llm/recipe_stage_shared.py`.

6. `cookimport/staging/jsonld.py`
- Deterministic converter for schema.org intermediate recipe payloads used by `write_intermediate_outputs(...)`.

## Tests Covering This Contract Surface

1. `tests/staging/test_draft_v1_staging_alignment.py`
- Staging alignment/sanitization guardrails for draft payload shape and fields.

2. `tests/staging/test_draft_v1_lowercase.py`
- Lowercasing normalization for ingredient text fields.

3. `tests/staging/test_draft_v1_variants.py`
- Variant extraction behavior and fallback-step behavior.

4. `tests/parsing/test_source_field.py`
- Source-population behavior in draft writer outputs.

5. `tests/parsing/test_tip_recipe_notes.py`
- Recipe-note extraction path into draft payload.

6. `tests/llm/test_writer_overrides.py`
- Confirms writer accepts current schema.org/draft override seams and authoritative recipe payload projection.

7. `tests/llm/test_codex_farm_contracts.py`
- Validates required fields for the live merged-repair contract envelope.

8. `tests/llm/test_codex_farm_orchestrator.py`
- Exercises the deterministic-build plus single recipe-correction orchestration path.

9. `tests/staging/test_draft_v1_priority6.py`
- Covers active priority-6 draft metadata behavior: `recipe.max_oven_temp_f`, per-step `temperature_items`, and writer-sidecar extraction for `_p6_debug`.

## Guardrails

1. `docs/11-reference/recipeDraftV1.schema.json` and `docs/11-reference/recipeDraftV1.ts` are reference mirrors; Python runtime does not import these files directly.
2. These mirrors now cover the active final draft fields emitted by staging, including `recipe.max_oven_temp_f` and step `temperature_items`. The remaining documented non-final gap is optional `_p6_debug` before writer-sidecar extraction.
3. Python runtime model (`RecipeDraftV1`) currently allows extra fields (`extra="allow"`), while mirror schema/TS validators are strict (`additionalProperties: false` / `.strict()`).
4. When changing draft output fields, update this folder and stage/LLM docs together (`docs/05-staging`, `docs/10-llm`) so contract docs remain in sync.
