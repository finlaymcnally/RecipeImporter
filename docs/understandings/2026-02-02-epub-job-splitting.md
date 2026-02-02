---
summary: "Notes on EPUB job splitting and spine-index ordering for merges."
read_when:
  - When modifying EPUB job splitting or merge ordering
---

# EPUB Job Splitting Notes (2026-02-02)

- EPUB blocks are emitted as a linear list with `start_block`/`end_block` provenance indices, so split jobs need a stable global ordering key.
- Each spine item is processed with a `spine_index` feature on blocks, and recipe provenance records `start_spine`/`end_spine` so merge ordering can sort by spine index before local block indices.
- Split jobs write raw artifacts into `.job_parts/<workbook>/job_<index>/raw/`, then the main merge step moves them into `raw/` and rewrites recipe IDs to a single global sequence.
