---
summary: "Text/PDF/EPUB outputs overwrite when row_index is missing."
read_when:
  - When debugging missing/overwritten outputs for non-Excel importers
---

Text, PDF, and EPUB importers store candidate positions under provenance.location (chunk_index, start/end blocks/lines) rather than top-level row_index. The staging writer originally used only row_index for filenames, so multiple candidates would overwrite r0. Outputs are now flattened per source file and named by sequential index, while stable IDs still fall back to location.chunk_index when row_index is missing.
