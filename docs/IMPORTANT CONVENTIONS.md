---
summary: "Cross-cutting convention index pointing to code-adjacent convention docs."
read_when:
  - "When looking for hidden rules; start here to find the code-local convention file"
  - "When adding a new convention and deciding where it should live"
---

# Important Conventions

Most durable conventions now live next to the code they govern.
This file is now an index, not a long rule dump.

## Code-Adjacent Convention Files

- `cookimport/CONVENTIONS.md` — CLI discovery/runtime behavior and dependency-resolution notes.
- `cookimport/config/CONVENTIONS.md` — Run-settings source-of-truth and propagation contracts.
- `cookimport/labelstudio/CONVENTIONS.md` — Label Studio prelabel/task/export contracts.
- `cookimport/staging/CONVENTIONS.md` — Stage report and section-artifact output contracts.
- `cookimport/plugins/CONVENTIONS.md` — Ingestion split/merge and extractor contracts.
- `cookimport/bench/CONVENTIONS.md` — Benchmark scoring/orchestration contracts.
- `cookimport/analytics/CONVENTIONS.md` — Analytics/dashboard caveats and history contracts.
- `tests/CONVENTIONS.md` — Test modularity and low-noise pytest contracts.

## Recent Cross-Cutting Update

- Benchmark scoring now uses stage block evidence manifests (`.bench/<workbook_slug>/stage_block_predictions.json`) rather than pipeline chunk span overlap. See `cookimport/bench/CONVENTIONS.md` and `cookimport/staging/CONVENTIONS.md`.
- Label Studio import/export/eval are freeform-only (`freeform-spans`); legacy `pipeline` and `canonical-blocks` scopes are rejected in current workflows. See `cookimport/CONVENTIONS.md` and `cookimport/labelstudio/CONVENTIONS.md`.

## Adding New Conventions

When you discover a new durable rule:

1. Write it in the nearest code folder (`<folder>/CONVENTIONS.md`) first.
2. Add that folder-level conventions file if it does not exist yet.
3. Update this index only if a new conventions file/path should be discoverable here.
