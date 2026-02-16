---
summary: "Staging/output reference for intermediate drafts, final drafts, writer behavior, and staging contracts."
read_when:
  - When changing output paths, filenames, or report artifacts
  - When modifying draft-v1 conversion or staging contract invariants
---

# Staging Section Reference

Staging transforms importer results into persisted artifacts under `data/output/<timestamp>/`.

## Core code

- `cookimport/staging/jsonld.py`: intermediate schema.org Recipe JSON
- `cookimport/staging/draft_v1.py`: final cookbook3 draft shaping (`RecipeDraftV1`)
- `cookimport/staging/writer.py`: output writers for drafts, tips, chunks, raw artifacts, reports
- `cookimport/staging/pdf_jobs.py`: split-job planning helpers and ID reassignment support

## Output surfaces

- `intermediate drafts/<workbook>/r{index}.jsonld`
- `final drafts/<workbook>/r{index}.json`
- `tips/<workbook>/...`
- `chunks/<workbook>/...`
- `raw/<importer>/<source_hash>/...`
- `<workbook>.excel_import_report.json` at run root

## Contract and naming notes

- Staging contract alignment task note:
  `docs/05-staging/2026-02-12_10.41.48-staging-contract-alignment.md`
- Edge-case contract constraints:
  `docs/05-staging/2026-02-12_10.41.48-staging-contract-edge-cases.md`
- Format naming conventions used in docs/CLI text:
  `docs/05-staging/2026-02-12_10.25.47-format-naming-conventions.md`

## Related docs

- Ingestion merge/split behavior that feeds staging:
  `docs/03-ingestion/README.md`
- Parsing logic invoked during draft-v1 conversion:
  `docs/04-parsing/README.md`
