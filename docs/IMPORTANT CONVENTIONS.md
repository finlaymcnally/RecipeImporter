---
summary: "Project-wide coding and organization conventions for the import tooling."
read_when:
  - Before starting any new implementation
  - When organizing output folders or defining new models
---

# Important Conventions

- The import tooling lives in the Python package `cookimport/`, with the CLI entrypoint exposed as the `cookimport` script via `pyproject.toml`.
- Core shared models are defined in `cookimport/core/models.py`, and staging JSON-LD helpers live in `cookimport/staging/`.
- Staging output folders use workbook stems (no file extension) for `intermediate drafts/<workbook>/...`, `final drafts/<workbook>/...`, and report names, while provenance still records the full filename.
- Outputs are flattened per source file (no sheet subfolders) and named `r{index}.json[ld]` in the order recipes are emitted.
- Stable IDs still derive from provenance (`row_index`/`rowIndex` for Excel, `location.chunk_index` for non-tabular importers).
