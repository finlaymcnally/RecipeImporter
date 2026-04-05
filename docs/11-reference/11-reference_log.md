---
summary: "Reference-section version/build/fix-attempt log to prevent repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on reference artifacts or program behavior
  - When the human says "we are going in circles on this"
  - When you need prior architecture versions, builds, or fix attempts before changing reference contracts
---

# Reference Log

Read this if you are going in multi-turn circles on the program, or if the human says "we are going in circles on this."
This file tracks reference-section architecture versions, builds, fix attempts, and prior dead ends so we do not repeat them.

## Chronology and Prior Attempts (do not discard)

1. `2026-02-19_11-reference-readme-log-split`
- split section docs into:
  - `11-reference_README.md` for current source-of-truth reference documentation.
  - `11-reference_log.md` for architecture/build/fix-attempt history and anti-loop guidance.

2. `2026-02-27_19.55.26_reference-docs-code-coverage-audit`
- audited `docs/11-reference` against active runtime code paths.
- gap found: README listed static artifacts but did not map ownership in `cookimport/staging`, `cookimport/core/models`, and `cookimport/llm`, which made docs incomplete for code-level review.
- action: expanded README with:
  - artifact inventory and purpose
  - runtime ownership map for draft-v1 contract producers/validators
  - tests that currently lock contract behavior
  - strict-vs-permissive guardrail note (`schema/json+ts` strict mirrors vs Python model `extra="allow"`)

3. `2026-03-15_22.41.34_reference-doc-drift-audit`
- cleaned out stale provenance references and tightened wording around what the mirror files cover.
- tightened README wording so `recipeDraftV1.schema.json` and `recipeDraftV1.ts` are described as useful external mirrors, not a complete source of truth for every current runtime-emitted field.
- kept active draft-v1 behavior in scope:
  - priority-6 draft metadata such as `recipe.max_oven_temp_f`, step `temperature_items`, and `_p6_debug` sidecar extraction

4. `2026-03-30_11-reference-doc-prune`
- removed stale notes about writer-added top-level alias fields; current writer strips legacy `name` / `ingredients` / `instructions` keys from override payloads instead of documenting them as active output behavior.
- removed an unrelated `tests/ingestion/test_excel_importer.py` reference from the README because it no longer covers draft-v1 output shape.
- corrected the runtime ownership note so `cookimport/llm/codex_farm_orchestrator.py` is described as the public facade, with the live recipe-stage implementation living behind it.

5. `2026-03-30_11-reference-mirror-alignment`
- aligned `recipeDraftV1.schema.json` and `recipeDraftV1.ts` with current runtime-emitted final draft fields by adding recipe-level `max_oven_temp_f` and step-level `temperature_items`.
- removed stale schema wording that described the JSON Schema mirror as a review-metadata/unresolved-text extension.
- clarified that `2026-02-10_recipe-database-field-inventory.md` is a dated snapshot, not a repo-verifiable claim about the current live schema.

## Known Gaps and Guardrails

1. No section-specific fix-attempt ledger existed before this file.
- Use this log going forward to capture failed schema/model contract changes so future turns avoid repeating them.

2. Draft-v1 strictness differs by enforcement layer.
- Reference mirror validators (`recipeDraftV1.schema.json`, `recipeDraftV1.ts`) are strict by design.
- Runtime Python model accepts extra fields (`extra="allow"`), so contract tightness depends on producer logic + tests unless stricter runtime validation is introduced later.
