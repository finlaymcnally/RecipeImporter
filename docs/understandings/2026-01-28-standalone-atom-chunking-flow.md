---
summary: "Standalone EPUB/PDF tip extraction now uses container → atom chunking with per-atom provenance context."
read_when:
  - When debugging standalone tip extraction or topic_candidates output
---

# Standalone container → atom flow (EPUB/PDF)

Standalone blocks outside recipe ranges are grouped into containers via `cookimport/parsing/tips.py::chunk_standalone_blocks` (header + anchor overlap). Each container is then split into atoms using `cookimport/parsing/atoms.py` and processed per-atom in `cookimport/plugins/epub.py` and `cookimport/plugins/pdf.py`.

Key behaviors:
- Each atom becomes a `TopicCandidate` with provenance that includes `location.start_block`/`end_block` and an `atom` payload (`index`, `kind`, `block_index`, `context_prev`, `context_next`).
- Tips are extracted per atom with `extract_tip_candidates`, using `header_hint` from the container header to preserve header-based classification without re-merging text.
- Container headers are kept as `topic_header` in provenance and are emitted as header atoms for coverage, but header atoms are skipped for tip extraction.
