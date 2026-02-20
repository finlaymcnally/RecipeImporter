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

1. `11-reference_README.md` (historical baseline before split)
- established the canonical reference artifacts list for schemas/models/field inventories:
  - `docs/11-reference/2026-02-10_recipe-database-field-inventory.md`
  - `docs/11-reference/recipeDraftV1.schema.json`
  - `docs/11-reference/recipeDraftV1.ts`

2. `2026-02-19_11-reference-readme-log-split` (this change)
- split section docs into:
  - `11-reference_README.md` for current source-of-truth reference documentation.
  - `11-reference_log.md` for architecture/build/fix-attempt history and anti-loop guidance.

## Known Gaps and Guardrails

1. No section-specific fix-attempt ledger existed before this file.
- Use this log going forward to capture failed schema/model contract changes so future turns avoid repeating them.
