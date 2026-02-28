---
summary: "Reference artifacts for schemas, model templates, and field inventories used by the pipeline."
read_when:
  - When validating output contracts or aligning with external data models
  - When you need canonical schema/type reference files
  - When auditing draft-v1 contract coverage between docs and runtime code
---

# Reference Section

This folder holds static contract references and inventory snapshots used to reason about pipeline outputs.
For versions/build/fix-attempt history and anti-loop notes, read `docs/11-reference/11-reference_log.md`.

## Artifact Inventory

1. `docs/11-reference/2026-02-10_recipe-database-field-inventory.md`
- Consolidated inventory of recipe-related DB fields and constraints from the live public schema.
- This file is a reference snapshot only; runtime code does not import it directly.

2. `docs/11-reference/recipeDraftV1.schema.json`
- JSON Schema mirror for the cookbook3 draft-v1 payload contract.
- Useful for external validators and cross-repo contract checks.

3. `docs/11-reference/recipeDraftV1.ts`
- Zod mirror of the draft-v1 contract (`RecipeDraftV1Schema`) plus helpers (`parseRecipeDraftV1`, `formatZodError`).
- Useful when TypeScript tooling needs strict draft-v1 validation behavior.

## Runtime Code Map (Draft-v1 Contract)

1. `cookimport/staging/draft_v1.py`
- Primary deterministic converter from `RecipeCandidate` to draft-v1 payload.
- Enforces staging-specific shaping rules (quantity normalization, fallback IDs, variant extraction, source normalization, prep-step insertion for unassigned ingredients).

2. `cookimport/staging/writer.py`
- `write_draft_outputs(...)` writes final draft JSON payloads under `r{index}.json`.
- Accepts `draft_overrides_by_recipe_id` so LLM pass outputs can replace deterministic conversion output.
- `write_intermediate_outputs(...)` writes schema.org intermediates and shares override plumbing for pass2 payloads.

3. `cookimport/core/models.py`
- Defines internal `RecipeDraftV1`, `RecipeDraftRecipeMeta`, and `RecipeDraftStep` models used by runtime validation and type boundaries.

4. `cookimport/llm/codex_farm_contracts.py`
- Defines pass3 LLM contract envelope (`Pass3FinalDraftOutput`) carrying `draft_v1`.

5. `cookimport/llm/codex_farm_orchestrator.py`
- Normalizes LLM pass3 draft payload, validates with `RecipeDraftV1.model_validate(...)`, and forwards validated overrides into writer output paths.

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

6. `tests/ingestion/test_excel_importer.py`
- Confirms generated draft outputs include `schema_v == 1` for importer outputs.

7. `tests/llm/test_writer_overrides.py`
- Confirms writer accepts and emits pass2/pass3 override payloads.

8. `tests/llm/test_codex_farm_contracts.py`
- Validates required fields for pass3 bundle contract envelope.

9. `tests/llm/test_codex_farm_orchestrator.py`
- Exercises pass1/pass2/pass3 orchestration, including draft-v1 payload acceptance in pass3 bundle flow.

## Guardrails

1. `docs/11-reference/recipeDraftV1.schema.json` and `docs/11-reference/recipeDraftV1.ts` are reference mirrors; Python runtime does not import these files directly.
2. Python runtime model (`RecipeDraftV1`) currently allows extra fields (`extra="allow"`), while mirror schema/TS validators are strict (`additionalProperties: false` / `.strict()`).
3. When changing draft output fields, update this folder and stage/LLM docs together (`docs/05-staging`, `docs/10-llm`) so contract docs remain in sync.

## 2026-02-27 merged understanding provenance

Merged source note:
- `docs/understandings/2026-02-27_19.55.26-reference-docs-code-coverage-audit.md`

Status:
- Runtime ownership map, validation-surface list, and strict-vs-permissive guardrail notes from that audit are now integrated in this README and `11-reference_log.md`.
