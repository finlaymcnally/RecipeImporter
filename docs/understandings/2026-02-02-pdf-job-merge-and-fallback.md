---
summary: "Notes on PDF job merge ordering, ID rewrites, and serial fallback behavior."
read_when:
  - When modifying PDF job merging or troubleshooting job-split staging runs
---

# PDF Job Merge and Fallback Notes (2026-02-02)

- Split PDF jobs return `ConversionResult` payloads without raw artifacts; the main process merges recipes, tip candidates, topic candidates, and non-recipe blocks, then recomputes tips and chunks before writing outputs.
- Recipe IDs are rewritten to a global `c0..cN` sequence ordered by `provenance.location.start_page` (falling back to `start_block`), and any tip `sourceRecipeId` references are updated via the same mapping.
- Raw artifacts are written under `.job_parts/<workbook_slug>/job_<index>/raw/` during job execution, then moved into `raw/` with filename prefixing on collisions once the merge completes.
- If `ProcessPoolExecutor` fails to initialize (PermissionError), staging falls back to serial job execution so CLI/test runs can still complete.
