---
summary: "Unstructured EPUB adapter behavior, traceability fields, and integration flow."
read_when:
  - When debugging or modifying unstructured EPUB extraction
  - When reconciling extractor settings between CLI and importer paths
---

# Unstructured EPUB Adapter

## How it works

Unstructured is the default EPUB extractor. Configurable via interactive Settings menu (`EPUB Extractor`) or `--epub-extractor legacy` CLI flag or `C3IMP_EPUB_EXTRACTOR` env var.

**Data flow**: EPUB spine HTML → `partition_html()` → Unstructured Elements → `partition_html_to_blocks()` adapter → Blocks (with traceability features) → `signals.enrich_block()` → `assign_block_roles()` → downstream segmentation.

## Key files

- `cookimport/parsing/unstructured_adapter.py` — Element→Block mapping + diagnostics JSONL generation
- `cookimport/parsing/block_roles.py` — Deterministic role assignment (recipe_title, ingredient_line, instruction_line, tip_like, narrative, metadata, section_heading, other)
- `cookimport/plugins/epub.py` — Extractor switch (env var `C3IMP_EPUB_EXTRACTOR`), wired into both ebooklib and zip extraction paths

## Traceability features on each Block

`unstructured_element_id`, `unstructured_element_index`, `unstructured_stable_key`, `unstructured_category`, `unstructured_category_depth`, `unstructured_parent_id`, `source_location_id`

## Artifacts

When enabled, emits `unstructured_elements.jsonl` as a RawArtifact (one JSON object per line, per element).

## Tests

`tests/test_unstructured_adapter.py` — 26 tests covering adapter mapping, split-spine merge, and block roles.
